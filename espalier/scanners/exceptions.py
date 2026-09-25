#!/usr/bin/env python3
"""Find swallowed exceptions: bare except:pass, broad catches without re-raise or logging."""
from __future__ import annotations

import ast
import json
import os
from typing import Any

# NOTE: "cc" is a bare BASENAME, so os.walk prunes EVERY directory named cc at
# any depth -- the top-level blueprints cc/, tools/cc/, and its
# espalier/_vendor/cc/ byte-mirror. Deliberate: those governed harness-internal
# trees carry their own dense hits that would otherwise flood `espalier scan`.
# Caveat (latent, adopter-only): it also prunes an adopter package coincidentally
# named cc/, and --exclude only ADDs to this set (no override). If that ever
# bites, scope to the three harness cc path-suffixes explicitly, not a repo-root
# prefix (tools/cc & _vendor/cc are NOT at repo root).
DEFAULT_EXCLUDE = {".git", ".venv", "venv", "__pycache__", ".pytest_cache",
                   "node_modules", "dist", "build", ".mypy_cache", ".ruff_cache",
                   "cc"}

# Skip earn-the-gate fixtures so live `espalier scan exceptions`
# runs are not polluted by the scanner's own positive-case test data.
# The tests/test_scanner_exceptions.py earn-the-gate test bypasses this
# filter by calling scan_file directly with the fixture path.
EXEMPT_PREFIXES: tuple[str, ...] = ("tests/fixtures/",)


def _skip_nested_repos(dirpath: str, dirnames: list[str]) -> None:
    """Drop embedded-repo subdirs from an os.walk ``dirnames`` in place — parity
    with ``espalier._safe_walk.safe_rglob(skip_nested_repos=True)``. Scanners are
    stdlib-only and cannot import ``_safe_walk``, so the prune is duplicated here.
    A nested ``.git`` (dir OR gitlink file) marks a foreign project."""
    dirnames[:] = [
        d for d in dirnames
        if not os.path.exists(os.path.join(dirpath, d, ".git"))
    ]


def iter_py_files(root: str, exclude: set[str] | None = None) -> list[str]:
    exclude = exclude or DEFAULT_EXCLUDE
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude]
        _skip_nested_repos(dirpath, dirnames)
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(os.path.join(dirpath, fn))
    return out


def _snippet(src: str, lineno: int) -> str:
    lines = src.splitlines()
    return lines[lineno - 1].rstrip() if 1 <= lineno <= len(lines) else ""


_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
_LOGGER_ROOTS = {"log", "logger", "logging", "_log", "_logger"}


def _is_logger_call(n: ast.AST) -> bool:
    """A logger call requires BOTH a logging method name AND a logger-plausible
    receiver. Receiver-blind matching cleared real broad swallows whose body was
    ``response.error()`` / ``db.collection.info()`` / ``QMessageBox.warning()``
    — a non-logger ``.error()`` is not logging, and a correctness scanner that
    reads such a swallow as clean is the false-negative it exists to prevent.
    Accepted receivers: a root ``ast.Name`` in _LOGGER_ROOTS (``logger.error``,
    ``logging.warning``, ``_log.debug``) or ``self.log`` / ``self.logger``
    chains."""
    if not isinstance(n, ast.Call):
        return False
    f = n.func
    if not isinstance(f, ast.Attribute):
        return False
    if f.attr.lower() not in _LOG_METHODS:
        return False
    # Walk the attribute chain to its root Name, remembering the first hop.
    cur: ast.AST = f
    first_hop: str | None = None
    while isinstance(cur, ast.Attribute):
        first_hop = cur.attr
        cur = cur.value
    # Inline `logging.getLogger(__name__).exception(...)` / `getLogger(...).error(...)`
    # and the snake_case `structlog.get_logger().error(...)` / `get_logger(...)...`
    # idiom (structlog/loguru, common in adopter code): the chain root is the
    # getLogger()/get_logger() CALL, not a Name. Such a receiver IS a logger.
    if isinstance(cur, ast.Call):
        callee = cur.func
        if isinstance(callee, ast.Name) and callee.id in ("getLogger", "get_logger"):
            return True
        if isinstance(callee, ast.Attribute) and callee.attr in ("getLogger", "get_logger"):
            return True
    if not isinstance(cur, ast.Name):
        return False
    if cur.id.lower() in _LOGGER_ROOTS:
        return True
    # self.logger.error(...) / self.log.info(...): root is `self`, the attribute
    # directly under self (the LAST hop walked) must be log/logger.
    if cur.id == "self":
        return (first_hop or "").lower() in {"log", "logger", "_log", "_logger"}
    return False


def _handler_type(h: ast.ExceptHandler) -> str:
    if h.type is None:
        return "<bare>"
    if isinstance(h.type, ast.Name):
        return h.type.id
    if isinstance(h.type, ast.Attribute):
        return h.type.attr
    return ast.unparse(h.type) if hasattr(ast, "unparse") else "<expr>"


