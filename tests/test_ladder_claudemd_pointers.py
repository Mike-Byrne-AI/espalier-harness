"""Folder CLAUDE.md pointer/anchor freshness — the make-it-prove-it half of the
ladder-design principle (memory/ladder-claudemd-design.md).

Every folder CLAUDE.md router is a set of POINTERS (the Read-first link, SoT links,
inline command links). A pointer whose target file or anchor rots is a silent lie
that reads as truth. tests/test_folder_claude_md_routers.py pins the router SHAPE
(<=20 lines, the required headers, the single Read-first link, no pack-ids) over a
curated 7-router set; THIS module is the complementary FRESHNESS net over the whole
git-tracked folder-CLAUDE.md population:

  * link half   — every relative markdown link target resolves at HEAD (covers the
                  inline SoT links the router-shape test does not walk).
  * anchor half — every ``symbol``+``file.py:NN`` line anchor resolves within
                  tolerance, reusing the canonical resolver
                  (test_catalog_self_consistency._check_line_anchors_fresh) rather
                  than re-implementing it — the same reuse
                  test_memory_anchor_freshness does for ESPALIER_MEMORY.md.

The link half EXCLUDES the espalier/assets/ mirror twins: their ``../`` links are
relative to the SOURCE's location (e.g. task-packs/), not the mirror's, so resolving
them against the mirror's own parent would false-break. The mirror's byte-parity to
its source is pinned separately (test_deploy_doc_parity), and the links are
resolved in their real deploy context -- against a driven `init` tree -- by
test_adopter_pointer_resolution. The anchor half KEEPS the
mirrors: a ``file.py:NN`` anchor resolves against the source tree regardless of the
doc's location, so scanning the twin is harmless belt-and-suspenders.

Population comes from ``git ls-files`` (drift-proof: a new folder router auto-enrolls;
gitignored scratch is never scanned). An empty result — a non-git export or fresh
clone — SKIPS visibly (fail-closed), mirroring
test_catalog_self_consistency._tracked_anchor_docs, so the module is export-safe
without a full_tree node-id.

What this canNOT catch, named honestly: a pointer whose target COMMAND changed
behavior while staying at the same path (the 0-B case — scope-check.md never moved;
/implement-pack grew around it). Full behavior-drift detection is not mechanically
tractable; see memory/ladder-claudemd-design.md.
"""
from __future__ import annotations

# slow-exempt: the one subprocess call is a single fast `git ls-files` enumeration
import re
import subprocess
from pathlib import Path

import pytest

from test_catalog_self_consistency import _check_line_anchors_fresh

REPO_ROOT = Path(__file__).resolve().parents[1]

# espalier/assets/ carries byte-mirror twins whose relative links are SOURCE-relative
# (they climb ``../`` from the source's location, not the mirror's) — excluded from
# the link half only.
_LINK_EXCLUDE_PREFIXES = ("espalier/assets/",)

_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _tracked_folder_claude_mds() -> list[str]:
    """Every git-tracked ``CLAUDE.md`` via ``git ls-files`` (NOT Path.rglob) so only
    committed surface is walked and a new folder router auto-enrolls. Empty on a
    non-git tree (fresh clone / export) → the caller SKIPS, fail-closed, rather than
    raising at collection."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "*CLAUDE.md"],
            capture_output=True, text=True, check=True, encoding="utf-8",
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return sorted(f for f in out.split() if f.endswith("CLAUDE.md"))


def _broken_links(rel: str, text: str) -> list[str]:
    """Relative markdown link targets in ``text`` that do not resolve, relative to
    the file's own parent. Skips external (http/https/mailto) and pure in-page
    (``#anchor``) links; strips a trailing ``#fragment`` and any ``"title"`` before
    resolving."""
    parent = (REPO_ROOT / rel).parent
    broken: list[str] = []
    for m in _MD_LINK_RE.finditer(text):
        raw = m.group(1).strip()
        if not raw or raw.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = raw.split()[0].split("#", 1)[0]  # drop "title" and #fragment
        if not target:
            continue
        if not (parent / target).resolve().exists():
            broken.append(f"{rel} -> {raw}")
    return broken


def test_folder_claude_md_links_resolve():
    """Link half: every relative markdown link in a folder CLAUDE.md resolves at HEAD
    (mirror twins excluded — their links are source-relative)."""
    files = _tracked_folder_claude_mds()
    if not files:
        pytest.skip("`git ls-files` yielded nothing — not a dev tree / fresh clone")
    broken: list[str] = []
    for rel in files:
        if rel.startswith(_LINK_EXCLUDE_PREFIXES):
            continue
        broken += _broken_links(rel, (REPO_ROOT / rel).read_text(encoding="utf-8"))
    assert not broken, (
        "folder CLAUDE.md relative links that do not resolve (repoint the link, or "
        "fix the target path):\n  " + "\n  ".join(broken)
    )


def test_folder_claude_md_line_anchors_fresh():
    """Anchor half: every ``symbol``+``file.py:NN`` line anchor in a folder CLAUDE.md
    resolves within tolerance, via the reused canonical resolver. Mirror twins
    INCLUDED — line anchors are location-independent. Collects every failure into one
    message instead of stopping at the first."""
    files = _tracked_folder_claude_mds()
    if not files:
        pytest.skip("`git ls-files` yielded nothing — not a dev tree / fresh clone")
    failures: list[str] = []
    for rel in files:
        try:
            _check_line_anchors_fresh(
                (REPO_ROOT / rel).read_text(encoding="utf-8"), doc_rel=rel
            )
        except AssertionError as exc:
            failures.append(f"{rel}: {exc}")
    assert not failures, (
        "stale folder CLAUDE.md `symbol`+`file.py:NN` line anchors (correct the line, "
        "or drop the line number to a drift-proof reference):\n  " + "\n  ".join(failures)
    )


class TestLadderPointerEarnRed:
    """The detectors fire on rot and stay quiet on healthy pointers — proven on
    synthetic text so the earn-red never depends on the live files being dirty."""

    def test_broken_relative_link_detected(self):
        broken = _broken_links(
            "task-packs/CLAUDE.md", "see [x](../does/not/exist_xyz_qqq.md) for detail\n"
        )
        assert broken, "a dangling relative link must be reported"

    def test_resolving_relative_link_not_flagged(self):
        # scope-check.md really exists relative to task-packs/ (the 1-A pointer target).
        broken = _broken_links(
            "task-packs/CLAUDE.md",
            "SoT: [scope-check.md](../.claude/commands/scope-check.md)\n",
        )
        assert not broken

    def test_fragment_stripped_before_resolving(self):
        # A #fragment on a real file must not defeat resolution.
        broken = _broken_links(
            "task-packs/CLAUDE.md",
            "[when](../.claude/commands/scope-check.md#when-to-use)\n",
        )
        assert not broken

    def test_external_and_in_page_links_skipped(self):
        assert not _broken_links("docs/CLAUDE.md", "[site](https://example.com/a)\n")
        assert not _broken_links("docs/CLAUDE.md", "[top](#a-heading)\n")

    def test_stale_line_anchor_detected(self):
        # The reused resolver fires on a deliberately-wrong line number — the same
        # mechanism the anchor half runs over each folder CLAUDE.md.
        stale = "see `_check_line_anchors_fresh` (`tests/test_catalog_self_consistency.py:1`).\n"
        with pytest.raises(AssertionError):
            _check_line_anchors_fresh(stale)
