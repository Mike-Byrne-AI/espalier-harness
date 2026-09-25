"""TP-328: production-source citation contract for hand-maintained live-state maps.

The sibling ``tests/test_doc_test_citations.py`` resolves backtick ``tests/test_*.py``
citations against ``git ls-files``. That contract proves the mechanism works but does not
cover **production-source** citations (``espalier/**``, ``tools/cc/**``, ``.claude/**``,
``pyproject.toml``) — which is exactly what a *live-state map* leans on. A live-state map
(``espalier.claim_extractor.LIVE_STATE_MAPS``) is a doc that is audit-excluded yet makes
current-state ``path::symbol`` claims: nothing else catches a citation that rots on a
rename. This contract closes that gap by resolving each such citation's file (and its
``::symbol`` when the target is a ``.py`` file) against the tracked tree.

Design (mirrors the sibling, deliberately narrower):

- **Population is DERIVED, not hand-listed** (``_swept_docs``) — tracked markdown under
  ``docs/`` / ``memory/`` / the repo root, plus the forward ledger and the router under
  ``task-packs/`` (tracked since 2026-09-21; the packs beside them are plan surfaces and
  stay out by predicate), so a new doc is covered the day it lands.
  ⚠ It was previously ``LIVE_STATE_MAPS``, which is **one file**: this contract guarded a
  single document while the identical rot class ran free across the rest. Measured after
  widening: **112 docs, 406 source citations** (docs/ 59 · memory/ 46 · root 7), and it
  immediately found one real rot (``CONVENTIONS.md``'s ``_atomic_io`` cell, whose own
  parenthetical admitted the path did not exist). ``test_swept_population_shape_is_pinned``
  fails closed if the derivation ever loses a subtree.
- **Line numbers are NOT resolved** — the regex tolerates a ``:NN`` suffix and ignores it;
  line anchors rot constantly and carry near-zero signal.
- **No ``tests/`` branch** — the registry's ``tests/test_*.py`` citations are already
  resolved by the sibling (which does not exclude the registry).
- **Proposal/recommendation citations are suppressed** — the registry is a *planning* doc
  that legitimately cites not-yet-built modules under ``Recommended:`` / ``Proposed pack:``
  / pack-queue rows; without this the contract false-fails on those. The token set is
  calibrated to zero false-positives against the live registry (per
  ``memory/calibrate-an-enforcement-contract-against-the-live-population.md``).
- **Four exemption classes, each derived from the live population and each stating its
  reason** — never-committed-but-real config (``.claude/settings.json`` and the Claude Code
  runtime's own files), append-only record surfaces, deliberately-unbuilt artifacts, and
  illustrative placeholder paths. Measured at introduction: 14 unresolved citations, of
  which exactly one was genuine rot. An unexplained exemption is how a guard quietly stops
  guarding, so each carries its rationale in-file and, where it can stale, a test that reds.

The registry is export-excluded, so the three tests that need it are registered in
``tests/conftest.py::_FULL_TREE_NODEIDS`` and auto-skip on a detected release export;
the rest sweep whatever docs ship and run there too (measured on a seeded export,
2026-09-23). ``slow`` (spawns ``git ls-files``).
"""
from __future__ import annotations

import collections
import re
import subprocess

import pytest

from espalier.surface_contract import is_shipped_pack

# Reuse the sibling's canonical resolvers rather than re-deriving them: the AST symbol
# resolver and the git-ls-files tracked-set are the same shape this contract needs. The
# package-qualified import (deliberate, mirroring tests/test_surface_hygiene_parity.py's
# established pattern) pulls in only functions + a Path constant, never Test* classes, so
# it cannot trigger re-collection of the sibling's tests.
# ⚠ ``_symbol_phantom`` resolves through the OWNING module's globals — its ``__globals__``
# is ``tests.test_doc_test_citations``, so ``REPO_ROOT``, ``_symbol_cache`` and
# ``_member_cache`` are read from THERE, not from this module's namespace. Monkeypatching
# this module's ``REPO_ROOT`` (the sibling's own established test idiom, which this module's
# docstring says it mirrors) is therefore INERT: the resolver keeps answering against the
# real repo and a fixture-based test silently passes for the wrong reason. Patch
# ``tests.test_doc_test_citations`` instead. Pinned by
# ``test_imported_resolver_reads_the_owning_modules_root``.
from tests.test_doc_test_citations import (
    REPO_ROOT,
    _symbol_phantom,
    _tracked_files,
)

