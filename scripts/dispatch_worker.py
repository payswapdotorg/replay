#!/usr/bin/env python3
"""dispatch_worker.py — create chat.z.ai worker sessions via the browser (replay).

Usage:
  dispatch_worker.py create <name> <prompt_file>   -> new tab, send prompt, register
  dispatch_worker.py check <name>                  -> session state (text tail)
  dispatch_worker.py list                          -> registered sessions
  dispatch_worker.py models                        -> inspect model selector options

Sessions registry: scripts/flags/session_registry.jsonl
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import channel

BASE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(BASE, "flags/session_registry.jsonl")


def _sessions():
    try:
        return [json.loads(l) for l in open(REG).read().split("\n") if l.strip()]
    except Exception:
        return []


def _save(s):
    with open(REG, "a") as f:
        f.write(json.dumps(s) + "\n")


def _find(name):
    for s in _sessions():
        if s["name"] == name:
            return s
    return None


def _tab_for(s):
    tabs = channel.list_tabs()
    for t in tabs:
        if t["id"] == s.get("tab_id"):
            return t
    for t in tabs:
        if s.get("url") and s["url"].split("chat.z.ai")[-1][:30] in (t.get("url") or ""):
            return t
    return None


def create(name, prompt_file):
    prompt = open(prompt_file).read()
    if _find(name):
        print(f"session {name} already exists")
        return 1
    tab = channel.new_tab()
    if not tab:
        print("ERROR: could not create tab")
        return 1
    print(f"tab created: {tab['id'][:8]}")
    # /json/new does not navigate in this Chrome build — do it via CDP
    c = channel.CDP(tab["webSocketDebuggerUrl"], timeout=20)
    try:
        c.call("Page.navigate", {"url": "https://chat.z.ai/"}, timeout=30)
    finally:
        c.close()
    # wait for load + composer
    for _ in range(25):
        time.sleep(1.5)
        try:
            c = channel.CDP(tab["webSocketDebuggerUrl"], timeout=10)
            ready = c.eval(
                "(() => { const i = document.querySelector('#chat-input, textarea');"
                " return i ? 'ready' : 'no-input'; })()")
            c.close()
            if ready == "ready":
                break
        except Exception:
            pass
    else:
        print("WARN: chat input not detected; continuing anyway")

    c = channel.CDP(tab["webSocketDebuggerUrl"], timeout=60)
    try:
        # focus the input, insert the prompt, send with Enter
        c.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 720, "y": 660, "button": "left", "clickCount": 1})
        c.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": 720, "y": 660, "button": "left", "clickCount": 1})
        time.sleep(0.5)
        c.call("Input.insertText", {"text": prompt})
        time.sleep(0.8)
        for typ in ("keyDown", "keyUp"):
            c.call("Input.dispatchKeyEvent", {
                "type": typ, "key": "Enter", "code": "Enter",
                "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13})
        time.sleep(2)
        # verify the prompt landed in the DOM
        snippet = prompt[:60].replace("\n", " ")
        body = c.eval("document.body.innerText || ''", timeout=15) or ""
        ok = snippet[:40] in body
        url = c.eval("location.href")
        print(f"prompt sent: {'VERIFIED' if ok else 'NOT VERIFIED — retry needed'}")
        print(f"session url: {url}")
        _save({"name": name, "tab_id": tab["id"], "url": url, "ts": int(time.time()),
               "prompt_file": prompt_file, "sent": ok})
        return 0 if ok else 2
    finally:
        c.close()


def check(name):
    s = _find(name)
    if not s:
        print(f"no session named {name}")
        return 1
    tab = _tab_for(s)
    if not tab:
        print(f"session tab LOST (was {s.get('tab_id','')[:8]}); url: {s.get('url')}")
        return 2
    c = channel.CDP(tab["webSocketDebuggerUrl"], timeout=20)
    try:
        body = c.eval("document.body.innerText || ''", timeout=15) or ""
        # crude progress heuristics
        streaming = any(m in body for m in ("Thinking", "Generating", "typing…"))
        lines = body.split("\n")
        print(f"session {name} | url {c.eval('location.href')}")
        print(f"chars: {len(body)} | streaming-marker: {streaming}")
        print("---- last 15 lines ----")
        for l in lines[-15:]:
            if l.strip():
                print("  " + l[:120])
        return 0
    finally:
        c.close()


def models():
    tab = channel.find_tab("chat.z.ai")
    if not tab:
        print("no chat.z.ai tab")
        return 1
    c = channel.CDP(tab["webSocketDebuggerUrl"], timeout=20)
    try:
        # try to open the model selector and read options
        c.eval("""(() => {
          const btns = Array.from(document.querySelectorAll('button'));
          const sel = btns.find(b => /GLM|model/i.test(b.innerText||'') && b.innerText.length < 40);
          if (sel) sel.click();
          return sel ? 'clicked: ' + sel.innerText.trim() : 'no selector found';
        })()""")
        time.sleep(1)
        opts = c.eval("""(() => {
          const items = Array.from(document.querySelectorAll('[role=menuitem], [role=option], li, div[class*=dropdown] div'))
            .map(e => (e.innerText||'').trim().split('\\n')[0])
            .filter(t => t && t.length < 50 && /GLM|Air|Flash|Max|4\\.|5\\./.test(t));
          return JSON.stringify([...new Set(items)].slice(0, 20));
        })()""")
        print("MODEL OPTIONS:", opts)
        return 0
    finally:
        c.close()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "create":
        return create(sys.argv[2], sys.argv[3])
    if cmd == "check":
        return check(sys.argv[2])
    if cmd == "list":
        for s in _sessions():
            print(f"{s['name']:12} tab={s.get('tab_id','')[:8]} sent={s.get('sent')} url={s.get('url','')[:60]}")
        return 0
    if cmd == "models":
        return models()
    print("unknown command")
    return 1


if __name__ == "__main__":
    sys.exit(main())
