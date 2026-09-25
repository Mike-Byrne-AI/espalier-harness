"""Tests for ``espalier.scanners`` — the stdlib-only AST scanners
(``exceptions``, ``prints``, ``godfiles``, ``perf_smells``) that
``/scan`` and the harness reflect pass invoke for code-quality
findings.

Pins per-scanner detection invariants against the ``python_repo``
and ``ml_repo`` fixtures (which contain seeded violations). Without
this contract a regex/AST tweak in any scanner could silently
under-report findings — the scanner would still run, still emit a
report, but the count would drop to zero with no visible failure,
defeating the whole point of the periodic scan.
"""
from __future__ import annotations

from pathlib import Path


class TestScanners:
    def test_exception_scanner_finds_swallowed(self, python_repo):
        from espalier.scanners.exceptions import scan_repo
        report = scan_repo(str(python_repo))
        assert report["count"] >= 1
        kinds = report["by_kind"]
        assert "swallowed_silent" in kinds or "swallowed_broad_no_log" in kinds

    def test_print_scanner_finds_prints(self, python_repo):
        from espalier.scanners.prints import scan_repo
        report = scan_repo(str(python_repo))
        assert report["count"] >= 1

    def test_godfiles_outline_clusters(self, python_repo):
        from espalier.scanners.godfiles import outline_file
        outline = outline_file(str(python_repo / "src" / "utils.py"))
        assert len(outline["clusters"]) >= 1
        cache_cluster = [c for c in outline["clusters"] if c["group_key"] == "cache"]
        assert len(cache_cluster) == 1
        assert cache_cluster[0]["count"] == 4

    def test_godfiles_report(self, python_repo):
        from espalier.scanners.godfiles import scan_repo
        report = scan_repo(str(python_repo), threshold=5)
        assert report["above_threshold"] >= 1

    def test_perf_smells_ml(self, ml_repo):
        from espalier.scanners.perf_smells import scan_repo, select_patterns
        patterns = select_patterns(ml=True)
        report = scan_repo(str(ml_repo), patterns)
        assert report["files_with_hits"] >= 1

    def test_exception_scanner_handles_syntax_error(self, tmp_path):
        (tmp_path / "bad.py").write_text("def broken(\n", encoding="utf-8")
        from espalier.scanners.exceptions import scan_file
        findings = scan_file(str(tmp_path / "bad.py"))
        assert len(findings) == 1
        assert findings[0]["kind"] == "syntax_error"


