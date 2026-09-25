"""Detect convergence theater in test parity assertions.

A "convergence theater" is an assertion where both sides ultimately
resolve to the same source -- the test passes by construction rather
than by observation.

Stdlib-only. Registry is INLINED here (per `TestScannerSelfContainment`
contract at tests/test_scanners.py -- harness-package imports are
forbidden in scanner modules; scanners are copied verbatim into target
repos via inspect.getsource).

Detection shapes (severity classifier):
- THEATER -- proven self-reference:
  - literal-pair: `assert X == X`
  - same-call: `f(args) == f(args)` (identical callable + args; subsumes same-glob)
  - same-attribute: `a.b.c == a.b.c`
  - assertEqual-self: `self.assertEqual(X, X)` (unittest)
- SUSPECT -- likely theater requiring operator review:
  - derived-constant: `len(producer) == EXPECTED_DERIVED`
  - approx-self: `assert X == pytest.approx(X)` (either operand order)
  - assertEqual-same-call: `self.assertEqual(f(args), f(args))`
- VALID -- independent witnesses; not reported.

Generator-expression reductions (`assert all(x == x for x in items)`)
are NOT detected -- the outer node is `ast.Call`, not `ast.Compare`,
so neither classifier branch fires. Deferred until a real positive
surfaces.

Pragma exemption: `# theater: ok <reason >=12 chars>` on the line
directly above the assertion (or its outermost containing statement
if multi-line).

File exemption: prepend file path to EXEMPT_FILES below with
inline rationale comment.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


EXEMPT_FILES: frozenset[str] = frozenset({
    # Legacy theater classes preserved for archeology; load carried by
    # TestCommittedManifestMatchesRenderer at tests/test_manifest_truth.py.
    "tests/test_manifest_truth.py",
    # Scanner self-tests contain literal theater examples in
    # tmp_path-written file bodies that AST-parse cleanly when the
    # scanner walks the test file itself.
    "tests/test_scanner_convergence_theater.py",
})

# Per-repo cap on EXEMPT_FILES. Sister to MAX_PRAGMA_COUNT: raising the
# cap is a deliberate operator act that surfaces accumulating exemption
# debt in git log. Without this, EXEMPT_FILES grows unbounded as
# operators add files to silence flapping findings (same drift pathway
# the pragma cap was built to prevent).
MAX_EXEMPT_FILES: int = 3

# Directory prefixes whose contents are out-of-scope for the scanner.
# Sister-site protection: fixture files under tests/fixtures/ contain
# intentional theater positives; without this shared prefix, the scanner
# would false-flag them on every run.
EXEMPT_PREFIXES: tuple[str, ...] = (
    "tests/fixtures/",
)

# Anchored standalone-comment pragma with a scanner-specific token and an intentional
# minimum-reason length. Purpose-scoped sibling of the pragmas in magic_depth and
# subprocess_contracts (also anchored) and filesystem_contracts (unanchored, inline,
# shorter min-reason). Do NOT factor these into a shared PRAGMA_RE factory: it would
# break scanner self-containment and un-recognize live pragmas. Leave as-is.
PRAGMA_RE = re.compile(r"^#\s*theater:\s*ok\s+(.{12,})$")

# Per-repo cap on pragma count. Raise deliberately when the sister-site
# sweep results land; raising signals growing technical debt.
MAX_PRAGMA_COUNT: int = 5


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
class TheaterFinding:
    path: Path
    lineno: int
    severity: str   # THEATER | SUSPECT
    shape: str
    explanation: str


def scan_repo(root: Path) -> list[TheaterFinding]:
    """Walk tests/ under root; return findings (THEATER + SUSPECT only).

    Cross-references tests/_surface_expected.py (if present) to learn
    which EXPECTED_* constants are `# class: literal` (legitimate
    hand-pinned witnesses) vs `# class: derived` (computed from the
    producer). The derived-constant SUSPECT shape only fires when the
    right-hand-side EXPECTED_* is derived (or unknown); literals are
    skipped to mirror the narrow witness contract
    (tests/test_surface_expected_witness_contract.py).

    Adopter repos without tests/_surface_expected.py see every
    EXPECTED_* treated as unknown -> derived -> flagged. That is the
    conservative default.
    """
    findings: list[TheaterFinding] = []
    tests_dir = root / "tests"
    if not tests_dir.exists():
        return findings
    literal_expected = _load_literal_expected_names(root)
    for test_file in _safe_rglob(tests_dir, "test_*.py"):
        rel = str(test_file.relative_to(root)).replace("\\", "/")
        if rel in EXEMPT_FILES:
            continue
        if any(rel.startswith(prefix) for prefix in EXEMPT_PREFIXES):
            continue
        findings.extend(_scan_file(test_file, root, literal_expected))
    return findings


def _load_literal_expected_names(root: Path) -> frozenset[str]:
    """Parse tests/_surface_expected.py for `EXPECTED_X = ... # class: literal`
    annotations. Returns the set of literal names; empty if the file
    doesn't exist or has no markers.
    """
    target = root / "tests" / "_surface_expected.py"
    if not target.exists():
        return frozenset()
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return frozenset()
    names: set[str] = set()
    for raw in text.splitlines():
        if "EXPECTED_" not in raw or "=" not in raw or "# class:" not in raw:
            continue
        head, _, tail = raw.partition("=")
        name = head.strip()
        if not name.startswith("EXPECTED_"):
            continue
        # A dangling '# class:' (no token after the colon) yields an
        # empty split — guard the index so the whole scan doesn't crash.
        parts = tail.split("# class:", 1)[1].strip().split()
        cls_marker = parts[0] if parts else ""
        if cls_marker == "literal":
            names.add(name)
    return frozenset(names)


def build_report(root: Path) -> dict[str, Any]:
    """Adapter for cmd_scan integration -- matches the dict-of-counts
    shape used by the other scan_repo callers in espalier/cli.py."""
    findings = scan_repo(root)
    return {
        "count": len(findings),
        "theater_count": sum(1 for f in findings if f.severity == "THEATER"),
        "suspect_count": sum(1 for f in findings if f.severity == "SUSPECT"),
        "findings": [
            {
                "path": str(f.path).replace("\\", "/"),
                "lineno": f.lineno,
                "severity": f.severity,
                "shape": f.shape,
                "explanation": f.explanation,
            }
            for f in findings
        ],
    }


def _pragma_in_line(line: str) -> bool:
    """Single normalization point shared by both pragma
    readers (count_pragmas + _has_pragma_above). Strip before matching the
    ^#-anchored PRAGMA_RE so an indented pragma is seen consistently by the
    cap counter AND the exemption check -- never honored by one while
    invisible to the other."""
    return PRAGMA_RE.search(line.strip()) is not None


def count_pragmas(root: Path) -> int:
    """Total pragma usage across tests/ -- caller asserts <= MAX_PRAGMA_COUNT."""
    total = 0
    tests_dir = root / "tests"
    if not tests_dir.exists():
        return 0
    for test_file in _safe_rglob(tests_dir, "test_*.py"):
        rel = str(test_file.relative_to(root)).replace("\\", "/")
        # Honor the same file-scope EXEMPT filter the detector applies, so an
        # exempt fixture pragma doesn't eat the cap budget.
        if rel in EXEMPT_FILES:
            continue
        if any(rel.startswith(prefix) for prefix in EXEMPT_PREFIXES):
            continue
        try:
            source = test_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        total += sum(1 for line in source.splitlines() if _pragma_in_line(line))
    return total


def collect_pragmas(root: Path) -> list[dict]:
    """Like ``count_pragmas`` but keep the reason ``PRAGMA_RE`` group 1
    captures. Mirrors THIS scanner's count_pragmas scope (convergence
    theater: ``tests/`` only, ``tests/fixtures/`` excluded) and gates on the
    SAME ``_pragma_in_line`` normalization point so
    ``len(collect_pragmas(root)) == count_pragmas(root)`` holds — the corpus is
    the labeled per-pragma view of the same lines the cap counts. Returns
    ``{scanner, path, line, reason}`` records."""
    records: list[dict] = []
    tests_dir = root / "tests"
    if not tests_dir.exists():
        return records
    for test_file in _safe_rglob(tests_dir, "test_*.py"):
        rel = str(test_file.relative_to(root)).replace("\\", "/")
        if rel in EXEMPT_FILES:
            continue
        if any(rel.startswith(prefix) for prefix in EXEMPT_PREFIXES):
            continue
        try:
            source = test_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(source.splitlines(), start=1):
            if not _pragma_in_line(line):
                continue
            m = PRAGMA_RE.search(line.strip())
            records.append({
                "scanner": "convergence_theater", "path": rel, "line": i,
                "reason": m.group(1).strip() if m else "",
            })
    return records


def _scan_file(
    path: Path, root: Path, literal_expected: frozenset[str],
) -> Iterable[TheaterFinding]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return
    source_lines = source.splitlines()
    rel = path.relative_to(root)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare):
            yield from _classify_compare(
                node.test, node, rel, source_lines, literal_expected
            )
        elif isinstance(node, ast.Call):
            finding = _classify_unittest_call(node, rel, source_lines)
            if finding is not None:
                yield finding


def _classify_compare(
    cmp: ast.Compare,
    enclosing_stmt: ast.stmt,
    rel: Path,
    source_lines: list[str],
    literal_expected: frozenset[str],
) -> Iterable[TheaterFinding]:
    """Each ast.Compare may chain (a < b < c); pair-wise classify.

    Only `==` parity is theater shape. `>=` / `<=` / `!=` / `in` etc.
    represent floor/ceiling/inequality contracts that are legitimately
    asymmetric (e.g., `assert len(agents) >= EXPECTED_AGENT_COUNT_MIN`
    is a floor contract, not theater). This asymmetric pattern is
    deliberately preserved, and the sister contract test
    `test_derived_constants_not_used_as_witnesses` matches the same
    `==`-only filter.
    """
    if _has_pragma_above(source_lines, enclosing_stmt.lineno):
        return
    sides = [cmp.left, *cmp.comparators]
    for i, op in enumerate(cmp.ops):
        if not isinstance(op, ast.Eq):
            continue
        left, right = sides[i], sides[i + 1]
        finding = _compare_two_sides(
            left, right, rel, enclosing_stmt.lineno, literal_expected
        )
        if finding is not None:
            yield finding


def _classify_unittest_call(
    call: ast.Call, rel: Path, source_lines: list[str],
) -> Optional[TheaterFinding]:
    """Catch self.assertEqual(A, B), self.assertIs(A, B), etc."""
    if not isinstance(call.func, ast.Attribute):
        return None
    if call.func.attr not in {"assertEqual", "assertIs", "assertEquals"}:
        return None
    if len(call.args) < 2:
        return None
    if _has_pragma_above(source_lines, call.lineno):
        return None
    # Order mirrors _compare_two_sides: more-specific shape (same-call)
    # before more-generic (same-expression). Two identical len(...) calls
    # are AST-equal, so the generic check would swallow the call case
    # without this precedence.
    if (
        isinstance(call.args[0], ast.Call)
        and isinstance(call.args[1], ast.Call)
        and _ast_equal(call.args[0].func, call.args[1].func)
        and _same_args(call.args[0], call.args[1])
    ):
        return TheaterFinding(
            path=rel, lineno=call.lineno, severity="SUSPECT",
            shape="assertEqual-same-call",
            explanation=(
                f"{call.func.attr}(f(args), f(args)) -- both sides same call. "
                f"Probable theater; verify f(args) is non-deterministic."
            ),
        )
    if _ast_equal(call.args[0], call.args[1]):
        return TheaterFinding(
            path=rel, lineno=call.lineno, severity="THEATER",
            shape="assertEqual-self",
            explanation=f"{call.func.attr}(X, X) -- same expression both sides",
        )
    return None


def _compare_two_sides(
    left: ast.expr, right: ast.expr, rel: Path, lineno: int,
    literal_expected: frozenset[str] = frozenset(),
) -> Optional[TheaterFinding]:
    """Classification order matters: more-specific shapes first, so
    `assert len(items) == len(items)` reports as `same-call` (descriptive)
    rather than `literal-pair` (generic). The narrower `literal-pair`
    label is reserved for non-Call, non-Attribute equalities like
    `assert 1 == 1` or `assert name == name`.
    """
    # Order-agnostic, like the derived-constant arm below (DEF-410l):
    # `pytest.approx(X) == X` is the same tolerance check against self as
    # `X == pytest.approx(X)`, and the right-only check missed it.
    for subject, wrapped in ((left, right), (right, left)):
        if isinstance(wrapped, ast.Call) and _is_pytest_approx(wrapped.func):
            if wrapped.args and _ast_equal(subject, wrapped.args[0]):
                return TheaterFinding(
                    path=rel, lineno=lineno, severity="SUSPECT", shape="approx-self",
                    explanation=(
                        "assert X == pytest.approx(X) (either order) -- "
                        "tolerance check against self."
                    ),
                )
    # Order-agnostic + module-qualified. Fire on either
    # `len(...) == EXPECTED_X` OR `EXPECTED_X == len(...)`, and accept a
    # module-qualified `mod.EXPECTED_X` (ast.Attribute) alongside a bare
    # ast.Name. This repo's own tests/test_wheel_smoke.py uses BOTH the
    # reversed orientation and the qualified form, so a left-only /
    # bare-Name-only check would be structurally blind to a parity shape it ships.
    for len_side, exp_side in ((left, right), (right, left)):
        if not (
            isinstance(len_side, ast.Call)
            and isinstance(len_side.func, ast.Name)
            and len_side.func.id == "len"
        ):
            continue
        exp_name: Optional[str] = None
        if isinstance(exp_side, ast.Name) and exp_side.id.startswith("EXPECTED_"):
            exp_name = exp_side.id
        elif isinstance(exp_side, ast.Attribute) and exp_side.attr.startswith("EXPECTED_"):
            exp_name = exp_side.attr
        if exp_name is not None and exp_name not in literal_expected:
            return TheaterFinding(
                path=rel, lineno=lineno, severity="SUSPECT", shape="derived-constant",
                explanation=(
                    f"`len(...) == {exp_name}` is theater iff {exp_name} is "
                    f"derived. Cross-check via tests/test_surface_expected_witness_contract.py."
                ),
            )
    if isinstance(left, ast.Call) and isinstance(right, ast.Call):
        if _ast_equal(left.func, right.func) and _same_args(left, right):
            return TheaterFinding(
                path=rel, lineno=lineno, severity="SUSPECT", shape="same-call",
                explanation=(
                    f"Both sides call {_describe_callable(left.func)} with "
                    f"identical args — probable theater, BUT a stateful or "
                    f"non-deterministic callable (e.g. a fresh read on each side) "
                    f"genuinely differs at runtime; verify the callable is "
                    f"deterministic and side-effect-free before treating as theater."
                ),
            )
    if isinstance(left, ast.Attribute) and isinstance(right, ast.Attribute):
        if _ast_equal(left, right):
            return TheaterFinding(
                path=rel, lineno=lineno, severity="THEATER", shape="same-attribute",
                explanation=(
                    f"Both sides reference {_attribute_chain(left)}; "
                    f"identical expression evaluated twice."
                ),
            )
    if _ast_equal(left, right):
        return TheaterFinding(
            path=rel, lineno=lineno, severity="THEATER",
            shape="literal-pair",
            explanation="Both sides AST-identical; assertion is X == X.",
        )
    return None


def _ast_equal(a: ast.expr, b: ast.expr) -> bool:
    return ast.dump(a, annotate_fields=False) == ast.dump(b, annotate_fields=False)


def _same_args(a: ast.Call, b: ast.Call) -> bool:
    if len(a.args) != len(b.args) or len(a.keywords) != len(b.keywords):
        return False
    if not all(_ast_equal(x, y) for x, y in zip(a.args, b.args)):
        return False
    # Two calls that differ ONLY in keyword args are not a tautology
    # (e.g. render(d, sort_keys=True) == render(d, sort_keys=False)); ignoring
    # call.keywords would false-flag that as theater. Compare keywords as an
    # order-insensitive set of (name, value-dump); k.arg is None for **kwargs.
    def _kw_key(k: ast.keyword) -> tuple[str, str]:
        return (k.arg or "", ast.dump(k.value, annotate_fields=False))
    return sorted(map(_kw_key, a.keywords)) == sorted(map(_kw_key, b.keywords))


def _describe_callable(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return _attribute_chain(func)
    return "<callable>"


def _attribute_chain(attr: ast.expr) -> str:
    parts: list[str] = []
    cur: ast.expr = attr
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _is_pytest_approx(func: ast.expr) -> bool:
    """Match `pytest.approx` (Attribute form) AND `approx` (Name form from
    `from pytest import approx`). Both are documented pytest API."""
    if isinstance(func, ast.Attribute) and func.attr == "approx":
        if isinstance(func.value, ast.Name) and func.value.id == "pytest":
            return True
    if isinstance(func, ast.Name) and func.id == "approx":
        return True
    return False


def _has_pragma_above(lines: list[str], stmt_lineno: int) -> bool:
    """Pragma must be on the line directly above the assertion's
    OUTERMOST statement (handles multi-line asserts)."""
    if stmt_lineno < 2:
        return False
    return _pragma_in_line(lines[stmt_lineno - 2])
