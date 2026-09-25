#!/usr/bin/env python3
"""Sync the wheel-vendored deploy source ``espalier/_vendor/cc/`` from
the canonical ``tools/cc/``.

The wheel ships hook/tool scripts as package-data under ``espalier/_vendor/cc/``
— it must NOT ship a bare top-level ``tools`` package (that would squat the
generic ``tools`` import name in every environment that installed Espalier). ``tools/cc/``
stays the canonical, hand-edited source (and the adopter DEST after ``init``);
``espalier/_vendor/cc/`` is a byte-for-byte mirror of its deploy-source files:
every ``.py``, and the ``.cmd`` Windows statusline shim (DEF-729).
``tests/test_vendor_cc_parity.py`` reds if the two drift.

Run this after editing any ``tools/cc/**/*.py`` or ``*.cmd`` so the vendored
copy stays in lockstep::

    python scripts/sync_vendor_cc.py

Pass ``--check`` to verify byte-parity read-only (nonzero exit on drift, no
writes) -- the CI-friendly twin, matching ``sync_claude_mirrors.py --check``.

Stdlib-only: copies every mirrored file into the mirror and prunes any
vendored file whose source was removed, so the parity bijection holds in both
directions.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "tools" / "cc"
VENDOR = REPO_ROOT / "espalier" / "_vendor" / "cc"

#: The deploy-source suffixes the mirror carries. Mirrors the brace set of the
#: ``vendor-cc`` row in ``espalier/mirror_registry.py`` (this script is
#: stdlib-only and cannot import it); ``tests/test_vendor_cc_parity.py`` pins
#: the two equal.
MIRRORED_SUFFIXES: tuple[str, ...] = (".py", ".cmd")


def _mirrored_files(root: Path) -> set[str]:
    """Repo-relative deploy-source paths under ``root``, excluding ``__pycache__``."""
    return {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix in MIRRORED_SUFFIXES
        and "__pycache__" not in p.parts
    }


def _require_source(src_files: set[str]) -> None:
    """Refuse to operate on an empty/missing source: a rename would otherwise
    silently prune the entire vendored mirror."""
    if not src_files:
        raise SystemExit(
            f"refusing to sync: source {SRC} is missing or contains no deploy-source "
            f"files (a rename would otherwise silently prune the entire vendored mirror)"
        )


def plan() -> tuple[list[str], list[str]]:
    """Read-only drift report ``(stale, orphans)`` -- the ``--check`` twin of
    ``sync()``. ``stale`` = source files whose vendored copy is missing or
    byte-differs; ``orphans`` = vendored files with no surviving source. Writes
    nothing."""
    src_files = _mirrored_files(SRC)
    _require_source(src_files)
    stale = [
        rel
        for rel in sorted(src_files)
        if not (VENDOR / rel).exists()
        or (VENDOR / rel).read_bytes() != (SRC / rel).read_bytes()
    ]
    orphans = sorted(_mirrored_files(VENDOR) - src_files)
    return stale, orphans


def sync() -> tuple[int, int]:
    """Mirror SRC -> VENDOR. Returns ``(copied, pruned)``."""
    src_files = _mirrored_files(SRC)
    _require_source(src_files)
    for rel in sorted(src_files):
        target = VENDOR / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SRC / rel, target)
    # Prune vendored files whose source was deleted (keep the bijection).
    orphans = sorted(_mirrored_files(VENDOR) - src_files)
    for rel in orphans:
        (VENDOR / rel).unlink()
    return len(src_files), len(orphans)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Sync (or --check) the wheel-vendored espalier/_vendor/cc mirror."
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="verify mirror byte-parity WITHOUT writing; nonzero exit on drift",
    )
    ns = ap.parse_args(argv)
    if ns.check:
        stale, orphans = plan()
        if stale or orphans:
            for rel in stale:
                print(f"DRIFT stale   espalier/_vendor/cc/{rel}", file=sys.stderr)
            for rel in orphans:
                print(f"DRIFT orphan  espalier/_vendor/cc/{rel}", file=sys.stderr)
            print("check: espalier/_vendor/cc DIVERGES from tools/cc", file=sys.stderr)
            return 1
        print("check: espalier/_vendor/cc in parity with tools/cc")
        return 0
    copied, pruned = sync()
    print(
        f"synced espalier/_vendor/cc <- tools/cc: {copied} copied, {pruned} pruned"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
