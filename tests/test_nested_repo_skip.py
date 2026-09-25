"""TP-277: repo-root filesystem walkers must not descend into an embedded
(nested) git repository.

An untracked nested git repo left in the tree (a separate, foreign project) is
NOT part of THIS repo's surface. The release-archive builders, the fixture
copy, and the self-check scanners each walk the raw working tree; every one of
them must treat a nested ``.git`` as a boundary. This module pins that contract
end to end:

* 2-A/2-B — neither release-zip builder includes foreign nested-repo files.
* 3-A — the ``initialized_repo_root`` copy mechanism no longer chokes on an
  *empty* nested repo (which breaks ``git add -A`` with exit 128).
* 4-A — a single enumerating contract test asserts EVERY repo-root walker
  excludes a planted nested repo, so a future walker added without the skip reds
  here (the anti-whack-a-mole gate).
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from espalier._safe_walk import is_own_git_repo
from espalier.release_pack import create_release_zip

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_build_script():
    """Load scripts/build_release_archive.py by file path (it is not a package)."""
    candidate = REPO_ROOT / "scripts" / "build_release_archive.py"
    spec = importlib.util.spec_from_file_location("_build_release_archive_nested", candidate)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise FileNotFoundError(candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plant_tree_with_nested_repo(root: Path) -> None:
    """A minimal working tree that owns ``keep.py`` + a root-level ``.env``
    (an untracked secret THIS repo's walkers must still see), plus a foreign
    nested git repo whose content must never be walked."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "keep.py").write_text("x = 1\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=root-level\n", encoding="utf-8")  # this repo's own secret
    nested = root / "adopt2"
    (nested / ".git").mkdir(parents=True)  # embedded repo -> foreign project
    (nested / "foreign.py").write_text("y = 2\n", encoding="utf-8")
    (nested / ".env").write_text("SECRET=foreign\n", encoding="utf-8")
    (nested / ".claude").mkdir()
    (nested / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")


# --- 2-A: scripts/build_release_archive.py::_walk_repo --------------------

def test_build_walk_repo_skips_nested_repo(tmp_path):
    build = _load_build_script()
    root = tmp_path / "tree"
    _plant_tree_with_nested_repo(root)

    yielded = {p.relative_to(root).as_posix() for p in build._walk_repo(root)}

    # this repo's own content — including a root-level secret — is still walked
    # (the untracked-secret detection the walker deliberately preserves).
    assert "keep.py" in yielded
    assert ".env" in yielded
    # the whole foreign nested repo is excluded — not just its .git.
    assert not any(rel == "adopt2" or rel.startswith("adopt2/") for rel in yielded), (
        f"foreign nested-repo files leaked into the archive walk: "
        f"{sorted(r for r in yielded if r.startswith('adopt2'))}"
    )


# --- 2-B: espalier/release_pack.py::create_release_zip --------------------

def test_create_release_zip_excludes_nested_repo_members(tmp_path):
    root = tmp_path / "tree"
    _plant_tree_with_nested_repo(root)
    # adopt2/foreign.py classifies as `public`, so ONLY the nested-repo skip
    # keeps it out — the denylist would not (that is the whole point: a foreign
    # nested file that does not match the denylist would otherwise ship).
    out = tmp_path / "out.zip"
    create_release_zip(root, out)

    with zipfile.ZipFile(out) as zf:
        members = set(zf.namelist())

    assert "keep.py" in members  # this repo's own public content still ships
    assert not any(m == "adopt2" or m.startswith("adopt2/") for m in members), (
        f"foreign nested-repo files shipped in the release zip: "
        f"{sorted(m for m in members if m.startswith('adopt2'))}"
    )


# --- 3-A: tests/conftest.py::initialized_repo_root copy mechanism ----------
#
# The fixture copytree's the source tree then runs `git add -A` in the copy.
# An EMPTY nested repo (its own `.git`, no commit) breaks `git add -A` with
# exit 128 ("does not have a commit checked out"), erroring every test that
# uses the fixture. The `_ignore` skip below is the exact mechanism the fixture
# now uses; we drive the copy+init+add path on a tmp tree (never the real repo
# root, per the pack) and prove the skip is what averts the crash.

def _ignore_factory(*, skip_nested: bool):
    def _ignore(path: str, names: list[str]) -> set[str]:
        skip: set[str] = set()
        if skip_nested:
            for n in names:
                if is_own_git_repo(Path(path) / n):
                    skip.add(n)
        return skip
    return _ignore


def _drive_copy_and_add(src: Path, dst: Path, *, skip_nested: bool) -> None:
    """Replicate the fixture's copytree -> git init -> git add -A path."""
    shutil.copytree(src, dst, ignore=_ignore_factory(skip_nested=skip_nested))
    subprocess.run(["git", "init", "-q"], cwd=str(dst), check=True)
    subprocess.run(
        ["git", "add", "-A"], cwd=str(dst), check=True, capture_output=True
    )


def _src_tree_with_empty_nested_repo(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    empty_repo = src / "empty_repo"
    empty_repo.mkdir()
    # A real but EMPTY nested repo (valid .git, zero commits) — the exact shape
    # that produced the observed exit-128 in TP-275.
    subprocess.run(["git", "init", "-q"], cwd=str(empty_repo), check=True)
    return src


def test_fixture_copy_without_skip_chokes_on_empty_nested_repo(tmp_path):
    """Earn-the-red: the pre-fix mechanism (no nested-repo skip) copies the
    empty nested repo, and `git add -A` dies with exit 128."""
    src = _src_tree_with_empty_nested_repo(tmp_path)
    with pytest.raises(subprocess.CalledProcessError) as exc:
        _drive_copy_and_add(src, tmp_path / "dst_broken", skip_nested=False)
    assert exc.value.returncode == 128


def test_fixture_copy_with_skip_survives_empty_nested_repo(tmp_path):
    """Post-fix: the nested-repo skip omits the embedded repo, so the copy is
    clean and `git add -A` succeeds; the nested repo is absent from the copy."""
    src = _src_tree_with_empty_nested_repo(tmp_path)
    dst = tmp_path / "dst_ok"
    _drive_copy_and_add(src, dst, skip_nested=True)  # must not raise
    assert (dst / "pkg" / "mod.py").exists()
    assert not (dst / "empty_repo").exists()


# --- 4-A: the enumerating contract test (anti-whack-a-mole gate) -----------
#
# EVERY repo-root scanner that walks the raw working tree must exclude a planted
# nested repo. Adding a new repo-root walker without the skip reds here. Walkers
# routed through safe_rglob inherit the skip by default (Option B); the raw
# os.walk / rglob walkers (analyze, repo_mode, pre_release) are pruned inline.

def _plant_rich_nested_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "own.py").write_text("a = 1\n", encoding="utf-8")
    (root / "own.md").write_text("# own\n", encoding="utf-8")
    nested = root / "adopt2"
    (nested / ".git").mkdir(parents=True)  # embedded repo -> foreign project
    (nested / "foreign.py").write_text("b = 2\n", encoding="utf-8")
    (nested / "foreign.md").write_text("# foreign\n", encoding="utf-8")
    (nested / "__pycache__").mkdir()
    (nested / "__pycache__" / "cache.pyc").write_text("", encoding="utf-8")
    (nested / "blueprint.md").write_text("internal-classified\n", encoding="utf-8")


def _reflection_rels(root):
    from espalier.reflection import _iter_markdown_files
    return [p.relative_to(root).as_posix() for p in _iter_markdown_files(root)]


def _strengthen_rels(root):
    from espalier.strengthen import _iter_repo_py
    return [rel for _p, rel in _iter_repo_py(root, ())]


def _scope_walker_rels(root):
    from espalier.scope_walker import _iter_scannable_lines
    return [rel for rel, _ln, _line in _iter_scannable_lines(root)]


def _analyze_rels(root):
    from espalier.analyze import _iter_files
    return [p.relative_to(root).as_posix() for p in _iter_files(root)]


def _repo_mode_rels(root):
    from espalier.repo_mode import list_repo_files_via_filesystem
    return list_repo_files_via_filesystem(root)


def _pre_release_transient_rels(root):
    from espalier.pre_release import _find_transient_noise
    return _find_transient_noise(root)


def _pre_release_leaks_rels(root):
    from espalier.pre_release import _find_internal_leaks
    return _find_internal_leaks(root)


# (name, fn, own_marker): own_marker is a repo-own path each walker MUST still
# surface (guards the OPPOSITE regression — over-pruning that drops own content).
# The two pre_release reporters only emit transient/internal paths (own.py/own.md
# are neither), so they have no own-content marker — exclusion-only.
REPO_ROOT_WALKERS = [
    ("reflection._iter_markdown_files", _reflection_rels, "own.md"),
    ("strengthen._iter_repo_py", _strengthen_rels, "own.py"),
    ("scope_walker._iter_scannable_lines", _scope_walker_rels, "own.py"),
    ("analyze._iter_files", _analyze_rels, "own.py"),
    ("repo_mode.list_repo_files_via_filesystem", _repo_mode_rels, "own.py"),
    ("pre_release._find_transient_noise", _pre_release_transient_rels, None),
    ("pre_release._find_internal_leaks", _pre_release_leaks_rels, None),
]


def test_all_repo_root_walkers_skip_nested_repo(tmp_path):
    root = tmp_path / "tree"
    _plant_rich_nested_repo(root)

    leaks: dict[str, list[str]] = {}
    over_pruned: dict[str, str] = {}
    for name, fn, own_marker in REPO_ROOT_WALKERS:
        rels = {str(r).replace("\\", "/") for r in fn(root)}
        nested = sorted(r for r in rels if r == "adopt2" or r.startswith("adopt2/"))
        if nested:
            leaks[name] = nested
        if own_marker is not None and own_marker not in rels:
            over_pruned[name] = own_marker

    assert not leaks, "repo-root walkers leaked foreign nested-repo content:\n" + "\n".join(
        f"  {name}: {found}" for name, found in leaks.items()
    )
    # Guard the opposite regression: a walker that over-prunes and drops this
    # repo's OWN content would otherwise pass an exclusion-only assertion.
    assert not over_pruned, "repo-root walkers dropped this repo's OWN content (over-prune):\n" + "\n".join(
        f"  {name}: missing {marker}" for name, marker in over_pruned.items()
    )


def test_bare_os_walk_walkers_prune_nested_repos():
    """Mechanical anti-whack-a-mole gate (the durable form of the enumeration
    above). Every ``for ... in os.walk(...)`` loop in espalier/ must either prune
    embedded repos OR carry a ``# nested-repo-ok <reason>`` pragma. Bare
    ``os.walk`` is the ONE recursive-walk shape the recurrence scanner does NOT
    flag (it flags ``followlinks=True`` and raw ``rglob``/``glob``), so a future
    repo-root walker written with a bare ``os.walk`` and no prune would silently
    reintroduce the nested-repo class and evade the hand-list above. Walkers are
    DISCOVERED via AST (not hand-listed) with per-bucket floors guarding a vacuous
    pass. Split-bucket prune markers (TP-389): engine walkers prune via
    ``is_own_git_repo``; scanner walkers (``espalier/scanners/``) are stdlib-only
    and prune via the inline ``_skip_nested_repos`` helper — both accepted, each
    only in its own bucket. ``espalier/_vendor/`` stays excluded (a tools/cc
    byte-mirror, governed there)."""
    import ast

    espalier_dir = REPO_ROOT / "espalier"
    pragma = "# nested-repo-ok"
    # Split-bucket (TP-389): engine walkers prune via `has_git_entry` (the
    # PRUNE predicate: any `.git` entry, a dangling symlink included -- DEF-673
    # third failure-mode pass) or the stricter `is_own_git_repo` (both imported
    # from _safe_walk); scanner walkers are stdlib-only and prune via the inline
    # `_skip_nested_repos` helper. Each bucket accepts ONLY its own marker(s),
    # so an engine walker cannot "pass" on a scanner-only name (or vice-versa).
    # `espalier/_vendor/` stays excluded (byte-mirror of tools/cc, governed there
    # + pinned by test_vendor_cc_parity).
    discovered: list[str] = []
    scanner_discovered: list[str] = []
    unguarded: list[str] = []
    for py in sorted(espalier_dir.rglob("*.py")):
        rel = py.relative_to(REPO_ROOT).as_posix()
        if "espalier/_vendor/" in rel:
            continue
        is_scanner = "espalier/scanners/" in rel
        markers = (
            ("_skip_nested_repos",) if is_scanner
            else ("has_git_entry", "is_own_git_repo")
        )
        text = py.read_text(encoding="utf-8")
        lines = text.splitlines()
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.For):
                continue
            it = node.iter
            if not (
                isinstance(it, ast.Call)
                and isinstance(it.func, ast.Attribute)
                and it.func.attr == "walk"
                and isinstance(it.func.value, ast.Name)
                and it.func.value.id == "os"
            ):
                continue
            site = f"{rel}:{node.lineno}"
            (scanner_discovered if is_scanner else discovered).append(site)
            walk_line = it.lineno  # 1-based
            annotated = any(
                0 <= i < len(lines) and pragma in lines[i]
                for i in (walk_line - 1, walk_line - 2)
            )
            pruned = any(
                (isinstance(n, ast.Name) and n.id in markers)
                or (isinstance(n, ast.Attribute) and n.attr in markers)
                for stmt in node.body
                for n in ast.walk(stmt)
            )
            if not (annotated or pruned):
                unguarded.append(site)

    assert len(discovered) >= 3, (
        f"os.walk discovery floor breached (engine): found {discovered} (expected "
        ">=3: _safe_walk.safe_rglob, analyze._iter_files, repo_mode._walk_with_pruning)"
    )
    assert len(scanner_discovered) >= 11, (
        f"os.walk discovery floor breached (scanners): found {scanner_discovered} "
        "(expected >=11: 5 family-1 iter-walkers + 6 family-2 _safe_rglob sites — an "
        "exact floor mirroring the engine bucket's >=3; bump it deliberately when a "
        "scanner walker is added or removed)"
    )
    assert not unguarded, (
        "bare os.walk loop(s) in espalier/ missing the nested-repo prune. Engine "
        "walkers add `dirnames[:] = [d for d in dirnames if not "
        "is_own_git_repo(Path(dirpath) / d)]`; scanner walkers (stdlib-only) call "
        "`_skip_nested_repos(dirpath, dirnames)`; or add a `# nested-repo-ok "
        "<reason>` pragma if the walk genuinely cannot meet a nested repo:\n  "
        + "\n  ".join(unguarded)
    )
