"""Detect any ``.parents[N]`` subscript (receiver-type-blind) with N >= 2 not in MAGIC_DEPTH_SITES.

Stdlib-only AST walker. The registry is INLINED so harness-package
imports are forbidden (per TestScannerSelfContainment in
tests/test_scanners.py).

Dynamic indices (``parents[N_VAR]``, ``parents[some_expr]``) are
flagged as UNPINNED requiring explicit
``# magic-depth: ok dynamic-index <reason>``. The reason length floor
of 12 chars forces a non-trivial justification.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# ─────────────────────────────────────────────────────────────────────
# A LINE-KEYED REGISTRY, RETIRED ON THE SELF-HOST TREE (ledger DEF-417j).
#
# The key was `<file>:<line>`, so an edit ABOVE a pinned site un-keyed it: the real
# site went UNPINNED (loud, fine) while the stale key silently kept describing
# nothing -- and worse, a DIFFERENT parents[N] later landing on that line number
# inherited the exemption without anyone deciding to. It drifted once in the wild
# (131 -> 133, from expanding a comment four lines above) and cost a red in a file
# the editor had no reason to think was involved.
#
# The pragma below is the drift-proof replacement and the go-forward mechanism: it
# rides ON the line it exempts, so it cannot be separated from its site by any edit.
# The self-host tree holds this dict empty -- pinned by
# tests/test_scanner_magic_depth.py::test_registry_stays_empty_line_keys_are_retired.
#
# STILL WIRED, DELIBERATELY, and not dead code: an ADOPTER may have a parents[N] in
# a generated or vendored file they cannot annotate. For them the registry is the
# only escape hatch, so the mechanism ships; only this repo's own use of it is
# ratcheted off. Prefer the pragma wherever the file can carry a comment.
MAGIC_DEPTH_SITES: dict[str, str] = {}

# Anchored standalone-comment pragma, scanner-specific token + intentional min-reason.
# Purpose-scoped sibling of the convergence_theater / subprocess_contracts pragmas and
# the unanchored inline one in filesystem_contracts; do NOT collapse into a shared
# factory (it would break scanner self-containment and un-recognize live pragmas).
PRAGMA_RE = re.compile(r"^#\s*magic-depth:\s*ok\s+(.{12,})$")
MAX_PRAGMA_COUNT: int = 3

# Sister-site protection: fixture files contain intentional positives;
# the live-fire test would false-flag them without this prefix
# exclusion.
EXEMPT_PREFIXES: tuple[str, ...] = (
    "tests/fixtures/",
    # espalier/_vendor/cc/ is a byte-identical copy of tools/cc/ (the canonical
    # source, already scanned under the "tools" scope). Skip the vendored dup so
    # its sites are not double-counted.
    "espalier/_vendor/",
)
MAX_EXEMPT_PREFIXES: int = 3
# ─────────────────────────────────────────────────────────────────────


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


@dataclass(frozen=True, slots=True)
class MagicDepthFinding:
    path: Path
    lineno: int
    depth: Optional[int]    # None for dynamic indices
    severity: str           # PINNED | UNPINNED
    explanation: str


def scan_repo(root: Path) -> list[MagicDepthFinding]:
    findings: list[MagicDepthFinding] = []
    for scope in ("espalier", "tools", "scripts", "tests"):
        scope_dir = root / scope
        if not scope_dir.is_dir():
            continue
        for path in _safe_rglob(scope_dir, "*.py"):
            rel = str(path.relative_to(root)).replace("\\", "/")
            if any(rel.startswith(prefix) for prefix in EXEMPT_PREFIXES):
                continue
            findings.extend(_scan_file(path, root))
    return findings


def build_report(root: Path) -> dict:
    findings = scan_repo(root)
    return {
        "count": len(findings),
        "findings": [
            {
                "path": str(f.path).replace("\\", "/"),
                "lineno": f.lineno,
                "depth": f.depth,
                "severity": f.severity,
                "explanation": f.explanation,
            }
            for f in findings
        ],
    }


def _pragma_in_line(line: str) -> bool:
    """Single normalization point shared by both pragma readers
    (count_pragmas + _has_pragma_above). Strip before matching the
    ^#-anchored PRAGMA_RE so an indented pragma is seen consistently by the
    cap counter AND the exemption check -- never honored by one while
    invisible to the other."""
    return PRAGMA_RE.search(line.strip()) is not None


def count_pragmas(root: Path) -> int:
    total = 0
    for scope in ("espalier", "tools", "scripts", "tests"):
        scope_dir = root / scope
        if not scope_dir.is_dir():
            continue
        for path in _safe_rglob(scope_dir, "*.py"):
            rel = str(path.relative_to(root)).replace("\\", "/")
            # Honor the same file-scope EXEMPT filter the detector applies, so
            # an exempt fixture pragma doesn't eat the cap budget.
            if any(rel.startswith(prefix) for prefix in EXEMPT_PREFIXES):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            total += sum(1 for line in source.splitlines() if _pragma_in_line(line))
    return total


def collect_pragmas(root: Path) -> list[dict]:
    """Like ``count_pragmas`` but keep the reason ``PRAGMA_RE`` group 1 captures.
    Mirrors THIS scanner's count_pragmas scope (all four:
    ``espalier``/``tools``/``scripts``/``tests``, ``tests/fixtures/`` excluded)
    and gates on the SAME ``_pragma_in_line`` normalization point so
    ``len(collect_pragmas(root)) == count_pragmas(root)`` holds.
    Returns ``{scanner, path, line, reason}`` records."""
    records: list[dict] = []
    for scope in ("espalier", "tools", "scripts", "tests"):
        scope_dir = root / scope
        if not scope_dir.is_dir():
            continue
        for path in _safe_rglob(scope_dir, "*.py"):
            rel = str(path.relative_to(root)).replace("\\", "/")
            if any(rel.startswith(prefix) for prefix in EXEMPT_PREFIXES):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(source.splitlines(), start=1):
                if not _pragma_in_line(line):
                    continue
                m = PRAGMA_RE.search(line.strip())
                records.append({
                    "scanner": "magic_depth", "path": rel, "line": i,
                    "reason": m.group(1).strip() if m else "",
                })
    return records


def _scan_file(path: Path, root: Path) -> Iterable[MagicDepthFinding]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return
    source_lines = source.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        if not _is_parents_subscript(node):
            continue
        depth = _extract_constant_index(node)
        if depth is not None and depth < 2:
            continue
        yield _classify(path, _parents_lineno(node), depth, root, source_lines)


def _is_parents_subscript(node: ast.Subscript) -> bool:
    value = node.value
    return isinstance(value, ast.Attribute) and value.attr == "parents"


def _parents_lineno(node: ast.Subscript) -> int:
    """Line of the ``.parents[N]`` access, not the expression start.

    On a multi-line chain (``Path(...).resolve()`` then ``.parents[N]`` on a
    later line), ``node.lineno`` is the EXPR START, so the finding cites the
    wrong line AND a pragma / MAGIC_DEPTH_SITES key on the real ``.parents``
    line is invisible (sweep T5). ``node.value`` is the
    ``Attribute(attr="parents")``; its ``end_lineno`` is the ``.parents`` line.
    Fall back to ``node.lineno`` if end_lineno is absent (older grammar).
    """
    attr = node.value  # Attribute(attr="parents") — guaranteed by _is_parents_subscript
    end = getattr(attr, "end_lineno", None)
    return end if isinstance(end, int) else node.lineno


def _extract_constant_index(node: ast.Subscript) -> Optional[int]:
    slice_node = node.slice
    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, int):
        return slice_node.value
    # A negative index ``parents[-1]`` parses as ``UnaryOp(USub,
    # Constant(int))``, which the Constant-only check above misses → depth
    # None → spurious UNPINNED finding on a fully-static from-the-end
    # reference. Resolve the signed constant so the depth<2 floor skips it
    # (a negative index is not a positive structural depth).
    if (
        isinstance(slice_node, ast.UnaryOp)
        and isinstance(slice_node.op, (ast.USub, ast.UAdd))
        and isinstance(slice_node.operand, ast.Constant)
        and isinstance(slice_node.operand.value, int)
    ):
        value = slice_node.operand.value
        return -value if isinstance(slice_node.op, ast.USub) else value
    return None


def _classify(
    path: Path, lineno: int, depth: Optional[int], root: Path, source_lines: list[str],
) -> MagicDepthFinding:
    rel = str(path.relative_to(root)).replace("\\", "/")
    key = f"{rel}:{lineno}"
    depth_label = f"parents[{depth}]" if depth is not None else "parents[<dynamic>]"

    if _has_pragma_above(source_lines, lineno):
        return MagicDepthFinding(
            path=Path(rel), lineno=lineno, depth=depth, severity="PINNED",
            explanation=f"inline `# magic-depth: ok` pragma on {depth_label}",
        )
    if key in MAGIC_DEPTH_SITES:
        return MagicDepthFinding(
            path=Path(rel), lineno=lineno, depth=depth, severity="PINNED",
            explanation=f"registry: {MAGIC_DEPTH_SITES[key]}",
        )
    if depth is None:
        return MagicDepthFinding(
            path=Path(rel), lineno=lineno, depth=None, severity="UNPINNED",
            explanation=(
                f"`parents[<dynamic>]` at {rel}:{lineno} — dynamic index "
                f"with no `# magic-depth: ok` pragma. Either pin the depth "
                f"as a constant OR add pragma with reason >=12 chars."
            ),
        )
    return MagicDepthFinding(
        path=Path(rel), lineno=lineno, depth=depth, severity="UNPINNED",
        explanation=(
            f"`{depth_label}` at {rel}:{lineno} encodes a structural depth "
            f"assumption with no documentation. Add to MAGIC_DEPTH_SITES "
            f"with one-line rationale OR add `# magic-depth: ok <reason>` "
            f"pragma."
        ),
    )


def _has_pragma_above(lines: list[str], lineno: int) -> bool:
    if lineno < 2:
        return False
    return _pragma_in_line(lines[lineno - 2])
