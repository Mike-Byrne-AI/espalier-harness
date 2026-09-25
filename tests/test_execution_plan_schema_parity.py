"""Pin cc/execution_plan.json schema parity within tools/cc/execution_plan.py.

The producer is also the consumer: `tools/cc/execution_plan.py` writes
the JSON via `create` and reads it back via `status`/`mark`. There is
no espalier-side reader (verified at pack-authoring time by
`grep -rn execution_plan.json espalier/` — only docstring/registry
mentions, no read sites). The parity surface is therefore:

1. JSON shape — top-level + per-step keys
2. CLI round-trip — `create` then `status` must agree

Drift mode: a future edit renames a field on the create-side without
updating the status-side parser. The round-trip test surfaces it.
"""

import json
import subprocess
import sys
from pathlib import Path

EXPECTED_PLAN_TOP_LEVEL_KEYS: frozenset[str] = frozenset({
    "task",
    "created",
    "status",
    "goal",
    "not_doing",
    "steps",
})

EXPECTED_STEP_KEYS: frozenset[str] = frozenset({
    "index",
    "description",
    "status",
    "note",
    "timestamp",
})

# `action_justification` is conditionally written by `cmd_mark` when the
# plan carries plan-level goal+not_doing AND the step transitions to
# `running` (TP-128 auto-compose). It is the only optional key produced
# by the live writer; legacy speculative keys like `started_at` /
# `completed_at` are NOT written by any current call site.
OPTIONAL_STEP_KEYS: frozenset[str] = frozenset({
    "action_justification",
})

REPO_ROOT = Path(__file__).resolve().parents[1]
EXECUTION_PLAN_SCRIPT = REPO_ROOT / "tools" / "cc" / "execution_plan.py"


def _create_plan_via_cli(tmp_path: Path) -> Path:
    plan_path = tmp_path / "cc" / "execution_plan.json"
    plan_path.parent.mkdir(parents=True)
    subprocess.run(
        [
            sys.executable, str(EXECUTION_PLAN_SCRIPT), "create",
            "--task", "TP-137 §C schema-parity fixture",
            "--steps", "step one|step two",
        ],
        check=True,
        cwd=tmp_path,
    )
    return plan_path


def test_writer_emits_expected_top_level_keys(tmp_path: Path) -> None:
    plan_path = _create_plan_via_cli(tmp_path)
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    actual_keys = set(payload.keys())
    unexpected = actual_keys - EXPECTED_PLAN_TOP_LEVEL_KEYS
    missing = EXPECTED_PLAN_TOP_LEVEL_KEYS - actual_keys
    assert not unexpected, f"writer emits unexpected top-level keys: {unexpected}"
    assert not missing, f"writer missing expected top-level keys: {missing}"


def test_step_keys_within_schema(tmp_path: Path) -> None:
    plan_path = _create_plan_via_cli(tmp_path)
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    for step in payload["steps"]:
        unexpected = set(step.keys()) - (EXPECTED_STEP_KEYS | OPTIONAL_STEP_KEYS)
        missing = EXPECTED_STEP_KEYS - set(step.keys())
        assert not unexpected, f"step emits unexpected keys: {unexpected}"
        assert not missing, f"step missing required keys: {missing}"


def test_cli_round_trip(tmp_path: Path) -> None:
    """create -> status round-trip. The two subcommands share no
    in-process state — they communicate via the JSON file — so a
    rename on one side that isn't propagated to the other surfaces
    here even though within-module."""
    _create_plan_via_cli(tmp_path)
    result = subprocess.run(
        [sys.executable, str(EXECUTION_PLAN_SCRIPT), "status"],
        capture_output=True, text=True, cwd=tmp_path, check=True, encoding="utf-8",
    )
    output = result.stdout + result.stderr
    assert "TP-137 §C schema-parity fixture" in output, (
        f"status subcommand did not surface the task name written by create. "
        f"output={output[:300]!r}"
    )
    assert "step one" in output and "step two" in output, (
        f"status subcommand did not surface the step descriptions. "
        f"output={output[:300]!r}"
    )
