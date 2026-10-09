#!/usr/bin/env python3
"""PostToolUse hook — triggers reflect_protocol.py after source-file write milestones.

Advisory only (always exits 0). Tracks writes to project source files and
triggers reflect every 10th write, or immediately on config file changes.
What the pass finds, and a reflect pipeline gone dark, reach Claude in the
additionalContext of the ONE JSON object the hook prints at the end of its run
(``_hook_utils.emit_advisories``); stderr carries the debug copy, which is all
an exit-0 hook's stderr ever reaches (docs/external/cc-hook-protocol.md).

The same ``"*"`` matcher makes this the hook that sees an APPROVED
``ExitPlanMode``, so it carries the plan-mode bridge (INV-8): the approved
plan's Markdown becomes ``cc/execution_plan.json`` through
``execution_plan.build_plan``, and plan_guard allows the edits the user just
approved without a manual ``/implement-task``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tools/cc for _json_safe
import _hook_utils  # noqa: E402
from _json_safe import load_json_dict_safe, os_error_text  # noqa: E402

# Config files that trigger reflect immediately when written. The core project
# manifests derive from the single owner _hook_utils.PROJECT_MANIFEST_NAMES;
# settings.json is reflect-trigger-specific (a Claude Code config write).
CONFIG_FILES = set(_hook_utils.PROJECT_MANIFEST_NAMES) | {"settings.json"}

# Source file extensions to track
# The source-language core is owned by _hook_utils.SOURCE_LANGUAGE_EXTENSIONS so
# reflect-tracking and plan_guard's root gate cannot disagree on what is source.
SOURCE_LANGUAGE_EXTENSIONS = _hook_utils.SOURCE_LANGUAGE_EXTENSIONS

# Universal excluded prefixes — paths under these are not tracked for
# auto-reflect regardless of repo context. On the self-host repo, espalier/
# and tools/cc/ ARE source and should be tracked, so the runtime call uses
# _hook_utils.harness_excluded_prefixes() to drop them.
# sister-site: ok purpose-scoped: reflect-tracking exclusion (INCLUDES espalier/); distinct from plan_guard.EXEMPT_PREFIXES
EXCLUDED_PREFIXES = [
    "tests/",
    "tools/cc/",
    ".claude/",
    "espalier/",
    "cc/",
    "reports/",
]

# STATE_DIR + COUNTER_FILE + the flocked counter helpers live in _hook_utils so
# _speedbump.py reuses the same flock primitive. Aliased here (the existing
# alias shape, matching `_resolve_project_root` below) to keep every
# `reflect_trigger.STATE_DIR` / `._locked_increment` reference resolving — incl.
# the concurrency tests that `inspect.getsource` these names.
STATE_DIR = _hook_utils.STATE_DIR
COUNTER_FILE = _hook_utils.COUNTER_FILE
# Per-session agent-trajectory signals. tool_call_count counts
# EVERY tool invocation (not just source writes); last_tool tracks the
# identical-consecutive-tool streak (recursive-call detection). Both are
# siblings of write_count and are cleared per-session by
# session_start._clean_state_flags. The counter helpers below take an optional
# `name=` so the one flocked idiom serves write_count AND tool_call_count.
TOOL_CALL_COUNTER_FILE = "tool_call_count"
LAST_TOOL_FILE = "last_tool"
# One-shot WARN flag for missing
# reflect-pipeline scripts. Session_start._clean_state_flags clears
# this on every SessionStart so operators hear the WARN once per
# session.
WARN_FLAG_FILE = "reflect_trigger_warned"


_resolve_project_root = _hook_utils.resolve_project_root


# Aliased to `_hook_utils.normalize_path` (single source of truth). A non-str
# payload returns "<invalid>" rather than raising AttributeError — the same
# fail-closed shape `write_guard` already uses.
_normalize_path = _hook_utils.normalize_path


def _is_source_file(rel_path: str, root: Path) -> bool:
    """Return True if path is a project source file (not harness, not tests).

    Resolves the prefix list per-call via _hook_utils.harness_excluded_prefixes
    so the dogfood-reflect story works on the self-host repo (espalier/ and
    tools/cc/ ARE source there) without leaking into user repos.

    A path OUTSIDE ``root`` is never project source. The counter this feeds
    drives ``stop_gate`` Gate 2 ("significant changes may require doc updates"),
    so an out-of-root scratch write used to block a session whose tracked source
    had not changed at all -- observed three times, most sharply at
    ``write_count`` = 11 on a tree byte-identical to session start.

    Root-containment, deliberately NOT "tracked source". The wider predicate
    needs ``git check-ignore``: a subprocess per Write inside a PostToolUse hook
    that runs on every tool call, plus a non-git-repo failure path. Measured, it
    would catch nothing extra -- every in-root gitignored directory that can
    hold a ``.py`` is a cache or build artifact written only by subprocesses,
    and this counter is structurally unreachable from Bash (only
    Write/Edit/NotebookEdit and MCP write verbs reach it). Widen only if a real
    in-root gitignored ``.py`` write is ever observed.
    """
    if not _is_within_root(rel_path, root):
        return False
    for prefix in _hook_utils.harness_excluded_prefixes(root):
        if rel_path.startswith(prefix):
            return False
    ext = Path(rel_path).suffix.lower()
    if ext in SOURCE_LANGUAGE_EXTENSIONS:
        return True
    # The adopter's own source extensions (espalier.toml `source_extensions`),
    # read only for an extension the shipped set does not name, so a tree
    # that sets nothing pays no TOML read per write.
    return ext in _hook_utils.source_extensions(root, hook="reflect_trigger")


def _is_within_root(rel_path: str, root: Path) -> bool:
    """Return True if ``rel_path`` resolves inside ``root``.

    Handles both shapes the caller can produce: a repo-relative path (the
    normal case, always inside) and an absolute path that ``_normalize_path``
    could not reduce (the out-of-root case). ``..`` traversal escapes without
    being absolute, so containment is checked after resolution rather than by
    testing ``is_absolute()``.

    Fails OPEN -- an unresolvable path counts as inside, preserving the
    pre-existing behaviour rather than silently suppressing a real source write.
    """
    try:
        candidate = Path(rel_path)
        resolved = candidate if candidate.is_absolute() else (root / candidate)
        resolved = resolved.resolve()
        root_resolved = root.resolve()
    except (OSError, ValueError, RuntimeError):
        return True
    # Path comparison is normalized for Windows (repo convention).
    r = str(resolved).replace("\\", "/")
    b = str(root_resolved).replace("\\", "/").rstrip("/")
    return r == b or r.startswith(b + "/")


def _is_config_file(rel_path: str) -> bool:
    """Return True if this is a root-level config file that warrants immediate reflect."""
    filename = Path(rel_path).name
    if filename in CONFIG_FILES:
        return True
    # Root-level .yaml/.yml
    if Path(rel_path).parent == Path(".") and Path(rel_path).suffix in (".yaml", ".yml"):
        return True
    return False


# _read_counter / _write_counter / _locked_increment live in _hook_utils (the
# flocked session-state counter primitive `_speedbump.py` also reuses). Aliased
# here so every existing `reflect_trigger._locked_increment` / `._write_counter`
# reference still resolves — the concurrency tests `inspect.getsource` these
# names, and getsource follows the alias to the _hook_utils definition (which
# keeps the atomic-write / no-in-place-truncate body the tests pin).
_read_counter = _hook_utils._read_counter
_write_counter = _hook_utils._write_counter
_locked_increment = _hook_utils._locked_increment


def _track_last_tool(state_dir: Path, tool_name: str) -> int:
    """Identical-consecutive-tool streak (recursive-call signal).

    Persists ``last_tool`` as JSON ``{"tool": <name>, "streak": <n>}``; the
    streak increments when ``tool_name`` repeats the immediately-previous call,
    resets to 1 otherwise. BEST-EFFORT advisory — a read/write failure or a
    concurrent-session interleave just yields a momentarily-off streak, which
    is acceptable for a warn-only signal; we deliberately do NOT pay a second
    flock for it (the primary ``tool_call_count`` IS flocked). Never raises.
    """
    path = state_dir / LAST_TOOL_FILE
    prev_tool, prev_streak = None, 0
    if path.exists():
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                prev_tool = obj.get("tool")
                prev_streak = int(obj.get("streak", 0) or 0)
        except (OSError, ValueError):
            prev_tool, prev_streak = None, 0
    streak = prev_streak + 1 if prev_tool == tool_name else 1
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        _hook_utils.atomic_write_text(
            path, json.dumps({"tool": tool_name, "streak": streak})
        )
    except OSError:
        pass
    return streak


def _record_tool_call(state_dir: Path, tool_name: str) -> tuple[int, int]:
    """Bump the per-session tool-call odometer + the streak.

    Returns ``(tool_call_count, streak)``. ``tool_call_count`` goes through the
    same flocked ``_locked_increment`` as ``write_count`` (atomic,
    cross-session-safe) because the burst/trajectory advisories read it;
    ``last_tool`` is best-effort (see ``_track_last_tool``).
    """
    count = _locked_increment(state_dir, name=TOOL_CALL_COUNTER_FILE)
    streak = _track_last_tool(state_dir, tool_name)
    return count, streak


# ── The plan-mode bridge (INV-8) ─────────────────────────────────────────────
# Claude Code's ExitPlanMode tool fires PostToolUse only once the user has
# APPROVED the plan: a rejection fails the tool and goes to PostToolUseFailure
# (docs/HOOK_ASSUMPTIONS.md §7.1; driven on the self-host tree 2026-10-09, a
# rejected ExitPlanMode left last_tool untouched). The approved plan opens
# cc/execution_plan.json through execution_plan.build_plan, the same shape the
# CLI writes, so plan_guard allows the edits the user just approved. Nothing
# closes the window but the plan's own verbs, as for a CLI-created plan; the
# advisory names them. An in_progress plan is REPLACED (the approval seconds
# ago is the user's current intent) and the superseded task is named.
PLAN_MODE_TOOL = "ExitPlanMode"
PLAN_BRIDGE_MAX_STEPS = 30
PLAN_BRIDGE_STEP_CHARS = 300
#: The approval text Claude Code hands the model as the tool result. A string
#: tool_response that does not begin with it is not an approval the bridge
#: recognises: it writes nothing and names the shape (the pinned protocol
#: excerpt never describes tool_response, so the bridge fails CLOSED on the
#: window and OPEN on the hook).
PLAN_APPROVED_PREFIX = "User has approved"
#: Headings that FRAME a plan rather than step it, lower-cased, matched on the
#: heading's opening words. Purpose-scoped to plan prose -- none is a stack
#: directory name, and 'test'/'tests' stay out of it on purpose.
_PLAN_FRAME_HEADINGS = (
    "context", "background", "overview", "summary", "motivation", "problem",
    "goal", "goals", "non-goals", "non goals", "out of scope", "scope",
    "open questions", "decisions", "risks", "notes", "references",
    "known limit", "known limits", "not doing",
)
_PLAN_NOT_DOING_HEADINGS = ("non-goals", "non goals", "out of scope", "not doing")
#: The one ``why_not`` that is a decision, not a shape fault: a subagent's
#: approval. Every other refusal is recorded once a session as a fault, so
#: ``/status --log`` shows a Claude Code whose stdin JSON moved.
PLAN_SUBAGENT_SKIP = "a subagent's plan (isAgent on the object-shaped result), not this session's"
_PLAN_FIXED_NOT_DOING = "not stated in the approved plan"
# Line-anchored and bounded, applied one line at a time after splitlines():
# no dotstar, no nested quantifier, so a 30 KB plan costs one pass.
_NUMBERED_ITEM_RE = re.compile(r"^ {0,2}\d{1,3}[.)] {1,4}")  # a top-level ordered item (3+ spaces, or a tab, is nested)
_HEADING_RE = re.compile(r"^#{2,3} {1,4}")
_H1_RE = re.compile(r"^# {1,4}")
_FENCE_RE = re.compile(r"^ {0,3}(```|~~~)")
_BULLET_RE = re.compile(r"^ {0,3}[-*+] {1,4}")


def _plan_lines_outside_fences(text: str) -> list[str]:
    """The plan's lines with every fenced code block dropped (a ``1.`` inside
    a shell example is not a step)."""
    out: list[str] = []
    fence: str | None = None  # the delimiter that opened the block; only it closes it
    for line in text.splitlines():
        m = _FENCE_RE.match(line)
        if m and fence is None:
            fence = m.group(1)
            continue
        if m and m.group(1) == fence:
            fence = None
            continue
        if fence is None:
            out.append(line.rstrip())
    return out


def _clean_step(text: str) -> str:
    """One line of plain text for a step: whitespace collapsed, emphasis and
    code marks dropped, the CLI's pipe separator replaced, length capped."""
    s = " ".join(text.replace("**", "").replace("`", "").split()).replace("|", "/").strip()
    if len(s) > PLAN_BRIDGE_STEP_CHARS:
        s = s[: PLAN_BRIDGE_STEP_CHARS - 3].rstrip() + "..."
    return s


