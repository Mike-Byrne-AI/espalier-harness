"""Freshness-verdict propagation contract for audit_accuracy.

Pins that `audit_accuracy` emits a verdict per critical-or-stale
fragment derived from the state_cache in
`.espalier/.freshness_state_cache.json`. Without this contract the audit orchestrator
can silently stop surfacing freshness verdicts after a refactor, and
stale fragments ship to production with no signal — defeating the
freshness gate that the CI workflow relies on.

The freshness verdicts are derived from the state_cache in
``.espalier/.freshness_state_cache.json``. The audit orchestrator surfaces them
alongside the existing claim verdicts.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _init_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "init", "-q"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "-C", str(repo), "commit", "--allow-empty", "-q", "-m", "init"],
        check=True, capture_output=True,
    )
    return repo


def _head_sha(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()


def _write_cache(
    repo: Path,
    *,
    critical: list[dict],
    stale: list[dict],
    sha: str | None = None,
) -> None:
    from espalier.freshness import update_state_cache
    update_state_cache(
        repo,
        counts={
            "fresh": 0,
            "stale": len(stale),
            "critical": len(critical),
            "unpinned": 0,
        },
        critical=critical,
        stale=stale,
        computed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        computed_at_sha=sha or _head_sha(repo),
    )


class TestAuditAccuracyFreshness:
    def test_critical_fragment_emits_fail_verdict(
        self, tmp_path: Path
    ) -> None:
        from espalier.audit_accuracy import (
            MODE_FRESHNESS,
            VERDICT_FAIL,
            audit_accuracy,
        )
        repo = _init_git_repo(tmp_path)
        _write_cache(
            repo,
            critical=[
                {"id": "marker-contract",
                 "source": "docs/CONVENTIONS.md:42",
                 "reason": "drift exceeds threshold (7 commits, 0 days)"},
            ],
            stale=[],
        )
        report = audit_accuracy(repo)
        verdicts = [v for v in report.verdicts
                    if v.verification_mode == MODE_FRESHNESS]
        assert len(verdicts) == 1
        assert verdicts[0].verdict == VERDICT_FAIL
        assert verdicts[0].location == "docs/CONVENTIONS.md:42"
        assert "drift" in verdicts[0].evidence

    def test_stale_fragment_emits_unverifiable_verdict(
        self, tmp_path: Path
    ) -> None:
        from espalier.audit_accuracy import (
            MODE_FRESHNESS,
            VERDICT_UNVERIFIABLE,
            audit_accuracy,
        )
        repo = _init_git_repo(tmp_path)
        _write_cache(
            repo,
            critical=[],
            stale=[
                {"id": "release-noise-patterns",
                 "source": "README.md:103",
                 "reason": "drift detected (2 commits, 0 days)"},
            ],
        )
        report = audit_accuracy(repo)
        verdicts = [v for v in report.verdicts
                    if v.verification_mode == MODE_FRESHNESS]
        assert len(verdicts) == 1
        assert verdicts[0].verdict == VERDICT_UNVERIFIABLE
        assert verdicts[0].location == "README.md:103"

    def test_all_fresh_emits_no_freshness_verdicts(
        self, tmp_path: Path
    ) -> None:
        from espalier.audit_accuracy import MODE_FRESHNESS, audit_accuracy
        repo = _init_git_repo(tmp_path)
        _write_cache(repo, critical=[], stale=[])
        report = audit_accuracy(repo)
        verdicts = [v for v in report.verdicts
                    if v.verification_mode == MODE_FRESHNESS]
        assert verdicts == []

    def test_state_cache_stale_emits_no_freshness_verdicts(
        self, tmp_path: Path
    ) -> None:
        from espalier.audit_accuracy import MODE_FRESHNESS, audit_accuracy
        repo = _init_git_repo(tmp_path)
        _write_cache(
            repo,
            critical=[{"id": "x", "source": "a.md:1", "reason": "y"}],
            stale=[],
            sha="0" * 40,  # mismatched SHA -> reader treats cache as stale
        )
        report = audit_accuracy(repo)
        verdicts = [v for v in report.verdicts
                    if v.verification_mode == MODE_FRESHNESS]
        assert verdicts == []

    def test_missing_state_cache_emits_no_freshness_verdicts(
        self, tmp_path: Path
    ) -> None:
        from espalier.audit_accuracy import MODE_FRESHNESS, audit_accuracy
        repo = _init_git_repo(tmp_path)
        # No manifest written.
        report = audit_accuracy(repo)
        verdicts = [v for v in report.verdicts
                    if v.verification_mode == MODE_FRESHNESS]
        assert verdicts == []

    def test_corrupt_cache_entries_degrade_not_crash(
        self, tmp_path: Path
    ) -> None:
        """TP-176 W3-1: a hand-edited / corrupted freshness.json whose
        `critical` holds a non-dict item, or whose `stale` is a non-list,
        must degrade (skip the bad data) rather than crash
        `audit_accuracy` with an AttributeError (exit 1)."""
        from espalier.audit_accuracy import (
            MODE_FRESHNESS,
            VERDICT_FAIL,
            audit_accuracy,
        )
        repo = _init_git_repo(tmp_path)
        # Write a fresh, valid cache first so the staleness gate passes and we
        # reach the verdict loops.
        _write_cache(
            repo,
            critical=[{"id": "good", "source": "docs/X.md:1", "reason": "r"}],
            stale=[],
        )
        # Corrupt it: inject a non-dict entry into critical and make stale a
        # non-list container — both would have crashed the pre-fix loops.
        # TP-329: the cache is its own gitignored file (whole body IS the cache).
        cache_file = repo / ".espalier" / ".freshness_state_cache.json"
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        data["critical"].append("CORRUPT-NON-DICT-ENTRY")
        data["stale"] = "not-a-list"
        cache_file.write_text(json.dumps(data), encoding="utf-8")

        # Must not raise.
        report = audit_accuracy(repo)
        verdicts = [v for v in report.verdicts
                    if v.verification_mode == MODE_FRESHNESS]
        # The one valid critical entry still yields its FAIL verdict; the
        # corrupt string entry and the non-list stale are silently skipped.
        assert len(verdicts) == 1
        assert verdicts[0].verdict == VERDICT_FAIL
        assert verdicts[0].location == "docs/X.md:1"

    def test_mode_constant_is_freshness(self) -> None:
        from espalier.audit_accuracy import MODE_FRESHNESS
        assert MODE_FRESHNESS == "freshness"

    def test_doc_scoped_audit_excludes_out_of_scope_freshness(
        self, tmp_path: Path
    ) -> None:
        """TP-152 B-3: `--doc <file>` scopes freshness verdicts to the
        requested file. A critical fragment in an unrelated doc must NOT
        surface (pre-fix it did, so a single-file audit exited 1 on
        repo-wide drift)."""
        from espalier.audit_accuracy import (
            MODE_FRESHNESS,
            VERDICT_FAIL,
            audit_accuracy,
        )
        repo = _init_git_repo(tmp_path)
        (repo / "docs").mkdir(exist_ok=True)
        (repo / "docs" / "in_scope.md").write_text("# in scope\n", encoding="utf-8")
        _write_cache(
            repo,
            critical=[{"id": "out", "source": "docs/other.md:3",
                       "reason": "drift"}],
            stale=[],
        )
        # full audit surfaces the critical
        full = audit_accuracy(repo)
        assert any(
            v.verification_mode == MODE_FRESHNESS and v.verdict == VERDICT_FAIL
            for v in full.verdicts
        )
        # scoped to in_scope.md: the out-of-scope critical is filtered out
        scoped = audit_accuracy(repo, doc_globs=["docs/in_scope.md"])
        fresh = [v for v in scoped.verdicts
                 if v.verification_mode == MODE_FRESHNESS]
        assert fresh == [], f"out-of-scope freshness leaked into --doc: {fresh}"

    def test_doc_scoped_audit_includes_in_scope_freshness(
        self, tmp_path: Path
    ) -> None:
        """TP-152 B-3 guard rail: a critical fragment whose source IS the
        scoped doc still surfaces — scoping filters, it doesn't suppress."""
        from espalier.audit_accuracy import (
            MODE_FRESHNESS,
            VERDICT_FAIL,
            audit_accuracy,
        )
        repo = _init_git_repo(tmp_path)
        (repo / "docs").mkdir(exist_ok=True)
        (repo / "docs" / "in_scope.md").write_text("# in scope\n", encoding="utf-8")
        _write_cache(
            repo,
            critical=[{"id": "in", "source": "docs/in_scope.md:1",
                       "reason": "drift"}],
            stale=[],
        )
        scoped = audit_accuracy(repo, doc_globs=["docs/in_scope.md"])
        assert any(
            v.verification_mode == MODE_FRESHNESS and v.verdict == VERDICT_FAIL
            for v in scoped.verdicts
        )
