### Changed

- **The review a lane runs is computed from its diff.** On the Espalier-Harness
  tree, `scripts/proof_tier.py` prints a `review:` line beside the tier, from
  the same changed paths (`--base` and `--json` too): `none`, `code-reviewer`
  or `both`, by the rule `/implement-task` and `/preflight` step 6 state, with
  each path that earned it. Both reviewers are earned by a hook or any
  `tools/cc/` module a hook loads, a command / agent / skill / workflow body,
  a gate, `espalier.toml` and `pyproject.toml`, and the `.gitignore` line that
  keeps `.claude/settings.json` out of a commit; a gate is the CI definition,
  `bench/` and every repo file a workflow calls from a `run:` step or a local
  `uses:` (a script after an interpreter, quoted or not, a `$(...)` inside
  double quotes, a `-m` module, a step's working directory), read from the
  head when the line is printed, so a script joins the moment a workflow
  runs it, while printed text and a test's operand stay data. A mirror's
  source earns what the mirror earns. What cannot be read, and an unresolved
  `--base`, read both; `--base` names the uncommitted paths it leaves out.
  `--quiet` still prints the tier word alone. The step 6 bodies cite the
  line, and on this repository the worker tick names it.
