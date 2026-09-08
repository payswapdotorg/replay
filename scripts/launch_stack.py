"""launch_stack.py — start Xvfb + Chrome (CDP :9222) for the replay.

Relocatable + configurable via env:
  REPLAY_DISPLAY   (default :99)
  REPLAY_WxH       (default 1440x900)
  CHROME_BIN       (default: auto-discover playwright chromium / system chrome)
  REPLAY_START_URL (default https://chat.z.ai/)
  CDP_PORT         (default 9222)

The browser profile persists in scripts/browser-profile (gitignored) so
logins survive restarts of this script (but NOT sandbox resets — logins are
per-sandbox; operators log in through the console after a fresh deploy).
"""
import glob
import os
import subprocess
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

DISPLAY = os.environ.get("REPLAY_DISPLAY", ":99")
SCREEN = os.environ.get("REPLAY_WxH", "1440x900")
CDP_PORT = os.environ.get("CDP_PORT", "9222")
START_URL = os.environ.get("REPLAY_START_URL", "https://chat.z.ai/")
PROFILE = os.path.join(BASE, "browser-profile")


def find_chrome():
    """CHROME_BIN env -> playwright cache glob -> system chrome."""
    cand = os.environ.get("CHROME_BIN", "")
    if cand and os.path.exists(cand):
        return cand
    for pat in (
        os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome"),
        os.path.expanduser("~/.cache/ms-playwright/chrome-linux*/chrome"),
        "/usr/bin/google-chrome*",
        "/usr/bin/chromium*",
    ):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return ""


chrome = find_chrome()
if not chrome:
    print("ERROR: no chrome/chromium binary found. Set CHROME_BIN=/path/to/chrome")
    raise SystemExit(1)
print("chrome:", chrome)

# 1. Xvfb (a duplicate display bind simply fails and exits — harmless)
p1 = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", f"{SCREEN}x24"],
    stdout=open(os.path.join(BASE, "xvfb.log"), "w"), stderr=subprocess.STDOUT,
    start_new_session=True)
open(os.path.join(BASE, "xvfb.pid"), "w").write(str(p1.pid))
time.sleep(2)

# 2. Chrome with CDP
env = dict(os.environ)
env["DISPLAY"] = DISPLAY
p2 = subprocess.Popen([chrome,
    f"--remote-debugging-port={CDP_PORT}", "--remote-debugging-address=127.0.0.1",
    "--remote-allow-origins=*", f"--user-data-dir={PROFILE}",
    f"--window-size={SCREEN.replace('x', ',')}", "--window-position=0,0",
    "--no-first-run", "--no-default-browser-check",
    "--disable-session-crashed-bubble", "--hide-crash-restore-bubble",
    "--disable-background-timer-throttling", "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding", "--disable-dev-shm-usage", "--disable-features=Translate",
    "--lang=en-US", "--no-sandbox", START_URL],
    stdout=open(os.path.join(BASE, "browser.log"), "w"), stderr=subprocess.STDOUT,
    start_new_session=True, env=env)
open(os.path.join(BASE, "browser.pid"), "w").write(str(p2.pid))
print(f"xvfb pid={p1.pid} chrome pid={p2.pid}")
time.sleep(8)
try:
    v = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=5).read()
    print("CDP OK:", v[:60])
except Exception as e:
    print("CDP not up yet:", e)
