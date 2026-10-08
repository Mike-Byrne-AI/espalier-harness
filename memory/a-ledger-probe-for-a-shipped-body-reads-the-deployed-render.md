# A ledger probe for a shipped body reads the deployed render, never the body

**Status:** active — the probe shape for a ledger row whose defect lives in a
shipped body; landed 2026-10-07 with the twelve rows filed on the
adopter-readiness pack lane.

**Linked from:** `ESPALIER_MEMORY.md` row of 2026-10-07 (six adopter-readiness
packs drafted); `docs/FAILURE_MODES.md` 5.23 is the failure class it guards.

**Lesson (2026-10-07).** A forward-ledger row whose defect lives in a shipped
body (a command, agent or skill under `.claude/`, a seeded doc under
`espalier/assets/docs/`) cannot carry a probe that greps that body. The
paperwork ratchet, `tests/test_check_ledger_probes.py::TestProbeShapesAreRatcheted`,
refuses a probe that reads text out of its own subject file unless it parses
it, because a comment, a changelog line or a "see X" pointer flips such a probe
while the defect stands (`docs/FAILURE_MODES.md` 5.23). Six of twelve rows filed
on 2026-10-07 (`DEF-1180` to `DEF-1188`, the pack lane `adopter-readiness-packs`)
were refused on exactly this shape, and a seventh (`DEF-1187`) was keyed on the
fallback its own fix keeps, so it could never flip.

**The shape that holds.** Build the tree an adopter would have and read what
lands there:

- `tests/_adopter_tree.py::build_adopter_tree(dest, stack="node")` builds a
  Node repo, runs `espalier init` and `install-ci` on it, in about two seconds;
  `stack="python"` and `tree="git"` (no init) are the other arms.
- Read the **deployed** copy under that tree, or drive the verb there
  (`render-template`, `doctor`, a hook with a minimal payload), and print the
  predicate the fix must change.
- The probe's `--subject` is the **deployer**, `espalier/cli.py`, and the asset
  mirrors the render comes from (`espalier/assets/claude/...`,
  `espalier/assets/docs/...`) go on `--inputs`; the body's own path never
  appears in the command, so the ratchet reads it as structural, and it is.
- The runner compares the probe's **last stdout line** to `open_value`, so the
  builder's own chatter (install-ci's branch-protection note) is harmless.

**Two more traps met the same day.**

- A pipe character inside a row's text cell (`(^|/)` in a regex) is a cell
  separator to the ledger's row parser and shifts every cell after it; the
  `--dry-run` of `ledger_row.py file` does not run the convergence check that
  catches it, only the real write does. Spell the regex in words or escape the
  pipe.
- A probe over a body's **source** text that counts spellings is still the
  right first measurement for the pack's Task 0; it is only the ledger's probe
  that needs the deployed-render shape. Keep both: the pack's census as the
  deriving command, the row's probe on the render.

**Why:** the ledger's probes are what `check_ledger_probes.py` re-derives at
every handoff and what the strike verb trusts; a probe the fix's paperwork can
close is a row that reads struck while an adopter still meets the defect.

**How to apply:** before `ledger_row.py file` on a body-shaped row, write the
probe against `build_adopter_tree(stack="node")` and the deployed path, subject
`espalier/cli.py`, mirrors as inputs; drive it once by hand; expect the
convergence check only on the real write. See
[[fix-the-class-not-the-instance]] for why the row's unit is the render stage,
and `memory/one-writer-per-shared-state.md` for filing rows serially while
drafters run.
