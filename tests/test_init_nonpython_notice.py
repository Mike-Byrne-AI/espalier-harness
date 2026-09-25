"""TP-189-A (NONPY-3): ``espalier init`` on a non-Python repo prints a
one-line scanner-scope notice so the adopter does not read the armed
harness banner as a full governance toolbelt.

The code scanners (``/scan``, the quality gates) are Python-AST-specific
and no-op on a JS/Go/Rust repo (a documented SHARP_EDGES class). Before
this notice, ``espalier init`` on such a repo printed a fully-armed banner
with zero degradation signal — the "Honest scope" caveat lived only in the
README the adopter had not read (neutral-lens audit NEUTRAL-NONPY-3).

Earn-the-red: the asserted string ``Python-AST-specific`` is introduced
solely by the ``cmd_init`` notice (Fix 2-B); without it the positive test
goes RED. The negative test pins that a Python repo stays silent, so the
notice is gated, not unconditional.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


_NOTICE_MARKER = "Python-AST-specific"


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)


@pytest.fixture
def nonpython_repo(tmp_path: Path) -> Path:
    """A repo whose only source is JavaScript — fingerprints non-Python."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.js").write_text("export const x = 1;\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name": "demo", "version": "1.0.0"}\n', encoding="utf-8")
    _git_init(tmp_path)
    return tmp_path


@pytest.fixture
def python_repo(tmp_path: Path) -> Path:
    """A repo whose source is Python — fingerprints python."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# placeholder\n", encoding="utf-8")
    _git_init(tmp_path)
    return tmp_path


def _run_init(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "espalier.cli", "init", str(repo), *extra],
        capture_output=True, text=True, check=False, encoding="utf-8",
    )


def test_init_nonpython_repo_prints_scanner_scope_notice(nonpython_repo: Path) -> None:
    result = _run_init(nonpython_repo)
    assert result.returncode == 0, (
        f"init failed (stdout={result.stdout!r}, stderr={result.stderr!r})"
    )
    assert _NOTICE_MARKER in result.stdout, (
        "A non-Python adopter must see the scanner-scope notice after init.\n"
        f"stdout:\n{result.stdout}"
    )


def test_init_python_repo_omits_scanner_scope_notice(python_repo: Path) -> None:
    result = _run_init(python_repo)
    assert result.returncode == 0, (
        f"init failed (stdout={result.stdout!r}, stderr={result.stderr!r})"
    )
    assert _NOTICE_MARKER not in result.stdout, (
        "A Python repo must NOT get the non-Python scanner-scope notice.\n"
        f"stdout:\n{result.stdout}"
    )
