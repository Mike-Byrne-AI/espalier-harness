"""Tests for the freshness manifest ``state_cache`` block (TP-56-B).

Covers:
- Writer side: ``espalier freshness check`` persists counts + SHA.
- Reader side: ``read_state_cache_safe`` + ``is_state_cache_stale``
  via ``espalier.freshness`` (audit_accuracy consumer path).
- Adversarial: future-dated cache, mismatched SHA, symlinked
  manifest, schema_version drift.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "-C", str(repo), *args],
        check=True, capture_output=True,
    )


def _init_repo_with_pinned_fragment(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    doc = repo / "docs" / "x.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "# x\n\n"
        "<!-- espalier:fragment id=foo bound=a.py "
        "policy=numeric-contract -->\n"
        "claim line\n",
        encoding="utf-8",
    )
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", "-A"],
        check=True, capture_output=True,
    )
    _git(repo, "commit", "-q", "-m", "init")
    from espalier.freshness import pin_fragment
    pin_fragment("foo", repo, expected_value=1)
    return repo


def _run_cli(*argv: str) -> tuple[int, str, str]:
    from espalier.cli import build_parser
    parser = build_parser()
    ns = parser.parse_args(list(argv))
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = ns.func(ns)
    return rc, out.getvalue(), err.getvalue()


class TestFreshnessStateCache:
    def test_check_writes_state_cache_with_counts_and_sha(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo_with_pinned_fragment(tmp_path)
        rc, _, _ = _run_cli("freshness", "check", str(repo))
        assert rc == 0
        # TP-329: the derived cache is written to its own gitignored per-install
        # file (whole body IS the cache), NOT a `state_cache` block in the manifest.
        cache = json.loads(
            (repo / ".espalier" / ".freshness_state_cache.json").read_text(encoding="utf-8")
        )
        assert set(cache["counts"].keys()) == {
            "fresh", "stale", "critical", "unpinned"
        }
        assert cache["counts"]["fresh"] == 1
        assert len(cache["computed_at_sha"]) == 40
        assert "T" in cache["computed_at"]  # ISO timestamp

    def test_state_cache_caps_entry_count_to_stay_readable(
        self, tmp_path: Path
    ) -> None:
        """R3: update_state_cache caps each list at _STATE_CACHE_MAX_ENTRIES.
        With hundreds of simultaneously-critical fragments, truncating only the
        per-entry reason still blows past the 64KB reader cap, after which
        read_state_cache_safe silently rejects the file and loses the cache. The
        cap keeps it readable; the true totals are preserved in `counts`."""
        from espalier.freshness import (
            update_state_cache,
            read_state_cache_safe,
            _STATE_CACHE_MAX_ENTRIES,
        )
        (tmp_path / ".espalier").mkdir()
        n = 300  # uncapped, ~300 * ~240B > 64KB -> reader would reject
        many = [
            {"id": f"frag-{i}", "source": f"f{i}.py:1", "reason": "x" * 300}
            for i in range(n)
        ]
        update_state_cache(
            tmp_path,
            counts={"critical": n, "stale": 0, "fresh": 0, "unpinned": 0},
            critical=many, stale=[],
            computed_at="2026-01-01T00:00:00Z", computed_at_sha="0" * 40,
        )
        cache = read_state_cache_safe(tmp_path)
        assert cache is not None, "capped manifest must stay under the 64KB cap"
        assert len(cache["critical"]) == _STATE_CACHE_MAX_ENTRIES
        assert cache["counts"]["critical"] == n  # true total preserved

    def test_reader_rejects_future_dated_cache(
        self, tmp_path: Path
    ) -> None:
        from espalier.freshness import is_state_cache_stale
        future = (
            datetime.now(timezone.utc) + timedelta(hours=2)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        cache = {
            "computed_at": future,
            "computed_at_sha": "0" * 40,
            "counts": {"fresh": 0, "stale": 0, "critical": 0, "unpinned": 0},
        }
        assert is_state_cache_stale(cache, repo_root=tmp_path) is True

    def test_reader_treats_mismatched_sha_as_stale(
        self, tmp_path: Path
    ) -> None:
        from espalier.freshness import is_state_cache_stale
        repo = _init_repo_with_pinned_fragment(tmp_path)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cache = {
            "computed_at": now_iso,
            "computed_at_sha": "1" * 40,
            "counts": {"fresh": 1, "stale": 0, "critical": 0, "unpinned": 0},
        }
        assert is_state_cache_stale(cache, repo_root=repo) is True

    def test_schema_version_one_roundtrips_state_cache(
        self, tmp_path: Path
    ) -> None:
        from espalier.freshness import (
            read_state_cache_safe,
            update_state_cache,
        )
        repo = tmp_path / "repo"
        (repo / ".espalier").mkdir(parents=True)
        (repo / ".espalier" / "freshness.json").write_text(
            json.dumps({"schema_version": 1, "fragments": {}}),
            encoding="utf-8",
        )
        update_state_cache(
            repo,
            counts={"fresh": 2, "stale": 1, "critical": 0, "unpinned": 0},
            critical=[],
            stale=[{"id": "x", "source": "a.md:1", "reason": "drift"}],
            computed_at="2026-05-17T12:00:00Z",
            computed_at_sha="a" * 40,
        )
        cache = read_state_cache_safe(repo)
        assert cache is not None
        assert cache["counts"]["fresh"] == 2
        assert cache["stale"][0]["id"] == "x"
        assert cache["stale"][0]["source"] == "a.md:1"

    def test_safe_reader_refuses_to_follow_symlink(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        if sys.platform == "win32":
            pytest.skip("symlinks require admin on Windows")
        from espalier.freshness import read_state_cache_safe
        repo = tmp_path / "repo"
        (repo / ".espalier").mkdir(parents=True)
        decoy = tmp_path / "decoy.json"
        decoy.write_text(
            # A non-None whole-body cache: if the O_NOFOLLOW guard were absent the
            # reader would follow the symlink and return this, failing the assert.
            json.dumps({"computed_at": "2026-05-17T12:00:00Z", "hostile": True}),
            encoding="utf-8",
        )
        # TP-329: symlink the file the reader actually opens now (the per-install
        # cache file), else the guard is never exercised and the test false-greens.
        cache_path = repo / ".espalier" / ".freshness_state_cache.json"
        os.symlink(decoy, cache_path)
        assert read_state_cache_safe(repo) is None

    def test_reason_truncated_at_two_hundred_chars(
        self, tmp_path: Path
    ) -> None:
        from espalier.freshness import (
            read_state_cache_safe,
            update_state_cache,
        )
        repo = tmp_path / "repo"
        (repo / ".espalier").mkdir(parents=True)
        (repo / ".espalier" / "freshness.json").write_text(
            json.dumps({"schema_version": 1, "fragments": {}}),
            encoding="utf-8",
        )
        long_reason = "x" * 500
        update_state_cache(
            repo,
            counts={"fresh": 0, "stale": 0, "critical": 1, "unpinned": 0},
            critical=[{"id": "big", "source": "a.md:1", "reason": long_reason}],
            stale=[],
            computed_at="2026-05-17T12:00:00Z",
            computed_at_sha="b" * 40,
        )
        cache = read_state_cache_safe(repo)
        assert cache is not None
        assert len(cache["critical"][0]["reason"]) == 200

    def test_reader_treats_naive_timestamp_as_stale(
        self, tmp_path: Path
    ) -> None:
        """TP-152 A-1: a timezone-naive ``computed_at`` must read stale,
        not raise ``TypeError`` on the aware/naive comparison (pre-fix
        crashed statusline every prompt + aborted audit-accuracy)."""
        from espalier.freshness import is_state_cache_stale
        cache = {
            "computed_at": "2026-05-17T12:00:00",  # no offset -> naive
            "computed_at_sha": "0" * 40,
            "counts": {"fresh": 0, "stale": 0, "critical": 0, "unpinned": 0},
        }
        assert is_state_cache_stale(cache, repo_root=tmp_path) is True

    def test_committed_bound_change_reads_stale(
        self, tmp_path: Path
    ) -> None:
        """TP-152 A-3 (W17): after a commit touches a pinned fragment's
        bound source, the cache must read stale even though its SHA is a
        recent ancestor — otherwise consumers serve the pre-change
        critical/stale verdicts."""
        from espalier.freshness import (
            is_state_cache_stale,
            read_state_cache_safe,
        )
        repo = _init_repo_with_pinned_fragment(tmp_path)
        rc, _, _ = _run_cli("freshness", "check", str(repo))
        assert rc == 0
        cache = read_state_cache_safe(repo)
        assert cache is not None
        # HEAD == computed_at_sha right after check -> fresh.
        assert is_state_cache_stale(cache, repo_root=repo) is False
        # A commit that edits the bound source (a.py) advances HEAD; the
        # cache SHA is still an ancestor-within-50, so pre-fix this read
        # FRESH. The bound-change guard must now read it stale.
        (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(repo), "add", "-A"],
            check=True, capture_output=True,
        )
        _git(repo, "commit", "-q", "-m", "bump bound source")
        assert is_state_cache_stale(cache, repo_root=repo) is True

    def test_unrelated_commit_keeps_ancestor_cache_fresh(
        self, tmp_path: Path
    ) -> None:
        """TP-152 A-3 guard rail: a commit that does NOT touch a pinned
        bound source must keep the ancestor-within-50 cache fresh — the
        W17 guard invalidates on bound changes, not on any HEAD movement."""
        from espalier.freshness import (
            is_state_cache_stale,
            read_state_cache_safe,
        )
        repo = _init_repo_with_pinned_fragment(tmp_path)
        rc, _, _ = _run_cli("freshness", "check", str(repo))
        assert rc == 0
        cache = read_state_cache_safe(repo)
        assert cache is not None
        # commit an unrelated file (not a pinned bound)
        (repo / "unrelated.txt").write_text("noise\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(repo), "add", "-A"],
            check=True, capture_output=True,
        )
        _git(repo, "commit", "-q", "-m", "unrelated change")
        assert is_state_cache_stale(cache, repo_root=repo) is False

    def test_sha256_head_passes_length_filter(
        self, tmp_path: Path
    ) -> None:
        """TP-152 A-4: a 64-char SHA-256 HEAD must not be rejected by the
        commit-hash length filter (SHA-256 repos otherwise read
        permanently stale)."""
        from espalier.freshness import _git_head_sha_quiet
        repo = tmp_path / "repo256"
        try:
            subprocess.run(
                ["git", "init", "-q", "--object-format=sha256", str(repo)],
                check=True, capture_output=True,
            )
        except subprocess.CalledProcessError:
            pytest.skip("git build lacks --object-format=sha256")
        (repo / "f.txt").write_text("x\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "init")
        sha = _git_head_sha_quiet(repo)
        assert sha is not None and len(sha) == 64


def test_write_manifest_routes_through_atomic_write_text(tmp_path, monkeypatch) -> None:
    """TP-174b R27: _write_manifest must route through the shared
    atomic_write_text helper (random temp name, MAX_PATH cap, cleanup, the
    target's mode), not the inline ``.json.tmp`` write/replace it
    reimplemented before."""
    import espalier.freshness as fr

    calls: list[Path] = []
    real = fr.atomic_write_text

    def _spy(path, content, **kwargs):
        calls.append(Path(path))
        return real(path, content, **kwargs)

    monkeypatch.setattr(fr, "atomic_write_text", _spy)
    manifest = {"schema_version": fr.SCHEMA_VERSION, "fragments": {}}
    fr._write_manifest(tmp_path, manifest)

    expected = tmp_path / fr.MANIFEST_REL_PATH
    assert calls == [expected], (
        f"expected one atomic_write_text({expected}), got {calls}"
    )
    assert json.loads(expected.read_text(encoding="utf-8")) == manifest



class TestLoadManifestForWriteRobustness:
    """TP-191 W2: a present-but-malformed/non-UTF-8 freshness manifest must
    raise the module's typed FreshnessError on the write path, not a bare
    JSONDecodeError / UnicodeDecodeError that tracebacks every freshness
    write caller."""

    def test_malformed_json_raises_freshness_error(self, tmp_path):
        import espalier.freshness as fr
        path = tmp_path / fr.MANIFEST_REL_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not valid json", encoding="utf-8")
        with pytest.raises(fr.FreshnessError):
            fr._load_manifest_for_write(tmp_path)

    def test_non_utf8_raises_freshness_error(self, tmp_path):
        import espalier.freshness as fr
        path = tmp_path / fr.MANIFEST_REL_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xfe\x00bad")
        with pytest.raises(fr.FreshnessError):
            fr._load_manifest_for_write(tmp_path)


class TestFreshnessCheckLeavesTrackedTreeClean:
    """`freshness check` must not dirty the tracked manifest.

    The derived state_cache is relocated to a gitignored per-install file, so a
    bare check writes only that file and leaves ``.espalier/freshness.json`` (the
    committed fragment SoT) byte-identical. Earn-red: RED against the pre-fix code
    (the check rewrites the manifest's ``state_cache`` block every run), GREEN once
    the writer targets the relocated cache file.
    """

    def test_check_does_not_modify_committed_manifest(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo_with_pinned_fragment(tmp_path)
        # _init_repo_with_pinned_fragment leaves .espalier/freshness.json UNTRACKED
        # (pin_fragment writes it after the initial commit). An untracked file reads
        # `??` in porcelain both before AND after the check -- a false RED that never
        # turns GREEN regardless of the fix. Commit it so the assertion discriminates.
        _git(repo, "add", ".espalier/freshness.json")
        _git(repo, "commit", "-q", "-m", "commit manifest")
        precondition = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain",
             ".espalier/freshness.json"],
            check=True, capture_output=True, text=True, encoding="utf-8",
        ).stdout.strip()
        assert precondition == "", (
            f"precondition failed -- manifest not tracked+clean: {precondition!r}"
        )

        rc, _, _ = _run_cli("freshness", "check", str(repo))
        assert rc == 0

        dirty = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain",
             ".espalier/freshness.json"],
            check=True, capture_output=True, text=True, encoding="utf-8",
        ).stdout.strip()
        assert dirty == "", (
            f"freshness check dirtied the tracked manifest: {dirty!r}"
        )


class TestManifestDropsOrphanStateCache:
    """Migration: a pre-relocation manifest that still carries a legacy
    `state_cache` block must have it stripped on the next pin/unpin, so the
    committed manifest converges to fragments+schema_version only and never
    re-commits dead cache data (the shipped "manifest carries ONLY fragments"
    invariant). RED before `_load_manifest_for_write` pops the orphan key.
    """

    def test_pin_strips_orphan_state_cache_block(self, tmp_path: Path) -> None:
        from espalier.freshness import pin_fragment
        repo = _init_repo_with_pinned_fragment(tmp_path)
        manifest = repo / ".espalier" / "freshness.json"
        # Simulate an upgraded checkout: a legacy state_cache block still present
        # in the committed manifest from a pre-relocation espalier version.
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["state_cache"] = {"computed_at": "2026-01-01T00:00:00Z", "counts": {}}
        manifest.write_text(json.dumps(data), encoding="utf-8")
        # A pin loads-mutates-writes the manifest via _load_manifest_for_write.
        pin_fragment("foo", repo, expected_value=1)
        after = json.loads(manifest.read_text(encoding="utf-8"))
        assert "state_cache" not in after, "orphan state_cache survived a pin"
        assert "foo" in after["fragments"]
