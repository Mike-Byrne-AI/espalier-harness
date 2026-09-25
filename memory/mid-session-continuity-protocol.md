# Mid-session continuity protocol

**Status:** active
**Linked from:** [CLAUDE.md "Core Rules"](../CLAUDE.md)

When the agent is reasoning about a decision the session already touched —
choosing between approaches, reconsidering a path, comparing alternatives —
prior reasoning may already exist in the active blueprint that the agent's
context has lost.

`tools/cc/cognitive_blueprint.py::cmd_load` surfaces prior reasoning at
session boundaries (SessionStart, PostCompact). Between boundaries —
mid-session — those entries are on disk but not in context. TP-125 closes
that gap with a discoverability advisory printed by `task_router.py` on
decision-shape prompts.

## When the advisory fires

`task_router.py` (UserPromptSubmit) prints an advisory on stdout when
BOTH conditions hold:

1. The user prompt matches a decision-shape pattern (`should I/we`,
   `X vs Y`, `decide`, `what about`, `reconsider`, `switch to`,
   `choose between`, `better to use/do/try`).
2. `cc/blueprints/latest.json` contains ≥1 entry with `kind == "decision"`.

If both `ROUTING_GUIDANCE` and the decision advisory fire on the same
prompt, both print (separated by a blank line). Stdout from
UserPromptSubmit is injected as additional context for Claude per
`docs/external/cc-hook-protocol.md`.

## What the agent should do

Run the advisory's suggested command:

```bash
python tools/cc/cognitive_blueprint.py show-recent --n 5 --kind decision
```

Surface the prior decisions in your response. If a prior decision
contradicts the current direction, name it explicitly and ask whether
the operator wants to override it. Don't silently re-litigate a choice
the session already made.

## Why two-condition gating

Without the "blueprint has decisions" gate, every `should we` question
fires the advisory — including on fresh sessions where nothing is
recorded. That trains the agent to ignore the channel, which destroys
the advisory's signal value. The mechanical gate (handled by
`task_router.py::_count_decisions_in_blueprint`) preserves signal
density: the advisory only fires when there's something to surface.

The load-bearing test is
`tests/test_hooks.py::TestAdvisoryGating::test_silent_when_no_decisions_recorded`.
If that test ever turns green-without-the-gate (e.g., a refactor
removes the count check), the channel has degraded and the test will
fail loudly.

## What this protocol does NOT cover

- **Decisions in other sessions' blueprints.** Cross-session reasoning
  surfaces at SessionStart via `loaded_continuation_fragments`, not
  mid-session. The mid-session advisory reads only `latest.json`.
- **Other reasoning kinds** (`pattern_discovered`, `alternative_rejected`,
  `reflect_insight`). The advisory is narrowed to `--kind decision`
  because that's the kind most often re-litigated. The bare
  `show-recent --n N` CLI still surfaces all kinds.
- **Auto-execution by the harness.** The advisory tells the agent to
  run `show-recent`; it does not run it for the agent. Auto-execution
  would inject potentially noisy reasoning into every decision-shape
  prompt regardless of relevance.
- **LLM-based intent classification.** The detector uses simple regex
  (`_DECISION_SHAPE_PATTERNS`). An Anthropic-call classifier would be
  more accurate but introduces network dependency, latency, and
  stdlib-only architectural violation in a hook — the same posture
  TP-127 rejects for coherence inspection.

## See also

- `tools/cc/hooks/task_router.py` — the hook with the classifier
- `tools/cc/cognitive_blueprint.py` — `show-recent` subcommand
- `docs/external/cc-hook-protocol.md` — UserPromptSubmit stdout
  contract
