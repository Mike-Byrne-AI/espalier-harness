"""The directories a live-tree walker in ``tests/`` never descends.

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
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

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
