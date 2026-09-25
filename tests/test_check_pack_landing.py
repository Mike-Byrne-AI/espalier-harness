"""Regression tests for the ``## Landing`` closeout parser
(``scripts/check_pack_landing.py``).

These lock the two defects found while archiving the post-tier-retirement
packs:

1. The parser must tolerate the markdown-bold ``- **State:** LANDED`` spelling
   that packs actually author -- not only the canonical non-bold
   ``- State: LANDED`` shown in the blueprint-authoring skill.
2. ``landed_state`` must read the ``## Landing`` stanza, not the top-of-file
   ``## Status`` block (which carries its own authoring ``State: DRAFT``). Before
   the fix, ``re.search`` returned the first ``State:`` (the Status DRAFT), so
   every landed pack would have been mis-flagged as unstamped.
"""
# pytest-marker: default-unit -- pure unit tests over a parser function (no
# subprocess, no security/release surface); the fast unit slice is correct.
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# scripts/ is dev tooling and is intentionally NOT shipped in the sdist (per
# MANIFEST.in). When tests run from a sdist install, scripts/ is absent; skip
# the whole file with a clear reason in that environment.
if not (REPO_ROOT / "scripts" / "check_pack_landing.py").is_file():
    pytest.skip(
        "scripts/check_pack_landing.py is dev tooling not shipped in sdist; "
        "this test file applies only to source-checkout runs.",
        allow_module_level=True,
    )

# full-tree-exempt: the two live-tree tests below read `task-packs/Done/`, which
# IS export-ignored (.gitattributes `/task-packs/Done/`), but each carries its own
# `skipif(not (REPO_ROOT / "task-packs" / "Done").is_dir())` so they skip rather
# than FileNotFoundError on an extracted archive. Verified: `scripts/` is NOT
# export-ignored, so the module-level guard above does not fire on an export and
# the per-test skipif is what does the work. Keyed on `Done/`, never on
# `task-packs/` -- `task-packs/CLAUDE.md` is TRACKED, so the parent directory
# exists in every clone while its packs do not.
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_pack_landing  # type: ignore[import-not-found]  # noqa: E402

# A pack as actually authored: a top ``## Status`` block with the authoring
# State (DRAFT) and a bottom ``## Landing`` stanza with the terminal State.
# Both use markdown bold -- the spelling every real pack uses.
_LANDED_PACK = """\
# TP-999 -- example

## Status

- **Kind:** PACK
- **State:** DRAFT

## Landing

- **State:** LANDED
- **Commits:** `deadbee`
- **Date:** 2026-01-01
"""

_DRAFT_PACK = """\
# TP-998 -- example

## Status

- **State:** DRAFT
"""


def test_reads_bold_landing_state_not_top_status():
    # Regression for BOTH bugs: the old regex matched no bold ``**State:**`` at
    # all (returned None); even had it matched, ``re.search`` would have grabbed
    # the Status-block DRAFT. The Landing stanza's LANDED is the answer.
    assert check_pack_landing.landed_state(_LANDED_PACK) == "LANDED"


def test_tolerates_canonical_non_bold_spelling():
    # The blueprint-authoring skill shows ``- State: LANDED`` (no bold).
    pack = "## Landing\n- State: LANDED\n"
    assert check_pack_landing.landed_state(pack) == "LANDED"


def test_scrapped_is_recognized():
    pack = "## Landing\n- **State:** SCRAPPED\n"
    assert check_pack_landing.landed_state(pack) == "SCRAPPED"


def test_no_landing_stanza_falls_back_to_non_terminal_status():
    # A pack that never landed has only the Status DRAFT -- correctly non-terminal.
    assert check_pack_landing.landed_state(_DRAFT_PACK) == "DRAFT"


def test_absent_state_returns_none():
    assert check_pack_landing.landed_state("# TP-000\n\nno state here\n") is None


def test_prose_mention_of_state_is_not_matched():
    # "the State: field" in running prose must not be read as the marker.
    pack = "Some prose about the State: field of a pack.\n\n## Status\n- **State:** DRAFT\n"
    assert check_pack_landing.landed_state(pack) == "DRAFT"


