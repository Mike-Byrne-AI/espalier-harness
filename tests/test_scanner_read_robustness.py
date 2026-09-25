# pytest-marker: default-unit
"""Read-tolerance regression for the adopter-facing scanners (GAP-SCANNER-FP-01).

A single unreadable ``.py`` — a dangling symlink, a permission-denied file, or a
file deleted mid-walk — must NOT abort the whole ``espalier scan``. Each
``scan_repo`` (and godfiles' ``build_report``) skips the offending file and keeps
scanning; ``cmd_scan`` completes with exit 0 and writes all ten reports.

Earn-the-red: at HEAD every ``scan_repo`` below does a raw per-file ``open()`` in
an unguarded loop, so the dangling symlink raises ``FileNotFoundError`` and the
call propagates out — these tests error RED. Green after Block 2's per-file
``OSError`` guards.
"""
from __future__ import annotations

import argparse
import json
import os

import pytest

# Content that trips the exceptions (bare-except: pass) + prints scanners, so we
# can assert the GOOD file was still scanned after the bad one is skipped.
_GOOD_SRC = (
    "def handler():\n"
    "    try:\n"
    "        risky()\n"
    "    except:\n"
    "        pass\n"
    "    print('done')\n"
)
# A tautological assert trips the test-loosening scanner (test_*.py only).
_GOOD_TEST_SRC = "def test_something():\n    assert True\n"


def _make_tree(tmp_path):
    """Build a tree with a good ``.py`` + a good ``test_*.py`` + one dangling
    symlink ``test_dangling.py`` (matches BOTH iter_py_files and iter_test_files).
    Skip the whole test if the platform cannot create symlinks."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "good.py").write_text(_GOOD_SRC, encoding="utf-8")
    (pkg / "test_good.py").write_text(_GOOD_TEST_SRC, encoding="utf-8")
    _make_unreadable(pkg / "test_dangling.py")
    return tmp_path


def _make_unreadable(path):
    """Create an unreadable ``.py`` at ``path`` so the read-guard is exercised.
    Primary: a dangling symlink (root-safe — even root cannot open a missing
    target). Fallback: a chmod-000 real file, enforce-able only as non-root on
    POSIX. Skip loudly only if NEITHER can be produced (e.g. privilege-less
    Windows) so coverage never silently vanishes on a symlink-capable host."""
    try:
        os.symlink(str(path) + ".nonexistent_target", str(path))
        if not os.path.exists(str(path)):
            return
        os.unlink(str(path))  # target unexpectedly resolvable — fall through
    except (OSError, NotImplementedError):
        pass
    if os.name == "posix" and getattr(os, "geteuid", lambda: 0)() != 0:
        path.write_text("x = 1\n", encoding="utf-8")
        os.chmod(str(path), 0o000)
        try:
            open(str(path), encoding="utf-8").close()
        except OSError:
            return  # genuinely unreadable
        os.chmod(str(path), 0o644)  # readable despite chmod — not usable
    pytest.skip("cannot create an unreadable .py (no symlink priv, no enforceable chmod)")


class TestScannerReadTolerance:
    def test_exceptions_scan_repo_skips_unreadable(self, tmp_path):
        tree = _make_tree(tmp_path)
        from espalier.scanners.exceptions import scan_repo
        report = scan_repo(str(tree))
        assert any("test_dangling" in s["file"] for s in report["skipped"])
        assert any("good.py" in f["file"] for f in report["findings"])

    def test_prints_scan_repo_skips_unreadable(self, tmp_path):
        tree = _make_tree(tmp_path)
        from espalier.scanners.prints import scan_repo
        report = scan_repo(str(tree))
        assert any("test_dangling" in s["file"] for s in report["skipped"])
        assert any("good.py" in f["file"] for f in report["findings"])

    def test_perf_smells_scan_repo_skips_unreadable(self, tmp_path):
        tree = _make_tree(tmp_path)
        from espalier.scanners.perf_smells import scan_repo
        report = scan_repo(str(tree))
        assert any("test_dangling" in s["file"] for s in report["skipped"])
        assert report["files_scanned"] >= 2

    def test_test_loosening_scan_repo_skips_unreadable(self, tmp_path):
        tree = _make_tree(tmp_path)
        from espalier.scanners.test_loosening import scan_repo
        report = scan_repo(str(tree))
        assert any("test_dangling" in s["file"] for s in report["skipped"])
        # the good test_ file was still scanned (tautological assert flagged)
        assert report["count"] >= 1

    def test_godfiles_build_report_skips_unreadable(self, tmp_path):
        tree = _make_tree(tmp_path)
        from espalier.scanners.godfiles import build_report
        rows = build_report(str(tree))
        paths = " ".join(r.path for r in rows)
        assert "test_dangling" not in paths  # absence: the unreadable file is omitted
        assert "good.py" in paths            # the good file is still reported

    def test_cmd_scan_completes_and_writes_all_reports(self, tmp_path, capsys):
        tree = _make_tree(tmp_path)
        from espalier.cli import cmd_scan
        rc = cmd_scan(argparse.Namespace(repo=str(tree)))
        assert rc == 0
        reports = tree / "reports"
        expected = [
            "scan_exceptions.json", "scan_prints.json", "godfiles_report.json",
            "scan_perf_smells.json", "scan_test_loosening.json",
            "scan_convergence_theater.json", "scan_subprocess_contracts.json",
            "scan_filesystem_contracts.json", "scan_magic_depth.json",
            "scan_retired_vocab.json",
        ]
        for name in expected:
            assert (reports / name).exists(), f"missing report: {name}"
        exc = json.loads((reports / "scan_exceptions.json").read_text(encoding="utf-8"))
        assert any("test_dangling" in s["file"] for s in exc.get("skipped", []))
        god = json.loads((reports / "godfiles_report.json").read_text(encoding="utf-8"))
        assert "test_dangling" not in json.dumps(god)
        # The WARN counts DISTINCT unreadable files (1), not per-scanner skip
        # records (this fixture's single dangling file matches 4 scanner globs).
        err = capsys.readouterr().err
        assert "[WARN]" in err
        assert "1 unreadable file" in err
