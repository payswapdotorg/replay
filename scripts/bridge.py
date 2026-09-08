#!/usr/bin/env python3
"""bridge.py — CDP bridge for the Next.js operator console.

Usage:
  bridge.py frame [taburl]        -> JPEG screenshot bytes on stdout
  bridge.py event <json>          -> inject input (click/type/key) into a tab
  bridge.py status                -> JSON program status (GitHub + local)
"""
import base64
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import channel


def active_tab_id():
    try:
        return open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "flags/active_tab.txt")).read().strip()
    except Exception:
        return ""


def pick_tab(pattern=None):
    tabs = channel.list_tabs()
    aid = active_tab_id()
    if aid:
        for t in tabs:
            if t.get("id") == aid:
                return t
    if pattern:
        t = channel.find_tab(pattern)
        if t:
            return t
    for t in tabs:
        if "chat.z.ai" in (t.get("url") or ""):
            return t
    return tabs[0] if tabs else None


def cmd_tabs():
    tabs = channel.list_tabs()
    aid = active_tab_id()
    if aid and not any(t.get("id") == aid for t in tabs):
        aid = ""
    if not aid:
        t = pick_tab()
        aid = (t or {}).get("id", "")
    # detect new tabs vs last listing (for auto-focus of login popups)
    base = os.path.dirname(os.path.abspath(__file__))
    seen_path = os.path.join(base, "flags/tabs_seen.json")
    try:
        seen = set(json.loads(open(seen_path).read()))
    except Exception:
        seen = set()
    cur = {t["id"] for t in tabs}
    fresh = [t["id"] for t in tabs if t["id"] not in seen and (t.get("url") or "") not in ("", "about:blank")]
    try:
        open(seen_path, "w").write(json.dumps(sorted(cur)))
    except Exception:
        pass
    out = {
        "active": aid,
        "new": fresh,
        "tabs": [{"id": t["id"], "title": (t.get("title") or "")[:70], "url": (t.get("url") or "")[:140]} for t in tabs],
    }
    print(json.dumps(out))
    return 0


def cmd_frame():
    tab = pick_tab(os.environ.get("FRAME_TAB"))
    if not tab:
        sys.stdout.buffer.write(b"")
        return 1
    cdp = channel.CDP(tab["webSocketDebuggerUrl"], timeout=30)
    try:
        cdp.call("Page.enable", {})
        # capture the full viewport
        r = cdp.call("Page.captureScreenshot", {"format": "jpeg", "quality": 75}, timeout=30)
        data = base64.b64decode(r.get("data", ""))
        sys.stdout.buffer.write(data)
        return 0
    finally:
        cdp.close()


def _viewport_size(cdp):
    """CSS size of the visible viewport — the single source of truth for
    mapping replay-image fractions to real page coordinates."""
    try:
        r = cdp.call("Page.getLayoutMetrics", {}, timeout=10)
        m = r.get("cssVisualViewport") or {}
        w = float(m.get("clientWidth") or 0)
        h = float(m.get("clientHeight") or 0)
        if w > 50 and h > 50:
            return w, h
        m = r.get("cssLayoutViewport") or {}
        return float(m.get("clientWidth") or 1440), float(m.get("clientHeight") or 756)
    except Exception:
        return 1440.0, 756.0


def _resolve_pt(payload, cdp, keys=("x", "y")):
    """Accept fractional (fx/fy in 0..1 of the viewport) or absolute coords.
    Fractions are the robust path: the server maps them with the live viewport
    size, so no client-side image-natural-size assumptions can skew clicks."""
    if "fx" in payload and "fy" in payload:
        w, h = _viewport_size(cdp)
        return float(payload["fx"]) * w, float(payload["fy"]) * h
    kx, ky = keys
    return float(payload[kx]), float(payload[ky])


