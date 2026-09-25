"""TP-07 — release archive filtering parity.

One classifier in ``espalier.surface_contract`` is the SoT used by
``release_pack.py``, ``scripts/build_release_archive.py``, and the
``scripts/release_check.py`` archive scanner. These tests pin the
classifier's behavior on every known risky path and prove the build
script and the scanner agree by construction.
"""
from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

from espalier import surface_contract

from tests._symlink_support import requires_symlink

REPO_ROOT = Path(__file__).resolve().parent.parent

# Marker assignment lives in tests/conftest.py::_MARKER_RULES.


# ---------------------------------------------------------------------------
# classify_release_path correctness for known risky paths (pack §2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path,expected_bucket", [
    # Public — included in release
    ("README.md", "public"),
    ("LICENSE", "public"),
    ("CHANGELOG.md", "public"),
    ("espalier/cli.py", "public"),
    ("tests/test_foo.py", "public"),
    ("cc/COMMANDS.md", "public"),
    ("cc/LIVE_SURFACE.md", "public"),
    ("cc/PACK_MANIFEST.txt", "public"),
    (".github/workflows/release.yml", "public"),
    ("bench/RESULTS.md", "public"),
    ("bench/corpus/example.json", "public"),
    # Local-only — gitignored or experimental
    (".claude/settings.local.json", "local_only"),
    ("cc/SURFACE_HANDOFF.md", "local_only"),
    # BLUEPRINT_HANDOFF.md matches the BLUEPRINT*.md internal pattern;
    # internal check runs before local_only.
    ("cc/BLUEPRINT_HANDOFF.md", "internal"),
    ("cc/execution_plan.json", "local_only"),
    ("cc/blueprints/20260101.json", "local_only"),
    ("reports/repo_fingerprint.json", "local_only"),
    ("reports/foo/bar.json", "local_only"),
    ("bench/results/run_20260101.md", "local_only"),
    ("bench/end_to_end/runs/2026.json", "local_only"),
    ("zDone/old_pack.md", "local_only"),
    ("Finished Tasks/x.md", "local_only"),
    ("receiver-test/log.txt", "local_only"),
    # Internal — planning/internal docs
    ("TP-FOO.md", "internal"),
    ("BLUEPRINT_X.md", "internal"),
    ("TASK_PACK_1.md", "internal"),
    ("docs/session-archive.md", "internal"),
    ("docs/internal/secret.md", "internal"),
    # Transient — caches, build outputs, junk
    (".DS_Store", "transient"),
    ("Thumbs.db", "transient"),
    ("__pycache__/foo.pyc", "transient"),
    ("espalier/__pycache__/foo.pyc", "transient"),
    ("dist/wheel.whl", "transient"),
    ("build/lib/foo.py", "transient"),
    ("foo.egg-info/PKG-INFO", "transient"),
    (".pytest_cache/v/cache/lastfailed", "transient"),
    (".venv/lib/python3.12/site-packages/x.py", "transient"),
    # TP-RELEASE-11 — workspace files (was: public; classifier missing the rule)
    ("foo.code-workspace", "transient"),
    ("MyProject 3.code-workspace1.code-workspace", "transient"),  # mangled-suffix shape
    ("utws 2.code-workspace", "transient"),
    ("subdir/nested.code-workspace", "transient"),
    # TP-RELEASE-11 — browser/Finder download dupes
    ("docs/docs-README (1).md", "transient"),
    ("foo (1).md", "transient"),
    ("report (12).pdf", "transient"),
    ("utws 2.code-workspace", "transient"),  # also caught by workspace rule
    # Negative cases — must NOT match dupe shapes
    ("docs/v2.md", "public"),
    ("docs/section-2.md", "public"),
    ("docs/section 2 notes.md", "public"),
    # TP-174b R18 — a bare " <N>.ext" is NOT a dupe shape (it false-flagged
    # legitimate adopter docs); only " (N)" and " copy[ N]" classify transient.
    ("docs/Chapter 7.md", "public"),
    ("Python 3.md", "public"),
    ("Catch 22.md", "public"),
    ("notes copy.md", "transient"),
    ("notes copy 2.txt", "transient"),
    # TP-RELEASE-11 — Claude Code session lock
    (".claude/scheduled_tasks.lock", "local_only"),
])
def test_classify_release_path(path, expected_bucket):
    assert surface_contract.classify_release_path(path) == expected_bucket


