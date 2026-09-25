"""End-to-end bench orchestrator.

Enumerates scenarios under `bench/end_to_end/scenarios/`, runs each
via `runner.run_scenario`, evaluates with `assertions.evaluate`, and
produces a markdown or JSON report. Tracks cumulative cost; aborts if
`--max-cost-usd` is exceeded. Saves raw transcripts to
`bench/end_to_end/runs/<timestamp>/<scenario_id>.json` for replay.

Exit codes:
    0  every scenario `pass` or `warn`.
    1  any scenario `fail` -- including a per-scenario orchestrator error
       (invalid scenario YAML, missing `claude` CLI) caught as a FAIL verdict.
    2  cumulative `--max-cost-usd` exceeded, or no scenarios matched `--scenario`.

Cost discipline is the load-bearing constraint here. Scheduled CI
(weekly + workflow_dispatch) is the only place this should run with
real LLM cost. See bench/end_to_end/README.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
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
from bench.end_to_end.runner import ScenarioRun, load_scenario, run_scenario

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCENARIOS_DIR = REPO_ROOT / "bench" / "end_to_end" / "scenarios"
RUNS_DIR = REPO_ROOT / "bench" / "end_to_end" / "runs"


def _enumerate_scenarios(filter_id: str | None = None) -> list[Path]:
    out: list[Path] = []
    for p in sorted(SCENARIOS_DIR.glob("BCE-*.yaml")):
        if p.name.startswith("_"):
            continue
        if filter_id is None or p.stem == filter_id:
            out.append(p)
    return out


def _archive_transcript(run: ScenarioRun, run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / f"{run.scenario_id}.json"
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
) -> tuple[ScenarioRun, ScenarioVerdict, float]:
    """Run a scenario with retry-on-inconclusive per scenario config."""
    scenario = load_scenario(scenario_path)
    flak = scenario.get("flakiness_handling") or {}
    retries = int(flak.get("retry_on_inconclusive", 0))

    def _do_run() -> tuple[ScenarioRun, ScenarioVerdict]:
        run = run_scenario(scenario_path, keep_work_dir=keep_work_dir)
        verdict = evaluate(scenario, run.transcript, cost_tokens=run.cost_tokens)
        return run, verdict

    run, verdict = _do_run()
    cumulative_cost += run.cost_usd_estimate
    if max_cost_usd is not None and cumulative_cost > max_cost_usd:
        return run, verdict, cumulative_cost

    attempt = 0
    while verdict.overall == VERDICT_INCONCLUSIVE and attempt < retries:
        attempt += 1
        run, verdict = _do_run()
        cumulative_cost += run.cost_usd_estimate
        if max_cost_usd is not None and cumulative_cost > max_cost_usd:
            break

    return run, verdict, cumulative_cost


def render_markdown(verdicts: list[ScenarioVerdict],
                    *, total_cost_usd: float, total_cost_tokens: int,
                    elapsed_seconds: float) -> str:
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pass_count = sum(1 for v in verdicts if v.overall == VERDICT_PASS)
    fail_count = sum(1 for v in verdicts if v.overall == VERDICT_FAIL)
    warn_count = sum(1 for v in verdicts if v.overall == VERDICT_WARN)
    incon_count = sum(1 for v in verdicts if v.overall == VERDICT_INCONCLUSIVE)
    lines: list[str] = []
    lines.append("# End-to-End Bench Report")
    lines.append("")
    lines.append(f"**Date:** {started}")
    lines.append(
        f"**Scenarios:** {len(verdicts)} "
        f"({pass_count} pass / {fail_count} fail / {warn_count} warn / {incon_count} inconclusive)"
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
            )
            cumulative_tokens += run.cost_tokens
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
    if args.json:
        report = {
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

    if aborted:
        return 2
    if any(v.overall == VERDICT_FAIL for v in verdicts):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
