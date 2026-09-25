"""Expected surface cardinality — single source of truth for tests.

Adding an agent / command / hook means updating the constant here and
nowhere else. Tests asserting cardinality must import from this module
rather than hardcoding integers.

TP-11 Task 11-B. Reflects post-TP-13-B deploy-all semantics: the
universal agent set is a *floor*, with profile-aware OPTIONAL_AGENTS
layered on top per fingerprint match (commands and skills don't have
this distinction — they're universal).

Updating these values: bump the constant, run pytest, expect cardinality
tests to either pass (new surface item already added) or fail with a
clear message (item not yet wired).

SoT-vs-witness contract (TP-137):
Constants in this module fall into two classes:
- **DERIVED** — value is ``len(producer)`` or ``getattr(producer, ...)``.
  These are intentional consolidations of repo state. They CANNOT be
  used as independent witnesses in parity tests
  (``assert len(other_view_of_X) == EXPECTED_X`` where
  ``other_view_of_X`` also routes through the same SoT is tautological
  — TP-12/TP-74/TP-136 convergence-theater pattern). Marked
  ``# class: derived``.
- **LITERAL** — value is a hand-pinned constant. These ARE legitimate
  independent witnesses; the test side is independent of the producer.
  Marked ``# class: literal``.

When adding a new EXPECTED_X constant, choose intentionally and mark
the class. New tests asserting ``len(producer) == EXPECTED_X`` where
the constant is ``# class: derived`` will fail
``tests/test_surface_expected_witness_contract.py``.
"""
from __future__ import annotations


# ── Pytest markers ──────────────────────────────────────────────────

# Markers a pytest PLUGIN owns -> the distribution that owns them. Declared in
# pyproject.toml as well so that `--strict-markers` accepts them on an install
# without the plugin (the runtime-only `pip install -e .`; measured 2026-09-22
# on a 3.14 venv: six files errored at collection with `'timeout' not found in
# markers`). They are not part of the taxonomy: tests/test_marker_parity.py
# excludes them from the pyproject-equals-conftest comparison, and
# tests/test_test_suite_contract.py pins that each one is declared, that the
# owning distribution is in the dev extra (so a taxonomy marker cannot hide
# here), that the map is non-empty, and that it stays under its ceiling.
PLUGIN_OWNED_MARKERS: dict[str, str] = {  # class: literal
    "timeout": "pytest-timeout",  # the declaration is inert without the plugin
}


# ── Agents ──────────────────────────────────────────────────────────

# The universal canonical agent set deployed by `espalier init`
# regardless of repo fingerprint. Profile-aware OPTIONAL_AGENTS
# (api-reviewer, data-engineer, etc.) layer on top per fingerprint
# match — these names define the floor, not the ceiling.
EXPECTED_UNIVERSAL_AGENTS = frozenset({  # class: literal
    "architecture-analyst",
    "code-reviewer",
    "docs-maintainer",
    "harness-config-advisor",
    "repo-analyst",
    "test-writer",
    # TP-40: post-v0.6.5 audit addition. failure-mode-reviewer is the
    # internal-failure-mode lens (distinct cognitive mode from
    # code-reviewer). Renamed from adversarial-reviewer in TP-56-followup
    # (reframe to internal-mistake focus; single-operator harness).
    "failure-mode-reviewer",
})

# Minimum agent count — for cardinality assertions where profile-aware
# extras shouldn't fail the test. Use `>= EXPECTED_AGENT_COUNT_MIN`.
EXPECTED_AGENT_COUNT_MIN = len(EXPECTED_UNIVERSAL_AGENTS)  # class: derived


# ── Commands & skills ───────────────────────────────────────────────

