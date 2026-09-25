"""Contract test for Espalier-Harness's test suite shape and marker discipline.

Locks in the marker taxonomy declared in pyproject.toml + assigned in
tests/conftest.py. Catches drift if a contributor adds a new test file
that doesn't match any pattern (would default to `unit`, possibly
incorrectly), or if a doc edit reintroduces a hard-coded exact test count.

See `tests/README.md` for operator-facing guidance.
"""
from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests._surface_expected import CONTRACT_CEILINGS, PLUGIN_OWNED_MARKERS


REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"
PYPROJECT = REPO_ROOT / "pyproject.toml"

KNOWN_MARKERS = {
    "unit", "integration", "contract", "security", "release",
    # Additive overlays. `full_tree` was missing here until 2026-08-24, so
    # test_pyproject_declares_strict_markers would not have noticed it being
    # dropped from pyproject -- the same reads-as-enforcement gap the two
    # `unit` contracts below close, one level up.
    "slow", "heavy_e2e", "full_tree",
}


def test_pyproject_declares_strict_markers():
    """pyproject.toml must declare --strict-markers and every known marker."""
    text = PYPROJECT.read_text(encoding="utf-8")
    assert "--strict-markers" in text, (
        "pyproject.toml must enable --strict-markers so unknown markers fail loudly"
    )
    for marker in KNOWN_MARKERS:
        assert f'"{marker}:' in text, (
            f"marker {marker!r} not declared in pyproject.toml [tool.pytest.ini_options].markers"
        )


def test_pyproject_declares_xfail_strict():
    """pyproject.toml must set ``xfail_strict = true``.

    Without it, an ``@pytest.mark.xfail`` that starts PASSING reports as
    XPASS and the suite stays green — so a gate can be silently repaired,
    or silently neutered, and nothing says so. There are zero real xfail
    decorators today, which is precisely why pinning it is cheap now: the
    first one added inherits the strict behaviour rather than the lenient
    one, and no existing test changes meaning.

    Sibling of the ``--strict-markers`` assertion above and of
    ``tests/test_ruff_config_includes_security_rules.py``'s REQUIRED_RULES —
    same shape, same reason: pin the config value so a future edit dropping
    it is loud at unit-test time instead of silently rolling the gate back.
    The ``test_loosening`` scanner does not cover this: it flags an ``xfail``
    with no reason, not a non-strict ``xfail`` *with* one.
    """
    text = PYPROJECT.read_text(encoding="utf-8")
    assert re.search(r"^\s*xfail_strict\s*=\s*true\s*$", text, re.MULTILINE), (
        "pyproject.toml [tool.pytest.ini_options] must set `xfail_strict = true` so an "
        "xfail that starts passing fails the suite instead of reporting a green XPASS"
    )


def test_no_hard_coded_exact_test_count_in_docs():
    """Operator docs must not pin an exact test count.

    Exact counts drift on every parametrize edit, which makes the docs
    a maintenance burden and a misleading signal for reviewers. The
    marker taxonomy + this contract test are the canonical proof shape.
    """
    forbidden = re.compile(r"Total test count:\s*\d", re.IGNORECASE)
    for doc in (REPO_ROOT / "README.md", REPO_ROOT / "CONTRIBUTING.md"):
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8")
        match = forbidden.search(text)
        assert match is None, (
            f"{doc.name} hard-codes an exact test count "
            f"({match.group(0)!r}); use marker-based guidance instead "
            "(see tests/README.md)."
        )


def test_tests_readme_exists():
    """tests/README.md is the canonical operator doc for the marker taxonomy."""
    assert (TESTS_DIR / "README.md").exists(), (
        "tests/README.md missing — operators have nowhere to look up "
        "the marker taxonomy or how to run release-confidence slices."
    )


def test_suite_size_lower_bound():
    """Reasonable lower bound — guards against accidental mass-deletion.

    Bound raised from 40 to 80 in TP-RELEASE-26. The prior bound and the
    error message were calibrated for a much smaller suite — live count
    was already 91+ when this fix landed, so the historical guard was
    advisory rather than effective. 80 absorbs a few intentional
    consolidations (5-10 files merging) without false alarms but catches
    actual mass deletion.
    """
    test_files = list(TESTS_DIR.glob("test_*.py"))
    assert len(test_files) >= 80, (
        f"Only {len(test_files)} test files. The suite had 92+ files "
        f"in 0.5.0. If you intentionally consolidated below 80, update "
        f"this bound in the same commit so the signal stays calibrated."
    )


def test_live_tree_guard_sees_an_add_and_a_remove_that_cancel_in_count(tmp_path):
    """The fingerprint is a SET per directory. The count form passed a test
    that added one entry while another went away -- under xdist a sibling
    worker can be the remover -- which is a false green in the guard the
    parallel full run leans on. Pins the set form and the self-diagnosing
    message that names what came and went."""
    import tests.conftest as _conftest

    d = tmp_path / "reports"; d.mkdir()
    (d / "old.txt").write_text("x", encoding="utf-8")
    before = _conftest._live_tree_fingerprint(tmp_path, ("reports",))
    (d / "old.txt").unlink()
    (d / "new.txt").write_text("x", encoding="utf-8")
    after = _conftest._live_tree_fingerprint(tmp_path, ("reports",))
    assert len(before["reports"]) == len(after["reports"]) == 1
    moves = _conftest._live_tree_moves(before, after)
    assert moves == ["reports (added: ['new.txt']; removed: ['old.txt'])"]


def test_live_tree_watch_is_not_whittled_to_nothing():
    """``conftest._LIVE_TREE_WATCH`` must keep watching something.

    The autouse ``_no_live_tree_writes`` fixture compares the entry set per
    watched directory before and after every test. Its sibling set
    ``_LIVE_TREE_ALLOWED`` carries a written rule -- "a deliberate, reviewed
    exception with a stated reason, never a way to silence a red" -- and the
    fixture's own failure message offers exactly two remedies: redirect the
    writer to ``tmp_path``, or allowlist it.

    There is a cheaper third move the file does not mention: delete the entry
    from ``_LIVE_TREE_WATCH``. That silences the red with no ledger, no stated
    reason, and no test noticing -- and at ``()`` the fixture becomes a no-op
    across the entire suite while every assertion in it still "passes". This
    contract is the missing counterweight, added after a 2026-08-05 review
    observed the watch list being narrowed 4 -> 2 precisely that way.

    Deliberately a floor, not an exact pin: the membership is a calibration
    judgement (both current entries are gitignored build/output dirs), and
    pinning the exact set would red on every legitimate recalibration. What
    must never happen silently is the set emptying.
    """
    import tests.conftest as _conftest

    assert len(_conftest._LIVE_TREE_WATCH) >= 2, (
        f"_LIVE_TREE_WATCH is down to {list(_conftest._LIVE_TREE_WATCH)}. "
        "Removing a directory to clear a red is the un-ledgered path around "
        "_LIVE_TREE_ALLOWED. If churn in a watched dir is genuinely not "
        "attributable to the test that straddles it, say so in the comment "
        "and allowlist the writer -- do not shrink the field of view. If you "
        "are deliberately recalibrating below 2, lower this floor in the same "
        "commit with the reason."
    )


def test_scripts_dir_matches_pinned_inventory():
    """scripts/ names must match _surface_expected.EXPECTED_SCRIPT_NAMES.

    Adding/removing a script means editing the roster in
    tests/_surface_expected.py in the same commit (the count beside it is
    derived from the roster, never bumped by hand). The pin makes silent
    additions (e.g., a contributor drops a one-off helper script) visible
    at test time rather than at release time.
    """
    from _surface_expected import EXPECTED_SCRIPT_NAMES
    scripts_dir = REPO_ROOT / "scripts"
    live_names = frozenset(
        p.name for p in scripts_dir.glob("*.py")
        if not p.name.startswith("__")
    )
    assert live_names == EXPECTED_SCRIPT_NAMES, (
        f"scripts/ name set drifted. "
        f"Live: {sorted(live_names)}; expected: {sorted(EXPECTED_SCRIPT_NAMES)}."
    )


def test_every_test_file_matches_a_marker_rule_or_defaults_to_unit():
    """Every test file under tests/ has a deterministic marker assignment.

    This is a static check: we read the pattern lists from conftest.py
    and assert each test_*.py file either matches a pattern or falls
    through to the unit default. The assertion form catches a contributor
    adding a new category without updating _MARKER_RULES (the file would
    silently get the unit marker, which is wrong for security/release tests).
    """
    # Read the rules THEMSELVES, not a text window around them. This was a
    # substring slice from "_MARKER_RULES" to the first later "_SLOW_FILES",
    # and the first later "_SLOW_FILES" is a COMMENT inside the security tuple
    # -- so the window closed at conftest.py:434 and extracted 179 of 328
    # patterns, seeing neither the integration, contract, nor unit tuples. A
    # new `test_release_*` or `test_artifact_*` file was therefore reported as
    # unregistered even when it was registered, and the 2026-08-24 `unit`
    # contract's remedy message ("move each stem into the integration tuple")
    # steered the operator straight into that false red. Importing costs
    # nothing here -- tests/test_marker_taxonomy.py has always done it.
    from tests.conftest import _MARKER_RULES

    pattern_strs = {p for patterns, _marker in _MARKER_RULES for p in patterns}
    assert pattern_strs, "no patterns extracted from _MARKER_RULES"

    test_files = sorted(TESTS_DIR.glob("test_*.py"))
    unmatched: list[str] = []
    for path in test_files:
        stem = path.stem
        if any(stem == p or stem.startswith(p + "_") for p in pattern_strs):
            continue
        # Falling through to the unit default is fine for pure unit tests.
        # We only flag files whose name suggests a non-unit category was missed.
        suspicious_prefixes = (
            "test_release_",
            "test_security_",
            "test_artifact_",
            "test_ci_",
            "test_kill_switch",
            "test_plan_guard",
            "test_write_guard",
            "test_hook_",
        )
        if any(stem.startswith(p) for p in suspicious_prefixes):
            unmatched.append(stem)
    assert not unmatched, (
        "Test files whose names suggest a non-unit category but are not "
        "registered in _MARKER_RULES (so they silently default to unit):\n"
        + "\n".join(f"  - {s}" for s in unmatched)
        + "\nAdd patterns to _MARKER_RULES in tests/conftest.py."
    )


# ── The dev extra: what the README promises, what pyproject declares, what
# the modules import ─────────────────────────────────────────────────────────


def _how_we_test_section(text: str) -> str:
    """README's ``## How we test`` section: from its heading to the next H2."""
    start = text.index("\n## How we test")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else None]


def test_readme_names_the_dev_extra_install_above_its_verification_line():
    """README's release-confidence line runs only after the dev extra is installed.

    The install line at the top of the README is the runtime-only
    ``pip install -e .``; its verification line
    ``python -m pytest -m "contract or release or security"`` needs ``pytest``
    and the plugins the dev extra brings. Measured 2026-09-22 on a 3.14 venv
    with the runtime install alone: collection refused six files
    (``'timeout' not found in markers``) and exited 2. CONTRIBUTING already
    carries the precondition; the README is the front door and must carry it
    too, ABOVE the line it qualifies, so a stranger reads the install before
    the command.
    """
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    section = _how_we_test_section(text)
    verify_at = section.find('-m "contract or release or security"')
    assert verify_at != -1, "README's How-we-test section lost its verification line"
    install_at = section.find("pip install -e '.[dev]'")
    assert install_at != -1, (
        "README's How-we-test section never names the dev-extra install "
        "(`python -m pip install -e '.[dev]'`) that its verification line needs"
    )
    assert install_at < verify_at, (
        "README names the dev-extra install AFTER the verification line it qualifies"
    )


