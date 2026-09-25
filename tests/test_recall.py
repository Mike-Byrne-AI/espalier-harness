"""Rank / suppress / pointer-recall gate for the pull-recall engine (TP-167).

⚠ READ THE DEF-609 BLOCK AT THE END OF THIS FILE BEFORE TRUSTING THE PARAGRAPH BELOW.
Suppression is proven only for OUT-OF-VOCABULARY queries; ordinary off-topic English is
not suppressed at all, and no floor fixes that (nine mechanisms measured). The paragraph
below describes what this file pinned before that was discovered, and is kept because the
tests it describes still exist and still pass -- not because its claim is complete.

`_recall.py` proves it is a real ranking engine, not a pointer that always returns
*something*. The load-bearing guard is SUPPRESSION: a naive top-1 retriever always has
some highest-scoring doc, so a nonsense or near-miss query "recalls" an irrelevant
snippet and trains the operator to distrust `/recall`. Without the half-corpus floor a
near-miss of ubiquitous tokens would surface a spurious hit; this file guards against
that with two negatives (pure nonsense AND a near-miss of common tokens both return
``[]``) and a positive (a distinctive query returns the right doc).

The rank-not-point proof (TP-105 earn-the-gate discipline): the ranking is driven by
``idf_weight`` -- monkeypatch it to a constant and the higher-IDF doc no longer wins,
which proves the engine RANKS rather than POINTS. Pointer-recall (167-D) is tested
separately because TP-166's exemplars have no body: ``recall("new hook")`` must surface
``GEN-NEW-HOOK``'s ``source`` pointer, not whichever doc merely says "hook" most often.

Note: ``EXEMPLAR_MAP`` docs are loaded ONLY in the harness's own checkout (TP-168 #3:
``_load_corpus`` gates them behind ``is_self_host_repo(root)`` so an adopter's first
/recall does not see espalier/scanners + task-packs pointers). The synthetic-corpus
mechanics tests run against non-self-host tmp roots (and also monkeypatch the map to
``{}``) so N == len(docs); pointer-recall and the live-corpus smoke tests use the real
map against the self-host repo root.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _hook_utils  # noqa: E402
import _recall  # noqa: E402

from _git_oracle import require_tracked_paths  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def _synth(tmp_path, monkeypatch, docs: dict[str, str]) -> Path:
    """Build a synthetic memory/ corpus under tmp_path and blank EXEMPLAR_MAP so the
    doc count N == len(docs) (deterministic floor/ranking, no module-level padding)."""
    monkeypatch.setattr(_recall, "EXEMPLAR_MAP", {})
    mem = tmp_path / "memory"
    mem.mkdir()
    for name, text in docs.items():
        (mem / name).write_text(text, encoding="utf-8")
    return tmp_path


def _two_candidate_corpus(tmp_path, monkeypatch) -> Path:
    # 'zeta' df=1 (high IDF, only in high.md); 'omega' df=2 (lower IDF, low+extra).
    # A query "zeta omega" must rank high.md (rarer match) first WHEN idf is real.
    return _synth(tmp_path, monkeypatch, {
        "high.md": "# High\nzeta marker alpha\n",
        "low.md": "# Low\nomega marker beta\n",
        "extra.md": "# Extra\nomega padding gamma\n",
        "pad1.md": "# Pad1\ndelta epsilon\n",
        "pad2.md": "# Pad2\nkappa lambda\n",
    })


# ── live-corpus smoke (the §6 pass-criteria) ──────────────────────────────────

def test_live_corpus_recalls_speedbump_atlas_top1():
    """A real topical query returns the right memory/ doc as the top hit, won by a
    score MARGIN (not a reverse=True source tie-break). 'speedbump cap exemption'
    used to tie at the top (gap 0.0); 'speedbump chokepoint' gives a clear gap so
    the assertion proves ranking, not tie ordering (TP-168 168-F)."""
    hits = _recall.recall("speedbump chokepoint", REPO_ROOT, top=2)
    assert hits, "expected a hit for a clearly topical query"
    assert hits[0].source == "memory/speedbump-checkpoint-atlas.md"
    assert len(hits) > 1 and hits[0].score > hits[1].score, "top-1 must win by margin"


def test_live_corpus_suppresses_pure_nonsense():
    """A pure-nonsense query (no corpus tokens) suppresses -- never a spurious top-1.
    Uses consonant gibberish that appears in no doc; an "ordinary" word like "topic"
    IS a corpus token (it appears in generative-injection-atlas.md) and would not."""
    assert _recall.recall("zqxwvk jmpfbn wlgrtz", REPO_ROOT) == []


# ── 167-D: pointer-recall over TP-166's pull-only exemplars ───────────────────

def test_pointer_recall_surfaces_gen_new_hook():
    """recall("new hook") surfaces GEN-NEW-HOOK's source pointer (pointer-recall, not
    body-recall) -- the exemplar's trigger match beats any doc that merely says 'hook'."""
    hits = _recall.recall("new hook", REPO_ROOT)
    assert hits, "expected the exemplar trigger to produce a hit"
    assert "GEN-NEW-HOOK" in hits[0].snippet
    assert "tools/cc/hooks/" in hits[0].source  # the pointer, not a doc body


def test_diagnostic_query_does_not_hijack_to_authoring_pointer():
    """T7: a regression/diagnostic query that lexically matches a GEN-NEW-*
    trigger ('why did the new scanner integration regress') must NOT surface
    the authoring pointer top-1 — the diagnostic-framing gate suppresses the
    trigger floor-exemption. The relevant doc wins instead."""
    hits = _recall.recall("why did the new scanner integration regress", REPO_ROOT, top=1)
    assert hits, "expected at least one hit"
    assert "GEN-NEW-SCANNER" not in hits[0].snippet, (
        f"diagnostic query hijacked by authoring pointer: {hits[0].snippet!r}"
    )


def test_authoring_query_still_surfaces_new_scanner_pointer():
    """T7 (no-regression): a genuine authoring query ('draft a new scanner
    module') STILL surfaces the GEN-NEW-SCANNER pointer top-1 — no diagnostic
    framing, so the floor-exemption holds and the push-side intent is preserved."""
    hits = _recall.recall("draft a new scanner module", REPO_ROOT, top=1)
    assert hits and "GEN-NEW-SCANNER" in hits[0].snippet, (
        f"authoring query lost the new-scanner pointer: "
        f"{hits[0].snippet if hits else '<no hit>'}"
    )


# ── 168-B: TP-166 exemplars are self-host-gated (adopter must not see them) ───

def test_adopter_repo_does_not_leak_exemplar_pointers(tmp_path, monkeypatch):
    """An adopter checkout (NOT self-host) must not surface harness-dev exemplar
    pointers (espalier/scanners, task-packs/) on /recall. The GATE -- not corpus
    emptiness -- is what suppresses them: with the real detector the same query
    returns []; force the gate open and the SAME tmp root leaks GEN-NEW-HOOK
    (the exact pre-fix adopter leak this fix closes)."""
    assert _recall.EXEMPLAR_MAP, "real EXEMPLAR_MAP must be populated for this to bite"
    assert not _recall.is_self_host_repo(tmp_path), "tmp_path must not look self-host"

    # real detector: adopter sees nothing -- the gate closes the leak.
    assert _recall.recall("new hook", tmp_path) == []

    # force the gate open -> the same tmp root would surface the exemplar pointer.
    monkeypatch.setattr(_recall, "is_self_host_repo", lambda root: True)
    leaked = _recall.recall("new hook", tmp_path)
    assert leaked and "GEN-NEW-HOOK" in leaked[0].snippet
    assert "tools/cc/hooks/" in leaked[0].source  # an Espalier-internal pointer


def test_seeded_sharp_edges_scaffold_is_not_retrievable(tmp_path, monkeypatch):
    """`init` seeds docs/SHARP_EDGES.md near-empty. Indexing its "write your
    first edge here" section makes /recall answer a real footgun question with
    the placeholder -- a confident wrong hit, strictly worse than the honest
    no-match this engine is built to give.

    The banner now points every adopter at /recall for footguns, so this is the
    retrieval end of that promise: an empty catalog must return nothing rather
    than return the invitation to fill it.
    """
    monkeypatch.setattr(_recall, "EXEMPLAR_MAP", {})
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    seed = REPO_ROOT / "espalier" / "assets" / "seed" / "SHARP_EDGES.md"
    (docs_dir / "SHARP_EDGES.md").write_text(
        seed.read_text(encoding="utf-8"), encoding="utf-8"
    )

    corpus = _recall._load_corpus(tmp_path)
    assert corpus == [], (
        f"the seeded scaffold entered the recall corpus: {[d.source for d in corpus]}"
    )
    assert _recall.recall("sharp edge", tmp_path) == []


def test_a_real_edge_in_the_seeded_file_is_retrievable(tmp_path, monkeypatch):
    """The positive arm -- suppression must be scoped to the placeholder, not to
    the file. An operator who writes one real edge gets it back, placeholder
    still present or not."""
    monkeypatch.setattr(_recall, "EXEMPLAR_MAP", {})
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    seed = REPO_ROOT / "espalier" / "assets" / "seed" / "SHARP_EDGES.md"
    (docs_dir / "SHARP_EDGES.md").write_text(
        seed.read_text(encoding="utf-8")
        + "\n## zsh does not word-split unquoted parameters\n\n"
        "`rm -- $LIST` in zsh passes ONE filename; loop per item instead.\n",
        encoding="utf-8",
    )

    sources = [d.source for d in _recall._load_corpus(tmp_path)]
    assert sources == ["docs/SHARP_EDGES.md :: zsh does not word-split unquoted parameters"]
    hits = _recall.recall("zsh word-split unquoted", tmp_path)
    assert hits and "zsh" in hits[0].snippet


def test_indexes_failure_modes_matches_the_corpus(tmp_path, monkeypatch):
    """DERIVED, not restated. `session_start._footgun_pointer` asks this
    predicate whether to promise /recall for docs/FAILURE_MODES.md. If the
    predicate and `_load_corpus` ever disagree, the banner goes back to
    advertising a retrieval that returns [] -- so pin them to each other on a
    tree that HAS the file, in both directions."""
    monkeypatch.setattr(_recall, "EXEMPLAR_MAP", {})
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "FAILURE_MODES.md").write_text(
        (REPO_ROOT / "espalier" / "assets" / "docs" / "FAILURE_MODES.md").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )

    def fm_sources(root):
        return [d.source for d in _recall._load_corpus(root)
                if d.source.startswith("docs/FAILURE_MODES.md")]

    # adopter-shaped: predicate says no, corpus has none
    assert _recall.indexes_failure_modes(tmp_path) is False
    assert fm_sources(tmp_path) == []

    # force the predicate open: the corpus must follow it, not a second copy
    # of the same rule
    monkeypatch.setattr(_recall, "is_self_host_repo", lambda root: True)
    assert _recall.indexes_failure_modes(tmp_path) is True
    assert fm_sources(tmp_path), (
        "the predicate says FAILURE_MODES is indexed but _load_corpus produced "
        "none -- the two have diverged"
    )


#: HAND-WRITTEN on purpose. The obvious version of this test derived the
#: expectation from ``_FM_COINAGE_TWINS`` -- and that map is PART OF WHAT CAN
#: SILENTLY GROW, so adding three skips moved the expectation with the subject
#: and the assertion stayed green. Driven, in the change that added this test.
#: That is the population-is-the-subject shape; the remedy this repo already
#: landed for it (DEF-603) is a hand-kept roster compared BOTH directions, so
#: the expectation cannot move when the thing under test does.
#: Adding a coinage to the skip map must red HERE and be resolved by editing
#: this roster deliberately -- that edit is the review moment.
_EXPECTED_INDEXED_COINAGE_NUMBERS = frozenset({
    "1.3", "1.6", "1.7", "1.10", "1.11", "1.12",
})


def test_failure_mode_coverage_matches_its_adjudicated_roster():
    """The sibling assertion above is ``assert fm_sources(tmp_path)`` -- bare
    truthiness, a presence floor that cannot tell 6-of-13 from 13-of-13 and
    would sit green if the coinage walk narrowed to a single survivor.

    That matters more than it looks: the SessionStart banner advertises
    ``docs/FAILURE_MODES.md`` as retrievable via ``/recall``, and this walk is
    what backs the promise. A narrowing turns the banner into an overclaim while
    the only existing pin stays satisfied.

    Both directions, against a roster that does NOT derive from the skip map.
    """
    text = (REPO_ROOT / "docs" / "FAILURE_MODES.md").read_text(encoding="utf-8")
    coinages = _recall._load_failure_mode_coinages(text)
    assert coinages, "the section-1 coinage walk found nothing -- the walk broke"

    indexed = {
        d.source.split(" :: ", 1)[1].split()[0]
        for d in _recall._load_corpus(REPO_ROOT)
        if d.source.startswith("docs/FAILURE_MODES.md ::")
    }
    assert indexed == _EXPECTED_INDEXED_COINAGE_NUMBERS, (
        "the FAILURE_MODES slice of the recall corpus moved.\n"
        f"  expected but missing: {sorted(_EXPECTED_INDEXED_COINAGE_NUMBERS - indexed)}\n"
        f"  indexed unexpectedly: {sorted(indexed - _EXPECTED_INDEXED_COINAGE_NUMBERS)}\n"
        "A coinage newly skipped via _FM_COINAGE_TWINS reds here BY DESIGN -- "
        "update this roster deliberately, with the reason, rather than letting "
        "coverage drift. Do not re-derive it from the skip map: that is what "
        "made the first version of this test unable to fail."
    )
    # The skip map must stay ACCOUNTED FOR, not merely non-empty: every coinage
    # is either indexed or explicitly twinned, with no third silent state.
    all_numbers = {title.split()[0] for title, _ in coinages}
    accounted = _EXPECTED_INDEXED_COINAGE_NUMBERS | set(_recall._FM_COINAGE_TWINS)
    assert all_numbers == accounted, (
        f"section-1 coinages neither indexed nor twinned: {sorted(all_numbers - accounted)}; "
        f"accounted-for numbers that no longer exist: {sorted(accounted - all_numbers)}"
    )


def test_self_host_repo_is_detected_for_live_root():
    """Sanity: the live repo root IS self-host, so the exemplar corpus loads there
    (the positive half of the 168-B gate -- pointer-recall keeps working in-harness)."""
    assert _recall.is_self_host_repo(REPO_ROOT)


# ── synthetic-corpus mechanics (deterministic N via blanked EXEMPLAR_MAP) ──────

def test_ranks_distinctive_term_top1(tmp_path, monkeypatch):
    root = _synth(tmp_path, monkeypatch, {
        "alpha.md": "# Alpha\nflux capacitor delorean\n",
        "beta.md": "# Beta\nwidget gadget thing\n",
        "gamma.md": "# Gamma\nwidget gadget gizmo\n",
    })
    hits = _recall.recall("flux capacitor", root)
    assert hits and hits[0].source == "memory/alpha.md"


def test_two_candidate_ranks_higher_idf_first(tmp_path, monkeypatch):
    root = _two_candidate_corpus(tmp_path, monkeypatch)
    hits = _recall.recall("zeta omega", root)
    assert hits and hits[0].source == "memory/high.md"  # 'zeta' (df=1) outweighs 'omega' (df=2)


def test_rank_not_point_idf_weight_is_load_bearing(tmp_path, monkeypatch):
    """Earn the gate: with real IDF the rarer-term doc wins; flatten idf_weight to a
    constant and the winner changes -- proving the engine RANKS, not points."""
    root = _two_candidate_corpus(tmp_path, monkeypatch)
    real_top = _recall.recall("zeta omega", root)[0].source
    assert real_top == "memory/high.md"

    monkeypatch.setattr(_recall, "idf_weight", lambda df, n: 1.0)
    const_top = _recall.recall("zeta omega", root)[0].source
    assert const_top != real_top  # idf changed the winner -> it is load-bearing


def test_suppresses_near_miss_of_ubiquitous_tokens(tmp_path, monkeypatch):
    """A near-miss of tokens present in > half the docs clears nothing (the floor)."""
    root = _synth(tmp_path, monkeypatch, {
        "n1.md": "# N1\ncommon ordinary alpha\n",
        "n2.md": "# N2\ncommon ordinary beta\n",
        "n3.md": "# N3\ncommon ordinary gamma\n",
        "n4.md": "# N4\ncommon ordinary delta\n",
    })
    assert _recall.recall("common ordinary", root) == []  # both df=4 > N/2=2 -> suppress


def test_suppresses_nonsense_with_no_corpus_overlap(tmp_path, monkeypatch):
    root = _synth(tmp_path, monkeypatch, {
        "alpha.md": "# Alpha\nflux capacitor\n",
        "beta.md": "# Beta\nwidget gadget\n",
    })
    assert _recall.recall("qwxyz plughh vorpal", root) == []


def test_single_doc_corpus_recalls_topical_match(tmp_path, monkeypatch):
    """TP-174a: a brand-new adopter with exactly ONE memory/ note must still
    get a /recall hit for a distinctive term. Pre-fix the topicality floor was
    n/2.0=0.5 at N=1, so every df=1 term failed `df <= half` and the engine
    was silently dead."""
    root = _synth(tmp_path, monkeypatch, {
        "deploy.md": "# Deploy checklist\nRun migrations before flipping the feature flag.\n",
    })
    hits = _recall.recall("deploy migrations feature flag", root)
    assert hits, "single-doc corpus suppressed an exact-topic match"
    assert hits[0].source == "memory/deploy.md"


def test_empty_or_all_stopword_query_returns_empty(tmp_path, monkeypatch):
    root = _synth(tmp_path, monkeypatch, {"alpha.md": "# Alpha\nflux capacitor\n"})
    assert _recall.recall("", root) == []
    assert _recall.recall("the of and to", root) == []  # all stopwords -> no query terms


def test_hit_render_is_advisory_framed():
    hit = _recall.Hit(source="memory/x.md", snippet="A Title", score=2.0)
    rendered = hit.render()
    assert rendered.startswith("Recalled (advisory):")
    assert "memory/x.md" in rendered


def test_cli_shim_honors_claude_project_dir(tmp_path):
    """TP-174b R28: the __main__ shim resolves the corpus root via
    resolve_project_root() (CLAUDE_PROJECT_DIR), not Path.cwd(). Run the shim
    from an unrelated cwd with CLAUDE_PROJECT_DIR pointed at the live repo and
    confirm it still surfaces a corpus hit. Pre-fix (Path.cwd()) the corpus
    would resolve to the empty tmp cwd and emit nothing."""
    import os
    import subprocess

    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(REPO_ROOT)
    script = REPO_ROOT / "tools" / "cc" / "hooks" / "_recall.py"
    result = subprocess.run(
        [sys.executable, str(script), "speedbump", "chokepoint"],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), (
        "shim produced no recall hit — corpus root did not resolve from "
        "CLAUDE_PROJECT_DIR (regressed to cwd?)"
    )


# ── TP-187: FAILURE_MODES § 1 footgun coinages in the recall corpus ──────────
# Indexed self-host-only, per-### shard, and NARROWED to coinages without a
# SHARP_EDGES twin (deviation TP-187-A — § 1 overlaps the already-indexed
# SHARP_EDGES; indexing twins just adds losing duplicates).

_SAMPLE_FM = """# Failure Modes

## 1. Major named failure modes

### 1.1 Convergence theater

This coinage HAS a SHARP_EDGES twin (in _FM_COINAGE_TWINS) so it must be
SKIPPED. zorptwinalpha qqskip.

### 1.7 Gate tuning-to-HEAD blind spot

This coinage has no twin, so it is INDEXED. zorpbetagamma wwindex.

## 2. Something else

### 2.1 Not a § 1 coinage

Outside § 1 — must never be indexed. zorpsectiontwo deltdelt.
"""


def _fm_corpus(tmp_path, monkeypatch, *, self_host: bool):
    """tmp root with a synthetic FAILURE_MODES.md + a neutral memory/ doc."""
    monkeypatch.setattr(_recall, "EXEMPLAR_MAP", {})
    monkeypatch.setattr(_recall, "is_self_host_repo", lambda root: self_host)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "FAILURE_MODES.md").write_text(_SAMPLE_FM, encoding="utf-8")
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "neutral.md").write_text("# Neutral\n\npotato carrot turnip parsnip\n", encoding="utf-8")
    return tmp_path


def test_fm_helper_splits_section1_coinages_only():
    out = _recall._load_failure_mode_coinages(_SAMPLE_FM)
    titles = [t for t, _ in out]
    assert "1.1 Convergence theater" in titles
    assert "1.7 Gate tuning-to-HEAD blind spot" in titles
    assert all(t.startswith("1.") for t in titles)  # § 2 excluded
    assert len(out) == 2


def test_fm_helper_absent_section_returns_empty():
    assert _recall._load_failure_mode_coinages("# Doc\n\nno section one here\n") == []


def test_fm_self_host_indexes_non_twin_coinage_and_query_hits(tmp_path, monkeypatch):
    root = _fm_corpus(tmp_path, monkeypatch, self_host=True)
    hits = _recall.recall("zorpbetagamma wwindex", root, top=1)
    assert hits and "FAILURE_MODES.md :: 1.7" in hits[0].source


def test_fm_twin_coinage_is_skipped(tmp_path, monkeypatch):
    # 1.1 is in _FM_COINAGE_TWINS -> never indexed, even self-host.
    root = _fm_corpus(tmp_path, monkeypatch, self_host=True)
    corpus = _recall._load_corpus(root)
    assert all("1.1 Convergence" not in d.source for d in corpus)
    # Its distinctive marker recalls nothing from FAILURE_MODES.
    hits = _recall.recall("zorptwinalpha qqskip", root, top=3)
    assert all("FAILURE_MODES" not in h.source for h in hits)


def test_fm_off_topic_gibberish_suppresses_with_coinages(tmp_path, monkeypatch):
    root = _fm_corpus(tmp_path, monkeypatch, self_host=True)
    assert _recall.recall("zqxwvk jmpfbn wlgrtz", root) == []


def test_fm_strip_metaphor_drops_mental_model_keeps_technical():
    # The pure-analogy ``**Mental model.**`` block is dropped (its everyday words
    # would erode the suppress-floor); technical blocks are kept. Adversarial
    # review TP-187 suppress-floor lens.
    body = (
        "**Signature.** a structurally impossible canon formula.\n\n"
        "**Mental model.** a thermometer reading ambient air temperature.\n\n"
        "**Shapes.** the LHS and RHS diverge on a real input.\n"
    )
    stripped = _recall._strip_metaphor_sections(body)
    assert "thermometer" not in stripped and "temperature" not in stripped
    assert "formula" in stripped and "diverge" in stripped


def test_fm_live_pure_metaphor_query_does_not_surface_a_coinage():
    # The reviewer's point: probing only gibberish gave false suppress-confidence.
    # After the Mental-model strip, pure cross-domain analogy words no longer
    # surface a coinage as the #1 hit (these were live leaks before the fix).
    for q in ("air temperature room thermometer", "letterhead business cards"):
        hits = _recall.recall(q, REPO_ROOT, top=1)
        assert all("FAILURE_MODES" not in h.source for h in hits), (q, hits)


def test_fm_adopter_repo_does_not_index_failure_modes(tmp_path, monkeypatch):
    root = _fm_corpus(tmp_path, monkeypatch, self_host=False)
    corpus = _recall._load_corpus(root)
    assert all("FAILURE_MODES" not in d.source for d in corpus)


def test_fm_twin_map_pins_the_skip_set():
    # 1.11 is NOT a twin (its apparent SHARP_EDGES match is a different footgun);
    # it is indexed, not skipped (adversarial review TP-187). 1.13 (Autoimmune
    # regression) IS skipped: indexing the densest coinage eroded the suppress
    # floor (off-topic queries returned it top-1); its negative-corpus SHARP_EDGES
    # twin carries the born-weak terms instead (adversarial review).
    assert set(_recall._FM_COINAGE_TWINS) == {"1.1", "1.2", "1.4", "1.5", "1.8", "1.9", "1.13"}


def test_fm_live_indexes_exactly_the_non_twin_coinages():
    corpus = _recall._load_corpus(REPO_ROOT)
    fm = sorted(d.source.split("::")[1].strip().split()[0]
                for d in corpus if "FAILURE_MODES" in d.source)
    assert fm == ["1.10", "1.11", "1.12", "1.3", "1.6", "1.7"]


def test_fm_dense_coinage_does_not_erode_floor_for_offtopic_queries():
    # Earn-the-red for the twin-skip of 1.13: everyday-vocabulary OFF-TOPIC queries
    # whose words appear in 1.13's prose (plausible/magnitude/competent/adversary/
    # behavior/contract) must NOT return a FAILURE_MODES coinage as top-1. Against
    # an indexed 1.13 these returned "1.13 Autoimmune regression"; twin-skipped, the
    # floor holds.
    offtopic = [
        "how do I configure the budget for a plausible magnitude estimate",
        "the document contract says the behavior survives review",
        "what is the competent pattern when no adversary is present",
    ]
    for q in offtopic:
        hits = _recall.recall(q, REPO_ROOT, top=1)
        top = hits[0].source if hits else ""
        assert "FAILURE_MODES.md :: 1.13" not in top, (q, top)


def test_born_weak_query_resolves_to_sharp_edges_twin():
    # The POSITIVE side of the 1.13 twin-skip: it is only sound if the SHARP_EDGES
    # twin actually carries the autoimmune vocabulary (the §1.13 Conceptual-parent
    # fold). Bind that premise to live behavior -- delete that paragraph and this
    # reds, instead of silently dropping born-weak coverage with a green suite
    # (the unpinned-premise gap, adversarial review).
    hits = _recall.recall("born-weak autoimmune guard suppression", REPO_ROOT, top=1)
    assert hits and "must-NOT-trip negative corpus" in hits[0].source, (
        hits and hits[0].source)


def test_fm_live_non_twin_coinages_are_retrievable():
    # Each indexed coinage surfaces top-1 for its own topical query.
    cases = {
        "1.7": "tuning a gate threshold to the current HEAD state",
        "1.11": "gate reports green while the tree is red enumerates a subset of surfaces",
        "1.12": "sister predicate domain blindness one hardened the other left blind",
    }
    for cn, q in cases.items():
        hits = _recall.recall(q, REPO_ROOT, top=1)
        assert hits and f":: {cn} " in hits[0].source, (cn, q, hits and hits[0].source)


def test_fm_live_skipped_coinage_absent_from_corpus():
    corpus = _recall._load_corpus(REPO_ROOT)
    assert all("1.1 Convergence" not in d.source for d in corpus)


# ── TP-187 ranking-edge: canonical footgun wins score ties ───────────────────

