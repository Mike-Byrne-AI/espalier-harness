"""TP-35: hook matchers must be narrow, not blanket ``*``.

Pre-TP-35 every mutation hook used ``matcher: "*"``, firing on every
tool call (Read, Grep, Glob, WebSearch, AskUserQuestion, ...) and
spawning a Python process per hook per call. The fix narrows matchers
to the tools the hooks actually govern.

Documented exception: ``reflect_trigger.py`` keeps ``"*"`` because its
"every Nth tool call" cadence must observe every tool, not just
mutations. The exception is enumerated in ``ALLOWED_STAR_HOOKS``.

See docs/HOOKS.md for the matcher rules and the per-event matcher-
support truth table.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# TP-108: import MUTATION_TOOLS from the shared _hook_utils SoT rather
# than re-declare it here. The sys.path pattern matches tests/test_hook_utils.py
# and tests/test_sister_site_probe_synthetic.py — adding ``tools/cc/hooks``
# to path lets the bare ``_hook_utils`` import resolve without dotted
# package syntax (which no other test file uses for hook internals).
sys.path.insert(0, str(REPO_ROOT / "tools" / "cc" / "hooks"))
from _hook_utils import MUTATION_TOOLS as EXPECTED_MUTATION_TOOLS  # noqa: E402


@pytest.fixture
def initialized_repo(tmp_path: Path) -> Path:
    subprocess.run(
        ["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True
    )
    subprocess.run(
        [sys.executable, "-m", "espalier.cli", "init", str(tmp_path)],
        check=True, cwd=REPO_ROOT, capture_output=True,
    )
    return tmp_path


def _load_settings(repo: Path) -> dict:
    return json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))


def _extract_script(hook: dict) -> str:
    """Extract the script basename from a hook entry, supporting exec
    or shell form. Exec form: args[0] is the script. Shell form: the
    .py token in command.
    """
    args = hook.get("args") or []
    for arg in args:
        if isinstance(arg, str) and arg.endswith(".py"):
            return Path(arg).name
    cmd = hook.get("command", "")
    tokens = cmd.replace('"', " ").split()
    for tok in tokens:
        if tok.endswith(".py"):
            return Path(tok).name
    return ""


# TP-64: plan_guard.py legitimately omits Bash/PowerShell/MCP from its
# matcher. Other narrow PreToolUse hooks (none in tree today, but
# preserved as the contract for future additions) still require the
# full mutation-tool set.
PLAN_GUARD_EXPECTED_TOKENS = {"Write", "Edit", "NotebookEdit"}


def _expected_tokens_for(script: str) -> set[str]:
    if script == "plan_guard.py":
        return PLAN_GUARD_EXPECTED_TOKENS
    return EXPECTED_MUTATION_TOOLS


# Documented exceptions:
#   - reflect_trigger.py needs "*" for every-Nth-call cadence counting.
#   - write_guard.py widened to "*" by TP-48 C2 so Task / TodoWrite /
#     SlashCommand / BashOutput dispatches reach write_guard's
#     kill-switch and protected-zone gates. Pre-TP-48 the narrowed
#     matcher excluded those tools and the kill-switch silently skipped
#     subagent dispatches.
# plan_guard.py was previously in this set (TP-48 C2 widening) but TP-64
# narrowed it back to Write|Edit|NotebookEdit to cut subprocess-fork
# overhead and eliminate Bash write-intent false positives. write_guard
# remains the kill-switch path; plan_guard is now purely the
# Write/Edit/NotebookEdit plan gate.
ALLOWED_STAR_HOOKS = {"reflect_trigger.py", "write_guard.py"}

# Events the live Claude Code docs (2026-05-13) confirm do NOT support matchers
NO_MATCHER_EVENTS = {
    "UserPromptSubmit", "Stop", "PostToolBatch",
    "TeammateIdle", "TaskCreated", "TaskCompleted", "CwdChanged",
}


@pytest.mark.integration
class TestMatcherPrecision:
    def test_pretooluse_mutation_hooks_use_narrow_matcher(self, initialized_repo):
        settings = _load_settings(initialized_repo)
        for entry in settings.get("hooks", {}).get("PreToolUse", []):
            matcher = entry.get("matcher", "")
            for hook in entry.get("hooks", []):
                script = _extract_script(hook)
                if script in ALLOWED_STAR_HOOKS:
                    continue
                assert matcher != "*", (
                    f"PreToolUse matcher is '*' for {script!r}; "
                    f"narrow mutation matcher expected.\nEntry: {entry}"
                )
                tokens = set(matcher.split("|"))
                # TP-64: plan_guard.py legitimately requires only
                # {Write, Edit, NotebookEdit}; other narrow hooks keep
                # the full mutation set.
                missing = _expected_tokens_for(script) - tokens
                assert not missing, (
                    f"PreToolUse matcher missing mutation tools "
                    f"{missing}: {matcher!r}"
                )
                # R13 B3: explicitly assert ``mcp__.*`` is in the matcher.
                # Pre-fix the contract test used a subset check
                # (EXPECTED - tokens) — `mcp__.*` was unverified and a
                # regression to drop it would not have failed CI.
                # TP-64 exempts plan_guard.py: it intentionally omits
                # mcp__ to skip the subprocess fork on every MCP call;
                # write_guard remains the protected-zone defense.
                if script != "plan_guard.py":
                    assert any("mcp__" in t for t in tokens), (
                        f"PreToolUse matcher missing mcp__ alternative — MCP "
                        f"writes bypass write_guard. matcher={matcher!r}"
                    )

    def test_posttooluse_mutation_hooks_use_narrow_matcher(self, initialized_repo):
        settings = _load_settings(initialized_repo)
        for entry in settings.get("hooks", {}).get("PostToolUse", []):
            matcher = entry.get("matcher", "")
            for hook in entry.get("hooks", []):
                script = _extract_script(hook)
                if script in ALLOWED_STAR_HOOKS:
                    continue
                assert matcher != "*", (
                    f"PostToolUse matcher is '*' for {script!r}; "
                    f"narrow mutation matcher expected.\nEntry: {entry}"
                )
                tokens = set(matcher.split("|"))
                missing = EXPECTED_MUTATION_TOOLS - tokens
                assert not missing, (
                    f"PostToolUse matcher missing mutation tools "
                    f"{missing}: {matcher!r}"
                )
                # R13 B3: same as the PreToolUse assertion above.
                assert any("mcp__" in t for t in tokens), (
                    f"PostToolUse narrow matcher missing mcp__ alternative. "
                    f"matcher={matcher!r}"
                )

    def test_no_matcher_events_omit_matcher_field(self, initialized_repo):
        settings = _load_settings(initialized_repo)
        for event in NO_MATCHER_EVENTS:
            entries = settings.get("hooks", {}).get(event, [])
            for entry in entries:
                assert "matcher" not in entry, (
                    f"Event {event!r} does not support matchers per "
                    f"Claude Code docs, but generated settings carries "
                    f"matcher={entry['matcher']!r}. The field is "
                    f"silently ignored; remove it from the renderer."
                )

    def test_reflect_trigger_keeps_star_matcher(self, initialized_repo):
        """reflect_trigger.py needs '*' for its every-Nth-call cadence
        and is the only documented exception. If a future renderer
        narrows it, the trigger stops counting Read/Grep/Glob calls
        and the periodic reflect pass goes silent."""
        settings = _load_settings(initialized_repo)
        found_reflect = False
        for entry in settings.get("hooks", {}).get("PostToolUse", []):
            for hook in entry.get("hooks", []):
                if _extract_script(hook) == "reflect_trigger.py":
                    found_reflect = True
                    assert entry.get("matcher") == "*", (
                        f"reflect_trigger.py must use matcher='*' for "
                        f"cadence counting; got {entry.get('matcher')!r}"
                    )
        assert found_reflect, (
            "reflect_trigger.py not found in PostToolUse entries"
        )

    def test_tp163_new_event_matchers(self, initialized_repo):
        """TP-163: SubagentStart carries no matcher (fires at every subagent
        spawn); PostToolUseFailure narrows to the edit tools in the canonical
        Write|Edit|NotebookEdit token order (helper-derived). The generic
        per-event tests above don't iterate these two events, so pin them
        explicitly — a wrong/blanket matcher would otherwise ship unguarded."""
        settings = _load_settings(initialized_repo)
        hooks = settings.get("hooks", {})

        # SubagentStart: empty matcher → field omitted by the renderer.
        ss_entries = hooks.get("SubagentStart", [])
        assert ss_entries, "SubagentStart group missing from generated settings"
        for entry in ss_entries:
            assert "matcher" not in entry, (
                f"SubagentStart must omit the matcher field (empty matcher); "
                f"got matcher={entry.get('matcher')!r}"
            )
            assert any(
                _extract_script(h) == "subagent_start.py"
                for h in entry.get("hooks", [])
            ), "subagent_start.py not wired under SubagentStart"

        # PostToolUseFailure: narrow matcher, canonical token order.
        ptf_entries = hooks.get("PostToolUseFailure", [])
        assert ptf_entries, (
            "PostToolUseFailure group missing from generated settings"
        )
        for entry in ptf_entries:
            assert entry.get("matcher") == "Write|Edit|NotebookEdit", (
                f"PostToolUseFailure must narrow to 'Write|Edit|NotebookEdit' "
                f"(canonical token order); got {entry.get('matcher')!r}"
            )
            assert any(
                _extract_script(h) == "context_reinject_failure.py"
                for h in entry.get("hooks", [])
            ), "context_reinject_failure.py not wired under PostToolUseFailure"


# TP-110: dual-witness parity between engine-side ordered tuple and
# enforcement-side frozenset. Order source vs membership source.
def test_mutation_tools_dual_witness():
    """`harness_config.MUTATION_TOOLS_TOKENS` (tuple, order-preserving)
    and `_hook_utils.MUTATION_TOOLS` (frozenset, membership-only) are
    declared independently per the zero-imports rule. Set equality
    pins them: a new token added on one side without the other fires
    here at pytest time.
    """
    from espalier.harness_config import MUTATION_TOOLS_TOKENS
    assert frozenset(MUTATION_TOOLS_TOKENS) == EXPECTED_MUTATION_TOOLS, (
        "MUTATION_TOOLS dual-witness drift:\n"
        f"  harness_config.MUTATION_TOOLS_TOKENS = {sorted(MUTATION_TOOLS_TOKENS)}\n"
        f"  _hook_utils.MUTATION_TOOLS = {sorted(EXPECTED_MUTATION_TOOLS)}\n"
        "Both must list the same tokens (order-source vs membership-source)."
    )


def test_settings_matcher_strings_derive_from_helper(initialized_repo):
    """Every non-empty, non-'*' matcher value in `CANONICAL_HOOK_WIRING`
    is reproducible by `matcher_token_string()` with some choice of
    `tokens` and `extras`. Pins the contract that settings.json matcher
    strings come from the helper, not from hand-typed pipe-string
    literals.
    """
    from espalier.harness_config import (
        CANONICAL_HOOK_WIRING,
        matcher_token_string,
    )

    # Enumerate every helper-producible (tokens, extras) combination
    # observed in live CHW values. Adding a new matcher shape requires
    # adding it here.
    candidates: list[str] = [
        matcher_token_string(),  # default full token set, no extras
        matcher_token_string(extras=("mcp__.*",)),  # full + mcp wildcard
        matcher_token_string(tokens=("Write", "Edit", "NotebookEdit")),  # narrow
    ]
    candidate_set = frozenset(candidates)

    violations: list[str] = []
    for script, spec in CANONICAL_HOOK_WIRING.items():
        matcher = spec["matcher"]
        if matcher in {"", "*"}:
            continue
        if matcher not in candidate_set:
            violations.append(
                f"  {script}: CHW matcher={matcher!r} is not derivable "
                f"from matcher_token_string() with known (tokens, extras) "
                f"combinations. Either add a new candidate to this test "
                f"or update CHW to a helper-derivable form."
            )
    assert not violations, (
        "CHW matcher values must be derivable from matcher_token_string():\n"
        + "\n".join(violations)
    )
