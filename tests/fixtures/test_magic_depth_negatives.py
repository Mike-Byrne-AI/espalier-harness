"""Must-NOT-trip negatives corpus for ``espalier.scanners.magic_depth``.

Companion to ``test_magic_depth_positives.py``: where the positives
fixture earns the gate (every flagged ``parents[N>=2]`` shape surfaces),
this fixture proves the scanner STAYS SILENT on clean-but-tempting
constructs. The direct-call test (``_scan_file`` on this path) must
report ZERO ``MagicDepthFinding`` objects — not even a PINNED one.

Why these stay clean (mirrors ``magic_depth._scan_file`` logic):

* ``parents[0]`` / ``parents[1]`` — a ``parents`` subscript, but the
  constant index is < 2, so ``_scan_file`` skips it (the ``depth < 2``
  guard) before yielding anything.
* ``children[3]`` / a plain list index — a deep constant subscript that
  LOOKS structural, but the attribute is not ``parents``, so
  ``_is_parents_subscript`` rejects it.
* a dynamic index on a non-``parents`` attribute — same rejection; the
  dynamic-index UNPINNED path only fires for ``.parents[<expr>]``.

Note on pragmas: a ``# magic-depth: ok <reason>`` pragma above a real
``parents[2]`` produces a PINNED *finding* (severity flips, the finding
is NOT suppressed). Because this corpus asserts ZERO findings, no
``parents[>=2]`` appears here at all — pinned or otherwise. The pragma
mechanism's clean path is exercised by the positives/live-repo tests,
not here.

Fixtures only — NO real assertions. Inner functions OMIT the ``test_``
prefix so pytest does not collect them. The file itself is named
``test_*`` so the collector's ``rglob('test_*.py')`` still discovers it
(matching the positives fixture's discoverability convention).
"""
from __future__ import annotations

from pathlib import Path


# precision-boundary: a multi-line parents-chain whose subscript line differs
# from the expression-start line — line attribution follows the access line,
# not the expression start.


def clean_parents_0() -> Path:
    # parents[0] — a parents subscript, but depth < 2 is skipped.
    return Path(__file__).resolve().parents[0]


def clean_parents_1() -> Path:
    # parents[1] — still below the depth-2 floor; never yielded.
    return Path(__file__).resolve().parents[1]


def clean_deep_non_parents_index() -> int:
    # Deep constant index, but the attribute is not `parents`, so
    # `_is_parents_subscript` rejects it before depth is even read.
    rows = [0, 1, 2, 3, 4, 5]
    holder = Path(__file__)
    holder.children = rows  # type: ignore[attr-defined]
    return holder.children[3]  # type: ignore[attr-defined]


def clean_dynamic_non_parents_index() -> int:
    # Dynamic index, but on a non-`parents` attribute — the
    # dynamic-UNPINNED path only fires for `.parents[<expr>]`.
    n = 4
    holder = Path(__file__)
    holder.ancestors = [10, 20, 30, 40, 50]  # type: ignore[attr-defined]
    return holder.ancestors[n]  # type: ignore[attr-defined]


def clean_plain_list_deep_index() -> int:
    # A bare subscript with a large constant — no `.parents` attribute
    # value at all, so the scanner never inspects the index.
    data = list(range(10))
    return data[7]


def clean_parents_negative_index() -> Path:
    # TP-174b R24: a negative index is a from-the-end reference, not a
    # positive structural depth — `_extract_constant_index` resolves the
    # USub-wrapped constant to -1 so the depth<2 floor skips it. Pre-fix
    # this yielded a spurious UNPINNED `parents[<dynamic>]` finding.
    return Path(__file__).resolve().parents[-1]


def clean_chained_parent_attribute() -> Path:
    # TP-174b T11 lock: the chained `.parent.parent.parent` spelling is an
    # Attribute chain, NOT a `parents[N]` subscript, so the scanner stays
    # silent by design. The explicit chain spells its depth out in source
    # (it hides no magic literal), so it is intentionally NOT flagged —
    # widening the scanner to catch it would over-fire on ~228 benign sites.
    return Path(__file__).resolve().parent.parent.parent
