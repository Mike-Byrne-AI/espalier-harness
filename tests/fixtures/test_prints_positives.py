"""Known-positive prints scanner fixtures.

Each function intentionally exhibits a bare `print()` call the `prints`
scanner is documented to detect. The contract test at
`tests/test_scanner_prints.py::test_earn_the_gate_detects_every_fixture_shape`
asserts every call surfaces. This is the "earn the gate" validation
(TP-105 / FM-7 §1.7 close).

The scanner does not discriminate by `file=` kwarg today; verify at
execution time. If discrimination is added in the future, this
fixture's coverage must expand.

DO NOT add real assertions here; these are fixtures only. Functions
deliberately lack the `test_` prefix so pytest collection skips them.
Normal scanner runs skip this file via the scanner's
`EXEMPT_PREFIXES = ("tests/fixtures/",)`.
"""
from __future__ import annotations

import sys


def shape_bare_print() -> None:
    print("bare print call")  # expected: detected


def shape_print_to_stdout() -> None:
    print("explicit stdout", file=sys.stdout)  # expected: detected


def shape_print_to_stderr() -> None:
    print("explicit stderr", file=sys.stderr)  # expected: detected
