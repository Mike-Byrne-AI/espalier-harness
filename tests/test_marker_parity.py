"""TP-113: structural test marker parity.

`pyproject.toml [tool.pytest.ini_options].markers` declares 8 taxonomy
markers as a flat list: ``unit``, ``integration``, ``contract``, ``security``,
``release``, ``slow``, ``heavy_e2e``, ``full_tree`` -- plus the plugin-owned
declarations named in ``tests/_surface_expected.py::PLUGIN_OWNED_MARKERS``
(``timeout``, declared so ``--strict-markers`` collects without
``pytest-timeout``), which are not taxonomy and are removed before the
comparison below. ``tests/conftest.py`` implements the same vocabulary across
FOUR surfaces:

- ``_MARKER_RULES``: list of ``(filenames, marker_name)`` tuples that
  classify 5 markers (``security`` / ``release`` / ``contract`` /
  ``integration`` / ``unit``).
- ``_SLOW_FILES``: non-empty set that overlays the additive ``slow``
  marker on top of the primary classification.
- ``_HEAVY_E2E_TESTS``: non-empty set (keyed by test function name)
  that overlays the additive ``heavy_e2e`` marker (TP-223).
- ``_FULL_TREE_NODEIDS``: non-empty set (keyed by ``item.nodeid``
  substring) that overlays the additive ``full_tree`` marker on the
  full-self-host-dev-tree-only tests.

The structural contract: the UNION of ``{markers in _MARKER_RULES}``
∪ ``{"slow" if _SLOW_FILES else nothing}``
∪ ``{"heavy_e2e" if _HEAVY_E2E_TESTS else nothing}``
∪ ``{"full_tree" if _FULL_TREE_NODEIDS else nothing}`` must equal the
pyproject declared set. Drift modes this catches:

- New marker added to ``_MARKER_RULES`` without ``pyproject.toml``
  declaration causes ``pytest --strict-markers`` to reject at runtime.
- Marker removed from ``pyproject.toml`` without scrubbing
  ``_MARKER_RULES`` leaves a dead taxonomy entry.
- ``slow`` removed from ``_SLOW_FILES`` (set emptied) without
  scrubbing the pyproject ``slow`` marker leaves an orphaned
  declaration.

The contract is encoded as ``MARKER_PARITY_CONTRACT`` —
a ``StringListContract`` instance (TP-109b primitive) so the
``marker-taxonomy`` rule_id has a discoverable registry surface; the
behavioral assertion uses the AST helper ``_parse_conftest_taxonomy``
because regex cannot faithfully extract markers from nested tuple
literals in ``_MARKER_RULES`` or detect ``_SLOW_FILES`` set
non-emptiness. ``CONTRACT_CEILINGS["marker-taxonomy"] = 0`` keys
per-rule opt-out chip-down per TP-109b infrastructure.
"""
from __future__ import annotations

# slow-exempt: ONE `--collect-only` subprocess over the whole suite (~2.2s for
# 8257 nodeids), not per-fragment. That is the only way to verify a `[param]`
# fragment resolves -- pytest builds param ids from runtime values, so no AST
# check can see them. Precedent: tests/test_benchmark_release_hygiene.py.

import ast
from pathlib import Path

# tomllib lives in stdlib from Py 3.11+; repo declares
# `requires-python = ">=3.10"`, so bare `import tomllib` would crash
# Py 3.10 at collection. Use espalier._compat.tomllib (try tomllib,
# fall back to tomli, expose None if neither — caller raises).
# Established pattern: tests/test_bench_results_parity.py:25.
import pytest

from espalier._compat import tomllib
from tests._contracts import StringListContract
from tests._surface_expected import PLUGIN_OWNED_MARKERS

REPO_ROOT = Path(__file__).resolve().parent.parent


