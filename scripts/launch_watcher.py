"""launch_watcher.py — start the resident watcher detached."""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))

PY = sys.executable
try:
    cand = open(os.path.join(BASE, "python_bin.txt")).read().strip()
    if cand:
        PY = cand
except Exception:
    pass

p = subprocess.Popen([PY, os.path.join(BASE, "watcher.py")],
    stdout=open(os.path.join(BASE, "watcher.out"), "w"), stderr=subprocess.STDOUT,
    start_new_session=True, cwd=BASE)
open(os.path.join(BASE, "watcher.pid"), "w").write(str(p.pid))
print("watcher pid", p.pid)
