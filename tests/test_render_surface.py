"""Tests for ``espalier.render_surface`` — the producers of
``cc/LIVE_SURFACE.md``, ``cc/COMMANDS.md``, and
``cc/PACK_MANIFEST.txt`` (the three docs the init lifecycle writes
to expose the deployed agent/command/skill surface to the operator).

Pins helper-level contracts (``_read_frontmatter_description`` YAML
parsing, ``_agent_name`` /
``_command_name`` deriving slugs from path) plus the top-level
``render_*`` shapes. Without this contract a refactor of one helper
could silently emit a malformed ``LIVE_SURFACE.md``, breaking the
SessionStart hook's surface-aware orientation and the ``/status``
slash command's 10-line report.
"""
from __future__ import annotations

import json

import pytest

from espalier.render_surface import (
    MANAGED_MARKER,
    _agent_name,
    _command_name,
    _load_stable_actions,
    _read_body_description,
    _read_description,
    _read_frontmatter_description,
    _skill_name,
    render_commands_doc,
    render_live_surface,
    render_pack_manifest,
    write_required_surface,
)


# ── _agent_name / _command_name ──────────────────────────────────────────────


class TestAgentAndCommandName:
    def test_agent_name_from_relative_path(self):
        assert _agent_name(".claude/agents/code-reviewer.md") == "code-reviewer"

    def test_command_name_from_relative_path(self):
        assert _command_name(".claude/commands/analyze.md") == "analyze"

    def test_agent_name_bare_filename(self):
        assert _agent_name("repo-analyst.md") == "repo-analyst"

    def test_command_name_bare_filename(self):
        assert _command_name("smoke.md") == "smoke"

    def test_skill_name_from_relative_path(self):
        assert _skill_name(".claude/skills/reflect/SKILL.md") == "reflect"

    def test_skill_name_is_parent_dir_not_stem(self):
        # .stem would return "SKILL"; the name is the containing directory.
        assert _skill_name(".claude/skills/adversarial/SKILL.md") == "adversarial"


# ── _read_frontmatter_description ────────────────────────────────────────────


