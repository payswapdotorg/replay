# Recovery Runbook — Resident Agent / Browser Replay / Operator Console

The sandbox can RESET at any time (total filesystem loss). Durable state =
the remote git repo + this runbook + `worklog.md` + the conversation
transcript. Everything below is rebuildable from scratch.

## What the stack consists of

| Piece | File / Location | Notes |
|---|---|---|
| Xvfb :99 | `scripts/xvfb.{pid,log}` | 1440x900x24 virtual display |
| Chrome (CDP 9222) | `scripts/browser.{pid,log}`, profile `scripts/browser-profile/` | persistent profile → operator login survives restarts |
| CDP client | `scripts/channel.py` | list_tabs / new_tab / find_tab / CDP class (suppress_origin!) |
| CLI bridge | `scripts/bridge.py` | frame / event / tabs / status — used by the console API routes |
| Watchdog | `scripts/watcher.py` (pid `scripts/watcher.pid`, log `scripts/watcher.log`) | 60s cycle: restarts, dialog auto-accept, new-tab auto-select, operator msg log, session registry |
| Process mgr | `scripts/procs.py` | start_xvfb / start_chrome / start_dev, all detached (start_new_session) |
| Console | `src/app/page.tsx` + `src/app/api/{frame,event,tabs,inbox,status}/route.ts` | Next.js on port 3000, the ONLY user-visible route |
| Flags | `scripts/flags/` | active_tab.txt, operator_inbox.jsonl, agent_outbox.jsonl, heartbeat, watcher_heartbeat, seen_tabs.json, session_registry.json, last_account.txt, watermarks |
| Secrets | `scripts/env.sh` (chmod 600) | NEVER in prompts, logs, chat, or git |

## Cold-start sequence (after a sandbox reset)

```bash
cd /home/z/my-project

# 1. dev server (if not already supervised by the platform)
setsid bun run dev >> dev.log 2>&1 < /dev/null &
sleep 5 && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/   # expect 200

# 2. Xvfb + Chrome
/home/z/.venv/bin/python3 scripts/start_stack.py

# 3. watcher (detached)
setsid /home/z/.venv/bin/python3 scripts/watcher.py >> scripts/watcher_stdout.log 2>&1 < /dev/null &
sleep 1; pgrep -f "scripts/watcher.py" > scripts/watcher.pid

# 4. heartbeat + sanity checks
touch scripts/flags/heartbeat
curl -s http://127.0.0.1:3000/api/status | python3 -m json.tool
```

## Known gotchas (debug in this order)

1. **WS handshake 403 from CDP** — websocket-client must use
   `create_connection(url, suppress_origin=True)` (Chrome rejects Origin
   headers). Already handled in `channel.py`.
2. **Corrupted screenshots** — `bridge.py frame` writes RAW BYTES to stdout;
   the Next.js route MUST exec it with `encoding: 'buffer'` (see
   `src/lib/bridge.ts`). Routing binary through a string corrupts JPEGs.
3. **Click offsets / broken logins** — the replay `<img>` click handler must
   map coordinates via `img.naturalWidth/naturalHeight` (real viewport is
   1439x756, NOT the requested 1440x900). Never hardcode viewport numbers.
4. **Events going to the wrong tab** — `bridge.py` always targets the ACTIVE
   tab from `scripts/flags/active_tab.txt`. The watcher auto-selects newly
   created tabs (auth popups); the operator can switch back via tab chips.
5. **Dialogs blocking the page** ("Reload site?" / beforeunload) — the
   watcher calls `Page.handleJavaScriptDialog {accept:true}` on the active
   tab every cycle and ignores the no-dialog error.
6. **Chrome zombie** — check `scripts/browser.pid`; `procs.pid_alive` treats
   zombies as dead, the watcher restarts it.
7. **Login state** — detected heuristically from `document.body.innerText`
   (email / "sign in" / "sign out" markers); shown in the console header.
   The OPERATOR performs logins themselves through the replay panel.

## chat.z.ai operating procedure (per worker/task)

1. `channel.new_tab("https://chat.z.ai/")`, wait for load, confirm the chat
   input exists in the DOM.
2. Pick the model FIRST: click the model selector, read options from the DOM,
   click the intended model, verify the selector label changed.
3. Send a prompt: click the chat input, `Input.insertText` the FULL prompt,
   then Enter (keyDown/keyUp, code "Enter", windowsVirtualKeyCode 13).
   VERIFY the send: `document.body.innerText` must contain a distinctive
   snippet of the prompt; else retry (focus → insert → Enter).
4. Re-resolve tabs before every injection (tab IDs change on navigation);
   match by URL/title. Monitor the tab (innerText + screenshots) afterwards.
5. Keep ≤ 3 concurrent chat.z.ai sessions; URLs go to
   `scripts/flags/session_registry.json` so tab loss is recoverable.

## Operator messaging protocol

- Operator sends via the console textbox → POST /api/inbox →
  `scripts/flags/operator_inbox.jsonl` ({ts, from:"operator", text}).
- The agent reads that file with a WATERMARK
  (`scripts/flags/agent_watermark.txt` — line number of the last handled
  message), handles EVERY new message, and replies by appending
  `{ts, from:"agent", text}` to `scripts/flags/agent_outbox.jsonl`.
- Both files are merged (sorted by ts) by GET /api/inbox and rendered in the
  console thread. Heartbeat: `touch scripts/flags/heartbeat` after every
  work unit — the console shows "agent last active …".

## Restart matrix

| Symptom | Fix |
|---|---|
| Console 502 on /api/frame | Chrome down → `start_stack.py`; check `scripts/browser.log` |
| Frame frozen | watcher dead → restart watcher; else check active tab |
| Clicks land wrong | check naturalWidth mapping in page.tsx; check active tab chip |
| Login bounces to home | wrong tab active (switch chip) or stale frame (wait 2.5s) |
| Dev server dead | `setsid bun run dev >> dev.log 2>&1 &` (single instance only!) |
