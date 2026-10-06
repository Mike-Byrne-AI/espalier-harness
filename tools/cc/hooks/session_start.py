#!/usr/bin/env python3
"""SessionStart hook — context loader + blueprint-chain advancer.

Always exits 0. Emits bounded context as structured JSON on stdout so Claude
Code can inject it into the conversation context window. Warnings and
non-fatal errors go to stderr only.

On a NEW-session source (``startup``/``clear``) the hook also advances the
cognitive-blueprint chain — it starts a fresh blueprint node so this session's
reasoning lands in its own container, after capturing the PRIOR node's
reasoning for injection. ``resume``/``compact`` (and an unknown/absent source)
load read-only: they CONTINUE an existing logical session, and ``compact``
fires mid-session on every compaction, so advancing there would fragment the
chain. This replaces the prior reliance on the operator manually running
``/context-load`` after each ``/clear`` to advance the chain.

SessionStart cannot block Claude Code execution per the official hook
protocol (docs/external/cc-hook-protocol.md). Kill-switch findings are
audited and surfaced to stderr for the user; actual blocking lives in the
PreToolUse (write_guard) and ConfigChange (config_guard) hooks while those
hooks are active, and in CI for merge-time enforcement.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
import _hook_utils  # noqa: E402
from _hook_utils import atomic_write_text, check_branch, is_self_host_repo, repo_name, surface_status, warn, warn_exc, COLD_OPEN_FLAG  # noqa: E402
import _integrity  # noqa: E402
import _maintenance_mode  # noqa: E402
from _json_safe import decode_text_or_problem, os_error_text  # noqa: E402
try:  # owner of "can /recall reach this catalog?"
    import _recall  # noqa: E402
# fail-open: ok deliberate -- a missing sibling costs the /recall line only, and the banner says so where _recall is None
except ImportError:  # pragma: no cover - SessionStart is a REPORTER
    # Degrade, never take the orientation surface down: a missing sibling costs
    # the /recall promise on one banner line, not the whole banner.
    _recall = None  # type: ignore[assignment]
import _reinject  # noqa: E402
from _freshness_cache import (  # noqa: E402
    _is_state_cache_stale,
    _read_state_cache_safe,
)

# Hard OUTER ceiling on additionalContext bytes (last-resort backstop). The
# redesigned banner sits ~5.5KB (MEMORY digest + standing-principles index +
# footgun pointer + GOAL + orientation tail); individual tenants are governed by
# the per-section _SOFT_BUDGETS above, so this ceiling should never bind. The
# output is a system-reminder block, not main context window — well-bounded, and
# the boundary-truncation fallback below still fires if the budget overflows.
_MAX_CONTEXT_BYTES = 16_000

# The blueprint's soft-budget share of the context block. Blueprint continuity
# is the one CONTENT-not-index tenant, so this is GENEROUS (6KB) -- a normal
# handoff rides through whole. The outer _MAX_CONTEXT_BYTES backstops the block.
_MAX_BLUEPRINT_CONTEXT_BYTES = 6_000

# Per-section SOFT budgets (bytes). Generous by design: a normal-length goal,
# blueprint, or digest passes through WHOLE -- the budget only bites genuine
# bloat, and when it does it FLAGS (visibly) and truncates on a fragment
# boundary rather than swallowing content silently mid-word. The outer
# _MAX_CONTEXT_BYTES is the hard ceiling of last resort. Sections absent from
# this map are unbounded at the section level (the outer ceiling still backstops).
_SOFT_BUDGETS = {
    "blueprint": _MAX_BLUEPRINT_CONTEXT_BYTES,
    "goal": 2_000,
    "memory": 1_200,
    "standing": 1_000,
}
# Which source file each budgeted section is rendered FROM, so a bloat flag can
# point at the RIGHT file to trim rather than a single hardcoded guess (the
# ``memory`` section is ESPALIER_MEMORY.md, not cc/GOAL.md). ``blueprint`` is flagged on
# its own path (not via _bounded); the ``.get`` default covers unmapped names.
# Committed project-memory filename, routed through one per-file constant so a
# future rename is a value flip. Per-file (not a shared import) — tools/cc scripts
# run standalone; adding a sibling import risks the copy-subset footgun.
_MEMORY_FILENAME = "ESPALIER_MEMORY.md"

_SECTION_SOURCE = {
    "goal": "cc/GOAL.md",
    "memory": _MEMORY_FILENAME,
    "standing": "docs/STANDING_PRINCIPLES.md",
}
# GOAL is FLAGGED at its 2_000 soft budget but rides through WHOLE up to this
# ceiling: the goal-proper (At a glance / North star) sits below the perishable
# Notes head, so a soft-only cut hides exactly the part you want. Sized so the
# worst-case banner (sum of section caps + margin) stays under _MAX_CONTEXT_BYTES.
_GOAL_HARD_CAP = 4_500

# _truncate_keeping_tail admits the perishable HEAD section partially when whole
# trailing sections leave room. Below this floor a heading plus a sentence-stub
# costs more attention than it returns, so the section is dropped whole instead.
_MIN_PARTIAL_SECTION_BYTES = 400
# The two blank-line joins _truncate_keeping_tail adds around a partial section.
_SECTION_JOIN_BYTES = 4

# Blueprint `load` outputs that mean the continuity surface did NOT come up --
# the health self-check flags these so a silently-missing blueprint is visible.
# (The success/auto-start strings and real reasoning text are NOT failures.)
_BLUEPRINT_FAILURE_STATES = frozenset({
    "No blueprint system",
    "Blueprint load failed",
    "No active blueprint",
    "No active blueprint (auto-start failed)",
})

# Orientation Claude performs on first response, replacing the typed
# `/context-load`. The slash command stays available for explicit mid-session
# re-orient / PostCompact recovery / DEGRADED-surface recovery. The session
# OPENS with Claude's own provisional reasoning over the handoff -- generating
# thinking about the context (not just receiving it) primes the session and
# surfaces the read for the operator to correct on turn one. The footgun line
# and the no-digest fallback are INDEPENDENT conditions, not two arms of one
# identity fork: the first rides the catalogs, the second rides the digest, and
# a tree can honestly warrant both or neither (see the call site).
# The two GOAL-bearing clauses, swapped on whether a GOAL section was actually
# injected. Until 2026-09-30 nothing created `cc/GOAL.md` on an adopter's tree,
# so naming it unconditionally told every adopter's first response to read a
# section that is not in their banner, and to source a state line from a file
# they do not have (DEF-424f). init seeds it by default now, but an opted-out
# (`goal_snapshot = false`), deleted or pre-seed tree still has none, so the
# swap stays keyed on the injected section. Same shape as the SHARP_EDGES /
# adopter split below.
#
# Interpolated as CLAUSES rather than kept as two whole blocks: a second copy of
# this prose is a restatement that drifts at the next wording change, and only
# one of the copies would get edited.
_ORIENTATION_SOURCES_WITH_GOAL = "blueprint + Notes to next session + GOAL"
_ORIENTATION_SOURCES_NO_GOAL = "blueprint + Notes to next session"

_ORIENTATION_STATE_LINE_WITH_GOAL = """\
- Give the operator a one-glance state line (Working on / Next / Owed, from
  GOAL) and END with a proposed next move + "confirm or redirect?"."""

# ⚠ Keep "confirm or redirect" ON ONE LINE. Three tests in test_hooks.py match
# that phrase as a plain substring, and the first cut of this variant wrapped it
# as "confirm or\n  redirect?" -- three reds from a rewrap alone, with every
# word still present. The banner is prose matched by substring, so a line break
# inside a matched phrase is a behaviour change.
_ORIENTATION_STATE_LINE_NO_GOAL = """\
- Give the operator a one-glance state line (Working on / Next / Owed, read
  from the continuity above) and END with a proposed next move +
  "confirm or redirect?"."""


def _orientation_common(has_goal: bool) -> str:
    """Render the always-on orientation block.

    ``has_goal`` must reflect whether a GOAL section reached the banner, not
    whether this is the self-host repo: the file is gitignored, so even here it
    can be absent, and the instruction has to match what was actually injected.
    """
    sources = (
        _ORIENTATION_SOURCES_WITH_GOAL if has_goal
        else _ORIENTATION_SOURCES_NO_GOAL
    )
    state_line = (
        _ORIENTATION_STATE_LINE_WITH_GOAL if has_goal
        else _ORIENTATION_STATE_LINE_NO_GOAL
    )
    return f"""\
Orientation (on first response -- this REPLACES the old terse status report):
- Open with your genuine, PROVISIONAL first-thoughts read of the continuity
  above ({sources}). REASON about it -- what
  stands out, what you'd watch, where you'd pick up -- don't just restate it.
  Your own thinking over the context primes the session and surfaces your read
  for the operator to correct. Keep it a hypothesis to confirm, not a plan.
{state_line}
- If the Surface line above is DEGRADED, run the recovery it names first.
- Do NOT re-litigate decisions already marked settled in the handoff.
"""

def _orientation_footgun_line(families: list[str]) -> str:
    """The orientation bullet that teaches /recall, naming what it indexes HERE.

    ``families`` is ``_recall.indexed_sources(root)`` -- the source families the
    corpus actually yielded on this tree, in the retriever's own words. This used
    to be a constant that hand-listed three sources "indexed UNGATED, so the
    claim holds on every tree"; the retriever then started indexing
    docs/STANDING_PRINCIPLES.md wherever the file exists and the prose never
    followed (DEF-562). Under-claiming was the safe direction, but a list that
    can be read off the corpus should not be a claim at all. A family that did
    not yield on this tree is not named, so an adopter is never sent down a
    retrieval path that returns nothing for it; one that did yield is.
    """
    body = (
        "Footguns/failure-modes: pull the relevant entry with /recall <topic> (it "
        f"indexes {' + '.join(families)}); the folder CLAUDE.md ladder also fires "
        "per-surface footguns on entry. Don't scan the whole catalog."
    )
    return textwrap.fill(body, width=78, initial_indent="- ",
                         subsequent_indent="  ", break_long_words=False,
                         break_on_hyphens=False) + "\n"

# Fallback when no recent-session digest reached the banner: point at
# ESPALIER_MEMORY.md as the running-decisions source the digest would otherwise
# summarize. Gated on the DIGEST's absence, not on repo identity -- `init`
# deploys ESPALIER_MEMORY.md, so an adopter who has run /handoff HAS a digest,
# and a fresh self-host clone with an empty Session Log does not. The old
# wording named "the self-host recent-session digest", an internal concept with
# no referent on the very tree this line exists to serve.
_ORIENTATION_NO_DIGEST_LINE = """\
- Consult ESPALIER_MEMORY.md for the project's running decisions (no
  recent-session digest reached this banner -- its Session Log has no dated
  rows yet).
"""

_ORIENTATION_TAIL = """\
- If RESUMING prior work, read cc/_working_summary.md (/read-summary) and reason
  over it before acting -- it is the always-current pick-up-where-we-left-off
  mirror; self-reading it primes better than a passive dump would.
- For any repo change, enter the workflow: /implement-task (or --multi for
  multi-phase) -> /preflight -> /commit -> /handoff. Don't free-hand source edits.\
"""


_resolve_project_root = _hook_utils.resolve_project_root


# SessionStart fires on four sources: ``startup``, ``resume``, ``clear``,
# ``compact`` (confirmed against the official CC hooks docs). Only ``startup``
# and ``clear`` begin a NEW logical session that should get its own blueprint
# node. ``resume`` and ``compact`` CONTINUE an existing session — and
# ``compact`` fires MID-session on every compaction, so advancing the chain
# there would spawn a spurious node each time. An unknown/absent source fails
# toward NOT advancing (the pre-source-aware behavior) so a future protocol
# change can never silently fragment the chain.
_NEW_SESSION_SOURCES = frozenset({"startup", "clear"})
# Continuation sources that must NOT rewind per-session gate state (a mid-session
# compact/resume re-fires SessionStart). Everything else — startup, clear, or an
# unlabeled/unknown payload — clears, so a genuinely fresh session starts clean.
_CONTINUATION_SOURCES = frozenset({"resume", "compact"})


def _should_advance_chain(source: str) -> bool:
    """True iff this SessionStart source should start a new blueprint node."""
    return source in _NEW_SESSION_SOURCES


def _set_cold_open_flag(root: Path, source: str) -> None:
    """Producer half of the cold-open baton: write a one-shot flag on a NEW
    logical session (startup/clear); remove it on a continuation source so a
    resumed/compacted session never inherits a stale cold-open.

    Reuses ``_should_advance_chain`` -- the same startup|clear predicate that gates
    blueprint-chain advance -- so "new session" means one thing across the hook.
    Best-effort and fail-open: a flag-I/O error degrades to no-orientation and
    never blocks the session (SessionStart cannot block regardless).
    """
    state_dir = root / _hook_utils.STATE_DIR
    flag = state_dir / COLD_OPEN_FLAG
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        if _should_advance_chain(source):
            atomic_write_text(flag, datetime.now(timezone.utc).isoformat())
        else:
            flag.unlink(missing_ok=True)
    except OSError as e:
        warn_exc("session_start: cold-open flag write failed", e)


def _blueprint_present(root: Path) -> bool:
    """True if a blueprint pointer exists on disk in ANY state — a real file or
    a symlink, including a dangling one.

    The bootstrap decision keys on PRESENCE, not readability: a present-but-
    unreadable ``latest.json`` (symlink / oversize / corrupt — for which
    cognitive_blueprint._load_latest returns None, so a `load` yields empty
    output) must NOT be treated as "no blueprint" and clobbered by a
    continuation source (resume/compact), which would reset the chain
    mid-compaction. ``is_symlink`` catches the dangling-symlink case
    ``exists()`` misses.
    """
    p = root / "cc" / "blueprints" / "latest.json"
    try:
        return p.exists() or p.is_symlink()
    except OSError:  # fail-open: ok deliberate -- a blueprint that cannot be stat-ed reads as absent; the banner's blueprint line says none
        return False


#: Files ``_safe_read`` has already named on stderr this session (it reads the
#: memory file twice), so a re-encoded file is named once, not per reader.
_ENCODING_WARNED: set[str] = set()


def _safe_read(path: Path, max_lines: int = 0) -> str:
    """Read file content, optionally limited to max_lines.

    Absent file -> silent empty string (normal). Present but unreadable -> warn.
    Decoded through ``decode_text_or_problem`` first, so a UTF-8 or UTF-16
    byte-order mark from an operator's editor or a PowerShell re-encode reads
    as text (the memory file is hand-edited at every handoff, and a UTF-16 one
    rendered as every other byte NUL through the replacing decode; DEF-797).
    When it cannot -- bytes that are not UTF-8, or a mark-less UTF-16 file --
    the file is named ONCE on stderr with the encoding to re-save in, and the
    reporter still renders what it can: the replacing UTF-8 decode with the
    NULs dropped, which recovers the ASCII of a mark-less UTF-16 file. It
    never raises on content.
    """
    if not path.exists():
        return ""
    try:
        raw = path.read_bytes()
        text, problem = decode_text_or_problem(raw)
        if problem:
            if str(path) not in _ENCODING_WARNED:
                _ENCODING_WARNED.add(str(path))
                warn(f"{path.name} is {problem}")
            text = raw.decode("utf-8", errors="replace").replace("\x00", "")
        if max_lines > 0:
            lines = text.splitlines()[:max_lines]
            return "\n".join(lines)
        return text
    except OSError as e:
        warn(f"could not read {path.name}: {os_error_text(e)}")
        return ""


