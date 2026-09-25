"""Pull-recall engine: IDF-ranked retrieval over the in-repo judgment corpus.

The PULL side of the recall engine -- sibling of ``_reinject.py``'s push side. Where
``_reinject`` fires when the harness detects a trigger, ``recall()`` answers when the
operator (or agent) *asks*: ``/recall <topic>`` returns up to four candidates of
accumulated project judgment, interleaved from two rankers, for the reader to pick between.

The corpus is small and in-loop (no persistent index). What it holds on a given
tree is whatever ``_iter_corpus`` yields there -- ``indexed_sources(root)`` names
the families, and the SessionStart banner prints that list rather than a prose
copy of it (this docstring used to carry one, and it drifted). Each doc is tokenized; a query is scored
by IDF-weighted term overlap; the top hit is returned -- OR the engine returns ``[]``
when the query shares no usable vocabulary with the corpus. The CLI front door is
``recall_union``, which runs TWO length normalisations (one calibrated for queries
that name a doc, one for queries that describe it) and returns both rankers' slots
interleaved -- up to four candidates at the CLI's ``top=2``, and a single one when
only one document clears the floor (a one-word query, about a third of the time);
plain ``recall`` remains the single-answer API.

WHAT THE FLOOR ACTUALLY DOES -- state this precisely, because it was overstated
for a long time and the overstatement is what made it dangerous (DEF-609). The floor
is the **half-corpus document-frequency line**: a matched term counts as topical only
if it appears in at most half the docs (``df <= N/2``). That reliably suppresses a
query sharing NO vocabulary with the corpus -- gibberish, or another project's
identifiers. It does NOT suppress ordinary off-topic English. Measured 2026-08-19 on the live
corpus: gibberish suppressed 1/1, ordinary off-topic English leaked
29/29. "recipe for banana bread" returns the write_guard Bash-string-literal edge at
score 3.42, and a restaurant review outscores every legitimate query in the test
suite's own must-answer arm.

So the honest contract is: **out-of-vocabulary queries suppress; everything else gets
a NEAREST NEIGHBOUR.** Render hits accordingly -- advisory, nearest-match, never
"the engine would have stayed silent if this were irrelevant".

AND NO FLOOR FIXES IT. Nine mechanisms were driven through the real ``recall()``
path against two 26+ query arms; every one has a negative margin (the best off-topic
query outscores the worst legitimate one): IDF coverage, whole-identifier phrase
matching, inverted ``df >= K``, score-margin/decisiveness, query-shape, doc-side title
anchoring, boolean composition of the best two, background-English surprisal, and
query-term PMI. The cause is structural: every doc is English prose about software
process, so on-topic jargon is HIGH-df/LOW-IDF while incidental everyday words are
LOW-df/HIGH-IDF -- IDF points the wrong way for SEPARATING off-topic from on-topic.

⚠ SCOPE THAT SENTENCE CAREFULLY, because an earlier draft of it did not and the
looser reading is false. It is a claim about SUPPRESSION -- deciding whether to answer
at all. It is NOT a claim about RANKING, and generalising it there would foreclose the
one improvement that is actually available: re-weighting term statistics moved
paraphrase recall from 1/16 to 6/16 as measured 2026-08-19 (see
PARAPHRASE_NORM_EXPONENT) -- that is the second normalisation ALONE at one
candidate; the SHARP_EDGES entry's 8/16 is the shipped union with each ranker
contributing two (the up-to-four-line shape /recall ships), same measurement,
same day. ⚠ Document expansion has since lifted the SHIPPED
normalisation to the same 6/16, so that differential is now zero and the second
ranker earns its place on the UNION (9/16 at top=1), not on the gap. Suppression and
ranking are different problems on the same corpus, and only the first one is proven
unfixable. The full record, including the table, is the pull-recall suppression entry in
docs/SHARP_EDGES.md; the contract is pinned by the three-tier arm set in
tests/test_recall.py (must-answer / must-rank / off-topic ratchet).

Exemplars are POINTER-recall, not body-recall: the ``Exemplar`` has no text body
(it names cross-file shapes), so a query matching an exemplar's ``trigger`` regex
surfaces its ``source`` pointer ("the canonical shape lives at ...") with a deterministic
bonus -- the exemplar exists to answer exactly that trigger.

Stdlib only; zero espalier imports. ``import _reinject`` (a tools/cc sibling, itself
zero-espalier) is the one cross-module import, guarded so the engine degrades to the
file corpus if the sibling is absent.
"""
from __future__ import annotations

import math
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path

# _hook_utils is the foundational sibling helper (every hook bare-imports it; it is in
# MANIFEST_FILES + every settings.json deploy). A bare import is the established shape
# and keeps the helper single-sourced (tests/test_hook_helper_consolidation.py forbids a
# local re-def). is_self_host_repo returns False for any adopter repo, which is what
# gates the harness-dev exemplar corpus.
from _hook_utils import (
    is_seeded_placeholder,
    is_self_host_repo,
    iter_doc_sections,
    next_fence_state,
    resolve_project_root,
)

try:  # _reinject is a tools/cc sibling (zero espalier imports); guard for robustness.
    from _reinject import EXEMPLAR_MAP
except Exception:  # noqa: BLE001 -- _reinject optional; degrade to the file corpus if absent
    EXEMPLAR_MAP = {}

_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "of", "to",
    "in", "on", "for", "with", "by", "as", "at", "is", "are", "be", "been",
    "it", "its", "this", "that", "these", "those", "from", "not", "no", "so",
    "do", "does", "can", "will", "via", "per", "vs", "you", "your", "we",
})

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower())
            if len(t) > 1 and t not in _STOPWORDS]


