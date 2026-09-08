#!/usr/bin/env python3
"""Process management for the browser replay stack.

Manages: Xvfb (:99), Chrome for Testing (CDP on 127.0.0.1:9222, persistent
profile), and the Next.js dev server (port 3000). All processes are started
detached (start_new_session=True) with pid files + logs under scripts/.
"""
import os
import subprocess
import time
import urllib.request

ROOT = "/home/z/my-project"
SCRIPTS = os.path.join(ROOT, "scripts")
FLAGS = os.path.join(SCRIPTS, "flags")
PROFILE = os.path.join(SCRIPTS, "browser-profile")
CHROME_BIN = "/home/z/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome"
PYTHON = "/home/z/.venv/bin/python3"
XVFB_DISPLAY = ":99"
CDP_PORT = 9222
DEV_URL = "http://127.0.0.1:3000/"


def ensure_dirs():
    os.makedirs(FLAGS, exist_ok=True)
    os.makedirs(PROFILE, exist_ok=True)


def _pid_path(name):
    return os.path.join(SCRIPTS, f"{name}.pid")


def read_pid(name):
    try:
        with open(_pid_path(name)) as f:
            return int(f.read().strip())
    except Exception:
        return None


def write_pid(name, pid):
    ensure_dirs()
    with open(_pid_path(name), "w") as f:
        f.write(str(pid))


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        # a zombie is not alive for our purposes
        stat = open(f"/proc/{pid}/stat").read().split(") ", 1)[1].split()[0]
        return stat != "Z"
    except Exception:
        return False


def _log(name):
    return open(os.path.join(SCRIPTS, f"{name}.log"), "ab", buffering=0)


# ---------------------------------------------------------------- Xvfb

def xvfb_up():
    pid = read_pid("xvfb")
    if not pid_alive(pid):
        return False
    return os.path.exists(f"/tmp/.X11-unix/X{XVFB_DISPLAY.lstrip(':')}")


def start_xvfb():
    """Start Xvfb on :99 (1440x900x24) if not already running. Returns pid."""
    old = read_pid("xvfb")
    if xvfb_up():
        return old
    ensure_dirs()
    with _log("xvfb") as log:
        p = subprocess.Popen(
            ["Xvfb", XVFB_DISPLAY, "-screen", "0", "1440x900x24", "-nolisten", "tcp"],
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    write_pid("xvfb", p.pid)
    time.sleep(0.8)
    return p.pid


# ---------------------------------------------------------------- Chrome

def chrome_up():
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2
        ) as r:
            return r.status == 200
    except Exception:
        return False


def start_chrome(url="https://chat.z.ai/"):
    """Start headed Chrome under Xvfb with CDP on 127.0.0.1:9222.

    Persistent user-data-dir means operator login survives restarts.
    Returns the pid.
    """
    if chrome_up():
        return read_pid("browser")
    ensure_dirs()
    if not xvfb_up():
        start_xvfb()
        time.sleep(0.5)
    env = dict(os.environ)
    env["DISPLAY"] = XVFB_DISPLAY
    with _log("browser") as log:
        p = subprocess.Popen(
            [
                CHROME_BIN,
                f"--remote-debugging-port={CDP_PORT}",
                "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={PROFILE}",
                "--no-sandbox",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--hide-crash-restore-bubble",
                "--window-size=1440,900",
                url,
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    write_pid("browser", p.pid)
    return p.pid


# ---------------------------------------------------------------- dev server

def dev_up():
    try:
        with urllib.request.urlopen(DEV_URL, timeout=5) as r:
            return r.status < 500
    except Exception:
        return False


def start_dev():
    """Restart the Next.js dev server (single instance, guarded by dev_up())."""
    if dev_up():
        return read_pid("dev")
    old = read_pid("dev")
    if pid_alive(old):
        try:
            os.killpg(os.getpgid(old), 15)
        except Exception:
            pass
        time.sleep(2)
    devlog = open(os.path.join(ROOT, "dev.log"), "ab", buffering=0)
    p = subprocess.Popen(
        ["bun", "run", "dev"],
        cwd=ROOT,
        stdout=devlog,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    write_pid("dev", p.pid)
    return p.pid


# ---------------------------------------------------------------- helpers

def touch(path):
    ensure_dirs()
    with open(path, "a"):
        os.utime(path, None)


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "start":
        ensure_dirs()
        start_xvfb()
        time.sleep(0.6)
        start_chrome()
        for _ in range(30):
            if chrome_up():
                break
            time.sleep(0.5)
        print("xvfb_up:", xvfb_up(), "chrome_up:", chrome_up(), "dev_up:", dev_up())
    elif cmd == "status":
        print("xvfb_up:", xvfb_up(), "chrome_up:", chrome_up(), "dev_up:", dev_up())
    else:
        print("usage: procs.py [start|status]", file=sys.stderr)
