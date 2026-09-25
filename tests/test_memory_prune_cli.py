"""Tests for the ``espalier memory prune`` CLI verb (TP-68) and the
underlying ``cmd_memory_prune`` autoprune path that fires from
``post_write_check`` whenever ESPALIER_MEMORY.md crosses the 80-line cap.

Pins the prune algorithm: archives the oldest Session Log rows
first, tolerates blank lines between rows (hand-edit artifact),
preserves the table header + separator + prose sections. Without
this contract autoprune could silently drop the wrong rows (newest-
instead-of-oldest, header rows, prose sections) and the operator
would lose recent cross-session context the blueprint chain relies
on.
"""
from __future__ import annotations

import argparse
import codecs
from pathlib import Path


from espalier.cli import cmd_memory_prune
from espalier.reflect_protocol import run_reflect_pass


def _write_memory(
    repo: Path,
    rows: list[str],
    *,
    blank_between_rows: bool = False,
) -> Path:
    """Write a ESPALIER_MEMORY.md with a Session Log table containing `rows`.

    Mirrors the live ESPALIER_MEMORY.md shape: prose lines between
    ``## Session Log`` and the pipe table header, then header + separator
    + data rows. Set ``blank_between_rows`` to inject a blank line
    between every pair of data rows (regression cover for
    hand-edit artifacts).
    """
    joiner = "\n\n" if blank_between_rows else "\n"
    body_rows = joiner.join(f"| {r} |" for r in rows)
    text = (
        "# Test MEMORY\n"
        "\n"
        "## Repo Context\n"
        "\n"
        "**Repo:** test\n"
        "\n"
        "## Session Log\n"
        "\n"
        "**Pruning policy:** Keep 5 most recent. Move older to docs/session-archive.md.\n"
        "Keep this file under 80 lines.\n"
        "\n"
        "| Date | What Happened | Notes |\n"
        "|------|--------------|-------|\n"
        f"{body_rows}\n"
    )
    memory = repo / "ESPALIER_MEMORY.md"
    memory.write_text(text, encoding="utf-8")
    return memory


def _ns(**kwargs: object) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


