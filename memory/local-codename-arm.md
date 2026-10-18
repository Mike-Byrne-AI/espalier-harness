# Local codename arm

**Status:** active
**Linked from:** `tests/test_no_internal_codenames.py` (module docstring) ·
                 `scripts/check_handoff_landing.py::check_local_codename_arm` ·
                 `.gitignore` (the `/.local-codenames.txt` row) ·
                 [[classify-the-surface-before-measuring-it]]

The internal-codename gate (`tests/test_no_internal_codenames.py`) reads two
pattern sources: its tracked `FORBIDDEN_PATTERNS` (names safe to print) and a
gitignored root file, `.local-codenames.txt`, that holds the operator's own
terms — the ones the public repo must not carry precisely because a tracked
denylist that spells them is itself the leak (ledger `DEF-708`, closed by
TP-452 1-G on 2026-09-21). The file exists on the operator's machine only.

## The file

- One regex per line; a line starting with `#` is a comment; blank lines are
  skipped; the whole stripped line is the pattern, so a pattern cannot start
  with `#` (spell it `[#]`) and a trailing `# note` is part of the pattern.
- Read as `utf-8-sig`, so a BOM written by Notepad on the Windows walk host
  does not ride on line 1 and disarm it. A file that does not decode, or a
  line that does not compile, fails the gate loud — by file and line, never
  by the pattern text.
- A hit is reported as `.local-codenames.txt#<line>`: the term never enters a
  failure, a transcript or a pasted log. A `pytest -l` re-run cannot print it
  either — the loader's and the scanner's frames are hidden and the compile
  error's chained cause is dropped.
- Every pattern runs against every tracked line (465,320 lines, 24 MB on
  2026-09-21); a pattern that spends more than `PATTERN_BUDGET_S` (10 s) over
  the tree fails by label. Keep the regexes literal or simple.
- Walls: the root-anchored `.gitignore` row, the exact `_LOCAL_ONLY_PATHS`
  entry in `espalier/surface_contract.py` (the archive builder's no-index
  fallback walks the tree), and an index-aware `git check-ignore` pin in the
  gate, so a force-added copy reds. The file is deliberately *not* in the
  gate's own exclusion list: it never reaches the walk, and a force-added
  copy should red on its own lines.

## Why an absent file is the failure to watch

With the file absent the gate runs on the tracked list alone and is green for
every term that lives only in the file: a fresh clone, a second worktree, a
new machine, `git clean -fdx`. No test can tell "not armed" from "nothing to
enforce". `scripts/check_handoff_landing.py::check_local_codename_arm` is the
one place that can. On the operator's tree — the tell is the gitignored
marker `cc/OPERATOR_TREE` (below) — an absent or comments-only
file is a red at `/commit` and `/handoff`, and the clean path prints
`local arm: N pattern(s)` so a truncated file is visible. Anywhere else it is
a printed note, because a contributor cannot recreate a file whose content is
not theirs (`--skip-local-arm` silences it on such a tree). A linked worktree of
the operator's tree is the operator's: the tell is read from its main checkout
(`_operator_root`; a worktree checks out tracked files only, so it never carries
the tell), and the red there names the main checkout's file to copy in — the gate
read the worktree's own, so a copy left in the main checkout arms nothing
(DEF-1137, 2026-10-06).

## Marking the operator's tree

The tell is `cc/OPERATOR_TREE`: a gitignored, empty file whose one meaning is
"this is the operator's tree", read through
`scripts/record_snapshot.py::operator_root`. Two kinds of arm in
`scripts/check_handoff_landing.py` read it:

- **Operator arms** red only there: the record snapshot, the changelog records
  on the record ref, and the candidate log's home. A seat's second clone has no
  record to keep, so a red there is one it cannot clear.
- **Seat arms** red there and on every seat, a checkout answering
  `git config espalier.machine` (the mail channel's own read): this codename arm
  and the hook wiring arm, because every seat pushes to the public repo. Only a
  contributor's clone, with neither, reads notes.

`scripts/handoff_mechanics.py`'s goal-doc step reads the marker too. Every
landing run prints which it is first (`operator tree: <root>` or `not the
operator's tree`), so a marker lost to `git clean -fdx` or a re-clone shows on a
clean run. Create the marker once, in the MAIN checkout of the clone the
operator works from (an empty file at that path is enough): `cc/` is a
write_guard zone, so from the operator's own terminal or a maintenance-mode
session. A linked worktree inherits its main checkout's, and a marker inside a
worktree marks nothing. Never in another clone: not a contributor's, not a
seat's second clone, not a reviewer's. It is never a record root, so a record
restored onto another clone does not mark that clone. Until 2026-10-18 the tell
was the goal doc `cc/GOAL.md`, so a second clone keeping a goal of its own read
as the operator's and the operator arms red there on state that belongs to the
first (DEF-1119); the goal doc now carries only the goal.

## Recreating it

The terms are not written anywhere tracked — that is the point. Their
provenance lives in the operator's machine-local auto-memory
(`~/.claude/projects/<project>/memory/`; see `docs/MEMORY_SYSTEMS.md`): one
entry per term family, saying what the family is and why it must not ship.
Recreate the file from those entries, one regex per family, then run the
gate: it names every tracked site by line label, and the tree is scrubbed when
it is green. As of 2026-09-21 the file holds two families — a third party's
name, and the private reason hosted CI did not run for a period. The bare word
that narrative used also appears in six benign API-pricing sentences, so the
patterns are deliberately narrow; widen them and the gate names the rest.

## What the redaction relies on

The pre-scrub phrasing stays in this tree's git history. The scrub holds only
because the public artifact is a generated fresh-history repository
(the `DEC-25` memo, `publish-from-a-generated-public-repo.md`, in the maintainers'
archive since the seed); if that decision ever
flips to pushing this history, every scrub is cosmetic. A record surface may
be edited for this one reason and no other — the clause lives in
[[classify-the-surface-before-measuring-it]].
