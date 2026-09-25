"""Walk load-bearing claims; resolve each claim's ``<!-- canon: ... -->``
annotation to a real canon; verify the bidirectional claim-id <-> pins
link.

Stdlib-only. INLINED registry (per TestScannerSelfContainment in
tests/test_scanners.py). Enforcement is default-ON: the contract tests
run on every pytest invocation. The ``ESPALIER_CANON_VERIFIER=enforce``
env var is retained only as a debug re-gate opt-in living in
test_canon_verifier_contract.py.

See ``docs/SHARP_EDGES.md`` "Annotate claims with canons or label them
convention" for the operator-facing protocol.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# Committed project-memory filename. A per-file constant, not a shared import:
# espalier/scanners/ is stdlib-only (test_scanners_stdlib_only) and cannot import
# a cross-module constant; a future rename flips this one value.
_MEMORY_FILENAME = "ESPALIER_MEMORY.md"

# ─────────────────────────────────────────────────────────────────────
# INLINED registry — explicit list of doc surfaces where load-bearing
# claims live. New claim surfaces require explicit registration (forces
# operator awareness; no `_is_claim_marker` heuristic that silently
# misses new surfaces).
#
# INVARIANT for any shape registered here: adjacent claims MUST be
# separated by a real (non-blank, non-comment) line. `_find_adjacent_claim_id`
# binds a canon to the claim-id in its annotation BLOCK (bounded by real
# text); a shape whose claims are separated only by blank lines would
# collapse two claims' annotations into one block and mis-bind. Every shape
# below satisfies this (each claim carries its own prose / heading / row).

CLAIM_SURFACES: tuple[tuple[str, str], ...] = (
    # (path_relative_to_root, claim-discovery shape label)
    ("CLAUDE.md", "priority-order-numbered-list"),
    ("docs/HOOK_ASSUMPTIONS.md", "backed-by-bullet"),
    ("docs/CONVENTIONS.md", "scaffolding-canon-table-row"),
    # README.md is not registered: its load-bearing prose is unstructured;
    # the `_discover_naked_prose` stub returned [] unconditionally, making
    # `test_no_naked_claims` pass vacuously for README. Re-register when a
    # real structural shape exists (e.g., a normative "Invariants" section
    # with parametrized rows).
)

CANON_ANNOTATION_RE = re.compile(r"<!--\s*canon:\s*([^-][^>]*?)\s*-->")
CLAIM_ID_ANNOTATION_RE = re.compile(r"<!--\s*claim-id:\s*([\w-]+)\s*-->")
PINS_ANNOTATION_RE = re.compile(r"#\s*pins:\s*claim:([\w-]+)")
PINS_STUB_ANNOTATION_RE = re.compile(r"#\s*pins-stub:\s*claim:([\w-]+)")

# §5.10 / F-1: numeric-threshold literals in a claim's prose -- decimals
# (0.10) and percentages (20%). A claim carrying one of these "names a
# threshold"; the pinned test must reference at least one such literal to
# earn PINNED (else it exercises arithmetic shape only -> PINNED-STUB).
THRESHOLD_LITERAL_RE = re.compile(r"\d+\.\d+%?|\d+%")

# Up-walk window for `_build_covered_claim_lines` (canon annotation -> its
# claim text line). Claim-id discovery no longer uses it — that bind is now
# block-bounded (see `_find_adjacent_claim_id`).
ADJACENCY_WINDOW: int = 5

# Stub-pin budget. PINNED-STUB findings are allowed (bootstrap reality)
# but capped — raising this is a deliberate operator act that signals
# growing canon-vs-claim debt. Same discipline as MAX_PRAGMA_COUNT.
MAX_PINS_STUB_COUNT: int = 5

# Docs that mention the annotation syntax in prose (typically inside
# backticks, describing the protocol) without carrying real annotations.
# Excluded from the UNREGISTERED_SURFACE walk to avoid false positives.
# Same shape as retired_vocab.EXEMPT_FILES. Cap: small set so
# operators notice growth as the doc surface expands.
EXEMPT_PROSE_FILES: frozenset[str] = frozenset({
    "docs/FAILURE_MODES.md",
    "docs/SHARP_EDGES.md",
    "CHANGELOG.md",
    # Both files quote canon annotation syntax inside backticks while
    # discussing the protocol; neither carries real annotations. Without
    # these entries the enforce gate fails on
    # test_no_unregistered_claim_surfaces.
    _MEMORY_FILENAME,
    "docs/session-archive.md",
})
MAX_EXEMPT_PROSE_FILES: int = 5

# Per-surface CLAIM_DISCOVERERS map shape_label -> a function that walks
# the surface's lines and returns the line numbers (1-indexed) of every
# load-bearing claim. The verifier flags any discovered claim line that
# lacks an adjacent canon annotation as MISSING_ANNOTATION. This closes
# the originating failure mode (v2's annotation-driven walk silently
# accepted a NEW naked claim added to a registered surface).

# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ClaimRecord:
    surface_path: Path
    claim_lineno: int
    claim_text: str
    canon: str
    claim_id: str


@dataclass(frozen=True, slots=True)
class CanonFinding:
    claim: ClaimRecord
    severity: str
    # PINNED | PINNED-STUB | CONVENTION | DORMANT
    # | MISSING_CANON | MISSING_CLAIM_ID | MISSING_PINS | PINS_MISMATCH
    # | MISSING_ANNOTATION | UNREGISTERED_SURFACE
    explanation: str


def _discover_priority_order(lines: list[str]) -> list[int]:
    """Numbered items under any '## Priority Order' or '## Core Rules'
    heading. Anchors closure of the originating failure mode for
    CLAUDE.md."""
    in_section = False
    line_nums: list[int] = []
    for i, line in enumerate(lines, start=1):
        stripped = line.rstrip()
        if stripped.startswith("## "):
            in_section = (
                "Priority Order" in stripped or "Core Rules" in stripped
            )
            continue
        if not in_section:
            continue
        if re.match(r"^\d+\.\s+\S", line):
            line_nums.append(i)
    return line_nums


def _discover_backed_by_blocks(lines: list[str]) -> list[int]:
    """Each `**Backed by:**` marker line in HOOK_ASSUMPTIONS.md is a claim."""
    return [
        i for i, line in enumerate(lines, start=1)
        if "**Backed by:**" in line
    ]


def _discover_signal_threshold_rows(lines: list[str]) -> list[int]:
    """Table rows in the CONVENTIONS scaffolding-canon falsifiability section.
    Shape: `| N -- <name> | ... | ... |` under a Falsifiability heading."""
    in_section = False
    line_nums: list[int] = []
    for i, line in enumerate(lines, start=1):
        stripped = line.rstrip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            in_section = (
                "Falsifiability" in stripped or "Scaffolding" in stripped
            )
            continue
        if not in_section:
            continue
        if re.match(r"^\|\s*\d+\s+[—-]\s+", line):
            line_nums.append(i)
    return line_nums


CLAIM_DISCOVERERS: dict[str, object] = {
    "priority-order-numbered-list": _discover_priority_order,
    "backed-by-bullet": _discover_backed_by_blocks,
    "scaffolding-canon-table-row": _discover_signal_threshold_rows,
    # `load-bearing-invariant-prose` / `_discover_naked_prose` removed:
    # the stub `return []` made test_no_naked_claims pass vacuously for
    # README. Pinned by TestClaimDiscoverersNotStubs.
}


def _build_covered_claim_lines(lines: list[str]) -> set[int]:
    """For each ``<!-- canon: ... -->`` annotation, return the line number
    of the claim it covers — the nearest non-empty, non-comment line
    ABOVE the annotation (within ADJACENCY_WINDOW).

    This binds 1 annotation -> 1 claim. A window-based "any annotation
    within +/-N lines" check silently collapses when claims are dense
    (consecutive numbered items): one annotation at the bottom would
    suppress naked-claim findings for every item above. Precise binding
    makes each annotation cover exactly the immediately preceding claim,
    so operators must annotate each claim.
    """
    covered: set[int] = set()
    for lineno, line in enumerate(lines, start=1):
        if not CANON_ANNOTATION_RE.search(line):
            continue
        anchor_idx = lineno - 1
        # Embedded annotation: canon comment is INSIDE other content on
        # the same line (e.g., a table cell). The annotation covers its
        # own line, not the line above. Detect by stripping all
        # annotations and checking whether real text remains.
        line_without = CANON_ANNOTATION_RE.sub("", line)
        line_without = CLAIM_ID_ANNOTATION_RE.sub("", line_without).strip()
        if line_without and not line_without.startswith("<!--"):
            covered.add(lineno)
            continue
        for j in range(
            anchor_idx - 1,
            max(-1, anchor_idx - 1 - ADJACENCY_WINDOW),
            -1,
        ):
            text = lines[j].strip()
            if not text:
                continue
            if text.startswith("<!--"):
                continue
            covered.add(j + 1)
            break
    return covered


def verify_repo(root: Path) -> list[CanonFinding]:
    findings: list[CanonFinding] = []
    findings.extend(_detect_unregistered_surfaces(root))
    for surface_rel, shape_label in CLAIM_SURFACES:
        target = root / surface_rel
        if not target.exists():
            continue
        findings.extend(_verify_surface(target, root, shape_label))
    return findings


def _detect_unregistered_surfaces(root: Path) -> Iterable[CanonFinding]:
    """Scan likely doc surfaces for canon/claim-id annotations OUTSIDE
    CLAIM_SURFACES — surfaces with annotations are clearly claim-bearing
    and must be explicitly registered."""
    known_surfaces = {p for p, _ in CLAIM_SURFACES}
    docs_dir = root / "docs"
    candidates: list[Path] = []
    if docs_dir.exists():
        candidates.extend(docs_dir.rglob("*.md"))  # espalier:safe-walk-ok self-host canon re-gate (test-only via test_canon_verifier_contract), never walks an adopter tree
    candidates.extend([
        root / "CLAUDE.md",
        root / "README.md",
        root / _MEMORY_FILENAME,
        root / "CHANGELOG.md",
    ])
    for path in candidates:
        if not path.exists():
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        if rel in known_surfaces:
            continue
        if rel in EXEMPT_PROSE_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if (
            CANON_ANNOTATION_RE.search(text)
            or CLAIM_ID_ANNOTATION_RE.search(text)
        ):
            yield CanonFinding(
                claim=ClaimRecord(
                    surface_path=Path(rel),
                    claim_lineno=0,
                    claim_text="",
                    canon="",
                    claim_id="",
                ),
                severity="UNREGISTERED_SURFACE",
                explanation=(
                    f"{rel} contains canon/claim-id annotations but is "
                    f"not registered in CLAIM_SURFACES. Three exits, and "
                    f"the registry one is a TWO-part edit:\n"
                    f"    (a) the annotations are spurious (an example, or "
                    f"prose that quotes the syntax) -- remove them;\n"
                    f"    (b) it is a real claim surface -- add a "
                    f"(path, shape_label) row to CLAIM_SURFACES AND, if "
                    f"that shape label is new, a matching "
                    f"CLAIM_DISCOVERERS entry in the SAME change. The row "
                    f"alone lands you on tests/"
                    f"test_canon_verifier_contract.py::"
                    f"test_every_registered_surface_has_a_discoverer, "
                    f"which exists to catch a surface policed by "
                    f"nothing;\n"
                    f"    (c) it only MENTIONS the syntax in prose -- "
                    f"EXEMPT_PROSE_FILES covers that, but it holds "
                    f"{len(EXEMPT_PROSE_FILES)} of a capped "
                    f"{MAX_EXEMPT_PROSE_FILES}, so it is not a general "
                    f"escape hatch."
                ),
            )


def _verify_surface(
    path: Path, root: Path, shape_label: str,
) -> Iterable[CanonFinding]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    lines = text.splitlines()
    rel = path.relative_to(root)
    # PASS 1: walk existing annotations — each canon comment marks a claim line.
    for lineno, line in enumerate(lines, start=1):
        canon_match = CANON_ANNOTATION_RE.search(line)
        if not canon_match:
            continue
        canon = canon_match.group(1).strip()
        claim_id = _find_adjacent_claim_id(lines, lineno - 1)
        claim_text = _find_claim_text(lines, lineno - 1)
        record = ClaimRecord(
            surface_path=rel,
            claim_lineno=lineno,
            claim_text=claim_text,
            canon=canon,
            claim_id=claim_id,
        )
        yield _verify_claim(record, root)

    # PASS 2: discover STRUCTURAL claim positions for this surface's shape.
    # Any discovered claim line not covered by a precise 1:1 annotation
    # binding is the naked-claim failure mode.
    discoverer = CLAIM_DISCOVERERS.get(shape_label)
    if discoverer is None:
        return
    covered = _build_covered_claim_lines(lines)
    for expected_lineno in discoverer(lines):  # type: ignore[operator]
        if expected_lineno in covered:
            continue
        claim_text = lines[expected_lineno - 1].strip()[:200]
        yield CanonFinding(
            claim=ClaimRecord(
                surface_path=rel,
                claim_lineno=expected_lineno,
                claim_text=claim_text,
                canon="",
                claim_id="",
            ),
            severity="MISSING_ANNOTATION",
            explanation=(
                f"{rel}:{expected_lineno} matches the `{shape_label}` "
                f"claim shape but no `<!-- canon: ... -->` annotation "
                f"binds to it (annotation must appear on a line directly "
                f"following the claim, separated only by blanks). Either "
                f"annotate with a real canon, OR `<!-- canon: convention -->` "
                f"to declare it honest non-canon, OR `<!-- canon: dormant: "
                f"<reason >=12 chars> -->` if structurally prepared but unwired."
            ),
        )


def _annotation_block_bounds(lines: list[str], idx: int) -> tuple[int, int]:
    """Inclusive ``(lo, hi)`` bounds of the contiguous blank/comment block
    containing ``idx``. The block is capped ABOVE by the claim's text line
    and BELOW by the next real (non-blank, non-comment) line, so it never
    reaches into a neighbouring claim's annotations. Conceptually the same
    claim-block boundary as ``_build_covered_claim_lines``'s up-walk (they
    share no code, and this scan is uncapped rather than ADJACENCY_WINDOW-
    bounded), applied here to claim-id discovery.

    Relies on a real (non-blank, non-comment) line separating any two
    claims' annotation groups — true for every CLAIM_SURFACES shape today
    (each claim's own numbered/bulleted prose intervenes). A future surface
    whose claims are separated by pure blank runs would need an explicit cap.
    """
    def _is_block_line(k: int) -> bool:
        s = lines[k].strip()
        return (not s) or s.startswith("<!--")

    lo = idx
    while lo - 1 >= 0 and _is_block_line(lo - 1):
        lo -= 1
    hi = idx
    while hi + 1 < len(lines) and _is_block_line(hi + 1):
        hi += 1
    return lo, hi


def _find_adjacent_claim_id(lines: list[str], idx: int) -> str:
    """Return the claim-id bound to the canon annotation at ``idx``.

    Same-line check first, so an embedded annotation (a canon comment inside
    a table cell) binds to a claim-id in that same cell. Otherwise search the
    canon's ANNOTATION BLOCK (the contiguous blank/comment run between the
    claim text above and the next real line below) rather than a raw
    ±ADJACENCY_WINDOW scan. The block never crosses a real text line, so a
    stacked-canon claim no longer mis-binds its top canon to the PREVIOUS
    claim's claim-id: canon-first and claim-id-first orderings both resolve."""
    if not (0 <= idx < len(lines)):
        return ""
    m = CLAIM_ID_ANNOTATION_RE.search(lines[idx])
    if m:
        return m.group(1)
    lo, hi = _annotation_block_bounds(lines, idx)
    for j in range(lo, hi + 1):
        m = CLAIM_ID_ANNOTATION_RE.search(lines[j])
        if m:
            return m.group(1)
    return ""


