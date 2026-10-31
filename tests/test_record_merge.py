"""Contract tests for ``tools/cc/record_merge.py``: the shape-aware merge of
the record files two machines' lanes conflict on by construction.

Three layers, each with its own oracle:

* the pure resolvers (hunk parser, Session Log row algebra, ledger row and
  derived-line rules, the probes union) on synthetic conflict text;
* the orchestration (``merge_ref_in``, ``probe_conflicts``, the cap step) on a
  recording fake runner, for the refusals and the argv each step issues;
* two REAL-GIT cases, because git is the only honest oracle for what a merge
  conflicts on: a bare origin with two clones standing in for the two
  machines, and a replay of the live 2026-10-05 witness (PR 88 against main)
  from this checkout's own objects, skipped where those commits are not
  reachable.

The real-git cases run ``espalier memory prune`` through the module's own
ladder, so the cap step is driven, not mocked.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests._git_oracle import _git_env
from tests.test_generate_ledger_regions import STORED_ALL, _ledger
from tests._live_tree import copy_checkout

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE = REPO_ROOT / "tools" / "cc" / "record_merge.py"
GEN = REPO_ROOT / "tools" / "cc" / "generate_ledger_regions.py"


def _load(path: Path, alias: str):
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rm():
    return _load(MODULE, "record_merge_under_test")


@pytest.fixture(scope="module")
def gen():
    return _load(GEN, "gen_for_record_merge")


# ── synthetic conflict text ──────────────────────────────────────────────────

def _diff3(ours: list[str], base: list[str], theirs: list[str]) -> str:
    return "\n".join(["<<<<<<< ours", *ours, "||||||| base", *base, "=======", *theirs, ">>>>>>> theirs"])


def _merge_style(ours: list[str], theirs: list[str]) -> str:
    return "\n".join(["<<<<<<< ours", *ours, "=======", *theirs, ">>>>>>> theirs"])


def _row(date: str, text: str) -> str:
    return f"| {date} | **{text}** | Proof: a thing |"


class TestParseConflicts:
    def test_merge_style_markers_yield_a_two_sided_hunk(self, rm):
        text = "a\n" + _merge_style(["x"], ["y"]) + "\nb\n"
        segs = rm.parse_conflicts(text)
        assert [k for k, _ in segs] == ["text", "conflict", "text"]
        hunk = segs[1][1]
        assert (hunk.ours, hunk.base, hunk.theirs) == (["x"], None, ["y"])
        assert segs[2][1] == ["b", ""]  # the trailing newline survives the round trip

    def test_diff3_markers_carry_the_base_section(self, rm):
        segs = rm.parse_conflicts(_diff3(["x"], ["o"], ["y"]))
        hunk = segs[0][1]
        assert (hunk.ours, hunk.base, hunk.theirs) == (["x"], ["o"], ["y"])

    def test_text_without_markers_round_trips_byte_for_byte(self, rm):
        text = "| 2026-10-05 | **a** | b |\n|---|---|---|\nplain\n"
        segs = rm.parse_conflicts(text)
        assert rm._join(segs, lambda h: []) == text

    def test_an_unterminated_hunk_is_refused(self, rm):
        with pytest.raises(rm.Unresolvable, match="unterminated"):
            rm.parse_conflicts("<<<<<<< ours\nx\n=======\ny\n")

    def test_a_table_separator_is_not_a_marker(self, rm):
        """`|------|` and `=======` differ; only the exact seven-equals line
        separates the sides, and only at column 0."""
        text = "<<<<<<< ours\n|------|\n=======\n|---|\n>>>>>>> theirs"
        hunk = rm.parse_conflicts(text)[0][1]
        assert hunk.ours == ["|------|"] and hunk.theirs == ["|---|"]


class TestSessionLogRows:
    A = _row("2026-10-05", "THE MAC'S LANE LANDED")
    B = _row("2026-10-05", "THE WINDOWS BOX'S LANE LANDED")
    OLD1 = _row("2026-09-29", "AN OLD ROW")
    OLD2 = _row("2026-09-28", "AN OLDER ROW")
    OLD3 = _row("2026-09-27", "THE OLDEST ROW")

    def test_two_rows_inserted_at_the_anchor_are_both_kept_ours_first(self, rm):
        kept, new = rm.resolve_memory_hunk(rm.Hunk([self.A], [], [self.B]))
        assert kept == [self.A, self.B] and new == [self.A, self.B]

    def test_a_tail_both_sides_evicted_differently_keeps_only_what_both_kept(self, rm):
        hunk = rm.Hunk([self.OLD1, self.OLD2], [self.OLD1, self.OLD2, self.OLD3], [])
        kept, new = rm.resolve_memory_hunk(hunk)
        assert kept == [] and new == []
        hunk = rm.Hunk([self.OLD1], [self.OLD1, self.OLD2, self.OLD3], [self.OLD1, self.OLD2])
        assert rm.resolve_memory_hunk(hunk) == ([self.OLD1], [])

    def test_a_row_rewritten_on_one_side_and_evicted_on_the_other_survives_as_rewritten(self, rm):
        edited = self.OLD1.replace("AN OLD ROW", "AN OLD ROW, CORRECTED")
        kept, new = rm.resolve_memory_hunk(rm.Hunk([edited], [self.OLD1], []))
        assert kept == [edited] and new == [edited]

    def test_the_same_row_added_on_both_sides_is_kept_once(self, rm):
        kept, new = rm.resolve_memory_hunk(rm.Hunk([self.A], [], [self.A]))
        assert kept == [self.A] and new == [self.A]

    def test_blank_lines_inside_the_hunk_are_dropped(self, rm):
        kept, _ = rm.resolve_memory_hunk(rm.Hunk([self.A, ""], [], ["", self.B]))
        assert kept == [self.A, self.B]

    def test_a_cell_with_an_escaped_pipe_is_one_row_kept_whole(self, rm):
        piped = r"| 2026-10-05 | **a cell with `a \| b` in it** | note |"
        kept, _ = rm.resolve_memory_hunk(rm.Hunk([piped], [], [self.B]))
        assert kept == [piped, self.B]

    def test_prose_in_the_hunk_is_refused_naming_the_file(self, rm):
        with pytest.raises(rm.Unresolvable, match=r"ESPALIER_MEMORY\.md: a conflict outside the Session Log rows"):
            rm.resolve_memory_hunk(rm.Hunk(["**Stack:** python"], ["**Stack:** py"], ["**Stack:** Python 3"]))

    def test_a_hunk_without_a_base_section_is_refused_rather_than_guessed(self, rm):
        """`git merge-file --diff3` always emits the base section (even empty);
        a two-sided hunk means some other producer wrote the markers, and a
        two-sided rule ("rows against nothing keeps nothing") would silently
        drop a side's rows (failure-mode review, 2026-10-05)."""
        with pytest.raises(rm.Unresolvable, match="carried no base section"):
            rm.resolve_memory_hunk(rm.Hunk([self.A], None, [self.B]))
        with pytest.raises(rm.Unresolvable, match="carried no base section"):
            rm.resolve_memory_hunk(rm.Hunk([self.OLD1], None, []))

    def test_a_whole_file_with_anchor_and_tail_hunks_resolves_and_names_the_new_rows(self, rm):
        head = "## Session Log\n\n| Date | What Happened | Notes |\n|------|--------------|-------|\n"
        text = (head + _diff3([self.A], [], [self.B]) + "\n" + _row("2026-10-01", "SHARED") + "\n"
                + _diff3([self.OLD1], [self.OLD1, self.OLD2], []) + "\n\n## Categorized memory\n")
        out, new = rm.resolve_memory_text(text)
        assert new == [self.A, self.B]
        assert out == (head + self.A + "\n" + self.B + "\n" + _row("2026-10-01", "SHARED")
                       + "\n\n## Categorized memory\n")


class TestMemoryCap:
    def _tree(self, tmp_path: Path, *, hook_cap: int | None, policy_cap: int | None) -> Path:
        tmp_path.mkdir(parents=True, exist_ok=True)
        if hook_cap is not None:
            hook = tmp_path / "tools" / "cc" / "hooks" / "post_write_check.py"
            hook.parent.mkdir(parents=True)
            hook.write_text(f"# a hook\n_MEMORY_MD_CAP = {hook_cap}\n_AUTOPRUNE_HEADROOM = 1\n", encoding="utf-8")
        policy = f"**Pruning policy:** Bounded at {policy_cap} lines.\n" if policy_cap else ""
        (tmp_path / "ESPALIER_MEMORY.md").write_text("# Memory\n\n" + policy, encoding="utf-8")
        return tmp_path

    def test_the_cap_is_the_hook_constant_when_the_hook_is_there(self, rm, tmp_path):
        assert rm.memory_cap(self._tree(tmp_path, hook_cap=7, policy_cap=9)) == 7

    def test_the_cap_falls_back_to_the_policy_sentence_then_to_none(self, rm, tmp_path):
        assert rm.memory_cap(self._tree(tmp_path, hook_cap=None, policy_cap=9)) == 9
        assert rm.memory_cap(self._tree(tmp_path / "bare", hook_cap=None, policy_cap=None)) is None

    def test_an_over_cap_file_runs_the_prune_verb_with_the_merged_rows_reserved(self, rm, tmp_path):
        root = self._tree(tmp_path, hook_cap=4, policy_cap=None)
        (root / "ESPALIER_MEMORY.md").write_text("1\n2\n3\n4\n5\n6\n", encoding="utf-8")
        calls: list[list[str]] = []

        def fake_run(argv, **kw):
            calls.append(list(argv))
            return 0, "", ""

        said: list[str] = []
        assert rm.restore_memory_cap(root, new_rows=["5", "6"], run=fake_run, say=said.append) is True
        assert len(calls) == 1 and said == []
        tail = calls[0][-10:]
        assert tail[-9:] == ["memory", "prune", "--rows", "2", "--root", str(root), "--allow-empty",
                             "--keep-newest", "2"], calls[0]

    def test_where_the_loader_is_deployed_the_cap_step_evicts_no_table_row(self, rm, tmp_path):
        """Review of #179: the cap step evicted main's oldest frozen-table row
        to make room for a merged-in pre-freeze row, and the resolve reported
        merged. Where the loader is deployed, the over-cap file is said and
        nothing is pruned. Mutation seen red: the prune verb spawned."""
        root = self._tree(tmp_path, hook_cap=4, policy_cap=None)
        (root / "tools" / "cc" / "_record_fragments.py").write_text("# the loader\n", encoding="utf-8")
        (root / "ESPALIER_MEMORY.md").write_text("1\n2\n3\n4\n5\n6\n", encoding="utf-8")
        said: list[str] = []
        assert rm.restore_memory_cap(root, new_rows=["5"], run=lambda *a, **k: pytest.fail("spawned"),
                                     say=said.append) is False
        assert len(said) == 1 and "2 line(s) over its cap of 4" in said[0]
        assert "evicts no row of the frozen table" in said[0]

    def test_a_file_at_or_under_cap_spawns_nothing(self, rm, tmp_path):
        root = self._tree(tmp_path, hook_cap=4, policy_cap=None)
        (root / "ESPALIER_MEMORY.md").write_text("1\n2\n3\n4\n", encoding="utf-8")
        assert rm.restore_memory_cap(root, new_rows=["4"], run=lambda *a, **k: pytest.fail("spawned")) is True

    def test_a_prune_that_fails_on_every_rung_is_a_note_with_the_way_back(self, rm, tmp_path):
        root = self._tree(tmp_path, hook_cap=2, policy_cap=None)
        (root / "ESPALIER_MEMORY.md").write_text("1\n2\n3\n", encoding="utf-8")
        said: list[str] = []
        assert rm.restore_memory_cap(root, new_rows=["3"], run=lambda *a, **k: (1, "", "boom"),
                                     say=said.append) is False
        assert len(said) == 1 and "espalier memory prune" in said[0] and "over its cap of 2" in said[0]

    def test_a_runner_that_raises_a_foreign_error_is_a_note_not_a_raise(self, rm, tmp_path):
        """ship.py injects a runner whose failures are ship.Refused, not this
        module's class: a prune that times out must stay the documented note,
        never an exception that aborts a fully resolved merge (both reviews)."""
        root = self._tree(tmp_path, hook_cap=2, policy_cap=None)
        (root / "ESPALIER_MEMORY.md").write_text("1\n2\n3\n", encoding="utf-8")

        def foreign(*a, **k):
            raise RuntimeError("espalier memory prune took longer than 30s")

        said: list[str] = []
        assert rm.restore_memory_cap(root, new_rows=["3"], run=foreign, say=said.append) is False
        assert len(said) == 1 and "took longer than 30s" in said[0]

    def test_a_merged_in_row_the_prune_archived_is_named(self, rm, tmp_path):
        """The reservation is by date rank; a merged-in row carrying a wrong,
        older date can still be evicted, and the only place that is visible is
        a re-read after the prune."""
        root = self._tree(tmp_path, hook_cap=2, policy_cap=None)
        path = root / "ESPALIER_MEMORY.md"
        path.write_text("| 2026-10-05 | new |\n| 2026-09-01 | merged in, dated wrong |\n| 2026-10-04 | old |\n",
                        encoding="utf-8")

        def prune(argv, **kw):   # the verb evicts the oldest by date: the merged-in row
            path.write_text("| 2026-10-05 | new |\n| 2026-10-04 | old |\n", encoding="utf-8")
            return 0, "", ""

        said: list[str] = []
        assert rm.restore_memory_cap(root, new_rows=["| 2026-09-01 | merged in, dated wrong |"], run=prune,
                                     say=said.append) is True
        assert len(said) == 1 and "archived a merged-in row" in said[0] and "dated wrong" in said[0]

    def test_no_readable_cap_is_a_note_not_a_guess(self, rm, tmp_path):
        root = self._tree(tmp_path, hook_cap=None, policy_cap=None)
        said: list[str] = []
        assert rm.restore_memory_cap(root, new_rows=["x"], run=lambda *a, **k: pytest.fail("spawned"),
                                     say=said.append) is False
        assert "no memory cap could be read" in said[0]

    # Reads the repository's own memory file (a doc, and one the release
    # export prunes): the contract slice, and the full tree only.
    @pytest.mark.contract
    def test_the_cap_read_from_this_checkout_is_the_hooks_constant(self, rm):
        """A parity pin, beside the date-regex one: an annotation on the hook's
        constant or a reworded policy sentence would degrade the cap to None
        and the merge would commit an over-cap file with only a note."""
        hook = _load(REPO_ROOT / "tools" / "cc" / "hooks" / "post_write_check.py", "_pwc_for_record_merge")
        assert rm.memory_cap(REPO_ROOT) == hook._MEMORY_MD_CAP
        sentence = rm._POLICY_CAP_RE.search((REPO_ROOT / "ESPALIER_MEMORY.md").read_text(encoding="utf-8"))
        assert sentence is not None and int(sentence.group(1)) == hook._MEMORY_MD_CAP

    def test_the_archive_undo_restores_bytes_or_absence(self, rm, tmp_path):
        archive = tmp_path / "docs" / "session-archive.md"
        archive.parent.mkdir()
        archive.write_text("appended by a prune\n", encoding="utf-8")
        rm._restore_archive(tmp_path, None)
        assert not archive.exists()
        archive.write_text("appended again\n", encoding="utf-8")
        rm._restore_archive(tmp_path, b"what was there\n")
        assert archive.read_bytes() == b"what was there\n"


