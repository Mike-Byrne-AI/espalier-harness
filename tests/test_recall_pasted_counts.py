"""The three pasted recall counts -- corpus size, heading arm, stripped arm --
against the live corpus, in about a second.

Why a module of its own: the counts are the whole red signal when the corpus
grows (measured 2026-09-09: nine new documents pushed all three counts past the
3% band then in force, the corpus count by 0.06 of a document, while every
rate cell stayed inside its band), and until now the only test reading
them dragged a five-alpha sweep along under ``@pytest.mark.slow``, so the breach
surfaced in the full tier three commits after the memory commit that caused it.
The count band is now the larger of five documents or a tenth of the pasted
value (``tests/_recall_pins.py``), so a re-paste is owed when the corpus has
materially grown, not on every note.
scripts/check_handoff_landing.py runs this module conditionally -- whenever a
session touched a corpus root -- so the catch moves to the commit that ages the
pins (STANDING_PRINCIPLES §17). The rate cells keep their guards in
tests/test_recall_eval.py, where the sweeps they need already run.

Loaded via ``importlib.spec_from_file_location`` per ``tests/CLAUDE.md`` --
``scripts/`` is not an importable package.
"""
from __future__ import annotations

import collections
import importlib.util
import sys
from pathlib import Path

import pytest

from tests._recall_pins import (
    ALPHA_PROVENANCE_RE,
    BAND,
    COUNT_BAND,
    COUNT_FLOOR,
    BODY_AGREEMENT_RE,
    EVAL_SCRIPT,
    RECALL_BODY,
    STRIP_PROVENANCE_RE,
    alpha_block,
    block_prose,
    count_drift,
    rate_drift,
    strip_block,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE = REPO_ROOT / "scripts" / "check_handoff_landing.py"
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))
import _recall  # noqa: E402

#: Corpus families that are not files under a corpus root: the exemplar
#: pointers tools/cc/hooks/_recall.py builds from its own EXEMPLAR_MAP. Named,
#: not filtered by `is_file()`, so a new non-file family is flagged rather
#: than silently exempted.
NON_FILE_FAMILIES = frozenset({"pull-only shape pointers"})


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve string annotations here
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def eval_mod():
    return _load(EVAL_SCRIPT, "recall_eval_for_counts")


@pytest.fixture(scope="module")
def corpus():
    return _recall._load_corpus(REPO_ROOT)


@pytest.fixture(scope="module")
def live(eval_mod, corpus):
    """The three counts, derived from the instrument's own label builders."""
    return {
        "corpus": len(corpus),
        "heading arm": len(eval_mod.heading_labels(corpus)),
        "stripped arm": len(eval_mod.stripped_labels(corpus)),
    }


def test_the_alpha_table_provenance_counts_track_the_corpus(live):
    m = ALPHA_PROVENANCE_RE.search(block_prose(alpha_block()))
    assert m, "tools/cc/hooks/_recall.py lost the alpha table's provenance line"
    corpus_n, heading_n, stripped_n = int(m.group(1)), int(m.group(2)), int(m.group(3))
    stale = [d for d in (
        count_drift("corpus", corpus_n, live["corpus"]),
        count_drift("heading arm", heading_n, live["heading arm"]),
        count_drift("stripped arm", stripped_n, live["stripped arm"]),
        # The arms are the rate cells' denominators. Their SHARE of the corpus
        # is invariant to ordinary growth and reds under the tight rate band
        # when a root is skipped or a heading parse stops producing labels --
        # the coverage regression the wide count band would otherwise absorb.
        rate_drift("heading arm share", heading_n / corpus_n, live["heading arm"] / live["corpus"]),
        rate_drift("stripped arm share", stripped_n / corpus_n, live["stripped arm"] / live["corpus"]),
    ) if d]
    assert not stale, (
        "the LENGTH_NORM_ALPHA table in tools/cc/hooks/_recall.py was pasted over a "
        "smaller corpus. Regenerate it with `python3 scripts/recall_eval.py --alpha-sweep` "
        "LAST in this commit (after every memory/ and docs/ edit), keep the hand "
        "annotations, and re-sync the vendor mirror:\n  " + "\n  ".join(stale)
    )


