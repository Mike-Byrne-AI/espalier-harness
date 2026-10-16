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

**The set is the single home.** It grows only with a measured red. It is what
a walk that must see past git keeps out (a mutation guard snapshotting the
tree, the no-git fallback below); a contract over this tree's text reads git's
view instead (next paragraph).

**Git's view is what "this tree" means.** The worktree set was the first
measured member of a wider class: a filesystem walk sees everything git
ignores -- a maintainer's untracked script under the gitignored ``reports/``
(the encoding contract red on ``reports/c0-sort/run_sort.py``, measured
2026-10-14), ``docs/session-archive.md`` (which the memory prune grows on every
self-host box), a Windows copy-duplicate ``docs/X (1).md`` (``docs/* (*).md``),
a second checkout under ``.claude/worktrees/`` -- and a contract test reds on a
file no commit carries. :func:`checkout_files` is the population a live-tree
contract judges: the files git tracks (still on disk) plus the ones it neither
tracks nor ignores (``git ls-files --cached --others --exclude-standard``, the
``espalier.repo_mode.list_tracked_or_walked_files`` precedent), so a new command
is still judged before its commit -- the reason the index alone was refused
here before. Where the root has no ``.git`` of its own (an extracted release
archive) the precedent walks the filesystem minus the release-excluded state.
:func:`checkout_glob`, :func:`checkout_rglob` and :func:`checkout_iterdir` are
``Path.glob`` / ``rglob`` / ``iterdir`` over that population, :func:`keep_in_checkout`
filters a scanner's result to it (the scanners' own walks are the adopter's
and stay as they are), and :func:`copy_checkout` copies it.
``tests/_live_tree_census.py`` derives every enumeration of the checkout in
``tests/`` and ``tests/test_utf8_text_io.py::TestLiveTreeWalkRatchet`` ratchets
it.

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

import fnmatch
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from espalier._safe_walk import has_git_entry

#: This checkout: the root a live-tree helper judges when no other is given.
REPO_ROOT = Path(__file__).resolve().parent.parent

#: Consecutive path components, relative to the repo root, under which nothing
#: is this tree's text. One member, measured: Claude Code's linked worktrees
#: (``claude --worktree``; the directory is gitignored since 2026-10-08, which a
#: filesystem walk does not consult).
EXCLUDED_DIR_PARTS: tuple[tuple[str, ...], ...] = ((".claude", "worktrees"),)

#: Directory names skipped at any depth by every walk and copy of the live
#: checkout: bytecode caches. No tool under test writes one on purpose, and a
#: test worker's first import of a module compiles one inside another test's
#: window -- the live-tree isolation manifest read that as the tool's mutation
#: and reddened required cells twice on 2026-10-16 (DEF-5009: run 38874646235,
#: four `tests/__pycache__/test_*.cpython-314.pyc`; run 38878802493, two
#: `bench/sandbox_read_drive/__pycache__/*.cpython-313.pyc`). Bytecode is never
#: a copy's to carry either: the copy compiles its own.
SKIPPED_DIR_NAMES: frozenset[str] = frozenset({"__pycache__"})


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
    the last member of an :data:`EXCLUDED_DIR_PARTS` run whose leading
    members end ``directory`` -- ``worktrees`` under a ``.claude`` -- and a
    :data:`SKIPPED_DIR_NAMES` member at any depth. The name
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
    return nested_repo_names(directory, names) | by_name | (SKIPPED_DIR_NAMES & set(names))


def live_tree_copy_ignore(*patterns: str) -> Callable[[str, list[str]], set[str]]:
    """``shutil.ignore_patterns(*patterns)`` plus :func:`live_tree_skip_names`:
    the ``ignore`` for a copy of the live checkout. A copy that leaves ``.git``
    out without it erases a linked worktree's boundary (the module docstring)."""
    by_pattern = shutil.ignore_patterns(*patterns)

    def ignore(directory: str, names: list[str]) -> set[str]:
        return set(by_pattern(directory, names)) | live_tree_skip_names(directory, names)

    return ignore


# ── Git's view of the checkout ───────────────────────────────────────────────

_LIVE_VIEW: dict[str, tuple[str, ...]] = {}
_IGNORED_BASE: dict[tuple[str, str], bool] = {}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    from tests._git_oracle import GitAnswerUnavailable, _git_env

    try:
        return subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=root, env=_git_env(),
                              capture_output=True, timeout=30)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise GitAnswerUnavailable(f"git could not answer about {root}: {exc}") from exc


def _git_listing(root: Path) -> list[str]:
    """``git ls-files -z --cached --others --exclude-standard`` at ``root``,
    asked with the repository-selecting overrides stripped
    (``tests/_git_oracle.py``) and refused unless git answers about ``root``
    itself. A refusal raises: a view that quietly fell back to the filesystem
    would judge what git ignores again, and be cached for the session."""
    from tests._git_oracle import GitAnswerUnavailable, owns_its_worktree

    if not owns_its_worktree(root):
        raise GitAnswerUnavailable(f"git does not answer about {root} as its own worktree")
    proc = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if proc.returncode != 0:
        raise GitAnswerUnavailable(
            f"git ls-files at {root} exited {proc.returncode}: {proc.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return [rel for rel in proc.stdout.decode("utf-8", "replace").split("\0") if rel]


def _view(root: Path) -> tuple[str, ...]:
    """The repo-relative POSIX paths of git's view of ``root``, sorted: tracked
    files still on disk plus untracked files git does not ignore, never a file
    below a nested checkout.

    A root with a ``.git`` of its own -- this checkout, or a planted
    repository -- is asked through :func:`_git_listing`, which raises rather
    than degrade. This checkout with no ``.git`` (an extracted release archive)
    is read through the precedent, ``espalier.repo_mode.list_tracked_or_walked_files``,
    whose filesystem walk leaves the release-excluded state out. A planted
    tree with no git is a plain walk that leaves nested repositories and the
    worktree pair out (:func:`live_tree_skip_names`): the release-excluded
    prune is an archive root's, and judged from a planted root it dropped a
    planted ``TP-*.md``. This checkout's view is cached per process: a test
    session judges the tree it started on, so a file added mid-run is not seen
    and one removed mid-run is dropped at read time (the helpers below return
    only paths that still exist)."""
    root = Path(root).resolve()
    key = os.path.normcase(str(root))
    live = key == os.path.normcase(str(REPO_ROOT))
    if live and key in _LIVE_VIEW:
        return _LIVE_VIEW[key]
    if has_git_entry(root):
        listed = _git_listing(root)
    elif live:
        from espalier.repo_mode import list_tracked_or_walked_files

        listed, _source = list_tracked_or_walked_files(root, include_untracked=True)
    else:
        listed = []
        for dirpath, dirnames, filenames in os.walk(root):
            skip = live_tree_skip_names(dirpath, dirnames)
            dirnames[:] = [d for d in dirnames if d not in skip]
            rel_dir = Path(dirpath).relative_to(root).as_posix()
            listed += [f if rel_dir == "." else f"{rel_dir}/{f}" for f in filenames]
    nested: dict[str, bool] = {}

    def in_a_nested_checkout(rel: str) -> bool:
        """Below a directory holding a ``.git`` of its own, or the worktree
        pair: another checkout's file, whatever git says of it (git lists one
        whose gitlink target is gone as plain untracked files)."""
        parts = rel.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            d = "/".join(parts[:i])
            if d not in nested:
                nested[d] = has_git_entry(root / d) or is_under_excluded_dir(root / d / "_", root)
            if nested[d]:
                return True
        return False

    view = tuple(sorted({
        rel for rel in listed
        if rel and not rel.endswith("/") and (root / rel).is_file() and not in_a_nested_checkout(rel)
    }))
    if live:
        _LIVE_VIEW[key] = view
    return view


def _root_of(base: Path, root: Path | None) -> tuple[Path, str]:
    """``(root, prefix)``: the checkout ``base`` lies in and ``base``'s path
    inside it ('' for the root itself). Without ``root``: this checkout when
    ``base`` is inside it, else the nearest directory at or above ``base``
    holding a ``.git`` of its own (a planted repository), else ``base`` itself
    (a planted tree with no git: the filesystem fallback walks it). A planted
    tree under ANOTHER repository's worktree (a temp directory inside a
    git-tracked home) would read that repository's view: pass ``root=``."""
    base = Path(base).resolve()
    if root is None:
        try:
            base.relative_to(REPO_ROOT)
            root = REPO_ROOT
        except ValueError:
            root = next((d for d in (base, *base.parents) if has_git_entry(d)), base)
    root = Path(root).resolve()
    try:
        rel = base.relative_to(root)
    except ValueError:
        raise ValueError(f"{base} is not inside the checkout {root}") from None
    return root, rel.as_posix() if rel.parts else ""


def _base_is_ignored(root: Path, prefix: str) -> bool:
    from tests._git_oracle import GitAnswerUnavailable

    key = (os.path.normcase(str(root)), os.path.normcase(prefix))
    if key not in _IGNORED_BASE:
        proc = _git(root, "check-ignore", "-q", "--", prefix)
        if proc.returncode not in (0, 1):
            raise GitAnswerUnavailable(f"git check-ignore {prefix} at {root} exited {proc.returncode}")
        _IGNORED_BASE[key] = proc.returncode == 0
    return _IGNORED_BASE[key]


def _ignored(root: Path, prefix: str) -> bool:
    return bool(prefix) and has_git_entry(root) and _base_is_ignored(root, prefix)


def ignored_by_git(path: Path, *, root: Path | None = None) -> bool:
    """Whether git ignores ``path`` in its checkout, so that git's view holds
    nothing under it. The self-host tree keeps folders out of git by design
    (``task-packs/Done/``, ``Merged/`` and ``Scrapped/``); a walk of one reads
    the filesystem, marked `# live-tree: ok -- <why>`, and every other folder
    reads git's view. False for the checkout's root and on a tree with no git.

    Only for a folder git ignores by design whose files are this tree's own
    records. A folder of build or scratch output (``reports/``, ``build/``) is
    never read this way: its walk refuses, which is what the refusal is for."""
    return _ignored(*_root_of(path, root))


def plant_self_host_packs(root: Path) -> Path:
    """A repository at ``root`` whose ``task-packs/`` is shaped like a self-host
    checkout's: an in-flight pack (tracked), an untracked draft beside it, a
    deferred pack, and a landed pack in the gitignored ``Done/``. Returns
    ``root / "task-packs"``.

    Its ``.gitignore`` is this checkout's own, so the plant ignores what the
    real tree ignores; where git cannot build it, or the real tree stops
    ignoring ``Done/``, it raises instead of planting a shape that proves
    nothing."""
    root.mkdir(parents=True, exist_ok=True)
    rules = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    (root / ".gitignore").write_bytes(("\n".join(rules) + "\n").encode("utf-8"))
    packs = root / "task-packs"
    for rel in ("TP-2-in-flight.md", "TP-3-draft.md", "Deferred/TP-4-parked.md", "Done/TP-1-landed.md"):
        (packs / rel).parent.mkdir(parents=True, exist_ok=True)
        (packs / rel).write_bytes(f"# {rel.rsplit('/', 1)[-1][:-3]}\n".encode("utf-8"))
    for args in (("init", "-q"), ("add", ".gitignore", "task-packs/TP-2-in-flight.md", "task-packs/Deferred/TP-4-parked.md")):
        done = _git(root, *args)
        if done.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed planting {root}: {done.stderr!r}")
    if not ignored_by_git(packs / "Done") or ignored_by_git(packs / "Deferred"):
        raise RuntimeError(f"{REPO_ROOT / '.gitignore'} no longer ignores task-packs/Done/ while tracking "
                           "Deferred/, so the self-host shape this plant reproduces is gone")
    return packs


def _members(base: Path, root: Path | None) -> tuple[Path, str, list[str]]:
    root, prefix = _root_of(base, root)
    view = _view(root)
    if _ignored(root, prefix):
        raise ValueError(
            f"{prefix}/ is ignored by git in {root}, so git's view holds nothing under it and a walk "
            "of it would judge nothing. A walk of gitignored state (a guard watching reports/, the "
            "session state under .espalier-state/) reads the filesystem on purpose: leave the walk as "
            "it is and mark it `# live-tree: ok -- <why>`."
        )
    if not prefix:
        return root, prefix, list(view)
    lead = os.path.normcase(prefix + "/")
    return root, prefix, [rel[len(prefix) + 1:] for rel in view if os.path.normcase(rel[:len(lead)]) == lead]


def _segments_match(parts: list[str], pats: list[str]) -> bool:
    """``Path.glob`` segment matching: ``**`` takes zero or more whole
    segments, every other pattern segment one, case as the platform's paths."""
    if not pats:
        return not parts
    if pats[0] == "**":
        return any(_segments_match(parts[i:], pats[1:]) for i in range(len(parts) + 1))
    if not parts:
        return False
    return fnmatch.fnmatchcase(os.path.normcase(parts[0]), os.path.normcase(pats[0])) \
        and _segments_match(parts[1:], pats[1:])


def _path_order(rel: str) -> list[str]:
    """``sorted(Path)``'s order: part by part, case-folded where the platform's
    paths are (Windows)."""
    return [os.path.normcase(part) for part in rel.split("/")]


def checkout_glob(base: Path, pattern: str, *, root: Path | None = None) -> Iterator[Path]:
    """``base.glob(pattern)`` over git's view of the checkout: the files, and the
    directories holding one, whose path below ``base`` matches ``pattern``
    (``**`` for any depth), in ``sorted(Path)`` order; an iterator, as
    ``Path.glob`` returns. ``root`` names the checkout when inference would
    not (see :func:`_root_of`). A ``base`` git ignores raises (:func:`_members`).
    Where pathlib differs, this does not follow it: a bare trailing ``**``
    matches files too (pathlib's yields directories only), a trailing ``/`` is
    dropped (pathlib's keeps directories only), and an empty directory is
    never a match. No routed site spells either pattern."""
    base = Path(base)
    _root, _prefix, rels = _members(base, root)
    pats = [p for p in pattern.replace("\\", "/").split("/") if p]
    candidates: set[str] = set(rels)
    for rel in rels:
        parts = rel.split("/")
        candidates.update("/".join(parts[:i]) for i in range(1, len(parts)))
    hits = sorted((c for c in candidates if _segments_match(c.split("/"), pats)), key=_path_order)
    return iter([base / c for c in hits if (base / c).exists()])


def checkout_rglob(base: Path, pattern: str, *, root: Path | None = None) -> Iterator[Path]:
    """``base.rglob(pattern)`` over git's view of the checkout."""
    return checkout_glob(base, "**/" + pattern.replace("\\", "/").lstrip("/"), root=root)


def checkout_iterdir(base: Path, *, root: Path | None = None) -> Iterator[Path]:
    """``base.iterdir()`` over git's view: the files directly under ``base`` and
    the subdirectories that hold one (an empty or wholly ignored directory is
    not part of the tree git sees)."""
    return checkout_glob(base, "*", root=root)


def checkout_files(base: Path = REPO_ROOT, *, root: Path | None = None) -> list[Path]:
    """Every file of git's view under ``base`` (default: the whole checkout),
    in ``sorted(Path)`` order."""
    _root, _prefix, rels = _members(Path(base), root)
    return [Path(base) / rel for rel in sorted(rels, key=_path_order) if (Path(base) / rel).is_file()]


#: The listings above by name: the spelling every tests/ walk takes once the
#: live-tree census routes it. A gate that finds a listing call by its name
#: reads this (tests/test_package_resource_parity.py's `.claude`-kind walk,
#: tests/test_ledger_fragments.py's record-read census, the doc-sweep regex in
#: tests/test_marker_taxonomy.py, the corpus-count regex in
#: tests/test_corpus_count_parity.py); a listing added here without joining it
#: reds tests/test_utf8_text_io.py::TestCheckoutView.
LISTING_HELPERS: tuple[str, ...] = ("checkout_glob", "checkout_rglob", "checkout_iterdir", "checkout_files")


#: The fields a scanner's finding names its file by, and the ones it nests the
#: finding's subject under (the canon verifier's ``claim``, the freshness
#: scanner's ``fragment``), read in this order. A finding type that names its
#: file in none of them makes :func:`keep_in_checkout` raise, so the next new
#: field name is a red, never a silent keep.
_PATH_FIELDS = ("path", "file", "rel", "relpath", "filename", "source_path", "surface_path", "writer_path",
                "caller_path")
_NESTED_FIELDS = ("claim", "fragment")


def _path_of(item: Any, depth: int = 0) -> str | None:
    if isinstance(item, (str, os.PathLike)):
        return os.fspath(item)
    if isinstance(item, dict):
        for k in _PATH_FIELDS:
            if isinstance(item.get(k), (str, os.PathLike)):
                return os.fspath(item[k])
        return None
    for k in _PATH_FIELDS:
        v = getattr(item, k, None)
        if isinstance(v, (str, os.PathLike)):
            return os.fspath(v)
    if depth < 2:
        for k in _NESTED_FIELDS:
            v = getattr(item, k, None)
            if v is not None:
                return _path_of(v, depth + 1)
    return None


def _member_test(root: Path | None) -> Callable[[str | os.PathLike], bool]:
    """A predicate over paths (absolute, or relative to the root): is it a file
    of git's view? The view is read once, here."""
    root_path = Path(root).resolve() if root is not None else REPO_ROOT
    members = frozenset(os.path.normcase(r) for r in _view(root_path))

    def test(path: str | os.PathLike) -> bool:
        p = Path(path)
        if p.is_absolute():
            try:
                p = p.resolve().relative_to(root_path)
            except ValueError:
                return False
        return os.path.normcase(p.as_posix()) in members

    return test


def in_checkout(path: str | os.PathLike, *, root: Path | None = None) -> bool:
    """Whether ``path`` (absolute, or relative to the root) is a file of git's
    view of the checkout."""
    return _member_test(root)(path)


def keep_in_checkout(result: Any, *, root: Path | None = None) -> Any:
    """A scanner's result over the live tree, kept to the files git's view
    holds. A finding is dropped only when it names an existing file under the
    root that git's view leaves out. It is kept when it is in the view, when it
    is a plain string that names no file (a pattern, a message), or when it
    carries no path beside findings that do. It RAISES when a finding names a
    path that is not a file under the root (a scan of another tree routed
    without ``root=``, a path relative to another base), and when no finding
    in a non-empty list names its file in a field this reads
    (:data:`_PATH_FIELDS`): either would otherwise filter silently, and the
    hiding direction is the one a contract cannot afford.

    Shapes: a list or tuple of findings; a tuple of such lists (``(findings,
    skipped)``), filtered element by element; a dict report, copied with each
    list value filtered and every other value as the scanner wrote it (a count
    in it is the scanner's count: a test that judges a count reads the list's
    length, or the scanner's ``collect_*``, through here). A bare number cannot
    be filtered and raises. The scanner's own walk is untouched -- an adopter's
    scan is the adopter's -- so this is the test side's view of it."""
    root_path = Path(root).resolve() if root is not None else REPO_ROOT
    member = _member_test(root)

    def kept(item) -> bool:
        p = _path_of(item)
        if p is None:
            return True
        q = Path(p)
        absolute = q if q.is_absolute() else root_path / q
        if isinstance(item, str) and not absolute.is_file():
            return True
        try:
            rel = absolute.resolve().relative_to(root_path)
        except ValueError:
            raise ValueError(f"a finding names {p}, outside the root {root_path}: pass the scan's root as root=") from None
        if not (root_path / rel).is_file():
            raise ValueError(f"a finding names {p}, which is not a file under {root_path}: "
                             "a path relative to another base, or the wrong root=")
        return member(rel)

    def keep(items) -> list:
        items = list(items)
        objects = [i for i in items if not isinstance(i, (str, bytes, int, float, bool)) and i is not None]
        if objects and all(_path_of(i) is None for i in objects):
            raise TypeError(
                f"none of the {len(objects)} {type(objects[0]).__name__} findings names its file in a field "
                f"keep_in_checkout reads ({', '.join(_PATH_FIELDS)}; nested under {', '.join(_NESTED_FIELDS)}): "
                "add its field to _PATH_FIELDS")
        return [i for i in items if kept(i)]

    if isinstance(result, tuple) and result and all(isinstance(r, (list, tuple)) for r in result):
        return tuple(type(r)(keep(r)) for r in result)
    if isinstance(result, (list, tuple)):
        return type(result)(keep(result))
    if isinstance(result, dict):
        return {k: keep(v) if isinstance(v, list) else v for k, v in result.items()}
    raise TypeError(f"keep_in_checkout cannot filter a {type(result).__name__}; route the call that lists files")


_COPIES: dict[tuple[str, tuple[str, ...]], Any] = {}


def checkout_copy(patterns: Iterable[str], *, src: Path = REPO_ROOT) -> Path:
    """A copy of the files git's view of ``src`` holds under ``patterns``
    (``Path.glob`` patterns, ``**`` for any depth), at the same places in a
    temporary directory: made once per process, removed at a clean exit (a
    killed run leaves its ``checkout-copy-*`` folder in the system temp
    directory). For a walker
    that raises on what it reads before a filter could run (the freshness
    scanner on a duplicate fragment id), so ``keep_in_checkout`` cannot cut its
    result; derive ``patterns`` from the walker's own roster, so a pattern it
    gains is copied too."""
    import tempfile

    key = (os.path.normcase(str(Path(src).resolve())), tuple(patterns))
    if key not in _COPIES:
        holder = tempfile.TemporaryDirectory(prefix="checkout-copy-")
        dst = Path(holder.name)
        for pattern in key[1]:
            for path in checkout_glob(Path(src), pattern):
                if path.is_file():
                    target = dst / path.relative_to(src)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
        _COPIES[key] = holder
    return Path(_COPIES[key].name)


def copy_checkout(src: Path, dst: Path, *, ignore: Callable[[str, list[str]], Iterable[str]] | None = None,
                  root: Path | None = None) -> Path:
    """``shutil.copytree(src, dst, ignore=ignore)`` over git's view: copy the
    files of the checkout below ``src`` (``.git`` is never among them) to the
    same places under ``dst``, metadata kept. ``ignore`` is a copytree-style
    callback, asked per directory as copytree would ask it; a name it returns is
    left out with everything below it. Returns ``dst``. A missing ``src``
    raises ``FileNotFoundError``, as copytree's does: an empty copy would
    leave the caller asserting over nothing. Unlike copytree, ``dst`` may
    already exist, and what it holds stays."""
    src = Path(src)
    dst = Path(dst)
    if not src.is_dir():
        raise FileNotFoundError(f"copy_checkout: no directory at {src}")
    _root, _prefix, rels = _members(src, root)
    skipped: dict[str, set[str]] = {}
    dst.mkdir(parents=True, exist_ok=True)
    for rel in rels:
        parts = rel.split("/")
        if ignore is not None and _ignored_on_the_way(src, parts, ignore, skipped):
            continue
        if not src.joinpath(*parts).is_file():
            continue
        target = dst.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src.joinpath(*parts), target)
    return dst


def _ignored_on_the_way(src: Path, parts: list[str], ignore, cache: dict[str, set[str]]) -> bool:
    for depth in range(len(parts)):
        directory = str(src.joinpath(*parts[:depth])) if depth else str(src)
        if directory not in cache:
            try:
                names = sorted(os.listdir(directory))
            except OSError:
                names = []
            cache[directory] = set(ignore(directory, names))
        if parts[depth] in cache[directory]:
            return True
    return False
