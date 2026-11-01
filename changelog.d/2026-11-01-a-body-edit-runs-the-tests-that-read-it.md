### Fixed

- **A diff that edits one agent, command or skill body now runs every test
  file that names that body.** Five integration-classified files read a single
  body's text by name (the `inbox`, `smoke` and `preflight` commands, the
  `hook-authoring` and `reflect` skills), and a body-only diff earned the
  contract tier, whose `-m contract` deselected all of them, so their reds
  arrived on `main` after the merge. `scripts/proof_tier.py::own_tests` now
  reads the top-level test files for the paths they name (a string literal,
  the string constants that end a `/` join or a path-building call, the same
  join on a tree `espalier init` built included, and a path constant imported
  from a test helper) and adds, on the two cheaper tiers, every
  file that names a changed path under `.claude/` or `espalier/assets/claude/`.
  The map is derived from the test files at each call and cached per file; a
  name built at run time (an f-string, a glob) is not read.
