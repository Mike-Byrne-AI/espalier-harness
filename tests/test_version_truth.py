"""Version-truth regression tests (Pack 17).

Prevents pyproject.toml, espalier.__version__, and CHANGELOG.md from
silently drifting out of sync. Intentionally avoids any .git dependency
so the suite runs cleanly in wheel/sdist test environments.
"""
from __future__ import annotations

import re
from pathlib import Path

import espalier
from espalier.version_surfaces import VERSION_SURFACES, read_surface_version

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    # Route through the canonical version_surfaces extractor (VERSION_SURFACES[0])
    # instead of re-rolling the pyproject version regex.
    version = read_surface_version(REPO_ROOT, *VERSION_SURFACES[0])
    assert version, "Could not parse version from pyproject.toml"
    return version


def _current_minor() -> str:
    """`0.8.0a13` -> `0.8` (the major.minor the package currently lives on)."""
    m = re.match(r"(\d+)\.(\d+)", espalier.__version__)
    assert m, f"cannot parse __version__: {espalier.__version__!r}"
    return f"{m.group(1)}.{m.group(2)}"


# Narrative surfaces that describe "what ships now" / roadmap in prose. These
# drifted to v0.7 while the package crossed to 0.8 because nothing bound the
# prose to __version__ (TP-177 root #2). CHANGELOG owns concrete version pins
# (covered above) and is intentionally excluded.
_VERSION_PROSE_SURFACES = (
    "README.md",
    "examples/dogfooding/README.md",
    "docs/SECURITY_TAXONOMY.md",
)


def test_narrative_prose_carries_no_stale_version_token():
    """Any ``v0.<minor>`` token in narrative prose whose minor != the current
    package minor is a drift bomb: it claims a version the package has left
    behind (or forward-promises an unbuilt one). Keep these surfaces
    version-agnostic ("a future release", "current releases"); let CHANGELOG
    own the concrete pins. (TP-177 W3-1)
    """
    minor = _current_minor()  # e.g. "0.8"
    tok = re.compile(r"\bv(0\.\d+)")
    offenders: list[str] = []
    for rel in _VERSION_PROSE_SURFACES:
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            for m in tok.finditer(line):
                if m.group(1) != minor:
                    offenders.append(f"{rel}:{lineno}: {m.group(0)}")
    assert not offenders, (
        f"narrative prose names a version != current package minor (v{minor}); "
        f"make it version-agnostic or correct the token:\n  "
        + "\n  ".join(offenders)
    )


def test_pyproject_version_matches_runtime_version():
    pyproject_ver = _pyproject_version()
    runtime_ver = espalier.__version__
    assert pyproject_ver == runtime_ver, (
        f"pyproject.toml version ({pyproject_ver}) != "
        f"espalier.__version__ ({runtime_ver})"
    )


def test_changelog_has_current_version_section():
    version = _pyproject_version()
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"[{version}]" in changelog, (
        f"CHANGELOG.md has no section for version {version} — add a release entry"
    )


def test_changelog_unreleased_link_starts_from_current_version():
    """[Unreleased] compare-link base must reference either the
    current pyproject version OR (during a prerelease cycle) the
    most recent stable.

    TP-145 relaxation: when pyproject is on a prerelease (vX.Y.ZaN /
    bN / rcN), the link can legitimately remain anchored to the
    prior stable version per `tests/test_changelog_footer.py`'s
    monotonicity contract. The two contracts must agree on the
    prerelease-cycle shape — pre-TP-145 they disagreed and one
    forced the other to break.
    """
    version = _pyproject_version()
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^\[Unreleased\]:\s*(.+)", changelog, re.MULTILINE)
    assert m, "CHANGELOG.md has no [Unreleased] compare link"
    link = m.group(1).strip()
    if f"v{version}" in link:
        return
    # Allow the prerelease-cycle anchor: extract the base from the
    # link and confirm it's a stable version <= current.
    base_m = re.search(r"/compare/v([^\s.]+(?:\.[^\s.]+)*)\.\.\.HEAD", link)
    assert base_m, (
        f"[Unreleased] compare link does not start from v{version} "
        f"and could not parse the link base: {link}"
    )
    base = base_m.group(1)
    is_prerelease = bool(re.search(r"(?:a|b|rc)\d+$", version))
    is_base_stable = not re.search(r"(?:a|b|rc)\d+$", base)
    assert is_prerelease and is_base_stable, (
        f"[Unreleased] compare link does not start from v{version}: "
        f"{link}. Prerelease-cycle relaxation only applies when "
        f"pyproject is on a prerelease tag and the link base is a "
        f"stable version (pyproject={version}, base={base})."
    )
