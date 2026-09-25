## Summary

<!-- 1-3 sentences describing what this PR does and why. Lead with the
why; the diff shows the what. -->

## Harness zones

<!-- If this PR touches tools/cc/hooks/ or .github/workflows/ (or one of the
five individually-gated files listed in CONTRIBUTING.md), the required
`harness-guard` check reads the PR TITLE for an approval marker bound to the
head under review (`HARNESS-UPDATE-APPROVED@<sha>`) and fails the merge
without it; a force-push after approval needs the title re-bound. Add it to
the title, not to this body. The authority is tools/cc/ci_guard.py -- the
runtime hook guards a WIDER zone, which is a different policy and not the one
that blocks this merge. -->

- [ ] This PR touches no CI-gated harness path, OR its **title** carries
      `HARNESS-UPDATE-APPROVED@<sha>` for the head under review

## Type of change

<!-- Check all that apply. -->

- [ ] `feat` — new functionality, new flag, new surface
- [ ] `fix` — bug fix; behavior was wrong, is now correct
- [ ] `docs` — documentation only; no code change
- [ ] `refactor` — internal restructure; no behavior change
- [ ] `chore` — tooling, build, deps, formatting; no behavior change
- [ ] `test` — new or refactored tests only
- [ ] `security` — closes a CVE, CVE-adjacent hardening, or a bypass-corpus row

## Test plan

<!-- How you proved this works. Bullet list — one item per check.
At least one item must be reproducible by a reviewer locally. -->

- [ ] `pytest -q` passes
- [ ] `python scripts/release_check.py` passes (if release-gated path was touched)
- [ ] `espalier audit .` exits 0
- [ ] Additional targeted tests / manual smokes:

## Pass criteria

<!-- One-line statements that must all be true for this PR to be
considered done. Stricter than "tests pass" — name the user-visible
behavior. -->

- [ ] <state outcome 1>
- [ ] <state outcome 2>

## Linked issues / task pack

<!-- Issue numbers or task-pack IDs (e.g., `TP-NN`) this PR addresses.
For a bare bug fix, "Closes #NNN" is sufficient. For a task-pack
execution, paste the pack ID + the one-line task statement. -->

- Closes #
- Pack: <TP-NN or N/A>
