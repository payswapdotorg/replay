# Resident Agent Worklog

Shared worklog for all agents. Append-only; every section starts with `---`.

---
Task ID: 1
Agent: resident-agent (main)
Task: Verify environment facts (project dir, chrome binary, python, Xvfb, dev server)

Work Log:
- Confirmed /home/z/my-project is a Next.js 16 + TS + Tailwind project; dev server already running on port 3000 (HTTP 200), dev.log clean.
- Confirmed Chrome for Testing at /home/z/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome.
- Confirmed /home/z/.venv/bin/python3 with websocket-client; Xvfb at /usr/bin/Xvfb; bun + setsid + curl available.
- Git repo present; no scripts/ dir or worklog.md yet — created both.

Stage Summary:
- All environment prerequisites for the replay stack are satisfied.

---
Task ID: 2
Agent: resident-agent (main)
Task: §1.1–1.2 Start Xvfb + Chrome with CDP (port 9222, persistent profile)

Work Log:
- Wrote scripts/procs.py (detached process management: start_xvfb / start_chrome / start_dev, pid files, logs).
- Ran scripts/start_stack.py: Xvfb :99 (1440x900x24) up; Chrome started with --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --user-data-dir=scripts/browser-profile --no-sandbox --no-first-run --no-default-browser-check --window-size=1440,900 https://chat.z.ai/.
- Verified CDP HTTP endpoint /json/version responds; one tab open at chat.z.ai.

Stage Summary:
- Headed Chrome under Xvfb reachable on 127.0.0.1:9222 with a persistent profile (login survives restarts).

---
Task ID: 3
Agent: resident-agent (main)
Task: §1.3–1.4 channel.py + bridge.py (frame / event / tabs / status)

Work Log:
- scripts/channel.py: list_tabs (type=="page"), new_tab (PUT /json/new, GET fallback), find_tab (pattern → chat.z.ai → first), CDP class (request/response over ws, event frames skipped, Runtime.evaluate with returnByValue).
- Fixed CDP WS 403: Chrome DevTools rejects Origin headers — create_connection(..., suppress_origin=True).
- scripts/bridge.py: frame (Page.enable + captureScreenshot jpeg q75, RAW bytes to stdout), event (click/dblclick via mousePressed+Released, scroll via mouseWheel, type via Input.insertText, key/enter via keyDown+keyUp with windowsVirtualKeyCode, nav, reload), tabs, status (login heuristic from body.innerText + heartbeat ages).
- Both frame and event resolve the ACTIVE tab (scripts/flags/active_tab.txt → chat.z.ai → first tab).
- Verified: 62KB valid JPEG; nav to scripts/testpage.html; clicks land exactly (center + top-left calibration buttons); insertText typed into the page input; viewport measured 1439x756 (≠ requested 1440x900 — confirms natural-size mapping requirement).

Stage Summary:
- Full CDP bridge verified end-to-end against the calibration page.

---
Task ID: 4
Agent: resident-agent (main)
Task: §1.5 watcher.py + start_stack.py, launch watcher detached

Work Log:
- scripts/watcher.py: 60s cycle — restarts dead Xvfb/Chrome/dev-server, auto-accepts JS dialogs (Page.handleJavaScriptDialog accept:true on active tab, errors ignored), auto-selects exactly-one newly created tab (auth popups), logs new operator messages with its own watermark, maintains session_registry.json for chat.z.ai tabs (>3 warns).
- scripts/start_stack.py: idempotent launcher.
- Watcher started detached (setsid), pid scripts/watcher.pid, log scripts/watcher.log, heartbeat scripts/flags/watcher_heartbeat touched.

Stage Summary:
- Watchdog is autonomous: process restarts, dialog handling, new-tab focus, message logging.

---
Task ID: 5
Agent: resident-agent (main)
Task: §2 console API routes (frame/event/tabs/inbox/status)

Work Log:
- src/lib/bridge.ts: runBridge (text) + runBridgeBuffer (encoding:'buffer' — binary-safe for screenshots; known bug: routing JPEG through a string corrupts it).
- /api/frame GET → JPEG, Content-Type image/jpeg, Cache-Control no-store, 502 on failure (client keeps last frame).
- /api/event POST → validates type whitelist (click|dblclick|type|key|enter|scroll|nav|reload), sanitizes numbers/text/url, runs bridge.py event.
- /api/tabs GET/POST → tab list + active; POST persists id to scripts/flags/active_tab.txt after verifying the tab exists.
- /api/inbox GET/POST → merges operator_inbox.jsonl + agent_outbox.jsonl sorted by ts; POST appends {ts, from:"operator", text} (1..4000 chars).
- /api/status GET → bridge.py status passthrough.
- All routes: dynamic force-dynamic, nodejs runtime.
- Verified with curl: frame 200 image/jpeg (two polls differ → live); tabs/status/inbox/event all OK; bad type rejected 400.