def _handler_is_broad(h: ast.ExceptHandler) -> bool:
    """True if the handler catches Exception/BaseException — directly, or as a
    member of a tuple ``except (ValueError, Exception):``. A bare ``except:`` is
    also broad. The prior gate compared the unparsed handler string against a
    name set, so a tuple containing Exception was silently missed (latent — 0
    live non-pass instances, but a real all-clear risk). The bare-pass tuple
    sub-case was already caught by _body_is_pass."""
    if h.type is None:
        return True
    members = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
    return any(isinstance(m, ast.Name) and m.id in ("Exception", "BaseException")
               for m in members)


def _body_is_pass(body: list[ast.stmt]) -> bool:
    return len(body) == 0 or (len(body) == 1 and isinstance(body[0], ast.Pass))


def _iter_handler_scope(body: list[ast.stmt]):
    """Yield every node in the handler's OWN lexical scope.

    Descends through control flow (``if`` / ``for`` / ``while`` / ``with`` /
    ``try``) but NOT into nested ``def`` / ``async def`` / ``class`` / ``lambda``
    bodies. A ``raise`` or logger call inside an uninvoked nested function does
    NOT re-raise or report the handled exception, so a plain ``ast.walk``
    (which descends into nested scopes) would clear a genuine swallow — a false
    negative.
    """
    for stmt in body:
        yield from _iter_node_same_scope(stmt)


def _iter_node_same_scope(node: ast.AST):
    yield node
    if isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
    ):
        return  # a nested scope — its raises/logs are not the handler's
    for child in ast.iter_child_nodes(node):
        yield from _iter_node_same_scope(child)


def _contains_raise(body: list[ast.stmt]) -> bool:
    return any(isinstance(n, ast.Raise) for n in _iter_handler_scope(body))


def _contains_log(body: list[ast.stmt]) -> tuple[bool, bool]:
    has_log = has_print = False
    for n in _iter_handler_scope(body):
        if _is_logger_call(n):
            has_log = True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print":
            has_print = True
    return has_log, has_print


def scan_file(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        src = f.read()
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError as e:
        return [{"file": path, "lineno": getattr(e, "lineno", None),
                 "kind": "syntax_error", "message": str(e)}]

    findings: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        handler_name = _handler_type(node)
        lineno = getattr(node, "lineno", 0) or 0
        body = node.body

        if _body_is_pass(body):
            findings.append({
                "file": path, "lineno": lineno,
                "kind": "swallowed_silent",
                "handler": handler_name,
                "line": _snippet(src, lineno),
                "message": f"except {handler_name}: pass -- exception silently swallowed",
            })
            continue

        has_raise = _contains_raise(body)
        has_log, has_print = _contains_log(body)

        if _handler_is_broad(node):
            if not has_raise and not has_log:
                kind = "swallowed_broad_no_log" if not has_print else "swallowed_broad_print_only"
                findings.append({
                    "file": path, "lineno": lineno,
                    "kind": kind,
                    "handler": handler_name,
                    "line": _snippet(src, lineno),
                    "message": f"except {handler_name}: broad catch without re-raise or logging",
                })
    return findings


def scan_repo(root: str, exclude: set[str] | None = None) -> dict[str, Any]:
    files = iter_py_files(root, exclude)
    files = [
        f for f in files
        if not any(
            os.path.relpath(f, root).replace("\\", "/").startswith(prefix)
            for prefix in EXEMPT_PREFIXES
        )
    ]
    all_findings: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for p in files:
        try:
            all_findings.extend(scan_file(p))
        except OSError as e:
            # A dangling symlink, a permission-denied file, or a file deleted
            # mid-walk must not abort the whole scan — skip it, record it, keep going.
            # The path is its own key; the OS reason stands alone, so the
            # record never carries a repr'd path (DEF-799).
            skipped.append({"file": p, "error": e.strerror or type(e).__name__})
    return {
        "root": os.path.abspath(root),
        "files_scanned": len(files),
        "count": len(all_findings),
        "skipped": skipped,
        "by_kind": _group_by_kind(all_findings),
        "findings": all_findings,
    }


def _group_by_kind(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        k = f.get("kind", "unknown")
        counts[k] = counts.get(k, 0) + 1
    return counts


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Scan Python files for swallowed exceptions")
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="reports/scan_exceptions.json")
    ap.add_argument("--exclude", nargs="*", default=[])
    args = ap.parse_args()

    exclude = DEFAULT_EXCLUDE | set(args.exclude)
    report = scan_repo(args.root, exclude)

    # Guard against flat `--out` paths (no directory
    # component). ``os.path.dirname("flat.json")`` returns ``""``
    # and ``os.makedirs("")`` raises ``FileNotFoundError``.
    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    silent = report["by_kind"].get("swallowed_silent", 0)
    broad = report["by_kind"].get("swallowed_broad_no_log", 0)
    print(f"Scanned {report['files_scanned']} files: {report['count']} findings "
          f"({silent} silent, {broad} broad-no-log)")
    return 1 if report["count"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
