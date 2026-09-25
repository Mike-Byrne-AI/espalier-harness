#!/usr/bin/env python3
"""Regenerate the inlined fixed-checklist regions from their canonical sources.

Two shipped bodies carry a checklist that is maintained somewhere else:

===========================  =========================================
canonical source             generated into
===========================  =========================================
pack-artifact checklist      ``.claude/commands/implement-pack.md``
reasoning-review checklist   ``.claude/skills/reflect/SKILL.md``
===========================  =========================================

Both canonical files live under ``tools/cc/``, which ``espalier init`` never
copies into an adopter repo -- so both bodies carry the items INLINE. (An earlier
version instructed *"read tools/cc/<name>.md"*, which dangled for every adopter;
inlining fixed that and created this.)

Both copies were then maintained by hand, and the guard meant to hold each pair
together compared only an item's leading TITLE. Under that guard an item's entire
elaboration can be replaced with nonsense and the full suite stays green --
measured on both pairs, not supposed. That is why the item blocks are generated
now, and why one script owns both: a second copy of this logic would be the
parallel-inventory hazard the thing it fixes is made of.

The transform per region is deliberately trivial and total -- take the item block
verbatim, apply a constant line prefix -- because a transform with judgement in
it is just a second place for the two copies to disagree. The prefixes differ
(five spaces for a bullet-nested block; ``   > `` for one embedded in a
blockquoted agent prompt) and that is the whole of the difference.

Two constraints are enforced here rather than left to a downstream red:

* **A generated region must carry no digit-bearing pack id.** Both targets are
  common-tier and ship to every adopter, where
  ``tests/test_init_tier_split.py::TestCommonTierAssetHygiene`` forbids them.
  Each canonical file's *header* carries a version stamp deliberately (which
  ``espalier/provenance_census.py`` pins); slicing the ITEM BLOCK is what keeps
  it out of the shipped body. Enforced against the same ``SPECIFIC_ID_RE`` the
  contract uses, so the two cannot disagree about what counts.
* **Overwriting a region that differs prints the diff.** A wording improvement
  that lives only on the generated side is exactly what a silent sync destroys.

Each region is byte-pinned by its own row in ``espalier/mirror_registry.py``.
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from espalier.surface_hygiene import SPECIFIC_ID_RE  # noqa: E402

_SCRIPT = "scripts/sync_checklist_regions.py"


class Region:
    """One ``(canonical source, generated region)`` pair."""

    __slots__ = ("name", "sot", "target", "prefix", "start_re", "end_re")

    #: A region name starting with this makes ``managed_markers`` read the
    #: begin marker as an OWNERSHIP marker -- its ``\b`` matches before a hyphen
    #: -- flipping the target from operator-owned to harness-owned so
    #: ``clean-generated`` deletes it. This script's targets are ``.claude/``
    #: command and skill bodies that ship to EVERY adopter, so the blast radius
    #: here is larger than in the sibling generator that first carried this
    #: guard: an adopter loses their command body.
    _OWNERSHIP_MARKER_PREFIX = "espalier:managed"

    def __init__(self, name: str, sot: str, target: str, prefix: str,
                 start: str, end: str):
        if name.startswith(self._OWNERSHIP_MARKER_PREFIX):
            raise ValueError(
                f"region name {name!r} starts with "
                f"{self._OWNERSHIP_MARKER_PREFIX!r}: managed_markers would read "
                "the begin marker as an ownership marker, flipping this shipped "
                "body to harness-owned so `clean-generated` deletes the "
                "adopter's copy. Rename."
            )
        self.name = name
        self.sot = Path(sot)
        self.target = Path(target)
        #: Prepended to every non-blank line. Blank lines get it right-stripped,
        #: so a blockquote stays contiguous without trailing whitespace.
        self.prefix = prefix
        self.start_re = re.compile(start)
        self.end_re = re.compile(end)

    @property
    def begin_marker(self) -> str:
        # Names NO undeployed tools/cc/*.md path: these markers ship, that source
        # does not, and a shipped body naming it is the dangling-reference class
        # this repo already fixed once -- tests/test_shipped_asset_md_refs.py
        # enforces it and caught exactly that in an earlier draft. The self-host
        # reader loses nothing: the edit-time advisory, `--check` and
        # `espalier surface-impact` all name the source when it matters.
        return (f"<!-- {self.name}: BEGIN generated region -- do not hand-edit. "
                f"Regenerated by {_SCRIPT}, Espalier-Harness self-host tooling; "
                "an adopter repo has no scripts/ and never runs it. -->")

    @property
    def end_marker(self) -> str:
        return f"<!-- {self.name}: END generated region -->"


REGIONS: tuple[Region, ...] = (
    Region(
        name="pack-artifact-checklist",
        sot="tools/cc/pack_artifact_checklist.md",
        target=".claude/commands/implement-pack.md",
        prefix=" " * 5,               # nested inside step 0-A's bullet list
        start=r"^1\.\s",
        end=r"^Output format per item:",
    ),
    Region(
        name="reasoning-review-checklist",
        sot="tools/cc/reasoning_review_checklist.md",
        target=".claude/skills/reflect/SKILL.md",
        prefix="   > ",               # inside the blockquoted agent prompt
        start=r"^For each item below",
        end=r"^Output format per item:",
    ),
)

_ITEM_RE = re.compile(r"^(?:\*\*)?(\d+)\.\s")


def extract_items(region: Region, sot_text: str) -> str:
    """Return the region's source block verbatim (unprefixed, no trailing NL).

    Raises ``ValueError`` naming the fix rather than returning a partial block. A
    sync that silently renders half a checklist into a shipped body is worse than
    one that refuses.
    """
    lines = sot_text.splitlines()
    start = next((i for i, ln in enumerate(lines) if region.start_re.match(ln)), None)
    if start is None:
        raise ValueError(
            f"{region.sot}: no line matching {region.start_re.pattern!r} -- the "
            "item block cannot be located."
        )
    end = next((i for i, ln in enumerate(lines[start:], start)
                if region.end_re.match(ln)), None)
    if end is None:
        raise ValueError(
            f"{region.sot}: no line matching {region.end_re.pattern!r} after the "
            "items -- the block has no terminator, so its extent is unknown."
        )
    block = "\n".join(lines[start:end]).rstrip("\n")
    if not block.strip():
        raise ValueError(f"{region.sot}: the item block is empty.")

    numbers = [int(m.group(1)) for m in
               (_ITEM_RE.match(ln) for ln in block.split("\n")) if m]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError(
            f"{region.sot}: item numbers are {numbers}, expected a contiguous run "
            "from 1. Renumber; a gap means an item was lost in an edit."
        )

    leaked = sorted(set(SPECIFIC_ID_RE.findall(block)))
    if leaked:
        raise ValueError(
            f"{region.sot}: item text carries digit-bearing pack id(s) {leaked}. "
            f"{region.target} is common-tier and ships to every adopter, where "
            "TestCommonTierAssetHygiene forbids them. Keep specific ids in the "
            "file's header (outside the item block) or use a generic placeholder "
            "such as `TP-NN`."
        )
    return block


def render(region: Region, block: str) -> str:
    """Apply the region's constant line prefix."""
    return "\n".join(
        f"{region.prefix}{ln}" if ln.strip() else region.prefix.rstrip()
        for ln in block.split("\n")
    )


