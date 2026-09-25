"""Worked example: a StringContract consumer.

Pins one canonical greeting string across two prose surfaces. Adopters
copy this shape for their own canonical-string parity needs (event
names, schema versions, denial reasons, etc.). The dataclass primitives
and ``OPT_OUT_MARKER_RE`` grammar live in ``tests/_contracts.py``;
the per-rule chip-down lives in ``tests/_surface_expected.py``.

This file is dogfooding reference, not a runtime test in the adopter's
suite. Run via ``pytest examples/dogfooding/contracts/`` from the
repo root.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# tests/ is pruned from the published sdist; this dogfooding-reference test
# then can't import its primitives. Skip cleanly there instead of erroring at
# collection.
_contracts = pytest.importorskip("tests._contracts")
StringContract = _contracts.StringContract
extract_matches = _contracts.extract_matches

# A REAL worked example reads its NAMED source, not a synthetic fixture it
# writes itself. The README in this directory names `StringContract` exactly
# once (the canonical primitive an adopter author references); we pin that the
# string is present in the real on-disk file. This is the shape an adopter
# copies: name a concrete (relpath, regex) pair against a committed file and
# assert the canonical value is the only thing the pattern extracts.
_REPO_ROOT = Path(__file__).resolve().parents[3]

EXAMPLE_CONTRACT = StringContract(
    name="example-canonical-primitive",
    expected_value="StringContract",
    sources=(
        ("examples/dogfooding/contracts/README.md", r"\b(StringContract)\b"),
    ),
)


@pytest.mark.parametrize("relpath,pattern", EXAMPLE_CONTRACT.sources)
def test_example_canonical_string_matches_real_source(relpath, pattern):
    """Worked example: extract the canonical string from the REAL named source
    and assert parity. Unlike a synthetic-fixture test, this goes RED if the
    README ever stops naming `StringContract` — which is the actual drift an
    adopter's own consumer would need to catch."""
    source = _REPO_ROOT / relpath
    assert source.exists(), f"named source missing: {relpath}"
    matches = extract_matches(source, pattern)
    assert len(matches) >= 1, (
        f"vacuous-pass guard: no match for {pattern} in {relpath} — a real "
        f"worked example must extract its canonical value from its named source"
    )
    assert all(m == EXAMPLE_CONTRACT.expected_value for m in matches)
