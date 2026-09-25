#!/usr/bin/env python3
"""Detect large Python files and produce AST outlines with extraction hints."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from collections import defaultdict
from dataclasses import asdict, dataclass
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
DEFAULT_THRESHOLD = 750

# Skip earn-the-gate fixtures so live `espalier scan godfiles`
# runs are not polluted by the scanner's synthetic over-threshold test
# data. The fixture is intentionally > 750 lines; without exemption it
# would appear in the live above_threshold count every release.
EXEMPT_PREFIXES: tuple[str, ...] = ("tests/fixtures/",)


def _filter_exempt(rows: list[FileRow]) -> list[FileRow]:
    """Drop rows under any EXEMPT_PREFIXES path (POSIX-normalized)."""
    return [
        r for r in rows
        if not any(r.path.replace("\\", "/").startswith(p) for p in EXEMPT_PREFIXES)
    ]


@dataclass(frozen=True, slots=True)
class FileRow:
    path: str
    loc: int
    sha256: str
    top_level_functions: int
    top_level_classes: int


@dataclass(frozen=True, slots=True)
class FunctionInfo:
    name: str
    start: int
    end: int
    args: list[str]
    doc: str


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _first_line(s: str | None) -> str:
    return s.strip().splitlines()[0].strip() if s else ""


def _expr_name(e: ast.expr) -> str:
    try:
        return ast.unparse(e)
    except (ValueError, TypeError):
        return e.__class__.__name__  # Fallback for unsupported AST nodes


def _group_key(name: str) -> str:
    if name.startswith("__") and name.endswith("__"):
        return "__dunder__"
    base = name.lstrip("_")
    if not base:
        return "_private"
    return base.split("_", 1)[0] if "_" in base else base


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


def outline_file(path: str) -> dict[str, Any]:
    """Produce a structured AST outline of a Python file."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            src = f.read()
    except OSError as e:
        # The path is its own key; the OS reason stands alone (DEF-799).
        return {"file": path, "error": "unreadable", "detail": e.strerror or type(e).__name__,
                "classes": [], "functions": [], "clusters": []}
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError:
        return {"file": path, "error": "syntax_error", "classes": [], "functions": [], "clusters": []}

    classes: list[dict[str, Any]] = []
    functions: list[FunctionInfo] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(FunctionInfo(
                        name=item.name,
                        start=getattr(item, "lineno", 0),
                        end=getattr(item, "end_lineno", 0),
                        args=[a.arg for a in item.args.args],
                        doc=_first_line(ast.get_docstring(item)),
                    ))
            classes.append({
                "name": node.name,
                "start": getattr(node, "lineno", 0),
                "end": getattr(node, "end_lineno", 0),
                "bases": [_expr_name(b) for b in node.bases],
                "method_count": len(methods),
                "methods": [asdict(m) for m in methods],
                "doc": _first_line(ast.get_docstring(node)),
            })
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(FunctionInfo(
                name=node.name,
                start=getattr(node, "lineno", 0),
                end=getattr(node, "end_lineno", 0),
                args=[a.arg for a in node.args.args],
                doc=_first_line(ast.get_docstring(node)),
            ))

    # Cluster functions by naming prefix — suggests extraction boundaries
    clusters = _cluster_functions(functions)

    return {
        "file": path,
        "loc": len(src.splitlines()),
        "classes": classes,
        "functions": [asdict(f) for f in functions],
        "clusters": clusters,
    }


def _cluster_functions(funcs: list[FunctionInfo]) -> list[dict[str, Any]]:
    groups: dict[str, list[FunctionInfo]] = defaultdict(list)
    for f in funcs:
        groups[_group_key(f.name)].append(f)

    out: list[dict[str, Any]] = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda x: x.start)
        out.append({
            "group_key": key,
            "count": len(members),
            "start": members[0].start,
            "end": members[-1].end,
            "symbols": [m.name for m in members],
        })
    out.sort(key=lambda x: (-x["count"], x["start"]))
    return out


