"""Host-agnostic engine-integrity seed test for the ``espalier selfcheck`` channel.

This is the first entry of the curated, host-agnostic engine-integrity set that
``espalier selfcheck`` runs against the INSTALLED engine. It asserts the engine
is importable and exposes a real public symbol — a genuine, non-tautological
check that the bundled mirror is wired and the engine resolves. The curated set
grows to the full host-agnostic suite; the channel only requires that one real
test ships here and runs green from the mirror.

Canonical home: this file lives in ``tests/`` (dev pytest collects it). A
byte-identical mirror under ``espalier/_vendor/selfcheck_tests/`` travels with
the engine; ``scripts/sync_selfcheck_tests.py`` keeps the two in lockstep and
``tests/test_selfcheck_tests_parity.py`` reds if they drift.
"""
from __future__ import annotations


def test_engine_imports():
    from espalier import analyze

    assert callable(analyze.fingerprint_repo)
