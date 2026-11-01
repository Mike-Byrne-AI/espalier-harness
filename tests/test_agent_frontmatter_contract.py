"""TP-36: pin each bundled agent's capability tier.

A future change adding `Write` to `code-reviewer.md` would be a silent
capability escalation if not caught. This test makes the tier explicit:
each agent declares its tier in `AGENT_TIER`, and the tier is the set of
tools the agent's frontmatter grants.

A tools line is a list of tool names: Claude Code documents the field that
way, and the one specifier its subagent page names is `Agent(...)`. A
command pattern such as `Bash(git *)` is not documented there and was
measured inert on Claude Code 2.1.314: in bypass mode a subagent holding only
such entries ran `date`, `echo` and `ls`, and in default mode its `git tag`
asked exactly as a plain `Bash` grant's did (DEF-1107). So a pattern read as
a narrowed grant it never was; the contract forbids every specifier but
`Agent(...)`, and each body that grants `Bash` says where its scope is set.

`TestRootMirrorParity` already guarantees `.claude/agents/` and
`examples/dogfooding/.claude/agents/` are byte-identical, so checking
one location is sufficient.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from espalier._safe_walk import visible
from tests._live_tree import checkout_glob

REPO_ROOT = Path(__file__).resolve().parent.parent

AGENT_DIRS = [
    REPO_ROOT / ".claude" / "agents",
    REPO_ROOT / "examples" / "dogfooding" / ".claude" / "agents",
]
#: Every place a bundled body lives: the two above and the deploy source.
ALL_AGENT_DIRS = AGENT_DIRS + [REPO_ROOT / "espalier" / "assets" / "claude" / "agents"]

# Update this map when intentionally changing an agent's capability.
# CI fails if an agent's actual tools don't match its declared tier.
AGENT_TIER = {
    "architecture-analyst": "review-with-comments",
    "code-reviewer": "review-with-comments",
    "docs-maintainer": "docs-writing",
    "harness-config-advisor": "review-with-comments",
    "repo-analyst": "review-with-comments",
    "test-writer": "test-writing",
    # TP-40: failure-mode-reviewer (Opus, renamed from adversarial-reviewer
    # post-TP-56) is the internal-failure lens distinct from code-reviewer's
    # correctness lens — review-with-comments tier (no Write, broad reads).
    "failure-mode-reviewer": "review-with-comments",
}

#: Each tier's tools, exactly. A review agent reads and runs read-only
#: commands; the docs agent edits in place, so it holds Edit beside Write; the
#: test-writer writes new files.
TIER_CONTRACT = {
    "review-with-comments": frozenset({"Read", "Grep", "Glob", "Bash"}),
    "docs-writing": frozenset({"Read", "Grep", "Glob", "Bash", "Write", "Edit"}),
    "test-writing": frozenset({"Read", "Grep", "Glob", "Bash", "Write"}),
}

#: A tools entry: a bare tool name (an MCP tool's included), or the one
#: documented specifier, `Agent(...)`.
TOOL_ENTRY = re.compile(r"[A-Za-z][A-Za-z0-9_-]*|Agent\([^()]*\)")

#: The paragraph each body that grants Bash carries: where its scope is set.
BASH_SCOPE = "**Bash scope.** `Bash` on the tools line above is the whole tool"


def _read_agent_tools(path: Path) -> list[str]:
    """Parse YAML-like frontmatter `tools:` line into a list."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^tools:\s*(.+)$", text, re.MULTILINE)
    if not m:
        return []
    return [t.strip() for t in m.group(1).strip().split(",")]


def _agent_files(name: str) -> list[Path]:
    return [d / f"{name}.md" for d in AGENT_DIRS if (d / f"{name}.md").exists()]


