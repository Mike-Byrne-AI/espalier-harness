# pytest-marker: default-unit  (pure-function tests of the changelog canon)
"""Contract tests for ``espalier/changelog.py`` — the CHANGELOG structural canon.

The module's reason for existing is that "does this section carry content?" was
hand-rolled as ``^###`` at every consumer while ``CHANGELOG.md`` has never
contained an h3. The detector matched nothing, everywhere, and reported success
every run (``DEF-457`` / ``DEF-591``). So the tests below are weighted toward
shape-agnosticism: each detector is driven against BOTH shapes the project has
used, and the live artifact is driven directly so the canon cannot quietly
drift away from the file it governs again.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from espalier.changelog import (
    category_label,
    has_content,
    section_body,
    substantive_entries,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestCategoryLabel:
    """The dual-shape category matcher."""

    def test_matches_keep_a_changelog_h3_shape(self):
        assert category_label("### Added") == "Added"

    def test_matches_the_bold_shape_the_file_actually_uses(self):
        assert category_label("**Fixed**") == "Fixed"

    def test_matches_a_qualified_bold_label_by_first_word(self):
        """A qualified label still collides with its own kind, so duplicate
        detection is not defeated by trailing words."""
        assert category_label("**Breaking changes**") == "Breaking"

    def test_ignores_a_bold_lead_in_inside_a_bullet(self):
        """``**Why:** …`` opens many bullets in this repo's prose. Treating it
        as a category label would make every explanatory bullet a section."""
        assert category_label("- **Why:** the premise was refuted") is None
        assert category_label("**Why:** the premise was refuted") is None

    def test_ignores_ordinary_prose(self):
        assert category_label("Release-readiness hardening for 0.8.") is None


class TestSubstantiveEntries:
    """"Has work accumulated here?" — must see every shape, not one."""

    def test_counts_bullets(self):
        body = "\n- first entry\n- second entry\n"
        assert len(substantive_entries(body)) == 2

    def test_counts_asterisk_bullets(self):
        assert len(substantive_entries("\n* an entry\n")) == 1

    def test_counts_h3_and_h4_subheadings(self):
        assert len(substantive_entries("\n### Added\n#### Detail\n")) == 2

    def test_counts_bold_category_labels(self):
        """The regression that started this: the live file labels groups
        ``**Fixed**``, and an h3-keyed detector scored it zero."""
        assert len(substantive_entries("\n**Fixed**\n")) == 1

    def test_sees_both_shapes_in_one_body(self):
        """Pins the step that converts this file's labels from bold to h3:
        the detector must not go blind on either side of that change."""
        mixed = "\n**Fixed**\n- a bullet\n### Added\n- another\n"
        assert len(substantive_entries(mixed)) == 4

    def test_prose_alone_yields_no_entries(self):
        """Narrower than has_content by design — see TestHasContent."""
        assert substantive_entries("\nA prose paragraph about the release.\n") == []

    def test_empty_body_yields_no_entries(self):
        assert substantive_entries("") == []
        assert substantive_entries("\n\n   \n") == []


class TestHasContent:
    """"Is this section empty?" — prose counts, furniture does not."""

    def test_prose_is_content(self):
        """The design catch. Every dated section in CHANGELOG.md is a prose
        summary with zero bullets; an entry-only test would call a perfectly
        good release section empty and red the live tree."""
        assert has_content("\nRelease-readiness hardening for the 0.8 line.\n")

    def test_bullets_are_content(self):
        assert has_content("\n- an entry\n")

    def test_blank_body_is_not_content(self):
        assert not has_content("")
        assert not has_content("\n\n")
        assert not has_content("\n   \n\t\n")

    def test_horizontal_rule_alone_is_not_content(self):
        assert not has_content("\n---\n")
        assert not has_content("\n***\n")

    def test_link_reference_definitions_alone_are_not_content(self):
        """The 30 compare-links at the foot of the file are furniture. If they
        counted, the last release section could never be detected as empty."""
        body = (
            "\n[0.8.0a13]: https://example.invalid/compare/v0.8.0a12...v0.8.0a13\n"
            "[0.7.8]: https://example.invalid/compare/v0.7.7...v0.7.8\n"
        )
        assert not has_content(body)

    def test_content_above_link_references_still_counts(self):
        body = "\nA real summary.\n\n[0.1.0]: https://example.invalid/x\n"
        assert has_content(body)

    def test_a_pointer_line_satisfies_has_content_by_design(self):
        """Pins a SURPRISING DEFAULT so the next reader cannot mistake this
        gate for a stronger one. One non-furniture line is enough — `TBD` or a
        defer-pointer passes. That is deliberate: the live `## [0.8.0a13]`
        section legitimately ends with *"See [Unreleased] for the headline 0.8
        feature set"*, and a defer-pointer is a real mid-alpha release note.
        This answers "is the section empty", never "are the notes any good".
        """
        assert has_content("\nSee [Unreleased].\n")
        assert has_content("\nTBD\n")


class TestSectionBody:
    """Extraction boundaries — where a release section actually ends."""

    TEXT = (
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "- staged work\n\n"
        "## [0.2.0] — 2026-02-02\n\n"
        "Second release summary.\n\n"
        "## [0.1.0] — 2026-01-01\n\n"
        "First release summary.\n\n"
        "## Pre-0.1 history — 2025\n\n"
        "Condensed early history.\n\n"
        "---\n\n"
        "[0.1.0]: https://example.invalid/releases/tag/v0.1.0\n"
    )

    def test_returns_the_named_versions_body(self):
        body = section_body(self.TEXT, "0.2.0")
        assert body is not None
        assert "Second release summary." in body

    def test_stops_at_the_next_dated_header(self):
        body = section_body(self.TEXT, "0.2.0")
        assert "First release summary." not in body

    def test_stops_at_a_non_bracket_h2_header(self):
        """The boundary trap. ``## Pre-0.8 alpha — …`` is a real section that
        matches no bracket form; an extractor keyed on ``^## \\[`` swallows it
        AND the link-reference block below it, so a genuinely empty release
        section reads as populated."""
        body = section_body(self.TEXT, "0.1.0")
        assert body is not None
        assert "First release summary." in body
        assert "Condensed early history." not in body
        assert "example.invalid" not in body

    def test_absent_version_returns_none(self):
        """Distinct from an empty body: no header at all is a different defect
        and the caller reports it differently."""
        assert section_body(self.TEXT, "9.9.9") is None

    def test_dated_but_empty_section_returns_an_empty_body(self):
        text = "## [0.3.0] — 2026-03-03\n\n## [0.2.0] — 2026-02-02\n\nreal.\n"
        body = section_body(text, "0.3.0")
        assert body is not None
        assert not has_content(body)

    @pytest.mark.parametrize("spacing", ["", "\t", "  "])
    def test_boundary_is_never_narrower_than_the_header_pattern(self, spacing):
        """A boundary requiring a literal `## ` is narrower than
        DATED_VERSION_RE's `^##\\s*\\[`, so `##[0.2.0]` is a header the canon
        accepts but the boundary would not stop at — letting an EMPTY section
        swallow the next one and report content. Driven: that returned PASS
        from the release gate on the exact slip it was rewritten to catch.

        The trigger is the documented manual step (`CONTRIBUTING.md`: "add a
        `[x.y.z]` section"), hand-typed at the highest-friction moment of the
        cycle — and CommonMark renders `##[0.2.0]` as body text, so the
        operator sees a run-together section and never suspects the gate.
        """
        text = (
            "# Changelog\n\n"
            "## [0.3.0] — 2026-03-03\n\n"
            f"##{spacing}[0.2.0] — 2026-02-02\n\n"
            "Notes that belong to 0.2.0, not 0.3.0.\n"
        )
        body = section_body(text, "0.3.0")
        assert body is not None
        assert not has_content(body), (
            f"[0.3.0] is empty but section_body swallowed the {spacing!r}-spaced "
            f"sibling header: {body!r}"
        )

    def test_the_last_section_in_the_file_runs_to_eof(self):
        """The `else rest` arm — no subsequent h2 exists at all. Every other
        fixture here has a trailing section, so this branch shipped untested."""
        text = "# Changelog\n\n## [0.1.0] — 2026-01-01\n\nFinal notes.\n"
        body = section_body(text, "0.1.0")
        assert body is not None
        assert "Final notes." in body
        assert has_content(body)

    def test_the_last_section_in_the_file_can_still_be_empty(self):
        """Same branch, opposite verdict — a trailing header with nothing under
        it must not be rescued into looking populated by running to EOF."""
        text = "# Changelog\n\n## [0.1.0] — 2026-01-01\n"
        body = section_body(text, "0.1.0")
        assert body is not None
        assert not has_content(body)

    def test_an_h3_does_not_end_a_section(self):
        """`(?!#)` in the boundary — category subheadings live INSIDE a
        section, so an h3 must not terminate it."""
        text = "## [0.1.0] — 2026-01-01\n\n### Added\n- a thing\n"
        body = section_body(text, "0.1.0")
        assert body is not None
        assert "a thing" in body


class TestAgainstTheLiveChangelog:
    """Drive the canon against the artifact it governs.

    The failure this module exists to prevent is a detector that matches
    nothing while reporting success, and that failure is invisible to
    synthetic fixtures alone — both prior fixes passed their own suites.
    """

    @classmethod
    def _text(cls) -> str:
        return (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    # A deliberately NAIVE, independent notion of "this line looks like a
    # changelog entry", spelled out here rather than imported. If this test
    # derived its expectation from the canon it is checking, the two would
    # agree by construction and the probe would be blind to the very drift it
    # exists to catch — the trap that let a `^###` detector sit green for
    # months. Two implementations that must agree is the whole point.
    _NAIVE_ENTRY = re.compile(r"^\s*(?:[-*]\s+\S|#{3,4}\s+\S)")
    _NAIVE_LABEL = re.compile(r"^(?:\*\*[A-Z][A-Za-z ]*\*\*|#{3}\s+[A-Z]\w*)\s*$")

    def _unreleased_body(self) -> str:
        from espalier.changelog import UNRELEASED_BODY_RE

        m = UNRELEASED_BODY_RE.search(self._text())
        assert m is not None, "CHANGELOG.md has no [Unreleased] section"
        return m.group("body")

    def test_no_entry_shaped_line_is_invisible_to_the_detector(self):
        """Anti-vacuity WITHOUT pinning the file's current contents.

        The failure guarded here is a detector scoring zero on a populated
        section. Asserting "[Unreleased] has entries" would catch that — and
        would ALSO fail the moment a release fold legitimately empties the
        section. This file is not in `_SLOW_FILES`, so it rides in the
        `-m "not slow"` slice that `release_check.check_tests_pass` runs with
        `ESPALIER_RELEASE_CHECK_WITH_TESTS=1`; a contents-pinned assertion here
        would red the publish-proof gate on the one commit this whole module
        exists to protect. So the property is CONDITIONAL: whatever
        entry-shaped lines the section happens to hold, the canon must see all
        of them. An emptied section passes trivially, which is correct.
        """
        body = self._unreleased_body()
        naive = [ln for ln in body.splitlines() if self._NAIVE_ENTRY.match(ln)]
        if not naive:
            pytest.skip("[Unreleased] holds no entry-shaped lines (folded or prose-only)")
        seen = substantive_entries(body)
        assert len(seen) >= len(naive), (
            f"the canon sees {len(seen)} entries where a naive independent scan "
            f"finds {len(naive)}. A detector that scores lower than a two-line "
            f"regex is keyed on a shape the file does not use — the DEF-591 "
            f"failure exactly. Missed: {[ln for ln in naive if ln not in seen][:5]}"
        )

    def test_every_group_label_shaped_line_is_recognised(self):
        """Shape-independent AND fold-safe.

        Asserts the matcher recognises every line that LOOKS like a group
        label — not that four specific labels are present. Pinning
        {Added, Changed, Fixed, Removed} would red on a patch-only cycle with
        no removals, and again at the fold. Passes before and after the
        bold→h3 conversion; fails if a future style change outruns the matcher.
        """
        body = self._unreleased_body()
        label_shaped = [
            ln for ln in body.splitlines() if self._NAIVE_LABEL.match(ln.rstrip())
        ]
        if not label_shaped:
            pytest.skip("[Unreleased] carries no group labels")
        unrecognised = [ln for ln in label_shaped if category_label(ln) is None]
        assert not unrecognised, (
            f"group-label-shaped lines the matcher does not recognise: "
            f"{unrecognised}. CATEGORY_LABEL_RE has fallen behind the file's style."
        )

    def test_the_current_pyproject_version_has_a_populated_section(self):
        """The live-tree half of the invariant the release gate now asserts."""
        from espalier.version_surfaces import VERSION_SURFACES, read_surface_version

        version = read_surface_version(REPO_ROOT, *VERSION_SURFACES[0])
        assert version is not None
        body = section_body(self._text(), version)
        assert body is not None, f"pyproject {version!r} has no dated section"
        assert has_content(body), (
            f"[{version}] is dated but empty — the release gate would FAIL here"
        )