# NOTE: ``LIVE_STATE_MAPS`` is deliberately NOT imported any more. It was this module's
# population until the sweep was derived; keeping the import alive would have preserved a
# tie that no longer carries meaning here. Its real contract — the symmetric difference
# with ``FROZEN_RECORD_DOCS`` — is owned by ``tests/test_doc_maintenance_classes.py``.

# group(1) = the production-source path (optionally with a ``:NN`` or ``:NN-MM`` line
# suffix, ignored); group(2) = the ``::Symbol`` chain (or None), resolved only for .py
# targets. The ``-MM`` arm matters: without it a range citation like ``pyproject.toml:70-76``
# fails the whole backtick match and is silently skipped — reopening the drift class this
# contract exists to close, for one citation shape.
# ``.`` is inside group 2's class for the same reason as the sibling module's: without it a
# ``::Class.member`` citation does not match AT ALL — the member text blocks the closing
# backtick — so a dotted phantom is silently skipped rather than flagged. Both modules carried
# the identical gap, so closing one would have been a half class-fix.
_SOURCE_CITATION_RE = re.compile(
    r"`((?:espalier|tools|\.claude)/[A-Za-z0-9_./-]+\.(?:py|md|json|toml)"
    r"|pyproject\.toml)(?::[0-9]+(?:-[0-9]+)?)?(?:::([A-Za-z0-9_.:]+))?`"
)
_CODESPAN_RE = re.compile(r"`[^`]*`")

# (1) Real but never-committed config, so a citation to it resolves despite being untracked.
# Two sub-classes, same reason: ``espalier init`` gitignores settings.json (it records a
# machine-detected interpreter name) and settings.local.json is its documented sibling; scheduled_tasks.json
# and loop.md are files the Claude Code RUNTIME writes into `.claude/` — this repo documents
# them (docs/CC_AUTOMATION.md) but does not own them and never commits them.
_EXPECTED_UNTRACKED = frozenset({
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/scheduled_tasks.json",
    ".claude/loop.md",
})

# A citation whose window names a *proposal* legitimately points at a not-yet-built
# module; the registry catalogues future SoT packs. Suppress those (codespans stripped so
# a filename's own substrings can't self-trigger). Calibrated to zero false-positives
# against the live registry — keep tight so a real rotted citation is not hidden.
_PROPOSAL_TOKENS = (
    "recommended",
    "proposed pack",
    "proposed:",
    "new module",
    "catalogued-deferred",
    "pack queue",
    "notes for the",
)


def _is_proposal(lines: list[str], idx: int) -> bool:
    window = lines[max(0, idx - 1): idx + 2]
    text = _CODESPAN_RE.sub(" ", "\n".join(window)).lower()
    return any(tok in text for tok in _PROPOSAL_TOKENS)


# ── The swept population ──────────────────────────────────────────────────────
# ``LIVE_STATE_MAPS`` is ONE file, so this contract used to guard one document while
# the same rot class ran free across the rest of the doc surface. The population is now
# derived from tracked markdown under ``docs/``, ``memory/`` and the repo root — measured
# 112 files, 406 source citations. Deriving it (rather than hand-listing) is the point: a
# new doc under those roots is covered the day it lands, with nobody remembering to enrol
# it. ⚠ Scope honesty: "covered the day it lands" holds INSIDE those three roots only.
# ``.claude/``, ``bench/`` and ``cc/`` markdown also carry source citations and are NOT
# swept here (measured zero live rot in them at introduction); the sibling module's
# ``_SCAN_GLOBS`` covers that wider surface for test-file citations. Widening this one is
# tracked work, not a claim already met.
#
# The four exemption classes below were each derived from the live population, not
# predicted. Measured at introduction: 14 unresolved citations, of which exactly ONE was
# genuine rot (``docs/CONVENTIONS.md``'s ``_atomic_io`` cell, repaired in the same
# change). Each class states its reason, because an unexplained exemption is how a guard
# quietly stops guarding — and each is pinned by a test that reds when its reason expires
# (``test_each_exemption_suppresses_on_purpose``), per docs/FAILURE_MODES.md §13.17:
# a narrowing needs its own earn-the-red.

