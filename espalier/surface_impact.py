"""``espalier surface-impact`` — the shipped-surface obligation pre-flight (0-D).

The pack pre-flight validates a pack's ARTIFACT (0-A), its symbol reference
GRAPH (0-B), and Python-body duplication (0-C) — but none of those look at
whether the NEW FILES a pack ships satisfy the surface contracts that fire
only in the full suite: content-hygiene, registration/count pins, byte-mirror
parity, broken-links, onboarding-honesty, provenance, release classification.

A file added to any shipped surface is auto-enrolled in those contracts:
:func:`espalier.surface_contract.classify_release_path` falls through to
``"public"`` for every un-ruled path, and ``"public"`` opts the file into the
provenance census, the release archive, mirror-parity, and the count pins with
no opt-in. So a pack can pass 0-A/0-B/0-C clean and still fail the full suite on
a count-pin, a missing mirror, a hygiene leak, or a broken link.

``surface-impact`` reads a pack's declared ``### Added-paths`` and
``### Removed-paths`` (a path-shaped ``### Renamed`` entry is the removal of
its old name; a new CLI subcommand registered inside an existing file is
detected too), matches each to its surface, and prints the OBLIGATIONS the
full suite will demand — so the executor can bundle the implied SoT edits into
the plan up front. A removal names the SAME sites its addition enrolled it in,
in reverse (decrement the count, drop the row, let the mirror sync prune, refresh
the manifest): one table, never a reverse-worded copy. It also runs the cheap
content scans (:mod:`espalier.surface_hygiene`,
:data:`espalier.provenance_census.PROVENANCE_RE`) over any declared ADDED path
that already exists on disk; a removal is not scanned, the file is leaving.

It is an ADVISORY pre-flight, the same contract as ``scope-check``: it reports
an obligation map and exits ``2`` when a declared path classifies ``public``
(it will ship, or stop shipping, so it carries obligations to acknowledge);
``--accept-surface-gap "<reason>"`` flips that to ``0``. It never re-derives a
contract or auto-fixes an obligation — the full suite stays the actual gate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from espalier import surface_hygiene
from espalier.pack_manifest import (
    ADDED,
    CHANGED_SEMANTICS,
    REMOVED_PATH,
    RENAMED,
    affected_symbols_diagnostics,
    parse_pack,
)
from espalier.provenance_census import (
    PROVENANCE_RE,
    allowed_tokens,
    path_is_scanned,
)
from espalier.surface_contract import classify_release_path, off_self_host
from espalier._text import plural

# Adopter-facing body prefixes — the surfaces TestCommonTierAssetHygiene
# actually polices. The hygiene (internal-ID / self-host-vocab) scan applies
# ONLY here: running it over engine source (espalier/*.py) is a category error
# and self-matches surface_hygiene.py's own pattern definitions.
_HYGIENE_SCAN_PREFIXES = (".claude/", "espalier/assets/", "docs/", "memory/")

# ONE spelling, because the filter below keys on it. Five call sites listed this
# demand as a literal; a reworded copy at any one of them would have silently
# stopped being filtered, which is the "one fact, N restatements" class this
# repo keeps closing. Change the wording here and every site moves with it.
_PROVENANCE_DEMAND = "provenance: no build-history tags (espalier provenance .)"


def _applicable_demands(demands: list[str], adopter_tree: bool) -> list[str]:
    """Drop obligations that cannot be discharged on the tree being reported on.

    `espalier provenance` stands down off the self-host tree (`cli.cmd_provenance`,
    same `off_self_host` owner `_scan_existing` consults 400 lines below). So on an
    adopter tree this demand names a check that structurally cannot run -- and
    `.claude/commands/implement-pack.md` step 0-D tells the reader to work this
    map "as the checklist". Listing it there hands them a no-op and calls it an
    obligation; they run the verb, get exit 0, and tick it off.

    DROPPED, BUT NEVER SILENTLY -- see `_stand_down_note`. The first cut dropped
    without a word, reasoning that `_scan_existing` already returns silently and
    that nobody asked this report about provenance. The adversarial pass
    overturned that: they did not ask about provenance, but they DID type
    `surface-impact`, whose entire output contract is *this is the obligation
    list*. Shortening that list without saying so is nearer to `pre-release`
    printing "pass" than to leaving something unasked unmentioned -- and it
    makes a FALSE NEGATIVE from `is_self_host_repo` (5 signals, one a content
    hash over editable prose) indistinguishable from a clean short report.
    """
    if not adopter_tree:
        return demands
    return [d for d in demands if d != _PROVENANCE_DEMAND]


def _stand_down_note(report: SurfaceImpactReport) -> list[str]:
    """Footer disclosing that some obligations were withheld as inapplicable.

    Two failures this closes, both measured. (1) `--repo` defaults to `"."` and
    is not walked up to the repo root, so running the verb from a SUBDIRECTORY
    of this very repo produced a full report with every provenance row missing
    and nothing saying why. (2) `is_self_host_repo` pins a content hash over
    `write_guard.py`'s first 200 bytes -- editable prose -- so an ordinary
    reflow flips this tree to "adopter" and quietly shortens the checklist on
    the one tree where the census is the actual gate. The full suite catches
    that via `test_adopter_verb_stand_down.py::TestTheGateIsNotVacuousOnSelfHost`;
    this note catches it in the fast loop, by eye, at the moment it happens.
    """
    if not report.off_self_host:
        return []
    return [
        "Note: obligations that apply only to the Espalier-Harness source tree",
        "      were omitted (`espalier provenance` exits 0 without scanning here).",
        "      Seeing this on the harness's own repo means the self-host check",
        "      failed -- re-run from the repo root, or refresh the write_guard pin.",
        "",
    ]


@dataclass
class Obligation:
    """One surface a pack adds, plus the contracts the full suite will demand."""

    surface: str            # human label for the surface kind
    trigger: str            # the declared path (or symbol) that triggered it
    classification: str     # public / internal / transient / local_only; "" for a symbol
    demands: list[str] = field(default_factory=list)
    #: ``"added"`` (what every producer wrote before DEF-410j), ``"removed"``
    #: (a ``### Removed-paths`` entry) or ``"renamed"`` (a path-shaped
    #: ``### Renamed`` entry, reported as the removal of its old name). The
    #: demands are the SAME sites in every direction -- one table, never a
    #: reverse-worded copy; the renderer says what reverse means once.
    direction: str = "added"


@dataclass
class ContentHit:
    """A cheap-scan finding on a declared path that already exists on disk."""

    path: str
    kind: str               # "internal-id" | "self-host-vocab" | "provenance-tag"
    hits: list[str]


@dataclass
class SurfaceImpactReport:
    pack_id: str
    obligations: list[Obligation] = field(default_factory=list)
    content_hits: list[ContentHit] = field(default_factory=list)
    unmatched_public: list[str] = field(default_factory=list)
    #: Declared removals that classify ``public`` with no surface rule: they
    #: will stop shipping, and whatever enrolled them moves in reverse.
    unmatched_public_removed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: What the pack parser DROPPED -- a bullet under a routed sub-heading
    #: with no backticked token, a strike spelling it does not honour -- the
    #: same lines ``scope-check`` prints as ``!``. Without them a pack adding
    #: a public module as a bare path read ``[ok] No shipped-surface
    #: additions`` here (review of the §C7 lane, 2026-09-11).
    parser_notes: list[str] = field(default_factory=list)
    #: True when this report was built off the Espalier-Harness source tree,
    #: i.e. some obligations were withheld as inapplicable. Rendered as a
    #: footer so a SHORTER list is never mistaken for a shorter obligation.
    off_self_host: bool = False

    def public_additions(self) -> list[str]:
        """Declared paths that classify ``public`` — the ones that will ship."""
        return [
            o.trigger for o in self.obligations
            if o.classification == "public" and o.direction == "added"
        ]

    def public_removals(self) -> list[str]:
        """Declared removals (and renamed old names) that classify ``public``
        — the ones that will stop shipping, so every count pin, table row,
        regenerated index, mirror and manifest entry that enrolled them moves
        in reverse (DEF-410j)."""
        return [
            o.trigger for o in self.obligations
            if o.classification == "public" and o.direction != "added"
        ]

    def has_public_changes(self) -> bool:
        """True when something public will ship OR stop shipping -- the verb's
        exit-2 condition. Was ``has_public_additions`` until DEF-410j, when a
        removal declared nothing and a deleted shipped file passed 0-D clean."""
        return bool(
            self.public_additions()
            or self.public_removals()
            or self.unmatched_public
            or self.unmatched_public_removed
        )


# --------------------------------------------------------------------------- #
# Surface → obligations table.
#
# Ordered most-specific first; the FIRST matching rule wins. Each ``demands``
# entry names a SoT constant, contract class, or sync script the full suite
# enforces once the file lands — grounded against HEAD and cited by NAME so a
# reader can grep it. This table ORCHESTRATES the existing contracts; it does
# not re-derive them.
# --------------------------------------------------------------------------- #

# 3-way .claude mirror: source + packaged asset + dogfooding example.
_MIRROR_3WAY = (
    "3-way mirror parity: espalier/assets/claude/... + "
    "examples/dogfooding/.claude/... (scripts/sync_claude_mirrors.py --check; "
    "tests/test_package_resource_parity.py::TestAssetClaudeMirrorParity)"
)
_ASSET_HYGIENE = (
    "adopter-facing hygiene: no internal pack IDs / self-host vocab "
    "(tests/test_init_tier_split.py::TestCommonTierAssetHygiene)"
)


def _hook_demands(is_helper: bool) -> list[str]:
    count = (
        "EXPECTED_HOOK_HELPER_COUNT (tests/_surface_expected.py) + "
        "_HOOK_HELPERS (espalier/managed_inventory.py)"
        if is_helper
        else "EXPECTED_HOOK_COUNT + EXPECTED_HOOK_ENTRY_COUNT "
        "(tests/_surface_expected.py) + _CANONICAL_HOOK_SCRIPTS "
        "(espalier/surface_contract.py)"
    )
    demands = [
        f"count SoT: bump {count}",
        # NOT CLAUDE.md: its only numeral is "governs 10 of Claude Code's hook
        # EVENTS", which does not move with the hook count. CLAUDE.md's real
        # obligation is a table row, listed separately below for hook entries.
        "the hardcoded hook-count sites (README.md, docs/HOOKS.md, "
        "docs/CHEAT-SHEET.md)",
        "scripts/wheel_smoke.py packaged-hook SoT",
        "integrity manifest refresh (espalier integrity refresh)",
        "vendor mirror: espalier/_vendor/cc/hooks/... "
        "(scripts/sync_vendor_cc.py; tests/test_vendor_cc_parity.py)",
        _PROVENANCE_DEMAND,
    ]
    if not is_helper:
        demands[1:1] = [
            "settings wiring: .claude/settings.json hook registration",
            "freshness hook-count fragment (.espalier/freshness.json)",
            "cc/PACK_MANIFEST.txt regen",
            "CLAUDE.md '## Hooks' table row (row count is pinned by "
            "tests/test_agent_contracts.py::TestCommandTableMatchesFiles)",
            "tier membership: a hook that DENIES joins "
            "espalier/harness_config.py::GOVERNANCE_BLOCKING_HOOKS and the "
            "tools/cc/ci_guard.py mirror (tests/test_deny_markers.py pins the "
            "blocking set against the deny sites); a reporter needs nothing, "
            "the reporter tier derives",
        ]
    return demands


def classify_surface(rel_path: str) -> tuple[str, list[str]] | None:
    """Return ``(surface_label, demands)`` for ``rel_path``, or ``None``.

    ``None`` means no rule matched — an unclassified addition. If it also
    classifies ``public`` the caller warns that it will ship + be scanned
    with no declared obligations (a brand-new top-level dir usually).
    """
    p = rel_path.replace("\\", "/")
    base = p.rsplit("/", 1)[-1]

    if p.startswith(".claude/commands/") and p.endswith(".md"):
        demands = [
            "count SoT: bump EXPECTED_COMMAND_COUNT (tests/_surface_expected.py) "
            "and its == consumers",
            "CLAUDE.md '## Slash Commands' table row + README command-count claim",
            "cc/COMMANDS.md + cc/PACK_MANIFEST.txt regen",
            _MIRROR_3WAY,
            _ASSET_HYGIENE,
        ]
        if base == "implement-pack.md":  # noqa: SIM102
            # The one command body carrying a GENERATED region. It is both a
            # mirror target and a mirror source, so it is the only path here
            # where "run the .claude sync" is an incomplete instruction.
            demands.append(
                "its pack-artifact checklist region is GENERATED: edit "
                "tools/cc/pack_artifact_checklist.md, then run "
                "`python3 scripts/sync_checklist_regions.py` BEFORE "
                "sync_claude_mirrors.py -- a hand edit between the markers is "
                "discarded, and syncing only the mirrors propagates the stale "
                "region byte-perfectly"
            )
        return "slash command", demands
    if p.startswith(".claude/agents/") and p.endswith(".md"):
        return "agent", [
            "roster SoT: add to EXPECTED_UNIVERSAL_AGENTS "
            "(tests/_surface_expected.py, exact frozenset)",
            "AGENT_TIER (tests/test_agent_frontmatter_contract.py)",
            "README + CLAUDE.md agent tables + adopter-handoff section",
            _MIRROR_3WAY,
            _ASSET_HYGIENE,
        ]
    if p.startswith(".claude/skills/") and base == "SKILL.md":
        skill_demands = [
            "count SoT: bump EXPECTED_SKILL_COUNT (tests/_surface_expected.py) "
            "-- wheel_smoke.py's same-named value is DERIVED and cannot be bumped",
            "CLAUDE.md Skills table row",
            _FRONTMATTER_NAME_DEMAND,
            "cc/PACK_MANIFEST.txt regen",
            _MIRROR_3WAY,
            _ASSET_HYGIENE,
        ]
        if p == ".claude/skills/reflect/SKILL.md":
            # The second shipped body carrying a GENERATED region, for the same
            # reason implement-pack.md is: its checklist lives in an undeployed
            # tools/cc/ file, so the items are inlined and now generated.
            skill_demands.append(
                "its reasoning-review checklist region is GENERATED: edit "
                "tools/cc/reasoning_review_checklist.md, then run "
                "`python3 scripts/sync_checklist_regions.py` BEFORE "
                "sync_claude_mirrors.py -- a hand edit between the markers is "
                "discarded, and syncing only the mirrors propagates the stale "
                "region byte-perfectly"
            )
        return "skill", skill_demands
    if p in ("tools/cc/pack_artifact_checklist.md",
             "tools/cc/reasoning_review_checklist.md"):
        # The two .md files under tools/cc/ that are mirror SOURCES. Their
        # sibling (CLAUDE.md) stays unclassified on purpose: None is the signal
        # for "no declared obligations".
        return "fixed checklist (mirror SoT)", [
            "regenerate the inlined region: `python3 scripts/sync_checklist_regions.py`, "
            "THEN `python3 scripts/sync_claude_mirrors.py` -- chained, because the "
            "target is itself the source of the .claude mirrors",
            "keep digit-bearing pack ids OUT of the item block: the target is "
            "common-tier (tests/test_init_tier_split.py::TestCommonTierAssetHygiene). "
            "The file's header stamp is exempt and must stay -- "
            "espalier/provenance_census.py pins it",
            "this file is NOT deployed (tools/cc/*.md is outside the vendor row and "
            "INIT_TOOL_SCRIPTS), which is why the items are inlined at all",
        ]
    if p in ("README.md", "docs/QUICKSTART.md"):
        # The two carriers of a Python-sourced generated region. Declared here
        # because the mechanism that FORCES an obligation entry for the other
        # region family iterates espalier/mirror_registry.py -- and this family
        # deliberately carries no row there, a render-from-Python being no kind
        # of byte-mirror. So it arrived with neither an obligation row nor an
        # edit-time advisory, invisible to the one guard that would have said so.
        return "front-door doc (generated region carrier)", [
            "regions are GENERATED: fix the Python source, then run "
            "`python3 scripts/generate_doc_regions.py` -- never retype the block",
            "`--check` is the gate (tests/test_doc_regions.py::"
            "TestEveryRegionIsInParityWithItsGenerator)",
            "do NOT reword the hook-count bullet ('N hook entry scripts + N helper "
            "modules') in README, nor the '7 / 17 / 9 (agents / commands / skills)' "
            "line in QUICKSTART: between them they are the SOLE site of five "
            "numeric-contract regexes that assert they matched at least once, so a "
            "reword reds five parametrizations even with every number still correct "
            "(tests/test_documented_claims.py::TestNoStaleNumericContracts)",
        ]
    if p.startswith("tools/cc/hooks/") and p.endswith(".py"):
        return ("hook helper" if base.startswith("_") else "hook entry"), _hook_demands(
            base.startswith("_")
        )
    if p.startswith("scripts/") and p.endswith(".py"):
        return "dev script", [
            "roster SoT: add to EXPECTED_SCRIPT_NAMES (tests/_surface_expected.py); "
            "EXPECTED_SCRIPT_COUNT is derived from it -- do not hand-edit the count",
        ]
    if p.startswith("espalier/assets/docs/") and p.endswith(".md"):
        return "portable-knowledge doc asset", [
            # The discard leads, as it does on the claude-mirror row below. Every
            # demand after this one is work to do on the SOURCE; without this line
            # the list reads as work to do on the file just edited -- which
            # sync_asset_docs.py overwrites from docs/, so following it destroys
            # the edit and exits 0. Same defect the PostToolUse advisory carried.
            "do NOT hand-edit: generated from docs/ by scripts/sync_asset_docs.py "
            "-- an edit here is overwritten, not merged; re-apply it to the docs/ "
            "original, then sync",
            "source↔asset byte-parity (scripts/sync_asset_docs.py --check; "
            "tests/test_deploy_doc_parity.py::TestSourceAssetDocByteParity)",
            "if init-seeded: _SEED_DOC_REL_PATHS (order-sensitive) + its test "
            "mirror + _SEED_DOCS_WITH_ADAPT_HEADER (espalier/managed_inventory.py)",
            "_ALLOWED_UNDEPLOYED_DOC_REFS disjointness (tests/test_deploy_doc_parity.py)",
            "_reinject._DOCS_ASSET_TAILS (tools/cc/hooks/_reinject.py) if a reinjected tail",
            "onboarding-honesty list",
            _ASSET_HYGIENE,
        ]
    if p.startswith("espalier/assets/seed/") and p.endswith(".md"):
        return "adopter seed stub", [
            "package-data glob: assets/seed/*.md (pyproject.toml) — the ONLY "
            "thing shipping it; a miss deploys fewer files with no source symptom",
            "_SEED_DOC_REL_PATHS + _SEED_ASSET_SOURCES (espalier/managed_inventory.py)",
            "_ALLOWED_UNDEPLOYED_DOC_REFS disjointness (tests/test_deploy_doc_parity.py)",
            "_CENSUS_FORCE_SCAN (espalier/provenance_census.py) — exact-path; "
            "assets/ is blanket-excluded and a stub has no scanned SoT",
            "deployed-file count moves — re-measure by driving a real init, not by grep",
            _ASSET_HYGIENE,
        ]
    # Pinned by test_deploy_doc_parity, NOT the generic packaged-asset rule below:
    # it sits outside assets/docs/**, so that module's rglob never reaches it and
    # it carries its own explicitly-added guard. Naming the wrong parity module
    # sends the reader to a test that cannot fail for this file.
    # Both legs of the claude mirror. The generic packaged-asset rule below cites
    # the parity test but not the generator, and the dogfooding leg matched no rule
    # at all -- so the two mirrors an operator is most likely to hand-edit were the
    # two least likely to say what regenerates them.
    if p.startswith("espalier/assets/claude/") or p.startswith(
        "examples/dogfooding/.claude/"
    ):
        return "generated claude mirror", [
            "do NOT hand-edit: regenerated from .claude/{agents,commands,skills} "
            "by scripts/sync_claude_mirrors.py -- an edit here is overwritten, "
            "not merged (tests/test_package_resource_parity.py)",
            "re-apply the change to the .claude/ source, then run the sync",
        ]
    # The inverted row's SOURCE side. Without this the generic packaged-asset rule
    # below answers, and it says "byte-mirror sync to its source SoT" -- asserting
    # this file is a copy of something. It is the something. On the one row where
    # direction is the entire point, that is the wrong answer, not a vague one.
    if p == "espalier/assets/github/workflows/harness-guard.yml":
        return "workflow asset (source of truth)", [
            "INVERTED: this IS the SoT; .github/workflows/harness-guard.yml is "
            "generated FROM it -- run scripts/sync_github_workflow_asset.py after "
            "editing (tests/test_package_resource_parity.py::TestRootMirrorParity"
            "::test_root_workflow_mirrors_package)",
            "integrity: the generated root copy is in _integrity.MANIFEST_FILES -- "
            "run `espalier integrity refresh .` after syncing",
            _ASSET_HYGIENE,
        ]
    if p.startswith("espalier/assets/task-packs/"):
        return "packaged folder router", [
            "do NOT hand-edit: generated from task-packs/CLAUDE.md by "
            "scripts/sync_asset_docs.py -- an edit here is overwritten, not "
            "merged; re-apply it to the task-packs/ original, then sync",
            "byte-mirror of the task-packs/ router "
            "(scripts/sync_asset_docs.py; "
            "tests/test_deploy_doc_parity.py::TestSourceAssetDocByteParity)",
            _ASSET_HYGIENE,
        ]
    if p.startswith("espalier/assets/"):
        return "packaged asset", [
            "byte-mirror sync to its source SoT "
            "(tests/test_package_resource_parity.py)",
            "_CENSUS_FORCE_SCAN (espalier/provenance_census.py) if not byte-pinned "
            "to a scanned SoT",
            _ASSET_HYGIENE,
        ]
    # espalier/_vendor/ hosts TWO mirror families with DIFFERENT sync scripts, so
    # the narrower one must be tested FIRST. A bare `_vendor/` prefix answers for
    # selfcheck_tests/ with sync_vendor_cc.py -- a wrong remedy rather than a
    # missing one, and the worse failure of the two: the named script cannot fix a
    # selfcheck drift and exits 0 having changed nothing, so the reader rules the
    # cause out. Ordering here is load-bearing; tests/test_surface_impact.py pins
    # both directions.
    if p.startswith("espalier/_vendor/selfcheck_tests/"):
        return "selfcheck mirror", [
            "do NOT hand-edit: generated from a CURATED tests/ subset by "
            "scripts/sync_selfcheck_tests.py -- an edit here is overwritten, not "
            "merged; re-apply it to the tests/ original, then sync "
            "(tests/test_selfcheck_tests_parity.py reds on drift)",
            "not a plain byte-copy: sync splits BYTE_MIRRORED from TRANSFORMED, and "
            "pytest.ini is authored from a literal with no source file",
        ]
    if p.startswith("espalier/_vendor/") and p.endswith(".py"):
        return "vendored mirror", [
            "do NOT hand-edit: generated from tools/cc/ by scripts/sync_vendor_cc.py "
            "-- an edit here is overwritten, not merged; re-apply it to the "
            "tools/cc/ original, then sync "
            "(tests/test_vendor_cc_parity.py reds on drift)",
        ]
    if p.startswith("espalier/scanners/") and p.endswith(".py"):
        return "scanner module", [
            _SCANNER_STDLIB_DEMAND,
            _PROVENANCE_DEMAND,
        ]
    if p.startswith("espalier/") and p.endswith(".py"):
        return "engine module", [
            _PROVENANCE_DEMAND,
            _ENGINE_IMPORTS_DEMAND,
        ]
    if p.startswith("tools/cc/") and p.endswith(".py"):
        return "standalone tool", [
            _TOOL_ZERO_IMPORTS_DEMAND,
            "vendor mirror: espalier/_vendor/cc/... "
            "(scripts/sync_vendor_cc.py; tests/test_vendor_cc_parity.py)",
            _PROVENANCE_DEMAND,
        ]
    if p.startswith("tools/cc/") and p.endswith(".cmd"):
        # The Windows statusline shim (DEF-729): a deploy source like the .py
        # files, so the same mirror row, plus the two batch-only constraints.
        return "deployed shim", [
            "vendor mirror: espalier/_vendor/cc/... "
            "(scripts/sync_vendor_cc.py; tests/test_vendor_cc_parity.py)",
            "no label search -- no goto, no call to a label (cmd.exe misreads "
            "one in an LF-only file; .gitattributes pins *.cmd eol=lf), ASCII "
            "only, exit 0 on the fallback branch; the shim's own fallback text "
            "equals cli.STATUSLINE_FALLBACK_TEXT (tests/test_hook_exec_form.py "
            "pins every tools/cc/*.cmd)",
        ]
    # "Is this path a shipped TEST MODULE?" (tests/ prefix, .py) — a third, distinct
    # "is it a test path?" question. Cf. strengthen._is_test_path (coverage view) and
    # test_loosening.iter_test_files (test_*.py files). Deliberately divergent; leave separate.
    if p.startswith("tests/") and p.endswith(".py"):
        return "test module", [
            _TEST_NAMING_DEMAND,
        ]
    if p.startswith("docs/") and p.endswith(".md"):
        return "shipped doc", [
            _PROVENANCE_DEMAND,
            _DOC_VOCAB_DEMAND,
            "broken-links scan (all relative links resolve)",
            "if init-seeded: also the seed-doc obligations "
            "(_SEED_DOC_REL_PATHS + asset byte-mirror + _DOCS_ASSET_TAILS)",
        ]
    # The SoT side of the task-packs router mirror. Without this it classified as
    # None, so editing the file you are SUPPOSED to edit surfaced no sync at all --
    # the mirror rules only ever answered for the copy.
    if p == "task-packs/CLAUDE.md":
        return "mirrored folder router", [
            "byte-mirrored to espalier/assets/task-packs/CLAUDE.md "
            "(scripts/sync_asset_docs.py; "
            "tests/test_deploy_doc_parity.py::TestSourceAssetDocByteParity)",
            _ROUTER_VOCAB_DEMAND,
        ]
    # The ONE inverted row: the packaged asset is the SoT and this root file is
    # generated from it. Every other workflow in this directory is edited in place,
    # so the rule is right most of the time and confidently wrong here -- which is
    # exactly the shape that produces a self-assured hand-edit. Exact-path, never a
    # .github/workflows/ prefix.
    if p == ".github/workflows/harness-guard.yml":
        return "generated workflow mirror", [
            "INVERTED: the SoT is espalier/assets/github/workflows/harness-guard.yml "
            "and THIS file is generated -- edit the asset, not this copy",
            "re-apply the change to the asset, THEN run "
            "scripts/sync_github_workflow_asset.py -- running it against an edited "
            "root file overwrites the edit (tests/test_package_resource_parity.py"
            "::TestRootMirrorParity::test_root_workflow_mirrors_package)",
            "integrity: this path is in _integrity.MANIFEST_FILES -- "
            "run `espalier integrity refresh .` after syncing",
        ]
    if p.startswith("bench/corpus/") and base.startswith("BC-") and p.endswith(".json"):
        return "bypass-class corpus", [
            "BC-NNN numbering contiguity",
            "BASELINE_INVOKERS wiring (bench/run_benchmark.py)",
            "scoreboard / RESULTS.md regen (python3 bench/run_benchmark.py --update-canonical)",
            "README's class-count sentence ('Tested against N in-scope bypass classes'; "
            "pinned to the directory by tests/test_bench_corpus_schema.py)",
        ]
    # A top-level bench script is a tracked ORACLE and ships in the archive.
    # Top level only (one slash): bench/corpus/ answers above, bench/end_to_end/
    # is its own harness with its own README, and a prefix here would swallow
    # both. Until 2026-09-14 a new oracle declared zero obligations, so three of
    # four never reached the README inventory (DEF-654).
    if p.startswith("bench/") and p.count("/") == 1 and p.endswith(".py"):
        return "bench oracle", [
            "bench/README.md: the 'Curated, tracked' list AND the layout tree "
            "(both derived from the tracked tree by "
            "tests/test_benchmark_release_hygiene.py -- an absent name reds)",
            "if it carries a ROWS table: a '<N> of <N> rows' docstring sentence "
            "and a gap clause that moves with KNOWN_GAPS "
            "(tests/test_write_guard.py::TestBenchGuardFixture)",
            "release surface: no machine-local path "
            "(tests/test_no_internal_codenames.py::TestNoMachineLocalPaths), "
            "no pointer at a gitignored record",
            _PROVENANCE_DEMAND,
            "scripts/host_check.py: a cell if it should run on the other host "
            "(tests/test_host_check.py pins the step set)",
        ]
    return None


# A new CLI verb is registered INSIDE an existing file (espalier/cli.py), so it
# is a Changed-semantics edit, not an added path — the path rules above never
# see it. Detect it from the affected symbols so the tool self-catches its own
# subcommand additions.
_CLI_VERB_RE = re.compile(r"^cmd_[a-z0-9_]+$")


def _cli_verb_obligation(
    symbol_names: list[str], direction: str = "added",
) -> Obligation | None:
    """One CLI-subcommand obligation if any ``cmd_*`` / ``build_parser`` symbol
    is touched — the cheat-sheet CLI-parity contract the full suite enforces,
    in both directions (a removed verb whose cheat-sheet line stays reds the
    same parity test an added verb without one does)."""
    triggers = [
        n for n in symbol_names if _CLI_VERB_RE.match(n) or n == "build_parser"
    ]
    if not triggers:
        return None
    verbs = sorted(n for n in triggers if n != "build_parser")
    return Obligation(
        surface="CLI subcommand (espalier verb)",
        trigger=", ".join(verbs) if verbs else "build_parser",
        classification="",  # a symbol edit inside an existing file, not a new path
        demands=[
            "docs/CHEAT-SHEET.md: the verb's line -- list it when added, drop it "
            "when removed (tests/test_documented_claims.py::TestCheatSheetCliParity "
            "pins both directions)",
            "any CLI-verb count claim in CLAUDE.md / README",
        ],
        direction=direction,
    )


def _warn_ambiguous(report: SurfaceImpactReport, tokens: list[str], heading: str) -> None:
    """Never silently drop: a token that is neither a recognized path nor a bare
    Python identifier is genuinely ambiguous — surface it rather than bucketing
    it into the symbol residue (where it would vanish with no obligation). Also
    catch a filey token whose suffix is not whitelisted yet still reduces to a
    valid identifier (``go.mod`` -> ``go_mod``, ``configure.ac``): the ``not
    isidentifier`` test alone lets those slip. A lowercase alpha suffix <=5
    chars reads as a file extension; a dotted SYMBOL (``Klass.DEFAULT``) has an
    UPPERCASE tail so ``looks_filey`` stays False and it is left as a symbol.
    One helper for every heading: the first cut ran it over Added-paths only,
    and the identical token under Removed-paths vanished (DEF-410j review)."""
    for tok in tokens:
        reduced = tok.replace(".", "_")
        suffix = tok.rsplit(".", 1)[-1] if "." in tok else ""
        looks_filey = (
            "." in tok and suffix.isalpha() and suffix.islower() and len(suffix) <= 5
        )
        if not reduced.isidentifier() or looks_filey:
            report.warnings.append(
                f"ambiguous {heading} entry {tok!r}: not a recognized file path "
                f"nor a bare symbol — declare it explicitly (a path, or path::symbol)"
            )


# Demands that police the CONTENT of the file itself and have no reverse: a
# departing file cannot carry a provenance tag, a vocabulary leak, a forbidden
# import or a mis-named test. Filtered out of a removal's obligation at the sink
# (a filter, not a reverse-worded copy, so the one-table rule holds); the same
# shape as `_applicable_demands`, which drops what cannot be discharged on the
# tree, this drops what cannot be discharged on a file that is leaving.
_SCANNER_STDLIB_DEMAND = (
    "stdlib-only: no third-party imports (tests/test_contracts.py scanner-isolation)"
)
_ENGINE_IMPORTS_DEMAND = (
    "shipped in the wheel — imports from espalier/ only "
    "(no `import tools`, tests/test_contracts.py)"
)
_TOOL_ZERO_IMPORTS_DEMAND = "zero espalier imports (tests/test_contracts.py)"
_TEST_NAMING_DEMAND = "test-naming per docs/CONVENTIONS.md (TestX / test_specific_behavior)"
_FRONTMATTER_NAME_DEMAND = "frontmatter name == dir (all mirrors)"
_DOC_VOCAB_DEMAND = "cheat-sheet + retired-vocab hygiene"
_ROUTER_VOCAB_DEMAND = "ships to adopters — no internal pack IDs / self-host vocab"


def _content_only_demands() -> frozenset[str]:
    return frozenset({
        _PROVENANCE_DEMAND,
        _ASSET_HYGIENE,
        _SCANNER_STDLIB_DEMAND,
        _ENGINE_IMPORTS_DEMAND,
        _TOOL_ZERO_IMPORTS_DEMAND,
        _TEST_NAMING_DEMAND,
        _FRONTMATTER_NAME_DEMAND,
        _DOC_VOCAB_DEMAND,
        _ROUTER_VOCAB_DEMAND,
    })


# Top-level shipped files that carry no extension but ARE files (not identifiers).
# NB: MANIFEST.in is covered by the "in" suffix rule below — do not re-list it.
_EXTENSIONLESS_ROOT_FILES = frozenset({
    "Makefile", "Dockerfile", "LICENSE", "NOTICE", "COPYING",
})
# Suffixes that mark a token as a file path (with a dot). Kept broad enough to
# cover the common top-level build/config files a pack might add at the repo root.
# Purpose-scoped sibling of scope_walker.INCLUDED_EXTS (a dotted Path.suffix gate)
# and proofs.TEXT_SUFFIXES — same idea, un-dotted token form here; do NOT collapse.
# sister-site: ok purpose-scoped: token recognizer; sibling of scope_walker.INCLUDED_EXTS / proofs.TEXT_SUFFIXES (see comment above)
_PATH_SUFFIXES = frozenset({
    "py", "md", "json", "toml", "yml", "yaml", "txt",
    "cfg", "ini", "in", "sh", "ps1", "bat", "rst", "lock",
})


def _looks_like_path(token: str) -> bool:
    """A declared ``### Added-paths`` entry is a new FILE path, not a symbol.

    ``### Added-paths`` mixes real new files (``espalier/foo.py``) with
    ``path::symbol`` added-symbols that ``parse_pack`` reduces to a bare
    symbol name (``_SEED_ADAPT_HEADER``). Only the former is a new shipped
    surface; a bare symbol is an addition INSIDE an existing file and carries
    no path-level obligation of its own. A too-narrow recognizer silently DROPS
    a real top-level shipped file (Makefile, setup.cfg, .flake8) — no obligation,
    no warning — so widen conservatively and let ``build_report`` warn on the
    genuinely ambiguous residue rather than dropping it.
    """
    if "/" in token:
        return True
    # A leading-dot config dotfile (.flake8, .gitignore, .editorconfig) is always a
    # file — a reduced ``path::symbol`` is a bare Python identifier and CANNOT start
    # with a dot, so this is unambiguous.
    if token.startswith("."):
        return True
    if token in _EXTENSIONLESS_ROOT_FILES:
        return True
    return "." in token and token.rsplit(".", 1)[-1] in _PATH_SUFFIXES


def build_report(repo_root: Path, pack_path: Path) -> SurfaceImpactReport:
    """Parse ``pack_path`` and derive its shipped-surface obligation map."""
    manifest = parse_pack(pack_path)
    report = SurfaceImpactReport(pack_id=manifest.pack_id)
    # The parser's own account of what it could not read, on the same text
    # parse_pack read (the same replacement decoding).
    report.parser_notes = affected_symbols_diagnostics(
        pack_path.read_text(encoding="utf-8", errors="replace")
    )
    # Resolved once HERE, for the demand filter and the report flag. Not once
    # per process: `_scan_existing` below re-asks per existing file (pre-dating
    # this call and left alone -- it is a pure function of `repo_root`, so the
    # answers cannot disagree; the cost is a repeated 5-signal read).
    adopter_tree = off_self_host(repo_root)

    added_all = [s.name for s in manifest.affected_symbols if s.change_type == ADDED]
    added = [n for n in added_all if _looks_like_path(n)]
    added_symbols = [n for n in added_all if not _looks_like_path(n)]
    _warn_ambiguous(report, added_symbols, "Added-paths")
    changed = [
        s.name
        for s in manifest.affected_symbols
        if s.change_type == CHANGED_SEMANTICS
    ]

    for path in added:
        classification = classify_release_path(path)
        matched = classify_surface(path)
        if matched is None:
            # Unclassified: only noteworthy if it would ship.
            if classification == "public":
                report.unmatched_public.append(path)
            continue
        label, demands = matched
        report.obligations.append(
            Obligation(
                surface=label,
                trigger=path,
                classification=classification,
                demands=demands,
            )
        )
        # Cheap content scan over any declared path that already exists on disk
        # (a pre-existing file the pack promotes / relocates).
        _scan_existing(repo_root, path, report)

    # CLI verbs come from added-symbols OR changed symbols (a pack usually
    # files `cli.py::cmd_x` + `build_parser` under Changed-semantics).
    verb = _cli_verb_obligation(added_symbols + changed)
    if verb is not None:
        report.obligations.append(verb)

    # Removed paths (DEF-410j): the SAME classifier, so a removal names exactly
    # the sites its addition enrolled it in -- one table, never a reverse-worded
    # copy (a prefix rule that swallowed a sibling would name the wrong remedy
    # in both directions alike, which is the point of sharing it). No content
    # scan: the file is leaving. A path-shaped `### Renamed` entry is the
    # removal of its OLD name -- the parser keeps a bullet's first token, after
    # reading the `(none ...)` and spaced `path :: symbol` spellings real packs
    # use -- and the new name belongs under Added-paths; the renderer says so.
    # A bare symbol under either heading is an edit inside an existing file and
    # carries no path-level obligation, as for additions; a removed `cmd_*` is
    # the verb obligation in reverse; an ambiguous token warns, as for additions.
    for direction, change_type, heading in (
        ("removed", REMOVED_PATH, "Removed-paths"),
        ("renamed", RENAMED, "Renamed"),
    ):
        names = [s.name for s in manifest.affected_symbols if s.change_type == change_type]
        residue = [n for n in names if not _looks_like_path(n)]
        _warn_ambiguous(report, residue, heading)
        verb = _cli_verb_obligation(residue, direction=direction)
        if verb is not None:
            report.obligations.append(verb)
        for name in names:
            if not _looks_like_path(name):
                continue
            classification = classify_release_path(name)
            matched = classify_surface(name)
            if matched is None:
                if classification == "public":
                    report.unmatched_public_removed.append(name)
                continue
            label, demands = matched
            report.obligations.append(
                Obligation(
                    surface=label,
                    trigger=name,
                    classification=classification,
                    demands=demands,
                    direction=direction,
                )
            )

    # Filtered AT THE SINK, over every obligation, rather than at the one
    # append site above. `_cli_verb_obligation` appends straight to the list,
    # so a per-call-site filter covered one of the two producers -- and the
    # miss was invisible: adding a provenance demand to the CLI-verb list left
    # the whole new test class green while the defect shipped to every adopter
    # who declares a `cmd_*` symbol. A new producer joins this loop for free.
    content_only = _content_only_demands()
    for obligation in report.obligations:
        obligation.demands = _applicable_demands(obligation.demands, adopter_tree)
        if obligation.direction != "added":
            # A departing file cannot carry a tag, a leak or a forbidden import.
            obligation.demands = [d for d in obligation.demands if d not in content_only]
    report.off_self_host = adopter_tree

    return report


def _provenance_applies(rel: str) -> bool:
    """Mirror the provenance census's own scan decision for ``rel``.

    Delegates to :func:`espalier.provenance_census.path_is_scanned` rather
    than re-deriving it. This previously re-implemented the prefix and
    force-scan halves inline and omitted the whole-file allowlist entirely,
    so every ``_ALLOWLISTED_FILES`` entry was reported as carrying a
    provenance obligation the census would never raise. Two enumerations of
    the same rule are exactly the drift this module's own guard exists to
    catch, so there is only one now.
    """
    return path_is_scanned(rel)


def _scan_existing(repo_root: Path, rel_path: str, report: SurfaceImpactReport) -> None:
    """Run the cheap content scans over ``rel_path`` if it exists on disk.

    Each scan is scoped to the surface its contract actually polices: hygiene
    only on adopter-facing bodies, provenance only on census-scanned paths.
    """
    # A declared path may carry a glob / brace token (`a/{b,c}.md`) — only scan
    # a concrete file that actually resolves.
    if any(ch in rel_path for ch in "{}*?"):
        return
    abs_path = (repo_root / rel_path).resolve()
    if not abs_path.is_file():
        return
    try:
        text = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    p = rel_path.replace("\\", "/")
    # The obligation MAP below is adopter-useful; these two CONTENT scans are
    # not, and were measured firing on an adopter's own files. `internal_id_hits`
    # and `self_host_vocab_hits` police ESPALIER's vocabulary, and PROVENANCE_RE
    # matches `TP-`/`TQ-`/`XPLAT-`, which collide with ordinary ticket prefixes
    # -- an adopter doc reading "See ticket ACME-4821" was reported as carrying a
    # build-history tag, at exit 2, from a verb `/implement-pack` step 0-D runs.
    # Same defect as the three CLI verbs gated in cli.py, at a VISIBLE verb the
    # hidden-command accounting could never have seen.
    if off_self_host(repo_root):
        return
    if p.startswith(_HYGIENE_SCAN_PREFIXES):
        id_hits = surface_hygiene.internal_id_hits(text)
        if id_hits:
            report.content_hits.append(ContentHit(rel_path, "internal-id", id_hits))
        vocab_hits = surface_hygiene.self_host_vocab_hits(text)
        if vocab_hits:
            report.content_hits.append(
                ContentHit(rel_path, "self-host-vocab", vocab_hits)
            )
    if _provenance_applies(p):
        # Per-token, mirroring the census: an _ALLOWED_HITS entry forgives
        # specific tags in this file, it does NOT exempt the file. A second,
        # un-allowlisted tag in the same file is still reported.
        prov_hits = sorted(set(PROVENANCE_RE.findall(text)) - allowed_tokens(p))
        if prov_hits:
            report.content_hits.append(ContentHit(rel_path, "provenance-tag", prov_hits))


def render_report(report: SurfaceImpactReport, pack_rel: str) -> str:
    """Render the obligation map as the operator-facing report body."""
    lines: list[str] = []
    lines.append(f"\n{report.pack_id} surface-impact pre-flight")
    lines.append("=" * 40)
    lines.append(f"Pack: {pack_rel}")
    n_added = sum(1 for o in report.obligations if o.direction == "added")
    n_removed = len(report.obligations) - n_added
    n_public = len(report.public_additions())
    n_public_removed = len(report.public_removals())
    any_removal = bool(n_removed or report.unmatched_public_removed)
    header = f"Declares {plural(n_added, 'surface addition')}"
    if any_removal:
        header += f", {plural(n_removed, 'surface removal')}"
    header += f"; {n_public} classify public (will ship)"
    if any_removal:
        header += f", {n_public_removed} public (will stop shipping)"
    lines.append(header + ".")
    lines.append("")

    if (
        not report.obligations
        and not report.unmatched_public
        and not report.unmatched_public_removed
        and not report.warnings
        and not report.parser_notes
    ):
        lines.append("[ok] No shipped-surface additions or removals declared.")
        lines.append("")
        lines.extend(_stand_down_note(report))
        return "\n".join(lines)

    for ob in report.obligations:
        tag = f" [{ob.classification}]" if ob.classification else ""
        kind = "" if ob.direction == "added" else f" ({ob.direction})"
        lines.append(f"* {ob.surface}{kind}: {ob.trigger}{tag}")
        if ob.direction != "added":
            # Said once, here, rather than as a reverse-worded copy of every
            # demand below: the sites are the same, the verb is the inverse.
            # The one obligation a removal carries that an addition never does
            # is INBOUND: an addition cannot break a citation, a removal can.
            lines.append(
                "    - direction: the same sites in reverse -- decrement the count "
                "SoT, drop the table row and regenerate the indexes, refresh the "
                "integrity manifest, and sweep INBOUND references (docs, tests and "
                "hook string literals that cite the path)"
            )
            if any(
                "sync_asset_docs.py" in d or "asset byte-mirror" in d for d in ob.demands
            ):
                # The one named sync that copies source -> asset and never
                # enumerates the asset side: an orphaned copy passes --check.
                lines.append(
                    "    - the asset-doc sync never prunes: delete the copy under "
                    "espalier/assets/ by hand (scripts/sync_asset_docs.py copies "
                    "source to asset and reports parity over an orphan)"
                )
            else:
                lines.append(
                    "    - the mirror sync prunes its copies (claude-mirrors, "
                    "vendor-cc, selfcheck-tests); run it after the delete"
                )
            if ob.direction == "renamed":
                lines.append(
                    "    - a rename is read as the removal of the OLD name; declare "
                    "the new path under ### Added-paths so its own obligations are "
                    "enrolled"
                )
        for d in ob.demands:
            lines.append(f"    - {d}")
        lines.append("")

    if report.unmatched_public:
        lines.append(f"{plural(len(report.unmatched_public), 'unclassified public addition')} -- will be scanned + shipped:")
        for path in report.unmatched_public:
            lines.append(f"  [!] {path}")
            lines.append(
                "      classifies public with no surface rule; add a "
                "classify_release_path rule if this should be internal/local_only."
            )
        lines.append("")

    if report.unmatched_public_removed:
        lines.append(
            f"{plural(len(report.unmatched_public_removed), 'unclassified public removal')} "
            "-- will stop shipping:"
        )
        for path in report.unmatched_public_removed:
            lines.append(f"  [!] {path}")
            lines.append(
                "      classifies public with no surface rule; whatever enrolled it "
                "(a count pin, a mirror, the release manifest) moves in reverse -- "
                "check the full suite's contracts by hand."
            )
            if path.endswith("/"):
                # A directory has no surface rule; its files do. This is the
                # shape a removal usually takes and an addition rarely does.
                lines.append(
                    "      a directory matches no surface rule -- declare the "
                    "concrete file(s) it holds (e.g. .claude/skills/<name>/SKILL.md) "
                    "so the count pin and mirror they enrolled in are named."
                )
        lines.append("")

    if report.content_hits:
        lines.append("Content scan (declared paths already on disk):")
        for hit in report.content_hits:
            lines.append(f"  [!] {hit.path} [{hit.kind}]: {', '.join(hit.hits)}")
        lines.append("")

    if report.warnings:
        lines.append(f"{plural(len(report.warnings), 'ambiguous declaration')} -- could not classify path vs symbol:")
        for w in report.warnings:
            lines.append(f"  [?] {w}")
        lines.append("")

    if report.parser_notes:
        lines.append(f"{plural(len(report.parser_notes), 'parser note')} -- declarations the walk cannot see:")
        for n in report.parser_notes:
            lines.append(f"  [!] {n}")
        lines.append("")

    lines.extend(_stand_down_note(report))
    return "\n".join(lines)