#: Exponent on a document's vocabulary size, dividing its presence-summed IDF.
#: ``0.0`` is no normalisation (the original behaviour); ``1.0`` divides by the
#: full vocabulary.
#:
#: CALIBRATED AGAINST THE LIVE CORPUS, not chosen by taste. The label set is
#: built from each document's OWN heading -- a fact about the corpus, never the
#: scorer's own output, because calibrating a ranker against what it already
#: returns is circular. Measured through the REAL ``recall()`` path (an earlier
#: pass re-implemented the scoring and silently omitted the tie-break, which is
#: how the regression below was nearly missed).
#:
#: REGENERATE, NEVER RETYPE:  python3 scripts/recall_eval.py --alpha-sweep
#: -- and regenerate LAST. The corpus is the tree you run in, so in a commit
#: that also edits memory/ or docs/ the sweep runs after those edits, never
#: before: measured 2026-09-09, one reworded sibling line moved four cells by
#: 0.3pp, inside the tolerance band, with nothing red.
#: The table below is that command's output, pasted, plus the hand-written
#: annotations in its last column -- the three "<-" markers AND the alpha-0 row's
#: parenthetical carrying the pre-2026-09-04 path-name-key numbers (keep all of
#: them; the generator prints only the "shipped" marker, and the parenthetical
#: is the only tracked record of the numbers the story below rests on).
#: tests/test_recall_eval.py reds when a pasted rate drifts
#: more than three points from a fresh sweep. The first version of this
#: table was typed from a one-off script on a 246-heading corpus and nothing
#: regenerated it, so every number aged silently for forty documents (DEF-679's
#: closure records the gap). Corpus 318 docs, 2026-09-21; heading arm 310
#: queries, stripped arm 269 (df > 0.15n removed, >= 2 tokens kept):
#:
#:     alpha  heading@1  stripped@1   heading@4  lost-to-a-BIGGER-doc
#:      0.00      83.9%       79.5%       98.1%      3   <- shipped for a long time (with the path-name tie-break: 60.2% / 62.2% / 94.8% / 108)
#:      0.05      84.2%       81.4%       98.1%      0   <- CHOSEN
#:      0.15      81.9%       80.3%       98.1%      0
#:      0.50      74.8%       76.2%       93.5%      0   <- the naive sqrt guess
#:      1.00      56.1%       57.6%       81.0%      0
#:
#: The last column was the bias this exponent was calibrated against -- heading
#: queries whose named document lost top-1 to a document with a LARGER
#: vocabulary -- and most of it was never a breadth bias. Under no
#: normalisation a heading query's named document matches every one of its
#: own terms, so it cannot lose strictly; it can only TIE with a document that
#: also carries all of them, and until 2026-09-04 an exact tie went to whichever
#: path sorted higher. The 108 losses the previous table recorded at alpha 0
#: (75 of 246 at first calibration) were those ties -- driven at full depth: 114
#: exact ties and one exemplar trigger bonus, no strict loss. With the focus
#: tie-break in _rank_key (fewer tokens first) the 2026-09-09 corpus read 2 and
#: the 2026-09-12 corpus read 4, all of them ties as well (driven:
#: equal scores to four places): two taken by a FAILURE_MODES coinage on the
#: canonical key, by design; two lost to a document with a LARGER vocabulary
#: but FEWER tokens -- the case the focus key reads backwards and the exponent,
#: which divides by vocabulary, reads right. The 2026-09-15 folds took the
#: column to 3, and it read 3 again on 2026-09-21; which of the four resolved
#: was not re-driven, so the two-and-two split above is the 2026-09-12
#: reading. The exponent's measured job is therefore the stripped arm and
#: those ties, held as a PROPERTY rather than re-pinned as a number:
#: tests/test_recall_eval.py's
#: test_alpha_zero_shows_the_bias_the_exponent_corrects requires, against a
#: fresh sweep, that the shipped alpha beats alpha 0 on stripped@1 and ties or
#: wins on heading@1 (2026-09-21: +1.9pp and +0.3pp; earlier readings are in
#: this block's history, not repeated here). tests/test_recall_eval.py keeps
#: the shipped regression reproducible by putting the old key back.
#:
#: Both label tiers peak at the same value. 0.05 over 0.15 is ~2pp on the
#: heading arm and ~1pp on the stripped arm (2026-09-21) -- real but small;
#: the value is taken at the measured peak rather than nudged, because "pick
#: by the measurement" is the whole point. The
#: heading@4 column is NOT flat across the range any more (it was ~96.7% at
#: every alpha on the first corpus): the tails now lose whole documents from
#: the top four, so a large exponent changes whether the right document is
#: found at all, not only which one wins. Between 0.05 and 0.15 it is flat.
#:
#: It does NOT rescue a caller that passes a whole paragraph as a query: the bias
#: scales with MATCHED-TERM COUNT, so a 100-word query needs far more correction
#: than any value that is sane for a real one. That is a contract violation on
#: the caller's side, not a ranking defect, and it needs fixing there.
LENGTH_NORM_ALPHA = 0.05

#: Second length-normalisation exponent, used ONLY by ``recall_union`` — and it
#: divides by a DIFFERENT quantity than LENGTH_NORM_ALPHA above: total token count
#: (``sum(tokens.values())``), not distinct-vocabulary size. That difference is
#: load-bearing, not incidental; the two constants are not interchangeable.
#:
#: WHY A SECOND RANKER RATHER THAN A BETTER SINGLE ONE. LENGTH_NORM_ALPHA was
#: calibrated honestly — and calibrated on 246 queries that NAME a document. A query
#: that DESCRIBES what it wants is a different retrieval task, and 0.05 is measurably
#: the wrong constant for it. Measured 2026-08-19 on a 16-query paraphrase arm
#: against the corpus of that day (the naming denominator is its 274-heading
#: arm; nothing regenerates this table), with "naming" = every doc's own title
#: returning that doc:
#:
#:     ranker                     paraphrase   naming     (top=1)
#:     vocab ** 0.05 (shipped)       6/16      233/274
#:     totlen ** 0.75                6/16      182/274   <- and breaks _MUST_RANK
#:     UNION of the two              9/16      233/274
#:
#: ⚠ RE-DERIVED after document expansion. It previously read 1/16 · 6/16 · 6/16 and
#: the argument was "one pivot is wrong for describing queries". That is no longer
#: what the numbers say: expansion lifted the SHIPPED pivot to parity with the
#: sibling, so the two rankers now tie at top=1 and the union's 9/16 comes from
#: returning BOTH winners rather than from either pivot being better. The union
#: still earns its place; the original justification for it does not. Re-ask this
#: after the next expansion round. (Naming denominators moved 282 -> 274 because the
#: label set is now the heading-derived one, not the corpus doc count.)
#:
#: So the tradeoff is an artifact of insisting on ONE ranker. The union takes the
#: paraphrase gain at zero naming cost, and cannot regress: today's winner is always
#: a member of the union by construction. This is pivoted document length
#: normalisation (Singhal, Buckley & Mitra, SIGIR 1996 — BM25's ``b`` in modern
#: terms); the repo had one pivot tuned for one query shape and no pivot for the other.
#:
#: ⚠ What this does NOT reach: roughly 3 of the 16 arm queries share ZERO content
#: words with their target. No re-weighting of term statistics can retrieve those —
#: that is the vocabulary problem (Furnas et al., CACM 1987), and its answers are
#: document expansion or model-side reranking, neither of which is implemented here.
PARAPHRASE_NORM_EXPONENT = 0.75

#: Relative band within which the canonical-coinage preference below still
#: applies. Load-bearing BECAUSE of the normalisation above, and it is a real
#: semantic change rather than the same rule restated:
#:
#: The preference was written as a pure tie-break, on the reasoning that scores
#: were frequently EXACTLY equal (unnormalised presence-summed IDF lands on the
#: same float often). Dividing by a fractional power of the vocabulary makes
#: exact equality vanish, and with it the mechanism -- measured: the live query
#: "gate tuning to HEAD" stopped returning the coinage literally named for it
#: and returned a scanner section 1.5% above it instead.
#:
#: So the premise "on equal evidence, prefer canon" now needs a tolerance to
#: survive. Honest consequence, stated rather than glossed: a canonical coinage
#: scoring up to 1% BELOW the top can now win, which the old comment explicitly
#: disclaimed. Calibrated, not guessed -- the tolerance IMPROVED the labelled
#: set of 2026-08-08 (heading@1 85.4% -> 86.2%, stripped@1 83.4% -> 84.4%), so
#: it is not buying one query at the expense of the corpus.
#: The window does NOT apply to a query that names the leader (every content
#: token of the leader's title in the query -- ``_names``): a document's own
#: title query keeps its slot whatever coinage sits inside the window. Added
#: 2026-09-12 after the catalog fold put a coinage 0.2% behind a memory note on
#: that note's own title. A principle's NAME query is covered by the same rule.
CANON_TIE_EPSILON = 0.01


def idf_weight(df: int, n: int) -> float:
    """Smoothed inverse document frequency. Module-level so the rank-not-point proof
    can monkeypatch it to a constant and watch the ranking collapse."""
    return math.log((1 + n) / (1 + df))


@dataclass(frozen=True)
class Hit:
    source: str   # a repo path, or an exemplar `source` pointer
    snippet: str  # the advisory one-liner (doc title, or exemplar id + pointer)
    score: float

    def render(self) -> str:
        return f"Recalled (advisory): {self.snippet}\n  source: {self.source}"


