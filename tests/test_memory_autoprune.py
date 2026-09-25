"""TP-86 — post_write_check auto-prunes ESPALIER_MEMORY.md when over cap.

Class-of-bug guard: before TP-86, appending a Session Log row to
ESPALIER_MEMORY.md at the 80-line cap left the file failing
``TestMemoryMdLineLimit``. The operator had to manually back out the
append, prune, re-apply. This test pins the auto-heal: a write that
exceeds the cap fires a post-write prune that brings the file back to
cap-headroom.
"""
from __future__ import annotations

import codecs
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests._surface_expected import EXPECTED_MEMORY_MD_CAP


HOOK_PATH = (
    Path(__file__).resolve().parent.parent
    / "tools" / "cc" / "hooks" / "post_write_check.py"
)


def _espalier_available() -> bool:
    """True when ``espalier`` is invokable as either a PATH binary or a
    ``python -m espalier.cli`` subprocess. Matches the hook's fallback
    chain in ``_maybe_autoprune_memory``. The PATH binary may resolve
    to a Python without the espalier module installed on dev machines
    where multiple Pythons coexist (documented in docs/SHARP_EDGES.md
    under "macOS python resolver gap"); in that case the
    ``find_spec`` branch keeps the test runnable as long as the test
    interpreter itself can import espalier.
    """
    if importlib.util.find_spec("espalier") is not None:
        return True
    return shutil.which("espalier") is not None


def _make_over_cap_memory(
    repo_root: Path,
    target_lines: int = EXPECTED_MEMORY_MD_CAP + 5,
    *,
    session_log_rows: int = 10,
) -> Path:
    """Materialize a ESPALIER_MEMORY.md with ``target_lines`` lines and a valid
    Session Log table with ``session_log_rows`` data rows. Default 10
    rows leaves plenty of headroom for the prune verb. Use
    ``session_log_rows=1`` to exercise the TP-91 cap-stack-floor case.
    """
    memory_path = repo_root / "ESPALIER_MEMORY.md"
    header = ["# Test Memory", "", "## Repo Context", ""]
    decisions = [
        "## Harness Decisions", "",
        "| Decision | Date | Reason |",
        "|----------|------|--------|",
        "| Test decision | 2026-01-01 | seed |",
        "",
    ]
    session_log_header = [
        "## Session Log", "",
        "Pruning policy: TP-68 + TP-86 autoprune.",
        "",
        "| Date | What Happened | Notes |",
        "|------|--------------|-------|",
    ]
    # Newest at the TOP, as `/handoff` prepends: the top row carries the latest
    # date and the bottom row the earliest, so the OLDEST row (by date, the one
    # the prune verb archives) and the FIRST row (by position, the one a naive
    # ``rows[:N]`` would take) are different rows. Until 2026-09-13 the dates
    # ascended with position, the two readings named the same row, and the
    # assertions below could not tell which one the verb used (DEF-592). The
    # label is the day, so ``row 1`` is 2026-01-01, the oldest, at the bottom.
    sessions = [
        f"| 2026-01-{i:02d} | row {i} | n |"
        for i in range(session_log_rows, 0, -1)
    ]
    fixed = header + decisions + session_log_header + sessions
    padding_needed = max(0, target_lines - len(fixed))
    padding = ["<!-- pad -->"] * padding_needed
    all_lines = (fixed + padding)[:target_lines]
    memory_path.write_text("\n".join(all_lines) + "\n", encoding="utf-8")
    return memory_path


_SESSION_ROW_RE = re.compile(r"^\| (2026-\d\d-\d\d) \| row \d+ \|", re.M)


def _session_dates(text: str) -> list[str]:
    """The dates of the fixture's Session Log rows, in file order."""
    return _SESSION_ROW_RE.findall(text)


def _run_hook(repo_root: Path, rel_path: str) -> subprocess.CompletedProcess:
    payload = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": rel_path},
        "cwd": str(repo_root),
    })
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(repo_root)
    # Conftest autouse sets ESPALIER_AUDIT_DIR to its own tmp_path/audit;
    # without popping it, the hook subprocess writes audit entries to the
    # conftest fixture's dir instead of fresh_repo. Documented pitfall in
    # docs/CONVENTIONS.md ("subprocess env hygiene").
    env.pop("ESPALIER_AUDIT_DIR", None)
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        env=env,
        timeout=15, encoding="utf-8",
    )


