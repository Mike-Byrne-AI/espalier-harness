"""Fingerprint-pipeline contracts for espalier.analyze.

Pins the cross-platform invariants in the language / package / CI
detectors that the rest of the harness builds on. `analyze` is the
first step of every `espalier init`, `audit`, and `doctor` flow; if
these detectors return wrong shapes, the downstream `surface_contract`,
`harness_config`, and rendering stages compound the error silently.

Specific guards: path normalization always returns forward-slashes
(would fail on Windows hosts otherwise), make-target extraction skips
dot-prefixed phony targets, and the path-allowed filter degrades to
allow-all when no filters are configured.
"""
from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path

import espalier.analyze as analyze_module
from espalier.analyze import (
    HARNESS_OUTPUT_PREFIXES,
    is_harness_output,
    detect_languages,
    detect_package_systems,
    detect_package_roots,
    detect_entrypoints,
    detect_ci,
    detect_tests,
    detect_actions,
    detect_docs_surface,
    detect_runtime_surface,
    detect_api_surface,
    detect_ui_surface,
    detect_ml_surface,
    detect_ops_surface,
    detect_monorepo,
    detect_generated_zones,
    detect_large_files,
    detect_garbage_files,
    detect_conventions,
    risk_notes,
    fingerprint_repo,
    _parse_make_targets,
    _path_allowed,
    _rel,
)
from espalier.models import HarnessConfig, RepoFingerprint


# ─── _rel ───────────────────────────────────────────────────────────────────

class TestRel:
    def test_returns_forward_slashes(self, tmp_path):
        child = tmp_path / "src" / "main.py"
        child.parent.mkdir(parents=True)
        child.touch()
        result = _rel(child, tmp_path)
        assert "\\" not in result
        assert result == "src/main.py"

    def test_root_level_file(self, tmp_path):
        f = tmp_path / "README.md"
        f.touch()
        assert _rel(f, tmp_path) == "README.md"


# ─── _parse_make_targets ─────────────────────────────────────────────────────

class TestParseMakeTargets:
    def test_extracts_simple_targets(self, tmp_path):
        makefile = tmp_path / "Makefile"
        makefile.write_text("test:\n\tpytest\n\nbuild:\n\tpip install .\n", encoding="utf-8")
        targets = _parse_make_targets(makefile)
        assert "test" in targets
        assert "build" in targets

    def test_skips_dot_targets(self, tmp_path):
        makefile = tmp_path / "Makefile"
        makefile.write_text(".PHONY: test\ntest:\n\tpytest\n", encoding="utf-8")
        targets = _parse_make_targets(makefile)
        assert ".PHONY" not in targets
        assert "test" in targets


# ─── _path_allowed ───────────────────────────────────────────────────────────

class TestPathAllowed:
    def test_allows_all_when_no_filters(self, tmp_path):
        f = tmp_path / "src" / "main.py"
        f.parent.mkdir()
        f.touch()
        config = HarnessConfig()
        assert _path_allowed(f, tmp_path, config) is True

    def test_exclude_path_blocks_file(self, tmp_path):
        f = tmp_path / "vendor" / "lib.py"
        f.parent.mkdir()
        f.touch()
        config = HarnessConfig(exclude_paths=["vendor"])
        assert _path_allowed(f, tmp_path, config) is False

    def test_include_path_restricts_to_prefix(self, tmp_path):
        allowed = tmp_path / "src" / "a.py"
        blocked = tmp_path / "other" / "b.py"
        allowed.parent.mkdir()
        blocked.parent.mkdir()
        allowed.touch()
        blocked.touch()
        config = HarnessConfig(include_paths=["src"])
        assert _path_allowed(allowed, tmp_path, config) is True
        assert _path_allowed(blocked, tmp_path, config) is False

    def test_include_path_does_not_admit_sibling_dir(self, tmp_path):
        """include_paths=['src'] requires a path-segment
        boundary — src/ is admitted but siblings sharing the prefix
        (srcbox/, src_gen/) are rejected. Pre-fix the bare startswith
        admitted both."""
        in_src = tmp_path / "src" / "a.py"
        sib_box = tmp_path / "srcbox" / "x.py"
        sib_gen = tmp_path / "src_gen" / "y.py"
        for p in (in_src, sib_box, sib_gen):
            p.parent.mkdir()
            p.touch()
        config = HarnessConfig(include_paths=["src"])
        assert _path_allowed(in_src, tmp_path, config) is True
        assert _path_allowed(sib_box, tmp_path, config) is False
        assert _path_allowed(sib_gen, tmp_path, config) is False


# ─── detect_languages ────────────────────────────────────────────────────────

