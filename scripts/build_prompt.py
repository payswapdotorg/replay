#!/usr/bin/env python3
"""build_prompt.py — generate WO worker prompts (contract + packet + source bundle).

Usage:
  build_prompt.py WO-010 <repo-path> <base-sha>   -> worker-prompts/WO-010-chat.md

The source bundle: VERBATIM for boundary-critical files, SIGNATURES (bodies
stripped: struct fields + enum variants kept, fn bodies dropped) for the rest.
"""
import os
import re
import sys
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
PROMPTS = os.path.join(BASE, "worker-prompts")


# ------------------------------------------------------- signature digests --

def rust_signatures(src: str) -> str:
    """Strip Rust bodies, keep the type-level contract.

    Kept: doc comments, attributes, use/mod lines, item headers, struct
    fields, enum variants, method signatures. Dropped: fn bodies, private
    (non-pub) members inside impl blocks, plain comments.
    """
    lines = src.split("\n")
    out = []
    depth = 0
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()
        # comments
        if s.startswith("//") and not s.startswith("///") and not s.startswith("//!"):
            i += 1
            continue
        # skip string literals that confuse brace counting: not needed for our style
        opens = line.count("{") - line.count("}")
        if s.startswith("#[") or s.startswith("#![") or s.startswith("///") or s.startswith("//!"):
            out.append(line)
            i += 1
            continue
        if depth == 0:
            if not s:
                out.append("")
                i += 1
                continue
            if s.startswith("pub ") or s.startswith("pub(") or s.startswith("impl ") or \
               s.startswith("use ") or s.startswith("mod ") or s.startswith("type ") or \
               s.startswith("const ") or s.startswith("static "):
                out.append(line)
                if opens > 0:
                    # entering a body: enum/struct/impl/trait/fn
                    depth += opens
                    i += 1
                    # struct/enum/trait/impl: keep members; fn: drop body
                    header = s
                    is_fn = re.search(r"\bfn\b", header.split("{")[0])
                    is_impl = header.startswith("impl")
                    if is_fn and not is_impl:
                        _skip_body(lines, i, out)
                        i = _match_close(lines, i, depth)
                        depth = 0
                else:
                    i += 1
                continue
            # non-pub top-level (fn, struct...) — skip entirely
            if opens > 0:
                i = _match_close(lines, i + 1, 1)
            else:
                i += 1
            continue
        # depth > 0: inside an impl/trait/struct/enum
        if opens != 0 or "{" in line or "}" in line:
            pass
        if s.startswith("}") and depth + opens <= 0:
            out.append("}")
            depth = 0
            i += 1
            continue
        # member lines
        if not s or s.startswith("#[") or s.startswith("///"):
            out.append(line)
            i += 1
            continue
        if s.startswith("pub ") or s.startswith("pub("):
            out.append(line)
            if opens > 0:
                depth += opens
                i += 1
                if re.search(r"\bfn\b", s.split("{")[0]):
                    _skip_body(lines, i, out)
                    i = _match_close(lines, i, depth - 1) if depth - 1 > 0 else i
                    # fall back to brute-force resync below
                    i, depth = _resync(lines, i, out)
                continue
            i += 1
            continue
        # struct fields / enum variants (indented, no 'pub') — keep
        if re.match(r"^[a-z_][a-z0-9_]*\s*[:,(=]", s) or s.startswith("_"):
            out.append(line)
        i += 1
    # collapse >2 consecutive blank lines
    cleaned = []
    blanks = 0
    for l in out:
        if not l.strip():
            blanks += 1
            if blanks <= 1:
                cleaned.append("")
        else:
            blanks = 0
            cleaned.append(l)
    return "\n".join(cleaned).strip() + "\n"


def _skip_body(lines, i, out):
    """Emit a '...' body placeholder is NOT wanted; just skip."""


def _match_close(lines, i, depth):
    return i  # placeholder — resync handles it


def _resync(lines, i, out):
    """Brute-force: skip until braces return to a sane member level."""
    d = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        d += line.count("{") - line.count("}")
        if d <= 0:
            return i + 1, 0
        i += 1
    return i, 0


# ------------------------------------------------------------ file reading --

def read_file(repo, rel):
    p = os.path.join(repo, rel)
    if not os.path.exists(p):
        return None
    return open(p, encoding="utf-8").read()


def file_lines(repo, rel):
    p = os.path.join(repo, rel)
    if not os.path.exists(p):
        return 0
    return sum(1 for _ in open(p, encoding="utf-8"))


# ------------------------------------------------------------------ prompt --

