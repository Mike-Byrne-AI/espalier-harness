"""TP-38: tests for the ``SurfaceMatrix`` classifier + canonical
parser.

The matrix file itself is validated by
``tests/test_surface_support_matrix.py`` (TP-36). This module
pins the python-API consumers: the classifier that ``espalier
scope-check`` uses to tag each affected symbol in pack pre-flight.
Without this contract a regression in ``classify_path`` or the
matrix row-parser would silently mis-tag affected symbols during
scope-check, producing reference graphs the pack author cannot
trust — the surface-classifier output is the seed for every
downstream pack-execution decision.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from espalier.surface_matrix import (
    SurfaceMatrix,
    SurfaceRow,
    load_matrix,
    parse_matrix_rows,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_MATRIX = REPO_ROOT / "docs" / "SURFACE_SUPPORT_MATRIX.md"


SAMPLE_MATRIX = """# Header text

## Status vocabulary

…

## Matrix

| Surface | Status | Guarding mechanism | Release guarantee | Notes |
|---|---|---|---|---|
| Main session Write/Edit | guarded | PreToolUse | yes | n |
| Subagents (built-in) | guarded | frontmatter | yes | n |
| Agent teams | deferred | docs only | no | n |
| MCP tools (external) | documented-only | none | no | n |

## After
"""


class TestParseMatrixRows:
    def test_parses_sample(self):
        rows = parse_matrix_rows(SAMPLE_MATRIX)
        assert len(rows) == 4
        assert rows[0]["Surface"] == "Main session Write/Edit"
        assert rows[0]["Status"] == "guarded"

    def test_empty_when_no_table(self):
        assert parse_matrix_rows("no table here") == []

    def test_stops_at_first_non_table_line(self):
        rows = parse_matrix_rows(SAMPLE_MATRIX)
        # Should not include the "## After" header
        surfaces = {r["Surface"] for r in rows}
        assert "After" not in surfaces

    def test_cells_are_sanitised(self):
        """Round-6: ASCII control characters in matrix cells must be
        stripped. A rogue PR landing an ANSI cursor-reposition escape
        in any cell would otherwise rewrite the operator's terminal
        when scope-check prints the report."""
        text = """## Matrix

