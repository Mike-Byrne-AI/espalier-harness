"""Which readers of the machine-name key tell a read that failed from a key that is not set.

``git config espalier.machine`` is read three ways under ``tools/cc``: through
``mail.machine_setting``, whose reason opens with ``MACHINE_UNREAD`` when the read
itself failed (a timeout, a config git cannot parse); through ``mail.clone_machine``,
which cannot tell the two apart yet (DEF-5003); and by raw ``git config --get``
calls (DEF-5004). One predicate serves the contract pin
(``tests/test_contracts.py::TestEveryNameReaderSaysWhichItIs``) and those rows'
ledger probes, so a pin and a probe cannot disagree about a call. Standard library
only; the files come from git's view of the checkout (``git ls-files``), never a
filesystem walk.

A call says which when its result is unpacked into a pair (a plain or a conditional
assignment) and that binding of the reason reaches a ``startswith`` on
``MACHINE_UNREAD`` (or a name bound from it) or ``_off_reason`` before the name is
bound again; or when a ``# unread-name: ok <why>`` comment sits on the call's own
line or the line above, where silence is the intent. A raw read says which only
through that comment: once it is fixed it reads through a reader that returns the
reason, and leaves this population.

    python3 tests/_name_readers.py machine_setting   # open=False while every call says which
    python3 tests/_name_readers.py clone_machine     # DEF-5003's probe
    python3 tests/_name_readers.py --raw             # DEF-5004's probe
    (add --list for the sites)
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if __package__ in (None, ""):   # run as the ledger probe: the root, not tests/, resolves `tests.`
    sys.path.insert(0, str(REPO))
from tests._git_oracle import require_tracked_paths  # noqa: E402
MARK = re.compile(r"#\s*unread-name: ok \w{3}")
#: The readers that answer with the reason (or will): a raw read inside them is the
#: reader itself, not a caller.
READERS = ("machine_setting", "clone_machine")
_KEY_LITERAL = "espalier.machine"


def tools_cc_files(root: Path = REPO) -> list[Path]:
    """Every tracked ``.py`` under ``tools/cc`` (subfolders included), from git's view; a
    query git cannot answer raises (``tests/_git_oracle.py``), never an empty population."""
    rels = require_tracked_paths(root, "tools/cc", minimum=10, what="tools/cc files")
    return [root / r for r in sorted(rels) if r.endswith(".py") and (root / r).is_file()]


def _name(node: ast.AST) -> str | None:
    return getattr(node, "attr", getattr(node, "id", None))


def _mentions_unread(node: ast.AST) -> bool:
    return any((isinstance(n, (ast.Attribute, ast.Name)) and _name(n) == "MACHINE_UNREAD")
               or (isinstance(n, ast.Constant) and n.value == "MACHINE_UNREAD") for n in ast.walk(node))


def _bound_names(node: ast.AST) -> set[str]:
    targets: list[ast.AST] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.For, ast.AsyncFor)):
        targets = [node.target]
    elif isinstance(node, ast.withitem) and node.optional_vars is not None:
        targets = [node.optional_vars]
    return {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}


def _marked(lines: list[str], lineno: int) -> bool:
    """The comment on the call's own line or the line above."""
    return any(MARK.search(lines[i]) for i in (lineno - 1, lineno - 2) if 0 <= i < len(lines))


def _says_which(call: ast.Call, scope: ast.AST, lines: list[str]) -> bool:
    if _marked(lines, call.lineno):
        return True
    binding = None
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Tuple):
            value, elts = node.value, node.targets[0].elts
            hit = value is call or (isinstance(value, ast.IfExp) and call in (value.body, value.orelse))
            if hit and len(elts) == 2 and isinstance(elts[1], ast.Name) and elts[1].id != "_":
                binding = node
    if binding is None:
        return False   # a bare use, a subscript, or the reason thrown away
    reason = binding.targets[0].elts[1].id
    start = binding.end_lineno or binding.lineno
    # This binding of the reason holds until the name is bound again: a test of a
    # later binding, or of an earlier one, is not this call's.
    until = min((n.lineno for n in ast.walk(scope) if getattr(n, "lineno", 0) > start
                 and reason in _bound_names(n)), default=len(lines) + 1)
    bound = {t.id for a in ast.walk(scope) if isinstance(a, ast.Assign) and _mentions_unread(a.value)
             for t in a.targets if isinstance(t, ast.Name)}
    for c in ast.walk(scope):
        if not (isinstance(c, ast.Call) and start < c.lineno < until):
            continue
        if (isinstance(c.func, ast.Attribute) and c.func.attr == "startswith" and c.args
                and any(isinstance(n, ast.Name) and n.id == reason for n in ast.walk(c.func.value))
                and (_mentions_unread(c.args[0]) or (isinstance(c.args[0], ast.Name) and c.args[0].id in bound))):
            return True
        if _name(c.func) == "_off_reason" and any(isinstance(n, ast.Name) and n.id == reason
                                                  for a in c.args for n in ast.walk(a)):
            return True
    return False