def _heading_text(line: str) -> str:
    """The heading's text: the opening hashes, an ATX closing run of hashes
    and a trailing colon dropped."""
    body = re.sub(r"[ \t]+#+[ \t]*$", "", line.lstrip("#").strip())
    return body.strip().rstrip(":").strip()


def _is_frame_heading(title: str) -> bool:
    low = title.lower().strip(" *_`")
    return any(low == h or low.startswith(h + " ") or low.startswith(h + ":") for h in _PLAN_FRAME_HEADINGS)


def _cap_steps(steps: list[str]) -> list[str]:
    if len(steps) <= PLAN_BRIDGE_MAX_STEPS:
        return steps
    kept = steps[: PLAN_BRIDGE_MAX_STEPS - 1]
    return kept + [f"...and {len(steps) - len(kept)} more items in the plan file"]


def _plan_title(text: str, plan_file: str) -> str:
    """The plan's H1, else a name from its file, else a fixed name."""
    for ln in _plan_lines_outside_fences(text):
        if _H1_RE.match(ln):
            title = _clean_step(_heading_text(ln))
            if title:
                return title[:160]
    stem = Path(plan_file).stem if plan_file else ""
    return f"approved plan-mode plan ({stem})" if stem else "approved plan-mode plan"


def _steps_from_plan(text: str) -> list[str]:
    """Steps from an approved plan's Markdown: its top-level numbered items
    outside fenced code; else its ``##``/``###`` headings minus the ones that
    frame the plan; else one step naming the title. Never empty: plan_guard
    reads an empty step list as no plan."""
    lines = _plan_lines_outside_fences(text)
    # A numbered list under a FRAME heading (Decisions, Context, Risks) is
    # not the plan's steps; the first smoke on a real plan turned four
    # numbered decisions into steps 1-4.
    numbered: list[str] = []
    frame_level = 0  # the depth of the frame heading we are under; 0 outside one
    for ln in lines:
        if _H1_RE.match(ln):
            frame_level = 0
            continue
        if _HEADING_RE.match(ln):
            level = len(ln) - len(ln.lstrip("#"))
            if frame_level and level > frame_level:
                continue  # a sub-heading inside a frame section stays framed
            frame_level = level if _is_frame_heading(_heading_text(ln)) else 0
            continue
        if not frame_level and _NUMBERED_ITEM_RE.match(ln):
            step = _clean_step(_NUMBERED_ITEM_RE.sub("", ln, count=1))
            if step:
                numbered.append(step)
    if numbered:
        return _cap_steps(numbered)
    headings = [_clean_step(_heading_text(ln)) for ln in lines if _HEADING_RE.match(ln)]
    headings = [h for h in headings if h and not _is_frame_heading(h)]
    if headings:
        return _cap_steps(headings)
    for ln in lines:
        if _H1_RE.match(ln) and _clean_step(_heading_text(ln)):
            return [f"Execute the approved plan: {_clean_step(_heading_text(ln))[:160]}"]
    return ["Execute the approved plan"]


