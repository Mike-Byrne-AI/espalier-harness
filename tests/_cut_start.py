"""One reader for a SessionStart script start cut at its wall (DEF-2048).

Run as a script, ``tools/cc/hooks/session_start.py`` cuts itself at a 13 s
wall from module load and prints a short banner naming the phase in flight
(``session_start._cut_banner``), since Claude Code drops the whole banner past
its 15 s timeout. On a loaded runner a test's driven start can cross that wall
(#456's windows-latest leg: cut at 13.0 s in the banner build, ten errors in
one file), and a row that judges what a full start prints then reads the
hook's designed answer as a failure, or an absence assertion passes on a
banner that never got that far. Either way the row could not tell.

So each driven-start helper in DEF-2048's census files hands the hook's
stdout (or its banner) to ``skip_if_cut`` before it asserts what only a full
start shows (a row a cut start still answers, its rc or another hook's import
errors, asserts that first): a cut start skips, naming the phase and the
seconds, and a full start returns. The opening is calibrated
against the hook's own short form in
``tests/test_quickstart_doctor_example.py::TestTheCutOpeningReadsAsCannotTell``,
so a rewording reds there, never as a skip. ``tests/test_session_start_wall.py``
judges the cut itself and its no-stall row the full banner at the real wall;
it never reads through here.
"""
from __future__ import annotations

import re

import pytest

#: The opening of the short banner a script start cut at its wall gives.
CUT_OPEN_RE = re.compile(
    r"=== Espalier-Harness === SessionStart \(short: cut at (?P<seconds>\d+(?:\.\d+)?) s in the (?P<phase>[^;]+);")


def skip_if_cut(output: str) -> None:
    """A driven start cut at its wall is cannot-tell, never a verdict: skip,
    naming the phase and the seconds, when ``output`` (the hook's stdout or
    its banner) is a cut start's; a full start returns."""
    cut = CUT_OPEN_RE.search(output)
    if cut:
        pytest.skip(f"cannot tell: the driven start was cut at {cut['seconds']} s in the "
                    f"{cut['phase']} and printed the short banner; only a full start judges this row")