@dataclass
class _Doc:
    source: str
    snippet: str
    tokens: Counter           # term -> occurrence count in this doc
    trigger: str | None = None  # exemplar trigger regex source (pointer-recall), else None
    #: The source FAMILY this doc came from, as the SessionStart banner names it
    #: ("memory/", "docs/SHARP_EDGES.md sections", ...). Set at the yield
    #: site in _iter_corpus, so the list of what /recall indexes on a tree is
    #: read off the corpus that tree actually built -- never restated. Pinned
    #: non-empty for every doc by tests/test_recall.py.
    family: str = ""


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return ""


_FM_SECTION1_RE = re.compile(r"(?m)^##[ \t]+1\.\s")
_FM_NEXT_H2_RE = re.compile(r"(?m)^##[ \t]")
_FM_COINAGE_RE = re.compile(r"^###[ \t]+(\S.*)$")  # title stripped by caller

# A coinage body is a sequence of ``**Section.**`` blocks. The ``**Mental model.**``
# block is a pure cross-domain ANALOGY — a thermometer, toddlers on stairs, business
# letterhead — whose everyday words are df==1 in the corpus and so become high-IDF
# triggers that surface the coinage for OFF-TOPIC queries ("air temperature room
# thermometer"), eroding the recall suppress-floor. We drop ONLY that block
# before tokenizing. We deliberately
# KEEP ``**Industry analogs.**``: despite the name it carries real technical terms
# ("incomplete case analysis", "missing default branch") that aid retrieval — and
# dropping it measurably regressed coinage 1.12's recall.
_FM_BOLD_SECTION_RE = re.compile(r"^\*\*([A-Z][^*]*)\.\*\*")
_FM_METAPHOR_SECTIONS = frozenset({"mental model"})


def _strip_metaphor_sections(body: str) -> str:
    kept: list[str] = []
    skipping = False
    for line in body.splitlines():
        m = _FM_BOLD_SECTION_RE.match(line)
        if m:
            skipping = m.group(1).strip().lower() in _FM_METAPHOR_SECTIONS
        if not skipping:
            kept.append(line)
    return "\n".join(kept)

# Measured, NOT assumed: FAILURE_MODES § 1 substantially OVERLAPS the
# already-indexed SHARP_EDGES. A first pass indexing
# all 12 coinages surfaced only ~5/9 as top-1 — most lose to (or merely
# duplicate) a SHARP_EDGES section covering the SAME footgun, because the small
# sharded coinage docs match fewer terms than the larger twin and recall's
# tie-break sorts ``docs/FAILURE_MODES.md`` last. So we index only the coinages
# WITHOUT a twin — the genuinely-new retrievable coverage. Each skipped coinage
# is keyed to the SHARP_EDGES entry that already delivers a hit for it; a coinage
# NOT in this map is indexed by default (a new footgun is assumed new coverage).
_FM_COINAGE_TWINS = {
    "1.1": 'SHARP_EDGES "Convergence theater is a class, not a bug"',
    "1.2": 'SHARP_EDGES "Stealth contracts are five categories, not one bug"',
    "1.4": 'SHARP_EDGES "Annotate claims with canons or label them convention"',
    "1.5": 'SHARP_EDGES "Transition-Friendly Relaxation Followed by Tightening"',
    "1.8": 'SHARP_EDGES "\'Active\' Predicate That Includes a Closed State"',
    "1.9": 'SHARP_EDGES "Init Suggestions Gated on File Existence"',
    # NOTE: 1.11 (Gate credibility) is INDEXED, not skipped. Its apparent twin
    # "Release Gates That Grade Themselves Through The Same Path" is a DIFFERENT
    # footgun — shared-classifier circularity, which is only ONE of 1.11's shapes;
    # 1.11's class is subset-enumeration (gate green while pytest RED). Measured:
    # the twin is absent from top-5 for 1.11's footgun query, and 1.11 indexed
    # wins top-1 — so skipping it dropped real coverage.
    # 1.13 (Autoimmune regression) is SKIPPED: it is the densest coinage (386
    # tokens) and its everyday df=1 prose (plausible/magnitude/competent/adversary/
    # behavior/contract/survives-review) leaked it as a spurious top-1 for OFF-TOPIC
    # queries (suppress-floor erosion).
    # Its SHARP_EDGES negative-corpus twin now carries the born-weak/autoimmune
    # terms (the §1.13 Conceptual-parent fold), so born-weak queries still resolve.
    "1.13": 'SHARP_EDGES "Every scanner must also ship with a must-NOT-trip negative corpus"',
}


_CANONICAL_FOOTGUN_PREFIX = "docs/FAILURE_MODES.md ::"


def _is_canonical_footgun(source: str) -> bool:
    """True for a FAILURE_MODES § 1 coinage — the authoritative named-footgun
    catalog. Used as a TIE-BREAK edge in :func:`recall` so the canonical coinage
    wins when it ties a non-coinage doc's score."""
    return source.startswith(_CANONICAL_FOOTGUN_PREFIX)


def _load_failure_mode_coinages(text: str) -> list[tuple[str, str]]:
    """Return one ``(title, body)`` per ``### `` coinage within § 1 of
    ``FAILURE_MODES.md``.

    § 1 is bounded by its ``## 1.`` heading and the next ``## `` heading; within
    that slice each ``### `` subsection is a named footgun coinage. Sharding
    per-``###`` (NOT one § 1 blob) is load-bearing: ``recall`` scores by
    presence-summed IDF with a ``df <= n/2`` topicality floor, so a ~968-line
    blob matches nearly any query's terms and clears the suppress floor — tight
    per-coinage docs keep suppression honest. Returns ``[]`` if § 1 is absent.
    """
    m = _FM_SECTION1_RE.search(text)
    if not m:
        return []
    rest = text[m.end():]
    end = _FM_NEXT_H2_RE.search(rest)
    section1 = rest[: end.start()] if end else rest

    coinages: list[tuple[str, str]] = []
    title: str | None = None
    buf: list[str] = []
    for line in section1.splitlines():
        cm = _FM_COINAGE_RE.match(line)
        if cm:
            if title is not None:
                coinages.append((title, "\n".join(buf)))
            title, buf = cm.group(1).strip(), []
        elif title is not None:
            buf.append(line)
    if title is not None:
        coinages.append((title, "\n".join(buf)))
    return coinages


# ``indexes_failure_modes(root)`` -- True when THIS tree's recall corpus reaches
# ``docs/FAILURE_MODES.md``. Single owner for a fact two surfaces need:
# ``_load_corpus`` indexes the FAILURE_MODES coinage shards only on the
# self-host tree (measured, not assumed: un-gating them on a fresh adopter's
# thin corpus turned two correct suppressions into confident wrong hits), and
# the SessionStart banner NAMES that catalog and tells the reader how to reach
# it, so it must ASK here rather than restate the gate; a restatement is how
# the banner came to promise ``/recall`` for a doc the corpus had never
# indexed.
#
# A LATE-BOUND wrapper on purpose, not an alias: ``_load_corpus`` gates two
# sources on ``is_self_host_repo`` for two different reasons, and four tests
# force both open by patching that one name -- an alias binds at import and
# silently stops following it (driven: two recall tests went red on the alias).
# The sister-site probe's alias-call arm reads a one-line wrapper as a
# re-implementation; this is the purpose-scoped shape its opt-out marker exists
# for, and the ceiling in tests/_surface_expected.py was raised by one for it.
# Pinned to ``_load_corpus``'s real behaviour by
# tests/test_recall.py::test_indexes_failure_modes_matches_the_corpus.
# sister-site: ok purpose-scoped late-bound gate; tests patch is_self_host_repo and both corpus gates must follow
def indexes_failure_modes(root: Path) -> bool:
    """True when THIS tree's recall corpus reaches ``docs/FAILURE_MODES.md``."""
    return is_self_host_repo(root)


