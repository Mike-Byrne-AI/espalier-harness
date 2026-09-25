"""Subprocess driver.

Invokes Claude Code as a subprocess against a scenario YAML, captures
the stream-json transcript, and returns a `ScenarioRun`. Real LLM cost
incurred per call; this module is exercised in CI via
`.github/workflows/end-to-end-bench.yml` and locally by operators.

Network and `claude` CLI invocations are isolated to this module —
`transcript.py` and `assertions.py` are pure transforms over the
result. Unit tests of the parser and assertion framework do not need to
run real subprocesses.

Auth: the operator must export `ANTHROPIC_API_KEY` in the environment.
The runner does not embed or read keys from disk.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from bench.end_to_end.transcript import Transcript, parse_stream_json

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = REPO_ROOT / "bench" / "end_to_end" / "templates"
DEFAULT_TIMEOUT_SECONDS = 300  # 5 minutes per scenario


@dataclass(frozen=True)
class ScenarioRun:
    scenario_id: str
    started_at: datetime
    ended_at: datetime
    exit_code: int
    transcript: Transcript
    cost_tokens: int
    cost_usd_estimate: float
    raw_stream_json: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "exit_code": self.exit_code,
            "cost_tokens": self.cost_tokens,
            "cost_usd_estimate": round(self.cost_usd_estimate, 4),
            "error": self.error,
            "n_events": len(self.transcript.events),
        }


def load_scenario(path: Path) -> dict[str, Any]:
    """Parse a scenario YAML; raise ValueError on missing required fields."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: scenario must be a YAML mapping")
    required = ("id", "description", "in_scope", "verifies",
                "setup", "trigger", "expected_receiver_behavior")
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"{path.name}: missing required fields {missing}")
    # A present-but-empty or typo'd expected_receiver_behavior would evaluate to
    # zero assertions and (pre-289-F-1) vacuously PASS. Require at least one
    # recognized behavior key so a non-verifying scenario fails loudly at load,
    # not silently green at evaluation. Keys mirror the assertions.py checks
    # (note: no_repeat_of is nested under agent_actions_after, not a top-level key).
    behavior = data.get("expected_receiver_behavior") or {}
    recognized = {"must_contain_any", "must_not_contain_any",
                  "block_acknowledgment", "agent_actions_after", "max_turns"}
    if not (isinstance(behavior, dict) and recognized & set(behavior)):
        raise ValueError(
            f"{path.name}: expected_receiver_behavior has no recognized keys "
            f"(need at least one of {sorted(recognized)})"
        )
    return data


def _materialize_setup(setup: dict[str, Any], work_dir: Path) -> None:
    """Create files, copy hooks, init git, deploy settings template."""
    # files
    for entry in setup.get("files") or []:
        rel = entry["path"]
        target = work_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if "content" in entry:
            target.write_text(entry["content"], encoding="utf-8")
        elif "from_template" in entry:
            tpl = TEMPLATES_DIR / f"{entry['from_template']}.json"
            if not tpl.exists():
                raise ValueError(f"unknown template {entry['from_template']!r}")
            shutil.copy(tpl, target)

    # copy hooks if requested
    if setup.get("copy_hooks"):
        src_hooks = REPO_ROOT / "tools" / "cc"
        dst_hooks = work_dir / "tools" / "cc"
        if dst_hooks.exists():
            shutil.rmtree(dst_hooks)
        shutil.copytree(src_hooks, dst_hooks)

    # settings template
    settings_template = setup.get("settings_template")
    if settings_template:
        tpl = TEMPLATES_DIR / f"{settings_template}.json"
        if not tpl.exists():
            raise ValueError(f"unknown settings template {settings_template!r}")
        target = work_dir / ".claude" / "settings.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(tpl, target)

    # git init
    if setup.get("git_init"):
        subprocess.run(["git", "init"], cwd=str(work_dir), capture_output=True, check=False)
        # Initial commit so `git status --short` returns the dirty state cleanly.
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(work_dir), capture_output=True, check=False,
        )
        subprocess.run(
            ["git", "-c", "user.email=e2e@bench", "-c", "user.name=e2e-bench",
             "commit", "-m", "scenario init", "--allow-empty"],
            cwd=str(work_dir), capture_output=True, check=False,
        )


def _resolve_claude_cli() -> str:
    """Return the resolved path to the claude CLI; raise if absent."""
    cli = shutil.which("claude")
    if cli is None:
        raise RuntimeError(
            "claude CLI not found on PATH. Install with "
            "`npm install -g @anthropic-ai/claude-code` or follow "
            "https://docs.claude.com/en/docs/claude-code/setup."
        )
    return cli


def _estimate_cost(cost_tokens: int, *, usd_per_1k_tokens: float = 0.015) -> float:
    """Rough sonnet-tier estimate. Real billing is per-input/output tokens
    and per-cache-tier; this is a first-order approximation suitable for
    the budget cap, not for reporting."""
    return (cost_tokens / 1000.0) * usd_per_1k_tokens


