"""The symbols a change touches, derived from its diff.

A symbol is ``path::qualname``: a function, a method as ``Class.method``, a
class, or a module-level assignment by each target name it binds. Symbols are
derived by the standard library's ``ast`` on BOTH sides of every hunk: added
and changed lines in the new version of a file, removed and changed lines in the
old one, so a rename reports both names and a hunk that deletes one function
while extending another reports both. A decorator, or an unbroken run of
comments directly above a definition and not indented deeper than it, belongs
to it. A blank line is its function's inside one and neutral elsewhere. A
changed line no definition holds (an import, a lone comment, a line of a file
one side cannot parse, a line a side does not have) is UNPLACED: counted, a
path hit at most, and never read as "different functions"; nor is a file no
line of which was read. A file that is not Python is a path tier of its own,
never a symbol.

Two changes that touch conflict in git even in different functions, so each
hunk also places the old lines beside it: the line before and the line after
an edit, and the two lines an insertion sits between. A blank neighbour
between nodes stays neutral; one before the first line or past the last is
the file's own ``<start>`` or ``<end>``, so two appends to one file meet
there. "Different functions" therefore means no symbol shared and none next
to the other's change.

The mapper moved here from ``scripts/lane_overlap_census.py`` (the oracle that
measured it over thirty merged pull requests), which now imports it and keeps no
copy. Read by the mail channel's claims (``mail.py``: a claim carries the
symbols its lane changed) and by the plan pre-flight (``execution_plan.py``).
:func:`symbols_meet` is the one rule for what two symbol sets share; every
reader calls it.

Standard library and ``git`` only, run through ``record_merge.run`` (the one
spawn, injectable as ``run=``), with no import of the engine
(``tests/test_contracts.py::TestToolsCcNoEspalierImports``). So the fold of a
mirror twin onto its source here is the one pair the deployed tools own, the
vendored copy of this directory; the census keeps the engine registry's full
fold.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Callable

# The one spawn and the named stop, from the sibling every deployed tool shares
# (tests/test_deploy_set_import_closure.py pins the reachability).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from record_merge import Unresolvable, run  # noqa: E402

__all__ = [
    "DIFF_ARGS", "MODULE", "Unresolvable", "VENDOR_MIRROR", "VENDOR_SOURCE", "canonical",
    "changed_symbols", "concurrent", "enclosing", "innermost", "innermost_spans", "pair_verdict", "placed", "spans",
    "symbols_between", "symbols_meet", "symbols_of_lane",
]

Runner = Callable[..., tuple[int, str, str]]

MODULE = "<module>"
#: The edges of a file, as the neighbours a hunk at either end touches.
START, END = "<start>", "<end>"
#: Every verdict ``pair_verdict`` gives; a reader that words them covers each.
VERDICTS = ("shared symbol", "unplaced", "different functions", "path only", "none")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
#: Every diff read here: rename detection off, so a moved file is a deletion at
#: its old path and an addition at its new one, and another lane editing the old
#: path meets it; and the format pinned against the user's git config, which
#: otherwise reaches this reader (code review, driven): an external differ or a
#: textconv filter replaces git's own text, a forced colour puts a code before
#: every hunk header, and a wider inter-hunk context merges two hunks over an
#: untouched function between them. Pinned by the tests.
DIFF_ARGS: tuple[str, ...] = (
    "--no-renames", "--no-ext-diff", "--no-textconv", "--no-color", "--inter-hunk-context=0",
)
#: The lines a ``-U0`` diff carries besides its hunks: git's own header lines.
#: A Python file whose diff holds anything else and no hunk this reader can
#: parse is unplaced, never "nothing changed".
_DIFF_HEADERS = (
    "diff --git ", "index ", "old mode ", "new mode ", "deleted file mode ", "new file mode ",
    "--- ", "+++ ", "similarity index ", "dissimilarity index ", "rename from ", "rename to ",
    "copy from ", "copy to ",
)
#: The mirror pair the deployed tools own: the engine's vendored copy of this
#: directory, folded onto it so a lane editing a tool and its twin meets another
#: lane once. Pinned against ``espalier/mirror_registry.py``'s ``vendor-cc`` row
#: by the test, since this module may not import the registry.
VENDOR_MIRROR = "espalier/_vendor/cc/"
VENDOR_SOURCE = "tools/cc/"
_GIT_TIMEOUT = 60.0
_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_ASSIGN_NODES = (ast.Assign, ast.AnnAssign, ast.AugAssign)


# ---------------------------------------------------------------- placement

Span = tuple[str, int, int, str]


def _target_names(node: ast.AST) -> list[str]:
    """Each name an assignment target binds: ``a`` for ``a = 1``, ``a`` and
    ``b`` for ``a, b = ...``, the root name for an attribute or subscript
    (``X`` for ``X[1, 2] = ...``, so no comma reaches a symbol)."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [n for elt in node.elts for n in _target_names(elt)]
    if isinstance(node, ast.Starred):
        return _target_names(node.value)
    while isinstance(node, (ast.Subscript, ast.Attribute)):
        node = node.value
    if isinstance(node, ast.Name):
        return [node.id]
    return [ast.unparse(node)]