class TestDetectLanguages:
    def test_detects_python_files(self, tmp_path):
        (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
        counts, langs = detect_languages(tmp_path)
        assert "python" in langs
        assert counts["python"] >= 1

    def test_detects_typescript(self, tmp_path):
        (tmp_path / "index.ts").write_text("const x: number = 1;\n", encoding="utf-8")
        counts, langs = detect_languages(tmp_path)
        assert "typescript" in langs

    def test_empty_repo_returns_empty(self, tmp_path):
        counts, langs = detect_languages(tmp_path)
        assert langs == []
        assert counts == {}

    def test_counts_multiple_files_of_same_language(self, tmp_path):
        (tmp_path / "a.py").write_text("pass\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("pass\n", encoding="utf-8")
        counts, langs = detect_languages(tmp_path)
        assert counts["python"] == 2

    def test_skips_venv_directory(self, tmp_path):
        venv = tmp_path / ".venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "util.py").write_text("pass\n", encoding="utf-8")
        counts, langs = detect_languages(tmp_path)
        assert counts.get("python", 0) == 0


# ─── detect_package_systems ──────────────────────────────────────────────────

class TestDetectPackageSystems:
    def test_detects_python_from_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
        systems = detect_package_systems(tmp_path)
        assert "python" in systems

    def test_detects_python_from_requirements(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
        systems = detect_package_systems(tmp_path)
        assert "python" in systems

    def test_detects_node_from_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name":"app"}\n', encoding="utf-8")
        systems = detect_package_systems(tmp_path)
        assert "node" in systems

    def test_detects_rust_from_cargo_toml(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "app"\n', encoding="utf-8")
        systems = detect_package_systems(tmp_path)
        assert "rust" in systems

    def test_detects_go_from_go_mod(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/app\n", encoding="utf-8")
        systems = detect_package_systems(tmp_path)
        assert "go" in systems

    def test_empty_repo_returns_empty(self, tmp_path):
        systems = detect_package_systems(tmp_path)
        assert systems == []


# ─── detect_package_roots ────────────────────────────────────────────────────

class TestDetectPackageRoots:
    def test_finds_root_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        roots = detect_package_roots(tmp_path)
        assert "/" in roots or "." in roots or roots == ["/"]

    def test_finds_nested_package_json(self, tmp_path):
        pkg = tmp_path / "frontend"
        pkg.mkdir()
        (pkg / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
        roots = detect_package_roots(tmp_path)
        assert any("frontend" in r for r in roots)

    def test_empty_repo_returns_empty(self, tmp_path):
        roots = detect_package_roots(tmp_path)
        assert roots == []


# ─── detect_entrypoints ──────────────────────────────────────────────────────

class TestDetectEntrypoints:
    def test_detects_main_py(self, tmp_path):
        (tmp_path / "main.py").write_text("if __name__ == '__main__': pass\n", encoding="utf-8")
        hits = detect_entrypoints(tmp_path)
        assert "main.py" in hits

    def test_detects_app_py(self, tmp_path):
        (tmp_path / "app.py").write_text("from flask import Flask\n", encoding="utf-8")
        hits = detect_entrypoints(tmp_path)
        assert "app.py" in hits

    def test_detects_package_json_scripts(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"name":"app","scripts":{"dev":"next dev","test":"jest"}}\n',
            encoding="utf-8",
        )
        hits = detect_entrypoints(tmp_path)
        assert "package.json:scripts.dev" in hits

    def test_detects_pyproject_console_scripts(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            "[project.scripts]\nmy-tool = 'my_tool:main'\n",
            encoding="utf-8",
        )
        hits = detect_entrypoints(tmp_path)
        assert "pyproject.toml:scripts" in hits

    def test_empty_repo_returns_empty(self, tmp_path):
        hits = detect_entrypoints(tmp_path)
        assert hits == []


# ─── detect_ci ───────────────────────────────────────────────────────────────

class TestDetectCi:
    def test_detects_github_actions(self, tmp_path):
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        providers = detect_ci(tmp_path)
        assert "github_actions" in providers

    def test_detects_gitlab_ci(self, tmp_path):
        (tmp_path / ".gitlab-ci.yml").write_text("stages:\n  - test\n", encoding="utf-8")
        providers = detect_ci(tmp_path)
        assert "gitlab_ci" in providers

    def test_empty_repo_returns_empty(self, tmp_path):
        providers = detect_ci(tmp_path)
        assert providers == []


# ─── detect_tests ────────────────────────────────────────────────────────────

class TestDetectTests:
    def test_detects_pytest_from_tests_dir_and_pyproject(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        commands = detect_tests(tmp_path)
        assert "pytest -q" in commands

    def test_detects_pytest_from_pytest_ini(self, tmp_path):
        (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        commands = detect_tests(tmp_path)
        assert "pytest -q" in commands

    def test_detects_npm_test_from_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"scripts":{"test":"jest"}}\n', encoding="utf-8"
        )
        commands = detect_tests(tmp_path)
        assert "npm test" in commands

    def test_detects_cargo_test(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\n', encoding="utf-8")
        commands = detect_tests(tmp_path)
        assert "cargo test" in commands

    def test_detects_go_test(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com\n", encoding="utf-8")
        commands = detect_tests(tmp_path)
        assert "go test ./..." in commands

    def test_detects_make_test_from_makefile(self, tmp_path):
        (tmp_path / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")
        commands = detect_tests(tmp_path)
        assert "make test" in commands

    def test_empty_repo_returns_empty(self, tmp_path):
        commands = detect_tests(tmp_path)
        assert commands == []

    def test_bare_tests_dir_with_pytest_module_detects_pytest(self, tmp_path):
        """DEF-690: src/ + tests/test_app.py and no packaging file is still a
        Python test suite; the module is the signal."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_app.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        assert "pytest -q" in detect_tests(tmp_path)

    def test_bare_tests_dir_with_suffix_style_module_detects_pytest(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "app_test.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        assert "pytest -q" in detect_tests(tmp_path)

    def test_bare_tests_dir_without_python_modules_is_not_pytest(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "app.test.js").write_text("test('x', () => {});\n", encoding="utf-8")
        (tmp_path / "tests" / "helpers.py").write_text("X = 1\n", encoding="utf-8")  # not test-shaped
        assert "pytest -q" not in detect_tests(tmp_path)

    def test_rust_repo_with_tests_dir_does_not_add_pytest(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\n', encoding="utf-8")
        (tmp_path / "tests").mkdir()
        # A pytest-shaped module too: the empty-dir version of this test passed
        # vacuously while the bare-tests fallback listed pytest FIRST for Rust.
        (tmp_path / "tests" / "test_smoke.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        commands = detect_tests(tmp_path)
        assert "pytest -q" not in commands
        assert commands[0] == "cargo test"

    def test_node_repo_with_pytest_shaped_tests_keeps_npm_test(self, tmp_path):
        (tmp_path / "package.json").write_text('{"scripts":{"test":"jest"}}\n', encoding="utf-8")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_shim.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        assert detect_tests(tmp_path) == ["npm test"]


# ─── detect_actions ──────────────────────────────────────────────────────────

class TestDetectActions:
    def test_always_includes_audit(self, tmp_path):
        actions = detect_actions(tmp_path, [])
        assert "audit" in actions

    def test_includes_test_when_commands_present(self, tmp_path):
        actions = detect_actions(tmp_path, ["pytest -q"])
        assert "test" in actions
        assert actions["test"] == ["pytest -q"]

    def test_includes_scan_for_python_repo(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        actions = detect_actions(tmp_path, [])
        assert "scan" in actions

    def test_includes_lint_when_ruff_in_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            "[tool.ruff]\nline-length = 100\n", encoding="utf-8"
        )
        actions = detect_actions(tmp_path, [])
        assert "lint" in actions
        assert actions["lint"] == ["ruff check ."]

    def test_includes_build_from_package_json_scripts(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"scripts":{"build":"next build"}}\n', encoding="utf-8"
        )
        actions = detect_actions(tmp_path, [])
        assert "build" in actions


# ─── detect_docs_surface ─────────────────────────────────────────────────────

class TestDetectDocsSurface:
    def test_detects_readme(self, tmp_path):
        (tmp_path / "README.md").write_text("# Readme\n", encoding="utf-8")
        docs = detect_docs_surface(tmp_path)
        assert "README.md" in docs

    def test_detects_contributing(self, tmp_path):
        (tmp_path / "CONTRIBUTING.md").write_text("# Contributing\n", encoding="utf-8")
        docs = detect_docs_surface(tmp_path)
        assert "CONTRIBUTING.md" in docs

    def test_detects_docs_directory(self, tmp_path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "setup.md").write_text("# Setup\n", encoding="utf-8")
        docs = detect_docs_surface(tmp_path)
        assert "docs" in docs
        assert any("docs/setup.md" in d for d in docs)

    def test_empty_repo_returns_empty(self, tmp_path):
        docs = detect_docs_surface(tmp_path)
        assert docs == []


# ─── detect_runtime_surface ──────────────────────────────────────────────────

class TestDetectRuntimeSurface:
    def test_detects_app_py(self, tmp_path):
        (tmp_path / "app.py").write_text("pass\n", encoding="utf-8")
        hits = detect_runtime_surface(tmp_path)
        assert "app.py" in hits

    def test_detects_src_dir(self, tmp_path):
        (tmp_path / "src").mkdir()
        hits = detect_runtime_surface(tmp_path)
        assert "src" in hits

    def test_detects_python_package_with_init(self, tmp_path):
        pkg = tmp_path / "mypackage"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        hits = detect_runtime_surface(tmp_path)
        assert "mypackage" in hits


# ─── detect_api_surface ──────────────────────────────────────────────────────

class TestDetectApiSurface:
    def test_detects_fastapi_in_app_py(self, tmp_path):
        (tmp_path / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
        assert detect_api_surface(tmp_path) is True

    def test_detects_flask_in_server_py(self, tmp_path):
        (tmp_path / "server.py").write_text("from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8")
        assert detect_api_surface(tmp_path) is True

    def test_no_api_framework_returns_false(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        assert detect_api_surface(tmp_path) is False

    def test_empty_repo_returns_false(self, tmp_path):
        assert detect_api_surface(tmp_path) is False


# ─── detect_ui_surface ───────────────────────────────────────────────────────

class TestDetectUiSurface:
    def test_detects_react_in_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"dependencies":{"react":"^18.0.0"}}\n', encoding="utf-8"
        )
        assert detect_ui_surface(tmp_path) is True

    def test_detects_frontend_directory(self, tmp_path):
        (tmp_path / "frontend").mkdir()
        assert detect_ui_surface(tmp_path) is True

    def test_detects_tsx_files_in_src(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "App.tsx").write_text("export default function App() {}\n", encoding="utf-8")
        assert detect_ui_surface(tmp_path) is True

    def test_no_ui_signals_returns_false(self, tmp_path):
        (tmp_path / "main.py").write_text("pass\n", encoding="utf-8")
        assert detect_ui_surface(tmp_path) is False

    def test_detects_streamlit_in_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\ndependencies = ["streamlit"]\n', encoding="utf-8"
        )
        assert detect_ui_surface(tmp_path) is True

    def test_bare_pages_dir_without_web_content_is_not_ui(self, tmp_path):
        """a pure-Python repo with a pages/ dir (Django/docs) holding
        no web-ish file must NOT be detected as ui_surface. Pre-fix the bare
        directory name fired."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        pages = tmp_path / "pages"
        pages.mkdir()
        (pages / "about.md").write_text("# About\n", encoding="utf-8")
        assert detect_ui_surface(tmp_path) is False

    def test_django_public_images_only_is_not_ui(self, tmp_path):
        (tmp_path / "public").mkdir()
        (tmp_path / "public" / "logo.png").write_bytes(b"\x89PNG\r\n")
        assert detect_ui_surface(tmp_path) is False

    def test_pages_dir_with_jsx_is_ui(self, tmp_path):
        """VERIFY: a Next.js-style pages/ with a .jsx file still fires."""
        pages = tmp_path / "pages"
        pages.mkdir()
        (pages / "index.jsx").write_text("export default () => null\n", encoding="utf-8")
        assert detect_ui_surface(tmp_path) is True


# detect_ml_surface
# Multi-signal detector: requires 2+ independent signals to fire.
# Single-signal cases are intentionally False; the framework-shaped repos
# they used to fire on (a `models/` directory, a bare `torch` dep without
# a training script) are precisely the false-positive class that
# triggered the rewrite. Full coverage lives in
# tests/test_detect_ml_surface_{false,true}_positives.py.

class TestDetectMlSurface:
    def test_one_signal_does_not_fire(self, tmp_path):
        (tmp_path / "train.py").write_text("import torch\n", encoding="utf-8")
        assert detect_ml_surface(tmp_path) is False

    def test_two_signals_fire(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "m"\ndependencies = ["torch"]\n', encoding="utf-8"
        )
        (tmp_path / "train.py").write_text("import torch\n", encoding="utf-8")
        assert detect_ml_surface(tmp_path) is True

    def test_no_ml_signals_returns_false(self, tmp_path):
        (tmp_path / "app.py").write_text("pass\n", encoding="utf-8")
        assert detect_ml_surface(tmp_path) is False


# ─── detect_ops_surface ──────────────────────────────────────────────────────

class TestDetectOpsSurface:
    def test_triggers_on_two_ops_categories(self, tmp_path):
        (tmp_path / "content").mkdir()
        (tmp_path / "analytics").mkdir()
        is_ops, dirs = detect_ops_surface(tmp_path)
        assert is_ops is True
        assert "content" in dirs
        assert "analytics" in dirs

    def test_single_category_does_not_trigger(self, tmp_path):
        (tmp_path / "content").mkdir()
        is_ops, dirs = detect_ops_surface(tmp_path)
        assert is_ops is False

    def test_strategy_file_counts_as_category(self, tmp_path):
        (tmp_path / "content").mkdir()
        (tmp_path / "brand.md").write_text("# Brand\n", encoding="utf-8")
        is_ops, dirs = detect_ops_surface(tmp_path)
        assert is_ops is True

    def test_empty_repo_returns_false(self, tmp_path):
        is_ops, dirs = detect_ops_surface(tmp_path)
        assert is_ops is False
        assert dirs == []

    def test_data_plus_tasks_is_not_ops(self, tmp_path):
        """a plain code repo with data/ (fixtures) + tasks/ (Celery/
        invoke modules) must NOT be classified ai_ops_channel. Pre-fix this
        tripped the 2-category threshold (analytics+workflow)."""
        (tmp_path / "data").mkdir()
        (tmp_path / "tasks").mkdir()
        is_ops, _ = detect_ops_surface(tmp_path)
        assert is_ops is False

    def test_analytics_plus_workflow_without_content_is_not_ops(self, tmp_path):
        """two non-content categories alone are ambiguous — require a
        defining content/strategy marker."""
        (tmp_path / "metrics").mkdir()
        (tmp_path / "pipelines").mkdir()
        is_ops, _ = detect_ops_surface(tmp_path)
        assert is_ops is False


# ─── detect_monorepo ─────────────────────────────────────────────────────────

class TestDetectMonorepo:
    def test_two_non_root_packages_triggers_monorepo(self):
        assert detect_monorepo(["packages/a", "packages/b"]) is True

    def test_single_root_is_not_monorepo(self):
        assert detect_monorepo(["/"]) is False

    def test_empty_roots_is_not_monorepo(self):
        assert detect_monorepo([]) is False

    def test_root_and_one_nested_is_not_monorepo(self):
        assert detect_monorepo(["/", "packages/a"]) is False


# ─── detect_generated_zones ──────────────────────────────────────────────────

class TestDetectGeneratedZones:
    def test_detects_dist_directory(self, tmp_path):
        (tmp_path / "dist").mkdir()
        generated, risky = detect_generated_zones(tmp_path, [])
        assert "dist" in generated
        assert "dist" in risky

    def test_detects_build_directory(self, tmp_path):
        (tmp_path / "build").mkdir()
        generated, risky = detect_generated_zones(tmp_path, [])
        assert "build" in generated

    def test_many_package_roots_adds_risky_marker(self, tmp_path):
        roots = ["pkg/a", "pkg/b", "pkg/c"]
        _, risky = detect_generated_zones(tmp_path, roots)
        assert "multiple_package_roots" in risky

    def test_empty_repo_returns_empty(self, tmp_path):
        generated, risky = detect_generated_zones(tmp_path, [])
        assert generated == []
        assert risky == []


# ─── detect_large_files ──────────────────────────────────────────────────────

class TestDetectLargeFiles:
    def test_file_above_threshold_is_detected(self, tmp_path):
        big = tmp_path / "big.py"
        big.write_bytes(b"x = 1\n" * 40_000)
        hits = detect_large_files(tmp_path, threshold_bytes=100_000)
        assert any(h.path.replace("\\", "/") == "big.py" for h in hits)

    def test_file_below_threshold_is_not_detected(self, tmp_path):
        small = tmp_path / "small.py"
        small.write_text("x = 1\n", encoding="utf-8")
        hits = detect_large_files(tmp_path, threshold_bytes=200_000)
        assert hits == []

    def test_results_sorted_largest_first(self, tmp_path):
        (tmp_path / "a.py").write_bytes(b"x\n" * 30_000)
        (tmp_path / "b.py").write_bytes(b"x\n" * 60_000)
        hits = detect_large_files(tmp_path, threshold_bytes=10_000)
        assert hits[0].size_bytes >= hits[-1].size_bytes

    # Two independent defects converged on this report: the walker did not skip
    # the type-checker caches its sibling scanner already skips, and
    # `errors="replace"` never raises, so the `except OSError` "binary — report
    # size only" branch was unreachable and a database got a fabricated `loc`.
    # BOTH are asserted. The skip-set fix alone makes the cache row vanish, which
    # would green a test that only looked for it — while leaving the fabrication
    # live for any adopter with a legitimately large tracked binary.
    @staticmethod
    def _write_binary(path, *, lines=40_000):
        """A >threshold binary shaped like a real cache db: a NUL inside the
        first 8 KiB, non-UTF-8 bytes, and newlines — so a decode-based line
        count returns a plausible non-zero number instead of failing."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"SQLite format 3\x00" + b"\xff\xfe\n" * lines)

    def test_type_checker_cache_is_skipped(self, tmp_path):
        self._write_binary(tmp_path / ".mypy_cache" / "3.14" / "cache.9.db")
        (tmp_path / "real.py").write_bytes(b"x = 1\n" * 40_000)
        hits = detect_large_files(tmp_path, threshold_bytes=100_000)
        paths = [h.path.replace("\\", "/") for h in hits]
        assert paths == ["real.py"], paths

    def test_binary_outside_the_skip_set_reports_zero_loc(self, tmp_path):
        self._write_binary(tmp_path / "assets" / "fixture.bin")
        hits = detect_large_files(tmp_path, threshold_bytes=100_000)
        binary = [h for h in hits if h.path.replace("\\", "/") == "assets/fixture.bin"]
        assert binary, [h.path for h in hits]
        assert binary[0].loc == 0, f"fabricated line count: {binary[0].loc}"

    def test_large_text_file_still_reports_real_loc(self, tmp_path):
        (tmp_path / "big.py").write_bytes(b"x = 1\n" * 40_000)
        hits = detect_large_files(tmp_path, threshold_bytes=100_000)
        assert hits[0].loc == 40_000


# ─── detect_garbage_files ────────────────────────────────────────────────────

class TestDetectGarbageFiles:
    def test_detects_suspicious_filename(self, tmp_path):
        (tmp_path / "cc_surface_gate.py").write_text("pass\n", encoding="utf-8")
        hits = detect_garbage_files(tmp_path)
        assert "cc_surface_gate.py" in hits

    def test_detects_suspicious_content_in_txt(self, tmp_path):
        (tmp_path / "notes.txt").write_text("SUMMARY OF LESS COMMANDS\nsome content\n", encoding="utf-8")
        hits = detect_garbage_files(tmp_path)
        assert "notes.txt" in hits

    def test_clean_file_not_flagged(self, tmp_path):
        (tmp_path / "README.md").write_text("# Normal README\n", encoding="utf-8")
        hits = detect_garbage_files(tmp_path)
        assert "README.md" not in hits

    def test_empty_repo_returns_empty(self, tmp_path):
        hits = detect_garbage_files(tmp_path)
        assert hits == []

    def test_py_quoting_marker_not_flagged(self, tmp_path):
        """a .py source file that merely *quotes* a marker as a
        constant is not garbage (pre-fix it was flagged)."""
        (tmp_path / "patch_parser.py").write_text(
            'HEADER = "diff --git a/"\n', encoding="utf-8"
        )
        assert "patch_parser.py" not in detect_garbage_files(tmp_path)

    def test_readme_fencing_diff_example_not_flagged(self, tmp_path):
        """a README that embeds a `diff --git a/` example deeper in
        the body (not leading) is not a dump (pre-fix it was flagged)."""
        (tmp_path / "CONTRIBUTING.md").write_text(
            "# Contributing\n\nSubmit patches like:\n\n"
            "```diff\ndiff --git a/foo b/foo\n```\n",
            encoding="utf-8",
        )
        assert "CONTRIBUTING.md" not in detect_garbage_files(tmp_path)

    def test_leading_dump_still_flagged(self, tmp_path):
        """VERIFY: a real dump that LEADS with the junk still fires."""
        (tmp_path / "stray.txt").write_text(
            "diff --git a/x b/x\n@@ -1 +1 @@\n", encoding="utf-8"
        )
        assert "stray.txt" in detect_garbage_files(tmp_path)


# ─── detect_conventions ──────────────────────────────────────────────────────

class TestDetectConventions:
    def test_returns_dict_with_known_keys(self, tmp_path):
        result = detect_conventions(tmp_path)
        assert isinstance(result, dict)

    def test_detects_src_layout(self, tmp_path):
        (tmp_path / "src").mkdir()
        result = detect_conventions(tmp_path)
        layout = result.get("layout", [])
        assert any("src/" in item for item in layout)

    def test_detects_ruff_in_commands(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
        result = detect_conventions(tmp_path)
        commands = result.get("commands", [])
        assert any("ruff" in item.lower() for item in commands)

    def test_detects_tests_directory_convention(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        result = detect_conventions(tmp_path, {"test_commands": ["pytest -q"]})
        tests_convs = result.get("tests", [])
        assert any("tests/" in item for item in tests_convs)

    def test_ops_surface_adds_guardrails(self, tmp_path):
        (tmp_path / "content").mkdir()
        (tmp_path / "analytics").mkdir()
        result = detect_conventions(tmp_path)
        guardrails = result.get("guardrails", [])
        assert any("analytics" in item.lower() for item in guardrails)

    def test_ops_signals_dir_adds_analytics_guardrail(self, tmp_path):
        # earn-the-red: a `signals/` ops dir must add the analytics
        # guardrail. Pre-fix the hardcoded set was {analytics, metrics,
        # engagement, data} — missing signals/feedback (and carrying the dead
        # 'data'), out of sync with the canonical OPS_ANALYTICS_DIRS — so the
        # guardrail was silently skipped for a signals/ ops surface.
        (tmp_path / "content").mkdir()  # 2nd ops category so ops_surface fires
        (tmp_path / "signals").mkdir()
        result = detect_conventions(tmp_path)
        guardrails = result.get("guardrails", [])
        assert any("fabricate" in item.lower() for item in guardrails)

    def test_single_root_with_sentinel_no_multiroot_guardrail(self, tmp_path):
        # earn-the-red: one real root plus the "/" sentinel must NOT
        # trip the multiple-package-roots guardrail. Pre-fix `len(package_roots)
        # >= 2` counted the sentinel.
        result = detect_conventions(tmp_path, {"package_roots": ["/", "pkg"]})
        guardrails = result.get("guardrails", [])
        assert not any("Multiple package roots" in item for item in guardrails)

    def test_two_real_roots_trips_multiroot_guardrail(self, tmp_path):
        result = detect_conventions(tmp_path, {"package_roots": ["pkg/a", "pkg/b"]})
        guardrails = result.get("guardrails", [])
        assert any("Multiple package roots" in item for item in guardrails)


# ─── risk_notes ──────────────────────────────────────────────────────────────

class TestRiskNotes:
    def test_no_test_commands_emits_note(self):
        fp = RepoFingerprint(repo_name="x", repo_root=".", test_commands=[])
        notes = risk_notes(fp)
        assert any("test command" in n.lower() for n in notes)

    def test_garbage_files_emits_note(self):
        fp = RepoFingerprint(repo_name="x", repo_root=".", garbage_files=["junk.txt"])
        notes = risk_notes(fp)
        assert any("junk" in n.lower() or "suspicious" in n.lower() for n in notes)

    def test_monorepo_emits_note(self):
        fp = RepoFingerprint(repo_name="x", repo_root=".", monorepo=True)
        notes = risk_notes(fp)
        assert any("multiple" in n.lower() or "monorepo" in n.lower() or "package" in n.lower() for n in notes)

    def test_clean_fingerprint_no_notes(self):
        fp = RepoFingerprint(
            repo_name="x",
            repo_root=".",
            test_commands=["pytest -q"],
            garbage_files=[],
            monorepo=False,
            large_files=[],
        )
        notes = risk_notes(fp)
        assert notes == []


# ─── fingerprint_repo ────────────────────────────────────────────────────────

class TestFingerprintRepo:
    def test_empty_repo_does_not_crash(self, tmp_path):
        fp = fingerprint_repo(tmp_path)
        assert fp.repo_name == tmp_path.name

    def test_python_repo_detected_correctly(self, python_repo):
        fp = fingerprint_repo(python_repo)
        assert set(fp.languages) == {"python"}
        assert fp.api_surface is True

    def test_node_repo_detected_correctly(self, node_repo):
        fp = fingerprint_repo(node_repo)
        assert set(fp.languages) == {"javascript"}
        assert set(fp.package_systems) == {"node"}

    def test_fingerprint_repo_name_matches_directory(self, tmp_path):
        fp = fingerprint_repo(tmp_path)
        assert fp.repo_name == tmp_path.name

    def test_to_dict_produces_serialisable_output(self, tmp_path):
        fp = fingerprint_repo(tmp_path)
        data = fp.to_dict()
        json_str = json.dumps(data)
        assert isinstance(json_str, str)

    def test_repo_root_in_to_dict_is_dot(self, tmp_path):
        fp = fingerprint_repo(tmp_path)
        assert fp.to_dict()["repo_root"] == "."


class TestDetectArchitecture:
    def test_harness_layered_pattern(self, tmp_path):
        from espalier.analyze import detect_architecture
        (tmp_path / "espalier").mkdir()
        (tmp_path / "tools" / "cc").mkdir(parents=True)
        (tmp_path / "espalier" / "scanners").mkdir()
        arch = detect_architecture(tmp_path)
        assert arch["pattern"] == "harness_layered"
        assert "espalier" in arch["layers"]
        assert "tools/cc" in arch["layers"]
        assert "espalier/scanners" in arch["layers"]
        assert arch["layer_rules"]["tools/cc"] == "zero_espalier_imports"
        assert arch["layer_rules"]["espalier/scanners"] == "stdlib_only"

    def test_src_layout_pattern(self, tmp_path):
        from espalier.analyze import detect_architecture
        (tmp_path / "src" / "mypackage").mkdir(parents=True)
        arch = detect_architecture(tmp_path)
        assert arch["pattern"] == "src_layout"
        assert "src/mypackage" in arch["layers"]

    def test_mvc_pattern(self, tmp_path):
        from espalier.analyze import detect_architecture
        for d in ("controllers", "services", "models"):
            (tmp_path / d).mkdir()
        arch = detect_architecture(tmp_path)
        assert arch["pattern"] == "mvc"
        assert "controllers" in arch["layers"]
        assert "services" in arch["layers"]
        assert "models" in arch["layers"]

    def test_flat_fallback(self, tmp_path):
        from espalier.analyze import detect_architecture
        arch = detect_architecture(tmp_path)
        assert arch["pattern"] == "flat"
        assert arch["layers"] == []

    def test_harness_layered_without_scanners(self, tmp_path):
        from espalier.analyze import detect_architecture
        (tmp_path / "espalier").mkdir()
        (tmp_path / "tools" / "cc").mkdir(parents=True)
        arch = detect_architecture(tmp_path)
        assert arch["pattern"] == "harness_layered"
        assert "espalier/scanners" not in arch["layers"]


# ─── seed-stamped docs are harness provenance, not adopter content ──────────


def _seed_stamped(body: str) -> str:
    import hashlib

    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"<!-- espalier:seed-version v0.8.0a13 sha256:{digest} -->\n{body}"


class TestSeedStampedDocsExcluded:
    """DEF-686: ``init`` seeds ~20 docs (FAILURE_MODES.md alone > 400 KB) at
    adopter paths. Keyed on the first-line stamp, not the path, because the
    same path unstamped IS the adopter's doc."""

    def test_docs_surface_skips_stamped_and_keeps_unstamped(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "FAILURE_MODES.md").write_text(_seed_stamped("# Failure modes\n"), encoding="utf-8")
        (docs / "GUIDE.md").write_text("# Their guide\n", encoding="utf-8")
        surface = detect_docs_surface(tmp_path)
        assert "docs/GUIDE.md" in surface
        assert "docs/FAILURE_MODES.md" not in surface
        assert "docs" in surface  # the directory itself is still a cue

    def test_same_path_unstamped_is_the_adopters_doc(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "FAILURE_MODES.md").write_text("# Our own failure modes\n", encoding="utf-8")
        assert "docs/FAILURE_MODES.md" in detect_docs_surface(tmp_path)

    def test_stamp_not_on_first_line_does_not_exclude(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "NOTES.md").write_text("\n" + _seed_stamped("# Notes\n"), encoding="utf-8")
        assert "docs/NOTES.md" in detect_docs_surface(tmp_path)

    def test_stamped_large_seed_is_not_a_large_file(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        body = "line\n" * 60_000  # ~300 KB, over the 200 KB threshold
        (docs / "FAILURE_MODES.md").write_text(_seed_stamped(body), encoding="utf-8")
        assert detect_large_files(tmp_path) == []
        (docs / "THEIRS.md").write_text(body, encoding="utf-8")
        assert [lf.path for lf in detect_large_files(tmp_path)] == ["docs/THEIRS.md"]

    def test_crlf_resaved_seed_is_still_excluded(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        body = "line\n" * 60_000
        (docs / "FAILURE_MODES.md").write_bytes(_seed_stamped(body).replace("\n", "\r\n").encode("utf-8"))
        assert "docs/FAILURE_MODES.md" not in detect_docs_surface(tmp_path)
        assert detect_large_files(tmp_path) == []

    def test_seeded_tree_is_not_docs_heavy(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='app'\n", encoding="utf-8")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        (tmp_path / "README.md").write_text("# app\n", encoding="utf-8")
        docs = tmp_path / "docs"
        docs.mkdir()
        for name in ("FAILURE_MODES", "SHARP_EDGES", "HOOKS", "WORKFLOW", "CHEAT-SHEET"):
            (docs / f"{name}.md").write_text(_seed_stamped(f"# {name}\n" + "x\n" * 50_000), encoding="utf-8")
        fp = fingerprint_repo(tmp_path)
        assert "docs_heavy" not in fp.profiles
        assert fp.large_files == []
        assert all(not d.startswith("docs/") for d in fp.docs_surface)
        # Derived guard against a FOURTH walker: no seed path may surface in
        # ANY fingerprint field, whichever detector a future change adds.
        dumped = json.dumps(fp.to_dict())
        for name in ("FAILURE_MODES", "SHARP_EDGES", "HOOKS", "WORKFLOW", "CHEAT-SHEET"):
            assert f"docs/{name}.md" not in dumped, name


# ─── DEF-410f: one harness-output predicate; init leaves the fingerprint alone ─

ANALYZE_PATH = Path(analyze_module.__file__)

# The driven differential -- a real `init` on a three-file repo changes no
# fingerprint field -- lives in tests/test_init_fingerprint_differential.py:
# it shells out to git, and the suite contract keeps child processes out of
# this `unit` module (which is also byte-mirrored into the selfcheck subset).


class TestDocsDirectoryCue:
    """The ``docs`` cue is earned by adopter-owned content, not by the
    directory: ``init`` creates ``docs/`` on a repo that had none and fills it
    with stamped seeds, and a cue on that directory reached the fingerprint,
    the ``docs_surface`` signal and two docs conventions (DEF-410f)."""

    def _seeds(self, root: Path) -> Path:
        docs = root / "docs"
        docs.mkdir()
        for name in ("FAILURE_MODES", "SHARP_EDGES", "HOOKS"):
            (docs / f"{name}.md").write_text(_seed_stamped(f"# {name}\n"), encoding="utf-8")
        return docs

    def test_a_docs_dir_of_seeds_only_is_not_a_cue(self, tmp_path):
        self._seeds(tmp_path)
        (tmp_path / "README.md").write_text("# app\n", encoding="utf-8")
        assert detect_docs_surface(tmp_path) == ["README.md"]
        fp = fingerprint_repo(tmp_path)
        assert "docs_surface" not in {signal.name for signal in fp.signals}
        assert not any("docs/ exists" in line for line in fp.conventions.get("docs", []))

    def test_one_unstamped_markdown_earns_the_cue(self, tmp_path):
        docs = self._seeds(tmp_path)
        (docs / "GUIDE.md").write_text("# Their guide\n", encoding="utf-8")
        assert detect_docs_surface(tmp_path) == ["docs", "docs/GUIDE.md"]

    def test_a_non_markdown_adopter_file_earns_the_cue(self, tmp_path):
        docs = self._seeds(tmp_path)
        (docs / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        assert detect_docs_surface(tmp_path) == ["docs"]

    def test_an_empty_docs_dir_is_not_a_cue(self, tmp_path):
        (tmp_path / "docs").mkdir()
        assert detect_docs_surface(tmp_path) == []

    def test_placeholders_and_generated_trees_are_not_adopter_content(self, tmp_path):
        """Driven 2026-09-12 by the failure-mode pass: Finder writes
        docs/.DS_Store the moment a macOS adopter opens the seeded directory,
        and that one file re-earned the cue, the signal and the conventions."""
        docs = self._seeds(tmp_path)
        (docs / ".DS_Store").write_bytes(b"\x00\x01")
        (docs / "Thumbs.db").write_bytes(b"\x00")
        (docs / ".gitkeep").write_text("", encoding="utf-8")
        (docs / "node_modules" / "pkg").mkdir(parents=True)
        (docs / "node_modules" / "pkg" / "index.js").write_text("module.exports = 1;\n", encoding="utf-8")
        assert detect_docs_surface(tmp_path) == []
        (docs / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        assert detect_docs_surface(tmp_path) == ["docs"]

    def test_every_seed_under_docs_is_markdown(self):
        """The stamp is checked on ``.md`` only; a non-Markdown seed under
        docs/ would count as adopter content and reopen the cue, so the seed
        inventory is pinned to that assumption."""
        from espalier.managed_inventory import get_seed_docs

        under_docs = [rel for rel in get_seed_docs() if rel.startswith("docs/")]
        assert under_docs  # the pin has a population behind it
        assert all(rel.endswith(".md") for rel in under_docs), under_docs

    def test_conventions_key_on_the_detected_surface(self, tmp_path):
        docs = self._seeds(tmp_path)
        line = "docs/ exists; prefer repo-local documentation patterns over invented ones."
        assert line not in detect_conventions(tmp_path).get("docs", [])
        (docs / "GUIDE.md").write_text("# Their guide\n", encoding="utf-8")
        assert line in detect_conventions(tmp_path)["docs"]
        # an explicit empty surface from the caller means none, not "detect it"
        assert line not in detect_conventions(tmp_path, {"docs_surface": []}).get("docs", [])


class TestHarnessOutputPredicate:
    """``HARNESS_OUTPUT_PREFIXES`` is derived from the two inventory owners
    and ``is_harness_output`` is the one predicate every consumer reads. Both
    directions are pinned: every owner entry is harness output (no drop) and
    every prefix is an owner entry or the one rostered self-host extra (no
    invention); and the tuple is loaded by the predicate alone, so no consumer
    can inline a second copy of the match."""

    @staticmethod
    def _owners() -> set[str]:
        from espalier.managed_inventory import get_local_runtime_prefixes
        from espalier.managed_paths import HARNESS_OWNED_ROOTS

        return {*HARNESS_OWNED_ROOTS, *(p.rstrip("/") for p in get_local_runtime_prefixes())}

    def test_every_inventory_owner_is_harness_output(self):
        owners = self._owners()
        assert owners  # the derivation has a population behind it
        for rel in owners:
            assert is_harness_output(rel), rel
            assert is_harness_output(rel + "/anything.py"), rel

    def test_every_prefix_is_an_owner_or_the_rostered_extra(self):
        # bench/results: the self-host benchmark's gitignored output, which no
        # adopter inventory names because no adopter receives it
        assert set(HARNESS_OUTPUT_PREFIXES) - self._owners() == {"bench/results"}

    def test_the_derived_tuple_is_the_set_it_was_calibrated_on(self):
        """Derived, so a prefix added to an inventory owner arrives here by
        construction -- and also stops the fingerprint from seeing that
        directory on every adopter tree. This pin makes that widening a
        decision: confirm it is intended, then update the set."""
        # cc/_cold: the plan records the reset verb demotes (DEF-788). Inside
        # `cc`, already harness output, so the widening hides nothing new.
        assert set(HARNESS_OUTPUT_PREFIXES) == {
            ".claude", "cc", "cc/blueprints", "cc/_cold", "tools/cc",
            ".espalier", ".espalier-state", "reports", "bench/results",
        }, (
            "a prefix was added to an inventory owner; it now also hides that "
            "directory from every adopter's fingerprint -- confirm that is "
            "intended, then update this pin"
        )

    def test_the_tuple_is_loaded_only_by_the_predicate(self):
        """A consumer that inlines the match instead of calling the predicate
        is the third spelling coming back: the walker did exactly that on the
        first draft of this lane -- byte-identical that day, and a hardening
        of the predicate would have skipped it."""
        tree = ast.parse(ANALYZE_PATH.read_text(encoding="utf-8"))
        loads = sorted({
            func.name
            for func in ast.walk(tree) if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef))
            for node in ast.walk(func)
            if isinstance(node, ast.Name) and node.id == "HARNESS_OUTPUT_PREFIXES"
        })
        assert loads == ["is_harness_output"], (
            f"a consumer inlined the predicate body instead of calling it: {loads}"
        )

    def test_a_user_path_sharing_a_basename_or_a_string_prefix_is_not(self):
        for rel in ("tools", "tools/x.py", "tools/ccache/x", "ccache", "benchmark/results/x", "reportsx"):
            assert not is_harness_output(rel), rel

    # Recursive walks only: a shallow ``repo_root.iterdir()`` lists the top
    # level, where the harness-output prefixes are whole entries the four
    # existing detectors filter by name (line 455 asks the predicate); the
    # class is a walk that reaches a deployed file at depth.
    _WALKERS = frozenset({"safe_rglob", "rglob", "glob", "walk"})

    @classmethod
    def _root_walks(cls, source: str) -> list[str]:
        """Every walk of ``repo_root`` outside ``_iter_files``, in either
        spelling: the helper form ``safe_rglob(repo_root, ...)`` /
        ``os.walk(repo_root)`` (the root is the first argument) and the
        pathlib form ``repo_root.rglob(...)`` (the root is the receiver)."""
        tree = ast.parse(source)
        hits = []
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)) or func.name == "_iter_files":
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.Call):
                    continue
                name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                if name not in cls._WALKERS:
                    continue
                first = node.args[0] if node.args else None
                recv = node.func.value if isinstance(node.func, ast.Attribute) else None
                on_root = any(
                    isinstance(n, ast.Name) and n.id == "repo_root" for n in (first, recv)
                )
                if on_root:
                    hits.append(f"{func.name}:{node.lineno} {ast.unparse(node)}")
        return hits

    def test_no_detector_walks_the_repo_root_outside_the_filtered_walker(self):
        """The Windows-helpers detector did (`safe_rglob(repo_root, '*.cmd')`),
        so the deployed statusline shim (DEF-729) read as the adopter's own
        helper and the fingerprint drifted on every fresh init -- the
        predicate is the one owner only for walks that go through
        ``_iter_files``. A walk scoped to a subdirectory that is never harness
        output (docs/, src/, a notebooks dir) is not this class."""
        hits = self._root_walks(ANALYZE_PATH.read_text(encoding="utf-8"))
        assert not hits, (
            "a detector walks the repo root without the harness-output filter; "
            f"go through _iter_files: {hits}"
        )

    def test_the_root_walk_matcher_sees_both_spellings(self):
        """The must-NOT-pass fixture: the helper form the detector used, and
        the pathlib form a future detector would idiomatically write (the
        first draft of this matcher read only the first argument and let the
        receiver spelling through -- the failure-mode review's finding)."""
        source = (
            "def d(repo_root):\n"
            "    a = list(safe_rglob(repo_root, '*.cmd'))\n"
            "    b = list(repo_root.rglob('*.cmd'))\n"
            "    c = list(os.walk(repo_root))\n"
            "    d = list(safe_rglob(repo_root / 'docs'))\n"
            "    return a, b, c, d\n"
        )
        hits = self._root_walks(source)
        assert [h.split(" ", 1)[1] for h in hits] == [
            "safe_rglob(repo_root, '*.cmd')",
            "repo_root.rglob('*.cmd')",
            "os.walk(repo_root)",
        ], hits

    def test_the_deployed_windows_shim_is_not_the_adopters_windows_helper(self, tmp_path):
        line = "Windows shell helpers are present; preserve existing command style where possible."
        shim = tmp_path / "tools" / "cc" / "statusline.cmd"
        shim.parent.mkdir(parents=True)
        shim.write_text("@echo off\n", encoding="utf-8")
        assert line not in detect_conventions(tmp_path).get("commands", [])
        (tmp_path / "build.cmd").write_text("@echo off\n", encoding="utf-8")
        assert line in detect_conventions(tmp_path).get("commands", [])

    def test_runtime_surface_skips_a_package_named_like_harness_output(self, tmp_path):
        for name in ("cc", "reports", ".claude", ".espalier"):
            (tmp_path / name).mkdir()
            (tmp_path / name / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "tools").mkdir()
        (tmp_path / "tools" / "__init__.py").write_text("", encoding="utf-8")
        surface = detect_runtime_surface(tmp_path)
        assert "tools" in surface  # a user's top-level tools/ package stays a candidate
        assert not {"cc", "reports", ".claude", ".espalier"} & set(surface)


_EXISTENCE_ATTRS = frozenset({"exists", "is_dir", "is_file"})
_OS_PATH_ATTRS = frozenset({"exists", "isdir", "isfile"})
_UNRESOLVED = "<unresolved>"

#: Bare existence probes on a path the harness deploys, keyed (function,
#: repo-relative literal) -> (how many such probes the function holds, why the
#: probe is not a leak). Hand-written on purpose: the census DERIVES the
#: population from analyze.py by AST walk and asserts equality, so a new probe
#: on a harness path reds here and so does a stale exemption; the count is
#: asserted too, so a second probe added inside an exempt function reds. The
#: shape is ``tests/test_atomic_io.py``'s rosters with the module column
#: dropped -- one module, so the key's first half is the function.
_EXISTENCE_EXEMPT: dict[tuple[str, str], tuple[int, str]] = {
    ("detect_ci", ".github/workflows"): (1,
        "install-ci writes harness-guard.yml there, and the fact that makes "
        "true -- this repo runs GitHub Actions -- is re-baselined at the "
        "writer (DEF-688), never hidden at the detector"),
    ("detect_architecture", "tools/cc"): (1,
        "the self-host layering probe, gated on espalier/ beside it; an "
        "adopter tree has no espalier/, so the deployed tools/cc never flips it"),
    ("detect_docs_surface", "docs"): (1,
        "content-gated: the cue needs one adopter-owned file under docs/; the "
        "seeds are excluded by stamp and the directory they create is not a cue"),
}


def _module_constant_strings(tree: ast.Module) -> dict[str, list[str]]:
    """Module-level ``NAME = ("a", "b")`` / ``[...]`` of string constants."""
    out: dict[str, list[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not (isinstance(value, (ast.Tuple, ast.List)) and value.elts and all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in value.elts
        )):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                out[target.id] = [e.value for e in value.elts]
    return out


def _string_options(expr: ast.expr, loops: dict[str, list[str]], consts: dict[str, list[str]]) -> list[str] | None:
    """The strings an expression can be: a constant, a loop variable over
    string constants, a module constant list, or a literal tuple/list of
    strings. None when it is none of those."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return [expr.value]
    if isinstance(expr, ast.Name):
        return loops.get(expr.id) or consts.get(expr.id)
    if isinstance(expr, (ast.Tuple, ast.List)) and expr.elts and all(
        isinstance(e, ast.Constant) and isinstance(e.value, str) for e in expr.elts
    ):
        return [e.value for e in expr.elts]
    return None


def _joined(
    bases: list[str], segments: list[ast.expr], loops: dict[str, list[str]], consts: dict[str, list[str]],
) -> list[str]:
    paths = list(bases)
    for segment in segments:
        options = _string_options(segment, loops, consts) or [_UNRESOLVED]
        paths = [f"{base}/{option}" if base else option for base in paths for option in options]
    return paths


def _chain_paths(
    expr: ast.expr, loops: dict[str, list[str]], consts: dict[str, list[str]], aliases: dict[str, list[str]],
) -> list[str] | None:
    """Resolve a path expression rooted at ``repo_root`` -- ``repo_root / a / b``,
    ``repo_root.joinpath(a, b)``, ``Path(repo_root, a, b)``, or a local alias
    bound to one of those -- to the repo-relative paths it can name. None when
    the expression is not rooted at ``repo_root`` (an ``iterdir`` child, a
    walk result; the differential covers those). A segment the resolver
    cannot read yields ``<unresolved>`` so it cannot pass silently."""
    if isinstance(expr, ast.Name):
        if expr.id == "repo_root":
            return [""]
        return aliases.get(expr.id)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
        lefts = _chain_paths(expr.left, loops, consts, aliases)
        return None if lefts is None else _joined(lefts, [expr.right], loops, consts)
    if isinstance(expr, ast.Call):
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "joinpath":
            base = _chain_paths(expr.func.value, loops, consts, aliases)
            return None if base is None else _joined(base, list(expr.args), loops, consts)
        if isinstance(expr.func, ast.Name) and expr.func.id == "Path" and expr.args:
            base = _chain_paths(expr.args[0], loops, consts, aliases)
            return None if base is None else _joined(base, list(expr.args[1:]), loops, consts)
    return None


def _mentions_root(expr: ast.expr, aliases: dict[str, list[str]]) -> bool:
    return any(
        isinstance(node, ast.Name) and (node.id == "repo_root" or node.id in aliases)
        for node in ast.walk(expr)
    )


def _is_os_path(expr: ast.expr) -> bool:
    return (
        isinstance(expr, ast.Attribute) and expr.attr == "path"
        and isinstance(expr.value, ast.Name) and expr.value.id == "os"
    )


def _probe_receiver(call: ast.Call) -> ast.expr | None:
    """The path expression an existence call probes: the receiver of
    ``.exists()`` / ``.is_dir()`` / ``.is_file()``, or the first argument of
    ``os.path.exists`` / ``isdir`` / ``isfile``. None for any other call."""
    if not isinstance(call.func, ast.Attribute):
        return None
    if _is_os_path(call.func.value):
        return call.args[0] if call.func.attr in _OS_PATH_ATTRS and call.args else None
    return call.func.value if call.func.attr in _EXISTENCE_ATTRS else None


def _bare_existence_probes(source: str) -> list[tuple[str, str]]:
    """Every existence probe on a path rooted at ``repo_root`` in the module,
    as (enclosing function, repo-relative literal). Derived by an AST walk,
    so a new detector is censused the day it is written. Resolves the inline
    chain, ``joinpath``, the ``Path(...)`` constructor, ``os.path.*`` over any
    of those, a local alias (``docs_dir = repo_root / "docs"``), and a for /
    comprehension variable over string constants or a module-level constant
    list (a variable bound twice takes the union, so a probe is never
    dropped). A probe whose receiver mentions ``repo_root`` (or an alias) and
    does not resolve is reported as ``<unresolved>``: a new spelling is loud,
    never silent. A receiver that never mentions the root -- an ``iterdir``
    child, a walk result -- is an enumeration, which the differential covers."""
    tree = ast.parse(source)
    consts = _module_constant_strings(tree)
    probes: list[tuple[str, str]] = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(arg.arg == "repo_root" for arg in (*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs)):
            continue
        loops: dict[str, list[str]] = {}
        for node in ast.walk(func):
            if isinstance(node, (ast.For, ast.comprehension)) and isinstance(node.target, ast.Name):
                options = _string_options(node.iter, loops, consts)
                if options is not None:
                    loops[node.target.id] = list(dict.fromkeys([*loops.get(node.target.id, []), *options]))
        aliases: dict[str, list[str]] = {}
        for node in ast.walk(func):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                paths = _chain_paths(node.value, loops, consts, aliases)
                if paths is not None:
                    aliases[node.targets[0].id] = paths
        for node in ast.walk(func):
            receiver = _probe_receiver(node) if isinstance(node, ast.Call) else None
            if receiver is None:
                continue
            paths = _chain_paths(receiver, loops, consts, aliases)
            if paths is None:
                if not _mentions_root(receiver, aliases):
                    continue  # an enumeration, not a probe on a root-relative literal
                paths = [_UNRESOLVED]
            probes.extend((func.name, path) for path in paths)
    return probes


def _probes_existence(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(node, ast.Call) and _probe_receiver(node) is not None
        for node in ast.walk(func)
    )


def _harness_touched(rel: str) -> bool:
    """Would the harness put something at, or under, this repo-relative path?
    Derived from the inventory owners -- never a hand list of detector names:
    the deployed and packaged files, the seeds, install-ci's artifacts, the
    local runtime paths, and every deployed or runtime prefix."""
    from espalier import managed_inventory as mi
    from espalier.managed_paths import HARNESS_OWNED_ROOTS, STANDARD_MANAGED_ROOT_DOCS, STANDARD_MANAGED_TOOLS

    files = {
        *mi.get_seed_docs(), *mi.get_install_ci_artifacts(), *mi.get_local_only_files(),
        *mi.local_runtime_rel_paths(), *mi.get_generated_docs(), *mi.get_hook_entry_files(),
        *mi.get_hook_helper_files(), *STANDARD_MANAGED_TOOLS, *STANDARD_MANAGED_ROOT_DOCS,
    }
    prefixes = {
        p.rstrip("/")
        for p in (*mi.get_managed_public_prefixes(), *mi.get_local_runtime_prefixes(), *HARNESS_OWNED_ROOTS)
    }
    if is_harness_output(rel):
        return True
    if any(f == rel or f.startswith(rel + "/") for f in files):
        return True
    return any(rel == p or rel.startswith(p + "/") for p in prefixes)


class TestBareExistenceCensus:
    """Every ``(repo_root / X).exists()`` / ``.is_dir()`` / ``.is_file()`` in
    analyze.py, derived by AST walk (never a hand list of detector names), is
    checked against the deployed-path oracle derived from the inventory: a
    probe on a path the harness deploys is the leak shape DEF-410f names, and
    stays only as a rostered count and reason."""

    @staticmethod
    def _probes() -> list[tuple[str, str]]:
        return _bare_existence_probes(ANALYZE_PATH.read_text(encoding="utf-8"))

    def test_the_census_resolves_every_shape_in_the_module(self):
        probes = self._probes()
        assert not [p for p in probes if p[1] == "<unresolved>"], probes
        # one of each shape the resolver claims to read, on the live module
        assert ("detect_tests", "pytest.ini") in probes          # inline chain
        assert ("detect_architecture", "tools/cc") in probes     # two-segment chain
        assert ("detect_docs_surface", "docs") in probes         # local alias
        assert ("detect_runtime_surface", "main.py") in probes   # comprehension over a module constant
        assert ("detect_ui_surface", "pages") in probes          # alias bound inside a for over a tuple

    def test_every_probe_on_a_harness_path_is_rostered_with_its_count(self):
        touched = Counter(probe for probe in self._probes() if _harness_touched(probe[1]))
        assert dict(touched) == {key: count for key, (count, _reason) in _EXISTENCE_EXEMPT.items()}

    def test_every_exemption_names_a_live_function_and_gives_a_reason(self):
        """The reference roster's fifth guard (``tests/test_atomic_io.py``):
        a renamed detector already reds through the set equality above, but
        an entry added with an empty reason would ship silently."""
        names = {
            node.name for node in ast.walk(ast.parse(ANALYZE_PATH.read_text(encoding="utf-8")))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for (func, path), (count, reason) in _EXISTENCE_EXEMPT.items():
            assert func in names, f"exempt function {func!r} no longer exists"
            assert count >= 1, (func, path)
            assert reason.strip(), (func, path)

    def test_a_fabricated_probe_reds(self):
        """Earn the red: the census sees a probe on a harness path in each
        shape it resolves, names the ones it cannot, and the oracle keeps an
        adopter path clean."""
        cases = {
            'def detect_x(repo_root):\n    return (repo_root / "reports").exists()\n':
                ("detect_x", "reports"),
            'def detect_y(repo_root):\n    goal = repo_root / "cc" / "GOAL.md"\n    return goal.is_file()\n':
                ("detect_y", "cc/GOAL.md"),
            'def detect_z(repo_root):\n    return any((repo_root / n).exists() for n in ("x", "tools/cc"))\n':
                ("detect_z", "tools/cc"),
            'NAMES = ("a", ".claude")\n\ndef detect_v(repo_root):\n    return [n for n in NAMES if (repo_root / n).is_dir()]\n':
                ("detect_v", ".claude"),
            'def detect_j(repo_root):\n    return repo_root.joinpath("cc", "blueprints").is_dir()\n':
                ("detect_j", "cc/blueprints"),
            'def detect_p(repo_root):\n    return Path(repo_root, ".espalier-state").exists()\n':
                ("detect_p", ".espalier-state"),
            'def detect_o(repo_root):\n    return os.path.isdir(repo_root / "reports")\n':
                ("detect_o", "reports"),
            'def detect_k(repo_root, *, flag=False):\n    return (repo_root / ".claude").exists()\n':
                ("detect_k", ".claude"),
            # the loud arm: a receiver that mentions the root and does not resolve
            'def detect_w(repo_root, names):\n    return any((repo_root / n).exists() for n in names)\n':
                ("detect_w", _UNRESOLVED),
            'def detect_u(repo_root):\n    return repo_root.parent.joinpath("x").exists()\n':
                ("detect_u", _UNRESOLVED),
            'def detect_f(repo_root, stem):\n    return (repo_root / f"{stem}.md").exists()\n':
                ("detect_f", _UNRESOLVED),
        }
        for source, probe in cases.items():
            probes = _bare_existence_probes(source)
            assert probe in probes, (source, probes)
            if probe[1] != _UNRESOLVED:
                assert _harness_touched(probe[1]), probe
        # the quiet arm: a receiver that never mentions the root is an enumeration
        quiet = 'def detect_q(repo_root):\n    return [c for c in repo_root.iterdir() if (c / "__init__.py").exists()]\n'
        assert _bare_existence_probes(quiet) == []
        for rel in ("pytest.ini", "tests", "src/main.rs", "README.md", "Makefile", "espalier"):
            assert not _harness_touched(rel), rel

    def test_every_probing_function_names_its_root_repo_root(self):
        """The census keys on a parameter named ``repo_root``; a detector that
        took ``root`` (annotated or not, first or keyword-only, nested or a
        method) would probe outside its sight. So every function in the
        module that probes existence at all must have a parameter named
        ``repo_root``; the helpers that take a file path (``_rel``,
        ``_safe_text``, ``_parse_make_targets``, ``_path_allowed``) probe
        nothing and need no roster."""
        tree = ast.parse(ANALYZE_PATH.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _probes_existence(node):
                continue
            names = {arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)}
            if "repo_root" not in names:
                offenders.append((node.name, sorted(names)))
        assert not offenders, (
            f"these functions probe existence with no parameter named repo_root, so "
            f"TestBareExistenceCensus cannot read them -- name the root repo_root: {offenders}"
        )
        # earn the red on the guard itself
        shapes = (
            "def detect_r(root: Path):\n    return (root / '.claude').exists()\n",
            "def detect_s(root):\n    return (root / '.claude').exists()\n",
            "def detect_t(cfg, *, root: Path):\n    return os.path.exists(root / 'cc')\n",
            "class D:\n    def probe(self, root):\n        return (root / 'cc').is_dir()\n",
        )
        for shape in shapes:
            func = next(n for n in ast.walk(ast.parse(shape)) if isinstance(n, ast.FunctionDef))
            assert _probes_existence(func) and "repo_root" not in {a.arg for a in func.args.args}, shape
