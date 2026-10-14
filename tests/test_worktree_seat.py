"""A fresh linked-worktree seat, read by the readers that classify it.

A worktree checks out tracked files only. Claude Code then copies in the
gitignored paths ``.worktreeinclude`` lists -- the project settings file and the
two reports the audit reads -- and nothing else. Every other per-checkout record
is absent until something in the seat writes it: the surface gate's result
(``reports/cc_surface_gate.json``) and the integrity manifest
(``.espalier/integrity.json``). Neither absence is damage; each is a verdict
about a tree, and this tree has not been judged yet.

Driven 2026-10-13 on a real seat of this repository: the SessionStart banner
read ``Surface: healthy`` and called the missing manifest a note, while
``/status`` and ``/context-load`` (``tools/cc/session_resume.py``) read the
same seat DEGRADED and said "rebuild or re-audit the CC surface", and
``espalier integrity verify`` -- ``/preflight``'s integrity step -- exited 1.
Copying the two records in was the rejected fix: a copied gate result or
manifest is the main checkout's verdict shown as the seat's own.

So a seat judges its per-checkout files against its main checkout: a record
no include entry carries reads "not generated in this worktree yet" with what
writes it, and an include entry the seat lacks while its main checkout has it
reads "copy it from there" -- never "rebuild", never ``espalier init``, which
would redeploy the harness into the seat. A worktree of a bare repository has
no main checkout to judge against and reads as it did before.

This module pins those readings on a real ``git worktree add`` seat, guards the
main-checkout and corrupt-record reds they must not soften, and holds the three
copies of the linked-worktree predicate and resume's two seat rosters to each
other and to the engine's lists, because each is a hand-kept copy across an
import wall that would otherwise drift in silence.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# slow-exempt: each test builds one scratch repo and one `git worktree add`
# (measured 2026-10-13: 2.4 s for the module on 3.14, 2.6 s on 3.10, 0.3 s the
# slowest test) -- what a linked worktree's `.git` holds is a fact about real
# git output, so only real git can show it.

from espalier.cli import REQUIRED_GITIGNORE, WORKTREE_INCLUDE_ENTRIES, _gitignore_entry_covering
from tests._git_oracle import _git_env
from tools.cc import session_resume
from tools.cc.session_resume import REQUIRED_PATHS, assess_repo_state, render_status_report

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT / "tools" / "cc" / "hooks"))
import _integrity  # noqa: E402
sys.path.pop(0)

GATE = "reports/cc_surface_gate.json"
# What init's `.worktreeinclude` has Claude Code copy into a new worktree.
INCLUDED = tuple(WORKTREE_INCLUDE_ENTRIES)
COHERENT = "surface looks coherent"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env=_git_env(), timeout=45)


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _main_checkout(tmp_path: Path, *, initialized: bool = True, manifest: str = "") -> Path:
    """A repository holding the committed harness surface, its runtime files
    gitignored and (when ``initialized``) present, as ``espalier init`` leaves
    them, with the surface gate's result written by an audit."""
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    for key, value in (("user.name", "t"), ("user.email", "t@example.invalid"),
                       ("commit.gpgsign", "false")):
        _git(main, "config", key, value)
    _write(main, ".gitignore", ".claude/settings.json\nreports/\n.espalier/integrity.json\n")
    _write(main, ".worktreeinclude", "".join(f"{rel}\n" for rel in INCLUDED))
    for rel in ("cc/LIVE_SURFACE.md", "cc/COMMANDS.md"):
        _write(main, rel, "# surface\n")
    _write(main, "cc/PACK_MANIFEST.txt", manifest)
    for rel in ("tools/cc/cognitive_blueprint.py", "tools/cc/session_resume.py"):
        _write(main, rel, "# stub\n")
    _git(main, "add", "-A")
    _git(main, "commit", "-qm", "base")
    if initialized:
        for rel in INCLUDED:
            _write(main, rel, "{}")
        _write(main, GATE, json.dumps({"status": "pass"}))
    return main


