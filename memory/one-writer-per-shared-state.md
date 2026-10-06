# One writer per shared state

**Status:** active — the sole home of root `CLAUDE.md` Core Rule 14; landed
2026-09-10 with the DEF-753 follow-up that gave the PowerShell differential
a private interpreter cache per run.

**Linked from:** `ESPALIER_MEMORY.md` row "One writer per shared state";
root `CLAUDE.md` Core Rule 14. Kin:
[[a-friction-fix-and-a-fail-open-are-one-edit]] (the calibrated-baseline
rule that catches a dead instrument), `tests/README.md` (the running log of
xdist live-tree races), `docs/SHARP_EDGES.md` "freshness check writes the
state cache" (the git-stash strand).

## The rule

A file, directory or index that two actors can touch at once has one owner
at a time, and the tool that spawns the second actor is what enforces it.
Isolate the state per actor when you can (a temp root, a per-run cache
directory, a worktree, `tmp_path`); serialise only where isolation is
impossible; and never enforce it by remembering to run things one at a
time, because the next session will not remember. Where a shared state
cannot be isolated, the gate that reads it calibrates at both ends of its
run, so a death in the middle is loud rather than a comforting agreement.

## What it cost to learn

The same class, four ways in one month, every one green until it was not:

- **xdist workers and the live tree.** A sibling worker's atomic-write
  temp file under `reports/` appears or vanishes while another test watches
  the directory, and the `_no_live_tree_writes` teardown fires. Nine
  instances since 2026-09-06, all logged on the races line of
  `tests/README.md`, each re-run serially green. Expect one per full
  parallel run; it is a loud error, never a false green.
- **Two PowerShell differential runs at once (2026-09-10).** pwsh keeps a
  startup cache under the user's profile. Two concurrent populations wrote
  it together; every pwsh afterwards aborted on load with "The given
  assembly name was invalid", every later row read as not reaching, and the
  run against an unfixed tree reported no false allow where 21 were live.
  The calibration check ran only at start-up, so nothing caught a death
  mid-run. Fixed by isolation: `main()` gives every spawn a private
  `XDG_CACHE_HOME` for the life of the run, and `run()` re-asserts the
  calibration after the last row.
- **A reviewer agent stash-round-tripping the tree (2026-09-10)** while the
  other reviewer read it. Reviewer briefs now carry the no-stash line and
  say to prove a red in a scratch copy.
- **A git-capable sub-agent mutating the shared index (2026-06-23)**, so
  the parent's staging read differently after the agent returned.

## How to apply

1. **Before spawning anything that runs beside you** (a bench gate, a
   reviewer, a tier, a sub-agent with git access), name the state it shares
   with you and with its siblings. If you cannot name it, you have not
   looked.
2. **Isolate by construction, inside the tool.** A per-run temp directory
   for a cache, a `git worktree` for a second checkout, a temp root for a
   guard under test. The differential's `_child_env` is the pattern: the
   isolation is in the environment every spawn receives, not in a docstring.
3. **Serialise only what cannot be isolated**, and write down why: the
   three wall-clock-budget test files run serially after the parallel leg
   because timing under contention is the thing they measure.

   A second case, measured 2026-09-26: `tests/test_wheel_payload.py`'s
   `_built_wheel` / `_built_sdist` fixtures called
   `artifact_parity.clear_stale_packaging_state(REPO_ROOT)`, which deletes the
   repo root's `build/` and every top-level `*.egg-info` before each build -- a
   live-tree path, not a `tmp_path`. Four xdist workers running the module
   beside itself reded it; serially it passed. Isolated by construction on
   2026-10-06 (`DEF-1138`): `artifact_parity.build_wheel` and `build_sdist`
   stage a per-call copy of the working tree under a temp root
   (`stage_build_tree`) and build there, so the sdist's staged release tree,
   the wheel's `build/` and the `*.egg-info` land in the copy and die with
   it; the fixtures build through them, and each reads the root's packaging
   litter (name and mtime) before and after. Isolating by copying turns a
   write race into a read race unless the copy skips what churns:
   `shutil.copytree` lists a directory, then copies each entry, and an entry
   gone between the two raises `shutil.Error`, so the staged copy leaves out
   `cc/blueprints/`, `bench/results/` and `bench/end_to_end/runs/` beside the
   never-shipped names (the lane's failure-mode review, driven). The two
   hand-run release-ladder builds (`scripts/final_release_matrix.py`,
   `scripts/wheel_smoke.py`) still run in the live tree, alone by design, and
   `tests/test_test_suite_contract.py` pins that no other file in the tree
   spawns a build.

4. **Calibrate at both ends** of any run whose oracle can die silently. A
   start-up check certifies the first row; only an end-of-run check
   certifies the last.
5. **After a race or an interrupted write, `git diff` before the next
   edit.** A half-landed change looks like a failed tool call.
