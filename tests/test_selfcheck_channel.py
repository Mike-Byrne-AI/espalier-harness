"""The ``espalier selfcheck`` channel: the subcommand exists, the bundled mirror
resolves from the installed package, and the curated tests run green against the
installed engine without reading the adopter repo tree.

This guards the selfcheck delivery channel itself — the wiring (subparser →
``cmd_selfcheck`` → ``run_selfcheck`` → subprocess pytest against the resolved
mirror) that the curated host-agnostic check content fills behind it. Without
this, the channel could silently stop resolving the mirror (a package-data glob
regression) or stop dispatching (a dropped subparser) and the bundled checks
would never run, defeating the whole point of ``selfcheck``.
"""
from __future__ import annotations

import argparse
from importlib.resources import as_file, files
from pathlib import Path

import pytest


def _selfcheck_subparser() -> argparse.ArgumentParser:
    from espalier.cli import build_parser

    parser = build_parser()
    action = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    return action.choices["selfcheck"]


class TestSelfcheckChannel:
    def test_help_exits_zero(self):
        sub = _selfcheck_subparser()
        with pytest.raises(SystemExit) as exc:
            sub.parse_args(["--help"])
        assert exc.value.code == 0

    def test_subparser_binds_handler_and_default_repo(self):
        from espalier.cli import build_parser, cmd_selfcheck

        parser = build_parser()
        ns = parser.parse_args(["selfcheck"])
        assert ns.func is cmd_selfcheck
        assert ns.repo == "."

    def test_mirror_resolves_and_is_nonempty(self):
        with as_file(
            files("espalier").joinpath("_vendor", "selfcheck_tests")
        ) as mirror:
            mirror = Path(mirror)
            assert mirror.is_dir(), f"selfcheck mirror is not a directory: {mirror}"
            assert any(mirror.glob("*.py")), "selfcheck mirror has no .py files"

    def test_run_selfcheck_is_green_against_synthetic_repo(self, tmp_path):
        # A synthetic empty repo: run_selfcheck must ignore the adopter tree (the
        # curated tests build their own tmp_path repos) and still run the bundled
        # mirror green. Proves the channel does not depend on the host tree.
        from espalier.selfcheck import run_selfcheck

        assert run_selfcheck(tmp_path) == 0

    def test_cmd_selfcheck_returns_pytest_exit_code(self, tmp_path):
        from espalier.cli import cmd_selfcheck

        rc = cmd_selfcheck(argparse.Namespace(repo=str(tmp_path)))
        assert rc == 0

    def test_run_selfcheck_propagates_espalier_import_root(self, tmp_path, monkeypatch):
        # Regression (env-relative green): run_selfcheck spawns pytest with a
        # throwaway cwd, so the subprocess CANNOT pick espalier up off the cwd.
        # It MUST hand the running espalier's import root to the subprocess via
        # PYTHONPATH, else the bundled tests fail with ModuleNotFoundError on a
        # source checkout (the channel works only when espalier is pip-installed).
        # Earns-the-red install-agnostically: before the fix the subprocess got
        # env=None and the PYTHONPATH assertion below reds even under an editable
        # install (which would otherwise mask the bug via test_run_selfcheck_*).
        import os
        import subprocess
        from pathlib import Path

        import espalier
        from espalier.selfcheck import run_selfcheck

        pkg_parent = str(Path(espalier.__file__).resolve().parents[1])
        captured: dict[str, object] = {}
        real_run = subprocess.run

        def _spy(cmd, *args, **kwargs):
            captured["env"] = kwargs.get("env")
            return real_run(cmd, *args, **kwargs)

        monkeypatch.setattr("espalier.selfcheck.subprocess.run", _spy)
        rc = run_selfcheck(tmp_path)

        assert rc == 0
        env = captured.get("env")
        assert env is not None, "run_selfcheck must pass env= to propagate the import root"
        assert pkg_parent in env.get("PYTHONPATH", "").split(os.pathsep)
