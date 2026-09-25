"""B-1 (OSS-launch): `espalier merge-settings` — opt-in hook wiring for an
adopter whose own .claude/settings.json blocked init/fuse from wiring the hooks.

These tests pin that contract because a governance tool that silently ships
disarmed is the worst failure mode: the command must wire Espalier's hook events
in, preserve every other operator key, write a .bak backup, stay idempotent, and
never stamp the file managed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from _locked import locked
from _symlink_support import requires_symlink

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = [pytest.mark.integration]


def _git_repo_with_adopter_settings(tmp_path: Path, settings: dict) -> Path:
    target = tmp_path / "adopter"
    (target / ".claude").mkdir(parents=True)
    (target / "README.md").write_text("# adopter\n", encoding="utf-8")
    (target / ".claude" / "settings.json").write_text(
        json.dumps(settings, indent=2) + "\n", encoding="utf-8"
    )
    subprocess.check_call(["git", "init", "--quiet"], cwd=str(target))
    return target


def _merge(target: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "espalier.cli", "merge-settings", str(target)],
        capture_output=True, text=True, timeout=120, encoding="utf-8",
    )


def _has_espalier_hooks(settings_path: Path) -> bool:
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    return "tools/cc/hooks" in json.dumps(data.get("hooks", {}))


class TestMergeSettings:
    def test_merge_wires_hooks_and_preserves_keys(self, tmp_path):
        target = _git_repo_with_adopter_settings(
            tmp_path,
            {"permissions": {"allow": ["Bash(ls:*)"]}, "env": {"FOO": "bar"}},
        )
        settings_path = target / ".claude" / "settings.json"
        assert not _has_espalier_hooks(settings_path)  # precondition: disarmed
        result = _merge(target)
        assert result.returncode == 0, result.stderr
        assert _has_espalier_hooks(settings_path), "hooks not wired after merge"
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        # Every operator key is preserved verbatim.
        assert data["permissions"]["allow"] == ["Bash(ls:*)"]
        assert data["env"]["FOO"] == "bar"
        # The file stays the operator's: never stamped harness-managed.
        assert "_espalier_managed" not in data

    def test_merge_preserves_operator_own_hooks(self, tmp_path):
        # A rare adopter who has their OWN hook on a shared event must keep it.
        own_hook = {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": "echo", "args": ["hi"]}],
        }
        target = _git_repo_with_adopter_settings(
            tmp_path, {"hooks": {"PreToolUse": [own_hook]}}
        )
        settings_path = target / ".claude" / "settings.json"
        assert _merge(target).returncode == 0
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        # Operator's PreToolUse hook survives alongside Espalier's.
        commands = [
            h.get("command")
            for entry in data["hooks"]["PreToolUse"]
            for h in entry.get("hooks", [])
        ]
        assert "echo" in commands, "operator's own PreToolUse hook was dropped"
        assert _has_espalier_hooks(settings_path)

    def test_merge_writes_bak_backup(self, tmp_path):
        original = {"permissions": {"allow": ["Bash(ls:*)"]}}
        target = _git_repo_with_adopter_settings(tmp_path, original)
        _merge(target)
        bak = target / ".claude" / "settings.json.bak"
        assert bak.exists(), ".bak backup not written"
        assert json.loads(bak.read_text(encoding="utf-8")) == original

    def test_merge_is_idempotent(self, tmp_path):
        target = _git_repo_with_adopter_settings(
            tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}}
        )
        assert _merge(target).returncode == 0
        settings_path = target / ".claude" / "settings.json"
        after_first = settings_path.read_text(encoding="utf-8")
        second = _merge(target)
        assert second.returncode == 0
        assert "already wired" in second.stdout
        assert settings_path.read_text(encoding="utf-8") == after_first, (
            "second merge churned an already-wired settings.json"
        )

    def test_merge_errors_when_no_settings(self, tmp_path):
        target = tmp_path / "bare"
        target.mkdir()
        subprocess.check_call(["git", "init", "--quiet"], cwd=str(target))
        result = _merge(target)
        assert result.returncode == 1
        assert "init" in result.stderr

    def test_merge_errors_on_nonobject_hooks(self, tmp_path):
        # A hand-rolled config whose `hooks` value is the wrong type must get a
        # clear message, NOT a raw TypeError traceback (this command's whole
        # population is operators with hand-rolled Claude Code configs).
        target = _git_repo_with_adopter_settings(
            tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}, "hooks": 42}
        )
        result = _merge(target)
        assert result.returncode == 1
        assert "malformed 'hooks'" in result.stderr, result.stderr
        assert "Traceback" not in result.stderr, (
            "merge-settings tracebacked on a malformed hooks value:\n" + result.stderr
        )

    def test_merge_errors_on_corrupt_settings(self, tmp_path):
        target = tmp_path / "corrupt"
        (target / ".claude").mkdir(parents=True)
        (target / ".claude" / "settings.json").write_text(
            "{not json", encoding="utf-8"
        )
        subprocess.check_call(["git", "init", "--quiet"], cwd=str(target))
        result = _merge(target)
        assert result.returncode == 1
        assert "parse" in result.stderr.lower()


class TestMergeCore:
    """TP-183: direct unit tests of the extracted merge core
    (`merge_hooks_into_settings`). The core is the single implementation behind
    both `merge-settings` and `init/fuse --wire-hooks`; it returns a stable
    MergeResult status and NEVER overwrites a malformed file."""

    @staticmethod
    def _settings(tmp_path: Path, data) -> Path:
        (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
        path = tmp_path / ".claude" / "settings.json"
        path.write_text(json.dumps(data) + "\n", encoding="utf-8")
        return path

    def test_core_wires_and_reports_count(self, tmp_path):
        from espalier.cli import MERGE_WIRED, merge_hooks_into_settings
        path = self._settings(tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}})
        result = merge_hooks_into_settings(path, repo_root=tmp_path)
        assert result.status == MERGE_WIRED
        assert result.event_count > 0
        assert result.detail == "settings.json.bak"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "tools/cc/hooks" in json.dumps(data["hooks"])
        assert data["permissions"]["allow"] == ["Bash(ls:*)"]  # preserved
        assert "_espalier_managed" not in data  # never stamped

    def test_core_idempotent_already(self, tmp_path):
        from espalier.cli import (
            MERGE_ALREADY,
            MERGE_WIRED,
            merge_hooks_into_settings,
        )
        path = self._settings(tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}})
        assert merge_hooks_into_settings(path, repo_root=tmp_path).status == MERGE_WIRED
        before = path.read_text(encoding="utf-8")
        assert merge_hooks_into_settings(path, repo_root=tmp_path).status == MERGE_ALREADY
        assert path.read_text(encoding="utf-8") == before  # no churn

    def test_core_refuses_without_clobber(self, tmp_path):
        from espalier.cli import (
            MERGE_BAD_HOOKS,
            MERGE_NO_FILE,
            MERGE_NOT_OBJECT,
            MERGE_PARSE_ERROR,
            merge_hooks_into_settings,
        )
        # no file
        missing = tmp_path / ".claude" / "settings.json"
        assert merge_hooks_into_settings(missing, repo_root=tmp_path).status == MERGE_NO_FILE
        # unparseable JSON -> parse_error, never clobbered
        (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
        corrupt = tmp_path / ".claude" / "settings.json"
        corrupt.write_text("{not json", encoding="utf-8")
        before_corrupt = corrupt.read_text(encoding="utf-8")
        assert merge_hooks_into_settings(corrupt, repo_root=tmp_path).status == MERGE_PARSE_ERROR
        assert corrupt.read_text(encoding="utf-8") == before_corrupt  # not clobbered
        # non-object top level
        list_path = self._settings(tmp_path, ["not", "an", "object"])
        before = list_path.read_text(encoding="utf-8")
        assert merge_hooks_into_settings(list_path, repo_root=tmp_path).status == MERGE_NOT_OBJECT
        assert list_path.read_text(encoding="utf-8") == before  # not clobbered
        # non-object hooks value
        bad = self._settings(tmp_path, {"hooks": 42})
        before_bad = bad.read_text(encoding="utf-8")
        result = merge_hooks_into_settings(bad, repo_root=tmp_path)
        assert result.status == MERGE_BAD_HOOKS
        assert result.detail == "int"  # the offending type, for the caller's message
        assert bad.read_text(encoding="utf-8") == before_bad  # not clobbered

    def test_core_b12_falsy_non_dict_hooks_refused_not_replaced(self, tmp_path):
        """TP-184 B12: a FALSY non-object hooks value ([], "", 0) must refuse like
        a truthy one. Pre-fix `existing.get("hooks") or {}` coerced these to {}
        BEFORE the isinstance check, so they were silently replaced (status=wired)
        — contradicting the core's "NEVER overwrites a malformed file" contract."""
        from espalier.cli import MERGE_BAD_HOOKS, merge_hooks_into_settings
        for falsy in ([], "", 0):
            p = self._settings(tmp_path, {"hooks": falsy, "permissions": {}})
            before = p.read_text(encoding="utf-8")
            res = merge_hooks_into_settings(p, repo_root=tmp_path)
            assert res.status == MERGE_BAD_HOOKS, f"hooks={falsy!r} -> {res.status}"
            assert p.read_text(encoding="utf-8") == before  # not clobbered
            assert not p.with_name(p.name + ".bak").exists()  # no backup churn

    def test_core_b12_null_or_absent_hooks_wires_clean(self, tmp_path):
        """null / absent hooks => no operator hooks to preserve => wire cleanly
        (the legitimate empty case, distinct from a malformed non-object)."""
        from espalier.cli import MERGE_WIRED, merge_hooks_into_settings
        p = self._settings(tmp_path, {"hooks": None, "permissions": {}})
        assert merge_hooks_into_settings(p, repo_root=tmp_path).status == MERGE_WIRED

    def test_core_b5_per_event_non_list_refused_no_traceback(self, tmp_path):
        """TP-184 B5: a VALID hooks dict whose ONE event value is a truthy
        non-list (a dict/string) made `dict + list` raise an uncaught TypeError
        — a raw traceback BEFORE the backup, leaving no .bak. Now refuses cleanly,
        naming the offending event."""
        from espalier.cli import MERGE_BAD_HOOKS, merge_hooks_into_settings
        p = self._settings(tmp_path, {"hooks": {"Stop": {"foo": "bar"}}})
        res = merge_hooks_into_settings(p, repo_root=tmp_path)  # must NOT raise
        assert res.status == MERGE_BAD_HOOKS
        assert "Stop" in res.detail  # names the offending event
        assert not p.with_name(p.name + ".bak").exists()  # refused before backup

    def test_core_b6_existing_bak_not_clobbered(self, tmp_path):
        """TP-184 B6: a pristine .bak already on disk (e.g. from an earlier wire
        the operator hand-reverted) must survive the next wire — both
        settings.json and .bak are gitignored, so .bak may be the only on-disk
        original. The new backup falls back to .bak.1."""
        from espalier.cli import MERGE_WIRED, merge_hooks_into_settings
        p = self._settings(tmp_path, {"hooks": {"PreToolUse": [
            {"matcher": "*", "hooks": [{"type": "command", "command": "python3",
             "args": ["/x/mine.py"]}]}]}})
        bak = p.with_name(p.name + ".bak")
        bak.write_text("PRISTINE", encoding="utf-8")
        res = merge_hooks_into_settings(p, repo_root=tmp_path)
        assert res.status == MERGE_WIRED
        assert bak.read_text(encoding="utf-8") == "PRISTINE", ".bak was clobbered"
        assert p.with_name(p.name + ".bak.1").exists(), "no .bak.1 fallback written"

    # DEF-809 (walk 3, leg 5-F): the ladder climbed one rung per re-wire, and
    # every rung past the first held the same bytes -- an uninstall unwires the
    # file back to what the last wire backed up. A rung that already holds the
    # bytes IS the backup; the climb happens only for bytes no rung holds.

    @staticmethod
    def _rungs(path: Path) -> list[str]:
        return sorted(
            q.name for q in path.parent.iterdir() if q.name.startswith(path.name + ".bak")
        )

    def test_core_a_rewire_over_bytes_a_rung_already_holds_adds_no_rung(self, tmp_path):
        from espalier.cli import MERGE_WIRED, merge_hooks_into_settings
        p = self._settings(tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}})
        original = p.read_bytes()
        assert merge_hooks_into_settings(p, repo_root=tmp_path).status == MERGE_WIRED
        assert self._rungs(p) == ["settings.json.bak"]
        for _ in range(2):
            p.write_bytes(original)          # an uninstall's unwire, or a hand revert
            res = merge_hooks_into_settings(p, repo_root=tmp_path)
            assert res.status == MERGE_WIRED
            assert res.detail == "settings.json.bak", "detail names the rung that holds the bytes"
            assert self._rungs(p) == ["settings.json.bak"], "a duplicate rung was written"
        assert p.with_name(p.name + ".bak").read_bytes() == original

    def test_core_bytes_no_rung_holds_still_climb_the_ladder(self, tmp_path):
        from espalier.cli import MERGE_WIRED, merge_hooks_into_settings
        p = self._settings(tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}})
        original = p.read_bytes()
        merge_hooks_into_settings(p, repo_root=tmp_path)
        edited = {"permissions": {"allow": ["Bash(ls:*)", "Bash(cat:*)"]}}
        p.write_text(json.dumps(edited) + "\n", encoding="utf-8")   # the operator's own edit
        res = merge_hooks_into_settings(p, repo_root=tmp_path)
        assert res.status == MERGE_WIRED
        assert res.detail == "settings.json.bak.1"
        assert self._rungs(p) == ["settings.json.bak", "settings.json.bak.1"]
        assert p.with_name(p.name + ".bak").read_bytes() == original, ".bak was rewritten"
        assert json.loads(p.with_name(p.name + ".bak.1").read_text(encoding="utf-8")) == edited

    def test_core_a_copy_beyond_a_hand_made_gap_is_still_recognised(self, tmp_path):
        """The operator deleted ``.bak.1`` by hand and kept ``.bak.2``, which
        holds today's bytes: the climb alone would stop at the free ``.bak.1``
        and write a duplicate there. Every rung on disk is compared first."""
        from espalier.cli import MERGE_WIRED, merge_hooks_into_settings
        p = self._settings(tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}})
        p.with_name(p.name + ".bak").write_text("PRISTINE", encoding="utf-8")
        p.with_name(p.name + ".bak.2").write_bytes(p.read_bytes())
        p.with_name(p.name + ".bak.old").write_bytes(p.read_bytes())   # theirs, never a rung
        res = merge_hooks_into_settings(p, repo_root=tmp_path)
        assert res.status == MERGE_WIRED
        assert res.detail == "settings.json.bak.2"
        assert self._rungs(p) == ["settings.json.bak", "settings.json.bak.2", "settings.json.bak.old"]

    @requires_symlink
    def test_core_a_symlinked_rung_is_never_the_backup(self, tmp_path):
        """A ``.bak`` that is a link to the settings file itself holds the same
        bytes before the write and the POST-write bytes after it; taken as the
        backup it would name a copy that no longer exists. The scan passes a
        link and a real copy lands on the next free rung (both reviewers)."""
        from espalier.cli import MERGE_WIRED, merge_hooks_into_settings
        p = self._settings(tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}})
        original = p.read_bytes()
        link = p.with_name(p.name + ".bak")
        link.symlink_to(p.name)
        res = merge_hooks_into_settings(p, repo_root=tmp_path)
        assert res.status == MERGE_WIRED
        assert res.detail == "settings.json.bak.1"
        assert link.is_symlink() and link.resolve() == p.resolve(), "the link was replaced"
        assert p.with_name(p.name + ".bak.1").read_bytes() == original

    def test_core_a_rung_that_is_not_a_readable_file_is_climbed_past(self, tmp_path):
        """A directory squatting on ``.bak`` cannot hold the bytes and cannot be
        clobbered; the copy lands on the next free rung."""
        from espalier.cli import MERGE_WIRED, merge_hooks_into_settings
        p = self._settings(tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}})
        p.with_name(p.name + ".bak").mkdir()
        res = merge_hooks_into_settings(p, repo_root=tmp_path)
        assert res.status == MERGE_WIRED
        assert res.detail == "settings.json.bak.1"
        assert p.with_name(p.name + ".bak").is_dir()


