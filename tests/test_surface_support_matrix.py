"""TP-36: validate the surface support matrix format and required
surfaces.

The matrix at ``docs/SURFACE_SUPPORT_MATRIX.md`` is normative.
Pins five invariants:

1. The file exists.
2. The markdown table has exactly the required columns.
3. Status values are from the closed vocabulary.
4. Every required surface appears at least once.
5. Public docs don't overclaim coverage of deferred/unsupported
   surfaces.

TP-38: the table parser moved to ``espalier/surface_matrix.py``
as the single source of truth so ``espalier scope-check`` consumes
the same rows the test validates. Without this contract a hand-
edit of the matrix could silently introduce a typo'd status value
or a new column, breaking the parser AND the docs without the
test surfacing which side drifted first.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from espalier.surface_contract import get_public_doc_relpaths
from espalier.surface_matrix import (
    REQUIRED_COLUMNS as _CANON_COLUMNS,
    VALID_STATUSES as _CANON_STATUSES,
    parse_matrix_rows,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
MATRIX = REPO_ROOT / "docs" / "SURFACE_SUPPORT_MATRIX.md"

VALID_STATUSES = set(_CANON_STATUSES)
REQUIRED_COLUMNS = list(_CANON_COLUMNS)

REQUIRED_SURFACES = {
    "Main session Write/Edit",
    "Skills",
    "Subagents",
    "Agent teams",
    "MCP tools",
    "Settings changes",
    "Compaction",
    "ExitPlanMode",
}


def _parse_matrix_rows() -> list[dict[str, str]]:
    """Extract rows from the matrix table — delegates to the canonical parser."""
    rows = parse_matrix_rows(MATRIX.read_text(encoding="utf-8"))
    if not rows:
        pytest.fail("No matrix table found in SURFACE_SUPPORT_MATRIX.md")
    return rows


class TestMatrixFile:
    def test_matrix_exists(self):
        assert MATRIX.exists(), f"Missing {MATRIX}. Create it per TP-36."

    def test_matrix_has_required_columns(self):
        rows = _parse_matrix_rows()
        assert rows, "No data rows in matrix"
        headers = list(rows[0].keys())
        assert headers == REQUIRED_COLUMNS, (
            f"Matrix columns must be exactly {REQUIRED_COLUMNS}\n"
            f"Got: {headers}"
        )

    def test_all_statuses_valid(self):
        rows = _parse_matrix_rows()
        invalid = []
        for row in rows:
            status = row["Status"].strip().lower()
            if status not in VALID_STATUSES:
                invalid.append(
                    f"{row['Surface']!r}: status {status!r} not in "
                    f"closed vocabulary {sorted(VALID_STATUSES)}"
                )
        assert not invalid, "\n".join(invalid)

    def test_no_rows_silently_dropped_by_parser(self):
        """The number of parsed rows must equal the number of data lines
        in the file's table — guards against the v0.6.x latent bug where
        a ``\\|`` (escaped pipe) inside a Notes cell made the parser see
        too many cells, silently dropping the row. Caught by /reflect.

        Separator detection uses a GFM-structural regex (``|---|---|...``)
        rather than ``"---" in line``, so a legitimate ``---`` inside a
        Notes cell does not get miscounted as a separator. Header count
        is derived from separator count (one header per table) so the
        check generalises if the file ever grows a second table.
        """
        text = MATRIX.read_text(encoding="utf-8")
        pipe_lines = [
            ln for ln in text.splitlines()
            if ln.lstrip().startswith("|")
        ]
        # GFM separator: every cell is only dashes/colons/spaces.
        separator_re = re.compile(r"^\|(?:[-:\s]+\|)+\s*$")
        separators = [ln for ln in pipe_lines if separator_re.match(ln.strip())]
        header_count = len(separators)  # one header per table
        data_line_count = len(pipe_lines) - header_count - len(separators)
        parsed_count = len(_parse_matrix_rows())
        assert parsed_count == data_line_count, (
            f"Matrix has {data_line_count} data lines in the markdown table "
            f"but parser returned {parsed_count} rows. A row is being silently "
            f"dropped — most likely cause is a literal `|` inside a cell "
            f"(check for `\\|` escapes or unescaped pipes in Notes)."
        )

    def test_data_row_count_matches_sharp_edges_claim(self):
        """TP-39: pin the live data row count to the value claimed in
        ``docs/SHARP_EDGES.md`` ("19 rows across 5 status values"). The
        NumericContract for ``surface matrix row count`` binds the
        SHARP_EDGES prose to the same int; this pin binds the source-of-
        truth file to the int. Together they break the closed-loop trap.
        """
        # If you intentionally change the count, update both this assertion
        # AND the SHARP_EDGES.md receipt line ("(N rows across 5 status values)")
        # AND the NumericContract.expected_value in tests/test_documented_claims.py.
        assert len(_parse_matrix_rows()) == 19

    def test_required_surfaces_present(self):
        rows = _parse_matrix_rows()
        surfaces = {row["Surface"].strip() for row in rows}
        missing = []
        for required in REQUIRED_SURFACES:
            if not any(required.lower() in s.lower() for s in surfaces):
                missing.append(required)
        assert not missing, (
            f"Required surfaces missing from matrix: {missing}\n"
            f"Present surfaces: {sorted(surfaces)}"
        )


class TestPublicDocsNoOverclaim:
    """Public docs must not claim coverage of deferred/unsupported surfaces."""

    # The front-door docs, deliberately -- not every public doc. The front door
    # is where an overclaim costs: a stranger reads these first and decides on
    # them. README.md and docs/README.md say "the front-door docs" for exactly
    # this population (2026-09-22; they used to say "public docs", which read
    # as the whole public set). Widen the tuple only with a measured reason.
    PUBLIC_DOCS = (
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "QUICKSTART.md",
        REPO_ROOT / "docs" / "CHEAT-SHEET.md",
    )

    OVERCLAIM_PATTERNS = (
        r"governs?\s+all\s+Claude\s+Code",
        r"comprehensive\s+Claude\s+Code\s+governance",
        r"protects?\s+against\s+all",
    )

    def test_no_overclaim_phrases(self):
        offenders = []
        for path in self.PUBLIC_DOCS:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in self.OVERCLAIM_PATTERNS:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    rel = path.relative_to(REPO_ROOT)
                    offenders.append(
                        f"  {rel}: matches {pattern!r}: {match.group(0)!r}"
                    )
        assert not offenders, (
            "Public docs overclaim Claude Code coverage. The surface "
            "matrix declares espalier's actual scope; docs must match.\n"
            + "\n".join(offenders)
        )

    # The README audit-visibility paragraph must stay accurate to the code:
    # the integrity manifest hashes the enforcement scripts + CI workflow, not
    # "every governance file" (0 of the 33 .claude/*.md governance files are in
    # MANIFEST_FILES); and the audit directory lives under $HOME, absent from
    # _protected_zones, so a session shell can still delete it -- "visibility,
    # not a boundary". These absolutes asserted the opposite of what the code does.
    AUDIT_OVERCLAIM_PATTERNS = (
        r"hashes?\s+every\s+governance\s+file",
        r"can.?t\s+be\s+wiped\s+from\s+inside\s+a\s+session",
    )

    def test_audit_paragraph_no_unbacked_absolutes(self):
        """No public doc may assert audit-visibility absolutes the code does not
        back: the integrity manifest hashes the enforcement scripts + CI workflow
        (not every governance file), and the $HOME audit directory is not in
        _protected_zones (so it can be wiped in-session -- the README paragraph's
        own 'Not a security boundary' sibling and the audit-append code comment
        both say as much).

        TP-366 1-E: scans the FULL public-doc set (``get_public_doc_relpaths()``,
        which includes ``docs/POSITIONING.md``), not README alone -- the identical
        false sentence had sailed through in POSITIONING.md because this scan was
        README-only (STANDING_PRINCIPLES ss8, class-fix scope = every shipped
        surface). Kept off the shared ``PUBLIC_DOCS`` 3-tuple deliberately: that
        tuple also drives ``test_no_overclaim_phrases`` /
        ``test_deferred_surfaces_not_claimed``, and widening it there would expand
        two unrelated scans."""
        offenders = []
        for rel in get_public_doc_relpaths():
            path = REPO_ROOT / rel
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in self.AUDIT_OVERCLAIM_PATTERNS:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    offenders.append(
                        f"  {rel}: un-backed absolute {pattern!r}: {match.group(0)!r}"
                    )
        assert not offenders, (
            "A public doc's audit-visibility text overclaims vs code reality "
            "(MANIFEST_FILES hashes the enforcement scripts + CI workflow, not "
            "every governance file; the $HOME audit dir is not protected, so a "
            "session shell can delete it).\n"
            + "\n".join(offenders)
        )

    def test_deferred_surfaces_not_claimed(self):
        """If the matrix marks a surface deferred, public docs must not
        claim coverage."""
        rows = _parse_matrix_rows()
        deferred_surfaces = [
            row["Surface"] for row in rows
            if "deferred" in row["Status"].lower()
        ]
        offenders = []
        for path in self.PUBLIC_DOCS:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8").lower()
            for surface in deferred_surfaces:
                surface_key = surface.lower().split("(")[0].strip()
                pattern = (
                    rf"(espalier\s+(?:governs?|supports?|protects?|"
                    rf"enforces?).{{0,40}}{re.escape(surface_key)})"
                )
                for match in re.finditer(pattern, text):
                    rel = path.relative_to(REPO_ROOT)
                    offenders.append(
                        f"  {rel}: claims coverage of deferred surface "
                        f"{surface!r}: {match.group(0)!r}"
                    )
        assert not offenders, (
            "Public docs claim coverage of surfaces marked 'deferred' "
            "in SURFACE_SUPPORT_MATRIX.md.\n"
            + "\n".join(offenders)
        )