# ── the ledger ───────────────────────────────────────────────────────────────

def _member(rid: str, what: str = "what") -> str:
    return f"| `{rid}` | site | {what} | minor |"


def _index(rid: str, section: str = "§C1") -> str:
    return f"| `{rid}` | {section} | site |"


class TestLedgerHunks:
    def test_two_rows_filed_into_the_same_slot_are_both_kept_ours_first(self, rm, gen):
        out = rm.resolve_ledger_hunk(rm.Hunk([_member("DEF-9")], [], [_member("DEF-8")]), gen)
        assert out == [_member("DEF-9"), _member("DEF-8")]

    def test_the_same_new_id_with_different_text_is_two_machines_minting_one_id(self, rm, gen):
        hunk = rm.Hunk([_member("DEF-9", "mac")], [], [_member("DEF-9", "win")])
        with pytest.raises(rm.Unresolvable, match=r"DEF-9 was filed on both sides.*No ledger verb renames"):
            rm.resolve_ledger_hunk(hunk, gen)

    def test_the_two_machine_refusal_names_only_verbs_ledger_row_has(self, rm, gen):
        """Its first text sent the operator to a ledger_row "renumber" verb that
        tool never had (found by air on 2026-10-09, mid-merge). The verbs it
        names are read against ledger_row.py's own subcommands; the steps
        themselves (rename the id in the member row, the index row and the
        probe, then repin the new id) were driven on a scratch ledger."""
        import re

        hunk = rm.Hunk([_member("DEF-9", "mac")], [], [_member("DEF-9", "win")])
        with pytest.raises(rm.Unresolvable) as refusal:
            rm.resolve_ledger_hunk(hunk, gen)
        source = (Path(__file__).resolve().parents[1] / "tools" / "cc" / "ledger_row.py").read_text(encoding="utf-8")
        verbs = set(re.findall(r"add_parser\(\s*\"(\w+)\"", source))
        named = set(re.findall(r"ledger_row\.py (\w+)", str(refusal.value)))
        assert verbs >= {"strike", "file", "class", "repin"}, verbs   # the reader still finds the verbs
        assert named and named <= verbs, (named, verbs)

    def test_the_same_new_row_on_both_sides_is_kept_once(self, rm, gen):
        out = rm.resolve_ledger_hunk(rm.Hunk([_member("DEF-9")], [], [_member("DEF-9")]), gen)
        assert out == [_member("DEF-9")]

    def test_derived_lines_on_both_sides_keep_ours(self, rm, gen):
        ours = ["**Live: 325** — 162 logic bugs · 160 hygiene · 3 operator actions.", "**152** reach an adopter."]
        theirs = ["**Live: 322** — 158 logic bugs · 161 hygiene · 3 operator actions.", "**148** reach an adopter."]
        base = ["**Live: 321** — 157 logic bugs · 161 hygiene · 3 operator actions.", "**147** reach an adopter."]
        assert rm.resolve_ledger_hunk(rm.Hunk(ours, base, theirs), gen) == ours

    def test_the_section_two_header_and_members_lines_are_derived(self, rm, gen):
        ours = ["## §2 — Open fixes, by unit of work (325 LIVE issues in 47 classes + 149 standalone)"]
        theirs = ["## §2 — Open fixes, by unit of work (322 LIVE issues in 46 classes + 148 standalone)"]
        assert rm.resolve_ledger_hunk(rm.Hunk(ours, [], theirs), gen) == ours
        ours, theirs = ["**Members (168)** — derived, never typed"], ["**Members (169)** — derived, never typed"]
        assert rm.resolve_ledger_hunk(rm.Hunk(ours, [], theirs), gen) == ours

    def test_class_index_rows_merge_by_section(self, rm, gen):
        c77 = "| [§C77](#c77--a-class) | A class | LOGIC_BUG | ADOPTER | ~1 LOC |"
        c78 = "| [§C78](#c78--another) | Another | HYGIENE | MAINTAINER | ~1 LOC |"
        assert rm.resolve_ledger_hunk(rm.Hunk([c77], [], [c78]), gen) == [c77, c78]

    _C0 = "| [§C0](#c0--standalone) | Standalone | MIXED | MIXED | — |"

    def _counted(self, row: str, n: int) -> str:
        return row.replace("| Standalone |", f"| Standalone | {n} |")

    def test_a_class_row_that_differs_only_by_a_stored_count_is_one_row(self, rm, gen):
        """Two older lanes' counts, or an older lane's count against the
        count-free row: one row either way, and the generator strips the count
        after the merge."""
        c0 = self._C0
        ours, theirs = self._counted(c0, 168), self._counted(c0, 169)
        assert rm.resolve_ledger_hunk(rm.Hunk([ours], [], [theirs]), gen) == [ours]
        assert rm.resolve_ledger_hunk(rm.Hunk([c0], [self._counted(c0, 167)], [theirs]), gen) == [c0]

    def test_a_class_row_retagged_on_one_side_keeps_the_retag_past_the_other_sides_count(self, rm, gen):
        base = self._counted(self._C0, 167)
        retagged = self._C0.replace("| MIXED | MIXED |", "| MIXED | MAINTAINER |")
        assert rm.resolve_ledger_hunk(rm.Hunk([retagged], [base], [self._counted(self._C0, 168)]), gen) == [retagged]
        assert rm.resolve_ledger_hunk(rm.Hunk([self._C0], [base], [retagged]), gen) == [retagged]

    def test_a_class_row_edited_on_both_sides_is_refused_by_section(self, rm, gen):
        """The index stores no count, so a row that differs on both sides is a
        title, tag or effort edited twice: the operator's, as a member row's
        is. Before the counts left, ours was taken and theirs' edit dropped."""
        hunk = rm.Hunk([self._C0.replace("Standalone", "Loose")], [self._C0],
                       [self._C0.replace("| — |", "| ~5 LOC |")])
        with pytest.raises(rm.Unresolvable, match="§C0 was changed on both sides"):
            rm.resolve_ledger_hunk(hunk, gen)

    @pytest.mark.parametrize("old, new", [
        (["**Live: 325** — 162 logic bugs · 160 hygiene · 3 operator actions.", "**152** reach an adopter."],
         ["**Counts are derived, never stored here:** see --print."]),
        (["## §2 — Open fixes, by unit of work (325 LIVE issues in 47 classes + 149 standalone)"],
         ["## §2 — Open fixes, by unit of work"]),
        (["## §3 — New features & product bets (55)"], ["## §3 — New features & product bets"]),
        (["| population | live | what it means |", "|---|---|---|", "| LOGIC_BUG | 162 | code behaves wrongly |"],
         ["| population | what it means |", "|---|---|", "| LOGIC_BUG | code behaves wrongly |"]),
        (["| audience | live |", "|---|---|", "| **ADOPTER** — someone | **152** |", "| OPERATOR | 6 |"],
         ["| audience |", "|---|", "| **ADOPTER** — someone |", "| OPERATOR |"]),
        (["| § | class | members | population | audience | effort |", "|---|---|---|---|---|---|"],
         ["| § | class | population | audience | effort |", "|---|---|---|---|---|"]),
        (["**Members (168)** — derived, never typed"], ["**Members**"]),
    ])
    def test_a_stored_total_against_its_count_free_line_resolves_by_shape(self, rm, gen, old, new):
        """A lane cut before the counts left, merged with one cut after (either
        way round): every such line is the generator's, so the hunk keeps ours'
        and the generator strips whatever total survives, where a line it did
        not name would be refused as prose."""
        assert rm.resolve_ledger_hunk(rm.Hunk(new, old, old), gen) == new
        assert rm.resolve_ledger_hunk(rm.Hunk(old, old, new), gen) == old

    def test_a_row_changed_on_one_side_only_takes_that_side(self, rm, gen):
        base, changed = _member("DEF-1"), _member("DEF-1", "repinned")
        assert rm.resolve_ledger_hunk(rm.Hunk([changed], [base], [base]), gen) == [changed]
        assert rm.resolve_ledger_hunk(rm.Hunk([base], [base], [changed]), gen) == [changed]

    def test_a_row_changed_on_both_sides_is_refused_by_id(self, rm, gen):
        hunk = rm.Hunk([_member("DEF-1", "a")], [_member("DEF-1")], [_member("DEF-1", "b")])
        with pytest.raises(rm.Unresolvable, match="DEF-1 was changed on both sides"):
            rm.resolve_ledger_hunk(hunk, gen)

    def test_a_row_removed_on_one_side_and_untouched_on_the_other_is_dropped(self, rm, gen):
        base = _member("DEF-1")
        out = rm.resolve_ledger_hunk(rm.Hunk([_member("DEF-9")], [base], [base, _member("DEF-8")]), gen)
        assert out == [_member("DEF-9"), _member("DEF-8")]

    def test_a_row_removed_on_one_side_and_changed_on_the_other_is_refused(self, rm, gen):
        hunk = rm.Hunk([], [_member("DEF-1")], [_member("DEF-1", "changed")])
        with pytest.raises(rm.Unresolvable, match="changed on one side and removed on the other"):
            rm.resolve_ledger_hunk(hunk, gen)

    def test_prose_on_both_sides_is_refused_as_the_operators(self, rm, gen):
        hunk = rm.Hunk(["**Unit of work.** Ours."], ["**Unit of work.** Base."], ["**Unit of work.** Theirs."])
        with pytest.raises(rm.Unresolvable, match="a conflict in prose"):
            rm.resolve_ledger_hunk(hunk, gen)

    def test_theirs_new_rows_land_after_ours_last_row_not_after_a_derived_line(self, rm, gen):
        members = "**Members (3)** — derived, never typed"
        out = rm.resolve_ledger_hunk(
            rm.Hunk([members, "", _member("DEF-9")], ["**Members (2)** — derived, never typed", ""],
                    [members, "", _member("DEF-8")]), gen)
        assert out == [members, "", _member("DEF-9"), _member("DEF-8")]

    def test_when_ours_has_no_rows_the_hunk_takes_theirs_structure(self, rm, gen):
        members_o, members_t = "**Members (2)** — x", "**Members (3)** — x"
        out = rm.resolve_ledger_hunk(rm.Hunk([members_o], ["**Members (1)** — x"], [members_t, _member("DEF-8")]), gen)
        assert out == [members_t, _member("DEF-8")]

    def test_appendix_rows_merge_like_member_rows(self, rm, gen):
        out = rm.resolve_ledger_hunk(rm.Hunk([_index("DEF-9")], [], [_index("DEF-8", "§C0")]), gen)
        assert out == [_index("DEF-9"), _index("DEF-8", "§C0")]

    def test_a_hunk_without_a_base_section_is_refused(self, rm, gen):
        with pytest.raises(rm.Unresolvable, match="carried no base section"):
            rm.resolve_ledger_hunk(rm.Hunk([_member("DEF-9")], None, [_member("DEF-8")]), gen)

    def test_rows_of_two_tables_in_one_hunk_are_refused_not_misfiled(self, rm, gen):
        """Code review, driven: a hunk spanning the tail of one class and the
        head of the next would have put theirs' new row after ours' LAST row,
        in the wrong class, and the generator then converged the counts around
        the misfiling."""
        members = "**Members (1)** — derived, never typed"
        hunk = rm.Hunk([_member("DEF-9"), "", members, _member("DEF-5")], ["", members, _member("DEF-5")],
                       [_member("DEF-8"), "", members, _member("DEF-5")])
        with pytest.raises(rm.Unresolvable, match="spans rows of more than one table"):
            rm.resolve_ledger_hunk(hunk, gen)


