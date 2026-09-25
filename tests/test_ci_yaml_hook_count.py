"""TP-115 (deferred/minimal): forbid new hand-typed hook counts
in CI YAML outside marked historical lines.

The C-L02 debt today is ONE historical comment at release.yml:95.
This test prevents a future contributor from inlining a `9 hooks` /
`10 hooks` claim that silently rots. New CI workflows that need to
assert the hook count must use a subprocess assertion
(`espalier audit .` or pytest) — those derive from live state.

The contract is grep-based (no StringContract dataclass machinery
per the C-U01 deferral discussed in TP-115 — past-tense facts
shouldn't be contract-pinned for byte-equality).

The second assertion enforces the CONTRACT_CEILINGS["ci-yaml-hook-count"]
discipline exactly: live opt-out count for this rule_id across CI
YAML must be exactly 1 (the release.yml:95 historical marker).
"""
from __future__ import annotations

import re
from pathlib import Path

from tests._contracts import count_opt_outs_for_rule
from tests._surface_expected import CONTRACT_CEILINGS

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# Word-boundary + negative-lookahead to avoid false-matches on
# `timeout-minutes: 10`, `python-version: 3.11`, `step-id:`, etc.
HOOK_COUNT_RE = re.compile(
    r"\b(\d+)\s+hooks?\b(?!\s*-\s*(?:minutes|version|id))",
    re.IGNORECASE,
)


def _line_carries_historical_marker(line: str) -> bool:
    return "# contract: ok ci-yaml-hook-count" in line


def _yaml_files() -> list[Path]:
    return sorted(WORKFLOWS_DIR.glob("*.yml"))


class TestCiYamlHookCount:
    def test_no_fresh_hook_count_in_ci_yaml(self):
        violations: list[tuple[Path, int, str]] = []
        for wf in _yaml_files():
            for lineno, line in enumerate(
                wf.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if HOOK_COUNT_RE.search(line) and not _line_carries_historical_marker(line):
                    violations.append((wf, lineno, line.strip()))
        assert not violations, (
            "Fresh hook-count literals in CI YAML (use a subprocess "
            "assertion that derives from live state, OR annotate the "
            "line with `# contract: ok ci-yaml-hook-count <reason>` "
            "if it's a historical reference):\n"
            + "\n".join(
                f"  {wf.relative_to(REPO_ROOT)}:{ln}: {ltext}"
                for wf, ln, ltext in violations
            )
        )

    def test_live_opt_out_count_matches_ceiling(self):
        ceiling = CONTRACT_CEILINGS["ci-yaml-hook-count"]
        live = count_opt_outs_for_rule("ci-yaml-hook-count", _yaml_files())
        assert live == ceiling, (
            f"ci-yaml-hook-count opt-out count drift: live={live} "
            f"vs CONTRACT_CEILINGS={ceiling}. Either remove the stray "
            f"marker or raise the ceiling with a documented reason."
        )