# (2) Append-only RECORD surfaces. These quote findings — and the phantom citations
# inside them — VERBATIM, as the record of what a review round actually found. Editing
# one to satisfy a citation checker falsifies the record it exists to preserve. The
# sibling module excludes the same records for this identical reason; the convergence
# ledger's own header reads "Appended by: the convergence-critic", and its cited
# dead-code orphans were real symbols that were found dead and deleted.
_RECORD_SURFACE_DOCS = frozenset({
    "docs/session-archive.md",
    "memory/CONVERGENCE_LEDGER.md",
})

# (3) Artifacts this repo has DELIBERATELY not built, named in prose that proposes them.
# Kept as an explicit list rather than a prose-token match because the tokens that would
# catch them ("deferred", "would mechanize") are common enough to suppress real rot.
# ``test_unbuilt_allowlist_is_self_cleaning`` asserts every entry is still absent, so
# building one REDs the suite and forces its removal — the list cannot silently stale.
_DELIBERATELY_UNBUILT = frozenset({
    "tools/cc/confirm_test_failure.py",
    "tools/cc/scaffolding_canon.py",
    "tools/cc/forensic_run_audit.py",
    "espalier/recall_telemetry.py",
})


def _is_placeholder_path(path: str) -> bool:
    """(4) Illustrative placeholder paths — a single-character stem (``x.py``, ``X.md``).
    The sharp-edges docs demonstrate path-equivalence attacks with deliberately fake
    paths (``tools/CC/hooks/x.py`` for case folding, ``tools/cc/x.py`` for an NTFS
    stream); they are examples of a SHAPE, never citations. Keyed on the stem so no
    hand-list is needed and a new example is covered on arrival."""
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return len(stem) == 1


def _swept_docs(tracked: set[str]) -> list[str]:
    """Tracked markdown under ``docs/`` / ``memory/`` / the repo root, plus the
    forward ledger and the router under ``task-packs/``, minus the append-only
    record surfaces and the shipped packs. Tracked-only by the same reasoning the
    sibling module states: gitignored local state legitimately quotes historical
    phantoms and is absent on a fresh clone, so it is not a shipping-citation
    surface. A shipped pack (2026-09-21) is tracked but is a dated PLAN: it cites
    the files it proposes to create (44 such citations across 14 drafts when they
    first entered the tree), and its Affected-symbols walk re-derives them at
    execution -- so the one predicate that defines a pack keeps it out, and the
    ledger, whose rows are live claims, comes in."""
    return sorted(
        p for p in tracked
        if p.endswith(".md")
        and (
            p.startswith(("docs/", "memory/"))
            or "/" not in p
            or (p.startswith("task-packs/") and not is_shipped_pack(p))
        )
        and p not in _RECORD_SURFACE_DOCS
    )


def _find_source_phantoms(rel: str, lines: list[str], tracked: set[str]):
    """Backtick production-source citations in ``lines`` that do not resolve: the cited
    file is neither tracked nor an expected-untracked config, OR a ``.py`` target's cited
    ``::symbol`` is absent. Proposal-window citations are skipped."""
    phantoms: list[tuple[str, int, str, str]] = []
    for i, line in enumerate(lines):
        for m in _SOURCE_CITATION_RE.finditer(line):
            path, sym = m.group(1), m.group(2)
            if _is_proposal(lines, i):
                continue
            if path in _DELIBERATELY_UNBUILT or _is_placeholder_path(path):
                continue
            if path not in tracked and path not in _EXPECTED_UNTRACKED:
                phantoms.append((rel, i + 1, m.group(0), "file"))
                continue
            # Symbol resolution only for .py targets (the resolver AST-parses the file);
            # a ::symbol on a .md/.json/.toml would false-flag through an empty parse.
            if sym and path in tracked and path.endswith(".py"):
                # Shared with the sibling module rather than re-implemented: the dotted
                # arm has ONE owner, so a later correction cannot land on half the class.
                if _symbol_phantom(path, sym):
                    phantoms.append((rel, i + 1, m.group(0), "symbol"))
    return phantoms


