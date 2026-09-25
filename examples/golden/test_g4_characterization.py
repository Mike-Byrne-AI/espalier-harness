"""GOLDEN #4 — Characterization test (regression net, NOT a correctness proof).

WHY GOLDEN: before refactoring code you do not fully understand, pin its CURRENT
behavior — whatever it is, bugs and surprises included — so a refactor that
changes behavior reds. This is honest scaffolding: it does not claim the behavior
is right, only that it is unchanged.

GUARDS: the "characterize before you refactor" discipline `espalier strengthen`
suggests for an untested existing repo. Explicitly NOT a §13.5 earn-the-gate —
it asserts current output, not desired output.

ADAPT IT: run the legacy function on representative inputs, paste the OBSERVED
outputs into the assertions, and label them observed-not-desired. Delete/replace
the characterization once real correctness tests exist.

NOTE: `round()` uses banker's rounding (round-half-to-even), so round(0.5)==0 and
round(2.5)==2. Surprising, but that IS the current behavior this test locks in.
"""


def legacy_round(x):  # existing code; behavior characterized, not endorsed
    return round(x)


def test_characterizes_current_rounding():
    # OBSERVED outputs (banker's rounding), not the outputs you might expect.
    assert legacy_round(0.5) == 0
    assert legacy_round(1.5) == 2
    assert legacy_round(2.5) == 2
