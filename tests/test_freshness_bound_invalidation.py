"""BC-040 regression coverage: bound change invalidates pin.

The defense has two halves:

- **Scan side:** the scanner compares manifest-stored bound paths
  against fragment-marker bound paths and forces state to
  ``critical`` (with a rebinding-attempt message) on mismatch,
  regardless of the recorded SHA.
- **Pin side:** ``pin_fragment`` refuses to silently overwrite a
  different bound — operator must pass ``force=True`` (CLI:
  ``--force``) to acknowledge the rebinding. Mirrors the
  scan-side defense at the call site so a hurried operator
  cannot clear the critical finding by re-pinning without seeing
  the diff.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


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


def _write_fragment(repo: Path, bound: str) -> None:
    doc = repo / "docs" / "x.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        f"# x\n\n"
        f"<!-- espalier:fragment id=foo bound={bound} policy=weekly -->\n",
        encoding="utf-8",
    )


class TestBoundInvalidation:
    def test_pin_captures_current_bound_paths_into_manifest(
        self, tmp_path: Path
    ) -> None:
        from espalier.freshness import pin_fragment
        repo = _init_repo(tmp_path)
        _write_fragment(repo, "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        entry = pin_fragment("foo", repo)
        assert entry["bound"] == ["a.py"]

    def test_pinned_bound_paths_strips_symbol_suffix(
        self, tmp_path: Path
    ) -> None:
        """TP-171 §4.3: a `path::symbol` bound reduces to the bare path for the
        git pathspec. git treats `path::symbol` as a pathspec matching no file,
        which silently disabled the W17 cache-invalidation guard."""
        from espalier.freshness import pin_fragment, _pinned_bound_paths
        repo = _init_repo(tmp_path)
        _write_fragment(repo, "a.py::some_func")
        (repo / "a.py").write_text(
            "def some_func():\n    return 1\n", encoding="utf-8"
        )
        _commit_all(repo, "init")
        pin_fragment("foo", repo)
        paths = _pinned_bound_paths(repo)
        assert paths == ["a.py"]
        assert all("::" not in p for p in paths)

    def test_symbol_bound_change_detected_as_stale(
        self, tmp_path: Path
    ) -> None:
        """TP-171 §4.3 earn-the-red: a commit touching a `::symbol`-bound source
        is detected as stale. Pre-fix the raw `path::symbol` pathspec matched no
        file, so the guard reported 'not stale' for every such commit."""
        from espalier.freshness import pin_fragment, _pinned_bound_changed_since
        repo = _init_repo(tmp_path)
        _write_fragment(repo, "a.py::some_func")
        (repo / "a.py").write_text(
            "def some_func():\n    return 1\n", encoding="utf-8"
        )
        cache_sha = _commit_all(repo, "init")
        pin_fragment("foo", repo)
        (repo / "a.py").write_text(
            "def some_func():\n    return 2\n", encoding="utf-8"
        )
        _commit_all(repo, "touch bound source")
        assert _pinned_bound_changed_since(repo, cache_sha) is True

    def test_pin_persists_marker_doc_path(self, tmp_path: Path) -> None:
        """TP-191 W3 (W17): the pinned entry records the marker-doc path so the
        cache-invalidation guard can watch the claim doc itself."""
        from espalier.freshness import pin_fragment
        repo = _init_repo(tmp_path)
        _write_fragment(repo, "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        entry = pin_fragment("foo", repo)
        assert entry["marker_path"] == "docs/x.md"

    def test_marker_doc_change_detected_as_stale(self, tmp_path: Path) -> None:
        """TP-191 W3 (W17) earn-the-red: a commit that edits ONLY the claim doc
        (the marker's prose, no bound source) must invalidate the cached scan.
        Pre-fix the W17 guard watched only bound SOURCE paths, so a doc-only
        drift silently reported 'not stale'."""
        from espalier.freshness import pin_fragment, _pinned_bound_changed_since
        repo = _init_repo(tmp_path)
        _write_fragment(repo, "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        cache_sha = _commit_all(repo, "init")
        pin_fragment("foo", repo)
        # Edit the marker doc's prose only; keep the marker line intact (no
        # rebinding) and do NOT touch the bound source a.py.
        doc = repo / "docs" / "x.md"
        doc.write_text(
            doc.read_text(encoding="utf-8") + "\nClarifying prose added later.\n",
            encoding="utf-8",
        )
        _commit_all(repo, "edit marker doc prose only")
        assert _pinned_bound_changed_since(repo, cache_sha) is True

    def test_bound_mismatch_forces_critical_state(
        self, tmp_path: Path
    ) -> None:
        """TP-56-C round-2: a bound redirect after pinning is treated
        as a rebinding attempt and forced to ``critical`` (was
        ``unpinned`` pre-TP-56-C)."""
        from espalier.freshness import pin_fragment, scan_repo
        repo = _init_repo(tmp_path)
        _write_fragment(repo, "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        pin_fragment("foo", repo)
        _write_fragment(repo, "b.py")
        (repo / "b.py").write_text("y = 1\n", encoding="utf-8")
        _commit_all(repo, "redirect bound")
        states = scan_repo(repo)
        assert states[0].state == "critical"
        assert "rebinding attempt" in states[0].message

    def test_added_bound_path_forces_critical(
        self, tmp_path: Path
    ) -> None:
        """TP-56-C round-2: widening the bound list post-pin trips the
        rebinding-attempt escalation."""
        from espalier.freshness import pin_fragment, scan_repo
        repo = _init_repo(tmp_path)
        _write_fragment(repo, "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "b.py").write_text("y = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        pin_fragment("foo", repo)
        _write_fragment(repo, "a.py,b.py")
        _commit_all(repo, "widen bound")
        states = scan_repo(repo)
        assert states[0].state == "critical"
        assert "rebinding attempt" in states[0].message

    def test_removed_bound_path_forces_critical(
        self, tmp_path: Path
    ) -> None:
        """TP-56-C round-2: narrowing the bound list post-pin trips the
        rebinding-attempt escalation."""
        from espalier.freshness import pin_fragment, scan_repo
        repo = _init_repo(tmp_path)
        _write_fragment(repo, "a.py,b.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "b.py").write_text("y = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        pin_fragment("foo", repo)
        _write_fragment(repo, "a.py")
        _commit_all(repo, "narrow bound")
        states = scan_repo(repo)
        assert states[0].state == "critical"
        assert "rebinding attempt" in states[0].message

    def test_re_pinning_after_bound_change_requires_force(
        self, tmp_path: Path
    ) -> None:
        """Pin-time defense: re-pinning a rebound fragment refuses
        without ``force=True``; with ``force=True`` it consents
        and clears the critical finding on the next scan."""
        from espalier.freshness import (
            pin_fragment, scan_repo, RebindingRefusedError,
        )
        repo = _init_repo(tmp_path)
        _write_fragment(repo, "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        pin_fragment("foo", repo)
        _write_fragment(repo, "b.py")
        (repo / "b.py").write_text("y = 1\n", encoding="utf-8")
        _commit_all(repo, "redirect")
        assert scan_repo(repo)[0].state == "critical"
        with pytest.raises(RebindingRefusedError, match="rebind"):
            pin_fragment("foo", repo)
        pin_fragment("foo", repo, force=True)
        states = scan_repo(repo)
        assert states[0].state == "fresh"

    def test_pin_refusal_message_names_both_bound_values(
        self, tmp_path: Path
    ) -> None:
        """The refusal message must show what's being asked to
        change — operator cannot consent (with --force) without
        first seeing the prior bound and the new bound side by
        side."""
        from espalier.freshness import pin_fragment, RebindingRefusedError
        repo = _init_repo(tmp_path)
        _write_fragment(repo, "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        pin_fragment("foo", repo)
        _write_fragment(repo, "b.py")
        (repo / "b.py").write_text("y = 1\n", encoding="utf-8")
        _commit_all(repo, "redirect")
        with pytest.raises(RebindingRefusedError) as exc_info:
            pin_fragment("foo", repo)
        message = str(exc_info.value)
        assert "a.py" in message
        assert "b.py" in message
        assert "--force" in message
        assert "unpin" in message

    def test_first_pin_succeeds_without_force(
        self, tmp_path: Path
    ) -> None:
        """No prior manifest entry means there is no rebinding to
        refuse; first pin must not require ``--force``."""
        from espalier.freshness import pin_fragment
        repo = _init_repo(tmp_path)
        _write_fragment(repo, "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        entry = pin_fragment("foo", repo)
        assert entry["bound"] == ["a.py"]

    def test_idempotent_repin_unchanged_bound_does_not_require_force(
        self, tmp_path: Path
    ) -> None:
        """When the marker's bound matches the manifest's bound,
        re-pinning is idempotent — refreshes SHA + timestamp,
        keeps ``pin --all`` re-runnable for seeding passes."""
        from espalier.freshness import pin_fragment
        repo = _init_repo(tmp_path)
        _write_fragment(repo, "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        pin_fragment("foo", repo)
        entry = pin_fragment("foo", repo)
        assert entry["bound"] == ["a.py"]

    def test_pin_force_consents_to_rebinding(
        self, tmp_path: Path
    ) -> None:
        """``force=True`` overwrites the manifest entry with the
        new bound; the next scan reports the fragment as fresh
        against the new bound."""
        from espalier.freshness import pin_fragment, scan_repo
        repo = _init_repo(tmp_path)
        _write_fragment(repo, "a.py")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        pin_fragment("foo", repo)
        _write_fragment(repo, "b.py")
        (repo / "b.py").write_text("y = 1\n", encoding="utf-8")
        _commit_all(repo, "redirect")
        entry = pin_fragment("foo", repo, force=True)
        assert entry["bound"] == ["b.py"]
        states = scan_repo(repo)
        assert states[0].state == "fresh"


class TestALibraryPinCarriesTheLiteral:
    """The carried literal is ``pin_fragment``'s own contract, not the CLI's.
    A caller that passes no ``expected_value`` gets the entry's literal back
    under ``carried_literal``'s rules, so a script, a hook or the bench that
    imports the library cannot recreate the pre-cut review's D1 (the CLI
    passed ``None`` and the engine, rebuilding the entry from scratch, dropped
    ``hook-count``'s literal) at a new call site. An explicit ``None`` is
    still "record no literal" -- the way a literal is retired on purpose.
    """

    def _numeric_repo(self, tmp_path: Path) -> Path:
        repo = _init_repo(tmp_path)
        doc = repo / "docs" / "x.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(
            "# x\n\n"
            "<!-- espalier:fragment id=foo bound=a.py policy=numeric-contract -->\n",
            encoding="utf-8",
        )
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "init")
        return repo

    def test_a_pin_given_no_literal_carries_the_entrys_own(
        self, tmp_path: Path
    ) -> None:
        from espalier.freshness import pin_fragment
        repo = self._numeric_repo(tmp_path)
        pin_fragment("foo", repo, expected_value=7)
        _commit_all(repo, "pin")
        assert pin_fragment("foo", repo)["expected_value"] == 7

    def test_an_explicit_none_records_no_literal(self, tmp_path: Path) -> None:
        from espalier.freshness import pin_fragment
        repo = self._numeric_repo(tmp_path)
        pin_fragment("foo", repo, expected_value=7)
        _commit_all(repo, "pin")
        assert "expected_value" not in pin_fragment("foo", repo, expected_value=None)

    def test_a_pin_refuses_to_carry_across_a_bound_that_moved(
        self, tmp_path: Path
    ) -> None:
        from espalier.freshness import StaleLiteralRefusedError, pin_fragment
        repo = self._numeric_repo(tmp_path)
        pin_fragment("foo", repo, expected_value=7)
        _commit_all(repo, "pin")
        (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        _commit_all(repo, "the bound moved")
        with pytest.raises(StaleLiteralRefusedError, match="touched its bound"):
            pin_fragment("foo", repo)
        assert pin_fragment("foo", repo, expected_value=8)["expected_value"] == 8