def spans(source: str) -> list[Span]:
    """``[(qualname, first_line, last_line, kind)]``, ``kind`` one of ``def``,
    ``class`` and ``name``, for every function, async function and class at
    any depth (qualified by the definitions above it: ``C.m``; a block such as
    ``if TYPE_CHECKING:`` or ``try:`` adds nothing), a definition's span
    starting at its first decorator, and for every module-level assignment by
    each target it binds. An assignment inside a class body is the class's,
    not a symbol of its own. Unparseable source maps nothing, so its lines
    read as unplaced (a NUL byte is a ValueError on Python 3.10, a
    SyntaxError later)."""
    out: list[Span] = []
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return out

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _DEF_NODES):
                name = f"{prefix}{child.name}"
                lo = min([child.lineno] + [d.lineno for d in child.decorator_list])
                kind = "class" if isinstance(child, ast.ClassDef) else "def"
                out.append((name, lo, child.end_lineno or child.lineno, kind))
                walk(child, name + ".")
            elif prefix == "" and isinstance(child, _ASSIGN_NODES):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    for name in _target_names(target):
                        out.append((name, child.lineno, child.end_lineno or child.lineno, "name"))
            else:
                walk(child, prefix)

    walk(tree, "")
    return out


def innermost_spans(nodes: list[Span], line: int) -> list[Span]:
    """Every span that is the shortest one holding ``line``: one for a line
    inside a definition, each name of a tuple target for the line of
    ``a, b = ...`` (they share one span), nothing outside every node."""
    best: int | None = None
    found: list[Span] = []
    for span in nodes:
        _name, lo, hi, _kind = span
        if not (lo <= line <= hi):
            continue
        if best is None or (hi - lo) < best:
            best, found = hi - lo, [span]
        elif (hi - lo) == best:
            found.append(span)
    return found


def innermost(nodes: list[Span], line: int) -> list[str]:
    """The names of `innermost_spans`."""
    return [name for name, *_ in innermost_spans(nodes, line)]


def enclosing(nodes: list[Span], line: int) -> str:
    """The innermost span holding ``line`` (the first of `innermost`), else the module."""
    names = innermost(nodes, line)
    return names[0] if names else MODULE


def _indent(text: str) -> int:
    return len(text) - len(text.lstrip())