class TestSettingsHasEspalierHooks:
    """TP-184 B3: `_settings_has_espalier_hooks` must require an EXECUTING Espalier
    hook entry (matched via the shape-aware exec-form oracle), not a bare
    `tools/cc/hooks` substring that any mention satisfies — else --wire-hooks /
    merge-settings false-no-op under a green banner and ship disarmed."""

    def test_genuine_exec_form_reads_wired(self):
        from espalier.cli import _settings_has_espalier_hooks
        s = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": "python3",
             "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"]}]}]}}
        assert _settings_has_espalier_hooks(s) is True

    def test_substring_bait_reads_not_wired(self):
        # B3 bait: the fragment appears only in a non-executing echo command.
        from espalier.cli import _settings_has_espalier_hooks
        s = {"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "echo tools/cc/hooks are cool"}]}]}}
        assert _settings_has_espalier_hooks(s) is False

    def test_adopter_own_unrelated_hook_reads_not_wired(self):
        from espalier.cli import _settings_has_espalier_hooks
        s = {"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command", "command": "python3",
             "args": ["${CLAUDE_PROJECT_DIR}/scripts/my_lint.py"]}]}]}}
        assert _settings_has_espalier_hooks(s) is False

    def test_legacy_shell_form_espalier_wiring_reads_wired(self):
        # TP-184 (adversarial follow-up): a pre-v0.6.5 deployment wired SHELL-FORM
        # commands (no `args`). The exec-form oracle fails CLOSED on these, so
        # without the shell-form fallback an UPGRADE would double-append the
        # canonical hooks (double enforcement) + the banner would mis-report
        # "NOT wired." A legacy espalier wiring must read as already-wired.
        from espalier.cli import _settings_has_espalier_hooks
        s = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command",
             "command": "python ${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"}]}]}}
        assert _settings_has_espalier_hooks(s) is True

    def test_non_dict_and_malformed_shapes_read_not_wired(self):
        from espalier.cli import _settings_has_espalier_hooks
        assert _settings_has_espalier_hooks("nope") is False
        assert _settings_has_espalier_hooks({"permissions": {}}) is False
        assert _settings_has_espalier_hooks({"hooks": "weird"}) is False
        assert _settings_has_espalier_hooks({"hooks": []}) is False


class TestMergeSingleImplementation:
    """TP-183: the per-event merge lives in ONE place so the operator command and
    the --wire-hooks deploy path cannot drift apart. Both callers must route
    through `merge_hooks_into_settings`; neither may re-implement the append."""

    def test_both_callers_route_through_core(self):
        import inspect

        from espalier import cli

        merge_src = inspect.getsource(cli.cmd_merge_settings)
        deploy_src = inspect.getsource(cli.deploy_harness)
        # TP-204d + TP-271b: the deploy `--wire-hooks` arming block was lifted
        # out of deploy_harness into _reconcile_existing_settings, then (271b)
        # further into _wire_hooks_into_existing so the flag path and the
        # interactive case-(b) prompt share ONE arming impl. The routing is now:
        # deploy_harness -> _reconcile_existing_settings -> _wire_hooks_into_existing
        # -> merge_hooks_into_settings (the core).
        reconcile_src = inspect.getsource(cli._reconcile_existing_settings)
        helper_src = inspect.getsource(cli._wire_hooks_into_existing)
        core_src = inspect.getsource(cli.merge_hooks_into_settings)

        assert "merge_hooks_into_settings(" in merge_src, (
            "cmd_merge_settings no longer routes through the shared merge core"
        )
        assert "_reconcile_existing_settings(" in deploy_src, (
            "deploy_harness no longer routes the existing-settings path through "
            "_reconcile_existing_settings"
        )
        assert "_wire_hooks_into_existing(" in reconcile_src, (
            "deploy --wire-hooks path (in _reconcile_existing_settings) no longer "
            "routes through the shared arming helper"
        )
        assert "merge_hooks_into_settings(" in helper_src, (
            "the arming helper (_wire_hooks_into_existing) does not route through "
            "the shared merge core"
        )
        # The distinctive per-event append shape lives ONLY in the core — if it
        # reappears in a caller, that caller has forked the merge logic.
        append_shape = "+ list(entries)"
        assert append_shape in core_src, "merge core lost its per-event append"
        for name, src in (
            ("cmd_merge_settings", merge_src),
            ("deploy_harness", deploy_src),
            ("_reconcile_existing_settings", reconcile_src),
            ("_wire_hooks_into_existing", helper_src),
        ):
            assert append_shape not in src, (
                f"{name} re-implements the per-event merge; call the core instead"
            )


class TestM3PerEventTopUp:
    """TP-192 M3: ``merge_hooks_into_settings`` returns ``MERGE_ALREADY`` only
    when EVERY canonical event is wired. A settings.json wired by an older engine
    but missing a newer event (PostToolUseFailure / SubagentStart, added TP-163)
    must be TOPPED UP — pre-fix the early MERGE_ALREADY fired on the first
    Espalier hook and never added the missing event."""

    def _write(self, tmp_path: Path, hooks_dict: dict, *, statusline: dict | None = None) -> Path:
        sp = tmp_path / ".claude" / "settings.json"
        sp.parent.mkdir(parents=True)
        data: dict = {"hooks": hooks_dict}
        if statusline is not None:
            data["statusLine"] = statusline
        sp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return sp

    def test_missing_newer_event_is_topped_up(self, tmp_path):
        from espalier.cli import (
            MERGE_WIRED,
            _build_settings_json,
            _event_groups_have_espalier_hook,
            merge_hooks_into_settings,
        )

        canonical = _build_settings_json(profile_name="workflow", repo_root=tmp_path)
        canonical_hooks = canonical["hooks"]
        # Simulate an older-engine wiring: every canonical event EXCEPT
        # PostToolUseFailure (a TP-163 addition).
        older = {k: v for k, v in canonical_hooks.items() if k != "PostToolUseFailure"}
        assert "PostToolUseFailure" not in older
        sp = self._write(tmp_path, older)

        result = merge_hooks_into_settings(sp, repo_root=tmp_path)
        assert result.status == MERGE_WIRED, result  # earn-the-red: pre-fix MERGE_ALREADY
        assert result.event_count >= 1
        after = json.loads(sp.read_text(encoding="utf-8"))["hooks"]
        # the missing event is now wired...
        assert _event_groups_have_espalier_hook(after.get("PostToolUseFailure")), after.keys()
        # ...and an already-wired event was NOT double-appended.
        assert len(after["PreToolUse"]) == len(older["PreToolUse"])

    def test_fully_wired_is_already_no_bak(self, tmp_path):
        from espalier.cli import MERGE_ALREADY, _build_settings_json, merge_hooks_into_settings

        canonical = _build_settings_json(profile_name="workflow", repo_root=tmp_path)
        # "Fully wired" carries espalier's statusLine too since DEF-798: a file
        # wired for every event but lacking the key is topped up, not left
        # as-is (TestAbsentStatusLineTopUp). This fixture was hooks-only and
        # read ALREADY by the old definition; the key is added on purpose.
        sp = self._write(tmp_path, canonical["hooks"], statusline=canonical["statusLine"])
        result = merge_hooks_into_settings(sp, repo_root=tmp_path)
        assert result.status == MERGE_ALREADY, result
        assert not sp.with_name("settings.json.bak").exists()

    def test_topup_then_rerun_is_idempotent(self, tmp_path):
        from espalier.cli import (
            MERGE_ALREADY,
            MERGE_WIRED,
            _build_settings_json,
            merge_hooks_into_settings,
        )

        canonical = _build_settings_json(profile_name="workflow", repo_root=tmp_path)
        older = {k: v for k, v in canonical["hooks"].items() if k != "SubagentStart"}
        sp = self._write(tmp_path, older)
        assert merge_hooks_into_settings(sp, repo_root=tmp_path).status == MERGE_WIRED
        # second run: now fully wired -> clean no-op, no double-append.
        assert merge_hooks_into_settings(sp, repo_root=tmp_path).status == MERGE_ALREADY
        after = json.loads(sp.read_text(encoding="utf-8"))["hooks"]
        assert len(after["SubagentStart"]) == len(canonical["hooks"]["SubagentStart"])

    def test_brand_new_adopter_still_full_merge(self, tmp_path):
        """Negative control: a settings.json with zero Espalier hooks still gets
        the full merge (MERGE_WIRED), unchanged from the prior behavior."""
        from espalier.cli import MERGE_WIRED, merge_hooks_into_settings

        sp = self._write(tmp_path, {"PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": "echo", "args": ["adopter-own-hook"]}]}]})
        result = merge_hooks_into_settings(sp, repo_root=tmp_path)
        assert result.status == MERGE_WIRED, result


class TestAbsentStatusLineTopUp:
    """DEF-798: the merge adds espalier's ``statusLine`` when the KEY is absent,
    the way it appends a missing hook event -- so ``init``/``fuse
    --wire-hooks``, ``merge-settings`` and ``upgrade --execute`` all deliver
    the interpreter-missing fallback to an adopter who arrived with a
    permissions-only file. Driven 2026-09-15 on a POSIX throwaway repo:
    ``--wire-hooks`` wired ten events, deployed the shim and the script, and
    left no ``statusLine``; ``doctor`` passed with one INFO about allow rules.
    A present key of ANY value (``null`` included: it turns Claude Code's
    statusline off on purpose) is the operator's and is never rewritten. The
    merge tests the key, never the files on disk: a deployed shim is a file,
    not a wiring (SHARP_EDGES, hook wiring vs file existence)."""

    @staticmethod
    def _write(tmp_path: Path, data: dict) -> Path:
        sp = tmp_path / ".claude" / "settings.json"
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return sp

    def test_hooks_current_but_no_statusline_is_topped_up(self, tmp_path):
        """earn-the-red: pre-fix this file reads MERGE_ALREADY and keeps no
        statusLine forever -- the walk's shape (wired, deployed, no key)."""
        from espalier.cli import MERGE_WIRED, _build_settings_json, merge_hooks_into_settings

        canonical = _build_settings_json(profile_name="workflow", repo_root=tmp_path)
        sp = self._write(tmp_path, {"hooks": canonical["hooks"]})
        result = merge_hooks_into_settings(sp, repo_root=tmp_path)
        assert result.status == MERGE_WIRED, result
        assert result.statusline_added is True
        assert result.event_count == 0, "no event was missing; only the key was"
        after = json.loads(sp.read_text(encoding="utf-8"))
        assert after["statusLine"] == canonical["statusLine"]
        assert after["hooks"] == canonical["hooks"], "a current event is never re-appended"
        assert sp.with_name("settings.json.bak").exists(), "a write takes its backup"

    def test_permissions_only_file_gains_hooks_and_statusline(self, tmp_path):
        from espalier.cli import MERGE_WIRED, _build_settings_json, merge_hooks_into_settings

        sp = self._write(tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}})
        result = merge_hooks_into_settings(sp, repo_root=tmp_path)
        assert result.status == MERGE_WIRED, result
        assert result.statusline_added is True
        assert result.event_count > 0
        after = json.loads(sp.read_text(encoding="utf-8"))
        canonical = _build_settings_json(profile_name="workflow", repo_root=tmp_path)
        assert after["statusLine"] == canonical["statusLine"]
        assert after["permissions"]["allow"] == ["Bash(ls:*)"]  # preserved
        assert "_espalier_managed" not in after  # never stamped
        assert list(after)[-1] == "statusLine", "appended after the operator's keys"

    def test_an_operators_own_statusline_is_left_alone(self, tmp_path):
        from espalier.cli import MERGE_ALREADY, _build_settings_json, merge_hooks_into_settings

        canonical = _build_settings_json(profile_name="workflow", repo_root=tmp_path)
        own = {"type": "command", "command": "my-prompt --short"}
        sp = self._write(tmp_path, {"hooks": canonical["hooks"], "statusLine": own})
        before = sp.read_text(encoding="utf-8")
        result = merge_hooks_into_settings(sp, repo_root=tmp_path)
        assert result.status == MERGE_ALREADY, result
        assert result.statusline_added is False
        assert sp.read_text(encoding="utf-8") == before

    @pytest.mark.parametrize(
        "present", [None, "off", 0, {}], ids=["null", "string", "zero", "empty-object"],
    )
    def test_a_present_key_of_any_value_is_the_operators(self, tmp_path, present):
        """Absence is the only trigger: an explicit null turns the statusline off
        on purpose, and a shape the merge does not understand is not its to
        rewrite. Every present value leaves the file byte-identical."""
        from espalier.cli import MERGE_ALREADY, _build_settings_json, merge_hooks_into_settings

        canonical = _build_settings_json(profile_name="workflow", repo_root=tmp_path)
        sp = self._write(tmp_path, {"hooks": canonical["hooks"], "statusLine": present})
        before = sp.read_text(encoding="utf-8")
        result = merge_hooks_into_settings(sp, repo_root=tmp_path)
        assert result.status == MERGE_ALREADY, result
        assert result.statusline_added is False
        assert sp.read_text(encoding="utf-8") == before

    def test_topped_up_file_is_already_on_the_rerun(self, tmp_path):
        from espalier.cli import (
            MERGE_ALREADY,
            MERGE_WIRED,
            _build_settings_json,
            merge_hooks_into_settings,
        )

        canonical = _build_settings_json(profile_name="workflow", repo_root=tmp_path)
        sp = self._write(tmp_path, {"hooks": canonical["hooks"]})
        assert merge_hooks_into_settings(sp, repo_root=tmp_path).status == MERGE_WIRED
        before = sp.read_text(encoding="utf-8")
        result = merge_hooks_into_settings(sp, repo_root=tmp_path)
        assert result.status == MERGE_ALREADY, result
        assert result.statusline_added is False
        assert sp.read_text(encoding="utf-8") == before, "no churn on the re-run"

    def test_the_added_statusline_is_rendered_for_the_host(self, tmp_path, monkeypatch):
        """The merge writes the string a fresh init renders on THIS host -- the
        shim head on a Windows key, the or-clause on POSIX -- through the same
        seam the render tests use, so the merge cannot drift from the builder."""
        from espalier import cli
        from espalier.cli import MERGE_WIRED, merge_hooks_into_settings

        monkeypatch.setattr(cli, "_render_host_is_posix", lambda: False)
        sp = self._write(tmp_path, {"permissions": {"allow": []}})
        assert merge_hooks_into_settings(sp, repo_root=tmp_path).status == MERGE_WIRED
        command = json.loads(sp.read_text(encoding="utf-8"))["statusLine"]["command"]
        fresh = cli._build_settings_json(profile_name="workflow", repo_root=tmp_path)
        assert command == fresh["statusLine"]["command"]
        assert cli.STATUSLINE_SHIM in command.replace("\\", "/") and " || " not in command

    def test_the_command_names_the_statusline_it_added(self, tmp_path):
        target = _git_repo_with_adopter_settings(
            tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}}
        )
        result = _merge(target)
        assert result.returncode == 0, result.stderr
        assert "Espalier hook event" in result.stdout and "added espalier's statusLine" in result.stdout, (
            result.stdout
        )

    def test_a_statusline_only_topup_is_said_as_such(self, tmp_path):
        """A file wired for every event but lacking the key, on a DEPLOYED tree
        (init, then the key dropped -- an older wiring): the line says what was
        written, never "wired 0 hook events", and the enforcement sentence says
        "was already active" -- the statusline is not a gate, so nothing
        transitioned. The fixture deploys the tree on purpose: on a bare repo
        the disarmed warning replaces the claim and neither sentence prints,
        which is how the first version of this test passed vacuously (both
        reviewers, 2026-09-15)."""
        target = tmp_path / "adopter"
        target.mkdir()
        subprocess.check_call(["git", "init", "--quiet"], cwd=str(target))
        subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(target)],
            check=True, capture_output=True, timeout=120, encoding="utf-8",
        )
        settings = target / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        del data["statusLine"]
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        result = _merge(target)
        assert result.returncode == 0, result.stderr
        assert "merge-settings: added espalier's statusLine into" in result.stdout, result.stdout
        assert "Enforcement was already active." in result.stdout, result.stdout
        assert "wired 0" not in result.stdout and "now active" not in result.stdout, result.stdout

    def test_the_read_only_twin_agrees_with_the_merge_on_the_key(self, tmp_path):
        """`_statusline_key_absent` (the stale-install `upgrade` preview's
        "would add") and the merge decide "add the key?" through one
        predicate; pin their agreement on every shape so a refinement in one
        cannot desynchronise the preview from what --execute writes (the
        sibling of the allow-gap twin's pin, failure-mode review)."""
        from espalier.cli import _build_settings_json, _statusline_key_absent, merge_hooks_into_settings

        absent = object()
        shapes = {
            "absent": absent, "null": None, "string": "off", "empty-object": {},
            "own": {"type": "command", "command": "my-prompt --short"},
        }
        for name, value in shapes.items():
            root = tmp_path / name
            (root / ".claude").mkdir(parents=True)
            canonical = _build_settings_json(profile_name="workflow", repo_root=root)
            data: dict = {"hooks": canonical["hooks"]}
            if value is not absent:
                data["statusLine"] = value
            sp = root / ".claude" / "settings.json"
            sp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            predicted = _statusline_key_absent(sp)
            assert merge_hooks_into_settings(sp, repo_root=root).statusline_added is predicted, name
        assert _statusline_key_absent(tmp_path / "absent" / ".claude" / "settings.json") is False, (
            "after the merge the twin reads the added key"
        )

    def test_the_did_phrase_covers_every_combination(self):
        from espalier.cli import MERGE_WIRED, MergeResult, _merge_did_phrase

        def r(**kw):
            return MergeResult(MERGE_WIRED, detail="settings.json.bak", **kw)

        assert _merge_did_phrase(r()) == "rewrote nothing"
        assert _merge_did_phrase(r(event_count=1)) == "wired 1 Espalier hook event"
        assert _merge_did_phrase(r(event_count=2), noun="hook event") == "wired 2 hook events"
        assert _merge_did_phrase(r(statusline_added=True)) == "added espalier's statusLine"
        assert _merge_did_phrase(r(event_count=3, statusline_added=True)) == (
            "wired 3 Espalier hook events and added espalier's statusLine"
        )
        assert _merge_did_phrase(
            r(event_count=3, added_allows=("Read",), statusline_added=True), profile="workflow",
        ) == (
            "wired 3 Espalier hook events, appended 1 allow rule of the 'workflow' "
            "profile and added espalier's statusLine"
        )