def test_is_public_release_allowed_agrees_with_classifier():
    """``is_public_release_allowed`` must return True iff bucket == public."""
    sample_paths = [
        "README.md", "espalier/cli.py", "cc/COMMANDS.md",
        "reports/x.json", "TP-FOO.md",
        ".DS_Store", "__pycache__/x.pyc",
    ]
    for path in sample_paths:
        bucket = surface_contract.classify_release_path(path)
        is_public = surface_contract.is_public_release_allowed(path)
        assert (bucket == "public") == is_public, (
            f"{path}: classifier={bucket}, is_public_release_allowed={is_public}"
        )


def test_release_predicate_wrappers_match_classifier():
    """``is_release_included`` / ``is_release_excluded`` must agree with
    :func:`classify_release_path` and be exact negations of each other.

    The predicates are TP-07 §1 wrappers — adding them late in TP-SYN-11
    closed the only spec gap from the audit pass. Their contract is
    purely thin: included iff bucket=='public'; excluded iff not.
    """
    sample_paths = [
        "README.md", "espalier/cli.py", "cc/COMMANDS.md",
        "reports/x.json", "TP-FOO.md",
        ".DS_Store", "__pycache__/x.pyc", ".github/workflows/test.yml",
        "tools/cc/hooks/write_guard.py",
        # Leading "./" from Path.relative_to / os.path.relpath outputs —
        # _normalize must strip these before prefix matching, otherwise
        # is_local_only/is_internal_release_leak silently return False.
        "./reports/x.json",
        "./cc/blueprints/session.json",
        # Windows backslash form — same path, different OS.
        "cc\\blueprints\\session.json",
    ]
    for path in sample_paths:
        bucket = surface_contract.classify_release_path(path)
        included = surface_contract.is_release_included(path)
        excluded = surface_contract.is_release_excluded(path)
        assert included == (bucket == "public"), (
            f"{path}: classifier={bucket}, is_release_included={included}"
        )
        assert excluded == (not included), (
            f"{path}: included={included}, excluded={excluded} — "
            "wrappers must be exact negations"
        )
    # Pin the specific bug the issue caught: ./-prefixed local paths
    # must classify as local_only, not public.
    assert surface_contract.classify_release_path("./reports/x.json") == "local_only"
    assert surface_contract.classify_release_path("./cc/blueprints/s.json") == "local_only"
    assert surface_contract.classify_release_path("cc\\blueprints\\s.json") == "local_only"


# ---------------------------------------------------------------------------
# get_release_excluded_prefixes — useful for build-time directory pruning
# ---------------------------------------------------------------------------


class TestExcludedPrefixesAccessor:
    def test_includes_known_local_only_prefixes(self):
        prefixes = surface_contract.get_release_excluded_prefixes()
        for required in (
            "cc/blueprints/", "reports/",
            "bench/results/", "zDone/",
        ):
            assert required in prefixes, (
                f"{required} missing from get_release_excluded_prefixes"
            )

    def test_includes_transient_directory_patterns(self):
        prefixes = surface_contract.get_release_excluded_prefixes()
        for required in (".pytest_cache/", "__pycache__/", "dist/"):
            assert required in prefixes


# ---------------------------------------------------------------------------
# Build vs scan parity — both consume surface_contract.classify_release_path
# ---------------------------------------------------------------------------


