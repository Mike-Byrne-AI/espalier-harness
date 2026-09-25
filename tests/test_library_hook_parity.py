"""TP-59 sub-task 1-G: AST parity test for mirrored library/hook modules.

The standalone-execution invariant for `tools/cc/` (zero `espalier`
imports) forces duplication of defensive constants and helpers across a
library-side copy under `espalier/` and a hook-side copy under
`tools/cc/`. This test asserts the duplication stays in sync.

Strategy: parse both copies via `ast`, extract assigned constants, and
compare values for the named defensive symbols. Module formatting
(import order, docstring wording, comment placement) is intentionally
NOT compared -- only the named symbols that constitute the defensive
contract.

See `docs/CONVENTIONS.md` section "Library / hook parity (TP-59)" for
the rules these mirrors must obey.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _extract_module_constants(path: Path) -> dict[str, object]:
    """Return ``{name: value}`` for every top-level ``Name = literal``
    assignment in the module. Only ``Constant`` RHS values are
    captured -- expressions are skipped (they are not the kind of
    parity-load-bearing values this test asserts on).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                out[target.id] = node.value.value
    return out


class TestBlueprintLimitsParity:
    """The 128 KB blueprint cap is the canonical mirror-pair: both
    ``espalier/_blueprint_limits.py`` and ``tools/cc/_blueprint_limits.py``
    must export an identical ``BLUEPRINT_MAX_SIZE`` constant. Drift
    here means readers on one side accept oversize blueprints the other
    side rejects -- exactly the BC-038 footgun this pack closes."""

    LIBRARY = REPO_ROOT / "espalier" / "_blueprint_limits.py"
    HOOK = REPO_ROOT / "tools" / "cc" / "_blueprint_limits.py"

    def test_both_mirror_modules_exist(self):
        assert self.LIBRARY.is_file(), f"missing library-side mirror: {self.LIBRARY}"
        assert self.HOOK.is_file(), f"missing hook-side mirror: {self.HOOK}"

    def test_blueprint_max_size_value_parity(self):
        lib = _extract_module_constants(self.LIBRARY)
        hook = _extract_module_constants(self.HOOK)
        assert "BLUEPRINT_MAX_SIZE" in lib, (
            "library-side _blueprint_limits.py must export BLUEPRINT_MAX_SIZE"
        )
        assert "BLUEPRINT_MAX_SIZE" in hook, (
            "hook-side _blueprint_limits.py must export BLUEPRINT_MAX_SIZE"
        )
        assert lib["BLUEPRINT_MAX_SIZE"] == hook["BLUEPRINT_MAX_SIZE"], (
            f"BLUEPRINT_MAX_SIZE drift: library={lib['BLUEPRINT_MAX_SIZE']!r} "
            f"hook={hook['BLUEPRINT_MAX_SIZE']!r}. Both copies must be "
            f"updated in the same commit."
        )

    def test_blueprint_retention_value_parity(self):
        """TP-176 W2-4: the retention bounds the prune uses must match
        across the mirror so library and hook reclaim identically."""
        lib = _extract_module_constants(self.LIBRARY)
        hook = _extract_module_constants(self.HOOK)
        for const in ("BLUEPRINT_RETENTION", "BLUEPRINT_MIN_PRUNE_AGE_S", "BLUEPRINT_STUB_MAX_BYTES"):
            assert const in lib, f"library-side _blueprint_limits.py must export {const}"
            assert const in hook, f"hook-side _blueprint_limits.py must export {const}"
            assert lib[const] == hook[const], (
                f"{const} drift: library={lib[const]!r} hook={hook[const]!r}. "
                f"Both copies must be updated in the same commit."
            )

    def test_both_modules_reference_the_other_in_docstring(self):
        """Reader-discovery contract: anyone reading one mirror must
        see a pointer to the other in the docstring header. Stops the
        long-tail footgun of a future contributor editing only one
        side because they did not know the other existed."""
        lib_doc = ast.get_docstring(ast.parse(self.LIBRARY.read_text(encoding="utf-8"))) or ""
        hook_doc = ast.get_docstring(ast.parse(self.HOOK.read_text(encoding="utf-8"))) or ""
        assert "tools/cc/_blueprint_limits.py" in lib_doc, (
            f"library-side docstring must reference the hook-side mirror; "
            f"got: {lib_doc[:200]!r}"
        )
        assert "espalier/_blueprint_limits.py" in hook_doc, (
            f"hook-side docstring must reference the library-side mirror; "
            f"got: {hook_doc[:200]!r}"
        )


