"""Tests for ``espalier.reflect_protocol`` — the structured reflect-
pass engine invoked by ``reflect_trigger`` every Nth source write to
build a reference matrix, find orphans, surface ref gaps, and emit
``ReflectFinding`` rows.

Pins the unit-level helpers (``_rel`` posix-normalization,
``_text_without_fences`` link scrubber, ``_section_density`` scorer)
plus the integrating ``run_reflect_pass`` shape. Without this
contract a refactor to the matrix builder could silently regress
the reflect surface — findings would still emit (so the trigger
appears healthy) but they'd point to the wrong files or miss
real broken-link drift.
"""
from __future__ import annotations

from pathlib import Path

import pytest


from espalier.reflect_protocol import (
    _rel,
    _iter_surface_files,
    _text_without_fences,
    _extract_local_links,
    _count_placeholders,
    _section_density,
    build_reference_matrix,
    find_orphans,
    find_expected_ref_gaps,
    detect_quality_signals,
    validate_command_tools,
    run_reflect_pass,
    render_reflect_pass,
    EXPECTED_REFS,
)
from espalier.models import ReflectFinding, ReflectPass


# ─── _rel ────────────────────────────────────────────────────────────────────

class TestRel:
    def test_returns_forward_slashes(self, tmp_path):
        child = tmp_path / "cc" / "LIVE_SURFACE.md"
        child.parent.mkdir(parents=True)
        child.touch()
        result = _rel(child, tmp_path)
        assert "\\" not in result
        assert result == "cc/LIVE_SURFACE.md"

    def test_root_level_file(self, tmp_path):
        f = tmp_path / "CLAUDE.md"
        f.touch()
        assert _rel(f, tmp_path) == "CLAUDE.md"


# ─── _text_without_fences ────────────────────────────────────────────────────

class TestIterSurfaceFiles:
    """The engine reflect walker must enumerate the FULL ``docs/`` tree — matching
    the hook twin's ``docs/**/*.md`` walk. A hardcoded docs subset silently dropped
    new docs (HOOK_ASSUMPTIONS.md, MEMORY_SYSTEMS.md, docs/schemas/*)."""

    @staticmethod
    def _make_repo(root: Path) -> None:
        (root / "docs" / "schemas").mkdir(parents=True)
        (root / "CLAUDE.md").write_text("root", encoding="utf-8")
        # In the old hardcoded list:
        (root / "docs" / "CONVENTIONS.md").write_text("in old list", encoding="utf-8")
        # NOT in the old hardcoded list:
        (root / "docs" / "HOOK_ASSUMPTIONS.md").write_text("new doc", encoding="utf-8")
        (root / "docs" / "schemas" / "nested.md").write_text("nested", encoding="utf-8")

    def test_walks_full_docs_tree_not_a_hardcoded_subset(self, tmp_path):
        self._make_repo(tmp_path)
        found = {p.name for p in _iter_surface_files(tmp_path)}
        # A doc in the old hardcoded list is still enumerated ...
        assert "CONVENTIONS.md" in found
        # ... and so is one that was NOT in the hardcoded list (the whole point).
        assert "HOOK_ASSUMPTIONS.md" in found, (
            "engine walker missed a docs/ file absent from the old hardcoded "
            "subset — it must walk docs/**/*.md like the hook twin"
        )
        # Nested docs are reached by the recursive walk.
        assert "nested.md" in found

    def test_root_level_docs_still_enumerated(self, tmp_path):
        self._make_repo(tmp_path)
        found = {p.name for p in _iter_surface_files(tmp_path)}
        assert "CLAUDE.md" in found

    def test_returns_no_duplicate_paths(self, tmp_path):
        self._make_repo(tmp_path)
        found = _iter_surface_files(tmp_path)
        assert len(found) == len(set(found)), "walker returned duplicate paths"


class TestTextWithoutFences:
    def test_strips_code_block_content(self):
        text = "Outside\n```\ninside code\n```\nAlso outside\n"
        result = _text_without_fences(text)
        assert "inside code" not in result
        assert "Outside" in result
        assert "Also outside" in result

    def test_preserves_non_fenced_text(self):
        text = "Line one\nLine two\n"
        result = _text_without_fences(text)
        assert "Line one" in result

    def test_empty_input_returns_empty(self):
        assert _text_without_fences("") == ""

    def test_nested_fence_content_excluded(self):
        text = "```\nlink: [foo](bar.md)\n```\n"
        result = _text_without_fences(text)
        assert "bar.md" not in result


# ─── _extract_local_links ────────────────────────────────────────────────────

class TestExtractLocalLinks:
    def test_extracts_relative_link(self):
        text = "See [guide](setup.md) for details."
        links = _extract_local_links(text)
        assert "setup.md" in links

    def test_ignores_http_links(self):
        text = "Visit [site](https://example.com)"
        links = _extract_local_links(text)
        assert "https://example.com" not in links
        assert links == []

    def test_ignores_anchor_links(self):
        text = "Go to [section](#heading)"
        links = _extract_local_links(text)
        assert links == []

    def test_strips_anchor_from_file_link(self):
        text = "[doc](guide.md#section)"
        links = _extract_local_links(text)
        assert "guide.md" in links
        assert any("#" not in link for link in links)

    def test_links_inside_fences_excluded(self):
        text = "```\n[hidden](secret.md)\n```\n"
        links = _extract_local_links(text)
        assert "secret.md" not in links

    def test_multiple_links_extracted(self):
        text = "[a](one.md) and [b](two.md)"
        links = _extract_local_links(text)
        assert "one.md" in links
        assert "two.md" in links


# ─── _count_placeholders ─────────────────────────────────────────────────────

class TestCountPlaceholders:
    def test_counts_curly_brace_placeholder(self):
        text = "Set {your_name} here."
        count = _count_placeholders(text)
        assert count >= 1

    def test_counts_todo_marker(self):
        text = "TODO: fill this in"
        count = _count_placeholders(text)
        assert count >= 1

    def test_counts_fixme_marker(self):
        text = "FIXME: broken here"
        count = _count_placeholders(text)
        assert count >= 1

    def test_clean_text_has_zero_placeholders(self):
        text = "This is a clean, complete sentence with no placeholders."
        count = _count_placeholders(text)
        assert count == 0

    def test_placeholders_inside_fences_excluded(self):
        text = "```\nTODO: not counted\n```\n"
        count = _count_placeholders(text)
        assert count == 0

    def test_multiple_placeholders_counted(self):
        text = "{field_a} and {field_b} and TODO: also this"
        count = _count_placeholders(text)
        assert count >= 3