_PRINCIPLE_ALIAS_RE = re.compile(r"^## +(\d+)\. ", re.M)


def _load_principle_aliases(root: Path) -> dict[str, str]:
    """Map ``"1."`` -> the alias phrases for that principle, or ``{}`` if absent.

    DOCUMENT EXPANSION, and the reason it is a separate file rather than more prose
    in the principles doc: /recall is lexical, so a query that DESCRIBES a situation
    shares almost no vocabulary with the principle that answers it (the vocabulary
    problem, Furnas et al. 1987). The remedy is to give the document the words people
    search with -- but those words are machine-facing bait, and putting them in the
    doc a human reads degrades that doc to serve the tokenizer. So they live in
    ``docs/STANDING_PRINCIPLES.aliases.md`` and are folded in HERE, at load time.

    Gated on file existence exactly as the principles tier is, and for the same
    reason: an adopter who never writes a sidecar simply gets no aliases, which is a
    no-op rather than a degradation. Parsing is deliberately forgiving -- a malformed
    sidecar yields fewer aliases, never an exception, because a broken companion file
    must not take /recall down with it.
    """
    path = root / "docs" / "STANDING_PRINCIPLES.aliases.md"
    if not path.is_file():
        return {}
    out: dict[str, list[str]] = {}
    current: str | None = None
    fence: str | None = None
    for line in _read(path).splitlines():
        # A fenced block is prose ABOUT the format, not the format. Without this a
        # documented example inside ``` is parsed as real structure -- measured: a
        # fence containing "## 2." and "- fake" produced a real block 2 AND stole the
        # following genuine bullet from block 1. Silent misattribution, not attrition.
        # The grammar is the stack's one fence tracker (next_fence_state), shared
        # with the section splitter this loader's output is folded into.
        fenced = fence is not None
        fence = next_fence_state(line, fence)
        if fenced or fence is not None:
            continue
        heading = _PRINCIPLE_ALIAS_RE.match(line)
        if heading:
            current = f"{heading.group(1)}."
            out.setdefault(current, [])
        elif line.startswith("#"):
            # ANY heading depth ends a block, not just H1. The first version tested
            # `"# "` -- a branch that is DEAD in the live file (its only H1 precedes
            # every block, so `current` is already None) while the heading a
            # maintainer would actually add to an all-H2 document went unhandled.
            # Measured: appending "## Maintenance notes" + bullets folded every one
            # of them into principle 16's retrieval bag, with all guards green.
            current = None
        elif current and line.startswith("- "):
            out[current].append(line[2:].strip())
    return {k: " ".join(v) for k, v in out.items() if v}


#: ``memory/`` notes the pull ranker does NOT index, each with the reason it is
#: out. Two reasons, kept apart because they are pinned differently:
#:
#: ``record`` -- a RECORD surface (root CLAUDE.md Core Rule 13; the canon is
#:   ``espalier.claim_extractor.RECORD_SURFACES``, a forced twin here because this
#:   module cannot import ``espalier/``; tests/test_recall.py binds the record
#:   members to the canon in both directions). A log of rounds is not judgment:
#:   the convergence ledger was the first line delivered for about one pull query
#:   in five over the telemetry log's first five weeks (121 of 539 at the
#:   2026-09-12 snapshot -- a point-in-time count of an append-only log that
#:   nothing re-derives), and after the 2026-09-11 catalog fold it out-ranked
#:   STANDING_PRINCIPLES §8 on a blind held-out row it has nothing to say about.
#:   docs/FAILURE_MODES.md is ALSO a record surface on the canon and stays
#:   indexed on purpose: its §1 coinages are the named-footgun catalog the tie
#:   rule privileges, recalled by coinage title, and the record-axis reading of
#:   that file is about the point-in-time counts in its examples, not its names
#:   (the same carve-out reflect_protocol's RESIDUE_EXEMPT_SURFACES makes). The
#:   parity pin derives the record members from every canon key the loader
#:   could read and names that one exception.
#: ``aggregate`` -- a protocol note so large it wins task-shaped queries on
#:   breadth (the pack-authoring note is the largest non-record note in
#:   ``memory/`` by vocabulary). Excluded on the operator's 2026-09-12 call from
#:   the measurement, not from the record axis; the parity pin does not bind it.
#:
#: Measured 2026-09-12 on this tree, before and after (heading@1 / stripped@1 /
#: task control@4 / blind held-out): 251 of 301, 213 of 262, 2 of 29, 16 of 24
#: -> 251 of 300, 214 of 262, 3 of 29, 17 of 24. The naming arm loses exactly the
#: excluded note's own title; every other label holds. PULL-side only, by
#: construction: ``_load_corpus`` (recall, recall_union, the CLI shim, the eval
#: and its labels) applies it, ``_load_full_corpus`` (``nearest_by_title``, the
#: reflect protocol's fold-here hint) does not -- the two notes left out of
#: ranking are exactly the canon homes a pack-shaped or convergence-shaped
#: insight must still be folded into (the failure-mode review drove it: with
#: the exclusion in the shared loader, a pack paragraph's nearest note fell from
#: memory/task-packs.md to a SHARP_EDGES section). Membership is case-folded,
#: because a case-insensitive filesystem serves the excluded name under any
#: spelling and an exact skip would index ``memory/Task-Packs.md`` unseen.
PULL_EXCLUDED_MEMORY_NOTES: dict[str, str] = {
    "memory/CONVERGENCE_LEDGER.md": "record",
    "memory/task-packs.md": "aggregate",
}


def _is_pull_excluded(source: str, exclude: "Iterable[str]") -> bool:
    """Case-folded membership in the pull exclusion. A case-insensitive
    filesystem serves the excluded name under any spelling, so an exact-string
    skip would index ``memory/Task-Packs.md`` while every check keyed on the
    lower-case name stayed green (driven on APFS, 2026-09-12)."""
    folded = source.lower()
    return any(folded == k.lower() for k in exclude)


def _load_corpus(root: Path) -> list[_Doc]:
    """Load the PULL corpus: ``list(_iter_corpus(root))`` with
    ``PULL_EXCLUDED_MEMORY_NOTES`` applied. ``_iter_corpus`` is the single
    enumeration and labels each doc's family at the yield; ask
    ``indexed_sources`` what a tree holds rather than a prose list here (the one
    this docstring carried drifted, as it said it would). The push side's
    title matcher reads :func:`_load_full_corpus` instead."""
    return list(_iter_corpus(root))


def _load_full_corpus(root: Path) -> list[_Doc]:
    """Every document the loader can read, the pull exclusion NOT applied.

    ``nearest_by_title`` answers the reflect protocol's "which existing note is
    ABOUT this paragraph", the fold-here hint that keeps an insight from being
    written as a rival file, and the two notes the pull ranker leaves out are
    exactly the canon homes a pack-shaped or a convergence-shaped insight must
    be folded into. With the exclusion in the shared loader (driven 2026-09-12
    by the failure-mode review) a pack paragraph's nearest note fell from
    memory/task-packs.md at 2.8 to a SHARP_EDGES section, and a convergence
    paragraph lost memory/CONVERGENCE_LEDGER.md from its top three."""
    return list(_iter_corpus(root, exclude=()))


