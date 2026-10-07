"""Symlink-safe recursive walk — the version-agnostic replacement for
``Path.rglob`` / recursive ``Path.glob`` on adopter trees.

``Path.rglob(...)`` (and ``Path.glob("**/...")``) follows directory symlinks on
CPython < 3.13 (``recurse_symlinks`` only became default-``False`` at 3.13), so
on an adopter repo with a directory-symlink LOOP it raises ``OSError(ELOOP)``
or, on a plain dir symlink, inflates / double-counts results.
``os.walk(followlinks=False)`` never descends into a symlinked directory on ANY
supported version, so it is both crash-safe and inflation-safe. See
docs/FAILURE_MODES.md §9.7 + memory earn-the-red-has-a-platform-ceiling.

Stdlib-only: importable from ``espalier/scanners/`` without breaking the
zero-third-party-dependency contract.
"""
from __future__ import annotations

import fnmatch
import os
from collections.abc import Collection, Iterable, Iterator
from pathlib import Path

#: Directories a package manager fills with third-party code, by NAME and at
#: any depth: a workspace keeps a ``node_modules/`` beside each package, not
#: only at the root, so a root-anchored prefix misses the second one. What is
#: under them is never this repository's docs or source -- a package's README
#: links to files the package did not ship, and its modules are not the
#: adopter's public surface. Shared by three walkers that read files FOR their
#: content -- ``reflection._iter_markdown_files``, ``strengthen._iter_repo_py``
#: and ``scope_walker._iter_scannable_lines`` -- whose three hand-kept lists
#: gave three answers about the same tree. It is NOT every walker's list: the
#: scanners cannot import it (they are stdlib-only copies), and the
#: fingerprint, release and fusion walkers keep lists of their own, for
#: questions of their own. A new walker that reads content from the repository
#: root passes this as ``skip_dirs``; nothing reds if it does not.
#:
#: ``vendor/`` is deliberately NOT a member: a Go repository commits it as
#: source. Python environments are not members either: their names are the
#: operator's choice, and the release classifier already calls the usual ones
#: transient.
DEPENDENCY_TREE_DIRS: frozenset[str] = frozenset({
    "node_modules",
    "bower_components",
    "jspm_packages",
    ".yarn",
    ".pnpm-store",
})


def is_hidden_name(name: str) -> bool:
    """True for a dot-prefixed file or directory name.

    A file manager or an archive tool writes these beside the real entries of
    a directory and never as part of a project's surface: Finder's
    ``.DS_Store``; the AppleDouble ``._<name>`` sidecar a non-APFS volume or a
    macOS-made zip leaves beside every file, and so beside every ``*.md`` an
    agent or command glob matches; an editor's ``.<name>.swp``. Every
    enumerator of a deployed ``.claude/`` kind gives such a name one answer,
    not a member (§C28, 2026-10-06: a count contract read a sidecar as a
    seventh agent and named a wrong count, never the sidecar). The predicate
    is on the NAME: a hidden PARENT the caller chose to look inside
    (``.claude/`` itself) is the caller's business, never this function's.
    """
    return name.startswith(".")


def visible(paths: Iterable[Path], base: Path) -> list[Path]:
    """``paths`` without any member carrying a hidden name below ``base``, sorted.

    ``base`` is the directory the enumeration started from; every component
    of a member's path below it is checked, so a skill under
    ``._pkg/SKILL.md`` drops with its sidecar directory, and ``.claude/``
    above the base is never read. A member that is not under ``base`` raises
    ``ValueError`` from ``relative_to``: a caller passing the wrong base is a
    bug this function must not paper over with a silently kept entry. The
    OTHER wrong base is quiet: a ``base`` one level too high (``.claude``'s
    parent) puts the hidden ``.claude`` component below it and drops every
    member, so a caller comparing two such listings compares two empty sets;
    a non-empty floor beside the comparison is the guard (the parity rows
    carry one). Real ``Path``s only: an ``importlib.resources`` traversable
    is not a ``PathLike`` under a zip import, so a traversable walk filters
    with ``is_hidden_name(node.name)`` directly (``espalier.assets``).
    """
    base = Path(base)
    return sorted(
        p for p in paths
        if not any(is_hidden_name(part) for part in Path(p).relative_to(base).parts)
    )


def is_own_git_repo(path: Path) -> bool:
    """True if ``path`` is the root of its OWN git repository — a ``.git``
    directory OR a ``.git`` gitlink file (worktree / submodule shape, per
    :mod:`espalier.fuse`). An embedded repo is a foreign project, not part of
    the surface a self-check — or a fresh clone of THIS repo — should include.

    Deliberately FALSE on a dangling ``.git`` symlink: git itself ignores one
    and walks UP to the enclosing repository, which is the exact trap
    :func:`espalier.surface_contract` guards (an extracted archive inside
    ``dist/`` answering for its parent). Callers that PRUNE a walk want the
    opposite answer for that shape — use :func:`has_git_entry`.

    ``os.path.exists``, never ``Path.exists()``: a walk reaches directories
    the process cannot search, and pathlib let the ``PermissionError`` out on
    CPython 3.10-3.13 while 3.14 swallowed it -- ``python -m
    espalier.self_hosting`` crashed on a locked ``.claude`` from exactly this
    probe (DEF-763). ``os.path`` answers False everywhere.
    """
    return os.path.exists(path / ".git")


