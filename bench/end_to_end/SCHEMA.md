# Scenario Schema

End-to-end bench scenarios live as YAML files under
`bench/end_to_end/scenarios/`. Each scenario invokes real Claude Code
as a subprocess, captures the transcript, and asserts on **receiver-side
behavior** — what the agent did *with* the hook output, not just what
the hook *emitted*.

This file documents the schema. The canonical example skeleton is
`bench/end_to_end/scenarios/_schema.yaml`. Real scenarios start with
`BCE-` (Bench Class End-to-end).

## Top-level fields

| Field | Required | Type | Notes |
|---|---|---|---|
| `id` | yes | string | `BCE-NNN-short-name`. Must match the filename stem. |
| `description` | yes | string (block) | One paragraph: what this scenario validates and why. |
| `in_scope` | yes | bool | `true` = behavior under test should occur; `false` = the scenario documents an explicit non-claim (agent should NOT block / the bench should pass-through). |
| `verifies` | yes | string | One sentence describing the receiver-side property. |
| `setup` | yes | object | See [Setup](#setup). |
| `trigger` | yes | object | See [Trigger](#trigger). |
| `expected_receiver_behavior` | yes | object | See [Expected Receiver Behavior](#expected-receiver-behavior). |
| `flakiness_handling` | no | object | See [Flakiness Handling](#flakiness-handling). Defaults: `retry_on_inconclusive: 0`, `treat_inconclusive_as: warn`. |
| `cost_budget_tokens` | no | int | Advisory only — **not currently enforced** by the runner; the live cost cap is the cumulative `--max-cost-usd` in `run.py`. Scenarios set it as documentation. |

## Setup

| Field | Type | Notes |
|---|---|---|
| `files` | list of `{path, content?, from_template?}` | Files to materialize in the temporary working directory before the scenario runs. |
| `git_init` | bool | Initialize a git repo in the tmpdir. Default: `false`. |
| `copy_hooks` | bool | Copy `tools/cc/hooks/*.py` and `_*.py` into the tmpdir. Default: `false`. |
| `settings_template` | string | Name of a `.claude/settings.json` template under `bench/end_to_end/templates/` to materialize. |

## Trigger

| Field | Type | Notes |
|---|---|---|
| `type` | `prompt` \| `tool_call` \| `noop` | How the agent is kicked off. **`tool_call` is not implemented** — `runner.py` returns "tool_call trigger not supported in this runner version"; use `prompt` or `noop`. |
| `content` | string | For `prompt`: the user message piped to Claude Code's stdin. |
| `tool_name` | string | For `tool_call`: the tool to attempt directly. |
| `tool_input` | object | For `tool_call`: the tool input payload. |

## Expected Receiver Behavior

This is the assertion surface — see `bench/end_to_end/assertions.py`.

| Field | Type | Semantics |
|---|---|---|
| `must_contain_any` | list of `string` or `{regex: ...}` | At least one pattern must appear in any assistant turn. Fail if none. |
| `must_not_contain_any` | list of `string` or `{regex: ...}` | None of the patterns may appear. Fail if any. |
| `block_acknowledgment.required` | bool | At least one assistant turn must reference the deny reason AND not propose retry. Inconclusive if heuristic can't classify. |
| `agent_actions_after.no_repeat_of` | string | The agent must not retry the same target tool call. Fail if found. |
| `max_turns` | int | Cap on agent turns. Inconclusive if assertions can't be resolved within. |

**Loose by design.** Match on *meaning*, not exact phrasing. Calibration
discipline lives in `bench/end_to_end/README.md` § "Adding a scenario".

## Flakiness Handling

| Field | Type | Notes |
|---|---|---|
| `retry_on_inconclusive` | int | If verdict is `inconclusive`, rerun N times. Default: 0. |
| `treat_inconclusive_as` | `fail` \| `warn` | After retries, how to surface a final inconclusive. Default: `warn`. |

## Verdict semantics

A scenario yields one of: `pass`, `fail`, `inconclusive`, `warn`.

- Any assertion `fail` → overall `fail`.
- All assertion `pass` → overall `pass`.
- Mix of `pass` + `inconclusive` (no `fail`) → overall `inconclusive`.
- An `inconclusive` scenario with `treat_inconclusive_as: warn` becomes
  `warn` after retries are exhausted (still surfaces, doesn't break CI).

The orchestrator (`run.py`) exits `1` only on `fail`. `warn` exits `0`
but is reported prominently.

## Why this format

YAML over JSON because operators edit these by hand. The schema is
deliberately sparse — every field exists because a specific failure
mode justified it. New fields require a documented justification.
