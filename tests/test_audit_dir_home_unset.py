"""Audit-log directory: HOME-unset fallback hardening.

Prevents a symlink-pre-place attack on the audit-log fallback path.
Pre-fix (post-v0.6.5 adversarial review finding): the HOME-unset
fallback in ``tools/cc/hooks/_integrity._audit_dir`` returned a STABLE
path ``tempfile.gettempdir() / ".espalier-audit"``. On a multi-tenant
POSIX host with world-writable ``/tmp``, an attacker could pre-place a
symlink at that path; the subsequent ``mkdir(exist_ok=True)`` would
no-op and the ``chmod(0o700)`` would tighten permissions on the
attacker-controlled target.

Fix: use ``tempfile.mkdtemp(prefix=".espalier-audit-")`` so the
fallback gets a unique, exclusive, mode-0o700 directory per process.
Cached at module level so multiple calls within one process land in
the same dir.

The RuntimeError branch of ``Path.home()`` is hard to trigger
naturally on a developer machine (POSIX falls back to pwd lookup).
We mock ``Path.home`` to raise so the fallback path is exercised
deterministically.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests._symlink_support import requires_symlink

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"


def _load_integrity_module():
    """Import the standalone hook helper without polluting sys.modules
    for tests that share the same name elsewhere."""
    sys.path.insert(0, str(HOOKS_DIR))
    if "_integrity" in sys.modules:
        del sys.modules["_integrity"]
    import _integrity  # type: ignore
    return _integrity


def test_audit_dir_returns_unique_tempdir_when_home_raises(monkeypatch):
    integ = _load_integrity_module()
    monkeypatch.delenv("ESPALIER_AUDIT_DIR", raising=False)
    # Force the RuntimeError branch deterministically.
    monkeypatch.setattr(
        integ.Path, "home",
        classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("no HOME"))),
    )
    # Reset the per-process cache so this test gets a fresh fallback.
    integ._make_fallback_dir.cache_clear()

    result = integ._audit_dir()

    assert result.name.startswith(".espalier-audit-"), (
        f"fallback dir must use mkdtemp prefix; got {result.name!r}"
    )
    import tempfile
    legacy = Path(tempfile.gettempdir()) / ".espalier-audit"
    assert result != legacy, (
        f"fallback returned the pre-fix stable path (symlink-attackable): {result}"
    )
    assert result.exists() and result.is_dir(), (
        f"fallback dir was not created: {result}"
    )
    # mkdtemp creates dirs with mode 0o700 on POSIX. Windows has no POSIX mode
    # bits (the temp dir is user-scoped via ACLs), so st_mode reports 0o777 —
    # assert the mode only where it is meaningful.
    if sys.platform != "win32":
        mode = result.stat().st_mode & 0o777
        assert mode == 0o700, f"fallback dir has mode {oct(mode)} (expected 0o700)"


def test_audit_dir_caches_fallback_within_process(monkeypatch):
    """Two calls within one process must return the same Path — caching
    ensures ``audit_path`` and ``append_audit`` land in the same dir.
    """
    integ = _load_integrity_module()
    monkeypatch.delenv("ESPALIER_AUDIT_DIR", raising=False)
    monkeypatch.setattr(
        integ.Path, "home",
        classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("no HOME"))),
    )
    integ._make_fallback_dir.cache_clear()

    a = integ._audit_dir()
    b = integ._audit_dir()
    assert a == b, f"fallback not cached: {a} != {b}"


def test_audit_dir_returns_home_path_when_home_is_set(monkeypatch):
    """The happy path (HOME set, or pwd fallback succeeds) must still
    return the canonical ``~/.espalier/audit`` location, NOT a tempdir.
    """
    integ = _load_integrity_module()
    monkeypatch.delenv("ESPALIER_AUDIT_DIR", raising=False)
    result = integ._audit_dir()
    # On dev machines and CI with HOME set, Path.home() succeeds and we
    # get the canonical path. The fallback branch should NOT fire.
    assert ".espalier" in result.parts, (
        f"expected canonical home audit path; got {result}"
    )
    assert "audit" in result.parts, (
        f"expected canonical home audit path; got {result}"
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only attack class")
def test_append_audit_does_not_crash_with_simulated_home_unset(monkeypatch, tmp_path):
    """End-to-end: ``append_audit`` must not raise even when the home
    branch fails. The hook's outer except already absorbs failures, but
    we want the happy path to write the log to the fallback dir."""
    integ = _load_integrity_module()
    monkeypatch.delenv("ESPALIER_AUDIT_DIR", raising=False)
    monkeypatch.setattr(
        integ.Path, "home",
        classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("no HOME"))),
    )
    integ._make_fallback_dir.cache_clear()

    # Should not raise; should log to the fallback dir.
    integ.append_audit(tmp_path, {"event_type": "test_home_unset", "details": {}})

    # Inspect the cached fallback dir via the lru_cache-wrapped helper.
    fallback_dir = integ._make_fallback_dir()
    log_files = list(fallback_dir.glob("*.log"))
    assert log_files, (
        f"append_audit did not write any log under fallback {fallback_dir}"
    )


class TestAuditDirEnvOverride:
    """ESPALIER_AUDIT_DIR overrides the HOME-based default."""

    def test_env_override_returns_override_path(self, monkeypatch, tmp_path):
        integ = _load_integrity_module()
        override = tmp_path / "my_audit"
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(override))
        assert integ._audit_dir() == override

    def test_env_override_takes_priority_over_home(self, monkeypatch, tmp_path):
        integ = _load_integrity_module()
        override = tmp_path / "my_audit"
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(override))
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        result = integ._audit_dir()
        assert result == override
        assert result != tmp_path / "home" / ".espalier" / "audit"

    def test_env_unset_falls_through_to_home(self, monkeypatch, tmp_path):
        integ = _load_integrity_module()
        monkeypatch.delenv("ESPALIER_AUDIT_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        # Path.home() reads USERPROFILE on Windows, HOME on POSIX — set both so
        # the fallback resolves under tmp_path on either platform.
        monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
        result = integ._audit_dir()
        assert result == tmp_path / "home" / ".espalier" / "audit"


class TestPruneOldAuditLogs:
    """_prune_old_audit_logs deletes logs older than max_age_days."""

    def test_deletes_old_logs(self, monkeypatch, tmp_path):
        import time
        integ = _load_integrity_module()
        audit_dir = tmp_path / "audit"
        audit_dir.mkdir(exist_ok=True)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(audit_dir))

        old_log = audit_dir / "old.log"
        old_log.write_text("x", encoding="utf-8")
        # Set mtime to 40 days ago.
        old_mtime = time.time() - (40 * 86400)
        import os
        os.utime(old_log, (old_mtime, old_mtime))

        deleted = integ._prune_old_audit_logs(max_age_days=30)
        assert deleted == 1
        assert not old_log.exists()

    def test_keeps_recent_logs(self, monkeypatch, tmp_path):
        integ = _load_integrity_module()
        audit_dir = tmp_path / "audit"
        audit_dir.mkdir(exist_ok=True)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(audit_dir))

        recent = audit_dir / "recent.log"
        recent.write_text("y", encoding="utf-8")

        deleted = integ._prune_old_audit_logs(max_age_days=30)
        assert deleted == 0
        assert recent.exists()

    def test_returns_zero_when_dir_missing(self, monkeypatch, tmp_path):
        integ = _load_integrity_module()
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "nonexistent"))
        assert integ._prune_old_audit_logs() == 0

    def test_never_raises(self, monkeypatch, tmp_path):
        integ = _load_integrity_module()
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "nonexistent"))
        # Must not raise even with a missing directory.
        result = integ._prune_old_audit_logs()
        assert isinstance(result, int)


class TestThePruneIsBoundedInsideTheWall:
    """DEF-3022: SessionStart's prune read the first line of up to
    ``_MAX_PRUNE_SCAN`` logs with no bound of its own, and on the Windows box
    (5,695 logs in the home store) 5,000 such reads took 11.7 s, so the banner
    was cut at its 13 s wall inside the prune. The scan reads the oldest
    name date first (``<slug>-<YYYYMMDD>.log``, a name with none before
    every dated one), stops at its deadline, and tells the caller how many
    logs dated past the window it left unread."""

    _OLD = "20240101"

    @staticmethod
    def _store(monkeypatch, tmp_path, names, *, age_days=40):
        import time
        from datetime import datetime, timezone
        integ = _load_integrity_module()
        audit_dir = tmp_path / "audit"
        audit_dir.mkdir(exist_ok=True)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(audit_dir))
        stamp = datetime.fromtimestamp(time.time() - age_days * 86400, timezone.utc).isoformat()
        for name in names:
            (audit_dir / name).write_bytes((json.dumps({"timestamp": stamp}) + "\n").encode("utf-8"))
        return integ, audit_dir

    @staticmethod
    def _slow_reads(monkeypatch, integ, seconds, order=None):
        import time
        real = integ._parse_first_log_timestamp

        def slow(f):
            time.sleep(seconds)
            if order is not None:
                order.append(f.name)
            return real(f)
        monkeypatch.setattr(integ, "_parse_first_log_timestamp", slow)

    def test_the_scan_stops_at_its_deadline_and_counts_the_old_logs_left(self, monkeypatch, tmp_path):
        """Dies to: no deadline, a deadline the loop never reads, or a stop
        that says nothing of the old logs it left. The bound is a count, not a
        clock: each read sleeps at least 10 ms, so a scan that stops at a
        0.3 s deadline has read at most 31 logs on any host, however slow
        (a wall-clock ceiling would false-fail a loaded parallel run)."""
        import inspect
        import time
        integ, audit_dir = self._store(monkeypatch, tmp_path, [f"s{n:03d}-{self._OLD}.log" for n in range(300)])
        assert "deadline" in inspect.signature(integ._prune_old_audit_logs).parameters
        self._slow_reads(monkeypatch, integ, 0.01)
        left: list[tuple[int, int]] = []
        demoted = integ._prune_old_audit_logs(max_age_days=30, deadline=time.monotonic() + 0.3,
                                              on_stop=lambda n, days: left.append((n, days)))
        assert 0 < demoted <= 31, f"the scan ran past its deadline: {demoted} logs read"
        assert left == [(300 - demoted, 30)], (demoted, left)
        assert len(list((audit_dir / "_cold").glob("*.log"))) == demoted

    def test_the_oldest_name_date_is_read_first(self, monkeypatch, tmp_path):
        """A sort by name orders by repository slug, so a time bound on it
        reads the same first slugs every start and never reaches an old log
        late in the alphabet. Dies to: the scan's order left by name."""
        names = ["a-20261031.log", "m-20250101.log", "z-20240101.log", "nodate.log"]
        integ, _ = self._store(monkeypatch, tmp_path, names)
        order: list[str] = []
        self._slow_reads(monkeypatch, integ, 0, order)
        integ._prune_old_audit_logs(max_age_days=30)
        assert order == ["nodate.log", "z-20240101.log", "m-20250101.log", "a-20261031.log"], order

    def test_logs_dated_inside_the_window_left_unread_say_nothing(self, monkeypatch, tmp_path):
        """Logs named inside the window hold nothing to demote unless renamed,
        so a stop among them is silent: else a store of recent logs past the
        bound would say so on every start. Dies to: every stop reported."""
        import time
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        integ, _ = self._store(monkeypatch, tmp_path, [f"s{n:03d}-{today}.log" for n in range(100)], age_days=0)
        self._slow_reads(monkeypatch, integ, 0.01)
        left: list[tuple[int, int]] = []
        assert integ._prune_old_audit_logs(max_age_days=30, deadline=time.monotonic() + 0.1,
                                           on_stop=lambda n, days: left.append((n, days))) == 0
        assert left == [], left

    def test_a_stop_counts_the_old_logs_past_the_cap_and_a_raising_notice_costs_only_itself(self, monkeypatch,
                                                                                            tmp_path):
        """Dies to: the count read over the capped slice (an old log past
        ``_MAX_PRUNE_SCAN`` is unread too), or an ``on_stop`` that raises out
        of a prune documented as never raising."""
        import time
        integ, _ = self._store(monkeypatch, tmp_path, [f"s{n:03d}-{self._OLD}.log" for n in range(10)])
        monkeypatch.setattr(integ, "_MAX_PRUNE_SCAN", 5)
        left: list[tuple[int, int]] = []

        def notice(n, days):
            left.append((n, days))
            raise RuntimeError("a notice that fails")
        assert integ._prune_old_audit_logs(max_age_days=30, deadline=time.monotonic() - 1, on_stop=notice) == 0
        assert left == [(10, 30)], left

    def test_the_name_date_the_scan_reads_is_the_one_audit_path_writes(self, monkeypatch, tmp_path):
        """The scan's order and the stop's count read the date ``audit_path``
        writes into a log's name: one format, two homes. Dies to:
        ``audit_path`` writing another date shape (``%Y-%m-%d``: the order
        falls back to the slug and today's log counts as old)."""
        import time
        from datetime import datetime, timezone
        integ, _ = self._store(monkeypatch, tmp_path, [])
        named = integ.audit_path(tmp_path / "repo", datetime(2024, 1, 1, tzinfo=timezone.utc)).name
        found = integ._AUDIT_LOG_DATE_RE.search(named)
        assert found is not None and found.group(1) == "20240101", named
        assert not integ._named_before(integ.audit_path(tmp_path / "repo"), time.time() - 30 * 86400)

    def test_session_start_bounds_the_prune_and_says_when_it_stopped_early(self, monkeypatch, tmp_path):
        """The hook passes the prune a deadline inside its own budget (the
        wall less the tail the network reads keep, or the smaller budget a
        handed-off fresh start was given) and names a stop that left old logs
        unread, with the bound that stopped it. Dies to: a deadline past the
        hook's budget or past a fresh start's, a stop the banner never hears
        of, or its own bound blamed for a stop the hook's budget made. (The
        boot table's call is the census below's.)"""
        import importlib.util
        import time
        spec = importlib.util.spec_from_file_location("_prune_wall_session_start", HOOKS_DIR / "session_start.py")
        ss = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, ss)
        spec.loader.exec_module(ss)
        seen: dict = {}

        def fake(max_age_days=30, *, deadline=None, on_stop=None):
            seen["deadline"] = deadline
            on_stop(7, 30)
            return 3
        said: list[str] = []
        monkeypatch.setattr(ss._integrity, "_prune_old_audit_logs", fake)
        monkeypatch.setattr(ss._hook_utils, "advise", lambda line, **kw: said.append(line))
        hook_start = time.monotonic() - 12.0
        ss._prune_audit_logs_inside_the_wall(hook_start)
        assert seen["deadline"] <= hook_start + ss._HOOK_BUDGET_SECONDS, seen
        assert len(said) == 1 and said[0].startswith("[INFO]") and said[0].isascii(), said
        assert "with 7 logs named before its 30-day window" in said[0] and "the hook's budget" in said[0], said
        now = time.monotonic()
        ss._prune_audit_logs_inside_the_wall(now)
        assert now < seen["deadline"] <= time.monotonic() + ss._PRUNE_BUDGET_SECONDS, seen
        assert "at its 1 s bound" in said[-1], said
        ss._prune_audit_logs_inside_the_wall(now, 0.25)
        assert seen["deadline"] <= now + 0.25, seen


