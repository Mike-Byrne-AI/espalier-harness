### Added

- **The Stop hook's fifth gate: a finished lane is handed off in the turn that
  finishes it.** `stop_gate` Gate 5 (`_gate_handoff`) blocks the Stop once per
  commit when nothing is in flight (no plan in progress, no tracked edit) and
  the branch holds commits its upstream does not (its own upstream, else
  `origin/HEAD`, else `origin/main` or `origin/master`), made in this session,
  on a repository whose `espalier.toml` sets `handoff_push = true`; the reason
  names the plan (or that none is in progress), the branch, the count and the
  upstream, says what the push does for this branch, says to run `/handoff` now,
  and names three carve-outs (the operator asked to hold the push; the lane
  ships together with another; more of the lane's work is still to come this
  session). Maintenance mode does not lift it, and it runs alone on the
  continuation Stop that follows a hygiene gate's block: the measured case ran
  under the flag (a lane finished at 05:13 EDT and left for the operator's
  `/handoff` sat unpushed, with no Session Log row and its claims live, for
  eleven hours, 2026-10-24, and the next session handed it off from a cold
  context). "This session" is the flag `.espalier-state/handoff_gate_said`
  (`_hook_utils.HANDOFF_GATE_FLAG`): SessionStart seeds it with HEAD on a new
  session and keeps it across a compaction, and every judgment rewrites it, so
  a lane an earlier session left unpushed is the banner's to name, a new commit
  speaks once, and a handoff whose push failed (its row moved HEAD) speaks
  again. `_hook_utils.plan_completion` reads the plan beside `has_active_plan`
  on one read (`_read_plan_dict`). The audit record is `stop_blocked_handoff`
  (pause tier; `details.ahead` the count, never the branch or the title); a git
  that cannot be asked lets the Stop through and says so once
  (`stop_failed_open_handoff_git`); a tree without `tools/cc/ship.py` has no
  gate, and a driver that cannot import, is shadowed by another module of its
  name, predates `handoff_push_setting` or fails its read stands the gate down
  and says so once (`stop_failed_open_handoff_driver`).

### Changed

- **`/implement-pack` and `/implement-task` end with `/handoff`, not a
  report.** Single-pack mode's step 13 and the auto-continue policy, the
  chain's final report, focused-mode step 10 (`/commit`, then `/handoff`: the
  task command commits nothing of its own) and a new multi-phase Phase 5 all
  run `/handoff` in the turn the work is committed, naming the gate as the floor
  and the three carve-outs; Core Rule 10 says the same in one clause, and the
  handoff body's worktree note says step 8's push runs from a worktree too. The
  docs that counted four gates (`docs/HOOKS.md`, `docs/QUICKSTART.md`,
  `docs/TROUBLESHOOTING.md`, `docs/HOOK_ASSUMPTIONS.md`, the README, the demo
  storyboard and the root `CLAUDE.md` tables) count five, and a test derives the
  number word from the hook's own `Gate N:` lines so a sixth cannot land with
  "five" standing in seven places. The `handoff_push` comment `init` writes, the
  `upgrade` message that names the setting, and the adopter hooks table say the
  setting also arms the handoff gate (the table row no longer names a "state"
  gate retired in 2026-05). `tests/test_no_stale_gate_five_references.py` no
  longer treats the words `Gate 5` as a straggler of that retired gate; its own
  vocabulary stays pinned.
