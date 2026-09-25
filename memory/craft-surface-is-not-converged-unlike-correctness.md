# The craft surface is not converged, unlike correctness

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "Craft surface isn't converged (unlike correctness)"

The correctness and cross-platform surfaces have returned **0 blockers across
many independent rounds** — and that null *is* the signal
(`docs/STANDING_PRINCIPLES.md` §5). But a converged surface is **evidence of
nothing** about an un-attacked one.

## The evidence (2026-07-05, convergence Round 2)

Round 2 re-weighted the finders toward the never-attacked **OSS craft /
first-impressions** surface — internal-terminology leaks and vibe-coder tells on
public surfaces — and *immediately* found a **major**: the CHANGELOG was a
7,780-line dev-log carrying 631 internal task IDs, published as the PyPI
`Changelog=` URL. Plus a systemic root cause: **the public/private curation
boundary had never been drawn as a policy**, so internal build-process vocabulary
bled onto every surface a cold visitor reads.

**The key nuance:** the **code** was clean. The code-craft and latest-changes
finder lanes both returned zero — no dead code, no debug prints, no bugs in
recent changes. The "looks like a vibe coder built it" risk lived **entirely in
the narrative surfaces** (changelog, docs, `--help` output, shipped agent
bodies), never in the source.

## How to apply

- When a convergence dimension has gone null for several rounds, that is the cue
  to **re-point the finders at a fresh dimension** — not to stop reviewing.
- For mechanizing craft leaks, **reuse the existing guard**:
  `provenance_census.PROVENANCE_RE` already exists. Make a file clean, then
  remove it from `_ALLOWLISTED_FILES`. Do **not** build a brittle new jargon
  linter — false positives outrank leak-closing on a toolbelt
  (`docs/STANDING_PRINCIPLES.md` §2).

Related: [[pizza-test-review-lens]] (the successor lens — hunt the singular
category error once the class-hunt converges) ·
[[github-workflows-are-a-shipping-surface]]
