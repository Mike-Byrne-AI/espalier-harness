"""Every VERSION_SURFACES entry must equal pyproject.version. This fails at
pytest time the moment a bump skews a surface — the witness that would have
caught the v0.8.0a12 bench/RESULTS.md skew before it hit CI. Per TP-148 148-A."""
from __future__ import annotations

import sys
from pathlib import Path

from espalier.version_surfaces import VERSION_SURFACES, read_surface_version

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_all_version_surfaces_match_pyproject():
    canonical = read_surface_version(REPO_ROOT, *VERSION_SURFACES[0])
    drift = {
        relpath: got
        for relpath, pattern in VERSION_SURFACES[1:]
        if (got := read_surface_version(REPO_ROOT, relpath, pattern)) is not None
        and got != canonical
    }
    assert not drift, f"version surfaces disagree with pyproject {canonical!r}: {drift}"


def _import_release_check():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import release_check  # noqa: E402

    return release_check


def test_stranded_surface_fails_gate(tmp_path):
    """TP-149 (E-4): a version surface that is PRESENT but whose version
    literal no longer matches its extractor (format drift) must FAIL
    check_version_consistent — not be silently treated as "agrees" because
    read_surface_version collapses absent + no-match to None (§1.11 gate
    credibility). Earn-the-red: skew a copy so espalier/__init__.py is
    present but the __version__ regex misses; assert FAIL + "stranded"."""
    rc = _import_release_check()

    (tmp_path / "pyproject.toml").write_text('version = "9.9.9"\n', encoding="utf-8")
    pkg = tmp_path / "espalier"
    pkg.mkdir()
    # Present but mangled: the `^__version__ = "..."` extractor will not
    # match (no quotes), so read_surface_version returns None → stranded.
    (pkg / "__init__.py").write_text("__version__ = BROKEN_NO_QUOTES\n", encoding="utf-8")
    # bench/RESULTS.md deliberately absent — that path must be SKIPPED, not
    # flagged, so the only drift is the stranded __init__.py.

    result = rc.check_version_consistent(tmp_path)
    assert result.status == "FAIL", (
        f"stranded surface must FAIL the gate, got {result.status!r}: {result.detail}"
    )
    assert "stranded" in result.detail.lower(), (
        f"FAIL detail must name the stranded surface, got: {result.detail}"
    )


def test_absent_surface_is_skipped_not_stranded(tmp_path):
    """Companion to test_stranded_surface_fails_gate: an ABSENT optional
    surface (adopter without bench/RESULTS.md) must NOT be flagged as
    drift — only present-but-unmatched surfaces strand."""
    rc = _import_release_check()

    (tmp_path / "pyproject.toml").write_text('version = "9.9.9"\n', encoding="utf-8")
    pkg = tmp_path / "espalier"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    # No bench/RESULTS.md, no CHANGELOG → the surface loop must pass; the
    # FAIL (if any) comes from the later CHANGELOG check, never "stranded".
    result = rc.check_version_consistent(tmp_path)
    assert "stranded" not in result.detail.lower(), (
        f"absent surface wrongly flagged as stranded: {result.detail}"
    )
