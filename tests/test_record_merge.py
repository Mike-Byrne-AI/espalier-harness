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
import subprocess
import sys
from pathlib import Path

import pytest

from tests._git_oracle import _git_env
from tests.test_generate_ledger_regions import _ledger

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
        with pytest.raises(rm.Unresolvable, match=r"DEF-9 was filed on both sides.*renumber"):
            rm.resolve_ledger_hunk(hunk, gen)

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

    def test_class_index_rows_merge_by_section_and_a_count_clash_takes_ours(self, rm, gen):
        c77 = "| [§C77](#c77--a-class) | A class | 3 | LOGIC_BUG | ADOPTER | ~1 LOC |"
        c78 = "| [§C78](#c78--another) | Another | 1 | HYGIENE | MAINTAINER | ~1 LOC |"
        assert rm.resolve_ledger_hunk(rm.Hunk([c77], [], [c78]), gen) == [c77, c78]
        c0_ours = "| [§C0](#c0--standalone) | Standalone | 168 | MIXED | MIXED | — |"
        c0_theirs = c0_ours.replace("168", "169")
        assert rm.resolve_ledger_hunk(rm.Hunk([c0_ours], [], [c0_theirs]), gen) == [c0_ours]

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
               "ledger_lock", "LedgerBusy", "_PROBES")

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
           "_count": len(ids), "probes": [{"id": i, "subject": "site", "cmd": f"echo {i}", "open_value": i,
                                           "why_not": None, "row_sha": "x"} for i in ids]}
    return doc


class TestRegenerateLedger:
    def _probes(self, tmp_path: Path, *ids: str) -> Path:
        p = tmp_path / "LEDGER_PROBES.json"
        p.write_text(json.dumps(_probes_doc(*ids), indent=1) + "\n", encoding="utf-8")
        return p

    def test_stale_counts_after_a_row_union_are_re_derived(self, rm, gen, tmp_path):
        text = _ledger(headline=1, c1_cell="1", c1_members=1, split=(1, 0, 0), adopter=1)  # two rows, counts say one
        out = rm.regenerate_ledger(text, gen, self._probes(tmp_path, "DEF-1", "DEF-2"))
        assert "**Members (2)**" in out and "**Live: 2**" in out and "**2** reach an adopter" in out
        assert gen.find_drift(out) == []

    def test_drift_the_generator_cannot_write_is_a_refusal_naming_the_region(self, rm, gen, tmp_path):
        struck = _ledger(c1_rows=("| ~~`DEF-1`~~ | site | what | major |", "| `DEF-2` | site | what | minor |"),
                         appendix=("| ~~`DEF-1`~~ | §C1 | site |", "| `DEF-2` | §C1 | site |"),
                         headline=1, c1_cell="1", c1_members=1, split=(1, 0, 0), adopter=1)
        with pytest.raises(rm.Unresolvable, match="does not converge.*probe-roster"):
            rm.regenerate_ledger(struck, gen, self._probes(tmp_path, "DEF-1", "DEF-2"))


class TestProbesThreeWay:
    def _text(self, *ids: str, **top) -> str:
        return json.dumps(_probes_doc(*ids, **top), indent=1) + "\n"

    def test_probes_added_on_each_side_are_unioned_and_the_count_re_derived(self, rm):
        out = json.loads(rm.resolve_probes(self._text("A", "B"), self._text("A", "B", "C"), self._text("A", "B", "D")))
        assert [p["id"] for p in out["probes"]] == ["A", "B", "C", "D"]
        assert out["_count"] == 4 and isinstance(out["_count"], int)

    def test_a_probe_retired_on_one_side_stays_retired(self, rm):
        out = json.loads(rm.resolve_probes(self._text("A", "B"), self._text("B"), self._text("A", "B", "D")))
        assert [p["id"] for p in out["probes"]] == ["B", "D"]

    def test_a_probe_changed_on_one_side_takes_that_side(self, rm):
        ours = json.loads(self._text("A", "B"))
        ours["probes"][0]["open_value"] = "re-pinned"
        out = json.loads(rm.resolve_probes(self._text("A", "B"), json.dumps(ours), self._text("A", "B", "D")))
        assert out["probes"][0]["open_value"] == "re-pinned" and out["_count"] == 3

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
        assert list(json.loads(out)) == ["_README", "_generated", "_count", "probes", "_note"]
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


