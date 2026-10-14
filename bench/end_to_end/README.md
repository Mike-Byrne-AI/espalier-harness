# End-to-End Bench

Receiver-side verification of Espalier-Harness's hooks. Runs real Claude Code
as a subprocess against scenario fixtures and asserts on agent
behavior — what the agent did *with* the hook output, not just what
the hook *emitted*.

> **This subsystem catches the receiver-blind class of bugs that
> emission-side tests cannot. It is also the most flake-prone subsystem
> we have. Both properties are inherent to running real LLMs. We accept
> the flake noise as the cost of catching this bug class.**

## What this catches

- **Hook protocol regressions.** A bug class where every internal
  layer agrees the hook was correct, but the deny reason never reaches
  Claude. `BCE-001` is the direct regression test: if it fails, the
  channel-XOR contract has silently broken again.
- **Schema mismatches.** A bug class where stop_gate emits
  the PreToolUse JSON shape (nested under `hookSpecificOutput`) instead
  of Stop's top-level `decision/reason`. `BCE-002` covers that path.
- **Friction-as-teaching regressions.** `BCE-003` validates that
  plan_guard's deny reason actually steers the agent toward planning
  rather than bouncing off the deny.

## What this does NOT catch

- Multi-session behavior (session resume, ESPALIER_MEMORY.md handoff). Single-session only.
- Comparative behavior (espalier vs no-governance receivers). Single-baseline only.
- Performance characteristics. Cost is reported but not optimized for.
- Replay against recorded transcripts. Future work.
- Anything that requires a specific Claude Code CLI version other than the
  version the workflow installs — `.github/workflows/end-to-end-bench.yml`
  runs an unpinned `npm install -g @anthropic-ai/claude-code`.

## Cost

Measured 2026-10-14, one run each, on a maintainer's Mac with Claude Code
2.1.299 and its default model (`claude-opus-5-5`), with the run's cost read
from the CLI's own `result` event (`total_cost_usd`; tokens include the cache
tokens, which are most of them). Runs vary with the model's path, and a CI key
whose default model is cheaper will cost less, so treat these as one sample:

| Scenario | Tokens | Cost |
|---|---|---|
| BCE-000 (smoke) | 16,373 | $0.05 |
| BCE-001 | 263,375 | $0.42 |
| BCE-002 | 78,866 | $0.11 |
| BCE-003 | 54,926 | $0.09 |

One pass of all four is about **$0.67** at these figures, so a weekly run is
about $35 a year. The workflow passes `--max-cost-usd 5.00`, which the
orchestrator checks after each run: past it, no further scenario starts, so the
run in flight can go over it. A run the timeout cuts off sends no `result` event, so the cap prices
its messages' usage instead, each token class at the rates the CLI's own prices
of these runs solve to (4, 20, 8 and 0.20 USD a million input, output,
cache-write and cache-read tokens); that reads 80 to 89 percent of the billed
price on the captured runs, since the stream's per-message output count is the
one each message opened with. (The table this replaced, about 3,000 tokens a scenario under a
3-turn cap, came from a runner whose own estimate left the cache tokens out and
that never reached the CLI: it lacked `--verbose`.)

> **Schedule is manual pre-launch.** The weekly `schedule:` trigger is
> currently commented out in `end-to-end-bench.yml` pending the
> `ANTHROPIC_API_KEY_E2E_BENCH` repo secret; only `workflow_dispatch` is
> active today. Re-enable the cron block once the secret is set.

> **Stay scheduled or per-PR. Never per-commit.** Four scenarios at about
> $0.67 a pass per commit on a busy repo runs into thousands of dollars
> per year and produces signal that the weekly run already gives you.

## When to run locally

