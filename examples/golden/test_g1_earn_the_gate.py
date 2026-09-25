"""GOLDEN #1 — Earn-the-gate + a must-not-trip negative corpus.

WHY GOLDEN: a detector is only trustworthy once you've proven BOTH directions —
it flags what it's for (recall) AND stays silent on the near-misses that look
similar (precision). Weak tests assert only the positive; the negative corpus is
what catches the "substring shadow" bug where a naive `"eval(" in line` check
also fires on `primeval(`.

GUARDS: FAILURE_MODES §13.5 (earn-the-gate — the positive fixture proves the
guard actually fires) + §13.9 (complacent oracle — the negative fixture proves
it does not over-fire on a look-alike).

ADAPT IT: for your own detector, add at least one KNOWN-NEGATIVE that a naive
implementation would wrongly flag. If you cannot think of a plausible false
positive, your negative corpus is too easy — the gate is not earned.
"""
import re


def uses_eval(line: str) -> bool:
    # Flag a real eval() call, not the bare substring "eval".
    return re.search(r"\beval\s*\(", line) is not None


# POSITIVE corpus: the detector MUST flag every line (proves recall).
MUST_FLAG = [
    "result = eval(user_input)",
    "  x = eval( expr )",
]

# NEGATIVE corpus: the detector must NOT flag any line (proves precision).
# Each is a plausible false positive for a naive substring check. Only
# `primeval(3)` actually contains `eval(` — the exact "substring shadow" a bare
# `"eval(" in line` trips on; the other two only share the bare `eval` stem.
MUST_NOT_FLAG = [
    "score = evaluate(candidate)",  # 'eval' is a prefix of a longer word
    "self.eval_mode = True",        # 'eval_' is an attribute, not a call
    "primeval(3)",                  # contains 'eval(' but no word boundary
]


def test_detector_flags_every_positive():
    for line in MUST_FLAG:
        assert uses_eval(line), f"recall gap: failed to flag {line!r}"


def test_detector_silent_on_every_negative():
    for line in MUST_NOT_FLAG:
        assert not uses_eval(line), f"false positive: wrongly flagged {line!r}"