def _check_dirty(root: Path) -> str:
    """Report uncommitted changes count."""
    try:
        result = subprocess.run(  # spawn: ok a reporter: a git that cannot run costs the dirty line, never the banner
            ["git", "status", "--short"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, cwd=str(root),
        )
        lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
        if not lines:
            return "clean"
        return f"{len(lines)} uncommitted changes"
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return "unknown"


# Loose processes (DEF-752). A fan-out or background probe whose shell parent
# died leaves its child reparented to PID 1 at full CPU: a `python3 -` heredoc
# probe spun 44.75 CPU-hours across two sessions (2026-09-10), invisible to a
# memory reading (9 MB RSS) and to ListAgents; the 2026-08-25 machine note
# records fifty `yes` spinners at once and three wrong hypotheses before anyone
# read the process table. Root CLAUDE.md step 0 asks the session to read it by
# hand; this is the mechanical twin -- a reporter line with the PIDs, never a
# kill. POSIX only (`ps -axo`); Windows reports nothing.
_LOOSE_CPU_FLOOR_SECONDS = 10 * 60      # CPU time, not wall-clock: a spinner earns it fast
# Command stems (the comm basename, case-folded, ASCII-folded), in two rosters
# because they match differently: a prefix catches python / python3 /
# python3.14 / pythonw; an exact name keeps `yes` from swallowing `yesterday-sync`.
_LOOSE_PREFIX_STEMS = ("python",)
_LOOSE_EXACT_STEMS = ("yes",)


def _is_loose_stem(stem: str) -> bool:
    return stem.startswith(_LOOSE_PREFIX_STEMS) or stem in _LOOSE_EXACT_STEMS


def _ps_time_seconds(text: str) -> float | None:
    """CPU seconds from a `ps -o time` cell: `[D-]HH:MM:SS` (Linux, procps) or
    `M+:SS.ss` with unbounded minutes (macOS). None when it does not parse."""
    days = 0
    if "-" in text:
        day_part, _, text = text.partition("-")
        if not day_part.isdigit():
            return None
        days = int(day_part)
    try:
        nums = [float(p) for p in text.split(":")]
    except ValueError:  # fail-open: ok text-fallback -- a ps time field that does not parse skips that row
        return None
    if len(nums) == 3:
        hours, minutes, seconds = nums
    elif len(nums) == 2:
        hours, (minutes, seconds) = 0.0, nums
    else:
        return None
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _loose_processes(table: str) -> list[tuple[int, str, str]]:
    """``(pid, stem, cpu)`` for every row of a `ps -axo pid,ppid,time,comm`
    table whose parent is PID 1, whose command stem is python* or yes, and whose
    CPU time clears the floor. The header row and any row that does not parse
    are skipped, so a truncated or foreign table yields nothing, never a crash."""
    found: list[tuple[int, str, str]] = []
    for line in table.splitlines()[1:]:
        cols = line.split(None, 3)     # comm may carry spaces (an .app bundle path)
        if len(cols) < 4:
            continue
        pid, ppid, cpu, comm = cols
        if ppid != "1" or not pid.isdigit():
            continue
        # ASCII-folded: the stem lands in operator-facing hook text, and a
        # non-ASCII (or replacement-char) path would break that contract.
        stem = (
            comm.strip().replace("\\", "/").rsplit("/", 1)[-1].lower()
            .encode("ascii", "replace").decode("ascii")
        )
        if not _is_loose_stem(stem):
            continue
        seconds = _ps_time_seconds(cpu)
        if seconds is None or seconds < _LOOSE_CPU_FLOOR_SECONDS:
            continue
        found.append((int(pid), stem, cpu))
    return found


def _read_process_table() -> str:
    """`ps -axo pid,ppid,time,comm` on POSIX; '' on Windows or on any failure."""
    if os.name != "posix":
        return ""
    try:
        result = subprocess.run(  # spawn: ok a reporter: a ps that cannot run costs the Loose: line, never the banner
            ["ps", "-axo", "pid,ppid,time,comm"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):  # fail-open: ok deliberate -- a reporter that cannot read the process table prints no Loose: line; that is its contract
        return ""
    return result.stdout if result.returncode == 0 else ""


def _loose_processes_line(table: str | None = None) -> str:
    """The banner's `Loose:` value -- PIDs, stems, CPU time and the one-paste
    kill -- or '' when nothing qualifies. ``table`` is for tests; production
    reads the live process table."""
    rows = _loose_processes(_read_process_table() if table is None else table)
    if not rows:
        return ""
    named = ", ".join(f"PID {pid} {stem} {cpu} CPU" for pid, stem, cpu in rows)
    pids = " ".join(str(pid) for pid, _, _ in rows)
    # PPID 1 is a fact; "orphan" is an inference. A run you detached on
    # purpose (`nohup ... & disown` -- the proof tier itself), a launchd or
    # systemd service, and every process in a container look identical here,
    # so the line names the fact and tells the reader to check before pasting.
    return (
        f"{named} -- parent is PID 1: a fan-out's orphan, a run you detached on "
        f"purpose (nohup ... & disown, e.g. the proof tier), or any process in a "
        f"container; reporter only, nothing was killed. Check before you paste: "
        f"kill {pids}"
    )


# ---------------------------------------------------------------------------
# Sibling sessions -- the banner's `Sessions:` line. Two Claude
# Code sessions in one tree (two tabs, an IDE and a CLI, a worktree entered
# mid-session, whose hooks keep the main checkout as their project dir) share
# every current-X file under cc/ and .espalier-state/ -- the plan, the blueprint
# head, the working summary, the per-session flags -- and nothing said so. Each
# session writes a marker under .espalier-state/sessions/ at start and touches
# it on every prompt (task_router); this line names the siblings touched within
# the live window. Reporter only: it names the collision, it does not move the
# files (a later wave keys them by session).

_SESSIONS_NAMED_MAX = 3
_SESSIONS_TAIL = (
    "cc/ and .espalier-state/ are shared, so the plan, the blueprint head and the "
    "working summary are last-writer-wins. Keep one session per launched worktree "
    "(entering a worktree mid-session does not separate them: its hooks keep this "
    "checkout). Reporter only: a window closed without /handoff keeps its marker "
    "until it ages out, so a sibling that last prompted about when you did may be "
    "your own previous window. (docs/SHARP_EDGES.md \"The live working-summary doc "
    "is last-writer-wins under parallel sessions\")"
)


def _age_text(seconds: float | None) -> str:
    """'just now', '3 min ago', '2 h ago', '1 d ago'; 'unknown' for None."""
    if seconds is None:
        return "unknown"
    s = max(0, int(seconds))
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600} h ago"
    return f"{s // 86400} d ago"


def _sessions_line(
    root: Path, sid: str, rows: list[dict[str, Any]] | None = None, now: float | None = None,
) -> str:
    """The banner's `Sessions:` value -- each other session whose marker was
    touched within the live window: its id prefix, when it started, when it
    last prompted; then what is shared and the sharp edge -- or '' when none.
    ``rows`` is for tests; production reads the markers under ``root``."""
    rows = _hook_utils.other_live_sessions(root, sid, now) if rows is None else rows
    if not rows:
        return ""
    here = str(root).replace("\\", "/").rstrip("/")
    named = []
    for row in rows[:_SESSIONS_NAMED_MAX]:
        ident = _hook_utils.safe_session_id(row.get("session_id"))[:8]
        started_s = row.get("started_s")
        started = "start time unknown" if started_s is None else f"started {_age_text(started_s)}"
        # The recorded cwd is the one field that says WHICH window: the same
        # checkout, or a worktree entered mid-session. Shown only when it
        # differs from this root; folded to ASCII like every banner value.
        cwd = str(row.get("cwd") or "").replace("\\", "/").rstrip("/")
        # A recorded cwd is tail-capped at the write, so a long path to THIS
        # root reads back as "...<its tail>": a tail match is the same tree.
        same = cwd == here or (cwd.startswith("...") and here.endswith(cwd[3:]))
        where = f", in {cwd}" if cwd and not same else ""
        where = where.encode("ascii", "replace").decode("ascii")
        named.append(f"{ident} ({started}, last prompt {_age_text(row.get('last_seen_s'))}{where})")
    count = len(rows)
    head = f"{count} other session{'s' if count != 1 else ''} in this tree: " + ", ".join(named)
    more = count - len(named)
    if more > 0:
        head += f", and {more} more"
    return f"{head} -- {_SESSIONS_TAIL}"


# ---------------------------------------------------------------------------
# Pull requests -- the SessionStart half of the /ship lane. A lane shipped with
# auto-merge armed lands on the base branch while nobody is watching, so the
# next session opens on a local base branch that is behind it; when a check
# went red instead, it opens on a PR that sits armed and unmerged until someone
# notices. Two header lines name both: `Open PRs:` lists each pull request the
# operator has open, by number and head branch, with its check tally and its
# auto-merge state; `Merged:` lists each recently merged one whose merge commit
# the local base branch does not yet reach, with the pull that catches up, and
# each one whose latest run of a check is red -- a check that is not required
# finishes after the merge and reports to nobody (one observed case: the
# Windows leg went red 28 minutes after the merge; the rollup carried it and
# the line was empty). So the session knows what is in flight, what landed
# behind its back, and what landed red, before it commits anything.
#
# Reporter only, and bounded as a BLOCK: two `gh pr list` reads (the open
# PRs, then the recent merges -- separate reads, because one recency window
# shared by every state let ten merges evict the one open PR the line exists
# to name) and a read-only git question per merged row, all under one
# eight-second budget. The whole hook runs under settings.json's 15 s
# ceiling, and blowing THAT loses the whole banner, so when the budget is
# spent the block returns what it has. Measured 1.3 s for one read with every
# field (2026-09-27). Any failure -- no `gh`, no sign-in, no GitHub remote, a
# timeout, a foreign JSON shape -- costs the lines, never the banner. Read
# once in main and threaded in, like the process table, so the builders never
# spawn `gh` on a scratch tree.
_PR_BLOCK_BUDGET_SECONDS = 8.0   # the two list reads, the git questions, and the required-check reads together
_PR_READ_CAP_SECONDS = 5.0       # one gh list read, never more
_PR_CHECKS_CAP_SECONDS = 2.0     # one required-check read (a rendered row with a red), never more
_PR_GIT_CAP_SECONDS = 2.0        # one git question, never more
_OPEN_PR_LIMIT = 10              # open PRs are few; the line renders the first _PR_RENDER_ROWS
_MERGED_PR_ROWS = 5              # the most recent merges, each asked about once
_PR_RENDER_ROWS = 3              # per line, then "and N more": the header is never clipped
_PR_FIELDS = (
    "number,state,headRefName,baseRefName,isDraft,mergeStateStatus,autoMergeRequest,"
    "statusCheckRollup,mergeCommit,mergedAt"
)
# One `statusCheckRollup` row is a CheckRun (`status` + `conclusion`) or a
# legacy StatusContext (`state`). Not green and not still running reads as red:
# a cancelled or timed-out cell holds a merge exactly as a failure does.
_CHECK_GREEN = frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})
_CHECK_RUNNING = frozenset({"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"})
# A completed CheckRun that reached no verdict. Open, `_check_outcome` reads it as
# red (a cancelled cell holds a merge); merged, the leg simply never reported.
_NO_VERDICT = frozenset({"CANCELLED", "STALE"})
# The `gh pr checks` buckets that hold a merge: a cancelled required cell holds
# it as surely as a failed one (a job no runner picked up reads `cancel`).
_RED_BUCKETS = frozenset({"fail", "cancel"})
_PR_INDENT = " " * len("Open PRs:  ")   # `Merged:    ` is the same width


def _pr_deadline() -> float:
    """The block's budget as a monotonic instant; every read and git question
    below takes its timeout from what is left of it."""
    return time.monotonic() + _PR_BLOCK_BUDGET_SECONDS


def _seconds_left(deadline: float | None, cap: float) -> float:
    """The timeout for one subprocess: ``cap``, or less when the block's
    deadline is nearer; zero or negative means do not start it."""
    return cap if deadline is None else min(cap, deadline - time.monotonic())


def _ascii(text: str) -> str:
    """ASCII-folded: the value lands in operator-facing hook text, and a
    non-ASCII branch or check name would break that contract."""
    return text.encode("ascii", "replace").decode("ascii")


def _gh_pr_list(root: Path, state: str, limit: int, deadline: float | None) -> str:
    """One `gh pr list` read for the caller's PRs in ``state``; '' on any
    failure (no `gh`, not signed in, no GitHub remote, a timeout, no budget)."""
    timeout = _seconds_left(deadline, _PR_READ_CAP_SECONDS)
    if timeout <= 0.2:
        return ""
    try:
        result = subprocess.run(  # spawn: ok a reporter: a gh that cannot run costs the Open PRs: line; a missing gh is named by the load-bearing-tool warning
            ["gh", "pr", "list", "--author", "@me", "--state", state,
             "--limit", str(limit), "--json", _PR_FIELDS],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, cwd=str(root),
        )
    except (OSError, subprocess.SubprocessError):  # fail-open: ok deliberate -- a reporter that cannot run gh prints no Open PRs: line; a missing gh is named by the load-bearing-tool warning
        return ""
    return result.stdout if result.returncode == 0 else ""


def _read_open_prs(root: Path, deadline: float | None = None) -> str:
    return _gh_pr_list(root, "open", _OPEN_PR_LIMIT, deadline)


def _read_merged_prs(root: Path, deadline: float | None = None) -> str:
    return _gh_pr_list(root, "merged", _MERGED_PR_ROWS, deadline)


def _gh_pr_required_reds(root: Path, number: int, deadline: float | None) -> list[str] | None:
    """The names of the REQUIRED checks that are red on pull request ``number``
    (failed or cancelled: either holds the merge),
    from one `gh pr checks <n> --required --json name,bucket` read, made only
    when the tally already has a red (the listing carries no is-required flag,
    and a pull request has merged with three advisory legs red). `gh pr
    checks` exits 1 when a check has failed and 8 while one is pending -- the
    two states this read exists for -- so stdout is parsed whenever it is JSON,
    whatever the exit code. None only when the read could not be made or
    answered (no budget left, no `gh`, a timeout, unparseable output); the
    caller names that in the tail instead of guessing which red holds."""
    timeout = _seconds_left(deadline, _PR_CHECKS_CAP_SECONDS)
    if timeout <= 0.2:
        return None
    try:
        result = subprocess.run(  # spawn: ok a reporter: a gh that cannot run costs the required-red name in one tail, never the line; a missing gh is named by the load-bearing-tool warning
            ["gh", "pr", "checks", str(number), "--required", "--json", "name,bucket"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, cwd=str(root),
        )
    except (OSError, subprocess.SubprocessError):  # fail-open: ok deliberate -- a reporter that cannot run gh says so in the tail (could not read which reds are required); a missing gh is named by the load-bearing-tool warning
        return None
    try:
        rows = json.loads(result.stdout or "")
    except ValueError:  # fail-open: ok deliberate -- unparseable output is named in the tail (could not read which reds are required), never read as no required red
        return None
    if not isinstance(rows, list):
        return None
    return sorted(
        _ascii(str(row.get("name") or "?"))
        for row in rows
        if isinstance(row, dict) and str(row.get("bucket") or "").lower() in _RED_BUCKETS
    )


def _pr_has_red(pr: dict) -> bool:
    """Does the row's tally carry a red? The gate on the required-checks read:
    a row without a red never spends the extra `gh` call."""
    rollup = pr.get("statusCheckRollup")
    rows = _latest_run_per_check(rollup if isinstance(rollup, list) else [])
    return any(_check_outcome(r) == "red" for r in rows)


def _check_outcome(row: object) -> str:
    """'green', 'running' or 'red' for one statusCheckRollup row. A row of a
    shape this reader does not know reads as running: unknown is not a pass."""
    if not isinstance(row, dict):
        return "running"
    state = row.get("state")
    if isinstance(state, str) and state:  # StatusContext
        s = state.upper()
        return "green" if s in _CHECK_GREEN else "running" if s in _CHECK_RUNNING else "red"
    if str(row.get("status") or "").upper() != "COMPLETED":
        return "running"
    return "green" if str(row.get("conclusion") or "").upper() in _CHECK_GREEN else "red"


def _prs(listing: str) -> list[dict]:
    """The pull requests a `gh pr list` JSON listing carries. A row that is not
    a dict with an integer `number` is skipped, so a foreign shape (an error
    page, a bare object, `null`) yields nothing, never a crash."""
    try:
        data = json.loads(listing) if listing.strip() else []  # json-dict-safe: ok — a LIST of rows; each row is isinstance-checked below
    except ValueError:  # fail-open: ok text-fallback -- a listing that is not JSON carries no pull requests
        return []
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict) and isinstance(row.get("number"), int)]


def _pr_state(pr: dict) -> str:
    return str(pr.get("state") or "").upper()


def _render_rows(rows: list[str]) -> str:
    """The first `_PR_RENDER_ROWS` rows, one per line aligned under the label,
    then "and N more": the header is never clipped, so its lines are counted
    here instead."""
    if not rows:
        return ""
    shown = rows[:_PR_RENDER_ROWS]
    if len(rows) > _PR_RENDER_ROWS:
        shown.append(f"and {len(rows) - _PR_RENDER_ROWS} more")
    return ("\n" + _PR_INDENT).join(shown)


# ----------------------------------------------------------------- the mail --
# The mail channel between the machines that share this repository
# (tools/cc/mail.py: one append-only ref per machine on origin, typed
# messages, claims as a fold). Read here so a claim or a request the other
# box left is in front of the session before it commits anything. Off, and
# spawning nothing, where `git config espalier.machine` names no machine.
# Reporter only, and bounded under the pull-request block's deadline (one
# eight-second budget for both blocks, under settings.json's 15 s ceiling):
# one fetch, then local reads, each taking what is left of the budget, so a
# slow `gh` costs the mail line and never the banner (the review that found
# the two budgets summing to twelve of fifteen, 2026-10-05). Read once in main
# and threaded in, like the process table, so the builders never spawn for it.
_MAIL_FETCH_CAP_SECONDS = 3.0   # the one network call, never more
_MAIL_READ_CAP_SECONDS = 2.0    # one local git read (the config, the refs, a file), never more
_MAIL_TAIL = "(the other machine's text, unverified; orient with it; bodies: /inbox)"