Stage Summary:
- All five API routes work; frame route is buffer-safe by construction.

---
Task ID: 6
Agent: resident-agent (main)
Task: §2 console UI on / (replay + tab chips + thread + status, sticky footer)

Work Log:
- src/app/page.tsx: left = live replay (blob URLs with revocation, poll 2.5s, keep last frame on error, tab chips nav, click-to-interact using img.naturalWidth/naturalHeight — NEVER hardcoded viewport, scroll arrows, reload + chat.z.ai quick-nav, "type into the page" box → insertText + Enter); right = status card (processes, active tab, login, heartbeats) + operator⇄agent thread (poll 4s, auto-scroll, newest last) with textbox.
- Sticky footer via min-h-screen flex flex-col + footer mt-auto; responsive (lg side-by-side, mobile stacked); semantic HTML (header/main/section/aside/nav/footer, aria labels, role=log thread); shadcn/ui Card/Button/Input/Badge/Skeleton; lucide icons; no blue/indigo (emerald/amber/rose accents).
- globals.css: .thin-scroll custom scrollbar for tab bar + thread.
- bun run lint: clean.

Stage Summary:
- Console UI complete on the only user-visible route /.

---
Task ID: 7
Agent: resident-agent (main)
Task: §5 self-verification with agent-browser

Work Log:
- agent-browser opened http://127.0.0.1:3000/; a11y snapshot shows header, replay region, tab chip, clickable image, scroll/reload/chat.z.ai buttons, both textboxes.
- img loaded: naturalWidth 1439 / naturalHeight 756 (real viewport, rendered responsive).
- E2E click mapping: synthetic MouseEvent on the img at fraction (180/1439, 124/756) → replay Chrome's test page registered "TOP-LEFT HIT" — pixel-exact, no offset.
- E2E typing: click input focus point via img + "Type into the page" box → page input received full text (status "TYPED: …").
- E2E operator message: filled "Message the agent" + clicked Send → operator_inbox.jsonl gained the message; GET /api/inbox returns merged thread.
- Tab switching: created second tab (channel.new_tab) → both chips render; clicked chips → active tab persisted and frame/events followed; quick-nav "chat.z.ai" button navigated the active tab.
- Footer: 1920x1080 → docScrollH 1080 = viewport, footer bottom 1080, gap 0 (sticks); 390x844 → stacked layout, page scrolls, footer pushed naturally; agent-browser errors: none; dev.log: no errors.
- VLM check of screenshots: layout as designed, no broken images/overlaps; "Not logged in" badge correct (operator has not logged in yet).
- Cleaned up: closed the extra test tab, restored the main tab to https://chat.z.ai/.

Stage Summary:
- Every §5 requirement verified in a real browser; golden path works end-to-end.

---
Task ID: 8
Agent: resident-agent (main)
Task: §3 durable state (worklog, recovery runbook, env.sh, session registry)

Work Log:
- scripts/RECOVERY.md: cold-start sequence, known gotchas (WS 403 suppress_origin, buffer encoding, natural-size click mapping, active-tab targeting, dialog auto-accept), chat.z.ai operating procedure, operator messaging protocol, restart matrix.
- scripts/env.sh created with chmod 600 (secrets ONLY here, never in prompts/logs/chat).
- scripts/flags/session_registry.json maintained by the watcher.

Stage Summary:
- Sandbox-reset recovery is documented and all state files are in place.

---
Task ID: 9
Agent: resident-agent (main)
Task: §3/§4 resident loop — operator inbox handling + chat.z.ai operations

Work Log:
- Watermark protocol armed: scripts/flags/agent_watermark.txt tracks the last handled operator_inbox line; every new message gets a reply in agent_outbox.jsonl.
- Heartbeat touched after every work unit (scripts/flags/heartbeat); console shows "agent last active".
- chat.z.ai state: operator NOT logged in yet — login must be performed by the operator through the replay panel (Sign in → Continue with email). Agent never handles credentials.
- Initial agent reply posted to the thread with login instructions.

Stage Summary:
- Resident loop active; waiting on operator login before §4 chat.z.ai session work can proceed.
