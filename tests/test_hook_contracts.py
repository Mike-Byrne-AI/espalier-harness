"""Tests for hook timing contract — espalier/hook_contract.py and its standalone copy.

Verifies:
- The Stop timing invariant: OUTER >= INNER + MARGIN.
- The two constant files (_hook_contract.py and hook_contract.py) are in sync.
- The settings generator emits STOP_OUTER_TIMEOUT, not a stray literal.
- stop_gate.py uses STOP_INNER_BUDGET for its pytest subprocess.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path


from espalier import hook_contract
from espalier.cli import _build_settings_json

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
STOP_GATE = HOOKS_DIR / "stop_gate.py"
_HOOK_CONTRACT = HOOKS_DIR / "_hook_contract.py"


# ── Invariant: timing contract ───────────────────────────────────────────────


class TestStopTimingInvariant:
    def test_outer_gte_inner_plus_margin(self):
        assert hook_contract.STOP_OUTER_TIMEOUT >= (
            hook_contract.STOP_INNER_BUDGET + hook_contract.STOP_SAFETY_MARGIN
        ), (
            f"STOP_OUTER_TIMEOUT ({hook_contract.STOP_OUTER_TIMEOUT}) must be >= "
            f"STOP_INNER_BUDGET ({hook_contract.STOP_INNER_BUDGET}) + "
            f"STOP_SAFETY_MARGIN ({hook_contract.STOP_SAFETY_MARGIN})"
        )

    def test_safety_margin_positive(self):
        assert hook_contract.STOP_SAFETY_MARGIN > 0

    def test_inner_budget_positive(self):
        assert hook_contract.STOP_INNER_BUDGET > 0

    def test_outer_timeout_positive(self):
        assert hook_contract.STOP_OUTER_TIMEOUT > 0


# ── Sync: espalier/hook_contract.py matches tools/cc/hooks/_hook_contract.py ──


class TestConstantSync:
    def _load_standalone(self) -> dict:
        """Load _hook_contract.py values without importing it (isolation)."""
        text = _HOOK_CONTRACT.read_text(encoding="utf-8")
        tree = ast.parse(text)
        values: dict = {}
        for node in ast.walk(tree):
            # Handle plain assignments: NAME = value
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                        values[target.id] = node.value.value
            # Handle annotated assignments: NAME: type = value
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and isinstance(node.value, ast.Constant):
                    values[node.target.id] = node.value.value
        return values

    def test_stop_outer_timeout_in_sync(self):
        standalone = self._load_standalone()
        assert standalone.get("STOP_OUTER_TIMEOUT") == hook_contract.STOP_OUTER_TIMEOUT

    def test_stop_inner_budget_in_sync(self):
        standalone = self._load_standalone()
        assert standalone.get("STOP_INNER_BUDGET") == hook_contract.STOP_INNER_BUDGET

    def test_stop_safety_margin_in_sync(self):
        standalone = self._load_standalone()
        assert standalone.get("STOP_SAFETY_MARGIN") == hook_contract.STOP_SAFETY_MARGIN


# ── Settings generator uses constant, not stray literal ─────────────────────


class TestSettingsGeneratorUsesConstant:
    def test_stop_timeout_equals_outer_constant(self):
        settings = _build_settings_json()
        stop_hooks = settings["hooks"]["Stop"][0]["hooks"]
        assert len(stop_hooks) == 1
        assert stop_hooks[0]["timeout"] == hook_contract.STOP_OUTER_TIMEOUT

    def test_no_stray_literal_ten_for_stop(self):
        """The cli.py Stop entry must not use the old stale literal 10."""
        cli_src = (REPO_ROOT / "espalier" / "cli.py").read_text(encoding="utf-8")
        # Look for the Stop section and assert it does not contain '"timeout": 10'
        # adjacent to stop_gate references.
        stop_section_match = re.search(
            r'"Stop".*?"stop_gate\.py".*?}', cli_src, re.DOTALL
        )
        if stop_section_match:
            stop_section = stop_section_match.group(0)
            assert '"timeout": 10' not in stop_section, (
                "Stop entry in cli.py still contains stray literal 10"
            )


# ── stop_gate.py uses STOP_INNER_BUDGET ─────────────────────────────────────


class TestStopGateUsesContract:
    def test_stop_gate_imports_hook_contract(self):
        """stop_gate.py must import from _hook_contract, not hardcode a timeout."""
        src = STOP_GATE.read_text(encoding="utf-8")
        assert "_hook_contract" in src or "STOP_INNER_BUDGET" in src

    def test_stop_gate_no_stray_literal_sixty(self):
        """stop_gate.py must not have a bare timeout=60 literal after Pack 4."""
        src = STOP_GATE.read_text(encoding="utf-8")
        assert "timeout=60" not in src, (
            "stop_gate.py still has stray timeout=60 literal; should use STOP_INNER_BUDGET"
        )


# ── post-v0.6.6: stdin-safety source-level contract ──────────────────────────


class TestStdinSafetyContract:
    """Every canonical hook script must consume stdin via the shared
    ``_hook_utils.read_stdin_safely`` helper, never via inline
    ``json.load(sys.stdin)``.

    The migration to the helper landed in v0.6.6 (BOM bypass + UTF-8
    fail-open sister-site sweep). This contract prevents a future hook
    author from re-introducing the inline pattern that left the helper
    unreached.
    """

    def test_no_hook_uses_inline_json_load_stdin(self):
        from espalier.surface_contract import get_canonical_hook_scripts

        offenders: list[str] = []
        for hook_name in get_canonical_hook_scripts():
            hook_path = HOOKS_DIR / hook_name
            src = hook_path.read_text(encoding="utf-8")
            # Allow the pattern to appear inside a docstring or comment
            # (cf. the helper's own docstring at _hook_utils.py — which
            # references the pattern as historical context). We only
            # flag bare-code occurrences. The cheap discriminator: the
            # string `json.load(sys.stdin)` appearing OUTSIDE a triple-
            # quoted block. Since the helper docstring is in
            # _hook_utils.py (not a canonical hook) and these scripts
            # don't have multi-line docstrings referencing the literal
            # form, a flat substring search is sufficient.
            if "json.load(sys.stdin)" in src:
                offenders.append(hook_name)

        assert not offenders, (
            f"Found hooks still using inline json.load(sys.stdin) "
            f"instead of the shared _hook_utils.read_stdin_safely "
            f"helper: {offenders!r}. The post-v0.6.6 migration "
            f"replaced this pattern across all 10 hooks; "
            f"re-introducing it bypasses the BOM-aware decode and the "
            f"unified UTF-8 fail-open handling."
        )

    def test_every_hook_calls_read_stdin_safely(self):
        """Every canonical hook script must reference
        ``read_stdin_safely``. Catches a hook that deletes the helper
        call but doesn't replace it with anything (regression: silently
        misses the stdin payload)."""
        from espalier.surface_contract import get_canonical_hook_scripts

        missing: list[str] = []
        for hook_name in get_canonical_hook_scripts():
            hook_path = HOOKS_DIR / hook_name
            src = hook_path.read_text(encoding="utf-8")
            if "read_stdin_safely" not in src:
                missing.append(hook_name)

        assert not missing, (
            f"Hooks missing a call to read_stdin_safely: {missing!r}. "
            f"Every canonical hook must consume stdin via the shared "
            f"helper for BOM + UTF-8 safety."
        )