def _find_claim_text(lines: list[str], idx: int) -> str:
    for j in range(idx, max(0, idx - 5), -1):
        line = lines[j].strip()
        if not line:
            continue
        if line.startswith("<!--"):
            continue
        return line[:200]
    return ""


def _verify_claim(claim: ClaimRecord, root: Path) -> CanonFinding:
    if not claim.canon:
        return CanonFinding(
            claim=claim,
            severity="MISSING_CANON",
            explanation="canon annotation empty",
        )
    if not claim.claim_id:
        return CanonFinding(
            claim=claim,
            severity="MISSING_CLAIM_ID",
            explanation=(
                "claim has `<!-- canon: ... -->` but no adjacent "
                "`<!-- claim-id: <slug> -->`. Both required so tests "
                "can pin via `# pins: claim:<slug>`."
            ),
        )
    if claim.canon == "convention":
        return CanonFinding(
            claim=claim,
            severity="CONVENTION",
            explanation="explicit non-canon; honest disclosure",
        )
    if claim.canon.startswith("dormant:"):
        reason = claim.canon[len("dormant:"):].strip()
        if len(reason) < 12:
            return CanonFinding(
                claim=claim,
                severity="MISSING_CANON",
                explanation="`dormant:` annotation requires reason >=12 chars",
            )
        return CanonFinding(
            claim=claim,
            severity="DORMANT",
            explanation=f"canon dormant: {reason}",
        )
    if claim.canon.startswith("docs/external/"):
        target = root / claim.canon
        if not target.exists():
            return CanonFinding(
                claim=claim,
                severity="MISSING_CANON",
                explanation=f"external pin not found: {claim.canon}",
            )
        return CanonFinding(
            claim=claim,
            severity="PINNED",
            explanation=f"external pin: {claim.canon}",
        )
    if claim.canon.startswith("tests/"):
        return _verify_test_canon(claim, root)
    if claim.canon.startswith("espalier/"):
        return _verify_runtime_canon(claim, root)
    return CanonFinding(
        claim=claim,
        severity="MISSING_CANON",
        explanation=f"canon value unrecognized: {claim.canon}",
    )