def placed(nodes: list[Span], lines: list[str], line: int) -> list[str]:
    """Where ``line`` (1-based) lands: a line the source does not have is the
    module, unplaced (a side that could not be read certifies nothing); a
    blank line is its function's when a function's span holds it (git
    conflicts on the edit beside it) and nothing elsewhere, neutral (the
    blank between two methods and a deletion's trailing blanks name no
    symbol, so an edit never flags a neighbour it did not touch); else its
    innermost node or nodes; for a comment outside every node, the node that
    starts right after an unbroken run of comments, when the comment is not
    indented deeper than that node (a blank breaks the run, and a comment
    indented as the body above it is unplaced); else the module, unplaced."""
    if not 0 < line <= len(lines):
        return [MODULE]
    text = lines[line - 1]
    stripped = text.strip()
    here = innermost_spans(nodes, line)
    if not stripped:
        return [name for name, _lo, _hi, kind in here if kind == "def"]
    if here:
        return [name for name, *_ in here]
    if not stripped.startswith("#"):
        return [MODULE]
    cursor = line
    while cursor <= len(lines):
        found = innermost_spans(nodes, cursor)
        if found:
            if _indent(text) <= _indent(lines[found[0][1] - 1]):
                return [name for name, *_ in found]
            return [MODULE]
        run = lines[cursor - 1].strip()
        if not run or not run.startswith("#"):
            return [MODULE]
        cursor += 1
    return [MODULE]


def _lines(source: str) -> list[str]:
    """The lines as git and ``ast`` count them: split on newlines only
    (``str.splitlines`` also splits on form feed and U+2028, and every line
    after one would read one off), without the empty tail a final newline leaves."""
    lines = source.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def symbols_meet(one: set[str], two: set[str]) -> set[str]:
    """The symbols two lanes both touch, the one rule every reader uses: an
    equal name, or a class on one side with a member of it on the other
    (``path::C`` meets ``path::C.m``, reported as the class); never the
    module, which is unplaced on both sides and a path hit at most."""
    met = {s for s in one & two if not s.endswith(f"::{MODULE}")}
    for a, b in ((one, two), (two, one)):
        for symbol in a:
            if symbol.endswith(f"::{MODULE}"):
                continue
            if any(other.startswith(symbol + ".") for other in b):
                met.add(symbol)
    return met


def changed_symbols(path: str, old_source: str, new_source: str, unified_diff: str) -> dict:
    """``{"kind", "symbols", "changed", "unplaced"}`` for one file's diff
    (``-U0`` from any producer): ``kind`` is ``python`` or ``path``; for Python
    every removed or changed line is placed in the old source and every added
    or changed line in the new, ``changed`` counts the lines read and
    ``unplaced`` the ones no node holds; for any other file the path is the
    one symbol and nothing is unplaced. Lines are counted by the newline
    alone (`_lines`), as git and the parser count them, and so is the diff.
    A diff that holds text other than git's headers and no hunk this reader
    can parse counts one unplaced line: whatever produced it, the file
    changed, and it is never certified as unchanged."""
    if not path.endswith(".py"):
        return {"kind": "path", "symbols": {path}, "changed": 0, "unplaced": 0}
    new_nodes, old_nodes = spans(new_source), spans(old_source)
    new_lines, old_lines = _lines(new_source), _lines(old_source)
    symbols: set[str] = set()
    changed = unplaced = 0
    hunks = 0
    unread = False
    for line in unified_diff.split("\n"):
        m = HUNK_RE.match(line)
        if not m:
            if line.strip() and not line.startswith(_DIFF_HEADERS):
                unread = True
            continue
        hunks += 1
        old_start, old_len = int(m.group(1)), int(m.group(2) or 1)
        new_start, new_len = int(m.group(3)), int(m.group(4) or 1)
        sides = []
        if old_len > 0 and m.group(2) != "0":
            sides.append((old_nodes, old_lines, range(old_start, old_start + old_len)))
        if new_len > 0 and m.group(4) != "0":
            sides.append((new_nodes, new_lines, range(new_start, new_start + new_len)))
        for nodes, lines, span in sides:
            for ln in span:
                names = placed(nodes, lines, ln)
                if not names:                 # a blank line: neutral, neither placed nor unplaced
                    continue
                changed += 1
                if names == [MODULE]:
                    unplaced += 1
                for where in names:
                    symbols.add(f"{path}::{where}")
        # The old lines touching the hunk: git conflicts on two changes that touch, so a
        # change also names what sits right beside it (an insertion, the two lines it is
        # between; an edit, the line before and the line after).
        around = (old_start, old_start + 1) if m.group(2) == "0" else (old_start - 1, old_start + old_len)
        for ln in around:
            if ln < 1 or ln > len(old_lines):
                symbols.add(f"{path}::{START if ln < 1 else END}")
                continue
            names = placed(old_nodes, old_lines, ln)
            if names == [MODULE]:
                unplaced += 1
            for where in names:               # a blank between nodes names nothing: neutral
                symbols.add(f"{path}::{where}")
    if unread and not hunks:
        changed += 1
        unplaced += 1
        symbols.add(f"{path}::{MODULE}")
    return {"kind": "python", "symbols": symbols, "changed": changed, "unplaced": unplaced}