def test_is_canonical_footgun_predicate():
    assert _recall._is_canonical_footgun("docs/FAILURE_MODES.md :: 1.7 Gate tuning")
    assert not _recall._is_canonical_footgun("docs/SHARP_EDGES.md :: Anything")
    assert not _recall._is_canonical_footgun("memory/x.md")


def _tie_corpus(tmp_path, monkeypatch):
    """A FM coinage and a memory doc that tie on one distinctive token. The
    memory source ("memory/...") sorts ABOVE "docs/FAILURE_MODES.md" in the old
    lexicographic tie-break, so without the edge the memory doc wins. Padding
    docs keep ``zorptiebreaker``'s df at the half-corpus floor (df=2 of n=4 <=
    2.0) so it stays topical instead of being suppressed as ubiquitous."""
    monkeypatch.setattr(_recall, "is_self_host_repo", lambda root: True)
    monkeypatch.setattr(_recall, "EXEMPLAR_MAP", {})
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "FAILURE_MODES.md").write_text(
        "# F\n\n## 1. Major named failure modes\n\n"
        "### 1.7 Gate tuning-to-HEAD blind spot\n\n"
        "**Signature.** zorptiebreaker footgun body.\n",
        encoding="utf-8")
    mem = tmp_path / "memory"
    mem.mkdir()
    # EQUAL VOCABULARY SIZE with the coinage above (9 distinct tokens each) is
    # load-bearing since length normalisation landed: the scorer divides by a
    # fractional power of a doc's vocabulary, so two docs of different sizes no
    # longer produce the exact float tie this fixture's whole premise rests on.
    # Before this padding the coinage carried 9 distinct tokens and this note 4,
    # the note won on score, and the tie-break under test never ran -- the test
    # failed while the behaviour it guards was intact. Count the tokens if you
    # edit either doc; `_tokenize` drops stopwords and 1-char tokens.
    (mem / "aaa.md").write_text(
        "# Aaa\n\nzorptiebreaker note body alpha beta gamma delta epsilon\n",
        encoding="utf-8")
    (mem / "pad1.md").write_text("# Pad1\n\npotato carrot turnip\n", encoding="utf-8")
    (mem / "pad2.md").write_text("# Pad2\n\nparsnip radish leek\n", encoding="utf-8")
    return tmp_path


def test_canonical_footgun_wins_score_tie(tmp_path, monkeypatch):
    root = _tie_corpus(tmp_path, monkeypatch)
    hits = _recall.recall("zorptiebreaker", root, top=1)
    assert hits and "FAILURE_MODES.md :: 1.7" in hits[0].source


def test_tie_break_edge_is_what_bites(tmp_path, monkeypatch):
    # Neutralize the edge -> the memory doc wins the same tie (proves the edge,
    # not score, decides it; non-vacuous earn-the-red).
    root = _tie_corpus(tmp_path, monkeypatch)
    monkeypatch.setattr(_recall, "_is_canonical_footgun", lambda s: False)
    hits = _recall.recall("zorptiebreaker", root, top=1)
    assert hits and hits[0].source == "memory/aaa.md"


def test_edge_does_not_outrank_higher_scoring_doc(tmp_path, monkeypatch):
    # A non-coinage doc with a STRICTLY higher score still wins — the edge is
    # ties-only, never a score bonus.
    monkeypatch.setattr(_recall, "is_self_host_repo", lambda root: True)
    monkeypatch.setattr(_recall, "EXEMPLAR_MAP", {})
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "FAILURE_MODES.md").write_text(
        "# F\n\n## 1. Major named failure modes\n\n"
        "### 1.7 Gate tuning-to-HEAD blind spot\n\n**Signature.** sharedterm only.\n",
        encoding="utf-8")
    mem = tmp_path / "memory"
    mem.mkdir()
    # memory doc matches TWO query terms -> higher base score than the coinage's one.
    (mem / "rich.md").write_text("# Rich\n\nsharedterm extraterm both here\n", encoding="utf-8")
    # Padding keeps sharedterm below the half-corpus floor (df=2 of n=4) so it
    # stays topical rather than suppressed as ubiquitous.
    (mem / "pad1.md").write_text("# Pad1\n\npotato carrot turnip\n", encoding="utf-8")
    (mem / "pad2.md").write_text("# Pad2\n\nparsnip radish leek\n", encoding="utf-8")
    hits = _recall.recall("sharedterm extraterm", tmp_path, top=1)
    assert hits and hits[0].source == "memory/rich.md"


def test_live_gate_tuning_terse_query_now_surfaces_a_coinage():
    # The earn-the-red: "gate tuning to HEAD" lost the 12.x tie to a SHARP_EDGES
    # scanner section pre-edge; now a FAILURE_MODES coinage wins it.
    hits = _recall.recall("gate tuning to HEAD", REPO_ROOT, top=1)
    assert hits and _recall._is_canonical_footgun(hits[0].source), hits and hits[0].source


def test_live_suppress_floor_unchanged_by_edge():
    assert _recall.recall("zqxwvk jmpfbn wlgrtz", REPO_ROOT) == []


def _proof_tier():
    """The tier script, loaded the way its own tests load it: its corpus
    predicate is the one home of "which files does the pull-recall loader
    read", so a pin that needs that roster derives it rather than retyping it."""
    import importlib.util
    path = REPO_ROOT / "scripts" / "proof_tier.py"
    spec = importlib.util.spec_from_file_location("proof_tier_for_recall_tests", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _named_leader_corpus(tmp_path, monkeypatch):
    """A memory note whose TITLE is the query, and a FAILURE_MODES coinage that
    carries both query terms too, one distinct token larger (10 against 9): the
    note out-scores the coinage by (10/9)**LENGTH_NORM_ALPHA, about half a
    percent -- strictly ahead, and inside CANON_TIE_EPSILON, which is the cell
    the 2026-09-11 catalog fold produced live (DEF-775). Padding keeps both
    query terms at df=2 of n=4, on the topicality floor rather than suppressed
    as ubiquitous. Count the tokens if you edit either doc."""
    monkeypatch.setattr(_recall, "is_self_host_repo", lambda root: True)
    monkeypatch.setattr(_recall, "EXEMPLAR_MAP", {})
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "FAILURE_MODES.md").write_text(
        "# F\n\n## 1. Major named failure modes\n\n"
        "### 1.7 Gate tuning-to-HEAD blind spot\n\n"
        "**Signature.** zorptiebreaker quux footgun body.\n",
        encoding="utf-8")
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "named.md").write_text(
        "# Zorptiebreaker quux\n\n"
        "zorptiebreaker quux alpha beta gamma delta epsilon zeta eta\n",
        encoding="utf-8")
    (mem / "pad1.md").write_text("# Pad1\n\npotato carrot turnip\n", encoding="utf-8")
    (mem / "pad2.md").write_text("# Pad2\n\nparsnip radish leek\n", encoding="utf-8")
    return tmp_path


def test_edge_never_displaces_a_document_the_query_names(tmp_path, monkeypatch):
    """A query that covers a document's own title gets that document, even with
    a canonical coinage inside the window behind it."""
    root = _named_leader_corpus(tmp_path, monkeypatch)
    hits = _recall.recall("zorptiebreaker quux", root, top=2)
    assert [h.source for h in hits] == [
        "memory/named.md", "docs/FAILURE_MODES.md :: 1.7 Gate tuning-to-HEAD blind spot"], hits
    # Non-vacuity: the fixture really is inside the window -- the coinage trails
    # the note by a positive margin of under CANON_TIE_EPSILON of the leader.
    gap = hits[0].score - hits[1].score
    assert 0 < gap <= _recall.CANON_TIE_EPSILON * hits[0].score, (hits, gap)


def test_naming_guard_is_what_holds_the_slot(tmp_path, monkeypatch):
    """Earn the red: with the guard neutralised the same query hands the slot to
    the coinage, so the guard decides this cell, not the scores."""
    root = _named_leader_corpus(tmp_path, monkeypatch)
    monkeypatch.setattr(_recall, "_names", lambda d, q: False)
    hits = _recall.recall("zorptiebreaker quux", root, top=1)
    assert hits and hits[0].source.startswith("docs/FAILURE_MODES.md :: 1.7"), hits


def test_a_one_token_title_is_not_a_name(tmp_path, monkeypatch):
    """The guard stands down below two content tokens: a one-word title covers
    too many queries to count as being named by one."""
    root = _named_leader_corpus(tmp_path, monkeypatch)
    (root / "memory" / "named.md").write_text(
        "# Zorptiebreaker\n\n"
        "zorptiebreaker quux alpha beta gamma delta epsilon zeta eta\n",
        encoding="utf-8")
    hits = _recall.recall("zorptiebreaker quux", root, top=1)
    assert hits and hits[0].source.startswith("docs/FAILURE_MODES.md :: 1.7"), hits


def test_live_a_memory_notes_own_title_holds_against_a_coinage_in_the_window():
    """The live cell (DEF-775): after the 2026-09-11 fold the note's own title
    query returned FAILURE_MODES §1.12 from 0.2% behind it."""
    hits = _recall.recall("gate parser inputs only output", REPO_ROOT, top=1)
    assert hits and hits[0].source == "memory/gate-the-parsers-inputs-not-only-its-output.md", hits


class TestLengthNormalisation:
    """The scorer used to rank by document SIZE as much as by topic.

    Presence-summed IDF rewards a document for every query term it happens to
    contain, and a bigger vocabulary contains more of anything -- so the largest
    note in the corpus beat the note a query literally names. Measured over 246
    heading-derived queries before the fix: 75 returned some LARGER document
    instead of the one they name, and top-1 accuracy was 66.7%. After: 0 and
    ~86%. Recall@3 was flat throughout, so what changed is which doc WINS.
    """

    def test_alpha_is_engaged(self):
        """A zero exponent is the unnormalised behaviour this class exists to
        prevent regressing to."""
        assert _recall.LENGTH_NORM_ALPHA > 0, (
            "length normalisation disabled -- the scorer is back to ranking by "
            "vocabulary size; see the calibration table on LENGTH_NORM_ALPHA"
        )

    def test_a_query_naming_a_doc_beats_a_five_times_larger_neighbour(self):
        """The earn-the-red, on the live corpus rather than a fixture.

        ``git artifact hygiene`` names ``memory/git-artifact-hygiene.md`` (201
        tokens) about as unambiguously as a query can. It used to return
        ``memory/task-packs.md`` (1044 tokens) -- five times the size, and not
        what was asked for.
        """
        expected = REPO_ROOT / "memory" / "git-artifact-hygiene.md"
        assert expected.is_file(), (
            f"fixture doc {expected.name} is gone -- this test's premise moved; "
            "re-point it at another small, precisely-named note rather than "
            "deleting the coverage"
        )
        hits = _recall.recall("git artifact hygiene", REPO_ROOT, top=1)
        assert hits, "expected a hit for a query naming a document"
        assert hits[0].source == "memory/git-artifact-hygiene.md", (
            f"got {hits[0].source} -- a query naming a doc must not lose to a "
            "larger neighbour"
        )

    def test_normalisation_does_not_break_suppression(self):
        """Dividing by document length must not lift a nonsense query over the
        floor: the floor is df-based and post-normalisation, but a smaller
        divisor raises every score, so this is worth pinning rather than
        assuming."""
        assert _recall.recall("zqxwvk jmpfbn wlgrtz", REPO_ROOT) == []


class TestNearestByTitle:
    """`nearest_by_title` answers a different question from `recall`.

    `recall` scores against document BODIES and expects a short topic.
    `nearest_by_title` answers "which existing note is ABOUT this paragraph",
    which is what a title declares -- and titles are short and near-uniform, so
    the vocabulary-size bias that defeats a long body query cannot arise.
    """

    def test_a_long_paragraph_finds_the_title_that_names_it(self, tmp_path, monkeypatch):
        """The mechanism, on a corpus where body-matching demonstrably fails."""
        root = _synth(tmp_path, monkeypatch, {
            # The right answer: a terse title naming the subject, tiny body.
            "closed-loop.md": "# Closed loop verification trap\n\nshort body\n",
            # The decoy: says nothing about closed loops in its TITLE, but its
            # body sprawls across every word the paragraph happens to use.
            "sprawl.md": (
                "# Miscellaneous notes\n\nguard transform round trip oracle "
                "normalise whitespace prefix assertion constant indent nested "
                "bullet region generated source sync correctness independent\n"
            ),
            "pad1.md": "# Pad one\n\npotato carrot\n",
            "pad2.md": "# Pad two\n\nparsnip radish\n",
        })
        para = (
            "A generated region needs three guards because the first two are "
            "structurally blind to the transform. Round trip proves sync but not "
            "correctness; the independent oracle must normalise whitespace to "
            "ignore the prefix, which is what makes it blind to the prefix. This "
            "is the closed loop verification trap wearing a different hat."
        )
        by_title = _recall.nearest_by_title(para, root, top=3)
        assert by_title, "expected a title match"
        assert by_title[0].source == "memory/closed-loop.md", (
            f"title match picked {by_title[0].source}"
        )

        # EARN THE RED: the body-scoring path picks the sprawling decoy on the
        # same corpus and the same paragraph. That divergence is the whole reason
        # this function exists -- if it ever stops diverging, re-check the premise.
        by_body = _recall.recall(para, root, top=1)
        assert by_body and by_body[0].source == "memory/sprawl.md", (
            "the decoy no longer wins the body path; this test's premise moved"
        )

    def test_returns_several_ranked_candidates(self, tmp_path, monkeypatch):
        """Top-N, not top-1: a weak hit must read as one option among several
        rather than as an answer."""
        root = _synth(tmp_path, monkeypatch, {
            "aaa.md": "# Alpha widget gadget\n\nbody\n",
            "bbb.md": "# Beta widget\n\nbody\n",
            "ccc.md": "# Gamma gadget\n\nbody\n",
            "pad.md": "# Unrelated\n\npotato\n",
        })
        hits = _recall.nearest_by_title("widget gadget discussion", root, top=3)
        assert len(hits) >= 2, "expected several ranked candidates"
        assert hits[0].score >= hits[-1].score, "must be ranked descending"

    def test_no_title_overlap_returns_nothing(self, tmp_path, monkeypatch):
        """A genuinely novel insight has no near neighbour, and saying so is the
        honest answer -- never a spurious top-1."""
        root = _synth(tmp_path, monkeypatch, {
            "aaa.md": "# Potato farming\n\nbody\n",
            "bbb.md": "# Radish cultivation\n\nbody\n",
        })
        assert _recall.nearest_by_title("zqxwvk jmpfbn wlgrtz", root) == []

    def test_live_corpus_finds_the_closed_loop_note(self):
        """On the real corpus, the case that motivated the change: body-matching
        returned the largest file in the corpus for this entry; title-matching
        returns the note it is actually about, by a clear margin.

        ⚠ The matching is LEXICAL, not semantic. This passes because the entry
        NAMES the trap. A paraphrase that never says "closed loop" scores ~1.3
        against a scatter of unrelated notes -- verified while writing this test,
        by writing exactly that paraphrase first. So the hint helps most when the
        author already half-knows the neighbour, which bounds its value; it is
        advisory for that reason, not merely by politeness.
        """
        para = (
            "A generated region needs three guards because the first two are "
            "structurally blind to the transform. The round trip puts the "
            "generator on both sides of the equality. Closed-loop verification "
            "trap has a sibling: the escape from the loop can itself be blind."
        )
        hits = _recall.nearest_by_title(para, REPO_ROOT, top=3)
        assert hits, "expected a title match on the live corpus"
        assert any("closed-loop-verification-trap" in h.source.lower()
                   or "Closed-Loop Verification Trap" in h.source
                   for h in hits), [h.source for h in hits]


# ── DEF-609: the two-arm suppression contract ─────────────────────────────────
#
# WHY THIS BLOCK EXISTS. The suppression guard above is pinned by exactly two
# negatives, and BOTH are the easy half of the contract: pure gibberish
# ("qwxyz plughh vorpal") and a synthetic near-miss of ubiquitous tokens. Neither
# can fail for the reason the guard is supposed to hold. Gibberish tokens have
# df=0, so they are dropped BEFORE the floor is consulted -- the floor is never
# actually exercised by the test that claims to earn it. Measured 2026-08-19 on
# the live corpus: pure gibberish suppresses 1/1, ordinary off-topic English
# leaks 29/29. "recipe for banana bread" returns the write_guard Bash-string-
# literal edge, confidently, at score 3.42.
#
# This is the engine committing the class its own catalog is FOR (docs/sharp-edges/
# a-new-guard-is-blind-the-way-it-claims-to-see.md): the floor's predicate --
# "is any matched term rare?" -- structurally cannot see its own subject, which is
# "does this document account for what was ASKED".
#
# NO FLOOR FIXES IT, AND THAT IS A MEASURED RESULT, NOT A CONCESSION. Eight
# mechanisms were driven through the real recall() path on two 26+ query arms;
# every one has a NEGATIVE margin (max off-topic scores above min legitimate):
#
#     mechanism                                    gap        note
#     IDF coverage >= tau                        -0.571   the prescribed fix
#     whole-identifier / phrase floor            -1        gates typing style
#     inverted df >= K (and the two-sided band) -164
#     score margin (top1/top2, z, n-within-5%)   -2.899   inverted
#     query-shape (function words, code tokens)  -0.607   no signal at all
#     doc-side title / filename anchor           -1        deletes 74% of real Qs
#     boolean composition (A or B, A and B)      <=0      OR unions the leaks,
#                                                         AND unions the misses
#     background-English surprisal               -6.000   measures "is this
#                                                         specialist prose", not
#                                                         "is this OUR domain"
#     query-term PMI co-occurrence (joint)       -3.124
#
# The root cause is structural: all 266 docs are English prose about software
# process, so on-topic jargon is HIGH-df/LOW-IDF while incidental everyday words
# are LOW-df/HIGH-IDF. IDF points the wrong way here, and every term-statistic
# inherits that. See docs/SHARP_EDGES.md "A pull-recall engine must SUPPRESS on
# no-match" for the full record.
#
# So this block pins the contract HONESTLY, in three tiers rather than pretending
# a guarantee we cannot deliver:
#   1. _MUST_ANSWER  -- over-suppression guard. Any future floor that silences a
#                       real operator question reds here. This is the arm that
#                       protects the engine's actual value.
#   2. _MUST_RANK    -- a small, semantically UNAMBIGUOUS subset that also pins
#                       WHICH doc wins.
#   3. _OFF_TOPIC_ENGLISH under a characterization RATCHET -- today's leak count
#                       is recorded as a number. Improvement is allowed; silent
#                       regression is not.

_MUST_ANSWER = (
    # terse jargon -- every token is ordinary English, which is what makes these
    # the hardest legitimate case and why no vocabulary-based floor can survive.
    "plan guard", "mirror sync", "hook exit codes", "kill switch settings",
    "stop gate pytest", "born weak guard", "earn the red", "class fix scope",
    "gate tuning to HEAD", "vendor byte parity", "blueprint chain depth",
    "scanner stdlib only", "citation rot", "provenance census",
    # carrying tokens absent from the corpus (ticket IDs, versions, ordinals)
    "why did TP-442 break the mirror sync", "DEF-609 recall floor",
    "what does reflect_trigger.py do on the tenth write",
    "python 3.14 tomli minimum version",
    # plain-English sentences with no jargon at all
    "why is the stop gate green when the tests did not run",
    "how do I add a new scanner", "who owns the settings file",
    "what happens when a subagent writes to git",
    # a paraphrase of a doc that genuinely exists
    "a guard that is blind the same way it claims to see",
)

#: (query, expected substring of Hit.source). Deliberately SMALL and restricted to
#: queries whose right answer is SEMANTICALLY UNARGUABLE -- which is NOT the same as
#: wide-margin, and an earlier draft of this comment wrongly implied it was.
#:
#: Measured margins for the rows kept here (2026-08-19), all as
#: (top1 - top2) / top1 -- ONE formula, stated once, because an earlier
#: draft mixed two denominators and no reader could tell whether a changed
#: number meant engine drift or a changed rule:
#:     how do I add a new scanner ................. 63.3%
#:     windows path normalization ................. 13.0%
#:     hook exit codes ............................  6.8%
#:     citation rot ...............................  6.3%
#:     a guard that is blind ... claims to see .....  6.2%
#:     pipefail grep sigpipe ......................  4.3%
#:     cognitive_blueprint justify ................  4.1%
#: So FIVE of the seven sit under 8%. They are kept anyway because the match is exact
#: in meaning (the query names the doc's subject outright), not because the margin is
#: safe -- and that is a deliberate accepted flake risk, stated rather than hidden.
#: If one starts failing, check whether a NEW doc legitimately answers the query better
#: before "fixing" the engine -- that is corpus growth, not a regression. BUT retargeting
#: a row is not free: _MUST_RANK is the ONLY correctness arm here, and a written-in
#: permission to loosen is how a 7-query pin becomes a 0-query pin over four sessions
#: (the repo has paid for this: tests/test_check_pack_landing.py:299, "a ratchet that
#: trains people to raise it has inverted its own purpose"). So the count below is a
#: FLOOR, pinned by test_must_rank_is_not_silently_drained -- drop a row only by adding
#: a replacement in the same commit.
_MUST_RANK = (
    ("how do I add a new scanner", "espalier/scanners/"),
    ("windows path normalization", "Path Normalization on Windows"),
    ("hook exit codes", "Channel XOR"),
    ("cognitive_blueprint justify", "action-justification-protocol"),
    ("a guard that is blind the same way it claims to see",
     "A New Guard Is Blind The Way It Claims To See"),
    ("pipefail grep sigpipe", "SIGPIPE race"),
    ("citation rot", "Rotted Citation"),
    # STANDING_PRINCIPLES tier. Only the two WIDE-margin ones are pinned:
    # 41.6% and 8.6%. Deliberately NOT pinned despite being correct today:
    # "earn the red" (0.3%) and "read the neighbours before adding a sibling"
    # (1.3%) -- correct answers sitting on a knife edge are flakes waiting to
    # happen, and pinning them would trade a real guard for a maintenance tax.
    ("match the net to the hole", "Match the net to the hole"),
    ("direction is not magnitude", "Direction \u2260 magnitude"),
)

_OFF_TOPIC_ENGLISH = (
    # everyday English about non-software topics
    "what should I have for lunch", "my car will not start",
    "recipe for banana bread", "the weather next tuesday",
    "how tall is the building", "who won the game last night",
    "best coffee beans for espresso", "my knee hurts when I run",
    "flight to lisbon on friday", "the dog keeps barking at night",
    # specialist prose from ANOTHER domain -- the highest-scoring attack found
    # (23.92 against memory/pizza-test-review-lens.md, higher than every
    # legitimate query in _MUST_ANSWER)
    "the chef's pancake crust had a soda taste and the sauce was thin",
    "the soup was too salty and the bread was stale",
    "we ordered a large pie with extra cheese and it arrived cold",
    # the hard half: ordinary English built ONLY from corpus-present tokens, so
    # no out-of-vocabulary term can do the suppressing. Any floor that passes the
    # gibberish test but fails here is measuring vocabulary, not topic.
    "should I change the order of the steps", "what is the best time to start",
    "is it worth the cost", "keep the same name for the new one",
    "can you make the list shorter", "what happens after the first one",
    "the second half was much better than the first",
    "why is the number so much larger now",
    "make sure to check the other side first", "how long does it take to run",
    "I would like to see more of them", "please put it back where it was",
    "there is no need to do that again", "that was a very good idea",
    "most people would not notice the difference",
    "the whole thing needs to be much simpler",
)

#: How many of _OFF_TOPIC_ENGLISH the engine currently answers instead of
#: suppressing. Lower it whenever a change improves the floor; NEVER raise it
#: without recording why in the commit message.
#:
#: 2026-08-19: 29 of 29. The engine suppresses NONE of them.
#:
#: ⚠ BE HONEST ABOUT WHAT THIS CAN AND CANNOT DETECT, because the ceiling currently
#: EQUALS the arm size, which makes `len(leaked) <= ceiling` true for any possible
#: behaviour of recall() -- including a perfect one. Flagged in review; kept, with the
#: claim corrected rather than the number massaged. It is today a BOOKKEEPING TRIP-WIRE,
#: not a regression detector: it fires only if someone adds a leaking query to the arm
#: without deliberately bumping this constant. It BECOMES a real regression detector the
#: moment a floor drops the count below the arm size, and that asymmetry is the point --
#: there is no headroom to lose while everything already leaks.
#: The regression detection that has real headroom today is
#: _OUT_OF_VOCABULARY_MUST_SUPPRESS below: that arm is at 0 leaks and CAN regress.
_OFF_TOPIC_LEAK_CEILING = 29


def test_must_answer_arm_is_never_suppressed():
    """Over-suppression guard: a real operator question must always get an answer.

    This is the arm that makes the ratchet below safe to tighten. Any future
    suppression floor is free to reduce the leak count -- but the moment it
    silences one of these, it reds here. Without this arm, "improve suppression"
    has a trivially winning cheat: suppress everything.
    """
    silenced = [q for q in _MUST_ANSWER if not _recall.recall(q, REPO_ROOT, top=1)]
    assert not silenced, (
        f"{len(silenced)} legitimate operator queries were suppressed: {silenced}. "
        "A suppression floor that silences real questions costs more than the "
        "off-topic leak it buys -- see the mechanism table above."
    )


def test_must_rank_arm_returns_the_right_document():
    """The unambiguous subset also pins WHICH doc wins, not merely that one did."""
    wrong = []
    for query, expected in _MUST_RANK:
        hits = _recall.recall(query, REPO_ROOT, top=1)
        if not hits or expected.lower() not in hits[0].source.lower():
            wrong.append((query, expected, hits[0].source if hits else "SUPPRESSED"))
    assert not wrong, f"top-1 changed for {len(wrong)} pinned queries: {wrong}"


def test_off_topic_english_leak_count_does_not_grow():
    """The characterization ratchet.

    ⚠ Read the number, not just the colour. This test passing does NOT mean the
    engine suppresses off-topic English -- today it suppresses none of it. It
    means the leak count has not grown. That distinction is the entire point of
    DEF-609: the previous pin was green while the behaviour it claimed to
    guarantee was absent.
    """
    leaked = [q for q in _OFF_TOPIC_ENGLISH if _recall.recall(q, REPO_ROOT, top=1)]
    # TWO-SIDED, and that is the whole repair. The first draft asserted `<=`, which
    # with ceiling == len(arm) is literally `len(subset) <= len(superset)` -- true for
    # ANY behaviour of recall(), including a perfect one. Driven in review: deleting
    # the suppression floor outright left it green. `==` is falsifiable in both
    # directions and forces a re-derivation either way.
    assert len(leaked) == _OFF_TOPIC_LEAK_CEILING, (
        f"off-topic leak count moved to {len(leaked)} (pinned "
        f"{_OFF_TOPIC_LEAK_CEILING}). LOWER is good news -- lower the constant in the "
        f"same commit and say why. HIGHER is a regression. Either way RE-DERIVE the "
        f"number; do not adjust it to fit. Currently leaking: {leaked}"
    )


