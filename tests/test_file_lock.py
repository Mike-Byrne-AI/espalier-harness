"""File locks that hold on every OS, and the appends that rely on them.

The harness serializes its read-modify-write windows and its log appends with
one primitive, ``lock_file`` / ``unlock_file``: ``fcntl.flock`` on POSIX and
``LockFileEx`` on Windows. Two copies exist because the layers cannot import
each other -- ``tools/cc/_json_safe.py`` for the hooks and the standalone CLIs,
``espalier/_atomic_io.py`` for the engine -- and
``tests/test_surface_contract.py::test_lock_file_two_copy_parity`` holds them
equal.

Before the primitive, every site imported ``fcntl`` and ran UNLOCKED on Windows
as a "documented limit". Driven on a Windows host (2026-10-02): eight processes
incrementing one counter 25 times each left it at 14 of 200, and ten writers
appending 200 lines each kept 1,705 to 1,778 of 2,000 intact with 29 to 47 torn
lines. Parallel hooks and subagents in one session are concurrent writers, so
this was not a two-sessions-in-one-repo corner.

Every child here waits on a start barrier so the writers overlap, and runs with
``CLAUDE_PROJECT_DIR`` pinned to ``tmp_path`` and every other ``CLAUDE_*``
variable stripped (docs/SHARP_EDGES.md "Subprocesses Inheriting
CLAUDE_PROJECT_DIR Mis-Route Harness Scripts").
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_CC = REPO_ROOT / "tools" / "cc"
HOOKS_DIR = TOOLS_CC / "hooks"

#: How each copy of the primitive is imported inside a child process.
_PRIMITIVE_IMPORT = {
    "tools_cc": f"sys.path.insert(0, {str(TOOLS_CC)!r})\nfrom _json_safe import lock_file, unlock_file",
    "engine": f"sys.path.insert(0, {str(REPO_ROOT)!r})\nfrom espalier._atomic_io import lock_file, unlock_file",
}


def _child_env(tmp_path: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    env["ESPALIER_AUDIT_DIR"] = str(tmp_path / "audit")
    env.pop("ESPALIER_MAINTENANCE_MODE", None)
    return env


#: Every wait here stays well under pytest-timeout's 60 s: under the thread
#: method (Windows) a test that reaches it ends the WHOLE run, so a hang must
#: fail this test on its own clock first (failure-mode review).
_CHILD_DEADLINE_S = 30


def _wait_for(path: Path, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.02)
    return path.exists()


def _load_parent_copy(copy: str):
    if copy == "engine":
        from espalier import _atomic_io
        return _atomic_io.lock_file, _atomic_io.unlock_file
    sys.path.insert(0, str(TOOLS_CC))
    try:
        import _json_safe  # type: ignore
        return _json_safe.lock_file, _json_safe.unlock_file
    finally:
        sys.path.pop(0)


def _spawn_locker(tmp_path: Path, copy: str, lock_path: Path, *, shared: bool, tag: str) -> subprocess.Popen:
    """A child that opens the lock file, announces it is about to lock (the
    statement right before the call), takes the lock, announces it holds it,
    and releases at once."""
    code = textwrap.dedent(f"""
        import sys
        from pathlib import Path
        {{imp}}
        locking, acquired = Path({str(tmp_path / (tag + '.locking'))!r}), Path({str(tmp_path / (tag + '.acquired'))!r})
        with open({str(lock_path)!r}, "a+", encoding="utf-8") as fh:
            locking.write_text("1", encoding="utf-8")
            lock_file(fh, shared={shared!r})
            acquired.write_text("1", encoding="utf-8")
            unlock_file(fh)
    """).replace("{imp}", _PRIMITIVE_IMPORT[copy])  # dedented first: the block goes in at column 0
    return subprocess.Popen([sys.executable, "-c", code], env=_child_env(tmp_path),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")


@pytest.mark.parametrize("copy", sorted(_PRIMITIVE_IMPORT))
class TestLockPrimitiveAcrossProcesses:
    """The three properties the sites rely on, observed from a second process.
    A child announces ``locking`` in the statement before it asks for the lock,
    so "not acquired half a second later" is a wait on the lock, not a slow
    interpreter start (code review: the earlier marker came before the import)."""

    def _hold_then_release(self, tmp_path, copy, *, parent_shared, child_shared, child_should_wait):
        lock_file, unlock_file = _load_parent_copy(copy)
        lock_path = tmp_path / ".probe.lock"
        with open(lock_path, "a+", encoding="utf-8") as fh:
            lock_file(fh, shared=parent_shared)
            child = _spawn_locker(tmp_path, copy, lock_path, shared=child_shared, tag="child")
            try:
                assert _wait_for(tmp_path / "child.locking"), child.communicate(timeout=_CHILD_DEADLINE_S)
                if child_should_wait:
                    time.sleep(0.5)
                    assert not (tmp_path / "child.acquired").exists(), (
                        "the child took the lock while the parent held it")
                else:
                    assert _wait_for(tmp_path / "child.acquired"), (
                        "the child could not take a shared lock beside the parent's")
            finally:
                unlock_file(fh)
        out, err = child.communicate(timeout=_CHILD_DEADLINE_S)
        assert child.returncode == 0, err
        assert (tmp_path / "child.acquired").exists()

    def test_an_exclusive_lock_excludes_another_process(self, tmp_path, copy):
        self._hold_then_release(tmp_path, copy, parent_shared=False, child_shared=False,
                                child_should_wait=True)

    def test_shared_locks_coexist(self, tmp_path, copy):
        self._hold_then_release(tmp_path, copy, parent_shared=True, child_shared=True,
                                child_should_wait=False)

    def test_an_exclusive_lock_waits_for_a_shared_one(self, tmp_path, copy):
        self._hold_then_release(tmp_path, copy, parent_shared=True, child_shared=False,
                                child_should_wait=True)

    def test_a_reader_of_the_locked_file_is_not_blocked(self, tmp_path, copy):
        # append_audit locks the log it appends to. Windows byte-range locks are
        # mandatory for I/O on the locked range, so the primitive locks a range
        # far past any data: a reader of the file must still read it.
        lock_file, unlock_file = _load_parent_copy(copy)
        log = tmp_path / "audit.log"
        log.write_text("first line\n", encoding="utf-8")
        with open(log, "a", encoding="utf-8") as fh:
            lock_file(fh)
            try:
                code = f"from pathlib import Path; print(Path({str(log)!r}).read_text(encoding='utf-8'), end='')"
                r = subprocess.run([sys.executable, "-c", code], env=_child_env(tmp_path),
                                   capture_output=True, text=True, encoding="utf-8", timeout=30)
            finally:
                unlock_file(fh)
        assert r.returncode == 0, r.stderr
        assert r.stdout == "first line\n"


#: Each append site, called from a child: (import lines, one call writing token T).
_APPEND_SITES = {
    "append_jsonl": (
        f"sys.path.insert(0, {str(HOOKS_DIR)!r})\nimport _hook_utils",
        "_hook_utils._append_jsonl(STATE, 'probe.jsonl', {'token': T})",
    ),
    "born_weak": (
        f"sys.path.insert(0, {str(HOOKS_DIR)!r})\nimport _born_weak",
        "_born_weak.bw_log_observation(ROOT, {'token': T})",
    ),
    "append_audit": (
        f"sys.path.insert(0, {str(HOOKS_DIR)!r})\nimport _integrity",
        "assert _integrity.append_audit(ROOT, {'event_type': 'probe', 'details': {'token': T}}, quiet=True)",
    ),
}


def _tokens_in(record: object) -> list[str]:
    """Every exact value under a ``token`` key, at any depth (``append_audit``
    nests it under ``details``)."""
    found: list[str] = []
    if isinstance(record, dict):
        for key, value in record.items():
            if key == "token" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_tokens_in(value))
    elif isinstance(record, list):
        for value in record:
            found.extend(_tokens_in(value))
    return found


def _append_logs(tmp_path: Path, root: Path, site: str) -> list[Path]:
    """Where each site's lines land: ``_append_jsonl`` under the STATE dir the
    child passes, ``bw_log_observation`` under ``ROOT``'s state dir, and
    ``append_audit`` in ``ESPALIER_AUDIT_DIR`` (one file per UTC day)."""
    if site == "append_jsonl":
        return [root.parent / ".espalier-state" / "probe.jsonl"]
    if site == "born_weak":
        return [root / ".espalier-state" / "born_weak_observations.jsonl"]
    return sorted((tmp_path / "audit").glob("*.log"))


@pytest.mark.parametrize("site", sorted(_APPEND_SITES))
def test_concurrent_appends_keep_every_line_whole(tmp_path, site):
    """Eight processes append forty lines each to one log through the site's own
    function: every line lands, and every line parses."""
    workers, each = 8, 40
    imports, call = _APPEND_SITES[site]
    go = tmp_path / "go"
    root = tmp_path / "repo"
    root.mkdir()
    code = textwrap.dedent("""
        import sys, time
        from pathlib import Path
        {imports}
        ROOT = Path(sys.argv[1]); STATE = ROOT.parent / ".espalier-state"
        W = int(sys.argv[2]); GO = Path(sys.argv[3])
        Path(sys.argv[3] + f".ready{{W}}").write_text("1", encoding="utf-8")
        deadline = time.monotonic() + {deadline}
        while not GO.exists():
            if time.monotonic() > deadline:
                sys.exit(3)  # the parent died or never opened the barrier
            time.sleep(0.005)
        for i in range({each}):
            T = f"probe-w{{W}}-i{{i}}"
            {call}
    """).format(imports=imports, call=call, each=each,  # dedented first: imports go in at column 0
                deadline=_CHILD_DEADLINE_S)
    procs = [subprocess.Popen([sys.executable, "-c", code, str(root), str(w), str(go)],
                              env=_child_env(tmp_path), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, encoding="utf-8")
             for w in range(workers)]
    try:
        for w in range(workers):
            assert _wait_for(Path(f"{go}.ready{w}")), procs[w].communicate(timeout=_CHILD_DEADLINE_S)
        go.write_text("1", encoding="utf-8")
        for p in procs:
            out, err = p.communicate(timeout=_CHILD_DEADLINE_S)
            assert p.returncode == 0, err
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
    tokens, torn = [], []
    for log in _append_logs(tmp_path, root, site):
        for raw in log.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(raw)
            except ValueError:
                torn.append(raw[:80])
                continue
            tokens.extend(_tokens_in(record))
    # Compared as exact values: a substring match let `probe-w0-i1` hide inside
    # `probe-w0-i10`..`i19`, blinding the test to 24 of its 320 lines (review).
    expected = {f"probe-w{w}-i{i}" for w in range(workers) for i in range(each)}
    assert not torn, f"{len(torn)} torn lines, first: {torn[:3]}"
    assert len(tokens) == len(set(tokens)), "a line was written twice"
    missing = expected - set(tokens)
    assert not missing, f"{len(missing)} of {len(expected)} appended lines were lost: {sorted(missing)[:5]}"
    assert set(tokens) == expected


def test_the_speedbump_cap_admits_exactly_cap_concurrent_firings(tmp_path):
    """``_speedbump._locked_check_and_increment`` compares and increments under
    the lock, so eight PreToolUse hooks released together fire exactly ``cap``
    times. Unlocked (Windows until 2026-10-02) two hooks could read the same
    count and both fire, worsening the storm the cap exists to stop."""
    workers, cap = 8, 4
    go = tmp_path / "go"
    state = tmp_path / ".espalier-state"
    code = textwrap.dedent(f"""
        import sys, time
        from pathlib import Path
        sys.path.insert(0, {str(HOOKS_DIR)!r})
        import _speedbump
        W, GO = int(sys.argv[1]), Path(sys.argv[2])
        Path(sys.argv[2] + f".ready{{W}}").write_text("1", encoding="utf-8")
        deadline = time.monotonic() + {_CHILD_DEADLINE_S}
        while not GO.exists():
            if time.monotonic() > deadline:
                sys.exit(3)  # the parent died or never opened the barrier
            time.sleep(0.005)
        fired = _speedbump._locked_check_and_increment(Path({str(state)!r}), {cap})
        print("FIRED" if fired else "SUPPRESSED")
    """)
    procs = [subprocess.Popen([sys.executable, "-c", code, str(w), str(go)],
                              env=_child_env(tmp_path), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, encoding="utf-8")
             for w in range(workers)]
    try:
        for w in range(workers):
            assert _wait_for(Path(f"{go}.ready{w}")), procs[w].communicate(timeout=_CHILD_DEADLINE_S)
        go.write_text("1", encoding="utf-8")
        outcomes = []
        for p in procs:
            out, err = p.communicate(timeout=_CHILD_DEADLINE_S)
            assert p.returncode == 0, err
            outcomes.append(out.strip())
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
    assert outcomes.count("FIRED") == cap, outcomes


#: The only places shipped code may reach a platform lock: ``fcntl`` in the
#: primitive's two copies and the hook layer's guarded fallback for a
#: ``_json_safe.py`` that predates it; ``msvcrt`` / ``LockFileEx`` /
#: ``UnlockFileEx`` in the two copies' Windows arm. Asserted equal to the
#: derived census both ways (the ``_REPLACE_WRITERS`` shape in test_atomic_io),
#: so a new lock site that imports ``fcntl`` itself -- and so runs unlocked on
#: Windows -- reds here, and so does a site that reaches for ``msvcrt.locking``
#: directly: it would lock a different byte than the primitive and exclude
#: nothing (failure-mode review). A stale entry reds too.
_LOCK_PRIMITIVE_ALLOWED: frozenset[tuple[str, str]] = frozenset({
    ("tools/cc/_json_safe.py", "lock_file"),
    ("tools/cc/_json_safe.py", "unlock_file"),
    ("tools/cc/_json_safe.py", "_lock_byte"),
    ("espalier/_atomic_io.py", "lock_file"),
    ("espalier/_atomic_io.py", "unlock_file"),
    ("espalier/_atomic_io.py", "_lock_byte"),
    ("tools/cc/hooks/_hook_utils.py", "lock_file"),
    ("tools/cc/hooks/_hook_utils.py", "unlock_file"),
})
_LOCK_MODULES = frozenset({"fcntl", "msvcrt"})
_LOCK_CALLS = frozenset({"LockFileEx", "UnlockFileEx"})


def lock_primitive_sites(root: Path) -> set[tuple[str, str]]:
    """Every ``(module, innermost function)`` under ``espalier/`` (minus the
    ``_vendor/`` byte mirror) and ``tools/cc/`` that imports or names ``fcntl``
    or ``msvcrt`` (an ``import``, a bare name, or a string handed to
    ``__import__`` / ``import_module``) or reaches ``LockFileEx`` /
    ``UnlockFileEx``."""
    import ast

    found: set[tuple[str, str]] = set()
    for sub in ("espalier", "tools/cc"):
        for py in sorted((root / sub).rglob("*.py")):
            rel = py.relative_to(root).as_posix()
            if rel.startswith("espalier/_vendor/"):
                continue
            tree = ast.parse(py.read_text(encoding="utf-8"))

            def visit(node: ast.AST, owner: str) -> None:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    owner = node.name
                hit = (
                    (isinstance(node, ast.Import) and any(a.name in _LOCK_MODULES for a in node.names))
                    or (isinstance(node, ast.ImportFrom) and node.module in _LOCK_MODULES)
                    or (isinstance(node, ast.Name) and node.id in _LOCK_MODULES)
                    or (isinstance(node, ast.Attribute) and node.attr in _LOCK_CALLS)
                    or (isinstance(node, ast.Call) and bool(node.args)
                        and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value in _LOCK_MODULES)
                )
                if hit:
                    found.add((rel, owner))
                for child in ast.iter_child_nodes(node):
                    visit(child, owner)

            visit(tree, "<module>")
    return found


def test_no_shipped_lock_site_reaches_for_fcntl_itself():
    actual = lock_primitive_sites(REPO_ROOT)
    assert actual == set(_LOCK_PRIMITIVE_ALLOWED), (
        f"a platform lock outside the primitive (a site that runs unlocked on "
        f"Windows, or locks a byte the primitive does not; take "
        f"_json_safe.lock_file / _atomic_io.lock_file instead): "
        f"{sorted(actual - _LOCK_PRIMITIVE_ALLOWED)}; stale allowed entries: "
        f"{sorted(_LOCK_PRIMITIVE_ALLOWED - actual)}"
    )


def test_the_census_sees_every_spelling_it_claims(tmp_path):
    # Earn the census's red on each spelling it promises to catch.
    pkg = tmp_path / "tools" / "cc"
    pkg.mkdir(parents=True)
    (tmp_path / "espalier").mkdir()
    spellings = {
        "a.py": "import fcntl as f\n",
        "b.py": "def g():\n    __import__('fcntl')\n",
        "c.py": "import importlib\ndef h():\n    importlib.import_module('msvcrt')\n",
        "d.py": "def k(kernel32):\n    kernel32.LockFileEx(0, 0, 0, 1, 0, None)\n",
        "e.py": "from msvcrt import locking\n",
    }
    for name, body in spellings.items():
        (pkg / name).write_text(body, encoding="utf-8")
    assert {rel for rel, _ in lock_primitive_sites(tmp_path)} == {f"tools/cc/{n}" for n in spellings}


def _load_hooks(*names: str):
    """Import hook modules the way Claude Code runs them (their own directory on
    ``sys.path``); they then share one ``_hook_utils`` module object."""
    import importlib

    sys.path.insert(0, str(HOOKS_DIR))
    try:
        return [importlib.import_module(n) for n in names]
    finally:
        sys.path.pop(0)


def _refuse(*_a, **_kw):
    raise OSError(45, "Operation not supported (simulated: a filesystem that cannot lock)")


class TestEveryLockSiteDegradesWhenTheLockIsRefused:
    """A lock CALL that raises -- a filesystem that cannot lock, or, on Windows,
    a hand-patched ``_json_safe.py`` that predates the primitive (the hook
    layer's fallback then raises on every call) -- must leave each site doing
    its job unlocked: no exception AND the effect lands. The first cut answered
    a refused counter lock with a read, which froze the reflect cadence for
    good, and let the integrity reader raise (failure-mode review, 2026-10-02).
    Each case patches the binding the site itself calls."""

    def test_the_counter_still_increments(self, tmp_path, monkeypatch):
        (hu,) = _load_hooks("_hook_utils")
        monkeypatch.setattr(hu, "lock_file", _refuse)
        state = tmp_path / ".espalier-state"
        assert [hu._locked_increment(state) for _ in range(3)] == [1, 2, 3]
        assert (state / "write_count").read_text(encoding="utf-8").strip() == "3"

    def test_the_speedbump_cap_still_counts(self, tmp_path, monkeypatch):
        (sb,) = _load_hooks("_speedbump")
        monkeypatch.setattr(sb, "lock_file", _refuse)
        state = tmp_path / ".espalier-state"
        assert [sb._locked_check_and_increment(state, 2) for _ in range(3)] == [True, True, False]

    def test_the_telemetry_append_lands(self, tmp_path, monkeypatch):
        (hu,) = _load_hooks("_hook_utils")
        monkeypatch.setattr(hu, "lock_file", _refuse)
        hu._append_jsonl(tmp_path, "t.jsonl", {"token": "landed"})
        assert _tokens_in(json.loads((tmp_path / "t.jsonl").read_text(encoding="utf-8"))) == ["landed"]

    def test_the_born_weak_append_lands(self, tmp_path, monkeypatch):
        hu, bw = _load_hooks("_hook_utils", "_born_weak")
        monkeypatch.setattr(hu, "lock_file", _refuse)
        bw.bw_log_observation(tmp_path, {"token": "landed"})
        log = tmp_path / ".espalier-state" / "born_weak_observations.jsonl"
        assert _tokens_in(json.loads(log.read_text(encoding="utf-8"))) == ["landed"]

    def test_the_audit_append_lands(self, tmp_path, monkeypatch):
        hu, integ = _load_hooks("_hook_utils", "_integrity")
        monkeypatch.setattr(hu, "lock_file", _refuse)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        assert integ.append_audit(tmp_path, {"event_type": "probe", "details": {"token": "landed"}}, quiet=True)
        (log,) = (tmp_path / "audit").glob("*.log")
        assert _tokens_in(json.loads(log.read_text(encoding="utf-8"))) == ["landed"]

    def test_the_integrity_manifest_writes_and_verifies(self, tmp_path, monkeypatch):
        hu, integ = _load_hooks("_hook_utils", "_integrity")
        for rel in integ.MANIFEST_FILES:
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f"# {rel}\n".encode("utf-8"))
        monkeypatch.setattr(hu, "lock_file", _refuse)
        integ.write_manifest(tmp_path)
        assert integ.load_manifest(tmp_path) is not None
        ok, mismatched = integ.verify_integrity(tmp_path)
        assert ok, mismatched

    def test_the_blueprint_lock_yields(self, tmp_path, monkeypatch):
        sys.path.insert(0, str(TOOLS_CC))
        try:
            import cognitive_blueprint  # type: ignore
        finally:
            sys.path.pop(0)
        monkeypatch.setattr(sys.modules["_json_safe"], "lock_file", _refuse)
        runs = 0
        with cognitive_blueprint._acquire_write_lock(tmp_path / "bp"):
            runs += 1
        assert runs == 1

    def test_the_plan_lock_yields(self, tmp_path, monkeypatch):
        sys.path.insert(0, str(TOOLS_CC))
        try:
            import execution_plan  # type: ignore
        finally:
            sys.path.pop(0)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setattr(sys.modules["_json_safe"], "lock_file", _refuse)
        runs = 0
        with execution_plan._plan_lock():
            runs += 1
        assert runs == 1

    def test_the_freshness_lock_yields(self, tmp_path, monkeypatch):
        from espalier import freshness

        monkeypatch.setattr(freshness, "lock_file", _refuse)
        runs = 0
        with freshness._freshness_write_lock(tmp_path):
            runs += 1
        assert runs == 1