# The contract surface (registry-discoverable). The pyproject regex
# captures the marker name from each `"name: description"` TOML list
# entry. The conftest source is intentionally bound to an AST helper
# rather than a regex because no regex can faithfully extract markers
# from nested tuple literals in `_MARKER_RULES` or detect
# `_SLOW_FILES` set non-emptiness; the placeholder regex below would
# return `[]` if ever called via `extract_matches`, and the
# behavioral assertion routes conftest through `_parse_conftest_taxonomy`.
MARKER_PARITY_CONTRACT = StringListContract(
    name="pytest markers ↔ conftest._MARKER_RULES + _SLOW_FILES",
    rule_id="marker-taxonomy",
    expected_values=frozenset({
        "unit", "integration", "contract", "security",
        "release", "slow", "heavy_e2e", "full_tree",
    }),
    sources=(
        # pyproject markers (flat list — regex-extractable; group(1)
        # captures the marker name).
        ("pyproject.toml", r'"(\w+):\s+'),
        # conftest taxonomy — AST-extracted by
        # _parse_conftest_taxonomy below, NOT by extract_matches.
        # The placeholder regex is intentional: a regex cannot
        # faithfully extract markers from `_MARKER_RULES` (nested
        # tuple structure) or detect `_SLOW_FILES` set non-emptiness.
        ("tests/conftest.py", r"# AST: see _parse_conftest_taxonomy"),
    ),
)


def _parse_pyproject_markers() -> frozenset[str]:
    """Read pyproject.toml [tool.pytest.ini_options].markers; extract the
    TAXONOMY marker names -- each 'name: description' string's name, minus
    the plugin-owned declarations (``PLUGIN_OWNED_MARKERS``).

    Raises RuntimeError if neither tomllib nor tomli is available
    (Py 3.10 without tomli) — matches espalier/config.py pattern.
    """
    if tomllib is None:
        raise RuntimeError(
            "Install tomli for Python < 3.11; espalier._compat.tomllib "
            "returned None (no tomllib stdlib + no tomli fallback)."
        )
    data = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    markers = data["tool"]["pytest"]["ini_options"]["markers"]
    return _taxonomy_only(_marker_names(markers))


def _marker_names(lines) -> frozenset[str]:
    """The bare name of each ``name: description`` / ``name(args): description``
    line -- pytest's own split, on ``:`` and then on ``(``."""
    return frozenset(m.split(":", 1)[0].split("(", 1)[0].strip() for m in lines)


def _taxonomy_only(names: frozenset[str]) -> frozenset[str]:
    """Drop the plugin-owned declarations: they are in pyproject so the suite
    collects without the plugin, and in no conftest surface, by design."""
    return names - set(PLUGIN_OWNED_MARKERS)


