#!/usr/bin/env python3
"""Start the watcher daemon, detached + self-healing. IDEMPOTENT.

The watcher is wrapped in a `while true` shell loop so that if the python
process ever exits (crash or external kill), the wrapper restarts it after
5s. The wrapper itself is started with start_new_session=True and orphaned
to init — the same pattern that keeps Xvfb/Chrome reliably alive here.

If a live wrapper already exists (pid file + fresh watcher heartbeat), this
script does nothing, so `bootstrap.sh` can be run any number of times.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from procs import PYTHON, pid_alive  # noqa: E402

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
FLAGS = os.path.join(SCRIPTS, "flags")
HEARTBEAT = os.path.join(FLAGS, "watcher_heartbeat")

WRAPPER = (
    "while true; do "
    f"{PYTHON} {SCRIPTS}/watcher.py >> {SCRIPTS}/watcher_stdout.log 2>&1; "
    f"echo \"[wrapper] watcher exited $? at $(date) — restarting in 5s\" >> {SCRIPTS}/watcher.log; "
    "sleep 5; "
    "done"
)


def _heartbeat_fresh(max_age=180):
    try:
        return (time.time() - os.path.getmtime(HEARTBEAT)) < max_age
    except Exception:
        return False


def _pid_file():
    try:
        with open(os.path.join(SCRIPTS, "watcher.pid")) as f:
            return int(f.read().strip())
    except Exception:
        return None


def main():
    pid = _pid_file()
    if pid and pid_alive(pid) and _heartbeat_fresh():
        print(f"watcher already running (wrapper pid {pid}, heartbeat fresh)")
        return
    log = open(os.path.join(SCRIPTS, "watcher_stdout.log"), "ab", buffering=0)
    p = subprocess.Popen(
        ["/bin/sh", "-c", WRAPPER],
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        cwd=SCRIPTS,
        start_new_session=True,
    )
    with open(os.path.join(SCRIPTS, "watcher.pid"), "w") as f:
        f.write(str(p.pid))
    print("watcher wrapper pid:", p.pid)


if __name__ == "__main__":
    main()
