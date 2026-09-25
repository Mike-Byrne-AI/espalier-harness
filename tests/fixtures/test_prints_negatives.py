"""Known-NEGATIVE prints scanner fixtures (must-NOT-trip corpus).

Each function below is a clean-but-tempting construct: it looks
print-adjacent but contains NO bare `print(...)` call, so the `prints`
scanner is contractually required to report ZERO findings here. The
companion test at
`tests/test_scanner_prints.py::test_does_not_trip_on_negatives`
asserts `scan_file` on this fixture returns an empty list. This closes
the gap where the harness proves the scanner FIRES (positives /
earn-the-gate) but never proves it STAYS SILENT on clean input
(TP-156 Tier 1).

The scanner flags `ast.Call` nodes whose func is a bare `Name` with
id `"print"`. The constructs here deliberately sit near that boundary:
logging instead of printing, `print` referenced as an attribute /
shadowed name / string, and `pprint`-family calls — none of which is a
bare `print(...)` Name call.

DO NOT add real assertions here; these are fixtures only. Functions
deliberately lack the `test_` prefix so pytest collection skips them.
Normal scanner runs skip this file via the scanner's
`EXEMPT_PREFIXES = ("tests/fixtures/",)`.
"""
from __future__ import annotations

import logging
import sys
from pprint import pprint

logger = logging.getLogger(__name__)


def shape_log_instead_of_print() -> None:
    # Tempting: the canonical thing a print() should become. Clean:
    # this is a logging call, not a print() Name call.
    logger.info("structured logging, not a print")


def shape_write_to_stdout() -> None:
    # Tempting: emits to stdout like print does. Clean: it is a method
    # call (Attribute func), not a bare `print` Name call.
    sys.stdout.write("explicit stdout write, no print()\n")


def shape_print_as_attribute() -> None:
    # Tempting: the literal token `print` appears. Clean: `self_print`
    # is an Attribute access, and the scanner only flags func Name "print".
    formatter = _Formatter()
    formatter.print_line("attribute method named print_*")


def shape_print_in_string_literal() -> None:
    # Tempting: the word "print" sits inside source text. Clean: it is
    # a string constant, never a call node.
    message = "remember to print the receipt"
    return message  # type: ignore[return-value]


def shape_shadowed_print_name() -> str:
    # Tempting: a local binding literally named `print`. Clean: it is
    # never *called* — no ast.Call with func Name "print" exists here.
    print = "shadowed-but-uncalled"  # noqa: A001
    return print


def shape_pprint_pretty_printer() -> None:
    # Tempting: `pprint` ends in "print". Clean: func Name id is
    # "pprint", not "print".
    pprint({"clean": True, "scanner": "prints"})


class _Formatter:
    def print_line(self, text: str) -> None:
        # Tempting: a method whose NAME contains "print". Clean: the
        # func here is an Attribute (logger.debug), not a print Name call.
        logger.debug("formatted: %s", text)
