"""The record/claim axis is one answer, consulted in several places.

``espalier.claim_extractor.RECORD_SURFACES`` is the single home for one question:
does this document assert what is true NOW (a claim surface — a pointer that stops
resolving is rot) or what was true THEN (a record — the same broken pointer is
expected aging, and "correcting" it falsifies the log)? Root ``CLAUDE.md`` Core
Rule 13 turns on that answer.

Several registries needed it before the axis existed, and each answered it privately.
``_RECONCILED`` below is the CHECKED list; this table is the reader's version of it,
and the first commit's table named five when six were reconcilable — the undercount
itself an instance of the enumeration gap this module is about:

===============================  =====================================================
registry                         its actual question
===============================  =====================================================
``FROZEN_RECORD_DOCS``           which audit-excluded docs are records, not live maps?
``_RECORD_SURFACE_DOCS``         which docs may carry unresolvable citations?
``_ANCHOR_SCAN_EXCLUDE_DOCS``    which docs are out of the anchor scan?
``_NOT_CAP_SURFACES``            which surfaces skip the memory-cap census?
``_EXCLUDE_FILES``               which docs may cite a test path that no longer exists?
``_DISCOVERY_EXEMPT``            which docs may enumerate sub-modes without being one?
absence from ``DEFAULT_DOC_GLOBS``  which docs are not audited for live claims at all?
===============================  =====================================================

The last row has no forward reconciliation and never will: an omission is not a
declaration, so there is nothing to check FROM. ``ESPALIER_MEMORY.md`` and
``CHANGELOG.md`` reach the axis by that route alone, which is why they carry their
own anchor arm rather than a subset assertion.

They are **not** five copies of one list, which is why this module reconciles them
rather than replacing them — collapsing them would destroy four distinct meanings.
Two of them exempt surfaces for mixed reasons, so their entries carry an explicit
class token; keying on the prose instead would put a classification one reword away
from changing.

What went wrong without this: ``ESPALIER_MEMORY.md`` is a record on any reading and
was named by *no* registry — its status lived only in a comment. A guard needing the
answer imported ``FROZEN_RECORD_DOCS``, which is a **partition** of
``EXCLUDED_DOC_GLOBS`` and structurally cannot contain a doc that is not
audit-excluded by path. The guard then ran, honestly and greenly, over a population
that excluded its own subject (``docs/FAILURE_MODES.md`` 13.28).
"""
from __future__ import annotations

# slow-exempt: the subprocess calls are `git ls-files` enumerations plus one
# `git check-ignore -q` per axis member (8 today) -- all local index reads, no
# network and no child interpreter. Whole module measured at 0.22s, slowest arm
# 0.09s. The calls exist because asserting a registry member with `.exists()` is a
# dev-tree fact that reds on every clone (docs/FAILURE_MODES.md 13.30), so the
# cheap git round-trips are the fix, not incidental cost.
import importlib.util
import subprocess
from pathlib import Path

import pytest

from tests._export_guard import pruned_from_this_tree