class TestSourceCitationRegex:
    """Pin the regex's line-suffix tolerance, ranges included. A range like
    ``pyproject.toml:70-76`` must still match (the citation is visited; only the line
    suffix is ignored) — without the ``-MM`` arm the whole backtick span fails to match
    and the citation is silently skipped, reopening the very drift class this closes."""

    def test_single_line_suffix_matches(self):
        assert _SOURCE_CITATION_RE.search("`espalier/cli.py:120`")

    def test_range_line_suffix_matches(self):
        m = _SOURCE_CITATION_RE.search("`pyproject.toml:70-76`")
        assert m and m.group(1) == "pyproject.toml"
        m2 = _SOURCE_CITATION_RE.search("`tools/cc/_paths.py:10-20`")
        assert m2 and m2.group(1) == "tools/cc/_paths.py"

    def test_symbol_suffix_still_matches(self):
        m = _SOURCE_CITATION_RE.search("`tools/cc/hooks/_hook_utils.py::MUTATION_TOOLS`")
        assert m and m.group(2) == "MUTATION_TOOLS"

    def test_imported_resolver_reads_the_owning_modules_root(self):
        """Pin the cross-module seam as an executable fact, not a comment nobody reads.

        ``_symbol_phantom`` is imported from the sibling, so its ``__globals__`` is the
        SIBLING's module dict. Anyone testing it by monkeypatching *this* module's
        ``REPO_ROOT`` — the idiom the sibling itself uses, and which this module's
        docstring invites by saying it mirrors the sibling — gets a resolver that quietly
        keeps answering against the real repository. The failure mode is a green test that
        proved nothing. If the seam is ever closed properly (e.g. by threading an explicit
        root parameter), this test REDs and the fix gets acknowledged deliberately."""
        import tests.test_doc_test_citations as _owner
        assert _symbol_phantom.__globals__["__name__"] == _owner.__name__, (
            "the resolver no longer resolves through the owning module — re-derive the "
            "monkeypatch guidance at this module's import site before trusting it")

    def test_dotted_member_suffix_matches(self):
        """The same gap the sibling module carried, and the same failure mode: with ``.``
        outside group 2's class the member text blocks the closing backtick, the whole
        span fails, and the citation is silently SKIPPED — exactly the ``-MM`` story in
        this class's own docstring, one citation shape over. Closing it in only one of
        the two modules would have been a half class-fix."""
        m = _SOURCE_CITATION_RE.search(
            "`espalier/strengthen.py::PublicSymbol.has_docstring`")
        assert m and m.group(1) == "espalier/strengthen.py"
        assert m.group(2) == "PublicSymbol.has_docstring"


def _gitignored_record_surfaces() -> set[str]:
    """Record surfaces that are deliberately gitignored (so absent from a clone).

    ``git check-ignore`` answers "would git ignore this path", which is true on a
    clone that does not have the file -- unlike ``.exists()``, which is a dev-tree
    fact. Keeps the exclusion honest without demanding the file be present.

    Verified 2026-08-05: ``check-ignore -q`` returns 0 for an ignored path whether
    or not it exists on disk, and 128 outside a git work tree. The 128 case yields
    an EMPTY set here, which SHRINKS ``known`` and makes the caller's assertion
    stricter -- this helper fails CLOSED.

    §C21 (2026-08-14): that "fails CLOSED" holds for rc 128 and NOT for the other
    way git declines to answer about this tree. With ``REPO_ROOT`` inside another
    worktree's gitignored directory, ``check-ignore`` returns rc 0 for EVERY path
    -- a made-up filename included -- so this helper would return ALL of
    ``_RECORD_SURFACE_DOCS``, WIDENING ``known`` and making the caller looser, the
    exact inverse of the recorded direction.

    What actually protects this today is the caller's ``if not tracked:
    pytest.skip`` (``test_record_surfaces_are_excluded``), which fires in that
    case too because ``git ls-files`` there is rc 0 with zero rows. That guard is
    therefore LOAD-BEARING, not belt-and-braces: removing it re-opens a fail-OPEN
    hole, not a fail-closed one. Left as-is deliberately rather than routed
    through ``tests/_git_oracle.py`` -- the skip is the honest disposition here
    and re-raising would only convert a correct skip into a failure.
    """
    out: set[str] = set()
    for rel in _RECORD_SURFACE_DOCS:
        rc = subprocess.run(
            ["git", "check-ignore", "-q", rel],
            cwd=REPO_ROOT, capture_output=True, timeout=10,
        ).returncode
        if rc == 0:
            out.add(rel)
    return out