class TestMemoryPrune:
    def test_rows_zero_is_noop_and_exits_zero(
        self, tmp_path: Path, capsys
    ) -> None:
        memory = _write_memory(tmp_path, [
            "2026-01-01 | A | notes-a",
            "2026-01-02 | B | notes-b",
        ])
        original = memory.read_text(encoding="utf-8")

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=0, archive=None))

        assert rc == 0
        assert "nothing to prune" in capsys.readouterr().out
        assert memory.read_text(encoding="utf-8") == original

    def test_prunes_oldest_row_and_archives(
        self, tmp_path: Path, capsys
    ) -> None:
        memory = _write_memory(tmp_path, [
            "2026-01-01 | A | notes-a",
            "2026-01-02 | B | notes-b",
            "2026-01-03 | C | notes-c",
        ])

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None))

        assert rc == 0
        new_memory = memory.read_text(encoding="utf-8")
        assert "notes-a" not in new_memory
        assert "notes-b" in new_memory
        assert "notes-c" in new_memory

        archive = tmp_path / "docs" / "session-archive.md"
        assert archive.is_file()
        archive_text = archive.read_text(encoding="utf-8")
        assert "notes-a" in archive_text
        assert "## Pruned" in archive_text
        assert "via espalier memory prune" in archive_text

    def test_refuses_to_empty_the_table(
        self, tmp_path: Path, capsys
    ) -> None:
        memory = _write_memory(tmp_path, [
            "2026-01-01 | A | notes-a",
        ])
        original = memory.read_text(encoding="utf-8")

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None))

        assert rc == 1
        assert "refusing to prune" in capsys.readouterr().err
        assert memory.read_text(encoding="utf-8") == original

    def test_allow_empty_opts_out_of_floor(
        self, tmp_path: Path, capsys
    ) -> None:
        """TP-91 — with --allow-empty, prune succeeds even when the
        Session Log would end up empty. Hook context relies on this so
        autoprune never blocks on a 1-row Session Log over the cap."""
        memory = _write_memory(tmp_path, [
            "2026-01-01 | A | notes-a",
        ])

        rc = cmd_memory_prune(
            _ns(root=str(tmp_path), rows=1, archive=None, allow_empty=True)
        )

        assert rc == 0
        new_memory = memory.read_text(encoding="utf-8")
        assert "notes-a" not in new_memory, "row should be archived"
        archive = tmp_path / "docs" / "session-archive.md"
        assert archive.is_file()
        assert "notes-a" in archive.read_text(encoding="utf-8")
        # Session Log section header + table header + separator remain;
        # data row is gone.
        assert "## Session Log" in new_memory
        assert "| Date | What Happened | Notes |" in new_memory

    def test_allow_empty_default_false_still_refuses(
        self, tmp_path: Path, capsys
    ) -> None:
        """TP-91 — explicit `allow_empty=False` matches the default
        (refuse). Pins the safety default for direct CLI users."""
        memory = _write_memory(tmp_path, [
            "2026-01-01 | A | notes-a",
        ])
        original = memory.read_text(encoding="utf-8")

        rc = cmd_memory_prune(
            _ns(root=str(tmp_path), rows=1, archive=None, allow_empty=False)
        )

        assert rc == 1
        err = capsys.readouterr().err
        assert "refusing to prune" in err
        assert "--allow-empty" in err, "error message must name the opt-out flag"
        assert memory.read_text(encoding="utf-8") == original

    def test_allow_empty_clamps_over_request(
        self, tmp_path: Path, capsys
    ) -> None:
        """TP-91 — with --allow-empty, requesting more rows than exist
        clamps to availability instead of refusing. Pre-TP-91 the verb
        refused even when the caller wanted best-effort cleanup."""
        memory = _write_memory(tmp_path, [
            "2026-01-01 | A | notes-a",
        ])

        # Request 5 rows; only 1 exists. With --allow-empty, archive 1.
        rc = cmd_memory_prune(
            _ns(root=str(tmp_path), rows=5, archive=None, allow_empty=True)
        )

        assert rc == 0
        new_memory = memory.read_text(encoding="utf-8")
        assert "notes-a" not in new_memory
        archive = tmp_path / "docs" / "session-archive.md"
        assert archive.is_file()
        assert "notes-a" in archive.read_text(encoding="utf-8")

    def test_allow_empty_with_empty_session_log_is_noop(
        self, tmp_path: Path, capsys
    ) -> None:
        """TP-91 — when Session Log is already empty, --allow-empty
        returns 0 with a 'nothing to prune' message rather than the
        'requested N but only 0 rows' error. Idempotent under
        repeated hook calls."""
        # Table with header + separator but zero data rows.
        memory_path = tmp_path / "ESPALIER_MEMORY.md"
        memory_path.write_text(
            "# Test\n\n"
            "## Session Log\n\n"
            "| Date | What Happened | Notes |\n"
            "|------|--------------|-------|\n",
            encoding="utf-8",
        )

        rc = cmd_memory_prune(
            _ns(root=str(tmp_path), rows=3, archive=None, allow_empty=True)
        )

        assert rc == 0
        out = capsys.readouterr().out
        assert "nothing to prune" in out

    def test_appends_to_existing_archive(
        self, tmp_path: Path
    ) -> None:
        _write_memory(tmp_path, [
            "2026-01-01 | A | notes-a",
            "2026-01-02 | B | notes-b",
        ])
        archive = tmp_path / "docs" / "session-archive.md"
        archive.parent.mkdir(parents=True)
        archive.write_text("# Existing archive\n\nprior content\n", encoding="utf-8")

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None))

        assert rc == 0
        archive_text = archive.read_text(encoding="utf-8")
        assert archive_text.startswith("# Existing archive\n")
        assert "prior content" in archive_text
        assert "notes-a" in archive_text

    def test_missing_session_log_section_errors(
        self, tmp_path: Path, capsys
    ) -> None:
        memory = tmp_path / "ESPALIER_MEMORY.md"
        memory.write_text("# No Session Log here\n", encoding="utf-8")

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None))

        assert rc == 1
        assert "no '## Session Log'" in capsys.readouterr().err

    def test_rows_exceeding_table_size_errors(
        self, tmp_path: Path, capsys
    ) -> None:
        _write_memory(tmp_path, [
            "2026-01-01 | A | notes-a",
            "2026-01-02 | B | notes-b",
        ])

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=99, archive=None))

        assert rc == 1
        assert "only" in capsys.readouterr().err

    def test_prunes_correctly_with_blank_line_between_rows(
        self, tmp_path: Path
    ) -> None:
        """Hand-edits can leave a blank line between data rows; the
        parser must see the whole table, not stop at the blank.
        """
        memory = _write_memory(
            tmp_path,
            [
                "2026-01-01 | A | notes-a",
                "2026-01-02 | B | notes-b",
                "2026-01-03 | C | notes-c",
            ],
            blank_between_rows=True,
        )

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None))

        assert rc == 0
        new_memory = memory.read_text(encoding="utf-8")
        assert "notes-a" not in new_memory
        assert "notes-b" in new_memory
        assert "notes-c" in new_memory
        archive = tmp_path / "docs" / "session-archive.md"
        assert "notes-a" in archive.read_text(encoding="utf-8")


