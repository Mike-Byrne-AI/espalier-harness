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
import string
import sys
from pathlib import Path

import pytest

from espalier import _venv, cli
from espalier._text import quoted_if_spaced
from tests._cut_start import skip_if_cut
from tests._stubs import write_stub

# The sh stubs below are POSIX-only, so every class built on them skips on
# Windows. TestTheLauncherRewiresWithItsFlag is built on the cross-platform
# hosts of tests/_interpreter_hosts.py and runs everywhere -- on Windows, where
# the launcher lives, most of all.
_POSIX_STUBS = pytest.mark.skipif(
    sys.platform == "win32", reason="sh interpreter stubs are POSIX"
)


def _stub(tmp_path: Path, name: str, says: str) -> str:
    """An executable that answers `--version` with `says`."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    return str(write_stub(d / name, f"#!/bin/sh\necho '{says}'\n"))


def _settings(tmp_path: Path, interpreter: str) -> Path:
    """A realistic adopter settings.json: exec form, legacy shell form,
    statusLine, a non-Python hook of their own, and keys we must not touch.
    The shell-form strings carry the interpreter as `init` renders one,
    quoted when its path holds a space (DEF-5082); the exec-form command is
    argv[0] whole and takes no quotes (DEF-968)."""
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
                 "command": f"{quoted_if_spaced(interpreter)} tools/cc/hooks/session_start.py"},
                {"type": "command", "command": "node", "args": ["their_own.js"]},
            ]}],
        },
        "statusLine": {"type": "command",
                       "command": f"{quoted_if_spaced(interpreter)} tools/cc/statusline.py --short"},
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


@_POSIX_STUBS
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

    @pytest.mark.parametrize("lead", ["", "& ", ". "], ids=["bare", "called", "dotted"])
    def test_the_windows_shim_render_rewires_its_interpreter_argument(self, tmp_path, lead):
        """DEF-729: on Windows the statusLine head is the deployed shim and
        the interpreter is its first argument. The rewire swaps THAT word and
        leaves the head byte-for-byte -- the operator before it included: the
        dot `init` renders for both shells (DEF-3017), and PowerShell's call
        operator, which an install rendered since DEF-929 can carry; doctor
        reads the same helper, so the two cannot disagree about which word is
        the interpreter."""
        old = _stub(tmp_path, "python3", "Python 3.9.6")
        path = _settings(tmp_path, old)
        data = json.loads(path.read_text(encoding="utf-8"))
        head = lead + '"${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" '
        shim_render = head + quoted_if_spaced(old)
        if lead == ". ":
            # the render takes the interpreter spelling as given: `init` hands
            # it a PATH name or the launcher, this fixture a quoted spaced
            # path, the spelling a hand edit under Program Files writes
            assert shim_render == cli._statusline_command(quoted_if_spaced(old), posix=False), "the render init writes"
        data["statusLine"]["command"] = shim_render
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_DONE, result
        assert any(w == "statusLine" for w, _, _ in result.changes), result.changes
        after = json.loads(path.read_text(encoding="utf-8"))["statusLine"]["command"]
        assert after.startswith(head), after
        assert not after.endswith(" " + old), after
        assert old not in after, after

    @pytest.mark.parametrize("lead", ["", "& ", ". "], ids=["bare", "called", "dotted"])
    @pytest.mark.parametrize("pad", ["  ", " \t", ""], ids=["trailing-spaces", "trailing-tab", "none"])
    def test_a_hand_edit_with_trailing_whitespace_still_rewires_the_shim_argument(self, tmp_path, pad, lead):
        """Both reviewers' finding (2026-09-13): the swap's start offset was
        measured on a stripped copy, so trailing whitespace from a hand edit
        put it past the interpreter word and the site was reported as neither
        changed nor declined. The offset is measured on the string itself."""
        old = _stub(tmp_path, "python3", "Python 3.9.6")
        path = _settings(tmp_path, old)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["statusLine"]["command"] = (" " + lead + '"${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" '
                                         + quoted_if_spaced(old) + pad)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_DONE, result
        after = json.loads(path.read_text(encoding="utf-8"))["statusLine"]["command"]
        assert old not in after, after
        assert after.endswith(pad), "the whitespace the operator left is kept as found"
        assert '/tools/cc/statusline.cmd" ' in after, after

    def test_a_quoted_spaced_shell_form_interpreter_is_rewired(self, tmp_path):
        """A wired interpreter whose path holds a space, quoted as every shell
        this repo targets reads one word (`_detect_python_command` writes a
        PATH name or the launcher, so the spelling is a hand edit's, or a
        tool's absolute write): the shell-form and statusLine sites carry it
        quoted, and the rewire swaps them as it swaps the exec-form site
        beside them, the target bringing its own quoting. DEF-4094: the predicate read
        the quote's content, whitespace and all, as the unterminated-quote
        shape, declined both sites and reported the exec-form one rewired,
        so a below-floor interpreter stayed wired at two of three sites. On
        every host: the space is this test's."""
        spaced = tmp_path / "with space"
        spaced.mkdir()
        old = _stub(spaced, "python3", "Python 3.9.6")
        path = _settings(spaced, old)
        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_DONE, result
        where = {w for w, _, _ in result.changes}
        assert "statusLine" in where and any(w.startswith("hooks.SessionStart") for w in where), (
            where, result.declined)
        assert not result.declined, result.declined
        after = json.loads(path.read_text(encoding="utf-8"))
        shell = after["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        status = after["statusLine"]["command"]
        assert old not in shell and old not in status, (shell, status)
        # The target brings its own quoting (a bare name bare: PowerShell, which
        # runs a shell-form hook where Git Bash is absent, refuses `"python3" x.py`);
        # the arguments are byte for byte, and the three sites run one interpreter.
        exec_head = after["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        assert shell.endswith(" tools/cc/hooks/session_start.py"), shell
        assert status.endswith(" tools/cc/statusline.py --short"), status
        assert _venv.interpreter_token(shell) == _venv.interpreter_token(status) == exec_head, (
            shell, status, exec_head)

    def test_a_backup_is_written_before_the_change(self, tmp_path):
        old = _stub(tmp_path, "python3", "Python 3.9.6")
        path = _settings(tmp_path, old)
        original = path.read_bytes()
        cli.rewire_interpreter_in_settings(path)
        backup = path.parent.parent / ".espalier" / "settings-backups" / "settings.json.0.json"
        assert backup.exists(), "no backup was written on the ladder"
        assert backup.read_bytes() == original, (
            "the backup is not the pre-change file"
        )


@_POSIX_STUBS
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


@_POSIX_STUBS
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


@_POSIX_STUBS
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


@_POSIX_STUBS
class TestShapesTheRewireMustDecline:
    """Every case here was found by driving, not by review, and each one shipped
    past the first version of this file's tests (adversarial pass, 2026-09-03).
    """

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
            {"type": "command", "command": '"python3 -u -m espalier.hookrunner write_guard'},
        ]}]}}), encoding="utf-8")
        issues = " ".join(doctor_module._check_python_resolver(tmp_path, path))
        assert "will NOT fix this one" in issues, (
            f"doctor prescribed a remedy the rewire declines: {issues}"
        )


