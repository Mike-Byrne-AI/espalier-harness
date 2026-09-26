#!/usr/bin/env python3
"""Enumerate test populations that derive from the source they police.

`docs/FAILURE_MODES.md` §18.4: a test whose *population* is derived from the
constant under test enrols an addition and is **structurally blind to a
deletion** — the population shrinks in lockstep with the thing it was meant to
police, and the suite still reports green with a smaller row count nobody reads
as a failure.

This script is the standing enumerator for that shape. It replaces a one-time
census that recorded a bare count and no roster — which could not be reconciled
by the next reader, because a number is not a population.

WHAT IT EMITS: candidates. Never a verdict.
------------------------------------------
Deriving a population is not itself a defect. §18.4's discriminator is
*semantic*, and no AST shape distinguishes the two sides:

    CORRECT  the property is "everything present is safe" — a budget, a
             ceiling, a ReDoS bound. A shrunken population makes a smaller
             claim, and the smaller claim is still true.
    DEFECT   the property is "everything required is present" — a coverage
             floor. A shrunken population silently retires the requirement.

`tests/test_redos.py` deriving from `_CMD_POS_WRAPPER` is CORRECT and is
shape-identical to the defective sites. So this script deliberately stops at
enumeration: a probe that printed "DEFECT" on a shape match would manufacture
exactly the false confidence this class is made of.

WHY IT LOOKS AT FIVE SHAPES
---------------------------
The original census keyed on one shape — a `for` loop with an assert in its
body — and thereby under-counted its own class. The mechanism is
shape-independent, so this script reports each shape separately rather than
collapsing them into one number:

    parametrize   `@pytest.mark.parametrize("x", <source container>)`. THE shape
                  every filed member of this class takes (DEF-595, DEF-598,
                  DEF-599). Also resolved one hop through a module-level alias
                  (`_TEMPLATE_NAMES = list(<source>.CONST)`), which is the form
                  DEF-598 actually has.
    for-assert    a `for` loop over a source container, asserting in the body.
                  The shape the DEF-600 census filed.
    for-plain     the same loop with no assert in the body. Often feeds a later
                  assertion, so it carries the same blindness with one more hop.
    comprehension a list/set/dict/generator comprehension over a source
                  container. No rows to lose and no body to read.
    all-any       `assert all(... for x in CONST)`. The population is inside the
                  assertion itself.

⚠ `parametrize` was MISSING from the first version of this file, and the
consequence is worth recording rather than quietly repairing: the census then
returned, for both subject files, only the lines the *fix* had just added — and
none of the lines that were the *defect*. An enumerator built for a class
inherits the class. `check_health()` now asserts the census can still see its
own filed members, which is the cheapest mechanical form of that check.

A NOTE ON HOW A CONTAINER IS FOUND
----------------------------------
`tests/CLAUDE.md` mandates that `tools/cc/` modules load via
`importlib.spec_from_file_location`, never a plain import — that keeps espalier
out of their zero-import graph. An enumerator that only understands `import`
statements is therefore blind to every hook-module population by construction,
which is how the first census lost 3 sites of its own declared shape. Bindings
produced by `module_from_spec` / `spec_from_file_location` are resolved here.

Self-host contributor tooling. Not deployed by `espalier init`. Stdlib only.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"

#: Package roots whose names count as "the subject". A container reached
#: through one of these came from the code under test; one defined in the test
#: file did not.
SOURCE_ROOTS = ("espalier", "tools", "cc")


SHAPES = ("parametrize", "for-assert", "for-plain", "comprehension", "all-any")

#: THE ADJUDICATED CENSUS, one entry per file. LITERAL, and it must stay literal.
#:
#: This replaced a `MIN_PER_SHAPE` dict of `>=` floors, which was a live member
#: of the very class this script enumerates. Measured before removal: live
#: yields sat 8 / 7 / 6 / 24 / 2 above their floors, so dropping exactly the
#: slack returned rc=0 for every shape, and draining all five silently retired
#: 47 of 207 rows -- 22.7% -- with nothing red. §18.4 retracts the `>=` floor by
#: name; the enumerator for §18.4 was built on one.
#:
#: WHY A DIGEST AND NOT A ROSTER. A hand-written roster is §18.4's attested
#: remedy and would work. It was rejected here for the reason
#: `tests/test_release_noise_parity.py` already recorded at a third of this
#: size: a roster "duplicates the data, has to move in lockstep, and its bulk is
#: what invites the regenerate-from-the-subject edit". A roster keyed on
#: `(file, shape, population)` is also WRONG here, not merely bulky: that triple
#: is NOT unique on this tree, so set-equality over it lets every duplicate row
#: be deleted in silence -- worse than the floors it replaced. No count is
#: quoted for that here on purpose; the numbers moved twice while this change
#: was being written, which is §18.1. The property is asserted instead, by
#: `TestCheckHealthEarnsItsRed::test_deleting_ONE_row_of_a_multi_row_file_reds`.
#: See `file_digest` for why the digest is over a sorted LIST.
#:
#: EACH ENTRY IS (row_count, sha256, verdict, written reason).
#: `check_health` compares both directions: an entry whose file no longer emits
#: rows reds (the population VANISHED -- the class itself), and a file emitting
#: rows with no entry reds (a NEW candidate, adjudicate it before it goes green
#: rather than in a 137-row batch two sessions later).
#:
#: ⚠ THE VERDICT VOCABULARY IS HONEST ABOUT WHAT IS NOT KNOWN. 34 of the 79
#: files carry `PRIOR_PASS_UNRECORDED` or `MIXED_WITH_PRIOR_PASS`: their rows
#: were adjudicated in the earlier parametrize/for-assert pass, which preserved
#: only an aggregate (70 of 71 CORRECT) and no per-row reason. Those codes are
#: not filler -- they are the standing work item, and they mark exactly which
#: entries a future adjudication should upgrade. Do not invent a reason to make
#: one look finished.
#:
#: ⚠ AND THE VERDICTS ARE READ-ONLY EVIDENCE, NOT PROOF. The 137 rows adjudicated
#: in the pass that built this were graded by reading and grep; NO mutation was
#: driven against any of them. A clean sweep is a null result -- evidence, not
#: permission. This map records what was judged, not that the judgement is right.
#:
#: TO UPDATE: run `--print-adjudicated-entry <file>` and paste the line it
#: prints. There is deliberately no flag that rewrites this map in place; a
#: regeneration keeps every count and runtime value identical, so no assertion
#: over VALUES can see it, and only the AST-literalness row in
#: `tests/test_derived_population_census.py` can. That row is why this comment
#: can be trusted.
ADJUDICATED: dict[str, tuple[int, str, str, str]] = {
    # 8 row(s), shapes: comprehension, for-assert
    "tests/test_cli_deploy.py": (
        8, "b740fdf1eb8f565c861769e33381037e0da8b71f1497a3465410507757d0de60",
        "MIXED",
        "Lane 6 (DEF-806). Seven rows walk `PLAN_READERS`, the engine's hand-kept "
        "pair of plan-reading cc/ docs, asserting per member that a plan writer "
        "re-rendered it, named it, or failed on it by its own path: the 18.4 "
        "shape, blind to a member dropped from the pair. Remedied in the SAME file, "
        "tests/test_cli_deploy.py:1196 "
        "(test_the_plan_reader_set_is_derived_from_the_renderers) derives the reader "
        "set from the renderers' own source (`_load_stable_actions` callers) and "
        "holds it set-equal to `PLAN_READERS` in both directions, so a dropped "
        "member reds by name there while its per-member rows vanish here; and one "
        "file over, tests/test_paths_parity.py:57 pins `REQUIRED_SURFACE_RENDERERS` "
        "set-equal to the required-init roster. The eighth row (:1210, the "
        "comprehension over `REQUIRED_SURFACE_RENDERERS.items()`) IS that remedy: "
        "it derives the ACTUAL side and asserts equality to the hand-kept pair, "
        "not a roster walked for safety.",
    ),
    # 1 row(s), shapes: for-assert
    "tests/test_fuse.py": (
        1, "c74be737a2bbe7ca99d7252188013ce5afd79ec2bd12e297f68c80c3479a5d83",
        "CORRECT_BY_REMEDY",
        "Lane 6 (DEF-806). The for-assert walks `PLAN_READERS` in the end-to-end "
        "Node-host fusion, asserting each plan-reading doc carries the post-overlay "
        "action: the 18.4 shape, blind to a member dropped from the pair. Remedied "
        "one file over: tests/test_cli_deploy.py:1196 "
        "(test_the_plan_reader_set_is_derived_from_the_renderers) holds the pair "
        "set-equal, both directions, to the set "
        "derived from the renderers' source, and guards its own derivation "
        "against emptiness, so a shrink reds there by name.",
    ),
    # 1 row(s), shapes: comprehension
    "tests/test_proofs.py": (
        1, "79257e73e45e5ab44bfb1d6d398d556a8cd5456428d20e777630ec5191cefe86",
        "CORRECT_BY_PROPERTY",
        "tests/test_proofs.py:493 (test_a_recommendation_with_no_body_is_not_warned, 2026-09-12, DEF-766) derives the bodiless optional agents from harness_config.OPTIONAL_AGENTS minus asset_inventory.packaged_agent_names(); the derived list is asserted non-empty before use (an empty one reds with a retire-this-case message) and one member is driven through run_cc_surface_gate, so a population that shrinks to nothing is loud, not green",
    ),
    "tests/test_python_floor.py": (
        1, "50f73a6fd385544587e109006590a56e98413f143e0773270d172d926b9fdb61",
        "CORRECT_BY_SHAPE",
        "Not the 18.4 shape. The row RE-DERIVES an expected value -- "
        "`floor_text()` must equal `'.'.join(str(p) for p in MIN_PYTHON)` -- "
        "rather than enumerating a roster and asserting each member is safe, so "
        "there is no population whose members could go missing unnoticed; both "
        "sides move together by construction. Honest residual, recorded rather "
        "than smoothed: an EMPTY `MIN_PYTHON` renders both sides `''` and the "
        "assertion passes vacuously. That cannot survive the sibling test in "
        "the same class, which pins the tuple against `pyproject.toml`'s "
        "`requires-python` and would red on an empty tuple.",
    ),
    # 3 row(s), shapes: comprehension
    "tests/test_analyze.py": (
        3, "b8d499b85fab155343f97288e11ed56f8a6f5487cb150aff258e0781d1db58b3",
        "MIXED_WITH_PRIOR_PASS",
        "Three rows, three verdicts (DEF-410f, 2026-09-12). (1) "
        "TestHarnessOutputPredicate._owners walks the inventory owners and each is "
        "asserted harness output -- the 18.4 shape, blind to a dropped owner -- "
        "REMEDIED in the same class: test_the_derived_tuple_is_the_set_it_was_"
        "calibrated_on pins the derived tuple to a hand-written set in BOTH "
        "directions. (2) test_every_seed_under_docs_is_markdown asserts every seed "
        "under docs/ ends in .md -- CORRECT_BY_PROPERTY: the property is that "
        "nothing present breaks the stamp assumption, a dropped seed cannot hurt "
        "it, an added non-md seed reds, and the population is asserted non-empty. "
        "(3) test_every_exemption_names_a_live_function_and_gives_a_reason builds a "
        "lookup set over the AST -- CORRECT_BY_SHAPE: an index the roster is checked "
        "against, not a population asserted member by member; the roster itself is "
        "pinned by set equality in both directions one test up.",
    ),
    # 1 row(s), shapes: for-assert
    "tests/test_bash_inert_syntax_mask.py": (
        1, "65ad236f8dbbd9941acfcfeb112f1cede3a0c7d464e18951cb75a9cc885925a7",
        "CORRECT_BY_REMEDY",
        "The for-assert walks `_READER_HEAD_SPELLINGS`, a derived roster, and "
        "asserts each spelling resolves to a reader family: the 18.4 shape, "
        "blind to a spelling dropped from the roster. Remedied one file over "
        "and at import: tests/test_guard_metamorphic.py:158 "
        "(test_every_head_has_an_explicit_spelling) pins the roster against the "
        "hand-written `_HEAD_ARGS` table in BOTH directions, and `_bash_patterns` "
        "raises at import when a spelling's family has no reader; the same "
        "test's hand-written near-miss list is the discriminating half.",
    ),
    # 11 row(s), shapes: all-any, comprehension, for-assert
    "tests/test_check_handoff_landing.py": (
        11, "6f44bf4af3af73bfef38f1af69604b30ae9fc57ae998cafadd35076852bfbc2b",
        "CORRECT_BY_PROPERTY",
        "The population is the gate's OWN OUTPUT (`problems`), not an input "
        "roster, and each case builds exactly one violation and asserts it is "
        "reported -- so a member going missing REDS, which is the direction "
        "18.4 is about. Honest residual, recorded rather than smoothed: `any()` "
        "over that output cannot see a SPURIOUS EXTRA problem, so these rows "
        "are one-directional too, just pointed the safe way. Two cases where "
        "an extra would have mattered pin exact length instead "
        "(test_an_erroring_probe_is_not_read_as_done, "
        "test_an_item_whose_probe_stopped_reporting_open_is_flagged's sibling). "
        "Not driven by mutation; graded by reading, like the rest of this map.",
    ),
    "tests/_adopter_tree.py": (
        1, "cc16f0f9163a0a3f12e837e9c8925ea47c834213163625c66ee8429956a6e52e",
        "CORRECT_BY_REMEDY",
        "tests/test_cleanup.py:348 set-equality vs a driven cmd_install_ci",
    ),
    "tests/test_action_justifications.py": (
        1, "12e5d18496750284ff049b077accb3a3f2f7d36c26f3c428f7abc84e685305de",
        "CORRECT_BY_PROPERTY",
        "no pin cited: the property is 'everything present is safe', so a smaller population makes a s...",
    ),
    "tests/test_adopter_pointer_resolution.py": (
        3, "359102dd8be9b35ffbdcab30e032122bca51f9d6137241deb69a152c80182ccc",
        "MIXED_WITH_PRIOR_PASS",
        "tests/test_managed_inventory.py:252 — `assert get_seed_docs() == (...)` against a hand-writte...",
    ),
    "tests/test_canon_verifier_contract.py": (
        4, "31db2af8c583411d205117b3e1478df6bd3d225ab7e05882b52c163ae3fce217",
        "MIXED_WITH_PRIOR_PASS",
        "per-row verdicts differ within this file; see the ledger row for DEF-600",
    ),
    "tests/test_ci_guard.py": (
        2, "1a792343675ac5f5c12ff4ec80c40e83b6ca3522919651141785df9f321e65fe",
        "MIXED_WITH_PRIOR_PASS",
        "for-assert row: the prior pass, per-row reason not preserved. comprehension "
        "row (added by DEF-605): derives the EXPECTATION from GOVERNANCE_BLOCKING_HOOKS "
        "while the SUBJECT is ci_guard's mirror -- different sources, so it is not the "
        "population-is-the-subject shape, and set-equality both directions reds on a "
        "shrink at either end",
    ),
    "tests/test_cleanup.py": (
        14, "af4119b58593643b9678e062ba0ab72b00e0b664af5ac10d506d99cf9ee87d8e",
        "MIXED_WITH_PRIOR_PASS",
        "tests/test_managed_inventory.py:252 — `assert get_seed_docs() == (...)` against a hand-writte..."
        " Grew 9 -> 13 on 2026-09-11 (§C8): four populations read from their owners, not typed --"
        " the runtime prefixes and the surface contract's runtime-generated list (each member must"
        " be nameable by local_state_on_disk), the file-shaped REQUIRED_GITIGNORE entries (same),"
        " and the managed inventory's .py files (all under the bytecode sweep root); each a"
        " for-assert over the canon, so a new member enrols itself."
        " Grew 13 -> 14 on 2026-09-15 (DEF-808): the witness map derived over"
        " REQUIRED_GITIGNORE -- one survivor planted per entry from the entry's own"
        " grammar, each kept entry must name exactly its own (a comprehension over the"
        " canon; a new entry enrols itself and reds until the guard can name what it"
        " keeps).",
    ),
    "tests/test_cli_commands.py": (
        3, "302580d087fba687aadd317785a167a07e69f8859aca5f375f37ac43fbc00a73",
        "CORRECT_BY_REMEDY",
        "hook row: tests/test_surface_contract.py:55-69 hand-written 12-name set + "
        "set-equality. The two build_parser()._actions comprehensions (DEF-772, "
        "2026-09-12) derive the listed and hidden verb sets from the parser; each "
        "is held against a population that does not come from the parser -- the "
        "hand-typed HIDDEN tuple by set-equality, and the README-derived verb "
        "set -- so a subparser that gains or loses help= reds one or the other",
    ),
    "tests/test_cognitive_blueprint_schema_parity.py": (
        4, "b0f216eca77cf0272063994d9ed507ed57a149c837c5d3727a1cc65aac11a125",
        "CORRECT_BY_SHAPE",
        "tools/cc/cognitive_blueprint.py:678 _REFLECT_PASS_FIELDS literal",
    ),
    "tests/test_command_surface_truth.py": (
        1, "e5ee93b6e57c13b271f99e66b4964218ef60f8e48fff895c88b67e9158b6421a",
        "CORRECT_BY_PROPERTY",
        "no pin cited: the property is 'everything present is safe', so a smaller population makes a s...",
    ),
    "tests/test_contract_consumers.py": (
        5, "bcad11528af813902863bdc591a3364adde2fb462074875cd6bbb7a3635f6642",
        "MIXED_WITH_PRIOR_PASS",
        "tests/test_contract_consumers.py:419 — `assert integ_hooks == self._INTEGRITY_HOOK_GOLDEN`, a...",
    ),
    "tests/test_contracts.py": (
        1, "c384d0efa18d68d0452bf91191d2fcba6616c48e00b3e12e4b4328c990bcba77",
        "CORRECT_BY_REMEDY",
        "tests/test_managed_inventory.py:252 — `assert get_seed_docs() == (...)`, a hand-written exact...",
    ),
    "tests/test_count_claims.py": (
        1, "94d051dbcf27ab1a7eb85989c25fd786fe98a8917b048161ef8c4ed2b048720b",
        "CORRECT_BY_SHAPE",
        "derives the EXPECTATION and compares it against an independently obtained actual -- the corre...",
    ),
    "tests/test_denial_reason_actionability.py": (
        9, "a890570d3679a1d1416a5adf9b0fa5d8e0f8c4a78665df37b5c5289ad73220d2",
        "MIXED_WITH_PRIOR_PASS",
        "per-row verdicts differ within this file; see the ledger row for DEF-600. "
        "Six rows walk every operator-facing template through the four "
        "actionability elements; three more (DEF-496, 2026-09-07) walk the same "
        "population for a single canonical subagent-dispatch spelling, against "
        "a roster derived from .claude/agents frontmatter -- same axis, same "
        "floor (_PINNED_REGISTRY_COUNT), a growth not a shrink; a tenth row walks "
        "every @agent- mention in the shipped docs against the same roster.",
    ),
    "tests/test_denial_reasons.py": (
        5, "d96000241e7ccb5d2123a7734feb822478811d46607fd3b176d95c47cd6c9555",
        "MIXED_WITH_PRIOR_PASS",
        "tests/test_managed_inventory.py:252 asserts `get_seed_docs() == (…)` against a hand-written 2...; "
        "the fifth row (DEF-830, 2026-09-17) is the hard-tier vocabulary set derived over "
        "`vars(_denial_reasons)` by the CATASTROPHIC_ prefix so a sixth wall's reason is enrolled "
        "the day it lands -- not blind: the five known names are asserted as its floor in the same test",
    ),
    "tests/test_deploy_set_import_closure.py": (
        2, "c07d94fe342a8f8b5c829cdb524308698c363ec88d5139db533a266d7b096409",
        "CORRECT_BY_PROPERTY",
        "tests/test_managed_inventory.py:228-241 exact tuple equality",
    ),
    "tests/test_derived_population_census.py": (
        15, "a5d03d93973730c526dd1b26e156a9b19adcb48dd4c33ab9f1d81b66f0fb8a88",
        "MIXED_WITH_PRIOR_PASS",
        "battery rows derive the MUTATION TARGET, not a coverage floor; the ADJUDICATED comprehensions...",
    ),
    "tests/test_doc_maintenance_classes.py": (
        3, "2006f95779eabefda0b19fb782eb50b087931360efd2bee0e811fad7765a6e42",
        "MIXED_WITH_PRIOR_PASS",
        "tests/test_doc_maintenance_classes.py:117 — `assert set(AUDITED_INTERNAL_DOCS) == {'docs/RELE...",
    ),
    "tests/test_doc_regions.py": (
        13, "01120d1e3dee9b232fbac2153a936c54e85fe7b1efe37d38423ad4cd9d988e71",
        "MIXED_WITH_PRIOR_PASS",
        "tests/test_doc_regions.py:421 — `assert not orphans` over every `git ls-files`-derived marker...",
    ),
    "tests/test_doctor.py": (
        7, "db6d90c67176d6075fa27e9df6409b4e9aa461f7eac7cb424ab496b6fa5fbad0",
        "MIXED_WITH_PRIOR_PASS",
        "TWO rows, adjudicated separately and deliberately not merged. (1) the "
        "for-assert over `surface_contract.get_required_init_files()` predates "
        "this entry and still carries PRIOR_PASS_UNRECORDED -- it was graded in "
        "the parametrize/for-assert pass with no per-row reason preserved, and "
        "this edit does NOT upgrade it, because nothing here re-derived it. "
        "(2) the comprehension over REQUIRED_GITIGNORE is new (2026-08-26) and "
        "is CORRECT_BY_PROPERTY: it is a FIXTURE that writes every required "
        "entry EXCEPT `.claude/settings.json`, so the one entry the test can "
        "speak about is the one git tracks. If REQUIRED_GITIGNORE grows, the "
        "fixture grows with it and still isolates exactly that path; if it "
        "shrank to nothing the test would fail its own explicit precondition "
        "(`assert \'.claude/settings.json\' in status.missing`) rather than pass "
        "on an empty population. Deriving beats hand-listing here because a "
        "typed copy would silently stop covering a newly-required entry. "
        "(3) NEW for-assert over `sorted(harness_config.GATE_SHAPES)` "
        "(test_every_shape_gets_a_doctor_next_step, 2026-08-27): "
        "CORRECT_BY_REMEDY. It is the doctor-side twin of the cli gate in "
        "tests/test_hook_event_contracts.py -- gating only one narrator is "
        "the half-swept class fix STANDING_PRINCIPLES §8 forbids. Derived "
        "rather than hand-listed for the same reason as its twin: the shapes "
        "it must cover ARE the roster, and a hand copy would become the "
        "fourth roster on this surface. Its blindness (an empty GATE_SHAPES "
        "passes vacuously) is covered by the set-equality row one file over, "
        "which reds when the constants and the roster disagree."
        "(4) TWO NEW comprehensions over `get_seed_docs()` (TestUnstampedSeedIsNamed, "
        "2026-09-05): CORRECT_BY_PROPERTY. The population IS the seed list, filtered to "
        "the files present in a copy of the real adopter tree; a shrink to nothing fails "
        "the explicit preconditions (`assert rels` and `assert 'docs/CONVENTIONS.md' in "
        "present and len(present) > 4`) rather than passing empty, and the test must "
        "follow the seed list, so a hand copy would stop covering a newly-seeded doc. "
        "(5) ONE MORE comprehension over `get_seed_docs()` (2026-09-05, DEF-696, "
        "test_each_named_seed_gets_its_own_stamp_and_no_other): CORRECT_BY_PROPERTY "
        "for the same reason as (4) -- it strips every present seed to drive the "
        "three-name cap, keeps the `len(present) > 4` floor, and the property it "
        "checks (the three stamps printed are exactly the three names, in order) "
        "does not weaken on a smaller seed list above that floor. "
        "(6) a generator over `managed_inventory.get_seed_docs()` (2026-09-05, DEF-696, "
        "test_an_unreadable_packaged_copy_is_named_without_a_stamp, mixed case): "
        "CORRECT_BY_SHAPE -- it is a SELECTOR (`next(r for r in ... if r != rel and "
        "present)`) that picks one other seed to strip, not a population any assertion "
        "ranges over; a seed list shrunk to one entry makes `next()` raise "
        "StopIteration and the test ERRORS rather than passing vacuously. ",
    ),
    "tests/test_symbol_census.py": (
        2, "9499586d33ba6491ae8b4c1806e68438918e71f9857bff2a90c30e48e9b79238",
        "CORRECT_BY_PROPERTY",
        "Two comprehensions over `mirror_registry.MIRROR_ROWS` (2026-09-06): the test "
        "finds a region-only mirror row and a whole-tree row BY SHAPE (a file-path "
        "mirror with kind subset+transform; a directory prefix) rather than by name, "
        "because the census script classifies by that same shape and a hand-named row "
        "would pin a name the registry may retire. The population is the registry, "
        "which IS the canon (there is no second list to derive from); a registry with "
        "no region-only row fails the explicit `assert rows` precondition rather than "
        "passing vacuously. ",
    ),
    "tests/test_documented_claims.py": (
        1, "95f96cceb8f3971b9af4de88f0aebe173833ab8dbc15d47c1bfd4aa8b07ea952",
        "CORRECT_BY_SHAPE",
        "derives the EXPECTATION and compares it against an independently obtained actual -- the corre...",
    ),
    "tests/test_exemplar_parity.py": (
        4, "18964e09c44373cac01ebc7b9c51bc5ac6e292bd6b2de57657bb3cf149f8d89f",
        "MIXED",
        "tests/test_exemplar_parity.py:168 — `assert set(_reinject.EXEMPLAR_MAP) == expected` (hand-wr...",
    ),
    "tests/test_external_tool_contract.py": (
        2, "7aaf438edf8e1975e94235b67574de8ca4df1a9b3a42cc3ae5f218f5b02f6f6d",
        "MIXED",
        "tests/test_adopter_message_hints.py:34 — `_LOAD_BEARING_EXTERNAL_TOOLS['ruff']` KeyErrors if ...",
    ),
    # 1 row(s), shapes: for-plain
    "tests/test_final_release_matrix.py": (
        1, "030ad94261ce80ee8bb047d7c72e97c6ca019b97c7e381e143cc3a7ffe5b0d19",
        "CORRECT_BY_PROPERTY",
        "the driven strip row plants every flag in `_RELEASE_CHECK_OPT_INS` and asserts the "
        "release_check call's strip list IS that census -- the property is 'everything the "
        "census names is stripped'; an empty census would pass here vacuously and reds one "
        "file over, where tests/test_release_check.py pins the census's members and their "
        "single home",
    ),
    "tests/test_finding_ledger.py": (
        1, "b683fade80ddbd7471e2590d3c9bf4498de2f81ab2bd49766e7d256a451cd57d",
        "CORRECT_BY_PROPERTY",
        "no pin cited: the property is 'everything present is safe', so a smaller population makes a s...",
    ),
    "tests/test_forced_copy_parity.py": (
        2, "5152aa6464d07a0aa5b3a7984b22f04af2b16a52341d4799c1ccf13fccb3b619",
        "CORRECT_BY_SHAPE",
        "derives the EXPECTATION and compares it against an independently obtained actual -- the corre...",
    ),
    "tests/test_hook_authoring_skill_parity.py": (
        3, "c506c8d29657aac4b748beb2c69adf326c6cc6d7d1835428f8bcd83602f534b1",
        "CORRECT_BY_REMEDY",
        "tests/test_harness_config.py:389 (driven: 11 vs 12 reds)",
    ),
    "tests/test_hook_contracts.py": (
        2, "03425d8a3f7b3941d98fd4dff3c91da5fc38d0d8fcf461732cf701dea33b814e",
        "CORRECT_BY_REMEDY",
        "tests/test_surface_contract.py:69 — `assert set(sc.get_canonical_hook_scripts()) == expected`...",
    ),
    "tests/test_hook_event_contracts.py": (
        8, "6d283ac1ba6145dac1006e285fa52256254a404e590e87b062b27934a75f4529",
        "MIXED_WITH_PRIOR_PASS",
        "for-assert GOVERNANCE_BLOCKING_HOOKS.items(): prior pass, reason not "
        "preserved. comprehension vars(hc).items() (TestGateShapeRoster): "
        "CORRECT_BY_REMEDY -- set-equality against the hand-written "
        "harness_config.GATE_SHAPES literal, so a derivation that stops seeing "
        "the GATE_* constants reds on the equality instead of narrowing quietly. "
        "NEW for-assert sorted(hc.GATE_SHAPES) "
        "(test_every_shape_in_the_roster_is_actually_narrated): "
        "CORRECT_BY_REMEDY -- it iterates the SAME roster the sibling row pins "
        "by set-equality, so a narrowed GATE_SHAPES cannot quietly shrink this "
        "loop without reddening that row first. Deliberately derived rather "
        "than hand-listed: the shapes it must cover are exactly the roster's "
        "members, and a hand copy is the third roster this file exists to "
        "prevent. Its own blindness (an EMPTY GATE_SHAPES would vacuously pass) "
        "is covered by the same equality row, which reds when the constants and "
        "the roster disagree. NEW (DEF-619) for-assert "
        "GOVERNANCE_REPORTER_HOOKS.items(), two more "
        "GOVERNANCE_BLOCKING_HOOKS.items() and CANONICAL_HOOK_WIRING.items(): "
        "RELATION pins (the two tiers partition CHW; the blocking tier stays "
        "readable by ci_guard's twin; every matcher token has a probe shape) "
        "over populations whose SIZE is pinned one test up by the 4-literal "
        "set-equality, so a narrowing reds there before these could narrow "
        "with it. NEW (DEF-618) for-assert sorted(cli._REPAIR_HANDLED_SHAPES): "
        "CORRECT_BY_REMEDY -- the set it iterates is pinned by union-equality "
        "against GATE_SHAPES in the sibling row, so it cannot shrink quietly.",
    ),
    "tests/test_hook_matcher_precision.py": (
        1, "02d37dca769df4fd6851f18c93ad69b0baf95ad37956954d2e0a03ad435f7604",
        "CORRECT_BY_PROPERTY",
        "no pin cited: the property is 'everything present is safe', so a smaller population makes a s...",
    ),
    "tests/test_hook_unicode_stdin.py": (
        3, "a361694ee78a541b415ec5b62dc977c7c6696e5b82afdd6d669e696721259f9a",
        "PRIOR_PASS_UNRECORDED",
        "adjudicated in the parametrize/for-assert pass; per-row reason not preserved",
    ),
    "tests/test_hook_utils.py": (
        1, "37bedf36f74335da3a86c0ce499d39612e7a8c2100962ebe36678a23a23acbf9",
        "PRIOR_PASS_UNRECORDED",
        "adjudicated in the parametrize/for-assert pass; per-row reason not preserved",
    ),
    "tests/test_hooks.py": (
        5, "005bbddbc900c550d48bcfdb0016d4b463a6545ee0e93786a6a96b198b8f9d6e",
        "MIXED_WITH_PRIOR_PASS",
        "per-row verdicts differ within this file; see the ledger row for DEF-600",
    ),
    "tests/test_implement_pack_step_zero.py": (
        4, "bdcf38049c1482b27f8458bc21de1e5e77560677cf56165c7baede28f28a0574",
        "MIXED",
        "was 3 NOT_A_MEMBER (census mis-read: those containers are not derived "
        "from the subject); +1 GROWTH adjudicated by hand 2026-09-05 -- the added "
        "row derives `labels` from sister_site_probe.BLOCKING_LABELS to assert the "
        "0-C body names every blocking kind the probe gates on (DEF-673). Worth "
        "having: the exit table had omitted constant cliques and an adopter could "
        "not map rc=2 to any listed cause. CORRECT_BY_REMEDY: `len(labels) >= 4` "
        "floors it, so a shrunken tuple reds instead of narrowing the check. Not "
        "pinned elsewhere.",
    ),
    "tests/test_init.py": (
        10, "a15e3c7f3cda7d4178789253a79c870fe6cd95a3ebb241506c0f21e84c7ab103",
        "MIXED_WITH_PRIOR_PASS",
        "per-row verdicts differ within this file; see the ledger row for DEF-600",
    ),
    "tests/test_init_fresh_hooks.py": (
        3, "b9655af640ef6d0ccb7eff594d13a632acd44af44fb156d2b9a588931e7ee8cc",
        "MIXED",
        "tests/test_deploy_set_import_closure.py:166 — `assert not violations`; closure_violations fla...",
    ),
    "tests/test_init_gitignore_default.py": (
        5, "0edefc2d006c74addabcd1157ec4d727fde75a29b5cebe0ab15f599d06f0b584",
        "MIXED_WITH_PRIOR_PASS",
        "DEF-635 added two rows over REQUIRED_GITIGNORE: test_every_required_entry_covers_its_own_probes (for-assert + comprehension) writes each entry ALONE and asserts the git oracle covers exactly it -- the shape-coverage guard for _entry_probe_paths, blind to nothing in the tuple by construction, and not pinned elsewhere. Earlier: tests/test_init_gitignore_default.py:58 and tests/test_init_gitignore_protection.py:52 — both...",
    ),
    # 1 row(s), shapes: comprehension
    "tests/test_init_upgrade_paths.py": (
        1, "11e768dbf628443658ea8c709b33a2158ec96f7c0773349b3daa2fd09bfb2aa5",
        "CORRECT_BY_PROPERTY",
        "picks ONE seed from get_seed_docs() to age (DEF-774, 2026-09-12); the "
        "assertion is about that seed by name in the upgrade preview and after "
        "--execute, and an empty population raises StopIteration in the fixture "
        "rather than passing -- the derivation exists so the aged path cannot "
        "go stale when the seed set changes, not to enumerate it",
    ),
    "tests/test_integrity.py": (
        1, "c6eccad6191ad12b2c2932344dd64d3dbd00abca8fc94c3b296f41f114e864be",
        "CORRECT_BY_REMEDY",
        "tests/test_integrity_contract_parity.py:47 asserts set(MANIFEST_FILES) == set(surface_contrac...",
    ),
    "tests/test_integrity_contract_parity.py": (
        2, "f6b82bf8b2f6a1d07921232e8cbf73a92d7009de3d4ecb4efed728fe20d8d7ff",
        "MIXED_WITH_PRIOR_PASS",
        "per-row verdicts differ within this file; see the ledger row for DEF-600",
    ),
    "tests/test_lifecycle_parity.py": (
        3, "b9655af640ef6d0ccb7eff594d13a632acd44af44fb156d2b9a588931e7ee8cc",
        "CORRECT_BY_PROPERTY",
        "no pin cited: the property is 'everything present is safe', so a smaller population makes a s...",
    ),
    "tests/test_managed_inventory.py": (
        7, "6647aaaa737042dfeaf27b2b6d6301c972600dbfe3f5772e7a43996e88aa26b2",
        "MIXED_WITH_PRIOR_PASS",
        "tests/test_managed_inventory.py:252 — `assert get_seed_docs() == (…20 hand-typed paths…)`; th... "
        "PLUS (2026-09-05, DEF-696) two rows in TestSeedStampRenderParity iterating "
        "`get_seed_docs()`: the render-parity oracle (every seed's on-disk first line on "
        "the driven adopter tree equals the rendered stamp) and the ASCII/regex row. "
        "CORRECT_BY_PROPERTY with a floor: the parity row asserts BOTH tiers are in the "
        "population before iterating (`tiers == {True, False}`), so a seed list shrunk to "
        "one tier fails the precondition rather than passing with the header branch "
        "unproven; and the population must be the seed list, because the claim is 'for "
        "every seed init deploys', not 'for these twenty' -- the hand-typed tuple at :252 "
        "one class up is the deletion guard for the list itself. ",
    ),
    "tests/test_managed_paths.py": (
        2, "3ddecd462f189a35e27aa7c406ee240f6e4ab4a5d89abcf9551bca979159b672",
        "MIXED_WITH_PRIOR_PASS",
        "row 1 (canonical hooks from the contract) adjudicated in the "
        "parametrize/for-assert pass, per-row reason not preserved. Row 2 "
        "(2026-09-11, `for kind in surface_contract.CLAUDE_SURFACE_KINDS` in "
        "test_self_host_contains_every_installed_claude_kind) derives the "
        "population from the owner under test, so a kind dropped from the owner "
        "narrows it silently; the removal direction is closed in the SAME file by "
        "test_fallback_names_every_claude_file_the_deploy_writes, which asserts the "
        "owner set-EQUAL to the kinds cli._packaged_md_assets writes -- an "
        "independent enumerator -- so a kind the deploy still writes and the owner "
        "dropped reds there.",
    ),
    "tests/test_manifest_truth.py": (
        1, "e16163c3a1510d8b34bac4ba84b74c59979ae987d0f14ffffcb4902f135f62e6",
        "PRIOR_PASS_UNRECORDED",
        "adjudicated in the parametrize/for-assert pass; per-row reason not preserved",
    ),
    "tests/test_init_interactive_arming.py": (
        1, "66aa6484a2c5d46883914c9aaf6c1f3ba6035da957670ed8a9654d4a47af37ef",
        "CORRECT_BY_PROPERTY",
        "a FIXTURE deployer, added 2026-08-27 to make this file's arming "
        "assertions describe their OWN tree. Before it, the fixture wrote "
        "settings under tmp_path while passing repo_root=REPO_ROOT, so the "
        "armament check read the HARNESS REPO'S own .claude/settings.json "
        "and `settings_hooks_wired is True` reported that this repo is "
        "healthy -- it would have passed with the fixture wiring nothing. "
        "Deriving the stub tree from INIT_HOOK_SCRIPTS rather than hand-"
        "listing is deliberate: the predicate under test derives its own "
        "population from the written settings, so the two lists are "
        "obtained independently and a divergence REDS the arming row "
        "(driven: remove the stub tree and test_interactive_yes_arms "
        "fails) instead of passing on a smaller population.",
    ),
    "tests/test_merge_settings.py": (
        4, "a79835dcba577a16b738f1f842a19b679056ce30abd95416a1ececea72d3fd3c",
        "MIXED",
        "FOUR rows. (1)+(2), unchanged from the 2-row entry, CORRECT_BY_PROPERTY: "
        "the row is a FIXTURE, not a coverage claim: it walks INIT_HOOK_SCRIPTS "
        "to CREATE the deployed hook tree that the harness-present control for "
        "DEF-427 needs to exist. The assertion it serves is about the message "
        "`merge-settings` prints, and the predicate under test derives its own "
        "population from the WIRED SETTINGS rather than from this list. So the "
        "two populations are obtained independently, and any divergence between "
        "them REDS the control -- the enforcement claim stops appearing -- "
        "rather than passing on a smaller population. Deriving here instead of "
        "hand-listing the twelve paths is the point: a hand-written copy would "
        "silently stop covering a newly-deployed hook. "
        "GREW 1 -> 2 on 2026-08-27, adjudicated by hand rather than "
        "regenerated: the second row is the identical shape in "
        "`TestEnforcementClaimBlockersComposeThreeOracles._deploy_hooks`, "
        "serving the union-oracle matrix. Same property holds -- the "
        "oracle under test reads the WIRTTEN SETTINGS, so a shrink in "
        "INIT_HOOK_SCRIPTS reds the healthy-tree row instead of "
        "quietly narrowing it."
        " (3) NEW for-assert over `cli.MERGE_REFUSAL_KINDS` "
        "(TestNoOfferSiteNamesAMergeThatRefuses::test_every_verdict_kind_has_its_own_sentence, "
        "2026-09-07, DEF-700): CORRECT_BY_REMEDY. The population IS the renderer's "
        "verdict roster, so a hand copy would become a second roster; its blindness "
        "(a kind deleted from the tuple while the predicate still emits it passes on a "
        "smaller population) is closed two ways: a typed floor in the test "
        "(`len(cli.MERGE_REFUSAL_KINDS) == 6`) reds in-file, and the driven file-shape "
        "matrix one file over (tests/test_doctor.py::TestMergeOfferOnAFileTheMergeCannotRead, "
        "EXPECTED_SENTENCE) reds when any real verdict falls to the renderer's fallback."
        " (4) NEW comprehension over `CANONICAL_HOOK_WIRING` "
        "(TestEnforcementClaimBlockersComposeThreeOracles::"
        "test_an_interpreter_that_is_not_python_3_is_caught_by_the_identity_arm, "
        "2026-09-10, DEF-727): CORRECT_BY_PROPERTY. The assertion is that the "
        "identity arm names EVERY hook wired through a word that is not a Python 3, "
        "and the wired population IS the canonical wiring the merge wrote from, so "
        "the roster is the right derivation and a hand copy would be a second roster. "
        "The blindness (a hook dropped from the roster narrows both sides together) "
        "is not this test's claim -- the roster's SIZE is pinned one file over by "
        "`tests/_surface_expected.py::EXPECTED_HOOK_ENTRY_COUNT` and "
        "tests/test_agent_contracts.py's `len(CANONICAL_HOOK_WIRING)` row, which red "
        "on a shrink before this test could pass on one.",
    ),
    "tests/test_memory_autoprune.py": (
        3, "306a58d755d2e43a831420d9b8cb669659439ff218d1ec669ee38d6874e8da53",
        "CORRECT_BY_PROPERTY",
        "all three rows are the same shape and the same argument. The sum over "
        "`_memory_section_lines(...)` is compared against a quantity "
        "the census does not produce -- `len(text.splitlines())` off the fixture "
        "text -- so a census that returns fewer sections, or none, FAILS rather "
        "than passing on a smaller population. The companion assertion in the same "
        "class is built the other way round on purpose: its fixture makes a "
        "NON-Session-Log section the fat one, so a handler that answered "
        "'Session Log' for everything cannot satisfy it.",
    ),
    "tests/test_operator_docs.py": (
        1, "dfa914b71f041c6eb47e9ef8f4261b2907b7b3e1a51fbd8bbd0aacca6538afac",
        "CORRECT_BY_PROPERTY",
        "2 -> 1 on 2026-09-22, and NOT a shrink of the gate: TestDocIndexCompleteness stopped deriving from get_indexed_doc_relpaths() (ten of thirty-one public docs) and now derives from git ls-files docs/*.md filtered by classify_release_path, a WIDER population the census's shapes do not read; the remaining row is TestIndexedDocsAreShippable's, whose property is 'everything present is safe' (a smaller population is a safe error); the widened gate carries its own must-trip twin (an unlinked doc is named).",
    ),
    "tests/test_pack_manifest.py": (
        2, "20ef9327c9c4e2387fd8dc2e45dc152502b86cee9d75e481fb6627dc02e2eb66",
        "CORRECT_BY_REMEDY",
        "tests/test_check_pack_landing.py:207-209 exact literal (driven)",
    ),
    "tests/test_package_resource_parity.py": (
        2, "16ed099057b04295dbf4a95d7fb2a37c71cbc55559e662991e0bae4f8f8d736f",
        "MIXED",
        "tests/test_package_resource_parity.py:219 (test_asset_claude_mirrors_dogfooding) and :158 (te... | :349 (TestPackagedAgentNames, 2026-09-12, DEF-766) CORRECT_BY_PROPERTY: the expected names are derived from the same packaged agent paths the SUT reads -- a pin of the normalisation shape, not of the population -- and the population is asserted non-empty and flat .md leaves in the case before it, with one literal member (code-reviewer) anchored",
    ),
    "tests/test_plan_guard_adopter_config.py": (
        1, "cc092d700c29431a826c8bbf384840adfe15da5f1fa4d113e6dcccada2d74ea0",
        "CORRECT_BY_PROPERTY",
        "no pin cited: the property is 'everything present is safe', so a smaller population makes a s...",
    ),
    "tests/test_pre_release.py": (
        2, "311bba6276361968cfe4e428db0b9940fd559fcbb534aa2707cbe060818ee734",
        "CORRECT_BY_PROPERTY",
        "no pin cited: the property is 'everything present is safe', so a smaller population makes a s...",
    ),
    "tests/test_protected_path_contract_parity.py": (
        4, "655c863c6fda1df764a7b48135b8c1a92c79938ae030a7d17b20678767275993",
        "CORRECT_BY_SHAPE",
        "renders the EXPECTED block from the tuples and byte-compares it against doc text it does not own"
        " -- a narrowed tuple mismatches the unchanged docs instead of shrinking alongside them",
    ),
    "tests/test_record_axis_reconciliation.py": (
        7, "c9f2a7dc1b7437db793c03a07847de9e397ef7e82fe4adeeddadbd5ed3446576",
        "MIXED",
        "tests/test_documented_claims.py:1714-1726 — `accounted = set(EXPECTED_MEMORY_CAP_SITES) | glo...",
    ),
    # 2 row(s), shapes: comprehension
    "tests/test_redos.py": (
        2, "f57251382881438681f269356df68a33007c47f7dc12e6992a270af2274a86e4",
        "CORRECT_BY_SHAPE",
        "two keyed next() on literal pids (the mixed record at module level, the prefix "
        "record inside the DEF-822 forward pin); each fails closed at import or at the "
        "first call if its pid leaves DANGEROUS_PS_PATTERNS",
    ),
    # 2 row(s), shapes: for-assert, parametrize
    "tests/test_reflect_memory_candidates.py": (
        2, "ca641076cb3a371335d9140588d9e998e524cffdbac4e86dad5956449797207f",
        "CORRECT_BY_PROPERTY",
        "Both rows iterate `RESOLVED_DISPOSITIONS`, the enumeration the hold "
        "retirement and the skip-rate READ, so the population is the mutation "
        "target itself: a decision added later is covered without enrolment "
        "(one row proves it retires a held candidate, the other that the "
        "SKILL names it). The blind direction -- a member REMOVED shrinks both "
        "rows silently -- is closed by the literal sibling one test over, "
        "`test_resolved_dispositions_are_exactly_the_three_decisions`, which "
        "pins the set by value and pins `held` OUT of it. Adjudicated "
        "2026-09-05 with the `held` disposition (DEF-685).",
    ),
    # 2 row(s), shapes: comprehension, for-assert
    "tests/test_recall.py": (
        2, "8413df67ce34ac2eb667bc5d2d9aec7b064e81a1a4ddd4dccdd9cd87b3f34601",
        "CORRECT_BY_PROPERTY",
        "NEW 2026-09-12 (the recall lane, DEF-775/DEF-699). The for-assert walks "
        "`_recall.PULL_EXCLUDED_MEMORY_NOTES` asserting each excluded name exists on "
        "disk under exactly that spelling and is absent from the pull corpus -- "
        "'everything present is consistent', the §18.4 CORRECT shape. The other "
        "direction ('everything required is excluded') is not the loop's job: the "
        "comprehension DERIVES the expected record members from the canon, "
        "`espalier.claim_extractor.RECORD_SURFACES` filtered by the tier script's "
        "corpus predicate minus the one named exception (docs/FAILURE_MODES.md), and "
        "the test asserts set equality both ways -- a record surface the loader "
        "could read that is not excluded reds with the remedy named, and a note "
        "excluded as a record that the canon does not call one reds too.",
    ),
    "tests/test_reflect_protocol.py": (
        7, "50463d01a09d1dd28d03f5f27e4291e54d3b94c2a80b40008b8f906278eb0261",
        "CORRECT_BY_REMEDY",
        "GREW 1 -> 7 on 2026-09-08 (ledger §C12, the two /reflect halves aligned): "
        "the six new rows all walk the placeholder pattern twins, "
        "`_erp.PLACEHOLDER_PATTERNS` (engine) and `hook.PLACEHOLDER_RES` (hook side). "
        "Two are the parity pin TestReflectTwinParity::"
        "test_placeholder_patterns_match_pattern_for_pattern, which DERIVES both lists "
        "and holds them equal pattern-for-pattern and flag-for-flag in both directions, "
        "so an edit that narrows ONE side reds. A coordinated narrowing of both is the "
        "DEF-598 enrol-not-require shape, and the protection is on an independent axis "
        "in the same file: the other four rows are `sum(len(p.findall(text)) for p in "
        "hook.PLACEHOLDER_RES)` drives inside TestInlineCodeIsNotResidue and "
        "test_a_tilde_fence_hides_residue_on_both_halves, and the fixture tests "
        "tests/test_reflect_protocol.py:723 (TestRecordSurfacesAreNotResidueScanned::"
        "test_engine, `2 placeholder patterns in docs/draft.md` from a TODO and a brace "
        "token), tests/test_reflect_protocol.py:793 (the three-hit severity boundary) and "
        "tests/test_reflect_protocol.py:643 (prose residue still counts) run docs through "
        "both halves' real scanners and assert the exact count -- drop a pattern from "
        "both lists and those red. The "
        "prior row (for-assert over EXPECTED_REFS) is unchanged and keeps its "
        "PRIOR_PASS_UNRECORDED reason.",
    ),
    "tests/test_reflect_reasoning.py": (
        1, "0c86c38855f10d0c1fa8fe84d4ac52af3f0332e0ffb13854c5165e04c61f8ad2",
        "NOT_A_MEMBER",
        "census mis-read: the container is not derived from the subject",
    ),
    "tests/test_reinject_sync.py": (
        17, "0ca03a84ba0e51eb8bac2f4dc14cc5d11e558b247f17c70cb4b181d593ffc0bf",
        "MIXED_WITH_PRIOR_PASS",
        "tests/test_reinject_sync.py:528+:578 — len(MIRROR_ROWS) is asserted equal to the number-word ... (5) FOUR MORE rows over `_reinject.REINJECTS` in the priority-ladder test (2026-09-06): the once-per-session <-> cap_exempt pairing, the rule-id charset and the case-folded uniqueness of ids. CORRECT_BY_PROPERTY: each is an invariant every registered row must satisfy (a smaller registry makes a smaller, still-true claim), and the registry cannot shrink unnoticed because the same test pins the exact priority ladder.",
    ),
    "tests/test_release_noise_parity.py": (
        2, "6a450daa35131de5202e220afa565b78e8d218792b40ca8ad1a141265626a3fb",
        "MIXED_WITH_PRIOR_PASS",
        "per-row verdicts differ within this file; see the ledger row for DEF-600",
    ),
    "tests/test_render_surface.py": (
        1, "d2b70da55c03eee145cebeba90c602f0808c471030f32003ca4546aa873430cf",
        "PRIOR_PASS_UNRECORDED",
        "adjudicated in the parametrize/for-assert pass; per-row reason not preserved",
    ),
    "tests/test_repo_mode.py": (
        2, "f32366b16c4b1865c1f018fe881c21048d2bd5b2e20f0fc833d504e6e25ddc9a",
        "CORRECT_BY_REMEDY",
        "tests/test_self_host_fingerprint_parity.py:129 — asserts `found == declared`, where `found` i...",
    ),
    "tests/test_required_status_checks.py": (
        1, "bf74b08ff18db0d1fe17783fc228874852a8d270ab26082db8946b04fd614e0f",
        "NOT_A_MEMBER",
        "census mis-read: the container is not derived from the subject",
    ),
    "tests/test_ruff_config_includes_security_rules.py": (
        1, "e6af2f0ec87e5ae2d584ebb0c83d4c02abc5e71d9d7943cbb4bf0e268ca7347e",
        "CORRECT_BY_SHAPE",
        "derives the EXPECTATION and compares it against an independently obtained actual -- the corre...",
    ),
    "tests/test_scanner_filesystem_contracts.py": (
        2, "c0592d1ed94e5273636ba7705f3d5d0a6546dbab0386d8e3c5eacf7cc7b8cc66",
        "MIXED_WITH_PRIOR_PASS",
        "per-row verdicts differ within this file; see the ledger row for DEF-600",
    ),
    "tests/test_scanner_pragma_anchoring.py": (
        1, "1c703d160048df5ad4f6599dad994b08514588bf6ece7eae37faba73ba71004a",
        "NOT_A_MEMBER",
        "census mis-read: the container is not derived from the subject",
    ),
    "tests/test_scanner_retired_vocab.py": (
        4, "7c15759b75acdc45548d176d9cdee699dfbde7c159e791bdc8e04aef5ba20850",
        "MIXED_WITH_PRIOR_PASS",
        "per-row verdicts differ within this file; see the ledger row for DEF-600. "
        "GROWTH 3->4 adjudicated 2026-08-24: the new row derives over RETIRED_TERMS "
        "to assert the mention-versus-use distinction holds for EVERY registered "
        "term rather than a sampled few. Deriving is correct here -- the backtick "
        "guard sits on the shared alternation, so a term added later inherits it "
        "and must be covered without anyone remembering to extend a list. Not "
        "blind: the same test asserts both halves (a backticked mention is allowed "
        "AND a bare label still fires), so an over-broad guard that simply stopped "
        "matching reds it. Not pinned one file over -- no sibling derives over "
        "RETIRED_TERMS for this property.",
    ),
    "tests/test_scanner_subprocess_contracts.py": (
        1, "fc5cf0549d1b1074c71cd2dfec721448a81c8195a7caf18ef9fe86582edd8ae8",
        "PRIOR_PASS_UNRECORDED",
        "adjudicated in the parametrize/for-assert pass; per-row reason not preserved",
    ),
    "tests/test_selfcheck_tests_parity.py": (
        1, "34bbac373004c27444930768869f773b2334c7b53b3870ce67ad23c70c0f38a1",
        "CORRECT_BY_REMEDY",
        "tests/test_selfcheck_tests_parity.py:55 — `assert expected == mirror` where expected = set(BY...",
    ),
    # 3 row(s), shapes: comprehension, for-assert
    "tests/test_session_banner.py": (
        6, "d90628e39fb19ceb2d55add1b8faba12784a32040abc6e8e17e9276bb5a614fb",
        "MIXED_WITH_PRIOR_PASS",
        "NEW 2026-09-12 (+3, the Loose: line, DEF-752): two for-asserts over "
        "mod._LOOSE_PREFIX_STEMS / mod._LOOSE_EXACT_STEMS in "
        "test_every_declared_stem_matches_a_fixture_row (every declared stem must "
        "catch a fixture row) and one set comprehension over "
        "mod._loose_processes(_PS_TABLE) (the fixture's parse). The two roster "
        "loops ARE the §18.4 shape -- drop `yes` from the roster and the loop "
        "shrinks with it -- so the same test pins the positives by hand "
        "(`_is_loose_stem('pythonw')`, `_is_loose_stem('yes')`) and two negatives, "
        "which red on exactly that drop: CORRECT_BY_REMEDY. The comprehension "
        "feeds those hand-written checks and is not blind. PRIOR: "
        "for-assert over mod._SOFT_BUDGETS.items(): adjudicated in the "
        "parametrize/for-assert pass; per-row reason not preserved. NEW 2026-09-04, two "
        "comprehensions over mod._hook_utils.SEEDED_PLACEHOLDER_BODIES.items() in "
        "test_placeholder_titles_match_the_seed_corpus: (a) the live body pin -- "
        "{title: flat(bodies[-1])} must equal the seed ASSET's scaffold sections, the "
        "right-hand side walked from espalier/assets/seed/*.md by sentinel, so an "
        "emptied or stale constant reds against canon, not against itself; (b) the "
        "history-length pin -- {title: len(bodies)} == a hand-pinned dict, so a body "
        "silently dropped from the append-only history reds. Worth having: the hook "
        "runs standalone and cannot read the asset, so this is the ONLY tie between "
        "the DEF-560 residual predicate and what init actually deploys. Not blind: (a) "
        "is anchored to a file the subject does not write. Not pinned elsewhere. ⚠ A "
        "first cut of this fix iterated a function-local alias and vanished from this "
        "census (DEF-684 files that blindness); rewritten to the module binding so it "
        "is adjudicated here rather than evaded.",
    ),
    "tests/test_settings_profiles.py": (
        5, "9f971b684bc67f17b6c964c03e97ad766d4469853f5a2968e203ae21b534cda2",
        "CORRECT_BY_REMEDY",
        "NEW 2026-09-03. `[r for r in deny_defaults() if "
        "r.startswith('Read(')]` in "
        "test_deny_defaults_no_longer_arms_the_read_deny_prompt. Worth having: it is "
        "the SOLE pin that a `Read()` deny rule never returns to _DENY_DEFAULTS, and "
        "its return silently re-arms Claude Code's static-resolvability permission "
        "prompt -- unsuppressable by allow rules or bypassPermissions, and measured "
        "at hours of stalled sessions. Not blind: the population is the live tuple, "
        "so a re-added rule is caught whatever it is named. Not pinned one file over "
        "-- a duplicate was written into tests/test_write_guard.py and REMOVED when "
        "this census flagged it; that file carries a pointer comment instead. The pin "
        "is tests/test_settings_profiles.py:61, and the coverage it guards moved to "
        "tools/cc/hooks/write_guard.py::check_secret_path_access. Three rows added "
        "2026-09-07 (DEF-714) walk PROFILES: two parametrize over sorted(PROFILES) "
        "for the interpreter-twin contract in both directions, one comprehension "
        "unions the rule shapes as the earn-the-gate floor. Remedy for the shrink "
        "direction: tests/test_settings_profiles.py:422 pins the pytest pair's "
        "presence per profile with literals, so deleting both spellings cannot read "
        "as symmetric."
        " Fifth row 2026-09-25: TestPowerShellTwinsFollowTheRenderHost::test_every_bash_rule_is_twinned_and_nothing_else_is parametrizes sorted(PROFILES) to pin that every Bash allow rule has its PowerShell twin and nothing else is twinned. Worth having: a Windows render with zero twins leaves the profile inert for the PowerShell tool while doctor reports nothing missing. Not blind: the population is the live tuple, so a profile added later is walked too. Not pinned one file over.",
    ),
    # 1 row(s), shapes: for-plain
    "tests/test_shipped_asset_md_refs.py": (
        1, "fc30dbb9372658e5664ecaf624372c152cd5eb564ea51b04d6c5af4ca5a188ba",
        "CORRECT_BY_REMEDY",
        "NEW 2026-09-12 (DEF-622). `for rel in managed_inventory.get_seed_docs()` "
        "in _shipped_asset_bodies derives the SCANNED population (the asset "
        "source of every seed doc, plus a glob over assets/claude/) for both the "
        "paste-the-file and the invocation gates. Worth having: it replaced "
        "`_ASSET_DIR.rglob('*.md')`, which read the maintainer folder router "
        "assets/CLAUDE.md as a shipped body. Blind in the shrink direction on its "
        "own -- a seed doc dropped from the inventory is a doc no longer scanned "
        "-- but pinned one file over: tests/test_managed_inventory.py:252 holds "
        "get_seed_docs() to a literal by set-equality, and the claude/ half is "
        "the mirror the parity tests pin. The invocation gate also carries its "
        "own vacuity floor (test_the_exec_population_is_not_vacuous).",
    ),
    # 2 row(s), shapes: comprehension
    "tests/test_sister_site_probe_adopter_tree.py": (
        2, "d8b92e9311389d4b7bbc52456b8a02a0cce46edab96e9d68ed1b5611c4296b46",
        "CORRECT_BY_REMEDY",
        "NEW 2026-09-05 (DEF-673). Two comprehensions over "
        "fusion_manifest.HARNESS_INCLUDE in test_fused_tree_gates_on_the_host_not_"
        "the_overlay: the overlaid prefixes and files, used to assert nothing the "
        "overlay wrote is in the deployed probe's gating scope on a REAL `fuse` tree. "
        "Worth having: it is the artifact-level proof of the row's own verification "
        "criterion. Not blind, because it is belt-and-braces beside an EXACT pin two "
        "asserts above it: tests/test_sister_site_probe_adopter_tree.py:128 "
        "pins `scope['scanned']` to the host's four files by equality, so a manifest "
        "shrink cannot hide a leak -- any extra file reds the equality before the "
        "derived accounting at :247 runs. Not pinned one file over: the unit "
        "parity test pins the MIRROR, this pins the CONSEQUENCE.",
    ),
    "tests/test_sister_site_probe_scope.py": (
        1, "08637fa0b02d16f8ecb3e7e98198a2a221288ef6c9cad77e05e89d37d0548520",
        "CORRECT_BY_PROPERTY",
        "no pin cited: the property is 'everything present is safe', so a smaller population makes a s...",
    ),
    # 8 row(s), shapes: comprehension, for-assert, for-plain
    "tests/test_sister_site_probe_unit.py": (
        8, "57a6a6ae2a1dfdadacc9eb5275a8ef347e20a1b2d1eecf920a7eb4cc7942daae",
        "CORRECT_BY_REMEDY",
        "NEW 2026-09-05 (DEF-673, TestFusedOverlay + TestProbeMode); was 5, +2 "
        "GROWTH the same day when the fused prune moved to the manifest's own "
        "granularity (_FUSED_OVERLAY_PATHS joined _FUSED_OVERLAY_DIRS / _FILES), "
        "+1 when the tools/ derivation went recursive (a second comprehension "
        "over _FUSED_OVERLAY_PATHS to exclude files already under a path prune). "
        "Populations: (a) fusion_manifest.HARNESS_INCLUDE (for-plain) -- every "
        ".py-bearing entry must be pruned on a fused tree, at its own granularity; "
        "(b) sister_site_probe._ENGINE_SIGNATURE (for-assert + two for-plain "
        "fixtures) -- each signature file must exist in the live package, floored "
        "by `len(_ENGINE_SIGNATURE) >= 2` so a one-module signature cannot pass as "
        "weaker-but-green; (c) the three _FUSED_OVERLAY_* sets (comprehensions) -- "
        "the REVERSE direction, every prune entry must be exactly a manifest entry "
        "or a live tools/*.py, never wider (the first cut collapsed entries to their "
        "top directory and could not see a wholesale bench/ prune hiding the host's "
        "own files). Worth having: the probe cannot import the manifest (tools/cc "
        "zero-import), so this is the ONLY tie between what fuse overlays and what "
        "the adopter walk prunes; measured before it existed, 97 of 98 'your source' "
        "files on a fused tree were Espalier's. Not blind: both directions are "
        "pinned, so a manifest shrink reds via (c) and a prune shrink via (a). The "
        "pins: tests/test_sister_site_probe_unit.py:638 (the signature floor), "
        ":668 (forward, manifest -> prune), :681 (reverse, prune -> manifest). "
        "Not pinned one file over: the real-fuse drive in "
        "tests/test_sister_site_probe_adopter_tree.py asserts the CONSEQUENCE "
        "(scanned == the host's files), not the mirror.",
    ),
    "tests/test_skill_tier_contract.py": (
        1, "95f96cceb8f3971b9af4de88f0aebe173833ab8dbc15d47c1bfd4aa8b07ea952",
        "CORRECT_BY_PROPERTY",
        "exemption set; narrowing tightens the check",
    ),
    # 1 row(s), shapes: for-assert
    "tests/test_speedbump.py": (
        1, "bd1ba5fb524c3374f64bdf2f035b4a9a514f856feaa9eaa40d0bab055e805a8d",
        "CORRECT_BY_PROPERTY",
        "ADDED 2026-09-13 (DEF-790, the group-10 failure-mode review): "
        "test_every_registry_predicate_takes_the_four_argument_call walks "
        "`_speedbump.SPEEDBUMPS` and holds every predicate to the four-argument call "
        "`check_fired` makes, outside that function's `except Exception` net (which reads "
        "a TypeError as 'does not fire', so a predicate written to the older three-argument "
        "shape would go silently dead). A property of the derived population, no hand "
        "roster: the registry is the canon and a member that stops answering reds.",
    ),
    "tests/test_speedbump_irreversible.py": (
        14, "436c0049b7ee9c5c69df80cfd76a233760c1633d76e461d3f0f5997532bc5ab9",
        "MIXED",
        "GREW 13 -> 14 on 2026-09-16 (DEF-832, the program operand as one shell word): "
        "the derived pin that every program-operand opener carries the `word` group under "
        "its declared flag regime iterates `_INLINE_PROGRAM_RES` (the inline openers' "
        "table) so a seventh opener enrols itself; the two shell openers are named beside "
        "it. "
        "was 10; +3 GROWTH adjudicated by hand 2026-09-10 (DEF-738) -- two more "
        "`SPEEDBUMPS` comprehensions (the fetch checkpoint's record-shape lookup "
        "and the derived pin on write_guard's registry-count comment) and one "
        "more `vars(_speedbump).items()` census, `_speedbump_regex_names`: EVERY "
        "compiled pattern in the module, the timing twin of the "
        "anchored-or-declared census, so a new regex is budgeted without "
        "enrolment (CORRECT under 18.4 -- the property is 'every pattern is "
        "linear at the command cap', and a shrink of the module's pattern set "
        "is caught by the `>= 16` floor beside it). "
        "was 9; +1 GROWTH adjudicated by hand 2026-09-06 (DEF-701) -- the added "
        "for-plain row `for entry in write_guard.DANGEROUS_BASH_PATTERNS` enrols "
        "the record-held anchored patterns into the newline-span census, whose "
        "property is 'everything present stops at a newline' (CORRECT under "
        "18.4); a shrink of that roster would narrow the census silently, which "
        "the census's own `>= 25` population floor is there to catch. "
        "was 8; +1 GROWTH adjudicated by hand 2026-08-24 — the added row derives "
        "`unkeyed` from `_speedbump.SPEEDBUMPS` to assert every cap_exempt "
        "checkpoint carries a flag_key (two did not, so the irreversible tier was "
        "inconsistent with itself and nothing said so). Derived, not hand-listed, "
        "so it self-enrols a new checkpoint. File stays MIXED for the pre-existing "
        "exact-set assertion at the git-regex axis.",
    ),
    "tests/test_speedbump_metacognitive.py": (
        5, "5d718547ff74de90543b152f8f1091c53dbf58bd37869e5e2438bab178a704b0",
        "MIXED_WITH_PRIOR_PASS",
        "per-row verdicts differ within this file; see the ledger row for DEF-600. "
        "was 3; +2 GROWTH adjudicated by hand 2026-08-24 for the CP-GATEWEAKEN "
        "Write arm (P5). Both new rows derive from `_speedbump._GUARD_FILES` "
        "rather than hand-listing the guard files, so a fifth guard self-enrols "
        "into the Write-arm coverage the same way it already does into the Edit "
        "arm. Derived-from-the-subject is the right shape here: the population "
        "IS the guard roster, and the assertion is per-member behaviour (does a "
        "full-file Write over this guard fire?), not a count — so a shrink "
        "cannot hide behind it the way §18.4 warns about.",
    ),
    "tests/test_speedbump_v1_1.py": (
        2, "ee9fc45dfd84f6128f9d2044204864e88b00ae7ad41702a39bd9bdda88ad88af",
        "CORRECT_BY_SHAPE",
        "derives the EXPECTATION and compares it against an independently obtained actual -- the corre...",
    ),
    "tests/test_stop_gate.py": (
        4, "312fff6c9c1c728881a1106734b131102bcc09b1a4f08dc42b1069fe85bdd288",
        "MIXED",
        "tests/test_stop_gate.py:375 — `assert result.paths == ['tests/test_fingerprint.py', 'tests/te...",
    ),
    "tests/test_stop_gate_dormancy.py": (
        1, "9711378885df4eb83b4be84955ea2f4125719f8b3724881a2c69a5fae562fbe3",
        "CORRECT_BY_REMEDY",
        "tests/test_stop_gate.py:375 — `assert result.paths == ['tests/test_fingerprint.py', 'tests/te...",
    ),
    "tests/test_surface_contract.py": (
        6, "c498531cef13df5606be4386f67c8de6d53dc428aa0193f5d8af885e4e641489",
        "CORRECT_BY_PROPERTY",
        "three rows are TestDiscoverClaudeKinds (2026-09-11): a comprehension "
        "and a for-plain over surface_contract.CLAUDE_KIND_GLOBS / "
        "CLAUDE_SURFACE_KINDS, the owner under test. Worth having: they pin the "
        "per-member property that every owned kind has a glob, is reported by the "
        "composite, and discovers a file at exactly its declared shape (the "
        "KeyError-at-the-owner contract). Blind to a REMOVED kind by construction; "
        "that direction is pinned one file over, tests/test_managed_paths.py's "
        "set-equality of the owner against cli._packaged_md_assets. Three rows are "
        "TestShippedPackBoundary (2026-09-21, the shipping-boundary lane): two "
        "comprehensions over sc.SHIPPED_PACK_DIRS derive the .gitignore "
        "re-includes the owner demands and the probe paths git is asked about, "
        "and a for-assert over sc._LOCAL_ONLY_PREFIXES pins that every prefix "
        "but the carved-out one is still a prune-dir. All are per-member "
        "properties over the owner; the absence direction (a re-include the "
        "owner does not name) is the set-equality in the same test, read from "
        "the live .gitignore, and the behavioural test asks git about strays "
        "the owner never names.",
    ),
    "tests/test_surface_impact.py": (
        2, "470f841c4113e504a757c6fa2d0adc1508a0258ed4614c0f09532cc8b24815d9",
        "MIXED_WITH_PRIOR_PASS",
        "per-row verdicts differ within this file; see the ledger row for DEF-600",
    ),
    "tests/test_surface_support_matrix.py": (
        1, "8ae56d475e01210d4884e8b48c2c1c5bfbff17850b5c9ef9513ca95330a1a6bc",
        "CORRECT_BY_PROPERTY",
        "tests/test_doc_maintenance_classes.py:117 pins set(AUDITED_INTERNAL_DOCS) == {'docs/RELEASE_C...",
    ),
    "tests/test_troubleshooting_enumerations.py": (
        1, "d99cb7764a2812e929cfd3133bafbbb3f778d44290d301b2488579fe498742a6",
        "PRIOR_PASS_UNRECORDED",
        "adjudicated in the parametrize/for-assert pass; per-row reason not preserved",
    ),
    # 1 row(s), shapes: comprehension
    "tests/test_vendor_cc_parity.py": (
        1, "662f1b34646e9793620d7fbc2e00e4eb69176fded889c9361304207e31435c61",
        "CORRECT_BY_PROPERTY",
        "a selector, not a census: `next(r for r in MIRROR_ROWS if r.name == 'vendor-cc')` "
        "picks the one row by name and errors (StopIteration) if it is gone; the assertion it "
        "feeds holds four spellings of one suffix set equal (the sync script's constant, this "
        "test's, the row's brace set, managed_paths.DEPLOYED_SCRIPT_SUFFIXES), so the property "
        "is 'everything present agrees' and no smaller population passes it silently "
        "(DEF-729, 2026-09-13).",
    ),
    "tests/test_verify_landing.py": (
        1, "bfdc7cb2bdabda780f8ae4acf2b49e92ba8e813038d39757d5aefae3d1bff12a",
        "PRIOR_PASS_UNRECORDED",
        "adjudicated in the parametrize/for-assert pass; per-row reason not preserved",
    ),
    "tests/test_version_surfaces_parity.py": (
        1, "039a67e0fc67aed3bc16722551fa1569a6f08d5a7e9cb73aa938035520eb0b23",
        "CORRECT_BY_REMEDY",
        "tests/test_version_truth.py:74 — asserts pyproject version == espalier.__version__ (imported,...",
    ),
    "tests/test_wheel_payload.py": (
        1, "11e768dbf628443658ea8c709b33a2158ec96f7c0773349b3daa2fd09bfb2aa5",
        "CORRECT_BY_PROPERTY",
        "no pin cited: the property is 'everything present is safe', so a smaller population makes a s...",
    ),
    "tests/test_wheel_smoke.py": (
        2, "06fecacb93fec888ae58d0ec05d1f5b0c0508eb91cac99e1a2ee80e1d6535d99",
        "MIXED",
        "scripts/wheel_smoke.py:443-457 — `extra_helpers = helper_names - set(EXPECTED_HOOK_HELPERS)` ...",
    ),
    "tests/test_write_guard.py": (
        24, "31e3d77685407128006c51c8e074396d1d18e57adb336f00d14a2000de22b78c",
        "CORRECT_BY_REMEDY",
        "GREW 23 -> 24 on 2026-09-19 (lane 1, the cross-shell flag): the row is "
        "`test_no_memo_can_serve_an_unflagged_answer_to_a_flagged_call`. It DERIVES every "
        "memoized function from `vars(_bash_patterns)` and pins the set EQUAL to a hand list, "
        "so a new memo reds until its author decides whether the flag joins its key; the "
        "plain-command gate `_relief_applies` joined the list the same day, its freedom from "
        "the flag pinned by `test_the_gate_reads_the_command_and_nothing_else`. "
        "GREW 20 -> 23 on 2026-09-18 (DEF-837, the word-list loop head): the three rows are "
        "one test, `test_the_loop_openers_are_one_derived_roster_loop`. It DERIVES the loop "
        "opener population from `vars(_bash_patterns)` (every compiled pattern whose source "
        "carries `_DO_BODY`) and pins it EQUAL to the hand-kept `_LOOP_OPENERS` table, so a "
        "shrink -- an opener deleted, or refactored off `_DO_BODY` -- reds against an "
        "independent list instead of narrowing in lockstep with it; the zone reader's "
        "by-name arms are pinned to cover the derived set, the half-fix the review found "
        "silent. "
        "GREW 19 -> 20 on 2026-09-16 (DEF-831, the version-control listing head): the carrier "
        "roster test derives its head population from the guard's head table "
        "(`_PIPED_ENUM_HEAD_SPELLINGS`) and pins the keys, the openers' spellings and the readers "
        "table as one set, refusing an off-table key; a head added to the table without a reader "
        "reds at import and here. "
        "GREW 18 -> 19 on 2026-09-14 (lane 2, the remove/relocate operand class): "
        "`TestRemovedOrRelocatedOperandIsAMutation` derives its deny-arm roster from the "
        "module's own consumption tables (`_MUTATION_ARMS`, `_SECRET_EFFECT_ARMS`, "
        "`_MUTATION_INNER_ARMS` -- the inner one derived from the by-name dispatch, the other "
        "two hand-written and PINNED to the readers' free names by an AST walk), pins every arm to a row and every row to an arm, and blinds "
        "each arm to prove its rows reach it; a new reader arm without a row reds there. "
        "GREW 17 -> 18 on 2026-09-14 (lane 1b, the review fix batch): the root-row pin walks "
        "the promoted probe's `ROWS` so every DEF-794 regression row names the ledger row it "
        "regresses on (a note that described the closed defect in the present tense outlived "
        "the fix); same remedy. "
        "GREW 15 -> 17 on 2026-09-14 (lane 1b, DEF-794): `TestQuotedTargetSurvivesTheRoot` "
        "DERIVES its arm roster from `vars(_bash_patterns)` (every `_CMD_POS` / `_PS_CMD_POS`-"
        "anchored pattern, floored) and drives one fixture per arm through the zone checks under "
        "a spaced and a paren project root -- the population that lives in the module it "
        "polices, which is the point: a new arm without a fixture reds there instead of "
        "shipping the class again (remedy: the fixture dict must equal the roster, "
        "tests/test_write_guard.py::TestQuotedTargetSurvivesTheRoot::test_every_arm_has_a_fixture_or_a_reason). "
        "GREW 11 -> 15 on 2026-09-14 (lane 1a, the review fix batch): the count-sentence pin "
        "derives its expected gap count over `mod.ROWS` x the shape vocabulary, and the "
        "fixture-directory pin walks `_protected_zones.PROTECTED_PREFIXES` / `PROTECTED_FILES` "
        "to require a parent for each in the throwaway project -- the canon the fixture now "
        "reads at run time (bench/powershell_guard_rehearsal.py::protected_fixture_dirs), so "
        "the test and the fixture cannot drift apart; same remedy. "
        "GREW 9 -> 11 on 2026-09-14 (lane 1a, DEF-811): `TestBenchGuardFixture` walks the two "
        "bench oracles' `KNOWN_GAPS` (every declaration must name the ledger row that retires "
        "it) and the promoted probe's `ROWS` (every row's tool namespace is one of the two "
        "shells) -- populations that live in `bench/`, not in the hook, and each already held "
        "to a shape the oracle's own run enforces (a declared gap that closes FAILS the run, "
        "bench/powershell_guard_rehearsal.py::drive; a stale declaration fails it, ::stale_declarations); "
        "same remedy. "
        "GREW 8 -> 9 on 2026-09-13 (the group-10 failure-mode review): `_anchored_records` "
        "walks write_guard's own `DANGEROUS_BASH_PATTERNS` / `DANGEROUS_PS_PATTERNS` so the "
        "two quoted-verb rosters below cover the second module the command-position canon "
        "lives in (the two literal rm backstops, the two Remove-Item records), each held to "
        "the same hand roster in both directions -- the pins' second population, same remedy. "
        "GREW 7 -> 8 on 2026-09-13 (DEF-791): "
        "TestPowerShellQuotedVerbBehindTheCallOperator::test_the_roster_is_the_modules_anchored_arms "
        "walks the same `vars(bp).items()` for every pattern anchored on `_PS_CMD_POS` -- the "
        "PowerShell twin of the DEF-410q pin one row down, same shape, same remedy (a "
        "hand-written fixture roster keyed by arm name, held equal in both directions, each "
        "fixture then driven bare and quoted behind the call operator through the real hook). "
        "The seven prior rows are unchanged and keep theirs. "
        "GREW 6 -> 7 on 2026-09-13 (DEF-410q): "
        "TestQuotedVerbTailIsUniform::test_the_roster_is_the_modules_anchored_arms walks "
        "`vars(bp).items()` for every pattern anchored on `_CMD_POS` and holds that "
        "population EQUAL to a hand-written fixture roster keyed by arm name, in both "
        "directions (a new anchored arm without a fixture reds; a fixture naming a "
        "retired arm reds), and each fixture is then driven bare and in both quote kinds "
        "through the real hook -- the independent axis -- CORRECT_BY_REMEDY on the "
        "reasoning of the rows below. The six prior rows are unchanged and keep theirs. "
        "GREW 3 -> 6 on 2026-09-08 (DEF-718): the roster pin "
        "TestSecretPathAccess::test_the_powershell_roster_mirrors_the_bash_roster_class_for_class "
        "walks `wg._PS_SECRET_READ_VERBS` twice (the all-any lower-case check and the "
        "native-only set comprehension), and with the in-test `import write_guard as wg` "
        "binding the pre-existing comprehension over `write_guard.DANGEROUS_PS_PATTERNS` "
        "(the ephemeral carve-out test, filed below) became visible as its own row -- "
        "three rows, no population narrowed. The pin's verdict: it DERIVES both read "
        "rosters from the module and holds them to a hand-written twin table in both "
        "directions (every bash verb carried whole, every native verb naming a bash "
        "class), so a roster edit that drops a class reds; the independent axis is the "
        "deny rows driving each verb through the real hook (33 PowerShell and 11 bash "
        "rows) -- CORRECT_BY_REMEDY on the reasoning of the rows below. "
        "GREW 2 -> 3 on 2026-09-07 (DEF-697): no population changed; the file gained "
        "in-test `import _bash_patterns as bp` bindings (the PowerShell permission "
        "matcher's group-shape and backslash pins), and with them the pre-existing "
        "`_assignment_guarded_verbs` walk -- `for name, val in sorted(vars(mod).items())` "
        "-- became visible to the census as a third row (probable cause; the walk itself "
        "predates the lane). Its verdict: it DERIVES the `(?!=)`-guarded verb set from the "
        "module's own source, so a verb regex that adopts the guard self-enrols and one that "
        "forgets it drops out; the count floor beneath it is what catches the drop, and the "
        "per-verb deny rows in TestPermissionVerbs / TestPowerShellPermissionVerbs drive each "
        "guarded verb through the real hook, the independent axis -- CORRECT_BY_REMEDY on the "
        "same reasoning as the row below. The two prior rows are unchanged and keep theirs. "
        "GREW 1 -> 2 on 2026-08-22 (PowerShell ephemeral carve-out); the prior row is "
        "unchanged and keeps its verdict. NEW row: TestPowerShellEphemeralCarveOut::"
        "test_the_carved_record_set_is_derived_not_hand_listed derives `{e.pid for e in "
        "DANGEROUS_PS_PATTERNS if 'remove-item-recurse-force' in e.pid}` and compares it to "
        "write_guard._PS_RECURSIVE_DELETE_PIDS. ⚠ IT DERIVES FROM THE SAME PREDICATE AS THE "
        "PRODUCTION SIDE, so it ENROLS rather than REQUIRES -- the DEF-598 shape -- and a "
        "coordinated edit to both predicates passes it. Filed CORRECT_BY_REMEDY, not "
        "CORRECT_BY_PROPERTY, because the protection is on an INDEPENDENT AXIS one class "
        "over: tests/test_write_guard.py:2826 (`TestPowerShellEphemeralCarveOut::"
        "test_recognized_safe_ephemeral_targets_are_allowed`) and :2832 "
        "(`::test_everything_else_still_hard_denies`) drive a 25-case table "
        "end-to-end through the real hook "
        "process, so narrowing the pid set makes the -mixed record deny `.\\build` again and "
        "the ALLOW arm reds. Driven, not argued -- mutation M7 (hand-narrow the pid set to "
        "`endswith('-prefix')`) killed with 6 red, allow-arm rows among them. On its own this "
        "row is weak; it is kept because it names the intent at the definition site.",
    ),
    "tests/test_write_guard_pattern_message_coupling.py": (
        6, "def930a6139b4dfa0f7b9d283d6415c07158b9eb7ed525d13943325fd73b87d5",
        "PRIOR_PASS_UNRECORDED",
        "adjudicated in the parametrize/for-assert pass; per-row reason not preserved",
    ),
    "tests/test_write_guard_sed_grammar.py": (
        1, "0401c98ac5a6a76b1ec74765ae07dc2b2cf33c84a93dfe489a520ef6f4826b28",
        "CORRECT_BY_PROPERTY",
        "Worth having: it is the release gate for the in-place option-grammar "
        "class, where the hand-written roster that opened the work covered 5% of "
        "the real population (14 spellings listed; 237 of 333 sed and 37 of 37 "
        "perl spellings reached a protected path unchecked). Deriving is correct "
        "here because the defect IS the option grammar -- a spelling nobody "
        "listed is the failure mode, so a listed roster reproduces the bug one "
        "level up. NOT BLIND, in three independent directions: "
        "TestControlsAndMustAllow asserts the OPPOSITE property (a protected path "
        "quoted inside the sed expression must NOT extract, reads must not, "
        "grep -i / sort -i must not), so an extractor that simply started "
        "yielding every token reds; "
        "TestTheRetainedRegexIsWitnessed asserts a NEGATIVE (an unquoted "
        "separator is a shell pipeline, verified against real /bin/bash, and "
        "must not yield); and "
        "test_the_population_is_large_enough_to_be_a_population reds if the "
        "generator collapses, so the sweep cannot pass vacuously. "
        "Not pinned one file over: tests/test_write_guard_long_flags.py derives "
        "over SHORT-vs-LONG flag pairs across write verbs, a different axis that "
        "carries exactly one sed row and no perl arm at all. "
        "\u26a0 The alphabet itself is hand-written and that is the standing "
        "weakness -- an adversarial pass added delimiters, BSD -I and verb "
        "spelling as axes after the first cut reported full coverage while "
        "sed -i.bak 's|a|b|' <protected> wrote unchecked. Size is not "
        "exhaustiveness; attack the alphabet, not the row count.",
    ),
}

ADJUDICATED_FILE_COUNT = 102
ADJUDICATED_ROW_COUNT = 367

#: Files that MUST appear in the census, because they still carry a derived
#: population. An enumerator built for a class inherits the class, and this is
#: the cheapest mechanical check that it does not: before `parametrize` was a
#: shape, this script returned the lines of the FIXES and none of the DEFECTS.
#:
#: Both entries carry a floor beside the derived parametrize rather than instead
#: of it, so the derivation is still there and must still be visible.
#: Keyed on (file, shape, population) -- NOT on the file alone.
#: File-granularity was satisfied by rows the FIXES added: after 441-B/441-C, both
#: files still appeared in the census via the fix's own helper lines, so deleting
#: the parametrize handler or the alias pass left `check_health` green while the
#: actual defect rows vanished. That is verbatim the confusion this check exists
#: to prevent, rebuilt inside the check itself.
SELF_CHECK_MUST_SEE = {
    "DEF-598": (
        "tests/test_denial_reason_actionability.py", "parametrize", "_TEMPLATE_NAMES",
    ),
    "DEF-599": (
        "tests/test_release_noise_parity.py", "parametrize", "RELEASE_NOISE_PATTERNS",
    ),
}

#: ⚠ THIS SET IS DELIBERATELY EMPTY, AND ITS HISTORY IS THE POINT.
#:
#: It briefly held `tests/test_write_guard_command_position.py` (DEF-595's
#: founding site), on the reasoning that the file was CLOSED -- its rows now
#: parametrize from a hand-written `_PINNED_WRAPPERS` frozenset -- so zero census
#: rows was the correct answer and reporting it would be a false alarm.
#:
#: THAT REASONING WAS WRONG, and it was refuted mechanically: this file's only
#: resolved bindings are `{spec, module}`, both throwaway locals, because
#: `_load_bash_patterns()` is called INLINE and never assigned. The census
#: returns zero rows for it whether DEF-595 is open or CLOSED -- re-deriving its
#: three parametrize rows from the subject reproduces the defect verbatim and the
#: census still says zero. "Zero because repaired" and "zero because the resolver
#: is blind" were indistinguishable, and the comment asserted the first while the
#: second was true.
#:
#: Kept as an empty set with this note rather than deleted, because the failure
#: was not the wrong entry -- it was writing a documented impossibility at all
#: (`docs/FAILURE_MODES.md` §18.4: a "we looked, it cannot be done" comment is
#: why the next person does not look). An absence is now proven by the
#: unresolved-bindings check in `check_health`, never by prose.
SELF_CHECK_CORRECTLY_ABSENT: dict[str, str] = {}

#: Files the resolver genuinely cannot read, each with the reason. A BACKED
#: residue, not silence: any file that becomes unresolvable and is NOT named here
#: reds `check_health`, so the set cannot grow quietly. Subtracting a backed
#: residue is the discipline; an unbacked exclusion list would just be the
#: hand-list moved one level up.
#:
#: All three load the subject INSIDE a function or method body, so no
#: module-level name is ever bound to it. A population they iterate is therefore
#: a local, not a module-level derived population -- but that is an argument for
#: why the risk is low, NOT a proof they derive nothing, and it is written here
#: rather than asserted as an impossibility.
UNRESOLVED_BY_DESIGN = {
    "tests/test_execution_plan.py": "loads via a class method `_load_module`; "
                                    "reached as self._load_module(), never a "
                                    "module-level name",
    "tests/test_task_router.py": "loads inside a single test-method body; "
                                 "`spec`/`mod` never escape the method",
}

#: Throwaway locals of the importlib dance. A file whose ONLY source bindings are
#: these has not been resolved -- the module alias the tests actually use is
#: returned from a loader function, never assigned at module level.
_IMPORTLIB_SCRATCH_NAMES = frozenset({"spec", "mod", "module", "loader"})


def _hook_module_stems() -> set[str]:
    """Bare module names importable after the tests' sys.path juggling."""
    stems: set[str] = set()
    for sub in ("hooks", ""):
        d = REPO_ROOT / "tools" / "cc" / sub if sub else REPO_ROOT / "tools" / "cc"
        if d.is_dir():
            stems |= {p.stem for p in d.glob("*.py") if not p.stem.startswith("__")}
    return stems


