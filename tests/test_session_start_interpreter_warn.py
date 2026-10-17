"""TP-177 W6-3: SessionStart emits a WARN when a wired hook interpreter
does not resolve on the host.

A settings.json hook command naming an absent interpreter (``python`` on a
python3-only host, or a stale absolute path) makes Claude Code run the hook,
exit 127 with empty stdout, and -- per the protocol -- treat the non-{0,2}
exit as non-blocking. Every blocking guard then fails OPEN, silently. The
only pre-existing detector was opt-in ``espalier doctor``; this banner makes
the gap visible every boot.

REACH, stated honestly (DEF-508). The warning is printed by a SessionStart
hook that RAN, so it can only ever report an interpreter other than its own:
a hook hand-wired to a different name than SessionStart's (the shape every
test below builds -- PreToolUse names the bogus interpreter while
session_start runs under ``sys.executable``), or a Python 3 that runs this
hook but is below the floor the blueprint modules need. On the file ``init``
renders every hook shares ONE interpreter, so the "does not resolve" branch
cannot fire there: SessionStart itself never started. That population is
covered out-of-band -- Claude Code's own per-hook ``Executable not found in
$PATH`` notice, the statusLine fallback ``init`` renders on POSIX hosts
(``tests/test_hook_exec_form.py::TestStatusLinePortability``) and
``espalier doctor``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION_START = REPO_ROOT / "tools" / "cc" / "hooks" / "session_start.py"


def _write_settings(repo: Path, command: str, args: list | None = None) -> None:
    claude = repo / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    entry = {"type": "command", "command": command}
    if args is not None:
        entry["args"] = args
    settings = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "*", "hooks": [entry]}
            ]
        }
    }
    (claude / "settings.json").write_text(json.dumps(settings), encoding="utf-8")


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    return subprocess.run(
        [sys.executable, str(SESSION_START)],
        input='{"hook_event_name":"SessionStart"}',
        capture_output=True,
        cwd=str(repo),
        env=env,
        text=True,
        timeout=15, encoding="utf-8",
    )


def test_warns_when_hook_interpreter_unresolved(tmp_path):
    # Python-shaped on purpose: only a word that names a Python is asked
    # whether it is one (DEF-1024).
    bogus = "python-definitely-not-real-xyz"
    _write_settings(tmp_path, f"{bogus} /x/hook.py")
    result = _run(tmp_path)
    assert "[WARN]" in result.stderr
    assert "does not resolve" in result.stderr, (
        "SessionStart did not warn about the unresolved hook interpreter. "
        "stderr was:\n" + result.stderr
    )
    assert bogus in result.stderr


def test_silent_when_hook_interpreter_resolves(tmp_path):
    # The interpreter running this test resolves by definition. Shell form, so
    # the path is quoted as a shell needs it when it holds a space.
    _write_settings(tmp_path, f'"{sys.executable}" /x/hook.py')
    result = _run(tmp_path)
    assert "does not resolve" not in result.stderr, (
        "SessionStart falsely flagged a resolvable interpreter. "
        "stderr was:\n" + result.stderr
    )


def test_silent_when_the_exec_form_init_renders_resolves(tmp_path):
    """The entry the way ``init`` renders it: exec form, ``command`` the
    running interpreter unquoted, ``args`` the script. Read as a shell string
    it was ``C:\\Program`` on a host whose interpreter sits under a spaced
    directory, and warned every session (DEF-968)."""
    _write_settings(tmp_path, sys.executable, args=["/x/hook.py"])
    result = _run(tmp_path)
    assert "does not resolve" not in result.stderr, (
        "SessionStart falsely flagged the exec-form entry init renders. "
        "stderr was:\n" + result.stderr
    )


def test_silent_on_bare_path_variable_command(tmp_path):
    """TP-184 B10: a bare-PATH command carrying an unexpanded ${...} variable
    (a canonical Claude Code idiom) is a SCRIPT run via its shebang, not an
    interpreter on PATH. `which` returns None for it, but that is not a real
    failure — the resolve WARN must NOT fire (it did pre-fix, every boot)."""
    _write_settings(tmp_path, "${CLAUDE_PROJECT_DIR}/tools/cc/hooks/x.py")
    result = _run(tmp_path)
    assert "does not resolve" not in result.stderr, (
        "SessionStart falsely flagged a ${...} bare-path script command. "
        "stderr was:\n" + result.stderr
    )


def test_silent_on_bare_script_path_command(tmp_path):
    """TP-184 B10: a bare absolute script path (ending .py/.sh) is likewise run
    via its shebang — not a resolvable interpreter name."""
    _write_settings(tmp_path, "/opt/hooks/my_hook.py")
    result = _run(tmp_path)
    assert "does not resolve" not in result.stderr, (
        "SessionStart falsely flagged a bare script-path command. "
        "stderr was:\n" + result.stderr
    )


def _session_start_in_process():
    """``session_start`` loaded the way a hook loads it, so its ``_hook_utils`` is
    the shared module object the seams below patch."""
    import importlib.util
    hooks = str(SESSION_START.parent)
    if hooks not in sys.path:
        sys.path.insert(0, hooks)
    spec = importlib.util.spec_from_file_location("_ss_interpreter_warn", SESSION_START)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _on_a_loaded_host(monkeypatch) -> tuple:
    """Every ``--version`` spawn times out, as on a host loaded past 2 s; returns
    the module and the lines SessionStart said."""
    ss = _session_start_in_process()
    monkeypatch.setattr(ss._hook_utils, "_INTERPRETER_IDENTITY_MEMO", {})

    def run(argv, **_kw):
        raise subprocess.TimeoutExpired(argv, 2)
    monkeypatch.setattr(ss._hook_utils, "run_bounded", run)
    said: list = []
    monkeypatch.setattr(ss._hook_utils, "advise", lambda line, **_kw: said.append(line))
    return ss, said


def test_a_wired_interpreter_that_never_answers_is_not_confirmed_never_older(tmp_path, monkeypatch):
    """DEF-5016: a probe that never answered in its time is no answer, so the
    line says the version was not confirmed, never "does not resolve" or
    "older than"."""
    ss, said = _on_a_loaded_host(monkeypatch)
    other = tmp_path / "bin" / "python3"
    other.parent.mkdir()
    other.write_bytes(b"")
    _write_settings(tmp_path, str(other), ["x.py"])
    ss._warn_if_hook_interpreter_unresolved(tmp_path)
    assert len(said) == 1 and "not confirmed" in said[0], said
    assert "older than" not in said[0] and "does not resolve" not in said[0], said
    # a WARN, not a NOTE the banner trims first: a hang fails its hooks open
    assert said[0].startswith("[WARN]") and "fails OPEN" in said[0], said


def test_the_running_interpreter_wired_is_silent_on_a_loaded_host(tmp_path, monkeypatch):
    """DEF-5016, the row's own case: the interpreter running the hooks, wired,
    was called "a Python 3 but older than" the floor when its own `--version`
    timed out. Its version is read from sys.version_info now."""
    if " " in sys.executable:
        pytest.skip("an exec-form name with a space is the unstartable branch, not this one")
    if tuple(sys.version_info[:2]) < (3, 10):
        pytest.skip("below the floor, the warning is right")
    ss, said = _on_a_loaded_host(monkeypatch)
    _write_settings(tmp_path, sys.executable, ["x.py"])
    ss._warn_if_hook_interpreter_unresolved(tmp_path)
    assert said == [], said


def test_a_kept_older_helper_without_the_reader_still_starts(tmp_path, monkeypatch):
    """A kept, older _hook_utils has no `interpreter_version_unanswered`: the
    check reads every False as a verdict, as before, and never raises."""
    ss, said = _on_a_loaded_host(monkeypatch)
    monkeypatch.delattr(ss._hook_utils, "interpreter_version_unanswered")
    other = tmp_path / "bin" / "python3"
    other.parent.mkdir()
    other.write_bytes(b"")
    _write_settings(tmp_path, str(other), ["x.py"])
    ss._warn_if_hook_interpreter_unresolved(tmp_path)
    assert len(said) == 1 and "not confirmed" not in said[0], said