def _not_doing_from_plan(text: str) -> str:
    """The first line under a Non-goals / Out of scope heading, else a fixed
    sentence: auto-compose of the action_justification needs ``not_doing``
    and ``goal`` both non-empty, so an empty field would silently drop it."""
    lines = _plan_lines_outside_fences(text)
    for i, ln in enumerate(lines):
        if not _HEADING_RE.match(ln):
            continue
        low = _heading_text(ln).lower().strip(" *_`")
        if not any(low == h or low.startswith(h + " ") or low.startswith(h + ":") for h in _PLAN_NOT_DOING_HEADINGS):
            continue
        for nxt in lines[i + 1:]:
            if _HEADING_RE.match(nxt) or _H1_RE.match(nxt):
                break
            body = _clean_step(_BULLET_RE.sub("", nxt, count=1))
            if body:
                return body
    return _PLAN_FIXED_NOT_DOING


def _approved_plan_text(data: dict) -> tuple[str, str, str]:
    """``(plan_text, plan_file, why_not)`` -- the plan an APPROVAL carries, read
    from a success-shaped payload only: ``tool_response`` an object with a
    non-empty ``plan`` string (its ``filePath`` beside it), or the approval
    text as a string with ``tool_input.plan`` as the text. Anything else is
    ``("", "", reason)`` and the bridge writes nothing. A subagent's approval
    -- ``isAgent``, which the object-shaped result carries; the string shape
    has no such signal -- must not open the main session's window."""
    tool_input = data.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    resp = data.get("tool_response")
    if isinstance(resp, dict):
        if resp.get("isAgent") is True:
            return "", "", PLAN_SUBAGENT_SKIP
        plan = resp.get("plan")
        if isinstance(plan, str) and plan.strip():
            path = resp.get("filePath") or tool_input.get("planFilePath") or ""
            return plan, path if isinstance(path, str) else "", ""
        return "", "", f"tool_response is an object without a plan text (keys: {sorted(map(str, resp))[:8]})"
    if isinstance(resp, str) and resp.startswith(PLAN_APPROVED_PREFIX):
        plan = tool_input.get("plan")
        if isinstance(plan, str) and plan.strip():
            path = tool_input.get("planFilePath") or ""
            return plan, path if isinstance(path, str) else "", ""
        return "", "", "the approval text arrived with no plan in tool_input"
    return "", "", f"tool_response is {type(resp).__name__}, not an approval the bridge reads"