class TestEnforcementClaimRequiresADeployedHookTree:
    """DEF-427 (ledger §C6) — `merge-settings` must not report enforcement
    active when the hook scripts it just wired do not exist on disk.

    Driven day-one shape: an adopter who already uses Claude Code runs
    `merge-settings` on a repo where `espalier init` has never run. The merge
    writes 12 hook entries pointing at `${CLAUDE_PROJECT_DIR}/tools/cc/hooks/*.py`,
    every one of them absent, prints "Enforcement is now active." and exits 0.

    The command must still WRITE in that state — wiring settings ahead of a
    deploy is a legitimate operator move, and this command is the documented
    escape from the preserved-but-disarmed state that `init` leaves behind
    (see `cmd_merge_settings.__doc__`). A refusal would break that path. So the
    contract is: warn loudly, wire anyway, and do not assert enforcement.

    Both claim branches are covered — MERGE_WIRED and MERGE_ALREADY — because
    a re-run repeats the claim, and fixing only the first is the
    land-one-surface-short shape this repo has recorded repeatedly.

    NOT covered here, deliberately — and the scope note below was NARROWED
    2026-08-27 rather than deleted, because its core result was real and is
    still load-bearing.

    As written it said `cli.py::_wire_hooks_into_existing` "is NOT vulnerable —
    driven". Re-driven clause by clause:

    * "`--wire-hooks` only runs inside `init`" — IMPRECISE. The helper is not
      gated on the flag: the interactive case-(b) prompt reaches it with
      `wire_hooks=False`, and so does `cmd_upgrade` via `deploy_harness`.
    * "init deploys the hook tree in the same invocation" — TRUE ONLY WHEN the
      packaged deploy source is intact. `_deploy_managed_py` returns
      `skipped_source_missing`, which is non-fatal and surfaces as an aggregate
      count. That precondition is guarded at build time by
      `tests/test_wheel_payload.py`, which is why the original result held.
    * "so the claim is true there" — FALSE as a general statement. Two driven
      counterexamples, one of them on a correct install with an echo-neutered
      settings.json reaching the MERGE_ALREADY arm.

    What the original genuinely established, and what survives: under a healthy
    deploy source, the SCRIPT-EXISTENCE question this class covers is answered
    correctly at that site. What it never examined is EXECUTABLE WIRING, a
    disjoint failure mode — a gate can be present, path-correct and inert.
    Both sites are now covered by
    `TestEveryClaimSiteConsultsTheBlockers`.

    ⚠ The lesson is why this paragraph was kept: a scope-out is a CLAIM with a
    precondition, and this one recorded the conclusion while dropping the
    precondition that made it true. `cmd_upgrade`'s merge branch still makes no
    enforcement claim — that clause re-drove clean.
    """

    # The two branches word the claim differently -- "Enforcement is now
    # active." on wire, "enforcement is active" on the idempotent no-op -- so
    # the needle must be a pattern, not a substring. A plain
    # `"enforcement is active" in text` check MISSES the wired branch entirely
    # and reads as a pass; that false green was caught while earning this red.
    _CLAIM_RE = re.compile(r"enforcement is (?:now )?active", re.IGNORECASE)

    @staticmethod
    def _deploy_stub_hook_tree(target: Path) -> None:
        """Create the hook scripts a wired settings.json will reference.

        Derived from `espalier.cli.INIT_HOOK_SCRIPTS`, not a hand-written copy
        of it (STANDING_PRINCIPLES §14): if init's deploy list grows, this
        fixture grows with it instead of silently testing a stale population.
        """
        from espalier.cli import INIT_HOOK_SCRIPTS

        for rel in INIT_HOOK_SCRIPTS:
            path = target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# stub\n", encoding="utf-8")

    def test_wired_branch_makes_no_enforcement_claim_when_hook_tree_absent(
        self, tmp_path
    ):
        target = _git_repo_with_adopter_settings(
            tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}}
        )
        assert not (target / "tools" / "cc" / "hooks").exists()  # precondition

        result = _merge(target)

        combined = (result.stdout + result.stderr).lower()
        assert not self._CLAIM_RE.search(combined), (
            "merge-settings claimed enforcement with no deployed hook tree:\n"
            + result.stdout + result.stderr
        )

    def test_already_branch_makes_no_enforcement_claim_when_hook_tree_absent(
        self, tmp_path
    ):
        target = _git_repo_with_adopter_settings(
            tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}}
        )
        _merge(target)  # first run wires
        result = _merge(target)  # second run is the MERGE_ALREADY branch

        combined = (result.stdout + result.stderr).lower()
        assert "already wired" in combined or "nothing to do" in combined, (
            "expected the idempotent no-op branch, got:\n"
            + result.stdout + result.stderr
        )
        assert not self._CLAIM_RE.search(combined), (
            "the idempotent re-run repeated the enforcement claim with no "
            "deployed hook tree:\n" + result.stdout + result.stderr
        )

    def test_still_wires_and_warns_when_hook_tree_absent(self, tmp_path):
        """The command must not degrade into a refusal — that would break the
        preserved-but-disarmed recovery path it exists to serve."""
        target = _git_repo_with_adopter_settings(
            tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}, "env": {"FOO": "bar"}}
        )
        settings_path = target / ".claude" / "settings.json"

        result = _merge(target)

        assert result.returncode == 0, result.stderr
        assert _has_espalier_hooks(settings_path), (
            "merge-settings refused to wire; the recovery path is broken"
        )
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        assert data["permissions"]["allow"] == ["Bash(ls:*)"]
        assert data["env"]["FOO"] == "bar"
        combined = (result.stdout + result.stderr).lower()
        assert "tools/cc/hooks" in combined, (
            "the warning must name the missing tree so the operator can act:\n"
            + result.stdout + result.stderr
        )

    def test_wired_branch_still_claims_enforcement_when_hook_tree_present(
        self, tmp_path
    ):
        """The harness-present control. Without this the fix could pass by
        deleting the sentence outright."""
        target = _git_repo_with_adopter_settings(
            tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}}
        )
        self._deploy_stub_hook_tree(target)

        result = _merge(target)

        assert result.returncode == 0, result.stderr
        combined = (result.stdout + result.stderr).lower()
        assert self._CLAIM_RE.search(combined), (
            "the enforcement claim must survive when the tree IS deployed:\n"
            + result.stdout + result.stderr
        )

    def test_already_branch_still_claims_enforcement_when_hook_tree_present(
        self, tmp_path
    ):
        target = _git_repo_with_adopter_settings(
            tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}}
        )
        self._deploy_stub_hook_tree(target)
        _merge(target)
        result = _merge(target)

        assert result.returncode == 0, result.stderr
        combined = (result.stdout + result.stderr).lower()
        assert self._CLAIM_RE.search(combined), (
            "the idempotent branch must still confirm enforcement when the "
            "tree IS deployed:\n" + result.stdout + result.stderr
        )


class TestEnforcementClaimSurvivesRealSettingsShapes:
    """Red-team regressions on ``_missing_wired_hook_scripts`` (2026-08-26).

    All four were one root cause: the predicate hand-rolled a settings.json
    reader instead of reusing ``surface_contract.decode_bom``, which the merge
    ten lines above it already uses. The neighbour was in the same file.

    * UTF-16 (PowerShell 5.1 ``Out-File`` default) raised ``UnicodeDecodeError``
      -- a ``ValueError``, not ``JSONDecodeError`` -- which escaped the handler
      and crashed the command with rc=1 on a fully-healthy repo. A regression
      introduced by the DEF-427 fix itself.
    * A UTF-8 BOM produced ``JSONDecodeError`` -> ``[]`` -> "nothing missing",
      restoring DEF-427 verbatim on a repo with no hook tree at all.
    * The legacy pre-v0.6.5 quoted shell form kept its trailing quote, so a
      fully-armed adopter was told enforcement was dead for all 12 hooks.
    * An unreadable file returned "nothing missing", asserting enforcement from
      an unverifiable state -- the opposite of the safe direction its own
      sibling ``_read_gitignore_text`` documents in the same diff.
    """

    @staticmethod
    def _deploy(target: Path) -> None:
        from espalier.cli import INIT_HOOK_SCRIPTS, INIT_TOOL_SCRIPTS

        for rel in (*INIT_HOOK_SCRIPTS, *INIT_TOOL_SCRIPTS):
            p = target / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# stub\n", encoding="utf-8")

    CLAIM = TestEnforcementClaimRequiresADeployedHookTree._CLAIM_RE

    def test_utf16_settings_on_a_deployed_repo_does_not_crash(self, tmp_path):
        target = _git_repo_with_adopter_settings(tmp_path, {"permissions": {}})
        self._deploy(target)
        _merge(target)  # wire it (UTF-8)
        sp = target / ".claude" / "settings.json"
        sp.write_bytes(sp.read_text(encoding="utf-8").encode("utf-16"))

        result = _merge(target)

        assert result.returncode == 0, (
            "UTF-16 settings crashed merge-settings on a healthy repo:\n"
            + result.stdout + result.stderr
        )
        assert self.CLAIM.search((result.stdout + result.stderr).lower()), (
            "enforcement claim lost on a deployed repo merely because the file "
            "is UTF-16:\n" + result.stdout + result.stderr
        )

    def test_utf8_bom_does_not_resurrect_the_false_claim(self, tmp_path):
        target = _git_repo_with_adopter_settings(tmp_path, {"permissions": {}})
        self._deploy(target)
        _merge(target)
        # Now remove the tree so enforcement is genuinely dead, and add a BOM.
        for child in list((target / "tools").iterdir()):
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        sp = target / ".claude" / "settings.json"
        sp.write_bytes(b"\xef\xbb\xbf" + sp.read_bytes())

        result = _merge(target)

        combined = (result.stdout + result.stderr).lower()
        assert not self.CLAIM.search(combined), (
            "a UTF-8 BOM restored the false enforcement claim on a repo with no "
            "hook scripts:\n" + result.stdout + result.stderr
        )

    @staticmethod
    def _rewire_to_quoted_shell_form(settings_path: Path) -> None:
        """Spell every hook the pre-v0.6.5 way: path inside a quoted command."""
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        for entries in data["hooks"].values():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    if hook.get("args"):
                        hook["command"] = 'python3 "' + hook.pop("args")[0] + '"'
        settings_path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    def test_legacy_quoted_shell_form_is_not_reported_as_disarmed(self, tmp_path):
        target = _git_repo_with_adopter_settings(tmp_path, {"permissions": {}})
        self._deploy(target)
        _merge(target)
        self._rewire_to_quoted_shell_form(target / ".claude" / "settings.json")

        result = _merge(target)

        combined = (result.stdout + result.stderr).lower()
        assert self.CLAIM.search(combined), (
            "a fully-deployed repo wired in the legacy quoted shell form was "
            "reported as disarmed:\n" + result.stdout + result.stderr
        )

    def test_legacy_quoted_shell_form_still_DETECTS_a_missing_script(self, tmp_path):
        """The direction that earns the red.

        ⚠ The sibling above is NOT sufficient on its own and this comment is the
        reason: if the trailing quote survives, the mangled path fails the
        deployed-set membership check and is silently skipped, the missing-list
        comes back empty, and the enforcement claim prints anyway -- so asserting
        the claim APPEARS passes whether the quote is handled or not. Measured:
        reverting the quote-terminator left the sibling GREEN. Only asking the
        quoted form to still FIND an absent script separates the two.
        """
        target = _git_repo_with_adopter_settings(tmp_path, {"permissions": {}})
        self._deploy(target)
        _merge(target)
        self._rewire_to_quoted_shell_form(target / ".claude" / "settings.json")
        victim = target / "tools" / "cc" / "hooks" / "stop_gate.py"
        assert victim.is_file(), "precondition: the stub was deployed"
        victim.unlink()

        result = _merge(target)

        combined = (result.stdout + result.stderr).lower()
        assert not self.CLAIM.search(combined), (
            "a hook script is absent but the quoted shell form hid it, so "
            "enforcement was still claimed:\n" + result.stdout + result.stderr
        )
        assert "stop_gate.py" in combined, (
            "the WARN must name the script it could not resolve:\n"
            + result.stdout + result.stderr
        )

    def test_an_operators_own_tools_cc_script_is_not_judged(self, tmp_path):
        """We check the scripts WE deploy, not anything under a tools/cc path."""
        target = _git_repo_with_adopter_settings(tmp_path, {"permissions": {}})
        self._deploy(target)
        _merge(target)
        sp = target / ".claude" / "settings.json"
        data = json.loads(sp.read_text(encoding="utf-8"))
        data["hooks"].setdefault("PreToolUse", []).append({
            "matcher": "*",
            "hooks": [{"type": "command", "command": "python3",
                       "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/operator_own.py"]}],
        })
        sp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        result = _merge(target)

        combined = (result.stdout + result.stderr).lower()
        assert self.CLAIM.search(combined), (
            "the operator's own script under tools/cc/ was counted as our "
            "missing enforcement:\n" + result.stdout + result.stderr
        )

    def test_unreadable_settings_withholds_the_claim(self, tmp_path):
        """None must mean UNVERIFIED, never 'nothing missing'."""
        from espalier.cli import _missing_wired_hook_scripts

        target = _git_repo_with_adopter_settings(tmp_path, {"permissions": {}})
        sp = target / ".claude" / "settings.json"
        sp.write_text("{ not json", encoding="utf-8")

        assert _missing_wired_hook_scripts(target, sp) is None, (
            "an unparseable settings file must report UNVERIFIED (None), not "
            "an empty missing-list, which the caller reads as 'enforcement ok'"
        )


