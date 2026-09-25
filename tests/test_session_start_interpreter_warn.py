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

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION_START = REPO_ROOT / "tools" / "cc" / "hooks" / "session_start.py"


def _write_settings(repo: Path, command: str) -> None:
    claude = repo / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    settings = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "*", "hooks": [{"type": "command", "command": command}]}
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
    bogus = "definitely-not-a-real-python-xyz"
    _write_settings(tmp_path, f"{bogus} /x/hook.py")
    result = _run(tmp_path)
    assert "[WARN]" in result.stderr
    assert "does not resolve" in result.stderr, (
        "SessionStart did not warn about the unresolved hook interpreter. "
        "stderr was:\n" + result.stderr
    )
    assert bogus in result.stderr


def test_silent_when_hook_interpreter_resolves(tmp_path):
    # The interpreter running this test resolves by definition.
    _write_settings(tmp_path, f"{sys.executable} /x/hook.py")
    result = _run(tmp_path)
    assert "does not resolve" not in result.stderr, (
        "SessionStart falsely flagged a resolvable interpreter. "
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