def splice(region: Region, target_text: str, rendered: str) -> tuple[str, str]:
    """Return ``(new_target_text, current_region)``.

    Line-based on purpose. A character-offset splice has to re-add the end
    marker's own indent, so the round trip ``sync`` -> ``--check`` compares a
    region carrying a trailing indent against one that does not, and reports
    drift on a file it just wrote.
    """
    begin, end_m = region.begin_marker, region.end_marker
    lines = target_text.split("\n")
    # Exactly one pair. Both this writer and its pinning test take the FIRST pair,
    # so a duplicated region (a bad merge, a second variant flow) would be
    # regenerated by neither and checked by neither -- stale forever, and green.
    if sum(begin in ln for ln in lines) > 1 or sum(end_m in ln for ln in lines) > 1:
        raise ValueError(
            f"{region.target}: more than one '{region.name}' marker pair. Both "
            "this script and its pinning test read only the first, so any later "
            "region would be silently stale. Remove the duplicate."
        )
    b = next((i for i, ln in enumerate(lines) if begin in ln), None)
    e = next((i for i, ln in enumerate(lines[b + 1:], b + 1) if end_m in ln),
             None) if b is not None else None
    if b is None or e is None:
        raise ValueError(
            f"{region.target}: '{region.name}' markers not found. Expected a line\n"
            f"  {begin}\nand a later line\n  {end_m}\n"
            "Re-add them around the checklist items; this script does not guess "
            "where the region belongs."
        )
    current = "\n".join(lines[b + 1:e])
    return "\n".join(lines[: b + 1] + rendered.split("\n") + lines[e:]), current


