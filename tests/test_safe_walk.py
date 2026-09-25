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
    symlink-safe core (followlinks, fnmatch filter, yield)."""
    if (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "skip_nested_repos"
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