def _superseded_note(plan_path: Path) -> str:
    """``'<task> (k/n passed)'`` when an in_progress plan is about to be
    replaced, else ``''``. Read through the json-dict-safe chokepoint."""
    try:
        raw = plan_path.read_bytes()
    except OSError:  # fail-open: ok deliberate -- no file, or an unreadable one, is no plan to name
        return ""
    old = load_json_dict_safe(raw, default=None)
    if not isinstance(old, dict) or old.get("status") != "in_progress":
        return ""
    raw_steps = old.get("steps")
    steps = [s for s in raw_steps if isinstance(s, dict)] if isinstance(raw_steps, list) else []
    done = sum(1 for s in steps if s.get("status") == "passed")
    task = str(old.get("task", "") or "")[:120]
    return f"{task or 'an unnamed plan'} ({done}/{len(steps)} passed)"


def _bridge_approved_plan(data: dict, root: Path) -> None:
    """Open ``cc/execution_plan.json`` from an approved plan-mode plan and say
    so in the hook's one JSON object. Advisory: every failure is fail-open
    with voice (one record + one seen line), never a raise past here."""
    try:
        plan_text, plan_file, why_not = _approved_plan_text(data)
        if why_not == PLAN_SUBAGENT_SKIP:
            _hook_utils.advise(f"[INFO] plan-mode bridge: no execution plan opened -- {why_not}")
            return
        if why_not:
            # A shape the bridge does not read is a Claude Code that moved:
            # the record keeps it visible past this turn (`/status --log`).
            _hook_utils.say_once(
                root, "plan-bridge-shape", "reflect_trigger",
                "posttooluse_failed_open_plan_bridge_shape",
                f"plan-mode bridge: no execution plan opened -- {why_not}",
            )
            _hook_utils.advise(
                f"[WARN] plan-mode bridge: no execution plan opened -- {why_not}; "
                f"open the plan by hand: python tools/cc/execution_plan.py create",
                echo=False,
            )
            return
        try:
            import execution_plan  # lazy: only an approval pays for it; tools/cc is on sys.path above
        except ImportError as exc:  # fail-open: ok deliberate -- a deploy without the module keeps the window as it was, and the line says so
            _hook_utils.advise(
                f"[WARN] plan-mode bridge: tools/cc/execution_plan.py is not importable "
                f"({type(exc).__name__}); open the plan by hand: python tools/cc/execution_plan.py create"
            )
            return
        if not hasattr(execution_plan, "build_plan"):
            # An upgrade preserves a user-edited tools/cc file: the module
            # predates the bridge and the generic handler would name a class.
            _hook_utils.advise(
                "[WARN] plan-mode bridge: tools/cc/execution_plan.py predates the bridge (no build_plan) -- "
                "an upgrade preserved a user edit of it; add the `# espalier:managed` marker line and run "
                "`espalier upgrade --execute`, or open the plan by hand: python tools/cc/execution_plan.py create"
            )
            return
        plan_path = root / "cc" / "execution_plan.json"
        superseded = _superseded_note(plan_path)
        demoted = ""
        if superseded:
            # Its passed steps, notes and timestamps are reasoning: demote
            # the file beside the blueprint cold store as `reset` does, never
            # overwrite it in place.
            try:
                cold = execution_plan.demote_plan(plan_path)
                demoted = str(cold.relative_to(root)).replace("\\", "/") if cold else ""
            except (OSError, ValueError) as exc:  # fail-open: ok deliberate -- the cold store could not be written; the plan is overwritten and the line says so
                demoted = f"NOT demoted ({type(exc).__name__}), overwritten"
        steps = _steps_from_plan(plan_text)
        task = _plan_title(plan_text, plan_file)
        goal = "approved in plan mode" + (f" -- {plan_file}" if plan_file else "")
        plan = execution_plan.build_plan(task, steps, goal, _not_doing_from_plan(plan_text))
        execution_plan.save_plan(plan, plan_path)
        line = (
            f"[INFO] plan-mode bridge: cc/execution_plan.json opened from the approved plan -- "
            f"{len(steps)} step{'s' if len(steps) != 1 else ''}; source writes are allowed; "
            f"python tools/cc/execution_plan.py status, and mark <i> passed as you go"
        )
        if superseded:
            line += f"; superseded: {superseded}" + (f", demoted to {demoted}" if demoted else "")
        _hook_utils.advise(line)
        try:
            # The other machine's live claims this plan meets (the mail
            # channel): the same advisory `create` prints, kept for the one
            # JSON object. Silent where no machine is named.
            for claim_line in execution_plan._claim_overlaps("|".join(steps)):
                _hook_utils.advise(f"[WARN] plan-mode bridge: {claim_line}")
        except Exception as exc:  # noqa: BLE001 -- fail-open: ok telemetry -- the claim read is advisory; the plan is already written
            _hook_utils.advise_exc("plan-mode bridge: claim overlap read failed", exc)
    except Exception as exc:  # noqa: BLE001 -- fail open, with voice: the counter already ran; the window stays as it was
        _hook_utils.say_once(
            root, f"plan-bridge-{type(exc).__name__}", "reflect_trigger",
            "posttooluse_failed_open_plan_bridge",
            f"plan-mode bridge failed ({type(exc).__name__}); open the plan by hand: "
            f"python tools/cc/execution_plan.py create",
            fault=type(exc).__name__,
        )
        _hook_utils.advise(  # the seen twin of the record above (say_once printed the debug copy)
            f"[WARN] plan-mode bridge failed ({type(exc).__name__}); open the plan by hand: "
            f"python tools/cc/execution_plan.py create",
            echo=False,
        )


