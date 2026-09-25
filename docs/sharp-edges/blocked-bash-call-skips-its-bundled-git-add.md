# A hook-blocked Bash call runs none of its commands — a bundled `git add` silently never happens

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "A Hook-Blocked Bash Call Skips Its Bundled `git add`"

**What it is:** A blocked Bash tool call is **all-or-nothing**. The harness denies
the entire command string, so every `&&`- or newline-separated step in it is
skipped — including a `git add` that had nothing to do with the reason for the
block. An on-disk edit is not staged until a `git add` actually *succeeds*, so
the index can silently lag the working tree, and the **next** clean commit
captures the stale index.

**How you hit it:** A `git add CHANGELOG.md` was bundled into the same Bash call
as a commit prefixed with an inline harness env-var assignment. (Harness env vars
must be set in the parent shell *before* launching Claude Code; the hook denies
the inline spelling because it silently does nothing.) The hook blocked the call
wholesale, so the `git add` never ran. The next, clean commit then captured the
stale index — committing the CHANGELOG with a literal `SUITE_COUNT` placeholder
instead of the real counts edited onto disk afterward. It was caught only by
running `git status --short` *after* the commit (which still showed
`M CHANGELOG.md`) and diffing `git show HEAD:CHANGELOG.md`.

**A second, self-demonstrating instance:** migrating this very entry into
`docs/sharp-edges/` failed on its first attempt, because the prose above quoted
the inline env-var spelling literally and the guard's bash-pattern matcher
matched the *heredoc body*. The entire batch of eight file writes in that call
was discarded — not just the offending one. Prose that quotes a denied pattern is
itself subject to the guard when it travels through Bash; author such files with
the Write tool instead.

**How to avoid it:**

- **Never bundle `git add` with a command that might be hook-blocked.** Set
  harness env vars in the parent shell before launching, where mid-session inline
  assignment does nothing anyway.
- **After every commit**, run `git status --short` and spot-check
  `git show HEAD:<file>` for the load-bearing edit. A placeholder like
  `SUITE_COUNT` or `TODO` leaking into a commit is the tell.
- Re-stage and `--amend` while the commit is still local and unpushed, rather
  than layering a follow-up commit.
- **Prefer the Write tool over Bash heredocs for multi-file authoring** — a Bash
  batch is a single all-or-nothing unit, so one denied pattern anywhere in it
  discards every write.

**Related class — an allowlist is a claim; enumerate the real surface.** The same
change hand-picked a five-command nudge-exempt set. A mechanical enumeration of
*all* `build_parser` subcommands plus an adversarial pass found it missed three
more — and one of them runs on a source checkout **by design**, so nudging it
would have corrupted the very state it validates: a guaranteed false positive in
the harness's own pre-PR flow. Do not trust a curated subset; enumerate the full
command/symbol surface and rule on each.