def test_every_prune_call_outside_its_module_is_bounded():
    """DEF-3022 (the failure-mode review): the boot table's bare
    ``_integrity._prune_old_audit_logs`` restored beside a still-defined
    bounded helper kept every row above green. Dies to: a call under
    ``tools/cc/`` with no ``deadline=``, or the function handed on as a bare
    value (a table entry, a callback) for a caller to run unbounded."""
    import ast
    from tests._live_tree import checkout_glob

    name = "_prune_old_audit_logs"
    calls, unbounded = [], []
    for path in checkout_glob(REPO_ROOT / "tools" / "cc", "**/*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) == name:
                called.add(id(node.func))
                calls.append(f"{path.name}:{node.lineno}")
                if not any(kw.arg == "deadline" for kw in node.keywords):
                    unbounded.append(f"{path.name}:{node.lineno} (no deadline=)")
        for node in ast.walk(tree):
            if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load) \
                    and getattr(node, "attr", getattr(node, "id", None)) == name and id(node) not in called:
                unbounded.append(f"{path.name}:{node.lineno} (a bare value)")
    assert calls and unbounded == [], (calls, unbounded)


#: What a site's scope may store in place of the suite's audit store: a store
#: of its own, or a home of the child's own (the store then sits under it).
_STORE_KEYS = frozenset({"ESPALIER_AUDIT_DIR", "HOME", "USERPROFILE"})


