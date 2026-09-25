"""docs/QUICKSTART.md deploy counts must match live inventory.

The QUICKSTART "deploys X / Y / Z" prose has a history of drift — pre-TP-99
the file said 4 / 10 / 4 and listed agents that had already moved tiers.
This contract derives the live numbers from the package SoT
(``espalier.asset_inventory.get_packaged_surface`` via
``tests._surface_expected.live_surface_counts``) and asserts QUICKSTART.md
matches.

The harness-dev deploy tier was retired — every consumer now gets the full
surface — so there is a single deploy-count line, no "common tier deploys
..." vs "harness-developer-only subset is omitted ..." split to keep in
sync.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._surface_expected import live_surface_counts

REPO_ROOT = Path(__file__).resolve().parent.parent
QUICKSTART = REPO_ROOT / "docs" / "QUICKSTART.md"

# Captures the three numbers in "X / Y / Z (agents / commands / skills)".
# Anchored on the "(agents / commands / skills)" suffix rather than the verb
# "deploys" so prose wording can vary; QUICKSTART wraps lines for readability,
# so the phrase may span a line break — search with DOTALL to tolerate.
_DEPLOY_COUNT_RE = re.compile(
    r"(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s+"
    r"\(agents\s*/\s*commands\s*/\s*skills\)",
    re.DOTALL,
)


@pytest.fixture(scope="module")
def quickstart_text() -> str:
    assert QUICKSTART.exists(), f"docs/QUICKSTART.md missing at {QUICKSTART}"
    return QUICKSTART.read_text(encoding="utf-8")


class TestQuickstartCounts:
    """The "deploys X / Y / Z" line in QUICKSTART must match the live
    inventory derived from the package SoT.
    """

    def test_count_matches_live_inventory(self, quickstart_text: str):
        match = _DEPLOY_COUNT_RE.search(quickstart_text)
        assert match is not None, (
            "docs/QUICKSTART.md must contain the line "
            '"deploys X / Y / Z (agents / commands / skills)" '
            "— this is the contract surface the parity test binds."
        )
        documented = tuple(int(g) for g in match.groups())
        assert documented == live_surface_counts(), (
            f"QUICKSTART.md says {documented} (agents/commands/skills) "
            f"but live inventory derives {live_surface_counts()}. Update "
            f"docs/QUICKSTART.md to match the packaged surface."
        )
