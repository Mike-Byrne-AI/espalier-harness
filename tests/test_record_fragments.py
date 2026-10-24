"""Contract tests for ``tools/cc/_record_fragments.py``, the one loader for
the records two lanes both append to (TP-479 Wave C, layers L1 and L8): the
Session Log, written one row per file under ``memory/session-log.d/`` beside
the frozen legacy table, and the changelog's unreleased entries, one file per
lane under ``changelog.d/`` beside ``[Unreleased]``.

These rows pin the loader's reading rules (both forms, newest first by the
date a row carries, only fragment names read, the prune keeping the newest)
because every reader of the two records now reads through it: a loader that
drops a form does not red its readers, it makes them read less and pass. The
census class guards the other half, that no reader goes around the loader.

Each class names the mutation it was seen red against. Everything here runs
in-process over a ``tmp_path`` tree; the two-lane merge test, which needs real
git, lives with the other merge rows in ``tests/test_record_merge.py``.
"""
# pytest-marker: default-unit  (pure functions over a tmp_path tree; no subprocess)
from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import re
import sys
import time
from pathlib import Path

import pytest
from tests._live_tree import checkout_rglob

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_CC = REPO_ROOT / "tools" / "cc"


def _load():
    spec = importlib.util.spec_from_file_location("_record_fragments_under_test",
                                                  TOOLS_CC / "_record_fragments.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rf():
    return _load()


def _row(date: str, lead: str) -> str:
    return f"| {date} | **{lead}** | notes |"


def _memory(*rows: str, extra: str = "") -> str:
    return (
        "# Memory\n\n## Harness Decisions\n\n| Decision | Date | Reason |\n|---|---|---|\n"
        "| keep | 2099-01-01 | a dated cell outside the log |\n\n"
        "## Session Log\n\n| Date | What Happened | Notes |\n|------|--------------|-------|\n"
        + "".join(r + "\n" for r in rows)
        + "\n## Categorized memory\n\n- a pointer\n" + extra
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _fragment(root: Path, name: str, row: str) -> None:
    _write(root / "memory" / "session-log.d" / name, row + "\n")


class TestTheLoaderReadsBothForms:
    """Mutations seen red: dropping the legacy rows; dropping the fragments."""

    def test_legacy_rows_alone_are_read_from_the_session_log_section(self, rf, tmp_path):
        _write(tmp_path / "ESPALIER_MEMORY.md", _memory(_row("2026-10-02", "b"), _row("2026-10-01", "a")))
        rows = rf.session_log_rows(tmp_path)
        assert [r.date for r in rows] == ["2026-10-02", "2026-10-01"]
        assert {r.source for r in rows} == {"ESPALIER_MEMORY.md"}

    def test_a_date_first_row_in_another_table_is_not_a_session(self, rf, tmp_path):
        """An adopter's own table that puts the date first would otherwise
        take the digest's top slot forever."""
        decisions = "\n## Decisions\n\n| Date | Decision |\n|---|---|\n| 2099-01-01 | a decision |\n"
        _write(tmp_path / "ESPALIER_MEMORY.md", _memory(_row("2026-10-01", "a"), extra=decisions))
        assert [r.date for r in rf.session_log_rows(tmp_path)] == ["2026-10-01"]

    def test_a_file_without_the_heading_is_read_whole(self, rf, tmp_path):
        _write(tmp_path / "ESPALIER_MEMORY.md", _row("2026-10-01", "a") + "\n")
        assert [r.date for r in rf.session_log_rows(tmp_path)] == ["2026-10-01"]

    def test_fragments_alone_are_read(self, rf, tmp_path):
        _fragment(tmp_path, "2026-10-10-120000-win.md", _row("2026-10-10", "f"))
        rows = rf.session_log_rows(tmp_path)
        assert [(r.date, r.source) for r in rows] == [
            ("2026-10-10", "memory/session-log.d/2026-10-10-120000-win.md")]

    def test_both_forms_together(self, rf, tmp_path):
        _write(tmp_path / "ESPALIER_MEMORY.md", _memory(_row("2026-10-01", "legacy")))
        _fragment(tmp_path, "2026-10-10-120000-win.md", _row("2026-10-10", "fragment"))
        assert [r.line for r in rf.session_log_rows(tmp_path)] == [
            _row("2026-10-10", "fragment"), _row("2026-10-01", "legacy")]

    def test_the_callers_own_decode_is_used_when_given(self, rf, tmp_path):
        _write(tmp_path / "ESPALIER_MEMORY.md", _memory(_row("2026-10-01", "on disk")))
        rows = rf.session_log_rows(tmp_path, memory_text=_memory(_row("2026-10-03", "passed in")))
        assert [r.line for r in rows] == [_row("2026-10-03", "passed in")]


class TestNewestFirst:
    """Mutations seen red: oldest-first order; fragments sorted by name
    ascending; a legacy row placed below every fragment whatever its date."""

    def test_fragments_newest_name_first_within_a_date(self, rf, tmp_path):
        _fragment(tmp_path, "2026-10-10-080000-win.md", _row("2026-10-10", "morning"))
        _fragment(tmp_path, "2026-10-10-200000-air.md", _row("2026-10-10", "evening"))
        _fragment(tmp_path, "2026-10-09-230000-win-2.md", _row("2026-10-09", "yesterday"))
        assert [r.line for r in rf.session_log_rows(tmp_path)] == [
            _row("2026-10-10", "evening"), _row("2026-10-10", "morning"), _row("2026-10-09", "yesterday")]

    def test_legacy_same_day_rows_keep_file_order(self, rf, tmp_path):
        _write(tmp_path / "ESPALIER_MEMORY.md",
               _memory(_row("2026-10-05", "top"), _row("2026-10-05", "below"), _row("2026-10-04", "older")))
        assert [r.line for r in rf.session_log_rows(tmp_path)] == [
            _row("2026-10-05", "top"), _row("2026-10-05", "below"), _row("2026-10-04", "older")]

    def test_a_legacy_row_landing_after_the_switch_sorts_by_its_date(self, rf, tmp_path):
        """A lane opened before the switch prepends to the table and merges
        after fragments exist: its row is placed by the date it carries."""
        _write(tmp_path / "ESPALIER_MEMORY.md", _memory(_row("2026-10-12", "late legacy")))
        _fragment(tmp_path, "2026-10-11-120000-win.md", _row("2026-10-11", "fragment"))
        assert [r.line for r in rf.session_log_rows(tmp_path)] == [
            _row("2026-10-12", "late legacy"), _row("2026-10-11", "fragment")]

    def test_on_one_date_the_fragment_leads_the_legacy_row(self, rf, tmp_path):
        _write(tmp_path / "ESPALIER_MEMORY.md", _memory(_row("2026-10-11", "legacy")))
        _fragment(tmp_path, "2026-10-11-120000-win.md", _row("2026-10-11", "fragment"))
        assert [r.line for r in rf.session_log_rows(tmp_path)][0] == _row("2026-10-11", "fragment")


class TestOnlyFragmentNamesAreRows:
    """Mutation seen red: every file in the directory read as a row."""

    def test_a_readme_and_a_typo_are_skipped_and_named(self, rf, tmp_path):
        _write(tmp_path / "memory" / "session-log.d" / "README.md", _row("2026-10-10", "not a row") + "\n")
        _fragment(tmp_path, "2026-10-10-1200-win.md", _row("2026-10-10", "short time"))
        _fragment(tmp_path, "2026-10-10-120000-win.md", _row("2026-10-10", "good"))
        good, skipped = rf.session_log_fragments(tmp_path)
        assert [p.name for p in good] == ["2026-10-10-120000-win.md"]
        assert skipped == ["2026-10-10-1200-win.md", "README.md"]
        assert [r.line for r in rf.session_log_rows(tmp_path)] == [_row("2026-10-10", "good")]


class TestRowsFromTextsInHand:
    """The pure core a reader of another commit uses (``git show``, no tree on
    disk): the same order and filter as the file reader. Mutations seen red:
    a non-fragment name read; a CRLF row kept with its carriage return."""

    def test_names_are_filtered_and_order_is_the_loaders(self, rf):
        rows = rf.rows_from_texts(
            [("README.md", "| 2026-10-12 | not a row |\n"),
             ("2026-10-10-120000-win.md", "| 2026-10-10 | older |\r\n"),
             ("2026-10-11-120000-win.md", "| 2026-10-11 | newer |\n")],
            "## Session Log\n| 2026-10-09 | legacy |\n",
        )
        assert [r.line for r in rows] == ["| 2026-10-11 | newer |", "| 2026-10-10 | older |",
                                          "| 2026-10-09 | legacy |"]


class TestTheWriterNamesTheFile:
    def test_the_name_is_the_local_clock_and_the_seat(self, rf):
        """The name takes the wall clock it is handed, never converted: an
        evening handoff four hours behind UTC is named for the operator's
        day, the day its row carries. Mutation seen red: converting to UTC
        (the first cut, which named a 23:30 handoff for tomorrow)."""
        now = dt.datetime(2026, 10, 10, 23, 30, 9, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
        assert rf.session_log_name(now, "win-2") == "2026-10-10-233009-win-2.md"
        assert rf.SESSION_LOG_NAME_RE.match(rf.session_log_name(now, "win-2"))

    def test_the_path_is_under_the_directory_and_the_file_is_not_made(self, rf, tmp_path):
        now = dt.datetime(2026, 10, 10, 18, 5, 9, tzinfo=dt.timezone.utc)
        path = rf.new_session_log_path(tmp_path, seat="air", now=now)
        assert path == tmp_path / "memory" / "session-log.d" / "2026-10-10-180509-air.md"
        assert path.parent.is_dir() and not path.exists()


class TestTheSeatNameSaysAFailedRead:
    def test_a_failed_name_read_refuses_rather_than_naming_the_fragment_local(self, rf, tmp_path, monkeypatch,
                                                                            capsys):
        """A timeout, then a config git cannot parse. Dies to the failed read
        named ``local``, which also picks today's started row as this seat's:
        another unnamed seat's row is taken, or a second is started that the
        handoff refuses."""
        import subprocess

        for failed in (subprocess.TimeoutExpired(["git"], 5),
                       subprocess.CompletedProcess([], 128, "", "fatal: bad config line 3 in file .git/config")):
            def fake(argv, _failed=failed, **kw):
                if isinstance(_failed, BaseException):
                    raise _failed
                return _failed
            monkeypatch.setattr(rf, "run_bounded", fake)
            try:
                got = rf._seat(tmp_path)
            except Exception as exc:  # noqa: BLE001 -- the refusal is the expected answer
                got = exc
            assert isinstance(got, getattr(rf, "SeatNameUnread", ())) and "could not be read" in str(got), got
            assert rf.main(["--root", str(tmp_path), "new", "session-log"]) == 2
            assert "no Session Log row is named" in capsys.readouterr().err
        monkeypatch.setattr(rf, "run_bounded", lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", ""))
        assert rf._seat(tmp_path) == "local"


class TestThePruneKeepsTheNewest:
    """Mutations seen red: pruning the newest fragment; counting the legacy
    rows toward the cap."""

    def _five(self, rf, root):
        for i in range(5):
            _fragment(root, f"2026-10-1{i}-120000-win.md", _row(f"2026-10-1{i}", f"row {i}"))

    def test_the_oldest_beyond_keep_leave_and_the_newest_stay(self, rf, tmp_path):
        self._five(rf, tmp_path)
        left = rf.prune_session_log(tmp_path, keep=3, today="2026-10-20")
        assert [r.date for r in left] == ["2026-10-10", "2026-10-11"]
        kept = sorted(p.name for p in (tmp_path / "memory" / "session-log.d").iterdir())
        assert kept == ["2026-10-12-120000-win.md", "2026-10-13-120000-win.md", "2026-10-14-120000-win.md"]

    def test_the_rows_that_left_are_in_the_archive(self, rf, tmp_path):
        self._five(rf, tmp_path)
        _write(tmp_path / "docs" / "session-archive.md", "# Archive\n")
        rf.prune_session_log(tmp_path, keep=3, today="2026-10-20")
        archive = (tmp_path / "docs" / "session-archive.md").read_text(encoding="utf-8")
        assert archive.startswith("# Archive\n")
        assert "## Pruned 2026-10-20 (via _record_fragments prune)" in archive
        assert _row("2026-10-10", "row 0") in archive and _row("2026-10-11", "row 1") in archive
        assert _row("2026-10-12", "row 2") not in archive

    def test_the_legacy_table_is_neither_counted_nor_touched(self, rf, tmp_path):
        legacy = _memory(*[_row(f"2026-09-{d:02d}", "old") for d in range(1, 29)])
        _write(tmp_path / "ESPALIER_MEMORY.md", legacy)
        self._five(rf, tmp_path)
        assert rf.prune_session_log(tmp_path, keep=5) == []
        assert (tmp_path / "ESPALIER_MEMORY.md").read_text(encoding="utf-8") == legacy

    def test_a_dry_run_names_the_rows_and_changes_nothing(self, rf, tmp_path):
        self._five(rf, tmp_path)
        left = rf.prune_session_log(tmp_path, keep=4, dry_run=True)
        assert [r.date for r in left] == ["2026-10-10"]
        assert len(list((tmp_path / "memory" / "session-log.d").iterdir())) == 5
        assert not (tmp_path / "docs" / "session-archive.md").exists()


class TestUnreleasedReadsTheFileAndTheFragments:
    """Mutations seen red: the fragments dropped; the file's body dropped."""

    _CHANGELOG = ("# Changelog\n\n## [Unreleased]\n\n### Added\n\n- **In the file.**\n\n"
                  "## [0.8.0b2] - 2026-09-27\n\n### Added\n\n- **Released.**\n")

    @staticmethod
    def _opt_in(root: Path) -> None:
        _write(root / "espalier.toml", "changelog_fragments = true\n")

    def test_body_then_fragments_by_name(self, rf, tmp_path):
        self._opt_in(tmp_path)
        _write(tmp_path / "CHANGELOG.md", self._CHANGELOG)
        _write(tmp_path / "changelog.d" / "2026-10-11-b.md", "### Fixed\n\n- **From b.**\n")
        _write(tmp_path / "changelog.d" / "2026-10-10-a.md", "### Added\n\n- **From a.**\n")
        text = rf.unreleased_text(tmp_path)
        assert text.index("In the file.") < text.index("From a.") < text.index("From b.")
        assert "Released." not in text

    def test_no_fragments_is_the_body(self, rf, tmp_path):
        _write(tmp_path / "CHANGELOG.md", self._CHANGELOG)
        assert rf.unreleased_text(tmp_path) == rf.unreleased_body(self._CHANGELOG)

    def test_the_body_regex_is_the_engines(self, rf):
        """The loader is standalone, so it carries its own copy of the
        engine's ``UNRELEASED_BODY_RE``; the two must not drift."""
        from espalier.changelog import UNRELEASED_BODY_RE
        assert rf._UNRELEASED_BODY_RE.pattern == UNRELEASED_BODY_RE.pattern
        assert rf._UNRELEASED_BODY_RE.flags == UNRELEASED_BODY_RE.flags

    def test_the_engine_reads_through_the_loader(self, tmp_path):
        from espalier.changelog import unreleased_text
        self._opt_in(tmp_path)
        _write(tmp_path / "CHANGELOG.md", self._CHANGELOG)
        _write(tmp_path / "changelog.d" / "2026-10-10-a.md", "### Added\n\n- **From a.**\n")
        text = unreleased_text(tmp_path)
        assert "In the file." in text and "From a." in text and "Released." not in text

    def test_a_misnamed_file_is_still_unreleased(self, rf, tmp_path):
        """An entry in a file whose name the pattern rejects is still an
        unreleased entry; dropping it would hide it from the release gate and
        the provenance guard. Mutation seen red: only fragment names read."""
        self._opt_in(tmp_path)
        _write(tmp_path / "CHANGELOG.md", self._CHANGELOG)
        _write(tmp_path / "changelog.d" / "my-entry.md", "### Fixed\n\n- **Misnamed.**\n")
        assert "Misnamed." in rf.unreleased_text(tmp_path)

    def test_without_the_opt_in_the_directory_is_another_tools(self, rf, tmp_path):
        """Review of the Wave C batch: the opt-in gated the writer alone, so
        the readers (the release fold among them) took a towncrier or scriv
        directory's entries as this changelog's. Mutation seen red: the
        reader ungated."""
        _write(tmp_path / "CHANGELOG.md", self._CHANGELOG)
        _write(tmp_path / "changelog.d" / "123.feature.md", "towncrier's own entry\n")
        _write(tmp_path / "changelog.d" / "2026-10-10-a.md", "### Added\n\n- **From a.**\n")
        assert rf.unreleased_text(tmp_path) == rf.unreleased_body(self._CHANGELOG)

    def test_on_this_opted_in_tree_every_changelog_file_is_a_fragment_name(self, rf):
        """Every ``*.md`` here is read as an unreleased entry, misnamed or
        not, while the conflict-marker scans read only fragment names; so a
        misnamed file is refused here, where CI sees it, rather than folding a
        hand-merged entry's leftover markers into the release notes in
        silence (review of the Wave C batch)."""
        assert rf.changelog_fragments_setting(REPO_ROOT)[0]
        _good, skipped = rf.changelog_fragments(REPO_ROOT)
        misnamed = [name for name in skipped if name.endswith(".md")]
        assert not misnamed, (f"changelog.d/ files with no fragment name: {misnamed}; take the name "
                              "from `python tools/cc/_record_fragments.py new changelog`")

    @pytest.mark.parametrize("branch, slug", [
        ("lane/parallel-work-c", "parallel-work-c"), ("lane/_x", "x"), ("Feature/Big Thing", "feature-big-thing"),
        ("lane/", "local"),
    ])
    def test_every_slug_makes_a_name_the_reader_takes(self, rf, branch, slug):
        """Mutation seen red: a slug that keeps a leading `_` (`lane/_x`),
        which the name pattern rejects, so the lane's entries went unread."""
        assert rf.lane_slug(branch) == slug
        assert rf.CHANGELOG_NAME_RE.match(f"2026-10-10-{slug}.md")

    def test_a_lane_finds_its_own_fragment_again(self, rf, tmp_path):
        _write(tmp_path / "changelog.d" / "2026-10-09-parallel-work-c.md", "- x\n")
        assert rf.changelog_path(tmp_path, "lane/parallel-work-c", today="2026-10-11").name == \
            "2026-10-09-parallel-work-c.md"
        assert rf.changelog_path(tmp_path, "lane/other", today="2026-10-11").name == "2026-10-11-other.md"


class TestTheChangelogWriterNeedsTheOptIn:
    """Review of #179: the implement-pack body opened the changelog file
    where the loader and a ``changelog.d/`` existed, and the loader ships to
    every tree, so it opened exactly where another changelog tool keeps its
    directory. The writer now names a file only where ``espalier.toml`` opts
    in. Mutation seen red: the ``new changelog`` verb ungated."""

    def _tree(self, tmp_path, toml: str | None):
        _write(tmp_path / "changelog.d" / "123.feature.md", "towncrier's own entry\n")
        if toml is not None:
            _write(tmp_path / "espalier.toml", toml)
        return tmp_path

    def test_a_tree_with_another_tools_directory_is_refused_with_the_way_on(self, rf, tmp_path, capsys):
        root = self._tree(tmp_path, None)
        assert rf.main(["--root", str(root), "new", "changelog", "--branch", "lane/x"]) == 2
        out = capsys.readouterr()
        assert out.out == "" and "changelog fragments are off here" in out.err
        assert "changelog_fragments = true" in out.err

    def test_the_opt_in_names_the_lanes_file(self, rf, tmp_path, capsys):
        root = self._tree(tmp_path, "changelog_fragments = true\n")
        assert rf.main(["--root", str(root), "new", "changelog", "--branch", "lane/x"]) == 0
        assert re.fullmatch(r"changelog\.d/\d{4}-\d{2}-\d{2}-x\.md\n", capsys.readouterr().out)

    def test_the_opt_in_makes_the_directory_it_names(self, rf, tmp_path, capsys):
        """An opted-in tree with no changelog.d/ yet: the printed path must be
        writable, as the session-log verb's is. Mutation seen red: no mkdir."""
        _write(tmp_path / "espalier.toml", "changelog_fragments = true\n")
        assert rf.main(["--root", str(tmp_path), "new", "changelog", "--branch", "lane/x"]) == 0
        printed = capsys.readouterr().out.strip()
        assert (tmp_path / printed).parent.is_dir() and not (tmp_path / printed).exists()

    def test_this_repository_opts_in(self, rf):
        assert rf.changelog_fragments_setting(REPO_ROOT) == (
            True, "espalier.toml sets changelog_fragments = true")

    @pytest.mark.parametrize("body", [
        None, "", "KEY = true\n", "KEY = false\n", 'KEY = "true"\n', "KEY = yes\n",
        "[table]\nKEY = true\n", "other = 1\nKEY = true  # on\n", "'KEY' = true\n",
    ])
    def test_it_reads_as_ship_reads_handoff_push(self, rf, tmp_path, monkeypatch, body):
        """The same contract as ``ship.handoff_push_setting``, one reader per
        key: only the bare word ``true``, at the top level, is on."""
        monkeypatch.syspath_prepend(str(TOOLS_CC))
        spec = importlib.util.spec_from_file_location("_ship_for_the_opt_in", TOOLS_CC / "ship.py")
        ship = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = ship
        spec.loader.exec_module(ship)
        a, b = tmp_path / "a", tmp_path / "b"
        for root, key in ((a, rf.CHANGELOG_FRAGMENTS_KEY), (b, ship.HANDOFF_PUSH_KEY)):
            root.mkdir()
            if body is not None:
                (root / "espalier.toml").write_text(body.replace("KEY", key), encoding="utf-8")
        assert rf.changelog_fragments_setting(a)[0] is ship.handoff_push_setting(b)[0]


class TestFragmentDirectories:
    def test_a_file_under_a_directory_is_in_it_and_the_directory_is_not(self, rf):
        assert rf.in_fragment_dir("memory/session-log.d/2026-10-10-120000-win.md")
        assert rf.in_fragment_dir("changelog.d\\2026-10-10-x.md")
        assert not rf.in_fragment_dir("memory/session-log.d/")
        assert not rf.in_fragment_dir("memory/session-log.dx/a.md")
        assert not rf.in_fragment_dir("CHANGELOG.md")

    def test_every_name_the_writers_make_is_one_the_copies_take(self, rf, tmp_path):
        """The hooks' and the resolver's copies of the name pattern (one for
        both directories) take every name the loader writes."""
        import datetime as _dt
        spec = importlib.util.spec_from_file_location("_ci_guard_for_fragment_names", TOOLS_CC / "ci_guard.py")
        ci = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = ci
        spec.loader.exec_module(ci)
        copy = ci._FRAGMENT_NAME_RE      # tests/test_hooks.py pins the hooks' and the resolver's equal to it
        now = _dt.datetime(2026, 10, 10, 18, 21, 52)
        names = [rf.new_session_log_path(tmp_path, seat="win-2", now=now).name,
                 rf.changelog_path(tmp_path, "lane/wave-c-review-batch", today="2026-10-10").name]
        for name in names:
            assert copy.match(name), name
        for foreign in ("20261010_120000_someone.md", "123.feature.md", "README.md"):   # scriv, towncrier
            assert not copy.match(foreign), foreign


#: Every copy of the whole set of fragment directories, by module and name: a
#: tuple of the directories (or a roster whose ``/``-ended entries are them).
#: Each must equal the loader's ``FRAGMENT_DIRS``, or a third directory ships
#: unclassified and under-counted (review of #179).
_FULL_SET_COPIES = {
    "tools/cc/ci_guard.py": "_RECORD_FILES",
    "tools/cc/hooks/_hook_utils.py": "RECORD_FILES",
    "tools/cc/record_merge.py": "FRAGMENT_DIRS",
    "scripts/merge_cost_census.py": "RECORD_DIRS",
}
#: Modules that name one directory by its literal, each with why it cannot read
#: the loader's constant. The scan below checks the value of every such literal.
_ONE_DIRECTORY_SITES = {
    "tools/cc/hooks/post_write_check.py": "the prune's gate, read before the loader loads",
    "tools/cc/hooks/session_start.py": "the digest's note for a loader that is missing, so not readable off it",
    "scripts/release_check.py": "an operator line naming the changelog directory",
    "tools/cc/session_summary.py": "the resume index's pointer to where the newest rows live",
    "espalier/cli.py": "the memory prune's note on a folded section (the engine imports nothing from tools/cc)",
    "tools/cc/ship.py": "the row question's pathspec, read without loading the loader on every ship",
    "espalier/surface_contract.py": "the ship decision (the engine imports nothing from tools/cc)",
    "scripts/symbol_census.py": ("a subset on purpose: the two dated records are records, while the "
                                 "ledger's row files are live text with a struck row's line a record"),
    "tools/cc/hooks/_reinject.py": ("the ledger-parser hint's trigger and text, in a hook that loads "
                                    "no sibling beyond its own"),
}
#: Each fragment directory's release bucket, decided once. A new directory
#: reds here until someone decides whether it ships.
_SHIP_DECISIONS = {
    "memory/session-log.d/": ("internal", "the dev log, which ships in no artifact, as ESPALIER_MEMORY.md does not"),
    "changelog.d/": ("public", "unreleased changelog entries, which the release fold reads"),
    "task-packs/ledger.d/": ("public", "the forward ledger's rows, which ship with the ledger"),
    "task-packs/probes.d/": ("public", "the ledger's probes, which ship with the roster"),
}
_DIR_TOKEN_RE = re.compile(
    r"(?<![\w.-])((?:[\w.-]+/)*(?:session-log|changelog|ledger|probes)\.d)(?=/|$|[^\w.-])")


def _dir_literals(root: Path) -> dict[str, list[str]]:
    """Every non-docstring string literal under ``tools/cc``, ``scripts`` and
    ``espalier`` (mirrors excluded) that names a fragment directory, by module.
    Derived, so a copy added anywhere in that scope is seen on arrival."""
    out: dict[str, list[str]] = {}
    for base in ("tools/cc", "scripts", "espalier"):
        for p in checkout_rglob(root / base, "*.py"):
            rel = p.relative_to(root).as_posix()
            if "/_vendor/" in rel or "/assets/" in rel:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            if not any(f"{name}.d" in text for name in ("session-log", "changelog", "ledger", "probes")):
                continue
            tree = ast.parse(text)
            docs = set()
            for node in ast.walk(tree):
                body = getattr(node, "body", None)
                if (isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                        and body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)):
                    docs.add(id(body[0].value))
            tokens = [m.group(1) for node in ast.walk(tree)
                      if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs
                      for m in _DIR_TOKEN_RE.finditer(node.value)]
            if tokens:
                out[rel] = tokens
    return out


def _module_constant(rel: str, name: str):
    """The literal value a module binds to ``name`` at its top level."""
    tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == name for t in targets) and node.value is not None:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{rel} binds no literal {name}")


class TestFragmentDirectoryNamesHaveOneSource:
    """The fragment directories are named in the production modules the two
    registries above list: some copy the whole set, the rest name one
    directory, and the loader owns them. Both directions are pinned: every
    copy equals the loader's, and no module outside the registry names a
    directory at all. Mutations seen red: a third
    directory added to the loader alone; a planted copy in a new module."""

    def test_every_copy_of_the_set_is_the_loaders(self, rf):
        wrong = {}
        for rel, name in _FULL_SET_COPIES.items():
            value = tuple(e for e in _module_constant(rel, name) if e.endswith("/"))
            if value != rf.FRAGMENT_DIRS:
                wrong[f"{rel}::{name}"] = value
        assert not wrong, f"copies that are not the loader's {rf.FRAGMENT_DIRS}: {wrong}"

    def test_every_directory_has_a_ship_decision(self, rf):
        from espalier.surface_contract import classify_release_path

        assert set(_SHIP_DECISIONS) == set(rf.FRAGMENT_DIRS), (
            "a fragment directory with no ship decision (or a decision for one the loader dropped): "
            f"decide it in _SHIP_DECISIONS and espalier/surface_contract.py; {sorted(rf.FRAGMENT_DIRS)}")
        got = {d: classify_release_path(d + "2026-10-10-x.md") for d in _SHIP_DECISIONS}
        assert got == {d: bucket for d, (bucket, _) in _SHIP_DECISIONS.items()}, got

    def test_no_module_outside_the_registry_names_a_directory(self, rf):
        found = _dir_literals(REPO_ROOT)
        known = {"tools/cc/_record_fragments.py", *_FULL_SET_COPIES, *_ONE_DIRECTORY_SITES}
        assert not set(found) - known, (
            "modules that name a fragment directory outside the registry: read the loader's "
            f"constant, or register the copy here with its reason: {sorted(set(found) - known)}")
        names = {d.rstrip("/") for d in rf.FRAGMENT_DIRS}
        names |= {n.rsplit("/", 1)[-1] for n in names}
        stale = {rel: [t for t in tokens if t not in names] for rel, tokens in found.items()}
        assert not any(stale.values()), f"literals naming no directory the loader has: {stale}"

    def test_no_registry_entry_is_stale(self):
        found = _dir_literals(REPO_ROOT)
        stale = [rel for rel in (*_FULL_SET_COPIES, *_ONE_DIRECTORY_SITES) if rel not in found]
        assert not stale, f"registered copies that no longer name a directory: {stale}"

    def test_the_scan_sees_a_planted_copy_and_skips_a_docstring(self, tmp_path):
        _write(tmp_path / "scripts" / "planted.py",
               '"""Reads memory/session-log.d/ in prose."""\nDIRS = ("changelog.d/",)\n')
        _write(tmp_path / "espalier" / "_vendor" / "cc" / "mirror.py", 'X = "changelog.d/"\n')
        assert _dir_literals(tmp_path) == {"scripts/planted.py": ["changelog.d"]}


#: Prose that sends a reader or a session to the memory file as the Session
#: Log row's home, which it has not been since the rows became files: the
#: reader census above reads code signatures, so a sentence in a doc or a
#: command body was invisible to it (review of #179). A back-link to a
#: decision or pattern row (``ESPALIER_MEMORY.md row "<label>"``) is not one:
#: those rows still live in the file.
_TABLE_HOME_PROSE = {
    "the handoff updating the memory file": re.compile(r"update ESPALIER_MEMORY\.md", re.I),
    "the memory file's session log as the row's home": re.compile(r"ESPALIER_MEMORY\.md(?:'s)? session[ -]log", re.I),
    "a row prepended to the memory file": re.compile(
        r"prepend\w*\b[^.\n]{0,40}ESPALIER_MEMORY\.md|ESPALIER_MEMORY\.md[^.\n]{0,15}\bprepend", re.I),
}


def _table_home_prose(root: Path) -> list[str]:
    """``path:line: reason`` for each live doc line that names the memory file
    as the row's home. Scope, stated: the ``.claude`` bodies, ``docs/`` (less
    the external pins and the local archive), every ``CLAUDE.md`` and the
    README; records (``CHANGELOG.md``, ``changelog.d/``, ``memory/``,
    ``task-packs/``) say what was true on their day, and mirrors follow their
    sources."""
    files = [p for d in (".claude/agents", ".claude/commands", ".claude/skills", "docs")
             for p in checkout_rglob(root / d, "*.md")]
    files += [p for p in checkout_rglob(root, "CLAUDE.md")]
    files += [root / "README.md"]
    out = []
    for p in sorted(set(files)):
        rel = p.relative_to(root).as_posix()
        if (not p.is_file() or rel.startswith((".claude/worktrees/", "docs/external/", "espalier/assets/",
                                               "examples/", "memory/", "task-packs/"))
                or rel == "docs/session-archive.md"):
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            out += [f"{rel}:{n}: {reason}" for reason, pat in _TABLE_HOME_PROSE.items() if pat.search(line)]
    return out


class TestNoDocSendsTheRowToTheMemoryFile:
    """The pointer half of the census. Mutation seen red: a planted
    ``update ESPALIER_MEMORY.md session log`` in a command body."""

    def test_no_live_doc_names_the_memory_file_as_the_rows_home(self):
        found = _table_home_prose(REPO_ROOT)
        assert not found, ("these lines send the Session Log row to ESPALIER_MEMORY.md; it is a file "
                           "under memory/session-log.d/: " + "; ".join(found))

    def test_the_scan_sees_a_planted_pointer_and_skips_a_record(self, tmp_path):
        _write(tmp_path / ".claude" / "commands" / "x.md", "Then update ESPALIER_MEMORY.md session log.\n")
        _write(tmp_path / "memory" / "CLAUDE.md", "Prepend the row to ESPALIER_MEMORY.md.\n")
        _write(tmp_path / "docs" / "ok.md", 'Linked from: ESPALIER_MEMORY.md row "A decision".\n')
        _write(tmp_path / "README.md", "nothing here\n")
        assert _table_home_prose(tmp_path) == [
            ".claude/commands/x.md:1: the handoff updating the memory file",
            ".claude/commands/x.md:1: the memory file's session log as the row's home"]


#: Each signature marks a module that reads the Session Log or the unreleased
#: changelog entries by itself: the section heading, the row marker's regex
#: source, or the [Unreleased] body regex (by its owner's name or its source).
_READER_SIGNATURES = {
    "the Session Log heading": "## Session Log",
    "the row marker": r"^\|\s*(\d{4}-\d{2}-\d{2})",
    "the [Unreleased] body regex": "UNRELEASED_BODY_RE",
    "an [Unreleased] regex": r"\[Unreleased\]",
}
#: A call into the loader: what a reader that takes both forms does.
_LOADER_CALLS = ("session_log_rows(", "rows_from_texts(", "unreleased_text(", "load_record_fragments(")
#: Readers that keep reading one file, each with its reason. A stale entry
#: (the file no longer carries a signature) reds, so the list cleans itself.
_DECLARED_ONE_FILE_READERS = {
    "tools/cc/_record_fragments.py": "the loader itself",
    "tools/cc/record_merge.py": "resolves a conflict inside the legacy table itself; a fragment "
                                "never conflicts by shape and is refused by name",
    "espalier/cli.py": "`espalier memory prune` keeps the memory file under its line cap from the "
                       "file's own table; on the folded section (2026-10-10) it holds no table and "
                       "names the fragments' prune, never running it for a line-cap caller",
}


class TestEveryReaderTakesBothForms:
    """The class census Wave C adds. A reader that applies a regex to the one
    file does not red when an entry moves to a fragment: it reads less and
    passes (C0-B). So every production module that carries a reader's
    signature calls the loader, or is declared here with its reason.

    Scope, stated: production code (``tools/cc``, ``scripts``, ``espalier``,
    mirrors excluded), keyed on the four signatures above. A reader that reads
    the file as a whole corpus without naming the section (the tag-parity
    gate) carries no signature and is outside it; tests are outside it too,
    since their fixtures write the heading. Mutation seen red: a module that
    applies ``UNRELEASED_BODY_RE`` to ``CHANGELOG.md`` without the loader."""

    @staticmethod
    def _readers() -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for base in ("tools/cc", "scripts", "espalier"):
            for p in checkout_rglob(REPO_ROOT / base, "*.py"):
                rel = p.relative_to(REPO_ROOT).as_posix()
                if "/_vendor/" in rel or "/assets/" in rel:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
                hits = [name for name, sig in _READER_SIGNATURES.items() if sig in text]
                if hits:
                    out[rel] = hits
        return out

    def test_every_reader_calls_the_loader_or_is_declared(self):
        offenders = []
        for rel, hits in self._readers().items():
            if rel in _DECLARED_ONE_FILE_READERS:
                continue
            text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
            if not any(call in text for call in _LOADER_CALLS):
                offenders.append(f"{rel} ({', '.join(hits)})")
        assert not offenders, (
            "these modules read the Session Log or [Unreleased] from the one file, so a row "
            "or entry written as a fragment is invisible to them: read through "
            "tools/cc/_record_fragments.py, or declare the reason in _DECLARED_ONE_FILE_READERS: "
            + "; ".join(offenders)
        )

    def test_no_declared_reader_is_stale(self):
        readers = self._readers()
        stale = [rel for rel in _DECLARED_ONE_FILE_READERS
                 if (REPO_ROOT / rel).is_file() and rel not in readers]
        assert not stale, f"declared one-file readers that no longer read the record: {stale}"


class TestDecode:
    def test_byte_order_marks_and_bad_bytes(self, rf):
        assert rf.decode(b"\xef\xbb\xbf| 2026") == "| 2026"
        assert rf.decode("| 2026".encode("utf-16")) == "| 2026"
        assert rf.decode(b"| \xff 2026") == "| � 2026"

    def test_line_ends_are_folded(self, rf):
        """A Windows checkout writes a merged-in fragment CRLF beside its own
        LF one; two readers of one record must not differ by that."""
        assert rf.decode(b"- a\r\n- b\n") == "- a\n- b\n"


class TestNewestRowDateBySeat:
    """The Session Log debt is counted from each seat's newest row, read by
    name alone, so the board can ask the base's tree (``git ls-tree``) and
    never a checkout a seat can edit."""

    def test_the_newest_date_per_seat_from_names_or_paths(self, rf):
        names = ["memory/session-log.d/2026-10-15-073941-win-2.md", "2026-10-18-163553-win-2.md",
                 "2026-10-18-224242-air.md", "2026-10-19-053029-air.md", "README.md", "2026-10-17-notes.md"]
        assert rf.newest_row_date_by_seat(names) == {"win-2": "2026-10-18", "air": "2026-10-19"}

    def test_order_does_not_matter_and_an_empty_listing_is_empty(self, rf):
        names = ["2026-10-19-053029-air.md", "2026-10-15-073941-air.md"]
        assert rf.newest_row_date_by_seat(names) == rf.newest_row_date_by_seat(names[::-1]) == {"air": "2026-10-19"}
        assert rf.newest_row_date_by_seat([]) == {}

    def test_a_row_parked_on_the_records_ref_counts_and_is_said_to_be_parked(self, rf):
        """A handoff whose lane already merged parks its row on the seat's
        records ref until some push folds it; the seat wrote its row, so it is
        not in debt, and the reader says the fold is owed. Dies to: the parked
        row ignored (the dispatcher's own 10-20 row read as debt on 10-23), or
        an older parked row read over a newer one on the base."""
        base = ["memory/session-log.d/2026-10-18-163553-win.md", "memory/session-log.d/2026-10-19-053029-air.md"]
        parked = ["memory/session-log.d/2026-10-20-210952-air.md", "memory/session-log.d/2026-10-17-120000-win.md",
                  "memory/session-log.d/2026-10-18-163553-win-2.md"]
        assert rf.newest_row_by_seat(base, parked) == {"air": ("2026-10-20", True), "win": ("2026-10-18", False),
                                                       "win-2": ("2026-10-18", True)}
        assert rf.newest_row_by_seat(base) == {"air": ("2026-10-19", False), "win": ("2026-10-18", False)}
        assert rf.newest_row_by_seat([], []) == {}
        # A parked row of the same day as the base's newest is not newer.
        same = ["memory/session-log.d/2026-10-18-200000-win.md"]
        assert rf.newest_row_by_seat(base, same) == {"air": ("2026-10-19", False), "win": ("2026-10-18", False)}


class TestLanesSinceRow:
    """The count the board's ``records:`` line and the ship driver's row-debt
    read share: a seat's merged lanes dated, in the writer's zone, after its
    newest row. Mutation named in the pack: the merge day read in UTC, which
    counts a 21:00 EDT merge after the day's row as next-day debt."""

    _EDT = dt.timezone(dt.timedelta(hours=-4))

    def _merged(self):
        return [{"number": 1, "headRefName": "lane/a", "mergedAt": "2026-10-18T15:00:00Z"},
                {"number": 2, "headRefName": "lane/b", "mergedAt": "2026-10-19T01:00:00Z"},  # 21:00 EDT on the 18th
                {"number": 3, "headRefName": "lane/c", "mergedAt": "2026-10-19T15:00:00Z"},
                {"number": 4, "headRefName": "lane/other", "mergedAt": "2026-10-19T16:00:00Z"},
                {"number": 5, "headRefName": "lane/d", "mergedAt": ""},
                "junk"]

    def test_counts_the_seats_lanes_merged_on_a_local_day_after_its_newest_row(self, rf):
        seat_of = {"lane/a": "win", "lane/b": "win", "lane/c": "win", "lane/d": "win", "lane/other": "air"}
        assert rf.lanes_since_row(self._merged(), seat_of, "win", "2026-10-18", tz=self._EDT) == 1
        assert rf.lanes_since_row(self._merged(), seat_of, "win", "2026-10-18", tz=dt.timezone.utc) == 2
        assert rf.lanes_since_row(self._merged(), seat_of, "win", "", tz=self._EDT) == 3
        assert rf.lanes_since_row(self._merged(), seat_of, "air", "2026-10-19", tz=self._EDT) == 0

    def test_local_day_reads_the_stamp_in_the_given_zone_and_says_nothing_for_none(self, rf):
        assert rf.local_day("2026-10-19T01:00:00Z", tz=self._EDT) == "2026-10-18"
        assert rf.local_day("2026-10-19T01:00:00Z", tz=dt.timezone.utc) == "2026-10-19"
        assert rf.local_day("", tz=self._EDT) == "" and rf.local_day(None, tz=self._EDT) == ""
        assert rf.local_day("yesterday") == ""

    @pytest.mark.skipif(not hasattr(time, "tzset"), reason="the process zone cannot be set on this host")
    def test_the_default_zone_is_the_process_zone_not_utc(self, rf, monkeypatch):
        """Every other row passes a zone, and the board and ship rows use noon
        stamps, so a reader that fell back to UTC passed them all (failure-mode
        review, survivor S1). Dies to: ``astimezone(tz or utc)``."""
        monkeypatch.setenv("TZ", "America/New_York")
        time.tzset()
        try:
            assert rf.local_day("2026-10-19T01:00:00Z") == "2026-10-18"
            assert rf.lanes_since_row([{"headRefName": "lane/a", "mergedAt": "2026-10-19T01:00:00Z"}],
                                      {"lane/a": "win"}, "win", "2026-10-18") == 0
        finally:
            monkeypatch.undo()
            time.tzset()

    def test_a_full_read_whose_oldest_merge_is_newer_than_the_row_is_a_floor(self, rf):
        """The window spans every seat's merges, so a seat's count never says
        whether the read reached its row (code review of the first cut rule).
        Dies to: the flag read from the count, or a full read with the row
        inside it called a floor."""
        full = [{"headRefName": "lane/a", "mergedAt": f"2026-10-{19 + (i % 2):02d}T12:00:00Z"} for i in range(4)]
        assert rf.window_stops_short(full, "2026-10-10", 4, tz=self._EDT) is True
        assert rf.window_stops_short(full, "", 4, tz=self._EDT) is True
        assert rf.window_stops_short(full, "2026-10-19", 4, tz=self._EDT) is False
        assert rf.window_stops_short(full[:3], "2026-10-10", 4, tz=self._EDT) is False
        assert rf.window_stops_short(full + ["junk"], "2026-10-10", 0, tz=self._EDT) is False

    def test_the_window_covers_three_days_of_the_measured_rate(self, rf):
        """25 lanes a day across four seats (2026-10-16 to 10-18); the ship
        driver's POST_MERGE_ROWS (20) covers under one."""
        assert rf.ROW_DEBT_WINDOW >= 75
