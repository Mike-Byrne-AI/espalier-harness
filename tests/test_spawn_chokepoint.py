"""Every spawn in ``tools/cc/hooks/`` is the chokepoint, routed through it, or
declared.

The chokepoint, ``_hook_utils.spawn_checked``, resolves argv[0] first
(``shutil.which``, which honours PATHEXT on Windows so ``npm`` finds
``npm.cmd`` -- DEF-948's remaining half) and returns a ``SpawnFailure``
instead of raising when the program cannot start, so every gate that routes
through it must decide what to SAY. Reporters keep their own
``subprocess.run`` under a ``# spawn: ok <reason>`` declaration on the call
line or the line above.

The population is derived, never hand-listed: an AST walk over every
``subprocess.run`` / ``Popen`` / ``call`` / ``check_output`` / ``check_call``
and every ``spawn_checked(`` call. FLOOR: the 27 sites the walk found at first
execution (28 by grep at authoring; the walk is the number that counts), so a
walk that finds fewer broke or a site vanished without the floor being lowered
on purpose. This pins the chokepoint contract and prevents the drift it
exists to end: a gate spawning raw again (the Windows shim unresolved, a
spawn failure raising past the gate) reds here by file and line, because a
silent green was exactly how the ``npm test`` gate ran green while never
running (DEF-948).
"""
from __future__ import annotations

import ast
import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[1] / "tools" / "cc" / "hooks"
SPAWN_FLOOR = 27
SPAWN_ATTRS = frozenset({"run", "Popen", "call", "check_output", "check_call"})
PRAGMA = "# spawn: ok"