def _load_mail() -> Any:
    """``tools/cc/mail.py`` by path under a private alias (post_compact.py's
    parent-dir pattern, by path so an older deploy set without the module
    costs the line and not the hook, and a test's own instance of the module
    is left alone). None where it is not deployed beside the hooks."""
    path = Path(__file__).resolve().parent.parent / "mail.py"
    if not path.is_file():
        return None
    alias = "_session_start_mail"
    mod = sys.modules.get(alias)
    if mod is None:
        spec = importlib.util.spec_from_file_location(alias, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[alias] = mod
        spec.loader.exec_module(mod)
    return mod


def _mail_line(root: Path, deadline: float | None = None, mail: Any = None) -> str:
    """The banner's `Mail:` value: the unread messages the other machines
    left, newest first, one headline per row (three, then "and N more"), with
    the tail that says whose text it is -- or '' where nothing is unread after
    a fetch that went through. A fetch that could not be made is said in the
    line, beside what was fetched before. Where this clone names no machine
    but already holds another machine's mail ref (a plain ``git fetch
    origin`` brings them in), the line says how to opt in; with no ref either,
    no name means no line and no spawn past the config read. ``deadline`` is
    the pull-request block's: every read here takes what is left of it, and
    a budget already spent costs the line. ``mail`` is the channel module,
    injectable for tests."""
    mail = mail if mail is not None else _load_mail()
    if mail is None:
        return ""
    left = _seconds_left(deadline, _MAIL_READ_CAP_SECONDS)
    if left <= 0.2:
        return ""
    machine, _how = mail.machine_setting(root, timeout=left)
    if machine is None:
        left = _seconds_left(deadline, _MAIL_READ_CAP_SECONDS)
        others = mail.local_mail_machines(root, timeout=left) if left > 0.2 else []
        if not others:
            return ""
        return (f"{', '.join(_ascii(m) for m in others)} write(s) on the mail channel and this clone names "
                "no machine: `git config espalier.machine <name>` turns it on here, then /inbox reads it")
    note = ""
    timeout = _seconds_left(deadline, _MAIL_FETCH_CAP_SECONDS)
    if timeout > 0.2:
        ok, problem = mail.fetch_mail(root, timeout=timeout)
        if not ok:
            note = f"(could not fetch: {_ascii(problem)[:80]}; what was fetched before)"
    else:
        note = "(no time left to fetch; what was fetched before)"
    left = _seconds_left(deadline, _MAIL_READ_CAP_SECONDS)
    if left <= 0.2:
        return "(no time left to read the mail refs; /inbox reads them)"
    by_machine, _skipped = mail.read_mail(root, timeout=left)
    pending = mail.unread(by_machine, mail.read_cursor(root), exclude_machine=machine)
    rows = [_ascii(mail.headline(m)) for m in reversed(pending)]
    if not rows:
        return note
    return _render_rows(rows) + "\n" + _PR_INDENT + _MAIL_TAIL + (f" {note}" if note else "")


def _latest_run_per_check(rows: list) -> list:
    """One row per check name, its latest run. A push or a title edit re-runs
    a workflow, and the rollup lists the superseded run (CANCELLED) beside the
    new one, while GitHub's merge rule reads only the latest run per name --
    so the tally reads the same (the reporter's own first live read showed six
    false reds on its lane, 2026-09-28). A later `startedAt` wins; with none,
    the later row in the rollup wins. Rows with no name pass through."""
    keep: dict[str, tuple[str, int, object]] = {}
    order: list[tuple[str | None, object]] = []
    for i, r in enumerate(rows):
        name = str(r.get("name") or r.get("context") or "") if isinstance(r, dict) else ""
        if not name:
            order.append((None, r))
            continue
        started = str(r.get("startedAt") or "")
        prev = keep.get(name)
        if prev is None:
            order.append((name, None))
        if prev is None or (started, i) >= (prev[0], prev[1]):
            keep[name] = (started, i, r)
    return [keep[n][2] if n is not None else r for n, r in order]


def _pr_summary(pr: dict, required_red: list[str] | None = None) -> str:
    """One open pull request as the banner names it: number, head branch, the
    check tally (red checks by name, at most three; one row per check, its
    latest run), a conflict or behind-base note, and what auto-merge will do
    about it. ``required_red`` is the answer of the required-checks read for a
    row with a red (the names that are red AND required; ``[]`` when none is;
    ``None`` when the read could not be made), so a merge GitHub reports as
    blocked names what holds it instead of guessing."""
    rollup = pr.get("statusCheckRollup")
    rows = _latest_run_per_check(rollup if isinstance(rollup, list) else [])
    outcomes = [(_check_outcome(r), r) for r in rows]
    green = sum(1 for o, _ in outcomes if o == "green")
    running = sum(1 for o, _ in outcomes if o == "running")
    red = sum(1 for o, _ in outcomes if o == "red")
    head = _ascii(str(pr.get("headRefName") or "?"))
    base = _ascii(str(pr.get("baseRefName") or "the base branch"))
    lead = f"#{pr['number']} {head} --"
    if pr.get("isDraft"):
        lead += " draft;"
    if not outcomes:
        checks = "no checks reported"
    else:
        checks = f"{green} of {len(outcomes)} checks green"
        if running:
            checks += f", {running} running"
        if red:
            names = [
                _ascii(str(r.get("name") or r.get("context") or "?"))
                for o, r in outcomes if o == "red" and isinstance(r, dict)
            ]
            checks += f", {red} red ({_check_names(names)})"
    merge_state = str(pr.get("mergeStateStatus") or "").upper()
    held = ""
    behind = False
    if merge_state == "DIRTY":
        checks += f", conflicts with {base}"
        held = "the conflict"
    elif merge_state == "BEHIND":
        checks += f", behind {base}"
        behind = True
    if not pr.get("autoMergeRequest"):
        tail = "auto-merge not armed"
    elif held:
        # The server cannot make this merge (GitHub honours no merge driver);
        # the ship driver's catch-up makes it locally with the record files --
        # the memory row, the ledger's rows and counts, the probes -- resolved
        # by shape, then pushes and re-binds. Name that verb, as the behind
        # row names its own remedy.
        tail = (f"auto-merge armed but held by {held}; tools/cc/ship.py catch-up merges {base} in "
                "with the record files resolved by shape, then re-binds")
    elif behind:
        # GitHub holds a behind-base merge only when the branch must be up to
        # date (a protection setting this reader cannot see), and a held one
        # sits silently across sessions: name the catch-up, not the maybe.
        # `gh pr update-branch` changes nothing on a lane that is not behind.
        # Ahead of the red clause: under that rule a behind lane cannot merge
        # until it is caught up whatever its checks say, and the tally above
        # already names the red.
        tail = (f"auto-merge armed; if it sits, gh pr update-branch {pr['number']} "
                f"catches the lane up, then re-bind any title marker")
    elif merge_state in ("BLOCKED", "UNKNOWN"):
        # GitHub is holding the merge (BLOCKED: a required check has not
        # passed, or a review is required; UNKNOWN: it has not decided yet).
        # Until 2026-09-30 this row fell through to the optimistic tail below
        # while a pull request sat armed and blocked on a required red for a title
        # that was already correct. Say what holds it: the required reds by
        # name when the read answered, the running count while checks run,
        # and the command that answers when the read could not be made. A
        # required red is a test's verdict or a lost runner's (2026-10-05: two
        # cells ended with no failed step and parked a merge), and only the
        # driver's annotation read tells them apart, so the tail names it
        # instead of guessing "fix" for a cell a re-bind would never re-run.
        if red and required_red:
            tail = (f"auto-merge armed but held: required "
                    f"{'check' if len(required_red) == 1 else 'checks'} red "
                    f"({_check_names(required_red)}); tools/cc/ship.py status tells a test red "
                    f"(fix, push, re-bind) from a lost runner (rerun)")
        elif running:
            tail = f"auto-merge armed; waiting on {running} running"
        elif red and required_red is None:
            tail = (f"auto-merge armed but held ({merge_state.lower()}); could not "
                    f"read which reds are required: gh pr checks {pr['number']} --required")
        elif red:
            # The read answered: none of the reds is required, so the hold is a
            # review requirement or a required check that has not reported --
            # the command already answered, do not send the operator back to it.
            tail = (f"auto-merge armed but GitHub is holding it ({merge_state.lower()}): no red "
                    f"is required, so a review or a required check that has not reported")
        else:
            tail = (f"auto-merge armed but GitHub is holding it ({merge_state.lower()}): "
                    f"gh pr checks {pr['number']} --required says which")
    elif red:
        # A red on a row GitHub does not report as blocked holds the merge
        # only when its check is required, and the listing carries no
        # is-required flag: a pull request has merged with three advisory
        # legs red while this tail said "held by the red". Name the command
        # that says which reds are required instead.
        tail = (f"auto-merge armed; it merges unless a red check is required "
                f"(gh pr checks {pr['number']} --required says which)")
    else:
        tail = f"auto-merge armed: it merges on its own, so pull {base} after"
    return f"{lead} {checks}; {tail}"


def _open_prs_line(
    listing: str | None = None,
    root: Path | None = None,
    deadline: float | None = None,
    required_reader: Callable[[int], list[str] | None] | None = None,
) -> str:
    """The banner's `Open PRs:` value -- one open pull request per line, the
    first on the label's line and the rest aligned under it -- or '' when the
    caller has none open. ``listing`` is for tests; production reads `gh` in
    main and passes the text with ``root`` and the block's ``deadline``, which
    bound the one extra read a row with a red earns (`gh pr checks --required`,
    ``_gh_pr_required_reds``); ``required_reader`` is that read, injectable so
    the tests count it."""
    if listing is None:
        listing = _read_open_prs(root if root is not None else Path.cwd(), deadline)
    if required_reader is None and root is not None:
        base = root

        def required_reader(number: int) -> list[str] | None:
            return _gh_pr_required_reds(base, number, deadline)
    prs = [pr for pr in _prs(listing) if _pr_state(pr) == "OPEN"]
    rows = []
    for i, pr in enumerate(prs):
        reds = None
        # The read is spent only on a row the line will render (the rest
        # fold into "and N more") and only while the block can still afford
        # the merged read that follows it: three rows with a red must not
        # starve the `Merged:` line, whose silence reads as nothing merged.
        affordable = deadline is None or (deadline - time.monotonic()) > (
            _PR_READ_CAP_SECONDS + _PR_CHECKS_CAP_SECONDS)
        if required_reader is not None and i < _PR_RENDER_ROWS and affordable and _pr_has_red(pr):
            reds = required_reader(int(pr["number"]))
        rows.append(_pr_summary(pr, reds))
    return _render_rows(rows)


def _local_has_commit(
    root: Path, base: str, oid: str,
    deadline: float | None = None,
    local_branches: dict[str, bool] | None = None,
) -> bool | None:
    """Does the LOCAL branch ``base`` reach commit ``oid``? True when it does,
    False when the branch exists here and does not (the merge is not pulled
    yet, or was never fetched), None when the branch is not local, git could
    not answer, or the block's budget is spent -- a None costs the row, never
    the banner. ``local_branches`` caches the branch-exists question per base
    across one banner, so five merges into `main` cost one `rev-parse`."""
    if not base or not oid or not all(c in "0123456789abcdefABCDEF" for c in oid):
        return None
    if local_branches is not None and base in local_branches:
        known = local_branches[base]
    else:
        timeout = _seconds_left(deadline, _PR_GIT_CAP_SECONDS)
        if timeout <= 0.2:
            return None
        try:
            have = subprocess.run(  # spawn: ok a reporter: a git that cannot answer decides nothing about the Merged: line
                ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{base}"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout, cwd=str(root),
            )
        except (OSError, subprocess.SubprocessError):  # fail-open: ok deliberate -- a git that cannot answer decides nothing; the Merged: line is not drawn
            return None
        known = have.returncode == 0
        if local_branches is not None:
            local_branches[base] = known
    if not known:
        return None
    timeout = _seconds_left(deadline, _PR_GIT_CAP_SECONDS)
    if timeout <= 0.2:
        return None
    try:
        reach = subprocess.run(  # spawn: ok a reporter: a git that cannot answer decides nothing about the Merged: line
            ["git", "merge-base", "--is-ancestor", oid, f"refs/heads/{base}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, cwd=str(root),
        )
    except (OSError, subprocess.SubprocessError):  # fail-open: ok deliberate -- a git that cannot answer decides nothing; the Merged: line is not drawn
        return None
    # 0: reachable. 1: not reachable. 128: the commit is unknown here -- never
    # fetched -- which for this question is the same answer as 1.
    return reach.returncode == 0


def _merged_when(stamp: object) -> str:
    """`2026-09-27T23:48:28Z` -> `2026-09-27 23:48Z`; anything else verbatim."""
    s = str(stamp or "")
    if len(s) >= 16 and s[10] == "T":
        return f"{s[:10]} {s[11:16]}Z"
    return s


def _check_names(names: list[str]) -> str:
    """At most three check names, then `...`: the one cap both lines share."""
    return ", ".join(names[:3]) + (", ..." if len(names) > 3 else "")


def _merged_summary(
    pr: dict, *, unpulled: bool, reds: list[str] | None = None, no_verdict: list[str] | None = None,
) -> str:
    """One merged pull request as the banner names it: the pull when the local
    base lacks its merge commit; `red after merge:` naming the checks whose
    latest run is red; `no verdict:` naming those whose latest run was
    cancelled. A row that is both un-pulled and red renders once, both clauses."""
    head = _ascii(str(pr.get("headRefName") or "?"))
    base = _ascii(str(pr.get("baseRefName") or "?"))
    when = _merged_when(pr.get("mergedAt"))
    text = f"#{pr['number']} {head} -- merged into {base}{' ' + when if when else ''}"
    if unpulled:
        text += f", not in your local {base}; pull it: git switch {base} && git pull --ff-only origin {base}"
    if reds:
        text += f"; red after merge: {_check_names(reds)}"
    if no_verdict:
        text += f"; no verdict: {_check_names(no_verdict)}"
    return text


def _post_merge_verdicts(merged: list[dict]) -> dict[int, tuple[list[str], list[str]]]:
    """Per merged pull request, newest merge first: the check names it owns
    whose latest run is red, and those whose latest run reached no verdict. A
    check name is owned by the newest merged pull request whose latest run of
    it reached a VERDICT, green or red: five ledger-only chores that never ran
    `portability` cannot push a red code merge out of view, a later merge whose
    leg ran green supersedes an older red, and a leg still running, cancelled
    or stale on the newer merge supersedes nothing (the red-team drove the
    silent shape: a long leg pending on the newer of two merges nineteen minutes
    apart hid the older one's red). Inside one pull request
    `_latest_run_per_check` keeps one row per name, so a cancelled latest run
    has already displaced that pull request's own older red -- the helper's
    contract, and `no verdict` is the loud substitute."""
    owned: set[str] = set()
    out: dict[int, tuple[list[str], list[str]]] = {}
    for pr in merged:
        rollup = pr.get("statusCheckRollup")
        reds: list[str] = []
        no_verdict: list[str] = []
        for row in _latest_run_per_check(rollup if isinstance(rollup, list) else []):
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or row.get("context") or "")
            if not name or name in owned:
                continue
            outcome = _check_outcome(row)
            if outcome == "running":
                continue  # not a verdict yet: it supersedes nothing
            conclusion = str(row.get("conclusion") or "").upper()
            if conclusion in _NO_VERDICT:
                # Named for this row, and the older verdict of the same name
                # stays in force. (A StatusContext row carries `state`, never
                # one of these, so the split is a no-op for that shape.)
                no_verdict.append(f"{_ascii(name)} ({conclusion.lower()})")
                continue
            owned.add(name)
            if outcome == "red":
                reds.append(_ascii(name))
        if reds or no_verdict:
            out[pr["number"]] = (reds, no_verdict)
    return out


def _merged_prs_line(
    listing: str | None = None,
    root: Path | None = None,
    local_has_commit: Callable[[str, str], bool | None] | None = None,
    deadline: float | None = None,
) -> str:
    """The banner's `Merged:` value -- each recently merged pull request whose
    merge commit the local base branch does not reach, with the pull that
    catches up, and each whose latest run of a check is red (or cancelled with
    no re-run: `no verdict`) -- or '' when everything merged is here and green.
    At most `_MERGED_PR_ROWS` merged rows are read (one `merge-base` each, plus
    one `rev-parse` per distinct base; the rollup rows cost no call, `_PR_FIELDS`
    already fetches them). ``listing`` and ``local_has_commit`` are for tests;
    production reads `gh` in main under the block's deadline."""
    root = root if root is not None else Path.cwd()
    if listing is None:
        listing = _read_merged_prs(root, deadline)
    branches: dict[str, bool] = {}
    has = local_has_commit or (
        lambda base, oid: _local_has_commit(root, base, oid, deadline, branches)
    )
    # `gh pr list` orders by creation; ownership and the render order follow
    # the MERGE order, newest first, so a lane opened first and merged last
    # owns the checks it ran (its run is the current state of the base).
    merged = sorted(
        (pr for pr in _prs(listing) if _pr_state(pr) == "MERGED"),
        key=lambda pr: str(pr.get("mergedAt") or ""), reverse=True,
    )[:_MERGED_PR_ROWS]
    verdicts = _post_merge_verdicts(merged)
    rows: list[str] = []
    for pr in merged:
        mc = pr.get("mergeCommit")
        oid = str(mc.get("oid") or "") if isinstance(mc, dict) else ""
        base = str(pr.get("baseRefName") or "")
        unpulled = bool(oid and base) and has(base, oid) is False
        reds, no_verdict = verdicts.get(pr["number"], ([], []))
        if unpulled or reds or no_verdict:
            rows.append(_merged_summary(pr, unpulled=unpulled, reds=reds, no_verdict=no_verdict))
    return _render_rows(rows)

def _summarize_memory(root: Path) -> str:
    """Read ESPALIER_MEMORY.md and produce a compact summary.

    Skips Markdown headings (#) AND multi-line HTML comments (<!-- ... -->) so the
    leading self-hosted-memory-log comment does not bury the **Repo:**/**Stack:**
    identity. The comment spans several lines, so track in-comment STATE rather
    than matching a single `<!--` line (a continuation line does not start with it).
    """
    memory_path = root / _MEMORY_FILENAME
    text = _safe_read(memory_path)
    if not text.strip():
        return "No ESPALIER_MEMORY.md found"

    # A half-merged file -- a hand merge through Bash, which no write-tool
    # hook sees, then `git add -A` (driven 2026-10-05) -- would otherwise
    # digest its marker lines as the first survivors: they are neither
    # headings, rows, comments nor template lines. Skip them, and name the
    # finding where the garbage would have been read; the merge gate refuses
    # the same lines at the pull request.
    marker_at = {lineno for lineno, _head in _hook_utils.conflict_marker_lines(text)}

    lines = []
    in_comment = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if lineno in marker_at:
            continue
        stripped = line.strip()
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:  # multi-line opens here; single-line closes here
                in_comment = True
            continue
        # Skip markdown table structure (separator rows and empty skeleton
        # header rows) so the init-deployed empty ESPALIER_MEMORY.md tables don't leak
        # raw `|---|` pipes into a fresh adopter's first SessionStart digest.
        if stripped.startswith("|"):
            continue
        if stripped and not stripped.startswith("#"):
            if " ".join(stripped.split()) in _MEMORY_TEMPLATE_LINES:
                continue
            lines.append(stripped)
        if len(lines) >= 10:
            break
    digest = " | ".join(lines[:5]) if lines else "ESPALIER_MEMORY.md is empty"
    if marker_at:
        where = ", ".join(str(n) for n in sorted(marker_at))
        return (f"MERGE-CONFLICT MARKER at line {where} of {_MEMORY_FILENAME} -- a "
                f"half-merged record; resolve the hunk and write the file whole | {digest}")
    return digest


# MEMORY Session-Log digest. N is how many recent rows to show; each row renders
# as an HONEST headline (the date + the bold lead, word-boundary capped) -- NOT a
# mid-word byte slice of a multi-kilobyte row masquerading as the whole row.
_MEMORY_DIGEST_ROWS = 3
_MEMORY_HEADLINE_BYTES = 140  # word-boundary cap per headline (never mid-word)
# A Session Log row begins `| YYYY-MM-DD ...`; the date is both the row marker and
# the chronological order key. (Harness-decision-table dates sit in column 2, so
# this first-column anchor does not false-match them.)
_MEMORY_DATE_RE = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})")
# Init-deployed ESPALIER_MEMORY.md template boilerplate (cli.py::_build_memory_md).
# A fresh adopter's file is ONLY the template, so without this filter the SessionStart
# "Memory:" digest renders scaffolding prose instead of the **Repo:**/**Stack:** identity.
# Keep in sync with _build_memory_md if that template's prose changes -- the drift
# pin in tests/test_hooks.py feeds the real template through this filter.
# WHOLE LINES, not line-opening phrases. Until 2026-09-12 this held four prefixes
# behind a startswith(), so an adopter who rewrote the pruning policy
# ("**Pruning policy:** keep 12 rows; older go to docs/archive.md") or opened a
# sentence of their own with "For long-form entries that don't fit" lost that
# line from every digest: their prose, filtered as scaffolding (DEF-382a). A line
# is boilerplate only when it IS a template line, whitespace-collapsed so an
# editor re-spacing the paragraph does not un-filter it.
_MEMORY_TEMPLATE_LINES: frozenset[str] = frozenset(
    " ".join(line.split()) for line in (
        "**Pruning policy:** Keep the 5 most recent entries; keep this file short.",
        "For long-form entries that don't fit in the index above, see",
        "[`memory/`](memory/).  `espalier init .` creates an empty `memory/`",
        "folder with a README explaining the convention.",
    )
)


def _memory_headline(row: str) -> str:
    """Extract an honest one-line headline from a MEMORY Session-Log row.

    A row is ``| YYYY-MM-DD **bold lead ...** | ...long body... |``. We take the
    date + the bold lead (or the first cell when there is no bold lead), then cap
    it on a WORD boundary via _truncate_on_boundary -- so the digest is a true
    headline pointer, never a half-word byte-clip pretending to be the full row.
    """
    m = _MEMORY_DATE_RE.match(row)
    date = m.group(1) if m else ""
    rest = (row[m.end():] if m else row).strip().lstrip("|").strip()
    if rest.startswith("**"):
        close = rest.find("**", 2)
        headline = rest[2:close] if close != -1 else rest[2:]
    else:
        headline = rest.split("|", 1)[0]
    headline = headline.strip().strip("*").strip()
    capped = _truncate_on_boundary(headline, _MEMORY_HEADLINE_BYTES, " ...")
    return f"- {date} {capped}".rstrip()


