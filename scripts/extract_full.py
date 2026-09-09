#!/usr/bin/env python3
"""extract_full.py — full-response extractor via CodeMirror editor states.

z.ai renders assistant code blocks as CodeMirror 6 editors. The DOM shows
only virtualized line windows, but the editor STATE holds the complete
document text. This extractor:

  1. locates the LAST [class*=chat-assistant] container,
  2. walks its markdown-prose structure in document order,
  3. for each CodeMirror block reads el.cmView.view.state.doc.toString(),
  4. for prose elements reads innerText,
  5. assembles the full message text (code blocks fenced) and parses it with
     the same path-anchor parser as harvest_report.py.

Usage: extract_full.py <session-name>
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
LANG_LINE_RE = re.compile(r"^(rust|toml|json|yaml|text|bash|sh|markdown|md)$", re.IGNORECASE)

WALK_JS = """(() => {
  const cs = [...document.querySelectorAll('[class*=chat-assistant]')];
  if (!cs.length) return JSON.stringify({error: 'no-assistant'});
  const parts = [];
  function walk(node) {
    for (const child of node.childNodes) {
      if (child.nodeType === Node.ELEMENT_NODE) {
        const cls = String(child.className || '');
        if (/^(BUTTON|SVG|svg)$/.test(child.tagName)) continue;
        if (cls.includes('cm-editor') || (child.querySelector && child.querySelector('.cm-editor'))) {
          const cm = child.querySelector('.cm-content');
          let code = '';
          if (cm && cm.cmView && cm.cmView.view) {
            try { code = cm.cmView.view.state.doc.toString(); } catch (e) { code = ''; }
          }
          parts.push({t: 'code', header: '', v: code});
        } else if (cls.includes('markdown-prose')) {
          continue;
        } else {
          const hasBlock = child.querySelector && child.querySelector('.cm-editor');
          if (hasBlock) { walk(child); continue; }
          const txt = (child.innerText || '').trim();
          if (txt) parts.push({t: 'text', v: txt});
        }
      }
    }
  }
  for (const cont of cs) {
    const prose = cont.querySelector('.markdown-prose') || cont;
    walk(prose);
  }
  return JSON.stringify({n: parts.length, parts: parts});
})()"""


def parse_files(text):
    """Files = the first fenced code block after each path-anchor line.

    The flattened text wraps every CodeMirror block in ``` fences; a path
    anchor (a line that is just a repo path) precedes its block. Taking the
    fenced block (instead of everything up to the next anchor) prevents
    trailing prose/reports from being glued into the last file.
    """
    lines = text.split("\n")
    anchors = []
    for i, ln in enumerate(lines):
        m = PATH_RE.match(ln.strip())
        if m and "/" in m.group(1):
            anchors.append((i, m.group(1)))
    files = {}
    report_end = anchors[0][0] if anchors else len(lines)
    report = "\n".join(lines[:report_end]).strip()
    for (i, path) in anchors:
        block = None
        j = i + 1
        while j < len(lines):
            s = lines[j].strip()
            if s == "```":
                end = j + 1
                while end < len(lines) and lines[end].strip() != "```":
                    end += 1
                if end < len(lines):
                    block = lines[j + 1:end]
                break
            m2 = PATH_RE.match(s)
            if m2 and "/" in m2.group(1):
                break  # next anchor: this one has no code block
            j += 1
        if not block:
            continue
        if block and LANG_LINE_RE.match(block[0].strip()):
            block = block[1:]
        while block and not block[0].strip():
            block.pop(0)
        while block and not block[-1].strip():
            block.pop()
        if len(block) >= 3:
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
    c = channel.CDP(tab["webSocketDebuggerUrl"], timeout=60)
    try:
        # scroll sweep: the transcript virtualizes turns — render every window
        # (top -> bottom) and collect parts from each position
        parts = []
        seen = set()
        for pos in (0.0, 0.12, 0.25, 0.4, 0.55, 0.7, 0.85, 1.0):
            try:
                c.eval(
                    "(() => { const sc = document.querySelector('[class*=scroll]') ||"
                    f" document.scrollingElement; sc.scrollTop = sc.scrollHeight * {pos}; return 1; }})()",
                    timeout=8)
            except Exception:
                pass
            time.sleep(1.2)
            try:
                raw = c.eval(WALK_JS, timeout=45)
                d = json.loads(raw)
            except Exception as e:
                print(f"  [scroll {pos}] walk failed: {e!r}"[:90])
                continue
            if "error" in d:
                continue
            for p in d.get("parts") or []:
                key = (p["t"], hash(p["v"]))
                if key in seen:
                    continue
                seen.add(key)
                parts.append(p)
        if not parts:
            print("error: no parts collected")
            return 3
    finally:
        c.close()

    out = []
    for p in parts:
        if p["t"] == "code":
            out.append("\n```\n" + p["v"] + "\n```\n")
        else:
            out.append(p["v"] + "\n")
    text = "\n".join(out)
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    raw_path = os.path.join(OUTDIR, f"{name}-full-{stamp}.txt")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"extracted {len(text)} chars -> {raw_path} (code blocks: "
          f"{sum(1 for p in parts if p['t'] == 'code')})")

    report, files = parse_files(text)
    files_dir = os.path.join(OUTDIR, f"{name}-full-files")
    for p, content in files.items():
        dest = os.path.join(files_dir, p)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(content)
    print(f"files -> {files_dir}: {len(files)}")
    for p in sorted(files):
        print(f"  {p}  ({len(files[p])} chars, {files[p].count(chr(10))+1} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