def _seat(tmp_path: Path, *, copy: tuple[str, ...] = INCLUDED,
          initialized: bool = True, manifest: str = "") -> tuple[Path, Path]:
    """``(main, seat)``: a linked worktree of a fresh main checkout, holding
    the tracked files git checked out plus ``copy`` from the main checkout --
    by default what ``.worktreeinclude`` has Claude Code copy in."""
    main = _main_checkout(tmp_path, initialized=initialized, manifest=manifest)
    seat = tmp_path / "seat"
    _git(main, "worktree", "add", "-q", "-b", "seat", str(seat))
    for rel in copy:
        (seat / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(main / rel, seat / rel)
    assert (seat / ".git").is_file(), "precondition: a linked worktree's .git is a gitlink file"
    return main, seat


class TestTheSeatRosters:
    """Resume cannot import the engine, so it keeps its own two rosters of the
    gitignored required paths; these hold them to the engine's lists, so a new
    include entry or a new gitignored required path reds here rather than
    reading every fresh seat DEGRADED."""

    def test_the_copied_roster_is_inits_include(self):
        assert session_resume._COPIED_INTO_A_SEAT == tuple(
            e for e in WORKTREE_INCLUDE_ENTRIES if e in REQUIRED_PATHS)

    def test_every_gitignored_required_path_is_in_exactly_one_roster(self):
        copied = set(session_resume._COPIED_INTO_A_SEAT)
        not_copied = set(session_resume._NOT_COPIED_INTO_A_SEAT)
        assert not copied & not_copied
        for rel in REQUIRED_PATHS:
            ignored = _gitignore_entry_covering(rel, REQUIRED_GITIGNORE) is not None
            assert (rel in copied or rel in not_copied) == ignored, rel

    def test_every_record_never_copied_names_its_writer(self):
        for rel, writer in session_resume._NOT_COPIED_INTO_A_SEAT.items():
            assert writer.startswith("/"), (rel, writer)  # a slash command, never a bare console script


class TestResumeReadsASeat:
    """``/status`` and ``/context-load`` on a seat: what is missing because the
    seat has not judged itself yet is a note naming its writer; what is missing
    because a copy was never made is a copy, from the main checkout."""

    def test_a_fresh_seat_reads_healthy_and_names_the_audit(self, tmp_path):
        """Dies to: the seat read as a main checkout that lost its gate result."""
        _main, seat = _seat(tmp_path)
        report = assess_repo_state(seat)
        assert (report["status"], report["surface"]) == ("pass", "healthy"), report["fail_reasons"]
        assert GATE not in report["missing"]
        assert report["not_generated_here"] == [GATE]
        recs = report["recommendations"]
        # /context-load prints the first as NEXT: the orientation reads stay first.
        assert recs[0].startswith(COHERENT), recs
        assert any(GATE in r and "/smoke" in r for r in recs[1:]), recs
        assert not any("rebuild" in r for r in recs), recs

    def test_the_status_block_says_what_is_not_generated_here(self, tmp_path):
        _main, seat = _seat(tmp_path)
        block = render_status_report(assess_repo_state(seat))
        assert "MISSING:" not in block, block
        assert f"PENDING:  {GATE} (this worktree's own; /smoke" in block, block

    def test_a_seat_missing_an_include_entry_is_told_to_copy_it(self, tmp_path):
        """A seat made before ``.worktreeinclude`` listed the reports: the
        audit fails there, so the surface is degraded -- and the fix is the
        copy, named from the main checkout. Dies to: "rebuild" as the remedy."""
        main, seat = _seat(tmp_path, copy=(".claude/settings.json",))
        report = assess_repo_state(seat)
        assert report["surface"] == "DEGRADED"
        recs = " ".join(report["recommendations"])
        for rel in ("reports/repo_fingerprint.json", "reports/harness_config.json"):
            assert str(main / rel) in recs, (rel, recs)
        assert "rebuild" not in recs, recs

    def test_a_tracked_file_deleted_in_a_seat_is_damage_never_a_copy(self, tmp_path):
        """A tracked file's fix is git's; a copy from the main checkout could be
        another branch's. Dies to: the copy advice taken for every missing file
        the main checkout has (the include's claim made about a tracked path)."""
        main, seat = _seat(tmp_path)
        (seat / "cc" / "COMMANDS.md").unlink()
        (seat / "reports" / "repo_fingerprint.json").unlink()
        report = assess_repo_state(seat)
        assert report["surface"] == "DEGRADED"
        recs = report["recommendations"]
        copy = [r for r in recs if r.startswith("a linked worktree checks out")]
        assert len(copy) == 1 and str(main / "reports" / "repo_fingerprint.json") in copy[0], recs
        assert "COMMANDS.md" not in copy[0], copy
        assert any(r.startswith("rebuild or re-audit") for r in recs), recs

    def test_a_seat_without_the_settings_file_is_degraded_never_told_to_init(self, tmp_path):
        """No copied settings: a session launched here loads none of the hooks.
        Read as a fresh source checkout, the seat was called healthy and told
        to run ``espalier init .``, which redeploys the harness into it."""
        main, seat = _seat(tmp_path, copy=())
        report = assess_repo_state(seat)
        assert report["surface"] == "DEGRADED"
        recs = " ".join(report["recommendations"])
        assert str(main / ".claude" / "settings.json") in recs, recs
        assert "loads none of the harness's hooks" in recs, recs
        assert "espalier init" not in recs, recs

    def test_a_manifest_entry_for_a_record_never_copied_is_not_damage(self, tmp_path):
        """An adopter's manifest may list the gate result; in a seat that entry
        is the same not-yet record, not a missing promise. Dies to: the
        manifest list left unfiltered in a seat."""
        _main, seat = _seat(tmp_path, manifest=f"{GATE}\n")
        report = assess_repo_state(seat)
        assert report["manifest_missing_docs"] == [], report["manifest_missing_docs"]
        assert report["surface"] == "healthy", report["fail_reasons"]

    def test_a_seat_of_an_uninitialized_checkout_reads_as_a_source_checkout(self, tmp_path):
        """Guard: where the main checkout has no runtime files either, the
        seat is the pre-init state it always was. Green before and after."""
        _main, seat = _seat(tmp_path, copy=(), initialized=False)
        report = assess_repo_state(seat)
        assert report["surface"] == "healthy"
        assert any("espalier init" in r for r in report["recommendations"])

    def test_a_corrupt_gate_result_in_a_seat_still_fails(self, tmp_path):
        """Guard: a record the seat DID write and cannot read is damage."""
        _main, seat = _seat(tmp_path)
        _write(seat, GATE, "{")
        report = assess_repo_state(seat)
        assert report["surface"] == "DEGRADED"
        assert GATE in report["unreadable_reports"]

    def test_a_main_checkout_missing_its_gate_result_still_fails(self, tmp_path):
        """Guard: the exemption is a seat's alone."""
        main = _main_checkout(tmp_path)
        (main / GATE).unlink()
        report = assess_repo_state(main)
        assert report["surface"] == "DEGRADED"
        assert GATE in report["missing"]
        assert report["not_generated_here"] == []


def _verify(repo: Path) -> int:
    from espalier.cli import cmd_integrity
    return cmd_integrity(argparse.Namespace(repo=str(repo), action="verify"))


class TestIntegrityVerifyReadsASeat:
    """``espalier integrity verify`` -- ``/preflight``'s integrity step -- on a
    seat with no manifest says what the SessionStart banner says, and passes."""

    def test_a_fresh_seat_without_a_manifest_is_a_note_not_a_failure(
            self, tmp_path, monkeypatch, capsys):
        """Dies to: the seat read as an initialized checkout whose manifest
        was removed (exit 1, "create one ... in your own terminal")."""
        _main, seat = _seat(tmp_path)
        monkeypatch.chdir(seat)
        assert _verify(seat) == 0
        out = capsys.readouterr().out
        assert "no manifest in this worktree (per checkout, gitignored)" in out, out
        assert "-m espalier integrity refresh ." in out, out
        assert "loads none" not in out, out

    def test_a_seat_without_its_settings_is_never_sent_to_init(
            self, tmp_path, monkeypatch, capsys):
        """A seat whose settings copy never arrived reads to ``detect_repo_mode``
        as a fresh source checkout, and verify told it to run ``init``. Dies to:
        the seat asked after the mode branch."""
        main, seat = _seat(tmp_path, copy=())
        monkeypatch.chdir(seat)
        assert _verify(seat) == 0
        out = capsys.readouterr().out
        assert "espalier init" not in out, out
        assert "no manifest in this worktree" in out, out
        assert str(main / ".claude" / "settings.json") in out, out

    @pytest.mark.parametrize("reader", ["verify", "resume"])
    def test_a_seat_holding_its_copies_is_a_seat_whatever_its_main_holds_now(
            self, tmp_path, monkeypatch, capsys, reader):
        """The seat's copies arrived; the main checkout's runtime files have
        since gone (or the seat's main is a clone with none, as a driven
        2026-10-13 seat of a --no-checkout clone was). Asking only the main
        checkout read the seat as an initialized tree whose manifest was
        removed, and verify exited 1. Dies to: initialized judged on the main
        checkout alone."""
        main, seat = _seat(tmp_path)
        for rel in (*INCLUDED, GATE):
            (main / rel).unlink()
        if reader == "verify":
            monkeypatch.chdir(seat)
            assert _verify(seat) == 0
            assert "no manifest in this worktree" in capsys.readouterr().out
        else:
            report = assess_repo_state(seat)
            assert report["surface"] == "healthy", report["fail_reasons"]
            assert report["not_generated_here"] == [GATE]

    def test_the_main_checkout_without_a_manifest_still_fails(self, tmp_path, monkeypatch):
        """Guard: an initialized main checkout whose manifest is gone had it
        removed; that stays the red it was. Green before and after."""
        main = _main_checkout(tmp_path)
        monkeypatch.chdir(main)
        assert _verify(main) == 1

    def test_a_seat_with_its_settings_reads_as_initialized(self, tmp_path):
        """The premise this lane was assigned with -- that ``detect_repo_mode``
        misreads a seat -- did not reproduce: the seat's hooks are wired, so
        "initialized" is the right answer, and every fix here asks about the
        seat beside the mode, never lowers it. Pinned so a later reading does
        not re-open it from the code alone."""
        from espalier.repo_mode import REPO_MODE_INITIALIZED_CONSUMER, detect_repo_mode

        _main, seat = _seat(tmp_path)
        assert detect_repo_mode(seat) == REPO_MODE_INITIALIZED_CONSUMER


def _predicates():
    """The three copies of one rule, one per side of the import walls: the
    engine (which cannot import ``tools/cc``), the standalone resume script
    (which cannot import the engine) and the hooks (the banner's own).
    ``scripts/record_snapshot.py::linked_worktree_main`` is a different rule --
    it asks git, which a hook's budget and resume's no-spawn read cannot -- and
    is not held here."""
    from espalier._safe_walk import linked_worktree_main
    return {
        "engine": linked_worktree_main,
        "resume": session_resume._linked_worktree_main,
        "hook": _integrity._linked_worktree_main,
    }


def _resolved(path: Path | None) -> Path | None:
    return None if path is None else path.resolve()


class TestTheSeatPredicatesAgree:
    """One question -- is this root a linked worktree, and of which main
    checkout -- answered in three places, so the banner, ``/status`` and
    ``/preflight`` never read one seat three ways again."""

    def test_they_agree_on_every_shape_git_writes(self, tmp_path):
        main, seat = _seat(tmp_path)
        submodule = tmp_path / "sub"
        submodule.mkdir()
        (main / ".git" / "modules" / "sub").mkdir(parents=True)
        (submodule / ".git").write_text(f"gitdir: {main / '.git' / 'modules' / 'sub'}\n",
                                        encoding="utf-8")
        bare = tmp_path / "proj.git"
        _git(tmp_path, "clone", "-q", "--bare", str(main), str(bare))
        bare_seat = tmp_path / "bare-seat"
        _git(bare, "worktree", "add", "-q", "--detach", str(bare_seat))
        crlf = tmp_path / "crlf"
        crlf.mkdir()
        (crlf / ".git").write_bytes(
            f"gitdir: {main / '.git' / 'worktrees' / 'seat'}  \r\n".encode())
        plain = tmp_path / "plain"
        plain.mkdir()
        expected = {seat: main.resolve(), crlf: main.resolve(), main: None,
                    submodule: None, bare_seat: None, plain: None}
        for name, predicate in _predicates().items():
            for root, want in expected.items():
                assert _resolved(predicate(root)) == want, (name, root.name)

    @pytest.mark.parametrize("copy", ["engine", "resume", "hook"])
    def test_a_gitlink_whose_admin_directory_is_gone_is_no_seat(self, tmp_path, copy):
        """An export that carried a worktree's gitlink, or a seat whose main
        checkout moved, names a directory that is not there: not a seat, so
        the main-checkout readings stand -- the same in all three readers."""
        export = tmp_path / "export"
        export.mkdir()
        (export / ".git").write_text("gitdir: /nonexistent/main/.git/worktrees/x\n",
                                     encoding="utf-8")
        assert _predicates()[copy](export) is None

    @pytest.mark.parametrize("copy", ["engine", "resume", "hook"])
    def test_a_relative_gitdir_resolves_against_the_seat(self, tmp_path, copy, monkeypatch):
        """git 2.48's ``worktree.useRelativePaths`` writes the gitlink
        relative to the seat; read against the process's directory, the main
        checkout named would be wrong wherever the reader runs from."""
        main, seat = _seat(tmp_path)
        relative = "gitdir: ../main/.git/worktrees/seat\n"
        # Git for Windows marks the .git it writes hidden, and a "w" open
        # (create-truncate) of a hidden file is access-denied: rewrite in place.
        with (seat / ".git").open("r+", encoding="utf-8") as gitlink:
            gitlink.write(relative)
            gitlink.truncate()
        assert (seat / ".git").read_text(encoding="utf-8") == relative, "precondition: the gitlink is relative"
        monkeypatch.chdir(tmp_path.parent)
        assert _resolved(_predicates()[copy](seat)) == main.resolve()