# Commands and skills are universal — no profile-aware variation.
# These are exact-equality assertions.
# TP-40: 15 -> 14 after folding /audit into /smoke (audit.md deleted;
# `espalier audit .` invoked as Step 7 of /smoke).
# TP-50: 6 -> 10 skills after wiring the 5 orphan agents via delegation
# skills (review / arch-check / adversarial) on top of the pre-existing 6
# (analyze / blueprint-authoring / debug / design / hook-authoring /
# reflect). M8 + M10 + HCA-8. 10 -> 9: verify-release retired alongside
# the release-verifier agent (the harness-dev deploy tier was removed).
EXPECTED_COMMAND_COUNT = 17  # class: literal  (TP-167: +/recall; TP-214: +/read-summary; TP-233b: +/strengthen)
EXPECTED_SKILL_COUNT = 9  # class: literal


# ── Hooks ───────────────────────────────────────────────────────────

# Number of wired hook scripts in .claude/settings.json. Exact equality.
# Same as len(managed_inventory.get_hook_entry_files()) — kept here as
# a constant so cardinality assertions don't need to import the SoT.
# TP-40: 9 -> 10 with subagent_stop.py addition (Gate 4 only — appends
# subagent reasoning to the active blueprint; never blocks the subagent).
# TP-163: 10 -> 12 with subagent_start.py (SubagentStart, cold-subagent
# orientation) + context_reinject_failure.py (PostToolUseFailure, Rule A) —
# the recall-engine substrate.
EXPECTED_HOOK_COUNT = 12  # class: literal
EXPECTED_HOOK_ENTRY_COUNT = 12  # class: literal

# Number of helper modules under tools/cc/hooks/ — files matching `_*.py`
# excluding `__init__.py`. Same as len(managed_inventory.get_hook_helper_files()).
# The package marker (__init__.py) is intentionally NOT counted as a
# helper. External reviewers (or cross-cutting docs) that count files
# by ls should consult this constant rather than direct directory listing
# — that's what the post-TP-SYN-11 audit miscount (4 vs 5) revealed.
# TP-112: 7 -> 8 with _denial_reasons.py addition (denial-reason
# templates SoT for 4 hook scripts).
EXPECTED_HOOK_HELPER_COUNT = 13  # class: literal  (TP-159: +_speedbump.py; TP-164: +_reinject.py; TP-167: +_recall.py; TP-204e: +_born_weak.py; TP-332: +_explain_path.py)


# ── Scripts ─────────────────────────────────────────────────────────