@pytest.fixture
def fresh_repo(tmp_path):
    """A minimal repo root with ``.espalier/`` + ``docs/`` so the hook
    can run integrity checks without erroring on missing dirs and the
    prune verb can write to ``docs/session-archive.md``.
    """
    (tmp_path / ".espalier").mkdir()
    (tmp_path / "docs").mkdir()
    return tmp_path


class TestMemoryAutoprune:
    """TP-86 — post_write_check auto-prunes ESPALIER_MEMORY.md when over cap."""

    def test_autoprune_triggered_when_memory_over_cap(self, fresh_repo):
        """Writing a ESPALIER_MEMORY.md that pushes the file past the cap triggers
        an autoprune; file ends up at or below the cap.
        """
        if not _espalier_available():
            pytest.skip(
                "espalier neither importable nor on PATH"
            )

        over_cap = EXPECTED_MEMORY_MD_CAP + 5
        session_rows = 10
        memory_path = _make_over_cap_memory(
            fresh_repo, target_lines=over_cap, session_log_rows=session_rows,
        )
        pre_lines = memory_path.read_text(encoding="utf-8").splitlines()
        assert len(pre_lines) == over_cap
        # The fixture's shape, asserted so the discrimination below is real:
        # the first data row by position is the NEWEST by date.
        pre_dates = _session_dates(memory_path.read_text(encoding="utf-8"))
        assert pre_dates[0] == max(pre_dates)

        result = _run_hook(fresh_repo, "ESPALIER_MEMORY.md")

        assert result.returncode == 0, (
            f"hook exited {result.returncode}; stderr={result.stderr}"
        )
        # Specifically the success notification, not a "autoprune failed"
        # warn — the latter would satisfy a loose substring match and let
        # an environment-broken prune slip through unnoticed.
        assert "ESPALIER_MEMORY.md autoprune:" in result.stderr, (
            f"expected ESPALIER_MEMORY.md autoprune success message on stderr; "
            f"got: {result.stderr}"
        )

        post_lines = memory_path.read_text(encoding="utf-8").splitlines()
        # _AUTOPRUNE_HEADROOM = 1, so the prune archives enough oldest rows to
        # land the file back at <= cap (excess + headroom rows removed).
        assert len(post_lines) <= EXPECTED_MEMORY_MD_CAP, (
            f"ESPALIER_MEMORY.md still over cap after autoprune: "
            f"{len(post_lines)} lines"
        )

        archive_path = fresh_repo / "docs" / "session-archive.md"
        assert archive_path.is_file(), (
            "expected docs/session-archive.md to receive the pruned row"
        )
        archive_text = archive_path.read_text(encoding="utf-8")
        archived = _session_dates(archive_text)
        kept = _session_dates(memory_path.read_text(encoding="utf-8"))
        # Oldest by DATE, not first by POSITION. The fixture puts the newest row
        # at the top, so a prune that took the first N rows would archive the
        # newest ones and leave 2026-01-01 in place; the exact cell, because
        # "row 1" is a substring of "row 10".
        assert "| row 1 |" in archive_text, (
            "expected the oldest Session Log row (2026-01-01) to be archived"
        )
        assert f"| row {session_rows} |" not in archive_text, (
            "the newest Session Log row was archived: the prune took rows by "
            "position, not by date"
        )
        assert archived and kept and max(archived) < min(kept), (
            f"archived {sorted(archived)} is not strictly older than kept "
            f"{sorted(kept)}: the prune took rows by position, not by date"
        )

    def test_no_autoprune_when_memory_under_cap(self, fresh_repo):
        """A ESPALIER_MEMORY.md write under the cap leaves the file untouched."""
        memory_path = _make_over_cap_memory(
            fresh_repo, target_lines=EXPECTED_MEMORY_MD_CAP - 10
        )
        pre_text = memory_path.read_text(encoding="utf-8")

        result = _run_hook(fresh_repo, "ESPALIER_MEMORY.md")

        assert result.returncode == 0
        assert "autoprune" not in result.stderr.lower(), (
            f"unexpected autoprune action on under-cap file: {result.stderr}"
        )
        assert memory_path.read_text(encoding="utf-8") == pre_text

    def test_autoprune_keeps_the_only_session_log_row_and_says_it_is_over_cap(
        self, fresh_repo
    ):
        """The newest row survives even when keeping it leaves the file over cap.

        ⚠ THIS TEST INVERTED, DELIBERATELY. It was
        ``test_autoprune_clears_over_cap_with_one_session_log_row`` and asserted
        ``post_data_rows == []`` -- i.e. that a one-row Session Log is emptied.
        Three shapes in sequence:

        * Pre-TP-91: the verb REFUSED (rc=1, "would leave fewer than 1 row") and
          the hook nagged on every ESPALIER_MEMORY.md write.
        * TP-91: the hook passes ``--allow-empty``, the verb archives the one row
          and leaves the table empty. But with one row, the oldest row IS the row
          the operator just wrote -- so the handoff note silently landed in a
          gitignored archive and the file looked like nothing was written.
        * Now: the hook also passes ``--keep-newest 1``, which ``--allow-empty``
          does not waive. The newest row is never evicted.

        The reason this is a fix and not a preference: ESPALIER_MEMORY.md's own
        pruning policy has said "the newest rows are always kept" in shipped prose
        the whole time, and the assertion this replaces pinned the opposite. The
        code had drifted from its documented contract and the test held the drift
        in place.

        The cost, taken knowingly: an over-cap file whose entire excess is one fat
        log row can no longer self-heal. It falls to the residual-over-cap warning
        and stays over cap until an operator trims -- which is why the warning
        naming the fattest sections is part of the same change.
        """
        if not _espalier_available():
            pytest.skip("espalier neither importable nor on PATH")

        over_cap = EXPECTED_MEMORY_MD_CAP + 1
        memory_path = _make_over_cap_memory(
            fresh_repo, target_lines=over_cap, session_log_rows=1,
        )
        pre_lines = memory_path.read_text(encoding="utf-8").splitlines()
        assert len(pre_lines) == over_cap
        # Sanity: exactly 1 data row in Session Log before the run.
        data_rows = [
            line for line in pre_lines
            if line.startswith("| 2026-")
        ]
        assert len(data_rows) == 1

        result = _run_hook(fresh_repo, "ESPALIER_MEMORY.md")

        assert result.returncode == 0, (
            f"hook exited {result.returncode}; stderr={result.stderr}"
        )
        # CARRIED FORWARD from the pre-inversion assertion, and it is the only
        # oracle here that separates "the prune ran and correctly declined" from
        # "the prune subprocess never executed at all" -- the macOS python
        # resolver gap fails exactly that way, and every other assertion below is
        # satisfied by a prune that never ran.
        assert "autoprune failed" not in result.stderr, (
            "hook fell through to the warn path — the prune subprocess did not "
            f"run at all; stderr={result.stderr}"
        )
        # The file is still over cap, and the hook must SAY so rather than buy
        # headroom with the newest row.
        assert "STILL over the" in result.stderr, (
            "expected the residual-over-cap warning naming the fattest sections; "
            f"got: {result.stderr}"
        )

        post_lines = memory_path.read_text(encoding="utf-8").splitlines()
        post_data_rows = [
            line for line in post_lines if line.startswith("| 2026-")
        ]
        # `== data_rows`, not `!= []`: this must fail both for "the row was
        # evicted" AND for "the row was archived and then re-added", which a
        # non-emptiness check would pass.
        assert post_data_rows == data_rows, (
            f"the newest Session Log row must survive --keep-newest 1; "
            f"before={data_rows} after={post_data_rows}"
        )
        archive = fresh_repo / "docs" / "session-archive.md"
        if archive.is_file():
            assert "row 1" not in archive.read_text(encoding="utf-8"), (
                "the reserved newest row reached the archive anyway"
            )

    def test_autoprune_warns_when_still_over_cap(self, fresh_repo):
        """TP-192 W3-5: ``excess`` is a LINE delta but ``memory prune`` consumes
        it as a SESSION-LOG-ROW count. When the bloat is NOT in the Session Log
        (here: padding stands in for the Decisions/Patterns tables), pruning the
        only log row cannot bring the file under cap — the prune "succeeds" yet
        the file stays over cap. The hook must make that observable (warn)
        instead of printing the success line and exiting 0 silently."""
        if not _espalier_available():
            pytest.skip("espalier neither importable nor on PATH")

        # cap+20 lines, only 1 prunable Session Log row → pruning it leaves the
        # file ~cap+19 lines: still over cap.
        over_cap = EXPECTED_MEMORY_MD_CAP + 20
        memory_path = _make_over_cap_memory(
            fresh_repo, target_lines=over_cap, session_log_rows=1,
        )
        result = _run_hook(fresh_repo, "ESPALIER_MEMORY.md")

        assert result.returncode == 0, result.stderr
        post_lines = memory_path.read_text(encoding="utf-8").splitlines()
        # premise: the prune ran but couldn't clear the cap (excess was padding)
        assert len(post_lines) > EXPECTED_MEMORY_MD_CAP, (
            f"test premise broken — file should still be over cap; "
            f"got {len(post_lines)} lines"
        )
        assert "STILL over the" in result.stderr, (
            f"expected a residual-over-cap warning; got: {result.stderr}"
        )

    def test_no_autoprune_for_non_memory_writes(self, fresh_repo):
        """Writes to other files never trigger ESPALIER_MEMORY.md autoprune."""
        memory_path = _make_over_cap_memory(fresh_repo, target_lines=85)
        pre_text = memory_path.read_text(encoding="utf-8")

        # CLAUDE.md is a managed root .md, so the hook activates, but
        # the autoprune branch should early-return on rel_path mismatch.
        (fresh_repo / "CLAUDE.md").write_text(
            "# Test\n", encoding="utf-8"
        )
        result = _run_hook(fresh_repo, "CLAUDE.md")

        assert result.returncode == 0
        assert "autoprune" not in result.stderr.lower(), (
            f"unexpected autoprune action on non-ESPALIER_MEMORY.md write: "
            f"{result.stderr}"
        )
        # ESPALIER_MEMORY.md not touched
        assert memory_path.read_text(encoding="utf-8") == pre_text