def test_the_off_topic_ratchet_has_a_falsifiable_companion():
    """Non-vacuity guard for the ratchet above -- the repo requires one of every
    ratchet (tests/test_check_pack_landing.py::test_the_advisory_ratchets_are_not_vacuous).

    ⚠ Stated plainly so nobody over-reads the green above: this block does NOT
    detect removal of the suppression floor. Gibberish suppresses because its tokens
    have df=0 and are dropped BEFORE the floor is consulted, so floor-deletion is
    invisible here. That case is covered -- by the synthetic
    test_suppresses_near_miss_of_ubiquitous_tokens above, which is the only test in
    this file that reds when the floor is removed. Do not delete it thinking this
    block supersedes it.
    """
    assert _OFF_TOPIC_LEAK_CEILING <= len(_OFF_TOPIC_ENGLISH)
    assert _OFF_TOPIC_ENGLISH, "the arm must not be empty -- an empty arm ratchets nothing"


def test_must_rank_is_not_silently_drained():
    """_MUST_RANK is the only correctness arm; its size is a floor, not a snapshot."""
    assert len(_MUST_RANK) >= 7, (
        f"_MUST_RANK dropped to {len(_MUST_RANK)} rows. Retargeting a row when the "
        "corpus legitimately grows is fine; REMOVING one without a replacement "
        "quietly converts the only correctness arm into nothing."
    )


def _in_band(measured, centre, *, slack=1):
    """±slack around the RECORDED measurement. NOT a floor, and not a shape.

    The disturbance this absorbs was measured on 2026-08-20 by a leave-one-out
    census over the whole live corpus -- every one of the 285 documents held out
    of `_iter_corpus` in turn, in an isolated worktree. 18 of 258 testable
    documents (7.0%) move at least one pinned constant, and EVERY move is exactly
    ±1: `memory/` 8/58 (13.8%), `docs/sharp-edges/` 2/24, `docs/SHARP_EDGES.md`
    sections 8/176.
    ⚠ RE-MEASURED against the SHIPPED pin, and the first figures were wrong. The
    census was first run against a three-leg plateau and the pin gained a fourth
    leg later in the same change series, so it reported 14/258 (5.4%) and
    `memory/` 4/58. The re-run is 18/258 and `memory/` 8/58 -- a 2x understatement
    on the one tier /handoff and reflect actually write. The census derives the
    swept slots FROM this file, so re-running it was the whole fix; it simply was
    not re-run. Per-pin rates, which differ by an order of magnitude and are the
    reason one pin below is NOT banded: curve 7/258 (2.71%), contested 6/258
    (2.33%), distinct winners 4/258 (1.55%), blind scored arm 2/258 (0.78%). The moves run in BOTH directions (plateau slot 2 falls 7 -> 6 when
    memory/publish-from-a-generated-public-repo.md lands; the blind arm rises
    12 -> 13 when one SHARP_EDGES section lands), which is why a floor is the
    wrong instrument: it is blind upward, and upward is half the observed noise.

    The attack these pins actually catch is LARGER: aliasing three currently-
    missing scored rows against the held-out fixture moves that pin 13 -> 16. So
    ±1 absorbs one adverse document and still reds on tuning.

    ⚠ It cannot separate a ONE-row tuning event from a ONE-document drift -- they
    are the same magnitude and no threshold fixes that. The separators are
    upstream (the fixture's "spend a row, delete the row" rule, or a larger arm),
    not here. Do not widen the band to make a red go away; re-derive and record
    the cause, as the failure messages ask.

    Precedent for the shape and for the ±1 specifically:
    tests/test_check_pack_landing.py -- "HEADROOM OF ONE, AND THE ONE IS
    LOAD-BEARING".
    """
    return centre - slack <= measured <= centre + slack


#: How many DISTINCT documents the 23 _MUST_ANSWER queries resolve to today.
#: Pinned with `==` because this is the arm's only real teeth: _MUST_ANSWER itself
#: asserts non-emptiness, which a mutation returning ONE fixed doc for every query
#: satisfies completely (driven in review -- it left all four original tests green).
#: A collapse in this number is that mutation's signature.
#:
#: 2026-08-19: 23 queries -> 18 distinct winners (three collapse onto the
#: De-provenancing SHARP_EDGES section, which is itself a measurable ranking smell).
#: ⚠ BANDED ±1 on 2026-08-20. The leave-one-out census (see `_in_band`) measured
#: FOUR documents that move this number by one in ordinary documentation work, in
#: both directions: memory/CONVERGENCE_LEDGER.md and the SHARP_EDGES sections
#: "Local Hooks Are Not a Sandbox" and "De-provenancing edits go to the SoT, never
#: the mirror" each take it to 19; docs/sharp-edges/deleted-governance-event-fail-open.md
#: takes it to 17. The collapse this pin exists to detect is a drop to ~1, so the
#: band costs the claim nothing and buys four documents' worth of false reds.
#: 2026-09-12: 18 -> 20 when the pull ranker stopped indexing
#: memory/CONVERGENCE_LEDGER.md and memory/task-packs.md (PULL_EXCLUDED_MEMORY_NOTES
#: in _recall.py): each had been the collapsed winner of a must-answer query, which
#: is the displacement DEF-699 measured. Higher is the good direction here.
_MUST_ANSWER_DISTINCT_WINNERS = 20


def test_must_answer_winners_do_not_collapse():
    """Teeth for the non-emptiness arm above.

    ⚠ This does NOT assert the winners are CORRECT. Measured 2026-08-19, roughly ten
    of the 23 return a doc that is not the best answer -- 'earn the red' returns a
    packaging edge, 'born weak guard' does not return the born-weak spine doc. That is
    the separate RANKING defect (see the module docstring), deliberately out of scope
    here and NOT laundered into a green by this file. What this pins is that the engine
    still discriminates at all.
    """
    winners = {h[0].source for q in _MUST_ANSWER
               if (h := _recall.recall(q, REPO_ROOT, top=1))}
    # Non-vacuity: a collapsed corpus yields few winners AND few queries that
    # return anything, so assert the arm still resolves before believing the band.
    # Split for the same reason as the plateau guard's twin: measured, a realistic
    # 24th query leaves the band passing and correct (18-19 winners) and makes the
    # length leg the sole red, so one shared "the corpus collapsed" message
    # misdiagnoses the common case.
    assert len(winners) >= 10, (
        f"only {len(winners)} distinct winners -- the ranker or the corpus "
        "collapsed and the band below would pass measuring nothing"
    )
    assert len(_MUST_ANSWER) == 23, (
        f"the must-answer arm is {len(_MUST_ANSWER)} queries, not 23 -- the arm "
        "CHANGED SIZE, so the pinned winner count is not comparable. Re-derive it "
        "against the new arm; do not adjust the constant to fit."
    )
    assert _in_band(len(winners), _MUST_ANSWER_DISTINCT_WINNERS), (
        f"distinct winners moved to {len(winners)} (pinned "
        f"{_MUST_ANSWER_DISTINCT_WINNERS}, band ±1). A DROP means the ranker is "
        "collapsing queries onto fewer documents -- that is a real degradation even "
        "though every query still returns something. Re-derive; do not adjust to fit. "
        "The mutation this exists to catch (one fixed document for every query) lands "
        "far outside the band, so the band costs it nothing."
    )


#: Corpus tiers and the filesystem oracle that derives each count. A tier that stops
#: loading is invisible to every other test here: driven in review, deleting the whole
#: docs/sharp-edges/ tier (24 docs, including the born-weak spine this fix is written
#: against) left all 51 tests green. Derived, never hand-copied -- STANDING_PRINCIPLES
#: §14. Note docs/sharp-edges/*.md is a NON-recursive glob in _iter_corpus, so a file
#: added in a subfolder silently never joins the corpus; this catches that too.
def test_every_corpus_tier_still_loads():
    docs = _recall._load_corpus(REPO_ROOT)
    loaded_sharp_edges = sum(1 for d in docs if d.source.startswith("docs/sharp-edges/"))
    loaded_memory = sum(1 for d in docs if d.source.startswith("memory/"))
    fs_sharp_edges = len([p for p in (REPO_ROOT / "docs" / "sharp-edges").glob("*.md")
                          if p.name != "README.md"])
    # The loader skips README.md and the notes PULL_EXCLUDED_MEMORY_NOTES names
    # (a record and an aggregate, 2026-09-12); the on-disk side applies the same
    # two rules so a tier that stopped loading still reds and a skip does not.
    fs_memory = len([p for p in (REPO_ROOT / "memory").glob("*.md")
                     if p.name != "README.md"
                     and f"memory/{p.name}" not in _recall.PULL_EXCLUDED_MEMORY_NOTES])
    assert loaded_sharp_edges == fs_sharp_edges, (
        f"docs/sharp-edges/ tier: {loaded_sharp_edges} loaded vs {fs_sharp_edges} on "
        "disk -- a corpus tier stopped loading, or a .md landed in a subfolder the "
        "non-recursive glob cannot see."
    )
    assert loaded_memory == fs_memory, (
        f"memory/ tier: {loaded_memory} loaded vs {fs_memory} on disk"
    )
    loaded_principles = sum(1 for d in docs
                            if d.source.startswith("docs/STANDING_PRINCIPLES.md"))
    fs_principles = sum(1 for ln in (REPO_ROOT / "docs" / "STANDING_PRINCIPLES.md")
                        .read_text(encoding="utf-8").splitlines()
                        if ln.startswith("## "))
    assert loaded_principles == fs_principles, (
        f"STANDING_PRINCIPLES tier: {loaded_principles} loaded vs {fs_principles} "
        "`## ` sections on disk"
    )


def test_every_principle_is_retrievable_by_its_own_name():
    """Coverage win from indexing docs/STANDING_PRINCIPLES.md, pinned by IDENTITY.

    Before the widening this was 0 of 16: the document whose entire purpose is to be
    recalled was not in the corpus, so `/recall earn the red` returned a packaging
    edge. The SessionStart banner prints these principles BY NAME every session, so
    the name-shaped query -- the heading minus its ordinal -- is the shape operators
    are actually trained to type.

    ⚠ DERIVED from the document, never a hand-written copy of it (§14, which is one
    of the very principles this covers). Two drafts of this test were rejected in
    review for exactly the reasons the derivation removes: the first asserted only
    `source.startswith("docs/STANDING_PRINCIPLES.md")`, which any of the 16 sections
    satisfies -- driven, appending two sentences of ordinary prose to §7 made
    `earn the red` return §1 instead, restoring the defect the tier exists to fix
    while the test stayed green. The second hand-listed 8 queries, all passing, under
    a comment claiming a 10-query population -- the two failures had been dropped from
    the set rather than pinned. Deriving fixes both and covers principles not yet
    written.

    ⚠ What this does NOT claim. Indexing fixes COVERAGE, not paraphrase. A query that
    DESCRIBES a principle rather than naming it ("how do I know my new test would
    actually catch the bug") still resolves by lexical overlap and mostly lands
    elsewhere -- measured 1 of 16 on a paraphrase arm, unchanged by this widening.
    Read this green as "their names now work", not "the principles are retrievable".
    """
    sections = _hook_utils.iter_doc_sections(
        (REPO_ROOT / "docs" / "STANDING_PRINCIPLES.md").read_text(encoding="utf-8"))
    assert len(sections) >= 10, (
        f"only {len(sections)} principle sections parsed -- the population collapsed, "
        "so asserting over it would pass vacuously"
    )
    wrong = []
    margins = []  # (relative gap to the runner-up, query, runner-up source)
    for title, _ in sections:
        query = re.sub(r"^\d+\.\s*", "", title)  # the banner shape: no ordinal
        hits = _recall.recall(query, REPO_ROOT, top=1)
        want = f"docs/STANDING_PRINCIPLES.md :: {title}"
        if not hits or hits[0].source != want:
            wrong.append((query, hits[0].source if hits else "SUPPRESSED"))
            continue
        pair = _recall.recall(query, REPO_ROOT, top=2)
        if len(pair) == 2 and pair[0].score > 0:
            margins.append(((pair[0].score - pair[1].score) / pair[0].score,
                            query, pair[1].source))
    # The margin is DERIVED here, never quoted: the first version of this message
    # cited "1.4%" for the thinnest case, and by 2026-09-09 that case sat at 0.06%
    # -- four new distinct tokens in the principle's own section away from a flip.
    tightest = min(margins, default=None)
    tightest_note = (
        f"(tightest today: {tightest[0]:.2%} on {tightest[1]!r} vs {tightest[2]})"
        if tightest else "(no margin measurable)"
    )
    assert not wrong, (
        f"{len(wrong)} of {len(sections)} principles do not win their own name:\n  "
        + "\n  ".join(f"{q!r} -> {got}" for q, got in wrong)
        + "\n\nBefore 'fixing' the engine, check whether a NEW doc legitimately "
          "out-ranks the principle. Several of these sit on thin margins against a "
          f"same-titled memory/ twin {tightest_note}, so an ordinary /handoff note "
          "CAN flip one -- and a short note carrying most of a title's tokens "
          "out-ranks the section that owns the title (binary presence over a length "
          "norm; the quote is a correlate, the size is the mechanism). That is a "
          "real signal worth acting on at the source -- two committed documents "
          "competing for one name -- not a number to adjust."
    )


def test_principles_tier_is_absent_when_the_file_is(tmp_path, monkeypatch):
    """The tier is gated on file existence, not repo identity -- so an adopter who
    has not written standing principles gets a no-op, and one who HAS gets them
    recalled. Both halves matter: gating on is_self_host_repo would have locked
    adopters out of their own document."""
    root = _synth(tmp_path, monkeypatch, {"a.md": "# A\nflux capacitor widget\n"})
    # The absence half must witness the GATE, not merely its effect. Without this
    # monkeypatch the assertion is vacuous: _read() swallows OSError (and
    # FileNotFoundError is one), so deleting `if sp.is_file()` still yields zero
    # docs and still passes -- driven in review. Making _read explode for this path
    # proves is_file() short-circuits BEFORE the read.
    _orig_read = _recall._read

    def _exploding_read(path):
        if path.name == "STANDING_PRINCIPLES.md":
            raise AssertionError("the file-existence gate was skipped")
        return _orig_read(path)

    monkeypatch.setattr(_recall, "_read", _exploding_read)
    assert not any(d.source.startswith("docs/STANDING_PRINCIPLES.md")
                   for d in _recall._load_corpus(root))
    monkeypatch.setattr(_recall, "_read", _orig_read)
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "STANDING_PRINCIPLES.md").write_text(
        "# P\n\n## 1. Never trust the odometer\nbody\n", encoding="utf-8")
    hits = _recall.recall("never trust the odometer", root, top=1)
    assert hits and hits[0].source.startswith("docs/STANDING_PRINCIPLES.md"), (
        f"an adopter's own standing principles must be recallable, got {hits}"
    )


# ── DEF-609 docs-parity: DERIVED, not a hand-kept list ────────────────────────
#
# The first draft of this guard hand-listed four paths and matched one literal
# phrase. Review found it missed README.md -- the repo's highest-traffic operator
# surface -- which promised "stays silent when nothing matches", and that a plain
# markdown reflow (a double space) walked through the regex. Both failures are the
# SAME shape as the defect this whole file is about: match the easy literal, miss
# the class. So the population is derived from `git ls-files` and the net is
# paraphrase-class (STANDING_PRINCIPLES §14, derive the list; §10, match the net
# to the hole).

#: Trees excluded from the scan, each for a stated reason -- never "it was noisy".
_CLAIM_SCAN_EXCLUDED_PREFIXES = (
    "tests/",                    # this file quotes the forbidden phrasings on purpose
    "task-packs/",               # ledgers RECORD the defect; quoting it is correct
    "cc/",                       # session state, not an operator surface
    "espalier/assets/",          # byte-pinned mirrors -- scanning both double-reports
    "espalier/_vendor/",         # ditto
    "examples/dogfooding/",      # ditto
)
#: Record surfaces per root CLAUDE.md Core Rule 13 -- a stale claim on a dated
#: record is expected aging, and editing one falsifies the record.
_CLAIM_SCAN_EXCLUDED_FILES = (
    "docs/session-archive.md",
    "memory/CONVERGENCE_LEDGER.md", "CHANGELOG.md",
)

#: Paraphrase-class net. Every alternation arm below was derived from a REAL evasion
#: measured against the first draft, not invented: the README used "stays silent
#: when", and `[\s-]?` accepted only one whitespace character so a reflowed double
#: space evaded the literal.
_SUPPRESSION_CLAIM_RE = re.compile(
    r"suppress\w*[\s-]+on[\s-]+no[\s-]*match"
    r"|no[\s-]*match\s+suppress\w*"
    r"|stays?\s+silent(?:\s+\w+){0,3}\s+(?:when|if|unless)"
    r"|returns?\s+nothing(?:\s+\w+){0,3}\s+(?:when|if|unless)"
    r"|silent\s+unless\s+relevant",
    re.I,
)

#: A match only counts as a CLAIM ABOUT /recall if the surrounding window mentions
#: recall -- otherwise "returns nothing when the list is empty" in unrelated prose
#: would fire. Window is generous on purpose; a false positive here is cheap to fix
#: and a false negative is the whole defect.
_CLAIM_WINDOW = 400

#: Qualifiers that make a suppression mention HONEST rather than a false guarantee.
_CLAIM_QUALIFIERS = ("nearest", "out-of-vocabulary", "out of vocabulary",
                     "no vocabulary", "off-topic", "does not", "DEF-609")


def _tracked_claim_surfaces() -> list[str]:
    """The population to scan, via the shared git oracle -- never raw `git ls-files`.

    Routed through require_tracked_paths (tests/_git_oracle.py) because a raw call
    that returns an empty or collapsed population would make the assertion below
    pass while scanning NOTHING -- an unanswerable query reading as an answer, which
    is the same shape as the defect this whole block exists to retire. The floor is
    deliberately well below the true count (~250) and well above collapse.
    """
    paths = require_tracked_paths(
        REPO_ROOT, "*.md", "*.py", minimum=150,
        what="tracked markdown/python claim surfaces",
    )
    return [rel for p in paths
            if not (rel := p.replace("\\", "/")).startswith(_CLAIM_SCAN_EXCLUDED_PREFIXES)
            and rel not in _CLAIM_SCAN_EXCLUDED_FILES]


def test_no_tracked_surface_promises_suppression_while_it_leaks():
    """Docs-parity, derived. This is what makes the correction load-bearing.

    While _OFF_TOPIC_LEAK_CEILING is above zero, no tracked surface may tell an
    operator that /recall goes quiet when nothing is relevant -- in ANY phrasing.

    ⚠ When the ceiling reaches 0 this stops applying by its own terms, which is the
    right coupling (the claim becomes true exactly when the behaviour does) -- but
    reaching 0 proves it only for the static queries in _OFF_TOPIC_ENGLISH. Re-grow
    that arm adversarially with queries never tried before restoring any unqualified
    guarantee, or you will have earned a benchmark rather than a behaviour.
    """
    if _OFF_TOPIC_LEAK_CEILING == 0:
        pytest.skip("ceiling is 0 -- re-grow the arm adversarially before trusting it")
    offenders = []
    for rel in _tracked_claim_surfaces():
        try:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in _SUPPRESSION_CLAIM_RE.finditer(text):
            window = text[max(0, m.start() - _CLAIM_WINDOW):m.end() + _CLAIM_WINDOW]
            if "recall" not in window.lower():
                continue
            if any(q.lower() in window.lower() for q in _CLAIM_QUALIFIERS):
                continue
            offenders.append(f"{rel}:{text[:m.start()].count(chr(10)) + 1}: {m.group(0)!r}")
    assert not offenders, (
        f"tracked surfaces promise suppression while the engine leaks "
        f"{_OFF_TOPIC_LEAK_CEILING}/{len(_OFF_TOPIC_ENGLISH)} off-topic queries:\n  "
        + "\n  ".join(offenders)
    )


def test_recall_rendered_snippet_carries_the_correction():
    """The correction must live where RETRIEVAL can reach it, not only in a body.

    Hit.render() prints the doc TITLE. The first draft corrected the SHARP_EDGES
    entry's body and left its heading asserting the retired guarantee -- so
    `/recall "does recall suppress irrelevant results"` recited the false claim, in
    the imperative voice of a rule, from the harness's own primary retrieval surface.
    Corrected surfaces nobody greps do not help; this is the surface the repo tells
    everyone to use.
    """
    headings = [ln for ln in (REPO_ROOT / "docs" / "SHARP_EDGES.md")
                .read_text(encoding="utf-8").splitlines() if ln.startswith("## ")]
    bad = [h for h in headings
           if _SUPPRESSION_CLAIM_RE.search(h)
           and not any(q.lower() in h.lower() for q in _CLAIM_QUALIFIERS)]
    assert not bad, (
        "a SHARP_EDGES heading asserts suppression unqualified; the heading IS the "
        f"snippet /recall renders, so the body's correction is invisible: {bad}"
    )


def test_no_corpus_document_quotes_the_off_topic_arm():
    """A document inside a retrieval corpus cannot quote the queries it is about.

    The first draft of the SHARP_EDGES entry quoted its own off-topic examples in
    full. Because that file IS corpus-scanned, the entry became top-1 for 6 of the 29
    arm queries -- displacing the documents it cited as evidence and invalidating
    three of its own numbers on landing. FAILURE_MODES §18, committed while writing
    the entry that names it.
    """
    # DERIVED from _iter_corpus, not hand-listed (STANDING_PRINCIPLES §14). The
    # hand-list covered SHARP_EDGES + sharp-edges/ + memory/ and silently omitted
    # docs/STANDING_PRINCIPLES.md -- and now its alias sidecar, whose stated editing
    # rule ("prefer ordinary words the principle does not already contain") steers
    # the next author straight at the population _OFF_TOPIC_ENGLISH is drawn from.
    # _OFF_TOPIC_LEAK_CEILING cannot backstop this: it sits at 29 of 29 with zero
    # headroom, so it is bookkeeping, not a detector. Deriving also covers whatever
    # tier is added next.
    scan = {doc.source.split(" :: ")[0] for doc in _recall._load_corpus(REPO_ROOT)}
    scan = {r for r in scan if r.endswith(".md") and (REPO_ROOT / r).is_file()}
    scan.add("docs/STANDING_PRINCIPLES.aliases.md")  # feeds a corpus doc, isn't one
    scan = {r for r in scan if (REPO_ROOT / r).is_file()}
    assert len(scan) >= 50, (
        f"corpus-backed scan set collapsed to {len(scan)} files -- deriving it from "
        "_load_corpus stopped working and this guard covers almost nothing"
    )
    for tier in ("docs/SHARP_EDGES.md", "docs/STANDING_PRINCIPLES.md",
                 "docs/STANDING_PRINCIPLES.aliases.md"):
        assert tier in scan, f"{tier} fell out of the derived scan set"
    captured = []
    for doc_rel in sorted(scan):
        text = (REPO_ROOT / doc_rel).read_text(encoding="utf-8").lower()
        captured += [f"{doc_rel} quotes {q!r}" for q in _OFF_TOPIC_ENGLISH
                     if q.lower() in text]
    assert not captured, (
        "a corpus document quotes an off-topic probe verbatim, making itself that "
        "query's answer:\n  " + "\n  ".join(captured)
    )


