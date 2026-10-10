"""Contract tests for ``tools/cc/_record_fragments.py``, the one loader for
the records two lanes both append to (TP-479 Wave C, layers L1 and L8): the
Session Log, written one row per file under ``memory/session-log.d/`` beside
the frozen legacy table, and the changelog's unreleased entries, one file per
lane under ``changelog.d/`` beside ``[Unreleased]``.

Each class names the mutation it was seen red against. Everything here runs
in-process over a ``tmp_path`` tree; the two-lane merge test, which needs real
git, lives with the other merge rows in ``tests/test_record_merge.py``.
"""
# pytest-marker: default-unit  (pure functions over a tmp_path tree; no subprocess)
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

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


class TestTheWriterNamesTheFile:
    def test_the_name_is_the_utc_clock_and_the_seat(self, rf):
        now = dt.datetime(2026, 10, 10, 14, 5, 9, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
        assert rf.session_log_name(now, "win-2") == "2026-10-10-180509-win-2.md"
        assert rf.SESSION_LOG_NAME_RE.match(rf.session_log_name(now, "win-2"))

    def test_the_path_is_under_the_directory_and_the_file_is_not_made(self, rf, tmp_path):
        now = dt.datetime(2026, 10, 10, 18, 5, 9, tzinfo=dt.timezone.utc)
        path = rf.new_session_log_path(tmp_path, seat="air", now=now)
        assert path == tmp_path / "memory" / "session-log.d" / "2026-10-10-180509-air.md"
        assert path.parent.is_dir() and not path.exists()


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

    def test_body_then_fragments_by_name(self, rf, tmp_path):
        _write(tmp_path / "CHANGELOG.md", self._CHANGELOG)
        _write(tmp_path / "changelog.d" / "2026-10-11-b.md", "### Fixed\n\n- **From b.**\n")
        _write(tmp_path / "changelog.d" / "2026-10-10-a.md", "### Added\n\n- **From a.**\n")
        text = rf.unreleased_text(tmp_path)
        assert text.index("In the file.") < text.index("From a.") < text.index("From b.")
        assert "Released." not in text

    def test_no_fragments_is_the_body(self, rf, tmp_path):
        _write(tmp_path / "CHANGELOG.md", self._CHANGELOG)
        assert rf.unreleased_text(tmp_path) == rf.unreleased_body(self._CHANGELOG)

    def test_a_lane_finds_its_own_fragment_again(self, rf, tmp_path):
        _write(tmp_path / "changelog.d" / "2026-10-09-parallel-work-c.md", "- x\n")
        assert rf.changelog_path(tmp_path, "lane/parallel-work-c", today="2026-10-11").name == \
            "2026-10-09-parallel-work-c.md"
        assert rf.changelog_path(tmp_path, "lane/other", today="2026-10-11").name == "2026-10-11-other.md"


class TestFragmentDirectories:
    def test_a_file_under_a_directory_is_in_it_and_the_directory_is_not(self, rf):
        assert rf.in_fragment_dir("memory/session-log.d/2026-10-10-120000-win.md")
        assert rf.in_fragment_dir("changelog.d\\2026-10-10-x.md")
        assert not rf.in_fragment_dir("memory/session-log.d/")
        assert not rf.in_fragment_dir("memory/session-log.dx/a.md")
        assert not rf.in_fragment_dir("CHANGELOG.md")

    def test_fragment_paths_lists_both_directories(self, rf, tmp_path):
        _fragment(tmp_path, "2026-10-10-120000-win.md", _row("2026-10-10", "f"))
        _write(tmp_path / "changelog.d" / "2026-10-10-x.md", "- x\n")
        assert [p.relative_to(tmp_path).as_posix() for p in rf.fragment_paths(tmp_path)] == [
            "changelog.d/2026-10-10-x.md", "memory/session-log.d/2026-10-10-120000-win.md"]


class TestDecode:
    def test_byte_order_marks_and_bad_bytes(self, rf):
        assert rf.decode(b"\xef\xbb\xbf| 2026") == "| 2026"
        assert rf.decode("| 2026".encode("utf-16")) == "| 2026"
        assert rf.decode(b"| \xff 2026") == "| � 2026"

    def test_line_ends_are_folded(self, rf):
        """A Windows checkout writes a merged-in fragment CRLF beside its own
        LF one; two readers of one record must not differ by that."""
        assert rf.decode(b"- a\r\n- b\n") == "- a\n- b\n"