_PROBE_JS = """(function(){
  var X=%f, Y=%f;
  function clickable(el){var n=el;for(var i=0;i<6&&n;i++){var t=(n.tagName||'').toUpperCase();
    if(t==='A'||t==='BUTTON'||t==='TEXTAREA'||t==='SELECT'||n.getAttribute('role')==='button'||n.onclick||
       (t==='INPUT'))return n;
    n=n.parentElement;}return null;}
  function describe(el){if(!el)return null;var t=((el.innerText||el.value||el.placeholder||el.getAttribute('aria-label')||'')+'').trim().slice(0,60);
    return {tag:(el.tagName||'').toLowerCase(),id:el.id||'',cls:(''+(el.className||'')).slice(0,50),text:t};}
  function tryPt(x,y){var els=document.elementsFromPoint?document.elementsFromPoint(x,y):[document.elementFromPoint(x,y)];
    for(var i=0;i<els.length;i++){var c=clickable(els[i]);if(c)return describe(c);}return null;}
  var off=[[0,0]];
  var ds=[4,8,12,16,20,24];
  for(var j=0;j<ds.length;j++){var d=ds[j];off.push([d,0],[-d,0],[0,d],[0,-d],[d,d],[-d,d],[d,-d],[-d,-d]);}
  for(var k=0;k<off.length;k++){var r=tryPt(X+off[k][0],Y+off[k][1]);if(r){r.dx=off[k][0];r.dy=off[k][1];return r;}}
  var top=document.elementFromPoint(X,Y);
  var d2=describe(top);if(d2){d2.dx=0;d2.dy=0;return d2;}
  return {tag:'none',text:'',dx:0,dy:0};
})()"""


_DOMCLICK_JS = """(function(){
  var X=%f, Y=%f;
  function clickable(el){var n=el;for(var i=0;i<6&&n;i++){var t=(n.tagName||'').toUpperCase();
    if(t==='A'||t==='BUTTON'||t==='TEXTAREA'||t==='SELECT'||n.getAttribute('role')==='button'||n.onclick||
       (t==='INPUT'))return n;
    n=n.parentElement;}return null;}
  function findAt(x,y){var els=document.elementsFromPoint?document.elementsFromPoint(x,y):[document.elementFromPoint(x,y)];
    for(var i=0;i<els.length;i++){var c=clickable(els[i]);if(c)return c;}return document.elementFromPoint(x,y);}
  var off=[[0,0]];
  var ds=[4,8,12,16,20,24];
  for(var j=0;j<ds.length;j++){var d=ds[j];off.push([d,0],[-d,0],[0,d],[0,-d],[d,d],[-d,d],[d,-d],[-d,-d]);}
  var el=null,dx=0,dy=0;
  for(var k=0;k<off.length&&!el;k++){el=findAt(X+off[k][0],Y+off[k][1]);dx=off[k][0];dy=off[k][1];}
  if(!el)return {ok:false,target:{tag:'none',text:''}};
  var t=((el.innerText||el.value||el.getAttribute('aria-label')||'')+'').trim().slice(0,60);
  var desc={tag:(el.tagName||'').toLowerCase(),text:t,dx:dx,dy:dy};
  try{if(/^(input|textarea|select)$/i.test(el.tagName)){el.focus();if(el.setSelectionRange)el.setSelectionRange(el.value.length,el.value.length);}}catch(e){}
  try{el.click();}catch(e){return {ok:false,target:desc,err:''+e};}
  return {ok:true,target:desc};
})()"""


def _out(obj):
    """Print a compact JSON result line for the API layer to pass through."""
    try:
        print(json.dumps(obj))
    except Exception:
        print('{"ok":true}')


