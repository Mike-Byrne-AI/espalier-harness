"""TP-50 — asset shipping contract.

``espalier init`` deploys agents / commands / skills from
``espalier/assets/claude/<kind>/`` with TP-03 marker discipline. This
suite pins the deploy positive contract (counts + parity with the
packaged inventory) and the marker-aware regeneration policy (user-
edited files preserved on rerun).

Adjacent suites:
- ``test_init_managed_markers.py``  marker placement + ownership tally
- ``test_package_resource_parity.py`` packaged-inventory cardinality
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests._surface_expected import (
    EXPECTED_AGENT_COUNT_MIN,
    EXPECTED_COMMAND_COUNT,
    EXPECTED_SKILL_COUNT,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_CLAUDE = REPO_ROOT / "espalier" / "assets" / "claude"


def _make_target(tmp_path: Path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    (target / "README.md").write_text("# target\n", encoding="utf-8")
    subprocess.check_call(["git", "init", "--quiet"], cwd=str(target))
    return target


def _run_init(target: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "espalier.cli", "init", str(target)]
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=120, check=True, encoding="utf-8",
    )


pytestmark = [pytest.mark.integration]


class TestAssetShippingDeploy:
    """``espalier init`` deploys the full asset tree (every packaged
    agent / command / skill lands). The harness-dev deploy tier was
    retired, so every init deploys everything.
    """

    def test_agent_count_matches_floor(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        agents = sorted((target / ".claude" / "agents").glob("*.md"))
        assert len(agents) >= EXPECTED_AGENT_COUNT_MIN

    def test_command_count_matches_expected(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        commands = sorted((target / ".claude" / "commands").glob("*.md"))
        assert len(commands) == EXPECTED_COMMAND_COUNT

    def test_skill_count_matches_expected(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        skills = sorted((target / ".claude" / "skills").rglob("SKILL.md"))
        assert len(skills) == EXPECTED_SKILL_COUNT


class TestAssetParity:
    """Each shipped asset has a deploy target; each deploy target maps to
    an asset. The two trees stay in lock-step so an asset added without a
    matching deploy entry — or vice versa — surfaces as a test failure."""

    def _asset_rel_paths(self, kind: str) -> set[str]:
        base = ASSETS_CLAUDE / kind
        if not base.is_dir():
            return set()
        if kind == "skills":
            return {p.relative_to(base).as_posix() for p in base.rglob("SKILL.md")}
        return {p.name for p in base.glob("*.md")}

    def _deployed_rel_paths(self, target: Path, kind: str) -> set[str]:
        base = target / ".claude" / kind
        if not base.is_dir():
            return set()
        if kind == "skills":
            return {p.relative_to(base).as_posix() for p in base.rglob("SKILL.md")}
        return {p.name for p in base.glob("*.md")}

    @pytest.mark.parametrize("kind", ["agents", "commands", "skills"])
    def test_every_asset_lands_at_target(self, tmp_path, kind):
        target = _make_target(tmp_path)
        _run_init(target)
        asset_rels = self._asset_rel_paths(kind)
        deployed_rels = self._deployed_rel_paths(target, kind)
        missing = asset_rels - deployed_rels
        assert not missing, (
            f"asset files not deployed by init for {kind}: {sorted(missing)}"
        )

    @pytest.mark.parametrize("kind", ["agents", "commands", "skills"])
    def test_no_orphan_target_without_asset(self, tmp_path, kind):
        target = _make_target(tmp_path)
        _run_init(target)
        asset_rels = self._asset_rel_paths(kind)
        deployed_rels = self._deployed_rel_paths(target, kind)
        extra = deployed_rels - asset_rels
        assert not extra, (
            f"target {kind}/ has files not present in assets/claude/{kind}/: "
            f"{sorted(extra)}"
        )


class TestReinitPreservesUserEdits:
    """Marker-aware regeneration: managed copies refresh; user edits stay."""

    def test_user_edited_agent_preserved_on_reinit(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        # Drop the marker by overwriting with frontmatter-only user content.
        user_path = target / ".claude" / "agents" / "test-writer.md"
        user_content = "---\nname: test-writer\n---\n\nUSER OVERRIDE — no marker\n"
        user_path.write_text(user_content, encoding="utf-8")
        result = _run_init(target)
        assert user_path.read_text(encoding="utf-8") == user_content, (
            "user-edited agent was clobbered by reinit; expected preserve"
        )
        # The summary must surface a skipped_user_files count >= 1 so
        # operators can see that init left something alone.
        assert "skipped_user_files" in result.stdout, (
            "init summary did not surface 'skipped_user_files' tally"
        )

    def test_managed_agent_regenerated_on_reinit(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        managed_path = target / ".claude" / "agents" / "code-reviewer.md"
        before = managed_path.read_text(encoding="utf-8")
        # Touch but keep the marker so it stays "managed" — regeneration
        # should rewrite the file to the asset content verbatim.
        modified = before.replace("Espalier-Harness", "ESPALIER_TEST_MARKER")
        managed_path.write_text(modified, encoding="utf-8")
        _run_init(target)
        after = managed_path.read_text(encoding="utf-8")
        assert "ESPALIER_TEST_MARKER" not in after, (
            "managed agent (with marker) was NOT regenerated on reinit"
        )

    def test_summary_tally_counts_user_skip(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        user_path = target / ".claude" / "commands" / "commit.md"
        user_path.write_text("# user-rewritten\n", encoding="utf-8")
        result = _run_init(target)
        # The tally line is rendered when any of created/updated/skipped > 0:
        # `created: N  updated_managed: N  skipped_user_files: N`
        out = result.stdout
        assert "skipped_user_files: 0" not in out, (
            "tally still reports skipped_user_files: 0 despite a user edit"
        )
