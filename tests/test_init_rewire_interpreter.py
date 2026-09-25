"""Tests for `espalier init --rewire-interpreter` (TP-448 Class 3 / DEF-620).

`doctor` told an adopter to "re-run `init` to rewire the hook commands with an
interpreter that resolves on this host". `init` does not overwrite an existing
`.claude/settings.json` — user sovereignty — so the step was a no-op the adopter
could follow forever: measured before and after, `group_unwired_gates_by_shape`
returned the identical `{'legacy_form': [...]}` both times.

This flag is the remedy, and it writes a file the operator owns. The contract it
must keep, and that these tests exist to pin:

1. **Only argv[0] of a hook command changes.** Every other key, every `args`
   entry, every permission, the operator's own non-Python hooks — untouched.
2. **Only interpreters that FAIL the floor are touched**, so it is idempotent
   and creates no `.bak` churn.
3. **A malformed file is refused, never clobbered.**
4. **It refuses to rewire to an interpreter that fails the same floor** — that
   would report success and fix nothing, which is DEF-620's own shape.
"""
from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

from espalier import cli

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="sh interpreter stubs are POSIX"
)


def _stub(tmp_path: Path, name: str, says: str) -> str:
    """An executable that answers `--version` with `says`."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    stub = d / name
    stub.write_text(f"#!/bin/sh\necho '{says}'\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return str(stub)


def _settings(tmp_path: Path, interpreter: str) -> Path:
    """A realistic adopter settings.json: exec form, legacy shell form,
    statusLine, a non-Python hook of their own, and keys we must not touch."""
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "$schema": "https://json.schemastore.org/claude-code-settings.json",
        "permissions": {"allow": ["Bash(pytest *)"], "deny": ["Read(.env)"]},
        "hooks": {
            "PreToolUse": [{"matcher": "*", "hooks": [
                {"type": "command", "command": interpreter,
                 "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"]},
            ]}],
            "SessionStart": [{"matcher": "*", "hooks": [
                {"type": "command",
                 "command": f"{interpreter} tools/cc/hooks/session_start.py"},
                {"type": "command", "command": "node", "args": ["their_own.js"]},
            ]}],
        },
        "statusLine": {"type": "command",
                       "command": f"{interpreter} tools/cc/statusline.py --short"},
        "theirOwnKey": {"nested": [1, 2, {"deep": True}]},
    }, indent=2) + "\n", encoding="utf-8")
    return path


def _leaves(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, f"{prefix}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _leaves(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


class TestRewireChangesOnlyTheInterpreter:
    def test_only_command_leaves_change(self, tmp_path):
        """The whole promise of the flag, checked leaf by leaf rather than by
        reading the diff — including the operator's own `node` hook, their
        `${CLAUDE_PROJECT_DIR}` arg, and an arbitrary key we know nothing about.
        """
        old = _stub(tmp_path, "python3", "Python 3.9.6")
        path = _settings(tmp_path, old)
        before = json.loads(path.read_text(encoding="utf-8"))

        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_DONE, result

        after = json.loads(path.read_text(encoding="utf-8"))
        b, a = dict(_leaves(before)), dict(_leaves(after))
        assert set(b) == set(a), f"key set changed: {set(b) ^ set(a)}"
        changed = {k for k in b if b[k] != a[k]}
        assert changed, "nothing changed at all"
        assert all(k.endswith(".command") for k in changed), (
            f"a non-command leaf was modified: "
            f"{[k for k in changed if not k.endswith('.command')]}"
        )
        # The operator's own non-Python hook is not ours to rewrite.
        assert a[".hooks.SessionStart[0].hooks[1].command"] == "node"
        assert a[".theirOwnKey.nested[2].deep"] is True
        assert list(before) == list(after), "top-level key order changed"

    def test_all_three_command_shapes_are_covered(self, tmp_path):
        """Exec form, legacy shell form, and statusLine — the last lives
        OUTSIDE `hooks` and is the 13th interpreter site."""
        old = _stub(tmp_path, "python3", "Python 3.9.6")
        path = _settings(tmp_path, old)
        result = cli.rewire_interpreter_in_settings(path)
        where = {w for w, _, _ in result.changes}
        assert "statusLine" in where, f"statusLine was missed: {where}"
        assert any(w.startswith("hooks.PreToolUse") for w in where), where
        assert any(w.startswith("hooks.SessionStart") for w in where), where
        after = json.loads(path.read_text(encoding="utf-8"))
        # The shell form keeps its script argument; only argv[0] moved.
        assert after["hooks"]["SessionStart"][0]["hooks"][0]["command"].endswith(
            " tools/cc/hooks/session_start.py"
        )
        assert after["statusLine"]["command"].endswith(
            " tools/cc/statusline.py --short"
        )

    def test_the_rendered_statusline_fallback_survives_a_rewire(self, tmp_path):
        """DEF-508: on a POSIX host `init` renders the statusLine as
        `<interp> "<script>" || echo '<fallback>'`. The rewire swaps argv[0]
        and leaves the clause byte-for-byte -- its contract is "only argv[0]",
        because the rest of a statusLine may be the operator's (the `--short`
        in this fixture). That is also why the fallback text names no
        interpreter. A clause that is WRONG for the host (a POSIX render
        carried onto Windows by a tracked settings.json) is doctor's to flag,
        never the rewire's to strip: `espalier/doctor.py::
        _statusline_fallback_notes`."""
        from espalier._venv import interpreter_token

        old = _stub(tmp_path, "python3", "Python 3.9.6")
        path = _settings(tmp_path, old)
        data = json.loads(path.read_text(encoding="utf-8"))
        before = cli._statusline_command(old, posix=True)
        assert " || echo '" in before, before
        data["statusLine"]["command"] = before
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_DONE, result
        after = json.loads(path.read_text(encoding="utf-8"))["statusLine"]["command"]
        assert interpreter_token(after) != old, after
        assert after.split(" || ", 1)[1] == before.split(" || ", 1)[1], after
        assert after == cli._swap_interpreter_token(before, interpreter_token(after))

    def test_the_windows_shim_render_rewires_its_interpreter_argument(self, tmp_path):
        """DEF-729: on Windows the statusLine head is the deployed shim and
        the interpreter is its first argument. The rewire swaps THAT word and
        leaves the head byte-for-byte; doctor reads the same helper, so the
        two cannot disagree about which word is the interpreter."""
        old = _stub(tmp_path, "python3", "Python 3.9.6")
        path = _settings(tmp_path, old)
        data = json.loads(path.read_text(encoding="utf-8"))
        shim_render = cli._statusline_command(old, posix=False)
        assert shim_render.startswith('"${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" '), shim_render
        data["statusLine"]["command"] = shim_render
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_DONE, result
        assert any(w == "statusLine" for w, _, _ in result.changes), result.changes
        after = json.loads(path.read_text(encoding="utf-8"))["statusLine"]["command"]
        assert after.startswith('"${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" '), after
        assert not after.endswith(" " + old), after
        assert old not in after, after

    @pytest.mark.parametrize("pad", ["  ", " \t", ""], ids=["trailing-spaces", "trailing-tab", "none"])
    def test_a_hand_edit_with_trailing_whitespace_still_rewires_the_shim_argument(self, tmp_path, pad):
        """Both reviewers' finding (2026-09-13): the swap's start offset was
        measured on a stripped copy, so trailing whitespace from a hand edit
        put it past the interpreter word and the site was reported as neither
        changed nor declined. The offset is measured on the string itself."""
        old = _stub(tmp_path, "python3", "Python 3.9.6")
        path = _settings(tmp_path, old)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["statusLine"]["command"] = " " + cli._statusline_command(old, posix=False) + pad
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_DONE, result
        after = json.loads(path.read_text(encoding="utf-8"))["statusLine"]["command"]
        assert old not in after, after
        assert after.endswith(pad), "the whitespace the operator left is kept as found"
        assert '/tools/cc/statusline.cmd" ' in after, after

    def test_a_backup_is_written_before_the_change(self, tmp_path):
        old = _stub(tmp_path, "python3", "Python 3.9.6")
        path = _settings(tmp_path, old)
        original = path.read_bytes()
        cli.rewire_interpreter_in_settings(path)
        backup = path.with_name(path.name + ".bak")
        assert backup.exists(), "no .bak was written"
        assert backup.read_bytes() == original, (
            "the .bak is not the pre-change file"
        )


class TestRewireRefusesRatherThanPretend:
    def test_idempotent_and_no_bak_churn(self, tmp_path):
        """A conforming interpreter is left alone. Without this the command
        would rewrite (and re-.bak) on every run, and `.bak` is gitignored —
        churning it can destroy the only pristine copy."""
        good = _stub(tmp_path, "python3", "Python 3.14.0")
        path = _settings(tmp_path, good)
        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_NOTHING, result
        assert not path.with_name(path.name + ".bak").exists(), (
            "a no-op run still wrote a backup"
        )

    def test_refuses_to_rewire_to_a_below_floor_target(self, tmp_path):
        """DEF-620's own shape, one level in: swapping 3.9 for 3.9 would print
        success and repair nothing, and the adopter would re-run doctor to find
        the identical failure."""
        old = _stub(tmp_path, "python3", "Python 3.9.6")
        path = _settings(tmp_path, old)
        before = path.read_bytes()
        result = cli.rewire_interpreter_in_settings(path, new_interpreter=old)
        assert result.status == cli.REWIRE_NO_TARGET, result
        assert path.read_bytes() == before, "the file was modified on a refusal"

    def test_malformed_json_is_refused_not_clobbered(self, tmp_path):
        path = tmp_path / ".claude" / "settings.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"hooks": {broken', encoding="utf-8")
        before = path.read_bytes()
        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_PARSE_ERROR, result
        assert path.read_bytes() == before, "a malformed file was overwritten"

    def test_non_object_top_level_is_refused(self, tmp_path):
        path = tmp_path / ".claude" / "settings.json"
        path.parent.mkdir(parents=True)
        path.write_text('["not", "an", "object"]', encoding="utf-8")
        before = path.read_bytes()
        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_NOT_OBJECT, result
        assert path.read_bytes() == before

    def test_missing_file_is_reported_not_created(self, tmp_path):
        path = tmp_path / ".claude" / "settings.json"
        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_NO_FILE, result
        assert not path.exists(), "a settings.json was conjured from nothing"


class TestEveryStatusSaysWhatToDoNext:
    """A repair verb that reports only "done" or nothing is how DEF-620's no-op
    survived: the operator re-ran it, saw success, re-ran doctor, saw the same
    failure. Every outcome must name a next action."""

    @pytest.mark.parametrize("case", ["done", "nothing", "no_file", "parse_error"])
    def test_status_message_is_actionable(self, tmp_path, capsys, case):
        if case == "done":
            path = _settings(tmp_path, _stub(tmp_path, "python3", "Python 3.9.6"))
        elif case == "nothing":
            path = _settings(tmp_path, _stub(tmp_path, "python3", "Python 3.14.0"))
        elif case == "no_file":
            path = tmp_path / ".claude" / "settings.json"
        else:
            path = tmp_path / ".claude" / "settings.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"broken', encoding="utf-8")
        cli._report_interpreter_rewire(path)
        err = capsys.readouterr().err
        assert err.strip(), f"{case} printed nothing at all"
        assert "rewire-interpreter" in err, err
        if case in ("no_file", "parse_error"):
            assert "NOT modified" in err or "init ." in err, (
                f"a refusal must say what to do next: {err}"
            )


def test_doctor_prescribes_the_flag_not_the_no_op():
    """DEF-620 itself: doctor's next_step must not send the adopter to a plain
    `init .`, which cannot rewire an existing settings.json."""
    src = (Path(__file__).resolve().parent.parent / "espalier" / "doctor.py").read_text(
        encoding="utf-8"
    )
    marker = "to rewire the "
    assert marker in src, "doctor's rewire next_step is gone; re-point this test"
    idx = src.index(marker)
    window = src[max(0, idx - 400): idx + 400]
    assert "--rewire-interpreter" in window, (
        "doctor still prescribes a bare `init .` to rewire hook commands, "
        "which is the DEF-620 no-op"
    )


class TestShapesTheRewireMustDecline:
    """Every case here was found by driving, not by review, and each one shipped
    past the first version of this file's tests (adversarial pass, 2026-09-03).
    """

    @pytest.mark.skipif(sys.platform == "win32", reason="sh interpreter stubs are POSIX")
    def test_py_launcher_is_declined_not_rewritten(self, tmp_path):
        """`py -3 <hook>` -> `python3 -3 <hook>` BRICKED the session.

        `-3` is a Windows Python Launcher flag, not an interpreter flag, and the
        swap only replaces argv[0]. `python3 -3` exits non-zero with `Unknown
        option: -3`; from a PreToolUse hook that is a BLOCK, so every tool call
        in the session was denied — by the repair command. The harness supplies
        this input itself: `doctor` tells Windows operators to try `py -3`.
        """
        path = tmp_path / ".claude" / "settings.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command", "command": "py -3 tools/cc/hooks/write_guard.py"},
        ]}]}}), encoding="utf-8")
        before = path.read_bytes()
        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_NOTHING, result
        assert path.read_bytes() == before, "the py-launcher form was rewritten"
        assert any("py -3" in cmd for _, cmd in result.declined), (
            f"a declined site must be REPORTED, not silently skipped: {result.declined}"
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="sh interpreter stubs are POSIX")
    def test_unterminated_quote_is_declined(self, tmp_path):
        """`interpreter_token` returns the whole rest of the line on an unclosed
        quote, so the swap DELETED every argument while the report said "your
        args were preserved". An unclosed quote around a Windows path with
        spaces is the likeliest hand-edit typo on this exact surface."""
        path = tmp_path / ".claude" / "settings.json"
        path.parent.mkdir(parents=True)
        broken = '"python3 -u -m espalier.hookrunner write_guard'
        path.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command", "command": broken},
        ]}]}}), encoding="utf-8")
        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_NOTHING, result
        after = json.loads(path.read_text(encoding="utf-8"))
        assert after["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == broken, (
            "the arguments were destroyed"
        )
        assert result.declined, "the declined site was not reported"

    def test_duplicate_keys_are_refused_not_collapsed(self, tmp_path):
        """`json.loads` keeps the LAST duplicate and re-serialising persists the
        loss — driven, an operator's own `node` hook block silently vanished."""
        path = tmp_path / ".claude" / "settings.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            '{"hooks": {"PreToolUse": [{"hooks": [{"type": "command", '
            '"command": "node mine.js"}]}]}, '
            '"hooks": {"PreToolUse": [{"hooks": [{"type": "command", '
            '"command": "python x.py"}]}]}}',
            encoding="utf-8",
        )
        before = path.read_bytes()
        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_DUPLICATE_KEYS, result
        assert path.read_bytes() == before, (
            "a file with duplicate keys was rewritten, dropping a block"
        )

    def test_doctor_does_not_prescribe_the_flag_for_a_declined_shape(self, tmp_path):
        """DEF-620 once more: `doctor` must not send the operator to
        `--rewire-interpreter` for a site that verb refuses. Both read the same
        predicate so they cannot drift."""
        from espalier import doctor as doctor_module

        path = tmp_path / ".claude" / "settings.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command", "command": "py -3 tools/cc/hooks/write_guard.py"},
        ]}]}}), encoding="utf-8")
        issues = " ".join(doctor_module._check_python_resolver(tmp_path, path))
        assert "will NOT fix this one" in issues, (
            f"doctor prescribed a remedy the rewire declines: {issues}"
        )


class TestRewireReportDoesNotContradictItself:
    def test_a_no_op_run_is_not_also_reported_as_refused(self, tmp_path, capsys):
        """Driven by the failure-mode pass: the report's second chain started
        at `if result.declined`, so a DONE or NOTHING run with nothing declined
        fell through to "refused ... Fix the JSON by hand" right under its own
        success line."""
        path = _settings(tmp_path, sys.executable)
        status = cli._report_interpreter_rewire(path)
        err = capsys.readouterr().err
        assert status == cli.REWIRE_NOTHING, (status, err)
        assert "nothing to rewire" in err, err
        assert "refused" not in err, err