_LINE_RE = re.compile(r"(.*?(?:\r\n|\n|\r|$))")


def _source_lines(text: str) -> list[str]:
    """Split ``text`` into lines the way the parser does, ONCE per file.

    ``ast.get_source_segment`` re-splits the WHOLE source on every call, and
    on Python 3.10 that split is a per-character Python loop: 36 ms per call on
    a 362 KB test module against 0.1 ms on 3.14 (measured 2026-09-13). This
    census made 31,098 such calls over 1.85 GB of re-split text, so on the
    3.10 CI cell the health test spent about 186 s inside the splitter and
    died on the 60 s per-test timeout while every newer interpreter finished
    the same walk in 19 s (`DEF-762`). The pattern is the one 3.11+ ships: it
    splits on ``\\r\\n``, ``\\n`` and ``\\r`` only, never on the form feed or
    the other separators ``str.splitlines`` honours, so the line numbers agree
    with the parser's ``lineno``.
    """
    return [m[0] for m in _LINE_RE.finditer(text)]


def _segment(lines: list[str], node: ast.AST) -> str | None:
    """``ast.get_source_segment(text, node)`` over lines split once.

    Same contract as the stdlib call it replaces (``padded=False``): ``None``
    when the node carries no end position; offsets are BYTE offsets into the
    UTF-8 encoding of the line, because ``col_offset`` counts bytes, not
    characters. Pinned equal to the stdlib on the live suite by
    ``tests/test_derived_population_census.py``.
    """
    try:
        if node.end_lineno is None or node.end_col_offset is None:
            return None
        lineno = node.lineno - 1
        end_lineno = node.end_lineno - 1
        col_offset = node.col_offset
        end_col_offset = node.end_col_offset
    except AttributeError:
        return None
    if end_lineno == lineno:
        return lines[lineno].encode()[col_offset:end_col_offset].decode()
    first = lines[lineno].encode()[col_offset:].decode()
    last = lines[end_lineno].encode()[:end_col_offset].decode()
    return "".join([first, *lines[lineno + 1:end_lineno], last])