# ── The paraphrase arm and the two-ranker union ───────────────────────────────
#
# A DIFFERENT DEFECT from suppression, and the distinction is load-bearing: a query
# that NAMES a doc finds it (16/16, above); a query that DESCRIBES what it wants
# mostly does not. LENGTH_NORM_ALPHA was calibrated honestly -- on 246 naming queries
# -- and is measurably the wrong pivot for describing queries. Swapping it is not the
# fix: totlen**0.75 took paraphrase 1->6 of 16 but naming 236->181 of 282 and breaks
# _MUST_RANK. Running both and unioning takes the gain at zero naming cost.
# ⚠ Post-expansion the two pivots TIE at 6/16 (naming 233 vs 182 of 274), so the union
# now earns its 9/16 by returning both winners, not by one pivot beating the other.
#
# ⚠ TWO CAVEATS THAT MUST SURVIVE, because this arm is not a clean benchmark.
# (1) The answer key is CONTESTED on at least two rows, marked below. Principle 13
#     has a byte-identical title to memory/read-the-neighbours-before-adding-a-
#     sibling.md, and for the class-scope question the root CLAUDE.md Rule 12 names
#     memory/fix-the-class-not-the-instance.md the "sole home" -- so the principle may
#     be the WRONG expected answer there. The pinned count below therefore measures a
#     defensible reading, not ground truth.
# (2) This arm is mechanical, so it is unaffected by a contamination that would ruin
#     any MODEL-side version of it: session_start.py injects all 16 principle titles
#     into every self-host session, so a model asked to pick has part of the key in
#     context already. Do not reuse these queries to evaluate a model-side design
#     without controlling for that.
# (3) THESE COUNTS MOVE ON ORDINARY DOCUMENTATION WORK, and that is why the
#     MAGNITUDES below are banded +/-1 rather than pinned with `==`. Measured
#     2026-08-20 by a leave-one-out census over the whole live corpus -- each of the
#     285 documents held out of _iter_corpus in turn, in an isolated worktree:
#     18 of 258 testable documents (7.0%) move at least one constant here, always by
#     exactly one hit, and in BOTH directions. Per tier: memory/ 8 of 58 (13.8%),
#     docs/sharp-edges/ 2 of 24, docs/SHARP_EDGES.md sections 8 of 176. THREE of the
#     five tiers _iter_corpus yields are written by this harness's own routine
#     workflows (/handoff promotes a sharp edge; reflect writes a memory/ file), so a
#     red here is more often a documentation commit than a regression.
#     ⚠ The exposure is NOT volume: eight synthetic memory/ documents (corpus
#     285 -> 293) moved nothing at all. It is single-document competition. The
#     2026-08-20 case was isolated to one document and one row, and that document
#     shares no token with the row's answer -- the effect ran through a competitor.
# (4) WHAT THIS BLOCK DOES NOT GUARD IS THE RANKER, and no comment here said so
#     before 2026-08-20. Sweeping PARAPHRASE_NORM_EXPONENT across
#     0.6 / 0.75 / 0.85 / 1.5 / 2.0 leaves _HELDOUT_UNCONTESTED_HITS at 13 in every
#     case, and at 0.85 the ENTIRE paraphrase battery is byte-identical, so a small
#     retune is invisible here and was equally invisible to the `==` pins this
#     replaced.
#     ⚠ RE-MEASURED 2026-09-04 after the second alias round -- those figures are
#     the 2026-08-20 corpus. The live sweep is the table in
#     test_the_paraphrase_battery_can_see_a_ranker_change: the scored arm now
#     reads 16 across 0.5-1.0 and 17 at 0.3, and the downward direction is blind
#     on every arm. The conclusion (small retunes are invisible) still holds.
#     ⚠ CORRECTED: this sentence used to say the contested arm was "the only
#     measured ranker sensitivity in this file", and gave its sweep as
#     14/11/11/12/10. BOTH halves were wrong, and both were contradicted by a table
#     THIS FILE already contained -- see
#     test_the_paraphrase_battery_can_see_a_ranker_change, whose docstring shows the
#     union arm going 10 -> 8 at exponents 1.5 and 2.0, outside its band. The
#     contested arm reads 14/11/11/12/11 (the trailing 10 was copied from a review
#     summary that had already been corrected here). Two arms are ranker-sensitive,
#     two are blind (the scored held-out arm and the equal-budget control), and the
#     must-trip twin now pins that the sensitive ones actually move. The naming axis
#     is guarded separately in tests/test_recall_calibration.py.
# (5) THE BANDS' OWN BLINDNESS, stated because memory/a-live-artifact-test-must-not-
#     pin-its-contents.md -- the doc this instrument answers to -- requires the
#     cruder oracle to be INDEPENDENTLY computed, and these are not. Every relation
#     kept exact here (curve[1] == curve[2], the relational tail bound,
#     union > control, the margin band) is computed by one engine over one corpus in
#     one run, so a regression
#     landing equally on both sides of a contrast is invisible to all of them.
#     A band also cannot separate a one-row tuning event from a one-document drift:
#     same magnitude, no threshold fixes it. The separators are upstream.
# (6) THE TWO IDENTITY SITES IN THIS FILE LOOK LIKE MEMBERS OF THE SAME CLASS AND
#     ARE NOT. Banding them was designed on 2026-08-20 and DROPPED on measurement,
#     which is recorded here because the argument for changing them is persuasive
#     and wrong. test_must_rank_arm_returns_the_right_document and
#     test_every_principle_is_retrievable_by_its_own_name both assert `not wrong`
#     against the live corpus with no constant to adjust, and the margins are
#     genuinely thin: the tightest pinned _MUST_RANK query wins by 4.09%, and
#     principle 7 wins its own name by 0.08% (its failure message still quotes the
#     1.4% that principle 13 measured when it was written; 13 is 0.86% today).
#     ⚠ But thin is not fragile, and the leave-one-out census says so. Across all
#     258 held-out documents, principle-name retrieval NEVER flips -- zero, at any
#     margin. _MUST_RANK flips exactly six times and every one is the document
#     being its OWN expected answer, which is the test working rather than
#     drifting. The probe is not blind: those six ARE the non-vacuity evidence that
#     a zero elsewhere means something.
#     So there is no defect here yet, by STANDING_PRINCIPLES §16 -- nobody is hurt
#     and nothing has flaked. Both arms are also already margin-curated by hand
#     (see _MUST_RANK's own comment, which refuses to pin two correct-but-knife-edge
#     principle answers for exactly this reason). ⚠ HONEST LIMIT: leave-one-out
#     measures REMOVING a document; the risk at a 0.08% margin is an ADDED
#     competitor, which this proxy only approximates. If one of these ever does
#     flake, the fix is a margin-DERIVED split (above-floor pinned to top-1,
#     below-floor degraded to top-3, the split computed and never hand-written),
#     not a wider tolerance and not an exemption roster.
_PARAPHRASE_ARM = (
    ("why should I distrust a green test I did not re-derive", "1."),
    ("is the harness a security boundary", "2."),
    ("do I need to grep-verify what an agent told me", "3."),
    ("the tool printed something odd, can I trust it", "4."),
    ("we found nothing again, is that meaningful", "5."),
    ("the mechanism is sound but how big is the effect", "6."),
    ("how do I know my new test would actually catch the bug", "7."),
    ("I fixed one site, where else does this live", "8."),      # ⚠ CONTESTED (Rule 12)
    ("this came together suspiciously quickly", "9."),
    ("my regex is too broad for the problem", "10."),
    ("can I scope out a defect in my own deliverable", "11."),
    ("the gate passes on the repo I wrote it in", "12."),
    ("should I look at similar files before adding mine", "13."),  # ⚠ CONTESTED (title twin)
    ("my test hardcodes a copy of the list", "14."),
    ("five attempts and it breaks differently every time", "15."),
    ("is this actually a defect or just untidy", "16."),
)

#: The TASK-shaped arm (DEF-699, measured 2026-09-06 and made an instrument arm
#: 2026-09-11). A lane's task text carries the GOAL's vocabulary; the catalog
#: entry that would have saved it carries the HAZARD's, and the two share
#: almost no words -- so `/recall` on the text an executor actually has returns
#: the corpus's largest generic documents. Each row is (the text the executor
#: had at that moment, the FULL `source:` of an entry a red team then found
#: applicable). A query with several applicable entries is several rows: the
#: instrument asks, per entry, whether the front door delivered it.
#:
#: Provenance, per row, because it bounds what the arm measures. TWO label
#: provenances, stated apart: rows marked `2026-09-06 probe` carry the one query
#: of the seven driven that day that a record kept (the DEF-699 probe; the other
#: six were plan step texts and an operator prompt) with the four entries the
#: two red teams then found applicable -- the labels came from the reviews, not
#: from any ranking. Rows marked `2026-09-11 <lane>` are the three Group 3
#: ledger rows run that day: the query is the row's own claim sentence (what an
#: executor reads first) and the label is an entry a HAZARD-WORD `/recall`
#: surfaced and the lane's review then used -- so those labels are reachable by
#: the ranker under some phrasing BY CONSTRUCTION, which biases the arm's rate
#: upward (an applicable entry no query can reach is not in it). Read the rate
#: as an optimistic bound. A row marked TITLE-OVERLAP shares its entry's title
#: tokens, so its hit says the query named the answer, not that the gap closed.
#: Grow this arm one row per lane, at the lane's handoff, with the review's
#: entry and a dated mark (implement-task step 1 says when); rows may be added,
#: never dropped -- `_TASK_ARM_FILED` below ratchets the filed ones. Read by
#: scripts/recall_eval.py by AST; nothing here asserts a rate (they move on
#: documentation commits) -- the number is the instrument's output, recorded in
#: the lane's Landing line.
_TASK_ARM = (
    ("TP-449 Tier 3 group 9, the write-guard layer: the guard's missed spellings "
     "(a quoted verb, the scriptblock Create opener, the FileInfo object API), the "
     "speed bump keyed too coarsely (the MCP bump per session, the discard snapshot "
     "keyed on the Bash tool), a leading cd and the payload cwd resolve a relative "
     "bash write",
     "docs/SHARP_EDGES.md :: An MCP-tool speed-bump predicate must parse the `__` "
     "segments, match the verb as a leading token, and defer local-fs ops to "
     "write_guard"),  # 2026-09-13 group 9 (hazard query: speed bump flag key per tool; applied: the key is the whole tool name)
    ("TP-449 Tier 3 group 9, the write-guard layer: the guard's missed spellings "
     "(a quoted verb, the scriptblock Create opener, the FileInfo object API), the "
     "speed bump keyed too coarsely (the MCP bump per session, the discard snapshot "
     "keyed on the Bash tool), a leading cd and the payload cwd resolve a relative "
     "bash write",
     "docs/sharp-edges/protected-zone-path-equivalence.md"),  # 2026-09-13 group 9 (hazard query: relative path resolved against the repo root after a leading cd; applied: one resolver, never a rival)
    ("Item 4: scripts/ledger_row.py strike and file (PRIOR TEXT, index row, "
     "probe retire/add driven at filing, row_sha, regions --write)",
     "docs/SHARP_EDGES.md :: Markdown Escaped Pipes Silently Drop Matrix Rows"),  # 2026-09-06 probe
    ("Item 4: scripts/ledger_row.py strike and file (PRIOR TEXT, index row, "
     "probe retire/add driven at filing, row_sha, regions --write)",
     "docs/SHARP_EDGES.md :: New Test Files Default to `unit` Silently"),  # 2026-09-06 probe
    ("Item 4: scripts/ledger_row.py strike and file (PRIOR TEXT, index row, "
     "probe retire/add driven at filing, row_sha, regions --write)",
     "docs/SHARP_EDGES.md :: Two operator-doc contracts can collide on one line "
     "— satisfying one breaks the other"),  # 2026-09-06 probe
    ("Item 4: scripts/ledger_row.py strike and file (PRIOR TEXT, index row, "
     "probe retire/add driven at filing, row_sha, regions --write)",
     "docs/SHARP_EDGES.md :: A Hand-Maintained Doc Enumeration With No "
     "Code-Pinned Parity Test Rots Silently"),  # 2026-09-06 probe
    ("When agents finish, the harness records only 'agent X finished' -- none of "
     "their reasoning is kept, so a fan-out session's findings survive only if "
     "retyped by hand.",
     "docs/SHARP_EDGES.md :: tools/cc/ Importing espalier/"),  # 2026-09-11 DEF-586 lane
    ("Once a PR carries the approval marker in its title, a later force-push can "
     "add a brand-new protected-zone change and CI still passes, because approval "
     "is never tied to a specific commit.",
     "docs/SHARP_EDGES.md :: CI Approval Marker — Trust the Trigger, Not the OR"),  # 2026-09-11 DEF-338 lane; ⚠ TITLE-OVERLAP (approval, marker)
    ("The 0-D pre-flight only reports obligations for symbols a pack ADDS or "
     "CHANGES, so a path the pack DELETES declares no obligations even when a "
     "contract tracks it.",
     "docs/SHARP_EDGES.md :: A prefix match that swallows a sibling names the "
     "wrong remedy — confidently"),  # 2026-09-11 DEF-410j lane
    ("TP-449 Tier 2, lane 1: §C8 — derive one inventory of harness-owned files "
     "and make write, claim and uninstall all read it (rows DEF-556, DEF-410d, "
     "DEF-552, plus DEF-737 filed into §C8 by the walk)",
     "docs/SHARP_EDGES.md :: A Parity Contract That Pins Presence, Not "
     "Absence"),  # 2026-09-11 §C8 lane (hazard query: hand-maintained enumeration)
    ("TP-449 Tier 2, lane 2: §C7 — make the pack parser honour the pack's own "
     "markup and report the heading it really matched (rows CONV-2, DEF-430, "
     "DEF-431)",
     "docs/SHARP_EDGES.md :: Striking a pack's Affected-symbols entry with `~~` "
     "withdraws it from the walk — strike only what the pack no longer touches"),  # 2026-09-11 §C7 lane (hazard query: strikethrough struck bullet); heading renamed 2026-09-12 (DEF-779), same entry
    ("TP-449 Tier 2, lane 3: §C20 — the seed-doc banner says what re-init does "
     "(row DEF-432: the header promises \"never overwritten on re-init\" while an "
     "untouched seed is refreshed when the packaged copy changes)",
     "docs/SHARP_EDGES.md :: A skip-if-exists deploy helper has no upgrade-drift "
     "path — an untouched template silently keeps stale bytes across "
     "versions"),  # 2026-09-11 §C20 lane (hazard query: seed doc stamp refresh)
    ("TP-449 Tier 2 lane C17: close DEF-532's two remaining legs -- .claude/skills/ "
     "visible to the ownership views, and promote audit_accuracy._extract_count_for_label "
     "to a public name",
     "docs/SHARP_EDGES.md :: A Hand-Maintained Doc Enumeration With No Code-Pinned Parity Test Rots Silently"),  # 2026-09-11 §C17 lane (hazard query: hand-maintained enumeration)
    ("TP-449 Tier 2 lane C17: close DEF-532's two remaining legs -- .claude/skills/ "
     "visible to the ownership views, and promote audit_accuracy._extract_count_for_label "
     "to a public name",
     "docs/SHARP_EDGES.md :: A Parity Contract That Pins Presence, Not Absence"),  # 2026-09-11 §C17 lane (hazard query: hand-maintained enumeration)
    ("TP-449 Tier 2 lane DEF-410f: raw-existence detectors in espalier/analyze.py "
     "consult one harness-output predicate",
     "docs/SHARP_EDGES.md :: A Hand-Maintained Doc Enumeration With No Code-Pinned Parity Test Rots Silently"),  # 2026-09-12 DEF-410f lane (hazard query: hand-maintained enumeration)
    ("TP-449 Tier 2 lane DEF-410f: raw-existence detectors in espalier/analyze.py "
     "consult one harness-output predicate",
     "docs/SHARP_EDGES.md :: A Parity Contract That Pins Presence, Not Absence"),  # 2026-09-12 DEF-410f lane (hazard query: hand-maintained enumeration)
    ("TP-449 Tier 2 lane A (C6): the read-only diagnostics report the real state "
     "and hand back a usable next step -- doctor after an uninstall, scan names its "
     "reports, init and upgrade name paths not counts, the fuse epilogue on an "
     "unparseable settings file, --help lists the documented verbs",
     "docs/SHARP_EDGES.md :: A Hand-Maintained Doc Enumeration With No Code-Pinned Parity Test Rots Silently"),  # 2026-09-12 C6 lane A (hazard query: hand-maintained enumeration)
    ("TP-449 Tier 2 lane A (C6): the read-only diagnostics report the real state "
     "and hand back a usable next step -- doctor after an uninstall, scan names its "
     "reports, init and upgrade name paths not counts, the fuse epilogue on an "
     "unparseable settings file, --help lists the documented verbs",
     "docs/SHARP_EDGES.md :: A Parity Contract That Pins Presence, Not Absence"),  # 2026-09-12 C6 lane A (hazard query: hand-maintained enumeration)
    ("TP-449 Tier 2 group 4 lane 1 (the driven-verb class): scaffolding-bench "
     "write hygiene, doctor's self-host gate line on a consumer tree, cmd_init's "
     "write_gitignore default, the plan's bodiless agent recommendations at the "
     "surface gate and the init summary, selfcheck --contracts with a marker-aware "
     "upstream-parity compare",
     "docs/SHARP_EDGES.md :: Blueprint JSON Accumulation"),  # 2026-09-12 driven-verb lane (hazard query: a report verb writes files on every run)
    ("TP-449 Tier 2 group 4 lane 1 (the driven-verb class): scaffolding-bench "
     "write hygiene, doctor's self-host gate line on a consumer tree, cmd_init's "
     "write_gitignore default, the plan's bodiless agent recommendations at the "
     "surface gate and the init summary, selfcheck --contracts with a marker-aware "
     "upstream-parity compare",
     "docs/SHARP_EDGES.md :: Advisory reinject rules need the same self-host gate as observers"),  # 2026-09-12 driven-verb lane (hazard query: an internal check name reaches the adopter)
    ("TP-449 Tier 2 group 4 lane 1 (the driven-verb class): scaffolding-bench "
     "write hygiene, doctor's self-host gate line on a consumer tree, cmd_init's "
     "write_gitignore default, the plan's bodiless agent recommendations at the "
     "surface gate and the init summary, selfcheck --contracts with a marker-aware "
     "upstream-parity compare",
     "docs/SHARP_EDGES.md :: The recall corpus must gate harness-internal entries for adopters"),  # 2026-09-12 driven-verb lane (hazard query: an internal check name reaches the adopter)
    ("TP-449 Tier 2 group 4 lane 1 (the driven-verb class): scaffolding-bench "
     "write hygiene, doctor's self-host gate line on a consumer tree, cmd_init's "
     "write_gitignore default, the plan's bodiless agent recommendations at the "
     "surface gate and the init summary, selfcheck --contracts with a marker-aware "
     "upstream-parity compare",
     "docs/STANDING_PRINCIPLES.md :: 14. Derive the list, don't test a hand-written copy of it"),  # 2026-09-12 driven-verb lane (hazard query: a defensive getattr default disagrees with the parser's declared default)
    ("The 2026-08-24 rm re-tier changed both tiers and updated neither tier's "
     "operator text, so the two messages are now inverted against each other.",
     "memory/removing-a-leak-can-break-a-contract-that-rode-on-it.md"),  # 2026-09-12 group 4 lane 3 (hazard query: rm -rf denial reason plain english tier text speedbump; applied: the four pins rode on the old text and were un-pinned first)
    ("The 2026-08-24 rm re-tier changed both tiers and updated neither tier's "
     "operator text, so the two messages are now inverted against each other.",
     "docs/SHARP_EDGES.md :: write_guard Blocks Inline Python Mentioning Dangerous Patterns"),  # 2026-09-12 group 4 lane 3 (hazard query: rm -rf denial reason plain english tier text speedbump; applied: the texts were edited with the Edit tool and the commit message avoids the idiom)
    ("init, doctor, merge-settings, upgrade and fuse spell operator-facing remedies "
     "with _detect_python_command(), the resolver whose answer is what gets WRITTEN "
     "into settings.json",
     "docs/SHARP_EDGES.md :: Closed-Loop Verification Trap"),  # 2026-09-12 group 4 lane 3 (hazard query: remedy interpreter _detect_python_command pasteable command bare python; the failure-mode review's finding 2 -- two tests green only by this host's interpreter -- is this entry)
    ("Every file the harness writes through `atomic_write_text` ends at mode 0600, "
     "whatever it was.",
     "docs/sharp-edges/chmod-444-decision.md"),  # 2026-09-12 group 6 (hazard query: atomic write mode bits; the lane's constraint "the helper imposes no mode policy of its own" is this entry; the claim sentence recalls memory/hook-authoring.md and the atomic-update entry instead)
    ("Every file the harness writes through `atomic_write_text` ends at mode 0600, "
     "whatever it was.",
     "docs/sharp-edges/protected-zone-hardlink-backstop.md"),  # 2026-09-12 group 6 (hazard query: earn the red platform ceiling windows skip; the hardlink leg of the target's identity, documented as a property -- the failure-mode review's finding 8 cites this entry)
    ("The `reset` verb the session banner prescribes leaves an untracked file "
     "nothing ignores.",
     "docs/SHARP_EDGES.md :: A Hand-Maintained Doc Enumeration With No Code-Pinned Parity Test Rots Silently"),  # 2026-09-12 group 6 (hazard query: hand-maintained enumeration; the two set-equal fixture twins of REQUIRED_GITIGNORE both gained the entry)
    ("The `reset` verb the session banner prescribes leaves an untracked file "
     "nothing ignores.",
     "docs/STANDING_PRINCIPLES.md :: 14. Derive the list, don't test a hand-written copy of it"),  # 2026-09-12 group 6 (hazard query: generated doc region; the README and QUICKSTART fences were regenerated, never typed)
    ("The session log carries the Stop gates' blocks and tiers pauses from "
     "refusals; a pin refuses a bound with uncommitted changes and the scan "
     "reads it stale; the reset message names cc/_cold/",
     "docs/SHARP_EDGES.md :: A Hand-Maintained Doc Enumeration With No Code-Pinned Parity Test Rots Silently"),  # 2026-09-12 group 7 (hazard query: hand-maintained enumeration; the pause tier, the HOOKS.md tier column and the funnel rosters are each pinned to code or derived -- the constraint line every list this lane added was written against)
    ("The session log carries the Stop gates' blocks and tiers pauses from "
     "refusals; a pin refuses a bound with uncommitted changes and the scan "
     "reads it stale; the reset message names cc/_cold/",
     "docs/SHARP_EDGES.md :: Hook Exit Codes — Channel XOR"),  # 2026-09-12 group 7 (hazard query: hook exit code channel; the Stop hook's record write must leave stdout to the block JSON and stderr empty -- the code review's WARN and the failure-mode review's m6 were this entry, and three funnels are now proven silent under a real OSError)
    ("TP-449 Tier 2 recall lane: DEF-775 (six recall calibration pins red on main "
     "after the held-pile fold; the tier rule lets a corpus change land on the "
     "contract slice) + DEF-699 (the pull ranker's length norm returns the two "
     "largest record-shaped docs for task-shaped queries)",
     "memory/a-hand-written-count-that-moves-on-ordinary-growth-is-tax.md"),  # 2026-09-12 recall lane (hazard query: pasted eval table tolerance; the four pasted tables were regenerated last, provenance banded)
    ("TP-449 Tier 2 recall lane: DEF-775 (six recall calibration pins red on main "
     "after the held-pile fold; the tier rule lets a corpus change land on the "
     "contract slice) + DEF-699 (the pull ranker's length norm returns the two "
     "largest record-shaped docs for task-shaped queries)",
     "docs/SHARP_EDGES.md :: The recall corpus must gate harness-internal entries for adopters"),  # 2026-09-12 recall lane (hazard query: recall corpus exclusion ranker; the exclusion is proven both ways as that entry prescribes)
    ("TP-449 Tier 2 recall lane: DEF-775 (six recall calibration pins red on main "
     "after the held-pile fold; the tier rule lets a corpus change land on the "
     "contract slice) + DEF-699 (the pull ranker's length norm returns the two "
     "largest record-shaped docs for task-shaped queries)",
     "memory/classify-the-surface-before-measuring-it.md"),  # 2026-09-12 recall lane (hazard query: number word count claim; the ledger left the corpus on the record axis, the aggregate on measurement)
    ("TP-449 Tier 2 recall lane: DEF-775 (six recall calibration pins red on main "
     "after the held-pile fold; the tier rule lets a corpus change land on the "
     "contract slice) + DEF-699 (the pull ranker's length norm returns the two "
     "largest record-shaped docs for task-shaped queries)",
     "memory/recall-keys-on-the-hazard-not-the-task.md"),  # 2026-09-12 recall lane; TITLE-OVERLAP (the query carries `recall` and `task`) -- the task text itself returned this one
    # 2026-09-14/15, lane 2 (the remove/relocate operand class, DEF-795 + DEF-796):
    # the task text recalled the hook-authoring memory, the MCP defer-set entry,
    # the speed-bump atlas and Class-A1; the seven below came only from the
    # hazard queries named in each comment, and each shaped the diff.
    ("Lane 2: C52 as any-mutation -- the operand a verb removes or relocates is "
     "classified on both shells beside the operands it writes and reads (DEF-795 + "
     "DEF-796), the two shell checks renamed to the mutation vocabulary, the "
     "hook-authoring skill's three sentences corrected",
     "docs/SHARP_EDGES.md :: ReDoS budget receipt"),  # hazard query: hook regex adjacent quantifiers ReDoS f-string assembly; applied: bounded spans, `+` composition, a row per new pattern (and a pre-existing quadratic opener found by one)
    ("Lane 2: C52 as any-mutation -- the operand a verb removes or relocates is "
     "classified on both shells beside the operands it writes and reads (DEF-795 + "
     "DEF-796), the two shell checks renamed to the mutation vocabulary, the "
     "hook-authoring skill's three sentences corrected",
     "docs/SHARP_EDGES.md :: A new pattern-detector trips the harness's own defenses"),  # hazard query: the same; applied: fixtures through the Write tool, the shadowing grep, the census and dead-rule audit learn the new arms
    ("Lane 2: C52 as any-mutation -- the operand a verb removes or relocates is "
     "classified on both shells beside the operands it writes and reads (DEF-795 + "
     "DEF-796), the two shell checks renamed to the mutation vocabulary, the "
     "hook-authoring skill's three sentences corrected",
     "docs/sharp-edges/marker-classification-grows-grandfather-tuple.md"),  # hazard query: test marker taxonomy security; applied: a class in an existing file, no marker change
    ("Lane 2: C52 as any-mutation -- the operand a verb removes or relocates is "
     "classified on both shells beside the operands it writes and reads (DEF-795 + "
     "DEF-796), the two shell checks renamed to the mutation vocabulary, the "
     "hook-authoring skill's three sentences corrected",
     "docs/SHARP_EDGES.md :: Markdown Escaped Pipes Silently Drop Matrix Rows"),  # hazard query: escaped pipes ledger table; applied: no bare pipe in the plan's --steps texts or a ledger cell
    ("Lane 2: C52 as any-mutation -- the operand a verb removes or relocates is "
     "classified on both shells beside the operands it writes and reads (DEF-795 + "
     "DEF-796), the two shell checks renamed to the mutation vocabulary, the "
     "hook-authoring skill's three sentences corrected",
     "docs/SHARP_EDGES.md :: A Hand-Maintained Doc Enumeration With No "
     "Code-Pinned Parity Test Rots Silently"),  # hazard query: hand-maintained enumeration; applied: the shipped prose names the class by effect and cites the derived test class as the oracle
    ("Lane 2: C52 as any-mutation -- the operand a verb removes or relocates is "
     "classified on both shells beside the operands it writes and reads (DEF-795 + "
     "DEF-796), the two shell checks renamed to the mutation vocabulary, the "
     "hook-authoring skill's three sentences corrected",
     "memory/asset-mirroring.md"),  # hazard query: asset mirroring sync claude mirrors; applied: SoT edits only, then the three sync scripts
    ("Lane 2: C52 as any-mutation -- the operand a verb removes or relocates is "
     "classified on both shells beside the operands it writes and reads (DEF-795 + "
     "DEF-796), the two shell checks renamed to the mutation vocabulary, the "
     "hook-authoring skill's three sentences corrected",
     "docs/SHARP_EDGES.md :: The mirror whose SoT is the packaged copy"),  # hazard query: sync vendor cc mirror parity; applied: the vendor sync after every hook edit, never a mirror by hand
    ("Lane 5 of the Windows-walk findings: paths rendered through repr in operator "
     "text (a class), no KeyboardInterrupt handler at the wire prompt, the "
     "resolver's evidence probe last-wins, and the below-floor remedy spells the "
     "broken interpreter",
     "docs/SHARP_EDGES.md :: An AST content-scanner gated on a call-name allowlist is blind to every user-facing sink the allowlist omits"),  # 2026-09-15 lane 5 (hazard query: operator-facing string non-ASCII portability contract new message; applied: the OSError pin keys on the except binding, never on a print/log call-name list)
    ("Lane 5 of the Windows-walk findings: paths rendered through repr in operator "
     "text (a class), no KeyboardInterrupt handler at the wire prompt, the "
     "resolver's evidence probe last-wins, and the below-floor remedy spells the "
     "broken interpreter",
     "docs/SHARP_EDGES.md :: Closed-Loop Verification Trap"),  # 2026-09-15 lane 5 (hazard query: remedy interpreter spelled through _remedy_py; applied: every new pin reads the AST, never the rendered message, which on POSIX with a plain path agrees with the fix)
    ("Lane 5 of the Windows-walk findings: paths rendered through repr in operator "
     "text (a class), no KeyboardInterrupt handler at the wire prompt, the "
     "resolver's evidence probe last-wins, and the below-floor remedy spells the "
     "broken interpreter",
     "docs/SHARP_EDGES.md :: tools/cc/ Importing espalier/"),  # 2026-09-15 lane 5 (hazard query: byte-twin helper tools/cc cannot import espalier; applied: the helper is twinned in _json_safe behind a parity pin, never imported across the boundary)
    ("Lane 5 of the Windows-walk findings: paths rendered through repr in operator "
     "text (a class), no KeyboardInterrupt handler at the wire prompt, the "
     "resolver's evidence probe last-wins, and the below-floor remedy spells the "
     "broken interpreter",
     "docs/SHARP_EDGES.md :: Every scanner must ship with an earn-the-gate fixture"),  # 2026-09-15 lane 5 (hazard query: AST census pin allowlist argued exemption every exemption is a live site; applied: each pin carries red and quiet fixtures and its red was measured on HEAD in a worktree, 95 sites)
    ("Lane 7 of the Windows-walk findings: the uninstall report keeps a harness "
     "gitignore line for an operator file it never names, and the settings backup "
     "ladder is unbounded and the uninstall report never counts it",
     "docs/STANDING_PRINCIPLES.md :: 14. Derive the list, don't test a hand-written copy of it"),  # 2026-09-15 lane 7 (hazard query: hand-maintained enumeration two lists answer the same question derive the inventory; applied: the witness test plants one survivor per REQUIRED_GITIGNORE entry from the entry's own grammar, never a typed list)
    ("Lane 7 of the Windows-walk findings: the uninstall report keeps a harness "
     "gitignore line for an operator file it never names, and the settings backup "
     "ladder is unbounded and the uninstall report never counts it",
     "docs/SHARP_EDGES.md :: A Hand-Maintained Doc Enumeration With No Code-Pinned Parity Test Rots Silently"),  # 2026-09-15 lane 7 (same hazard query; applied: the ladder grammar is spelled once in managed_inventory.settings_backup_rung and read by the predicate, the wire's scan and the report)
    ("Lane 9 of the Windows-walk findings: four walk-operator hazards, each a "
     "confident wrong answer rather than an error, with no catalog entry",
     "docs/SHARP_EDGES.md :: The doc line-anchor scanner can read prose as a stale anchor"),  # 2026-09-15 lane 9 (hazard query: line anchors in reference docs stale; applied: the four entries carry no symbol+file:NN anchor, only the walk row ids)
    ("DEF-820: the BOM census in tests/test_settings_reader_bom_contract.py marks a read "
     "guarded when a helper's name appears anywhere in the enclosing function; re-key "
     "guarded on dataflow -- the read call nested in a BOM helper's argument, or the name "
     "it is assigned to reaching a helper's argument in the same function -- so a second "
     "strict read beside a guarded one reports unguarded",
     "docs/SHARP_EDGES.md :: A new pattern-detector trips the harness's own defenses"),  # 2026-09-16 DEF-820 (hazard query: AST census contract test earn the red vacuous instrument; applied: the census's own parents dictionary tripped the magic-depth scanner in the tier, renamed parent_of)
    ("DEF-827: the PowerShell find head reads the call operator on a command-object "
     "sub-expression so the sweep meets the wall; the variable-bound spelling stays a "
     "declared limit; the two KNOWN_GAPS entries leave on purpose",
     "docs/SHARP_EDGES.md :: A New Guard Is Blind The Way It Claims To See"),  # 2026-09-16 DEF-827 (hazard query: PowerShell call operator command object sub-expression exe prefix head regex quantifiers; applied: every docstring names the driven spellings and the declared limits, each limit a DECLARED matrix row)
    ("DEF-827: the PowerShell find head reads the call operator on a command-object "
     "sub-expression so the sweep meets the wall; the variable-bound spelling stays a "
     "declared limit; the two KNOWN_GAPS entries leave on purpose",
     "docs/SHARP_EDGES.md :: ReDoS budget receipt"),  # 2026-09-16 DEF-827 (hazard query: regex adjacent quantifiers mutually exclusive ReDoS bounded prefix; applied: six repeated-head rows registered the day the two resolvers landed, every adjacent quantifier pair exclusive)
    ("TP-452 1-B decision 1: in scripts/ledger_rebuild_assemble.py a verdict whose "
     "section is extra (the §1/§3/§4/§5 lane's) is routed by id onto the §2 member "
     "row that shares the id, and step 3 skips the extra row because the id is in "
     "class_ids; route by the verdict's section; fixture: a §1 twin row sharing the "
     "two-id member row's id pair",
     "docs/SHARP_EDGES.md :: Markdown Escaped Pipes Silently Drop Matrix Rows"),  # 2026-09-20 TP-452 1-B co-id routing (hazard query: escaped pipes markdown table cell; the task query returned hook authoring, named_unit, the speed-bump atlas and a stale egg-info; applied: every cell read goes through _UNESCAPED_PIPE, no bare pipe in a fixture cell -- and the plan tool's --steps split on the pipe the constraint quoted)
    ("DEF-922 class fix: every wall-clock bound in the serial timing files is a named ceiling at ten times a named dated floor, derived by a contract; the PS body row gets a chain tier and a scaling arm; both CI matrices stop cancelling siblings",
     "docs/sharp-edges/the-measuring-instrument-is-a-claim-too.md"),  # 2026-09-24 DEF-922 (hazard query: wall-clock ceiling timing test floor CI runner; applied: the population floor asserted before the verdict, the floors as the minimum of three passes at a noted load, and the grep that miscounted test_hooks.py's bound as zero caught by the AST walk)
    ("DEF-922 class fix: every wall-clock bound in the serial timing files is a named ceiling at ten times a named dated floor, derived by a contract; the PS body row gets a chain tier and a scaling arm; both CI matrices stop cancelling siblings",
     "docs/SHARP_EDGES.md :: A Parity Contract That Pins Presence, Not Absence"),  # 2026-09-24 DEF-922 (hazard query: hand-maintained enumeration derived population contract test; applied: a paired ceiling no row asserts reds, and a high-water mark nothing pairs reds)
    ("DEF-922 class fix: every wall-clock bound in the serial timing files is a named ceiling at ten times a named dated floor, derived by a contract; the PS body row gets a chain tier and a scaling arm; both CI matrices stop cancelling siblings",
     "docs/STANDING_PRINCIPLES.md :: 14. Derive the list, don't test a hand-written copy of it"),  # 2026-09-24 DEF-922 (hazard query: hand-maintained enumeration derived population contract test; applied: the sites from the AST, the file list from proof_tier, the matrices from the workflow glob)
)

