"""CHANGELOG footer link order contract.

Keep-a-Changelog convention is newest-first. The `[Unreleased]` row is
followed by version-tagged compare links in descending semver order.

This test exists because the `[0.7.0]` link drifted to a between-the-
patches position during the v0.7.0 fold-up and survived three
consecutive releases without detection (release-verifier audit
2026-05-19).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ``packaging`` is a [project.optional-dependencies.dev] dep, not a base
# install dep. Use importorskip so a contributor who forgot
# ``pip install -e ".[dev]"`` gets a clean skip rather than a collection
# error that wipes the whole pytest session.
packaging_version = pytest.importorskip("packaging.version")
InvalidVersion = packaging_version.InvalidVersion
Version = packaging_version.Version


REPO_ROOT = Path(__file__).parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

_FOOTER_LINE_RE = re.compile(
    r"^\[(?P<label>[^\]]+)\]:\s+\S+"
)


def _parse_footer_versions() -> list[tuple[str, Version | None]]:
    """Return (label, parsed-version-or-None) for each footer line.

    `[Unreleased]` is the first row by convention and is returned as
    (label, None). Every other row must parse as a PEP-440 version.
    """
    text = CHANGELOG.read_text(encoding="utf-8")
    rows: list[tuple[str, Version | None]] = []
    in_footer = False
    for line in text.splitlines():
        if line.startswith("[Unreleased]:"):
            in_footer = True
            rows.append(("Unreleased", None))
            continue
        if not in_footer:
            continue
        match = _FOOTER_LINE_RE.match(line)
        if not match:
            if line.strip() == "":
                continue
            break
        label = match.group("label")
        try:
            parsed = Version(label)
        except InvalidVersion:
            parsed = None
        rows.append((label, parsed))
    return rows


def test_changelog_footer_is_newest_first_monotonic() -> None:
    """Every footer row after `[Unreleased]` must parse as a version
    AND must be strictly less than the row immediately above it."""
    rows = _parse_footer_versions()
    assert rows, "CHANGELOG footer link block not found"
    assert rows[0] == ("Unreleased", None), (
        f"first footer row must be [Unreleased], got {rows[0][0]!r}"
    )

    failures: list[str] = []
    previous: Version | None = None
    previous_label = "Unreleased"
    for label, version in rows[1:]:
        if version is None:
            failures.append(f"row [{label}] does not parse as PEP-440")
            continue
        if previous is not None and version >= previous:
            failures.append(
                f"row [{label}] (={version}) appears below "
                f"[{previous_label}] (={previous}) but is NOT strictly "
                f"older -- footer is not newest-first"
            )
        previous = version
        previous_label = label

    assert not failures, "\n".join(failures)


def test_changelog_footer_unreleased_base_matches_latest_stable() -> None:
    """`[Unreleased]: .../compare/<base>...HEAD` -- the <base> must
    equal the newest NON-PRERELEASE version in the footer.

    Relaxed for prerelease cycles: during a prerelease ladder the
    operator legitimately leaves `[Unreleased]` pointing at the prior
    stable while a new prerelease tag (e.g., v0.8.0a1) exists.
    """
    text = CHANGELOG.read_text(encoding="utf-8")
    rows = _parse_footer_versions()
    assert len(rows) >= 2, "footer has fewer than 2 rows"

    newest_stable: tuple[str, Version | None] | None = None
    for label, version in rows[1:]:
        if version is None:
            continue
        if version.is_prerelease:
            continue
        newest_stable = (label, version)
        break

    assert newest_stable is not None, (
        "no non-prerelease version row found in footer"
    )

    unreleased_line_re = re.compile(
        r"^\[Unreleased\]:\s+\S+/compare/v(?P<base>\S+?)\.\.\.HEAD\s*$",
        re.MULTILINE,
    )
    match = unreleased_line_re.search(text)
    assert match is not None, (
        "[Unreleased]: ...compare/v<X>...HEAD line not found"
    )
    assert match.group("base") == newest_stable[0], (
        f"[Unreleased] base v{match.group('base')} does not match "
        f"newest non-prerelease footer row v{newest_stable[0]}"
    )
