#!/usr/bin/env python3
"""What ``write_guard`` costs a call, measured: the per-call cost instrument.

``write_guard.py`` is wired on PreToolUse with matcher ``*``, so every tool call
starts it, and every Bash, PowerShell, mutation and ``mcp__`` call loads its
pattern path (``tools/cc/hooks/write_guard.py::_load_the_pattern_path``). This
script reads three figures; none of them is a verdict, and it changes nothing the
guard judges.

Usage::

    python3 scripts/guard_cost_census.py --calls 30 [--kind bash ...] [--json]
    python3 scripts/guard_cost_census.py --compile [--json]
    python3 scripts/guard_cost_census.py --import-time --rounds 10 [--cold] [--json]
    python3 scripts/guard_cost_census.py --compile --at caae022 --json

``--calls N`` spawns the guard N times for each call kind (a Read, a Bash ``ls
-la``, an MCP read, an MCP write, a PowerShell ``Get-ChildItem``, and the three
calls that pay a first-use accessor's compile, ``COMMANDS``, and a Write, an
Edit, a Bash ``ls`` and a PowerShell ``Get-ChildItem`` of a file in the
session's own checkout, each also with maintenance mode on, ``REPO_KINDS``) beside a bare interpreter start as the control,
which is always timed, shuffled, each spawn in an empty temp project of its own
(for ``REPO_KINDS``, a linked worktree of a fresh repository, a seat's layout)
(no settings file, no ``espalier.toml``), the way the wiring starts it
(``<python> <tools/cc/hooks/write_guard.py>``, the payload on stdin) with
``-B`` added, and
prints each kind's median, IQR, min and max in milliseconds beside the decisions
it saw. A guard call starts two interpreters (the thin parent and its judging
child) and the control one, so the control nets out one start. ``-B`` writes no
cache: a checkout's existing cache is read, and an ``--at`` tree has none, so
its figure is the no-cache one. The wiring passes no ``-B``, so after a pull a
live call rewrites a stale module's cache once, where every census spawn
recompiles it: a row whose modules read stale overstates a warm live call. The MCP write names a file inside its temp
project, so the zone layer allows it. Each spawn's project is its own, so a
one-shot nudge an earlier spawn spent cannot change a later one's decision. A
row whose decisions are not what an ordinary call gets (``allow``; ``exit 0`` for
the control) is tagged ``decisions mixed`` and the run exits
``DECISIONS_MIXED_EXIT``: its figure is not a cost. A refusal at the guard's
deadline reads ``deny (time budget)``, a deny it gave as it failed itself
``deny (crash)`` (DEF-2096), and the guard's own budget records are
counted per kind before the run's audit folder goes.

``--compile`` records every ``re._compile`` call while ``_bash_patterns``,
``_speedbump`` and ``write_guard`` import and ``_load_the_pattern_path`` runs, in
a fresh interpreter (``-I -B``): the distinct patterns (keyed by pattern and
flags) and the characters of the distinct string patterns, those again for the
compiles whose call stack passes through the hooks folder (the standard
library's own differ by interpreter), the hooks-folder patterns the loader
compiled first (``loader_patterns``, ``loader_chars``: the imports compile the
rest), and the shared fragment
``_bash_patterns._CMD_POS_NO_VERB``'s length (and ``_CMD_POS``'s). Then, with the recorder
still in place, it compiles each pattern compiled on first use
(``FIRST_USE_RULE``: a module-level cached accessor of the three modules that
takes no argument and whose body names ``compile``, called; and each of a
module's own first-use objects, ``_bash_patterns._FirstUse``, which hold every
module-level pattern there since DEF-2084, read once; ``tests/_first_use_patterns.py``'s
rule, carried here and pinned equal to it): ``first_use_patterns`` and
``first_use_chars`` are those patterns and their characters, each
counted whether or not an import compiled it first (note 0b0d58's hand probe),
and ``summed_patterns`` and ``summed_chars`` are the distinct patterns the hooks
folder compiled across the imports, the loader and those calls: the figure a
cost gate reads, since a pattern moved behind an accessor is still compiled by
every call that opens its check (DEF-4122). ``embedding_patterns`` and
``embedding_chars`` count the patterns of every compile recorded, first use
included, that embed the fragment, and their characters. ``loader_ran`` and
``fragment_found`` say whether those two were there: a tree whose
``write_guard`` has no ``_load_the_pattern_path`` (before DEF-946, 2026-11-08)
is read by its imports alone and says so, and on this checkout that is an error,
since the loader's own compiles would go uncounted. A run that records no pattern
prints no figure and exits 1.

``--import-time --rounds N`` times the two pattern modules' import in N fresh
interpreters, each reading the bytecode cache a warm-up run wrote into a private
``pycache_prefix`` (what a session's spawn reads); ``--cold`` gives every round
an empty prefix instead, so the figure carries the source compile.

``--at <sha>`` runs any of the three against ``git archive <sha> tools/cc`` in a
temp folder (a commit only a closed pull request reaches needs its ref fetched
first: ``git fetch origin pull/516/head``). ``--root <dir>`` reads another
folder's ``tools/cc`` instead (a fixture, a second checkout). ``--json`` prints
one JSON object. Beside every figure: the tree (on this checkout, whether its
``tools/cc`` is ``origin/main``'s as the local ref has it), the interpreter, the
cache state of every module a spawn imports, the lock, and the load average at
the start and the end (on Windows, which has none, the CPU's busy share over the
run).

**The box lock.** ``--calls`` and ``--import-time`` time, so they hold the box
lock the test tiers take (ruling 3a): the file ``$ESPALIER_BOX_LOCK`` names,
through ``tools/cc/_json_safe.py::try_lock_file``, loaded by path. ``tests/
_box_lock.py`` imports pytest, so this script keeps its own copy of what a holder
does there, pinned to it by ``tests/test_guard_cost_census.py``: the launcher's
old default path is read as its new one, the holder record carries
``build_record``'s keys and is stamped when the lock is taken, a waiter names its
holder at once and every ``REPORT_S``, ``ESPALIER_BOX_LOCK_WAIT_S`` bounds the
wait with ``DID_NOT_RUN_EXIT``, every outcome appends one line to
``<lock path>.log``, and the record is cleared at release, where a hold's
``released`` line (its ``held_s``) is written before the unlock. One difference: a
tier waits unbounded where the variable is unset, and the census, always an
agent's run under a Bash call's ten-minute cap, waits ``DEFAULT_WAIT_S``. Inside
a holder (the inherited ``ESPALIER_BOX_LOCK_HOLDER`` names the live pid in the
record) it passes through. With the lock variable unset it runs unguarded and
says ``unguarded`` beside every figure. ``--compile`` counts and takes no lock.
On a box of several slots (``tools/cc/_json_safe.py::box_lock_slots``, the
count in the file beside the lock) the census holds every slot, in order, as a
tier's serial line does, since what it times is one process's start on a quiet
box (DEF-2105); the pair is read over every slot first, and its log lines name
the slot the plugin's way.

Every child's environment drops ``ESPALIER_MAINTENANCE_MODE`` (the ``_maintenance``
kinds set it) and every
``CLAUDE_*`` variable, sets ``CLAUDE_PROJECT_DIR`` to the spawn's temp project and
``ESPALIER_AUDIT_DIR`` to a temp folder, so no state lands in the checkout and no
session's markers are touched; where the guard rejects that folder (a ``TMPDIR``
outside its safe roots) its records reach ``~/.espalier/audit``, and the output
says so. Stdlib only, self-host; output is ASCII.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import math
import os
import platform
import random
import re
import shlex
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

REPO_ROOT = Path(__file__).resolve().parents[1]
KINDS = ("control", "read", "bash", "mcp_read", "mcp_write",
         "powershell", "powershell_pipe", "bash_xargs", "bash_powershell",
         "bash_redirect", "powershell_redirect",
         "write", "edit", "write_maintenance", "edit_maintenance",
         "bash_seat", "bash_seat_maintenance",
         "powershell_seat", "powershell_seat_maintenance")
#: The file-tool kinds (DEF-3106): a Write and an Edit of a file in the
#: session's own checkout, spawned in a repository whose project dir is a
#: linked worktree, as a worker seat's is, so the worktree registry the
#: file-tool readers walk (``_hook_utils.sibling_checkouts``) is there to read.
#: Each has a twin with ``ESPALIER_MAINTENANCE_MODE`` set, which every seat on
#: the Air runs and which skips the zone check ahead of the speed bumps.
#: ``bash_seat`` and ``powershell_seat`` (DEF-5135) are a Bash and a
#: PowerShell call in the same layout naming the session's own tree through
#: the main checkout's path, the costliest call CP-OTHER-CHECKOUT's shell gate
#: reads and stays shut on; the plain ``bash`` and ``powershell`` kinds spawn
#: in a folder that is no repository, where the shell arm stops at the empty
#: worktree registry and never reaches its gate.
REPO_KINDS = frozenset({"write", "edit", "write_maintenance", "edit_maintenance",
                        "bash_seat", "bash_seat_maintenance",
                        "powershell_seat", "powershell_seat_maintenance"})
MAINTENANCE_KINDS = frozenset({"write_maintenance", "edit_maintenance", "bash_seat_maintenance",
                               "powershell_seat_maintenance"})
#: The commands of the Bash and PowerShell kinds. ``bash`` and ``powershell``
#: are the ordinary call of each tool; ``powershell_pipe``, ``bash_xargs``
#: and ``bash_powershell`` are the calls each of `_bash_patterns`' first-use
#: accessors exists for (the ratchet's ``OPENING_CALLS``, pinned equal by
#: ``tests/test_guard_compile_ratchet.py``): a piped PowerShell call
#: (``_ps_interp_stdin_re``), a Bash pipe into xargs
#: (``_carrier_fed_remove_re``) and a Bash call naming powershell
#: (``_powershell_head_re``), so the call that pays a first-use compile has a
#: per-call figure of its own (DEF-5115). The two ``_redirect`` kinds are the
#: ordinary call with a redirect on it, which about two thirds of this
#: project's Bash calls carry (3,996 of 6,104 in its 60 newest transcripts,
#: air's ruling f03cb7): the readers that also match with the redirects
#: blanked (`_bash_patterns._redirects_blanked`, DEF-2087) do that work on
#: such a call alone, so the plain kinds never time it.
COMMANDS = {
    "bash": ("Bash", "ls -la"),
    "powershell": ("PowerShell", "Get-ChildItem notes"),
    "powershell_pipe": ("PowerShell", "Get-ChildItem notes | Select-Object -First 1"),
    "bash_xargs": ("Bash", "echo notes | xargs cat"),
    "bash_powershell": ("Bash", "powershell Get-ChildItem notes"),
    "bash_redirect": ("Bash", "git status 2>&1"),
    "powershell_redirect": ("PowerShell", "git status 2>&1"),
}
#: The decision an ordinary call of each kind gets; any other makes the row's
#: figure something other than a cost.
EXPECTED_DECISION = {"control": "exit 0", **{kind: "allow" for kind in KINDS[1:]}}
#: How long one spawn may take: the guard's own deadline is 4 s from its first
#: line and the wired timeout 5 s, so a spawn past this is a hang, not a cost.
SPAWN_TIMEOUT_S = 30.0
#: One fresh interpreter's compile or import read, which imports the hooks once.
CHILD_TIMEOUT_S = 120.0
GIT_TIMEOUT_S = 60.0
#: How often a long --calls run says how far it is.
PROGRESS_S = 30.0
#: The exit of a --calls run with a row whose decisions are not the ordinary ones.
DECISIONS_MIXED_EXIT = 3
#: The guard's records of a refusal or allow at its deadline.
BUDGET_EVENTS = ("pretooluse_blocked_time_budget", "pretooluse_failed_open_time_budget")

# The box lock, as tests/_box_lock.py names it (pinned equal by the test).
LOCK_KEY = "ESPALIER_BOX_LOCK"
HOLDER_KEY = "ESPALIER_BOX_LOCK_HOLDER"
WAIT_KEY = "ESPALIER_BOX_LOCK_WAIT_S"
DID_NOT_RUN_EXIT = 75
POLL_S = 0.25
REPORT_S = 30.0
EVERY_SLOT = "every"
#: The census's wait where ``WAIT_KEY`` is unset: under a Bash call's ten-minute
#: cap, so a run behind a seat's tier ends with ``DID_NOT_RUN_EXIT`` rather than
#: being cut by the cap or backgrounded into timing the box later (DEF-4056).
DEFAULT_WAIT_S = 540.0


def _json_safe() -> Any:
    """This checkout's ``tools/cc/_json_safe.py`` by path, under a private name
    (``scripts/host_check.py``'s way): its ``try_lock_file`` is the tiers' lock
    primitive and its ``run_bounded`` holds a timeout on Windows too."""
    spec = importlib.util.spec_from_file_location(
        "_json_safe_for_guard_cost_census", REPO_ROOT / "tools" / "cc" / "_json_safe.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_JSON_SAFE = _json_safe()
run_bounded = _JSON_SAFE.run_bounded


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


# -- Statistics --------------------------------------------------------------


def summarize(values: list[float]) -> dict:
    """``n``, median, the quartiles (``statistics.quantiles``' inclusive method,
    named so a default change cannot move it, and inside min and max at every
    n; one value is its own quartiles), min and max."""
    data = sorted(values)
    if not data:
        return {"n": 0, "median": None, "q1": None, "q3": None, "min": None, "max": None}
    if len(data) == 1:
        q1 = q3 = data[0]
    else:
        q1, _, q3 = statistics.quantiles(data, n=4, method="inclusive")
    return {"n": len(data), "median": statistics.median(data), "q1": q1, "q3": q3,
            "min": data[0], "max": data[-1]}


def load_average() -> list[float] | None:
    """The 1, 5 and 15 minute load averages, or None where the platform has none."""
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except (AttributeError, OSError):
        return None


def system_times() -> tuple[int, int] | None:
    """Windows: the CPU's (busy, total) time so far, from ``GetSystemTimes``
    (kernel time includes idle); None elsewhere or where it cannot be read."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None

        def value(ft: Any) -> int:
            return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

        i, k, u = value(idle), value(kernel), value(user)
        return (k - i) + u, k + u
    except (AttributeError, OSError, ValueError):
        return None


def cpu_busy(start: tuple[int, int] | None, end: tuple[int, int] | None) -> float | None:
    """The CPU's busy share between two :func:`system_times` reads."""
    if start is None or end is None or end[1] <= start[1]:
        return None
    return round((end[0] - start[0]) / (end[1] - start[1]), 3)


# -- The tree a run reads ----------------------------------------------------


def _git(*args: str, cwd: Path = REPO_ROOT, text: bool = True, timeout: float = GIT_TIMEOUT_S) -> Any:
    return run_bounded(["git", *args], cwd=str(cwd), capture_output=True, text=text, timeout=timeout,
                       **({"encoding": "utf-8", "errors": "replace"} if text else {}))


def _git_line(*args: str, cwd: Path = REPO_ROOT) -> tuple[int, str] | None:
    """``(returncode, stripped stdout)``, or None where git cannot be run."""
    try:
        proc = _git(*args, cwd=cwd)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return proc.returncode, proc.stdout.strip()


def checkout_tree(root: Path = REPO_ROOT) -> dict:
    """A checkout: its HEAD and branch, whether ``tools/cc`` holds uncommitted
    edits, and whether its ``tools/cc`` is the local ``origin/main``'s (no fetch:
    as of the ref's last fetch), None where a read cannot be made."""
    def out(*args: str) -> str | None:
        got = _git_line(*args, cwd=root)
        return got[1] if got and got[0] == 0 and got[1] else None

    status = _git_line("status", "--porcelain", "--", "tools/cc", cwd=root)
    edited = bool(status[1]) if status and status[0] == 0 else None
    origin = out("rev-parse", "--verify", "--quiet", "origin/main^{commit}")
    same: bool | None = None
    if origin is not None and edited is not None:
        diff = _git_line("diff", "--quiet", "origin/main", "HEAD", "--", "tools/cc", cwd=root)
        same = None if diff is None or diff[0] not in (0, 1) else (diff[0] == 0 and not edited)
    return {"kind": "checkout", "root": str(root), "head": out("rev-parse", "HEAD"),
            "branch": out("rev-parse", "--abbrev-ref", "HEAD"), "tools_cc_edited": edited,
            "origin_main": origin, "tools_cc_is_origin_main": same}


def archive_tree(at: str, dest: Path) -> dict:
    """``git archive <at> tools/cc`` extracted under ``dest``. Raises
    ``SystemExit`` with a reason where ``at`` names no commit here."""
    resolved = _git_line("rev-parse", "--verify", "--quiet", f"{at}^{{commit}}")
    if not resolved or resolved[0] != 0 or not resolved[1]:
        raise SystemExit(f"guard_cost_census: {at!r} names no commit in this clone; a commit only a closed "
                         "pull request reaches needs its ref fetched first (git fetch origin pull/<n>/head)")
    sha = resolved[1]
    archived = _git("archive", "--format=tar", sha, "tools/cc", text=False)
    if archived.returncode != 0:
        raise SystemExit(f"guard_cost_census: git archive {sha} tools/cc failed: "
                         + archived.stderr.decode("utf-8", "replace").strip()[:200])
    with tarfile.open(fileobj=io.BytesIO(archived.stdout)) as tar:
        if not hasattr(tarfile, "data_filter"):
            raise SystemExit("guard_cost_census: --at needs tarfile's extraction filters (Python 3.11.4 or later); "
                             "update the interpreter")
        tar.extractall(dest, filter="data")
    return {"kind": "archive", "at": at, "commit": sha, "root": str(dest)}


def hooks_of(root: Path) -> Path:
    return root / "tools" / "cc" / "hooks"


def pyc_state(source: Path) -> str:
    """``fresh``, ``stale`` or ``absent``: this interpreter's cached bytecode for
    ``source`` against the source's mtime and size (a hash-based cache reads
    ``hashed``)."""
    try:
        cached = Path(importlib.util.cache_from_source(str(source)))
        head = cached.read_bytes()[:16]
    except (NotImplementedError, OSError):
        return "absent"
    if len(head) < 16 or head[:4] != importlib.util.MAGIC_NUMBER:
        return "stale"
    if int.from_bytes(head[4:8], "little") & 1:
        return "hashed"
    try:
        st = source.stat()
    except OSError:
        return "absent"
    fresh = (int.from_bytes(head[8:12], "little") == int(st.st_mtime) & 0xFFFFFFFF
             and int.from_bytes(head[12:16], "little") == st.st_size & 0xFFFFFFFF)
    return "fresh" if fresh else "stale"


def cache_state(modules: list[str]) -> dict[str, str]:
    """:func:`pyc_state` of each module file a spawn imports."""
    return {Path(m).name: pyc_state(Path(m)) for m in modules}


# -- The children's environment ----------------------------------------------


def child_env(project: Path | None, audit_dir: Path, *, maintenance: bool = False) -> dict:
    """The environment every spawn gets: no maintenance mode (set where the
    kind is a ``_maintenance`` twin), no ``CLAUDE_*`` variable but the spawn's
    own project, and an audit folder of the run's own."""
    env = {k: v for k, v in os.environ.items()
           if k != "ESPALIER_MAINTENANCE_MODE" and not k.startswith("CLAUDE_")}
    if maintenance:
        env["ESPALIER_MAINTENANCE_MODE"] = "1"
    if project is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project)
    env["ESPALIER_AUDIT_DIR"] = str(audit_dir)
    return env