def _warn_once_about_missing(
    root: Path, missing: str, effect: str = "drift detection DISABLED",
) -> None:
    """Say once a session that a reflect-pipeline script is absent, in the
    hook's advisory (stderr keeps the debug copy). Without it the trigger
    silently no-ops and nobody learns drift detection is dark.

    The flag suppresses repeat WARNs within a session — every 10th write
    fires _run_reflect, so without the gate the WARN would repeat on every
    pass. session_start._clean_state_flags clears the flag at SessionStart.
    """
    flag = root / STATE_DIR / WARN_FLAG_FILE
    if flag.exists():
        return
    try:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(missing, encoding="utf-8")
    except OSError:
        # Best-effort flag; the WARN still emits even if the flag
        # write fails. Operator gets the WARN multiple times in this
        # session but the missing-script information still surfaces.
        pass
    _hook_utils.advise(
        f"[WARN] reflect_trigger: {missing} not found -- {effect}. "
        "Run `espalier init .` to restore the reflect pipeline.",
    )


def _render_reflect_report(report: dict) -> None:
    """Print the human-readable reflect summary to stderr (the debug log) and,
    on a non-clean pass, keep the advisory for the hook's one JSON object
    (``_hook_utils.advise``), which reaches Claude next to the tool result.
    Per-finding observable-sentinel logic stays here and never raises on
    producer drift."""
    findings = report.get("findings", [])
    gap_count = report.get("gap_count", 0)
    orphan_count = report.get("orphan_count", 0)
    files_analyzed = report.get("files_analyzed", 0)
    # On a clean reflect (no findings, no gaps, no orphans), emit a single line
    # instead of a 7-line block. Heavy sessions trigger reflect every 10 writes,
    # so the full block would be 7 lines of noise per fire even when the surface
    # is coherent.
    if not findings and gap_count == 0 and orphan_count == 0:
        # voice: debug-log a clean pass injects nothing mid-flow, by the decision its test pins
        print(
            f"[reflect] clean -- {files_analyzed} files, surface coherent",
            file=sys.stderr,
        )
        return
    # Use ASCII separator so log sinks that strip non-ASCII don't
    # render the divider as garbage.
    print("=== REFLECT TRIGGER (auto) ===", file=sys.stderr)
    print(f"  Files analyzed:    {files_analyzed}", file=sys.stderr)
    print(f"  Cross-ref density: {report.get('cross_ref_density', 0)} refs/file", file=sys.stderr)
    print(f"  Gaps:              {gap_count}", file=sys.stderr)
    print(f"  Orphans:           {orphan_count}", file=sys.stderr)
    for f in findings:
        # Observable sentinels -- a finding missing OR null-valued
        # kind/severity/description renders (UNKNOWN / <missing description>)
        # instead of crashing the advisory hook. `.get(k) or default` coalesces
        # BOTH the absent key AND a present-but-None value (producer drift) --
        # `.get(k, default)` would leave None and crash `kind.upper()`. A row
        # that is not a mapping at all is drift too, and says so.
        if not isinstance(f, dict):
            # voice: twin the advisory below counts every finding; this row is the debug copy
            print(f"  [UNKNOWN] <malformed finding: {type(f).__name__}>", file=sys.stderr)
            continue
        severity = f.get("severity") or "UNKNOWN"
        kind = f.get("kind") or "UNKNOWN"
        description = f.get("description") or "<missing description>"
        sev = f"[{severity}] " if severity != "low" else ""
        # voice: twin the advisory below names the first three findings, most severe first
        print(f"  [{kind.upper()}] {sev}{description}", file=sys.stderr)
    print("=" * 30, file=sys.stderr)

    # Surface the drift to the AGENT: the stderr above reaches the debug log
    # only (exit 0; docs/external/cc-hook-protocol.md), while PostToolUse
    # additionalContext reaches the model. Non-clean branch ONLY. Kept in the
    # collector, not printed here: the hook prints ONE JSON object at the end
    # of its run (two stdout JSON lines fail the whole parse).
    _hook_utils.advise(
        f"Reflect pass flagged surface drift: "
        f"{_hook_utils.plural(gap_count, 'gap')}, "
        f"{_hook_utils.plural(orphan_count, 'orphan')}, "
        f"{_hook_utils.plural(len(findings), 'finding')} across "
        f"{files_analyzed} files. Review before continuing."
        + _named_findings(findings),
        echo=False,
    )


