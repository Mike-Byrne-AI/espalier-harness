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
import sys
from pathlib import Path
from tests._live_tree import checkout_rglob

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
        for p in checkout_rglob(MIRROR, "*")
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

    def test_every_curated_name_is_a_direct_child_of_tests(self):
        """The mirror is flat, and that is a contract here, not a comment.

        The edit-time advisory's source-side pattern
        (``_SELFCHECK_SOT_RE`` in ``tools/cc/hooks/_reinject.py``) keeps the slash
        out of its name class, so it reads a direct child of ``tests/`` only. A
        curated name under a subdirectory would leave its file outside the
        advisory while every parity test here stayed green, and an edit of it
        would go without the reminder to sync.
        """
        hooks = str(REPO_ROOT / "tools" / "cc" / "hooks")
        if hooks not in sys.path:
            sys.path.insert(0, hooks)
        import _reinject  # the hook's own pattern, never a restated copy of it

        sync = _load_sync()
        unread = sorted(
            n for n in (*sync.BYTE_MIRRORED, *sync.TRANSFORMED)
            if not _reinject._SELFCHECK_SOT_RE.search("tests/" + n)
        )
        assert not unread, (
            f"curated selfcheck names the advisory cannot read: {unread}. "
            "_SELFCHECK_SOT_RE reads a direct child of tests/ ending .py or .ini: "
            "widen its name class and the comment above it in the same change, or "
            "keep the name flat."
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

    def test_no_mirrored_module_imports_the_source_tests_package(self):
        """The mirror runs inside an installed engine, where no ``tests``
        package exists. ``tests/test_scanners.py`` imports ``tests._live_tree``
        inside the methods of the two classes the transform drops (DEF-2013);
        hoisting that import would ship a mirror that fails to import on every
        adopter's ``espalier selfcheck``, and no workflow runs one."""
        import ast

        leaks = []
        for rel in sorted(_mirror_files()):
            if not rel.endswith(".py"):
                continue
            for node in ast.walk(ast.parse((MIRROR / rel).read_text(encoding="utf-8"))):
                names = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                         else [a.name for a in node.names] if isinstance(node, ast.Import) else [])
                leaks += [f"{rel}:{node.lineno} {n}" for n in names if n == "tests" or n.startswith("tests.")]
        assert not leaks, f"mirrored modules import the source tests package: {leaks}"

    def test_pytest_ini_silences_marker_warning_and_cache(self):
        text = (MIRROR / "pytest.ini").read_text(encoding="utf-8")
        assert "PytestUnknownMarkWarning" in text
        assert "-p no:cacheprovider" in text

    def test_mirror_is_nonempty(self):
        # Guards against a refactor silently emptying the mirror, which would make
        # the bijection assertion vacuously true (empty == empty).
        assert _mirror_files(), "espalier/_vendor/selfcheck_tests has no files"