def _declaration_body(text: str, decl_lineno: int) -> str:
    """Return the full source of the def/class declared at ``decl_lineno``
    (1-indexed): the declaration line plus every following line indented
    deeper than it, up to the next sibling/dedent. Static slice only -- the
    body is never executed (§5.10 scope guard)."""
    lines = text.splitlines()
    start = decl_lineno - 1
    if start < 0 or start >= len(lines):
        return ""
    decl_indent = len(lines[start]) - len(lines[start].lstrip())
    body = [lines[start]]
    for line in lines[start + 1:]:
        if not line.strip():
            body.append(line)
            continue
        if (len(line) - len(line.lstrip())) <= decl_indent:
            break
        body.append(line)
    return "\n".join(body)


def _threshold_literals(claim_text: str) -> list[str]:
    """Numeric-threshold literals named in a claim's prose (decimals +
    percentages). Bare integers are excluded -- they are too common in test
    bodies (sample sizes, indices) to discriminate. Order-preserving, deduped."""
    seen: dict[str, None] = {}
    for lit in THRESHOLD_LITERAL_RE.findall(claim_text):
        seen.setdefault(lit, None)
    return list(seen)


def _verify_test_canon(claim: ClaimRecord, root: Path) -> CanonFinding:
    canon_path, _, ident = claim.canon.partition("::")
    target = root / canon_path
    if not target.exists():
        return CanonFinding(
            claim=claim,
            severity="MISSING_CANON",
            explanation=f"test file not found: {canon_path}",
        )
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return CanonFinding(
            claim=claim,
            severity="MISSING_CANON",
            explanation=f"test file unreadable: {canon_path}",
        )
    if not ident:
        return CanonFinding(
            claim=claim,
            severity="MISSING_CANON",
            explanation=(
                f"file-level test canon `{canon_path}` has no `::<symbol>` "
                f"suffix. Canonical form is `tests/<path>::<TestClass>` or "
                f"`tests/<path>::<test_function>`. Either tighten to a "
                f"specific symbol, or use `convention` if this is a "
                f"meta-claim about the test file."
            ),
        )
    decl_lineno = _find_declaration(text, ident)
    if decl_lineno is None:
        return CanonFinding(
            claim=claim,
            severity="MISSING_CANON",
            explanation=(
                f"test identifier `{ident}` not found as `def {ident}(` "
                f"or `class {ident}` in {canon_path}"
            ),
        )
    pins_slug, is_stub = _extract_pins_slug(text, decl_lineno)
    if pins_slug is None:
        return CanonFinding(
            claim=claim,
            severity="MISSING_PINS",
            explanation=(
                f"test `{ident}` exists at {canon_path}:{decl_lineno} "
                f"but has no `# pins: claim:<slug>` or "
                f"`# pins-stub: claim:<slug>` annotation."
            ),
        )
    if pins_slug != claim.claim_id:
        return CanonFinding(
            claim=claim,
            severity="PINS_MISMATCH",
            explanation=(
                f"test `{ident}` pins claim:{pins_slug!r} but the doc "
                f"claim has claim-id:{claim.claim_id!r}. Bidirectional "
                f"slug must match exactly."
            ),
        )
    if is_stub:
        return CanonFinding(
            claim=claim,
            severity="PINNED-STUB",
            explanation=(
                "test pinned via `# pins-stub:` — placeholder that does "
                "not yet exercise the claim's behavior. Counted against "
                "MAX_PINS_STUB_COUNT budget."
            ),
        )
    # §5.10 / F-1: a meta-gate must assert the artifact DISCRIMINATES, not
    # merely that it exists + slug-matches. For a claim that names a numeric
    # threshold, require the pinned test body to reference at least one of
    # those literals; a body that matches by slug yet exercises only
    # arithmetic shape is a stub in disguise. Static reference-check only
    # (no execution) -- the bounded, tractable form of "discriminates".
    thresholds = _threshold_literals(claim.claim_text)
    if thresholds:
        body = _declaration_body(text, decl_lineno)
        if not any(lit in body for lit in thresholds):
            return CanonFinding(
                claim=claim,
                severity="PINNED-STUB",
                explanation=(
                    f"test `{ident}` pins a numeric-threshold claim "
                    f"(literals {thresholds}) but its body references none "
                    f"of them — it exercises arithmetic shape, not the named "
                    f"threshold. Assert the threshold or annotate "
                    f"`# pins-stub:`. Counted against MAX_PINS_STUB_COUNT."
                ),
            )
    return CanonFinding(
        claim=claim,
        severity="PINNED",
        explanation=f"test pinned: {claim.canon}",
    )


