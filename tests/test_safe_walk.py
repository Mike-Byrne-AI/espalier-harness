"""TP-194: safe_rglob / safe_glob must not follow directory symlinks (the class fix).

This pins the symlink-safe contract of the helpers and guards against a
regression to bare ``rglob``/recursive ``glob`` (which would follow directory
symlinks and crash on an adopter loop). The loop tests earn their red only on
CPython 3.10-3.12 (where bare ``rglob`` raises ``OSError(ELOOP)`` on a loop);
on 3.13+ they are no-op-safe because the safe default already applies. The
pattern-matching assertions are version-agnostic.
"""
# pytest-marker: default-unit  (pure-function helper tests; not a grandfather entry)
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from espalier._safe_walk import has_git_entry, is_own_git_repo, safe_glob, safe_rglob

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- TP-277: nested-repo (embedded git repo) skip -------------------------

def test_is_own_git_repo_false_for_plain_dir(tmp_path):
    plain = tmp_path / "r"
    plain.mkdir()
    assert is_own_git_repo(plain) is False


def test_is_own_git_repo_true_for_git_directory(tmp_path):
    r = tmp_path / "r"
    (r / ".git").mkdir(parents=True)
    assert is_own_git_repo(r) is True


def test_is_own_git_repo_true_for_gitlink_file(tmp_path):
    # worktree / submodule shape: `.git` is a FILE (`gitdir: ...` pointer),
    # not a directory — must still count as its own repo (per espalier.fuse).
    r = tmp_path / "r"
    r.mkdir()
    (r / ".git").write_text("gitdir: /elsewhere/.git/worktrees/r\n", encoding="utf-8")
    assert is_own_git_repo(r) is True


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_a_dangling_git_symlink_splits_the_two_predicates(tmp_path):
    """The two questions diverge on exactly this shape (DEF-673 failure-mode
    pass): a PRUNE must treat a removed worktree's dangling ``.git`` as a
    foreign checkout, while "is this the root of a working repo" must stay
    False -- git ignores a dangling link and walks UP, the trap
    surface_contract guards."""
    r = tmp_path / "r"
    r.mkdir()
    (r / ".git").symlink_to(tmp_path / "no-such-admin-dir")
    assert has_git_entry(r) is True
    assert is_own_git_repo(r) is False


