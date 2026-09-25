"""TP-149 (G-3): ``python -m espalier`` must invoke the CLI, in parity with
the ``espalier`` console script.

Before G-3 there was no ``espalier/__main__.py``, so the documented
``python3 -m espalier audit .`` fallback failed with "No module named
espalier.__main__". This smoke test pins that the module entry point exists,
exits 0 on ``--version``, and delegates to the same ``espalier.cli:main``
the console-script entry point uses.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_module(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "espalier", *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=30,
        check=False, encoding="utf-8",
    )


def test_python_dash_m_version_exits_zero():
    proc = _run_module("--version")
    assert proc.returncode == 0, (
        f"`python -m espalier --version` exited {proc.returncode}; "
        f"stderr: {proc.stderr}"
    )
    assert "espalier" in proc.stdout.lower(), (
        f"--version did not print the version: {proc.stdout!r}"
    )


def test_main_module_delegates_to_cli_main():
    """Importing the module must not run main() (guarded by __name__), and
    its ``main`` symbol must be the console-script entry point."""
    import espalier.__main__ as main_module
    from espalier.cli import main as cli_main

    assert main_module.main is cli_main


def test_main_oserror_subclass_yields_clean_error(monkeypatch, capsys):
    """FAILUX-1: a NotADirectoryError (an OSError subclass that the old handler
    — which caught only FileNotFoundError / PermissionError — let escape) must
    yield a clean ``Error: ...`` + exit 1, not a raw traceback. RED before the
    ``except OSError`` broaden."""
    from espalier import cli

    def boom(args):
        raise NotADirectoryError("not a directory: foo/bar")

    # build_parser() runs inside main(), binding the module-global cmd_doctor
    # at that point — so patching the global routes `doctor .` to the raiser.
    monkeypatch.setattr(cli, "cmd_doctor", boom)
    monkeypatch.setattr(sys, "argv", ["espalier", "doctor", "."])

    rc = cli.main()

    assert rc == 1
    err = capsys.readouterr().err
    assert "Error: " in err
    assert "not a directory" in err


def test_main_turns_ctrl_c_into_one_line_and_130(monkeypatch, capsys):
    """DEF-800: ``KeyboardInterrupt`` is a BaseException, so the OSError and
    ValueError handlers never saw it and Ctrl+C at init's wire prompt dumped a
    runpy traceback. RED before the handler: the interrupt propagated out of
    ``main``. 130 is the shell's convention for a SIGINT exit; the partial-state
    sentence is the prompt site's job (test_init_interactive_arming.py)."""
    from espalier import cli

    def interrupted(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "cmd_doctor", interrupted)
    monkeypatch.setattr(sys, "argv", ["espalier", "doctor", "."])

    rc = cli.main()

    assert rc == 130
    out, err = capsys.readouterr()
    assert err.strip() == "Interrupted."
    assert "Traceback" not in err and out == ""
