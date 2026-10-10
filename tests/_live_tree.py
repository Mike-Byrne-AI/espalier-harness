"""The directories a live-tree walker in ``tests/`` never descends, and what a
copy of the live tree leaves out.

Not a test module (leading underscore) -- no marker classification needed.

**Why this exists.** Three contract tests walk the checkout's ``.claude/`` with
``rglob`` and read what they find as this tree's shipped text:
``tests/test_utf8_text_io.py::_shipped_texts``,
``tests/test_interpreter_hosts.py::_shipped_claude_bodies`` and
``tests/test_documented_claims.py::_public_scan_files``. ``claude --worktree``
checks a SECOND copy of the tree out under ``.claude/worktrees/<name>/`` -- at
another commit, with its own line endings -- and ``espalier._safe_walk.visible``
keeps it: that filter drops hidden names below its base, and ``worktrees`` is not
a hidden name, so ``.claude/worktrees/<name>/docs/x.md`` has no hidden component
below ``.claude`` and every markdown file of the other checkout passes. Measured
2026-10-09 on the self-host box with a detached worktree at
``.claude/worktrees/probe``: ten reds across four files (three in
``test_utf8_text_io``, five in ``test_interpreter_hosts``, one in
``test_documented_claims``, and one through ``espalier/scanners/freshness.py`` --
the scanner half, which this module does not reach; `DEF-1196` keeps it). CI has
no worktree and never sees any of them; the operator running the slice beside a
worktree session reads ten false reds and sorts them by hand.

**The set is the single home.** It grows only with a measured red, and every
walker that routes through :func:`exclude_worktrees` carries a planted-file test
beside it: a scratch tree with a file under ``.claude/worktrees/`` and a control
beside it, so each walker's exclusion is earned on its own, not inferred from
the helper's. ``git ls-files`` was the other shape (the population IS the tracked
tree) and was not taken: these walkers deliberately read an unstaged body so a
new command is judged before its commit, and a switch to the index would retire
that silently.

**Copies are the other half.** A test that copies the checkout with
``shutil.copytree(REPO_ROOT, ...)`` and ``ignore_patterns(".git", ...)`` drops a
linked worktree's ``.git`` gitlink FILE along with the checkout's own ``.git``
directory, so the worktree lands in the copy as plain files and nothing in the
copy says it is another checkout. The scanners' nested-repo prune holds on the
live tree (a ``.git`` entry of any kind) and so cannot hold on the copy: the
freshness scanner read ``.claude/worktrees/probe/docs/CONVENTIONS.md`` in
``test_freshness_hook_count_migration``'s copy and raised "duplicate fragment id
'hook-count'" (DEF-1196's scanner half, measured 2026-10-10: the live tree's
walk yielded nothing under the worktree; the copy held it whole).
:func:`live_tree_copy_ignore` (and :func:`live_tree_skip_names`, for a callback
with rules of its own) leaves every nested repository out, judged at the source
before the ``.git`` name is gone -- the engine's prune rule
(``espalier._safe_walk.has_git_entry``), so a submodule or an embedded clone
keeps its boundary too -- and the walkers' name pair beside it, so a worktree
folder that lost its ``.git`` is still left out. ``conftest.py``'s isolated-repo
fixture keeps the nested-repo half with ``is_own_git_repo``.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Iterable

from espalier._safe_walk import has_git_entry

#: Consecutive path components, relative to the repo root, under which nothing
#: is this tree's text. One member, measured: Claude Code's linked worktrees
#: (``claude --worktree``; the directory is gitignored since 2026-10-08, which a
#: filesystem walk does not consult).
EXCLUDED_DIR_PARTS: tuple[tuple[str, ...], ...] = ((".claude", "worktrees"),)


def is_under_excluded_dir(path: Path, repo_root: Path) -> bool:
    """True when ``path`` lies below one of :data:`EXCLUDED_DIR_PARTS`, the pair
    matched anywhere in its parts relative to ``repo_root`` -- a nested checkout
    carries its own ``.claude/worktrees``. A path not under ``repo_root`` is
    judged on its own parts, so a caller passing the wrong root cannot keep a
    worktree's file by accident. Pure path arithmetic: nothing is resolved or
    read, so a dangling member costs nothing."""
    path = Path(path)
    try:
        parts = path.relative_to(Path(repo_root)).parts
    except ValueError:
        parts = path.parts
    for excluded in EXCLUDED_DIR_PARTS:
        width = len(excluded)
        if any(tuple(parts[i:i + width]) == excluded for i in range(len(parts) - width + 1)):
            return True
    return False


def exclude_worktrees(paths: Iterable[Path], repo_root: Path) -> list[Path]:
    """``paths`` without any member under an excluded directory, in input order
    (compose with ``visible``, which sorts)."""
    return [p for p in paths if not is_under_excluded_dir(p, repo_root)]


def nested_repo_names(directory: str, names: list[str]) -> set[str]:
    """The members of ``names`` that are a repository of their own inside
    ``directory`` -- a ``.git`` entry of any kind: a linked worktree's gitlink
    file, a submodule's, an embedded clone's directory. Nothing is resolved, so
    a symlinked directory is judged by its link path, the path a copy walks."""
    return {n for n in names if has_git_entry(Path(directory) / n)}


def live_tree_skip_names(directory: str, names: list[str]) -> set[str]:
    """What a copy of the live checkout leaves out of ``directory``, in
    ``shutil.copytree``'s ``ignore`` signature, for a callback with rules of its
    own to compose with: every nested repository (:func:`nested_repo_names`),
    and the last member of an :data:`EXCLUDED_DIR_PARTS` run whose leading
    members end ``directory`` -- ``worktrees`` under a ``.claude``. The name
    rule is the walkers' and covers a worktree folder whose ``.git`` link is
    gone (an interrupted removal on Windows stops at the first locked file;
    ``tools/cc/checkout_sync.py`` reports that state), so a walk and a copy
    never disagree about one directory."""
    tail = Path(directory).parts
    by_name = {
        excluded[-1] for excluded in EXCLUDED_DIR_PARTS
        if excluded[-1] in names and len(tail) >= len(excluded) - 1
        and tuple(tail[len(tail) - len(excluded) + 1:]) == excluded[:-1]
    }
    return nested_repo_names(directory, names) | by_name


def live_tree_copy_ignore(*patterns: str) -> Callable[[str, list[str]], set[str]]:
    """``shutil.ignore_patterns(*patterns)`` plus :func:`live_tree_skip_names`:
    the ``ignore`` for a copy of the live checkout. A copy that leaves ``.git``
    out without it erases a linked worktree's boundary (the module docstring)."""
    by_pattern = shutil.ignore_patterns(*patterns)

    def ignore(directory: str, names: list[str]) -> set[str]:
        return set(by_pattern(directory, names)) | live_tree_skip_names(directory, names)

    return ignore