# -- --calls -----------------------------------------------------------------


#: The characters a path may hold and stay bare in either shell: letters,
#: digits and ``_ . / : - \``, so a POSIX temp root and a Windows drive path
#: keep the bytes the census has always timed. Anything else (a space, a comma
#: PowerShell reads as an array, a quote) is quoted.
_BARE_OPERAND_RE = re.compile(r"[A-Za-z0-9_./:\\-]+")
#: The characters PowerShell reads as a single quote inside a single-quoted
#: string, each escaped by doubling: the ASCII one and the two typographic ones.
_POWERSHELL_QUOTES = ("'", "‘", "’")


def shell_operand(path: str, *, powershell: bool = False) -> str:
    """``path`` as one shell operand: bare where every character is in
    ``_BARE_OPERAND_RE`` (so the timed commands stay byte for byte what the
    census has always timed, on POSIX and Windows roots alike), else quoted
    for the shell named, so a project root holding a space (the perturbed CI
    cell's pytest root) is still one operand the hook judges."""
    if _BARE_OPERAND_RE.fullmatch(path):
        return path
    if not powershell:
        return shlex.quote(path)
    for quote in _POWERSHELL_QUOTES:
        path = path.replace(quote, quote * 2)
    return f"'{path}'"


def payload(kind: str, project: Path) -> dict:
    """The PreToolUse payload of one call kind, naming a file in ``project``."""
    notes = str(project / "notes.txt")
    base = {"session_id": "guard-cost-census", "hook_event_name": "PreToolUse", "cwd": str(project),
            "transcript_path": str(project / "transcript.jsonl"), "permission_mode": "default"}
    if kind == "read":
        base.update(tool_name="Read", tool_input={"file_path": notes})
    elif kind in COMMANDS:
        tool, command = COMMANDS[kind]
        base.update(tool_name=tool, tool_input={"command": command, "description": "List files"})
    elif kind == "mcp_read":
        base.update(tool_name="mcp__filesystem__read_file", tool_input={"path": notes})
    elif kind == "mcp_write":
        base.update(tool_name="mcp__filesystem__write_file", tool_input={"path": notes, "content": "y\n"})
    elif kind in ("write", "write_maintenance"):
        base.update(tool_name="Write", tool_input={"file_path": notes, "content": "y\n"})
    elif kind in ("edit", "edit_maintenance"):
        base.update(tool_name="Edit", tool_input={"file_path": notes, "old_string": "x", "new_string": "y"})
    elif kind in ("bash_seat", "bash_seat_maintenance"):
        base.update(tool_name="Bash", tool_input={"command": f"ls -la {shell_operand(notes)}", "description": "List files"})
    elif kind in ("powershell_seat", "powershell_seat_maintenance"):
        base.update(tool_name="PowerShell",
                    tool_input={"command": f"Get-ChildItem {shell_operand(notes, powershell=True)}",
                                "description": "List files"})
    else:
        raise ValueError(f"no payload for kind {kind!r}")
    return base


