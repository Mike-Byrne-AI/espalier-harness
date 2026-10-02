"""Every committed review scaffold launches its agents the same way.

Why this exists
---------------
Three conventions were added to the scaffolds under ``.claude/workflows/`` on
2026-10-01 after a precheck of the review system, and each one fails silently
when a copy drops it:

1. **One model per run.** Workflow agents inherit the session model unless each
   ``agent()`` call overrides it. The scaffolds route ``args.model`` through one
   ``opts()`` helper at every call, so an operator who must not run a given
   model in fan-outs can say so once per launch. A single call that passes a
   bare options literal reverts to the inherited model for that agent and
   nothing reports it.
2. **Finder-time field strip.** ``aggregate_findings`` honours a present
   ``corrected_category`` over the original even when it is null, so a finder
   that echoes the schema's optional keys sinks its finding into the null
   bucket (16 of 38 records in one round). ``stripRefuterFields`` removes the
   refuter-owned keys from finder output. The three scaffolds must carry the
   same field set, or a round's category mix depends on which scaffold ran.
3. **Lane identity.** The per-run ledger's ``finder_identities`` derives from
   ``rule_or_scanner``; a finder-authored blurb there makes every finding its
   own identity. Each scaffold stamps the lane id into that field.

The checks read the live scripts with whole-line ``//`` comments removed, so a
convention carried only in a comment does not pass (the same discipline as
``test_convergence_workflow_stages.py``).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".claude" / "workflows"

# The one helper every scaffold carries, verbatim: the destructure names the
# refuter-owned keys, so a scaffold that drops or adds one differs here.
STRIP_HELPER_LINE = (
    "const { corrected_category, corrected_confidence, externally_verified, ...rest } = x"
)
_AGENT_CALL = re.compile(r"\bagent\(")
_OPTS_CALL = re.compile(r"\bopts\(")
# A stamp is `rule_or_scanner: <value>` outside the schema, whose own line reads
# `rule_or_scanner: { type: 'string', ...`.
_LANE_STAMP = re.compile(r"rule_or_scanner: (?!\{)")


def _code_lines(src: str) -> str:
    return "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("//")
    )


def _scaffolds() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.js"))


def test_there_are_scaffolds_to_check():
    """Floor: an empty glob would make every check below vacuously green."""
    assert _scaffolds(), f"no *.js under {WORKFLOWS}"


@pytest.mark.parametrize("path", _scaffolds(), ids=lambda p: p.name)
def test_every_agent_call_routes_its_options_through_opts(path: Path):
    code = _code_lines(path.read_text(encoding="utf-8"))
    n_agent = len(_AGENT_CALL.findall(code))
    n_opts = len(_OPTS_CALL.findall(code))
    assert n_agent > 0, f"{path.name}: no agent() call found; the check is vacuous"
    assert "const MODEL = " in code and "const opts = " in code, (
        f"{path.name}: the args.model passthrough (MODEL + opts) is missing"
    )
    assert n_agent == n_opts, (
        f"{path.name}: {n_agent} agent() calls but {n_opts} opts() wrappers -- an "
        "agent call that passes a bare options literal inherits the session model "
        "for that agent alone, and nothing reports it"
    )


@pytest.mark.parametrize("path", _scaffolds(), ids=lambda p: p.name)
def test_every_scaffold_strips_the_same_refuter_fields_at_finder_time(path: Path):
    code = _code_lines(path.read_text(encoding="utf-8"))
    assert STRIP_HELPER_LINE in code, (
        f"{path.name}: stripRefuterFields is missing or its field set differs from "
        f"the canonical line: {STRIP_HELPER_LINE}"
    )
    # Defined once, applied at least once: a helper nobody calls strips nothing.
    assert len(re.findall(r"\bstripRefuterFields\(", code)) >= 1, (
        f"{path.name}: stripRefuterFields is defined but never applied"
    )


@pytest.mark.parametrize("path", _scaffolds(), ids=lambda p: p.name)
def test_every_scaffold_stamps_the_lane_identity(path: Path):
    code = _code_lines(path.read_text(encoding="utf-8"))
    assert _LANE_STAMP.search(code), (
        f"{path.name}: no `rule_or_scanner: <lane>` stamp outside the schema -- the "
        "per-run ledger's finder_identities will be one blurb per finding again"
    )
