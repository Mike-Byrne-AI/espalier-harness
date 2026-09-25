"""``tests/_export_guard.py`` -- the per-arm export guard, witnessed on both trees.

The guard returns the empty set on the dev tree by construction, so a suite
run here cannot tell a working guard from ``return set()``: these arms build a
minimal tree ``is_release_export`` accepts and drive the guard there, including
the must-NOT-trip twin -- an entry naming a shipped file is never forgiven.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from espalier import surface_contract
from tests._export_guard import AUDIT_ENV, pruned_from_this_tree
from tests._git_oracle import GitAnswerUnavailable, require_is_gitignored

REPO_ROOT = Path(__file__).resolve().parent.parent

# A path every export-ignore pattern on this tree leaves alone.
SHIPPED = ("docs/CONVENTIONS.md", "espalier/cli.py", "tests/conftest.py")


@pytest.fixture
def synthesized_export(tmp_path: Path) -> Path:
    """The smallest tree ``is_release_export`` says True for.

    The self-host layout (``espalier/``, ``tools/cc/``, ``bench/``, the
    pyproject name, the pinned ``write_guard.py`` prefix) plus the real
    ``.gitattributes``; every plain-file export-ignore sentinel is absent by
    construction because nothing else is copied.
    """
    target = tmp_path / "export"
    for rel in ("espalier", "tools/cc/hooks", "bench"):
        (target / rel).mkdir(parents=True)
    for rel in ("pyproject.toml", "tools/cc/hooks/write_guard.py", ".gitattributes"):
        shutil.copy2(REPO_ROOT / rel, target / rel)
    assert surface_contract.is_release_export(target), (
        "test setup: the synthesized tree is not detected as a release export"
    )
    return target


def _sentinels() -> set[str]:
    """The live sentinel set, derived from the one helper ``is_release_export``
    reads -- never a re-copied filter, which rots the moment the helper's
    exclusions change."""
    return set(surface_contract.export_sentinels(REPO_ROOT))


class TestIsReleaseExport:
    def test_a_seeded_memory_file_does_not_unmake_an_export(self, synthesized_export):
        """DEC-31's third tree shape. The public repository is an export that
        grows ``ESPALIER_MEMORY.md`` at the seed (docs/RELEASE_CHECKLIST.md step
        5) and at every handoff after it. The memory file is harness-managed
        (cc/PACK_MANIFEST.txt names it) and present in every governed tree, so it
        says nothing about which tree this is. Until 2026-09-24 it was a sentinel:
        creating it flipped the discriminator, which switched off the full_tree
        auto-skip and the export guard on the public repository (Round 12)."""
        assert surface_contract.is_release_export(synthesized_export)
        (synthesized_export / "ESPALIER_MEMORY.md").write_text("# seeded\n", encoding="utf-8")
        assert surface_contract.is_release_export(synthesized_export), (
            "a seeded ESPALIER_MEMORY.md must not unmake an export (DEC-31)"
        )

    def test_any_other_sentinel_still_unmakes_an_export(self, synthesized_export):
        """The must-trip twin: the remaining sentinels keep their meaning."""
        others = sorted(_sentinels())
        assert others, "test setup: no sentinel besides the forgiven rows"
        target = synthesized_export / others[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# a maintainers-only doc\n", encoding="utf-8")
        assert not surface_contract.is_release_export(synthesized_export), others[0]

    def test_a_harness_grown_gitignored_file_does_not_unmake_an_export(
        self, synthesized_export
    ):
        """The third harness-grown shape (2026-09-25). ``docs/session-archive.md``
        is export-ignored (the cleanliness gate reads it as internal) AND
        gitignored (the memory prune's overflow tank, created on whichever tree
        the prune runs in). On the public tree the first over-cap handoff wrote
        it, the discriminator flipped, and 29 contract-tier tests ran red against
        pruned content. The ignore row is the signal: a file the tree declares
        local cannot tell the trees apart."""
        shutil.copy2(REPO_ROOT / ".gitignore", synthesized_export / ".gitignore")
        assert surface_contract.is_release_export(synthesized_export)
        archive = synthesized_export / "docs" / "session-archive.md"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text("# archived rows\n", encoding="utf-8")
        assert surface_contract.is_release_export(synthesized_export), (
            "a gitignored, harness-grown docs/session-archive.md must not unmake "
            "an export"
        )

    def test_the_forgiveness_comes_from_the_ignore_row_not_the_name(
        self, synthesized_export
    ):
        """The must-trip twin: the same file on a tree with no ``.gitignore`` is
        an ordinary sentinel again, so the exclusion is derived from the ignore
        file and never hard-coded by name."""
        assert not (synthesized_export / ".gitignore").exists()
        archive = synthesized_export / "docs" / "session-archive.md"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text("# archived rows\n", encoding="utf-8")
        assert not surface_contract.is_release_export(synthesized_export)

    def test_export_sentinels_match_what_git_ignores(self) -> None:
        """Closed-world pin with git as the independent oracle: a plain-file
        export-ignore row is a sentinel exactly when it is neither named in
        ``_EXPORT_SENTINEL_EXCLUSIONS`` nor ignored by git. A future ignore row
        spelled as a glob or a directory that covers a sentinel reds HERE, at
        the row, instead of as 29 contract failures after the next handoff.
        Rows are compared with a leading ``/`` stripped, the way the helper
        returns them: an anchored row passed raw makes ``git check-ignore``
        exit 128, and this pin would skip at the one row it exists to catch."""
        plain = [
            pat.lstrip("/")
            for pat in surface_contract.export_ignore_patterns(REPO_ROOT)
            if not pat.endswith("/") and not any(ch in pat for ch in "*?[")
        ]
        try:
            ignored = {rel for rel in plain if require_is_gitignored(REPO_ROOT, rel)}
        except GitAnswerUnavailable as exc:
            pytest.skip(f"git cannot answer about this tree: {exc}")
        expected = [
            pat
            for pat in plain
            if pat not in surface_contract._EXPORT_SENTINEL_EXCLUSIONS
            and pat not in ignored
        ]
        assert surface_contract.export_sentinels(REPO_ROOT) == expected
        # Non-vacuity: the live tree carries one row of each forgiven kind.
        assert "ESPALIER_MEMORY.md" in plain
        assert "docs/session-archive.md" in ignored
        assert expected, "test setup: the live tree yields no sentinel at all"

    def test_an_exact_negation_row_un_forgives(self, synthesized_export):
        """Last match wins, as git reads it: ``docs/session-archive.md`` then
        ``!docs/session-archive.md`` leaves the file an ordinary sentinel."""
        (synthesized_export / ".gitignore").write_text(
            "docs/session-archive.md\n!docs/session-archive.md\n", encoding="utf-8"
        )
        archive = synthesized_export / "docs" / "session-archive.md"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text("# archived rows\n", encoding="utf-8")
        assert not surface_contract.is_release_export(synthesized_export)

    def test_no_harness_managed_file_is_a_sentinel(self) -> None:
        """The tracked-and-grown class, caught at the row: a file the harness
        writes on every tree (cc/PACK_MANIFEST.txt lists them) that is also
        export-ignored must be forgiven -- by name in
        ``_EXPORT_SENTINEL_EXCLUSIONS`` or by an exact ``.gitignore`` row --
        else its first creation on the public clone flips the discriminator.
        Derived from the helper, so it holds whichever mechanism forgives."""
        manifest = REPO_ROOT / "cc" / "PACK_MANIFEST.txt"
        if not manifest.is_file():
            pytest.skip("no cc/PACK_MANIFEST.txt on this tree")
        managed = {
            line.strip()
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        # Non-vacuity: the memory file is managed AND export-ignored.
        assert "ESPALIER_MEMORY.md" in managed
        assert "ESPALIER_MEMORY.md" in surface_contract.export_ignore_patterns(REPO_ROOT)
        leaking = managed & set(surface_contract.export_sentinels(REPO_ROOT))
        assert not leaking, (
            f"harness-managed export-ignored file(s) still read as sentinels: "
            f"{sorted(leaking)} -- add each to _EXPORT_SENTINEL_EXCLUSIONS (tracked "
            "here) or an exact .gitignore row (untracked everywhere)"
        )


class TestPrunedFromThisTree:
    def test_inert_on_the_dev_tree(self) -> None:
        """Positive confirmation only: here nothing is forgiven, so every
        self-expiry arm runs unchanged."""
        assert not surface_contract.is_release_export(REPO_ROOT)
        assert pruned_from_this_tree(sorted(_sentinels()) + list(SHIPPED)) == set()

    def test_forgives_an_export_ignored_entry_on_an_export(self, synthesized_export):
        sentinels = _sentinels()
        assert sentinels, "test setup: .gitattributes yields no plain-file sentinel"
        forgiven = pruned_from_this_tree(sorted(sentinels), synthesized_export)
        assert forgiven == sentinels, (forgiven, sentinels)

    def test_forgives_a_glob_and_a_directory_pattern_too(self, synthesized_export):
        """The patterns are matched by ``matches_export_ignore``, not equality:
        ``memory/*-atlas.md`` and ``/task-packs/`` prune by shape."""
        patterns = surface_contract.export_ignore_patterns(REPO_ROOT)
        globbed = [p for p in patterns if "*" in p]
        dirs = [p for p in patterns if p.endswith("/")]
        assert globbed and dirs, "test setup: expected a glob and a directory pattern"
        probes = [
            globbed[0].replace("*", "some-name"),
            dirs[0].strip("/") + "/inside.md",
        ]
        assert pruned_from_this_tree(probes, synthesized_export) == set(probes)

    def test_never_forgives_a_shipped_entry_on_an_export(self, synthesized_export):
        """THE NEGATIVE TWIN. An entry naming a file the export ships is not
        pruned, so a roster naming a shipped file that is gone still reds."""
        forgiven = pruned_from_this_tree(list(SHIPPED), synthesized_export)
        assert forgiven == set(), forgiven

    def test_the_audit_switch_forgives_nothing_even_on_an_export(
        self, synthesized_export, monkeypatch
    ):
        """``ESPALIER_FULL_TREE_AUDIT`` is the one self-expiry oracle for
        full-tree suppressions; this guard folds into it rather than opening a
        second, un-audited one."""
        monkeypatch.setenv(AUDIT_ENV, "1")
        assert pruned_from_this_tree(sorted(_sentinels()), synthesized_export) == set()
