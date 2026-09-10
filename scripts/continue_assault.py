#!/usr/bin/env python3
"""continue_assault.py — in-session capacity assault for a stalled continuation.

Operator policy (2026-09-09, AGENT_BOOT_PROMPT.md rung 9): never wait out a
GLM-5.3 capacity peak — always fight through it. When a continuation `send`
lands on a session whose model is at capacity, the site shows an inline
"Model is currently at capacity" banner and keeps the text in the composer.
This script re-clicks the session's send button round after round (with
backoff, cancelling any modal it meets) until the turn actually starts
(Stop/Pause button appears) or the composer clears AND the transcript grows.

Usage: continue_assault.py <session-name> [max_rounds]
Exit codes: 0 = turn started / submitted; 3 = exhausted; 4 = tab lost.
Logs to scripts/logs/continue_assault.log (also stdout).
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, "/home/z/my-project/scripts")
import channel  # noqa: E402

BASE = "/home/z/my-project/scripts"
REG = f"{BASE}/flags/session_registry.jsonl"


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(f"{BASE}/logs/continue_assault.log", "a") as f:
        f.write(line + "\n")


def _tab_for(name):
    regs = [json.loads(l) for l in open(REG) if l.strip()]
    s = None
    for r in regs:
        if r.get("name") == name and r.get("tab_id"):
            s = r  # last registry record wins (tab-reopen aware)
    if not s:
        return None, None
    tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json").read())
    tab = next((t for t in tabs if t.get("id") == s["tab_id"]), None)
    if not tab:
        # fall back to URL match (session survives server-side)
        want = (s.get("url") or "").rsplit("/", 1)[-1]
        tab = next((t for t in tabs if want and want in (t.get("url") or "")), None)
    return s, tab


def _eval(c, js, timeout=15):
    try:
        return c.eval(js, timeout=timeout)
    except Exception:
        return None


STATE_JS = r"""(() => {
  const busy = Array.from(document.querySelectorAll('button'))
    .some(b => /^(Stop|Pause|Halt)$/i.test((b.innerText||'').trim()));
  const i = document.querySelector('#chat-input, textarea');
  const compLen = i ? (i.value || '').length : -1;
  const body = document.body.innerText || '';
  const banners = (body.match(/Model is currently at capacity/g) || []).length;
  // modal with a Cancel button?
  let modalCancel = null;
  for (const d of document.querySelectorAll('[role=dialog], [class*="modal"]')) {
    if (d.getBoundingClientRect().width > 0) {
      const cb = Array.from(d.querySelectorAll('button'))
        .find(b => /^(Cancel|取消|Close|Dismiss)$/i.test((b.innerText||'').trim()));
      if (cb) {
        const r = cb.getBoundingClientRect();
        modalCancel = {x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)};
        break;
      }
    }
  }
  // the session send button: last enabled button inside the composer form
  let send = null;
  if (i) {
    const form = i.closest('form');
    if (form) {
      const btns = Array.from(form.querySelectorAll('button'))
        .filter(b => !b.disabled && b.getBoundingClientRect().width > 0);
      if (btns.length) {
        const b = btns[btns.length - 1];
        const r = b.getBoundingClientRect();
        send = {x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)};
      }
    }
  }
  return JSON.stringify({busy, compLen, banners, modalCancel, send,
                         bodyLen: body.length});
})()"""


def click(c, x, y):
    for typ in ("mousePressed", "mouseReleased"):
        c.call("Input.dispatchMouseEvent",
               {"type": typ, "x": x, "y": y, "button": "left", "clickCount": 1})


def main():
    name = sys.argv[1]
    max_rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    s, tab = _tab_for(name)
    if not s:
        log(f"no session {name}")
        return 4
    if not tab:
        log(f"tab LOST for {name} (was {s['tab_id'][:8]})")
        return 4
    log(f"assault start: {name} tab={tab['id'][:8]} rounds<={max_rounds}")
    c = channel.CDP(tab["webSocketDebuggerUrl"], timeout=30)
    body_len0 = None
    try:
        for rnd in range(max_rounds):
            st = _eval(c, STATE_JS)
            try:
                st = json.loads(st)
            except Exception:
                st = {}
            busy = st.get("busy")
            comp = st.get("compLen", -1)
            bl = st.get("bodyLen", 0)
            if body_len0 is None:
                body_len0 = bl
            log(f"r{rnd}: busy={busy} compLen={comp} banners={st.get('banners')} "
                f"bodyLen={bl}")
            if busy:
                log("TURN IS GENERATING — assault complete")
                return 0
            if comp == 0 and bl > body_len0 + 50:
                log("composer cleared and transcript grew — submitted; "
                    "waiting a few seconds to confirm turn start")
                time.sleep(8)
                st2 = json.loads(_eval(c, STATE_JS) or "{}")
                if st2.get("busy"):
                    log("turn started after submit")
                    return 0
                body_len0 = bl  # keep reference moving
            # cancel any modal first
            mc = st.get("modalCancel")
            if mc:
                log(f"cancelling modal at {mc['x']},{mc['y']}")
                click(c, mc["x"], mc["y"])
                time.sleep(2)
            # press the send button
            sb = st.get("send")
            if sb:
                log(f"clicking send at {sb['x']},{sb['y']}")
                click(c, sb["x"], sb["y"])
            elif comp and comp > 0:
                # send button locator failed — try Enter on the composer
                log("send button not found; trying Enter")
                for typ in ("keyDown", "keyUp"):
                    c.call("Input.dispatchKeyEvent", {
                        "type": typ, "key": "Enter", "code": "Enter",
                        "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13})
            else:
                log("no composer text and no send button — nothing to do")
                time.sleep(10)
                continue
            # backoff: 12s -> 45s
            delay = min(12 + rnd * 3, 45)
            log(f"sleep {delay}s (backoff)")
            time.sleep(delay)
        log("rounds exhausted")
        return 3
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())
