"""TP-05 §4 — integrity manifest vs surface contract parity.

The integrity manifest in ``tools/cc/hooks/_integrity.py`` is hard-coded
to preserve the ``tools/cc/`` zero-espalier-import isolation rule. That
isolation only works if a parity test catches drift between the
manifest and ``surface_contract.get_protected_integrity_paths``.

This test loads ``_integrity.py`` by file path so the isolation is not
weakened by importing ``espalier`` from inside the hook module.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


from espalier import managed_inventory, surface_contract

REPO_ROOT = Path(__file__).resolve().parent.parent

# Marker assignment lives in tests/conftest.py::_MARKER_RULES.


def _load_integrity_module():
    """Load tools/cc/hooks/_integrity.py without making tools/cc an espalier dep."""
    candidate = REPO_ROOT / "tools" / "cc" / "hooks" / "_integrity.py"
    spec = importlib.util.spec_from_file_location("_cc_integrity", candidate)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"Cannot locate _integrity.py at {candidate}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_integrity_manifest_equals_surface_contract():
    """``_integrity.MANIFEST_FILES`` must equal ``get_protected_integrity_paths``.

    Either side adding/removing a file without updating the other
    silently breaks integrity tracking. The failure message lists the
    asymmetric difference so an operator knows exactly which side to fix.
    """
    integrity = _load_integrity_module()
    manifest = set(integrity.MANIFEST_FILES)
    contract = set(surface_contract.get_protected_integrity_paths())

    only_in_contract = sorted(contract - manifest)
    only_in_manifest = sorted(manifest - contract)

    assert manifest == contract, (
        "Integrity manifest drift detected.\n"
        f"  In surface_contract.get_protected_integrity_paths but NOT in "
        f"_integrity.MANIFEST_FILES: {only_in_contract}\n"
        f"  In _integrity.MANIFEST_FILES but NOT in "
        f"surface_contract.get_protected_integrity_paths: {only_in_manifest}\n"
        f"Resolution: bring both lists into agreement; refresh "
        f".espalier/integrity.json afterwards."
    )


def test_manifest_includes_every_integrity_protected_path():
    """Sanity: each individual entry in the contract is reachable.

    Useful when the parity test fails — pinpoints which file is missing
    instead of dumping a diff.
    """
    integrity = _load_integrity_module()
    manifest = set(integrity.MANIFEST_FILES)
    for path in surface_contract.get_protected_integrity_paths():
        assert path in manifest, (
            f"protected integrity path {path!r} missing from "
            f"_integrity.MANIFEST_FILES"
        )


def test_every_hook_helper_is_integrity_tracked():
    """Every ``tools/cc/hooks/`` helper module must be integrity-tracked.

    TP-168 #7 roster-binding: ``_denial_reasons.py`` was a registered hook
    helper (``managed_inventory._HOOK_HELPERS``) but absent from
    ``MANIFEST_FILES`` / the surface_contract protected-integrity getter — so tampering with its
    block-message bodies escaped ``espalier audit``. Integrity coverage is an
    EXACT-file list (no prefix shortcut), so each helper must be enumerated.
    This binds the helper roster to the manifest so the next forgotten helper
    reddens here instead of opening a silent audit blind spot.
    """
    integrity = _load_integrity_module()
    manifest = set(integrity.MANIFEST_FILES)
    helpers = set(managed_inventory.get_hook_helper_files())
    missing = sorted(helpers - manifest)
    assert not missing, (
        f"hook helper module(s) not integrity-tracked: {missing}\n"
        "Add each to _integrity.MANIFEST_FILES (surface_contract's protected-"
        "integrity list now derives the tools/cc/hooks/ portion from "
        "managed_inventory automatically), then `espalier integrity refresh .`."
    )


def test_manifest_files_exist_on_disk():
    """Every file the manifest claims to track must actually exist."""
    integrity = _load_integrity_module()
    missing = [
        rel for rel in integrity.MANIFEST_FILES
        if not (REPO_ROOT / rel).is_file()
    ]
    assert not missing, (
        f"_integrity.MANIFEST_FILES references non-existent paths: {missing}"
    )


def test_json_safe_chokepoint_is_integrity_covered():
    """TP-191 W6: _integrity.py hard-imports tools/cc/_json_safe.py as its JSON
    decode chokepoint — the integrity check reads settings/manifests THROUGH that
    module, so tampering it could subvert the check itself. It must therefore be
    integrity-tracked. Earn-the-red: it was absent from MANIFEST_FILES."""
    integrity = _load_integrity_module()
    assert "tools/cc/_json_safe.py" in set(integrity.MANIFEST_FILES), (
        "tools/cc/_json_safe.py is imported by _integrity.py but not "
        "integrity-tracked — tampering it would escape `espalier audit`."
    )
