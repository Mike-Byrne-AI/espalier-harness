### Added

- **The threshold handoff: a seat is asked to hand off at a context size, not at
  the window's end.** Where `espalier.toml` sets a top-level
  `handoff_context_tokens = <int>` (opt-in, like `handoff_push`; this tree sets
  200000), `tools/cc/hooks/task_router.py` reads the session's context size on
  every prompt, loop ticks included, from the tail of the transcript the hook
  payload names (`_hook_utils.read_context_from_transcript`: the last assistant
  record's input, cache-creation and cache-read counts, the figure the status
  line reports as `total_input_tokens`; measured equal on a live session) and,
  once the figure is at or past the setting, prints one ASCII paragraph beside
  the prompt: finish a lane in hand through its own landing and start no new
  job, or with no lane in hand run `/handoff` now; after it take no new work
  and tell the operator the window needs a `/clear`. The ask never says "commit
  and hand off" mid-lane, because on a tree with `handoff_push` the handoff's
  last step opens the lane's pull request with auto-merge armed. It sits above
  the router's active-plan return, repeats on every prompt until the window is
  cleared, records its first ask beside the session's marker
  (`.espalier-state/sessions/<id>.handoff-asked`, a side file the marker's
  sweeps retire, with a suffix the marker readers' `*.json` glob never matches)
  and quotes it after, carries the push clause only where `handoff_push = true`,
  and says once a session when a transcript longer than its first window yields
  no figure. The setting rides a new flat-scalar toml reader
  (`_hook_utils.read_toml_scalar`, the string-list reader's twin over one shared
  body, with a scalar regex fallback for a host with no TOML parser);
  `handoff_context_threshold` reads it as off for anything but a positive
  integer and says why. Measured on this box before the build, one record per
  `(message.id, requestId)`: turns past 150k carried about nine tenths of a
  session's weighted spend on both seats, and a cut at 200k reads as roughly
  0.55 of the dispatcher's spend and 0.37 of a worker's, restart overhead
  included. `docs/HOOK_ASSUMPTIONS.md` Assumption 7 holds the three platform
  facts it stands on.
- **The status line shows the context and the account's limits.**
  `tools/cc/statusline.py` reads the JSON Claude Code sends it (when stdin is
  not a terminal; bounded, BOM-safe, never raising) and prints
  `ctx=<tokens>k/<window>k` from `context_window` and
  `limits=<five_hour>%/<seven_day>%` from `rate_limits`, the figure the
  threshold handoff reads and the facts that decide when a box freezes. It
  writes nothing.
- **`scripts/usage_tail.py`**, dev-only: where a session's tokens go by context
  size, from its transcripts, with the restart cost, the cap counterfactual at
  both cache-write weights, the subagent shape and a per-day table (the
  before/after measure: a session after a `/clear` is shorter by construction,
  a day's spend per seat is not); the threshold handoff's pre-registered
  instrument, driven in-process by `tests/test_usage_tail.py`.

### Changed

- **The seat briefs and the worker tick name the ask.** `tools/cc/seat.py`'s
  worker and dispatcher briefs run `/handoff` when the operator ends the
  session or when the prompt router reports the context past the threshold,
  and take no new work after a threshold handoff until the window is cleared;
  the worker tick's "then your next assigned job" yields to the ask (finish the
  lane in hand, hand off, take no new job until the clear). A seat already
  looping keeps its old tick until relaunched from a checkout that holds this.