class TestMemoryPruneDateAware:
    """Pins date-aware row archival: regardless of file insertion order,
    `cmd_memory_prune --rows N` archives the N rows with the EARLIEST
    `| YYYY-MM-DD` prefix.

    Pre-fix the implementation took `data_row_indices[:N]` (first N by
    file position) which silently archived NEWEST rows when operators
    inserted at top (de-facto reading order is newest-first). Bit the
    repo twice during the 2026-05-25 sessions; documented in ESPALIER_MEMORY.md
    + docs/session-archive.md. Without this contract a future refactor
    could regress the date-sort and re-fire the same silent loss.
    """

    def test_newest_at_top_insertion_still_archives_oldest_by_date(
        self, tmp_path: Path
    ) -> None:
        """The exact bug shape: NEW row at top, older rows below."""
        memory = _write_memory(tmp_path, [
            "2026-05-25 | NEW | notes-new",      # inserted-at-top
            "2026-01-03 | C | notes-c",
            "2026-01-02 | B | notes-b",
            "2026-01-01 | A | notes-a",          # oldest by date, bottom
        ])

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None))

        assert rc == 0
        new_memory = memory.read_text(encoding="utf-8")
        # Pre-fix: notes-new (top of table) was archived. Post-fix: notes-a
        # (oldest by date) is archived.
        assert "notes-a" not in new_memory
        assert "notes-new" in new_memory
        assert "notes-b" in new_memory
        assert "notes-c" in new_memory

        archive = (tmp_path / "docs" / "session-archive.md").read_text(encoding="utf-8")
        assert "notes-a" in archive
        assert "notes-new" not in archive

    def test_shuffled_dates_archive_strictly_by_date(
        self, tmp_path: Path
    ) -> None:
        """Random insertion order: prune walks date order, not file order."""
        memory = _write_memory(tmp_path, [
            "2026-03-15 | mid-march | notes-mar",
            "2026-01-10 | early-jan | notes-jan",     # oldest by date
            "2026-05-20 | mid-may | notes-may",
            "2026-02-05 | early-feb | notes-feb",
        ])

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=2, archive=None))

        assert rc == 0
        new_memory = memory.read_text(encoding="utf-8")
        # 2 oldest by date: jan + feb. Archive should hold those; memory keeps mar + may.
        assert "notes-jan" not in new_memory
        assert "notes-feb" not in new_memory
        assert "notes-mar" in new_memory
        assert "notes-may" in new_memory

        archive = (tmp_path / "docs" / "session-archive.md").read_text(encoding="utf-8")
        assert "notes-jan" in archive
        assert "notes-feb" in archive

    def test_undated_row_is_preserved_not_archived(
        self, tmp_path: Path
    ) -> None:
        """Rows without a parseable YYYY-MM-DD prefix sort to the end
        (sentinel 9999-12-31) so they're preserved, not silently archived.
        Safety net against malformed rows being treated as 'oldest'."""
        memory = _write_memory(tmp_path, [
            "no-date prefix | weird | notes-undated",
            "2026-01-01 | A | notes-a",                 # oldest with date
            "2026-01-02 | B | notes-b",
        ])

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None))

        assert rc == 0
        new_memory = memory.read_text(encoding="utf-8")
        # notes-a (oldest dated row) archived; undated row preserved.
        assert "notes-a" not in new_memory
        assert "notes-undated" in new_memory
        assert "notes-b" in new_memory

    def test_same_date_rows_break_tie_by_file_position(
        self, tmp_path: Path
    ) -> None:
        """Two rows with identical dates: the BOTTOM-most is archived first.

        The sign of the tie-break encodes the insertion convention, so this
        test's direction is not arbitrary. `/handoff` PREPENDS — newest at the
        top of the table — so within one date the bottom-most row is the oldest
        and is the correct one to archive.

        This previously asserted the opposite and justified it as "the one
        appearing earlier in file (first inserted)". Under prepend, earlier in
        file is the LAST inserted, so the test pinned the inverse of its own
        stated reason and passed. Driven at the time: with three rows sharing
        today's date and one from yesterday, `--rows 2` archived yesterday's row
        AND the row the operator had just written, keeping both older same-day
        rows — the footgun docs/SHARP_EDGES.md names in "ESPALIER_MEMORY.md
        Autoprune Archives the Row You Just Added".
        """
        memory = _write_memory(tmp_path, [
            "2026-01-01 | first-A | notes-first",       # earlier in file = LAST written
            "2026-01-01 | second-A | notes-second",     # later in file = oldest of the day
            "2026-05-25 | new | notes-new",
        ])

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None))

        assert rc == 0
        new_memory = memory.read_text(encoding="utf-8")
        assert "notes-second" not in new_memory, (
            "the bottom-most same-date row is the oldest under prepend and must "
            "be archived first"
        )
        assert "notes-first" in new_memory, (
            "archiving the TOP same-date row discards the most recently written "
            "session -- the regression this test exists to catch"
        )
        assert "notes-new" in new_memory


