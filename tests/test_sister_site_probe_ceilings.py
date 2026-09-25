"""TP-107: ceiling pins for sister-site probe's "frozen list" surfaces.

Three numeric pins surface as ``EXPECTED_*`` constants in
``tests/_surface_expected.py``; each is asserted here against a live
read of the underlying source. Reasoning:

- ``EXPECTED_OPT_OUT_CEILING`` (value in ``tests/_surface_expected.py`` —
  deliberately not restated here; a hand-copied number is a drift source and
  nothing pins this docstring) — the escape hatch must not become
  steady-state. Live count reads ``# sister-site: ok`` markers above
  every non-class module-level node (assignment, import, constant,
  function) AND every non-dunder class method in ``_default_scan_targets``
  — the exact surface the probe's detectors consult. Grandfather-frozen
  at the current population, not 0: the prior walk counted only
  ``_collect_sites`` FunctionDef/method sites, so it was blind to the live
  constant/assign markers and passed vacuously at 0.
- ``EXPECTED_GRANDFATHER_CEILING = 59`` — TP-105 froze the unit-tagged
  grandfather tuple in ``conftest._MARKER_RULES``. Live count via AST.
- ``EXPECTED_HOOK_UTILS_PUBLIC_COUNT = 11`` — asymmetric: shrinkage is
  suspicious; growth is fine. Live count via
  ``test_hook_helper_consolidation._hook_utils_public_names``.

Without these pins, the three "frozen list" surfaces drift silently in
prose comments but not in mechanical contract.

Test naming follows ``test_{specific_behavior}`` per docs/CONVENTIONS.md.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from _surface_expected import (
    EXPECTED_ALIAS_MISS_CEILING,
    EXPECTED_CONSTANT_CLIQUE_CEILING,
    EXPECTED_GRANDFATHER_CEILING,
    EXPECTED_HOOK_UTILS_PUBLIC_COUNT,
    EXPECTED_OPT_OUT_CEILING,
)

REPO_ROOT = Path(__file__).parent.parent
PROBE_PATH = REPO_ROOT / "tools" / "cc"
sys.path.insert(0, str(PROBE_PATH))
from sister_site_probe import (  # noqa: E402
    _collect_sites,
    _default_scan_targets,
    _opt_out_marker_above,
    probe_compression_debt,
)


def _live_opt_out_count(targets: list[Path] | None = None) -> int:
    """Count ``# sister-site: ok`` markers across the surface the probe's
    detectors actually consult — the honest opt-out population.

    Two arms, together the exact set of sites where a marker suppresses a
    real finding:

    - every module-level node that is NOT a class (assignment, import,
      constant, function) — the alias/canon/constant detectors iterate
      module-level ``tree.body``; a marker above a bare ``class`` line
      suppresses nothing and is intentionally not counted;
    - every non-dunder class method — mirroring ``_collect_sites``'s own
      one-level ``ClassDef`` recursion (``FunctionDef``, ``__dunder__``
      skipped) exactly, so the counter matches the surface the clique
      detector honors (not a looser superset).

    The prior version counted only ``_collect_sites`` (function/method)
    sites, so it was blind to the live markers above assignment/constant
    sites and returned a vacuous 0 while 20 real markers existed. Reuses
    the probe's own ``_opt_out_marker_above`` so the marker grammar stays
    single-sourced (re-implementing it would itself be a sister-site
    violation). ``test_opt_out_counter_covers_the_clique_detector_surface``
    binds the method arm to ``_collect_sites`` so a future detector-reach
    expansion cannot silently outrun this counter (the hollow-gate class
    this counter exists to close, reborn one level deeper).

    ``targets`` defaults to the live scan set; a test passes an explicit
    fixture list to pin the counter's reach directly.
    """
    if targets is None:
        targets = _default_scan_targets(REPO_ROOT)
    count = 0
    for path in targets:
        try:
            src = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = src.splitlines()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if (
                        isinstance(sub, ast.FunctionDef)
                        and not sub.name.startswith("__")
                        and _opt_out_marker_above(lines, sub.lineno) is not None
                    ):
                        count += 1
            elif _opt_out_marker_above(lines, node.lineno) is not None:
                count += 1
    return count


def _live_grandfather_count() -> int:
    """Count entries in the unit-tagged grandfather tuple in conftest.

    Reads ``tests/conftest.py`` via AST and finds the ``_MARKER_RULES``
    list; returns the length of the tuple whose marker string is
    ``"unit"``.
    """
    tree = ast.parse((REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign):
            continue
        if not (isinstance(node.target, ast.Name)
                and node.target.id == "_MARKER_RULES"):
            continue
        for elem in node.value.elts:
            if not (isinstance(elem, ast.Tuple) and len(elem.elts) == 2):
                continue
            names_tuple, marker = elem.elts
            if (isinstance(marker, ast.Constant)
                    and marker.value == "unit"
                    and isinstance(names_tuple, ast.Tuple)):
                return len(names_tuple.elts)
    raise AssertionError(
        "Could not locate unit-tagged tuple in conftest._MARKER_RULES — "
        "ceiling test must be updated for new conftest shape."
    )


@pytest.mark.security
class TestSisterSiteProbeCeilings:
    def test_opt_out_marker_count_does_not_grow(self):
        live = _live_opt_out_count()
        assert live <= EXPECTED_OPT_OUT_CEILING, (
            f"Opt-out marker count rose to {live} (ceiling: "
            f"{EXPECTED_OPT_OUT_CEILING}). Either remove the new opt-out "
            f"and compress the duplicate, or deliberately raise "
            f"EXPECTED_OPT_OUT_CEILING in tests/_surface_expected.py with "
            f"a justification — the escape hatch should not become "
            f"steady-state."
        )

    def test_opt_out_counter_sees_assign_import_and_method_markers(self, tmp_path):
        """The opt-out counter must see markers on EVERY surface where a
        ``# sister-site: ok`` marker suppresses a finding — module-level
        assign/import (the alias/canon surface) AND class methods (the
        clique surface). Earns the red on both blind spots: a
        ``tree.body``-only walk misses the method; a ``_collect_sites``-only
        walk misses assign/import. Neither sub-walk alone is a faithful
        population count — the union is.
        """
        fixture = tmp_path / "marked_module.py"
        fixture.write_text(
            "import _hook_utils\n"
            "# sister-site: ok deliberate assign rename\n"
            "_my_normalize = _hook_utils.normalize_path\n"
            "# sister-site: ok deliberate import rename\n"
            "from _hook_utils import resolve_project_root as _find_root\n"
            "class C:\n"
            "    # sister-site: ok deliberate method opt-out\n"
            "    def m(self):\n"
            "        return 1\n",
            encoding="utf-8",
        )
        union = _live_opt_out_count([fixture])

        src = fixture.read_text(encoding="utf-8")
        lines = src.splitlines()
        tree = ast.parse(src)
        tree_body_only = sum(
            1 for n in tree.body
            if _opt_out_marker_above(lines, n.lineno) is not None
        )
        collect_sites_only = sum(
            1 for s in _collect_sites(fixture, tmp_path)
            if s.opt_out_reason is not None
        )

        assert union == 3, (
            f"union counter should see assign+import+method = 3; got {union}"
        )
        assert tree_body_only == 2, (
            f"tree.body-only walk is blind to the class-method marker "
            f"(should see assign+import = 2); got {tree_body_only}"
        )
        assert collect_sites_only == 1, (
            f"_collect_sites-only walk is blind to assign/import markers "
            f"(should see the method = 1); got {collect_sites_only}"
        )

    def test_opt_out_counter_covers_the_clique_detector_surface(self):
        """Mechanical guard on the counter's own reach: the live opt-out
        count must never fall BELOW the clique detector's honored marker
        surface (``_collect_sites`` sites carrying an ``opt_out_reason``).
        Green today (0 live function/method markers); it reds the day a
        detector-reach expansion — e.g. ``_collect_sites`` learning to
        descend nested classes or collect async methods — starts honoring
        markers this counter's one-level walk cannot see. That is the
        'measures the wrong population' hollow gate one level deeper, the
        exact class this counter exists to close, so it must not be able to
        drift back in silently.
        """
        detector_honored = sum(
            1
            for path in _default_scan_targets(REPO_ROOT)
            for site in _collect_sites(path, REPO_ROOT)
            if site.opt_out_reason is not None
        )
        live = _live_opt_out_count()
        assert live >= detector_honored, (
            f"opt-out counter ({live}) fell below the clique detector's "
            f"honored marker surface ({detector_honored}) — a marker the "
            f"detector suppresses on is uncounted. Extend _live_opt_out_count "
            f"to match _collect_sites's reach (then re-derive the ceiling)."
        )

    def test_grandfather_tuple_does_not_grow(self):
        live = _live_grandfather_count()
        assert live <= EXPECTED_GRANDFATHER_CEILING, (
            f"Unit grandfather tuple grew to {live} entries (ceiling: "
            f"{EXPECTED_GRANDFATHER_CEILING}). New tests must be "
            f"deliberately classified into one of the existing tagged "
            f"tuples in conftest._MARKER_RULES, not added to the "
            f"grandfather list. If the addition is intentional, lower the "
            f"ceiling first — the tuple is meant to chip down, not grow."
        )

    def test_hook_utils_public_names_does_not_shrink(self):
        # Re-derive locally to avoid coupling to the consolidation test's
        # import side effects.
        tree = ast.parse(
            (REPO_ROOT / "tools" / "cc" / "hooks" / "_hook_utils.py")
            .read_text(encoding="utf-8")
        )
        live = sum(
            1 for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and not node.name.startswith("_")
        )
        assert live >= EXPECTED_HOOK_UTILS_PUBLIC_COUNT, (
            f"_hook_utils.py public-API surface shrank to {live} names "
            f"(floor: {EXPECTED_HOOK_UTILS_PUBLIC_COUNT}). Removing an "
            f"exported helper leaves hooks free to define private copies "
            f"with subtly different bodies — the helper-shadow contract "
            f"can no longer catch them. If the removal is intentional, "
            f"lower EXPECTED_HOOK_UTILS_PUBLIC_COUNT in "
            f"tests/_surface_expected.py with a justification."
        )

    def test_constant_clique_count_does_not_grow(self):
        """TP-108: WARN-blocking constant cliques must stay at the
        ceiling (0). DIVERGENT cliques (e.g. ``__all__`` per-module
        with different contents) are advisory and excluded from the
        block count, mirroring the function-clique policy.
        """
        report = probe_compression_debt([REPO_ROOT])
        blocking = [
            c for c in report.constant_cliques
            if c.severity == "WARN" and not c.divergent
        ]
        live = len(blocking)
        assert live <= EXPECTED_CONSTANT_CLIQUE_CEILING, (
            f"WARN-blocking constant cliques rose to {live} (ceiling: "
            f"{EXPECTED_CONSTANT_CLIQUE_CEILING}). Cliques: "
            f"{[(c.name, len(c.sites)) for c in blocking]}. Either "
            f"compress the duplicate constant via a shared SoT module "
            f"(e.g. _hook_utils) or deliberately raise "
            f"EXPECTED_CONSTANT_CLIQUE_CEILING in tests/_surface_expected.py "
            f"with a justification."
        )

    def test_alias_miss_count_does_not_grow(self):
        """TP-341: alias-misses were closed to 0 and flipped to blocking; the
        count must not re-accrue. A new short-name alias must adopt the canonical
        export name (`_X = M.X`) or carry a `# sister-site: ok` marker."""
        report = probe_compression_debt([REPO_ROOT])
        live = len(report.alias_misses)
        assert live <= EXPECTED_ALIAS_MISS_CEILING, (
            f"alias-misses rose to {live} (ceiling: {EXPECTED_ALIAS_MISS_CEILING}). "
            f"Sites: {[(a.file, a.lineno, a.lhs_name) for a in report.alias_misses]}. "
            f"Adopt the canonical export name locally (`_X = M.X`) or add a "
            f"`# sister-site: ok <reason>` marker above the alias."
        )
