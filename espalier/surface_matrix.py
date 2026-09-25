"""Parse ``docs/SURFACE_SUPPORT_MATRIX.md`` and classify symbols.

The matrix is the normative declaration of which Claude Code surfaces
espalier governs. This module exposes its rows as data so
``espalier scope-check`` can tag each affected symbol with the
surface's risk level (``guarded`` → high-risk; ``supported`` →
medium-risk; ``documented-only`` / ``deferred`` / ``unsupported`` →
informational).

Single SoT: ``parse_matrix_rows`` is the canonical parser; the
existing ``tests/test_surface_support_matrix.py`` imports it rather
than maintaining a parallel implementation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


REQUIRED_COLUMNS: tuple[str, ...] = (
    "Surface",
    "Status",
    "Guarding mechanism",
    "Release guarantee",
    "Notes",
)

VALID_STATUSES: frozenset[str] = frozenset({
    "guarded",
    "supported",
    "documented-only",
    "deferred",
    "unsupported",
})


@dataclass(frozen=True)
class SurfaceRow:
    """One row of the support matrix."""

    surface: str
    status: str
    guarding: str
    guarantee: str
    notes: str


class SurfaceMatrix:
    """Parsed surface support matrix with a :meth:`classify` lookup."""

    def __init__(self, rows: list[SurfaceRow]):
        self.rows = rows

    def classify(self, symbol: str) -> str | None:
        """Return the matrix ``Status`` for the row whose ``Surface``
        loosely matches ``symbol``, or ``None`` if no row matches.

        Matching is token-boundary-aligned, case-insensitive, with
        slash-stripping. The classifier is intentionally simple: it
        catches the easy cases (direct token containment + plural/
        singular stem) and returns ``None`` when no row clearly
        matches. The CLI surfaces both matched and unmatched symbols
        so the operator sees what the classifier missed.

        Token comparison strips a trailing ``s`` so ``agents`` ↔
        ``subagents`` / ``agent`` ↔ ``agents`` overlap — without it
        ``.claude/agents/`` returns ``None`` because no row contains the
        token ``agents`` verbatim (the matrix uses ``Subagents``).
        """
        if not symbol:
            return None
        key = symbol.lower().strip().strip("/")
        key_tokens = {t.lower() for t in _split_into_tokens(key)}
        # Split each row's surface label ONCE; both the exact-token pass and the
        # stem/suffix pass derive from this. The two passes stay SEPARATE
        # (exact-token precedence requires the first to complete across all rows
        # before the stem fallback runs — do not merge).
        row_tokens = [(row, _split_into_tokens(row.surface)) for row in self.rows]
        for row, tokens in row_tokens:
            # Token-bound this branch. A bare ``key in surface_lower`` matched
            # non-token-aligned interior/prefix substrings (``compact`` ⊂
            # ``Compaction``, ``set`` ⊂ ``settings``), mis-tagging benign symbols
            # [HIGH-RISK] on the advisory scope-check surface. Require
            # token-boundary alignment: every key token is a surface token
            # (symbol ⊆ surface label) OR every surface token is a key token
            # (symbol ⊇ surface label). Single common tokens that ARE a whole
            # surface token (``main``/``settings``) stay matched here AND via the
            # stem branch — structurally identical to the load-bearing
            # ``ExitPlanMode`` ⊂ ``ExitPlanMode bridge`` query, so killing them
            # would false-negative real surface queries.
            surface_tokens = {t.lower() for t in tokens}
            if key_tokens and surface_tokens and (
                key_tokens <= surface_tokens or surface_tokens <= key_tokens
            ):
                return row.status.lower()
        # Token overlap with plural-stripping. ``.claude/agents/`` stems
        # to ``{claude, agent}``; the row label ``Subagents (built-in)``
        # stems to ``{subagent, built-in}``. The ``agent`` ⊂ ``subagent``
        # containment captures the intended match. Length floor (≥ 4)
        # avoids matching ``in`` against ``built-in`` or ``set`` against
        # ``settings``.
        sym_stems = {
            _stem(t.lower()) for t in _split_into_tokens(symbol)
            if len(t) >= 4
        }
        sym_stems.discard("")
        for row, tokens in row_tokens:
            row_stems = {
                _stem(t.lower()) for t in tokens
                if len(t) >= 4
            }
            # Direct match OR stem-suffix overlap (agent ⊂ subagent).
            # Suffix-only, not bare substring — bare ``s in r or r in s``
            # over-matched prefixes/interiors (``main`` ⊂ ``mainframe``),
            # mis-tagging benign symbols on the advisory scope-check surface.
            if sym_stems & row_stems:
                return row.status.lower()
            for s in sym_stems:
                if any(_suffix_overlap(s, r) for r in row_stems):
                    return row.status.lower()
        return None


_CONTROL_CHAR_RE = re.compile(
    "["
    "\x00-\x1f\x7f"             # ASCII control + DEL
    "\u200b-\u200f"             # zero-width chars + LTR/RTL marks
    "\u2028\u2029"               # LINE / PARAGRAPH SEPARATOR
    "\u202a-\u202e"             # bidi embedding/overrides (incl. U+202E RTL OVERRIDE)
    "\u2066-\u2069"             # bidi isolates
    "]"
)


def _sanitize_cell(cell: str) -> str:
    """Strip ASCII + Unicode control characters from a matrix cell.

    Covers ASCII 0x00-0x1F + 0x7F (ANSI/cursor escapes) and Unicode
    controls: zero-width chars, LINE/PARAGRAPH SEPARATOR (U+2028/2029),
    and the bidi overrides (U+202A-202E, U+2066-2069 — incl. the infamous
    U+202E RTL OVERRIDE). A poisoned matrix cell with any of these would
    otherwise flip displayed text or split log parsers when scope-check
    prints the report.
    """
    return _CONTROL_CHAR_RE.sub("", cell)


def parse_matrix_rows(text: str) -> list[dict[str, str]]:
    """Extract the matrix table rows as a list of dicts.

    Returns rows from the first markdown table whose header line starts
    with ``| Surface |``. Each row is keyed by the literal header cell
    text. Missing or malformed lines are silently skipped — callers
    that care about completeness should check the resulting list length.
    Control characters (ASCII and Unicode) are stripped from every cell.
    """
    lines = text.splitlines()
    table_start: int | None = None
    for i, line in enumerate(lines):
        if line.strip().startswith("| Surface |"):
            table_start = i
            break
    if table_start is None:
        return []

    header_cells = [
        _sanitize_cell(c.strip()) for c in lines[table_start].strip("|").split("|")
    ]
    rows: list[dict[str, str]] = []
    for line in lines[table_start + 2:]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            break
        cells = [_sanitize_cell(c.strip()) for c in stripped.strip("|").split("|")]
        if len(cells) != len(header_cells):
            continue
        rows.append(dict(zip(header_cells, cells)))
    return rows


def load_matrix(path: Path) -> SurfaceMatrix:
    """Load + parse the matrix at ``path``; empty matrix if missing."""
    if not path.exists():
        return SurfaceMatrix([])
    rows_dicts = parse_matrix_rows(path.read_text(encoding="utf-8"))
    structured = [
        SurfaceRow(
            surface=row.get("Surface", ""),
            status=row.get("Status", ""),
            guarding=row.get("Guarding mechanism", ""),
            guarantee=row.get("Release guarantee", ""),
            notes=row.get("Notes", ""),
        )
        for row in rows_dicts
    ]
    return SurfaceMatrix(structured)


def _stem(token: str) -> str:
    """Strip a single trailing ``s`` so ``agents`` ↔ ``agent`` overlap.

    Intentionally simple — not a full stemmer. Anything more aggressive
    (e.g., handling ``ies`` → ``y``) risks false positives without an
    enumerated rule set, which is a worse trap than the current
    pluralization gap. Skip stems of length ≤ 2 so common short tokens
    (``is``, ``as``) aren't collapsed.
    """
    if len(token) > 2 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _suffix_overlap(a: str, b: str) -> bool:
    """True when the shorter stem is a SUFFIX of the longer — the
    ``agent`` ⊂ ``subagent`` ('sub-X') morphology the classifier is built
    around. Suffix-only avoids the prefix/interior over-match that bare
    substring containment produced (``main`` ⊂ ``mainframe``,
    ``set`` ⊂ ``settings``, ``tool`` ⊂ ``toolkit``).
    """
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return short != "" and long.endswith(short)


def _split_into_tokens(label: str) -> list[str]:
    """Pull individual words/segments out of a surface label.

    Matrix surfaces look like ``Subagents (built-in)`` /
    ``Main session Write/Edit``; token-split on space and ``/`` so the
    classifier can match a single path component.
    """
    tokens: list[str] = []
    current = ""
    for ch in label:
        if ch.isalnum() or ch == "_" or ch == "-":
            current += ch
        else:
            if current:
                tokens.append(current)
                current = ""
    if current:
        tokens.append(current)
    return tokens