def _source_bindings(
    tree: ast.Module,
    text: str,
    hook_stems: set[str],
    lines: list[str] | None = None,
) -> dict[str, str]:
    """Map name-in-test -> how it was bound, for source-module bindings only.

    ``lines`` is ``_source_lines(text)``; a caller that already split the file
    passes it so the split happens once per file, not once per pass.
    """
    out: dict[str, str] = {}
    if lines is None:
        lines = _source_lines(text)

    def is_source(mod: str) -> bool:
        root = mod.split(".")[0]
        return root in SOURCE_ROOTS or root in hook_stems

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if is_source(mod):
                for alias in node.names:
                    out[alias.asname or alias.name] = f"from {mod}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if is_source(alias.name):
                    out[alias.asname or alias.name.split(".")[0]] = f"import {alias.name}"
        elif isinstance(node, ast.Assign):
            # The importlib dance tests/CLAUDE.md mandates for tools/cc modules.
            src = _segment(lines, node.value) or ""
            if "module_from_spec" in src or "spec_from_file_location" in src:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        out[target.id] = "importlib-bound"

    # Second pass: a module alias produced by a LOADER FUNCTION rather than a
    # bare assignment. The house idiom is
    #     def _load_x():
    #         spec = importlib.util.spec_from_file_location(...)
    #         module = importlib.util.module_from_spec(spec)
    #         return module
    #     x = _load_x()
    # so the first pass binds only the throwaway locals `spec`/`module` and the
    # alias the tests actually iterate is never resolved.
    loader_fns = {
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
        and "spec_from_file_location" in (_segment(lines, fn) or "")
    }
    if loader_fns:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            fn = node.value.func
            called = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if called in loader_fns:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        out[target.id] = "importlib-bound (loader fn)"

    # Third pass: a module-level FUNCTION that reaches the subject and returns it.
    #     def _live_wrappers(): return _load_bash_patterns()._CMD_POS_WRAPPER
    #     @pytest.mark.parametrize("w", sorted(_live_wrappers()))
    # The loader is called INLINE, so pass two never fires and the whole file
    # resolves to nothing. This is the shape DEF-595's own founding file takes,
    # and missing it made that file's zero-row census result meaningless.
    # ⚠ The test is what the function RETURNS, not what it mentions. An earlier
    # version bound any module-level function whose SOURCE TEXT named a source
    # binding and had a `return` -- which enrolled
    # `tests/test_onboarding_nudge.py::_exempt_command_params`, a HAND-WRITTEN
    # roster of `pytest.param(cli.cmd_*)` literals. That is §18.4's prescribed
    # REMEDY, and reporting it as a candidate inflates the census with the very
    # shape the class is fixed BY. Require a return rooted in the subject.
    accessor_fns: dict[str, str] = {}
    for fn in tree.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # A pytest FIXTURE is test infrastructure, not a source-container
        # accessor. It is module-level and it returns derived data, so it looks
        # identical to an accessor from the outside -- but what it returns is
        # test input built from a live artifact, and there is no per-member
        # requirement to retire. Enrolling one put `labels[:50]` in the census as
        # a candidate when `labels` is a fixture over doc headings and `[:50]` is
        # a sample cap.
        if any(
            "fixture" in (_segment(lines, d) or "")
            for d in fn.decorator_list
        ):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Return) or node.value is None:
                continue
            returned = _root_name(node.value)
            if returned in loader_fns or returned in out:
                # Same reason as the alias pass below: the accessor's RETURN
                # expression is the indirection, and a bare "source accessor fn"
                # keeps it out of every digested field. Driven on
                # `tests/test_hook_unicode_stdin.py`, narrowing
                # `list(get_canonical_hook_scripts())` to `[:1]` took 12 hooks to
                # 1 with the digest unchanged.
                body = (_segment(lines, node.value) or returned)
                accessor_fns[fn.name] = f"source accessor fn := {body.strip()}"
                break
    out.update({k: v for k, v in accessor_fns.items() if k not in out})

    # Fourth pass: ONE-HOP module-level aliases of a source container.
    #     _TEMPLATE_NAMES = list(_denial_reasons._OPERATOR_FACING_TEMPLATES)
    # An alias is still the subject; a population derived from it carries the
    # identical blindness. This is the shape DEF-598 actually takes.
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        root = _root_name(node.value)
        if root in out:
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id not in out:
                    # The RHS TEXT, not just the root name. `bound_via` is one of
                    # the three fields `file_digest` hashes, and the alias's
                    # right-hand side appears in NO other digested field -- the
                    # iterated expression is just `_TEMPLATE_NAMES`. Recording
                    # only "alias of _denial_reasons" left the indirection
                    # invisible: narrowing the alias to
                    # `list(...)[:1]` took DEF-598's own founding site from 9
                    # templates to 1 across five parametrized classes with the
                    # digest BIT-IDENTICAL and check_health returning 0. Driven
                    # 2026-08-18. The one-hop alias is the shape DEF-598 has, so
                    # that blindness sat exactly where the class lives.
                    rhs = (_segment(lines, node.value) or root)
                    out[target.id] = f"alias of {root} := {rhs.strip()}"
    return out