class TestAQuotedHeadIsOneWordToItsShell:
    """DEF-4094: a shell-form head in a terminated quote is one word to the
    shell, as an exec-form ``command`` is to its spawn, so the whitespace
    inside it is the path's own (``"C:\\Program Files\\Python39\\python.exe"
    x.py``: the shape the swap's docstring kept both quotes for while the
    predicate declined it). The refusal the 2026-09-03 adversarial pass drove
    stays for the unterminated quote, whose token is the rest of the line: the
    two read alike as a token, and only a reader of the command string tells
    them apart, so each row here feeds both (a pin fed only conforming inputs
    certifies nothing). No stub, every host; the doctor rows patch the remedy
    spelling so no interpreter is probed for it."""

    @pytest.mark.parametrize("token,kwargs,rewirable", [
        pytest.param("/x y/python3", {"quoted": True}, True, id="terminated-quote-spaced-dir"),
        pytest.param("/x y/python3 x.py", {}, False, id="unterminated-quote-rest-of-line"),
        pytest.param("/x y/python3", {}, False, id="whitespace-with-no-quote-read"),
        pytest.param("/x y/python3 -u", {"quoted": True}, False, id="terminated-quote-space-in-the-name"),
        pytest.param("python3", {}, True, id="bare"),
        pytest.param("/x y/python3", {"exec_form": True}, True, id="exec-form-spaced-dir"),
        pytest.param("/x y/python3", {"quoted": True, "cut": True}, False, id="cut-is-read-first"),
        pytest.param("/x y/python_hook.py", {"quoted": True}, False, id="shebang-script-stays-declined"),
    ])
    def test_the_predicate_reads_a_terminated_quote_as_the_paths_own_space(self, token, kwargs, rewirable):
        assert cli._is_rewirable_interpreter(token, **kwargs) is rewirable

    @pytest.mark.parametrize("command,quoted", [
        pytest.param('"/x y/python3" x.py', True, id="double-terminated"),
        pytest.param("'/x y/python3' x.py", True, id="single-terminated"),
        pytest.param('"/x y/python3 x.py', False, id="double-unterminated"),
        pytest.param("'/x y/python3 x.py", False, id="single-unterminated"),
        pytest.param("/x y/python3 x.py", False, id="bare-spaced-the-shell-cuts"),
        pytest.param("python3 x.py", False, id="bare"),
        pytest.param('  "/x y/python3" x.py  ', True, id="padded"),
        pytest.param('"/x y/python3"', True, id="terminated-nothing-after"),
        pytest.param('"/x y/python3"x.py', False, id="closing-quote-glued-to-the-next-word"),
        pytest.param("", False, id="empty"),
        pytest.param("   ", False, id="blank"),
    ])
    def test_the_venv_reader_tells_a_terminated_quote_from_an_unterminated_one(self, command, quoted):
        assert _venv.head_is_quoted(command) is quoted
        if quoted:
            # The token the terminated quote returns is its content, whitespace and all.
            body = command.strip()
            assert _venv.interpreter_token(command) == body[1:body.find(body[0], 1)]

    @pytest.mark.parametrize("command,quoted", [
        pytest.param('. "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" "/x y/python3"', True, id="dotted-shim-quoted"),
        pytest.param('& "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" "C:/Program Files/py.exe" -3', True,
                     id="called-shim-quoted-launcher"),
        pytest.param('"${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" python3', False, id="bare-shim-bare-interpreter"),
        pytest.param('. "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" "/x y/python3', False, id="dotted-shim-unterminated"),
        pytest.param('"/x y/python3" tools/cc/statusline.py --short', True, id="posix-quoted"),
        pytest.param("python3 tools/cc/statusline.py --short", False, id="posix-bare"),
    ])
    def test_the_site_reader_looks_past_the_windows_shim(self, command, quoted):
        assert _venv.interpreter_site_quoted(command) is quoted

    @pytest.mark.parametrize("command,target,expected", [
        pytest.param('"/x y/python3" x.py', '"/a b/python3"', '"/a b/python3" x.py', id="quoted-old-quoted-spaced-target"),
        pytest.param('"/x y/python3" x.py', "/a b/python3", '"/a b/python3" x.py', id="quoted-old-bare-spaced-target"),
        pytest.param('"/x y/python3" x.py', "python3", "python3 x.py", id="quoted-old-bare-target-drops-the-quotes"),
        pytest.param('"/x y/python3" x.py', "py -3", "py -3 x.py", id="quoted-old-launcher-target-drops-the-quotes"),
        pytest.param("'/x y/python3' x.py", '"/a b/python3"', '"/a b/python3" x.py', id="single-quoted-old-takes-double-quotes"),
        pytest.param("python3 x.py", "/a b/python3", '"/a b/python3" x.py', id="bare-old-bare-spaced-target"),
        pytest.param("python3 x.py", '"/a b/python3"', '"/a b/python3" x.py', id="bare-old-quoted-spaced-target"),
        pytest.param("python3 x.py", "py -3", "py -3 x.py", id="bare-old-launcher-target"),
        pytest.param("python3 x.py", '"C:/Program Files/py.exe" -3', "C:/'Program Files'/py.exe -3 x.py",
                     id="bare-old-quoted-launcher-path-target"),
        pytest.param('. "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" "/x y/python3"', "python3",
                     '. "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" python3', id="dotted-shim-quoted-old-bare-target"),
        pytest.param('& "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" "C:/Program Files/py.exe" -3', "/a b/python3",
                     '& "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" "/a b/python3"',
                     id="called-shim-quoted-launcher-old-spaced-target"),
        pytest.param('"C:/Program Files/py.exe" -3 x.py', '"/a b/python3"', '"/a b/python3" x.py',
                     id="quoted-launcher-old-quoted-spaced-target"),
        pytest.param('"C:/Program Files/py.exe" -3 x.py', "python3", "python3 x.py", id="quoted-launcher-old-bare-target"),
    ])
    def test_the_swap_quotes_the_target_as_the_site_does(self, command, target, expected):
        """The target brings its own quoting: the old name's quotes go with
        it, a word is quoted only when it holds whitespace (a POSIX path
        double-quoted, which sh and Git Bash take; a drive-rooted Windows path
        quoted folder by folder, DEF-2063, since PowerShell refuses a word that
        opens with a quote and `"python3" x.py` is its parse error), and the
        launcher's flag follows the word bare.
        Production targets arrive bare (`python`, `python3`, `py -3`, the
        DEF-636 absolute path); the quoted ones are the API's and this table's.
        Before this a bare old name took a spaced target bare, the shape the
        shell cuts, and the old swap wrote `"py -3" x.py`, a file no host has."""
        assert cli._swap_interpreter_token(command, target) == expected

    def test_the_exec_form_rewire_writes_the_target_bare(self):
        """Exec form spawns ``command`` as one file name, so a quote there is
        part of the name (`_venv.entry_argv`): a quoted target is written
        without its quotes, and reported as written."""
        entry = {"type": "command", "command": "python3", "args": ["${CLAUDE_PROJECT_DIR}/x.py"]}
        assert cli._rewire_exec_entry(entry, '"/a b/python3"') == ("python3", "/a b/python3")
        assert entry["command"] == "/a b/python3", entry
        assert entry["args"] == ["${CLAUDE_PROJECT_DIR}/x.py"], entry

    def test_doctor_prescribes_the_rewire_for_a_quoted_spaced_site(self, tmp_path, monkeypatch):
        """DEF-620's loop, closed for this shape too: doctor reads the same
        predicate and told the operator the rewire "will NOT fix this one"
        for a site the rewire now fixes. The fixture's one spelling is exec
        form at one site and quoted shell form at two, so the per-spelling
        fold must keep it one word to its runner (exec form alone, folded
        across the three, reads False)."""
        from espalier import doctor as doctor_module

        monkeypatch.setattr(doctor_module, "_remedy_py", lambda: "python3")
        spaced = tmp_path / "with space"
        spaced.mkdir()
        missing = str(spaced / "bin" / "python3")  # resolves nowhere, on every host
        path = _settings(spaced, missing)
        issues = doctor_module._check_python_resolver(tmp_path, path)
        assert issues, "a wired interpreter that resolves nowhere drew no issue"
        joined = " ".join(issues)
        assert "will NOT fix this one" not in joined, joined

    def test_doctor_keeps_the_by_hand_remedy_where_one_site_of_the_spelling_is_unterminated(
            self, tmp_path, monkeypatch):
        """The fold's AND half: a hook quoted and terminated beside a statusLine
        whose quote never closes read as ONE spelling (the shim puts the
        interpreter last, so the unterminated token equals the terminated
        one); the rewire fixes the hook and declines the statusLine, and
        doctor's one sentence per spelling sends the operator to the hand edit
        rather than to a rewire that leaves the statusLine broken (an OR fold
        passed every other row here; code review)."""
        from espalier import doctor as doctor_module

        monkeypatch.setattr(doctor_module, "_remedy_py", lambda: "python3")
        missing = str(tmp_path / "with space" / "bin" / "python3")
        path = tmp_path / ".claude" / "settings.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "hooks": {"SessionStart": [{"hooks": [
                {"type": "command", "command": f'"{missing}" tools/cc/hooks/session_start.py'}]}]},
            "statusLine": {"type": "command",
                           "command": f'. "${{CLAUDE_PROJECT_DIR}}/tools/cc/statusline.cmd" "{missing}'},
        }), encoding="utf-8")
        joined = " ".join(doctor_module._check_python_resolver(tmp_path, path))
        assert "will NOT fix this one" in joined, joined

    @pytest.mark.parametrize("command", [
        pytest.param('"/x y/python3" x.py', id="quoted-spaced-dir-rewired"),
        pytest.param('"py -3" x.py', id="quoted-launcher-and-flag-one-file-name-declined"),
        pytest.param('"/x y/python3 -u" x.py', id="quoted-space-in-the-name-declined"),
        pytest.param("/x y/python3 x.py", id="bare-spaced-cut-declined"),
        pytest.param("python3 x.py", id="bare-rewirable"),
    ])
    def test_the_rewire_and_doctor_agree_on_every_shell_form_shape(self, tmp_path, command):
        """DEF-620 was two readers of one file disagreeing about argv[0]. The
        shape that decides a decline is read by `_wired_entry` for doctor and
        by the rewire walk for itself, so each row asks both and the verdicts
        must match; `"py -3" x.py` disagreed before this lane (the old swap
        wrote that shape). An unterminated quote whose rest of line ends in
        `.py` is skipped by doctor's suffix filter and declined by the rewire,
        a known gap named in the ledger and not pinned here."""
        entry = cli._wired_entry({"type": "command", "command": command}, ["x.py"])
        doctor_says_rewirable = cli._is_rewirable_interpreter(
            entry.argv[0], exec_form=entry.exec_form, cut=entry.cut, quoted=entry.quoted)
        path = tmp_path / ".claude" / "settings.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command", "command": command}]}]}}), encoding="utf-8")
        result = cli.rewire_interpreter_in_settings(path)
        rewire_declines = any(c == command for _, c in result.declined)
        assert doctor_says_rewirable == (not rewire_declines), (command, entry, result)

    def test_every_engine_caller_of_the_predicate_passes_all_three_readings(self):
        """A caller that leaves `quoted=` out gets the old whitespace refusal,
        and a mutation dropping it at the disarmed-diagnosis site turned no
        test red (failure-mode review), so every call in the engine is pinned
        to pass the three readings, and the count is pinned so a fourth
        caller is a decision, never a default."""
        import ast
        import inspect

        from espalier import doctor as doctor_module

        calls = []
        for module in (cli, doctor_module):
            for node in ast.walk(ast.parse(inspect.getsource(module))):
                if isinstance(node, ast.Call):
                    name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                    if name == "_is_rewirable_interpreter":
                        calls.append((module.__name__, node.lineno, sorted(k.arg or "" for k in node.keywords)))
        assert len(calls) == 3, calls
        for name, line, keywords in calls:
            assert {"exec_form", "cut", "quoted"} <= set(keywords), (name, line, keywords)

    def test_the_disarmed_fold_keeps_a_mixed_spelling_one_word(self, monkeypatch):
        """`_not_python3_from_entries` folds a spelling's entries to the shape
        that decides the remedy; a spelling exec form at one site and quoted
        at another stays rewirable, and an unterminated quote standing alone
        stays declined."""
        monkeypatch.setattr(cli._doctor, "_interpreter_is_python3", lambda resolved, *flags: False)
        entries = [
            cli._wired_entry({"command": "/x y/python3", "args": ["x.py"]}, ["tools/cc/hooks/write_guard.py"]),
            cli._wired_entry({"command": '"/x y/python3" tools/cc/hooks/session_start.py'},
                             ["tools/cc/hooks/session_start.py"]),
        ]
        found = cli._not_python3_from_entries(entries)
        assert set(found) == {"/x y/python3"}, found
        shape = found["/x y/python3"]
        assert shape.exec_form is False and shape.quoted is True, shape
        assert cli._is_rewirable_interpreter(
            shape.argv[0], exec_form=shape.exec_form, cut=shape.cut, quoted=shape.quoted)
        alone = cli._not_python3_from_entries([cli._wired_entry({"command": '"/x y/python3 x.py'}, ["x.py"])])
        (shape,) = alone.values()
        assert shape.quoted is False, shape
        assert not cli._is_rewirable_interpreter(
            shape.argv[0], exec_form=shape.exec_form, cut=shape.cut, quoted=shape.quoted)