- Before significant hook protocol changes (`tools/cc/hooks/*.py`).
- Before a release (the pre-flight checklist includes "run e2e bench
  at least once against the release branch").
- When debugging a CI failure (`workflow_dispatch` with `--scenario` to
  reproduce the failing case at lower cost).

```bash
pip install -e ".[dev]"   # the runner does `import yaml`; PyYAML is a dev extra
export ANTHROPIC_API_KEY="..."
python3 -m bench.end_to_end.run --scenario BCE-001-write-guard-deny-reaches-agent
```

Run it with `python3 -m bench.end_to_end.run` from the repo root — the `-m`
module form is required (the package resolves `bench.end_to_end` relative to the
repo root, not the script's directory).

A run measures its scenario, not your machine: the runner passes
`--setting-sources project` and `--strict-mcp-config`, so your user-scope hooks,
permission mode and MCP connectors stay out (a user-scope SessionStart hook once
told the nested agent to make no edits), and it drops every `ESPALIER_*` variable
and the three that make the child a nested session (`CLAUDECODE`,
`CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_PROJECT_DIR`) from the child's environment, so
a run from inside a session or a maintenance-mode shell still exercises the
scenario's hooks. Any other setting a parent session exports (an effort level, a
subagent model) still reaches the child. The CLI authenticates however it finds
(an API key, or your local login), and the model is your CLI's default; the
report names the CLI version and model of each run. A run that itself failed
before any model turn (the CLI refused the argv, or found no login or a bad key,
when it sends only its own error message and an error result) fails with its
exit code and error printed beside the verdict and no assertion under it, which
is how it reads apart from a hook verdict; a run that exited 0 with no events is
inconclusive, which a wiring scenario reports as a warn; a run the timeout ended
fails.

## When to ignore failures

**Never silently.** A flake is a real signal that needs triage:

- **Single flake** (one of N=5 reruns failed): warn, don't fail. The
  scenario's `flakiness_handling.treat_inconclusive_as: warn` produces
  exactly this behavior.
- **Repeat flake** (N>=2 of N=5 reruns fail): fix the assertion (it's
  too tight) or fix the bug (it's a real regression). Don't loosen the
  scenario by removing assertions — that defeats the purpose.

Failed CI runs open a GitHub issue tagged `e2e-bench-failure`. Don't
auto-close. Investigate every issue before dismissing.

## How to add a scenario

1. **Justify the scenario** in writing: which bug class does it catch
   that the existing scenarios don't? If you can't articulate that,
   the scenario doesn't belong yet.

2. **Write the YAML** under `bench/end_to_end/scenarios/BCE-NNN-name.yaml`
   following the schema in `SCHEMA.md`.

3. **Calibrate the assertions.** Run the scenario locally **at least
   5 times** in a row before committing. Record the verdicts:

   ```bash
   for i in {1..5}; do
     python3 -m bench.end_to_end.run --scenario BCE-NNN-name
   done
   ```

   - 5 passes → assertions are well-calibrated.
   - 4 pass + 1 inconclusive → keep `retry_on_inconclusive: 1`,
     `treat_inconclusive_as: warn`. Acceptable.
   - 3 pass + 2 inconclusive → assertions are too tight. Loosen
     `must_contain_any` patterns; the agent's phrasing is noisier than
     you anticipated.
   - Any fail → either the scenario is testing a real bug (good!) or
     the assertions don't match what the agent actually does (tighten
     them after fixing, or document why this is the right answer).

4. **Document the failure mode.** Add the scenario name to
   `bench/end_to_end/README.md` under "What this catches" with a
   one-line description.

## How to debug a flake

1. Pull the artifact transcript from the failing CI run:
   `Actions → end-to-end-bench → run → Artifacts → e2e-transcripts-...`
2. Inspect `bench/end_to_end/runs/<timestamp>/<scenario_id>.json`. The
   `events` list shows every assistant turn, tool_use, and system
   message. The `raw_stream_json` field is the unparsed Claude Code
   output for completeness.
3. Reproduce locally: `python3 -m bench.end_to_end.run --scenario <id>`.
   Compare to a passing transcript from the same artifact.
4. If the agent's wording drifted but the *meaning* is unchanged,
   loosen `must_contain_any` patterns. If the meaning drifted (the agent
   no longer references the deny reason at all), it's a real bug.

## Layout

```
bench/end_to_end/
├── README.md                     this file
├── SCHEMA.md                     scenario YAML schema
├── runner.py                     subprocess driver
├── transcript.py                 stream-json parser
├── assertions.py                 fuzzy assertion framework
├── run.py                        orchestrator + reporter
├── scenarios/
│   ├── _schema.yaml              skeleton with all fields
│   ├── BCE-000-smoke-test.yaml   harness sanity check
│   ├── BCE-001-write-guard-...   deny-reason-reaches-agent regression
│   ├── BCE-002-stop-gate-...     Stop schema verification
│   └── BCE-003-plan-guard-...    friction-as-teaching test
├── templates/
│   └── minimal_governance.json   .claude/settings.json template
└── runs/                         per-run transcripts (gitignored)
```

`runs/` is intentionally gitignored — every run produces fresh
transcripts and committing them would bloat the repo. CI uploads them
as workflow artifacts with 30-day retention.
