# A reverting proof is a claim so stash the one file

**Status:** active
**Linked from:** memory/ cool-store — reached on demand via the `memory/CLAUDE.md` folder router and sibling cross-links; not rowed in `ESPALIER_MEMORY.md` (at its cap).

A handoff that says "N pre-existing reds, proven by reverting" hands the next session a claim, not a result. Re-drive it before touching a ratchet or a baseline: `git stash push -- <the one suspect file>`, run the failing test file, `git stash pop`, verify the pop.

**Measured 2026-09-09.** The record claimed three reds on `main`; there were four, HEAD passed 31 of 31, and every red came from the uncommitted test's bare `file.py:NN` citations against a citation ratchet sitting exactly at its ceiling. The wrong reading invited the wrong fix, raising the ceiling; the right one was symbol citations.

**Why the whole-tree revert lied.** Reverting "everything" in a tree that also holds another session's work measures the wrong tree. The one-file stash isolates the suspect and nothing else.

Siblings: `docs/STANDING_PRINCIPLES.md` §3 -- this note is that principle applied to a handoff record -- and [[the-handoff-record-goes-stale-if-work-continues]].
