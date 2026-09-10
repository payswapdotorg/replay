#!/usr/bin/env python3
"""patience_send.py — retry a message on a session until the site recovers.

Site-wide send outages return an HTML error page (JSON parse error banner)
and roll the message back. This script types + sends + verifies, once per
invocation; call it in a loop from the resident operator.
Usage: patience_send.py <session-name> <message-file>
Exit: 0 = landed; 1 = rolled back / error.
"""
import json
import re
import sys
import time

sys.path.insert(0, "/home/z/my-project/scripts")
import channel
from monitor_worker import _session, _connect

BASE = "/home/z/my-project/scripts"


def main():
    name = sys.argv[1]
    msg_file = sys.argv[2]
    msg = open(msg_file, encoding="utf-8").read()

    s = _session(name)
    if not s:
        print("no session record")
        return 1
    c = _connect(s)
    if not c:
        print("no tab")
        return 1

    def eval_js(js):
        r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
        return r["result"].get("value")

    try:
        # resync first
        try:
            c.call("Page.reload", {"ignoreCache": True}, timeout=30)
            time.sleep(6)
        except Exception:
            pass
        n_before = json.loads(eval_js(
            '(() => { const m = document.querySelectorAll(\'[class*="chat-user"], [class*="chat-assistant"]\'); return JSON.stringify({n: m.length}); })()'
        ))["n"]

        typed = eval_js("""(() => {
          const ta = document.querySelector('textarea');
          if (!ta) return 0;
          ta.focus();
          const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
          setter.call(ta, %s);
          ta.dispatchEvent(new Event('input', {bubbles: true}));
          return 1;
        })()""" % json.dumps(msg))
        if not typed:
            print("no composer")
            return 1
        time.sleep(2)
        eval_js("""(() => {
          const ta = document.querySelector('textarea');
          let form = ta.closest('form');
          const btns = Array.from((form || document).querySelectorAll('button')).filter(b => !b.disabled);
          if (btns.length) btns[btns.length-1].click();
          return 1;
        })()""")
        time.sleep(30)
        st = json.loads(eval_js(r"""(() => {
          const msgs = Array.from(document.querySelectorAll('[class*="chat-user"], [class*="chat-assistant"]'));
          const last = msgs[msgs.length-1];
          const txt = last ? (last.innerText||'').replace(/\s+/g,' ') : '';
          const ta = document.querySelector('textarea');
          return JSON.stringify({n: msgs.length, comp: ta?ta.value.length:-1, tail: txt.slice(-120)});
        })()"""))
        err = "No response" in st["tail"] or "SyntaxError" in st["tail"]
        print(time.strftime("[%H:%M:%S]"),
              f"n={st['n']} (was {n_before}) comp={st['comp']} err={err}",
              "|", st["tail"][:80], flush=True)
        if err:
            return 1
        if st["n"] > n_before:
            print("LANDED")
            return 0
        return 1
    finally:
        try:
            c.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