def indexed_sources(root: Path) -> list[str]:
    """The source families /recall indexes on THIS tree, in corpus order, as the
    banner names them -- e.g. ``["memory/", "docs/SHARP_EDGES.md sections"]``.

    Read off the corpus the tree actually builds, family by family, rather than
    restated: the SessionStart orientation line used to hand-list three sources
    while ``_iter_corpus`` indexed four on this tree (docs/STANDING_PRINCIPLES.md
    was added gated on file existence and the prose never followed -- DEF-562).
    A family appears here exactly when at least one of its docs was yielded, so
    a gate that closed on this tree (the FAILURE_MODES coinages off self-host,
    the exemplars) cannot be advertised, and a family added to the loader shows
    up the moment it yields. Walks the whole corpus (~40 ms measured on the
    self-host tree, under 4% of the SessionStart hook's own wall time); an empty
    list means the tree has no corpus at all, which is the banner's other question.
    """
    seen: list[str] = []
    for d in _iter_corpus(root):
        if d.family and d.family not in seen:
            seen.append(d.family)
    return seen


def _iter_corpus(root: Path, *, exclude: "Iterable[str] | None" = None) -> "Iterator[_Doc]":
    """Yield the corpus lazily; ``_load_corpus`` materializes it.

    A generator: ``indexed_sources`` and ``_load_corpus`` both consume it whole
    today, but a consumer that can stop early (the old yes/no banner gate did)
    should not have to pay for the rest.

    ``exclude`` is the set of ``memory/`` sources to skip; ``None`` means the
    pull ranker's ``PULL_EXCLUDED_MEMORY_NOTES`` (read at call time, so a test
    that patches the dict is honoured), ``()`` means none -- the push side's
    ``_load_full_corpus``.
    """
    if exclude is None:
        exclude = PULL_EXCLUDED_MEMORY_NOTES

    mem = root / "memory"
    if mem.is_dir():
        for p in sorted(mem.glob("*.md")):
            if p.name == "README.md":
                continue
            source = f"memory/{p.name}"
            if _is_pull_excluded(source, exclude):
                continue  # a record or an aggregate, not judgment -- see the dict
            text = _read(p)
            yield _Doc(source,
                       _first_heading(text) or p.stem,
                       Counter(_tokenize(text)),
                       family="memory/")

    se = root / "docs" / "SHARP_EDGES.md"
    if se.is_file():
        for title, body in iter_doc_sections(_read(se)):
            # `init` seeds this doc near-empty; its one section is a "write your
            # first edge here" scaffold. Indexing it makes /recall answer real
            # footgun questions with the placeholder -- a confident wrong hit,
            # worse than the honest no-match. Shares the banner's single owner
            # (_hook_utils) so the two readers of this file cannot disagree, and
            # is BODY-aware: an operator who writes their first edge under the
            # seeded heading (which literally invites exactly that) keeps it,
            # provided it adds at least SEEDED_NEW_CONTENT_FLOOR content units
            # beyond the seed's own prose, or a fenced code block.
            if is_seeded_placeholder(title, body):
                continue
            yield _Doc(f"docs/SHARP_EDGES.md :: {title}",
                       title,
                       Counter(_tokenize(f"{title} {body}")),
                       family="docs/SHARP_EDGES.md sections")

    sed = root / "docs" / "sharp-edges"
    if sed.is_dir():
        for p in sorted(sed.glob("*.md")):
            if p.name == "README.md":
                continue
            text = _read(p)
            yield _Doc(f"docs/sharp-edges/{p.name}",
                       _first_heading(text) or p.stem,
                       Counter(_tokenize(text)),
                       family="docs/sharp-edges/")

    # docs/STANDING_PRINCIPLES.md -- the document whose entire PURPOSE is to be
    # recalled, and it was not in the corpus at all: 0 of its 16 sections were
    # retrievable, so `/recall earn the red` returned a packaging edge and
    # `/recall class fix scope` returned a symlink backstop. Measured after
    # widening: 8 of 10 principle-NAME queries return the right principle,
    # 0 displacement of the pinned _MUST_RANK answers, off-topic leak count
    # unchanged.
    #
    # Gated on FILE EXISTENCE, deliberately NOT on is_self_host_repo() like the two
    # sources below. Those are gated because their content is espalier-internal
    # vocabulary or points at paths an adopter's tree lacks. This one is the
    # opposite case: an adopter who writes their own standing principles SHOULD get
    # them back from /recall, and `init` does not seed this file -- so on a tree that
    # has not authored one the check is a no-op. The gate and the intent coincide,
    # which is why it needs no repo-identity condition.
    #
    # ⚠ Scope, stated so nobody over-reads the win: this fixes COVERAGE, not
    # paraphrase. A query naming a principle now finds it; a query DESCRIBING one
    # still resolves by lexical overlap and often does not (1 of 16 on a paraphrase
    # arm when this was written; 6 of 16 on 2026-08-19, after the union and
    # document expansion). That is the separate ranking defect, not addressed here.
    sp = root / "docs" / "STANDING_PRINCIPLES.md"
    if sp.is_file():
        # Document expansion. The aliases are tokenized into the principle's bag but
        # are NOT part of `snippet`, so Hit.render() still shows the real title and a
        # reader is never quoted search bait. See _load_principle_aliases.
        aliases = _load_principle_aliases(root)
        for title, body in iter_doc_sections(_read(sp)):
            # `title` can be EMPTY: iter_doc_sections keys on the "## " prefix and
            # strips the rest, so a heading line of "## " followed by trailing
            # whitespace -- invisible in an editor and common in hand-edited
            # markdown -- yields an empty title. The
            # unguarded `[0]` raised IndexError straight out of the CLI, which has no
            # try/except: one stray space would take /recall down entirely. Same
            # shape guarded at the coinage loader below.
            parts = title.split(maxsplit=1)
            num = parts[0] if parts else ""  # "1."
            yield _Doc(f"docs/STANDING_PRINCIPLES.md :: {title}",
                       title,
                       Counter(_tokenize(f"{title} {body} {aliases.get(num, '')}")),
                       family="docs/STANDING_PRINCIPLES.md")

    # Two self-host-only sources, deliberately gated by TWO conditions rather
    # than one. They are suppressed for different reasons and a single `if`
    # hides that: the FAILURE_MODES shards are a RANKING decision (measured
    # net-negative on a thin corpus), the exemplars are a genuine repo-identity
    # question (their targets do not exist on an adopter's tree at all).
    if indexes_failure_modes(root):
        # FAILURE_MODES.md § 1 is the deepest footgun catalog and the one
        # footgun surface recall did not reach (mem/SHARP_EDGES/sharp-edges are
        # indexed; this 3573-line doc was not). Index § 1's named coinages, one
        # _Doc per `### ` shard (see _load_failure_mode_coinages for why sharding
        # is load-bearing). Self-host ONLY: the coinages are espalier-internal
        # vocabulary (espalier.canon_vocab) — an adopter's footgun catalog differs,
        # and these must not out-rank their own docs (same gate as the exemplars).
        fm = root / "docs" / "FAILURE_MODES.md"
        if fm.is_file():
            for title, body in _load_failure_mode_coinages(_read(fm)):
                parts = title.split(maxsplit=1)
                num = parts[0] if parts else ""  # "1.7"
                if num in _FM_COINAGE_TWINS:
                    continue  # already retrievable via its SHARP_EDGES twin
                tokens = _tokenize(f"{title} {_strip_metaphor_sections(body)}")
                yield _Doc(f"docs/FAILURE_MODES.md :: {title}",
                           title,
                           Counter(tokens),
                           family="docs/FAILURE_MODES.md section-1 coinages")

    # Pull-only exemplars -- POINTER-recall: tokenize id + source pointer, carry
    # the trigger so a query that matches it deterministically surfaces the
    # pointer. The Exemplar has no body, so `source` IS the answer. Gated on
    # repo IDENTITY and correctly so: an exemplar is a cross-file SHAPE pointer
    # with no artifact to test, aimed at harness-authoring paths
    # (espalier/scanners/, task-packs/, CHANGELOG.md) that an adopter's tree
    # does not have -- and it wins on a trigger bonus, so un-gating it would
    # answer an adopter's query with a confident pointer to a path they lack.
    if is_self_host_repo(root):
        for ex in EXEMPLAR_MAP.values():
            id_words = ex.id.replace("-", " ")
            yield _Doc(ex.source,
                       f"{ex.id}: {ex.source}",
                       Counter(_tokenize(f"{id_words} {ex.source}")),
                       trigger=ex.trigger,
                       family="pull-only shape pointers")


