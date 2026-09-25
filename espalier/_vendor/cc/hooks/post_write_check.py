#!/usr/bin/env python3
"""PostToolUse hook — validates writes to harness infrastructure files.

Advisory only (always exits 0). Prints warnings to stderr.
Triggers on: .claude/settings.json, .claude/agents/*.md, .claude/commands/*.md,
             tools/cc/**/*.py, root .md files (CLAUDE.md, ESPALIER_MEMORY.md, etc.)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _integrity  # noqa: E402
import _hook_utils  # noqa: E402
import _reinject  # noqa: E402
from _hook_utils import warn  # noqa: E402

# SoT for cc/ path strings. Lives one directory up at tools/cc/_paths.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _paths  # noqa: E402
from _json_safe import decode_text_or_problem, os_error_text  # noqa: E402

PLACEHOLDERS = ["<repo>", "<fill>", "INSERT HERE", "TEMPLATE_ONLY"]

# ESPALIER_MEMORY.md autoprune contract.
# Pinned to ``tests/test_documented_claims.py``'s ``ESPALIER_MEMORY.md line cap``
# NumericContract (expected_value=120). If the cap changes, update that
# contract — this constant binds to it. ``_AUTOPRUNE_HEADROOM`` keeps
# the file at ``cap - headroom`` after a prune so a subsequent single-row
# append doesn't immediately re-trip the cap.
_MEMORY_MD_CAP = 120
_AUTOPRUNE_HEADROOM = 1

# ⚠ TRAP FOR ANYONE ADDING AN EVENT-LEVEL BUDGET HERE. The guard below is
# ``line_count <= _MEMORY_MD_CAP: return``, so by the time ``excess`` is computed
# it is at least ``_AUTOPRUNE_HEADROOM + 1`` -- i.e. at least 2 today, on EVERY
# invocation. A "this is more than routine session turnover" advisory keyed on a
# LITERAL threshold was designed on 2026-08-20 and killed on that measurement: at
# 1 it is unreachable dead code, at 2 it fires on every routine /handoff. If such
# a budget is ever wanted, DERIVE it (``_AUTOPRUNE_HEADROOM + 1``) and have its
# test assert the RELATION to the headroom -- an assertion of ``>= 1`` is green at
# both the broken value and the correct one, which is how the first draft passed.
# Note also that ``excess`` is a LINE delta consumed as a ROW count; the verb
# reconciles that and reports any shortfall, so do not re-derive it here.

# Committed project-memory filename, routed through one per-file constant so a
# future rename is a value flip. Per-file (not a shared import) — tools/cc scripts
# run standalone; adding a sibling import risks the copy-subset footgun.
_MEMORY_FILENAME = "ESPALIER_MEMORY.md"

ALLOWLISTED_WRITE_PATHS = {
    _MEMORY_FILENAME,
    _paths.COMMANDS_INDEX_REL,
    _paths.LIVE_SURFACE_REL,
    _paths.PACK_MANIFEST_REL,
    "cc/execution_plan.json",
}
ALLOWLISTED_WRITE_PREFIXES = (
    _paths.BLUEPRINTS_DIR_REL + "/",
    "reports/",
    "tests/",
)


def _is_allowlisted(rel_path: str) -> bool:
    if rel_path in ALLOWLISTED_WRITE_PATHS:
        return True
    for prefix in ALLOWLISTED_WRITE_PREFIXES:
        if rel_path.startswith(prefix):
            return True
    return False


def _integrity_spot_check(repo_root: Path, rel_path: str) -> None:
    """Re-run integrity verification and warn on drift. Never blocks."""
    ok, mismatched = _integrity.verify_integrity(repo_root)
    if ok:
        return
    # Suppress the noisy ABSENT case — no manifest just means the user hasn't
    # initialized integrity yet. A manifest that is present but unusable is NOT
    # suppressed: it reports as MANIFEST_UNREADABLE and falls through to the
    # warning below.
    if mismatched == [_integrity.MANIFEST_ABSENT]:
        return
    _integrity.append_audit(
        repo_root,
        {"event_type": "post_write_integrity_drift",
         "details": {"triggered_by": rel_path, "mismatched": mismatched}},
    )
    warn(f"integrity drift after write to {rel_path}: {', '.join(mismatched)}")


def _memory_section_lines(text: str) -> "list[tuple[str, int]]":
    """[(section title, line count)] for each ``## `` section, largest first.

    The cap is measured over the WHOLE file while ``espalier memory prune`` only
    ever evicts rows from the Session Log, so growth in any other section is paid
    for out of session history -- an 8-line addition to a pointer section near the
    top of the file once archived eight July session rows, and nobody editing a
    prose section predicts that. A message that reports "still over cap" without
    naming which section is fat mis-attributes the cost to the log.

    Lines before the first ``## `` belong to a synthetic "(preamble)" section so
    the counts sum to the file and a fat header cannot hide.
    """
    sections: "list[tuple[str, int]]" = []
    title, count = "(preamble)", 0
    fence: "str | None" = None
    for line in text.splitlines():
        # Fence tracking, because a ``## `` inside a code block is prose ABOUT a
        # heading, not one. Measured harm today is mild -- the phantom section is
        # always a sub-range of its parent, so the operator is pointed at the right
        # region under a wrong label -- and the trigger population in this repo's
        # own ESPALIER_MEMORY.md is zero across 363 revisions. Handled anyway
        # because it is two lines and the shipped adopter template is not this repo.
        # The grammar is _hook_utils.next_fence_state, shared with every other
        # ``## `` reader in the hook stack (a backtick-only toggle lived here).
        fenced = fence is not None
        fence = _hook_utils.next_fence_state(line, fence)
        if line.startswith("## ") and not fenced:
            sections.append((title, count))
            title, count = line[3:].strip(), 1
        else:
            count += 1
    sections.append((title, count))
    return sorted(sections, key=lambda pair: -pair[1])


def _read_memory_text(memory_path: Path) -> str | None:
    """ESPALIER_MEMORY.md as text, decoded through ``decode_text_or_problem`` --
    the file is hand-edited at every handoff, so a UTF-8 or UTF-16 byte-order
    mark from an editor or a PowerShell re-encode reads as text instead of
    raising (the strict reads here had no local handler, so the hook's
    umbrella printed a traceback line and the autoprune never ran; DEF-797).
    Bytes that are neither, or a byte-order-mark-less UTF-16 file (NUL-laden
    once decoded), are named once on stderr in the helper's sentence, with the
    encoding to re-save in, and ``None`` comes back so the caller stands down."""
    text, problem = decode_text_or_problem(memory_path.read_bytes())
    if problem:
        warn(f"ESPALIER_MEMORY.md is {problem}; the autoprune cannot count its lines")
        return None
    return text


def _maybe_autoprune_memory(repo_root: Path, rel_path: str) -> None:
    """If the just-written file is ESPALIER_MEMORY.md and now exceeds the cap,
    invoke ``espalier memory prune`` to archive the oldest Session Log
    row(s). Never blocks; logs the action to stderr.

    Tries ``shutil.which("espalier")`` first (production speed), then
    falls back to ``sys.executable -m espalier.cli`` for environments
    where the PATH binary resolves to a Python without the espalier
    module installed (documented in docs/SHARP_EDGES.md under "macOS
    python resolver gap"). Subprocess only — no espalier IMPORT here,
    per the ``tools/cc/`` isolation rule.
    """
    import shutil
    import subprocess

    if rel_path != _MEMORY_FILENAME:
        return

    memory_path = repo_root / _MEMORY_FILENAME
    if not memory_path.is_file():
        return

    text = _read_memory_text(memory_path)
    if text is None:
        return
    line_count = len(text.splitlines())
    if line_count <= _MEMORY_MD_CAP:
        return

    excess = line_count - _MEMORY_MD_CAP + _AUTOPRUNE_HEADROOM
    invocations: list[list[str]] = []
    espalier_bin = shutil.which("espalier")
    if espalier_bin is not None:
        invocations.append([espalier_bin])
    invocations.append([sys.executable, "-m", "espalier.cli"])

    # Self-host bridge: when this hook lives co-located with an
    # ``espalier/`` source tree (the espalier-harness repo itself), add
    # that source root to PYTHONPATH so ``python -m espalier.cli`` finds
    # the package even when the running Python lacks espalier in its
    # site-packages. Production adopters do not have ``espalier/`` next
    # to ``tools/cc/`` -> branch is a no-op for them.
    #
    # Drop any inherited ``PYTHONPATH`` first: a developer with multiple
    # espalier checkouts open (each Claude session under one repo) could
    # otherwise resolve ``espalier`` from an unrelated checkout's source
    # tree. The hook must run the espalier shipped with this repo, not
    # whichever one happens to be on the parent shell's PYTHONPATH.
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    # magic-depth: ok hooks live at tools/cc/hooks/<file>.py, so depth=3 is the repo root
    self_host_root = Path(__file__).resolve().parents[3]
    if (self_host_root / "espalier" / "__init__.py").is_file():
        env["PYTHONPATH"] = str(self_host_root)

    last_error = ""
    for base in invocations:
        cmd = base + [
            "memory", "prune",
            "--rows", str(excess),
            "--root", str(repo_root),
            # Hook context is non-blocking by design; never refuse
            # to fix an over-cap ESPALIER_MEMORY.md just because Session Log has
            # only 1 row. Direct CLI users keep the safety default.
            "--allow-empty",
            # ...but --allow-empty alone archives the row the operator just
            # wrote when the log holds exactly one. ESPALIER_MEMORY.md's own
            # pruning policy already promises "the newest rows are always kept";
            # this closes the gap between that shipped sentence and the code.
            # Reserving the newest row can leave the file over cap, which is the
            # deliberate trade -- the residual-over-cap warning below reports it
            # rather than paying for headroom with the newest row.
            "--keep-newest", "1",
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, env=env
            )
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {os_error_text(exc)}"
            continue
        if result.returncode == 0:
            after = _read_memory_text(memory_path)
            if after is None:
                return
            new_count = len(after.splitlines())
            # `excess` is a LINE-count delta but `memory prune`
            # consumes it as a SESSION-LOG-ROW count. When the bloat lives in the
            # permanent Decisions/Patterns tables (not the Session Log), pruning
            # log rows cannot bring the file under cap — the prune "succeeds" yet
            # the file stays over cap, and the success line below would mask it
            # behind a silent exit 0. Make the residual over-cap state OBSERVABLE.
            # (The structural fix — capping the permanent tables in parity with
            # cognitive_blueprint's truncate-to-cap — is the owed ESPALIER_MEMORY.md
            # spin-out TP, deliberately not bundled here.)
            if new_count > _MEMORY_MD_CAP:
                census = _memory_section_lines(after)
                fattest = ", ".join(
                    f"{title} ({count} lines)" for title, count in census[:3]
                )
                warn(
                    f"ESPALIER_MEMORY.md autoprune ran ({line_count} -> {new_count} lines) "
                    f"but the file is STILL over the {_MEMORY_MD_CAP}-line cap -- "
                    f"the excess is not in the Session Log ROWS. Largest sections: "
                    f"{fattest}. Trim the fattest one, or spin the permanent "
                    f"tables out; pruning more log rows cannot help."
                )
                return
            # Carry the verb's own line through verbatim: it names the DATES of
            # the rows that left, and the archive is gitignored, so this is the
            # only place the operator learns which sessions were evicted.
            #
            # ⚠ Keep the LITERAL "docs/session-archive.md" in the sentence below.
            # The verb's stdout names the path too, but only at runtime, and
            # tests/test_adopter_pointer_resolution.py::_NOT_POINTERS carries a
            # declared non-pointer row keyed to this file naming that exact path.
            # Dropping the literal kills that row (driven: it reported the
            # exemption as matching nothing) and leaves the operator with no path
            # at all on the branch where stdout comes back empty.
            detail = result.stdout.strip().splitlines()
            print(
                f"[post_write_check] ESPALIER_MEMORY.md autoprune: "
                f"{line_count} -> {new_count} lines "
                f"(archived to docs/session-archive.md; requested "
                f"{_hook_utils.plural(excess, 'row')}"
                + (f" -- {detail[-1]}" if detail else "")
                + ")",
                file=sys.stderr,
            )
            return
        last_error = (
            f"rc={result.returncode} stderr={result.stderr.strip()}"
        )

    warn(
        f"ESPALIER_MEMORY.md autoprune failed: {last_error} "
        f"(file remains at {line_count} lines, cap={_MEMORY_MD_CAP}; "
        f"run `espalier memory prune --rows {excess}` manually)"
    )


_resolve_project_root = _hook_utils.resolve_project_root


# Aliased to `_hook_utils.normalize_path` (single source of truth).
# A non-str payload returns "<invalid>" instead of raising AttributeError —
# the same fail-closed shape `write_guard` already uses.
_normalize_path = _hook_utils.normalize_path


def check_json(content: str, rel_path: str) -> None:
    """Validate JSON parses cleanly."""
    try:
        json.loads(content)
    except json.JSONDecodeError as e:
        warn(f"{rel_path} contains invalid JSON: {e}")


def check_placeholders(content: str, rel_path: str) -> None:
    """Scan for placeholder values."""
    found = [p for p in PLACEHOLDERS if p in content]
    if found:
        warn(f"{rel_path} contains placeholders: {', '.join(found)}")


def check_python_syntax(content: str, rel_path: str) -> None:
    """Basic Python syntax check via compile()."""
    try:
        compile(content, rel_path, "exec")
    except SyntaxError as e:
        warn(f"{rel_path} has a Python syntax error: {e}")


# The three deployed body kinds under .claude/ -- ONE tuple, read by both the
# harness-file gate and the placeholder dispatch below. The two used to spell
# the agents-plus-commands pair by hand, twice, and neither learned the third
# kind: a write to .claude/skills/<name>/SKILL.md returned before any check
# ran, so a placeholder left in a deployed skill body surfaced at the next
# doctor instead of at the write (DEF-782; the same hand-typed-pair shape as
# DEF-532, seen from the validation side). A hook cannot import the engine's
# owner (surface_contract.CLAUDE_KIND_GLOBS), so the tuple lives here and a
# parity pin holds the two equal.
_CLAUDE_BODY_KINDS: tuple[str, ...] = ("agents", "commands", "skills")


def _is_claude_body(rel_path: str) -> bool:
    """A deployed .claude/ body of any kind, case-insensitively."""
    rel_lc = rel_path.lower()
    return any(rel_lc.startswith(f".claude/{kind}/") for kind in _CLAUDE_BODY_KINDS)


def _is_harness_file(rel_path: str) -> bool:
    """Return True if this path is in the harness infrastructure zones.

    Lowercase comparison so case-varied paths (e.g.,
    ``.CLAUDE/AGENTS/evil.md`` on macOS HFS+ or Windows NTFS) still
    trigger the validation pipeline, matching write_guard + plan_guard.
    """
    rel_lc = rel_path.lower()
    return (
        rel_lc == ".claude/settings.json"
        or _is_claude_body(rel_path)
        or rel_lc.startswith("tools/cc/")
    )


def _is_root_md(rel_path: str) -> bool:
    """Return True if this is a managed governance .md file (root-level or docs/)."""
    managed_docs = {
        "CLAUDE.md", _MEMORY_FILENAME,
        "docs/CONVENTIONS.md", "docs/SHARP_EDGES.md",
        "docs/CHEAT-SHEET.md", "docs/TASK_RECIPES.md",
    }
    return rel_path in managed_docs


# action_justification retroactive advisory. Runs BEFORE the
# Write/Edit-only early-return so Bash/PowerShell mutations also get
# coverage. Non-blocking — emits stderr advisory + audit-log entry on
# miss. Reads the active blueprint via raw json.load — the hook does NOT
# import espalier.cognitive_blueprint.
_AJ_WINDOW_SECS = 60

# The MCP tool-name substrings that mark a write-class call.
# Shared by _check_action_justification_for_mutation (the AJ advisory) and
# _run_main's is_mcp_write gate so the two membership tests cannot drift. Derived
# from the single owner _hook_utils.MCP_WRITE_VERB_SUBSTRINGS (also consumed by
# reflect_trigger's is_mcp_write gate).
_MCP_WRITE_VERB_SUBSTRINGS = _hook_utils.MCP_WRITE_VERB_SUBSTRINGS


def _check_action_justification_for_mutation(
    root: Path, tool_name: str, tool_input: dict
) -> None:
    """If the active blueprint has no matching action_justification
    within the 60s window, emit advisory + audit-log entry. Always
    returns None; never raises."""
    latest = root / "cc" / "blueprints" / "latest.json"
    if not latest.exists():
        return
    try:
        bp = json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # A non-UTF-8 latest.json raises
        # UnicodeDecodeError (a ValueError, not OSError); degrade silently
        # like the JSON/OSError cases rather than escape this reporter.
        return
    if not isinstance(bp, dict):
        return

    target = ""
    content_hash = None
    if tool_name in ("Write", "Edit", "NotebookEdit") or (
        tool_name.startswith("mcp__")
        and any(v in tool_name.lower() for v in _MCP_WRITE_VERB_SUBSTRINGS)
    ):
        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
        if not file_path:
            return
        # Advisory parity with write_guard.check_write_edit's isinstance handling
        # (write_guard DENIES on a non-str payload; this REPORTER returns so a
        # malformed payload loses only its own advisory, not its well-formed
        # siblings' in the same call). Return-not-deny is correct at the advisory
        # tier -- the main() umbrella's AttributeError catch is the sanctioned
        # fail-open; this just keeps it from firing on a typed payload.
        if not isinstance(file_path, str):
            return
        full = root / file_path.replace("\\", "/")
        try:
            content_hash = "sha256:" + hashlib.sha256(full.read_bytes()).hexdigest()
        except OSError:
            return
        target = file_path
    elif tool_name in ("Bash", "PowerShell"):
        cmd = tool_input.get("command", "")
        if not cmd:
            return
        content_hash = "sha256:" + hashlib.sha256(cmd.encode("utf-8")).hexdigest()
        target = cmd[:80]
    else:
        return

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=_AJ_WINDOW_SECS)
    # Matcher gates on timestamp window + AJ presence only.
    # The composer in execution_plan.py hashes plan metadata
    # (sha256 of task|index|description); the matcher above computed
    # sha256(file_bytes) for Write/Edit and sha256(cmd) for Bash.
    # Those two hash domains are disjoint by construction; equality
    # would couple the planner to the hook implementation. Trade-off:
    # a single AJ within the 60s window suppresses all mutations in
    # that window. See docs/HOOK_ASSUMPTIONS.md "Action-justification
    # matching" for the full trade-off discussion. content_hash above
    # is preserved for the audit-log payload on miss.
    for aj in bp.get("action_justifications", []):
        if not isinstance(aj, dict):
            continue
        try:
            ts = datetime.fromisoformat(aj.get("timestamp", ""))
        except (TypeError, ValueError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= window_start:
            return  # action_justification recorded within window

    print(
        f"[post_write_check] no action_justification recorded for "
        f"{tool_name}:{target} within {_AJ_WINDOW_SECS}s window -- consider: "
        + (f"{_py} tools/cc/cognitive_blueprint.py justify "
           "--from-tool-input-file ..."
           if (_py := _hook_utils.python_command_hint())
           else "record one with cognitive_blueprint.py justify -- no Python "
                f"{_hook_utils.floor_text()}+ interpreter is on PATH to run it"),
        file=sys.stderr,
    )
    try:
        _integrity.append_audit(root, {
            "event_type": "action_justification_missing",
            "details": {
                "tool": tool_name,
                "target": str(target)[:200],
                "content_hash": content_hash,
            },
        })
    except Exception:  # noqa: BLE001, S110 -- audit best-effort; hook protocol forbids stderr noise
        pass


# The born-weak co-occurrence OBSERVER lives in the co-located sibling
# _born_weak.py (mirrors write_guard's _bash_patterns/_protected_zones split).
# Re-export the symbols tests/test_born_weak_observer.py reaches via
# `import post_write_check as p` so its `p.<symbol>` access is unchanged.
from _born_weak import (  # noqa: E402,F401  (re-export for the test surface)
    _BW_LOG_NAME,
    bw_log_observation,
    observe_born_weak,
    _bw_count_exempt_entries,
    _bw_is_guard_material,
    _observe_born_weak,
)


_BRIDGE_MAX_PATHS = 8


def _bash_derived_payloads(tool_input: dict, root: Path, *, already: int,
                           tool_name: str = "Bash", cwd: Path | None = None) -> list:
    """Registry payloads for the paths a Bash or PowerShell command WROTE.

    The guard's extractor over-yields by design (a path inside a string literal,
    a `cp -t` source, a `grep` pattern) because its caller filters through the
    protected-zone check; this caller filters through existence instead -- a
    path that is not on disk after the call was not written by it, and a
    pointer spent on a mention would be gone when the file arrives (failure-mode
    pass, driven: a `python3 -c` run from /tmp whose body named two paths burnt
    both flags). Each real path is offered as the write it was -- `Write` for a
    file git does not track yet, `Edit` for one it does -- so the sync rows that
    gate on those two names fire for a heredoc exactly as for the Write tool.
    The remaining per-turn budget is passed INTO `check`, which marks a once
    row only when it emits, so the caller never trims a returned list.
    """
    command = tool_input.get("command", "")
    if not isinstance(command, str) or not command.strip():
        return []
    try:
        import _bash_patterns  # noqa: E402  -- sibling; the guard's extractors
        # The directory the command ran in (DEF-509), read as write_guard
        # reads it: the payload cwd, moved by the command's own cd chain; a
        # .NET-API path on PowerShell keeps the process directory.
        start = cwd or root
        _exists = _hook_utils.directory_exists(start)
        if tool_name == "PowerShell":
            paths = _bash_patterns._candidate_paths_from_powershell(command)
            text, statements = _bash_patterns.powershell_directory_chain(command, _exists)
            fixed = frozenset(_bash_patterns.powershell_dotnet_paths(command))
        else:
            paths = _bash_patterns._candidate_paths_from_bash(command)
            text, statements = _bash_patterns.bash_directory_chain(command, _exists)
            fixed = frozenset()
    except Exception:  # noqa: BLE001 -- a reporter never crashes the hook
        return []
    out: list = []
    seen: set = set()
    budget = _reinject.REINJECT_PER_TURN_CAP - already
    for rel in paths:
        if budget <= 0 or len(seen) >= _BRIDGE_MAX_PATHS:
            break
        if not isinstance(rel, str) or rel in seen:
            continue
        seen.add(rel)
        try:
            # The checkout the path sits in (root or a registered worktree,
            # DEF-743): existence, the index and the synthesized payload's path
            # all belong to it, so the registry re-resolves to the same checkout.
            landed = None
            for spelled in (["."] if rel in fixed
                            else _bash_patterns.statement_directories(text, statements, rel)):
                base, norm = _hook_utils.resolve_in_checkout(
                    rel, root, base=_hook_utils.join_directory(start, spelled))
                if (base / norm).is_file():
                    landed = (base, norm)
                    break
            if landed is None:
                continue          # mentioned, not written
            base, norm = landed
        except (OSError, ValueError):
            continue
        synthesized = "Edit" if _reinject._is_tracked(base, norm) else "Write"
        for text in _reinject.check("PostToolUse", synthesized,
                                    {"file_path": str(base / norm), "command": command}, root,
                                    budget=budget):
            if text not in out:
                out.append(text)
                budget -= 1
    return out


def main() -> int:
    """Public entry-point. Fail-OPEN umbrella: post_write_check is an advisory
    PostToolUse hook, so an uncaught crash in ``_run_main`` (a check helper, a
    producer schema drift) must degrade to a no-op advisory (exit 0 + one
    [ERROR] line), NOT a per-write traceback. Mirrors task_router.main —
    advisory tier fails OPEN.
    """
    try:
        return _run_main()
    except BaseException as exc:  # noqa: BLE001 — fail-open crash guard (advisory hook)
        print(
            f"[ERROR] post_write_check crashed: {type(exc).__name__}: {os_error_text(exc)}",
            file=sys.stderr,
        )
        return 0


def _run_main() -> int:
    # PostToolUse runs AFTER the tool call has already executed —
    # it cannot block. Every print here is advisory; the gate is the
    # `# stop_gate.py` (Stop event) or PreToolUse hooks. Failures land
    # as stderr warnings + audit-log entries, never as a denied tool call.
    from _hook_utils import read_stdin_safely  # noqa: E402

    data = read_stdin_safely()
    if not data:
        return 0

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}

    # action_justification retroactive advisory runs FIRST so
    # Bash/PowerShell mutations also get coverage (the JSON-validity /
    # path-consistency checks below remain Write/Edit-only via the
    # existing early-return). Non-blocking — never affects return value.
    root_for_aj = _resolve_project_root()
    _check_action_justification_for_mutation(root_for_aj, tool_name, tool_input)

    # Advisory PostToolUse reinject -- delivered next to the tool result, BEFORE
    # the write-only early-return below. The JSON/path validation below stays
    # stderr-advisory, so no channel collision.
    #
    # Gated to SELF-HOST. The PostToolUse sync rows (every `event="PostToolUse"`
    # row in `_reinject.REINJECTS`; the first of them were the command
    # five-surface sync, the hook-helper count and the integrity MANIFEST_FILES
    # parity) surface multi-surface-sync SoTs whose witnesses name engine internals
    # (cli.py::INIT_HOOK_SCRIPTS, examples/dogfooding/, tests/...) absent from an
    # adopter repo -- so an adopter who creates a command/hook would otherwise be
    # injected mid-session with guidance about Espalier's own tree. Gate on the
    # repo root (here `root_for_aj`, == _resolve_project_root()) like the born-weak
    # observer below. SessionStart/UserPromptSubmit orientation + PostToolUseFailure
    # Rule A are generic and adopter-relevant -- they are NOT routed through this
    # call, so they stay ungated. An empty PostToolUse registry => [] => no print.
    _reinject_payloads = (
        _reinject.check("PostToolUse", tool_name, tool_input, root_for_aj)
        if _hook_utils.is_self_host_repo(root_for_aj)
        else []
    )
    # A Bash write carries no file_path, so every path-keyed row above was
    # silent for a heredoc, `printf >>`, `sed -i` or `python -c` edit --
    # measured 2026-09-06: 3 pushes in a session of hundreds of tool calls.
    # Derive the written paths with the guard's own extractor and ask the
    # registry once per path, under the same per-turn ceiling.
    if tool_name in ("Bash", "PowerShell") and _hook_utils.is_self_host_repo(root_for_aj):
        _reinject_payloads = _reinject_payloads + _bash_derived_payloads(
            tool_input, root_for_aj, already=len(_reinject_payloads), tool_name=tool_name,
            cwd=_hook_utils.payload_cwd(data, root_for_aj)
        )
    if _reinject_payloads:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "\n".join(_reinject_payloads),
            }
        }))

    # Include MCP write tools so post-write JSON / Python / placeholder
    # checks still fire when the agent uses `mcp__filesystem__write_file`
    # instead of the native Write tool.
    is_native_write = tool_name in ("Write", "Edit", "NotebookEdit")
    is_mcp_write = (
        tool_name.startswith("mcp__")
        and any(verb in tool_name.lower() for verb in _MCP_WRITE_VERB_SUBSTRINGS)
    )
    if not (is_native_write or is_mcp_write):
        return 0

    # MCP tool_input uses `path` more than `file_path`. Sweep both.
    file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
    root = _resolve_project_root()
    # `base` is the checkout the written file sits in -- the root, or a registered
    # worktree of the repository (DEF-743) -- and `rel_path` is relative to it;
    # every read-back, the observer's diff and the memory prune below go through
    # `base`. The integrity spot-check runs for a root write only: the manifest
    # describes the root's deployed surface, which a worktree write cannot drift.
    base, rel_path = _hook_utils.resolve_in_checkout(file_path, root)

    # Born-weak co-occurrence OBSERVER (self-host only; observe-first instrument).
    # Runs BEFORE the harness-file gate below, which would skip tests/ + scanners.
    # Observe-only, best-effort, never affects the return value.
    if _hook_utils.is_self_host_repo(root):
        _observe_born_weak(root, rel_path, base=base)

    # Only activate for harness infrastructure or root managed docs
    if not _is_harness_file(rel_path) and not _is_root_md(rel_path):
        return 0

    full_path = base / rel_path
    if not full_path.exists():
        return 0

    try:
        content = full_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0

    # .claude/settings.json → JSON validation
    if rel_path == ".claude/settings.json":
        check_json(content, rel_path)

    # .claude/{agents,commands,skills}/ bodies → placeholder check
    if _is_claude_body(rel_path):
        check_placeholders(content, rel_path)

    # tools/cc/**/*.py → Python syntax check
    if rel_path.startswith("tools/cc/") and rel_path.endswith(".py"):
        check_python_syntax(content, rel_path)

    # Root .md files → placeholder check
    if _is_root_md(rel_path):
        check_placeholders(content, rel_path)

    # Integrity spot-check for non-allowlisted writes in protected zones.
    if not _is_allowlisted(rel_path) and base == root:
        _integrity_spot_check(root, rel_path)

    # Auto-prune ESPALIER_MEMORY.md when the just-completed write pushes
    # the file past the line cap. Always last (advisory action; never
    # blocks).
    _maybe_autoprune_memory(base, rel_path)

    return 0


if __name__ == "__main__":
    # UTF-8 on both streams, whatever the console code page: on Windows a
    # redirected stream defaults to the ANSI page, a non-ASCII character in
    # the CONTENT this prints (a plan's text, a recall title, a memory row)
    # goes out as cp1252, and a parent decoding UTF-8 loses the whole stream
    # (CPython's Windows communicate() answers None for a reader thread that
    # died; Portability, 2026-09-24). Content is the operator's and may be
    # anything; the messages around it stay 7-bit ASCII by rule.
    import sys as _sys
    for _stream in (_sys.stdout, _sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
