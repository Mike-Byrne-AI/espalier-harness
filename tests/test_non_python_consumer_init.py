"""TP-60 — non-Python consumer end-to-end coverage.

Exercises `espalier init` and `espalier scan` against the typescript/go
fixtures from conftest.py to confirm v0.7 is honest about its
Python-flavored surface: init succeeds without traceback on non-Python
repos, and scan emits the calibrated WARN + typed skip envelope rather
than silently reporting "0 findings."
"""
from __future__ import annotations

import argparse
import json

from espalier.cli import cmd_init, cmd_scan


class TestInitNonPythonConsumer:
    """`espalier init` does not traceback on non-Python primary repos."""

    def test_init_on_typescript_repo_succeeds(self, typescript_repo):
        args = argparse.Namespace(repo=str(typescript_repo), config=None)
        assert cmd_init(args) == 0
        assert (typescript_repo / ".claude" / "settings.json").exists()
        assert (typescript_repo / "CLAUDE.md").exists()
        assert (typescript_repo / "reports" / "repo_fingerprint.json").exists()
        fp = json.loads(
            (typescript_repo / "reports" / "repo_fingerprint.json").read_text(encoding="utf-8")
        )
        assert fp["languages"][0] == "typescript"

    def test_init_on_go_repo_succeeds(self, go_repo):
        args = argparse.Namespace(repo=str(go_repo), config=None)
        assert cmd_init(args) == 0
        assert (go_repo / ".claude" / "settings.json").exists()
        assert (go_repo / "CLAUDE.md").exists()
        fp = json.loads(
            (go_repo / "reports" / "repo_fingerprint.json").read_text(encoding="utf-8")
        )
        assert fp["languages"][0] == "go"


class TestScanNonPythonConsumer:
    """`espalier scan` is honest about its Python-AST scope on non-Python repos."""

    def test_scan_on_typescript_repo_warns(self, typescript_repo, capsys):
        args = argparse.Namespace(repo=str(typescript_repo))
        assert cmd_scan(args) == 0
        captured = capsys.readouterr()
        assert "[WARN]" in captured.err
        assert "Python-specific" in captured.err
        assert "typescript" in captured.err
        summary = json.loads(
            (typescript_repo / "reports" / "scan_summary.json").read_text(encoding="utf-8")
        )
        assert summary["status"] == "skipped_no_python_files"
