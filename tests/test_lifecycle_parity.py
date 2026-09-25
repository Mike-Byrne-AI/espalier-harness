"""TP-RELEASE-17 — Cross-system managed-surface parity.

Pins the invariant that four independent views of "what the
harness owns" agree set-by-set on the live self-host repo:

1. **Init's deployment list** — the union of ``INIT_HOOK_SCRIPTS``,
   ``INIT_TOOL_SCRIPTS``, and the bundled package assets init
   copies into ``.claude/{commands,agents,skills}/`` in step 6b of
   ``cmd_init``.
2. **Managed inventory** — ``managed_inventory.get_managed_public_files``.
3. **Rendered manifest** — entries in ``render_pack_manifest`` output.
4. **Cleanup-considered set** — paths the cleanup module would
   inspect for marker-aware removal.

If any pair disagrees, the test fails with a specific diff. The
fix is always to converge the disagreeing views on a single SoT,
never to relax the test. Without this contract these four lists
could silently drift independently — a new asset added to init but
not registered in managed_inventory would deploy correctly but
later survive ``espalier clean-generated``, leaving orphans that
no one would discover until uninstall.

This is the cross-system complement to:

- ``test_manifest_truth.TestCommittedManifestMatchesRenderer``
  (file-level byte equality, TP-RELEASE-16)
- ``test_managed_cleanup_parity`` (init→clean dynamic behavior)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from espalier.cli import INIT_HOOK_SCRIPTS, INIT_TOOL_SCRIPTS
from espalier.managed_inventory import (
    get_managed_public_files,
)
from espalier.render_surface import render_pack_manifest

REPO_ROOT = Path(__file__).resolve().parent.parent

# full-tree-exempt: calls render_pack_manifest(REPO_ROOT) but only asserts
# PARITY against get_managed_public_files(REPO_ROOT) — both derive from the same
# root, so the equality is self-consistent on a pruned release export (no
# absolute-content assertion). Confirmed export-safe: not slow, so it runs and
# passes on the release-matrix export stage. Hence no `full_tree` marker. (TP-283)


def _rendered_manifest_entries() -> set[str]:
    """Path entries from render_pack_manifest, stripped of comments."""
    return {
        line.strip()
        for line in render_pack_manifest(REPO_ROOT).splitlines()
        if line.strip() and not line.startswith("#")
    }


# ---------------------------------------------------------------------------
# Init deploys → managed inventory: every deployed-managed path IS in inventory
# ---------------------------------------------------------------------------


class TestInitDeploysAreInManagedInventory:
    """Files init deploys as managed-public must appear in get_managed_public_files."""

    def test_hook_entries_in_managed_inventory(self):
        managed = set(get_managed_public_files(REPO_ROOT))
        hook_entries = [
            p for p in INIT_HOOK_SCRIPTS
            if not Path(p).name.startswith("_")
        ]
        missing = [p for p in hook_entries if p not in managed]
        assert not missing, (
            f"Hook entry scripts deployed by init but missing from "
            f"managed_inventory: {missing}"
        )

    def test_hook_helpers_in_managed_inventory(self):
        managed = set(get_managed_public_files(REPO_ROOT))
        hook_helpers = [
            p for p in INIT_HOOK_SCRIPTS
            if Path(p).name.startswith("_")
        ]
        missing = [p for p in hook_helpers if p not in managed]
        assert not missing, (
            f"Hook helpers deployed by init but missing from "
            f"managed_inventory: {missing}"
        )

    def test_tool_scripts_in_managed_inventory(self):
        managed = set(get_managed_public_files(REPO_ROOT))
        missing = [p for p in INIT_TOOL_SCRIPTS if p not in managed]
        assert not missing, (
            f"Non-hook tool scripts deployed by init but missing from "
            f"managed_inventory: {missing}.\n"
            "Either add to managed_inventory or remove from INIT_TOOL_SCRIPTS."
        )


# ---------------------------------------------------------------------------
# Managed inventory ↔ rendered manifest: SET EQUAL
# ---------------------------------------------------------------------------


class TestManagedInventoryEqualsRenderedManifest:
    """get_managed_public_files() must equal entries in render_pack_manifest().

    This is the strongest cross-system claim: the renderer's output is
    derived from the inventory by construction. They must agree exactly.
    """

    def test_set_equality(self):
        managed = set(get_managed_public_files(REPO_ROOT))
        rendered = _rendered_manifest_entries()

        in_managed_not_rendered = managed - rendered
        in_rendered_not_managed = rendered - managed

        if in_managed_not_rendered or in_rendered_not_managed:
            pytest.fail(
                "managed_inventory.get_managed_public_files() != "
                "render_pack_manifest entries.\n"
                f"  in managed but not rendered: "
                f"{sorted(in_managed_not_rendered)}\n"
                f"  in rendered but not managed: "
                f"{sorted(in_rendered_not_managed)}\n\n"
                "Both views are supposed to come from a single SoT. If "
                "they disagree, the renderer is not consuming the full "
                "managed inventory (fix render_surface.render_pack_manifest), "
                "or the inventory has stale entries (fix managed_inventory)."
            )


# ---------------------------------------------------------------------------
# Local-only files must NEVER appear in any of the views above
# ---------------------------------------------------------------------------


class TestLocalOnlyExcludedEverywhere:
    """Local-only paths must not leak into any managed-public view."""

    def test_settings_json_not_in_any_view(self):
        path = ".claude/settings.json"
        managed = set(get_managed_public_files(REPO_ROOT))
        rendered = _rendered_manifest_entries()
        assert path not in managed, f"{path} in managed_inventory (must be local-only)"
        assert path not in rendered, f"{path} in rendered manifest (must be local-only)"

    def test_scheduled_tasks_lock_not_in_any_view(self):
        path = ".claude/scheduled_tasks.lock"
        managed = set(get_managed_public_files(REPO_ROOT))
        rendered = _rendered_manifest_entries()
        assert path not in managed
        assert path not in rendered

    def test_surface_handoff_not_in_any_view(self):
        """The specific 0.5.0 leak: SURFACE_HANDOFF.md was in the manifest."""
        path = "cc/SURFACE_HANDOFF.md"
        managed = set(get_managed_public_files(REPO_ROOT))
        rendered = _rendered_manifest_entries()
        assert path not in managed, f"{path} in managed_inventory (must be local-only)"
        assert path not in rendered, (
            f"{path} in rendered manifest — this was the 0.5.0 corruption. "
            "Check managed_inventory.get_local_only_files contains it and "
            "that render_pack_manifest filters local-only paths."
        )

    def test_integrity_json_not_in_any_view(self):
        path = ".espalier/integrity.json"
        managed = set(get_managed_public_files(REPO_ROOT))
        rendered = _rendered_manifest_entries()
        assert path not in managed
        assert path not in rendered


# ---------------------------------------------------------------------------
# Pinned divergence: get_managed_public_files vs self_host_managed_paths
# ---------------------------------------------------------------------------


class TestKnownRootDocsDelta:
    """Pin the intentional divergence between two related views.

    ``self_host_managed_paths`` (the self-host ownership inventory ``doctor``
    reports; NOT write_guard's protected zone, which is
    ``tools/cc/hooks/_protected_zones.py`` and names neither root doc) and
    ``get_managed_public_files`` (publicly shipped surface) both describe
    "what the harness owns in self-host mode" but serve different
    consumers. They diverge on exactly one root-level path, and agree on a
    second by omission:

    - ``.claudeignore`` is in the ownership inventory (the harness claims
      it as its own config) but NOT in the public manifest (it is config
      the user may author themselves).
    - ``README.md`` is in NEITHER. It sat in the public manifest until
      2026-09-11 because it ships in the harness's own package, but the
      manifest answers what the harness OWNS in the tree it was run on,
      and ``init`` never writes an adopter's README -- so the manifest an
      adopter received claimed their own README as shipped surface while
      ``clean-generated`` reported it as a preserved user file (DEF-556).

    This delta is intentional. If a future contributor accidentally
    converges the lists (e.g., by routing self_host_managed_paths
    through get_managed_public_files), the rationale is lost. This
    test pins the expected delta so the divergence cannot drift
    silently in either direction.
    """

    def test_known_delta_between_self_host_and_managed_inventory(self):
        from espalier.managed_paths import self_host_managed_paths

        protected = set(self_host_managed_paths(REPO_ROOT))
        public = set(get_managed_public_files(REPO_ROOT))

        in_protected_only = protected - public
        in_public_only = public - protected

        # Pin the EXPECTED root-doc delta. Other deltas (e.g., reports/,
        # settings.json) are out of scope for this test — they are
        # different concerns (runtime artifacts, not root docs).
        protected_root_doc_extras = {p for p in in_protected_only if "/" not in p}
        public_root_doc_extras = {p for p in in_public_only if "/" not in p}

        assert ".claudeignore" in protected_root_doc_extras, (
            ".claudeignore should be in self_host_managed_paths "
            "(the harness claims it as its own config). Either restore it to "
            "STANDARD_MANAGED_ROOT_DOCS or update this test if the "
            "semantic decision has changed."
        )
        assert "README.md" not in public_root_doc_extras, (
            "README.md is back in get_managed_public_files. init never writes "
            "an adopter's README, so listing it makes the manifest claim their "
            "own file as shipped harness surface (DEF-556). Remove it from "
            "_PACKAGED_ROOT_DOCS, or update this test and that docstring if "
            "the semantic decision has changed."
        )
        # Also pin the inverse: don't let the lists silently equalize.
        assert ".claudeignore" not in public_root_doc_extras, (
            ".claudeignore unexpectedly appears in get_managed_public_files. "
            "If this is intentional (a SoT unification), update this test "
            "and the _PACKAGED_ROOT_DOCS docstring."
        )
        assert "README.md" not in protected_root_doc_extras, (
            "README.md unexpectedly appears in self_host_managed_paths. "
            "If this is intentional (a SoT unification), update this test "
            "and the _PACKAGED_ROOT_DOCS docstring."
        )
        assert "README.md" not in public, (
            "README.md must not be in the managed public inventory at all: "
            "the adopter's README is theirs (DEF-556)."
        )