def _audit_store_drops(text: str) -> list[int]:
    """The lines where ``text`` builds a child's env without the suite's audit
    store and stores none of its own: a comprehension whose ``startswith``
    filter names a prefix of ``ESPALIER_AUDIT_DIR`` (a string or a tuple, any
    quoting), or a ``pop``/``del`` of the name. A dict comprehension inside a
    function keeps the store when its filter, run on the name itself, selects
    it; one at module level never does, since it is built at import, before
    conftest's per-test value exists. Any site passes whose function (the
    module, for a module-level one) stores one of ``_STORE_KEYS`` as a
    subscript, a dict key or a keyword. A filter that reads another name is
    not run, and its site counts as dropping. Not read: a loop of ``if``
    statements popping by prefix, a prefix held in a named constant, and a
    child script inside a string."""
    import ast

    tree = ast.parse(text)
    parent: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[id(child)] = node

    def ancestors(node):
        while id(node) in parent:
            node = parent[id(node)]
            yield node

    def scope(node):
        return next((a for a in ancestors(node)
                     if isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))), tree)

    def stores(where) -> bool:
        for n in ast.walk(where):
            if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store) \
                    and isinstance(n.slice, ast.Constant) and n.slice.value in _STORE_KEYS:
                return True
            if isinstance(n, ast.Dict) and any(isinstance(k, ast.Constant) and k.value in _STORE_KEYS
                                               for k in n.keys):
                return True
            if isinstance(n, ast.keyword) and n.arg in _STORE_KEYS:
                return True
        return False

    def names_the_store(call) -> bool:
        if getattr(call.func, "attr", None) != "startswith" or not call.args:
            return False
        arg = call.args[0]
        # A prefix of the store's name at least as long as ESPALIER (spelled
        # so: a startswith call here would be a site this census reads).
        return any(isinstance(p, ast.Constant) and isinstance(p.value, str) and len(p.value) >= len("ESPALIER")
                   and "ESPALIER_AUDIT_DIR".startswith(p.value)
                   for p in (arg.elts if isinstance(arg, ast.Tuple) else [arg]))

    def filter_keeps(comp) -> bool:
        if len(comp.generators) != 1:
            return False
        gen = comp.generators[0]
        name = ast.Constant("ESPALIER_AUDIT_DIR")
        items = isinstance(gen.iter, ast.Call) and getattr(gen.iter.func, "attr", None) == "items"
        item = ast.Tuple([name, ast.Constant("x")], ast.Load()) if items else name
        run = ast.Expression(ast.ListComp(ast.Constant(1), [
            ast.comprehension(gen.target, ast.List([item], ast.Load()), gen.ifs, 0)]))
        try:
            return bool(eval(compile(ast.fix_missing_locations(run), "<filter>", "eval"), {"__builtins__": {}}))
        except Exception:  # a filter that reads another name is not run: the site counts as dropping
            return False

    comps = (ast.DictComp, ast.ListComp, ast.SetComp, ast.GeneratorExp)
    found = set()
    for node in ast.walk(tree):
        if any(isinstance(a, ast.Assert) for a in ancestors(node)):
            continue
        if isinstance(node, ast.Call) and names_the_store(node):
            comp = next((a for a in ancestors(node) if isinstance(a, comps)), None)
            if comp is None:
                continue  # one name tested, not an env built by a filter
            where = scope(comp)
            if isinstance(comp, ast.DictComp) and where is not tree and filter_keeps(comp):
                continue
            if not stores(where):
                found.add(comp.lineno)
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "pop" and node.args \
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == "ESPALIER_AUDIT_DIR":
            if not stores(scope(node)):
                found.add(node.lineno)
        elif isinstance(node, ast.Delete):
            if any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                   and t.slice.value == "ESPALIER_AUDIT_DIR" for t in node.targets) and not stores(scope(node)):
                found.add(node.lineno)
    return sorted(found)