def _process(region: Region, *, check: bool) -> tuple[int, bool]:
    """Return ``(exit_code, changed)`` for one region."""
    src, dst = _ROOT / region.sot, _ROOT / region.target
    for path, rel in ((src, region.sot), (dst, region.target)):
        if not path.is_file():
            print(f"missing: {rel}", file=sys.stderr)
            return 1, False
        # Matches sync_vendor_cc.py / sync_claude_mirrors.py: never propagate a
        # truncated source into a shipped surface.
        if path.stat().st_size == 0:
            print(f"refusing to operate on an EMPTY file: {rel}", file=sys.stderr)
            return 1, False
    try:
        rendered = render(region, extract_items(region, src.read_text(encoding="utf-8")))
        new_text, current = splice(region, dst.read_text(encoding="utf-8"), rendered)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1, False

    if current == rendered:
        print(f"  [{region.name}] in parity with {region.sot}")
        return 0, False

    diff = "\n".join(difflib.unified_diff(
        current.split("\n"), rendered.split("\n"),
        fromfile=f"{region.target} (inlined)", tofile=f"{region.sot} (source)",
        lineterm="",
    ))
    if check:
        print(
            f"DRIFT [{region.name}]: {region.target}'s region differs from its "
            f"source {region.sot}.\n"
            f"  {region.sot} is the source of truth; the region is generated.\n"
            f"  Re-apply any inline-only improvement to the SOURCE, then run:\n"
            f"    python3 {_SCRIPT}\n\n{diff}",
            file=sys.stderr,
        )
        return 1, False

    dst.write_text(new_text, encoding="utf-8")
    print(f"  [{region.name}] synced {region.target} <- {region.sot}")
    # Never discard an inline-only edit silently.
    print("    replaced:\n" + diff)
    return 0, True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Sync (or --check) the inlined fixed-checklist regions from "
                    "their canonical tools/cc/ sources.",
    )
    ap.add_argument(
        "--check", action="store_true",
        help="verify every region matches its source WITHOUT writing; nonzero "
             "exit on drift",
    )
    ap.add_argument(
        "--region", choices=[r.name for r in REGIONS],
        help="operate on one region only (default: all)",
    )
    ns = ap.parse_args(argv)

    regions = [r for r in REGIONS if not ns.region or r.name == ns.region]
    rc, any_changed = 0, False
    print("check:" if ns.check else "sync:")
    for region in regions:
        code, changed = _process(region, check=ns.check)
        rc = rc or code
        any_changed = any_changed or changed
    if any_changed:
        print("  note: .claude/ is byte-mirrored -- "
              "run `python3 scripts/sync_claude_mirrors.py` before commit.")
    return rc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