#: (target, the swapped shell-form command, id): one row per spelling the
#: head writer chooses (DEF-2063).
_WINDOWS_HEADS = [
    ("C:/Program Files/Py/python.exe", "C:/'Program Files'/Py/python.exe x.py", "single-quoted-folder"),
    ("C:\\Program Files (x86)\\Py\\python.exe", "C:/'Program Files (x86)'/Py/python.exe x.py",
     "backslashes-turned-x86-folder"),
    ("C:\\Users\\a\\Python311\\python.exe", "C:/Users/a/Python311/python.exe x.py", "unspaced-forward-slashes"),
    ("C:/it's here/Py/python.exe", "C:/\"it's here\"/Py/python.exe x.py", "double-quoted-folder-holding-a-quote"),
    ("C:/it's $x/Py/python.exe", "\"C:/it's $x/Py/python.exe\" x.py", "whole-path-fallback"),
    ("/home/a b/bin/python3", "\"/home/a b/bin/python3\" x.py", "posix-path-whole-quoted"),
]


class TestASpacedWindowsHeadRunsInBothHookShells:
    """DEF-2063: a shell-form hook rewired to a spaced interpreter opened with
    a double-quoted word, which Windows PowerShell 5.1 reads as a string and
    refuses, so the hook never parsed where Git Bash is absent; ``& "<path>"``,
    PowerShell's own answer, is a syntax error to bash. A drive-rooted head is
    now written with forward slashes and only its spaced folders quoted, one
    word both shells run (driven on Windows 11 for folders holding a space,
    ``(x86)``, ``&``, ``$`` and ``'``), and every reader of the head reads that
    word back, so doctor and a second rewire see the path the first wrote."""

    @pytest.mark.parametrize("target,expected", [r[:2] for r in _WINDOWS_HEADS], ids=[r[2] for r in _WINDOWS_HEADS])
    def test_the_swap_spells_the_head_for_both_hook_shells(self, target, expected):
        assert cli._swap_interpreter_token("python x.py", target) == expected

    def test_a_folder_quoted_launcher_keeps_its_flag(self):
        """Code review: the launcher's flag was found by searching for the
        decoded token, which is no substring of a folder-quoted head, so the
        site was probed as a bare launcher (the DEF-1146 hazard)."""
        command = "C:/'Program Files'/py.exe -3 x.py"
        assert cli._launcher_spelling_of({"command": command}, "command", "C:/Program Files/py.exe") == (
            "C:/Program Files/py.exe -3")

    def test_the_probe_a_spaced_target_no_longer_opens_with_a_quote(self):
        """The row's probe."""
        assert cli._swap_interpreter_token("python tools/cc/hooks/a.py", "C:/Program Files/Py/python.exe")[:1] != '"'

    @pytest.mark.parametrize("target", [r[0] for r in _WINDOWS_HEADS], ids=[r[2] for r in _WINDOWS_HEADS])
    def test_the_written_head_reads_back_and_rewires_again(self, tmp_path, monkeypatch, target):
        """air's edge (ack c76dfb): the round trip per quote form. The rewire
        writes the head, the readers (the rewire walk, doctor's ``_wired_entry``
        and the hook-side twin) read the same path back as one word, and a
        second rewire replaces it whole with every argument kept."""
        from tests.test_hook_entry_argv import _session_start

        written = target.replace("\\", "/") if target[1:2] == ":" else target
        later = "C:/Other Dir/python.exe"
        passing = {target}
        monkeypatch.setattr(cli, "interpreter_meets_floor", lambda p: p in passing)
        monkeypatch.setattr(cli, "start_unconfirmed_of", lambda p: None)
        monkeypatch.setattr(cli, "banner_unanswered_of", lambda p: None)
        path = tmp_path / ".claude" / "settings.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [
            {"type": "command", "command": "python tools/cc/hooks/session_start.py --tag a"}]}]}}),
            encoding="utf-8")

        first = cli.rewire_interpreter_in_settings(path, new_interpreter=target)
        assert first.status == cli.REWIRE_DONE, first
        command = json.loads(path.read_text(encoding="utf-8"))["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        rest = ["tools/cc/hooks/session_start.py", "--tag", "a"]
        assert _venv.entry_argv(command) == (written, rest), command
        assert _session_start()._entry_argv(command) == (written, rest), command
        assert _venv.shell_cut_path(command) is None, command
        entry = cli._wired_entry({"type": "command", "command": command}, ["x.py"])
        assert entry.argv[0] == written, entry
        assert cli._is_rewirable_interpreter(entry.argv[0], exec_form=entry.exec_form, cut=entry.cut,
                                             quoted=entry.quoted), entry

        passing = {later}
        second = cli.rewire_interpreter_in_settings(path, new_interpreter=later)
        assert second.status == cli.REWIRE_DONE, second
        again = json.loads(path.read_text(encoding="utf-8"))["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        assert again == "C:/'Other Dir'/python.exe tools/cc/hooks/session_start.py --tag a", again

    @pytest.mark.parametrize("command,glued", [
        pytest.param("C:/x/'a b'/python.exe y", ("C:/x/a b/python.exe", 0, 21), id="single"),
        pytest.param('  C:/x/"a b"/python.exe y', ("C:/x/a b/python.exe", 2, 23), id="double-padded"),
        pytest.param("C:/x/'a b/python.exe y", None, id="unterminated"),
        pytest.param("'C:/x/a b/python.exe' y", None, id="opens-with-a-quote"),
        pytest.param("C:/x/python.exe y", None, id="no-quote"),
        pytest.param("C:\\x\\'a b'\\python.exe", ("C:\\x\\a b\\python.exe", 0, 21), id="backslash-is-a-character"),
        pytest.param("", None, id="empty"),
    ])
    def test_the_glued_head_reads_alike_in_both_copies(self, command, glued):
        from tests.test_hook_entry_argv import _session_start

        assert _venv.glued_head(command) == glued
        assert _session_start()._glued_head(command) == glued

    @pytest.mark.parametrize("char", [c for c in string.printable if c not in "/\\" and not c.isspace()]
                             + ["\u2019", "\u201c"], ids=lambda c: f"U+{ord(c):04X}")
    def test_every_folder_character_reads_back_as_written(self, char):
        """The failure-mode review's pin: a folder holding any one character,
        beside a spaced folder and alone, reads back through the head readers as
        the path the swap was given (a bare `'` in an unspaced folder once read
        as `C:/Users/DAngelo/My` and ran nowhere)."""
        for target in (f"C:/My Py/A{char}B/python.exe", f"C:/A{char}B/python.exe"):
            command = cli._swap_interpreter_token("python x.py", target)
            assert command[:1] != "&", command
            assert _venv.entry_argv(command) == (target, ["x.py"]), (target, command)

    @pytest.mark.skipif(sys.platform != "win32", reason="the two hook shells of a Windows host")
    @pytest.mark.parametrize("folder", ["Pro gram (x86)", "it's here", "R &D x", "a $b c",
                                        "D'Angelo/My Py", "Py(3.12)/My Py", "R&D/My Py"],
                             ids=["x86", "quote", "ampersand", "dollar", "unspaced-quote-folder",
                                  "unspaced-paren-folder", "unspaced-ampersand-folder"])
    def test_git_bash_and_powershell_run_the_written_line(self, tmp_path, folder):
        """The oracle the row names, on the host that runs the hook: a venv
        under a spaced folder, the head this swap writes for it, and the line
        run by Git Bash and by Windows PowerShell 5.1 (``-Command``). cmd.exe
        runs no hook and is not asked."""
        import subprocess
        import venv

        from tests.test_json_safe_program_word import git_bash as _git_bash
        from tests._pwsh_cache import private_cache_env
        from tests._wait_budget import scaled

        root = tmp_path / folder / "v"
        venv.EnvBuilder(with_pip=False).create(str(root))
        script = tmp_path / "mark.py"
        script.write_bytes(b"print('MARK-OK')\n")
        line = cli._swap_interpreter_token("python x.py", str(root / "Scripts" / "python.exe")).replace(
            "x.py", script.as_posix())
        assert line[:1] != '"', line
        shells = [["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", line]]
        bash = _git_bash()
        if bash is not None:
            run_sh = tmp_path / "run.sh"
            run_sh.write_bytes((line + "\n").encode("utf-8"))
            shells.append([bash, "--noprofile", "--norc", str(run_sh)])
        for argv in shells:
            proc = subprocess.run(  # spawn: ok the row's oracle is the real hook shell
                argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=scaled(20),
                env=private_cache_env())
            assert "MARK-OK" in proc.stdout, (argv[0], line, proc.returncode, proc.stderr[-400:])


class TestTheLauncherRewiresWithItsFlag:
    """The Windows Python Launcher's version flag (`py -3`) belongs to the
    launcher, so a rewire carries it with the interpreter in both directions.

    It used to be declined outright: a swap of argv[0] alone turned
    `py -3 <hook>` into `python3 -3 <hook>`, which exits with `Unknown option:
    -3` -- from a PreToolUse hook a BLOCK on every tool call (driven
    2026-09-03). Declining was safe while nothing wrote `py -3`; once `init`
    writes it on a launcher-only host, a tree whose launcher later breaks (or
    a python-wired tree on a launcher-only host) had no repair at all.
    Driven on the stubbed-PATH hosts of `tests/_interpreter_hosts.py`.
    """

    _HOOK = "${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"
    _SHIM = '"${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd"'

    @staticmethod
    def _host(tmp_path, monkeypatch, shape):
        from tests import _interpreter_hosts as hosts

        monkeypatch.setenv("PATH", str(hosts.build_host(tmp_path / "hosts", shape)))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)

    def _write(self, tmp_path, hooks, status_line=None):
        path = tmp_path / ".claude" / "settings.json"
        path.parent.mkdir(parents=True)
        doc = {"hooks": {"PreToolUse": [{"hooks": hooks}]}}
        if status_line is not None:
            doc["statusLine"] = {"type": "command", "command": status_line}
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    # The shim bare, behind PowerShell's call operator (DEF-929), and behind
    # the dot init renders (DEF-3017): the launcher's flag is found past each head.
    @pytest.mark.parametrize("lead", ["", "& ", ". "], ids=["bare-shim", "called-shim", "dotted-shim"])
    def test_a_dead_launcher_is_rewired_to_a_name_and_loses_its_flag(self, tmp_path, monkeypatch, lead):
        from tests import _interpreter_hosts as hosts

        self._host(tmp_path, monkeypatch, hosts.STORE_PYTHON3)  # python works, no launcher
        path = self._write(tmp_path, [
            {"type": "command", "command": "py", "args": ["-3", self._HOOK]},
            {"type": "command", "command": "py -3.11 tools/cc/hooks/plan_guard.py"},
        ], status_line=f"{lead}{self._SHIM} py -3")
        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_DONE, result
        after = json.loads(path.read_text(encoding="utf-8"))
        exec_entry, shell_entry = after["hooks"]["PreToolUse"][0]["hooks"]
        assert (exec_entry["command"], exec_entry["args"]) == ("python", [self._HOOK]), exec_entry
        assert shell_entry["command"] == "python tools/cc/hooks/plan_guard.py", shell_entry
        assert after["statusLine"]["command"] == f"{lead}{self._SHIM} python", after["statusLine"]
        assert not result.declined, result.declined

    def test_a_dead_name_is_rewired_to_the_launcher_with_its_flag(self, tmp_path, monkeypatch):
        from tests import _interpreter_hosts as hosts

        self._host(tmp_path, monkeypatch, hosts.LAUNCHER_ONLY)  # only `py -3` runs
        path = self._write(tmp_path, [
            {"type": "command", "command": "python", "args": [self._HOOK]},
            {"type": "command", "command": "python3 tools/cc/hooks/plan_guard.py"},
        ], status_line='python "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.py" || echo x')
        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_DONE, result
        after = json.loads(path.read_text(encoding="utf-8"))
        exec_entry, shell_entry = after["hooks"]["PreToolUse"][0]["hooks"]
        assert (exec_entry["command"], exec_entry["args"]) == ("py", ["-3", self._HOOK]), exec_entry
        assert shell_entry["command"] == "py -3 tools/cc/hooks/plan_guard.py", shell_entry
        assert after["statusLine"]["command"] == (
            'py -3 "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.py" || echo x'
        ), after["statusLine"]

    def test_a_working_launcher_is_left_alone_and_not_declined(self, tmp_path, monkeypatch):
        from tests import _interpreter_hosts as hosts

        self._host(tmp_path, monkeypatch, hosts.LAUNCHER_ONLY)
        path = self._write(tmp_path, [
            {"type": "command", "command": "py", "args": ["-3", self._HOOK]},
        ], status_line=f"{self._SHIM} py -3")
        before = path.read_bytes()
        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_NOTHING, result
        assert path.read_bytes() == before
        assert not result.declined, f"a working launcher site was reported as declined: {result.declined}"

    def test_a_quoted_dead_launcher_loses_its_quotes_and_its_flag(self, tmp_path, monkeypatch):
        """A quoted launcher path puts its closing quote between the token and
        the flag; the swap that looked for the flag right after the token left
        `"python" -3 <hook>` -- the `Unknown option: -3` block (review, 2026-10-02)."""
        from tests import _interpreter_hosts as hosts

        self._host(tmp_path, monkeypatch, hosts.STORE_PYTHON3)
        # A forward-slash path names the launcher on both hosts: on POSIX a
        # backslash is not a separator, so a `C:\...\py.exe` spelling read as
        # one word there and the site was never recognised (red on the Linux
        # cells only, 2026-10-02).
        path = self._write(tmp_path, [
            {"type": "command", "command": '"/nosuch/bin/py" -3 tools/cc/hooks/plan_guard.py'},
        ])
        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_DONE, result
        entry = json.loads(path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]
        assert entry["command"] == "python tools/cc/hooks/plan_guard.py", entry

    def test_doctor_session_start_and_the_rewire_agree_on_a_launcher_with_an_old_default(
        self, tmp_path, monkeypatch,
    ):
        """A bare `py` asks the launcher's DEFAULT (here a 3.9, as PY_PYTHON or a
        py.ini can make it); `py -3` runs the interpreter the site is wired to.
        Doctor and SessionStart probed the bare word while the rewire probed the
        spelling, so doctor prescribed a rewire that reported nothing to do --
        DEF-620's loop. All three now read the site as `py -3`."""
        import os
        import subprocess
        from espalier import doctor as doctor_module
        from tests import _interpreter_hosts as hosts

        bin_dir = hosts.build_old_default_launcher(tmp_path / "host")
        monkeypatch.setenv("PATH", str(bin_dir))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        repo = tmp_path / "repo"
        path = self._write(repo, [{"type": "command", "command": "py", "args": ["-3", self._HOOK]}])
        issues = doctor_module._check_python_resolver(repo, path)
        assert not [i for i in issues if "`py" in i], issues
        assert cli.rewire_interpreter_in_settings(path).status == cli.REWIRE_NOTHING
        env = {**os.environ, "PATH": hosts.path_with(bin_dir), "CLAUDE_PROJECT_DIR": str(repo)}
        run = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks" / "session_start.py")],
            input='{"hook_event_name":"SessionStart"}', capture_output=True, cwd=str(repo),
            env=env, text=True, encoding="utf-8", errors="replace", timeout=45,
        )
        skip_if_cut(run.stdout)  # a cut start never reached the warn (DEF-2048)
        assert "wired hook interpreter `py" not in run.stderr, run.stderr[-2000:]

    def test_an_argument_after_the_flag_survives(self, tmp_path, monkeypatch):
        from tests import _interpreter_hosts as hosts

        self._host(tmp_path, monkeypatch, hosts.STORE_PYTHON3)
        path = self._write(tmp_path, [
            {"type": "command", "command": "py", "args": ["-3", "-X", "utf8", self._HOOK]},
        ])
        cli.rewire_interpreter_in_settings(path)
        entry = json.loads(path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]
        assert (entry["command"], entry["args"]) == ("python", ["-X", "utf8", self._HOOK]), entry