def _is_loop_bound(node: ast.expr) -> bool:
    """True for `range(<source const>)` -- a loop BOUND, not a member population.

    `for _ in range(_reinject.REINJECT_SESSION_CAP)` repeats an action N times.
    There is no per-member requirement to retire, and deriving the bound from the
    cap is what keeps the property meaningful at any cap value. Collecting it as a
    candidate is a false positive: driven, lowering the cap left that test passing
    and still driving its property, while four OTHER tests reddened.
    """
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "range"
    )


def _root_name(node: ast.expr) -> str | None:
    """Root identifier of an iterated expression: sorted(m.FOO)[1:] -> m."""
    cur: ast.expr = node
    while True:
        if isinstance(cur, ast.Name):
            return cur.id
        if isinstance(cur, ast.Attribute):
            cur = cur.value
        elif isinstance(cur, ast.Call):
            cur = cur.args[0] if cur.args else cur.func
        elif isinstance(cur, ast.Subscript):
            cur = cur.value
        else:
            return None


def _iter_populations(tree: ast.Module, text: str, lines: list[str] | None = None):
    """Yield (shape, iter_node, lineno) for every population-shaped construct."""
    if lines is None:
        lines = _source_lines(text)
    for node in ast.walk(tree):
        # `@pytest.mark.parametrize("name", <source container>)` -- the shape of
        # EVERY member of this class filed so far (DEF-595, DEF-598, DEF-599).
        # Omitting it is how the first version of this script returned the lines
        # of the FIXES and none of the DEFECTS.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                if "parametrize" not in (_segment(lines, dec.func) or ""):
                    continue
                # args[0] is the argnames string; the population follows.
                for arg in dec.args[1:]:
                    yield ("parametrize", arg, dec.lineno)
        if isinstance(node, (ast.For, ast.AsyncFor)):
            body_asserts = any(isinstance(s, ast.Assert) for s in ast.walk(node))
            yield ("for-assert" if body_asserts else "for-plain", node.iter, node.lineno)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            if node.generators:
                yield ("comprehension", node.generators[0].iter, node.lineno)
        elif isinstance(node, ast.Assert):
            for sub in ast.walk(node.test):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id in ("all", "any")
                ):
                    for arg in sub.args:
                        if isinstance(arg, ast.GeneratorExp) and arg.generators:
                            yield ("all-any", arg.generators[0].iter, node.lineno)


