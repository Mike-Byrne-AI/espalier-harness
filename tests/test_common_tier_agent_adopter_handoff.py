"""TP-93 §F — common-tier agent body adopter-handoff contract.

Pins the rule that every common-tier agent under
``espalier/assets/claude/agents/`` must either (a) avoid hardcoded
references to harness-internal paths, (b) gate each such reference
behind a presence-check pattern in a bash heredoc / code-fence, or
(c) ship an explicit "Adapting me to YOUR ..." section so adopters
know which parts of the body apply only to Espalier-Harness's own
dogfood layout.

The asset set is enumerated by iterating
``espalier/assets/claude/agents/*.md`` — every shipped agent (the
harness-dev deploy tier was retired, so there is no longer a tier
carve-out to skip).

Sibling-shape to the TP-78 contract; different assertion. TP-78
pins no-leaked-pack-IDs; this one pins adopter-fit framing.
Without this guard, a copy-paste of self-host-only paths into a shipped
agent body could silently leak them into every adopter init, leaving
them with agent bodies that reference files which don't exist in their
repo.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSET_AGENTS_DIR = REPO_ROOT / "espalier" / "assets" / "claude" / "agents"

HARNESS_PATH_TOKENS: tuple[str, ...] = (
    "espalier/",
    "tools/cc/",
    "bench/",
    "cc/blueprints/",
    "cc/PACK_MANIFEST",
    "cc/LIVE_SURFACE",
    "cc/COMMANDS",
)

# 98-E: literal-substring match on the canonical heading shape, not a
# broad regex over "your X". The pre-98-E matcher was case-insensitive
# and accepted phrases like "## What I do for your repo's tests" — any
# H2 mentioning "your" satisfied it, including ones unrelated to the
# adopter-handoff convention. The TP-93 common-tier convention is the
# exact prefix below (case-sensitive on YOUR). All 5 common-tier
# agents use this shape: "## Adapting me to YOUR repo|architecture|
# docs tree|test patterns". The literal prefix kills false-positives
# without losing any true-positive.
ADOPTER_HANDOFF_SECTION_PREFIX = "## Adapting me to YOUR "

PRESENCE_CHECK_PATTERN = re.compile(
    r"\[\s*-[dfe]\s|"
    r"\bif\s+\[\s*-[dfe]\s|"
    r"\.is_dir\(\)|\.is_file\(\)|\.exists\(\)|"
    r"NOT PRESENT|SURFACE MISSING|MISSING — "
)


def _enumerate_common_tier_agents() -> list[Path]:
    # Every shipped agent — the harness-dev deploy tier was retired, so
    # there is no longer a tier carve-out to skip.
    return sorted(ASSET_AGENTS_DIR.glob("*.md"))


def _has_adopter_handoff_section(body: str) -> bool:
    for line in body.splitlines():
        if line.startswith(ADOPTER_HANDOFF_SECTION_PREFIX):
            return True
    return False


def _line_is_gated(lines: list[str], idx: int, window: int = 6) -> bool:
    """Return True when the harness-path line at idx sits inside a
    presence-check guard within the surrounding `window` lines."""
    start = max(0, idx - window)
    end = min(len(lines), idx + window + 1)
    for j in range(start, end):
        if PRESENCE_CHECK_PATTERN.search(lines[j]):
            return True
    return False


class TestCommonTierAgentAdopterHandoff:
    """Common-tier agents must signal which content is harness-specific."""

    def test_each_common_tier_agent_satisfies_one_condition(self) -> None:
        agents = _enumerate_common_tier_agents()
        assert agents, "no common-tier agents found — discovery is broken"

        offenders: list[tuple[str, str]] = []
        for path in agents:
            body = path.read_text(encoding="utf-8")
            rel = path.relative_to(REPO_ROOT).as_posix()

            if _has_adopter_handoff_section(body):
                continue

            lines = body.splitlines()
            ungated_hits: list[str] = []
            for i, line in enumerate(lines):
                if not any(tok in line for tok in HARNESS_PATH_TOKENS):
                    continue
                if _line_is_gated(lines, i):
                    continue
                ungated_hits.append(f"L{i + 1}: {line.strip()[:100]}")

            if ungated_hits:
                offenders.append((rel, "; ".join(ungated_hits[:3])))

        assert not offenders, (
            "common-tier agent(s) lack adopter handoff:\n"
            + "\n".join(
                f"  {rel}\n    {hits}" for rel, hits in offenders
            )
            + "\nFix: add an '## Adapting me to YOUR ...' section, gate "
            "the harness-path references behind a presence-check, or "
            "make the references generic."
        )

    def test_handoff_matcher_rejects_false_positive_headings(self) -> None:
        """98-E: the post-tightening matcher must reject H2 headings that
        merely contain "your" — only the canonical "## Adapting me to YOUR "
        prefix counts as an adopter-handoff section.

        Pre-98-E the matcher was `r"adapting me to your|your repo|your project|
        your architecture|your docs tree|your test patterns"` with IGNORECASE,
        which accepted ANY H2 that mentioned the word "your" — including
        "## What I do for your repo's tests" or "## Tests in your project".
        Those don't satisfy the TP-93 convention. Lock the negative cases
        so a future widening of the matcher fires this test.
        """
        false_positives = [
            "## What I do for your repo's tests",
            "## Tests in your project",
            "## Your architecture diagram",
            "## How I read your docs tree",
            "## Adapting Me To Your Repo",  # wrong case on YOUR
            "## adapting me to YOUR repo",  # wrong case on Adapting
        ]
        for heading in false_positives:
            body = f"# Title\n\n{heading}\n\nSome content."
            assert not _has_adopter_handoff_section(body), (
                f"adopter-handoff matcher must reject false-positive "
                f"heading: {heading!r}"
            )

        true_positives = [
            "## Adapting me to YOUR repo",
            "## Adapting me to YOUR architecture",
            "## Adapting me to YOUR docs tree",
            "## Adapting me to YOUR test patterns",
        ]
        for heading in true_positives:
            body = f"# Title\n\n{heading}\n\nSome content."
            assert _has_adopter_handoff_section(body), (
                f"adopter-handoff matcher must accept canonical heading: "
                f"{heading!r}"
            )

    def test_agent_set_is_nonempty_and_release_verifier_retired(self) -> None:
        agents = _enumerate_common_tier_agents()
        names = {p.name for p in agents}

        # release-verifier was retired with the harness-dev deploy tier;
        # guard against an accidental re-add.
        assert "release-verifier.md" not in names, (
            "release-verifier.md was retired; it must not reappear"
        )
        assert len(agents) >= 6, (
            f"expected >=6 shipped agents, found {len(agents)}: {names}"
        )
