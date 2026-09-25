"""TP-59 BC-034: every bench/corpus/BC-*.json must reference a real test.

Pre-fix, corpus rows could carry stale ``documented_in`` strings that
named nonexistent tests; nothing failed when a test was renamed or
deleted. This parametrised test walks every in-scope corpus file and
asserts the referenced test resolves to a real class or function in the
named test file.

Resolver tolerates the human-readable patterns used in the existing corpus:

* Parenthetical annotations -- ``TestKillSwitchScan (inner-empty cases)``
  or ``TestX (8 tests covering A + B + C)``. All ``(...)`` sub-strings
  are stripped before splitting on separators (otherwise a ``+`` inside
  the annotation would split a single ref into garbage fragments).
* Combo refs joined by ``+``, ``;``, or the literal word ``plus`` --
  ``TestA + tests/test_b.py::TestB``. Each segment is tried
  independently; at least one must resolve.

BC-OOS-* rows are excluded -- they document out-of-scope bypasses for
the threat model and intentionally have no harness-side regression test.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._corpus_ref_resolver import _resolve_test_ref

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "bench" / "corpus"


class TestCorpusDocumentedIn:
    """BC-034: every bench/corpus/BC-*.json must point at a real test."""

    @pytest.mark.parametrize(
        "corpus_path",
        sorted(p for p in CORPUS_DIR.glob("BC-*.json") if "OOS" not in p.name),
        ids=lambda p: p.name,
    )
    def test_documented_in_resolves(self, corpus_path: Path) -> None:
        data = json.loads(corpus_path.read_text(encoding="utf-8"))
        ref = data.get("documented_in") or data.get("regression_test")
        assert ref, f"{corpus_path.name}: missing documented_in/regression_test"
        assert _resolve_test_ref(ref, REPO_ROOT), (
            f"{corpus_path.name}: {ref!r} does not resolve to a real test"
        )
