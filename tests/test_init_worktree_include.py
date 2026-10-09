"""DEF-1192: ``espalier init`` and ``upgrade`` write ``.worktreeinclude``.

Claude Code reads the shared ``.claude/settings.json`` from the session's own
directory, and a git worktree checks out tracked files only -- so on a tree
that gitignores the settings file (every ordinary install), a session launched
in a worktree Claude Code created (``claude --worktree``, a subagent worktree,
a background session) loads none of the harness's hooks: no banner, no guards,
no stop gate, and nothing says so (measured 2026-10-08 on two background
sessions). ``.worktreeinclude`` at the repo root lists the gitignored files
Claude Code copies into each worktree it creates; the self-host tree carried
one by hand and no adopter received it.

Sister to ``test_init_gitignore_default.py``: the same append-only, own-line-
ending, runs-when-absent contract, for the one other file a worktree session
needs. The doctor side lives in ``tests/test_doctor.py`` (the warn-state
ratchet carries ``_worktree_include_missing``).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests._git_oracle import require_is_gitignored
from espalier import cli
from espalier.cli import (
    REQUIRED_GITIGNORE,
    WORKTREE_INCLUDE_ENTRIES,
    WORKTREE_INCLUDE_FILE,
    WORKTREE_INCLUDE_HEADER,
    _gitignore_key,
    _handle_worktree_include,
    worktree_include_status,
)


def _entries(path: Path) -> list[str]:
    """The non-comment, non-blank lines of an include file, as written."""
    return [
        ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]


class TestTheEntries:
    def test_the_settings_file_is_the_entry(self) -> None:
        assert ".claude/settings.json" in WORKTREE_INCLUDE_ENTRIES

    def test_every_entry_is_a_required_gitignore_path(self) -> None:
        """Claude Code copies a listed path only when git ignores it, so an
        entry the harness does not also gitignore would be inert: the tuple is
        pinned as a subset of the gitignore block."""
        ignored = {_gitignore_key(e) for e in REQUIRED_GITIGNORE}
        for entry in WORKTREE_INCLUDE_ENTRIES:
            assert _gitignore_key(entry) in ignored, entry

    def test_the_header_is_a_comment(self) -> None:
        assert WORKTREE_INCLUDE_HEADER.startswith("#")
        assert "\n" not in WORKTREE_INCLUDE_HEADER


class TestStatus:
    def test_an_absent_file_lacks_every_entry(self, tmp_path: Path) -> None:
        status = worktree_include_status(tmp_path, withheld={})
        assert status.exists is False
        assert status.missing == WORKTREE_INCLUDE_ENTRIES
        assert status.unreadable is None

    def test_a_file_carrying_the_entry_lacks_nothing(self, tmp_path: Path) -> None:
        (tmp_path / WORKTREE_INCLUDE_FILE).write_text(
            ".claude/settings.json\n", encoding="utf-8")
        status = worktree_include_status(tmp_path, withheld={})
        assert status.exists is True
        assert status.missing == ()

    def test_a_comment_or_blank_line_is_not_an_entry(self, tmp_path: Path) -> None:
        (tmp_path / WORKTREE_INCLUDE_FILE).write_text(
            "# .claude/settings.json\n\n   \n", encoding="utf-8")
        assert worktree_include_status(tmp_path, withheld={}).missing == WORKTREE_INCLUDE_ENTRIES

    def test_a_backslash_spelling_and_a_bom_count(self, tmp_path: Path) -> None:
        """A Windows editor's spelling of the same path, under a BOM."""
        (tmp_path / WORKTREE_INCLUDE_FILE).write_bytes(
            b"\xef\xbb\xbf.claude\\settings.json\r\n")
        assert worktree_include_status(tmp_path, withheld={}).missing == ()

    def test_a_tracked_entry_is_inert_not_missing(self, tmp_path: Path) -> None:
        """DEF-11: a repo that commits `.claude/settings.json` has it in every
        worktree already, and Claude Code copies only a gitignored path."""
        status = worktree_include_status(tmp_path, withheld={".claude/settings.json": ["tracked"]})
        assert status.missing == ()
        assert status.inert == (".claude/settings.json",)

    def test_a_header_already_present_is_seen(self, tmp_path: Path) -> None:
        (tmp_path / WORKTREE_INCLUDE_FILE).write_text(
            WORKTREE_INCLUDE_HEADER + "\n.claude/settings.json\n", encoding="utf-8")
        assert worktree_include_status(tmp_path, withheld={}).has_header is True

    def test_an_unreadable_file_is_reported_not_guessed(self, tmp_path: Path) -> None:
        (tmp_path / WORKTREE_INCLUDE_FILE).mkdir()  # a directory in its place
        status = worktree_include_status(tmp_path, withheld={})
        assert status.exists is True
        assert status.missing == WORKTREE_INCLUDE_ENTRIES
        assert status.unreadable