# Number of top-level scripts under scripts/ (non-recursive, .py only,
# excluding __pycache__). Pinned post-Sprint-6 when a 4th script
# (final_release_matrix.py) joined the existing three (build_release_archive,
# release_check, wheel_smoke) — repo-analyst flagged the count as a new
# structural fact worth a counted invariant. TP-53: 5 -> 6 with
# check_exception_policy.py (broad-except regression gate, Group E).
# 6 -> 7 with audit_dead_rules.py (dead-rule histogram against bench/corpus).
# 7 -> 8 with extract_test_first_add.py (TP-106 docstring-rationale
# backfill authoring helper).
# 8 -> 9 with check_memory_md_tag_parity.py (TP-147 147-G Part 2 —
# every git tag must be mentioned in ESPALIER_MEMORY.md or session-archive.md).
# 9 -> 10 with check_pack_landing.py (TP-185 W0-D — advisory closeout lint:
# Done/ packs should carry a terminal ## Landing State:).
# 10 -> 11 with sync_vendor_cc.py (TP-178: the tools/cc -> espalier/_vendor/cc
# wheel-vendor mirror generator).
# 11 -> 12 with sync_claude_mirrors.py (the .claude config-triplet SoT
# generator — the .claude analog of sync_vendor_cc.py).
# 12 -> 13 with sync_selfcheck_tests.py (the espalier/_vendor/selfcheck_tests
# mirror generator — the selfcheck-channel analog of sync_vendor_cc.py).
# 13 -> 11 (surface curation): pruned capture_baseline.py (dead v0.6.1 audit
# one-shot carrying personal-identifier needles) and extract_test_first_add.py
# (stale docstring-rationale authoring helper — the backfill it wrote is done).
# 11 -> 12 with sync_asset_docs.py (the espalier/assets/docs + assets/task-packs
# doc-mirror generator — the doc-carryover analog of sync_vendor_cc.py).
# 12 -> 13 with sync_github_workflow_asset.py, the one mirror that runs the other
# way (packaged asset -> repo root) and until then had no script at all.
# 13 -> 15 with sync_checklist_regions.py (the two narrowest mirror rows: /implement-pack's
# inlined pack-artifact checklist, generated from tools/cc/pack_artifact_checklist.md
# because two hand-maintained copies drifted under a title-only guard) and
# check_pack_fences.py (resolves a pack's `python target=<path>` fences against the
# module they land in — a NameError in prescribed code, found before it is pasted).
# 17 -> 18 with derived_population_census.py (TP-441): the standing enumerator for
# the §18.4 class — test populations derived from the source they police, which see
# an addition and are blind to a deletion. It replaces a one-time census that filed a
# bare COUNT and no roster, so the next reader could not reconcile it; re-deriving
# found the filed shape under-counted (an import-only probe cannot see the
# importlib.spec_from_file_location bindings tests/CLAUDE.md mandates for tools/cc).
# 29 -> 30 on 2026-09-08: scripts/ledger_trend.py, which diffs the ledger's
# snapshots on the record ref (filed, struck, churn, net, by audience and
# population) -- the instrument contract rule 5 says the live count cannot be.
# 18 -> 19 on 2026-08-20: scripts/check_ledger_probes.py, the runner that
# re-derives every FORWARD_LEDGER.md row's claim. The census that motivated it
# found 41 of 222 rows already dead with nothing re-deriving them.
# 19 -> 20 on 2026-08-21: scripts/verify_pins.py, which reverts a change's
# non-test files in a throwaway clone and checks a test actually goes red.
# Measured motivation: 15 of 24 fix claims across 536a8c5/9b97e89/3060e20 are
# pinned by nothing -- delete the guard and the suite stays green.
# 20 -> 21 on 2026-08-31: scripts/archive_transcripts.py, a verified archiver for
# ~/.claude/projects. Measured motivation: Claude Code auto-prunes that tree and
# `cleanupPeriodDays` was never set here, so the default 30-day retention applied
# and the oldest surviving transcript was 2026-07-31 against a 2026-04-30 first
# commit -- roughly three months of session history already gone when it was found.
# 23 -> 24 on 2026-09-02: scripts/generate_ledger_regions.py. FORWARD_LEDGER.md
# asserted in four places that its summary regions were generated and NO generator
# existed; five had drifted -- headline 168 against 174 live rows, twelve ids struck
# in their section and unstruck in Appendix B, and four classes hiding eleven struck
# rows behind a bare cell no test could read. Enforced by
# tests/test_generate_ledger_regions.py, which runs --check inside the suite.
# 24 -> 25 on 2026-09-03: scripts/recall_eval.py. The recall engine's calibration
# lived as prose tables in _recall.py's comments and floors/bands in two test
# files; nothing printed a number, the naming arm was never measured on the
# front door (recall_union), and the "211 stripped queries" arm the comments
# cite had no committed definition. DEF-679 needs before/after numbers on the
# path that ships. Guarded by tests/test_recall_eval.py.
# 25 -> 28 on 2026-09-06: scripts/handoff_mechanics.py (the mechanical half of
# /handoff, two phases around the hand-authored texts), scripts/ledger_row.py
# (strike/file one ledger row with its probe and regions, refusing a row shape it
# cannot round-trip) and scripts/symbol_census.py (an untruncated rename census).
# All three were added in one batch, and this pin -- with the marker taxonomy and
# the slow-file set -- went red while every targeted run stayed green: a NEW file
# is invisible to a targeted run, which is why /implement-task step 6 now names
# the enumerator-pin slice before the reviewers are dispatched.
# 28 -> 29 on 2026-09-06: scripts/proof_tier.py, the one computation of the
# proof-tier boundary the four proof-order bodies cite instead of restating.
EXPECTED_SCRIPT_NAMES = frozenset({  # class: literal
    "proof_tier.py",
    "handoff_mechanics.py",
    "ledger_row.py",
    "ledger_trend.py",
    "host_check.py",  # 2026-09-10: a host's suite + bench results as one pushed commit
    # 2026-09-20 (TP-452 1-B): the ledger-rebuild assembler. The rebuild workflow
    # adjudicates; this script turns the verdicts into the rebuilt ledger, its
    # probes and the record-branch payload, re-runnable at seed time. Guarded by
    # tests/test_ledger_rebuild_assemble.py.
    "ledger_rebuild_assemble.py",
    # 2026-09-20 (TP-452 1-D): the structural cut. Drops every struck row and
    # every named history block from the rebuilt ledger, moves the mechanism
    # block under the contract, proves it dropped nothing else, and writes the
    # record-branch payload; re-runnable at the next rebuild. Guarded by
    # tests/test_ledger_structural_cut.py.
    "ledger_structural_cut.py",
    "symbol_census.py",
    "archive_transcripts.py",
    "audit_dead_rules.py",
    "build_release_archive.py",
    "check_exception_policy.py",
    "check_memory_md_tag_parity.py",
    "check_ledger_probes.py",
    "check_pack_fences.py",
    "record_snapshot.py",
    "check_pack_landing.py",
    "check_handoff_landing.py",
    "derived_population_census.py",
    "final_release_matrix.py",
    # 2026-09-22: the release gate -- the full proof tier in a fresh clone per
    # interpreter (a tree the suite was not written on), on the pre-tag ladder
    # before the matrix. Guarded by tests/test_fresh_clone_gate.py.
    "fresh_clone_gate.py",
    # 2026-09-23 (TP-455 1-H): the archive drive as a script -- build the
    # release archive from this checkout, extract, the DEF-670 seed, a venv,
    # the caller's pytest arguments inside the extracted tree; `--audit` runs
    # the full_tree self-expiry. The four-minute oracle for a dev-tree row,
    # before the matrix and not by it. Guarded by tests/test_archive_probe.py.
    "archive_probe.py",
    "generate_doc_regions.py",
    "generate_ledger_regions.py",
    "recall_eval.py",
    "release_check.py",
    "sync_asset_docs.py",
    "sync_claude_mirrors.py",
    "sync_github_workflow_asset.py",
    "sync_checklist_regions.py",
    "sync_selfcheck_tests.py",
    "sync_vendor_cc.py",
    "verify_pins.py",
    "wheel_smoke.py",
})
# Derived from the roster since 2026-09-10. The roster is the registration act
# and the literal witness: a deleted script or an unregistered new one reds the
# set equality in tests/test_test_suite_contract.py, and the count added
# nothing to that but one more edit per new script (five in nine days). Kept as
# a name because the post-write pointer and the surface-impact demand cite it.
EXPECTED_SCRIPT_COUNT = len(EXPECTED_SCRIPT_NAMES)  # class: derived


