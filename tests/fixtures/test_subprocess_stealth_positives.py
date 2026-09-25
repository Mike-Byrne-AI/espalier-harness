"""Earn-the-gate fixture for ``espalier.scanners.subprocess_contracts``.

Each function below uses a subprocess shape the scanner is expected to
flag as either UNPINNED or UNRESOLVED. Real production code routes
through wrappers and contracts; this file's job is to be the corpus
the scanner proves it can see. Without these positives, a regression
that quietly disables a detection branch would leave the scanner
returning "clean" against a clean repo with no failing test.

The earn-the-gate test in tests/test_scanner_subprocess_contracts.py
monkeypatches EXEMPT_PREFIXES to () so the fixture under
tests/fixtures/ is walked and each shape is asserted to produce at
least one finding.

Discoverability: prefixed `test_` so `pathlib.Path.rglob('test_*.py')`
(the convention pytest's collector uses internally) collects this
file. Without the prefix the fixture would be invisible — TP-138
learned this the hard way. The file contains no `def test_*`
functions; pytest collects no tests from it. The shapes are referenced
only by the scanner under test.
"""
from __future__ import annotations

import os
import subprocess


def theater_subprocess_run() -> None:
    subprocess.run(["espalier", "memory", "prune", "--rows", "200"])


def theater_subprocess_check_output() -> None:
    subprocess.check_output(["python", "tools/cc/cognitive_blueprint.py", "finalize"])


def theater_subprocess_popen() -> None:
    proc = subprocess.Popen(["python", "tools/cc/cognitive_blueprint.py", "justify"])
    proc.wait()


def theater_subprocess_popen_communicate() -> None:
    subprocess.Popen(["espalier", "memory", "prune", "--rows", "300"]).communicate()


def theater_os_system() -> None:
    os.system("espalier audit .")


def theater_os_popen() -> None:
    os.popen("espalier scan --magic-depth")


def theater_shell_true_string() -> None:
    subprocess.run("espalier audit .", shell=True)


def theater_dynamic_argv() -> None:
    cmd = ["espalier", "memory", "prune"]
    cmd.append("--rows")
    subprocess.run(cmd)
