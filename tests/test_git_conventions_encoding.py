"""TP-189 XPLAT-1 / CIMODALITY-1: detect_git_conventions decodes git's output
as UTF-8, never the OS locale.

``espalier.analyze.detect_git_conventions`` parses ``git log --format=%s`` —
free-form commit subjects that routinely carry non-ASCII (accented authors,
CJK, emoji). It used ``subprocess.run(..., text=True)`` with no ``encoding=``,
so the decode followed ``locale.getpreferredencoding()``. On a UTF-8 host that
is invisible; on a stock Windows cp1252 console (or any non-UTF-8 locale) git's
UTF-8 bytes mis-decode — silent mojibake, or a hard ``UnicodeDecodeError`` on a
byte the locale codepage leaves undefined.

CIMODALITY-1: the repo's ``windows-latest`` CI job runs the full suite but the
conftest fixtures make **no commits**, so ``detect_git_conventions`` never ran
past its ``len(messages) < 5`` guard — green Windows CI did not certify this
path. These tests give it real coverage AND reproduce the hostile-locale crash
on any host by forcing the locale in a child process, so the fix is pinned
without needing a Windows runner.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from espalier.analyze import detect_git_conventions

REPO_ROOT = Path(__file__).resolve().parent.parent

# A commit subject that is invalid in cp1252/ASCII when read as those codepages
# but valid UTF-8 — the exact shape that breaks a locale-decoded read.
_NON_ASCII_SUBJECT = "feat: café résumé ☕ 日本語"


def _git(repo: Path, *args: str) -> None:
    # Test helper: captures BYTES (no text= → no decode), so it is itself
    # locale-immune and out of scope for the encoding contract.
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


def _make_repo(tmp_path: Path, subjects: list[str]) -> Path:
    """A throwaway git repo with one empty commit per subject, in order
    (so ``subjects[-1]`` is the newest / first in ``git log``)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Tester")
    for subject in subjects:
        _git(repo, "commit", "-q", "--allow-empty", "-m", subject)
    return repo


class TestDetectGitConventions:
    """Baseline coverage — the function shipped with zero tests (CIMODALITY-1)."""

    def test_detects_conventional_format(self, tmp_path):
        repo = _make_repo(
            tmp_path,
            ["feat: a", "fix: b", "docs: c", "chore: d", "refactor: e", "feat: f"],
        )
        result = detect_git_conventions(repo)
        assert result["format"] == "conventional"
        assert result["confidence"] >= 0.6

    def test_below_five_commits_returns_freeform(self, tmp_path):
        # The < 5-message guard — exactly the branch the vacuous Windows CI
        # never escaped, because its fixtures committed nothing.
        repo = _make_repo(tmp_path, ["feat: a", "fix: b", "feat: c"])
        result = detect_git_conventions(repo)
        assert result["format"] == "freeform"
        assert result["confidence"] == 0.0

    def test_non_ascii_subject_decoded_on_utf8_host(self, tmp_path):
        # On a UTF-8 host this passes with or without the fix; its job is to
        # EXERCISE the decode path with non-ASCII content so the Windows CI job
        # (cp1252) becomes a real guard. The forced-locale test below makes it
        # an earn-the-red on this host too.
        repo = _make_repo(
            tmp_path,
            ["feat: a", "fix: b", "docs: c", "chore: d", "feat: e", _NON_ASCII_SUBJECT],
        )
        result = detect_git_conventions(repo)
        assert result["format"] == "conventional"
        assert _NON_ASCII_SUBJECT in result["evidence"], (
            "non-ASCII subject was mangled in the decode"
        )


class TestNonUtf8LocaleDoesNotCorruptDetection:
    """The host-independent earn-the-red: force a non-UTF-8 locale in a child
    process and confirm detection survives. Pre-fix this raises
    ``UnicodeDecodeError`` (verified by reverting the fix); post-fix it is
    correct."""

    _DRIVER = (
        "import json, locale, sys\n"
        "from pathlib import Path\n"
        "from espalier.analyze import detect_git_conventions\n"
        "res = detect_git_conventions(Path(sys.argv[1]))\n"
        "print(json.dumps({'enc': locale.getpreferredencoding(False), 'res': res}))\n"
    )

    def test_non_utf8_locale_does_not_corrupt_detection(self, tmp_path):
        repo = _make_repo(
            tmp_path,
            ["feat: a", "fix: b", "docs: c", "chore: d", "feat: e", _NON_ASCII_SUBJECT],
        )
        # Defeat PEP 540 UTF-8 mode + PEP 538 C-locale coercion so the child's
        # preferred encoding is genuinely ASCII/locale, not UTF-8.
        env = {
            **os.environ,
            "LC_ALL": "C", "LANG": "C", "LC_CTYPE": "C",
            "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0",
        }
        proc = subprocess.run(
            [sys.executable, "-c", self._DRIVER, str(repo)],
            cwd=str(REPO_ROOT), env=env,
            capture_output=True, text=True, encoding="utf-8",
            # Kill a hung child directly: pytest-timeout's thread method cannot
            # interrupt a blocked subprocess.run, so guard it here.
            timeout=30,
        )
        if proc.returncode != 0:
            # Pre-fix path: the locale-decoded read raised UnicodeDecodeError.
            assert "UnicodeDecodeError" in proc.stderr, (
                "detect_git_conventions failed under a non-UTF-8 locale for an "
                f"unexpected reason (not the XPLAT-1 decode):\n{proc.stderr}"
            )
            pytest.fail(
                "XPLAT-1 regression: detect_git_conventions raised "
                f"UnicodeDecodeError under a non-UTF-8 locale.\n{proc.stderr}"
            )
        payload = json.loads(proc.stdout)
        normalized = payload["enc"].lower().replace("-", "").replace("_", "")
        if normalized in ("utf8", "utf"):
            pytest.skip(
                f"platform kept UTF-8 ({payload['enc']}); cannot reproduce a "
                "hostile locale here (Windows CI / the contract test still pin it)"
            )
        # Hostile locale reproduced AND detection is correct → encoding="utf-8"
        # is doing the work (a locale decode would have crashed or mojibake'd).
        assert payload["res"]["format"] == "conventional", payload
        assert _NON_ASCII_SUBJECT in payload["res"]["evidence"], payload