#: How many findings the advisory names, and how much of each description it
#: carries: enough for the model to open the right file, short enough that a
#: large pass stays one paragraph. The full list stays on stderr for the
#: operator and in `reflect_protocol.py --json`.
_ADVISORY_NAMED_FINDINGS = 3
_ADVISORY_DESCRIPTION_CAP = 200
#: Most severe first, so three unlinked docs never crowd a broken link out of
#: the names the model sees (the report lists orphans first, broken links last).
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _named_findings(findings: list) -> str:
    """' First: [KIND] description; ... and N more.' -- the findings the counts
    above summarise, by name, most severe first and a gap before an orphan at
    the same severity. The stderr block carries the same text, but the model
    never sees stderr from an exit-0 hook, so without this the advisory told it
    to review drift without saying where (C62)."""
    usable = [f for f in findings if isinstance(f, dict)]
    usable.sort(key=lambda f: (_SEVERITY_RANK.get(str(f.get("severity")), 3),
                               0 if f.get("kind") == "gap" else 1))
    named = []
    for f in usable[:_ADVISORY_NAMED_FINDINGS]:
        kind = str(f.get("kind") or "unknown").upper()
        description = str(f.get("description") or "<missing description>")
        if len(description) > _ADVISORY_DESCRIPTION_CAP:
            description = description[:_ADVISORY_DESCRIPTION_CAP - 3] + "..."
        named.append(f"[{kind}] {description}")
    if not named:
        return ""
    more = len(usable) - len(named)
    return (" First: " + "; ".join(named)
            + (f"; and {more} more (reflect_protocol.py --json lists all)" if more > 0 else "")
            + ".")


