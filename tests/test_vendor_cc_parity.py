"""TP-178: byte-parity between the source-tree ``tools/cc`` and its
wheel-vendored copy ``espalier/_vendor/cc``.

The wheel stops shipping a bare top-level ``tools`` package (it squatted the
generic ``tools`` import name in every environment that installs Espalier).
The deploy SOURCE now reads hook/tool scripts from a committed byte-copy under
``espalier/_vendor/cc/`` — shipped as package-data, mirroring ``espalier/assets/``
(which has no ``__init__.py`` either). ``tools/cc/`` STAYS in the source tree
(self-host + sdist source readers) and remains the adopter DEST after init.

This test pins the two trees byte-identical in BOTH directions so the vendored
copy can never silently drift from the source the harness self-hosts on. To
re-sync after editing ``tools/cc``, run ``python scripts/sync_vendor_cc.py``.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "tools" / "cc"
VENDOR = REPO_ROOT / "espalier" / "_vendor" / "cc"


#: The deploy-source suffixes the mirror carries: every ``.py``, and the
#: ``.cmd`` Windows statusline shim (DEF-729). Pinned equal to the sync
#: script's constant and the ``vendor-cc`` row's brace set below.
MIRRORED_SUFFIXES = (".py", ".cmd")


def _mirrored_files(root: Path) -> dict[str, bytes]:
    """Map of repo-relative deploy-source path -> bytes, excluding ``__pycache__``."""
    return {
        str(p.relative_to(root)).replace("\\", "/"): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and p.suffix in MIRRORED_SUFFIXES and "__pycache__" not in p.parts
    }


class TestVendorCcParity:
    def test_file_sets_are_a_bijection(self):
        src = set(_mirrored_files(SRC))
        vendor = set(_mirrored_files(VENDOR))
        assert src == vendor, (
            "tools/cc and espalier/_vendor/cc deploy-source file sets diverged "
            "(run `python scripts/sync_vendor_cc.py`): "
            f"only in source={sorted(src - vendor)}; "
            f"only in vendor={sorted(vendor - src)}"
        )

    def test_every_file_is_byte_identical(self):
        src = _mirrored_files(SRC)
        vendor = _mirrored_files(VENDOR)
        mismatched = sorted(
            rel for rel in (set(src) & set(vendor)) if src[rel] != vendor[rel]
        )
        assert not mismatched, (
            "vendored copy drifted from source byte-for-byte "
            f"(run `python scripts/sync_vendor_cc.py`): {mismatched}"
        )

    def test_vendor_tree_is_nonempty(self):
        # Guards against a refactor silently emptying the vendored tree, which
        # would make the bijection assertion vacuously true (empty == empty).
        assert len(_mirrored_files(VENDOR)) > 0, "espalier/_vendor/cc has no deploy-source files"

    def test_the_statusline_shim_is_mirrored(self):
        """DEF-729: the one deployed non-.py file. A suffix filter that still
        read ``*.py`` would pass the bijection with the shim missing from the
        wheel's deploy source."""
        assert "statusline.cmd" in _mirrored_files(VENDOR), (
            "espalier/_vendor/cc/statusline.cmd is missing (run `python scripts/sync_vendor_cc.py`)"
        )

    def test_the_four_suffix_sets_agree(self):
        """The sync script, this test, the ``vendor-cc`` mirror row and the
        deploy inventory's ``DEPLOYED_SCRIPT_SUFFIXES`` (read by the retired-
        file scan) each spell the suffix set; the script is stdlib-only and
        cannot import the others. One drifting would let a suffix ship
        unmirrored, be pruned on sync, or never be named once retired."""
        import importlib.util

        from espalier import mirror_registry
        from espalier.managed_paths import DEPLOYED_SCRIPT_SUFFIXES

        spec = importlib.util.spec_from_file_location(
            "sync_vendor_cc", REPO_ROOT / "scripts" / "sync_vendor_cc.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        row = next(r for r in mirror_registry.MIRROR_ROWS if r.name == "vendor-cc")
        _, row_suffixes = mirror_registry.glob_row_parts(row.sot)
        assert (
            set(module.MIRRORED_SUFFIXES) == set(MIRRORED_SUFFIXES)
            == set(row_suffixes) == set(DEPLOYED_SCRIPT_SUFFIXES)
        )
