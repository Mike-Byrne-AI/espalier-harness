"""TP-147 147-G Part 2: ``scripts/check_memory_md_tag_parity.py``
correctly identifies missing-row tags.

Validates the gate against synthetic tag / memory text inputs so
adding the gate to ``harness-guard.yml`` is earned by demonstrated
correctness on the pre-state it was designed to catch (TP-105 pattern:
"earn-the-gate" validation).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _load_parity_script():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import check_memory_md_tag_parity as parity  # type: ignore
        return parity
    finally:
        sys.path.pop(0)


def test_missing_tag_rows_returns_empty_when_all_mentioned():
    parity = _load_parity_script()
    tags = ["v0.7.0", "v0.7.1", "v0.8.0a11"]
    memory = (
        "Session log:\n"
        "| 2026-05-12 | shipped v0.7.0 | ... |\n"
        "| 2026-05-28 | shipped v0.8.0a11 | ... |\n"
    )
    changelog = "## [0.7.1] - 2026-05-19\n[0.7.1]: ...compare/v0.7.0...v0.7.1\n"
    # Mentions in either ESPALIER_MEMORY.md or CHANGELOG.md count.
    assert parity.missing_tag_rows(tags, memory, changelog) == []


def test_missing_tag_rows_flags_unmentioned():
    parity = _load_parity_script()
    tags = ["v0.7.0", "v0.7.1", "v0.7.2"]
    memory = (
        "Session log:\n"
        "| 2026-05-12 | shipped v0.7.0 | ... |\n"
        "| 2026-05-19 | shipped v0.7.1 | ... |\n"
        # v0.7.2 deliberately absent from both surfaces
    )
    assert parity.missing_tag_rows(tags, memory, "") == ["v0.7.2"]


def test_missing_tag_rows_changelog_covers_pruned_rows():
    """CHANGELOG.md is a valid documentation surface — every released
    version earns a ``[X.Y.Z]`` section + footer link, so tags pruned
    out of ESPALIER_MEMORY.md (per its 80-line cap) still satisfy the contract
    via CHANGELOG mention.
    """
    parity = _load_parity_script()
    tags = ["v0.6.0", "v0.8.0a11"]
    memory = "| 2026-05-28 | shipped v0.8.0a11 | ... |\n"
    changelog = "## [0.6.0] - 2026-02-01\n[0.6.0]: ...compare/v0.5...v0.6.0\n"
    assert parity.missing_tag_rows(tags, memory, changelog) == []


def test_missing_tag_rows_empty_when_no_tags():
    parity = _load_parity_script()
    assert parity.missing_tag_rows([], "irrelevant", "") == []


def test_script_returns_zero_against_current_repo_state():
    """Earn-the-gate: the script must exit 0 on the live repo once
    TP-147 147-G Part 1 + Part 2 land. The Part 1 commit (0cadc9e)
    added the v0.8.0a11 row; older tag mentions are anchored in
    CHANGELOG.md's per-version section + footer links.
    """
    parity = _load_parity_script()
    tags = parity.list_release_tags()
    if not tags:
        # Shallow clone / detached HEAD — gate no-ops.
        assert parity.main() == 0
        return
    memory_text = parity.memory_log_text()
    cl_text = parity.changelog_text()
    missing = parity.missing_tag_rows(tags, memory_text, cl_text)
    assert not missing, (
        f"Live ESPALIER_MEMORY.md + CHANGELOG.md missing mention for tag(s): "
        f"{missing}. Add a row to ESPALIER_MEMORY.md before tagging, or fold "
        f"the version section + footer link into CHANGELOG.md."
    )


def test_prefix_colliding_tag_is_not_silently_satisfied():
    """TP-148 148-D: a GA tag (``v0.9.0``) is a substring of an earlier
    prerelease row (``v0.9.0a1``). The bare ``in`` check counted the
    prerelease text as satisfying the GA tag, so the gate could never
    catch its own motivating incident. The anchored match must flag the
    GA tag as missing while leaving the prerelease tag satisfied.
    """
    parity = _load_parity_script()
    missing = parity.missing_tag_rows(
        ["v0.9.0a1", "v0.9.0"],
        memory_text="| 2026-06-01 | shipped v0.9.0a1 | ... |\n",
        changelog_corpus="",
    )
    assert "v0.9.0" in missing
    assert "v0.9.0a1" not in missing


def test_mentions_tag_allows_trailing_sentence_period():
    """TP-267 1-A: a version tag at the end of a sentence (``…v0.9.0.``) must
    still count as mentioned. The old trailing-boundary class ``(?![0-9A-Za-z.])``
    also rejected a bare ``.``, so ``v0.9.0.`` read as un-mentioned → spurious red
    on the live harness-guard CI gate. It must now count, while a genuine version
    continuation (``v0.9.0.1``) and a prerelease suffix (``v0.9.0a1``) still do
    not (the substring-forgery guard is preserved)."""
    parity = _load_parity_script()
    assert parity._mentions_tag("shipped v0.9.0.", "v0.9.0") is True
    assert parity._mentions_tag("v0.9.0.1", "v0.9.0") is False
    assert parity._mentions_tag("v0.9.0a1", "v0.9.0") is False


def test_memory_log_text_returns_empty_when_missing(monkeypatch, tmp_path):
    """TP-267 1-B: a missing ESPALIER_MEMORY.md must yield ``""`` (a clean gate signal),
    not a FileNotFoundError traceback (exit 1 "script error"), matching how the
    sibling ``changelog_text()`` already guards. RED before: ``read_text`` raises."""
    parity = _load_parity_script()
    monkeypatch.setattr(parity, "REPO_ROOT", tmp_path)  # tmp_path has no ESPALIER_MEMORY.md
    assert parity.memory_log_text() == ""
