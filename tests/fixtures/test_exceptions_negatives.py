"""Known-negative exceptions scanner fixtures (must-NOT-trip corpus).

Each function is a clean-but-tempting variant of a shape the `exceptions`
scanner flags in the positives corpus, defanged so the scanner must report
ZERO findings. The contract test at
`tests/test_scanner_exceptions.py::test_does_not_trip_on_negatives`
asserts `scan_file` on this path yields an empty list. This closes the
gap where the harness proves the scanner FIRES but never proves it STAYS
SILENT on clean input (TP-156 Tier 1).

DO NOT add real assertions here; these are fixtures only. Functions
deliberately lack the `test_` prefix so pytest collection skips them.
Normal scanner runs skip this file via the scanner's
`EXEMPT_PREFIXES = ("tests/fixtures/",)`; the negatives test bypasses
that filter by calling `scan_file` directly with this path.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def shape_broad_reraise() -> None:
    """Broad catch is clean: it re-raises (has_raise)."""
    try:
        1 / 0
    except Exception:
        raise


def shape_broad_logs_then_swallows() -> None:
    """Broad catch is clean: it logs via a logger call (has_log)."""
    try:
        1 / 0
    except Exception:
        logger.error("division failed")


def shape_broad_log_exception() -> None:
    """Broad catch is clean: logger.exception counts as logging."""
    try:
        1 / 0
    except BaseException:
        logger.exception("unexpected failure")


def shape_bare_reraise_wrapped() -> None:
    """Bare except is clean when it re-raises a wrapped error."""
    try:
        1 / 0
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("wrapped") from exc


def shape_specific_silent_ok() -> None:
    """A SILENT pass is clean when the handler is a SPECIFIC, narrow
    exception type (not <bare>/Exception/BaseException). The scanner only
    flags silent-swallow on any type, but a specific catch that logs is
    doubly clean."""
    try:
        1 / 0
    except ZeroDivisionError:
        logger.warning("expected division-by-zero, continuing")


def shape_specific_print_only_ok() -> None:
    """print-only is flagged ONLY for broad handlers. A specific handler
    that prints is clean (narrow type, not broad)."""
    try:
        1 / 0
    except ValueError:
        print("bad value, recovering")


def shape_specific_logs_not_pass() -> None:
    """A narrow handler is clean as long as the body is not a bare pass
    (any bare-pass body trips swallowed_silent regardless of type). This
    one logs, so it stays silent for the scanner."""
    try:
        1 / 0
    except KeyError:
        logger.info("key absent, using default")


def shape_broad_print_and_log() -> None:
    """Broad catch with BOTH print and log is clean (has_log wins)."""
    try:
        1 / 0
    except Exception:
        print("diagnostic")
        logger.error("handled broadly")


# precision-boundary: a logging-method name (.error / .info / .warning) on a
# NON-logger receiver — the method name alone is not a logging call without a
# logger-plausible receiver; the old receiver-blind check cleared these.


def shape_broad_logs_via_self_logger() -> None:
    """Broad catch is clean: it logs via self.logger (a logger-plausible
    receiver). The receiver tighten must keep this CLEAN."""
    class _C:
        logger = logging.getLogger(__name__)

        def m(self) -> None:
            try:
                1 / 0
            except Exception:
                self.logger.error("handled")


def shape_broad_logs_via_module_logging() -> None:
    """Broad catch is clean: `logging.warning(...)` is a logger call."""
    try:
        1 / 0
    except Exception:
        logging.warning("handled at module level")