#: The ratchet: every (query, source) pair filed on 2026-09-11, and every row a
#: later lane files, as a LITERAL snapshot rather than a count. A count floor
#: lets a later session drop every miss and keep the rate up; a snapshot lets
#: the arm grow freely and no filed row disappear. A lane that adds rows to
#: _TASK_ARM adds them here too and bumps the count pin in
#: tests/test_recall_eval.py in the same commit (2026-09-12: the recall lane's
#: four rows had landed outside the ratchet, so they could have been dropped
#: silently); shrink it only when a row is retired with a reason. A source
#: string follows its heading when the heading is renamed (DEF-779) -- the
#: corpus-source pin reds until it does -- and that is the same row, not a
#: retirement.
_TASK_ARM_FILED = frozenset({
    # 2026-09-15, lane 5 (paths as paths; Ctrl+C at the wire prompt; the resolver's
    # evidence; the below-floor remedy): four rows
    *[("Lane 5 of the Windows-walk findings: paths rendered through repr in operator "
     "text (a class), no KeyboardInterrupt handler at the wire prompt, the "
     "resolver's evidence probe last-wins, and the below-floor remedy spells the "
     "broken interpreter", source) for source in (
        "docs/SHARP_EDGES.md :: An AST content-scanner gated on a call-name allowlist is blind to every user-facing sink the allowlist omits",
        "docs/SHARP_EDGES.md :: Closed-Loop Verification Trap",
        "docs/SHARP_EDGES.md :: tools/cc/ Importing espalier/",
        "docs/SHARP_EDGES.md :: Every scanner must ship with an earn-the-gate fixture",
    )],
    # 2026-09-15, lane 2 (the remove/relocate operand class): seven rows
    *[("Lane 2: C52 as any-mutation -- the operand a verb removes or relocates is "
       "classified on both shells beside the operands it writes and reads (DEF-795 + "
       "DEF-796), the two shell checks renamed to the mutation vocabulary, the "
       "hook-authoring skill's three sentences corrected", source) for source in (
        "docs/SHARP_EDGES.md :: ReDoS budget receipt",
        "docs/SHARP_EDGES.md :: A new pattern-detector trips the harness's own defenses",
        "docs/sharp-edges/marker-classification-grows-grandfather-tuple.md",
        "docs/SHARP_EDGES.md :: Markdown Escaped Pipes Silently Drop Matrix Rows",
        "docs/SHARP_EDGES.md :: A Hand-Maintained Doc Enumeration With No "
        "Code-Pinned Parity Test Rots Silently",
        "memory/asset-mirroring.md",
        "docs/SHARP_EDGES.md :: The mirror whose SoT is the packaged copy",
    )],
    ("Item 4: scripts/ledger_row.py strike and file (PRIOR TEXT, index row, "
     "probe retire/add driven at filing, row_sha, regions --write)",
     "docs/SHARP_EDGES.md :: Markdown Escaped Pipes Silently Drop Matrix Rows"),
    ("Item 4: scripts/ledger_row.py strike and file (PRIOR TEXT, index row, "
     "probe retire/add driven at filing, row_sha, regions --write)",
     "docs/SHARP_EDGES.md :: New Test Files Default to `unit` Silently"),
    ("Item 4: scripts/ledger_row.py strike and file (PRIOR TEXT, index row, "
     "probe retire/add driven at filing, row_sha, regions --write)",
     "docs/SHARP_EDGES.md :: Two operator-doc contracts can collide on one line "
     "— satisfying one breaks the other"),
    ("Item 4: scripts/ledger_row.py strike and file (PRIOR TEXT, index row, "
     "probe retire/add driven at filing, row_sha, regions --write)",
     "docs/SHARP_EDGES.md :: A Hand-Maintained Doc Enumeration With No "
     "Code-Pinned Parity Test Rots Silently"),
    ("When agents finish, the harness records only 'agent X finished' -- none of "
     "their reasoning is kept, so a fan-out session's findings survive only if "
     "retyped by hand.",
     "docs/SHARP_EDGES.md :: tools/cc/ Importing espalier/"),
    ("Once a PR carries the approval marker in its title, a later force-push can "
     "add a brand-new protected-zone change and CI still passes, because approval "
     "is never tied to a specific commit.",
     "docs/SHARP_EDGES.md :: CI Approval Marker — Trust the Trigger, Not the OR"),
    ("The 0-D pre-flight only reports obligations for symbols a pack ADDS or "
     "CHANGES, so a path the pack DELETES declares no obligations even when a "
     "contract tracks it.",
     "docs/SHARP_EDGES.md :: A prefix match that swallows a sibling names the "
     "wrong remedy — confidently"),
    ("TP-449 Tier 2, lane 1: §C8 — derive one inventory of harness-owned files "
     "and make write, claim and uninstall all read it (rows DEF-556, DEF-410d, "
     "DEF-552, plus DEF-737 filed into §C8 by the walk)",
     "docs/SHARP_EDGES.md :: A Parity Contract That Pins Presence, Not "
     "Absence"),
    ("TP-449 Tier 2, lane 2: §C7 — make the pack parser honour the pack's own "
     "markup and report the heading it really matched (rows CONV-2, DEF-430, "
     "DEF-431)",
     "docs/SHARP_EDGES.md :: Striking a pack's Affected-symbols entry with `~~` "
     "withdraws it from the walk — strike only what the pack no longer touches"),  # source string follows the 2026-09-12 heading rename (DEF-779); the filed row is the same entry, not a retirement
    ("TP-449 Tier 2, lane 3: §C20 — the seed-doc banner says what re-init does "
     "(row DEF-432: the header promises \"never overwritten on re-init\" while an "
     "untouched seed is refreshed when the packaged copy changes)",
     "docs/SHARP_EDGES.md :: A skip-if-exists deploy helper has no upgrade-drift "
     "path — an untouched template silently keeps stale bytes across "
     "versions"),
    ("TP-449 Tier 2 lane C17: close DEF-532's two remaining legs -- .claude/skills/ "
     "visible to the ownership views, and promote audit_accuracy._extract_count_for_label "
     "to a public name",
     "docs/SHARP_EDGES.md :: A Hand-Maintained Doc Enumeration With No Code-Pinned Parity Test Rots Silently"),
    ("TP-449 Tier 2 lane C17: close DEF-532's two remaining legs -- .claude/skills/ "
     "visible to the ownership views, and promote audit_accuracy._extract_count_for_label "
     "to a public name",
     "docs/SHARP_EDGES.md :: A Parity Contract That Pins Presence, Not Absence"),
    # Filed by the 2026-09-12 recall lane (the ratchet grows with the arm; the
    # count pin in tests/test_recall_eval.py is bumped in the same commit).
    ("TP-449 Tier 2 recall lane: DEF-775 (six recall calibration pins red on main "
     "after the held-pile fold; the tier rule lets a corpus change land on the "
     "contract slice) + DEF-699 (the pull ranker's length norm returns the two "
     "largest record-shaped docs for task-shaped queries)",
     "memory/a-hand-written-count-that-moves-on-ordinary-growth-is-tax.md"),
    ("TP-449 Tier 2 recall lane: DEF-775 (six recall calibration pins red on main "
     "after the held-pile fold; the tier rule lets a corpus change land on the "
     "contract slice) + DEF-699 (the pull ranker's length norm returns the two "
     "largest record-shaped docs for task-shaped queries)",
     "docs/SHARP_EDGES.md :: The recall corpus must gate harness-internal entries for adopters"),
    ("TP-449 Tier 2 recall lane: DEF-775 (six recall calibration pins red on main "
     "after the held-pile fold; the tier rule lets a corpus change land on the "
     "contract slice) + DEF-699 (the pull ranker's length norm returns the two "
     "largest record-shaped docs for task-shaped queries)",
     "memory/classify-the-surface-before-measuring-it.md"),
    ("TP-449 Tier 2 recall lane: DEF-775 (six recall calibration pins red on main "
     "after the held-pile fold; the tier rule lets a corpus change land on the "
     "contract slice) + DEF-699 (the pull ranker's length norm returns the two "
     "largest record-shaped docs for task-shaped queries)",
     "memory/recall-keys-on-the-hazard-not-the-task.md"),
    ("TP-449 Tier 3 group 9, the write-guard layer: the guard's missed spellings "
     "(a quoted verb, the scriptblock Create opener, the FileInfo object API), the "
     "speed bump keyed too coarsely (the MCP bump per session, the discard snapshot "
     "keyed on the Bash tool), a leading cd and the payload cwd resolve a relative "
     "bash write",
     "docs/SHARP_EDGES.md :: An MCP-tool speed-bump predicate must parse the `__` "
     "segments, match the verb as a leading token, and defer local-fs ops to "
     "write_guard"),
    ("TP-449 Tier 3 group 9, the write-guard layer: the guard's missed spellings "
     "(a quoted verb, the scriptblock Create opener, the FileInfo object API), the "
     "speed bump keyed too coarsely (the MCP bump per session, the discard snapshot "
     "keyed on the Bash tool), a leading cd and the payload cwd resolve a relative "
     "bash write",
     "docs/sharp-edges/protected-zone-path-equivalence.md"),
    # 2026-09-15, lanes 7 and 9 (the uninstall report's witness and the backup
    # ladder; four walk hazards catalogued): three rows
    *[("Lane 7 of the Windows-walk findings: the uninstall report keeps a harness "
       "gitignore line for an operator file it never names, and the settings backup "
       "ladder is unbounded and the uninstall report never counts it", source) for source in (
        "docs/STANDING_PRINCIPLES.md :: 14. Derive the list, don't test a hand-written copy of it",
        "docs/SHARP_EDGES.md :: A Hand-Maintained Doc Enumeration With No Code-Pinned Parity Test Rots Silently",
    )],
    ("Lane 9 of the Windows-walk findings: four walk-operator hazards, each a "
     "confident wrong answer rather than an error, with no catalog entry",
     "docs/SHARP_EDGES.md :: The doc line-anchor scanner can read prose as a stale anchor"),
    # 2026-09-16, DEF-820 (the BOM census guard keyed on the read's own dataflow): one row
    ("DEF-820: the BOM census in tests/test_settings_reader_bom_contract.py marks a read "
     "guarded when a helper's name appears anywhere in the enclosing function; re-key "
     "guarded on dataflow -- the read call nested in a BOM helper's argument, or the name "
     "it is assigned to reaching a helper's argument in the same function -- so a second "
     "strict read beside a guarded one reports unguarded",
     "docs/SHARP_EDGES.md :: A new pattern-detector trips the harness's own defenses"),
    # 2026-09-16, DEF-827 (a discovered command read as the command it names): two rows
    *[("DEF-827: the PowerShell find head reads the call operator on a command-object "
       "sub-expression so the sweep meets the wall; the variable-bound spelling stays a "
       "declared limit; the two KNOWN_GAPS entries leave on purpose", source) for source in (
        "docs/SHARP_EDGES.md :: A New Guard Is Blind The Way It Claims To See",
        "docs/SHARP_EDGES.md :: ReDoS budget receipt",
    )],
    # 2026-09-20, TP-452 1-B (the co-id routing fix in the rebuild assembler): one row
    ("TP-452 1-B decision 1: in scripts/ledger_rebuild_assemble.py a verdict whose "
     "section is extra (the §1/§3/§4/§5 lane's) is routed by id onto the §2 member "
     "row that shares the id, and step 3 skips the extra row because the id is in "
     "class_ids; route by the verdict's section; fixture: a §1 twin row sharing the "
     "two-id member row's id pair",
     "docs/SHARP_EDGES.md :: Markdown Escaped Pipes Silently Drop Matrix Rows"),
    # 2026-09-24, DEF-922 (the wall-clock rule derived by a contract): three rows
    ("DEF-922 class fix: every wall-clock bound in the serial timing files is a named ceiling at ten times a named dated floor, derived by a contract; the PS body row gets a chain tier and a scaling arm; both CI matrices stop cancelling siblings",
     "docs/sharp-edges/the-measuring-instrument-is-a-claim-too.md"),
    ("DEF-922 class fix: every wall-clock bound in the serial timing files is a named ceiling at ten times a named dated floor, derived by a contract; the PS body row gets a chain tier and a scaling arm; both CI matrices stop cancelling siblings",
     "docs/SHARP_EDGES.md :: A Parity Contract That Pins Presence, Not Absence"),
    ("DEF-922 class fix: every wall-clock bound in the serial timing files is a named ceiling at ten times a named dated floor, derived by a contract; the PS body row gets a chain tier and a scaling arm; both CI matrices stop cancelling siblings",
     "docs/STANDING_PRINCIPLES.md :: 14. Derive the list, don't test a hand-written copy of it"),
})

#: Characterisation counts, all pinned with `==`. Re-measured 2026-08-19 at a budget
#: matched on DELIVERED CANDIDATES -- which two successive drafts failed to do, in two
#: different ways, and that is the instructive part of this block.
#:
#: Draft 1 asserted `union_hits > single_hits` with the union at top=2 and the control
#: at top=1. Plainly void: recall@2 against recall@1 cannot lose.
#:
#: Draft 2 "fixed" it by giving both arms `top=2` -- and was STILL void, because `top`
#: does not mean the same thing to the two functions. `recall(top=k)` returns up to k
#: hits; `recall_union(top=k)` scores under BOTH normalisations and returns up to 2k,
#: deduplicated. Measured 2026-08-19 on this arm, against that day's 274-heading naming
#: denominator (nothing regenerates this table), when the defect was found: the union delivered
#: 3.69 candidates per query against the control's 2.00 (3.56 on 2026-08-19 -- the ratio
#: moves with the corpus, the defect does not). Draft 2 looked matched, asserted
#: matched-ness in its own test NAME, and was off by 84% at the time, 78% on 2026-08-19. That is
#: the worse failure of the two -- draft 1 was visibly lopsided, draft 2 invisibly so.
#:
#: The honest control is recall(top=4): 4.00 candidates per query, which OVER-budgets
#: the control against the union's 3.56 and so argues a fortiori. Scored that way and
#: indexed by what the caller actually receives:
#:
#:     ranker                cands/q   paraphrase   naming(any)   naming(elem 0)
#:     recall(top=1)            1.00       6/16       233/274        233/274
#:     recall(top=2)            2.00       7/16       262/274        233/274
#:     recall(top=3)            3.00       8/16       265/274        233/274
#:     recall(top=4)  CONTROL   4.00       8/16       269/274        233/274
#:     recall(top=6)            6.00       8/16       270/274        233/274
#:     recall_union(top=1)      1.81       9/16       233/274        233/274
#:     recall_union(top=2)      3.56      10/16       262/274        233/274  <- shipped
#:     recall_union(top=3)      5.12      10/16       265/274        233/274
#:
#: ⚠ RE-DERIVED after document expansion landed (docs/STANDING_PRINCIPLES.aliases.md),
#: and the shape of the result changed in a way worth stating: aliases lift the SINGLE
#: ranker from 1/16 to 6/16 at top=1, so expansion is partly a SUBSTITUTE for the
#: second normalisation rather than a complement. The union's margin over the honest
#: control narrowed from +4 (8 vs 4) to +2 (10 vs 8). It still wins, from fewer
#: candidates, and the naming column is untouched -- but a future round that improves
#: expansion further should re-ask whether the second pass still earns its place,
#: which is what the strict `==` on both constants below exists to force.
#:
#: ⚠ THIS IS A TRADE, NOT DOMINANCE -- and an earlier revision of this very comment
#: said "strictly dominant at every matched tier" while the naming column two lines
#: above it said otherwise. At every matched tier the union WINS paraphrase and LOSES
#: naming(any) to the slot-widened control: -29 at ~2, -7 at ~4, -5 at ~6. Writing
#: "dominant" here, inside the block correcting a budget claim, was §5.15's own
#: mechanism recurring -- reporting the axis the challenger wins.
#:
#: What IS true, and is the real justification for shipping the union:
#:   * At the SAME k the second normalisation costs nothing. union(k) naming(any) is
#:     IDENTICAL to recall(k)'s -- 233 / 262 / 265 at k = 1, 2, 3 -- because pass 1 is
#:     recall() and pass 2 only adds members (interleaved, never displacing one).
#:     The paraphrase gain is free at fixed k.
#:   * element 0 is 233/274 in EVERY configuration in the table. A caller that reads
#:     one answer is unaffected by any of this.
#:   * So the choice at ~4 candidates is: +2 paraphrase (union) or +7 naming (control).
#:     Taken deliberately -- naming is 95.6% and paraphrase 62.5% against the
#:     control's 50%, so the failing axis is still the one the union buys. ⚠ The
#:     margin was +4 before document expansion; aliases lift the single ranker too.
#:
#: ⚠ THE CONCLUSION SURVIVING DOES NOT MAKE THE CORRECTION OPTIONAL. When the budget
#: was corrected, the control constant did not move off 4 -- purely because recall's
#: paraphrase curve was then FLAT at 4/16 across top=2/3/4. Had it not been flat,
#: draft 2's headline would have been wrong as well as unearned: it survived on a
#: property of the corpus, not on the method. (The curve has since moved to 7 -> 8 -> 8
#: and the constant to 8, which is exactly why leaving the reasoning here rather than
#: only the number matters.) docs/FAILURE_MODES.md §5.15.
#:
#: ⚠ DENOMINATOR NOTE, so the naming column is not read as a regression. 274 is the
#: heading-derived label set built the way tests/test_recall_calibration.py builds it.
#: Earlier revisions of this table used /282 -- the CORPUS doc count at the time of
#: that revision (the corpus grows with every memory note; the count is not pinned
#: here because it is not the denominator). Different denominator, not drift: the
#: rates are consistent and marginally better (83.7% -> 85.0% at elem 0).
_PARAPHRASE_UNION_HITS = 10

#: The EQUAL-BUDGET control. Without this constant the headline is unearned: it is
#: what separates "the second NORMALISATION helps" from "more SLOTS help". The
#: distinction has teeth precisely because more slots demonstrably do NOT help here.
_PARAPHRASE_CONTROL_HITS = 8

#: The control's `top`, named rather than inlined so the budget guard below and the
#: headline cannot drift apart. 4, not 2 -- see the table.
_PARAPHRASE_CONTROL_TOP = 4

#: The SHIPPED union's `top`, named for the same reason -- and the first revision of
#: this block applied that reasoning to the control only, leaving the union side as
#: two independent literals. Demonstrated consequence: bumping the shipped union to
#: top=3 and honestly re-pinning the hit count left the budget guard GREEN while the
#: challenger ran 39% over the control. Threading one constant closes it.
#: Must track tools/cc/hooks/_recall.py's CLI shim.
_PARAPHRASE_UNION_TOP = 2

