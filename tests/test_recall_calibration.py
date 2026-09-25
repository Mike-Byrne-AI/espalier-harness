"""Retrieval QUALITY for the pull-recall engine, measured against the live corpus.

Every other recall test asks whether a specific query returns a specific document.
This one asks whether the ranker is any *good* — and it exists because the answer
was, for a long time, "worse than you would guess, and nobody had checked".

Presence-summed IDF rewards a document for every query term it happens to
contain, and a bigger vocabulary contains more of anything. Nothing normalised
for document length, so the largest note in the corpus (1718 distinct tokens
against a median of ~137) beat the note a query literally named. Measured before
the fix: **75 of 246** heading-derived queries returned some larger document, and
top-1 accuracy was **66.7%**. After: **0** and **~86%**.

That was invisible for two reasons worth keeping in mind here:

* the engine's own comment addressed TERM-FREQUENCY bias ("presence, not
  frequency"), which is a different bias, so the line looked considered; and
* every existing ranking test used a synthetic ``tmp_path`` corpus of three or
  four tiny documents, where no document is meaningfully larger than another —
  a corpus shaped so the defect could not appear.

GROUND TRUTH IS NOT SCORER-DERIVED. Each label is built from a document's OWN
heading: a fact about the corpus, never the ranker's output. Calibrating a ranker
against what it already returns is circular, and would make this file agree with
any ranking it was handed.

The assertions are a FLOOR and an INVARIANT, not the measured numbers. The corpus
grows; pinning 86.2% would fail on an unrelated note landing next week, and a
guard that cries wolf gets deleted. What must not come back is the *bias*.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _recall  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Top-1 accuracy the ranker must clear on heading-derived queries. Deliberately
#: slack: measured 86.2% at calibration, and 66.7% before it, so this sits well
#: below the achieved value and well above the regression. It is a tripwire for
#: "ranking got materially worse", not a record of the current score.
MIN_TOP1_ACCURACY = 0.75


@pytest.fixture(scope="module")
def corpus():
    """The live corpus, loaded ONCE.

    ``recall()`` reloads the corpus on every call (~32 ms), which over a few
    hundred labels is ~14 s of re-reading the same files. Caching the load and
    leaving everything else alone keeps this at ~1 s while still exercising the
    REAL ranking path -- which matters more than the speed: an earlier version of
    this measurement re-implemented the scoring, silently omitted the canonical
    tie-break, and reported a regression that did not exist in production.
    """
    return _recall._load_corpus(REPO_ROOT)


@pytest.fixture(scope="module")
def labels(corpus):
    """``[(query, expected_source)]`` derived from each document's own heading.

    A retrieval engine that cannot find a document by its own name is broken at
    the floor, so this is a floor test rather than a hard one. Documents whose
    "title" is an exemplar trigger rather than a heading are skipped: they answer
    a regex, not a topic.
    """
    out: list[tuple[str, str]] = []
    for d in corpus:
        title = d.snippet or ""
        if len(title) < 8:
            continue
        toks = [t for t in _recall._tokenize(title) if len(t) > 2]
        if len(toks) < 3:
            continue
        out.append((" ".join(toks), d.source))
    return out


@pytest.fixture
def scored(monkeypatch, corpus):
    """Run the real ``recall()`` without paying the corpus load each call."""
    monkeypatch.setattr(_recall, "_load_corpus", lambda root: corpus)

    def run(query: str):
        hits = _recall.recall(query, REPO_ROOT, top=1)
        return hits[0].source if hits else None
    return run


def _vocab(corpus) -> dict[str, int]:
    return {d.source: len(d.tokens) for d in corpus}


class TestRetrievalQuality:
    def test_the_label_set_is_not_empty(self, labels, corpus):
        """Non-vacuity. Every assertion below iterates the label set, so an empty
        one would make this whole file pass while measuring nothing -- which is
        the failure mode the engine's own suppress-on-no-match guard exists to
        prevent, reproduced in its test suite."""
        assert len(labels) > 100, (
            f"only {len(labels)} labels derived from {len(corpus)} docs -- the "
            "heading extractor is broken, and these tests are now vacuous"
        )

    def test_no_expected_doc_loses_to_a_larger_one(self, labels, scored, corpus):
        """THE INVARIANT, and the sharpest statement of the bias.

        A query built from a document's own heading may legitimately lose to a
        near-synonym. It must not lose to a document that merely contains MORE
        WORDS. Binary, and stable as the corpus grows -- unlike an accuracy
        percentage. Measured at 75 before the fix.
        """
        vocab = _vocab(corpus)
        lost = []
        for query, expected in labels:
            got = scored(query)
            if got is None or got == expected:
                continue
            if vocab.get(got, 0) > vocab.get(expected, 0):
                lost.append(
                    f"{query[:38]!r} -> {got} ({vocab.get(got)} tokens) "
                    f"instead of {expected} ({vocab.get(expected)})"
                )
        assert not lost, (
            f"{len(lost)} queries lost to a LARGER document -- the ranker is "
            "weighting vocabulary size again; check LENGTH_NORM_ALPHA.\n  "
            + "\n  ".join(lost[:5])
        )

    def test_top1_accuracy_clears_the_floor(self, labels, scored):
        """The coarse quality tripwire. Reports the actual figure on failure so a
        drop is diagnosable without re-deriving the harness."""
        hits = sum(scored(q) == expected for q, expected in labels)
        accuracy = hits / len(labels)
        assert accuracy >= MIN_TOP1_ACCURACY, (
            f"top-1 accuracy {accuracy:.1%} ({hits}/{len(labels)}) fell below "
            f"{MIN_TOP1_ACCURACY:.0%}; it measured 86.2% at calibration and "
            "66.7% before length normalisation landed"
        )


class TestTheGuardWouldCatchTheRegression:
    """Earn-the-red. A quality floor that has only ever passed proves nothing --
    and this one guards a defect that shipped undetected for a long time, so it
    is worth showing the guard actually bites.

    The defect that shipped was a PAIR, learned 2026-09-04 when half of it was
    fixed: under no normalisation a heading query's named document matches all
    of its own terms and cannot lose strictly -- it can only TIE with a document
    that also carries them all -- and the sort key of the day broke those ties by
    source path. The size-driven losses this test counts were those ties (114 of
    115 misses, driven at full depth). With the focus tie-break in `_rank_key`,
    alpha 0 alone reads 83.2% on this arm (2026-09-09; 84.8% on the 2026-09-04
    corpus) and 2 such losses, so the mutation that
    reproduces what shipped puts BOTH halves back. tests/test_recall_eval.py
    carries the same pair and the contrast (focus key alone clears the floor).
    """

    def test_disabling_normalisation_breaks_both_assertions(
        self, labels, corpus, monkeypatch
    ):
        monkeypatch.setattr(_recall, "_load_corpus", lambda root: corpus)
        monkeypatch.setattr(_recall, "LENGTH_NORM_ALPHA", 0.0)  # the old behaviour ...
        monkeypatch.setattr(                                     # ... and the old key
            _recall, "_rank_key",
            lambda sd: (sd[0], _recall._is_canonical_footgun(sd[1].source), sd[1].source),
        )
        vocab = _vocab(corpus)

        hits = lost = 0
        for query, expected in labels:
            got = _recall.recall(query, REPO_ROOT, top=1)
            src = got[0].source if got else None
            if src == expected:
                hits += 1
            elif src and vocab.get(src, 0) > vocab.get(expected, 0):
                lost += 1

        assert lost > 20, (
            f"only {lost} size-driven losses with normalisation OFF -- the "
            "invariant test above would pass either way, so it is no longer "
            "proving anything. Re-check the premise before relaxing it."
        )
        assert hits / len(labels) < MIN_TOP1_ACCURACY, (
            f"accuracy {hits/len(labels):.1%} still clears the floor with "
            "normalisation OFF -- the floor no longer discriminates"
        )


class TestLabelsAreNotScorerDerived:
    """The methodological guard: this file must never start agreeing with
    whatever ranking it is handed."""

    def test_labels_come_from_headings_not_from_recall(self, labels, corpus):
        """Each expected source must be a document whose HEADING produced the
        query -- verifiable without running the ranker at all."""
        by_source = {d.source: (d.snippet or "") for d in corpus}
        for query, expected in labels[:50]:
            heading_terms = set(_recall._tokenize(by_source[expected]))
            assert set(query.split()) <= heading_terms, (
                f"label {query!r} is not derivable from {expected}'s heading -- "
                "if labels stop coming from the corpus itself, this file is "
                "calibrating the ranker against its own output"
            )

    def test_no_label_was_taken_from_a_ranking_call(self):
        """Structural: the label fixture must not reference recall/scoring."""
        src = Path(__file__).read_text(encoding="utf-8")
        body = src.split("def labels(", 1)[1].split("@pytest.fixture", 1)[0]
        assert not re.search(r"\brecall\(|\bscored\b", body), (
            "the labels fixture now consults the ranker; ground truth must come "
            "from the corpus, never from what the ranker returns"
        )