class TestSettleProbesCount:
    """DEF-1128: a roster git merges clean as text can carry a stale ``_count``
    (the list moved on one side and the field on the other, or a hand edit
    left the field behind); the settle step re-derives it after ANY merge."""

    def _roster(self, root: Path, *ids: str, count: int | None = None) -> Path:
        doc = _probes_doc(*ids)
        if count is not None:
            doc["_count"] = count
        (root / "task-packs").mkdir(exist_ok=True)
        p = root / "task-packs" / "LEDGER_PROBES.json"
        p.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        return p

    def test_a_count_that_moved_is_rewritten_byte_stably_and_named(self, rm, gen, tmp_path):
        p = self._roster(tmp_path, "DEF-1", "DEF-2", "DEF-3", count=5)
        said: list[str] = []
        rewritten, note = rm.settle_probes_count(tmp_path, gen, say=said.append)
        assert rewritten == ["task-packs/LEDGER_PROBES.json"]
        assert "_count settled 5 -> 3" in note
        assert p.read_text(encoding="utf-8") == (
            json.dumps(_probes_doc("DEF-1", "DEF-2", "DEF-3"), indent=1, ensure_ascii=False) + "\n")
        assert said == []

    def test_a_count_that_matches_leaves_the_bytes_alone(self, rm, gen, tmp_path):
        p = self._roster(tmp_path, "DEF-1", "DEF-2")
        before = p.read_bytes()
        assert rm.settle_probes_count(tmp_path, gen) == ([], None)
        assert p.read_bytes() == before

    def test_no_roster_is_nothing_to_settle(self, rm, gen, tmp_path):
        assert rm.settle_probes_count(tmp_path, gen) == ([], None)

    def test_a_roster_this_tool_cannot_read_is_a_note_never_a_refusal(self, rm, gen, tmp_path):
        """The probes checker names a broken roster next; a clean merge is not
        the place to refuse over a file this tool did not write."""
        p = self._roster(tmp_path, "DEF-1")
        p.write_text("{not json", encoding="utf-8")
        said: list[str] = []
        assert rm.settle_probes_count(tmp_path, gen, say=said.append) == ([], None)
        assert len(said) == 1 and "LEDGER_PROBES.json" in said[0] and "not settled" in said[0]

    def test_the_ledger_regions_are_re_derived_against_the_settled_roster(self, rm, gen, tmp_path):
        self._roster(tmp_path, "DEF-1", "DEF-2", count=1)
        ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
        ledger.write_text(_ledger(headline=1, c1_cell="1", c1_members=1, split=(1, 0, 0), adopter=1),
                          encoding="utf-8", newline="\n")  # two rows, counts say one
        rewritten, _note = rm.settle_probes_count(tmp_path, gen)
        assert rewritten == ["task-packs/LEDGER_PROBES.json", "task-packs/FORWARD_LEDGER.md"]
        text = ledger.read_text(encoding="utf-8")
        assert "**Members (2)**" in text and "**Live: 2**" in text
        gen._PROBES = tmp_path / "task-packs" / "LEDGER_PROBES.json"
        assert gen.find_drift(text) == []

    def test_regeneration_is_left_to_the_caller_while_the_ledger_is_still_in_conflict(self, rm, gen, tmp_path):
        self._roster(tmp_path, "DEF-1", "DEF-2", count=1)
        ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
        ledger.write_text("<<<<<<< ours\nconflict\n=======\n>>>>>>> theirs\n", encoding="utf-8")
        rewritten, _note = rm.settle_probes_count(tmp_path, gen, regenerate=False)
        assert rewritten == ["task-packs/LEDGER_PROBES.json"]
        assert ledger.read_text(encoding="utf-8").startswith("<<<<<<< ours")


