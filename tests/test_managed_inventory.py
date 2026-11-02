"""TP-04 — managed inventory SoT shape tests.

Pins the contract that ``espalier.managed_inventory`` exposes the seven
classified APIs init/cleanup/doctor/PACK_MANIFEST consume. Verifies the
classifications stay disjoint where the contract requires it (public
files vs runtime files vs local-only files).
"""
from __future__ import annotations

from pathlib import Path

from espalier.managed_inventory import (
    get_generated_docs,
    get_hook_entry_files,
    get_hook_helper_files,
    get_local_only_files,
    get_local_runtime_files,
    get_managed_public_files,
    get_managed_public_prefixes,
    get_seed_docs,
    seed_needs_adapt_header,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Marker assignment lives in tests/conftest.py::_MARKER_RULES.


# ---------------------------------------------------------------------------
# Static accessors — expected counts and shapes
# ---------------------------------------------------------------------------


class TestStaticInventory:
    def test_hook_entry_count(self):
        # TP-40: 9 -> 10 with subagent_stop.py. TP-163: 10 -> 12 with
        # subagent_start.py + context_reinject_failure.py.
        entries = get_hook_entry_files()
        assert len(entries) == 12, (
            f"expected 12 hook entry scripts, got {len(entries)}: {entries}"
        )
        for path in entries:
            assert path.startswith("tools/cc/hooks/")
            assert path.endswith(".py")
            # Entry scripts don't start with underscore
            assert not Path(path).name.startswith("_")

    def test_hook_helper_count(self):
        helpers = get_hook_helper_files()
        assert len(helpers) == 15, (
            f"expected 15 hook helper modules (TP-79 added _bash_patterns.py + "
            f"_protected_zones.py to factor write_guard's dangerous-bash + "
            f"zone-classification primitives out of the 873-LOC dispatcher; "
            f"TP-112 added _denial_reasons.py as the SoT for deny()/block() "
            f"reason strings across 4 hook scripts; TP-159 added _speedbump.py "
            f"as the before-effect speed-bump mechanism; TP-164 added "
            f"_reinject.py as the recall-engine reinjection registry; TP-167 "
            f"added _recall.py as the pull-recall engine served by /recall; "
            f"TP-204e added _born_weak.py as the born-weak co-occurrence "
            f"observer extracted from post_write_check; TP-332 added "
            f"_explain_path.py as the /status --explain path-enforcement resolver; "
            f"TP-476 A-1 added _zone_watch.py, the zone after-check; DEF-3008 "
            f"added _start_refusal.py, the start refusal every deny hook "
            f"imports first), got "
            f"{len(helpers)}: {helpers}"
        )
        for path in helpers:
            assert path.startswith("tools/cc/hooks/_")
            assert path.endswith(".py")

    def test_hook_entries_and_helpers_disjoint(self):
        entries = set(get_hook_entry_files())
        helpers = set(get_hook_helper_files())
        assert entries.isdisjoint(helpers)

    def test_generated_docs_are_three_cc_files(self):
        docs = get_generated_docs()
        assert set(docs) == {
            "cc/LIVE_SURFACE.md",
            "cc/COMMANDS.md",
            "cc/PACK_MANIFEST.txt",
        }

    def test_managed_public_prefixes_cover_deploy_roots(self):
        prefixes = get_managed_public_prefixes()
        assert ".claude/agents/" in prefixes
        assert ".claude/commands/" in prefixes
        assert ".claude/skills/" in prefixes
        assert "cc/" in prefixes
        assert "tools/cc/" in prefixes

    def test_local_only_files_match_surface_contract(self):
        from espalier import surface_contract
        assert get_local_only_files() == surface_contract.get_local_only_paths()


# ---------------------------------------------------------------------------
# Repo-relative inventory — runs against the live self-host repo
# ---------------------------------------------------------------------------


class TestSelfHostInventory:
    def test_managed_public_files_includes_canonical_surface(self):
        files = set(get_managed_public_files(REPO_ROOT))
        # TP-31: agents/commands/skills no longer in managed inventory.
        # All hook entries + helpers
        for hook in get_hook_entry_files() + get_hook_helper_files():
            assert hook in files, f"hook {hook} missing from managed public files"
        # Generated docs
        for doc in get_generated_docs():
            assert doc in files

    def test_managed_public_files_excludes_runtime(self):
        files = set(get_managed_public_files(REPO_ROOT))
        # Runtime artifacts must NOT appear in the public managed list
        # because they're per-install / locally generated.
        for runtime in (
            ".claude/settings.json",
            ".espalier/integrity.json",
            "reports/harness_config.json",
            "reports/repo_fingerprint.json",
        ):
            assert runtime not in files, (
                f"runtime artifact {runtime} leaked into public inventory"
            )

    def test_managed_public_files_excludes_local_only(self):
        files = set(get_managed_public_files(REPO_ROOT))
        for local in get_local_only_files():
            assert local not in files, (
                f"local-only path {local} leaked into public inventory"
            )

    def test_runtime_classification_is_disjoint(self):
        # A file is runtime XOR local-only XOR public — never two at once.
        public = set(get_managed_public_files(REPO_ROOT))
        runtime = set(get_local_runtime_files(REPO_ROOT))
        local_only = set(get_local_only_files())
        assert public.isdisjoint(runtime), (
            f"public+runtime overlap: {public & runtime}"
        )
        assert public.isdisjoint(local_only), (
            f"public+local-only overlap: {public & local_only}"
        )

    def test_managed_public_files_deterministic(self):
        a = get_managed_public_files(REPO_ROOT)
        b = get_managed_public_files(REPO_ROOT)
        assert a == b
        # Sorted invariant
        assert a == sorted(a)


# ---------------------------------------------------------------------------
# Plan-based inventory (user repo path)
# ---------------------------------------------------------------------------


class TestPlanBasedInventory:
    def test_works_against_minimal_plan(self, tmp_path):
        # Synthesize a tiny user-repo with a saved plan whose agents list
        # includes a BOGUS agent that is not part of the packaged harness
        # surface. TP-31: the managed inventory is sourced from the package
        # SoT, not from the plan — plan-declared agents must NOT leak in.
        (tmp_path / "reports").mkdir()
        plan = {
            "repo_name": "demo",
            "agents": [{"name": "bogus-not-a-real-agent"}, {"name": "code-reviewer"}],
            "stable_actions": {},
            "generated_docs": [],
            "hooks": [],
            "config": {},
        }
        (tmp_path / "reports" / "harness_config.json").write_text(
            __import__("json").dumps(plan), encoding="utf-8",
        )
        files = get_managed_public_files(tmp_path, plan)

        # The plan-declared bogus agent must be absent — the inventory is not
        # plan-derived. A TP-31 regression (agents sourced from the plan) would
        # leak `.claude/agents/bogus-not-a-real-agent.md` and go RED here.
        assert not any("bogus-not-a-real-agent" in f for f in files)
        # The inventory is INVARIANT to the plan's agents list: an identical
        # call with no agents returns the same managed set.
        plan_no_agents = {**plan, "agents": []}
        assert get_managed_public_files(tmp_path, plan_no_agents) == files
        # Positive check: packaged harness agents/hooks are present regardless.
        assert ".claude/agents/code-reviewer.md" in files
        assert any(f.startswith("tools/cc/hooks/") for f in files)


class TestLocalRuntimeInventoryIsPinnedExactly:
    """The five per-install artifacts, pinned as a literal.

    Added because they were NOT pinned, and a generated doc now reads them.
    Measured by a failure-mode pass: delete one entry from
    ``_LOCAL_RUNTIME_REL_PATHS``, run ``scripts/generate_doc_regions.py`` as its
    banner instructs, and ``README.md`` + ``docs/QUICKSTART.md`` both quietly
    change from *"reports/ — 3 files"* to *"2 files"* — **with the full suite at
    8023 passed, zero failures**. Every existing consumer read the same constant
    on both sides of its assertion, so the population narrowed everywhere at
    once and nothing disagreed.

    This is the layer `tests/test_doc_regions.py::TestFloorGuard` names as its
    backstop. That claim was true for ``required-gitignore`` (independently
    verified: dropping two entries reds four tests) and **false for the
    deploy-inventory region** until this existed — the floor sits 10 below a
    population of 40, so a one-line deletion never reaches it.
    """

    def test_local_runtime_rel_paths_is_the_five_install_artifacts(self):
        from espalier.managed_inventory import local_runtime_rel_paths

        assert local_runtime_rel_paths() == (
            ".claude/settings.json",
            ".espalier/integrity.json",
            "reports/cc_surface_gate.json",
            "reports/harness_config.json",
            "reports/repo_fingerprint.json",
        )

    def test_init_tool_scripts_is_the_standalone_tools_roster_in_declaration_order(self):
        """The deploy-inventory region's other unpinned limb: the seventeen
        scripts plus the Windows statusline shim, the one non-.py deploy
        (DEF-729). The ship driver joined on 2026-09-30: the deployed /ship
        and /handoff bodies call it, so a fresh init must carry it. The
        forward ledger's verbs and the pack-scope reader they load by path
        joined the same day. The record merge joined on 2026-10-05 (the
        nineteenth): the driver imports it as a sibling, so a fresh init
        without it would raise ModuleNotFoundError on the first `/ship`.
        The stack table joined on 2026-10-06, beside the blueprint limits:
        stdlib data the hook layer imports and the engine byte-copies. The
        session catch-up joined on 2026-10-08: session_start.py loads it by
        path, so an adopter's `session_catch_up = true` needs it deployed.
        The board and the merge-rules read joined on 2026-10-09: the deployed
        /inbox body runs the board, and session_start.py imports the read, so
        a fresh init without it would raise ModuleNotFoundError at SessionStart.
        The symbol mapper joined on 2026-10-17 (TP-702 Wave 1): mail.py imports
        it as a sibling, so every reader of the mail channel reaches it. The
        post-merge verdict module joined on 2026-10-19: ship.py and board.py
        import it as a sibling and session_start.py loads it by path. (The
        test was named for a count of eighteen until then; the roster is the
        count, so the name no longer carries one.)"""
        from espalier.cli import INIT_TOOL_SCRIPTS

        # Declaration order, not sorted. The first draft of this pin was typed
        # from the generated README block, which sorts for display -- so it
        # asserted an order the constant does not have and went red on arrival.
        # Worth keeping as a comment: a pin copied from a rendering is a pin on
        # the rendering.
        assert tuple(INIT_TOOL_SCRIPTS) == (
            "tools/cc/cognitive_blueprint.py",
            "tools/cc/execution_plan.py",
            "tools/cc/reflect_protocol.py",
            "tools/cc/session_resume.py",
            "tools/cc/read_summary.py",
            "tools/cc/session_summary.py",
            "tools/cc/statusline.py",
            "tools/cc/statusline.cmd",
            "tools/cc/sister_site_probe.py",
            "tools/cc/ship.py",
            "tools/cc/record_merge.py",
            "tools/cc/mail.py",
            "tools/cc/_symbols.py",
            "tools/cc/board.py",
            "tools/cc/_merge_rules.py",
            "tools/cc/_post_merge.py",
            "tools/cc/_record_fragments.py",
            "tools/cc/checkout_sync.py",
            "tools/cc/seat.py",
            "tools/cc/_blueprint_limits.py",
            "tools/cc/_stack_table.py",
            "tools/cc/_freshness_cache.py",
            "tools/cc/_paths.py",
            "tools/cc/_json_safe.py",
            "tools/cc/ledger_row.py",
            "tools/cc/generate_ledger_regions.py",
            "tools/cc/check_ledger_probes.py",
            "tools/cc/_pack_scope.py",
        )


class TestSeedDocs:
    """TP-255 R2: ``get_seed_docs`` is the single source of truth for the
    init-seeded convention scaffolds, consumed by BOTH cli.py's deploy loop and
    cleanup.py's undeploy accounting so the two cannot drift. Seeds must stay
    OUT of the public managed surface (PACK_MANIFEST / doctor / surface gate).
    """

    def test_returns_the_seed_scaffolds(self):
        assert get_seed_docs() == (
            "memory/README.md",
            "docs/sharp-edges/README.md",
            "docs/TROUBLESHOOTING.md",
            "docs/external/cc-hook-protocol.md",
            "docs/sharp-edges/convergence-is-an-angle-set-property.md",
            "docs/sharp-edges/closed-loop-verification-trap.md",
            "docs/sharp-edges/hook-exit-codes-channel-xor.md",
            "task-packs/CLAUDE.md",
            "docs/INSTALL-CI.md",
            "docs/FAILURE_MODES.md",
            "docs/PACK_AUTHORING.md",
            "docs/HOOKS.md",
            "docs/HOOK_ASSUMPTIONS.md",
            "docs/WORKFLOW.md",
            "docs/CHEAT-SHEET.md",
            "docs/TASK_RECIPES.md",
            "docs/FRESHNESS.md",
            "docs/ENV_CATALOG.md",
            "docs/SHARP_EDGES.md",
            "docs/CONVENTIONS.md",
            "memory/CONVERGENCE_LEDGER.md",
            "memory/convergence-review-protocol.md",
            "task-packs/FORWARD_LEDGER.md",
        )

    def test_seeds_stay_out_of_public_surface(self):
        """No seed path lives under a public managed prefix — seeds are
        operator-editable and must never leak into the shipped surface."""
        public_prefixes = get_managed_public_prefixes()
        for rel in get_seed_docs():
            assert not any(rel.startswith(p) for p in public_prefixes), (
                f"{rel} must not live under a public managed prefix "
                f"{public_prefixes}"
            )

    def test_install_ci_artifacts_stay_out_of_public_surface(self):
        """install-ci artifacts must never appear in get_managed_public_files --
        that would leak .github/workflows/harness-guard.yml into PACK_MANIFEST /
        doctor / the surface gate. clean-generated reaches them via the separate
        get_install_ci_artifacts owner, not the public inventory. (A pin, not an
        earn-red: it guards the invariant against a future change that would
        route these through the public inventory.)"""
        from pathlib import Path
        from espalier.managed_inventory import (
            get_install_ci_artifacts,
            get_managed_public_files,
        )
        public = set(get_managed_public_files(Path(".").resolve()))
        for rel in get_install_ci_artifacts():
            assert rel not in public, f"{rel} must stay out of the public surface"

    def test_tier2_docs_need_adapt_header_tier1_do_not(self):
        """Tier-2 carried docs (illustrative Espalier examples) get the
        deploy-time adapt-header; Tier-1 docs (portable method / CC protocol)
        ship verbatim."""
        assert seed_needs_adapt_header("docs/FAILURE_MODES.md") is True
        assert seed_needs_adapt_header("docs/CHEAT-SHEET.md") is True
        assert seed_needs_adapt_header("docs/external/cc-hook-protocol.md") is False
        # A non-seed path is never a Tier-2 doc.
        assert seed_needs_adapt_header("README.md") is False

    def test_adapt_header_set_is_subset_of_seed_docs(self):
        """Every Tier-2 (adapt-header) doc must actually be a seeded doc, or the
        header would be computed for a path init never deploys."""
        from espalier.managed_inventory import _SEED_DOCS_WITH_ADAPT_HEADER
        assert _SEED_DOCS_WITH_ADAPT_HEADER <= set(get_seed_docs())


class TestSeedAssetSourceIndirection:
    """A seed's packaged body normally lives at the asset path matching its
    destination. The adopter stubs break that identity on purpose: sourcing
    ``docs/SHARP_EDGES.md`` / ``docs/CONVENTIONS.md`` from
    ``espalier/assets/docs/`` would subject them to that directory's
    ``_MIRRORED`` + byte-parity contracts, forcing each stub to become a
    byte-copy of this repo's own doc — the opposite of a near-empty adopter
    scaffold. ``_SEED_ASSET_SOURCES`` redirects them to
    ``espalier/assets/seed/`` so both contracts keep full strength.
    """

    def test_override_resolves_and_identity_is_the_fallback(self):
        from espalier.managed_inventory import get_seed_asset_source
        assert get_seed_asset_source("docs/SHARP_EDGES.md") == "seed/SHARP_EDGES.md"
        assert get_seed_asset_source("docs/CONVENTIONS.md") == "seed/CONVENTIONS.md"
        # The two review-memory seeds: an identity path would enrol them in the
        # asset-docs mirrored set and copy this tree's own memo and ledger over them.
        assert get_seed_asset_source("memory/CONVERGENCE_LEDGER.md") == "seed/CONVERGENCE_LEDGER.md"
        assert get_seed_asset_source("memory/convergence-review-protocol.md") == "seed/convergence-review-protocol.md"
        # Unmapped seeds keep today's derivation (source path == destination).
        assert get_seed_asset_source("docs/HOOKS.md") == "docs/HOOKS.md"
        assert get_seed_asset_source("memory/README.md") == "memory/README.md"
        # A path that is not a seed at all is still returned unchanged — the
        # accessor is a lookup, not a validator.
        assert get_seed_asset_source("README.md") == "README.md"

    def test_no_override_is_the_identity(self):
        """An override equal to its key is dead config that re-enrols the seed in
        the mirrored set; every row must redirect somewhere else."""
        from espalier.managed_inventory import _SEED_ASSET_SOURCES
        for dest, src in _SEED_ASSET_SOURCES.items():
            assert src != dest, dest

    def test_every_override_key_is_a_seed_doc(self):
        """An override for a non-seeded destination is dead config: nothing in
        the deploy loop would ever ask for it."""
        from espalier.managed_inventory import _SEED_ASSET_SOURCES
        assert set(_SEED_ASSET_SOURCES) <= set(get_seed_docs())

    def test_no_override_points_back_into_assets_docs(self):
        """The indirection exists to get these bodies OUT of
        ``espalier/assets/docs/``. An override resolving back into that
        directory would silently re-enter the byte-parity + ``_MIRRORED``
        contracts and force the stub to mirror the self-host doc again."""
        from espalier.managed_inventory import _SEED_ASSET_SOURCES
        offenders = [
            f"{dest} -> {src}"
            for dest, src in _SEED_ASSET_SOURCES.items()
            if src.startswith("docs/")
        ]
        assert not offenders, (
            "seed asset source resolves back into espalier/assets/docs/, "
            f"re-entering the contracts the indirection avoids: {offenders}"
        )

    def test_every_seed_doc_has_a_packaged_asset(self):
        """Resolve EVERY seed through the accessor and confirm the asset exists.

        This is the pin that a packaging miss trips: the stubs ship only via the
        ``assets/seed/*.md`` package-data glob, and a missing glob leaves the
        source tree looking correct while a real install deploys fewer files.
        Covers the identity path and the overridden path with one oracle.
        """
        from espalier.assets import assets_root
        from espalier.managed_inventory import get_seed_asset_source
        missing = []
        for dest in get_seed_docs():
            source_rel = get_seed_asset_source(dest)
            node = assets_root().joinpath(*source_rel.split("/"))
            if not node.is_file():
                missing.append(f"{dest} <- espalier/assets/{source_rel}")
        assert not missing, (
            "seed doc has no packaged asset (init would raise mid-deploy):\n  "
            + "\n  ".join(missing)
        )

    def test_stubs_are_near_empty_not_copies_of_the_source_docs(self):
        """The point of the whole indirection: the adopter receives a scaffold,
        not this repo's own footgun catalog / convention doc. Guards against a
        future 'just sync them like the others' change that would ship the
        self-host bodies (the shipping-docs-verbatim footgun).
        """
        from pathlib import Path
        repo_root = Path(__file__).resolve().parent.parent
        for name in ("SHARP_EDGES.md", "CONVENTIONS.md"):
            stub = repo_root / "espalier" / "assets" / "seed" / name
            source = repo_root / "docs" / name
            assert stub.is_file(), f"missing adopter stub for {name}"
            assert stub.read_bytes() != source.read_bytes(), (
                f"espalier/assets/seed/{name} is a byte-copy of docs/{name} — "
                "adopters would receive this repo's own content as if it "
                "described theirs"
            )
            # "Near-empty" is the stated contract; the self-host docs are
            # thousands of lines. A generous ceiling still catches a full copy.
            assert len(stub.read_text(encoding="utf-8").splitlines()) < 60, (
                f"espalier/assets/seed/{name} is no longer a near-empty stub"
            )


class TestSeedStampRenderParity:
    """DEF-696: ``doctor`` prints the stamp ``init`` writes, so the two must be
    ONE renderer -- ``managed_inventory.render_seed_body`` under
    ``seed_stamp_line``. This is the oracle: on the real adopter tree (a driven
    ``init`` on a foreign repo, not this checkout) the rendered stamp is
    byte-equal to the first line on disk for EVERY seed, and its digest is of
    exactly the bytes below it. Both tiers are in the population, so a renderer
    that dropped the adapt header reds on the Tier-2 seeds and one that added
    it everywhere reds on the Tier-1 seeds; the stub-backed seeds are in it too,
    so a renderer that derived the source from the destination reds on those."""

    def test_rendered_stamp_is_the_first_line_init_wrote_for_every_seed(self, adopter_tree):
        from espalier.managed_inventory import render_seed_stamp, seed_stamp_line
        seeds = get_seed_docs()
        tiers = {seed_needs_adapt_header(rel) for rel in seeds}
        assert tiers == {True, False}, "both tiers must be in the population, or the header branch is unproven"
        # The forward ledger is the one seed init EDITS after stamping it: it
        # files the onboarding rows through the deployed verb, which keeps the
        # stamp line and rewrites the body. So its stamp is pinned like every
        # other seed's, and its body is pinned as edited -- not as untouched.
        from espalier.cli import _LEDGER_REL
        from espalier.managed_markers import seed_is_untouched
        mismatched = []
        for rel in seeds:
            text = (adopter_tree / rel).read_text(encoding="utf-8")
            first, rest = text.split("\n", 1)
            printed = render_seed_stamp(rel)
            body_matches = seed_stamp_line(rest) == printed
            if first + "\n" != printed or body_matches != (rel != _LEDGER_REL):
                mismatched.append(rel)
        assert not mismatched, (
            "doctor would print a stamp init did not write for: " + ", ".join(mismatched)
        )
        assert not seed_is_untouched((adopter_tree / _LEDGER_REL).read_text(encoding="utf-8")), (
            "init filed no onboarding row into the seeded ledger"
        )

    def test_tier2_body_carries_the_adapt_header_inside_the_digest(self):
        from espalier.managed_inventory import (
            SEED_ADAPT_HEADER,
            render_seed_body,
            render_seed_stamp,
            seed_stamp_line,
        )
        tier2 = render_seed_body("docs/FAILURE_MODES.md")
        tier1 = render_seed_body("docs/external/cc-hook-protocol.md")
        assert tier2.startswith(SEED_ADAPT_HEADER)
        assert not tier1.startswith(SEED_ADAPT_HEADER)
        # the header is INSIDE the digest: the bare asset stamps differently, so
        # a printed stamp over the asset alone would never match what init wrote
        assert render_seed_stamp("docs/FAILURE_MODES.md") != seed_stamp_line(
            tier2[len(SEED_ADAPT_HEADER):]
        )

    def test_stub_backed_seed_renders_the_stub_not_this_repos_doc(self):
        from espalier.managed_inventory import render_seed_body
        body = render_seed_body("docs/CONVENTIONS.md")
        assert len(body.splitlines()) < 60, "the adopter stub, not a catalog"
        assert body != (REPO_ROOT / "docs" / "CONVENTIONS.md").read_text(encoding="utf-8")

    def test_stamp_is_ascii_and_read_back_by_the_single_regex(self):
        """What doctor prints must be pasteable from any terminal and must be
        the line the fingerprint's own predicate recognises."""
        from espalier.managed_markers import SEED_STAMP_RE
        from espalier.managed_inventory import render_seed_stamp
        for rel in get_seed_docs():
            stamp = render_seed_stamp(rel)
            assert all(ord(ch) < 128 for ch in stamp), rel
            assert SEED_STAMP_RE.match(stamp), rel


# ---------------------------------------------------------------------------
# The roster the deployed censuses prune
# ---------------------------------------------------------------------------


class TestHarnessWrittenPaths:
    """``harness_written_paths`` is every path the harness may write on any
    tree; ``census_prune_paths`` is the part of it the deployed censuses prune
    on one tree, rendered into the repo-analyst's and code-reviewer's ``own``
    walk at deploy (DEF-4066: the body-kept list pruned two of the 38 files
    init had written, and the fused engine none). The second is never wider
    than what the harness wrote there: an adopter's own file at a path the
    harness might write stays counted."""

    def test_sorted_unique_root_relative_and_named_once(self, tmp_path):
        from espalier.managed_inventory import census_prune_paths, harness_written_paths

        for paths in (harness_written_paths(), census_prune_paths(tmp_path)):
            assert list(paths) == sorted(set(paths)), paths
            assert all(not p.startswith(("/", "./", "..")) and "\\" not in p for p in paths), paths
            dirs = [p for p in paths if p.endswith("/")]
            under = [p for p in paths if any(p != d and p.startswith(d) for d in dirs)]
            assert under == [], under  # a file under a listed directory is the directory's

    def test_every_init_install_ci_and_runtime_roster_is_in(self):
        from espalier import fusion_manifest, surface_contract
        from espalier.managed_inventory import get_install_ci_artifacts, get_local_runtime_prefixes, harness_written_paths
        from espalier.managed_paths import HARNESS_OWNED_ROOTS, STANDARD_MANAGED_ROOT_DOCS

        paths = harness_written_paths()

        def covered(rel: str) -> bool:
            return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in paths)

        assert all(covered(root + "/") for root in HARNESS_OWNED_ROOTS), paths
        for roster in (
            STANDARD_MANAGED_ROOT_DOCS, get_seed_docs(), get_local_runtime_prefixes(),
            get_install_ci_artifacts(), surface_contract.SHIPPED_TASK_PACK_FILES,
            surface_contract.SHIPPED_TASK_PACK_DIRS, fusion_manifest.FUSE_WRITTEN_FILES,
        ):
            missed = [rel for rel in roster if not covered(rel)]
            assert missed == [], missed

    def test_the_session_log_directory_is_the_loaders(self):
        """The rows a handoff writes, one file each: the census counted them as
        the adopter's Markdown after the first handoff (the review's M2)."""
        import ast

        from espalier import managed_inventory

        tree = ast.parse((REPO_ROOT / "tools" / "cc" / "_record_fragments.py").read_text(encoding="utf-8"))
        values = [
            node.value.value for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            and any(isinstance(t, ast.Name) and t.id == "SESSION_LOG_DIR" for t in node.targets)
        ]
        assert len(values) == 1, values
        assert values[0] + "/" in managed_inventory._HARNESS_RECORD_DIRS, values

    def test_the_fuse_manifest_is_in_with_its_tools_tree_entry_by_entry(self):
        from espalier import fusion_manifest, managed_inventory
        from espalier.managed_inventory import harness_written_paths

        paths = set(harness_written_paths())
        for rel in fusion_manifest.HARNESS_INCLUDE:
            if rel == "tools/":
                assert set(managed_inventory._FUSE_TOOLS_TREE) <= paths, paths
            elif rel.startswith(".claude/"):
                assert ".claude/" in paths
            else:
                assert rel in paths, rel
        assert "tools/" not in paths  # an adopter's own tools/ stays theirs

    def test_the_fuse_tools_tree_is_this_repositorys_tracked_tools_tree(self):
        """The hand copy of what ``tools/`` brings, pinned to git's view of the
        tree: a new top-level entry under ``tools/`` is one a fusion vendors and
        a census must prune."""
        from _live_tree import checkout_iterdir
        from espalier import managed_inventory

        entries = list(checkout_iterdir(REPO_ROOT / "tools"))
        assert entries, "git's view of tools/ is empty"
        top = {"tools/" + p.name + ("/" if p.is_dir() else "") for p in entries}
        assert top == set(managed_inventory._FUSE_TOOLS_TREE), top

    def test_the_files_fuse_writes_are_the_manifests(self, tmp_path):
        """The marker and the scoreboard placeholder, written where the
        manifest names them, so a fused tree's census prunes both (the
        review's m4)."""
        from espalier import fuse, fusion_manifest

        assert fuse._FUSION_MARKER == fusion_manifest.FUSION_MARKER
        assert fuse._seed_fusion_marker(tmp_path) is True
        (tmp_path / "bench").mkdir()
        assert fuse._seed_bench_results(tmp_path) is True
        written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
        assert written == set(fusion_manifest.FUSE_WRITTEN_FILES), written

    def test_fuse_paths_are_pruned_on_a_fused_tree_alone(self, tmp_path):
        from espalier import fusion_manifest
        from espalier.managed_inventory import census_prune_paths

        fuse_only = ("espalier/", "tools/__init__.py", "bench/README.md", "docs/external/",
                     fusion_manifest.FUSION_MARKER, "bench/RESULTS.md")
        plain = set(census_prune_paths(tmp_path))
        assert not plain & set(fuse_only), plain & set(fuse_only)
        assert {"tools/cc/", ".claude/", "cc/"} <= plain, plain
        assert set(fuse_only) <= set(census_prune_paths(tmp_path, fused=True))
        (tmp_path / fusion_manifest.FUSION_MARKER).write_text("# marker\n", encoding="utf-8")
        assert set(fuse_only) <= set(census_prune_paths(tmp_path))

    def test_an_adopters_own_seed_path_is_theirs_and_a_stamped_one_the_harnesss(self, tmp_path):
        """``init`` keeps an adopter's own ``docs/HOOKS.md`` and stamps the ones
        it writes; the census follows the stamp. On a fused tree a path the
        overlay brings is the harness's whatever its stamp."""
        from espalier.managed_inventory import census_prune_paths, render_seed_stamp

        assert "docs/HOOKS.md" in census_prune_paths(tmp_path)  # absent: init writes it
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "HOOKS.md").write_text("# Our webhooks\n", encoding="utf-8")
        assert "docs/HOOKS.md" not in census_prune_paths(tmp_path)
        assert "docs/HOOKS.md" in census_prune_paths(tmp_path, fused=True)
        (tmp_path / "docs" / "HOOKS.md").write_text(render_seed_stamp("docs/HOOKS.md") + "\nbody\n", encoding="utf-8")
        assert "docs/HOOKS.md" in census_prune_paths(tmp_path)

    def test_reports_are_pruned_by_suffix_never_whole(self, tmp_path):
        from espalier.managed_inventory import census_prune_paths

        paths = census_prune_paths(tmp_path)
        assert "reports/" not in paths and "reports/*.json" in paths, paths
        assert not [p for p in paths if p.startswith("reports/") and "*" not in p], paths

    def test_a_path_takes_the_casing_the_trees_directories_hold(self, tmp_path):
        """An adopter's ``Docs/`` on a filesystem that folds case holds the
        seeds ``init`` wrote, and ``find -path`` compares case (the review's
        m5). On a case-sensitive filesystem ``init`` writes ``docs/`` beside
        it, and the roster keeps that spelling."""
        from espalier.managed_inventory import _case_insensitive, census_prune_paths

        (tmp_path / "Docs").mkdir()
        paths = census_prune_paths(tmp_path)
        if _case_insensitive(tmp_path):
            assert "Docs/HOOKS.md" in paths and "docs/HOOKS.md" not in paths, paths
        else:
            assert "docs/HOOKS.md" in paths and "Docs/HOOKS.md" not in paths, paths