# ─── _section_density ────────────────────────────────────────────────────────

class TestSectionDensity:
    def test_empty_doc_returns_zero_counts(self):
        result = _section_density("")
        assert result["headings"] == 0
        assert result["content_lines"] == 0
        assert result["empty_sections"] == 0

    def test_heading_with_content_not_empty(self):
        text = "# Heading\nSome content here.\n"
        result = _section_density(text)
        assert result["headings"] == 1
        assert result["content_lines"] >= 1
        assert result["empty_sections"] == 0

    def test_heading_with_no_content_is_empty_section(self):
        text = "# Heading\n# Another Heading\nContent\n"
        result = _section_density(text)
        assert result["empty_sections"] >= 1

    def test_ratio_is_content_over_headings(self):
        text = "# H\nLine 1\nLine 2\nLine 3\n# H2\nLine 4\n"
        result = _section_density(text)
        assert result["ratio"] == round(result["content_lines"] / max(result["headings"], 1), 1)

    def test_only_content_no_headings(self):
        text = "Just content\nmore content\n"
        result = _section_density(text)
        assert result["headings"] == 0
        assert result["content_lines"] == 2

    # The CommonMark ATX subset (C62). The ledger row's own probe document: a
    # parent-then-child pair, two `#` comments in a shell fence, an indented
    # example and one real empty section. The old parser counted four.
    _PROBE = "\n".join([
        "# Title", "intro", "## Commands", "### Session", "body", "## Run",
        "```bash", "# Run tests", "# then lint", "pytest", "```",
        "## Structure", "    # <Title>", "    body", "## Empty", "## Next", "body",
    ])

    def test_the_probe_document_holds_one_empty_section(self):
        assert _section_density(self._PROBE)["empty_sections"] == 1

    def test_a_comment_in_a_fence_is_content_not_a_heading(self):
        result = _section_density("## Run\n```bash\n# Run tests\npytest\n```\n")
        assert (result["headings"], result["empty_sections"]) == (1, 0)

    def test_a_tilde_fence_ignores_a_backtick_run_and_an_info_string(self):
        text = "## Run\n~~~\n```python\n# not a heading\n~~~\n## After\nbody\n"
        assert _section_density(text)["headings"] == 2
        text = "## Run\n```\n```bash\n# still fenced\n```\n## After\nbody\n"
        assert _section_density(text)["headings"] == 2

    def test_a_line_indented_four_spaces_is_not_a_heading(self):
        result = _section_density("## Structure\n    # <Title>\n    body\n")
        assert (result["headings"], result["empty_sections"]) == (1, 0)

    def test_a_parent_followed_by_its_subheading_is_not_empty(self):
        assert _section_density("## Commands\n### Session\nbody\n")["empty_sections"] == 0

    def test_a_subheading_closed_by_a_higher_heading_is_empty(self):
        assert _section_density("## A\n### B\n## C\nbody\n")["empty_sections"] == 1

    def test_a_heading_at_the_end_with_nothing_under_it_is_empty(self):
        assert _section_density("# T\nbody\n## Last\n")["empty_sections"] == 1

    def test_a_hash_without_a_space_or_seven_hashes_is_text(self):
        result = _section_density("# T\n#tag line\n####### seven\n")
        assert (result["headings"], result["content_lines"], result["empty_sections"]) == (1, 2, 0)


# ─── build_reference_matrix ──────────────────────────────────────────────────

