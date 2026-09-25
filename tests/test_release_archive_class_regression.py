"""TP-27: regression test for the v0.6.0 archive-class leak.

In v0.6.0, a top-level `project.zip` (6 MB dev snapshot) classified as
`public` and shipped in the release archive. Root cause: the noise
patterns covered `dist/` (releases) and `__pycache__/` (caches) but not
top-level archives at the repo root.

This test parametrizes on the false-positive class so it can't drift back.
"""
from __future__ import annotations

import pytest

from espalier.surface_contract import (
    classify_release_path,
    get_release_excluded_prefixes,
)

FALSE_POSITIVE_PATHS = [
    # The specific v0.6.0 instance
    "project.zip",
    # Class siblings: any top-level archive must not be public
    "snapshot.zip",
    "backup.tar",
    "release.tar.gz",
    "state.tgz",
    "archive.7z",
    "old-build.tar.bz2",
    # Subdir archives outside dist/ — also leaks
    "scratch/dump.zip",
    "deep/nested/file.tar.gz",
]


class TestArchiveClassNotPublic:
    @pytest.mark.parametrize("path", FALSE_POSITIVE_PATHS)
    def test_archive_does_not_classify_as_public(self, path):
        classification = classify_release_path(path)
        assert classification != "public", (
            f"Path {path!r} classified as {classification!r} but archives "
            f"should never be public. Pattern is missing from "
            f"espalier.release_noise.ARCHIVE_FILES."
        )


# TP-182 C6: the bespoke release-zip builders (`build_release_archive` /
# `release_pack`) walked the working tree at the time (they enumerate the git
# index now, with the tree walk as the no-index fallback), so they would ship
# gitignored `task-packs/*-findings.json` (which carried a private home-dir
# path) because they classified `public` — only the `TP-*.md` packs had a rule.
# The wired `python -m build` PyPI path was clean because MANIFEST.in never
# sweeps `task-packs/` -- NOT because it is git-based: setuptools enumerates the
# filesystem (no setuptools_scm in the build requires), so an untracked `.py`
# under a swept package dir ships in the wheel and the sdist (driven on a
# replica of this packaging config, 2026-09-08; a ledger row holds it).
# Parametrized on the leak class so it can't drift back.
TASK_PACK_LEAK_PATHS = [
    # The specific instances that leaked (findings JSON had no rule)
    "task-packs/TP-176-oss-convergence-findings.json",
    "task-packs/TP-169-round0-findings.json",
    # Class siblings: any file under task-packs/ that is not in the named ship
    # set must be excluded. Since 2026-09-21 the ship set is the forward ledger,
    # its probes file, the router and the packs directly under task-packs/ and
    # task-packs/Deferred/ (surface_contract.SHIPPED_TASK_PACK_FILES +
    # is_shipped_pack); a landed pack, a stray note, a nested findings file and
    # a non-pack under Deferred/ stay out. `task-packs/TP-182-fusion-first-hour-
    # correctness.md` sat here as a ROOT pack until then; it ships now, so the
    # landed copy takes its slot.
    "task-packs/Done/TP-182-fusion-first-hour-correctness.md",
    "task-packs/scratch-findings.json",
    "task-packs/notes.txt",
    "task-packs/nested/deep-findings.json",
    "task-packs/Deferred/notes.md",
    "task-packs/Done/LAYER1-SPEC.md",
    "task-packs/FORWARD_LEDGER_PRE_REBUILD_2026-09-20.md",
]


class TestTaskPacksNotPublic:
    @pytest.mark.parametrize("path", TASK_PACK_LEAK_PATHS)
    def test_task_packs_do_not_classify_as_public(self, path):
        classification = classify_release_path(path)
        assert classification != "public", (
            f"Path {path!r} classified as {classification!r} but task-packs/ is "
            f"local-only harness-dev authoring state outside its named ship set. "
            f"`task-packs/` is missing from surface_contract._LOCAL_ONLY_PREFIXES, "
            f"or the ship-set carve-out in is_local_only grew past its allow-list."
        )

    def test_task_packs_prefix_is_not_pruned_by_the_bespoke_walker(self):
        # INVERTED 2026-09-21. The directory-prune set the bespoke walkers use to
        # skip whole subtrees early once held `task-packs/`; now that the forward
        # ledger and the active packs ship from inside it, pruning the folder
        # would drop them, so the walkers must DESCEND and let the per-file
        # classifier decide. The leak class this module pins is still closed by
        # the prefix in `is_local_only` (the rows above), not by the prune.
        assert "task-packs/" not in get_release_excluded_prefixes()
        assert classify_release_path("task-packs/FORWARD_LEDGER.md") == "public"


# TP-182 C6 sibling (found by the adversarial pass): the SAME bespoke-walker leak
# class also covered underscore-prefixed cc/ review scratch (`cc/_pack_review_*`,
# `cc/_recall_engine_review*`) — gitignored harness-dev review artifacts (one was
# a 155 KB findings JSON) that classified `public` and shipped in the bespoke zip
# while the `python -m build` path stayed clean (MANIFEST.in never sweeps `cc/`;
# that path is a filesystem sweep, not git-based -- see above). cc/'s only public
# surfaces are the explicit COMMANDS.md/LIVE_SURFACE.md/PACK_MANIFEST.txt allowlist.
CC_SCRATCH_LEAK_PATHS = [
    "cc/_pack_review_findings.json",
    "cc/_pack_review_report.md",
    "cc/_pack_review_workflow.mjs",
    "cc/_recall_engine_review.mjs",
    "cc/_recall_engine_review_r2.mjs",
    # Class sibling: any future underscore-prefixed cc/ scratch must be excluded
    "cc/_future_review_scratch.json",
]


class TestCcScratchNotPublic:
    @pytest.mark.parametrize("path", CC_SCRATCH_LEAK_PATHS)
    def test_cc_scratch_does_not_classify_as_public(self, path):
        classification = classify_release_path(path)
        assert classification != "public", (
            f"Path {path!r} classified as {classification!r} but underscore-"
            f"prefixed cc/ scratch is gitignored review work product that must "
            f"never ship. `cc/_` is missing from "
            f"surface_contract._LOCAL_ONLY_PREFIXES."
        )

    def test_cc_allowlist_surfaces_stay_public(self):
        # Guard against the cc/_ rule over-matching: the explicit public cc/
        # surfaces (no underscore prefix) must remain shippable.
        for public in ("cc/COMMANDS.md", "cc/LIVE_SURFACE.md", "cc/PACK_MANIFEST.txt"):
            assert classify_release_path(public) == "public", (
                f"{public} must stay public; the cc/_ rule over-matched."
            )
