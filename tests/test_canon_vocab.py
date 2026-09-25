"""Contract for espalier.canon_vocab — the FAILURE_MODES coinage parser.

This test pins the helper's own behavior (parse / normalize / load / error) so
the coinage-vocabulary extraction cannot drift when the parser is refactored —
it guards the named_unit validation surface that consumes it. The cross-check
that the prose list equals the §1 headings is owned by
tests/test_catalog_self_consistency.py, which consumes this helper as one of
its two independent witnesses — that separation is intentional, not duplicated
here.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from espalier.canon_vocab import failure_mode_coinages, load_failure_mode_coinages

REPO_ROOT = Path(__file__).resolve().parents[1]
FAILURE_MODES = REPO_ROOT / "docs" / "FAILURE_MODES.md"


def _doc_text() -> str:
    return FAILURE_MODES.read_text(encoding="utf-8")


def test_parses_known_anchor_coinages():
    coinages = failure_mode_coinages(_doc_text())
    # Flagship named units that must be in the closed set.
    assert "convergence theater" in coinages
    assert "stealth contracts" in coinages


def test_names_are_normalized():
    coinages = failure_mode_coinages(_doc_text())
    assert coinages, "expected a non-empty coinage list"
    for name in coinages:
        assert name == name.strip().lower(), f"not normalized: {name!r}"
        assert name, "empty coinage entry"
        assert "  " not in name, f"whitespace not collapsed: {name!r}"


def test_raises_when_prose_absent():
    with pytest.raises(ValueError, match="coinage-enumeration prose"):
        failure_mode_coinages("a document with no enumeration sentence")


def test_load_wrapper_matches_direct_parse():
    assert load_failure_mode_coinages(REPO_ROOT) == tuple(
        failure_mode_coinages(_doc_text())
    )


def test_load_wrapper_defaults_to_repo_root():
    # No explicit root -> resolves this repo's docs/FAILURE_MODES.md.
    assert "convergence theater" in load_failure_mode_coinages()