def _load_build_script():
    """Load scripts/build_release_archive.py by file path."""
    candidate = REPO_ROOT / "scripts" / "build_release_archive.py"
    spec = importlib.util.spec_from_file_location("_build_release_archive", candidate)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_release_check_script():
    """Load scripts/release_check.py by file path."""
    candidate = REPO_ROOT / "scripts" / "release_check.py"
    spec = importlib.util.spec_from_file_location("_release_check", candidate)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(candidate)
    module = importlib.util.module_from_spec(spec)
    # release_check defines @dataclass — dataclasses needs the module
    # registered in sys.modules during class construction.
    sys.modules["_release_check"] = module
    spec.loader.exec_module(module)
    return module


class TestBuildAndScanParity:
    """Build script's _classify and release_check's bucket scan must agree."""

    @pytest.mark.parametrize("path", [
        "README.md", "espalier/cli.py",
        "reports/foo.json", "TP-FOO.md", ".DS_Store",
        "__pycache__/x.pyc", "cc/blueprints/y.json",
    ])
    def test_build_script_classify_matches_surface_contract(self, path):
        build = _load_build_script()
        bucket = surface_contract.classify_release_path(path)
        result = build._classify(path)
        if bucket == "public":
            assert result is None, (
                f"{path}: surface_contract says public, build script excludes ({result})"
            )
        else:
            assert result == bucket, (
                f"{path}: surface_contract={bucket!r} but build script={result!r}"
            )

    def test_release_check_archive_member_strip(self):
        rc = _load_release_check_script()
        # Build wraps members under espalier-harness-<version>/
        assert rc._archive_member_to_rel("espalier-harness-0.5.0/README.md") == "README.md"
        assert rc._archive_member_to_rel("espalier-harness-0.5.0/cc/COMMANDS.md") == "cc/COMMANDS.md"
        # No prefix → returned unchanged
        assert rc._archive_member_to_rel("README.md") == "README.md"


# ---------------------------------------------------------------------------
# End-to-end: built archive contents match classifier judgments
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestBuiltArchiveContents:
    """Build the actual release zip; verify every member is classified public.

    Slow because it builds a real zip. Skipped if the build script is
    not importable.
    """

    def test_built_archive_contains_only_public_paths(self, tmp_path):
        try:
            build = _load_build_script()
        except FileNotFoundError:
            pytest.skip("scripts/build_release_archive.py not present")
        try:
            archive = build.build_release_archive(REPO_ROOT, output_dir=tmp_path)
        except SystemExit as exc:
            pytest.fail(f"build_release_archive failed: rc={exc.code}")
        offenders = []
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                # Strip the espalier-harness-<version>/ prefix
                parts = name.split("/", 1)
                rel = parts[1] if len(parts) == 2 else name
                bucket = surface_contract.classify_release_path(rel)
                if bucket != "public":
                    offenders.append((name, bucket))
        assert not offenders, (
            f"built archive contains non-public members: {offenders[:5]}"
        )

    def test_built_archive_includes_required_public_assets(self, tmp_path):
        try:
            build = _load_build_script()
        except FileNotFoundError:
            pytest.skip("scripts/build_release_archive.py not present")
        archive = build.build_release_archive(REPO_ROOT, output_dir=tmp_path)
        with zipfile.ZipFile(archive) as zf:
            members = zf.namelist()
        # Strip the leading espalier-harness-<version>/
        rels = {m.split("/", 1)[1] for m in members if "/" in m}
        for required in (
            "README.md", "LICENSE", "CHANGELOG.md", "pyproject.toml",
            "espalier/cli.py", "espalier/surface_contract.py",
            "tools/cc/ci_guard.py", ".github/workflows/release.yml",
        ):
            assert required in rels, (
                f"built archive missing required public asset: {required}"
            )

    def test_built_archive_excludes_known_risky_paths(self, tmp_path):
        try:
            build = _load_build_script()
        except FileNotFoundError:
            pytest.skip("scripts/build_release_archive.py not present")
        archive = build.build_release_archive(REPO_ROOT, output_dir=tmp_path)
        with zipfile.ZipFile(archive) as zf:
            members = zf.namelist()
        rels = {m.split("/", 1)[1] for m in members if "/" in m}
        for forbidden in (
            ".claude/settings.local.json",
            "cc/SURFACE_HANDOFF.md",
        ):
            assert forbidden not in rels, (
                f"built archive includes excluded path: {forbidden}"
            )
        # No path-prefix leak either
        assert not any(r.startswith("reports/") for r in rels), (
            "built archive contains reports/ entries"
        )
        assert not any(r.startswith("cc/blueprints/") for r in rels), (
            "built archive contains cc/blueprints/ entries"
        )


