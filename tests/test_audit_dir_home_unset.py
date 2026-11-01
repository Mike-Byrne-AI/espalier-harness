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
        that says nothing of the old logs it left."""
        import inspect
        import time
        integ, audit_dir = self._store(monkeypatch, tmp_path, [f"s{n:03d}-{self._OLD}.log" for n in range(300)])
        assert "deadline" in inspect.signature(integ._prune_old_audit_logs).parameters
        self._slow_reads(monkeypatch, integ, 0.01)
        left: list[int] = []
        start = time.monotonic()
        demoted = integ._prune_old_audit_logs(max_age_days=30, deadline=time.monotonic() + 0.3, on_stop=left.append)
        assert time.monotonic() - start < 1.5, "the scan ran past its deadline"
        assert 0 < demoted < 300 and left == [300 - demoted], (demoted, left)
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
        left: list[int] = []
        assert integ._prune_old_audit_logs(max_age_days=30, deadline=time.monotonic() + 0.1, on_stop=left.append) == 0
        assert left == [], left

    def test_session_start_bounds_the_prune_and_says_when_it_stopped_early(self, monkeypatch, tmp_path):
        """The hook passes the prune a deadline inside its own budget (the
        wall less the tail the network reads keep) and names a stop that left
        old logs unread. Dies to: the bare call in the boot table, a deadline
        past the hook's budget, or a stop the banner never hears of."""
        import importlib.util
        import time
        spec = importlib.util.spec_from_file_location("_prune_wall_session_start", HOOKS_DIR / "session_start.py")
        ss = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = ss
        spec.loader.exec_module(ss)
        assert hasattr(ss, "_prune_audit_logs_inside_the_wall"), "the boot table calls the prune with no deadline"
        seen: dict = {}

        def fake(max_age_days=30, *, deadline=None, on_stop=None):
            seen["deadline"] = deadline
            on_stop(7)
            return 3
        said: list[str] = []
        monkeypatch.setattr(ss._integrity, "_prune_old_audit_logs", fake)
        monkeypatch.setattr(ss._hook_utils, "advise", lambda line, **kw: said.append(line))
        hook_start = time.monotonic() - 12.0
        ss._prune_audit_logs_inside_the_wall(hook_start)
        assert seen["deadline"] <= hook_start + ss._HOOK_BUDGET_SECONDS, seen
        assert len(said) == 1 and said[0].startswith("[INFO]") and "7" in said[0] and said[0].isascii(), said
        now = time.monotonic()
        ss._prune_audit_logs_inside_the_wall(now)
        assert now < seen["deadline"] <= time.monotonic() + ss._PRUNE_BUDGET_SECONDS, seen


def test_a_test_that_drops_the_harness_env_keeps_its_audit_store():
    """DEF-3022: conftest's ``_isolate_audit_dir`` points each test at a store
    of its own, and an env built from ``os.environ`` that drops every
    ``ESPALIER_*`` name drops that too, so the child it spawns writes, and its
    SessionStart prune reads, the operator's home store (5,695 logs on the
    Windows box, 40-odd test slugs a day). Dies to: a new such env that does
    not keep ``ESPALIER_AUDIT_DIR``."""
    import ast
    from tests._live_tree import checkout_glob

    dropping = []
    for path in checkout_glob(REPO_ROOT / "tests", "test_*.py"):
        text = path.read_text(encoding="utf-8")
        if 'startswith("ESPALIER_")' not in text:
            continue
        for node in ast.walk(ast.parse(text)):
            segment = ast.get_source_segment(text, node) if isinstance(node, ast.DictComp) else None
            if segment and "os.environ" in segment and 'startswith("ESPALIER_")' in segment \
                    and "ESPALIER_AUDIT_DIR" not in segment:
                dropping.append(f"{path.name}:{node.lineno}")
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
    empty .log files can't slow session_start indefinitely. Cap is
    enforced via sorted-first-N processing — deterministic order so the
    operator sees consistent pruning under flood."""

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
