"""BC-044 regression coverage: unknown policy is critical, not fresh.

Fail-closed by design — an unknown policy must NOT default to
``fresh`` because a typo or a malicious marker would suppress
otherwise-valid drift detection.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "-C", str(repo), *args],
        check=True, capture_output=True,
    )


def _init_with_fragment(tmp_path: Path, policy: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    doc = repo / "docs" / "x.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        f"# x\n\n"
        f"<!-- espalier:fragment id=foo bound=a.py policy={policy} -->\n",
        encoding="utf-8",
    )
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", "-A"],
        check=True, capture_output=True,
    )
    _git(repo, "commit", "-q", "-m", "init")
    return repo


class TestUnknownPolicy:
    def test_unknown_policy_yields_critical_state(
        self, tmp_path: Path
    ) -> None:
        from espalier.freshness import scan_repo
        repo = _init_with_fragment(tmp_path, "not-a-real-policy")
        states = scan_repo(repo)
        assert states[0].state == "critical"

    def test_unknown_policy_carries_explanatory_message(
        self, tmp_path: Path
    ) -> None:
        from espalier.freshness import scan_repo
        repo = _init_with_fragment(tmp_path, "made-up")
        states = scan_repo(repo)
        assert "unknown policy" in states[0].message
        assert "made-up" in states[0].message

    def test_known_policy_does_not_yield_critical(
        self, tmp_path: Path
    ) -> None:
        from espalier.freshness import scan_repo
        repo = _init_with_fragment(tmp_path, "verify-on-touch")
        states = scan_repo(repo)
        assert states[0].state != "critical"
