"""Release archive cleanliness — TP-RELEASE-03 task 3-D, TP-07,
TP-RELEASE-12.

Builds the release zip via ``scripts/build_release_archive.py``
into a temp directory and validates each member against the
independent denylist in
``tests/test_release_archive_filtering.py::TestArchiveJunkShapes``.

Pins the dual-witness defense against the closed-loop trap that
shipped v0.6.0's ``project.zip``. TP-RELEASE-12 replaced the
original ``surface_contract.classify_release_path`` check (which
was the same function the build script used to choose members — a
tautology) with the independent regex denylist so a classifier
blind spot cannot silence this test. Without two witnesses, a
broken classifier would simultaneously misclassify a file AND
mistakenly pass its own "is this clean?" check, shipping
inappropriate content to the release without any test catching
the divergence.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _archive_member_to_rel(name: str) -> str:
    """Strip the ``espalier-harness-<version>/`` archive prefix."""
    parts = name.split("/", 1)
    if len(parts) == 2 and parts[0].startswith("espalier-harness-"):
        return parts[1]
    return name


@pytest.mark.slow
def test_release_archive_has_no_forbidden_content(tmp_path):
    """The release zip must contain zero junk-by-inspection members.

    TP-RELEASE-12: this test used to validate archive members by calling
    surface_contract.classify_release_path on each — but the build
    script *also* called that same function to choose which members to
    include. Same function on both sides = a tautology. The 0.5.0
    archive shipped four junk classes because the classifier had blind
    spots and this test could not see them.

    The new shape uses the independent denylist maintained in
    tests/test_release_archive_filtering.py::TestArchiveJunkShapes.
    When the denylist and the classifier agree, this test passes.
    When they disagree, this test fails — surfacing a classifier blind
    spot rather than hiding it.
    """
    import re as _re

    # Import shared regex set so this test and TestArchiveJunkShapes
    # cannot drift apart. The denylist is the single canon.
    sys.path.insert(0, str(REPO_ROOT / "tests"))
    try:
        from test_release_archive_filtering import TestArchiveJunkShapes  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from build_release_archive import build_release_archive  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    archive_path = build_release_archive(REPO_ROOT, output_dir=tmp_path)
    assert archive_path.exists(), f"archive was not produced at {archive_path}"
    assert archive_path.stat().st_size > 0, "archive is empty"

    with zipfile.ZipFile(archive_path) as zf:
        members = zf.namelist()
    assert members, "archive has no members"

    offenders: list[tuple[str, str]] = []
    for name in members:
        rel = _archive_member_to_rel(name)
        for pattern, label in TestArchiveJunkShapes.FORBIDDEN_SHAPES:
            if _re.search(pattern, rel):
                offenders.append((name, label))
                break

    if offenders:
        pytest.fail(
            f"Release archive contains {len(offenders)} junk member(s). "
            f"First offender: {offenders[0][0]!r} ({offenders[0][1]}). "
            "The denylist (TestArchiveJunkShapes.FORBIDDEN_SHAPES) is "
            "independent of espalier/surface_contract — if a path here "
            "matches, the classifier has a blind spot. Fix the "
            "classifier; do not relax the denylist."
        )


@pytest.mark.slow
def test_release_archive_includes_public_assets(tmp_path):
    """Defensive: confirm the archive actually carries the public surface.

    A bug in the exclusion logic that excluded too much would silently
    produce a tiny but 'clean' archive. This test lower-bounds the
    archive's coverage of the intentional release surface.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from build_release_archive import build_release_archive  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    archive_path = build_release_archive(REPO_ROOT, output_dir=tmp_path)
    with zipfile.ZipFile(archive_path) as zf:
        members = set(zf.namelist())

    required_substrings = (
        "/README.md",
        "/pyproject.toml",
        "/espalier/cli.py",
        "/tools/cc/hooks/write_guard.py",
        "/.claude/agents/code-reviewer.md",
        "/.claude/commands/preflight.md",
        "/cc/LIVE_SURFACE.md",
        "/tests/test_hooks.py",
    )
    missing = [
        s for s in required_substrings
        if not any(s in m for m in members)
    ]
    assert not missing, (
        "Release archive is missing required public-surface files: "
        f"{missing}. The exclusion logic in "
        "scripts/build_release_archive.py is likely too aggressive."
    )
