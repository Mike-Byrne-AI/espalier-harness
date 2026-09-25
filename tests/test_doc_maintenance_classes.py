"""TP-328: partition-completeness contract for audit-excluded docs.

A doc excluded from ``audit_accuracy`` (``espalier.claim_extractor.EXCLUDED_DOC_GLOBS``)
is one of two kinds, and the harness must treat them differently:

- a **LIVE_STATE_MAP** — hand-written prose whose *facts* are current-state ``path::symbol``
  citations that rot on rename; guarded by ``tests/test_doc_source_citations.py``; and
- a **FROZEN_RECORD_DOC** — an append-only log/catalog whose point-in-time content is
  correct-by-design; ``stale`` is a category error, and rewriting it to chase a rename
  *falsifies the record*, so it is never guarded and never rewritten.

This contract pins the classification as *complete and disjoint*: every exact-path entry
of ``EXCLUDED_DOC_GLOBS`` is named in exactly one of the two tuples. A future audit
exclusion then cannot be added without declaring its class — closing the silent-drift
class where a live-state map slips into the exclusion set with no mechanical catch.
``docs/external/*.md`` is a third class (externally pinned; own freshness manifest) and is
a glob, deliberately outside this exact-path partition.
"""
from __future__ import annotations

from pathlib import Path

from espalier.claim_extractor import (
    AUDITED_INTERNAL_DOCS,
    DEFAULT_DOC_GLOBS,
    EXCLUDED_DOC_GLOBS,
    FROZEN_RECORD_DOCS,
    LIVE_STATE_MAPS,
    _enumerate_files,
)
from espalier.surface_contract import (
    classify_release_path,
    get_public_doc_relpaths,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestDeliberatelyAuditedInternalDocs:
    """The partition above forces a class to be DECLARED; it cannot force the
    declared class to be RIGHT. A doc that ships nowhere looks like it belongs in
    the exclusion set, and adding it there was fully green — the live procedure
    just stopped being audited, silently.

    These pin the deliberate asymmetry so the "fix the inconsistency" edit reds
    with a reason instead of passing.
    """

    def test_deliberately_audited_docs_stay_audited(self):
        """Asks the LIVE ENUMERATION, not the exclusion tuple's spelling.

        A string-set `AUDITED_INTERNAL_DOCS & EXCLUDED_DOC_GLOBS` intersection
        pins exactly one spelling of the un-audit edit. `EXCLUDED_DOC_GLOBS` is
        consumed by `repo_root.glob(ex)`, so `docs/RELEASE_*.md` — the natural
        "these two lines are one doc family" tidy-up, with `docs/external/*.md`
        already in the tuple as precedent — un-audits the checklist while a
        set-intersection stays green. Worse, collapsing both RELEASE_* rows to
        one glob ALSO drops RELEASE_DECISIONS out of the partition test below,
        which filters `*` entries out. One edit, three guards silent.

        `_enumerate_files` is the function `extract_claims` itself walks with,
        exclusions applied, so this reds on every spelling: exact path, prefix
        glob, suffix glob, extension glob, or a collapsed family glob.
        """
        enumerated = {
            str(p.relative_to(REPO_ROOT)).replace("\\", "/")
            for p in _enumerate_files(REPO_ROOT, DEFAULT_DOC_GLOBS)
        }
        assert enumerated, "test setup: the doc enumeration walked nothing"
        missing = [rel for rel in AUDITED_INTERNAL_DOCS if rel not in enumerated]
        assert not missing, (
            f"{missing} are declared AUDITED_INTERNAL_DOCS — audited on purpose "
            "despite classifying `internal` — but audit_accuracy no longer walks "
            "them, so some EXCLUDED_DOC_GLOBS entry now matches them (check for a "
            "glob, not just an exact path). These are a PROCEDURE someone "
            "executes, not a record of one; see claim_extractor."
            "AUDITED_INTERNAL_DOCS for what the membership buys. If the intent "
            "really changed, remove the AUDITED_INTERNAL_DOCS entry first and "
            "say why."
        )

    def test_deliberately_audited_docs_are_actually_internal_and_audited(self):
        audited = set(get_public_doc_relpaths())
        for rel in AUDITED_INTERNAL_DOCS:
            assert classify_release_path(rel) == "internal", (
                f"{rel} is listed as an audited INTERNAL doc but classifies "
                f"{classify_release_path(rel)!r} — the tuple is for the "
                "asymmetric case only; a public doc needs no entry here."
            )
            assert rel in audited, (
                f"{rel} is declared audited-despite-internal but is absent from "
                "_PUBLIC_DOC_RELPATHS, so nothing audits it — the declaration is "
                "the only thing keeping that membership from looking like a bug."
            )

    def test_audited_internal_docs_roster_is_pinned_against_deletion(self):
        """441-E / §18.4: every loop over AUDITED_INTERNAL_DOCS derives its
        population from the tuple, so EMPTYING it is bit-identically green.

        Driven: emptying the tuple took the full suite 8405 -> 8405 with zero
        failures and zero errors — no count moved, because a one-member `for`
        loop that runs zero times still reports one passing test.

        Which loop actually matters is NOT the one it looks like. The
        `rel not in enumerated` check above is triply redundant (the doc is
        reachable by several globs). The load-bearing assertion is
        `rel in get_public_doc_relpaths()` — that membership is what arms the
        overclaim-phrasing and forbidden-SessionStart-phrasing sweeps over
        docs/RELEASE_CHECKLIST.md. Lose the tuple entry and the checklist can
        silently acquire an overclaim.

        Exact set equality, and deliberately a LITERAL on the right: the tuple
        is the asymmetric-case register (audited despite classifying
        `internal`), so growth is a real editorial decision that should be made
        here, in the open, not absorbed silently.
        """
        assert set(AUDITED_INTERNAL_DOCS) == {"docs/RELEASE_CHECKLIST.md"}, (
            "AUDITED_INTERNAL_DOCS changed. This tuple is the register of docs "
            "audited DESPITE classifying `internal`, and every consumer loops "
            "over it — so a deletion retires its own coverage with no count "
            "moving.\n"
            f"  live   : {sorted(AUDITED_INTERNAL_DOCS)}\n"
            "  pinned : ['docs/RELEASE_CHECKLIST.md']\n"
            "If you added an entry: confirm it classifies `internal` AND is in "
            "_PUBLIC_DOC_RELPATHS (the two assertions above), then update this "
            "literal. If you removed one: say why in the commit — nothing else "
            "will notice."
        )
        assert AUDITED_INTERNAL_DOCS, (
            "AUDITED_INTERNAL_DOCS is empty; every loop over it now runs zero "
            "times and passes. This non-emptiness guard is the floor the "
            "sibling ADOPTER_RUNTIME_GENERATED already carries."
        )


class TestDocMaintenanceClasses:
    def test_every_excluded_doc_is_classified_exactly_once(self):
        exact = {g for g in EXCLUDED_DOC_GLOBS if "*" not in g}
        maps, records = set(LIVE_STATE_MAPS), set(FROZEN_RECORD_DOCS)
        assert not (maps & records), f"doc classified as both a map and a record: {maps & records}"
        assert exact == (maps | records), (
            "audit-excluded docs are not partitioned exactly once into "
            "LIVE_STATE_MAPS / FROZEN_RECORD_DOCS (symmetric difference): "
            f"{exact ^ (maps | records)}"
        )
