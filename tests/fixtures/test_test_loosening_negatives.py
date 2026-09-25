"""Known-negative test_loosening scanner corpus.

Each function here is a *clean-but-tempting* variant of a shape the
`test_loosening` scanner detects: near the boundary, but defanged so the
scanner stays SILENT. The contract test at
`tests/test_scanner_test_loosening.py::test_does_not_trip_on_negatives`
asserts `scan_file` returns ZERO findings for this whole file. This
closes the must-NOT-trip gap: the positives fixture proves the scanner
FIRES; this fixture proves it STAYS SILENT on legitimate constructs.

Filename has the double `test_test_` prefix because the scanner only
walks `test_*.py`, mirroring the positives fixture. The fixture is
exempted from live scans via `EXEMPT_PREFIXES = ("tests/fixtures/",)`;
the negatives test calls `scan_file` directly to bypass that filter.

DO NOT add real assertions here. Functions deliberately lack the
`test_` prefix so pytest collection skips them.

Why each construct is clean (mirrors a positives shape, defanged):
  * assert_tautological — only fires on a provably-tautological test
    expression: a truthy `ast.Constant`, or `Const == Const` that is
    equal. Asserts over *names*/*calls*/*non-equal constant compares*
    are NOT tautological, so the scanner ignores them.
  * bare_skip — only fires on `pytest.skip()` with no args AND no
    `reason=`. A skip WITH a reason (positional or kwarg) is clean.
  * skip_no_reason — only fires on `@pytest.mark.skip` without
    `reason=`. A skip decorator WITH `reason=` is clean.
  * xfail_no_reason — only fires on `@pytest.mark.xfail` without
    `reason=`. An xfail decorator WITH `reason=` is clean.
"""
from __future__ import annotations

import pytest


def shape_assert_real_expression() -> None:
    # Tempting: an `assert` near a tautology, but over a runtime name —
    # NOT a provable constant, so `_is_tautological_assert` returns False.
    value = 1 + 1
    assert value == 2


def shape_assert_non_equal_constants() -> None:
    # Tempting: `Const == Const` compare, but the constants are NOT
    # equal, so `_is_tautological_assert` returns False.
    assert 1 == 1 + 0 and 2 != 3  # noqa: PLR0133 - runtime boolop, not a constant


def shape_assert_call_result() -> None:
    # Tempting: a single-name truthy-looking assert, but the test
    # expression is a Call (not a Constant), so it is not flagged.
    assert bool([1, 2, 3])


def shape_skip_with_reason_kwarg() -> None:
    # Tempting: a `pytest.skip` call, but it carries a `reason=` kwarg,
    # so `bare_skip` does not fire (args/kwarg present).
    pytest.skip(reason="documented: requires network fixture, tracked in TP-xx")


def shape_skip_with_positional_reason() -> None:
    # Tempting: a `pytest.skip` call, but it carries a positional
    # message argument, so `bare_skip` does not fire (node.args truthy).
    pytest.skip("documented: hardware not present in CI")


@pytest.mark.skip(reason="documented: depends on external service; see SHARP_EDGES")
def shape_skip_decorator_with_reason() -> None:
    # Tempting: `@pytest.mark.skip`, but WITH `reason=`, so
    # `skip_no_reason` does not fire.
    return None


@pytest.mark.xfail(reason="documented: known upstream bug, tracked in issue #123")
def shape_xfail_decorator_with_reason() -> None:
    # Tempting: `@pytest.mark.xfail`, but WITH `reason=`, so
    # `xfail_no_reason` does not fire.
    return None


@pytest.mark.skipif(True, reason="documented: only runs on Windows hosts")
def shape_skipif_with_reason() -> None:
    # Tempting: a conditional-skip decorator. The scanner only targets
    # the exact dotted `pytest.mark.skip` / `pytest.mark.xfail`, not
    # `pytest.mark.skipif`, and this one carries `reason=` anyway.
    return None
