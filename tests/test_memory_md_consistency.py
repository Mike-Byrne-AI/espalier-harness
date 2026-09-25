"""TP-68 — ESPALIER_MEMORY.md session-log consistency tests.

Pre-TP-68, three different session-log rows carried mutually
contradictory sprint-progress claims (rows 78/79/80 of ESPALIER_MEMORY.md at
the v0.7.0a2 tag claimed "11/12 / 12/12 / 12/12 packs landed" and the
12/12 rows also claimed "Next pack: TP-61 LAST"). The contradictions
arose because the documented prune protocol ("Keep 5 most recent. Move
older to docs/session-archive.md.") had no mechanical reinforcement.

These tests run on every commit so the next handoff can't reintroduce
the same drift.
"""
from __future__ import annotations

import re
from pathlib import Path


MEMORY_PATH = Path(__file__).resolve().parent.parent / "ESPALIER_MEMORY.md"
_SPRINT_CLAIM_RE = re.compile(r"(\d+)/(\d+)\s+packs?\s+landed", re.IGNORECASE)


def _session_log_rows(text: str) -> list[str]:
    """Return the data-row lines of the Session Log table.

    A data row is any line under `## Session Log` that starts with `|`,
    skipping the header row (`| Date | What Happened | Notes |`) and
    the separator (`|------|...`).
    """
    in_session_log = False
    rows: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            in_session_log = line.strip() == "## Session Log"
            continue
        if not in_session_log:
            continue
        if not line.startswith("|"):
            continue
        stripped = line.strip()
        if stripped.startswith("|---") or stripped.startswith("| Date "):
            continue
        rows.append(line)
    return rows


class TestSessionLogSprintClaimsCoherent:
    def test_at_most_one_sprint_progress_claim_in_memory_md(self) -> None:
        """Sprint-progress claims ("N/M packs landed") should appear in
        at most one row. Older rows must have these claims stripped on
        prune so the file has a single authoritative current-state
        claim.
        """
        text = MEMORY_PATH.read_text(encoding="utf-8")
        matches = _SPRINT_CLAIM_RE.findall(text)
        assert len(matches) <= 1, (
            f"Multiple sprint-progress claims in ESPALIER_MEMORY.md: {matches}. "
            "Strip older claims when pruning, or update this test if "
            "intentional."
        )

    def test_full_count_row_does_not_also_claim_next_pack(self) -> None:
        """A row claiming "N/N packs landed" (full count) must not also
        contain "Next pack" — those statements contradict.

        Pre-TP-68 row 80 carried both "v0.7 sprint progress: 12/12 packs
        landed." and "Next pack per execution-order doc: TP-61 (LAST)".
        Either the count was wrong (TP-61 unlanded → 11/12) or the
        "next" forward-reference was stale.
        """
        offenders: list[str] = []
        for row in _session_log_rows(MEMORY_PATH.read_text(encoding="utf-8")):
            for landed, total in _SPRINT_CLAIM_RE.findall(row):
                if landed == total and "Next pack" in row:
                    offenders.append(
                        f"{landed}/{total} packs landed + 'Next pack' in same row"
                    )
        assert not offenders, (
            "Session-log row claims full count AND 'Next pack' "
            f"(contradiction): {offenders}. Resolve by adjusting the "
            "count or rephrasing the forward-reference."
        )


class TestSessionLogDatesAreSane:
    """Recency is read from the date cell, so a bad date cell is a live defect.

    `tools/cc/hooks/session_start.py::_memory_toc` ranks the SessionStart digest
    by each row's `| YYYY-MM-DD`, and `espalier memory prune` archives by the
    same field. That is deliberate -- position was the previous oracle and it
    served the three OLDEST rows as "recent sessions" for ~10 days -- but it
    moves authority from something mechanically unforgeable to a hand-typed
    cell, and nothing validated that cell anywhere in the repo.

    Lives here rather than beside the digest tests because this reads the LIVE
    `ESPALIER_MEMORY.md`, which a release export prunes; this module already
    reads it, already owns `_session_log_rows`, and is already registered in
    `conftest._FULL_TREE_NODEIDS`. Putting it in `test_hooks.py` pulled that
    whole module into the dev-tree-only class and reddened
    `test_every_dev_tree_test_is_full_tree_or_exempt`.
    """

    def test_no_session_log_row_is_future_dated(self) -> None:
        """A future-dated row is immortal, not merely loud.

        A year fat-finger (`2062-08-16`) takes a permanent digest slot AND --
        the half worth detecting -- sorts date-MAX forever, so `memory prune`
        never selects it and autoprune permanently loses a slot of cap relief.

        Declining a `date.today()` clamp inside the hook's sort key is right:
        wall-clock-dependent output in a reporter hook is its own defect.
        Declining to DETECT the bad cell was not, and this is that detection.
        """
        from datetime import datetime, timezone

        from espalier.cli import _MEMORY_DATE_RE

        # UTC, not local: rows are authored by handoffs running in any zone, so
        # a local `date.today()` would red spuriously for a few hours a day.
        today = datetime.now(timezone.utc).date().isoformat()
        text = MEMORY_PATH.read_text(encoding="utf-8")
        future = [
            m.group(1)
            for line in _session_log_rows(text)
            if (m := _MEMORY_DATE_RE.match(line)) and m.group(1) > today
        ]
        assert not future, (
            f"future-dated Session Log row(s) {future}: each pins a SessionStart "
            "digest slot indefinitely and can never be archived by "
            "`espalier memory prune`. Fix the date cell -- do not add a clamp to "
            "the sort key."
        )