class TestTheWrite:
    def test_an_absent_file_is_created_with_header_and_entry(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        still = _handle_worktree_include(tmp_path, write=True, rerun_hint="hint", withheld={})
        assert still == []
        path = tmp_path / WORKTREE_INCLUDE_FILE
        assert _entries(path) == list(WORKTREE_INCLUDE_ENTRIES)
        assert path.read_text(encoding="utf-8").splitlines()[0] == WORKTREE_INCLUDE_HEADER
        out = capsys.readouterr().out
        assert f"Wrote {WORKTREE_INCLUDE_FILE}" in out
        assert "worktree" in out and "Commit the file" in out

    def test_an_existing_file_keeps_its_lines_and_gains_the_entry(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / WORKTREE_INCLUDE_FILE
        path.write_text(".env.local\n", encoding="utf-8")
        assert _handle_worktree_include(tmp_path, write=True, rerun_hint="hint", withheld={}) == []
        assert _entries(path) == [".env.local", *WORKTREE_INCLUDE_ENTRIES]
        assert path.read_text(encoding="utf-8").startswith(".env.local\n")
        assert f"Appended to {WORKTREE_INCLUDE_FILE}" in capsys.readouterr().out

    def test_a_file_already_carrying_the_entry_is_untouched(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / WORKTREE_INCLUDE_FILE
        before = b"# mine\n.claude/settings.json\n"
        path.write_bytes(before)
        assert _handle_worktree_include(tmp_path, write=True, rerun_hint="hint", withheld={}) == []
        assert path.read_bytes() == before
        assert capsys.readouterr().out == ""

    @pytest.mark.parametrize("eol", [b"\n", b"\r\n"], ids=["lf", "crlf"])
    def test_the_append_follows_the_files_own_line_ending(
        self, tmp_path: Path, eol: bytes
    ) -> None:
        path = tmp_path / WORKTREE_INCLUDE_FILE
        path.write_bytes(b"first" + eol + b"second" + eol)
        _handle_worktree_include(tmp_path, write=True, rerun_hint="hint", withheld={})
        data = path.read_bytes()
        other = b"\n" if eol == b"\r\n" else b"\r\n"
        assert other not in data.replace(eol, b""), data
        assert data.endswith(eol)

    def test_a_file_with_no_terminator_gets_its_line_closed_first(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / WORKTREE_INCLUDE_FILE
        path.write_bytes(b"first")
        _handle_worktree_include(tmp_path, write=True, rerun_hint="hint", withheld={})
        assert _entries(path) == ["first", *WORKTREE_INCLUDE_ENTRIES]

    def test_the_header_is_written_once_when_the_roster_grows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A second roster member on a later upgrade must not append a second
        header line to every adopter's file (failure-mode review)."""
        _handle_worktree_include(tmp_path, write=True, rerun_hint="hint", withheld={})
        monkeypatch.setattr(cli, "WORKTREE_INCLUDE_ENTRIES", (".claude/settings.json", ".espalier/integrity.json"))
        _handle_worktree_include(tmp_path, write=True, rerun_hint="hint", withheld={})
        text = (tmp_path / WORKTREE_INCLUDE_FILE).read_text(encoding="utf-8")
        assert text.count(WORKTREE_INCLUDE_HEADER) == 1, text
        assert _entries(tmp_path / WORKTREE_INCLUDE_FILE) == [".claude/settings.json", ".espalier/integrity.json"]

    def test_a_tracked_entry_is_not_written_and_is_said(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        still = _handle_worktree_include(
            tmp_path, write=True, rerun_hint="hint", withheld={".claude/settings.json": ["x"]})
        assert still == []
        assert not (tmp_path / WORKTREE_INCLUDE_FILE).exists()
        out = capsys.readouterr().out
        assert "not written" in out and "tracks .claude/settings.json" in out, out

    def test_a_dry_run_reports_and_writes_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        still = _handle_worktree_include(
            tmp_path, write=False, rerun_hint="Re-run with --execute.", withheld={})
        assert still == list(WORKTREE_INCLUDE_ENTRIES)
        assert not (tmp_path / WORKTREE_INCLUDE_FILE).exists()
        out = capsys.readouterr().out
        assert f"WARN: {WORKTREE_INCLUDE_FILE} lacks .claude/settings.json (no such file)" in out
        assert "Re-run with --execute." in out

    def test_a_write_that_fails_degrades_to_the_lines_by_hand(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unwritable path is a one-line manual step, never an abort: the
        lines are printed and the entry is returned as still missing."""
        def _refuse(*a, **k):
            raise OSError(13, "Permission denied", str(tmp_path / WORKTREE_INCLUDE_FILE))
        monkeypatch.setattr("builtins.open", _refuse)
        still = _handle_worktree_include(tmp_path, write=True, rerun_hint="hint", withheld={})
        assert still == list(WORKTREE_INCLUDE_ENTRIES)
        out = capsys.readouterr().out
        assert "WARN: could not write" in out
        assert ".claude/settings.json" in out

    def test_an_unreadable_file_is_never_appended_to(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / WORKTREE_INCLUDE_FILE).mkdir()
        still = _handle_worktree_include(tmp_path, write=True, rerun_hint="hint", withheld={})
        assert still == list(WORKTREE_INCLUDE_ENTRIES)
        assert "WARN: could not read" in capsys.readouterr().out


# ── the real commands ────────────────────────────────────────────────────────

@pytest.fixture
def fresh_repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# placeholder\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    return tmp_path


def _run(repo: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "espalier.cli", *argv],
        cwd=repo, capture_output=True, text=True, check=False, encoding="utf-8",
    )


class TestTheRealCommands:
    """``init``, a second ``init``, ``upgrade`` in both modes and ``doctor``,
    each as a subprocess on a throwaway repo."""

    def test_init_writes_the_include_on_a_fresh_repo(self, fresh_repo: Path) -> None:
        result = _run(fresh_repo, "init", str(fresh_repo))
        assert result.returncode == 0, result.stdout + result.stderr
        path = fresh_repo / WORKTREE_INCLUDE_FILE
        assert path.is_file(), result.stdout
        assert _entries(path) == list(WORKTREE_INCLUDE_ENTRIES)
        assert f"Wrote {WORKTREE_INCLUDE_FILE}" in result.stdout
        # The file is meant to be committed: not caught by the harness's own block.
        assert require_is_gitignored(fresh_repo, WORKTREE_INCLUDE_FILE) is False, (
            "init's gitignore block must not hide the include")


    def test_a_second_init_leaves_the_include_untouched(self, fresh_repo: Path) -> None:
        assert _run(fresh_repo, "init", str(fresh_repo)).returncode == 0
        path = fresh_repo / WORKTREE_INCLUDE_FILE
        before = path.read_bytes()
        result = _run(fresh_repo, "init", str(fresh_repo))
        assert result.returncode == 0, result.stdout + result.stderr
        assert path.read_bytes() == before
        assert WORKTREE_INCLUDE_FILE not in result.stdout


    def test_upgrade_reports_a_missing_include_and_execute_writes_it(self, fresh_repo: Path) -> None:
        """A tree initialised before this file existed: the dry run names the gap
        and writes nothing; ``--execute`` writes it."""
        assert _run(fresh_repo, "init", str(fresh_repo)).returncode == 0
        path = fresh_repo / WORKTREE_INCLUDE_FILE
        path.unlink()

        dry = _run(fresh_repo, "upgrade", str(fresh_repo))
        assert dry.returncode == 0, dry.stdout + dry.stderr
        assert f"WARN: {WORKTREE_INCLUDE_FILE} lacks .claude/settings.json (no such file)" in dry.stdout
        assert not path.exists()

        run = _run(fresh_repo, "upgrade", str(fresh_repo), "--execute")
        assert run.returncode == 0, run.stdout + run.stderr
        assert path.is_file()
        assert _entries(path) == list(WORKTREE_INCLUDE_ENTRIES)


    def test_doctor_names_a_missing_include_and_is_quiet_with_it(self, fresh_repo: Path) -> None:
        from espalier.doctor import run_doctor_check

        assert _run(fresh_repo, "init", str(fresh_repo)).returncode == 0
        clean = run_doctor_check(fresh_repo, skip_self_host=True)
        assert not any(WORKTREE_INCLUDE_FILE in w for w in clean["warnings"]), clean["warnings"]

        (fresh_repo / WORKTREE_INCLUDE_FILE).unlink()
        result = run_doctor_check(fresh_repo, skip_self_host=True)
        hits = [w for w in result["warnings"] if WORKTREE_INCLUDE_FILE in w]
        assert hits and "loads none of the hooks" in hits[0], result["warnings"]
        assert any(WORKTREE_INCLUDE_FILE in s for s in result["next_steps"]), result["next_steps"]


    def test_doctor_is_quiet_when_the_repo_tracks_its_settings_file(self, fresh_repo: Path) -> None:
        """DEF-11: a repo that commits ``.claude/settings.json`` has it in every
        worktree already, so the include is inert there and doctor says nothing."""
        from espalier.doctor import run_doctor_check

        (fresh_repo / ".claude").mkdir()
        (fresh_repo / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
        subprocess.run(["git", "add", ".claude/settings.json"], cwd=fresh_repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "settings"], cwd=fresh_repo, check=True)
        init = _run(fresh_repo, "init", str(fresh_repo))
        assert init.returncode == 0, init.stdout + init.stderr
        assert not (fresh_repo / WORKTREE_INCLUDE_FILE).exists(), "inert on a tracked settings file"
        assert f"{WORKTREE_INCLUDE_FILE} not written" in init.stdout, init.stdout
        result = run_doctor_check(fresh_repo, skip_self_host=True)
        assert not any(WORKTREE_INCLUDE_FILE in w for w in result["warnings"]), result["warnings"]
        dry = _run(fresh_repo, "upgrade", str(fresh_repo))
        assert WORKTREE_INCLUDE_FILE not in dry.stdout, dry.stdout

    def test_a_gitignore_that_hides_the_include_is_named(self, fresh_repo: Path) -> None:
        """A dotfile catch-all: the file is written and would never reach a
        commit, so the other machine's worktrees run unhooked (failure-mode
        review). init says so with the one line that fixes it."""
        (fresh_repo / ".gitignore").write_text(".*\n!.gitignore\n", encoding="utf-8")
        result = _run(fresh_repo, "init", str(fresh_repo))
        assert result.returncode == 0, result.stdout + result.stderr
        assert (fresh_repo / WORKTREE_INCLUDE_FILE).is_file()
        assert f"your .gitignore hides {WORKTREE_INCLUDE_FILE}" in result.stdout, result.stdout
        assert f"!{WORKTREE_INCLUDE_FILE}" in result.stdout, result.stdout