class TestReadFrontmatterDescription:
    def test_reads_unquoted_description(self, tmp_path):
        f = tmp_path / "agent.md"
        f.write_text("---\nname: foo\ndescription: Does a thing\n---\n# Body\n", encoding="utf-8")
        assert _read_frontmatter_description(f) == "Does a thing"

    def test_reads_double_quoted_description(self, tmp_path):
        f = tmp_path / "agent.md"
        f.write_text('---\ndescription: "Quoted desc"\n---\n', encoding="utf-8")
        assert _read_frontmatter_description(f) == "Quoted desc"

    def test_reads_single_quoted_description(self, tmp_path):
        f = tmp_path / "agent.md"
        f.write_text("---\ndescription: 'Single quoted'\n---\n", encoding="utf-8")
        assert _read_frontmatter_description(f) == "Single quoted"

    def test_returns_empty_string_when_no_frontmatter(self, tmp_path):
        f = tmp_path / "agent.md"
        f.write_text("# Just a header\nNo frontmatter here.\n", encoding="utf-8")
        assert _read_frontmatter_description(f) == ""

    def test_returns_empty_string_when_no_description_field(self, tmp_path):
        f = tmp_path / "agent.md"
        f.write_text("---\nname: foo\nmodel: sonnet\n---\n# Body\n", encoding="utf-8")
        assert _read_frontmatter_description(f) == ""

    def test_returns_empty_string_for_missing_file(self, tmp_path):
        missing = tmp_path / "nonexistent.md"
        assert _read_frontmatter_description(missing) == ""

    def test_returns_empty_string_when_frontmatter_not_closed(self, tmp_path):
        f = tmp_path / "agent.md"
        f.write_text("---\ndescription: unclosed\n", encoding="utf-8")
        assert _read_frontmatter_description(f) == ""

    # ── YAML block-scalar descriptions (TP-RELEASE-01) ───────────────────

    def test_reads_folded_block_description(self, tmp_path):
        f = tmp_path / "agent.md"
        f.write_text(
            "---\n"
            "name: agent\n"
            "description: >\n"
            "  Reviews code changes for release readiness\n"
            "  and flags blocking issues.\n"
            "---\n", encoding="utf-8"
        )
        assert _read_frontmatter_description(f) == (
            "Reviews code changes for release readiness and flags blocking issues."
        )

    def test_reads_folded_chomped_block_description(self, tmp_path):
        f = tmp_path / "agent.md"
        f.write_text(
            "---\n"
            "description: >-\n"
            "  Reviews code changes\n"
            "  for release readiness.\n"
            "---\n", encoding="utf-8"
        )
        result = _read_frontmatter_description(f)
        assert ">" not in result
        assert ">-" not in result
        assert result == "Reviews code changes for release readiness."

    def test_reads_literal_block_description_as_single_renderable_line(self, tmp_path):
        f = tmp_path / "agent.md"
        f.write_text(
            "---\n"
            "description: |\n"
            "  Maintains harness docs.\n"
            "  Audits for freshness.\n"
            "---\n", encoding="utf-8"
        )
        assert _read_frontmatter_description(f) == (
            "Maintains harness docs. Audits for freshness."
        )

    def test_stops_block_description_at_next_frontmatter_key(self, tmp_path):
        f = tmp_path / "agent.md"
        f.write_text(
            "---\n"
            "description: >\n"
            "  Understands how Espalier-Harness's modules connect\n"
            "  and reviews changes.\n"
            "tools: Read, Grep, Glob\n"
            "model: opus\n"
            "---\n", encoding="utf-8"
        )
        result = _read_frontmatter_description(f)
        assert "tools:" not in result
        assert "Read, Grep, Glob" not in result
        assert "model:" not in result
        assert result == (
            "Understands how Espalier-Harness's modules connect and reviews changes."
        )

    def test_never_returns_raw_yaml_block_marker(self, tmp_path):
        # Real agent-style shape from .claude/agents/architecture-analyst.md.
        f = tmp_path / "architecture-analyst.md"
        f.write_text(
            "---\n"
            "name: architecture-analyst\n"
            "description: >\n"
            "  Understands how Espalier-Harness's modules connect and reviews changes for architectural\n"
            "  consistency. Flags layer boundary violations.\n"
            "tools: Read, Grep, Glob, Bash(python *), Bash(git *)\n"
            "model: opus\n"
            "---\n", encoding="utf-8"
        )
        result = _read_frontmatter_description(f)
        for marker in (">", ">-", ">+", "|", "|-", "|+"):
            assert result != marker, (
                f"_read_frontmatter_description leaked raw YAML block marker {marker!r}; "
                f"result was {result!r}"
            )
        assert result.startswith("Understands how Espalier-Harness's modules connect")

    @pytest.mark.parametrize("marker", ["|2", ">2", "|-2", "|2-", ">9"])
    def test_block_scalar_with_indent_indicator_not_leaked(self, tmp_path, marker):
        """TP-174a: a block-scalar header with an explicit indentation
        indicator must route to the block branch (body fallback), not leak the
        raw '|2' marker as the description. Pre-fix these were not in
        _BLOCK_SCALAR_MARKERS and leaked verbatim."""
        f = tmp_path / "a.md"
        f.write_text(
            "---\n"
            "name: x\n"
            f"description: {marker}\n"
            "  Real body line\n"
            "---\n"
            "# Body\nFallback prose.\n",
            encoding="utf-8",
        )
        result = _read_frontmatter_description(f)
        assert result == "Real body line", f"leaked marker; got {result!r}"

    def test_plain_single_line_after_gt_not_treated_as_block(self, tmp_path):
        """A genuine single-line value beginning with '>' (non-digit/chomp
        content) must stay on the single-line path — no over-fire."""
        f = tmp_path / "a.md"
        f.write_text(
            "---\nname: x\ndescription: > see docs\n---\n", encoding="utf-8"
        )
        assert _read_frontmatter_description(f) == "> see docs"

    def test_handles_block_scalar_with_blank_line_in_body(self, tmp_path):
        # Blank lines inside the body are folded out by whitespace
        # normalization; they must not terminate the block early.
        f = tmp_path / "agent.md"
        f.write_text(
            "---\n"
            "description: >\n"
            "  First sentence.\n"
            "\n"
            "  Second sentence.\n"
            "tools: Read\n"
            "---\n", encoding="utf-8"
        )
        result = _read_frontmatter_description(f)
        assert result == "First sentence. Second sentence."
        assert "tools" not in result


# ── _read_body_description ───────────────────────────────────────────────────


