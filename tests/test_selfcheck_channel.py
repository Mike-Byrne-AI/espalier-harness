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
        from pathlib import Path

        import espalier
        from espalier.selfcheck import run_selfcheck

        pkg_parent = str(Path(espalier.__file__).resolve().parents[1])
        captured: dict[str, object] = {}
        from espalier import selfcheck
        real_run = selfcheck.run_no_stdin

        def _spy(cmd, *args, **kwargs):
            captured["env"] = kwargs.get("env")
            return real_run(cmd, *args, **kwargs)

        # selfcheck's spawn goes through the engine wrapper (DEF-928)
        monkeypatch.setattr(selfcheck, "run_no_stdin", _spy)
        rc = run_selfcheck(tmp_path)

        assert rc == 0
        env = captured.get("env")
        assert env is not None, "run_selfcheck must pass env= to propagate the import root"
        assert pkg_parent in env.get("PYTHONPATH", "").split(os.pathsep)

    def test_the_callers_pytest_options_and_plugins_never_reach_the_bundled_run(self, tmp_path, monkeypatch):
        # DEF-1150: the child pytest took the caller's PYTEST_ADDOPTS and
        # PYTEST_PLUGINS, so a --basetemp named there was emptied (pytest
        # empties a basetemp it is given) and a plugin meant for the caller's
        # own suite loaded into the bundled run. Driven for real: an inherited
        # basetemp holding a file another run is using, and a plugin on the
        # path that leaves a mark when it loads.
        import os

        from espalier.selfcheck import run_selfcheck

        held = tmp_path / "bt" / "popen-gw0" / "test_x0" / "in-use.txt"
        held.parent.mkdir(parents=True)
        held.write_text("x", encoding="utf-8")
        mark = tmp_path / "callers-plugin-loaded"
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        (plugins / "callers_own_plugin.py").write_text(
            "from pathlib import Path\n"
            "def pytest_configure(config):\n"
            f"    Path({str(mark)!r}).write_text('x', encoding='utf-8')\n",
            encoding="utf-8")
        monkeypatch.setenv("PYTEST_ADDOPTS", f"--basetemp={(tmp_path / 'bt').as_posix()}")
        monkeypatch.setenv("PYTEST_PLUGINS", "callers_own_plugin")
        existing = os.environ.get("PYTHONPATH", "")
        monkeypatch.setenv("PYTHONPATH", os.pathsep.join(p for p in (str(plugins), existing) if p))

        rc = run_selfcheck(tmp_path)

        assert held.exists(), "the bundled run emptied a --basetemp the caller's PYTEST_ADDOPTS named"
        assert not mark.exists(), "the bundled run loaded a plugin the caller's PYTEST_PLUGINS named"
        assert rc == 0
