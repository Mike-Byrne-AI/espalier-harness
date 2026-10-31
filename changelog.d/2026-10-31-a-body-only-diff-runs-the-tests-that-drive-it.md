### Fixed

- **A diff that edits only an agent, command or skill body now runs the tests
  written for the bodies.** `scripts/proof_tier.py` gave such a diff the
  contract tier, whose `-m contract` deselects every row of
  `tests/test_first_contact_diagnostics.py` (the file is
  integration-classified), so the first-contact diagnostics could regress
  with every pull-request cell green and the red arrived on `main` after the
  merge. `own_tests` now adds that file for a changed body on the two cheaper
  tiers, the way it adds a changed script's own test file: a body is one of
  the kinds the file walks (`agents/*.md`, `commands/*.md`,
  `skills/*/SKILL.md`) under `.claude/` or under `espalier/assets/claude/`,
  the deploy source `espalier init` copies into the adopter tree the file
  builds. The roster is pinned to the file's own walk, and a driven test
  shows the body line collecting every row of the file where `-m contract`
  collects none.