def _parse_conftest_taxonomy() -> frozenset[str]:
    """AST-walk tests/conftest.py and build the union taxonomy.

    Extracts marker names from each ``(filenames, marker)`` tuple in
    ``_MARKER_RULES`` (the second tuple element when it's a
    ``ast.Constant`` str). Adds ``"slow"`` to the set when
    ``_SLOW_FILES`` is a non-empty ``ast.Set`` literal at module
    scope.

    Module-scope walk only (``tree.body``); handles both ``AnnAssign``
    (annotated) and ``Assign`` (plain) shapes for both names.
    """
    tree = ast.parse(
        (REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    )
    markers: set[str] = set()
    slow_files_nonempty = False
    heavy_e2e_nonempty = False
    full_tree_nonempty = False

    for node in tree.body:
        if not isinstance(node, (ast.AnnAssign, ast.Assign)):
            continue
        target = (
            node.target if isinstance(node, ast.AnnAssign)
            else (node.targets[0] if node.targets else None)
        )
        if not isinstance(target, ast.Name):
            continue
        if target.id == "_MARKER_RULES" and isinstance(node.value, ast.List):
            for entry in node.value.elts:
                if not isinstance(entry, ast.Tuple) or len(entry.elts) != 2:
                    continue
                _, marker = entry.elts
                if isinstance(marker, ast.Constant) and isinstance(marker.value, str):
                    markers.add(marker.value)
        elif target.id == "_SLOW_FILES" and isinstance(node.value, ast.Set):
            slow_files_nonempty = bool(node.value.elts)
        elif target.id == "_HEAVY_E2E_TESTS" and isinstance(node.value, ast.Set):
            heavy_e2e_nonempty = bool(node.value.elts)
        elif target.id == "_FULL_TREE_NODEIDS" and isinstance(node.value, ast.Set):
            full_tree_nonempty = bool(node.value.elts)

    if slow_files_nonempty:
        markers.add("slow")
    if heavy_e2e_nonempty:
        markers.add("heavy_e2e")
    if full_tree_nonempty:
        markers.add("full_tree")
    return frozenset(markers)


class TestMarkerParity:
    def test_pyproject_equals_conftest_taxonomy(self):
        """Live parsers on both sides; no hardcoded sister-site."""
        pyproject = _parse_pyproject_markers()
        conftest = _parse_conftest_taxonomy()
        assert pyproject == conftest, (
            f"Marker taxonomy drift:\n"
            f"  pyproject:        {sorted(pyproject)}\n"
            f"  conftest (union): {sorted(conftest)}\n"
            f"  pyproject-only:   {pyproject - conftest}\n"
            f"  conftest-only:    {conftest - pyproject}\n"
            f"Either side may need updating; the StringListContract "
            f"MARKER_PARITY_CONTRACT keys rule_id 'marker-taxonomy' "
            f"in CONTRACT_CEILINGS (tests/_surface_expected.py)."
        )

    def test_a_plugin_owned_marker_is_declared_and_excluded_not_absorbed(self):
        """The exclusion does work. The raw pyproject list carries every
        plugin-owned marker (else the suite would not collect without the
        plugin -- pinned again by test_test_suite_contract), and the taxonomy
        comparison never sees it. Earn the red: without ``_taxonomy_only``,
        ``test_pyproject_equals_conftest_taxonomy`` reds with
        ``pyproject-only: {'timeout'}`` (measured 2026-09-22)."""
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        raw = _marker_names(data["tool"]["pytest"]["ini_options"]["markers"])
        owned = set(PLUGIN_OWNED_MARKERS)
        assert owned and owned <= raw, owned - raw
        assert not (owned & _parse_pyproject_markers())

    def test_contract_expected_values_match_pyproject(self):
        """MARKER_PARITY_CONTRACT.expected_values must equal the live
        pyproject set — the contract is the registry surface; if it
        drifts from pyproject without conftest updating in sync, this
        fires before test_pyproject_equals_conftest_taxonomy gets to
        report the actual drift direction.
        """
        assert MARKER_PARITY_CONTRACT.expected_values == _parse_pyproject_markers()


class _CollectedItem:
    """Minimal stand-in for a pytest ``Item`` exposing only the attributes
    ``pytest_collection_modifyitems`` reads (``nodeid`` / ``path.stem`` /
    ``name``) and records ``add_marker`` calls. Leading underscore so pytest
    does not try to collect it."""

    def __init__(self, nodeid: str, stem: str, name: str):
        self.nodeid = nodeid
        self.path = type("_P", (), {"stem": stem})()
        self.name = name
        self.markers: list = []

    def add_marker(self, marker) -> None:
        self.markers.append(marker)


def _registered_test_fragment() -> tuple[str, str, str]:
    """One registered fragment of the exact ``file.py::Class::test`` shape, read
    from the registry itself: ``(nodeid, stem, name)``. Derived, not spelled --
    this fixture used to hard-code the reflection broken-links row, and the
    2026-09-23 self-expiry sweep (TP-455) retired that row and stranded the
    fixture; a fragment the registry actually carries cannot go stale here."""
    from tests.conftest import _FULL_TREE_NODEIDS

    cands = sorted(
        f for f in _FULL_TREE_NODEIDS
        if f.count("::") == 2 and not f.endswith("::") and "[" not in f
    )
    assert cands, "no file::Class::test fragment in _FULL_TREE_NODEIDS to drive the hook with"
    frag = cands[0]
    file, _cls, name = frag.split("::")
    return f"tests/{frag}", file[: -len(".py")], name


def _run_modifyitems(monkeypatch, *, is_export: bool) -> "_CollectedItem":
    """Drive conftest's collection hook over one full_tree item, forcing the
    export/dev-tree branch via ``surface_contract.is_release_export``."""
    import tests.conftest as conftest
    from espalier import surface_contract

    monkeypatch.setattr(
        surface_contract, "is_release_export", lambda root: is_export
    )
    nodeid, stem, name = _registered_test_fragment()
    item = _CollectedItem(nodeid=nodeid, stem=stem, name=name)
    conftest.pytest_collection_modifyitems(config=None, items=[item])
    return item


def _has_skip(item: "_CollectedItem") -> bool:
    return any(getattr(m, "name", None) == "skip" for m in item.markers)


class TestFullTreeExportAutoSkip:
    """On a detected release export, full_tree items are auto-skipped at
    collection so an export-pytest consumer that does NOT pass
    ``-m "not full_tree"`` (``release_check.py``'s ``tests_pass``, a bare
    ``pytest`` on an extracted archive, a future consumer) never runs them
    against pruned dev content. On the dev tree they run.
    """

    def test_full_tree_item_is_marked(self, monkeypatch):
        item = _run_modifyitems(monkeypatch, is_export=False)
        assert "full_tree" in [m for m in item.markers if isinstance(m, str)], (
            f"{item.nodeid} (the registry's first file::Class::test fragment) was not marked"
        )

    def test_auto_skipped_on_release_export(self, monkeypatch):
        # Earn-the-red: drop the `if repo_is_export: add skip` branch and this
        # item collects unskipped on an export, then fails on pruned content —
        # exactly the release_check `tests_pass` failure the matrix surfaced.
        item = _run_modifyitems(monkeypatch, is_export=True)
        assert _has_skip(item), f"{item.nodeid} must be skipped on a release export"

    def test_runs_on_dev_tree(self, monkeypatch):
        item = _run_modifyitems(monkeypatch, is_export=False)
        assert not _has_skip(item), f"dev tree must RUN {item.nodeid} (no skip)"

    def test_the_audit_switch_runs_the_rows_on_an_export(self, monkeypatch):
        monkeypatch.setenv("ESPALIER_FULL_TREE_AUDIT", "1")
        item = _run_modifyitems(monkeypatch, is_export=True)
        assert not _has_skip(item), f"under the audit {item.nodeid} must RUN on an export"

    def test_the_audit_switch_refuses_off_an_export(self, monkeypatch):
        # Off an export the switch used to change nothing, so a bare
        # `ESPALIER_FULL_TREE_AUDIT=1 pytest -m full_tree` at the repo root ran
        # every registered row on its own dev content and read the whole
        # registry as stale (the 2026-09-23 failure-mode review, F3).
        monkeypatch.setenv("ESPALIER_FULL_TREE_AUDIT", "1")
        with pytest.raises(pytest.UsageError, match="not a release export"):
            _run_modifyitems(monkeypatch, is_export=False)


def _full_tree_marks_outside_the_registry(tests_dir: Path = REPO_ROOT / "tests") -> list[str]:
    """Every `pytest.mark.full_tree` spelled in a test module -- a decorator or a
    `pytestmark` -- as `file.py:line`. AST, so prose and strings do not count."""
    hits: list[str] = []
    for path in sorted(tests_dir.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute) and node.attr == "full_tree"
                and isinstance(node.value, ast.Attribute) and node.value.attr == "mark"
                and isinstance(node.value.value, ast.Name) and node.value.value.id == "pytest"
            ):
                hits.append(f"{path.name}:{node.lineno}")
    return hits


