#!/usr/bin/env python3
"""watcher.py — resident replay-stack watcher.

Monitors (gentle, low-frequency):
  1. target-site login state     -> sets flags/LOGIN_READY when a session exists
  2. JS dialogs on the browser   -> auto-accepts ("Reload site?" popups)
  3. operator inbox messages     -> surfaces them into watcher.log
  4. stack processes             -> restarts dead CDP/dev/replayd/supervisor

Writes log lines to scripts/watcher.log; flag files in scripts/flags/.
Immortal: top-level restart loop + pidfile; the supervisor relaunches this
process if it ever dies, and THIS process resurrects the supervisor if IT
dies (mutual watchdog pair). Run via launch_watcher.py (start_new_session).
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import channel

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "watcher.log")
FLAGS = os.path.join(BASE, "flags")
os.makedirs(FLAGS, exist_ok=True)
CONSOLE_PORT = int(os.environ.get("REPLAY_PORT", "3000"))
CDP_PORT = int(os.environ.get("CDP_PORT", "9222"))
REPLAYD_PORT = int(os.environ.get("REPLAYD_PORT", "3100"))

STATE = {"login": "unknown"}


def py_bin():
    """Interpreter resolved by deploy.sh (scripts/python_bin.txt)."""
    try:
        return open(os.path.join(BASE, "python_bin.txt")).read().strip() or sys.executable
    except Exception:
        return sys.executable


def log(msg):
    line = time.strftime("[%H:%M:%S] ") + msg
    try:
        # self-rotate so the log can never grow unbounded
        if os.path.exists(LOG) and os.path.getsize(LOG) > 2 * 1024 * 1024:
            with open(LOG, "rb") as f:
                f.seek(-150 * 1024, 2)
                tail = f.read()
            with open(LOG, "wb") as f:
                f.write(tail)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass


def check_login():
    """Generic: a visible composer = session exists; 'Sign in' link = out."""
    try:
        tabs = channel.list_tabs()
        tab = next((t for t in tabs if (t.get("url") or "").startswith("http")), None)
        if not tab:
            return STATE["login"]
        cdp = channel.CDP(tab["webSocketDebuggerUrl"], timeout=12)
        try:
            has_composer = cdp.eval(
                "!!document.querySelector('textarea, #chat-input, div[contenteditable=true]')",
                timeout=8)
            body = cdp.eval("document.body.innerText || ''", timeout=8) or ""
        finally:
            cdp.close()
        if "Sign in" in body or "Log in" in body:
            return "logged-out"
        if has_composer:
            return "logged-in"
        return "page:" + str(len(body))
    except Exception:
        return STATE["login"]


def check_dialogs():
    """Auto-accept 'Reload site?' / beforeunload dialogs on the active tab."""
    try:
        tabs = channel.list_tabs()
        aid = ""
        try:
            aid = open(os.path.join(FLAGS, "active_tab.txt")).read().strip()
        except Exception:
            pass
        tab = next((t for t in tabs if t.get("id") == aid), None)
        if tab is None and tabs:
            tab = tabs[0]
        if not tab:
            return False
        cdp = channel.CDP(tab["webSocketDebuggerUrl"], timeout=8)
        try:
            cdp.call("Page.enable", {}, timeout=8)
            cdp.call("Page.handleJavaScriptDialog", {"accept": True}, timeout=8)
            return True  # a dialog was actually accepted
        except Exception:
            return False  # no dialog open — normal case
        finally:
            cdp.close()
    except Exception:
        return False


def check_inbox():
    """Surface new operator messages into watcher.log so the agent notices."""
    path = os.path.join(FLAGS, "operator_inbox.jsonl")
    try:
        if not os.path.exists(path):
            return
        lines = [l for l in open(path, encoding="utf-8").read().split("\n") if l.strip()]
        n = len(lines)
        prev = STATE.get("inbox_lines", 0)
        if n > prev:
            for l in lines[prev:]:
                try:
                    d = json.loads(l)
                    log(f"OPERATOR MESSAGE: {str(d.get('text'))[:200]}")
                except Exception:
                    pass
        STATE["inbox_lines"] = n
    except Exception:
        pass


def check_procs():
    """Restart dead infrastructure (Chrome/CDP / dev server / replayd /
    supervisor). Mutual-watchdog: the supervisor restarts us if we die; we
    restart the supervisor if IT dies — the pair survives unless both die in
    the same instant."""
    py = py_bin()
    try:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=3).read()
        except Exception:
            log("CDP dead — restarting Chrome + Xvfb")
            subprocess.run([py, os.path.join(BASE, "launch_stack.py")], timeout=120)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{CONSOLE_PORT}", timeout=4).read(64)
        except Exception:
            log(f"dev server :{CONSOLE_PORT} dead — restarting")
            subprocess.Popen([py, os.path.join(BASE, "launch_dev.py")],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(5)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{REPLAYD_PORT}/healthz", timeout=3).read(64)
        except Exception:
            log("replayd :3100 dead — restarting")
            subprocess.Popen([py, os.path.join(BASE, "launch_replayd.py")],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
        sup_pid = ""
        try:
            sup_pid = open(os.path.join(BASE, "supervisor.pid")).read().strip()
        except Exception:
            pass
        alive = False
        if sup_pid:
            try:
                cmd = open(f"/proc/{sup_pid}/cmdline", "rb").read().decode(errors="replace")
                alive = "supervisor.py" in cmd
            except Exception:
                alive = False
        if not alive:
            log("supervisor dead — resurrecting")
            subprocess.Popen(
                [py, os.path.join(BASE, "supervisor.py")],
                stdout=open(os.path.join(BASE, "logs", "supervisor.err"), "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True)
    except Exception as e:
        log(f"proc check error {e!r}")


def main():
    log("watcher online (login + dialogs + operator-inbox + proc watchdog)")
    while True:
        try:
            login = check_login()
            if login != STATE["login"]:
                log(f"login: {STATE['login']} -> {login}")
                STATE["login"] = login
                if login.startswith("logged-in"):
                    open(os.path.join(FLAGS, "LOGIN_READY"), "w").write(time.strftime("%H:%M:%S"))
                else:
                    p = os.path.join(FLAGS, "LOGIN_READY")
                    if os.path.exists(p):
                        os.remove(p)
        except Exception as e:
            log(f"loop error {e!r}")

        for _ in range(12):
            check_dialogs()
            check_inbox()
            time.sleep(10)
        check_procs()


if __name__ == "__main__":
    try:
        open(os.path.join(BASE, "watcher.pid"), "w").write(str(os.getpid()))
    except Exception:
        pass
    # IMMORTAL: even if main() somehow raises, restart after a short backoff.
    while True:
        try:
            main()
        except Exception as e:
            try:
                log(f"FATAL in main: {e!r} — restarting in 15s")
            except Exception:
                pass
            time.sleep(15)
        else:
            try:
                log("main() returned unexpectedly — restarting in 15s")
            except Exception:
                pass
            time.sleep(15)
