#!/usr/bin/env python3
"""Idempotent launcher for the replay stack: Xvfb (:99) + Chrome (CDP :9222).

Usage: /home/z/.venv/bin/python3 /home/z/my-project/scripts/start_stack.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import channel  # noqa: E402
from procs import chrome_up, ensure_dirs, start_chrome, start_xvfb, xvfb_up  # noqa: E402


def main():
    ensure_dirs()
    if not xvfb_up():
        print("starting Xvfb ...")
        start_xvfb()
        time.sleep(1.0)
    else:
        print("Xvfb already up")
    if not chrome_up():
        print("starting Chrome ...")
        start_chrome()
    else:
        print("Chrome already up")
    for _ in range(30):
        if chrome_up():
            break
        time.sleep(0.5)
    print("xvfb_up:", xvfb_up(), "| chrome_up:", chrome_up())
    for t in channel.list_tabs():
        print("tab:", t.get("id"), "|", (t.get("title") or "")[:60], "|", t.get("url"))


if __name__ == "__main__":
    main()
