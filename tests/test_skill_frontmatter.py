"""Skill frontmatter parity contracts.

Pins the rule that Claude Code keys skills by directory name, so
the frontmatter ``name:`` field MUST match the parent directory
name for trigger routing, UI display, and harness introspection
to agree. Pinned across THREE mirrors so a hand-edit to any one
of them fires the contract immediately:

  - ``.claude/skills/``                          (runtime)
  - ``espalier/assets/claude/skills/``           (asset SoT)
  - ``examples/dogfooding/.claude/skills/``      (dogfooding mirror)

Without this contract a typo in any single mirror's frontmatter
would silently make the skill un-triggerable in that mirror
(Claude Code routes by directory name but looks up the body by
frontmatter ``name``), and the bug would surface only when
someone tries to use the skill in a deployment of the wrong
mirror — a debugging dead-end if the typo isn't surfaced
mechanically.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent

SKILL_ROOTS = [
    REPO_ROOT / ".claude" / "skills",
    REPO_ROOT / "espalier" / "assets" / "claude" / "skills",
    REPO_ROOT / "examples" / "dogfooding" / ".claude" / "skills",
]


_NAME_RE = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)


def _all_skill_files() -> list[Path]:
    files: list[Path] = []
    for root in SKILL_ROOTS:
        if root.is_dir():
            files.extend(sorted(root.glob("*/SKILL.md")))
    return files


def test_skill_discovery_is_non_empty() -> None:
    """TP-190 floor: the parametrized contracts below iterate `_all_skill_files()`;
    if discovery returned [] (renamed SKILL_ROOTS, moved skills) every
    parametrized test would pass VACUOUSLY (zero cases). Assert the corpus is
    non-empty so the earn-the-red can't be silently neutered — mirrors the floor
    in test_agent_frontmatter."""
    assert _all_skill_files(), (
        "skill discovery is empty — _all_skill_files() found no */SKILL.md under "
        f"{SKILL_ROOTS}; the parametrized skill contracts would pass vacuously"
    )


@pytest.mark.parametrize(
    "skill_path",
    _all_skill_files(),
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_skill_name_equals_directory_name(skill_path: Path) -> None:
    """Every SKILL.md's `name:` frontmatter MUST equal its parent dir name.

    Class-of-bug guard: TP-82's blueprint-authoring rename surfaced
    the invariant. Pinned for every skill across all three mirrors.
    """
    text = skill_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        pytest.fail(
            f"{skill_path.relative_to(REPO_ROOT)} is missing the "
            f"YAML frontmatter `---` fence -- Claude Code's skill "
            f"loader requires it; the harness contract requires it"
        )
    parts = text.split("---", 2)
    if len(parts) < 3:
        pytest.fail(
            f"{skill_path.relative_to(REPO_ROOT)} has no closing "
            f"`---` fence -- frontmatter is unterminated"
        )
    frontmatter = parts[1]
    match = _NAME_RE.search(frontmatter)
    assert match is not None, (
        f"{skill_path.relative_to(REPO_ROOT)} has no `name:` "
        f"frontmatter line"
    )
    declared = match.group(1)
    dir_name = skill_path.parent.name
    assert declared == dir_name, (
        f"{skill_path.relative_to(REPO_ROOT)}: frontmatter "
        f"`name: {declared}` does not match parent directory "
        f"`{dir_name}`. Claude Code routes by directory name; the "
        f"frontmatter must agree."
    )
