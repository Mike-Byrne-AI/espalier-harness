"""Tests for ``espalier.surface_impact`` — the 0-D shipped-surface obligation
pre-flight.

The pre-flight reads a pack's declared ``### Added-paths`` (and a new CLI
subcommand), matches each to its surface, and emits the count pins / mirrors /
hygiene / provenance obligations the full suite will demand. These tests pin:

- ``classify_surface`` maps each surface type to its obligation set;
- ``build_report`` treats a bare ``path::symbol`` addition as a symbol, not a
  new shipped path (the retro-catch surfaced this);
- a new ``cmd_*`` verb emits the cheat-sheet CLI-parity obligation;
- a TP-271a-shaped pack (dev script + portable-knowledge doc asset) surfaces
  the script-count + asset-byte-mirror obligations it tripped — the regression
  proof. (The real-file run ``surface-impact task-packs/Done/TP-271a-*.md`` was
  done manually at execution; ``task-packs/Done/`` is gitignored, so the committed
  pin is a synthetic fixture of the same shape.)
- the CLI exit-code contract (0 report / 1 bad path / 2 public addition).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from espalier.cli import cmd_surface_impact
from espalier.surface_impact import build_report, classify_surface


def _write_pack(
    tmp_path: Path,
    *,
    added: tuple[str, ...] | list[str] = (),
    changed: tuple[str, ...] | list[str] = (),
    removed: tuple[str, ...] | list[str] = (),
    renamed: tuple[str, ...] | list[str] = (),
    pack_id: str = "TP-999",
) -> Path:
    """Write a minimal fixture pack declaring ``added`` / ``changed`` /
    ``removed`` / ``renamed`` symbols."""
    added_block = "\n".join(f"- `{a}`" for a in added) or "- (none)"
    changed_block = "\n".join(f"- `{c}`" for c in changed) or "- (none)"
    removed_block = "\n".join(f"- `{r}`" for r in removed) or "- (none)"
    renamed_block = "\n".join(f"- `{r}`" for r in renamed) or "- (none)"
    body = (
        f"# {pack_id} — fixture\n\n"
        "## Affected symbols\n\n"
        f"### Added-paths\n{added_block}\n\n"
        f"### Changed-semantics\n{changed_block}\n\n"
        f"### Removed-paths\n{removed_block}\n\n"
        f"### Renamed\n{renamed_block}\n"
    )
    p = tmp_path / f"{pack_id}-fixture.md"
    p.write_text(body, encoding="utf-8")
    return p


class TestClassifySurface:
    def test_slash_command(self) -> None:
        label, demands = classify_surface(".claude/commands/foo.md")
        assert label == "slash command"
        assert any("EXPECTED_COMMAND_COUNT" in d for d in demands)
        assert any("mirror" in d.lower() for d in demands)

    def test_agent(self) -> None:
        label, demands = classify_surface(".claude/agents/foo.md")
        assert label == "agent"
        assert any("EXPECTED_UNIVERSAL_AGENTS" in d for d in demands)

    def test_skill(self) -> None:
        label, demands = classify_surface(".claude/skills/foo/SKILL.md")
        assert label == "skill"
        assert any("EXPECTED_SKILL_COUNT" in d for d in demands)

    def test_skill_count_obligation_names_the_bumpable_sot(self) -> None:
        """The count SoT must be the editable literal, not the derived twin.

        Pinning the symbol name alone is not enough: ``EXPECTED_SKILL_COUNT``
        exists in BOTH ``tests/_surface_expected.py`` (a literal, which is what
        an executor must bump) and ``scripts/wheel_smoke.py`` (a
        ``_count_packaged_assets()`` call, which cannot be bumped). The
        obligation named the derived one, so an executor following it edited
        the one place already correct -- and the symbol-only assertion above
        stayed green throughout.
        """
        _, demands = classify_surface(".claude/skills/foo/SKILL.md")
        sot = [d for d in demands if "EXPECTED_SKILL_COUNT" in d]
        assert sot, "no count-SoT obligation emitted for a skill addition"
        assert all("tests/_surface_expected.py" in d for d in sot)
        assert not any(
            d.startswith("count SoT") and "bump EXPECTED_SKILL_COUNT (scripts/" in d
            for d in sot
        )

    def test_provenance_obligation_mirrors_the_census_scan_decision(self) -> None:
        """surface-impact must not demand provenance where the census is blind.

        Two enumerations of "what the census covers" had drifted: the prefix
        and force-scan halves were imported from the census, but the
        whole-file allowlist was not, so every ``_ALLOWLISTED_FILES`` entry
        reported an obligation the scanner would never raise.
        """
        from espalier import provenance_census
        from espalier.surface_impact import _provenance_applies

        for rel in sorted(provenance_census._ALLOWLISTED_FILES):
            assert not _provenance_applies(rel), (
                f"{rel} is whole-file allowlisted by the census but "
                "surface-impact still reports a provenance obligation"
            )

    def test_granular_allowlist_paths_are_still_scanned(self) -> None:
        """Discriminator: _ALLOWED_HITS must NOT suppress the whole file.

        ``_ALLOWED_HITS`` forgives specific tokens in a file that is still
        scanned. Skipping those paths wholesale would be strictly wider than
        the census and would hide a genuinely new tag.
        """
        from espalier import provenance_census
        from espalier.surface_impact import _provenance_applies

        paths = {rel for rel, _token in provenance_census._ALLOWED_HITS}
        scanned = {p for p in paths if _provenance_applies(p)}
        assert scanned, (
            "_ALLOWED_HITS paths were all suppressed -- the granular allowlist "
            "was applied as a whole-file skip, which is wider than the census"
        )

    def test_hook_entry(self) -> None:
        label, demands = classify_surface("tools/cc/hooks/foo.py")
        assert label == "hook entry"
        assert any("EXPECTED_HOOK_COUNT" in d for d in demands)
        assert any("vendor mirror" in d for d in demands)

    def test_hook_helper(self) -> None:
        label, demands = classify_surface("tools/cc/hooks/_foo.py")
        assert label == "hook helper"
        assert any("EXPECTED_HOOK_HELPER_COUNT" in d for d in demands)

    def test_dev_script(self) -> None:
        label, demands = classify_surface("scripts/foo.py")
        assert label == "dev script"
        assert any("EXPECTED_SCRIPT_NAMES" in d for d in demands)

    def test_engine_module(self) -> None:
        label, demands = classify_surface("espalier/foo.py")
        assert label == "engine module"
        assert any("provenance" in d for d in demands)

    def test_scanner_module_before_generic_engine(self) -> None:
        # espalier/scanners/ must match its own rule, not the generic engine one.
        assert classify_surface("espalier/scanners/foo.py")[0] == "scanner module"

    def test_vendored_mirror_before_generic_engine(self) -> None:
        assert classify_surface("espalier/_vendor/cc/foo.py")[0] == "vendored mirror"

    def test_selfcheck_mirror_is_not_the_vendor_cc_family(self) -> None:
        # espalier/_vendor/ hosts TWO mirror families with DIFFERENT sync scripts.
        # The generic `_vendor/` prefix used to swallow selfcheck_tests/ and hand
        # back sync_vendor_cc.py -- a wrong remedy, not a missing one: running it
        # cannot fix a selfcheck drift and exits 0 having changed nothing.
        label, demands = classify_surface(
            "espalier/_vendor/selfcheck_tests/test_fingerprint.py"
        )
        assert label == "selfcheck mirror"
        assert any("sync_selfcheck_tests.py" in d for d in demands)
        assert not any("sync_vendor_cc.py" in d for d in demands)

    def test_selfcheck_mirror_does_not_shadow_vendor_cc(self) -> None:
        # The negative half: adding the narrower rule must not steal the tools/cc
        # mirror's own paths.
        label, demands = classify_surface("espalier/_vendor/cc/hooks/_reinject.py")
        assert label == "vendored mirror"
        assert any("sync_vendor_cc.py" in d for d in demands)

    def test_doc_asset(self) -> None:
        label, demands = classify_surface("espalier/assets/docs/FOO.md")
        assert label == "portable-knowledge doc asset"
        assert any("_SEED_DOC_REL_PATHS" in d for d in demands)

    def test_task_packs_router_sot_names_its_sync(self) -> None:
        # The SoT side of a mirror row that classified as None, so an edit to it
        # surfaced no sync obligation at all.
        label, demands = classify_surface("task-packs/CLAUDE.md")
        assert label == "mirrored folder router"
        assert any("sync_asset_docs.py" in d for d in demands)

    def test_task_packs_asset_cites_its_real_parity_test(self) -> None:
        # It lives outside assets/docs/**, so the asset-docs rglob never reaches it
        # and it is pinned by its own explicitly-added guard -- in a DIFFERENT module
        # from the one the generic packaged-asset rule names.
        label, demands = classify_surface("espalier/assets/task-packs/CLAUDE.md")
        assert any("test_deploy_doc_parity.py" in d for d in demands)
        assert not any("test_package_resource_parity.py" in d for d in demands)

    def test_root_harness_guard_workflow_names_the_inverted_direction(self) -> None:
        # The one row whose SoT is the PACKAGED copy: the root file is generated.
        # It classified as None -- no obligation on the exact file whose hand-edit
        # is the failure this rule exists to catch.
        label, demands = classify_surface(".github/workflows/harness-guard.yml")
        assert label == "generated workflow mirror"
        assert any("espalier/assets/github/workflows/" in d for d in demands)
        assert any("test_package_resource_parity.py" in d for d in demands)

    def test_other_workflows_are_not_claimed_as_mirrors(self) -> None:
        # The negative half: only harness-guard.yml is generated. Every other
        # workflow in the same directory is edited in place.
        #
        # Compare the LABEL, not the whole return value. The first version of
        # this test compared the 2-tuple against a parenthesised bare string --
        # not a tuple, so the assertion held no matter what the function did and
        # the negative half had no coverage at all.
        result = classify_surface(".github/workflows/ci.yml")
        assert result is None or result[0] != "generated workflow mirror"

    def test_harness_guard_asset_is_labelled_the_source_not_a_copy(self) -> None:
        # The inverted row's SoT side. The generic packaged-asset rule says
        # "byte-mirror sync to its source SoT", which asserts this file is a copy
        # of something -- it is the something.
        label, demands = classify_surface(
            "espalier/assets/github/workflows/harness-guard.yml"
        )
        assert label == "workflow asset (source of truth)"
        assert any("INVERTED" in d for d in demands)
        assert any("sync_github_workflow_asset.py" in d for d in demands)

    def test_generated_workflow_names_its_sync_script(self) -> None:
        # Regression pin for a claim that shipped stale: this obligation read
        # "no sync script exists" in the same change that added the script.
        _, demands = classify_surface(".github/workflows/harness-guard.yml")
        joined = " ".join(demands)
        assert "sync_github_workflow_asset.py" in joined
        assert "no sync script exists" not in joined

    def test_shipped_doc(self) -> None:
        label, demands = classify_surface("docs/FOO.md")
        assert label == "shipped doc"
        assert any("broken-links" in d for d in demands)

    def test_bench_corpus(self) -> None:
        assert classify_surface("bench/corpus/BC-999.json")[0] == "bypass-class corpus"

    def test_bench_oracle_is_top_level_only(self) -> None:
        """A tracked top-level bench script names its README, row-table,
        release-surface and host-check obligations. Top level ONLY: the
        siblings under bench/ keep answering exactly as they did, driven
        rather than read (SHARP_EDGES: a prefix match that swallows a
        sibling names the wrong remedy)."""
        label, demands = classify_surface("bench/guard_row_probe.py")
        assert label == "bench oracle"
        joined = " ".join(demands)
        assert "bench/README.md" in joined and "layout tree" in joined
        assert "KNOWN_GAPS" in joined
        assert "TestNoMachineLocalPaths" in joined
        assert "host_check" in joined
        assert classify_surface("bench/run_benchmark.py")[0] == "bench oracle"
        assert classify_surface("bench/corpus/BC-999.json")[0] == "bypass-class corpus"
        assert classify_surface("bench/end_to_end/run.py") is None
        assert classify_surface("bench/README.md") is None
        assert classify_surface("bench/baselines/espalier/setup.sh") is None

    def test_standalone_tool(self) -> None:
        label, demands = classify_surface("tools/cc/foo.py")
        assert label == "standalone tool"
        assert any("zero espalier imports" in d for d in demands)

    def test_deployed_shim(self) -> None:
        # DEF-729: the .cmd statusline shim shares the vendor-mirror demand
        # with the .py tools and carries the two batch-only constraints.
        label, demands = classify_surface("tools/cc/statusline.cmd")
        assert label == "deployed shim"
        assert any("sync_vendor_cc.py" in d for d in demands)
        assert any("no label search" in d for d in demands)
        assert not any("zero espalier imports" in d for d in demands)

    def test_test_module(self) -> None:
        assert classify_surface("tests/test_foo.py")[0] == "test module"

    def test_unclassified_returns_none(self) -> None:
        assert classify_surface("brandnewdir/thing.py") is None


class TestBuildReport:
    def test_command_addition_emits_command_obligations(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, added=[".claude/commands/newcmd.md"])
        report = build_report(tmp_path, pack)
        assert "slash command" in {o.surface for o in report.obligations}
        assert report.has_public_changes()

    def test_brand_new_dir_flagged_unmatched_public(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, added=["brandnewdir/module.py"])
        report = build_report(tmp_path, pack)
        assert "brandnewdir/module.py" in report.unmatched_public
        assert report.has_public_changes()

    def test_added_symbol_not_treated_as_new_path(self, tmp_path: Path) -> None:
        # parse_pack reduces `path::symbol` to the bare symbol; a bare symbol is
        # an addition INSIDE an existing file, not a new shipped path, so it must
        # not surface as an obligation or an unmatched-public entry.
        pack = _write_pack(
            tmp_path, added=["espalier/managed_inventory.py::_SOME_CONST"]
        )
        report = build_report(tmp_path, pack)
        assert report.unmatched_public == []
        assert report.obligations == []

    def test_toplevel_shipped_files_are_not_silently_dropped(self, tmp_path: Path) -> None:
        """TP-274 4-A: a new top-level file whose suffix is not in the whitelist
        (``Makefile``, ``setup.cfg``, ``.flake8``) classifies PUBLIC but was
        silently dropped to added_symbols by ``_looks_like_path`` — no obligation,
        no unmatched-public warning. Each must now surface (as unmatched_public,
        since classify_surface has no specific rule for them). RED before (all three
        dropped → absent), GREEN after. ``.flake8`` is the leading-dot case the
        widened suffix list alone misses (its warning branch would also not fire)."""
        pack = _write_pack(tmp_path, added=["Makefile", "setup.cfg", ".flake8"])
        report = build_report(tmp_path, pack)
        for f in ("Makefile", "setup.cfg", ".flake8"):
            assert f in report.unmatched_public, f"{f} was silently dropped"
        assert report.has_public_changes()

    def test_ambiguous_added_entry_warns_not_drops(self, tmp_path: Path) -> None:
        """TP-274 4-A: a token that is neither a clean file path nor a bare Python
        identifier (e.g. a dashed name) must not vanish silently — build_report
        appends an ambiguity warning so the operator sees it."""
        pack = _write_pack(tmp_path, added=["not-a-real-symbol"])
        report = build_report(tmp_path, pack)
        assert any("not-a-real-symbol" in w for w in report.warnings), (
            f"ambiguous entry produced no warning: {report.warnings}"
        )


    def test_unknown_suffix_toplevel_file_warns_not_drops(self, tmp_path: Path) -> None:
        """TP-275 4-A: a top-level filey token whose suffix is NOT whitelisted yet
        reduces to a valid identifier (``go.mod`` -> ``go_mod``, ``configure.ac``)
        slipped past TP-274's ``not reduced.isidentifier()`` warn and vanished into
        added_symbols with no obligation and no warning. The widened ``looks_filey``
        discriminator now warns. A dotted UPPERCASE-tail SYMBOL (``Klass.DEFAULT``)
        must NOT warn — it is a real added symbol, not a file."""
        pack = _write_pack(tmp_path, added=["go.mod", "configure.ac", "Klass.DEFAULT"])
        report = build_report(tmp_path, pack)
        for f in ("go.mod", "configure.ac"):
            assert any(f in w for w in report.warnings), (
                f"{f} produced no ambiguity warning: {report.warnings}"
            )
        assert not any("Klass.DEFAULT" in w for w in report.warnings), (
            f"Klass.DEFAULT (uppercase-tail symbol) should not warn: {report.warnings}"
        )


class TestParserNotesReachTheSurfaceReport:
    """A bare-path ``### Added-paths`` bullet read ``[ok] No shipped-surface
    additions`` here while scope-check printed the ``!`` line for it (the
    failure-mode review of the §C7 lane drove both side by side): the
    parser's own account of what it dropped now reaches this report."""

    def test_a_bare_path_addition_is_a_parser_note_not_an_ok(self, tmp_path: Path) -> None:
        from espalier.surface_impact import render_report
        pack = tmp_path / "TP-998-bare.md"
        pack.write_text(
            "# TP-998 — fixture\n\n## Affected symbols\n\n### Added-paths\n"
            "- espalier/newthing.py -- a new shipped module, typed bare\n",
            encoding="utf-8",
        )
        report = build_report(tmp_path, pack)
        assert any("declares no backticked token" in n for n in report.parser_notes), (
            report.parser_notes
        )
        rendered = render_report(report, pack.name)
        assert "[ok] No shipped-surface additions" not in rendered, rendered
        assert "parser note" in rendered and "espalier/newthing.py" in rendered, rendered

    def test_a_clean_pack_still_reads_ok(self, tmp_path: Path) -> None:
        from espalier.surface_impact import render_report
        pack = _write_pack(tmp_path)
        report = build_report(tmp_path, pack)
        assert report.parser_notes == []
        assert "[ok] No shipped-surface additions" in render_report(report, pack.name)


