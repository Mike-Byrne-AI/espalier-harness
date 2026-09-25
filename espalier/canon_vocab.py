"""Controlled vocabulary of ``docs/FAILURE_MODES.md`` coinages (named units).

The §1 "named coinages in this catalog (…) are" enumeration is the closed,
authoritative set of in-house failure-mode unit names. This module is the
single importable source for parsing that list, so every consumer reads it the
same way:

- ``tests/test_catalog_self_consistency.py`` cross-checks the prose list
  against the §1 headings (it owns the *headings* derivation; this module owns
  the *prose* derivation — two independent witnesses, not one).
- A fan-out finding's ``named_unit`` (see :mod:`espalier.fan_out_findings`) can
  be validated against this closed set so the aggregator can route by unit.

Scope is §1 by design: §10.8's "enumeration-shadow leak" is a deliberately
catalog-internal coinage *outside* the §1 set (the §1 enumeration prose notes
the exclusion), so it is intentionally NOT parsed here and a finding naming it
is reported as an unknown named_unit rather than routed.

Stdlib-only; the parser mirrors the historical regex + normalization exactly so
the extraction is behavior-preserving.
"""
from __future__ import annotations

import re
from pathlib import Path

# Matches the §1 enumeration prose: "...named coinages in this catalog
# (convergence theater, stealth contracts, ...) are NOT industry-standard...".
_COINAGE_RE = re.compile(
    r"named coinages in this catalog \((.+?)\) are", re.DOTALL
)


def failure_mode_coinages(text: str) -> list[str]:
    """Normalized coinage names parsed from FAILURE_MODES.md prose.

    Whitespace is collapsed and the name lowercased (the historical
    normalization). Raises ``ValueError`` if the enumeration prose is absent.
    """
    m = _COINAGE_RE.search(text)
    if not m:
        raise ValueError("could not find the coinage-enumeration prose")
    return [
        re.sub(r"\s+", " ", c).strip().lower() for c in m.group(1).split(",")
    ]


def load_failure_mode_coinages(repo_root: Path | None = None) -> tuple[str, ...]:
    """Read this repo's ``docs/FAILURE_MODES.md`` and return the coinage tuple.

    Self-host convenience over :func:`failure_mode_coinages`. Adopters whose
    catalog lives elsewhere should call ``failure_mode_coinages(text)`` with
    their own document text instead.
    """
    root = repo_root or Path(__file__).resolve().parent.parent
    text = (root / "docs" / "FAILURE_MODES.md").read_text(encoding="utf-8")
    return tuple(failure_mode_coinages(text))
