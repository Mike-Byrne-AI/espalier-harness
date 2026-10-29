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
the number that counts), and the 50 timed sites under ``tools/cc`` at the
reroute (45 ``subprocess.run`` and 5 ``spawn_checked``; the CI guard's three
stay on ``subprocess.run``, ``STANDALONE_GUARD`` says why), so a walk that finds
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
from tests._platform_standin import as_os
from tests._live_tree import checkout_glob

HOOKS_DIR = Path(__file__).resolve().parents[1] / "tools" / "cc" / "hooks"
TOOLS_CC = HOOKS_DIR.parent
SPAWN_FLOOR = 27
TIMED_FLOOR = 50
SPAWN_ATTRS = frozenset({"run", "Popen", "call", "check_output", "check_call"})
PRAGMA = "# spawn: ok"
#: Where a raw timed spawn may stand: the bounded spawn and its tree kill...
BOUNDED_HOME = ("_json_safe.py", frozenset({"run_bounded", "_end_tree"}))
#: ...a ``run_bounded`` a module defines in its ``except ImportError`` handler,
#: the fallback for a load where ``_json_safe`` is not importable (a def of
#: that name anywhere else is no exemption)...
FALLBACK_NAME = "run_bounded"
#: ...and the CI guard, which imports no sibling: CI runs it from the pull
#: request's own tree, and ``_json_safe.py`` is not a gated path, so a pull
#: request could rewrite a spawn the guard imported (2026-10-13 review). Its
#: git reads are local, and its home is the Linux cell.
STANDALONE_GUARD = "ci_guard.py"