def test_unstamped_packs_flags_only_non_terminal(tmp_path: Path):
    done = tmp_path / "Done"
    done.mkdir()
    (done / "TP-1-landed.md").write_text(_LANDED_PACK, encoding="utf-8")
    (done / "TP-2-draft.md").write_text(_DRAFT_PACK, encoding="utf-8")
    flagged = check_pack_landing.unstamped_packs(done_dir=done)
    names = {name for name, _ in flagged}
    assert names == {"TP-2-draft.md"}  # the LANDED pack is NOT flagged


def test_unstamped_packs_empty_when_done_absent(tmp_path: Path):
    assert check_pack_landing.unstamped_packs(done_dir=tmp_path / "nope") == []


def test_non_pack_files_are_not_in_the_population(tmp_path: Path):
    # A runbook / archive in Done/ has no Landing stanza by construction and
    # must not be reported -- the population bug that buried 3 real signals
    # under 13 non-findings and taught every reader to skip the output.
    done = tmp_path / "Done"
    done.mkdir(parents=True)
    (done / "RUNBOOK_active-set_2099-01-01.md").write_text("# runbook\n", encoding="utf-8")
    (done / "BACKLOG_REVIEW_2099-01-01.md").write_text("# review\n", encoding="utf-8")
    (done / "CHANGELOG_archive_20990101.md").write_text("# archive\n", encoding="utf-8")
    (done / "TP-999-real-pack.md").write_text(
        "# pack\n\n## Landing\n- State: DRAFT\n", encoding="utf-8"
    )
    flagged = check_pack_landing.unstamped_packs(done_dir=done)
    assert [n for n, _ in flagged] == ["TP-999-real-pack.md"]


_BOLD_VALUE_PACK = """\
# TP-997 -- example

## Status

- **State:** DRAFT

## Landing
- State: **LANDED 2026-01-01.**
"""


def test_bold_value_state_names_the_violation(tmp_path: Path):
    # The diagnostic, not a parser widening. `- State: **LANDED**` violates the
    # bare-value convention (implement-pack.md); TP-311 explicitly REJECTED
    # relaxing _STATE_RE for it. Before this, it read as "(no State: line)" --
    # indistinguishable from a genuinely unstamped pack.
    assert check_pack_landing.bold_value_state(_BOLD_VALUE_PACK) == "LANDED"


def test_bold_value_pack_is_still_an_offender(tmp_path: Path):
    # The convention is PRESERVED, only its legibility changed: landed_state
    # still returns None, so the pack stays reported until the record is
    # de-bolded. A diagnostic that also widened the parser would have quietly
    # blessed the violation.
    assert check_pack_landing.landed_state(_BOLD_VALUE_PACK) is None
    done = tmp_path / "Done"
    done.mkdir(parents=True)
    (done / "TP-997-bold.md").write_text(_BOLD_VALUE_PACK, encoding="utf-8")
    assert [n for n, _ in check_pack_landing.unstamped_packs(done_dir=done)] == [
        "TP-997-bold.md"
    ]


def test_conforming_state_line_wins_over_a_bold_one():
    # FP calibration: bold_value_state must not fire on a pack that already has
    # a conforming line, or every correctly-stamped pack picks up a spurious
    # "convention violation" label.
    assert check_pack_landing.bold_value_state(_LANDED_PACK) is None


def test_roadmap_packs_are_their_own_tier_not_offenders(tmp_path: Path):
    # A drained ROADMAP in Done/ is finished-as-a-roadmap. Reporting it forever
    # is what made this tool permanently red; folding it into _LANDED_STATES
    # would instead make it silently invisible. It gets a tier.
    done = tmp_path / "Done"
    done.mkdir(parents=True)
    (done / "TP-996-roadmap.md").write_text(
        "# pack\n\n## Landing\n- State: ROADMAP\n", encoding="utf-8"
    )
    (done / "TP-995-draft.md").write_text(
        "# pack\n\n## Landing\n- State: DRAFT\n", encoding="utf-8"
    )
    assert check_pack_landing.roadmap_packs(done_dir=done) == ["TP-996-roadmap.md"]
    assert [n for n, _ in check_pack_landing.unstamped_packs(done_dir=done)] == [
        "TP-995-draft.md"
    ]