def _load_hook_utils():
    spec = importlib.util.spec_from_file_location("hook_utils_for_spawn", str(HOOKS_DIR / "_hook_utils.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hook_utils_for_spawn"] = mod
    spec.loader.exec_module(mod)
    return mod


def spawn_sites() -> list[dict]:
    """Every raw ``subprocess.*`` call and every ``spawn_checked(`` call."""
    out: list[dict] = []
    for f in sorted(HOOKS_DIR.glob("*.py")):
        src = f.read_text(encoding="utf-8")
        lines = src.splitlines()
        tree = ast.parse(src)
        # `from subprocess import run` binds a bare name the attribute form
        # would miss; so would `os.system` / `os.popen` (the 2-A review).
        bare_spawns = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "subprocess"
            for alias in node.names if alias.name in SPAWN_ATTRS
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            raw = (
                isinstance(fn, ast.Attribute) and fn.attr in SPAWN_ATTRS
                and isinstance(fn.value, ast.Name) and fn.value.id == "subprocess"
            ) or (
                isinstance(fn, ast.Attribute) and fn.attr in {"system", "popen"}
                and isinstance(fn.value, ast.Name) and fn.value.id == "os"
            ) or (isinstance(fn, ast.Name) and fn.id in bare_spawns)
            routed = (isinstance(fn, ast.Attribute) and fn.attr == "spawn_checked") or (
                isinstance(fn, ast.Name) and fn.id == "spawn_checked"
            )
            if not raw and not routed:
                continue
            declared = any(PRAGMA in lines[i] for i in (node.lineno - 1, node.lineno - 2) if 0 <= i < len(lines))
            out.append({"file": f.name, "lineno": node.lineno, "raw": raw, "routed": routed, "declared": declared})
    return out


class TestSpawnChokepoint:
    def test_the_walk_finds_the_population(self):
        n = len(spawn_sites())
        assert n >= SPAWN_FLOOR, (
            f"{n} spawn sites, below the floor {SPAWN_FLOOR} recorded at first execution: "
            "the walk broke, or a site was deleted -- lower the floor on purpose, naming it"
        )

    def test_every_raw_spawn_is_the_chokepoint_or_declared(self):
        chokepoint = [s for s in spawn_sites() if s["raw"] and s["file"] == "_hook_utils.py" and not s["declared"]]
        assert len(chokepoint) == 1, (
            "exactly one undeclared raw subprocess call belongs in _hook_utils.py -- the "
            f"chokepoint's own; found {chokepoint}"
        )
        stray = [s for s in spawn_sites() if s["raw"] and not s["declared"] and s["file"] != "_hook_utils.py"]
        assert not stray, (
            "raw subprocess calls outside the chokepoint must route through "
            "_hook_utils.spawn_checked (a gate) or carry `# spawn: ok <reason>` on the "
            "call line or the line above (a reporter):\n  "
            + "\n  ".join(f"{s['file']}:{s['lineno']}" for s in stray)
        )

    def test_the_gates_route(self):
        routed = {(s["file"]) for s in spawn_sites() if s["routed"]}
        assert "stop_gate.py" in routed, "the stop gate's spawns (override, pytest, finalize) route through the chokepoint"
        raw_stop = [s for s in spawn_sites() if s["raw"] and s["file"] == "stop_gate.py"]
        assert not raw_stop, f"stop_gate.py still spawns raw: {raw_stop}"


class TestSpawnChecked:
    def test_an_unresolvable_program_is_a_typed_failure_not_a_raise(self, tmp_path):
        hu = _load_hook_utils()
        got = hu.spawn_checked(["espalier-no-such-program-xyz", "--flag"], root=tmp_path, capture_output=True)
        assert isinstance(got, hu.SpawnFailure)
        assert got.error == "Unresolved" and got.resolved is None
        assert "`espalier-no-such-program-xyz` did not resolve" in got.resolution

    def test_a_resolved_program_runs_with_its_resolved_path(self, tmp_path, monkeypatch):
        hu = _load_hook_utils()
        seen: dict = {}

        def _capture(argv, **kw):
            seen["argv"] = argv
            import types
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        import subprocess
        monkeypatch.setattr(subprocess, "run", _capture)
        monkeypatch.setattr(shutil, "which", lambda tok, *a, **k: "/resolved/" + tok)
        got = hu.spawn_checked(["npm", "test"], root=tmp_path, capture_output=True)
        assert not isinstance(got, hu.SpawnFailure)
        assert seen["argv"] == ["/resolved/npm", "test"], "the RESOLVED path is what starts"

    def test_a_resolved_program_that_still_cannot_start_names_both(self, tmp_path, monkeypatch):
        hu = _load_hook_utils()
        import subprocess

        def _boom(argv, **kw):
            raise PermissionError(13, "denied")

        monkeypatch.setattr(subprocess, "run", _boom)
        monkeypatch.setattr(shutil, "which", lambda tok, *a, **k: "/resolved/" + tok)
        got = hu.spawn_checked(["npm", "test"], root=tmp_path)
        assert isinstance(got, hu.SpawnFailure)
        assert got.error == "PermissionError" and got.resolved == "/resolved/npm"
        assert "resolved to `/resolved/npm` and still could not start" in got.resolution

    def test_a_path_token_resolves_against_root_never_the_cwd(self, tmp_path, monkeypatch):
        hu = _load_hook_utils()
        script = tmp_path / "scripts" / "t.sh"
        script.parent.mkdir()
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)
        monkeypatch.chdir(tmp_path.parent)
        assert hu.resolve_program("scripts/t.sh", root=tmp_path) == str(script)
        assert hu.resolve_program("scripts/t.sh", root=tmp_path / "elsewhere") is None

    def test_root_is_required_so_a_dropped_argument_cannot_fall_back_to_the_cwd(self, tmp_path):
        """The relative-override fix of 2026-09-29 resolved against the root;
        a `root=None` default would let a dropped argument fall back to the
        hook process's cwd silently (the 2-A review). Both entry points refuse."""
        hu = _load_hook_utils()
        with pytest.raises(TypeError):
            hu.resolve_program("scripts/t.sh")  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            hu.spawn_checked(["true"])  # type: ignore[call-arg]

    def test_a_resolved_failure_carries_the_errno_detail(self, tmp_path, monkeypatch):
        hu = _load_hook_utils()
        import subprocess

        def _boom(argv, **kw):
            raise PermissionError(13, "Permission denied", "/resolved/npm")

        monkeypatch.setattr(subprocess, "run", _boom)
        monkeypatch.setattr(shutil, "which", lambda tok, *a, **k: "/resolved/" + tok)
        got = hu.spawn_checked(["npm", "test"], root=tmp_path)
        assert isinstance(got, hu.SpawnFailure)
        assert got.detail and "Permission denied" in got.detail and "13" in got.detail

    def test_a_windows_shim_with_a_metacharacter_argument_is_refused(self, tmp_path, monkeypatch):
        hu = _load_hook_utils()
        monkeypatch.setattr(hu.os, "name", "nt")
        monkeypatch.setattr(shutil, "which", lambda tok, *a, **k: r"C:\node\npm.cmd")
        got = hu.spawn_checked(["npm", "test", "&", "calc"], root=tmp_path)
        assert isinstance(got, hu.SpawnFailure) and got.error == "CmdShimMetachar"
        assert "re-parses its arguments" in got.resolution

    def test_timeouts_propagate(self, tmp_path, monkeypatch):
        hu = _load_hook_utils()
        import subprocess

        def _slow(argv, **kw):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=1)

        monkeypatch.setattr(subprocess, "run", _slow)
        monkeypatch.setattr(shutil, "which", lambda tok, *a, **k: "/resolved/" + tok)
        with pytest.raises(subprocess.TimeoutExpired):
            hu.spawn_checked(["slow"], root=tmp_path, timeout=1)

    def test_split_command_keeps_a_quoted_path_whole(self):
        hu = _load_hook_utils()
        assert hu.split_command('"/opt/my tools/npm" test --grep "a b"') == ["/opt/my tools/npm", "test", "--grep", "a b"]
        with pytest.raises(ValueError):
            hu.split_command('npm "unbalanced')


@pytest.mark.skipif(os.name != "nt", reason="the PATHEXT shim resolution is Windows's own; the portability leg drives it")
class TestWindowsShimResolution:
    def test_npm_resolves_to_its_cmd_shim_and_starts(self, tmp_path):
        """DEF-948's measurement, pinned where the dispatched Windows leg runs
        it: ``shutil.which('npm')`` returns the ``.cmd`` shim (2026-09-29,
        Windows 11: ``...\\npm.cmd``), and the chokepoint starts it. A runner
        without node is an ENVIRONMENT fact and skips loudly (the reflexive
        repair for a bare `None` would have been a permanent skip); the two
        assertions that remain are the CODE facts this case exists for."""
        hu = _load_hook_utils()
        found = shutil.which("npm")
        if found is None:
            pytest.skip("npm is not on this runner's PATH: the .cmd measurement cannot run here "
                        "(the windows-latest image ships node; a skip here means the image changed)")
        assert found.lower().endswith(".cmd"), found
        got = hu.spawn_checked(["npm", "--version"], root=tmp_path, capture_output=True, text=True, timeout=45)
        assert not isinstance(got, hu.SpawnFailure), got
        assert got.returncode == 0, got.stderr