def _census_paths() -> list[pathlib.Path]:
    """Every Python module under `tests/` the census reads, sorted.

    ONE definition, consulted by both walks. They used to carry the glob
    literal twice, and the copies drifted: both said ``test_*.py``, which
    skipped the 15 non-``test_``-prefixed modules under `tests/` -- including
    `tests/_surface_expected.py`, where this repo's literal pins live. So the
    file most often cited as the remedy for a derived population was the one
    file this enumerator could not read (`DEF-604`).

    ⚠ MEASURED YIELD, stated honestly because the first write-up overstated it:
    swapping this glob back to ``test_*.py`` on the same tree moves the census by
    exactly ONE row in ONE file (``tests/_adopter_tree.py``). In particular
    ``tests/_surface_expected.py`` -- named above as the motivation -- yields ZERO
    rows either way. What the widening buys is that the file is now READ, so a
    derived population appearing there would be seen; it is a closed blind spot,
    not a harvest.

    Widened to ``*.py`` rather than adding a helper-module allowlist: an
    allowlist is a second population that can rot, and this one would have to
    be kept in step with a directory nobody watches. `tests/fixtures/` is NOT
    carved out -- it yields zero rows today, and a carve-out would suppress
    nothing while adding a constant that can go stale. Sorted so the walk order
    is deterministic across platforms; the digests below depend on it.
    """
    return sorted(TESTS_DIR.rglob("*.py"))