def test_empty_landing_field_counts_as_missing(tmp_path: Path):
    # `- Commits:` with nothing after the colon IS the incompleteness this
    # reports. A `\s`-based field regex crosses the newline and reads the NEXT
    # line's `-` as the value, silently answering "is the line there?" instead
    # of "is the field filled?" -- the born-weak shape this tool was rescued from.
    done = tmp_path / "Done"
    done.mkdir(parents=True)
    (done / "TP-994-empty-fields.md").write_text(
        "# pack\n\n## Landing\n- State: LANDED\n- Commits:\n- Suite:\n- Date:\n",
        encoding="utf-8",
    )
    assert check_pack_landing.incomplete_landings(done_dir=done) == [
        ("TP-994-empty-fields.md", ["Commits", "Suite", "Date"])
    ]


def test_complete_landing_stanza_is_not_reported(tmp_path: Path):
    # Bold LABELS (`- **Commits:** ...`) are the spelling real packs use and must
    # still read as filled -- only a bold VALUE is the violation 1-C names.
    done = tmp_path / "Done"
    done.mkdir(parents=True)
    (done / "TP-993-complete.md").write_text(
        "# pack\n\n## Landing\n- **State:** LANDED\n- **Commits:** `deadbee`\n"
        "- **Suite:** 7123 passed\n- **Date:** 2026-01-01\n",
        encoding="utf-8",
    )
    (done / "TP-992-suiteless.md").write_text(
        "# pack\n\n## Landing\n- State: LANDED\n- Commits: `abc1234`\n- Date: 2026-01-01\n",
        encoding="utf-8",
    )
    assert check_pack_landing.incomplete_landings(done_dir=done) == [
        ("TP-992-suiteless.md", ["Suite"])
    ]


def test_incomplete_landings_ignores_non_landed_and_non_packs(tmp_path: Path):
    # Scope: only LANDED packs. A DRAFT pack's empty fields are not a record
    # defect (it has not landed), and a runbook has no stanza at all.
    done = tmp_path / "Done"
    done.mkdir(parents=True)
    (done / "TP-991-draft.md").write_text(
        "# pack\n\n## Landing\n- State: DRAFT\n- Commits:\n", encoding="utf-8"
    )
    (done / "RUNBOOK_x_2099-01-01.md").write_text("# runbook\n", encoding="utf-8")
    assert check_pack_landing.incomplete_landings(done_dir=done) == []


@pytest.mark.skipif(
    not (REPO_ROOT / "task-packs" / "Done").is_dir(),
    reason="self-host only: task-packs/Done/ is gitignored -- absent in a fresh clone",
)
def test_live_done_tree_has_no_unstamped_packs():
    # The standing proof the population fix + the three record repairs landed:
    # with non-packs and ROADMAPs out of the population, the advisory reaches
    # ZERO for the first time -- which is what makes the already-shipped
    # `--strict` flag usable. This is the "third arm" a rival Done/-population
    # walker would have duplicated.
    unstamped = check_pack_landing.unstamped_packs()
    assert not unstamped, (
        "Done/ packs with no terminal Landing State: -- stamp LANDED/SCRAPPED, or "
        f"if it is not a pack, it should not be in Done/: {unstamped}"
    )


@pytest.mark.skipif(
    not (REPO_ROOT / "task-packs" / "Done").is_dir(),
    reason="self-host only: task-packs/Done/ is gitignored -- absent in a fresh clone",
)
def test_live_done_tree_population_is_non_trivial():
    # Non-vacuity floor for the zero above. `unstamped_packs()` returning [] is
    # also what a broken glob, a wrong DONE_DIR, or an over-eager population
    # predicate produces -- so the zero only means something if the walk is
    # still SEEING packs. Asserts the scan has a real population, not the exact
    # count (which moves every time a pack lands).
    done = REPO_ROOT / "task-packs" / "Done"
    scanned = [p.name for p in done.glob("*.md") if check_pack_landing.is_pack_file(p.name)]
    assert len(scanned) > 20, (
        f"only {len(scanned)} packs classified in Done/ -- the population "
        "predicate or the glob broke; the passing zero above would be vacuous"
    )


