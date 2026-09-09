#!/usr/bin/env python3
"""build_audit_prompts.py — wave-3 REDEPLOYMENT prompts (agents-tab audit sessions).

The operator ruled chat-tab sessions void; WO-006/007/008 must be redeployed
under the agents tab. Each redeployed session audits the merged crate against
its Work Order packet and produces the authoritative completion report.

Usage: build_audit_prompts.py <repo-path>
Writes worker-prompts/WO-00{6,7,8}-audit.md
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_prompt import rust_signatures, read_file

BASE = os.path.dirname(os.path.abspath(__file__))
PROMPTS = os.path.join(BASE, "worker-prompts")

WO_TARGETS = {
    "WO-006": ("browser-use-adapter", "codex_browser_use_adapter"),
    "WO-007": ("computer-use-adapter", "codex_computer_use_adapter"),
    "WO-008": ("teaching-compiler", "codex_teaching_compiler"),
}

HEAD_TMPL = """You are {wo} Worker — an implementation specialist dispatched by the Tech Lead for payswapdotorg/codex. Work autonomously until the audit is complete and fully reported.

REDEPLOYMENT CONTEXT (read carefully)
This Work Order was previously implemented through a session in the plain chat tab, which the operator has ruled NULL AND VOID. Your session — a full-stack agents-tab session — is now the AUTHORITATIVE work record for {wo}. The implementation itself is already merged into main; your job is to audit it against the Work Order, fix anything unsound, and deliver the authoritative completion report.

ENVIRONMENT
You have a sandbox with a shell. Get the REAL tree first, in this order:
1. `git clone --depth 1 https://github.com/payswapdotorg/codex` (public, anonymous, read-only), or
2. `curl -L https://github.com/payswapdotorg/codex/archive/refs/heads/main.tar.gz | tar xz` if git is unavailable.
3. If you have NO network at all, fall back to the SOURCE BUNDLE at the end of this prompt (lib.rs verbatim + module signatures) and say so in your report — audit depth will be limited to what the bundle shows.
Check `which cargo` — if a Rust toolchain exists you may compile/test the crate; otherwise verify compile-correctness by careful static reasoning (types, trait bounds, ownership, imports, test bodies).

AUDIT TASK (in order)
1. Map EVERY Required outcome in the packet below to the code that implements it (file + item names).
2. Check the Forbidden list — none may be violated anywhere in the crate.
3. Verify static compile-correctness of every module (imports resolve, types line up, trait bounds satisfied, ownership/moves correct).
4. Verify the acceptance criteria are covered by the crate's tests (inline #[cfg(test)] modules).
5. FIX any gap, defect, or forbidden-pattern you find: deliver the COMPLETE corrected file contents as a fenced code block, each preceded by its path line. Only corrected files — do not re-emit sound files.
6. Produce the authoritative completion report (format at the end).

WORK ORDER PACKET — {wo} (verbatim):
"""

TAIL_TMPL = """

SOURCE BUNDLE (fallback if the clone/tarball failed) — codex-rs/{crate}/src/:

--- codex-rs/{crate}/src/lib.rs (verbatim) ---

```rust
{libsrc}
```

--- codex-rs/{crate}/src/ module signatures ---

```rust
{sigs}
```

DELIVERABLES (in this order):
1. Corrected files ONLY if gaps were found (complete contents, path line before each fenced block). If the implementation is sound: state 'NO CORRECTIONS — implementation sound' and why.
2. Then the === {wo} COMPLETION REPORT === (Work Order ID; how you obtained the tree: clone/tarball/bundle; audit verdict per Required outcome — file+item mapping; Forbidden-list check result; compile-correctness verdict; acceptance evidence; files corrected or none; known limitations).
"""


def build(repo, wo, crate, _libname):
    packet = read_file(repo, f"docs/work-orders/{wo}.md")
    if not packet:
        print(f"ERROR: packet for {wo} not found")
        return 1
    libsrc = read_file(repo, f"codex-rs/{crate}/src/lib.rs")
    if not libsrc:
        print(f"ERROR: lib.rs for {crate} not found")
        return 1
    # signatures of the other modules (cap total size)
    sig_parts = []
    total = 0
    srcdir = os.path.join(repo, f"codex-rs/{crate}/src")
    for fn in sorted(os.listdir(srcdir)):
        if fn in ("lib.rs",) or not fn.endswith(".rs"):
            continue
        body = rust_signatures(open(os.path.join(srcdir, fn), encoding="utf-8").read())
        if total + len(body) > 30000:
            body = body[:5000] + "\n// … (truncated — clone the repo for the full module)\n"
        sig_parts.append(f"// ==== {fn} ====\n{body}")
        total += len(body)
    sigs = "\n\n".join(sig_parts)

    prompt = (HEAD_TMPL.format(wo=wo) + packet.strip()
              + TAIL_TMPL.format(wo=wo, crate=crate, libsrc=libsrc.strip(), sigs=sigs))
    out = os.path.join(PROMPTS, f"{wo}-audit.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(prompt)
    print(f"wrote {out}: {len(prompt)} chars (sigs {total})")
    return 0


def main():
    repo = sys.argv[1] if len(sys.argv) > 1 else "/home/z/codex-clone"
    rc = 0
    for wo, (crate, libname) in WO_TARGETS.items():
        rc |= build(repo, wo, crate, libname)
    return rc


if __name__ == "__main__":
    sys.exit(main())