def test_pyproject_declares_the_plugin_owned_markers_so_the_suite_collects_without_the_plugin():
    """A marker a plugin owns is ALSO declared in pyproject, so ``--strict-markers``
    accepts it on a runtime-only install.

    ``@pytest.mark.timeout(...)`` sits on six test files. ``pytest-timeout``
    registers the marker when it is loaded; without the plugin, ``--strict-markers``
    makes its absence a collection ERROR in every one of those files -- the
    measurement quoted above. Declaring it in pyproject is inert with the plugin
    present (pytest keeps both lines) and lets the suite collect and run without
    it. ``tests/test_marker_parity.py`` excludes the same set from the taxonomy
    comparison; ``tests/_surface_expected.py::PLUGIN_OWNED_MARKERS`` is the one
    home of the set.
    """
    text = PYPROJECT.read_text(encoding="utf-8")
    assert PLUGIN_OWNED_MARKERS, "PLUGIN_OWNED_MARKERS is the one home; emptying it voids this row"
    assert len(PLUGIN_OWNED_MARKERS) <= CONTRACT_CEILINGS["plugin-owned-markers"], (
        "a marker was added to PLUGIN_OWNED_MARKERS past its ceiling -- a taxonomy "
        "marker belongs in conftest, not here"
    )
    dev_dists = _dev_extra_distributions()
    for marker, dist in sorted(PLUGIN_OWNED_MARKERS.items()):
        assert dist in dev_dists, (
            f"PLUGIN_OWNED_MARKERS says {marker!r} is owned by {dist!r}, which is not a "
            f"declared dev extra ({sorted(dev_dists)}) -- only a plugin's marker may be excluded "
            "from the taxonomy parity"
        )
        assert re.search(rf'^\s*"{re.escape(marker)}\(', text, re.MULTILINE), (
            f"plugin-owned marker {marker!r} is not declared in pyproject.toml "
            "[tool.pytest.ini_options].markers; without its plugin, --strict-markers "
            "errors at collection in every file that uses it"
        )


# Distribution name -> import name, the FALLBACK for a dev extra that is not
# installed (a runtime-only install cannot ask its metadata). When the
# distribution IS installed, the names come from importlib.metadata, so this
# table is only consulted where it cannot be checked -- and the row below
# asserts it agrees with the metadata wherever both are available.
_DIST_TO_IMPORT = {"pyyaml": "yaml"}


def _dev_extra_distributions() -> frozenset[str]:
    """The distribution names of ``[project.optional-dependencies].dev``, lower-cased."""
    from espalier._compat import tomllib

    assert tomllib is not None, "neither tomllib nor tomli; the contract cannot read pyproject"
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dists: set[str] = set()
    for spec in data["project"]["optional-dependencies"]["dev"]:
        m = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", spec.strip())
        assert m, f"unreadable dev-extra spec {spec!r}"
        dists.add(m.group(0).lower())
    return frozenset(dists)


def _installed_import_names(dist: str) -> frozenset[str] | None:
    """Top-level import names ``dist`` provides, from installed metadata; None when
    the distribution is not installed here."""
    from importlib import metadata

    try:
        provided = metadata.packages_distributions()
    except Exception:  # pragma: no cover - metadata unreadable on this host
        return None
    names = frozenset(pkg for pkg, dists in provided.items() if dist in {d.lower() for d in dists})
    return names or None


def _dev_extra_import_names() -> frozenset[str]:
    """The import names of ``[project.optional-dependencies].dev``, minus the runner.

    Derived, not listed: a dev extra added tomorrow is covered the day it lands
    -- from installed metadata when the distribution is present, else from the
    fallback map / the normalised distribution name. ``pytest`` and its plugins
    are excluded by construction -- the runner is imported by every test module
    by design, and a plugin contributes markers, not imports. ``tomli`` never
    enters: it is a conditional RUNTIME dependency under
    ``[project].dependencies``, not a dev extra, so no exempt list exists.
    """
    names: set[str] = set()
    for dist in _dev_extra_distributions():
        if dist == "pytest" or dist.startswith("pytest-"):
            continue
        names.update(_installed_import_names(dist) or {_DIST_TO_IMPORT.get(dist, dist.replace("-", "_"))})
    return frozenset(names)


def _guards_import_error(node: ast.Try) -> bool:
    for handler in node.handlers:
        t = handler.type
        if t is None:
            return True
        names = [t.id] if isinstance(t, ast.Name) else (
            [e.id for e in t.elts if isinstance(e, ast.Name)] if isinstance(t, ast.Tuple) else []
        )
        if "ImportError" in names or "ModuleNotFoundError" in names:
            return True
    return False


def _module_level_dev_extra_imports(text: str, names: frozenset[str]) -> list[tuple[int, str]]:
    """``(lineno, import_name)`` for every import of a dev extra that EXECUTES at
    module import time and is not guarded.

    Executes at import time: the module body and any ``if`` / ``with`` /
    ``for`` / ``while`` / ``match`` body under it -- not a function or class body.
    Guarded: inside a ``try`` whose handlers catch ``ImportError`` (or
    ``ModuleNotFoundError``, or a bare ``except``); a ``try`` that catches only
    something else guards nothing. (The first cut read only direct children of
    the module body, so an import under ``if sys.version_info >= ...`` passed --
    the 2026-09-22 code review drove it.) A ``SyntaxError`` reports empty; the
    module's own collection reports that.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    hits: list[tuple[int, str]] = []
    try_types: tuple[type, ...] = (ast.Try, getattr(ast, "TryStar", ast.Try))

    def visit(nodes: list[ast.stmt], guarded: bool) -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(node, ast.Import):
                if not guarded:
                    for alias in node.names:
                        root = alias.name.split(".", 1)[0]
                        if root in names:
                            hits.append((node.lineno, root))
            elif isinstance(node, ast.ImportFrom):
                if not guarded and node.module and node.level == 0:
                    root = node.module.split(".", 1)[0]
                    if root in names:
                        hits.append((node.lineno, root))
            elif isinstance(node, try_types):
                visit(node.body, guarded or _guards_import_error(node))
                for handler in node.handlers:
                    visit(handler.body, guarded)
                visit(node.orelse, guarded)
                visit(node.finalbody, guarded)
            elif isinstance(node, getattr(ast, "Match", ())):
                for case in node.cases:
                    visit(case.body, guarded)
            else:
                for field in ("body", "orelse"):
                    inner = getattr(node, field, None)
                    if isinstance(inner, list):
                        visit(inner, guarded)

    visit(tree.body, False)
    return hits


def test_no_test_module_imports_a_dev_extra_at_module_level():
    """A test module that imports a dev extra unguarded at module level makes a
    runtime-only install fail at COLLECTION -- the whole file, not one test --
    with no skip and no reason. The guarded forms are ``pytest.importorskip``
    and ``try`` / ``except ImportError``; ``tests/test_e2e_bench.py`` shows the
    first. The population is every ``tests/*.py``, helpers and conftest included.
    """
    names = _dev_extra_import_names()
    assert {"yaml", "packaging", "build"} <= names, names
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}: {name}"
        for path in sorted(TESTS_DIR.glob("*.py"))
        for lineno, name in _module_level_dev_extra_imports(
            path.read_text(encoding="utf-8"), names
        )
    ]
    assert not offenders, (
        "module-level imports of a dev extra (a runtime-only install cannot "
        "collect the file):\n  " + "\n  ".join(offenders)
        + "\nGuard it: `pytest.importorskip(...)` or `try: ... except ImportError`."
    )


class TestDevExtraImportDetector:
    """Earn the red: the checker names the line of a bare import and stays silent
    on every guarded form. Fed synthetic modules -- the live tree has no
    offender, so the live row above proves nothing about the checker by itself."""

    _NAMES = frozenset({"yaml", "packaging", "build"})

    def test_a_bare_import_is_named_with_its_line(self):
        assert _module_level_dev_extra_imports("import os\nimport yaml\n", self._NAMES) == [(2, "yaml")]

    def test_a_from_import_of_a_submodule_is_named_by_its_root(self):
        text = "from packaging.version import Version\n"
        assert _module_level_dev_extra_imports(text, self._NAMES) == [(1, "packaging")]

    def test_a_dotted_import_is_named_by_its_root(self):
        assert _module_level_dev_extra_imports("import build.util\n", self._NAMES) == [(1, "build")]

    def test_an_import_inside_try_except_importerror_is_not_reported(self):
        text = "try:\n    import yaml\nexcept ImportError:\n    yaml = None\n"
        assert _module_level_dev_extra_imports(text, self._NAMES) == []
        text = "try:\n    import yaml\nexcept (ImportError, OSError):\n    yaml = None\n"
        assert _module_level_dev_extra_imports(text, self._NAMES) == []
        text = "try:\n    import yaml\nexcept:\n    yaml = None\n"
        assert _module_level_dev_extra_imports(text, self._NAMES) == []

    def test_an_import_that_executes_under_a_module_level_branch_is_named(self):
        """Executes at import time as surely as a bare one (the review's three)."""
        text = "import sys\nif sys.version_info >= (3, 11):\n    import yaml\n"
        assert _module_level_dev_extra_imports(text, self._NAMES) == [(3, "yaml")]
        text = "import contextlib\nwith contextlib.suppress(None):\n    import yaml\n"
        assert _module_level_dev_extra_imports(text, self._NAMES) == [(3, "yaml")]
        text = "try:\n    import yaml\nexcept KeyError:\n    pass\n"
        assert _module_level_dev_extra_imports(text, self._NAMES) == [(2, "yaml")]
        text = "try:\n    if True:\n        import yaml\nexcept ImportError:\n    pass\n"
        assert _module_level_dev_extra_imports(text, self._NAMES) == []

    def test_importorskip_is_not_reported(self):
        text = "import pytest\nyaml = pytest.importorskip('yaml')\n"
        assert _module_level_dev_extra_imports(text, self._NAMES) == []

    def test_an_import_inside_a_function_is_not_reported(self):
        text = "def test_x():\n    import yaml\n    assert yaml\n"
        assert _module_level_dev_extra_imports(text, self._NAMES) == []

    def test_an_unrelated_import_is_not_reported(self):
        assert _module_level_dev_extra_imports("import pytest\nimport json\n", self._NAMES) == []

    def test_a_syntax_error_reports_empty_rather_than_raising(self):
        assert _module_level_dev_extra_imports("import (\n", self._NAMES) == []

    def test_the_fallback_map_agrees_with_installed_metadata(self):
        """Where a dev extra is installed, its import names come from metadata; the
        fallback map must agree with it, and every installed dev extra whose
        import name differs from its normalised distribution name must be in the
        map, or a runtime-only host would check for a name nobody imports."""
        dists = [d for d in _dev_extra_distributions() if not (d == "pytest" or d.startswith("pytest-"))]
        installed = {d: _installed_import_names(d) for d in dists}
        if not any(installed.values()):
            pytest.skip("no dev extra is installed here; the fallback map cannot be checked")
        for dist, names in installed.items():
            if names is None:
                continue
            fallback = _DIST_TO_IMPORT.get(dist, dist.replace("-", "_"))
            assert fallback in names, (
                f"{dist!r} provides {sorted(names)} but the fallback would look for {fallback!r}; "
                "add it to _DIST_TO_IMPORT"
            )

    def test_the_runner_its_plugins_and_tomli_are_excluded_by_construction(self):
        names = _dev_extra_import_names()
        assert not any(n == "pytest" or n.startswith("pytest") for n in names), names
        assert "tomli" not in names, "tomli is a conditional runtime dep, never a dev extra"


_SLOW_EXEMPT_MARKER = "# slow-exempt:"

# A SEPARATE hatch for the self-declared-heavy contract below, deliberately not
# `# slow-exempt:`. Reusing that one looked economical -- both remedies end at
# `_SLOW_FILES` -- and was wrong: the two markers answer different questions.
# `# slow-exempt:` says "this module spawns a child, but the child is cheap";
# it does NOT say "the raised timeout is headroom rather than cost", and 19
# modules carry it today for the first reason alone. Sharing the marker would
# have pre-forgiven all 19 for a question none of them was asked, including
# tests/test_front_door_numbers.py, whose reason literally reads "no
# subprocess" -- an answer to the other check entirely. Zero live sites need
# this one, which is exactly when a hatch is cheapest to separate.
_TIMEOUT_EXEMPT_MARKER = "# timeout-exempt:"

# Direct child-spawn call shapes the AST walker recognizes.
_SUBPROCESS_ATTRS = frozenset({
    "run", "Popen", "call", "check_call", "check_output",
    "getoutput", "getstatusoutput",
})
_OS_SPAWN_ATTRS = frozenset({"system", "popen"})
# Helpers that themselves spawn a child process: importing one is an
# indirect spawn the call-graph-blind AST walk would otherwise miss.
# (test_benchmark_pass_conditions imports invoke_real_write_guard, which
# chains through _invoke_hook_stdin -> subprocess.run.)
_SPAWNING_HELPERS = frozenset({"invoke_real_write_guard", "_invoke_hook_stdin"})


def _module_spawns_child(text: str) -> bool:
    """True if the module makes a direct subprocess.*/os.system/os.popen call
    OR imports a known child-spawning helper. AST-based so docstrings and
    type-hints mentioning 'subprocess' do not false-positive, and os.system /
    helper-indirected spawns are not false-negatives."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if func.value.id == "subprocess" and func.attr in _SUBPROCESS_ATTRS:
                    return True
                if func.value.id == "os" and func.attr in _OS_SPAWN_ATTRS:
                    return True
        elif isinstance(node, ast.ImportFrom):
            if any(alias.name in _SPAWNING_HELPERS for alias in node.names):
                return True
    return False


