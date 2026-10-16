### Changed

- **The review a lane runs is computed from its diff.** On the Espalier-Harness
  tree, `scripts/proof_tier.py` prints a `review:` line beside the tier, from
  the same changed paths (`--base` and `--json` too): `none`, `code-reviewer`
  or `both`, by the rule `/implement-task` and `/preflight` step 6 state, with
  each path that earned it. A hook, a command / agent / skill / workflow body
  or a gate earns both reviewers; a gate is the CI definition, `bench/` and
  every repo file a workflow calls from a `run:` step or a local `uses:`, read
  from the workflows at the diff's head, so a script joins the moment a
  workflow runs it (a path in a quoted string, a comment or an `env:` value is
  not a call). `--quiet` still prints the tier word alone. The step 6 bodies
  cite the line, and `.github/actions/` joins the review surface beside the
  workflows.