class TestSourceCitationPopulation:
    # ``test_source_citation_population_nonempty`` lived here and was DELETED, not moved.
    # Its docstring said an emptied ``LIVE_STATE_MAPS`` "would make this whole contract
    # vacuously pass" — true when the sweep read that tuple, FALSE the moment the population
    # was derived instead: ``_swept_docs`` never reads it, so emptying it now leaves all 112
    # docs swept and this contract fully live. Keeping a guard whose stated reason has been
    # falsified is the exact class the two commits alongside this one were about. The real
    # ``LIVE_STATE_MAPS`` contract is its symmetric difference with ``FROZEN_RECORD_DOCS``,
    # which is owned by ``tests/test_doc_maintenance_classes.py`` — the right module for it.
    # This module's fail-closed guard is ``test_swept_population_shape_is_pinned`` below.

    def test_redefined_registry_is_scanned(self):
        """Coverage witness: the known offender is in the scan population. Asserted against
        the DERIVED sweep, not against ``LIVE_STATE_MAPS`` — after the widening the two are
        no longer the same set, and checking membership of the old list would have measured
        the label instead of the fact this test is named for."""
        tracked = _tracked_files()
        if not tracked:
            pytest.skip("`git ls-files` yielded nothing — not a dev tree / fresh clone")
        assert "docs/REDEFINED_INFORMATION_REGISTRY.md" in _swept_docs(tracked)

    def test_swept_population_shape_is_pinned(self):
        """Fail closed on the SHAPE of the derivation, not on a total count.

        A bare floor is the wrong instrument because the risk is relative, not absolute.
        Measured composition is docs/ 59 · memory/ 46 · root 7 = 112, so a refactor that
        tidied the predicate down to ``p.startswith("docs/")`` would drop **all 46**
        ``memory/`` docs — including every ``memory/*-protocol.md`` the root charter's Core
        Rules point at — and still leave 66, sailing past any floor low enough to be
        stable. Losing a whole subtree is the realistic failure and a count cannot see it.

        Pinning the root set catches that; the small per-root floor catches a subtree being
        emptied rather than removed."""
        tracked = _tracked_files()
        if not tracked:
            pytest.skip("`git ls-files` yielded nothing — not a dev tree / fresh clone")
        swept = _swept_docs(tracked)
        by_root = collections.Counter(
            p.split("/")[0] if "/" in p else "<root>" for p in swept)
        # task-packs/ joined 2026-09-21 with a floor of its own: the ledger and
        # the router are its whole contribution by design (the packs are plan
        # surfaces, excluded by predicate), so the five-doc floor the other
        # roots carry would misread that as an emptied subtree.
        floors = {"docs": 5, "memory": 5, "<root>": 5, "task-packs": 1}
        assert set(by_root) == set(floors), (
            f"the swept population gained or lost a root: {dict(by_root)} — re-derive "
            "_swept_docs deliberately instead of letting a subtree drop out silently"
        )
        assert all(by_root[root] >= floor for root, floor in floors.items()), (
            f"a swept root has near-zero docs: {dict(by_root)} against {floors}")

    def test_the_ledger_is_swept_and_the_packs_are_not(self):
        """Both directions of the 2026-09-21 widening, against the derived sweep."""
        tracked = _tracked_files()
        if "task-packs/FORWARD_LEDGER.md" not in tracked:
            pytest.skip("the forward ledger is not tracked on this tree")
        swept = set(_swept_docs(tracked))
        assert "task-packs/FORWARD_LEDGER.md" in swept
        packs = sorted(p for p in tracked if is_shipped_pack(p))
        assert packs, "the ledger is tracked but no shipped pack is -- re-derive the ship set"
        assert not (set(packs) & swept), (
            f"shipped packs are plan surfaces and must stay out of the sweep: {sorted(set(packs) & swept)[:5]}"
        )

    def test_record_surfaces_are_excluded(self):
        """The append-only record surfaces stay OUT of the sweep. They quote findings —
        phantom citations included — as the record of what a round found; 'repairing' one
        falsifies that record."""
        tracked = _tracked_files()
        if not tracked:
            pytest.skip("`git ls-files` yielded nothing — not a dev tree / fresh clone")
        swept = set(_swept_docs(tracked))
        for rel in _RECORD_SURFACE_DOCS:
            assert rel not in swept, f"{rel} is an append-only record surface, not a claim surface"
        # ...and the exclusion is not silently naming nothing. Presence on THIS tree is
        # NOT the test: a record surface may be deliberately gitignored (docs/session-archive.md
        # is -- classify_release_path == 'internal'), so `.exists()` asserts a dev-tree fact and
        # reddened every fresh clone. The honest test is that the name is one git knows about --
        # tracked here, present here, or ignored by an actual rule.
        known = tracked | {
            p for p in _RECORD_SURFACE_DOCS if (REPO_ROOT / p).exists()
        } | _gitignored_record_surfaces()
        assert set(_RECORD_SURFACE_DOCS) <= known, (
            "a record-surface exclusion names a path git has never heard of: "
            f"{sorted(set(_RECORD_SURFACE_DOCS) - known)}"
        )

    def test_unbuilt_allowlist_is_self_cleaning(self):
        """Every deliberately-unbuilt artifact must still be absent. If one gets BUILT this
        REDs, forcing its removal from the allowlist — without which the entry would go on
        silently suppressing a citation that has become resolvable, and the allowlist would
        rot into exactly the stale hand-list this repo has canon about."""
        built = [p for p in sorted(_DELIBERATELY_UNBUILT) if (REPO_ROOT / p).exists()]
        assert not built, (
            "these are allowlisted as deliberately-unbuilt but now EXIST — remove them "
            f"from _DELIBERATELY_UNBUILT so their citations are guarded again: {built}"
        )

    def test_placeholder_paths_are_recognised(self):
        """The single-character-stem rule, pinned in both directions so it cannot quietly
        widen into a blanket suppressor."""
        assert _is_placeholder_path("tools/cc/x.py")
        assert _is_placeholder_path("tools/CC/hooks/x.py")
        assert _is_placeholder_path("espalier/assets/docs/X.md")
        # Real modules must NOT be swallowed — especially short ones.
        assert not _is_placeholder_path("espalier/cli.py")
        assert not _is_placeholder_path("tools/cc/_paths.py")
        assert not _is_placeholder_path("espalier/fuse.py")

    def test_each_exemption_suppresses_on_purpose(self):
        """§13.17 earn-the-red for the NARROWINGS themselves: plant a violation inside each
        excluded region and confirm the gate stays green **deliberately**.

        The other exemption tests check each set in isolation — that its paths exist, or
        do not, or match a predicate. None of them walks the actual scanner over a citation
        the exemption suppresses, so deleting a suppression branch from
        ``_find_source_phantoms`` reddened nothing. That is a narrowing with no earn-the-red,
        which is precisely what §13.17 (canonised in ``5636fcf``, alongside this change)
        says not to ship."""
        tracked = _tracked_files()
        if not tracked:
            pytest.skip("`git ls-files` yielded nothing — not a dev tree / fresh clone")
        for cite, why in (
            ("`tools/cc/forensic_run_audit.py`", "_DELIBERATELY_UNBUILT"),
            ("`tools/cc/x.py`", "_is_placeholder_path"),
            ("`.claude/scheduled_tasks.json`", "_EXPECTED_UNTRACKED"),
        ):
            planted = _find_source_phantoms("docs/_probe.md", [f"See {cite} here."], tracked)
            assert not planted, f"{why} failed to suppress {cite}: {planted}"
        # A control in the same shape: an unexempted missing path MUST still be flagged,
        # so the assertions above cannot be passing because the scanner is simply inert.
        control = _find_source_phantoms(
            "docs/_probe.md", ["See `espalier/definitely_not_real.py` here."], tracked)
        assert control, "the scanner flagged nothing at all — the exemption proof is vacuous"
        # And the record surfaces are excluded at the POPULATION level, not per-citation.
        assert "docs/session-archive.md" not in _swept_docs(tracked)

    def test_placeholder_rule_suppresses_nothing_real(self):
        """Calibrate the rule against the LIVE population, not a hand-picked negative set.
        Zero tracked files have a single-character stem today, so the rule suppresses
        nothing real — and if anyone ever adds ``espalier/x.py`` this REDs, which is the
        point: that file's citations would otherwise be silently unguarded forever, and
        nothing else in the repo would notice. A hand-picked negative list could never
        catch that; only the derived population can."""
        tracked = _tracked_files()
        if not tracked:
            pytest.skip("`git ls-files` yielded nothing — not a dev tree / fresh clone")
        swallowed = sorted(
            p for p in tracked
            if p.endswith((".py", ".md", ".json", ".toml")) and _is_placeholder_path(p)
        )
        assert not swallowed, (
            "the placeholder rule now suppresses REAL tracked files — their citations "
            f"are silently unguarded. Narrow the rule or rename them: {swallowed}"
        )


