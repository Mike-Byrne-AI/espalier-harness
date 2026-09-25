"""Known-NEGATIVE theater fixtures -- clean-but-tempting constructs.

Companion to test_convergence_theater_positives.py. Where the positives
fixture exhibits one theater shape per function, this fixture exhibits
the CLEAN twin of each shape: the same surface silhouette, defanged so
the scanner must stay silent. The contract test
`test_does_not_trip_on_negatives` asserts the scanner reports ZERO
findings here -- proving the green is non-vacuous (the scanner stays
silent on near-boundary clean input, not because it is dead).

DO NOT add real assertions here; these are fixtures only. Functions
deliberately lack the `test_` prefix so pytest collection skips them.
"""

# Normal scanner runs skip this file via EXEMPT_PREFIXES = ("tests/fixtures/",).
# The contract test DIRECT-CALLs ct._scan_file on this path (immune to
# live-tree drift), so these shapes are walked even with EXEMPT_PREFIXES on.

# precision-boundary: a same-call comparison whose callable is stateful (a fresh
# read on each side genuinely differs) — probable theater but not certain;
# SUSPECT, never hard THEATER.


def clean_independent_witnesses(producer_a, producer_b) -> None:
    # Twin of theater_same_call: two DIFFERENT producers, not f(x) == f(x).
    assert len(producer_a.items()) == len(producer_b.items())


def clean_floor_contract(agents) -> None:
    # Twin of derived-constant: `>=` is an asymmetric floor contract, not
    # `==` parity. Only `==` is theater shape (TP-137 §B).
    EXPECTED_AGENT_COUNT_MIN = 3  # noqa: F841 -- fixture local
    assert len(agents) >= EXPECTED_AGENT_COUNT_MIN


def clean_distinct_attributes(obj) -> None:
    # Twin of same-attribute: two DIFFERENT attribute chains.
    assert obj.foo.bar == obj.foo.baz


def clean_distinct_literals() -> None:
    # Twin of literal-pair: two distinct literals, a real comparison.
    assert 1 == 2 - 1


def clean_approx_against_other(value, other) -> None:
    # Twin of approx-self: approx tolerance against a DIFFERENT operand, in
    # both operand orders (the reversed arm landed with DEF-410l).
    import pytest
    assert value == pytest.approx(other)
    assert pytest.approx(other) == value


def clean_assertequal_distinct(obj) -> None:
    # Twin of assertEqual-self: two distinct operands.
    obj.assertEqual(1, 2 - 1)


def clean_assertequal_distinct_calls(obj, items, others) -> None:
    # Twin of assertEqual-same-call: same callable, DIFFERENT args.
    obj.assertEqual(len(items), len(others))


def clean_pragma_with_reason() -> None:
    # Twin of literal-pair, but exempted by a pragma WITH a >=12-char reason.
    # theater: ok intentional sanity baseline for the parser smoke path
    assert 1 == 1


def clean_non_equality_comparison(left, right) -> None:
    # Twin of same-call, but `!=` / `<` are not parity shapes.
    assert len(left) != len(right)


def clean_same_call_inequality(items) -> None:
    # Identical call on both sides, but `<=` ceiling contract -- not `==`.
    assert len(items) <= len(items) + 1
