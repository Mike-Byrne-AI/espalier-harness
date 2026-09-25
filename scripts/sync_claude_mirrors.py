#!/usr/bin/env python3
"""Sync the generated ``.claude`` config mirrors from the canonical self-host
``.claude/`` tree — the ``.claude`` analog of ``scripts/sync_vendor_cc.py``.

Espalier carries its agent/command/skill config three ways:

* ``.claude/{agents,commands,skills}`` — the SINGLE SOURCE OF TRUTH: the live
  self-host config Claude Code actually loads. **Hand-edit HERE only.**
* ``espalier/assets/claude/{...}`` — wheel package-data; ``init``/``deploy``
  copy it into an adopter repo. GENERATED — do not hand-edit.
* ``examples/dogfooding/.claude/{...}`` — the adopter-facing reference example
  (linked from README + QUICKSTART, shipped in the sdist). GENERATED.

All three are pinned byte-for-byte by ``tests/test_package_resource_parity.py``
(``TestRootMirrorParity`` + ``TestAssetClaudeMirrorParity``); the generator
itself is pinned by ``TestClaudeMirrorGenerator``. This script is the fixer
those tests point at.

Run this after editing any ``.claude/{agents,commands,skills}/`` file so the two
mirrors stay in lockstep::

    python scripts/sync_claude_mirrors.py

Stdlib-only: copies every SoT file into each mirror and prunes any mirror file
whose SoT source was removed, so the byte-parity holds in both directions.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUBDIRS = ("agents", "commands", "skills")
SRC = REPO_ROOT / ".claude"
MIRRORS = (
    REPO_ROOT / "espalier" / "assets" / "claude",
    REPO_ROOT / "examples" / "dogfooding" / ".claude",
)


def _files(root: Path) -> set[str]:
    """Repo-relative-to-``root`` POSIX paths of every file under the SoT subdirs.

    Globs all files (not just ``*.md``) to match the coverage of the byte-parity
    tests' ``rglob("*")`` — so a future non-Markdown asset can't slip the sync.
    """
    out: set[str] = set()
    for sub in SUBDIRS:
        base = root / sub
        if base.is_dir():
            out.update(
                p.relative_to(root).as_posix()
                for p in base.rglob("*")
                if p.is_file()
            )
    return out


def plan() -> dict[str, dict[str, list[str]]]:
    """Dry-run: what each mirror needs to match the SoT, WITHOUT writing.

    Returns ``{mirror_posix: {"stale": [...], "orphans": [...]}}`` where ``stale``
    are SoT files missing-or-byte-different in the mirror and ``orphans`` are
    mirror files with no SoT source. Empty everywhere == in sync.
    """
    src_files = _files(SRC)
    report: dict[str, dict[str, list[str]]] = {}
    for mirror in MIRRORS:
        stale = [
            rel
            for rel in sorted(src_files)
            if not (mirror / rel).exists()
            or (mirror / rel).read_bytes() != (SRC / rel).read_bytes()
        ]
        orphans = sorted(_files(mirror) - src_files)
        report[mirror.relative_to(REPO_ROOT).as_posix()] = {
            "stale": stale,
            "orphans": orphans,
        }
    return report


def sync() -> tuple[int, int]:
    """Mirror SoT -> every mirror. Returns ``(copied, pruned)``."""
    src_files = _files(SRC)
    if not src_files:
        raise SystemExit(
            f"refusing to sync: source {SRC} is missing or empty "
            "(syncing would prune every mirror file). Mirror of the "
            "sync_vendor_cc.py empty-source guard."
        )
    copied = pruned = 0
    for mirror in MIRRORS:
        for rel in sorted(src_files):
            target = mirror / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SRC / rel, target)
            copied += 1
        for rel in sorted(_files(mirror) - src_files):
            (mirror / rel).unlink()
            pruned += 1
    return copied, pruned


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sync (or --check) the .claude mirrors.")
    ap.add_argument(
        "--check", action="store_true",
        help="verify mirror byte-parity WITHOUT writing; nonzero exit on drift",
    )
    ns = ap.parse_args(argv)
    mirrors = ", ".join(m.relative_to(REPO_ROOT).as_posix() for m in MIRRORS)
    if ns.check:
        drift = {m: r for m, r in plan().items() if r["stale"] or r["orphans"]}
        if drift:
            for m, r in drift.items():
                for rel in r["stale"]:
                    print(f"DRIFT stale   {m}/{rel}", file=sys.stderr)
                for rel in r["orphans"]:
                    print(f"DRIFT orphan  {m}/{rel}", file=sys.stderr)
            print(f"check: [{mirrors}] DIVERGE from .claude", file=sys.stderr)
            return 1
        print(f"check: [{mirrors}] in parity with .claude")
        return 0
    copied, pruned = sync()
    print(f"synced [{mirrors}] <- .claude: {copied} copied, {pruned} pruned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
