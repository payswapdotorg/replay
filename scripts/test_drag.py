#!/usr/bin/env python3
"""test_drag.py — E2E test of the streamed drag pipeline (replayd :3100).

Opens a data: URL test page in a NEW tab, points active_tab at it, streams
dragstart/dragmove/dragend through the daemon, and verifies the page received
trusted pointer events at the right coordinates (press -> held moves ->
release). Restores the previous active tab and closes the test tab after.
"""
import base64
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import channel

DAEMON = os.environ.get("REPLAYD_URL") or "http://127.0.0.1:" + os.environ.get("REPLAYD_PORT", "3100")
FLAGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flags")

TEST_HTML = b"""<!doctype html><html><head><title>dragtest</title></head>
<body style="margin:0">
<div id="d" style="position:fixed;inset:0;background:#eef;font:13px monospace;white-space:pre"></div>
<script>
window.L=[];
function rec(e){window.L.push(e.type+" "+Math.round(e.clientX)+","+Math.round(e.clientY)+" b="+e.buttons);}
["pointerdown","pointermove","pointerup","mousedown","mousemove","mouseup"].forEach(function(t){addEventListener(t,rec,true);});
addEventListener("pointermove",function(){document.getElementById("d").textContent=window.L.slice(-8).join("\\n");},true);
</script></body></html>"""

DATA_URL = "data:text/html;charset=utf-8;base64," + base64.b64encode(TEST_HTML).decode()


def post(path, obj):
    req = urllib.request.Request(DAEMON + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def main():
    prev_active = ""
    try:
        prev_active = open(FLAGS + "/active_tab.txt").read().strip()
    except Exception:
        pass
    tab = channel.new_tab("about:blank")
    if not tab:
        print("FAIL: cannot open test tab")
        return 1
    tid = tab["id"]
    try:
        cdp = channel.CDP(tab["webSocketDebuggerUrl"], timeout=15)
        try:
            cdp.call("Page.enable", {})
            cdp.call("Page.navigate", {"url": DATA_URL})
            time.sleep(1.2)
            open(FLAGS + "/active_tab.txt", "w").write(tid)
            time.sleep(0.3)

            t0 = time.time()
            r1 = post("/event", {"type": "dragstart", "fx": 0.20, "fy": 0.50})
            r2 = post("/event", {"type": "dragmove", "fx": 0.35, "fy": 0.50})
            r3 = post("/event", {"type": "dragmove", "fx": 0.50, "fy": 0.51})
            r4 = post("/event", {"type": "dragend", "fx": 0.60, "fy": 0.50})
            dt = (time.time() - t0) * 1000
            print(f"4 streamed events total: {dt:.0f}ms ({dt/4:.1f}ms each)")
            for r in (r1, r2, r3, r4):
                print("  ", r)

            time.sleep(0.5)
            m = cdp.call("Page.getLayoutMetrics", {})
            v = m.get("cssVisualViewport") or {}
            w = float(v.get("clientWidth") or 1440)
            h = float(v.get("clientHeight") or 756)
            log = cdp.eval("window.L.join(';')", timeout=8) or ""
            entries = [e for e in log.split(";") if e]
            pdowns = [e for e in entries if e.startswith("pointerdown")]
            pmoves = [e for e in entries if e.startswith("pointermove") and "b=1" in e]
            pups = [e for e in entries if e.startswith("pointerup")]

            def xof(e):
                return float(e.split(" ")[1].split(",")[0])

            print(f"viewport {w:.0f}x{h:.0f}; captured {len(entries)} events")
            print("events:", log[:500])

            checks = {
                "pointerdown at start (+-4px)": bool(pdowns) and abs(xof(pdowns[0]) - 0.20 * w) <= 4,
                ">=2 live moves with button held (b=1)": len(pmoves) >= 2,
                "pointerup at end (+-4px)": bool(pups) and abs(xof(pups[-1]) - 0.60 * w) <= 4,
                "mouse-event pipeline also fired": "mousedown" in log and "mouseup" in log,
            }
            npass = 0
            for k, val in checks.items():
                print(("PASS " if val else "FAIL ") + k)
                npass += 1 if val else 0
            return 0 if npass == len(checks) else 1
        finally:
            cdp.close()
    finally:
        if prev_active:
            try:
                open(FLAGS + "/active_tab.txt", "w").write(prev_active)
            except Exception:
                pass
        try:
            urllib.request.urlopen(f"http://127.0.0.1:9222/json/close/{tid}", timeout=5).read()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