def test_the_strip_table_provenance_count_tracks_the_corpus(live):
    m = STRIP_PROVENANCE_RE.search(strip_block())
    assert m, "scripts/recall_eval.py lost the STRIP_FRACTION table's provenance line"
    drift = count_drift("corpus", int(m.group(1)), live["corpus"])
    assert drift is None, (
        "the STRIP_FRACTION table in scripts/recall_eval.py was pasted over a smaller "
        "corpus. Regenerate it with `python3 scripts/recall_eval.py --sweep` LAST in this "
        f"commit and re-date its provenance line: {drift}"
    )


def test_the_recall_body_count_tracks_the_heading_arm(live):
    body = RECALL_BODY.read_text(encoding="utf-8")
    m = BODY_AGREEMENT_RE.search(body)
    assert m, (".claude/commands/recall.md no longer quotes the agreement figure as "
               "'N of M queries naming a document'")
    drift = count_drift("naming queries", int(m.group(2)), live["heading arm"])
    assert drift is None, (
        "the /recall body's agreement figure was measured on a smaller heading arm. "
        "Re-measure with `python3 scripts/recall_eval.py`, re-date the body, and re-sync "
        f"the claude mirrors: {drift}"
    )


def test_the_loader_sees_every_file_under_each_file_backed_root(corpus):
    """Independent of any pasted number: the two directory families are counted
    off the disk and compared with what the loader yielded, so a skipped root
    or a filter that starts dropping files reds even though the wide count band
    would absorb the missing documents."""
    seen = collections.Counter(d.family for d in corpus)
    # The loader's two NAME-keyed skips under memory/ (README.md and the notes
    # PULL_EXCLUDED_MEMORY_NOTES names, 2026-09-12) are applied on the disk side
    # too, so a filter that starts dropping anything else still reds here; the
    # excluded names themselves are pinned to exist in tests/test_recall.py.
    on_disk = {
        "memory/": sum(1 for p in (REPO_ROOT / "memory").glob("*.md")
                       if p.name != "README.md"
                       and f"memory/{p.name}" not in _recall.PULL_EXCLUDED_MEMORY_NOTES),
        "docs/sharp-edges/": sum(
            1 for p in (REPO_ROOT / "docs" / "sharp-edges").glob("*.md") if p.name != "README.md"
        ),
    }
    for family, n in on_disk.items():
        assert n > 0, f"{family}: the on-disk listing is empty -- the check would pass vacuously"
        assert seen[family] == n, (
            f"{family}: {n} files on disk, {seen[family]} documents loaded -- the loader is "
            f"skipping files under a root it is supposed to cover"
        )


def test_the_handoff_gate_watches_every_corpus_root(corpus):
    """The gate runs this module only when a session touched one of its trigger
    prefixes. A corpus document outside those prefixes is an aging path the gate
    cannot see, so the trigger set is checked against the corpus, never retyped."""
    gate = _load(GATE, "check_handoff_landing_for_counts")
    entry = gate.CONDITIONAL.get("tests/" + Path(__file__).name)
    assert entry, "scripts/check_handoff_landing.py no longer lists this module in CONDITIONAL"
    _, triggers = entry
    roots, unresolved = set(), []
    for doc in corpus:
        if doc.family in NON_FILE_FAMILIES:
            continue
        path = doc.source.split(" :: ")[0]
        if (REPO_ROOT / path).is_file():
            roots.add(path)
        else:
            unresolved.append(f"{doc.source} (family {doc.family!r})")
    assert roots, "no corpus document resolved to a file -- the check would pass vacuously"
    assert not unresolved, (
        "corpus documents of a file-backed family do not resolve to a file, or a new "
        "non-file family appeared -- name it in NON_FILE_FAMILIES if it has no root:\n  "
        + "\n  ".join(unresolved[:10])
    )
    unwatched = sorted(p for p in roots if not any(p.startswith(t) for t in triggers))
    assert not unwatched, (
        f"corpus documents live outside the gate's trigger prefixes {triggers}:\n  "
        + "\n  ".join(unwatched[:10])
    )