class TestSelfHostDetectorConvergence:
    """``is_self_host_repo`` must agree byte-for-byte on every fixture.

    TP-67 (BC-035) hardened the library to 5 signals: ``espalier/`` dir,
    ``tools/cc/`` dir, ``bench/`` dir, pyproject name match, and a
    SHA-256 pin on ``tools/cc/hooks/write_guard.py``'s first 200 bytes.
    The hook side initially checked only 3 of those 5 signals (the SHA
    pin lived in ``espalier/_self_host_fingerprint.py`` which hooks
    cannot import per the isolation rule). The asymmetry meant a
    spoofed pyproject + empty stub directories blocked the library
    detector but allowed the hook detector to mark the repo as
    self-host -- the elevation surface where hooks fire.

    TP-76 closes the gap with a hook-side constant mirror at
    ``tools/cc/hooks/_self_host_fingerprint.py`` (byte-equality
    enforced by ``tests/test_self_host_fingerprint_parity.py``) and a
    5-signal hook-side detector. This class asserts both detectors
    produce the same boolean on six fixture shapes covering each
    failure mode plus the all-signals-present happy path.

    Scope (per TP-76 0-A revision): is_self_host_repo only. The
    sister functions (harness_protected_prefixes etc.) have no
    library-side mirror to converge with -- separate concern.
    """

    @staticmethod
    def _load_hook_side():
        """Load ``_hook_utils`` so it can find its ``_self_host_fingerprint``
        sibling. Inserts ``tools/cc/hooks/`` on sys.path the same way the
        live hook scripts do, then loads via importlib."""
        import importlib.util
        import sys
        hooks_dir = REPO_ROOT / "tools" / "cc" / "hooks"
        if str(hooks_dir) not in sys.path:
            sys.path.insert(0, str(hooks_dir))
        spec = importlib.util.spec_from_file_location(
            "_hook_utils_under_test",
            hooks_dir / "_hook_utils.py",
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        return mod

    @staticmethod
    def _build_fixture(tmp_path: Path, shape: str) -> None:
        """Build a fixture matching the named shape. Each shape exercises
        a specific combination of the 5 canonical signals; only the
        all-pristine shape should detect as self-host."""
        if shape == "empty_dir":
            return
        if shape == "espalier_dir_only":
            (tmp_path / "espalier").mkdir()
            return
        if shape == "espalier_plus_toolscc":
            (tmp_path / "espalier").mkdir()
            (tmp_path / "tools" / "cc").mkdir(parents=True)
            return
        if shape == "spoofed_name_no_bench":
            (tmp_path / "espalier").mkdir()
            (tmp_path / "tools" / "cc").mkdir(parents=True)
            (tmp_path / "pyproject.toml").write_text(
                '[project]\nname = "espalier-harness"\n', encoding="utf-8"
            )
            return
        if shape == "spoofed_name_with_bench_no_sha":
            # BC-035 attack: all four name/dir signals satisfied but
            # write_guard.py content is attacker-controlled (SHA mismatch).
            (tmp_path / "espalier").mkdir()
            (tmp_path / "tools" / "cc" / "hooks").mkdir(parents=True)
            (tmp_path / "tools" / "cc" / "hooks" / "write_guard.py").write_text(
                "# arbitrary attacker content\n", encoding="utf-8"
            )
            (tmp_path / "bench").mkdir()
            (tmp_path / "pyproject.toml").write_text(
                '[project]\nname = "espalier-harness"\n', encoding="utf-8"
            )
            return
        if shape == "all_5_signals_pristine_write_guard":
            import shutil
            (tmp_path / "espalier").mkdir()
            (tmp_path / "tools" / "cc" / "hooks").mkdir(parents=True)
            shutil.copy2(
                REPO_ROOT / "tools" / "cc" / "hooks" / "write_guard.py",
                tmp_path / "tools" / "cc" / "hooks" / "write_guard.py",
            )
            (tmp_path / "bench").mkdir()
            (tmp_path / "pyproject.toml").write_text(
                '[project]\nname = "espalier-harness"\n', encoding="utf-8"
            )
            return
        raise AssertionError(f"unknown fixture shape: {shape}")

    def test_detectors_agree_on_every_fixture(self, tmp_path: Path) -> None:
        from espalier.surface_contract import is_self_host_repo as lib_is_self_host
        hook = self._load_hook_side()

        cases = [
            ("empty_dir", False),
            ("espalier_dir_only", False),
            ("espalier_plus_toolscc", False),
            ("spoofed_name_no_bench", False),
            ("spoofed_name_with_bench_no_sha", False),  # BC-035 attack
            ("all_5_signals_pristine_write_guard", True),
        ]
        for shape, expected in cases:
            shape_dir = tmp_path / shape
            shape_dir.mkdir()
            self._build_fixture(shape_dir, shape)
            lib_result = lib_is_self_host(shape_dir)
            hook_result = hook.is_self_host_repo(shape_dir)
            assert lib_result == expected, (
                f"shape={shape!r}: library lib_is_self_host returned "
                f"{lib_result}, expected {expected}"
            )
            assert hook_result == expected, (
                f"shape={shape!r}: hook is_self_host_repo returned "
                f"{hook_result}, expected {expected}"
            )


class TestAJMutationToolsParity:
    """Hook-side ``_AJ_MUTATION_TOOLS_TOKENS`` in
    ``tools/cc/cognitive_blueprint.py`` must be byte-equal in MEMBERSHIP
    to the library-side ``MUTATION_TOOLS_TOKENS`` in
    ``espalier/harness_config.py``. Per the architecture rule the hook
    cannot import from ``espalier``; the dual-witness contract is pinned
    by this set-equality assertion instead.

    Sister-shape to
    ``tests/test_hook_matcher_precision.py::test_mutation_tools_dual_witness``,
    which pins ``MUTATION_TOOLS_TOKENS`` against
    ``tools/cc/hooks/_hook_utils.py::MUTATION_TOOLS`` (a different
    frozenset in a different file).
    """

    def test_aj_mutation_tools_tokens_pinned_to_library(self) -> None:
        from espalier.harness_config import MUTATION_TOOLS_TOKENS

        import importlib.util as _util
        spec = _util.spec_from_file_location(
            "_hook_cb_for_parity",
            REPO_ROOT / "tools" / "cc" / "cognitive_blueprint.py",
        )
        hook_cb = _util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(hook_cb)

        assert frozenset(hook_cb._AJ_MUTATION_TOOLS_TOKENS) == frozenset(
            MUTATION_TOOLS_TOKENS
        ), (
            "drift between hook-side _AJ_MUTATION_TOOLS_TOKENS "
            f"({set(hook_cb._AJ_MUTATION_TOOLS_TOKENS)!r}) and "
            f"library-side MUTATION_TOOLS_TOKENS "
            f"({set(MUTATION_TOOLS_TOKENS)!r}). The hook-side tuple is "
            f"a manual copy and must be updated when the library tuple "
            f"changes."
        )


# ── twin-registry completeness ────────────────────────────────────────
#
# The `## Library / hook parity` table in docs/CONVENTIONS.md is
# hand-maintained, and nothing asserted it against the real population of
# duplicated modules -- the "a presence check cannot see the absence"
# class. It has drawn blood: the retired findings corpus (record branch,
# b3e36ae:docs/known-findings.md) records a MAJOR where
# `_truncate_to_cap` was fixed in the engine copy and never in the hook
# copy, so shape rule 3 ("bug fixes must land in BOTH copies in the same
# commit") had no mechanical reader.

_TWIN_REGISTRY_EXEMPT = frozenset({
    "__init__.py",   # package namespace marker, not a mirrored implementation
})
_PARITY_SECTION_RE = re.compile(
    r"^## Library / hook parity\b(.*?)(?=^## )", re.MULTILINE | re.DOTALL
)


def _parity_registry_section(conventions: str) -> str:
    """The `## Library / hook parity` section body of docs/CONVENTIONS.md.

    Scoped deliberately: `cognitive_blueprint` (and other twin basenames)
    appear all over the document in unrelated prose -- 14 times, measured --
    so a whole-file substring haystack makes the assertion below pass
    vacuously and it can never earn a red.
    """
    m = _PARITY_SECTION_RE.search(conventions)
    assert m, "docs/CONVENTIONS.md has no `## Library / hook parity` section"
    return m.group(1)


@pytest.mark.skipif(
    not (REPO_ROOT / "tools" / "cc").is_dir(),
    reason="tools/cc/ absent -- no twin population to check (not a source checkout)",
)
def test_every_engine_hook_twin_is_named_in_the_conventions_registry():
    """The twin registry's population is the FILESYSTEM, not a hand-kept table.

    A newly duplicated engine<->hook module pair silently never gets a
    registry row, and nothing reds -- so shape rule 3 has no reader for it.
    Exemptions are explicit and carry a reason: an exclusion inside a
    mechanical gate is itself an untested assertion.
    """
    conventions = (REPO_ROOT / "docs" / "CONVENTIONS.md").read_text(encoding="utf-8")
    section = _parity_registry_section(conventions)
    esp = {p.name for p in (REPO_ROOT / "espalier").rglob("*.py") if "_vendor" not in str(p)}
    cc = {p.name for p in (REPO_ROOT / "tools" / "cc").rglob("*.py")}
    twins = sorted((esp & cc) - _TWIN_REGISTRY_EXEMPT)
    assert twins, "no engine<->hook twins discovered -- the walk broke"
    unregistered = [t for t in twins if t.removesuffix(".py") not in section]
    assert not unregistered, (
        "engine<->hook twin modules with no `## Library / hook parity` registry row "
        f"in docs/CONVENTIONS.md -- add a row or an exemption with a reason: {unregistered}"
    )


def test_parity_section_slice_stops_at_the_next_heading():
    # The slice is what makes the pin above non-vacuous. If the lookahead
    # broke and the section ran to EOF, the haystack would become the whole
    # file and every twin would match by luck.
    doc = "## Library / hook parity\nIN_SECTION\n\n## Next thing\nOUT_OF_SECTION\n"
    section = _parity_registry_section(doc)
    assert "IN_SECTION" in section
    assert "OUT_OF_SECTION" not in section