#: The plateau, pinned, because it is load-bearing for two separate conclusions:
#: (a) the control constant did not move when the budget was corrected -- luck, and
#:     worth knowing it was luck; and
#: (b) widening recall() SATURATES: it climbs 7 -> 8 between top=2 and top=3, then
#:     is flat through top=4 and top=6. So a third slot is worth exactly one hit and
#:     a fourth is worth none. The union saturates too -- 10/16 at both top=2 and
#:     top=3 -- so neither ranker has slot headroom left, and the residue has to be
#:     attacked by expansion or navigation rather than by another candidate.
#: ⚠ This pin USED to read ((2,4),(3,4),(4,4)) -- genuinely flat -- and the test
#: above it was named "..._more_slots_do_not_buy_paraphrase_reach". Document
#: expansion moved the curve, so that name became false and was changed. Kept as a
#: note because a pin whose NAME encodes an interpretation will outlive the
#: interpretation: docs/FAILURE_MODES.md §5.15.
#: ⚠ Re-pinned 2026-08-20 from ((2,7),(3,8),(4,8)) after ONE new memory/ doc landed
#: (memory/publish-from-a-generated-public-repo.md). Slot 2 fell 7 -> 6; slots 3 and
#: 4 did not move. The claim this pin carries is the PLATEAU, and it survives: the
#: curve still climbs then stops dead, 6 -> 8 -> 8. The test's own refutation
#: condition is a RISE (more slots buying reach); a fall at the first slot is corpus
#: drift, not a change of interpretation.
#: ⚠ Worth knowing before the next memory/ file: this pin is sensitive to a SINGLE
#: added corpus document, so it will red on ordinary documentation work. That is a
#: property of the pin, not a defect in the engine -- but if it reds a third time
#: for the same reason, the pin is measuring corpus size and needs re-deriving as a
#: shape (climbs-then-flat) rather than as three literals.
#: ⚠ 2026-08-20: the `top=6` leg was ADDED, not loosened. The prose above has
#: claimed "flat through top=4 and top=6" since it was written while the pin swept
#: only 2/3/4, so the sixth slot was an unasserted claim.
#: ⚠ AND ADDING IT WAS NOT FREE, which is the part worth inheriting. It was first
#: given the same EXACT flat-tail assertion as slots 3 and 4, on reasoning rather
#: than measurement. Driven the same day: held-out documents take the curve to
#: [7, 8, 8, 9] or [6, 8, 8, 9], moving the sixth slot ALONE. The full census
#: settles the size: across all 258 documents slots 3 and 4 never disagree ONCE,
#: while SIX documents move the sixth slot -- and all six are in memory/, 6 of 58,
#: better than one tier document in ten. So the leg added as "a strengthening" was
#: the single most corpus-fragile assertion in the file, on the tier this harness
#: writes to most. It is therefore bounded relationally in the test body, not
#: pinned -- and the level itself is banded like every other level here.
#: (An earlier revision of this note said "two", which was the count from a
#: five-document spot check rather than from the census. Same defect as the one
#: the note is about: a number recorded before the measurement that would settle it.)
#: (top, hits) for recall(). Slot 3 fell 8 -> 7 on 2026-09-03 when ONE new
#: docs/SHARP_EDGES.md entry (the `Read()`-deny-rule edge) entered the corpus and
#: displaced a STANDING_PRINCIPLES hit at that slot. A/B'd, not inferred: with
#: the entry the curve is [6, 7, 8, 8]; with that one file's diff stashed it is
#: [6, 8, 8, 8], the previous pin exactly. The plateau therefore begins at the
#: FOURTH slot now, not the third -- see the test's docstring for why the
#: headline argument still holds.
#: ⚠ RE-DERIVED 2026-09-04 after the second blind alias round: [7, 7, 8, 9].
#: Document expansion lifted slot 2 (6 -> 7) and the SIXTH slot (8 -> 9), so
#: the single ranker no longer plateaus within six slots at all. The headline
#: survives on a different leg -- the union still beats a six-slot control --
#: and the test now asserts that leg directly instead of a flat tail.
#: ⚠ RE-DERIVED 2026-09-05 after STANDING_PRINCIPLES §18 was rewritten ("Fix the
#: class in place; file only what needs its own oracle"): [7, 7, 9, 9]. Slot 4
#: rose 8 -> 9. A/B'd, not inferred: the aliases twin's three new §18 phrasings
#: stashed alone leave [7, 7, 9, 9]; stashing the principle's own body as well
#: restores [7, 7, 8, 9] exactly, so the body's vocabulary moved a paraphrase
#: from the sixth slot to the fourth. The union-over-control margin is unchanged.
#: ⚠ RE-DERIVED 2026-09-12 after the pull ranker stopped indexing two memory/
#: notes (PULL_EXCLUDED_MEMORY_NOTES in _recall.py): [7, 8, 9, 10]. A/B'd per
#: note, not inferred: the convergence ledger alone gives [7, 8, 9, 10] (it had
#: held one paraphrase query's third slot and another's sixth), the
#: pack-authoring note alone [7, 7, 9, 10] (the sixth slot only, the same hit),
#: both together [7, 8, 9, 10]. The union stays at 10 and the four-slot control
#: at 9 under every variant, so what moved is recall()'s deep reach, not the
#: front door -- see the six-slot test's docstring for what that does to its
#: headline.
#: ⚠ RE-DERIVED 2026-09-22 in two parts. At HEAD `1025ced`, BEFORE this lane's
#: folds, the curve was already [7, 7, 8, 9] (driven on a --shared clone at that
#: commit): the 2026-09-12 record had drifted one hit at slots 3, 4 and 6 under
#: ordinary corpus growth, inside every band (margin 1), so nothing red. Then the
#: six held reflect keys folded into seven corpus files: [7, 7, 8, 8]. A/B'd per
#: file on a scratch copy, not inferred: reverting
#: memory/convergence-review-protocol.md alone restores [7, 7, 8, 9] and each of
#: the other six leaves [7, 7, 8, 8] -- its new filing-pipeline section now ranks
#: fourth for "I fixed one site, where else does this live" (a CONTESTED row)
#: and §8 seventh. The union stays at 10 under every variant, so what moved is
#: recall()'s deep reach on one contested row, not the front door.
_PARAPHRASE_PLATEAU = ((2, 7), (3, 7), (4, 8), (6, 8))  # (top, hits) for recall()

#: union(top=_PARAPHRASE_UNION_TOP) minus recall(top=6) on the paraphrase arm --
#: the headline's actual claim ("handed more candidates and still loses"),
#: recorded as a margin; the DIRECTION is asserted separately and unbanded
#: (a tie reds), this constant only bands the margin's drift. 2026-09-04: 10 - 9 = 1.
#: 2026-09-12: 10 - 10 = 0, and the direction leg is now "never below" -- the
#: single ranker's deep reach rose when two aggregates left the corpus, the
#: union did not move, so the headline is parity at under four lines against
#: six (the test's docstring carries the re-derivation). 2026-09-22: 10 - 8 = 2
#: -- the single ranker's deep reach fell one hit on one contested row (the
#: fold recorded on the plateau above); the union did not move.
_PARAPHRASE_UNION_OVER_DEEP_CONTROL = 2

#: Rows 8 and 13 are contested (see the arm comment). Pinned separately so revising
#: the key changes ONE constant instead of silently moving the headline. Row 8 is a
#: HIT under the pinned key and a MISS under the Rule-12 reading, so one of the eight
#: rests on a contested reading -- stated as a number, not a prose caveat.
_PARAPHRASE_CONTESTED_ROWS = ("8.", "13.")
_PARAPHRASE_UNION_HITS_UNCONTESTED = 9


def _arm_hits(fn, skip=(), *, top=2):
    return sum(
        1 for query, want in _PARAPHRASE_ARM
        if want not in skip
        and any(h.source.startswith(f"docs/STANDING_PRINCIPLES.md :: {want}")
                for h in fn(query, REPO_ROOT, top=top))
    )


def _arm_candidates(fn, top):
    """Mean candidates the CALLER receives per query -- the budget that must match.

    Deliberately NOT `top`. recall_union(top=k) returns up to 2k hits, so measuring
    the parameter instead of the delivery is precisely what made two drafts of the
    comparison below void. Anything comparing two rankers must match on this.
    """
    return sum(len(fn(q, REPO_ROOT, top=top))
               for q, _ in _PARAPHRASE_ARM) / len(_PARAPHRASE_ARM)


def test_the_control_is_not_under_budgeted():
    """MECHANICAL equal-budget guard -- the property itself, not a claim about it.

    Two successive drafts of the comparison below were void on budget, and the second
    was void *while asserting matched-ness in its own test name*. A docstring cannot
    hold that line; an assertion can. If recall_union's fan-out changes, or the
    control's `top` is edited down, this reds before the headline can quietly become
    unearned again. docs/FAILURE_MODES.md §5.15.
    """
    union = _arm_candidates(_recall.recall_union, _PARAPHRASE_UNION_TOP)
    naive = _arm_candidates(_recall.recall, _PARAPHRASE_UNION_TOP)
    control = _arm_candidates(_recall.recall, _PARAPHRASE_CONTROL_TOP)

    # Non-vacuity: the asymmetry this guard exists to cover must actually exist.
    # If the union ever stops fanning out, `control >= union` passes trivially and
    # would licence dropping the control back to top=2 -- so fail loudly instead.
    assert union > naive, (
        f"recall_union(top=2) now delivers {union:.2f} candidates/query, no more than "
        f"recall(top=2)'s {naive:.2f} -- the 2k fan-out is gone, and this guard has "
        "become vacuous. Re-derive the table; the control may no longer need top=4."
    )
    assert control >= union, (
        f"the control receives FEWER candidates per query ({control:.2f}) than the "
        f"union ({union:.2f}) -- every comparison below is void until the control's "
        f"top is raised. recall_union(top=k) returns up to 2k hits: `top` is a "
        f"per-ranker slot count, NOT the budget."
    )
    # ...and per-query, not merely on average. A mean can be matched while the
    # challenger runs 2x over on precisely the queries that decide the headline;
    # today it never exceeds the control on ANY query, so assert the property that
    # actually holds rather than the weaker one that happens to summarise it.
    over = [q for q, _ in _PARAPHRASE_ARM
            if len(_recall.recall_union(q, REPO_ROOT, top=_PARAPHRASE_UNION_TOP))
            > len(_recall.recall(q, REPO_ROOT, top=_PARAPHRASE_CONTROL_TOP))]
    assert not over, (
        f"{len(over)} quer(y/ies) hand the union MORE candidates than the control "
        f"despite a matched mean -- the a fortiori argument holds on average and "
        f"fails where it counts: {over[:3]}"
    )


def test_the_union_beats_a_six_slot_control():
    """The slot curve, pinned -- and it is what stops the headline being a tautology.

    recall() climbs one hit from top=2 to top=3 and then stops dead through top=6,
    so "the union just shows more candidates" cannot explain a +2 margin: the
    shipped ranker is given MORE candidates than the union and still loses. It is
    also the standing evidence that slots are spent as a lever.

    ⚠ Renamed. This was "..._more_slots_do_not_buy_paraphrase_reach" while the curve
    was flat at 4/16 throughout; document expansion moved it to 7 -> 8 -> 8 and made
    that name false. The assertion never changed -- only the claim its name made.

    ⚠ AND THE SATURATION SLOT MOVED AGAIN, 2026-09-03 -- third slot to FOURTH.
    The curve is now 6 -> 7 -> 8 -> 8: adding ONE docs/SHARP_EDGES.md entry cost
    a hit at top=3. A/B'd rather than inferred -- stashing that single file's
    diff restores [6, 8, 8, 8] exactly. This function's NAME is now one slot
    optimistic; it is kept because the pin, the sweep and every message below
    read on the plateau's EXISTENCE, not its index, and a rename would churn a
    cross-referenced symbol for a number that the pin already states. Read the
    name as "saturates early", and the pin as where.

    The headline argument is UNAFFECTED and that was checked, not assumed: the
    union-vs-control comparisons in this module all still pass, so the shipped
    ranker is still handed more candidates than the union and still loses. What
    the drift does show is a real property worth watching -- recall's slot-3
    reach DEGRADES as the corpus grows, so a future entry could cost slot 4 as
    well and flatten the margin. If that happens, re-derive the table rather
    than nudging the pin again.

    ⚠ AND IT HAPPENED THE OTHER WAY, 2026-09-04. The second blind alias round
    lifted the single ranker at slot 2 AND at slot 6 -- [7, 7, 8, 9] -- so
    within six slots it no longer saturates at all. RENAMED from
    `test_the_single_ranker_saturates_by_the_third_slot` (the paragraph above
    argued the old name was cross-referenced from record surfaces; checked, it
    is cited only from two scrapped packs and a generated report, none of which
    is in the declared record-surface set, so the name was kept on a reason
    that did not hold). What the test guards has not changed: the union, with
    about three and a half candidates, delivers more paraphrase hits (10) than
    recall() handed six (9). That is now the assertion -- direction unbanded,
    margin banded -- and the "flat tail" it replaces was pinning a shape a
    better ranker was always going to break.

    ⚠ AND PARITY, 2026-09-12. The pull ranker stopped indexing two memory/
    aggregates (PULL_EXCLUDED_MEMORY_NOTES), and the slots they had occupied on
    paraphrase queries went to the right documents: recall(top=6) rose 9 -> 10
    while the union stayed at 10 (A/B'd per note on _PARAPHRASE_PLATEAU; the
    four-slot control stayed at 9, so the union still beats the SAME-budget
    control, which is the comparison the module docstring makes). The "more
    hits than six slots" leg therefore became a tie from the good side: the
    single ranker improved, the union did not regress. The headline this test
    can honestly hold is reach-per-line -- the same ten hits at two lines per
    ranker, at most four, against six -- so the direction leg reads "never
    below" and the margin is recorded at zero. The name is kept one more time,
    for the reason the paragraph above gives; read "beats" as "matches at under
    two thirds of the budget", and if a corpus change ever puts recall(top=6)
    ABOVE the union, that is the six-slot control beating the front door and
    the direction leg reds -- re-derive, do not band.

    ⚠ AND BACK TO A MARGIN, 2026-09-22. Six held reflect keys folded into seven
    corpus files; one of them (a new section on memory/convergence-review-
    protocol.md) outranks §8 at the sixth slot for that row's paraphrase, so
    recall(top=6) reads 8 while the union still delivers 10 (A/B'd per file on
    _PARAPHRASE_PLATEAU; the four-slot control stayed at 8, where ordinary
    growth since 09-12 had already put it). Direction unchanged, margin
    re-recorded at 2.
    """
    # Non-vacuity FIRST: the sweep reads its own `top` values out of the pin, so an
    # emptied or narrowed pin measures nothing and compares equal to itself. Measured:
    # `()` and `((2, 4),)` both passed before this line existed. Same reasoning as
    # _OFF_TOPIC_ENGLISH's "an empty arm ratchets nothing" guard ~400 lines above.
    assert [top for top, _ in _PARAPHRASE_PLATEAU] == [2, 3, 4, 6], (
        f"the plateau pin was narrowed to tops "
        f"{[t for t, _ in _PARAPHRASE_PLATEAU]} -- it must sweep 2, 3, 4 and 6 or "
        "it cannot show a plateau at all"
    )
    assert _PARAPHRASE_CONTROL_TOP in [t for t, _ in _PARAPHRASE_PLATEAU], (
        "the control's budget is no longer one of the swept slots, so the sweep "
        "and the headline comparison are measuring different things"
    )
    curve = [_arm_hits(_recall.recall, top=top) for top, _ in _PARAPHRASE_PLATEAU]
    # Non-vacuity, second leg: an all-zero curve is flat, and a corpus that
    # stopped loading produces exactly that.
    # Split, because these are two unrelated failures and one message diagnosed
    # both as "the corpus collapsed". Measured: adding a 17th principle plus its arm
    # row leaves every band and both floors GREEN and makes the length leg the sole
    # red -- so the operator would have been sent to look for a corpus collapse that
    # had not happened, in a file whose own history is comments that asserted more
    # than the code established.
    assert curve[0] >= 1, (
        f"curve {curve} -- recall() answers nothing at the first swept slot, so "
        "every assertion below would pass measuring an empty corpus"
    )
    assert len(_PARAPHRASE_ARM) == 16, (
        f"the paraphrase arm is {len(_PARAPHRASE_ARM)} rows, not 16 -- the arm "
        "CHANGED SIZE. Re-derive the whole table; do not adjust a constant. `==` "
        "rather than a floor is deliberate: the pinned magnitudes here are "
        "denominated in 16 (6/16, 10/16), so a 17th row silently re-bases them."
    )
    # THE SATURATION CLAIM, split by what is measurably stable and what is not.
    #
    # ⚠ THIS WAS ONE ASSERTION AND IT WAS WRONG, for one day, in the commit that
    # introduced it. It read `curve[1] == curve[2] == curve[3]`, exact and
    # unbanded, justified in a comment claiming "a corpus shift moves all three
    # together and cancels". That claim was reasoned, not measured, and it is
    # FALSE: holding out either memory/CONVERGENCE_LEDGER.md or
    # memory/fix-the-class-not-the-instance.md takes the curve to [7, 8, 8, 9] --
    # the SIXTH slot moves alone, while the third and fourth do not move at all.
    # The sixth slot had been added in that same commit and called "the one strict
    # strengthening", which made it instead the most corpus-fragile assertion in
    # this file: an exact equality on the only slot that had never been perturbed,
    # with no constant to adjust when it reds. The full suite could not catch it,
    # because the tail IS flat on the live tree; only driving the perturbation did.
    #
    # So: slots 3 and 4 stay EXACT. That equality survived all 258 held-out
    # documents in the leave-one-out census with zero movement, which is the
    # evidence the deleted comment only asserted.
    # ⚠ RE-DERIVED 2026-09-03, and the equality this replaces was the ROBUST one.
    # It read `curve[1] == curve[2]` (slots 3 and 4) on the evidence recorded
    # above: that pair survived all 258 held-out documents in the leave-one-out
    # census with zero movement. ONE NEW DOCUMENT BROKE IT -- the
    # `Read()`-deny-rule entry added to docs/SHARP_EDGES.md, which displaces a
    # STANDING_PRINCIPLES hit at slot 3. A/B'd, not inferred: stash that single
    # file's diff and the curve returns to [6, 8, 8, 8] exactly.
    #
    # Note the asymmetry that let this through: the census perturbed by REMOVING
    # documents, and this was an ADDITION. A corpus that is robust to holding any
    # one document out is not thereby robust to gaining one, and nothing here had
    # measured the second direction.
    #
    # The obvious repair -- move the equality to `curve[2] == curve[3]` -- was
    # REJECTED: slots 4 and 6 put the exact equality on the SIXTH slot, which the
    # comment above establishes is the corpus-fragile one that "moves alone"
    # under hold-out. That would relocate a load-bearing assertion onto the least
    # stable measurement in the file, which is precisely the error the comment
    # was written to warn about.
    #
    # So pin the SHAPE of the climb instead: +1, +1, then flat. Every step is
    # exact, no single equality carries the claim, and any drift at any slot reds
    # with the slot named rather than one pair silently absorbing it.
    # ⚠ RE-DERIVED AGAIN, 2026-09-04, and this time the SHAPE changed, not the
    # index. The second blind alias round took the curve from [6, 7, 8, 8] to
    # [7, 7, 8, 9]: slot 2 gained one (expansion lifts the single ranker too) and
    # the sixth slot gained one, so there is no flat tail inside six slots any
    # more. The previous assertions -- steps [1, 1, 0] and `curve[-1] ==
    # curve[-2]` -- were both falsified by a change that IMPROVED retrieval, which
    # is the sign they were pinning a rhetorical shape rather than the property.
    # The property the headline needs is the one asserted last below: handed six
    # candidates, recall() still delivers fewer paraphrase hits than the union
    # does with about three and a half. The steps stay pinned as the measured
    # shape (exact, per slot, so drift names the slot), and the tail is bounded
    # relationally as before.
    # 2026-09-05: [0, 2, 0]. STANDING_PRINCIPLES §18's rewrite moved one paraphrase
    # hit from the sixth slot to the fourth (A/B'd against the aliases twin alone,
    # which leaves the curve unchanged) -- see _PARAPHRASE_PLATEAU's note.
    # 2026-09-12: [1, 1, 1]. Two memory/ aggregates left the pull corpus and gave
    # back a third slot and a sixth (A/B'd per note on _PARAPHRASE_PLATEAU).
    # 2026-09-22: [0, 1, 0]. Ordinary growth since 09-12 had taken slots 3, 4 and 6
    # down one each inside the band; one fold then took the sixth alone (A/B'd per
    # file on _PARAPHRASE_PLATEAU).
    # ⚠ AND THE LITERAL IS RETIRED, 2026-09-12, on the pin's own rule: the
    # _PARAPHRASE_PLATEAU note said that a third red for corpus drift means the
    # literals measure corpus size, not the engine, and want re-deriving as a
    # SHAPE. This is the fourth re-pin (08-20, 09-03, 09-04, 09-12), and the
    # failure-mode review drove the fragility: of the 25 most recently added
    # memory/ notes, removing any one of four moves the steps. The recall tier
    # now runs this test on every memory/ commit, so the literal would red on
    # ordinary documentation work several times a month. The shape is what the
    # headline needs -- more slots never cost reach, and six slots reach further
    # than two -- asserted per step so a drop still names its slot; the recorded
    # curve lives on _PARAPHRASE_PLATEAU as a dated record, not an assertion.
    steps = [b - a for a, b in zip(curve, curve[1:])]
    falls = [(a_top, b_top, a, b) for (a_top, _), (b_top, _), a, b
             in zip(_PARAPHRASE_PLATEAU, _PARAPHRASE_PLATEAU[1:], curve, curve[1:]) if b < a]
    assert not falls, (
        f"recall()'s paraphrase reach FELL with more slots: curve {curve} across tops "
        f"{[t for t, _ in _PARAPHRASE_PLATEAU]} -- a slot losing hits as the budget "
        f"grows is a ranking defect, not drift: {falls}"
    )
    assert curve[-1] > curve[0], (
        f"recall()'s paraphrase curve is flat from slot 2 to slot 6 ({curve}): more "
        "slots buy nothing, which the union's reach-per-line headline below assumes "
        "is false. Re-derive the headline."
    )
    del steps  # computed for the message history above; the shape is the claim now
    # THE HEADLINE'S OWN PROPERTY, asserted directly: the deepest swept control
    # budget still delivers fewer hits than the union at its shipped budget.
    # Then the margin, banded around the recorded value so ordinary drift in
    # HOW MUCH the union wins by is absorbed, while a jump names itself.
    deep_control = curve[-1]
    union_hits = _arm_hits(_recall.recall_union, top=_PARAPHRASE_UNION_TOP)
    # Direction first, unbanded. Until 2026-09-12 this read `>`: a tie meant the
    # six-slot control had caught the union and the headline was false (and the
    # band below, centred on 1, would have let that tie through -- caught in the
    # adversarial pass). The tie then arrived from the OTHER side: two aggregates
    # left the corpus, recall(top=6) rose to 10, the union stayed at 10, and the
    # single ranker's gain is not the union's loss. The headline was re-derived
    # to reach-per-line (the docstring), so the direction leg is "never below":
    # recall(top=6) delivering MORE than the union is still the six-slot control
    # beating the front door, and still a red to re-derive rather than band.
    assert union_hits >= deep_control, (
        f"recall(top=6) delivers {deep_control} paraphrase hits and the union at "
        f"top={_PARAPHRASE_UNION_TOP} delivers {union_hits}: the six-slot control has "
        "overtaken the union, so 'the same reach at under four lines' is no longer "
        "true. Re-derive the headline; do not band this away."
    )
    assert _in_band(union_hits - deep_control, _PARAPHRASE_UNION_OVER_DEEP_CONTROL), (
        f"union(top={_PARAPHRASE_UNION_TOP}) delivers {union_hits} paraphrase hits "
        f"against {deep_control} for recall(top=6): margin "
        f"{union_hits - deep_control}, recorded {_PARAPHRASE_UNION_OVER_DEEP_CONTROL} "
        "(band ±1). The direction is asserted above; this is the margin DRIFTING by "
        "more than one hit -- re-derive the table and record the cause, do not widen "
        "the band."
    )
    # Both of the above are ONE-SIDED by construction, and it is worth saying which
    # side: `recall()` returns `scored[:top]`, so the curve is monotonically
    # non-decreasing and `curve[1] == curve[2]` can only ever fail as
    # `curve[1] < curve[2]` -- the FOURTH slot buying reach, never the third.
    # (The message above said "third" for one commit. A third slot buying reach is
    # `curve[1] > curve[0]`, which is TRUE today, 6 -> 8, and expected.)
    #
    # ...and the tail is bounded RELATIONALLY rather than pinned, same one-sidedness:
    # only the upper side can fail. One hit is the measured wander (8 or 9 across the
    # census); a sixth slot buying MORE than that is a real un-plateauing and reds.
    # Relational, not a literal, because a corpus shift that lifts both slots
    # together should not need a re-derivation -- which is what the original
    # comment wanted to be true and asserted in the wrong place.
    assert curve[3] <= curve[2] + 1, (
        f"the sixth slot bought {curve[3] - curve[2]} hits over the fourth: {curve} "
        f"across tops {[t for t, _ in _PARAPHRASE_PLATEAU]}. Saturation is the "
        "claim that ruled out 'the union merely shows more candidates', so this "
        "is the headline's premise failing -- re-derive the table. Widening this "
        "to +2 would retire the claim rather than repair it."
    )
    # THE LEVELS, banded: these DO move with the corpus -- slot 2 fell 7 -> 6 on
    # 2026-08-20 when one memory/ file landed, with slots 3 and 4 unmoved.
    off = [(t, m, c) for (t, c), m in zip(_PARAPHRASE_PLATEAU, curve)
           if not _in_band(m, c)]
    assert not off, (
        f"the plateau LEVEL moved more than one hit at {[(t, m) for t, m, _ in off]} "
        f"against recorded {_PARAPHRASE_PLATEAU}. One adverse document is worth ±1; "
        "this is larger. Re-derive the table and record the cause -- do not widen "
        "the band."
    )


def test_the_second_normalisation_beats_more_slots_at_a_matched_budget():
    """The measured gain, against a control given MORE candidates than the union.

    ⚠ The name matters, and it has been wrong twice. It was once
    "..._than_either_ranker_alone" (false: the union ties the paraphrase-calibrated
    ranker at one candidate and loses at two), then
    "..._at_the_same_candidate_budget" (false: the budgets were 3.69 against 2.00
    when measured; 3.56 against 2.00 on 2026-08-19).
    What the union actually buys is paraphrase reach WITHOUT surrendering the naming
    floor, at no extra candidate cost -- which neither ranker alone does.
    """
    union_hits = _arm_hits(_recall.recall_union, top=_PARAPHRASE_UNION_TOP)
    control_hits = _arm_hits(_recall.recall, top=_PARAPHRASE_CONTROL_TOP)
    assert _in_band(union_hits, _PARAPHRASE_UNION_HITS), (
        f"paraphrase reach moved to {union_hits}/{len(_PARAPHRASE_ARM)} "
        f"(recorded {_PARAPHRASE_UNION_HITS}, band ±1). Re-derive; do not adjust "
        "to fit, and do not widen the band."
    )
    assert _in_band(control_hits, _PARAPHRASE_CONTROL_HITS), (
        f"the equal-budget control moved to {control_hits} (recorded "
        f"{_PARAPHRASE_CONTROL_HITS}, band ±1) -- re-derive the whole table, not "
        "one row"
    )
    # THE MARGIN, banded -- and this is what restores the early warning the block
    # comment above says the strict `==` existed to force. Corpus drift moves both
    # sides and cancels here, so the difference is the corpus-stable quantity: if
    # the difference is what the argument rests on, pin the difference.
    margin = union_hits - control_hits
    assert _in_band(margin, _PARAPHRASE_UNION_HITS - _PARAPHRASE_CONTROL_HITS), (
        f"the union's margin over the honest control moved to {margin} (recorded "
        f"{_PARAPHRASE_UNION_HITS - _PARAPHRASE_CONTROL_HITS}). It was +4 before "
        "document expansion and +2 after; the block comment schedules a re-ask of "
        "whether the second pass still earns its place, and THIS is the assertion "
        "that fires while the question is still live rather than on the day the "
        "margin reaches zero."
    )
    assert union_hits > control_hits, (
        f"the union ({union_hits}) no longer beats recall() given MORE candidates "
        f"than it ({control_hits} at top={_PARAPHRASE_CONTROL_TOP}) -- the second "
        "NORMALISATION, as opposed to the extra SLOT, has stopped earning its place "
        "and should be removed"
    )


