"""Shared pins for the recall calibration tables and the /recall body figures.

One band, one drift rule per figure kind, and one slicer per pasted surface,
imported by tests/test_recall_eval.py (the sweep-backed guards) and
tests/test_recall_pasted_counts.py (the one-second count guard the handoff gate
runs). The first cut of the count guard retyped the band and the provenance
regex from its slow twin and denominated the band on the LIVE count, so the
corpus count (298 pasted, 307 live) sat 0.21 of a document inside a band it was
written to breach. Both bands are taken over the PASTED value -- the number
being defended.

Two rules, because the two kinds of figure age differently. A RATE is the
claim (the shipped constant sits at the sweep's peak) and moves only when the
ranker moves, so its band is three points and is never widened. A COUNT is
provenance (the corpus size a table was swept on, the arm it measured) and
moves with every memory note, so its band is the larger of ``COUNT_FLOOR``
documents or ``COUNT_BAND`` of the pasted value. Measured 2026-09-09: under a
3% count band with a floor of one document, ONE added note moved a
``too_short`` cell from 20 to 22 and reddened the full tier; a re-sweep costs
about a minute of sweeps and three pasted sites, one of them a shipped hook.
With the wide band a re-paste is owed when the corpus has grown by a tenth,
and the rate guards still catch a ranker regression the day it lands.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RECALL_HOOK = REPO_ROOT / "tools" / "cc" / "hooks" / "_recall.py"
EVAL_SCRIPT = REPO_ROOT / "scripts" / "recall_eval.py"
RECALL_BODY = REPO_ROOT / ".claude" / "commands" / "recall.md"

#: Relative drift a pasted RATE may carry before it is stale. Never widen it;
#: a wider rate band hides a ranker regression. Re-measure and re-paste instead,
#: LAST in a commit that also edits memory/ or docs/ -- the corpus is the tree
#: you run in.
BAND = 0.03

#: A pasted COUNT is stale past the larger of these two: an absolute floor in
#: documents (so a cell of 20 is not held to one document) and a relative band
#: of the pasted value (so a corpus of 300 is not held to five). Provenance
#: ages by construction; these are sized so ordinary growth between re-pastes
#: stays green and a materially different corpus does not.
COUNT_FLOOR = 5
COUNT_BAND = 0.10

#: The alpha table's provenance line, read over the comment block as prose.
ALPHA_PROVENANCE_RE = re.compile(
    r"Corpus (\d+) docs.*?heading arm (\d+)\s+queries, stripped arm (\d+)", re.S)
#: The strip table's provenance line.
STRIP_PROVENANCE_RE = re.compile(r"Swept \d{4}-\d{2}-\d{2} on the live (\d+)-document corpus")
#: The /recall body's agreement figure.
BODY_AGREEMENT_RE = re.compile(r"\((\d+) of (\d+) queries naming a document")


def count_drift(name: str, pasted: int, fresh: int) -> str | None:
    """A stale line for a pasted COUNT, or None while it is inside its band.

    At or above ``COUNT_FLOOR`` the band is the larger of ``COUNT_FLOOR``
    documents or ``COUNT_BAND`` of the pasted value. Below it the cell is
    claim-like, not provenance (a too_short of 0 at fraction 0.5 says no
    heading is stripped under two tokens there), and keeps a band of half its
    value, at least one, so a tiny cell cannot drift to five in silence.
    """
    if pasted < COUNT_FLOOR:
        band = max(1, pasted // 2)
    else:
        band = max(COUNT_FLOOR, COUNT_BAND * pasted)
    if abs(pasted - fresh) > band:
        return f"{name}: pasted {pasted}, fresh {fresh}"
    return None


def rate_drift(name: str, pasted: float, fresh: float) -> str | None:
    """A stale line for a pasted RATE (a fraction in [0, 1]), or None."""
    if abs(pasted - fresh) > BAND:
        return f"{name}: pasted {pasted:.1%}, fresh {fresh:.1%}"
    return None


def alpha_block() -> str:
    """The LENGTH_NORM_ALPHA comment block in tools/cc/hooks/_recall.py."""
    src = RECALL_HOOK.read_text(encoding="utf-8")
    head = src[:src.index("\nLENGTH_NORM_ALPHA = ")]
    return head[head.rindex("#: Exponent on a document's vocabulary size"):]


def strip_block() -> str:
    """The STRIP_FRACTION comment block in scripts/recall_eval.py."""
    src = EVAL_SCRIPT.read_text(encoding="utf-8")
    head = src[:src.index("\nSTRIP_FRACTION = ")]
    return head[head.rindex("#: Document-frequency fraction above which"):]


def min_kept_block() -> str:
    """The MIN_STRIPPED_TOKENS comment block in scripts/recall_eval.py."""
    src = EVAL_SCRIPT.read_text(encoding="utf-8")
    head = src[:src.index("\nMIN_STRIPPED_TOKENS = ")]
    return head[head.rindex("#: Minimum tokens a STRIPPED query must keep"):]


def block_prose(block: str) -> str:
    """A ``#:`` comment block as one line, so a sentence that wraps still matches."""
    return re.sub(r"\n#:\s*", " ", block)