# ---------------------------------------------------------------------------
# TP-RELEASE-12 — Independent denylist scan over built archive contents.
#
# This class is the SoT-divorced complement to TestBuiltArchiveContents.
# The regexes below are forbidden shapes by inspection (IDE droppings,
# OS metadata, download dupes, copy artifacts, runtime locks). They are
# intentionally *not* derived from espalier.surface_contract so a
# classifier blind spot cannot silence this test.
#
# Original failure mode the pack guards against: 0.5.0 release archive
# shipped *.code-workspace files and .claude/scheduled_tasks.lock because
# the classifier blessed them as public, and the cleanliness test
# validated archive members by calling that same classifier.
# ---------------------------------------------------------------------------


# (pattern, label) pairs. Each pattern matches "junk by inspection."
# If a future contributor adds a new IDE/OS artifact class that the
# classifier misses, add the regex here AND fix the classifier — both
# must agree on the new rejection.
#
# Lifted from inside TestArchiveJunkShapes to module-level so external
# consumers (scripts/final_release_matrix.py stage 5) import a public
# module-level constant rather than reaching into a test class via
# `sys.path` manipulation. Architecture-analyst flagged the prior shape
# as "test class accidentally became public API."
FORBIDDEN_SHAPES: tuple[tuple[str, str], ...] = (
    # IDE/editor workspace files
    (r"\.code-workspace$", "VS Code workspace file"),
    (r"\.iml$", "IntelliJ module file"),
    (r"\.sublime-(?:project|workspace)$", "Sublime Text workspace"),
    # Browser-download dupes
    (r" \(\d+\)\.[A-Za-z0-9]+$", "browser re-download duplicate (foo (1).ext)"),
    # macOS/Finder copy dupes. TP-174b R18: matches the explicit " copy"
    # shape ("notes copy.txt" / "notes copy 2.txt"), not a bare trailing
    # " <N>.ext" — the bare-number shape is textually indistinguishable from
    # legitimate names ("Catch 22.md", "Python 3.md") and false-flagged them
    # as forbidden. Mirrors surface_contract._DOWNLOAD_DUPE_RE (independent
    # canon, kept in lockstep by intent — both tightened together).
    (r" copy(?: \d+)?\.[A-Za-z0-9]+$", "macOS Finder copy duplicate (foo copy.ext)"),
    # OS metadata
    (r"(?:^|/)\.DS_Store$", "macOS Finder metadata"),
    (r"(?:^|/)Thumbs\.db$", "Windows Explorer metadata"),
    (r"(?:^|/)desktop\.ini$", "Windows folder metadata"),
    # Editor swap/backup files
    (r"\.(?:swp|swo)$", "vim swap file"),
    (r"~$", "editor backup file"),
    # Claude Code session locks
    (r"\.claude/scheduled_tasks\.lock$", "Claude Code session lock"),
    # Python bytecode (defense-in-depth — classifier already covers __pycache__/)
    (r"\.py[co]$", "Python bytecode"),
)


