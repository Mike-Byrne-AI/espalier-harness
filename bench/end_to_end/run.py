"""End-to-end bench orchestrator.

Enumerates scenarios under `bench/end_to_end/scenarios/`, runs each
via `runner.run_scenario`, evaluates with `assertions.evaluate`, and
produces a markdown or JSON report. Tracks cumulative cost; aborts if
`--max-cost-usd` is exceeded. Saves raw transcripts to
`bench/end_to_end/runs/<timestamp>/<scenario_id>.json` for replay, and each
run a retry replaced beside it as `<scenario_id>.run<N>.json`.

Exit codes:
    0  every scenario `pass` (on its first run or a retry).
    1  any scenario `fail` -- including a per-scenario orchestrator error
       (invalid scenario YAML, missing `claude` CLI) caught as a FAIL verdict.
    2  cumulative `--max-cost-usd` exceeded, or no scenarios matched `--scenario`.
    3  a scenario decided nothing after its retries (`ScenarioVerdict.undecided`:
       inconclusive before its `treat_inconclusive_as` mapping), so the run
       tested no hook, whatever the report's text; a `fail` outranks it (1)
       (DEF-5001).

Cost discipline is the load-bearing constraint here. Scheduled CI
(weekly + workflow_dispatch) is the only place this should run with
real LLM cost. See bench/end_to_end/README.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path


from bench.end_to_end.assertions import (
    VERDICT_FAIL,
    VERDICT_INCONCLUSIVE,
    VERDICT_PASS,
    VERDICT_WARN,
    ScenarioVerdict,
    evaluate,
)
from bench.end_to_end.runner import TIMEOUT_EXIT_CODE, ScenarioRun, load_scenario, run_scenario

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCENARIOS_DIR = REPO_ROOT / "bench" / "end_to_end" / "scenarios"
RUNS_DIR = REPO_ROOT / "bench" / "end_to_end" / "runs"

#: The exit code of a run in which a scenario decided nothing after its retries
#: (the module docstring's table).
EXIT_UNDECIDED = 3


def _enumerate_scenarios(filter_id: str | None = None) -> list[Path]:
    out: list[Path] = []
    for p in sorted(SCENARIOS_DIR.glob("BCE-*.yaml")):
        if p.name.startswith("_"):
            continue
        if filter_id is None or p.stem == filter_id:
            out.append(p)
    return out


def _archive_transcript(run: ScenarioRun, run_dir: Path, suffix: str = "") -> Path:
    """Save one run's transcript; ``suffix`` names a run a retry replaced
    (``.run1``), so the run a flake triager needs is kept beside the last."""
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / f"{run.scenario_id}{suffix}.json"
    payload = {
        **run.to_dict(),
        "raw_stream_json": run.raw_stream_json,
        "events": [
            {"role": e.role, "content": e.content, "metadata": e.metadata}
            for e in run.transcript.events
        ],
    }
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return out


def _run_with_retry(
    scenario_path: Path,
    *,
    max_cost_usd: float | None,
    cumulative_cost: float,
    keep_work_dir: bool,
    on_superseded: Callable[[ScenarioRun, int], object] | None = None,
) -> tuple[ScenarioRun, ScenarioVerdict, float]:
    """Run a scenario, retried while it decided nothing, up to its
    `flakiness_handling.retry_on_inconclusive`. The retry reads
    `ScenarioVerdict.undecided`, never the overall the scenario's
    `treat_inconclusive_as` rewrote for the report: read from the rewritten
    warn, the wiring scenarios' retry never ran (DEF-5001). A retried run
    leaves its trace: ``on_superseded`` is handed each run a retry replaced
    with its number (the orchestrator archives it), the verdict's tokens are
    the sum over the runs, and its notes say how many runs decided nothing."""
    scenario = load_scenario(scenario_path)
    flak = scenario.get("flakiness_handling") or {}
    retries = int(flak.get("retry_on_inconclusive", 0))

    def _do_run() -> tuple[ScenarioRun, ScenarioVerdict]:
        run = run_scenario(scenario_path, keep_work_dir=keep_work_dir)
        verdict = evaluate(scenario, run.transcript, cost_tokens=run.cost_tokens, target_state=run.target_state)
        verdict.run_exit_code, verdict.run_error = run.exit_code, run.error
        verdict.cli_version, verdict.model = run.cli_version, run.model
        verdict.permission_mode = run.permission_mode
        if run.exit_code == TIMEOUT_EXIT_CODE:
            # A run the timeout ended is a FAIL, never a warn: a Stop gate that
            # never releases, or an agent looping on a retry, shows up as exactly
            # this, and the cost cap sees only an estimate of it (no result
            # event, so no price: the messages' usage stands in).
            verdict.overall, verdict.undecided = VERDICT_FAIL, False
            verdict.notes = (verdict.notes + "; " if verdict.notes else "") + "the run timed out"
        elif (run.transcript.unreached_model_error() is not None
              or (not run.transcript.events and (run.exit_code not in (0, None) or run.error))):
            # The CLI found no login or a bad key (its own API-error message and
            # an is_error result, no model turn), whatever its exit code, or
            # refused the argv or never started (no events, a failed exit): no
            # hook was measured, and left to the evaluation it would read as a
            # scenario that decided nothing, retried for a fault no retry can
            # change. It fails with the run's exit code
            # and error beside it and no assertion under it, which is how a
            # report tells it from a hook verdict. A run that failed is decided:
            # retrying a refused argv or a missing login measures nothing new.
            verdict.overall, verdict.undecided = VERDICT_FAIL, False
            verdict.notes = ((verdict.notes + "; " if verdict.notes else "")
                             + f"the run itself failed (exit {run.exit_code}) before any model turn")
        return run, verdict

    run, verdict = _do_run()
    runs = 1
    tokens = run.cost_tokens
    cumulative_cost += run.cost_usd_estimate
    unarchived: list[str] = []
    while (verdict.undecided and runs <= retries
           and not (max_cost_usd is not None and cumulative_cost > max_cost_usd)):
        if on_superseded is not None:
            try:
                on_superseded(run, runs)
            except OSError as exc:
                # a side effect never blocks the measurement or drops its cost
                unarchived.append(f"run {runs} not archived: {exc}")
        run, verdict = _do_run()
        runs += 1
        tokens += run.cost_tokens
        cumulative_cost += run.cost_usd_estimate
    verdict.cost_tokens = tokens
    # every run a retry replaced decided nothing; the last did only if it is not undecided
    verdict.runs, verdict.undecided_runs = runs, runs - 1 + int(verdict.undecided)
    if unarchived:
        verdict.notes = (verdict.notes + "; " if verdict.notes else "") + "; ".join(unarchived)
    plural = "s" if runs != 1 else ""
    if verdict.undecided:
        # the scenario's own record; the run's exit code is main's to say (a
        # fail elsewhere, or this scenario's own fail mapping, outranks it)
        verdict.notes = ((verdict.notes + "; " if verdict.notes else "")
                         + f"the scenario decided nothing on {runs} run{plural}, so this run tested no hook there")
    elif runs > 1:
        verdict.notes = ((verdict.notes + "; " if verdict.notes else "")
                         + ("the first run decided nothing and was retried" if runs == 2 else
                            f"the first {runs - 1} runs decided nothing and were retried")
                         + f"; run {runs} decided")

    return run, verdict, cumulative_cost


def render_markdown(verdicts: list[ScenarioVerdict],
                    *, total_cost_usd: float, total_cost_tokens: int,
                    elapsed_seconds: float) -> str:
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pass_count = sum(1 for v in verdicts if v.overall == VERDICT_PASS)
    fail_count = sum(1 for v in verdicts if v.overall == VERDICT_FAIL)
    warn_count = sum(1 for v in verdicts if v.overall == VERDICT_WARN)
    incon_count = sum(1 for v in verdicts if v.overall == VERDICT_INCONCLUSIVE)
    undecided_count = sum(1 for v in verdicts if v.undecided)
    lines: list[str] = []
    lines.append("# End-to-End Bench Report")
    lines.append("")
    lines.append(f"**Date:** {started}")
    lines.append(
        f"**Scenarios:** {len(verdicts)} "
        f"({pass_count} pass / {fail_count} fail / {warn_count} warn / {incon_count} inconclusive)"
        + (f"; {undecided_count} decided nothing (after any retries), so this run tested no hook there"
           if undecided_count else "")
    )
    lines.append(
        f"**Cost:** {total_cost_tokens} tokens (\u2248 ${total_cost_usd:.2f})"
    )
    lines.append(f"**Elapsed:** {elapsed_seconds:.1f}s")
    lines.append("")
    for v in verdicts:
        emoji = {
            VERDICT_PASS: "\u2705",
            VERDICT_FAIL: "\u274c",
            VERDICT_WARN: "\u26a0\ufe0f",
            VERDICT_INCONCLUSIVE: "\u2754",
        }.get(v.overall, "?")
        lines.append(f"## {v.scenario_id} \u2192 {emoji} {v.overall.upper()}")
        lines.append("")
        if v.run_exit_code not in (None, 0) or v.run_error:
            # The run itself failed: say how, so a rejected argv or a timeout
            # never reads as the friction layer failing.
            lines.append(f"- run: exit {v.run_exit_code}" + (f"; error: {v.run_error}" if v.run_error else ""))
        if v.cli_version or v.model:
            lines.append(f"- ran on: Claude Code {v.cli_version or '?'}, model {v.model or '?'}"
                         + (f", permission mode {v.permission_mode}" if v.permission_mode else ""))
        for a in v.assertions:
            mark = {VERDICT_PASS: "\u2705", VERDICT_FAIL: "\u274c",
                    VERDICT_INCONCLUSIVE: "\u26a0\ufe0f"}.get(a.verdict, "?")
            lines.append(f"- {mark} **{a.name}** \u2014 {a.evidence}")
        if v.notes:
            lines.append("")
            lines.append(f"_Notes:_ {v.notes}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", default=None,
                        help="filter to one scenario id (e.g. BCE-001-...)")
    parser.add_argument("--json", action="store_true",
                        help="emit a structured JSON report instead of markdown")
    parser.add_argument("--max-cost-usd", type=float, default=None,
                        help="abort if cumulative cost exceeds this budget")
    parser.add_argument("--keep-work-dir", action="store_true",
                        help="leave per-scenario tmpdir in place for debugging")
    args = parser.parse_args(argv)

    scenarios = _enumerate_scenarios(filter_id=args.scenario)
    if not scenarios:
        msg = "no scenarios found"
        if args.scenario:
            msg += f" matching id {args.scenario!r}"
        print(msg, file=sys.stderr)
        return 2

    started_at = datetime.now(timezone.utc)
    run_dir = RUNS_DIR / started_at.strftime("%Y%m%dT%H%M%SZ")

    verdicts: list[ScenarioVerdict] = []
    cumulative_cost = 0.0
    cumulative_tokens = 0
    aborted = False
    for scenario_path in scenarios:
        try:
            run, verdict, cumulative_cost = _run_with_retry(
                scenario_path,
                max_cost_usd=args.max_cost_usd,
                cumulative_cost=cumulative_cost,
                keep_work_dir=args.keep_work_dir,
                on_superseded=lambda superseded, n: _archive_transcript(superseded, run_dir, f".run{n}"),
            )
            cumulative_tokens += verdict.cost_tokens  # every run's, a retried one's included
            _archive_transcript(run, run_dir)
            verdicts.append(verdict)
            if (
                args.max_cost_usd is not None
                and cumulative_cost > args.max_cost_usd
            ):
                aborted = True
                print(
                    f"cumulative cost ${cumulative_cost:.2f} exceeded "
                    f"--max-cost-usd ${args.max_cost_usd:.2f}; aborting",
                    file=sys.stderr,
                )
                break
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            verdicts.append(ScenarioVerdict(
                scenario_id=scenario_path.stem,
                overall=VERDICT_FAIL,
                assertions=[],
                cost_tokens=0,
                notes=f"orchestrator error: {exc}",
            ))

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    rc = _exit_code(verdicts, aborted=aborted)
    if args.json:
        # the exit code and the undecided scenarios lead the report: the issue the
        # workflow opens on a red run is this JSON, and its verdicts read `warn`
        report = {
            "exit_code": rc,
            "undecided_scenarios": [v.scenario_id for v in verdicts if v.undecided],
            "started_at": started_at.isoformat(),
            "elapsed_seconds": round(elapsed, 2),
            "total_cost_usd": round(cumulative_cost, 4),
            "total_cost_tokens": cumulative_tokens,
            "aborted": aborted,
            "verdicts": [v.to_dict() for v in verdicts],
        }
        print(json.dumps(report, indent=2))
    else:
        print(render_markdown(
            verdicts,
            total_cost_usd=cumulative_cost,
            total_cost_tokens=cumulative_tokens,
            elapsed_seconds=elapsed,
        ))
    return rc


def _exit_code(verdicts: list[ScenarioVerdict], *, aborted: bool) -> int:
    """The module docstring's table, first match: 2 on an abort, 1 on any fail,
    `EXIT_UNDECIDED` when a scenario decided nothing, 0 only when every scenario
    passed. The last arm reads the verdicts too, not the flag alone: a verdict
    built without `undecided` (its default is False) still never reads 0 unless
    it passed."""
    if aborted:
        return 2
    if any(v.overall == VERDICT_FAIL for v in verdicts):
        return 1
    if any(v.undecided for v in verdicts) or not all(v.overall == VERDICT_PASS for v in verdicts):
        # one is enough: a run whose hook scenario decided nothing tested no hook
        return EXIT_UNDECIDED
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