# ── Numeric SoT for multi-surface constants (TP-104) ─────────────────

from espalier.asset_inventory import get_packaged_surface  # noqa: E402


# ESPALIER_MEMORY.md line cap. Literal policy constant; no filesystem source
# to derive from. Consumed by: tests/test_contracts.py,
# tools/cc/hooks/post_write_check.py:_MEMORY_MD_CAP, and BOTH the
# `ESPALIER_MEMORY.md line cap` NumericContract and the MEMORY_CAP_POPULATION
# in tests/test_documented_claims.py.
#
# This comment used to read "The 6+ prose-surface mirrors are pinned by the
# NumericContract regex." That was an overclaim and it is the reason the
# population contract exists: `sources` holds 11 rows across 7 distinct paths,
# of which only FIVE are prose files (README.md, ESPALIER_MEMORY.md,
# docs/SHARP_EDGES.md, and the two copies of docs-maintainer.md). A tree-wide
# re-derivation found 20 restatements across 15 files. Do not restate a
# coverage claim here — EXPECTED_MEMORY_CAP_SITES below is the census, and it
# is mechanically checked.
EXPECTED_MEMORY_MD_CAP = 120  # class: literal


# Per-file cap-site census for MEMORY_CAP_POPULATION. Each value is the number
# of cap-context occurrences of EXPECTED_MEMORY_MD_CAP in that file.
#
# These are COMPLETENESS pins, not decoration. docs/SHARP_EDGES.md = 4 is the
# one that earns the contract: before this existed, one of those four was bound
# and three were not, so raising the cap would have been forced through the
# bound line and left the other three silently false.
#
# Raising the cap: every count below must be re-satisfied at the NEW value, so
# each file reds by name until its prose is updated. That is the intended cost.
EXPECTED_MEMORY_CAP_SITES: dict[str, int] = {  # class: literal
    "README.md": 1,
    "ESPALIER_MEMORY.md": 1,
    "docs/SHARP_EDGES.md": 4,
    "docs/CONVENTIONS.md": 2,
    # 2 = TWO shapes on ONE line ("at most 120 lines" AND the cap-history chain
    # "…80 → 120"). Counting lines by eye gives 1; do not "correct" it to 1, or
    # a genuinely lost second shape later reads as already-accounted-for. Was 3
    # until 2026-09-10: the CLI pin example quoted "--expected-value 120" and
    # now shows hook-count, the one numeric-contract fragment left.
    "docs/FRESHNESS.md": 2,
    "docs/MEMORY_SYSTEMS.md": 1,
    ".claude/commands/handoff.md": 1,
    ".claude/skills/design/SKILL.md": 1,
    ".claude/agents/docs-maintainer.md": 4,
    # Package data shipped to every adopter (pyproject.toml packages
    # `assets/memory/*.md`). NOT a mirror row — verified against
    # espalier/mirror_registry.py, which has no assets/memory entry.
    #
    # ⚠ CORRECTED 2026-08-20. This used to add "and deliberately not byte-equal
    # to memory/README.md", which is FALSE and was false in two places at once
    # (see espalier/managed_inventory.py, the note this line defers to). Driven:
    # `cmp espalier/assets/memory/README.md memory/README.md` returns 0 — 2751
    # bytes each, byte-identical.
    #
    # The true statement is the more interesting one: the twin exists, the two
    # files agree today, and NOTHING PINS THAT. Not a mirror row means no sync
    # script regenerates either from the other and no parity test compares them,
    # so the pair can drift silently in either direction. Whether it SHOULD be
    # pinned is an open question and deliberately not answered here — but do not
    # re-derive "they are meant to differ" from the absence of a pin, which is
    # how the false version got written.
    "espalier/assets/memory/README.md": 1,
    # The forward ledger, tracked and shipping since 2026-09-21: three live rows
    # (DEF-671, DEF-650, DEF-18) state the 120-line cap as a fact their claim
    # rests on, so when the cap moves those texts are stale and this census is
    # what says so; each row's own probe measures its defect, not the number.
    # Re-pin a row through scripts/ledger_row.py, never a hand edit.
    "task-packs/FORWARD_LEDGER.md": 3,
}

