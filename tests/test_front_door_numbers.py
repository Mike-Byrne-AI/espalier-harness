"""The stated Python floor must be the packaging floor, on every front-door surface.

DELIBERATELY NARROW, and the narrowing is the point. This module was drafted as a
general "front-door numeric claims" contract covering agent / command / skill / hook
counts and the ESPALIER_MEMORY.md line cap -- and then the suite pointed out that
``tests/test_documented_claims.py::NUMERIC_CONTRACTS`` already IS that mechanism:
multi-surface, sourced from ``_surface_expected``, and already refusing to pass when a
claim stops matching. Building a second one would have been the parallel-inventory
hazard this repo documents, with the two drifting against each other exactly the way
prose drifts against both. Those claims now live there as added SOURCES on the existing
rows (plus two new rows for the counts that had no contract at all: governance agents,
and hook helper modules).

What could NOT fold in is this: ``NumericContract`` compares a single captured integer
against an ``int``. A Python floor is a dotted version derived from ``requires-python``,
so it needs its own comparison. One test, for the one claim the neighbour cannot hold.

The defect that motivated it was live on the front door: the install section said
``Python 3.11+`` while ``requires-python`` was ``>=3.10`` and the Requirements section
forty lines from the bottom said ``3.10+``. A reader on 3.10 met "you are unsupported"
in the first paragraph and "you are supported" at the end. Both were prose; only one
could be right; neither was checked.
"""
# slow-exempt: no subprocess -- reads pyproject.toml and three docs, pure text work.
# pytest-marker: default-unit
from __future__ import annotations

import re
from pathlib import Path

from espalier._compat import tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Surfaces a stranger reads before installing. A doc absent from the tree is skipped
#: rather than failing: this is a claim-consistency gate, not a file-presence gate.
_FRONT_DOOR = ("README.md", "docs/QUICKSTART.md", "CONTRIBUTING.md")

_STATED_FLOOR_RE = re.compile(r"Python (\d+\.\d+)\+")


def _packaging_floor() -> str:
    """The minimum supported Python, from ``requires-python`` -- the metadata that
    actually decides whether an install succeeds, which is what makes it the SoT
    rather than one more opinion."""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requires = data["project"]["requires-python"]
    m = re.search(r">=\s*(\d+\.\d+)", requires)
    assert m, f"requires-python {requires!r} has no `>=X.Y` floor to derive from"
    return m.group(1)


def test_every_stated_python_floor_matches_requires_python():
    floor = _packaging_floor()
    stated = 0
    failures: list[str] = []
    for doc in _FRONT_DOOR:
        path = REPO_ROOT / doc
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for m in _STATED_FLOOR_RE.finditer(text):
            stated += 1
            if m.group(1) != floor:
                line = text[: m.start()].count("\n") + 1
                failures.append(f"{doc}:{line} says Python {m.group(1)}+")
    assert stated > 0, (
        "no `Python X.Y+` claim found anywhere on the front door. Either the phrasing "
        "changed (update the pattern in the same commit) or the claim was dropped — "
        "and a gate whose population went to zero reports success while checking "
        "nothing, which is the failure this assertion exists to prevent."
    )
    assert not failures, (
        f"pyproject requires-python declares a floor of {floor}, but the front door "
        f"states a different one:\n  " + "\n  ".join(failures) + "\n"
        "Correct the prose, or change requires-python — but they must agree, because "
        "only one of them decides whether `pip install` succeeds."
    )