class TestBuildReferenceMatrix:
    def test_empty_surface_returns_empty_matrix(self, tmp_path):
        matrix = build_reference_matrix(tmp_path)
        assert isinstance(matrix, dict)

    def test_file_references_existing_sibling(self, tmp_path):
        (tmp_path / "ESPALIER_MEMORY.md").write_text("# Memory\n", encoding="utf-8")
        (tmp_path / "CLAUDE.md").write_text(
            "# Claude\nSee [memory](ESPALIER_MEMORY.md)\n", encoding="utf-8"
        )
        matrix = build_reference_matrix(tmp_path)
        assert "CLAUDE.md" in matrix
        assert "ESPALIER_MEMORY.md" in matrix["CLAUDE.md"]

    def test_plain_text_mention_captured(self, tmp_path):
        (tmp_path / "ESPALIER_MEMORY.md").write_text("# Memory\n", encoding="utf-8")
        (tmp_path / "CLAUDE.md").write_text(
            "# Claude\nRead ESPALIER_MEMORY.md for context.\n", encoding="utf-8"
        )
        matrix = build_reference_matrix(tmp_path)
        assert "CLAUDE.md" in matrix
        assert "ESPALIER_MEMORY.md" in matrix["CLAUDE.md"]

    def test_matrix_values_are_lists(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")
        matrix = build_reference_matrix(tmp_path)
        for key, value in matrix.items():
            assert isinstance(value, list)

    def test_ambiguous_basename_no_phantom_edge(self, tmp_path):
        # STALE-1: two SKILL.md files share a basename; a single bare mention
        # of "SKILL.md" must NOT resolve to either (it's ambiguous). The old
        # basename-only fallback added BOTH as phantom edges, suppressing
        # orphan detection. RED before Fix 9-A.
        (tmp_path / ".claude" / "skills" / "a").mkdir(parents=True)
        (tmp_path / ".claude" / "skills" / "b").mkdir(parents=True)
        (tmp_path / ".claude" / "skills" / "a" / "SKILL.md").write_text("# A\n", encoding="utf-8")
        (tmp_path / ".claude" / "skills" / "b" / "SKILL.md").write_text("# B\n", encoding="utf-8")
        (tmp_path / "CLAUDE.md").write_text(
            "# Claude\nSee the SKILL.md docs for details.\n", encoding="utf-8"
        )
        edges = build_reference_matrix(tmp_path).get("CLAUDE.md", [])
        assert ".claude/skills/a/SKILL.md" not in edges
        assert ".claude/skills/b/SKILL.md" not in edges

    def test_unique_basename_resolves_amid_ambiguous(self, tmp_path):
        # Control: a uniquely-named file's bare mention STILL resolves even
        # when ambiguous basenames exist elsewhere — the fix must not over-prune.
        (tmp_path / ".claude" / "skills" / "a").mkdir(parents=True)
        (tmp_path / ".claude" / "skills" / "b").mkdir(parents=True)
        (tmp_path / ".claude" / "skills" / "a" / "SKILL.md").write_text("# A\n", encoding="utf-8")
        (tmp_path / ".claude" / "skills" / "b" / "SKILL.md").write_text("# B\n", encoding="utf-8")
        (tmp_path / "ESPALIER_MEMORY.md").write_text("# Memory\n", encoding="utf-8")
        (tmp_path / "CLAUDE.md").write_text(
            "# Claude\nRead ESPALIER_MEMORY.md for context.\n", encoding="utf-8"
        )
        edges = build_reference_matrix(tmp_path).get("CLAUDE.md", [])
        assert "ESPALIER_MEMORY.md" in edges


class TestHookBuildMatrixStaleParity:
    """TP-192 W2-2 behavioral-parity: the hook-invoked
    ``tools/cc/reflect_protocol.build_matrix`` must share the engine
    ``build_reference_matrix`` STALE-1 invariant — an ambiguous-basename
    mention produces NO phantom edge. The two are conceptually mirrored but
    NOT byte-parity; without this test a fix on one side silently rots the
    other (TP-192 SHARP_EDGES 'engine ↔ hook copies share a concept not bytes')."""

    @staticmethod
    def _hook_build_matrix():
        import importlib.util

        tools_cc = Path(__file__).resolve().parent.parent / "tools" / "cc"
        spec = importlib.util.spec_from_file_location(
            "_tp192_hook_reflect", tools_cc / "reflect_protocol.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.build_matrix

    @staticmethod
    def _ambiguous_fixture(tmp_path):
        (tmp_path / ".claude" / "skills" / "a").mkdir(parents=True)
        (tmp_path / ".claude" / "skills" / "b").mkdir(parents=True)
        (tmp_path / ".claude" / "skills" / "a" / "SKILL.md").write_text("# A\n", encoding="utf-8")
        (tmp_path / ".claude" / "skills" / "b" / "SKILL.md").write_text("# B\n", encoding="utf-8")
        (tmp_path / "CLAUDE.md").write_text(
            "# Claude\nSee the SKILL.md docs for details.\n", encoding="utf-8"
        )

    def test_hook_ambiguous_basename_no_phantom_edge(self, tmp_path):
        self._ambiguous_fixture(tmp_path)
        edges = self._hook_build_matrix()(tmp_path).get("CLAUDE.md", [])
        assert ".claude/skills/a/SKILL.md" not in edges
        assert ".claude/skills/b/SKILL.md" not in edges

    def test_hook_unique_basename_still_resolves(self, tmp_path):
        # Control: a uniquely-named file's bare mention STILL resolves even when
        # ambiguous basenames exist elsewhere — the guard must not over-prune.
        (tmp_path / ".claude" / "skills" / "a").mkdir(parents=True)
        (tmp_path / ".claude" / "skills" / "b").mkdir(parents=True)
        (tmp_path / ".claude" / "skills" / "a" / "SKILL.md").write_text("# A\n", encoding="utf-8")
        (tmp_path / ".claude" / "skills" / "b" / "SKILL.md").write_text("# B\n", encoding="utf-8")
        (tmp_path / "ESPALIER_MEMORY.md").write_text("# Memory\n", encoding="utf-8")
        (tmp_path / "CLAUDE.md").write_text(
            "# Claude\nRead ESPALIER_MEMORY.md for context.\n", encoding="utf-8"
        )
        edges = self._hook_build_matrix()(tmp_path).get("CLAUDE.md", [])
        assert "ESPALIER_MEMORY.md" in edges

    def test_engine_and_hook_agree_on_ambiguous_invariant(self, tmp_path):
        self._ambiguous_fixture(tmp_path)
        phantom = {".claude/skills/a/SKILL.md", ".claude/skills/b/SKILL.md"}
        hook_edges = set(self._hook_build_matrix()(tmp_path).get("CLAUDE.md", []))
        engine_edges = set(build_reference_matrix(tmp_path).get("CLAUDE.md", []))
        assert hook_edges.isdisjoint(phantom), hook_edges
        assert engine_edges.isdisjoint(phantom), engine_edges


# ─── find_orphans ────────────────────────────────────────────────────────────

class TestFindOrphans:
    def test_unreferenced_doc_is_orphan(self):
        matrix = {
            "CLAUDE.md": [],
            "ESPALIER_MEMORY.md": [],
        }
        orphans = find_orphans(matrix, root=None)
        assert "CLAUDE.md" in orphans or "ESPALIER_MEMORY.md" in orphans

    def test_referenced_doc_not_orphan(self):
        matrix = {
            "CLAUDE.md": ["ESPALIER_MEMORY.md"],
            "ESPALIER_MEMORY.md": [],
        }
        orphans = find_orphans(matrix, root=None)
        assert "ESPALIER_MEMORY.md" not in orphans

    def test_command_files_excluded_from_orphans(self):
        matrix = {
            ".claude/commands/design.md": [],
        }
        orphans = find_orphans(matrix, root=None)
        assert ".claude/commands/design.md" not in orphans

    def test_agent_files_excluded_from_orphans(self):
        matrix = {
            ".claude/agents/repo-analyst.md": [],
        }
        orphans = find_orphans(matrix, root=None)
        assert ".claude/agents/repo-analyst.md" not in orphans

    def test_empty_matrix_returns_empty(self):
        orphans = find_orphans({}, root=None)
        assert orphans == []


# ─── find_expected_ref_gaps ──────────────────────────────────────────────────

class TestFindExpectedRefGaps:
    def test_claude_md_missing_memory_md_is_gap(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Claude\nNo memory reference here.\n", encoding="utf-8")
        matrix = {"CLAUDE.md": []}
        gaps = find_expected_ref_gaps(tmp_path, matrix)
        gap_targets = [target for _, target in gaps]
        assert "ESPALIER_MEMORY.md" in gap_targets

    def test_claude_md_with_memory_md_not_gap(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Claude\nSee ESPALIER_MEMORY.md.\n", encoding="utf-8")
        matrix = {"CLAUDE.md": ["ESPALIER_MEMORY.md"]}
        gaps = find_expected_ref_gaps(tmp_path, matrix)
        gap_targets = [target for _, target in gaps]
        assert "ESPALIER_MEMORY.md" not in gap_targets

    def test_missing_source_file_skipped(self, tmp_path):
        # ``find_expected_ref_gaps`` walks the module-level EXPECTED_REFS; a
        # source doc that does not exist on disk hits the
        # ``if not source_path.exists(): continue`` skip. In this empty repo
        # NONE of the expected sources exist, so every entry is skipped and no
        # gap is reported. If the skip were removed, ``_safe_text`` on a missing
        # file returns "" and EVERY expected target would surface as a gap —
        # so ``gaps == []`` (not merely "is a list") proves the skip fires.
        assert EXPECTED_REFS, "vacuous unless EXPECTED_REFS has entries to skip"
        for source_name, _targets in EXPECTED_REFS:
            assert not (tmp_path / source_name).exists()
        gaps = find_expected_ref_gaps(tmp_path, {})
        assert gaps == []


# ─── detect_quality_signals ──────────────────────────────────────────────────

class TestDetectQualitySignals:
    def test_placeholder_in_doc_flagged(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "# Claude\n{your_name} should configure this.\n", encoding="utf-8"
        )
        findings = detect_quality_signals(tmp_path)
        assert any("placeholder" in f.description.lower() for f in findings)

    def test_clean_doc_has_no_findings(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "# Claude\nThis is complete documentation with real content.\n"
            "No placeholders or empty sections here.\n"
            "Third line of substantive content.\n"
            "Fourth line to stay clear of the sparse-section threshold.\n",
            encoding="utf-8",
        )
        findings = detect_quality_signals(tmp_path)
        assert findings == []

    def test_empty_section_flagged(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "# Section One\n# Section Two\nContent here.\n", encoding="utf-8"
        )
        findings = detect_quality_signals(tmp_path)
        assert any("empty section" in f.description.lower() for f in findings)

    def test_very_short_doc_flagged_as_high_severity(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Title\nOne line.\n", encoding="utf-8")
        findings = detect_quality_signals(tmp_path)
        high_severity = [f for f in findings if f.severity == "high"]
        assert len(high_severity) > 0

    def test_returns_list_of_reflect_findings(self, tmp_path):
        findings = detect_quality_signals(tmp_path)
        assert isinstance(findings, list)
        for f in findings:
            assert isinstance(f, ReflectFinding)


# ─── validate_command_tools ──────────────────────────────────────────────────

class TestValidateCommandTools:
    def test_no_commands_dir_returns_empty(self, tmp_path):
        findings = validate_command_tools(tmp_path)
        assert findings == []

    def test_existing_script_reference_not_flagged(self, tmp_path):
        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        tools_dir = tmp_path / "tools" / "cc"
        tools_dir.mkdir(parents=True)
        (tools_dir / "my_tool.py").write_text("print('ok')\n", encoding="utf-8")
        (commands_dir / "do-thing.md").write_text(
            "Run `python tools/cc/my_tool.py`\n", encoding="utf-8"
        )
        findings = validate_command_tools(tmp_path)
        assert findings == []

    def test_missing_script_reference_flagged(self, tmp_path):
        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "broken-cmd.md").write_text(
            "Run `python tools/cc/ghost_script.py`\n", encoding="utf-8"
        )
        findings = validate_command_tools(tmp_path)
        assert len(findings) > 0
        assert any("ghost_script.py" in f.description for f in findings)


# ─── run_reflect_pass ────────────────────────────────────────────────────────

class TestRunReflectPass:
    def test_returns_reflect_pass_object(self, tmp_path):
        rp = run_reflect_pass(tmp_path)
        assert isinstance(rp, ReflectPass)

    def test_empty_repo_has_zero_files_analyzed(self, tmp_path):
        rp = run_reflect_pass(tmp_path)
        assert rp.files_analyzed == 0

    def test_pass_number_preserved(self, tmp_path):
        rp = run_reflect_pass(tmp_path, pass_number=3)
        assert rp.pass_number == 3

    def test_timestamp_is_set(self, tmp_path):
        rp = run_reflect_pass(tmp_path)
        assert rp.timestamp != ""

    def test_findings_is_list(self, tmp_path):
        rp = run_reflect_pass(tmp_path)
        assert isinstance(rp.findings, list)

    def test_gap_count_matches_gap_findings(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "# Claude\nNo memory reference.\n", encoding="utf-8"
        )
        rp = run_reflect_pass(tmp_path)
        computed = sum(1 for f in rp.findings if f.kind == "gap")
        assert rp.gap_count == computed

    def test_orphan_count_matches_orphan_findings(self, tmp_path):
        (tmp_path / "ESPALIER_MEMORY.md").write_text("# Memory\n\nSome content.\n", encoding="utf-8")
        rp = run_reflect_pass(tmp_path)
        computed = sum(1 for f in rp.findings if f.kind == "orphan")
        assert rp.orphan_count == computed

    def test_broken_link_in_claude_md_creates_gap_finding(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "# Claude\nSee [missing](ghost.md)\n", encoding="utf-8"
        )
        rp = run_reflect_pass(tmp_path)
        gap_descs = [f.description for f in rp.findings if f.kind == "gap"]
        assert any("ghost.md" in d for d in gap_descs)

    def test_to_dict_is_serialisable(self, tmp_path):
        import json
        rp = run_reflect_pass(tmp_path)
        data = rp.to_dict()
        json.dumps(data)


# ─── render_reflect_pass ─────────────────────────────────────────────────────

class TestRenderReflectPass:
    def test_output_contains_pass_number(self, tmp_path):
        rp = run_reflect_pass(tmp_path, pass_number=2)
        output = render_reflect_pass(rp)
        assert "REFLECT PASS 2" in output

    def test_output_contains_files_analyzed_count(self, tmp_path):
        rp = run_reflect_pass(tmp_path)
        output = render_reflect_pass(rp)
        assert "Files analyzed:" in output

    def test_output_contains_gap_count(self, tmp_path):
        rp = run_reflect_pass(tmp_path)
        output = render_reflect_pass(rp)
        assert "Gaps:" in output

    def test_output_contains_orphan_count(self, tmp_path):
        rp = run_reflect_pass(tmp_path)
        output = render_reflect_pass(rp)
        assert "Orphans:" in output

    def test_no_findings_shows_coherent_message(self, tmp_path):
        rp = run_reflect_pass(tmp_path)
        if not rp.findings:
            output = render_reflect_pass(rp)
            assert "coherent" in output.lower() or "No findings" in output

    def test_output_ends_with_newline(self, tmp_path):
        rp = run_reflect_pass(tmp_path)
        output = render_reflect_pass(rp)
        assert output.endswith("\n")

    def test_gap_finding_appears_in_output(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "# Claude\n[broken](definitely_absent.md)\n", encoding="utf-8"
        )
        rp = run_reflect_pass(tmp_path)
        output = render_reflect_pass(rp)
        # The old `"GAP" in output` disjunct was always true — render emits a GAP
        # block for the expected-reference gaps of a bare CLAUDE.md even with no
        # broken link, so it could not fail if broken-link detection regressed.
        # Assert the specific signal instead: the render names the broken target.
        assert "definitely_absent.md" in output, (
            "the broken-link GAP finding must name its target in the output"
        )


# ─── §C12: the two halves agree on surface, residue and orphan exemptions ────
#
# One feature implemented twice across the tools/cc <-> espalier import
# boundary, disagreeing in three ways (DEF-416a, DEF-589, DEF-410g). The oracle
# the class names is one /reflect run with both halves' outputs diffed; these
# tests are that diff, per axis, on a fixture and on the live tree.

import espalier.reflect_protocol as _erp


def _hook_side():
    import importlib.util

    tools_cc = Path(__file__).resolve().parent.parent / "tools" / "cc"
    spec = importlib.util.spec_from_file_location(
        "_c12_hook_reflect", tools_cc / "reflect_protocol.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _c12_repo(root: Path) -> None:
    """A tree with a folder router nothing links to, a memory note nothing links
    to, a record surface that quotes template vocabulary, a doc whose only brace
    tokens are backticked mentions, and one doc with real residue."""
    (root / "docs").mkdir()
    (root / "memory").mkdir()
    (root / "pkg").mkdir()
    (root / "CLAUDE.md").write_text(
        "# Root\n\nSee [conventions](docs/CONVENTIONS.md) and [draft](docs/draft.md).\n",
        encoding="utf-8",
    )
    (root / "docs" / "CONVENTIONS.md").write_text(
        "# Conventions\n\nTest files: `tests/test_{topic}.py`; also ``a `{b}` c``.\n",
        encoding="utf-8",
    )
    (root / "docs" / "draft.md").write_text(
        "# Draft\n\nTODO: write this section about {thing}.\n", encoding="utf-8"
    )
    (root / "docs" / "RELEASE_DECISIONS.md").write_text(
        '# Corpus\n\nThe banner said "[banner] {name} section over" and a TODO: marker.\n',
        encoding="utf-8",
    )
    (root / "memory" / "note.md").write_text("# Note\n\nNothing links here.\n", encoding="utf-8")
    (root / "pkg" / "CLAUDE.md").write_text("# pkg/\n\nA folder router.\n", encoding="utf-8")


class TestInlineCodeIsNotResidue:
    """Every placeholder hit reflect raised on the three live docs on 2026-09-08
    was a backticked identifier such as `tests/test_{topic}.py` (12 of 12)."""

    def test_engine_ignores_a_backticked_brace_token(self):
        assert _count_placeholders("Set `{name}` in the config.") == 0
        assert _count_placeholders("Set ``{name}`` in the config.") == 0

    def test_engine_still_counts_prose_residue(self):
        assert _count_placeholders("Set {name} in the config.") == 1
        assert _count_placeholders("TODO: fill this in") == 1

    def test_hook_side_agrees(self):
        hook = _hook_side()
        text = hook._strip_inline_code("Set `{name}` here, and {real} there.")
        assert sum(len(p.findall(text)) for p in hook.PLACEHOLDER_RES) == 1


class TestSurfaceCoversRoutersAndMemory:
    def test_engine_surface_includes_memory_and_routers(self, tmp_path):
        _c12_repo(tmp_path)
        found = {p.relative_to(tmp_path).as_posix() for p in _iter_surface_files(tmp_path)}
        assert "memory/note.md" in found
        assert "pkg/CLAUDE.md" in found

    def test_hook_surface_includes_memory_and_routers(self, tmp_path):
        _c12_repo(tmp_path)  # not a git repo: exercises the pruned-walk fallback
        hook = _hook_side()
        found = {hook._rel(p, tmp_path) for p in hook.iter_surface(tmp_path)}
        assert "memory/note.md" in found
        assert "pkg/CLAUDE.md" in found

    def test_neither_half_reads_a_dependency_tree_or_a_nested_repo(self, tmp_path):
        """An npm package ships its own CLAUDE.md and the classifier calls
        node_modules/ public; a nested repository is a foreign project. The
        shared walk prunes both on both halves (the review's off-tree shapes)."""
        _c12_repo(tmp_path)
        (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
        (tmp_path / "node_modules" / "pkg" / "CLAUDE.md").write_text("# dep\n", encoding="utf-8")
        (tmp_path / "vendor" / "sub" / ".git").mkdir(parents=True)
        (tmp_path / "vendor" / "sub" / "CLAUDE.md").write_text("# foreign\n", encoding="utf-8")
        hook = _hook_side()
        engine = {p.relative_to(tmp_path).as_posix() for p in _iter_surface_files(tmp_path)}
        tools = {hook._rel(p, tmp_path) for p in hook.iter_surface(tmp_path)}
        for rel in ("node_modules/pkg/CLAUDE.md", "vendor/sub/CLAUDE.md"):
            assert rel not in engine, rel
            assert rel not in tools, rel
        assert "pkg/CLAUDE.md" in engine and "pkg/CLAUDE.md" in tools

    def test_neither_half_reads_the_assets_mirror_routers(self, tmp_path):
        _c12_repo(tmp_path)
        (tmp_path / "espalier" / "assets").mkdir(parents=True)
        (tmp_path / "espalier" / "assets" / "CLAUDE.md").write_text("# mirror\n", encoding="utf-8")
        hook = _hook_side()
        engine = {p.relative_to(tmp_path).as_posix() for p in _iter_surface_files(tmp_path)}
        tools = {hook._rel(p, tmp_path) for p in hook.iter_surface(tmp_path)}
        assert "espalier/assets/CLAUDE.md" not in engine
        assert "espalier/assets/CLAUDE.md" not in tools


class TestDiscoveryLoadedSurfacesAreNotOrphans:
    """A folder router is loaded by Claude Code's folder ladder and a memory note
    by the recall index; neither is reached by a link, so 'nothing references it'
    is not a finding. Widening the surface without this manufactured 12 phantom
    orphans on the live tree (measured 2026-09-08)."""

    _MATRIX = {
        "CLAUDE.md": ["docs/x.md"],
        "docs/x.md": [],
        "pkg/CLAUDE.md": [],
        "memory/note.md": [],
        "docs/lonely.md": [],
    }

    def test_engine_exempts_routers_and_memory(self):
        assert find_orphans(dict(self._MATRIX), root=None) == ["docs/lonely.md"]

    def test_hook_side_agrees(self):
        hook = _hook_side()
        assert hook.find_orphans(dict(self._MATRIX), root=None) == ["docs/lonely.md"]


class TestRecordSurfacesAreNotResidueScanned:
    """A findings corpus that quotes a template string is content, not residue,
    and the same doc's stale pointers are expected aging (Core Rule 13). Both
    halves skip the canon's record surfaces in the quality scan; the ordinary doc
    with prose residue still fires, so the exemption is not a blanket."""

    def test_engine(self, tmp_path):
        _c12_repo(tmp_path)
        descs = [f.description for f in _erp.detect_quality_signals(tmp_path)
                 if "placeholder" in f.description]
        assert descs == ["2 placeholder patterns in docs/draft.md"], descs

    def test_hook_side(self, tmp_path):
        _c12_repo(tmp_path)
        hook = _hook_side()
        descs = [f["description"] for f in hook.placeholder_findings(tmp_path)]
        assert descs == ["2 placeholder(s) in docs/draft.md"], descs

    def test_the_shipped_catalog_is_still_residue_scanned(self, tmp_path):
        """docs/FAILURE_MODES.md is a record for its counts and a seed doc
        adopters edit: residue there stays reportable on both halves."""
        _c12_repo(tmp_path)
        (tmp_path / "docs" / "FAILURE_MODES.md").write_text(
            "# Catalog\n\nTODO: describe the failure.\n", encoding="utf-8"
        )
        hook = _hook_side()
        assert any("FAILURE_MODES.md" in f["description"]
                   for f in hook.placeholder_findings(tmp_path))
        assert any("FAILURE_MODES.md" in f.description
                   for f in _erp.detect_quality_signals(tmp_path))

    def test_hook_side_severity_matches_the_engine_rule(self, tmp_path):
        _c12_repo(tmp_path)
        (tmp_path / "docs" / "draft.md").write_text(
            "# Draft\n\n{a} {b} {c} {d} TODO: five.\n", encoding="utf-8"
        )
        hook = _hook_side()
        [finding] = hook.placeholder_findings(tmp_path)
        assert finding["severity"] == "high"
        [engine] = [f for f in _erp.detect_quality_signals(tmp_path)
                    if "placeholder" in f.description]
        assert engine.severity == "high"


class TestReflectTwinParity:
    """The forced twins across the no-import boundary, pinned value-for-value
    (the pattern the pair already uses for LOCAL_ONLY_PREFIXES and
    DISCOVERY_DIRS)."""

    def test_placeholder_patterns_match_pattern_for_pattern(self):
        hook = _hook_side()
        assert [p.pattern for p in hook.PLACEHOLDER_RES] == \
            [p.pattern for p in _erp.PLACEHOLDER_PATTERNS]
        assert [p.flags for p in hook.PLACEHOLDER_RES] == \
            [p.flags for p in _erp.PLACEHOLDER_PATTERNS]

    def test_residue_exempt_surfaces_are_the_canon_minus_the_shipped_catalog(self):
        """The canon answers "is a stale number here expected aging?"; residue
        exemption answers "is quoted residue here content?". Same set but for
        docs/FAILURE_MODES.md, a catalog adopters receive and edit -- so a canon
        change still reds here, and the carve-out is pinned in both directions."""
        from espalier.claim_extractor import RECORD_SURFACES as canon

        hook = _hook_side()
        assert "docs/FAILURE_MODES.md" in canon
        expected = set(canon) - {"docs/FAILURE_MODES.md"}
        assert set(hook.RESIDUE_EXEMPT_SURFACES) == expected
        assert set(_erp.RESIDUE_EXEMPT_SURFACES) == expected

    def test_the_fence_grammar_matches_the_hook_stacks(self):
        """The engine's sparse-section parser walks fences with a forced twin of
        _hook_utils.next_fence_state, the hook stack's one fence grammar; pinned
        by pattern and by the state after each line of a walk that exercises
        every rule (tilde vs backtick, a shorter closer, an info string, an
        indent past three spaces)."""
        import importlib.util
        import sys

        from espalier import reflect_protocol as erp

        hooks = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
        sys.path.insert(0, str(hooks))
        sys.path.insert(0, str(hooks.parent))
        try:
            spec = importlib.util.spec_from_file_location("_c62_hook_utils", hooks / "_hook_utils.py")
            hu = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hu)
        finally:
            sys.path.remove(str(hooks))
            sys.path.remove(str(hooks.parent))
        assert erp._FENCE_RE.pattern == hu._FENCE_RE.pattern
        walk = ["text", "~~~~", "```", "~~~", "~~~~ x", "~~~~~", "    ```", "```py",
                "````", "```", "  ````  ", "## h", "~~~", "~~~"]
        ours, theirs = None, None
        for line in walk:
            ours = erp._next_fence_state(line, ours)
            theirs = hu.next_fence_state(line, theirs)
            assert ours == theirs, (line, ours, theirs)

    def test_the_seed_stamp_reader_matches_the_engines(self, tmp_path):
        """The hook twin cannot import managed_markers, so it carries the stamp
        regex and scan width inline; pinned by value and by behaviour on the
        shapes the engine's reader folds (a BOM, CRLF) and refuses."""
        from espalier import managed_markers as mm

        hook = _hook_side()
        assert hook._SEED_STAMP_RE.pattern == mm.SEED_STAMP_RE.pattern
        assert hook._SEED_STAMP_SCAN_BYTES == mm.SEED_STAMP_SCAN_BYTES
        stamp = "<!-- espalier:seed-version v0.8.0 sha256:" + "a" * 64 + " -->"
        cases = {
            "lf.md": (stamp + "\n# Seed\n").encode("utf-8"),
            "crlf_bom.md": ("\ufeff" + stamp + "\r\n# Seed\r\n").encode("utf-8"),
            "plain.md": b"# Mine\nbody\n",
            "second_line.md": ("# Mine\n" + stamp + "\n").encode("utf-8"),
        }
        for name, data in cases.items():
            (tmp_path / name).write_bytes(data)
            assert hook._is_init_seed(tmp_path / name) == mm.path_has_seed_stamp(tmp_path / name), name
        assert hook._is_init_seed(tmp_path / "missing.md") is False

    def test_orphan_exemptions_inline_code_and_walk_prune_match(self):
        hook = _hook_side()
        assert tuple(hook.ORPHAN_EXEMPT_PREFIXES) == tuple(_erp.ORPHAN_EXEMPT_PREFIXES)
        assert hook._INLINE_CODE_RE.pattern == _erp._INLINE_CODE_RE.pattern
        assert hook._INLINE_CODE_RE.flags == _erp._INLINE_CODE_RE.flags
        assert set(hook._WALK_SKIP_DIRS) == set(_erp._WALK_SKIP_DIRS)

    def test_three_hits_are_medium_on_both_halves(self, tmp_path):
        """The severity boundary sits at exactly three; an off-by-one on either
        side leaves every other test green (the review's green-while-disagreeing
        edit)."""
        _c12_repo(tmp_path)
        (tmp_path / "docs" / "draft.md").write_text(
            "# Draft\n\n{a} {b} TODO: three.\n", encoding="utf-8"
        )
        hook = _hook_side()
        [finding] = hook.placeholder_findings(tmp_path)
        assert finding["severity"] == "medium"
        [engine] = [f for f in _erp.detect_quality_signals(tmp_path)
                    if "placeholder" in f.description]
        assert engine.severity == "medium"

    def test_a_tilde_fence_hides_residue_on_both_halves(self):
        text = "Prose\n~~~\n{name} TODO: inside\n~~~\nAfter\n"
        assert _count_placeholders(text) == 0
        hook = _hook_side()
        stripped = hook._strip_inline_code(hook._strip_fences(text))
        assert sum(len(p.findall(stripped)) for p in hook.PLACEHOLDER_RES) == 0

    @pytest.mark.contract
    def test_both_halves_enumerate_one_surface_on_the_live_tree(self):
        """Derived, never typed: the routers and memory notes both halves must
        cover come from classify_release_path over the tracked tree -- an oracle
        that is NOT either walker, which is the point of the assertion.

        Carried a direct ``@pytest.mark.full_tree`` until 2026-09-23. The
        population comes through the git oracle, so on a seeded release export
        it is the shipped tree and the row passes there (measured under the
        self-expiry audit); on a giteless extract the oracle raises and the
        row skips. The mark is the registry's to apply, never a decorator's
        (tests/test_marker_parity.py pins that)."""
        from espalier.surface_contract import classify_release_path
        from tests._git_oracle import GitAnswerUnavailable, require_tracked_paths

        root = Path(__file__).resolve().parent.parent
        hook = _hook_side()
        engine = {p.resolve().relative_to(root).as_posix() for p in _iter_surface_files(root)}
        tools = {hook._rel(p.resolve(), root)
                 for p in hook.iter_surface(root) if p.suffix == ".md"}
        assert engine == tools, sorted(engine ^ tools)
        try:
            tracked = require_tracked_paths(root, "*CLAUDE.md", "memory/*.md", minimum=10,
                                            what="routers and memory notes")
        except GitAnswerUnavailable as exc:  # pragma: no cover - not a git checkout
            pytest.skip(f"tracked-set population unavailable: {exc}")
        routers = {p for p in tracked if p.endswith("CLAUDE.md")
                   and classify_release_path(p) == "public"
                   and not p.startswith("espalier/assets/")}
        memory = {p for p in tracked if p.startswith("memory/") and p.endswith(".md")}
        assert routers <= engine, sorted(routers - engine)
        assert memory <= engine, sorted(memory - engine)


# ─── A fresh adopter init reads as coherent (section C62) ────────────────────

_C62_BODY = "\n".join([
    "The first line of real content in this control file.",
    "The second line of real content in this control file.",
    "The third line of real content in this control file.",
])
#: The controls an adopter could plausibly add. Names no seed's text contains,
#: because both twins' basename fallback is a substring match.
_C62_CONTROLS = {
    ".claude/rules/zqtesting.md": "# Testing rules\n\n" + _C62_BODY + "\n",
    ".claude/rules/sub/zqscoped.md": (
        "---\npaths: src/**\n---\n# Scoped rules\n\n" + _C62_BODY + "\n"),
    ".claude/output-styles/zqstyle.md": (
        "---\nname: Zq style\n---\n# Zq style\n\n" + _C62_BODY + "\n"),
    "docs/zqmine-control.md": "# Mine\n\n" + _C62_BODY + "\n",
    "docs/zqheading-control.md": (
        "# Heading control\n\n" + _C62_BODY + "\n\n## Left empty\n\n## Filled\n\n"
        + _C62_BODY + "\n"),
}


@pytest.fixture(scope="module")
def c62_tree(adopter_tree, tmp_path_factory):
    """A copy of the adopter's freshly initialised tree plus the controls: two
    unlinked rule files (Claude Code loads them, no link needed), one unlinked
    doc (the one real orphan), and one linked doc holding one real empty
    section. Copied, because ``adopter_tree`` is session-shared."""
    import shutil

    tree = tmp_path_factory.mktemp("c62") / "tree"
    shutil.copytree(adopter_tree, tree, symlinks=True)
    for rel, text in _C62_CONTROLS.items():
        path = tree / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    claude = tree / "CLAUDE.md"
    claude.write_bytes(claude.read_bytes()
                       + b"\nSee [the heading control](docs/zqheading-control.md).\n")
    return tree


def _c62_hook_report(tree: Path, monkeypatch, capsys) -> dict:
    """The DEPLOYED hook twin's ``--pass 1 --json`` report over ``tree`` -- the
    copy reflect_trigger runs on an adopter's tree, not this checkout's source
    -- driven in-process from the tree's own file, so this module stays in the
    fast slice."""
    import importlib.util
    import json
    import sys

    path = tree / "tools" / "cc" / "reflect_protocol.py"
    spec = importlib.util.spec_from_file_location("_c62_deployed_reflect", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.chdir(tree)
    monkeypatch.setattr(sys, "argv", [str(path), "--pass", "1", "--json"])
    capsys.readouterr()
    assert mod.main() == 0
    return json.loads(capsys.readouterr().out)


def _c62_reflect_trigger():
    import importlib.util
    import sys

    hooks = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
    spec = importlib.util.spec_from_file_location("_c62_reflect_trigger", hooks / "reflect_trigger.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(hooks))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(hooks))
    return mod


class TestAFreshInitReadsAsCoherent:
    """Section C62's one oracle: on a freshly initialised adopter tree, both
    reflect twins report only the drift the adopter caused. Before the fix
    both twins listed init's unlinked seeds and the two rule files as
    orphans, reflect-deep counted dozens of empty sections in files init
    wrote, and the advisory carried counts with no file name."""

    def test_the_hook_twin_reports_only_the_orphan_control(self, c62_tree, monkeypatch, capsys):
        report = _c62_hook_report(c62_tree, monkeypatch, capsys)
        found = [(f["kind"], f["description"].split()[0]) for f in report["findings"]]
        assert found == [("orphan", "docs/zqmine-control.md")], found

    def test_the_engine_reports_the_orphan_and_the_one_empty_section(self, c62_tree):
        rp = run_reflect_pass(c62_tree)
        found = sorted((f.kind, f.description) for f in rp.findings)
        orphans = [d for k, d in found if k == "orphan"]
        assert orphans == ["docs/zqmine-control.md is not referenced by any other surface file"], found
        sparse = [d for _k, d in found if "empty section" in d]
        assert len(sparse) == 1 and sparse[0].startswith("1 empty section in docs/zqheading-control.md"), found
        assert len(found) == 2, found

    def test_the_advisory_names_the_orphan_and_not_the_empty_section(self, c62_tree, monkeypatch, capsys):
        import json

        report = _c62_hook_report(c62_tree, monkeypatch, capsys)
        rt = _c62_reflect_trigger()
        rt._render_reflect_report(report)
        # The hook prints its ONE JSON object at the end of a run, not where the
        # advisory is kept (two stdout JSON lines fail the whole parse): render
        # the collector as `_run_main` does.
        rt._hook_utils.emit_advisories("PostToolUse")
        context = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
        assert "docs/zqmine-control.md" in context, context
        assert "empty section" not in context, context


class TestExemptFilesAreStillLinkAndResidueChecked:
    """C62's exemptions are orphan-only. A rule file and a stamped seed still have
    their links checked and their residue read on both twins, so a later change
    that widened an exemption into the discovery dirs (which the quality scan
    skips) would red here rather than switch the checks off unseen."""

    _STAMP = "<!-- espalier:seed-version v0.8.0 sha256:" + "a" * 64 + " -->\n"

    def _tree(self, root: Path) -> None:
        files = {
            "CLAUDE.md": "# Project\n\nThe project overview, with no links.\n",
            ".claude/rules/zqbroken.md": (
                "# Rules\n\nSee [the guide](../../docs/zqgone.md).\n"
                "TODO: fill this in.\nA third line of rule text.\n"),
            ".claude/output-styles/zqstyle.md": (
                "# Style\n\nLine one of the style.\nLine two.\nLine three.\n"),
            "docs/zqstamped.md": (
                self._STAMP + "# Stamped\n\nSee [nowhere](zqmissing.md).\n"
                "Line two of the seed.\nLine three of the seed.\n"),
        }
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))

    def _assert_checked(self, findings: list[tuple[str, str]]) -> None:
        descriptions = [d for _k, d in findings]
        assert any(d.startswith("Broken link in .claude/rules/zqbroken.md") for d in descriptions), findings
        assert any(d.startswith("Broken link in docs/zqstamped.md") for d in descriptions), findings
        assert any("placeholder" in d and ".claude/rules/zqbroken.md" in d for d in descriptions), findings
        assert not [d for k, d in findings if k == "orphan"], findings

    def test_the_engine_still_checks_them(self, tmp_path):
        self._tree(tmp_path)
        self._assert_checked([(f.kind, f.description) for f in run_reflect_pass(tmp_path).findings])

    def test_the_hook_twin_still_checks_them(self, tmp_path, monkeypatch, capsys):
        import json
        import sys

        self._tree(tmp_path)
        hook = _hook_side()
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["reflect_protocol.py", "--pass", "1", "--json"])
        capsys.readouterr()
        assert hook.main() == 0
        report = json.loads(capsys.readouterr().out)
        self._assert_checked([(f["kind"], f["description"]) for f in report["findings"]])
