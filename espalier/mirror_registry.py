"""The declared census of this repo's byte-mirror families.

A *mirror row* is one ``(source of truth, mirror)`` pair that a test byte-pins.
This module is the single owner of that census: every other surface that needs
to know "is this path a mirror, and what fixes a drift" reads it from here
rather than re-listing the families.

Why a declaration and not a list in prose
-----------------------------------------
The census was maintained by hand in four independent places -- a runbook
invariant, a memory doc, the edit-time advisory table in the PostToolUse hook,
and this package's own surface classifier. They said three, four, two and four.
At the time they were reconciled the true count was six families across seven
rows -- and it has grown since, which is exactly the point. Each list was written
by someone reading the tree and typing what they saw, which is the failure mode
that a longer list cannot fix: the next family added will rot every hand-list
identically.

So the rule this module exists to enforce is **not** "the list is correct" --
it is "nothing may claim to enumerate mirrors except this file". A new family
is one row here, and the guards pick it up.

Reading the rows
----------------
Two fields are load-bearing and easy to skim past:

``comparator``
    Not every parity test compares the same way. Three rows compare through a
    line-ending normalisation; the rest compare raw bytes. A guard that assumed
    one comparator would silently loosen or tighten the other three contracts,
    so the difference is declared rather than averaged away.

``kind``
    ``byte`` rows are a whole-tree copy. ``subset`` rows mirror only part of
    their source tree -- three subdirectories of ``.claude/``, some of ``docs/``
    -- so a prefix test would claim unmirrored neighbours. The selfcheck row is
    ``subset+transform``: its sync copies some files verbatim, rewrites others,
    and *authors* one (``pytest.ini``) from a literal with no source file at
    all. So is ``pack-checklist``, narrower still -- it mirrors a delimited
    REGION of a single file, re-indented in transit, and deliberately leaves the
    source's version-stamped header behind. Guards must branch on this field
    rather than assume every row is a whole-tree byte pair; ``covers`` does that
    branching for them.

``direction`` is the one that bites. Every row but one puts the source of truth
in the working tree and the copy under a packaged directory; exactly one is
inverted -- the packaged asset is the source and the root file is generated.
"Edit the file where it lives" is therefore right everywhere except that single
row, and the wrong case looks exactly like its neighbours. The count is
deliberately not restated here: ``MIRROR_ROWS`` below is the census, and a
number in this docstring would be one more hand-kept copy of it.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Compare the two sides byte-for-byte.
BYTES = "bytes"
#: Compare after normalising CR/CRLF to LF (the packaged-resource parity style).
NORMALIZED = "normalized"

#: A whole-tree copy: every file on the source side appears verbatim on the
#: mirror side.
BYTE = "byte"
#: A curated selection of the source side, copied verbatim. Only some of the
#: source tree is mirrored, so source-side membership cannot be decided by
#: prefix alone.
SUBSET = "subset"
#: A curated selection, some of it rewritten in transit -- and, in one case,
#: authored outright with no source file behind it.
SUBSET_TRANSFORM = "subset+transform"

#: Kinds whose source side is a curated selection rather than a whole tree.
#: Membership for these is decided against the mirror tree, not by prefix.
_CURATED = (SUBSET, SUBSET_TRANSFORM)

#: The working-tree copy is the source of truth; the packaged copy is generated.
SOT_IS_SOURCE_TREE = "sot-is-source-tree"
#: Inverted: the packaged asset is the source of truth and the working-tree file
#: is generated from it.
SOT_IS_PACKAGED = "sot-is-packaged"


@dataclass(frozen=True)
class MirrorRow:
    """One byte-pinned ``(source of truth, mirror)`` pair.

    ``name`` is the stable handle. Rows are referred to by name everywhere --
    never by index -- because the census has been renumbered before and the
    stale ordinals outlived the tables that produced them.
    """

    name: str
    #: Repo-relative path, or an rglob-style pattern when the row covers a set
    #: of files rather than a directory (see ``vendor-cc``).
    sot: str
    #: One or more repo-relative mirror paths.
    mirrors: tuple[str, ...]
    #: The command that regenerates the mirror, or ``None`` when no script
    #: exists and the correction is a hand copy.
    sync: str | None
    #: pytest node id of the test that pins this row.
    pinning_test: str
    comparator: str
    kind: str
    direction: str

    @property
    def is_inverted(self) -> bool:
        return self.direction == SOT_IS_PACKAGED

    @property
    def has_sync(self) -> bool:
        return self.sync is not None


MIRROR_ROWS: tuple[MirrorRow, ...] = (
    MirrorRow(
        name="vendor-cc",
        # A GLOB, not a tree: the sync and its parity test both filter to the
        # deploy-source suffixes -- *.py, and *.cmd for the Windows statusline
        # shim (DEF-729) -- so the tracked .md files under tools/cc/ are
        # outside this row rather than missing from it. ``glob_row_parts``
        # reads the brace set; every consumer of the glob goes through it.
        sot="tools/cc/**/*.{py,cmd}",
        mirrors=("espalier/_vendor/cc/",),
        sync="python3 scripts/sync_vendor_cc.py",
        pinning_test="tests/test_vendor_cc_parity.py::TestVendorCcParity",
        comparator=BYTES,
        kind=BYTE,
        direction=SOT_IS_SOURCE_TREE,
    ),
    MirrorRow(
        name="claude-dogfooding",
        sot=".claude/",
        mirrors=("examples/dogfooding/.claude/",),
        sync="python3 scripts/sync_claude_mirrors.py",
        pinning_test=(
            "tests/test_package_resource_parity.py::TestRootMirrorParity"
            "::test_root_claude_mirrors_dogfooding"
        ),
        comparator=NORMALIZED,
        kind=SUBSET,
        direction=SOT_IS_SOURCE_TREE,
    ),
    MirrorRow(
        name="claude-asset",
        sot=".claude/",
        mirrors=("espalier/assets/claude/",),
        sync="python3 scripts/sync_claude_mirrors.py",
        pinning_test=(
            "tests/test_package_resource_parity.py::TestAssetClaudeMirrorParity"
        ),
        comparator=NORMALIZED,
        kind=SUBSET,
        direction=SOT_IS_SOURCE_TREE,
    ),
    MirrorRow(
        name="asset-docs",
        sot="docs/",
        mirrors=("espalier/assets/docs/",),
        sync="python3 scripts/sync_asset_docs.py",
        pinning_test=(
            "tests/test_deploy_doc_parity.py::TestSourceAssetDocByteParity"
            "::test_source_asset_docs_are_byte_equal"
        ),
        comparator=BYTES,
        kind=SUBSET,
        direction=SOT_IS_SOURCE_TREE,
    ),
    MirrorRow(
        name="task-packs-router",
        # Outside assets/docs/**, so the asset-docs rglob never reaches it. It
        # shares a sync script with asset-docs but carries its own guard, which
        # is why it is a row and not a footnote on that one.
        sot="task-packs/CLAUDE.md",
        mirrors=("espalier/assets/task-packs/CLAUDE.md",),
        sync="python3 scripts/sync_asset_docs.py",
        pinning_test=(
            "tests/test_deploy_doc_parity.py::TestSourceAssetDocByteParity"
            "::test_task_packs_asset_matches_source"
        ),
        comparator=BYTES,
        kind=BYTE,
        direction=SOT_IS_SOURCE_TREE,
    ),
    MirrorRow(
        name="selfcheck-tests",
        sot="tests/",
        mirrors=("espalier/_vendor/selfcheck_tests/",),
        sync="python3 scripts/sync_selfcheck_tests.py",
        pinning_test=(
            "tests/test_selfcheck_tests_parity.py::TestSelfcheckTestsParity"
        ),
        comparator=BYTES,
        kind=SUBSET_TRANSFORM,
        direction=SOT_IS_SOURCE_TREE,
    ),
    MirrorRow(
        name="harness-guard",
        # The inverted row: the asset is the source and the root workflow file is
        # generated from it. It carried no sync script for most of its life, which
        # is why a hand-edit of the generated copy was only caught by a full-suite
        # red -- there was nothing to run. The script now exists and runs
        # asset -> root, the opposite direction to every other sync here.
        sot="espalier/assets/github/workflows/harness-guard.yml",
        mirrors=(".github/workflows/harness-guard.yml",),
        sync="python3 scripts/sync_github_workflow_asset.py",
        pinning_test=(
            "tests/test_package_resource_parity.py::TestRootMirrorParity"
            "::test_root_workflow_mirrors_package"
        ),
        comparator=NORMALIZED,
        kind=BYTE,
        direction=SOT_IS_PACKAGED,
    ),
    MirrorRow(
        name="pack-checklist",
        # The narrowest row: a REGION of one file, not a tree. The nine
        # pack-artifact items live canonically in a tools/cc/ markdown file that
        # `init` never deploys, so /implement-pack carries them inline for
        # adopters -- two hand-maintained copies whose only guard compared each
        # item's leading TITLE. They drifted and read green for the whole of
        # their life. The inline copy is now generated between two markers.
        sot="tools/cc/pack_artifact_checklist.md",
        mirrors=(".claude/commands/implement-pack.md",),
        sync="python3 scripts/sync_checklist_regions.py",
        pinning_test=(
            "tests/test_implement_pack_step_zero.py::TestPackArtifactReviewSurface"
            "::test_inlined_checklist_is_generated_from_source"
        ),
        comparator=BYTES,
        # Both senses at once: only the ITEM BLOCK of the source crosses (the
        # version-stamped header must NOT -- the target is common-tier, where
        # TestCommonTierAssetHygiene forbids digit-bearing pack ids), and what
        # crosses is re-indented in transit.
        kind=SUBSET_TRANSFORM,
        direction=SOT_IS_SOURCE_TREE,
    ),
    MirrorRow(
        name="reasoning-checklist",
        # The pack-checklist row's twin, and the reason that row's script is named
        # for regions rather than for one file. Same shape exactly: a tools/cc/ .md
        # that `init` never deploys, inlined into a shipped common-tier body,
        # under a guard that compared item TITLES only -- measured blind on both.
        # The transform differs only in its line prefix: this region sits inside a
        # blockquoted agent prompt, so it takes "   > " rather than five spaces.
        sot="tools/cc/reasoning_review_checklist.md",
        mirrors=(".claude/skills/reflect/SKILL.md",),
        sync="python3 scripts/sync_checklist_regions.py",
        pinning_test=(
            "tests/test_reflect_reasoning.py::TestReasoningReviewSurface"
            "::test_inlined_checklist_is_generated_from_source"
        ),
        comparator=BYTES,
        kind=SUBSET_TRANSFORM,
        direction=SOT_IS_SOURCE_TREE,
    ),
)

#: Row names, for guards that report on coverage.
ROW_NAMES: frozenset[str] = frozenset(r.name for r in MIRROR_ROWS)

_GLOB_MARK = "/**/*."


def glob_row_parts(sot: str) -> "tuple[str, tuple[str, ...]] | None":
    """``(base, suffixes)`` for a glob-shaped ``sot``, else ``None``.

    The one parser of the ``<base>/**/*.<ext>`` and ``<base>/**/*.{a,b}``
    spellings: ``counterpart`` and the tests that derive a probe path per row
    both read it, so a row that widens its suffix set (``vendor-cc`` grew the
    ``.cmd`` shim, DEF-729) changes one string and no consumer.
    """
    idx = sot.find(_GLOB_MARK)
    if idx < 0:
        return None
    base = sot[: idx + 1]
    ext = sot[idx + len(_GLOB_MARK):]
    if ext.startswith("{") and ext.endswith("}"):
        names = [e.strip() for e in ext[1:-1].split(",") if e.strip()]
    else:
        names = [ext]
    return base, tuple("." + e for e in names)


def row(name: str) -> MirrorRow:
    """Return the row called ``name``.

    Raises ``KeyError`` rather than returning ``None`` so a typo in a caller
    fails loudly instead of silently disabling whatever the row was guarding.
    """
    for r in MIRROR_ROWS:
        if r.name == name:
            return r
    raise KeyError(f"no mirror row named {name!r}; known rows: {sorted(ROW_NAMES)}")


def counterpart(r: MirrorRow, rel_path: str) -> "str | None":
    """Map a source-side path to the mirror path it would land at.

    Returns ``None`` when ``rel_path`` is not on this row's source side at all.
    The answer is positional only -- it does not check whether the mirror file
    exists, which is what makes it usable as a membership oracle by callers that
    then stat the result (see ``covers``).
    """
    rel = rel_path.replace("\\", "/")
    prefix = r.sot
    glob = glob_row_parts(prefix)
    if glob is not None:
        base, suffixes = glob
        if not (rel.startswith(base) and rel.endswith(suffixes)):
            return None
        tail = rel[len(base):]
    elif prefix.endswith("/"):
        if not rel.startswith(prefix):
            return None
        tail = rel[len(prefix):]
    else:
        if rel != prefix:
            return None
        tail = ""
    mirror = r.mirrors[0]
    return mirror + tail if mirror.endswith("/") else mirror


def covers(r: MirrorRow, rel_path: str, root) -> bool:
    """Is ``rel_path`` a source-side file this row actually mirrors?

    For whole-tree rows this is a prefix test. For curated rows the source side
    is a *selection* -- only three subdirectories of ``.claude/``, only some of
    ``docs/``, only some of ``tests/`` -- so membership is decided by asking
    whether the counterpart exists on the mirror side.

    That indirection is deliberate. The alternative is to list the curated files
    here, which would be a second copy of a list the sync script already owns,
    and a second copy is the defect this module exists to remove. The mirror
    tree is the one oracle that cannot disagree with itself.

    It also fails in the safe direction. Declaring a row's source side too
    broadly (``.claude/`` when only three subdirectories ship) would otherwise
    make every unrelated neighbour look mirrored, and an advisory that fires on
    files it has no business firing on is the kind that gets tuned out.
    """
    target = counterpart(r, rel_path)
    if target is None:
        return False
    if r.kind not in _CURATED:
        return True
    return (root / target).exists()


def remedy(target: "MirrorRow | str") -> str:
    """One line telling the reader how to fix a drift in this row.

    Accepts a row or a row name. Every row currently ships a sync script, so the
    unscripted branch has no live population -- it is kept, and unit-tested
    against a synthetic row, because "no script" is a state this repo has been in
    before and the guard against naming a script that does not exist should not
    quietly become unreachable.

    Telling someone to "run the sync" when no script exists is worse than saying
    nothing: they run the nearest-looking script, it exits 0, and they rule the
    real cause out.
    """
    r = target if isinstance(target, MirrorRow) else row(target)
    if r.sync is not None:
        return f"run `{r.sync}`"
    return f"copy {r.sot} -> {r.mirrors[0]} by hand (no sync script exists)"
