"""Shipped skill bodies must not name agents that don't exist.

Originally a tier contract (BC-043): v0.7.1's `debug` skill named a
harness-dev agent (`architecture-analyst`) without a presence check, so a
common-tier deploy hit "agent not found" at runtime, and v0.7.1.1's hotfix
made the body tier-aware via an `ls .claude/agents/X.md` gate.

The harness-dev deploy tier was later retired — every consumer now gets
every agent — so the gate-the-reference contract is moot (there are no
harness-dev-only agents to gate). The surviving invariant is the sanity
check: every agent a skill body names must resolve to a real agent file,
plus the runtime/asset skill-dir parity check.
"""

from __future__ import annotations

import re
from pathlib import Path

from espalier.harness_config import CANONICAL_HOOK_WIRING


ASSET_ROOT = Path(__file__).parent.parent / "espalier" / "assets" / "claude"

# CC hook-event names (`SubagentStart`, `PreToolUse`, …) are CamelCase and are
# NOT agent slugs (which are lowercase-kebab). A skill that documents the hook
# surface (e.g. `hook-authoring`) backtick-wraps these event names, and pattern
# #4 of _AGENT_NAME_RE below would otherwise misread `SubagentStart` as an agent
# reference whenever the word "subagent" appears in the adjacent description.
# Exempt the closed set of governed event names, sourced from the wiring SoT so
# it can't drift.
_HOOK_EVENT_NAMES = {spec["event"] for spec in CANONICAL_HOOK_WIRING.values()}


# Four patterns by which a skill body names an agent. Note: the regex
# is intentionally a CANDIDATE list, NOT the SoT (round-2 review finding:
# the original 3-alternation regex missed `Delegates to the X agent` --
# the most common idiom -- because the optional qualifier group required
# >=1 char before `to`).
_AGENT_NAME_RE = re.compile(
    r"(?:"
    # 1. Code-block invocation: subagent_type="<agent-slug>"
    r"subagent_type\s*=\s*['\"]([a-z][a-z0-9-]+)['\"]"
    r"|"
    # 2. Body bolded: **<agent-slug>** agent / subagent
    r"\*\*([a-z][a-z0-9-]+)\*\*\s+(?:agent|subagent)"
    r"|"
    # 3. Plain "Delegates to the X agent" (zero or more qualifier chars
    # between Delegates and `to`, so "Delegates to ..." and "Delegates
    # cross-X to ..." both match). The * quantifier allows the zero-char
    # case the original + missed.
    r"\bDelegates?\s+(?:[a-z\- ,]*to\s+)?(?:the\s+)?"
    r"\*?\*?([a-z][a-z0-9-]+)\*?\*?\s+(?:agent|subagent)"
    r"|"
    # 4. Backtick reference: `failure-mode-reviewer` agent / `X` ... agent.
    # The (?:agent|subagent) suffix is REQUIRED -- otherwise any
    # backtick-wrapped lowercase word (`espalier`, `ImportError`, etc.)
    # matches and the sanity test misclassifies them as agent names.
    r"`([a-z][a-z0-9-]+)`[^`]{0,40}?(?:agent|subagent)"
    r")",
    re.IGNORECASE,
)


def _common_tier_skill_paths() -> list[Path]:
    # Every shipped skill — the harness-dev deploy tier was retired, so
    # there is no longer a tier carve-out to skip.
    return sorted((ASSET_ROOT / "skills").glob("*/SKILL.md"))


def _all_agent_names() -> set[str]:
    return {p.stem for p in (ASSET_ROOT / "agents").glob("*.md")}


def test_common_tier_skill_bodies_dont_name_unknown_agents() -> None:
    """Sanity: every named agent must resolve to a real agent file."""
    all_agents = {a.lower() for a in _all_agent_names()}
    failures: list[str] = []
    for skill_path in _common_tier_skill_paths():
        body = skill_path.read_text(encoding="utf-8")
        for match in _AGENT_NAME_RE.finditer(body):
            named = next((g for g in match.groups() if g), None)
            if named is None:
                continue
            if named in _HOOK_EVENT_NAMES:
                continue  # a hook-event name, not an agent reference
            if named.lower() not in all_agents:
                failures.append(
                    f"{skill_path.relative_to(ASSET_ROOT)}: "
                    f"names agent '{named}' which is not in "
                    f"espalier/assets/claude/agents/"
                )
    assert not failures, "\n".join(failures)


def test_hook_event_exemption_does_not_blind_the_agent_scanner() -> None:
    """Negative twin for the `_HOOK_EVENT_NAMES` exemption (TP-328).

    The exemption was added to stop the agent-name heuristic misreading CC
    hook-event names (`SubagentStart`, …) as agent references. A suppression
    shipped without a witness is the born-weak / autoimmune shape: a later edit
    could widen the exemption and silently blind the scanner. This pins both
    directions — the scanner still fires on a genuine bogus agent, and still
    exempts a CamelCase event name.
    """
    all_agents = {a.lower() for a in _all_agent_names()}

    def _flag(body: str) -> list[str]:
        out: list[str] = []
        for match in _AGENT_NAME_RE.finditer(body):
            named = next((g for g in match.groups() if g), None)
            if named is None:
                continue
            if named in _HOOK_EVENT_NAMES:
                continue
            if named.lower() not in all_agents:
                out.append(named)
        return out

    # A bogus lowercase-kebab agent reference is STILL flagged (scanner alive).
    assert _flag("Delegates to the `bogus-nonexistent-agent` agent") == [
        "bogus-nonexistent-agent"
    ]
    # A CamelCase hook-event name is exempted (the false positive TP-328 fixed).
    assert _flag("| `SubagentStart` | A subagent is spawned | x |") == []
    # A real agent still passes clean.
    assert _flag("Delegates to the `code-reviewer` agent") == []


def test_runtime_and_asset_skill_dirs_have_parity_for_tier_check() -> None:
    """The `.claude/skills/` runtime copy and the
    `espalier/assets/claude/skills/` asset copy must contain the same
    set of skill directories. This assertion is a minimal dir-set sanity
    check at this contract's scope; byte-for-byte BODY parity is owned by
    test_package_resource_parity.py -- `TestRootMirrorParity` (root .claude/
    <-> dogfooding) and `TestAssetClaudeMirrorParity` (asset copy <->
    dogfooding, TP-151 G-4) together cover the three-way invariant."""
    runtime_root = Path(__file__).parent.parent / ".claude" / "skills"
    runtime = sorted(
        p.name for p in runtime_root.iterdir() if p.is_dir()
    )
    assets = sorted(
        p.name for p in (ASSET_ROOT / "skills").iterdir() if p.is_dir()
    )
    assert runtime == assets, (
        f"skill-dir parity drift: .claude/skills={runtime}, "
        f"espalier/assets/claude/skills={assets}"
    )
