"""The drift matrix: ``espalier diff`` and doctor's drift check must stay quiet
on ordinary work and still flip on a change of kind.

The fingerprint reads the KIND of repo, not its size (docs/SHARP_EDGES.md
"Fingerprint Is Signal-Based, Not Census-Based"). Until 2026-10-04 the two
normalizers in ``espalier/diffing.py`` compared census-valued fields verbatim,
so an ordinary commit, a lock-file bump and a new docs page each turned
``espalier doctor`` yellow; the quiet rows below redded on that tree before
the reductions landed, which is the earned red. The matrix is the
pre-registered oracle (Standing Principle 19), every tree is a throwaway
(Standing Principle 12) and deliberately TypeScript-first, and every call
proves ``diff_repo`` is a read.

This file spawns ``git`` and is rostered in ``conftest._SLOW_FILES``; the pure
normalizer rows stay in ``tests/test_diffing.py`` and the fast slice.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from espalier.analyze import fingerprint_repo
from espalier.config import load_config
from espalier.diffing import diff_repo
from espalier.harness_config import build_harness_config

_GIT_IDENTITY = (
    "-c", "user.name=p", "-c", "user.email=p@p.invalid",
    "-c", "commit.gpgsign=false", "-c", "core.hooksPath=nohooks",
    "-c", "init.defaultBranch=main",
)


def _git(tree: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(tree), *_GIT_IDENTITY, *args],
                   capture_output=True, check=True, timeout=30)


def _write(tree: Path, rel: str, text: str) -> None:
    p = tree / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _signal_tree(tmp_path: Path, *, docs: bool | str = True, large: bool = True) -> Path:
    """A throwaway adopter tree: four ``.ts`` under ``src/`` (the primary
    language), two ``.go``, one ``.py``, six conventional commits. ``docs=True``
    is a README plus four pages (past the ``docs_heavy`` threshold);
    ``docs="single"`` is one page and no README (two surface entries, one short
    of the threshold); ``docs=False`` is none. ``large`` adds a 250 KB lock
    file. The union of the three member probes' fixtures."""
    tree = tmp_path / "adopter"
    tree.mkdir()
    for i in range(4):
        _write(tree, f"src/mod{i}.ts", f"export const v{i} = {i};\n")
    for i in range(2):
        _write(tree, f"cmd/tool{i}.go", f"package main\n// {i}\n")
    _write(tree, "scripts/helper.py", "x = 1\n")
    if docs is True:
        _write(tree, "README.md", "# adopter\n")
        for i in range(4):
            _write(tree, f"docs/page{i}.md", f"# page {i}\n")
    elif docs == "single":
        _write(tree, "docs/page0.md", "# page 0\n")
    if large:
        (tree / "uv.lock").write_bytes(b"A" * 250_000)
    _git(tree, "init", "-q")
    _git(tree, "add", "-A")
    for i in range(6):
        _git(tree, "commit", "-q", "--allow-empty", "-m", f"fix(pkg): change {i}")
    return tree


def _baseline(tree: Path) -> None:
    """Save the two reports the way ``init`` and ``fingerprint`` do."""
    config = load_config(tree)
    fp = fingerprint_repo(tree, config)
    reports = tree / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "repo_fingerprint.json").write_text(json.dumps(fp.to_dict()), encoding="utf-8")
    (reports / "harness_config.json").write_text(
        json.dumps(build_harness_config(fp, config).to_dict()), encoding="utf-8"
    )


def _drift(tree: Path) -> tuple[bool, bool]:
    """Both drift flags, after proving the read is a read: the saved reports
    are byte-identical after the call (memory/stateful-oracle-consumes-what-it-measures.md)."""
    before = {p.name: p.read_bytes() for p in (tree / "reports").glob("*.json")}
    result = diff_repo(tree)
    after = {p.name: p.read_bytes() for p in (tree / "reports").glob("*.json")}
    assert before == after, "diff_repo rewrote a saved report"
    return bool(result["fingerprint_changed"]), bool(result["build_plan_changed"])


# -- ordinary work: must stay quiet ------------------------------------------

def _empty_commit(tree: Path) -> None:
    _git(tree, "commit", "-q", "--allow-empty", "-m", "fix(pkg): change 7")


def _freeform_subject_commit(tree: Path) -> None:
    _git(tree, "commit", "-q", "--allow-empty", "-m", "tweak the thing")


def _second_file_in_an_existing_language(tree: Path) -> None:
    _write(tree, "src/mod4.ts", "export const v4 = 4;\n")