class TestEnforcementClaimBlockersComposeThreeOracles:
    """The enforcement claim needs THREE oracles, and none alone covers the
    class.

    Measured 2026-08-27 against four trees for the first two, and on the
    Windows walk 2 host (2026-09-09, `DEF-727`) for the third; the oracles
    are COMPLEMENTARY rather than weak/strong -- each is blind exactly where
    the others see:

        tree                     existence   executability   identity
        healthy                      0             0             0
        hook tree absent            12             0             0
        gates wired to echo          0             4             0
        PreToolUse key deleted       0             2             0
        wired to a Python 2          0             0       every wired script

    ``_missing_wired_hook_scripts`` asks "do the wired paths resolve on disk",
    so a gate wired to ``echo`` -- present, path-correct, and completely inert
    -- reads clean. ``surface_contract.unwired_governance_gates`` asks "is this
    gate executably wired", and skips gates whose file is absent by design
    (a repo that never installed the harness must not be flagged), so the
    no-hook-tree tree reads clean there. Neither runs the interpreter, so a
    ``python`` that is a Python 2 shim -- every path present, every entry
    canonical exec-form -- reads clean to both; the identity arm
    (``_wired_interpreters_not_python3``) asks ``doctor._interpreter_is_python3``
    of each wired word, and a below-floor 3.9 passes it because the guards run
    there.

    Replacing one with another therefore does NOT strengthen the check --
    it reopens whichever part the replacement is blind to. DEF-427 is the
    absent-tree part; swapping in the executability oracle alone restores it
    verbatim, and identity alone restores both. Only the UNION is correct,
    which is why this class drives all five rows rather than the poles the
    original fix covered.

    ``None`` stays distinct from ``[]``: an unreadable settings file is the
    state the check exists to refuse to make a claim about. ``not None`` is
    ``True`` in Python, so a caller writing ``not blockers`` collapses
    UNVERIFIABLE into ARMED -- the exact defect, gated behind an I/O failure
    instead of unconditionally.
    """

    @staticmethod
    def _wired_repo(tmp_path: Path) -> Path:
        """An adopter repo whose settings.json carries the canonical wiring."""
        target = _git_repo_with_adopter_settings(
            tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}}
        )
        _merge(target)
        return target

    @staticmethod
    def _deploy_hooks(target: Path) -> None:
        from espalier.cli import INIT_HOOK_SCRIPTS

        for rel in INIT_HOOK_SCRIPTS:
            path = target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# stub\n", encoding="utf-8")

    @staticmethod
    def _neuter_to_echo(settings_path: Path) -> None:
        """Keep every path, replace the interpreter with echo.

        This is the disarm shape a real operator reaches by hand-editing, and
        the one an existence check cannot see: every file is still on disk and
        every path still resolves.
        """
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        touched = 0
        for entries in data.get("hooks", {}).values():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    # The canonical wiring is EXEC-form: command is the
                    # interpreter ("python3") and the script path lives in
                    # args. An earlier draft of this helper scanned `command`
                    # for the path, found nothing, and mutated NOTHING -- the
                    # tree stayed healthy and the row passed as a clean [].
                    # Neuter the INTERPRETER and keep the path, which is both
                    # the real disarm shape and the one an existence check
                    # cannot see.
                    args = hook.get("args") or []
                    refs = any(
                        isinstance(a, str) and "tools/cc/hooks/" in a
                        for a in args
                    )
                    cmd = hook.get("command")
                    if refs and isinstance(cmd, str):
                        hook["command"] = "echo"
                        touched += 1
                    elif isinstance(cmd, str) and "tools/cc/hooks/" in cmd:
                        idx = cmd.find("tools/cc/hooks/")
                        hook["command"] = "echo " + cmd[idx:]
                        touched += 1
        assert touched, (
            "fixture mutated nothing -- it would have tested a healthy tree "
            "and read the resulting clean verdict as a pass"
        )
        settings_path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    @staticmethod
    def _delete_event(settings_path: Path, event: str) -> None:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        data.get("hooks", {}).pop(event, None)
        settings_path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    def _blockers(self, target: Path):
        from espalier.cli import _enforcement_claim_blockers

        return _enforcement_claim_blockers(
            target, target / ".claude" / "settings.json"
        )

    def test_healthy_tree_has_no_blockers(self, tmp_path):
        target = self._wired_repo(tmp_path)
        self._deploy_hooks(target)

        assert self._blockers(target) == []

    def test_absent_hook_tree_is_caught_by_the_existence_arm(self, tmp_path):
        target = self._wired_repo(tmp_path)
        # deliberately do NOT deploy the hook tree
        assert not (target / "tools" / "cc" / "hooks").exists()

        blockers = self._blockers(target)

        assert blockers, "an absent hook tree must block the enforcement claim"
        assert any("write_guard.py" in b for b in blockers), blockers

    def test_echo_neutered_gates_are_caught_by_the_executability_arm(
        self, tmp_path
    ):
        """The row an existence check cannot see, and the reason the union
        exists: every script is on disk and every path resolves."""
        target = self._wired_repo(tmp_path)
        self._deploy_hooks(target)
        settings_path = target / ".claude" / "settings.json"
        self._neuter_to_echo(settings_path)

        # Precondition: the EXISTENCE arm alone reads this tree as clean, so a
        # green here would be indistinguishable from a broken probe.
        from espalier.cli import _missing_wired_hook_scripts

        assert _missing_wired_hook_scripts(target, settings_path) == [], (
            "fixture precondition lost: the existence arm should read the "
            "echo-neutered tree as clean, which is the whole point of this row"
        )

        blockers = self._blockers(target)

        assert blockers, (
            "gates wired to echo are inert but the claim was not blocked"
        )
        assert any("write_guard.py" in b for b in blockers), blockers

    def test_deleted_event_key_is_caught_by_the_executability_arm(
        self, tmp_path
    ):
        target = self._wired_repo(tmp_path)
        self._deploy_hooks(target)
        settings_path = target / ".claude" / "settings.json"
        self._delete_event(settings_path, "PreToolUse")

        from espalier.cli import _missing_wired_hook_scripts

        assert _missing_wired_hook_scripts(target, settings_path) == [], (
            "fixture precondition lost: deleting an event key removes the "
            "wired paths, so the existence arm has nothing to resolve"
        )

        blockers = self._blockers(target)

        assert blockers, "a deleted PreToolUse key leaves write_guard inert"
        assert any("write_guard.py" in b for b in blockers), blockers

    @staticmethod
    def _rewire_every_espalier_entry(settings_path: Path, command: str) -> int:
        """Keep every path and shape, swap only the interpreter word -- the
        state a host produces when `init` wires a name that resolves to
        something other than a working Python 3 (`DEF-727`)."""
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        touched = 0
        for entries in data.get("hooks", {}).values():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    args = hook.get("args") or []
                    if any(isinstance(a, str) and "tools/cc/hooks/" in a for a in args):
                        hook["command"] = command
                        touched += 1
        settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return touched

    @staticmethod
    def _python_stub(tmp_path: Path, says: str) -> str:
        """An executable NAMED `python`, so the static exec-form arm reads the
        entry as a python interpreter site and only the identity probe can
        tell what it answers."""
        stubs = tmp_path / "stubs"
        stubs.mkdir(exist_ok=True)
        stub = stubs / "python"
        stub.write_text(f"#!/bin/sh\necho '{says}'\n", encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        return str(stub)

    def _other_two_arms_read_clean(self, target: Path) -> None:
        """Precondition for every identity-arm test: the existence arm and the
        executability arm both read the tree as armed, so a blocker can only
        have come from the arm under test."""
        from espalier.cli import _missing_wired_hook_scripts
        from espalier.harness_config import unwired_governance_gates

        settings_path = target / ".claude" / "settings.json"
        assert _missing_wired_hook_scripts(target, settings_path) == [], (
            "fixture precondition lost: the existence arm should read this tree "
            "as clean (every path resolves)"
        )
        assert unwired_governance_gates(target) == [], (
            "fixture precondition lost: the executability arm should read this "
            "tree as clean (the interpreter word is python-shaped)"
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_an_interpreter_that_is_not_python_3_is_caught_by_the_identity_arm(
        self, tmp_path
    ):
        """`DEF-727`, the third arm. Every path resolves and every entry is
        exec-form with a python-shaped word, so both existing arms read the
        tree as armed -- and the word resolves to a Python 2. On such a host
        every hook exits outside {0, 2}, a non-decision is non-blocking, and
        `init` said "Hooks now intercept" (Windows install walk 2)."""
        target = self._wired_repo(tmp_path)
        self._deploy_hooks(target)
        settings_path = target / ".claude" / "settings.json"
        assert self._rewire_every_espalier_entry(
            settings_path, self._python_stub(tmp_path, "Python 2.7.18")
        ) > 0
        self._other_two_arms_read_clean(target)

        blockers = self._blockers(target)

        assert blockers, "a wired Python 2 left the enforcement claim standing"
        assert any("write_guard.py" in b for b in blockers), blockers
        # Every hook wired through the word, not just the gates: a Python 2
        # runs none of them. The canonical wiring is the population of hook
        # ENTRIES (the helper modules under tools/cc/hooks/ are not wired).
        from espalier.harness_config import CANONICAL_HOOK_WIRING
        assert set(blockers) == {
            f"tools/cc/hooks/{script}" for script in CANONICAL_HOOK_WIRING
        }, blockers

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_a_below_floor_python_3_passes_the_identity_arm(self, tmp_path):
        """CONTROL, and the split this arm must respect: a 3.9 IS a Python 3
        and the blocking guards run on it (only the blueprint chain dies, the
        `DEF-636` half). Blocking the claim here would tell a 3.9 host its
        guards are off when they are on."""
        target = self._wired_repo(tmp_path)
        self._deploy_hooks(target)
        settings_path = target / ".claude" / "settings.json"
        self._rewire_every_espalier_entry(
            settings_path, self._python_stub(tmp_path, "Python 3.9.6")
        )
        self._other_two_arms_read_clean(target)

        assert self._blockers(target) == [], (
            "CONTROL FAILED: a below-floor Python 3 blocked the enforcement "
            "claim; identity and floor are different questions"
        )

    def test_a_python_word_that_does_not_resolve_is_caught_by_the_identity_arm(
        self, tmp_path
    ):
        """The settings.json a colleague committed from another OS: every path
        resolves, the word is python-shaped, and nothing on this host answers
        to it. Command-not-found is a non-decision too."""
        target = self._wired_repo(tmp_path)
        self._deploy_hooks(target)
        settings_path = target / ".claude" / "settings.json"
        self._rewire_every_espalier_entry(settings_path, "python-espalier-absent")
        self._other_two_arms_read_clean(target)

        blockers = self._blockers(target)

        assert blockers, "a wired interpreter that does not resolve left the claim standing"
        assert any("write_guard.py" in b for b in blockers), blockers

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_a_shape_the_rewire_declines_gets_the_by_hand_remedy(self, tmp_path):
        """DEF-620's loop, closed at the new prescriber: `--rewire-interpreter`
        declines a shebang script (and the `py` launcher, and an unterminated
        quote) and reports "nothing to rewire" -- a success-shaped sentence on
        a tree where every guard fails open. The narration must not send the
        operator there (driven by the DEF-727 failure-mode review)."""
        from espalier.cli import _disarmed_diagnosis

        target = self._wired_repo(tmp_path)
        self._deploy_hooks(target)
        settings_path = target / ".claude" / "settings.json"
        stubs = tmp_path / "stubs"
        stubs.mkdir(exist_ok=True)
        wrapper = stubs / "python_wrap.sh"   # python-shaped word, declined shape
        wrapper.write_text("#!/bin/sh\necho 'not a python'\n", encoding="utf-8")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
        self._rewire_every_espalier_entry(settings_path, str(wrapper))
        self._other_two_arms_read_clean(target)
        assert self._blockers(target), "precondition: the identity arm must block"

        reason, remedies = _disarmed_diagnosis(target)

        assert "does not answer as Python 3" in reason, reason
        joined = " ".join(remedies)
        assert "by hand" in joined, joined
        assert "-m espalier init . --rewire-interpreter" not in joined, (
            f"the narration prescribed the rewire for a shape it declines: {joined}"
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_wired_anyway_does_not_promise_arming_on_deploy_for_an_interpreter_blocker(
        self, tmp_path
    ):
        """"The settings were wired anyway so they arm the moment the harness
        is deployed" is true for one shape -- wired paths not on disk -- and
        was said for every shape. On a fully deployed tree whose interpreter
        word is a Python 2, nothing arms on deploy."""
        from espalier.cli import _disarmed_hook_tree_warning

        target = self._wired_repo(tmp_path)
        self._deploy_hooks(target)
        settings_path = target / ".claude" / "settings.json"
        self._rewire_every_espalier_entry(
            settings_path, self._python_stub(tmp_path, "Python 2.7.18")
        )

        text = _disarmed_hook_tree_warning(
            target, prefix="merge-settings", wrote_settings=True
        )

        assert "wired anyway" in text, text
        assert "arm the moment" not in text, (
            f"a deploy arms nothing on this tree, yet the banner said it would: {text}"
        )

    def test_wired_anyway_promises_arming_on_deploy_for_an_absent_hook_tree(
        self, tmp_path
    ):
        """CONTROL: the shape the sentence was written for keeps it."""
        from espalier.cli import _disarmed_hook_tree_warning

        target = self._wired_repo(tmp_path)  # deliberately no hook tree

        text = _disarmed_hook_tree_warning(
            target, prefix="merge-settings", wrote_settings=True
        )

        assert "arm the moment the harness is deployed" in text, text

    def test_unreadable_settings_returns_none_not_empty(self, tmp_path):
        """None means UNVERIFIABLE. It must not be spellable as falsy-empty:
        a caller writing `not blockers` would read it as ARMED."""
        target = self._wired_repo(tmp_path)
        self._deploy_hooks(target)
        settings_path = target / ".claude" / "settings.json"
        settings_path.write_bytes(b"{ this is not json")

        blockers = self._blockers(target)

        assert blockers is None, (
            "an unparseable settings.json must be UNVERIFIABLE, not clean"
        )
        # The trap this pins, stated as an assertion rather than a comment.
        assert not (blockers == []), "None must not compare equal to clean"


def _init(target: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "espalier.cli", "init", str(target), *extra],
        capture_output=True, text=True, timeout=180, encoding="utf-8",
    )


def _git_target(tmp_path: Path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    (target / "README.md").write_text("# target\n", encoding="utf-8")
    subprocess.check_call(["git", "init", "--quiet"], cwd=str(target))
    return target


class TestEveryClaimSiteConsultsTheBlockers:
    """Each PRODUCER of the enforcement claim, driven end-to-end.

    The sibling class above pins the PREDICATE. It cannot fail if a producer
    forgets to call it -- which is the whole defect: the oracle
    ``_missing_wired_hook_scripts`` was correct and answering correctly at
    every one of these sites while four of them never asked. A gate that pins
    the parameter and never the wiring is this repo's most-recorded false
    green (see DEF-498's inert first regression test), so these rows drive the
    real binary and read the operator-facing text.

    The disarm shape used throughout is the ECHO neuter: every hook script
    stays on disk and every wired path still resolves, so the existence oracle
    reads the tree as clean. Only the executability arm sees it. That makes
    each row a genuine test of the UNION rather than of the half that already
    shipped.

    ⚠ Every row carries the healthy control as its twin
    (``test_healthy_tree_still_claims``). Without it, deleting the claim
    sentence entirely would pass all four rows -- "says nothing" is not the
    contract; "says the true thing" is.
    """

    _CLAIM_RE = re.compile(r"enforcement is (?:now )?active|hooks now intercept",
                           re.IGNORECASE)

    @staticmethod
    def _neuter_to_echo(settings_path: Path) -> None:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        touched = 0
        for entries in data.get("hooks", {}).values():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    args = hook.get("args") or []
                    if any(isinstance(a, str) and "tools/cc/hooks/" in a
                           for a in args) and isinstance(hook.get("command"), str):
                        hook["command"] = "echo"
                        touched += 1
        assert touched, "fixture mutated nothing -- it would test a healthy tree"
        settings_path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    def _armed_then_neutered(self, tmp_path: Path) -> Path:
        target = _git_target(tmp_path)
        first = _init(target)
        assert first.returncode == 0, first.stdout + first.stderr
        settings = target / ".claude" / "settings.json"
        assert settings.is_file(), "init did not write settings.json"
        self._neuter_to_echo(settings)
        return target

    def test_healthy_tree_still_claims(self, tmp_path):
        """The control. A fix that simply stops talking passes every row below
        and helps nobody."""
        target = _git_target(tmp_path)
        _init(target)
        result = _init(target)

        combined = result.stdout + result.stderr
        assert self._CLAIM_RE.search(combined), (
            "a correctly armed repo must STILL be told enforcement is live:\n"
            + combined
        )

    def test_default_init_over_neutered_settings_withholds_the_claim(
        self, tmp_path
    ):
        """Producer: ``_reconcile_existing_settings``' case-(a) assignment.

        The reachable one, and the one every prior census missed -- it runs on
        every ``init`` over a pre-existing settings.json, needs no flag, and
        needs no broken package. Driven 2026-08-27: it named write_guard and
        plan_guard in the banner while exactly those two were inert.
        """
        target = self._armed_then_neutered(tmp_path)

        result = _init(target)

        combined = result.stdout + result.stderr
        assert not self._CLAIM_RE.search(combined), (
            "init claimed enforcement over settings whose gates are all "
            "wired to echo:\n" + combined
        )

    def test_wire_hooks_already_branch_withholds_the_claim(self, tmp_path):
        """Producer: ``_wire_hooks_into_existing`` MERGE_ALREADY arm.

        Every canonical event is present, so the merge core reports ALREADY and
        changes nothing -- while every gate it declines to touch is inert.
        """
        target = self._armed_then_neutered(tmp_path)

        result = _init(target, "--wire-hooks")

        combined = result.stdout + result.stderr
        assert not self._CLAIM_RE.search(combined), (
            "--wire-hooks reported enforcement active on a no-op run over "
            "echo-neutered gates:\n" + combined
        )

    def test_wire_hooks_wired_branch_withholds_the_claim(self, tmp_path):
        """Producer: ``_wire_hooks_into_existing`` MERGE_WIRED arm.

        Deleting one event forces a genuine top-up, so the merge reports WIRED
        -- but topping up one event does not re-arm the gates left on echo.
        """
        target = self._armed_then_neutered(tmp_path)
        settings = target / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["hooks"].pop("Stop", None)
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        result = _init(target, "--wire-hooks")

        combined = result.stdout + result.stderr
        assert not self._CLAIM_RE.search(combined), (
            "--wire-hooks topped up one event and claimed enforcement while "
            "other gates stayed inert:\n" + combined
        )

    def test_merge_settings_withholds_the_claim_when_gates_are_neutered(
        self, tmp_path
    ):
        """The site DEF-427 already 'fixed'.

        It gates on path existence, which an echo-neutered tree satisfies
        completely -- so the command that exists to rescue a disarmed repo
        reports that repo as healthy. This row is why the already-fixed site
        is in the class.
        """
        target = self._armed_then_neutered(tmp_path)

        result = _merge(target)

        combined = result.stdout + result.stderr
        assert not self._CLAIM_RE.search(combined), (
            "merge-settings reported enforcement active on echo-neutered "
            "gates:\n" + combined
        )


class TestDisarmedNarrationMatchesTheActualShape:
    """The banner and the WARN must describe the tree in front of them.

    One sentence used to serve every disarmed state: "your existing
    .claude/settings.json was preserved". It is true for exactly one shape. On
    the others it tells an operator a false story about their own repo and then
    points them at a command that will report success and leave them disarmed
    -- which is the same defect as claiming enforcement, one layer out.

    ⚠ The rewrite that split that sentence up made the SAME mistake one level
    down, and these rows exist because the first version of this class did not
    catch it: it bucketed every unwired gate as INERT, so an ABSENT gate (its
    event key deleted) was told "the entry runs no interpreter" and "No command
    repairs this" on a tree where ``merge-settings`` measurably restores it.
    Every row below that asserts prose is TWINNED with a row that drives
    ``merge-settings`` and reads the post-condition, because prose is the thing
    that was wrong both times and prose is what a prose-only gate pins.
    """

    @staticmethod
    def _neuter(settings_path: Path) -> None:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        touched = 0
        for entries in data.get("hooks", {}).values():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    if any(isinstance(a, str) and "tools/cc/hooks/" in a
                           for a in (hook.get("args") or [])):
                        hook["command"] = "echo"
                        touched += 1
        assert touched, "fixture mutated nothing"
        settings_path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    def test_inert_gates_are_not_described_as_a_preserved_file(self, tmp_path):
        target = _git_target(tmp_path)
        _init(target)
        self._neuter(target / ".claude" / "settings.json")

        out = _init(target).stdout

        assert "was preserved" not in out, (
            "init told an operator whose gates are inert that their existing "
            "settings.json was preserved -- there was nothing to preserve:\n"
            + out
        )

    def test_inert_gates_are_not_pointed_at_a_command_that_does_nothing(
        self, tmp_path
    ):
        """Driven: merge-settings returns MERGE_ALREADY on this tree, writes
        nothing, and reports success. Naming it here would be worse than
        silence."""
        target = _git_target(tmp_path)
        _init(target)
        self._neuter(target / ".claude" / "settings.json")

        out = _init(target).stdout

        assert "merge-settings . --repair" in out, out
        assert "no espalier command repairs that" not in out, out
        assert "write_guard.py" in out, "the WARN must name the dead gates:\n" + out
        # ⚠ Scoped to the REMEDY list, not to all of stdout. As a
        # whole-stdout absence check this row was coupled to
        # `_settings_has_espalier_hooks` 3000 lines away: harden that predicate
        # to require executable wiring -- a change this repo keeps being pulled
        # toward -- and the inert tree flips to the brought-your-own branch,
        # whose own stdout line mentions merge-settings. The row would red for a
        # reason that is not the row's subject, and the honest-looking repair is
        # to weaken the assertion, taking the real gate with it.
        from espalier import cli
        _, remedies = cli._disarmed_diagnosis(target)
        # The PLAIN merge is the no-op; `--repair` is the opt-in that rewrites
        # and the one spelling an inert tree may be offered.
        assert not any("merge-settings" in r and "--repair" not in r for r in remedies), (
            "an inert tree was offered merge-settings, which returns "
            "MERGE_ALREADY here and writes nothing:\n" + "\n".join(remedies)
        )

    def test_brought_your_own_still_gets_the_true_story(self, tmp_path):
        """The control for the row above: the preserved-file sentence is
        CORRECT here, and merge-settings genuinely fixes it. A rewrite that
        deleted it everywhere would pass the other rows and lose this."""
        target = _git_target(tmp_path)
        (target / ".claude").mkdir()
        (target / ".claude" / "settings.json").write_text(
            json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}) + "\n",
            encoding="utf-8",
        )

        out = _init(target).stdout

        assert "was preserved" in out, out
        assert "merge-settings" in out, out

    def test_wire_hooks_warning_is_not_labelled_merge_settings(self, tmp_path):
        """The prefix was hard-coded, so an operator running init --wire-hooks
        was handed a line labelled with a command they had not run."""
        target = _git_target(tmp_path)
        _init(target)
        self._neuter(target / ".claude" / "settings.json")
        settings = target / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["hooks"].pop("Stop", None)  # force a real top-up -> MERGE_WIRED
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        err = _init(target, "--wire-hooks").stderr

        assert "--wire-hooks: WARNING" in err, err
        assert "merge-settings: WARNING" not in err, (
            "the WARN is still labelled with the wrong command:\n" + err
        )

    def test_already_branch_does_not_claim_it_wired_anything(self, tmp_path):
        """'The settings were wired anyway' is past tense, printed on the
        branch that writes nothing at all."""
        target = _git_target(tmp_path)
        _init(target)
        self._neuter(target / ".claude" / "settings.json")

        result = _merge(target)
        combined = result.stdout + result.stderr

        assert "Nothing to do" in combined, combined
        assert "wired anyway" not in combined, (
            "the no-op branch claimed it had wired the settings:\n" + combined
        )

    # ---- the three per-gate shapes, and the mixed tree -------------------
    #
    # Fixtures are deliberately LITERAL about which script they break rather
    # than looping GOVERNANCE_BLOCKING_HOOKS: a row that derives its own
    # population from the source it polices is the docs/FAILURE_MODES.md
    # §18.4 class, and the sibling rows above are literal for the same reason.

    @staticmethod
    def _delete_event(settings_path: Path, event: str) -> None:
        """GATE_ABSENT: the whole event key is gone (the N7 shape)."""
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        assert data["hooks"].pop(event, None) is not None, "fixture removed nothing"
        settings_path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    @staticmethod
    def _drop_entry(settings_path: Path, event: str, script: str) -> None:
        """GATE_ORPHANED: the event survives, this script's entry does not."""
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        dropped = 0
        for entry in data["hooks"][event]:
            keep = []
            for hook in entry.get("hooks", []):
                blob = " ".join(
                    str(x) for x in
                    [hook.get("command"), *(hook.get("args") or [])]
                    if isinstance(x, str)
                )
                if script in blob:
                    dropped += 1
                else:
                    keep.append(hook)
            entry["hooks"] = keep
        assert dropped, "fixture removed nothing"
        assert data["hooks"][event], "fixture emptied the event -- that is ABSENT"
        settings_path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    def test_absent_event_is_offered_the_command_that_repairs_it(self, tmp_path):
        """The defect this class was extended for. Deleting ConfigChange leaves
        config_guard unwired in a shape merge-settings DOES fix, and the
        previous version narrated it as inert + "No command repairs this"."""
        target = _git_target(tmp_path)
        _init(target)
        self._delete_event(target / ".claude" / "settings.json", "ConfigChange")

        out = _init(target).stdout

        assert "config_guard.py" in out, out
        assert "merge-settings" in out, (
            "an ABSENT gate was not offered the command that repairs it:\n" + out
        )
        assert "runs no interpreter" not in out, (
            "a gate with no entry at all was described as running the wrong "
            "command:\n" + out
        )
        assert "no espalier command repairs that" not in out, (
            "the operator was told nothing repairs a tree merge-settings "
            "drives green:\n" + out
        )

    def test_absent_event_advice_is_true_when_driven(self, tmp_path):
        """The twin. The row above pins WORDS; this one runs the command those
        words name and reads the post-condition off the tree."""
        from espalier.harness_config import unwired_governance_gates

        target = _git_target(tmp_path)
        _init(target)
        self._delete_event(target / ".claude" / "settings.json", "ConfigChange")
        assert "config_guard.py" in unwired_governance_gates(target)

        _merge(target)

        assert "config_guard.py" not in unwired_governance_gates(target), (
            "the banner offers merge-settings on this tree and merge-settings "
            "did not repair it -- the advice is false"
        )

    def test_inert_advice_is_true_when_driven(self, tmp_path):
        """The converse twin: the banner says no command repairs an inert gate.
        Drive the most plausible command and confirm it does not."""
        from espalier.harness_config import unwired_governance_gates

        target = _git_target(tmp_path)
        _init(target)
        self._neuter(target / ".claude" / "settings.json")
        before = unwired_governance_gates(target)
        assert before, "fixture left the gates wired"

        _merge(target)

        assert unwired_governance_gates(target) == before, (
            "plain merge-settings repaired an inert gate -- that is --repair's "
            "job, and the plain merge's never-rewrite-an-entry contract is what "
            "the banner's wording rests on"
        )

    def test_orphaned_entry_is_not_described_as_a_wrong_command(self, tmp_path):
        """merge-settings no-ops here (its unit of work is the EVENT, which
        still exists), so the remedy is a hand edit -- but the DIAGNOSIS is not
        the inert one. There is no interpreter to restore; there is no entry."""
        target = _git_target(tmp_path)
        _init(target)
        self._drop_entry(
            target / ".claude" / "settings.json", "PreToolUse", "plan_guard.py"
        )

        out = _init(target).stdout

        assert "plan_guard.py" in out, out
        assert "no entry under PreToolUse" in out, (
            "an ORPHANED gate was not described as missing its entry:\n" + out
        )
        assert "runs no interpreter" not in out, (
            "a gate with no entry was described as running the wrong "
            "command:\n" + out
        )
        assert "will NOT add it" in out, (
            "the operator was not warned that merge-settings no-ops here:\n"
            + out
        )

    def test_orphaned_advice_is_true_when_driven(self, tmp_path):
        """The twin this class's docstring promised and did not have.

        Enumerated by a review pass: absent, inert and mixed each had a driven
        twin; orphaned had none -- and it is the hardest claim of the four,
        because "merge-settings will NOT add it" is an assertion about ANOTHER
        module's unit of work (the merge core tops up an EVENT, never an entry
        inside one). Harden the merge to top up entries -- a natural change,
        marked nowhere as load-bearing -- and the prose silently becomes false.
        """
        from espalier.harness_config import unwired_governance_gates

        target = _git_target(tmp_path)
        _init(target)
        self._drop_entry(
            target / ".claude" / "settings.json", "PreToolUse", "plan_guard.py"
        )
        assert unwired_governance_gates(target) == ["plan_guard.py"]

        _merge(target)

        assert unwired_governance_gates(target) == ["plan_guard.py"], (
            "merge-settings repaired an orphaned gate, so the banner's "
            "'merge-settings will NOT add it' is now false and the operator "
            "is being sent to a hand edit a command would do for them"
        )

    def test_mixed_tree_names_what_the_command_will_not_fix(self, tmp_path):
        """The shape a single-bucket narrator cannot express at all. One gate
        merge-settings repairs and one it does not; the caveat has to ride
        INSIDE the merge-settings line, because an operator who runs it and
        sees success does not come back for a trailing footnote."""
        settings = "settings.json"
        target = _git_target(tmp_path)
        _init(target)
        path = target / ".claude" / settings
        self._delete_event(path, "ConfigChange")          # absent  -> repairable
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data["hooks"]["Stop"]:               # inert   -> not
            for hook in entry.get("hooks", []):
                hook["command"] = "echo"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        out = _init(target).stdout

        assert "does NOT fix stop_gate.py" in out, (
            "the merge-settings line did not name the gate it leaves dead, so "
            "the operator gets a false finish:\n" + out
        )
        assert "config_guard.py" in out and "stop_gate.py" in out, out

    def test_mixed_tree_caveat_is_true_when_driven(self, tmp_path):
        """The twin for the row above: run the command and confirm it repairs
        exactly the gate the text promised and leaves exactly the one it
        disclaimed."""
        from espalier.harness_config import unwired_governance_gates

        target = _git_target(tmp_path)
        _init(target)
        path = target / ".claude" / "settings.json"
        self._delete_event(path, "ConfigChange")
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data["hooks"]["Stop"]:
            for hook in entry.get("hooks", []):
                hook["command"] = "echo"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        assert set(unwired_governance_gates(target)) == {
            "config_guard.py", "stop_gate.py"
        }

        _merge(target)

        assert unwired_governance_gates(target) == ["stop_gate.py"], (
            "the banner promised merge-settings wires ConfigChange and does "
            "NOT fix stop_gate.py; the tree disagrees"
        )

    def test_an_unrecognized_shape_is_named_not_dropped(self, tmp_path,
                                                        monkeypatch):
        """The row that makes version 4 of this bug impossible.

        Twice now the defect has been "a population narrated with one member's
        prose". The dispatch that fixes round 3 introduces a NEW way to lose a
        member: a shape it has no branch for falls through every ``if`` and
        disappears. Measured on the first draft -- one hypothetical fifth shape
        rendered the reason as ``"Hooks are NOT yet active: ."`` with the gate
        absent from the output entirely, which is strictly worse than the wrong
        sentence it replaced, because wrong prose is visible and silence is not.

        In-process rather than through the ``init`` subprocess: the point is the
        narrator's exhaustiveness, and monkeypatch cannot reach a subprocess.
        """
        from espalier import cli, harness_config

        target = _git_target(tmp_path)
        _init(target)
        self._delete_event(target / ".claude" / "settings.json", "ConfigChange")

        real = harness_config.classify_unwired_gate
        monkeypatch.setattr(
            harness_config, "classify_unwired_gate",
            lambda root, script: ("a_shape_from_the_future"
                                  if script == "config_guard.py"
                                  else real(root, script)),
        )
        reason, remedies = cli._disarmed_diagnosis(target)

        assert "config_guard.py" in reason, (
            "a gate in an unrecognized shape vanished from the banner -- the "
            f"operator is told nothing about it at all:\n{reason}"
        )
        # (An earlier draft also pinned the exact historical string
        # "Hooks are NOT yet active: ." here. Reword the prefix and that row
        # goes vacuously true forever while reading like a second gate -- the
        # line below is the one that actually fires.)
        assert ": ." not in reason, (
            "the reason rendered with an empty clause list:\n" + reason
        )
        assert any("doctor" in r for r in remedies), remedies

    def test_absent_gate_is_not_promised_a_merge_that_will_be_refused(
        self, tmp_path
    ):
        """Found by a review pass on the fix for this class, and it IS the
        class: a promise the command does not keep.

        `merge_hooks_into_settings` refuses the WHOLE file when any canonical
        event's value is a truthy non-list -- it does not skip the bad event and
        top up the rest. So on a tree with `hooks.PreToolUse` set to a string
        AND ConfigChange deleted, the banner offered merge-settings to repair
        the absent gate, and driving it returned `bad_hooks` and wrote nothing.
        """
        from espalier import cli, harness_config

        target = _git_target(tmp_path)
        _init(target)
        settings = target / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["hooks"].pop("ConfigChange", None)
        data["hooks"]["PreToolUse"] = "malformed-not-a-list"
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        # ⚠ This tree used to classify ABSENT; it now classifies
        # VOIDED_SETTINGS, and that is a CORRECTION rather than a regression.
        # The very value that makes the merge refuse (a canonical event whose
        # value is a truthy non-list) also makes Claude Code discard the entire
        # hooks block -- driven on CC 2.1.247. So "ConfigChange is absent" was
        # never the operative truth here: every gate is dead, not one.
        # The guarantee this row exists for is unchanged and still exercised
        # below: a file the merge refuses is never offered the merge.
        assert harness_config.group_unwired_gates_by_shape(target).get(
            harness_config.GATE_VOIDED_SETTINGS
        ), "expected the malformed event value to void the whole hooks block"

        reason, remedies = cli._disarmed_diagnosis(target)

        assert not any("merge-settings ." in r for r in remedies), (
            "the banner offered a command that refuses this file outright:\n"
            + "\n".join(remedies)
        )
        assert any("hooks.PreToolUse" in r for r in remedies), (
            "the real blocker was not named:\n" + "\n".join(remedies)
        )
        # And prove the withholding is EARNED, not cautious.
        before = harness_config.group_unwired_gates_by_shape(target)
        result = cli.merge_hooks_into_settings(
            settings, profile="workflow", repo_root=target
        )
        assert result.status == "bad_hooks", result
        assert harness_config.group_unwired_gates_by_shape(target) == before, (
            "merge-settings repaired this tree after all -- if so, withholding "
            "the offer is now the wrong advice"
        )

    def test_caveat_names_every_gate_the_command_leaves_behind(self, tmp_path):
        """`unfixed` must be the COMPLEMENT of what merge-settings repairs, not
        a hand-listed subset of it.

        Two shapes were missing from it, both found by review and both driven:
        an UNRECOGNIZED shape (by definition not something merge-settings can be
        claimed to fix) and LEGACY_FORM (which the enforcement claim forgives --
        but forgiving a shape in the CLAIM is not a licence to omit it from a
        list of what a command will not fix). The legacy one had a measured
        consequence: the operator ran the offered command, `init` then said
        "Hooks now intercept", and `doctor` on the same tree exited 1.
        """
        from espalier import cli

        _, remedies = cli._unwired_gate_diagnosis(
            {"absent": ["config_guard.py"],
             "legacy_form": ["write_guard.py"],
             "a_shape_from_the_future": ["stop_gate.py"]},
            "python3",
        )

        assert "does NOT fix" in remedies[0], remedies[0]
        for gate in ("write_guard.py", "stop_gate.py"):
            assert gate in remedies[0], (
                f"{gate} is not repaired by merge-settings and is missing from "
                f"the caveat, so the operator gets a false finish:\n{remedies[0]}"
            )

    def test_legacy_form_gets_no_clause_but_is_still_named(self, tmp_path):
        """The abstention and the caveat are different contracts.

        legacy_form must NOT appear as a reason enforcement is off (that is the
        false negative `b517a72` closed), and must still be named as something
        the command will not repair. Both, in one tree.
        """
        from espalier import cli

        reason, remedies = cli._unwired_gate_diagnosis(
            {"absent": ["config_guard.py"], "legacy_form": ["write_guard.py"]},
            "python3",
        )

        assert "write_guard.py" not in reason, (
            "legacy_form was narrated as a reason enforcement is off -- that is "
            f"the pre-v0.6.5 false negative b517a72 closed:\n{reason}"
        )
        assert any("write_guard.py" in r for r in remedies), (
            "legacy_form vanished from the remedies entirely:\n"
            + "\n".join(remedies)
        )


class TestMergeRefusalOracleAgreesWithTheMerge:
    """`cli._merge_refusal_detail` must answer for the merge, not beside it.

    The banner asks this predicate whether `merge-settings` would accept a file
    before offering it as a remedy. That is only safe while the predicate and
    the merge agree; a private copy of a rule is free to drift from the rule,
    and the drift would be invisible -- the banner would go on confidently
    naming a command that refuses.

    The merge itself is deliberately NOT refactored to call the predicate: it is
    a write path on an operator's own settings.json, and this agreement matrix
    buys the no-drift guarantee without touching it. If a future change makes
    the merge stricter or laxer, these rows red rather than the banner quietly
    lying.
    """

    SHAPES = [
        ("well-formed", None),
        ("event value is a string", "malformed-not-a-list"),
        ("event value is a dict", {"hooks": []}),
        ("event value is an int", 42),
        ("event value is a bool", True),
        ("event value is an empty string", ""),
        ("event value is null", None),
    ]

    @pytest.mark.parametrize("label,value", SHAPES, ids=[s[0] for s in SHAPES])
    def test_predicate_agrees_with_the_real_merge(self, tmp_path, label, value):
        from espalier import cli

        target = _git_target(tmp_path)
        _init(target)
        settings = target / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        if label != "well-formed":
            data["hooks"]["PreToolUse"] = value
        # Force a real merge attempt rather than the MERGE_ALREADY short-circuit.
        data["hooks"].pop("ConfigChange", None)
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        managed = cli._build_settings_json(
            profile_name="workflow", repo_root=target
        ).get("hooks", {})
        predicted = cli._merge_refusal_detail(
            json.loads(settings.read_text(encoding="utf-8")), managed
        )
        actual = cli.merge_hooks_into_settings(
            settings, profile="workflow", repo_root=target
        )

        refused = actual.status == "bad_hooks"
        assert bool(predicted) == refused, (
            f"[{label}] predicate said {predicted!r}, merge said "
            f"{actual.status!r} ({getattr(actual, 'detail', None)!r})"
        )
        if refused:
            assert predicted == actual.detail, (
                f"[{label}] predicate and merge disagree on the DETAIL: "
                f"{predicted!r} vs {actual.detail!r}"
            )


class TestClaimOraclesSurviveHandEditedSettingsShapes:
    """`hooks` can be any JSON type in a file a human edited.

    Filed against the measurement the 2026-08-26 session pre-registered and
    lost: this repo's gates pin MUTATIONS OF THE IMPLEMENTATION well and
    VARIATIONS OF THE INPUT not at all, and the two populations are disjoint,
    so a caught-tally over the first says nothing about the second. Both of
    this block's blockers were input shapes. So were the previous block's
    (UTF-16, a BOM, a legacy quoting style).

    Driven origin: ``{"hooks": 42}`` crashed ``init --wire-hooks`` with
    ``AttributeError: 'int' object has no attribute 'values'`` on an adopter
    tree the command had already, correctly, refused to touch. ``or {}`` reads
    like a guard and is not one -- every truthy non-dict sails through it.

    The distinction that matters and that a single guard gets wrong: ABSENT
    (no ``hooks`` key, or ``null``) is the ordinary brought-your-own adopter
    and means "nothing wired"; a truthy WRONG TYPE means "this file is not
    something we can read". One has a remedy, the other has a repair.
    """

    @staticmethod
    def _tree(tmp_path: Path, name: str, blob: str) -> Path:
        target = tmp_path / name
        (target / ".claude").mkdir(parents=True)
        (target / ".claude" / "settings.json").write_text(blob, encoding="utf-8")
        return target

    @pytest.mark.parametrize("name,blob", [
        ("absent", '{"permissions": {"allow": []}}'),
        ("null", '{"hooks": null}'),
    ])
    def test_absent_hooks_reads_as_nothing_wired_not_unreadable(
        self, tmp_path, name, blob
    ):
        from espalier.cli import _enforcement_claim_blockers

        target = self._tree(tmp_path, name, blob)
        result = _enforcement_claim_blockers(
            target, target / ".claude" / "settings.json"
        )
        assert result == [], (
            f"{name}: a file that simply wires no hooks was reported "
            f"unreadable, which sends the operator to a repair instead of a "
            f"remedy (got {result!r})"
        )

    @pytest.mark.parametrize("name,blob", [
        ("int", '{"hooks": 42}'),
        ("list", '{"hooks": [1, 2]}'),
        ("string", '{"hooks": "on"}'),
        ("top_level_array", "[1, 2, 3]"),
        ("unparseable", "{not json"),
    ])
    def test_malformed_shapes_are_unverifiable_and_never_crash(
        self, tmp_path, name, blob
    ):
        from espalier.cli import (
            _enforcement_claim_blockers,
            _gate_wiring_is_unreadable_legacy_form,
        )

        target = self._tree(tmp_path, name, blob)
        # Must not raise. The crash this pins reached rc=1 on a real init.
        result = _enforcement_claim_blockers(
            target, target / ".claude" / "settings.json"
        )
        assert result is None, (
            f"{name}: a malformed hooks value must be UNVERIFIABLE, not clean "
            f"(got {result!r} -- and [] would let the claim print)"
        )
        assert _gate_wiring_is_unreadable_legacy_form(
            target, "write_guard.py"
        ) is False, f"{name}: the abstention probe must not raise or abstain"

    @pytest.mark.parametrize("name,blob", [
        ("int", '{"hooks": 42}'),
        ("list", '{"hooks": [1, 2]}'),
    ])
    def test_init_does_not_crash_on_a_malformed_hooks_value(
        self, tmp_path, name, blob
    ):
        """End-to-end: the reader is reachable from the init banner now, so a
        shape that only ever hit a refusal branch before can crash the command
        that reports it."""
        target = tmp_path / f"e2e_{name}"
        target.mkdir()
        (target / "README.md").write_text("# t\n", encoding="utf-8")
        subprocess.check_call(["git", "init", "--quiet"], cwd=str(target))
        (target / ".claude").mkdir()
        (target / ".claude" / "settings.json").write_text(blob, encoding="utf-8")

        result = _init(target, "--wire-hooks")

        assert "AttributeError" not in result.stderr, result.stderr
        assert result.returncode == 0, (
            f"init exited {result.returncode} on a malformed hooks value:\n"
            + result.stderr
        )


class TestNoOfferSiteNamesAMergeThatRefuses:
    """DEF-700, the contract the reviewers asked for: on every FILE shape the
    merge refuses before reading a hook value, no surface that names
    `merge-settings` as a remedy may still offer it. The reference set is the
    offer SITES -- doctor's next steps and the init banner's remedies; the fuse
    banner has its own twin in tests/test_fuse.py -- so a fifth site added
    without the check reds here only if it is added to this list, which is why
    the list is short and the docstring says so.
    """

    REFUSING = ("no_file", "parse_error", "not_object", "bad_hooks")
    SHAPES = [
        ("zero bytes", b""),
        ("truncated object", b'{"hooks": {"PreToolUse": ['),
        ("top-level list", b"[]\n"),
        ("hooks block is a string", b'{"hooks": "x"}\n'),
        ("UTF-16 BOM only", b"\xff\xfe"),
    ]

    @pytest.mark.parametrize("label,raw", SHAPES, ids=[s[0] for s in SHAPES])
    def test_doctor_and_the_init_banner_withhold_the_offer(self, tmp_path, label, raw):
        from espalier import cli
        from espalier.doctor import run_doctor_check

        target = _git_target(tmp_path)
        _init(target)
        settings = target / ".claude" / "settings.json"
        settings.write_bytes(raw)
        actual = cli.merge_hooks_into_settings(settings, profile="workflow", repo_root=target)
        assert actual.status in self.REFUSING, f"[{label}] fixture does not refuse: {actual}"

        steps = run_doctor_check(target).get("next_steps", [])
        assert not any(s.startswith("run") and "merge-settings" in s for s in steps), (
            f"[{label}] doctor offered the refused merge:\n" + "\n".join(steps)
        )
        reason, remedies = cli._disarmed_diagnosis(target)
        assert not any("merge-settings ." in r and r.startswith("To activate") for r in remedies), (
            f"[{label}] the init banner offered the refused merge:\n{reason}\n" + "\n".join(remedies)
        )
        assert remedies, f"[{label}] the banner left the operator with no step"

    def test_every_verdict_kind_has_its_own_sentence(self):
        """The renderer's fallback sentence exists so a diagnostic cannot
        crash on a verdict it does not know; this pins that no verdict the
        predicate can emit reaches it."""
        from espalier import cli

        # A typed floor, on purpose: the loop below derives its population
        # from the tuple it polices, so a kind DELETED from the tuple while
        # the predicate still emits it would pass here on a smaller
        # population (the census's §18.4 shrink). Six kinds today; a change
        # means a new sentence AND a new file-shape row in tests/test_doctor.py.
        assert len(cli.MERGE_REFUSAL_KINDS) == 6, cli.MERGE_REFUSAL_KINDS
        for kind in cli.MERGE_REFUSAL_KINDS:
            refused = kind + "PreToolUse: str" if kind.endswith(".") else f"{kind}: detail"
            sentence = cli.merge_refusal_step(refused, "python3")
            assert "as it stands" not in sentence, f"{kind!r} fell to the fallback: {sentence}"
            assert "merge-settings" in sentence, sentence


class TestProfileAllowRulesReachAnExistingInstall:
    """DEF-715: `merge-settings` and `upgrade` carried hook events into an
    existing settings.json but never a profile allow rule, and nothing said
    the profile had moved under the install (driven 2026-09-07 on the self-host
    box right after the pytest python3 twin shipped: "hooks already wired --
    nothing to do", rule absent).

    Two halves, because `permissions` is the operator's (the merge's contract
    is to preserve it, pinned by `test_core_wires_and_reports_count`): the core
    ALWAYS reports the profile rules the file lacks, and APPENDS them only when
    asked (`add_allows=True`, the `--add-allows` opt-in). It never removes a
    rule of the operator's own.
    """

    @staticmethod
    def _wired(tmp_path: Path, allow) -> Path:
        """A settings.json fully wired for hooks, with the given allow list."""
        from espalier.cli import merge_hooks_into_settings
        (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
        path = tmp_path / ".claude" / "settings.json"
        path.write_text(json.dumps({"permissions": {"allow": list(allow)}}) + "\n", encoding="utf-8")
        merge_hooks_into_settings(path, repo_root=tmp_path)  # wires hooks, preserves allow
        return path

    def test_a_wired_file_missing_a_profile_rule_reports_it_and_stays_untouched(self, tmp_path):
        from espalier.cli import MERGE_ALREADY, merge_hooks_into_settings
        path = self._wired(tmp_path, ["Bash(ls:*)"])
        before = path.read_text(encoding="utf-8")
        result = merge_hooks_into_settings(path, repo_root=tmp_path)
        assert result.status == MERGE_ALREADY
        assert "Bash(python3 -m pytest *)" in result.missing_allows
        assert result.allow_count == 0
        assert path.read_text(encoding="utf-8") == before

    def test_add_allows_appends_the_missing_rules_and_keeps_the_operators_own(self, tmp_path):
        from espalier.cli import MERGE_WIRED, merge_hooks_into_settings
        path = self._wired(tmp_path, ["Bash(ls:*)"])
        result = merge_hooks_into_settings(path, repo_root=tmp_path, add_allows=True)
        assert result.status == MERGE_WIRED
        assert result.event_count == 0 and result.allow_count > 0
        assert result.missing_allows == (), "nothing left lacking after the append"
        data = json.loads(path.read_text(encoding="utf-8"))
        allow = data["permissions"]["allow"]
        assert allow[0] == "Bash(ls:*)"                      # the operator's rule, still first
        assert "Bash(python3 -m pytest *)" in allow
        assert len(allow) == len(set(allow))                 # no duplicates
        # The helper's wiring merge already wrote `.bak`; THIS call must back up too.
        assert (tmp_path / ".claude" / "settings.json.bak.1").exists()

    def test_add_allows_is_idempotent(self, tmp_path):
        from espalier.cli import MERGE_ALREADY, merge_hooks_into_settings
        path = self._wired(tmp_path, ["Bash(ls:*)"])
        merge_hooks_into_settings(path, repo_root=tmp_path, add_allows=True)
        before = path.read_text(encoding="utf-8")
        result = merge_hooks_into_settings(path, repo_root=tmp_path, add_allows=True)
        assert result.status == MERGE_ALREADY and not result.missing_allows
        assert path.read_text(encoding="utf-8") == before

    def test_a_malformed_permissions_block_is_named_never_appended(self, tmp_path):
        """The merge never rewrites a malformed shape; the gap is reported as
        unknowable, hooks still merge as before."""
        from espalier.cli import MERGE_WIRED, merge_hooks_into_settings
        (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
        path = tmp_path / ".claude" / "settings.json"
        path.write_text(json.dumps({"permissions": "nope"}) + "\n", encoding="utf-8")
        result = merge_hooks_into_settings(path, repo_root=tmp_path, add_allows=True)
        assert result.status == MERGE_WIRED and result.event_count > 0
        assert result.allow_count == 0 and result.missing_allows == ()
        assert "str" in result.allow_note
        assert json.loads(path.read_text(encoding="utf-8"))["permissions"] == "nope"

    def test_an_absent_permissions_block_gets_the_profile_rules_on_opt_in(self, tmp_path):
        from espalier.cli import merge_hooks_into_settings
        (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
        path = tmp_path / ".claude" / "settings.json"
        path.write_text("{}\n", encoding="utf-8")
        result = merge_hooks_into_settings(path, repo_root=tmp_path, add_allows=True)
        assert result.allow_count > 0
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "Bash(python3 -m pytest *)" in data["permissions"]["allow"]
        assert "deny" not in data["permissions"], "the opt-in adds allow rules only"

    def test_the_command_reports_the_gap_by_default_and_appends_on_the_flag(self, tmp_path):
        def run(*extra):
            return subprocess.run(
                [sys.executable, "-m", "espalier.cli", "merge-settings", str(tmp_path), *extra],
                capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT), encoding="utf-8",
            )
        path = self._wired(tmp_path, ["Bash(ls:*)"])
        first = run()
        assert first.returncode == 0, first.stderr
        text = first.stdout + first.stderr
        assert "Bash(python3 -m pytest *)" in text and "--add-allows" in text
        assert "Bash(python3 -m pytest *)" not in json.loads(path.read_text(encoding="utf-8"))["permissions"]["allow"]
        second = run("--add-allows")
        assert second.returncode == 0, second.stderr
        assert "appended" in second.stdout and "Bash(python3 -m pytest *)" in second.stdout
        assert "Bash(python3 -m pytest *)" in json.loads(path.read_text(encoding="utf-8"))["permissions"]["allow"]
        third = run("--add-allows")
        assert third.returncode == 0 and "Nothing to do" in third.stdout and "not in .claude/settings.json" not in third.stdout

    def test_a_rule_the_operator_denied_or_asked_is_neither_reported_nor_appended(self, tmp_path):
        """A deny or ask of a profile rule is a judgement, not friction: it is
        not a gap, and --add-allows never writes an allow beside it (failure-mode
        review, 2026-09-07: it did both)."""
        from espalier.cli import merge_hooks_into_settings
        (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
        path = tmp_path / ".claude" / "settings.json"
        path.write_text(json.dumps({"permissions": {
            "allow": ["Read", "Grep", "Glob"],
            "deny": ["Write", "Bash(black *)"],
            "ask": ["Bash(ruff *)"],
        }}) + "\n", encoding="utf-8")
        merge_hooks_into_settings(path, repo_root=tmp_path)  # wire hooks
        result = merge_hooks_into_settings(path, repo_root=tmp_path)
        assert not {"Write", "Bash(black *)", "Bash(ruff *)"} & set(result.missing_allows)
        assert "Bash(pytest *)" in result.missing_allows
        merge_hooks_into_settings(path, repo_root=tmp_path, add_allows=True)
        data = json.loads(path.read_text(encoding="utf-8"))["permissions"]
        assert "Write" not in data["allow"] and "Bash(black *)" not in data["allow"] and "Bash(ruff *)" not in data["allow"]
        assert data["deny"] == ["Write", "Bash(black *)"] and data["ask"] == ["Bash(ruff *)"]

    def test_an_existing_deny_list_is_byte_identical_after_the_append(self, tmp_path):
        from espalier.cli import merge_hooks_into_settings
        path = self._wired(tmp_path, ["Bash(ls:*)"])
        data = json.loads(path.read_text(encoding="utf-8"))
        data["permissions"]["deny"] = ["Bash(curl *)", "Read(./.env)"]
        path.write_text(json.dumps(data) + "\n", encoding="utf-8")
        merge_hooks_into_settings(path, repo_root=tmp_path, add_allows=True)
        after = json.loads(path.read_text(encoding="utf-8"))["permissions"]
        assert after["deny"] == ["Bash(curl *)", "Read(./.env)"]

    def test_the_read_only_twin_agrees_with_the_merge(self, tmp_path):
        """`settings_allow_gaps` and the merge compute the gap by different
        routes; pin their agreement so a refinement inside the settings
        builder cannot desynchronise doctor's report from what --add-allows
        appends (failure-mode review)."""
        from espalier.cli import merge_hooks_into_settings, settings_allow_gaps
        path = self._wired(tmp_path, ["Bash(ls:*)"])
        twin = settings_allow_gaps(path, profile="workflow", repo_root=tmp_path)
        result = merge_hooks_into_settings(path, repo_root=tmp_path, profile="workflow")
        assert twin is not None
        assert tuple(twin[0]) == result.missing_allows and twin[1] == result.allow_note

    def test_the_command_defaults_to_the_installed_profile_and_says_so_in_the_hint(self, tmp_path):
        """A `minimal` install compared against `workflow` was told it lacked
        the eleven rules minimal exists to withhold, and the printed remedy
        would have appended them (failure-mode review, MAJOR)."""
        from espalier.cli import installed_settings_profile, merge_hooks_into_settings
        path = self._wired(tmp_path, ["Read", "Grep", "Glob"])
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({"settings_profile": "minimal", "config": {"default_profile": None}}), encoding="utf-8",
        )
        assert installed_settings_profile(tmp_path) == "minimal"
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "merge-settings", str(tmp_path)],
            capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT), encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        assert "not in .claude/settings.json" not in result.stdout, result.stdout
        assert "Nothing to do" in result.stdout
        # The core, asked for workflow explicitly, still reports -- the default is what changed.
        assert merge_hooks_into_settings(path, repo_root=tmp_path, profile="workflow").missing_allows


class TestMergeBannerNamesDeadReporters:
    """DEF-619, driven by the failure-mode pass: `init` named a dead reporter,
    sent the operator to `merge-settings`, which topped up the missing event,
    said "Enforcement is now active." and left the orphaned reporter dead.
    Every armed-claim narrator carries the same line now."""

    def test_merge_names_the_reporter_it_could_not_repair(self, tmp_path):
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
        subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(tmp_path)],
            check=True, cwd=REPO_ROOT, capture_output=True,
        )
        settings = tmp_path / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["hooks"].pop("PostCompact")                      # absent: the merge adds it
        data["hooks"]["PostToolUse"] = [                      # orphaned: it will not
            e for e in data["hooks"]["PostToolUse"]
            if "reflect_trigger.py" not in json.dumps(e)
        ]
        settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "merge-settings", str(tmp_path)],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0, result
        assert "wired 1 Espalier hook event" in result.stdout, result.stdout
        assert "NOT wired: reflect_trigger.py is a reporter hook" in result.stdout, result.stdout
        assert "post_compact.py" not in result.stdout, result.stdout


