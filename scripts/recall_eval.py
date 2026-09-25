#!/usr/bin/env python3
"""Measure the pull-recall engine on the path that ships, and print the numbers.

`tools/cc/hooks/_recall.py` carries two calibration tables in its comments
(LENGTH_NORM_ALPHA, CANON_TIE_EPSILON) and `tests/test_recall*.py` carries the
floors and bands those tables justified. Neither prints a number on green: the
tests assert a 0.75 floor and +/-1 bands, and the comment tables were measured
once, on a corpus that has since grown by forty documents, with a "stripped"
query arm whose rule was never committed -- only its results were. So on the
day a ranking change is proposed (DEF-679), "evaluate it on the existing
labelled set" names a harness that half exists.

This script is that harness. It is a REPORTER, not a gate: it exits 0 whatever
the numbers say (1 only when there is no corpus to measure), and
`tests/test_recall_eval.py` is where anything is asserted. Run it before and
after a ranker change, diff the `--json`, and read which queries moved -- the
per-arm miss lists are in the JSON for exactly that, and the JSON keys are
stable across CONTROL_TOP / STRIP_FRACTION changes so the diff stays readable.

WHAT IT MEASURES, AND ON WHICH PATH
-----------------------------------
Two rankers, both measured, because they answer different callers:

  control     `recall(query, top=k)`        -- the single-answer API. Nothing in
                                               production calls it; every recall
                                               test pins against it.
  front door  `recall_union(query, top=2)`  -- what `/recall` actually runs
                                               (the CLI shim in _recall.py).
                                               Up to 4 candidates: the two
                                               winners, then the runners-up.

Reporting both is the point. A defect measured on the control can be absent on
the front door (DEF-679's query ranks the wanted principle 4th on the control
and 2nd-of-4 on the front door, because pass 2 ranks it first -- it was 3rd-of-4
until the passes were interleaved on 2026-09-04), and a fix judged on the
control alone can buy nothing a reader ever sees.

Per arm, per path:

  control@1     expected doc is the control's first hit
  control@k     expected doc is within the control's first CONTROL_TOP hits.
                ⚠ NOT an equal-budget number on every arm: the front door
                delivers ~2.9 candidates on the naming arms and ~3.5 on the
                paraphrase arm (the `delivered` column, printed beside it), so
                on the naming arms control@4 gives the control MORE reach than
                the front door has. Read it as the control's ceiling at k.
  union@1       expected doc is the front door's element 0. Identical to
                control@1 BY CONSTRUCTION (pass 1 is recall()); reported so
                the identity is a number you can check, not a claim
  union@any     expected doc is anywhere in the front door's delivered list
  pass2_rescues queries whose expected doc is absent from pass 1's slice
                (control[:UNION_TOP] -- pass 1 IS recall(top=UNION_TOP)) and
                present in the front door's list. Exactly what the second
                ranker buys. SET-based, never slot-based: since the interleave
                (2026-09-04) pass 2's winner sits at slot 2 when the passes
                disagree and pass 1's runner-up at slot 3; before it slot 2 was
                always pass 1's runner-up, and a slot-based count reported 33
                phantom rescues on the heading arm
  position      1-based slot of the expected doc in the delivered list, as a
                histogram. DEF-679's shape -- the wanted principle presented
                behind docs that cite it -- read across a whole arm. Slot 2 is
                pass 2's winner whenever the passes disagree; slot 3 is pass
                1's runner-up.
  named cases   full rankings on both paths. ⚠ front_door scores sit on TWO
                incommensurable scales (pass 1's are 13-96x larger), so a slot-2
                score below slot 3's is the interleave working, not a bug --
                `from_pass` on each hit says which scale it carries. Never sort
                or threshold them; recall_union's own comment says why.

THE FOUR ARMS
-------------
  heading     one query per corpus document, built from the document's OWN
              heading by the exact rule tests/test_recall_calibration.py uses
              (pinned against that fixture, not re-typed). Ground truth is a
              fact about the corpus, never the ranker's output. ⚠ Documents
              whose title has fewer than three content tokens get no query and
              are UNMEASURED here -- on 2026-09-03 that was 9 of 298, including
              three STANDING_PRINCIPLES sections (1, 6, 7).
  stripped    the heading queries with the corpus's ubiquitous tokens removed
              (document frequency above STRIP_FRACTION of the corpus), keeping
              every treated query that is still a query (MIN_STRIPPED_TOKENS).
              A degraded-naming arm: does the ranker still find a document when
              the query loses its most generic words? Reported WITH the same
              documents' heading@1 (`paired_heading_at_1`) so the comparison is
              paired -- the arm is a subset of the heading population and a
              subset-vs-whole comparison measures the selection, not the
              stripping.
  paraphrase  the 16 hand-labelled describing queries in tests/test_recall.py
              (_PARAPHRASE_ARM), read from that file by AST so there is one copy.
              Two rows are contested there; this script reports them as labelled
              and does not adjudicate.
  task        the TASK-shaped queries in tests/test_recall.py (_TASK_ARM, same
              file, same loader): the text an executor actually has when the
              "run /recall before a fix" rule fires -- a task line, a ledger
              row's claim sentence -- labelled with the FULL source of an entry
              a red team then found applicable. DEF-699's population: on
              2026-09-06 seven such queries recalled none of four applicable
              entries, and only one of the seven was persisted verbatim, so the
              arm carries that one (four labels, one per entry) plus the three
              lanes run on 2026-09-11, and grows one row per lane at handoff. A
              query with several applicable entries is several labels: the
              question is per entry. Exact-source match, like the naming arms.
              ⚠ It measures what the corpus's largest generic documents crowd
              out; do not read its rate against the naming arms' -- they ask a
              different question of the same ranker. `n` counts LABELS, not
              queries (`distinct_queries` in the report says how many), so a
              query with four labels weighs 4:1 in every non-rate aggregate;
              and a row whose query shares its entry's title tokens is marked
              TITLE-OVERLAP in _TASK_ARM, because such a row hits for a reason
              that is not the gap this arm exists to measure.

Stdlib-only. No espalier import. Existence is pinned by
tests/_surface_expected.py::EXPECTED_SCRIPT_NAMES.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
#: One owner file for BOTH hand-labelled arms (_PARAPHRASE_ARM, _TASK_ARM), so a
#: caller redirecting one cannot silently empty the other without noticing.
LABELLED_ARM_SOURCE = REPO_ROOT / "tests" / "test_recall.py"
PARAPHRASE_SOURCE = LABELLED_ARM_SOURCE  # the name the paraphrase arm's tests use

if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _recall  # noqa: E402

#: The front door's per-ranker slot count. Must track the CLI shim at the foot of
#: tools/cc/hooks/_recall.py (`recall_union(_query, _root, top=2)`) and
#: tests/test_recall.py::_PARAPHRASE_UNION_TOP -- three sites, one value, and
#: tests/test_recall_eval.py pins this one against BOTH of the others.
UNION_TOP = 2

#: The control's `top`. tests/test_recall.py::_PARAPHRASE_CONTROL_TOP settled on 4
#: for the paraphrase arm after two drafts compared a 2-candidate union against a
#: 1- then a 2-candidate control and were void both times. Pinned equal to that
#: constant by tests/test_recall_eval.py. See the control@k note above for why it
#: is NOT equal-budget on the naming arms.
CONTROL_TOP = 4

#: Minimum content tokens for a HEADING query. Not a choice made here: the rule
#: is tests/test_recall_calibration.py's labels fixture, and the test pins this
#: script's heading arm to that fixture's output, whole.
MIN_QUERY_TOKENS = 3

#: Minimum tokens a STRIPPED query must keep. 2, not MIN_QUERY_TOKENS, and the
#: difference is the whole measurement: the heading floor is applied BEFORE the
#: treatment (which documents have a usable title), so applying it again AFTER
#: stripping is a post-treatment filter on the outcome -- it discards exactly
#: the queries stripping hurt most. Measured 2026-09-21 at STRIP_FRACTION, paired
#: on the same documents (`--sweep --min-kept N` reproduces each row as the
#: 0.15 line of its sweep; tests/test_recall_eval.py reds when a row drifts):
#:
#:     min kept   arm   dropped-as-too-short   paired heading@1   stripped@1
#:        3       222           69                  85.6%           84.7%
#:        2       269           22                  84.4%           81.4%
#:        1       289            2                  84.4%           77.5%
#:
#: At 2 the arm reproduced the table in _recall.py (211 of 246 queries, 83.4%)
#: to 0.1pp on accuracy and 1% on size ratio when first measured, 2026-09-03
#: (251/289 = 0.869 vs 0.858); the size ratio has stayed within two points of
#: the original's at every re-paste since (269/310 = 0.868 on 2026-09-21) with
#: the accuracy about 2pp under it (81.4% on 2026-09-21), so it is PLAUSIBLE
#: -- fitted, not recovered -- that this was the original rule. The sub-second
#: prose test in tests/test_recall_eval.py pins both parentheticals to the
#: row above.
#: 1-token queries are kept out because the ranker's topicality floor makes a
#: one-term query answer a different question. Both discards are counted and
#: reported (`unchanged`, `too_short`) so nothing is filtered invisibly.
MIN_STRIPPED_TOKENS = 2

#: Document-frequency fraction above which a token is "ubiquitous" and stripped.
#:
#: Swept 2026-09-21 on the live 318-document corpus with MIN_STRIPPED_TOKENS=2
#: (first swept 2026-09-12 at 308 documents -- 308 again by coincidence after
#: the pull ranker stopped indexing two memory/ notes, not by standing still;
#: `--sweep` reproduces it; every cell below is that output, not a memory):
#:
#:     fraction   stripped   arm   too_short   paired heading@1   stripped@1   delta
#:       0.50        19      111        0           89.2%           87.4%      -1.8
#:       0.25       130      257        5           85.6%           82.9%      -2.7
#:       0.15       283      269       22           84.4%           81.4%      -3.0
#:       0.10       511      243       58           87.2%           81.9%      -5.3
#:       0.075      715      212       91           88.2%           82.1%      -6.1
#:       0.05      1067      159      147           91.2%           86.8%      -4.4
#:
#: Paired on the same documents, stripping is HARDER at every fraction (1.8 to
#: 6.1 points) -- the direction _recall.py's table recorded. The 2026-09-09
#: sweep had read a point EASIER at 0.5, where only 17 tokens went and the arm
#: was 95 rare-word titles; since 2026-09-12 that cell reads harder too, so the
#: one exception is gone. 0.15 is chosen because it MAXIMISES THE ARM: 269 of
#: 310 headings both contain a stripped token and survive the strip. Above it
#: fewer headings contain one (257 at 0.25); below it more are stripped under
#: two tokens (58, 91, 147 too_short) and the surviving arm drifts toward
#: rare-word-only titles, which is why paired heading@1 climbs there. Exposed
#: as `--strip-fraction` so the choice is one flag from being re-asked.
STRIP_FRACTION = 0.15

#: The sweep `--sweep` prints. Wide enough to show the plateau and both tails.
SWEEP_FRACTIONS = (0.5, 0.25, 0.15, 0.10, 0.075, 0.05)

#: The LENGTH_NORM_ALPHA values `--alpha-sweep` re-derives the ranker's own
#: calibration table over -- the same five the table in
#: tools/cc/hooks/_recall.py was first measured at, so the two stay diffable.
#: 0.0 is no normalisation (the pre-calibration behaviour); 1.0 divides by the
#: whole vocabulary.
ALPHA_SWEEP = (0.0, 0.05, 0.15, 0.5, 1.0)

#: Queries whose full ranking is printed by name. DEF-679 is the filing this
#: instrument was built to evaluate; a fix that moves this query but nothing else
#: is exactly what the arms above exist to catch.
NAMED_CASES: tuple[tuple[str, str], ...] = (
    ("DEF-679", "is the harness a security boundary"),
)

#: How many control hits a named case prints. Deep enough to show where a
#: principle sits when it loses -- DEF-679's sat 4th.
NAMED_CASE_DEPTH = 8

_PRINCIPLE_PREFIX = "docs/STANDING_PRINCIPLES.md :: "


@dataclass(frozen=True)
class Label:
    query: str
    expected: str  # exact source, or a source prefix (see Arm.prefix_match)


@dataclass(frozen=True)
class Arm:
    name: str
    labels: tuple[Label, ...]
    #: paraphrase labels name a principle by number ("2."), which resolves to a
    #: source PREFIX; heading/stripped labels name an exact source.
    prefix_match: bool = False
    #: expected source -> the same document's HEADING query, for a paired
    #: comparison. Only the stripped arm carries one.
    paired_queries: dict[str, str] | None = None
    #: what the arm's construction discarded, so a subset arm says so.
    census: dict[str, int] | None = None

    def matches(self, source: str, expected: str) -> bool:
        if self.prefix_match:
            return source.startswith(expected)
        return source == expected


# -- labels: facts about the corpus, never the ranker's output -----------------


def _heading_tokens(doc: "_recall._Doc") -> list[str]:
    """The labels-fixture rule from tests/test_recall_calibration.py. The test
    pins this function's whole output against that fixture, so a change there
    reds here rather than silently measuring a different population."""
    title = doc.snippet or ""
    if len(title) < 8:
        return []
    toks = [t for t in _recall._tokenize(title) if len(t) > 2]
    return toks if len(toks) >= MIN_QUERY_TOKENS else []


def heading_labels(corpus: list) -> tuple[Label, ...]:
    out = []
    for d in corpus:
        toks = _heading_tokens(d)
        if toks:
            out.append(Label(" ".join(toks), d.source))
    return tuple(out)


def ubiquitous_tokens(corpus: list, fraction: float) -> frozenset[str]:
    """Tokens whose document frequency exceeds ``fraction`` of the corpus."""
    df: Counter = Counter()
    for d in corpus:
        df.update(d.tokens.keys())
    threshold = len(corpus) * fraction
    return frozenset(t for t, c in df.items() if c > threshold)


def build_stripped(corpus: list, fraction: float = STRIP_FRACTION, *,
                   min_kept: int | None = None) -> Arm:
    """Heading queries minus ubiquitous tokens, as an Arm carrying its paired
    heading queries and a census of what was discarded.

    Every query here is strictly shorter than its heading twin (disjoint from
    the heading arm by construction). ``unchanged`` counts headings with no
    ubiquitous token to lose; ``too_short`` counts headings stripped below the
    floor -- MIN_STRIPPED_TOKENS unless ``min_kept`` overrides it, which only
    the ``--min-kept`` sweep does. Both are reported, never silently dropped."""
    floor = MIN_STRIPPED_TOKENS if min_kept is None else min_kept
    ubiq = ubiquitous_tokens(corpus, fraction)
    labels: list[Label] = []
    paired: dict[str, str] = {}
    unchanged = too_short = 0
    for d in corpus:
        toks = _heading_tokens(d)
        if not toks:
            continue
        kept = [t for t in toks if t not in ubiq]
        if len(kept) == len(toks):
            unchanged += 1
            continue
        if len(kept) < floor:
            too_short += 1
            continue
        labels.append(Label(" ".join(kept), d.source))
        paired[d.source] = " ".join(toks)
    return Arm("stripped", tuple(labels), paired_queries=paired,
               census={"unchanged": unchanged, "too_short": too_short})


def stripped_labels(corpus: list, fraction: float = STRIP_FRACTION) -> tuple[Label, ...]:
    return build_stripped(corpus, fraction).labels


def load_labelled_arm(name: str, source: Path = LABELLED_ARM_SOURCE) -> tuple[tuple[str, str], ...]:
    """A hand-labelled arm ``name`` (``_PARAPHRASE_ARM``, ``_TASK_ARM``) from
    tests/test_recall.py, by AST -- the test file is the single owner (its
    contested-row annotations and each arm's provenance live there), and
    executing a test module to read one constant would drag pytest and the live
    corpus load into a reporter.

    Reads a plain or annotated assignment at any nesting depth. Returns ``()``
    -- and says so on stderr, naming the arm -- if the file, the constant, or a
    literal tuple of (str, str) rows is absent: an empty arm prints `n/a` in a
    table a reader is scanning for numbers, so the emptiness must be loud
    somewhere."""
    human = name.strip("_").removesuffix("_ARM").lower()

    def _empty(reason: str) -> tuple[tuple[str, str], ...]:
        print(f"WARN: {human} arm is empty ({name}) -- {reason} ({source})", file=sys.stderr)
        return ()

    try:
        # Bytes: a non-UTF-8 source with no coding cookie is the SyntaxError
        # the handler already names, not a decode error past it (DEF-829).
        tree = ast.parse(source.read_bytes())
    except (OSError, SyntaxError) as exc:
        return _empty(f"cannot parse source: {exc.__class__.__name__}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError):
            return _empty(f"{name} is not a literal")
        rows = []
        for row in value:
            if not (isinstance(row, (tuple, list)) and len(row) == 2
                    and all(isinstance(x, str) for x in row)):
                return _empty(f"{name} row is not (str, str): {row!r}")
            rows.append((row[0], row[1]))
        return tuple(rows)
    return _empty(f"no {name} assignment found")


def load_paraphrase_arm(source: Path = PARAPHRASE_SOURCE) -> tuple[tuple[str, str], ...]:
    """``_PARAPHRASE_ARM`` -- see :func:`load_labelled_arm`."""
    return load_labelled_arm("_PARAPHRASE_ARM", source)


def paraphrase_labels(source: Path = PARAPHRASE_SOURCE) -> tuple[Label, ...]:
    return tuple(Label(q, _PRINCIPLE_PREFIX + want) for q, want in load_paraphrase_arm(source))


def task_labels(source: Path = LABELLED_ARM_SOURCE) -> tuple[Label, ...]:
    """``_TASK_ARM`` rows carry a FULL source (``docs/SHARP_EDGES.md :: <heading>``
    or ``memory/<note>.md``), not a principle number, so no prefix is added."""
    return tuple(Label(q, want) for q, want in load_labelled_arm("_TASK_ARM", source))


def build_arms(corpus: list, *, strip_fraction: float = STRIP_FRACTION,
               labelled_arm_source: Path = LABELLED_ARM_SOURCE) -> tuple[Arm, ...]:
    task = task_labels(labelled_arm_source)
    # A task label names an EXACT source -- a SHARP_EDGES heading, edited often.
    # A renamed heading would turn it into a permanent silent miss that reads as
    # a ranking regression in a --json diff, so the reporter says so where it
    # runs, not only under pytest (tests/test_recall_pasted_counts.py is the
    # gate that fires at the commit that renames).
    sources = {doc.source for doc in corpus}
    for lab in task:
        if lab.expected not in sources:
            print(
                "WARN: task arm label names a source the corpus does not have "
                f"(renamed heading?): {lab.expected!r}",
                file=sys.stderr,
            )
    return (
        Arm("heading", heading_labels(corpus)),
        build_stripped(corpus, strip_fraction),
        Arm("paraphrase", paraphrase_labels(labelled_arm_source), prefix_match=True),
        Arm("task", task),
    )


# -- scoring: the REAL ranking paths, corpus loaded once -----------------------


@contextmanager
def _cached(corpus: list):
    """Point both ranking paths at an already-loaded corpus, for the duration.

    ``recall()`` reloads from disk on every call (~32 ms), which over ~500 labels
    and two paths is a minute of re-reading the same files. Patching the loader
    -- the idiom tests/test_recall_calibration.py uses -- keeps the run at a few
    seconds while still exercising the real scoring, sort and canon promotion.

    Scoped, not permanent: this script shares the ``_recall`` module object with
    every test that imports it, and a patch left behind would make a later
    ``recall(tmp_path)`` answer from THIS repo's corpus instead of the synthetic
    one the test built.
    """
    original = _recall._load_corpus
    _recall._load_corpus = lambda root: corpus  # type: ignore[assignment]
    try:
        yield
    finally:
        _recall._load_corpus = original


def _control(query: str, root: Path, top: int) -> list[str]:
    return [h.source for h in _recall.recall(query, root, top=top)]


def _front_door(query: str, root: Path) -> list[str]:
    return [h.source for h in _recall.recall_union(query, root, top=UNION_TOP)]


def evaluate_arm(arm: Arm, root: Path) -> dict:
    n = len(arm.labels)
    control_at_1 = control_at_k = union_at_1 = union_at_any = 0
    paired_heading_at_1 = 0
    pass2_rescues = 0
    delivered_total = 0
    agree_at_1 = 0
    delivered_lines: Counter = Counter()
    positions: Counter = Counter()
    union_misses: list[dict] = []
    control_misses: list[dict] = []
    for label in arm.labels:
        control = _control(label.query, root, CONTROL_TOP)
        union = _front_door(label.query, root)
        delivered_total += len(union)
        delivered_lines[len(union)] += 1
        # The second ranker's own top-1, so the report can say how often the two
        # rankers agree -- the figure the /recall command body quotes.
        second = _recall.recall(label.query, root, top=1, norm=_recall._totlen_norm)
        agree_at_1 += bool(control) and bool(second) and control[0] == second[0].source
        c1 = bool(control) and arm.matches(control[0], label.expected)
        ck = any(arm.matches(s, label.expected) for s in control)
        in_pass1 = any(arm.matches(s, label.expected) for s in control[:UNION_TOP])
        u1 = bool(union) and arm.matches(union[0], label.expected)
        pos = next((i for i, s in enumerate(union, 1) if arm.matches(s, label.expected)), None)
        control_at_1 += c1
        control_at_k += ck
        union_at_1 += u1
        if not c1:
            control_misses.append({
                "query": label.query,
                "expected": label.expected,
                "got": control[:1],
            })
        if pos is not None:
            union_at_any += 1
            positions[pos] += 1
            if not in_pass1:
                pass2_rescues += 1
        else:
            union_misses.append({
                "query": label.query,
                "expected": label.expected,
                "got": union[:UNION_TOP * 2],
            })
        if arm.paired_queries is not None:
            twin = _control(arm.paired_queries[label.expected], root, 1)
            paired_heading_at_1 += bool(twin) and arm.matches(twin[0], label.expected)

    def rate(x: int) -> float | None:
        return round(x / n, 4) if n else None

    out = {
        "n": n,
        # Labels and queries are 1:1 on every arm but the task arm, where a
        # query with several applicable entries is several labels; every
        # non-rate aggregate below is therefore query-weighted, and this says by
        # how much.
        "distinct_queries": len({lb.query for lb in arm.labels}),
        "control_at_1": control_at_1,
        "control_at_k": control_at_k,
        "union_at_1": union_at_1,
        "union_at_any": union_at_any,
        "pass2_rescues": pass2_rescues,
        "delivered_mean": round(delivered_total / n, 2) if n else None,
        "delivered_histogram": {str(k): delivered_lines[k] for k in sorted(delivered_lines)},
        "agree_at_1": agree_at_1,
        "position_histogram": {str(k): positions[k] for k in sorted(positions)},
        "rates": {
            "control_at_1": rate(control_at_1),
            "control_at_k": rate(control_at_k),
            "union_at_1": rate(union_at_1),
            "union_at_any": rate(union_at_any),
        },
        "control_misses": control_misses,
        "union_misses": union_misses,
    }
    if arm.paired_queries is not None:
        out["paired_heading_at_1"] = paired_heading_at_1
        out["rates"]["paired_heading_at_1"] = rate(paired_heading_at_1)
    if arm.census is not None:
        out["census"] = dict(arm.census)
    return out


def named_case(case_id: str, query: str, root: Path) -> dict:
    # Which pass a front-door hit came from: pass 1 is recall() under the vocab
    # norm, and a hit carries its emitting pass's score, so an exact score match
    # against pass 1's own list identifies it (the two scales never coincide).
    pass1 = {h.source: h.score
             for h in _recall.recall(query, root, top=UNION_TOP, norm=_recall._vocab_norm)}
    return {
        "id": case_id,
        "query": query,
        "control": [
            {"rank": i, "score": h.score, "source": h.source}
            for i, h in enumerate(_recall.recall(query, root, top=NAMED_CASE_DEPTH), 1)
        ],
        "front_door": [
            {"rank": i, "score": h.score, "source": h.source,
             "from_pass": 1 if pass1.get(h.source) == h.score else 2}
            for i, h in enumerate(_recall.recall_union(query, root, top=UNION_TOP), 1)
        ],
    }


def corpus_facts(corpus: list) -> dict:
    vocab: set[str] = set()
    for d in corpus:
        vocab.update(d.tokens.keys())
    sp = [d for d in corpus if d.source.startswith(_PRINCIPLE_PREFIX)]
    return {
        "docs": len(corpus),
        "vocab": len(vocab),
        "canon_prefix": _recall._CANONICAL_FOOTGUN_PREFIX,
        "canon_docs": sum(_recall._is_canonical_footgun(d.source) for d in corpus),
        "docs_without_heading_query": [d.source for d in corpus if not _heading_tokens(d)],
        "standing_principles_sections": len(sp),
        "standing_principles_without_heading_query": [
            d.source for d in sp if not _heading_tokens(d)
        ],
    }


def ranker_constants() -> dict:
    return {
        "LENGTH_NORM_ALPHA": _recall.LENGTH_NORM_ALPHA,
        "PARAPHRASE_NORM_EXPONENT": _recall.PARAPHRASE_NORM_EXPONENT,
        "CANON_TIE_EPSILON": _recall.CANON_TIE_EPSILON,
        "UNION_TOP": UNION_TOP,
        "CONTROL_TOP": CONTROL_TOP,
        "MIN_STRIPPED_TOKENS": MIN_STRIPPED_TOKENS,
        "STRIP_FRACTION": STRIP_FRACTION,
    }


def evaluate(root: Path, *, corpus: list | None = None,
             strip_fraction: float = STRIP_FRACTION,
             extra_queries: tuple[str, ...] = ()) -> dict:
    """The whole report as one JSON-serialisable dict. ``corpus`` lets a caller
    (the tests) load once and evaluate several times; ``strip_fraction`` lets the
    sweep re-derive the stripped arm without rebuilding the others."""
    if corpus is None:
        corpus = _recall._load_corpus(root)
    arms = build_arms(corpus, strip_fraction=strip_fraction)
    cases = list(NAMED_CASES) + [("query", q) for q in extra_queries]
    with _cached(corpus):
        return {
            "corpus": corpus_facts(corpus),
            "constants": {**ranker_constants(), "STRIP_FRACTION": strip_fraction},
            "arms": {arm.name: evaluate_arm(arm, root) for arm in arms},
            "named_cases": [named_case(cid, q, root) for cid, q in cases],
        }


def empty_arms(report: dict) -> list[str]:
    """Arm names with n == 0. An empty arm prints `n/a` and measures nothing;
    the caller says so on stderr rather than letting the table look complete."""
    return [name for name, arm in report["arms"].items() if not arm["n"]]


def sweep(root: Path, corpus: list, fractions=SWEEP_FRACTIONS, *,
          min_kept: int | None = None) -> list[dict]:
    rows = []
    with _cached(corpus):
        for f in fractions:
            arm = build_stripped(corpus, f, min_kept=min_kept)
            r = evaluate_arm(arm, root)
            rows.append({
                "fraction": f,
                "tokens_stripped": len(ubiquitous_tokens(corpus, f)),
                "n": r["n"],
                "too_short": r["census"]["too_short"],
                "paired_heading_at_1": r["rates"]["paired_heading_at_1"],
                "control_at_1": r["rates"]["control_at_1"],
                "union_at_any": r["rates"]["union_at_any"],
            })
    return rows


def alpha_sweep(root: Path, corpus: list, alphas=ALPHA_SWEEP, *,
                strip_fraction: float = STRIP_FRACTION) -> list[dict]:
    """Re-derive the LENGTH_NORM_ALPHA table that justifies the shipped value.

    ``tools/cc/hooks/_recall.py`` carries that table as a comment. It was typed
    from a one-off script on a 246-heading corpus and nothing regenerated it, so
    every number in it aged silently as the corpus grew (DEF-679's closure
    recorded the gap). This is the regeneration: per alpha, the heading and
    stripped arms on the control path, plus the column the original table was
    built to show -- how many heading misses lost to a document with a LARGER
    vocabulary, the bias the exponent exists to correct.

    The constant is patched on the live module for the duration and restored
    on every exit path, because the module object is shared with the whole
    test session (see ``_cached``).
    """
    heading = Arm("heading", heading_labels(corpus))
    stripped = build_stripped(corpus, strip_fraction)
    by_source = {d.source: d for d in corpus}
    original = _recall.LENGTH_NORM_ALPHA
    # The shipped value is always a row: a recalibration off the grid must not
    # make its own justification table silent about the value it justifies.
    alphas = tuple(sorted({*alphas, original}))
    rows = []
    try:
        with _cached(corpus):
            for alpha in alphas:
                _recall.LENGTH_NORM_ALPHA = alpha
                h = evaluate_arm(heading, root)
                st = evaluate_arm(stripped, root)
                lost_to_bigger = sum(
                    1 for m in h["control_misses"]
                    if m["got"] and m["got"][0] in by_source
                    and len(by_source[m["got"][0]].tokens) > len(by_source[m["expected"]].tokens)
                )
                rows.append({
                    "alpha": alpha,
                    "n_heading": h["n"],
                    "n_stripped": st["n"],
                    "heading_at_1": h["rates"]["control_at_1"],
                    "heading_at_k": h["rates"]["control_at_k"],
                    "stripped_at_1": st["rates"]["control_at_1"],
                    "lost_to_bigger_doc": lost_to_bigger,
                })
    finally:
        _recall.LENGTH_NORM_ALPHA = original
    return rows


# -- rendering -----------------------------------------------------------------


def _pct(x: float | None) -> str:
    return "   n/a" if x is None else f"{x:6.1%}"


def render_text(report: dict, *, show_misses: bool = False) -> str:
    c = report["corpus"]
    k = report["constants"]
    top = k["CONTROL_TOP"]
    lines = [
        f"recall_eval -- corpus {c['docs']} docs, {c['vocab']} vocab, "
        f"canon set {c['canon_docs']} ({c['canon_prefix']!r}), "
        f"{c['standing_principles_sections']} STANDING_PRINCIPLES sections "
        f"({len(c['standing_principles_without_heading_query'])} without a heading query)",
        "constants: " + " ".join(f"{name}={val}" for name, val in k.items()),
        "",
        f"{'arm':<11}{'n':>5}  {'control@1':>9}  {'control@' + str(top):>9}  "
        f"{'union@any':>9}  {'pass2':>5}  {'delivered':>9}  position histogram",
    ]
    for name, a in report["arms"].items():
        r = a["rates"]
        hist = " ".join(f"{slot}:{n}" for slot, n in a["position_histogram"].items()) or "-"
        lines.append(
            f"{name:<11}{a['n']:>5}  {_pct(r['control_at_1']):>9}  "
            f"{_pct(r['control_at_k']):>9}  {_pct(r['union_at_any']):>9}  "
            f"{a['pass2_rescues']:>5}  {str(a['delivered_mean']):>9}  {hist}"
        )
        if name == "heading":
            dl = " / ".join(f"{k}:{v}" for k, v in a["delivered_histogram"].items()) or "-"
            lines.append(
                f"{'':<11}{'':>5}  rankers agree at top-1 on {a['agree_at_1']} of {a['n']}; "
                f"lines delivered {dl}  (the /recall command body quotes these)"
            )
        if name == "task":
            lines.append(
                f"{'':<11}{'':>5}  n counts labels over {a['distinct_queries']} distinct "
                "queries (a query with several applicable entries is several labels); "
                "a different question from the naming arms -- do not read this rate "
                "against theirs; a row marked TITLE-OVERLAP in _TASK_ARM hits because "
                "its query names the entry, not because the gap closed"
            )
        if "paired_heading_at_1" in r:
            cen = a.get("census", {})
            lines.append(
                f"{'':<11}{'':>5}  paired heading@1 on the same {a['n']} docs: "
                f"{_pct(r['paired_heading_at_1']).strip()}  "
                f"(unchanged {cen.get('unchanged', 0)}, too_short {cen.get('too_short', 0)} "
                f"excluded from the arm)"
            )
    lines.append("")
    lines.append("union@1 == control@1 on every arm by construction (pass 1 IS recall()); "
                 "the JSON carries both so the identity is checkable.")
    if c["standing_principles_without_heading_query"]:
        lines.append("unmeasured by the naming arms (title under 3 content tokens): "
                     + "; ".join(c["standing_principles_without_heading_query"]))
    for case in report["named_cases"]:
        lines.append("")
        lines.append(f"named case {case['id']}: {case['query']!r}")
        lines.append(f"  control (recall top={NAMED_CASE_DEPTH}):")
        for h in case["control"]:
            lines.append(f"    {h['rank']}. {h['score']:<7} {h['source']}")
        lines.append(f"  front door (recall_union top={k['UNION_TOP']}):")
        for h in case["front_door"]:
            lines.append(f"    {h['rank']}. {h['score']:<7} [pass {h['from_pass']}] {h['source']}")
    if show_misses:
        for name, a in report["arms"].items():
            lines.append("")
            lines.append(f"{name}: {len(a['union_misses'])} front-door misses")
            for m in a["union_misses"]:
                got = m["got"][0] if m["got"] else "(nothing)"
                lines.append(f"  {m['query'][:48]!r:<52} -> {got}")
                lines.append(f"  {'':<52}    wanted {m['expected']}")
    return "\n".join(lines)


def render_sweep(rows: list[dict]) -> str:
    lines = [f"{'fraction':>9}  {'stripped':>8}  {'arm':>5}  {'too_short':>9}  "
             f"{'paired h@1':>10}  {'stripped@1':>10}  {'delta':>6}  {'union@any':>9}"]
    for r in rows:
        if r["n"]:
            delta = f"{r['control_at_1'] - r['paired_heading_at_1']:>+6.1%}"
        else:
            delta = "   n/a"
        lines.append(
            f"{r['fraction']:>9}  {r['tokens_stripped']:>8}  {r['n']:>5}  {r['too_short']:>9}  "
            f"{_pct(r['paired_heading_at_1']):>10}  {_pct(r['control_at_1']):>10}  "
            f"{delta}  {_pct(r['union_at_any']):>9}"
        )
    return "\n".join(lines)


def render_alpha_sweep(rows: list[dict]) -> str:
    n_h = rows[0]["n_heading"] if rows else 0
    n_s = rows[0]["n_stripped"] if rows else 0
    lines = [
        f"LENGTH_NORM_ALPHA sweep -- heading arm {n_h} queries, stripped arm {n_s}; "
        f"control path (recall()), shipped {_recall.LENGTH_NORM_ALPHA}",
        f"{'alpha':>6}  {'heading@1':>9}  {'stripped@1':>10}  "
        f"{'heading@' + str(CONTROL_TOP):>10}  lost-to-a-BIGGER-doc",
    ]
    for r in rows:
        mark = "  <- shipped" if r["alpha"] == _recall.LENGTH_NORM_ALPHA else ""
        lines.append(
            f"{r['alpha']:>6.2f}  {_pct(r['heading_at_1']):>9}  {_pct(r['stripped_at_1']):>10}  "
            f"{_pct(r['heading_at_k']):>10}  {r['lost_to_bigger_doc']:>5}{mark}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--json", action="store_true", help="emit the full report as JSON")
    parser.add_argument("--misses", action="store_true",
                        help="text mode: list every front-door miss per arm")
    parser.add_argument("--sweep", action="store_true",
                        help="print the STRIP_FRACTION sweep instead of the report "
                             "(--strip-fraction adds a row, --min-kept moves the floor; "
                             "--query/--misses are refused)")
    parser.add_argument("--alpha-sweep", action="store_true",
                        help="print the LENGTH_NORM_ALPHA calibration table instead of "
                             "the report -- the source of the comment table in "
                             "tools/cc/hooks/_recall.py (--query/--misses/--sweep are refused)")
    parser.add_argument("--strip-fraction", type=float, default=None,
                        help=f"ubiquity threshold for the stripped arm, in (0, 1) "
                             f"(default {STRIP_FRACTION})")
    parser.add_argument("--min-kept", type=int, default=None,
                        help=f"--sweep only: minimum tokens a stripped query keeps "
                             f"(default {MIN_STRIPPED_TOKENS}); one run per value "
                             f"regenerates the MIN_STRIPPED_TOKENS table above")
    parser.add_argument("--query", action="append", default=[], metavar="TEXT",
                        help="print the full ranking for TEXT as an extra named case (repeatable)")
    parser.add_argument("--root", type=Path, default=REPO_ROOT,
                        help="corpus root (default: this repo). The ranker and the "
                             "hand-labelled arms (paraphrase, task) always come from this repo.")
    args = parser.parse_args(argv)

    if args.strip_fraction is not None and not 0.0 < args.strip_fraction < 1.0:
        parser.error(f"--strip-fraction must be in (0, 1); got {args.strip_fraction}")
    if args.sweep and (args.query or args.misses):
        parser.error("--sweep does not take --query or --misses")
    if args.min_kept is not None and not args.sweep:
        parser.error("--min-kept is only meaningful with --sweep")
    if args.min_kept is not None and args.min_kept < 1:
        parser.error(f"--min-kept must be at least 1; got {args.min_kept}")
    if args.alpha_sweep and (args.query or args.misses or args.sweep):
        parser.error("--alpha-sweep does not take --query, --misses or --sweep")
    strip_fraction = STRIP_FRACTION if args.strip_fraction is None else args.strip_fraction

    corpus = _recall._load_corpus(args.root)
    if not corpus:
        print(f"no recall corpus under {args.root}", file=sys.stderr)
        return 1

    if args.sweep:
        fractions = tuple(sorted({*SWEEP_FRACTIONS, strip_fraction}, reverse=True))
        rows = sweep(args.root, corpus, fractions, min_kept=args.min_kept)
        for r in rows:
            if r["n"] == 0:  # an n/a row is a number a reader skims past; say it
                print(f"WARN: the stripped arm is empty at fraction {r['fraction']} "
                      f"(min kept {args.min_kept or MIN_STRIPPED_TOKENS}) -- its rates "
                      "are n/a and measure nothing", file=sys.stderr)
        print(json.dumps(rows, indent=2) if args.json else render_sweep(rows))
        return 0

    if args.alpha_sweep:
        rows = alpha_sweep(args.root, corpus, strip_fraction=strip_fraction)
        print(json.dumps(rows, indent=2) if args.json else render_alpha_sweep(rows))
        return 0

    report = evaluate(args.root, corpus=corpus, strip_fraction=strip_fraction,
                      extra_queries=tuple(args.query))
    for name in empty_arms(report):
        print(f"WARN: arm {name!r} is empty -- its rates are n/a and measure nothing",
              file=sys.stderr)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report, show_misses=args.misses))
    return 0


if __name__ == "__main__":
    sys.exit(main())