@pytest.mark.slow
class TestArchiveJunkShapes:
    """Independent denylist scan over built archive contents."""

    # Backwards-compat alias — existing tests still reference
    # TestArchiveJunkShapes.FORBIDDEN_SHAPES via class attribute access.
    FORBIDDEN_SHAPES = FORBIDDEN_SHAPES

    def test_built_archive_has_no_forbidden_shapes(self, tmp_path):
        """Scan the built archive against an independent denylist.

        This test does NOT consult espalier.surface_contract. The
        denylist is a parallel statement of "what is junk." When the
        classifier and the denylist agree, this test passes. When
        they disagree (classifier blesses what the denylist rejects),
        this test fails with a specific offender list.
        """
        import re as _re

        try:
            build = _load_build_script()
        except FileNotFoundError:
            pytest.skip("scripts/build_release_archive.py not present")

        archive = build.build_release_archive(REPO_ROOT, output_dir=tmp_path)
        with zipfile.ZipFile(archive) as zf:
            members = zf.namelist()

        offenders: list[tuple[str, str]] = []
        for name in members:
            # Strip the espalier-harness-<version>/ prefix for matching.
            rel = name.split("/", 1)[1] if "/" in name else name
            for pattern, label in self.FORBIDDEN_SHAPES:
                if _re.search(pattern, rel):
                    offenders.append((name, label))
                    break  # one offence per member is enough

        assert not offenders, (
            f"Archive contains {len(offenders)} member(s) matching forbidden "
            f"shapes (verified independently of classify_release_path):\n"
            + "\n".join(f"  - {n}  ({label})" for n, label in offenders[:10])
            + ("\n  ... (truncated to first 10)" if len(offenders) > 10 else "")
            + "\n\nIf the classifier blessed these as public, the classifier "
            "is wrong — fix espalier/surface_contract.py:RELEASE_NOISE_PATTERNS, "
            "_LOCAL_ONLY_PATHS, or _is_download_dupe. Do not relax this "
            "denylist to silence the failure."
        )

