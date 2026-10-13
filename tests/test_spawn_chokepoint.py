"""Every spawn in ``tools/cc/hooks/`` is the chokepoint, routed through it, or
declared; every timed spawn under ``tools/cc/`` is bounded.

The chokepoint, ``_hook_utils.spawn_checked``, resolves argv[0] first
(``shutil.which``, which honours PATHEXT on Windows so ``npm`` finds
``npm.cmd`` -- DEF-948's remaining half) and returns a ``SpawnFailure``
instead of raising when the program cannot start, so every gate that routes
through it must decide what to SAY. Reporters keep their own spawn -- since
2026-10-13 ``run_bounded``, the bounded one -- under a ``# spawn: ok <reason>``
declaration on the call line or the line above.

The bounded spawn, ``_json_safe.run_bounded``, is ``subprocess.run`` whose
``timeout`` holds on Windows too, where ``run`` kills only the child and then
waits on any grandchild holding its pipe (``tests/test_bounded_spawn.py``).
``spawn_checked`` is built on it, and every other timed spawn under
``tools/cc`` calls it, so a raw ``subprocess.*`` call carrying a ``timeout``
(or the ``**`` splat that can carry one) lives only inside it.

The populations are derived, never hand-listed: an AST walk over every
``subprocess.run`` / ``Popen`` / ``call`` / ``check_output`` / ``check_call``
and every ``spawn_checked(`` and ``run_bounded(`` call. FLOOR: the 27 hook
sites the walk found at first execution (28 by grep at authoring; the walk is
the number that counts), and the 53 timed sites under ``tools/cc`` at the
reroute (48 ``subprocess.run`` and 5 ``spawn_checked``), so a walk that finds
fewer broke or a site vanished without the floor being lowered on purpose --
the first floor caught the reroute itself, 27 read as 5 until the walk learnt
the bounded spawn. This pins the chokepoint contract and prevents the drift it
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
TOOLS_CC = HOOKS_DIR.parent
SPAWN_FLOOR = 27
TIMED_FLOOR = 53
SPAWN_ATTRS = frozenset({"run", "Popen", "call", "check_output", "check_call"})
PRAGMA = "# spawn: ok"
#: Where a raw timed spawn may stand: inside ``run_bounded`` -- the bounded
#: spawn itself, and the fallback of that name a module keeps for a load where
#: ``_json_safe`` is not importable, which hands its call to ``subprocess.run``
#: -- and the bounded spawn's tree kill.
BOUNDED_FUNCTION = "run_bounded"
TREE_KILL = ("_json_safe.py", "_end_tree")


def _load_hook_utils():
    spec = importlib.util.spec_from_file_location("hook_utils_for_spawn", str(HOOKS_DIR / "_hook_utils.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hook_utils_for_spawn"] = mod
    spec.loader.exec_module(mod)
    return mod


def _named(fn: ast.expr, name: str) -> bool:
    """``fn`` calls ``name`` by bare name or as an attribute (``_hook_utils.name``)."""
    return (isinstance(fn, ast.Attribute) and fn.attr == name) or (isinstance(fn, ast.Name) and fn.id == name)


def _enclosing_functions(tree: ast.AST) -> dict[int, str]:
    """Each node's innermost enclosing function name, keyed by ``id``."""
    owner: dict[int, str] = {}

    def visit(node: ast.AST, name: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else name
            owner[id(child)] = inner
            visit(child, inner)

    visit(tree, "<module>")
    return owner


def spawn_sites(root: Path = HOOKS_DIR, pattern: str = "*.py") -> list[dict]:
    """Every raw ``subprocess.*`` call (and ``.communicate(timeout=...)``), and
    every ``spawn_checked(`` and ``run_bounded(`` call, under ``root``."""
    out: list[dict] = []
    for f in sorted(root.glob(pattern)):
        src = f.read_text(encoding="utf-8")
        lines = src.splitlines()
        tree = ast.parse(src)
        owner = _enclosing_functions(tree)
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
            keywords = {k.arg for k in node.keywords}
            raw = (
                isinstance(fn, ast.Attribute) and fn.attr in SPAWN_ATTRS
                and isinstance(fn.value, ast.Name) and fn.value.id == "subprocess"
            ) or (
                isinstance(fn, ast.Attribute) and fn.attr in {"system", "popen"}
                and isinstance(fn.value, ast.Name) and fn.value.id == "os"
            ) or (isinstance(fn, ast.Name) and fn.id in bare_spawns) or (
                isinstance(fn, ast.Attribute) and fn.attr == "communicate" and "timeout" in keywords
            )
            routed = _named(fn, "spawn_checked")
            bounded = _named(fn, "run_bounded")
            if not (raw or routed or bounded):
                continue
            declared = any(PRAGMA in lines[i] for i in (node.lineno - 1, node.lineno - 2) if 0 <= i < len(lines))
            out.append({
                "file": f.relative_to(root).as_posix(), "lineno": node.lineno, "raw": raw,
                "routed": routed, "bounded": bounded, "declared": declared,
                "timed": "timeout" in keywords or None in keywords, "function": owner.get(id(node), "<module>"),
            })
    return out


class TestSpawnChokepoint:
    def test_the_walk_finds_the_population(self):
        n = len(spawn_sites())
        assert n >= SPAWN_FLOOR, (
            f"{n} spawn sites, below the floor {SPAWN_FLOOR} recorded at first execution: "
            "the walk broke, or a site was deleted -- lower the floor on purpose, naming it"
        )

    def test_every_spawn_is_the_chokepoint_or_declared(self):
        undeclared = [s for s in spawn_sites() if (s["raw"] or s["bounded"]) and not s["declared"]]
        chokepoint = [s for s in undeclared if s["file"] == "_hook_utils.py"]
        assert [(s["function"], s["bounded"]) for s in chokepoint] == [("spawn_checked", True)], (
            "exactly one undeclared spawn belongs in _hook_utils.py -- the chokepoint's own, "
            f"spawn_checked onto run_bounded; found {chokepoint}"
        )
        stray = [s for s in undeclared if s["file"] != "_hook_utils.py"]
        assert not stray, (
            "spawns outside the chokepoint must route through _hook_utils.spawn_checked "
            "(a gate) or carry `# spawn: ok <reason>` on the call line or the line above "
            "(a reporter):\n  "
            + "\n  ".join(f"{s['file']}:{s['lineno']}" for s in stray)
        )

    def test_the_gates_route(self):
        routed = {(s["file"]) for s in spawn_sites() if s["routed"]}
        assert "stop_gate.py" in routed, "the stop gate's spawns (override, pytest, finalize) route through the chokepoint"
        raw_stop = [s for s in spawn_sites() if (s["raw"] or s["bounded"]) and s["file"] == "stop_gate.py"]
        assert not raw_stop, f"stop_gate.py still spawns outside the chokepoint: {raw_stop}"


class TestEveryTimedSpawnIsBounded:
    """Under all of ``tools/cc`` (the hooks and the scripts beside them), a
    spawn with a ``timeout`` goes through ``run_bounded`` or ``spawn_checked``;
    a raw one stands only inside the bounded spawn itself."""

    def test_the_timed_population_holds_its_floor(self):
        timed = [s for s in spawn_sites(TOOLS_CC, "**/*.py") if (s["bounded"] or s["routed"]) and s["timed"]]
        assert len(timed) >= TIMED_FLOOR, (
            f"{len(timed)} timed spawns through run_bounded or spawn_checked under tools/cc, below "
            f"the floor {TIMED_FLOOR} recorded at the reroute: the walk broke, or sites went back "
            "to subprocess.run -- lower the floor on purpose, naming it"
        )

    def test_no_raw_spawn_carries_a_timeout_outside_the_bounded_spawn(self):
        stray = [
            s for s in spawn_sites(TOOLS_CC, "**/*.py")
            if s["raw"] and s["timed"] and s["function"] != BOUNDED_FUNCTION
            and (s["file"], s["function"]) != TREE_KILL
        ]
        assert not stray, (
            "a raw subprocess call with a timeout (or the ** splat that can carry one) "
            "waits on any grandchild holding its pipe on Windows, past its cap; call "
            "run_bounded (from _json_safe, or _hook_utils in a hook) instead:\n  "
            + "\n  ".join(f"tools/cc/{s['file']}:{s['lineno']} in {s['function']}" for s in stray)
        )

    def test_the_walk_reads_each_shape_it_rules_on(self, tmp_path):
        """The walk's own control, on a planted tree: a raw timed spawn, a raw
        splat, a timed ``communicate`` and an untimed raw spawn are each read
        as what they are, a bounded call through a module is read as bounded,
        and the enclosing function is the one the home rule keys on."""
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "planted.py").write_bytes((
            "import subprocess\nimport _hook_utils\n"
            "def probe(**kw):\n"
            "    subprocess.run(['git'], timeout=5)\n"
            "    subprocess.run(['git'], **kw)\n"
            "    subprocess.Popen(['git']).communicate(timeout=5)\n"
            "    subprocess.run(['git'])\n"
            "    _hook_utils.run_bounded(['git'], timeout=5)\n"
        ).encode("ascii"))
        got = [(s["lineno"], s["raw"], s["bounded"], s["timed"], s["function"])
               for s in sorted(spawn_sites(tmp_path, "**/*.py"), key=lambda s: (s["lineno"], s["timed"]))]
        assert got == [
            (4, True, False, True, "probe"),
            (5, True, False, True, "probe"),
            (6, True, False, False, "probe"),  # the Popen: untimed itself
            (6, True, False, True, "probe"),  # its communicate(timeout=)
            (7, True, False, False, "probe"),
            (8, False, True, True, "probe"),
        ], got


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
        got = hu.spawn_checked(["npm", "--version"], root=tmp_path, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=45)
        assert not isinstance(got, hu.SpawnFailure), got
        assert got.returncode == 0, got.stderr