WO010_CONTRACT_HEAD = """You are WO-010 Worker — an implementation specialist dispatched by the Tech Lead for payswapdotorg/codex. Work autonomously until the Work Order is implemented, tested, and fully reported.

ROLE
Implement exactly WO-010 (Workflow Application Integration and End-to-End Runtime). You are not the architect and may not invent product scope, architecture, semantic contracts, or parallel runtimes.

ENVIRONMENT
You have NO shell, git, or cargo. The Tech Lead applies your output, builds, tests, and merges.
Produce COMPLETE file contents as fenced code blocks, each preceded by its path line.
Tests: inline #[cfg(test)] modules, static-only (the Tech Lead compiles and runs them).
Commit message for the Tech Lead: feat(workflow-app): WO-010 workflow application integration and e2e runtime.
Expected shape (verify against the bundle — do not trust this blindly): a new leaf crate
codex-rs/workflow-app (lib codex_workflow_app) that wires the workflow planes
(contracts + forge + teaching-compiler + browser-use + computer-use + execution
contracts) into application-facing lifecycle services WITHOUT touching the app-server
crate itself unless a thin seam file is unavoidable; plus one members line in
codex-rs/Cargo.toml. Integration tests live in the new crate's tests/ directory
(static-only here). If the real tree differs, adapt and say so in the report.

DESIGN GUIDANCE (from the Tech Lead; verify against the bundle first)
- A WorkflowLifecycle service in the new crate: select an immutable WorkflowVersion,
  instantiate (validate → approve → bind), run across environment classes via the
  execution-contracts abstractions, observe/emit events, and support recover/escalate.
- No second engine: all semantics delegate to the frozen contract types; the app layer
  composes them. No durable state owned by this crate — state stays behind control-plane
  seams (model them as ports/traits; in-memory implementations for tests).
- Mixed-environment runs: compose browser-use and computer-use adapters through the
  execution-contracts capability/resource readiness, approvals, evidence, and recovery
  records. Ordinary-codex compatibility: when no workflow is active, none of this code
  executes (a no-op default path).
- E2E tests (static): create → validate → publish → install → run (mixed env) →
  recover → verify, plus failure/recovery and approval/security cases mapped to the
  acceptance bullets.
"""

WO010_DELIVERABLES = """
DELIVERABLES (in this order):
1. codex-rs/workflow-app/Cargo.toml (name codex-workflow-app; lib codex_workflow_app; deps only on the bundled crates + serde/serde_json/thiserror/tokio only if async seams demand it)
2. codex-rs/workflow-app/src/*.rs — all modules fully implemented
3. codex-rs/workflow-app/tests/workflow_e2e.rs — the end-to-end integration tests
4. The exact workspace members line to add to codex-rs/Cargo.toml.
5. Then the === WO-010 COMPLETION REPORT === (Work Order ID; base SHA {base}; changed files; implementation summary; tests static-only: chat worker has no cargo — Tech Lead verifies; acceptance-criteria evidence mapped to each bullet; compatibility impact — especially that ordinary Codex behavior is untouched; known limitations).
"""

WO010_MANIFEST = {
    # rel path -> "verbatim" | "sig"
    "codex-rs/workflow-contracts/src/lib.rs": "verbatim",
    "codex-rs/workflow-contracts/src/repository.rs": "sig",
    "codex-rs/workflow-contracts/src/revision.rs": "sig",
    "codex-rs/workflow-contracts/src/manifest.rs": "sig",
    "codex-rs/workflow-contracts/src/version.rs": "sig",
    "codex-rs/workflow-contracts/src/dependency.rs": "sig",
    "codex-rs/workflow-contracts/src/lock.rs": "sig",
    "codex-rs/workflow-forge/src/lib.rs": "verbatim",
    "codex-rs/workflow-forge/src/collaboration.rs": "sig",
    "codex-rs/workflow-forge/src/github.rs": "sig",
    "codex-rs/workflow-forge/src/package.rs": "sig",
    "codex-rs/workflow-forge/src/install.rs": "sig",
    "codex-rs/workflow-forge/src/memory.rs": "sig",
    "codex-rs/teaching-compiler/src/lib.rs": "verbatim",
    "codex-rs/teaching-compiler/src/blueprint.rs": "sig",
    "codex-rs/teaching-compiler/src/session.rs": "sig",
    "codex-rs/browser-use-adapter/src/lib.rs": "verbatim",
    "codex-rs/computer-use-adapter/src/lib.rs": "verbatim",
    "codex-rs/execution-contracts/src/lib.rs": "verbatim",
}


def build_wo010(repo, base_sha):
    packet = read_file(repo, "docs/work-orders/WO-010.md")
    if not packet:
        print("ERROR: WO-010 packet not found in repo")
        return 1
    parts = []
    parts.append(WO010_CONTRACT_HEAD)
    parts.append("\nWORK ORDER PACKET — WO-010 (verbatim):\n")
    parts.append(packet.strip())
    parts.append("\n\nSOURCE BUNDLE @ base {} (authoritative):\n".format(base_sha[:16]))
    total = 0
    for rel, mode in WO010_MANIFEST.items():
        src = read_file(repo, rel)
        if src is None:
            print(f"WARN: {rel} missing — skipped")
            continue
        if mode == "verbatim":
            body = src
            tag = "verbatim"
        else:
            body = rust_signatures(src)
            tag = "signatures only"
        total += len(body)
        parts.append(f"\n--- {rel} ({tag}) ---\n\n```rust\n{body.strip()}\n```\n")
        print(f"  {rel}: {tag}, {len(body)} chars")
    parts.append(WO010_DELIVERABLES.replace("{base}", base_sha[:12]))
    prompt = "".join(parts)
    out = os.path.join(PROMPTS, "WO-010-chat.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(prompt)
    print(f"\nwrote {out}: {len(prompt)} chars (bundle {total})")
    return 0


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 1
    wo, repo, sha = sys.argv[1], sys.argv[2], sys.argv[3]
    if wo == "WO-010":
        return build_wo010(repo, sha)
    print(f"no builder for {wo}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
