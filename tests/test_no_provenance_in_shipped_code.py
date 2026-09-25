"""Shipping-surface provenance census — the de-provenance spine regression gate.

The detection logic (``PROVENANCE_RE`` + the scope/allowlist + ``census_offenders``)
is the single source of truth in ``espalier.provenance_census``, consumed BOTH
here and by the ``espalier provenance`` CLI / the ``/smoke`` check — so "what
counts as a provenance tag" has exactly one definition. This module is the
regression gate: a future comment that re-accretes a build-history tag on a
shipped surface (the wheel + sdist payload plus the GitHub-browsable tree) reds
here.

Add a load-bearing entry to ``espalier.provenance_census._ALLOWED_HITS`` (with a
reason) rather than disabling the guard.
"""
from __future__ import annotations

# pytest-marker: default-unit  (fast file-scan contract test)
from collections import Counter

from espalier.provenance_census import PROVENANCE_RE, census_offenders


class TestNoProvenanceInShippedCode:
    def test_provenance_re_catches_tq_subtask_tags(self):
        # The TQ- (test-quality sub-task) vocabulary must be caught on shipping
        # surfaces. Regression: TQ-adopter-3 leaked into
        # espalier/scanners/test_loosening.py because the pattern was TP-only.
        assert PROVENANCE_RE.search("# TQ-adopter-3: a test_* that proves nothing")
        assert PROVENANCE_RE.search("see TQ-7 for the rule")
        # ...without false-positiving on benign prose that merely contains "TQ".
        assert not PROVENANCE_RE.search("the STATUS code was 3 on retry")

    def test_no_build_history_on_shipping_surfaces(self):
        offenders = census_offenders()
        by_dir = Counter(rel.split("/")[0] for rel, _n, _t in offenders)
        sample = "\n".join(f"  {rel}:{n}  {txt}" for rel, n, txt in offenders[:40])
        assert not offenders, (
            f"{len(offenders)} internal build-history tags on shipping surfaces "
            f"(de-provenance incomplete). By top-dir: {dict(by_dir)}\n"
            f"First 40:\n{sample}\n"
            "Strip the provenance wrapper (keep the behavioral content), or add a "
            "load-bearing entry to espalier.provenance_census._ALLOWED_HITS with a reason."
        )
