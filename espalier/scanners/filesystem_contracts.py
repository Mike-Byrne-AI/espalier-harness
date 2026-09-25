"""Detect cross-module structured-file writes lacking a schema-parity test.

Stdlib-only AST walker. The registry is INLINED so harness-package
imports are forbidden (per TestScannerSelfContainment in
tests/test_scanners.py).

Detection covers:
- ``Path(...).write_text(...)`` / ``.write_bytes(...)`` with
  structured-suffix paths (.json / .toml / .yaml / .yml)
- ``json.dump(obj, file)`` / ``pickle.dump`` / ``yaml.dump`` / ``toml.dump``
- ``with open(path, "w") as f: ...`` blocks (alias resolution)
- Wrapper functions whose name contains "write" and "json" or matches
  WRAPPER_WRITE_PATTERNS (atomic_write_text, atomic_write_json, etc.)

Marker files (write_count, *_agent_done) are skipped — schema-parity
is not the contract surface for atomic counters or zero-byte presence
flags.
"""

from __future__ import annotations

import ast
import fnmatch
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


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
    """Symlink-safe rglob (inline copy — scanners have zero espalier imports,
    per TestScannerSelfContainment). See espalier/_safe_walk.py for the
    canonical version. ``os.walk(followlinks=False)`` never descends into a
    symlinked directory, so it is crash-safe on CPython 3.10-3.12 where bare
    ``rglob`` follows dir symlinks (ELOOP on a loop)."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        _skip_nested_repos(dirpath, dirnames)
        base = Path(dirpath)
        for name in (*dirnames, *filenames):
            if fnmatch.fnmatch(name, pattern):
                yield base / name


# ─────────────────────────────────────────────────────────────────────
FILESYSTEM_CONTRACTS: dict[str, str] = {
    "cc/blueprints/latest.json": "tests/test_cognitive_blueprint_schema_parity.py",
    ".espalier/freshness.json": "tests/test_freshness_cache_reader_parity.py",
    "cc/execution_plan.json": "tests/test_execution_plan_schema_parity.py",
    # Hook-read coordination file (SessionStart seeds gate_status from it).
    # Carved out of the reports/ output exemption via COORDINATION_FILES
    # below so it stays a schema contract surface.
    "reports/cc_surface_gate.json": "tests/test_cc_surface_gate_schema_parity.py",
}

# Files that live under an OUTPUT_PATH_PREFIXES dir but ARE
# cross-module coordination contracts (a hook/component reads them at runtime
# to make decisions), so they must NOT inherit the human-only output
# exemption. Forward-guard: today proofs.run_cc_surface_gate's write resolves
# to the partial hint `*/cc_surface_gate.json` (already non-exempt); if that
# hint ever fully resolves to `reports/cc_surface_gate.json` it would re-hit
# the reports/ prefix exemption and silently un-pin, so name it here.
COORDINATION_FILES: frozenset[str] = frozenset({
    "reports/cc_surface_gate.json",
})

STRUCTURED_SUFFIXES: frozenset[str] = frozenset({
    ".json", ".toml", ".yaml", ".yml",
})

WRAPPER_WRITE_PATTERNS: tuple[str, ...] = (
    "atomic_write_text", "atomic_write_json", "atomic_write_bytes",
    "_write_json", "write_json_atomically", "dump_json", "save_json",
    "write_toml", "dump_toml",
)

# Modes that indicate a write operation in open(path, mode, ...).
WRITE_MODE_PREFIXES: tuple[str, ...] = ("w", "a", "x")

EXEMPT_PREFIXES: tuple[str, ...] = (
    "tests/fixtures/",
    # espalier/_vendor/cc/ is a byte-identical copy of tools/cc/ (the canonical
    # source, already scanned under the "tools" scope). Skip the vendored dup so
    # its write-sites are not double-counted.
    "espalier/_vendor/",
)
MAX_EXEMPT_PREFIXES: int = 3
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FilesystemFinding:
    writer_path: Path
    writer_lineno: int
    file_path_hint: str
    severity: str  # PINNED | UNPINNED | UNSTRUCTURED | AMBIGUOUS
    explanation: str


def scan_repo(root: Path) -> list[FilesystemFinding]:
    findings: list[FilesystemFinding] = []
    for scope in ("espalier", "tools"):
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
    walks = scan_recursive_walks(root)
    return {
        "count": len(findings),
        "findings": [
            {
                "writer_path": str(f.writer_path).replace("\\", "/"),
                "writer_lineno": f.writer_lineno,
                "file_path_hint": f.file_path_hint,
                "severity": f.severity,
                "explanation": f.explanation,
            }
            for f in findings
        ],
        # bare-rglob / recursive-glob recurrence guard (separate finding
        # class from the structured-write contract above).
        "recursive_walks": {
            "count": len(walks),
            "findings": [
                {
                    "path": str(w.path).replace("\\", "/"),
                    "lineno": w.lineno,
                    "call": w.call,
                    "severity": w.severity,
                    "explanation": w.explanation,
                }
                for w in walks
            ],
        },
    }


def _scan_file(path: Path, root: Path) -> Iterable[FilesystemFinding]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            yield from _scan_with_block(node, path, root)
            continue
        hint = _extract_write_target(node)
        if hint is None:
            continue
        yield _classify(path, node.lineno, hint, root)


def _scan_with_block(
    node: ast.With, path: Path, root: Path,
) -> Iterable[FilesystemFinding]:
    """Resolve ``with open(target, "w") as alias:`` bindings and emit
    findings for any json.dump(obj, alias) etc. inside the body."""
    bindings: dict[str, str] = {}
    for item in node.items:
        ctx = item.context_expr
        if not (
            isinstance(ctx, ast.Call)
            and isinstance(ctx.func, ast.Name)
            and ctx.func.id == "open"
            and len(ctx.args) >= 2
        ):
            continue
        mode_arg = ctx.args[1]
        if not (isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str)):
            continue
        if not any(mode_arg.value.startswith(p) for p in WRITE_MODE_PREFIXES):
            continue
        target = _resolve_path_target(ctx.args[0])
        if not target or not _has_structured_suffix(target):
            continue
        alias = item.optional_vars
        if isinstance(alias, ast.Name):
            bindings[alias.id] = target
    if not bindings:
        return
    for child in ast.walk(node):
        if not (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)):
            continue
        if child.func.attr not in {"dump", "dumps"}:
            continue
        if not (
            isinstance(child.func.value, ast.Name)
            and child.func.value.id in {"json", "pickle", "yaml", "toml"}
        ):
            continue
        if len(child.args) < 2:
            continue
        file_arg = child.args[1]
        if isinstance(file_arg, ast.Name) and file_arg.id in bindings:
            yield _classify(path, child.lineno, bindings[file_arg.id], root)


def _extract_write_target(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        attr = node.func.attr
        if attr in {"write_text", "write_bytes"}:
            target = _resolve_path_target(node.func.value)
            if target and _has_structured_suffix(target):
                return target

        if attr in {"dump", "dumps"}:
            if isinstance(node.func.value, ast.Name):
                if node.func.value.id in {"json", "pickle", "yaml", "toml"}:
                    if len(node.args) >= 2:
                        target = _resolve_path_target(node.args[1])
                        if target and _has_structured_suffix(target):
                            return target

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in WRAPPER_WRITE_PATTERNS or _is_jsonish_write_wrapper(node.func.id):
            if node.args:
                target = _resolve_path_target(node.args[0])
                if target and _has_structured_suffix(target):
                    return target

    return None


def _resolve_path_target(expr: ast.expr) -> Optional[str]:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
        left = _resolve_path_target(expr.left)
        right = _resolve_path_target(expr.right)
        if left and right:
            return f"{left}/{right}"
        # Partial resolution: bp_dir / "latest.json" — the right-side
        # literal IS the contract surface. Mark left as unresolved with
        # */, and _classify will suffix-match against FILESYSTEM_CONTRACTS.
        if right and _has_structured_suffix(right):
            return f"*/{right}"
        return None
    if (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id == "Path"
    ):
        if expr.args and isinstance(expr.args[0], ast.Constant):
            value = expr.args[0].value
            if isinstance(value, str):
                return value
    return None


def _has_structured_suffix(path: str) -> bool:
    return any(path.endswith(suffix) for suffix in STRUCTURED_SUFFIXES)


def _is_jsonish_write_wrapper(name: str) -> bool:
    """A write-json wrapper by snake-token shape, not stray substrings.

    The old ``"write" in name and "json" in name`` over-fired on
    ``rewrite_json_cache``, ``overwrite_jsonish`` (sweep T4-A). Require a
    ``write``/``save``/``dump`` ACTION token adjacent to a
    ``json``/``toml``/``yaml`` FORMAT token in the snake-case name, so the name
    reads as a serialise-write sink, not a word that merely contains the
    letters. ``rewrite``/``overwrite`` are not the ``write`` token (they start a
    different word), so they no longer match; ``write_json``/``my_write_json``
    still do.
    """
    tokens = name.split("_")
    actions = {"write", "save", "dump"}
    formats = {"json", "toml", "yaml", "yml"}
    for i, tok in enumerate(tokens):
        if tok in actions and i + 1 < len(tokens) and tokens[i + 1] in formats:
            return True
    return False


def _is_temporary_path(hint: str) -> bool:
    """True iff the path hint names a temporary location.

    Anchored to path SEGMENTS: a segment must BE ``tmp``/``temp`` or begin
    with ``tmp`` (``tmp_path`` / ``tmpdir`` / mkstemp's ``tmpXXXX`` names).
    Segment-anchoring (rather than a bare ``"tmp" in hint`` substring) avoids
    demoting a structured path with a mid-word ``tmp`` (``reports/notmp/x.json``,
    ``src/footmp/y.json``) that is not temporary at all.
    """
    if (
        hint.startswith("/tmp/")
        or hint.startswith("/var/folders/")
        or "mkstemp" in hint
    ):
        return True
    low = hint.lower().replace("\\", "/")
    for seg in low.split("/"):
        if seg == "tmp" or seg == "temp" or seg.startswith("tmp"):
            return True
    return False


# Output-only prefixes — these are write-once-by-producer-read-by-humans
# artifacts (scan/fingerprint reports, audit logs). They are not
# cross-module coordination contracts: no other harness component reads
# them at runtime to make decisions. Schema-parity tests for these would
# create unrelated contract drift signal.
OUTPUT_PATH_PREFIXES: tuple[str, ...] = (
    "reports/", "*/reports/",
)

# Filename suffixes that name a scanner/fingerprint output regardless of
# the containing directory. The bare-filename match handles the common
# `reports_dir / "X.json"` pattern where the left side is a Name the
# scanner cannot resolve back to `reports/`.
OUTPUT_FILENAME_SUFFIXES: tuple[str, ...] = (
    "/repo_fingerprint.json",
    "/harness_config.json",
    "/scan_exceptions.json",
    "/scan_prints.json",
    "/scan_perf_smells.json",
    "/scan_test_loosening.json",
    "/scan_convergence_theater.json",
    "/scan_subprocess_contracts.json",
    "/scan_filesystem_contracts.json",
    "/scan_magic_depth.json",
    "/scan_retired_vocab.json",
    "/scan_encoding_contracts.json",
    "/godfiles_report.json",
    "/scan_summary.json",
    # `espalier strengthen` advisory test-gap report — human/advisory output,
    # same class as the scan_*.json above (the suggest layer may read it but
    # does not gate on it at runtime).
    "/strengthen_report.json",
    # Self-gov scanner telemetry/credibility outputs under reports/.
    # Diagnostic artifacts, not cross-module coordination files — same class as
    # the scan_*.json above (no schema-parity contract needed).
    "/scan_overrides.json",
    "/scan_telemetry.jsonl",
    "/scan_baseline.json",
)


def _is_output_path(hint: str) -> bool:
    # Coordination contracts checked FIRST — a hook-read file is never a
    # human-only output even if it sits under reports/.
    if hint in COORDINATION_FILES:
        return False
    if any(hint.startswith(prefix) for prefix in OUTPUT_PATH_PREFIXES):
        return True
    return any(hint.endswith(suffix) for suffix in OUTPUT_FILENAME_SUFFIXES)


def _classify(
    path: Path, lineno: int, hint: str, root: Path,
) -> FilesystemFinding:
    rel = path.relative_to(root)
    if _is_temporary_path(hint):
        return FilesystemFinding(
            writer_path=rel, writer_lineno=lineno, file_path_hint=hint,
            severity="UNSTRUCTURED", explanation="temporary path; skipped",
        )
    if _is_output_path(hint):
        return FilesystemFinding(
            writer_path=rel, writer_lineno=lineno, file_path_hint=hint,
            severity="UNSTRUCTURED",
            explanation="scanner/fingerprint output; not cross-module contract",
        )
    if hint in FILESYSTEM_CONTRACTS:
        return FilesystemFinding(
            writer_path=rel, writer_lineno=lineno, file_path_hint=hint,
            severity="PINNED",
            explanation=f"contract: {FILESYSTEM_CONTRACTS[hint]}",
        )
    if hint.startswith("*/"):
        suffix = hint[2:]
        matches = [
            (cp, tp) for cp, tp in FILESYSTEM_CONTRACTS.items()
            if cp == suffix or cp.endswith(f"/{suffix}")
        ]
        if len(matches) > 1:
            # Forward-guard: two contracts share a basename, so a `*/X` partial
            # hint cannot be resolved to ONE pinned surface — reading it as
            # PINNED would silently claim coverage of whichever contract sorts
            # first (sweep T4-B). No live collision today; AMBIGUOUS makes a
            # future collision visible instead of a false all-clear.
            colliding = ", ".join(cp for cp, _ in matches)
            return FilesystemFinding(
                writer_path=rel, writer_lineno=lineno, file_path_hint=hint,
                severity="AMBIGUOUS",
                explanation=(
                    f"partial hint {hint!r} matches multiple contracts by "
                    f"basename ({colliding}); resolve the write to a literal "
                    f"path so the parity test is unambiguous."
                ),
            )
        if matches:
            contract_path, test_path = matches[0]
            return FilesystemFinding(
                writer_path=rel, writer_lineno=lineno, file_path_hint=hint,
                severity="PINNED",
                explanation=(
                    f"contract (suffix match {suffix!r} -> "
                    f"{contract_path!r}): {test_path}"
                ),
            )
    return FilesystemFinding(
        writer_path=rel, writer_lineno=lineno, file_path_hint=hint,
        severity="UNPINNED",
        explanation=(
            f"Stealth filesystem contract: {rel}:{lineno} writes "
            f"structured file `{hint}` with no schema-parity test."
        ),
    )


# ─────────────────────────────────────────────────────────────────────
# bare-rglob / recursive-glob recurrence guard.
#
# ``Path.rglob(...)`` and recursive ``Path.glob("**/...")`` follow directory
# symlinks on CPython < 3.13 (ELOOP crash on a loop, inflation on a plain dir
# symlink); ``os.walk(..., followlinks=True)`` follows them on EVERY version.
# The class fix replaces every adopter-tree walk with the symlink-safe
# ``safe_rglob``/``_safe_rglob`` (os.walk followlinks=False, the default); this
# AST check stops a NEW symlink-following recursive walk from re-entering the
# codebase unannotated. It flags three shapes: a bare ``.rglob(...)``, a
# literal-recursive ``.glob("**/...")``, and an EXPLICIT
# ``os.walk(..., followlinks=True)`` (bare ``os.walk`` defaults to
# followlinks=False and is safe on all versions — NOT flagged). A genuinely-safe
# site (espalier-own / deploy-source) carries a trailing
# ``# espalier:safe-walk-ok <reason>`` pragma on the call's own line or the line
# directly above it.
#
# Known blind spots (this is a recurrence net, NOT a completeness proof):
#   * a ``glob`` whose pattern is a runtime VARIABLE (not a literal) — see
#     docs/FAILURE_MODES.md §2.8;
#   * a pragma on the CLOSING line of a multi-line enclosing call (place it on
#     the ``.rglob``/``.glob`` token line);
#   * SCOPE is ``espalier/`` + ``tools/`` + the fusion-overlaid ``scripts/``
#     subset (RGLOB_SCAN_OVERLAID_SCRIPTS) — the shipped surface. ``scripts/``
#     files that are NOT in fusion_manifest.HARNESS_INCLUDE, plus ``tests/`` and
#     ``bench/``, are dev-only (neither wheel nor adopter deploy) and stay
#     unscanned, so a bare rglob there is not a finding.
# ─────────────────────────────────────────────────────────────────────
# Anchored to a ``#`` so the marker only counts inside a COMMENT — a string
# literal containing the marker text must not silently suppress a finding.
# Unanchored INLINE pragma with a shorter min-reason — intentionally distinct from the
# anchored standalone-comment PRAGMA_RE in convergence_theater / magic_depth /
# subprocess_contracts. Same concept, different placement model; not a collapse candidate.
SAFE_WALK_PRAGMA_RE = re.compile(r"#[^\n]*espalier:safe-walk-ok\s+(.{6,})")

# Scoped to the harness's own source dirs; the vendored mirror is a
# byte-identical copy of tools/cc (mirror-parity test), and _safe_walk.py is
# the canonical helper (os.walk, not rglob) — both exempt.
RGLOB_SCAN_SCOPES: tuple[str, ...] = ("espalier", "tools")

# The scripts/ files the fusion overlays into every adopter repo
# (fusion_manifest.HARNESS_INCLUDE's *.py members) — a shipped surface, so a bare
# rglob there is a real finding. Scanners cannot import espalier
# (TestScannerSelfContainment), so this list is hardcoded and drift-pinned by
# tests/test_scanner_filesystem_contracts.py::test_overlaid_scripts_match_manifest
# (it reds the moment a new overlaid script is added). The dev-only scripts/
# files (release_check.py, sync_vendor_cc.py, …) are NOT overlaid and stay
# unscanned — scanning them would re-introduce false-positives on dev tooling.
RGLOB_SCAN_OVERLAID_SCRIPTS: tuple[str, ...] = (
    "scripts/check_exception_policy.py",
    "scripts/check_memory_md_tag_parity.py",
)
RGLOB_EXEMPT_PREFIXES: tuple[str, ...] = (
    "espalier/_vendor/",
    "espalier/_safe_walk.py",
    "tests/fixtures/",
)


@dataclass(frozen=True, slots=True)
class RecursiveWalkFinding:
    path: Path
    lineno: int
    call: str       # "rglob" | "glob(**)" | "os.walk(followlinks=True)"
    severity: str   # FLAGGED
    explanation: str


def scan_recursive_walks(root: Path) -> list[RecursiveWalkFinding]:
    """Flag every UNannotated bare ``.rglob(...)`` / literal-recursive
    ``.glob("**/...")`` call under espalier/ + tools/. Annotated sites
    (trailing ``# espalier:safe-walk-ok <reason>``) are not findings."""
    findings: list[RecursiveWalkFinding] = []
    for scope in RGLOB_SCAN_SCOPES:
        scope_dir = root / scope
        if not scope_dir.is_dir():
            continue
        for path in _safe_rglob(scope_dir, "*.py"):
            rel = str(path.relative_to(root)).replace("\\", "/")
            if any(rel == p or rel.startswith(p) for p in RGLOB_EXEMPT_PREFIXES):
                continue
            findings.extend(_scan_recursive_walks_file(path, root))
    # The fusion-overlaid scripts/ subset is a shipped surface too — scan each
    # explicitly (it lives outside RGLOB_SCAN_SCOPES). Same per-file analyzer +
    # exempt-prefix + pragma handling as the dir loop above.
    for rel in RGLOB_SCAN_OVERLAID_SCRIPTS:
        if any(rel == p or rel.startswith(p) for p in RGLOB_EXEMPT_PREFIXES):
            continue
        path = root / rel
        if not path.is_file():
            continue
        findings.extend(_scan_recursive_walks_file(path, root))
    return findings


def _scan_recursive_walks_file(
    path: Path, root: Path,
) -> Iterable[RecursiveWalkFinding]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return
    lines = source.splitlines()
    rel = str(path.relative_to(root)).replace("\\", "/")
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr = node.func.attr
        if attr == "rglob":
            call_label = "rglob"
        elif attr == "glob" and node.args:
            a0 = node.args[0]
            if (
                isinstance(a0, ast.Constant)
                and isinstance(a0.value, str)
                and "**" in a0.value
            ):
                call_label = "glob(**)"
            else:
                continue
        elif attr == "walk" and _walk_follows_symlinks(node):
            call_label = "os.walk(followlinks=True)"
        else:
            continue
        if _has_safe_walk_pragma(lines, node):
            continue
        yield RecursiveWalkFinding(
            path=Path(rel), lineno=node.lineno, call=call_label, severity="FLAGGED",
            explanation=(
                f"bare `{call_label}` at {rel}:{node.lineno} follows directory "
                f"symlinks on CPython <3.13 (ELOOP on a loop). Replace with "
                f"safe_rglob/_safe_rglob (os.walk followlinks=False) OR annotate "
                f"`# espalier:safe-walk-ok <reason>` if it never walks an adopter tree."
            ),
        )


def _walk_follows_symlinks(node: ast.Call) -> bool:
    """True iff an ``os.walk(...)`` call passes ``followlinks=True`` — the
    one os.walk shape that descends into a symlinked directory (the same class
    as bare rglob). Bare ``os.walk`` defaults to followlinks=False and is safe.
    Handles the keyword form and the 4th-positional form."""
    for kw in node.keywords:
        if (
            kw.arg == "followlinks"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
        ):
            return True
    # os.walk(top, topdown, onerror, followlinks): followlinks is positional 4.
    if (
        len(node.args) >= 4
        and isinstance(node.args[3], ast.Constant)
        and node.args[3].value is True
    ):
        return True
    return False


def _has_safe_walk_pragma(lines: list[str], node: ast.AST) -> bool:
    """True iff the call's own line-span (or the line directly above it)
    carries the ``# espalier:safe-walk-ok <reason>`` pragma. The pragma must sit
    on the ``.rglob``/``.glob``/``os.walk`` token line or the line above it — a
    pragma on the closing line of a multi-line enclosing call is NOT seen (see
    the module guard comment)."""
    start = node.lineno
    end = getattr(node, "end_lineno", None) or start
    for idx in (*range(start - 1, end), start - 2):
        if 0 <= idx < len(lines) and SAFE_WALK_PRAGMA_RE.search(lines[idx]):
            return True
    return False