class TestGeneratorSurface:
    """The resolver reaches into the generator by name; a rename there must red
    here, not degrade every ledger merge into a prose refusal or a traceback."""

    REACHED = ("_MEMBER_ID", "_CLASS_TABLE_ROW", "find_drift", "apply_writable", "_atomic_write",
               "ledger_lock", "LedgerBusy", "_PROBES", "class_row_without_count")

    def test_every_generator_name_the_resolver_reads_resolves(self, rm, gen):
        for name in rm._DERIVED_PATTERN_NAMES + self.REACHED:
            assert hasattr(gen, name), name
        for name in rm._DERIVED_PATTERN_NAMES:
            assert hasattr(getattr(gen, name), "match"), name

    def test_the_sibling_is_loaded_under_a_private_alias_and_the_probes_path_is_put_back(self, rm, gen, tmp_path):
        """A test module shares one generator instance under its bare name;
        a merge that replaced it, or left its probes path on a temp dir, would
        hand every later caller an empty roster (failure-mode review, driven)."""
        sentinel = object()
        sys.modules["generate_ledger_regions"] = sentinel  # type: ignore[assignment]
        try:
            loaded = rm._load_sibling("generate_ledger_regions")
            assert sys.modules["generate_ledger_regions"] is sentinel
            assert sys.modules["_record_merge_generate_ledger_regions"] is loaded
            was = loaded._PROBES
            probes = tmp_path / "LEDGER_PROBES.json"
            probes.write_text(json.dumps(_probes_doc("DEF-1", "DEF-2"), indent=1) + "\n", encoding="utf-8")
            rm.regenerate_ledger(_ledger(), loaded, probes)
            assert loaded._PROBES == was
        finally:
            del sys.modules["generate_ledger_regions"]


def _probes_doc(*ids: str, **top) -> dict:
    doc = {"_README": "roster", "_generated": "2026-10-01", **top,
           "probes": [{"id": i, "subject": "site", "cmd": f"echo {i}", "open_value": i,
                       "why_not": None, "row_sha": "x"} for i in ids]}
    return doc


class TestRegenerateLedger:
    def _probes(self, tmp_path: Path, *ids: str) -> Path:
        p = tmp_path / "LEDGER_PROBES.json"
        p.write_text(json.dumps(_probes_doc(*ids), indent=1) + "\n", encoding="utf-8")
        return p

    def test_a_stored_total_a_merge_left_is_stripped(self, rm, gen, tmp_path):
        text = _ledger(stored=STORED_ALL, count=1)  # two rows, the stored totals say one
        out = rm.regenerate_ledger(text, gen, self._probes(tmp_path, "DEF-1", "DEF-2"))
        assert out == _ledger()
        assert gen.find_drift(out) == []

    def test_drift_the_generator_cannot_write_is_a_refusal_naming_the_region(self, rm, gen, tmp_path):
        struck = _ledger(c1_rows=("| ~~`DEF-1`~~ | site | what | major |", "| `DEF-2` | site | what | minor |"),
                         appendix=("| ~~`DEF-1`~~ | §C1 | site |", "| `DEF-2` | §C1 | site |"),
                         stored=STORED_ALL, count=1)
        with pytest.raises(rm.Unresolvable, match="does not converge.*probe-roster"):
            rm.regenerate_ledger(struck, gen, self._probes(tmp_path, "DEF-1", "DEF-2"))


class TestProbesThreeWay:
    def _text(self, *ids: str, **top) -> str:
        return json.dumps(_probes_doc(*ids, **top), indent=1) + "\n"

    def test_probes_added_on_each_side_are_unioned_and_no_total_is_kept(self, rm):
        """A side branched before 2026-10-12 still stores ``_count``; the
        union drops it, whichever sides carry it. Dies to: the key carried
        through from either side."""
        out = json.loads(rm.resolve_probes(self._text("A", "B", _count=2), self._text("A", "B", "C", _count=3),
                                           self._text("A", "B", "D")))
        assert [p["id"] for p in out["probes"]] == ["A", "B", "C", "D"]
        assert "_count" not in out
        out = json.loads(rm.resolve_probes(self._text("A", "B"), self._text("A", "B", "C"),
                                           self._text("A", "B", "D", _count=3)))
        assert "_count" not in out

    def test_a_probe_retired_on_one_side_stays_retired(self, rm):
        out = json.loads(rm.resolve_probes(self._text("A", "B"), self._text("B"), self._text("A", "B", "D")))
        assert [p["id"] for p in out["probes"]] == ["B", "D"]

    def test_a_probe_changed_on_one_side_takes_that_side(self, rm):
        ours = json.loads(self._text("A", "B"))
        ours["probes"][0]["open_value"] = "re-pinned"
        out = json.loads(rm.resolve_probes(self._text("A", "B"), json.dumps(ours), self._text("A", "B", "D")))
        assert out["probes"][0]["open_value"] == "re-pinned" and len(out["probes"]) == 3

    def test_a_probe_changed_on_both_sides_is_refused_by_id(self, rm):
        ours, theirs = json.loads(self._text("A")), json.loads(self._text("A"))
        ours["probes"][0]["open_value"], theirs["probes"][0]["open_value"] = "x", "y"
        with pytest.raises(rm.Unresolvable, match="probe for A was changed on both sides"):
            rm.resolve_probes(self._text("A"), json.dumps(ours), json.dumps(theirs))

    def test_a_probe_retired_on_one_side_and_changed_on_the_other_is_refused(self, rm):
        theirs = json.loads(self._text("A", "B"))
        theirs["probes"][0]["open_value"] = "changed"
        with pytest.raises(rm.Unresolvable, match="changed on one side and retired on the other"):
            rm.resolve_probes(self._text("A", "B"), self._text("B"), json.dumps(theirs))

    def test_the_serializer_is_the_ledger_verbs_spelling_and_ours_key_order_is_kept(self, rm):
        """`ledger_row.py::_commit_both` writes the roster with one json.dumps
        call; the resolver restates it, so the two spellings are pinned equal
        in source, and the key order is ours' (the live file keeps `_note`
        after `probes`), so the bytes differ from ours only where a value did."""
        spelling = 'indent=1, ensure_ascii=False) + "\\n"'
        for path in (REPO_ROOT / "tools" / "cc" / "ledger_row.py", MODULE):
            assert spelling in path.read_text(encoding="utf-8"), path
        ours = {"_README": "r", "_generated": "g", "_count": 1, "probes": _probes_doc("A")["probes"], "_note": "n"}
        theirs = {**ours, "probes": _probes_doc("A", "B")["probes"], "_count": 2}
        base = ours
        out = rm.resolve_probes(json.dumps(base), json.dumps(ours), json.dumps(theirs))
        assert list(json.loads(out)) == ["_README", "_generated", "probes", "_note"]
        assert out == json.dumps(json.loads(out), indent=1, ensure_ascii=False) + "\n"
        assert out.endswith("\n") and "\r" not in out

    def test_a_top_level_key_ours_removed_stays_removed(self, rm):
        base = json.loads(self._text("A", _note="keep me"))
        ours = {k: v for k, v in base.items() if k != "_note"}
        out = json.loads(rm.resolve_probes(json.dumps(base), json.dumps(ours), json.dumps(base)))
        assert "_note" not in out
        theirs = {k: v for k, v in base.items() if k != "_note"}
        out = json.loads(rm.resolve_probes(json.dumps(base), json.dumps(base), json.dumps(theirs)))
        assert "_note" not in out

    def test_an_annotation_changed_on_both_sides_keeps_ours(self, rm):
        out = json.loads(rm.resolve_probes(self._text("A", _generated="base"), self._text("A", _generated="ours"),
                                           self._text("A", _generated="theirs")))
        assert out["_generated"] == "ours"

    def test_a_side_that_is_not_json_is_refused_by_name(self, rm):
        with pytest.raises(rm.Unresolvable, match=r"LEDGER_PROBES\.json \(theirs\) is not JSON"):
            rm.resolve_probes(self._text("A"), self._text("A"), "{not json")


class _Fake:
    """argv-prefix -> answer; every call recorded; an undescribed spawn fails."""

    def __init__(self, answers: dict[tuple[str, ...], tuple[int, str, str]]):
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kw):
        argv = list(argv)
        self.calls.append(argv)
        best = None
        for key in self.answers:
            if tuple(argv[: len(key)]) == key and (best is None or len(key) > len(best)):
                best = key
        if best is None:
            raise AssertionError("unplanned spawn: " + " ".join(argv))
        return self.answers[best]

    def has(self, *prefix: str) -> bool:
        return any(tuple(c[: len(prefix)]) == prefix for c in self.calls)


class TestProbeConflicts:
    def test_a_clean_merge_tree_is_an_empty_list(self, rm, tmp_path):
        fake = _Fake({("git", "merge-tree"): (0, "abc123\n", "")})
        assert rm.probe_conflicts(tmp_path, "origin/main", run=fake) == []

    def test_a_conflicting_merge_tree_names_the_paths_before_the_blank_line(self, rm, tmp_path):
        out = "abc123\nESPALIER_MEMORY.md\ntask-packs/FORWARD_LEDGER.md\n\nAuto-merging x\nCONFLICT (content)\n"
        fake = _Fake({("git", "merge-tree"): (1, out, "")})
        assert rm.probe_conflicts(tmp_path, "origin/main", run=fake) == ["ESPALIER_MEMORY.md",
                                                                          "task-packs/FORWARD_LEDGER.md"]

    def test_a_git_without_write_tree_cannot_probe(self, rm, tmp_path):
        fake = _Fake({("git", "merge-tree"): (129, "", "error: unknown option `write-tree'")})
        assert rm.probe_conflicts(tmp_path, "origin/main", run=fake) is None

    def test_a_ref_git_cannot_merge_is_cannot_say_never_clean(self, rm, tmp_path):
        """`merge-tree` exits 1 for "not something we can merge" too, with
        nothing on stdout (code review, driven): an absent origin/<base> must
        not read as a clean merge."""
        fake = _Fake({("git", "merge-tree"): (1, "", "merge-tree: not-a-ref - not something we can merge")})
        assert rm.probe_conflicts(tmp_path, "not-a-ref", run=fake) is None


