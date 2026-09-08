"""launch_replayd.py — start the persistent CDP replay daemon (:3100) detached."""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)

PY = sys.executable
try:
    cand = open(os.path.join(BASE, "python_bin.txt")).read().strip()
    if cand:
        PY = cand
except Exception:
    pass

p = subprocess.Popen(
    [PY, os.path.join(BASE, "replayd.py")],
    stdout=open(os.path.join(BASE, "logs", "replayd.out"), "a"),
    stderr=subprocess.STDOUT,
    start_new_session=True,
    cwd=BASE,
)
open(os.path.join(BASE, "replayd.pid"), "w").write(str(p.pid))
print("replayd pid", p.pid)
