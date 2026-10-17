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

from _wired_settings import write_wired_settings

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
    steps name nothing, or the channel cannot be read; one warning where the
    box's name could not be read."""

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

    def test_a_job_the_dispatcher_gave_another_seat_is_one_warning(self, monkeypatch, tmp_path):
        """TP-479 Wave A-3 (layer L4): a plan whose steps name a pack, a class
        or a row id the dispatcher assigned to ANOTHER seat warns, so the seat
        asks the dispatcher instead of working it; its own job is silent.
        Dies to: this seat's own assignments not excluded; ids not read from
        the step text."""
        mod = _load_plan_module()
        mail = _load_mail_module()
        from datetime import datetime, timezone
        stamp = datetime(2026, 10, 9, 20, 0, 0, tzinfo=timezone.utc)
        theirs = mail.new_message("air", "assign", "", seat="win-2", lane="TP-478 2-B", ids=["TP-478"], now=stamp)
        mine = mail.new_message("air", "assign", "", seat="mac", ids=["TP-479"], now=stamp.replace(second=1))
        stub = self._mail(monkeypatch, tmp_path, "mac", [])
        monkeypatch.setattr(stub, "read_mail", lambda root, run=None: ({"air": [theirs, mine]}, {}))
        monkeypatch.setattr(stub, "dispatcher_setting", lambda root: ("air", "stubbed"))
        lines = mod._claim_overlaps("Build TP-478 Wave 2 beside TP-479 A-3; proof: x", mail=stub)
        assert len(lines) == 1, lines
        assert lines[0].startswith("WARN: air assigned id TP-478 to win-2 (since ")
        assert "ask air before this plan works it" in lines[0]   # the assigner, who exists, not "the dispatcher"

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

    def _symbol_tree(self, mod, monkeypatch, tmp_path):
        """A working tree whose `tools/cc/mail.py` defines `send` and `Board.render`."""
        (tmp_path / "tools" / "cc").mkdir(parents=True)
        (tmp_path / "tools" / "cc" / "mail.py").write_text(
            "def send():\n    return 1\n\n\nclass Board:\n    def render(self):\n        return 2\n", encoding="utf-8")
        monkeypatch.setattr(mod._paths, "_repo_root", lambda: tmp_path)

    def test_a_symbols_step_meets_a_live_claim_by_the_symbol(self, monkeypatch, tmp_path):
        """TP-702 Wave 1 (1-C): a step's `symbols:` reach the claims matcher, and a claim naming
        the same function warns by it. Dies to: the field not read, or not handed to the matcher
        (the step meets the claim as a path only, or not at all with no `files:`)."""
        mod = _load_plan_module()
        self._symbol_tree(mod, monkeypatch, tmp_path)
        mail = _load_mail_module()
        claim = mail.new_message("win", "claim", "", lane="lane/w", symbols=["tools/cc/mail.py::send"])
        stub = self._mail(monkeypatch, tmp_path, "mac", [claim])
        lines = mod._claim_overlaps("Fix the send; symbols: tools/cc/mail.py::send(); proof: x", mail=stub)
        assert len(lines) == 1, lines
        assert lines[0].startswith("WARN: win claims symbol tools/cc/mail.py::send on lane/w (since "), lines[0]
        other = mod._claim_overlaps("Render; symbols: tools/cc/mail.py::Board.render; proof: x", mail=stub)
        assert other == [l for l in other if "no symbol in common" in l] and len(other) == 1, other

    def test_a_typed_symbol_that_resolves_to_nothing_warns(self, monkeypatch, tmp_path):
        """A symbol is the one thing a seat spells by hand here. Dies to: the step's symbols
        never checked against the file's definitions (a typo meets no claim, in silence)."""
        mod = _load_plan_module()
        self._symbol_tree(mod, monkeypatch, tmp_path)
        stub = self._mail(monkeypatch, tmp_path, "mac", [])
        lines = mod._claim_overlaps(
            "s; symbols: tools/cc/mail.py::sned, tools/cc/mail.py::Board.render, tools/cc/gone.py::f; proof: x",
            mail=stub)
        assert len(lines) == 2, lines
        assert "tools/cc/mail.py::sned" in lines[0] and "no definition" in lines[0] and lines[0].startswith("WARN: ")
        assert "tools/cc/gone.py::f" in lines[1] and "not in the working tree" in lines[1]
        assert all(line.isascii() for line in lines)

    def test_prose_naming_symbols_does_not_swallow_a_later_field(self):
        """One widened pattern let a `symbols:` match run on over a later `files:` in the same
        segment, and an approved plan's prose lost a path warning it gets today (code review,
        driven). Dies to: one pattern for the three fields."""
        mod = _load_plan_module()
        prose = "Update the exported symbols: none. files: tools/cc/b.py, classes: C1"
        assert mod._step_fields(prose)[0] == ["tools/cc/b.py"]

    def test_a_path_written_absolute_reads_as_its_repo_path_or_warns(self, monkeypatch, tmp_path):
        """An absolute `symbols:` entry passed the typo check by its file and then met no claim:
        the silence a plan reads as clear (failure-mode review, driven). Dies to: the entry handed
        on as written. Under the root it is the repo path; outside, a warning names it."""
        mod = _load_plan_module()
        self._symbol_tree(mod, monkeypatch, tmp_path)
        mail = _load_mail_module()
        claim = mail.new_message("win", "claim", "", lane="lane/w", symbols=["tools/cc/mail.py::send"])
        stub = self._mail(monkeypatch, tmp_path, "mac", [claim])
        inside = (tmp_path / "tools" / "cc" / "mail.py").as_posix() + "::send"
        lines = mod._claim_overlaps(f"s; symbols: {inside}; proof: x", mail=stub)
        assert len(lines) == 1 and "claims symbol tools/cc/mail.py::send" in lines[0], lines
        lines = mod._claim_overlaps("s; symbols: /elsewhere/x.py::f; proof: x", mail=stub)
        assert len(lines) == 1 and "/elsewhere/x.py::f" in lines[0] and "not a repo path" in lines[0], lines

    def test_a_typed_symbol_warning_outlives_a_channel_that_cannot_be_read(self, monkeypatch, tmp_path):
        """The typo is about the plan's own text, not the channel. Dies to: the warning computed
        where a failed mail read drops it with the claim warnings."""
        mod = _load_plan_module()
        self._symbol_tree(mod, monkeypatch, tmp_path)
        stub = self._mail(monkeypatch, tmp_path, "mac", [])

        def broken(root, run=None):
            raise OSError("no refs here")

        monkeypatch.setattr(stub, "read_mail", broken)
        lines = mod._claim_overlaps("s; symbols: tools/cc/mail.py::sned; proof: x", mail=stub)
        assert len(lines) == 1 and "tools/cc/mail.py::sned" in lines[0], lines

    def test_step_fields_keep_their_shape_beside_a_symbols_field(self):
        """Dies to: a `symbols:` entry read as a class (or the 2-tuple widened under its callers)."""
        mod = _load_plan_module()
        assert mod._step_fields("s; symbols: a.py::f; files: b.py; classes: C1") == (["b.py"], ["C1"])
        assert mod._step_symbols("s; symbols: a.py::f, `b.py::C.m` (new), c.py; files: d.py") == [
            "a.py::f", "b.py::C.m"]

    def test_an_unread_seat_name_is_one_warning_never_silence(self, monkeypatch, tmp_path):
        """A name read that failed (a timeout, a config git cannot parse) is not
        "no machine is named here": the pre-flight skipped every claim and job
        in silence, and the plan read as clear. Dies to: the unread reason
        taken for an unset name."""
        mod = _load_plan_module()
        mail = _load_mail_module()
        claim = mail.new_message("win", "claim", "", lane="lane/w", paths=["tools/cc/"])
        stub = self._mail(monkeypatch, tmp_path, None, [claim])
        unread = f"{mail.MACHINE_UNREAD} (git config took longer than 10s), so no machine is named"
        monkeypatch.setattr(stub, "machine_setting", lambda root, run=None: (None, unread))
        lines = mod._claim_overlaps(self._STEPS, mail=stub)
        assert len(lines) == 1, lines
        assert lines[0].startswith("WARN: ") and "could not be read" in lines[0], lines[0]
        assert "took longer than 10s" in lines[0] and "not checked" in lines[0] and lines[0].isascii()
        assert "git config espalier.machine <name>" not in lines[0]
        unset = "git config espalier.machine is not set, so the channel is off (the default)"
        monkeypatch.setattr(stub, "machine_setting", lambda root, run=None: (None, unset))
        assert mod._claim_overlaps(self._STEPS, mail=stub) == []   # an unset name stays silent

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