#: How a deny opens that the guard gave a call it never judged because it
#: failed itself: its crash guard's, its runner's, its refusal to start
#: (``bench/run_benchmark.py::CRASH_HEADS``, the release bench's reader).
_CRASH_HEADS = ("write_guard internal error", "write_guard cannot start", "write_guard cannot run here")


def decision(kind: str, returncode: int, stdout: str) -> str:
    """What the spawn answered: the control's exit; for the guard, ``allow``
    (exit 0, no decision), ``deny`` or ``ask``, ``deny (time budget)`` for a
    refusal at its deadline, ``deny (crash)`` for a deny it gave as it failed
    itself (DEF-2096: no judgment's cost either), ``nudge <CP-id>`` for a
    speed-bump checkpoint, ``block`` for exit 2, ``error`` otherwise."""
    if kind == "control":
        return f"exit {returncode}"
    if returncode == 2:
        return "block (exit 2)"
    if returncode != 0:
        return f"error (exit {returncode})"
    text = stdout.strip()
    if not text:
        return "allow"
    try:
        doc = json.loads(text)
    except ValueError:
        return "unreadable output"
    if not isinstance(doc, dict):
        return "unreadable output"
    out = doc.get("hookSpecificOutput")
    out = out if isinstance(out, dict) else {}
    verdict = out.get("permissionDecision")
    if verdict in ("deny", "ask"):
        reason = str(out.get("permissionDecisionReason", ""))
        if reason.startswith(_CRASH_HEADS):
            return f"{verdict} (crash)"
        if "time budget" in reason.lower():
            return f"{verdict} (time budget)"
        cp = next((w.strip(".,:;()[]`'\"") for w in reason.split() if w.strip("[(`'\"").startswith("CP-")), None)
        return f"nudge {cp}" if cp else str(verdict)
    return "allow (with context)" if out.get("additionalContext") else "allow"


