"""TP-111: pin espalier-side surface_contract cc/ paths to match
tools/cc/_paths.py.

Two independent witnesses (tools/cc/_paths.py + espalier/surface_contract.py)
declare the cc/ path set. The zero-espalier-imports rule for tools/cc/
forbids surface_contract from importing _paths, so this test enforces
the cross-witness agreement without crossing the layer boundary.

Pins:
- _REQUIRED_INIT_FILES (tuple equality) == CC_MANAGED_DOCS
- BLUEPRINTS_DIR_REL + "/" (membership) in _LOCAL_ONLY_PREFIXES
- SURFACE_HANDOFF_REL (membership) in _LOCAL_ONLY_PATHS

Drift in either direction fires. Catches the failure mode where a
new cc/ path is added on one side but not the other — silent enforcement
gap until something breaks at runtime.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools" / "cc"))

import _paths  # noqa: E402
from espalier.surface_contract import (  # noqa: E402
    _LOCAL_ONLY_PATHS,
    _LOCAL_ONLY_PREFIXES,
    _REQUIRED_INIT_FILES,
)


def test_required_init_files_matches_cc_managed_docs():
    assert _REQUIRED_INIT_FILES == _paths.CC_MANAGED_DOCS, (
        "_paths.CC_MANAGED_DOCS drifted from surface_contract."
        "_REQUIRED_INIT_FILES — both tuples must list the same cc/ "
        "managed docs in the same order."
    )


def test_blueprints_prefix_in_local_only_prefixes():
    expected = _paths.BLUEPRINTS_DIR_REL + "/"
    assert expected in _LOCAL_ONLY_PREFIXES, (
        f"{expected!r} missing from surface_contract._LOCAL_ONLY_PREFIXES; "
        f"the engine-side mirror has drifted from tools/cc/_paths.py."
    )


def test_surface_handoff_in_local_only_paths():
    assert _paths.SURFACE_HANDOFF_REL in _LOCAL_ONLY_PATHS, (
        f"{_paths.SURFACE_HANDOFF_REL!r} missing from "
        f"surface_contract._LOCAL_ONLY_PATHS; engine-side mirror drifted."
    )


def test_required_surface_registry_matches_the_required_init_files():
    """``render_surface.REQUIRED_SURFACE_RENDERERS`` decides what
    ``write_required_surface`` writes; the roster the deploy contract, the
    manifest and ``_paths`` agree on must be the same three docs (a fourth
    witness to the set, found by the lane's failure-mode review)."""
    from espalier.render_surface import REQUIRED_SURFACE_RENDERERS
    from espalier.surface_contract import get_required_init_files

    assert set(REQUIRED_SURFACE_RENDERERS) == set(get_required_init_files())