def cmd_event(payload):
    tab = pick_tab()
    if not tab:
        _out({"ok": False, "error": "no-tab"})
        return 1
    cdp = channel.CDP(tab["webSocketDebuggerUrl"], timeout=30)
    try:
        kind = payload.get("type")
        if kind == "click":
            x, y = _resolve_pt(payload, cdp)
            target = None
            try:
                target = cdp.eval(_PROBE_JS % (x, y), timeout=12)
            except Exception:
                pass
            # real input path: hover -> press -> release (proven with React apps)
            try:
                cdp.call("Input.dispatchMouseEvent", {
                    "type": "mouseMoved", "x": x, "y": y})
            except Exception:
                pass
            for typ in ("mousePressed", "mouseReleased"):
                cdp.call("Input.dispatchMouseEvent", {
                    "type": typ, "x": x, "y": y, "button": "left", "clickCount": 1,
                    "buttons": 1})
            _out({"ok": True, "kind": "click", "x": round(x), "y": round(y), "target": target})
        elif kind == "domclick":
            x, y = _resolve_pt(payload, cdp)
            res = cdp.eval(_DOMCLICK_JS % (x, y), timeout=12) or {"ok": False}
            res["kind"] = "domclick"
            res["x"] = round(x)
            res["y"] = round(y)
            _out(res)
        elif kind == "dblclick":
            x, y = _resolve_pt(payload, cdp)
            for typ in ("mousePressed", "mouseReleased", "mousePressed", "mouseReleased"):
                cdp.call("Input.dispatchMouseEvent", {
                    "type": typ, "x": x, "y": y, "button": "left",
                    "clickCount": 2, "buttons": 1})
            _out({"ok": True, "kind": "dblclick", "x": round(x), "y": round(y)})
        elif kind == "move":
            x, y = _resolve_pt(payload, cdp)
            cdp.call("Input.dispatchMouseEvent", {
                "type": "mouseMoved", "x": x, "y": y})
            _out({"ok": True, "kind": "move"})
        elif kind == "key":
            cdp.call("Input.dispatchKeyEvent", {
                "type": "char", "text": payload.get("text", "")})
            _out({"ok": True, "kind": "key"})
        elif kind == "enter":
            for typ in ("keyDown", "keyUp"):
                cdp.call("Input.dispatchKeyEvent", {
                    "type": typ, "key": "Enter", "code": "Enter",
                    "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13})
            _out({"ok": True, "kind": "enter"})
        elif kind == "type":
            cdp.call("Input.insertText", {"text": payload.get("text", "")})
            _out({"ok": True, "kind": "type"})
        elif kind == "scroll":
            x, y = _resolve_pt(payload, cdp)
            cdp.call("Input.dispatchMouseEvent", {
                "type": "mouseWheel", "x": x, "y": y,
                "deltaX": 0, "deltaY": float(payload.get("deltaY", 120))})
            _out({"ok": True, "kind": "scroll"})
        elif kind == "drag":
            import time as _time
            w, h = _viewport_size(cdp)
            if "fromFx" in payload:
                fx, fy = float(payload["fromFx"]) * w, float(payload["fromFy"]) * h
            else:
                fx, fy = float(payload.get("fromX", 0)), float(payload.get("fromY", 0))
            if "toFx" in payload:
                tx, ty = float(payload["toFx"]) * w, float(payload["toFy"]) * h
            else:
                tx, ty = float(payload.get("toX", 0)), float(payload.get("toY", 0))
            steps = max(2, int(payload.get("steps", 14)))
            cdp.call("Input.dispatchMouseEvent", {
                "type": "mousePressed", "x": fx, "y": fy, "button": "left", "clickCount": 1,
                "buttons": 1})
            for i in range(1, steps + 1):
                t = i / steps
                cdp.call("Input.dispatchMouseEvent", {
                    "type": "mouseMoved", "x": fx + (tx - fx) * t, "y": fy + (ty - fy) * t,
                    "button": "left", "buttons": 1})
                _time.sleep(0.035)
            cdp.call("Input.dispatchMouseEvent", {
                "type": "mouseReleased", "x": tx, "y": ty, "button": "left", "clickCount": 1,
                "buttons": 1})
            _out({"ok": True, "kind": "drag",
                  "from": [round(fx), round(fy)], "to": [round(tx), round(ty)]})
        elif kind == "nav":
            cdp.call("Page.navigate", {"url": payload.get("url", "https://chat.z.ai/")})
            _out({"ok": True, "kind": "nav"})
        elif kind == "reload":
            try:
                cdp.call("Page.reload", {"ignoreCache": True})
            except Exception:
                cdp.call("Page.navigate", {"url": cdp.eval("location.href") or "https://chat.z.ai/"})
            _out({"ok": True, "kind": "reload"})
        elif kind == "dialog":
            try:
                cdp.call("Page.handleJavaScriptDialog", {"accept": True})
            except Exception:
                pass
            _out({"ok": True, "kind": "dialog"})
        return 0
    finally:
        cdp.close()


def _env_conf():
    """Optional runtime config from scripts/env.sh (gitignored, no secrets
    in the repo). Recognized: REPO=owner/name, OPERATOR_PAT=ghp_... (only
    needed for private repos or API rate limits)."""
    conf = {"repo": "", "pat": ""}
    import re
    try:
        env = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "env.sh")).read()
        m = re.search(r"^\s*(?:export\s+)?REPO=([\w./-]+)", env, re.M)
        if m:
            conf["repo"] = m.group(1).strip().strip("\"'")
        m = re.search(r"^\s*(?:export\s+)?(?:OPERATOR_PAT|GITHUB_TOKEN)=(ghp_\w+)", env, re.M)
        if m:
            conf["pat"] = m.group(1)
    except Exception:
        pass
    if not conf["repo"]:
        conf["repo"] = os.environ.get("REPO", "")
    if not conf["pat"]:
        p = os.environ.get("OPERATOR_PAT") or os.environ.get("GITHUB_TOKEN") or ""
        if p.startswith("ghp_"):
            conf["pat"] = p
    return conf


