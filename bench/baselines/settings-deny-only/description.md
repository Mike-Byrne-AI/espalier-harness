# settings-deny-only baseline

**What this represents:** A Claude Code project that uses only the native
`permissions.deny` rules (no hook scripts) to protect harness paths.

**What it claims to handle:** Direct Write/Edit calls whose `file_path` is a
literal match against a deny pattern. That is what `permissions.deny` is
designed for, and the runner faithfully simulates Claude Code's matcher.

**What it does NOT claim to handle:** Bash commands. `permissions.deny` does
not match against the contents of a Bash command, so any redirect, tee,
cp/mv, git restore, or interpreter inline source whose effect is a write to a
protected path passes through unblocked. Path traversal (`safe_dir/../...`)
is also not normalized by the native matcher and slips through depending on
the exact pattern set.

**Expected results:** Catches a few direct Write/Edit cases. Misses the bulk
of Bash variants, traversal, and any kill-switch detection.

**Why it's in the benchmark:** Distinguishes "what Claude Code already gives
you" from "what espalier adds on top." If the gap is small, that's
information; if the gap is large, that's also information.

**Reproducibility note:** This baseline is evaluated by a small built-in
matcher in `bench/run_benchmark.py` that mirrors Claude Code's documented
deny-pattern behaviour (literal-path glob match against tool_input.file_path).
Bash commands are not matched against deny rules — that mirrors Claude Code's
documented behaviour, where Bash deny patterns require explicit
`Bash(<command>:*)` rules and even those operate on the launching command,
not the resolved write target.