@pytest.mark.parametrize("shape, drops", [
    ('def f():\n    return {k: v for k, v in os.environ.items() if not k.startswith("ESPALIER_")}\n', True),
    ("def f():\n    return {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE', 'ESPALIER'))}\n", True),
    ('def f():\n    return {k: v for k, v in os.environ.items()\n'
     '            if not k.startswith("ESPALIER") and k != "ESPALIER_AUDIT_DIR"}\n', True),
    ('def f():\n    env = dict(os.environ)\n    del env["ESPALIER_AUDIT_DIR"]\n    return env\n', True),
    ('def f():\n    env = os.environ.copy()\n    env.pop("ESPALIER_AUDIT_DIR", None)\n    return env\n', True),
    ('_ENV = {k: v for k, v in os.environ.items()\n'
     '        if not k.startswith("ESPALIER_") or k == "ESPALIER_AUDIT_DIR"}\n', True),
    ('def f():\n    env = os.environ.copy()\n    for k in [k for k in env if k.startswith("ESPALIER_")]:\n'
     '        env.pop(k)\n    return env\n', True),
    ('def f():\n    return {k: v for k, v in os.environ.items()\n'
     '            if not k.startswith("ESPALIER_") or k == "ESPALIER_AUDIT_DIR"}\n', False),
    ('def f(tree):\n    env = {k: v for k, v in os.environ.items() if not k.startswith(("ESPALIER_", "CLAUDE_"))}\n'
     '    env["ESPALIER_AUDIT_DIR"] = str(tree / ".audit")\n    return env\n', False),
    ('def f(home):\n    env = os.environ.copy()\n    env.pop("ESPALIER_AUDIT_DIR", None)\n'
     '    env["HOME"] = str(home)\n    return env\n', False),
    ('def f(**kw):\n    env = {k: v for k, v in os.environ.items() if not k.startswith("ESPALIER_")}\n'
     '    env.update(ESPALIER_AUDIT_DIR=os.environ["ESPALIER_AUDIT_DIR"], **kw)\n    return env\n', False),
    ('def f():\n    return {k: v for k, v in os.environ.items() if not k.startswith("ESPALIER_BOX_LOCK")}\n', False),
], ids=["literal", "tuple-single-quoted", "inverted-mention", "dict-then-del", "pop", "module-level-keep",
        "loop-of-pops", "keep-clause", "own-store", "own-home", "keyword-store", "other-prefix"])
