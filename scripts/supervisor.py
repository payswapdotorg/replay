#!/usr/bin/env python3
"""supervisor.py — makes the whole replay stack immortal.

Single-instance daemon (flock-guarded). Every 10s it verifies and, when dead,
automatically restarts:
  1. watcher.py        (login / dialog / inbox / proc monitor)
  2. Chrome CDP :9222  (+ Xvfb via launch_stack.py)
  3. dev server :3000  (operator console; REPLAY_PORT to override)
  4. replayd    :3100  (persistent CDP daemon — realtime frames + drags)

Also rotates logs so nothing grows unbounded, and touches
flags/supervisor_heartbeat. This process is launched detached (setsid) so it
survives CLI session resets; if IT is ever killed, watcher.py resurrects it
(mutual watchdog), and any later launch simply adopts the flock.

Run: setsid python3 scripts/supervisor.py >> scripts/logs/supervisor.log 2>&1 &
(deploy.sh does this for you)
"""
import fcntl
import os
import subprocess
import sys
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
FLAGS = os.path.join(BASE, "flags")
LOGDIR = os.path.join(BASE, "logs")
os.makedirs(FLAGS, exist_ok=True)
os.makedirs(LOGDIR, exist_ok=True)
LOG = os.path.join(LOGDIR, "supervisor.log")
PIDFILE = os.path.join(BASE, "supervisor.pid")
LOCK = os.path.join(FLAGS, "supervisor.lock")

MAX_LOG = 2 * 1024 * 1024      # rotate above 2MB
KEEP_TAIL = 150 * 1024         # keep last 150KB
CONSOLE_PORT = int(os.environ.get("REPLAY_PORT", "3000"))
CDP_PORT = int(os.environ.get("CDP_PORT", "9222"))
REPLAYD_PORT = int(os.environ.get("REPLAYD_PORT", "3100"))


def py_bin():
    try:
        return open(os.path.join(BASE, "python_bin.txt")).read().strip() or sys.executable
    except Exception:
        return sys.executable


PY = py_bin()


def log(msg):
    line = time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


def pid_alive(pid, needle=""):
    try:
        pid = int(pid)
        if pid <= 0:
            return False
        cmd = open(f"/proc/{pid}/cmdline", "rb").read().decode(errors="replace")
        if needle and needle not in cmd:
            return False
        return True
    except Exception:
        return False


def http_ok(url, timeout=4):
    try:
        urllib.request.urlopen(url, timeout=timeout).read(64)
        return True
    except Exception:
        return False


def read_pid(path):
    try:
        return open(path).read().strip()
    except Exception:
        return ""


def rotate_logs():
    for name in ("watcher.log", "channel.log"):
        _rotate(os.path.join(BASE, name))
    for name in ("supervisor.log", "replayd.log"):
        _rotate(os.path.join(LOGDIR, name))
    _rotate(os.path.join(BASE, "dev.log"))


def _rotate(path):
    try:
        if os.path.exists(path) and os.path.getsize(path) > MAX_LOG:
            with open(path, "rb") as f:
                f.seek(-KEEP_TAIL, 2)
                tail = f.read()
            with open(path, "wb") as f:
                f.write(tail)
    except Exception:
        pass


def ensure_watcher():
    pid = read_pid(os.path.join(BASE, "watcher.pid"))
    if pid_alive(pid, "watcher.py"):
        return False
    # pidfile stale or empty — double-check by scanning process list
    # (anchored to THIS deployment's path so parallel deployments don't alias)
    r = subprocess.run(["pgrep", "-f", os.path.join(BASE, "watcher.py")],
                       capture_output=True, text=True)
    if r.stdout.strip():
        try:
            open(os.path.join(BASE, "watcher.pid"), "w").write(r.stdout.strip().split("\n")[0])
        except Exception:
            pass
        return False
    log("watcher DEAD — restarting")
    subprocess.Popen([PY, os.path.join(BASE, "launch_watcher.py")],
                     stdout=open(os.path.join(LOGDIR, "watcher_launch.log"), "a"),
                     stderr=subprocess.STDOUT)
    return True


def ensure_browser():
    if http_ok(f"http://127.0.0.1:{CDP_PORT}/json/version"):
        return False
    log("Chrome CDP DEAD — restarting stack (Xvfb + Chrome)")
    # Xvfb may be dead too; launch_stack restarts both (a duplicate Xvfb simply
    # fails to bind and exits, which is harmless)
    subprocess.run([PY, os.path.join(BASE, "launch_stack.py")], timeout=120,
                   stdout=open(os.path.join(LOGDIR, "stack_launch.log"), "a"),
                   stderr=subprocess.STDOUT)
    return True


def ensure_dev():
    if http_ok(f"http://127.0.0.1:{CONSOLE_PORT}"):
        return False
    log(f"dev server :{CONSOLE_PORT} DEAD — restarting")
    subprocess.Popen([PY, os.path.join(BASE, "launch_dev.py")],
                     stdout=open(os.path.join(LOGDIR, "dev_launch.log"), "a"),
                     stderr=subprocess.STDOUT)
    return True


def ensure_replayd():
    if http_ok(f"http://127.0.0.1:{REPLAYD_PORT}/healthz"):
        return False
    log(f"replayd :{REPLAYD_PORT} DEAD — restarting")
    subprocess.Popen([PY, os.path.join(BASE, "launch_replayd.py")],
                     stdout=open(os.path.join(LOGDIR, "replayd_launch.log"), "a"),
                     stderr=subprocess.STDOUT)
    return True


def heartbeat():
    try:
        p = os.path.join(FLAGS, "supervisor_heartbeat")
        with open(p, "w") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass


def main():
    # single-instance guard
    lock_fh = open(LOCK, "w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another supervisor already holds the lock — exiting", flush=True)
        return 0
    open(PIDFILE, "w").write(str(os.getpid()))
    log(f"supervisor online (pid {os.getpid()}) — watching watcher/CDP:{CDP_PORT}/dev:{CONSOLE_PORT}/replayd:{REPLAYD_PORT}")

    cycle = 0
    while True:
        try:
            ensure_watcher()
            ensure_replayd()
            if cycle % 3 == 0:          # browser + console checks every ~30s
                ensure_browser()
                ensure_dev()
                rotate_logs()
            heartbeat()
        except Exception as e:
            log(f"cycle error {e!r} — continuing")
        cycle += 1
        time.sleep(10)


if __name__ == "__main__":
    main()
