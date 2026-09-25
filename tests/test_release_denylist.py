"""TP-37: independent denylist scanner for release-archive members.

Pins the SECOND witness on what should never appear in a release
archive. The classifier (``espalier.surface_contract``) is the
FIRST. Two witnesses, no shared code — defense in depth against
the closed-loop trap that shipped v0.6.0's ``project.zip``.
Without this second-witness contract, a classifier bug would
silently mis-include junk in the archive AND mis-pass the
"is this clean?" check that uses the same classifier (the
closed-loop trap by definition), shipping the regression without
any test catching it. The denylist is hand-curated regex with no
imports from the classifier.
"""
from __future__ import annotations

import ast
import zipfile
from pathlib import Path

import pytest

from espalier import release_denylist

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestNoSharedImports:
    """The denylist's value is being a SECOND witness with no shared code.

    If a future refactor adds an import of ``release_noise`` or
    ``surface_contract``, the modules collapse into one witness with two
    names and the v0.6.0 closed-loop trap is back.

    Round-6 hardening: AST-only checks miss evasion via
    ``importlib.import_module("espalier.release_noise")`` or
    ``__import__("espalier.surface_contract")`` — string-form imports
    that don't appear in the AST as `Import`/`ImportFrom` nodes pointing
    at the banned module. The substring check at the bottom of this
    class scans the source text for any literal mention of the banned
    module names — catches both AST imports and string-form evasions.
    """

    BANNED_MODULES = ("release_noise", "surface_contract")

    def test_denylist_does_not_import_release_noise(self):
        text = (REPO_ROOT / "espalier" / "release_denylist.py").read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "release_noise" not in (node.module or ""), (
                    "release_denylist must not import release_noise — that "
                    "collapses the dual-witness pattern into one witness"
                )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "release_noise" not in alias.name, (
                        "release_denylist must not import release_noise"
                    )

    def test_denylist_does_not_import_surface_contract(self):
        text = (REPO_ROOT / "espalier" / "release_denylist.py").read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "surface_contract" not in (node.module or ""), (
                    "release_denylist must not import surface_contract — that "
                    "collapses the dual-witness pattern"
                )

    def test_no_string_form_evasion(self):
        """Catch ``importlib.import_module('espalier.release_noise')`` and
        ``__import__('espalier.surface_contract')`` — both evade AST
        Import/ImportFrom node detection by hiding the banned module
        name in a string literal. A literal substring scan catches the
        evasion shape without false-positiving on the *banned* module
        name appearing in a docstring (the docstring DOES mention both
        modules by design; the scan filters comments and docstrings
        before checking)."""
        import io
        import tokenize

        path = REPO_ROOT / "espalier" / "release_denylist.py"
        text = path.read_text(encoding="utf-8")
        # Strip comments and docstrings via tokenize so the legitimate
        # docstring mentions of the banned names don't trip the test.
        code_only_chunks: list[str] = []
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        except tokenize.TokenizeError:
            tokens = []
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING and tok.string.startswith(('"""', "'''")):
                continue  # likely a docstring
            code_only_chunks.append(tok.string)
        code_only = " ".join(code_only_chunks)
        for banned in self.BANNED_MODULES:
            assert banned not in code_only, (
                f"release_denylist code-only text contains {banned!r} — "
                f"likely a string-form import evasion (importlib / __import__) "
                f"that AST checks would miss. The dual-witness invariant "
                f"requires zero shared code paths, including indirect ones."
            )


