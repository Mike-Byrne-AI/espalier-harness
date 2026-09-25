"""Walk doc surfaces; flag retired-vocabulary occurrences outside
allowed contexts.

Stdlib-only. Registry INLINED -- the package's own modules are off
limits here, per TestScannerSelfContainment at tests/test_scanners.py.

Case-sensitivity gaps in scrub regexes inform this design: rather than
pin terms to ``case_sensitive=True`` and miss
mixed-case occurrences, we match on the SEVERITY-LABEL USAGE SHAPE
(e.g., ``**WRONG**`` markdown bold, ``- WRONG --`` bullet prefix,
``WRONG:`` section label) and use context predicates to exclude
legitimate prose use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

# Committed project-memory filename. A per-file constant, not a shared import:
# espalier/scanners/ is stdlib-only (test_scanners_stdlib_only) and cannot import
# a cross-module constant; a future rename flips this one value.
_MEMORY_FILENAME = "ESPALIER_MEMORY.md"


def _skip_nested_repos(dirpath: str, dirnames: list[str]) -> None:
    """Drop embedded-repo subdirs from an os.walk ``dirnames`` in place — parity
    with ``espalier._safe_walk.safe_rglob(skip_nested_repos=True)``. Scanners are
    stdlib-only and cannot import ``_safe_walk``, so the prune is duplicated here
    (like ``_safe_rglob`` itself). A nested ``.git`` (dir OR gitlink file) marks a
    foreign project."""
    import os
    dirnames[:] = [
        d for d in dirnames
        if not os.path.exists(os.path.join(dirpath, d, ".git"))
    ]


def _safe_rglob(root, pattern: str = "*"):
    """Symlink-safe rglob (inline — scanners have zero espalier imports, per
    TestScannerSelfContainment; copied via inspect.getsource). See
    espalier/_safe_walk.py for the canonical version. os.walk(followlinks=
    False) never descends a symlinked dir, so it is crash-safe on CPython
    3.10-3.12 where bare rglob follows dir symlinks (ELOOP on a loop)."""
    import fnmatch
    import os
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        _skip_nested_repos(dirpath, dirnames)
        base = Path(dirpath)
        for name in (*dirnames, *filenames):
            if fnmatch.fnmatch(name, pattern):
                yield base / name


# Context predicates: (rel_path, line, immediate_parent_heading) -> bool
# Return True if the occurrence is allowed.

Context = Callable[[str, str, str], bool]


def _immediate_parent_historical(rel: str, line: str, parent_heading: str) -> bool:
    """Allow occurrences whose IMMEDIATE parent heading marks history.

    Stack-wide matching is over-permissive; a section titled 'Historical'
    would exempt all its descendants forever -- the v1 bug.
    """
    historical_markers = (
        "History", "Historical", "Migration", "Retired",
        "Provenance", "Pre-TP-114", "Deprecated",
    )
    return any(marker in parent_heading for marker in historical_markers)


def _changelog_file(rel: str, line: str, parent_heading: str) -> bool:
    return "CHANGELOG" in rel


def _test_or_pack_comment(rel: str, line: str, parent_heading: str) -> bool:
    """Allow occurrences inside line-comments in tests/ or task-packs/.

    Transitional refs during multi-step migrations. Canonical pack
    directory is lowercase ``task-packs/``.
    """
    stripped = line.lstrip()
    if not (stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("<!--")):
        return False
    return rel.startswith("tests/") or rel.startswith("task-packs/")


@dataclass(frozen=True, slots=True)
class RetiredTerm:
    term: str
    retired_in: str
    severity: str  # severity label (BLOCK/WARN/NIT/PASS). Pinned by
                   # tests/test_scanner_retired_vocab.py::
                   # TestRetiredTermSeverityClosedVocab.
    pattern: re.Pattern[str]
    allowed_contexts: tuple[Context, ...] = field(default_factory=tuple)


def _severity_label_pattern(term: str) -> re.Pattern[str]:
    """Match the term used as a severity LABEL, not as prose.

    Trailing delimiters are restricted to colon and em-dash so
    line-wrapped prose ("conflicting state.", "wrong premises ...")
    does not false-fire on the line-start anchor.

    ⚠ A BACKTICKED OCCURRENCE IS A MENTION, NOT A USE, and is excluded. Inline
    code renders as the literal characters, so ``` `**WRONG**` ``` is prose
    *about* the label -- it cannot function as one. Without this the scanner read
    documentation discussing the retired vocabulary as a use of it, which is how
    a memory row stating that these terms appear in zero files became the only
    thing making them appear. The recorded cost of that gap was
    compliance-by-rewriting: describing a term rather than naming it, paid at the
    instruction layer on every doc that needs to discuss the taxonomy.

    The guard is deliberately on the shared alternation rather than on the
    ``**TERM**`` arm alone: all four arms have the same mention-versus-use
    property, and fixing only the arm that happened to fire would leave the class
    open at three sites (Core Rule 12). The line-anchored arms cannot be preceded
    by a backtick anyway, so the lookbehind is inert for them.
    """
    return re.compile(
        rf"(?<!`)(?:\*\*{re.escape(term)}\*\*"  # **WRONG**
        rf"|^[-*]\s+{re.escape(term)}[:—]"      # - WRONG —, - WRONG:
        rf"|\|\s*{re.escape(term)}\s*\|"        # | WRONG |
        rf"|^{re.escape(term)}[:—])(?!`)",      # WRONG:, WRONG —
        re.IGNORECASE | re.MULTILINE,
    )


_ALLOWED = (_immediate_parent_historical, _changelog_file, _test_or_pack_comment)


RETIRED_TERMS: tuple[RetiredTerm, ...] = (
    RetiredTerm("WRONG", "TP-114", severity="BLOCK",
                pattern=_severity_label_pattern("WRONG"), allowed_contexts=_ALLOWED),
    RetiredTerm("CONFLICTING", "TP-114", severity="BLOCK",
                pattern=_severity_label_pattern("CONFLICTING"), allowed_contexts=_ALLOWED),
    RetiredTerm("VAGUE", "TP-114", severity="WARN",
                pattern=_severity_label_pattern("VAGUE"), allowed_contexts=_ALLOWED),
    RetiredTerm("CORRECT", "TP-114", severity="PASS",
                pattern=_severity_label_pattern("CORRECT"), allowed_contexts=_ALLOWED),
    RetiredTerm("BLOCKER", "TP-114", severity="BLOCK",
                pattern=_severity_label_pattern("BLOCKER"), allowed_contexts=_ALLOWED),
    RetiredTerm("MAJOR", "TP-114", severity="WARN",
                pattern=_severity_label_pattern("MAJOR"), allowed_contexts=_ALLOWED),
    RetiredTerm("MINOR", "TP-114", severity="NIT",
                pattern=_severity_label_pattern("MINOR"), allowed_contexts=_ALLOWED),
)

DOC_SURFACES: tuple[str, ...] = (
    "README.md", _MEMORY_FILENAME, "CLAUDE.md", "CHANGELOG.md",
    "docs/", "memory/",
    ".claude/agents/", ".claude/skills/", ".claude/commands/",
    "espalier/assets/claude/",
)

EXEMPT_FILES: frozenset[str] = frozenset({
    "tests/test_scanner_retired_vocab.py",
    "tests/fixtures/retired_vocab_positives.md",
    # The convergence ledger: an append-only RECORD of rows the convergence-critic
    # composes each round, not prose this project authored. A row quoting a
    # severity label would false-fire exactly as the retired findings corpus once
    # did (09be6f5); classify the surface before measuring it (Core Rule 13).
    # Added 2026-09-21 when that corpus retired and took its exemption with it.
    "memory/CONVERGENCE_LEDGER.md",
})

EXEMPT_PREFIXES: tuple[str, ...] = (
    "task-packs/",      # Pack drafts contain retired terms as examples
    "docs/external/",   # Verbatim quoted upstream -- prefix belt only
    "tests/fixtures/",  # Sister-site protection: fixture .md files have intentional positives
)

MAX_EXEMPT_FILES: int = 3
MAX_EXEMPT_PREFIXES: int = 5


@dataclass(frozen=True, slots=True)
class VocabFinding:
    path: Path
    lineno: int
    term: str
    retired_in: str
    severity: str  # carries the RetiredTerm.severity that fired this finding.
    line_snippet: str
    immediate_parent: str


def scan_repo(root: Path) -> list[VocabFinding]:
    findings: list[VocabFinding] = []
    for path in _doc_files(root):
        rel = str(path.relative_to(root)).replace("\\", "/")
        if rel in EXEMPT_FILES:
            continue
        if any(rel.startswith(prefix) for prefix in EXEMPT_PREFIXES):
            continue
        findings.extend(_scan_file(path, rel))
    return findings


def build_report(root: Path) -> dict:
    """Report-shape helper, so retired_vocab matches every other scanner's
    ``build_report`` surface instead of the CLI inlining the dict. ``path`` is
    normalized with ``.replace("\\", "/")`` so the emitted shape matches every
    sibling scanner's ``build_report``
    (magic_depth/filesystem_contracts/subprocess_contracts/convergence_theater)
    rather than leaking host-native backslashes."""
    findings = scan_repo(root)
    return {
        "count": len(findings),
        "findings": [
            {
                "path": str(f.path).replace("\\", "/"),
                "lineno": f.lineno,
                "term": f.term,
                "retired_in": f.retired_in,
                "severity": f.severity,
                "line_snippet": f.line_snippet,
                "immediate_parent": f.immediate_parent,
            }
            for f in findings
        ],
    }


def _doc_files(root: Path) -> Iterable[Path]:
    for surface in DOC_SURFACES:
        target = root / surface
        if target.is_file():
            yield target
        elif target.is_dir():
            yield from _safe_rglob(target, "*.md")


def _fires_as_label(term_entry: "RetiredTerm", line: str) -> bool:
    """True if the term matches on this line as a retired severity LABEL.

    The ``**term**`` and ``| term |`` shapes collide with ordinary markdown —
    adopter prose like ``**correct**`` or a semver table cell. An
    all-lowercase inner term in those two shapes is emphasis/table prose, not a
    label, so it does not fire; upper/title-case in those shapes (``**WRONG**``,
    ``**Wrong**``, ``| MAJOR |``) and the distinctive bullet/section shapes
    (``- TERM:``, ``TERM:``) at any case still fire. So a line that matches ONLY
    via a lowercase prose shape is suppressed; any non-prose match fires.
    """
    for m in term_entry.pattern.finditer(line):
        if not _is_lowercase_prose_shape(m.group(0)):
            return True
    # No match, or every match was a lowercase prose shape → not a label.
    return False


def _is_lowercase_prose_shape(matched: str) -> bool:
    """The ``**term**`` / ``| term |`` shapes with an all-lowercase inner term."""
    stripped = matched.strip()
    is_bold = stripped.startswith("**") and stripped.endswith("**")
    is_cell = stripped.startswith("|") and stripped.endswith("|")
    if not (is_bold or is_cell):
        return False
    inner = stripped.strip("*").strip("|").strip()
    return inner.islower()


def _scan_file(path: Path, rel: str) -> Iterable[VocabFinding]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    lines = text.splitlines()
    heading_stack: list[str] = []
    for lineno, line in enumerate(lines, start=1):
        _update_heading_stack(line, heading_stack)
        immediate_parent = heading_stack[-1] if heading_stack else ""
        for term_entry in RETIRED_TERMS:
            if not _fires_as_label(term_entry, line):
                continue
            if any(
                ctx(rel, line, immediate_parent)
                for ctx in term_entry.allowed_contexts
            ):
                continue
            yield VocabFinding(
                path=Path(rel), lineno=lineno, term=term_entry.term,
                retired_in=term_entry.retired_in,
                severity=term_entry.severity,
                line_snippet=line.strip()[:200],
                immediate_parent=immediate_parent,
            )


def _update_heading_stack(line: str, stack: list[str]) -> None:
    m = re.match(r"^(#+)\s+(.*)", line)
    if not m:
        return
    level = len(m.group(1))
    title = m.group(2).strip()
    while len(stack) >= level:
        stack.pop()
    stack.append(title)
