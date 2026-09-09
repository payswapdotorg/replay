"""launch_dev.py — start the Next.js console (default :3000).

Heap cap: next-server can balloon and get OOM-killed, taking the stack down.
Capping V8 old-space keeps the dev server bounded; the supervisor/watchdog
pair handles the rare restart if it hits the cap.

Env: REPLAY_PORT (default 3000)
"""
import os
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
PORT = os.environ.get("REPLAY_PORT", "3000")

env = dict(os.environ)
env["NODE_OPTIONS"] = "--max-old-space-size=1024"  # FORCE: setdefault silently drops the cap if NODE_OPTIONS is preset
p = subprocess.Popen(["bun", "run", "dev", "--", "-p", PORT],
    stdout=open(os.path.join(BASE, "dev.log"), "w"), stderr=subprocess.STDOUT,
    start_new_session=True, cwd=ROOT, env=env)
open(os.path.join(BASE, "dev.pid"), "w").write(str(p.pid))
print(f"dev server pid {p.pid} (port {PORT})")