def _memory_toc(root: Path) -> str:
    """Render the newest-N ESPALIER_MEMORY.md Session Log rows as honest headlines,
    newest-first, with a self-describing label + a pull pointer.

    Returns '' when ESPALIER_MEMORY.md is absent or has no dated Session Log rows (adopter
    template, fresh clone, post-archive empty log) so the section is omitted.
    UNGATED at the call site -- that emptiness check IS the gate. `init` deploys
    ESPALIER_MEMORY.md with a Session Log, so an adopter's own /handoff rows are
    their own recency; the digest is not harness-internal.
    """
    text = _safe_read(root / _MEMORY_FILENAME)
    if not text.strip():
        return ""
    # Pair each row with the date it carries AT THE FILTER. The sort below
    # needs that date, and re-matching there would reopen a question this
    # line has already answered -- leaving a miss that cannot happen but
    # still has to be spelled, as either a silent default (sorts a real row
    # to the bottom) or a raise inside a sort key -- which the next comment
    # block rules out, for a hook whose contract is to report and never block.
    # One pass, one answer, no third branch.
    dated = [
        (match.group(1), ln)
        for ln in text.splitlines()
        if (match := _MEMORY_DATE_RE.match(ln))
    ]
    if not dated:
        return ""
    # Newest by the date each row CARRIES -- never by its position in the file.
    #
    # The previous spelling was `rows[-N:][::-1]`, commented "last N in file
    # order = newest". The Session Log is hand-maintained: `/handoff` prepends in
    # practice while `handoff.md` said "append" for months, and one row followed
    # the doc. So file order is a convention that has ALREADY drifted, and
    # reading it as recency shipped the three OLDEST rows under the heading
    # "recent sessions" for ~10 days. `espalier/cli.py::cmd_memory_prune` closed
    # this same class on this same artifact five weeks before this function was
    # written; this is the sibling that fix did not reach.
    #
    # The key is the date STRING and nothing else, both parts deliberate:
    #   * NOT a `(date, index)` tuple, though the cli sibling's shape invites it
    #     -- `reverse=True` reverses the index too, so equal dates come back
    #     oldest-line-first. A plain sort is stable, so equal dates keep file
    #     order, which under prepend means the topmost is the newest.
    #   * NOT a real date parse -- `| 2026-13-45 |` satisfies the regex, and
    #     `date()`/`strptime` would raise INSIDE the sort key and traceback a
    #     hook whose whole contract is to report and never block. Lexicographic
    #     order on a zero-padded `YYYY-MM-DD` is already chronological.
    #
    # Cost of the change, named in full: recency authority moves from position
    # (mechanically unforgeable) to a hand-typed cell. A future-dated typo does
    # not merely take a digest slot -- it sorts date-max forever, so
    # `espalier memory prune` never selects it either and the row becomes
    # UN-ARCHIVABLE, permanently costing autoprune one slot of cap relief.
    # Do NOT clamp with `date.today()` inside this key: wall-clock-dependent
    # output in a reporter hook is its own defect. DETECTING it is free and has
    # no such property -- `tests/test_hooks.py::test_no_session_log_row_is_future_dated`.
    #
    # Scope, and it widened here: this scans EVERY dated row in the file, while
    # the `cmd_memory_prune` sibling scopes to `## Session Log`. Under the old
    # tail-slice only rows BELOW the log could contaminate; under date-ranking a
    # dated row anywhere wins outright. Not reachable on this tree today (all 38
    # dated rows are inside the log; the other tables key on labels), but the
    # shipped adopter template emits a `| Decision | Date | Reason |` table, and
    # an adopter putting the date first would hand it the top slot.
    newest = sorted(dated, key=lambda pair: pair[0], reverse=True)
    out = [_memory_headline(ln) for _, ln in newest[:_MEMORY_DIGEST_ROWS]]
    return (
        "\n--- MEMORY (recent sessions -- headlines only; read ESPALIER_MEMORY.md for full rows) ---\n"
        + "\n".join(out)
        + "\n(Pull ESPALIER_MEMORY.md or /recall <topic> for the full reasoning behind any row.)\n"
    )


def _footgun_pointer(root: Path) -> str:
    """A one-line pointer to the footgun/failure-mode catalogs in place of the
    old full SHARP_EDGES TOC.

    The TOC was ~53% of the banner and redundant: a pull beats a 100-heading
    wall (whose [recent:] signal was noise -- it marked ~82% of headings), and
    the folder-CLAUDE.md ladder surface-triggers the relevant footguns on entry.

    UNGATED at the call sites -- the content checks below ARE the gate. Returns
    '' when neither catalog carries real content (a bare tree, or one whose
    seeded scaffold nobody has filled in) so the line is omitted rather than
    pointing at an empty file.

    The retrieval clause is built per catalog, because NAMING a catalog and
    being able to PULL it are different facts: ``_recall`` indexes SHARP_EDGES
    sections on every tree but the FAILURE_MODES shards only where
    ``_recall.indexes_failure_modes`` says so. Asking that owner -- rather than
    restating its rule here -- is what stops this line promising ``/recall`` for
    a doc the corpus has never indexed. And when that owner could not be
    imported at all, the clause says nothing about ``/recall`` either way: an
    unconsulted corpus is not evidence of non-indexing (DEF-563).
    """
    has_sharp = _hook_utils.has_real_sections(root / "docs" / "SHARP_EDGES.md")
    has_fm = _hook_utils.has_real_sections(root / "docs" / "FAILURE_MODES.md")
    if not (has_sharp or has_fm):
        return ""
    # Annotated, not inferred. `catalogs` and `pullable` take literal appends
    # that mypy can infer from; `direct` is only ever reached through the
    # conditional `(pullable if reachable else direct).append(...)` below, which
    # mypy cannot attribute to either branch -- so it needs the type stated.
    catalogs: list[str] = []
    pullable: list[str] = []
    direct: list[str] = []
    if has_sharp:
        catalogs.append("docs/SHARP_EDGES.md (concrete footguns)")
        pullable.append("docs/SHARP_EDGES.md")
    if has_fm:
        catalogs.append("docs/FAILURE_MODES.md (failure classes)")
        reachable = _recall is not None and _recall.indexes_failure_modes(root)
        (pullable if reachable else direct).append("docs/FAILURE_MODES.md")
    if _recall is None:
        # The retriever failed to import in THIS process, so whether /recall can
        # pull either catalog is a fact this banner cannot check. Name the
        # catalogs and point at their tables of contents; say nothing about
        # /recall in either direction. "does not index it on this tree" was a
        # specific false fact here (DEF-563) -- the corpus was never consulted --
        # and "retrieve with /recall" would be a promise from a process that
        # just watched the retriever fail to load.
        named = pullable + direct
        where = "its table of contents" if len(named) == 1 else "their tables of contents"
        how = f"Open {' + '.join(named)} at {where}"
    elif pullable and not direct:
        how = "Retrieve the relevant one with /recall <topic>"
    elif pullable:
        how = (
            f"Pull {' + '.join(pullable)} with /recall <topic>; "
            f"read {' + '.join(direct)} directly"
        )
    else:
        # "at its table of contents", not "read it": the header says don't scan,
        # and the one catalog that lands here is ~300 KB. Sending a reader to
        # open the whole file would contradict the line above it.
        how = (
            f"Open {' + '.join(direct)} at its table of contents -- /recall "
            "does not index it on this tree"
        )
    return (
        "\n--- FOOTGUNS & FAILURE MODES (pull, don't scan) ---\n"
        + " + ".join(catalogs)
        + f"\n{how}; per-surface footguns also fire via the folder CLAUDE.md "
        "ladder on entry.\n"
    )


def _standing_principles_index(root: Path) -> str:
    """Render the TITLES of docs/STANDING_PRINCIPLES.md as a compact always-on
    index -- the few cross-cutting frames worth holding in context, scannable in
    one glance (bodies pulled on demand).

    Unlike the retired 126-heading SHARP wall, this is a compact set of
    always-relevant frames, so the whole index IS the signal. Self-host-gated at
    the call site. Returns '' when the doc is absent (so an adopter or a stripped
    tree omits it).
    """
    text = _safe_read(root / "docs" / "STANDING_PRINCIPLES.md")
    if not text.strip():
        return ""
    # Through the corpus's own splitter, so a fenced ``## `` example in the
    # principles doc is neither a phantom principle here nor a corpus doc there.
    titles = [title for title, _ in _hook_utils.iter_doc_sections(text)]
    if not titles:
        return ""
    return (
        "\n--- STANDING PRINCIPLES (hold these; bodies in docs/STANDING_PRINCIPLES.md) ---\n"
        + "\n".join(f"- {t}" for t in titles)
        + "\n"
    )


def _truncate_on_boundary(text: str, budget_bytes: int, marker: str) -> str:
    """Truncate ``text`` to at most ``budget_bytes``, cutting on a WHITESPACE
    boundary (newline preferred, else space) so a fragment is dropped whole --
    never mid-word. Appends ``marker`` only when truncation actually occurs.

    Honest by construction: the cut lands between tokens, not inside one, so a
    reader never sees a half-word masquerading as content. Returns ``text``
    unchanged when it already fits.
    """
    enc = text.encode("utf-8")
    if len(enc) <= budget_bytes:
        return text
    clipped = enc[: max(0, budget_bytes)].decode("utf-8", errors="ignore")
    # The LATEST whitespace boundary -- not "newline, unless there is none
    # anywhere". A newline-only preference throws the budget away on an
    # unwrapped line: in a "## Heading\n\n<long unwrapped body>" window the last
    # newline is the one ENDING THE HEADING, so the cut lands there and the body
    # never appears. Measured on cc/GOAL.md's own shape -- a 4,183-byte
    # allowance returned 24 bytes, a bare heading. A newline still wins whenever
    # it is the later boundary, which is what test_prefers_newline_boundary pins.
    cut = max(clipped.rfind("\n"), clipped.rfind(" "))
    if cut >= 0:
        # Cut at the boundary (>= 0, so a boundary at index 0 is honored).
        clipped = clipped[:cut]
    elif any(ord(c) > 127 for c in clipped) or "/" in clipped or ":" in clipped:
        # No whitespace boundary, but the leading run is a space-less SCRIPT
        # (CJK/Thai -- every char is whole) or a URL/token (a prefix is
        # meaningful). Vanishing the whole headline would be worse than an honest
        # "日本語…" / "https://ex…" pointer, so KEEP the head via the mid-char-safe
        # byte cut already in `clipped` (errors="ignore" never splits a UTF-8
        # sequence) + marker -- the same "keep the head, honest …" contract
        # `_hard_cut` uses.
        pass
    else:
        # No whitespace boundary and a pure-ASCII wordish run: a mid-word byte
        # prefix ("antidisestab…") is a misleading half-word, so drop the partial
        # token entirely -- the marker signals the omission. Preserves the
        # never-leak-a-fragment honesty contract for ASCII words.
        clipped = ""
    return clipped.rstrip() + marker


def _split_on_headings(text: str) -> "list[str]":
    """Split ``text`` before each top-level ``## `` heading, FENCE-AWARE.

    Returns ``[preamble, section, ...]``; the preamble is ``""`` when the text
    opens on a heading.

    A ``## `` inside a fenced block is prose ABOUT a heading, not one. The fence
    grammar is ``_hook_utils.next_fence_state`` -- the same one
    ``_hook_utils.iter_doc_sections`` (the recall corpus and the catalog check),
    ``post_write_check.py::_memory_section_lines`` and ``_recall``'s alias loader
    read through, so the ``## `` readers in this tree cannot disagree about
    what a fence is. This site used to flip on any line starting with three
    backticks, which a tilde fence or a longer closing run does not satisfy. The
    alias loader carries the measured incident: a fence containing ``## 2.``
    produced a phantom section AND stole the following genuine bullet from the
    block above it. Silent misattribution, not attrition.
    """
    parts: "list[str]" = []
    current: "list[str]" = []
    fence: "str | None" = None
    for line in text.splitlines(keepends=True):
        fenced = fence is not None
        fence = _hook_utils.next_fence_state(line, fence)
        if line.startswith("## ") and not fenced:
            parts.append("".join(current))
            current = []
        current.append(line)
    parts.append("".join(current))
    return parts


def _truncate_keeping_tail(text: str, budget_bytes: int, marker: str) -> str:
    """Bound ``text`` by dropping from the HEAD, keeping the preamble and as many
    WHOLE trailing ``## `` sections as fit, then admitting the next one partially.

    The mirror of :func:`_truncate_on_boundary`, for a section whose valuable
    content sits at the END. ``cc/GOAL.md`` is written newest-perishable-first:
    the handoff Notes block is the bulk and heads the file, and the goal-proper
    trails it -- so a head-keeping cut delivers precisely the part that does not
    matter. Sizing a hard cap above the file only DEFERS that (the file grows; it
    outgrew a 4,500B cap at 6,785B and shipped 0 bytes of goal-proper), which is
    why the fix here is directional rather than numeric.

    The perishable head yields GRADUALLY. Dropping it wholesale would merely
    INVERT the defect, and the first cut of this function did exactly that until
    it was driven.

    Two failure modes were measured on the first cut and are guarded by name
    below, because both shipped green:

    * a partial section can come back as a BARE HEADING -- ``_truncate_on_boundary``
      cuts to the last newline in its window, so a body with no newline inside the
      window leaves only the heading's own. A 4,183-byte allowance returned 24
      bytes. The gate is therefore on DELIVERED bytes, never the allowance.
    * the last-resort branch must head-keep the FINAL SECTION, not the whole
      document -- the latter restores this function's own defect (perishable head
      survives, goal-proper does not), which is what it did when first written.
    """
    if len(text.encode("utf-8")) <= budget_bytes:
        return text
    parts = _split_on_headings(text)
    if len(parts) < 2:
        # No tail to protect. Say so distinctly: an undifferentiated marker
        # cannot be told from a working tail-keep, and this contract's source
        # file is gitignored, so a silent revert would stay silent.
        return _truncate_on_boundary(
            text,
            budget_bytes,
            marker.replace("trimmed to fit", "trimmed from the TOP (no ## section to keep)"),
        )
    preamble, sections = parts[0], parts[1:]
    marker_bytes = len(marker.encode("utf-8"))
    reserved = len(preamble.encode("utf-8")) + marker_bytes + 1
    kept: "list[str]" = []
    used = 0
    partial = ""
    for section in reversed(sections):
        size = len(section.encode("utf-8"))
        if reserved + used + size > budget_bytes:
            remaining = budget_bytes - reserved - used - _SECTION_JOIN_BYTES
            if remaining >= _MIN_PARTIAL_SECTION_BYTES:
                candidate = _truncate_on_boundary(section, remaining, marker)
                delivered = len(candidate.encode("utf-8")) - marker_bytes
                if delivered >= _MIN_PARTIAL_SECTION_BYTES:
                    partial = candidate
            break
        kept.append(section)
        used += size
    if not kept:
        return _truncate_on_boundary(preamble + sections[-1], budget_bytes, marker)
    kept.reverse()
    body = "".join(kept).rstrip()
    if partial:
        return preamble.rstrip() + "\n\n" + partial.rstrip() + "\n\n" + body
    return preamble.rstrip() + marker + "\n" + body


def _bounded(name: str, text: str, flags: "list[str]", hard_cap: "int | None" = None,
             keep_tail: bool = False) -> str:
    """Bound a banner section to its ``_SOFT_BUDGETS`` share with an HONEST
    boundary truncation, recording a VISIBLE bloat flag in ``flags`` when the
    section ran over so growth is observable rather than silent.

    Sections with no soft budget (or empty text) pass through untouched -- the
    outer ``_MAX_CONTEXT_BYTES`` ceiling still backstops the whole banner. This
    is the "generous + honest + flagged" contract: normal-length content rides
    through whole; only genuine bloat is cut, and the cut announces itself.

    ``hard_cap`` decouples the FLAG threshold (soft) from the CUT threshold:
    set above ``soft``, a section that is over-soft is FLAGGED but rides through
    WHOLE up to ``hard_cap`` (truncated only beyond it). GOAL uses this so the
    goal-proper -- which sits below the perishable Notes head -- is not the part
    that gets cut. Default ``hard_cap == soft`` keeps flag-and-cut together.

    ``keep_tail`` decides WHICH END yields when the cut finally happens. The
    default keeps the head, which is right for a newest-first section (the memory
    digest). GOAL is written newest-PERISHABLE-first, so it passes ``keep_tail``
    and the handoff Notes block yields before the goal-proper. ``hard_cap`` alone
    could not hold that contract -- it holds only while the source stays under the
    number, and cc/GOAL.md outgrew it.
    """
    soft = _SOFT_BUDGETS.get(name)
    if not text or soft is None:
        return text
    size = len(text.encode("utf-8"))
    if size <= soft:
        return text
    src = _SECTION_SOURCE.get(name, "its source file")
    flags.append(
        f"[banner] {name} section is large ({size} bytes) -- consider trimming {src}"
    )
    cap = soft if hard_cap is None else hard_cap
    if size <= cap:
        return text  # over soft (flagged) but within hard_cap -- ride through whole
    cut = _truncate_keeping_tail if keep_tail else _truncate_on_boundary
    return cut(
        text, cap, f"\n[{name} section trimmed to fit -- see {src} for the full text]"
    )


_BLUEPRINT_ENTRY_RE = re.compile(r"^\[\d+\] ")


def _hard_cut(text: str, budget: int, marker: str) -> str:
    """Last-resort BYTE cut to ``budget`` + ``marker``, keeping the HEAD. A runaway
    entry (a pasted log with no whitespace boundary) is cut mid-token rather than
    lost WHOLE -- an honest '...[cut]' beats vanishing the newest reasoning. Used
    only on the single-entry-over-budget anomaly path the write-time advisory
    targets; the head is kept so a section is never emitted empty."""
    enc = text.encode("utf-8")
    if len(enc) <= budget:
        return text
    room = max(0, budget - len(marker.encode("utf-8")))
    return enc[:room].decode("utf-8", errors="ignore") + marker


# Marker for the single-runaway-entry fallback -- names what actually happened
# (the NEWEST entry was truncated), distinct from the multi-entry "older dropped".
_NEWEST_ENTRY_MARKER = "\n[newest entry truncated to budget -- pull cc/blueprints/latest.json]"


def _drop_whole_entries(text: str, budget: int, entry_re: "re.Pattern[str]", marker: str) -> str:
    """Bound ``text`` to ``budget`` by dropping WHOLE trailing entries -- never
    slicing one mid-thought (the "rewrite, don't cut" contract; the per-entry
    anomaly cap lives at the writer). ``entry_re`` matches a line that STARTS an
    entry; the run from one start to the next (or EOF) is one entry. Content
    before the first entry (a header) is the prefix, always kept. When even
    prefix+the NEWEST entry is over budget (a single runaway), the newest entry is
    byte-cut to budget (head kept) -- never lost whole -- and the marker says so."""
    if len(text.encode("utf-8")) <= budget:
        return text
    lines = text.split("\n")
    starts = [i for i, ln in enumerate(lines) if entry_re.match(ln)]
    if not starts:
        return _hard_cut(text, budget, marker)
    prefix = lines[: starts[0]]
    mbytes = len(marker.encode("utf-8"))
    kept = prefix
    for k, s in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        candidate = kept + lines[s:end]
        if len("\n".join(candidate).encode("utf-8")) + mbytes > budget:
            break
        kept = candidate
    if kept != prefix:
        return "\n".join(kept) + marker
    # Not even the NEWEST (first) entry fits with the header: keep header + that
    # entry, byte-cut to budget -- don't lose the newest entry's substance.
    first_end = starts[1] if len(starts) > 1 else len(lines)
    newest = "\n".join(prefix + lines[starts[0]:first_end])
    return _hard_cut(newest, budget, _NEWEST_ENTRY_MARKER)


def _bound_blueprint_context(text: str) -> str:
    """Bound the injected cross-session blueprint slice to its budget share by
    dropping WHOLE trailing lines -- never slicing an entry mid-thought (cmd_load
    renders each entry on one line with Next steps ABOVE the decisions, so the
    drop sheds the OLDEST decisions first and keeps the curated handoff). The
    NEWEST decision is NEVER dropped: if header+newest alone is over budget (a
    runaway), it is byte-cut (head kept) so the section is never emitted empty.
    The outer _MAX_CONTEXT_BYTES backstops the whole banner."""
    budget = _SOFT_BUDGETS["blueprint"]
    marker = "\n[blueprint context truncated]"
    if len(text.encode("utf-8")) <= budget:
        return text
    lines = text.split("\n")
    mbytes = len(marker.encode("utf-8"))
    # Floor: never drop below the header + the NEWEST decision (the first "- " line
    # after the reordered "## Recent reasoning"), so the section is never emptied.
    floor = 1
    for i, ln in enumerate(lines):
        if ln.startswith("## Recent reasoning"):
            nd = next((j for j in range(i + 1, len(lines)) if lines[j].startswith("- ")), None)
            if nd is not None:
                floor = nd + 1
            break
    while len(lines) > floor and len("\n".join(lines).encode("utf-8")) + mbytes > budget:
        lines.pop()
    kept = "\n".join(lines)
    if len(kept.encode("utf-8")) + mbytes <= budget:
        return kept + marker
    # Header + newest decision still over budget -> byte-cut (keep head + handoff).
    return _hard_cut(kept, budget, _NEWEST_ENTRY_MARKER)