class TestScannerSelfContainment:
    """Scanners are copied into target repos via inspect.getsource().
    Any import from `espalier` would silently break the generated file."""

    def test_no_scanner_imports_from_espalier(self):
        scanners_dir = Path(__file__).parent.parent / "espalier" / "scanners"
        violations = []
        for py_file in scanners_dir.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            source = py_file.read_text(encoding="utf-8")
            for i, line in enumerate(source.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "from espalier" in stripped or "import espalier" in stripped:
                    violations.append(f"{py_file.name}:{i}: {stripped}")
        assert violations == [], (
            "Scanners must be self-contained (stdlib only). "
            "Found espalier imports:\n" + "\n".join(violations)
        )


class TestScannerExemptPrefixesParity:
    """Every scanner that walks `tests/` must exempt `tests/fixtures/`.

    Sister fixtures (TP-138/139 known-positives) live under
    `tests/fixtures/` and contain intentional theater/positives. A new
    scanner that forgets the exemption false-flags every fixture on
    first run, and the operator response (add per-file EXEMPT_FILES)
    accumulates exemption debt instead of fixing the structural rule.
    This contract makes the exemption mechanical: any scanner whose
    walk reaches the tests/ tree must carry an EXEMPT_PREFIXES tuple
    that contains the fixtures path.

    Scope: every module under `espalier/scanners/` whose source
    references the string "tests" (signalling that scan_repo walks
    that tree). The check is structural — no scanner runtime needed.
    """

    def test_test_walking_scanners_exempt_fixtures(self):
        scanners_dir = Path(__file__).parent.parent / "espalier" / "scanners"
        offenders = []
        for path in scanners_dir.glob("*.py"):
            if path.name == "__init__.py":
                continue
            source = path.read_text(encoding="utf-8")
            walks_tests = '"tests"' in source or "'tests'" in source
            if not walks_tests:
                continue
            if "EXEMPT_PREFIXES" not in source:
                offenders.append(f"{path.name} — no EXEMPT_PREFIXES")
                continue
            if "tests/fixtures/" not in source:
                offenders.append(
                    f"{path.name} — EXEMPT_PREFIXES missing 'tests/fixtures/'"
                )
        assert not offenders, (
            "scanners walking tests/ must exempt tests/fixtures/:\n  "
            + "\n  ".join(offenders)
        )

    def test_exempt_prefixes_within_declared_cap(self):
        """TP-152 C-2: MAX_EXEMPT_PREFIXES was decorative — declared but
        unenforced. Every scanner that declares the cap must keep
        len(EXEMPT_PREFIXES) <= MAX_EXEMPT_PREFIXES, so growth past it is a
        deliberate decision (raise the cap) not silent exemption debt."""
        import importlib

        scanners_dir = Path(__file__).parent.parent / "espalier" / "scanners"
        checked: list[str] = []
        for path in sorted(scanners_dir.glob("*.py")):
            if path.name == "__init__.py":
                continue
            mod = importlib.import_module(f"espalier.scanners.{path.stem}")
            cap = getattr(mod, "MAX_EXEMPT_PREFIXES", None)
            prefixes = getattr(mod, "EXEMPT_PREFIXES", None)
            if cap is None or prefixes is None:
                continue
            checked.append(path.stem)
            assert len(prefixes) <= cap, (
                f"{path.stem}: {len(prefixes)} EXEMPT_PREFIXES exceeds cap "
                f"{cap} — raise MAX_EXEMPT_PREFIXES deliberately or trim"
            )
        # Guard against the contract silently checking nothing (the
        # vacuous-registry trap the catalog itself documents).
        assert {
            "subprocess_contracts", "filesystem_contracts", "magic_depth",
        } <= set(checked), (
            f"expected the cap-declaring scanners to be checked; got {checked}"
        )


class TestGodfilesThreshold:
    def test_default_threshold_is_750(self):
        from espalier.scanners.godfiles import DEFAULT_THRESHOLD
        assert DEFAULT_THRESHOLD == 750

    def test_godfiles_skips_under_750(self, python_repo):
        from espalier.scanners.godfiles import scan_repo
        report = scan_repo(str(python_repo))
        # Our small test files are well under 750
        assert report["above_threshold"] == 0

    def test_godfiles_custom_threshold(self, python_repo):
        from espalier.scanners.godfiles import scan_repo
        # With a very low threshold, files should be flagged
        report = scan_repo(str(python_repo), threshold=5)
        assert report["above_threshold"] >= 1


class TestTestLoosening:
    """Pin the test-loosening scanner's four high-confidence detection rules.

    Catches the regression where a future AST-predicate tweak silently
    under-reports findings — same shape as TestScanners above. Each rule
    has a positive test (must detect a known weak form) plus, where
    false-positives are plausible, a negative test (must NOT fire on
    valid usage). Empirical case for the scanner's existence: ImpossibleBench
    (Oct 2025) showed GPT-5 exploits test cases 76% of the time on
    impossible-SWE-bench; this scanner catches the landed artifacts.
    """

    def test_detects_assert_true(self, tmp_path):
        f = tmp_path / "test_x.py"
        f.write_text("def test_a():\n    assert True\n", encoding="utf-8")
        from espalier.scanners.test_loosening import scan_file
        report = scan_file(str(f))
        assert report["count"] == 1
        assert report["findings"][0]["rule"] == "assert_tautological"

    def test_detects_assert_one_equals_one(self, tmp_path):
        f = tmp_path / "test_x.py"
        f.write_text("def test_a():\n    assert 1 == 1\n", encoding="utf-8")
        from espalier.scanners.test_loosening import scan_file
        report = scan_file(str(f))
        rules = [r["rule"] for r in report["findings"]]
        assert "assert_tautological" in rules

    def test_does_not_fire_on_meaningful_assert(self, tmp_path):
        f = tmp_path / "test_x.py"
        f.write_text(
            "def compute():\n    return 42\n"
            "def test_a():\n    x = compute()\n    assert x == 42\n",
            encoding="utf-8",
        )
        from espalier.scanners.test_loosening import scan_file
        report = scan_file(str(f))
        rules = [r["rule"] for r in report["findings"]]
        assert "assert_tautological" not in rules

    def test_detects_bare_pytest_skip(self, tmp_path):
        f = tmp_path / "test_x.py"
        f.write_text(
            "import pytest\ndef test_a():\n    pytest.skip()\n",
            encoding="utf-8",
        )
        from espalier.scanners.test_loosening import scan_file
        report = scan_file(str(f))
        rules = [r["rule"] for r in report["findings"]]
        assert "bare_skip" in rules

    def test_does_not_fire_on_skip_with_reason(self, tmp_path):
        f = tmp_path / "test_x.py"
        f.write_text(
            "import pytest\n"
            "def test_a():\n    pytest.skip(reason='env not ready')\n",
            encoding="utf-8",
        )
        from espalier.scanners.test_loosening import scan_file
        report = scan_file(str(f))
        rules = [r["rule"] for r in report["findings"]]
        assert "bare_skip" not in rules

    def test_detects_skip_with_empty_reason_kwarg(self, tmp_path):
        """``reason=''`` is a present-but-empty reason kwarg; it
        must still flag skip_no_reason (the kwarg-presence check used to
        short-circuit to 'has reason' regardless of the value)."""
        f = tmp_path / "test_x.py"
        f.write_text(
            "import pytest\n"
            "@pytest.mark.skip(reason='')\n"
            "def test_a():\n    pass\n",
            encoding="utf-8",
        )
        from espalier.scanners.test_loosening import scan_file
        report = scan_file(str(f))
        rules = [r["rule"] for r in report["findings"]]
        assert "skip_no_reason" in rules

    def test_detects_skip_marker_without_reason(self, tmp_path):
        f = tmp_path / "test_x.py"
        f.write_text(
            "import pytest\n"
            "@pytest.mark.skip\n"
            "def test_a():\n    pass\n",
            encoding="utf-8",
        )
        from espalier.scanners.test_loosening import scan_file
        report = scan_file(str(f))
        rules = [r["rule"] for r in report["findings"]]
        assert "skip_no_reason" in rules

    def test_detects_xfail_marker_without_reason(self, tmp_path):
        f = tmp_path / "test_x.py"
        f.write_text(
            "import pytest\n"
            "@pytest.mark.xfail\n"
            "def test_a():\n    raise ValueError()\n",
            encoding="utf-8",
        )
        from espalier.scanners.test_loosening import scan_file
        report = scan_file(str(f))
        rules = [r["rule"] for r in report["findings"]]
        assert "xfail_no_reason" in rules

    def test_does_not_fire_on_xfail_with_reason(self, tmp_path):
        f = tmp_path / "test_x.py"
        f.write_text(
            "import pytest\n"
            "@pytest.mark.xfail(reason='upstream bug X')\n"
            "def test_a():\n    raise ValueError()\n",
            encoding="utf-8",
        )
        from espalier.scanners.test_loosening import scan_file
        report = scan_file(str(f))
        rules = [r["rule"] for r in report["findings"]]
        assert "xfail_no_reason" not in rules

    def test_detects_skip_on_async_test(self, tmp_path):
        """an `@pytest.mark.skip` (no reason) on an `async def` test
        must fire — pre-fix only ast.FunctionDef was inspected, so async tests
        evaded the check."""
        f = tmp_path / "test_x.py"
        f.write_text(
            "import pytest\n"
            "@pytest.mark.skip\n"
            "async def test_async(): pass\n"
            "@pytest.mark.xfail\n"
            "async def test_async_xf(): pass\n",
            encoding="utf-8",
        )
        from espalier.scanners.test_loosening import scan_file
        rules = [r["rule"] for r in scan_file(str(f))["findings"]]
        assert "skip_no_reason" in rules
        assert "xfail_no_reason" in rules

    def test_does_not_fire_on_async_skip_with_reason(self, tmp_path):
        f = tmp_path / "test_x.py"
        f.write_text(
            "import pytest\n"
            "@pytest.mark.skip(reason='env')\n"
            "async def test_async(): pass\n",
            encoding="utf-8",
        )
        from espalier.scanners.test_loosening import scan_file
        rules = [r["rule"] for r in scan_file(str(f))["findings"]]
        assert "skip_no_reason" not in rules

    def test_scan_repo_filters_to_test_files_only(self, tmp_path):
        (tmp_path / "test_a.py").write_text(
            "def test_x():\n    assert True\n", encoding="utf-8"
        )
        # Non-test file with a tautological assert must NOT be scanned
        (tmp_path / "helper.py").write_text(
            "def x():\n    assert True\n", encoding="utf-8"
        )
        from espalier.scanners.test_loosening import scan_repo
        report = scan_repo(str(tmp_path))
        assert report["files_scanned"] == 1
        assert report["count"] >= 1

    def test_handles_syntax_error_gracefully(self, tmp_path):
        f = tmp_path / "test_broken.py"
        f.write_text("def test_x(\n", encoding="utf-8")
        from espalier.scanners.test_loosening import scan_file
        report = scan_file(str(f))
        assert "syntax_error" in report
        assert report["count"] == 0

    def test_by_rule_aggregates_across_files(self, tmp_path):
        (tmp_path / "test_a.py").write_text(
            "def test_a():\n    assert True\n", encoding="utf-8"
        )
        (tmp_path / "test_b.py").write_text(
            "import pytest\n"
            "@pytest.mark.skip\n"
            "def test_b():\n    pass\n",
            encoding="utf-8",
        )
        from espalier.scanners.test_loosening import scan_repo
        report = scan_repo(str(tmp_path))
        assert report["by_rule"].get("assert_tautological") == 1
        assert report["by_rule"].get("skip_no_reason") == 1
        assert report["count"] == 2
