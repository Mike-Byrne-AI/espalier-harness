"""Parity: ``espalier/surface_hygiene.py`` is the single oracle for both the
full-suite ``TestCommonTierAssetHygiene`` contract AND the ``surface-impact``
pre-flight, so the two cannot drift on what counts as a hygiene leak.

If the pre-flight scanned with a different regex than the contract enforces,
a pack could pass ``surface-impact`` clean and still trip the full-suite
hygiene contract (or vice versa) — exactly the pre-flight/full-suite gap this
whole pack exists to close. These tests pin the shared-oracle invariant.

``test_init_tier_split`` is imported as a module alias (not ``from ... import
TestCommonTierAssetHygiene``) so pytest does not re-collect its test class
here.
"""
from __future__ import annotations

import tests.test_init_tier_split as _tit
from espalier import surface_hygiene


class TestSurfaceHygieneParity:
    def test_contract_sources_the_shared_regex(self) -> None:
        # The full-suite hygiene contract must read SPECIFIC_ID_RE from the
        # shared module, not a re-inlined private copy — else the pre-flight
        # and the contract can drift on which IDs leak.
        assert (
            _tit.TestCommonTierAssetHygiene._SPECIFIC_ID_RE
            is surface_hygiene.SPECIFIC_ID_RE
        )

    def test_contract_sources_the_shared_vocab_patterns(self) -> None:
        assert (
            _tit.TestCommonTierAssetHygiene._FORBIDDEN_SELF_HOST_PATTERNS
            is surface_hygiene.FORBIDDEN_SELF_HOST_PATTERNS
        )

    def test_specific_id_regex_pinned(self) -> None:
        # Pin the exact pattern so a careless edit to the shared module reds
        # here (and the pre-flight's content scan changes in lockstep).
        assert surface_hygiene.SPECIFIC_ID_RE.pattern == (
            r"\b(?:TP|TASK_PACK|BC)-[A-Z0-9_-]*\d[A-Z0-9_-]*\b"
        )

    def test_internal_id_hits_flags_specific_ignores_placeholder(self) -> None:
        # A digit-bearing ID leaks; a digit-free placeholder is allowed vocab.
        assert surface_hygiene.internal_id_hits("see TP-71 and BC-035") == [
            "BC-035",
            "TP-71",
        ]
        assert surface_hygiene.internal_id_hits("only TP-NN and BC-NNN") == []

    def test_self_host_vocab_hits_flags_known_vocab(self) -> None:
        assert "THIS harness" in surface_hygiene.self_host_vocab_hits(
            "Use THIS harness to govern"
        )
        assert surface_hygiene.self_host_vocab_hits("a neutral sentence") == []