# memory/**/*.md restates the cap in some notes' `**Linked from:**` line.
# Pinned in AGGREGATE, not per file: most notes legitimately never mention the
# cap, so a per-file rule would manufacture one finding per silent note.
#
# ⚠ This is an INCIDENTAL variant, NOT the prescribed boilerplate. Measured:
# 45 of 49 notes carry the `**Linked from:**` line; only a handful name the
# cap. Do not "standardize" the template to include it — that would multiply
# this constant's churn until someone deletes the assertion instead of
# maintaining it. The prescribed shape lives in `.claude/skills/reflect/` and
# `docs/CONVENTIONS.md`.
#
# 8, not 10: an earlier census used a looser "N lines" shape that also caught
# `memory/injection-opportunity-atlas.md`'s "120 raw candidates → 119 deduped",
# which is not a cap claim. The contract itself caught that overcount.
#
# `literal`, not `derived`, and the distinction is load-bearing: these two are
# hand-declared censuses that the contract checks AGAINST the filesystem. A
# `derived` marker would make that comparison convergence theater — a count
# derived from the tree asserted equal to a constant derived from the same
# tree, which can never fail.
EXPECTED_MEMORY_CAP_GLOB_SITES = 8  # class: literal


def live_surface_counts() -> tuple[int, int, int]:
    """Surface counts derived from the package SoT.

    Returns (agents, commands, skills) — the full bundled set. Every
    asset ships to every consumer now that the harness-dev deploy tier
    was retired. Consumed by tests/test_quickstart_tier_counts.py.
    """
    surface = get_packaged_surface()
    return (
        len(surface.agents.paths),
        len(surface.commands.paths),
        len(surface.skills.paths),
    )