class TestTheRegistryIsTheOnlySourceOfFullTree:
    """A `full_tree` suppression spelled as a decorator sits in the same
    population as a registry fragment but outside every contract over the
    registry: the self-expiry audit, the resolves-to-a-live-target pins, the
    file-granular detector's `marked_files`. One existed until 2026-09-23
    (`test_reflect_protocol.py`, a derived-population row that passes on a
    seeded export) and the sweep that retired 21 fragments could not see it.
    The registry is the one place the mark comes from."""

    def test_no_test_module_marks_full_tree_directly(self):
        hits = _full_tree_marks_outside_the_registry()
        assert not hits, (
            "full_tree is applied from tests/conftest.py::_FULL_TREE_NODEIDS at "
            "collection, never spelled in a test module -- a direct mark escapes "
            f"the registry's self-expiry audit and its resolution pins: {hits}"
        )

    def test_the_census_sees_a_direct_mark(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text(
            "import pytest\n\n@pytest.mark.full_tree\ndef test_y():\n    pass\n",
            encoding="utf-8",
        )
        assert _full_tree_marks_outside_the_registry(tmp_path / "tests") == ["test_x.py:3"]


def _module_nodeid_tails(path: Path) -> set[str]:
    """Every nodeid tail a pytest run could produce for ``path``.

    ``{"TestX", "TestX::test_y", "test_module_level"}`` — the forms
    ``_FULL_TREE_NODEIDS`` fragments are written against. AST-based so an
    unimportable module (or one with collection-time side effects) is still
    covered.
    """
    tails: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            tails.add(node.name)
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if sub.name.startswith("test"):
                        tails.add(f"{node.name}::{sub.name}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                tails.add(node.name)
    return tails






def _split_param(tail: str) -> tuple[str, str | None]:
    """``"C::t[p]"`` -> ``("C::t", "p")``; ``"C::t"`` -> ``("C::t", None)``.

    Only a tail ENDING in ``]`` is treated as parametrized, which is also the
    well-formedness rule: collection matches by plain substring, so an unclosed
    ``...[ESPALIER_MEMORY.md`` would silently also match
    ``...[ESPALIER_MEMORY.md line cap]``. Closing the bracket makes it exact.
    """
    if tail.endswith("]") and "[" in tail:
        base, _, param = tail.partition("[")
        return base, param[:-1]
    return tail, None


class TestFullTreeFragmentsResolve:
    """Every ``_FULL_TREE_NODEIDS`` fragment must name exactly what it claims.

    Two silent failure shapes, both measured live on 2026-08-14 and neither
    visible to any prior contract (``test_marker_parity`` asserted only that the
    set was non-EMPTY):

    * **Dead fragment.** ``test_catalog_self_consistency.py::test_bare_anchor_
      floor_counts_evaluated_anchors_not_regex_matches`` matched 0 of 8223
      collected nodeids — its target was deleted by 595409b five days earlier.
      A dead fragment is a false coverage claim, and worse, it keeps its module
      inside ``test_test_suite_contract``'s file-granular ``marked_files``,
      immunising every sibling from that detector.
    * **Silent over-match.** Collection matches with ``frag in item.nodeid`` —
      plain substring, prefix-open. A new test whose name EXTENDS a registered
      one (this repo builds twins that way: ``test_earn_the_red_*``) inherits
      ``full_tree`` on every export with no signal at all.
    """

    def _fragments(self):
        from tests.conftest import _FULL_TREE_NODEIDS

        return sorted(_FULL_TREE_NODEIDS)

    def test_every_fragment_names_a_live_module(self):
        missing = [
            frag for frag in self._fragments()
            if not (REPO_ROOT / "tests" / frag.split("::", 1)[0]).is_file()
        ]
        assert not missing, (
            f"{missing} name a test module that no longer exists. The fragment "
            "protects nothing and keeps a phantom module inside "
            "test_test_suite_contract's `marked_files`. Delete the entry."
        )

    def test_every_fragment_resolves_to_exactly_its_target(self):
        dead: list[str] = []
        over: list[tuple[str, list[str]]] = []
        for frag in self._fragments():
            module, _, tail = frag.partition("::")
            path = REPO_ROOT / "tests" / module
            if not path.is_file():
                continue  # reported by the sibling test above
            if not tail:
                continue  # whole-module registration: the file existing IS the target
            # A `[param]` suffix addresses ONE generated case. Resolve the base
            # against the AST and let the param ride along -- pytest builds the
            # id from runtime values, so it is not statically derivable here;
            # test_every_parametrized_fragment_targets_a_parametrized_test below
            # covers the failure this cannot see.
            tail, _param = _split_param(tail)
            tails = _module_nodeid_tails(path)
            # Replicate collection's substring semantics exactly, then compare
            # against what the fragment actually NAMES. A divergence is silent.
            substring_hits = sorted(n for n in tails if tail in n)
            named_hits = sorted(
                n for n in tails if n == tail or n.startswith(tail + "::")
            )
            if not substring_hits:
                dead.append(frag)
            elif substring_hits != named_hits:
                over.append((frag, sorted(set(substring_hits) - set(named_hits))))
        assert not dead, (
            f"{dead} match no test in their module — renamed or deleted. A "
            "fragment matching nothing is a false coverage claim; the release "
            "matrix reads it as protection that is not there."
        )
        assert not over, (
            "these fragments silently mark MORE than they name (collection uses "
            f"`frag in item.nodeid`, which is prefix-open): {over}. Either "
            "register the extra tests deliberately or disambiguate the fragment."
        )

    def test_every_fragment_collects_at_least_one_real_nodeid(self):
        """THE strong oracle: drive real collection, not the AST.

        The AST arms above resolve a fragment's BASE. For a `[param]` fragment
        that is a proxy, and it cannot see the id itself -- pytest builds ids
        from runtime values. Enumerated by the adversarial pass, a param
        fragment dies SILENTLY when `ids=` changes, when argvalues are reshaped
        so pytest auto-numbers, when duplicate ids force a `0`/`1` suffix, or
        when the population drops the row -- base alive, decorator present,
        every AST check green, matching nothing. That is exactly the dead-
        fragment shape `_FULL_TREE_NODEIDS` was hardened against in `3f8252a`,
        reintroduced one granularity down.

        One `--collect-only` answers all of it exactly: 8257 nodeids in ~2.2s,
        and it applies collection's OWN `frag in item.nodeid` semantics rather
        than a model of them. Subprocess (single, whole-suite) rather than
        in-process so a collection error in any module cannot take this test
        down with it.
        """
        import subprocess
        import sys

        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q",
             "-p", "no:cacheprovider", "tests/"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, encoding="utf-8",
        )
        nodeids = [ln.strip() for ln in proc.stdout.splitlines() if "::" in ln]
        assert len(nodeids) > 5000, (
            f"collected only {len(nodeids)} nodeids (rc={proc.returncode}) -- "
            "this oracle would pass vacuously. "
            f"stderr: {proc.stderr.strip()[:300]}"
        )
        unresolved = [
            frag for frag in self._fragments()
            if not any(frag in nid for nid in nodeids)
        ]
        assert not unresolved, (
            f"{unresolved} match no COLLECTED nodeid. For a `[param]` fragment "
            "the id is built from runtime values, so the AST arms above cannot "
            "see this -- they check the base only. A fragment matching nothing "
            "is a false coverage claim the release matrix reads as protection."
        )

    def test_every_parametrized_fragment_is_well_formed(self):
        """A ``[param]`` fragment dies silently if the decorator is removed.

        The base function survives a de-parametrization, so the AST resolution
        above still reports it live while pytest stops generating any nodeid the
        fragment could match -- a fragment that protects nothing, reported as
        protection. Registering at param granularity is deliberate here (2026-08-14):
        ``ESPALIER_MEMORY.md`` is 1 of 10 declared cap sites and the only pruned one,
        so marking the whole test would suppress NINE export-SAFE per-file checks to
        silence one.

        Honest limit: pytest builds param ids from runtime values, so this cannot
        confirm the specific id still exists -- only that the test still produces
        ids at all. A dropped ROW (rather than a dropped decorator) is caught
        instead by whatever derives that population; for the cap sites that is
        ``test_census_covers_every_tracked_file_stating_the_cap``.
        """
        malformed: list[str] = []
        for frag in self._fragments():
            module, _, tail = frag.partition("::")
            if tail and "[" in tail and not tail.endswith("]"):
                malformed.append(frag)
        assert not malformed, (
            f"{malformed} open a `[` without closing it. Collection matches by "
            "plain substring, so an unclosed param id also matches every LONGER "
            "id sharing that prefix -- close the bracket to make it exact."
        )