class TestMemorySectionCensus:
    """``_memory_section_lines`` -- the census behind the residual-over-cap message.

    Its whole reason to exist is that the cap is measured over the WHOLE file while
    only Session Log rows are ever evicted, so a message that reports "still over
    cap" without naming the fat section mis-attributes the cost to session history.
    """

    @staticmethod
    def _census(text: str):
        spec = importlib.util.spec_from_file_location("_pwc_census", HOOK_PATH)
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(HOOK_PATH.parent))
        sys.path.insert(0, str(HOOK_PATH.parent.parent))
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.path.pop(0)
            sys.path.pop(0)
        return mod._memory_section_lines(text)

    def test_the_fat_section_is_named_even_when_it_is_not_the_session_log(self):
        """⚠ DISCRIMINATING BY CONSTRUCTION, and that is the point.

        The obvious fixture puts the bulk in the Session Log, where a census that
        simply returned "Session Log" for everything would still look right. So the
        fat section here is deliberately NOT the log: an assertion that the log is
        named would pass on a broken census, and this one cannot.
        """
        text = (
            "# Memory\n\nintro\n"
            "## Session Log\n" + "| 2026-01-01 | a | b |\n" * 3
            + "## Patterns Learned\n" + "- a pattern\n" * 40
            + "## Decisions\n" + "- a decision\n" * 5
        )
        census = self._census(text)
        assert census[0][0] == "Patterns Learned", (
            f"the census named {census[0][0]!r} as the largest section; the fixture "
            f"makes Patterns Learned the fat one by construction. Full census: {census}"
        )
        by_title = dict(census)
        assert by_title["Session Log"] < by_title["Patterns Learned"], (
            f"Session Log ({by_title['Session Log']}) must not out-count Patterns "
            f"Learned ({by_title['Patterns Learned']})"
        )

    def test_the_counts_sum_to_the_file(self):
        """A section that vanishes from the census would otherwise hide silently, and
        a fat preamble above the first heading has no section to be attributed to."""
        text = "# Title\nlead\n## A\nx\ny\n## B\nz\n"
        census = self._census(text)
        assert sum(count for _, count in census) == len(text.splitlines()), (
            f"census {census} does not sum to {len(text.splitlines())} lines"
        )
        assert "(preamble)" in dict(census), (
            "lines above the first heading must be attributed, not dropped"
        )

    def test_a_heading_inside_a_code_fence_is_not_a_section(self):
        """A ``## `` inside a fenced block is prose ABOUT a heading, not one.

        Earned red: without the fence toggle this fixture reports four sections and
        names the phantom, splitting the real section's count in two.
        """
        text = (
            "# Memory\n\n"
            "## Session Log\n" + "| 2026-01-01 | a | b |\n" * 2
            + "## Notes\n"
            + "```\n## Not A Real Heading\n" + "padding\n" * 30 + "```\n"
            + "- a note\n" * 4
        )
        census = self._census(text)
        titles = [t for t, _ in census]
        assert "Not A Real Heading" not in titles, (
            f"a fenced heading became a section: {census}"
        )
        assert census[0][0] == "Notes", (
            f"the fenced block's lines were not attributed to Notes: {census}"
        )
        assert sum(c for _, c in census) == len(text.splitlines())


