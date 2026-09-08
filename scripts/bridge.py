#!/usr/bin/env python3
"""CLI bridge between the Next.js console API routes and Chrome via CDP.

Usage:
  bridge.py frame            -> JPEG screenshot of the ACTIVE tab (raw bytes on stdout)
  bridge.py event '<json>'   -> dispatch input event / navigate on the ACTIVE tab
  bridge.py tabs             -> JSON: {tabs: [{id,title,url}], active}
  bridge.py status           -> JSON status snapshot for the console

The ACTIVE tab is resolved as:
  1. scripts/flags/active_tab.txt if that tab still exists
  2. else a chat.z.ai tab
  3. else the first page tab
and is written back to scripts/flags/active_tab.txt.
"""
import base64
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import channel  # noqa: E402
from procs import FLAGS, chrome_up, dev_up, ensure_dirs, xvfb_up  # noqa: E402

ACTIVE_TAB_FILE = os.path.join(FLAGS, "active_tab.txt")
HEARTBEAT = os.path.join(FLAGS, "heartbeat")
WATCHER_HEARTBEAT = os.path.join(FLAGS, "watcher_heartbeat")
OPERATOR_INBOX = os.path.join(FLAGS, "operator_inbox.jsonl")
AGENT_OUTBOX = os.path.join(FLAGS, "agent_outbox.jsonl")
LAST_ACCOUNT = os.path.join(FLAGS, "last_account.txt")


def _read_active_id():
    try:
        with open(ACTIVE_TAB_FILE) as f:
            return f.read().strip() or None
    except Exception:
        return None


def _write_active_id(tid):
    ensure_dirs()
    with open(ACTIVE_TAB_FILE, "w") as f:
        f.write(tid)


def resolve_active(tabs=None):
    """Pick the active tab (persisted id if alive, else heuristic)."""
    tabs = channel.list_tabs() if tabs is None else tabs
    if not tabs:
        return None
    wanted = _read_active_id()
    if wanted:
        for t in tabs:
            if t.get("id") == wanted:
                return t
    t = channel.find_tab(None, tabs)
    if t:
        _write_active_id(t["id"])
    return t


def _connect(tab):
    return channel.CDP(tab["webSocketDebuggerUrl"])


def _count_lines(path):
    try:
        with open(path) as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


def _age(path):
    try:
        return int(time.time() - os.path.getmtime(path))
    except Exception:
        return None


# ---------------------------------------------------------------- frame

def cmd_frame():
    tab = resolve_active()
    if not tab:
        sys.stderr.write("no browser tab available\n")
        return 2
    c = _connect(tab)
    try:
        c.call("Page.enable")
        res = c.call("Page.captureScreenshot", {"format": "jpeg", "quality": 75})
        data = base64.b64decode(res.get("data", ""))
        sys.stdout.buffer.write(data)  # RAW BINARY — never route through a string
        sys.stdout.buffer.flush()
        return 0
    finally:
        c.close()


# ---------------------------------------------------------------- events

KEY_MAP = {
    "enter": ("Enter", 13, "\r"),
    "tab": ("Tab", 9, "\t"),
    "escape": ("Escape", 27, None),
    "backspace": ("Backspace", 8, None),
    "delete": ("Delete", 46, None),
    "arrowup": ("ArrowUp", 38, None),
    "arrowdown": ("ArrowDown", 40, None),
    "arrowleft": ("ArrowLeft", 37, None),
    "arrowright": ("ArrowRight", 39, None),
}


def _send_key(c, code, vk, text):
    down = {
        "type": "keyDown",
        "key": code,
        "code": code,
        "windowsVirtualKeyCode": vk,
        "nativeVirtualKeyCode": vk,
    }
    if text:
        down["text"] = text
        down["unmodifiedText"] = text
    c.call("Input.dispatchKeyEvent", down)
    c.call(
        "Input.dispatchKeyEvent",
        {
            "type": "keyUp",
            "key": code,
            "code": code,
            "windowsVirtualKeyCode": vk,
            "nativeVirtualKeyCode": vk,
        },
    )


def _viewport(c):
    try:
        raw = c.eval("JSON.stringify([window.innerWidth, window.innerHeight])")
        w, h = json.loads(raw)
        return int(w), int(h)
    except Exception:
        return 1440, 800