class TestReadBodyDescription:
    """Post-v0.6.5: the body-line fallback lets commands without YAML
    frontmatter still surface their summary paragraph instead of
    rendering as ``—``. Frontmatter still wins when present; this is
    pure fallback."""

    def test_reads_single_line_body(self, tmp_path):
        f = tmp_path / "cmd.md"
        f.write_text("Run the thing once.\n\n## Usage\n", encoding="utf-8")
        assert _read_body_description(f) == "Run the thing once."

    def test_collapses_multi_line_paragraph(self, tmp_path):
        f = tmp_path / "cmd.md"
        f.write_text(
            "Execute one or more packs end-to-end with the\n"
            "single-atomic-commit-per-pack workflow.\n"
            "\n"
            "## Usage\n", encoding="utf-8"
        )
        result = _read_body_description(f)
        assert result == (
            "Execute one or more packs end-to-end with the "
            "single-atomic-commit-per-pack workflow."
        )

    def test_skips_leading_blank_lines_and_headings(self, tmp_path):
        f = tmp_path / "cmd.md"
        f.write_text("\n\n# Title\n\n## Section\n\nThe real description.\n", encoding="utf-8")
        assert _read_body_description(f) == "The real description."

    def test_skips_frontmatter_when_present(self, tmp_path):
        f = tmp_path / "cmd.md"
        f.write_text(
            "---\nname: cmd\nmodel: sonnet\n---\n"
            "Body summary after frontmatter.\n", encoding="utf-8"
        )
        assert _read_body_description(f) == "Body summary after frontmatter."

    def test_returns_empty_for_headings_only(self, tmp_path):
        f = tmp_path / "cmd.md"
        f.write_text("# Title\n## Section\n### Subsection\n", encoding="utf-8")
        assert _read_body_description(f) == ""

    def test_returns_empty_for_missing_file(self, tmp_path):
        assert _read_body_description(tmp_path / "nope.md") == ""

    def test_returns_empty_for_unclosed_frontmatter(self, tmp_path):
        f = tmp_path / "cmd.md"
        f.write_text("---\ndescription: stuck\n# never closed\n", encoding="utf-8")
        assert _read_body_description(f) == ""

    def test_stops_at_blank_after_paragraph(self, tmp_path):
        f = tmp_path / "cmd.md"
        f.write_text(
            "First paragraph line one.\n"
            "First paragraph line two.\n"
            "\n"
            "Second paragraph (NOT in description).\n", encoding="utf-8"
        )
        result = _read_body_description(f)
        assert "Second paragraph" not in result
        assert result == "First paragraph line one. First paragraph line two."

    # ── post-v0.6.6 review remediation: skip markdown noise ──────────

    def test_skips_blockquote_first_line(self, tmp_path):
        """Blockquote lines (``> ...``) are not prose summaries; skip."""
        f = tmp_path / "cmd.md"
        f.write_text("> a blockquote line\n\nreal description.\n", encoding="utf-8")
        assert _read_body_description(f) == "real description."

    def test_skips_html_comment_single_line(self, tmp_path):
        """``<!-- ... -->`` on one line is a managed-marker shape; skip.

        Critical: prevents internal markers like
        ``<!-- espalier:managed -->`` from leaking into the rendered
        surface index as a command's "description."
        """
        f = tmp_path / "cmd.md"
        f.write_text(
            "<!-- espalier:managed -->\n\n"
            "real description.\n", encoding="utf-8"
        )
        assert _read_body_description(f) == "real description."

    def test_skips_html_comment_multi_line(self, tmp_path):
        """``<!-- ... -->`` spanning multiple lines — skip through the
        matching ``-->``."""
        f = tmp_path / "cmd.md"
        f.write_text(
            "<!--\n"
            "managed marker\n"
            "do not edit\n"
            "-->\n\n"
            "real description.\n", encoding="utf-8"
        )
        assert _read_body_description(f) == "real description."

    def test_skips_code_fence_first_block(self, tmp_path):
        """``` ``` ``` `` opens a fenced code block; skip through the
        matching close fence."""
        f = tmp_path / "cmd.md"
        f.write_text(
            "```bash\n"
            "echo test\n"
            "```\n\n"
            "real description.\n", encoding="utf-8"
        )
        assert _read_body_description(f) == "real description."

    def test_skip_stack_blockquote_html_code_then_prose(self, tmp_path):
        """Multiple non-prose blocks in sequence are all skipped before
        the first prose paragraph is captured."""
        f = tmp_path / "cmd.md"
        f.write_text(
            "<!-- comment -->\n"
            "> a quote\n"
            "```python\n"
            "x = 1\n"
            "```\n"
            "# Heading\n\n"
            "Real description after all noise.\n", encoding="utf-8"
        )
        assert _read_body_description(f) == "Real description after all noise."

    def test_crlf_line_endings_parsed_correctly(self, tmp_path):
        """Windows CRLF line endings must not break the parser.
        ``splitlines()`` strips ``\\r\\n``; the parser's prose capture
        sees the same content as it would for LF input."""
        f = tmp_path / "cmd.md"
        f.write_bytes(b"First paragraph.\r\n\r\n## Section\r\n")
        assert _read_body_description(f) == "First paragraph."

    def test_returns_empty_for_empty_body_after_frontmatter(self, tmp_path):
        """A file that closes its frontmatter at EOF with no body
        returns ``""``."""
        f = tmp_path / "cmd.md"
        f.write_text("---\nname: foo\n---\n", encoding="utf-8")
        assert _read_body_description(f) == ""

    def test_unterminated_html_comment_consumes_to_eof(self, tmp_path):
        """An unclosed ``<!--`` block consumes all remaining lines;
        no prose to render."""
        f = tmp_path / "cmd.md"
        f.write_text("<!-- never closed\nstill in comment\nstill in comment\n", encoding="utf-8")
        assert _read_body_description(f) == ""

    def test_unterminated_code_fence_consumes_to_eof(self, tmp_path):
        """An unclosed code fence consumes all remaining lines;
        no prose to render."""
        f = tmp_path / "cmd.md"
        f.write_text("```python\nx = 1\nnever closed\n", encoding="utf-8")
        assert _read_body_description(f) == ""

    def test_non_prose_mid_paragraph_terminates_capture(self, tmp_path):
        """A blockquote / HTML comment / code fence in the middle of
        the capture phase ends the paragraph, just like a blank or
        heading does."""
        f = tmp_path / "cmd.md"
        f.write_text(
            "First sentence of summary.\n"
            "> mid-paragraph quote breaks it\n"
            "this part is NOT captured.\n", encoding="utf-8"
        )
        result = _read_body_description(f)
        assert "mid-paragraph" not in result
        assert "NOT captured" not in result
        assert result == "First sentence of summary."


# ── _read_description (frontmatter + body fallback) ──────────────────────────


