"""Pin the post-TP-64 invariant: matcher is narrow AND dead branches remain.

These three assertions together catch the silent re-engagement failure
mode TP-66 documents: if a future change widens the
.claude/settings.json matcher back to "*" AND deletes the
Bash/PowerShell/MCP dispatch branches in the same commit, the
false-positive surface TP-64 removed would re-engage unannounced.

Each assertion alone is a single-sided protection:
  - test_matcher_remains_narrow fires if the matcher widens (regardless
    of branch state).
  - test_banner_present fires if the banner is removed (drift of doc
    truth from in-code reality).
  - test_dead_branches_still_present fires if the dispatch branches are
    deleted without a coordinated banner/wiring update.

This file is the wiring-invariant contract. The classifier-correctness
unit tests live in tests/test_plan_guard.py.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAN_GUARD_PATH = REPO_ROOT / "tools" / "cc" / "hooks" / "plan_guard.py"

BANNER_SENTINEL = "POST-TP-64 NOTICE"


def test_matcher_remains_narrow():
    from espalier.harness_config import CANONICAL_HOOK_WIRING
    matcher = CANONICAL_HOOK_WIRING["plan_guard.py"]["matcher"]
    assert matcher == "Write|Edit|NotebookEdit", (
        f"plan_guard matcher widened to {matcher!r}; if intentional, "
        f"delete the dead Bash/PowerShell/MCP branches in plan_guard.py "
        f"AND update tests/test_plan_guard_branch_pinned.py to reflect "
        f"the new contract."
    )


def test_banner_present():
    src = PLAN_GUARD_PATH.read_text(encoding="utf-8")
    assert BANNER_SENTINEL in src, (
        f"plan_guard.py is missing the {BANNER_SENTINEL} banner. If you "
        f"removed the dead branches, also remove this test."
    )


def test_dead_branches_still_present():
    src = PLAN_GUARD_PATH.read_text(encoding="utf-8")
    for marker in ('"Bash"', '"PowerShell"', "mcp__"):
        assert marker in src, (
            f"plan_guard.py no longer references {marker}. The dead-branch "
            f"contract assumed retention; if you intentionally deleted, "
            f"also widen the matcher discussion in the banner and delete "
            f"this test."
        )