def test_the_headline_does_not_rest_entirely_on_contested_rows():
    """Two of sixteen answer-key rows are contestable; pin the reading without them."""
    uncontested = _arm_hits(_recall.recall_union, skip=_PARAPHRASE_CONTESTED_ROWS,
                            top=_PARAPHRASE_UNION_TOP)
    assert _in_band(uncontested, _PARAPHRASE_UNION_HITS_UNCONTESTED), (
        f"uncontested reach moved to {uncontested}/"
        f"{len(_PARAPHRASE_ARM) - len(_PARAPHRASE_CONTESTED_ROWS)} "
        f"(recorded {_PARAPHRASE_UNION_HITS_UNCONTESTED}, band ±1)"
    )


# --------------------------------------------------------------------------
# Document expansion: docs/STANDING_PRINCIPLES.aliases.md
#
# The sidecar is a hand-keyed list whose keys must track a list maintained
# somewhere else -- which is STANDING_PRINCIPLES §14's own subject ("derive the
# list, don't test a hand-written copy of it"). So BOTH sides are derived from
# their live files here and compared; nothing about the principles is written
# down twice. A renamed, added or deleted principle reds this immediately rather
# than silently orphaning its aliases, which would degrade retrieval invisibly:
# an orphan block is not a crash, it is simply expansion that stops applying.
# --------------------------------------------------------------------------
_PRINCIPLE_HEADING_RE = re.compile(r"^## +(\d+)\.\s", re.M)


def _live_principle_numbers() -> set:
    return set(_PRINCIPLE_HEADING_RE.findall(
        (REPO_ROOT / "docs" / "STANDING_PRINCIPLES.md").read_text(encoding="utf-8")))


def test_a_heading_with_no_title_text_does_not_crash_the_engine(tmp_path):
    """Regression. `_SECTION_RE` is `^## +(.*)$`, so a line of "## " plus trailing
    whitespace matches with an EMPTY group -- and trailing whitespace is invisible in
    an editor. The section-number split was unguarded at two sites, so one stray
    space in docs/STANDING_PRINCIPLES.md raised IndexError straight out of the CLI,
    which wraps nothing. Verified red before the guard: IndexError from _iter_corpus.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "STANDING_PRINCIPLES.md").write_text(
        "# P\n\n## 1. Real principle\n\nbody\n\n## \n\nstray\n", encoding="utf-8")
    got = list(_recall._iter_corpus(tmp_path))          # must not raise
    assert any(d.source.endswith("1. Real principle") for d in got), (
        "the well-formed principle stopped being indexed -- the guard swallowed more "
        "than the malformed heading"
    )


def test_a_code_fence_in_the_sidecar_is_not_parsed_as_structure(tmp_path):
    """A documented example inside ``` is prose ABOUT the format, not the format.

    Measured before the fence guard: a fence containing "## 2." and "- fake alias"
    produced a real block 2 AND stole the next genuine bullet from block 1 -- silent
    MISATTRIBUTION, which the loader's docstring did not admit to (it promised only
    that a malformed sidecar yields fewer aliases, never an exception).
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "STANDING_PRINCIPLES.aliases.md").write_text(
        "# Aliases\n\n## 1. Real\n\n```\n## 2. inside a fence\n- fake alias\n```\n"
        "- genuine alias\n", encoding="utf-8")
    got = _recall._load_principle_aliases(tmp_path)
    assert "2." not in got, f"a fenced heading became a real block: {got}"
    assert got.get("1.") == "genuine alias", (
        f"the bullet after the fence was misattributed or dropped: {got}"
    )


@pytest.mark.parametrize("opener, inner, closer", [
    ("~~~", "```", "~~~"),        # a tilde fence; a backtick line inside does not close it
    ("````", "```", "````"),      # a four-backtick fence; a shorter run inside does not close it
    ("```", "", "`````"),         # a longer run of the same char closes
])
def test_the_alias_loader_reads_every_fence_shape_the_splitter_does(tmp_path, opener, inner, closer):
    """DEF-565's sibling: the loader used to flip on any line starting with three
    backticks, so a tilde fence was no fence at all and a ``` line INSIDE a longer
    fence closed it early. It now reads through the stack's one fence grammar
    (_hook_utils.next_fence_state), the same one iter_doc_sections uses on the
    principles doc its output is folded into."""
    docs = tmp_path / "docs"
    docs.mkdir()
    inner_line = f"{inner}\n" if inner else ""
    (docs / "STANDING_PRINCIPLES.aliases.md").write_text(
        f"# Aliases\n\n## 1. Real\n\n{opener}\n{inner_line}## 2. inside a fence\n- fake alias\n"
        f"{closer}\n- genuine alias\n", encoding="utf-8")
    got = _recall._load_principle_aliases(tmp_path)
    assert "2." not in got, f"a fenced heading became a real block: {got}"
    assert got.get("1.") == "genuine alias", f"misattributed or dropped: {got}"


def test_a_fenced_heading_in_sharp_edges_stays_inside_its_section(tmp_path):
    """DEF-565. `_recall` read docs/SHARP_EDGES.md through its own copy of the
    section splitter, and neither copy knew about fenced code: a documented
    example of a heading inside a fence became a corpus document of its own,
    with the example's title as its snippet. The corpus now comes through
    _hook_utils.iter_doc_sections -- the banner's splitter -- which is
    fence-aware, so the two readers of one catalog agree on where a section
    starts. (On the live tree the collapse changed nothing: 298 docs, identical
    token bags, measured; no tracked doc carries a fenced ``## `` line.)"""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "SHARP_EDGES.md").write_text(
        "# Sharp Edges\n\n## Real edge\n\nprose about the edge\n\n```md\n"
        "## Example heading\nxylophone\n```\n\n## Second edge\n\nmore prose\n",
        encoding="utf-8")
    docs_in = [d for d in _recall._load_corpus(tmp_path) if d.source.startswith("docs/SHARP_EDGES.md")]
    assert [d.snippet for d in docs_in] == ["Real edge", "Second edge"], [d.source for d in docs_in]
    assert "xylophone" in docs_in[0].tokens, "the fenced example's words belong to the section it sits in"


def test_every_principle_has_an_alias_block_and_vice_versa():
    """Derived both directions -- the sidecar cannot drift from the doc it expands."""
    principles = _live_principle_numbers()
    aliases = {k.rstrip(".") for k in _recall._load_principle_aliases(REPO_ROOT)}

    # Non-vacuity: two empty sets compare equal, and a moved/renamed sidecar or a
    # regex that stopped matching would produce exactly that. Same reasoning as the
    # _OFF_TOPIC_ENGLISH and _PARAPHRASE_PLATEAU guards elsewhere in this file.
    assert len(principles) >= 10, (
        f"only {len(principles)} principle headings parsed from the live doc -- the "
        "heading shape changed and this guard is measuring nothing"
    )
    assert aliases, (
        "no alias blocks loaded. Either docs/STANDING_PRINCIPLES.aliases.md is gone "
        "or _load_principle_aliases stopped parsing it -- in which case document "
        "expansion is silently OFF and the paraphrase pins below are measuring the "
        "un-expanded corpus"
    )
    assert aliases == principles, (
        f"alias sidecar out of step with the principles doc.\n"
        f"  principles with no alias block: {sorted(principles - aliases, key=int)}\n"
        f"  alias blocks with no principle: {sorted(aliases - principles, key=int)}\n"
        "Edit docs/STANDING_PRINCIPLES.aliases.md; do not relax this test."
    )


def test_alias_titles_match_the_live_doc_byte_for_byte():
    """A block keyed to the right NUMBER but the wrong TITLE is the silent case.

    The loader keys on the number alone, so a stale title never breaks retrieval --
    it just leaves a reader of the sidecar believing a principle says something it
    no longer says. Cheap to pin, and it is the only part of the sidecar a human
    reads.
    """
    def titles(rel):
        return {m.group(1): m.group(2).strip() for m in re.finditer(
            r"^## +(\d+)\.\s+(.*)$",
            (REPO_ROOT / rel).read_text(encoding="utf-8"), re.M)}
    live, side = titles("docs/STANDING_PRINCIPLES.md"), titles("docs/STANDING_PRINCIPLES.aliases.md")
    drift = {k: (live.get(k), side.get(k)) for k in live if live.get(k) != side.get(k)}
    assert not drift, f"alias block titles drifted from the live doc: {drift}"


def test_aliases_do_not_leak_into_what_a_reader_is_shown():
    """Expansion must move RANKING without changing the rendered answer.

    The whole design rests on aliases being tokenized but never surfaced -- if a
    hit's snippet were built from the expanded text, /recall would quote search
    bait back at the reader as though it were the principle. Sibling of the
    correction recorded in memory/fix-the-surface-the-reader-consumes.md.

    ⚠ THE FIRST DRAFT OF THIS GUARD COULD NOT FAIL, which is worth leaving on the
    record given what it is guarding. It compared ``doc.snippet`` against
    ``doc.source.split("::")[1]`` -- but _Doc is built as ``_Doc(f"... :: {title}",
    title, ...)``, so both sides came from one variable and the assertion was
    ``title == title``. It also carried an inner loop whose body was a bare
    ``continue``. The fix is to compare against an INDEPENDENT source: the live
    headings, re-read from disk here.
    """
    live = {m.group(1): m.group(2).strip() for m in re.finditer(
        r"^## +(\d+)\.\s+(.*)$",
        (REPO_ROOT / "docs" / "STANDING_PRINCIPLES.md").read_text(encoding="utf-8"), re.M)}
    aliases = _recall._load_principle_aliases(REPO_ROOT)
    assert live and aliases, "no principles or no aliases parsed -- guard is vacuous"

    checked = 0
    for doc in _recall._load_corpus(REPO_ROOT):
        if not doc.source.startswith("docs/STANDING_PRINCIPLES.md :: "):
            continue
        num = doc.source.split("::")[1].strip().split()[0]
        heading = f"{num} {live[num.rstrip('.')]}"
        # render() prints BOTH fields, so checking snippet alone leaves half the
        # rendered surface uncovered. Verified by mutation: folding aliases into
        # `source` instead of `snippet` left all five new guards green.
        assert doc.source == f"docs/STANDING_PRINCIPLES.md :: {heading}", (
            f"{doc.source!r} is no longer '<file> :: <heading>' -- the other half of "
            "what Hit.render() shows a reader may be carrying expanded text"
        )
        assert doc.snippet == heading, (
            f"{doc.source} renders {doc.snippet!r}, but the live doc's heading is "
            f"{heading!r} -- the snippet is no longer the heading, so expanded text "
            "may be reaching the surface a reader is shown"
        )
        # ...and state the leak directly, not just via the heading equality: no word
        # contributed ONLY by the sidecar may appear in what gets rendered.
        bait = set(_recall._tokenize(aliases.get(num, ""))) - set(_recall._tokenize(heading))
        surfaced = bait & set(_recall._tokenize(doc.snippet))
        assert not surfaced, (
            f"{doc.source} surfaces alias-only word(s) {sorted(surfaced)} in its "
            "rendered snippet -- /recall would quote search bait back as principle text"
        )
        checked += 1
    assert checked == len(live), (
        f"only {checked} of {len(live)} principles reached the assertions -- the "
        "corpus source prefix changed and this guard stopped covering them"
    )


# --------------------------------------------------------------------------
# The BLIND held-out arm. Everything else in this file that measures paraphrase
# was written by someone who could see the engine; this set was not, and it is
# the only arm here whose author had no access to the aliases being scored.
# Parsed from the fixture rather than inlined, so the "spend a row, delete the
# row" rule in its header operates on one artifact instead of two copies.
# --------------------------------------------------------------------------
_HELDOUT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "paraphrase_heldout_arm.md"
_ALIASES_PATH = REPO_ROOT / "docs" / "STANDING_PRINCIPLES.aliases.md"

#: Uncontested held-out rows answered at recall_union(top=2).
#:
#: Provenance, and the third category the old comment did not offer:
#:   9/24  before docs/STANDING_PRINCIPLES.aliases.md landed
#:  12/24  after document expansion -- THE number aliases.md records at adoption
#:  13/24  2026-08-20, and the +1 is NOT expansion. It arrived with the
#:         `## A mutation proves nothing until its subject is committed` section
#:         of docs/SHARP_EDGES.md, in a commit that changed no code. Isolated by
#:         holding that one section out of the corpus in-process: exactly one row
#:         flips -- principle 15., query "fourth try, new breakage". Principle 15
#:         is the ONLY scored-only principle in the fixture (the other 15 share a
#:         principle with a contested row), which is why the unscored arm below
#:         did not move and the tuning detector stayed silent.
#: So a move here has THREE causes, not two: a genuine improvement, tuning against
#: the arm, or CORPUS DRIFT -- a document landing that reorders a competitor. Say
#: which in the commit. The test's NAME still says "document expansion"; expansion
#: earned 12, not 13. docs/FAILURE_MODES.md §5.15.
#:
#: ⚠ HONEST SCOPE, because the old comment claimed more than this pin delivers.
#: It does NOT guard the ranker. Measured 2026-08-20: PARAPHRASE_NORM_EXPONENT
#: swept 0.6 / 0.75 / 0.85 / 1.5 / 2.0 leaves this count at 13 in every case, and
#: at 0.85 the ENTIRE paraphrase battery is byte-identical (union 10, control 8,
#: uncontested 9, curve [6,8,8,8], contested 11). What this pin actually detects
#: is aliases authored against the fixture: aliasing three currently-missing
#: scored rows moves it 13 -> 16.
#: ⚠ Those are 2026-08-20 figures; the live sweep after the second alias round is
#: the table in test_the_paraphrase_battery_can_see_a_ranker_change (scored 16,
#: contested 12 -> 11 after a row deletion, union 10-11, curve [7,7,8,9]).
#:
#: 2026-09-04, 13 -> 16: cause (1), a genuine gain. The second BLIND alias round
#: (docs/STANDING_PRINCIPLES.aliases.md, "Second blind round") -- its author opened
#: two files and neither was this fixture -- gained three uncontested rows and lost
#: none, while the unscored contested arm below stayed at its recorded level with
#: three gained and three lost. Held-out was read once, before the aliases touched
#: the tree, with the own-name guard repaired by a pre-registered per-block cap.
#: No row is spent.
#: 2026-09-10, 16 -> 17: cause (3), corpus drift. Two memory notes landed in
#: 150a259 and the IDF shift lifted STANDING_PRINCIPLES §8 into the top four for
#: "did i get all the instances"; no alias or fixture was touched, so the row is
#: not spent (b09fb97).
#: 2026-09-12: read 16 on `main` from the 2026-09-11 catalog fold until this
#: lane -- cause (3), corpus drift: the fold's appends let memory/CONVERGENCE_LEDGER.md
#: out-rank STANDING_PRINCIPLES §8 for "did i get all the instances" (driven on a
#: scratch worktree at the pre-fold commit: 17 there, 16 after). The pull ranker
#: no longer indexes the ledger (PULL_EXCLUDED_MEMORY_NOTES), and the row hits
#: again; the constant was not moved, the competitor was removed.
#: 2026-09-13: 17 -> 16, cause (3), corpus drift -- and the SAME row again, "did
#: i get all the instances" (STANDING_PRINCIPLES §8). The group-8 memory commit
#: `0e6701c` folded lessons into memory/an-enumeration-switch-reaches-every-consumer.md
#: and memory/recall-keys-on-the-hazard-not-the-task.md, and their new vocabulary
#: out-ranks §8 for that query: bisected by byte-swapping each corpus file the
#: commit touched back to d4c703f in turn (16 with both as landed, 17 with EITHER
#: restored, the other two files inert). Red on `main` since that commit; found
#: by the group-9 lane's tier. Both notes are live protocol, not records, so
#: this time the constant moves and the competitor stays. The row is knife-edge
#: for its principle -- its words are the fix-the-class vocabulary every class
#: note carries -- so the next memory fold on that theme will likely move it again.
#: 2026-09-14, 16 -> 17: cause (3), corpus drift, and the SAME row a fourth time,
#: "did i get all the instances" (STANDING_PRINCIPLES §8). The comment-correction
#: lane rewrote two docs/SHARP_EDGES.md entries (the engine <-> hook pair list and
#: two maintenance-mode roster sentences); bisected by restoring each of the five
#: edited corpus files to HEAD in turn -- only SHARP_EDGES.md returns 16 -- and the
#: hit-set diff names the row. No alias or fixture was touched; the row is not
#: spent; the constant moves.
_HELDOUT_UNCONTESTED_HITS = 17

#: Population pins for the fixture, so a leaked or deleted row is visible as a
#: separate constant rather than as movement in the hit count above.
#: 47, not 48, since 2026-09-04: one CONTESTED §12 row was deleted under the
#: fixture's own rule -- the alias sidecar's header quoted its query verbatim as
#: the motivating example, and that header is the brief every blind alias author
#: is handed, so the channel was open whatever any author did with it. The
#: deletion is recorded in the fixture at the row's position.
_HELDOUT_ROWS = 47
_HELDOUT_UNCONTESTED_TOTAL = 24

#: THE TUNING DETECTOR, and it is free -- these 24 rows are marked CONTESTED by the
#: fixture's author and are therefore NOT scored by the ratchet. That makes them a
#: held-back arm nobody has an incentive to tune against.
#:
#: The fixture's header says "if you tune against a row, delete the row". That is
#: prose with nothing behind it, and the failure message on the scored pin literally
#: invites raising the constant. What distinguishes a real improvement from a tuned
#: one is DIVERGENCE: tuning lifts the scored 24 while the unscored 24 sits still.
#: At adoption both moved, and the unscored arm moved MORE -- 6->11 against 9->12 --
#: which is the strongest evidence available that this round was not tuned.
#:
#: ⚠ MEASURED 2026-08-20, and it inverts the intuition: this UNSCORED arm is the
#: ranker-sensitive one. Sweeping PARAPHRASE_NORM_EXPONENT 0.6 / 0.75 / 0.85 / 1.5
#: / 2.0 leaves the SCORED arm at 13 in every case while this one reads
#: 14 / 11 / 11 / 12 / 10. Whatever ranker coverage this file has lives HERE.
#:
#: ⚠ AND THE DIVERGENCE IS DELIVERED BY THE PAIR, NOT BY A GATE. A
#: `scored - unscored <= N` ceiling was designed and REJECTED on measurement:
#: aliasing the three currently-missing scored rows takes the pair to 16/11, a
#: spread of exactly 5, so a gate of 5 passes the attack at its own boundary --
#: while the natural spread has already reached 3 (pre-alias) and 3 (exponent
#: 2.0), so a gate tight enough to catch the attack has a margin of one against
#: ordinary noise. Two banded pins that red independently say the same thing and
#: calibrate nothing new.
_HELDOUT_CONTESTED_HITS = 11

#: WHICH contested rows hit (0-based positions in the contested list, fixture
#: order) -- the mechanical answer to "did the unscored arm move or merely hold
#: its count". The second blind round (2026-09-04) left the count at its level
#: while three rows flipped in and three out; a count-only pin read that as
#: stasis, which is the tuning signature ("scored rose, unscored did not"), and
#: the reassurance that it was churn lived in prose. Banded by symmetric
#: difference, not equality: one adverse document is worth one row, two is
#: still noise; three or more is a re-derivation with a cause. Re-base when a
#: fixture row is added or deleted (positions shift).
_HELDOUT_CONTESTED_HIT_ROWS = frozenset({1, 2, 4, 7, 9, 10, 11, 14, 15, 17, 20})
_HELDOUT_CONTESTED_ROW_SLACK = 2


def _parse_heldout():
    """[(query, principle, contested)] -- derived from the fixture, never inlined."""
    rows, current = [], None
    for line in _HELDOUT_FIXTURE.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^## +(\d+)\.\s", line)
        if heading:
            current = f"{heading.group(1)}."
        elif line.startswith("#"):
            # Reset on ANY other heading. Without this the fixture's trailing
            # "## Provenance" narrative never closed block 16, so one bullet added
            # there -- exactly where a maintainer records a new review lane --
            # became a 49th SCORED row keyed to principle 16. The intactness floors
            # below could not see it, and the operator would have seen the ratchet
            # red while blaming the engine for a prose edit.
            current = None
        elif current and line.startswith("- "):
            rows.append([line[2:].strip(), current, False])
        elif rows and line.strip().startswith("CONTESTED:"):
            rows[-1][2] = True
    return [tuple(r) for r in rows]


def _heldout_hits(rows):
    """Rows answered at recall_union(top=_PARAPHRASE_UNION_TOP).

    One definition, two arms -- the scored/unscored comparison is only a
    comparison if both sides are scored by the same code, on the same corpus, in
    the same run. This was duplicated inline in both tests before 2026-08-20.
    """
    return sum(
        1 for q, w in rows
        if any(h.source.startswith(f"docs/STANDING_PRINCIPLES.md :: {w}")
               for h in _recall.recall_union(q, REPO_ROOT, top=_PARAPHRASE_UNION_TOP))
    )


def test_the_blind_heldout_arm_is_intact():
    """Non-vacuity for the ratchet below -- a fixture that stopped parsing scores 0
    against a pin of 0 and would look like a pass."""
    rows = _parse_heldout()
    # `==`, not a floor. Floors cannot see a row being ADDED, and the realistic way
    # this fixture changes is a prose edit leaking a bullet into the scored set.
    assert len(rows) == _HELDOUT_ROWS, (
        f"held-out fixture parsed to {len(rows)} rows, pinned {_HELDOUT_ROWS}. If you "
        "deliberately spent and deleted a tuned-against row, lower this constant and "
        "say so; if you did not, a prose bullet has leaked into the benchmark."
    )
    uncontested = [r for r in rows if not r[2]]
    assert len(uncontested) == _HELDOUT_UNCONTESTED_TOTAL, (
        f"{len(uncontested)} uncontested rows, pinned {_HELDOUT_UNCONTESTED_TOTAL} -- "
        "the scored population changed, so the hit pin below is not comparable"
    )
    assert len({r[1] for r in rows}) == 16, "the arm must cover all 16 principles"


#: Token-Jaccard at or above which an alias line is a NEAR-COPY of an arm query.
#: Measured 2026-09-04 over 344 alias lines x 63 queries: the maximum is 0.60,
#: a four-word §9 pair ("this was too easy" / "this feels too easy") written
#: blind on both sides -- the obvious symptom of the principle, reached twice
#: independently. A query lifted with one word DELETED sits at 0.8 or above
#: (four of five words), so 0.75 separates convergence from that copy with a
#: word of headroom on each side. A one-word SUBSTITUTION scores (n-1)/(n+1)
#: and clears 0.75 only from eight words up (arm queries run 4 to 23, median
#: 11), so a short query copied with one word swapped is not caught by the
#: ratio -- which is why verbatim containment in either direction is refused
#: outright, whatever the ratio, and why this gate claims to catch copying,
#: not paraphrase.
_ALIAS_NEAR_COPY_JACCARD = 0.75


def test_no_alias_line_reproduces_an_arm_query():
    """The blind protocol's one mechanical guard: no alias may contain, be
    contained by, or near-duplicate any held-out or scored paraphrase query.

    The protocol otherwise rests on attestation -- the author says it opened two
    files. That was true both rounds, and one of those two files (the sidecar's
    own header) turned out to QUOTE a held-out query as its motivating example,
    so the channel was open regardless of what the author did with it. The row
    was deleted under the fixture's rule; this is what stops the next quote.
    Scans the FILE by bullet, not the loader's joined bags, so the unit is one
    alias line.
    """
    tok = lambda text: set(re.findall(r"[a-z0-9']+", text.lower()))  # noqa: E731
    # The loader's own fence rule (_hook_utils.next_fence_state, which
    # _recall._load_principle_aliases uses): a bullet inside a fenced block is
    # documentation of the format, not an alias -- two readers of one file must
    # agree on what a line is, so this reads through the same grammar rather
    # than a restatement of it.
    aliases, fence = [], None
    for ln in _ALIASES_PATH.read_text(encoding="utf-8").splitlines():
        fenced = fence is not None
        fence = _hook_utils.next_fence_state(ln, fence)
        if not fenced and fence is None and ln.startswith("- "):
            aliases.append(ln[2:].strip())
    assert len(aliases) > 100, "the sidecar stopped parsing -- this gate would pass vacuously"
    arm = [q for q, _, _ in _parse_heldout()] + [q for q, _ in _PARAPHRASE_ARM]
    contained = [(a, q) for a in aliases for q in arm
                 if q.lower() in a.lower() or a.lower() in q.lower()]
    near = [(round(j, 2), a, q) for a in aliases for q in arm
            if (j := len(tok(a) & tok(q)) / len(tok(a) | tok(q))) >= _ALIAS_NEAR_COPY_JACCARD]
    assert not contained and not near, (
        "an alias line reproduces an evaluation query. Under the fixture's rule that "
        "query is spent: DELETE the fixture row (or the _PARAPHRASE_ARM row) and lower "
        f"its population pin in the same commit; do not edit the alias. contained="
        f"{contained} near={near}"
    )


def test_the_unscored_contested_arm_moves_with_the_scored_one():
    """Tuning detector. Nobody optimises against these rows -- they are not scored.

    So if the scored arm climbs while this one stays flat, the gain is memorisation
    rather than retrieval, and it shows up as a two-constant diff instead of a
    one-line bump that a commit message can wave through.
    """
    contested = [(q, w) for q, w, c in _parse_heldout() if c]
    hits = _heldout_hits(contested)
    assert _in_band(hits, _HELDOUT_CONTESTED_HITS), (
        f"unscored contested reach moved to {hits}/{len(contested)} (recorded "
        f"{_HELDOUT_CONTESTED_HITS}, band ±1). ⚠ If the SCORED pin rose and this one "
        "did not, the scored gain is very likely tuning against the fixture, not "
        "retrieval -- check which rows flipped before raising anything."
    )
    # The count alone cannot tell churn from stasis (the docstring's whole
    # argument rests on that distinction and, until 2026-09-04, nothing here
    # read it). The SET of hitting rows can: a round that lifts the scored arm
    # while this set is byte-identical is the tuning signature; a round that
    # flips rows in and out has moved the unscored arm even at a flat count.
    hit_rows = frozenset(
        i for i, (q, w) in enumerate(contested)
        if any(h.source.startswith(f"docs/STANDING_PRINCIPLES.md :: {w}")
               for h in _recall.recall_union(q, REPO_ROOT, top=_PARAPHRASE_UNION_TOP))
    )
    churn = hit_rows ^ _HELDOUT_CONTESTED_HIT_ROWS
    assert len(churn) <= _HELDOUT_CONTESTED_ROW_SLACK, (
        f"{len(churn)} contested rows changed verdict (positions {sorted(churn)}) against "
        f"the recorded hit set; slack is {_HELDOUT_CONTESTED_ROW_SLACK}. Re-derive the set "
        "and record the cause: an alias round that moved the unscored arm THIS much is "
        "either a real shift in the ranker's reach or a fixture edit -- say which."
    )


