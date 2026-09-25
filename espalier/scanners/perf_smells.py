#!/usr/bin/env python3
"""Scan for performance-sensitive patterns. Extensible per project type."""
from __future__ import annotations

import io
import json
import os
import re
import tokenize
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

# Skip earn-the-gate fixtures so live `espalier scan perf_smells`
# runs are not polluted by the scanner's positive-case test data.
EXEMPT_PREFIXES: tuple[str, ...] = ("tests/fixtures/",)

# Pattern sets by project type
ML_PATTERNS: list[tuple[str, str]] = [
    ("device_transfer", r"\.(to|cuda|cpu)\s*\("),
    ("tokenize_call", r"\b(tokenizer|tok)\s*\("),
    ("model_forward", r"\bmodel\s*\("),
    ("no_grad_block", r"torch\.(no_grad|inference_mode)\s*\("),
    ("autocast_block", r"torch\.cuda\.amp\.autocast\s*\("),
    ("load_model", r"from_pretrained\s*\("),
]

GENERAL_PATTERNS: list[tuple[str, str]] = [
    ("subprocess_shell", r"subprocess\.(run|call|Popen)\s*\([^)]*shell\s*=\s*True"),
    ("global_import_star", r"^from\s+\S+\s+import\s+\*"),
    # `nested_loop_pattern` is structurally inert — the `\n` requires a
    # newline, but scan_file searches line-by-line, so the regex never matches.
    # Unlike its API-only sister `n_plus_one`, it lives in GENERAL_PATTERNS (every
    # `espalier scan` evaluates it) yet still counts zero. Retained as
    # documentation of the smell shape and pinned dead in
    # test_scanner_perf_smells.py so it can't masquerade as live coverage;
    # activating it needs multi-line scan support (out of scope — perf_smells is
    # an informational report).
    ("nested_loop_pattern", r"for\s+.*:\s*\n\s+for\s+"),
    ("bare_open", r"(?<!with\s)open\s*\("),
]

API_PATTERNS: list[tuple[str, str]] = [
    ("sync_request", r"requests\.(get|post|put|delete|patch)\s*\("),
    # `n_plus_one` is a multi-line pattern (the `\n`) — like its
    # GENERAL sister `nested_loop_pattern`, it is structurally inert under
    # scan_file's line-by-line search, and it is additionally API-only
    # (select_patterns(api=True)); `espalier scan` never passes --api.
    # Retained as documentation of the smell shape; pinned dead in
    # test_scanner_perf_smells.py. Activating it needs multi-line scan
    # support — out of scope: perf_smells is an informational report.
    ("n_plus_one", r"for\s+.*:\s*\n.*\.(query|filter|get)\s*\("),
]


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


def _bare_open_linenos(src: str) -> set[int]:
    """Line numbers of real ``open(...)`` calls that are NOT attribute
    accesses (``os.open``, ``x.open``) and NOT inside a string/comment.

    The old per-line regex fired on the call name inside string literals,
    comments, ``Popen(``, ``reopen``, ``os.open`` — measured ~95% false
    positives on a live repo scan. Tokenizing skips string/comment spans for
    free and a one-token lookbehind rejects a dotted receiver, a ``with``
    keyword predecessor, AND a ``def`` predecessor (``def open(...)`` is a
    function DEFINITION named ``open``, not a call to the builtin).
    ``with open(...)`` is intentionally EXEMPT — the regex
    this replaces carried a with-lookbehind that exempted it too (a
    context-managed open is the idiomatic correct form, not the smell), and the
    existing ``shape_open_with_context_manager`` negative fixture pins that
    exemption.
    """
    out: set[int] = set()
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return out  # unparseable source: no false positives, report nothing
    skip = {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
            tokenize.DEDENT, tokenize.COMMENT, tokenize.ENCODING}
    prev: tokenize.TokenInfo | None = None
    for i, tok in enumerate(toks):
        if tok.type == tokenize.NAME and tok.string == "open":
            dotted = prev is not None and prev.type == tokenize.OP and prev.string == "."
            after_with = (
                prev is not None and prev.type == tokenize.NAME and prev.string == "with"
            )
            after_def = (
                prev is not None and prev.type == tokenize.NAME and prev.string == "def"
            )
            j = i + 1
            while j < len(toks) and toks[j].type in skip:
                j += 1
            is_call = j < len(toks) and toks[j].type == tokenize.OP and toks[j].string == "("
            if is_call and not dotted and not after_with and not after_def:
                out.add(tok.start[0])
        if tok.type not in skip:
            prev = tok
    return out


def scan_file(path: str, patterns: list[tuple[str, str]]) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        src = f.read()
    lines = src.splitlines()
    hits: dict[str, list[dict[str, Any]]] = {k: [] for k, _ in patterns}
    # `bare_open` is token-aware (skips strings/comments/dotted receivers and
    # `with open()`); the rest stay per-line regex.
    bare_open_lines = _bare_open_linenos(src) if "bare_open" in hits else set()
    for i, line in enumerate(lines, start=1):
        for k, pat in patterns:
            if k == "bare_open":
                if i in bare_open_lines:
                    hits[k].append({"lineno": i, "line": line.rstrip()})
                continue
            if re.search(pat, line):
                hits[k].append({"lineno": i, "line": line.rstrip()})
    counts = {k: len(v) for k, v in hits.items()}
    return {"file": path, "total_hits": sum(counts.values()), "counts": counts, "hits": hits}


def scan_repo(root: str, patterns: list[tuple[str, str]] | None = None,
              exclude: set[str] | None = None) -> dict[str, Any]:
    patterns = patterns or GENERAL_PATTERNS
    files = iter_py_files(root, exclude)
    files = [
        f for f in files
        if not any(
            os.path.relpath(f, root).replace("\\", "/").startswith(prefix)
            for prefix in EXEMPT_PREFIXES
        )
    ]
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for p in files:
        try:
            results.append(scan_file(p, patterns))
        except OSError as e:
            # The path is its own key; the OS reason stands alone, so the
            # record never carries a repr'd path (DEF-799).
            skipped.append({"file": p, "error": e.strerror or type(e).__name__})
    results.sort(key=lambda x: x["total_hits"], reverse=True)
    hotspots = [r for r in results if r["total_hits"] > 0]
    return {
        "root": os.path.abspath(root),
        "patterns": [k for k, _ in patterns],
        "files_scanned": len(files),
        "files_with_hits": len(hotspots),
        "skipped": skipped,
        "results": results[:30],
    }


def select_patterns(ml: bool = False, api: bool = False) -> list[tuple[str, str]]:
    patterns = list(GENERAL_PATTERNS)
    if ml:
        patterns.extend(ML_PATTERNS)
    if api:
        patterns.extend(API_PATTERNS)
    return patterns


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Scan for performance-sensitive code patterns")
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="reports/scan_perf.json")
    ap.add_argument("--ml", action="store_true", help="Include ML/GPU patterns")
    ap.add_argument("--api", action="store_true", help="Include API patterns")
    args = ap.parse_args()

    patterns = select_patterns(ml=args.ml, api=args.api)
    report = scan_repo(args.root, patterns)

    # Guard against flat `--out` paths (no directory component).
    # ``os.path.dirname("flat.json")`` returns ``""`` and
    # ``os.makedirs("")`` raises ``FileNotFoundError``.
    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Scanned {report['files_scanned']} files: {report['files_with_hits']} with hits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