# ── Sister-site probe ceiling pins (TP-107) ─────────────────────────

# Maximum number of ``# sister-site: ok <reason>`` opt-out markers
# allowed in code scanned by the probe (``tools/cc/hooks/*.py`` +
# ``espalier/*.py`` top-level). The live count reads markers above every
# non-class module-level node (assign/import/constant/function) AND every
# non-dunder class method — the exact surface a marker suppresses on.
# Grandfather-frozen at the current population (all above constant/assign
# sites): the prior ceiling test counted only FunctionDef/method sites and
# so was blind to these, passing vacuously at 0. Chip down, don't grow —
# raising requires a deliberate edit here; the escape hatch is a last
# resort, not a steady-state pattern. Test fixtures and synthetic
# injection markers under tests/ are excluded (the probe doesn't scan
# tests/).
#
# 20 -> 21 on 2026-09-05, deliberately: `_recall.indexes_failure_modes` is a
# LATE-BOUND one-line wrapper over `is_self_host_repo` (four tests force both
# corpus gates open by patching that one name; an alias binds at import and was
# driven red), so the alias-call arm's remedy does not apply and the
# purpose-scoped marker is the honest record. It was one of the two reds that
# kept this repo's own step 0-C at exit 2; the other (`doctor.py`'s floor seam)
# took the alias.
EXPECTED_OPT_OUT_CEILING = 21  # class: literal

# Maximum number of pre-existing test files grandfathered as ``unit``
# in ``tests/conftest.py::_MARKER_RULES``. TP-105 froze this list at
# 59 stems; new tests must be deliberately classified above the
# grandfather tuple. The ceiling chips down over time (as files are
# reclassified or deleted), never grows. Pinned here so a silent add
# fires the contract instead of waiting for runtime discovery.
#
# 59 -> 41 on 2026-08-24: eighteen grandfathered stems left for the
# `integration` tuple because they spawn child processes, which the
# `unit` marker's own declared description forbids. The ceiling has to
# come down with them -- it sat at the live count with ZERO headroom,
# which is precisely why `# pytest-marker: default-unit` had become the
# de-facto route into this bucket instead of the tuple. Leaving it at 59
# would silently re-open eighteen slots.
EXPECTED_GRANDFATHER_CEILING = 41  # class: literal

# Minimum number of public FunctionDef names exported by
# ``tools/cc/hooks/_hook_utils.py``. Asymmetric pin: shrinkage is
# suspicious (a helper was silently removed and hooks may now define
# private copies); growth is fine (more surface protected by the
# helper-shadow contract). 11 names as of TP-104.
EXPECTED_HOOK_UTILS_PUBLIC_COUNT = 11  # class: literal

# Maximum number of WARN-blocking constant cliques the sister-site
# probe may report (3+ sites, non-divergent — same name + same value
# across 3+ files). TP-108 introduced constant-clique detection and
# closed the seed instance (MUTATION_TOOLS, originally 3 sites:
# write_guard.py:52, plan_guard.py:60, test_hook_matcher_precision.py:61
# — now imported from _hook_utils). 0 is the steady-state ceiling: any
# growth surfaces new compression debt at pre-flight time.
EXPECTED_CONSTANT_CLIQUE_CEILING = 0  # class: literal