# --------------------------------------------------------------------------
# GROWTH RATCHETS over the two ADVISORY sections.
#
# The script prints both sections and exits 0, so nothing carried them forward
# and nobody acted on them. Giving them a "durable home" by writing them to a
# file would only be a second place to lose them -- a destination with no reader
# is the same failure one layer down. pytest IS the reader: it runs every suite,
# it already reads this tree, and it needs no new file, flag, or surface.
#
# These are CEILINGS, not equalities. The backlog may drain freely -- that is the
# point -- but it must not grow silently. Lower the constant in the same commit
# that drains one; never raise it. The script stays unchanged and keeps exiting 0,
# because these are genuine advisories and a hard fail on a small backlog just
# trains the reader to bypass the script.
# --------------------------------------------------------------------------
# HEADROOM OF ONE, AND THE ONE IS LOAD-BEARING -- these are not "current count"
# snapshots. A ceiling pinned to exactly today's number reds on the NEXT ordinary
# step rather than on the thing it means to catch, and the repo has now paid for
# that lesson four times on a different ratchet: a routine handoff mints a citation,
# a ceiling sitting at its own count goes red, and the reader learns to bump the
# constant. A ratchet that trains people to raise it has inverted its own purpose.
#
# So each ceiling is `today + 1`, and the +1 encodes a specific claim:
#
#   ROADMAP-in-Done/  : one undrained roadmap may legitimately be in flight. TWO
#                       means a roadmap was parked and forgotten, which is the
#                       actual defect -- a ROADMAP in Done/ is finished only when
#                       its children are drained.
#   incomplete Landing: one pack may legitimately be mid-landing. The stanza wants
#                       `Commits: <sha>`, which cannot be known until AFTER the
#                       commit, so hand-landing necessarily passes through a window
#                       where the stanza is incomplete. TWO simultaneous means a
#                       record was abandoned rather than in progress.
#
# Lower either in the same commit that drains one; never raise. If one drains to
# zero, DELETE its ceiling and its non-vacuity arm rather than leaving a guard that
# can no longer fail for the right reason.
_MAX_ROADMAP_IN_DONE = 6
_MAX_INCOMPLETE_LANDINGS = 3


@pytest.mark.skipif(
    not (REPO_ROOT / "task-packs" / "Done").is_dir(),
    reason="self-host only: task-packs/Done/ is gitignored -- absent in a fresh clone",
)
def test_roadmap_packs_in_done_do_not_grow():
    roadmaps = check_pack_landing.roadmap_packs()
    assert len(roadmaps) <= _MAX_ROADMAP_IN_DONE, (
        f"{len(roadmaps)} ROADMAP packs sit in Done/, above the ratchet of "
        f"{_MAX_ROADMAP_IN_DONE}: {sorted(roadmaps)}. A ROADMAP in Done/ is only "
        "finished when its children are drained. Drain them, or -- if this one is "
        "genuinely complete -- lower the ratchet in the same commit. Never raise it."
    )


@pytest.mark.skipif(
    not (REPO_ROOT / "task-packs" / "Done").is_dir(),
    reason="self-host only: task-packs/Done/ is gitignored -- absent in a fresh clone",
)
def test_incomplete_landing_stanzas_do_not_grow():
    incomplete = check_pack_landing.incomplete_landings()
    assert len(incomplete) <= _MAX_INCOMPLETE_LANDINGS, (
        f"{len(incomplete)} LANDED packs carry an incomplete Landing stanza, above "
        f"the ratchet of {_MAX_INCOMPLETE_LANDINGS}: "
        f"{sorted((n, sorted(m)) for n, m in incomplete)}. The stanza is the "
        "portable record of what landed; a LANDED pack missing Commits or Suite "
        "cannot be audited later. Fill it in, or lower the ratchet. Never raise it."
    )


@pytest.mark.skipif(
    not (REPO_ROOT / "task-packs" / "Done").is_dir(),
    reason="self-host only: task-packs/Done/ is gitignored -- absent in a fresh clone",
)
def test_the_advisory_ratchets_are_not_vacuous():
    # A ceiling passes trivially when the thing it counts reaches zero -- and it
    # reads that collapse as success. Both advisories are non-empty TODAY, so the
    # ratchets above are measuring a live population rather than a broken walk.
    # When either genuinely drains to zero, DELETE its ratchet rather than leaving
    # a guard that can no longer fail for the right reason.
    assert check_pack_landing.roadmap_packs(), (
        "roadmap_packs() returned nothing -- either the backlog drained (then drop "
        "_MAX_ROADMAP_IN_DONE and this arm) or the walk broke and the ceiling above "
        "is now vacuous"
    )
    assert check_pack_landing.incomplete_landings(), (
        "incomplete_landings() returned nothing -- either the backlog drained (then "
        "drop _MAX_INCOMPLETE_LANDINGS and this arm) or the walk broke"
    )


