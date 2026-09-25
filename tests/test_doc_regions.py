# slow-exempt: the one subprocess call is a single fast `git ls-files` enumeration
# over the region-bearing text globs, used so the census reads the tracked tree
# rather than a hand-written file list — the trade `test_catalog_self_consistency`
# already makes.
"""Pins for the doc regions generated from live Python objects.

Two distinct jobs, and it matters which is which:

1. **The machinery** -- ``scripts/generate_doc_regions.py``'s refusals. A
   generated region fails in one direction that a hand-written list cannot: it
   goes *shorter*, confidently and completely, with nothing left to disagree
   with it (``docs/STANDING_PRINCIPLES.md`` §14). The floor guard is what turns
   that silent narrowing into a refusal, so it is tested by mutation rather
   than by inspection.

2. **The census** -- ``TestEveryGeneratedRegionHasAGenerator``, which is the
   assertion §14 has promised since it was written (*"one trivial, reusable
   assertion covering every generated region, instead of N bespoke ones"*) and
   which did not exist. Before it, a marker pair added to any tracked markdown
   with no generator behind it was invisible to the whole suite: nothing
   scanned for markers, so the region simply rotted the way the hand-list it
   replaced would have.

**A deliberate divergence from the markdown-sourced precedent, stated so a
reviewer does not read it as a missing arm.** ``tests/test_implement_pack_step_zero.py``
carries a third arm that re-slices its source with independent logic, because
the round trip puts the generator on both sides of the ``==``
(``docs/sharp-edges/closed-loop-verification-trap.md``). That arm cannot exist
here. These regions are rendered from a Python object, so the only available
"second derivation" would read the same object -- which is
``docs/FAILURE_MODES.md`` §13.26, a duplication contract whose two sides are
not independent, and §14 calls a contract there theatre. What replaces it is
not a second derivation but a *property* check: the rendered block is asserted
to be complete with respect to its source (every entry present) and internally
consistent (every stated count equals the names beside it) -- both of which a
narrowing derivation fails and a byte-restatement would not catch.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parent.parent


def _load(script_name: str):
    """Load a ``scripts/*.py`` by path -- ``scripts/`` is not a package."""
    path = REPO / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = _load("generate_doc_regions.py")
CHECKLIST = _load("sync_checklist_regions.py")

#: Any ``<!-- <name>: BEGIN generated region ... -->`` line, whatever produced
#: it. Deliberately looser than either generator's own computed marker: the
#: point is to find regions NOBODY registered, so it cannot be built from the
#: registrations it is auditing.
_ANY_BEGIN_MARKER = re.compile(r"<!--\s*([\w:-]+):\s*BEGIN generated region")


#: Text formats a generated region could plausibly land in. NOT just `.md`:
#: `cc/PACK_MANIFEST.txt` is itself a generated surface doc and a plausible next
#: region target, as are the workflow YAML and `pytest.ini`. Measured with a
#: planted orphan -- a marker pair in `cc/PACK_MANIFEST.txt` was invisible to
#: the `.md`-only census while the suite stayed green.
_REGION_BEARING_GLOBS = ("*.md", "*.txt", "*.yml", "*.yaml", "*.toml", "*.ini")


def _tracked_text_files() -> list[str]:
    """Tracked files a region could live in.

    Tracked-only, and that limit is inherited rather than chosen: an untracked
    file is invisible to `git ls-files`, which is the documented `git add` trap
    in `tests/CLAUDE.md`. It bit this very change -- two contracts false-greened
    until the new files were staged.

    FAIL-CLOSED off a git worktree, and note there are TWO branches, not one --
    the second is why this needed a skip rather than a marker (2026-08-14):

      * no worktree up-chain (a downloaded release zip in ~/Downloads):
        `git ls-files` exits 128, so `check=True` RAISES.
      * a worktree up-chain but nothing tracked (an export extracted INSIDE a
        repo -- which is exactly where `final_release_matrix` stage 02 puts it,
        under the gitignored `dist/`): exits 0 with ZERO ROWS.

    The empty branch is the dangerous one: every caller asserts over the
    population, so an empty list passes them all while scanning nothing. That
    shipped as a green stage-02 "every generated region has a generator" run
    having read no files at all. Skipping here is deliberately at the SOURCE
    rather than at each caller, so a future test added to this module inherits
    the guard instead of re-earning it.
    """
    import subprocess

    try:
        completed = subprocess.run(
            ["git", "ls-files", *_REGION_BEARING_GLOBS], cwd=REPO,
            capture_output=True, text=True, check=True, encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("no git worktree at REPO: the tracked-set population is undefined")
    tracked = [p for p in completed.stdout.split("\n") if p.strip()]
    if not tracked:
        pytest.skip(
            "git reported zero tracked text files at REPO -- an export extracted "
            "inside a worktree. Asserting over an empty population would pass "
            "every caller while scanning nothing."
        )
    return tracked


def _registered() -> set[tuple[str, str]]:
    """``{(target_relpath, region_name)}`` across BOTH generator scripts."""
    pairs: set[tuple[str, str]] = set()
    for module in (GEN, CHECKLIST):
        for region in module.REGIONS:
            pairs.add((str(region.target).replace("\\", "/"), region.name))
    return pairs


# ── the machinery's refusals ─────────────────────────────────────────────


class TestRegionConstructionRefusals:
    #: Both generator scripts, because the guard was originally on only one --
    #: and on the LOWER-blast-radius one. `sync_checklist_regions` writes into
    #: `.claude/commands/implement-pack.md` and `.claude/skills/reflect/SKILL.md`,
    #: which ship to every adopter, where a flip to harness-owned means
    #: `clean-generated` deletes their command body. Parametrized so a third
    #: generator cannot arrive without it.
    _CONSTRUCTORS = (
        ("generate_doc_regions", lambda name: GEN.Region(
            name=name, target="README.md", source="x",
            render=lambda: ("body", 99), floor=1)),
        ("sync_checklist_regions", lambda name: CHECKLIST.Region(
            name=name, sot="tools/cc/pack_artifact_checklist.md",
            target=".claude/commands/implement-pack.md", prefix="", start="^1", end="^2")),
    )

    @pytest.mark.parametrize("script,make", _CONSTRUCTORS, ids=[c[0] for c in _CONSTRUCTORS])
    def test_ownership_marker_prefix_is_refused(self, script, make):
        """A name starting ``espalier:managed`` would make the target deletable.

        ``managed_markers._MARKER_LINE_RE`` ends in ``\\b``, which matches
        before a hyphen, so ``espalier:managed-region`` reads as an ownership
        marker: the file flips from operator-owned to harness-owned and
        ``clean-generated`` removes it. Refused at construction because the
        blast radius is a user losing a file, not a red test.
        """
        with pytest.raises(ValueError, match="clean-generated|deletes"):
            make("espalier:managed-region")

    @pytest.mark.parametrize("script,make", _CONSTRUCTORS, ids=[c[0] for c in _CONSTRUCTORS])
    def test_an_ordinary_name_is_accepted(self, script, make):
        """Vacuity guard: a constructor that rejected everything would pass above."""
        assert make("deploy-inventory") is not None

    def test_the_hazard_is_real_not_hypothetical(self):
        """Pin the upstream behaviour the refusal above exists for.

        If ``_MARKER_LINE_RE`` ever stops matching the hyphenated form, this
        red says the guard may be retired -- rather than leaving a refusal
        nobody can justify.
        """
        from espalier.managed_markers import has_managed_marker

        assert has_managed_marker("<!-- espalier:managed-region: BEGIN -->")
        assert not has_managed_marker("<!-- deploy-inventory: BEGIN -->")


class TestFloorGuard:
    """The floor is a BACKSTOP, and its permissiveness is deliberate.

    Measured: with ``required-gitignore`` at ``floor=8`` over 10 entries,
    dropping two entries lands exactly on the floor and does not refuse -- and
    the completeness arm cannot catch it either, because both sides read the
    same shrunken source. That gap is covered, one layer up, by exact population
    pins this suite deliberately does not duplicate (restating one here would be
    a second hand-copy of a population -- §C1 in the file closing §C1):

    * ``test_managed_inventory.py::TestSeedDocs::test_returns_the_seed_scaffolds``
    * ``test_managed_inventory.py::TestLocalRuntimeInventoryIsPinnedExactly``
    * ``test_init_gitignore_default.py::test_required_ignore_paths_match_cli_source``

    ⚠ **That backstop claim was HALF TRUE when first written, and a
    failure-mode pass proved it.** It held for ``required-gitignore`` (dropping
    two entries reds four tests) and was FALSE for ``deploy-inventory``: 17 of
    its 40 derived items -- ``local_runtime_rel_paths()`` and
    ``INIT_TOOL_SCRIPTS`` -- had no exact pin at all. Deleting one line from the
    runtime tuple silently changed README and QUICKSTART from "3 files" to "2"
    with the FULL SUITE GREEN at 8023 passed. The two pins above were added in
    response; the second and third rows of that list did not exist when this
    docstring first claimed them.

    So the floor exists for the case those pins cannot see: a *renderer* bug
    that silently emits fewer items than its source holds.
    """

    def test_a_shrunken_population_refuses_instead_of_writing(self):
        """The §14 hazard, proven by mutation: derive less, get a refusal."""
        region = GEN.Region(
            name="probe", target="README.md", source="probe-source",
            render=lambda: ("- one item", 1), floor=5,
        )
        with pytest.raises(ValueError, match="below the declared floor"):
            region.render()

    def test_a_population_at_the_floor_renders(self):
        region = GEN.Region(
            name="probe", target="README.md", source="probe-source",
            render=lambda: ("- one item", 5), floor=5,
        )
        assert region.render() == "- one item"

    def test_an_empty_block_refuses_even_above_the_floor(self):
        """Population size and rendered content can disagree; both are checked."""
        region = GEN.Region(
            name="probe", target="README.md", source="probe-source",
            render=lambda: ("   \n  ", 99), floor=1,
        )
        with pytest.raises(ValueError, match="empty block"):
            region.render()

    def test_every_live_region_sits_below_its_population(self):
        """A floor at or above the live count is a tripwire that already fired.

        It would red the next legitimate *addition* instead of the next
        accidental removal, so it is worth failing loudly here.
        """
        for region in GEN.REGIONS:
            _, population = region._render()
            assert population > region.floor, (
                f"{region.name}: floor {region.floor} >= live population "
                f"{population}. The floor is a tripwire against a derivation "
                "going wrong, not a running count -- keep it below the live "
                "number."
            )


class TestSpliceRefusals:
    def _region(self):
        return GEN.Region(
            name="probe", target="README.md", source="probe-source",
            render=lambda: ("BODY", 9), floor=1,
        )

    def test_duplicate_marker_pair_is_refused(self):
        """Writer and pinning test both take the FIRST pair, so a second would
        be regenerated by neither and checked by neither -- stale, and green."""
        r = self._region()
        doc = "\n".join([r.begin_marker, "x", r.end_marker,
                         r.begin_marker, "y", r.end_marker])
        with pytest.raises(ValueError, match="more than one"):
            GEN.splice(r, doc, "BODY")

    def test_missing_markers_are_refused(self):
        r = self._region()
        with pytest.raises(ValueError, match="markers not found"):
            GEN.splice(r, "a doc with no markers at all", "BODY")

    def test_splice_is_idempotent(self):
        """Round trip: splicing a rendered block leaves the region equal to it."""
        r = self._region()
        doc = "\n".join(["before", r.begin_marker, "stale", r.end_marker, "after"])
        once, _ = GEN.splice(r, doc, "BODY")
        twice, current = GEN.splice(r, once, "BODY")
        assert once == twice
        assert current == "BODY"
        assert once.startswith("before") and once.endswith("after")


# ── the renderers' properties (not a second derivation -- see module docstring)


class TestDeployInventoryProperties:
    def test_every_bullet_count_matches_the_names_beside_it(self):
        """The first cut of this renderer stated 5 and listed 3.

        It drew the count from the unfiltered runtime tuple and the names from
        a ``reports/``-filtered subset -- a count and a list from two
        populations, which is the defect class the region exists to close,
        reproduced inside its own generator.
        """
        block, _ = GEN.render_deploy_inventory()
        checked = 0
        for line in block.split("\n"):
            m = re.match(r"- \*\*`[^`]+`\*\* — (\d+) files?, ", line)
            if not m:
                continue
            checked += 1
            named = len(re.findall(r"`[^`]+`", line)) - 1  # minus the heading
            assert int(m.group(1)) == named, (
                f"bullet states {m.group(1)} but names {named}: {line[:80]}"
            )
        assert checked >= 5, f"only {checked} counted bullets -- renderer shape changed"

    def test_every_seed_doc_appears(self):
        """Completeness against the source: a narrowing derivation fails here."""
        from espalier import managed_inventory

        block, _ = GEN.render_deploy_inventory()
        missing = [
            rel for rel in managed_inventory.get_seed_docs()
            if f"`{rel.split('/', 1)[1] if '/' in rel else rel}`" not in block
        ]
        assert not missing, f"seed docs absent from the generated block: {missing}"

    def test_the_four_undisclosed_top_level_dirs_are_named(self):
        """The measured heart of DEF-473.

        ``init`` creates four top-level entries that neither hand-written list
        disclosed; a reader who ran the documented command met them for the
        first time in ``git status``.
        """
        block, _ = GEN.render_deploy_inventory()
        for top in ("docs/", "memory/", "task-packs/", "cc/"):
            assert f"**`{top}`**" in block, f"{top} not disclosed"


class TestRequiredGitignoreProperties:
    def test_every_canon_entry_is_rendered(self):
        from espalier import cli

        block, _ = GEN.render_required_gitignore()
        missing = [e for e in cli.REQUIRED_GITIGNORE
                   if e not in block.split("\n")]
        assert not missing, f"entries missing from the generated fence: {missing}"

    def test_the_header_comes_from_the_single_owner(self):
        from espalier import cli

        block, _ = GEN.render_required_gitignore()
        assert cli.GITIGNORE_BLOCK_HEADER in block

    def test_markers_would_sit_outside_the_fence(self):
        """The block opens and closes its own fence.

        An HTML comment inside a ``` block renders literally, and this is the
        one block on the page a reader selects and copies -- marker text
        landing in their ``.gitignore`` would be the fix minting its own defect.
        """
        block, _ = GEN.render_required_gitignore()
        lines = block.split("\n")
        assert lines[0] == "```" and lines[-1] == "```"


# ── the census §14 promised and nobody built ─────────────────────────────


class TestEveryGeneratedRegionHasAGenerator:
    """No marker pair may exist that no generator owns.

    ``docs/STANDING_PRINCIPLES.md`` §14 closes by naming this as the whole
    prize of generation -- *"one trivial, reusable assertion covering every
    generated region, instead of N bespoke ones"* -- and then it was never
    written. Until now nothing in the suite scanned for markers at all, so a
    region added with no generator behind it was invisible: it would rot
    exactly like the hand-list it replaced, while reading as machine-maintained
    to everyone who saw the *do not hand-edit* banner. That is strictly worse
    than the hand-list, because the banner discourages the one repair a human
    would otherwise make.

    Mirror copies are resolved through ``espalier/mirror_registry.py`` rather
    than allowlisted here. Four of the eight files carrying markers today are
    byte-mirrors of a registered target, and hand-listing them would be a
    second copy of the census the registry already owns -- §C1 inside the test
    closing §C1.
    """

    @staticmethod
    def _is_mirror_of_a_registered_target(rel: str, name: str) -> bool:
        from espalier import mirror_registry

        for row in mirror_registry.MIRROR_ROWS:
            for target, region_name in _registered():
                if region_name != name:
                    continue
                # `covers`, not `counterpart`: the latter is POSITIONAL only --
                # it maps a path without checking the row actually mirrors that
                # file, so an orphan marker planted at a phantom mirror path was
                # accepted. `covers` stats the mirror side for curated rows.
                if (mirror_registry.covers(row, target, REPO)
                        and mirror_registry.counterpart(row, target) == rel):
                    return True
        return False

    def test_the_scan_finds_the_known_regions(self):
        """Vacuity guard: a regex that matches nothing would pass everything."""
        found = [
            rel for rel in _tracked_text_files()
            if _ANY_BEGIN_MARKER.search((REPO / rel).read_text(encoding="utf-8"))
        ]
        assert len(found) >= len(_registered()), (
            f"marker scan found {len(found)} marker-bearing file(s) but "
            f"{len(_registered())} regions are registered: {found}. A fixed "
            "floor of 4 would have let half the population go dark; this is "
            "pinned to the registrations so it cannot."
        )

    def test_every_marker_pair_is_registered_or_a_mirror(self):
        orphans: list[str] = []
        for rel in _tracked_text_files():
            text = (REPO / rel).read_text(encoding="utf-8")
            for match in _ANY_BEGIN_MARKER.finditer(text):
                name = match.group(1)
                if (rel, name) in _registered():
                    continue
                if self._is_mirror_of_a_registered_target(rel, name):
                    continue
                orphans.append(f"{rel} :: {name}")
        assert not orphans, (
            "generated region(s) with no generator behind them: "
            f"{sorted(orphans)}.\nA region nothing regenerates is a hand-list "
            "wearing a 'do not hand-edit' banner -- worse than the hand-list, "
            "because the banner discourages the repair. Register it in "
            "scripts/generate_doc_regions.py or scripts/sync_checklist_regions.py, "
            "or delete the markers."
        )

    def test_every_registered_region_has_its_markers_on_disk(self):
        """The other direction: a registration whose markers were deleted.

        Both scripts already refuse at runtime, but only when something runs
        them. This makes the mismatch a suite failure rather than a surprise
        at the next sync.
        """
        for target, name in sorted(_registered()):
            path = REPO / target
            assert path.is_file(), (
                f"region '{name}' is registered against {target}, which does "
                "not exist. Either the doc was deleted without dropping its "
                "registration, or the path is a typo -- both would otherwise "
                "surface as a bare FileNotFoundError here."
            )
            text = path.read_text(encoding="utf-8")
            found = {m.group(1) for m in _ANY_BEGIN_MARKER.finditer(text)}
            assert name in found, (
                f"{target} has no '{name}' BEGIN marker, but a generator "
                f"registers one. Region names present: {sorted(found)}."
            )


class TestEveryRegionIsInParityWithItsGenerator:
    """The round trip, parametrized over every region in both scripts.

    This is the single reusable assertion §14 describes. The bespoke
    per-region copies in ``tests/test_implement_pack_step_zero.py`` and
    ``tests/test_reflect_reasoning.py`` stay: each carries a transform arm and
    an independent-oracle arm that this cannot express, and their round-trip
    overlap is cheap.
    """

    @pytest.mark.parametrize("region", GEN.REGIONS, ids=lambda r: r.name)
    def test_python_sourced_region_matches_its_derivation(self, region):
        target = (REPO / region.target).read_text(encoding="utf-8")
        _, current = GEN.splice(region, target, "")
        assert current == region.render(), (
            f"{region.target}'s '{region.name}' region is stale. Run "
            "`python3 scripts/generate_doc_regions.py`."
        )

    @pytest.mark.parametrize("region", CHECKLIST.REGIONS, ids=lambda r: r.name)
    def test_markdown_sourced_region_matches_its_source(self, region):
        sot = (REPO / region.sot).read_text(encoding="utf-8")
        rendered = CHECKLIST.render(region, CHECKLIST.extract_items(region, sot))
        _, current = CHECKLIST.splice(
            region, (REPO / region.target).read_text(encoding="utf-8"), rendered,
        )
        assert current == rendered, (
            f"{region.target}'s '{region.name}' region is stale. Run "
            "`python3 scripts/sync_checklist_regions.py`."
        )


class TestTheGoverningRuleIsEnforced:
    """*Generate where the doc has no downstream copies; contract where it ships.*

    Until this existed the rule was **prose in three places and code in none**
    -- this module's docstring, `scripts/generate_doc_regions.py`'s, and
    `docs/STANDING_PRINCIPLES.md` §14 -- with nothing relating a `Region.target`
    to shipped-doc status. A failure-mode pass named the exact path: a future
    session decides `docs/TROUBLESHOOTING.md`'s roster "should just be generated
    like the others" (the most natural refactor available, since the two files
    sit side by side under one rule), registers a Region, runs the script, and
    the suite stays green. Adopters then receive a *do not hand-edit* block;
    the first time one edits a word, `cli._seed_redeploy_decision` returns
    `"preserve"` **permanently** and they hold a frozen block with no
    `scripts/` to regenerate it.

    Three independent oracles, because "does this doc ship" has three different
    answers depending on the route: `init` seeds it, a mirror row copies it, or
    `fuse` overlays it.
    """

    @pytest.mark.parametrize("region", GEN.REGIONS, ids=lambda r: r.name)
    def test_no_region_targets_a_doc_that_ships(self, region):
        from espalier import fusion_manifest, managed_inventory, mirror_registry

        rel = str(region.target).replace("\\", "/")

        assert rel not in set(managed_inventory.get_seed_docs()), (
            f"{rel} is an `init` seed doc. `cli._seed_redeploy_decision` returns "
            "'preserve' permanently once an adopter's post-stamp bytes diverge, "
            "so a generated region freezes on their first edit into a block they "
            "are told not to hand-edit and have no scripts/ to regenerate. "
            "Contract it in prose instead — see "
            "tests/test_troubleshooting_enumerations.py for the shape."
        )
        offending = [
            row.name for row in mirror_registry.MIRROR_ROWS
            if mirror_registry.covers(row, rel, REPO)
        ]
        assert not offending, (
            f"{rel} is the source side of mirror row(s) {offending}, so the "
            "region would be byte-copied into a surface no generator runs against."
        )
        assert rel not in set(fusion_manifest.HARNESS_INCLUDE), (
            f"{rel} is overlaid into a fusion by `espalier fuse`, which is a "
            "downstream copy with no scripts/ behind it."
        )

    def test_the_ship_oracles_are_not_vacuous(self):
        """Each oracle must actually reject something, or the arm above is decor."""
        from espalier import fusion_manifest, managed_inventory, mirror_registry

        assert "docs/TROUBLESHOOTING.md" in set(managed_inventory.get_seed_docs())
        assert any(
            mirror_registry.covers(row, "docs/TROUBLESHOOTING.md", REPO)
            for row in mirror_registry.MIRROR_ROWS
        )
        assert fusion_manifest.HARNESS_INCLUDE


class TestTheEditTimeAdvisoryCoversEveryRegion:
    """Every region must have a PostToolUse advisory, and it must be accurate.

    The family arrived with none. `tests/test_reinject_sync.py::TestMirrorCensusCoverage`
    is the mechanism that FORCES an advisory, and it derives its requirement from
    `mirror_registry.MIRROR_ROWS` -- which this family deliberately does not join,
    because a render-from-Python is not a byte-mirror. So the naming decision that
    bought correctness on one guard bought blindness on another, and the gap was
    invisible until a failure-mode pass drove the hook by hand.

    This is the twin that closes it: keyed on the region registry instead of the
    mirror registry, so the NEXT generator family cannot ship advisory-less either.
    """

    @staticmethod
    def _hook_regions():
        import importlib.util as iu

        path = REPO / "tools" / "cc" / "hooks" / "_reinject.py"
        spec = iu.spec_from_file_location("_reinject_probe", path)
        mod = iu.module_from_spec(spec)
        import sys
        sys.path.insert(0, str(path.parent))
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.path.remove(str(path.parent))
        return mod._GENERATED_DOC_REGIONS

    def test_the_hook_tuple_matches_the_script_registry(self):
        """Two hand-kept halves would be the very defect this file closes."""
        hook = {(target, name) for target, name, _src in self._hook_regions()}
        script = {
            (str(r.target).replace("\\", "/"), r.name) for r in GEN.REGIONS
        }
        assert hook == script, (
            "tools/cc/hooks/_reinject.py::_GENERATED_DOC_REGIONS has drifted from "
            f"scripts/generate_doc_regions.py::REGIONS.\n  only in hook:   "
            f"{sorted(hook - script)}\n  only in script: {sorted(script - hook)}\n"
            "A region with no row here gets no edit-time advisory, so a hand edit "
            "inside it is silently reverted by the next regenerate."
        )

    def test_each_advisory_names_the_real_canonical_source(self):
        """A wrong source sends the author to edit the wrong file."""
        by_name = {r.name: r for r in GEN.REGIONS}
        for target, name, source in self._hook_regions():
            assert source == by_name[name].source, (
                f"advisory for '{name}' names {source!r} but the region derives "
                f"from {by_name[name].source!r}."
            )