# ---------------------------------------------------------------- the pair

def concurrent(a: dict, b: dict) -> bool:
    """Two pull requests were open at once: each was created before the other merged."""
    return a["created"] < b["merged"] and b["created"] < a["merged"]


def pair_verdict(one: dict[str, dict], two: dict[str, dict]) -> dict:
    """What two lanes' placements say about each other, over the files both
    changed: ``shared`` (symbols both changed, the module excluded), ``paths``
    (files that are not Python), ``unplaced`` (Python files where a side left
    lines unplaced, or read no line at all, and no symbol is shared),
    ``verdict`` one of ``shared symbol``, ``unplaced``, ``different
    functions``, ``path only``, ``none``."""
    files = sorted(set(one) & set(two))
    shared: set[str] = set()
    paths: list[str] = []
    unplaced: list[str] = []
    certified: list[str] = []
    for path in files:
        a, b = one[path], two[path]
        if a["kind"] != "python" or b["kind"] != "python":
            paths.append(path)
            continue
        meet = symbols_meet(a["symbols"], b["symbols"])
        if meet:
            shared |= meet
        elif a["unplaced"] or b["unplaced"] or not a["changed"] or not b["changed"]:
            unplaced.append(path)   # a side that read no line certifies nothing
        else:
            certified.append(path)
    if shared:
        verdict = "shared symbol"
    elif unplaced:
        verdict = "unplaced"
    elif certified:
        verdict = "different functions"
    elif paths:
        verdict = "path only"
    else:
        verdict = "none"
    return {"files": files, "shared": sorted(shared), "paths": paths, "unplaced": unplaced,
            "certified": certified, "verdict": verdict}


# ---------------------------------------------------------------- git

def canonical(path: str) -> str:
    """A path in the vendored copy of this directory folded onto its source;
    any other path as spelled."""
    if path.startswith(VENDOR_MIRROR):
        return VENDOR_SOURCE + path[len(VENDOR_MIRROR):]
    return path


def _git(root: Path | str | None, *args: str, run: Runner, env: dict[str, str] | None,
         check: bool = True) -> str:
    """``git <args>``'s stdout in ``root`` (the cwd when None). A failure is a
    named refusal; with ``check=False`` it is the empty string (``git show`` of
    a file the revision does not hold: a file one side added or deleted)."""
    rc, out, err = run(["git", *args], cwd=None if root is None else str(root), timeout=_GIT_TIMEOUT, env=env)
    if rc != 0:
        if not check:
            return ""
        why = (err.strip() or out.strip())[:200] or f"exit {rc} with nothing on stderr"
        raise Unresolvable(f"git {' '.join(args[:2])} failed: {why}")
    return out


def _blob(root: Path | str | None, rev: str, path: str, *, run: Runner, env: dict[str, str] | None) -> str:
    """A file's text at ``rev``, raw (no textconv, no filter): the empty
    string where the revision does not hold it (a file one side added or
    deleted)."""
    return _git(root, "cat-file", "blob", f"{rev}:{path}", run=run, env=env, check=False)