def test_at_least_one_agent_is_found():
    """Floor guard: the parametrized test below uses ``pytest.skip``
    when an agent file is missing. If the entire roster were relocated
    or deleted, every parametrized case would skip and the tier
    contract would silently void itself. This test fails loudly if
    fewer than half the expected agents are present on disk."""
    found = [name for name in AGENT_TIER if _agent_files(name)]
    minimum = max(1, len(AGENT_TIER) // 2)
    assert len(found) >= minimum, (
        f"Only {len(found)} agent file(s) found for the {len(AGENT_TIER)} "
        f"expected tiers; the parametrized contract would skip everything. "
        f"Check that .claude/agents/ + examples/dogfooding/.claude/agents/ "
        f"haven't moved or been emptied."
    )


@pytest.mark.parametrize(
    "agent_name,expected_tier", sorted(AGENT_TIER.items())
)
def test_agent_capability_matches_tier(agent_name, expected_tier):
    paths = _agent_files(agent_name)
    if not paths:
        pytest.skip(
            f"Agent {agent_name}.md not found in any expected location "
            f"(may have been intentionally removed)"
        )
    for path in paths:
        tools = _read_agent_tools(path)
        assert len(tools) == len(set(tools)), (path, tools)
        assert set(tools) == TIER_CONTRACT[expected_tier], (
            f"Agent {agent_name!r} is tier {expected_tier!r}, whose tools are "
            f"{sorted(TIER_CONTRACT[expected_tier])}, but declares {tools}. Either "
            f"update the tier in tests/test_agent_frontmatter_contract.py::AGENT_TIER "
            f"or correct the agent's tools line.\n"
            f"Agent file: {path.relative_to(REPO_ROOT)}"
        )


def _bodies() -> list[Path]:
    return [p for d in ALL_AGENT_DIRS for p in visible(checkout_glob(d, "*.md"), d)]


def test_no_tools_line_carries_a_command_specifier():
    """A specifier reads as a narrowed grant and narrows nothing; only the
    documented `Agent(...)` form is kept. Every body, the deploy source's too."""
    bodies = _bodies()
    assert len(bodies) >= 3 * len(AGENT_TIER), bodies
    bad = {
        str(p.relative_to(REPO_ROOT)): t
        for p in bodies for t in _read_agent_tools(p) if not TOOL_ENTRY.fullmatch(t)
    }
    assert not bad, bad


def test_each_body_that_grants_bash_says_where_its_scope_is_set():
    missing = [
        str(p.relative_to(REPO_ROOT)) for p in _bodies()
        if "Bash" in _read_agent_tools(p) and BASH_SCOPE not in _body_text(p)
    ]
    assert not missing, missing


def _body_text(path: Path) -> str:
    """The body's text with each paragraph's line breaks read as spaces."""
    return re.sub(r"[ \t]*\n[ \t]*(?=\S)", " ", path.read_text(encoding="utf-8"))


def test_every_agent_on_disk_has_tier():
    """TP-151 H-2: completeness backstop (U ⊆ R). Every agent file on disk must
    be registered in AGENT_TIER — otherwise a newly-added agent silently
    escapes the tier/capability contract (AGENT_TIER is the iteration domain;
    an unregistered agent is invisible to it). Sister to the TP-150
    'registration-set as iteration domain' mode (3rd fresh site)."""
    agents_dir = REPO_ROOT / ".claude" / "agents"
    on_disk = {p.stem for p in visible(checkout_glob(agents_dir, "*.md"), agents_dir)}
    unregistered = on_disk - set(AGENT_TIER)
    assert not unregistered, (
        f"agents on disk missing from AGENT_TIER: {sorted(unregistered)}. "
        f"Add each to AGENT_TIER with its capability tier so the tier contract "
        f"covers it."
    )


#: The test commands the fingerprint records per stack, as
#: espalier/analyze.py::detect_tests writes them.
RUNNER_STACKS = {
    "python": ["pytest -q"],
    "node": ["npm test"],
    "node_pnpm": ["pnpm test"],
    "go": ["go test ./..."],
    "rust": ["cargo test"],
    "make": ["make test"],
    "unittest": ["python -m unittest discover"],
    "polyglot": ["pytest -q", "npm test"],
}


def _runner_agents() -> list[str]:
    from espalier.harness_config import RUNNER_AGENT_PATHS

    return sorted(Path(p).stem for p in RUNNER_AGENT_PATHS)


def test_the_runner_agents_grant_bash():
    for name in _runner_agents():
        assert "Bash" in TIER_CONTRACT[AGENT_TIER[name]], name


@pytest.mark.parametrize("agent_name", _runner_agents())
@pytest.mark.parametrize("stack", sorted(RUNNER_STACKS))
def test_a_runner_agents_deploy_is_its_packaged_body(agent_name, stack):
    """The deploy renders each runner agent's tools line from the fingerprint's
    test commands, appending a narrowed rule the line does not already grant.
    A plain `Bash` grants every one, so on every stack the rendered body is
    the packaged body: the renderer adds nothing, and the repository's runner
    is reachable through the plain grant."""
    from espalier.harness_config import _rule_is_covered, agent_runner_rules, render_agent_tools

    packaged = REPO_ROOT / "espalier" / "assets" / "claude" / "agents" / f"{agent_name}.md"
    body = packaged.read_text(encoding="utf-8")
    rules = agent_runner_rules(RUNNER_STACKS[stack])
    assert rules, stack
    assert render_agent_tools(body, rules) == body, (agent_name, stack)
    tools = _read_agent_tools(packaged)
    for rule in rules:
        assert _rule_is_covered(rule, tools), (agent_name, stack, rule, tools)
