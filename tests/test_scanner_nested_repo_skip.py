# pytest-marker: default-unit
"""Nested-repo skip parity for the adopter-facing scanners (INV-28).

Guards against a scanner walking into a vendored sub-repo and flagging its code
as the adopter's own — the prune must stay in every scanner-local walker because
the stdlib-only isolation forbids sharing the engine's ``safe_rglob``.

An embedded git repository (a vendored dependency with its own ``.git``) is a
foreign project, not the adopter's own surface. The engine's
``espalier._safe_walk`` already prunes it (``skip_nested_repos=True``); the
stdlib-only scanner-local walkers must match — otherwise a scanner flags the
vendored project's code as the adopter's own (a first-run false positive).

Earn-the-red: before the ``_skip_nested_repos`` prune, each scanner-local walker
descends into the vendored dir and enumerates its ``.py`` body — so the
assertions below (vendored code absent, own code present) fail RED. The family-1
``iter_*`` walkers got the prune in TP-377; the family-2 ``_safe_rglob`` copies
in TP-389.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

# Bare-except: pass — trips the exceptions scanner (swallowed_silent).
_VIOLATION = "def f():\n    try:\n        risky()\n    except:\n        pass\n"

# (module, iter-helper) for each of the five family-1 walkers (TP-377).
_WALKERS = [
    ("exceptions", "iter_py_files"),
    ("prints", "iter_py_files"),
    ("perf_smells", "iter_py_files"),
    ("godfiles", "iter_py_files"),
    ("test_loosening", "iter_test_files"),
]

# The seven family-2 scanners route their walk through a local ``_safe_rglob``
# (not an ``iter_*`` helper); TP-389 added the same ``_skip_nested_repos`` prune
# there. ``_safe_rglob(root, pattern)`` yields Path objects, a different
# signature from the family-1 iter-helpers, so it gets its own parametrization.
_SAFE_RGLOB_SCANNERS = [
    "convergence_theater",
    "encoding_contracts",
    "filesystem_contracts",
    "freshness",
    "magic_depth",
    "retired_vocab",
    "subprocess_contracts",
]


def _make_nested_repo_tree(tmp_path):
    """outer/ has its OWN code (own.py, test_own.py) plus a vendored sub-repo
    (vendored/.git/) whose code (bad.py, test_bad.py) must be skipped."""
    outer = tmp_path / "outer"
    vendored = outer / "vendored"
    (vendored / ".git").mkdir(parents=True)               # embedded-repo marker (dir)
    (vendored / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (vendored / "bad.py").write_text(_VIOLATION, encoding="utf-8")
    (vendored / "test_bad.py").write_text(_VIOLATION, encoding="utf-8")
    (outer / "own.py").write_text(_VIOLATION, encoding="utf-8")
    (outer / "test_own.py").write_text(_VIOLATION, encoding="utf-8")
    return outer


class TestNestedRepoSkip:
    @pytest.mark.parametrize("modname,itername", _WALKERS)
    def test_walker_skips_embedded_repo(self, tmp_path, modname, itername):
        outer = _make_nested_repo_tree(tmp_path)
        mod = importlib.import_module(f"espalier.scanners.{modname}")
        iter_fn = getattr(mod, itername)
        yielded = [p.replace("\\", "/") for p in iter_fn(str(outer))]
        assert not any("/vendored/" in p for p in yielded), (
            f"{modname}.{itername} walked into the embedded repo: {yielded}"
        )
        # own code (whatever this walker enumerates) is still reachable
        assert any("own" in os.path.basename(p) for p in yielded), (
            f"{modname}.{itername} over-pruned — own code lost: {yielded}"
        )

    @pytest.mark.parametrize("modname", _SAFE_RGLOB_SCANNERS)
    def test_safe_rglob_scanner_skips_embedded_repo(self, tmp_path, modname):
        """Family-2 (TP-389): the six scanners that walk via a local
        ``_safe_rglob`` prune the vendored sub-repo, matching the engine's
        ``safe_rglob(skip_nested_repos=True)``. Earn-the-red: before the prune,
        ``_safe_rglob`` enumerated the vendored ``.py`` body (leak=True on every
        one of the six)."""
        outer = _make_nested_repo_tree(tmp_path)
        mod = importlib.import_module(f"espalier.scanners.{modname}")
        yielded = [str(p).replace("\\", "/") for p in mod._safe_rglob(Path(outer), "*.py")]
        assert not any("/vendored/" in p for p in yielded), (
            f"{modname}._safe_rglob walked into the embedded repo: {yielded}"
        )
        assert any("own" in os.path.basename(p) for p in yielded), (
            f"{modname}._safe_rglob over-pruned — own code lost: {yielded}"
        )

    def test_scan_repo_does_not_flag_embedded_repo(self, tmp_path):
        outer = _make_nested_repo_tree(tmp_path)
        from espalier.scanners.exceptions import scan_repo
        report = scan_repo(str(outer))
        files = [f["file"].replace("\\", "/") for f in report["findings"]]
        assert not any("/vendored/" in f for f in files), (
            f"exceptions flagged embedded-repo code: {files}"
        )
        assert any("own.py" in f for f in files), (
            f"exceptions dropped the adopter's own violation: {files}"
        )

    def test_parity_with_safe_rglob(self, tmp_path):
        """Documents the semantic the scanners now match: safe_rglob already
        prunes the embedded repo, so scanner + engine agree on the fixture."""
        outer = _make_nested_repo_tree(tmp_path)
        from espalier._safe_walk import safe_rglob
        engine = {str(p).replace("\\", "/") for p in safe_rglob(Path(outer), "*.py")}
        assert not any("/vendored/" in p for p in engine)

    def test_every_os_walk_scanner_is_behaviorally_covered(self):
        """Completeness pin — the anti-whack-a-mole half the presence-gate in
        ``test_nested_repo_skip.py`` cannot give. That gate proves the marker NAME
        is called; this proves the prune actually WORKS for EVERY scanner, not a
        hand-picked subset: every ``espalier/scanners/*.py`` that walks a tree via
        ``os.walk`` must appear in a behavioral list here (``_WALKERS`` or
        ``_SAFE_RGLOB_SCANNERS``), so a future scanner that copies the
        ``_skip_nested_repos`` helper is FORCED to earn a red proving its prune —
        guarding against a born-no-op copy shipping on the next scanner. Also
        forbids the ``from os import walk`` alias, which the ``os.walk``-attribute
        matcher (here and in the presence-gate) cannot see."""
        import ast
        import espalier.scanners as _pkg

        scanners_dir = Path(_pkg.__file__).parent
        covered = {m for m, _ in _WALKERS} | set(_SAFE_RGLOB_SCANNERS)
        discovered: set[str] = set()
        for py in sorted(scanners_dir.glob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "os":
                    assert not any(a.name == "walk" for a in node.names), (
                        f"{py.name}: `from os import walk` evades the nested-repo "
                        "enumeration gate (it matches an `os.walk` attribute call "
                        "only) — use `import os` + `os.walk(...)`."
                    )
                if isinstance(node, ast.For):
                    it = node.iter
                    if (
                        isinstance(it, ast.Call)
                        and isinstance(it.func, ast.Attribute)
                        and it.func.attr == "walk"
                        and isinstance(it.func.value, ast.Name)
                        and it.func.value.id == "os"
                    ):
                        discovered.add(py.stem)
        missing = discovered - covered
        assert not missing, (
            "scanner module(s) walk via os.walk but are NOT behaviorally pinned in "
            "_WALKERS / _SAFE_RGLOB_SCANNERS — add each + prove its prune reds:\n  "
            + "\n  ".join(sorted(missing))
        )
        assert len(discovered) >= 12, (
            f"scanner os.walk discovery floor breached: {sorted(discovered)} "
            "(expected the 12 known scanner walkers)"
        )

    def test_safe_rglob_skips_gitlink_file_repo(self, tmp_path):
        """The helper's ``dir OR gitlink file`` claim: a nested repo whose ``.git``
        is a FILE (submodule / worktree shape), not a dir, is pruned too — the
        scanner analog of ``test_is_own_git_repo_true_for_gitlink_file``. Guards the
        otherwise-untested half of the ``_skip_nested_repos`` docstring."""
        outer = tmp_path / "outer"
        sub = outer / "sub"
        sub.mkdir(parents=True)
        (sub / ".git").write_text("gitdir: /elsewhere/.git/modules/sub\n", encoding="utf-8")
        (sub / "code.py").write_text(_VIOLATION, encoding="utf-8")
        (outer / "own.py").write_text(_VIOLATION, encoding="utf-8")
        from espalier.scanners.freshness import _safe_rglob
        yielded = [str(p).replace("\\", "/") for p in _safe_rglob(Path(outer), "*.py")]
        assert not any("/sub/" in p for p in yielded), f"gitlink-file repo not pruned: {yielded}"
        assert any("own.py" in os.path.basename(p) for p in yielded), f"own code lost: {yielded}"