def cmd_event(spec):
    etype = spec.get("type")
    tab = resolve_active()
    if not tab:
        return {"ok": False, "error": "no browser tab available"}
    c = _connect(tab)
    try:
        if etype in ("click", "dblclick"):
            x = int(round(float(spec.get("x", 0))))
            y = int(round(float(spec.get("y", 0))))
            count = 2 if etype == "dblclick" else 1
            c.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
            c.call(
                "Input.dispatchMouseEvent",
                {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": count},
            )
            c.call(
                "Input.dispatchMouseEvent",
                {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": count},
            )
        elif etype == "scroll":
            dx = int(float(spec.get("dx", 0)))
            dy = int(float(spec.get("dy", 0)))
            w, h = _viewport(c)
            x = int(float(spec.get("x", w // 2)))
            y = int(float(spec.get("y", h // 2)))
            c.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
            c.call(
                "Input.dispatchMouseEvent",
                {"type": "mouseWheel", "x": x, "y": y, "deltaX": dx, "deltaY": dy},
            )
        elif etype == "type":
            text = str(spec.get("text", ""))
            if not text:
                return {"ok": False, "error": "empty text"}
            c.call("Input.insertText", {"text": text})
        elif etype == "key":
            name = str(spec.get("key", "enter")).lower()
            code, vk, text = KEY_MAP.get(name, ("Enter", 13, "\r"))
            _send_key(c, code, vk, text)
        elif etype == "enter":
            _send_key(c, "Enter", 13, "\r")
        elif etype == "nav":
            url = str(spec.get("url", ""))
            if not url.startswith(("http://", "https://", "file://")):
                return {"ok": False, "error": "invalid url"}
            c.call("Page.enable")
            c.call("Page.navigate", {"url": url})
        elif etype == "reload":
            c.call("Page.enable")
            c.call("Page.reload", {"ignoreCache": False})
        else:
            return {"ok": False, "error": f"unknown event type: {etype}"}
        return {"ok": True, "tab": tab["id"], "type": etype}
    finally:
        c.close()


# ---------------------------------------------------------------- tabs

def cmd_tabs():
    tabs = channel.list_tabs()
    active = resolve_active(tabs)
    out = {
        "ok": bool(tabs),
        "tabs": [
            {
                "id": t.get("id"),
                "title": (t.get("title") or "")[:80],
                "url": t.get("url", ""),
            }
            for t in tabs
        ],
        "active": active["id"] if active else None,
    }
    print(json.dumps(out))
    return 0


# ---------------------------------------------------------------- status

_LOGIN_JS = (
    "(() => {"
    "  const t = document.body ? document.body.innerText : '';"
    "  const m = t.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}/);"
    "  const input = document.querySelector('textarea, [contenteditable=\"true\"]');"
    "  return JSON.stringify({"
    "    url: location.href, title: document.title,"
    "    signIn: /\\b(sign ?in|log ?in)\\b/i.test(t),"
    "    signOut: /\\b(sign ?out|log ?out)\\b/i.test(t),"
    "    email: m ? m[0] : null,"
    "    chatInput: !!input"
    "  });"
    "})()"
)


def cmd_status():
    ensure_dirs()
    tabs = channel.list_tabs()
    active = resolve_active(tabs)
    snap = {}
    if active:
        try:
            c = _connect(active)
            try:
                c.call("Page.enable")
                snap = json.loads(c.eval(_LOGIN_JS) or "{}")
            finally:
                c.close()
        except Exception as e:
            snap = {"error": str(e)}

    login = "unknown"
    if snap.get("email") or (snap.get("signOut") and not snap.get("signIn")):
        login = "signed-in"
    elif snap.get("signIn") and not snap.get("signOut"):
        login = "signed-out"

    account = snap.get("email")
    if account:
        with open(LAST_ACCOUNT, "w") as f:
            f.write(account)
    else:
        try:
            with open(LAST_ACCOUNT) as f:
                account = f.read().strip() or None
        except Exception:
            account = None

    out = {
        "ok": bool(active),
        "ts": int(time.time() * 1000),
        "xvfb": xvfb_up(),
        "chrome": chrome_up(),
        "dev": dev_up(),
        "tabCount": len(tabs),
        "active": (
            {"id": active.get("id"), "title": (active.get("title") or "")[:80],
             "url": active.get("url", "")}
            if active
            else None
        ),
        "login": login,
        "account": account,
        "chatInput": bool(snap.get("chatInput")),
        "agentActiveAgo": _age(HEARTBEAT),
        "watcherActiveAgo": _age(WATCHER_HEARTBEAT),
        "operatorMessages": _count_lines(OPERATOR_INBOX),
        "agentMessages": _count_lines(AGENT_OUTBOX),
    }
    print(json.dumps(out))
    return 0


# ---------------------------------------------------------------- main

def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "frame":
        rc = cmd_frame()
        return rc if rc else 0
    if cmd == "event":
        try:
            spec = json.loads(argv[2]) if len(argv) > 2 else {}
        except Exception as e:
            print(json.dumps({"ok": False, "error": f"bad json: {e}"}))
            return 1
        try:
            print(json.dumps(cmd_event(spec)))
            return 0
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
    if cmd == "tabs":
        return cmd_tabs()
    if cmd == "status":
        return cmd_status()
    sys.stderr.write(__doc__ or "usage: bridge.py [frame|event|tabs|status]\n")
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