def test_every_subprocess_test_is_slow_or_exempt():
    """TP-189-B PERF-2 / TP-223 C: every test module that spawns a child
    process must be in tests/conftest.py::_SLOW_FILES (or carry an explicit
    ``# slow-exempt: <reason>`` opt-out), so ``pytest -m "not slow"`` is a
    genuinely fast in-process smoke slice and a future child-process-spawning
    file cannot silently rejoin it.

    Detection is AST-based (TP-223): direct ``subprocess.*`` / ``os.system`` /
    ``os.popen`` calls plus a known-spawning-helper import allowlist. The prior
    substring needle (``"subprocess."``) both false-negatived docstring-only
    mentions (it missed test_benchmark_pass_conditions, whose only `subprocess`
    token is in a docstring, even though it really spawns via
    invoke_real_write_guard) and false-positived type-hint/string mentions.
    Structural contract — asserts NO wall-clock number."""
    from tests.conftest import _SLOW_FILES

    offenders: list[str] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        if not _module_spawns_child(text):
            continue
        if _SLOW_EXEMPT_MARKER in text:
            continue
        if path.stem not in _SLOW_FILES:
            offenders.append(path.stem)
    assert not offenders, (
        "These test modules spawn a child process but are not in "
        "tests/conftest.py::_SLOW_FILES (and carry no `# slow-exempt: <reason>` "
        f"opt-out), so they drag the `not slow` fast slice: {offenders}. "
        "Add each stem to _SLOW_FILES, or add a slow-exempt comment with a reason."
    )


# ---------------------------------------------------------------------------
# The `unit` marker's DECLARED contract, enforced.
#
# pyproject.toml declares `unit: pure function/model tests; no subprocess, no
# filesystem-heavy work`, and tests/README.md calls the slice "fast, hermetic".
# Until this block existed nothing verified either clause. conftest assigns
# `unit` in the fall-through, and `# pytest-marker: default-unit` opts a file
# into the bucket whatever that file does -- so the guard above it secured
# DELIBERATENESS and not ACCURACY.
#
# Measured 2026-08-24 on the dev tree: a third of the `unit` bucket spawned
# child processes, and `-m unit` was slower PER TEST than the whole suite. The
# consequence is not tidiness. The honest gate is the full suite at ~14
# minutes, a gate with no credible cheap precursor is one sessions route
# around, and this repo has already shipped broken contracts out of a session
# that ran with the Stop gate on `light`.
#
# TWO CLAUSES, TWO STRUCTURAL DETECTORS, AND DELIBERATELY NO WALL-CLOCK NUMBER
# IN EITHER. A per-test duration cap was the recorded proposal; it is not what
# landed. Wall-clock budgets have two false-fail incidents on record here --
# tests/README.md ("they false-fail on scheduler wait, not on a real
# regression") and tests/test_derived_population_census.py's own timeout note,
# where a contract test redded on a CLEAN tree because a parallel-agent review
# round loaded the box. task-packs/Done/TP-189-B-honesty-and-ux-closeout.md
# states the rule outright: "Do not assert a wall-clock number." A gate that
# reds for load rather than for truth is one the reader learns to skip, and a
# skipped gate is worse than no gate -- it still reads as enforcement.
#
# So clause 1 ("no subprocess") is answered by the AST detector that already
# exists in this file, and clause 2 ("no filesystem-heavy work") is answered by
# asking the module what IT declared: a module that raises its own pytest
# timeout above the global ceiling has told us it is heavy, in its own source,
# with no measurement required.

_PYTEST_INI_SECTION = "[tool.pytest.ini_options]"


def _global_pytest_timeout() -> int:
    """pyproject.toml's `[tool.pytest.ini_options] timeout`, READ not copied.

    Derived rather than hard-coded so raising the global ceiling moves the
    contract with it instead of leaving a stale literal behind.
    """
    text = PYPROJECT.read_text(encoding="utf-8")
    start = text.find(_PYTEST_INI_SECTION)
    assert start >= 0, f"pyproject.toml has no {_PYTEST_INI_SECTION}"
    nxt = text.find("\n[tool", start + len(_PYTEST_INI_SECTION))
    section = text[start:] if nxt < 0 else text[start:nxt]
    match = re.search(r"^\s*timeout\s*=\s*(\d+)\s*$", section, re.MULTILINE)
    assert match, (
        f"pyproject.toml {_PYTEST_INI_SECTION} declares no `timeout` -- the "
        "self-declared-heavy contract below has no ceiling to compare against"
    )
    return int(match.group(1))


def _mark_name(node: ast.expr) -> str | None:
    """The marker name behind ``pytest.mark.<name>`` / ``mark.<name>``.

    Accepts the bare attribute (``pytest.mark.slow``) and the called form
    (``pytest.mark.timeout(300)``) alike; returns None for anything that is
    not a marker reference.
    """
    if isinstance(node, ast.Call):
        node = node.func
    if not isinstance(node, ast.Attribute):
        return None
    owner = node.value
    owner_is_mark = (
        (isinstance(owner, ast.Attribute) and owner.attr == "mark")
        or (isinstance(owner, ast.Name) and owner.id == "mark")
    )
    return node.attr if owner_is_mark else None


def _timeout_seconds(call: ast.expr) -> float | None:
    """The numeric argument of a ``mark.timeout(...)`` call, positional or
    ``seconds=``; None if it is absent or not a literal number."""
    if not isinstance(call, ast.Call):
        return None
    best: float | None = None
    for arg in list(call.args) + [k.value for k in call.keywords if k.arg == "seconds"]:
        if not isinstance(arg, ast.Constant):
            continue
        if isinstance(arg.value, bool) or not isinstance(arg.value, (int, float)):
            continue
        best = arg.value if best is None else max(best, arg.value)
    return best


def _scan_marks(exprs: list[ast.expr]) -> tuple[float | None, bool]:
    """(largest declared timeout, whether ``slow`` is among these marks)."""
    seconds: float | None = None
    slow = False
    for expr in exprs:
        name = _mark_name(expr)
        if name == "slow":
            slow = True
        elif name == "timeout":
            value = _timeout_seconds(expr)
            if value is not None:
                seconds = value if seconds is None else max(seconds, value)
    return seconds, slow