class TestAttributeMergedPaths:
    def _fake(self, ours: str, theirs: str, attrs: str) -> _Fake:
        return _Fake({
            ("git", "diff", "--name-only", "origin/main...HEAD"): (0, ours, ""),
            ("git", "diff", "--name-only", "HEAD...origin/main"): (0, theirs, ""),
            ("git", "check-attr", "merge", "--"): (0, attrs, ""),
        })

    def test_a_path_changed_on_both_sides_with_a_merge_attribute_is_named(self, rm, tmp_path):
        fake = self._fake("CHANGELOG.md\nREADME.md\n", "CHANGELOG.md\ndocs/x.md\n",
                          "CHANGELOG.md: merge: union\n")
        assert rm.attribute_merged_paths(tmp_path, "origin/main", run=fake) == ["CHANGELOG.md"]
        assert fake.calls[-1] == ["git", "check-attr", "merge", "--", "CHANGELOG.md"]

    def test_a_path_without_the_attribute_or_changed_on_one_side_is_not(self, rm, tmp_path):
        fake = self._fake("CHANGELOG.md\n", "CHANGELOG.md\n", "CHANGELOG.md: merge: unspecified\n")
        assert rm.attribute_merged_paths(tmp_path, "origin/main", run=fake) == []
        fake = self._fake("CHANGELOG.md\n", "README.md\n", "")
        assert rm.attribute_merged_paths(tmp_path, "origin/main", run=fake) == []
        assert not fake.has("git", "check-attr")


class TestMergeRefInRefusals:
    def _base(self, root: Path, *, dirty: str = "", ahead: str = "1\n", merging: bool = False) -> dict:
        return {
            ("git", "rev-parse", "-q", "--verify", "MERGE_HEAD"): (0 if merging else 1, "", ""),
            ("git", "status", "--porcelain", "-uno"): (0, dirty, ""),
            ("git", "rev-list", "--count"): (0, ahead, ""),
            ("git", "merge", "--abort"): (0, "", ""),
        }

    def test_a_merge_already_in_progress_is_refused_naming_abort_not_commit(self, rm, tmp_path):
        """Failure-mode review, driven: a half-merged tree read as "dirty" and
        the message said to commit, which would commit the conflict markers."""
        fake = _Fake(self._base(tmp_path, dirty="UU ESPALIER_MEMORY.md\n", merging=True))
        with pytest.raises(rm.Unresolvable, match=r"already in progress.*git merge --abort"):
            rm.merge_ref_in(tmp_path, "origin/main", run=fake)
        assert not fake.has("git", "merge")

    def test_a_dirty_tree_is_refused_before_any_merge(self, rm, tmp_path):
        fake = _Fake(self._base(tmp_path, dirty=" M a.py\n"))
        with pytest.raises(rm.Unresolvable, match="dirty"):
            rm.merge_ref_in(tmp_path, "origin/main", run=fake)
        assert not fake.has("git", "merge")

    def test_nothing_to_merge_is_a_report_not_a_merge(self, rm, tmp_path):
        fake = _Fake(self._base(tmp_path, ahead="0\n"))
        report = rm.merge_ref_in(tmp_path, "origin/main", run=fake)
        assert report.merged is False and "nothing to merge" in report.notes[0]
        assert not fake.has("git", "merge")

    def test_a_fragment_written_twice_under_one_name_is_refused_by_name(self, rm, tmp_path):
        """TP-479 Wave C: a fragment directory is on the roster (so the marker
        scans read it) but is never resolved by shape: a conflict there is two
        writers on one name, refused before any git call. Mutation seen red:
        the fragment passed to the shape resolvers. TP-479a 0-E: two lanes
        striking or re-pinning one ledger row (or its probe) meet on that row's
        own file, and the refusal names it."""
        fake = _Fake({})
        for path in ("changelog.d/2026-10-10-x.md", "memory/session-log.d/2026-10-10-120000-win.md",
                     "task-packs/ledger.d/DEF-9.md", "task-packs/probes.d/DEF-9.json"):
            with pytest.raises(rm.Unresolvable, match=r"one writer per name.*two writers on one name: " + path):
                rm._resolve_unmerged(tmp_path, "origin/main", [path], run=fake, say=lambda _s: None)
        assert fake.calls == []

    def test_the_roster_reads_fragments_by_directory(self, rm):
        assert rm.on_roster("memory/session-log.d/2026-10-10-120000-win.md")
        assert rm.on_roster("changelog.d\\2026-10-10-x.md") and rm.is_fragment("changelog.d/2026-10-10-x.md")
        assert rm.on_roster("ESPALIER_MEMORY.md") and not rm.is_fragment("ESPALIER_MEMORY.md")
        assert not rm.on_roster("memory/session-log.d/") and not rm.on_roster("docs/NOTES.md")

    @pytest.mark.parametrize("path", [
        "changelog.d/20261010_120000_someone.md",   # scriv's default name
        "changelog.d/123.feature.md",                # towncrier's
        "changelog.d/sub/2026-10-10-x.md",           # nested: no reader takes it
        "memory/session-log.d/README.md",
    ])
    def test_another_tools_file_in_a_fragment_directory_is_off_the_roster(self, rm, tmp_path, path):
        """Review of #179: the roster matched a fragment directory by prefix,
        so an adopter's own scriv or towncrier entry conflicting in a catch-up
        was refused as two writers on one name. It is the hand's conflict, and
        the refusal says so. Mutation seen red: the prefix match alone."""
        assert not rm.is_fragment(path) and not rm.on_roster(path)
        with pytest.raises(rm.Unresolvable, match=r"outside the record files"):
            rm._resolve_unmerged(tmp_path, "origin/main", [path], run=_Fake({}), say=lambda _s: None)

    def test_a_clean_merge_commits_and_resolves_nothing(self, rm, tmp_path):
        fake = _Fake({**self._base(tmp_path), ("git", "merge", "--no-edit"): (0, "Merge made\n", "")})
        report = rm.merge_ref_in(tmp_path, "origin/main", run=fake)
        assert report.merged is True and report.resolved == []

    def _stale_roster(self, root: Path, *ids: str, count: int | None) -> Path:
        """A roster storing ``count`` (a lane branched before 2026-10-12), or
        today's shape with ``None``."""
        doc = _probes_doc(*ids)
        if count is not None:
            doc["_count"] = count
        (root / "task-packs").mkdir(exist_ok=True)
        p = root / "task-packs" / "LEDGER_PROBES.json"
        p.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        return p

    @pytest.mark.parametrize("count", [None, 5])
    def test_a_clean_merge_spawns_nothing_after_gits_own_merge(self, rm, tmp_path, count):
        """The settle step that dropped a stored probes total after a clean
        merge retired with the fold (TP-479a Wave C): no writer has written the
        key since 2026-10-12, and a roster that still stores one is left as git
        merged it, for the checker to name. Dies to: the settle step restored."""
        p = self._stale_roster(tmp_path, "DEF-1", count=count)
        before = p.read_bytes()
        fake = _Fake({**self._base(tmp_path), ("git", "merge", "--no-edit"): (0, "Merge made\n", "")})
        report = rm.merge_ref_in(tmp_path, "origin/main", run=fake)
        assert report.resolved == [] and not fake.has("git", "commit") and not fake.has("git", "add")
        assert p.read_bytes() == before

    def test_a_conflict_off_the_roster_aborts_and_names_the_path(self, rm, tmp_path):
        fake = _Fake({**self._base(tmp_path),
                      ("git", "merge", "--no-edit"): (1, "CONFLICT", "Automatic merge failed"),
                      ("git", "diff", "--name-only", "--diff-filter=U"): (0, "ESPALIER_MEMORY.md\nREADME.md\n", "")})
        said: list[str] = []
        with pytest.raises(rm.Unresolvable, match=r"outside the record files: README\.md"):
            rm.merge_ref_in(tmp_path, "origin/main", run=fake, say=said.append)
        assert fake.has("git", "merge", "--abort")

    # The marker-taxonomy gate reads an `ls-files ... .md` line as a tree-wide
    # doc sweep; this fixture only feeds a fake runner a stage listing, but the
    # gate's remedy is the marker and the slice cost is nil, so it is in.
    @pytest.mark.contract
    def test_an_add_add_or_delete_modify_on_a_roster_file_aborts_by_name(self, rm, tmp_path):
        fake = _Fake({**self._base(tmp_path),
                      ("git", "merge", "--no-edit"): (1, "CONFLICT", ""),
                      ("git", "diff", "--name-only", "--diff-filter=U"): (0, "ESPALIER_MEMORY.md\n", ""),
                      ("git", "ls-files", "-u"): (0, "100644 aaaa 2\tESPALIER_MEMORY.md\n100644 bbbb 3\tESPALIER_MEMORY.md\n", "")})
        with pytest.raises(rm.Unresolvable, match="not a content conflict"):
            rm.merge_ref_in(tmp_path, "origin/main", run=fake)
        assert fake.has("git", "merge", "--abort")

    def test_a_merge_that_fails_without_conflicts_aborts_and_quotes_git(self, rm, tmp_path):
        fake = _Fake({**self._base(tmp_path),
                      ("git", "merge", "--no-edit"): (128, "", "fatal: refusing to merge unrelated histories"),
                      ("git", "diff", "--name-only", "--diff-filter=U"): (0, "", "")})
        with pytest.raises(rm.Unresolvable, match="unrelated histories"):
            rm.merge_ref_in(tmp_path, "origin/main", run=fake)
        assert fake.has("git", "merge", "--abort")


# ── real git: two machines ───────────────────────────────────────────────────

def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=_git_env(), check=check, timeout=45)


def _identity(repo: Path, name: str) -> None:
    _git(repo, "config", "user.name", name)
    _git(repo, "config", "user.email", f"{name}@example.invalid")
    _git(repo, "config", "commit.gpgsign", "false")


CAP = 14


def _memory(rows: list[str]) -> str:
    """A memory file of exactly CAP lines when len(rows) == CAP - 8."""
    head = ("# Project Memory\n\n## Session Log\n\n"
            f"**Pruning policy:** Bounded at {CAP} lines.\n\n"
            "| Date | What Happened | Notes |\n|------|--------------|-------|\n")
    return head + "\n".join(rows) + "\n"


def _seed_rows() -> list[str]:
    return [_row(f"2026-09-{d:02d}", f"SESSION {d}") for d in range(24, 18, -1)]  # six rows, 24 newest


def _ledger_with(*ids: str, stored: frozenset[str] = frozenset()) -> str:
    """The ledger a verb leaves with ``ids`` filed; ``stored=STORED_ALL`` is the
    one a verb from before the counts left wrote, its totals counting them."""
    rows = tuple(_member(i) for i in ids)
    appendix = tuple(_index(i) for i in ids)
    return _ledger(c1_rows=rows, appendix=appendix, stored=stored, count=len(ids))


