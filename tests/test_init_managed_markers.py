"""TP-03 Phase 5 — init upgrade behavior tests.

Pins the Pack §6 cases against the silent-overwrite failure mode:
rerunning ``espalier init`` must regenerate managed files (those
carrying the ``espalier:managed`` marker) while preserving any
unmarked user files at the same paths. Frontmatter validity must
also be preserved on the regenerated bodies, and the per-class
ownership tally must surface in ``deploy_harness``'s return dict
so the operator can audit what changed. Without this contract,
an init regression could silently overwrite adopter user files at
the marker boundary, destroying customizations the user expected
to survive an upgrade.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Marker assignment lives in tests/conftest.py::_MARKER_RULES.


def _make_target(tmp_path: Path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    (target / "README.md").write_text("# target\n", encoding="utf-8")
    subprocess.check_call(["git", "init", "--quiet"], cwd=str(target))
    return target


def _run_init(target: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "espalier.cli", "init", str(target)],
        capture_output=True, text=True, timeout=120, check=True, encoding="utf-8",
    )


def _frontmatter_close(text: str) -> int:
    """Index immediately past the closing ---\\n delimiter, or -1."""
    if not text.startswith("---\n"):
        return -1
    end = text.find("\n---\n", 4)
    return end + len("\n---\n") if end >= 0 else -1


# ---------------------------------------------------------------------------
# First init writes managed marker
# ---------------------------------------------------------------------------


class TestFirstInitWritesMarker:
    def test_command_files_carry_marker(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        for md in (target / ".claude" / "commands").glob("*.md"):
            content = md.read_text(encoding="utf-8")
            assert "espalier:managed" in content, (
                f"{md.name} missing espalier:managed marker"
            )

    def test_skill_files_carry_marker(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        for md in (target / ".claude" / "skills").glob("*/SKILL.md"):
            content = md.read_text(encoding="utf-8")
            assert "espalier:managed" in content, (
                f"{md.name} missing espalier:managed marker"
            )

    def test_rich_agent_files_carry_marker_after_frontmatter(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        for md in (target / ".claude" / "agents").glob("*.md"):
            content = md.read_text(encoding="utf-8")
            assert "espalier:managed" in content, (
                f"{md.name} missing espalier:managed marker"
            )
            # TP-03 §2: marker must NOT precede frontmatter on agents.
            if content.startswith("---\n"):
                end = _frontmatter_close(content)
                assert end > 0, f"{md.name} frontmatter is malformed"
                # Marker text appears at or after the close, not before.
                marker_pos = content.find("espalier:managed")
                assert marker_pos >= end, (
                    f"{md.name} marker at byte {marker_pos} precedes "
                    f"frontmatter close at byte {end} — frontmatter validity broken"
                )


# ---------------------------------------------------------------------------
# Rerun init: regenerate managed files
# ---------------------------------------------------------------------------


class TestRerunRegeneratesManaged:
    def test_modified_cc_pack_manifest_overwritten(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        manifest = target / "cc" / "PACK_MANIFEST.txt"
        manifest.write_text(
            manifest.read_text(encoding="utf-8") + "\nuser-injected-line\n",
            encoding="utf-8",
        )
        _run_init(target)
        fresh = manifest.read_text(encoding="utf-8")
        assert "user-injected-line" not in fresh, (
            "managed PACK_MANIFEST was not regenerated on rerun"
        )


# ---------------------------------------------------------------------------
# Rerun init: preserve unmarked user files
# ---------------------------------------------------------------------------


class TestRerunPreservesUserFiles:
    def test_user_claude_md_without_marker_preserved(self, tmp_path):
        """TP-31: user-owned CLAUDE.md (no marker) must survive init rerun."""
        target = _make_target(tmp_path)
        _run_init(target)
        claude_md = target / "CLAUDE.md"
        # Strip the marker — user has taken ownership
        claude_md.write_text("# fully user-owned, no marker\n", encoding="utf-8")
        _run_init(target)
        assert claude_md.read_text(encoding="utf-8") == "# fully user-owned, no marker\n"


# ---------------------------------------------------------------------------
# Tally — created/updated_managed/skipped_user_files
# ---------------------------------------------------------------------------


class TestDeployTally:
    """deploy_harness's return dict surfaces the ownership tally so init
    can print a clear, low-noise summary."""

    def test_first_init_all_created(self, tmp_path):
        target = _make_target(tmp_path)
        result = _run_init(target)
        # The summary line is in stdout: "  created: N  updated_managed: N  skipped_user_files: N"
        out = result.stdout
        assert "created:" in out and "updated_managed:" in out
        # First init: nothing pre-existed → updated_managed: 0, skipped_user_files: 0
        assert "updated_managed: 0" in out
        assert "skipped_user_files: 0" in out

    def test_first_init_tally_reconciles_with_deployed(self, tmp_path):
        """The written-ownership buckets (created + updated_managed + other)
        must partition the ``Deployed: N files`` count exactly. On a fresh init
        every deployed file was written, so the tally printed directly beneath
        ``Deployed`` cannot silently under-count it — the regression this pins is
        a 73-vs-94 gap where 21 append-only writes (settings.json, CLAUDE.md,
        ESPALIER_MEMORY.md, the seed docs, integrity.json, the surface-gate
        report) never reached the ``created`` bucket."""
        target = _make_target(tmp_path)
        out = _run_init(target).stdout
        deployed = int(re.search(r"Deployed:\s+(\d+)\s+files", out).group(1))
        created = int(re.search(r"\bcreated:\s+(\d+)", out).group(1))
        updated = int(re.search(r"\bupdated_managed:\s+(\d+)", out).group(1))
        m_other = re.search(r"\bother:\s+(\d+)", out)
        other = int(m_other.group(1)) if m_other else 0
        assert created + updated + other == deployed, (
            f"written buckets created({created}) + updated_managed({updated}) + "
            f"other({other}) must sum to Deployed({deployed}); the tally does not "
            f"partition the deploy count\n{out}"
        )

    def test_reinit_tally_reconciles_with_deployed(self, tmp_path):
        """The partition holds on a RE-init too. ``skipped_no_drift`` /
        ``skipped_user_files`` are disjoint from ``deployed`` (files considered
        but not written), so the residual ``other = deployed - created -
        updated_managed`` never goes negative — the reconcile is not a
        fresh-init coincidence where those skip buckets happen to be zero."""
        target = _make_target(tmp_path)
        _run_init(target)                       # first init lands the harness
        out = _run_init(target).stdout          # re-init: most files now skipped
        deployed = int(re.search(r"Deployed:\s+(\d+)\s+files", out).group(1))
        created = int(re.search(r"\bcreated:\s+(\d+)", out).group(1))
        updated = int(re.search(r"\bupdated_managed:\s+(\d+)", out).group(1))
        m_other = re.search(r"\bother:\s+(\d+)", out)
        other = int(m_other.group(1)) if m_other else 0
        assert created + updated + other == deployed, (
            f"re-init written buckets created({created}) + updated_managed"
            f"({updated}) + other({other}) must sum to Deployed({deployed})\n{out}"
        )

    def test_rerun_with_unmarked_file_reports_skip(self, tmp_path):
        """TP-31: stripping the managed marker from cc/PACK_MANIFEST.txt promotes
        it to a user file; the next init must preserve it and count it as skipped."""
        target = _make_target(tmp_path)
        _run_init(target)
        manifest = target / "cc" / "PACK_MANIFEST.txt"
        # Strip the managed marker -- init treats unmarked files as user-owned
        manifest.write_text("# user owned\n", encoding="utf-8")
        result = _run_init(target)
        out = result.stdout
        # At least one skipped_user_file (the manifest we just took over)
        for line in out.splitlines():
            if "skipped_user_files:" in line:
                token = line.split("skipped_user_files:")[1].strip().split()[0]
                assert int(token) >= 1, (
                    f"expected skipped_user_files >= 1, got {token}"
                )
                break
        else:
            pytest.fail(f"summary line not found in stdout: {out!r}")


# ---------------------------------------------------------------------------
# Frontmatter validity preserved across re-init cycles
# ---------------------------------------------------------------------------


class TestFrontmatterValidityAcrossRerun:
    def test_agent_frontmatter_remains_valid_after_three_inits(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        _run_init(target)
        _run_init(target)
        for md in (target / ".claude" / "agents").glob("*.md"):
            content = md.read_text(encoding="utf-8")
            if not content.startswith("---\n"):
                continue
            end = _frontmatter_close(content)
            assert end > 0, (
                f"{md.name} frontmatter close missing after rerun"
            )
            block = content[4:end - len("\n---\n")]
            # Required fields still parseable as top-level YAML keys
            assert any(line.startswith("name:") for line in block.splitlines())
            assert any(line.startswith("description:") for line in block.splitlines())


# ---------------------------------------------------------------------------
# Settings.json sentinel (TP-OSS-01 — preserved through TP-03)
# ---------------------------------------------------------------------------


class TestSettingsSentinel:
    def test_settings_carries_json_sentinel(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        settings = json.loads(
            (target / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        assert settings.get("_espalier_managed") is True


class TestReinitNamesTheRegeneratedFile:
    """DEF-774: a hand edit to a marked file is gone after re-init, and the
    summary said ``updated_managed: 1`` with the path nowhere -- the deploy
    loop had collected the paths and the printer dropped them. The path IS
    the next step (what changed, what was lost), so the block names it."""

    def test_reinit_names_the_regenerated_file_beside_the_count(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        edited = target / ".claude" / "commands" / "status.md"
        edited.write_text(edited.read_text(encoding="utf-8") + "\nmy edit\n", encoding="utf-8")
        out = _run_init(target).stdout
        assert "updated_managed: 1" in out, out
        assert "regenerated from the packaged copy" in out, out
        assert ".claude/commands/status.md" in out, out
        assert "my edit" not in edited.read_text(encoding="utf-8")

    def test_fresh_init_prints_no_regenerated_line(self, tmp_path):
        target = _make_target(tmp_path)
        out = _run_init(target).stdout
        assert "updated_managed: 0" in out, out
        assert "regenerated from the packaged copy" not in out, out