# Diagnostic-intent framing that DISQUALIFIES a pull-trigger from the authoring
# floor-exemption. An exemplar's GEN-NEW-* trigger matches "new <noun>" queries
# lexically, but a diagnostic/regression query ("why did the new scanner
# integration regress") wants the relevant DOC, not the authoring pointer.
# Rather than REQUIRE an authoring verb (which would also suppress a bare
# "new hook" authoring query — see test_pointer_recall_surfaces_gen_new_hook),
# keep the floor-exemption UNLESS the query carries explicit diagnostic framing.
# Matched against the lowercased query.
_DIAGNOSTIC_RE = re.compile(
    r"\b(why|regress|broke|broken|fail|debug|crash|wrong|stuck|hang|hung|"
    r"flaky|traceback)\w*\b"
)


def _vocab_norm(d: "_Doc") -> float:
    """Divide by distinct-vocabulary size. Calibrated on NAMING queries."""
    return len(d.tokens) ** LENGTH_NORM_ALPHA if d.tokens else 1.0


def _totlen_norm(d: "_Doc") -> float:
    """Divide by TOTAL token count. Calibrated on DESCRIBING queries."""
    return sum(d.tokens.values()) ** PARAPHRASE_NORM_EXPONENT if d.tokens else 1.0


def _names(d: "_Doc", q_terms: "set[str]") -> bool:
    """True when the query covers every content token of ``d``'s own title --
    the query NAMES this document, in the sense the naming arm of
    scripts/recall_eval.py is built on (title tokens longer than two characters,
    at least two of them). The canonical-coinage promotion in :func:`recall` is a
    tie rule for a query that names a COINAGE and finds an incidental match a hair
    ahead of it; it was never meant to take a document's own title query away
    from it, and after the 2026-09-11 catalog fold it did: ``gate parser inputs
    only output``, the title of memory/gate-the-parsers-inputs-not-only-its-output.md,
    scored 6.3759 against FAILURE_MODES §1.12's 6.3635 and lost the slot inside
    the one-percent window. A one-token title is not a name (``retired`` covers
    too much), so the guard stands down below two. A pull-only pointer's snippet
    is ``"<id>: <source sentence>"``, never a title, so no real query covers it
    and the guard never fires for that family -- harmless, a pointer leads on
    its trigger bonus, not on a tie. Measured 2026-09-12 over every own-title,
    paraphrase and task query (357): guard on and off differ in exactly the one
    cell above."""
    title = [t for t in _tokenize(d.snippet or "") if len(t) > 2]
    return len(title) >= 2 and all(t in q_terms for t in title)


def _rank_key(sd: "tuple[float, _Doc]") -> "tuple[float, bool, int, str]":
    """The sort key ``recall()`` ranks matched docs by, highest first: score,
    then canonical-footgun, then focus (fewer tokens), then source. A module
    function rather than an inline lambda so the instrument can put the OLD key
    back (score, canonical, source) and prove it still sees the regression the
    repo once shipped -- see tests/test_recall_eval.py."""
    score, d = sd
    return (score, _is_canonical_footgun(d.source), -sum(d.tokens.values()), d.source)


def recall(query: str, root: Path, *, top: int = 1,
           norm: "Callable[[_Doc], float] | None" = None,
           docs: "list[_Doc] | None" = None) -> list[Hit]:
    """Return up to ``top`` ranked hits for ``query`` over the corpus under ``root``,
    or ``[]`` when nothing clears the half-corpus topicality floor.

    ``[]`` means "no usable vocabulary overlap", NOT "not relevant" -- ordinary
    off-topic English clears this floor and gets a nearest neighbour. Callers that
    present a hit must frame it as nearest-match. See the module docstring."""
    # Sentinel, NOT a def-time default. A def-time `norm=_vocab_norm` binds the
    # function OBJECT at import, so this module's own documented monkeypatch idiom
    # (see idf_weight -- "module-level so the proof can swap it") would silently
    # affect recall_union and NOT recall, and the two would diverge by 122 of 282
    # answers. Resolving here means both paths share one binding.
    norm = norm or _vocab_norm
    q_terms = set(_tokenize(query))
    if not q_terms:
        return []
    # `docs` lets recall_union build the corpus ONCE and score twice. Without it the
    # union pays a second full rebuild: measured 38 ms -> 76 ms per call, of which
    # ~35 ms was redundant I/O and only 3 ms was the second scoring pass.
    if docs is None:
        docs = _load_corpus(root)
    if not docs:
        return []

    n = len(docs)
    df: Counter = Counter()
    for d in docs:
        df.update(d.tokens.keys())
    # Floor at 1.0 so an N=1 corpus (a brand-new adopter with one
    # memory/ note) is not structurally dead — at N=1, n/2.0 = 0.5 and every
    # term has df>=1 > 0.5, suppressing even an exact-title match. max(1.0, …)
    # is byte-identical for N>=2 (n/2 >= 1) and only lifts the N=1 case.
    half = max(1.0, n / 2.0)
    idf_max = idf_weight(0, n)  # the most a single distinctive term can weigh
    q_lower = query.lower()

    scored: list[tuple[float, _Doc]] = []
    for d in docs:
        matched = [t for t in q_terms if t in d.tokens]
        # An exemplar whose trigger matches the query is inherently on-topic, even if
        # its short pointer text shares few tokens -- it exists to answer this trigger.
        trigger_hit = bool(
            d.trigger
            and _trigger_matches(d.trigger, q_lower)
            and not _DIAGNOSTIC_RE.search(q_lower)
        )
        if not matched and not trigger_hit:
            continue
        # Binary IDF overlap (presence, not frequency) avoids the TF bias that would
        # rank "the doc that says 'hook' most often" over "the doc about new hooks".
        #
        # ...but presence-summing has a SECOND bias the line above does not address:
        # a document with a larger VOCABULARY matches more of any query's terms, so
        # the longest doc wins on breadth rather than on topic. Measured on this
        # corpus: the biggest note carried 1718 distinct tokens against a median of
        # 137, and 77 of 246 heading-derived queries returned some larger document
        # instead of the one they name. Dividing by a fractional power of the
        # vocabulary size corrects it; the exponent is calibrated, not chosen --
        # see LENGTH_NORM_ALPHA. ⚠ Scope that measurement: it was taken with a
        # path-name tie-break, and a heading query's named document carries every
        # one of its own terms, so under no normalisation it cannot lose strictly --
        # those were exact TIES on the presence sum that the path name broke
        # against it. The focus key in _rank_key resolves them; the exponent's
        # surviving, measured gain is on the stripped arm (the table's numbers).
        # ``norm`` is the length-normalisation divisor. Default is the shipped,
        # naming-calibrated one -- every existing caller and pin is byte-unchanged.
        # recall_union passes the paraphrase-calibrated sibling as a SECOND pass.
        base = sum(idf_weight(df[t], n) for t in matched) / norm(d)
        topical = any(df[t] <= half for t in matched) or trigger_hit
        if not topical:
            continue  # only ubiquitous-token overlap -> below the floor -> suppress
        score = base + (idf_max + base if trigger_hit else 0.0)
        scored.append((score, d))

    if not scored:
        return []
    # Tie-break order: score DESC -> canonical-footgun DESC -> focus (fewer
    # tokens) -> source DESC. On a score tie, prefer a canonical FAILURE_MODES
    # coinage: the named-footgun catalog is the authoritative source, so on equal
    # IDF-weighted overlap it should beat an incidental match ("gate tuning to
    # HEAD" against a scanner SHARP_EDGES section -- the coinage should win).
    # Then prefer the FOCUSED doc over the larger aggregate: an exact score tie
    # means equal matched terms and equal vocabulary (the norm is vocabulary-
    # keyed), so document length is the one thing left that says which doc is
    # ABOUT the query. Measured before this key existed: one naming query on the
    # live corpus -- the exact title of a memory note -- returned its 375-token
    # sibling instead of the 368-token note it named, because the sibling's path
    # sorted higher; every other arm (must-answer, must-rank, paraphrase,
    # off-topic, held-out, 400 fuzz queries, both norms) had no such tie. Focus
    # is post-floor and post-score, so it never outranks a higher-scoring doc.
    # Source DESC (reverse-lexicographic) stays as the final determinism key.
    scored.sort(key=_rank_key, reverse=True)
    # ...and the tie needs a TOLERANCE now, because length normalisation removed
    # the exact float equality the rule above was built on. Promote a canonical
    # coinage that sits within CANON_TIE_EPSILON of the leader. Deliberately a
    # promotion of an EXISTING entry, not a score edit: the reported score stays
    # the doc's own, so a reader is never shown a number the ranking did not use.
    # Post-floor, so the out-of-vocabulary suppression path is untouched. Never
    # over a leader the query NAMES (see _names): the window is for a coinage
    # query with an incidental match ahead of it, not for a document's own title.
    # An exact float tie still resolves through _rank_key, canonical first.
    if scored and not _is_canonical_footgun(scored[0][1].source) \
            and not _names(scored[0][1], q_terms):
        best = scored[0][0]
        for idx, (s, d) in enumerate(scored[1:], 1):
            if best - s > CANON_TIE_EPSILON * abs(best):
                break
            if _is_canonical_footgun(d.source):
                scored.insert(0, scored.pop(idx))
                break
    return [Hit(d.source, d.snippet, round(s, 4)) for s, d in scored[:top]]