class TestMergeSettingsRepair:
    """DEF-618: `merge-settings --repair` is the hand edit every surface used
    to prescribe, done by the tool that knows the canonical shape, on the
    operator's explicit request. The plain merge keeps its contract (the
    driven twins above still pin that it repairs nothing inside an event).
    Driven on real `espalier init` trees, one shape per test and all at once."""

    @staticmethod
    def _settings(target: Path) -> Path:
        return target / ".claude" / "settings.json"

    @classmethod
    def _load(cls, target: Path) -> dict:
        return json.loads(cls._settings(target).read_text(encoding="utf-8"))

    @classmethod
    def _save(cls, target: Path, data: dict) -> None:
        cls._settings(target).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _repair(target: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "espalier.cli", "merge-settings", str(target), "--repair"],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
        )

    @staticmethod
    def _unwired(target: Path) -> list[str]:
        from espalier.harness_config import unwired_governance_gates, unwired_reporter_hooks
        return sorted(unwired_governance_gates(target) + unwired_reporter_hooks(target))

    def test_inert_gate_is_repaired_and_the_plain_merge_still_is_not(self, tmp_path):
        target = _git_target(tmp_path)
        _init(target)
        data = self._load(target)
        data["hooks"]["Stop"][0]["hooks"][0]["command"] = "echo"
        self._save(target, data)
        assert self._unwired(target) == ["stop_gate.py"]
        _merge(target)
        assert self._unwired(target) == ["stop_gate.py"], "the plain merge must not rewrite an entry"
        result = self._repair(target)
        assert result.returncode == 0, result
        assert "stop_gate.py (inert): replaced the entry that ran no interpreter" in result.stdout, result.stdout
        assert self._unwired(target) == []
        # One write this run (the merge after it is MERGE_ALREADY): exactly `.bak`.
        assert (target / ".claude" / "settings.json.bak").exists()
        assert not (target / ".claude" / "settings.json.bak.1").exists()

    def test_orphaned_entry_is_added_under_the_existing_event(self, tmp_path):
        target = _git_target(tmp_path)
        _init(target)
        data = self._load(target)
        data["hooks"]["PreToolUse"] = [
            g for g in data["hooks"]["PreToolUse"] if "plan_guard.py" not in json.dumps(g)
        ]
        self._save(target, data)
        result = self._repair(target)
        assert "plan_guard.py (orphaned): added the entry under the existing 'PreToolUse' event" in result.stdout, result.stdout
        assert self._unwired(target) == []

    def test_miswired_entries_are_moved_and_widened_and_the_operators_hook_keeps_its_group(self, tmp_path):
        target = _git_target(tmp_path)
        _init(target)
        data = self._load(target)
        h = data["hooks"]
        h["PostToolUseFailure"].extend(h.pop("ConfigChange"))          # wrong event
        for g in h["PostToolUse"]:
            if "post_write_check.py" in json.dumps(g):                   # narrowed, shared group
                g["matcher"] = "Write"
                g["hooks"].append({"type": "command", "command": "node", "args": ["their_own.js"]})
        self._save(target, data)
        result = self._repair(target)
        assert result.returncode == 0, result
        assert "config_guard.py (miswired): rewired it: was wired under 'PostToolUseFailure' instead of 'ConfigChange'" in result.stdout, result.stdout
        assert "post_write_check.py (miswired): rewired it" in result.stdout, result.stdout
        after = self._load(target)["hooks"]
        assert json.dumps(after).count("config_guard.py") == 1
        assert "config_guard.py" not in json.dumps(after["PostToolUseFailure"])
        theirs = [g for g in after["PostToolUse"] if "their_own.js" in json.dumps(g)]
        assert theirs and theirs[0]["matcher"] == "Write", after["PostToolUse"]
        assert "post_write_check.py" not in json.dumps(theirs), "our entry was re-added in its own canonical group"
        assert self._unwired(target) == []

    def test_shell_form_entry_is_converted_to_exec_form(self, tmp_path):
        target = _git_target(tmp_path)
        _init(target)
        data = self._load(target)
        e = data["hooks"]["PostCompact"][0]["hooks"][0]
        e["command"] = e["command"] + " " + " ".join(e.pop("args"))
        self._save(target, data)
        result = self._repair(target)
        assert "post_compact.py (legacy_form): converted the shell-form entry to exec form" in result.stdout, result.stdout
        entry = self._load(target)["hooks"]["PostCompact"][0]["hooks"][0]
        assert isinstance(entry.get("args"), list) and entry["args"][0].endswith("post_compact.py")

    def test_every_shape_at_once_then_idempotent(self, tmp_path):
        target = _git_target(tmp_path)
        _init(target)
        data = self._load(target)
        h = data["hooks"]
        h["Stop"][0]["hooks"][0]["command"] = "echo"
        h["PreToolUse"] = [g for g in h["PreToolUse"] if "plan_guard.py" not in json.dumps(g)]
        for g in h["PreToolUse"]:
            if "write_guard.py" in json.dumps(g):
                g["matcher"] = "Write"
        h.pop("SubagentStart")
        data["permissions"]["allow"].append("Bash(theirs *)")
        data["theirOwnKey"] = {"deep": [1, 2]}
        self._save(target, data)
        before = self._load(target)
        result = self._repair(target)
        assert result.returncode == 0, result
        assert self._unwired(target) == [], result.stdout
        after = self._load(target)
        assert after["permissions"] == before["permissions"]
        assert after["theirOwnKey"] == before["theirOwnKey"]
        again = self._repair(target)
        assert "nothing to repair" in again.stdout, again.stdout

    def test_voided_file_is_refused_with_the_entry_named(self, tmp_path):
        target = _git_target(tmp_path)
        _init(target)
        data = self._load(target)
        data["hooks"]["Stop"][0]["hooks"][0]["type"] = "prompt"
        self._save(target, data)
        result = self._repair(target)
        # The repair refuses and says so; the plain merge still runs (it may
        # top up beside the voiding entry -- its own, pre-existing behaviour)
        # and the enforcement claim stays withheld over the voided block.
        assert "refused" in result.stderr and "hooks.Stop" in result.stderr, result.stderr
        assert "plain merge below still runs" in result.stderr, result.stderr
        after = self._load(target)["hooks"]["Stop"]
        assert any(h.get("type") == "prompt" for g in after for h in g["hooks"]), (
            "the repair rewrote inside a voided block"
        )
        assert "Enforcement is now active" not in result.stdout, result.stdout

    def test_the_narrators_name_the_command(self, tmp_path):
        """init's banner and doctor's next step both point at --repair for an
        inert gate; the hand edit stays as the fallback in the same sentence."""
        target = _git_target(tmp_path)
        _init(target)
        data = self._load(target)
        data["hooks"]["Stop"][0]["hooks"][0]["command"] = "echo"
        self._save(target, data)
        out = _init(target).stdout
        assert "merge-settings . --repair" in out and "stop_gate.py" in out, out
        doctor = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "doctor", str(target)],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        report = json.loads(doctor.stdout)
        assert any("merge-settings . --repair" in s and "stop_gate.py" in s for s in report["next_steps"]), report["next_steps"]

    def test_an_operator_entry_that_only_resembles_ours_survives(self, tmp_path):
        """The blocker both reviewers drove: `script in blob` deleted an
        operator's `my_plan_guard.py` and a `tests/test_write_guard.py` argument
        as copies of ours. Basename equality per token now; and an operator
        entry that carries the EXACT basename as data is removed but NAMED."""
        target = _git_target(tmp_path)
        _init(target)
        data = self._load(target)
        h = data["hooks"]
        h["Stop"][0]["hooks"][0]["command"] = "echo"                       # inert stop_gate
        h["PreToolUse"] = [g for g in h["PreToolUse"] if "plan_guard.py" not in json.dumps(g)]
        h["PreToolUse"].append({"matcher": "Edit", "hooks": [{
            "type": "command", "command": "python3",
            "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/my_plan_guard.py"]}]})
        h["PostToolUse"].append({"hooks": [{
            "type": "command", "command": "node", "args": ["ops/run.js", "tests/test_stop_gate.py"]}]})
        h["UserPromptSubmit"].append({"hooks": [{
            "type": "command", "command": "node",
            "args": ["ops/audit.js", "--watch", "tools/cc/hooks/stop_gate.py"], "timeout": 3}]})
        self._save(target, data)
        result = self._repair(target)
        assert result.returncode == 0, result
        after = json.dumps(self._load(target)["hooks"])
        assert "my_plan_guard.py" in after, "an operator hook resembling ours was deleted"
        assert "tests/test_stop_gate.py" in after, "an operator arg resembling ours was deleted"
        assert "ops/audit.js" not in after, "the exact-basename wrapper is ours to the oracle and is removed"
        assert "removed from 'UserPromptSubmit': `node ops/audit.js --watch tools/cc/hooks/stop_gate.py`" in result.stdout, result.stdout
        assert "dropped your timeout=3" in result.stdout, result.stdout
        assert "plan_guard.py (orphaned)" in result.stdout, result.stdout
        assert self._unwired(target) == []

    def test_dropped_keys_on_our_own_entry_are_named(self, tmp_path):
        target = _git_target(tmp_path)
        _init(target)
        data = self._load(target)
        e = data["hooks"]["Stop"][0]["hooks"][0]
        e["command"] = "echo"; e["timeout"] = 600; e["_note"] = "raised for our monorepo"
        self._save(target, data)
        result = self._repair(target)
        assert "dropped your _note='raised for our monorepo', timeout=600" in result.stdout, result.stdout

    def test_a_refused_repair_falls_through_to_the_plain_merge(self, tmp_path):
        """Driven by the failure-mode pass: with `hooks.Stop` null, `--repair`
        exited 1 over a voided block while the flag-less run wired the event.
        The repair's refusal is announced; the merge still runs."""
        target = _git_target(tmp_path)
        _init(target)
        data = self._load(target)
        data["hooks"]["Stop"] = None
        self._save(target, data)
        result = self._repair(target)
        assert result.returncode == 0, result
        assert "refused" in result.stderr and "plain merge below still runs" in result.stderr, result.stderr
        assert "wired 1 Espalier hook event" in result.stdout, result.stdout

    def test_refusal_reasons_use_the_shared_renderer(self, tmp_path):
        target = _git_target(tmp_path)
        _init(target)
        data = self._load(target)
        data["hooks"] = "oops"
        self._save(target, data)
        result = self._repair(target)
        assert "hooks-block: str" not in result.stderr, result.stderr
        assert "not an object keyed by event name" in result.stderr, result.stderr

    def test_the_wired_claim_is_repair_aware_and_names_both_backups(self, tmp_path):
        target = _git_target(tmp_path)
        _init(target)
        data = self._load(target)
        data["hooks"]["Stop"][0]["hooks"][0]["command"] = "echo"
        data["permissions"]["allow"] = ["Bash(ls:*)"]
        self._save(target, data)
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "merge-settings", str(target), "--repair", "--add-allows"],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0, result
        assert "Enforcement is now active." in result.stdout, result.stdout
        assert "was already active" not in result.stdout, result.stdout
        assert "two backups this run -- .claude/settings.json.bak is the file before --repair" in result.stdout, result.stdout

    def test_nothing_deployed_is_said_plainly(self, tmp_path):
        target = _git_target(tmp_path)
        (target / ".claude").mkdir()
        (target / ".claude" / "settings.json").write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        result = self._repair(target)
        assert "nothing deployed to repair" in result.stdout, result.stdout
        assert "every deployed espalier hook is executably wired" not in result.stdout, result.stdout

    def test_a_stray_copy_under_another_event_is_named_not_removed(self, tmp_path):
        target = _git_target(tmp_path)
        _init(target)
        data = self._load(target)
        data["hooks"]["SessionStart"].extend(json.loads(json.dumps(data["hooks"]["Stop"])))
        data["hooks"]["PreToolUse"] = [g for g in data["hooks"]["PreToolUse"] if "plan_guard.py" not in json.dumps(g)]
        self._save(target, data)
        result = self._repair(target)
        assert "left in place" in result.stderr and "stop_gate.py under 'SessionStart'" in result.stderr, result.stderr
        assert "stop_gate.py" in json.dumps(self._load(target)["hooks"]["SessionStart"])

    def test_report_branches_that_the_live_tree_cannot_reach(self, capsys):
        """`still_unwired` narrations are the DEF-620 defence; every profile
        ships every hook so the live tree never reaches them. Unit-drive both."""
        from espalier import cli

        cli._report_hook_repair(cli.RepairResult(cli.REPAIR_NOTHING, still_unwired=("stop_gate.py",)), "python3")
        err = capsys.readouterr().err
        assert "stop_gate.py" in err and "still not executably wired" in err, err
        cli._report_hook_repair(cli.RepairResult(
            cli.REPAIR_DONE, detail="settings.json.bak",
            changes=(("stop_gate.py", "inert", "replaced"),), still_unwired=("plan_guard.py",),
        ), "python3")
        captured = capsys.readouterr()
        assert "STILL not executably wired" in captured.err and "plan_guard.py" in captured.err, captured.err
        assert ".claude/settings.json.bak" in captured.err, captured.err

    def test_a_legacy_gate_is_offered_the_repair_by_both_narrators(self, tmp_path):
        target = _git_target(tmp_path)
        _init(target)
        data = self._load(target)
        e = data["hooks"]["ConfigChange"][0]["hooks"][0]
        e["command"] = e["command"] + " " + " ".join(e.pop("args"))
        data["hooks"]["Stop"][0]["hooks"][0]["command"] = "echo"   # so the claim narrates
        self._save(target, data)
        out = _init(target).stdout
        assert "config_guard.py" in out and "converts it to exec form" in out, out
        doctor = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "doctor", str(target)],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        steps = json.loads(doctor.stdout)["next_steps"]
        assert any("config_guard.py" in s and "--repair" in s for s in steps), steps


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permission bits and a non-root user",
)
class TestALockedParentIsUnreadableNotAbsent:
    """DEF-763: `merge-settings` on a `.claude` that denies traversal said
    "no settings.json found, run init" on CPython 3.14 and raised
    `PermissionError` out of `Path.exists()` on 3.10-3.13. The merge, its
    file-level predicate and the interpreter rewire now classify the stat's
    errno and answer `unreadable` -- with the OS's own words -- everywhere,
    for a locked parent and for a mode-000 file alike.
    """

    @staticmethod
    def _locked_init_tree(tmp_path: Path) -> tuple[Path, Path]:
        target = _git_target(tmp_path)
        _init(target)
        return target, target / ".claude"

    def test_the_merge_answers_unreadable_with_the_os_detail(self, tmp_path):
        from espalier import cli

        target, claude_dir = self._locked_init_tree(tmp_path)
        with locked(claude_dir):
            result = cli.merge_hooks_into_settings(
                claude_dir / "settings.json", profile="workflow", repo_root=target,
            )
        assert result.status == cli.MERGE_UNREADABLE, result
        assert "Permission denied" in result.detail and "settings.json" in result.detail, result

    def test_the_predicate_agrees_and_its_sentence_names_the_permission(self, tmp_path):
        from espalier import cli

        target, claude_dir = self._locked_init_tree(tmp_path)
        with locked(claude_dir):
            predicted = cli.merge_refusal_for_file(claude_dir / "settings.json", target)
        assert predicted.startswith(cli.MERGE_REFUSED_UNREADABLE + ": "), predicted
        sentence = cli.merge_refusal_step(predicted, "python3")
        assert "could not be read" in sentence and "permissions" in sentence, sentence
        assert "no file" not in sentence and "init" not in sentence, sentence

    def test_the_rewire_answers_unreadable_and_writes_nothing(self, tmp_path):
        from espalier import cli

        target, claude_dir = self._locked_init_tree(tmp_path)
        before = sorted(p.name for p in claude_dir.iterdir())
        with locked(claude_dir):
            result = cli.rewire_interpreter_in_settings(claude_dir / "settings.json")
        assert result.status == cli.REWIRE_UNREADABLE, result
        assert "Permission denied" in result.detail, result
        assert sorted(p.name for p in claude_dir.iterdir()) == before  # no .bak, no rewrite

    def test_a_settings_file_with_no_read_bit_is_unreadable_not_unparseable(self, tmp_path):
        """The FILE, not its parent: "could not parse" was a lie for bytes
        never read. The merge, the predicate and the rewire split the read's
        OSError from the decode the same way."""
        from espalier import cli

        target, claude_dir = self._locked_init_tree(tmp_path)
        settings = claude_dir / "settings.json"
        with locked(settings):
            merged = cli.merge_hooks_into_settings(settings, profile="workflow", repo_root=target)
            predicted = cli.merge_refusal_for_file(settings, target)
            rewired = cli.rewire_interpreter_in_settings(settings)
        assert merged.status == cli.MERGE_UNREADABLE and "Permission denied" in merged.detail, merged
        assert predicted.startswith(cli.MERGE_REFUSED_UNREADABLE + ": "), predicted
        assert rewired.status == cli.REWIRE_UNREADABLE, rewired

    def test_an_absent_file_is_still_absent_on_every_side(self, tmp_path):
        """The errno split: ENOENT and ENOTDIR stay `no_file` / `absent`."""
        from espalier import cli

        target = _git_target(tmp_path)
        missing = target / ".claude" / "settings.json"
        assert cli.merge_hooks_into_settings(missing, repo_root=target).status == cli.MERGE_NO_FILE
        assert cli.merge_refusal_for_file(missing, target) == cli.MERGE_REFUSED_ABSENT
        assert cli.rewire_interpreter_in_settings(missing).status == cli.REWIRE_NO_FILE
        (target / ".claude").write_text("not a directory\n", encoding="utf-8")
        assert cli.merge_hooks_into_settings(missing, repo_root=target).status == cli.MERGE_NO_FILE
        assert cli.merge_refusal_for_file(missing, target) == cli.MERGE_REFUSED_ABSENT
        assert cli.rewire_interpreter_in_settings(missing).status == cli.REWIRE_NO_FILE