def gh(repo, path, token=""):
    hdr = ["-H", f"Authorization: token {token}"] if token else []
    r = subprocess.run(["curl", "-s", "--max-time", "10", *hdr,
                        f"https://api.github.com/repos/{repo}{path}"],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}


def _login_state(tab):
    """Generic login heuristic: a visible composer means a session exists;
    a 'Sign in' affordance means logged out."""
    cdp = channel.CDP(tab["webSocketDebuggerUrl"], timeout=10)
    try:
        body = cdp.eval("document.body.innerText || ''", timeout=8) or ""
        has_composer = cdp.eval(
            "!!document.querySelector('textarea, #chat-input, div[contenteditable=true]')",
            timeout=6)
        if "Sign in" in body or "Log in" in body:
            return "logged-out"
        if has_composer:
            return "logged-in"
        return "page:" + str(len(body))
    finally:
        cdp.close()


def cmd_status():
    conf = _env_conf()
    out = {
        "ts": __import__("time").strftime("%Y-%m-%d %H:%M:%S UTC"),
        "repo": conf["repo"],
        "browser_login": "unknown",
    }
    try:
        tab = pick_tab()
        if tab:
            out["browser_login"] = _login_state(tab)
    except Exception:
        out["browser_login"] = "no-browser"
    if conf["repo"]:
        try:
            brs = gh(conf["repo"], "/branches?per_page=50", conf["pat"])
            blist = [{"name": b.get("name"), "sha": b.get("commit", {}).get("sha", "")[:10]}
                     for b in (brs if isinstance(brs, list) else [])]
            pulls = gh(conf["repo"], "/pulls?state=all&per_page=20", conf["pat"])
            prs = [{"n": p.get("number"), "state": p.get("state"),
                    "title": (p.get("title") or "")[:60]}
                   for p in (pulls if isinstance(pulls, list) else [])]
            out["main_sha"] = next((b["sha"] for b in blist if b["name"] == "main"), "?")
            out["branches"] = blist
            out["pulls"] = prs
        except Exception:
            pass
    print(json.dumps(out))
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "frame":
        return cmd_frame()
    if cmd == "event":
        return cmd_event(json.loads(sys.argv[2] if len(sys.argv) > 2 else "{}"))
    if cmd == "tabs":
        return cmd_tabs()
    if cmd == "status":
        return cmd_status()
    print("unknown command", cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