def recall_union(query: str, root: Path, *, top: int = 1) -> list[Hit]:
    """Union of two rankers that disagree on purpose -- the pull path's front door.

    ``recall()`` scores with a normalisation calibrated on queries that NAME a
    document. That is measurably the wrong pivot for a query that DESCRIBES what it
    wants -- 1 of 16 on a paraphrase arm against 6 of 16 for the sibling exponent
    when this was written. But swapping the constant is not the fix either: it takes
    naming from 233/274 to 182/274 and breaks the pinned answers. The two query
    shapes are different retrieval tasks and one pivot cannot serve both.

    ⚠ That 1-vs-6 gap is GONE. Document expansion lifted the shipped pivot to 6/16,
    so the two now tie at top=1 and this function's justification rests entirely on
    property 2 below -- returning both rankers' candidates for the caller to rerank -- rather
    than on either normalisation out-ranking the other. It still wins (9/16 at
    top=1 against 6/16 for each pass alone); the REASON changed.

    So run both and return both, INTERLEAVED -- pass 1's winner, pass 2's winner, then
    the runners-up in the same alternation. Three properties earn this over picking:

    1. **It cannot regress.** ``recall()``'s winner is always element 0, so every
       answer available today is still available. The second ranker can only ADD.
    2. **The caller reranks.** Two candidates from two rankers that disagree is a
       cheap retrieve-then-rerank: the model reading them picks, which is the one
       semantic step available here (the hooks are stdlib-only -- no embeddings).
    3. **Pass 2's winner is the SECOND thing a reader sees, not the third or
       fourth.** Until 2026-09-04 the list was pass 1's slots followed by pass 2's,
       so a document the second ranker ranked first sat at element 2 or 3 -- for
       DEF-679's query, STANDING_PRINCIPLES section 2 was presented behind two
       documents that merely cite it. Measured with scripts/recall_eval.py at the
       switch: the describing arm's pass-2 rescues moved from slot 3 to slot 2;
       on the naming arms 13 of 540 answers moved from slot 2 to slot 3 and none
       were lost. Whether a reader of four candidates is helped by slot 2 over
       slot 3 is NOT measured; what is measured is that nothing was lost.

    Returns up to ``2 * top`` hits, deduplicated by source (first occurrence wins),
    in that alternating order. Callers that need the single historical answer
    should keep calling ``recall()``.
    """
    shared = _load_corpus(root)  # built ONCE, scored twice
    first = recall(query, root, top=top, norm=_vocab_norm, docs=shared)
    second = recall(query, root, top=top, norm=_totlen_norm, docs=shared)
    seen: set[str] = set()
    out: list[Hit] = []
    # Alternate the two passes slot by slot (property 3 above). The passes are
    # the same length today -- `norm` feeds only `base`, never the membership
    # tests, so the scored SET is identical in both (the displacement sweep in
    # tests/test_recall.py rests on exactly that). zip_longest rather than zip is
    # belt-and-braces: a future per-pass floor must not let the shorter pass
    # truncate the other, and the `None` guard below is what makes that safe.
    for pair in zip_longest(first, second):
        for hit in pair:
            if hit is None or hit.source in seen:
                continue
            seen.add(hit.source)
            out.append(hit)
    # ⚠ SCORES ACROSS THE TWO PASSES ARE INCOMMENSURABLE and must never be sorted,
    # thresholded or compared. The divisors differ by orders of magnitude: measured
    # pass-1/pass-2 ratios of 13x, 19x and 96x on the same query. The returned list
    # is NOT monotonically descending -- pass 2's winner sits at element 1 carrying
    # a score on the other scale -- and must stay that way; the interleave IS the
    # point. A future minimum-score cutoff would
    # delete every pass-2 hit before touching a single pass-1 hit -- i.e. it would
    # silently remove 100% of the paraphrase gain while looking like a suppression fix.
    return out