class TestProvenanceObligationStandsDownWithItsVerb:
    """DEF-410i, code half: do not print an obligation the reader cannot discharge.

    `espalier provenance` stands down off the self-host tree (`cli.cmd_provenance`,
    exit 0, census never runs). The obligation map is not advisory reading --
    `.claude/commands/implement-pack.md` step 0-D instructs "Use the 0-D
    surface-impact obligation map as the checklist", so an adopter works the
    list, runs the verb, gets exit 0, and ticks off a check that never ran.

    The three carriers below are the ones REACHABLE on an adopter tree: `init`
    deploys `tools/cc/` (hooks + helpers) and `docs/`. The two sibling demands
    inside `classify_surface` fire only on `espalier/` and `espalier/scanners/`
    paths, which do not exist there -- they are covered by the keying guard
    rather than by a behavioural arm, because no adopter can reach them.
    """

    #: Adopter-reachable paths that carry the provenance demand on self-host.
    CARRIERS = (
        "tools/cc/hooks/newhook.py",   # hook entry -> _hook_demands
        "tools/cc/newtool.py",         # standalone tool
        "docs/NEWDOC.md",              # shipped doc
    )

    #: `build_report` has TWO obligation producers. The path loop is one; a
    #: `cmd_*` symbol reaching `_cli_verb_obligation` is the other, and it
    #: appends straight to the list. A population of paths alone left the
    #: second producer unexercised -- measured: adding the provenance demand
    #: to the CLI-verb list kept this whole class green.
    CLI_SYMBOL = "cli.py::cmd_frobnicate"

    @staticmethod
    def _provenance_demands(report) -> set[str]:
        """Triggers whose obligation still names the stand-down verb."""
        return {
            o.trigger
            for o in report.obligations
            for d in o.demands
            if "espalier provenance" in d
        }

    def test_an_adopter_tree_is_not_handed_an_undischargeable_obligation(
        self, tmp_path: Path
    ) -> None:
        """RED before the fix: all three carriers listed it.

        `tmp_path` is an adopter tree BY CONSTRUCTION -- `is_self_host_repo`
        needs five signals including a content hash on write_guard.py, which no
        fixture reproduces. That is why this arm needs no monkeypatch and its
        sibling below needs one.
        """
        pack = _write_pack(
            tmp_path, added=list(self.CARRIERS), changed=[self.CLI_SYMBOL]
        )
        report = build_report(tmp_path, pack)
        stranded = self._provenance_demands(report)
        assert not stranded, (
            f"surface-impact told an adopter to run `espalier provenance` for "
            f"{sorted(stranded)}. That verb stands down off the Espalier-Harness "
            "source tree and exits 0 without scanning, so the obligation cannot "
            "be discharged -- and step 0-D tells them to work this map as a "
            "checklist."
        )

    def test_the_self_host_tree_still_carries_it_for_every_carrier(
        self, tmp_path: Path, as_self_host_tree
    ) -> None:
        """Anti-vacuity floor, and it is an EQUALITY not a floor-count.

        A count ("at least one carrier still lists it") stays green if the
        filter widens from one demand to every demand on two of three surfaces.
        Asserting the exact trigger SET is what joins the population to the
        thing being filtered -- a population floor cannot see a keying defect.
        """
        pack = _write_pack(
            tmp_path, added=list(self.CARRIERS), changed=[self.CLI_SYMBOL]
        )
        report = build_report(tmp_path, pack)
        assert self._provenance_demands(report) == set(self.CARRIERS), (
            "the provenance obligation is no longer raised for every carrier ON "
            "THE SELF-HOST TREE -- the filter is over-reaching, or a carrier "
            "stopped classifying. Either way surface-impact has gone quiet where "
            "it is the actual gate."
        )

    def test_the_adopters_map_differs_from_self_host_by_exactly_this_demand(
        self, tmp_path: Path, request: pytest.FixtureRequest
    ) -> None:
        """The filter must remove ONE demand, not hollow out the report.

        THIS ARM WAS A FLOOR AND THE FLOOR COULD NOT SEE THE DEFECT. It used to
        assert `obligation.demands` -- non-emptiness -- with a docstring arguing
        that an over-broad filter "satisfies 'no provenance demand' exactly as
        well as the correct fix does". It did, and the floor stayed green:
        driven, `[d for d in demands if "espalier " not in d]` passed the whole
        class while silently stripping `integrity manifest refresh (espalier
        integrity refresh)` -- a REAL obligation on an adopter tree -- from
        every hook-entry map. A population count cannot see a keying defect;
        only the set difference joins the two sides.

        So: build the SAME pack twice, once per tree identity, and assert the
        adopter map is the self-host map minus exactly `_PROVENANCE_DEMAND`.
        """
        from espalier.surface_impact import _PROVENANCE_DEMAND

        pack = _write_pack(
            tmp_path, added=list(self.CARRIERS), changed=[self.CLI_SYMBOL]
        )
        adopter = {
            o.trigger: list(o.demands)
            for o in build_report(tmp_path, pack).obligations
        }
        # Same inputs, self-host identity. Applied here rather than via the
        # fixture so both halves are built inside ONE test -- a two-test split
        # could not assert the difference at all.
        request.getfixturevalue("as_self_host_tree")
        self_host = {
            o.trigger: list(o.demands)
            for o in build_report(tmp_path, pack).obligations
        }

        assert set(adopter) == set(self_host), (
            "the obligation ROWS differ between the two trees; only the demands "
            f"inside them should.\n  adopter-only: {sorted(set(adopter) - set(self_host))}"
            f"\n  self-host-only: {sorted(set(self_host) - set(adopter))}"
        )
        assert self_host, "self-host produced no obligations -- population is empty"
        for trigger, sh_demands in self_host.items():
            expected = [d for d in sh_demands if d != _PROVENANCE_DEMAND]
            assert adopter[trigger] == expected, (
                f"{trigger}: the adopter's demand list is not the self-host list "
                f"minus the provenance demand -- the filter is dropping (or "
                f"keeping) something else.\n  expected: {expected}\n  got:      "
                f"{adopter[trigger]}"
            )

    #: One probe per rule branch that carried the demand as its own literal
    #: before the fix. `espalier/` and `espalier/scanners/` are unreachable on
    #: an adopter tree, so the behavioural arms above cannot cover them -- this
    #: is where they are covered.
    DEMAND_PROBES = (
        "tools/cc/hooks/h.py",
        "tools/cc/t.py",
        "docs/D.md",
        "espalier/m.py",
        "espalier/scanners/s.py",
        "bench/b.py",
    )

    def test_every_rule_spells_the_demand_identically(self) -> None:
        """The filter compares by EQUALITY, so a near-miss spelling escapes it.

        Behavioural, not source-level, because the escape that matters is not
        only a reworded literal: driven, `_PROVENANCE_DEMAND + " -- run it
        before staging"` left the whole class green while shipping an
        unfilterable demand. A concatenation is invisible to any scan for
        string constants -- both halves are innocent on their own -- and only
        the rendered demand shows it.
        """
        from espalier.surface_impact import _PROVENANCE_DEMAND

        elicited = 0
        for probe in self.DEMAND_PROBES:
            matched = classify_surface(probe)
            assert matched is not None, (
                f"probe {probe!r} no longer classifies -- the rule it covers "
                "moved or was renamed, so this arm silently stopped testing it"
            )
            _label, demands = matched
            near_misses = [d for d in demands if "espalier provenance" in d]
            assert all(d == _PROVENANCE_DEMAND for d in near_misses), (
                f"{probe} emits a provenance demand that is not byte-identical "
                f"to `_PROVENANCE_DEMAND`: {near_misses}. The adopter filter "
                "keys on equality, so this variant reaches them unfiltered. "
                "Reference the constant without decorating it."
            )
            elicited += len(near_misses)

        assert elicited == len(self.DEMAND_PROBES), (
            f"only {elicited} of {len(self.DEMAND_PROBES)} probes produced the "
            "provenance demand. Either a rule stopped carrying it (drop the "
            "probe) or this arm has gone partly vacuous -- it cannot police a "
            "spelling it never elicits."
        )

    #: The functions that BUILD demand lists. Scanning the whole module was
    #: wrong twice over: it reddened on a one-line docstring mentioning the
    #: verb, and then on `_stand_down_note`'s own prose. Both are correct text
    #: whose remedy ("reference the constant") is impossible to follow, and an
    #: unfollowable red gets widened until the guard goes blind. The question
    #: is not "does any string name the verb" but "is there a second spelling
    #: of the DEMAND" -- so scan only where demands are made.
    DEMAND_PRODUCERS = ("classify_surface", "_hook_demands", "_cli_verb_obligation")

    def test_the_demand_table_still_lives_in_this_module(self) -> None:
        """Companion to the arm above, covering what behaviour cannot see.

        If a rule table moves to a new module, the probes keep passing while
        `_applicable_demands` and its constant stay behind. So pin the
        producers in this module: every demand literal naming the verb must BE
        the constant.
        """
        import ast

        from espalier.surface_impact import _PROVENANCE_DEMAND

        source = (
            Path(__file__).resolve().parents[1] / "espalier" / "surface_impact.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)

        producers = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in self.DEMAND_PRODUCERS
        }
        missing = set(self.DEMAND_PRODUCERS) - set(producers)
        assert not missing, (
            f"demand-producing function(s) {sorted(missing)} are gone from "
            "espalier/surface_impact.py. If they were renamed or moved, this "
            "arm is scanning nothing -- re-point DEMAND_PRODUCERS."
        )

        literals: set[str] = set()
        refs = 0
        for func in producers.values():
            body = func.body[1:] if ast.get_docstring(func) else func.body
            for stmt in body:
                for node in ast.walk(stmt):
                    if (
                        isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and "espalier provenance" in node.value
                    ):
                        literals.add(node.value)
                    elif isinstance(node, ast.Name) and node.id == "_PROVENANCE_DEMAND":
                        refs += 1

        assert not literals, (
            "a demand-producing function spells the provenance demand out as a "
            f"literal instead of referencing the constant: {sorted(literals)}. "
            "The adopter filter keys on `_PROVENANCE_DEMAND` by equality, so a "
            "second spelling reaches adopters unfiltered -- which is exactly "
            "how this defect shipped: five sites, five copies."
        )
        assert refs >= len(self.DEMAND_PROBES), (
            f"only {refs} reference(s) to `_PROVENANCE_DEMAND` remain in "
            f"{sorted(producers)}, against {len(self.DEMAND_PROBES)} rules known "
            "to carry it. Either the demand tables moved to another module -- "
            "leaving the constant and its filter behind, unreferenced -- or a "
            "rule dropped the demand without dropping its probe above."
        )
        assert _PROVENANCE_DEMAND, "the constant is empty; the filter matches nothing"

    def test_the_report_says_when_it_withheld_something(self, tmp_path: Path) -> None:
        """A shorter list must never be mistakable for a shorter obligation.

        Two measured triggers: `--repo` defaults to `"."` and is not walked up
        to the repo root, so running this verb from a subdirectory of the
        harness itself produced a full report with every provenance row missing
        and nothing saying why; and `is_self_host_repo` pins a content hash
        over editable prose, so a reflow flips this tree to "adopter" and
        quietly shortens the checklist where the census is the actual gate.
        """
        from espalier.surface_impact import render_report

        pack = _write_pack(tmp_path, added=list(self.CARRIERS))
        report = build_report(tmp_path, pack)
        assert report.off_self_host is True
        body = render_report(report, "pack.md")
        assert "apply only to the Espalier-Harness source tree" in body, (
            "the report withheld obligations and did not say so. A silent "
            f"stand-down is indistinguishable from a clean short report.\n{body}"
        )

    def test_the_self_host_report_carries_no_such_note(
        self, tmp_path: Path, as_self_host_tree
    ) -> None:
        """Anti-vacuity for the note: it must not print unconditionally."""
        from espalier.surface_impact import render_report

        pack = _write_pack(tmp_path, added=list(self.CARRIERS))
        report = build_report(tmp_path, pack)
        assert report.off_self_host is False
        assert "apply only to the Espalier-Harness source tree" not in render_report(
            report, "pack.md"
        ), "the stand-down note printed on the self-host tree, where nothing stood down"


