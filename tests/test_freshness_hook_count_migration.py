"""TP-56-A migration test: hook-count moved from NUMERIC_CONTRACTS
to the freshness manifest.

This is the proof-of-model for the document freshness signal:
the pre-existing `name="entry hooks deployed"` `NumericContract`
is retired, and the hook-count claim is now tracked via the
`.espalier/freshness.json` manifest with bound-path drift detection.

The three assertions in this file enforce the end-to-end migration:
(1) the literal name `entry hooks deployed` is absent from the
live `NUMERIC_CONTRACTS` tuple, (2) the freshness manifest at HEAD
contains a `hook-count` fragment with the resolved expected value,
(3) adding a fake 11th CANONICAL_HOOK_WIRING entry produces `stale`
state via the freshness scanner.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._live_tree import live_tree_copy_ignore


REPO_ROOT = Path(__file__).parent.parent
MANIFEST_PATH = REPO_ROOT / ".espalier" / "freshness.json"


class TestHookCountMigration:
    def test_entry_hooks_deployed_removed_from_numeric_contracts(self) -> None:
        from tests.test_documented_claims import NUMERIC_CONTRACTS
        names = {c.name for c in NUMERIC_CONTRACTS}
        assert "entry hooks deployed" not in names, (
            "The `entry hooks deployed` NumericContract was retired by "
            "TP-56-A; the hook-count claim now lives in the freshness "
            "manifest. Found it still present in NUMERIC_CONTRACTS — "
            "either TP-56-A was reverted incompletely or someone re-"
            "introduced the duplicate registry entry."
        )

    def test_hook_count_fragment_present_in_manifest_at_head(self) -> None:
        if not MANIFEST_PATH.is_file():
            pytest.fail(
                f"freshness manifest missing at {MANIFEST_PATH}; "
                "TP-56-A seeded the hook-count fragment — manifest "
                "should be committed."
            )
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        entry = manifest.get("fragments", {}).get("hook-count")
        assert entry is not None, (
            "hook-count fragment missing from freshness manifest"
        )
        assert entry["policy"] == "numeric-contract"
        assert entry["bound"] == [
            "espalier/harness_config.py::CANONICAL_HOOK_WIRING"
        ]
        from espalier.surface_contract import get_canonical_hook_scripts
        assert entry["expected_value"] == len(get_canonical_hook_scripts())
        assert entry["last_verified_sha"], "missing last_verified_sha"

    def test_manifest_expected_value_matches_live_canonical_hook_wiring(
        self,
    ) -> None:
        from espalier.surface_contract import get_canonical_hook_scripts
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        entry = manifest["fragments"]["hook-count"]
        assert entry["expected_value"] == len(get_canonical_hook_scripts()), (
            "Freshness manifest's hook-count expected_value drifted "
            "from live CANONICAL_HOOK_WIRING length. Either the hook "
            "count changed (re-pin: ESPALIER_MAINTENANCE_MODE=1 "
            "espalier freshness pin hook-count . --expected-value <N>) "
            "or the manifest was edited by hand."
        )

    def test_adding_canonical_hook_wiring_entry_yields_stale_state(
        self, tmp_path: Path
    ) -> None:
        """End-to-end drift signal: editing the bound path produces stale."""
        from espalier.freshness import scan_repo, pin_fragment

        test_repo = tmp_path / "repo"
        shutil.copytree(
            REPO_ROOT, test_repo,
            # A linked worktree under .claude/worktrees/ is left out whole: its
            # gitlink .git goes with the `.git` pattern, and the scanner then
            # read its docs as this tree's (DEF-1196, tests/_live_tree.py).
            ignore=live_tree_copy_ignore(
                ".git", ".venv", "__pycache__", "node_modules",
                "dist", "build", ".pytest_cache", ".mypy_cache",
                ".ruff_cache", "espalier_harness.egg-info",
                # Session state the harness's own hooks rewrite while a test
                # runs (`reports/` is on conftest's live-tree watch list for
                # that reason): a copytree over a file mid-rename raises. The
                # probe needs the docs, the engine and the manifest, not these.
                "reports", "cc", ".espalier-state", "results",
            ),
        )
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "-C", str(test_repo), "init", "-q"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(test_repo), "add", "-A"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "-C", str(test_repo), "commit", "-q", "-m", "fixture"],
            check=True, capture_output=True,
        )
        # TP-56-C: clear the carried-over manifest so the test
        # only deals with its own hook-count pin. Otherwise the 13
        # other freshness fragments retain their live-repo SHAs,
        # which don't exist in this freshly-init'd tmp repo and
        # break git_log_name_only's oldest_sha walk.
        (test_repo / ".espalier" / "freshness.json").write_text(
            '{"schema_version": 1, "fragments": {}}\n',
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "-C", str(test_repo), "add", "-A"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "-C", str(test_repo), "commit", "-q", "-m", "clear manifest"],
            check=True, capture_output=True,
        )
        pin_fragment("hook-count", test_repo, expected_value=12)  # TP-163: live count
        subprocess.run(
            ["git", "-C", str(test_repo), "add", "-A"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "-C", str(test_repo), "commit", "-q", "-m", "pin"],
            check=True, capture_output=True,
        )

        target = test_repo / "espalier" / "harness_config.py"
        body = target.read_text(encoding="utf-8")
        # The mutation lands INSIDE the bound symbol's region -- the line after
        # the declaration opens -- because a symbol-bound fragment drifts with
        # the symbol, not with its file (a comment appended at the end of the
        # file, the first cut's probe, is exactly the touch the scanner now
        # ignores). The first line-start occurrence is the declaration; the
        # name also appears in prose above it.
        decl = re.search(r"^CANONICAL_HOOK_WIRING\b[^\n]*\n", body, re.M)
        assert decl, "the bound symbol is not declared in the copied file"
        body = (
            body[:decl.end()]
            + "    # TP-56-A drift probe -- a line inside the bound symbol's region\n"
            + body[decl.end():]
        )
        target.write_text(body, encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(test_repo), "add", "-A"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "-C", str(test_repo), "commit", "-q", "-m", "probe"],
            check=True, capture_output=True,
        )

        states = scan_repo(test_repo)
        hook_count = next(
            (s for s in states if s.fragment.id == "hook-count"), None
        )
        assert hook_count is not None, (
            "hook-count fragment missing from scan_repo result"
        )
        assert hook_count.state == "stale", (
            f"Expected 'stale' after a commit touching CHW's bound "
            f"path; got {hook_count.state!r} with commits_since="
            f"{hook_count.commits_since}, message="
            f"{hook_count.message!r}"
        )
        assert hook_count.commits_since >= 1


class TestLiveTreeCopyKeepsTheWorktreeBoundary:
    """DEF-1196's scanner half, measured 2026-10-10: the copy above reds
    "duplicate fragment id 'hook-count'" beside a live `claude --worktree`
    session. The scanner's nested-repo prune holds on the live tree (a linked
    worktree's `.git` is a gitlink FILE, and the prune reads any `.git` entry);
    the copy's `.git` pattern dropped that file, so the worktree reached the
    scanner as plain docs. On a scratch tree, each layer earned on its own."""

    _MARKER = "<!-- espalier:fragment id=planted bound=a.py policy=weekly -->\n"

    def _plant(self, root: Path) -> Path:
        (root / "docs").mkdir(parents=True)
        (root / "docs" / "x.md").write_text(self._MARKER, encoding="utf-8")
        probe = root / ".claude" / "worktrees" / "probe"
        (probe / "docs").mkdir(parents=True)
        (probe / "docs" / "x.md").write_text(self._MARKER, encoding="utf-8")
        (probe / ".git").write_text("gitdir: /elsewhere/.git/worktrees/probe\n", encoding="utf-8")
        (root / ".claude" / "commands").mkdir(parents=True)
        (root / ".claude" / "commands" / "real.md").write_text("# real\n", encoding="utf-8")
        return root

    def test_the_scanner_prunes_the_worktree_on_the_live_tree(self, tmp_path: Path) -> None:
        from espalier.freshness import discover_fragments

        live = self._plant(tmp_path / "live")
        assert [f.source_path for f in discover_fragments(live)] == ["docs/x.md"]

    def test_a_copy_that_drops_git_alone_hands_the_scanner_the_worktree(self, tmp_path: Path) -> None:
        """The fixture's old shape, kept as the red the helper answers: without
        the gitlink, nothing in the copy marks the worktree as another checkout."""
        from espalier.freshness import FreshnessError, discover_fragments

        live = self._plant(tmp_path / "live")
        copy = tmp_path / "copy"
        shutil.copytree(live, copy, ignore=shutil.ignore_patterns(".git"))
        assert (copy / ".claude" / "worktrees" / "probe" / "docs" / "x.md").is_file()
        with pytest.raises(FreshnessError, match="duplicate fragment id 'planted'"):
            discover_fragments(copy)

    def test_the_live_tree_copy_ignore_leaves_the_worktree_out(self, tmp_path: Path) -> None:
        from espalier.freshness import discover_fragments

        live = self._plant(tmp_path / "live")
        copy = tmp_path / "copy"
        shutil.copytree(live, copy, ignore=live_tree_copy_ignore(".git"))
        assert not (copy / ".claude" / "worktrees" / "probe").exists()
        assert (copy / ".claude" / "commands" / "real.md").is_file()
        assert [f.source_path for f in discover_fragments(copy)] == ["docs/x.md"]