def test_has_git_entry_agrees_with_is_own_git_repo_on_the_resolving_shapes(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    as_dir = tmp_path / "d"
    (as_dir / ".git").mkdir(parents=True)
    as_file = tmp_path / "f"
    as_file.mkdir()
    (as_file / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
    for p in (plain, as_dir, as_file):
        assert has_git_entry(p) is is_own_git_repo(p)


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_safe_rglob_prunes_a_directory_with_a_dangling_git_symlink(tmp_path):
    """Earned red: with the prune keyed on ``is_own_git_repo`` the foreign
    tree's files came back."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ok.py").write_text("x = 1\n", encoding="utf-8")
    stale = tmp_path / "stale_worktree"
    stale.mkdir()
    (stale / "foreign.py").write_text("x = 1\n", encoding="utf-8")
    (stale / ".git").symlink_to(tmp_path / "gone")
    found = {p.relative_to(tmp_path).as_posix() for p in safe_rglob(tmp_path, "*.py")}
    assert found == {"src/ok.py"}


def _tree_with_nested_repo(tmp_path):
    root = tmp_path / "root"
    (root / "keep").mkdir(parents=True)
    (root / "keep" / "own.txt").write_text("mine", encoding="utf-8")
    nested = root / "nested"
    (nested / ".git").mkdir(parents=True)  # embedded repo -> foreign project
    (nested / "foreign.txt").write_text("theirs", encoding="utf-8")
    (nested / "deep").mkdir()
    (nested / "deep" / "buried.txt").write_text("theirs too", encoding="utf-8")
    return root


def test_safe_rglob_skips_nested_repo_by_default(tmp_path):
    root = _tree_with_nested_repo(tmp_path)
    found = {p.relative_to(root).as_posix() for p in safe_rglob(root)}
    # the whole nested subtree (dir entry + all descendants) is pruned;
    # this repo's own content is untouched.
    assert "keep/own.txt" in found
    assert not any(f == "nested" or f.startswith("nested/") for f in found), found


def test_safe_rglob_includes_nested_repo_when_opted_out(tmp_path):
    root = _tree_with_nested_repo(tmp_path)
    found = {
        p.relative_to(root).as_posix()
        for p in safe_rglob(root, skip_nested_repos=False)
    }
    # opt-out restores exact rglob parity: nested content is walked again.
    assert "nested/foreign.txt" in found
    assert "nested/deep/buried.txt" in found


def _tree_with_dependency_dirs(tmp_path):
    root = tmp_path / "root"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "own.md").write_text("mine", encoding="utf-8")
    for dep in ("node_modules/pkg", "packages/app/node_modules/pkg"):
        (root / dep).mkdir(parents=True)
        (root / dep / "README.md").write_text("theirs", encoding="utf-8")
    return root


def test_safe_rglob_prunes_a_named_directory_at_any_depth(tmp_path):
    """A workspace keeps a ``node_modules/`` beside each package, not only at
    the root, so the prune is by NAME during the walk, never by root prefix."""
    root = _tree_with_dependency_dirs(tmp_path)
    found = {
        p.relative_to(root).as_posix()
        for p in safe_rglob(root, skip_dirs=frozenset({"node_modules"}))
    }
    assert "docs/own.md" in found
    assert "packages/app" in found, "the directory above a pruned one is still walked"
    assert not any("node_modules" in f.split("/") for f in found), found


def test_safe_rglob_walks_everything_when_no_directory_is_named(tmp_path):
    """The default is the old behaviour: every earlier caller passes nothing."""
    root = _tree_with_dependency_dirs(tmp_path)
    found = {p.relative_to(root).as_posix() for p in safe_rglob(root, "*.md")}
    assert found == {
        "docs/own.md",
        "node_modules/pkg/README.md",
        "packages/app/node_modules/pkg/README.md",
    }


def test_safe_rglob_skip_dirs_names_directories_not_files(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "node_modules").write_text("a FILE by that name", encoding="utf-8")
    found = {
        p.relative_to(root).as_posix()
        for p in safe_rglob(root, skip_dirs=frozenset({"node_modules"}))
    }
    assert found == {"node_modules"}


def _hook_probe():
    """The hook-side sister-site probe, loaded by path with tools/cc resolvable
    for its sibling imports (``_json_safe``, the stack table) while it executes."""
    import importlib.util
    import sys

    tools_cc = REPO_ROOT / "tools" / "cc"
    added = str(tools_cc) not in sys.path
    if added:
        sys.path.insert(0, str(tools_cc))
    try:
        spec = importlib.util.spec_from_file_location(
            "_safe_walk_hook_probe", tools_cc / "sister_site_probe.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_safe_walk_hook_probe"] = mod
        spec.loader.exec_module(mod)
    finally:
        if added:
            sys.path.remove(str(tools_cc))
    return mod


def _walker_reads(root: Path) -> dict[str, set[str]]:
    """What each repo-root walker that prunes the dependency trees read, as
    repo-relative posix paths: the three readers of ``DEPENDENCY_TREE_DIRS``,
    and the five walkers whose own skip lists derive their dependency half
    from the stack table (TP-469 lane C) -- the fingerprint, the non-git
    fallback, both halves of the router walk and the sister-site probe."""
    from espalier import analyze, reflection, repo_mode, scope_walker, strengthen
    from espalier import reflect_protocol as engine_reflect
    from espalier.config import load_config

    hook_reflect = _hook_reflect()
    probe = _hook_probe()
    probe_files, _pruned = probe._walk_python_sources(root, root)
    return {
        "reflection": {
            p.relative_to(root).as_posix() for p in reflection._iter_markdown_files(root)
        },
        "strengthen": {
            rel.replace("\\", "/")
            for _path, rel in strengthen._iter_repo_py(root, strengthen._EXEMPT_PREFIXES)
        },
        "scope_walker": {
            rel.replace("\\", "/")
            for rel, _line_no, _line in scope_walker._iter_scannable_lines(root)
        },
        # The fingerprint reads the adopter's declared names from the loaded
        # configuration (it honours --config), so the test loads it as the CLI does.
        "fingerprint": {
            p.relative_to(root).as_posix() for p in analyze._iter_files(root, load_config(root))
        },
        "non-git fallback": set(repo_mode.list_repo_files_via_filesystem(root)),
        "router walk (engine)": set(engine_reflect._walk_router_docs(root)),
        "router walk (hook)": set(hook_reflect._walk_router_docs(root)),
        "sister-site probe": {
            Path(p).resolve().relative_to(root.resolve()).as_posix() for p in probe_files
        },
    }


def test_every_dependency_directory_is_pruned_by_every_sharing_walker(tmp_path):
    """One set, eight readers. Measured before the set existed, on one planted
    tree: the reflection walk read every dependency directory, the strengthen
    walk read ``bower_components`` and a nested ``node_modules``, and the
    scope walk read ``bower_components`` -- three hand-kept lists, three
    different answers. Measured again on 2026-10-07 (TP-469 lane C, Appendix
    B drive 2) before the five other walkers derived from the stack table: the
    fingerprint and the non-git fallback read four of the five, both router
    walks read two. The directories are planted FROM the set and from the
    census seed's table-shaped names (a name deleted from the table is still
    planted, and the walkers' renewed reading of it is seen here), at the
    root and one workspace down, so a member added later is covered without
    an edit; each carries a ``CLAUDE.md`` for the router walks."""
    from _stack_census import SEED_DEPENDENCY_DIRS
    from espalier._safe_walk import DEPENDENCY_TREE_DIRS

    assert DEPENDENCY_TREE_DIRS, "an empty set would pass this test over nothing"
    # ``.venv`` is seed vocabulary (a hand list may spell it) but a Python
    # environment is not a dependency tree the sharing walkers prune; the
    # floor pin makes the same subtraction.
    planted = (SEED_DEPENDENCY_DIRS - {".venv"}) | DEPENDENCY_TREE_DIRS
    root = tmp_path / "root"
    (root / "src").mkdir(parents=True)
    (root / "src" / "own.py").write_text("def own():\n    return 1\n", encoding="utf-8")
    (root / "src" / "CLAUDE.md").write_text("# own router\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "own.md").write_text("# own\n", encoding="utf-8")
    for name in sorted(planted):
        for parent in ("", "packages/app/"):
            dep = root / (parent + name) / "pkg"
            dep.mkdir(parents=True)
            (dep / "dep.py").write_text("def dep():\n    return 1\n", encoding="utf-8")
            (dep / "README.md").write_text("# dep\n", encoding="utf-8")
            (dep / "CLAUDE.md").write_text("# dep router\n", encoding="utf-8")

    for walker, seen in _walker_reads(root).items():
        assert seen & {"src/own.py", "docs/own.md", "src/CLAUDE.md"}, (
            f"{walker} read nothing of the tree's own files, so its silence about "
            f"the dependency directories proves nothing: {sorted(seen)}"
        )
        leaked = sorted(rel for rel in seen if set(rel.split("/")) & planted)
        assert not leaked, f"{walker} read a dependency tree: {leaked}"


def test_a_declared_dependency_directory_is_pruned_by_every_derived_walker(tmp_path):
    """4-C of the stack-registry pack: espalier.toml's flat ``dependency_dirs``
    key adds names to the shipped set, and every walker that derives from it
    prunes them at any depth -- the engine walks through
    ``_safe_walk.declared_dependency_dirs`` and the two tools/cc walkers
    through ``_hook_utils.declared_dependency_dirs``. The names are planted
    at the root and one workspace down with a file of every kind the walks
    read; a shipped name is planted beside them as the control that the
    shipped set still prunes, and the tree's own files are read."""
    root = tmp_path / "root"
    (root / "src").mkdir(parents=True)
    (root / "src" / "own.py").write_text("def own():\n    return 1\n", encoding="utf-8")
    (root / "src" / "CLAUDE.md").write_text("# own router\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "own.md").write_text("# own\n", encoding="utf-8")
    (root / "espalier.toml").write_text(
        'dependency_dirs = ["deps", "Third-Party"]\n', encoding="utf-8"
    )
    planted = {"deps", "Third-Party", "node_modules"}
    for name in sorted(planted):
        for parent in ("", "packages/app/"):
            dep = root / (parent + name) / "pkg"
            dep.mkdir(parents=True)
            (dep / "dep.py").write_text("def dep():\n    return 1\n", encoding="utf-8")
            (dep / "README.md").write_text("# dep\n", encoding="utf-8")
            (dep / "CLAUDE.md").write_text("# dep router\n", encoding="utf-8")

    for walker, seen in _walker_reads(root).items():
        assert seen & {"src/own.py", "docs/own.md", "src/CLAUDE.md"}, (
            f"{walker} read nothing of the tree's own files: {sorted(seen)}"
        )
        leaked = sorted(rel for rel in seen if set(rel.split("/")) & planted)
        assert not leaked, f"{walker} read a declared dependency directory: {leaked}"


def test_declared_dependency_dirs_reads_the_key_and_drops_a_bad_entry(tmp_path):
    from espalier._safe_walk import DEPENDENCY_TREE_DIRS, declared_dependency_dirs, dependency_dirs_for
    from espalier.models import HarnessConfig

    assert declared_dependency_dirs(tmp_path) == frozenset()
    (tmp_path / "espalier.toml").write_text(
        'dependency_dirs = [" deps ", "Third-Party", "vendor/pkg", "..", 3]\n', encoding="utf-8"
    )
    assert declared_dependency_dirs(tmp_path) == {"deps", "Third-Party"}
    assert dependency_dirs_for(tmp_path) == DEPENDENCY_TREE_DIRS | {"deps", "Third-Party"}
    # A caller holding the loaded configuration (the fingerprint) is read from it, not the file.
    assert declared_dependency_dirs(tmp_path, HarnessConfig(dependency_dirs=["x"])) == {"x"}


def test_safe_glob_recursive_skips_nested_repo_by_default(tmp_path):
    root = _tree_with_nested_repo(tmp_path)
    found = {p.relative_to(root).as_posix() for p in safe_glob(root, "**/*.txt")}
    assert "keep/own.txt" in found
    assert not any(f.startswith("nested/") for f in found), found
    # opt-out walks the nested repo again.
    opted = {
        p.relative_to(root).as_posix()
        for p in safe_glob(root, "**/*.txt", skip_nested_repos=False)
    }
    assert "nested/foreign.txt" in opted


def test_safe_glob_prefix_naming_nested_repo_is_pruned(tmp_path):
    # A pattern whose PREFIX names the embedded repo must STILL be pruned by
    # default — the re-rooting optimization (walk `nested/` directly) must not
    # bypass the skip. Regression guard for the safe_glob prefix-bypass gap.
    root = _tree_with_nested_repo(tmp_path)
    for pat in ("nested/**", "nested/**/*.txt", "nested/**/*"):
        found = {p.relative_to(root).as_posix() for p in safe_glob(root, pat)}
        assert not any(f == "nested" or f.startswith("nested/") for f in found), (
            f"safe_glob({pat!r}) walked into the embedded repo by default: {sorted(found)}"
        )
        opted = {
            p.relative_to(root).as_posix()
            for p in safe_glob(root, pat, skip_nested_repos=False)
        }
        assert any(f.startswith("nested/") for f in opted), (
            f"opt-out should still walk {pat!r} into the nested repo"
        )


def _try_symlink(target, link, *, directory=True):
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")


def test_safe_rglob_survives_a_directory_symlink_loop(tmp_path):
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    _try_symlink(tmp_path, sub / "loop")
    # bare rglob would raise OSError(ELOOP) on CPython 3.10-3.12; safe_rglob
    # must return finitely on every version (no-op-safe on 3.13+).
    names = sorted(p.name for p in safe_rglob(tmp_path, "*.md"))
    assert names == ["a.md"]


def test_safe_rglob_matches_pattern_and_skips_symlinked_dir(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "keep.md").write_text("x", encoding="utf-8")
    real = root / "real"
    real.mkdir()
    (real / "deep.md").write_text("y", encoding="utf-8")
    _try_symlink(real, root / "alias")
    # Collect RELATIVE PATHS, not bare names: a `followlinks=True` regression
    # would also yield `alias/deep.md`, which shares its name with `real/deep.md`
    # — a name-set would collapse the duplicate and pass vacuously. The
    # path-set makes the symlink-skip contract observable on EVERY platform
    # (not just on a 3.10-3.12 loop), so this test earns its red on the 3.14
    # dev host too.
    found = {p.relative_to(root).as_posix() for p in safe_rglob(root, "*.md")}
    assert found == {"keep.md", "real/deep.md"}


def test_safe_rglob_yields_files_and_dirs_like_rglob(tmp_path):
    # walk a dedicated subdir we fully control (the autouse audit-dir fixture
    # seeds tmp_path/audit, so tmp_path itself is not empty).
    root = tmp_path / "root"
    root.mkdir()
    (root / "pkg").mkdir()
    (root / "pkg" / "mod.py").write_text("x", encoding="utf-8")
    everything = {p.relative_to(root).as_posix() for p in safe_rglob(root)}
    # matches rglob("*"): both the dir and the nested file, not root itself.
    assert everything == {"pkg", "pkg/mod.py"}


def test_safe_glob_recursive_pattern_survives_symlink_loop(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("x", encoding="utf-8")
    nested = docs / "sub"
    nested.mkdir()
    (nested / "ref.md").write_text("y", encoding="utf-8")
    _try_symlink(tmp_path, docs / "loop")
    # equivalent to tmp_path.glob("docs/**/*.md") but symlink-safe.
    found = {p.name for p in safe_glob(tmp_path, "docs/**/*.md")}
    assert found == {"guide.md", "ref.md"}


def test_safe_glob_nonrecursive_pattern_is_plain_glob(tmp_path):
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    (tmp_path / "other.txt").write_text("y", encoding="utf-8")
    found = {p.name for p in safe_glob(tmp_path, "README.md")}
    assert found == {"README.md"}


def _prefix_star_tree(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "docs" / "sub").mkdir(parents=True)
    (root / "docs" / "a.md").write_text("a", encoding="utf-8")
    (root / "docs" / "sub" / "b.md").write_text("b", encoding="utf-8")
    return root


def _prefix_star_expected(root):
    """Expected ``safe_glob`` results over :func:`_prefix_star_tree`, stated
    explicitly instead of derived from ``Path.glob``.

    ``Path.glob`` is NOT a stable oracle. Python 3.13 changed a bare trailing
    ``**`` from directories-only to files-and-directories, so asserting parity
    with it silently encodes the *interpreter version* rather than the
    contract — green on 3.13+, red on 3.10–3.12. ``safe_glob`` is deliberately
    files+dirs on every supported version (its bare-``**`` branch routes
    through ``safe_rglob``/``os.walk``, never ``Path.glob``), so assert that
    directly.

    Measured: only the bare-trailing forms (``**``, ``docs/**``) ever diverged.
    A ``**`` followed by a filter agrees across the 3.13 boundary; those
    patterns are kept here as regression coverage and must not be dropped.
    """
    docs = root / "docs"
    a_md = docs / "a.md"
    sub = docs / "sub"
    b_md = sub / "b.md"
    return {
        "docs/**": {docs, a_md, sub, b_md},
        "**": {root, docs, a_md, sub, b_md},
        "docs/**/*.md": {a_md, b_md},
        "**/*.md": {a_md, b_md},
        "**/*": {docs, a_md, sub, b_md},
        "docs/**/*": {a_md, sub, b_md},
    }


def test_safe_glob_trailing_prefix_star_yields_files_and_dirs(tmp_path):
    """TP-266 Fix 6: a trailing ``prefix/**`` (and bare ``**``) must walk the
    subtree and yield files AND directories. Pre-fix the bare branch turned
    ``docs/**`` into ``docs/*`` and fnmatched that slash-bearing string against
    leaf names (which never contain ``/``) → zero matches, so
    ``safe_glob(root, "docs/**")`` silently returned ``[]``. RED before (empty),
    GREEN after (a trailing ``**`` includes the anchor dir itself).
    The already-working suffix-filtered forms must stay unchanged."""
    root = _prefix_star_tree(tmp_path)
    expected = _prefix_star_expected(root)
    assert set(safe_glob(root, "docs/**")), "trailing prefix/** dropped the subtree"
    for pat in ("docs/**", "**", "docs/**/*.md", "**/*.md"):
        assert set(safe_glob(root, pat)) == expected[pat], (
            f"safe_glob({pat!r}) drifted from the explicit expected set"
        )


def test_freshness_safe_glob_mirror_yields_files_and_dirs(tmp_path):
    """TP-266 Fix 6 mirror: ``scanners/freshness._safe_glob`` is an inline copy
    of ``safe_glob`` (scanners cannot import espalier — TestScannerSelfContainment,
    they are inspect.getsource-copied), so the same trailing-``prefix/**`` fix must
    land there too. Same RED (``docs/**`` → ``[]``) / GREEN (files+dirs)."""
    from espalier.scanners.freshness import _safe_glob

    root = _prefix_star_tree(tmp_path)
    expected = _prefix_star_expected(root)
    assert set(_safe_glob(root, "docs/**")), "mirror dropped the subtree"
    for pat in ("docs/**", "**", "docs/**/*.md", "**/*.md"):
        assert set(_safe_glob(root, pat)) == expected[pat], (
            f"_safe_glob({pat!r}) drifted from the explicit expected set"
        )


def test_safe_glob_recursive_all_excludes_anchor(tmp_path):
    """TP-274 2-A: a trailing ``**/*`` (leaf collapses to ``*``) must NOT yield the
    anchor dir, while a BARE ``**`` / ``prefix/**`` still DOES. Pre-fix the branch
    gated the anchor yield on ``leaf == "*"``, true for BOTH ``**`` and ``**/*``,
    so ``**/*`` leaked the anchor. Gate on an empty ``tail`` instead. RED before
    (anchor leaked into ``**/*``), GREEN after. The sibling test uses ``**/*.md``
    (leaf ``*.md``, which never matches the anchor dir), so it could not catch
    this — which is why both pattern tuples must survive."""
    root = _prefix_star_tree(tmp_path)
    expected = _prefix_star_expected(root)
    for pat in ("**/*", "docs/**/*", "**", "docs/**"):
        assert set(safe_glob(root, pat)) == expected[pat], (
            f"safe_glob({pat!r}) drifted from the explicit expected set"
        )
    assert root not in set(safe_glob(root, "**/*")), "anchor leaked into **/*"
    assert root in set(safe_glob(root, "**")), "bare ** must include the anchor"


def test_freshness_safe_glob_recursive_all_excludes_anchor(tmp_path):
    """TP-274 2-A mirror: the inline ``scanners/freshness._safe_glob`` copy needs
    the identical anchor-gating fix (scanners cannot import espalier). Same RED
    (anchor leaked into ``**/*``) / GREEN (explicit expected sets)."""
    from espalier.scanners.freshness import _safe_glob

    root = _prefix_star_tree(tmp_path)
    expected = _prefix_star_expected(root)
    for pat in ("**/*", "docs/**/*", "**", "docs/**"):
        assert set(_safe_glob(root, pat)) == expected[pat], (
            f"_safe_glob({pat!r}) drifted from the explicit expected set"
        )
    assert root not in set(_safe_glob(root, "**/*")), "mirror leaked anchor into **/*"


def _func_def(source: str, name: str):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _is_skip_nested_prune(node) -> bool:
    """A nested-repo prune, stripped before the shared-core compare — in EITHER
    of its two shapes. The canonical ``safe_rglob`` carries an
    ``if skip_nested_repos: dirnames[:] = ...`` guard (TP-277); the inline scanner
    ``_safe_rglob`` copies carry a bare ``_skip_nested_repos(dirpath, dirnames)``
    call (TP-389) — scanners prune via a stdlib-only helper because they cannot
    import the canonical ``is_own_git_repo``. Nested-repo parity across the
    scanner fleet is a separate concern (``test_nested_repo_skip.py``), so both
    prune shapes are decoupled here and the drift-pin compares only the shared
    symlink-safe core (followlinks, fnmatch filter, yield).

    The canonical walker's ``if skip_dirs:`` prune is stripped the same way and
    for the same reason: it is an argument the inline copies do not take (a
    scanner names its own exempt prefixes), its behaviour is pinned by the
    ``skip_dirs`` tests above, and leaving it in the compare would red every
    copy for lacking a statement none of them can use. Only a guard whose test
    is that one bare name is stripped, so a prune folded into another
    condition still reaches the compare."""
    if (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id in ("skip_nested_repos", "skip_dirs")
    ):
        return True
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "_skip_nested_repos"
    )


def _oswalk_loop_dump(func) -> str | None:
    """AST dump of the safety-critical ``for ... in os.walk(root,
    followlinks=False): ...`` loop inside a _safe_rglob/safe_rglob body.
    ast.dump omits line/col attributes, so it is position-independent but
    pins the os.walk kwargs, the fnmatch filter, and the yield shape.

    Both nested-repo prune shapes (the canonical ``if skip_nested_repos:`` guard,
    TP-277, and the inline scanner ``_skip_nested_repos(...)`` call, TP-389) are
    stripped before the dump so the pin compares the SHARED symlink-safe core; a
    followlinks flip, dropped fnmatch filter, or changed yield in any copy still
    reds."""
    for stmt in func.body:
        if isinstance(stmt, ast.For):
            stmt.body = [s for s in stmt.body if not _is_skip_nested_prune(s)]
            return ast.dump(stmt)
    return None


def test_inline_safe_rglob_copies_match_canonical_oswalk_loop():
    """TP-194 drift-pin: scanners and tools/cc CANNOT import espalier
    (TestScannerSelfContainment — they are inspect.getsource-copied), so each
    carries an INLINE ``_safe_rglob`` copy. A bugfix to the canonical
    espalier/_safe_walk.py::safe_rglob would silently NOT propagate, and the
    recurrence guard can't see a drifted copy (it's a Name call, not .rglob).
    This pins the safety-critical os.walk(followlinks=False) loop of EVERY copy
    to the canonical via AST, so a copy that drifts (followlinks flip, dropped
    fnmatch filter, changed yield) earns the red. Copies are DISCOVERED (not a
    hand-list), dogfooding safe_rglob itself, so a new inline copy is auto-pinned."""
    canonical = _func_def((REPO_ROOT / "espalier" / "_safe_walk.py").read_text(encoding="utf-8"), "safe_rglob")
    ref = _oswalk_loop_dump(canonical)
    assert ref, "canonical safe_rglob os.walk loop not found"

    copies: list[Path] = []
    for base in ("espalier", "tools"):
        for py in safe_rglob(REPO_ROOT / base, "*.py"):
            if py.name == "_safe_walk.py":
                continue
            if "def _safe_rglob" in py.read_text(encoding="utf-8", errors="replace"):
                copies.append(py)
    # Floor guards a vacuous pass (discovery regression): 6 scanners + 2 reflect
    # mirrors carry the inline copy.
    assert len(copies) >= 8, f"expected >=8 inline _safe_rglob copies, found {len(copies)}"

    drifted = []
    for py in copies:
        func = _func_def(py.read_text(encoding="utf-8", errors="replace"), "_safe_rglob")
        if func is None or _oswalk_loop_dump(func) != ref:
            drifted.append(str(py.relative_to(REPO_ROOT)))
    assert not drifted, (
        "inline _safe_rglob copy drifted from espalier/_safe_walk.py::safe_rglob "
        "(re-sync the os.walk loop byte-for-byte):\n  " + "\n  ".join(sorted(drifted))
    )


# --- A Claude Code worktree under .claude/ is a nested checkout -------------

def _hook_reflect():
    """The hook-side reflect walker, loaded by path: tools/cc is not a package,
    and it carries its own nested-repo prune across the no-import boundary."""
    import importlib.util

    path = REPO_ROOT / "tools" / "cc" / "reflect_protocol.py"
    spec = importlib.util.spec_from_file_location("_safe_walk_hook_reflect", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _plant_worktree(root: Path, git_entry) -> None:
    """A tree whose own ``.claude/notes/x.md`` is surface, plus a Claude Code
    worktree at ``.claude/worktrees/wt/`` -- a whole second checkout, so it
    holds every kind of file either walk reads. ``git_entry`` writes the
    worktree's ``.git``."""
    (root / ".claude" / "notes").mkdir(parents=True)
    (root / ".claude" / "notes" / "x.md").write_text("# x\n", encoding="utf-8")
    wt = root / ".claude" / "worktrees" / "wt"
    for rel in (".claude/agents/a.md", "CLAUDE.md", "docs/guide.md", "memory/n.md"):
        (wt / rel).parent.mkdir(parents=True, exist_ok=True)
        (wt / rel).write_text("# foreign\n", encoding="utf-8")
    git_entry(wt / ".git")


def _reflect_surfaces(root: Path) -> dict[str, set[str]]:
    from espalier.reflect_protocol import _iter_surface_files

    hook = _hook_reflect()
    return {
        "engine": {p.relative_to(root).as_posix() for p in _iter_surface_files(root)},
        "hook": {hook._rel(p, root) for p in hook.iter_surface(root)},
    }


def _assert_worktree_unread(root: Path) -> None:
    for walker, seen in _reflect_surfaces(root).items():
        assert ".claude/notes/x.md" in seen, f"{walker} stopped walking .claude/ itself: {sorted(seen)}"
        leaked = sorted(rel for rel in seen if rel.startswith(".claude/worktrees/"))
        assert not leaked, f"{walker} entered the worktree: {leaked}"


def test_neither_reflect_walker_enters_a_gitlink_worktree(tmp_path):
    """A worktree's ``.git`` is a FILE (``gitdir: ...``). Earned red: the hook
    side's walk entered it and read the second checkout as this tree's surface
    (on a checkout with five worktrees, 1857 files against the engine's 184)."""
    _plant_worktree(
        tmp_path,
        lambda git: git.write_text("gitdir: /elsewhere/.git/worktrees/wt\n", encoding="utf-8"),
    )
    _assert_worktree_unread(tmp_path)


def test_neither_reflect_walker_enters_a_worktree_whose_git_link_dangles(tmp_path):
    """A ``.git`` symlink whose admin dir has moved or been removed dangles.
    The prune holds on both halves, in the surface walk and the folder-router
    walk alike: a ``Path.exists()`` test follows the link, says False, and
    enters (the hook side's router walk did until it shared the prune)."""
    _plant_worktree(tmp_path, lambda git: _try_symlink(tmp_path / "gone-admin-dir", git))
    _assert_worktree_unread(tmp_path)
    assert _hook_reflect()._walk_router_docs(tmp_path) == []


def test_the_hook_side_prune_is_the_named_helper_on_lexists():
    """The drift-pin above strips a bare ``_skip_nested_repos(dirpath,
    dirnames)`` call before it compares the walk, so the hook copy's prune is
    pinned here instead: both of that file's walks call it, and it keys on
    ``os.path.lexists`` (a dangling link prunes) rather than ``exists``."""
    source = (REPO_ROOT / "tools" / "cc" / "reflect_protocol.py").read_text(encoding="utf-8")
    helper = _func_def(source, "_skip_nested_repos")
    assert helper is not None, "the hook side lost its nested-repo prune helper"
    assert "'lexists'" in ast.dump(helper), ast.unparse(helper)
    for walk in ("_safe_rglob", "_walk_router_docs"):
        calls = [
            n for n in ast.walk(_func_def(source, walk))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "_skip_nested_repos"
        ]
        assert calls, f"{walk} no longer prunes through _skip_nested_repos"


# --- §C28 (DEF-479 / DEF-489, 2026-10-06): hidden names are never members ---

def test_is_hidden_name_is_true_for_the_names_a_file_manager_leaves():
    from espalier._safe_walk import is_hidden_name
    assert is_hidden_name(".DS_Store") is True
    assert is_hidden_name("._code-reviewer.md") is True
    assert is_hidden_name(".SKILL.md.swp") is True
    assert is_hidden_name("code-reviewer.md") is False
    assert is_hidden_name("SKILL.md") is False
    assert is_hidden_name("a.b.md") is False


def test_visible_drops_a_hidden_component_at_any_depth_below_the_base(tmp_path):
    """Both arms: the real entry is kept, the sidecar and the sidecar DIRECTORY
    are dropped, and the hidden parent ABOVE the base (``.claude``) is not read
    -- the predicate is on the enumeration's own components only."""
    from espalier._safe_walk import visible
    base = tmp_path / ".claude" / "skills"
    (base / "real").mkdir(parents=True)
    (base / "real" / "SKILL.md").write_text("real\n", encoding="utf-8")
    (base / "._real").mkdir()
    (base / "._real" / "SKILL.md").write_text("sidecar dir\n", encoding="utf-8")
    (base / "real" / "._SKILL.md").write_text("sidecar\n", encoding="utf-8")
    assert visible(base.rglob("SKILL.md"), base) == [base / "real" / "SKILL.md"]
    assert visible(base.rglob("*"), base) == [base / "real", base / "real" / "SKILL.md"]


def test_visible_refuses_a_member_outside_the_base(tmp_path):
    """A wrong base is a caller bug; keeping the entry silently would hide it."""
    from espalier._safe_walk import visible
    with pytest.raises(ValueError):
        visible([tmp_path / "elsewhere" / "x.md"], tmp_path / "base")