def _innermost(funcs: list[ast.AST], lineno: int):
    return min((f for f in funcs if f.lineno <= lineno <= (f.end_lineno or f.lineno)),
               key=lambda f: (f.end_lineno or f.lineno) - f.lineno, default=None)


def _parse(path: Path) -> tuple[str, ast.AST, list[ast.AST], list[str]]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    funcs = [f for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return text, tree, funcs, text.splitlines()


def calls(files: list[Path], root: Path, reader: str = "machine_setting") -> tuple[list[str], list[str], list[str]]:
    """``(every call of reader, the calls that do not say which, the aliases of reader)``,
    each as ``<file>::<function>`` (``<module>`` for a top-level call) or ``<file>::<line>``."""
    found: list[str] = []
    silent: list[str] = []
    aliases: list[str] = []
    for path in files:
        _text, tree, funcs, lines = _parse(path)
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(a.name == reader and a.asname not in (None, reader)
                                                        for a in node.names):
                aliases.append(f"{rel}::{node.lineno}")
            if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Attribute, ast.Name)) \
                    and _name(node.value) == reader:
                aliases.append(f"{rel}::{node.lineno}")
            if (isinstance(node, ast.Call) and _name(node.func) == "getattr" and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant) and node.args[1].value == reader):
                aliases.append(f"{rel}::{node.lineno}")
        for call in ast.walk(tree):
            if not (isinstance(call, ast.Call) and _name(call.func) == reader):
                continue
            inner = _innermost(funcs, call.lineno)
            if inner is not None and inner.name == reader:
                continue
            scope, where = (tree, "<module>") if inner is None else (inner, inner.name)
            found.append(f"{rel}::{where}")
            if not _says_which(call, scope, lines):
                silent.append(f"{rel}::{where}")
    return found, silent, sorted(aliases)


def _raw_key_read(call: ast.AST) -> bool:
    """A ``git config ... --get`` of the machine-name key: the literal, or a name
    ``MACHINE_KEY``, among the call's arguments or a list argument's items."""
    if not isinstance(call, ast.Call):
        return False
    args = [x for a in call.args for x in (a.elts if isinstance(a, (ast.List, ast.Tuple)) else [a])]
    strings = {x.value for x in args if isinstance(x, ast.Constant) and isinstance(x.value, str)}
    return {"config", "--get"} <= strings and (
        _KEY_LITERAL in strings or any(isinstance(x, (ast.Name, ast.Attribute)) and _name(x) == "MACHINE_KEY"
                                       for x in args))


def raw_reads(files: list[Path], root: Path) -> tuple[list[str], list[str]]:
    """``(every raw read of the key outside the READERS, the reads not marked)``, each
    as ``<file>::<function>:<line>``."""
    found: list[str] = []
    silent: list[str] = []
    for path in files:
        _text, tree, funcs, lines = _parse(path)
        rel = path.relative_to(root).as_posix()
        for call in ast.walk(tree):
            if not _raw_key_read(call):
                continue
            inner = _innermost(funcs, call.lineno)
            if inner is not None and inner.name in READERS:
                continue
            site = f"{rel}::{inner.name if inner else '<module>'}:{call.lineno}"
            found.append(site)
            if not _marked(lines, call.lineno):
                silent.append(site)
    return sorted(found), sorted(silent)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--list"]
    files = tools_cc_files(REPO)
    if args == ["--raw"]:
        open_sites = raw_reads(files, REPO)[1]
    else:
        reader = args[0] if args else "machine_setting"
        if f"def {reader}(" not in (REPO / "tools" / "cc" / "mail.py").read_text(encoding="utf-8"):
            sys.exit(f"tools/cc/mail.py defines no {reader}: the reader moved, so this probe must move with it")
        found, open_sites, aliases = calls(files, REPO, reader)
        open_sites = open_sites + [f"alias {a}" for a in aliases]
    if "--list" in sys.argv[1:]:
        for site in open_sites:
            print(site)
    print(f"open={bool(open_sites)}")