def test_pack_name_convention_boundaries():
    # The population predicate itself. `TP-233b` (letter-suffixed) is a real
    # shape in this repo, and `TP-` with no number is not a pack -- both are
    # boundary cases a `startswith("TP-")` predicate would get wrong.
    assert check_pack_landing.is_pack_file("TP-1-x.md")
    assert check_pack_landing.is_pack_file("TP-233b-x.md")
    assert not check_pack_landing.is_pack_file("TP-no-number.md")
    assert not check_pack_landing.is_pack_file("RUNBOOK_active-set_2026-07-26.md")
    assert not check_pack_landing.is_pack_file("MEMORY_archive_20260705.md")


# ---------------------------------------------------------------------------
# The Scope (out) reader and the active-pack population (TP-452 1-H): the one
# home both DEF-412a's strike guard and DEF-412e's completeness gate read.
# ---------------------------------------------------------------------------

_PACK_WITH_SCOPE_OUT = """\
# TP-997 -- example

## Scope (in)
- `DEF-1`

## Scope (out) -- deferred, with reasons
- `DEF-2` waits on the walk
### why
- because §C4 owns it

## Implementation
- `DEF-3` is done here
"""


def test_scope_out_returns_the_section_body_up_to_the_next_h2():
    body = check_pack_landing.scope_out(_PACK_WITH_SCOPE_OUT)
    assert "DEF-2" in body and "§C4" in body            # sub-headings stay inside
    assert "DEF-1" not in body and "DEF-3" not in body  # neighbours stay out


def test_scope_out_is_empty_when_the_pack_has_none():
    assert check_pack_landing.scope_out(_LANDED_PACK) == ""


def test_scope_out_admits_the_hyphen_spelling_a_landed_pack_uses():
    # TP-451 (Done/) writes `## Scope-out`; one of 221 packs, measured 2026-09-21.
    text = "# x\n\n## Scope-out\n- `DEF-8` parked\n\n## Scope (outline)\n- not this\n"
    assert check_pack_landing.scope_out(text).strip() == "- `DEF-8` parked"
    assert check_pack_landing.scope_out("# x\n\n## Scope (outline)\n- no\n") == ""


def test_scope_out_does_not_key_on_a_prose_mention():
    text = "# x\n\nsee the Scope (out) section below\n\n## Scope (out)\n- `DEF-9`\n"
    assert check_pack_landing.scope_out(text).strip() == "- `DEF-9`"


def test_scope_out_is_fence_blind_in_both_directions():
    # A fenced shell comment is not a heading (it must not end the section) and
    # a fenced heading is not the section (code review, 2026-09-21; both latent).
    body_with_fence = "# x\n\n## Scope (out)\n```bash\n# a shell comment\n```\n- deferred `DEF-9`\n\n## Next\n- `DEF-8`\n"
    got = check_pack_landing.scope_out(body_with_fence)
    assert "DEF-9" in got and "DEF-8" not in got and "shell comment" not in got
    fenced_heading = "# x\n\n```md\n## Scope (out)\n- `DEF-7` (a quoted template)\n```\n\n## Scope (out)\n- `DEF-9`\n"
    assert check_pack_landing.scope_out(fenced_heading).strip() == "- `DEF-9`"


def test_scope_out_reads_every_heading_and_its_spans_index_the_original_text():
    text = "# x\n\n## Scope (out)\n- `DEF-1`\n\n## Mid\n\n## Scope (out)\n- `DEF-2`\n"
    got = check_pack_landing.scope_out(text)
    assert "DEF-1" in got and "DEF-2" in got
    spans = check_pack_landing.scope_out_spans(text)
    assert [text[s:e].strip() for s, e in spans] == ["- `DEF-1`", "- `DEF-2`"]
    assert [text[:s].count("\n") + 1 for s, _ in spans] == [4, 9]