# ── the checkout's wiring notice (DEF-1192) ───────────────────────────────────

class TestTheCheckoutWiringNotice:
    """``create`` says, on stderr, when a Claude Code session launched in the
    checkout the plan is written under would launch with the gates off
    (DEF-1192: a worktree checks out tracked files only, and the project
    settings file is gitignored). Advisory, beside the claim-overlap lines: the
    plan is created and the exit code is zero either way. The first row is the
    ledger probe's own shape, a bare directory; the wired shape in the second
    comes from ``tests/_wired_settings.py``, derived from the engine's table."""

    def test_create_in_a_bare_checkout_names_the_missing_settings_file(self, tmp_path):
        result = _run(["create", "--task", "t", "--steps", "s"], tmp_path)
        assert result.returncode == 0, result.stderr
        assert ".claude/settings.json" in result.stderr, result.stderr
        assert "loads none of the harness's hooks" in result.stderr, result.stderr
        assert (tmp_path / PLAN_REL).is_file()

    def test_create_is_silent_where_the_checkout_wires_every_deployed_gate(self, tmp_path):
        write_wired_settings(tmp_path)
        result = _run(["create", "--task", "t", "--steps", "s"], tmp_path)
        assert result.returncode == 0, result.stderr
        assert "settings.json" not in result.stderr, result.stderr
        assert (tmp_path / PLAN_REL).is_file()
