"""Known-positive perf_smells scanner fixtures.

Exhibits the GENERAL_PATTERNS the scanner is documented to detect.
Pre-existing scanner limitation discovered during TP-143 143-A:
`nested_loop_pattern` uses regex `for...\\n\\s+for` but scan_file walks
src.splitlines() output (newlines stripped), so the pattern is
structurally unreachable. The earn-the-gate test asserts only the
three patterns that CAN surface in the current scan_file
implementation: subprocess_shell, global_import_star, bare_open. If
the scanner adds multi-line support, the fixture and test should
expand together.

TP-105 / FM-7 §1.7 close. DO NOT add real assertions here.
"""
from __future__ import annotations

from typing import *  # noqa: F401, F403 -- expected pattern: global_import_star

import subprocess


def shape_subprocess_shell() -> None:
    subprocess.run("echo hi", shell=True)  # expected pattern: subprocess_shell


def shape_bare_open() -> None:
    f = open("/tmp/x")  # expected pattern: bare_open (no `with` preceding)
    f.close()