def _new_project(base: Path) -> Path:
    project = Path(tempfile.mkdtemp(prefix="p-", dir=base))
    (project / "notes.txt").write_text("x\n", encoding="utf-8")
    return project


def _new_repo_project(base: Path) -> Path:
    """A repository with one commit and a linked worktree under its
    ``.claude/worktrees/``, the worktree returned as the project: a worker
    seat's layout. The worktree's folder is named after the repository's, so
    each spawn's project (and its audit log) has a name of its own."""
    repo = Path(tempfile.mkdtemp(prefix="r-", dir=base))
    (repo / "notes.txt").write_text("x\n", encoding="utf-8")
    for args in (("init", "-q"), ("config", "user.email", "census@example.invalid"), ("config", "user.name", "census"),
                 ("config", "commit.gpgsign", "false"), ("add", "-A"), ("commit", "-q", "-m", "census seed")):
        _git(*args, cwd=repo).check_returncode()
    worktree = repo / ".claude" / "worktrees" / f"w{repo.name}"
    worktree.parent.mkdir(parents=True)
    _git("worktree", "add", "-q", str(worktree), "-b", "census", cwd=repo).check_returncode()
    return worktree


def budget_records(audit: Path, kind_of: dict[str, str]) -> dict[str, int]:
    """The guard's deadline records in the run's audit folder, per kind: each
    spawn's project has its own name, which is its audit file's prefix."""
    counts: dict[str, int] = {}
    # The guard names the file by tools/cc/hooks/_integrity.py::_safe_slug's rule.
    slug_of = {"".join(c if c.isascii() and (c.isalnum() or c in "_.-") else "_" for c in name).strip("_"): k
               for name, k in kind_of.items()}
    for log in sorted(audit.glob("*.log")):
        kind = next((k for slug, k in slug_of.items() if log.name.startswith(slug + "-")), "unknown")
        try:
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line).get("event_type")
            except (ValueError, AttributeError):
                continue
            if event in BUDGET_EVENTS:
                counts[kind] = counts.get(kind, 0) + 1
    return counts


