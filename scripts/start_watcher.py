#!/usr/bin/env python3
"""Start the watcher daemon, detached + self-healing.

The watcher is wrapped in a `while true` shell loop so that if the python
process ever exits (crash or external kill), the wrapper restarts it after
5s. The wrapper itself is started with start_new_session=True and orphaned
to init — the same pattern that keeps Xvfb/Chrome reliably alive here.
"""
import os
import subprocess

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PY = "/home/z/.venv/bin/python3"

WRAPPER = (
    "while true; do "
    f"{PY} {SCRIPTS}/watcher.py >> {SCRIPTS}/watcher_stdout.log 2>&1; "
    f"echo \"[wrapper] watcher exited $? at $(date) — restarting in 5s\" >> {SCRIPTS}/watcher.log; "
    "sleep 5; "
    "done"
)


def main():
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
