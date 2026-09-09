#!/usr/bin/env python3
"""harvest_report.py — extract a worker session's response into structured files.

Strategy:
  1. Locate the LAST [class*=chat-assistant] container (the worker's answer).
  2. innerText is used (visible-only => skips the hidden Thought Process, and
     preserves rendered newlines). The chat virtualizes long messages, so we
     sample at several scroll positions and keep the LONGEST capture.
  3. The answer is parsed into files using path-line anchors
     (^codex-rs/... or any repo-looking path on its own line); an optional
     language-label line (rust/toml/…) right after the anchor is dropped.
     When a file is emitted more than once (model corrections), the LAST
     emission wins.
  4. Outputs:
     scripts/worker-reports/<name>-response-<stamp>.txt  (raw answer)
     scripts/worker-reports/<name>-files/<repo-path>     (parsed files)

Usage: harvest_report.py <session-name>
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import channel
import dispatch_worker as _dw

BASE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(BASE, "flags", "session_registry.jsonl")
OUTDIR = os.path.join(BASE, "worker-reports")

PATH_RE = re.compile(r"^((?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9]+)(\s*\([^)]*\))?\s*$")
LANG_LINE_RE = re.compile(r"^(rust|toml|json|yaml|text|bash|sh|markdown|md|rs|toml§)$", re.IGNORECASE)


def scroll_and_extract(c, pos):
    c.eval(
        "(() => { const sc = document.querySelector('[class*=scroll]') ||"
        f" document.scrollingElement; sc.scrollTop = sc.scrollHeight * {pos}; return 1; }})()",
        timeout=8)
    time.sleep(1.5)
    return c.eval(
        "(() => { const cs = [...document.querySelectorAll('[class*=chat-assistant]')];"
        " const cont = cs[cs.length-1]; return (cont && cont.innerText) || ''; })()",
        timeout=25) or ""


def capture(tab):
    best = ""
    for pos in (0, 0.35, 0.7, 1.0):
        c = channel.CDP(tab["webSocketDebuggerUrl"], timeout=30)
        try:
            txt = scroll_and_extract(c, pos)
        finally:
            c.close()
        if len(txt) > len(best):
            best = txt
    return best


def parse_files(text):
    """Split the answer into (report_text, {path: content}).

    Guards: a run of CONSECUTIVE path lines (gap <= 2 lines) is a summary
    LIST, not an emission — skipped. Real emissions have >= 3 lines of
    content before the next anchor. When a file is emitted more than once
    (model corrections), the LAST real emission wins.
    """
    lines = text.split("\n")
    anchors = []  # (line_idx, path)
    for i, ln in enumerate(lines):
        m = PATH_RE.match(ln.strip())
        if m and "/" in m.group(1):
            anchors.append((i, m.group(1)))
    # classify: real emission vs summary-list entry
    real = []
    for k, (i, path) in enumerate(anchors):
        end = anchors[k + 1][0] if k + 1 < len(anchors) else len(lines)
        gap = end - (i + 1)
        if gap >= 3:  # has actual content -> emission
            real.append((i, path, end))
    files = {}
    report_end = anchors[0][0] if anchors else len(lines)
    report = "\n".join(lines[:report_end]).strip()
    for k, (i, path, end) in enumerate(real):
        block = lines[i + 1:end]
        # drop an immediately following language-label line
        if block and LANG_LINE_RE.match(block[0].strip()):
            block = block[1:]
        # trim leading/trailing empties
        while block and not block[0].strip():
            block.pop(0)
        while block and not block[-1].strip():
            block.pop()
        files[path] = "\n".join(block) + "\n"
    return report, files


def main(name):
    s = _dw._find(name)
    if not s:
        print(f"no session {name}")
        return 1
    tab = _dw._tab_for(s)
    if not tab:
        print(f"tab LOST for {name}")
        return 2

    text = capture(tab)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    os.makedirs(OUTDIR, exist_ok=True)
    raw_path = os.path.join(OUTDIR, f"{name}-response-{stamp}.txt")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"captured {len(text)} chars -> {raw_path}")

    report, files = parse_files(text)
    files_dir = os.path.join(OUTDIR, f"{name}-files")
    for p, content in files.items():
        dest = os.path.join(files_dir, p)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(content)
    rep_path = os.path.join(OUTDIR, f"{name}-report-{stamp}.md")
    with open(rep_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"report  -> {rep_path} ({len(report)} chars)")
    print(f"files   -> {files_dir}: {len(files)} files")
    for p in sorted(files):
        print(f"  {p}  ({len(files[p])} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