def _write_probes(repo: Path, *ids: str) -> None:
    (repo / "task-packs" / "LEDGER_PROBES.json").write_text(
        json.dumps(_probes_doc(*ids), indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


@pytest.fixture
def two_machines(tmp_path):
    """A bare origin and two clones, each with a committed memory file at its
    cap and a two-row ledger with its probes. The clones stand in for the two
    machines; the test is what each handoff writes."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "--quiet", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "--quiet", str(origin), str(seed))
    _identity(seed, "seed")
    (seed / "ESPALIER_MEMORY.md").write_text(_memory(_seed_rows()), encoding="utf-8", newline="\n")
    assert len((seed / "ESPALIER_MEMORY.md").read_text(encoding="utf-8").splitlines()) == CAP
    (seed / "task-packs").mkdir()
    (seed / "task-packs" / "FORWARD_LEDGER.md").write_text(_ledger_with("DEF-1", "DEF-2"), encoding="utf-8", newline="\n")
    _write_probes(seed, "DEF-1", "DEF-2")
    (seed / ".gitignore").write_text("docs/session-archive.md\n*.lock\n", encoding="utf-8")
    # As this repository does: changelog.d/ is this changelog's only where opted in.
    (seed / "espalier.toml").write_text("changelog_fragments = true\n", encoding="utf-8", newline="\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "--quiet", "-m", "seed")
    _git(seed, "push", "--quiet", "-u", "origin", "main")
    clones = {}
    for name in ("mac", "win"):
        clone = tmp_path / name
        _git(tmp_path, "clone", "--quiet", str(origin), str(clone))
        _identity(clone, name)
        clones[name] = clone
    return clones


def _handoff(repo: Path, headline: str, day: str) -> str:
    """What /handoff does to the memory file: prepend a row, evict the oldest
    so the file stays at its cap, commit."""
    path = repo / "ESPALIER_MEMORY.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    sep = next(i for i, ln in enumerate(lines) if ln.startswith("|---"))
    row = _row(day, headline)
    lines.insert(sep + 1, row)
    del lines[-1]  # the oldest row sits at the bottom
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    _git(repo, "commit", "--quiet", "-am", f"docs(memory): {headline}")
    return row


def _file_rows(repo: Path, *ids: str, stored: frozenset[str] = frozenset()) -> None:
    """What the ledger verb does: the rows into the first slot, the index rows,
    the probes appended (and, before the counts left, the totals rewritten)."""
    (repo / "task-packs" / "FORWARD_LEDGER.md").write_text(_ledger_with(*ids, stored=stored),
                                                           encoding="utf-8", newline="\n")
    _write_probes(repo, *ids)
    _git(repo, "commit", "--quiet", "-am", f"ledger: file {', '.join(ids)}")


def _real_run(rm):
    def run(argv, **kw):
        kw.setdefault("env", _git_env())
        return rm.run(argv, **kw)
    return run


class TestTwoMachines:
    def test_two_handoffs_between_syncs_keep_both_rows_and_the_cap(self, rm, two_machines):
        mac, win = two_machines["mac"], two_machines["win"]
        mac_row = _handoff(mac, "THE MAC LANDED A LANE", "2026-10-05")
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "switch", "--quiet", "-c", "lane/win")
        win_row = _handoff(win, "THE WINDOWS BOX LANDED A LANE", "2026-10-05")
        _git(win, "fetch", "--quiet", "origin")
        assert _git(win, "merge-tree", "--write-tree", "origin/main", "HEAD", check=False).returncode == 1

        said: list[str] = []
        report = rm.merge_ref_in(win, "origin/main", run=_real_run(rm), say=said.append)

        assert report.merged and report.resolved == ["ESPALIER_MEMORY.md"], report
        text = (win / "ESPALIER_MEMORY.md").read_text(encoding="utf-8")
        lines = text.splitlines()
        assert mac_row in lines and win_row in lines
        assert lines.index(win_row) < lines.index(mac_row)  # ours (the lane) first, then theirs
        assert len(lines) == CAP, "\n".join(lines)
        assert "SESSION 19" not in text and "SESSION 20" not in text  # evicted by the handoffs and the cap step
        archive = (win / "docs" / "session-archive.md").read_text(encoding="utf-8")
        assert "SESSION 20" in archive  # the cap step's eviction, archived on this machine
        assert said == [], said
        assert _git(win, "status", "--porcelain").stdout == ""
        assert _git(win, "log", "--merges", "--oneline").stdout.count("\n") == 1
        assert "1 session row(s)" not in report.notes[-1] and "2 session row(s)" in report.notes[-1]

    def test_two_filings_into_one_slot_keep_every_row_and_store_no_total(self, rm, gen, two_machines):
        mac, win = two_machines["mac"], two_machines["win"]
        _file_rows(mac, "DEF-3", "DEF-1", "DEF-2")
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "switch", "--quiet", "-c", "lane/win")
        _file_rows(win, "DEF-5", "DEF-4", "DEF-1", "DEF-2")
        _git(win, "fetch", "--quiet", "origin")

        report = rm.merge_ref_in(win, "origin/main", run=_real_run(rm))

        assert report.merged and set(report.resolved) == {"task-packs/FORWARD_LEDGER.md", "task-packs/LEDGER_PROBES.json"}
        ledger = (win / "task-packs" / "FORWARD_LEDGER.md").read_text(encoding="utf-8")
        for rid in ("DEF-1", "DEF-2", "DEF-3", "DEF-4", "DEF-5"):
            assert _member(rid) in ledger and _index(rid) in ledger, rid
        assert gen.stored_counts(ledger) == [] and gen.derive(ledger)["live_total"] == 5
        gen._PROBES = win / "task-packs" / "LEDGER_PROBES.json"
        assert gen.find_drift(ledger) == []
        probes = json.loads((win / "task-packs" / "LEDGER_PROBES.json").read_text(encoding="utf-8"))
        assert "_count" not in probes and sorted(p["id"] for p in probes["probes"]) == ["DEF-1", "DEF-2", "DEF-3", "DEF-4", "DEF-5"]
        assert _git(win, "status", "--porcelain").stdout == ""
        assert not (win / "task-packs" / "FORWARD_LEDGER.md.lock").exists()

    @pytest.mark.parametrize("main_stored, lane_stored", [(STORED_ALL, frozenset()), (frozenset(), STORED_ALL)],
                             ids=["lane-after-the-counts-left", "lane-before-them"])
    def test_a_filing_from_before_the_counts_left_merges_with_one_from_after(
        self, rm, gen, two_machines, monkeypatch, main_stored, lane_stored
    ):
        """The transition: both machines start from the file with its totals;
        one files rows the old way (every total rewritten), the other the new
        way (the totals gone). Every total line conflicts, and every one is the
        generator's, so the merge resolves by shape and leaves no total stored."""
        mac, win = two_machines["mac"], two_machines["win"]
        _file_rows(mac, "DEF-1", "DEF-2", stored=STORED_ALL)
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "pull", "--quiet", "--ff-only", "origin", "main")
        _file_rows(mac, "DEF-3", "DEF-1", "DEF-2", stored=main_stored)
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "switch", "--quiet", "-c", "lane/win")
        _file_rows(win, "DEF-5", "DEF-4", "DEF-1", "DEF-2", stored=lane_stored)
        _git(win, "fetch", "--quiet", "origin")

        report = rm.merge_ref_in(win, "origin/main", run=_real_run(rm))

        assert report.merged and "task-packs/FORWARD_LEDGER.md" in report.resolved, report
        ledger = (win / "task-packs" / "FORWARD_LEDGER.md").read_text(encoding="utf-8")
        for rid in ("DEF-1", "DEF-2", "DEF-3", "DEF-4", "DEF-5"):
            assert _member(rid) in ledger and _index(rid) in ledger, rid
        assert gen.stored_counts(ledger) == [], ledger
        monkeypatch.setattr(gen, "_PROBES", win / "task-packs" / "LEDGER_PROBES.json")
        assert gen.find_drift(ledger) == []
        assert _git(win, "status", "--porcelain").stdout == ""

    def test_the_same_id_filed_on_both_machines_is_refused_and_the_tree_is_left_clean(self, rm, two_machines):
        mac, win = two_machines["mac"], two_machines["win"]
        _file_rows(mac, "DEF-3", "DEF-1", "DEF-2")
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "switch", "--quiet", "-c", "lane/win")
        (win / "task-packs" / "FORWARD_LEDGER.md").write_text(
            _ledger_with("DEF-3", "DEF-1", "DEF-2").replace(_member("DEF-3"), _member("DEF-3", "a different defect")),
            encoding="utf-8", newline="\n")
        _write_probes(win, "DEF-3", "DEF-1", "DEF-2")
        _git(win, "commit", "--quiet", "-am", "ledger: file DEF-3 again")
        _git(win, "fetch", "--quiet", "origin")
        before = _git(win, "rev-parse", "HEAD").stdout

        with pytest.raises(rm.Unresolvable, match="DEF-3 was filed on both sides"):
            rm.merge_ref_in(win, "origin/main", run=_real_run(rm))

        assert _git(win, "rev-parse", "HEAD").stdout == before
        assert _git(win, "status", "--porcelain").stdout == ""
        assert not (win / ".git" / "MERGE_HEAD").exists()

    def test_a_conflict_in_a_file_off_the_roster_is_refused_with_the_tree_left_clean(self, rm, two_machines):
        mac, win = two_machines["mac"], two_machines["win"]
        (mac / "README.md").write_text("mac\n", encoding="utf-8")
        _git(mac, "add", "README.md")
        _git(mac, "commit", "--quiet", "-m", "readme")
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "switch", "--quiet", "-c", "lane/win")
        (win / "README.md").write_text("win\n", encoding="utf-8")
        _git(win, "add", "README.md")
        _git(win, "commit", "--quiet", "-m", "readme")
        _handoff(win, "A ROW TOO", "2026-10-05")
        _git(win, "fetch", "--quiet", "origin")
        with pytest.raises(rm.Unresolvable, match=r"outside the record files: README\.md"):
            rm.merge_ref_in(win, "origin/main", run=_real_run(rm))
        assert _git(win, "status", "--porcelain").stdout == ""

    def test_a_probes_only_collision_merges_under_the_ledger_lock(self, rm, two_machines):
        mac, win = two_machines["mac"], two_machines["win"]
        _write_probes(mac, "DEF-1", "DEF-2", "DEF-9")
        _git(mac, "commit", "--quiet", "-am", "probes: DEF-9")
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "switch", "--quiet", "-c", "lane/win")
        _write_probes(win, "DEF-1", "DEF-2", "DEF-8")
        _git(win, "commit", "--quiet", "-am", "probes: DEF-8")
        _git(win, "fetch", "--quiet", "origin")
        report = rm.merge_ref_in(win, "origin/main", run=_real_run(rm))
        assert report.merged and report.resolved == ["task-packs/LEDGER_PROBES.json"]
        probes = json.loads((win / "task-packs" / "LEDGER_PROBES.json").read_text(encoding="utf-8"))
        assert "_count" not in probes and [p["id"] for p in probes["probes"]] == ["DEF-1", "DEF-2", "DEF-8", "DEF-9"]
        assert not (win / "task-packs" / "FORWARD_LEDGER.md.lock").exists()
        assert _git(win, "status", "--porcelain").stdout == ""

    def _bring_back_a_stored_count(self, repo: Path, count: int) -> None:
        """What a lane branched before 2026-10-12 brings: its verbs wrote the
        key (here a stale one, the 2026-10-05 hand-merge shape). Written with
        the verbs' serializer so only the key differs."""
        p = repo / "task-packs" / "LEDGER_PROBES.json"
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["_count"] = count
        p.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    def test_a_stored_count_beside_a_memory_conflict_is_left_as_git_merged_it(self, rm, two_machines):
        """The conflicted path: the memory rows collide and the roster merges
        clean with a stored count. The settle step that dropped it here retired
        with the fold (TP-479a Wave C), so the memory file is the one thing
        resolved and the roster keeps main's bytes. Dies to: the settle step
        restored in the unmerged path."""
        mac, win = two_machines["mac"], two_machines["win"]
        _file_rows(mac, "DEF-3", "DEF-1", "DEF-2")
        self._bring_back_a_stored_count(mac, 2)
        _git(mac, "commit", "--quiet", "-am", "ledger: a hand merge left the count behind")
        _handoff(mac, "THE MAC LANDED A LANE", "2026-10-05")
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "switch", "--quiet", "-c", "lane/win")
        _handoff(win, "THE WINDOWS BOX LANDED A LANE", "2026-10-05")
        _git(win, "fetch", "--quiet", "origin")

        report = rm.merge_ref_in(win, "origin/main", run=_real_run(rm))

        assert report.resolved == ["ESPALIER_MEMORY.md"], report
        main_roster = _git(win, "show", "origin/main:task-packs/LEDGER_PROBES.json").stdout
        assert _git(win, "show", "HEAD:task-packs/LEDGER_PROBES.json").stdout == main_roster
        assert _git(win, "log", "--merges", "--oneline").stdout.count("\n") == 1
        assert _git(win, "status", "--porcelain").stdout == ""

    def test_a_path_with_a_merge_attribute_changed_on_both_sides_is_merged_first_not_read_clean(self, rm, two_machines):
        """`git merge-tree` honours a union attribute (code review, driven on
        git 2.39) while GitHub does not: a lane whose only collision is such a
        path probes clean and would be born CONFLICTING, so the attribute walk
        names it and the local merge unions it."""
        mac, win = two_machines["mac"], two_machines["win"]
        (mac / ".gitattributes").write_text("CHANGELOG.md merge=union\n", encoding="utf-8")
        (mac / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n- base bullet\n", encoding="utf-8")
        _git(mac, "add", "-A")
        _git(mac, "commit", "--quiet", "-m", "changelog")
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "pull", "--quiet", "--ff-only", "origin", "main")   # both clones now share the base
        assert (win / ".gitattributes").is_file()
        (mac / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n- mac bullet\n- base bullet\n", encoding="utf-8")
        _git(mac, "commit", "--quiet", "-am", "mac bullet")
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "switch", "--quiet", "-c", "lane/win")
        (win / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n- win bullet\n- base bullet\n", encoding="utf-8")
        _git(win, "commit", "--quiet", "-am", "win bullet")
        _git(win, "fetch", "--quiet", "origin")
        run = _real_run(rm)
        assert rm.probe_conflicts(win, "origin/main", run=run) == []   # the probe honours the attribute
        assert rm.attribute_merged_paths(win, "origin/main", run=run) == ["CHANGELOG.md"]
        report = rm.merge_ref_in(win, "origin/main", run=run)
        assert report.merged and report.resolved == []
        text = (win / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "- mac bullet" in text and "- win bullet" in text and text.count("- base bullet") == 1

    def test_a_merge_already_in_progress_is_refused_and_left_for_the_operator(self, rm, two_machines):
        mac, win = two_machines["mac"], two_machines["win"]
        _handoff(mac, "A MAC ROW", "2026-10-05")
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "switch", "--quiet", "-c", "lane/win")
        _handoff(win, "A WIN ROW", "2026-10-05")
        _git(win, "fetch", "--quiet", "origin")
        assert _git(win, "merge", "origin/main", check=False).returncode == 1   # the hand merge, conflicted
        try:
            with pytest.raises(rm.Unresolvable, match="already in progress"):
                rm.merge_ref_in(win, "origin/main", run=_real_run(rm))
            assert (win / ".git" / "MERGE_HEAD").exists(), "the operator's merge is theirs to finish or abort"
        finally:
            _git(win, "merge", "--abort")

    def test_the_probe_names_the_conflicts_without_touching_the_tree(self, rm, two_machines):
        mac, win = two_machines["mac"], two_machines["win"]
        _handoff(mac, "A MAC ROW", "2026-10-05")
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "switch", "--quiet", "-c", "lane/win")
        _handoff(win, "A WIN ROW", "2026-10-05")
        _git(win, "fetch", "--quiet", "origin")
        before = _git(win, "rev-parse", "HEAD").stdout
        assert rm.probe_conflicts(win, "origin/main", run=_real_run(rm)) == ["ESPALIER_MEMORY.md"]
        assert _git(win, "rev-parse", "HEAD").stdout == before
        assert _git(win, "status", "--porcelain").stdout == ""


