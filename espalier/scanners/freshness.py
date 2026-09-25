#!/usr/bin/env python3
"""Document freshness scanner — canonical types, regex, scan function.

Per the scanner-canon invariant this module owns the
`Fragment` and `FragmentState` dataclasses, the policy enum, the
`_FRAGMENT_RE` regex, the thresholds, and the `scan_repo` entry-point.
The public-facing `espalier/freshness.py` is a thin wrapper importing
from here; no duplication.

Critical correctness invariants:

- BC-038: fragment markers inside YAML frontmatter or fenced code
  blocks are not detected. The `bound` charclass is tightened to
  `[A-Za-z0-9_./*:,-]+` to refuse shell metachars.
- BC-039: the manifest lives at ``.espalier/freshness.json`` and is
  COMMITTED (not gitignored) — this scanner reads it from the repo
  root, not from a per-machine location.
- BC-040: the scan compares the manifest-stored bound array against
  the current fragment's bound list. Any divergence forces state
  to ``unpinned`` regardless of the recorded SHA.
- BC-041: ``schema_version`` mismatch raises ``FreshnessError``.
- BC-042: bound entries beginning with ``-`` are rejected (git
  pathspec safety; the bound array goes straight into ``git log``
  positional arguments).
- BC-044: the policy vocabulary is closed. Unknown policy yields
  state ``critical`` with the message ``unknown policy``.
- One ``git log --name-only`` subprocess per distinct pin SHA walks the
  union of that pin's bound paths since it; per-fragment drift is computed
  in-memory by path-set intersection. A bound that names a symbol
  (``path::symbol``) then narrows its path's count to the commits that
  changed the symbol's own lines -- ``git show HEAD:path`` for the span, one
  ``git log -L`` per such entry -- and only when the path's file-level count
  is non-zero (``_bound_drift``).
"""
from __future__ import annotations

import ast
import fnmatch
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _safe_glob(root, pattern: str):
    """Symlink-safe Path.glob (inline). Handles a recursive ``prefix/**/suffix``
    pattern via _safe_rglob; non-``**`` patterns fall through to Path.glob
    (non-recursive, never descends a symlink). Mirrors
    espalier/_safe_walk.py::safe_glob — used here because the glob pattern is a
    runtime VARIABLE the AST recurrence-scanner cannot see (FAILURE_MODES §2.8)."""
    if "**" not in pattern:
        yield from root.glob(pattern)
        return
    prefix, sep, suffix = pattern.partition("/**/")
    if sep:
        yield from _safe_rglob((root / prefix) if prefix else root, suffix or "*")
        return
    # bare "**", "**/x", or "prefix/**" anchored at root (no '/**/' separator).
    # A BARE trailing "**" (tail empty) includes the anchor dir itself, matching
    # Path.glob; an explicit "**/x" (e.g. "**/*") does NOT, matching Path.glob("**/*").
    # Gate on `tail`, not `leaf` (both collapse to "*"). The inline copy calls
    # _safe_rglob (scanners cannot import _safe_walk).
    head, _, tail = pattern.rpartition("**")
    walk_root = (root / head.strip("/")) if head.strip("/") else root
    leaf = tail.lstrip("/") or "*"
    if not tail and walk_root.is_dir():
        yield walk_root
    yield from _safe_rglob(walk_root, leaf)


STALE_THRESHOLD_COMMITS: int = 5
STALE_THRESHOLD_DAYS: int = 14
# §C22: the WARNING BAND on the day axis. Past STALE_THRESHOLD_DAYS a fragment
# goes `stale` (the CI freshness job warns and does NOT block); only past this
# does it go `critical` (blocking). Before this existed the day axis stepped
# fresh -> critical with no intermediate, so a cohort of fragments sharing one
# pin date took CI from all-green to blocking-every-touching-PR on a single day
# with no prior signal. The band is what makes a bulk re-pin recoverable instead
# of a cliff: you get STALE_THRESHOLD_DAYS days of warnings first.
CRITICAL_THRESHOLD_DAYS: int = 28

SCHEMA_VERSION: int = 1

MANIFEST_REL_PATH: str = ".espalier/freshness.json"

_ALLOWED_POLICIES: frozenset[str] = frozenset({
    "verify-on-touch",
    "weekly",
    "numeric-contract",
})

FRAGMENT_SURFACE_ALLOWLIST: tuple[str, ...] = (
    "README.md",
    "CHANGELOG.md",
    _MEMORY_FILENAME,
    "CLAUDE.md",
    "docs/**/*.md",
    ".claude/**/*.md",
)
FRAGMENT_SURFACE_DENYLIST: tuple[str, ...] = (
    "examples/**",
    "docs/external/**",
    "task-packs/**",
    ".espalier/**",
)

_FRAGMENT_OPEN_RE = re.compile(r"<!--\s*espalier:fragment\b")
_FRAGMENT_CLOSE_TOKEN = "-->"

_FIELD_RE = re.compile(
    r"\b(id|bound|policy|bound_closure)\s*=\s*([A-Za-z0-9_./*:,\-]+)"
)

_BOUND_CALL_OR_SUBSCRIPT_RE = re.compile(r"[ \t]*[(\[][^\n]*[)\]]?\s*$")


