"""Closed-loop verification registry.

Each entry pins a (producer, consumer-test) pair where the consumer
reads producer output at runtime. The registry's contract: each
consumer-test file MUST contain a parity-test function that drives
the consumer with REAL producer output (typically via the
``initialized_repo_root`` fixture).

Adding a producer/consumer relationship to the codebase requires
registering it here. Removing this discipline at the registry level
costs ~1 line per pair; failing to register lets the closed-loop
trap recur (TP-74 / BC-041 / BC-041b precedent).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProducerConsumerPair:
    """Pin a (producer, consumer-test) parity-test contract.

    The ``parity_test`` field names the test FUNCTION (not file) that
    must exist in ``consumer_test_path``. Convention: parity tests
    are named ``test_<consumer>_with_real_producer_output`` so they
    are discoverable + greppable.
    """

    name: str                    # human-readable label
    producer_module: str         # e.g. "espalier.analyze"
    producer_function: str       # e.g. "detect_tests"
    consumer_module: str         # e.g. "tools.cc.hooks.stop_gate"
    consumer_function: str       # e.g. "_resolve_core_tests"
    consumer_test_path: str      # e.g. "tests/test_stop_gate.py"
    parity_test: str             # e.g. "test_resolves_from_real_fingerprint_output"


CLOSED_LOOP_REGISTRY: tuple[ProducerConsumerPair, ...] = (
    # The TP-74 / BC-041 / BC-041b case -- the canonical precedent.
    ProducerConsumerPair(
        name="stop_gate Gate-1 vs analyze.detect_tests fingerprint",
        producer_module="espalier.analyze",
        producer_function="detect_tests",
        consumer_module="tools.cc.hooks.stop_gate",
        consumer_function="_resolve_core_tests",
        consumer_test_path="tests/test_stop_gate.py",
        parity_test="test_resolves_from_real_fingerprint_output",
    ),
    # Future entries chipped up as new producer/consumer
    # relationships emerge. Each addition is review-visible:
    # adding a row forces a parity-test addition.
)
