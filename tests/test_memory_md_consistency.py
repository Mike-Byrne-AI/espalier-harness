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


def _fragment_rows() -> list[str]:
    """The Session Log rows written one file each under memory/session-log.d/
    (since 2026-10-10), read through the loader. Every gate here reads them
    beside the table: reading the table alone, a future-dated or contradicting
    row in a fragment passed unseen (failure-mode review, 2026-10-10)."""
    import importlib.util
    import sys

    path = MEMORY_PATH.parent / "tools" / "cc" / "_record_fragments.py"
    spec = importlib.util.spec_from_file_location("_record_fragments_for_consistency", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return [row.line for row in mod.session_log_rows(MEMORY_PATH.parent, memory_text="")]


def _all_rows() -> list[str]:
    return _session_log_rows(MEMORY_PATH.read_text(encoding="utf-8")) + _fragment_rows()


class TestSessionLogSprintClaimsCoherent:
    def test_at_most_one_sprint_progress_claim_in_memory_md(self) -> None:
        """Sprint-progress claims ("N/M packs landed") should appear in
        at most one row. Older rows must have these claims stripped on
        prune so the file has a single authoritative current-state
        claim.
        """
        text = "\n".join([MEMORY_PATH.read_text(encoding="utf-8"), *_fragment_rows()])
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
        for row in _all_rows():
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
        future = [
            m.group(1)
            for line in _all_rows()
            if (m := _MEMORY_DATE_RE.match(line)) and m.group(1) > today
        ]
        assert not future, (
            f"future-dated Session Log row(s) {future}: each pins a SessionStart "
            "digest slot indefinitely and can never be archived by "
            "`espalier memory prune`. Fix the date cell -- do not add a clamp to "
            "the sort key."
        )

    def test_every_session_log_fragment_is_one_row_dated_as_named(self) -> None:
        """The fragments on the tree, whoever wrote them: a fragment name, one
        dated row, the row dated as the name, and no more of them than the
        merged tree's bound. The handoff driver checks a new one, but a row
        written by hand and staged by step 5's manual commit never passes it,
        and a misnamed file is skipped by every reader (failure-mode review,
        2026-10-10)."""
        root = MEMORY_PATH.parent
        problems = _fragment_problems(root, _load_tools_cc("_record_fragments.py"), _seats(root))
        assert not problems, "Session Log fragments the readers mishandle: " + "; ".join(problems)


def _load_tools_cc(filename: str):
    """A fresh copy of a ``tools/cc`` module, loaded by path."""
    import importlib.util
    import sys

    path = MEMORY_PATH.parent / "tools" / "cc" / filename
    spec = importlib.util.spec_from_file_location(f"{path.stem}_for_memory_consistency", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _seats(root: Path) -> int:
    """The named seats in ``espalier.toml``'s ``[id_blocks]``, read by the
    ledger verbs' own reader (the 3.10 floor has no tomllib). The shared
    ``_unnamed`` range is no seat. No table is one seat."""
    ledger_row = _load_tools_cc("ledger_row.py")
    blocks = ledger_row.read_id_blocks(root) or {}
    return max(1, len([s for s in blocks if s != ledger_row.UNNAMED_SEAT]))


def _fragment_problems(root: Path, rf, seats: int) -> list[str]:
    """What the readers would mishandle under ``root``'s Session Log fragment
    directory. The count is bounded on the MERGED tree: each lane prunes its
    own checkout to the cap before its push, and GitHub's merge runs no
    resolver, so two lanes that each add a row and evict the same oldest one
    land one over the cap (review of #179). With one open pull request per
    seat, at most one other lane per seat is in flight, so the bound is the
    cap plus the seats less one, and the next fragment write prunes back to
    the cap. Only fragment names count, the population the prune counts: a
    misnamed file is named as such, never folded into a count whose prune
    remedy cannot clear it (air, 2026-10-11)."""
    base = root / rf.SESSION_LOG_DIR
    files = sorted(p for p in base.iterdir() if p.is_file()) if base.is_dir() else []
    problems = []
    named_files = 0
    for p in files:
        named = rf.SESSION_LOG_NAME_RE.match(p.name)
        if named is None:
            problems.append(f"{p.name}: not a fragment name, so every reader skips it")
            continue
        named_files += 1
        rows = rf.rows_from_texts([(p.name, rf.decode(p.read_bytes()))], "")
        if len(rows) != 1:
            problems.append(f"{p.name}: {len(rows)} dated rows, not one")
        elif rows[0].date != named.group(1):
            problems.append(f"{p.name}: its row is dated {rows[0].date}")
    bound = rf.SESSION_LOG_CAP + seats - 1
    if named_files > bound:
        problems.append(
            f"{named_files} fragments, over the merged tree's bound of {bound} (the cap of "
            f"{rf.SESSION_LOG_CAP} plus {seats - 1} for the other seats' lanes in flight, one open "
            "pull request each): `python tools/cc/_record_fragments.py prune`")
    return problems


class TestTheFragmentBoundIsTheMergedTrees:
    """Review of #179: the cap was asserted on the merged tree but pruned per
    checkout, so seats handing off together turned ``main`` red on a diff that
    touched nothing. Mutations seen red: the bound read as the cap alone (32
    fragments at three seats); the count taking a misnamed file (a 31st file
    named ``notes.md`` at one seat)."""

    def _tree(self, root: Path, rf, n: int, extra: tuple[str, ...] = ()) -> Path:
        base = root / rf.SESSION_LOG_DIR
        base.mkdir(parents=True)
        for i in range(n):
            day = f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}"
            (base / f"{day}-120000-win.md").write_bytes(f"| {day} | row {i} | n |\n".encode())
        for name in extra:
            (base / name).write_bytes(b"not a row\n")
        return root

    def test_three_lanes_from_one_base_are_within_the_bound(self, tmp_path):
        rf = _load_tools_cc("_record_fragments.py")
        root = self._tree(tmp_path, rf, rf.SESSION_LOG_CAP + 2)
        assert _fragment_problems(root, rf, seats=3) == []

    def test_one_past_the_bound_is_said_with_the_bound(self, tmp_path):
        rf = _load_tools_cc("_record_fragments.py")
        root = self._tree(tmp_path, rf, rf.SESSION_LOG_CAP + 3)
        [problem] = _fragment_problems(root, rf, seats=3)
        assert f"over the merged tree's bound of {rf.SESSION_LOG_CAP + 2}" in problem

    def test_one_seat_is_bound_by_the_cap(self, tmp_path):
        rf = _load_tools_cc("_record_fragments.py")
        root = self._tree(tmp_path, rf, rf.SESSION_LOG_CAP + 1)
        assert len(_fragment_problems(root, rf, seats=1)) == 1

    def test_a_misnamed_file_is_named_and_not_counted(self, tmp_path):
        rf = _load_tools_cc("_record_fragments.py")
        root = self._tree(tmp_path, rf, rf.SESSION_LOG_CAP, extra=("notes.md",))
        assert _fragment_problems(root, rf, seats=1) == ["notes.md: not a fragment name, so every reader skips it"]

    def test_the_seats_are_this_trees_named_blocks(self, tmp_path):
        (tmp_path / "espalier.toml").write_text(
            '[id_blocks]\na = { DEF = "1-9" }\nb = { DEF = "10-19" }\n_unnamed = { DEF = "20-29" }\n',
            encoding="utf-8")
        assert _seats(tmp_path) == 2
        assert _seats(tmp_path / "nowhere") == 1