def test_the_census_reads_each_shape_that_drops_the_store(shape, drops):
    """The census below, on the shapes the failure-mode review drove past
    its literal first form. Dies to: a shape read the wrong way round."""
    assert bool(_audit_store_drops(shape)) is drops, _audit_store_drops(shape)


def test_a_child_env_the_suite_or_a_bench_builds_keeps_an_audit_store():
    """DEF-3022: conftest's ``_isolate_audit_dir`` points each test at a store
    of its own, and an env built from ``os.environ`` that drops every
    ``ESPALIER_*`` name drops that too, so the child it spawns writes, and its
    SessionStart prune reads, the operator's home store (5,695 logs on the
    Windows box, 40-odd test slugs a day; a lifecycle deny wrote
    ``<slug>-20261101.log`` there). Dies to: a new such env under ``tests/``
    or ``bench/`` that keeps no store (:func:`_audit_store_drops`)."""
    from tests._live_tree import checkout_glob

    dropping = []
    for top in ("tests", "bench"):
        for path in checkout_glob(REPO_ROOT / top, "**/*.py"):
            text = path.read_text(encoding="utf-8")
            if "ESPALIER" in text and ("startswith" in text or "ESPALIER_AUDIT_DIR" in text):
                dropping += [f"{top}/{path.relative_to(REPO_ROOT / top).as_posix()}:{line}"
                             for line in _audit_store_drops(text)]
    assert dropping == [], dropping


