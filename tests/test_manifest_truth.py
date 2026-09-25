"""TP-04 §8 + TP-RELEASE-16 — PACK_MANIFEST truth tests.

Two distinct concerns:

1. **The renderer produces the right shape** (TestManifestIncludesManagedSurface,
   TestManifestExcludesLocalOnly, TestManifestDeterminism). These tests
   call render_pack_manifest(REPO_ROOT) and assert categorical
   properties of the output.

2. **The committed cc/PACK_MANIFEST.txt is the renderer's output**
   (TestCommittedManifestMatchesRenderer, added by TP-RELEASE-16).
   This class reads the committed file from disk and asserts
   byte-equality with the renderer. It is the independent canon
   that catches drift between what the renderer produces today and
   what was last committed.

Both concerns must pass. The 0.5.0 release shipped a corrupted
committed manifest because (1) passed and (2) did not exist — every
existing test called render_pack_manifest on both sides, which made
drift invisible. TP-RELEASE-16 closes the loop.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from espalier.managed_inventory import (
    get_local_only_files,
)
from espalier.render_surface import (
    render_commands_doc,
    render_live_surface,
    render_pack_manifest,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Marker assignment lives in tests/conftest.py::_MARKER_RULES.


def _manifest_lines(repo_root: Path) -> set[str]:
    text = render_pack_manifest(repo_root)
    return {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    }


# ---------------------------------------------------------------------------
# Inclusion — pack §8 first assertion
# ---------------------------------------------------------------------------


class TestManifestIncludesManagedSurface:
    """Render-only assertions about the manifest shape.

    # contract: ok severity-scale tautological-legacy
    # NOTE (TP-137 §B): every test in this class calls
    # ``render_pack_manifest(REPO_ROOT)`` on both sides of every
    # assertion — tautological. Load is carried by
    # ``TestCommittedManifestMatchesRenderer`` (TP-RELEASE-16). Retained
    # for archeology; safe to delete if the rationale comment is
    # preserved in CHANGELOG.
    """
    # TP-31: agents/commands/skills removed from managed inventory (no longer
    # deployed by default). test_canonical_agents_in_manifest,
    # test_all_commands_in_manifest, and test_all_skills_in_manifest deleted.

    def test_all_hook_files_in_manifest(self):
        entries = _manifest_lines(REPO_ROOT)
        hooks_dir = REPO_ROOT / "tools" / "cc" / "hooks"
        for hook in hooks_dir.glob("*.py"):
            if hook.name == "__init__.py":
                continue
            rel = f"tools/cc/hooks/{hook.name}"
            assert rel in entries, f"{rel} missing from PACK_MANIFEST"

    def test_generated_cc_docs_in_manifest(self):
        entries = _manifest_lines(REPO_ROOT)
        for doc in ("cc/LIVE_SURFACE.md", "cc/COMMANDS.md", "cc/PACK_MANIFEST.txt"):
            assert doc in entries, f"{doc} missing from PACK_MANIFEST"


# ---------------------------------------------------------------------------
# Exclusion — pack §8 second assertion
# ---------------------------------------------------------------------------


class TestManifestExcludesLocalOnly:
    def test_local_only_paths_not_in_manifest(self):
        entries = _manifest_lines(REPO_ROOT)
        for local_only in get_local_only_files():
            assert local_only not in entries, (
                f"local-only path {local_only} leaked into PACK_MANIFEST"
            )

    def test_runtime_files_not_in_manifest(self):
        entries = _manifest_lines(REPO_ROOT)
        for runtime in (
            ".claude/settings.json",
            ".espalier/integrity.json",
            "reports/cc_surface_gate.json",
            "reports/harness_config.json",
            "reports/repo_fingerprint.json",
        ):
            assert runtime not in entries, (
                f"runtime artifact {runtime} leaked into PACK_MANIFEST"
            )

    def test_blueprint_files_not_in_manifest(self):
        entries = _manifest_lines(REPO_ROOT)
        # cc/blueprints/* are session-local
        for entry in entries:
            assert not entry.startswith("cc/blueprints/"), (
                f"session blueprint {entry} leaked into PACK_MANIFEST"
            )


# ---------------------------------------------------------------------------
# Determinism — re-rendering is byte-stable
# ---------------------------------------------------------------------------


class TestManifestDeterminism:
    """Renderer is deterministic — same input, same output.

    # contract: ok severity-scale tautological-legacy
    # NOTE (TP-137 §B): both sides of the equality call
    # ``render_pack_manifest(REPO_ROOT)`` — same function, same input.
    # Load is carried by ``TestCommittedManifestMatchesRenderer``
    # (TP-RELEASE-16). Retained for archeology; safe to delete if the
    # rationale comment is preserved in CHANGELOG.
    """
    def test_render_is_stable(self):
        a = render_pack_manifest(REPO_ROOT)
        b = render_pack_manifest(REPO_ROOT)
        assert a == b


# ---------------------------------------------------------------------------
# TP-RELEASE-16 — Independent canon: committed file matches renderer output.
#
# Every other test in this file calls render_pack_manifest(REPO_ROOT) on
# both sides of every assertion. That is a tautology — the committed
# cc/PACK_MANIFEST.txt is never read from disk. The 0.5.0 corruption
# (SURFACE_HANDOFF.md listed as public, skills + helpers missing, stale
# header) shipped because no test compared the committed file to the
# renderer.
#
# This class adds the missing canon: read cc/PACK_MANIFEST.txt from disk,
# compare to render_pack_manifest() byte-for-byte. If they disagree,
# either the renderer changed and the committed file needs regeneration
# (most common) or the SoT inventory changed and the renderer needs an
# update (TP-RELEASE-17 covers the inventory-parity case).
# ---------------------------------------------------------------------------


class TestCommittedManifestMatchesRenderer:
    """The committed cc/PACK_MANIFEST.txt must equal render_pack_manifest()."""

    MANIFEST_PATH = REPO_ROOT / "cc" / "PACK_MANIFEST.txt"

    def test_committed_file_exists(self):
        """The committed manifest must exist."""
        assert self.MANIFEST_PATH.exists(), (
            "cc/PACK_MANIFEST.txt missing — run "
            "render_pack_manifest(Path('.')) and write to "
            "cc/PACK_MANIFEST.txt with newline='\\n', then commit."
        )

    def test_committed_file_byte_equals_renderer(self):
        """The committed file's bytes must equal render_pack_manifest output.

        This is the missing independent canon. The 0.5.0 release shipped
        a corrupted committed manifest because no test compared committed
        to rendered. Now they must agree by construction.

        The committed PACK_MANIFEST must reflect the full shipped asset
        set. (The harness-dev deploy tier was retired, so every consumer
        gets the same surface; the manifest is no longer tier-dependent.)
        """
        rendered = render_pack_manifest(REPO_ROOT)
        committed = self.MANIFEST_PATH.read_text(encoding="utf-8")

        if rendered != committed:
            # Compute a small unified diff to put the failure mode in
            # the operator's hands rather than dumping both files.
            import difflib

            diff_lines = list(difflib.unified_diff(
                committed.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                fromfile="cc/PACK_MANIFEST.txt (committed)",
                tofile="render_pack_manifest() output",
                n=2,
            ))
            diff_text = "".join(diff_lines[:60])
            if len(diff_lines) > 60:
                diff_text += f"\n... ({len(diff_lines) - 60} more diff lines)"

            pytest.fail(
                "cc/PACK_MANIFEST.txt does not match render_pack_manifest() "
                "output. Regenerate the file with:\n\n"
                "    python -c \"import sys; sys.path.insert(0, '.'); "
                "from espalier.render_surface import render_pack_manifest; "
                "from pathlib import Path; "
                "Path('cc/PACK_MANIFEST.txt').write_text("
                "render_pack_manifest(Path('.')), encoding='utf-8', newline='\\n')\"\n\n"
                "If the renderer's output looks wrong, the cause is upstream "
                "in espalier.managed_inventory / espalier.surface_contract — "
                "fix there, then regenerate.\n\nDiff:\n" + diff_text
            )

    def test_committed_file_does_not_list_local_only_paths(self):
        """The committed manifest must not promise local-only paths.

        This is the specific 0.5.0 bug: cc/SURFACE_HANDOFF.md was listed
        as public surface, but surface_contract classifies it local_only.
        A user reading the manifest would expect that file to ship; it
        doesn't.
        """
        from espalier.surface_contract import classify_release_path

        if not self.MANIFEST_PATH.exists():
            pytest.skip("cc/PACK_MANIFEST.txt missing — see test_committed_file_exists")

        text = self.MANIFEST_PATH.read_text(encoding="utf-8")
        entries = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.startswith("#")
        ]

        leaks: list[tuple[str, str]] = []
        for entry in entries:
            bucket = classify_release_path(entry)
            if bucket != "public":
                leaks.append((entry, bucket))

        assert not leaks, (
            f"Committed manifest lists {len(leaks)} non-public path(s):\n"
            + "\n".join(f"  - {p}  (bucket: {b})" for p, b in leaks)
            + "\nThese promise files that won't ship in the public release. "
            "Either remove from PACK_MANIFEST or fix classify_release_path "
            "(rarely the right answer)."
        )

    def test_committed_file_header_documents_generation(self):
        """The committed manifest's header must document its generation.

        Operators who open cc/PACK_MANIFEST.txt to "fix" a count by hand
        need a hint at the top telling them the file is generated. This
        test locks in the presence of a regeneration breadcrumb.
        """
        if not self.MANIFEST_PATH.exists():
            pytest.skip("cc/PACK_MANIFEST.txt missing — see test_committed_file_exists")

        text = self.MANIFEST_PATH.read_text(encoding="utf-8")
        first_lines = "\n".join(text.splitlines()[:5])

        # The renderer emits a `# espalier:managed` marker on the first
        # line and a description in the next 1-2 lines. The "Operator-facing"
        # phrase is part of the canonical header.
        required_markers = (
            "# espalier:managed",
            "Operator-facing manifest",
            "managed_inventory",
        )
        for marker in required_markers:
            assert marker in first_lines, (
                f"cc/PACK_MANIFEST.txt header missing required marker {marker!r}. "
                f"First 5 lines were:\n{first_lines}\n\n"
                "The header is produced by render_pack_manifest; if it has "
                "drifted, regenerate the file."
            )


class TestCommittedSurfaceMatchesRenderer:
    """TP-184 B13: cc/COMMANDS.md and cc/LIVE_SURFACE.md must equal their
    renderers, byte for byte — a local drift gate for the two generated
    dispatch-table surfaces that (unlike cc/PACK_MANIFEST.txt) had no
    byte-equality contract, so their staleness shipped green.

    LOCAL-ONLY by necessity (TP-184 adversarial follow-up): unlike
    render_pack_manifest (which sources the committed managed_inventory),
    render_live_surface / render_commands_doc read GITIGNORED runtime state —
    render_live_surface's hook count comes from .claude/settings.json via
    surface_contract.discover_wired_hooks, and both renderers' "Stable actions"
    section comes from reports/harness_config.json via _load_stable_actions.
    On a clean checkout (CI's actions/checkout, which never runs `espalier init`
    / `fingerprint`) neither file exists, so the render emits "0 hooks" with no
    stable-actions block and could never byte-match the committed files — it
    would red EVERY CI run. The committed files are the SELF-HOST repo's
    runtime-rendered surface, not reproducible from the committed tree alone and
    not reproducible from a fresh common-tier `initialized_repo_root` (which
    renders a different surface), so this gate skips when the runtime inputs are
    absent and enforces where they exist (the maintainer's machine, where the
    regenerate-and-commit step happens).
    """

    SURFACES = (
        ("cc/COMMANDS.md", render_commands_doc),
        ("cc/LIVE_SURFACE.md", render_live_surface),
    )
    # The gitignored runtime inputs both renderers read (hook count from
    # settings.json; "Stable actions" from harness_config.json). Absent on a
    # clean checkout / CI -> skip (see class docstring).
    RUNTIME_INPUTS = (".claude/settings.json", "reports/harness_config.json")

    @pytest.mark.parametrize("rel,renderer", SURFACES, ids=[s[0] for s in SURFACES])
    def test_committed_file_byte_equals_renderer(self, rel, renderer):
        missing = [p for p in self.RUNTIME_INPUTS if not (REPO_ROOT / p).exists()]
        if missing:
            pytest.skip(
                f"{rel} byte-gate requires gitignored runtime inputs {missing} "
                f"(absent on a clean checkout / CI); this is a local drift gate "
                f"— see class docstring."
            )
        committed_path = REPO_ROOT / rel
        assert committed_path.exists(), (
            f"{rel} missing — run write_required_surface(Path('.')) and commit.")
        rendered = renderer(REPO_ROOT)
        committed = committed_path.read_text(encoding="utf-8")
        if rendered != committed:
            import difflib
            diff = "".join(list(difflib.unified_diff(
                committed.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                fromfile=f"{rel} (committed)",
                tofile=f"{renderer.__name__}() output",
                n=2,
            ))[:60])
            pytest.fail(
                f"{rel} does not match {renderer.__name__}() output. Regenerate "
                f"with:\n\n    python -c \"import sys; sys.path.insert(0, '.'); "
                f"from espalier.render_surface import write_required_surface; "
                f"from pathlib import Path; "
                f"write_required_surface(Path('.'))\"\n\n"
                f"If the renderer output looks wrong, fix upstream in "
                f"espalier.surface_contract / managed_inventory, then regenerate.\n\n"
                f"Diff:\n{diff}"
            )
