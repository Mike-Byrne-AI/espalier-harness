"""GOLDEN #3 — Closed-loop producer/consumer parity.

WHY GOLDEN: when a consumer is tested against a HAND-WRITTEN fixture that only
"looks like" what the producer emits, the fixture silently drifts the moment the
producer's format changes — the test stays green while the real pipeline breaks.
Drive the consumer with the producer's ACTUAL output and the loop reds on drift.

GUARDS: CONVENTIONS "Closed-loop verification — producer/consumer parity"; the
BC-041 corpus precedent (a test-shaped fixture that bypasses the real format).

ADAPT IT: never assert against a string you typed by hand when a real producer
can generate it. Feed producer output straight into the consumer.

DRIFT DEMO: the hand fixture "HELLO ada" (missing the trailing '!') parses to
None — a hardcoded-fixture test would need hand-editing every format change; the
closed-loop test below adapts for free.
"""
import re


def render_greeting(name: str) -> str:  # the producer
    return f"HELLO {name}!"


def parse_greeting(s: str):  # the consumer
    m = re.fullmatch(r"HELLO (.+)!", s)
    return m.group(1) if m else None


def test_consumer_parses_real_producer_output():
    # Closed loop: the fixture IS the producer's output, so it cannot drift.
    name = "ada"
    assert parse_greeting(render_greeting(name)) == name
