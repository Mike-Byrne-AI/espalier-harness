"""TP-28: ``espalier init`` summary must match filesystem reality.

Pins the rule that every count the init summary prints comes from
a glob of the actual deployed directory, not from a hardcoded
constant. Pre-TP-28 the output said ``Agents: N deployed by
default`` with a hardcoded ``N`` that did not match what was
actually written to disk — the operator had no way to detect the
discrepancy and trusted a stale claim. This test binds each
granular install label to a live filesystem count and confirms
the recommendation surface is shown separately when no agent
files are installed. Without this contract, future label additions
could silently drift back into hardcoded-count territory and
mislead every adopter about what init actually did.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests._git_oracle import require_is_gitignored

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_init(tmp_path: Path) -> str:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    result = subprocess.run(
        [sys.executable, "-m", "espalier.cli", "init", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT, encoding="utf-8",
    )
    return result.stdout


def _parse_labels(stdout: str) -> dict[str, int]:
    labels: dict[str, int] = {}
    for match in re.finditer(
        r"^\s*(Agent files|Command files|Skill files|"
        r"Hook entry scripts|Hook helper scripts):\s*(\d+)",
        stdout,
        re.MULTILINE,
    ):
        labels[match.group(1)] = int(match.group(2))
    return labels


@pytest.mark.integration
def test_each_label_matches_filesystem(tmp_path):
    out = _run_init(tmp_path)
    labels = _parse_labels(out)

    agents_dir = tmp_path / ".claude" / "agents"
    commands_dir = tmp_path / ".claude" / "commands"
    skills_dir = tmp_path / ".claude" / "skills"
    hooks_dir = tmp_path / "tools" / "cc" / "hooks"

    fs_agents = len(list(agents_dir.glob("*.md"))) if agents_dir.is_dir() else 0
    fs_commands = len(list(commands_dir.glob("*.md"))) if commands_dir.is_dir() else 0
    fs_skills = len(list(skills_dir.rglob("SKILL.md"))) if skills_dir.is_dir() else 0

    assert labels.get("Agent files") == fs_agents, (
        f"'Agent files' label {labels.get('Agent files')} "
        f"!= filesystem count {fs_agents}\n--- init stdout ---\n{out}"
    )
    assert labels.get("Command files") == fs_commands, (
        f"'Command files' label {labels.get('Command files')} "
        f"!= filesystem count {fs_commands}"
    )
    assert labels.get("Skill files") == fs_skills, (
        f"'Skill files' label {labels.get('Skill files')} "
        f"!= filesystem count {fs_skills}"
    )
    if hooks_dir.is_dir():
        total_hooks = len(list(hooks_dir.glob("*.py")))
        summed = labels.get("Hook entry scripts", 0) + labels.get("Hook helper scripts", 0)
        assert summed == total_hooks, (
            f"Hook entry+helper labels ({summed}) don't sum to filesystem "
            f"total ({total_hooks})"
        )


@pytest.mark.integration
def test_recommended_count_surfaced_alongside_installed(tmp_path):
    """Post-TP-50 init deploys agents by default. The recommendation count
    is informational (driven by the profile, separate from the
    filesystem-witnessed installed count). Both must appear so operators
    can compare "what shipped" against "what this profile recommends."
    """
    out = _run_init(tmp_path)
    assert "Recommended active agents" in out, (
        "init must surface the recommendation count alongside installed "
        "counts so operators can compare profile vs filesystem.\n"
        "--- init stdout ---\n" + out
    )


@pytest.mark.integration
def test_no_lying_agents_deployed_line(tmp_path):
    """The pre-TP-28 `Agents: N deployed` line must not re-appear in any
    form that asserts a count that contradicts the filesystem.
    """
    out = _run_init(tmp_path)
    # Catch the legacy phrasing if it slips back. The granular label
    # `Agent files: N` is allowed; the bare `Agents: N deployed by default`
    # phrasing is not.
    assert "deployed by default" not in out, (
        "Legacy 'deployed by default' phrasing reintroduced. The granular "
        "'Agent files: N' label is the SoT now.\n--- init stdout ---\n" + out
    )


@pytest.mark.integration
def test_a_recommendation_without_a_packaged_body_is_named(tmp_path):
    """DEF-766 (TP-449 Tier 2, 2026-09-12): on an API repo the plan recommends
    `api-reviewer`, an agent no release ships a body for; the count line said
    4 beside `Agent files: 7` and nothing said one of the four is not on disk.
    The summary now names the bodiless recommendations under the count; since
    2026-10-06 they are suggestions the plan saves apart, so the count is the
    agents that have a body."""
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )
    out = _run_init(tmp_path)
    match = re.search(r"Recommended active agents \(for this profile\): (\d+)", out)
    assert match and int(match.group(1)) >= 1, out
    assert "Suggested agents" in out and "api-reviewer" in out, out
    assert not (tmp_path / ".claude" / "agents" / "api-reviewer.md").exists()


@pytest.mark.integration
def test_a_plain_repo_prints_no_bodiless_line(tmp_path):
    out = _run_init(tmp_path)
    assert "Suggested agents" not in out, out


@pytest.mark.integration
def test_the_summary_names_the_per_machine_homes_git_really_ignores(tmp_path):
    """The epilogue names the homes init keeps on this machine (DEF-1105): the
    blueprint chain /handoff records into, and where a kept decision goes. Each
    `cc/` path the line names is one git ignores in the init'd tree, so the line
    never calls a committed path per-machine."""
    out = _run_init(tmp_path)
    line = next((ln for ln in out.splitlines() if "cc/blueprints/" in ln and "this machine" in ln), "")
    assert line, "no epilogue line names cc/blueprints/ as this machine's"
    assert "ESPALIER_MEMORY.md" in line, line
    named = re.findall(r"cc/[A-Za-z0-9_.]+/?", line)
    assert "cc/blueprints/" in named, line
    for rel in named:
        probe = rel + ("probe" if rel.endswith("/") else "")
        assert require_is_gitignored(tmp_path, probe), (
            f"{rel} is named per-machine but git does not ignore it: {line}"
        )


@pytest.mark.integration
def test_a_home_the_adopter_commits_is_never_called_per_machine(tmp_path):
    """An adopter who already commits ``cc/GOAL.md`` has init withhold that
    entry (it would protect nothing), so the epilogue's per-machine line must
    not name it: the line reads what git ignores in the tree, not the constant
    (a reviewer drove the old line naming a committed GOAL.md gitignored)."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "cc").mkdir()
    (tmp_path / "cc" / "GOAL.md").write_text("# our goal, committed\n", encoding="utf-8")
    subprocess.run(["git", "add", "cc/GOAL.md"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "-q", "-m", "goal"], cwd=tmp_path, check=True)
    result = subprocess.run(
        [sys.executable, "-m", "espalier.cli", "init", str(tmp_path)],
        capture_output=True, text=True, check=True, cwd=REPO_ROOT, encoding="utf-8",
    )
    line = next((ln for ln in result.stdout.splitlines()
                 if "cc/blueprints/" in ln and "this machine" in ln), "")
    assert line, "the per-machine line went missing for the homes git does ignore"
    assert "cc/GOAL.md" not in line, (
        f"a committed cc/GOAL.md is named as staying on this machine: {line}"
    )