def _load_hook_utils():
    spec = importlib.util.spec_from_file_location("hook_utils_for_spawn", str(HOOKS_DIR / "_hook_utils.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hook_utils_for_spawn"] = mod
    spec.loader.exec_module(mod)
    return mod


def _named(fn: ast.expr, name: str) -> bool:
    """``fn`` calls ``name`` by bare name or as an attribute (``_hook_utils.name``)."""
    return (isinstance(fn, ast.Attribute) and fn.attr == name) or (isinstance(fn, ast.Name) and fn.id == name)


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    caught = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(isinstance(n, ast.Name) and n.id in {"ImportError", "ModuleNotFoundError"} for n in caught)


def _enclosing_functions(tree: ast.AST) -> dict[int, tuple[str, bool]]:
    """Each node's innermost enclosing function, keyed by ``id``: its name, and
    whether it is defined directly in an ``except ImportError`` handler."""
    owner: dict[int, tuple[str, bool]] = {}

    def visit(node: ast.AST, ctx: tuple[str, bool]) -> None:
        fallbacks = (
            {id(s) for s in node.body if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if isinstance(node, ast.ExceptHandler) and _catches_import_error(node) else set()
        )
        for child in ast.iter_child_nodes(node):
            inner = ((child.name, id(child) in fallbacks)
                     if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else ctx)
            owner[id(child)] = inner
            visit(child, inner)

    visit(tree, ("<module>", False))
    return owner


def spawn_sites(root: Path = HOOKS_DIR, pattern: str = "*.py") -> list[dict]:
    """Every raw ``subprocess.*`` call (and a timed ``.communicate``), and
    every ``spawn_checked(``, ``run_bounded(`` and ``run_no_stdin(`` call, under
    ``root``. ``run_no_stdin`` is the engine's ``run_bounded`` with the child's
    stdin closed (DEF-928), so it reads as bounded; ``keywords`` names what the
    call passes and ``values`` the source of its ``stdin=`` and ``input=``, for
    the engine's stdin census."""
    out: list[dict] = []
    for f in sorted(checkout_glob(root, pattern)):
        src = f.read_text(encoding="utf-8")
        lines = src.splitlines()
        tree = ast.parse(src)
        owner = _enclosing_functions(tree)
        # `from subprocess import run` binds a bare name the attribute form
        # would miss; so would `os.system` / `os.popen` (the 2-A review), and
        # `import subprocess as sp` a module name (the 2026-10-13 review).
        bare_spawns = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "subprocess"
            for alias in node.names if alias.name in SPAWN_ATTRS
        }
        modules = {"subprocess"} | {
            alias.asname
            for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names if alias.name == "subprocess" and alias.asname
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            keywords = {k.arg for k in node.keywords}
            # communicate(input, timeout): a positional timeout is a timeout.
            communicates = isinstance(fn, ast.Attribute) and fn.attr == "communicate" and (
                "timeout" in keywords or len(node.args) >= 2)
            raw = (
                isinstance(fn, ast.Attribute) and fn.attr in SPAWN_ATTRS
                and isinstance(fn.value, ast.Name) and fn.value.id in modules
            ) or (
                isinstance(fn, ast.Attribute) and fn.attr in {"system", "popen"}
                and isinstance(fn.value, ast.Name) and fn.value.id == "os"
            ) or (isinstance(fn, ast.Name) and fn.id in bare_spawns) or communicates
            routed = _named(fn, "spawn_checked")
            no_stdin = _named(fn, "run_no_stdin")
            bounded = _named(fn, "run_bounded") or no_stdin
            if not (raw or routed or bounded):
                continue
            declared = any(PRAGMA in lines[i] for i in (node.lineno - 1, node.lineno - 2) if 0 <= i < len(lines))
            function, fallback = owner.get(id(node), ("<module>", False))
            out.append({
                "file": f.relative_to(root).as_posix(), "lineno": node.lineno, "raw": raw,
                "routed": routed, "bounded": bounded, "no_stdin": no_stdin, "declared": declared,
                "keywords": sorted(k for k in keywords if k),
                "values": {k.arg: ast.unparse(k.value) for k in node.keywords if k.arg in ("stdin", "input")},
                "timed": "timeout" in keywords or None in keywords or communicates,
                "function": function, "fallback": fallback,
            })
    return out


def _bounded_by_design(site: dict) -> bool:
    """A raw timed spawn the timed-spawn rule lets stand (the three homes above)."""
    home_file, home_functions = BOUNDED_HOME
    return (
        (site["file"] == home_file and site["function"] in home_functions)
        or (site["function"] == FALLBACK_NAME and site["fallback"])
        or site["file"] == STANDALONE_GUARD
    )


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
        stray = [s for s in spawn_sites(TOOLS_CC, "**/*.py") if s["raw"] and s["timed"] and not _bounded_by_design(s)]
        assert not stray, (
            "a raw subprocess call with a timeout (or the ** splat that can carry one) "
            "waits on any grandchild holding its pipe on Windows, past its cap; call "
            "run_bounded (from _json_safe, or _hook_utils in a hook) instead:\n  "
            + "\n  ".join(f"tools/cc/{s['file']}:{s['lineno']} in {s['function']}" for s in stray)
        )

    def test_the_walk_reads_each_shape_it_rules_on(self, tmp_path):
        """The walk's own control, on a planted tree: a raw timed spawn, a raw
        splat, a timed ``communicate`` (keyword or positional), an untimed raw
        spawn and a spawn through an aliased module are each read as what they
        are, a bounded call through a module is read as bounded, and the
        enclosing function is the one the home rule keys on."""
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "planted.py").write_bytes((
            "import subprocess\nimport subprocess as sp\nimport _hook_utils\n"
            "def probe(**kw):\n"
            "    subprocess.run(['git'], timeout=5)\n"
            "    subprocess.run(['git'], **kw)\n"
            "    subprocess.Popen(['git']).communicate(timeout=5)\n"
            "    subprocess.run(['git'])\n"
            "    _hook_utils.run_bounded(['git'], timeout=5)\n"
            "    sp.run(['git'], timeout=5)\n"
            "    subprocess.Popen(['git']).communicate(None, 5)\n"
        ).encode("ascii"))
        got = [(s["lineno"], s["raw"], s["bounded"], s["timed"], s["function"])
               for s in sorted(spawn_sites(tmp_path, "**/*.py"), key=lambda s: (s["lineno"], s["timed"]))]
        assert got == [
            (5, True, False, True, "probe"),
            (6, True, False, True, "probe"),
            (7, True, False, False, "probe"),  # the Popen: untimed itself
            (7, True, False, True, "probe"),  # its communicate(timeout=)
            (8, True, False, False, "probe"),
            (9, False, True, True, "probe"),
            (10, True, False, True, "probe"),  # through the alias
            (11, True, False, False, "probe"),
            (11, True, False, True, "probe"),  # communicate(input, timeout)
        ], got

    def test_only_the_three_homes_may_hold_a_raw_timed_spawn(self, tmp_path):
        """The exemption is the bounded spawn's own two functions, a fallback
        defined in an ``except ImportError`` handler, and the CI guard: a def
        named ``run_bounded`` anywhere else is no home."""
        planted = {
            "_json_safe.py": "import subprocess\ndef run_bounded(args, **kw):\n    return subprocess.run(args, **kw)\n",
            "fallback.py": ("import subprocess\ntry:\n    from _json_safe import run_bounded\nexcept ImportError:\n"
                            "    def run_bounded(args, **kw):\n        return subprocess.run(args, **kw)\n"),
            "copied.py": "import subprocess\ndef run_bounded(args, **kw):\n    return subprocess.run(args, **kw)\n",
            "ci_guard.py": "import subprocess\ndef _git():\n    return subprocess.run(['git'], timeout=30)\n",
            "other.py": "import subprocess\ndef _git():\n    return subprocess.run(['git'], timeout=30)\n",
        }
        for name, src in planted.items():
            (tmp_path / name).write_bytes(src.encode("ascii"))
        stray = sorted(s["file"] for s in spawn_sites(tmp_path, "*.py")
                       if s["raw"] and s["timed"] and not _bounded_by_design(s))
        assert stray == ["copied.py", "other.py"], stray


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
        from tests._stubs import write_stub
        script = tmp_path / "scripts" / "t.sh"
        script.parent.mkdir()
        write_stub(script, "#!/bin/sh\nexit 0\n")
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


def _load_json_safe():
    spec = importlib.util.spec_from_file_location("json_safe_for_spawn", str(TOOLS_CC / "_json_safe.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["json_safe_for_spawn"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestTheWindowsBranchOnEveryOS:
    """``run_bounded``'s Windows branch, driven on every OS: the required cells
    are Linux, where the call is ``subprocess.run``, so the branch runs here
    against a stand-in ``Popen`` with the platform read as ``win32``, and the
    tree kill recorded rather than made (``tests/test_bounded_spawn.py`` drives
    the real one on a Windows host)."""

    @pytest.fixture
    def windows(self, monkeypatch):
        import subprocess

        js = _load_json_safe()
        calls: list[tuple] = []

        class StandInPopen:
            plan: list = []

            def __init__(self, args, **kw):
                calls.append(("popen", args, kw))
                self.args, self.pid, self.returncode = args, 4242, None

            def communicate(self, input=None, timeout=None):
                calls.append(("communicate", input, timeout))
                step = StandInPopen.plan.pop(0)
                if isinstance(step, BaseException):
                    raise step
                if step == "timeout":
                    raise subprocess.TimeoutExpired(self.args, timeout)
                self.returncode = step
                return ("out", "err")

            def wait(self, timeout=None):
                calls.append(("wait", timeout))
                return self.returncode if self.returncode is not None else 1

            def kill(self):
                calls.append(("kill",))

        as_os(monkeypatch, "windows", os_name=False)
        monkeypatch.setattr(subprocess, "Popen", StandInPopen)
        monkeypatch.setattr(js, "_end_tree", lambda proc, end: calls.append(("end_tree", proc.pid)))
        return js, StandInPopen, calls

    def test_at_the_timeout_the_tree_ends_then_the_pipes_drain_then_the_child_is_reaped(self, windows):
        import subprocess

        js, popen, calls = windows
        popen.plan = ["timeout", 0]
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            js.run_bounded(["git", "fetch"], timeout=3, capture_output=True, text=True, encoding="utf-8")
        assert [c[0] for c in calls] == ["popen", "communicate", "end_tree", "communicate", "wait"], calls
        assert calls[0][2]["stdout"] is subprocess.PIPE and calls[0][2]["stderr"] is subprocess.PIPE
        assert calls[1][2] == 3 and calls[3][2] <= js.SPAWN_KILL_GRACE_SECONDS, calls
        assert (caught.value.stdout, caught.value.stderr) == ("out", "err"), "the drain's output rides the exception"

    def test_a_drain_the_tree_kill_cannot_finish_still_returns_within_the_grace(self, windows):
        import subprocess

        js, popen, calls = windows
        popen.plan = ["timeout", "timeout"]
        with pytest.raises(subprocess.TimeoutExpired):
            js.run_bounded(["shim.bat"], timeout=3, capture_output=True)
        assert [c[0] for c in calls] == ["popen", "communicate", "end_tree", "communicate", "wait"], calls

    def test_check_and_the_argument_errors_are_runs_own(self, windows):
        import subprocess

        js, popen, calls = windows
        popen.plan = [2]
        with pytest.raises(subprocess.CalledProcessError) as caught:
            js.run_bounded(["git"], timeout=3, capture_output=True, check=True)
        assert (caught.value.returncode, caught.value.output) == (2, "out")
        with pytest.raises(ValueError, match="stdin and input"):
            js.run_bounded(["git"], timeout=3, input="x", stdin=subprocess.PIPE)
        with pytest.raises(ValueError, match="capture_output"):
            js.run_bounded(["git"], timeout=3, capture_output=True, stdout=subprocess.PIPE)

    def test_an_interrupt_mid_call_ends_the_tree_and_goes_on(self, windows):
        js, popen, calls = windows
        popen.plan = [KeyboardInterrupt()]
        with pytest.raises(KeyboardInterrupt):
            js.run_bounded(["git"], timeout=3)
        assert [c[0] for c in calls] == ["popen", "communicate", "end_tree", "wait"], calls

    def test_a_stand_in_run_is_honoured_even_a_wrapped_one(self, windows, monkeypatch):
        """A test's fake ``subprocess.run`` is called, never bypassed for a real
        ``Popen`` -- a ``functools.wraps`` spy included, which copies the
        name and module of the real one but not its code."""
        import functools
        import subprocess

        js, popen, calls = windows
        seen: list = []

        @functools.wraps(subprocess.run)
        def spy(args, **kw):
            seen.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(subprocess, "run", spy)
        js.run_bounded(["git"], timeout=3)
        assert seen == [["git"]] and calls == [], (seen, calls)


class TestTheFallbacksStandWhereTheBoundedSpawnCannotBeImported:
    """A module that imports ``run_bounded`` behind ``except ImportError``
    (copied alone, or loaded by path with no ``tools/cc`` on ``sys.path``)
    takes a fallback that reads ``subprocess.run`` when called, so a replaced
    ``run`` is honoured there as ``run_bounded`` honours it. The population is
    every fallback the census finds."""

    FALLBACKS = sorted({s["file"] for s in spawn_sites(TOOLS_CC, "**/*.py") if s["fallback"]})

    def test_the_census_finds_the_fallbacks(self):
        assert len(self.FALLBACKS) >= 5, self.FALLBACKS

    @pytest.mark.parametrize("rel", FALLBACKS)
    def test_a_load_without_the_bounded_spawn_calls_a_late_bound_run(self, rel, monkeypatch):
        import subprocess
        import types

        stub = types.ModuleType("_json_safe")  # the helper as it was before run_bounded
        monkeypatch.setitem(sys.modules, "_json_safe", stub)
        monkeypatch.syspath_prepend(str((TOOLS_CC / rel).parent))
        name = "fallback_" + rel.replace("/", "_").removesuffix(".py")
        spec = importlib.util.spec_from_file_location(name, str(TOOLS_CC / rel))
        mod = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, mod)
        spec.loader.exec_module(mod)
        assert mod.run_bounded.__module__ == name, "the import did not fall back"
        seen: list = []
        monkeypatch.setattr(subprocess, "run", lambda args, **kw: seen.append((args, kw)) or "ran")
        assert mod.run_bounded(["git"], timeout=5) == "ran"
        assert seen == [(["git"], {"timeout": 5, "input": None, "capture_output": False, "check": False})], seen


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
