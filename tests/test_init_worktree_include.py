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

    def test_every_entry_is_covered_by_a_required_gitignore_path(self) -> None:
        """Claude Code copies a listed path only when git ignores it, so an
        entry the harness does not also gitignore would be inert: every entry
        is pinned as one the gitignore block covers, by its own line or by a
        directory line above it (the reports under ``/reports/``)."""
        for entry in WORKTREE_INCLUDE_ENTRIES:
            assert cli._gitignore_entry_covering(entry, REQUIRED_GITIGNORE), entry

    def test_coverage_is_a_directory_above_never_a_neighbour(self) -> None:
        """Dies to: a prefix match on the bare key (``reports2/x`` read as
        under ``/reports/``) or a file line read as a directory."""
        assert cli._gitignore_entry_covering("reports/repo_fingerprint.json", ["/reports/"]) == "/reports/"
        assert cli._gitignore_entry_covering("reports2/x.json", ["/reports/"]) is None
        assert cli._gitignore_entry_covering("cc/GOAL.md/x", ["cc/GOAL.md"]) is None
        assert cli._gitignore_entry_covering("src/main.py", REQUIRED_GITIGNORE) is None

    def test_every_entry_names_what_a_worktree_loses_without_it(self) -> None:
        for entry in WORKTREE_INCLUDE_ENTRIES:
            assert entry in cli._WORKTREE_INCLUDE_LOSS, entry

    def test_a_missing_report_never_reads_as_no_hooks(self) -> None:
        """Each message names the loss its own missing entries cause."""
        reports_only = cli.worktree_include_loss(("reports/repo_fingerprint.json", "reports/harness_config.json"))
        assert "hooks" not in reports_only and "harness audit" in reports_only
        assert reports_only.count("harness audit") == 1  # one loss, said once
        # the audit names a missing report itself, and an adopter has no
        # release gate: neither belongs in the reports' loss (failure-mode review)
        assert "says so" not in reports_only and "release gate" not in reports_only
        both = cli.worktree_include_loss(WORKTREE_INCLUDE_ENTRIES)
        assert "loads none of the hooks, and nothing in that session says so" in both
        assert "harness audit" in both

    def test_every_audit_input_the_harness_ignores_rides_the_include(self) -> None:
        """Derived, not a hand copy: each file the audit requires that the
        harness gitignores must be copied into a worktree, or a worktree session
        fails the audit on it. Dies to: a report dropped from the roster, or a
        new ignored audit input the include never learns of."""
        from espalier.proofs import AUDIT_REQUIRED_FILES

        ignored = [rel for rel in AUDIT_REQUIRED_FILES
                   if cli._gitignore_entry_covering(rel, REQUIRED_GITIGNORE)]
        assert len(ignored) >= 3, ignored  # settings and both reports: never vacuous
        for rel in ignored:
            assert rel in WORKTREE_INCLUDE_ENTRIES, rel

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
            ".claude/settings.json\nreports/repo_fingerprint.json\nreports/harness_config.json\n", encoding="utf-8")
        status = worktree_include_status(tmp_path, withheld={})
        assert status.exists is True
        assert status.missing == ()

    def test_a_file_from_before_the_reports_lacks_only_the_reports(self, tmp_path: Path) -> None:
        """Every install from before 2026-10-12 lists the settings file alone."""
        (tmp_path / WORKTREE_INCLUDE_FILE).write_text(".claude/settings.json\n", encoding="utf-8")
        assert worktree_include_status(tmp_path, withheld={}).missing == (
            "reports/repo_fingerprint.json", "reports/harness_config.json")

    def test_a_comment_or_blank_line_is_not_an_entry(self, tmp_path: Path) -> None:
        (tmp_path / WORKTREE_INCLUDE_FILE).write_text(
            "# .claude/settings.json\n\n   \n", encoding="utf-8")
        assert worktree_include_status(tmp_path, withheld={}).missing == WORKTREE_INCLUDE_ENTRIES

    def test_a_backslash_spelling_and_a_bom_count(self, tmp_path: Path) -> None:
        """A Windows editor's spelling of the same path, under a BOM."""
        (tmp_path / WORKTREE_INCLUDE_FILE).write_bytes(
            b"\xef\xbb\xbf.claude\\settings.json\r\n"
            b"reports\\repo_fingerprint.json\r\nreports\\harness_config.json\r\n")
        assert worktree_include_status(tmp_path, withheld={}).missing == ()

    def test_a_tracked_entry_is_inert_not_missing(self, tmp_path: Path) -> None:
        """DEF-11: a repo that commits `.claude/settings.json` has it in every
        worktree already, and Claude Code copies only a gitignored path."""
        status = worktree_include_status(tmp_path, withheld={".claude/settings.json": ["tracked"]})
        assert status.missing == ("reports/repo_fingerprint.json", "reports/harness_config.json")
        assert status.inert == (".claude/settings.json",)

    def test_a_declined_reports_line_leaves_the_reports_out(self, tmp_path: Path) -> None:
        """``gitignore_declined = ["/reports/"]`` leaves the reports unignored,
        and Claude Code copies only an ignored path: listing them would do
        nothing while the message said they were copied (failure-mode review,
        driven 2026-10-12)."""
        status = worktree_include_status(tmp_path, withheld={}, declined=["/reports/"])
        assert status.declined == ("reports/repo_fingerprint.json", "reports/harness_config.json")
        assert status.missing == (".claude/settings.json",) and status.inert == ()

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
        before = b"# mine\n.claude/settings.json\nreports/repo_fingerprint.json\nreports/harness_config.json\n"
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
        with monkeypatch.context() as m:  # the roster as every install before 2026-10-12 had it
            m.setattr(cli, "WORKTREE_INCLUDE_ENTRIES", (".claude/settings.json",))
            _handle_worktree_include(tmp_path, write=True, rerun_hint="hint", withheld={})
        _handle_worktree_include(tmp_path, write=True, rerun_hint="hint", withheld={})
        text = (tmp_path / WORKTREE_INCLUDE_FILE).read_text(encoding="utf-8")
        assert text.count(WORKTREE_INCLUDE_HEADER) == 1, text
        assert _entries(tmp_path / WORKTREE_INCLUDE_FILE) == list(WORKTREE_INCLUDE_ENTRIES)

    def test_a_tracked_entry_is_not_written_and_is_said(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A repo that tracks its settings file still needs the reports in a
        worktree: they are written, and the settings line is said left out."""
        still = _handle_worktree_include(
            tmp_path, write=True, rerun_hint="hint", withheld={".claude/settings.json": ["x"]})
        assert still == []
        assert _entries(tmp_path / WORKTREE_INCLUDE_FILE) == [
            "reports/repo_fingerprint.json", "reports/harness_config.json"]
        out = capsys.readouterr().out
        assert ".claude/settings.json left out: this repo tracks it" in out, out
        assert "hooks" not in out.split("left out")[0], out  # the written lines cost the audit, not the hooks

    def test_every_entry_tracked_writes_nothing_and_says_so(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        still = _handle_worktree_include(
            tmp_path, write=True, rerun_hint="hint",
            withheld={e: ["x"] for e in WORKTREE_INCLUDE_ENTRIES})
        assert still == []
        assert not (tmp_path / WORKTREE_INCLUDE_FILE).exists()
        out = capsys.readouterr().out
        assert "not written" in out, out
        assert f"{', '.join(WORKTREE_INCLUDE_ENTRIES)} left out: this repo tracks them" in out, out

    def test_a_dry_run_reports_and_writes_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        still = _handle_worktree_include(
            tmp_path, write=False, rerun_hint="Re-run with --execute.", withheld={})
        assert still == list(WORKTREE_INCLUDE_ENTRIES)
        assert not (tmp_path / WORKTREE_INCLUDE_FILE).exists()
        out = capsys.readouterr().out
        assert f"WARN: {WORKTREE_INCLUDE_FILE} lacks {', '.join(WORKTREE_INCLUDE_ENTRIES)} (no such file)" in out
        assert "loads none of the hooks" in out and "harness audit" in out
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
        assert f"WARN: {WORKTREE_INCLUDE_FILE} lacks {', '.join(WORKTREE_INCLUDE_ENTRIES)} (no such file)" in dry.stdout
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
        worktree already, so that entry is inert there; init writes the reports
        alone, and doctor and a later upgrade then say nothing."""
        from espalier.doctor import run_doctor_check

        (fresh_repo / ".claude").mkdir()
        (fresh_repo / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
        subprocess.run(["git", "add", ".claude/settings.json"], cwd=fresh_repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "settings"], cwd=fresh_repo, check=True)
        init = _run(fresh_repo, "init", str(fresh_repo))
        assert init.returncode == 0, init.stdout + init.stderr
        assert _entries(fresh_repo / WORKTREE_INCLUDE_FILE) == [
            "reports/repo_fingerprint.json", "reports/harness_config.json"], init.stdout
        assert ".claude/settings.json left out" in init.stdout, init.stdout
        result = run_doctor_check(fresh_repo, skip_self_host=True)
        assert not any(WORKTREE_INCLUDE_FILE in w for w in result["warnings"]), result["warnings"]
        dry = _run(fresh_repo, "upgrade", str(fresh_repo))
        assert f"{WORKTREE_INCLUDE_FILE} lacks" not in dry.stdout, dry.stdout

    def test_a_tracked_report_is_left_out_by_doctor_and_upgrade_alike(self, fresh_repo: Path) -> None:
        """An adopter who commits the reports, with an include from before they
        joined the roster: upgrade leaves them out (every worktree checks them out
        already), and doctor must not warn that the include lacks them. Dies to:
        doctor's input keyed by gitignore lines, under which the warning could
        never clear (both reviewers, driven 2026-10-12)."""
        from espalier.doctor import run_doctor_check

        assert _run(fresh_repo, "init", str(fresh_repo)).returncode == 0
        subprocess.run(["git", "add", "-f", "reports/repo_fingerprint.json", "reports/harness_config.json"],
                       cwd=fresh_repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "track the reports"], cwd=fresh_repo, check=True)
        (fresh_repo / WORKTREE_INCLUDE_FILE).write_text(
            WORKTREE_INCLUDE_HEADER + "\n.claude/settings.json\n", encoding="utf-8")
        result = run_doctor_check(fresh_repo, skip_self_host=True)
        assert not any(WORKTREE_INCLUDE_FILE in w for w in result["warnings"]), result["warnings"]
        dry = _run(fresh_repo, "upgrade", str(fresh_repo))
        assert f"{WORKTREE_INCLUDE_FILE} lacks" not in dry.stdout, dry.stdout

    def test_a_declined_reports_line_is_left_out_and_said(self, fresh_repo: Path) -> None:
        """The example config's own line: init writes the settings file alone and
        says why the reports are not copied; doctor does not warn about them and
        names them as information."""
        from espalier.doctor import run_doctor_check

        (fresh_repo / "espalier.toml").write_text('gitignore_declined = ["/reports/"]\n', encoding="utf-8")
        init = _run(fresh_repo, "init", str(fresh_repo))
        assert init.returncode == 0, init.stdout + init.stderr
        assert _entries(fresh_repo / WORKTREE_INCLUDE_FILE) == [".claude/settings.json"], init.stdout
        assert "gitignore_declined in espalier.toml leaves them unignored" in init.stdout, init.stdout
        result = run_doctor_check(fresh_repo, skip_self_host=True)
        assert not any(WORKTREE_INCLUDE_FILE in w for w in result["warnings"]), result["warnings"]
        assert any("leaves out reports/repo_fingerprint.json" in i for i in result["info"]), result["info"]

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

