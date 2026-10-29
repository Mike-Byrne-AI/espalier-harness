"""scripts/sync_asset_docs.py judges the seeded docs' audience where the text is
written.

The sync copies each source under docs/ (and task-packs/) over its packaged
mirror; it is the first step every fold into the seeded catalog runs. After the
copy it reads the seeded docs for maintainer-addressed text
(``espalier.surface_hygiene.seeded_marker_hits``, the audience gate's own walk
over git's view) and refuses when the count is over ``SEED_BASELINE``, naming
the per-file counts, the source each is fixed at, and the hits new in this lane:
each mirror body judged against its committed form, so a second run after a
refusal names the same words. Before this read, a fold of four catalog rows that
carried six hits past the ceiling went through the sync, the provenance census
and the landing check, and reached the pull request's five required test cells
first.

This module pins that read and guards against its drift: the refusal, the
parity copy made before it, the words named against the committed form on a
first and a second run, the own-source pointer, the check mode that writes
nothing, and the one home the gate and the sync read the ceiling from.

``_ROOT`` and ``_MIRRORED`` are redirected to a tmp checkout so the real mirrors
are never written.
"""
# slow-exempt: a few git calls on a tmp checkout per test (init, add, commit, show, ls-files): seconds for the module, not a slow file
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from espalier import surface_hygiene

REPO_ROOT = Path(__file__).resolve().parent.parent
MIRRORED_REL = "docs/CATALOG.md"
ASSET = Path("espalier/assets")


def _load_sync_script(monkeypatch):
    """Import the script as a module, registered for the test's life only."""
    spec = importlib.util.spec_from_file_location(
        "_ceiling_sync_asset_docs", REPO_ROOT / "scripts" / "sync_asset_docs.py",
    )
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    return mod


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "init.defaultBranch=main", *args],
        check=True, capture_output=True,
    )


def _ceiling() -> int:
    _, ceiling = surface_hygiene.SEED_BASELINE
    assert ceiling >= 2, "the fixtures write ceiling - 1 hits and then add two"
    return ceiling


def _ledger_lines(n: int) -> str:
    """``n`` lines carrying one ledger-id hit each (the ``DEF-1`` grammar)."""
    return "\n".join("A row names DEF-1 here." for _ in range(n)) + "\n"