def time_calls(root: Path, n: int, kinds: tuple[str, ...], scratch: Path,
               *, shuffle: Callable[[list], None] = random.shuffle, stream: TextIO | None = None) -> dict:
    """N spawns of each kind, in ``shuffle``'s order, each in a project of its own."""
    stream = stream if stream is not None else sys.stderr
    hook = hooks_of(root) / "write_guard.py"
    audit = scratch / "audit"
    audit.mkdir(exist_ok=True)
    order = [k for k in kinds for _ in range(n)]
    shuffle(order)
    times: dict[str, list[float]] = {k: [] for k in kinds}
    seen: dict[str, dict[str, int]] = {k: {} for k in kinds}
    kind_of: dict[str, str] = {}
    rejected = False
    last = time.monotonic()
    for done, kind in enumerate(order):
        if time.monotonic() - last >= PROGRESS_S:
            print(f"guard_cost_census: {done} of {len(order)} spawns", file=stream, flush=True)
            last = time.monotonic()
        project = _new_repo_project(scratch) if kind in REPO_KINDS else _new_project(scratch)
        kind_of[project.name] = kind
        if kind == "control":
            argv = [sys.executable, "-B", "-c", "pass"]
            data = b""
        else:
            argv = [sys.executable, "-B", str(hook)]
            data = json.dumps(payload(kind, project)).encode("utf-8")
        started = time.perf_counter()
        try:
            proc = run_bounded(argv, input=data, capture_output=True, cwd=str(project),
                               env=child_env(project, audit, maintenance=kind in MAINTENANCE_KINDS),
                               timeout=SPAWN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            said = f"timed out ({SPAWN_TIMEOUT_S:g} s)"
        else:
            times[kind].append((time.perf_counter() - started) * 1000.0)
            said = decision(kind, proc.returncode, proc.stdout.decode("utf-8", "replace"))
            rejected = rejected or b"[_audit_dir] WARN" in proc.stderr
        seen[kind][said] = seen[kind].get(said, 0) + 1
    budget = budget_records(audit, kind_of)
    rows = {k: {**summarize(times[k]), "decisions": seen[k], "budget_records": budget.get(k, 0),
                "as_expected": set(seen[k]) == {EXPECTED_DECISION[k]}} for k in kinds}
    return {"kinds": rows, "audit_dir_rejected": rejected}


# -- --compile and --import-time ---------------------------------------------

#: ``tests/_first_use_patterns.py::first_use_patterns``, carried: the census runs
#: in a fresh interpreter over a tree that may hold no ``tests`` folder, and a
#: script imports nothing from ``tests/``. ``{"<accessor>()": pattern}`` for each
#: function ``module`` defines behind ``functools.lru_cache`` or
#: ``functools.cache`` that takes no argument and whose body names ``compile``,
#: each called once; only a compiled pattern it returns is kept. And
#: ``{"<name>": pattern}`` for each of the module's own first-use objects
#: (``module._FirstUse``, DEF-2084), compiled by its own first read, so the
#: recorder sees the hooks folder's frame compile it.
#: ``tests/test_guard_cost_census.py`` pins it equal to the helper both ways and
#: its function body equal to the helper's, statement for statement (the
#: docstring and annotations apart).
FIRST_USE_RULE = r'''
def first_use_patterns(module):
    found = {}
    first_use = getattr(module, "_FirstUse", None)
    for name, obj in vars(module).items():
        if first_use is not None and type(obj) is first_use:
            found[name] = obj.search.__self__
            continue
        wrapped = getattr(obj, "__wrapped__", None)
        code = getattr(wrapped, "__code__", None)
        if not hasattr(obj, "cache_info") or code is None:
            continue
        if getattr(wrapped, "__module__", None) != module.__name__:
            continue
        if code.co_argcount or code.co_kwonlyargcount or "compile" not in code.co_names:
            continue
        value = obj()
        if isinstance(value, re.Pattern):
            found[f"{name}()"] = value
    return found
'''
#: The modules whose first-use accessors the child calls: the guard's pattern
#: modules, as ``tools/cc/hooks/_reinject.py::_GUARD_PATTERN_MODULES`` names the
#: roster the anchoring contract walks (pinned equal by the census's tests). A
#: module of them the tree does not hold, or the imports never load, is skipped.
FIRST_USE_MODULES = ("_bash_patterns", "_speedbump", "write_guard")

#: Run in a fresh ``-I -B`` interpreter with the hooks folder as its argument:
#: the recorder is in place before the first hook module imports, and a compile
#: whose call stack passes through the hooks folder is the hooks' own.
COMPILE_CHILD = r'''
import json, os, re, sys
''' + FIRST_USE_RULE + f"FIRST_USE_MODULES = {FIRST_USE_MODULES!r}\n" + r'''
hooks = sys.argv[1]
sys.path.insert(0, hooks)
inside = os.path.join(hooks, "")
seen = {}
ours = set()
original = re._compile
def record(pattern, flags):
    text = pattern if isinstance(pattern, (str, bytes)) else getattr(pattern, "pattern", repr(pattern))
    key = (text, int(flags))
    seen[key] = seen.get(key, 0) + 1
    frame = sys._getframe(1)
    while frame is not None:
        if frame.f_code.co_filename.startswith(inside):
            ours.add(key)
            break
        frame = frame.f_back
    return original(pattern, flags)
re._compile = record
re.purge()
import _bash_patterns
import _speedbump
loader_ran = False
loaded = set()
if not os.path.isfile(os.path.join(hooks, "write_guard.py")):
    method = "the two pattern modules imported; this tree has no write_guard.py"
else:
    import write_guard
    loader = getattr(write_guard, "_load_the_pattern_path", None)
    if loader is None:
        method = "imports alone: this tree's write_guard has no _load_the_pattern_path (before DEF-946)"
    else:
        before = set(ours)
        loader()
        loader_ran = True
        loaded = ours - before
        method = "imports and write_guard._load_the_pattern_path"
imported = dict(seen)
path = set(ours)
first_use = {}
for module in [sys.modules.get(name) for name in FIRST_USE_MODULES]:
    if module is not None:
        for name, value in first_use_patterns(module).items():
            first_use[module.__name__ + "." + name] = value
re._compile = original
fragment = getattr(_bash_patterns, "_CMD_POS_NO_VERB", None)
cmd_pos = getattr(_bash_patterns, "_CMD_POS", None)
found = isinstance(fragment, str) and bool(fragment)
texts = [k[0] for k in imported if isinstance(k[0], str)]
embedding = [k[0] for k in seen if isinstance(k[0], str) and found and fragment in k[0]]
tools_cc = os.path.dirname(os.path.abspath(hooks))
modules = sorted({os.path.abspath(m.__file__) for m in list(sys.modules.values())
                  if isinstance(getattr(m, "__file__", None), str)
                  and os.path.abspath(m.__file__).startswith(os.path.join(tools_cc, ""))
                  and os.path.basename(m.__file__) != "write_guard.py"})
print(json.dumps({
    "method": method,
    "loader_ran": loader_ran,
    "fragment_found": found,
    "patterns": len(imported),
    "compiled_chars": sum(len(t) for t in texts),
    "hooks_patterns": len(path),
    "hooks_chars": sum(len(k[0]) for k in path if isinstance(k[0], str)),
    "first_use_patterns": len(first_use),
    "first_use_chars": sum(len(p.pattern) for p in first_use.values() if isinstance(p.pattern, str)),
    "first_use_names": sorted(first_use),
    "summed_patterns": len(ours),
    "summed_chars": sum(len(k[0]) for k in ours if isinstance(k[0], str)),
    "loader_patterns": len(loaded),
    "loader_chars": sum(len(k[0]) for k in loaded if isinstance(k[0], str)),
    "fragment_len": len(fragment) if found else None,
    "cmd_pos_len": len(cmd_pos) if isinstance(cmd_pos, str) else None,
    "embedding_patterns": len(embedding),
    "embedding_chars": sum(len(t) for t in embedding),
    "modules": modules,
}))
'''

#: Run in a fresh interpreter with the hooks folder as its argument: the two
#: pattern modules' import, timed in that interpreter.
IMPORT_CHILD = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
t0 = time.perf_counter()
import _bash_patterns
t1 = time.perf_counter()
import _speedbump
t2 = time.perf_counter()
print(json.dumps({"bash_patterns": (t1 - t0) * 1000.0, "speedbump": (t2 - t1) * 1000.0}))
'''


def _child(code: str, hooks: Path, scratch: Path, *flags: str) -> dict:
    """One fresh interpreter running ``code`` over ``hooks``; its last stdout
    line as JSON. Raises ``SystemExit`` naming the child's error otherwise."""
    try:
        proc = run_bounded([sys.executable, *flags, "-c", code, str(hooks)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=str(scratch),
                           env=child_env(None, scratch / "audit"), timeout=CHILD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"guard_cost_census: the child over {hooks} ran past {CHILD_TIMEOUT_S:g} s") from None
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    tail = " | ".join(proc.stderr.strip().splitlines()[-3:])
    if proc.returncode != 0 or not lines:
        raise SystemExit(_ascii(f"guard_cost_census: the child over {hooks} exited {proc.returncode}: {tail}"))
    try:
        return json.loads(lines[-1])
    except ValueError:
        raise SystemExit(_ascii(f"guard_cost_census: the child over {hooks} printed no figure: "
                                f"{lines[-1][:120]}")) from None


def compile_counts(hooks: Path, scratch: Path) -> dict:
    return _child(COMPILE_CHILD, hooks, scratch, "-I", "-B")


def import_times(hooks: Path, rounds: int, scratch: Path, *, cold: bool = False) -> dict:
    """``rounds`` fresh interpreters. Warm (the default): a first run writes the
    whole import's bytecode into a private ``pycache_prefix`` and every round
    reads it. Cold: every round gets an empty prefix of its own and ``-B``."""
    per: dict[str, list[float]] = {"bash_patterns": [], "speedbump": [], "both": []}
    warm = scratch / "pycache-warm"
    if not cold:
        warm.mkdir()
        _child(IMPORT_CHILD, hooks, scratch, "-I", "-X", f"pycache_prefix={warm}")
    for i in range(rounds):
        prefix = warm
        if cold:
            prefix = scratch / f"pycache-{i}"
            prefix.mkdir()
        got = _child(IMPORT_CHILD, hooks, scratch, "-I", "-B", "-X", f"pycache_prefix={prefix}")
        per["bash_patterns"].append(got["bash_patterns"])
        per["speedbump"].append(got["speedbump"])
        per["both"].append(got["bash_patterns"] + got["speedbump"])
    return {k: summarize(v) for k, v in per.items()}


# -- The box lock (tests/_box_lock.py's holder, stdlib only) -----------------


def holder_alive(pid: int) -> bool:
    """Whether ``pid`` is a live process (``tests/_box_lock.py::holder_alive``)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_record(path: Path) -> dict | None:
    """The holder record in the lock file, or None (empty, missing, not one object)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    if not text.strip():
        return None
    try:
        record = json.loads(text)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def inside_holder(record: dict | None) -> bool:
    """The inherited pair: ``ESPALIER_BOX_LOCK_HOLDER`` names the record's pid
    and that pid is alive (``tests/_box_lock.py::inside_holder``)."""
    env_pid = os.environ.get(HOLDER_KEY)
    if not env_pid or not record:
        return False
    try:
        pid = int(env_pid)
    except ValueError:
        return False
    return str(record.get("pid")) == env_pid and holder_alive(pid)


def pair_paths(lock: Path, slot_paths: list[Path], most: int) -> list[Path]:
    """The slot files the inherited pair is read in (``tests/_box_lock.py::pair_paths``):
    the count's, then each later ``<lock>.slot<k>`` up to ``most`` that is there."""
    extra = [Path(f"{lock}.slot{k}") for k in range(len(slot_paths) + 1, most + 1)]
    return [*slot_paths, *(p for p in extra if p.is_file())]


def home_default() -> str | None:
    try:
        home = Path.home()
    except RuntimeError:
        return None
    if not home.is_absolute() or home.parent == home:
        return None
    return str(home / ".espalier" / "espalier-box.lock")


def current_path(path: str, *, stream: TextIO | None = None) -> str:
    """``path``, unless it is the launcher's old default under the temp folder,
    which is read as the home default (``tests/_box_lock.py::current_path``)."""
    old = os.path.join(tempfile.gettempdir(), "espalier-box.lock")
    new = home_default()
    if new is None or os.path.normcase(os.path.abspath(path)) != os.path.normcase(os.path.abspath(old)):
        return path
    print(f"box lock: {path} is the launcher's old default; this run locks {new} (a relaunched seat drops this line)",
          file=stream if stream is not None else sys.stderr, flush=True)
    return new


def wait_bound(raw: str | None, *, stream: TextIO | None = None) -> float | None:
    """``ESPALIER_BOX_LOCK_WAIT_S`` in seconds; unset, blank or unusable is None."""
    if raw is None or not raw.strip():
        return None
    try:
        bound = float(raw)
    except ValueError:
        bound = math.nan
    if math.isfinite(bound) and bound >= 0:
        return bound
    print(f"box lock: {WAIT_KEY}={_ascii(raw)[:40]} is not a number of seconds at or above 0; this run waits unbounded",
          file=stream if stream is not None else sys.stderr, flush=True)
    return None


def _now_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_record() -> dict:
    """This run's holder record, ``tests/_box_lock.py::build_record``'s keys: seat,
    lane and checkout from git (two seconds each, ``?`` on failure), pid, the
    start (stamped again when the lock is taken), the argv head."""
    def git(*args: str) -> str:
        try:
            proc = _git(*args, timeout=2.0)
        except (OSError, ValueError, subprocess.SubprocessError):
            return "?"
        return (proc.stdout.strip() or "?") if proc.returncode == 0 else "?"

    return {"seat": git("config", "espalier.machine"), "lane": git("rev-parse", "--abbrev-ref", "HEAD"),
            "checkout": git("rev-parse", "--show-toplevel"), "pid": os.getpid(), "started": _now_stamp(),
            "argv": [os.path.basename(str(sys.argv[0])), *[str(a) for a in sys.argv[1:9]]] if sys.argv else []}


def log_outcome(lock: Path, outcome: str, run: dict | None, holder: dict | None = None, waited_s: float = 0.0,
                *, why: str = "", held_s: float | None = None, slot: int | str | None = None,
                slots: int | None = None, stream: TextIO | None = None) -> None:
    """One JSON line in ``<lock path>.log``, ``tests/_box_lock.py::log_outcome``'s shape
    (a ``released`` line's ``held_s`` included, and every line's ``slot`` and ``slots``)."""
    end = datetime.now(timezone.utc)
    span = held_s if held_s is not None else waited_s
    start = datetime.fromtimestamp(end.timestamp() - span, tz=timezone.utc)
    line: dict = {"outcome": outcome,
                  "run": {k: (run or {}).get(k) for k in ("seat", "lane", "pid")},
                  "holder": {k: (holder or {}).get(k) for k in ("seat", "lane", "pid")},
                  "start": start.isoformat(timespec="seconds"), "end": end.isoformat(timespec="seconds"),
                  "waited_s": round(waited_s, 3), "slot": slot, "slots": slots}
    if held_s is not None:
        line["held_s"] = round(held_s, 3)
    if why:
        line["why"] = why
    try:
        with open(f"{lock}.log", "a", encoding="utf-8") as log:
            log.write(json.dumps(line) + "\n")
    except (OSError, ValueError) as exc:
        print(f"box lock: the log could not be written ({exc.__class__.__name__})",
              file=stream if stream is not None else sys.stderr, flush=True)


def _who(record: dict | None) -> str:
    if not record:
        return "a holder that left no record"
    return f"{record.get('seat') or '?'} {record.get('lane') or '?'} (pid {record.get('pid')})"


def waiting_line(record: dict | None, waited_s: float) -> str:
    """What a waiter prints: the holder's seat, lane, pid and how long it has
    held (its record's start, else this wait), then the head of its argv
    (``tests/_box_lock.py::waiting_line`` under its ceiling; the census leaves
    the past-the-ceiling advice to the tiers)."""
    held_min = int(waited_s // 60)
    if record and "pid" in record:
        try:
            pid: int | None = int(record.get("pid"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pid = None
        started = record.get("started")
        if isinstance(started, str):
            try:
                since = datetime.fromisoformat(started.replace("Z", "+00:00"))
                held_min = int((datetime.now(timezone.utc) - since).total_seconds() // 60)
            except ValueError:
                pass
        shown = pid if pid is not None else "?"
        held = "taking every slot" if record.get("draining") else f"held {held_min} min"
        who = f"{record.get('seat') or '?'} {record.get('lane') or '?'} (pid {shown}, {held})"
    else:
        who = "no holder record"
    argv = [str(a) for a in ((record or {}).get("argv") or [])]
    if argv:
        argv[0] = os.path.basename(argv[0])
    head = " ".join(argv)[:80]
    return _ascii(f"box lock: waiting on {who}" + (f": {head}" if head else ""))


class BoxLock:
    """The census's hold on the box lock for the length of its timed work:
    every slot of the box, taken in order and each kept as it comes, as the
    plugin's serial line takes them (``tests/_box_lock.py::BoxLock`` with
    ``every``), its record in each slot it holds saying so while it waits for
    the rest."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream if stream is not None else sys.stderr
        self.path: Path | None = None
        self.slot_paths: list[Path] = []
        self.handles: dict[int, TextIO] = {}  # each slot's open handle by its number (1 is the lock itself)
        self.taken: list[int] = []  # the slots held, always 1 to k
        self.record: dict | None = None
        self.held = False  # every slot is held
        self.outcome = "unguarded"
        self.why = f"{LOCK_KEY} is not set"
        self.holder_seen: dict | None = None
        self.waited_s = 0.0
        self.taken_at: float | None = None  # the take's time.monotonic(), set once its acquire line is logged

    @property
    def fh(self) -> TextIO | None:
        """The first open handle (slot 1's), None once every one is closed."""
        return next(iter(self.handles.values()), None)

    def acquire(self) -> None:
        raw = os.environ.get(LOCK_KEY)
        if not raw:
            return
        try:
            self.path = Path(current_path(raw, stream=self.stream))
            self.record = build_record()
            self.path.parent.mkdir(exist_ok=True)
            paths, note = _JSON_SAFE.box_lock_slots(str(self.path))
            if note:
                print(note, file=self.stream, flush=True)
            self.slot_paths = [Path(p) for p in paths]
            for number, slot in enumerate(self.slot_paths, 1):
                self.handles[number] = open(slot, "a+", encoding="utf-8")
            self._acquire()
        except SystemExit:
            self.release()
            raise
        except Exception as exc:  # noqa: BLE001 -- a lock that cannot be taken costs the run its guard, never the run
            self.release()
            self.outcome, self.why = "unguarded", _ascii(f"{type(exc).__name__}: {exc}")
            print(f"box lock: not taken ({self.why}); this run is unguarded", file=self.stream, flush=True)
            if self.path is not None:
                log_outcome(self.path, "unguarded", self.record or {"pid": os.getpid()}, why=self.why,
                            stream=self.stream)

    def _write(self, number: int, *, draining: bool = False) -> None:
        assert self.record is not None
        fh = self.handles[number]
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps({**self.record, "slot": EVERY_SLOT, **({"draining": True} if draining else {})}))
        fh.flush()

    def _acquire(self) -> None:
        assert self.path is not None and self.record is not None
        started = time.monotonic()
        bound = wait_bound(os.environ.get(WAIT_KEY), stream=self.stream)
        if bound is None:
            bound = DEFAULT_WAIT_S
        last_report: float | None = None
        count = len(self.slot_paths)
        while True:
            if not self.taken:  # the inherited pair before any slot, as the plugin reads it
                for number, slot in enumerate(pair_paths(self.path, self.slot_paths,
                                                         _JSON_SAFE.BOX_LOCK_MAX_SLOTS), 1):
                    record = read_record(slot)
                    if inside_holder(record):
                        assert record is not None
                        self.holder_seen = record
                        self.release()
                        self.outcome, self.why = "inside", ""
                        log_outcome(self.path, "inside", self.record, record, slot=record.get("slot", number),
                                    slots=count, stream=self.stream)
                        return
            refused: dict | None = None
            blocked = False
            for number in range(len(self.taken) + 1, count + 1):
                if not _JSON_SAFE.try_lock_file(self.handles[number]):
                    refused, blocked = read_record(self.slot_paths[number - 1]), True
                    break
                self.taken.append(number)
                if len(self.taken) < count:
                    self.record["started"] = _now_stamp()
                    self._write(number, draining=True)
            if not blocked:
                self.held = True
                taken_at = time.monotonic()
                self.record["started"] = _now_stamp()
                for number in self.taken:
                    self._write(number)
                if last_report is not None:
                    self.waited_s = time.monotonic() - started
                self.outcome, self.why = ("waited", "") if last_report is not None else ("taken", "")
                log_outcome(self.path, self.outcome, self.record, self.holder_seen, self.waited_s,
                            slot=EVERY_SLOT, slots=count, stream=self.stream)
                self.taken_at = taken_at  # once the acquire line is down, as the plugin's
                return
            self.holder_seen = refused or self.holder_seen
            now = time.monotonic()
            if last_report is None or now - last_report >= REPORT_S:
                print(waiting_line(refused, now - started), file=self.stream, flush=True)
                if last_report is None:
                    print(f"box lock: the census waits at most {bound:g} s ({WAIT_KEY} sets it)",
                          file=self.stream, flush=True)
                last_report = now
            if time.monotonic() - started >= bound:
                waited = time.monotonic() - started
                log_outcome(self.path, "gave_up", self.record, self.holder_seen, waited,
                            why=f"{WAIT_KEY}={bound:g}", slots=count, stream=self.stream)
                self.release()
                print(_ascii(f"box lock: did not run: waited {waited:.0f} s behind {_who(self.holder_seen)}, "
                             f"past {WAIT_KEY}={bound:g}; nothing was timed"), file=self.stream, flush=True)
                raise SystemExit(DID_NOT_RUN_EXIT)
            time.sleep(POLL_S)

    def _close(self) -> None:
        for fh in self.handles.values():
            try:
                fh.close()
            except OSError:  # one handle's close never keeps the others' slots
                pass
        self.handles.clear()
        self.taken.clear()

    def release(self) -> None:
        """Clear the record in every slot held, log the hold's ``released``
        line while it still holds, then unlock and close every handle:
        ``tests/_box_lock.py::BoxLock.release``'s order, so the log's lines pair
        in file order whichever of the two took the lock. A part-hold (a wait
        that gave up, a take that failed) is cleared and unlocked, never
        logged."""
        if not self.handles:
            return
        try:
            for number in self.taken:
                fh = self.handles[number]
                fh.seek(0)
                fh.truncate()
                fh.flush()
            if self.held and self.path is not None and self.taken_at is not None:
                log_outcome(self.path, "released", self.record, held_s=time.monotonic() - self.taken_at,
                            slot=EVERY_SLOT, slots=len(self.slot_paths), stream=self.stream)
            for number in self.taken:
                _JSON_SAFE.unlock_file(self.handles[number])
        finally:
            self._close()
            self.held = False

    def summary(self) -> dict:
        out: dict = {"outcome": self.outcome, "path": str(self.path) if self.path else None}
        if self.why:
            out["why"] = self.why
        if self.holder_seen:
            out["holder"] = {k: self.holder_seen.get(k) for k in ("seat", "lane", "pid")}
        if self.waited_s:
            out["waited_s"] = round(self.waited_s, 3)
        return out


# -- Rendering ---------------------------------------------------------------


def _ms(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def _load_text(load: dict) -> str:
    if load.get("cpu_busy") is not None:
        return f"cpu busy {load['cpu_busy']:.3f} over the run (this platform has no load average)"
    if load.get("start") is None:
        return "n/a (no load average on this platform)"
    return (" ".join(f"{x:.2f}" for x in load["start"]) + " at the start, "
            + " ".join(f"{x:.2f}" for x in (load.get("end") or [])) + " at the end")


def _tree_text(tree: dict) -> str:
    if tree["kind"] == "checkout":
        edited = {True: ", tools/cc edited", False: "", None: ", tools/cc state unread"}[tree["tools_cc_edited"]]
        main = {True: "origin/main's", False: f"NOT origin/main's ({(tree['origin_main'] or '?')[:12]})",
                None: "unread against origin/main"}[tree["tools_cc_is_origin_main"]]
        return (f"checkout {tree['root']} at {(tree['head'] or '?')[:12]} on {tree['branch'] or '?'}"
                f"{edited}; tools/cc {main}")
    if tree["kind"] == "archive":
        return f"git archive of {tree['commit'][:12]} ({tree['at']}) tools/cc"
    return f"folder {tree['root']}"


def tags(result: dict) -> list[str]:
    """What every figure of the run carries beside it."""
    out: list[str] = []
    lock = result.get("lock", {}).get("outcome")
    if lock == "unguarded":
        out.append("unguarded")
    elif lock == "inside":
        out.append("inside a holder")
    if result["tree"].get("tools_cc_is_origin_main") is False:
        out.append("not origin/main's tools/cc")
    if "stale" in result.get("bytecode_cache", {}).values():
        out.append("cache stale")
    return out


def render(result: dict) -> str:
    lines = [f"guard cost census -- {result['mode']}",
             f"tree:    {_tree_text(result['tree'])}",
             f"python:  {result['python']['version']} ({result['python']['executable']})"]
    if result["mode"] == "compile":
        c = result["compile"]
        lines += [f"method:  {c['method']}",
                  f"patterns at import and load:       {c['patterns']} ({c['hooks_patterns']} from the hooks folder)",
                  f"characters at import and load:     {c['compiled_chars']} ({c['hooks_chars']} from the hooks folder)",
                  f"first compiled by the loader:      {c['loader_patterns']} patterns, {c['loader_chars']} characters",
                  f"compiled on first use (all kinds): {c['first_use_patterns']} patterns, {c['first_use_chars']} characters",
                  f"path plus first use (distinct):    {c['summed_patterns']} patterns, {c['summed_chars']} characters",
                  f"_CMD_POS_NO_VERB length:           {c['fragment_len']}",
                  f"_CMD_POS length:                   {c['cmd_pos_len']}",
                  f"patterns embedding the fragment:   {c['embedding_patterns']}",
                  f"characters in those patterns:      {c['embedding_chars']}"]
        return _ascii("\n".join(lines))
    lock = result["lock"]
    held = lock["outcome"] + (f" ({lock['why']})" if lock.get("why") else "")
    if lock.get("holder"):
        h = lock["holder"]
        held += f" ({h.get('seat')} {h.get('lane')} pid {h.get('pid')})"
    lines += [f"lock:    {held}", f"load:    {_load_text(result['load'])}"]
    run_tags = tags(result)
    if result["mode"] == "calls":
        cache = result["bytecode_cache"]
        counts = {s: sum(1 for v in cache.values() if v == s) for s in sorted(set(cache.values()))}
        width = max([15, *map(len, result["kinds"])])
        project = "project: an empty temp folder a spawn (no settings file, no espalier.toml)"
        if REPO_KINDS & set(result["kinds"]):
            project += "; for the seat kinds, a linked worktree of a fresh repository"
        lines += [project,
                  "cache:   " + (", ".join(f"{n} {s}" for s, n in counts.items()) or "no module read")
                  + " (the modules a spawn imports)",
                  f"n={result['n']} a kind, shuffled, ms per spawn; a guard call starts two interpreters, the control one",
                  f"{'kind':{width}} {'n':>3} {'median':>8} {'q1-q3':>17} {'min':>8} {'max':>8}  decisions"]
        for kind, row in result["kinds"].items():
            seen = ", ".join(f"{d} x{c}" for d, c in sorted(row["decisions"].items()))
            if row["budget_records"]:
                seen += f"; {row['budget_records']} budget record(s)"
            row_tags = run_tags + ([] if row["as_expected"] else ["decisions mixed"])
            iqr = f"{_ms(row['q1'])}-{_ms(row['q3'])}"
            lines.append(f"{kind:{width}} {row['n']:>3} {_ms(row['median']):>8} {iqr:>17} {_ms(row['min']):>8} "
                         f"{_ms(row['max']):>8}  {seen}" + (f"  [{', '.join(row_tags)}]" if row_tags else ""))
        if result["audit_dir_rejected"]:
            lines.append("note:    the guard rejected the run's audit folder, so its records went to ~/.espalier/audit")
    else:
        lines += [f"rounds={result['rounds']}, a fresh interpreter each, "
                  + ("no bytecode cache (the source compile is in the figure)" if result["cold"]
                     else "reading a warmed private bytecode cache") + ", ms",
                  f"{'module':14} {'median':>8} {'q1-q3':>17} {'min':>8} {'max':>8}"]
        for name, row in result["import_time"].items():
            iqr = f"{_ms(row['q1'])}-{_ms(row['q3'])}"
            lines.append(f"{name:14} {_ms(row['median']):>8} {iqr:>17} {_ms(row['min']):>8} {_ms(row['max']):>8}"
                         + (f"  [{', '.join(run_tags)}]" if run_tags else ""))
    return _ascii("\n".join(lines))


# -- Main --------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="What write_guard costs a call, measured.")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--calls", type=int, metavar="N", help="time N spawns of each call kind")
    mode.add_argument("--compile", action="store_true", help="the compile proxy, from a fresh interpreter")
    mode.add_argument("--import-time", action="store_true", help="time the two pattern modules' import")
    p.add_argument("--rounds", type=int, help="--import-time: fresh interpreters (default 10)")
    p.add_argument("--cold", action="store_true", help="--import-time: no bytecode cache in any round")
    p.add_argument("--kind", action="append", choices=KINDS[1:], help="--calls: only this kind (repeatable; the control always runs)")
    where = p.add_mutually_exclusive_group()
    where.add_argument("--at", metavar="SHA", help="read git archive SHA tools/cc instead of this checkout")
    where.add_argument("--root", type=Path, help="read DIR/tools/cc instead of this checkout")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    return p


def _refusal(args: argparse.Namespace) -> str | None:
    if args.calls is not None and args.calls < 1:
        return "--calls takes 1 or more"
    if args.kind and args.calls is None:
        return "--kind goes with --calls"
    if (args.rounds is not None or args.cold) and not args.import_time:
        return "--rounds and --cold go with --import-time"
    if args.rounds is not None and args.rounds < 1:
        return "--rounds takes 1 or more"
    if args.at is not None and not args.at.strip():
        return "--at takes a commit"
    return None


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    refusal = _refusal(args)
    if refusal:
        print(f"guard_cost_census: {refusal}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="guard-cost-census-", ignore_cleanup_errors=True) as tmp:
        # Resolved: on macOS the temp folder is under /var, a link to /private/var,
        # and a payload path spelled through the link sits outside the root the
        # guard resolves, which no real project's own path does.
        scratch = Path(tmp).resolve()
        (scratch / "audit").mkdir()
        if args.at is not None:
            tree, root = archive_tree(args.at, scratch / "tree"), scratch / "tree"
        elif args.root:
            root = args.root.resolve()
            tree = {"kind": "folder", "root": str(root)}
        else:
            root, tree = REPO_ROOT, checkout_tree(REPO_ROOT)
        hooks = hooks_of(root)
        if not (hooks / "_bash_patterns.py").is_file():
            print(f"guard_cost_census: {hooks} holds no _bash_patterns.py", file=sys.stderr)
            return 2
        result: dict = {"tree": tree, "python": {"version": platform.python_version(),
                                                  "executable": sys.executable}}
        status = 0
        if args.compile:
            counts = compile_counts(hooks, scratch)
            if not counts["patterns"]:
                print("guard_cost_census: the pattern path recorded no pattern at all: the loader loaded "
                      "nothing, which is no figure", file=sys.stderr)
                return 1
            if tree["kind"] == "checkout" and not counts["loader_ran"]:
                print("guard_cost_census: this checkout's write_guard has no _load_the_pattern_path, so the "
                      "loader's own compiles would go uncounted; an older tree is read with --at", file=sys.stderr)
                return 1
            result.update(mode="compile", compile=counts)
        else:
            lock = BoxLock()
            try:
                lock.acquire()
                start, times_start = load_average(), system_times()
                if args.calls is not None:
                    kinds = ("control", *[k for k in KINDS[1:] if not args.kind or k in args.kind])
                    modules = compile_counts(hooks, scratch)["modules"]
                    result.update(mode="calls", n=args.calls, bytecode_cache=cache_state(modules),
                                  **time_calls(root, args.calls, kinds, scratch))
                    if not all(row["as_expected"] for row in result["kinds"].values()):
                        status = DECISIONS_MIXED_EXIT
                else:
                    result.update(mode="import-time", rounds=args.rounds or 10, cold=args.cold,
                                  import_time=import_times(hooks, args.rounds or 10, scratch, cold=args.cold))
                end, times_end = load_average(), system_times()
            finally:
                lock.release()
            result.update(lock=lock.summary(), load={"start": start, "end": end,
                                                     "cpu_busy": cpu_busy(times_start, times_end)})
        result["tags"] = tags(result)
        result["unguarded"] = "unguarded" in result["tags"]
        if result["mode"] == "calls":
            result["decisions_as_expected"] = status == 0
        print(json.dumps(result, indent=1) if args.json else render(result))
        return status


if __name__ == "__main__":
    sys.exit(main())
