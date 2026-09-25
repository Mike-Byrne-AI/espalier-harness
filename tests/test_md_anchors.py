"""Unit contract for the heading slugifier that makes ``#fragment`` links checkable.

The fixtures below are not decoration. A slugifier that is subtly wrong reports live
links as broken, and a guard that cries wolf gets an allowlist bolted on and then gets
ignored -- so the cases that could plausibly go wrong are pinned individually, each
with the reason it is here.
"""
# pytest-marker: default-unit  (pure-function string tests; no subprocess, no tmp tree)
from __future__ import annotations

import pytest

from _md_anchors import heading_anchors, slug_variants, slugify


class TestSlugify:
    @pytest.mark.parametrize(
        "heading,expected",
        [
            ("Simple heading", "simple-heading"),
            ("Trailing punctuation!", "trailing-punctuation"),
            ("Mixed CASE Heading", "mixed-case-heading"),
            ("  padded  ", "padded"),
            ("Numbers 123 stay", "numbers-123-stay"),
        ],
        ids=["simple", "punctuation", "case", "padding", "digits"],
    )
    def test_basic_github_rules(self, heading, expected):
        assert slugify(heading) == expected

    @pytest.mark.parametrize(
        "heading,expected",
        [
            ("The **bold** bit", "the-bold-bit"),
            ("The `code` bit", "the-code-bit"),
            ("The _em_ bit", "the-_em_-bit"),
            ("The *star* bit", "the-star-bit"),
        ],
        ids=["bold", "code", "underscore-em", "star-em"],
    )
    def test_markdown_markers_are_punctuation_and_drop_out(self, heading, expected):
        """Backticks and asterisks need no unwrapping — they are punctuation, so the
        punctuation rule already removes them. Underscores are KEPT, which is what
        GitHub does; that is the same rule that protects snake_case below."""
        assert slugify(heading) == expected

    @pytest.mark.parametrize(
        "heading,expected",
        [
            ("write_guard and plan_guard", "write_guard-and-plan_guard"),
            ("The foo_bar_baz helper", "the-foo_bar_baz-helper"),
            ("_needs_grounding is called once", "_needs_grounding-is-called-once"),
        ],
        ids=["two-identifiers", "triple-underscore", "leading-underscore"],
    )
    def test_snake_case_survives(self, heading, expected):
        """THE regression this fixture set exists for.

        A paired-emphasis regex (``_([^_]*)_``) is the obvious way to strip
        ``_italics_``, and it silently eats every snake_case identifier:
        ``write_guard and plan_guard`` becomes ``writeguard-and-planguard``. This
        repo's headings are full of such identifiers, so that spelling would have
        reported a large fraction of real, working anchors as broken.
        """
        assert slugify(heading) == expected

    def test_link_contributes_only_its_text(self):
        """``[Foo](bar.md)`` renders as ``Foo``; without unwrapping, the URL leaks
        into the slug as ``foobarmd``. The one construct that genuinely needs it."""
        assert slugify("[Foo](bar.md) heading") == "foo-heading"
        assert slugify("![Alt](img.png) shot") == "alt-shot"


class TestSlugVariants:
    def test_single_spelling_when_no_space_run(self):
        assert slug_variants("Simple heading") == {"simple-heading"}

    def test_both_spellings_when_punctuation_leaves_a_space_run(self):
        """Deliberate ambiguity, pinned so it cannot be collapsed by accident.

        Removing the em-dash from ``Step 1 — Identify`` leaves two spaces. Whether
        GitHub renders ``step-1--identify`` or ``step-1-identify`` is not settled by
        anything in this tree (614 affected headings, none linked to by anchor), so
        both are accepted rather than guessing and manufacturing findings. See
        ``_md_anchors``'s module docstring before narrowing this.
        """
        assert slug_variants("Step 1 — Identify") == {
            "step-1--identify",
            "step-1-identify",
        }


class TestHeadingAnchors:
    def test_collects_every_level(self):
        md = "# One\n\n## Two\n\n###### Six\n"
        assert heading_anchors(md) == {"one", "two", "six"}

    def test_closing_hashes_are_stripped(self):
        assert heading_anchors("## Title ##\n") == {"title"}

    def test_duplicate_headings_get_positional_suffixes(self):
        md = "# Dup\n\n# Dup\n\n# Dup\n"
        assert heading_anchors(md) == {"dup", "dup-1", "dup-2"}

    def test_fenced_blocks_do_not_contribute_headings(self):
        """A ``#`` inside a fence is a shell comment. Counting it would invent an
        anchor AND consume the un-suffixed spelling, pushing the real heading to
        ``-1`` — so this protects the de-duplication counter, not just the set."""
        md = "```bash\n# not a heading\n```\n\n# Real\n"
        assert heading_anchors(md) == {"real"}

    def test_a_two_variant_heading_advances_the_counter_only_once(self):
        """The de-duplication counter must track HEADINGS, not spellings. A heading
        emitting two variants must not consume two slots, or a genuine duplicate
        after it is mis-numbered."""
        md = "# Step 1 — Go\n\n# Step 1 — Go\n"
        anchors = heading_anchors(md)
        assert "step-1--go" in anchors and "step-1-go" in anchors
        assert "step-1--go-1" in anchors and "step-1-go-1" in anchors
        assert "step-1--go-2" not in anchors

    def test_non_heading_lines_are_ignored(self):
        md = "Just prose.\n\n#NoSpace\n\n - # nested\n"
        assert heading_anchors(md) == set()