def _load_blueprint(root: Path, advance_chain: bool) -> str:
    """Load the prior session's reasoning for injection and, on a new-session
    source, advance the blueprint chain.

    ``advance_chain`` True (source ``startup``/``clear``): start a fresh
    blueprint node — even when a prior node exists — so this session's
    reasoning accumulates in its own container chained from the prior. The
    prior node's reasoning is captured BEFORE the start (so the injection
    reflects the prior session, not the new empty node) and returned for
    injection.

    ``advance_chain`` False (source ``resume``/``compact``/unknown): load
    read-only and continue the existing session — EXCEPT when no blueprint
    FILE exists at all, in which case a node is bootstrapped (the
    pre-source-aware "create if missing" safety net). ``compact`` fires
    mid-session on every compaction; keying the bootstrap on the file's
    PRESENCE (not on whether `load` returned text) means a continuation source
    can never clobber a present-but-unreadable ``latest.json`` — it reads
    read-only and only seeds a node when the file is truly absent.
    """
    blueprint_script = root / "tools" / "cc" / "cognitive_blueprint.py"
    if not blueprint_script.exists():
        return "No blueprint system"

    # env= pins CLAUDE_PROJECT_DIR to root: cognitive_blueprint._repo_root()
    # prefers the env var over cwd, so an inherited value would silently
    # route reads/writes to the wrong repo. See docs/SHARP_EDGES.md
    # "Subprocesses Inheriting CLAUDE_PROJECT_DIR".
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    try:
        result = subprocess.run(  # spawn: ok a reporter: a blueprint load that cannot be spawned is warned at its handler
            [sys.executable, str(blueprint_script), "load"],
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=10,
            cwd=str(root),
            env=env,
        )
        # The prior session's reasoning (Next steps + continuation fragments +
        # recent decisions, formatted by cognitive_blueprint.cmd_load) so the
        # next session re-engages instead of re-deriving. Captured BEFORE any
        # `start` below so it reflects the PRIOR node. Bounded to the
        # blueprint's share; the outer _MAX_CONTEXT_BYTES backstops the block.
        prior_ctx = ""
        if result.returncode == 0 and result.stdout.strip():
            prior_ctx = _bound_blueprint_context(result.stdout.strip())

        # Start a fresh node when EITHER the source is a new logical session
        # (startup/clear — advance even when a prior exists, chaining the new
        # node from it: parent_session_id + accumulated_depth + 1) OR no
        # blueprint FILE exists at all (bootstrap). Keying on file presence
        # (not on prior_ctx emptiness) preserves the pre-source-aware "create
        # if missing" net for resume/compact/unknown WITHOUT clobbering a
        # present-but-unreadable latest.json mid-compaction: such a file reads
        # as empty `load` output but IS present, so a continuation source falls
        # through to the read-only return below.
        if advance_chain or not _blueprint_present(root):
            start_result = subprocess.run(  # spawn: ok a reporter: a blueprint start that cannot be spawned is warned at its handler
                [sys.executable, str(blueprint_script), "start"],
                capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                timeout=10,
                cwd=str(root),
                env=env,
            )
            if prior_ctx:
                # Inject the prior session's reasoning; the chain has advanced.
                return prior_ctx
            if start_result.returncode == 0:
                return "Auto-started new blueprint session"
            return "No active blueprint (auto-start failed)"

        # Continuation source (resume/compact) with a present blueprint: load
        # read-only and continue. ``prior_ctx`` is empty when the present file
        # is unreadable (symlink/oversize/corrupt) — surface that as a state
        # string rather than a blank line, and do NOT clobber the file.
        return prior_ctx or "No active blueprint"
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        warn_exc("session_start: blueprint load failed", e)
        return "Blueprint load failed"


def _clean_state_flags(root: Path, source: str = "") -> None:
    """Write the session-start timestamp; on a NEW logical session
    (startup/clear) also clear the previous session's stop-gate, speedbump, and
    reinject flags.

    On a CONTINUATION source (``compact``/``resume``) the per-session counters
    are PRESERVED. A mid-session context compaction re-fires SessionStart with
    source==compact; clearing write_count / tool_call_count / speedbump_* /
    reinject_count / post_compact_pending there would rewind stop_gate Gate 2
    (docs, write_count>=10) + Gate 3 (review) thresholds and re-arm
    already-shown speedbumps mid-session. Only ``compact``/``resume`` are
    continuations; startup, clear, and an unlabeled/unknown payload all clear, so
    a genuinely fresh session never inherits stale gate state.
    """
    state_dir = root / _hook_utils.STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)

    # Write session start timestamp (atomic — consistent with the project's
    # atomic-write convention; SIGINT mid-write doesn't leave a half-written
    # flag behind).
    atomic_write_text(
        state_dir / "session_started",
        datetime.now(timezone.utc).isoformat(),
    )

    # A mid-session compact/resume must NOT rewind the stop-gate/speedbump/reinject
    # counters; every other source clears them for a clean fresh session.
    if source in _CONTINUATION_SOURCES:
        return

    # Clean flags from previous session. reflect_trigger_warned is included so
    # the one-shot missing-script WARN re-fires each session rather than going
    # silent after the first session. tool_call_count + last_tool are
    # per-session siblings of write_count, so they clear here too;
    # session_length_recorded is the once-per-session guard for the
    # rolling-baseline append. NOTE: session_length_baseline AND
    # born_weak_observations.jsonl are deliberately ABSENT — both are
    # cross-session rolling history and must persist (clearing them would
    # defeat the base-rates they carry). post_compact_pending is the CP-COMPACT
    # producer flag dropped by post_compact.py; it is a single named flag (not a
    # speedbump_* glob member), so it clears here. Clearing it means a fresh
    # session does not start inside a stale post-compaction window.
    for flag in [
        # The stop_gate relief records subagent_stop writes (docs_refreshed,
        # code_reviewed) -- read from the shared table, never retyped.
        *_hook_utils.RELIEF_FLAGS.values(),
        # Legacy name of the review flag: stop_gate wrote it itself before
        # DEF-608. Nothing reads it now; swept so an upgraded tree carries no
        # stray file in a directory whose contents are contract-pinned.
        "review_requested",
        "write_count",
        "reflect_trigger_warned",
        "tool_call_count",
        "tool_call_count.lock",
        "last_tool",
        "session_length_recorded",
        "post_compact_pending",
        # stop_gate's once-per-session report of a test-gate override that
        # cannot be started (stop_gate.GATE1_SPAWN_FAILURE_REPORTED_FLAG).
        # Left in place it would silence the report in every later session.
        "gate1_spawn_failure_reported",
    ]:
        flag_path = state_dir / flag
        # missing_ok=True (idempotent): a second concurrent SessionStart
        # unlinking the same flag in the exists()->unlink() window must not raise
        # an uncaught FileNotFoundError that exits 1 and suppresses the entire
        # orientation injection. The two glob loops below already swallow
        # OSError; this matches that discipline.
        flag_path.unlink(missing_ok=True)

    # Speed-bump flags are per-(checkpoint[, file, deny-path]) plus the
    # speedbump_count counter and its .lock -- they cannot be enumerated, so glob
    # the speedbump_ prefix. Best-effort: a stale flag only suppresses one extra
    # fire, never a false deny.
    for flag_path in state_dir.glob("speedbump_*"):
        try:
            flag_path.unlink()
        except OSError:
            pass

    # Recall-engine session counter: reinject_count + its .lock bound the
    # per-session non-exempt reinject fires. MANDATORY reset -- without it the
    # SessionStart orientation row burns one slot per session and goes permanently
    # silent after ~REINJECT_SESSION_CAP sessions. Glob the reinject_ prefix
    # (mirrors speedbump_* above; catches the counter + its lock).
    for flag_path in state_dir.glob("reinject_*"):
        try:
            flag_path.unlink()
        except OSError:
            pass

    # The maintenance-bypass audit records' once-per-session guards, one per
    # hook (maintenance_bypass_recorded_<hook>, DEF-789; the prefix is
    # _integrity.MAINTENANCE_BYPASS_FLAG_PREFIX): glob the family like the
    # speed-bump flags, so a hook that starts recording needs no entry here.
    for flag_path in state_dir.glob("maintenance_bypass_recorded_*"):
        try:
            flag_path.unlink()
        except OSError:
            pass

    # The once-a-session voice's flags (`once_<key>`, _hook_utils.say_once): a
    # fail-open that spoke this session speaks again next session. Glob the
    # family, so a new key needs no entry here -- a flag left off this cleaner
    # turns "once a session" into "once ever".
    for flag_path in state_dir.glob(_hook_utils.ONCE_FLAG_PREFIX + "*"):
        try:
            flag_path.unlink()
        except OSError:
            pass


def _report_freshness(root: Path) -> None:
    """Stderr banner when the per-install state cache shows
    critical>0 OR stale>=3. Silent when the cache is missing
    or stale (cache-staleness is its own surface)."""
    cache = _read_state_cache_safe(root)
    if cache is None:
        return
    if _is_state_cache_stale(cache, repo_root=root):
        return
    counts = cache.get("counts", {})
    critical = counts.get("critical", 0)
    stale = counts.get("stale", 0)
    if critical == 0 and stale < 3:
        return
    fresh = counts.get("fresh", 0)
    print(
        f"[freshness] {fresh} fresh / {stale} stale / {critical} critical "
        f"-- run `espalier freshness check`",
        file=sys.stderr,
    )


def _report_integrity_state(root: Path) -> str:
    """Audit + warn on kill-switch and drift findings; return the banner summary.

    SessionStart cannot block Claude Code execution. This function records
    findings and surfaces ASCII warnings to stderr for visibility. Blocking
    enforcement lives in PreToolUse (write_guard.py), ConfigChange
    (config_guard.py), and CI (ci_guard.py).

    WHY IT ALSO RETURNS A STRING. The warnings below go to STDERR, and the
    injected session context is a separate channel (the ``additionalContext``
    JSON on stdout). Nothing threaded one into the other, so a session whose
    only view of the repo is the banner was never told about drift: a live
    6-file drift once sat behind a banner reading ``Surface: healthy`` for a
    whole session, and was found only because an unrelated command happened to
    run the check explicitly. The caller passes this return value to
    ``_build_context``.

    Computed ONCE, here, rather than recomputed in the banner: two independent
    verifications of tamper state could report different things in the same
    session, and two contradictory answers about whether the harness has been
    tampered with is a worse failure than the one this fixes.
    """
    # Reporter, not a blocker: SessionStart cannot deny per the hook protocol,
    # so surfacing an unparseable settings file here costs nothing and is the
    # earliest place the operator can see that the kill-switch scan could not
    # actually run.
    findings = _integrity.scan_for_kill_switches(root, include_unreadable=True)
    if findings:
        _integrity.append_audit(
            root,
            {"event_type": "session_kill_switch_detected",
             "details": {"findings": findings}},
        )
        msg = "\n  ".join(findings)
        print(
            f"[WARN] Espalier-Harness detected "
            f"{_hook_utils.plural(len(findings), 'kill-switch setting')} during "
            "SessionStart. SessionStart cannot block Claude Code execution. "
            "If hooks are still active, PreToolUse/ConfigChange guards will "
            "deny unsafe actions; tracked protected changes are enforced by "
            f"CI.\n  Findings:\n  {msg}",
            file=sys.stderr,
        )

    try:
        ok, mismatched = _integrity.verify_integrity(root)
    except Exception as e:  # noqa: BLE001 — bounded warn, do not crash session
        warn_exc("session_start: integrity verify failed", e)
        # The banner must not claim "ok" for a check that did not complete —
        # a silent pass here would be the blind-detector this whole function
        # exists to prevent, wearing a green label.
        return "unverified (check failed)"
    # Only an ABSENT manifest is exempt. A present-but-unusable one reports as
    # drift (MANIFEST_UNREADABLE), because tamper-detection being blind is the
    # thing this warning exists to surface.
    if not ok and mismatched != [_integrity.MANIFEST_ABSENT]:
        _integrity.append_audit(
            root,
            {"event_type": "session_integrity_drift",
             "details": {"mismatched": mismatched}},
        )
        msg = "\n  ".join(mismatched)
        if _integrity.is_protocol_mismatch(mismatched):
            # Not a changed file: a manifest this deployed copy of _integrity
            # cannot read. The writer is the engine's own copy, so the engine is
            # newer than the hooks; `refresh` would rewrite the same manifest.
            print(
                "[WARN] Espalier-Harness integrity manifest was written by a newer "
                "espalier than the deployed hooks (session continues; SessionStart "
                "cannot block):\n"
                f"  {msg}\n"
                "Run `espalier upgrade --execute` to redeploy the hooks; a refresh "
                "would rewrite the same manifest.",
                file=sys.stderr,
            )
        else:
            print(
                "[WARN] Espalier-Harness integrity drift (session continues; SessionStart "
                "cannot block):\n"
                f"  {msg}\n"
                "Run `espalier integrity refresh .` if this is expected.",
                file=sys.stderr,
            )
    # Banner summary, most severe first. A kill-switch outranks drift: drift means
    # a protected file changed, a kill-switch means the hooks are off entirely.
    if findings:
        return (
            f"KILL-SWITCH ({_hook_utils.plural(len(findings), 'setting')})"
            "  ->  remove it; enforcement is disabled"
        )
    if not ok and mismatched == [_integrity.MANIFEST_ABSENT]:
        # Not a failure: the manifest is gitignored and per-install, so a cloned
        # but un-inited tree legitimately has none. Same exemption the drift
        # warning above applies, and the same call `audit` and `doctor` make.
        return "no manifest (run `espalier init .`)"
    if not ok and _integrity.is_protocol_mismatch(mismatched):
        return "MANIFEST NEWER THAN HOOKS  ->  run `espalier upgrade --execute`"
    if not ok:
        return (
            f"DRIFT ({_hook_utils.plural(len(mismatched), 'file')})"
            "  ->  run `espalier integrity refresh .`"
        )
    return "ok"


# Parallel list to ``espalier.doctor._LOAD_BEARING_EXTERNAL_TOOLS``. Hardcoded
# here (NOT imported from espalier) to preserve the tools/cc/
# zero-espalier-imports invariant. Parity with the doctor side is enforced
# by ``tests/test_external_tool_contract.py``: adding a new tool to
# the doctor registry without adding it here fails the contract.
#
# NOTE: `_warn_if_load_bearing_tool_missing` gates this WHOLE loop on self-host
# (like the doctor twin), so every tool here is treated as self-host-only. A
# tool adopters MUST be warned about (e.g. a secret scanner) needs per-tool
# adopter-relevance gating first — a new row alone is silently suppressed for
# adopters. The parity contract pins membership, NOT gating, so it won't catch it.
_SESSION_START_LOAD_BEARING_TOOLS = (
    # Adopter-correct standalone install (`.[dev]` is espalier's own
    # source-checkout dev-extras, not an adopter's). Names must stay parallel
    # with doctor._LOAD_BEARING_EXTERNAL_TOOLS; only the hint string differs.
    ("ruff", "pip install 'ruff>=0.5,<1.0'"),
)


def _warn_if_load_bearing_tool_missing(self_host: bool) -> None:
    """Surface load-bearing external-tool absence at boot.

    The lint-gate-as-regression-test requires ``ruff`` on PATH.
    A missing binary degrades the gate to non-enforcement silently. The
    SessionStart line makes the gap visible per-session.

    Self-host-gated to match ``espalier.doctor.run_doctor_check``: ruff ships
    only in espalier's own dev-extras and its CI lint gate is ``if: is_source
    == 'true'``, so a ruff-less adopter has no ruff gate and must not be nagged
    at every boot (adopter-friction parity with the doctor side, which gates
    its own load-bearing-tool loop on is_self_host_repo the same way).
    """
    if not self_host:
        return
    import shutil as _shutil
    for tool, hint in _SESSION_START_LOAD_BEARING_TOOLS:
        if _shutil.which(tool) is None:
            print(
                f"[WARN] {tool} not on PATH -- Espalier-Harness's "
                f"lint gate requires {tool}. "
                f"Install via: {hint}",
                file=sys.stderr,
            )


def _warn_if_hook_interpreter_unresolved(root: Path) -> None:
    """Surface a broken settings.json hook interpreter at boot.

    If the interpreter named in a wired hook command (``python`` when the host
    only ships ``python3``, or a stale absolute path after an env change) does
    not resolve, Claude Code runs the hook, it exits 127 with empty stdout, and
    -- per the protocol -- a non-{0,2} exit is non-blocking. Every blocking
    guard then fails OPEN, silently. The other detector is opt-in
    ``espalier doctor``; this makes the gap visible every session.

    REACH (DEF-508): this runs inside a SessionStart hook that STARTED, so it
    can only report an interpreter other than its own -- a hook hand-wired to
    a different name (a partial edit, a teammate's merged file), or a Python 3
    that runs this file but is below the floor (the second branch below). On
    the file ``init`` renders every hook shares one interpreter, so when that
    name stops resolving this warning never runs either. That case is covered
    out-of-band: Claude Code prints its own ``Executable not found in $PATH``
    notice per hook fire, the statusLine ``init`` renders on POSIX hosts falls
    back to a visible line (``cli._statusline_command``), and ``espalier
    doctor`` names the wired interpreter and the rewire command.
    """
    from _hook_utils import (  # noqa: E402
        floor_text,
        interpreter_is_python3,
        interpreter_meets_floor,
        launcher_spelling,
    )
    settings = root / ".claude" / "settings.json"
    if not settings.is_file():
        return  # absence is reported by _check_surface; nothing to resolve
    try:
        # BOM-tolerant. `errors="replace"` does not help here: a UTF-8 BOM
        # survives as \ufeff and a UTF-16 file decodes to mojibake, so both
        # raised JSONDecodeError and took the silent return below -- meaning
        # this warning could never fire for a Windows adopter, every session,
        # which is the population it was written for.
        from _json_safe import decode_bom  # noqa: E402

        data = json.loads(decode_bom(settings.read_bytes()))
    except (json.JSONDecodeError, OSError, ValueError):  # fail-open: ok deliberate -- a malformed settings file is the kill-switch report's to name, not this check's
        return  # malformed/unreadable: not this check's job to report
    if not isinstance(data, dict):
        return
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return
    unresolved: set[str] = set()
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            for entry in group.get("hooks", []) or []:
                if not isinstance(entry, dict):
                    continue
                command = entry.get("command")
                if not isinstance(command, str) or not command.strip():
                    continue
                cmd = command.strip()
                # First token = interpreter. Handle a quoted path with spaces
                # (Windows ``"C:\\Program Files\\...\\python.exe"``) without
                # shlex, which mangles backslashes in posix mode.
                if cmd[:1] in ("'", '"'):
                    end = cmd.find(cmd[0], 1)
                    interp = cmd[1:end] if end > 0 else cmd[1:]
                    rest = cmd[end + 1:].split() if end > 0 else []
                else:
                    interp = cmd.split(None, 1)[0]
                    rest = cmd.split()[1:]
                if not rest and isinstance(entry.get("args"), list):
                    rest = entry["args"]  # exec form: the arguments live in args
                # A bare-PATH command (e.g.
                # `${CLAUDE_PROJECT_DIR}/tools/cc/hooks/x.py`, a canonical CC
                # idiom) is a SCRIPT the OS runs via its shebang, not an
                # interpreter NAME on PATH — `which` always returns None for it,
                # so the resolve check would WARN every session on a config that
                # is perfectly fine (espalier's own exec-form wiring uses
                # command="python3" + args=[path], so it is unaffected). Only a
                # genuine interpreter name is meaningfully resolvable: skip tokens
                # carrying an unexpanded ${...} variable or ending in a script
                # suffix.
                if "${" in interp or interp.endswith((".py", ".sh")):
                    continue
                # IDENTITY, not presence. `which(interp) is None` is False for a
                # stub that resolves, so this check used to pass silently on the
                # exact host it exists for.
                # FLOOR, not identity (DEF-636). A wired 3.9 answers as
                # Python 3, so the identity probe blessed it while every
                # consumer of cognitive_blueprint.py (3.10+ `match`) was
                # dead. The guards keep working, which is why nothing
                # visibly failed and this warning never fired.
                # The launcher WITH its version flag (`py -3`), as doctor and the
                # rewire read it: a bare `py` asks the launcher's default.
                interp = launcher_spelling(interp, rest)
                if interp and not interpreter_meets_floor(interp):
                    unresolved.add(interp)
    for interp in sorted(unresolved):
        # TWO failures share this warning and they need different words.
        # "Not a Python 3 at all" and "a Python 3 below the
        # floor" have different consequences AND different remedies: the first
        # breaks the guards, the second leaves them working while the blueprint
        # chain dies, and a `python3` shim fixes only the first. Saying "does
        # not resolve to a working Python 3" about a working 3.9 sends the
        # operator hunting for a missing install they already have.
        if interpreter_is_python3(interp):
            print(
                f"[WARN] wired hook interpreter `{interp}` IS a Python 3 but is "
                f"older than the {floor_text()} this harness requires -- the "
                "blocking guards keep working, so nothing visibly fails, while "
                "the blueprint chain, Gate 4 finalize and subagent-reasoning "
                "capture raise SyntaxError every session. That is why this "
                "session may say 'No active blueprint' no matter how often you "
                f"hand off. Install Python {floor_text()} or newer and re-wire "
                "the hooks to it. Run `espalier doctor .` for details.",
                file=sys.stderr,
            )
            continue
        print(
            f"[WARN] wired hook interpreter `{interp}` does not resolve to a "
            "working Python 3 on this host -- hooks exit outside the blocking "
            "range and every blocking guard fails OPEN. "
            "Add a `python3` shim, or re-wire the hooks to an interpreter that "
            "resolves. Run `espalier doctor .` for details.",
            file=sys.stderr,
        )