FOLD = (
    "\n### A new row\n\n"
    "**Measured in this repo.** On 2026-01-01 the gate was timed.\n"
    "The row is `DEF-2`; the fix is a derived line.\n"
)
FOLD_WORDS = (
    "[dated-measurement] 'Measured in this repo.** On 2026-01-01'",
    "[ledger-id] 'DEF-2'",
)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A repo-shaped tmp checkout (git, no origin) with one mirrored doc, the
    sync pointed at it. HEAD is the baseline once something is committed."""
    mod = _load_sync_script(monkeypatch)
    (tmp_path / "docs").mkdir()
    (tmp_path / ASSET / "docs").mkdir(parents=True)
    _git(tmp_path, "init", "-q")
    monkeypatch.setattr(mod, "_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_MIRRORED", (MIRRORED_REL,))
    return mod, tmp_path


def _commit_all(root: Path) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")


def _run(mod, argv, capsys):
    rc = mod.main(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


class TestTheSyncHoldsTheSeededCeiling:
    def test_a_body_under_the_ceiling_syncs_and_prints_the_count(self, tree, capsys):
        mod, root = tree
        ceiling = _ceiling()
        (root / MIRRORED_REL).write_text(_ledger_lines(ceiling), encoding="utf-8")
        rc, out, err = _run(mod, [], capsys)
        assert rc == 0, err
        assert (root / ASSET / MIRRORED_REL).read_bytes() == (root / MIRRORED_REL).read_bytes()
        assert "synced 1 asset doc mirrors" in out
        assert f"seeded docs: {ceiling} of {ceiling} maintainer-addressed hits" in out
        assert err == ""

    def test_a_fold_over_the_ceiling_is_refused_and_the_new_words_named(self, tree, capsys):
        """RED before the read: the sync copied, printed ``synced``, exited 0, and
        the pull request's test cells were the first to say the ceiling was
        crossed. GREEN after: exit 1 with the parity copy made, the per-file count,
        the source to fix at, the hits new against HEAD -- the words the author
        just wrote, not the hundreds already in the body -- and nothing on stdout,
        so the last line a reader sees is the refusal."""
        mod, root = tree
        ceiling = _ceiling()
        src, dst = root / MIRRORED_REL, root / ASSET / MIRRORED_REL
        src.write_text(_ledger_lines(ceiling - 1), encoding="utf-8")
        dst.write_bytes(src.read_bytes())
        _commit_all(root)
        src.write_text(src.read_text(encoding="utf-8") + FOLD, encoding="utf-8")
        rc, out, err = _run(mod, [], capsys)
        assert rc == 1
        assert dst.read_bytes() == src.read_bytes(), "the parity copy is made before the read"
        assert out == ""
        assert (
            f"REFUSED: the seeded docs carry {ceiling + 1} maintainer-addressed hits, "
            f"over the ceiling of {ceiling}" in err
        )
        assert f"{ASSET.as_posix()}/{MIRRORED_REL}  (fix at {MIRRORED_REL}, then run this sync again)" in err
        assert "New against HEAD:" in err
        for word in FOLD_WORDS:
            assert word in err
        assert "'DEF-1'" not in err, "the hits already in the body are counted, not listed"
        assert err.rstrip().splitlines()[-1].startswith("REFUSED (exit 1): the mirrors are copied")

    def test_a_second_run_after_a_refusal_names_the_same_words(self, tree, capsys):
        """The first cut judged against the mirror on disk; the refused run had
        copied, so the run the author actually read found nothing new and said
        the excess was already there. Judged against HEAD, both runs agree."""
        mod, root = tree
        ceiling = _ceiling()
        src, dst = root / MIRRORED_REL, root / ASSET / MIRRORED_REL
        src.write_text(_ledger_lines(ceiling - 1), encoding="utf-8")
        dst.write_bytes(src.read_bytes())
        _commit_all(root)
        src.write_text(src.read_text(encoding="utf-8") + FOLD, encoding="utf-8")
        first = _run(mod, [], capsys)
        second = _run(mod, [], capsys)
        assert first[0] == second[0] == 1
        for word in FOLD_WORDS:
            assert word in first[2] and word in second[2]
        assert "No mirror body differs" not in second[2]

    def test_a_mirror_new_since_head_and_a_repeated_match_are_counted(self, tree, capsys, monkeypatch):
        mod, root = tree
        ceiling = _ceiling()
        monkeypatch.setattr(mod, "_MIRRORED", (MIRRORED_REL, "docs/NEW.md"))
        src, dst = root / MIRRORED_REL, root / ASSET / MIRRORED_REL
        src.write_text(_ledger_lines(ceiling - 1), encoding="utf-8")
        dst.write_bytes(src.read_bytes())
        _commit_all(root)
        (root / "docs" / "NEW.md").write_text("DEF-2 and DEF-2 on one line.\n", encoding="utf-8")
        rc, out, err = _run(mod, [], capsys)
        assert rc == 1
        assert f"{ASSET.as_posix()}/docs/NEW.md: [ledger-id] 'DEF-2' x2" in err

    def test_a_changed_body_that_gains_no_hit_says_so(self, tree, capsys):
        mod, root = tree
        ceiling = _ceiling()
        src, dst = root / MIRRORED_REL, root / ASSET / MIRRORED_REL
        src.write_text(_ledger_lines(ceiling + 1), encoding="utf-8")
        dst.write_bytes(src.read_bytes())
        _commit_all(root)
        src.write_text(src.read_text(encoding="utf-8") + "A plain sentence.\n", encoding="utf-8")
        rc, out, err = _run(mod, [], capsys)
        assert rc == 1
        assert "1 mirror body differs from HEAD and gained no hit" in err
        assert "New against" not in err

    def test_a_seed_with_no_mirror_row_is_named_as_its_own_source(self, tree, capsys):
        mod, root = tree
        ceiling = _ceiling()
        (root / MIRRORED_REL).write_text(_ledger_lines(ceiling), encoding="utf-8")
        (root / ASSET / "memory").mkdir()
        (root / ASSET / "memory" / "README.md").write_text("A note names DEF-3.\n", encoding="utf-8")
        rc, out, err = _run(mod, [], capsys)
        assert rc == 1
        assert f"    1  {ASSET.as_posix()}/memory/README.md  (its own source: no mirror row)" in err

    def test_check_mode_refuses_over_the_ceiling_and_writes_nothing(self, tree, capsys):
        mod, root = tree
        ceiling = _ceiling()
        src, dst = root / MIRRORED_REL, root / ASSET / MIRRORED_REL
        src.write_text(_ledger_lines(ceiling + 1), encoding="utf-8")
        dst.write_bytes(src.read_bytes())
        stamp = dst.stat().st_mtime_ns
        rc, out, err = _run(mod, ["--check"], capsys)
        assert rc == 1
        assert "REFUSED" in err and "(--check reads the mirrors as they are" in err
        assert "copied" not in err, "--check copies nothing and must not say it did"
        assert dst.stat().st_mtime_ns == stamp
        assert out == ""

    def test_without_git_the_replaced_mirror_body_is_the_baseline(self, tmp_path, monkeypatch, capsys):
        mod = _load_sync_script(monkeypatch)
        (tmp_path / "docs").mkdir()
        (tmp_path / ASSET / "docs").mkdir(parents=True)
        monkeypatch.setattr(mod, "_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_MIRRORED", (MIRRORED_REL,))
        monkeypatch.setattr(mod, "_git", lambda *args: None)
        ceiling = _ceiling()
        src, dst = tmp_path / MIRRORED_REL, tmp_path / ASSET / MIRRORED_REL
        dst.write_text(_ledger_lines(ceiling - 1), encoding="utf-8")
        src.write_text(_ledger_lines(ceiling - 1) + FOLD, encoding="utf-8")
        rc, out, err = _run(mod, [], capsys)
        assert rc == 1
        assert "New against the mirror body this sync replaced:" in err
        for word in FOLD_WORDS:
            assert word in err


class TestTheCeilingHasOneHome:
    def test_the_audience_gate_reads_the_hygiene_modules_values(self):
        """The cheap wrong edit is a literal pair back in the test file: the gate
        and the sync would then hold different ceilings and nothing would say so."""
        from tests import test_deployed_text_audience as gate

        assert gate.SEED_BASELINE is surface_hygiene.SEED_BASELINE
        assert gate.TEXT_SUFFIXES is surface_hygiene.SEED_TEXT_SUFFIXES