class TestReadDescription:
    def test_frontmatter_wins_when_both_present(self, tmp_path):
        f = tmp_path / "cmd.md"
        f.write_text(
            "---\ndescription: FM wins\n---\nBody paragraph that loses.\n", encoding="utf-8"
        )
        assert _read_description(f) == "FM wins"

    def test_falls_back_to_body_when_no_frontmatter_description(self, tmp_path):
        f = tmp_path / "cmd.md"
        f.write_text("---\nname: cmd\n---\nBody-only summary.\n", encoding="utf-8")
        assert _read_description(f) == "Body-only summary."

    def test_falls_back_to_body_when_no_frontmatter_at_all(self, tmp_path):
        f = tmp_path / "cmd.md"
        f.write_text("Plain prose summary, no frontmatter.\n\n## Usage\n", encoding="utf-8")
        assert _read_description(f) == "Plain prose summary, no frontmatter."

    def test_returns_empty_when_no_description_anywhere(self, tmp_path):
        f = tmp_path / "cmd.md"
        f.write_text("# Title only\n## Section only\n", encoding="utf-8")
        assert _read_description(f) == ""


# ── _load_stable_actions ─────────────────────────────────────────────────────


class TestLoadStableActions:
    def test_loads_stable_actions_from_harness_config(self, tmp_path):
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "harness_config.json").write_text(
            json.dumps({"stable_actions": {"analyze": ["espalier analyze ."]}}),
            encoding="utf-8",
        )
        result = _load_stable_actions(tmp_path)
        assert result == {"analyze": ["espalier analyze ."]}

    def test_returns_empty_dict_when_no_harness_config(self, tmp_path):
        result = _load_stable_actions(tmp_path)
        assert result == {}

    def test_returns_empty_dict_on_malformed_json(self, tmp_path):
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "harness_config.json").write_text("not valid json", encoding="utf-8")
        assert _load_stable_actions(tmp_path) == {}

    def test_returns_empty_dict_when_stable_actions_missing(self, tmp_path):
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "harness_config.json").write_text(
            json.dumps({"profiles": ["python"]}), encoding="utf-8"
        )
        assert _load_stable_actions(tmp_path) == {}

    def test_returns_empty_dict_when_stable_actions_not_dict(self, tmp_path):
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "harness_config.json").write_text(
            json.dumps({"stable_actions": ["not", "a", "dict"]}), encoding="utf-8"
        )
        assert _load_stable_actions(tmp_path) == {}


# ── render_live_surface ───────────────────────────────────────────────────────


class TestRenderLiveSurface:
    def test_returns_string(self, tmp_path):
        result = render_live_surface(tmp_path)
        assert isinstance(result, str)

    @pytest.mark.parametrize(
        "expected",
        [
            MANAGED_MARKER,
            "# Live Surface",
            "## Agent roster",
            "## Commands",
            "## Skills",
            "## Hook architecture",
        ],
        ids=[
            "managed_marker",
            "live_surface_heading",
            "agent_roster_section",
            "commands_section",
            "skills_section",
            "hook_architecture_section",
        ],
    )
    def test_required_section_present(self, tmp_path, expected):
        """Every required section/marker is rendered into the live surface."""
        result = render_live_surface(tmp_path)
        assert expected in result, f"missing required section/marker: {expected!r}"

    def test_includes_agent_from_disk(self, tmp_path):
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "my-agent.md").write_text(
            "---\ndescription: My custom agent\n---\n# My Agent\n", encoding="utf-8"
        )
        result = render_live_surface(tmp_path)
        assert "my-agent" in result

    def test_includes_skill_from_disk(self, tmp_path):
        skill_dir = tmp_path / ".claude" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Does a focused thing\n---\n", encoding="utf-8"
        )
        result = render_live_surface(tmp_path)
        assert "/my-skill" in result
        assert "Does a focused thing" in result

    def test_includes_agent_description_from_frontmatter(self, tmp_path):
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "smart-agent.md").write_text(
            "---\ndescription: Does smart things\n---\n", encoding="utf-8"
        )
        result = render_live_surface(tmp_path)
        assert "Does smart things" in result

    def test_renders_folded_block_description_as_prose(self, tmp_path):
        """TP-RELEASE-01: agent rosters must render folded YAML block
        descriptions as prose, never as the raw block markers `>` or `|`.
        """
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "example-agent.md").write_text(
            "---\n"
            "name: example-agent\n"
            "description: >\n"
            "  Reviews code changes for release readiness\n"
            "  and flags blocking issues.\n"
            "tools: Read, Grep\n"
            "---\n", encoding="utf-8"
        )
        result = render_live_surface(tmp_path)
        assert (
            "`example-agent` -- Reviews code changes for release readiness"
            in result
        )
        assert "— >" not in result
        assert "— |" not in result

    def test_includes_stable_actions_section_when_present(self, tmp_path):
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "harness_config.json").write_text(
            json.dumps({"stable_actions": {"my-action": ["espalier audit ."]}}),
            encoding="utf-8",
        )
        result = render_live_surface(tmp_path)
        assert "## Stable actions" in result
        assert "my-action" in result

    def test_no_stable_actions_section_when_empty(self, tmp_path):
        result = render_live_surface(tmp_path)
        assert "## Stable actions" not in result

    def test_session_bootstrap_step3_references_smoke_not_audit(self, tmp_path):
        """TP-40 folded ``/audit`` into ``/smoke``. The Session-bootstrap
        template line must reflect that — previously it still pointed
        operators at ``/audit`` (a command that no longer exists)."""
        result = render_live_surface(tmp_path)
        assert "Run `/smoke` to verify surface integrity" in result, (
            "Session bootstrap step 3 must call /smoke (the post-TP-40 fold)"
        )
        # Defensive: catch a regression that re-introduces the stale form.
        assert "Run `/audit` to verify" not in result, (
            "Session bootstrap step 3 references obsolete /audit command"
        )

    def test_renders_body_description_when_no_frontmatter(self, tmp_path):
        """Commands without YAML frontmatter must still surface their
        first-paragraph summary (post-v0.6.5 fallback). Previously these
        rendered without a description."""
        cmds_dir = tmp_path / ".claude" / "commands"
        cmds_dir.mkdir(parents=True)
        (cmds_dir / "mything.md").write_text(
            "Run my thing in one paragraph.\n\n## Usage\nDetails.\n", encoding="utf-8"
        )
        result = render_live_surface(tmp_path)
        assert "`/mything` -- Run my thing in one paragraph." in result

    def test_ends_with_newline(self, tmp_path):
        result = render_live_surface(tmp_path)
        assert result.endswith("\n")