#: The payload's ``cwd`` resolved: one home in _hook_utils since the heartbeat
#: became the second writer of the marker's ``cwd`` (2026-10-05); the private
#: name stays for its readers here and in tests/test_nested_repo_litter.py.
_hook_cwd = _hook_utils.hook_cwd


def _nested_repo_containing(root: Path, cwd: Path | None) -> str | None:
    """Repo-relative path of the nested git repo the session's ``cwd`` sits in,
    or ``None`` when ``cwd`` is in the main checkout or outside the repo.

    Pure filesystem: walks up from ``cwd`` to ``root`` looking for a ``.git``
    entry (dir, gitlink file, or dangling symlink -- the litter descent's own
    predicate), so it needs no git subprocess and cannot be lost to a
    timeout. Identity is by inode (``samefile``), not spelling. Fail-open to
    ``None`` on any OS error. ``cwd=None`` means the process's cwd.
    """
    try:
        root_resolved = root.resolve()
        here = (cwd if cwd is not None else Path.cwd()).resolve()
    except (OSError, ValueError):  # fail-open: ok deliberate -- a cwd that cannot be resolved encloses no nested repo
        return None
    for ancestor in (here, *here.parents):
        try:
            if ancestor.samefile(root_resolved):
                return None  # reached the main checkout: cwd is not in a nested repo
        except (OSError, ValueError):
            pass
        if (ancestor / ".git").exists() or (ancestor / ".git").is_symlink():
            try:
                return str(ancestor.relative_to(root_resolved)).replace("\\", "/")
            except ValueError:  # fail-open: ok deliberate -- a repository outside the project tree is not litter
                return None  # a repo, but outside the project tree
    return None