class TestCliVerbDetection:
    def test_cmd_symbol_emits_cheat_sheet_obligation(self, tmp_path: Path) -> None:
        pack = _write_pack(
            tmp_path, changed=["espalier/cli.py::cmd_newverb", "build_parser"]
        )
        report = build_report(tmp_path, pack)
        cli = [o for o in report.obligations if o.surface.startswith("CLI subcommand")]
        assert len(cli) == 1
        assert "cmd_newverb" in cli[0].trigger
        assert any("CHEAT-SHEET" in d for d in cli[0].demands)

    def test_no_cli_obligation_without_cmd_symbol(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, added=["docs/FOO.md"])
        report = build_report(tmp_path, pack)
        assert not any(
            o.surface.startswith("CLI subcommand") for o in report.obligations
        )


class TestSurfaceImpactRetroCatch:
    """Regression pin (crit #3): a pack that ADDS a dev script + a
    portable-knowledge doc asset (TP-271a's shape) must surface the
    script-count and asset-byte-mirror obligations it tripped only in the full
    suite. Synthetic fixture — the real ``task-packs/Done/TP-271a-*.md`` is
    gitignored, so this committed pin reproduces the shape rather than reading
    the file (which the manual execution-time run used)."""

    def test_seed_doc_pack_surfaces_the_tripped_obligations(
        self, tmp_path: Path
    ) -> None:
        pack = _write_pack(
            tmp_path,
            added=[
                "scripts/sync_asset_docs.py",
                "espalier/assets/docs/FAILURE_MODES.md",
            ],
        )
        report = build_report(tmp_path, pack)
        obs = {o.surface: o for o in report.obligations}

        assert "dev script" in obs
        assert any("EXPECTED_SCRIPT_COUNT" in d for d in obs["dev script"].demands)

        assert "portable-knowledge doc asset" in obs
        doc_demands = " ".join(obs["portable-knowledge doc asset"].demands)
        assert "byte-parity" in doc_demands
        assert "_SEED_DOC_REL_PATHS" in doc_demands
        assert "_DOCS_ASSET_TAILS" in doc_demands