def _files_with_only_scratch_bindings() -> list[str]:
    """Test files that load a source module but resolve only throwaway locals.

    `tests/CLAUDE.md` mandates `importlib.spec_from_file_location` for tools/cc
    modules. When the loader is called inline, the only names bound are `spec` /
    `module` -- so the file yields zero census rows for a RESOLVER reason, which
    is indistinguishable from a file that genuinely derives nothing.

    ⚠ THIS COVERS ONE SHAPE OF THAT PROBLEM, NOT ALL OF IT, and saying otherwise
    was wrong. The accessor pass creates a THIRD state -- a file whose bindings
    resolve but which still emits no rows -- and such a file is in no net at all:
    not here, not in `ADJUDICATED`, not in `UNRESOLVED_BY_DESIGN`. Measured
    instance: `tests/test_write_guard_command_position.py` resolves
    `{spec, module, _load_bash_patterns}`, so the subset test below does not fire,
    and it emits zero rows because its population is a `BinOp` `_root_name`
    cannot read. Widening this helper to that third state is a real follow-up and
    is NOT done here; what is done is retracting the claim that it was covered.
    """
    hook_stems = _hook_module_stems()
    out: list[str] = []
    for path in _census_paths():
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (SyntaxError, UnicodeDecodeError):
            continue
        if "spec_from_file_location" not in text:
            continue
        bindings = _source_bindings(tree, text, hook_stems)
        if bindings and set(bindings) <= _IMPORTLIB_SCRATCH_NAMES:
            out.append(str(path.relative_to(REPO_ROOT)).replace("\\", "/"))
    return out