# ── orchestration on a recording fake ────────────────────────────────────────

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

    def test_a_clean_merge_commits_and_resolves_nothing(self, rm, tmp_path):
        fake = _Fake({**self._base(tmp_path), ("git", "merge", "--no-edit"): (0, "Merge made\n", "")})
        report = rm.merge_ref_in(tmp_path, "origin/main", run=fake)
        assert report.merged is True and report.resolved == []

    def _stale_roster(self, root: Path, *ids: str, count: int) -> Path:
        doc = _probes_doc(*ids)
        doc["_count"] = count
        (root / "task-packs").mkdir(exist_ok=True)
        p = root / "task-packs" / "LEDGER_PROBES.json"
        p.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        return p

    def test_a_clean_merge_with_a_stale_roster_settles_the_count_into_the_merge_commit(self, rm, tmp_path):
        """DEF-1128: the roster merged clean as text with its ``_count`` behind
        its list; the settle step rewrites it and amends the merge commit git
        just made (HEAD^2 exists), so the push carries a roster the checker
        will not refuse."""
        p = self._stale_roster(tmp_path, "DEF-1", count=5)
        fake = _Fake({**self._base(tmp_path),
                      ("git", "merge", "--no-edit"): (0, "Merge made\n", ""),
                      ("git", "add", "--", "task-packs/LEDGER_PROBES.json"): (0, "", ""),
                      ("git", "rev-parse", "-q", "--verify", "HEAD^2"): (0, "abc\n", ""),
                      ("git", "commit", "--amend", "--no-edit"): (0, "", "")})
        report = rm.merge_ref_in(tmp_path, "origin/main", run=fake)
        assert report.merged is True and report.resolved == ["task-packs/LEDGER_PROBES.json"]
        assert json.loads(p.read_text(encoding="utf-8"))["_count"] == 1
        assert fake.has("git", "commit", "--amend", "--no-edit")
        assert any("_count settled 5 -> 1" in n and "merge commit" in n for n in report.notes), report.notes
        assert not (tmp_path / "task-packs" / "FORWARD_LEDGER.md.lock").exists()

    def test_a_fast_forward_with_a_stale_roster_commits_the_settle_on_its_own(self, rm, tmp_path):
        """A fast-forward made no merge commit (HEAD^2 is absent) and HEAD is
        the base's own commit, which an amend would rewrite; the settle rides
        a commit of its own instead."""
        self._stale_roster(tmp_path, "DEF-1", count=5)
        fake = _Fake({**self._base(tmp_path),
                      ("git", "merge", "--no-edit"): (0, "Fast-forward\n", ""),
                      ("git", "add", "--"): (0, "", ""),
                      ("git", "rev-parse", "-q", "--verify", "HEAD^2"): (128, "", ""),
                      ("git", "commit", "-m"): (0, "", "")})
        report = rm.merge_ref_in(tmp_path, "origin/main", run=fake)
        assert report.resolved == ["task-packs/LEDGER_PROBES.json"]
        assert fake.has("git", "commit", "-m") and not fake.has("git", "commit", "--amend")

    def test_a_settle_that_cannot_take_the_ledger_lock_puts_the_merge_back(self, rm, tmp_path):
        """The settle refuses under a held lock, and a refusal must leave what
        the operator had: the merge git already committed is undone to
        ORIG_HEAD, the pre-merge HEAD, which the clean-tree precondition makes
        safe to return to."""
        self._stale_roster(tmp_path, "DEF-1", count=5)
        (tmp_path / "task-packs" / "FORWARD_LEDGER.md.lock").write_text("pid 1\n", encoding="utf-8")
        fake = _Fake({**self._base(tmp_path),
                      ("git", "merge", "--no-edit"): (0, "Merge made\n", ""),
                      ("git", "reset", "--hard", "ORIG_HEAD"): (0, "", "")})
        with pytest.raises(rm.Unresolvable, match="another ledger verb holds"):
            rm.merge_ref_in(tmp_path, "origin/main", run=fake)
        assert fake.has("git", "reset", "--hard", "ORIG_HEAD")
        assert not fake.has("git", "commit")

    def test_a_settle_whose_generator_is_missing_puts_the_merge_back_too(self, rm, tmp_path, monkeypatch):
        """Failure-mode review, 2026-10-05: the generator load sat outside the
        undo's reach, so a deploy set without it left the merge committed and
        unsettled with no reset -- the one shape the docstring promised against."""
        self._stale_roster(tmp_path, "DEF-1", count=5)

        def absent(name):
            raise rm.Unresolvable(f"{name}.py is not beside this script: the deploy set is incomplete")

        monkeypatch.setattr(rm, "_load_sibling", absent)
        fake = _Fake({**self._base(tmp_path),
                      ("git", "merge", "--no-edit"): (0, "Merge made\n", ""),
                      ("git", "reset", "--hard", "ORIG_HEAD"): (0, "", "")})
        with pytest.raises(rm.Unresolvable, match="deploy set is incomplete"):
            rm.merge_ref_in(tmp_path, "origin/main", run=fake)
        assert fake.has("git", "reset", "--hard", "ORIG_HEAD")

    def test_a_clean_merge_with_a_settled_roster_spawns_nothing_more(self, rm, tmp_path):
        self._stale_roster(tmp_path, "DEF-1", count=1)
        fake = _Fake({**self._base(tmp_path), ("git", "merge", "--no-edit"): (0, "Merge made\n", "")})
        report = rm.merge_ref_in(tmp_path, "origin/main", run=fake)
        assert report.resolved == [] and not fake.has("git", "commit")

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
                          errors="replace", env=_git_env(), check=check, timeout=60)


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