def _record_reflect_to_blueprint(root: Path, env: dict, raw: str) -> None:
    """Record the reflect pass into the active blueprint via a bounded
    subprocess. Symmetric WARN when the blueprint script is dark;
    a blueprint timeout warns but never aborts the render that already happened."""
    blueprint_script = root / "tools" / "cc" / "cognitive_blueprint.py"
    if not blueprint_script.exists():
        # Symmetric WARN: blueprint record path is dark. The pass itself ran,
        # so the line says what is lost -- the record -- not that drift
        # detection is off: Claude reads this line now, not only a debug log.
        _warn_once_about_missing(
            root, "tools/cc/cognitive_blueprint.py",
            "reflect passes are not recorded to the blueprint",
        )
        return
    try:
        subprocess.run(  # spawn: ok a reporter's helper; a record that cannot be spawned is warned in its handler
            [sys.executable, str(blueprint_script), "record-reflect",
             "--data", raw],
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=10,
            cwd=str(root),
            env=env,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        _hook_utils.advise_exc("reflect: blueprint record failed", e)


def _run_reflect(root: Path) -> None:
    """Run reflect_protocol.py, keep its advisory for the hook's JSON object
    (stderr carries the debug copy), and record to blueprint."""
    reflect_script = root / "tools" / "cc" / "reflect_protocol.py"
    if not reflect_script.exists():
        _warn_once_about_missing(root, "tools/cc/reflect_protocol.py")
        return

    # env= pins CLAUDE_PROJECT_DIR to root for both the reflect_protocol
    # invocation and the subsequent record-reflect blueprint write below.
    # cognitive_blueprint._repo_root() prefers the env var over cwd; the
    # symmetry on reflect_protocol future-proofs against added coupling.
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    try:
        result = subprocess.run(  # spawn: ok a reporter's helper; a reflect pass that cannot be spawned is warned in its handler
            [sys.executable, str(reflect_script), "--pass", "1", "--json"],
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=25,
            cwd=str(root),
            env=env,
        )
        if not result.stdout.strip():
            return

        # Parse JSON report. A non-dict report parses cleanly
        # but report.get(...) below would crash the advisory hook; route it to
        # the SAME raw-output fallback as malformed JSON (default=None).
        report = load_json_dict_safe(result.stdout, default=None)
        if report is None:
            # Fallback: the raw output, on stderr (the debug log), and a line
            # in the advisory saying the pass ran but could not be read.
            _hook_utils.advise(
                "[WARN] reflect_trigger: the reflect pass printed no JSON object, so its "
                "findings could not be read; run tools/cc/reflect_protocol.py --pass 1 --json",
            )
            print("=== REFLECT TRIGGER (auto) ===", file=sys.stderr)
            for line in result.stdout.strip().splitlines():
                # voice: twin the advisory above says the report was unreadable; this is its raw text
                print(f"  {line}", file=sys.stderr)
            print("=" * 30, file=sys.stderr)
            return

        _render_reflect_report(report)

        _record_reflect_to_blueprint(root, env, result.stdout.strip())

    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        _hook_utils.advise(f"[WARN] reflect_trigger: {type(e).__name__}: {os_error_text(e)}")


def main() -> int:
    """Public entry-point. Fail-OPEN umbrella: reflect_trigger is an advisory
    PostToolUse hook, so an uncaught crash in ``_run_main`` (producer schema
    drift, etc.) must degrade to a no-op advisory (exit 0 + one [ERROR] line),
    NOT a per-write traceback. Mirrors task_router.main — the
    advisory tier fails OPEN, unlike the blocking hooks' fail-closed umbrellas.
    """
    try:
        return _run_main()
    except BaseException as exc:  # noqa: BLE001 — fail-open crash guard (advisory hook)
        # Exit 0, so a stderr line alone reaches the debug log only (the
        # protocol pin): the record, once a session, is what `/status --log`
        # counts. Class name only, never the message's payload text.
        _hook_utils.say_crash(
            "reflect_trigger", "posttooluse_failed_open_reflect_crash", exc,
            "the write counter and the reflect pass did not run for this call",
        )
        return 0


def _run_main() -> int:
    _hook_utils.take_advisories()  # a line an in-process caller left is not this run's
    data = _hook_utils.read_stdin_safely()
    if not data:
        return 0
    try:
        return _track(data)
    finally:
        # The ONE JSON object: whatever the reflect pass and its helpers kept.
        _hook_utils.emit_advisories("PostToolUse")


def _track(data: dict) -> int:
    """The body of ``_run_main``: count the call, and run the reflect pass on
    a config write or every 10th source write."""

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}

    root = _resolve_project_root()
    _hook_utils.say_stack_table_fault(root, "reflect_trigger")
    state_dir = root / STATE_DIR

    # Count EVERY tool invocation (Read/Bash/Grep/Write/MCP/...), not just
    # source writes. This MUST precede the write-tool filter below: that
    # `return 0` is the binding early-return dropping non-write calls, so a
    # counter placed after it would only ever see writes.
    # Advisory only; stop_gate reads tool_call_count for the burst and
    # trajectory warnings. Skip empty tool_name (malformed payload).
    if tool_name:
        _record_tool_call(state_dir, tool_name)

    # The plan-mode bridge (INV-8): an APPROVED ExitPlanMode opens the
    # execution plan. Before the write-tool filter below, which drops every
    # non-write tool; after the counter, so the approval counts as a call.
    if tool_name == PLAN_MODE_TOOL:
        _bridge_approved_plan(data, root)
        return 0

    # Include MCP write tools so the reflect cadence still fires
    # under MCP-heavy workflows (e.g., agent using `mcp__filesystem__write_file`
    # rather than the built-in Write tool); otherwise the early-return drops MCP
    # writes from the counter and the every-10th-write trigger never fires.
    is_native_write = tool_name in ("Write", "Edit", "NotebookEdit")
    is_mcp_write = (
        tool_name.startswith("mcp__")
        and any(
            verb in tool_name.lower()
            for verb in _hook_utils.MCP_WRITE_VERB_SUBSTRINGS
        )
    )
    if not (is_native_write or is_mcp_write):
        return 0

    # MCP tool_input uses `path` more often than `file_path`. Sweep both.
    file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
    rel_path = _normalize_path(file_path, root)

    # Trigger immediately on config file changes
    if _is_config_file(rel_path):
        _run_reflect(root)
        return 0

    # Only count source file writes
    if not _is_source_file(rel_path, root):
        return 0

    # Atomic increment under the file lock (flock / LockFileEx) — no
    # concurrent-hook drift on any OS; its degrade is documented in
    # _locked_increment.
    count = _locked_increment(state_dir)

    # Trigger every 10th source file write
    if count % 10 == 0:
        _run_reflect(root)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