class TestEngineConsumerAllowlist:
    """TP-40: ``release_denylist`` is intentionally a SECOND witness on
    archive cleanliness, kept independent of ``release_noise.py`` /
    ``surface_contract.py``. Today the only consumer is
    ``scripts/release_check.py`` (the gate). If a future engine module
    starts importing it, the dual-witness invariant changes and the new
    consumer should be reviewed for code-sharing risk with the FIRST
    witness. This test fails the moment a non-allowlisted import lands.
    """

    ALLOWED_CONSUMERS = {
        "scripts/release_check.py",
        # Tests legitimately import directly:
        "tests/test_release_denylist.py",
        "tests/test_benchmark_release_hygiene.py",
        # Reads len(DENIED_PATTERNS) as the derived value of the "release
        # denylist pattern count" registry row (2026-09-10); it shares no code
        # with the first witness, so the dual-witness invariant is untouched.
        "tests/test_documented_claims.py",
    }

    def test_only_documented_consumers_import_release_denylist(self):
        roots = ["espalier", "tools", "scripts", "tests"]
        offenders: list[str] = []
        for root_name in roots:
            root = REPO_ROOT / root_name
            if not root.exists():
                continue
            for py in root.rglob("*.py"):
                rel = py.relative_to(REPO_ROOT).as_posix()
                if rel in self.ALLOWED_CONSUMERS:
                    continue
                try:
                    tree = ast.parse(py.read_text(encoding="utf-8"))
                except (SyntaxError, UnicodeDecodeError):
                    continue
                for node in ast.walk(tree):
                    target = ""
                    if isinstance(node, ast.ImportFrom):
                        target = node.module or ""
                    elif isinstance(node, ast.Import):
                        target = ",".join(a.name for a in node.names)
                    if "release_denylist" in target:
                        offenders.append(rel)
                        break
        assert not offenders, (
            "Undocumented consumers of espalier.release_denylist found:\n"
            + "\n".join(f"  - {o}" for o in offenders)
            + "\n\nIf the new consumer is legitimate, add it to "
            "ALLOWED_CONSUMERS here and review whether the dual-witness "
            "invariant (denylist independence from release_noise / "
            "surface_contract) still holds."
        )


class TestDeniedPatternCount:
    """TP-39: pin the live ``DENIED_PATTERNS`` count to the value claimed
    in ``docs/SHARP_EDGES.md`` ("55 patterns, no shared symbols"). The
    NumericContract for ``release denylist pattern count`` binds the
    SHARP_EDGES, FAILURE_MODES, and REDEFINED prose to the same int (TP-170
    widened it from the single SHARP_EDGES surface); this pin binds the
    source-of-truth code to the int. Together they break the closed-loop trap.
    """

    def test_denied_patterns_count_matches_sharp_edges_claim(self):
        # If you intentionally change the count, update both this assertion
        # AND the SHARP_EDGES.md receipt line ("(N patterns, no shared symbols)")
        # AND the NumericContract.expected_value in tests/test_documented_claims.py.
        assert len(release_denylist.DENIED_PATTERNS) == 56


class TestPrivateKeyFamilyOnBothWitnesses:
    """The private-cert/keystore family, on BOTH release witnesses.

    The builders enumerate the git index, so the shapes that reach an archive
    are a TRACKED key (committed or force-added by mistake) and the no-index
    fallback walk. Before this, the dual witness was ZERO-of-two: the denylist had no cert family and
    ``is_public_release_allowed`` returned True for every one of them — so a
    denylist-only fix would still leave one witness blind, and
    ``release_pack.create_release_zip``'s "included iff allowed" contract would
    happily include the key.

    FP calibration against the live population: ``git ls-files | grep -icE
    '\\.(pem|key|p12|pfx)$'`` is 0, so this costs nothing today.
    """

    @pytest.mark.parametrize("member", [
        "certs/server.pem",
        "certs/server.key",
        "certs/bundle.p12",
        "certs/bundle.pfx",
        # Uppercase spellings. A Windows PFX export is commonly `.PFX`, and the
        # allowlist witness was already case-insensitive — so a lowercase-only
        # denylist made the two "independent" witnesses disagree on a realistic
        # shape while both tests looked green.
        "certs/server.PEM",
        "certs/bundle.PFX",
        "MyCert.Key",
    ])
    def test_private_key_family_denied_by_both_witnesses(self, member):
        from espalier import surface_contract

        hits = release_denylist.find_denied_members([member])
        assert hits, f"denylist witness missed {member}"
        # The assertion that reds when ONLY the denylist half is fixed.
        assert surface_contract.is_public_release_allowed(member) is False, (
            f"allowlist witness still admits {member} — dual witness is "
            "one-of-two, and release_pack ships 'included iff allowed'"
        )

    def test_classifier_agrees_with_the_boolean(self):
        """The exact-negation contract must survive the widening."""
        from espalier import surface_contract

        for member in ("certs/server.pem", "README.md"):
            bucket = surface_contract.classify_release_path(member)
            assert (bucket == "public") is surface_contract.is_public_release_allowed(member)


