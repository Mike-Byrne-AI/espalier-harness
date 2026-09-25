"""Known-positive test_loosening scanner fixtures.

Each function intentionally exhibits ONE rule the `test_loosening`
scanner is documented to detect. The contract test at
`tests/test_scanner_test_loosening.py::test_earn_the_gate_detects_every_fixture_shape`
asserts every documented `rule` (assert_tautological / bare_skip /
skip_no_reason / xfail_no_reason) surfaces. TP-105 / FM-7 §1.7 close.

Filename has the double `test_test_` prefix because the scanner only
walks `test_*.py`, so the fixture itself must match that prefix to be
reachable via `iter_test_files`. The fixture is exempted from live
scans via the scanner's `EXEMPT_PREFIXES = ("tests/fixtures/",)`; the
earn-the-gate test calls `scan_file` directly to bypass that filter.

DO NOT add real assertions here. Functions deliberately lack the
`test_` prefix so pytest collection skips them.
"""
from __future__ import annotations

import pytest


def shape_assert_tautological() -> None:
    assert True  # expected rule: assert_tautological


def shape_bare_skip() -> None:
    pytest.skip()  # expected rule: bare_skip


@pytest.mark.skip
def shape_skip_no_reason() -> None:
    # expected rule: skip_no_reason
    return None


@pytest.mark.xfail
def shape_xfail_no_reason() -> None:
    # expected rule: xfail_no_reason
    return None