class TestMemoryAutoprunReadsTheOperatorsFile:
    """DEF-797: ESPALIER_MEMORY.md is hand-edited at every handoff. A UTF-8 or
    UTF-16 byte-order mark from an editor or a PowerShell re-encode reads as
    text (the strict reads had no local handler: the hook's umbrella printed a
    traceback line and the autoprune never ran); bytes the hook cannot decode
    are named once on stderr with the encoding to re-save in, and the file is
    left alone."""

    def test_a_byte_order_marked_over_cap_file_is_pruned_and_comes_back_utf8(self, fresh_repo):
        if not _espalier_available():
            pytest.skip("espalier neither importable nor on PATH")
        memory_path = _make_over_cap_memory(fresh_repo, target_lines=EXPECTED_MEMORY_MD_CAP + 5)
        text = memory_path.read_text(encoding="utf-8")
        memory_path.write_bytes(codecs.BOM_UTF16_LE + text.encode("utf-16-le"))

        result = _run_hook(fresh_repo, "ESPALIER_MEMORY.md")

        assert result.returncode == 0, result.stderr
        assert "Traceback" not in result.stderr, result.stderr
        assert "ESPALIER_MEMORY.md autoprune:" in result.stderr, result.stderr
        raw = memory_path.read_bytes()
        assert not raw.startswith(codecs.BOM_UTF16_LE) and b"\x00" not in raw
        assert len(raw.decode("utf-8").splitlines()) <= EXPECTED_MEMORY_MD_CAP

    def test_a_file_the_hook_cannot_decode_is_named_once_and_left_alone(self, fresh_repo):
        memory_path = _make_over_cap_memory(fresh_repo, target_lines=EXPECTED_MEMORY_MD_CAP + 5)
        text = memory_path.read_text(encoding="utf-8")
        for label, data, detail in (
            ("utf-16le, no byte-order mark", text.encode("utf-16-le"),
             "NUL bytes -- UTF-16 without a byte-order mark?"),
            ("cp1252 with an accent", text.replace("Test Memory", "M\xe9moire").encode("cp1252"),
             "invalid continuation byte"),
        ):
            memory_path.write_bytes(data)
            result = _run_hook(fresh_repo, "ESPALIER_MEMORY.md")
            assert result.returncode == 0, (label, result.stderr)
            assert "Traceback" not in result.stderr, (label, result.stderr)
            assert result.stderr.count("ESPALIER_MEMORY.md is not UTF-8 text") == 1, (label, result.stderr)
            assert detail in result.stderr and "re-save it as UTF-8" in result.stderr, (label, result.stderr)
            assert "autoprune:" not in result.stderr, (label, result.stderr)
            assert memory_path.read_bytes() == data, label