# Maximum number of alias-misses the sister-site probe may report — a
# hook-internal short name aliasing a longer _hook_utils export where the
# LHS basename diverges from the aliased attr (rename drift). Driven to 0
# and flipped from advisory to blocking (TP-341); a deliberate short-name
# alias opts out with a ``# sister-site: ok <reason>`` marker. Steady-state
# ceiling is 0 — any growth reintroduces the drift the flip forecloses.
EXPECTED_ALIAS_MISS_CEILING = 0  # class: literal


# ── Cross-source contract ceilings (TP-109b) ─────────────────────────

# Per-rule opt-out chip-down. Each entry caps the number of
# ``# contract: ok <rule-id> <reason>`` markers allowed for that
# rule. Adding a rule requires adding its row here; chipping down
# is the discipline (raise only with justification, lower as debt
# is closed). Replaces per-pack EXPECTED_*_OPT_OUT_CEILING constants
# for the per-rule pattern TP-110..115 establish. Single-purpose
# ceilings (EXPECTED_OPT_OUT_CEILING, EXPECTED_GRANDFATHER_CEILING,
# EXPECTED_HOOK_UTILS_PUBLIC_COUNT, EXPECTED_CONSTANT_CLIQUE_CEILING)
# stay as standalone constants — they don't share the rule-id grammar.
CONTRACT_CEILINGS: dict[str, int] = {
    # Exclusion BUDGET for the ESPALIER_MEMORY.md cap population contract
    # (tests/test_documented_claims.py::MEMORY_CAP_POPULATION). Unlike the
    # marker-based rules below, this one budgets REGISTRY exclusions: each is
    # a (path, line-regex, reason) row that silences a line the value scan
    # would otherwise count. Steady state is 1 -- the ESPALIER_MEMORY.md
    # session-log rows, which quote past state and must not be rewritten.
    # Raising this is the erosion path for that gate: prefer fixing the
    # prose, or narrowing a context shape, over adding exclusion #2.
    "memory-cap-population": 1,
    # TP-111: # contract: ok path-literal <reason> opt-outs for
    # hand-typed cc/ path strings in tools/cc/**/*.py (excluding
    # _paths.py). Steady-state ceiling is 0; raising requires
    # justification (the canonical fix is to import from _paths).
    # One justified opt-out: reflect_protocol's LOCAL_ONLY_PREFIXES keeps
    # cc/SURFACE_HANDOFF.md a string literal because the cross-twin parity
    # check ast.literal_eval's the whole tuple (a _paths reference would
    # break that parse and diverge from the zero-import engine twin).
    "path-literal": 1,
    # TP-110: # contract: ok hook-event-banner <reason> opt-outs for
    # hand-typed hook-event-name strings in hook docstring banners
    # or "hookEventName" JSON literals that intentionally diverge
    # from CHW. Steady-state ceiling is 0; the canonical fix is to
    # match the CHW spec for the hook script.
    "hook-event-banner": 0,
    # TP-112: # contract: ok denial-reason-fstring <reason> opt-outs
    # for inline f-string args to deny()/block() in
    # tools/cc/hooks/{write_guard,plan_guard,config_guard,stop_gate}.py
    # that intentionally diverge from the _denial_reasons.py templates.
    # Steady-state ceiling is 0; the canonical fix is to compose from
    # _denial_reasons.X.format(...) or assign a variable from
    # _denial_reasons.X and pass that.
    "denial-reason-fstring": 0,
    # TP-112: # contract: ok denial-reason-import <reason> opt-outs
    # for hooks that call deny()/block() but do not import
    # _denial_reasons (i.e., hooks composing all reasons from local
    # constants). Steady-state ceiling is 0; canonical fix is to
    # import _denial_reasons even if only one template is used.
    "denial-reason-import": 0,
    # TP-112: # contract: ok denial-reason-dead-template <reason>
    # opt-outs for templates defined in _denial_reasons.py that no
    # hook references (e.g., reserved-for-future-use constants kept
    # documented but not yet wired). Steady-state ceiling is 0; the
    # canonical fix is to delete the constant until a hook needs it.
    "denial-reason-dead-template": 0,
    # TP-113: # contract: ok marker-taxonomy <reason> opt-outs for
    # pyproject↔conftest marker taxonomy drift (e.g., a marker
    # transitionally declared in one surface ahead of the other
    # during a multi-step rollout). Steady-state ceiling is 0; the
    # canonical fix is to add/remove on both surfaces in lockstep.
    "marker-taxonomy": 0,
    # TP-114: # contract: ok severity-scale <reason> opt-outs for
    # transitional mentions of legacy severity tokens (BLOCKER,
    # MAJOR, MINOR, WRONG, CONFLICTING, VAGUE, CORRECT) in the
    # canonical surfaces (the code-reviewer agent body and the
    # pack-artifact checklist) during multi-step
    # vocabulary migrations. Steady-state ceiling is 0 — the
    # canonical fix is to complete the migration; opt-outs exist
    # for the in-flight window between coordinated edits.
    "severity-scale": 0,
    # TP-115: # contract: ok ci-yaml-hook-count <reason> opt-outs for
    # hand-typed hook-count literals in .github/workflows/*.yml that
    # intentionally freeze a past-state count (C-U01 out-of-reach
    # class — past-tense facts shouldn't be pinned for byte-equality).
    # Steady-state ceiling is 1 (the release.yml:95 historical
    # comment); raising requires justification — the canonical fix
    # for new claims is a subprocess assertion that derives the count
    # from live state (espalier audit . / pytest tests/test_hooks.py).
    "ci-yaml-hook-count": 1,
    # 2026-09-22: public top-level docs/*.md the doc index deliberately does
    # not link (tests/test_operator_docs.py::TestDocIndexCompleteness::
    # INDEX_EXEMPT). Steady state is 3 -- the index itself, the folder-ladder
    # CLAUDE.md and the aliases sidecar. Raising this is the erosion path for
    # that gate: the fix for a new red is a table row in docs/README.md.
    "doc-index-exempt": 3,
    # 2026-09-22: markers a plugin owns that pyproject declares so the suite
    # collects without the plugin (PLUGIN_OWNED_MARKERS above). Steady state
    # is 1 (pytest-timeout's `timeout`). A taxonomy marker never belongs here
    # -- the fix for a parity red is the conftest side.
    "plugin-owned-markers": 1,
}


# ── TP-114 severity-scale consolidation (Option A) ────────────────────

# Single canonical scale across all review surfaces (the code-reviewer
# agent + /preflight gates and the pack-artifact checklist). The parity
# test `tests/test_severity_scales.py` asserts each surface uses ONLY
# tokens from this set AND that the legacy tokens
# (LEGACY_SEVERITY_TOKENS below) do NOT appear in any of them.
CANONICAL_SEVERITY_SCALE: frozenset[str] = frozenset({
    "BLOCK", "WARN", "NIT", "PASS",
})

# Pre-TP-114 vocabularies (3 separate scales). Migration mapping:
# BLOCKER→BLOCK, MAJOR→WARN, MINOR→NIT (code-reviewer);
# WRONG→BLOCK, CONFLICTING→BLOCK, VAGUE→WARN, CORRECT→PASS
# (pack-artifact checklist). The migration consolidates 3
# vocabularies into 1; these tokens MUST be absent from the
# migrated surfaces (asserted by
# `test_surface_has_no_legacy_severity_tokens`).
LEGACY_SEVERITY_TOKENS: frozenset[str] = frozenset({
    "BLOCKER", "MAJOR", "MINOR",
    "WRONG", "CONFLICTING", "VAGUE", "CORRECT",
})