# ── real git: /ship's record-finish line, as the body spells it ──────────────

SHIP_BODY = REPO_ROOT / ".claude" / "commands" / "ship.md"


def _ship_finish_code() -> str:
    """The code of the one ``python -c`` line ship.md hands a session whose
    catch-up conflicts on a hand file and a record file, split as a POSIX shell
    splits it: the instruction itself is what runs, never a retyped copy."""
    import shlex

    lines = [ln.strip() for ln in SHIP_BODY.read_text(encoding="utf-8").splitlines()
             if ln.strip().startswith("python -c ") and "record_merge" in ln]
    assert len(lines) == 1, f"ship.md should carry exactly one record-finish line, found {len(lines)}: {lines}"
    argv = shlex.split(lines[0])
    assert argv[:2] == ["python", "-c"] and len(argv) == 3, argv
    return argv[2]


_RECIPE = re.compile(r"`git update-index --unresolve[^`]*`")


def _recovery_argv(path: str) -> list[str]:
    """The argv of the one recovery line ship.md prints for a record file staged
    with its markers, with ``<path>`` filled in: the body's own spelling is what
    the drive runs, never a retyped copy (the retyped copy is how the dashed
    spelling stayed in the test after the body changed, and how the two could
    drift apart again)."""
    import shlex

    recipes = _RECIPE.findall(SHIP_BODY.read_text(encoding="utf-8"))
    assert len(recipes) == 1, recipes
    argv = shlex.split(recipes[0].strip("`").replace("<path>", path))
    assert argv[0] == "git", argv
    return argv[1:]


def _hand_plus_record(rm, two_machines, *, roster: bool) -> tuple[Path, str, str]:
    """A lane and its base that conflict on a hand file (``README.md``, added
    on both sides) and one record file (two handoffs into the memory file),
    with ``merge origin/main`` left in progress, this checkout's ``tools/cc``
    beside it as the line's import expects. ``roster=False`` is this tree
    since the 2026-10-14 fold: no probes roster file on either side."""
    mac, win = two_machines["mac"], two_machines["win"]
    if not roster:
        _git(mac, "rm", "--quiet", "task-packs/LEDGER_PROBES.json")
        _git(mac, "commit", "--quiet", "-m", "the fold: the roster becomes files")
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "pull", "--quiet", "--ff-only", "origin", "main")
    _git(win, "switch", "--quiet", "-c", "lane/win")
    for repo, side in ((mac, "mac"), (win, "win")):
        (repo / "README.md").write_bytes(f"{side}\n".encode("utf-8"))
        _git(repo, "add", "README.md")
        _git(repo, "commit", "--quiet", "-m", f"readme on {side}")
    mac_row = _handoff(mac, "THE MAC LANDED A LANE", "2026-10-05")
    _git(mac, "push", "--quiet", "origin", "main")
    win_row = _handoff(win, "THE WINDOWS BOX LANDED A LANE", "2026-10-05")
    _git(win, "fetch", "--quiet", "origin")
    # The body's precondition: catch-up refuses the hand file by name.
    with pytest.raises(rm.Unresolvable, match=r"outside the record files: README\.md"):
        rm.merge_ref_in(win, "origin/main", run=_real_run(rm))
    assert _begin_merge(win) == ["ESPALIER_MEMORY.md", "README.md"]
    return win, mac_row, win_row


def _begin_merge(win: Path) -> list[str]:
    """``git merge origin/main`` left in progress, this checkout's ``tools/cc``
    beside it (the line's import is relative to the checkout it runs in, and
    the copy is excluded so status stays strict); the paths git left unmerged."""
    copy_checkout(REPO_ROOT / "tools" / "cc", win / "tools" / "cc", ignore=shutil.ignore_patterns("__pycache__"))
    with (win / ".git" / "info" / "exclude").open("a", encoding="utf-8") as fh:
        fh.write("tools/\n")
    assert _git(win, "merge", "origin/main", check=False).returncode == 1
    return sorted(_git(win, "diff", "--name-only", "--diff-filter=U").stdout.split())


def _set_heading(repo: Path, heading: str) -> None:
    """Edit the memory file's prose (its first line), outside every row."""
    path = repo / "ESPALIER_MEMORY.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = heading
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    _git(repo, "commit", "--quiet", "-am", f"memory prose: {heading}")


def _no_markers(repo: Path, *rels: str) -> bool:
    return not any(ln.startswith(("<<<<<<<", ">>>>>>>")) for rel in rels
                   for ln in _git(repo, "show", f"HEAD:{rel}").stdout.splitlines())


def _run_finish_line(repo: Path) -> subprocess.CompletedProcess:
    code = _ship_finish_code().replace("<base>", "main")
    return subprocess.run([sys.executable, "-c", code], cwd=repo, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=_git_env(), timeout=45)


@pytest.mark.contract
class TestTheShipBodysRecordFinish:
    """/ship's Step 3, a catch-up that conflicts on a hand file and a record
    file: resolve the hand file, ``git add`` it, and the body's one line lets
    the record resolver conclude the merge with the hand resolution in it.

    Red earned on 7afe323: the line listed ``[rm.MEMORY, rm.LEDGER,
    rm.PROBES]`` whatever conflicted, and ``_resolve_unmerged`` refuses a
    listed path that is not a content conflict, so with the memory file the
    only record conflict it raised ``task-packs/FORWARD_LEDGER.md: not a
    content conflict`` before it reached the roster the fold deleted -- and
    the body's next step, ``git merge --abort``, threw the staged hand
    resolution away (DEF-4018). Contract-marked: a later edit to ship.md
    alone earns the contract slice, which must still run the line."""

    def test_the_line_is_one_argument_in_posix_shells_and_powershell(self):
        code = _ship_finish_code()
        # PowerShell 5.1 re-splits a native argument at an embedded double quote,
        # $ and a backtick expand inside double quotes, a POSIX double quote eats
        # a backslash, and ! is bash history expansion.
        assert not [ch for ch in '"$`\\!' if ch in code], code
        assert code.count("<base>") == 1, code

    @pytest.mark.parametrize("roster", [False, True], ids=["roster-folded", "roster-kept"])
    def test_a_staged_hand_resolution_rides_the_merge_the_line_concludes(self, rm, two_machines, roster):
        win, mac_row, win_row = _hand_plus_record(rm, two_machines, roster=roster)
        (win / "README.md").write_bytes(b"mac\nwin\n")
        _git(win, "add", "README.md")

        proc = _run_finish_line(win)

        assert proc.returncode == 0, proc.stderr[-800:]
        assert not (win / ".git" / "MERGE_HEAD").exists()
        assert _git(win, "rev-parse", "HEAD^2").stdout == _git(win, "rev-parse", "origin/main").stdout
        assert _git(win, "show", "HEAD:README.md").stdout == "mac\nwin\n"  # the hand resolution kept
        memory = _git(win, "show", "HEAD:ESPALIER_MEMORY.md").stdout.splitlines()
        assert mac_row in memory and win_row in memory
        assert not any(ln.startswith(("<<<<<<<", "=======", ">>>>>>>")) for ln in memory)
        assert _git(win, "status", "--porcelain").stdout == ""

    def test_an_unstaged_hand_file_is_refused_by_name_and_the_merge_kept(self, rm, two_machines):
        win, _mac_row, _win_row = _hand_plus_record(rm, two_machines, roster=False)

        proc = _run_finish_line(win)

        assert proc.returncode != 0 and "outside the record files: README.md" in proc.stderr, proc.stderr[-800:]
        assert (win / ".git" / "MERGE_HEAD").exists()
        assert sorted(_git(win, "diff", "--name-only", "--diff-filter=U").stdout.split()) == [
            "ESPALIER_MEMORY.md", "README.md"]
        # Settled by hand and staged, the same line then concludes it.
        (win / "README.md").write_bytes(b"mac\nwin\n")
        _git(win, "add", "README.md")
        assert _run_finish_line(win).returncode == 0
        assert not (win / ".git" / "MERGE_HEAD").exists()

    def test_the_body_prints_the_recovery_this_test_drives(self):
        """The staged-with-a-conflict-marker arm of ship.md's refusal recipe prints
        the one recovery line, and it is the spelling the test below drives: no
        ``--`` before the path. Apple Git 2.39.5 (the git Xcode ships) reads that
        separator as a path named ``--`` and exits 1 without unresolving anything,
        so the body's old ``git update-index --unresolve -- <path>`` failed every
        macOS operator who typed it while the test, red on every Air run, was
        explained by hand in 37 of 100 merged pull-request bodies (the ledger
        row that filed and struck the defect). This pin reds the moment the body
        and the test spell the recovery differently, on every host."""
        body = SHIP_BODY.read_text(encoding="utf-8")
        recipes = _RECIPE.findall(body)
        assert recipes == ["`git update-index --unresolve <path>`"], (
            f"ship.md must carry exactly one inline recovery recipe, spelled bare, found {recipes}: "
            "Apple Git 2.39.5 takes every word after --unresolve as a path, the -- separator included; "
            "the drive test reads its argv from this recipe, so change the two together"
        )
        assert not re.search(r"update-index\s+--unresolve\s+--\s", body), (
            "the separator is back somewhere in ship.md: Apple Git 2.39.5 reads it as a path and exits 1"
        )

    def test_the_refusal_names_each_path_separated_by_a_space(self):
        """The refusal lists the record files staged with their markers so the
        operator can paste them after ``--unresolve``; joined with a comma the
        paste fails the same way the separator did (``error: a.md,: not in our
        branch``, exit 1, nothing unresolved, driven on Apple Git 2.39.5), so
        the line joins them with spaces and this pins that it keeps doing so."""
        code = _ship_finish_code()
        assert "staged with a conflict marker: ' + ' '.join(m)" in code, code
        assert "', '.join(" not in code, code

    def test_a_record_file_staged_with_its_markers_is_refused_until_unresolved(self, rm, two_machines):
        """``git add -A`` after the hand file stages the memory file with its
        markers, so git no longer reports it unmerged: the line must refuse,
        not commit the markers (failure-mode review, driven)."""
        win, mac_row, win_row = _hand_plus_record(rm, two_machines, roster=False)
        head = _git(win, "rev-parse", "HEAD").stdout
        (win / "README.md").write_bytes(b"mac\nwin\n")
        _git(win, "add", "-A")

        proc = _run_finish_line(win)

        assert proc.returncode != 0 and "staged with a conflict marker: ESPALIER_MEMORY.md" in proc.stderr, \
            proc.stderr[-800:]
        assert (win / ".git" / "MERGE_HEAD").exists() and _git(win, "rev-parse", "HEAD").stdout == head
        _git(win, *_recovery_argv("ESPALIER_MEMORY.md"))  # the body's own recipe, read from ship.md
        assert _run_finish_line(win).returncode == 0
        memory = _git(win, "show", "HEAD:ESPALIER_MEMORY.md").stdout.splitlines()
        assert mac_row in memory and win_row in memory and _no_markers(win, "ESPALIER_MEMORY.md")
        assert _git(win, "show", "HEAD:README.md").stdout == "mac\nwin\n"

    def test_a_shape_refusal_after_a_rewrite_keeps_the_merge_and_the_next_run_concludes(self, rm, two_machines):
        """The resolver writes the roster and the ledger before it reads the
        memory file's prose conflict and refuses it. The merge, the staged hand
        file and the two rewritten files' conflicts must all survive, so the
        memory file merged by hand and staged alone lets the next run conclude
        with both lanes' rows (the body's third refusal kind)."""
        mac, win = two_machines["mac"], two_machines["win"]
        _git(win, "switch", "--quiet", "-c", "lane/win")
        for repo, side, ids in ((mac, "mac", ("DEF-1", "DEF-2", "DEF-3")), (win, "win", ("DEF-1", "DEF-2", "DEF-4"))):
            (repo / "README.md").write_bytes(f"{side}\n".encode("utf-8"))
            _git(repo, "add", "README.md")
            _git(repo, "commit", "--quiet", "-m", f"readme on {side}")
            _file_rows(repo, *ids)
            _set_heading(repo, f"# Project Memory ({side})")
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "fetch", "--quiet", "origin")
        assert _begin_merge(win) == ["ESPALIER_MEMORY.md", "README.md", "task-packs/FORWARD_LEDGER.md",
                                     "task-packs/LEDGER_PROBES.json"]
        (win / "README.md").write_bytes(b"mac\nwin\n")
        _git(win, "add", "README.md")

        proc = _run_finish_line(win)

        assert proc.returncode != 0 and "ESPALIER_MEMORY.md" in proc.stderr, proc.stderr[-800:]
        assert (win / ".git" / "MERGE_HEAD").exists()
        assert "README.md" in _git(win, "diff", "--cached", "--name-only").stdout.split()
        assert "task-packs/FORWARD_LEDGER.md" in _git(win, "diff", "--name-only", "--diff-filter=U").stdout.split()
        (win / "ESPALIER_MEMORY.md").write_bytes(_git(win, "show", ":2:ESPALIER_MEMORY.md").stdout.encode("utf-8"))
        _git(win, "add", "ESPALIER_MEMORY.md")
        assert _run_finish_line(win).returncode == 0
        assert not (win / ".git" / "MERGE_HEAD").exists()
        ledger = _git(win, "show", "HEAD:task-packs/FORWARD_LEDGER.md").stdout
        assert "`DEF-3`" in ledger and "`DEF-4`" in ledger
        assert _no_markers(win, "ESPALIER_MEMORY.md", "task-packs/FORWARD_LEDGER.md", "task-packs/LEDGER_PROBES.json")
        assert _git(win, "show", "HEAD:README.md").stdout == "mac\nwin\n"

    def test_a_row_file_both_sides_wrote_is_refused_by_name_and_one_side_kept(self, rm, two_machines):
        """Two writers on one row file: the resolver refuses it by name before
        it writes anything; one side kept by hand, the line concludes (the
        body's second refusal kind)."""
        mac, win = two_machines["mac"], two_machines["win"]
        _git(win, "switch", "--quiet", "-c", "lane/win")
        row = "task-packs/ledger.d/DEF-9.md"
        for repo, side in ((mac, "mac"), (win, "win")):
            (repo / "task-packs" / "ledger.d").mkdir()
            (repo / row).write_bytes(f"{side}\n".encode("utf-8"))
            _git(repo, "add", row)
            _git(repo, "commit", "--quiet", "-m", f"a row file on {side}")
        mac_row = _handoff(mac, "THE MAC LANDED A LANE", "2026-10-05")
        _git(mac, "push", "--quiet", "origin", "main")
        win_row = _handoff(win, "THE WINDOWS BOX LANDED A LANE", "2026-10-05")
        _git(win, "fetch", "--quiet", "origin")
        assert _begin_merge(win) == ["ESPALIER_MEMORY.md", row]

        proc = _run_finish_line(win)

        assert proc.returncode != 0 and "one writer per name" in proc.stderr and row in proc.stderr, \
            proc.stderr[-800:]
        assert (win / ".git" / "MERGE_HEAD").exists()
        _git(win, "checkout", "--ours", "--", row)
        _git(win, "add", row)
        assert _run_finish_line(win).returncode == 0
        assert _git(win, "show", f"HEAD:{row}").stdout == "win\n"
        memory = _git(win, "show", "HEAD:ESPALIER_MEMORY.md").stdout.splitlines()
        assert mac_row in memory and win_row in memory