def _declared_timeout_sites(text: str) -> list[tuple[str, float, bool]]:
    """Every site declaring a pytest-timeout override, as
    ``(label, seconds, this site is already marked slow)``.

    BOTH granularities are in live use and the contract must honour both.
    Timeouts are declared module-wide via ``pytestmark = pytest.mark.timeout(N)``
    (tests/test_verify_pins.py) and per-test via ``@pytest.mark.timeout(N)``
    (tests/test_derived_population_census.py). Slowness is *also* declared two
    ways -- ``conftest._SLOW_FILES`` for a whole file, and an inline
    ``@pytest.mark.slow`` on a single test (four files do this today).

    Asking only the file-level question flags ``test_final_release_matrix``,
    whose one 900s test already carries ``@pytest.mark.slow`` inline. Moving
    that whole module into ``_SLOW_FILES`` to satisfy a file-granular contract
    would drop its cheap siblings out of the pull-request slice -- a coverage
    loss wearing a speed fix's clothes. So the unit here is the SITE.

    ``slow`` on a class or on module-level ``pytestmark`` is inherited by the
    sites nested inside it, which is how pytest itself resolves them.

    Stated limit: a timeout built from a variable (``@pytest.mark.timeout(BUDGET)``)
    is invisible -- only literal numbers are read. There are none today, and a
    stale literal is the failure this helper exists to prevent, not to create.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    sites: list[tuple[str, float, bool]] = []

    module_seconds: float | None = None
    module_slow = False
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(tgt, ast.Name) and tgt.id == "pytestmark"
                   for tgt in node.targets):
            continue
        value = node.value
        exprs = list(value.elts) if isinstance(value, (ast.List, ast.Tuple)) else [value]
        module_seconds, module_slow = _scan_marks(exprs)
    if module_seconds is not None:
        sites.append(("pytestmark", module_seconds, module_slow))

    def _visit(body: list[ast.stmt], prefix: str, inherited_slow: bool) -> None:
        for node in body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            seconds, slow = _scan_marks(node.decorator_list)
            slow = slow or inherited_slow
            label = f"{prefix}{node.name}"
            if seconds is not None:
                sites.append((label, seconds, slow))
            if isinstance(node, ast.ClassDef):
                _visit(node.body, f"{label}::", slow)

    _visit(tree.body, "", module_slow)
    return sites


def _live_test_modules() -> list[tuple[str, str]]:
    """(stem, source) for every collected test module, read once."""
    return [(p.stem, p.read_text(encoding="utf-8"))
            for p in sorted(TESTS_DIR.glob("test_*.py"))]


def _timeout_offenders(
    modules: list[tuple[str, str]], slow_files: set[str], ceiling: int
) -> tuple[list[str], list[str]]:
    """(sites declaring themselves heavy, those not covered by anything).

    Split out from the contract so the VERDICT path can be driven with
    synthetic input. The live tree is clean, so `assert not offenders` would
    otherwise never be observed non-empty -- a guard nobody has seen fire is a
    guard nobody knows still fires.
    """
    declaring: list[str] = []
    offenders: list[str] = []
    for stem, text in modules:
        module_is_slow = stem in slow_files
        exempt = _TIMEOUT_EXEMPT_MARKER in text
        for label, seconds, site_is_slow in _declared_timeout_sites(text):
            if seconds <= ceiling:
                continue
            declaring.append(f"{stem}::{label}")
            if site_is_slow or module_is_slow or exempt:
                continue
            offenders.append(f"{stem}::{label} (declares {seconds:g}s vs global {ceiling}s)")
    return declaring, offenders


def _unit_spawn_offenders(
    modules: list[tuple[str, str]], primary
) -> tuple[list[str], list[str]]:
    """(modules resolving to `unit`, those among them that spawn a child)."""
    unit_modules: list[str] = []
    offenders: list[str] = []
    for stem, text in modules:
        if primary(stem) != "unit":
            continue
        unit_modules.append(stem)
        if _module_spawns_child(text):
            offenders.append(stem)
    return unit_modules, offenders


def test_every_self_declared_slow_site_is_slow_or_exempt():
    """A site that raises its own pytest timeout above the global ceiling must
    already be marked ``slow`` -- inline, or by its module's membership in
    ``tests/conftest.py::_SLOW_FILES`` -- or carry a ``# timeout-exempt: <reason>``
    opt-out.

    The clause-2 half of the `unit` contract, and the one that catches
    in-process heaviness the subprocess detector above is structurally blind
    to. ``tests/test_derived_population_census.py`` spawns nothing -- it
    ``exec_module``s the census script and walks the tree in-process -- so its
    cost was invisible to every existing gate while it sat in the slice CI
    runs on every pull request, measured at roughly a quarter of that slice.

    Asserts NO wall-clock number. It reads the ceiling from pyproject and the
    override from the module's own source: the author already wrote down that
    this site needs more than the global budget, and that written declaration
    is the evidence. Nothing here is timed, so nothing here can red for load.
    """
    from tests.conftest import _SLOW_FILES

    ceiling = _global_pytest_timeout()
    modules = _live_test_modules()
    scanned = len(modules)
    declaring, offenders = _timeout_offenders(modules, set(_SLOW_FILES), ceiling)

    # Non-vacuity sentinels. If the glob or the detector regressed to nothing,
    # `offenders` would be empty and this contract would report a reassuring
    # green while policing an empty set -- the exact instrument failure this
    # repo logged four times in a single prior session.
    assert scanned >= 80, (
        f"only {scanned} test modules scanned -- the glob regressed and this "
        "contract is policing an empty set"
    )
    assert declaring, (
        "no site declares a pytest-timeout override above the global "
        f"{ceiling}s ceiling -- either every override was removed (then delete "
        "this contract) or _declared_timeout_sites regressed to empty"
    )
    assert not offenders, (
        "These sites declare a pytest timeout above pyproject's global ceiling "
        "-- they have said in their own source that they are heavy -- but are "
        "not marked `slow` at either granularity and carry no "
        f"`{_TIMEOUT_EXEMPT_MARKER} <reason>` opt-out, so they drag every fast "
        f"slice: {offenders}. Add the module's stem to "
        "tests/conftest.py::_SLOW_FILES, or mark the single site "
        "`@pytest.mark.slow` inline, or add a timeout-exempt comment saying why "
        "the raised timeout is headroom rather than cost."
    )


def test_no_unit_module_spawns_a_child_process():
    """Clause 1 of the `unit` contract: a module classified `unit` must not
    spawn a child process.

    ``pyproject.toml`` says `unit: pure function/model tests; no subprocess,
    no filesystem-heavy work`. A module that shells out is an integration test
    by this repo's own taxonomy -- `integration: subprocess, CLI, hook,
    filesystem, or rendered-surface integration tests` -- and belongs in that
    tuple.

    Note this is orthogonal to `slow`: the primary marker says what KIND of
    test a module holds, the additive `slow` overlay says what it COSTS. Five
    of the modules this contract moved carry a `# slow-exempt:` reason and are
    genuinely fast (a single `git ls-files`); they stay in the `not slow`
    slice after reclassification and lose no coverage.

    THERE IS DELIBERATELY NO OPT-OUT HATCH. Its two siblings above have one
    because both ask a question with a legitimate "looks bad, is fine" answer
    (a single `git ls-files` is a spawn but not a cost; a raised timeout can be
    headroom). This one does not: if the module really does spawn a child, the
    declared property is false, and the remedy -- classify it `integration` --
    is always available and always correct. An exemption here would reproduce
    `# pytest-marker: default-unit`, the reason-free comment that let this
    bucket fill in the first place.

    Resolution goes through ``conftest._primary_marker``, the same function the
    collection hook calls, so this contract cannot answer a question the live
    dispatch would answer differently.
    """
    from tests.conftest import _SLOW_FILES, _primary_marker

    modules = _live_test_modules()
    scanned = len(modules)
    unit_modules, offenders = _unit_spawn_offenders(modules, _primary_marker)

    # `-m unit` selects on the PRIMARY marker and does NOT filter `slow`, so a
    # `unit` module carrying the overlay runs in the slice tests/README.md
    # advertises as the cheap precursor. The intersection is empty today by
    # accident, not by contract; this pins it. The remedy the message above
    # gives -- "add the stem to _SLOW_FILES" -- is precisely how a future
    # session would re-create the disease, so the two have to be nailed shut
    # together.
    both = sorted(set(unit_modules) & set(_SLOW_FILES))
    assert not both, (
        "These modules are `unit` AND in _SLOW_FILES, so they still run under "
        f"`-m unit`, the slice documented as hermetic and fast: {both}. "
        "Reclassify them `integration` rather than only overlaying `slow`."
    )

    assert scanned >= 80, (
        f"only {scanned} test modules scanned -- the glob regressed and this "
        "contract is policing an empty set"
    )
    assert unit_modules, (
        "no module resolves to the `unit` marker -- either the taxonomy was "
        "restructured (then rewrite this contract) or _primary_marker "
        "regressed; a green here would be vacuous"
    )
    assert not offenders, (
        "These modules are classified `unit` but spawn a child process, which "
        "pyproject.toml's `unit` description ('no subprocess') says they "
        f"cannot: {offenders}. Move each stem into the `integration` tuple of "
        "tests/conftest.py::_MARKER_RULES -- append to the EXISTING tuple so "
        "the earlier security/release/contract rules keep winning, and mind "
        "that matching is prefix-open (`stem.startswith(p + '_')`), so a "
        "shorter stem can capture a longer sibling."
    )


class TestDeclaredTimeoutDetector:
    """Calibration pins for ``_declared_timeout_sites``.

    Four of a prior session's instruments broke by returning the flattering
    answer, and a detector reporting "nothing found" is indistinguishable from
    a clean tree. These pins prove the helper reports BOTH verdicts, on every
    spelling that appears in the live tree, before either contract above is
    allowed to lean on it.
    """

    def test_decorator_spelling_is_seen(self):
        assert _declared_timeout_sites(
            "import pytest\n\n@pytest.mark.timeout(300)\ndef test_x(): pass\n"
        ) == [("test_x", 300, False)]

    def test_module_level_pytestmark_spelling_is_seen(self):
        assert _declared_timeout_sites(
            "import pytest\n\npytestmark = pytest.mark.timeout(1800)\n"
        ) == [("pytestmark", 1800, False)]

    def test_bare_mark_alias_is_seen(self):
        assert _declared_timeout_sites(
            "from pytest import mark\n\n@mark.timeout(900)\ndef test_x(): pass\n"
        ) == [("test_x", 900, False)]

    def test_keyword_form_is_seen(self):
        assert _declared_timeout_sites(
            "import pytest\n\n@pytest.mark.timeout(seconds=120)\ndef test_x(): pass\n"
        ) == [("test_x", 120, False)]

    def test_an_inline_slow_on_the_same_site_is_recorded(self):
        # The false positive that made this detector site-granular:
        # tests/test_final_release_matrix.py:116-117.
        assert _declared_timeout_sites(
            "import pytest\n\n@pytest.mark.slow\n@pytest.mark.timeout(900)\n"
            "def test_x(): pass\n"
        ) == [("test_x", 900, True)]

    def test_slow_on_the_enclosing_class_is_inherited(self):
        assert _declared_timeout_sites(
            "import pytest\n\n@pytest.mark.slow\nclass TestX:\n"
            "    @pytest.mark.timeout(400)\n    def test_y(self): pass\n"
        ) == [("TestX::test_y", 400, True)]

    def test_slow_on_module_pytestmark_is_inherited(self):
        assert _declared_timeout_sites(
            "import pytest\n\npytestmark = pytest.mark.slow\n\n"
            "@pytest.mark.timeout(400)\ndef test_x(): pass\n"
        ) == [("test_x", 400, True)]

    def test_largest_override_on_one_site_wins(self):
        sites = _declared_timeout_sites(
            "import pytest\n\n@pytest.mark.timeout(90)\ndef test_a(): pass\n\n"
            "@pytest.mark.timeout(600)\ndef test_b(): pass\n"
        )
        assert sorted(sites) == [("test_a", 90, False), ("test_b", 600, False)]

    def test_a_module_with_no_override_reports_empty(self):
        assert _declared_timeout_sites(
            "import pytest\n\n@pytest.mark.parametrize('x', [1])\n"
            "def test_x(x): pass\n"
        ) == []

    def test_an_unrelated_timeout_call_is_not_a_marker(self):
        # `sock.settimeout(30)` and `conn.timeout(45)` are not marker
        # declarations; the `.mark.` chain is what makes one.
        assert _declared_timeout_sites(
            "import socket\n\ndef test_x():\n    socket.socket().settimeout(30)\n"
            "    conn.timeout(45)\n"
        ) == []

    def test_a_syntax_error_reports_empty_rather_than_raising(self):
        assert _declared_timeout_sites("def test_x(:\n") == []


_HEAVY = "import pytest\n\n@pytest.mark.timeout(300)\ndef test_x(): pass\n"


class TestTheUnitContractsCanReportAnOffender:
    """Must-trip twins for both verdict paths.

    The sentinels inside the two contracts (`scanned >= 80`, non-empty
    population) pin the DETECTOR's reach, not the VERDICT's. On a clean tree
    `assert not offenders` is never observed non-empty, so a refactor that
    widened the forgiveness triple -- or broke `_module_spawns_child` outright
    -- would leave every sentinel green forever. These drive the same functions
    with synthetic input and watch them ACCUSE.
    """

    def test_an_uncovered_heavy_site_is_reported(self):
        declaring, offenders = _timeout_offenders([("test_synth", _HEAVY)], set(), 60)
        assert declaring == ["test_synth::test_x"]
        assert len(offenders) == 1 and "test_synth::test_x" in offenders[0]

    def test_membership_in_slow_files_covers_it(self):
        _, offenders = _timeout_offenders([("test_synth", _HEAVY)], {"test_synth"}, 60)
        assert offenders == []

    def test_an_inline_slow_covers_it(self):
        text = "import pytest\n\n@pytest.mark.slow\n@pytest.mark.timeout(300)\ndef test_x(): pass\n"
        _, offenders = _timeout_offenders([("test_synth", text)], set(), 60)
        assert offenders == []

    def test_a_timeout_exempt_comment_covers_it(self):
        text = "# timeout-exempt: the raised bound is headroom for a slow CI host\n" + _HEAVY
        _, offenders = _timeout_offenders([("test_synth", text)], set(), 60)
        assert offenders == []

    def test_a_slow_exempt_comment_does_NOT_cover_it(self):
        """The cross-purpose leak, pinned shut.

        `# slow-exempt:` answers "does this module spawn an expensive child",
        which is not "is this raised timeout headroom". Nineteen live modules
        carry it for the first reason; sharing the marker would forgive all of
        them for a question none of them answered.
        """
        text = "# slow-exempt: the one subprocess call is a fast `git ls-files`\n" + _HEAVY
        _, offenders = _timeout_offenders([("test_synth", text)], set(), 60)
        assert len(offenders) == 1

    def test_a_site_at_or_below_the_ceiling_is_not_reported(self):
        text = "import pytest\n\n@pytest.mark.timeout(60)\ndef test_x(): pass\n"
        declaring, offenders = _timeout_offenders([("test_synth", text)], set(), 60)
        assert declaring == [] and offenders == []

    def test_a_spawning_unit_module_is_reported(self):
        text = "import subprocess\n\ndef test_x():\n    subprocess.run(['true'])\n"
        units, offenders = _unit_spawn_offenders([("test_synth", text)], lambda s: "unit")
        assert units == ["test_synth"] and offenders == ["test_synth"]

    def test_the_same_module_classified_integration_is_not_reported(self):
        text = "import subprocess\n\ndef test_x():\n    subprocess.run(['true'])\n"
        units, offenders = _unit_spawn_offenders(
            [("test_synth", text)], lambda s: "integration")
        assert units == [] and offenders == []


class TestSubprocessDetector:
    """Calibration pins for ``_module_spawns_child``.

    It had none. It was already load-bearing for
    ``test_every_subprocess_test_is_slow_or_exempt``, and 2026-08-24 made it
    load-bearing for a second contract that has NO opt-out hatch -- so a silent
    regression to "sees nothing" would now quietly unclassify the whole `unit`
    bucket rather than merely relax one slice.
    """

    def test_a_direct_subprocess_run_is_seen(self):
        assert _module_spawns_child(
            "import subprocess\ndef test_x(): subprocess.run(['true'])\n")

    def test_os_system_is_seen(self):
        assert _module_spawns_child("import os\ndef test_x(): os.system('true')\n")

    def test_a_spawning_helper_import_is_seen(self):
        assert _module_spawns_child(
            "from tests.helpers import invoke_real_write_guard\ndef test_x(): pass\n")

    def test_a_docstring_mention_is_not_seen(self):
        # Mention, not use -- the reason this detector is AST-based and not a
        # substring needle. The substring form missed a module that really did
        # spawn while flagging one that only talked about it.
        assert not _module_spawns_child(
            '"""This test does not call subprocess.run anywhere."""\ndef test_x(): pass\n')

    def test_a_pure_module_is_not_seen(self):
        assert not _module_spawns_child("def test_x(): assert 1 + 1 == 2\n")

    def test_a_bare_aliased_import_is_a_DOCUMENTED_blind_spot(self):
        """Pinned as a LIMIT, not as coverage.

        ``from subprocess import run`` produces a bare ``run(...)`` call with no
        attribute chain, and this detector cannot see it. Recorded here so the
        gap is legible instead of being mistaken for a clean bill of health --
        the same reason the fixture-mediated spawn hole is worth naming: a
        module reaching a child through ``tests/_git_oracle.py`` or the
        ``adopter_tree`` fixture is invisible to this walk too, and
        ``tests/test_adopter_pointer_resolution.py`` is a live instance in the
        `not slow` slice today. If this assertion ever fails, the detector got
        BETTER -- delete the pin and say so.
        """
        assert not _module_spawns_child(
            "from subprocess import run\ndef test_x(): run(['true'])\n")


# ---------------------------------------------------------------------------
# TP-283 — every full-dev-tree-only test must carry the `full_tree` marker.
#
# The analog of test_every_subprocess_test_is_slow_or_exempt for the
# "context-blind verification over-reach" class TP-281/282 addressed: a test
# that reads content pruned from a release export (a `git archive` /
# Download-ZIP) will FileNotFoundError or mis-assert when the suite runs against
# an extracted archive. TP-282 marked today's instances by hand via
# tests/conftest.py::_FULL_TREE_NODEIDS; this contract reds the *next* un-marked
# one at authoring time instead of years later in a release gate.
#
# Like the subprocess-slow model — which imports _SLOW_FILES rather than scanning
# source for a "slow" marker — this reads _FULL_TREE_NODEIDS from conftest: the
# `full_tree` marker is applied at COLLECTION time (by nodeid substring), so it
# is never written in any test file's source. Detection is file-granular,
# matching the model's file-stem shape; see TP-283's documented mixed-granularity
# gap for the accepted tradeoff.
# ---------------------------------------------------------------------------

_FULL_TREE_EXEMPT_MARKER = "# full-tree-exempt:"

# ---------------------------------------------------------------------------
# §C21 — raw git POPULATION calls that do not route through tests/_git_oracle.py
#
# WHY THIS EXISTS AS CODE AND NOT AS A NOTE. §C21 ("absence conflated with
# emptiness on a git ls-files result") was closed on 2026-08-10 with the words
# "apply it from one helper so a third caller cannot re-introduce the
# distinction". The helper was never built; the rule stayed in the ledger; five
# more sites re-introduced it and the class reopened on 2026-08-14. The helper
# now exists -- and the routing rule was STILL only prose, with 23 sites
# unrouted. A rule whose only home is a tracker is a rule that gets re-learned.
#
# This is a RATCHET, not a ban. Every count below is a site asking git for a
# population WITHOUT the ownership check, so each is a place where a foreign or
# empty answer can read as this tree's. Many are fine today (tmp_path fixtures,
# or callers with their own fail-closed skip); what must not happen is the
# number going UP silently. Lower an entry when you route one; delete the key
# when it reaches zero.
#
# Seeded 2026-08-14 by AST census. tests/_git_oracle.py (the helper) and
# tests/test_git_oracle.py (which pins raw git behaviour deliberately, as
# facts about the platform) are excluded by construction.
_RAW_GIT_POPULATION_SITES: dict[str, int] = {
    "test_adopter_verb_stand_down.py": 1,
    # 2026-09-21: one `check-ignore --no-index` over a derived probe list. The
    # oracle's `require_is_gitignored` answers about the index first, so it
    # cannot ask what the RULES say about a tracked ship-set member, which is
    # the parity that test pins; the worktree guard is applied by hand there.
    "test_surface_contract.py": 1,
    "test_catalog_self_consistency.py": 2,
    "test_contracts.py": 2,
    "test_doc_regions.py": 1,
    "test_doc_source_citations.py": 1,
    "test_doc_test_citations.py": 1,
    "test_documented_claims.py": 1,
    "test_folder_claude_md_routers.py": 2,
    "test_git_archive_parity.py": 2,
    "test_init_gitignore_default.py": 1,
    "test_ladder_claudemd_pointers.py": 1,
    "test_md_heading_anchors.py": 1,
    "test_record_axis_reconciliation.py": 4,
    "test_reinject_sync.py": 2,
    "test_sister_site_probe_scope.py": 1,
}

_GIT_POPULATION_VERBS = frozenset({"ls-files", "ls-tree", "check-ignore"})


def _raw_git_population_census() -> dict[str, int]:
    """Per-module count of `subprocess.*(["git", ..., <population verb>, ...])`.

    AST, not a regex: the verb can sit at any argv position (`git -C <path>
    ls-files` vs `git ls-files`), and a docstring mentioning `ls-files` must not
    count. Only a list literal whose first element ends in `git` is considered,
    so a variable-built argv is invisible here -- an accepted limit, recorded
    rather than papered over.
    """
    census: dict[str, int] = {}
    for path in sorted(TESTS_DIR.glob("*.py")):
        if path.name in ("_git_oracle.py", "test_git_oracle.py"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a syntax error reds elsewhere
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name not in ("run", "check_output", "Popen"):
                continue
            if not node.args or not isinstance(node.args[0], ast.List):
                continue
            literals = [
                e.value for e in node.args[0].elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
            if literals and literals[0].endswith("git") and (
                set(literals) & _GIT_POPULATION_VERBS
            ):
                census[path.name] = census.get(path.name, 0) + 1
    return census


def test_raw_git_population_sites_only_shrink():
    """The §C21 routing rule, as a mechanism instead of a sentence."""
    census = _raw_git_population_census()
    assert census, (
        "the AST census found ZERO raw git population calls, which cannot be "
        "right while _RAW_GIT_POPULATION_SITES is non-empty -- the matcher "
        "broke and this contract would pass having checked nothing."
    )
    grew = {
        mod: (count, _RAW_GIT_POPULATION_SITES.get(mod, 0))
        for mod, count in census.items()
        if count > _RAW_GIT_POPULATION_SITES.get(mod, 0)
    }
    assert not grew, (
        f"new raw git population call(s), module -> (found, allowed): {grew}. "
        "Route it through tests/_git_oracle.py (require_tracked_paths / "
        "require_head_tree_paths / require_is_gitignored) so an unanswerable "
        "query cannot read as an answer. If the call genuinely must be raw -- "
        "it drives a tmp_path fixture, or it pins git's own behaviour -- raise "
        "that module's entry deliberately and say why in a comment beside it."
    )
    shrank = {
        mod: (census.get(mod, 0), allowed)
        for mod, allowed in _RAW_GIT_POPULATION_SITES.items()
        if census.get(mod, 0) < allowed
    }
    assert not shrank, (
        f"raw git call(s) removed, module -> (found, allowed): {shrank}. Good "
        "-- now lower the entry (or delete the key at zero) so the ratchet "
        "cannot silently absorb a NEW one in the space you just freed."
    )

# `Path.exists()`, `is_file()`, `is_dir()` and `is_symlink()` share ONE
# `_ignore_error` table that admits ENOENT/ENOTDIR/EBADF/ELOOP and does NOT admit
# EACCES -- and CPython MOVED that boundary: 3.14 rewrote all four over
# `os.path.*` (which swallows every OSError) while 3.10--3.13 re-raise. Inside a
# permission-denial block that makes any of them a coin-flip on the interpreter.
#
# `is_symlink` belongs here and its earlier exclusion was wrong on both clauses:
# it shares the identical table (so it is no safer), and it WAS the observed
# failure -- `_integrity._manifest_is_symlinked` is the frame the first cut of
# this fix moved the CI exception into. "Correct probe for asking about symlinks"
# and "EACCES-safe" are orthogonal questions; the carve-out belongs on the call
# site, via the waiver marker below, never on the method name.
_EACCES_UNSAFE_PROBES = frozenset({"exists", "is_file", "is_dir", "is_symlink"})

# Third verdict, so the gate has somewhere to put correct code instead of reding
# on it (§C19: a gate that fires on correct code gets switched off). Same idiom
# as `# slow-exempt:` and `# full-tree-exempt:` above. Legitimate use: a probe
# that runs BEFORE the chmod or AFTER the restoring chmod, or one on a path
# outside the denied subtree.
_EACCES_PROBE_WAIVER = "# eacces-probe-ok:"


def _is_os_path_call(func: ast.Attribute) -> bool:
    """True for `os.path.exists(...)` -- safe on every version, never flagged.

    Reachable only for the KEYWORD form `os.path.exists(path=x)`: the positional
    form carries an argument, so `not node.args` in the caller already excludes
    it, and the live corpus (`test_scanner_read_robustness.py::_make_unreadable`)
    is positional.
    Kept because the caller's arg-count filter is an accident of the bound
    methods taking none -- widening it later to catch the unbound `Path.exists(p)`
    form would otherwise silently start flagging `os.path` too.
    """
    value = func.value
    return (
        isinstance(value, ast.Attribute)
        and value.attr == "path"
        and isinstance(value.value, ast.Name)
        and value.value.id == "os"
    )


def _is_chmod_denial(node: ast.AST) -> bool:
    """True for a call that chmods something to mode 0, in any spelling.

    THE SINGLE OWNER of that question -- the detector and its vacuity floor both
    call it, because they were a copy-paste pair and a widening applied to one
    would have left the other blind.

    All three live spellings: `os.chmod(p, 0o000)` (two positional),
    `p.chmod(0o000)` (bound, ONE positional -- an AST census of `tests/` gives 7
    bound against 10 unbound, and the repo's two other permission tests
    `test_hooks.py::test_code_review_flag_write_oserror_is_handled` and
    `test_reinject.py::test_append_jsonl_read_only_dir_is_silent` are both
    bound, so a matcher keyed on arity alone misses half the idiom), and
    `mode=` by keyword.
    A `stat.S_*` or variable mode stays invisible to THIS matcher: an accepted
    limit, recorded rather than papered over. The live instances of that
    shape route through `tests/_locked.py::locked`, and `_LOCKING_HELPERS`
    below makes a function that calls it a denial block by name.
    """
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    if node.func.attr != "chmod":
        return False
    mode = None
    if len(node.args) >= 2:      # os.chmod(path, mode)
        mode = node.args[1]
    elif len(node.args) == 1:
        # path.chmod(mode). No `os.path` exclusion here, unlike the probe
        # detector: `os.path.chmod` is not an API, so there is nothing to
        # exclude and a guard against it would only imply there is.
        mode = node.args[0]
    for kw in node.keywords:     # a keyword `mode=` overrides either position
        if kw.arg == "mode":
            mode = kw.value
    return isinstance(mode, ast.Constant) and mode.value == 0


def _is_waived(lines: list[str], node: ast.Call) -> bool:
    """True when `_EACCES_PROBE_WAIVER` covers exactly THIS probe.

    Two accepted placements, and the split between them exists to stop a waiver
    leaking onto its neighbour:

      * ANYWHERE IN THE CALL'S OWN SPAN (`lineno`..`end_lineno`) -- covers the
        trailing form and, on a chained multi-line call, the marker's natural
        home beside the `.is_file()` token. `Call.lineno` is where the outermost
        expression STARTS, not where the probe method appears, so a window that
        stopped at `lineno` would never see the latter.
      * A COMMENT-ONLY LINE DIRECTLY ABOVE, for the line-above form.

    "Comment-only" is what makes the second placement unambiguous. A trailing
    marker sits on a CODE line, so it can no longer waive the probe on the
    following line as collateral -- measured: with a plain
    `[lineno-2:end_lineno]` window, `a = p.is_file()  # eacces-probe-ok: ...`
    silently waived an unrelated `b = p.is_dir()` beneath it.
    """
    span = lines[node.lineno - 1:node.end_lineno]
    if any(_EACCES_PROBE_WAIVER in ln for ln in span):
        return True
    above = lines[node.lineno - 2] if node.lineno >= 2 else ""
    return above.strip().startswith("#") and _EACCES_PROBE_WAIVER in above


# Helpers that lock a path for a block: a function CALLING one holds a denial
# window without a literal chmod-0 of its own -- the analog of
# `_SPAWNING_HELPERS` / `_DEV_TREE_WALKING_HELPERS` for this contract. The
# helper's own body is pinned EACCES-safe below, beside `_traversal_denied`.
_LOCKING_HELPERS = frozenset({"locked"})


def _calls_locking_helper(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _LOCKING_HELPERS
    )


def _denial_block_functions(
    tree: ast.AST,
) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Yield every function whose body contains a chmod-to-0 anywhere, or a
    call to one of the `_LOCKING_HELPERS`."""
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(_is_chmod_denial(c) or _calls_locking_helper(c) for c in ast.walk(fn)):
            yield fn


