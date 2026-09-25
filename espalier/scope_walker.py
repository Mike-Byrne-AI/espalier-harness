"""Walk the codebase for references to a symbol or path.

Symbol can be a path string (``.claude/agents/``), a Python identifier
(``_has_plan``), or a module name (``espalier.cli``). The walker
returns structured references the operator can use to expand a pack's
``Scope (in)`` or acknowledge the gap explicitly.

Two reference kinds:

- ``string`` — symbol appears in source as code (high confidence).
- ``comment`` — the match is inside a comment line (low confidence;
  reported separately so the operator can ignore "mention" matches that
  don't represent real coupling).

The scan prefers ripgrep (fixed-string mode) when available and falls
back to a pure-Python file walk; tests force the fallback so the contract
is testable without a system ripgrep.

Identifier-like symbols (a plain Python name such as ``main`` or
``_run_main``) are matched on WORD BOUNDARIES so ``main`` does not match
``maintain`` / ``domain`` / ``docs-maintainer``. Path- and dotted-module
symbols (anything containing ``/`` or ``.``) stay substring-matched, since
word boundaries don't apply cleanly to them.

The boundary is purely lexical (a Python word boundary): it is
token-equality, NOT definition-site-aware. Two consequences the operator
should read as intended, not bugs: (1) a hyphen IS a word boundary, so
symbol ``main`` DOES match ``pre-main-hook`` / ``x-main-y`` (a hyphenated
mention is a real textual reference); (2) the bare symbol greps EVERY
module, so a ``cli.py::main`` token stripped to ``main`` by ``pack_manifest``
surfaces every same-named ``main`` across the tree as a candidate scope
gap. The walker reports textual coupling for the operator to triage with
``--accept-scope-gap``; it is a pre-flight signal, not a definition
resolver.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from espalier._safe_walk import safe_rglob
from typing import Iterable, TypedDict


class Reference(TypedDict):
    file: str
    line: int
    context: str
    confidence: str  # "high" | "low"
    kind: str  # "string" | "comment"


EXCLUDED_DIRS: frozenset[str] = frozenset({
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".espalier",
    ".espalier-state",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
    "reports",
    "results",
    "__MACOSX",
})
# Path.suffix walk-gate: which files the surface walker descends into. This is a
# purpose-scoped SIBLING of surface_impact._PATH_SUFFIXES (an un-dotted token
# recognizer), proofs.TEXT_SUFFIXES (a text-read gate) and pack_manifest's inline
# tuple — the same *idea* (relevant file extensions) under three different
# mechanisms and breadths. Do NOT collapse them to one canon: a breadth change
# appropriate for one silently mis-shifts another.
# sister-site: ok purpose-scoped: Path.suffix walk-gate; sibling of surface_impact._PATH_SUFFIXES / proofs.TEXT_SUFFIXES (see Wave-3 note)
INCLUDED_EXTS: frozenset[str] = frozenset({
    ".py", ".md", ".json", ".toml", ".yml", ".yaml", ".txt", ".cfg",
})

_CONTEXT_LIMIT = 200

# A "plain identifier" symbol (a Python name) is matched on word boundaries so
# `main` does not match `maintain`/`domain`; path- and dotted-module symbols
# stay substring-matched. See module docstring.
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _is_identifier(symbol: str) -> bool:
    return bool(_IDENTIFIER_RE.fullmatch(symbol))


def _matcher_for(symbol: str):
    """Return a predicate ``line -> bool`` for ``symbol`` — word-boundary regex
    for a plain identifier, plain substring otherwise. The same rule both the
    single- and multi-symbol Python arms use, so their outputs agree."""
    if _is_identifier(symbol):
        rx = re.compile(r"\b" + re.escape(symbol) + r"\b")
        return lambda line: rx.search(line) is not None
    return lambda line: symbol in line


def walk_references(
    repo_root: Path,
    symbol: str,
    *,
    use_ripgrep: bool = True,
) -> list[Reference]:
    """Find every textual reference to ``symbol`` under ``repo_root``.

    Args:
        repo_root: directory to walk.
        symbol: literal string to look for (paths, identifiers).
        use_ripgrep: if False, force the pure-Python fallback. Used by
            tests so the same code path runs everywhere.

    Identifier symbols are matched on word boundaries (``main`` not
    ``maintain``); path/dotted symbols are matched as substrings.

    Returns one :class:`Reference` per match. Each match marks comments
    as ``confidence="low"`` and code as ``confidence="high"``.
    """
    word_boundary = _is_identifier(symbol)
    if use_ripgrep:
        refs = _walk_with_ripgrep(repo_root, symbol, word_boundary)
        if refs is not None:
            return refs
    return _walk_with_python(repo_root, symbol, word_boundary)


def walk_references_multi(
    repo_root: Path,
    symbols: Iterable[str],
    *,
    use_ripgrep: bool = True,
) -> dict[str, list[Reference]]:
    """Batched :func:`walk_references`: find references to MANY symbols in a
    SINGLE tree pass instead of one walk (or one ``rg`` subprocess) per symbol.

    Returns ``{symbol: [Reference, ...]}``. For any given symbol the result is
    identical to ``walk_references(repo_root, symbol, ...)`` — same matcher
    (word-boundary for identifiers, substring for paths) and same (file, line)
    ordering — the only change is that the tree is read once, not once per symbol
    (the O(symbols x files) -> O(files) fix). Duplicate symbol names collapse to
    one walk; a caller's own per-symbol loop over its symbol list is unchanged.
    """
    ordered = list(dict.fromkeys(symbols))
    if not ordered:
        return {}
    if use_ripgrep:
        result = _walk_multi_with_ripgrep(repo_root, ordered)
        if result is not None:
            return result
    return _walk_multi_with_python(repo_root, ordered)


def _walk_with_ripgrep(
    repo_root: Path, symbol: str, word_boundary: bool,
) -> list[Reference] | None:
    """Try ripgrep. Returns None if rg is unavailable or errored.

    ``word_boundary`` adds ``--word-regexp`` so an identifier matches as a
    whole word — parity with the Python arm's ``\\b…\\b`` matcher.
    """
    rg_args = [
        "rg", "--no-heading", "-n", "--fixed-strings", "--null",
        # Without --hidden --no-ignore, ripgrep skips
        # dotfiles/dotdirs (.claude/, .github/) and .gitignore'd files
        # that _walk_with_python walks — the two arms diverge. The
        # post-filter below already applies
        # _is_excluded (drops .git/, __pycache__, …) and the
        # INCLUDED_EXTS suffix gate, so --no-ignore cannot leak .git/
        # internals; the flags only ADD the refs the Python arm reports.
        "--hidden", "--no-ignore",
    ]
    if word_boundary:
        rg_args.append("--word-regexp")
    rg_args += ["--", symbol, str(repo_root)]
    try:
        proc = subprocess.run(
            rg_args,
            capture_output=True,
            # errors="replace" (not strict) — rg streams matched FILE
            # CONTENTS, which can hold non-UTF-8 bytes (e.g. a latin-1 source
            # file); degrade them to U+FFFD rather than crash /scope-check's rg
            # arm (a UnicodeDecodeError escapes the FileNotFoundError/
            # SubprocessError except below).
            text=True, encoding="utf-8", errors="replace",
            check=False,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if proc.returncode not in (0, 1):
        return None
    refs: list[Reference] = []
    for line in proc.stdout.splitlines():
        # NUL separator between path and rest, so paths with colons are OK.
        if "\x00" not in line:
            continue
        path_part, rest = line.split("\x00", 1)
        m = re.match(r"^(\d+):(.*)$", rest)
        if not m:
            continue
        file_path = Path(path_part)
        if file_path.is_symlink():
            continue  # symlink-skip parity with the Python fallback
        try:
            rel = file_path.relative_to(repo_root)
        except ValueError:
            continue
        if _is_excluded(rel):
            continue
        if file_path.suffix not in INCLUDED_EXTS:
            continue
        line_no = int(m.group(1))
        context = m.group(2).rstrip()
        refs.append(_make_reference(str(rel), line_no, context))
    # rg searches files in parallel, so its cross-file output order is
    # NONDETERMINISTIC. The Python arm walks sorted(safe_rglob(...)), so without
    # this the two backends can return the same references in different orders
    # for the same input -- and the same backend can differ between runs.
    return sorted(refs, key=_reference_order)


def _reference_order(ref: Reference) -> tuple[str, int]:
    """Deterministic (file, line) ordering key.

    Single owner for the ordering promised by ``walk_references_multi``'s
    docstring ("same (file, line) ordering" as the per-symbol walk). Both rg
    arms sort through this so the batched, per-symbol and Python paths agree.
    """
    return (ref["file"], ref["line"])


def _iter_scannable_lines(repo_root: Path):
    """Yield ``(rel_posix, line_no, line)`` for every scannable line in the tree,
    walking + reading each file ONCE. Shared by the single- and multi-symbol
    Python matchers so a multi-symbol scope-check reads the tree once, not once
    per symbol. Applies the same file gate as elsewhere (symlink-skip, excluded
    dirs, INCLUDED_EXTS)."""
    for path in sorted(safe_rglob(repo_root)):
        if not _is_safe_walk_target(path):
            continue
        try:
            rel = path.relative_to(repo_root)
        except ValueError:
            continue
        if _is_excluded(rel):
            continue
        if path.suffix not in INCLUDED_EXTS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel_str = str(rel)
        for line_no, line in enumerate(text.splitlines(), start=1):
            yield rel_str, line_no, line


def _walk_with_python(
    repo_root: Path, symbol: str, word_boundary: bool,
) -> list[Reference]:
    """Pure-Python fallback when ripgrep is unavailable.

    ``word_boundary`` matches an identifier as a whole word (``\\b…\\b``) —
    parity with the ripgrep arm's ``--word-regexp``.
    """
    matcher = re.compile(r"\b" + re.escape(symbol) + r"\b") if word_boundary else None
    refs: list[Reference] = []
    for rel_str, line_no, line in _iter_scannable_lines(repo_root):
        if matcher.search(line) if matcher else symbol in line:
            refs.append(_make_reference(rel_str, line_no, line))
    return refs


def _walk_multi_with_python(
    repo_root: Path, symbols: list[str],
) -> dict[str, list[Reference]]:
    """Multi-symbol Python arm: one tree walk, every symbol matched per line."""
    matchers = {s: _matcher_for(s) for s in symbols}
    out: dict[str, list[Reference]] = {s: [] for s in symbols}
    for rel_str, line_no, line in _iter_scannable_lines(repo_root):
        for s in symbols:
            if matchers[s](line):
                out[s].append(_make_reference(rel_str, line_no, line))
    return out


def _rg_multi(
    repo_root: Path, symbols: list[str], word_boundary: bool,
) -> list[tuple[str, int, str]] | None:
    """One ripgrep call over MANY fixed-string patterns → the parsed
    ``(rel, line_no, context)`` matches (union over patterns), or None if rg is
    unavailable/errored. Same file gate + parsing as :func:`_walk_with_ripgrep`."""
    rg_args = [
        "rg", "--no-heading", "-n", "--fixed-strings", "--null",
        "--hidden", "--no-ignore",
    ]
    if word_boundary:
        rg_args.append("--word-regexp")
    for symbol in symbols:
        rg_args += ["-e", symbol]
    rg_args += ["--", str(repo_root)]
    try:
        proc = subprocess.run(
            rg_args,
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            check=False,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if proc.returncode not in (0, 1):
        return None
    results: list[tuple[str, int, str]] = []
    for line in proc.stdout.splitlines():
        if "\x00" not in line:
            continue
        path_part, rest = line.split("\x00", 1)
        m = re.match(r"^(\d+):(.*)$", rest)
        if not m:
            continue
        file_path = Path(path_part)
        if file_path.is_symlink():
            continue  # symlink-skip parity with the Python fallback
        try:
            rel = file_path.relative_to(repo_root)
        except ValueError:
            continue
        if _is_excluded(rel):
            continue
        if file_path.suffix not in INCLUDED_EXTS:
            continue
        results.append((str(rel), int(m.group(1)), m.group(2).rstrip()))
    return results


def _walk_multi_with_ripgrep(
    repo_root: Path, symbols: list[str],
) -> dict[str, list[Reference]] | None:
    """Multi-symbol ripgrep arm: at most TWO rg calls (identifiers with
    ``--word-regexp``, paths without) instead of one per symbol. Each matched
    line is attributed to every symbol in its group that actually matches it (the
    same per-symbol predicate the Python arm uses), so per-symbol output equals
    the single-symbol walk. Returns None (→ Python fallback) if rg is unavailable."""
    out: dict[str, list[Reference]] = {s: [] for s in symbols}
    for word_boundary, group in (
        (True, [s for s in symbols if _is_identifier(s)]),
        (False, [s for s in symbols if not _is_identifier(s)]),
    ):
        if not group:
            continue
        matches = _rg_multi(repo_root, group, word_boundary)
        if matches is None:
            return None
        matchers = {s: _matcher_for(s) for s in group}
        for rel, line_no, context in matches:
            for s in group:
                if matchers[s](context):
                    out[s].append(_make_reference(rel, line_no, context))
    # Same reason as the single-symbol arm: rg's parallel output order is not
    # stable, and this function's docstring promises per-symbol results
    # IDENTICAL to walk_references -- ordering included. Measured: without this
    # the batched and per-symbol rg arms returned the same two references in
    # opposite orders, and the parity gate flaked rather than failed honestly.
    return {s: sorted(refs, key=_reference_order) for s, refs in out.items()}


def _is_safe_walk_target(path: Path) -> bool:
    """Skip non-files AND symlinks.

    A symlink under ``repo_root`` can target a file *outside* ``repo_root``
    (e.g., ``repo/link.py -> /etc/passwd``). The walker would then
    ``read_text`` the target and embed its contents in the printed
    scope-check report. Symlink-skip is fail-closed — operators wanting
    symlink-traversal-aware scope analysis can run with a deliberate
    pre-pass that resolves symlinks under a controlled root.
    """
    return path.is_file() and not path.is_symlink()


def _is_excluded(rel: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in rel.parts)


def _make_reference(file: str, line_no: int, context: str) -> Reference:
    """Normalise context + classify as code/comment."""
    stripped = context.lstrip()
    is_comment = stripped.startswith("#") or stripped.startswith("//")
    norm_file = file.replace("\\", "/")
    return {
        "file": norm_file,
        "line": line_no,
        "context": context.strip()[:_CONTEXT_LIMIT],
        "confidence": "low" if is_comment else "high",
        "kind": "comment" if is_comment else "string",
    }


def classify_references(
    refs: Iterable[Reference],
    scope_in: Iterable[str],
) -> dict[str, list[Reference]]:
    """Split references into in-scope and out-of-scope.

    A reference is in-scope when its file path matches an entry in
    ``scope_in`` directly OR is under a directory entry (``scope_in``
    item ending with ``/``). Directory match also fires for items that
    look like prefixes without a trailing slash.
    """
    scope_files: set[str] = set()
    scope_prefixes: list[str] = []
    for entry in scope_in:
        norm = entry.replace("\\", "/").strip()
        if not norm:
            continue
        if norm.endswith("/"):
            scope_prefixes.append(norm)
            continue
        scope_files.add(norm)
        # Also treat the entry as a directory prefix unless it has a
        # known file extension. This means ``scope_in=["src"]`` matches
        # ``src/a.py`` even without an explicit trailing slash, while
        # ``scope_in=["foo.py"]`` does NOT match ``foo.py.bak``.
        if "." not in Path(norm).name:
            scope_prefixes.append(norm + "/")

    in_scope: list[Reference] = []
    out_of_scope: list[Reference] = []
    for ref in refs:
        rfile = ref["file"]
        matched = (
            rfile in scope_files
            or any(rfile.startswith(p) for p in scope_prefixes)
        )
        if matched:
            in_scope.append(ref)
        else:
            out_of_scope.append(ref)
    return {"in_scope": in_scope, "out_of_scope": out_of_scope}
