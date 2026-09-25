#!/usr/bin/env python3
"""Regenerate espalier/assets/ doc mirrors from their docs/ (+ task-packs/) sources.

Assets ship via package-data and MUST be byte-identical to source —
tests/test_deploy_doc_parity.py::TestSourceAssetDocByteParity pins the
assets/docs/** bodies and a targeted test in the same module pins
assets/task-packs/CLAUDE.md. Run after editing any carried doc so the mirror
stays in lockstep with its source.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _mirrored() -> tuple[str, ...]:
    """DERIVE the mirror set from the deploy inventory, don't hand-keep it.

    A seed is mirrored iff ``init`` copies its body straight out of
    ``espalier/assets/<dest>`` -- i.e. iff its asset source is the identity.
    The two Tier-3 stubs (``docs/SHARP_EDGES.md``, ``docs/CONVENTIONS.md``)
    redirect to ``seed/`` and have no source twin, so they fall out naturally
    rather than needing an exclusion.

    This was a hand-written tuple, and it failed the first time it was tested:
    adding ``docs/HOOK_ASSUMPTIONS.md`` to the deploy set left the mirror
    un-synced and silently stale, so `init` shipped the OLD body while the
    source read correct -- the enumeration-drift class (§C1) inside the very
    script that exists to keep two copies in step. Derived, that cannot recur.
    """
    from espalier import managed_inventory

    return tuple(
        rel for rel in sorted(managed_inventory.get_seed_docs())
        if managed_inventory.get_seed_asset_source(rel) == rel
    )


_MIRRORED: tuple[str, ...] = _mirrored()


def _diff_only() -> list[str]:
    """Byte-parity drift for the ``_MIRRORED`` set, WITHOUT copying. Returns
    human-readable drift lines (empty == in parity)."""
    drift: list[str] = []
    for rel in _MIRRORED:
        src = _ROOT / rel
        dst = _ROOT / "espalier" / "assets" / rel
        if not src.is_file():
            drift.append(f"missing source: {rel}")
        elif not dst.is_file():
            drift.append(f"missing asset: espalier/assets/{rel}")
        elif src.read_bytes() != dst.read_bytes():
            drift.append(f"stale asset: espalier/assets/{rel} != {rel}")
    return drift


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sync (or --check) the asset doc mirrors.")
    ap.add_argument(
        "--check", action="store_true",
        help="verify source↔asset byte-parity WITHOUT writing; nonzero exit on drift",
    )
    ns = ap.parse_args(argv)
    if ns.check:
        drift = _diff_only()
        if drift:
            for d in drift:
                print(f"DRIFT: {d}", file=sys.stderr)
            return 1
        print(f"check: {len(_MIRRORED)} asset doc mirror(s) in parity")
        return 0
    for rel in _MIRRORED:
        src = _ROOT / rel
        dst = _ROOT / "espalier" / "assets" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    print(f"synced {len(_MIRRORED)} asset doc mirrors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