def _normalize_bound(bound: str) -> str:
    """Normalize a bound-field entry for comparison.

    Scanner discovery + manifest writer + audit consumer all route
    through this function so divergence is impossible. Strips
    ``path::fn(arg)``, ``path::fn ()``, and ``path::fn[idx]`` shapes in
    addition to a trailing literal ``()``.
    """
    bound = bound.strip()
    while "//" in bound:
        bound = bound.replace("//", "/")
    if "::" in bound:
        path, sep, symbol = bound.rpartition("::")
        symbol = _BOUND_CALL_OR_SUBSCRIPT_RE.sub("", symbol).strip()
        bound = f"{path}{sep}{symbol}".strip()
    elif bound.endswith("()"):
        bound = bound[:-2]
    return bound


@dataclass(frozen=True, slots=True)
class Fragment:
    """A doc-side claim that binds to code paths and declares a policy.

    Parsed from ``<!-- espalier:fragment id=... bound=... policy=... -->``
    markers in the repository's documentation surface. The ``bound``
    list captures one or more ``path[::symbol]`` references.
    """

    id: str
    bound: tuple[str, ...]
    policy: str
    source_path: str = ""
    source_line: int = 0
    bound_closure: bool = False


@dataclass(frozen=True, slots=True)
class FragmentState:
    """Computed freshness state for a fragment at a point in time."""

    fragment: Fragment
    state: str
    last_verified_sha: str = ""
    manifest_bound: tuple[str, ...] = field(default_factory=tuple)
    commits_since: int = 0
    days_since: int = 0
    message: str = ""
    #: Bound paths carrying uncommitted changes -- drift that has not landed
    #: (``_dirty_bound``); empty on a clean checkout, so CI never sees one.
    dirty_paths: tuple[str, ...] = field(default_factory=tuple)


class FreshnessError(Exception):
    """Raised when the manifest is malformed or schema-incompatible."""


def parse_fragment_markers(
    content: str,
    *,
    source_path: str = "",
) -> list[Fragment]:
    """Extract fragment markers from a doc string.

    Skips markers inside YAML frontmatter regions (`---...---` at top
    of document) and fenced code blocks (``` ``` ``` ``). Raises
    ``FreshnessError`` on duplicate ids or invalid field values.
    """
    fragments: list[Fragment] = []
    seen_ids: set[str] = set()

    lines = content.splitlines()
    in_yaml = False
    yaml_closed = False
    in_fence = False
    i = 0
    line_count = len(lines)

    while i < line_count:
        line = lines[i]
        stripped = line.strip()

        if not yaml_closed and i == 0 and stripped == "---":
            in_yaml = True
            yaml_closed = False
            i += 1
            continue
        if in_yaml and stripped == "---":
            in_yaml = False
            yaml_closed = True
            i += 1
            continue
        if in_yaml:
            i += 1
            continue

        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            i += 1
            continue
        if in_fence:
            i += 1
            continue

        if not _FRAGMENT_OPEN_RE.search(line):
            i += 1
            continue

        buf_parts: list[str] = []
        start_line = i + 1
        j = i
        while j < line_count:
            buf_parts.append(lines[j])
            if _FRAGMENT_CLOSE_TOKEN in lines[j]:
                break
            j += 1
        else:
            raise FreshnessError(
                f"{source_path}:{start_line}: unterminated fragment marker"
            )

        buf = " ".join(buf_parts)
        fields_found = dict(_FIELD_RE.findall(buf))

        missing = [k for k in ("id", "bound", "policy") if k not in fields_found]
        if missing:
            # Enumerate the closed policy vocabulary (BC-044) inline when policy
            # is the missing field, so an adopter authoring a fragment marker can
            # recover without the (un-deployed) reference docs — do NOT point at a
            # doc init does not ship (that would recreate the dangling-ref class).
            hint = ""
            if "policy" in missing:
                hint = " (policy must be one of: numeric-contract, verify-on-touch, weekly)"
            raise FreshnessError(
                f"{source_path}:{start_line}: fragment missing fields: "
                f"{', '.join(missing)}{hint}"
            )

        frag_id = fields_found["id"]
        if frag_id in seen_ids:
            raise FreshnessError(
                f"{source_path}:{start_line}: duplicate fragment id "
                f"{frag_id!r}"
            )
        seen_ids.add(frag_id)

        bound_raw = fields_found["bound"]
        bound = tuple(_normalize_bound(b) for b in bound_raw.split(",") if b)
        for b in bound:
            if b.startswith("-"):
                raise FreshnessError(
                    f"{source_path}:{start_line}: bound entry {b!r} "
                    f"begins with '-' (rejected per BC-042 git "
                    f"pathspec safety)"
                )

        policy = fields_found["policy"]

        closure_raw = fields_found.get("bound_closure", "false").lower()
        if closure_raw not in ("true", "false"):
            raise FreshnessError(
                f"{source_path}:{start_line}: bound_closure must be "
                f"true|false, got {closure_raw!r}"
            )
        bound_closure = closure_raw == "true"

        fragments.append(Fragment(
            id=frag_id,
            bound=bound,
            policy=policy,
            source_path=source_path,
            source_line=start_line,
            bound_closure=bound_closure,
        ))

        i = j + 1

    return fragments


