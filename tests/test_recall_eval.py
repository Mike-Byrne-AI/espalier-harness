"""The recall evaluation instrument (`scripts/recall_eval.py`) -- is it measuring
what it says, on the path that ships, from ground truth the ranker did not write?

`tests/test_recall_calibration.py` guards the NAMING axis with a floor and an
invariant; `tests/test_recall.py` guards the DESCRIBING axis with banded pins.
Neither reports a number, and neither measures the naming arm on
``recall_union`` -- the front door `/recall` actually runs. The instrument does
both, and this file guards the instrument: the arms are non-vacuous, the labels
come from the corpus and never from a ranking call, the front door provably
cannot lose an answer the control had, the constants it claims to share with
sister sites are PINNED to those sites rather than re-typed, and the instrument
sees the one ranker regression this repo has already shipped once (no length
normalisation).

What this file deliberately does NOT pin: any rate, any rank, any named case's
position. Those are the instrument's OUTPUT and they move on ordinary
documentation commits (tests/test_recall.py's arm comment, caveat 3: one added
document moves a paraphrase constant 7% of the time). A pin here would red on
the next memory/ file and be deleted; the floors live in the calibration file
and the bands in test_recall.py, where they were earned.

⚠ Loaded via ``importlib.spec_from_file_location`` per ``tests/CLAUDE.md`` --
``scripts/`` is not an importable package.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "recall_eval.py"
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _recall  # noqa: E402

from tests.test_recall import (  # noqa: E402
    _PARAPHRASE_ARM,
    _PARAPHRASE_CONTROL_TOP,
    _PARAPHRASE_UNION_TOP,
)
from tests.test_doc_source_citations import _RECORD_SURFACE_DOCS  # noqa: E402
from tests.test_recall_calibration import MIN_TOP1_ACCURACY  # noqa: E402
from tests.test_recall_calibration import labels as _calibration_labels_fixture  # noqa: E402
from tests._recall_pins import (  # noqa: E402
    ALPHA_PROVENANCE_RE,
    BODY_AGREEMENT_RE,
    STRIP_PROVENANCE_RE,
    alpha_block,
    block_prose,
    count_drift,
    min_kept_block,
    rate_drift,
    strip_block,
)

#: Non-vacuity floor for the stripped arm. The heading arm's floor in the
#: calibration file is 100 of ~290; the stripped arm measured 251 at
#: STRIP_FRACTION=0.15 / MIN_STRIPPED_TOKENS=2 on 2026-09-03, so 50 is well
#: below today and well above "the strip rule ate the arm".
MIN_STRIPPED_ARM = 50

_NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 8: "eight"}


def _delivered_shape(eval_mod) -> str:
    """The phrase every source-of-truth site states for what /recall delivers,
    derived from the shim's slot count: 'up to four candidates' at UNION_TOP=2.
    'Up to', not 'two to': the floor is one line, not two (see the one-word
    query pin below)."""
    return f"up to {_NUMBER_WORDS[2 * eval_mod.UNION_TOP]} candidates"


@pytest.fixture(scope="module")
def eval_mod():
    spec = importlib.util.spec_from_file_location("recall_eval", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: the script's dataclasses carry string annotations
    # (`from __future__ import annotations`), and dataclasses resolves those by
    # looking the class's module up in sys.modules. Unregistered, every field
    # annotation raises at class-creation time -- the sibling exec_module idiom
    # in test_derived_population_census.py never hit this because that script
    # declares no dataclass.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def corpus():
    """The live corpus, loaded ONCE for the module (the calibration file's idiom)."""
    return _recall._load_corpus(REPO_ROOT)


@pytest.fixture(scope="module")
def small_corpus(corpus):
    """A dozen documents, for tests that exercise evaluate()'s MECHANICS (cache
    scoping, JSON shape) and do not need the ~5 s full run."""
    return corpus[:12]


@pytest.fixture(scope="module")
def fresh_alpha_rows(eval_mod, corpus):
    """One full LENGTH_NORM_ALPHA sweep for the module (~30s on an idle box).
    Every slow test that needs the sweep reads this, so the cost is paid once."""
    return eval_mod.alpha_sweep(REPO_ROOT, corpus)


@pytest.fixture(scope="module")
def report(eval_mod, corpus):
    """One full evaluation, shared -- ~5 s, and every assertion below reads it."""
    return eval_mod.evaluate(REPO_ROOT, corpus=corpus)


class TestArmsAreNotVacuous:
    """Every rate the instrument prints is a ratio over an arm; an empty arm
    prints a confident `n/a` and measures nothing."""

    def test_heading_arm_is_the_calibration_population(self, report):
        assert report["arms"]["heading"]["n"] > 100

    def test_stripped_arm_survives_the_strip_rule(self, report):
        assert report["arms"]["stripped"]["n"] > MIN_STRIPPED_ARM

    def test_paraphrase_arm_is_the_committed_one(self, eval_mod):
        """The instrument reads _PARAPHRASE_ARM out of tests/test_recall.py by
        AST so there is one copy. This is the parity check: the AST read agrees
        with the executed module, row for row."""
        assert eval_mod.load_paraphrase_arm() == tuple(_PARAPHRASE_ARM)

    def test_empty_arms_are_named_not_silent(self, eval_mod):
        """The CLI prints a WARN line per empty arm; this is the predicate it
        uses, checked on a synthetic report so it does not depend on producing
        an empty arm from the live corpus."""
        fake = {"arms": {"heading": {"n": 3}, "stripped": {"n": 0}, "paraphrase": {"n": 0}}}
        assert eval_mod.empty_arms(fake) == ["stripped", "paraphrase"]


class TestTheParaphraseLoaderIsLoudWhenItFails:
    """`()` from the loader means `n/a` in the table. Every way the loader can
    come back empty must say so on stderr, and the ordinary refactors of a
    constant -- annotating it, nesting it -- must NOT come back empty."""

    def test_missing_source_warns_and_yields_empty(self, eval_mod, tmp_path, capsys):
        assert eval_mod.load_paraphrase_arm(tmp_path / "absent.py") == ()
        assert "WARN: paraphrase arm is empty" in capsys.readouterr().err

    def test_absent_constant_warns(self, eval_mod, tmp_path, capsys):
        (tmp_path / "other.py").write_text("X = 1\n", encoding="utf-8")
        assert eval_mod.load_paraphrase_arm(tmp_path / "other.py") == ()
        assert "no _PARAPHRASE_ARM assignment" in capsys.readouterr().err

    def test_a_latin1_source_warns_and_yields_empty(self, eval_mod, tmp_path, capsys):
        """Ledger DEF-829: ``UnicodeDecodeError`` is a ``ValueError`` the
        ``(OSError, SyntaxError)`` tuple let past. The source is parsed from
        bytes now, so a non-UTF-8 file with no coding cookie is the
        SyntaxError Python itself raises, and the arm says so."""
        src = tmp_path / "cp1252.py"
        src.write_bytes(b'_PARAPHRASE_ARM = (("caf\xe9", "1."),)\n')
        assert eval_mod.load_paraphrase_arm(src) == ()
        assert "cannot parse source: SyntaxError" in capsys.readouterr().err

    def test_annotated_assignment_is_still_read(self, eval_mod, tmp_path):
        src = tmp_path / "ann.py"
        src.write_text(
            '_PARAPHRASE_ARM: tuple[tuple[str, str], ...] = (("q one", "1."), ("q two", "2."))\n',
            encoding="utf-8",
        )
        assert eval_mod.load_paraphrase_arm(src) == (("q one", "1."), ("q two", "2."))

    def test_nested_assignment_is_still_read(self, eval_mod, tmp_path):
        src = tmp_path / "nested.py"
        src.write_text('if True:\n    _PARAPHRASE_ARM = (("q", "3."),)\n', encoding="utf-8")
        assert eval_mod.load_paraphrase_arm(src) == (("q", "3."),)

    def test_non_literal_warns(self, eval_mod, tmp_path, capsys):
        src = tmp_path / "expr.py"
        src.write_text('S = "x"\n_PARAPHRASE_ARM = (("q" + S, "2."),)\n', encoding="utf-8")
        assert eval_mod.load_paraphrase_arm(src) == ()
        assert "not a literal" in capsys.readouterr().err

    def test_malformed_row_warns(self, eval_mod, tmp_path, capsys):
        src = tmp_path / "row.py"
        src.write_text('_PARAPHRASE_ARM = (("q", "2."), 5)\n', encoding="utf-8")
        assert eval_mod.load_paraphrase_arm(src) == ()
        assert "row is not (str, str)" in capsys.readouterr().err


class TestLabelsAreNotScorerDerived:
    """Ground truth is a fact about the corpus. A label set that consulted the
    ranker would make the instrument agree with any ranking it was handed."""

    def test_heading_labels_are_the_calibration_fixtures_output(self, eval_mod, corpus):
        """Pinned against the calibration file's OWN labels fixture, called
        directly -- not against a re-typed copy of its rule. A third copy of
        `len(title) < 8 / len(t) > 2 / len(toks) < 3` would stay green while
        the fixture changed underneath it (STANDING_PRINCIPLES 14)."""
        expected = _calibration_labels_fixture.__wrapped__(corpus)
        got = [(lb.query, lb.expected) for lb in eval_mod.heading_labels(corpus)]
        assert got == expected

    def test_stripped_queries_are_strict_subsets_of_their_heading_twin(self, eval_mod, corpus):
        arm = eval_mod.build_stripped(corpus)
        heading = {lb.expected: lb.query.split() for lb in eval_mod.heading_labels(corpus)}
        for lb in arm.labels:
            twin = heading[lb.expected]  # KeyError here = a stripped label with no heading twin
            kept = lb.query.split()
            assert set(kept) < set(twin), (lb.expected, kept, twin)
            assert len(kept) >= eval_mod.MIN_STRIPPED_TOKENS
            assert arm.paired_queries[lb.expected] == " ".join(twin)

    def test_stripped_census_accounts_for_every_heading(self, eval_mod, corpus):
        """The arm is a subset of the heading population; the census must say
        exactly where the rest went, so nothing is filtered invisibly."""
        arm = eval_mod.build_stripped(corpus)
        heading_n = len(eval_mod.heading_labels(corpus))
        assert len(arm.labels) + arm.census["unchanged"] + arm.census["too_short"] == heading_n

    def test_stripped_arm_shares_no_query_with_the_heading_arm(self, eval_mod, corpus):
        heading_queries = {lb.query for lb in eval_mod.heading_labels(corpus)}
        stripped_queries = {lb.query for lb in eval_mod.stripped_labels(corpus)}
        assert not heading_queries & stripped_queries

    def test_label_builders_never_call_the_ranker(self, eval_mod):
        """Structural: the label functions must not reference a ranking call.
        The calibration file pins the same property on its fixture. The set is
        DERIVED -- every `*_labels`, `load_*` and `build_stripped` callable the
        module exposes -- so a new arm's builder is walked by construction: the
        first cut listed five names by hand, and moving the loader body into
        `load_labelled_arm` left the guard inspecting a three-line delegator
        while an injected `recall()` in the new body stayed green (both reviews
        of the DEF-699 lane drove it)."""
        names = sorted(
            n for n in dir(eval_mod)
            if (n.endswith("_labels") or n.startswith("load_") or n == "build_stripped")
            and callable(getattr(eval_mod, n))
        )
        for required in ("heading_labels", "build_stripped", "stripped_labels",
                         "paraphrase_labels", "load_paraphrase_arm",
                         "load_labelled_arm", "task_labels"):
            assert required in names, names
        for name in names:
            body = inspect.getsource(getattr(eval_mod, name))
            assert not re.search(r"\brecall\(|\brecall_union\(|nearest_by_title\(", body), name


class TestSisterSitesArePinnedNotRetyped:
    """Every constant the script says it shares with another file is asserted
    equal to that file's value. A comment saying 'must track X' is not a pin."""

    def test_union_top_tracks_the_cli_shim(self, eval_mod):
        shim = (HOOKS_DIR / "_recall.py").read_text(encoding="utf-8")
        m = re.search(r"recall_union\(_query, _root, top=(\d+)\)", shim)
        assert m, "the CLI shim's recall_union call moved; re-anchor this test"
        assert int(m.group(1)) == eval_mod.UNION_TOP

    def test_union_top_tracks_the_paraphrase_battery(self, eval_mod):
        assert eval_mod.UNION_TOP == _PARAPHRASE_UNION_TOP

    def test_control_top_tracks_the_paraphrase_battery(self, eval_mod):
        assert eval_mod.CONTROL_TOP == _PARAPHRASE_CONTROL_TOP

    def test_recall_command_body_states_the_delivered_shape(self, eval_mod):
        """The /recall command body is the only surface that turns candidate
        ORDER into reader behaviour, and it was still describing a top=1 output
        ('if exactly one prints, the rankers agreed') after the CLI had run
        top=2 for weeks -- measured 2026-09-04: no query delivers one candidate.
        Pin the body's count to the constant and require it to say the list
        alternates, so the next construction change cannot leave the consumer
        behind again."""
        body = (REPO_ROOT / ".claude" / "commands" / "recall.md").read_text(encoding="utf-8")
        expected = _delivered_shape(eval_mod)
        assert expected in body, f"/recall body no longer says {expected!r}"
        assert "alternating" in body, "/recall body no longer says the candidates alternate"
        assert "exactly one prints" not in body, "the dead top=1 branch is back in the body"
        # The 2026-09-04 rewrite said "two to four" and "a single line never
        # prints" -- a naming-arm measurement generalised to every query. A
        # one-word query delivers ONE line about a third of the time (measured
        # the same day: 107 to 121 of 300 random corpus words across three
        # draws). The body must say so.
        assert re.search(r"single line", body), (
            "/recall body no longer tells the reader what a single line means"
        )

    def test_recall_command_body_figures_track_the_instrument(self, report):
        """The body quotes two measured figures -- how often the rankers agree at
        top-1 and the delivered-line histogram on the naming arm -- as dated prose.
        A ranking change moves them (the 2026-09-04 focus tie-break did) and
        nothing else reds, so pin each to the eval's own number: the arm size
        under the count band (wide, it is provenance) and the agreement under a
        fixed six (it is the claim). Re-measure and re-date the body when this
        reds; widen neither."""
        body = (REPO_ROOT / ".claude" / "commands" / "recall.md").read_text(encoding="utf-8")
        h = report["arms"]["heading"]
        m = BODY_AGREEMENT_RE.search(body)
        assert m, "the body no longer quotes the agreement figure as 'N of M queries naming a document'"
        agree, n = int(m.group(1)), int(m.group(2))
        assert count_drift("naming queries", n, h["n"]) is None, (
            f"body says {n} naming queries, the arm has {h['n']} -- re-measure and re-date"
        )
        assert abs(agree - h["agree_at_1"]) <= 6, (
            f"body says the rankers agree on {agree} of {n}; the instrument measures "
            f"{h['agree_at_1']} of {h['n']} -- re-measure with `python3 scripts/recall_eval.py` "
            "and re-date the body"
        )
        m = re.search(r"(\d):(\d+) / (\d):(\d+) / (\d):(\d+) on the \d+ naming queries", body)
        assert m, "the body no longer quotes the delivered-line histogram as 'a:n / b:n / c:n'"
        quoted = {m.group(i): int(m.group(i + 1)) for i in (1, 3, 5)}
        fresh = h["delivered_histogram"]
        assert set(quoted) == set(fresh), f"body buckets {sorted(quoted)} vs measured {sorted(fresh)}"
        drift = {k: (quoted[k], fresh[k]) for k in quoted if abs(quoted[k] - fresh[k]) > 10}
        assert not drift, f"delivered-line histogram drifted (body, measured): {drift} -- re-measure and re-date"


class TestTheDeliveredShapeIsStatedAtEverySourceOfTruth:
    """DEF-615. The /recall command BODY was rewritten for the interleave while
    the description line the harness loads every session -- and six sibling
    sites -- kept promising 'the single most relevant piece' or 'up to two'.
    A fix that lands one surface short is the shape this repo had already
    named; these pins make the next construction change red at every site
    that states the shape, not just the one the fixer happened to open.

    ``SITES`` are the SOURCE-OF-TRUTH copies only. The mirrors and rendered
    copies (both claude asset trees, the vendor twin, the asset-docs mirror,
    ``examples/CLAUDE.template.md`` and the ``cc/`` surface docs) are owned by
    their own byte-parity gates and follow on sync.
    """

    SITES = (
        ".claude/commands/recall.md",
        "CLAUDE.md",
        "docs/CHEAT-SHEET.md",
        ".claude/skills/blueprint-authoring/SKILL.md",
        "README.md",
        "tools/cc/hooks/_recall.py",
    )

    #: Wordings the sites carried while the CLI already delivered up to
    #: 2*UNION_TOP candidates -- including the "two to four" the first repair
    #: wrote, which a one-word query falsifies. This is a KNOWN-WORDINGS gate,
    #: not a completeness gate: it catches a phrase coming back, never a new
    #: mis-statement (the adversarial pass found "returning BOTH winners" one
    #: inflection away -- true where it stands, and invisible here).
    STALE = (
        "single most relevant",
        "up to two candidates",
        "up to 2 nearest",
        "two nearest matches",
        "two to four candidates",
        "returns the NEAREST match",
        "returns both winners",
    )

    #: Dated records where a retired wording is history, not a claim -- editing
    #: one to satisfy this gate would falsify the record (Core Rule 13). The
    #: citation contract's declared set is the shared home; the additions are
    #: this gate's own, with their reasons, so a widening there for a
    #: citation-rot reason does not silently widen this gate unexamined.
    RECORDS = frozenset(_RECORD_SURFACE_DOCS) | frozenset({
        "CHANGELOG.md",          # the full internal record, names the command as released
        "ESPALIER_MEMORY.md",    # the session log quotes what a session found
        "tests/test_recall_eval.py",  # this file quotes the phrases it hunts
    })

    @staticmethod
    def _order_stated_beside(text: str, shape: str) -> bool:
        """The order clause must sit in the SAME passage as the shape, not
        anywhere in the file: ``_recall.py`` says "interleaved" four times in
        ``recall_union`` alone, so a file-wide search would stay green after
        the module docstring reverted to the old wording. Checked at EVERY
        occurrence -- ``recall.md`` states the shape on its description line
        and again in the body paragraph that teaches the reader the order, and
        ``_recall.py`` at lines 5 and 16; the first occurrence passing must not
        cover a second one going stale."""
        starts = [m.start() for m in re.finditer(re.escape(shape), text)]
        return bool(starts) and all(
            re.search(r"alternating|interleaved", text[max(0, i - 600): i + 600])
            for i in starts
        )

    @pytest.mark.parametrize("rel", SITES)
    def test_site_states_the_delivered_range_and_order(self, eval_mod, rel):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        shape = _delivered_shape(eval_mod)
        assert shape in text, f"{rel} no longer says {shape!r}"
        assert self._order_stated_beside(text, shape), (
            f"{rel} no longer says, beside the shape, that the two rankers' candidates alternate"
        )

    def test_the_description_line_carries_the_shape_as_rendered(self, eval_mod):
        """The template table and the slash-command menu show the FIRST SENTENCE
        of the description, cut at 100 characters -- which is exactly how the
        body could be right for weeks while the line every session loads stayed
        wrong. Assert on the renderer's own output -- its paragraph walk AND its
        sentence cut -- not on a re-typed copy of either."""
        from espalier.cli import _first_sentence, _opening_paragraph

        text = (REPO_ROOT / ".claude" / "commands" / "recall.md").read_text(encoding="utf-8")
        rendered = _first_sentence(_opening_paragraph(text))
        assert _delivered_shape(eval_mod) in rendered, (
            f"the rendered description no longer states the shape: {rendered!r}"
        )
        assert not rendered.endswith("\u2026"), (
            f"the first sentence overflows the renderer's cut: {rendered!r}"
        )
        # The slash-command menu Claude Code shows is a second, tighter cut:
        # observed 2026-09-04 showing 97 characters of a 99-character sentence
        # before its ellipsis. Not this repo's renderer -- a bound with the
        # observation recorded, so a reword that crosses it is a choice.
        assert len(rendered) <= 97, (
            f"the first sentence is {len(rendered)} chars; the command menu cut 97 when observed"
        )

    def test_a_one_word_query_can_deliver_a_single_candidate(self, corpus):
        """The shape is 'up to four', not 'two to four': a query whose only
        token lives in ONE document scores one document, under both rankers,
        and the dedup leaves one line. Derived from the live corpus (a token
        with document frequency 1), never a hard-coded word."""
        df: dict[str, int] = {}
        for doc in corpus:
            for tok in set(doc.tokens):
                df[tok] = df.get(tok, 0) + 1
        # isalpha: the lexicographically-first singleton is otherwise a quoted
        # git sha, and a red reading ('00554bb', [...]) looks like corruption.
        singleton = next(
            tok for tok in sorted(df) if df[tok] == 1 and len(tok) > 3 and tok.isalpha()
        )
        hits = _recall.recall_union(singleton, REPO_ROOT, top=2)
        assert len(hits) == 1, (singleton, [h.source for h in hits])

    def test_line_two_follows_the_agree_disagree_rule_on_every_heading_query(self, eval_mod, corpus):
        """The docs say line two is the describing ranker's winner WHEN THE TWO
        DISAGREE, and the naming ranker's runner-up when they agree -- because
        the union prints a document both chose once, in its first slot, and
        zip_longest then pairs pass 1's runner-up with pass 2's. Asserted per
        query over the whole heading arm (measured 2026-09-04: 225 agree, 73
        disagree, 0 violations), not sampled: a per-pass floor that broke the
        rule for a subset would slip past a two-query pin."""
        agreed = disagreed = 0
        violations: list[tuple[str, str, str]] = []
        with eval_mod._cached(corpus):
            for lb in eval_mod.heading_labels(corpus):
                first = _recall.recall(lb.query, REPO_ROOT, top=2, norm=_recall._vocab_norm, docs=corpus)
                second = _recall.recall(lb.query, REPO_ROOT, top=2, norm=_recall._totlen_norm, docs=corpus)
                union = _recall.recall_union(lb.query, REPO_ROOT, top=2)
                if len(union) < 2 or len(first) < 2:
                    continue  # the one-line case is the singleton pin above
                if first[0].source == second[0].source:
                    agreed += 1
                    expected = first[1].source
                else:
                    disagreed += 1
                    expected = second[0].source
                if union[1].source != expected:
                    violations.append((lb.query, union[1].source, expected))
        assert agreed and disagreed, "the heading arm no longer has both kinds of query"
        assert not violations, violations[:5]

    @staticmethod
    def _stale_hits(texts: dict[str, str], stale: tuple[str, ...]) -> list[tuple[str, str]]:
        return [(rel, phrase) for rel, text in sorted(texts.items())
                for phrase in stale if phrase in text]

    def test_no_live_tracked_file_carries_a_retired_wording(self):
        """Derived from the tracked set, never from ``SITES`` -- a hand list is
        the one-surface-short trap in miniature. The population comes through
        ``tests/_git_oracle.py``, which raises when git cannot answer or the
        answer is implausibly small, so an empty census skips rather than
        passing vacuously. It was registered in ``conftest._FULL_TREE_NODEIDS``
        until 2026-09-23: on a DEF-670-seeded export the oracle answers with
        the shipped subset and the sweep is live there (measured under the
        self-expiry audit, TP-455 1-G), so it runs on an export too."""
        from tests._git_oracle import GitAnswerUnavailable, require_tracked_paths

        try:
            # 100: the six SITES alone are a handful; the live tree carries
            # several hundred tracked .md/.py files, so anything under 100 is a
            # collapsed or foreign population, not a small repo.
            tracked = require_tracked_paths(
                REPO_ROOT, "*.md", "*.py", minimum=100, what="tracked .md/.py surfaces"
            )
        except GitAnswerUnavailable as exc:
            pytest.skip(f"tracked-set census unavailable -- not a dev tree / fresh clone: {exc}")
        texts = {
            rel: (REPO_ROOT / rel).read_text(encoding="utf-8")
            for rel in tracked if rel not in self.RECORDS
        }
        hits = self._stale_hits(texts, self.STALE)
        assert not hits, "retired /recall wording is back on a live surface: " + ", ".join(
            f"{rel} ({phrase!r})" for rel, phrase in hits
        )

    def test_the_absence_gate_can_fire(self):
        """Earn the red: the gate above must see a planted phrase."""
        hits = self._stale_hits(
            {"x.md": "It returns the single most relevant piece.", "y.md": "clean"},
            self.STALE,
        )
        assert hits == [("x.md", "single most relevant")]


class TestTheFrontDoorCannotRegress:
    """recall_union's docstring, property 1: recall()'s winner is always element
    0, so every answer the control had is still available. Stated for years;
    here it is checked."""

    def test_union_at_any_never_falls_below_control_at_1(self, report):
        for name, arm in report["arms"].items():
            assert arm["union_at_any"] >= arm["control_at_1"], name

    def test_union_element_zero_is_the_control_answer_by_count(self, report):
        for name, arm in report["arms"].items():
            assert arm["union_at_1"] == arm["control_at_1"], name

    def test_union_element_zero_is_the_control_answer_per_query(self, eval_mod, corpus):
        """The count identity above could hold by coincidence; this one cannot.
        Checked on the whole paraphrase arm and a slice of the heading arm."""
        labels = list(eval_mod.paraphrase_labels()) + list(eval_mod.heading_labels(corpus))[:40]
        with eval_mod._cached(corpus):
            for lb in labels:
                control = eval_mod._control(lb.query, REPO_ROOT, 1)
                union = eval_mod._front_door(lb.query, REPO_ROOT)
                assert union[:1] == control[:1], lb.query

    def test_pass2_rescues_match_an_independent_rederivation(self, report, eval_mod, corpus):
        """Re-derive the heading arm's rescue count from the two ranking calls
        directly -- absent from recall(top=UNION_TOP), present in recall_union --
        and require the instrument to agree exactly.

        An exact re-derivation, not a bound: the first draft defined a rescue as
        'missed at control[0], found anywhere in the union', which counts pass
        1's own second slot as a second-ranker win (33 of them on the heading
        arm, every one at slot 2). A bound of the form
        `rescues <= union_at_any - control_at_1` holds with EQUALITY under that
        wrong definition, so it never bit; this does. (The 33 sat at slot 2
        under the old concatenation; since the interleave they read 25 at slot 2
        and 8 at slot 3 -- which is why the count is set-based, not slot-based.)
        """
        arm = next(a for a in eval_mod.build_arms(corpus) if a.name == "heading")
        rescues = 0
        with eval_mod._cached(corpus):
            for lb in arm.labels:
                pass1 = eval_mod._control(lb.query, REPO_ROOT, eval_mod.UNION_TOP)
                union = eval_mod._front_door(lb.query, REPO_ROOT)
                if lb.expected not in pass1 and lb.expected in union:
                    rescues += 1
        assert report["arms"]["heading"]["pass2_rescues"] == rescues

    def test_control_misses_reconcile_with_control_at_1(self, report):
        """The control@1 miss list is what lets a reader re-derive '0 lost'
        claims from --json; it must be the exact complement of the hit count."""
        for name, arm in report["arms"].items():
            assert len(arm["control_misses"]) == arm["n"] - arm["control_at_1"], name


class TestTheCorpusCacheIsScoped:
    def test_evaluate_restores_the_loader(self, eval_mod, small_corpus):
        """The instrument shares the _recall module object with every recall
        test in the suite. A loader patch left behind would make a later
        recall(tmp_path) answer from THIS repo's corpus."""
        before = _recall._load_corpus
        eval_mod.evaluate(REPO_ROOT, corpus=small_corpus)
        assert _recall._load_corpus is before

    def test_a_leaking_cache_would_be_caught(self, eval_mod, small_corpus, monkeypatch):
        """Earn the red for the restore check above: swap in a cache that patches
        and never restores, run evaluate, and confirm the loader is left
        replaced -- i.e. the assertion above discriminates. monkeypatch puts the
        real loader back regardless of how this test exits."""
        real_loader = _recall._load_corpus
        monkeypatch.setattr(_recall, "_load_corpus", real_loader)  # so teardown restores it

        @contextmanager
        def leaking(c):
            _recall._load_corpus = lambda root: c
            yield

        monkeypatch.setattr(eval_mod, "_cached", leaking)
        eval_mod.evaluate(REPO_ROOT, corpus=small_corpus)
        assert _recall._load_corpus is not real_loader

    def test_synthetic_corpus_still_resolves_after_evaluate(self, eval_mod, small_corpus, tmp_path):
        eval_mod.evaluate(REPO_ROOT, corpus=small_corpus)
        (tmp_path / "memory").mkdir()
        (tmp_path / "memory" / "zebra-quokka-note.md").write_text(
            "# Zebra quokka lantern\n\nzebra quokka lantern zebra quokka lantern\n",
            encoding="utf-8",
        )
        hits = _recall.recall("zebra quokka lantern", tmp_path, top=1)
        assert hits and hits[0].source == "memory/zebra-quokka-note.md"


#: The sort key recall() shipped before 2026-09-04: score, canonical-footgun,
#: source path. An exact tie went to whichever path sorted higher.
def _path_name_key(sd):
    return (sd[0], _recall._is_canonical_footgun(sd[1].source), sd[1].source)


class TestTheInstrumentSeesTheKnownRegression:
    """Earn the red. The one ranker regression this repo has shipped -- no
    length normalisation, 66.7% top-1 -- must be visible through the instrument,
    or a fix evaluated with it could ship the same defect back.

    The regression was a PAIR, and that was only learned when half of it was
    fixed: under no normalisation a heading query's named document matches all
    of its own terms and cannot lose strictly, only tie, and the path-name key
    broke those ties against it. With the focus key (fewer tokens first) alpha 0
    reads 83.2% on this arm (2026-09-09; 84.8% on the 2026-09-04 corpus). So the
    mutation that reproduces what shipped puts
    BOTH back; the contrast below says which half carries the accuracy.
    """

    def test_disabling_normalisation_with_the_path_name_key_drops_below_the_floor(
        self, eval_mod, corpus, monkeypatch
    ):
        monkeypatch.setattr(_recall, "LENGTH_NORM_ALPHA", 0.0)
        monkeypatch.setattr(_recall, "_rank_key", _path_name_key)
        broken = eval_mod.evaluate(REPO_ROOT, corpus=corpus)
        assert broken["arms"]["heading"]["rates"]["control_at_1"] < MIN_TOP1_ACCURACY

    def test_the_focus_key_alone_clears_the_floor_without_normalisation(
        self, eval_mod, corpus, monkeypatch
    ):
        """The finding, pinned so it cannot quietly un-happen: most of the
        'lost to a bigger document' count was ties, not breadth. If this reds,
        the exponent has become load-bearing on the heading arm again and the
        LENGTH_NORM_ALPHA annotations are wrong."""
        monkeypatch.setattr(_recall, "LENGTH_NORM_ALPHA", 0.0)
        alone = eval_mod.evaluate(REPO_ROOT, corpus=corpus)
        assert alone["arms"]["heading"]["rates"]["control_at_1"] >= MIN_TOP1_ACCURACY

    def test_the_live_ranker_clears_the_same_floor(self, report):
        """The converse, so the assertion above is a contrast and not a
        property of the floor."""
        assert report["arms"]["heading"]["rates"]["control_at_1"] >= MIN_TOP1_ACCURACY


class TestReportShape:
    def test_report_is_json_serialisable_and_complete(self, report, eval_mod):
        text = json.dumps(report)
        back = json.loads(text)
        assert set(back) == {"corpus", "constants", "arms", "named_cases"}
        assert set(back["arms"]) == {"heading", "stripped", "paraphrase", "task"}
        for name, arm in back["arms"].items():
            # stable keys: a CONTROL_TOP change must not rename them, or the
            # documented before/after diff breaks
            assert {"control_at_1", "control_at_k", "union_at_1", "union_at_any"} <= set(arm["rates"])
            assert ("paired_heading_at_1" in arm["rates"]) == (name == "stripped")
        assert back["constants"]["UNION_TOP"] == eval_mod.UNION_TOP
        assert back["constants"]["CONTROL_TOP"] == eval_mod.CONTROL_TOP

    def test_corpus_facts_name_the_unmeasured_principles(self, report):
        """Documents with no heading query are unmeasured by two of four arms;
        the report must list them rather than let 'n lost' read as 'all'."""
        facts = report["corpus"]
        assert isinstance(facts["standing_principles_without_heading_query"], list)
        assert set(facts["standing_principles_without_heading_query"]) <= set(
            facts["docs_without_heading_query"]
        )

    def test_def679_is_a_named_case_on_both_paths(self, report):
        case = next(c for c in report["named_cases"] if c["id"] == "DEF-679")
        assert case["control"] and case["front_door"]
        assert case["control"][0]["source"] == case["front_door"][0]["source"]

    def test_front_door_hits_say_which_pass_emitted_them(self, report):
        """Scores on the front door sit on two scales; `from_pass` is what
        stops a reader 'fixing' a slot-2 score below slot 3's by sorting."""
        for case in report["named_cases"]:
            passes = [h["from_pass"] for h in case["front_door"]]
            assert set(passes) <= {1, 2}, passes
            assert passes[0] == 1, "element 0 must be pass 1's winner"

    def test_main_json_emits_a_parseable_report(self, eval_mod, capsys):
        assert eval_mod.main(["--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["arms"]["heading"]["n"] > 100

    def test_sweep_row_for_the_default_fraction_matches_the_report(self, eval_mod, corpus, report):
        rows = eval_mod.sweep(REPO_ROOT, corpus, fractions=(eval_mod.STRIP_FRACTION,))
        assert rows[0]["n"] == report["arms"]["stripped"]["n"]
        assert rows[0]["paired_heading_at_1"] == report["arms"]["stripped"]["rates"]["paired_heading_at_1"]

    def test_strip_fraction_outside_unit_interval_is_refused(self, eval_mod):
        for bad in ("0", "1", "2.0", "-1"):
            with pytest.raises(SystemExit) as exc:
                eval_mod.main(["--strip-fraction", bad])
            assert exc.value.code == 2

    def test_sweep_refuses_flags_it_would_ignore(self, eval_mod):
        for extra in (["--query", "x"], ["--misses"]):
            with pytest.raises(SystemExit) as exc:
                eval_mod.main(["--sweep", *extra])
            assert exc.value.code == 2



class TestTheStripSweepRegeneratesTheEvalTables:
    """`--sweep` is the source of the STRIP_FRACTION comment table in
    scripts/recall_eval.py, and `--sweep --min-kept N` of the MIN_STRIPPED_TOKENS
    table above it. The alpha table in _recall.py got its freshness check the
    day it was found aging silently (DEF-679); these two, same shape and same
    aging, had none. Measured 2026-09-09: a re-pin regenerated one of them and
    left the other contradicting it on the shipped cell twenty lines up, with
    nothing red. A guard born for a class had been scoped to one instance
    (STANDING_PRINCIPLES §8, §18); this closes the sibling sites.
    """

    _STRIP_ROW = re.compile(
        r"^#:\s+(\d\.\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+\.\d)%\s+(\d+\.\d)%\s+([+-]\d+\.\d)",
        re.M)
    _MIN_ROW = re.compile(r"^#:\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+\.\d)%\s+(\d+\.\d)%", re.M)
    #: The floors the MIN_STRIPPED_TOKENS table documents. A dropped row would
    #: otherwise vanish from the guard with nothing red.
    _MIN_ROWS_DOCUMENTED = frozenset({1, 2, 3})

    @staticmethod
    def _pasted_strip_rows():
        """(block, {fraction: (tokens_stripped, arm, too_short, paired_h1, stripped_at_1, delta)})"""
        block = strip_block()
        rows = {}
        for m in TestTheStripSweepRegeneratesTheEvalTables._STRIP_ROW.finditer(block):
            rows[float(m.group(1))] = (
                int(m.group(2)), int(m.group(3)), int(m.group(4)),
                float(m.group(5)) / 100, float(m.group(6)) / 100, float(m.group(7)) / 100)
        return block, rows

    @staticmethod
    def _pasted_min_kept_rows():
        """(block, {min_kept: (arm, too_short, paired_h1, stripped_at_1)})"""
        block = min_kept_block()
        rows = {}
        for m in TestTheStripSweepRegeneratesTheEvalTables._MIN_ROW.finditer(block):
            rows[int(m.group(1))] = (int(m.group(2)), int(m.group(3)),
                                     float(m.group(4)) / 100, float(m.group(5)) / 100)
        return block, rows

    _count_drift = staticmethod(count_drift)
    _rate_drift = staticmethod(rate_drift)

    #: The sentences beside the three tables that restate cells, pinned to the
    #: parsed rows without a sweep. A re-paste that regenerates the cells and
    #: leaves a paragraph arguing the constant from the old sweep reds here:
    #: the 2026-09-21 re-paste found two such figures beside the alpha table
    #: that had survived two earlier re-pastes, and the strip paragraph's four
    #: had no guard at all. Every dated reading must carry its own table's
    #: paste date, so a re-date without a sweep (or a sweep without a re-date)
    #: reds too; the fractions the sentences name are derived from the parsed
    #: rows and the shipped constant, never listed here.
    _STRIP_DATE_RE = re.compile(
        r"Swept (\d{4}-\d{2}-\d{2}) on the live \d+-document corpus with MIN_STRIPPED_TOKENS=(\d+)")
    _HARDER_RE = re.compile(r"HARDER at every fraction \((\d+\.\d) to (\d+\.\d) points\)")
    _MAXIMISES_RE = re.compile(r"MAXIMISES THE ARM: (\d+) of (\d+) headings")
    _ABOVE_RE = re.compile(r"fewer headings contain one \((\d+) at (\d\.\d+)\)")
    _BELOW_RE = re.compile(r"two tokens \(((?:\d+, )*\d+) too_short\)")
    _MIN_KEPT_DATE_RE = re.compile(r"Measured (\d{4}-\d{2}-\d{2}) at STRIP_FRACTION")
    _ORIGINAL_ACC_RE = re.compile(r"\(\d+ of \d+ queries, (\d+\.\d)%\)")
    _ORIGINAL_RATIO_RE = re.compile(r"\(\d+/\d+ = 0\.\d{3} vs (0\.\d{3})\)")
    _RATIO_RE = re.compile(r"re-paste since \((\d+)/(\d+) = (0\.\d{3}) on (\d{4}-\d{2}-\d{2})\)")
    _ACCURACY_RE = re.compile(r"under it \((\d+\.\d)% on (\d{4}-\d{2}-\d{2})\)")
    _ALPHA_DATE_RE = re.compile(r"Corpus \d+ docs, (\d{4}-\d{2}-\d{2});")
    _ALPHA_ROW_RE = re.compile(
        r"^#:\s+(\d\.\d\d)\s+(\d+\.\d)%\s+(\d+\.\d)%\s+(\d+\.\d)%\s+(\d+)", re.M)
    _ALPHA_GAIN_RE = re.compile(r"\((\d{4}-\d{2}-\d{2}): ([+-]\d+\.\d)pp and ([+-]\d+\.\d)pp;")
    _ALPHA_MARGIN_RE = re.compile(
        r"(\d\.\d\d) over (\d\.\d\d) is ~(\d+)pp on the heading arm and ~(\d+)pp on the "
        r"stripped arm \((\d{4}-\d{2}-\d{2})\)")

    def test_the_prose_beside_the_tables_restates_their_cells(self, eval_mod):
        """Sub-second and sweep-free: every figure the paragraphs derive from
        the tables equals the parsed cell, every delta keeps the sign the
        paragraph asserts, and every dated reading carries its table's paste
        date. The dated readings pinned here are the CURRENT paste; dated
        history that names an older corpus is left alone. A lost sentence is
        reported beside the drifted numbers, never instead of them."""
        stale: list[str] = []

        def need(rx, text, what):
            m = rx.search(text)
            if not m:
                stale.append(f"lost: {what}")
            return m

        # -- the STRIP_FRACTION table and its paragraph -------------------------
        block, rows = self._pasted_strip_rows()
        prose = block_prose(block)
        shipped_f = eval_mod.STRIP_FRACTION
        shipped = rows[shipped_f]
        below = [f for f in sorted(rows, reverse=True) if f < shipped_f]
        above = min(f for f in rows if f > shipped_f)

        m = need(self._STRIP_DATE_RE, block,
                 "the strip provenance line 'Swept DATE on the live N-document corpus with "
                 "MIN_STRIPPED_TOKENS=K'")
        strip_date = m.group(1) if m else None
        if m and int(m.group(2)) != eval_mod.MIN_STRIPPED_TOKENS:
            stale.append(f"the provenance line says MIN_STRIPPED_TOKENS={m.group(2)}; the "
                         f"constant is {eval_mod.MIN_STRIPPED_TOKENS}")

        m = need(self._HARDER_RE, prose, "'HARDER at every fraction (lo to hi points)'")
        if m:
            easier = [(f, r[5]) for f, r in sorted(rows.items()) if r[5] >= 0]
            if easier:
                stale.append("'HARDER at every fraction': a delta is not negative -- "
                             + ", ".join(f"{f}: {d:+.1%}" for f, d in easier))
            deltas = sorted(round(abs(r[5]) * 100, 1) for r in rows.values())
            if (float(m.group(1)), float(m.group(2))) != (deltas[0], deltas[-1]):
                stale.append(f"'HARDER at every fraction ({m.group(1)} to {m.group(2)} "
                             f"points)': the rows span {deltas[0]} to {deltas[-1]}")

        m = need(self._MAXIMISES_RE, prose, "'MAXIMISES THE ARM: A of B headings'")
        heading_claim = int(m.group(2)) if m else None
        if m:
            arm_claim = int(m.group(1))
            biggest = max(r[1] for r in rows.values())
            if arm_claim != shipped[1] or shipped[1] != biggest:
                stale.append(f"'MAXIMISES THE ARM: {arm_claim} of {heading_claim} headings': "
                             f"the shipped row's arm is {shipped[1]}, the largest arm {biggest}")

        m = need(self._ABOVE_RE, prose, "'(N at F)' for the fraction above the shipped one")
        if m and (float(m.group(2)) != above or int(m.group(1)) != rows[above][1]):
            stale.append(f"'({m.group(1)} at {m.group(2)})': the fraction above {shipped_f} "
                         f"is {above} and its arm {rows[above][1]}")

        m = need(self._BELOW_RE, prose,
                 "'(a, b, c too_short)' for the fractions below the shipped one")
        if m:
            claimed = tuple(int(x) for x in m.group(1).split(", "))
            expected = tuple(rows[f][2] for f in below)
            if claimed != expected:
                stale.append(f"'({m.group(1)} too_short)': the rows below {shipped_f} "
                             f"({', '.join(str(f) for f in below)}) read {expected}")

        # -- the MIN_STRIPPED_TOKENS table and its paragraph --------------------
        mblock, min_rows = self._pasted_min_kept_rows()
        mprose = block_prose(mblock)
        arm, _too_short, _h1, s1 = min_rows[eval_mod.MIN_STRIPPED_TOKENS]
        m = need(self._MIN_KEPT_DATE_RE, mprose, "'Measured DATE at STRIP_FRACTION'")
        if m and strip_date and m.group(1) != strip_date:
            stale.append(f"the MIN_STRIPPED_TOKENS table is dated {m.group(1)}, the "
                         f"STRIP_FRACTION table {strip_date}: regenerate both from one tree")
        m = need(self._ORIGINAL_ACC_RE, mprose, "the original '(N of M queries, dd.d%)'")
        original_acc = float(m.group(1)) if m else None
        m = need(self._ORIGINAL_RATIO_RE, mprose, "the original '(A/B = 0.ddd vs 0.ddd)'")
        original_ratio = float(m.group(1)) if m else None

        m = need(self._RATIO_RE, mprose, "'re-paste since (arm/headings = ratio on DATE)'")
        if m and heading_claim is not None:
            a, b = int(m.group(1)), int(m.group(2))
            ratio_claim, date = float(m.group(3)), m.group(4)
            if (a, b) != (arm, heading_claim):
                stale.append(f"'({a}/{b} = ...)': the shipped min-kept row's arm is {arm}, "
                             f"the strip paragraph's heading count {heading_claim}")
            if abs(ratio_claim - round(a / b, 3)) > 1e-9:
                stale.append(f"'({a}/{b} = {ratio_claim})': {a}/{b} is {a / b:.3f}")
            if original_ratio is not None and abs(a / b - original_ratio) > 0.02:
                stale.append(f"'within two points of the original's' no longer holds: "
                             f"{a / b:.3f} against {original_ratio}")
            if strip_date and date != strip_date:
                stale.append(f"the ratio reading is dated {date}, the table {strip_date}")
        m = need(self._ACCURACY_RE, mprose, "'under it (dd.d% on DATE)'")
        if m:
            acc_claim, date = float(m.group(1)), m.group(2)
            if abs(acc_claim - round(s1 * 100, 1)) > 1e-9:
                stale.append(f"'({acc_claim}% on ...)': the shipped min-kept row's stripped@1 "
                             f"is {s1:.1%}")
            if original_acc is not None and abs((original_acc - s1 * 100) - 2.0) > 0.5:
                stale.append(f"'about 2pp under it' no longer holds: {original_acc - s1 * 100:.1f}pp")
            if strip_date and date != strip_date:
                stale.append(f"the accuracy reading is dated {date}, the table {strip_date}")

        # -- the LENGTH_NORM_ALPHA table and its paragraph ----------------------
        ablock = alpha_block()
        aprose = block_prose(ablock)
        arows = {float(x.group(1)): (float(x.group(2)), float(x.group(3)))
                 for x in self._ALPHA_ROW_RE.finditer(ablock)}
        m = need(self._ALPHA_DATE_RE, aprose, "the alpha provenance 'Corpus N docs, DATE;'")
        alpha_date = m.group(1) if m else None
        shipped_a = _recall.LENGTH_NORM_ALPHA
        if 0.0 not in arows or shipped_a not in arows:
            stale.append(f"the alpha table lacks the 0.00 row or the shipped {shipped_a} row")
        else:
            gain_s = round(arows[shipped_a][1] - arows[0.0][1], 1)
            gain_h = round(arows[shipped_a][0] - arows[0.0][0], 1)
            m = need(self._ALPHA_GAIN_RE, aprose, "the dated gain pair '(DATE: +x.xpp and +y.ypp;'")
            if m:
                if alpha_date and m.group(1) != alpha_date:
                    stale.append(f"the gain pair is dated {m.group(1)}, the alpha table {alpha_date}")
                if abs(float(m.group(2)) - gain_s) > 1e-9 or abs(float(m.group(3)) - gain_h) > 1e-9:
                    stale.append(f"'({m.group(1)}: {m.group(2)}pp and {m.group(3)}pp)': the "
                                 f"shipped row over alpha 0 reads {gain_s:+.1f}pp on stripped@1 "
                                 f"and {gain_h:+.1f}pp on heading@1")
            m = need(self._ALPHA_MARGIN_RE, aprose,
                     "'A over B is ~Npp on the heading arm and ~Mpp on the stripped arm (DATE)'")
            if m:
                a1, a2 = float(m.group(1)), float(m.group(2))
                if a1 != shipped_a or a2 not in arows:
                    stale.append(f"'{m.group(1)} over {m.group(2)}': the shipped alpha is "
                                 f"{shipped_a} and the table's rows are {sorted(arows)}")
                else:
                    margin_h = arows[a1][0] - arows[a2][0]
                    margin_s = arows[a1][1] - arows[a2][1]
                    if abs(margin_h - int(m.group(3))) > 0.5 or abs(margin_s - int(m.group(4))) > 0.5:
                        stale.append(f"'~{m.group(3)}pp on the heading arm and ~{m.group(4)}pp on "
                                     f"the stripped arm': the rows read {margin_h:.1f}pp and "
                                     f"{margin_s:.1f}pp")
                if alpha_date and m.group(5) != alpha_date:
                    stale.append(f"the margin reading is dated {m.group(5)}, the alpha table {alpha_date}")

        assert not stale, (
            "a sentence beside a pasted recall table (scripts/recall_eval.py, "
            "tools/cc/hooks/_recall.py) restates a cell the table no longer carries, or "
            "carries a date its table does not; refresh the sentence and its date with the "
            "paste (and re-sync the vendor mirror for the hook):\n  " + "\n  ".join(stale)
        )

    def test_min_kept_is_refused_where_it_would_be_ignored(self, eval_mod):
        for argv in (["--min-kept", "3"], ["--sweep", "--min-kept", "0"],
                     ["--alpha-sweep", "--min-kept", "3"]):
            with pytest.raises(SystemExit) as exc:
                eval_mod.main(argv)
            assert exc.value.code == 2, argv

    def test_the_two_pasted_tables_agree_on_the_shipped_cell(self, eval_mod):
        """The MIN_STRIPPED_TOKENS row for the shipped floor and the STRIP_FRACTION
        row for the shipped fraction describe ONE configuration, so their four
        shared cells are identical or one table was regenerated without the
        other. Sub-second and sweep-free: the check that catches the split."""
        _, min_rows = self._pasted_min_kept_rows()
        _, strip_rows = self._pasted_strip_rows()
        assert eval_mod.MIN_STRIPPED_TOKENS in min_rows, sorted(min_rows)
        assert eval_mod.STRIP_FRACTION in strip_rows, sorted(strip_rows)
        arm, too_short, h1, s1 = min_rows[eval_mod.MIN_STRIPPED_TOKENS]
        _, arm2, too_short2, h1_2, s1_2, _ = strip_rows[eval_mod.STRIP_FRACTION]
        assert (arm, too_short, h1, s1) == (arm2, too_short2, h1_2, s1_2), (
            "the MIN_STRIPPED_TOKENS and STRIP_FRACTION tables in scripts/recall_eval.py "
            "disagree on the shipped cell -- one was regenerated without the other. "
            "Regenerate both from the same tree (`--sweep`, then `--sweep --min-kept N` "
            "per row), LAST in any commit that also edits memory/ or docs/."
        )

    @pytest.mark.slow
    @pytest.mark.timeout(300)
    def test_the_pasted_strip_table_is_within_tolerance_of_a_fresh_sweep(self, eval_mod, corpus,
                                                                         report):
        block, pasted = self._pasted_strip_rows()
        fresh = {r["fraction"]: r for r in eval_mod.sweep(REPO_ROOT, corpus)}
        assert set(pasted) == set(fresh), (sorted(pasted), sorted(fresh))
        stale = []
        for f, (tok, arm, too_short, h1, s1, delta) in sorted(pasted.items()):
            r = fresh[f]
            stale += [d for d in (
                self._count_drift(f"fraction {f} tokens stripped", tok, r["tokens_stripped"]),
                self._count_drift(f"fraction {f} arm", arm, r["n"]),
                self._count_drift(f"fraction {f} too_short", too_short, r["too_short"]),
                self._rate_drift(f"fraction {f} paired heading@1", h1, r["paired_heading_at_1"]),
                self._rate_drift(f"fraction {f} stripped@1", s1, r["control_at_1"]),
                self._rate_drift(f"fraction {f} delta", delta,
                                 r["control_at_1"] - r["paired_heading_at_1"]),
            ) if d]
        m = STRIP_PROVENANCE_RE.search(block)
        assert m, "the STRIP_FRACTION table lost its provenance line (corpus size)"
        stale += [d for d in (self._count_drift("corpus", int(m.group(1)), len(corpus)),) if d]
        # The heading count the prose divides the arm by ("A of B headings") is
        # the one figure beside this table no cell carries; it is the heading
        # arm the sweep was paired against, banded like the corpus size.
        m = self._MAXIMISES_RE.search(block_prose(block))
        assert m, "the strip paragraph lost its 'MAXIMISES THE ARM: A of B headings' sentence"
        stale += [d for d in (self._count_drift("heading arm (strip prose)", int(m.group(2)),
                                                report["arms"]["heading"]["n"]),) if d]
        assert not stale, (
            "the STRIP_FRACTION table in scripts/recall_eval.py has drifted from the live "
            "corpus; regenerate it with `python3 scripts/recall_eval.py --sweep` LAST in "
            "this commit (after every memory/ and docs/ edit) and re-date its provenance "
            "line:\n  " + "\n  ".join(stale)
        )

    @pytest.mark.slow
    @pytest.mark.timeout(300)
    def test_the_pasted_min_kept_table_is_within_tolerance_of_fresh_sweeps(self, eval_mod, corpus):
        _, pasted = self._pasted_min_kept_rows()
        assert eval_mod.MIN_STRIPPED_TOKENS in pasted, sorted(pasted)
        assert set(pasted) >= self._MIN_ROWS_DOCUMENTED, (
            f"the MIN_STRIPPED_TOKENS table lost a row: parsed {sorted(pasted)}"
        )
        stale = []
        for k, (arm, too_short, h1, s1) in sorted(pasted.items()):
            r = eval_mod.sweep(REPO_ROOT, corpus, fractions=(eval_mod.STRIP_FRACTION,),
                               min_kept=k)[0]
            stale += [d for d in (
                self._count_drift(f"min kept {k} arm", arm, r["n"]),
                self._count_drift(f"min kept {k} too_short", too_short, r["too_short"]),
                self._rate_drift(f"min kept {k} paired heading@1", h1, r["paired_heading_at_1"]),
                self._rate_drift(f"min kept {k} stripped@1", s1, r["control_at_1"]),
            ) if d]
        assert not stale, (
            "the MIN_STRIPPED_TOKENS table in scripts/recall_eval.py has drifted from the "
            "live corpus; regenerate each row with `python3 scripts/recall_eval.py --sweep "
            "--min-kept N` (its 0.15 line) LAST in this commit, and re-date the block:\n  "
            + "\n  ".join(stale)
        )


class TestTheAlphaSweepRegeneratesTheRankerTable:
    """`--alpha-sweep` is the source of the LENGTH_NORM_ALPHA comment table in
    tools/cc/hooks/_recall.py. That table was typed once from a one-off script
    and aged silently for forty documents; this is what ties it to the
    instrument (DEF-679's closure owed exactly this).
    """

    def test_the_shipped_alpha_row_matches_the_report(self, eval_mod, corpus, report):
        rows = eval_mod.alpha_sweep(REPO_ROOT, corpus, alphas=(_recall.LENGTH_NORM_ALPHA,))
        assert rows[0]["alpha"] == _recall.LENGTH_NORM_ALPHA
        assert rows[0]["heading_at_1"] == report["arms"]["heading"]["rates"]["control_at_1"]
        assert rows[0]["heading_at_k"] == report["arms"]["heading"]["rates"]["control_at_k"]
        assert rows[0]["stripped_at_1"] == report["arms"]["stripped"]["rates"]["control_at_1"]
        assert rows[0]["lost_to_bigger_doc"] == 0, (
            "the shipped exponent exists to remove the larger-vocabulary bias; "
            "a nonzero count here is the regression the table was built to show"
        )

    def test_the_constant_is_restored_on_every_exit(self, eval_mod, small_corpus, monkeypatch):
        original = _recall.LENGTH_NORM_ALPHA
        eval_mod.alpha_sweep(REPO_ROOT, small_corpus, alphas=(0.0, 1.0))
        assert _recall.LENGTH_NORM_ALPHA == original

        def boom(*_a, **_k):
            raise RuntimeError("mid-sweep")
        monkeypatch.setattr(eval_mod, "evaluate_arm", boom)
        with pytest.raises(RuntimeError):
            eval_mod.alpha_sweep(REPO_ROOT, small_corpus, alphas=(1.0,))
        assert _recall.LENGTH_NORM_ALPHA == original, (
            "a sweep that raised left the shared module patched; every later "
            "recall() in this session would rank under the wrong exponent"
        )

    @pytest.mark.slow
    @pytest.mark.timeout(300)
    def test_alpha_zero_shows_the_bias_the_exponent_corrects(self, fresh_alpha_rows):
        """The last column is the point of the table: with no normalisation,
        heading queries lose to bigger documents; with the shipped exponent
        they do not. Both directions, so the column cannot go vacuous.

        Re-scoped 2026-09-04 when the focus tie-break landed: at alpha 0 the
        column fell from 108 to 2 (the rest were exact ties the path name broke)
        and heading@1 now TIES the shipped value there, so the exponent's
        measured gain is read on the stripped arm, where it survives. The
        heading arm is held at >= so a future corpus where alpha 0 pulls ahead
        reds here instead of passing unnoticed."""
        by_alpha = {r["alpha"]: r for r in fresh_alpha_rows}
        assert by_alpha[0.0]["lost_to_bigger_doc"] > 0, (
            "no heading query loses to a bigger document at alpha 0 any more (it was 108 "
            "before the focus tie-break and 2 after). This is not a corpus collapse: it "
            "means the exponent has no remaining measured job on the HEADING arm. Re-argue "
            "LENGTH_NORM_ALPHA on the stripped arm's gain alone, or retire it -- do not "
            "loosen this assertion."
        )
        assert by_alpha[_recall.LENGTH_NORM_ALPHA]["lost_to_bigger_doc"] == 0
        assert by_alpha[_recall.LENGTH_NORM_ALPHA]["stripped_at_1"] > by_alpha[0.0]["stripped_at_1"], (
            "the shipped exponent no longer beats alpha 0 on the stripped arm -- that was "
            "its last measured gain after the focus tie-break; re-argue or retire it"
        )
        assert by_alpha[_recall.LENGTH_NORM_ALPHA]["heading_at_1"] >= by_alpha[0.0]["heading_at_1"]

    def test_the_shipped_alpha_always_has_a_row(self, eval_mod, small_corpus):
        """A recalibration off the grid must not make the table silent about the
        value it justifies: the shipped alpha is unioned into any sweep."""
        rows = eval_mod.alpha_sweep(REPO_ROOT, small_corpus, alphas=(0.0, 1.0))
        assert _recall.LENGTH_NORM_ALPHA in {r["alpha"] for r in rows}

    @pytest.mark.slow
    @pytest.mark.timeout(300)
    def test_the_shipped_alpha_is_within_a_point_of_the_sweep_peak(self, fresh_alpha_rows):
        """The calibration claim itself, re-derived: the shipped exponent is the
        measured peak on heading@1 (within 1pp -- the corpus grows every session
        and a 0.3pp lead changing hands is noise, a clear better value is not).
        Reads the module's one sweep (~30s idle; timeout widened because the
        global 60s thread-timeout has taken a whole suite down under load)."""
        rows = fresh_alpha_rows
        by_alpha = {r["alpha"]: r for r in rows}
        peak = max(rows, key=lambda r: r["heading_at_1"])
        shipped = by_alpha[_recall.LENGTH_NORM_ALPHA]
        assert shipped["heading_at_1"] >= peak["heading_at_1"] - 0.01, (
            f"alpha {peak['alpha']} now beats the shipped {_recall.LENGTH_NORM_ALPHA} on "
            f"heading@1 ({peak['heading_at_1']:.1%} vs {shipped['heading_at_1']:.1%}); "
            "re-calibrate and regenerate the table with --alpha-sweep"
        )

    @pytest.mark.slow
    @pytest.mark.timeout(300)
    def test_the_pasted_table_is_within_tolerance_of_a_fresh_sweep(self, fresh_alpha_rows, corpus):
        """The fix for 'the table aged silently' has to ship a check that it is
        current, or it is the same defect with a newer date. Tolerance, not
        equality: the corpus grows every session and a point of drift is
        expected aging; three points is a stale table."""
        block = alpha_block()
        pasted = {
            float(m.group(1)): (float(m.group(2)) / 100, float(m.group(3)) / 100,
                                float(m.group(4)) / 100, int(m.group(5)))
            for m in re.finditer(
                r"^#:\s+(\d\.\d\d)\s+(\d+\.\d)%\s+(\d+\.\d)%\s+(\d+\.\d)%\s+(\d+)",
                block, re.M)
        }
        fresh = {r["alpha"]: r for r in fresh_alpha_rows}
        assert set(pasted) == set(fresh), (pasted.keys(), fresh.keys())
        stale = []
        for alpha, (h1, s1, hk, lost) in pasted.items():
            f = fresh[alpha]
            for name, was, now in (("heading@1", h1, f["heading_at_1"]),
                                   ("stripped@1", s1, f["stripped_at_1"]),
                                   ("heading@k", hk, f["heading_at_k"])):
                drift = rate_drift(f"alpha {alpha}: {name}", was, now)
                if drift:
                    stale.append(drift)
            if alpha > 0 and lost != f["lost_to_bigger_doc"]:
                stale.append(f"alpha {alpha}: lost-to-bigger pasted {lost}, fresh {f['lost_to_bigger_doc']}")
            elif alpha == 0 and abs(lost - f["lost_to_bigger_doc"]) > 0.1 * max(1, f["lost_to_bigger_doc"]):
                # the one cell the prose quotes twice and the CHANGELOG once
                stale.append(f"alpha 0: lost-to-bigger pasted {lost}, fresh {f['lost_to_bigger_doc']} (>10% off)")
        # The header counts the prose leans on, against the same fresh sweep.
        n_h, n_s = fresh_alpha_rows[0]["n_heading"], fresh_alpha_rows[0]["n_stripped"]
        m = ALPHA_PROVENANCE_RE.search(block_prose(block))
        assert m, "the table's provenance line (corpus size, arm sizes) is missing"
        for name, pasted_n, fresh_n in (("corpus", int(m.group(1)), len(corpus)),
                                        ("heading arm", int(m.group(2)), n_h),
                                        ("stripped arm", int(m.group(3)), n_s)):
            drift = count_drift(name, pasted_n, fresh_n)
            if drift:
                stale.append(drift)
        assert not stale, (
            "the LENGTH_NORM_ALPHA table in tools/cc/hooks/_recall.py has drifted from "
            "the live corpus; regenerate it with `python3 scripts/recall_eval.py "
            "--alpha-sweep`, keep the hand-written annotations (the three `<-` markers "
            "AND the alpha-0 row's parenthetical with the pre-2026-09-04 path-name-key "
            "numbers), and re-sync the vendor mirror:\n  " + "\n  ".join(stale)
        )
        assert "path-name tie-break" in block, (
            "the alpha-0 row lost its parenthetical (the old-key numbers 60.2% / 62.2% / "
            "94.8% / 108) -- a re-paste dropped it. It is the only tracked record of the "
            "numbers the calibration story rests on; put it back beside the fresh row."
        )

    def test_alpha_sweep_refuses_flags_it_would_ignore(self, eval_mod):
        for extra in (["--query", "x"], ["--misses"], ["--sweep"]):
            with pytest.raises(SystemExit) as exc:
                eval_mod.main(["--alpha-sweep", *extra])
            assert exc.value.code == 2

    def test_recall_py_points_at_the_sweep_beside_its_table(self, eval_mod):
        """The pointer is the whole reason the table can be trusted: the file a
        session opens to change LENGTH_NORM_ALPHA must say where its numbers
        come from, and the rows it carries must be the sweep's alphas."""
        block = alpha_block()
        assert "scripts/recall_eval.py --alpha-sweep" in block
        for alpha in eval_mod.ALPHA_SWEEP:
            assert re.search(rf"^#:\s+{alpha:.2f}\s", block, re.M), (
                f"the pasted table has no row for alpha {alpha:.2f}; regenerate it"
            )


class TestIsolation:
    def test_script_has_no_espalier_import(self):
        src = SCRIPT.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+espalier\b", src, re.M)


class TestTaskArm:
    """DEF-699: the task-shaped arm. A lane's task text and the catalog entry
    that would have saved it share almost no words, and on 2026-09-06 seven
    such queries recalled none of the four applicable entries. The instrument
    now carries that population as its fourth labelled arm so the claim is a
    number printed on every run rather than a one-day probe. As with the other
    arms, no rate or rank is pinned here. The labels are facts about the lanes:
    four came from the reviews of 2026-09-06, three from an entry a hazard-word
    recall surfaced and the lane's review used (ranker-reachable by
    construction, so the rate is an optimistic bound -- the arm's own comment
    says so per row); the arm reads from one owner file, its filed rows
    ratchet, and it grows one row per lane at handoff."""

    def test_the_loader_reads_a_named_constant(self, eval_mod):
        from tests.test_recall import _TASK_ARM
        rows = eval_mod.load_labelled_arm("_TASK_ARM")
        assert rows == tuple(_TASK_ARM)
        assert eval_mod.load_labelled_arm("_PARAPHRASE_ARM") == eval_mod.load_paraphrase_arm()

    def test_the_task_arm_is_in_the_report_with_the_committed_rows(self, report):
        from tests.test_recall import _TASK_ARM
        assert "task" in report["arms"], sorted(report["arms"])
        assert report["arms"]["task"]["n"] == len(_TASK_ARM)
        assert report["arms"]["task"]["distinct_queries"] == len({q for q, _ in _TASK_ARM})

    def test_the_filed_rows_ratchet_and_the_arm_may_only_grow(self):
        """A count floor lets a later session drop every miss and keep the
        rate up; the filed rows are a literal snapshot the arm must contain."""
        from tests.test_recall import _TASK_ARM, _TASK_ARM_FILED
        assert _TASK_ARM_FILED <= set(_TASK_ARM), sorted(_TASK_ARM_FILED - set(_TASK_ARM))
        # Twelve filed on 2026-09-11, four by the 2026-09-12 recall lane, two by
        # the 2026-09-13 group-9 lane. Bump this deliberately when a lane extends
        # the ratchet; never lower it.
        assert len(_TASK_ARM_FILED) == 39  # 2026-09-24: +3, DEF-922 (the wall-clock rule derived by a contract: the measuring instrument, presence-not-absence, derive the list). 2026-09-20: +1, TP-452 1-B (the escaped-pipe edge under the rebuild assembler's cell reads). 2026-09-16: +2, DEF-827 (a discovered command read as the command it names); +1, DEF-820 (the BOM census guard on dataflow). 2026-09-15: +7, lane 2 (the remove/relocate operand class); +4, lane 5 (paths as paths); +3, lanes 7 and 9 (the uninstall report's witness and the backup ladder; four walk hazards)

    def test_task_labels_are_the_committed_rows_and_exact_sources(self, eval_mod, corpus):
        from tests.test_recall import _TASK_ARM
        labels = eval_mod.task_labels()
        assert [(lab.query, lab.expected) for lab in labels] == list(_TASK_ARM)
        sources = {doc.source for doc in corpus}
        missing = [lab.expected for lab in labels if lab.expected not in sources]
        assert not missing, f"a task label names a source the corpus does not have: {missing}"
        arm = next(a for a in eval_mod.build_arms(corpus) if a.name == "task")
        assert arm.prefix_match is False, "task labels are exact sources, not principle prefixes"

    def test_an_absent_task_constant_is_loud_not_silent(self, eval_mod, tmp_path, capsys):
        src = tmp_path / "test_recall.py"
        src.write_text("_PARAPHRASE_ARM = ((\"q\", \"1.\"),)\n", encoding="utf-8")
        assert eval_mod.load_labelled_arm("_TASK_ARM", src) == ()
        assert "_TASK_ARM" in capsys.readouterr().err

    def test_render_prints_a_task_row_and_names_its_misses(self, report, eval_mod):
        text = eval_mod.render_text(report, show_misses=True)
        assert re.search(r"(?m)^task\s+\d+\s", text), text[:600]
        assert re.search(r"(?m)^task: \d+ front-door misses", text)
        # The caveat the docstring states travels into the table the operator
        # actually reads, beside the distinct-query count.
        n_q = report["arms"]["task"]["distinct_queries"]
        assert f"n counts labels over {n_q} distinct queries" in text
        assert "do not read this rate against theirs" in text

    def test_the_docstring_counts_the_arms_it_builds(self, eval_mod, corpus):
        """Derived from build_arms, so a fifth arm reds here when the prose is
        NOT updated -- a literal 'FOUR' would red on the fix instead."""
        arms = eval_mod.build_arms(corpus)
        head = SCRIPT.read_text(encoding="utf-8").split("from __future__", 1)[0]
        assert f"THE {_NUMBER_WORDS[len(arms)].upper()} ARMS" in head
        block = head.split("ARMS\n", 1)[1].split("Stdlib-only", 1)[0]
        for arm in arms:
            assert re.search(rf"(?m)^  {re.escape(arm.name)}\s", block), arm.name

    def test_a_dead_task_label_is_loud_in_the_reporter(self, eval_mod, corpus, tmp_path, capsys):
        """A renamed SHARP_EDGES heading turns an exact-source label into a
        permanent miss that reads as a ranking regression in a --json diff; the
        reporter says so on stderr, not only pytest."""
        src = tmp_path / "test_recall.py"
        src.write_text(
            "_PARAPHRASE_ARM = ()\n"
            "_TASK_ARM = ((\"a task text\", \"docs/SHARP_EDGES.md :: Gone Heading\"),)\n",
            encoding="utf-8",
        )
        arms = eval_mod.build_arms(corpus, labelled_arm_source=src)
        assert [a.name for a in arms][-1] == "task"
        err = capsys.readouterr().err
        assert "Gone Heading" in err and "renamed heading" in err
