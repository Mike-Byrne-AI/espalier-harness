"""TP-175 R2: review_agent_audit must not false-positive on stdout prints that
live in a hook module's ``if __name__ == "__main__":`` CLI shim (e.g. the
``/recall`` pull tool in tools/cc/hooks/_recall.py). Those are not hook-event
handlers — their stdout cannot corrupt block JSON — so flagging them is a
false-positive that reddens the test.yml code-review-audit CI job for no real
defect. This contract guards against that regression, which had kept the job red
on every push since TP-167; without it the audit's own guardrail blocks merges."""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
_AUDIT_PATH = REPO_ROOT / "tools" / "review_agent_audit.py"


def _load_audit():
    spec = importlib.util.spec_from_file_location("review_agent_audit", _AUDIT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_full_mode_exits_zero():
    """Earn-the-red: `review_agent_audit.py --mode full` must exit 0 on the live
    repo. Against pre-R2 HEAD this FAILS (exit 1, flagging _recall.py's __main__
    print)."""
    proc = subprocess.run(
        [sys.executable, str(_AUDIT_PATH), "--mode", "full"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, (
        f"review_agent_audit --mode full exited {proc.returncode}:\n"
        f"{proc.stdout}\n{proc.stderr}"
    )


def test_print_in_main_guard_not_flagged():
    """A bare-stdout print inside `if __name__ == '__main__':` (a CLI shim) is
    NOT a hook-event handler and must not be flagged."""
    audit = _load_audit()
    src = (
        "import sys\n"
        "def handler(event):\n"
        "    return 0\n"
        "if __name__ == '__main__':\n"
        "    print('cli output')\n"
    )
    tree = ast.parse(src)
    path = Path("tools/cc/hooks/_fake_shim.py")
    assert audit.check_hook_print_to_stdout(path, tree) == []


def test_a_latin1_source_is_a_reported_syntax_error_not_a_traceback(tmp_path, capsys):
    """Ledger DEF-829: ``UnicodeDecodeError`` is a ``ValueError`` the
    ``except OSError`` let past ``run_audit``. The source is parsed from bytes
    now, so a non-UTF-8 file with no coding cookie is the SyntaxError the
    handler already reports, and the run finishes with it counted."""
    audit = _load_audit()
    bad = tmp_path / "cp1252.py"
    bad.write_bytes(b'x = "caf\xe9"\n')
    assert audit.run_audit([bad], "full") == 1
    assert "SYNTAX ERROR" in capsys.readouterr().out


def test_print_in_event_handler_still_flagged():
    """A bare-stdout print in real hook-handler code (not a __main__ shim) is
    still flagged — the fix must not blanket-disable the check."""
    audit = _load_audit()
    src = (
        "def main():\n"
        "    print('advisory')\n"
    )
    tree = ast.parse(src)
    path = Path("tools/cc/hooks/fake_hook.py")
    issues = audit.check_hook_print_to_stdout(path, tree)
    assert issues and "PRINT STDOUT" in issues[0]