def _eacces_unsafe_probes_in_denial_blocks() -> dict[str, list[str]]:
    """Per-module `<fn>:<line>` for an unsafe Path probe in a chmod-0 function.

    Scoped to the enclosing function rather than a line window, so nudging the
    probe a few lines does not evade it. The cost of that width is a probe which
    genuinely runs outside the denial window; `_EACCES_PROBE_WAIVER` on the line
    (or the line above) is the declared way to say so.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(TESTS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:  # pragma: no cover - a syntax error reds elsewhere
            continue
        lines = text.splitlines()
        for fn in _denial_block_functions(tree):
            for node in ast.walk(fn):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _EACCES_UNSAFE_PROBES
                    and not node.args
                    and not _is_os_path_call(node.func)
                ):
                    continue
                if _is_waived(lines, node):
                    continue
                found.setdefault(path.name, []).append(
                    f"{fn.name}:{node.lineno} .{node.func.attr}()"
                )
    return found


def test_no_eacces_unsafe_probe_inside_a_permission_denial_block():
    """The rule this fix's own description contains, as a mechanism.

    A test that chmods a path to 0o000 and then asks `Path.exists()` whether the
    denial took is asking the one API whose answer depends on which CPython is
    running. `tests/test_integrity.py` did exactly that and reddened CI run
    31731067158 on the 3.10 and 3.11 legs while passing on the 3.14 dev host.

    This is the STATIC half only, and its limit is worth stating because
    mistaking it for the whole cost a second defect: it reads `tests/*.py`, so it
    is structurally blind to the same bug in product code -- which is exactly
    where the first cut of this fix relocated it. The behavioural half lives in
    `tests/_legacy_pathlib.py`, which substitutes the 3.10--3.13 bodies and
    therefore RUNS the product. Neither replaces the other.
    """
    offenders = _eacces_unsafe_probes_in_denial_blocks()
    assert not offenders, (
        f"EACCES-unsafe probe inside a chmod-0 block, module -> sites: "
        f"{offenders}. `Path.exists()`/`is_file()`/`is_dir()`/`is_symlink()` "
        "swallow the permission error on CPython 3.14 and RAISE it on "
        "3.10-3.13, so this passes locally and fails CI. Ask `os.stat` or "
        "`os.path.*` and discriminate PermissionError from FileNotFoundError "
        "-- `tests/test_integrity.py::_traversal_denied` is the worked example. "
        f"If the probe genuinely runs OUTSIDE the denial window (before the "
        f"chmod, after the restoring chmod, or on a path outside the denied "
        f"subtree), mark it `{_EACCES_PROBE_WAIVER} <reason>` -- do not delete "
        "the check."
    )


def test_the_traversal_denied_helper_body_stays_eacces_safe():
    """`_traversal_denied` is the one function the contract above cannot see.

    It holds no chmod, so it is not a denial block; its caller holds the chmod
    but no probe. Rewriting its seven lines back to `return not path.exists()`
    -- the single most likely future "simplification" -- leaves that contract
    AND its vacuity floor green while restoring the CI red. So the helper is
    named here directly, the same way `_LIVE_TREE_WATCH` is counterweighted
    above.
    """
    src = (TESTS_DIR / "test_integrity.py").read_text(encoding="utf-8")
    fn = next(
        (
            n for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.FunctionDef) and n.name == "_traversal_denied"
        ),
        None,
    )
    assert fn is not None, (
        "tests/test_integrity.py::_traversal_denied is gone. It is the EACCES-"
        "safe probe every chmod-0 test in this suite routes through; if it was "
        "renamed or moved to conftest.py, re-point this contract at the new "
        "home rather than deleting it."
    )
    calls = {
        f"{n.func.value.id}.{n.func.attr}"
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
    }
    assert "os.stat" in calls, (
        f"_traversal_denied no longer calls os.stat (found: {sorted(calls)}). "
        "It must ask an API that RAISES on EACCES on every supported version, "
        "then discriminate -- that discrimination is the entire point of the "
        "helper, and a `Path` probe cannot do it portably."
    )
    unsafe = [
        n.func.attr for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in _EACCES_UNSAFE_PROBES
        and not n.args
    ]
    assert not unsafe, (
        f"_traversal_denied uses the version-gated probe(s) {unsafe} it exists "
        "to replace."
    )


def test_the_locked_helper_body_stays_eacces_safe():
    """`tests/_locked.py` is the second function the contract above cannot
    see from the outside: its callers are denial blocks by name
    (`_LOCKING_HELPERS`), but its own body holds the chmod as a variable
    mode and the enforcement probes beside it. Rewriting a probe to
    `path.exists()` would be green on the 3.14 dev host and red on the
    3.10-3.13 cells -- the exact class the helper serves -- so both
    functions are pinned to the `os.*` calls, the same way `_traversal_denied`
    is."""
    src = (TESTS_DIR / "_locked.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for helper in ("locked", "_lock_is_enforced"):
        fn = next(
            (
                n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == helper
            ),
            None,
        )
        assert fn is not None, (
            f"tests/_locked.py::{helper} is gone. Every chmod test that locks a "
            "path routes through it; if it was renamed, re-point `_LOCKING_HELPERS` "
            "and this contract at the new name rather than deleting them."
        )
        unsafe = [
            n.func.attr for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in _EACCES_UNSAFE_PROBES
            and not n.args
        ]
        assert not unsafe, (
            f"tests/_locked.py::{helper} uses the version-gated probe(s) {unsafe} "
            "the helper exists to keep out of denial blocks."
        )
        if helper == "_lock_is_enforced":
            calls = {
                f"{n.func.value.id}.{n.func.attr}"
                for n in ast.walk(fn)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name)
            }
            assert "os.stat" in calls, (
                f"_lock_is_enforced no longer probes with os.stat (found: {sorted(calls)})."
            )


def test_the_denial_block_detector_still_engages_the_live_corpus():
    """Anti-vacuity floor: a matcher finding no chmod-0 function at all would
    pass the contract above having checked nothing -- the born-weak shape
    (docs/FAILURE_MODES.md, `/scan test_loosening`)."""
    blocks = 0
    for path in sorted(TESTS_DIR.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        blocks += sum(1 for _ in _denial_block_functions(tree))
    # Deliberately below the live count, not flush against it. The scanner's
    # chmod-0 site is a documented FALLBACK ("Primary: a dangling symlink") and
    # may legitimately go; pinning at the live number would meet that with
    # "the matcher has broken", sending the contributor to re-add a chmod they
    # just decided to delete. The sibling ratchet above solves the same problem
    # with an explicit shrink branch.
    assert blocks >= 2, (
        f"the chmod-0 census found {blocks} denial-block function(s); this "
        "suite has at least two (tests/test_integrity.py, tests/test_scanner_"
        "read_robustness.py). At this floor the contract above is vacuous. "
        "FIRST check whether _is_chmod_denial has stopped recognising a "
        "spelling -- that is the likely cause and the thing to fix. Only if "
        "the corpus genuinely shrank (a denial test was deliberately removed) "
        "should this floor move, and then lower it deliberately, in the same "
        "commit, with the reason beside it."
    )


# Base names that denote the LIVE repo root. A dev-only path anchored here hits
# real pruned content on an export; a tmp_path fixture never touches the live
# tree, so it is deliberately not flagged.
_REPO_ANCHOR_NAMES = frozenset(
    {"REPO_ROOT", "_REPO_ROOT", "REPO", "_REPO", "PROJECT_ROOT"}
)

# Helpers that walk the whole repo tree: calling one on the live root is an
# indirect (transitive) dev-only read the path-literal scan would otherwise miss
# — the analog of _SPAWNING_HELPERS for the subprocess contract.
_DEV_TREE_WALKING_HELPERS = frozenset({"render_pack_manifest", "reflect_repo"})


def _is_repo_anchor(node: ast.AST) -> bool:
    """True if `node` denotes the live repo root: a REPO_ROOT-style Name, the
    same name reached as an ATTRIBUTE (`self._REPO_ROOT` -- a class keeps its
    root as a class attribute; the spelling that carried the one literal-path
    read of the six the release matrix red on 2026-09-23, DEF-916), or the
    `Path(__file__).resolve().parent.parent` / `.parents[1]` idiom (…/tests ->
    repo root).

    The Attribute arm FALLS THROUGH to the idiom arm: `Path(__file__)...parent`
    is itself an ast.Attribute (attr='parent'), so an arm that returned
    `node.attr in _REPO_ANCHOR_NAMES` would answer False for the idiom before
    ast.dump could see it (measured: that form dropped two modules from the
    detector and failed test_path_file_idiom_anchor_is_flagged)."""
    if isinstance(node, ast.Name):
        return node.id in _REPO_ANCHOR_NAMES
    if isinstance(node, ast.Attribute) and node.attr in _REPO_ANCHOR_NAMES:
        return True
    dumped = ast.dump(node)
    return "__file__" in dumped and ("parent" in dumped or "parents" in dumped)


def _flatten_div(node: ast.BinOp) -> tuple[ast.AST, list]:
    """Flatten a `base / "a" / "b"` Path join into (base, [parts]). A non-string
    component (a variable) becomes None, terminating the known-prefix."""
    parts: list = []
    cur: ast.AST = node
    while isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Div):
        right = cur.right
        if isinstance(right, ast.Constant) and isinstance(right.value, str):
            parts.append(right.value)
        else:
            parts.append(None)
        cur = cur.left
    parts.reverse()
    return cur, parts


def _dev_only_chains(text: str, is_dev_only) -> int:
    """How many times the module reaches an export-ignored path anchored at the
    live repo root — directly (`REPO_ROOT / "ESPALIER_MEMORY.md"`) or via a
    dev-tree-walking helper called on that anchor (`render_pack_manifest(REPO_ROOT)`).

    `is_dev_only(rel) -> bool` is the single-owner predicate
    (surface_contract.export_ignore_patterns). tmp_path-anchored constructions
    are not counted: they build dev-only-*shaped* paths under a fixture dir and
    never read the live tree. AST-based so string/comment mentions of a dev-only
    path do not false-positive. The count is what
    `test_every_exempt_module_carries_exactly_its_measured_dev_only_chains` pins
    per exempt module; `_module_reads_dev_only_path` is its boolean."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return 0
    chains = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            base, parts = _flatten_div(node)
            if not _is_repo_anchor(base):
                continue
            known: list = []
            for part in parts:
                if part is None:
                    break
                known.append(part)
            if any(
                is_dev_only("/".join(known[:i])) for i in range(1, len(known) + 1)
            ):
                chains += 1
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _DEV_TREE_WALKING_HELPERS:
                if any(_is_repo_anchor(arg) for arg in node.args):
                    chains += 1
    return chains