class TestDenylistIsIndependentCanon:
    """The independent denylist must remain an independent SoT.

    Pins two properties of FORBIDDEN_SHAPES:

    1. It does not import or symbolically reference surface_contract
       (so a classifier blind spot cannot silence the canon).
    2. It still catches every original 0.5.0 leak shape (so a future
       weakening of any single regex surfaces immediately).

    These tests are fast (pure regex / AST inspection — no archive
    build) and live outside ``TestArchiveJunkShapes`` so they run in
    the default ``-m "not slow"`` slice. The slow archive build sits
    in ``TestArchiveJunkShapes``; the fast canon-integrity pins sit
    here.
    """

    def test_denylist_catches_known_0_5_0_leaks(self):
        """Unit test the denylist against the four 0.5.0 leak classes.

        This test does not build an archive; it asserts the denylist
        regexes match the original 0.5.0 leak filenames. If any of
        these regexes is later weakened, this test fails — preventing
        a silent regression. Lives in this class (rather than
        ``TestArchiveJunkShapes``) so it runs in the default
        non-slow loop.
        """
        import re as _re

        # The four 0.5.0 leak filenames, each must match at least one rule
        zero_five_leaks = [
            "MyProject 3.code-workspace1.code-workspace",
            "utws 2.code-workspace",
            ".claude/scheduled_tasks.lock",
            "docs/docs-README (1).md",
        ]
        for path in zero_five_leaks:
            matched = False
            for pattern, label in TestArchiveJunkShapes.FORBIDDEN_SHAPES:
                if _re.search(pattern, path):
                    matched = True
                    break
            assert matched, (
                f"Denylist no longer catches 0.5.0 leak {path!r}. "
                f"A regex was likely weakened. Restore the rule that catches "
                f"this shape, do not silence the test."
            )

    def test_denylist_does_not_import_surface_contract(self):
        """TestArchiveJunkShapes must not import or symbolically reference surface_contract.

        Naming the classifier in a docstring or error-message string is
        not coupling — the class can point readers at the classifier
        without depending on it. Real coupling shows up in the AST as
        an ``Import`` / ``ImportFrom`` node or a ``Name`` reference
        bound to ``surface_contract``. This AST check catches the
        latter while permitting the former.
        """
        import ast
        import inspect

        src = inspect.getsource(TestArchiveJunkShapes)
        tree = ast.parse(src)

        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "surface_contract" in alias.name:
                        offenders.append(f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if "surface_contract" in mod:
                    offenders.append(f"from {mod} import ...")
                for alias in node.names:
                    if alias.name == "surface_contract":
                        offenders.append(f"from {mod} import surface_contract")
            elif isinstance(node, ast.Name) and node.id == "surface_contract":
                offenders.append("Name reference to surface_contract")

        assert not offenders, (
            f"TestArchiveJunkShapes is coupled to surface_contract: {offenders}. "
            "The denylist must remain independent of the classifier — that "
            "independence is what makes it a glass-castle check."
        )

    def test_denylist_rejects_at_least_one_shape_classifier_would_need_rules_for(self):
        """A future shape (e.g., .iml IntelliJ files) is caught by the
        denylist even if the classifier hasn't added a rule for it.

        If TP-RELEASE-11's classifier rules were reverted, this test
        would still flag .iml files in an archive. That's the value:
        defense in depth across two independent SoTs.
        """
        import re as _re
        # A path the classifier currently classifies "public" (no .iml rule)
        # but the denylist rejects.
        synthetic_path = "espalier/foo.iml"

        classifier_says = surface_contract.classify_release_path(synthetic_path)

        denylist_rejects = any(
            _re.search(pat, synthetic_path)
            for pat, _ in TestArchiveJunkShapes.FORBIDDEN_SHAPES
        )

        # Document the asymmetry. If both agreed on every shape, the
        # denylist would be redundant; the value is in the disagreement
        # surfacing.
        assert denylist_rejects, (
            "Denylist must reject .iml at least; if it doesn't, the "
            "denylist has been weakened."
        )
        # Note: classifier_says == 'public' is the CURRENT state and is
        # NOT a bug — .iml is rare enough that the classifier doesn't
        # need an explicit rule yet. The denylist catches it as
        # defense-in-depth. If a future classifier change adds .iml to
        # RELEASE_NOISE_PATTERNS, this test still passes.
        _ = classifier_says  # use the variable so static analyzers don't complain


# ---------------------------------------------------------------------------
# TP-151 151-A: release-cleanliness BLOCK closures
# (symlink filter W1; build* family-glob; wheel shape-aware strip W7)
# ---------------------------------------------------------------------------


class TestSymlinkFiltering:
    """A-1 (W1): in-tree symlinks must not be walked into the release archive.

    ``is_file()`` is True for a symlink to a regular file, so without the guard
    an in-tree symlink pointing OUTSIDE the repo embeds the target's bytes into
    the public zip. Mirrors the ``espalier/release_pack.py`` symlink guard.
    """

    @requires_symlink
    def test_walk_repo_skips_in_tree_symlink_to_outside_file(self, tmp_path):
        import os
        build = _load_build_script()
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "real.py").write_text("# real\n", encoding="utf-8")
        outside = tmp_path / "secret.txt"
        outside.write_text("S3CRET-A1-MARKER\n", encoding="utf-8")
        os.symlink(outside, repo / "leaked.py")
        walked = {p.relative_to(repo).as_posix() for p in build._walk_repo(repo)}
        assert "leaked.py" not in walked  # FAILS pre-fix: symlink-to-file walked
        assert "real.py" in walked

    @requires_symlink
    def test_walk_repo_skips_in_tree_symlink_to_outside_dir(self, tmp_path):
        import os
        build = _load_build_script()
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "real.py").write_text("# real\n", encoding="utf-8")
        outdir = tmp_path / "outdir"
        outdir.mkdir()
        (outdir / "x.py").write_text("# x\n", encoding="utf-8")
        os.symlink(outdir, repo / "linkdir")
        walked = {p.relative_to(repo).as_posix() for p in build._walk_repo(repo)}
        assert not any(w.startswith("linkdir/") for w in walked)  # FAILS pre-fix

    @requires_symlink
    def test_release_zip_excludes_symlink_target_bytes(self, tmp_path):
        import os
        build = _load_build_script()
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.0.0"\n', encoding="utf-8")
        (repo / "espalier").mkdir()
        (repo / "espalier" / "__init__.py").write_text("", encoding="utf-8")
        marker = b"S3CRET-A1-E2E-MARKER"
        (tmp_path / "secret.txt").write_bytes(marker)
        # espalier/*.py classifies public, so pre-fix this symlink WOULD ship.
        os.symlink(tmp_path / "secret.txt", repo / "espalier" / "leaked.py")
        try:
            archive = build.build_release_archive(repo, output_dir=tmp_path / "out")
        except SystemExit as exc:  # pragma: no cover - defensive
            pytest.fail(f"build_release_archive failed: {exc}")
        data = archive.read_bytes()
        assert marker not in data  # FAILS pre-fix: target bytes embedded
        with zipfile.ZipFile(archive) as zf:
            assert not any(n.endswith("leaked.py") for n in zf.namelist())

    def test_build_archive_excludes_export_ignored_memory_md(self, tmp_path):
        """TP-174b T10: build_release_archive must honor .gitattributes
        export-ignore. ESPALIER_MEMORY.md classifies `public`, so without the skip this
        walker (which bypasses git archive) would ship it — the leak the scout
        observed ('espalier-harness-X/ESPALIER_MEMORY.md' in a live build)."""
        build = _load_build_script()
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.0.0"\n', encoding="utf-8")
        (repo / "espalier").mkdir()
        (repo / "espalier" / "__init__.py").write_text("", encoding="utf-8")
        (repo / "ESPALIER_MEMORY.md").write_text("internal session log\n", encoding="utf-8")
        (repo / ".gitattributes").write_text("ESPALIER_MEMORY.md export-ignore\n", encoding="utf-8")
        archive = build.build_release_archive(repo, output_dir=tmp_path / "out")
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
        assert not any(Path(n).name == "ESPALIER_MEMORY.md" for n in names), names