def discover_fragments(repo_root: Path) -> list[Fragment]:
    """Walk the configured fragment surface and parse all markers.

    Iterates ``FRAGMENT_SURFACE_ALLOWLIST`` via ``Path.glob`` and
    skips any path whose POSIX-relative form matches a pattern in
    ``FRAGMENT_SURFACE_DENYLIST`` (via ``fnmatch.fnmatch``).
    """
    seen_ids: dict[str, str] = {}
    fragments: list[Fragment] = []
    seen_paths: set[str] = set()
    for pattern in FRAGMENT_SURFACE_ALLOWLIST:
        for doc_path in sorted(_safe_glob(repo_root, pattern)):
            try:
                rel = str(doc_path.relative_to(repo_root)).replace("\\", "/")
            except ValueError:
                continue
            if rel in seen_paths:
                continue
            if any(fnmatch.fnmatch(rel, deny)
                   for deny in FRAGMENT_SURFACE_DENYLIST):
                continue
            seen_paths.add(rel)
            try:
                text = doc_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            file_frags = parse_fragment_markers(text, source_path=rel)
            for f in file_frags:
                if f.id in seen_ids:
                    raise FreshnessError(
                        f"duplicate fragment id {f.id!r} "
                        f"(first in {seen_ids[f.id]}, second in {rel})"
                    )
                seen_ids[f.id] = rel
                fragments.append(f)
    return fragments


