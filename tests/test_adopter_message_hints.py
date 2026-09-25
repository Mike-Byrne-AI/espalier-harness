"""TP-193 R4: pin adopter-facing message hints so they do not misdirect.

These guard against two first-run friction regressions:
- The protected-zone deny message must tell an adopter whose OWN source collides
  with a harness path (e.g. a top-level `cc/`) to RELOCATE it, because relaunching
  in maintenance mode (the old advice) is the wrong remedy for adopter code.
- The doctor / session_start ruff install hint must lead with the adopter-correct
  standalone install, not espalier's own source-checkout `.[dev]` extras.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))
import _denial_reasons  # noqa: E402

from espalier.doctor import _LOAD_BEARING_EXTERNAL_TOOLS  # noqa: E402


def test_protected_zone_deny_offers_relocate_for_adopter_collision():
    msg = _denial_reasons.PROTECTED_ZONE_WRITE
    assert "relocate" in msg.lower(), (
        "deny message gives no relocate remedy for an adopter's own cc/ "
        "collision:\n" + msg
    )
    assert "cc/" in msg  # the remedy is anchored to a colliding adopter dir


def test_doctor_ruff_hint_leads_with_standalone_install():
    hint = _LOAD_BEARING_EXTERNAL_TOOLS["ruff"]
    assert hint.startswith("pip install 'ruff"), (
        "doctor ruff hint must lead with the adopter standalone install, not "
        "espalier's `.[dev]`:\n" + hint
    )
    # `.[dev]` may remain as a labelled source-checkout secondary, but AFTER.
    assert hint.index("ruff>=") < hint.index(".[dev]"), hint


def test_session_start_ruff_hint_is_adopter_standalone():
    text = (HOOKS_DIR / "session_start.py").read_text(encoding="utf-8")
    m = re.search(r'\("ruff",\s*"([^"]+)"\)', text)
    assert m, "ruff hint tuple not found in session_start.py"
    assert "ruff>=" in m.group(1) and ".[dev]" not in m.group(1), m.group(1)