@_POSIX_STUBS
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


class TestTheRewireMovesAWindowsHeadWhenAsked:
    """DEF-4071, as the operator ruled it (air's ack 04a16e): an install
    rendered before the dot form (DEF-3017) carries the statusline shim bare,
    which only Git Bash runs, or behind PowerShell's `&`, which only
    PowerShell runs (DEF-929), and the line is blank in the other shell.
    `init --rewire-interpreter` puts that head behind the dot, on request,
    keyed on the render host, printing what it wrote. A step of its own: the
    floor rewire beside it still changes only an interpreter word. Every
    other path leaves a working line alone (the standing word of 2cde27).
    Driven through the verb's report path on the stubbed-PATH host of
    `tests/_interpreter_hosts.py` whose `python` starts, so the floor rewire
    has nothing to do and the head step is all that can move."""

    _SHIM = '"${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd"'

    @staticmethod
    def _host(tmp_path, monkeypatch, *, posix=False):
        from tests import _interpreter_hosts as hosts

        monkeypatch.setenv("PATH", str(hosts.build_host(tmp_path / "hosts", hosts.STORE_PYTHON3)))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        monkeypatch.setattr(cli, "_render_host_is_posix", lambda: posix)

    @staticmethod
    def _write(tmp_path, command):
        path = tmp_path / "repo" / ".claude" / "settings.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"statusLine": {"type": "command", "command": command}}),
                        encoding="utf-8")
        return path

    @staticmethod
    def _command(path):
        return json.loads(path.read_text(encoding="utf-8"))["statusLine"]["command"]

    @pytest.mark.parametrize("lead", ["", "& ", "&"], ids=["bare", "called", "called-unspaced"])
    def test_a_bare_or_called_head_is_put_behind_the_dot(self, tmp_path, monkeypatch, capsys, lead):
        self._host(tmp_path, monkeypatch)
        legacy = f"{lead}{self._SHIM} python"
        path = self._write(tmp_path, legacy)
        status = cli._report_interpreter_rewire(path)
        err = capsys.readouterr().err
        after = self._command(path)
        assert after == f". {self._SHIM} python", (after, err)
        assert after == cli._statusline_command("python", posix=False), "not the form init renders"
        assert status == cli.REWIRE_DONE, (status, err)
        assert f"`{legacy}` -> `{after}`" in err, err
        assert "No file was written" not in err, err
        backups = list((tmp_path / "repo" / ".espalier" / "settings-backups").iterdir())
        assert backups, "the head moved with no backup on the ladder"

    @pytest.mark.parametrize("command", [
        '. "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" python',
        'node "${CLAUDE_PROJECT_DIR}/my_statusline.js"',
        'python "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.py" || echo x',
    ], ids=["dot-head", "not-espalier", "posix-string"])
    def test_a_line_with_no_legacy_shim_head_is_never_touched(self, tmp_path, monkeypatch, capsys, command):
        self._host(tmp_path, monkeypatch)
        path = self._write(tmp_path, command)
        before = path.read_bytes()
        status = cli._report_interpreter_rewire(path)
        err = capsys.readouterr().err
        assert path.read_bytes() == before, err
        assert status == cli.REWIRE_NOTHING, (status, err)

    @pytest.mark.parametrize("lead", ["", "& "], ids=["bare", "called"])
    def test_a_posix_render_host_is_never_given_a_dot_head(self, tmp_path, monkeypatch, capsys, lead):
        """A shim head on a POSIX host was carried in from Windows; the dot
        would run only the shim's first line there, so the line is doctor's
        to name (take the POSIX render), never this step's to move."""
        self._host(tmp_path, monkeypatch, posix=True)
        path = self._write(tmp_path, f"{lead}{self._SHIM} python")
        before = path.read_bytes()
        status = cli._report_interpreter_rewire(path)
        err = capsys.readouterr().err
        assert path.read_bytes() == before, err
        assert status == cli.REWIRE_NOTHING, (status, err)

    def test_a_kept_shim_git_bash_cannot_source_keeps_the_head_and_says_why(
        self, tmp_path, monkeypatch, capsys,
    ):
        """The dot sources the shim under Git Bash through its first line; a
        copy the deploy keeps as the operator's (no managed marker) that does
        not open with it would turn a working bare line blank there."""
        self._host(tmp_path, monkeypatch)
        legacy = f"{self._SHIM} python"
        path = self._write(tmp_path, legacy)
        shim = tmp_path / "repo" / "tools" / "cc" / "statusline.cmd"
        shim.parent.mkdir(parents=True)
        shim.write_bytes(b"@echo off\r\nrem the operator's own copy\r\n")
        before = path.read_bytes()
        status = cli._report_interpreter_rewire(path)
        err = capsys.readouterr().err
        assert path.read_bytes() == before, err
        assert status == cli.REWIRE_NOTHING, (status, err)
        assert "first line" in err and f"`{legacy}`" in err, err

    def test_an_old_managed_shim_the_deploy_refreshes_does_not_hold_the_move(
        self, tmp_path, monkeypatch, capsys,
    ):
        """The rewire runs before init's deploy, which replaces a copy that
        carries the managed marker with the packaged one, first line and all,
        so an install old enough to need the move is not refused for the shim
        it is about to get."""
        from espalier.managed_markers import MARKER_BATCH_COMMENT

        self._host(tmp_path, monkeypatch)
        path = self._write(tmp_path, f"& {self._SHIM} python")
        shim = tmp_path / "repo" / "tools" / "cc" / "statusline.cmd"
        shim.parent.mkdir(parents=True)
        shim.write_bytes(f"@echo off\r\n{MARKER_BATCH_COMMENT}\r\nrem an older shim\r\n".encode())
        assert cli._report_interpreter_rewire(path) == cli.REWIRE_DONE, capsys.readouterr().err
        assert self._command(path) == f". {self._SHIM} python"

    def test_a_managed_shim_the_deploy_cannot_write_holds_the_head(self, tmp_path, monkeypatch, capsys):
        """Failure-mode review: a managed shim the deploy cannot replace (a
        read-only copy, as a read-only checkout leaves it) stays old, so a
        moved head would be blank under Git Bash over it."""
        import stat

        from espalier.managed_markers import MARKER_BATCH_COMMENT

        self._host(tmp_path, monkeypatch)
        legacy = f"{self._SHIM} python"
        path = self._write(tmp_path, legacy)
        shim = tmp_path / "repo" / "tools" / "cc" / "statusline.cmd"
        shim.parent.mkdir(parents=True)
        shim.write_bytes(f"@echo off\r\n{MARKER_BATCH_COMMENT}\r\nrem an older shim\r\n".encode())
        shim.chmod(stat.S_IREAD)
        try:
            status = cli._report_interpreter_rewire(path)
        finally:
            shim.chmod(stat.S_IREAD | stat.S_IWRITE)
        err = capsys.readouterr().err
        assert self._command(path) == legacy, err
        assert status == cli.REWIRE_NOTHING, (status, err)
        assert "cannot write" in err and f"`{legacy}`" in err, err

    def test_both_steps_write_and_each_says_what_it_wrote(self, tmp_path, monkeypatch, capsys):
        """A dead interpreter behind a called head: the floor rewire swaps the
        word and the head step moves the head, each on its own backup rung."""
        self._host(tmp_path, monkeypatch)
        path = self._write(tmp_path, f"& {self._SHIM} py -3")
        status = cli._report_interpreter_rewire(path)
        err = capsys.readouterr().err
        assert self._command(path) == f". {self._SHIM} python", err
        assert status == cli.REWIRE_DONE, (status, err)
        assert f"`& {self._SHIM} py -3` -> `& {self._SHIM} python`" in err, err
        assert f"`& {self._SHIM} python` -> `. {self._SHIM} python`" in err, err
        backups = list((tmp_path / "repo" / ".espalier" / "settings-backups").iterdir())
        assert len(backups) == 2, backups

    def test_a_refused_file_never_reaches_the_head_step(self, tmp_path, monkeypatch, capsys):
        """A repeated key is refused by the read both steps share; the head
        step never runs over it, and "NOT modified" stays true."""
        self._host(tmp_path, monkeypatch)
        path = tmp_path / "repo" / ".claude" / "settings.json"
        path.parent.mkdir(parents=True)
        command = json.dumps(f"& {self._SHIM} python")
        path.write_text('{"statusLine": {"command": %s}, "statusLine": {"command": %s}}'
                        % (command, command), encoding="utf-8")
        before = path.read_bytes()
        status = cli._report_interpreter_rewire(path)
        err = capsys.readouterr().err
        assert path.read_bytes() == before, err
        assert status == cli.REWIRE_DUPLICATE_KEYS, (status, err)

    def test_the_head_step_has_no_permissive_default_and_one_caller(self):
        """Failure-mode review: the shim judge is required (a caller that
        forgot it got the move over a shim Git Bash cannot source), and the
        step is reached from the report alone, which only `cmd_init` calls,
        behind the flag: no unflagged path migrates a working line."""
        import ast
        import inspect

        from tests._live_tree import checkout_glob

        param = inspect.signature(cli.move_statusline_head_in_settings).parameters[
            "shim_sources_under_bash"]
        assert param.default is inspect.Parameter.empty, param
        callers: dict[str, set[str]] = {}
        for module in checkout_glob(Path(__file__).resolve().parent.parent / "espalier", "*.py"):
            tree = ast.parse(module.read_text(encoding="utf-8"))

            def visit(node: ast.AST, owner: str) -> None:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    owner = node.name
                if isinstance(node, ast.Call):
                    name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                    if name in ("move_statusline_head_in_settings", "_report_interpreter_rewire"):
                        callers.setdefault(name, set()).add(f"{module.name}::{owner}")
                for child in ast.iter_child_nodes(node):
                    visit(child, owner)

            visit(tree, "<module>")
        assert callers == {
            "move_statusline_head_in_settings": {"cli.py::_report_interpreter_rewire"},
            "_report_interpreter_rewire": {"cli.py::cmd_init"},
        }, callers
        lines = inspect.getsource(cli.cmd_init).splitlines()
        at = next(i for i, ln in enumerate(lines) if "_report_interpreter_rewire(" in ln)
        assert lines[at - 1].strip() == 'if getattr(args, "rewire_interpreter", False):', (
            "the call is no longer behind the flag", lines[at - 1])

    @pytest.mark.parametrize("dotted", [False, True], ids=["bare-head", "dotted-over-kept-shim"])
    def test_upgrade_names_the_flag_only_where_it_moves_something(
        self, tmp_path, monkeypatch, capsys, dotted,
    ):
        """Failure-mode review: upgrade's version-current line named the flag
        for every line one Windows shell cannot run, but a dotted head over a
        shim kept as the operator's has nothing for it to move, and upgrade
        then said the same again (DEF-620's loop). It names the flag for a
        bare or called head, and the shim's first line for a dotted one."""
        import argparse
        import subprocess

        from espalier import doctor as doctor_module
        from tests._quiet_git import NO_BACKGROUND_GIT

        monkeypatch.setattr(cli, "_render_host_is_posix", lambda: False)
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: True)
        monkeypatch.setattr(doctor_module, "git_bash_path", lambda *_: None)
        tree = tmp_path / "repo"
        tree.mkdir()
        (tree / "README.md").write_text("# t\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(tree), "init", "-q"], check=True, capture_output=True)
        for key, value in NO_BACKGROUND_GIT:
            subprocess.run(["git", "-C", str(tree), "config", key, value],
                           check=True, capture_output=True)
        monkeypatch.chdir(tree)
        assert cli.cmd_init(argparse.Namespace(repo=str(tree), config=None,
                                               write_gitignore=True)) == 0
        path = tree / ".claude" / "settings.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        rendered = data["statusLine"]["command"]
        if dotted:
            (tree / "tools" / "cc" / "statusline.cmd").write_bytes(b"@echo off\r\nrem mine\r\n")
        else:
            data["statusLine"]["command"] = rendered[len(". "):]
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        capsys.readouterr()
        assert cli.cmd_upgrade(argparse.Namespace(repo=str(tree), execute=False, config=None)) == 0
        out = capsys.readouterr().out
        line = next((ln for ln in out.splitlines() if "Windows shells cannot run" in ln), "")
        assert line, out
        if dotted:
            assert "--rewire-interpreter" not in line and "first line" in line, line
        else:
            assert "-m espalier init . --rewire-interpreter`" in line, line

    def test_init_moves_the_head_only_when_asked(self, tmp_path, monkeypatch, capsys):
        """The flag absent, a working line stays as it is: `init` keeps an
        existing settings.json and renders `.new` beside it. With the flag it
        moves, and the file reaches init's list of what it wrote."""
        import argparse
        import subprocess

        from tests._quiet_git import NO_BACKGROUND_GIT

        monkeypatch.setattr(cli, "_render_host_is_posix", lambda: False)
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        tree = tmp_path / "repo"
        tree.mkdir()
        (tree / "README.md").write_text("# t\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(tree), "init", "-q"], check=True, capture_output=True)
        for key, value in NO_BACKGROUND_GIT:
            subprocess.run(["git", "-C", str(tree), "config", key, value],
                           check=True, capture_output=True)
        monkeypatch.chdir(tree)
        rendered = cli._statusline_command(cli._detect_python_command(), posix=False)
        legacy = "& " + rendered[len(". "):]
        path = tree / ".claude" / "settings.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"statusLine": {"type": "command", "command": legacy}}),
                        encoding="utf-8")

        def init(**flags):
            return cli.cmd_init(argparse.Namespace(repo=str(tree), config=None,
                                                   write_gitignore=True, **flags))

        assert init() == 0
        assert self._command(path) == legacy, "init without the flag moved a working line"
        capsys.readouterr()
        assert init(rewire_interpreter=True) == 0
        err = capsys.readouterr().err
        assert self._command(path) == rendered, err
        assert f"`{legacy}` -> `{rendered}`" in err, err