def test_the_paraphrase_battery_can_see_a_ranker_change(monkeypatch):
    """MUST-TRIP twin for every banded count above -- the one property they cannot
    assert about themselves.

    ⚠ WHY THIS EXISTS, and it is a correction in BOTH directions. This file's
    comments overclaimed ranker coverage for months. Then, on 2026-08-20, a review
    measured the SCORED blind arm across a five-point exponent sweep, found it
    frozen at 13, and concluded the whole battery was ranker-blind and unfixable.
    That was the opposite error. Re-measured across the same sweep, in process:

        exponent   scored  contested  union  control
        0.6          13       14        9      8
        0.75         13       11       10      8     <- shipped
        0.85         13       11       10      8
        1.0          13       12        9      8
        1.5          13       12        8      8
        2.0          13       11        8      8

    So two arms are genuinely blind (the scored held-out arm and the equal-budget
    control) and two are not. The honest claim is therefore narrow, and this test
    pins exactly it: the battery CANNOT see a small retune -- 0.75 -> 0.85 is
    invisible on every arm, and was equally invisible to the strict `==` the bands
    replaced -- and it CAN see a large one.

    Without this, "the bands are green" reads as evidence the ranker is unchanged.
    It is not, and no comment can hold that line: the comment above the pins made
    a ranker claim and was wrong for months. Same reasoning as
    test_the_displacement_sweep_can_actually_fire elsewhere in this file -- a gate
    that has never been shown to fire is not yet known to be a gate.

    Asserted as the PROPERTY (the measurement leaves its band), never as a second
    set of literals. Literals here would be one more table to re-derive on every
    corpus edit, which is the failure this whole change set exists to end.
    """
    contested = [(q, w) for q, w, c in _parse_heldout() if c]

    # Non-vacuity, and it runs FIRST: at the SHIPPED exponent both arms must sit
    # INSIDE their bands. Without this the test passes on a harness that reports
    # nonsense for every exponent, which is precisely how a must-trip guard goes
    # bad -- it only ever checks that something moved.
    assert _in_band(_heldout_hits(contested), _HELDOUT_CONTESTED_HITS), (
        "the contested arm is out of band at the SHIPPED exponent -- fix that "
        "before reading anything below; this guard is measuring a broken baseline"
    )
    assert _in_band(_arm_hits(_recall.recall_union, top=_PARAPHRASE_UNION_TOP),
                    _PARAPHRASE_UNION_HITS), (
        "the union arm is out of band at the SHIPPED exponent -- same"
    )

    # A LARGE retune must leave the band on at least the two arms measured to be
    # sensitive.
    #
    # ⚠ RE-MEASURED 2026-09-04 after the second blind alias round, and the
    # DOWNWARD direction went blind. The first leg used to halve the exponent
    # (0.6) and watch the contested arm RISE 11 -> 14; with the richer bags it
    # reads 12 at 0.6, 13 at 0.5 and 11 at 0.3 -- inside the band at every
    # value tried -- and the union arm sits at 10/10/9 across the same sweep,
    # also inside. The full sweep, in process, at the shipped corpus:
    #
    #     exponent   scored  contested  union  control
    #     0.3          17       11        9      8
    #     0.5          16       13       10      8
    #     0.6          16       12       10      8
    #     0.75         16       12       10      8     <- shipped
    #     0.85         16       12       11      8
    #     1.0          16       12       10      8
    #     1.5          16       10        9      8
    #     2.0          15        9        8      8
    #     4.0          13        7        7      8
    #
    # So the honest claim narrowed again: the battery sees a large UPWARD retune
    # on two arms (contested 12 -> 7 and union 10 -> 7 at 4.0, three and two
    # clear of their bands) and is blind to a downward one. Both legs below now
    # use 4.0; the asymmetry is recorded here rather than papered over with a
    # value that happens to cross by one. Document expansion is what muted the
    # low end: more shared vocabulary per principle means less for a smaller
    # length penalty to reorder.
    monkeypatch.setattr(_recall, "PARAPHRASE_NORM_EXPONENT", 4.0)
    low = _heldout_hits(contested)
    assert not _in_band(low, _HELDOUT_CONTESTED_HITS), (
        f"a fourth-power length normalisation left the contested arm at "
        f"{low}, inside its band around {_HELDOUT_CONTESTED_HITS}. Every count in "
        "this file is now blind to the ranker, so a green run says nothing about "
        "retrieval. Do NOT widen a band to fix this and do NOT delete this test -- "
        "find an arm that still moves, or the battery has stopped being evidence."
    )

    # 4.0, not 2.0. At 2.0 the union arm reads 8 against a band floor of 9 -- it
    # leaves the band by exactly ONE, so a single corpus deletion could put this leg
    # back inside and quietly retire it. At 4.0 it reads 7, two clear. Choosing the
    # mutation with headroom is the same discipline as not pinning a knife-edge
    # answer: a guard whose margin is one is a future flake, and a flaky must-trip
    # guard gets deleted rather than investigated.
    monkeypatch.setattr(_recall, "PARAPHRASE_NORM_EXPONENT", 4.0)
    high = _arm_hits(_recall.recall_union, top=_PARAPHRASE_UNION_TOP)
    assert not _in_band(high, _PARAPHRASE_UNION_HITS), (
        f"a fourth-power length normalisation left the union arm at {high}, inside "
        f"its band around {_PARAPHRASE_UNION_HITS} -- see above."
    )


def test_document_expansion_holds_its_blind_heldout_gain():
    """The one paraphrase number on this repo whose author could not see the answer."""
    uncontested = [(q, w) for q, w, c in _parse_heldout() if not c]
    hits = _heldout_hits(uncontested)
    # ⚠ `==`, NOT `_in_band` -- the single exception in this file, and the reason is
    # measured rather than stylistic. Every other magnitude here is banded because
    # corpus drift moves it and the drift carries no information. This one is the
    # BLIND arm: its value is that nobody could see the answers, so the event it
    # exists to catch is someone aliasing against it -- and a single aliased row
    # moves it by exactly +1 (11 of the 11 currently-missing rows do), which a +-1
    # band cannot see. Banding it therefore retires the arm's entire purpose.
    # The trade measures well in both directions: its own corpus-drift rate is the
    # LOWEST of the seven pins (the cause-(3) moves are dated in the provenance
    # block above; the corpus size the rate divides by is whatever _load_corpus
    # reads at the time, not a figure kept here), and an exact pin also catches a
    # second event the band
    # misses -- a global min-score cutoff around 0.15 takes this count 13 -> 12.
    # A re-pin is cheap now in a way it was not before: the message below names the
    # three causes, so classifying a move is a one-line honest edit rather than a
    # choice between two explanations that do not fit.
    assert hits == _HELDOUT_UNCONTESTED_HITS, (
        f"blind held-out reach moved to {hits}/{len(uncontested)} (pinned "
        f"{_HELDOUT_UNCONTESTED_HITS}). HIGHER is not automatically good "
        f"news -- it "
        f"has THREE causes and only one is an improvement: (1) a genuine gain, "
        f"(2) aliases authored against this arm, which is not a gain and spends the "
        f"row (the fixture header's rule is to DELETE it and lower _HELDOUT_ROWS in "
        f"the same commit), or (3) corpus drift -- a document landed and reordered a "
        f"competitor, which happened on 2026-08-20 and is worth zero. Say which in "
        f"the commit before touching the constant. LOWER means expansion or ranking "
        f"regressed."
    )


def test_union_cannot_regress_below_the_shipped_ranker(monkeypatch):
    """recall()'s winner must be element 0 of the union, for every corpus title.

    ⚠ HONEST SCOPE, because the first draft's docstring overclaimed here. This is an
    IDENTITY, not a discovered property: `norm` affects only the `base` score, never
    `matched`/`trigger_hit`/`topical`, so the scored SET is bit-identical in both
    passes and no second ranker can displace element 0 -- verified against a
    12-mutation matrix including a hash-garbage divisor, all 0 displacements. So this
    pins recall_union's CONSTRUCTION (pass 1's winner at element 0, then the passes
    alternate; first-occurrence dedup), not the
    ranker. test_the_displacement_sweep_can_actually_fire is its must-trip twin.
    """
    docs = _recall._load_corpus(REPO_ROOT)
    assert len(docs) >= 100, f"corpus collapsed to {len(docs)} -- assertion would be vacuous"
    monkeypatch.setattr(_recall, "_load_corpus", lambda _root, _d=docs: _d)
    displaced = _sweep_for_displacement(docs)
    assert not displaced, (
        f"{len(displaced)} document(s) had their shipped answer displaced from "
        f"element 0 of the union: {displaced[:5]}"
    )


def test_the_displacement_sweep_can_actually_fire(monkeypatch):
    """Must-trip twin for the sweep above -- without it that guard is unfalsifiable.

    Reverse the union's concatenation so pass 2 leads. The sweep MUST detect it.
    """
    docs = _recall._load_corpus(REPO_ROOT)
    monkeypatch.setattr(_recall, "_load_corpus", lambda _root, _d=docs: _d)
    real_union = _recall.recall_union

    def reversed_union(query, root, *, top=1):
        hits = real_union(query, root, top=top)
        return list(reversed(hits))

    monkeypatch.setattr(_recall, "recall_union", reversed_union)
    assert _sweep_for_displacement(docs), (
        "the displacement sweep stayed green with pass 2 leading -- it cannot "
        "detect the reordering it exists to forbid"
    )


def _sweep_for_displacement(docs):
    displaced = []
    for doc in docs:
        single = _recall.recall(doc.snippet, REPO_ROOT, top=1)
        union = _recall.recall_union(doc.snippet, REPO_ROOT, top=1)
        if single and (not union or union[0].source != single[0].source):
            displaced.append(doc.source)
    return displaced


def test_the_second_rankers_winner_is_presented_second(monkeypatch):
    """recall_union property 3: whatever pass 2 ranks first is element 1 of the
    union whenever it differs from pass 1's winner -- for every corpus title.

    This is the DEF-679 fix, pinned as a CONSTRUCTION property like the sweep
    above. Before 2026-09-04 the union was pass 1's slots followed by pass 2's,
    so a document the second ranker put first was the third or fourth thing a
    reader saw; for `is the harness a security boundary` that was
    STANDING_PRINCIPLES section 2, behind two documents that cite it. Nothing
    about recall() changed: the scored SET is identical, element 0 is identical,
    only the order of the tail moved. test_the_second_slot_sweep_can_actually_fire
    is the must-trip twin; it restores the old concatenation and requires this
    sweep to catch it.
    """
    docs = _recall._load_corpus(REPO_ROOT)
    assert len(docs) >= 100, f"corpus collapsed to {len(docs)} -- assertion would be vacuous"
    monkeypatch.setattr(_recall, "_load_corpus", lambda _root, _d=docs: _d)
    misplaced, disagreements = _sweep_for_second_slot(docs)
    # Non-vacuity: if the two passes never disagreed on a winner, the property
    # would hold with nothing to hold it on.
    assert disagreements >= 10, (
        f"the two passes disagreed on a winner for only {disagreements} titles -- "
        "the second-slot property has nothing to bite on; check the second ranker"
    )
    assert not misplaced, (
        f"{len(misplaced)} title(s) had pass 2's winner presented somewhere other "
        f"than element 1 of the union: {misplaced[:5]}"
    )


def test_the_second_slot_sweep_can_actually_fire(monkeypatch):
    """Must-trip twin: rebuild the pre-2026-09-04 construction (pass 1's slots,
    THEN pass 2's) and require the sweep to detect it."""
    docs = _recall._load_corpus(REPO_ROOT)
    monkeypatch.setattr(_recall, "_load_corpus", lambda _root, _d=docs: _d)

    def concatenated_union(query, root, *, top=1):
        seen, out = set(), []
        for hit in [*_recall.recall(query, root, top=top, norm=_recall._vocab_norm, docs=docs),
                    *_recall.recall(query, root, top=top, norm=_recall._totlen_norm, docs=docs)]:
            if hit.source in seen:
                continue
            seen.add(hit.source)
            out.append(hit)
        return out

    monkeypatch.setattr(_recall, "recall_union", concatenated_union)
    misplaced, _ = _sweep_for_second_slot(docs)
    assert misplaced, (
        "the second-slot sweep stayed green with pass 1's runner-up printed ahead "
        "of pass 2's winner -- it cannot detect the ordering it exists to forbid"
    )


def _sweep_for_second_slot(docs):
    """``(misplaced, disagreements)``: titles where pass 2's winner is not element 1
    of the union, and how many titles the two passes disagreed on at all."""
    misplaced, disagreements = [], 0
    for doc in docs:
        second = _recall.recall(doc.snippet, REPO_ROOT, top=1, norm=_recall._totlen_norm)
        union = _recall.recall_union(doc.snippet, REPO_ROOT, top=_PARAPHRASE_UNION_TOP)
        if not second or not union or second[0].source == union[0].source:
            continue
        disagreements += 1
        if len(union) < 2 or union[1].source != second[0].source:
            misplaced.append(doc.source)
    return misplaced, disagreements


def test_cli_shim_emits_the_union_not_the_single_ranker():
    """Pins the ONLY operator-visible change in this feature.

    Both union tests call recall_union() directly; nothing else drives the __main__
    shim. Reverting that one line to recall() left all 61 tests green while the
    feature silently vanished -- and the /recall command body would keep telling
    Claude to compare two candidates that no longer exist.
    """
    script = REPO_ROOT / "tools" / "cc" / "hooks" / "_recall.py"
    result = subprocess.run(
        [sys.executable, str(script), "is the harness a security boundary"],
        capture_output=True, text=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(REPO_ROOT)}, check=False, encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("source:") >= 2, (
        "the shim emitted fewer than two candidates -- reverted to recall()? "
        f"stdout was:\n{result.stdout}"
    )


def test_every_corpus_doc_names_its_family():
    """DEF-562. The SessionStart orientation line names what /recall indexes,
    and it used to be a hand-written list of three sources while the loader
    indexed four on this tree. It is now read off the corpus: every yield site
    in ``_iter_corpus`` labels its family, and ``indexed_sources`` is the ordered
    set of the labels that actually yielded. DERIVED population: a source added
    to the loader without a family label reds here, before it can be indexed
    unnamed."""
    docs = _recall._load_corpus(REPO_ROOT)
    assert len(docs) > 200, "corpus collapsed; the assertions below would be vacuous"
    unlabelled = [d.source for d in docs if not d.family]
    assert not unlabelled, f"corpus docs with no source family: {unlabelled[:5]}"
    # A per-family floor, because the total above cannot see an amputation: the
    # fence-aware splitter (DEF-565) makes an UNCLOSED fence swallow every section
    # below it, and one stray opener at 85% of docs/SHARP_EDGES.md measured 179 -> 161
    # sections with `len(docs) > 200` still green.
    by_family = Counter(d.family for d in docs)
    assert by_family["docs/SHARP_EDGES.md sections"] >= 150, (
        f"docs/SHARP_EDGES.md contributes {by_family['docs/SHARP_EDGES.md sections']} corpus "
        "docs, not ~179 -- an unclosed code fence swallows every section below it now that "
        "iter_doc_sections is fence-aware; find the unbalanced fence (see "
        "test_every_corpus_doc_closes_its_fences) before touching this floor"
    )
    families: list[str] = []
    for d in docs:
        if d.family not in families:
            families.append(d.family)
    assert _recall.indexed_sources(REPO_ROOT) == families


def test_pull_excluded_memory_notes_exist_and_are_not_indexed():
    """Each excluded note must exist on this tree (a stale exclusion is a silent
    no-op nobody sees) and must be absent from the live corpus."""
    sources = {d.source for d in _recall._load_corpus(REPO_ROOT)}
    # The exact on-disk spelling, not `is_file()`: on a case-insensitive
    # filesystem `is_file()` answers yes for any casing, and a differently-cased
    # file would be indexed under a name this loop never checks.
    on_disk = {f"memory/{p.name}" for p in (REPO_ROOT / "memory").glob("*.md")}
    for src in _recall.PULL_EXCLUDED_MEMORY_NOTES:
        assert src in on_disk, f"{src} is excluded but no file of exactly that name exists"
        assert src not in sources, f"{src} is indexed despite the exclusion"


def test_pull_exclusion_is_the_gate_not_the_files(tmp_path, monkeypatch):
    """Both ways: the excluded names are skipped where they exist, and opening
    the gate indexes the same files -- the gate is the load-bearing line, not
    corpus emptiness (the same proof shape the exemplar gate carries)."""
    monkeypatch.setattr(_recall, "EXEMPLAR_MAP", {})
    excluded = sorted(_recall.PULL_EXCLUDED_MEMORY_NOTES)
    mem = tmp_path / "memory"
    mem.mkdir()
    for src in excluded:
        (tmp_path / src).write_text("# Excluded\n\nrounds ledger rows authoring\n", encoding="utf-8")
    (mem / "kept.md").write_text("# Kept note\n\nkept note body words\n", encoding="utf-8")
    assert [d.source for d in _recall._load_corpus(tmp_path)] == ["memory/kept.md"]
    monkeypatch.setattr(_recall, "PULL_EXCLUDED_MEMORY_NOTES", {})
    assert sorted(d.source for d in _recall._load_corpus(tmp_path)) == sorted(["memory/kept.md", *excluded])


def test_pull_exclusion_record_members_are_the_canon():
    """The ``record`` members are a forced twin of the record axis
    (espalier.claim_extractor.RECORD_SURFACES) restricted to the one corpus root
    the loader reads whole, ``memory/``; the ``aggregate`` member is the
    operator's measured call and is deliberately NOT bound to the canon. Both
    directions, so a record surface added under memory/ reds here until the
    ranker skips it, and a note excluded as a record must be one."""
    from espalier.claim_extractor import RECORD_SURFACES as canon

    excluded = _recall.PULL_EXCLUDED_MEMORY_NOTES
    record = {src for src, why in excluded.items() if why == "record"}
    # Every canon key the loader could READ (the tier script's corpus predicate
    # is the one home of that roster), minus the one deliberate exception: the
    # failure-mode catalog is a record for its point-in-time counts but is
    # indexed by coinage title on purpose -- see the constant's docstring.
    readable = {src for src in canon if _proof_tier().is_recall_corpus(src)}
    assert "docs/FAILURE_MODES.md" in readable, "the canon no longer lists the catalog; re-read the carve-out"
    expected = readable - {"docs/FAILURE_MODES.md"}
    assert record == expected, (
        f"a record surface the pull ranker can read is indexed: add {sorted(expected - record)} "
        f"to PULL_EXCLUDED_MEMORY_NOTES in tools/cc/hooks/_recall.py as 'record' (or, for "
        f"{sorted(record - expected)}, the canon no longer calls it a record -- re-read the row)"
    )
    assert set(excluded.values()) <= {"record", "aggregate"}, excluded
    assert excluded.get("memory/task-packs.md") == "aggregate"


def test_pull_exclusion_is_case_folded(tmp_path, monkeypatch):
    """A case-insensitive filesystem serves the excluded name under any spelling,
    so an exact-string skip would index ``memory/Task-Packs.md`` while every
    live assertion about ``memory/task-packs.md`` stayed green (driven by the
    failure-mode review on APFS)."""
    monkeypatch.setattr(_recall, "EXEMPLAR_MAP", {})
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "Task-Packs.md").write_text("# Task pack authoring\n\npack authoring rows\n", encoding="utf-8")
    (mem / "kept.md").write_text("# Kept note\n\nkept note body words\n", encoding="utf-8")
    assert [d.source for d in _recall._load_corpus(tmp_path)] == ["memory/kept.md"]


def test_the_push_side_still_sees_the_pull_excluded_notes(tmp_path, monkeypatch):
    """The exclusion is the PULL ranker's. ``nearest_by_title`` answers the
    reflect protocol's "which existing note is ABOUT this paragraph", and the two
    notes the ranker leaves out are exactly the canon homes a pack-shaped or a
    convergence-shaped insight must be folded into; driven by the failure-mode
    review with the exclusion in the shared loader, a pack paragraph's nearest
    note fell from memory/task-packs.md to a SHARP_EDGES section. Both ways on a
    tmp tree, then the live cell."""
    monkeypatch.setattr(_recall, "EXEMPLAR_MAP", {})
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "task-packs.md").write_text("# Task pack authoring\n\npack authoring rows\n", encoding="utf-8")
    (mem / "kept.md").write_text("# Kept note\n\nkept note body words\n", encoding="utf-8")
    assert [d.source for d in _recall._load_corpus(tmp_path)] == ["memory/kept.md"]
    assert sorted(d.source for d in _recall._load_full_corpus(tmp_path)) == ["memory/kept.md", "memory/task-packs.md"]
    hits = _recall.nearest_by_title("authoring a task pack", tmp_path, top=3)
    assert hits and hits[0].source == "memory/task-packs.md", hits
    live = _recall.nearest_by_title(
        "a task pack's Scope (in) and Affected symbols sections, authoring the pack before execution",
        REPO_ROOT, top=3)
    assert "memory/task-packs.md" in [h.source for h in live], live


def test_indexed_sources_follows_the_corpus_gates(tmp_path, monkeypatch):
    """A family is named exactly when one of its docs yielded on THIS tree --
    the gates are asked, never restated. Same shape as
    test_indexes_failure_modes_matches_the_corpus, one level up."""
    monkeypatch.setattr(_recall, "EXEMPLAR_MAP", {})
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "a.md").write_text("# A\nalpha beta gamma\n", encoding="utf-8")
    assert _recall.indexed_sources(tmp_path) == ["memory/"]

    docs = tmp_path / "docs"
    docs.mkdir()
    # An adopter who authored their own principles gets them named (DEF-562's
    # exact miss: the old constant could not say this).
    (docs / "STANDING_PRINCIPLES.md").write_text(
        "# Principles\n\n## 1. Earn the red\n\nprove the gate catches it\n", encoding="utf-8")
    assert _recall.indexed_sources(tmp_path) == ["memory/", "docs/STANDING_PRINCIPLES.md"]

    # The seeded SHARP_EDGES scaffold yields no doc, so its family is not named.
    seed = next((REPO_ROOT / "espalier" / "assets" / "seed").glob("SHARP_EDGES*.md"))
    (docs / "SHARP_EDGES.md").write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")
    assert "SHARP_EDGES" not in " ".join(_recall.indexed_sources(tmp_path))

    # FAILURE_MODES present but gated off this tree: not named. Force the gate
    # open and the family follows the corpus -- not a second copy of the rule.
    (docs / "FAILURE_MODES.md").write_text(
        (REPO_ROOT / "espalier" / "assets" / "docs" / "FAILURE_MODES.md").read_text(encoding="utf-8"),
        encoding="utf-8")
    assert "FAILURE_MODES" not in " ".join(_recall.indexed_sources(tmp_path))
    monkeypatch.setattr(_recall, "indexes_failure_modes", lambda root: True)
    assert "docs/FAILURE_MODES.md section-1 coinages" in _recall.indexed_sources(tmp_path)


def test_an_exact_score_tie_prefers_the_focused_doc_over_the_aggregate(tmp_path, monkeypatch):
    """DEF-532's recall leg. On an EXACT score tie the final sort key was the
    source path, reverse-lexicographic -- arbitrary with respect to what the
    doc is about. An exact tie means equal matched terms and equal vocabulary
    (the norm is vocabulary-keyed), so the one signal left is length: the
    focused doc says what the query says and little else; the aggregate says it
    among much more. Built so the focused doc's path sorts LOWER: under the old
    key `zzz.md` won on its name."""
    root = _synth(tmp_path, monkeypatch, {
        "aaa.md": "# Focused\nwidget\n",                       # vocab 2, length 2
        "zzz.md": "# Aggregate\nwidget widget widget\n",       # vocab 2, length 4
        "pad1.md": "# Pad1\ndelta epsilon\n",
        "pad2.md": "# Pad2\nkappa lambda\n",
    })
    hits = _recall.recall("widget", root, top=2)
    assert [h.source for h in hits] == ["memory/aaa.md", "memory/zzz.md"], hits
    assert hits[0].score == hits[1].score, "the fixture must be an EXACT tie or it tests nothing"


def test_a_memory_note_named_by_its_own_title_wins_the_tie_it_used_to_lose():
    """The live instance the measurement found (2026-09-04): this query is the
    exact title of `memory/a-fixed-fail-open-can-move-rather-than-close.md`, and
    it tied `memory/an-exemption-outlives-its-own-premise.md` to the last float,
    which then won on its path. If the tie ever dissolves this still holds --
    a doc named by its own title is the unarguable answer."""
    hits = _recall.recall("A fixed fail-open can move rather than close", REPO_ROOT, top=1)
    assert hits and hits[0].source == "memory/a-fixed-fail-open-can-move-rather-than-close.md", hits


def test_every_corpus_doc_closes_its_fences():
    """DEF-565's cost, gated. A fence-aware splitter reads an UNCLOSED fence the way
    a CommonMark renderer does: everything below it is code, so every ``## `` after
    a stray opener silently leaves the recall corpus (measured: 179 -> 161
    SHARP_EDGES sections from one opener, no other gate red). Before the collapse
    the splitter was fence-blind and the same typo cost nothing. So every file the
    corpus reads must end with its fences balanced -- derived from the loader's own
    sources, and the failure names the file and the fence left open."""
    roots = [REPO_ROOT / "docs" / "SHARP_EDGES.md", REPO_ROOT / "docs" / "STANDING_PRINCIPLES.md",
             REPO_ROOT / "docs" / "STANDING_PRINCIPLES.aliases.md", REPO_ROOT / "docs" / "FAILURE_MODES.md"]
    roots += sorted((REPO_ROOT / "memory").glob("*.md")) + sorted((REPO_ROOT / "docs" / "sharp-edges").glob("*.md"))
    assert len(roots) > 50, "corpus file set collapsed; the sweep below would be vacuous"
    unbalanced = []
    for path in roots:
        fence = None
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            fence = _hook_utils.next_fence_state(line, fence)
        if fence is not None:
            unbalanced.append((str(path.relative_to(REPO_ROOT)), fence))
    assert not unbalanced, (
        f"unclosed code fence(s) -- every heading below each is now invisible to /recall: {unbalanced}"
    )