def build_report(root: str, exclude: set[str] | None = None) -> list[FileRow]:
    rows: list[FileRow] = []
    for p in iter_py_files(root, exclude):
        try:
            with open(p, "rb") as f:
                b = f.read()
        except OSError:
            # Dangling symlink / unreadable file: a size report omits it
            # rather than aborting the whole scan.
            continue
        try:
            s = b.decode("utf-8")
        except UnicodeDecodeError:
            s = b.decode("utf-8", errors="replace")
        try:
            tree = ast.parse(s)
        except SyntaxError:
            tree = ast.Module(body=[], type_ignores=[])
        funcs = sum(1 for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        clss = sum(1 for n in tree.body if isinstance(n, ast.ClassDef))
        rows.append(FileRow(
            path=os.path.relpath(p, root),
            loc=len(s.splitlines()),
            sha256=_sha256(b),
            top_level_functions=funcs,
            top_level_classes=clss,
        ))
    rows.sort(key=lambda r: r.loc, reverse=True)
    return rows


def render_godfiles_md(rows: list[FileRow], threshold: int = DEFAULT_THRESHOLD) -> str:
    big = [r for r in rows if r.loc >= threshold]
    lines = [
        "# Large File Report",
        "",
        f"Threshold: {threshold} LOC | Files above threshold: {len(big)} / {len(rows)}",
        "",
    ]
    if big:
        lines.extend([
            "| File | LOC | Functions | Classes | Extraction hint |",
            "|---|---:|---:|---:|---|",
        ])
        for r in big:
            hint = "review for split" if r.loc >= threshold * 2 else "monitor"
            lines.append(f"| `{r.path}` | {r.loc} | {r.top_level_functions} | {r.top_level_classes} | {hint} |")
    else:
        lines.append("No files above threshold. Codebase is well-factored.")
    return "\n".join(lines) + "\n"


def scan_repo(root: str, threshold: int = DEFAULT_THRESHOLD, exclude: set[str] | None = None,
              rows: list[FileRow] | None = None) -> dict[str, Any]:
    if rows is None:
        rows = _filter_exempt(build_report(root, exclude))
    big = [r for r in rows if r.loc >= threshold]
    outlines = {}
    for r in big[:10]:
        full_path = os.path.join(root, r.path)
        outlines[r.path] = outline_file(full_path)
    return {
        "root": os.path.abspath(root),
        "threshold": threshold,
        "total_files": len(rows),
        "above_threshold": len(big),
        "files": [asdict(r) for r in rows[:50]],
        "outlines": outlines,
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Report large Python files with AST outlines")
    ap.add_argument("--root", default=".")
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    ap.add_argument("--out", default="reports/godfiles_report.json")
    ap.add_argument("--md", default="reports/godfiles_report.md")
    args = ap.parse_args()

    # Build + EXEMPT-filter the rows once, then feed BOTH the JSON report
    # (via scan_repo's `rows=`) and the Markdown render, so the two can no
    # longer drift on the ``above_threshold`` count.
    rows = _filter_exempt(build_report(args.root))
    report = scan_repo(args.root, args.threshold, rows=rows)

    # Guard against flat `--out` / `--md` paths (no
    # directory component). ``os.path.dirname("flat.json")`` returns
    # ``""`` and ``os.makedirs("")`` raises ``FileNotFoundError``.
    # godfiles writes BOTH a JSON and a Markdown report; each needs
    # its own guard since adopters may override one but not the
    # other.
    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    md_dir = os.path.dirname(args.md)
    if md_dir:
        os.makedirs(md_dir, exist_ok=True)
    with open(args.md, "w", encoding="utf-8") as f:
        f.write(render_godfiles_md(rows, args.threshold))

    big = report["above_threshold"]
    print(f"Scanned {report['total_files']} files: {big} above {args.threshold} LOC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