class TestAuditDirOverrideValidation:
    """TP-44: ESPALIER_AUDIT_DIR must reject symlinks and paths that
    resolve outside the user's safe roots (home, tempdir). Without the
    validator, a compromised parent shell could redirect audit JSON
    into /etc/cron.d/ or other sensitive locations."""

    @requires_symlink
    def test_audit_dir_rejects_symlink_override(self, monkeypatch, tmp_path, capsys):
        integ = _load_integrity_module()
        target = tmp_path / "real_audit"
        target.mkdir()
        sym = tmp_path / "audit_sym"
        sym.symlink_to(target)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(sym))
        integ._make_fallback_dir.cache_clear()

        result = integ._audit_dir()
        captured = capsys.readouterr()

        assert result != sym, (
            f"symlink override was accepted: returned {result}"
        )
        assert "is a symlink" in captured.err, (
            f"expected stderr to mention symlink rejection; got: {captured.err!r}"
        )

    def test_audit_dir_rejects_non_home_non_tmp_override(
        self, monkeypatch, capsys,
    ):
        # /etc is not under home or tempdir on any POSIX layout; rejecting
        # it is the canonical case from the threat model.
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", "/etc/cron.d")
        integ = _load_integrity_module()
        integ._make_fallback_dir.cache_clear()

        result = integ._audit_dir()
        captured = capsys.readouterr()

        assert "/etc/cron.d" not in str(result), (
            f"non-home/non-tmp override was accepted: returned {result}"
        )
        assert "not under home or tempdir" in captured.err, (
            f"expected stderr to mention root rejection; got: {captured.err!r}"
        )

    def test_audit_dir_accepts_tmp_override(self, monkeypatch, tmp_path):
        """tmp_path is under tempfile.gettempdir() on every supported
        platform; the validator must NOT reject pytest's standard fixture
        path or every test that uses ESPALIER_AUDIT_DIR breaks."""
        integ = _load_integrity_module()
        override = tmp_path / "fresh_audit"
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(override))
        result = integ._audit_dir()
        assert result == override