def run_scenario(
    scenario_path: Path,
    *,
    work_dir: Path | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    keep_work_dir: bool = False,
) -> ScenarioRun:
    """Run one scenario end-to-end against real Claude Code.

    Materializes scenario.setup into a tmpdir, invokes
    `claude --print --output-format stream-json`, parses the transcript,
    returns a ScenarioRun. Cleans up the tmpdir unless `keep_work_dir`.
    """
    scenario = load_scenario(scenario_path)
    started_at = datetime.now(timezone.utc)
    cleanup_dir: Path | None = None
    try:
        if work_dir is None:
            work_dir = Path(tempfile.mkdtemp(prefix="cc-e2e-"))
            cleanup_dir = work_dir
        else:
            work_dir = Path(work_dir).resolve()
            work_dir.mkdir(parents=True, exist_ok=True)

        _materialize_setup(scenario.get("setup") or {}, work_dir)

        trigger = scenario.get("trigger") or {}
        trigger_type = trigger.get("type", "prompt")
        if trigger_type == "noop":
            return ScenarioRun(
                scenario_id=scenario["id"],
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
                exit_code=0,
                transcript=Transcript([]),
                cost_tokens=0,
                cost_usd_estimate=0.0,
                raw_stream_json="",
            )

        cli = _resolve_claude_cli()
        # The `claude` CLI accepts neither `--working-dir` nor `--max-turns`
        # (both were removed from the CLI; passing either makes every real
        # scenario exit 1 at arg-parse before any hook fires — the whole
        # subsystem is inoperative). Set the working directory via cwd= below
        # instead; the run is bounded by DEFAULT_TIMEOUT_SECONDS. Only flags in
        # the live CLI's surface may be added here (see the allowlist test in
        # tests/test_e2e_bench.py). A future turn/budget cap would use
        # `--max-budget-usd`, which needs an explicit dollar amount.
        cmd = [
            cli, "--print",
            "--output-format", "stream-json",
        ]

        stdin_payload = trigger.get("content") if trigger_type == "prompt" else None
        if trigger_type == "tool_call":
            # Tool-call triggers are out of scope for v0 — Claude Code's CLI
            # doesn't expose direct tool invocation. Operators wanting this
            # path should use a prompt that elicits the tool call instead.
            return ScenarioRun(
                scenario_id=scenario["id"],
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
                exit_code=2,
                transcript=Transcript([]),
                cost_tokens=0,
                cost_usd_estimate=0.0,
                raw_stream_json="",
                error="tool_call trigger not supported in this runner version",
            )

        env = os.environ.copy()
        env.setdefault("ESPALIER_E2E_BENCH", "1")

        try:
            proc = subprocess.run(
                cmd,
                input=stdin_payload,
                capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                timeout=timeout_seconds,
                env=env,
                cwd=str(work_dir),
            )
            raw = proc.stdout or ""
            exit_code = proc.returncode
            error: str | None = None
            if proc.returncode != 0 and proc.stderr:
                error = proc.stderr.strip()[:500]
        except subprocess.TimeoutExpired as exc:
            raw = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            exit_code = 124
            error = f"timeout after {timeout_seconds}s"

        events = parse_stream_json(raw)
        cost_tokens = _estimate_cost_tokens_from_events(events)
        cost_usd = _estimate_cost(cost_tokens)
        ended_at = datetime.now(timezone.utc)
        return ScenarioRun(
            scenario_id=scenario["id"],
            started_at=started_at,
            ended_at=ended_at,
            exit_code=exit_code,
            transcript=Transcript(events),
            cost_tokens=cost_tokens,
            cost_usd_estimate=cost_usd,
            raw_stream_json=raw,
            error=error,
        )
    finally:
        if cleanup_dir is not None and not keep_work_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)


def _estimate_cost_tokens_from_events(events) -> int:
    """Pull a usage/total-tokens count out of stream-json metadata when
    Claude Code surfaces it; otherwise approximate from text length.

    The approximation is intentionally crude — the cost is only used for
    the budget cap, not for billing."""
    total = 0
    saw_usage = False
    for e in events:
        meta = e.metadata
        if isinstance(meta, dict):
            usage = meta.get("usage") or meta.get("message", {}).get("usage") if isinstance(meta.get("message"), dict) else meta.get("usage")
            if isinstance(usage, dict):
                input_tokens = int(usage.get("input_tokens", 0) or 0)
                output_tokens = int(usage.get("output_tokens", 0) or 0)
                total += input_tokens + output_tokens
                saw_usage = True
    if saw_usage:
        return total
    # Fallback: ~4 chars/token approximation. tool_use events carry no
    # `content` (it's stubbed to "" by the parser) but their inputs are
    # billable input tokens — count the metadata size as a rough proxy
    # so heavy tool-call traffic doesn't silently undercount and blow
    # past --max-cost-usd.
    chars = 0
    for e in events:
        chars += len(e.content)
        if e.role == "tool_use":
            chars += len(repr(e.metadata))
    return max(1, chars // 4)


def main(argv: list[str] | None = None) -> int:
    """`python -m bench.end_to_end.runner <scenario.yaml>` for ad-hoc smoke."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--keep-work-dir", action="store_true")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)

    run = run_scenario(
        args.scenario,
        timeout_seconds=args.timeout,
        keep_work_dir=args.keep_work_dir,
    )
    print(json.dumps(run.to_dict(), indent=2))
    return 0 if run.error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
