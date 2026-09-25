#!/usr/bin/env python3
"""Regenerate the doc regions whose content a Python object already owns.

Sibling of ``scripts/sync_checklist_regions.py``, and deliberately a separate
script rather than a second family inside that one: its regions are sliced out
of a canonical *markdown file*, these are *rendered from a live Python object*.
Same marker convention, same splice, different source kind.

Why not ``sync_*.py``
---------------------
The name is load-bearing. ``tests/test_reinject_sync.py`` enrolls every
``scripts/sync_*.py`` in the byte-mirror census and requires each to be claimed
by an ``espalier/mirror_registry.py`` row. A render-from-Python is **not** a
byte-mirror -- there is no ``(source file, mirror file)`` pair to pin, and
declaring one would mean inventing a fake source path to satisfy a guard about
a different thing. ``generate_`` states the difference in the filename.

Which docs may carry a region -- the rule this script exists inside
------------------------------------------------------------------
**Generate where the doc has no downstream copies; contract where it ships.**

A seed doc that is also a mirror source must never get a generated region. Such
a file ships to an adopter under an explicit *"this file is yours, never
overwritten"* promise, and ``espalier/cli.py::_seed_redeploy_decision`` returns
``"preserve"`` **permanently** once the adopter's post-stamp bytes stop hashing
to the recorded digest. So the first time they edit one word, they are frozen
holding a generated block that says *do not hand-edit* -- which they cannot
regenerate, because an adopter tree has no ``scripts/``. ``docs/TROUBLESHOOTING.md``
and ``docs/WORKFLOW.md`` are exactly that shape and are fixed by prose plus a
contract test instead. ``README.md`` and ``docs/QUICKSTART.md`` are self-host
only, with zero downstream copies, which is what makes them eligible.

Marker naming is a live hazard
------------------------------
``espalier/managed_markers.py::_MARKER_LINE_RE`` matches ``espalier:managed``
with a trailing ``\\b``, and ``\\b`` matches before a hyphen. A region named
``espalier:managed-anything`` therefore flips its file from operator-owned to
harness-owned, and ``clean-generated`` deletes it. Region names here must not
begin ``espalier:managed``; ``_forbidden_marker_name`` refuses at construction
rather than leaving it to review.

The floor, and why every region declares one
--------------------------------------------
``docs/STANDING_PRINCIPLES.md`` §14: *derive the population and a narrowing is
silent*. That is the live hazard for a generated doc region -- delete an entry
from the source tuple and the block simply gets shorter, confidently and
completely, with nothing left to disagree with it. Each region declares the
smallest population it may legitimately render; below that the script refuses
instead of writing. The floor is a *tripwire against a derivation going wrong*,
not a running count, so it sits well under the live number and moves only when
a population genuinely shrinks.
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from espalier import cli  # noqa: E402
from espalier import managed_inventory  # noqa: E402
from espalier.surface_hygiene import SPECIFIC_ID_RE  # noqa: E402

_SCRIPT = "scripts/generate_doc_regions.py"

#: A region name starting with this flips its file to harness-owned (see the
#: module docstring). Refused at construction.
_OWNERSHIP_MARKER_PREFIX = "espalier:managed"


# ── renderers ────────────────────────────────────────────────────────────
# Each returns ``(block_text, population_size)``. The size is what the floor is
# checked against: it counts DERIVED items, not rendered lines, so reformatting
# the block can never quietly satisfy a floor that a shrinking source broke.


def _bullet(paths: tuple[str, ...] | list[str]) -> str:
    return ", ".join(f"`{p}`" for p in paths)


def render_deploy_inventory() -> tuple[str, int]:
    """What ``init`` writes that the hand-written bullet lists do not name.

    Deliberately additive. The lists it sits under carry five sole-site numeric
    contracts between them (``README.md``'s hook-entry and helper-module counts,
    ``docs/QUICKSTART.md``'s ``7 / 17 / 9``), and those contracts assert their
    regex matched at least once -- so rewording either line reds five
    parametrizations even with every number still correct. This block adds what
    is missing and touches neither.
    """
    seeds = managed_inventory.get_seed_docs()
    generated = managed_inventory.get_generated_docs()
    tools = tuple(cli.INIT_TOOL_SCRIPTS)
    runtime = managed_inventory.local_runtime_rel_paths()

    # (heading, description, paths-under-that-heading). Every group's count and
    # its names come from ONE list, because the first cut of this function drew
    # them from two -- rendering "5 artifacts" above a list of 3 -- which is the
    # very defect class the region exists to close.
    def _group_by_top_level(paths, description, out):
        """Bucket by top-level directory, keeping ROOT-LEVEL files separate.

        `rel.split("/", 1)[0]` returns the whole path when there is no `/`, so
        a root-level entry rendered as its own directory: adding `AGENTS.md`
        to the seed set shipped ``**`AGENTS.md/`** — 1 file … `AGENTS.md``` into
        README and QUICKSTART, and BOTH property arms passed (1 == 1, and the
        completeness arm used the same fallback, so it found the name it was
        looking for). A very live convention away from being wrong in public.
        """
        by_dir: dict[str, list[str]] = {}
        root: list[str] = []
        for rel in paths:
            (by_dir.setdefault(rel.split("/", 1)[0], []) if "/" in rel
             else root).append(rel)
        for top in sorted(by_dir):
            out.append((f"{top}/", description, sorted(by_dir[top])))
        if root:
            out.append(("", f"{description}, at the repo root", sorted(root)))

    # A seed doc covered by a required gitignore entry is still the adopter's
    # to edit, but it will NOT stage -- and saying only "yours to edit", in a
    # list that explicitly contrasts that bucket against "never committed",
    # tells them the opposite of what their git will do. Split by the canon
    # rather than restating a verdict beside it: REQUIRED_GITIGNORE is a
    # third, independent authority on committed-vs-not, so without this the
    # two generated regions in the SAME doc can contradict each other and no
    # test can see it. Derived, so a future required entry that swallows a
    # seed doc self-reports here.
    from espalier.cli import REQUIRED_GITIGNORE, _gitignore_key, _ignore_pattern_matches

    def _is_ignored(rel: str) -> bool:
        return any(
            _ignore_pattern_matches(entry, rel)
            for entry in REQUIRED_GITIGNORE
            if _gitignore_key(entry)
        )

    seeds_open = [r for r in seeds if not _is_ignored(r)]
    seeds_ignored = [r for r in seeds if _is_ignored(r)]

    groups: list[tuple[str, str, list[str]]] = []
    # The sentence states what `cli._write_seed` does: an untouched seed is
    # refreshed when the packaged copy changes, an edited one is left as it
    # is. "skip-if-exists" was written here on 2026-08-12 (b943e05), eighteen
    # days AFTER the refresh helper (e3aff98, 2026-07-25) stopped skipping, by
    # a doc commit whose subject claimed to describe what init does: born
    # wrong, not aged wrong (DEF-432). Both seed groups carry the clause, or
    # the contrast tells the reader the gitignored seed is not refreshed.
    seed_rule = "seeded, refreshed on re-init only while untouched, and yours to edit"
    _group_by_top_level(seeds_open, seed_rule, groups)
    if seeds_ignored:
        _group_by_top_level(
            seeds_ignored,
            # No backticks in this description: the bullet's own count gate
            # parses backticked tokens after the colon as FILENAMES, so a
            # backticked git command in the prose reads as a second file and
            # reds "states 1 but names 2". Measured, not guessed.
            seed_rule + ", but gitignored as local working "
            "state -- force-add if you want one in history",
            groups,
        )
    groups.append(("cc/", "generated surface docs", sorted(generated)))
    groups.append((
        "tools/cc/", "standalone scripts alongside the hook tree", sorted(tools),
    ))
    _group_by_top_level(
        runtime, "generated per install, never committed", groups,
    )

    lines = [
        # NOT "which the list above does not name" -- the first draft said that,
        # and it was false for three entries the summary above does name
        # (`statusline.py`, `integrity.json`, `reports/`). This block is shared
        # by two docs whose preceding lists differ, so any claim about "above"
        # is unverifiable from here. Claim only what is true in both: this list
        # is complete.
        "`init` also creates the paths below. Every path and count here is",
        "generated from the deploy inventory itself, so the list is complete",
        "and cannot drift from what lands in your repo.",
        "",
    ]
    for heading, description, paths in groups:
        # Strip the GROUP'S OWN heading, not the first path segment: `tools/cc/`
        # is a two-segment heading, and splitting on the first `/` left every
        # entry rendering as `cc/_paths.py` under a `tools/cc/` bullet.
        shown = [p[len(heading):] if p.startswith(heading) else p for p in paths]
        noun = "file" if len(paths) == 1 else "files"
        label = f"**`{heading}`** — " if heading else "**Repo root** — "
        lines.append(
            f"- {label}{len(paths)} {noun}, {description}:"
            f" {_bullet(tuple(shown))}"
        )
    lines.append(
        f"- **`.gitignore`** -- {len(cli.REQUIRED_GITIGNORE)} entries appended,"
        " unless you pass `--no-write-gitignore`"
    )
    return "\n".join(lines), sum(len(p) for _, _, p in groups)


def render_required_gitignore() -> tuple[str, int]:
    """The exact block ``init`` appends, for the ``--no-write-gitignore`` reader.

    Renders the fence delimiters too, so the markers sit OUTSIDE the fence. An
    HTML comment inside a ``` block renders literally, and this is the one block
    on the page a reader is meant to select and copy -- marker text landing in
    their ``.gitignore`` would be the fix creating its own defect.
    """
    entries = cli.REQUIRED_GITIGNORE
    body = "\n".join((cli.GITIGNORE_BLOCK_HEADER, *entries))
    return f"```\n{body}\n```", len(entries)


# ── regions ──────────────────────────────────────────────────────────────


class Region:
    """One ``(Python source, generated region)`` pair."""

    __slots__ = ("name", "target", "source", "_render", "floor")

    def __init__(self, name: str, target: str, source: str, render, floor: int):
        if name.startswith(_OWNERSHIP_MARKER_PREFIX):
            raise ValueError(
                f"region name {name!r} starts with {_OWNERSHIP_MARKER_PREFIX!r}: "
                "managed_markers._MARKER_LINE_RE would read the begin marker as an "
                "ownership marker (its \\b matches before a hyphen), flipping the "
                "file to harness-owned so `clean-generated` deletes it. Rename."
            )
        self.name = name
        self.target = Path(target)
        #: Human-readable derivation, quoted in every message. Always a `.py`
        #: symbol: the pointer-resolution extractors match `.md` targets only,
        #: so naming a Python path here cannot mint a dangling doc pointer.
        self.source = source
        self._render = render
        self.floor = floor

    @property
    def begin_marker(self) -> str:
        return (f"<!-- {self.name}: BEGIN generated region -- do not hand-edit. "
                f"Regenerated by {_SCRIPT} from {self.source}. -->")

    @property
    def end_marker(self) -> str:
        return f"<!-- {self.name}: END generated region -->"

    def render(self) -> str:
        block, population = self._render()
        if population < self.floor:
            raise ValueError(
                f"{self.name}: derived {population} item(s) from {self.source}, "
                f"below the declared floor of {self.floor}. A generated region "
                "shrinks SILENTLY -- the block just gets shorter and every test "
                "still passes -- so this refuses instead of writing. If the "
                "population legitimately shrank, lower the floor in the same "
                "commit that shrank it, and say why."
            )
        if not block.strip():
            raise ValueError(f"{self.name}: rendered an empty block.")
        leaked = sorted(set(SPECIFIC_ID_RE.findall(block)))
        if leaked:
            raise ValueError(
                f"{self.name}: rendered text carries digit-bearing pack id(s) "
                f"{leaked}. {self.target} is a public doc scanned by "
                "espalier/provenance_census.py; keep internal ids out of it."
            )
        return block


REGIONS: tuple[Region, ...] = (
    Region(
        name="deploy-inventory",
        target="README.md",
        source="espalier/managed_inventory.py + espalier/cli.py::INIT_TOOL_SCRIPTS",
        render=render_deploy_inventory,
        floor=30,
    ),
    Region(
        name="deploy-inventory-quickstart",
        target="docs/QUICKSTART.md",
        source="espalier/managed_inventory.py + espalier/cli.py::INIT_TOOL_SCRIPTS",
        render=render_deploy_inventory,
        floor=30,
    ),
    Region(
        name="required-gitignore",
        target="docs/QUICKSTART.md",
        source="espalier/cli.py::REQUIRED_GITIGNORE",
        render=render_required_gitignore,
        floor=8,
    ),
)


def splice(region: Region, target_text: str, rendered: str) -> tuple[str, str]:
    """Return ``(new_target_text, current_region)``.

    Line-based, first-pair, duplicate-refusing -- copied wholesale from
    ``sync_checklist_regions.py::splice``, including the reason a character
    offset is wrong there (the end marker's indent makes ``sync`` -> ``--check``
    report drift on a file it just wrote).
    """
    begin, end_m = region.begin_marker, region.end_marker
    lines = target_text.split("\n")
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
            "Re-add them around the region; this script does not guess where it "
            "belongs."
        )
    current = "\n".join(lines[b + 1:e])
    return "\n".join(lines[: b + 1] + rendered.split("\n") + lines[e:]), current


def _process(region: Region, *, check: bool) -> tuple[int, bool]:
    """Return ``(exit_code, changed)`` for one region."""
    dst = _ROOT / region.target
    if not dst.is_file():
        print(f"missing: {region.target}", file=sys.stderr)
        return 1, False
    if dst.stat().st_size == 0:
        print(f"refusing to operate on an EMPTY file: {region.target}",
              file=sys.stderr)
        return 1, False
    try:
        rendered = region.render()
        new_text, current = splice(region, dst.read_text(encoding="utf-8"), rendered)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1, False

    if current == rendered:
        print(f"  [{region.name}] in parity with {region.source}")
        return 0, False

    diff = "\n".join(difflib.unified_diff(
        current.split("\n"), rendered.split("\n"),
        fromfile=f"{region.target} (inlined)", tofile=f"{region.source} (derived)",
        lineterm="",
    ))
    if check:
        print(
            f"DRIFT [{region.name}]: {region.target}'s region differs from what "
            f"{region.source} now derives.\n"
            f"  The Python source is canonical; the region is generated.\n"
            f"  Re-apply any inline-only improvement to the SOURCE, then run:\n"
            f"    python3 {_SCRIPT}\n\n{diff}",
            file=sys.stderr,
        )
        return 1, False

    dst.write_text(new_text, encoding="utf-8")
    print(f"  [{region.name}] generated {region.target} <- {region.source}")
    # Never discard an inline-only edit silently.
    print("    replaced:\n" + diff)
    return 0, True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate (or --check) the doc regions whose content a live "
                    "Python object owns.",
    )
    ap.add_argument(
        "--check", action="store_true",
        help="verify every region matches its derivation WITHOUT writing; "
             "nonzero exit on drift",
    )
    ap.add_argument(
        "--region", choices=[r.name for r in REGIONS],
        help="operate on one region only (default: all)",
    )
    ns = ap.parse_args(argv)

    regions = [r for r in REGIONS if not ns.region or r.name == ns.region]
    rc = 0
    print("check:" if ns.check else "generate:")
    for region in regions:
        code, _ = _process(region, check=ns.check)
        rc = rc or code
    return rc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
