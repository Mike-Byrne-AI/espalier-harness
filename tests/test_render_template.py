"""Render-time contract tests for cli.render_canonical_template output.

Static-doc tests (test_documented_claims.py) audit this repo's
docs. Rendered output is an unaudited surface -- adopter repos
get the rendered string, not the test-asserted one. This module
binds the rendered output to the external protocol pin.

Marker: inherits `contract` from conftest.py::_MARKER_RULES via
the `stem.startswith("test_render_")` match on the existing
`"test_render"` rule. If that rule is renamed or removed, add an
explicit `"test_render_template"` entry so this file does not
silently demote to `unit`.
"""
import pytest

from espalier.cli import render_canonical_template


class TestChannelXORContract:
    """Hook exit codes in rendered CLAUDE.md must match cc-hook-protocol.md."""

    @pytest.fixture
    def rendered(self) -> str:
        return render_canonical_template("claude")

    def test_forbidden_phrase_absent(self, rendered: str) -> None:
        """`2 = block (JSON on stdout)` is the wrong contract -- must not
        appear in rendered output."""
        assert "2 = block (JSON on stdout)" not in rendered
        assert "exit 2 (JSON" not in rendered

    def test_correct_contract_present(self, rendered: str) -> None:
        """Channel-XOR contract must be present. The rendered string
        backticks each exit-code digit (`0`, `2`, `1`) so the visible
        markdown matches the cc-hook-protocol.md SoT verbatim."""
        assert "`0` = allow OR structured channel" in rendered
        assert "`2` = simple block" in rendered
        assert "no stdout JSON" in rendered


class TestRenderedTemplateNumericClaims:
    """All numeric claims in rendered CLAUDE.md must bind to the same
    SoTs that test_documented_claims.py audits for the static doc.

    Static-doc tests audit THIS repo's files; the rendered template
    is what adopters see. The template body has multiple numeric
    claims; each needs a binding here.
    """

    @pytest.fixture
    def rendered(self) -> str:
        return render_canonical_template("claude")

    def test_hook_count_matches_canonical(self, rendered: str) -> None:
        """Rendered template's hook count must match
        surface_contract.get_canonical_hook_scripts()."""
        from espalier.surface_contract import get_canonical_hook_scripts
        expected = len(get_canonical_hook_scripts())
        assert str(expected) in rendered, (
            f"rendered template missing hook count {expected}"
        )

    def test_reflect_threshold_matches_source(self, rendered: str) -> None:
        """The rendered "every Nth source write" claim must match the
        actual modulus in tools/cc/hooks/reflect_trigger.py. Source uses
        a hardcoded `count % 10 == 0` (no named constant); we grep the
        live file to derive the SoT rather than re-hardcoding here."""
        import re
        from pathlib import Path
        source = Path("tools/cc/hooks/reflect_trigger.py").read_text(encoding="utf-8")
        match = re.search(r"count\s*%\s*(\d+)\s*==\s*0", source)
        assert match, "could not locate reflect modulus in reflect_trigger.py"
        modulus = match.group(1)
        assert f"every {modulus}th source write" in rendered, (
            f"rendered template's reflect-threshold claim does not match "
            f"source modulus {modulus}"
        )
