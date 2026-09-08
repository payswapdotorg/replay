#!/usr/bin/env python3
"""Watchdog for the browser replay stack (cycle: 60s).

Each cycle:
- restart dead Xvfb / Chrome / dev-server (via procs.py)
- auto-accept JavaScript dialogs on the active tab (Page.handleJavaScriptDialog
  {accept:true}; errors are ignored when no dialog is open)
- auto-select newly created tabs (auth popups) as the active replay tab
- log new operator messages from scripts/flags/operator_inbox.jsonl
- maintain the chat.z.ai session registry (scripts/flags/session_registry.json)
- touch scripts/flags/watcher_heartbeat
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import channel  # noqa: E402
from procs import (  # noqa: E402
    TARGET_URL,
    chrome_up,
    dev_up,
    ensure_dirs,
    start_chrome,
    start_dev,
    start_xvfb,
    xvfb_up,
)

CYCLE = 60
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
FLAGS = os.path.join(SCRIPTS, "flags")
LOG = os.path.join(SCRIPTS, "watcher.log")
SEEN_TABS = os.path.join(FLAGS, "seen_tabs.json")
WATCHER_HEARTBEAT = os.path.join(FLAGS, "watcher_heartbeat")
OPERATOR_INBOX = os.path.join(FLAGS, "operator_inbox.jsonl")
OP_WATERMARK = os.path.join(FLAGS, "watcher_op_watermark.txt")
REGISTRY = os.path.join(FLAGS, "session_registry.json")
ACTIVE_TAB_FILE = os.path.join(FLAGS, "active_tab.txt")


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)


def _read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, obj):
    ensure_dirs()
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


def touch_heartbeat():
    ensure_dirs()
    with open(WATCHER_HEARTBEAT, "a"):
        os.utime(WATCHER_HEARTBEAT, None)


def restart_dead():
    if not xvfb_up():
        log("xvfb down -> starting")
        start_xvfb()
    if not chrome_up():
        log("chrome down -> starting")
        start_chrome()
    if not dev_up():
        log("dev server down -> starting")
        start_dev()


def auto_select_new_tabs(tabs):
    if not tabs:
        return
    seen = _read_json(SEEN_TABS, None)
    ids = [t.get("id") for t in tabs]
    if seen is None:
        # first boot: baseline only, no switching
        _write_json(SEEN_TABS, ids)
        return
    seen = set(seen)
    fresh = [t for t in tabs if t.get("id") not in seen]
    if fresh and len(fresh) == 1:
        new = fresh[0]
        with open(ACTIVE_TAB_FILE, "w") as f:
            f.write(new["id"])
        log(f"new tab auto-selected: {new.get('title', '')!r} {new.get('url', '')}")
    elif fresh:
        log(f"{len(fresh)} new tabs appeared (restart?) — not switching")
    _write_json(SEEN_TABS, ids)


def accept_dialogs(tabs):
    """Auto-accept JS dialogs (beforeunload / alert / confirm) on the active tab.

    Calling Page.handleJavaScriptDialog when no dialog is open raises an
    error which we intentionally ignore.
    """
    if not tabs:
        return
    wanted = None
    try:
        with open(ACTIVE_TAB_FILE) as f:
            wanted = f.read().strip()
    except Exception:
        pass
    tab = next((t for t in tabs if t.get("id") == wanted), tabs[0])
    try:
        c = channel.CDP(tab["webSocketDebuggerUrl"])
        try:
            c.call("Page.enable")
            c.call("Page.handleJavaScriptDialog", {"accept": True})
            log(f"dialog accepted on {tab.get('url', '')}")
        finally:
            c.close()
    except Exception:
        pass


def log_operator_messages():
    if not os.path.exists(OPERATOR_INBOX):
        return
    try:
        with open(OPERATOR_INBOX) as f:
            lines = f.readlines()
    except Exception:
        return
    try:
        with open(OP_WATERMARK) as f:
            wm = int(f.read().strip())
    except Exception:
        wm = 0
    if len(lines) > wm:
        for line in lines[wm:]:
            try:
                msg = json.loads(line)
                log(f"OPERATOR: {msg.get('text', '')!r}")
            except Exception:
                pass
        ensure_dirs()
        with open(OP_WATERMARK, "w") as f:
            f.write(str(len(lines)))


def session_registry(tabs):
    """Track tabs belonging to the target site ($TARGET_URL, chat.z.ai default)."""
    from urllib.parse import urlparse

    try:
        host = urlparse(TARGET_URL).host or urlparse(TARGET_URL).netloc
    except Exception:
        host = "chat.z.ai"
    if not host:
        host = "chat.z.ai"
    chat = [
        {"id": t.get("id"), "title": (t.get("title") or "")[:80], "url": t.get("url", "")}
        for t in tabs
        if host in t.get("url", "")
    ]
    if chat:
        prev = _read_json(REGISTRY, {"knownUrls": []})
        urls = set(prev.get("knownUrls", []))
        for s in chat:
            urls.add(s["url"])
        _write_json(
            REGISTRY,
            {"ts": int(time.time() * 1000), "sessions": chat, "knownUrls": sorted(urls)},
        )
        if len(chat) > 3:
            log(f"target-site session count = {len(chat)} (> 3) — trim recommended")


def cycle():
    touch_heartbeat()
    restart_dead()
    tabs = channel.list_tabs()
    auto_select_new_tabs(tabs)
    accept_dialogs(tabs)
    log_operator_messages()
    session_registry(tabs)


def main():
    ensure_dirs()
    log("watcher started")
    while True:
        try:
            cycle()
        except Exception as e:
            log(f"cycle error: {e}")
        time.sleep(CYCLE)


if __name__ == "__main__":
    main()
