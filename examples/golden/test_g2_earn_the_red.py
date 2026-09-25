"""GOLDEN #2 — Earn-the-red discrimination.

WHY GOLDEN: a passing test proves nothing until you have watched it FAIL on the
bug it is supposed to catch. This test was confirmed RED before the fix and GREEN
after — that is what makes it a gate, not decoration.

GUARDS: FAILURE_MODES §11.11 (earn-the-red is necessary, not sufficient).

ADAPT IT: write the test, then BREAK the code it covers (the mutation noted
below) and run it — if it stays green, the test is decoration. Revert, confirm
green, ship.

MUTATION THAT REDS THIS: change the body of `discount` to `return price` (drop
the discount) — `test_discount_applies` then fails. Revert to re-green.
"""


def discount(price, rate):
    return price * (1 - rate)


def test_discount_applies():
    # Reds if the discount is dropped (see MUTATION THAT REDS THIS above).
    assert discount(100, 0.1) == 90