class TestBackupLadderAcrossUninstallCycles:
    """DEF-809, the walk's own sequence (walk 3, leg 5-F, 2026-09-14): an
    adopter with a pre-existing ``settings.json`` wires the harness, uninstalls
    it, and wires again. Each wire backs the file up first; each uninstall
    unwires it back to the bytes the previous wire backed up. Before the fix
    three cycles left ``.bak``, ``.bak.1`` and ``.bak.2`` with the last two
    byte-identical; now the ladder holds one rung per distinct content."""

    @staticmethod
    def _run(verb: str, target: Path, *extra: str) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", verb, str(target), *extra],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0, (verb, result.stdout, result.stderr)
        return result

    def test_three_cycles_leave_one_rung_per_distinct_content(self, tmp_path):
        target = _git_target(tmp_path)
        (target / ".claude").mkdir()
        settings = target / ".claude" / "settings.json"
        settings.write_text('{"permissions": {"allow": ["Bash(ls *)"]}}\n', encoding="utf-8")
        original = settings.read_bytes()

        for _ in range(3):
            self._run("init", target, "--wire-hooks")
            self._run("clean-generated", target, "--execute")

        rungs = sorted(
            q.name for q in (target / ".claude").iterdir() if ".bak" in q.name
        )
        assert rungs == ["settings.json.bak", "settings.json.bak.1"], rungs
        assert (target / ".claude" / "settings.json.bak").read_bytes() == original
        # The second rung is the unwired shape the first uninstall left, which
        # every later wire found identical and reused.
        unwired = json.loads(
            (target / ".claude" / "settings.json.bak.1").read_text(encoding="utf-8")
        )
        assert "hooks" not in unwired or not unwired["hooks"]
        assert unwired["permissions"]["allow"] == ["Bash(ls *)"]
