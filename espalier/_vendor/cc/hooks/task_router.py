#!/usr/bin/env python3
"""UserPromptSubmit hook — classifies prompt scope and injects routing guidance.

Exit 0 always (never rejects prompts). Stdout text is injected as context
Claude sees alongside the user prompt. Empty stdout = no injection.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _hook_utils import has_active_plan, os_error_text, read_stdin_safely, resolve_project_root, STATE_DIR, COLD_OPEN_FLAG  # noqa: E402
import _reinject  # noqa: E402  -- the UserPromptSubmit generative recall dispatch

# Keywords that suggest a multi-step task
MULTI_STEP_KEYWORDS = {
    "refactor", "build", "implement", "add feature", "redesign", "migrate",
    "create a", "set up", "integrate", "overhaul", "rewrite", "restructure",
    "build a", "build the", "create the",
}

# Prefixes/keywords that indicate a quick fix or question — skip injection
QUICK_FIX_PREFIXES = ("how", "why", "what", "where", "when", "can you", "does", "is ", "are ")
QUICK_FIX_KEYWORDS = {"fix this", "typo", "rename", "explain", "run tests", "update this"}

ROUTING_GUIDANCE = (
    "[HARNESS] Multi-step task detected. Use /implement-task --multi to create an "
    "execution plan with verification gates before writing source files. For a single "
    "focused change with one clear deliverable, use /implement-task."
)

# Cold-open orientation directive -- injected on the session's FIRST prompt after a
# new-session SessionStart. Carries NO GOAL/blueprint data (so it cannot go stale);
# it points Claude at the continuity already in its context and forces a readout-first
# reply. Plain text on the same stdout channel as ROUTING_GUIDANCE.
# ⚠ Names the BANNER, never a section of it. This directive used to say
# "from GOAL / ACTIVE PLAN in your SessionStart banner" and "source the readout
# from the GOAL/blueprint", and this hook has ZERO self-host gates — so it ships
# that instruction to every adopter, none of whom have a `cc/GOAL.md` (`init`
# deploys no such file and nothing creates one). Worse, it names two sections
# the banner can carry NEITHER of on this event: the cold-open flag is written
# only on `startup`/`clear`, while an `ACTIVE PLAN` section is produced solely by
# `_build_compact_context`. Naming the banner keeps the directive true wherever
# it lands, and cannot go stale when a section's gating changes.
_COLD_OPEN_DIRECTIVE = (
    "[HARNESS] Cold open -- first prompt of a new session. Before anything else, "
    "emit a compact state readout for the operator, then proceed:\n"
    "  Working on: <current focus, from the continuity in your SessionStart banner>\n"
    "  Next:       <the immediate next action>\n"
    "  Owed:       <any deferred/owed item, or '--'>\n"
    "Follow it with ONE line of your provisional read of where things stand, THEN "
    "address the prompt below. Do not skip this even when the prompt is a concrete "
    "task -- the readout comes first. Source the readout from the continuity "
    "already in your context; if that context is thin, say so in one line rather "
    "than inventing."
)

# Decision-shape patterns. The advisory is `print()`-ed to the
# same plain-text stdout channel as ROUTING_GUIDANCE (UserPromptSubmit
# injects stdout as additional context per
# docs/external/cc-hook-protocol.md; there is NO JSON envelope here).
# When both fire on the same prompt, ROUTING_GUIDANCE prints first,
# then a blank line, then the decision advisory.
_DECISION_SHAPE_PATTERNS = (
    re.compile(r"\bshould\s+(?:i|we)\b", re.IGNORECASE),
    re.compile(r"\bchoose\s+between\b", re.IGNORECASE),
    re.compile(r"\b\w+\s+vs\.?\s+\w+\b", re.IGNORECASE),
    re.compile(r"\b(?:decide|deciding|decision)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+about\b", re.IGNORECASE),
    re.compile(r"\breconsider\b", re.IGNORECASE),
    re.compile(r"\bswitch\s+to\b", re.IGNORECASE),
    re.compile(r"\bbetter\s+to\s+(?:use|do|try)\b", re.IGNORECASE),
)

_BLUEPRINT_LATEST_REL = Path("cc") / "blueprints" / "latest.json"


def _classify(prompt: str) -> bool:
    """Return True if the prompt looks multi-step (warrants routing guidance)."""
    if not prompt or len(prompt) < 10:
        return False

    lower = prompt.lower().strip()

    # Questions and quick fixes never get routing guidance
    if lower.startswith(QUICK_FIX_PREFIXES):
        return False
    for kw in QUICK_FIX_KEYWORDS:
        if kw in lower:
            return False

    # Single-word prompts: skip
    if len(lower.split()) <= 2:
        return False

    # Check for multi-step indicators
    # Word-boundary match, not bare substring — `rebuild the index`
    # must not match `build`.
    for kw in MULTI_STEP_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", lower):
            return True

    return False


def _count_decisions_in_blueprint(blueprint_path: Path) -> int:
    """Read cc/blueprints/latest.json raw and count kind=='decision' entries.

    Stdlib-only — must NOT import espalier.cognitive_blueprint (task_router
    is a hook). Returns 0
    on missing file, unreadable file, malformed JSON, or missing
    reasoning_entries key, so the advisory silently no-ops on fresh sessions.
    """
    if not blueprint_path.is_file():
        return 0
    try:
        data = json.loads(blueprint_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # A BOM/non-UTF-8 latest.json raises UnicodeDecodeError
        # (a ValueError, not OSError) out of read_text(encoding="utf-8") —
        # degrade silently, mirroring post_compact / post_write_check (the
        # other readers of this same file).
        return 0
    entries = data.get("reasoning_entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return 0
    return sum(1 for e in entries if isinstance(e, dict) and e.get("kind") == "decision")


def _detect_decision_shape(prompt: str, blueprint_path: Path) -> str | None:
    """Two-condition gate:

      1. Prompt matches at least one _DECISION_SHAPE_PATTERNS regex, AND
      2. The active blueprint at `blueprint_path` has ≥1 kind=='decision' entry.

    Returns the advisory string to inject when both hold; otherwise None.
    The "blueprint has decisions" gate is non-optional — without it the
    advisory fires on every "should we" question including on fresh
    sessions, training the agent to ignore the channel.
    """
    if not prompt:
        return None
    if not any(p.search(prompt) for p in _DECISION_SHAPE_PATTERNS):
        return None
    count = _count_decisions_in_blueprint(blueprint_path)
    if count < 1:
        return None
    plural = "" if count == 1 else "s"
    return (
        f"[harness] Decision-shape prompt detected. You have {count} prior "
        f"decision{plural} recorded this session. Before answering, consider "
        f"surfacing them:\n"
        f"  python tools/cc/cognitive_blueprint.py show-recent --n 5 --kind decision"
    )


def _has_active_plan(root: Path | None = None) -> bool:
    """True iff an execution plan is OPEN — ``status == "in_progress"`` AND it
    has at least one step.

    Delegates to the single owner _hook_utils.has_active_plan, resolving the
    root relative to ``CLAUDE_PROJECT_DIR`` (the documented harness convention —
    see ``docs/CONVENTIONS.md`` "Hook Conventions") with cwd as the fallback.
    Routing through the canon makes this predicate truly agree with
    plan_guard's (same symlink-refusing read + fail-closed error domain) — the
    prior copy used a symlink-FOLLOWING is_file()+read_text().

    ``root`` is optional so a caller that has ALREADY resolved it can pass it
    in. ``_run_main`` had one, and re-resolving here emitted the
    "CLAUDE_PROJECT_DIR is empty" warning a SECOND time on every prompt when
    the variable is unset — one hook, two identical stderr lines. Defaulting
    to ``None`` rather than requiring the argument keeps the zero-arg call
    that the sister-predicate parity contract with ``plan_guard`` and the
    state-space pins in ``tests/test_task_router.py`` are written against;
    it also brings this signature into line with the twin, which has always
    taken a root.
    """
    return has_active_plan(resolve_project_root() if root is None else root)


def _consume_cold_open(root: Path) -> bool:
    """One-shot consumer half of the cold-open baton: True iff this is the
    session's first prompt after a new-session SessionStart. Reads and DELETES the
    flag the SessionStart producer dropped, so the directive fires exactly once per
    new session. Fail-open: any flag-I/O error returns False (no directive) rather
    than suppressing the routing advisories below or crashing this advisory hook.
    """
    # Presence-only baton: the flag's CONTENT is never read into the directive, so
    # the no-follow reader is intentionally not used here -- a planted symlink at
    # this path can at worst be unlinked, never sourced. A future flag that READS
    # content must use the no-follow posture.
    flag = root / STATE_DIR / COLD_OPEN_FLAG
    try:
        if not flag.is_file():
            return False
        flag.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def main() -> int:
    """Public entry-point. Umbrella try/except degrades any uncaught
    exception in ``_run_main`` to a no-op advisory (exit 0).

    task_router is the UserPromptSubmit advisory hook: it cannot and must
    not block. Per channel-XOR, exit 1 = a script bug — which here would
    spew a traceback on EVERY prompt. So the advisory tier fails OPEN
    (return 0), unlike the blocking sister hooks plan_guard / write_guard
    whose umbrellas fail closed (deny).
    """
    try:
        return _run_main()
    except BaseException as exc:  # noqa: BLE001 — fail-open crash guard (advisory hook)
        print(
            f"[ERROR] task_router crashed: {type(exc).__name__}: {os_error_text(exc)}",
            file=sys.stderr,
        )
        return 0


def _run_main() -> int:
    data = read_stdin_safely()

    prompt = data.get("prompt", "")
    if not isinstance(prompt, str):
        return 0

    root = resolve_project_root()

    printed_any = False
    # Cold-open orientation fires on the FIRST prompt of a new session, on the same
    # turn as that prompt -- so a task-first message can't silently preempt it. This
    # sits BEFORE the active-plan early-return below: a /clear into a planned task is
    # exactly when the operator most needs the where-was-I readout.
    if _consume_cold_open(root):
        print(_COLD_OPEN_DIRECTIVE)
        printed_any = True

    if _has_active_plan(root):
        return 0

    if _classify(prompt):
        if printed_any:
            print()
        print(ROUTING_GUIDANCE)
        printed_any = True

    # The decision-shape advisory composes additively with the scope
    # classifier above. Same plain-text stdout channel; blank line between
    # when both fire so they read as two distinct context blocks.
    blueprint_path = root / _BLUEPRINT_LATEST_REL
    advisory = _detect_decision_shape(prompt, blueprint_path)
    if advisory is not None:
        if printed_any:
            print()
        print(advisory)
        printed_any = True

    # The UserPromptSubmit face of the recall engine. _reinject.check
    # returns generative exemplar payloads to inject BEFORE the model drafts the
    # artifact. FRICTIONLESS (advisory only, never rejects) on the SAME plain-stdout
    # channel as the advisories above -- NOT a JSON additionalContext envelope (per
    # docs/external/cc-hook-protocol.md, plain stdout is injected as actionable
    # context on UserPromptSubmit). Inert until a generative REINJECTS row exists:
    # the EXEMPLAR_MAP catalog ships PULL-ONLY, so check() returns [] here today.
    # The dispatch is wired now so no later change re-touches this hook.
    for payload in _reinject.check("UserPromptSubmit", "", {"prompt": prompt}, root):
        if printed_any:
            print()
        print(payload)
        printed_any = True

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