def _module_reads_dev_only_path(text: str, is_dev_only) -> bool:
    """True if the module reaches an export-ignored path anchored at the live
    repo root at least once -- see `_dev_only_chains`."""
    return _dev_only_chains(text, is_dev_only) > 0


def _export_ignore_predicate():
    """A `rel -> bool` closure: True when `rel` is pruned from a release export
    (a `.gitattributes export-ignore` entry — exactly what `git archive` drops,
    which is what `surface_contract.is_release_export` keys on). Single owner:
    surface_contract."""
    from espalier import surface_contract

    patterns = surface_contract.export_ignore_patterns(REPO_ROOT)

    def is_dev_only(rel: str) -> bool:
        rel = rel.replace("\\", "/").strip("/")
        if not rel:
            return False
        return any(
            surface_contract.matches_export_ignore(rel, pat) for pat in patterns
        )

    return is_dev_only


def test_every_dev_tree_test_is_full_tree_or_exempt():
    """TP-283: every test that reads full-dev-tree-only content (a path pruned
    from a release export) must be covered by tests/conftest.py::_FULL_TREE_NODEIDS
    (so it auto-skips on a detected export) or carry an explicit
    ``# full-tree-exempt: <reason>`` opt-out.

    An exempt module either self-guards when the content is absent, or derives
    its population from the tree it runs on and was measured passing on an
    extracted archive -- the marker says which, with the date. The marker is a
    whole-module suppression the self-expiry audit never reaches, so
    `test_every_exempt_module_carries_exactly_its_measured_dev_only_chains`
    below pins each exempt module's dev-only chain count: a second live-tree
    read landing in one reds instead of hiding under the first one's reason
    (the 2026-09-23 failure-mode review, F1 and F8).

    The analog of test_every_subprocess_test_is_slow_or_exempt for the over-reach
    class TP-281/282 addressed: a test reading content that a ``git archive``
    drops will FileNotFoundError / mis-assert when the suite runs against an
    extracted export. This reds the next un-marked one at authoring time.

    File-granular by design (TP-283's documented mixed-granularity gap). The
    marker is read from _FULL_TREE_NODEIDS, never scanned from source — it is
    applied at collection time, so it appears in no test file.

    ⚠ MEASURED RECALL: 0 of 8. Read this before treating a green here as
    coverage. On 2026-08-14 a real release archive was driven at two extraction
    locations and produced 28 dev-tree-only test failures across 8 modules;
    `_module_reads_dev_only_path` flags **none** of those 8. That is on top of
    the 0/3 already on record in the retired findings corpus (record branch,
    b3e36ae:docs/known-findings.md). Every one of the 28
    reaches pruned content through a shape the predicate cannot see — a
    module-level constant list, a `Path.cwd()` walk, a `git` shell-out, or
    `tests/_git_oracle.py::require_tracked_paths` — not through the
    `REPO_ROOT / "<literal>"` BinOp it scans for.

    Widening the predicate was considered and rejected: each of the 28 uses a
    different indirection, so it is an unwinnable chase (a prototype measured
    3/10 recall with 8 false positives, `DEF-491`). The runtime measurement in
    `scripts/final_release_matrix.py` stage 02 — the whole suite against a real
    archive — is what actually has recall here. This stays as a cheap
    authoring-time FLOOR, and the honest statement of its value is "it catches
    the literal-path shape and nothing else."

    2026-09-23, the matrix's six (DEF-916): one was the literal-path shape and
    escaped on spelling alone (a class-attribute anchor, `self._REPO_ROOT`, now
    seen); five were the shapes this paragraph already names as unreachable --
    a pin on a population the export changes, an export-detected behaviour.
    The archive drive (`scripts/archive_probe.py`, TP-455's Task 0) is the
    four-minute oracle for those.

    File-granularity is deliberate and load-bearing, not an oversight: 10
    per-test-registered modules DO trip the predicate at module level
    (re-derived 2026-09-23 after the TP-455 sweep narrowed six whole-module and
    class entries to their failing tests: test_contracts,
    test_convergence_workflow_stages, test_doc_source_citations,
    test_doc_test_citations, test_documented_claims, test_finding_ledger,
    test_manifest_truth, test_memory_anchor_freshness,
    test_memory_md_consistency, test_release_checklist_contract), and they are
    correctly handled by their per-test fragments. Making registration
    granularity-matched here would red all 10 for no defect."""
    from tests.conftest import _FULL_TREE_NODEIDS

    is_dev_only = _export_ignore_predicate()
    marked_files = {frag.split("::", 1)[0] for frag in _FULL_TREE_NODEIDS}

    offenders: list = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        if not _module_reads_dev_only_path(text, is_dev_only):
            continue
        if _FULL_TREE_EXEMPT_MARKER in text:
            continue
        if path.name not in marked_files:
            offenders.append(path.stem)
    assert not offenders, (
        "These test modules read full-dev-tree-only content (a path pruned from "
        "a release export) anchored at the live repo root, but are not covered by "
        "tests/conftest.py::_FULL_TREE_NODEIDS and carry no "
        f"`# full-tree-exempt: <reason>` opt-out: {offenders}. Such a test "
        "FileNotFoundErrors / mis-asserts when the suite runs against an "
        "extracted archive. Add its nodeid to _FULL_TREE_NODEIDS (so it "
        "auto-skips on a detected export), or add a `# full-tree-exempt: "
        "<reason>` comment if it self-guards when the content is absent, or "
        "derives its population from the tree it runs on and was measured "
        "passing on an extracted archive (say which, with the date), and add "
        "the module to _EXEMPT_MODULE_DEV_ONLY_CHAINS with its measured count."
    )


