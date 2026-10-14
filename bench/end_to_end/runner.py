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
import math
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


def _bounded_spawn():
    """``run_bounded`` from this checkout's ``tools/cc/_json_safe.py``, loaded
    by path, never an installed engine's: ``subprocess.run`` whose timeout
    holds on Windows, where ``run`` waits on a grandchild holding its pipe
    (DEF-3004)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_json_safe_for_end_to_end_runner", REPO_ROOT / "tools" / "cc" / "_json_safe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_bounded


run_bounded = _bounded_spawn()
TEMPLATES_DIR = REPO_ROOT / "bench" / "end_to_end" / "templates"
DEFAULT_TIMEOUT_SECONDS = 300  # 5 minutes per scenario
#: The exit code a run reports when the runner's timeout ended it (timeout(1)'s).
TIMEOUT_EXIT_CODE = 124


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
    #: From the run's `init` event: what it measured, so a report says which
    #: CLI and model a verdict holds for (CI installs an unpinned CLI).
    cli_version: str | None = None
    model: str | None = None

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
            "cli_version": self.cli_version,
            "model": self.model,
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
                  "block_acknowledgment", "agent_actions_after", "max_turns",
                  "stream_well_formed"}
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


#: Set by a parent Claude Code session: inherited, they make the child a nested
#: session and root its hooks at the parent's project, not the scenario's tmpdir.
_NESTED_SESSION_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_PROJECT_DIR")


def _friction_bypass_vars() -> tuple[str, ...]:
    """The variables that switch the friction layer off, read from the hook
    module that defines them (`tools/cc/hooks/_maintenance_mode.py`'s
    `ENV_VAR`), so a rename there follows here. Parsed, not imported: the bench
    never executes a hook module to configure itself."""
    import ast

    src = (REPO_ROOT / "tools" / "cc" / "hooks" / "_maintenance_mode.py").read_text(encoding="utf-8")
    found = tuple(
        node.value.value for node in ast.parse(src).body
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        and any(isinstance(t, ast.Name) and t.id == "ENV_VAR"
                for t in (node.targets if isinstance(node, ast.Assign) else [node.target])))
    if not found:
        # Never run a scenario with the bypass possibly still set.
        raise RuntimeError("tools/cc/hooks/_maintenance_mode.py names no ENV_VAR; the bench cannot "
                           "tell which variable switches the friction layer off")
    return found


def _scenario_env() -> dict[str, str]:
    """The nested CLI's environment: this process's, less what would make the
    run measure something other than the scenario's own wiring -- the friction
    bypass (the suite's own subprocess helpers drop it:
    `tests/conftest.py::_isolate_maintenance_mode`), every other `ESPALIER_*`
    knob a maintainer's shell carries (`ESPALIER_STOP_GATE=full` would change
    the stop gate a scenario tests; `ESPALIER_AUDIT_DIR` would send its audit
    rows to the operator's pile), and the three variables that make the child
    a nested session (`_NESTED_SESSION_VARS`). Any other setting a parent
    session exports (an effort level, a subagent model) still reaches the child."""
    bypass = _friction_bypass_vars()
    env = os.environ.copy()
    for name in [k for k in env if k.startswith("ESPALIER_")] + [*bypass, *_NESTED_SESSION_VARS]:
        env.pop(name, None)
    return env


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
        # `--verbose` is not optional: with `--print`, the live CLI rejects
        # `--output-format stream-json` without it at arg-parse ("requires
        # --verbose", 2.1.274 on), so the pair is pinned in the same test.
        # `--strict-mcp-config` loads no MCP server the scenario does not name
        # (a maintainer's claude.ai connectors otherwise join the run).
        # `--setting-sources project` makes the scenario's own
        # .claude/settings.json the only settings the run loads: without it a
        # maintainer's user-scope hooks and permission mode ride along (driven
        # 2026-10-14: a user-scope SessionStart hook told the agent to make no
        # edits, so the protected write the scenario exists to test never ran).
        cmd = [
            cli, "--print",
            "--output-format", "stream-json", "--verbose",
            "--setting-sources", "project", "--strict-mcp-config",
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

        env = _scenario_env()

        try:
            proc = run_bounded(
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
            # CPython hands a timeout its output as bytes even under text=True,
            # so decode it: the events before the timeout are the evidence.
            out = exc.stdout or b""
            raw = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
            exit_code = TIMEOUT_EXIT_CODE
            error = f"timeout after {timeout_seconds}s"

        events = parse_stream_json(raw)
        cost_tokens, cost_usd = _cost_of_run(events)
        init = next((e.metadata for e in events if e.metadata.get("type") == "system"
                     and e.metadata.get("subtype") == "init"), {})
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
            cli_version=init.get("claude_code_version"),
            model=init.get("model"),
        )
    finally:
        if cleanup_dir is not None and not keep_work_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)


def _cost_of_run(events) -> tuple[int, float]:
    """``(tokens, USD)`` for the run, from the CLI's own `result` event when it
    sent one: its `total_cost_usd`, and its usage with the cache tokens counted.
    The estimate below is the fallback for a run that ended before one (a
    timeout). Driven 2026-10-14: a run the result priced at 0.43 USD the
    estimate put at 0.036 (2,410 tokens), since it summed input and output
    tokens and left out 44,848 cache-creation and 141,327 cache-read tokens --
    and the --max-cost-usd cap reads this number."""
    result = next((e.metadata for e in reversed(events) if e.metadata.get("type") == "result"), None)
    if result is not None:
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        tokens = sum(_count(usage.get(k)) for k in (
            "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        cost = result.get("total_cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost):
            return tokens, float(cost)
        if tokens:
            # The result's usage is the whole run's; summing the messages' usage
            # on top of it would count every token twice.
            return tokens, _estimate_cost(tokens)
    tokens = _estimate_cost_tokens_from_events(events)
    return tokens, _estimate_cost(tokens)


def _count(value: Any) -> int:
    """A usage count, or 0 for anything that is not one (the run already spent
    the money; a malformed field must not crash its report)."""
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):  # json.loads accepts Infinity and NaN
        return 0


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
                # Cache reads are most of a real run's tokens (220,316 of the
                # captured 0.42 USD run's 263,375), and a run cut off before its
                # result is the runaway the cap is for. The estimate prices every
                # token at one rate, so it overstates a cache-heavy run: the safe
                # side for a cap.
                total += sum(_count(usage.get(k)) for k in (
                    "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
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
