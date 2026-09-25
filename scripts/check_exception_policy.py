#!/usr/bin/env python3
"""Exception-policy regression gate.

Walks ``espalier/`` and ``tools/cc/`` for broad except-handlers in three
distinct categories:

- ``bare`` — ``except:`` with no type (aliases BaseException, no
  name binding). Always a finding; no legitimate use case here.
- ``exception`` — ``except Exception`` (signal-safe; covers the
  regular exception hierarchy). Default-flagged; per-site
  ``# noqa: BLE001 — <reason>`` annotation acknowledges.
- ``baseexception`` — ``except BaseException`` (catches signals
  including KeyboardInterrupt and SystemExit). Flagged by default;
  EXEMPT at hook entrypoints because Claude Code's hook protocol
  treats exit 1 as "hook bug — allow the tool call to proceed",
  which is the OPPOSITE of the deny-on-uncertainty contract a
  guard hook needs. See docs/CONVENTIONS.md "Hook entrypoints:
  catch BaseException, deny on uncertainty".

Each non-exempt finding satisfies one of:

1. The except line carries a ``# noqa: BLE001`` marker (deliberate
   broad except; see docs/CONVENTIONS.md "Broad-except narrowing").
2. The handler is narrowed to specific exception types
   (``except (ValueError, OSError):`` etc.) — these are NOT matched
   by this scanner and need no annotation.

Pre-existing unannotated sites are recorded in
``scripts/exception_policy_allowlist.json`` so the gate fires only on
NEW additions. The allowlist shrinks over time as narrowing continues.

Stdlib-only. Exit 0 = clean; exit 1 = NEW unannotated handler found.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST_PATH = REPO_ROOT / "scripts" / "exception_policy_allowlist.json"
SCAN_ROOTS = ("espalier", "tools/cc")


HOOK_ENTRYPOINT_DIRS: tuple[str, ...] = (
    "tools/cc/hooks/",
)
"""Directory prefixes whose ``*.py`` entrypoints share the
deny-on-uncertainty hook contract. BaseException catches in any file
under these prefixes are EXEMPT from the scanner."""

HOOK_ENTRYPOINT_FILES: tuple[str, ...] = (
    "tools/cc/ci_guard.py",
    "tools/cc/cognitive_blueprint.py",
    "tools/cc/execution_plan.py",
    "tools/cc/reflect_protocol.py",
    "tools/cc/statusline.py",
    "tools/cc/session_resume.py",
)
"""Individual files outside HOOK_ENTRYPOINT_DIRS that share the
deny-on-uncertainty contract: ci_guard runs at the CI tier with the
same fail-closed semantics; the other four are harness-internal
helpers that hook scripts dispatch into at the top-level entrypoint
and therefore inherit the contract. Adding a new file here without
documenting its entrypoint discipline is the failure shape this
list guards against — the cardinality is pinned by
tests/test_exception_policy.py::test_hook_entrypoint_files_cardinality_pinned."""


def _is_hook_entrypoint(rel_path: str) -> bool:
    """True when ``rel_path`` belongs to a hook entrypoint surface.

    Path is normalised to forward-slash form before prefix matching
    so Windows-style ``tools\\cc\\hooks\\...`` paths still match.
    """
    rel_path = rel_path.replace("\\", "/")
    if any(rel_path.startswith(d) for d in HOOK_ENTRYPOINT_DIRS):
        return True
    return rel_path in HOOK_ENTRYPOINT_FILES


def _classify_handler(handler: ast.ExceptHandler) -> str | None:
    """Return one of ``"bare"``, ``"exception"``, ``"baseexception"``
    or ``None`` (handler is narrower than broad).
    """
    if handler.type is None:
        return "bare"
    if isinstance(handler.type, ast.Name):
        if handler.type.id == "Exception":
            return "exception"
        if handler.type.id == "BaseException":
            return "baseexception"
    return None


# Retained for backwards compatibility with any internal callers that
# imported the original predicate. Returns True for the same shapes the
# original recognised (bare + Exception). BaseException is NOT included
# here; the three-construct split lives in _classify_handler.
def _is_broad_except(handler: ast.ExceptHandler) -> bool:
    """True if the handler matches ``except:`` or ``except Exception[ as e]:``.

    Kept for backwards compatibility. Prefer ``_classify_handler`` for
    new code — it surfaces all three broad-except constructs distinctly
    so the BaseException-at-hook exemption can apply.
    """
    return _classify_handler(handler) in ("bare", "exception")


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line: int
    kind: str
    message: str


# Tolerant of either ``--`` (ASCII) or ``—`` (em-dash) as the
# code/reason separator; some sites use em-dash freely. Sister-shape:
# ``tests/test_hook_audit_noqa_annotations.NOQA_RE``.
_NOQA_CODES_RE = re.compile(r"noqa:\s*([A-Z0-9,\s]+?)(?:\s+(?:--|—)|\s*$)")


def _has_noqa_marker(file_text: str, lineno: int) -> bool:
    """True if the source line carries ``# noqa`` with BLE001 in its code set.

    Order-insensitive: parses comma-separated codes after ``noqa:`` as a
    set, so ``noqa: S110, BLE001`` is accepted (a bare substring match for
    ``"noqa: BLE001"`` would silently reject it).
    """
    lines = file_text.splitlines()
    if not (1 <= lineno <= len(lines)):
        return False
    match = _NOQA_CODES_RE.search(lines[lineno - 1])
    if not match:
        return False
    codes = {c.strip() for c in match.group(1).split(",")}
    return "BLE001" in codes


def scan_file(path: Path, rel_path: str | None = None) -> list[Finding]:
    """Scan a single Python file for broad-except findings.

    ``rel_path`` (if provided) is the repository-relative path used
    for hook-entrypoint matching and finding reporting. When omitted,
    the absolute ``path`` is used as-is.

    Returns one ``Finding`` per non-exempt, non-noqa broad-except
    handler. The list is empty when the file has only narrow handlers
    or every broad handler is annotated / exempt.
    """
    rel = rel_path if rel_path is not None else str(path)
    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except (SyntaxError, OSError, UnicodeDecodeError):
        return findings
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        kind = _classify_handler(node)
        if kind is None:
            continue
        if kind == "baseexception" and _is_hook_entrypoint(rel):
            # Counterfactual: BaseException at hook entrypoints is the
            # CORRECT deny-on-uncertainty form (Claude Code treats
            # exit 1 as "hook bug — allow"; the hook must fail-closed
            # on signals too). Not a finding.
            continue
        if _has_noqa_marker(text, node.lineno):
            continue
        findings.append(Finding(
            path=rel,
            line=node.lineno,
            kind=kind,
            message=f"broad-except ({kind}) without justification",
        ))
    return findings


def find_unannotated_broad_excepts(repo_root: Path) -> list[str]:
    """Return ``"rel:lineno"`` for every unannotated broad except.

    Files outside SCAN_ROOTS are ignored. Syntax errors yield an empty
    list for that file (best-effort scan; CI's `compile()` covers
    parse errors separately). Delegates to ``scan_file``.
    """
    findings: list[str] = []
    for root in SCAN_ROOTS:
        base = repo_root / root
        if not base.is_dir():
            continue
        # os.walk(followlinks=False) is symlink-loop-safe on every CPython
        # version; bare base.rglob("*.py") follows directory symlinks on
        # CPython 3.10-3.12 (recurse_symlinks=False only became the default in
        # 3.13) → ELOOP on an adopter loop (FAILURE_MODES §9.7).
        # Stdlib-only file: inline os.walk, do NOT import espalier._safe_walk.
        py_files: list[Path] = []
        for dirpath, _dirnames, filenames in os.walk(base, followlinks=False):
            for name in filenames:
                if name.endswith(".py"):
                    py_files.append(Path(dirpath) / name)
        for py in sorted(py_files):
            rel = py.relative_to(repo_root).as_posix()
            if rel.startswith("espalier/_vendor/"):
                # Byte-identical mirror of tools/cc / selfcheck tests; the
                # canonical copies are scanned under their real roots. Sibling
                # scanners (magic_depth, filesystem_contracts) exclude it too.
                continue
            for f in scan_file(py, rel):
                findings.append(f"{f.path}:{f.line}")
    return findings


def _load_allowlist() -> set[str]:
    if not ALLOWLIST_PATH.exists():
        return set()
    try:
        data = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # strict decode: a structured answer (DEF-829)
        return set()
    return set(data.get("grandfathered", []))


def main() -> int:
    findings = set(find_unannotated_broad_excepts(REPO_ROOT))
    allowlist = _load_allowlist()
    new_violations = sorted(findings - allowlist)
    stale_allowlist = sorted(allowlist - findings)

    if new_violations:
        print(
            "[FAIL] exception-policy: new unannotated broad-except handlers:",
            file=sys.stderr,
        )
        for v in new_violations:
            print(f"  {v}", file=sys.stderr)
        print(
            "\nFix: narrow to a concrete exception tuple "
            "(e.g., `(ValueError, OSError)`) OR annotate the line "
            "with `# noqa: BLE001 -- <one-line reason>`. See "
            "docs/CONVENTIONS.md 'Broad-except narrowing'.",
            file=sys.stderr,
        )
        return 1

    if stale_allowlist:
        print(
            "[INFO] exception-policy: allowlist entries no longer present "
            "in source (remove from allowlist):",
            file=sys.stderr,
        )
        for v in stale_allowlist:
            print(f"  {v}", file=sys.stderr)

    print(
        f"[PASS] exception-policy: {len(findings)} grandfathered handler(s); "
        f"0 new violations.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
