"""Known-positive theater fixtures (synthesized from TP-12/74/136 history).

Each function here intentionally exhibits ONE theater shape. The
scanner contract test asserts every function is detected with the
expected shape label. This is the "earn the gate" validation
(TP-105 pattern) -- without it, a future scanner change that silently
breaks detection passes CI.

DO NOT add real assertions here; these are fixtures only. Functions
deliberately lack the `test_` prefix so pytest collection skips them.
"""

# Normal scanner runs skip this file via EXEMPT_PREFIXES = ("tests/fixtures/",).
# The earn-the-gate test monkeypatches BOTH EXEMPT_FILES AND
# EXEMPT_PREFIXES off so the shapes become detectable.


def theater_literal_pair() -> None:
    assert 1 == 1  # expected shape: literal-pair


def theater_same_call(items: list) -> None:
    assert len(items) == len(items)  # expected shape: same-call (SUSPECT after T6)


def suspect_stateful_same_call(it) -> None:
    # same-call shape — SUSPECT (was THEATER); the hedge names the stateful-
    # callable escape hatch: a fresh read on each side genuinely differs (T6).
    assert next(it) == next(it)  # expected shape: same-call (SUSPECT)


def theater_same_attribute(obj) -> None:
    assert obj.foo.bar == obj.foo.bar  # expected shape: same-attribute


def theater_derived_constant(producer) -> None:
    EXPECTED_THING = 5  # noqa: F841 -- fixture local, mirrors real EXPECTED_X shape
    assert len(producer.items()) == EXPECTED_THING  # expected: derived-constant (SUSPECT)


def theater_approx_self(value) -> None:
    import pytest
    assert value == pytest.approx(value)  # expected shape: approx-self
    assert pytest.approx(value) == value  # expected shape: approx-self (reversed operands, DEF-410l)


def theater_assertequal_self(obj) -> None:
    obj.assertEqual(1, 1)  # expected shape: assertEqual-self


def theater_assertequal_same_call(obj, items: list) -> None:
    obj.assertEqual(len(items), len(items))  # expected shape: assertEqual-same-call (SUSPECT)


def valid_independent_witnesses(producer_a, producer_b) -> None:
    # NOT theater -- two independent producers
    assert len(producer_a.items()) == len(producer_b.items())