from espalier.claim_extractor import (
    DEFAULT_DOC_GLOBS,
    EXCLUDED_DOC_GLOBS,
    FROZEN_RECORD_DOCS,
    LIVE_STATE_MAPS,
    MIRROR,
    OUT_OF_DOMAIN,
    RECORD,
    RECORD_SURFACES,
    _enumerate_files,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# One row per registry this module reconciles forward. The docstring's table is
# prose for a reader; THIS is what is checked, and
# ``test_every_reconciled_registry_has_an_arm`` requires an arm per row -- so a
# registry added here without an arm reds, and an arm with no row reds too.
#
# "Absence from DEFAULT_DOC_GLOBS" is deliberately NOT a row: an omission is not a
# declaration, so there is nothing to reconcile forward FROM. That direction is
# covered instead by ``test_the_record_by_omission_pair_stays_on_the_axis``.
_RECONCILED = (
    "claim_extractor.FROZEN_RECORD_DOCS",
    "test_doc_source_citations._RECORD_SURFACE_DOCS",
    "test_catalog_self_consistency._ANCHOR_SCAN_EXCLUDE_DOCS",
    "test_documented_claims._NOT_CAP_SURFACES",
    "test_doc_test_citations._EXCLUDE_FILES",
    "test_documented_claims.TestScanSubmodesConsistent._DISCOVERY_EXEMPT",
)


def _load(rel: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, str(REPO_ROOT / rel))
    assert spec is not None and spec.loader is not None, f"cannot load {rel}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def registries():
    citations = _load("tests/test_doc_source_citations.py", "_rx_citations")
    catalog = _load("tests/test_catalog_self_consistency.py", "_rx_catalog")
    claims = _load("tests/test_documented_claims.py", "_rx_claims")
    return citations, catalog, claims


class TestEveryDeclaredRecordIsOnTheAxis:
    """A record declared anywhere must be a record everywhere.

    This is the assertion that would have caught the original defect: a registry
    naming a record the axis does not know about means the axis is incomplete, and
    the next guard to consult it inherits the gap.
    """

    def test_frozen_record_docs_are_on_the_axis(self):
        missing = sorted(set(FROZEN_RECORD_DOCS) - set(RECORD_SURFACES))
        assert not missing, (
            f"declared frozen records absent from RECORD_SURFACES: {missing}"
        )

    def test_citation_record_surfaces_are_on_the_axis(self, registries):
        citations, _, _ = registries
        missing = sorted(
            set(citations._RECORD_SURFACE_DOCS) - set(RECORD_SURFACES)
        )
        assert not missing, (
            "docs declared record surfaces for citation purposes but absent from "
            f"RECORD_SURFACES: {missing}. Core Rule 13's answer must not depend on "
            "which module asked."
        )

    def test_record_tagged_anchor_exclusions_are_on_the_axis(self, registries):
        _, catalog, _ = registries
        tagged = {
            rel
            for rel, cls in catalog._ANCHOR_SCAN_EXCLUDE_DOCS.items()
            if cls == RECORD
        }
        missing = sorted(tagged - set(RECORD_SURFACES))
        assert not missing, (
            f"anchor-scan exclusions tagged {RECORD!r} but absent from "
            f"RECORD_SURFACES: {missing}"
        )

    def test_record_tagged_cap_exemptions_are_on_the_axis(self, registries):
        _, _, claims = registries
        tagged = {
            rel
            for rel, (cls, _reason) in claims._NOT_CAP_SURFACES.items()
            if cls == RECORD
        }
        missing = sorted(tagged - set(RECORD_SURFACES))
        assert not missing, (
            f"memory-cap exemptions tagged {RECORD!r} but absent from "
            f"RECORD_SURFACES: {missing}"
        )

    def test_test_citation_excludes_are_on_the_axis(self, registries):
        """``_EXCLUDE_FILES`` states its reason in Core Rule 13 terms verbatim.

        It was not reconciled by the first version of this module, so the axis's own
        "single home" claim was false on arrival -- a new append-only log added there,
        the natural place since that guard reds first on a phantom citation, would
        never reach the axis.
        """
        citations2 = _load("tests/test_doc_test_citations.py", "_rx_testcites")
        missing = sorted(set(citations2._EXCLUDE_FILES) - set(RECORD_SURFACES))
        assert not missing, (
            f"test-citation excludes absent from RECORD_SURFACES: {missing}"
        )

    def test_submode_discovery_exemptions_are_on_the_axis(self, registries):
        _, _, claims = registries
        exempt = set(claims.TestScanSubmodesConsistent._DISCOVERY_EXEMPT)
        missing = sorted(exempt - set(RECORD_SURFACES))
        assert not missing, (
            f"sub-mode discovery exemptions absent from RECORD_SURFACES: {missing}"
        )

    def test_every_reconciled_registry_has_an_arm(self):
        """Describing a registry is not reconciling it.

        Keyed on ``_RECONCILED``, not on the docstring's table: parsing prose to
        decide what is checked is the failure this module exists to name, and the
        first version of this arm did exactly that -- its line-prefix heuristic
        counted a sentence and an indented continuation as registries.
        """
        import inspect

        arms = [
            n for n, _ in inspect.getmembers(TestEveryDeclaredRecordIsOnTheAxis)
            if n.startswith("test_") and n.endswith("_are_on_the_axis")
        ]
        assert len(arms) == len(_RECONCILED), (
            f"{len(_RECONCILED)} registries are declared reconciled but "
            f"{len(arms)} arms exist. Declared: {list(_RECONCILED)}. "
            f"Arms: {sorted(arms)}."
        )


class TestTheAxisDoesNotSwallowNonRecords:
    """Over-inclusion is the failure mode on the other side.

    "It is a record" is not a general excuse for a stale pointer. It holds only
    where the artifact is genuinely append-only, so the axis has to stay refusable.
    """

    def test_live_state_maps_are_never_records(self):
        overlap = sorted(set(LIVE_STATE_MAPS) & set(RECORD_SURFACES))
        assert not overlap, (
            f"{overlap} is classified a LIVE_STATE_MAP — it makes current-state "
            "citations, so its pointers must keep drifting red. A document cannot "
            "be both."
        )

    def test_mirrors_are_not_smuggled_in_as_records(self, registries):
        """Mirror population derived from the census, not from a test-local list.

        Keying on ``_NOT_CAP_SURFACES``'s seven MIRROR entries checked the seven
        mirrors that happen to also be memory-cap exemptions. The derivable set is
        far larger, so putting `espalier/assets/docs/FAILURE_MODES.md` on the axis --
        a defensible-looking edit, since its source already is one -- passed.
        Root ``CLAUDE.md`` names ``espalier/mirror_registry.py`` as the sole home of
        the mirror census; this reads it.
        """
        from espalier.mirror_registry import MIRROR_ROWS, counterpart, covers

        tracked = subprocess.run(
            ["git", "ls-files"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=30, encoding="utf-8",
        ).stdout.split()
        if not tracked:
            pytest.skip("`git ls-files` yielded nothing -- not a dev tree")
        mirrors = {
            counterpart(row, rel)
            for rel in tracked
            for row in MIRROR_ROWS
            if covers(row, rel, REPO_ROOT)
        } - {None}
        overlap = sorted(mirrors & set(RECORD_SURFACES))
        assert not overlap, (
            f"{overlap} is a byte-parity MIRROR target, not a record. A mirror's "
            "content is guaranteed by its sync row; calling it a record would "
            "excuse the drift the mirror contract exists to refuse."
        )

    def test_the_cap_exemption_mirrors_agree_with_the_census(self, registries):
        """Second eye: the hand-tagged MIRROR entries must be real mirror targets."""
        from espalier.mirror_registry import MIRROR_ROWS, counterpart, covers

        _, _, claims = registries
        tagged = {
            rel for rel, (cls, _r) in claims._NOT_CAP_SURFACES.items() if cls == MIRROR
        }
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=30, encoding="utf-8",
        ).stdout.split()
        if not tracked:
            pytest.skip("`git ls-files` yielded nothing -- not a dev tree")
        real = {
            counterpart(row, rel)
            for rel in tracked
            for row in MIRROR_ROWS
            if covers(row, rel, REPO_ROOT)
        } - {None}
        bogus = sorted(tagged - real)
        assert not bogus, (
            f"{bogus} is tagged MIRROR but is not a mirror target in any row of "
            "espalier/mirror_registry.py -- the tag is claiming a guarantee that "
            "no sync provides."
        )


class TestTheClassTokensAreAClosedVocabulary:
    """An opt-in string with no allowed set is a fail-open enumerator.

    Every reconciliation above filters ``if cls == RECORD``, so a token that is
    merely *different* -- a typo, a capitalisation, a copy-pasted neighbour --
    silently shrinks the checked set instead of failing. Mutation-measured: adding a
    record tagged ``"recrod"``, or tagged ``OUT_OF_DOMAIN``, leaves the whole suite
    green and drops the entry from every arm. This is the presence-check-cannot-see-
    absence shape, one level up from the defect these tokens were introduced to fix.
    """

    _CLASSES = frozenset({RECORD, MIRROR, OUT_OF_DOMAIN})

    def test_anchor_scan_exclusions_carry_a_known_class(self, registries):
        _, catalog, _ = registries
        bad = sorted(
            (rel, cls)
            for rel, cls in catalog._ANCHOR_SCAN_EXCLUDE_DOCS.items()
            if cls not in self._CLASSES
        )
        assert not bad, (
            f"unknown class token(s): {bad}. Allowed: {sorted(self._CLASSES)}. An "
            "unrecognised token is not an error today -- it just quietly leaves the "
            "entry out of every record reconciliation."
        )

    def test_cap_exemptions_carry_a_known_class_and_a_reason(self, registries):
        _, _, claims = registries
        bad = sorted(
            (rel, value if not isinstance(value, tuple) else value[0])
            for rel, value in claims._NOT_CAP_SURFACES.items()
            if not (
                isinstance(value, tuple)
                and len(value) == 2
                and value[0] in self._CLASSES
                and isinstance(value[1], str)
            )
        )
        assert not bad, (
            f"entries whose value is not (class, reason) with a known class: {bad}. "
            f"Allowed classes: {sorted(self._CLASSES)}. This also turns a revert to "
            "the old flat `path: reason` shape into a legible failure instead of an "
            "AttributeError from whichever arm unpacks first."
        )


class TestTheAxisIsHonest:
    def test_every_member_is_a_name_git_knows_about(self):
        """Tracked OR deliberately gitignored -- never a bare ``.exists()``.

        ``.exists()`` asserts a DEV-TREE fact. ``docs/session-archive.md`` is on this
        axis, is gitignored, and has never been committed (``git log --all`` on it is
        empty), so an existence check passes on the author's machine and reds on every
        clone and every CI matrix cell. The sibling module learned this in 2026-08 and
        its ``_gitignored_record_surfaces`` is the shape reused here; this arm was
        written with ``.exists()`` anyway and shipped the same defect, which is why the
        reason is recorded at the assertion rather than left in a commit message.

        Fails CLOSED: off a git work tree ``check-ignore`` returns 128, contributing
        nothing, which SHRINKS ``known`` and makes this stricter.

        §C21 (2026-08-14): that reasoning covers only ONE of the two ways git
        declines. With ``REPO_ROOT`` inside another worktree's gitignored
        directory, ``check-ignore`` returns rc 0 for EVERY path, so ``ignored``
        would swell to all of ``RECORD_SURFACES`` and this assertion would pass
        vacuously -- fail-OPEN, not closed. The ``tracked`` skip-guard below is
        what actually covers both cases (``git ls-files`` is rc 0 with zero rows
        there, so ``tracked`` is empty and the test skips before reaching this).
        It is LOAD-BEARING, not a convenience: do not remove it as dead code.
        """
        tracked = set(
            subprocess.run(
                ["git", "ls-files"], cwd=REPO_ROOT,
                capture_output=True, text=True, timeout=30, encoding="utf-8",
            ).stdout.split()
        )
        if not tracked:
            pytest.skip("`git ls-files` yielded nothing -- not a dev tree / fresh clone")
        ignored = {
            p for p in RECORD_SURFACES
            if subprocess.run(
                ["git", "check-ignore", "-q", p], cwd=REPO_ROOT,
                capture_output=True, timeout=10,
            ).returncode == 0
        }
        unknown = sorted(set(RECORD_SURFACES) - tracked - ignored)
        # On a release export a record surface can be absent by construction
        # (the internal docs the classifier withholds); git in the extract has
        # never heard of them for that reason, not because the registry names
        # a phantom (DEF-670).
        unknown = sorted(set(unknown) - pruned_from_this_tree(unknown))
        assert not unknown, (
            f"RECORD_SURFACES names paths git has never heard of: {unknown}. A registry "
            "that can name a phantom cannot be trusted to be complete -- but note the "
            "test is 'does git know this name', not 'is the file here': a deliberately "
            "gitignored record is absent from every clone and is still a real member."
        )

    def test_every_member_states_a_reason(self):
        """An EMPTINESS floor, not a quality bar -- 25 is well below any real entry.

        Stated so the number does not read as calibrated: the shortest live reason is
        ~50 chars, so this catches a blank or a one-word stub and nothing subtler. A
        length check cannot verify that a reason is *true*; that is a reader's job.
        """
        thin = sorted(p for p, why in RECORD_SURFACES.items() if len(why.strip()) < 25)
        assert not thin, (
            f"these axis entries have no usable reason: {thin}. The reason is what "
            "a future reader checks the classification against; without it the "
            "entry is an assertion nobody can audit."
        )

    def test_the_record_by_omission_pair_stays_on_the_axis(self):
        """These two are named by NO other registry -- delete a row and nothing remembers.

        Absence from ``DEFAULT_DOC_GLOBS`` is a non-declaration: it makes them
        unaudited, not classified. Their record status lived in a comment until the
        axis existed, and it now lives in exactly one dict entry. Deriving consumers
        from the axis fixed the ADD direction and widened the DELETE one -- removing
        a line here silently shrinks the subject of a guard in another module.
        """
        anchored = ("ESPALIER_MEMORY.md", "CHANGELOG.md")
        missing = [p for p in anchored if p not in RECORD_SURFACES]
        assert not missing, (
            f"{missing} left the record axis. No other registry names either file, "
            "so nothing else in this repo records that it is a historical narrative "
            "-- and any guard deriving its record set from the axis just stopped "
            "protecting it, silently."
        )

    def test_a_record_is_never_audited_as_a_live_claim_surface(self):
        """The axis and the audited-claim population must not overlap.

        This is the relationship the original defect lived in: a doc can be a record
        by classification and still sit in a scan that treats it as asserting current
        state, with nothing connecting the two facts.

        Population is RESOLVED, not the non-glob slice of the tuple. Filtering
        ``DEFAULT_DOC_GLOBS`` for entries without ``*`` yields exactly README.md,
        CLAUDE.md and CONTRIBUTING.md -- three files that could never plausibly be
        records -- while dropping the ``docs/*.md`` and ``.claude/`` globs where 5 of
        the 8 axis members live. The arm carried the assertion's name without ever
        having been load-bearing.
        """
        audited = {
            str(p.relative_to(REPO_ROOT)).replace("\\", "/")
            for p in _enumerate_files(REPO_ROOT, DEFAULT_DOC_GLOBS, EXCLUDED_DOC_GLOBS)
        }
        overlap = sorted(audited & set(RECORD_SURFACES))
        assert not overlap, (
            f"{overlap} is on the record axis yet inside the audited-claim "
            "population, so its historical numbers are checked as live claims."
        )


class TestTheEmptyPopulationGuardsAreLoadBearing:
    """§C21: pin the guards this module's own comments call load-bearing.

    `test_every_member_is_a_name_git_knows_about`'s docstring records the real
    direction: its `check-ignore` reads fail OPEN, not closed, when git answers
    about a foreign tree -- from inside an ignored directory `check-ignore`
    returns rc 0 for EVERY path, so `ignored` swells to all of `RECORD_SURFACES`
    and `unknown` is empty by construction. What actually prevents that is the
    `if not tracked: pytest.skip(...)` above it, which reads like ordinary
    defensive boilerplate and is nothing of the kind.

    A comment saying "do not remove this as dead code" is not a mechanism.
    These are. Deleting a guard now reds by name instead of silently reopening
    a fail-open hole that only shows up on an archive extracted under `dist/`.
    """

    class _Empty:
        """A `git` that answers successfully and says nothing -- the rc-0,
        zero-rows shape a gitignored subdirectory of another worktree returns."""
        returncode = 0
        stdout = ""
        stderr = ""

    @pytest.mark.parametrize("cls_name,test_name,needs_registries", [
        ("TestTheAxisDoesNotSwallowNonRecords",
         "test_mirrors_are_not_smuggled_in_as_records", True),
        ("TestTheAxisDoesNotSwallowNonRecords",
         "test_the_cap_exemption_mirrors_agree_with_the_census", True),
        ("TestTheAxisIsHonest",
         "test_every_member_is_a_name_git_knows_about", False),
    ])
    def test_an_empty_tracked_set_skips_rather_than_asserting(
        self, cls_name, test_name, needs_registries, registries, monkeypatch
    ):
        # Patch the module object the CLASS lives in, not a re-import: under
        # `pythonpath = ["."]` an `import tests.<mod>` yields a SECOND module
        # object and the patch lands on the wrong global.
        import sys

        mod = sys.modules[type(self).__module__]
        monkeypatch.setattr(
            mod.subprocess, "run", lambda *a, **k: TestTheEmptyPopulationGuardsAreLoadBearing._Empty()
        )
        method = getattr(getattr(mod, cls_name)(), test_name)
        # Two of the three take the module-scoped `registries` fixture. Calling
        # them bare raised TypeError, which `pytest.raises(Skipped)` reported as
        # DID NOT RAISE -- the pin failing loudly on its own wiring rather than
        # passing, which is the property that makes it worth having.
        args = (registries,) if needs_registries else ()
        with pytest.raises(pytest.skip.Exception):
            method(*args)