def _lock_file_grows_by_four_bytes(tree: Path) -> None:
    p = tree / "uv.lock"
    p.write_bytes(p.read_bytes() + b"AAAA")


def _new_docs_page_past_the_threshold(tree: Path) -> None:
    _write(tree, "docs/aaa.md", "# a\n")


def _language_rank_swap_below_first_place(tree: Path) -> None:
    # python 1 -> 3 overtakes go 2; typescript stays first at 4 (no ties)
    for i in range(2):
        _write(tree, f"scripts/more{i}.py", "y = 2\n")


def _new_folder_under_src(tree: Path) -> None:
    # the most common action on a src-layout tree; `detect_architecture` lists
    # every directory under src/ as a layer
    _write(tree, "src/components/Button.ts", "export const Button = 1;\n")


def _root_debris_file(tree: Path) -> None:
    # a pasted patch dump at the root: `detect_garbage_files` flags it and
    # `risk_notes` restates the flag as a note
    _write(tree, "out.txt", "diff --git a/x b/x\n--- a/x\n+++ b/x\n")


# -- changes of kind: must still flip -----------------------------------------

def _new_ci_provider(tree: Path) -> None:
    _write(tree, ".github/workflows/ci.yml", "on: push\n")


def _new_language(tree: Path) -> None:
    _write(tree, "lib/mod.rs", "fn main() {}\n")


def _first_docs_page(tree: Path) -> None:
    _write(tree, "docs/intro.md", "# intro\n")


def _first_large_file(tree: Path) -> None:
    (tree / "big.bin").write_bytes(b"B" * 250_000)


def _primary_language_overtaken_by_file_count(tree: Path) -> None:
    # go 2 -> 5 overtakes typescript 4: the primary language is the signal the
    # CLI keys on, so this flips by design (the operator's call, 2026-10-04)
    for i in range(3):
        _write(tree, f"cmd/more{i}.go", f"package main\n// more {i}\n")


def _docs_page_crosses_the_docs_heavy_threshold(tree: Path) -> None:
    # on the "single" shape the surface is [docs, docs/page0.md]; a second page
    # takes it to three and `classify_repo` scores docs_heavy: a profile flip
    # is a kind change (the operator's call, 2026-10-04)
    _write(tree, "docs/page1.md", "# page 1\n")


_ORDINARY_WORK = {
    "empty-commit": _empty_commit,
    "freeform-subject-commit": _freeform_subject_commit,
    "second-file-in-an-existing-language": _second_file_in_an_existing_language,
    "lock-file-grows-by-four-bytes": _lock_file_grows_by_four_bytes,
    "new-docs-page-past-the-docs-heavy-threshold": _new_docs_page_past_the_threshold,
    "language-rank-swap-below-first-place": _language_rank_swap_below_first_place,
    "new-folder-under-src": _new_folder_under_src,
    "root-debris-file": _root_debris_file,
}

#: name -> (mutation, the tree shape it needs). The two "first" rows start from
#: a tree WITHOUT the surface, so the appearance is the signal; the threshold
#: row starts one page short of it.
_CHANGES_OF_KIND = {
    "new-ci-provider": (_new_ci_provider, {}),
    "new-language": (_new_language, {}),
    "first-docs-page": (_first_docs_page, {"docs": False}),
    "first-large-file": (_first_large_file, {"large": False}),
    "primary-language-overtaken-by-file-count": (_primary_language_overtaken_by_file_count, {}),
    "docs-page-crosses-the-docs-heavy-threshold": (
        _docs_page_crosses_the_docs_heavy_threshold, {"docs": "single"}
    ),
}


class TestDriftIsSignalNotCensus:
    """Doctor's own drift check is derived from these two flags, so they are
    the thing to pin."""

    @pytest.mark.parametrize("name", sorted(_ORDINARY_WORK))
    def test_ordinary_work_is_not_drift(self, tmp_path, name):
        tree = _signal_tree(tmp_path)
        _baseline(tree)
        assert _drift(tree) == (False, False), "the baseline itself reads as drift"
        _ORDINARY_WORK[name](tree)
        assert _drift(tree) == (False, False), f"{name} turned a drift flag"

    @pytest.mark.parametrize("name", sorted(_CHANGES_OF_KIND))
    def test_a_change_of_kind_still_flips(self, tmp_path, name):
        mutate, shape = _CHANGES_OF_KIND[name]
        tree = _signal_tree(tmp_path, **shape)
        _baseline(tree)
        assert _drift(tree) == (False, False), "the baseline itself reads as drift"
        mutate(tree)
        fingerprint_changed, _ = _drift(tree)
        assert fingerprint_changed, f"{name} must read as drift"