class TestTmpdirPoisoning:
    """H2 (TP-49) — ``tempfile.gettempdir()`` honors $TMPDIR. An
    attacker-controlled parent shell setting TMPDIR to a sensitive
    location outside home (e.g., /etc/cron.d, /etc/init.d) would have
    legitimized ESPALIER_AUDIT_DIR=$TMPDIR/silent because the override
    validator unconditionally accepted ``gettempdir()`` in safe_roots.

    Post-fix: when TMPDIR is set, the env-driven gettempdir entry is
    skipped. The hard-coded /tmp + /var/folders fallback covers the
    legitimate POSIX/macOS tempdir locations without honoring env.
    """

    def test_tmpdir_poisoning_outside_home_rejected(
        self, monkeypatch, tmp_path, capsys,
    ):
        """The attack scenario from the H2 motivation: TMPDIR points at
        a non-home / non-/tmp / non-/var/folders location so the pre-fix
        gettempdir entry validated the attacker's chosen sink."""
        monkeypatch.setenv("TMPDIR", "/etc/cron.d")
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", "/etc/cron.d/silent")
        integ = _load_integrity_module()
        integ._make_fallback_dir.cache_clear()

        result = integ._audit_dir()
        captured = capsys.readouterr()

        assert "/etc/cron.d" not in str(result), (
            f"TMPDIR poisoning succeeded — override accepted: {result}"
        )
        assert "not under home or tempdir" in captured.err, (
            f"expected rejection on stderr; got {captured.err!r}"
        )

    def test_tmpdir_unset_gettempdir_still_accepted(
        self, monkeypatch, tmp_path,
    ):
        """When TMPDIR is NOT set (normal operation), the gettempdir
        entry is still in safe_roots. Sanity / non-regression."""
        monkeypatch.delenv("TMPDIR", raising=False)
        override = tmp_path / "fresh_audit"
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(override))
        integ = _load_integrity_module()
        integ._make_fallback_dir.cache_clear()
        result = integ._audit_dir()
        assert result == override

    def test_hardcoded_tmp_allowlist_works_without_env(
        self, monkeypatch, capsys, tmp_path,
    ):
        """Even when TMPDIR is poisoned, the hard-coded /tmp + /var/folders
        fallback still works. A path under /tmp directly (no env help) is
        accepted because the validator includes /tmp regardless of TMPDIR."""
        import sys
        if sys.platform == "win32":
            return  # POSIX-only test path
        monkeypatch.setenv("TMPDIR", "/etc/cron.d")  # poisoned
        # /tmp/espalier-test-... is owned by the test runner; create it.
        target = Path("/tmp") / f"espalier-h2-test-{tmp_path.name}"
        target.mkdir(exist_ok=True)
        try:
            monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(target))
            integ = _load_integrity_module()
            integ._make_fallback_dir.cache_clear()
            result = integ._audit_dir()
            assert result == target, (
                f"hard-coded /tmp allowlist should accept {target}; got {result}"
            )
        finally:
            try:
                target.rmdir()
            except OSError:
                pass


