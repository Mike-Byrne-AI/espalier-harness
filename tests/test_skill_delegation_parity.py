"""TP-50 — orphan-agent parity contract.

Every agent under ``.claude/agents/`` must be wired by at least one
skill / command / hook so it has an automatic delivery path. An agent
that exists but is never referenced by any wired surface loads as
token cost every session with no actionable trigger — this test
catches that drift early.

The scan looks at three surfaces for agent-name references:

1. ``.claude/skills/<name>/SKILL.md`` — delegate-style skills mention
   the agent by name in body prose.
2. ``.claude/commands/<name>.md`` — commands that delegate to agents
   mention them the same way.
3. ``tools/cc/hooks/*.py`` — hook scripts that nudge toward an agent
   (e.g. stop_gate's denial message naming ``code-reviewer`` as
   ``subagent_type='code-reviewer'``).

A loose substring match is used because the harness convention is
prose ("the code-reviewer subagent") beside the parameter spelling
(``subagent_type='<name>'``), not a structured field alone. False
positives are vanishingly unlikely because agent names are unusual
compound identifiers (e.g. ``architecture-analyst``).

The second contract here (DEF-713): no command, skill or agent body names
the subagent TOOL -- by its retired name (Task) or its current one (Agent,
since Claude Code 2.1.63). The harness spells a dispatch by the parameter,
``subagent_type='<name>'``, which survives a rename; a body that says "via
the Task tool" teaches an adopter's Claude the wrong spelling on the surface
that exists to teach spellings, and one that says "via the Agent tool" is
the same drift one rename later.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


def _agent_names() -> set[str]:
    agents_dir = REPO_ROOT / ".claude" / "agents"
    if not agents_dir.is_dir():
        return set()
    return {p.stem for p in agents_dir.glob("*.md")}


def _scan_surfaces() -> str:
    """Concatenate every wired surface body into a single haystack."""
    parts: list[str] = []
    for skill_md in (REPO_ROOT / ".claude" / "skills").rglob("SKILL.md"):
        parts.append(skill_md.read_text(encoding="utf-8"))
    for cmd_md in (REPO_ROOT / ".claude" / "commands").glob("*.md"):
        parts.append(cmd_md.read_text(encoding="utf-8"))
    for hook_py in (REPO_ROOT / "tools" / "cc" / "hooks").glob("*.py"):
        parts.append(hook_py.read_text(encoding="utf-8"))
    return "\n".join(parts)


pytestmark = [pytest.mark.contract]


class TestOrphanAgentParity:
    def test_every_agent_invoked_by_a_wired_surface(self):
        agents = _agent_names()
        assert agents, "expected .claude/agents/*.md to exist"
        haystack = _scan_surfaces()
        orphans = sorted(name for name in agents if name not in haystack)
        assert not orphans, (
            "agents have no wired invocation in skills / commands / hooks; "
            "add a delegation skill or command body reference so they have an "
            f"automatic delivery path: {orphans}"
        )

    def test_every_agent_invoked_outside_its_own_definition(self):
        """An agent referencing itself (in its own file) does not count."""
        agents = _agent_names()
        for agent in sorted(agents):
            haystack_parts: list[str] = []
            for skill_md in (REPO_ROOT / ".claude" / "skills").rglob("SKILL.md"):
                haystack_parts.append(skill_md.read_text(encoding="utf-8"))
            for cmd_md in (REPO_ROOT / ".claude" / "commands").glob("*.md"):
                haystack_parts.append(cmd_md.read_text(encoding="utf-8"))
            for hook_py in (REPO_ROOT / "tools" / "cc" / "hooks").glob("*.py"):
                haystack_parts.append(hook_py.read_text(encoding="utf-8"))
            haystack = "\n".join(haystack_parts)
            assert agent in haystack, (
                f"agent {agent!r} has no off-file invocation; even self-mentions "
                f"in its own .md don't count because the scan does not read "
                f".claude/agents/. Add a delegation skill or command body "
                f"reference."
            )


# The subagent tool by NAME -- the retired one (Task) or the current one
# (Agent). A body that names the tool at all spells a dispatch in the way that
# does not survive the next rename; the parameter spelling is the contract.
# Whitespace-normalised, so a hard-wrapped "Task\n   tool" is seen, and so are
# `Task (`, `Task-tool` and `Task tools`; ordinary lower-case "task" prose and
# "the X agent" stay out.
_TOOL_NAME_RE = re.compile(r"\b(?:Task|Agent)\s*\(|\b(?:Task|Agent)[-\s]+tools?\b")


def _wired_bodies() -> list[Path]:
    """The three markdown surfaces an adopter's Claude reads as instructions.

    Hook message templates are the fourth wired surface; their dispatch
    spelling is gated by tests/test_denial_reason_actionability.py::
    TestAgentDispatchIsSpelledOneWay over the derived template registry, not
    here -- hook SOURCE carries history comments that name the old tool as a
    record, and a record is not an instruction.
    """
    root = REPO_ROOT / ".claude"
    return sorted([
        *(root / "skills").rglob("SKILL.md"),
        *(root / "commands").glob("*.md"),
        *(root / "agents").glob("*.md"),
    ])


class TestNoBodyNamesTheSubagentTool:
    def test_no_wired_body_names_the_tool(self):
        offenders: list[str] = []
        for path in _wired_bodies():
            text = path.read_text(encoding="utf-8")
            for m in _TOOL_NAME_RE.finditer(text):
                lineno = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {m.group(0)!r}")
        assert not offenders, (
            "a command, skill or agent body names the subagent tool; dispatch by "
            "name -- subagent_type='<name>' -- instead:\n  " + "\n  ".join(offenders)
        )

    def test_the_pattern_fires_and_stays_narrow(self):
        for hit in (
            "Launch it via the Task tool with:", "dispatch it via the Agent tool",
            "Task(subagent_type='x')", "Agent(subagent_type='x')", "Task (subagent_type='x')",
            "via the Task\n   tool (wrapped)", "the Task-tool", "Task tools are gone",
            "the Task tool's rename",
        ):
            assert _TOOL_NAME_RE.search(hit), hit
        for miss in (
            "a task list, then the next task", "dispatch the subagent (subagent_type='code-reviewer')",
            "an agent tool belt", "the failure-mode-reviewer agent", "SubagentStart",
        ):
            assert not _TOOL_NAME_RE.search(miss), miss

    def test_the_scan_sees_every_body_kind(self):
        bodies = _wired_bodies()
        kinds = {"skills" if p.name == "SKILL.md" else p.parent.name for p in bodies}
        assert kinds == {"skills", "commands", "agents"}, kinds
        skill_dirs = [d for d in (REPO_ROOT / ".claude" / "skills").iterdir() if d.is_dir()]
        assert len([p for p in bodies if p.name == "SKILL.md"]) == len(skill_dirs) >= 1
