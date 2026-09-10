#!/usr/bin/env python3
"""monitor_worker.py — resident monitor for the WO-049 worker session.

Polls the session tab every ~48s with periodic Page.reload (the session DOM
goes stale after capacity fights — reload re-syncs with the server).
Detects:
  - turn activity (body length growth)
  - the true completion report marker (=== WORK-048 COMPLETION REPORT ===)
    ONLY in the last ASSISTANT message (user messages quoting it are ignored)
Writes probes to scripts/logs/monitor_worker.log; writes
scripts/flags/worker_report.json when the report is detected.
Usage: monitor_worker.py <session-name> [minutes]
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, "/home/z/my-project/scripts")
import channel  # noqa: E402

BASE = "/home/z/my-project/scripts"
LOG = f"{BASE}/logs/monitor_worker.log"
FLAG = f"{BASE}/flags/worker_report.json"
REG = f"{BASE}/flags/session_registry.jsonl"


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _session(name):
    regs = [json.loads(l) for l in open(REG) if l.strip()]
    s = None
    for r in regs:
        if r.get("name") == name and r.get("tab_id"):
            s = r
    return s


def _connect(s):
    tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json").read())
    tab = next((t for t in tabs if t.get("id") == s["tab_id"]), None)
    if not tab:
        want = (s.get("url") or "").rsplit("/", 1)[-1]
        tab = next((t for t in tabs if want and want in (t.get("url") or "")), None)
    if not tab:
        return None
    return channel.CDP(tab["webSocketDebuggerUrl"], timeout=30)


PROBE_JS_TEMPLATE = r"""(() => {
  const body = document.body.innerText||'';
  const msgs = Array.from(document.querySelectorAll('[class*="chat-user"], [class*="chat-assistant"]'));
  const last = msgs[msgs.length-1];
  const isAssist = last ? last.className.toString().includes('chat-assistant') : false;
  const txt = last ? (last.innerText||'').replace(/\s+/g,' ') : '';
  const report = isAssist && /=== *WORK-%WO% COMPLETION REPORT *===/.test(txt);
  const busy = Array.from(document.querySelectorAll('button'))
    .some(b => /^(Stop|Pause|Halt)$/i.test((b.innerText||'').trim()));
  return JSON.stringify({len: body.length, n: msgs.length, report, isAssist, busy,
    tail: txt.slice(-100)});
})()"""


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "WO-049"
    minutes = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    wo = name.replace("WO-", "").replace("wo-", "").replace("WORK-", "")
    probe_js = PROBE_JS_TEMPLATE.replace("%WO%", wo)
    s = _session(name)
    if not s:
        log(f"no session {name}")
        return 4
    c = _connect(s)
    if not c:
        log(f"tab LOST for {name}")
        return 4
    log(f"monitor start {name} tab={s['tab_id'][:8]} for {minutes}m")
    last_len = 0
    deadline = time.time() + minutes * 60
    n = 0
    while time.time() < deadline:
        try:
            if n % 3 == 0 and n > 0:
                try:
                    c.call("Page.reload", {"ignoreCache": True})
                    time.sleep(6)
                except Exception:
                    pass
            st = json.loads(c.eval(probe_js, timeout=25))
            growth = "+" if st["len"] > last_len else ("=" if st["len"] == last_len else "-")
            log(f"len={st['len']} {growth} msgs={st['n']} REPORT={st['report']} | ...{st['tail'][:80]}")
            last_len = st["len"]
            if st["report"]:
                log("=== COMPLETION REPORT DETECTED (assistant message) ===")
                with open(FLAG, "w") as f:
                    json.dump({"ts": int(time.time() * 1000), "name": name,
                               "detected": True}, f)
                return 0
        except Exception as e:
            log(f"probe error: {e}; reconnecting")
            try:
                c.close()
            except Exception:
                pass
            time.sleep(5)
            c = _connect(s)
            if not c:
                log("reconnect failed; retry in 30s")
                time.sleep(30)
        n += 1
        time.sleep(48)
    log("monitor window elapsed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