class TestTheEmptyPopulationGuardsAreLoadBearing:
    """§C21: pin the guards whose comments call themselves load-bearing.

    `_gitignored_record_surfaces`'s docstring records that this module's
    `check-ignore` reads fail OPEN, not closed, when git answers about a foreign
    tree -- `check-ignore` returns rc 0 for EVERY path from inside an ignored
    directory, so `known` would swell to all of `_RECORD_SURFACE_DOCS` and the
    assertion would pass over nothing. The only thing standing between that and
    a false green is the `if not tracked: pytest.skip(...)` above it, which
    reads like ordinary defensive boilerplate.

    Prose cannot stop a tidy-up pass (or an agent asked to "remove redundant
    guards") deleting it -- the suite would stay green everywhere and the hole
    would open silently. These four assert the skip actually fires, so removing
    a guard reds immediately and by name.
    """

    @pytest.mark.parametrize("test_name", [
        "test_redefined_registry_is_scanned",
        "test_swept_population_shape_is_pinned",
        "test_record_surfaces_are_excluded",
        "test_each_exemption_suppresses_on_purpose",
    ])
    def test_an_empty_tracked_set_skips_rather_than_asserting(
        self, test_name, monkeypatch
    ):
        # Patch the module object the CLASS actually lives in. `import
        # tests.test_doc_source_citations` yields a SECOND module object under a
        # different key than the one pytest imported (rootdir + `pythonpath =
        # ["."]`), so patching that one leaves the real global untouched and the
        # guard never fires. Caught because these reds said DID NOT RAISE rather
        # than passing -- an assert-on-absence that fails loudly when its own
        # setup is wrong is the shape worth copying.
        import sys

        mod = sys.modules[TestSourceCitationPopulation.__module__]
        monkeypatch.setattr(mod, "_tracked_files", lambda: set())
        method = getattr(TestSourceCitationPopulation(), test_name)
        with pytest.raises(pytest.skip.Exception):
            method()