def _verify_runtime_canon(claim: ClaimRecord, root: Path) -> CanonFinding:
    """Documented canon form: ``espalier/<path>.<symbol>`` — slashes for
    the module path, single dot before the symbol. Uses ``rpartition`` so
    nested paths like ``espalier/scanners/canon_verifier._find_declaration``
    parse correctly (split on LAST dot). Python-dotted forms
    (``espalier.scanners.canon_verifier._find_declaration``) are rejected
    explicitly so operators get a clear error rather than the silent
    misleading MISSING_CANON the original ``partition`` produced.
    """
    module_part, sep, symbol = claim.canon.rpartition(".")
    if not sep:
        module_part, symbol = claim.canon, ""
    if "." in module_part:
        return CanonFinding(
            claim=claim,
            severity="MISSING_CANON",
            explanation=(
                f"runtime canon {claim.canon!r} uses dotted module path. "
                f"Canonical form is slash-separated: "
                f"`espalier/<path>.<symbol>` (e.g. "
                f"`espalier/scaffolding_canon._signal_1_continuity`)."
            ),
        )
    target = root / f"{module_part}.py"
    if not target.exists():
        return CanonFinding(
            claim=claim,
            severity="MISSING_CANON",
            explanation=f"runtime canon module not found: {module_part}",
        )
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return CanonFinding(
            claim=claim,
            severity="MISSING_CANON",
            explanation=f"runtime canon unreadable: {module_part}",
        )
    if symbol:
        decl_lineno = _find_declaration(text, symbol)
        if decl_lineno is None:
            return CanonFinding(
                claim=claim,
                severity="MISSING_CANON",
                explanation=(
                    f"symbol `{symbol}` not found as `def {symbol}(` or "
                    f"`class {symbol}` in {module_part}.py"
                ),
            )
    return CanonFinding(
        claim=claim,
        severity="PINNED",
        explanation=f"runtime canon: {claim.canon}",
    )