class TestMemoryPruneParserWiring:
    def test_argparse_round_trip(self) -> None:
        """Subparser wiring: prune action + --rows int default + --archive
        + --root all resolve to cmd_memory_prune.
        """
        from espalier.cli import build_parser

        args = build_parser().parse_args(["memory", "prune", "--rows", "2"])
        assert args.command == "memory"
        assert args.memory_action == "prune"
        assert args.rows == 2
        assert args.func is cmd_memory_prune

    def test_argparse_rows_default_is_one(self) -> None:
        from espalier.cli import build_parser

        args = build_parser().parse_args(["memory", "prune"])
        assert args.rows == 1


class TestMemoryPruneKeepNewest:
    """``--keep-newest N`` reserves the N newest rows and ``--allow-empty`` does not
    waive it.

    Why it exists: ESPALIER_MEMORY.md's pruning policy says, in shipped prose, "the
    newest rows are always kept" -- and with a one-row Session Log the hook's
    ``--allow-empty`` archived exactly that row, because with nothing older the row
    the operator just wrote IS the oldest. The documented contract and the code had
    drifted apart and a test pinned the drift in place.

    ⚠ These fixtures seed DESCENDING (newest at top), unlike the shared
    ``_write_memory`` callers above. That is the live artifact's shape -- ``/handoff``
    prepends -- and it is the shape where "newest" by date and "first" by file
    position disagree, so an implementation that reserved by position instead of by
    date cannot pass these.
    """

    def test_keep_newest_reserves_the_newest_row_by_date(self, tmp_path: Path) -> None:
        memory = _write_memory(tmp_path, [
            "2026-05-25 | NEW | notes-new",      # newest by date, TOP of file
            "2026-01-03 | C | notes-c",
            "2026-01-02 | B | notes-b",
            "2026-01-01 | A | notes-a",          # oldest by date, BOTTOM of file
        ])

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=99, archive=None,
                                  allow_empty=True, keep_newest=1))

        assert rc == 0
        kept = memory.read_text(encoding="utf-8")
        assert "notes-new" in kept, "the reserved newest row was evicted"
        for gone in ("notes-a", "notes-b", "notes-c"):
            assert gone not in kept, f"{gone} should have been archived"
        archive = (tmp_path / "docs" / "session-archive.md").read_text(encoding="utf-8")
        assert "notes-new" not in archive

    def test_allow_empty_does_not_waive_the_reservation(self, tmp_path: Path) -> None:
        """The exact autoprune shape: one row, hook passes both flags."""
        memory = _write_memory(tmp_path, ["2026-05-25 | ONLY | notes-only"])
        original = memory.read_text(encoding="utf-8")

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=2, archive=None,
                                  allow_empty=True, keep_newest=1))

        assert rc == 0, "reserving every available row must not be an error"
        assert memory.read_text(encoding="utf-8") == original, (
            "the single row was evicted despite --keep-newest 1"
        )
        assert not (tmp_path / "docs" / "session-archive.md").exists(), (
            "nothing should have been archived"
        )

    def test_keep_newest_reserves_by_date_not_by_file_position(
        self, tmp_path: Path
    ) -> None:
        """The reservation must consume the SAME sorted order the eviction reads.

        Seeded ASCENDING here -- newest at the BOTTOM -- which is the mirror image of
        the class above. An implementation that reserved ``rows[:1]`` or ``rows[-1:]``
        by file position passes exactly one of these two tests and fails the other;
        only one that slices the date-sorted order passes both.
        """
        memory = _write_memory(tmp_path, [
            "2026-01-01 | A | notes-a",          # oldest by date, TOP of file
            "2026-01-02 | B | notes-b",
            "2026-05-25 | NEW | notes-new",      # newest by date, BOTTOM of file
        ])

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=99, archive=None,
                                  allow_empty=True, keep_newest=1))

        assert rc == 0
        kept = memory.read_text(encoding="utf-8")
        assert "notes-new" in kept, (
            "reserved the wrong row -- 'newest' was read as a file position, not a date"
        )
        assert "notes-a" not in kept and "notes-b" not in kept

    def test_keep_newest_zero_changes_nothing(self, tmp_path: Path) -> None:
        """The default is a provable no-op, which is what lets every pre-existing
        case in this module stay green unmodified."""
        rows = [
            "2026-05-25 | NEW | notes-new",
            "2026-01-02 | B | notes-b",
            "2026-01-01 | A | notes-a",
        ]
        (tmp_path / "without").mkdir()
        (tmp_path / "with_zero").mkdir()
        without = _write_memory(tmp_path / "without", rows)
        with_zero = _write_memory(tmp_path / "with_zero", rows)

        assert cmd_memory_prune(
            _ns(root=str(tmp_path / "without"), rows=2, archive=None)) == 0
        assert cmd_memory_prune(
            _ns(root=str(tmp_path / "with_zero"), rows=2, archive=None,
                keep_newest=0)) == 0

        assert without.read_text(encoding="utf-8") == with_zero.read_text(encoding="utf-8")

    def test_a_clamped_request_names_its_shortfall(self, tmp_path: Path, capsys) -> None:
        """A line-denominated request must not read as satisfied when it was not.

        The hook asks for a LINE delta and the verb spends it as ROWS. When the
        over-cap lines live in prose rather than in the log, there are fewer rows
        than the request and the difference is unspendable -- which was silently
        clamped, so a caller asking for eight and getting two could not tell.
        """
        _write_memory(tmp_path, [
            "2026-05-25 | NEW | notes-new",
            "2026-01-02 | B | notes-b",
            "2026-01-01 | A | notes-a",
        ])

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=8, archive=None,
                                  allow_empty=True, keep_newest=1))

        assert rc == 0
        out = capsys.readouterr().out
        assert "requested 8" in out, (
            f"the clamped request is not named, so the shortfall is invisible: {out!r}"
        )
        assert "pruned 2 rows" in out, f"expected 2 evictable rows archived: {out!r}"

    def test_an_unclamped_request_says_nothing_about_shortfall(
        self, tmp_path: Path, capsys
    ) -> None:
        """Non-vacuity for the assertion above: the shortfall clause must be
        ABSENT when nothing was clamped, or 'requested N' proves nothing."""
        _write_memory(tmp_path, [
            "2026-05-25 | NEW | notes-new",
            "2026-01-02 | B | notes-b",
            "2026-01-01 | A | notes-a",
        ])

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None,
                                  allow_empty=True, keep_newest=1))

        assert rc == 0
        out = capsys.readouterr().out
        assert "requested" not in out, (
            f"a request that was met in full must not report a shortfall: {out!r}"
        )