def test_active_pack_dirs_are_the_root_and_every_non_terminal_folder(tmp_path: Path):
    dirs = check_pack_landing.active_pack_dirs(tmp_path)
    assert dirs[0] == tmp_path
    assert [d.name for d in dirs[1:]] == list(check_pack_landing.NON_TERMINAL_DIRS)
    for terminal in (*check_pack_landing.TERMINAL_DIRS, *check_pack_landing.UNSTAMPABLE_DIRS):
        assert tmp_path / terminal not in dirs


def test_pack_files_is_tolerant_of_the_off_convention_shapes_and_absent_folders(tmp_path: Path):
    # The TP-372 lesson: a glob("TP-*.md") let `tp-999.markdown` escape the
    # orphan guard; the shared reader admits both spellings, skips non-packs
    # and treats an absent folder as an empty population.
    (tmp_path / "TP-1-a.md").write_text("x", encoding="utf-8")
    (tmp_path / "tp-2-b.markdown").write_text("x", encoding="utf-8")
    (tmp_path / "FORWARD_LEDGER.md").write_text("x", encoding="utf-8")
    (tmp_path / "TP-3-dir.md").mkdir()
    found = check_pack_landing.pack_files((tmp_path, tmp_path / "Deferred"))
    assert [p.name for p in found] == ["TP-1-a.md", "tp-2-b.markdown"]


# --------------------------------------------------------------------------
# THE REPORT SAYS WHAT IT SCANNED (DEF-858). `Done/` and `Scrapped/` are
# local-only; on a public checkout every walk above runs over nothing, and the
# all-clear line printed the same as on a tree with 148 stamped packs. A ledger
# probe shelling out to this script read that as "chore drained" and graded two
# live rows STRIKE_CANDIDATE (measured 2026-09-22 in a --shared clone without
# Done/). The shape adopted is sister_site_probe's SCANNED NOTHING: loud, the
# remedy named, the exit code unchanged -- never a false red on a checkout that
# lacks a folder it cannot carry.
# --------------------------------------------------------------------------

def _root_with(tmp_path: Path, done: dict[str, str] | None,
               scrapped: dict[str, str] | None = None) -> Path:
    packs = tmp_path / "task-packs"
    packs.mkdir()
    (packs / "TP-1-root.md").write_text(_DRAFT_PACK, encoding="utf-8")
    for folder, files in (("Done", done), ("Scrapped", scrapped)):
        if files is None:
            continue
        (packs / folder).mkdir()
        for name, text in files.items():
            (packs / folder / name).write_text(text, encoding="utf-8")
    return packs


def _drive_main(monkeypatch, capsys, packs: Path, *argv: str) -> tuple[int, str]:
    # `main` reads the module global at call time and passes it down explicitly
    # (its own comment: a def-time default would answer about the real tree).
    monkeypatch.setattr(check_pack_landing, "PACKS_ROOT", packs)
    rc = check_pack_landing.main(list(argv))
    return rc, capsys.readouterr().out


def test_main_says_scanned_nothing_and_withholds_the_all_clear_on_an_absent_population(
    tmp_path: Path, monkeypatch, capsys,
):
    packs = _root_with(tmp_path, done=None)          # the public checkout: no Done/, no Scrapped/
    rc, out = _drive_main(monkeypatch, capsys, packs)
    assert rc == 0
    assert "SCOPE -- 0 pack(s) under task-packs/Done/, 0 pack(s) under task-packs/Scrapped/" in out
    assert "SCANNED NOTHING" in out and "says nothing about the landed packs" in out
    # two predicates, two lines: the terminal-State check over every terminal
    # folder, and the two Done/-only tiers for themselves
    assert "terminal-State check ran over an empty population" in out
    assert "task-packs/Done/ holds no pack" in out
    assert "carry a terminal State" not in out, "the all-clear printed over an empty walk"
    assert out.isascii(), "rendered output must be 7-bit ASCII (a Windows console reads it)"


def test_the_exit_code_does_not_move_on_an_empty_population_even_under_strict(
    tmp_path: Path, monkeypatch, capsys,
):
    # A red on every checkout that lacks a local-only folder is the permanently-
    # red advisory this script was rescued from (its docstring); the LINE carries
    # the fact, the exit code stays the advisory it was.
    packs = _root_with(tmp_path, done=None)
    rc, out = _drive_main(monkeypatch, capsys, packs, "--strict")
    assert rc == 0 and "SCANNED NOTHING" in out