@pytest.mark.parametrize("path", [
    "build2/x.py", "build_orig_stale/y.py", "build-backup/z.py",
])
def test_build_glob_nonbare_dirs_classify_transient(path):
    """A-2 (NEW BLOCK): ``build*`` family dirs classify transient, not public.

    Pre-fix the classifier SoT carried bare ``build/`` so ``build2/`` etc.
    classified ``public`` and shipped. FAILS pre-fix.
    """
    assert surface_contract.classify_release_path(path) == "transient"


@pytest.mark.parametrize("path", ["build/lib/foo.py", "dist/x.whl"])
def test_build_glob_regression_controls(path):
    """A-2 controls: bare ``build/`` and ``dist/`` were transient pre-fix too."""
    assert surface_contract.classify_release_path(path) == "transient"


class TestWheelShapeAwareStrip:
    """A-3 (W7): artifact-cleanliness must match forbidden shapes against the FULL
    member path for wheels (no shared top dir), stripping a ``name-version/``
    prefix only when ALL members share one (sdist / source archives).
    """

    @staticmethod
    def _load_frm():
        spec = importlib.util.spec_from_file_location(
            "_final_release_matrix", REPO_ROOT / "scripts" / "final_release_matrix.py"
        )
        mod = importlib.util.module_from_spec(spec)
        # Register before exec: final_release_matrix defines a @dataclass and
        # Python 3.14's dataclasses resolves annotations via
        # sys.modules.get(cls.__module__).__dict__ — unregistered -> AttributeError.
        sys.modules[spec.name] = mod
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.path.pop(0)
        return mod

    _LOCK = ((r"(?:^|/)\.claude/scheduled_tasks\.lock$", "scheduled_tasks.lock"),)

    def test_wheel_top_level_lock_is_flagged(self):
        frm = self._load_frm()
        wheel = ["espalier/cli.py", "x-0.8.dist-info/RECORD", ".claude/scheduled_tasks.lock"]
        flagged = frm._flag_forbidden_members("x.whl", wheel, self._LOCK)
        # FAILS pre-fix: the lone first segment was stripped, so the anchored
        # `\.claude/...lock$` shape never matched the wheel's top-level lock.
        assert any(lbl == "scheduled_tasks.lock" for _, _, lbl in flagged)

    def test_sdist_shared_prefix_still_stripped_and_flagged(self):
        frm = self._load_frm()
        sdist = ["pkg-0.8.0/espalier/cli.py", "pkg-0.8.0/.claude/scheduled_tasks.lock"]
        flagged = frm._flag_forbidden_members("pkg.tar.gz", sdist, self._LOCK)
        assert any(lbl == "scheduled_tasks.lock" for _, _, lbl in flagged)


