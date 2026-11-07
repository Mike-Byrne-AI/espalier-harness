"""Espalier-Harness — Claude Code governance harness."""
from __future__ import annotations

import sys

# The engine's own floor sentence, before anything else in the package is
# compiled. pip already refuses the package below the floor (`Requires-Python`),
# but a clone kept current by `git pull` never re-reads it, so a host below the
# floor running `python -m espalier` reads the floor here, never a traceback from
# a module that needs a newer interpreter. Every entry runs this file first: the
# `espalier` console script and `python -m espalier` both import the package
# before `espalier.cli`. This file stays parseable on 3.9, stock macOS's
# python3 (its py39 row in pyproject.toml's [tool.ruff]
# per-file-target-version), the check names nothing but `sys`, `_FLOOR` and
# builtins (a call into another module could raise first), and `_FLOOR` is pinned
# equal to `_python_floor.MIN_PYTHON` by tests/test_python_floor.py.
_FLOOR = (3, 11)
if sys.version_info[:2] < _FLOOR:
    raise SystemExit(
        "espalier-harness does not run on Python %d.%d.%d. Update to Python "
        "%d.%d or newer to install and use it." % (tuple(sys.version_info[:3]) + _FLOOR)
    )

__version__ = "0.8.0b2"