class TestExitCodes:
    def _run(self, pack_path: Path, accept: str | None = None) -> int:
        args = argparse.Namespace(
            repo=".", pack_path=str(pack_path), accept_surface_gap=accept
        )
        return cmd_surface_impact(args)

    def test_public_addition_exits_2(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, added=[".claude/commands/foo.md"])
        assert self._run(pack) == 2

    def test_accept_surface_gap_exits_0(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, added=[".claude/commands/foo.md"])
        assert self._run(pack, accept="reviewed, tests-only") == 0

    def test_no_declared_addition_exits_0(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, added=[])
        assert self._run(pack) == 0

    def test_missing_pack_exits_1(self, tmp_path: Path) -> None:
        assert self._run(tmp_path / "nope.md") == 1

    def test_directory_pack_path_exits_1(self, tmp_path: Path) -> None:
        assert self._run(tmp_path) == 1


class TestCitedScriptFlagsExist:
    """TP-274 8-B: every ``scripts/<name>.py --<flag>`` that surface_impact.py
    emits as operator guidance must be a REAL flag the script accepts — else the
    cited 'verify' command silently does something else (the phantom-flag class,
    the very defect 8-A closed). Parse the citations, confirm each flag is in the
    script's --help. RED if a cited flag is unimplemented (the pre-8-A state)."""

    def test_surface_impact_cited_script_flags_are_real(self) -> None:
        import contextlib
        import importlib.util
        import io
        import re
        import sys

        repo_root = Path(__file__).resolve().parent.parent
        src = (repo_root / "espalier" / "surface_impact.py").read_text(encoding="utf-8")
        cites = sorted(set(re.findall(
            r"scripts/([A-Za-z0-9_]+\.py)\s+(--[a-z][a-z0-9-]*)", src
        )))
        assert cites, (
            "no `scripts/*.py --flag` citations found in surface_impact.py — the "
            "regex is vacuous or the citations were removed (this contract would "
            "then pass without checking anything)"
        )
        for script_name, flag in cites:
            spec = importlib.util.spec_from_file_location(
                f"_pf_{script_name}", repo_root / "scripts" / script_name
            )
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            buf = io.StringIO()
            code: object = None
            try:
                with contextlib.redirect_stdout(buf):
                    mod.main(["--help"])
            except SystemExit as exc:
                code = exc.code
            except TypeError as exc:
                raise AssertionError(
                    f"scripts/{script_name}.main() does not accept argv — cannot "
                    f"honor the cited `{flag}` (phantom flag): {exc}"
                ) from exc
            help_text = buf.getvalue()
            assert code == 0, f"scripts/{script_name} --help exited {code}"
            assert flag in help_text, (
                f"surface_impact.py cites `scripts/{script_name} {flag}` but the "
                f"script's --help does not list {flag} — phantom flag (the cited "
                f"command silently does something else)"
            )