class TestPruneTimestampSemantics:
    """TP-44: prune uses the first JSON line's ``timestamp`` field as the
    primary age signal so mtime tampering can't keep a tampered log
    visible past its cutoff. mtime is the fallback when the log body
    can't be parsed (truncated file, corrupted JSON)."""

    def test_prune_uses_log_timestamp_not_mtime(self, monkeypatch, tmp_path):
        """Mtime tampering on a 31-day-old-content log must still prune."""
        import os
        import time
        from datetime import datetime, timedelta, timezone
        integ = _load_integrity_module()
        audit_dir = tmp_path / "audit"
        audit_dir.mkdir(exist_ok=True)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(audit_dir))

        old_ts = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        log = audit_dir / "tampered.log"
        log.write_text(
            json.dumps({"timestamp": old_ts, "event_type": "x"}) + "\n",
            encoding="utf-8",
        )
        # Tamper mtime to look fresh — the legacy mtime-only check would
        # keep this log.
        fresh = time.time()
        os.utime(log, (fresh, fresh))

        deleted = integ._prune_old_audit_logs(max_age_days=30)
        assert deleted == 1, (
            f"timestamp-based prune missed the tampered log; "
            f"got deleted={deleted}"
        )
        assert not log.exists()

    def test_prune_falls_back_to_mtime_on_unparseable_log(
        self, monkeypatch, tmp_path,
    ):
        """A log file that can't be JSON-parsed (truncated, corrupted)
        must still prune based on mtime — otherwise an attacker could
        write garbage that's never pruned."""
        import os
        import time
        integ = _load_integrity_module()
        audit_dir = tmp_path / "audit"
        audit_dir.mkdir(exist_ok=True)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(audit_dir))

        log = audit_dir / "corrupted.log"
        log.write_text("not valid json\n", encoding="utf-8")
        old_mtime = time.time() - (40 * 86400)
        os.utime(log, (old_mtime, old_mtime))

        deleted = integ._prune_old_audit_logs(max_age_days=30)
        assert deleted == 1
        assert not log.exists()


class TestPruneIterationCap:
    """TP-44: cap iteration so an attacker spamming the audit dir with
    empty .log files can't slow session_start indefinitely. Above the cap
    the oldest-named N are read (by the date in each name, DEF-3022's
    ``_audit_log_order``), a deterministic order, so each start goes on
    where the old logs are."""

    def test_prune_caps_iteration_count(self, monkeypatch, tmp_path, capsys):
        integ = _load_integrity_module()
        audit_dir = tmp_path / "audit"
        audit_dir.mkdir(exist_ok=True)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(audit_dir))
        # Make the cap small for the test.
        monkeypatch.setattr(integ, "_MAX_PRUNE_SCAN", 5)

        for i in range(10):
            (audit_dir / f"spam-{i:03d}.log").touch()

        integ._prune_old_audit_logs(max_age_days=0)
        captured = capsys.readouterr()

        assert "exceeds cap" in captured.err, (
            f"expected stderr warning on cap-exceeded; got: {captured.err!r}"
        )
