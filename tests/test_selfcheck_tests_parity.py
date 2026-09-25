"""Parity between the curated ``tests/`` subset and its engine-package mirror at
``espalier/_vendor/selfcheck_tests/``.

The curated host-agnostic engine-integrity tests live canonically in ``tests/``.
A mirror inside the engine package lets ``espalier selfcheck`` run them against
the INSTALLED engine (the wheel ships the mirror as package-data; ``fuse``
overlays all of ``espalier/``). This test reds if the mirror drifts from the
curation rule applied to the current ``tests/`` — run
``python scripts/sync_selfcheck_tests.py`` to re-sync.

The curation rule is sourced from ``scripts/sync_selfcheck_tests.py`` (single
SoT) rather than re-declared here, so the bijection cannot silently diverge from
what the sync script actually copies. Two flavours of mirrored file:

* ``BYTE_MIRRORED`` — pinned byte-identical to source (same as ``_vendor/cc``).
* ``TRANSFORMED`` — pinned to the deterministic transform re-applied to current
  source (``conftest.py`` / ``test_scanners.py``) or to the authored constant
  (``pytest.ini``).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "tests"
MIRROR = REPO_ROOT / "espalier" / "_vendor" / "selfcheck_tests"


def _load_sync():
    path = REPO_ROOT / "scripts" / "sync_selfcheck_tests.py"
    spec = importlib.util.spec_from_file_location("_sync_selfcheck_tests", path)
    assert spec and spec.loader, f"cannot load sync script at {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mirror_files() -> set[str]:
    """Mirror-relative file names, excluding ``__pycache__``."""
    if not MIRROR.exists():
        return set()
    return {
        p.relative_to(MIRROR).as_posix()
        for p in MIRROR.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }


class TestSelfcheckTestsParity:
    def test_mirror_matches_curation_file_set(self):
        sync = _load_sync()
        expected = set(sync.BYTE_MIRRORED) | set(sync.TRANSFORMED)
        mirror = _mirror_files()
        assert expected == mirror, (
            "selfcheck mirror file-set diverged from the curation rule "
            "(run `python scripts/sync_selfcheck_tests.py`): "
            f"only curated={sorted(expected - mirror)}; "
            f"only in mirror={sorted(mirror - expected)}"
        )

    def test_byte_mirrored_files_are_identical(self):
        sync = _load_sync()
        mismatched = sorted(
            rel
            for rel in sync.BYTE_MIRRORED
            if (SRC / rel).read_bytes() != (MIRROR / rel).read_bytes()
        )
        assert not mismatched, (
            "selfcheck mirror drifted from source byte-for-byte "
            f"(run `python scripts/sync_selfcheck_tests.py`): {mismatched}"
        )

    def test_test_scanners_matches_curated_transform(self):
        sync = _load_sync()
        expected = sync._transform_test_scanners(
            (SRC / "test_scanners.py").read_text(encoding="utf-8")
        )
        actual = (MIRROR / "test_scanners.py").read_text(encoding="utf-8")
        assert actual == expected, (
            "selfcheck mirror test_scanners.py drifted from the curated "
            "transform of tests/test_scanners.py (run "
            "`python scripts/sync_selfcheck_tests.py`)"
        )

    def test_test_scanners_drops_source_dir_classes(self):
        text = (MIRROR / "test_scanners.py").read_text(encoding="utf-8")
        for dropped in (
            "TestScannerSelfContainment",
            "TestScannerExemptPrefixesParity",
            "Path(__file__)",
        ):
            assert dropped not in text, f"mirror test_scanners.py still has {dropped!r}"
        for kept in ("TestScanners", "TestGodfilesThreshold", "TestTestLoosening"):
            assert kept in text, f"mirror test_scanners.py is missing {kept!r}"

    def test_conftest_matches_curated_transform(self):
        sync = _load_sync()
        expected = sync._transform_conftest(
            (SRC / "conftest.py").read_text(encoding="utf-8")
        )
        actual = (MIRROR / "conftest.py").read_text(encoding="utf-8")
        assert actual == expected, (
            "selfcheck mirror conftest.py drifted from the curated transform of "
            "tests/conftest.py (run `python scripts/sync_selfcheck_tests.py`)"
        )

    def test_conftest_carries_portable_fixtures_only(self):
        text = (MIRROR / "conftest.py").read_text(encoding="utf-8")
        for fixture in (
            "_isolate_maintenance_mode",
            "_isolate_audit_dir",
            "python_repo",
            "ml_repo",
            "node_repo",
            "typescript_repo",
            "go_repo",
            "polyglot_repo",
        ):
            assert f"def {fixture}(" in text, f"mirror conftest missing {fixture!r}"
        for self_host in ("harness_repo", "initialized_repo_root", "REPO_ROOT"):
            assert self_host not in text, f"mirror conftest leaked {self_host!r}"

    def test_pytest_ini_silences_marker_warning_and_cache(self):
        text = (MIRROR / "pytest.ini").read_text(encoding="utf-8")
        assert "PytestUnknownMarkWarning" in text
        assert "-p no:cacheprovider" in text

    def test_mirror_is_nonempty(self):
        # Guards against a refactor silently emptying the mirror, which would make
        # the bijection assertion vacuously true (empty == empty).
        assert _mirror_files(), "espalier/_vendor/selfcheck_tests has no files"