class TestDocSourceCitations:
    def test_every_source_citation_resolves(self):
        tracked = _tracked_files()
        if not tracked:
            pytest.skip("`git ls-files` yielded nothing — not a dev tree / fresh clone")

        phantoms: list[tuple[str, int, str, str]] = []
        for rel in _swept_docs(tracked):
            path = REPO_ROOT / rel
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            phantoms.extend(_find_source_phantoms(rel, lines, tracked))

        assert not phantoms, (
            "Docs cite production-source paths/symbols that don't resolve (rot on "
            "rename/move). Pick the one that applies:\n"
            "  • The target EXISTS but is untracked → `git add` it. This contract "
            "resolves against `git ls-files`, so a brand-new file false-REDs here until "
            "it is staged. This is the most common cause.\n"
            "  • It was renamed/moved → repoint the citation at the live site.\n"
            "  • It names a module deliberately NOT built → add it to "
            "`_DELIBERATELY_UNBUILT` (a test then reds if it is ever built), or put the "
            "citation in a proposal window (Recommended:/Proposed pack:/pack queue).\n"
            "  • It is an illustrative placeholder → give it a single-character stem "
            "(`x.py`), which `_is_placeholder_path` recognises as an example, not a claim.\n"
            "  • The doc is an append-only RECORD of past findings → it belongs in "
            "`_RECORD_SURFACE_DOCS`, not in the sweep.\n"
            + "\n  ".join(f"{rel}:{ln}  {cite}  [{kind}]" for rel, ln, cite, kind in phantoms)
        )

    def test_phantom_source_citation_in_registry_is_flagged(self, tmp_path):
        """Earn-the-red coverage witness: inject a phantom production-source citation into
        a copy of the *real* registry and assert the scanner flags it. Witnesses that the
        contract catches rot in the actual doc, not just a synthetic minimal fixture."""
        tracked = _tracked_files()
        if not tracked:
            pytest.skip("`git ls-files` yielded nothing — not a dev tree / fresh clone")

        real = (REPO_ROOT / "docs/REDEFINED_INFORMATION_REGISTRY.md").read_text(encoding="utf-8")
        injected = real + "\n\n### Injected coverage witness\n\n**Sites:** `espalier/does_not_exist.py`\n"
        phantoms = _find_source_phantoms(
            "docs/REDEFINED_INFORMATION_REGISTRY.md", injected.splitlines(), tracked
        )
        assert any("does_not_exist" in cite for _rel, _ln, cite, _k in phantoms), (
            "scanner failed to flag an injected phantom production-source citation"
        )
        # And the un-injected real registry has zero phantoms (Wave 2 cleaned it).
        assert not _find_source_phantoms(
            "docs/REDEFINED_INFORMATION_REGISTRY.md", real.splitlines(), tracked
        ), "real registry already carries an unresolved production-source citation"

    def test_phantom_dotted_member_citation_is_flagged(self):
        """CONSUMER-side witness for the member arm — the owner's test is not enough.

        ``test_dotted_member_suffix_matches`` pins only the regex, and the ``::symbol``
        witness below uses a bare symbol, so the member-level resolution *in this module*
        had no test that failed when it was removed: reverting ``_find_source_phantoms``
        to head-only resolution left the whole module green. The resolver is shared, so
        the owner was protected and the importer was not — the reverse of the usual
        shared-code worry, and worse, because this is the module whose swept population
        grew by two orders of magnitude.

        Uses the REAL ``PublicSymbol`` dataclass so the fixture cannot drift from the
        thing it stands for: ``name`` is a live annotated field, ``has_docstring`` was
        removed as dead code."""
        tracked = _tracked_files()
        if not tracked:
            pytest.skip("`git ls-files` yielded nothing — not a dev tree / fresh clone")
        lines = [
            "Real member: `espalier/strengthen.py::PublicSymbol.name`.",
            "Gone member: `espalier/strengthen.py::PublicSymbol.has_docstring`.",
            "Real class:  `espalier/strengthen.py::PublicSymbol`.",
        ]
        flagged = {c for _rel, _ln, c, kind in
                   _find_source_phantoms("docs/_probe.md", lines, tracked) if kind == "symbol"}
        assert "`espalier/strengthen.py::PublicSymbol.has_docstring`" in flagged
        assert "`espalier/strengthen.py::PublicSymbol.name`" not in flagged
        assert "`espalier/strengthen.py::PublicSymbol`" not in flagged

    def test_phantom_source_symbol_citation_is_flagged(self):
        """Earn-the-red twin of the file-not-found witness above, for the ``::symbol``
        arm (TP-328's own motivating defect): a citation to a REAL tracked ``.py`` file
        with a symbol that does NOT resolve must be flagged, kind ``"symbol"`` — while a
        citation to a symbol that DOES resolve stays clean. Without this the symbol arm of
        ``_find_source_phantoms`` had no committed witness (only the file arm did)."""
        tracked = _tracked_files()
        if not tracked:
            pytest.skip("`git ls-files` yielded nothing — not a dev tree / fresh clone")

        real = (REPO_ROOT / "docs/REDEFINED_INFORMATION_REGISTRY.md").read_text(encoding="utf-8")
        injected = real + (
            "\n\n### Injected symbol coverage witness\n\n"
            "**Phantom symbol:** `espalier/claim_extractor.py::ThisSymbolDoesNotExist`\n\n"
            "**Resolving symbol:** `espalier/claim_extractor.py::Claim`\n"
        )
        phantoms = _find_source_phantoms(
            "docs/REDEFINED_INFORMATION_REGISTRY.md", injected.splitlines(), tracked
        )
        # the unresolved symbol on a real .py file is flagged, kind "symbol"...
        assert any(
            kind == "symbol" and "ThisSymbolDoesNotExist" in cite
            for _rel, _ln, cite, kind in phantoms
        ), "scanner failed to flag a phantom ::symbol citation to a real tracked .py file"
        # ...and a symbol that DOES resolve is not flagged (discriminating control).
        assert not any(
            "::Claim" in cite for _rel, _ln, cite, _kind in phantoms
        ), "scanner false-flagged a resolving ::symbol citation"