| Surface | Status | Guarding mechanism | Release guarantee | Notes |
|---|---|---|---|---|
| Sneaky | guarded\x1b[2J\x1b[H | x | yes | with ctrl-char\x07 in notes |
"""
        rows = parse_matrix_rows(text)
        assert len(rows) == 1
        # Control chars are absent from every cell.
        for v in rows[0].values():
            assert all(0x20 <= ord(c) <= 0x7e or c in " \t" for c in v) or all(ord(c) > 0x1f and ord(c) != 0x7f for c in v), (
                f"control char present in cell: {v!r}"
            )
        assert "\x1b" not in rows[0]["Status"]
        assert "\x07" not in rows[0]["Notes"]

    def test_sanitize_cell_strips_unicode_threat_classes(self):
        """TP-224 (TQ-coverage-engine-2): the docstring of ``_sanitize_cell``
        justifies the function via Unicode threats — U+202E RTL OVERRIDE,
        zero-width U+200B, LINE/PARAGRAPH SEPARATOR U+2028/2029, bidi
        isolates U+2066-2069 — but pre-224 the only test fed ASCII control
        chars, leaving the entire Unicode half of ``_CONTROL_CHAR_RE``
        behaviorally uncovered. Each class below maps to one character range
        in the regex; deleting any range turns the matching assertion RED.
        """
        from espalier.surface_matrix import _sanitize_cell

        # Use \uXXXX ESCAPES, not literal characters: a literal U+2028/U+2029
        # LINE/PARAGRAPH SEPARATOR can collapse to an ordinary space when the
        # test source is copied through a heredoc / some editors / git filters
        # (verified this session), which would make the test assert against a
        # space and false-fail. Escapes round-trip exactly.
        threats = {
            "U+202E RTL OVERRIDE": "\u202e",
            "U+200B zero-width space": "\u200b",
            "U+200F RTL mark": "\u200f",
            "U+2028 LINE SEPARATOR": "\u2028",
            "U+2029 PARAGRAPH SEPARATOR": "\u2029",
            "U+2066 first bidi isolate": "\u2066",
            "U+2069 last bidi isolate": "\u2069",
        }
        for name, ch in threats.items():
            out = _sanitize_cell(f"safe{ch}text")
            assert ch not in out, f"{name} ({ch!r}) survived _sanitize_cell: {out!r}"
            assert out == "safetext", f"{name}: expected clean 'safetext', got {out!r}"
        # An ordinary cell is untouched (the sub() does not mangle benign text).
        assert _sanitize_cell("guarded | yes") == "guarded | yes"

    def test_mismatched_cell_count_row_is_silently_dropped(self):
        """The parser guards against rows that have a wrong cell count
        (the latent bug fixed in commit 19affdc — `\\|` in a Notes cell
        produced an extra cell and dropped the row from the output).
        Pin the guard at unit level so a future refactor that removes
        it fails CI immediately.
        """
        text = """## Matrix

| Surface | Status | Guarding mechanism | Release guarantee | Notes |
|---|---|---|---|---|
| Good row | guarded | x | yes | n |
| Bad row | guarded | x | yes | one | two | three |
| Another good | deferred | x | no | n |
"""
        rows = parse_matrix_rows(text)
        # The "Bad row" with 7 cells is dropped; the two well-formed
        # rows are kept.
        assert len(rows) == 2
        assert rows[0]["Surface"] == "Good row"
        assert rows[1]["Surface"] == "Another good"


class TestSurfaceMatrixClassifier:
    @pytest.fixture
    def matrix(self) -> SurfaceMatrix:
        return SurfaceMatrix([
            SurfaceRow("Main session Write/Edit", "guarded", "", "", ""),
            SurfaceRow("Subagents (built-in)", "guarded", "", "", ""),
            SurfaceRow("Agent teams", "deferred", "", "", ""),
            SurfaceRow("MCP tools (external)", "documented-only", "", "", ""),
        ])

    def test_token_match(self, matrix):
        """Symbol containing a literal token from the surface label
        matches that row (case-insensitive)."""
        assert matrix.classify("MCP tools") == "documented-only"

    def test_pluralization_stem_match(self, matrix):
        """Round-6 fix: ``agents`` ⊂ ``subagent`` stem-overlap so
        ``.claude/agents/`` classifies as guarded (Subagents row),
        not deferred (Agent teams row). Pre-fix the path returned
        None; with literal stem-strip it returned the WRONG status."""
        # Real-repo fixture: live matrix has both Subagents (built-in,
        # guarded) and Agent teams (deferred). Path .claude/agents/ must
        # land on Subagents.
        from pathlib import Path
        live = load_matrix(Path(__file__).parent.parent / "docs" / "SURFACE_SUPPORT_MATRIX.md")
        assert live.classify(".claude/agents/") == "guarded"

    def test_exact_surface_label(self, matrix):
        assert matrix.classify("Agent teams") == "deferred"

    def test_case_insensitive(self, matrix):
        assert matrix.classify("AGENT TEAMS") == "deferred"

    def test_unknown_symbol_returns_none(self, matrix):
        assert matrix.classify("Quantum Teleporter") is None

    def test_empty_symbol_returns_none(self, matrix):
        assert matrix.classify("") is None

    def test_substring_match(self, matrix):
        assert matrix.classify("Main session Write") == "guarded"

    def test_stem_directional_match_is_suffix_only(self):
        """TP-174b T16: the stem directional branch is suffix-only, so a
        prefix/interior over-match (``main`` ⊂ ``mainframe``) no longer
        mis-tags a benign symbol. The load-bearing ``agent`` ⊂ ``subagent``
        suffix case stays matched."""
        over = SurfaceMatrix([SurfaceRow("mainframe console", "unsupported", "", "", "")])
        assert over.classify("main session") is None
        keep = SurfaceMatrix([SurfaceRow("Subagents (built-in)", "guarded", "", "", "")])
        assert keep.classify(".claude/agents/") == "guarded"

    def test_first_branch_is_token_bounded(self):
        """TP-192 W2-1: the FIRST classify branch is token-boundary-aligned
        (the same whole-token discipline T16 applied to the stem branch). A
        benign symbol that is only a non-token-aligned interior/prefix substring
        of a surface token (``compact`` ⊂ ``Compaction``) no longer matches and
        no longer gets spuriously tagged [HIGH-RISK] by scope-check. Genuine
        token-aligned matches (the surface name itself, its stem) still resolve.

        Calibrated scope (TP-192 §6.10): single common tokens that ARE a whole
        surface token (``main`` ⊂ ``Main session …``, ``settings`` ⊂ ``Settings
        changes``) stay matched — they are structurally identical to the
        load-bearing ``ExitPlanMode`` ⊂ ``ExitPlanMode bridge`` query and the
        stem branch matches them regardless, so killing them would
        false-negative real surface queries.
        """
        m = SurfaceMatrix([SurfaceRow("Compaction", "guarded", "", "", "")])
        # non-token-aligned prefix substring → no longer matched
        assert m.classify("compact") is None
        # token-aligned matches still resolve
        assert m.classify("Compaction") == "guarded"
        assert m.classify("compaction") == "guarded"
        # multi-token subset of the surface label still matches
        mcp = SurfaceMatrix([SurfaceRow("MCP tools (external)", "documented-only", "", "", "")])
        assert mcp.classify("MCP tools") == "documented-only"


class TestLoadMatrixLive:
    """Smoke test against the actual repo matrix."""

    def test_loads_repo_matrix(self):
        matrix = load_matrix(LIVE_MATRIX)
        assert matrix.rows, "live matrix returned no rows"
        # The 5-value closed vocabulary should appear
        statuses = {r.status.lower() for r in matrix.rows}
        assert "guarded" in statuses
        assert "deferred" in statuses

    def test_missing_path_returns_empty_matrix(self, tmp_path):
        matrix = load_matrix(tmp_path / "nope.md")
        assert matrix.rows == []
        assert matrix.classify("anything") is None

    def test_classifies_known_surface_from_live(self):
        matrix = load_matrix(LIVE_MATRIX)
        # The matrix has a row for ExitPlanMode bridge (TP-36 amendment).
        assert matrix.classify("ExitPlanMode") == "deferred"