def nearest_by_title(text: str, root: Path, *, top: int = 3) -> list[Hit]:
    """Rank corpus documents by how well their TITLE matches ``text``.

    A different question from :func:`recall`, for a different caller. ``recall``
    answers "what does the corpus say about this SHORT topic" and scores against
    document BODIES. This answers "which existing note is ABOUT the same thing as
    this paragraph", which is what a nearest-note hint means -- and a title is
    exactly where a note declares its subject.

    Why not just call ``recall`` with the paragraph: presence-summed IDF rewards a
    document for every query term it contains, so a long query makes the largest
    document win on breadth. Measured on this corpus, five consecutive reasoning
    entries -- on slicing, on guard design, on calibration, on a pin defect -- all
    returned the same 1718-token ledger. Titles are short and near-uniform in
    length, so that failure cannot arise here; the ``sqrt`` divisor below only
    keeps a wordy title from edging out a terse one.

    Advisory and unthresholded ON PURPOSE. A freshly-written insight often has no
    near neighbour, and inventing a cutoff to say so would be a tuned constant
    with nothing behind it. The caller shows several ranked candidates with their
    scores and lets a reader judge; a strong match separates itself (measured: a
    correct hit scored 4.38 against 2.07 for the runner-up, where the weak cases
    all clustered near 1.5).

    Reads the FULL corpus, not the pull ranker's: the notes ``recall`` leaves
    out (a record and an aggregate) are fold targets here -- see
    :func:`_load_full_corpus`.
    """
    docs = _load_full_corpus(root)
    if not docs:
        return []
    n = len(docs)
    df: Counter = Counter()
    for d in docs:
        df.update(d.tokens.keys())
    q = set(_tokenize(text))
    scored: list[tuple[float, _Doc]] = []
    for d in docs:
        title_terms = set(_tokenize(d.snippet or ""))
        if not title_terms:
            continue
        matched = q & title_terms
        if not matched:
            continue
        base = sum(idf_weight(df.get(t, 0), n) for t in matched)
        scored.append((base / math.sqrt(len(title_terms)), d))
    # Source-only tie key, deliberately NOT _rank_key's focus leg: titles are
    # near-uniform in length so ties are common here (measured 2026-09-04: 52
    # exact ties, 47 with the larger doc first, over 817 queries at top=3) and
    # the push-side consumer (reflect_protocol) reads the whole top-3, so order
    # within it is not the answer. DEF-532's row carries the measurement.
    scored.sort(key=lambda sd: (sd[0], sd[1].source), reverse=True)
    return [Hit(d.source, d.snippet, round(s, 4)) for s, d in scored[:top]]


def _trigger_matches(pattern: str, text: str) -> bool:
    try:
        return re.search(pattern, text) is not None
    except re.error:  # pragma: no cover - triggers are validated by test_exemplar_parity
        return False


if __name__ == "__main__":  # CLI shim driving the /recall command
    # UTF-8 on both streams, whatever the console code page: on Windows a
    # redirected stream defaults to the ANSI page, a non-ASCII character in
    # the CONTENT this prints (a plan's text, a recall title, a memory row)
    # goes out as cp1252, and a parent decoding UTF-8 loses the whole stream
    # (CPython's Windows communicate() answers None for a reader thread that
    # died; Portability, 2026-09-24). Content is the operator's and may be
    # anything; the messages around it stay 7-bit ASCII by rule.
    import sys as _sys
    for _stream in (_sys.stdout, _sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    _query = " ".join(sys.argv[1:])
    # Resolve the corpus root via the helper that honors
    # CLAUDE_PROJECT_DIR (the idiom task_router/context_reinject_failure use),
    # not Path.cwd() — /recall must read the project corpus, not wherever the
    # shell happens to be. Falls back to cwd when the env var is unset.
    _root = resolve_project_root()
    # The union, not recall(): the CLI is the path a model reads, and two
    # candidates from two rankers that disagree is the one rerank step available
    # here. recall() stays the single-answer API for programmatic callers.
    # top=2. ⚠ A TRADE, not dominance -- and the revision of this comment that first
    # corrected the budget claim pruned the table down to the paraphrase column, which
    # is the one axis the corrected comparison still wins. Both axes, at a budget
    # matched on DELIVERED CANDIDATES:
    #   ranker               cands/q  paraphrase  naming(any)  naming(elem 0)
    #   recall(top=4) CTRL     4.00      8/16       269/274       233/274
    #   recall_union(top=2)    3.56     10/16       262/274       233/274   <- this
    # +2 paraphrase for -7 naming(any), element 0 unchanged. Taken deliberately:
    # naming is 95.6% and paraphrase 62.5%, so the failing axis is still the one the
    # union buys. ⚠ The margin was +4 before document expansion landed; aliases lift
    # the SINGLE ranker too, so expansion partly substitutes for the second pass.
    # Re-ask whether pass 2 earns its place after the next expansion round. And at
    # the SAME k the second
    # normalisation costs nothing at all -- union(k) naming(any) is IDENTICAL to
    # recall(k)'s (233/262/265 at k=1,2,3), because pass 1 IS recall() and pass 2
    # only adds members (interleaved since 2026-09-04; it never displaces one).
    # ⚠ `top` is a PER-RANKER slot count, NOT the budget: recall_union scores under
    # both normalisations and returns up to 2k hits. Two drafts of that comparison
    # were void for missing this -- the first scored a two-candidate union against a
    # one-candidate control; the second gave both arms top=2 and still delivered 3.69
    # against 2.00 while asserting matched-ness in its own test name. The full table
    # is RECORDED in tests/test_recall.py (_PARAPHRASE_UNION_HITS and its
    # neighbours) and deliberately NOT duplicated here -- a second copy is a second
    # thing to stale. "Recorded", not "pinned": since 2026-08-20 those magnitudes are
    # asserted within +/-1 of the recorded value rather than exactly, because a single
    # added corpus document moves one of them by one hit and 7.0% of the corpus does
    # so (leave-one-out census, 18 of 258 documents; the memory/ tier alone is
    # 13.8%). One pin is deliberately NOT banded -- the blind held-out arm, whose own
    # drift rate is 0.78% and which a band would stop protecting. The relations --
    # the flat step between the third and fourth slots, and the union's margin over
    # the control -- remain exact, since a corpus shift moves both sides and
    # cancels. ⚠ That cancelling argument is NOT general: the sixth slot moves
    # independently of the third and fourth (six documents in the census do it), so
    # the tail beyond the fourth slot is bounded relationally rather than pinned.
    # docs/FAILURE_MODES.md §5.15 carries the class.
    _hits = recall_union(_query, _root, top=2)
    for _hit in _hits:
        print(_hit.render())
    # No match -> print nothing (suppress); /recall renders the empty result as
    # "nothing recalled", never a hallucinated snippet.
    # Pull-side usage telemetry, recorded HERE (the operator path) and not inside
    # recall(): reflect_protocol.py:462 calls the sibling nearest_by_title() on the
    # /handoff candidate pass, and that automated caller must not inflate the "how often
    # does someone run /recall" count. `matched` is the field that earns this --
    # /recall returns [] for an out-of-vocabulary query, so the miss rate says
    # whether the corpus answers the topics actually asked of it. It does NOT
    # measure off-topic rejection (the engine leaks 29/29 there -- see the module
    # docstring). Best-effort: a telemetry failure
    # must never change what the operator sees printed above.
    try:
        from _hook_utils import (
            RECALL_LOG_NAME,
            STATE_DIR,
            _append_jsonl,
            _telemetry_enabled,
        )
        if _telemetry_enabled(_root):
            _append_jsonl(_root / STATE_DIR, RECALL_LOG_NAME, {
                "side": "pull",
                # `via` makes the SCOPE of this count self-describing in the data
                # itself, not only in this comment: reflect_protocol's candidate
                # pass calls recall() directly and is deliberately absent here, so
                # a future reader with a jq one-liner can see what was counted
                # rather than having to find the caveat.
                "via": "cli",
                "query": _query,
                "matched": bool(_hits),
                "source": _hits[0].source if _hits else None,
            })
    except Exception:  # noqa: BLE001, S110 -- telemetry never breaks the CLI
        pass