class TestRemovedPathsDeclareObligations:
    """DEF-410j. The pre-flight reported obligations only for the paths a pack
    ADDS or CHANGES, so a path the pack DELETES declared none even when every
    count pin, table row, regenerated index, mirror and manifest entry that
    enrolled it still tracks it -- the same sites, in reverse. The manifest
    parser already routed ``### Removed-paths`` / ``### Deleted-paths``; the
    report ignored them. Now a removed path runs through the SAME surface
    classifier (one table, never a reverse-worded copy) and is reported as a
    removal with the same demands and one leading line saying what reverse
    means; a renamed path is the removal of its old name with a hint to
    declare the new one under Added-paths (the parser keeps a bullet's first
    token only); no content scan runs on a removal; the verb exits 2 on a
    public removal as on a public addition.
    """

    def test_a_removed_command_carries_the_command_obligations_in_reverse(
        self, tmp_path: Path,
    ) -> None:
        pack = _write_pack(tmp_path, removed=[".claude/commands/oldcmd.md"])
        report = build_report(tmp_path, pack)
        removals = [o for o in report.obligations if o.direction == "removed"]
        assert [o.surface for o in removals] == ["slash command"]
        assert removals[0].trigger == ".claude/commands/oldcmd.md"
        assert removals[0].classification == "public"
        import espalier.surface_impact as si
        _, added_demands = classify_surface(".claude/commands/oldcmd.md")
        # The same SoT sites, in reverse -- minus the demands that police the
        # departing file's own content, which have no reverse.
        expected = [d for d in added_demands if d not in si._content_only_demands()]
        assert removals[0].demands == expected
        assert len(expected) < len(added_demands), "the content-only filter must bite here"
        assert report.public_removals() == [".claude/commands/oldcmd.md"]
        assert report.public_additions() == []
        assert report.has_public_changes()

    def test_an_unmatched_public_removal_surfaces(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, removed=["brandnewdir/module.py"])
        report = build_report(tmp_path, pack)
        assert report.unmatched_public_removed == ["brandnewdir/module.py"]
        assert report.unmatched_public == []
        assert report.has_public_changes()

    def test_a_removed_path_symbol_is_a_symbol_not_a_path(self, tmp_path: Path) -> None:
        """Paired with a positive control in the same pack, so the negative is
        attributable to the symbol reading and not to the loop being absent."""
        pack = _write_pack(
            tmp_path,
            removed=["espalier/managed_inventory.py::_SOME_CONST", ".claude/commands/oldcmd.md"],
        )
        report = build_report(tmp_path, pack)
        assert [o.trigger for o in report.obligations] == [".claude/commands/oldcmd.md"]
        assert report.unmatched_public_removed == []
        assert report.warnings == []

    def test_the_deleted_spelling_routes_too(self, tmp_path: Path) -> None:
        body = (
            "# TP-999 — fixture\n\n## Affected symbols\n\n"
            "### Deleted-paths\n- `.claude/commands/oldcmd.md`\n"
        )
        p = tmp_path / "TP-999-fixture.md"
        p.write_text(body, encoding="utf-8")
        report = build_report(tmp_path, p)
        assert [o.direction for o in report.obligations] == ["removed"]

    def test_a_renamed_path_is_the_removal_of_its_old_name_with_a_hint(
        self, tmp_path: Path,
    ) -> None:
        from espalier.surface_impact import render_report
        pack = _write_pack(tmp_path, renamed=[".claude/commands/oldcmd.md"])
        report = build_report(tmp_path, pack)
        renamed = [o for o in report.obligations if o.direction == "renamed"]
        assert [o.trigger for o in renamed] == [".claude/commands/oldcmd.md"]
        assert report.public_removals() == [".claude/commands/oldcmd.md"]
        text = render_report(report, "x.md")
        assert "Added-paths" in text and "rename" in text.lower()

    def test_a_renamed_bare_symbol_is_not_a_path(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, renamed=["espalier/cli.py::old_name"])
        report = build_report(tmp_path, pack)
        assert report.obligations == []

    def test_no_content_scan_on_a_removal(self, tmp_path: Path, monkeypatch) -> None:
        """An addition's declared path is content-scanned when it exists on
        disk; a removal's is not -- the file is leaving. Recorded through the
        scan hook itself, since on an adopter-shaped tmp tree the scan stands
        down and would leave nothing else to observe."""
        import espalier.surface_impact as si
        scanned: list[str] = []
        monkeypatch.setattr(si, "_scan_existing", lambda root, rel, report: scanned.append(rel))
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        (tmp_path / ".claude" / "commands" / "oldcmd.md").write_text("old\n", encoding="utf-8")
        (tmp_path / ".claude" / "commands" / "newcmd.md").write_text("new\n", encoding="utf-8")
        pack = _write_pack(
            tmp_path,
            added=[".claude/commands/newcmd.md"],
            removed=[".claude/commands/oldcmd.md"],
        )
        build_report(tmp_path, pack)
        assert scanned == [".claude/commands/newcmd.md"]

    def test_render_marks_removals_and_says_what_reverse_means(self, tmp_path: Path) -> None:
        from espalier.surface_impact import render_report
        pack = _write_pack(
            tmp_path,
            added=[".claude/commands/newcmd.md"],
            removed=[".claude/commands/oldcmd.md"],
        )
        text = render_report(build_report(tmp_path, pack), "x.md")
        assert "1 surface addition" in text and "1 surface removal" in text
        assert "oldcmd.md" in text and "newcmd.md" in text
        assert "removal" in text
        assert "decrement" in text and "prune" in text

    def test_cli_exits_two_on_a_public_removal_and_zero_when_acknowledged(
        self, tmp_path: Path, capsys,
    ) -> None:
        pack = _write_pack(tmp_path, removed=[".claude/commands/oldcmd.md"])
        args = argparse.Namespace(
            pack_path=str(pack), repo=str(tmp_path), accept_surface_gap=None,
        )
        assert cmd_surface_impact(args) == 2
        out = capsys.readouterr().out
        assert "removal" in out
        args.accept_surface_gap = "known and bundled"
        assert cmd_surface_impact(args) == 0

    # -- review batch (2026-09-11): the holes both reviewers drove --------------

    def test_the_live_spaced_symbol_rename_is_not_a_file_removal(self, tmp_path: Path) -> None:
        """Verbatim from a real pack. The parser kept the path (a spaced `::`
        was not joined) and 0-D reported the removal of espalier/cli.py."""
        body = (
            "# TP-999 — fixture\n\n## Affected symbols\n\n### Renamed\n"
            "- `espalier/cli.py` :: local `_tp88_deploys` → `deployed_seed_docs` "
            "(4-A; pack-id identifier, two sites L2156/L2190)\n"
        )
        p = tmp_path / "TP-999-fixture.md"
        p.write_text(body, encoding="utf-8")
        report = build_report(tmp_path, p)
        assert report.obligations == []
        assert report.unmatched_public_removed == []
        assert not report.has_public_changes()

    def test_the_live_none_bullet_is_not_a_file_removal(self, tmp_path: Path) -> None:
        """Verbatim from a real pack: `(none — `path` ...)` declares nothing;
        twelve packs spell it that way."""
        body = (
            "# TP-999 — fixture\n\n## Affected symbols\n\n### Renamed\n"
            "- *(none — `docs/TASK_RECIPES.md`'s heading rename is doc text, not a\n"
            "  production symbol.)*\n"
        )
        p = tmp_path / "TP-999-fixture.md"
        p.write_text(body, encoding="utf-8")
        report = build_report(tmp_path, p)
        assert report.obligations == []
        assert not report.has_public_changes()

    def test_a_removal_of_a_local_only_path_stays_quiet(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, removed=["reports/old.md"])
        report = build_report(tmp_path, pack)
        assert report.obligations == []
        assert report.unmatched_public_removed == []
        assert not report.has_public_changes()

    def test_a_removed_cli_verb_carries_the_cheat_sheet_obligation(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, removed=["espalier/cli.py::cmd_gone"])
        report = build_report(tmp_path, pack)
        verbs = [o for o in report.obligations if o.surface.startswith("CLI subcommand")]
        assert [o.direction for o in verbs] == ["removed"]
        assert verbs[0].trigger == "cmd_gone"
        assert any("CHEAT-SHEET" in d for d in verbs[0].demands)

    def test_an_ambiguous_removed_token_warns_naming_the_heading(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, removed=["go.mod"], renamed=["configure.ac"])
        report = build_report(tmp_path, pack)
        assert any("go.mod" in w and "Removed-paths" in w for w in report.warnings), report.warnings
        assert any("configure.ac" in w and "Renamed" in w for w in report.warnings), report.warnings

    def test_content_only_demands_are_dropped_from_a_removal(self, tmp_path: Path) -> None:
        """A departing file cannot carry a vocabulary leak; its count pin and
        mirror still move. Driven on a demand `_applicable_demands` leaves
        alone on an adopter-shaped tree, so the drop is attributable."""
        import espalier.surface_impact as si
        pack = _write_pack(
            tmp_path,
            added=[".claude/commands/newcmd.md"],
            removed=[".claude/commands/oldcmd.md"],
        )
        report = build_report(tmp_path, pack)
        (added,) = [o for o in report.obligations if o.direction == "added"]
        (removed,) = [o for o in report.obligations if o.direction == "removed"]
        assert si._ASSET_HYGIENE in added.demands
        assert si._ASSET_HYGIENE not in removed.demands
        assert any("EXPECTED_COMMAND_COUNT" in d for d in removed.demands)
        assert any("mirror" in d.lower() for d in removed.demands)

    def test_the_asset_doc_removal_names_the_hand_delete(self, tmp_path: Path) -> None:
        from espalier.surface_impact import render_report
        text = render_report(
            build_report(tmp_path, _write_pack(tmp_path, removed=["docs/OLD.md"])), "x.md",
        )
        assert "never prunes" in text and "sync_asset_docs.py" in text
        text2 = render_report(
            build_report(
                tmp_path,
                _write_pack(tmp_path, removed=[".claude/commands/oldcmd.md"], pack_id="TP-998"),
            ),
            "y.md",
        )
        assert "prunes its copies" in text2 and "never prunes" not in text2

    def test_a_directory_shaped_removal_says_to_declare_the_files(self, tmp_path: Path) -> None:
        from espalier.surface_impact import render_report
        pack = _write_pack(tmp_path, removed=[".claude/skills/oldskill/"])
        report = build_report(tmp_path, pack)
        assert report.unmatched_public_removed == [".claude/skills/oldskill/"]
        assert "declare the concrete file" in render_report(report, "x.md")

    def test_the_render_row_marker_and_inbound_clause_are_literal(self, tmp_path: Path) -> None:
        from espalier.surface_impact import render_report
        pack = _write_pack(
            tmp_path, removed=[".claude/commands/oldcmd.md"], renamed=["docs/old.md"],
        )
        text = render_report(build_report(tmp_path, pack), "x.md")
        assert "* slash command (removed): .claude/commands/oldcmd.md [public]" in text
        assert "* shipped doc (renamed): docs/old.md [public]" in text
        assert "INBOUND" in text