def _find_declaration(text: str, ident: str) -> Optional[int]:
    """Find the line where ``ident`` is DECLARED (def or class). Walks
    all lines; returns earliest matching declaration."""
    if not ident:
        return None
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if (
            stripped.startswith(f"def {ident}(")
            or stripped.startswith(f"def {ident} (")
            or stripped.startswith(f"async def {ident}(")
            or stripped.startswith(f"class {ident}(")
            or stripped.startswith(f"class {ident}:")
        ):
            return lineno
    return None


def _extract_pins_slug(
    text: str, decl_lineno: int,
) -> tuple[Optional[str], bool]:
    """Find ``# pins: claim:<slug>`` or ``# pins-stub: claim:<slug>``
    annotation within 10 lines above or below the declaration.

    Returns (slug, is_stub). ``is_stub=True`` means the test body does
    not exercise the claim's behavior; verifier surfaces PINNED-STUB.
    """
    lines = text.splitlines()
    decl_idx = decl_lineno - 1
    for j in range(decl_idx - 1, max(-1, decl_idx - 10), -1):
        m_stub = PINS_STUB_ANNOTATION_RE.search(lines[j])
        if m_stub:
            return m_stub.group(1), True
        m_real = PINS_ANNOTATION_RE.search(lines[j])
        if m_real:
            return m_real.group(1), False
    for j in range(decl_idx + 1, min(len(lines), decl_idx + 10)):
        m_stub = PINS_STUB_ANNOTATION_RE.search(lines[j])
        if m_stub:
            return m_stub.group(1), True
        m_real = PINS_ANNOTATION_RE.search(lines[j])
        if m_real:
            return m_real.group(1), False
    return None, False