class TestDriftRules:
    """The two drift rules, pinned on the cases that motivated their bands.

    Counts are provenance (the corpus size a table was swept on); rates are
    the claim (the shipped constant is at the peak). A count moves with every
    memory note, so its band is wide -- the larger of ``COUNT_FLOOR``
    documents or ``COUNT_BAND`` of the pasted value; measured 2026-09-09, a
    single added document moved a ``too_short`` cell from 20 to 22 and the
    old 3% band (0.6 of a document, floored at one) reddened the tier on it.
    A rate moves only when the ranker's behaviour moves, so its band stays
    at three points. The outside cases keep the bands from being widened
    into silence.
    """

    def test_a_small_count_absorbs_ordinary_corpus_growth(self):
        assert count_drift("too_short", 20, 22) is None
        assert count_drift("too_short", 20, 25) is None

    def test_a_small_count_still_reds_past_the_floor(self):
        assert count_drift("too_short", 20, 26) is not None
        assert count_drift("too_short", 20, 14) is not None

    def test_a_large_count_uses_the_relative_band(self):
        assert count_drift("corpus", 300, 330) is None
        assert count_drift("corpus", 300, 331) is not None
        assert count_drift("corpus", 300, 269) is not None

    def test_the_band_is_taken_over_the_pasted_value(self):
        # 298 pasted, 330 live: 32 off, band 29.8 -> stale. Over the LIVE
        # value the band would be 33 and the same drift would pass.
        assert count_drift("corpus", 298, 330) is not None

    def test_rates_keep_the_three_point_band(self):
        assert rate_drift("heading@1", 0.850, 0.879) is None
        assert rate_drift("heading@1", 0.850, 0.881) is not None
        assert rate_drift("heading@1", 0.850, 0.819) is not None

    def test_a_tiny_count_keeps_a_tight_band(self):
        # below the floor a cell is claim-like: half its value, at least one
        assert count_drift("too_short", 0, 1) is None
        assert count_drift("too_short", 0, 2) is not None
        assert count_drift("too_short", 2, 3) is None
        assert count_drift("too_short", 2, 4) is not None
        assert count_drift("too_short", 4, 6) is None
        assert count_drift("too_short", 4, 7) is not None

    def test_the_band_constants_are_the_calibrated_values(self):
        assert COUNT_FLOOR == 5
        assert COUNT_BAND == 0.10
        assert BAND == 0.03

    def test_the_handoff_gate_describes_the_live_band(self):
        """The operator reads the band in the gate's own description at handoff;
        it is checked against the constants so a re-calibration cannot leave
        it lying."""
        gate = _load(GATE, "check_handoff_landing_for_band")
        desc, _ = gate.CONDITIONAL["tests/" + Path(__file__).name]
        assert f"{COUNT_FLOOR} documents" in desc, desc
        assert f"{round(COUNT_BAND * 100)}%" in desc, desc


def test_every_task_arm_label_names_a_live_corpus_source(eval_mod, corpus):
    """DEF-699: `_TASK_ARM` labels are exact `source:` strings (a SHARP_EDGES
    heading, em-dash included); a renamed heading turns a label into a
    permanent silent miss that reads as a ranking regression. This module runs
    on the landing gate's own trigger set (memory/, SHARP_EDGES, the script), so
    the rot is caught at the commit that renames, not at the next full tier."""
    sources = {d.source for d in corpus}
    dead = [lb.expected for lb in eval_mod.task_labels() if lb.expected not in sources]
    assert not dead, f"rename the label to the heading's new text: {dead}"
