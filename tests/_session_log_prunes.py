"""Which code prunes the Session Log to its cap, outside the one writer that owns it.

``tools/cc/_record_fragments.py::prune_session_log`` drops the oldest fragments
past ``SESSION_LOG_CAP``. Until 2026-10-16 every lane enforced the cap in its own
tree (``post_write_check`` at the write, ``handoff_mechanics`` at the handoff),
and two trees each kept at 30 merged to 31 on main: a count two lanes both
recompute (Core Rule 15), which cost a prune commit on the next lane to land. The
one place the Session Log is pruned is now the fold in ``tools/cc/ship.py``, which
brings every records ref's pending rows into the lane at its push and prunes back
to the cap past its slack; the prune verb's own command line stays, an operator's
tool. Any other call of ``prune_session_log`` in the shipped code, and any
``.claude/`` body naming the verb, is a second writer. One predicate serves the
contract pin (``tests/test_contracts.py::TestOnlyTheFoldPrunesTheSessionLog``) and the
ledger probe, so the two cannot disagree. Standard library only; the files come
from git's view of the checkout.

    python3 tests/_session_log_prunes.py          # open=False while only the fold and the CLI prune
    python3 tests/_session_log_prunes.py --list   # the sites outside them
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if __package__ in (None, ""):   # run as the ledger probe: the root, not tests/, resolves `tests.`
    sys.path.insert(0, str(REPO))
from tests._git_oracle import require_tracked_paths  # noqa: E402

PRUNE = "prune_session_log"
#: The calls that are the one writer, or the operator's own verb: (file, enclosing function).
ALLOWED: frozenset[tuple[str, str]] = frozenset({
    ("tools/cc/ship.py", "_fold_session_log"),
    ("tools/cc/_record_fragments.py", "main"),
})
#: The shipped code a second writer could live in; the byte mirrors are copies of it.
ROOTS = ("tools/cc", "scripts", "espalier")
SKIP = ("espalier/_vendor/", "espalier/assets/")


def shipped_files(root: Path = REPO) -> list[str]:
    """Every tracked ``.py`` under ``ROOTS`` but the mirrors, from git's view; a query git
    cannot answer raises (``tests/_git_oracle.py``), never an empty population."""
    out: list[str] = []
    for top in ROOTS:
        rels = require_tracked_paths(root, top, minimum=1, what=f"{top} files")
        out += [r for r in rels if r.endswith(".py") and not r.startswith(SKIP)]
    return sorted(set(out))


def prune_calls(root: Path = REPO, files: list[str] | None = None) -> list[tuple[str, str, int]]:
    """``(file, enclosing function, line)`` for every call of ``prune_session_log``, by
    name or as an attribute, in ``files`` (default: the shipped code)."""
    found: list[tuple[str, str, int]] = []
    for rel in files if files is not None else shipped_files(root):
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue

        def walk(node: ast.AST, where: str) -> None:
            for child in ast.iter_child_nodes(node):
                inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else where
                if isinstance(child, ast.Call):
                    name = getattr(child.func, "attr", getattr(child.func, "id", None))
                    if name == PRUNE:
                        found.append((rel, where, child.lineno))
                elif isinstance(child, ast.ImportFrom) and any(
                        a.name == PRUNE and a.asname for a in child.names):
                    # A call through an alias would pass the name test above.
                    found.append((rel, where, child.lineno))
                walk(child, inner)

        walk(tree, "<module>")
    return sorted(found)


def outside_the_fold(root: Path = REPO, files: list[str] | None = None) -> list[tuple[str, str, int]]:
    """The calls that are neither the fold nor the operator's verb."""
    return [c for c in prune_calls(root, files) if (c[0], c[1]) not in ALLOWED]


#: The verb's command line, as a body under ``.claude/`` would tell a session to run it.
PRUNE_VERB = "_record_fragments.py prune"


def prose_prunes(root: Path = REPO) -> list[str]:
    """``path:line`` for every line of a tracked ``.claude/`` body that names the
    prune verb: an agent, command or skill told to prune in its own lane is a
    second writer of the cap through prose, which the call walk above cannot
    see (the failure-mode review of DEF-5007 found the docs-maintainer agent
    doing it). The operator's own mentions live in ``docs/``, not here."""
    out: list[str] = []
    for rel in require_tracked_paths(root, ".claude", minimum=1, what=".claude files"):
        if not rel.endswith(".md"):
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        out += [f"{rel}:{n}" for n, line in enumerate(text.splitlines(), 1) if PRUNE_VERB in line]
    return out


if __name__ == "__main__":
    sites = outside_the_fold(REPO)
    prose = prose_prunes(REPO)
    if "--list" in sys.argv[1:]:
        for rel, where, line in sites:
            print(f"{rel}:{line} in {where}")
        for site in prose:
            print(f"{site} (a body naming the prune verb)")
    print(f"open={bool(sites or prose)}")
