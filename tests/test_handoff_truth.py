"""Anti-regression: cc/SURFACE_HANDOFF.md must not reference removed commands.

The /recover command was intentionally merged away in an earlier pack;
local-only handoff documentation that points at a phantom command is a
release embarrassment. This test locks the removal in.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _assert_no_removed_recover_refs(text: str) -> None:
    """The two anti-regression assertions, factored so both the real-doc test
    and the synthetic-fixture test exercise identical logic. Pins the removal
    of /recover from handoff documentation."""
    assert "/recover" not in text, (
        "/recover was removed; SURFACE_HANDOFF.md must not reference it"
    )
    assert "commands/recover.md" not in text, (
        "recover.md was removed; SURFACE_HANDOFF.md must not reference it"
    )


def test_surface_handoff_does_not_reference_removed_recover():
    handoff = REPO_ROOT / "cc" / "SURFACE_HANDOFF.md"
    if not handoff.exists():
        pytest.skip(
            # TP-225-F: cc/SURFACE_HANDOFF.md is gitignored (a local-only handoff
            # artifact, never committed), so in CI it is ALWAYS absent and this
            # test ALWAYS skips there — by design, not an accidental skip. There
            # is nothing to regress when the doc is not present. The synthetic-
            # fixture test below exercises the assertion LOGIC unconditionally so
            # the guard is never vacuous even on a clean checkout.
            "SURFACE_HANDOFF.md is local-only (gitignored) and absent here"
        )
    text = handoff.read_text(encoding="utf-8")
    _assert_no_removed_recover_refs(text)


def test_removed_recover_guard_fires_on_synthetic_content():
    """TP-225-F: the real test skips in CI (the doc is gitignored/local-only),
    so without this the /recover-removal guard has ZERO CI coverage and a future
    edit re-introducing the reference would not be caught. This exercises the
    assertion logic on synthetic content unconditionally: clean text passes, and
    each removed-reference spelling raises. Guards the guard against vacuity.
    """
    _assert_no_removed_recover_refs("# Handoff\nUse /handoff and /status.\n")
    with pytest.raises(AssertionError):
        _assert_no_removed_recover_refs("see /recover for details")
    with pytest.raises(AssertionError):
        _assert_no_removed_recover_refs("see commands/recover.md")
