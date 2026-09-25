"""TP-88 — categorized ``memory/`` + ``docs/sharp-edges/`` folder
bootstrap.

Bootstrap-shape: the convention test runs against the only files
that exist (the two READMEs). As future entries land in ``memory/``
or ``docs/sharp-edges/``, this test scales to cover them
automatically. Pins the layout invariants (filename pattern,
required-section ordering) so the on-demand `/recall` index keeps
parsing both folders without maintenance — without this guard, a typo'd
filename or out-of-order section would silently break the layout that
`/recall`'s parser traverses when it pulls a footgun on demand.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = REPO_ROOT / "memory"
SHARP_EDGES_DIR = REPO_ROOT / "docs" / "sharp-edges"


def _list_md_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.md"))


class TestCategorizedMemoryLayout:
    """TP-88 — bootstrap folder + convention enforcement."""

    def test_memory_folder_exists_with_readme(self):
        assert MEMORY_DIR.is_dir(), (
            "memory/ folder is missing — TP-88 bootstrap incomplete"
        )
        readme = MEMORY_DIR / "README.md"
        assert readme.is_file(), (
            "memory/README.md is missing — folder must self-document"
        )
        first_line = readme.read_text(encoding="utf-8").splitlines()[0]
        assert first_line.startswith("# "), (
            f"memory/README.md must start with an H1 heading; got: {first_line!r}"
        )

    def test_sharp_edges_folder_exists_with_readme(self):
        assert SHARP_EDGES_DIR.is_dir(), (
            "docs/sharp-edges/ folder is missing — TP-88 bootstrap incomplete"
        )
        readme = SHARP_EDGES_DIR / "README.md"
        assert readme.is_file(), (
            "docs/sharp-edges/README.md is missing — folder must self-document"
        )
        first_line = readme.read_text(encoding="utf-8").splitlines()[0]
        assert first_line.startswith("# "), (
            f"docs/sharp-edges/README.md must start with an H1; got: {first_line!r}"
        )

    @pytest.mark.parametrize("folder", [MEMORY_DIR, SHARP_EDGES_DIR])
    def test_subdocs_follow_convention(self, folder):
        """Every .md in the folder (other than README.md / CLAUDE.md) must
        start with an H1 and declare a `**Status:**` line within the first
        10 lines.  README.md is exempt (it documents the convention, not an
        entry); CLAUDE.md is the folder router, governed by
        tests/test_folder_claude_md_routers.py instead."""
        for md_file in _list_md_files(folder):
            if md_file.name in ("README.md", "CLAUDE.md"):
                continue
            lines = md_file.read_text(encoding="utf-8").splitlines()
            assert lines, f"{md_file.relative_to(REPO_ROOT)} is empty"
            assert lines[0].startswith("# "), (
                f"{md_file.relative_to(REPO_ROOT)} must start with H1; "
                f"got: {lines[0]!r}"
            )
            status_present = any(
                "**Status:**" in line for line in lines[:10]
            )
            assert status_present, (
                f"{md_file.relative_to(REPO_ROOT)} must declare "
                f"`**Status:** active|historical|experimental|retired` "
                f"in the first 10 lines"
            )
