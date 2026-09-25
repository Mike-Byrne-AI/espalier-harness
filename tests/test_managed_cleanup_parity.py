"""TP-04 §7 — init↔clean parity tests.

Pins the end-to-end cleanup contract: rerun init writes a known
surface; ``clean-generated`` then removes managed files (marker-
identified) while preserving unmarked user files; empty managed
directories are pruned only when safe (no surviving user content).
Without this contract a drift between init's marker-writing and
cleanup's marker-recognition could silently leak orphaned files
into the adopter repo on every upgrade cycle, OR cleanup could
over-reach and delete user customizations that init never wrote.
Both failure modes are recoverable only via git, and only if the
adopter notices the delta.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

# Marker assignment lives in tests/conftest.py::_MARKER_RULES.


def _make_target(tmp_path: Path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    (target / "README.md").write_text("# target\n", encoding="utf-8")
    subprocess.check_call(["git", "init", "--quiet"], cwd=str(target))
    return target


def _run_init(target: Path) -> None:
    subprocess.check_call(
        [sys.executable, "-m", "espalier.cli", "init", str(target)],
        timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _run_clean(target: Path, *, execute: bool = False) -> dict:
    cmd = [sys.executable, "-m", "espalier.cli", "clean-generated", str(target)]
    if execute:
        cmd.append("--execute")
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=60, check=True, encoding="utf-8",
    )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Pack §7 — init → clean parity flow
# ---------------------------------------------------------------------------


class TestInitToCleanParity:
    """init -> clean parity flow. Post-TP-31, `espalier init` deploys no
    bundled commands / agents / skills, so the cleanup contract is now
    user-file-centric: cleanup must preserve user-authored files dropped
    in .claude/{commands,agents,skills}/, and the user-authoring dirs
    themselves must be created by the user (not the harness)."""

    def test_dry_run_classifies_user_files_as_preserved(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)

        # User authors files in user-authoring dirs that init no longer
        # populates. Each dir is created on demand by the user.
        (target / ".claude" / "commands").mkdir(parents=True, exist_ok=True)
        (target / ".claude" / "commands" / "my-user-cmd.md").write_text(
            "# user only\n", encoding="utf-8",
        )
        (target / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
        (target / ".claude" / "agents" / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: x\nmodel: opus\n---\n# user\n",
            encoding="utf-8",
        )
        skill_dir = target / ".claude" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: x\n---\n# user\n",
            encoding="utf-8",
        )

        report = _run_clean(target, execute=False)

        # Unmarked user files appear in preserved_user_files
        preserved = set(report["preserved_user_files"])
        assert ".claude/commands/my-user-cmd.md" in preserved
        assert ".claude/agents/my-agent.md" in preserved
        assert ".claude/skills/my-skill/SKILL.md" in preserved
        # Local runtime is reported separately
        runtime = set(report["preserved_local_runtime"])
        assert ".claude/settings.json" in runtime
        assert ".espalier/integrity.json" in runtime

    def test_execute_preserves_user_files(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)

        (target / ".claude" / "commands").mkdir(parents=True, exist_ok=True)
        user_cmd = target / ".claude" / "commands" / "my-user-cmd.md"
        user_cmd.write_text("# user\n", encoding="utf-8")

        _run_clean(target, execute=True)

        assert user_cmd.exists(), (
            "user-authored command was incorrectly removed"
        )

    def test_local_runtime_files_not_removed(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        _run_clean(target, execute=True)
        # Runtime files must still be on disk after cleanup
        assert (target / ".claude" / "settings.json").exists()
        assert (target / ".espalier" / "integrity.json").exists()
        assert (target / "reports" / "harness_config.json").exists()
        assert (target / "reports" / "repo_fingerprint.json").exists()

    def test_user_file_blocks_dir_pruning(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        # Drop a user file in a user-authoring dir; cleanup must NOT prune
        # the parent dir because it still contains the user file.
        (target / ".claude" / "commands").mkdir(parents=True, exist_ok=True)
        (target / ".claude" / "commands" / "my-user-cmd.md").write_text(
            "# user\n", encoding="utf-8",
        )
        _run_clean(target, execute=True)
        assert (target / ".claude" / "commands" / "my-user-cmd.md").exists()
        assert (target / ".claude" / "commands").is_dir()


# ---------------------------------------------------------------------------
# Idempotence — second cleanup is a no-op
# ---------------------------------------------------------------------------


class TestCleanupIdempotence:
    def test_second_cleanup_is_no_op(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        _run_clean(target, execute=True)
        # Second run on the post-cleanup state: nothing left to delete
        report = _run_clean(target, execute=True)
        assert report["status"] == "pass"
        assert report["deleted"] == []
