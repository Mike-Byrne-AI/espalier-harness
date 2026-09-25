#!/usr/bin/env python3
"""Find print() calls that should probably be logging."""
from __future__ import annotations

import ast
import json
import os
from typing import Any

# NOTE: "cc" is a bare BASENAME, so os.walk prunes EVERY directory named cc at
# any depth -- the top-level blueprints cc/, tools/cc/, and its
# espalier/_vendor/cc/ byte-mirror. Deliberate: those governed trees carry ~200
# legitimate hook/CLI print()s each that would otherwise flood `espalier scan`.
# Caveat (latent, adopter-only): it also prunes an adopter package coincidentally
# named cc/, and --exclude only ADDs to this set (no override). If that ever
# bites, scope to the three harness cc path-suffixes explicitly, not a repo-root
# prefix (tools/cc & _vendor/cc are NOT at repo root).
DEFAULT_EXCLUDE = {".git", ".venv", "venv", "__pycache__", ".pytest_cache",
                   "node_modules", "dist", "build", ".mypy_cache", ".ruff_cache",
                   "cc"}

# Skip fixtures so live `espalier scan prints` runs are not polluted by
# the scanner's own positive-case test data.
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


def scan_file(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        src = f.read()
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError:
        return []

    lines = src.splitlines()
    findings: list[dict[str, Any]] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print":
            lineno = getattr(n, "lineno", 0) or 0
            findings.append({
                "file": path,
                "lineno": lineno,
                "col": getattr(n, "col_offset", None),
                "line": lines[lineno - 1].rstrip() if 1 <= lineno <= len(lines) else "",
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
            # The path is its own key; the OS reason stands alone, so the
            # record never carries a repr'd path (DEF-799).
            skipped.append({"file": p, "error": e.strerror or type(e).__name__})
    return {
        "root": os.path.abspath(root),
        "files_scanned": len(files),
        "count": len(all_findings),
        "skipped": skipped,
        "findings": all_findings,
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Scan Python files for print() calls")
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="reports/scan_prints.json")
    args = ap.parse_args()

    report = scan_repo(args.root)

    # Guard against flat `--out` paths (no directory component).
    # ``os.path.dirname("flat.json")`` returns ``""`` and
    # ``os.makedirs("")`` raises ``FileNotFoundError``.
    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Scanned {report['files_scanned']} files: {report['count']} print() calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
