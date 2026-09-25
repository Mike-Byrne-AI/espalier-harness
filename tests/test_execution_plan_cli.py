"""CLI exit-code tests for ``tools/cc/execution_plan.py``.

Pins the CLI's automation-trustworthy contract: failure states
(no plan, missing step, blocked plan) exit nonzero; success states
exit zero. All tests use ``tmp_path`` and isolated temporary repos
so the assertions don't leak between runs. Without this guard, a
refactor of the CLI's return paths could silently flip an exit
code, breaking the ``/implement-pack`` workflow's step-by-step
progression (the slash command body conditions on ``$?`` after each
``execution_plan.py mark`` call).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "cc" / "execution_plan.py"
PLAN_REL = "cc/execution_plan.json"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False, encoding="utf-8",
    )


def _create(cwd: Path, steps: int = 3) -> None:
    step_list = "|".join(f"step {i}" for i in range(steps))
    result = _run(["create", "--task", "test task", "--steps", step_list], cwd)
    assert result.returncode == 0, f"create failed: {result.stderr}"


class TestStatusExitCodes:
    def test_execution_plan_status_exits_nonzero_without_active_plan(self, tmp_path):
        """status with no plan file must exit nonzero."""
        result = _run(["status"], tmp_path)
        assert result.returncode != 0

    def test_status_with_active_plan_exits_zero(self, tmp_path):
        _create(tmp_path)
        result = _run(["status"], tmp_path)
        assert result.returncode == 0

    def test_status_no_plan_has_useful_stderr(self, tmp_path):
        result = _run(["status"], tmp_path)
        assert "No active plan" in result.stderr

    def test_status_blocked_plan_exits_nonzero(self, tmp_path):
        """status must exit nonzero when the plan has a failed step (status=blocked)."""
        _create(tmp_path, steps=3)
        _run(["mark", "0", "failed"], tmp_path)
        result = _run(["status"], tmp_path)
        assert result.returncode != 0

    def test_status_complete_plan_exits_zero(self, tmp_path):
        """status must exit zero when all steps are passed (status=complete)."""
        _create(tmp_path, steps=2)
        _run(["mark", "0", "passed"], tmp_path)
        _run(["mark", "1", "passed"], tmp_path)
        result = _run(["status"], tmp_path)
        assert result.returncode == 0


class TestCreateExitCodes:
    def test_create_valid_plan_exits_zero(self, tmp_path):
        result = _run(
            ["create", "--task", "my task", "--steps", "step0|step1|step2"],
            tmp_path,
        )
        assert result.returncode == 0

    def test_create_writes_plan_file(self, tmp_path):
        _create(tmp_path)
        assert (tmp_path / PLAN_REL).exists()


class TestMarkExitCodes:
    def test_mark_existing_step_done_exits_zero(self, tmp_path):
        _create(tmp_path, steps=3)
        result = _run(["mark", "0", "passed"], tmp_path)
        assert result.returncode == 0

    def test_mark_missing_step_exits_nonzero(self, tmp_path):
        """mark with an out-of-range index must exit nonzero."""
        _create(tmp_path, steps=3)
        result = _run(["mark", "99", "passed"], tmp_path)
        assert result.returncode != 0

    def test_mark_missing_step_has_useful_stderr(self, tmp_path):
        _create(tmp_path, steps=3)
        result = _run(["mark", "99", "passed"], tmp_path)
        assert "Invalid step index" in result.stderr

    def test_mark_without_plan_exits_nonzero(self, tmp_path):
        """mark with no plan file must exit nonzero."""
        result = _run(["mark", "0", "passed"], tmp_path)
        assert result.returncode != 0

    def test_mark_last_step_passed_sets_complete(self, tmp_path):
        """Marking all steps passed should transition plan to complete."""
        _create(tmp_path, steps=2)
        _run(["mark", "0", "passed"], tmp_path)
        _run(["mark", "1", "passed"], tmp_path)
        plan = json.loads((tmp_path / PLAN_REL).read_text(encoding="utf-8"))
        assert plan["status"] == "complete"

    def test_mark_failed_step_sets_blocked(self, tmp_path):
        """Marking a step failed should transition plan to blocked."""
        _create(tmp_path, steps=3)
        _run(["mark", "0", "failed"], tmp_path)
        plan = json.loads((tmp_path / PLAN_REL).read_text(encoding="utf-8"))
        assert plan["status"] == "blocked"


class TestMainReturnsInt:
    """main() must be callable directly and return an integer (not None)."""

    def test_main_returns_nonzero_for_status_with_no_plan(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        import importlib.util
        spec = importlib.util.spec_from_file_location("execution_plan", str(SCRIPT))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.main(["status"])
        assert isinstance(result, int)
        assert result != 0

    def test_main_returns_zero_for_successful_create(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        import importlib.util
        spec = importlib.util.spec_from_file_location("execution_plan", str(SCRIPT))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.main(["create", "--task", "t", "--steps", "s0|s1"])
        assert isinstance(result, int)
        assert result == 0


class TestResetLeavesNothingUnignored:
    """DEF-788: the ``reset`` verb the session banner prescribes demotes the
    finished plan to ``cc/_cold/<stamp>-execution_plan.json``. On a tree
    carrying init's gitignore block git ignores the record; before the entry
    every reset left a ``??`` in ``git status`` (driven 2026-09-12 on the
    self-host tree, where ``scripts/proof_tier.py`` then refused to run)."""

    @staticmethod
    def _git_init(repo: Path) -> None:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)

    def test_the_demoted_record_is_ignored_on_a_tree_carrying_the_init_block(self, tmp_path):
        from espalier.cli import (
            GITIGNORE_BLOCK_FOOTER,
            GITIGNORE_BLOCK_HEADER,
            REQUIRED_GITIGNORE,
        )
        from tests._git_oracle import require_is_gitignored

        self._git_init(tmp_path)
        (tmp_path / ".gitignore").write_text(
            "\n".join((GITIGNORE_BLOCK_HEADER, *REQUIRED_GITIGNORE, GITIGNORE_BLOCK_FOOTER)) + "\n",
            encoding="utf-8",
        )
        _create(tmp_path)

        result = _run(["reset"], tmp_path)

        assert result.returncode == 0, result.stderr
        # The message names the directory from the repo root, so the reader
        # looks in the right place: ``cc/_cold/``, not the bare ``_cold/``.
        assert "demoted to cc/_cold/" in result.stdout, result.stdout
        records = list((tmp_path / "cc" / "_cold").glob("*-execution_plan.json"))
        assert len(records) == 1, records
        rel = records[0].relative_to(tmp_path).as_posix()
        assert require_is_gitignored(tmp_path, rel), f"{rel} is not ignored by init's block"
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", "cc"],
            cwd=tmp_path, capture_output=True, text=True, check=True, encoding="utf-8",
        ).stdout
        assert "_cold" not in status, status

    def test_the_self_host_tree_ignores_the_record_too(self):
        """The self-host ``.gitignore`` carries the same line: the tier script
        refuses to run over any untracked file, and this record is the one a
        fresh session's banner tells the operator to create. Asserts against
        the tree this test file sits in, so a worktree behind main (the
        Windows walk) reds here until it advances past the entry."""
        from tests._git_oracle import require_is_gitignored

        assert require_is_gitignored(REPO_ROOT, "cc/_cold/20260912-000000-execution_plan.json")
