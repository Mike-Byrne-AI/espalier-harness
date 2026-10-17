### Fixed

- **A deny hook whose floor module raises at import refuses instead of
  turning off.** `write_guard`, `plan_guard`, `config_guard` and `stop_gate`
  imported `_hook_utils.py` and `_denial_reasons.py` outside the guard that
  turns a sibling's failed import into a refusal, so a raise in either, or in
  `_maintenance_mode.py` or `tools/cc/_json_safe.py` under them, made all four
  exit 1, which Claude Code reads as a non-blocking error: every tool call,
  settings change and Stop went through unjudged, and nothing said so. The
  refusal now lives in a new `tools/cc/hooks/_start_refusal.py`, which each
  deny hook imports first, and the floor imports under the guard: the hook
  refuses, names the file and its line, and `write_guard` lets through the one
  restore of that file to HEAD. If the new module itself cannot import, each
  hook refuses in its own words, and `write_guard` lets through
  `git restore --source=HEAD -- :/tools/cc/hooks/_start_refusal.py`, which
  works from any directory of the checkout. On the Stop hook a start refusal
  now lets Claude Code's loop signal through, so it pauses a Stop once and
  never locks it.
