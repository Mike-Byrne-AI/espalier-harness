"""Tests for ``espalier.scanners.freshness.scan_repo`` — the
canonical end-to-end driver every freshness consumer delegates to.

Pins state classification (fresh/stale/critical), manifest loading
+ schema enforcement, git-log integration, and the single-
subprocess optimization that batches all ``git log`` queries into
one call. Without this contract a refactor of any one phase could
silently regress the others — the scanner would still produce a
report (so smoke tests pass) but the classification would be
wrong, the statusline freshness segment would mislead, and the CI
gate would let stale critical fragments merge unnoticed.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from espalier.scanners.freshness import (
    CRITICAL_THRESHOLD_DAYS,
    cohort_warning,
    pin_cohorts,
    FreshnessError,
    SCHEMA_VERSION,
    STALE_THRESHOLD_COMMITS,
    STALE_THRESHOLD_DAYS,
    scan_repo,
)

# Single source of truth for fixture freshness dates. Every manifest
# timestamp derives from `_NOW`, so fixtures track wall-clock and can
# never age into a different state classification. (A hardcoded
# `2026-05-17` default previously aged past STALE_THRESHOLD_DAYS=14 and
# flipped five "fresh"/"stale" assertions to `critical` on 2026-06-01.)
# To shift fixture freshness, change only `_iso_days_ago` / its callers.
_NOW = datetime.now(timezone.utc)


def _iso_days_ago(days: int) -> str:
    """ISO-8601 ``Z`` timestamp ``days`` before now.

    ``days=0`` sits comfortably inside the fresh band
    (``STALE_THRESHOLD_DAYS`` = 14); pass a value > 14 to force an
    age-driven ``critical`` deterministically regardless of run date.
    """
    return (_NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "-C", str(repo), *args],
        check=True, capture_output=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    return repo


def _commit_all(repo: Path, message: str) -> str:
    subprocess.run(
        ["git", "-C", str(repo), "add", "-A"],
        check=True, capture_output=True,
    )
    _git(repo, "commit", "-q", "-m", message)
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return result.stdout.strip()


def _write_doc_with_fragment(
    repo: Path, fragment_id: str, bound: str, policy: str = "weekly"
) -> None:
    doc = repo / "docs" / "x.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        f"# x\n\n"
        f"<!-- espalier:fragment id={fragment_id} "
        f"bound={bound} policy={policy} -->\n"
        f"Claim line.\n",
        encoding="utf-8",
    )


def _write_manifest(
    repo: Path, fragment_id: str, sha: str, bound: list[str],
    policy: str = "weekly", expected_value: object = None,
    last_verified_at: str | None = None,
) -> None:
    # Default to a freshly-verified fragment derived from the single
    # `_NOW` anchor (never a hardcoded calendar date). Age-driven tests
    # pass an explicit `_iso_days_ago(n)`; no caller currently needs an
    # old date (criticals here are commit- or bound-driven).
    entry: dict[str, object] = {
        "bound": bound,
        "policy": policy,
        "last_verified_sha": sha,
        "last_verified_at": last_verified_at or _iso_days_ago(0),
    }
    if expected_value is not None:
        entry["expected_value"] = expected_value
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "fragments": {fragment_id: entry},
    }
    target = repo / ".espalier" / "freshness.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


class TestScanRepo:
    def test_scan_repo_returns_empty_on_repo_without_fragments(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        (repo / "README.md").write_text("# r\n", encoding="utf-8")
        _commit_all(repo, "init")
        states = scan_repo(repo)
        assert states == []

    def test_scan_repo_returns_unpinned_when_no_manifest_entry(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        states = scan_repo(repo)
        assert len(states) == 1
        assert states[0].state == "unpinned"
        assert "not pinned" in states[0].message

    def test_scan_repo_returns_fresh_when_pinned_at_head(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        sha = _commit_all(repo, "init")
        _write_manifest(repo, "foo", sha, ["a.py"])
        states = scan_repo(repo)
        assert len(states) == 1
        assert states[0].state == "fresh"
        assert states[0].commits_since == 0

    def test_scan_repo_returns_stale_on_one_commit_to_bound_path(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        sha = _commit_all(repo, "init")
        _write_manifest(repo, "foo", sha, ["a.py"])
        (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        _commit_all(repo, "modify bound path")
        states = scan_repo(repo)
        assert states[0].state == "stale"
        assert states[0].commits_since == 1

    def test_scan_repo_dedupes_multi_symbol_same_file_binding(
        self, tmp_path: Path
    ) -> None:
        """A fragment binding N symbols in ONE file counts that file's drift ONCE.

        Earn-the-red (TP-251): before ``_bound_to_paths`` deduped, a fragment
        bound to ``mod.py::a,mod.py::b`` returned ``["mod.py", "mod.py"]`` and
        ``scan_repo``'s ``sum(sha_commits.get(p, 0) for p in bound_paths)``
        counted each real commit TWICE. Three honest commits reported as six —
        crossing ``STALE_THRESHOLD_COMMITS`` (5) and flipping ``stale`` to a
        false ``critical`` that trips the exit-2 CI freshness gate. This test
        goes RED (``commits_since == 6``, ``state == "critical"``) on the
        pre-fix code and GREEN once the path list is deduped. Since 2026-09-10
        a symbol bound counts only its own lines, so each commit here changes
        BOTH bound symbols: the union of the two walks still reports three.
        """
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", "mod.py::a,mod.py::b")
        (repo / "mod.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
        sha = _commit_all(repo, "init")
        _write_manifest(repo, "foo", sha, ["mod.py::a", "mod.py::b"])
        for i in range(3):
            (repo / "mod.py").write_text(
                f"a = {i + 10}\nb = {i + 20}\n", encoding="utf-8"
            )
            _commit_all(repo, f"touch mod.py {i}")
        states = scan_repo(repo)
        assert len(states) == 1
        # Three commits to one file bound by two symbols == three, not six.
        assert states[0].commits_since == 3
        assert states[0].state == "stale"
        assert states[0].state != "critical"

    def test_scan_repo_counts_drift_per_fragment_pin(
        self, tmp_path: Path
    ) -> None:
        """R07: each fragment's drift is counted from ITS OWN pin, not a single
        shared window — closing both error directions a shared window has.

        Setup: ``aaa`` (iterates FIRST) is pinned at a RECENT sha (HEAD); ``zzz``
        (iterates LAST) is pinned at the OLDEST sha. A commit touching zzz's
        bound path (z.py) lands BETWEEN the two pins; aaa's bound path (a.py)
        is touched only AT aaa's own pin.

        - A first-seen single window (the original bug) opens at aaa's recent
          sha and MISSES the z.py commit → ``zzz`` wrongly fresh (false neg).
        - A chronological-min single window opens at zzz's old sha and counts
          the a.py commit (which predates aaa's pin) against ``aaa`` → ``aaa``
          wrongly stale (false POSITIVE — the cardinal sin; this is what the
          per-distinct-pin design avoids).

        Only per-fragment-pin counting gets BOTH right: zzz stale, aaa fresh.
        Distinct committer timestamps are forced via GIT_COMMITTER_DATE so the
        two pins are genuinely orderable.
        """
        repo = _init_repo(tmp_path)

        def _commit_dated(message: str, epoch: int) -> str:
            subprocess.run(
                ["git", "-C", str(repo), "add", "-A"],
                check=True, capture_output=True,
            )
            env = {
                **os.environ,
                "GIT_AUTHOR_DATE": f"{epoch} +0000",
                "GIT_COMMITTER_DATE": f"{epoch} +0000",
            }
            subprocess.run(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                 "-C", str(repo), "commit", "-q", "-m", message],
                check=True, capture_output=True, env=env,
            )
            out = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True, encoding="utf-8",
            )
            return out.stdout.strip()

        base = int(_NOW.timestamp())
        # Two fragments in two docs (one fragment per file, avoiding any
        # single-file parsing assumption); bound to distinct source files.
        for fid, bound in (("aaa", "a.py"), ("zzz", "z.py")):
            doc = repo / "docs" / f"{fid}.md"
            doc.parent.mkdir(parents=True, exist_ok=True)
            doc.write_text(
                f"# {fid}\n\n"
                f"<!-- espalier:fragment id={fid} bound={bound} "
                f"policy=weekly -->\nClaim line.\n",
                encoding="utf-8",
            )
        (repo / "a.py").write_text("a = 1\n", encoding="utf-8")
        (repo / "z.py").write_text("z = 1\n", encoding="utf-8")
        old_sha = _commit_dated("c1: both fragments (oldest, zzz pin)", base - 300)
        # Drift to zzz's bound path, BETWEEN the two pins.
        (repo / "z.py").write_text("z = 2\n", encoding="utf-8")
        _commit_dated("c2: drift z.py (between pins)", base - 200)
        # aaa's pin point (newest); also HEAD.
        (repo / "a.py").write_text("a = 2\n", encoding="utf-8")
        new_sha = _commit_dated("c3: drift a.py (newest, aaa pin)", base - 100)

        # aaa iterates FIRST (recent sha), zzz LAST (oldest sha).
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "fragments": {
                "aaa": {"bound": ["a.py"], "policy": "weekly",
                        "last_verified_sha": new_sha,
                        "last_verified_at": _iso_days_ago(0)},
                "zzz": {"bound": ["z.py"], "policy": "weekly",
                        "last_verified_sha": old_sha,
                        "last_verified_at": _iso_days_ago(0)},
            },
        }
        target = repo / ".espalier" / "freshness.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        states = scan_repo(repo)
        zzz = next(s for s in states if s.fragment.id == "zzz")
        aaa = next(s for s in states if s.fragment.id == "aaa")
        # Older pin must see the between-pins drift to z.py (closes false neg).
        assert zzz.state == "stale", (
            f"zzz pinned at the older sha must see the c2 commit to z.py; "
            f"got state={zzz.state!r} commits={zzz.commits_since}"
        )
        assert zzz.commits_since >= 1
        # HEAD-pinned fragment with no drift since ITS pin must stay fresh —
        # a shared oldest-window would over-count the a.py commit that predates
        # aaa's pin (false positive). Per-pin counting keeps it fresh.
        assert aaa.state == "fresh", (
            f"aaa pinned at HEAD has no drift since its own pin; a shared "
            f"window over-counts it. got state={aaa.state!r} "
            f"commits={aaa.commits_since}"
        )
        assert aaa.commits_since == 0

    def test_scan_repo_stays_fresh_when_other_paths_change(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "unrelated.py").write_text("y = 1\n", encoding="utf-8")
        sha = _commit_all(repo, "init")
        _write_manifest(repo, "foo", sha, ["a.py"])
        (repo / "unrelated.py").write_text("y = 2\n", encoding="utf-8")
        _commit_all(repo, "modify unrelated path")
        states = scan_repo(repo)
        assert states[0].state == "fresh"
        assert states[0].commits_since == 0

    def test_scan_repo_yields_critical_on_unknown_policy(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(
            repo, "foo", "a.py", policy="not-a-real-policy"
        )
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        states = scan_repo(repo)
        assert states[0].state == "critical"
        assert "unknown policy" in states[0].message

    def test_scan_repo_escalates_critical_on_bound_mismatch(
        self, tmp_path: Path
    ) -> None:
        """TP-56-C round-2: bound mismatch is a rebinding attempt
        and is escalated to ``critical`` (was ``unpinned`` pre-TP-56-C)."""
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        sha = _commit_all(repo, "init")
        _write_manifest(repo, "foo", sha, ["b.py"])
        states = scan_repo(repo)
        assert states[0].state == "critical"
        assert "rebinding attempt" in states[0].message
        # The rebinding message must name both bounds; this content check is folded
        # in from a removed duplicate so the render-format invariant is not lost.
        assert "a.py" in states[0].message and "b.py" in states[0].message

    def test_scan_repo_raises_on_schema_version_mismatch(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        manifest_path = repo / ".espalier" / "freshness.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps({"schema_version": 99, "fragments": {}}),
            encoding="utf-8",
        )
        with pytest.raises(FreshnessError, match="schema_version"):
            scan_repo(repo)

    def test_scan_repo_raises_on_malformed_json(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        manifest_path = repo / ".espalier" / "freshness.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("not json", encoding="utf-8")
        with pytest.raises(FreshnessError, match="valid JSON"):
            scan_repo(repo)

    def test_scan_repo_raises_on_non_utf8_manifest(
        self, tmp_path: Path
    ) -> None:
        # TP-313b ITEM B: a present-but-non-UTF-8 manifest must raise the typed
        # FreshnessError (as the hardened write path already does), not leak an
        # uncaught UnicodeDecodeError. UnicodeDecodeError subclasses ValueError,
        # not OSError, so the pre-fix ``except OSError`` guard does not catch it.
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        manifest_path = repo / ".espalier" / "freshness.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(b"\xff\xfe\x00bad")
        with pytest.raises(FreshnessError):
            scan_repo(repo)

    def test_scan_repo_handles_path_with_symbol_suffix(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", "a.py::SYM")
        (repo / "a.py").write_text("SYM = 1\n", encoding="utf-8")
        sha = _commit_all(repo, "init")
        _write_manifest(repo, "foo", sha, ["a.py::SYM"])
        states = scan_repo(repo)
        assert states[0].state == "fresh"

    def test_scan_repo_uses_single_git_log_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", "a.py")
        _write_doc_with_fragment(
            repo / "extra",  # second doc dir not used by globs
            "ignored", "b.py"
        ) if False else None
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        sha = _commit_all(repo, "init")
        _write_manifest(repo, "foo", sha, ["a.py"])

        from espalier.scanners import freshness as fr_mod
        log_calls: list[list[str]] = []
        original_run = subprocess.run

        def counting_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
            if isinstance(cmd, list) and "log" in cmd:
                log_calls.append(list(cmd))
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(fr_mod.subprocess, "run", counting_run)
        scan_repo(repo)
        assert len(log_calls) == 1

    def test_scan_repo_escalates_critical_when_bound_added_post_pin(
        self, tmp_path: Path
    ) -> None:
        """TP-56-C round-2: a marker that widens its bound list after
        pinning trips the rebinding-attempt escalation; operator must
        ``unpin`` then re-``pin`` to consent to the new bound."""
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", "a.py,b.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "b.py").write_text("y = 1\n", encoding="utf-8")
        sha = _commit_all(repo, "init")
        _write_manifest(repo, "foo", sha, ["a.py"])
        states = scan_repo(repo)
        assert states[0].state == "critical"
        assert "rebinding attempt" in states[0].message

    def test_scan_repo_classifies_critical_above_threshold(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", "a.py")
        (repo / "a.py").write_text("x = 0\n", encoding="utf-8")
        sha = _commit_all(repo, "init")
        _write_manifest(repo, "foo", sha, ["a.py"])
        for n in range(STALE_THRESHOLD_COMMITS + 1):
            (repo / "a.py").write_text(f"x = {n + 1}\n", encoding="utf-8")
            _commit_all(repo, f"bump {n}")
        states = scan_repo(repo)
        assert states[0].state == "critical"
        assert states[0].commits_since > STALE_THRESHOLD_COMMITS

    def test_scan_repo_returns_fragment_metadata_per_state(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(
            repo, "foo", "a.py::SYM", policy="numeric-contract"
        )
        (repo / "a.py").write_text("SYM = 1\n", encoding="utf-8")
        sha = _commit_all(repo, "init")
        _write_manifest(
            repo, "foo", sha, ["a.py::SYM"],
            policy="numeric-contract", expected_value=42,
        )
        states = scan_repo(repo)
        assert states[0].fragment.id == "foo"
        assert states[0].fragment.bound == ("a.py::SYM",)
        assert states[0].fragment.policy == "numeric-contract"
        assert states[0].last_verified_sha == sha

    def test_scan_repo_missing_manifest_treated_as_empty(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        states = scan_repo(repo)
        assert len(states) == 1
        assert states[0].state == "unpinned"


class TestSurfaceAllowlist:
    """TP-56-B: scanner walks ALLOWLIST and filters via DENYLIST."""

    def test_examples_directory_is_skipped(self, tmp_path: Path) -> None:
        from espalier.scanners.freshness import discover_fragments
        repo = _init_repo(tmp_path)
        (repo / "examples" / "dogfooding").mkdir(parents=True)
        (repo / "examples" / "dogfooding" / "README.md").write_text(
            "<!-- espalier:fragment id=ex bound=a.py "
            "policy=numeric-contract -->\n",
            encoding="utf-8",
        )
        _commit_all(repo, "ex")
        frags = discover_fragments(repo)
        assert all(f.id != "ex" for f in frags)

    def test_task_packs_directory_is_skipped(self, tmp_path: Path) -> None:
        from espalier.scanners.freshness import discover_fragments
        repo = _init_repo(tmp_path)
        (repo / "task-packs").mkdir()
        (repo / "task-packs" / "TP-99.md").write_text(
            "<!-- espalier:fragment id=tp99 bound=a.py "
            "policy=numeric-contract -->\n",
            encoding="utf-8",
        )
        _commit_all(repo, "tp")
        frags = discover_fragments(repo)
        assert all(f.id != "tp99" for f in frags)

    def test_docs_external_is_skipped(self, tmp_path: Path) -> None:
        from espalier.scanners.freshness import discover_fragments
        repo = _init_repo(tmp_path)
        (repo / "docs" / "external").mkdir(parents=True)
        (repo / "docs" / "external" / "pinned.md").write_text(
            "<!-- espalier:fragment id=ext bound=a.py "
            "policy=numeric-contract -->\n",
            encoding="utf-8",
        )
        _commit_all(repo, "ext")
        frags = discover_fragments(repo)
        assert all(f.id != "ext" for f in frags)

    def test_readme_at_root_is_walked(self, tmp_path: Path) -> None:
        from espalier.scanners.freshness import discover_fragments
        repo = _init_repo(tmp_path)
        (repo / "README.md").write_text(
            "<!-- espalier:fragment id=readme bound=a.py "
            "policy=numeric-contract -->\n",
            encoding="utf-8",
        )
        _commit_all(repo, "r")
        frags = discover_fragments(repo)
        assert any(f.id == "readme" for f in frags)

    def test_arbitrary_top_level_md_is_skipped(
        self, tmp_path: Path
    ) -> None:
        from espalier.scanners.freshness import discover_fragments
        repo = _init_repo(tmp_path)
        (repo / "NOTES.md").write_text(
            "<!-- espalier:fragment id=notes bound=a.py "
            "policy=numeric-contract -->\n",
            encoding="utf-8",
        )
        _commit_all(repo, "n")
        frags = discover_fragments(repo)
        assert all(f.id != "notes" for f in frags)


class TestBoundNormalization:
    """TP-56-C round-2/3: ``_normalize_bound`` discipline.

    Scanner discovery + manifest writer + audit consumer all route
    through this helper so a marker with `path::fn()` and a manifest
    pinned to `path::fn` cannot disagree silently. Round-3 widened
    the closure to also strip `(arg)`, ` ()`, and `[idx]` shapes.
    """

    def test_strips_trailing_parens(self) -> None:
        from espalier.scanners.freshness import _normalize_bound
        assert _normalize_bound("espalier/m.py::fn()") == "espalier/m.py::fn"

    def test_collapses_repeated_slashes(self) -> None:
        from espalier.scanners.freshness import _normalize_bound
        assert _normalize_bound("espalier//m.py") == "espalier/m.py"

    def test_preserves_case(self) -> None:
        from espalier.scanners.freshness import _normalize_bound
        assert _normalize_bound("m.py::Fn") == "m.py::Fn"

    def test_strips_call_with_args(self) -> None:
        from espalier.scanners.freshness import _normalize_bound
        assert _normalize_bound("m.py::fn(arg)") == "m.py::fn"

    def test_strips_whitespace_before_parens(self) -> None:
        from espalier.scanners.freshness import _normalize_bound
        assert _normalize_bound("m.py::fn ()") == "m.py::fn"

    def test_strips_subscript(self) -> None:
        from espalier.scanners.freshness import _normalize_bound
        assert _normalize_bound("m.py::fn[0]") == "m.py::fn"

    def test_no_separator_strips_trailing_parens(self) -> None:
        from espalier.scanners.freshness import _normalize_bound
        assert _normalize_bound("fn()") == "fn"

    def test_idempotent_on_normalized_input(self) -> None:
        from espalier.scanners.freshness import _normalize_bound
        once = _normalize_bound("espalier/m.py::fn(arg)")
        twice = _normalize_bound(once)
        assert once == twice == "espalier/m.py::fn"


class TestBoundToPaths:
    """TP-251: ``_bound_to_paths`` returns UNIQUE paths.

    A fragment binding several symbols in one file must yield that file
    once, or ``scan_repo``'s per-path drift sum double-counts it into a
    false ``critical`` (see
    ``TestScanRepo.test_scan_repo_dedupes_multi_symbol_same_file_binding``).
    """

    def test_dedupes_multiple_symbols_in_one_file(self) -> None:
        from espalier.scanners.freshness import _bound_to_paths
        assert _bound_to_paths(("mod.py::a", "mod.py::b")) == ["mod.py"]

    def test_preserves_first_seen_order_across_files(self) -> None:
        from espalier.scanners.freshness import _bound_to_paths
        assert _bound_to_paths(
            ("b.py::x", "a.py::y", "b.py::z")
        ) == ["b.py", "a.py"]

    def test_bare_path_without_symbol_passes_through(self) -> None:
        from espalier.scanners.freshness import _bound_to_paths
        assert _bound_to_paths(("a.py", "a.py")) == ["a.py"]


class TestRebindingAttemptEscalation:
    """TP-56-C: a marker whose bound disagrees with the manifest entry
    is escalated to ``critical`` with the rebinding-attempt message,
    never silently re-pinned."""

    def test_marker_parens_normalize_to_manifest_match(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        (repo / "a.py").write_text("def fn(): pass\n", encoding="utf-8")
        _write_doc_with_fragment(repo, "foo", "a.py::fn()")
        sha = _commit_all(repo, "init")
        _write_manifest(repo, "foo", sha, ["a.py::fn"])
        states = scan_repo(repo)
        assert states[0].state in {"fresh", "stale"}
        assert "rebinding" not in states[0].message


class TestBoundClosure:
    """TP-56-C round-3: ``bound_closure=true`` widens to importers."""

    def test_closure_walks_python_importers(self, tmp_path: Path) -> None:
        from espalier.scanners.freshness import _resolve_bound_closure
        repo = _init_repo(tmp_path)
        (repo / "pkg").mkdir()
        (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (repo / "pkg" / "target.py").write_text(
            "def fn(): return 1\n", encoding="utf-8"
        )
        (repo / "pkg" / "caller_a.py").write_text(
            "from pkg.target import fn\nfn()\n", encoding="utf-8"
        )
        (repo / "pkg" / "caller_b.py").write_text(
            "import pkg.target\npkg.target.fn()\n", encoding="utf-8"
        )
        (repo / "pkg" / "unrelated.py").write_text(
            "x = 1\n", encoding="utf-8"
        )
        _commit_all(repo, "init")
        closure = _resolve_bound_closure("pkg/target.py::fn", repo)
        assert "pkg/target.py" in closure
        assert "pkg/caller_a.py" in closure
        assert "pkg/caller_b.py" in closure
        assert "pkg/unrelated.py" not in closure

    def test_closure_resolves_relative_and_name_imports(self, tmp_path: Path) -> None:
        """DEF-410m earn-the-red: two import spellings the walker missed. A
        RELATIVE import (``node.level``: ``from . import target``,
        ``from .target import fn``, ``from .. import target`` and
        ``from ..target import fn`` out of a subpackage) resolved against the
        importer's package, and the bound module imported as a NAME from its
        parent package (``node.names``: ``from pkg import target``, with or
        without an alias). Each was a pure false negative: an importer edited
        under a ``bound_closure=true`` fragment and the fragment never noticed.
        Precision witnesses: a relative import of a DIFFERENT sibling, and a
        ``from . import target`` inside the subpackage -- that names
        ``pkg.sub.target``, not the bound ``pkg.target``."""
        from espalier.scanners.freshness import _resolve_bound_closure
        repo = _init_repo(tmp_path)
        (repo / "pkg" / "sub").mkdir(parents=True)
        (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (repo / "pkg" / "sub" / "__init__.py").write_text("", encoding="utf-8")
        (repo / "pkg" / "target.py").write_text(
            "def fn(): return 1\n", encoding="utf-8"
        )
        importers = {
            "pkg/rel_module.py": "from . import target\n",
            "pkg/rel_symbol.py": "from .target import fn\n",
            "pkg/sub/rel_parent.py": "from .. import target\n",
            "pkg/sub/rel_parent_symbol.py": "from ..target import fn\n",
            "pkg/name_import.py": "from pkg import target\n",
            "pkg/name_alias.py": "from pkg import target as t\n",
        }
        bystanders = {
            "pkg/other.py": "x = 1\n",
            "pkg/other_sibling.py": "from . import other\n",
            "pkg/sub/own_sibling.py": "from . import target\n",
        }
        for rel, body in {**importers, **bystanders}.items():
            (repo / rel).write_text(body, encoding="utf-8")
        _commit_all(repo, "init")
        closure = _resolve_bound_closure("pkg/target.py::fn", repo)
        missed = set(importers) - closure
        assert not missed, f"importers the closure walker did not see: {sorted(missed)}"
        leaked = set(bystanders) & closure
        assert not leaked, f"non-importers pulled into the closure: {sorted(leaked)}"

    def test_closure_resolves_root_level_relative_imports(self, tmp_path: Path) -> None:
        """At the repo root the importer's package is empty, so ``from . import
        top`` names ``top`` itself (review of DEF-410m: the symbol spelling
        ``from .top import fn`` resolved there while the module spelling
        returned nothing). Both must join the closure of a root-level module."""
        from espalier.scanners.freshness import _resolve_bound_closure
        repo = _init_repo(tmp_path)
        (repo / "top.py").write_text("def fn(): return 1\n", encoding="utf-8")
        (repo / "root_dot_module.py").write_text("from . import top\n", encoding="utf-8")
        (repo / "root_dot_symbol.py").write_text("from .top import fn\n", encoding="utf-8")
        (repo / "root_other.py").write_text("from . import other\n", encoding="utf-8")
        _commit_all(repo, "init")
        closure = _resolve_bound_closure("top.py::fn", repo)
        assert {"root_dot_module.py", "root_dot_symbol.py"} <= closure
        assert "root_other.py" not in closure

    def test_closure_for_non_python_path_is_singleton(
        self, tmp_path: Path
    ) -> None:
        from espalier.scanners.freshness import _resolve_bound_closure
        repo = _init_repo(tmp_path)
        (repo / "docs").mkdir()
        (repo / "docs" / "thing.md").write_text("x", encoding="utf-8")
        _commit_all(repo, "init")
        closure = _resolve_bound_closure("docs/thing.md", repo)
        assert closure == {"docs/thing.md"}

    def test_parser_accepts_bound_closure_true(self, tmp_path: Path) -> None:
        from espalier.scanners.freshness import parse_fragment_markers
        text = (
            "# x\n"
            "<!-- espalier:fragment id=foo bound=a.py "
            "bound_closure=true policy=verify-on-touch -->\n"
        )
        frags = parse_fragment_markers(text, source_path="x.md")
        assert len(frags) == 1
        assert frags[0].bound_closure is True

    def test_parser_rejects_invalid_bound_closure(self) -> None:
        from espalier.scanners.freshness import (
            FreshnessError, parse_fragment_markers,
        )
        text = (
            "<!-- espalier:fragment id=foo bound=a.py "
            "bound_closure=maybe policy=verify-on-touch -->\n"
        )
        with pytest.raises(FreshnessError, match="bound_closure"):
            parse_fragment_markers(text, source_path="x.md")


class TestDayAxisWarningBand:
    """§C22: the day axis must WARN before it blocks.

    Pre-fix, ``_classify`` returned ``fresh`` at ``days <= STALE_THRESHOLD_DAYS``
    and ``critical`` at ``days > STALE_THRESHOLD_DAYS`` — ``stale`` was reachable
    only via the commit axis, so there was no warning band on the day clock at
    all. Combined with a bulk re-pin putting every fragment on one date, the whole
    cohort stepped from "all green" to "CI blocks every touching PR" on a single
    day, with no prior signal. The CI job treats ``stale`` as a warning that never
    blocks, so a band is exactly the difference between a heads-up and a wall.
    """

    def _classify(self, days: int, commits: int = 0) -> str:
        from espalier.scanners.freshness import _classify

        return _classify(
            policy_known=True, manifest_match=True, has_pin=True,
            commits=commits, days=days, dirty=False,
        )

    def test_inside_stale_threshold_is_fresh(self):
        assert self._classify(days=STALE_THRESHOLD_DAYS - 1) == "fresh"
        assert self._classify(days=STALE_THRESHOLD_DAYS) == "fresh"

    def test_past_stale_threshold_warns_instead_of_blocking(self):
        """Earn-the-red: pre-fix this returned 'critical' with no warning first."""
        assert self._classify(days=STALE_THRESHOLD_DAYS + 1) == "stale"
        assert self._classify(days=CRITICAL_THRESHOLD_DAYS) == "stale"

    def test_past_critical_threshold_blocks(self):
        assert self._classify(days=CRITICAL_THRESHOLD_DAYS + 1) == "critical"

    def test_band_is_non_empty(self):
        """A band whose bounds are equal is not a band — it is the old cliff."""
        assert CRITICAL_THRESHOLD_DAYS > STALE_THRESHOLD_DAYS, (
            "CRITICAL_THRESHOLD_DAYS must exceed STALE_THRESHOLD_DAYS or the "
            "day axis steps straight from fresh to critical again"
        )

    def test_commit_axis_still_escalates_independently_of_the_band(self):
        """The band is on the DAY axis only — heavy drift still blocks at once."""
        assert self._classify(days=0, commits=STALE_THRESHOLD_COMMITS + 1) == "critical"


class TestCohortAdvisory:
    """§C22: a bulk re-pin must announce itself when it happens, not 14 days later."""

    def _manifest(self, tmp_path, dates: list[str]):
        (tmp_path / ".espalier").mkdir(parents=True, exist_ok=True)
        frags = {
            f"f{i}": {"last_verified_at": f"{d}T00:00:00Z", "policy": "verify-on-touch"}
            for i, d in enumerate(dates)
        }
        (tmp_path / ".espalier" / "freshness.json").write_text(
            json.dumps({"schema_version": SCHEMA_VERSION, "fragments": frags}),
            encoding="utf-8",
        )
        return tmp_path

    def test_one_date_dominating_warns(self, tmp_path):
        root = self._manifest(tmp_path, ["2026-08-04"] * 14)
        assert pin_cohorts(root) == {"2026-08-04": 14}
        warning = cohort_warning(root)
        assert warning and "14 of 14" in warning and "2026-08-04" in warning

    def test_staggered_pins_do_not_warn(self, tmp_path):
        root = self._manifest(
            tmp_path, ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"]
        )
        assert cohort_warning(root) is None

    def test_half_the_manifest_on_one_date_warns_and_less_does_not(self, tmp_path):
        """Half is a cohort. Measured 2026-09-10: a re-pin of seven of fourteen
        fragments sat exactly on the old strict-majority boundary and was
        silent, while the seven cross both thresholds as one block."""
        half = self._manifest(tmp_path / "a", ["2026-08-01"] * 2 + ["2026-08-02"] * 2)
        assert cohort_warning(half) is not None, "exactly 50% must fire"
        under = self._manifest(tmp_path / "b", ["2026-08-01"] * 2 + ["2026-08-02", "2026-08-03", "2026-08-04"])
        assert cohort_warning(under) is None, "under 50% must not fire"

    def test_absent_manifest_is_silent_not_an_exception(self, tmp_path):
        """The advisory must never be the thing that raises — a missing manifest
        is already reported as `unpinned` by the scan itself."""
        assert pin_cohorts(tmp_path) == {}
        assert cohort_warning(tmp_path) is None

    def test_unreadable_manifest_is_silent(self, tmp_path):
        (tmp_path / ".espalier").mkdir(parents=True)
        (tmp_path / ".espalier" / "freshness.json").write_text("{not json", encoding="utf-8")
        assert cohort_warning(tmp_path) is None

    def test_non_object_manifest_is_silent(self, tmp_path):
        """Valid JSON that is not an object must not raise — caught by
        tests/test_json_dict_safe.py on the first attempt at this fix."""
        (tmp_path / ".espalier").mkdir(parents=True)
        (tmp_path / ".espalier" / "freshness.json").write_text("[]", encoding="utf-8")
        assert pin_cohorts(tmp_path) == {}
        assert cohort_warning(tmp_path) is None


class TestSymbolLevelDrift:
    """A bound that names a symbol drifts with the symbol, not with its file.

    Measured 2026-09-09 on the live manifest: two fragments bound to constants
    in one test file had been re-pinned twice in eight days at unchanged
    values, because every lane touched that file somewhere else, and a third,
    bound to a hook-wiring table, read stale on three commits that never
    touched the table. The walk is ``git log -L`` over the symbol's own lines
    at HEAD (``git show HEAD:path`` parsed by ``ast``, decorators included);
    anything the span cannot place (a nested or missing symbol, a file that is
    not Python) and any git error keeps the file count, so the fallback is
    always the conservative one.
    """

    @staticmethod
    def _pinned(tmp_path: Path, bound: str, body: str) -> Path:
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", bound)
        (repo / "a.py").write_text(body, encoding="utf-8")
        sha = _commit_all(repo, "init")
        _write_manifest(repo, "foo", sha, bound.split(","))
        return repo

    @staticmethod
    def _rewrite_and_commit(repo: Path, body: str, message: str) -> None:
        (repo / "a.py").write_text(body, encoding="utf-8")
        _commit_all(repo, message)

    def test_a_commit_elsewhere_in_the_bound_file_stays_fresh(self, tmp_path: Path) -> None:
        repo = self._pinned(tmp_path, "a.py::SYM", "SYM = 1\n\nOTHER = 2\n")
        self._rewrite_and_commit(repo, "SYM = 1\n\nOTHER = 3\n", "touch OTHER")
        state = scan_repo(repo)[0]
        assert state.state == "fresh", state.message
        assert state.commits_since == 0

    def test_a_commit_to_the_bound_constant_stales(self, tmp_path: Path) -> None:
        repo = self._pinned(tmp_path, "a.py::SYM", "SYM = 1\n\nOTHER = 2\n")
        self._rewrite_and_commit(repo, "SYM = 2\n\nOTHER = 2\n", "touch SYM")
        state = scan_repo(repo)[0]
        assert state.state == "stale"
        assert state.commits_since == 1

    def test_a_commit_inside_a_bound_function_body_stales(self, tmp_path: Path) -> None:
        repo = self._pinned(tmp_path, "a.py::f", "def f():\n    return 1\n\n\nX = 2\n")
        self._rewrite_and_commit(repo, "def f():\n    return 2\n\n\nX = 2\n", "touch f")
        assert scan_repo(repo)[0].state == "stale"

    def test_a_commit_after_a_bound_function_stays_fresh(self, tmp_path: Path) -> None:
        repo = self._pinned(tmp_path, "a.py::f", "def f():\n    return 1\n\n\nX = 2\n")
        self._rewrite_and_commit(repo, "def f():\n    return 1\n\n\nX = 3\n", "touch X")
        assert scan_repo(repo)[0].state == "fresh"

    def test_a_commit_to_a_bound_class_body_stales(self, tmp_path: Path) -> None:
        body = "class C:\n    A = 1\n\n\nX = 2\n"
        repo = self._pinned(tmp_path, "a.py::C", body)
        self._rewrite_and_commit(repo, body.replace("A = 1", "A = 2"), "touch C")
        assert scan_repo(repo)[0].state == "stale"

    def test_a_nested_symbol_keeps_the_file_count(self, tmp_path: Path) -> None:
        body = "class C:\n    def m(self):\n        return 1\n\n\nX = 2\n"
        repo = self._pinned(tmp_path, "a.py::C.m", body)
        self._rewrite_and_commit(repo, body.replace("X = 2", "X = 3"), "touch X")
        assert scan_repo(repo)[0].state == "stale"

    def test_a_symbol_missing_at_head_keeps_the_file_count(self, tmp_path: Path) -> None:
        repo = self._pinned(tmp_path, "a.py::GONE", "SYM = 1\n")
        self._rewrite_and_commit(repo, "SYM = 2\n", "touch SYM")
        assert scan_repo(repo)[0].state == "stale"

    def test_a_symbol_in_a_non_python_bound_keeps_the_file_count(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", "notes.txt::SYM")
        (repo / "notes.txt").write_text("SYM = 1\nOTHER = 2\n", encoding="utf-8")
        sha = _commit_all(repo, "init")
        _write_manifest(repo, "foo", sha, ["notes.txt::SYM"])
        (repo / "notes.txt").write_text("SYM = 1\nOTHER = 3\n", encoding="utf-8")
        _commit_all(repo, "touch OTHER")
        assert scan_repo(repo)[0].state == "stale"

    def test_two_symbols_in_one_file_count_a_shared_commit_once(self, tmp_path: Path) -> None:
        repo = self._pinned(tmp_path, "a.py::A,a.py::B", "A = 1\n\nB = 1\n")
        self._rewrite_and_commit(repo, "A = 2\n\nB = 2\n", "touch both")
        state = scan_repo(repo)[0]
        assert state.state == "stale"
        assert state.commits_since == 1

    def test_a_whole_file_entry_beside_a_symbol_entry_keeps_the_file_count(
        self, tmp_path: Path
    ) -> None:
        repo = self._pinned(tmp_path, "a.py,a.py::SYM", "SYM = 1\n\nOTHER = 2\n")
        self._rewrite_and_commit(repo, "SYM = 1\n\nOTHER = 3\n", "touch OTHER")
        assert scan_repo(repo)[0].state == "stale"

    @staticmethod
    def _log_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
        from espalier.scanners import freshness as fr_mod
        calls: list[list[str]] = []
        original_run = subprocess.run

        def counting_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
            if isinstance(cmd, list) and "log" in cmd:
                calls.append(list(cmd))
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(fr_mod.subprocess, "run", counting_run)
        return calls

    def test_no_symbol_walk_runs_while_the_file_count_is_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = self._pinned(tmp_path, "a.py::SYM", "SYM = 1\n")
        calls = self._log_calls(monkeypatch)
        scan_repo(repo)
        assert len(calls) == 1
        assert not any("-L" in c for c in calls)

    def test_one_symbol_walk_per_bound_symbol_whose_file_drifted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = self._pinned(tmp_path, "a.py::A,a.py::B", "A = 1\n\nB = 1\n\nC = 1\n")
        self._rewrite_and_commit(repo, "A = 1\n\nB = 1\n\nC = 2\n", "touch C")
        calls = self._log_calls(monkeypatch)
        assert scan_repo(repo)[0].state == "fresh"
        assert sum(1 for c in calls if "-L" in c) == 2
        assert sum(1 for c in calls if "--name-only" in c) == 1

    def test_a_column_zero_decoy_above_the_symbol_does_not_hide_its_change(
        self, tmp_path: Path
    ) -> None:
        """A docstring line starting with the symbol's name at column zero is
        what a funcname-regex locator would anchor on; the span is read from
        the AST, so the real declaration's change still counts."""
        body = '_DOC = """\nSYM = 999 is the budget\n"""\nSYM = 1\nOTHER = 2\n'
        repo = self._pinned(tmp_path, "a.py::SYM", body)
        self._rewrite_and_commit(repo, body.replace("SYM = 1\n", "SYM = 7\n"), "touch SYM")
        state = scan_repo(repo)[0]
        assert state.state == "stale"
        assert state.commits_since == 1

    def test_a_decorator_change_on_a_bound_function_stales(self, tmp_path: Path) -> None:
        body = "def deco(f):\n    return f\n\n\n@deco\ndef h():\n    return 1\n\n\nX = 2\n"
        repo = self._pinned(tmp_path, "a.py::h", body)
        self._rewrite_and_commit(repo, body.replace("@deco\n", "@deco  # changed\n"), "touch deco")
        assert scan_repo(repo)[0].state == "stale"

    def test_the_span_ignores_the_repo_diff_driver(self, tmp_path: Path) -> None:
        """With ``*.py diff=python`` git's funcname lines are def and class lines
        only; a regex locator over a constant errored out and a def region ran
        to the next def. A line span is the same under any driver."""
        body = "def f():\n    return 1\n\n\nZ = 1\n\n\ndef g():\n    return 2\n"
        repo = _init_repo(tmp_path)
        (repo / ".gitattributes").write_text("*.py diff=python\n", encoding="utf-8")
        _write_doc_with_fragment(repo, "foo", "a.py::f")
        (repo / "a.py").write_text(body, encoding="utf-8")
        sha = _commit_all(repo, "init")
        _write_manifest(repo, "foo", sha, ["a.py::f"])
        self._rewrite_and_commit(repo, body.replace("Z = 1", "Z = 99"), "touch Z")
        assert scan_repo(repo)[0].state == "fresh"
        self._rewrite_and_commit(repo, body.replace("Z = 1", "Z = 99").replace("return 1", "return 3"), "touch f")
        state = scan_repo(repo)[0]
        assert state.state == "stale"
        assert state.commits_since == 1

    def test_a_git_error_in_the_symbol_walk_keeps_the_file_count(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from espalier.scanners import freshness as fr_mod
        repo = self._pinned(tmp_path, "a.py::SYM", "SYM = 1\n\nOTHER = 2\n")
        self._rewrite_and_commit(repo, "SYM = 1\n\nOTHER = 3\n", "touch OTHER")
        sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD~1"],
            check=True, capture_output=True, text=True, encoding="utf-8",
        ).stdout.strip()
        assert fr_mod._git_log_symbol_commits(repo, sha, "a.py", (9999, 9999)) is None
        monkeypatch.setattr(fr_mod, "_symbol_span", lambda *a, **k: (9999, 9999))
        state = scan_repo(repo)[0]
        assert state.state == "stale", "a walk git refuses must keep the file count, never read fresh"
        assert state.commits_since == 1

    def test_a_bare_hex_line_inside_the_region_is_not_a_commit(self, tmp_path: Path) -> None:
        digest = "0123456789abcdef0123456789abcdef01234567"
        body = 'SYM = """\n' + digest + '\n"""\nOTHER = 2\n'
        repo = self._pinned(tmp_path, "a.py::SYM", body)
        self._rewrite_and_commit(repo, body.replace(digest, digest[::-1]), "touch SYM")
        state = scan_repo(repo)[0]
        assert state.state == "stale"
        assert state.commits_since == 1


class TestUncommittedBoundChanges:
    """Ledger row DEF-702. Drift is counted in commits since the pin, so a
    bound edited but not yet committed read ``fresh`` while the pinned claim
    could already be false of the working tree (driven 2026-09-06: a count
    fragment pinned at 47 beside a HEAD where the answer was 46). An
    uncommitted change to the bound is drift that has not landed: the
    fragment reads ``stale`` with a message naming the paths, narrowed to the
    symbol's own lines the way the commit walk is, and a literal edited by
    hand in the manifest beside an unchanged pin reads ``stale`` too. CI runs
    on a clean checkout, so only a working tree mid-edit sees the state."""

    @staticmethod
    def _pinned(tmp_path: Path, bound: str, body: str, **manifest_kw: object) -> Path:
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", bound)
        (repo / "a.py").write_text(body, encoding="utf-8")
        sha = _commit_all(repo, "init")
        _write_manifest(repo, "foo", sha, bound.split(","), **manifest_kw)
        return repo

    def test_a_modified_bound_file_reads_stale_and_names_the_path(self, tmp_path: Path) -> None:
        repo = self._pinned(tmp_path, "a.py", "x = 1\n")
        assert scan_repo(repo)[0].state == "fresh"
        (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        state = scan_repo(repo)[0]
        assert state.state == "stale", state.message
        assert state.commits_since == 0
        assert "uncommitted" in state.message and "a.py" in state.message, state.message
        assert state.dirty_paths == ("a.py",)

    def test_an_uncommitted_edit_outside_the_bound_symbol_stays_fresh(self, tmp_path: Path) -> None:
        repo = self._pinned(tmp_path, "a.py::SYM", "SYM = 1\n\nOTHER = 2\n")
        (repo / "a.py").write_text("SYM = 1\n\nOTHER = 3\n", encoding="utf-8")
        state = scan_repo(repo)[0]
        assert state.state == "fresh", state.message
        assert state.dirty_paths == ()

    def test_an_uncommitted_edit_to_the_bound_symbol_reads_stale(self, tmp_path: Path) -> None:
        repo = self._pinned(tmp_path, "a.py::SYM", "SYM = 1\n\nOTHER = 2\n")
        (repo / "a.py").write_text("SYM = 2\n\nOTHER = 2\n", encoding="utf-8")
        state = scan_repo(repo)[0]
        assert state.state == "stale", state.message
        assert state.dirty_paths == ("a.py",)

    def test_an_uncommitted_insertion_inside_a_bound_function_reads_stale(self, tmp_path: Path) -> None:
        repo = self._pinned(tmp_path, "a.py::f", "def f():\n    return 1\n\n\nX = 2\n")
        (repo / "a.py").write_text("def f():\n    y = 0\n    return 1\n\n\nX = 2\n", encoding="utf-8")
        assert scan_repo(repo)[0].state == "stale"

    def test_an_untracked_file_under_a_directory_bound_reads_stale(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _write_doc_with_fragment(repo, "foo", "corpus/")
        (repo / "corpus").mkdir()
        (repo / "corpus" / "one.txt").write_text("1\n", encoding="utf-8")
        sha = _commit_all(repo, "init")
        _write_manifest(repo, "foo", sha, ["corpus/"])
        assert scan_repo(repo)[0].state == "fresh"
        (repo / "corpus" / "two.txt").write_text("2\n", encoding="utf-8")
        state = scan_repo(repo)[0]
        assert state.state == "stale", state.message
        assert state.dirty_paths == ("corpus/",)

    def test_a_committed_bound_and_an_uncommitted_manifest_stay_fresh(self, tmp_path: Path) -> None:
        # The documented flow: pin, then commit the manifest beside the doc.
        # An uncommitted MANIFEST is not an uncommitted bound.
        repo = self._pinned(tmp_path, "a.py", "x = 1\n")
        assert scan_repo(repo)[0].state == "fresh"

    def test_a_literal_edited_by_hand_beside_an_unchanged_pin_reads_stale(self, tmp_path: Path) -> None:
        repo = self._pinned(tmp_path, "a.py", "x = 1\n", policy="numeric-contract", expected_value=1)
        _commit_all(repo, "pin")
        assert scan_repo(repo)[0].state == "fresh"
        manifest = repo / ".espalier" / "freshness.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["fragments"]["foo"]["expected_value"] = 2
        manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        state = scan_repo(repo)[0]
        assert state.state == "stale", state.message
        assert "by hand" in state.message and "1" in state.message, state.message

    def test_a_dirty_bound_never_masks_a_critical(self, tmp_path: Path) -> None:
        repo = self._pinned(tmp_path, "a.py", "x = 1\n", last_verified_at=_iso_days_ago(40))
        (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        assert scan_repo(repo)[0].state == "critical"

    def test_a_staged_rename_of_the_bound_file_reads_stale_under_its_old_name(self, tmp_path: Path) -> None:
        # ``git status -z`` carries a rename as two fields; both are dirty.
        repo = self._pinned(tmp_path, "a.py", "x = 1\n")
        _git(repo, "mv", "a.py", "b.py")
        state = scan_repo(repo)[0]
        assert state.state == "stale", state.message
        assert state.dirty_paths == ("a.py",)

    def test_status_parser_keeps_a_path_with_a_space_whole(self, tmp_path: Path) -> None:
        from espalier.scanners.freshness import _git_status_dirty

        repo = _init_repo(tmp_path)
        (repo / "sp ace.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        (repo / "sp ace.py").write_text("x = 2\n", encoding="utf-8")
        assert _git_status_dirty(repo, ["sp ace.py"]) == {"sp ace.py": " M"}
        assert _git_status_dirty(repo, []) == {}