class TestMemoryPruneReadsTheOperatorsFile:
    """DEF-797: the file is hand-edited at every handoff, and the autoprune hook
    shells out to this verb. A byte-order-marked file (a PowerShell re-encode,
    an editor) prunes and is written back as UTF-8; one the verb cannot decode
    is refused, exit 1, with the encoding named -- pruning it would write the
    garbage back."""

    def test_a_byte_order_marked_file_prunes_and_comes_back_utf8(
        self, tmp_path: Path, capsys
    ) -> None:
        memory = _write_memory(tmp_path, ["2026-01-01 | A | notes-a", "2026-01-02 | B | notes-b"])
        text = memory.read_text(encoding="utf-8")
        for label, data in (
            ("utf-16le with a byte-order mark", codecs.BOM_UTF16_LE + text.encode("utf-16-le")),
            ("utf-8 with a byte-order mark", codecs.BOM_UTF8 + text.encode("utf-8")),
        ):
            memory.write_bytes(data)
            rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None))
            assert rc == 0, (label, capsys.readouterr())
            raw = memory.read_bytes()
            assert raw[:1] == b"#" and b"\x00" not in raw, label
            new_memory = raw.decode("utf-8")
            assert "notes-a" not in new_memory and "notes-b" in new_memory, label

    def test_a_file_the_verb_cannot_decode_is_refused_and_left_alone(
        self, tmp_path: Path, capsys
    ) -> None:
        memory = _write_memory(tmp_path, ["2026-01-01 | A | notes-a", "2026-01-02 | B | notes-b"])
        text = memory.read_text(encoding="utf-8")
        for label, data, detail in (
            ("utf-16le, no byte-order mark", text.encode("utf-16-le"),
             "NUL bytes -- UTF-16 without a byte-order mark?"),
            ("cp1252 with an accent", text.replace("Test MEMORY", "M\xe9moire").encode("cp1252"),
             "invalid continuation byte"),
        ):
            memory.write_bytes(data)
            rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None))
            captured = capsys.readouterr()
            assert rc == 1, label
            assert "ESPALIER_MEMORY.md is not UTF-8 text" in captured.err and detail in captured.err, (label, captured.err)
            assert "re-save it as UTF-8" in captured.err, label
            assert memory.read_bytes() == data, label
            assert not (tmp_path / "docs" / "session-archive.md").exists(), label

    def test_a_byte_order_marked_archive_is_read_and_written_back_utf8(
        self, tmp_path: Path, capsys
    ) -> None:
        # The archive is the sibling an operator appends to by hand; the
        # failure-mode review drove a marked one through the verb and it
        # tracebacked three lines after the memory file was refused politely.
        _write_memory(tmp_path, ["2026-01-01 | A | notes-a", "2026-01-02 | B | notes-b"])
        archive = tmp_path / "docs" / "session-archive.md"
        archive.parent.mkdir(exist_ok=True)
        archive.write_bytes(codecs.BOM_UTF16_LE + "# Archive\n\nolder rows\n".encode("utf-16-le"))
        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None))
        assert rc == 0, capsys.readouterr()
        raw = archive.read_bytes()
        assert raw.startswith(b"# Archive") and b"\x00" not in raw
        assert "older rows" in raw.decode("utf-8") and "notes-a" in raw.decode("utf-8")

    def test_an_archive_the_verb_cannot_decode_is_refused_before_either_write(
        self, tmp_path: Path, capsys
    ) -> None:
        memory = _write_memory(tmp_path, ["2026-01-01 | A | notes-a", "2026-01-02 | B | notes-b"])
        before = memory.read_bytes()
        archive = tmp_path / "docs" / "session-archive.md"
        archive.parent.mkdir(exist_ok=True)
        data = "# Archive\n".encode("utf-16-le")
        archive.write_bytes(data)
        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None))
        captured = capsys.readouterr()
        assert rc == 1, captured
        assert "docs/session-archive.md is not UTF-8 text (NUL bytes" in captured.err, captured.err
        assert memory.read_bytes() == before and archive.read_bytes() == data