class TestDeniedShapes:
    """Each shape the denylist is supposed to catch."""

    @pytest.mark.parametrize("member,reason_substr", [
        ("project.zip", "nested archive"),
        ("dist/release-0.6.4.tar.gz", "tarball"),
        ("dist/release.tar", "tar"),
        ("dist/release.tgz", "tarball"),
        ("dist/release.tar.bz2", "tarball"),
        ("dist/release.7z", "7-zip"),
        ("dist/espalier_harness-0.6.4-py3-none-any.whl", "wheel"),
        ("foo.egg", "egg"),
        ("foo.egg-info/PKG-INFO", "egg-info"),
        (".vscode/settings.json", "VS Code"),
        (".idea/workspace.xml", "JetBrains"),
        (".pytest_cache/v/cache/nodeids", "pytest cache"),
        ("tools/cc/__pycache__/x.pyc", "bytecode cache"),
        (".mypy_cache/3.12/foo", "mypy cache"),
        (".ruff_cache/0.1/foo", "ruff cache"),
        # §C13 (DEF-417f): the repo's own admin dir, and the bare gitlink FILE a
        # `git worktree` / submodule checkout leaves at its root.
        (".git/HEAD", "git admin"),
        (".git", "gitlink"),
        ("wt/.git", "gitlink"),
        (".coverage", "coverage data"),
        ("htmlcov/index.html", "coverage HTML"),
        (".DS_Store", "macOS finder"),
        ("subdir/.DS_Store", "macOS finder"),
        ("Thumbs.db", "Windows thumbnail"),
        ("__MACOSX/foo", "macOS resource"),
        (".espalier-state/seed", "session state"),
        (".espalier/integrity.json", "integrity manifest"),
        (".claude/settings.json", "per-install"),
        (".claude/settings.local.json", "per-machine"),
        ("reports/x.json", "per-run generated"),
        ("cc/blueprints/2026.json", "blueprint state"),
        ("bench/results/2026.json", "benchmark output"),
        ("build/lib/x.py", "build"),
        # TP-149 (F-2 / §10.8 renamed-sibling regression): the family-glob
        # must catch build-prefixed siblings, not just the literal `build/`.
        # `build_orig_stale/` is the exact dir that leaked 96 stale .py files.
        ("build_orig_stale/x.py", "build* directory family"),
        ("build2/y.py", "build* directory family"),
        ("dist/x.whl", "wheel"),  # also matches dist/ prefix; first match wins
        ("receiver-test/x.py", "receiver test"),
        ("TP-37-foo.md", "task pack working note"),
        ("docs/TP-37-foo.md", "task pack working note"),
        # A pack outside its two shipped locations (2026-09-21): the landed /
        # merged / scrapped subtrees, a nested folder, an adopter's vendored
        # copy -- at the archive root or under the release zip's version dir.
        ("task-packs/Done/TP-37-foo.md", "task pack working note"),
        ("task-packs/Merged/TP-37-foo.md", "task pack working note"),
        ("task-packs/Scrapped/TP-37-foo.md", "task pack working note"),
        ("task-packs/Deferred/old/TP-37-foo.md", "task pack working note"),
        ("src/vendor/task-packs/TP-37-foo.md", "task pack working note"),
        ("vendor/task-packs/TP-37-foo.md", "task pack working note"),
        ("espalier-harness-0.8.0/task-packs/Done/TP-37-foo.md", "task pack working note"),
        # The same `TP-<anything>.md` spelling the two noise twins use.
        ("TP-abc.md", "task pack working note"),
        ("foo_task_pack.md", "task pack working note"),
        # TP-247a #4 — OS/editor/tool droppings that formerly classified public
        # in BOTH witnesses (verified at HEAD da89d0a).
        ("._resourcefork", "AppleDouble"),
        ("docs/._notes.md", "AppleDouble"),
        ("main.c.swp", "vim swap"),
        (".main.py.swo", "vim swap"),
        ("cli.py.orig", "merge conflict"),
        ("patch.rej", "patch reject"),
        ("settings.bak", "backup"),
        ("README.md~", "backup"),
        (".tox/py312/bin/python", "tox"),
        (".nox/tests/foo", "nox"),
        # TP-247a #5 — secret / credential files that formerly shipped into the
        # public archive verbatim (the builders were tree walks then; today a
        # tracked one, or one walked by the no-index fallback, is the shape).
        (".env", "secret"),
        (".env.local", "secret"),
        (".env.production", "secret"),
        (".pypirc", "credential"),
        (".netrc", "credential"),
        ("id_rsa", "private key"),
        ("id_ed25519", "private key"),
        (".ssh/id_ecdsa", "private key"),
        ("credentials.json", "credential"),
        (".aws/credentials", "credential"),
    ])
    def test_denied_shape_caught(self, member, reason_substr):
        results = release_denylist.find_denied_members([member])
        assert results, f"denylist did not catch {member!r}"
        path, reason = results[0]
        assert path == member
        assert reason_substr.lower() in reason.lower(), (
            f"{member!r}: expected reason containing {reason_substr!r}, "
            f"got {reason!r}"
        )

    @pytest.mark.parametrize("member", [
        "README.md",
        "src/foo.py",
        "docs/QUICKSTART.md",
        "espalier/cli.py",
        "tests/test_foo.py",
        "tools/cc/hooks/write_guard.py",
        "pyproject.toml",
        "LICENSE",
        # TP-247a #4/#5 over-match guards: near-miss shapes must still ship.
        ".environment",              # not `.env` / `.env.*`
        "espalier/environment.py",   # basename is not `.env*`
        "credential_helper.py",      # not the bare `credentials` name
        "id_rsa.pub",                # public key is not a private key
        "docs/original.md",          # not `*.orig`
        # §C13 (DEF-417f) over-match guards: tracked names sharing the `.git`
        # prefix stay shippable.
        ".gitignore",
        ".gitattributes",
        ".gitmodules",
        ".github/workflows/ci.yml",
        # The shipped pack locations (2026-09-21), repo-relative as the release
        # check hands them over, plus the ledger and its probes file.
        "task-packs/TP-452-the-ledger-ships.md",
        "task-packs/Deferred/TP-203a-learning-loop.md",
        "task-packs/FORWARD_LEDGER.md",
        "task-packs/LEDGER_PROBES.json",
    ])
    def test_clean_path_passes(self, member):
        assert release_denylist.find_denied_members([member]) == []