# ── real git: two lanes writing fragments (TP-479 Wave C) ─────────────────────

FRAGMENTS = REPO_ROOT / "tools" / "cc" / "_record_fragments.py"


@pytest.fixture(scope="module")
def rf():
    return _load(FRAGMENTS, "record_fragments_for_record_merge")


def _fragment_handoff(rf, repo: Path, seat: str, headline: str, day: str, lane: str) -> str:
    """What /handoff and a lane's changelog entry do since Wave C: one Session
    Log row in a file the loader names from the clock and the seat, and one
    changelog fragment for the lane; the legacy table and ``[Unreleased]`` are
    not touched. Committed on the lane's branch."""
    import datetime as dt
    _git(repo, "switch", "--quiet", "-c", lane)
    now = dt.datetime.fromisoformat(f"{day}T12:00:00+00:00")
    row = _row(day, headline)
    rf.new_session_log_path(repo, seat=seat, now=now).write_bytes((row + "\n").encode("utf-8"))
    rf.changelog_path(repo, lane, today=day).parent.mkdir(parents=True, exist_ok=True)
    rf.changelog_path(repo, lane, today=day).write_bytes(f"### Added\n\n- **{headline}.**\n".encode("utf-8"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", f"docs(memory): {headline}")
    return row


class TestFragmentsMergeClean:
    """The pass line of TP-479 Wave C: two lanes from one base each run the
    real writer, GitHub's merge (``merge-tree``, no merge driver) takes both
    cleanly, and the record read back is the same whichever lane lands first.

    Earned red: with ``_fragment_handoff``'s body replaced by today's
    prepend (``_handoff``), the first assertion fails -- the same conflict
    ``TestTwoMachines`` records for the table."""

    def test_two_lanes_merge_clean_and_read_the_same_in_either_order(self, rf, two_machines):
        mac, win = two_machines["mac"], two_machines["win"]
        mac_row = _fragment_handoff(rf, mac, "mac", "THE MAC LANDED A LANE", "2026-10-11", "lane/mac-c")
        win_row = _fragment_handoff(rf, win, "win", "THE WINDOWS BOX LANDED A LANE", "2026-10-11", "lane/win-c")
        _git(mac, "push", "--quiet", "origin", "lane/mac-c")
        _git(win, "push", "--quiet", "origin", "lane/win-c")
        for repo in (mac, win):
            _git(repo, "fetch", "--quiet", "origin")
        assert _git(win, "merge-tree", "--write-tree", "origin/lane/mac-c", "HEAD", check=False).returncode == 0

        # Either order: the Mac's lane lands first, then the Windows box's, and
        # the other way round.
        _git(mac, "merge", "--quiet", "--no-edit", "origin/lane/win-c")
        _git(win, "merge", "--quiet", "--no-edit", "origin/lane/mac-c")
        mac_view = [r.line for r in rf.session_log_rows(mac)]
        win_view = [r.line for r in rf.session_log_rows(win)]
        assert mac_view == win_view
        assert {mac_row, win_row} <= set(mac_view)
        assert set(_seed_rows()) <= set(mac_view)
        assert rf.unreleased_text(mac) == rf.unreleased_text(win)
        assert "THE MAC LANDED A LANE." in rf.unreleased_text(mac)
        assert "THE WINDOWS BOX LANDED A LANE." in rf.unreleased_text(mac)
        # The legacy table is the seed's, byte for byte: neither writer touched it.
        seed = _git(mac, "show", "origin/main:ESPALIER_MEMORY.md").stdout
        assert (mac / "ESPALIER_MEMORY.md").read_text(encoding="utf-8") == seed

    def test_two_lanes_pruning_the_same_oldest_fragment_merge_clean(self, rf, two_machines):
        """Both lanes over the cap evict the same oldest fragment: a file
        deleted on both sides is no conflict."""
        mac, win = two_machines["mac"], two_machines["win"]
        _git(mac, "switch", "--quiet", "-c", "seed-fragments")
        for d in range(1, 4):
            path = mac / "memory" / "session-log.d" / f"2026-10-0{d}-120000-seed.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((_row(f"2026-10-0{d}", f"SEED {d}") + "\n").encode("utf-8"))
        _git(mac, "add", "-A")
        _git(mac, "commit", "--quiet", "-m", "three fragments")
        _git(mac, "push", "--quiet", "origin", "seed-fragments:main")
        _git(win, "fetch", "--quiet", "origin")
        _git(win, "switch", "--quiet", "--detach", "origin/main")
        for repo, seat in ((mac, "mac"), (win, "win")):
            _fragment_handoff(rf, repo, seat, f"{seat.upper()} ROW", "2026-10-11", f"lane/{seat}-p")
            left = rf.prune_session_log(repo, keep=3, today="2026-10-11")
            assert [r.date for r in left] == ["2026-10-01"]
            _git(repo, "add", "-A")
            _git(repo, "commit", "--quiet", "-m", "prune")
            _git(repo, "push", "--quiet", "origin", f"lane/{seat}-p")
        _git(win, "fetch", "--quiet", "origin")
        assert _git(win, "merge-tree", "--write-tree", "origin/lane/mac-p", "HEAD", check=False).returncode == 0
        _git(win, "merge", "--quiet", "--no-edit", "origin/lane/mac-p")
        names = sorted(p.name for p in (win / "memory" / "session-log.d").iterdir())
        assert names == ["2026-10-02-120000-seed.md", "2026-10-03-120000-seed.md",
                         "2026-10-11-120000-mac.md", "2026-10-11-120000-win.md"]
        # One over the cap: each lane pruned its own checkout, and the merge
        # (GitHub's, no resolver) sees neither prune. The next fragment write
        # prunes the merged tree back, which is why the merged tree's bound is
        # the cap plus the other lanes in flight (review of #179).
        _fragment_handoff(rf, win, "win", "NEXT ROW", "2026-10-12", "lane/win-next")
        assert [r.date for r in rf.prune_session_log(win, keep=3, today="2026-10-12")] == [
            "2026-10-02", "2026-10-03"]
        assert len(list((win / "memory" / "session-log.d").iterdir())) == 3


# ── real git: the live witness ───────────────────────────────────────────────

#: The 2026-10-05 collision between the two boxes, as commits on this
#: repository. Memory: #92's head (the Mac's README lane, merged into main)
#: against PR 88's head of that hour (the Windows box's guard lane), both
#: prepending a row under the Session Log header. Ledger: main after #91
#: merged (DEF-1126 filed into the first slot of the standalone class) against
#: PR 88's later head (DEF-1125 into the same slot), with the changelog's
#: Unreleased bullets and the probes roster conflicting beside them.
WITNESS_MEMORY = {"lane": "6eb550ff", "base": "ba9977b4"}
WITNESS_LEDGER = {"lane": "73cd91f0", "base": "58563022"}


def _reachable(*shas: str) -> bool:
    for sha in shas:
        proc = _git(REPO_ROOT, "cat-file", "-e", f"{sha}^{{commit}}", check=False)
        if proc.returncode != 0:
            return False
    return True


def _scratch_clone(tmp_path: Path, lane_sha: str) -> Path:
    clone = tmp_path / "witness"
    _git(tmp_path, "clone", "--quiet", "--shared", "--no-checkout", str(REPO_ROOT), str(clone))
    _identity(clone, "witness")
    # Not `lane`: the clone carries this checkout's `lane/*` branches, and a ref
    # cannot be both a name and a namespace.
    _git(clone, "switch", "--quiet", "-c", "witness-lane", lane_sha)
    return clone


class TestLiveWitness:
    @pytest.mark.skipif(not _reachable(*WITNESS_MEMORY.values()), reason="the 2026-10-05 memory witness commits are not in this checkout")
    def test_the_memory_row_collision_resolves_to_both_rows_under_the_cap(self, rm, tmp_path):
        clone = _scratch_clone(tmp_path, WITNESS_MEMORY["lane"])
        report = rm.merge_ref_in(clone, WITNESS_MEMORY["base"], run=_real_run(rm))
        # The witness roster predates 2026-10-12 and stores a `_count`; the
        # settle step that dropped it retired with the fold (TP-479a Wave C),
        # so the roster stays as git merged it and the memory file is resolved.
        assert report.merged and report.resolved == ["ESPALIER_MEMORY.md"], report
        text = (clone / "ESPALIER_MEMORY.md").read_text(encoding="utf-8")
        assert "THE README LANE LANDED" in text and "THE OVERNIGHT SESSION'S FOUR LANES" in text
        cap = rm.memory_cap(clone)
        assert cap is not None and cap == rm.memory_cap(REPO_ROOT)
        assert len(text.splitlines()) <= cap
        assert _git(clone, "status", "--porcelain").stdout == ""

    @pytest.mark.skipif(not _reachable(*WITNESS_LEDGER.values()), reason="the 2026-10-05 ledger witness commits are not in this checkout")
    def test_the_ledger_slot_collision_keeps_both_rows_and_converges(self, rm, gen, tmp_path):
        clone = _scratch_clone(tmp_path, WITNESS_LEDGER["lane"])
        # The changelog's Unreleased bullets conflict beside the ledger; the live
        # tree resolves them with a union attribute in .gitattributes, which the
        # lane commit predates, so the scratch clone declares it the same way.
        (clone / ".git" / "info" / "attributes").write_text("CHANGELOG.md merge=union\n", encoding="utf-8")
        report = rm.merge_ref_in(clone, WITNESS_LEDGER["base"], run=_real_run(rm))
        assert report.merged and set(report.resolved) == {"task-packs/FORWARD_LEDGER.md", "task-packs/LEDGER_PROBES.json"}, report
        ledger = (clone / "task-packs" / "FORWARD_LEDGER.md").read_text(encoding="utf-8")
        assert "| `DEF-1125` |" in ledger and "| `DEF-1126` |" in ledger
        assert ledger.count("| `DEF-1125` |") == 2 and ledger.count("| `DEF-1126` |") == 2  # member row + index row each
        gen._PROBES = clone / "task-packs" / "LEDGER_PROBES.json"
        assert gen.find_drift(ledger) == []
        probes = json.loads(gen._PROBES.read_text(encoding="utf-8"))  # ledger-read: gen._PROBES is the scratch clone's roster here, pinned as a file
        ids = {p["id"] for p in probes["probes"]}
        assert {"DEF-1125", "DEF-1126"} <= ids and "_count" not in probes
        changelog = (clone / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "stays green after ordinary work" in changelog and "Removing a temp directory works" in changelog
        assert _git(clone, "status", "--porcelain").stdout == ""


# ── a criss-cross: two merge bases ────────────────────────────────────────────

def _merge_lane_one_into_main(mac: Path, win: Path) -> None:
    """The pull request's merge of the first stacked lane: a merge commit on
    origin/main, made in the other machine's clone, which stands in for the
    GitHub merge button here."""
    _git(win, "push", "--quiet", "origin", "lane/one")
    _git(mac, "fetch", "--quiet", "origin")
    _git(mac, "merge", "--quiet", "--no-ff", "--no-edit", "origin/lane/one")
    _git(mac, "push", "--quiet", "origin", "main")


def _criss_cross(rm, mac: Path, win: Path, change) -> list[str]:
    """The stacked-lane shape of 2026-10-05: two lanes stacked on one machine,
    each caught up with the other machine's landed lane, then the first
    stacked lane merged. The second lane's next catch-up has TWO merge bases
    (the first lane's tip and the other machine's commit), and for a
    criss-cross git's stage 1 is a virtual base -- the recursive merge of the
    real bases, carrying nine-character ``Temporary merge branch`` markers
    where they disagreed (measured 2026-10-06, git 2.39.5) -- not a text either
    side ever wrote. ``change(repo, tag)`` is what each lane writes. Returns
    the merge bases, asserting there are two: the fixture proves its shape."""
    change(mac, "mac")
    _git(mac, "push", "--quiet", "origin", "main")
    _git(win, "switch", "--quiet", "-c", "lane/one")
    change(win, "one")
    _git(win, "switch", "--quiet", "-c", "lane/two")
    change(win, "two")
    _git(win, "fetch", "--quiet", "origin")
    _git(win, "switch", "--quiet", "lane/one")
    assert rm.merge_ref_in(win, "origin/main", run=_real_run(rm)).merged
    _git(win, "switch", "--quiet", "lane/two")
    assert rm.merge_ref_in(win, "origin/main", run=_real_run(rm)).merged
    _merge_lane_one_into_main(mac, win)
    _git(win, "fetch", "--quiet", "origin")
    bases = _git(win, "merge-base", "--all", "HEAD", "origin/main").stdout.split()
    assert len(bases) == 2, bases
    return bases


_DAY = "2026-10-05"
_HEADLINES = {"mac": "THE MAC LANDED A LANE", "one": "LANE ONE LANDED", "two": "LANE TWO LANDED"}
_FILINGS = {"mac": ("DEF-3", "DEF-1", "DEF-2"), "one": ("DEF-4", "DEF-1", "DEF-2"),
            "two": ("DEF-5", "DEF-4", "DEF-1", "DEF-2")}


def _handoff_change(repo: Path, tag: str) -> None:
    _handoff(repo, _HEADLINES[tag], _DAY)


def _filing_change(repo: Path, tag: str) -> None:
    _file_rows(repo, *_FILINGS[tag])


def _strike_change(repo: Path, tag: str) -> None:
    """The other machine and lane one file as above; lane two STRIKES the row
    lane one filed, the way the verb does it: the member row's text rewritten,
    its probe entry removed. Against the other machine's base, which never had
    the row, the probe reads as added by theirs and the ledger as one id filed
    twice; against lane one's base both read right. Two bases, two answers."""
    if tag != "two":
        _file_rows(repo, *_FILINGS[tag])
        return
    (repo / "task-packs" / "FORWARD_LEDGER.md").write_text(
        _ledger_with("DEF-4", "DEF-1", "DEF-2").replace(_member("DEF-4"), _member("DEF-4", "struck on lane two")),
        encoding="utf-8", newline="\n")
    _write_probes(repo, "DEF-1", "DEF-2")
    _git(repo, "commit", "--quiet", "-am", "ledger: strike DEF-4")


class TestCrissCrossBases:
    def test_two_stacked_lanes_caught_up_twice_merge_the_memory_file(self, rm, two_machines):
        mac, win = two_machines["mac"], two_machines["win"]
        bases = _criss_cross(rm, mac, win, _handoff_change)

        report = rm.merge_ref_in(win, "origin/main", run=_real_run(rm))

        assert report.merged and "ESPALIER_MEMORY.md" in report.resolved, report
        text = (win / "ESPALIER_MEMORY.md").read_text(encoding="utf-8")
        lines = text.splitlines()
        for headline in _HEADLINES.values():
            assert _row(_DAY, headline) in lines, headline
        assert "Temporary merge branch" not in text and "<<<<<<<" not in text
        assert len(lines) == CAP, "\n".join(lines)
        assert any("merge base" in n and (bases[0][:7] in n or bases[1][:7] in n) for n in report.notes), report.notes
        assert _git(win, "status", "--porcelain").stdout == ""
        assert _git(win, "rev-parse", "-q", "--verify", "HEAD^2", check=False).returncode == 0

    def test_two_stacked_filings_caught_up_twice_merge_the_ledger_and_its_probes(self, rm, gen, two_machines, monkeypatch):
        mac, win = two_machines["mac"], two_machines["win"]
        _criss_cross(rm, mac, win, _filing_change)

        report = rm.merge_ref_in(win, "origin/main", run=_real_run(rm))

        assert report.merged, report
        assert set(report.resolved) == {"task-packs/FORWARD_LEDGER.md", "task-packs/LEDGER_PROBES.json"}, report
        ledger = (win / "task-packs" / "FORWARD_LEDGER.md").read_text(encoding="utf-8")
        for rid in ("DEF-1", "DEF-2", "DEF-3", "DEF-4", "DEF-5"):
            assert _member(rid) in ledger and _index(rid) in ledger, rid
        assert "Temporary merge branch" not in ledger
        assert gen.stored_counts(ledger) == [] and gen.derive(ledger)["live_total"] == 5
        monkeypatch.setattr(gen, "_PROBES", win / "task-packs" / "LEDGER_PROBES.json")
        assert gen.find_drift(ledger) == []
        probes = json.loads((win / "task-packs" / "LEDGER_PROBES.json").read_text(encoding="utf-8"))
        assert "_count" not in probes and sorted(p["id"] for p in probes["probes"]) == ["DEF-1", "DEF-2", "DEF-3", "DEF-4", "DEF-5"]
        assert _git(win, "status", "--porcelain").stdout == ""

    def test_a_prose_conflict_under_two_bases_is_refused_naming_both_and_the_tree_is_left_clean(self, rm, two_machines):
        mac, win = two_machines["mac"], two_machines["win"]
        bases = _criss_cross(rm, mac, win, _handoff_change)
        for repo, word in ((win, "lane"), (mac, "main")):
            path = repo / "ESPALIER_MEMORY.md"
            path.write_text(path.read_text(encoding="utf-8").replace("# Project Memory", f"# Project Memory ({word})", 1),
                            encoding="utf-8", newline="\n")
            _git(repo, "commit", "--quiet", "-am", f"prose on {word}")
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "fetch", "--quiet", "origin")
        before = _git(win, "rev-parse", "HEAD").stdout

        with pytest.raises(rm.Unresolvable, match=r"none of the 2 merge bases") as excinfo:
            rm.merge_ref_in(win, "origin/main", run=_real_run(rm))

        assert all(b[:7] in str(excinfo.value) for b in bases), str(excinfo.value)
        assert _git(win, "rev-parse", "HEAD").stdout == before
        assert not (win / ".git" / "MERGE_HEAD").exists()
        assert _git(win, "status", "--porcelain").stdout == ""

    def test_a_strike_of_the_first_lanes_row_on_the_second_is_refused_not_resurrected(self, rm, two_machines):
        """Failure-mode review, driven: "the first base that resolves" resolved
        the probes against the base that never had the row (its retired probe
        came back) and the ledger against the other (the row stayed struck),
        in one merge commit, clean tree, exit 0. The bases must agree."""
        mac, win = two_machines["mac"], two_machines["win"]
        _criss_cross(rm, mac, win, _strike_change)
        before = _git(win, "rev-parse", "HEAD").stdout

        with pytest.raises(rm.Unresolvable, match=r"merge bases disagree"):
            rm.merge_ref_in(win, "origin/main", run=_real_run(rm))

        probes = json.loads((win / "task-packs" / "LEDGER_PROBES.json").read_text(encoding="utf-8"))
        ids = [p["id"] for p in probes["probes"]]
        assert "DEF-4" not in ids and sorted(ids) == ["DEF-1", "DEF-2", "DEF-3"], ids  # the retired probe stays retired
        assert _git(win, "rev-parse", "HEAD").stdout == before
        assert not (win / ".git" / "MERGE_HEAD").exists()
        assert _git(win, "status", "--porcelain").stdout == ""

    def test_a_git_that_cannot_name_the_bases_resolves_against_stage_one_and_says_so(self, rm, two_machines):
        mac, win = two_machines["mac"], two_machines["win"]
        _handoff(mac, "THE MAC LANDED A LANE", _DAY)
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "switch", "--quiet", "-c", "lane/win")
        _handoff(win, "THE WINDOWS BOX LANDED A LANE", _DAY)
        _git(win, "fetch", "--quiet", "origin")
        real = _real_run(rm)

        def run(argv, **kw):
            if list(argv[:3]) == ["git", "merge-base", "--all"]:
                return (128, "", "fatal: injected")
            return real(argv, **kw)

        report = rm.merge_ref_in(win, "origin/main", run=run)

        assert report.merged and report.resolved == ["ESPALIER_MEMORY.md"], report
        assert any("could not name the merge bases" in n for n in report.notes), report.notes


class TestMergeBases:
    def test_the_argv_is_pinned_and_a_failure_is_an_empty_list(self, rm, tmp_path):
        fake = _Fake({("git", "merge-base", "--all", "HEAD", "MERGE_HEAD"): (0, "aaa\nbbb\n", "")})
        assert rm._merge_bases(fake, tmp_path) == ["aaa", "bbb"]
        assert fake.calls == [["git", "merge-base", "--all", "HEAD", "MERGE_HEAD"]]
        fake = _Fake({("git", "merge-base"): (128, "", "fatal: not a git repository")})
        assert rm._merge_bases(fake, tmp_path) == []


class TestTheRunnersStops:
    def test_a_program_that_outlives_its_timeout_is_a_timed_out_stop(self, rm, monkeypatch):
        """The mail driver reads origin back after a push that outlived its
        timeout (one landed anyway, 2026-10-30), so the runner tells a timeout
        apart from its other stops, under the class every caller catches."""
        def never_returns(argv, **kw):
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

        monkeypatch.setattr(rm, "run_bounded", never_returns)
        timed_out = getattr(rm, "TimedOut", None)
        assert timed_out is not None and issubclass(timed_out, rm.Unresolvable), "no TimedOut stop on the runner"
        with pytest.raises(timed_out, match=r"git push took longer than 2s"):
            rm.run(["git", "push", "origin", "x"], timeout=2)
