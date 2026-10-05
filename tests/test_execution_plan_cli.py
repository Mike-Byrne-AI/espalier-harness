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


def _load_plan_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("execution_plan_for_preflight", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_mail_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("mail_for_preflight", str(REPO_ROOT / "tools" / "cc" / "mail.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestClaimOverlapPreflight:
    """`create` warns, on stderr and never as a refusal, when a step's
    `files:` or `classes:` meet another machine's live claim on the mail
    channel (tools/cc/mail.py); silent where no machine is named here, the
    steps name nothing, or the channel cannot be read."""

    _STEPS = ("Settle step; files: tools/cc/record_merge.py, tests/test_record_merge.py (new); proof: x; "
              "rollback: y|Docs; files: docs/HOOKS.md; classes: C13, C24; proof: z")

    def test_step_fields_read_paths_and_classes_from_the_step_convention(self):
        mod = _load_plan_module()
        paths, classes = mod._step_fields(self._STEPS)
        assert paths == ["tools/cc/record_merge.py", "tests/test_record_merge.py", "docs/HOOKS.md"]
        assert classes == ["C13", "C24"]
        assert mod._step_fields("a step with no fields|another") == ([], [])

    def _mail(self, monkeypatch, tmp_path, machine, claims):
        mail = _load_mail_module()
        monkeypatch.setattr(mail, "_repo_root", lambda explicit: tmp_path)
        monkeypatch.setattr(mail, "machine_setting", lambda root, run=None: (machine, "stubbed"))
        monkeypatch.setattr(mail, "read_mail", lambda root, run=None: ({"win": claims}, {}))
        return mail

    def test_a_live_claim_on_a_named_path_or_class_is_one_warning_each(self, monkeypatch, tmp_path):
        mod = _load_plan_module()
        mail = _load_mail_module()
        from datetime import datetime, timezone
        stamp = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)
        # Distinct stamps: the fold's order is (stamp, machine, position), and a
        # test that minted two claims in one second and indexed lines[0] was a
        # coin flip (failure-mode review, 2026-10-05: 11 of 20 runs red).
        claim_a = mail.new_message("win", "claim", "", lane="lane/w", paths=["tools/cc/"], now=stamp)
        claim_b = mail.new_message("win", "claim", "", classes=["C24"], now=stamp.replace(second=1))
        released = mail.new_message("win", "claim", "", paths=["docs/HOOKS.md"], now=stamp.replace(second=2))
        release = mail.new_message("win", "release", "", ack=released["id"], now=stamp.replace(second=3))
        stub = self._mail(monkeypatch, tmp_path, "mac", [claim_a, claim_b, released, release])
        lines = mod._claim_overlaps(self._STEPS, mail=stub)
        assert len(lines) == 2, lines
        assert "WARN: win claims path tools/cc/record_merge.py (their tools/cc) on lane/w (since " in lines[0]
        assert "tests/test_record_merge.py" not in lines[0]  # tests/ is not under their tools/cc
        assert "/inbox" in lines[0]
        assert "WARN: win claims class C24 (since " in lines[1]

    def test_this_machines_own_claims_and_a_nameless_box_are_silent(self, monkeypatch, tmp_path):
        mod = _load_plan_module()
        mail = _load_mail_module()
        own = mail.new_message("mac", "claim", "", paths=["tools/cc/"])
        stub = self._mail(monkeypatch, tmp_path, "mac", [])
        monkeypatch.setattr(stub, "read_mail", lambda root, run=None: ({"mac": [own]}, {}))
        assert mod._claim_overlaps(self._STEPS, mail=stub) == []
        nameless = self._mail(monkeypatch, tmp_path, None, [own])
        assert mod._claim_overlaps(self._STEPS, mail=nameless) == []

    def test_a_channel_that_cannot_be_read_is_silent_not_a_refusal(self, monkeypatch, tmp_path):
        mod = _load_plan_module()
        stub = self._mail(monkeypatch, tmp_path, "mac", [])

        def broken(root, run=None):
            raise OSError("no refs here")

        monkeypatch.setattr(stub, "read_mail", broken)
        assert mod._claim_overlaps(self._STEPS, mail=stub) == []
        assert mod._claim_overlaps("no fields at all", mail=stub) == []

    def test_one_bad_path_token_costs_itself_not_the_warnings(self, monkeypatch, tmp_path):
        """`files: ~/notes.md` made the channel's path check raise and the
        pre-flight swallow it, so every valid warning was lost and the silence
        read as "no overlap" (failure-mode review, 2026-10-05)."""
        mod = _load_plan_module()
        mail = _load_mail_module()
        claim = mail.new_message("win", "claim", "", lane="lane/w", paths=["tools/cc/"])
        stub = self._mail(monkeypatch, tmp_path, "mac", [claim])
        lines = mod._claim_overlaps("s; files: ~/notes.md, tools/cc/mail.py (new), C:/x; proof: y", mail=stub)
        assert len(lines) == 1 and "path tools/cc/mail.py (their tools/cc)" in lines[0]
        assert mod._step_fields("s; files: a.py (also touches b.py, c.py), d.py") == (["a.py", "d.py"], [])

    def test_create_in_a_scratch_tree_prints_no_warning(self, tmp_path):
        result = _run(["create", "--task", "t", "--steps",
                       "s0; files: tools/cc/mail.py|s1; files: docs/HOOKS.md"], tmp_path)
        assert result.returncode == 0 and "WARN:" not in result.stderr, result.stderr


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