# ── render_commands_doc ───────────────────────────────────────────────────────


class TestRenderCommandsDoc:
    def test_returns_string(self, tmp_path):
        result = render_commands_doc(tmp_path)
        assert isinstance(result, str)

    def test_contains_managed_marker(self, tmp_path):
        result = render_commands_doc(tmp_path)
        assert MANAGED_MARKER in result

    def test_contains_commands_heading(self, tmp_path):
        result = render_commands_doc(tmp_path)
        assert "# Commands" in result

    def test_contains_table_header(self, tmp_path):
        result = render_commands_doc(tmp_path)
        assert "| Command | Purpose |" in result

    def test_includes_command_from_disk(self, tmp_path):
        cmds_dir = tmp_path / ".claude" / "commands"
        cmds_dir.mkdir(parents=True)
        (cmds_dir / "analyze.md").write_text(
            "---\ndescription: Re-analyze the repo\n---\n", encoding="utf-8"
        )
        result = render_commands_doc(tmp_path)
        assert "/analyze" in result

    def test_includes_command_description_from_frontmatter(self, tmp_path):
        cmds_dir = tmp_path / ".claude" / "commands"
        cmds_dir.mkdir(parents=True)
        (cmds_dir / "smoke.md").write_text(
            "---\ndescription: Fast structural integrity check\n---\n", encoding="utf-8"
        )
        result = render_commands_doc(tmp_path)
        assert "Fast structural integrity check" in result

    def test_pipe_in_description_does_not_break_table(self, tmp_path):
        """TP-174a: a description containing a literal '|' must be escaped so
        the GFM table row keeps exactly 2 columns. Pre-fix the raw '|' added a
        third column."""
        cmds_dir = tmp_path / ".claude" / "commands"
        cmds_dir.mkdir(parents=True)
        (cmds_dir / "bad.md").write_text(
            "---\ndescription: Run build | then push\n---\n", encoding="utf-8"
        )
        result = render_commands_doc(tmp_path)
        row = next(line for line in result.splitlines() if "/bad" in line)
        # Escaped pipe → still 2 data cells (3 delimiter pipes: outer + middle).
        assert row.count("|") - row.count("\\|") == 3, f"malformed row: {row!r}"
        assert "\\|" in row

    def test_uses_dash_when_no_description(self, tmp_path):
        """A file with neither a YAML description nor a prose body line
        (only a markdown heading) renders as ``—``."""
        cmds_dir = tmp_path / ".claude" / "commands"
        cmds_dir.mkdir(parents=True)
        (cmds_dir / "nodesc.md").write_text("# No frontmatter\n", encoding="utf-8")
        result = render_commands_doc(tmp_path)
        assert "/nodesc" in result
        assert " | -- |" in result

    def test_renders_body_description_when_no_frontmatter(self, tmp_path):
        """Command files without YAML frontmatter render their first-
        paragraph summary in the COMMANDS.md table (post-v0.6.5)."""
        cmds_dir = tmp_path / ".claude" / "commands"
        cmds_dir.mkdir(parents=True)
        (cmds_dir / "mything.md").write_text(
            "Do my thing in one line.\n\n## Usage\n", encoding="utf-8"
        )
        result = render_commands_doc(tmp_path)
        assert "| `/mything` | Do my thing in one line. |" in result

    def test_renders_multi_line_body_paragraph(self, tmp_path):
        """A body paragraph spanning multiple lines collapses to a
        single description (matches the folded-block frontmatter
        behavior)."""
        cmds_dir = tmp_path / ".claude" / "commands"
        cmds_dir.mkdir(parents=True)
        (cmds_dir / "multi.md").write_text(
            "Execute one or more packs end-to-end with the\n"
            "single-atomic-commit-per-pack workflow.\n"
            "\n"
            "## Usage\n", encoding="utf-8"
        )
        result = render_commands_doc(tmp_path)
        assert (
            "Execute one or more packs end-to-end with the "
            "single-atomic-commit-per-pack workflow."
        ) in result

    def test_includes_stable_actions_when_present(self, tmp_path):
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "harness_config.json").write_text(
            json.dumps({"stable_actions": {"audit": ["espalier audit ."]}}),
            encoding="utf-8",
        )
        result = render_commands_doc(tmp_path)
        assert "## Stable actions" in result

    def test_ends_with_newline(self, tmp_path):
        result = render_commands_doc(tmp_path)
        assert result.endswith("\n")