def _line_count(text: str) -> int:
    """How many lines git counts in ``text``: one per newline, plus an
    unterminated last line."""
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def _fold(out: dict[str, dict], path: str, here: dict, fold: Callable[[str], str]) -> None:
    """Add one file's placement to ``out`` under its folded path, a twin's
    symbols united with its source's and the counts summed."""
    key = fold(path)
    if key != path:
        here["symbols"] = {s.replace(path, key, 1) for s in here["symbols"]}
    if key in out:
        got = out[key]
        got["symbols"] |= here["symbols"]
        got["changed"] += here["changed"]
        got["unplaced"] += here["unplaced"]
    else:
        out[key] = here


def _names(text: str) -> list[str]:
    """The paths of a ``-z`` listing."""
    return [p for p in text.split("\0") if p]


def symbols_between(base: str, head: str, *, root: Path | str | None = None, run: Runner = run,
                    env: dict[str, str] | None = None, fold: Callable[[str], str] = canonical) -> dict[str, dict]:
    """``{folded path: placement}`` for every file ``base..head`` changes, both
    revisions read from git, mirror twins folded by ``fold`` (symbols united,
    counts summed)."""
    out: dict[str, dict] = {}
    for path in _names(_git(root, "diff", "--name-only", "-z", *DIFF_ARGS, base, head, run=run, env=env)):
        py = path.endswith(".py")
        new = _blob(root, head, path, run=run, env=env) if py else ""
        old = _blob(root, base, path, run=run, env=env) if py else ""
        diff = _git(root, "diff", "-U0", *DIFF_ARGS, base, head, "--", path, run=run, env=env) if py else ""
        _fold(out, path, changed_symbols(path, old, new, diff), fold)
    return out


def symbols_of_lane(root: Path | str, base_ref: str, *, run: Runner = run, env: dict[str, str] | None = None,
                    fold: Callable[[str], str] = canonical) -> dict[str, dict]:
    """``{folded path: placement}`` for everything a lane changes: read against
    the merge-base of ``base_ref`` and ``HEAD`` with no second revision, so the
    working tree counts, staged or not, and a base that moved after the branch
    point contributes nothing of its own; plus the untracked files
    ``git ls-files --others --exclude-standard`` names, each read as wholly
    added. A base git cannot read is a named refusal, never an empty lane.
    Read from the top of the tree whatever directory ``root`` names, since
    git names untracked files relative to the directory it runs in and diff
    names relative to the top."""
    root = Path(_git(Path(root), "rev-parse", "--show-toplevel", run=run, env=env).strip())
    try:
        merge_base = _git(root, "merge-base", base_ref, "HEAD", run=run, env=env).strip()
    except Unresolvable as exc:
        raise Unresolvable(f"the lane cannot be read against {base_ref}: no common history with HEAD, "
                           f"or {base_ref} is not a revision here ({exc})") from None
    out: dict[str, dict] = {}
    for path in _names(_git(root, "diff", "--name-only", "-z", *DIFF_ARGS, merge_base, run=run, env=env)):
        py = path.endswith(".py")
        new = _working_text(root, path) if py else ""
        old = _blob(root, merge_base, path, run=run, env=env) if py else ""
        diff = _git(root, "diff", "-U0", *DIFF_ARGS, merge_base, "--", path, run=run, env=env) if py else ""
        _fold(out, path, changed_symbols(path, old, new, diff), fold)
    for path in _names(_git(root, "ls-files", "--others", "--exclude-standard", "-z", run=run, env=env)):
        new = _working_text(root, path) if path.endswith(".py") else ""
        count = _line_count(new)
        added = f"@@ -0,0 +1,{count} @@\n" if count else ""
        _fold(out, path, changed_symbols(path, "", new, added), fold)
    return out


def _working_text(root: Path, path: str) -> str:
    """A file's text in the working tree; the empty string where it is gone
    (deleted in the working tree) or unreadable as a file."""
    try:
        return (root / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