# ---------------------------------------------------------------------------
# TP-151 151-B: .espalier/ runtime-dir classification (W2/W20/W21/W22)
# ---------------------------------------------------------------------------

from espalier import release_denylist  # noqa: E402


class TestEspalierRuntimeClassification:
    """The gitignored .espalier/ runtime files must classify local_only AND be
    denied by the second (denylist) witness — while the COMMITTED
    ``.espalier/freshness.json`` (BC-039 / TP-56-A) stays public and shipping.
    """

    GITIGNORED = [
        ".espalier/.freshness.write.lock",
        ".espalier/.freshness_state_cache.json",
        ".espalier/reasoning_review_log.jsonl",
        ".espalier/.manifest.write.lock",
        ".espalier/integrity.json",
        ".espalier/memory_candidate_log.jsonl",
    ]

    @pytest.mark.parametrize("path", GITIGNORED)
    def test_gitignored_runtime_files_are_local_only(self, path):
        # FAILS pre-fix for .freshness.write.lock / reasoning_review_log.jsonl
        assert surface_contract.is_local_only(path) is True
        assert surface_contract.classify_release_path(path) == "local_only"

    @pytest.mark.parametrize("path", GITIGNORED)
    def test_gitignored_runtime_files_are_denied(self, path):
        assert release_denylist.find_denied_members([path])  # non-empty

    def test_freshness_json_stays_public_bc039(self):
        """BC-039 / TP-56-A positive control: the committed manifest must NOT be
        swept by the broad-prefix mistake this pack explicitly avoided."""
        assert surface_contract.classify_release_path(".espalier/freshness.json") == "public"
        assert surface_contract.is_local_only(".espalier/freshness.json") is False
        assert not release_denylist.find_denied_members([".espalier/freshness.json"])

    @pytest.mark.slow
    def test_built_archive_excludes_gitignored_espalier_keeps_freshness(self, tmp_path):
        """End-to-end: no gitignored .espalier/ member ships, but
        .espalier/freshness.json IS present in the real archive."""
        build = _load_build_script()
        try:
            archive = build.build_release_archive(REPO_ROOT, output_dir=tmp_path)
        except SystemExit as exc:
            pytest.fail(f"build_release_archive failed: rc={exc.code}")
        with zipfile.ZipFile(archive) as zf:
            rels = {m.split("/", 1)[1] if "/" in m else m for m in zf.namelist()}
        leaked = sorted(
            r for r in rels
            if r.startswith(".espalier/") and r != ".espalier/freshness.json"
        )
        assert not leaked, f"gitignored .espalier/ members shipped: {leaked}"
        assert ".espalier/freshness.json" in rels, (
            "BC-039: committed freshness.json must ship in the public archive"
        )