def has_git_entry(path: Path) -> bool:
    """True if ``path`` carries a ``.git`` entry of ANY kind — directory,
    gitlink file, or a dangling symlink to a moved or removed admin dir.

    The PRUNE predicate: a walk must not descend into a foreign checkout even
    when its ``.git`` no longer resolves (a removed worktree, a relocated
    admin dir). ``Path.exists()`` follows the link and says False on a
    dangling one, so the foreign tree entered the surface (found by the
    DEF-673 failure-mode pass, first at ``tools/cc/sister_site_probe.py``'s
    own re-derivation of this rule, then traced back here). Stricter than
    :func:`is_own_git_repo`, which must stay False on that shape.
    """
    # `lexists` is exactly `exists() or is_symlink()`, minus the version-gated
    # raise through a parent that denies traversal (DEF-763; see
    # :func:`is_own_git_repo`).
    return os.path.lexists(path / ".git")


def safe_rglob(
    root: Path,
    pattern: str = "*",
    *,
    skip_nested_repos: bool = True,
    skip_dirs: Collection[str] | None = None,
) -> Iterator[Path]:
    """Yield every descendant of ``root`` whose final component matches
    ``pattern`` (``fnmatch``), WITHOUT following directory symlinks.

    Two safety prunes: this never follows a directory symlink, and — with
    ``skip_nested_repos=True`` (the default) — it never descends into an
    embedded git repository (a nested ``.git`` entry of any kind marks a
    foreign project, never part of THIS repo's surface, per
    :func:`has_git_entry`). Pass
    ``skip_nested_repos=False`` to walk into nested repos, restoring exact
    ``rglob`` parity. Yields files AND directories (not ``root`` itself); order
    is os.walk top-down, so callers needing the old sorted order should wrap in
    ``sorted(...)`` as they did with rglob.

    ``skip_dirs`` names directories the walk never enters and never yields,
    at any depth (:data:`DEPENDENCY_TREE_DIRS` is the usual argument). The
    prune happens DURING the walk: a filter applied to the results afterwards
    still reads every file of an installed dependency tree first. It names
    directories only, so a file that happens to carry one of the names is
    yielded. Nothing is skipped by default.
    """
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if skip_nested_repos:
            dirnames[:] = [
                d for d in dirnames if not has_git_entry(Path(dirpath) / d)
            ]
        if skip_dirs:
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        base = Path(dirpath)
        for name in (*dirnames, *filenames):
            if fnmatch.fnmatch(name, pattern):
                yield base / name


def _prefix_enters_nested_repo(root: Path, walk_root: Path) -> bool:
    """True when a glob *prefix* re-roots the walk INTO (or AT) an embedded git
    repo discovered below ``root``. :func:`safe_rglob` never prunes its own
    ``root`` argument (pointing it at a repo means "walk this repo"), so without
    this guard a pattern like ``vendor/**`` whose ``vendor/`` is an embedded repo
    would be walked in full — contradicting ``skip_nested_repos``. The caller's
    OWN ``root`` is never treated as foreign; only a nested repo on the prefix
    path below it is."""
    if walk_root == root:
        return False
    try:
        parts = walk_root.relative_to(root).parts
    except ValueError:
        return False
    cur = root
    for part in parts:
        cur = cur / part
        if is_own_git_repo(cur):
            return True
    return False


def safe_glob(
    root: Path, pattern: str, *, skip_nested_repos: bool = True
) -> Iterator[Path]:
    """Symlink-safe equivalent of ``root.glob(pattern)``.

    Handles the recursive ``"prefix/**/suffix"`` shape (which follows dir
    symlinks under bare ``glob`` on CPython < 3.13) by walking ``prefix`` with
    :func:`safe_rglob`; non-recursive patterns fall through to ``Path.glob``
    (which does not recurse, so it never descends into a symlinked subtree).

    Like :func:`safe_rglob`, the recursive path prunes embedded git repos found
    below ``root`` by default — INCLUDING when the pattern's own prefix names one
    (``"vendor/**"`` with ``vendor/`` an embedded repo yields nothing). The
    caller's own ``root`` is always walked. Pass ``skip_nested_repos=False`` to
    walk into nested repos. The non-recursive path never recurses, so the flag is
    inert there.

    This is the drop-in for a ``glob`` whose pattern is a *runtime variable*
    that may contain ``**`` — a site the AST recurrence-scanner cannot detect
    statically, so it must be converted by hand. See docs/FAILURE_MODES.md §2.8.
    """
    root = Path(root)
    if "**" not in pattern:
        yield from root.glob(pattern)
        return
    prefix, sep, suffix = pattern.partition("/**/")
    if sep:
        # "docs/**/*.md" -> walk docs/ for names matching *.md
        walk_root = root / prefix if prefix else root
        if skip_nested_repos and _prefix_enters_nested_repo(root, walk_root):
            return
        yield from safe_rglob(
            walk_root, suffix or "*", skip_nested_repos=skip_nested_repos
        )
        return
    # bare "**", "**/x", or "prefix/**" anchored at root (no '/**/' separator)
    head, _, tail = pattern.rpartition("**")
    walk_root = root / head.strip("/") if head.strip("/") else root
    if skip_nested_repos and _prefix_enters_nested_repo(root, walk_root):
        return
    leaf = tail.lstrip("/") or "*"
    # A BARE trailing "**" (tail empty: "**", "prefix/**") matches the anchor
    # directory itself too, mirroring Path.glob("**") / Path.glob("prefix/**");
    # safe_rglob yields only descendants, so add the anchor when it is a real dir.
    # An explicit "**/x" (tail non-empty, e.g. "**/*") does NOT include the anchor,
    # matching Path.glob("**/*") — gate on `tail`, not `leaf` (both collapse to "*").
    if not tail and walk_root.is_dir():
        yield walk_root
    yield from safe_rglob(walk_root, leaf, skip_nested_repos=skip_nested_repos)
