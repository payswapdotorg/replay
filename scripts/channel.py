#!/usr/bin/env python3
"""channel.py — minimal CDP client for the chat.z.ai automation stack (rebuilt post-sandbox-reset).

Provides: list_tabs, new_tab, find_tab, CDP (eval/call), STATE_JS, send_text.
"""
import json
import os
import time
import urllib.request
import urllib.parse
import websocket

CDP_HTTP = "http://127.0.0.1:" + os.environ.get("CDP_PORT", "9222")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "channel.log")


def _log(*args):
    try:
        with open(LOG, "a") as f:
            f.write(" ".join(str(a) for a in args) + "\n")
    except Exception:
        pass


def _http_json(path, method="GET", timeout=6):
    req = urllib.request.Request(CDP_HTTP + path, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def list_tabs():
    tabs = _http_json("/json/list")
    return [t for t in tabs if t.get("type") == "page"]


def new_tab(url="about:blank"):
    qs = "?" + urllib.parse.urlencode({"url": url})
    for method in ("PUT", "GET"):
        try:
            return _http_json("/json/new" + qs, method=method)
        except Exception:
            continue
    return None


def find_tab(pattern=None):
    tabs = list_tabs()
    if pattern:
        for t in tabs:
            if pattern in t.get("url", ""):
                return t
    for t in tabs:
        if (t.get("url") or "").startswith("https://chat.z.ai"):
            return t
    return tabs[0] if tabs else None


class CDP:
    """Minimal request/response CDP client (skips event frames)."""

    def __init__(self, ws_url, timeout=30):
        self.ws = websocket.create_connection(ws_url, timeout=timeout)
        self._id = 0

    def call(self, method, params=None, timeout=30):
        self._id += 1
        self.ws.settimeout(timeout)
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            raw = self.ws.recv()
            d = json.loads(raw)
            if d.get("id") == self._id:
                if "error" in d:
                    raise RuntimeError(f"cdp error: {d['error']}")
                return d.get("result", {})

    def eval(self, expr, await_promise=False, timeout=30):
        r = self.call("Runtime.evaluate", {
            "expression": expr, "returnByValue": True,
            "awaitPromise": await_promise,
        }, timeout=timeout)
        if r.get("exceptionDetails"):
            raise RuntimeError("js error: " + json.dumps(r.get("exceptionDetails"))[:200])
        v = r.get("result", {}).get("value")
        return v

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


STATE_JS = """(() => {
  const ta = document.querySelector('textarea');
  return JSON.stringify({
    url: location.href,
    bodyLength: (document.body.innerText || '').length,
    composerLength: ta ? ta.value.length : -1,
    generating: !!(document.querySelector('img[class*=loading], [class*=generating], [role=status]')),
    tail: (document.body.innerText || '').slice(-400)
  });
})()"""

CLEAR_JS = """(() => {
  const ta = document.querySelector('textarea');
  if (!ta) return 'no-composer';
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(ta, '');
  ta.dispatchEvent(new Event('input', {bubbles: true}));
  return 'cleared';
})()"""

SUBMIT_JS = """(() => {
  const ta = document.querySelector('textarea');
  if (!ta) return 'no-composer';
  const form = ta.closest('form');
  if (form) { form.requestSubmit ? form.requestSubmit() : form.submit(); return 'form-submit'; }
  const btn = [...document.querySelectorAll('button')].find(b => (b.getAttribute('aria-label') || '').toLowerCase().includes('send'));
  if (btn) { btn.click(); return 'btn-click'; }
  return 'no-submit';
})()"""


def _body_len(cdp):
    try:
        return len(cdp.eval("document.body.innerText || ''", timeout=10) or "")
    except Exception:
        return 0


def _type_into_composer(cdp, text):
    try:
        cdp.eval(CLEAR_JS, timeout=10)
    except Exception:
        pass
    try:
        cdp.call("Input.insertText", {"text": text})
        time.sleep(0.6)
        v = cdp.eval("(document.querySelector('textarea') || {value: ''}).value.length", timeout=10)
        return v and v >= min(len(text), 40)
    except Exception:
        return False


def _proof_of_send(cdp, body_before, timeout=10):
    time.sleep(2)
    return _body_len(cdp) > body_before


def send_text(text, tab=None):
    """Full send with proof + Enter fallback."""
    result = {"ok": False, "attempts": 0, "proof": "", "detail": ""}
    tab = tab or find_tab()
    if not tab:
        result["detail"] = "no tab"
        return result
    try:
        ws = CDP(tab["webSocketDebuggerUrl"], timeout=60)
    except Exception as e:
        result["detail"] = f"ws fail: {e!r}"
        return result
    try:
        body_before = _body_len(ws)
        for attempt in range(5):
            result["attempts"] = attempt + 1
            try:
                if not _type_into_composer(ws, text):
                    result["detail"] += f"|insert-mismatch@{attempt+1}"
                    continue
                ws.eval(SUBMIT_JS, timeout=10)
                if _proof_of_send(ws, body_before):
                    result["ok"] = True
                    result["proof"] = "composer cleared + body growth"
                    return result
                result["detail"] += f"|proof-fail@{attempt+1}"
            except Exception as e:
                result["detail"] += f"|exc@{attempt+1}:{e!r}"
        # Enter fallback
        try:
            for typ in ("keyDown", "keyUp"):
                ws.call("Input.dispatchKeyEvent", {
                    "type": typ, "key": "Enter", "code": "Enter",
                    "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13})
            if _proof_of_send(ws, body_before):
                result["ok"] = True
                result["proof"] = "cdp-enter fallback"
                return result
        except Exception as e:
            result["detail"] += f"|enter:{e!r}"
        return result
    finally:
        ws.close()
