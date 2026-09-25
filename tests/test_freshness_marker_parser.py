"""Tests for ``espalier.scanners.freshness.parse_fragment_markers``.

Pins the regex-and-region-tracker boundary cases identified in
TP-56-A: YAML frontmatter exclusion, fenced-code-block exclusion,
duplicate-id raises, bound rejecting leading dash (BC-042). Each
case prevents a specific silent miss — without the frontmatter
exclusion the parser would treat YAML metadata as fragment text;
without the code-fence exclusion every Markdown example in docs
would register as a real fragment; the BC-042 leading-dash
rejection guards against shell-flag-as-bound parser confusion.
"""
from __future__ import annotations

import pytest

from espalier.scanners.freshness import (
    FreshnessError,
    parse_fragment_markers,
)


class TestFragmentMarkerParser:
    def test_parser_extracts_minimal_marker(self):
        text = (
            "Lead-in.\n"
            "<!-- espalier:fragment id=foo bound=a/b.py policy=weekly -->\n"
            "Trailing.\n"
        )
        fragments = parse_fragment_markers(text, source_path="docs/x.md")
        assert len(fragments) == 1
        assert fragments[0].id == "foo"
        assert fragments[0].bound == ("a/b.py",)
        assert fragments[0].policy == "weekly"
        assert fragments[0].source_path == "docs/x.md"
        assert fragments[0].source_line == 2

    def test_parser_extracts_multi_line_marker(self):
        text = (
            "<!-- espalier:fragment id=hook-count\n"
            "     bound=espalier/harness_config.py::CANONICAL_HOOK_WIRING\n"
            "     policy=numeric-contract -->\n"
        )
        fragments = parse_fragment_markers(text)
        assert len(fragments) == 1
        assert fragments[0].id == "hook-count"
        assert fragments[0].bound == (
            "espalier/harness_config.py::CANONICAL_HOOK_WIRING",
        )
        assert fragments[0].policy == "numeric-contract"

    def test_parser_extracts_comma_separated_bound(self):
        text = (
            "<!-- espalier:fragment id=multi "
            "bound=a/b.py,c/d.py::SYM policy=weekly -->\n"
        )
        fragments = parse_fragment_markers(text)
        assert fragments[0].bound == ("a/b.py", "c/d.py::SYM")

    def test_parser_skips_markers_inside_yaml_frontmatter(self):
        text = (
            "---\n"
            "title: Doc\n"
            "<!-- espalier:fragment id=in-yaml bound=a.py policy=weekly -->\n"
            "---\n"
            "Body.\n"
        )
        fragments = parse_fragment_markers(text)
        assert fragments == []

    def test_parser_detects_marker_after_yaml_frontmatter(self):
        text = (
            "---\n"
            "title: Doc\n"
            "---\n"
            "<!-- espalier:fragment id=after bound=a.py policy=weekly -->\n"
        )
        fragments = parse_fragment_markers(text)
        assert len(fragments) == 1
        assert fragments[0].id == "after"

    def test_parser_skips_markers_inside_fenced_code_block(self):
        text = (
            "Lead.\n"
            "```\n"
            "<!-- espalier:fragment id=fenced bound=a.py policy=weekly -->\n"
            "```\n"
            "Trail.\n"
        )
        fragments = parse_fragment_markers(text)
        assert fragments == []

    def test_parser_skips_markers_inside_tilde_fenced_block(self):
        text = (
            "~~~\n"
            "<!-- espalier:fragment id=tilde bound=a.py policy=weekly -->\n"
            "~~~\n"
        )
        fragments = parse_fragment_markers(text)
        assert fragments == []

    def test_parser_raises_on_duplicate_fragment_id(self):
        text = (
            "<!-- espalier:fragment id=dup bound=a.py policy=weekly -->\n"
            "<!-- espalier:fragment id=dup bound=b.py policy=weekly -->\n"
        )
        with pytest.raises(FreshnessError, match="duplicate fragment id"):
            parse_fragment_markers(text)

    def test_parser_rejects_bound_starting_with_dash(self):
        text = (
            "<!-- espalier:fragment id=danger "
            "bound=-no-such-flag policy=weekly -->\n"
        )
        with pytest.raises(FreshnessError, match="BC-042"):
            parse_fragment_markers(text)

    def test_parser_raises_on_missing_field(self):
        text = "<!-- espalier:fragment id=only bound=a.py -->\n"
        with pytest.raises(FreshnessError, match="missing fields"):
            parse_fragment_markers(text)

    def test_parser_raises_on_unterminated_marker(self):
        text = "<!-- espalier:fragment id=open bound=a.py policy=weekly\n"
        with pytest.raises(FreshnessError, match="unterminated"):
            parse_fragment_markers(text)
