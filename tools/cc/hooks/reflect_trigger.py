#!/usr/bin/env python3
"""PostToolUse hook — triggers reflect_protocol.py after source-file write milestones.

Advisory only (always exits 0). Tracks writes to project source files and
triggers reflect every 10th write, or immediately on config file changes.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tools/cc for _json_safe
import _hook_utils  # noqa: E402
from _hook_utils import warn_exc  # noqa: E402
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
    return ext in SOURCE_LANGUAGE_EXTENSIONS


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


def _warn_once_about_missing(root: Path, missing: str) -> None:
    """Emit one-shot stderr WARN per session when a reflect-pipeline script is
    absent. Without it the trigger silently no-ops and the operator never
    learns drift detection is dark.

    The flag suppresses repeat WARNs within a session — every 10th write
    fires _run_reflect, so without the gate the WARN would spam stderr.
    session_start._clean_state_flags clears the flag at SessionStart.
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
    print(
        f"[WARN] reflect_trigger: {missing} not found -- drift detection "
        "DISABLED. Run `espalier init .` to restore the reflect pipeline.",
        file=sys.stderr,
    )


def _render_reflect_report(report: dict) -> None:
    """Print the human-readable reflect summary to stderr and, on a non-clean
    pass, emit the structured PostToolUse additionalContext channel.
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
        # `.get(k, default)` would leave None and crash `kind.upper()`.
        severity = f.get("severity") or "UNKNOWN"
        kind = f.get("kind") or "UNKNOWN"
        description = f.get("description") or "<missing description>"
        sev = f"[{severity}] " if severity != "low" else ""
        print(f"  [{kind.upper()}] {sev}{description}", file=sys.stderr)
    print("=" * 30, file=sys.stderr)

    # Surface the drift to the AGENT, not only the
    # operator's stderr. PostToolUse additionalContext reaches the model
    # (docs/external/cc-hook-protocol.md). Non-clean branch ONLY. Channel-XOR:
    # exit 0 + this stdout JSON is the structured channel; the stderr above is
    # incidental operator debug.
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"Reflect pass flagged surface drift: "
                f"{_hook_utils.plural(gap_count, 'gap')}, "
                f"{_hook_utils.plural(orphan_count, 'orphan')}, "
                f"{_hook_utils.plural(len(findings), 'finding')} across "
                f"{files_analyzed} files. Review before continuing."
            ),
        }
    }))


def _record_reflect_to_blueprint(root: Path, env: dict, raw: str) -> None:
    """Record the reflect pass into the active blueprint via a bounded
    subprocess. Symmetric WARN when the blueprint script is dark;
    a blueprint timeout warns but never aborts the render that already happened."""
    blueprint_script = root / "tools" / "cc" / "cognitive_blueprint.py"
    if not blueprint_script.exists():
        # Symmetric WARN: blueprint record path is dark.
        _warn_once_about_missing(root, "tools/cc/cognitive_blueprint.py")
        return
    try:
        subprocess.run(
            [sys.executable, str(blueprint_script), "record-reflect",
             "--data", raw],
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=10,
            cwd=str(root),
            env=env,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        warn_exc("reflect: blueprint record failed", e)


def _run_reflect(root: Path) -> None:
    """Run reflect_protocol.py, print results to stderr, and record to blueprint."""
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
        result = subprocess.run(
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
            # Fallback: print raw output if JSON parse fails / is non-object.
            print("=== REFLECT TRIGGER (auto) ===", file=sys.stderr)
            for line in result.stdout.strip().splitlines():
                print(f"  {line}", file=sys.stderr)
            print("=" * 30, file=sys.stderr)
            return

        _render_reflect_report(report)

        _record_reflect_to_blueprint(root, env, result.stdout.strip())

    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        print(f"[WARN] reflect_trigger: {type(e).__name__}: {os_error_text(e)}", file=sys.stderr)


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
        print(
            f"[ERROR] reflect_trigger crashed: {type(exc).__name__}: {os_error_text(exc)}",
            file=sys.stderr,
        )
        return 0


def _run_main() -> int:
    data = _hook_utils.read_stdin_safely()
    if not data:
        return 0

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}

    root = _resolve_project_root()
    state_dir = root / STATE_DIR

    # Count EVERY tool invocation (Read/Bash/Grep/Write/MCP/...), not just
    # source writes. This MUST precede the write-tool filter below: that
    # `return 0` is the binding early-return dropping non-write calls, so a
    # counter placed after it would only ever see writes.
    # Advisory only; stop_gate reads tool_call_count for the burst and
    # trajectory warnings. Skip empty tool_name (malformed payload).
    if tool_name:
        _record_tool_call(state_dir, tool_name)

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

    # Atomic increment under flock (POSIX) — no concurrent-session
    # drift. Windows fall-through is documented in _locked_increment.
    count = _locked_increment(state_dir)

    # Trigger every 10th source file write
    if count % 10 == 0:
        _run_reflect(root)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
