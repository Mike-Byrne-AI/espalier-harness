"""Known-positive exceptions scanner fixtures.

Each function intentionally exhibits ONE shape the `exceptions` scanner
is documented to detect. The contract test at
`tests/test_scanner_exceptions.py::test_earn_the_gate_detects_every_fixture_shape`
asserts every documented `kind` surfaces. This is the "earn the gate"
validation (TP-105 / FM-7 §1.7 close).

DO NOT add real assertions here; these are fixtures only. Functions
deliberately lack the `test_` prefix so pytest collection skips them.
Normal scanner runs skip this file via the scanner's
`EXEMPT_PREFIXES = ("tests/fixtures/",)`; the earn-the-gate test
bypasses that filter by calling `scan_file` directly with this path.
"""
from __future__ import annotations


def shape_swallowed_silent() -> None:
    try:
        1 / 0
    except ZeroDivisionError:
        pass  # expected kind: swallowed_silent


def shape_swallowed_broad_no_log() -> None:
    try:
        1 / 0
    except Exception:
        value = 42  # expected kind: swallowed_broad_no_log
        del value


def shape_swallowed_broad_print_only() -> None:
    try:
        1 / 0
    except Exception:
        print("oops")  # expected kind: swallowed_broad_print_only


def shape_broad_swallow_via_nonlogger_error() -> None:
    """TP-217b: a broad handler whose only body is `obj.error()` is NOT logging
    (non-logger receiver) — it is a real swallow and MUST be flagged. The old
    receiver-blind _is_logger_call cleared this as has_log=True."""
    response = object()
    try:
        1 / 0
    except Exception:  # expected kind: swallowed_broad_no_log (non-logger receiver)
        response.error()


def shape_broad_tuple_swallow() -> None:
    """TP-217b: a broad TUPLE handler (Exception as a member) with a non-pass,
    non-logging body is a real swallow and MUST be flagged. The old string-set
    gate unparsed the tuple to '(ValueError, Exception)' and missed it."""
    try:
        1 / 0
    except (ValueError, Exception):  # expected kind: swallowed_broad_no_log
        value = 1  # not pass, not logging
        del value