# Measured 2026-09-23 by `_dev_only_chains` over every module carrying the
# opt-out marker. A whole-module opt-out is the one suppression the self-expiry
# audit never reaches, so the count is pinned: a second live-tree read landing
# in an exempt module reds here instead of hiding under the first one's
# reason. `test_test_suite_contract.py` carries the marker only as its own
# definition and prose; `test_verify_pins.py` reaches git history through a
# shape the walk cannot see, so both pin at zero.
_EXEMPT_MODULE_DEV_ONLY_CHAINS: dict[str, int] = {
    "test_check_ledger_probes.py": 1,
    "test_check_pack_landing.py": 6,
    "test_generate_ledger_regions.py": 1,
    "test_lifecycle_parity.py": 1,
    "test_pack_manifest.py": 3,
    "test_record_snapshot.py": 1,   # the checklist reader, guarded through tests/_export_guard.py
    "test_reflection.py": 1,        # reflect_repo on the repo root, a derived population
    "test_test_suite_contract.py": 0,
    "test_verify_pins.py": 0,
}


def test_every_exempt_module_carries_exactly_its_measured_dev_only_chains():
    """The exempt set is derived (every module carrying the marker); the count
    per module is the pin. Growth is a new unguarded read that the file-granular
    contract above can no longer see; shrinkage is a stale reason; a module
    missing from the pin is a new exemption to measure and state."""
    is_dev_only = _export_ignore_predicate()
    measured = {
        path.name: _dev_only_chains(path.read_text(encoding="utf-8"), is_dev_only)
        for path in sorted(TESTS_DIR.glob("test_*.py"))
        if _FULL_TREE_EXEMPT_MARKER in path.read_text(encoding="utf-8")
    }
    assert measured, "no module carries the opt-out marker -- the census read nothing"
    assert measured == _EXEMPT_MODULE_DEV_ONLY_CHAINS, (
        "an exempt module's dev-only chain count moved, or the exempt set did: "
        f"measured {measured}, pinned {_EXEMPT_MODULE_DEV_ONLY_CHAINS}. A new "
        "live-tree read in an exempt module must be guarded or registered like "
        "the first one -- the opt-out covers the reads it was written for, not "
        "the next one. Re-measure and re-state the pin with the reason."
    )