class TestWindowsPathNormalization:
    """Paths with backslashes (Windows ZipFile) must normalise correctly."""

    def test_backslash_path_is_caught(self):
        results = release_denylist.find_denied_members([
            r"dist\foo.zip",
            r".vscode\settings.json",
        ])
        assert len(results) == 2


class TestAssertClean:
    def test_clean_archive_does_not_raise(self):
        release_denylist.assert_clean(["README.md", "src/foo.py"])

    def test_dirty_archive_raises(self):
        with pytest.raises(ValueError) as exc:
            release_denylist.assert_clean(["project.zip", "README.md"])
        assert "project.zip" in str(exc.value)
        assert "nested archive" in str(exc.value).lower()


class TestEmptyInput:
    def test_find_denied_members_empty_iterable(self):
        """Zero members in, zero results out — no regex compilation
        failure, no spurious return."""
        assert release_denylist.find_denied_members([]) == []

    def test_assert_clean_empty_iterable(self):
        """Zero members in, no raise."""
        release_denylist.assert_clean([])


class TestSyntheticDirtyZipCaught:
    """End-to-end: build a synthetic dirty ZIP, scan it via the denylist."""

    def test_dirty_zip_with_project_zip_inside(self, tmp_path):
        outer = tmp_path / "release.zip"
        with zipfile.ZipFile(outer, "w") as zf:
            zf.writestr("README.md", "# ok\n")
            zf.writestr("project.zip", b"fake nested archive bytes")
            zf.writestr("reports/run.json", "{}")
        with zipfile.ZipFile(outer) as zf:
            members = zf.namelist()
        denied = release_denylist.find_denied_members(members)
        names = {m for m, _ in denied}
        assert "project.zip" in names
        assert "reports/run.json" in names
        assert "README.md" not in names