# ── render_pack_manifest ──────────────────────────────────────────────────────


class TestRenderPackManifest:
    def test_returns_string(self, tmp_path):
        result = render_pack_manifest(tmp_path)
        assert isinstance(result, str)

    def test_contains_managed_marker_comment(self, tmp_path):
        result = render_pack_manifest(tmp_path)
        assert f"# {MANAGED_MARKER}" in result

    def test_contains_version_stamp(self, tmp_path):
        """TP-189-D CAPGAP-1: the manifest carries a deploy-time version stamp
        (a #-comment, not a managed-path entry) that tracks espalier.__version__ —
        the discriminator `espalier upgrade` reads to detect a stale harness."""
        from espalier import __version__
        result = render_pack_manifest(tmp_path)
        assert f"# espalier-version: {__version__}" in result
        stamp = [l for l in result.splitlines() if l.startswith("# espalier-version:")]
        assert len(stamp) == 1  # exactly one stamp; it is a #-comment, not a path entry

    def test_always_includes_required_cc_docs(self, tmp_path):
        result = render_pack_manifest(tmp_path)
        assert "cc/LIVE_SURFACE.md" in result
        assert "cc/COMMANDS.md" in result
        assert "cc/PACK_MANIFEST.txt" in result

    def test_includes_hook_files(self, tmp_path):
        # discover_wired_hooks reads hook paths from .claude/settings.json commands,
        # not by scanning tools/cc/hooks/ on disk directly.
        import json as _json
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True)
        settings = {
            "hooks": {
                "Stop": [{"hooks": [{"command": '/usr/bin/python3 "$CLAUDE_PROJECT_DIR/tools/cc/hooks/stop_gate.py"'}]}]
            }
        }
        (claude_dir / "settings.json").write_text(_json.dumps(settings), encoding="utf-8")
        result = render_pack_manifest(tmp_path)
        assert "tools/cc/hooks/stop_gate.py" in result

    def test_includes_root_docs_when_present(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# CLAUDE\n", encoding="utf-8")
        (tmp_path / "ESPALIER_MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")
        result = render_pack_manifest(tmp_path)
        assert "CLAUDE.md" in result
        assert "ESPALIER_MEMORY.md" in result

    def test_excludes_root_docs_when_absent(self, tmp_path):
        result = render_pack_manifest(tmp_path)
        assert "CLAUDE.md" not in result

    def test_entries_are_sorted_and_unique(self, tmp_path):
        result = render_pack_manifest(tmp_path)
        lines = [
            line for line in result.splitlines()
            if line and not line.startswith("#")
        ]
        assert lines == sorted(set(lines))

    def test_ends_with_newline(self, tmp_path):
        result = render_pack_manifest(tmp_path)
        assert result.endswith("\n")


# ── write_required_surface ────────────────────────────────────────────────────


class TestWriteRequiredSurface:
    """TP-03 — write_required_surface now returns (rel, action) tuples and
    applies the 3-state marker-aware policy."""

    def test_creates_all_three_files_when_missing(self, tmp_path):
        actions = write_required_surface(tmp_path)
        assert {(r, a) for r, a in actions} == {
            ("cc/LIVE_SURFACE.md", "created"),
            ("cc/COMMANDS.md", "created"),
            ("cc/PACK_MANIFEST.txt", "created"),
        }
        for fname in ("LIVE_SURFACE.md", "COMMANDS.md", "PACK_MANIFEST.txt"):
            assert (tmp_path / "cc" / fname).exists()

    def test_preserves_unmarked_user_files(self, tmp_path):
        cc = tmp_path / "cc"
        cc.mkdir()
        # User-authored content with no marker — must be preserved.
        (cc / "LIVE_SURFACE.md").write_text("# custom\n", encoding="utf-8")
        actions = write_required_surface(tmp_path)
        rel_map = dict(actions)
        assert rel_map["cc/LIVE_SURFACE.md"] == "skipped_user_file"
        assert (cc / "LIVE_SURFACE.md").read_text(encoding="utf-8") == "# custom\n"
        # The other two are still missing → created
        assert rel_map["cc/COMMANDS.md"] == "created"
        assert rel_map["cc/PACK_MANIFEST.txt"] == "created"

    def test_non_utf8_preexisting_doc_does_not_abort_init(self, tmp_path):
        # EA-2: a non-UTF-8 pre-existing managed doc must NOT crash init. A file
        # we cannot decode as UTF-8 is not one we can prove is ours → preserve it,
        # exactly as an unmarked user file, rather than aborting the whole init.
        cc = tmp_path / "cc"
        cc.mkdir()
        # 0xff/0xfe are invalid UTF-8 start bytes → read_text("utf-8") raises
        # UnicodeDecodeError (a ValueError, NOT an OSError) at the unguarded read.
        (cc / "LIVE_SURFACE.md").write_bytes(b"\xff\xfe not valid utf-8 \x80\x81")
        actions = write_required_surface(tmp_path)  # RED before the guard
        rel_map = dict(actions)
        assert rel_map["cc/LIVE_SURFACE.md"] == "skipped_user_file"
        # The undecodable file is left byte-for-byte untouched.
        assert (cc / "LIVE_SURFACE.md").read_bytes() == b"\xff\xfe not valid utf-8 \x80\x81"
        # The other two managed docs are still absent → created (init completed).
        assert rel_map["cc/COMMANDS.md"] == "created"
        assert rel_map["cc/PACK_MANIFEST.txt"] == "created"

    def test_regenerates_managed_files(self, tmp_path):
        cc = tmp_path / "cc"
        cc.mkdir()
        # Existing managed copy — must be overwritten on rerun.
        (cc / "LIVE_SURFACE.md").write_text(
            f"<!-- {MANAGED_MARKER} -->\n# stale\n", encoding="utf-8",
        )
        actions = write_required_surface(tmp_path)
        rel_map = dict(actions)
        assert rel_map["cc/LIVE_SURFACE.md"] == "updated_managed"
        content = (cc / "LIVE_SURFACE.md").read_text(encoding="utf-8")
        assert MANAGED_MARKER in content
        assert "# stale" not in content

    def test_creates_cc_directory_if_missing(self, tmp_path):
        assert not (tmp_path / "cc").exists()
        write_required_surface(tmp_path)
        assert (tmp_path / "cc").exists()

    def test_all_unmarked_files_all_skipped(self, tmp_path):
        cc = tmp_path / "cc"
        cc.mkdir()
        for fname in ("LIVE_SURFACE.md", "COMMANDS.md", "PACK_MANIFEST.txt"):
            (cc / fname).write_text("# existing user\n", encoding="utf-8")
        actions = write_required_surface(tmp_path)
        assert all(a == "skipped_user_file" for _, a in actions)

    def test_written_files_have_managed_marker(self, tmp_path):
        write_required_surface(tmp_path)
        for fname in ("LIVE_SURFACE.md", "COMMANDS.md", "PACK_MANIFEST.txt"):
            content = (tmp_path / "cc" / fname).read_text(encoding="utf-8")
            assert MANAGED_MARKER in content, f"{fname} is missing managed marker"

    def test_second_run_is_no_drift_and_does_not_churn_mtime(self, tmp_path):
        """W5-2 (TP-177): a back-to-back re-render of byte-identical content
        reports skipped_no_drift and leaves the file (and its mtime) untouched
        instead of unconditionally rewriting + reporting updated_managed."""
        first = write_required_surface(tmp_path)
        assert all(a == "created" for _, a in first)
        mtimes = {
            rel: (tmp_path / rel).stat().st_mtime_ns
            for rel, _ in first
        }
        second = write_required_surface(tmp_path)
        rel_map = dict(second)
        assert all(a == "skipped_no_drift" for _, a in second), (
            f"expected all skipped_no_drift on identical re-render: {second}"
        )
        for rel in mtimes:
            assert (tmp_path / rel).stat().st_mtime_ns == mtimes[rel], (
                f"{rel} mtime churned on a no-drift re-render"
            )

    def test_dry_run_classifies_without_writing(self, tmp_path):
        """DEF-726: `upgrade`'s preview reads the cc/ surface through THIS
        classifier with its writes switched off, so the preview and the deploy
        cannot disagree about a doc. On an empty tree the dry run reports every
        doc as `created` and creates nothing -- not even the cc/ directory; on
        a stale managed doc it reports `updated_managed` and leaves the bytes
        alone; and the write that follows lands exactly the actions the dry
        run predicted."""
        assert not (tmp_path / "cc").exists()
        preview = write_required_surface(tmp_path, dry_run=True)
        assert {(r, a) for r, a in preview} == {
            ("cc/LIVE_SURFACE.md", "created"),
            ("cc/COMMANDS.md", "created"),
            ("cc/PACK_MANIFEST.txt", "created"),
        }
        assert not (tmp_path / "cc").exists(), "a dry run created the directory"

        cc = tmp_path / "cc"
        cc.mkdir()
        stale = f"<!-- {MANAGED_MARKER} -->\n# stale\n"
        (cc / "LIVE_SURFACE.md").write_text(stale, encoding="utf-8")
        predicted = dict(write_required_surface(tmp_path, dry_run=True))
        assert predicted["cc/LIVE_SURFACE.md"] == "updated_managed"
        assert (cc / "LIVE_SURFACE.md").read_text(encoding="utf-8") == stale
        assert not (cc / "COMMANDS.md").exists()
        assert dict(write_required_surface(tmp_path)) == predicted, (
            "the dry run and the write classified the same tree differently"
        )
        assert "# stale" not in (cc / "LIVE_SURFACE.md").read_text(encoding="utf-8")


class TestCoreFlowSection:
    """TP-241: the SessionStart banner's command line is truth-sourced from the
    rendered ``## Core flow`` section, not a hardcoded sibling tuple in the hook.
    """

    def test_render_emits_core_flow_section(self):
        from pathlib import Path

        from espalier.render_surface import CORE_FLOW_COMMANDS, render_commands_doc

        root = Path(__file__).resolve().parent.parent
        doc = render_commands_doc(root)
        assert "## Core flow" in doc
        section = doc.split("## Core flow", 1)[1]
        for name in CORE_FLOW_COMMANDS:
            assert f"`{name}`" in section, f"{name} missing from Core flow section"

    def test_core_flow_omits_undiscovered_name(self, monkeypatch):
        # A core name that is NOT a discovered command must never be emitted, so
        # a stale entry can't linger in the banner.
        from pathlib import Path

        from espalier import render_surface as rs

        root = Path(__file__).resolve().parent.parent
        monkeypatch.setattr(
            rs, "CORE_FLOW_COMMANDS", tuple(rs.CORE_FLOW_COMMANDS) + ("/nope-not-real",)
        )
        doc = rs.render_commands_doc(root)
        section = doc.split("## Core flow", 1)[1]
        assert "/nope-not-real" not in section

    # ── 441-E / §18.4: the DELETION direction, which nothing above covers ──
    #
    # `test_render_emits_core_flow_section` loops CORE_FLOW_COMMANDS and asserts
    # each is present -- population derived FROM the subject, so removing a name
    # removes its own assertion and the loop just runs one iteration shorter.
    # `test_core_flow_omits_undiscovered_name` drives the ADDITION direction
    # only (`+ ("/nope-not-real",)`). Neither can see a narrowing.
    #
    # The three docs below hand-author the banner line verbatim, so the joined
    # tuple is an INDEPENDENT expectation: narrow the constant and the expected
    # string shortens while the docs still carry six names -> RED.
    #
    # Population is HAND-AUTHORED and count-pinned on purpose. Deriving the doc
    # list from a glob or a manifest would reproduce the very class this test
    # closes -- drop a doc from the list and coverage would shrink silently.
    _COMMANDS_LINE_DOCS = (
        "docs/QUICKSTART.md",   # NOT overlaid into adopter trees (fusion_manifest.py:79)
        "docs/WORKFLOW.md",     # overlaid into adopter trees (fusion_manifest.py:70)
        "docs/HOOKS.md",        # overlaid into adopter trees (fusion_manifest.py:69)
    )

    def test_docs_banner_line_matches_the_core_flow_tuple(self):
        """A narrowed CORE_FLOW_COMMANDS must red, not go quiet.

        This drift ALREADY HAPPENED ONCE and is filed at line 509 of the
        retired findings corpus (record branch, b3e36ae:docs/known-findings.md).
        Two of the three docs are overlaid into
        adopter trees by fusion, so the stale copy ships.

        ⚠ Satisfying a red here by editing the three docs is the WRONG fix and
        leaves the hook's fallback tuple stale -- see
        tests/test_hook_constant_parity.py::test_core_flow_fallback_matches_sot,
        which must fail alongside this one.
        """
        from pathlib import Path

        from espalier.render_surface import CORE_FLOW_COMMANDS

        assert len(self._COMMANDS_LINE_DOCS) == 3, (
            "the hand-authored doc roster changed size; a shrinking roster is "
            "exactly the §18.4 defect this test exists to close -- re-derive "
            "with: command grep -rn 'Commands: /status' docs/"
        )
        root = Path(__file__).resolve().parent.parent
        expected = "Commands: " + " ".join(CORE_FLOW_COMMANDS)
        for rel in self._COMMANDS_LINE_DOCS:
            body = (root / rel).read_text(encoding="utf-8")
            assert expected in body, (
                f"{rel} does not carry the banner line {expected!r}.\n"
                "If CORE_FLOW_COMMANDS was just narrowed, RESTORE THE NAME -- "
                "do not edit the docs to match. If a command was genuinely "
                "retired, update all three docs AND "
                "session_start._CORE_FLOW_COMMANDS, then run "
                "python3 scripts/sync_asset_docs.py for the two overlaid docs."
            )

    def test_the_doc_roster_is_still_a_hand_written_literal(self):
        """441-E: the count pin above catches a SHRINKING roster; it cannot
        catch a roster that is COLLAPSED into a derivation.

        Replacing ``_COMMANDS_LINE_DOCS`` with, say, a glob over ``docs/`` or a
        read of the fusion manifest would keep the count at 3 and keep the suite
        green while turning a hand-authored witness into one more derived
        population -- reproducing, inside the fix, the very class the fix
        closes. AST-level because the runtime value would be identical.
        """
        import ast
        from pathlib import Path

        source = Path(__file__).resolve().read_text(encoding="utf-8")
        node = None
        for stmt in ast.walk(ast.parse(source)):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if (isinstance(target, ast.Name)
                            and target.id == "_COMMANDS_LINE_DOCS"):
                        node = stmt.value
        why = (
            "_COMMANDS_LINE_DOCS must stay a literal tuple of string literals. "
            "Deriving it from a glob, a manifest, or the fusion INCLUDE list "
            "makes it shrink silently with whatever it derives from -- which is "
            "the §18.4 defect this whole test exists to close."
        )
        assert isinstance(node, (ast.Tuple, ast.List)), why
        assert node.elts, why
        for element in node.elts:
            assert (
                isinstance(element, ast.Constant) and isinstance(element.value, str)
            ), why