class TestMemoryPruneRebasesRowLinks:
    """DEF-793: a moved row's relative links are re-based onto the archive.

    A row is written in ESPALIER_MEMORY.md at the repo root, so its links are
    spelled from the root (``](memory/x.md)``). Both reflect link checkers, like
    any markdown renderer, resolve a link from the doc that CONTAINS it, so a row
    copied verbatim into ``docs/session-archive.md`` broke every such link, each
    read as a high broken link on every reflect pass and the session banner's
    unresolved slots filled with them. Who got hurt: the maintainer or adopter
    whose next session opened on phantom unresolved items after an autoprune.

    The load-bearing oracle is the reflect pass itself, run over the fixture after
    the prune, not a string check: a prefix that is merely present can still be
    the wrong one (a hard-coded ``../`` under a non-default archive path), and only
    resolution from the archive's directory says the link works.
    """

    @staticmethod
    def _seed_targets(repo: Path, *rels: str) -> None:
        for rel in rels:
            target = repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# X\n", encoding="utf-8")

    @staticmethod
    def _archived_row(repo: Path, archive_rel: str = "docs/session-archive.md") -> str:
        text = (repo / archive_rel).read_text(encoding="utf-8")
        rows = [line for line in text.splitlines() if line.startswith("| 2026-01-01")]
        assert len(rows) == 1, f"expected the one archived row, got {rows!r}"
        return rows[0]

    @staticmethod
    def _broken_archive_links(repo: Path) -> list[str]:
        return [f.description for f in run_reflect_pass(repo, 1).findings
                if f.description.startswith("Broken link in docs/session-archive.md")]

    def test_root_relative_links_resolve_from_the_archive(self, tmp_path: Path) -> None:
        # Three different top-level trees, so re-basing one prefix is not enough.
        self._seed_targets(tmp_path, "memory/x.md", "docs/y.md", "tools/cc/z.py")
        _write_memory(tmp_path, [
            "2026-01-01 | read [m](memory/x.md), [d](docs/y.md), [t](tools/cc/z.py) "
            "and [gone](memory/missing.md) | notes-a",
            "2026-01-02 | B | notes-b",
        ])

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None))

        assert rc == 0
        broken = self._broken_archive_links(tmp_path)
        # Positive control: the one link whose target really is missing must still
        # be reported, re-based -- otherwise "nothing broken" could mean the checker
        # never read the archive at all.
        assert len(broken) == 1 and "(../memory/missing.md)" in broken[0], (
            f"a moved row's links do not resolve from the archive: {broken!r}"
        )

    def test_the_row_is_byte_identical_but_for_the_inserted_prefix(
        self, tmp_path: Path
    ) -> None:
        self._seed_targets(tmp_path, "memory/x.md", "docs/pic.png")
        _write_memory(tmp_path, [
            "2026-01-01 | Kept **prose**, a [frag](memory/x.md#x), an "
            '![img](docs/pic.png "a title"), a [dot](./memory/x.md), an '
            "[angle](<memory/x.md>) and a [dir](memory/) link. | notes-a",
            "2026-01-02 | B | notes-b",
        ])

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None))

        assert rc == 0
        assert self._archived_row(tmp_path) == (
            "| 2026-01-01 | Kept **prose**, a [frag](../memory/x.md#x), an "
            '![img](../docs/pic.png "a title"), a [dot](../memory/x.md), an '
            "[angle](<../memory/x.md>) and a [dir](../memory/) link. | notes-a |"
        )

    def test_links_that_need_no_rebase_are_left_alone(self, tmp_path: Path) -> None:
        """A URL of any scheme, a same-doc fragment, a root-anchored path, a target
        already spelled from below the root (a row restored from the archive, or a
        hand-repaired one -- re-basing it again would double the prefix), and link
        syntax inside a code span, which is a mention and not a link."""
        self._seed_targets(tmp_path, "memory/x.md")
        row = (
            "2026-01-01 | [w](https://example.com/memory/x.md) [s](ftp://host/memory/x.md) "
            "[e](mailto:a@example.com) [f](#notes) [a](/memory/x.md) [r](../memory/x.md) "
            "`[c](memory/x.md)` ``[cc](memory/x.md) ` `` | notes-a"
        )
        _write_memory(tmp_path, [row, "2026-01-02 | B | notes-b"])

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None))

        assert rc == 0
        assert self._archived_row(tmp_path) == f"| {row} |"

    def test_a_link_already_correct_from_the_archive_is_not_rebased(
        self, tmp_path: Path
    ) -> None:
        """"Already correct" is a resolution fact, not a spelling: a target that
        resolves from the archive's directory and NOT from the root was written
        for where the row lands, so it stays. One that resolves from the root is
        re-based even when the archive's directory has a same-named file -- the
        row meant the root's."""
        self._seed_targets(tmp_path, "docs/CONVENTIONS.md", "README.md", "docs/README.md")
        _write_memory(tmp_path, [
            "2026-01-01 | [c](CONVENTIONS.md) and [r](README.md) | notes-a",
            "2026-01-02 | B | notes-b",
        ])

        rc = cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None))

        assert rc == 0
        assert self._archived_row(tmp_path) == (
            "| 2026-01-01 | [c](CONVENTIONS.md) and [r](../README.md) | notes-a |"
        )
        assert self._broken_archive_links(tmp_path) == []

    def test_a_parent_relative_link_written_at_the_root_is_rebased(self, tmp_path: Path) -> None:
        """A `../` target was skipped by its spelling alone, for the restored or
        hand-repaired row -- which the resolution check already leaves (it
        resolves from the archive, not the root). A parent-relative link written
        at the root and resolving from there, to a sibling checkout's note, was
        left to break in the archive (the lane's review, item 13)."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (tmp_path / "sibling").mkdir()
        (tmp_path / "sibling" / "y.md").write_text("y\n", encoding="utf-8")
        _write_memory(repo, ["2026-01-01 | [s](../sibling/y.md) | notes-a", "2026-01-02 | B | notes-b"])

        rc = cmd_memory_prune(_ns(root=str(repo), rows=1, archive=None))

        assert rc == 0
        assert self._archived_row(repo) == "| 2026-01-01 | [s](../../sibling/y.md) | notes-a |"

    def test_the_prefix_is_derived_from_the_archive_path(self, tmp_path: Path) -> None:
        """An adopter's ``--archive`` elsewhere gets that location's prefix, not a
        hard-coded ``../``; an archive beside the memory file needs none."""
        rows = ["2026-01-01 | [m](memory/x.md) | notes-a", "2026-01-02 | B | notes-b"]
        for sub, archive_rel, expected in (
            ("deep", "notes/deep/log.md", "../../memory/x.md"),
            ("beside", "log.md", "memory/x.md"),
        ):
            repo = tmp_path / sub
            repo.mkdir()
            self._seed_targets(repo, "memory/x.md")
            _write_memory(repo, rows)

            rc = cmd_memory_prune(_ns(root=str(repo), rows=1, archive=archive_rel))

            assert rc == 0, sub
            assert self._archived_row(repo, archive_rel) == (
                f"| 2026-01-01 | [m]({expected}) | notes-a |"
            ), sub
            assert ((repo / archive_rel).parent / expected).is_file(), (
                f"{expected!r} does not resolve from {archive_rel!r}"
            )

    def test_a_row_archived_twice_is_rebased_once_each_time(self, tmp_path: Path) -> None:
        """The verb writes the archive before the memory file, so an interrupt
        between the two leaves the row in both and the next prune archives it
        again. Each copy is re-based from its root spelling exactly once, and the
        archive's existing bytes are never re-processed."""
        self._seed_targets(tmp_path, "memory/x.md")
        memory = _write_memory(tmp_path, [
            "2026-01-01 | [m](memory/x.md) | notes-a",
            "2026-01-02 | B | notes-b",
        ])
        original = memory.read_bytes()
        archive = tmp_path / "docs" / "session-archive.md"

        assert cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None)) == 0
        first = archive.read_text(encoding="utf-8")
        memory.write_bytes(original)
        assert cmd_memory_prune(_ns(root=str(tmp_path), rows=1, archive=None)) == 0
        second = archive.read_text(encoding="utf-8")

        assert second.startswith(first)
        assert second.count("](../memory/x.md)") == 2 and "../../" not in second