def _ledger_with(*ids: str) -> str:
    rows = tuple(_member(i) for i in ids)
    appendix = tuple(_index(i) for i in ids)
    n = len(ids)
    return _ledger(headline=n, c1_cell=str(n), c1_members=n, c1_rows=rows, appendix=appendix,
                   split=(n, 0, 0), adopter=n)


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


def _file_rows(repo: Path, *ids: str) -> None:
    """What the ledger verb does: the rows into the first slot, the index rows,
    the derived counts rewritten, the probes appended."""
    (repo / "task-packs" / "FORWARD_LEDGER.md").write_text(_ledger_with(*ids), encoding="utf-8", newline="\n")
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

    def test_two_filings_into_one_slot_keep_every_row_and_re_derive_the_counts(self, rm, gen, two_machines):
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
        assert "**Members (5)**" in ledger and "**Live: 5**" in ledger and "**5** reach an adopter" in ledger
        assert "(5 LIVE issues in 1 classes + 0 standalone)" in ledger
        gen._PROBES = win / "task-packs" / "LEDGER_PROBES.json"
        assert gen.find_drift(ledger) == []
        probes = json.loads((win / "task-packs" / "LEDGER_PROBES.json").read_text(encoding="utf-8"))
        assert probes["_count"] == 5 and sorted(p["id"] for p in probes["probes"]) == ["DEF-1", "DEF-2", "DEF-3", "DEF-4", "DEF-5"]
        assert _git(win, "status", "--porcelain").stdout == ""
        assert not (win / "task-packs" / "FORWARD_LEDGER.md.lock").exists()

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
        assert probes["_count"] == 4 and [p["id"] for p in probes["probes"]] == ["DEF-1", "DEF-2", "DEF-8", "DEF-9"]
        assert not (win / "task-packs" / "FORWARD_LEDGER.md.lock").exists()
        assert _git(win, "status", "--porcelain").stdout == ""

    def _hand_edit_the_count(self, repo: Path, count: int) -> None:
        """What a hand merge did on 2026-10-05: the list moved, the field did
        not. Written with the verbs' serializer so only the field differs."""
        p = repo / "task-packs" / "LEDGER_PROBES.json"
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["_count"] = count
        p.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    def test_a_roster_hand_edited_without_its_count_is_settled_in_the_merge_commit(self, rm, gen, two_machines):
        """DEF-1128, the live shape: main carries a roster whose ``_count`` a
        hand merge left behind; the lane touched only the memory file, so git
        merges the roster clean as text and, before the settle step, the stale
        count rode into the merge commit."""
        mac, win = two_machines["mac"], two_machines["win"]
        _file_rows(mac, "DEF-3", "DEF-1", "DEF-2")
        self._hand_edit_the_count(mac, 2)
        _git(mac, "commit", "--quiet", "-am", "ledger: a hand merge left the count behind")
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "switch", "--quiet", "-c", "lane/win")
        _handoff(win, "THE WINDOWS BOX LANDED A LANE", "2026-10-05")
        _git(win, "fetch", "--quiet", "origin")
        assert _git(win, "merge-tree", "--write-tree", "origin/main", "HEAD", check=False).returncode == 0

        report = rm.merge_ref_in(win, "origin/main", run=_real_run(rm))

        assert report.merged and report.resolved == ["task-packs/LEDGER_PROBES.json"], report
        assert any("_count settled 2 -> 3" in n for n in report.notes), report.notes
        committed = _git(win, "show", "HEAD:task-packs/LEDGER_PROBES.json").stdout
        assert json.loads(committed)["_count"] == 3
        assert _git(win, "rev-parse", "-q", "--verify", "HEAD^2", check=False).returncode == 0  # still a merge commit
        assert _git(win, "log", "--merges", "--oneline").stdout.count("\n") == 1
        assert _git(win, "status", "--porcelain").stdout == ""
        assert not (win / "task-packs" / "FORWARD_LEDGER.md.lock").exists()
        ledger = (win / "task-packs" / "FORWARD_LEDGER.md").read_text(encoding="utf-8")
        gen._PROBES = win / "task-packs" / "LEDGER_PROBES.json"
        assert gen.find_drift(ledger) == []

    def test_a_stale_count_beside_a_memory_conflict_is_settled_under_the_one_merge_commit(self, rm, two_machines):
        """The conflicted path: the memory rows collide, the roster merges
        clean with its count behind, and the settle step runs under the
        ledger lock before the one merge commit."""
        mac, win = two_machines["mac"], two_machines["win"]
        _file_rows(mac, "DEF-3", "DEF-1", "DEF-2")
        self._hand_edit_the_count(mac, 2)
        _git(mac, "commit", "--quiet", "-am", "ledger: a hand merge left the count behind")
        _handoff(mac, "THE MAC LANDED A LANE", "2026-10-05")
        _git(mac, "push", "--quiet", "origin", "main")
        _git(win, "switch", "--quiet", "-c", "lane/win")
        _handoff(win, "THE WINDOWS BOX LANDED A LANE", "2026-10-05")
        _git(win, "fetch", "--quiet", "origin")

        report = rm.merge_ref_in(win, "origin/main", run=_real_run(rm))

        assert set(report.resolved) == {"ESPALIER_MEMORY.md", "task-packs/LEDGER_PROBES.json"}, report
        assert json.loads(_git(win, "show", "HEAD:task-packs/LEDGER_PROBES.json").stdout)["_count"] == 3
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
        probes = json.loads(gen._PROBES.read_text(encoding="utf-8"))
        ids = {p["id"] for p in probes["probes"]}
        assert {"DEF-1125", "DEF-1126"} <= ids and probes["_count"] == len(probes["probes"])
        changelog = (clone / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "stays green after ordinary work" in changelog and "Removing a temp directory works" in changelog
        assert _git(clone, "status", "--porcelain").stdout == ""
