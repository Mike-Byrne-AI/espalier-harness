"""TP-36: pin each bundled agent's capability tier.

A future change adding `Write` to `code-reviewer.md` would be a silent
capability escalation if not caught. This test makes the tier explicit:
each agent declares its tier in `AGENT_TIER`, and the tier defines what
tools the agent may grant.

`TestRootMirrorParity` already guarantees `.claude/agents/` and
`examples/dogfooding/.claude/agents/` are byte-identical, so checking
one location is sufficient.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from espalier._safe_walk import visible

REPO_ROOT = Path(__file__).resolve().parent.parent

AGENT_DIRS = [
    REPO_ROOT / ".claude" / "agents",
    REPO_ROOT / "examples" / "dogfooding" / ".claude" / "agents",
]

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

TIER_CONTRACT = {
    "read-only": {
        "allows_write": False,
        "bash_allowlist_regex": (
            r"^Bash\((?:git\s+(?:diff|log|show|status|branch|remote)"
            r"|grep|head|cat|wc|find|ls)(\s+[^)]+)?\)$"
        ),
    },
    "review-with-comments": {
        "allows_write": False,
        "bash_allowlist_regex": (
            r"^Bash\((?:git\s+\*|grep\s+\*|head\s+\*|cat\s+\*|wc\s+\*"
            r"|find\s+\*|ls\s+\*|python\s+\*|python3\s+\*)\)$"
        ),
        # A runner agent's deployed line may also carry the repository's own
        # test runner, rendered from the fingerprint in the narrowed shape
        # (DERIVED_RUNNER_REGEX below). The packaged bodies this file reads
        # carry none; the render test pins what a deploy adds.
        "derived_runner": True,
    },
    "docs-writing": {
        "allows_write": True,
        "bash_allowlist_regex": (
            r"^Bash\((?:git\s+\*|grep\s+\*|head\s+\*|cat\s+\*|wc\s+\*"
            r"|echo\s+\*)\)$"
        ),
    },
    "test-writing": {
        "allows_write": True,
        "bash_allowlist_regex": (
            r"^Bash\((?:pytest\s+\*|python\s+\*|python3\s+\*|git\s+\*)\)$"
        ),
        "derived_runner": True,
    },
    "mutation-capable": {
        "allows_write": True,
        "bash_allowlist_regex": r".*",
    },
}


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

    contract = TIER_CONTRACT[expected_tier]
    bash_pattern = re.compile(contract["bash_allowlist_regex"])

    for path in paths:
        tools = _read_agent_tools(path)
        has_write = "Write" in tools
        if not contract["allows_write"]:
            assert not has_write, (
                f"Agent {agent_name!r} is tier {expected_tier!r} but "
                f"declares Write capability. Either update the tier in "
                f"tests/test_agent_frontmatter_contract.py::AGENT_TIER "
                f"or remove Write from the agent's tools.\n"
                f"Agent file: {path.relative_to(REPO_ROOT)}\n"
                f"Tools: {tools}"
            )

        bash_tools = [t for t in tools if t.startswith("Bash(")]
        for bash in bash_tools:
            assert bash_pattern.match(bash), (
                f"Agent {agent_name!r} tier {expected_tier!r} has Bash "
                f"command {bash!r} that doesn't match tier allowlist:\n"
                f"  {contract['bash_allowlist_regex']}\n"
                f"Either update the tier in AGENT_TIER or narrow the Bash "
                f"grant.\n"
                f"Agent file: {path.relative_to(REPO_ROOT)}"
            )


def test_every_agent_on_disk_has_tier():
    """TP-151 H-2: completeness backstop (U ⊆ R). Every agent file on disk must
    be registered in AGENT_TIER — otherwise a newly-added agent silently
    escapes the tier/capability contract (AGENT_TIER is the iteration domain;
    an unregistered agent is invisible to it). Sister to the TP-150
    'registration-set as iteration domain' mode (3rd fresh site)."""
    agents_dir = REPO_ROOT / ".claude" / "agents"
    on_disk = {p.stem for p in visible(agents_dir.glob("*.md"), agents_dir)}
    unregistered = on_disk - set(AGENT_TIER)
    assert not unregistered, (
        f"agents on disk missing from AGENT_TIER: {sorted(unregistered)}. "
        f"Add each to AGENT_TIER with its capability tier so the tier contract "
        f"covers it."
    )


#: The shape of a fingerprint-derived runner rule in a deployed tools line
#: (espalier/harness_config.py::render_agent_tools): a command of two or more
#: words with an optional trailing ` *`, or one word exactly. Never
#: `Bash(<binary> *)`: `Bash(npm *)` would grant the reviewer `npm install`
#: and `npm publish` (DEF-963, in DEF-965's narrowed form).
DERIVED_RUNNER_REGEX = r"^Bash\((?:[^\s()*]+(?: [^\s()*]+)+(?: \*)?|[^\s()*]+)\)$"

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


def test_the_runner_agents_are_tiered_to_carry_a_derived_runner():
    for name in _runner_agents():
        assert TIER_CONTRACT[AGENT_TIER[name]].get("derived_runner"), name


@pytest.mark.parametrize("agent_name", _runner_agents())
@pytest.mark.parametrize("stack", sorted(RUNNER_STACKS))
def test_a_rendered_runner_agent_keeps_its_tier(agent_name, stack):
    """The deploy renders each runner agent's tools line from the fingerprint
    (multi-language, in the style of
    tests/test_build_claude_md_uses_fingerprint.py): every Bash rule on the
    rendered line is a tier rule or a narrowed runner the fingerprint
    derived, the repository's runner is reachable, no Write appears where
    the tier forbids it, and nothing but the tools line changes."""
    from espalier.harness_config import _rule_is_covered, agent_runner_rules, render_agent_tools

    packaged = REPO_ROOT / "espalier" / "assets" / "claude" / "agents" / f"{agent_name}.md"
    body = packaged.read_text(encoding="utf-8")
    rules = agent_runner_rules(RUNNER_STACKS[stack])
    assert rules, stack
    rendered = render_agent_tools(body, rules)
    tools_line = re.compile(r"^tools:.*$", re.MULTILINE)
    assert tools_line.sub("", rendered) == tools_line.sub("", body), "only the tools line may change"
    tools = [t.strip() for t in tools_line.search(rendered).group(0)[len("tools:"):].split(",")]
    contract = TIER_CONTRACT[AGENT_TIER[agent_name]]
    static = re.compile(contract["bash_allowlist_regex"])
    derived = re.compile(DERIVED_RUNNER_REGEX)
    assert ("Write" in tools) == contract["allows_write"]
    for tool in (t for t in tools if t.startswith("Bash(")):
        assert static.match(tool) or (derived.match(tool) and tool in rules), (agent_name, stack, tool)
    for rule in rules:
        assert _rule_is_covered(rule, tools), (agent_name, stack, rule, tools)
    for bare in ("Bash(npm *)", "Bash(pnpm *)", "Bash(go *)", "Bash(cargo *)", "Bash(make *)"):
        assert bare not in tools, (agent_name, stack, bare)


def test_a_derived_rule_the_line_already_grants_is_not_added():
    from espalier.harness_config import agent_runner_rules, render_agent_tools

    body = (REPO_ROOT / "espalier" / "assets" / "claude" / "agents" / "test-writer.md").read_text(encoding="utf-8")
    assert render_agent_tools(body, agent_runner_rules(["pytest -q"])) == body, (
        "test-writer already grants Bash(pytest *): a Python repository's deploy is the packaged body"
    )