def census_derived_populations() -> list[dict[str, object]]:
    """Return every candidate site. Candidates -- not defects. See module docstring."""
    hook_stems = _hook_module_stems()
    rows: list[dict[str, object]] = []

    for path in _census_paths():
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (SyntaxError, UnicodeDecodeError):
            continue
        lines = _source_lines(text)
        bindings = _source_bindings(tree, text, hook_stems, lines)
        if not bindings:
            continue
        for shape, iter_node, lineno in _iter_populations(tree, text, lines):
            if _is_loop_bound(iter_node):
                continue
            root = _root_name(iter_node)
            if root is None or root not in bindings:
                continue
            expr = (_segment(lines, iter_node) or "?").replace("\n", " ")
            rows.append(
                {
                    "file": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                    "line": lineno,
                    "shape": shape,
                    "population": expr.strip()[:100],
                    # UNtruncated, and the only field `file_digest` reads for the
                    # expression. `population` is truncated at 100 chars for
                    # display, and one live row already sits exactly at that cap
                    # -- two distinct expressions sharing a 100-char prefix would
                    # collide, and a deletion could then hide behind its twin.
                    # Digesting the truncated form would rebuild §18.4 inside the
                    # check written to close it.
                    "population_full": expr.strip(),
                    "bound_via": bindings[root],
                    "verdict": None,  # adjudicated per-site; never by this script
                }
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument(
        "--shape", choices=SHAPES, help="restrict output to one shape"
    )
    parser.add_argument(
        "--print-adjudicated-entry",
        metavar="FILE",
        help=(
            "print the ADJUDICATED entry for one repo-relative test file and "
            "exit. PRINTS ONLY -- it never edits this file. Paste the result and "
            "fill in the verdict and reason yourself; that hand step is the "
            "adjudication, and automating it away would make the map a "
            "restatement of the census instead of a check on it."
        ),
    )
    args = parser.parse_args(argv)

    all_rows = census_derived_populations()

    if args.print_adjudicated_entry:
        target = args.print_adjudicated_entry.replace("\\", "/")
        frows = [r for r in all_rows if r["file"] == target]
        if not frows:
            print(
                f"{target} emits no census rows. Either the path is wrong "
                f"(it must be repo-relative, e.g. tests/test_foo.py) or the file "
                f"carries no derived population -- in which case it needs no entry.",
                file=sys.stderr,
            )
            return 1
        shapes = ", ".join(sorted({str(r["shape"]) for r in frows}))
        print(f'    "{target}": (')
        print(f'        {len(frows)}, "{file_digest(frows)}",')
        print('        "<VERDICT>",   # adjudicate it: is the test worth having, is it')
        print('        "<reason>",    # blind, and is it already pinned one file over?')
        print("    ),")
        print(f"    # {len(frows)} row(s), shapes: {shapes}", file=sys.stderr)
        return 0

    rows = [r for r in all_rows if r["shape"] == args.shape] if args.shape else all_rows

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        by_shape: dict[str, int] = {s: 0 for s in SHAPES}
        by_file: dict[str, list] = {}
        for r in rows:
            by_shape[str(r["shape"])] += 1
            by_file.setdefault(str(r["file"]), []).append(r)
        print("Derived-population census (CANDIDATES, not defects)")
        print("=" * 66)
        for shape in SHAPES:
            print(f"  {shape:16} {by_shape[shape]:4}")
        print(f"  {'TOTAL':16} {len(rows):4}   across {len(by_file)} files")
        print()
        # ASCII only: tests/test_portability_contract.py scans runtime prints in
        # scripts/. Docstrings and comments may carry the section sign; a print
        # may not.
        print("Apply the docs/FAILURE_MODES.md section 18.4 discriminator per site:")
        print("  CORRECT if the property is 'everything present is safe'")
        print("  DEFECT  if the property is 'everything required is present'")
        print()
        for f in sorted(by_file, key=lambda k: -len(by_file[k])):
            print(f"{f}  ({len(by_file[f])})")
            for r in by_file[f]:
                print(f"    :{r['line']:<5} [{r['shape']:13}] {r['population']}")

    # Floors are checked against the FULL census, never the filtered view --
    # `--shape all-any` legitimately returns a handful and must not read as a
    # resolver failure.
    return check_health(all_rows)


def file_digest(rows: list[dict[str, object]]) -> str:
    """sha256 identity of one file's census rows. Order-independent, line-independent.

    Digests a SORTED LIST, not a set, and that is the load-bearing choice.
    `(file, shape, population)` is NOT unique on this tree: 208 rows hold only
    149 distinct triples, so a set -- or a roster keyed on the triple -- lets
    59 rows (28%) vanish with the check still green, which is WORSE than the
    `>=` floors this replaced. A sorted list carries multiplicity, so deleting
    one of `test_speedbump_irreversible.py`'s eight `SPEEDBUMPS` comprehensions
    moves the digest.

    `line` is deliberately excluded: lines move on every edit above them, and a
    digest that churns on unrelated edits gets regenerated, which is the failure
    this whole artefact exists to prevent. `bound_via` IS included -- it is the
    resolution route, and a population that starts resolving through a different
    binding is a different population even when its text is unchanged.
    """
    payload = "\n".join(
        f"{r['shape']}\t{r['population_full']}\t{r['bound_via']}"
        for r in sorted(
            rows,
            key=lambda r: (
                str(r["shape"]),
                str(r["population_full"]),
                str(r["bound_via"]),
            ),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def check_health(rows: list[dict[str, object]]) -> int:
    """Compare the live census against ADJUDICATED. Returns a process exit code.

    Set-equality in BOTH directions plus a per-file identity digest. The arm
    this replaced was a per-shape `>=` floor, which §18.4 retracts by name and
    which measured 47 of 207 rows of silent headroom on this tree.

    Deliberately NOT a count. A count cannot distinguish "one row left and
    another arrived" from "nothing changed", and it cannot name what moved. The
    digest carries the file's whole population, so the failure message can print
    the live rows beside the expectation -- which is where a digest's opacity is
    paid back, at the only moment anyone reads it.
    """
    from collections import defaultdict

    failures: list[str] = []
    live: dict[str, list[dict[str, object]]] = defaultdict(list)
    for r in rows:
        live[str(r["file"])].append(r)

    vanished = sorted(set(ADJUDICATED) - set(live))
    for path in vanished:
        expected_n = ADJUDICATED[path][0]
        failures.append(
            f"{path} is in ADJUDICATED with {expected_n} row(s) but the census "
            f"now emits NONE for it. Either its derived population was removed "
            f"-- which is the §18.4 defect this script exists to catch, and the "
            f"deletion is the thing to look at, not this message -- or a "
            f"resolver change stopped reading the file. If the population really "
            f"is gone, drop its ADJUDICATED entry and lower "
            f"ADJUDICATED_FILE_COUNT / ADJUDICATED_ROW_COUNT in the same edit."
        )

    unadjudicated = sorted(set(live) - set(ADJUDICATED))
    for path in unadjudicated:
        shapes = ", ".join(sorted({str(r["shape"]) for r in live[path]}))
        failures.append(
            f"{path} emits {len(live[path])} census row(s) ({shapes}) and has no "
            f"ADJUDICATED entry. A new derived population appeared. Adjudicate it "
            f"against §18.4's discriminator -- ask first whether the test is worth "
            f"having, then whether it is blind, then whether a pin already exists "
            f"one file over -- and add the entry with "
            f"`--print-adjudicated-entry {path}`."
        )

    for path in sorted(set(ADJUDICATED) & set(live)):
        expected_n, expected_digest = ADJUDICATED[path][0], ADJUDICATED[path][1]
        actual = live[path]
        actual_digest = file_digest(actual)
        if actual_digest == expected_digest and len(actual) == expected_n:
            continue
        detail = "\n".join(
            f"      {r['shape']:14s} {str(r['population'])[:70]}" for r in
            sorted(actual, key=lambda r: (str(r["shape"]), str(r["population_full"])))
        )
        failures.append(
            f"{path}: census rows changed. Expected {expected_n} row(s) "
            f"(digest {expected_digest[:12]}...), found {len(actual)} "
            f"(digest {actual_digest[:12]}...). A SHRINK is the §18.4 defect -- a "
            f"population narrowed and every check derived from it narrowed with "
            f"it. A GROWTH is a new candidate to adjudicate. ⚠ DO NOT REGENERATE "
            f"THE WHOLE MAP -- a wholesale regeneration that carries the old "
            f"verdicts forward is caught by nothing here. Run "
            f"`--print-adjudicated-entry {path}`, paste the ONE line, keep or "
            f"revise that file's verdict and reason by hand, and move "
            f"ADJUDICATED_ROW_COUNT by the same delta. Live rows now:\n"
            f"{detail}"
        )

    seen = {(str(r["file"]), str(r["shape"]), str(r["population"])) for r in rows}
    for tag, (path, shape, population) in SELF_CHECK_MUST_SEE.items():
        if not any(f == path and s == shape and population in p for f, s, p in seen):
            failures.append(
                f"self-check: {tag}'s {shape} population over {population!r} in "
                f"{path} is no longer visible to the census. Seeing the FILE is "
                f"not enough -- it appears via other rows, including ones the fix "
                f"itself added. A handler or resolver pass has probably been "
                f"removed."
            )

    # A file that uses the importlib dance but resolves ONLY throwaway locals has
    # not been read -- its zero rows are a RESOLVER result, not a clean file.
    # This is the check whose absence let a documented impossibility stand:
    # `_IMPORTLIB_SCRATCH_NAMES` existed, said exactly this, and was never called.
    # Computed ONCE -- this walk re-parses every test file, and calling it twice
    # doubled the cost of the row that runs it in the suite.
    scratch_only = set(_files_with_only_scratch_bindings())
    unresolved = sorted(f for f in scratch_only if f not in UNRESOLVED_BY_DESIGN)
    stale = sorted(f for f in UNRESOLVED_BY_DESIGN if f not in scratch_only)
    if stale:
        failures.append(
            "file(s) in UNRESOLVED_BY_DESIGN now resolve fine: "
            + ", ".join(stale)
            + ". Remove them -- a stale exclusion understates what the census "
            "can actually read."
        )
    if unresolved:
        failures.append(
            "the census could not resolve a source alias in these files, so a "
            "zero-row result for them proves NOTHING about whether they derive a "
            "population: " + ", ".join(unresolved) + ". Extend _source_bindings "
            "rather than reading their silence as clean."
        )

    if failures:
        print("\nCENSUS HEALTH FAILED", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