# The REGISTERED twin of the pin above, added 2026-09-23 after the first
# registration for tests/test_archive_probe.py landed: a module named in
# _FULL_TREE_NODEIDS by ANY fragment is skipped wholesale by the file-granular
# contract (`marked_files`), so a second, unregistered live-tree read landing
# in such a module inherited the first one's suppression with no signal -- the
# exempt set got its count pin the day before, the registered set had none.
# Population: every module in the registry's file set that trips the detector;
# the count per module is the pin. Measured 2026-09-23 over the 23 registered
# modules (the other 13 trip nothing today; one that starts to joins here).
_REGISTERED_MODULE_DEV_ONLY_CHAINS: dict[str, int] = {
    "test_contracts.py": 5,
    "test_convergence_workflow_stages.py": 1,
    "test_doc_source_citations.py": 2,
    "test_doc_test_citations.py": 1,
    "test_documented_claims.py": 1,
    "test_finding_ledger.py": 1,
    "test_manifest_truth.py": 3,
    "test_memory_anchor_freshness.py": 1,
    "test_memory_md_consistency.py": 1,
    "test_release_checklist_contract.py": 1,
}


def test_every_registered_module_carries_exactly_its_measured_dev_only_chains():
    """The registered set is derived (every module the registry names); the
    count per module is the pin. Growth is a new live-tree read hiding under
    a sibling's registration; shrinkage is a guard or a registration that
    should be recorded; a module appearing here for the first time is a
    registered module that started reading the dev tree and needs its own
    fragment or guard, not the file-set immunity it just inherited."""
    from tests.conftest import _FULL_TREE_NODEIDS

    is_dev_only = _export_ignore_predicate()
    marked = {frag.split("::", 1)[0] for frag in _FULL_TREE_NODEIDS}
    assert marked, "the registry names no module -- the census read nothing"
    measured: dict[str, int] = {}
    for name in sorted(marked):
        path = TESTS_DIR / name
        assert path.is_file(), f"the registry names a module that does not exist: {name}"
        text = path.read_text(encoding="utf-8")
        if _module_reads_dev_only_path(text, is_dev_only):
            measured[name] = _dev_only_chains(text, is_dev_only)
    assert measured, "no registered module trips the detector -- the census read nothing"
    assert measured == _REGISTERED_MODULE_DEV_ONLY_CHAINS, (
        "a registered module's dev-only chain count moved, or the set of "
        f"registered modules that read the dev tree did: measured {measured}, "
        f"pinned {_REGISTERED_MODULE_DEV_ONLY_CHAINS}. A new live-tree read in a "
        "registered module must be registered or guarded like the first one -- "
        "a fragment covers the test it names, not the module. Re-measure and "
        "re-state the pin with the reason."
    )


class TestDevTreeContractDetector:
    """Pin the detector's repo-anchor-vs-tmp_path discrimination — the property
    that keeps test_every_dev_tree_test_is_full_tree_or_exempt free of false
    positives on the many fixture tests that build dev-only-shaped paths under
    tmp_path (the calibration that made the file-granular contract viable)."""

    def _dev_only(self):
        return _export_ignore_predicate()

    def test_repo_anchored_dev_only_read_is_flagged(self):
        src = (
            "from pathlib import Path\n"
            "REPO_ROOT = Path(__file__).resolve().parent.parent\n"
            'x = REPO_ROOT / "ESPALIER_MEMORY.md"\n'
        )
        assert _module_reads_dev_only_path(src, self._dev_only())

    def test_path_file_idiom_anchor_is_flagged(self):
        # A landed pack: `task-packs/Done/` is export-ignored. The fixture read
        # `task-packs/CLAUDE.md` until 2026-09-21, when the router (with the
        # forward ledger and the active packs) started shipping and stopped
        # being a dev-only path.
        src = 'from pathlib import Path\nx = Path(__file__).resolve().parent.parent / "task-packs" / "Done" / "TP-1-x.md"\n'
        assert _module_reads_dev_only_path(src, self._dev_only())

    def test_the_shipped_router_is_no_longer_a_dev_only_path(self):
        # The other direction of the same date: a module reading the router
        # reads shipped content, so the dev-tree registration is not owed.
        src = 'from pathlib import Path\nx = Path(__file__).resolve().parent.parent / "task-packs" / "CLAUDE.md"\n'
        assert not _module_reads_dev_only_path(src, self._dev_only())

    def test_tmp_path_dev_only_write_is_ignored(self):
        src = 'def t(tmp_path):\n    (tmp_path / "ESPALIER_MEMORY.md").write_text("x")\n'
        assert not _module_reads_dev_only_path(src, self._dev_only())

    def test_dev_tree_walking_helper_on_anchor_is_flagged(self):
        src = "REPO_ROOT = 1\nrender_pack_manifest(REPO_ROOT)\n"
        assert _module_reads_dev_only_path(src, self._dev_only())

    def test_dev_tree_walking_helper_on_tmp_is_ignored(self):
        src = "def t(tmp_path):\n    reflect_repo(tmp_path)\n"
        assert not _module_reads_dev_only_path(src, self._dev_only())

    def test_public_path_anchored_read_is_not_flagged(self):
        # espalier/ ships in the export — reading it is not a full_tree concern.
        src = 'REPO_ROOT = 1\nx = REPO_ROOT / "espalier" / "cli.py"\n'
        assert not _module_reads_dev_only_path(src, self._dev_only())

    def test_class_attribute_anchor_is_flagged(self):
        # The spelling that escaped until 2026-09-23 (DEF-916): a class keeps
        # the root as `_REPO_ROOT` and reads through `self.`.
        src = (
            "class TestX:\n"
            "    _REPO_ROOT = 1\n"
            "    def test_y(self):\n"
            '        (self._REPO_ROOT / "docs" / "RELEASE_CHECKLIST.md").read_text()\n'
        )
        assert _module_reads_dev_only_path(src, self._dev_only())

    def test_an_attribute_that_is_not_a_root_name_is_not_an_anchor(self):
        src = (
            "class TestX:\n"
            "    def test_y(self, tmp_path):\n"
            '        (self.scratch / "ESPALIER_MEMORY.md").write_text("x")\n'
        )
        assert not _module_reads_dev_only_path(src, self._dev_only())

    def test_a_root_named_attribute_on_a_fixture_object_is_flagged_by_name(self):
        # The accepted false-positive shape (the 2026-09-23 failure-mode
        # review, F2): the arm keys on the attribute's NAME, so a fixture kept
        # under a root-like name is an anchor too. Zero on the live tree; the
        # remedy is not to name a fixture attribute like a root, never the
        # whole-module opt-out.
        src = (
            "class TestX:\n"
            "    def test_y(self, tmp_path):\n"
            "        self.REPO = tmp_path\n"
            '        (self.REPO / "ESPALIER_MEMORY.md").write_text("x")\n'
        )
        assert _module_reads_dev_only_path(src, self._dev_only())

    def test_the_chain_count_is_per_read_not_per_module(self):
        src = (
            "REPO_ROOT = 1\n"
            'a = REPO_ROOT / "ESPALIER_MEMORY.md"\n'
            'b = REPO_ROOT / "docs" / "RELEASE_CHECKLIST.md"\n'
            'c = REPO_ROOT / "espalier" / "cli.py"\n'
            "render_pack_manifest(REPO_ROOT)\n"
        )
        assert _dev_only_chains(src, self._dev_only()) == 3


def test_the_report_os_name_guard_is_registered(pytestconfig):
    """D2's fix is one hookwrapper (`tests/_report_os_name_guard.py`) whose only
    registration is an import line in `tests/conftest.py`. Dropping that line
    -- a conftest refactor, a tidy of "unused imports", a merge -- disarms it
    everywhere, and on 3.12+ nothing notices: pytest's failure formatter
    constructs there anyway, so every local run stays green while the 3.10
    floor goes back to a session INTERNALERROR (the red team drove it,
    2026-09-22). The inner-session row cannot catch this: it writes its own
    conftest with the import. So this asserts the hook is in the RUNNING
    session's plugin manager, on every interpreter, in the suite that is
    actually executing."""
    from tests import _report_os_name_guard as guard

    registered = [
        impl.function
        for impl in pytestconfig.pluginmanager.hook.pytest_runtest_makereport.get_hookimpls()
    ]
    assert guard.pytest_runtest_makereport in registered, (
        "tests/_report_os_name_guard.py::pytest_runtest_makereport is not registered -- "
        "tests/conftest.py must import it by name (see the module docstring)"
    )


def test_no_non_test_function_carries_a_skip_or_xfail_mark():
    """A `pytest.mark.skip` / `skipif` / `xfail` on a function that is not a
    test is inert -- pytest stamps `pytestmark` on it and moves on -- and the
    only way one gets there is by mistake: a helper inserted between a
    class's decorator and the class detaches the mark from the class
    (`tests/test_hook_exec_form.py`, red-team lane A, 2026-09-22: the Windows
    `skipif` landed on `_base_interpreter`, and the class it guarded would
    have false-redded `portability.yml`'s Windows cell). Nothing else notices:
    `--strict-markers` accepts the mark, mypy does not read decorators, the
    loosening scanner reads only tests. Census on landing: none."""
    import ast
    import re
    offenders = []
    mark_re = re.compile(r"pytest\.mark\.(skip|skipif|xfail)\b")
    for path in sorted((REPO_ROOT / "tests").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("test_"):
                for deco in node.decorator_list:
                    text = ast.unparse(deco)
                    if mark_re.match(text):
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} {node.name}: @{text[:60]}")
    assert not offenders, (
        "a skip/skipif/xfail mark on a non-test function is inert -- it was meant for "
        "the class or test below it; move the helper out of the way:\n  " + "\n  ".join(offenders)
    )
