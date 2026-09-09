#!/usr/bin/env python3
"""release_sandboxes.py — release stale agent sandboxes blocking the sandbox limit.

The 'Limit Sandbox Concurrency' modal appears on a session page when active
sandboxes exceed the limit. Each Release click may auto-dismiss the modal;
reload to bring it back until no modal appears (limit satisfied).

Robust version: every round opens a FRESH CDP connection; all evals retried.
"""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import channel

KEEP = set()  # sandbox names to keep (none by default)

MODAL_JS = r"""(() => {
  const el = Array.from(document.querySelectorAll('div,section,[role=dialog]'))
    .find(e => (e.innerText||'').includes('Limit Sandbox Concurrency'));
  if (!el) return JSON.stringify({present: false});
  const rows = [];
  el.querySelectorAll('button').forEach(b => {
    if ((b.innerText||'').trim() === 'Release') {
      const row = b.closest('tr, div');
      rows.push({name: row ? (row.innerText||'').split('\n')[0].substring(0,60) : '?'});
    }
  });
  return JSON.stringify({present: true, rows: rows});
})()"""

CLICK_JS = r"""(() => {
  const el = Array.from(document.querySelectorAll('div,section,[role=dialog]'))
    .find(e => (e.innerText||'').includes('Limit Sandbox Concurrency'));
  if (!el) return 'modal-gone';
  const btns = Array.from(el.querySelectorAll('button'))
    .filter(b => (b.innerText||'').trim() === 'Release');
  if (!btns.length) return 'no-buttons';
  btns[0].click();
  return 'clicked';
})()"""


def find_tab_by_url(substr):
    for t in channel.list_tabs():
        if substr in (t.get("url") or ""):
            return t
    return None


def _conn(tab):
    for t in channel.list_tabs():
        if t["id"] == tab["id"]:
            return channel.CDP(t["webSocketDebuggerUrl"], timeout=45)
    raise RuntimeError("tab gone")


def robust_eval(tab, js, tries=4, timeout=20):
    last = None
    for _ in range(tries):
        c = None
        try:
            c = _conn(tab)
            return c.eval(js, timeout=timeout), c
        except Exception as e:
            last = e
            time.sleep(2)
        finally:
            if c and _ != tries - 1:
                try:
                    c.close()
                except Exception:
                    pass
    raise RuntimeError(f"eval failed: {last!r}")


def run(session_substr):
    tab = find_tab_by_url(session_substr)
    if not tab:
        print("no tab matching", session_substr)
        return 1
    for round_ in range(10):
        st, c = robust_eval(tab, MODAL_JS)
        st = json.loads(st or '{}')
        if not st.get("present"):
            print(f"[round {round_}] modal gone — limit satisfied")
            return 0
        rows = st.get("rows") or []
        print(f"[round {round_}] modal present, {len(rows)} release button(s): "
              + ", ".join(r["name"] for r in rows))
        if not rows:
            print("modal present but no Release buttons — inspect manually")
            return 2
        target = None
        for r in rows:
            if not any(k in r["name"] for k in KEEP):
                target = r
                break
        if target is None:
            print("only KEEP sandboxes remain — not releasing")
            return 0
        res, c2 = robust_eval(tab, CLICK_JS)
        print(f"  release click: {res} (target: {target['name']})")
        time.sleep(3)
        # modal state after the click
        try:
            st2, _ = robust_eval(tab, MODAL_JS, tries=2)
            st2 = json.loads(st2 or '{}')
        except Exception:
            st2 = {"present": True}
        if not st2.get("present"):
            print("  modal closed — reloading to re-check ...")
            try:
                c2.call("Page.reload", {}, timeout=30)
            except Exception:
                pass
            time.sleep(7)
    print("too many rounds — manual inspection needed")
    return 2


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "23a808db"))