def _load_manifest(repo_root: Path) -> dict[str, Any]:
    manifest_path = repo_root / MANIFEST_REL_PATH
    if not manifest_path.is_file():
        return {"schema_version": SCHEMA_VERSION, "fragments": {}}
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # The path plain and the OS reason from strerror, never str(exc), whose
        # repr'd path doubles every backslash on Windows (DEF-799); a decode
        # error has no strerror and is named by its class.
        reason = (exc.strerror if isinstance(exc, OSError) else None) or type(exc).__name__
        raise FreshnessError(f"cannot read manifest {manifest_path}: {reason}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FreshnessError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise FreshnessError("manifest root must be an object")
    schema = data.get("schema_version")
    if schema != SCHEMA_VERSION:
        raise FreshnessError(
            f"manifest schema_version={schema!r}; this scanner "
            f"requires {SCHEMA_VERSION}. Run `espalier freshness check` "
            f"after upgrading the harness, or re-pin fragments under "
            f"the new schema."
        )
    if not isinstance(data.get("fragments"), dict):
        raise FreshnessError("manifest 'fragments' must be an object")
    return data


def _bound_to_paths(bound: tuple[str, ...]) -> list[str]:
    """Strip ``::symbol`` suffix; return UNIQUE filesystem paths only.

    Dedup is load-bearing: a fragment binding N symbols in the SAME file
    (e.g. ``mod.py::a``, ``mod.py::b``) would otherwise return that path N
    times, and ``scan_repo``'s ``sum(sha_commits.get(p, 0) for p in
    bound_paths)`` would count that file's drift N times — inflating a
    ``stale`` fragment into a false ``critical`` that trips the exit-2 CI
    freshness gate (a false positive — the cardinal sin). ``dict.fromkeys``
    dedups while preserving first-seen order. The other caller (the
    per-pin grouping in ``scan_repo``) feeds a ``set`` and is unaffected.
    """
    paths: list[str] = []
    for b in bound:
        path = b.split("::", 1)[0]
        if path and not path.startswith("-"):
            paths.append(path)
    return list(dict.fromkeys(paths))


def _resolve_bound_closure(
    bound_entry: str, repo_root: Path
) -> set[str]:
    """Return the closure of repo-relative files that import the bound symbol.

    For Python paths, walks every ``*.py`` file under ``repo_root``
    via ``ast`` and collects those that ``import`` or ``from ... import``
    the bound module -- absolute, relative (``from . import target``,
    ``from ..target import fn``), or as a name from its parent package
    (``from pkg import target``). For non-Python paths, returns just the path.

    Closure widens ``--changed-files`` intersection for fragments that
    set ``bound_closure=true``: a PR that modifies a caller of the
    bound symbol counts as touching the fragment's surface even when
    the bound file itself is unchanged.
    """
    import ast as _ast
    bound = _normalize_bound(bound_entry)
    base_path = bound.split("::", 1)[0]
    closure: set[str] = {base_path}
    if not base_path.endswith(".py"):
        return closure
    module_name = base_path[:-3].replace("/", ".")

    def _names_bound_module(candidate: str) -> bool:
        return candidate == module_name or candidate.startswith(module_name + ".")

    def _import_from_targets(node: _ast.ImportFrom, importer_pkg: str) -> list[str]:
        """Every dotted module a ``from ... import ...`` statement can name
        (DEF-410m). The ``from`` module is resolved through ``node.level``
        against the importing file's package -- ``from . import x`` /
        ``from .x import y`` / ``from ..x import y`` -- and each imported NAME
        is appended to it, because ``from pkg import target`` names the module
        ``pkg.target`` and whether ``target`` is a module or a symbol is
        undecidable without importing it; both readings count. At the repo root
        the package is empty, so ``from . import top`` names ``top`` itself. A
        level that climbs above the tree resolves to nothing, and a star import
        contributes only its ``from`` module (``from pkg import *`` does not
        name ``pkg.target``; ``from pkg.target import *`` does). Two whole
        import spellings were false negatives before this: every relative
        import, and the bound module imported as a name from its parent
        package."""
        if node.level:
            parts = importer_pkg.split(".") if importer_pkg else []
            drop = node.level - 1
            if drop > len(parts):
                return []  # climbs above the tree; not resolvable here
            base = ".".join(parts[: len(parts) - drop] if drop else parts)
            if node.module:
                mod = f"{base}.{node.module}" if base else node.module
            else:
                mod = base
        else:
            mod = node.module or ""
        names = [a.name for a in node.names if a.name != "*"]
        if not mod:
            return names  # `from . import top` at the repo root names `top`
        return [mod, *(f"{mod}.{name}" for name in names)]

    for py_file in _safe_rglob(repo_root, "*.py"):
        try:
            rel = str(py_file.relative_to(repo_root)).replace("\\", "/")
        except ValueError:
            continue
        if rel == base_path or rel in closure:
            continue
        try:
            tree = _ast.parse(py_file.read_text(encoding="utf-8"))
        except (SyntaxError, OSError, UnicodeDecodeError, ValueError):
            continue
        # The importer's package, for relative imports: a module's package is its
        # directory, and so is an ``__init__.py``'s (it IS the package).
        importer_pkg = rel.rpartition("/")[0].replace("/", ".")
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                if any(_names_bound_module(a.name) for a in node.names):
                    closure.add(rel)
                    break
            elif isinstance(node, _ast.ImportFrom):
                if any(
                    _names_bound_module(t)
                    for t in _import_from_targets(node, importer_pkg)
                ):
                    closure.add(rel)
                    break
    return closure


def _git_log_name_only(
    repo_root: Path, since_sha: str, paths: list[str]
) -> dict[str, int]:
    """Return per-path commit-count from ``since_sha..HEAD``.

    Uses a single ``git log --name-only`` subprocess; intersects in
    memory per fragment (caller's responsibility).
    """
    if not since_sha or not paths:
        return {}
    cmd = [
        "git", "-C", str(repo_root),
        "log", "--name-only", "--pretty=format:%H", f"{since_sha}..HEAD",
        "--",
    ] + paths
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return {}
    if result.returncode != 0:
        return {}
    per_path: dict[str, int] = {p: 0 for p in paths}
    current_paths: set[str] = set()

    def _flush() -> None:
        for p in current_paths:
            if p in per_path:
                per_path[p] += 1

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            _flush()
            current_paths = set()
            continue
        if len(line) in (40, 64) and all(c in "0123456789abcdef" for c in line):
            if current_paths:
                _flush()
            current_paths = set()
            continue
        current_paths.add(line)
    if current_paths:
        _flush()
    return per_path


def _symbol_span(repo_root: Path, path: str, symbol: str) -> tuple[int, int] | None:
    """The 1-based line span of a top-level symbol in ``path`` at HEAD, or
    ``None`` when the symbol cannot be placed.

    Read from ``git show HEAD:<path>`` rather than the working tree: ``git log
    -L`` applies a line range to the newest revision it walks, and a dirty
    tree would hand it lines that no longer line up. Only a top-level ``def``,
    ``async def``, ``class`` or assignment is placed, decorators included, so
    the span is the symbol's own lines -- a function's whole body, a tuple's
    every row -- and nothing before or after it; a column-zero mention of the
    name in a docstring above cannot capture the region, and the repo's diff
    driver plays no part. A dotted or ``::``-nested symbol, a symbol the file
    no longer defines, a path absent at HEAD, a file that does not parse or is
    not Python returns ``None`` and the caller keeps the file-level count,
    the conservative side.
    """
    if not symbol or "." in symbol or "::" in symbol or not path.endswith(".py"):
        return None
    try:
        shown = subprocess.run(
            ["git", "-C", str(repo_root), "show", f"HEAD:{path}"],
            capture_output=True, text=True, encoding="utf-8", check=False, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    if shown.returncode != 0:
        return None
    try:
        tree = ast.parse(shown.stdout)
    except (SyntaxError, ValueError):
        return None
    for node in tree.body:
        names: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        if symbol not in names:
            continue
        start = node.lineno
        decorators = getattr(node, "decorator_list", [])
        if decorators:
            start = min(start, min(d.lineno for d in decorators))
        return start, node.end_lineno or node.lineno
    return None


#: Leads every commit line ``_git_log_symbol_commits`` asks git for, so a
#: patch line that happens to be a bare hex token (a fixture digest inside the
#: region) can never be read as a commit.
_COMMIT_SENTINEL = "\x1e"


def _git_log_symbol_commits(
    repo_root: Path, since_sha: str, path: str, span: tuple[int, int]
) -> set[str] | None:
    """The commits in ``since_sha..HEAD`` that changed the symbol's lines, or
    ``None`` when git cannot say (a span past the file's end at some
    revision, a path absent at some commit, a timeout): the caller then keeps
    the file count.
    """
    start, end = span
    cmd = [
        "git", "-C", str(repo_root),
        "log", f"--format={_COMMIT_SENTINEL}%H",
        "-L", f"{start},{end}:{path}", f"{since_sha}..HEAD",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", check=False, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    if result.returncode != 0:
        return None
    found: set[str] = set()
    # split on the newline only: ``str.splitlines`` treats the record
    # separator as a line boundary and would eat the sentinel it looks for
    for line in result.stdout.split("\n"):
        if line.startswith(_COMMIT_SENTINEL):
            sha = line[len(_COMMIT_SENTINEL):].strip()
            if sha:
                found.add(sha)
    return found


def _bound_drift(
    repo_root: Path,
    since_sha: str,
    bound: tuple[str, ...],
    bound_paths: list[str],
    path_commits: dict[str, int],
) -> int:
    """Commits since the pin that touched the fragment's bound, summed per path.

    A path bound whole counts every commit to it. A path bound only through
    ``::symbol`` entries counts the union of the commits that changed those
    symbols' own lines at HEAD (``_symbol_span``), so a commit that touched two
    bound symbols at once counts once and a commit to the rest of the file
    counts not at all.
    Measured 2026-09-09: two fragments bound to constants in one test file had
    been re-pinned twice in eight days at unchanged values because every lane
    touched that file elsewhere, and a third, bound to a hook-wiring table,
    read stale on three commits that never touched the table. The symbol walk
    runs only for a path whose file-level count is non-zero, so a scan of a
    quiet tree stays at one subprocess per pin, and any entry the walk cannot
    place keeps the whole path's file-level count.
    """
    symbols_by_path: dict[str, list[str]] = {}
    whole_paths: set[str] = set()
    for entry in bound:
        path, sep, symbol = entry.partition("::")
        if not path or path.startswith("-"):
            continue
        if sep and symbol:
            symbols_by_path.setdefault(path, []).append(symbol)
        else:
            whole_paths.add(path)
    total = 0
    for path in bound_paths:
        file_count = path_commits.get(path, 0)
        symbols = symbols_by_path.get(path)
        if file_count == 0 or path in whole_paths or not symbols:
            total += file_count
            continue
        touched: set[str] = set()
        placed = True
        for symbol in symbols:
            span = _symbol_span(repo_root, path, symbol)
            found = (
                _git_log_symbol_commits(repo_root, since_sha, path, span)
                if span else None
            )
            if found is None:
                placed = False
                break
            touched |= found
        total += len(touched) if placed else file_count
    return total


def _git_status_dirty(repo_root: Path, paths: list[str]) -> dict[str, str]:
    """``repo-relative path -> XY status`` for every entry ``git status``
    reports under ``paths``: modified, staged, untracked, deleted, renamed
    (``--untracked-files=all`` so a new file inside a directory bound is
    listed by name; ``-z`` so a path with a space arrives unquoted). One
    subprocess for the union of every fragment's bound paths. Any git error
    yields ``{}``, the same side ``_git_log_name_only`` falls to: a scan that
    cannot ask git cannot claim drift."""
    if not paths:
        return {}
    cmd = [
        "git", "-C", str(repo_root),
        "status", "--porcelain=v1", "-z", "--untracked-files=all", "--",
    ] + paths
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", check=False, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return {}
    if result.returncode != 0:
        return {}
    out: dict[str, str] = {}
    fields = result.stdout.split("\0")
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        out[path] = code
        if code[0] in "RC" and i < len(fields) and fields[i]:
            # A rename or copy carries its other path in the next field; a
            # file moved out of (or into) a bound directory is a change to it.
            out[fields[i]] = code
            i += 1
    return out


_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def _git_diff_old_ranges(repo_root: Path, path: str) -> list[tuple[int, int]] | None:
    """The HEAD-side line ranges ``git diff -U0 HEAD`` reports changed in the
    working tree for ``path``, or ``None`` when git cannot say. A pure
    insertion after old line ``n`` is read as touching ``n`` and ``n + 1``,
    so an insertion inside a symbol's span, or at either of its edges, counts
    as a change to the symbol (the conservative side)."""
    cmd = ["git", "-C", str(repo_root), "diff", "-U0", "--no-color", "HEAD", "--", path]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", check=False, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    if result.returncode != 0:
        return None
    ranges: list[tuple[int, int]] = []
    for line in result.stdout.splitlines():
        m = _HUNK_HEADER_RE.match(line)
        if not m:
            continue
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) is not None else 1
        ranges.append((start, start + 1) if count == 0 else (start, start + count - 1))
    return ranges


def _dirty_bound(
    repo_root: Path,
    bound: tuple[str, ...],
    bound_paths: list[str],
    status: dict[str, str],
) -> list[str]:
    """The paths of ``bound`` carrying uncommitted changes, in bound order.

    Drift is counted in commits since the pin (``_bound_drift``), so a bound
    edited but not yet committed read ``fresh`` while the pinned claim could
    already be false of the working tree -- measured 2026-09-06: a count
    fragment pinned at 47 beside a HEAD where the answer was 46. An
    uncommitted change is drift that has not landed. A path bound whole is
    dirty on any status entry at or under it (an untracked file inside a
    directory bound included). A path bound only through ``::symbol`` entries
    is narrowed the way the commit walk is: a tracked modification is dirty
    only when a changed HEAD-side range meets a bound symbol's span at HEAD
    (``_symbol_span``); an untracked, added, deleted or renamed entry, a
    range git cannot report, or a span that cannot be placed keeps the whole
    path, the conservative side.
    """
    symbols_by_path: dict[str, list[str]] = {}
    whole_paths: set[str] = set()
    for entry in bound:
        path, sep, symbol = entry.partition("::")
        if not path or path.startswith("-"):
            continue
        if sep and symbol:
            symbols_by_path.setdefault(path, []).append(symbol)
        else:
            whole_paths.add(path)
    dirty: list[str] = []
    for path in bound_paths:
        norm = path.rstrip("/")
        hits = {p: code for p, code in status.items() if p == norm or p.startswith(norm + "/")}
        if not hits:
            continue
        symbols = symbols_by_path.get(path)
        if (
            path in whole_paths
            or not symbols
            or set(hits) != {norm}
            or hits[norm] not in (" M", "M ", "MM")
        ):
            dirty.append(path)
            continue
        ranges = _git_diff_old_ranges(repo_root, norm)
        if ranges is None:
            dirty.append(path)
            continue
        for symbol in symbols:
            span = _symbol_span(repo_root, norm, symbol)
            if span is None:
                dirty.append(path)
                break
            start, end = span
            if any(max(start, a) <= min(end, b) for a, b in ranges):
                dirty.append(path)
                break
    return dirty


def dirty_bound_paths(repo_root: Path, bound: tuple[str, ...]) -> list[str]:
    """The paths of ``bound`` carrying uncommitted changes -- the pin-time
    twin of the scan's rule (``_dirty_bound``), for ``pin_fragment``."""
    paths = _bound_to_paths(bound)
    return _dirty_bound(repo_root, bound, paths, _git_status_dirty(repo_root, paths))


def bound_commits_since(repo_root: Path, since_sha: str, bound: tuple[str, ...]) -> int:
    """Commits from ``since_sha`` to HEAD that touched ``bound`` -- the
    single-fragment form of the scan's drift count (``_bound_drift`` over one
    ``git log --name-only``), for ``pin_fragment``'s carried-literal rule.
    ``0`` where git cannot answer (an unknown SHA, no git): the scan reads such
    a pin ``fresh`` for the same reason, and the pin stays consistent with it."""
    paths = _bound_to_paths(bound)
    return _bound_drift(
        repo_root, since_sha, bound, paths, _git_log_name_only(repo_root, since_sha, paths),
    )


def _manifest_fragments_at_head(repo_root: Path) -> dict[str, Any] | None:
    """The manifest's ``fragments`` as committed at HEAD, or ``None`` when the
    manifest is not at HEAD (``init`` gitignores ``.espalier/`` on an adopter
    tree, so there it never is; the harness's own tree commits it). A real
    pin rewrites ``last_verified_at`` and ``_sha``; an entry whose literal
    differs from HEAD's beside unchanged provenance was edited by hand, and
    ``scan_repo`` reads it stale -- a check that stands down, and says so
    through ``hand_edit_check_note``, wherever this returns ``None``."""
    cmd = ["git", "-C", str(repo_root), "show", f"HEAD:{MANIFEST_REL_PATH}"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", check=False, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return None
    frags = data.get("fragments") if isinstance(data, dict) else None
    return frags if isinstance(frags, dict) else {}


def hand_edit_check_note(repo_root: Path) -> str | None:
    """One advisory line for ``check`` when the hand-edited-literal check is
    standing down: the on-disk manifest carries an ``expected_value`` and the
    manifest is not at HEAD. ``None`` when the check is on, or when no entry
    carries a literal (nothing to check). Never raises."""
    try:
        entries = _load_manifest(repo_root).get("fragments", {})
    except FreshnessError:
        return None
    if not isinstance(entries, dict) or not any(
        isinstance(e, dict) and "expected_value" in e for e in entries.values()
    ):
        return None
    if _manifest_fragments_at_head(repo_root) is not None:
        return None
    return (
        f"{MANIFEST_REL_PATH} is not tracked at HEAD, so an expected_value "
        f"edited by hand cannot be told from a pinned one here, and the "
        f"pin-time refusal stands down with it: a re-pin given no "
        f"--expected-value carries the on-disk number, so restate it when "
        f"you mean to change it"
    )


def _literal_edited_by_hand(entry: dict[str, Any], head_entry: Any) -> tuple[bool, Any]:
    """``(edited, head_value)``: the on-disk entry carries an ``expected_value``
    that differs from the committed one while its pin fields are unchanged."""
    if not isinstance(head_entry, dict) or "expected_value" not in entry:
        return False, None
    if (
        entry.get("last_verified_sha") != head_entry.get("last_verified_sha")
        or entry.get("last_verified_at") != head_entry.get("last_verified_at")
    ):
        return False, None
    head_value = head_entry.get("expected_value")
    return entry.get("expected_value") != head_value, head_value


def _days_since(iso_timestamp: str) -> int:
    if not iso_timestamp:
        return 0
    try:
        ts = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return max(0, (now - ts).days)


# §C22 cohort advisory. Fires when a single pin date dominates the manifest —
# the shape a bulk re-pin creates. Advisory only (see `cohort_warning`).
COHORT_WARN_FRACTION: float = 0.5
COHORT_MIN_FRAGMENTS: int = 3


def pin_cohorts(repo_root: Path) -> dict[str, int]:
    """Map ``last_verified_at`` DATE -> how many fragments carry it.

    §C22: a bulk re-pin puts every fragment on one date, so the whole set ages
    as one cohort and crosses each threshold on the same day. The warning band
    makes that recoverable; this makes it *visible at the moment it is created*
    rather than N days later. Returns ``{}`` when the manifest is absent or
    unreadable — a missing manifest is already reported as ``unpinned`` by the
    scan itself, and this advisory must never be the thing that raises.
    """
    manifest = repo_root / MANIFEST_REL_PATH
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        # Valid JSON that is not an object (`[]`, `"x"`, `3`) would make the
        # .get() below raise AttributeError, which the except above does not
        # catch — a fail-open in an advisory that must never raise.
        return {}
    fragments = data.get("fragments")
    if not isinstance(fragments, dict):
        return {}
    counts: dict[str, int] = {}
    for entry in fragments.values():
        if not isinstance(entry, dict):
            continue
        pinned = entry.get("last_verified_at")
        if not isinstance(pinned, str) or len(pinned) < 10:
            continue
        day = pinned[:10]
        counts[day] = counts.get(day, 0) + 1
    return counts


def cohort_warning(repo_root: Path) -> str | None:
    """Advisory string when one pin date dominates, else ``None``.

    Deliberately advisory: it fired on the tree it was written against (every
    fragment shared one pin date on 2026-08-04), so making it blocking would red
    the suite on the very condition it exists to report; it is silent on a
    cluster under ``COHORT_WARN_FRACTION`` of the manifest. It is the signal that the next bulk re-pin re-created
    the cohort — see the class note in ``CRITICAL_THRESHOLD_DAYS``.
    """
    counts = pin_cohorts(repo_root)
    total = sum(counts.values())
    if total < COHORT_MIN_FRAGMENTS:
        return None
    day, biggest = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    # Half is a cohort (measured 2026-09-10: a re-pin of seven of fourteen
    # sat exactly on the old strict-majority boundary and was silent, while
    # the seven cross both thresholds as one block).
    if biggest / total < COHORT_WARN_FRACTION:
        return None
    return (
        f"cohort clock: {biggest} of {total} fragments share one pin date "
        f"({day}), so they cross every threshold together. They go `stale` on "
        f"day {STALE_THRESHOLD_DAYS + 1} and block on day "
        f"{CRITICAL_THRESHOLD_DAYS + 1}. Stagger the next re-pin instead of "
        f"re-pinning them all at once."
    )


def _classify(
    *,
    policy_known: bool,
    manifest_match: bool,
    has_pin: bool,
    commits: int,
    days: int,
    dirty: bool,
) -> str:
    if not policy_known:
        return "critical"
    if not has_pin:
        return "unpinned"
    if not manifest_match:
        return "unpinned"
    # ``dirty``: the bound has uncommitted changes, or the literal was edited
    # by hand -- drift that has not landed. It withholds ``fresh`` and never
    # promotes to ``critical``; the commit and day axes below decide that.
    if commits == 0 and days <= STALE_THRESHOLD_DAYS and not dirty:
        return "fresh"
    # Commit axis: heavy drift against the bound source blocks immediately —
    # the band below is deliberately NOT applied here, because many commits
    # touching a bound path is evidence the claim is wrong NOW, not ageing.
    if commits > STALE_THRESHOLD_COMMITS:
        return "critical"
    # Day axis (§C22): warn for a band, then block. `stale` never blocks CI.
    if days > CRITICAL_THRESHOLD_DAYS:
        return "critical"
    return "stale"


def scan_repo(repo_root: Path) -> list[FragmentState]:
    """Walk fragments under ``repo_root`` and return their freshness state.

    One ``git log --name-only`` subprocess per distinct pin SHA across the
    union of that pin's bound paths, then per-fragment state in-memory; a
    symbol-bound path whose file drifted adds one ``git log -L`` per symbol
    (``_bound_drift``).
    """
    manifest = _load_manifest(repo_root)
    fragments = discover_fragments(repo_root)
    manifest_entries: dict[str, dict[str, Any]] = manifest.get("fragments", {})

    # Count each fragment's drift from ITS OWN pin. A single shared
    # ``oldest_sha..HEAD`` window is wrong whenever fragments carry different
    # pins: it attributes commits that PREDATE a fragment's pin to that
    # fragment, so a recently-pinned, genuinely-fresh fragment is over-counted
    # into ``stale``/``critical`` and trips the exit-2 freshness gate (a false
    # positive — the cardinal sin). Pick ``since = the fragment's own pin``
    # instead: group bound paths by pin sha and run ONE ``git log`` per
    # DISTINCT pin (bounded by #distinct-pins, not #fragments; a single-pin
    # manifest stays a single subprocess). Each distinct pin's walk is
    # independent, so the oldest pin's drift is also captured correctly — this
    # closes the original false-negative AND avoids the false-positive.
    paths_by_sha: dict[str, set[str]] = {}
    for frag_id, entry in manifest_entries.items():
        sha = entry.get("last_verified_sha")
        if not sha:
            continue
        bound_arr = entry.get("bound", [])
        if isinstance(bound_arr, list):
            paths_by_sha.setdefault(sha, set()).update(
                _bound_to_paths(tuple(bound_arr))
            )

    per_sha_path_commits: dict[str, dict[str, int]] = {}
    for sha, paths in paths_by_sha.items():
        if paths:
            per_sha_path_commits[sha] = _git_log_name_only(
                repo_root, sha, sorted(paths)
            )

    # Uncommitted changes to any pinned fragment's bound: ONE ``git status``
    # over the union of the bound paths, then per fragment in memory (a
    # symbol-bound path adds one ``git diff -U0`` only when it is dirty).
    all_bound_paths: set[str] = set()
    for paths in paths_by_sha.values():
        all_bound_paths.update(paths)
    dirty_status = _git_status_dirty(repo_root, sorted(all_bound_paths))
    # The committed manifest, read once, only when an entry carries a literal;
    # ``None`` (not at HEAD) switches the hand-edit check off for every entry.
    fragments_at_head = (
        _manifest_fragments_at_head(repo_root)
        if any(isinstance(e, dict) and "expected_value" in e for e in manifest_entries.values())
        else {}
    ) or {}

    states: list[FragmentState] = []
    for frag in fragments:
        policy_known = frag.policy in _ALLOWED_POLICIES
        entry = manifest_entries.get(frag.id)
        has_pin = entry is not None and bool(entry.get("last_verified_sha"))

        manifest_bound_raw = (entry or {}).get("bound", [])
        if isinstance(manifest_bound_raw, list):
            manifest_bound: tuple[str, ...] = tuple(manifest_bound_raw)
        else:
            manifest_bound = ()

        manifest_bound_norm = tuple(_normalize_bound(b) for b in manifest_bound)
        fragment_bound_norm = tuple(_normalize_bound(b) for b in frag.bound)
        manifest_match = manifest_bound_norm == fragment_bound_norm

        last_sha = (entry or {}).get("last_verified_sha", "") or ""
        last_at = (entry or {}).get("last_verified_at", "") or ""

        bound_paths = _bound_to_paths(frag.bound)
        # Drift is counted from this fragment's OWN pin window, not a
        # shared global window (see scan_repo's per-distinct-pin block above),
        # and a symbol-bound path narrows to its symbols' own commits.
        sha_commits = per_sha_path_commits.get(last_sha, {})
        commits = (
            _bound_drift(repo_root, last_sha, frag.bound, bound_paths, sha_commits)
            if has_pin else 0
        )
        days = _days_since(last_at) if has_pin else 0
        dirty_here = (
            _dirty_bound(repo_root, frag.bound, bound_paths, dirty_status)
            if has_pin and manifest_match else []
        )
        hand_edited, head_value = (
            _literal_edited_by_hand(entry, fragments_at_head.get(frag.id))
            if has_pin and isinstance(entry, dict) else (False, None)
        )

        state = _classify(
            policy_known=policy_known,
            manifest_match=manifest_match,
            has_pin=has_pin,
            commits=commits,
            days=days,
            dirty=bool(dirty_here) or hand_edited,
        )

        message = ""
        if not policy_known:
            message = f"unknown policy: {frag.policy!r}"
        elif entry is not None and not manifest_match:
            state = "critical"
            message = (
                f"fragment-id rebinding attempt: marker at "
                f"{frag.source_path}:{frag.source_line} claims "
                f"bound={list(frag.bound)} but manifest entry pins "
                f"bound={list(manifest_bound)}"
            )
        elif not has_pin:
            message = "fragment not pinned"
        elif state == "critical":
            message = (
                f"drift exceeds threshold "
                f"({commits} commits, {days} days)"
            )
        elif hand_edited:
            message = (
                f"expected_value edited by hand: HEAD carries {head_value!r}, the "
                f"manifest {(entry or {}).get('expected_value')!r}, beside an unchanged "
                f"pin ({last_sha[:7]}); verify the number, then re-pin with "
                f"--expected-value"
            )
        elif dirty_here:
            message = (
                f"bound has uncommitted changes ({', '.join(dirty_here)}): the pin "
                f"at {last_sha[:7]} cannot vouch for the working tree; commit, then "
                f"re-pin"
            )
            if commits:
                message += f"; drift detected ({commits} commits, {days} days)"
        elif state == "stale":
            message = f"drift detected ({commits} commits, {days} days)"

        states.append(FragmentState(
            fragment=frag,
            state=state,
            last_verified_sha=last_sha,
            manifest_bound=manifest_bound,
            commits_since=commits,
            days_since=days,
            message=message,
            dirty_paths=tuple(dirty_here),
        ))

    return states


def _head_sha(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", check=False, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):  # strict decode: a structured answer (DEF-821)
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    """Stdlib-only direct-invocation entry; the operator-facing CLI lives
    in ``espalier.cli``."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="repository root")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    states = scan_repo(root)
    for s in states:
        print(json.dumps({
            "id": s.fragment.id,
            "state": s.state,
            "commits_since": s.commits_since,
            "days_since": s.days_since,
            "message": s.message,
        }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
