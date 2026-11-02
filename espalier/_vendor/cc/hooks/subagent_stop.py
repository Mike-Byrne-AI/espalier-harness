#!/usr/bin/env python3
"""SubagentStop hook — finalize subagent reasoning into the parent
session's blueprint chain.

Agents (architecture-analyst, code-reviewer, etc.) run in isolated
contexts and bypass ``stop_gate.py`` entirely. Their reasoning lands in
the parent session's tool-result stream, but no gate finalizes it into
the blueprint. This hook closes that gap: on every SubagentStop, append
a reasoning entry to the active blueprint carrying the head of the
agent's final message and the transcript it came from (``[subagent:<type>]
<lead>``), so a fan-out session's findings reach the next session rather
than surviving only in a tool-result stream the next compaction discards.

Gates: Gate 4 only (auto-finalize blueprint append). Pytest, docs
refresh, code review do NOT fire — subagent results don't carry the
same blast radius as a parent Stop.

Matcher: "*" (all subagent types). Filter happens internally; payload
``stop_hook_active`` is honored to prevent recursive subagent loops.

Protocol contract (cc-hook-protocol.md):
- Exit 0 with no JSON → allow subagent stop (default path).
- Exit 0 + ``{"decision": "block", "reason": "..."}`` → block stop;
  stderr goes to the parent session. SubagentStop uses the same JSON
  shape as Stop (top-level, not nested in hookSpecificOutput).
- Exit 1 = script bug. NEVER use for governance decisions.

This hook only emits exit 0 (with or without JSON). It never blocks
the subagent — blocking would deadlock the parent session waiting for
agent completion.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _hook_utils  # noqa: E402
import _maintenance_mode  # noqa: E402
from _hook_utils import os_error_text  # noqa: E402

# tools/cc, for `_earlier_evidence`'s `_json_safe` import. `_hook_utils` makes
# the same insert as it loads; made here too, after it, so this file's reach
# does not rest on that side effect and the path order is unchanged
# (tests/test_deploy_set_import_closure.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_resolve_project_root = _hook_utils.resolve_project_root


def _append_subagent_reasoning(
    root: Path, agent_type: str, lead: str, evidence: str | None = None,
) -> None:
    """Append a ``pattern_discovered`` reasoning entry tagged with the
    agent type to the active blueprint.

    Uses the standalone ``tools/cc/cognitive_blueprint.py record`` CLI
    (same one the other hooks use) — keeps the zero-espalier-import
    constraint. The blueprint's ``kind`` enum doesn't include a
    dedicated ``subagent`` value (would require schema bump); we encode
    the subagent identity in the description prefix so the entry is
    grep-able by ``[subagent:<type>]``.

    ``lead`` is the head of the agent's final message (see ``_lead``) and
    ``evidence`` is where it was cut from. THE TWO TRAVEL TOGETHER, and that
    is a contract the blueprint readers key on (DEF-586): an entry with the
    prefix AND evidence is a REPORT, kept by ``show-recent`` and carried into
    the next session through its own bounded fragment slot; an entry with the
    prefix and no evidence is an ANCHOR ("completed"), the activity marker
    every selection reader drops. A lead without evidence would be dropped
    as an anchor; an anchor with evidence would put a content-free line into
    the next session's banner.

    Failure is non-fatal — subagent stop must not block on logging.
    """
    script = root / "tools" / "cc" / "cognitive_blueprint.py"
    if not script.is_file():
        return
    description = f"[subagent:{agent_type}] {lead or 'completed'}"
    argv = [
        sys.executable, str(script),
        "record",
        "--kind", "pattern_discovered",
        "--description", description,
    ]
    if lead and evidence:
        argv += ["--evidence", evidence]
    # env= pins CLAUDE_PROJECT_DIR to root: cognitive_blueprint._repo_root()
    # prefers the env var over cwd, so an inherited value would silently
    # record subagent reasoning into the wrong repo's blueprint chain.
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    try:
        result = _hook_utils.run_bounded(  # spawn: ok a reporter's append; a spawn that cannot start is handled where it is caught
            argv,
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=10,
            cwd=str(root),
            env=env,
        )
        if result.returncode == 2:
            # No active session — that's fine, this hook is opportunistic.
            # The agent's reasoning is still visible in the parent's
            # tool-result stream regardless of blueprint state.
            return
        if result.returncode != 0:
            # A non-zero non-2 exit means the standalone record CLI crashed
            # (file lock failure, OOM, bad JSON parse mid-modify). Recorded
            # once a session so subagent reasoning isn't lost without a signal:
            # this hook exits 0, and stderr alone reaches the debug log only
            # (the protocol pin). SubagentStop's additionalContext would
            # continue the subagent, so a record is the quiet seen channel.
            _hook_utils.say_once(
                root, f"subagent-record-rc-{result.returncode}", "subagent_stop",
                "subagentstop_failed_open_blueprint_record",
                f"cognitive_blueprint record exited {result.returncode}: "
                f"{(result.stderr or '').strip()[:200]}; the subagent's reasoning was not appended",
                returncode=result.returncode,
            )
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        # Exit 0, no JSON: recorded once a session, stderr as its copy.
        _hook_utils.say_once(
            root, f"subagent-record-{type(e).__name__}", "subagent_stop",
            "subagentstop_failed_open_blueprint_record",
            f"blueprint record failed ({type(e).__name__}: {os_error_text(e)}); "
            "the subagent's reasoning was not appended",
            fault=type(e).__name__,
        )


STATE_DIR = _hook_utils.STATE_DIR  # single source of truth; see _hook_utils

# Agents whose completion satisfies a stop_gate hygiene gate: agent_type ->
# flag-file name in STATE_DIR. When a SubagentStop event fires with one of
# these agent_types, the flag is written as a JSON record of what the run
# produced, and the next stop_gate evaluation reads it.
#
# Why here, not in stop_gate.py: stop_gate fires on the parent Stop event
# AFTER the agent has finished and the operator has typed nothing. It cannot
# observe in-session agent runs. SubagentStop fires immediately when the
# agent finishes; this is the only hook that sees the agent_type and can
# persist a session-scoped record.
#
# This hook is the ONLY writer. stop_gate's Gate 3 used to write its own
# `review_requested` flag on its first block, which made the gate relieve on
# having ASKED for a review -- once per session, no review run (DEF-608), and
# was why this map once forbade a code-reviewer entry. The gates now only
# read; the table lives in _hook_utils so reader, writer and sweeper share it,
# and _hook_utils.relief_flags adds the agents the adopter declares in
# espalier.toml (the writer below and stop_gate's reader both call it).

# How much of the subagent's final message the record quotes, and the size the
# whole record stays under (tests/test_state_file_flag_parity.py caps a relief
# record at 1 KiB so a flag never becomes a payload channel). The payload keys
# read here -- `agent_type`, `last_assistant_message`, `agent_transcript_path`
# -- are the documented SubagentStop input
# (code.claude.com/docs/en/hooks#subagentstop, verified 2026-09-07 and again
# 2026-09-11); a payload without the message still records the run.
_EXCERPT_CHARS = 160
_RECORD_MAX_CHARS = 900

# How much of the final message the BLUEPRINT entry keeps (DEF-586). A
# different cap from the relief excerpt above because the consumers differ: the
# relief record is a 1 KiB flag one gate parses, the blueprint entry is a
# fragment the next session's banner renders, where two agent leads share a
# 3 KB blueprint budget with the operator's own pinned decisions
# (session_start._MAX_BLUEPRINT_CONTEXT_BYTES; two leads at this cap take
# about two fifths of it, and the budget shrinks further when the banner's
# body is long: the blueprint yields to it). The prefix plus a lead at this
# cap stays under the record CLI's 1000-char write-time advisory, which would
# otherwise print on
# every stop. The full message is in the agent transcript the entry names as
# evidence, and in the parent's tool-result stream until that is compacted.
# Whose lines pay for the two leads: cmd_load renders fragments ABOVE the
# decisions and session_start._bound_blueprint_context sheds whole lines from
# the bottom, so the leads are never cut and the oldest unpinned decisions are
# what the budget takes.
_LEAD_CHARS = 600


def _lead(text: str, cap: int = _LEAD_CHARS) -> str:
    """The head of ``text`` for a blueprint entry.

    Every character outside printable ASCII becomes a space first: the record
    CLI echoes the entry to a stdout that is cp1252 on a Windows child, and an
    arrow or a tick in a reviewer's message crashed that echo AFTER the write,
    which this hook then reported as reasoning lost (tools/cc/CLAUDE.md rule 4;
    the allowlist is ``_sanitize_for_priming``'s). Then whitespace collapses to
    single spaces (a reviewer's markdown is many lines; the entry is one), and
    the result is cut on a word boundary at ``cap`` with an ASCII ``...``
    marker when there was more. A run with no space inside the cap is cut hard
    at ``cap``.
    """
    text = " ".join("".join(c if " " <= c <= "~" else " " for c in text).split())
    if len(text) <= cap:
        return text
    cut = text.rfind(" ", 0, cap + 1)
    head = text[:cut] if cut > 0 else text[:cap]
    return head + " ..."


def _changed_markdown(root: Path) -> list[str]:
    """Markdown paths (``.md`` and ``.mdx``) with uncommitted changes — the
    evidence a refresh happened. ``.mdx`` since 2026-10-06: an Astro or Docusaurus
    site keeps its documentation there, and a docs run that edited only ``.mdx``
    recorded no changed docs, so Gate 2 blocked it as having changed nothing.

    DEF-495: the flag below used to be written empty on agent COMPLETION, so
    stop_gate Gate 2 relieved on attendance rather than on work. Keyed on the
    file TYPE rather than a curated doc-path list deliberately: a hand-kept set
    of "the doc files" is the §C1 shape this repo keeps paying for, and any
    markdown change is adequate evidence that doc work occurred.

    Returns ``[]`` on any failure — a non-git tree, no git binary, a timeout.
    The gate reads an empty list as "no evidence", which is the correct
    conservative answer when we cannot see the tree.
    """
    return _dirty_markdown(root) or []


def _dirty_markdown(root: Path, timeout: float = 10) -> list[str] | None:
    """:func:`_changed_markdown`'s list, or ``None`` when git could not be
    read: the start snapshot (DEF-1100) must tell "nothing was dirty" from "we
    could not look", since an empty snapshot credits the run with every file
    dirty at its stop. ``timeout`` is shorter on the start path, which shares
    SubagentStart's 10 s with the orientation it prints."""
    try:
        # -z: a path is never quoted (a non-ASCII name read as `"docs/caf\303\251.md"`
        # matched no file, so its digest compared equal at both ends).
        r = _hook_utils.run_bounded(  # spawn: ok a reporter; a git that cannot run lists no changed markdown (declared at its handler)
            ["git", "status", "--porcelain", "-z", "--", "*.md", "*.mdx"],
            cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):  # fail-open: ok deliberate -- a git that cannot answer lists no changed markdown; the append proceeds without it
        return None
    if r.returncode != 0:
        return None
    changed: list[str] = []
    fields = iter(r.stdout.split("\0"))
    for entry in fields:
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        # A rename or copy names the new path first, then the old one as a
        # field of its own: the new path exists on disk and is the evidence.
        if status[0] in "RC":
            next(fields, None)
        if path.endswith((".md", ".mdx")):
            changed.append(path)
    return changed


def _git_top(root: Path, timeout: float) -> Path:
    """The worktree's top, which porcelain paths are relative to; ``root``
    where git cannot say. A project root below the top (a monorepo package)
    resolved no porcelain path, so every digest compared equal (code review)."""
    try:
        r = _hook_utils.run_bounded(  # spawn: ok a reporter; a git that cannot answer leaves the paths read from the root
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):  # strict decode: a structured answer (DEF-821) # fail-open: ok deliberate -- the paths are read from the root, as before the top was asked
        return root
    top = r.stdout.strip()
    return Path(top) if r.returncode == 0 and top else root


# DEF-1100: the docs record's evidence is what the agent changed during ITS run.
# The stop alone sees the tree's dirty markdown, which holds whatever the parent
# edited before it dispatched the agent, so SubagentStart keeps a snapshot for a
# docs-mapped agent (each dirty file's digest), and the stop records only the
# paths new or changed since. One file per run under this folder of STATE_DIR,
# named by the agent id, written once (Claude Code may run SubagentStart again
# for one subagent, after its auto-compaction, and a second snapshot would
# absolve the agent's own earlier edits) and consumed by the stop. A run whose
# stop never comes leaves its file; the next start sweeps any older than a day.
DOCS_SNAPSHOT_DIR = "docs_snapshots"
_SNAPSHOT_MAX_AGE_SECONDS = 24 * 60 * 60
_SNAPSHOT_SWEEP_CAP = 200
# The start path's git read: SubagentStart's whole timeout is 10 s, and the
# orientation it prints must survive a slow git (no snapshot is the stop's
# named stand-down; a killed start loses the orientation unsaid).
_SNAPSHOT_GIT_SECONDS = 4
_SNAPSHOT_TOP_SECONDS = 2  # the worktree-top read after it: 6 s of git at most


def _run_key(value: object) -> str:
    """A file-safe name for one subagent run, from an agent id or a transcript
    name; ``""`` when there is none. One rule for every source: a leading
    ``agent-`` is dropped, so ``agent-abc123`` (the upstream page's example
    id) and ``abc123`` (the id Claude Code sends) name one run."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if value.startswith("agent-"):
        value = value[len("agent-"):]
    return "".join(c for c in value if c.isalnum() or c in "-_")[:80]


def _stop_run_keys(data: dict) -> list[str]:
    """The names a stop's snapshot may be under: the payload's ``agent_id``,
    then the transcript's own name. Driven 2026-11-02 on this host's Claude
    Code (a payload logger wired on both events): SubagentStart and
    SubagentStop carried one ``agent_id`` (``a060f8fc0f85f8900``, no prefix),
    and the stop's ``agent_transcript_path`` ended ``agent-<that id>.jsonl``.
    The upstream page documents ``agent_id`` on both events and says nothing
    of the two being one value, so the transcript is the second key."""
    keys = [_run_key(data.get("agent_id"))]
    transcript = data.get("agent_transcript_path")
    if isinstance(transcript, str) and transcript.strip():
        stem = transcript.replace("\\", "/").rsplit("/", 1)[-1]
        keys.append(_run_key(stem[: -len(".jsonl")] if stem.endswith(".jsonl") else stem))
    return [k for k in dict.fromkeys(keys) if k]


def _digests(root: Path, paths: list[str], timeout: float = 3) -> dict[str, str]:
    """Each path's content digest, read from the worktree's top (porcelain
    paths are top-relative); ``""`` for one that cannot be read (a deletion is
    dirty with no content, and stays ``""`` while it stays one)."""
    out: dict[str, str] = {}
    top = _git_top(root, timeout) if paths else root
    for rel in paths:
        try:
            out[rel] = hashlib.sha256((top / rel).read_bytes()).hexdigest()
        except OSError:  # fail-open: ok deliberate -- a deleted or unreadable file digests as "", the same at both ends while it stays so
            out[rel] = ""
    return out


def _sweep_old_snapshots(folder: Path) -> None:
    """Remove snapshot files older than a day (a run whose stop never came).
    Bounded: the first ``_SNAPSHOT_SWEEP_CAP`` entries a listing yields."""
    cutoff = time.time() - _SNAPSHOT_MAX_AGE_SECONDS
    try:
        entries = list(folder.iterdir())[:_SNAPSHOT_SWEEP_CAP]
    except OSError:  # fail-open: ok deliberate -- an unlistable folder keeps its old files; the write below names a failure of its own
        return
    for entry in entries:
        try:
            if entry.suffix == ".json" and entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:  # fail-open: ok deliberate -- an old snapshot that will not go is swept by a later start
            continue


def snapshot_docs_at_start(root: Path, data: dict) -> None:
    """SubagentStart's half of DEF-1100, called by ``subagent_start.py``: for
    an agent the relief table maps to Gate 2's record, keep the dirty markdown
    and each file's digest under the run's agent id. Nothing for any other
    agent, and nothing when git cannot be read: no snapshot is the stop's
    named stand-down, never a wrong empty one."""
    agent_type = str(data.get("agent_type", ""))
    flag = _hook_utils.relief_flags(root, hook="subagent_start").get(agent_type)
    if flag != _hook_utils.DOCS_REFRESHED:
        return
    key = _run_key(data.get("agent_id"))
    if not key:
        return
    folder = root / STATE_DIR / DOCS_SNAPSHOT_DIR
    target = folder / f"{key}.json"
    if target.exists():
        return
    dirty = _dirty_markdown(root, timeout=_SNAPSHOT_GIT_SECONDS)
    if dirty is None:
        return
    folder.mkdir(parents=True, exist_ok=True)
    _sweep_old_snapshots(folder)
    _hook_utils.atomic_write_text(
        target,
        json.dumps({"agent": agent_type, "docs": _digests(root, dirty, _SNAPSHOT_TOP_SECONDS)},
                   ensure_ascii=False),
    )


def _take_snapshot(root: Path, data: dict) -> dict[str, str] | None:
    """The run's start snapshot (path -> digest), removed as it is read; None
    when there is none to read."""
    folder = root / STATE_DIR / DOCS_SNAPSHOT_DIR
    for key in _stop_run_keys(data):
        path = folder / f"{key}.json"
        try:
            # Decoded with replacement: a strict read raised a UnicodeDecodeError
            # past this handler and lost the relief record (code review).
            raw = path.read_bytes().decode("utf-8", errors="replace")
        except OSError:  # fail-open: ok deliberate -- no snapshot under this name; the next name is tried, and none at all is the stop's named stand-down
            continue
        try:
            path.unlink()
        except OSError:  # fail-open: ok deliberate -- a snapshot left behind is swept by a later start after a day
            pass
        try:
            parsed = json.loads(raw)
        except ValueError:  # fail-open: ok deliberate -- a torn snapshot reads as none, the named stand-down
            return None
        docs = parsed.get("docs") if isinstance(parsed, dict) else None
        if isinstance(docs, dict) and all(isinstance(v, str) for v in docs.values()):
            return docs
        return None
    return None


def _earlier_evidence(root: Path) -> list[str]:
    """The paths an earlier docs run this session recorded (the record a new
    session's start sweeps), so a later run that changes nothing does not
    erase them: the failure-mode review found a second, read-only docs agent
    re-blocking Gate 2 over the first one's still-uncommitted edits."""
    # Bytes through decode_text_or_problem, as stop_gate reads the same record:
    # an operator writes it by hand (the gate's own message says how), and a
    # PowerShell or editor save carries a byte-order mark.
    try:
        from _json_safe import decode_text_or_problem  # noqa: PLC0415 -- tools/cc is on the path where the hooks run

        text, problem = decode_text_or_problem((root / STATE_DIR / _hook_utils.DOCS_REFRESHED).read_bytes())
        earlier = json.loads(text) if not problem else None
    except (OSError, ValueError, ImportError):  # fail-open: ok deliberate -- no earlier record, a torn one, or no decoder carries nothing forward
        return []
    docs = earlier.get("changed_docs") if isinstance(earlier, dict) else None
    return [p for p in docs if isinstance(p, str)] if isinstance(docs, list) else []


def _docs_evidence(root: Path, data: dict) -> tuple[list[str], str]:
    """``(changed_docs, evidence_scope)`` for the docs record: the paths new or
    changed since the run's start snapshot (``"run"``), with an earlier run's
    paths this session that are still uncommitted carried forward; or, with no
    snapshot, every dirty markdown file (``"tree"``), which is said once a
    session since it may hold the parent's own edits."""
    changed = _changed_markdown(root)
    start = _take_snapshot(root, data)
    if start is None:
        _hook_utils.say_once(
            root, "docs-evidence-unscoped", "subagent_stop", "subagentstop_failed_open_docs_evidence_unscoped",
            f"the {data.get('agent_type')!r} run had no start record, so its docs evidence is "
            "every markdown file with uncommitted changes, edits made before it ran included. "
            "SubagentStart kept no snapshot for it that could be read: a settings file that "
            "does not wire that hook (`espalier doctor` names one), an older subagent_start.py "
            "kept by an upgrade, a start payload with no agent_id, a git that did not answer "
            "at the start, or a snapshot file that would not parse",
            agent=str(data.get("agent_type", "")),
        )
        return changed, "tree"
    now = _digests(root, changed)
    own = [p for p in changed if start.get(p) != now[p]]
    still_dirty = set(changed)
    carried = [p for p in _earlier_evidence(root) if p in still_dirty and p not in own]
    return own + carried, "run"


def _relief_payload(root: Path, agent_type: str, flag_name: str, data: dict | None) -> dict:
    """What the relief record carries, per FLAG (so a second agent mapped to a
    flag in the shared table gets the record that flag's gate reads).

    Every record names the agent and quotes the head of its final message
    (SubagentStop's ``last_assistant_message``), so an operator who opens the
    file sees what the run concluded without opening a transcript. The docs
    record adds ``changed_docs``, the evidence Gate 2 actually reads (DEF-495),
    plus the total before any size trimming, and ``evidence_scope``: ``run``
    where the list is the run's own changes, ``tree`` where no start snapshot
    scoped it (DEF-1100). The review record's evidence is the run itself -- a
    review that found nothing is still a review -- so Gate 3 reads the agent
    name (DEF-608).
    """
    data = data or {}
    message = data.get("last_assistant_message")
    message = " ".join(message.split()) if isinstance(message, str) else ""
    payload: dict = {
        "agent": agent_type,
        "last_message_chars": len(message),
        "excerpt": message[:_EXCERPT_CHARS],
    }
    if flag_name == _hook_utils.DOCS_REFRESHED:
        changed, scope = _docs_evidence(root, data)
        payload["evidence_scope"] = scope
        payload["changed_docs"] = changed
        payload["changed_docs_total"] = len(changed)
    return payload


def _render_record(payload: dict) -> str:
    """The record as text, kept under the parity cap by trimming the path list
    (never the count): a docs-heavy session is exactly when this record is
    written, and Gate 2 reads the list's truthiness, not its length."""
    text = json.dumps(payload, ensure_ascii=False)
    while len(text) > _RECORD_MAX_CHARS and payload.get("changed_docs"):
        payload["changed_docs"] = payload["changed_docs"][:-1]
        text = json.dumps(payload, ensure_ascii=False)
    return text


def _set_relief_flag(root: Path, agent_type: str, data: dict | None = None) -> None:
    """Persist the stop_gate relief record for this agent type, if any.

    The record is ALWAYS written when a mapped agent runs — its presence says
    the agent ran, its body says what that produced. stop_gate distinguishes
    the two: no record means "never ran", a docs record with an empty
    ``changed_docs`` means "ran and changed nothing", and those need different
    messages or the operator loops through the same retry. Written atomically:
    the gate PARSES this file, and a torn write would read as a malformed
    record rather than as the run that happened.
    """
    # The shipped table plus the agents the adopter declares in espalier.toml
    # (code_review_agents, docs_refresh_agents): their own reviewer relieves
    # the gate the way code-reviewer does.
    flag_name = _hook_utils.relief_flags(root, hook="subagent_stop").get(agent_type)
    if not flag_name:
        return
    try:
        state_dir = root / STATE_DIR
        state_dir.mkdir(parents=True, exist_ok=True)
        _hook_utils.atomic_write_text(
            state_dir / flag_name,
            _render_record(_relief_payload(root, agent_type, flag_name, data)),
        )
    except OSError as e:
        # Exit 0, no JSON: recorded once a session (stderr alone reaches the
        # debug log only), so a Stop gate that stays shut after its agent ran
        # has a record saying why. Same shape as _append_subagent_reasoning.
        _hook_utils.say_once(
            root, f"relief-flag-{flag_name}-{type(e).__name__}", "subagent_stop",
            "subagentstop_failed_open_relief_flag",
            f"could not set the {flag_name!r} relief record for agent {agent_type!r} "
            f"({type(e).__name__}: {os_error_text(e)}); the Stop gate it relieves stays shut",
            fault=type(e).__name__, flag=flag_name,
        )


def _run_main() -> int:
    # Under maintenance mode this hook does nothing -- including NOT writing the
    # stop_gate relief record. That is consistent only because stop_gate
    # bypasses Gates 2 and 3 under the same flag: lifting a hygiene gate's
    # maintenance bypass requires lifting this early-return in the same change,
    # or the gate becomes unrelievable except by the hand-recorded escape.
    if _maintenance_mode.is_active(
        "subagent_stop",
        action="blueprint-append and stop_gate relief record skipped",
    ):
        return 0

    data = _hook_utils.read_stdin_safely()
    if not data:
        return 0

    # Recursive-loop guard: if a subagent is being asked to stop by another
    # subagent stop hook, do not re-enter. Honored by CC per protocol.
    if data.get("stop_hook_active"):
        return 0

    agent_type = str(data.get("agent_type", "")) or "unknown"
    # The entry carries the head of the agent's final message, not a fixed
    # sentence (DEF-586): the parent's tool-result stream holds the whole
    # report only until the next compaction, and the blueprint is what the
    # next session reads. The transcript path is the evidence the readers key
    # on to tell a report from an anchor -- so a report cut from a payload that
    # names no transcript still records where it came from.
    message = data.get("last_assistant_message")
    lead = _lead(message) if isinstance(message, str) else ""
    transcript = data.get("agent_transcript_path")
    has_transcript = isinstance(transcript, str) and bool(transcript.strip())
    evidence = transcript if has_transcript else "SubagentStop.last_assistant_message"
    root = _resolve_project_root()
    if has_transcript and not isinstance(message, str):
        # The two keys are documented together. A transcript with no message
        # STRING means the message key moved (a Claude Code rename), not that
        # the agent said nothing -- and without this line every stop would
        # record an anchor and the blueprint would stop gaining reports with
        # no signal at all (the trigger-gated-defect shape). Recorded once a
        # session: a stderr line alone reaches the debug log only.
        _hook_utils.say_once(
            root, "subagent-message-key", "subagent_stop", "subagentstop_failed_open_message_key",
            "the payload names agent_transcript_path but "
            "carries no last_assistant_message string; if Claude Code renamed "
            "the key, every stop now records an anchor and the blueprint stops "
            "gaining agent reports -- re-verify "
            "code.claude.com/docs/en/hooks#subagentstop",
        )

    # Relief-record side-effect FIRST: set before the (potentially-failing)
    # blueprint record so a stop_gate gate is unblocked even if the
    # blueprint append fails. Empty agent_type / unmapped agent_type is
    # a no-op.
    _set_relief_flag(root, agent_type, data)

    _append_subagent_reasoning(root, agent_type, lead, evidence)
    return 0


def main() -> int:
    """Public entry-point. Fail-OPEN umbrella: subagent_stop is an advisory
    SubagentStop finalizer, so an uncaught crash must degrade to a no-op
    advisory (exit 0 + one [ERROR] line), never a traceback that breaks the
    parent session's subagent-stop handling. Mirrors task_router.main.
    """
    try:
        return _run_main()
    except BaseException as exc:  # noqa: BLE001 — fail-open crash guard (advisory hook)
        # Exit 0, so a stderr line alone reaches the debug log only (the
        # protocol pin): the record, once a session, is what `/status --log`
        # counts, with the stderr line as its copy.
        _hook_utils.say_crash(
            "subagent_stop", "subagentstop_failed_open_crash", exc,
            "the subagent's reasoning and relief record were not written",
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
