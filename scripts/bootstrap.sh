#!/usr/bin/env bash
# bootstrap.sh — one-command cold start for the Replay console.
#
# Idempotent: safe to run any number of times. Use cases:
#
#   1) In a fresh z.ai sandbox, deploy the repo (see README "Deploy"):
#        git clone https://github.com/payswapdotorg/replay.git /tmp/replay
#        INSTALL_DIR=/home/z/my-project bash /tmp/replay/scripts/bootstrap.sh
#
#   2) Inside an existing checkout, just (re)start everything:
#        bash scripts/bootstrap.sh
#
# Environment (all optional):
#   INSTALL_DIR  where the app should live (default: the repo checkout itself)
#   TARGET_URL   page Chrome opens first (default: https://chat.z.ai/)
#   CHROME_BIN   explicit Chrome binary (default: auto-detected)
#   PYTHON_BIN   python with websocket-client (default: /home/z/.venv/bin/python3)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${INSTALL_DIR:-$REPO_ROOT}"
PYTHON_BIN="${PYTHON_BIN:-/home/z/.venv/bin/python3}"
TARGET_URL="${TARGET_URL:-https://chat.z.ai/}"

log()  { printf '\033[0;32m[bootstrap]\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m[bootstrap]\033[0m %s\n' "$*" >&2; }

# ---------------------------------------------------------------- 0. sanity
for bin in bun git; do
  command -v "$bin" >/dev/null 2>&1 || { warn "missing dependency: $bin"; exit 1; }
done
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3 || true)"
  [ -n "$PYTHON_BIN" ] || { warn "no python3 found"; exit 1; }
fi

# ---------------------------------------------------------------- 1. place the app
if [ "$INSTALL_DIR" != "$REPO_ROOT" ]; then
  log "copying repo into $INSTALL_DIR (runtime state preserved)"
  mkdir -p "$INSTALL_DIR"
  rsync -a --delete \
    --exclude '.git/' \
    --exclude 'node_modules/' \
    --exclude '.next/' \
    --exclude 'scripts/browser-profile/' \
    --exclude 'scripts/flags/' \
    --exclude 'scripts/env.sh' \
    --exclude 'scripts/*.log' \
    --exclude 'scripts/*.pid' \
    --exclude 'db/' \
    --exclude 'dev.log' \
    --exclude 'worklog.md' \
    --exclude 'tests/' \
    --exclude 'skills/' \
    "$REPO_ROOT"/ "$INSTALL_DIR"/
fi
cd "$INSTALL_DIR"

# ---------------------------------------------------------------- 2. python deps
if "$PYTHON_BIN" -c 'import websocket' >/dev/null 2>&1; then
  log "websocket-client: ok"
else
  log "installing websocket-client into $PYTHON_BIN"
  "$PYTHON_BIN" -m pip install -q websocket-client \
    || warn "pip install failed — API routes to bridge.py will fail until fixed"
fi

# ---------------------------------------------------------------- 3. js deps
if [ -d node_modules ]; then
  log "node_modules: ok"
else
  log "installing js dependencies (bun install)"
  bun install
fi

# ---------------------------------------------------------------- 4. database
if [ ! -f db/custom.db ]; then
  log "creating SQLite database (prisma db push)"
  bun run db:push >/dev/null
else
  log "database: ok"
fi

# ---------------------------------------------------------------- 5. browser stack
export TARGET_URL
log "starting Xvfb + Chrome (target: $TARGET_URL)"
PYTHON="$PYTHON_BIN"
[ -x "$PYTHON" ] || PYTHON=python3
"$PYTHON" scripts/start_stack.py

# ---------------------------------------------------------------- 6. dev server
if curl -sf -o /dev/null http://127.0.0.1:3000/; then
  log "dev server: already up on :3000"
else
  log "starting dev server on :3000"
  nohup bun run dev >>dev.log 2>&1 &
fi
for _ in $(seq 1 40); do
  curl -sf -o /dev/null http://127.0.0.1:3000/ && break
  sleep 1.5
done
if curl -sf -o /dev/null http://127.0.0.1:3000/; then
  log "dev server: up on :3000"
else
  warn "dev server did not answer on :3000 yet — check dev.log"
fi

# ---------------------------------------------------------------- 7. watcher daemon
log "starting watcher (self-healing wrapper)"
"$PYTHON" scripts/start_watcher.py

# ---------------------------------------------------------------- 8. verify
log "verification:"
"$PYTHON" scripts/bridge.py status || true
log "done — open the sandbox preview on port 3000 to see the console."
