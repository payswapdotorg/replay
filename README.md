# Replay Console

A deployable **remote-browser-control console** (a "replay"): a web page that
live-mirrors a headless Chrome and lets a human operate it from anywhere —
click, **drag (streamed in real time)**, type, scroll, switch tabs, log in —
including slider-captcha verification.

Deploy the whole stack into a fresh sandbox with one command and a one-line
login; no rebuilding.

## Stack

```
Xvfb :99 ── Chrome (CDP :9222, persistent profile scripts/browser-profile)
                 │
                 ├── replayd :3100   persistent CDP daemon: frames ~100ms,
                 │                  streamed dragstart/dragmove/dragend (~5ms)
                 │
                 └── watcher ⇄ supervisor   mutual-watchdog pair: each restarts
                    the other if it dies; they also relaunch Chrome, replayd
                    and the console. Logs self-rotate.

Next.js console :3000  (/) ── frame/event/tabs/status/inbox routes proxy to
                 replayd with a bridge.py spawn fallback.
```

- Console UI: live replay image (native pointer listeners — React synthetic
  handlers proved unreliable), amber drag guide, click feedback line with the
  probed target element, tab bar with auto-focus of new tabs, keyboard box
  (no auto-Enter), message thread to the resident agent.
- Clicks are sent as **fractions** (fx/fy 0..1); the daemon maps them with the
  live viewport (`Page.getLayoutMetrics`) — immune to image-size/scale skew.
- `scripts/dispatch_worker.py` — create named chat sessions in the browser
  (new tab → navigate → type prompt → Enter → verify in DOM) and check them.
  Useful for dispatching work to AI chat sessions living inside the replay.

## Deploy (fresh sandbox)

```bash
git clone https://github.com/payswapdotorg/replay2.git
cd replay2
./deploy.sh
```

`deploy.sh` is **idempotent** — every component is health-checked and only
started when missing; re-running is always safe.

Requirements (present in the standard sandbox): `bun`, `python3` +
`websocket-client` (auto-installed if missing), `Xvfb`, and a Chrome/Chromium
binary (playwright cache auto-discovered; else set `CHROME_BIN=...`).

After deploy:
1. Open the console (the preview panel / port 3000).
2. **Log in to the target site through the replay image** (click Sign in →
   Continue with Email → click the field → type in the box under the replay →
   slider captcha: press and drag slowly on the image, release when aligned).
   The session persists in `scripts/browser-profile` across stack restarts
   (not across sandbox resets — re-login after a reset).

Optional: `cp scripts/env.sh.example scripts/env.sh` and set `REPO=owner/name`
to get a branch/PR summary card in the console.

### Environment variables

| var | default | effect |
|---|---|---|
| `REPLAY_PORT` | `3000` | console port |
| `CDP_PORT` | `9222` | Chrome DevTools port |
| `REPLAYD_PORT` | `3100` | replay daemon port |
| `CHROME_BIN` | auto | chrome binary for launch_stack.py |
| `REPLAY_START_URL` | `https://chat.z.ai/` | first page in the browser |
| `REPLAY_DISPLAY` / `REPLAY_WxH` | `:99` / `1440x900` | Xvfb settings |
| `SKIP_BROWSER=1` | — | console-only redeploy |
| `SKIP_SUPERVISOR=1` | — | don't start watchdogs (parallel test) |

Set all three `*_PORT` vars to run a fully isolated second deployment
beside an existing one (e.g. `REPLAY_PORT=3005 CDP_PORT=9223 REPLAYD_PORT=3101
REPLAY_DISPLAY=:98 ./deploy.sh`).

## Verify a deployment

```bash
curl -s http://127.0.0.1:3100/healthz        # {"ok":true,...}
curl -s http://127.0.0.1:9222/json/version   # Chrome CDP
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/   # 200
curl -s http://127.0.0.1:3000/api/status     # browser_login state
```

Then in the browser: the replay image renders, clicking shows a green ripple +
`clicked → <element>` feedback, a drag shows the amber guide line and the page
follows it live.

## Troubleshooting

- **Stale/frozen page** → hard-refresh the console (Ctrl+Shift+R); check the
  version badge. If frames still don't update: `curl :3100/healthz`; the
  watcher auto-restarts a dead replayd within ~2 min.
- **Clicks land wrong** → toggle **DOM click** mode in the replay header.
- **Login popup events go to the wrong tab** → click the tab in the tab bar
  (new tabs get a ✦ badge and auto-focus).
- **Typing goes nowhere** → the daemon auto-focuses the first visible input;
  click the field first, then type.
- **Everything dead** → re-run `./deploy.sh` (idempotent). The supervisor and
  watcher mutually resurrect each other, so this is rarely needed.
- Logs: `scripts/logs/`, `scripts/watcher.log`, `scripts/dev.log`,
  `scripts/browser.log`.

## Self-test

`python3 scripts/test_drag.py` runs the full pointer pipeline
(pointerdown → held moves → pointerup) against a data-URL test page and
asserts the events landed — proves drag streaming before you trust it with a
captcha.