def _find_nested_repo_litter(
    root: Path, *, cwd: Path | None = None, max_depth: int = 4, max_nodes: int = 5000,
) -> list[str]:
    """Repo-relative paths of nested git repos littering the working tree.

    A nested git repo -- a directory that is (or contains) its own ``.git`` (a
    ``.git`` dir OR a ``.git`` gitlink file) -- is a foreign project (a leftover
    ``git worktree`` or clone) the fs-scanners skip by design; if it lingers it
    still surfaces as phantom scan noise. Two candidate sources are unioned so a
    litter shape invisible to one is caught by the other:

    * ``git worktree list`` -- registered worktrees nested INSIDE the repo,
      found regardless of ``.gitignore`` / ``.git/info/exclude``. This is the
      load-bearing source for the motivating case: ``.claude/worktrees/`` is
      commonly machine-local-excluded (so ``git status`` is blind to it) yet a
      leftover worktree there is still a registered worktree.
    * ``git status --porcelain`` untracked dirs -- a bounded, prune-at-``.git``
      descent catches non-worktree nested clones (e.g. an ``adopt2/`` scratch
      checkout) that ``git worktree list`` does not know about. ``quotepath`` is
      disabled so a non-ASCII dir name is not silently missed.

    Two nested repos are NOT litter, and BOTH sources skip them (the untracked
    descent finds a worktree's gitlink too whenever ``.claude/`` is untracked
    rather than excluded). The ``cc-worktrees`` external pin (espalier's
    pinned excerpt of the Claude Code worktrees page) is the source of truth
    for the rule; the mechanics are here:

    * the nested repo that contains ``cwd`` -- the worktree or scratch clone
      this session is running in. The hook input's ``cwd`` follows Claude into
      a worktree while ``CLAUDE_PROJECT_DIR`` (this ``root``) stays at the
      project root, so a scan rooted here would otherwise name the very tree
      the session is using. ``cwd=None`` means the process's working
      directory; pass ``cwd=root`` to skip nothing (no nested repo contains
      the root).
    * a registered worktree whose ``git worktree list --porcelain`` block
      carries a ``locked`` line (bare, or ``locked <reason>``) -- ANY lock, not
      only Claude Code's. Claude Code holds a ``git worktree lock`` on a
      running agent's or backgrounded session's worktree, and git refuses
      ``worktree remove`` on a locked tree, so the remedy this reporter
      prescribes cannot apply. Claude Code's lock can outlive its session (a
      killed background session, a ``-p`` run) until the stale-lock sweep
      releases it, and a lock you set yourself is never swept: for that
      window, or until you unlock it, the worktree goes unreported rather
      than reported with a remedy that fails. Considered and not taken:
      naming a locked tree with ``git worktree unlock`` as the remedy -- a
      locked tree is, by the lock's meaning, one someone still wants.

    The ``locked`` set comes from the worktree list, so when that command
    fails or times out the lock skip is lost and the untracked descent may
    report a locked worktree (with the remedy git refuses); the ``cwd`` skip
    does not depend on it. That degradation errs toward noise, the right bias
    for a reporter, and is pinned by test.

    Fail-open: any git/OS error yields whatever was found so far (``[]`` if
    nothing) -- a SessionStart reporter must never crash the session. The
    untracked descent is bounded in both depth (``max_depth``) and total visited
    dirs (``max_nodes``) so a large untracked tree cannot slow session start
    unboundedly.
    """
    root_resolved = root.resolve()
    offenders: set[str] = set()
    locked: set[Path] = set()  # filled by source A; read by both sources

    cwd_resolved: Path | None
    try:
        cwd_resolved = (cwd if cwd is not None else Path.cwd()).resolve()
    except (OSError, ValueError):  # fail-open: ok deliberate -- a vanished cwd: nothing to tell apart, report everything
        cwd_resolved = None  # a vanished cwd: nothing to tell apart, report everything

    def _same_dir(a: Path, b: Path) -> bool:
        # Identity by inode, not spelling. ``resolve()`` follows symlinks but
        # does NOT canonicalise case, and a case-insensitive filesystem (APFS,
        # NTFS) spells one directory two ways -- driven 2026-09-09: a lower-case
        # root spelling on macOS lost both skips under a plain ``==``. Errs
        # toward "not the same" on any OS error, which errs toward reporting.
        if a == b:
            return True
        try:
            return a.samefile(b)
        except (OSError, ValueError):  # fail-open: ok deliberate -- two paths that cannot be compared are not the same directory
            return False

    def _in_use(path: Path) -> bool:
        # ``path`` contains the directory the session is working in.
        if cwd_resolved is None:
            return False
        return any(_same_dir(ancestor, path) for ancestor in (cwd_resolved, *cwd_resolved.parents))

    def _is_locked(path: Path) -> bool:
        return any(_same_dir(path, wt) for wt in locked)

    def _rel_to_root(path: Path) -> str | None:
        # Repo-relative spelling of ``path``, found by walking up to the
        # ancestor that IS the root (by inode) -- ``relative_to`` compares
        # spellings and would call a case-variant root "outside the repo".
        for depth, ancestor in enumerate((path, *path.parents)):
            if _same_dir(ancestor, root_resolved):
                if depth == 0:
                    return None  # the root itself
                return "/".join(path.parts[len(path.parts) - depth:])
        return None  # outside the repo tree

    # Source A: registered worktrees nested inside the repo. Independent of
    # gitignore/exclude -- catches the excluded ``.claude/worktrees/`` case that
    # ``git status`` cannot see. The porcelain output is one block per worktree
    # (``worktree <path>`` first, attribute lines such as ``locked`` after it,
    # a blank line between blocks); ``locked`` is read per block.
    try:
        wl = subprocess.run(  # spawn: ok a reporter: a git that cannot list worktrees reports the litter it can see
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, cwd=str(root),
        )
        if wl.returncode == 0:
            registered: dict[Path, bool] = {}
            current: Path | None = None
            for line in wl.stdout.splitlines():
                if line.startswith("worktree "):
                    # ``splitlines()`` already dropped the line terminator; do NOT
                    # ``.strip()`` -- ``git worktree list`` does not quote paths, so a
                    # dir name with a legitimate leading/trailing space would strip to
                    # a phantom, non-existent path (and fail to dedup against source B).
                    try:
                        current = Path(line[len("worktree "):]).resolve()
                    except (OSError, ValueError):  # fail-open: ok deliberate -- an unresolvable registry line registers nothing
                        current = None
                        continue
                    registered.setdefault(current, False)
                elif current is not None and (line == "locked" or line.startswith("locked ")):
                    registered[current] = True
            locked.update(wt for wt, is_locked in registered.items() if is_locked)
            for wt in registered:
                if not wt.is_dir():
                    continue  # a prunable/dangling registration is no scan-noise hazard
                rel = _rel_to_root(wt)
                if rel is None:
                    continue  # the main worktree (the repo itself), or registered OUTSIDE the tree
                if _is_locked(wt) or _in_use(wt):
                    continue  # in use: a lock, or the session's own tree
                offenders.add(rel)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass  # fail-open; source B may still contribute (without the lock skip)

    # Source B: untracked dirs that are (or hide) a nested ``.git``.
    try:
        st = subprocess.run(  # spawn: ok a reporter: a git that cannot run reports the litter it can see
            ["git", "-c", "core.quotepath=false", "status", "--porcelain"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, cwd=str(root),
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return sorted(offenders)
    if st.returncode != 0:
        return sorted(offenders)
    nodes = 0
    for line in st.stdout.splitlines():
        # Porcelain v1 marks untracked with "?? " and COLLAPSES an untracked
        # subtree to its top dir (trailing "/") -- a deep nested repo hides
        # under its top untracked dir, so we must descend, not trust the line.
        if not line.startswith("?? "):
            continue
        entry = line[3:].strip().strip('"')
        if not entry.endswith("/"):
            continue
        cand = (root_resolved / entry).resolve()
        if not cand.is_dir():
            continue
        base_depth = len(cand.parts)
        for dirpath, dirnames, _files in os.walk(cand, followlinks=False):
            nodes += 1
            if nodes > max_nodes:
                return sorted(offenders)  # bounded: never slow boot unboundedly
            here = Path(dirpath)
            # A ``.git`` entry of any kind (dir, gitlink, or a dangling
            # symlink to a removed admin dir) == a foreign repo. Keep this in
            # sync with espalier/_safe_walk.py::has_git_entry -- a zero-import
            # copy the tools/cc rule forbids importing.
            if (here / ".git").exists() or (here / ".git").is_symlink():
                dirnames[:] = []          # do NOT descend into the nested repo
                if _is_locked(here) or _in_use(here):
                    continue  # in use: a locked worktree's gitlink, or the session's own tree
                rel = _rel_to_root(here)
                if rel is not None:
                    offenders.add(rel)
                continue
            if len(here.parts) - base_depth >= max_depth:
                dirnames[:] = []
    return sorted(offenders)


def _is_registered_worktree(root: Path, inside: str) -> bool:
    """Is the nested repo at ``inside`` (repo-relative, from
    ``_nested_repo_containing``) a registered worktree of this repository --
    one the path guards resolve against (DEF-743) -- rather than a foreign
    clone dropped into the tree? ``_hook_utils.is_sibling_checkout`` answers
    (identity by inode; never raises)."""
    return _hook_utils.is_sibling_checkout(root, root / inside)


def _warn_if_nested_repo_litter(root: Path, *, cwd: Path | None = None) -> None:
    """Surface untracked nested-repo litter at boot (defense-in-depth).

    A leftover worktree/clone (a stray ``.claude/worktrees/<name>/`` or an
    ``adopt2/`` scratch dir) is a foreign repo the walkers skip -- but if it
    lingers it still surfaces as phantom scan noise (a leftover worktree once
    produced ~17 ``fixture_skipped_by_live_scan`` fails that looked like a
    regression). This line makes the litter visible BEFORE it confuses a scan.

    Not litter, and not named by the WARN (the ``cc-worktrees`` external pin
    is the source of truth; ``_find_nested_repo_litter`` has the mechanics):
    the nested repo the session is running in -- ``cwd``, the hook input's via
    ``_hook_cwd``, the process cwd when ``None`` -- and any registered worktree
    carrying a ``git worktree lock``, Claude Code's or one you set yourself (a
    lock you set is never swept, so that worktree stays unreported until you
    unlock it). The first case gets one INFO line instead, so the session is
    not silent about where it is: a registered worktree of this repository is
    named as one (the path guards and plan checks resolve a target against
    the checkout containing it, so they govern the worktree like the root --
    DEF-743, ``_hook_utils.sibling_checkouts``); a foreign nested repo, which
    they do not govern, keeps the clause saying so.
    STDERR only (stdout carries the banner JSON). Silent when the tree is clean.
    """
    governed = (
        "-- the path guards and plan checks govern it like the root; the execution "
        "plan is the root's cc/execution_plan.json."
    )
    inside = _nested_repo_containing(root, cwd)
    if inside is not None:
        if _is_registered_worktree(root, inside):
            print(
                f"[INFO] session cwd is inside registered worktree {inside} "
                f"(not reported as litter) {governed}",
                file=sys.stderr,
            )
        else:
            print(
                f"[INFO] session cwd is inside nested git repo {inside} (not reported as litter) "
                "-- not a checkout of this repository, so the harness's path guards and plan "
                "checks do not govern writes made inside it.",
                file=sys.stderr,
            )
    else:
        # A worktree BESIDE the root (the shape docs/FAILURE_MODES.md recommends
        # for a second instance) is outside the walk above and was silent; the
        # session should still hear that the guards govern it.
        try:
            here = cwd if cwd is not None else Path.cwd()
        except OSError:  # fail-open: ok deliberate -- a vanished cwd sits in no sibling checkout
            here = None
        beside = _hook_utils.sibling_checkout_containing(root, here) if here is not None else None
        if beside is not None:
            print(
                f"[INFO] session cwd is inside worktree {beside} of this repository {governed}",
                file=sys.stderr,
            )
    litter = _find_nested_repo_litter(root, cwd=cwd)
    if not litter:
        return
    shown = ", ".join(litter[:5]) + ("  ..." if len(litter) > 5 else "")
    print(
        f"[WARN] untracked "
        f"{_hook_utils.plural(len(litter), 'nested git repo')} in the working tree: {shown} "
        "-- a leftover worktree/clone can surface as phantom scanner noise. "
        "Remove it (`git worktree remove --force <path>`, or delete the dir) "
        "or add it to .gitignore.",
        file=sys.stderr,
    )


def _warn_if_stop_gate_override_unresolved(root: Path) -> None:
    """One advisory line when ``ESPALIER_STOP_GATE_TEST_CMD`` names a program
    this host cannot start: the gate the operator armed for Stop would block
    once and then stand aside (stop_gate), and until 2026-09-30 nothing said so
    at boot. Splits with the stop gate's own splitter and resolves token 0 by
    the chokepoint's rules (``_hook_utils.resolve_program``: a path against
    the root, a bare name through ``shutil.which`` with PATHEXT), so the two
    never disagree -- and never the first-word extractor of DEF-968. A
    reporter; exit 0 always."""
    cmd = _hook_utils.stop_gate_test_cmd()
    if not cmd.strip():
        return
    try:
        parts = _hook_utils.split_command(cmd)
    except ValueError as exc:
        warn(
            f"ESPALIER_STOP_GATE_TEST_CMD could not be split ({exc}); the test gate armed "
            "for Stop will not start. Fix the quoting where the variable is set."
        )
        return
    if not parts:
        return
    if _hook_utils.resolve_program(parts[0], root=root) is not None:
        return
    # Reached only after shutil.which (PATHEXT included) failed, so a `.cmd`
    # respelling cannot help; the fix is the PATH of the launching shell.
    warn(
        f"ESPALIER_STOP_GATE_TEST_CMD names `{parts[0]}`, which does not resolve to a "
        "program on this host; the test gate armed for Stop will not start. Name a "
        "program on the PATH of the shell that launches Claude Code, or its full path, "
        "where the variable is set; it takes effect at the next launch."
    )


def _warn_if_maintenance_mode_active() -> None:
    """Surface persistent maintenance-mode usage.

    Per-bypass logs (``_maintenance_mode.is_active``) fire only when a
    hook check is invoked. If an operator sets the env var in a shell
    rc for permanence, the persistence cost only surfaces on the next
    bypass attempt — often not at all in a session that never trips a
    friction check. A SessionStart line makes the persistence visible
    at every boot.
    """
    if not _maintenance_mode._maintenance_mode_active(
        os.environ.get(_maintenance_mode.ENV_VAR)
    ):
        return
    print(
        f"[WARN] {_maintenance_mode.ENV_VAR} active -- protected-zone, "
        "plan-required, Stop gates 2/3 and the subagent blueprint append are "
        "bypassed for this session. "
        "Unset to restore enforcement.",
        file=sys.stderr,
    )


def _stop_gate_dormancy_note(root: Path) -> str | None:
    """When full-mode stop-gate is set, return a one-line warning if Gate 1 would
    dormant-skip on this repo's fingerprint shape, else None. Isolates the
    stop_gate._resolve_core_tests reach out of the banner assembler."""
    # ONE grammar (_hook_utils.stop_gate_mode). A raw `!= "full"` here meant a
    # padded value silently skipped this warning while stop_gate ran the full
    # suite on every Stop — the most consequential of the five divergences.
    if _hook_utils.stop_gate_mode(os.environ.get("ESPALIER_STOP_GATE")) != "full":
        return None
    try:
        from stop_gate import _resolve_core_tests
        resolved = _resolve_core_tests(root)
        if resolved.status.startswith("dormant_"):
            return (
                f"Stop-gate: Gate 1 dormant ({resolved.status}): it runs nothing. "
                "Set ESPALIER_STOP_GATE_TEST_CMD=<your test command> to run your suite.\n"
            )
        if resolved.status == "ok_harness_defaults":
            return (
                "Stop-gate: Gate 1 runs only the harness default test files, not "
                "your suite. Set ESPALIER_STOP_GATE_TEST_CMD=<your test command>.\n"
            )
    except Exception as e:  # noqa: BLE001 — bounded warn, never block session
        warn_exc("session_start: dormancy check failed", e)
    return None


# Core-loop commands shown in the SessionStart footer, in workflow order.
# This is a CURATED short list (not the full command set — that lives in
# cc/COMMANDS.md / `/status`); it is validated against cc/COMMANDS.md at
# render so a removed or renamed command can never linger in the banner.
# This tuple is now a FALLBACK ONLY -- the source of truth for the core set
# lives in render_surface.CORE_FLOW_COMMANDS, emitted into cc/COMMANDS.md's
# `## Core flow` section, which _commands_footer reads. Kept for the
# missing/unreadable/pre-regen COMMANDS.md case so the banner never crashes.
# sister-site: ok forced crash-fallback copy of render_surface.CORE_FLOW_COMMANDS (hook = zero-espalier-import; runtime reads cc/COMMANDS.md)
_CORE_FLOW_COMMANDS = (
    "/status", "/implement-task", "/smoke", "/preflight", "/commit", "/handoff", "/ship",
)
# Matches a command-name table cell in cc/COMMANDS.md: a `/name` wrapped in a
# tight backtick pair (descriptions embedding `/implement-task --multi` etc.
# carry trailing content inside the backticks, so they do NOT match).
_COMMANDS_MD_CELL_RE = re.compile(r"`(/[a-z][a-z0-9-]*)`")


def _parse_core_flow(text: str) -> "list[str]":
    """Extract the ordered `/command` names from cc/COMMANDS.md's rendered
    `## Core flow` section -- the run of lines after that heading, until the
    next `## `. Empty when the section is absent. This section is the source of
    truth for the banner command line (emitted by
    render_surface.render_commands_doc); the banner DERIVES from it rather than
    re-listing a tuple here, so a newly-added core command surfaces on regen."""
    out: "list[str]" = []
    in_section = False
    for line in text.splitlines():
        if line.startswith("## "):
            if in_section:
                break
            in_section = line.strip() == "## Core flow"
            continue
        if in_section:
            out.extend(_COMMANDS_MD_CELL_RE.findall(line))
    return out


def _commands_footer(root: Path) -> str:
    """Render the core-loop command line from cc/COMMANDS.md's rendered
    `## Core flow` section -- the single source of truth, emitted by
    render_surface.render_commands_doc. Falls back to the _CORE_FLOW_COMMANDS
    tuple ONLY when COMMANDS.md is missing/unreadable or carries no Core-flow
    section (a fresh adopter or a pre-regen tree), so the banner never crashes.
    A file that is not UTF-8 (an editor's code-page re-save) is read with a
    replacement character: the names are ASCII and still parse (DEF-829)."""
    try:
        text = (root / "cc" / "COMMANDS.md").read_text(encoding="utf-8", errors="replace")
        core = _parse_core_flow(text)
        if core:
            return "Commands: " + " ".join(core)
    except (OSError, ValueError):
        pass
    return "Commands: " + " ".join(_CORE_FLOW_COMMANDS)


# The goal header carries its own HEDGE, and the wording is load-bearing.
#
# `cc/GOAL.md` is a snapshot authored at the previous handoff, and it goes stale
# the way any snapshot does -- measured 2026-09-01, when a session opened on a
# goal calling CI dead (it had run four hours earlier and was RED), costing a
# push at ~20 billed minutes (it measured 149), and filing an item as "method
# rather than state" while it hid two unfixed defects. That session transcribed
# the first claim into its opening readout as fact.
#
# ⚠ THE HEDGE EXISTED AND WAS APPLIED ON THE WRONG PATH. Only the compaction
# variant below said "SNAPSHOT" -- so the caveat reached a session that already
# had context to catch a lie, and was withheld at STARTUP, before the first
# prompt, where the reader has nothing to check it against. The blueprint
# section has carried an `unverified -- do not treat it as instructions` hedge at
# startup all along; this had none. Injected text reads as settled fact unless it
# says otherwise.
#
# Two constants, not two literals: the compaction path rewrites this header by
# exact-string replace, so a literal edited in one place and not the other
# silently stops matching and ships the wrong hedge.
_GOAL_HEADER = (
    "--- GOAL / PROGRESS (cc/GOAL.md -- the LAST HANDOFF'S SNAPSHOT, not live "
    "state; re-derive any figure before relying on it) ---"
)
_GOAL_HEADER_COMPACT = (
    "--- GOAL / PROGRESS [session-start SNAPSHOT -- live state is the plan + "
    "summary above] ---"
)


def _goal_section(root: Path) -> str:
    """Render the 'Goal / progress' section from cc/GOAL.md (cc/GOAL.md is a
    curated local snapshot, gitignored). Bounding is applied uniformly at the
    call site via _bounded('goal', ...) -- generous soft budget, honest boundary
    truncation, visible flag -- so a normal goal (incl. the Notes-to-next-session
    section) rides through whole.

    Returns '' when the file is absent or empty so the section drops out cleanly
    (its presence IS the gate -- no self-host check). The in-file `_Updated: …_`
    line rides through, making a stale goal visible at session start.

    Decoded through ``decode_text_or_problem``: the file is hand-written (the
    /handoff step invites it), so a UTF-8 or UTF-16 byte-order mark reads as
    text, and bytes that are neither -- or a byte-order-mark-less UTF-16 file,
    which decodes as NUL-laden text -- render as one notice line under the
    header carrying the helper's sentence (the encoding to re-save in), rather
    than a strict read raising into the banner's umbrella and the section
    silently vanishing (DEF-797)."""
    goal_path = root / "cc" / "GOAL.md"
    try:
        raw = goal_path.read_bytes()
    except FileNotFoundError:  # fail-open: ok deliberate -- no goal file is the common case, and the banner says so
        return ""
    except OSError as exc:
        warn_exc("session_start: cc/GOAL.md unreadable; the goal section is omitted", exc)
        return ""
    text, problem = decode_text_or_problem(raw)
    if problem:
        # The header names the file; the line does not repeat it, because a
        # printed path an adopter cannot open is the pointer-resolution arm's
        # defect.
        return "\n" + _GOAL_HEADER + "\n" + f"(this goal snapshot is {problem})\n"
    text = text.strip()
    if not text:
        return ""
    return "\n" + _GOAL_HEADER + "\n" + text + "\n"


# ── Compact (mid-session) orientation: live mechanical state regenerated HERE ──
# These run ONLY on source=="compact" (not every session). Each is fail-open and
# time-bounded so a git/plan/blueprint hiccup degrades to '' and never crashes the
# post-compaction re-orientation. Regenerating at orientation (vs. an always-on
# write hook) gives always-current state without re-deriving it on every tool call.

def _active_plan_status(root: Path) -> str:
    """The live execution-plan task + current step. Regenerated at orientation, so
    always-current. '' when no plan is in_progress or it is unreadable (fail-open)."""
    try:
        data = json.loads((root / "cc" / "execution_plan.json").read_text(encoding="utf-8"))
    except FileNotFoundError:  # fail-open: ok deliberate -- no plan file is no plan
        return ""
    except (OSError, ValueError) as exc:
        # A plan file that exists and cannot be read is a plan the guard treats
        # as absent; the banner says so instead of drawing nothing.
        warn_exc("session_start: cc/execution_plan.json unreadable; plan_guard reads it as no plan", exc)
        return ""
    # Class-B guard: a malformed-but-valid JSON (a list/string/number) must not
    # AttributeError past the except -- isinstance before any dict deref.
    if not isinstance(data, dict) or data.get("status") != "in_progress":
        return ""
    steps = _plan_steps(data)
    running = next((s for s in steps if s.get("status") == "running"), None)
    current = running or next((s for s in steps if s.get("status") == "pending"), None)
    if not current:
        return ""
    done = sum(1 for s in steps if s.get("status") == "passed")
    return (
        "\n--- ACTIVE PLAN (live -- this is where you were) ---\n"
        + f"{_one_line(data.get('task', ''), 200)}\n"
        + _plan_step_line(current, steps, done, running is not None)
    )


def _plan_steps(data: dict) -> list[dict]:
    """The plan's step dicts, or [] when ``steps`` is not a list. Shared by
    both renderers of cc/execution_plan.json: ``has_active_plan`` accepts any
    truthy ``steps`` (``bool(5)``), and iterating that here raised a TypeError
    past the reader's except -- swallowed by main()'s umbrella at the cost of
    the whole banner, not the section."""
    raw = data.get("steps")
    return [s for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []


def _one_line(value: object, cap: int) -> str:
    """Operator-authored plan text collapsed to one line and capped: a newline
    in a task or step description would break the line shape and could forge
    a banner section header (`_summarize_memory` collapses the same way)."""
    return " ".join(str(value).split())[:cap]


def _plan_step_line(current: dict, steps: list[dict], done: int, running: bool) -> str:
    """One step line, spelled with the step's INDEX as the plan verbs take it
    (``mark <index> ...`` is 0-based), never as a 1-based fraction: `step 0/6`
    read as "no progress" and `step 2/4 (1 passed)` as skipped work."""
    return (
        f"  [{'>' if running else '.'}] step index {current.get('index')} of "
        f"{len(steps)} ({done} passed): {_one_line(current.get('description', ''), 160)}\n"
    )


def _plan_age_label(seconds: float) -> str:
    """How long since the plan file last changed: '3d 2h', '2h 05m' or '12m'."""
    total = max(0, int(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def _open_plan_section(root: Path) -> str:
    """A plan left ``in_progress`` when a FRESH session starts (source startup/clear).

    ``_hook_utils.has_active_plan`` -- the predicate plan_guard reads -- accepts
    the RECORD of a plan (``status == in_progress`` with at least one step) and
    takes no age or session input, because a plan legitimately spans sessions
    (``implement-pack --resume``). So the record of a task that ended without
    its ``/handoff`` (a crash, Ctrl-C, context exhaustion) holds plan_guard's
    mutation window open for every later session, and until 2026-09-12 nothing
    said so: ``_active_plan_status`` fired only inside the post-compaction
    re-orient, so a fresh ``startup`` never mentioned the open plan (DEF-643).
    This is the fresh-session twin: the same file, named as a state an EARLIER
    session left, with its age and the two verbs that resolve it. '' when no
    plan is open or the file is unreadable -- a reporter, so it fails open.
    """
    if not _hook_utils.has_active_plan(root):
        return ""
    plan_path = root / "cc" / "execution_plan.json"
    try:
        # The same symlink-refusing read the predicate just used, so the two
        # cannot be answering about different files.
        data = json.loads(_hook_utils.read_text_nofollow(plan_path, within=root))
        touched = plan_path.stat().st_mtime
    except (OSError, ValueError):  # fail-open: ok deliberate -- _active_plan_status reads the same file and speaks for it
        return ""
    if not isinstance(data, dict):
        return ""
    steps = _plan_steps(data)
    done = sum(1 for s in steps if s.get("status") == "passed")
    running = next((s for s in steps if s.get("status") == "running"), None)
    current = running or next((s for s in steps if s.get("status") == "pending"), None)
    age = _plan_age_label(time.time() - touched)
    # The interpreter the operator will TYPE, resolved on this host (never a bare
    # `python`, which a stock macOS lacks). '' when nothing clears the floor --
    # then the script is named and the interpreter left to the operator.
    py = _hook_utils.python_command_hint()
    verb = f"{py} tools/cc/execution_plan.py" if py else "tools/cc/execution_plan.py"
    parts = [
        f"\n--- OPEN PLAN (cc/execution_plan.json is in_progress; last touched {age} ago) ---\n",
        f"{_one_line(data.get('task', ''), 200)}\n",
    ]
    if current:
        parts.append(_plan_step_line(current, steps, done, running is not None))
    else:
        parts.append(
            f"  {done}/{len(steps)} steps passed, none pending -- the record never closed\n"
        )
    parts.append(
        "plan_guard reads this as an open mutation window on source files.\n"
        f"  Yours? Continue it: `{verb} status`\n"
        f"  A finished task's? Clear it: `{verb} reset` (the record is demoted "
        "beside the blueprint cold store)\n"
    )
    return "".join(parts)


def _recent_commits(root: Path, n: int = 3) -> str:
    """The newest ``n`` commit subjects, regenerated here. '' on git failure/timeout."""
    try:
        r = subprocess.run(  # spawn: ok a reporter: a git that cannot run draws no recent-commits section
            ["git", "log", f"-{n}", "--oneline", "--no-decorate"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, cwd=str(root),
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):  # fail-open: ok deliberate -- a git that cannot run draws no recent-commits section; a missing git is named by the load-bearing-tool warning
        return ""
    if r.returncode != 0 or not r.stdout.strip():
        return ""
    return "\n--- RECENT COMMITS ---\n" + r.stdout.strip() + "\n"


def _blueprint_recent(root: Path) -> str:
    """This-session blueprint decisions (cognitive_blueprint show-recent) -- the
    CURRENT reasoning, replacing the prior-session note on a compact. '' on failure."""
    bp = root / "tools" / "cc" / "cognitive_blueprint.py"
    if not bp.exists():
        return ""
    try:
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
        r = subprocess.run(  # spawn: ok a reporter: a show-recent that cannot run is warned at its handler
            [sys.executable, str(bp), "show-recent", "--n", "5"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, cwd=str(root), env=env,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        warn_exc("session_start: blueprint show-recent could not run; recent reasoning omitted", exc)
        return ""
    if r.returncode != 0 or not r.stdout.strip():
        return ""
    return "\n--- THIS SESSION'S DECISIONS (blueprint) ---\n" + r.stdout.strip() + "\n"


_ORIENTATION_COMPACT = """\
You just COMPACTED mid-session -- your working context was summarized, not lost.
Orient by REASONING over the compaction summary (in your context above) + the
ACTIVE PLAN step + this session's decisions -- re-establish, provisionally, where
you were and the immediate next action. Don't passively resume; reason your way
back in, then end with a proposed next move + "confirm or redirect?".
(Full record: cc/_working_summary.md, or /read-summary.)\
"""


def _build_compact_context(
    root: Path, self_host: bool, integrity: str = "", loose: str = "",
    open_prs: str = "", merged_prs: str = "", mail: str = "", sessions: str = "",
) -> str:
    """The mid-session COMPACT-orientation banner. Reshapes the normal banner:
    OMITS the MEMORY digest + the prior-session blueprint note (the compaction
    summary + this-session decisions are the current record); FLAGS GOAL as a
    start-of-session snapshot; ADDS the live plan step + recent commits + a pointer
    to the compaction summary; KEEPS the durable layer (standing principles, footgun
    pointer) that compaction dropped. A separate builder so the normal path stays
    byte-identical."""
    name = repo_name(root, warn_label="session_start")
    branch = check_branch(root)
    status = _check_dirty(root)
    surface = surface_status(root, degraded_format="upper")
    surface_line = surface if surface == "healthy" else (
        surface + "  ->  run `/context-load --mode recover`"
    )
    header_parts = [
        "=== Espalier-Harness === POST-COMPACTION RE-ORIENT (mid-session) ===\n",
        f"Repo:      {name}\n",
        f"Branch:    {branch}\n",
        f"Status:    {status}\n",
        # Orphaned heavy-CPU processes (DEF-752): a fan-out mid-session is
        # exactly when they appear, so the re-orient carries the line too.
        # Omitted when empty, like Integrity below, so callers that pass
        # nothing keep a byte-identical banner.
        *([f"Loose:     {loose}\n"] if loose else []),
        # Another live session in this same tree: the re-orient
        # carries it too, since a second window may have opened mid-session.
        # Same omit-when-empty contract.
        *([f"Sessions:  {sessions}\n"] if sessions else []),
        # The operator's open pull requests: a lane that auto-merged during
        # the session, or one a red check is holding. Same omit-when-empty
        # contract as Loose.
        *([f"Open PRs:  {open_prs}\n"] if open_prs else []),
        *([f"Merged:    {merged_prs}\n"] if merged_prs else []),
        *([f"Mail:      {mail}\n"] if mail else []),
        f"Surface:   {surface_line}\n",
        # Tamper state, in the channel the session actually reads. Omitted when the
        # caller supplies nothing so the existing shorter-arity callers (tests, and
        # any future one) keep a byte-identical banner; production always passes it.
        # Rendered even when clean, deliberately: "ok" and "no line at all" must not
        # look the same, or a check that stopped running would read as a pass.
        *([f"Integrity: {integrity}\n"] if integrity else []),
        _commands_footer(root) + "\n",
    ]
    for _payload in reversed(_reinject.check("SessionStart", "", {}, root)):
        header_parts.insert(1, _payload + "\n")
    header = "".join(header_parts)

    flags: "list[str]" = []
    body_parts = [
        "\nYour working context was summarized (the compaction summary is above). "
        "The sections below are the LIVE current state, regenerated now.\n",
    ]
    # LIVE mechanical state (regenerated here -- the real "where was I"):
    for section in (_active_plan_status(root), _recent_commits(root)):
        if section:
            body_parts.append(section)
    recent = _blueprint_recent(root)
    if recent:
        bp_budget = _SOFT_BUDGETS["blueprint"]
        if len(recent.encode("utf-8")) > bp_budget:
            flags.append(
                "[banner] blueprint section is large -- "
                "bounded (oldest whole entries dropped, or newest truncated if it "
                "alone exceeds budget); pull cc/blueprints for the full record"
            )
        body_parts.append(_drop_whole_entries(
            recent, bp_budget, _BLUEPRINT_ENTRY_RE,
            "\n[older blueprint entries dropped -- pull cc/blueprints/latest.json]",
        ))
    # GOAL: flagged as a session-start SNAPSHOT (its "next" is stale mid-session).
    goal = _goal_section(root)
    if goal:
        goal = goal.replace(_GOAL_HEADER, _GOAL_HEADER_COMPACT)
        body_parts.append(_bounded("goal", goal, flags, hard_cap=_GOAL_HARD_CAP, keep_tail=True))
    # Durable layer dropped in compaction: standing + footgun pointer. The
    # pointer rides its CATALOGS here exactly as it does in _build_context --
    # this function carries its own copy of that gate, and an adopter compacting
    # mid-session is precisely when the durable layer needs to survive. STANDING
    # stays self-host-gated for the same reason as there: no adopter artifact.
    if self_host:
        standing = _standing_principles_index(root)
        if standing:
            body_parts.append(_bounded("standing", standing, flags))
    fp = _footgun_pointer(root)
    if fp:
        body_parts.append(fp)
    body_parts.append(
        "\n--- CURRENT-SESSION RECORD ---\nPrimary: the compaction summary in your "
        "context. Pull for detail: cc/_working_summary.md (/read-summary).\n"
    )
    body = "".join(body_parts)
    if flags:
        body = "--- BANNER HEALTH ---\n" + "\n".join(flags) + "\n\n" + body

    tail = "".join([
        "\n", _ORIENTATION_COMPACT,
        "\n\n", "(/context-load --mode recover if the Surface line above is DEGRADED.)",
    ])
    margin = 64
    budget = _MAX_CONTEXT_BYTES - len(header.encode("utf-8")) - len(tail.encode("utf-8")) - margin
    body = _truncate_on_boundary(body, max(0, budget), "\n[banner body truncated -- budget]")
    return header + body + tail


def _build_context(
    root: Path,
    self_host: bool,
    advance_chain: bool,
    source: str = "",
    integrity: str = "",
    loose: str = "",
    open_prs: str = "",
    merged_prs: str = "",
    mail: str = "",
    sessions: str = "",
) -> str:
    """Assemble the SessionStart additionalContext banner. ``self_host`` is the
    once-computed value from main so is_self_host_repo is not re-probed here.
    ``advance_chain`` (derived from the SessionStart source) decides whether
    ``_load_blueprint`` starts a fresh blueprint node or loads read-only.
    ``source == "compact"`` selects the mid-session compact-orientation variant
    (live mechanical state regenerated here + a pointer to the compaction summary,
    not the stale start-of-session banner); ``source`` defaults to "" so the 11
    existing 3-arg callers stay valid and every NON-compact source keeps the
    normal banner byte-identical."""
    if source == "compact":
        return _build_compact_context(root, self_host, integrity, loose, open_prs, merged_prs, mail, sessions)
    name = repo_name(root, warn_label="session_start")
    branch = check_branch(root)
    status = _check_dirty(root)
    memory = _summarize_memory(root)
    blueprint = _load_blueprint(root, advance_chain)
    surface = surface_status(root, degraded_format="upper")
    # Health self-check: a non-healthy surface CARRIES its recovery action, so a
    # session that no longer types /context-load still learns when to run it.
    surface_line = surface if surface == "healthy" else (
        surface + "  ->  run `/context-load --mode recover`"
    )
    # The footgun catalogs are retrievable via /recall, so the banner carries a
    # one-line POINTER, not the old ~8KB TOC wall. Gated on the CATALOGS, not on
    # repo identity: `init` seeds docs/FAILURE_MODES.md in full, so an adopter
    # owns a catalog the old `if self_host` wrapper threw away. `_footgun_pointer`
    # already returns '' when neither catalog carries real content, which is the
    # question the wrapper was standing in for.
    footgun_pointer = _footgun_pointer(root)

    # The banner is assembled as FIXED header + CLIPPABLE optional body +
    # ALWAYS-ON orientation tail. Sections are bounded by generous per-section
    # soft budgets (_bounded) and the body as a whole is boundary-clipped against
    # the remaining budget; the orientation tail always survives.
    header_parts = [
        "=== Espalier-Harness === Session Start ===\n",
        f"Repo:      {name}\n",
        f"Branch:    {branch}\n",
        f"Status:    {status}\n",
        # Orphaned heavy-CPU processes an earlier session left (DEF-752): the
        # PIDs and the one-paste kill, reporter only. Omitted when empty, like
        # Integrity below, so the shorter-arity callers keep a byte-identical
        # banner; production always passes what the process table said.
        *([f"Loose:     {loose}\n"] if loose else []),
        # Another live Claude Code session in this same tree:
        # its id prefix, when it started and last prompted, and what the two
        # share. Same omit-when-empty contract; production passes what the
        # per-session markers said.
        *([f"Sessions:  {sessions}\n"] if sessions else []),
        # The operator's pull requests (the /ship lane's SessionStart half):
        # the open ones with number, head branch, check tally and auto-merge
        # state, then the merged ones the local base branch does not reach yet
        # -- so a lane a red check is holding, or one that landed behind this
        # session's back, is named before it commits anything. Same
        # omit-when-empty contract as Loose; production passes what `gh pr
        # list` said.
        *([f"Open PRs:  {open_prs}\n"] if open_prs else []),
        *([f"Merged:    {merged_prs}\n"] if merged_prs else []),
        # The other machine's unread mail (tools/cc/mail.py), where this box
        # is named: headlines newest first, then the tail that says whose
        # text it is. Same omit-when-empty contract; read once in main.
        *([f"Mail:      {mail}\n"] if mail else []),
        f"Memory:    {memory}\n",
        f"Blueprint: {blueprint}\n",
        f"Surface:   {surface_line}\n",
        # Tamper state, in the channel the session actually reads. Omitted when the
        # caller supplies nothing so the existing shorter-arity callers (tests, and
        # any future one) keep a byte-identical banner; production always passes it.
        # Rendered even when clean, deliberately: "ok" and "no line at all" must not
        # look the same, or a check that stopped running would read as a pass.
        *([f"Integrity: {integrity}\n"] if integrity else []),
        _commands_footer(root) + "\n",
        "Run /status to verify harness state.\n",
    ]
    # Tier-1 ambient orientation (host/interpreter + active modes) from the
    # recall registry -- the parent-session twin of subagent_start's cold
    # orientation. Inserted right after the banner; _clean_state_flags (above)
    # already reset reinject_count this session, so the row fires (n=1).
    for _payload in reversed(_reinject.check("SessionStart", "", {}, root)):
        header_parts.insert(1, _payload + "\n")
    header = "".join(header_parts)

    # OPTIONAL body — the high-byte, clippable tenants.
    body_parts = []
    flags: "list[str]" = []  # visible per-section bloat flags (populated by _bounded)
    # A plan an EARLIER session left in_progress, first in the body so it
    # survives the clip: plan_guard's window is open on its record (DEF-643).
    # Gated on advance_chain -- this hook's own definition of a fresh session
    # (startup/clear) -- so a resume of the same session, whose plan is simply
    # live, keeps the banner it had.
    if advance_chain:
        open_plan = _open_plan_section(root)
        if open_plan:
            body_parts.append(open_plan)
    # Health self-check (logic-only): flag a continuity surface that failed to
    # load so a silently-missing blueprint is observable, not invisible. Gated on
    # the STATE, not on repo identity -- an adopter whose blueprint chain broke
    # needs to see that at least as much as the harness does, and the state test
    # is right here in the same condition.
    if blueprint in _BLUEPRINT_FAILURE_STATES:
        flags.append(f"[banner] blueprint continuity unavailable: {blueprint!r}")
    goal = _bounded("goal", _goal_section(root), flags, hard_cap=_GOAL_HARD_CAP,
                     keep_tail=True)
    if goal:
        body_parts.append(goal)
    # MEMORY Session-Log digest -- gated on the DIGEST, not on repo identity.
    # `init` deploys ESPALIER_MEMORY.md WITH a Session Log, so an adopter who has
    # run /handoff has their own recency to show; the old gate computed it and
    # threw it away. `_memory_toc` already returns '' when the file is absent or
    # carries no dated rows.
    memory_digest = _memory_toc(root)
    if memory_digest:
        body_parts.append(_bounded("memory", memory_digest, flags))
    # STANDING PRINCIPLES stays self-host-gated, deliberately. Unlike its two
    # siblings above there is no adopter artifact to gate ON:
    # docs/STANDING_PRINCIPLES.md reaches neither adopter path (not a seed, not in
    # the fusion manifest), so un-gating would render nothing while dropping this
    # helper out of test_adopter_pointer_resolution's self-host-only exemption --
    # buying a dead-pointer exemption for zero behaviour.
    #
    # ⚠ THE REVISIT TRIGGER CHANGED, 2026-08-19. This used to read "revisit if the
    # doc is ever seeded", which watches for something that will never happen --
    # `init` deliberately does not seed it. The event that actually matters already
    # occurred: `_recall.py` now indexes docs/STANDING_PRINCIPLES.md gated on FILE
    # EXISTENCE, so an adopter who WRITES one gets it from `/recall` but not from
    # this banner. The real trigger is therefore "an adopter authored the file",
    # which `_standing_principles_index` already detects -- it returns '' when the
    # doc is absent, exactly like the memory_digest content-gate ten lines above.
    # Switching `self_host` to a content-gate is a one-line change with identical
    # self-host behaviour. Deliberately NOT done here: it widens this diff from a
    # recall-corpus change into a SessionStart-surface change with its own
    # adopter-pointer test consequences. Left as a stated, accurate trigger.
    if self_host:
        standing = _standing_principles_index(root)
        if standing:
            body_parts.append(_bounded("standing", standing, flags))
    if footgun_pointer:
        body_parts.append(footgun_pointer)
    # When full-mode stop-gate is set, warn the operator if Gate 1 would
    # dormant-skip on this repo's fingerprint shape.
    dormancy = _stop_gate_dormancy_note(root)
    if dormancy:
        body_parts.append(dormancy)
    body = "".join(body_parts)
    # Surface any bloat flags at the TOP of the body so they survive the outer
    # clip and are immediately visible -- growth is observable, not silent.
    if flags:
        body = "--- BANNER HEALTH ---\n" + "\n".join(flags) + "\n\n" + body

    # ALWAYS-ON tail — the orientation block. (The leading "\n" was previously a
    # standalone part between the body and orientation; it rides the tail now so
    # the no-clip output is byte-identical.)
    # `goal` is the BOUNDED section built above -- falsy when cc/GOAL.md is
    # absent or empty. Gating on it (not on self_host) keeps the instruction
    # honest on a self-host tree whose GOAL has been deleted, too.
    tail_parts = ["\n", _orientation_common(bool(goal))]
    # Two INDEPENDENT conditions, not two arms of one identity fork. The footgun
    # line names the same catalogs the pointer does, so it rides the POINTER --
    # present exactly when there is something to pull. The no-digest line exists
    # BECAUSE no digest was injected, so it rides that. A tree can honestly
    # warrant both (catalogs present, Session Log still empty) or neither.
    # Rides what /recall can reach here (indexed_sources), not the pointer's wording. Gating
    # on the pointer looked right and was wrong the other way: `init` seeds three
    # real docs/sharp-edges/ files, so /recall WORKS on a fresh adopter tree --
    # but their seeded docs/SHARP_EDGES.md is (correctly) suppressed, so the
    # pointer took its no-pull branch and this line vanished with it. Their first
    # banner then said "/recall does not index it" and nothing else about
    # /recall, on the one tree where it does work.
    # One corpus walk answers both "can /recall reach anything here" and "what
    # does it reach": a non-empty family list IS the corpus being non-empty.
    families = _recall.indexed_sources(root) if _recall is not None else []
    if families:
        tail_parts.append(_orientation_footgun_line(families))
    if not memory_digest:
        tail_parts.append(_ORIENTATION_NO_DIGEST_LINE)
    tail_parts.append(_ORIENTATION_TAIL)
    tail_parts.extend([
        "\n\n",
        "(/context-load remains available for explicit mid-session re-orient.)",
    ])
    tail = "".join(tail_parts)

    # Clip the BODY (never the header or tail) against the remaining budget, on a
    # whitespace boundary via the shared helper. main()'s outer
    # encoded[:_MAX_CONTEXT_BYTES] stays as a last-resort backstop but is now
    # unreachable in the worst case.
    margin = 64  # join/newline slack
    budget = _MAX_CONTEXT_BYTES - len(header.encode("utf-8")) - len(tail.encode("utf-8")) - margin
    body = _truncate_on_boundary(body, max(0, budget), "\n[banner body truncated -- budget]")
    return header + body + tail


def _run_main() -> int:
    from _hook_utils import read_stdin_safely  # noqa: E402

    # The SessionStart payload carries `source` (startup|resume|clear|compact).
    # It decides whether to advance the blueprint chain (see _load_blueprint).
    payload = read_stdin_safely()
    src = payload.get("source") if isinstance(payload, dict) else None
    source = src if isinstance(src, str) else ""

    root = _resolve_project_root()
    # is_self_host_repo does 3 is_dir stats + a pyproject parse + a SHA-256 of
    # write_guard.py's first 200 bytes; the result is invariant within one
    # invocation, so compute it once and reuse at both gate sites.
    self_host = is_self_host_repo(root)

    # State-flag I/O runs BEFORE the banner builds; a read-only/full/occupied
    # .espalier-state dir must not cost the whole orientation banner. Each flag
    # job is best-effort (warn + continue) so _build_context still runs.
    # The payload's session_id names this session's marker;
    # sanitised, because it is a file name taken from untrusted text, and ''
    # (no id) writes no marker.
    sid = _hook_utils.safe_session_id(payload.get("session_id") if isinstance(payload, dict) else "")

    def _marker_job() -> None:
        # A compact or resume re-fires SessionStart mid-session; the session did
        # not start again, so its marker keeps the start it recorded. The helper
        # fails open by returning False; raising here routes that into the
        # loop's warn, so a marker that never lands is at least said (a payload
        # with no id writes none by design, and says nothing).
        if sid and not _hook_utils.write_session_marker(
            root, sid, pid=os.getppid(), cwd=str(_hook_cwd(payload) or ""), source=source,
            keep_started=source in _CONTINUATION_SOURCES,
        ):
            raise OSError("the session marker could not be written")

    for _flagjob, _flaglabel in (
        (lambda: _clean_state_flags(root, source), "session_start: state-flag cleanup failed"),
        (lambda: _set_cold_open_flag(root, source), "session_start: cold-open flag write failed"),
        (_marker_job, "session_start: session marker write failed"),
    ):
        try:
            _flagjob()
        except Exception as e:  # noqa: BLE001 — flag I/O is best-effort; never lose the banner
            warn_exc(_flaglabel, e)

    # The boot warnings are advisory reporters — each must fail open (warn +
    # continue, never block the session). One handler in a loop keeps that
    # discipline in a single place and unifies the BLE001 rationale text. The
    # no-arg callees are wrapped so the table is uniform without touching their
    # signatures.
    # Hoisted out of the uniform table below because it is the one reporter whose
    # RESULT the banner needs — the table discards return values by design. Same
    # guard shape as the loop: a reporter must never take the session down.
    try:
        integrity_line = _report_integrity_state(root)
    except Exception as e:  # noqa: BLE001 — bounded warn, never block session
        warn_exc("session_start: integrity check failed", e)
        integrity_line = "unverified (check failed)"

    _boot_warnings = [
        (lambda: _report_freshness(root), "session_start: freshness banner failed"),
        (_integrity._prune_old_audit_logs, "session_start: audit log pruning failed"),
        (_warn_if_maintenance_mode_active, "session_start: maintenance-mode banner failed"),
        (lambda: _warn_if_load_bearing_tool_missing(self_host), "session_start: external-tool banner failed"),
        (lambda: _warn_if_hook_interpreter_unresolved(root), "session_start: hook-interpreter banner failed"),
        (lambda: _warn_if_stop_gate_override_unresolved(root), "session_start: stop-gate override banner failed"),
        (lambda: _warn_if_nested_repo_litter(root, cwd=_hook_cwd(payload)), "session_start: nested-repo-litter banner failed"),
    ]
    for _job, _label in _boot_warnings:
        try:
            _job()
        except Exception as e:  # noqa: BLE001 — bounded warn, never block session
            warn_exc(_label, e)

    # The process table, read once here (never inside the builders, which the
    # banner tests drive on scratch trees): a reporter, so a missing `ps` or a
    # failed spawn costs the line, never the banner.
    try:
        loose_line = _loose_processes_line()
    except Exception as e:  # noqa: BLE001 — bounded warn, never block session
        warn_exc("session_start: loose-process scan failed", e)
        loose_line = ""

    # The sibling sessions' markers, read once here like the process table: a
    # second Claude Code session in this same tree shares every current-X file
    # with this one, and nothing else says so. The age sweep rides the same
    # read. Reporter: a state dir that cannot be read costs the line, never the
    # banner.
    try:
        if source == "clear":
            # The previous session in THIS window is gone; where the hook's
            # parent pid identifies the window, its marker is retired here so
            # the operator's handoff-then-clear loop is not told about itself.
            _hook_utils.retire_same_window_markers(root, sid, os.getppid())
        _hook_utils.prune_session_markers(root)
        sessions_line = _sessions_line(root, sid)
    except Exception as e:  # noqa: BLE001 — bounded warn, never block session
        warn_exc("session_start: session marker scan failed", e)
        sessions_line = ""

    # The operator's pull requests, read here for the same reason: two bounded
    # `gh` reads under one deadline, and a host without `gh`, a sign-in or a
    # GitHub remote costs the lines, never the banner. Two handlers, so the
    # merged question (the one that shells out to git per row) cannot take
    # the already-computed open line down with it.
    pr_deadline = _pr_deadline()
    try:
        open_prs_line = _open_prs_line(_read_open_prs(root, pr_deadline), root, deadline=pr_deadline)
    except Exception as e:  # noqa: BLE001 — bounded warn, never block session
        warn_exc("session_start: open pull-request scan failed", e)
        open_prs_line = ""
    try:
        merged_prs_line = _merged_prs_line(_read_merged_prs(root, pr_deadline), root, deadline=pr_deadline)
    except Exception as e:  # noqa: BLE001 — bounded warn, never block session
        warn_exc("session_start: merged pull-request scan failed", e)
        merged_prs_line = ""

    # The other machine's mail, read here under the SAME deadline for the same
    # reason: one bounded fetch, then local reads, each taking what the
    # pull-request block left; a box that names no machine gets at most the
    # opt-in line.
    try:
        mail_line = _mail_line(root, pr_deadline)
    except Exception as e:  # noqa: BLE001 — bounded warn, never block session
        warn_exc("session_start: mail scan failed", e)
        mail_line = ""

    context = _build_context(
        root, self_host, _should_advance_chain(source), source,
        integrity=integrity_line, loose=loose_line, sessions=sessions_line,
        open_prs=open_prs_line, merged_prs=merged_prs_line, mail=mail_line,
    )

    # Enforce size budget — truncate rather than flood context window.
    encoded = context.encode("utf-8")
    if len(encoded) > _MAX_CONTEXT_BYTES:
        context = encoded[:_MAX_CONTEXT_BYTES].decode("utf-8", errors="replace") + "\n[context truncated]"

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))
    return 0


def main() -> int:
    """Public entry-point. Umbrella try/except degrades any uncaught exception
    in ``_run_main`` to a quiet no-op (exit 0), matching every advisory/reporter
    sibling. (Only ``stop_gate.py`` re-raises KeyboardInterrupt/SystemExit before
    its ``BaseException`` catch — a Stop-hook concern; the PreToolUse guards
    intentionally convert an interrupt into a fail-closed deny/block.)

    SessionStart is a REPORTER: per the hook protocol it cannot block, and a
    non-{0,2} exit only drops the banner while spewing a traceback. It fires on
    EVERY session and is the adopter's first-impression orientation surface, so
    a crash (read-only repo root, occupied .espalier-state, full disk) must fail
    OPEN — lose the banner quietly, never crash the session with a traceback.
    """
    try:
        return _run_main()
    except BaseException as exc:  # noqa: BLE001 — fail-open crash guard (reporter hook)
        print(
            f"[ERROR] session_start crashed: {type(exc).__name__}: {os_error_text(exc)}",
            file=sys.stderr,
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
