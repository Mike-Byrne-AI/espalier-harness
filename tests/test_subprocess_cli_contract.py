"""Pin CLI subcommand surfaces that hooks invoke via subprocess.

Hooks call `espalier ...` or `python tools/cc/cognitive_blueprint.py ...`
without sharing imports. The CLI flag surface is the contract. If a CLI
flag is renamed and the caller isn't updated, the subprocess silently
no-ops (or fails with a non-2 exit that the hook may not propagate).

Pinned surfaces (TP-137 + TP-139):
- `espalier memory prune --rows N --root PATH --allow-empty --keep-newest N`
  called by: `tools/cc/hooks/post_write_check.py::_maybe_autoprune_memory`
- `python tools/cc/cognitive_blueprint.py finalize ...`
  called by: `tools/cc/hooks/stop_gate.py::_gate_finalize_blueprint`
- `python tools/cc/cognitive_blueprint.py justify ...`
  called by: `tools/cc/execution_plan.py::_record_justification_via_subprocess`
- `python -m espalier.cli init <path>` (TP-139)
  called by: `espalier/artifact_parity.py::run_init_source_path`
- `python -m espalier.cli --version` (TP-139)
  called by: `scripts/release_check.py::check_cli_entrypoint`

Symbol references (not line numbers) — line numbers drift on every
edit; symbols anchor the contract.
"""

import subprocess
import sys


def _run_cli(*args: str, expect_success: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        [sys.executable, "-m", "espalier.cli", *args],
        capture_output=True,
        text=True,
        check=False, encoding="utf-8",
    )
    if expect_success:
        assert proc.returncode == 0, (
            f"espalier {' '.join(args)} failed: rc={proc.returncode}, "
            f"stderr={proc.stderr[:300]}"
        )
    return proc


def test_memory_prune_accepts_documented_flags(tmp_path) -> None:
    """`post_write_check.py::_maybe_autoprune_memory` invokes
    `espalier memory prune --rows N --root PATH --allow-empty`."""
    memory = tmp_path / "ESPALIER_MEMORY.md"
    # Minimal fixture: prune needs the `## Session Log` section header
    # to parse; `--allow-empty` covers the empty-table case but not a
    # missing section.
    memory.write_text(
        "# fixture\n\n## Session Log\n\n| Date | What Happened | Notes |\n"
        "|------|--------------|-------|\n",
        encoding="utf-8",
    )
    _run_cli(
        "memory", "prune",
        "--rows", "1",
        "--root", str(tmp_path),
        "--allow-empty",
        expect_success=True,
    )


def test_memory_prune_help_lists_required_flags() -> None:
    """Sanity: --help mentions every flag post_write_check depends on."""
    proc = _run_cli("memory", "prune", "--help", expect_success=True)
    output = proc.stdout + proc.stderr
    for required in ("--rows", "--root", "--allow-empty", "--keep-newest"):
        assert required in output, (
            f"`espalier memory prune --help` no longer documents {required}. "
            "post_write_check.py depends on this flag surface — coordinate "
            "the rename with the caller."
        )


def test_cognitive_blueprint_finalize_subcommand_exists() -> None:
    """`stop_gate.py::_gate_finalize_blueprint` invokes
    `cognitive_blueprint.py finalize`."""
    proc = subprocess.run(
        [sys.executable, "tools/cc/cognitive_blueprint.py", "--help"],
        capture_output=True,
        text=True,
        check=False, encoding="utf-8",
    )
    assert "finalize" in proc.stdout + proc.stderr, (
        "tools/cc/cognitive_blueprint.py no longer exposes `finalize` subcommand. "
        "stop_gate.py invokes it — break the silent dependency."
    )


def test_read_summary_list_flag_exists() -> None:
    """`scripts/handoff_mechanics.py::after_goal` invokes
    `tools/cc/read_summary.py --list` to find the newest transcript stem for
    the handoff's archive leg; a renamed flag would break the handoff silently
    (the script would report no transcript row and refuse)."""
    proc = subprocess.run(
        [sys.executable, "tools/cc/read_summary.py", "--help"],
        capture_output=True,
        text=True,
        check=False, encoding="utf-8",
    )
    assert "--list" in proc.stdout + proc.stderr, (
        "tools/cc/read_summary.py no longer exposes `--list`. "
        "scripts/handoff_mechanics.py invokes it — break the silent dependency."
    )


def test_espalier_init_subcommand_accepts_target_path(tmp_path) -> None:
    """`artifact_parity.py::run_init_source_path` invokes
    `python -m espalier.cli init <path>`. The CLI must accept a single
    positional path argument and return rc=0 on a fresh git repo."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    proc = _run_cli("init", str(tmp_path), expect_success=True)
    # Sanity: settings.json must land at the target.
    assert (tmp_path / ".claude" / "settings.json").exists(), (
        f"espalier init {tmp_path} did not produce .claude/settings.json. "
        f"stdout={proc.stdout[:200]} stderr={proc.stderr[:200]}"
    )


def test_espalier_version_flag_returns_zero_with_output() -> None:
    """`release_check.py::check_cli_entrypoint` invokes
    `python -m espalier.cli --version` and expects rc=0 + non-empty
    stdout. Pin both halves of the contract."""
    proc = _run_cli("--version", expect_success=True)
    assert proc.stdout.strip(), (
        f"espalier --version produced empty stdout (rc={proc.returncode}). "
        f"release_check.py asserts both rc=0 AND non-empty output."
    )


def test_cognitive_blueprint_justify_accepts_six_fields() -> None:
    """execution_plan.py `_record_justification_via_subprocess` passes 6
    named fields to `cognitive_blueprint justify`."""
    proc = subprocess.run(
        [sys.executable, "tools/cc/cognitive_blueprint.py", "justify", "--help"],
        capture_output=True,
        text=True,
        check=False, encoding="utf-8",
    )
    output = proc.stdout + proc.stderr
    # Verify against the actual call site at execution time:
    expected_flags = [
        "--goal", "--step-rationale", "--expected-outcome",
        "--not-doing", "--tool", "--content-hash",
    ]
    missing = [f for f in expected_flags if f not in output]
    assert not missing, (
        f"`cognitive_blueprint.py justify --help` missing flags: {missing}. "
        "`execution_plan.py::_record_justification_via_subprocess` passes "
        "these; the contract is the CLI surface."
    )