def test_an_existing_but_packless_folder_is_scanned_nothing_too(tmp_path: Path, monkeypatch, capsys):
    # The population is PACKS, not files: a Done/ holding only a runbook is empty.
    packs = _root_with(tmp_path, done={"RUNBOOK_x.md": "# not a pack\n"})
    rc, out = _drive_main(monkeypatch, capsys, packs)
    assert rc == 0 and "SCANNED NOTHING" in out and "carry a terminal State" not in out
    assert "task-packs/Done/ holds no pack" in out


def test_the_done_tiers_say_scanned_nothing_when_only_scrapped_holds_a_pack(
    tmp_path: Path, monkeypatch, capsys,
):
    # The terminal-State check ran over one pack, so its all-clear is honest;
    # the ROADMAP and incomplete-Landing tiers read Done/ ALONE and walked
    # nothing -- and the ledger probe greps their two headings (both reviewers,
    # 2026-09-22). Two predicates, two lines: the top-level marker stays silent,
    # the tiers' own marker fires.
    packs = _root_with(
        tmp_path, done={}, scrapped={"TP-3-b.md": _LANDED_PACK.replace("LANDED", "SCRAPPED")},
    )
    rc, out = _drive_main(monkeypatch, capsys, packs)
    assert rc == 0
    assert "SCOPE -- 0 pack(s) under task-packs/Done/, 1 pack(s) under task-packs/Scrapped/" in out
    assert "carry a terminal State" in out
    assert "terminal-State check ran over an empty population" not in out
    assert "task-packs/Done/ holds no pack" in out


def test_main_counts_the_population_it_scanned_and_gives_the_all_clear_over_a_real_one(
    tmp_path: Path, monkeypatch, capsys,
):
    packs = _root_with(
        tmp_path,
        done={"TP-2-a.md": _LANDED_PACK, "RUNBOOK_x.md": "# no\n"},
        scrapped={"TP-3-b.md": _LANDED_PACK.replace("LANDED", "SCRAPPED")},
    )
    rc, out = _drive_main(monkeypatch, capsys, packs)
    assert rc == 0
    assert "SCOPE -- 1 pack(s) under task-packs/Done/, 1 pack(s) under task-packs/Scrapped/" in out
    assert "SCANNED NOTHING" not in out
    assert "carry a terminal State" in out


def test_terminal_packs_is_the_one_population_the_three_done_readers_share(tmp_path: Path):
    # The SCOPE count must be what the checks saw: an unstamped pack, a ROADMAP
    # and an incomplete LANDED stanza are each one member of terminal_packs, a
    # non-pack file is none of them, and an absent folder is an empty population.
    done = tmp_path / "Done"
    done.mkdir()
    (done / "TP-1-unstamped.md").write_text(_DRAFT_PACK, encoding="utf-8")
    (done / "TP-2-roadmap.md").write_text(_LANDED_PACK.replace("LANDED", "ROADMAP"), encoding="utf-8")
    (done / "TP-3-incomplete.md").write_text(_LANDED_PACK, encoding="utf-8")   # no Suite: line
    (done / "RUNBOOK_x.md").write_text("# no\n", encoding="utf-8")
    # the off-convention spellings `pack_files` admits for the orphan guard are
    # NOT this population (the docstring's "deliberately not pack_files")
    (done / "tp-9-x.markdown").write_text(_LANDED_PACK, encoding="utf-8")
    (done / "TP-10.md").write_text(_LANDED_PACK, encoding="utf-8")
    assert [p.name for p in check_pack_landing.terminal_packs(done)] == [
        "TP-1-unstamped.md", "TP-2-roadmap.md", "TP-3-incomplete.md",
    ]
    assert [n for n, _ in check_pack_landing.unstamped_packs(done)] == ["TP-1-unstamped.md"]
    assert check_pack_landing.roadmap_packs(done) == ["TP-2-roadmap.md"]
    assert [n for n, _ in check_pack_landing.incomplete_landings(done)] == ["TP-3-incomplete.md"]
    assert check_pack_landing.terminal_packs(tmp_path / "absent") == []
