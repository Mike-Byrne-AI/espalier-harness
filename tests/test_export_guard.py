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
    return {
        pat for pat in surface_contract.export_ignore_patterns(REPO_ROOT)
        if not pat.endswith("/") and not any(ch in pat for ch in "*?[")
    }


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
        others = sorted(_sentinels() - {"ESPALIER_MEMORY.md"})
        assert others, "test setup: no sentinel besides the memory file"
        target = synthesized_export / others[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# a maintainers-only doc\n", encoding="utf-8")
        assert not surface_contract.is_release_export(synthesized_export), others[0]


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
