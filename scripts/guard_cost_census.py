#!/usr/bin/env python3
"""What ``write_guard`` costs a call, measured: TP-707's instrument (Wave 1, 1-A).

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
-la``, an MCP read, an MCP write) beside a bare interpreter start as the control,
which is always timed, shuffled, each spawn in an empty temp project of its own
(no settings file, no ``espalier.toml``), the way the wiring starts it
(``<python> -B <tools/cc/hooks/write_guard.py>``, the payload on stdin), and
prints each kind's median, IQR, min and max in milliseconds beside the decisions
it saw. A guard call starts two interpreters (the thin parent and its judging
child) and the control one, so the control nets out one start. ``-B`` writes no
cache: a checkout's existing cache is read, and an ``--at`` tree has none, so
its figure is the no-cache one. The MCP write names a file inside its temp
project, so the zone layer allows it. Each spawn's project is its own, so a
one-shot nudge an earlier spawn spent cannot change a later one's decision. A
row whose decisions are not what an ordinary call gets (``allow``; ``exit 0`` for
the control) is tagged ``decisions mixed`` and the run exits
``DECISIONS_MIXED_EXIT``: its figure is not a cost. A refusal at the guard's
deadline reads ``deny (time budget)``, and the guard's own budget records are
counted per kind before the run's audit folder goes.

``--compile`` records every ``re._compile`` call while ``_bash_patterns``,
``_speedbump`` and ``write_guard`` import and ``_load_the_pattern_path`` runs, in
a fresh interpreter (``-I -B``): the distinct patterns (keyed by pattern and
flags) and the characters of the distinct string patterns, those again for the
compiles whose call stack passes through the hooks folder (the standard
library's own differ by interpreter), the shared fragment
``_bash_patterns._CMD_POS_NO_VERB``'s length (and ``_CMD_POS``'s), and how many
of the patterns, and of their characters, embed it. ``loader_ran`` and
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
``<lock path>.log``, and the record is cleared at release. One difference: a
tier waits unbounded where the variable is unset, and the census, always an
agent's run under a Bash call's ten-minute cap, waits ``DEFAULT_WAIT_S``. Inside
a holder (the inherited ``ESPALIER_BOX_LOCK_HOLDER`` names the live pid in the
record) it passes through. With the lock variable unset it runs unguarded and
says ``unguarded`` beside every figure. ``--compile`` counts and takes no lock.

Every child's environment drops ``ESPALIER_MAINTENANCE_MODE`` and every
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
KINDS = ("control", "read", "bash", "mcp_read", "mcp_write")
#: The decision an ordinary call of each kind gets; any other makes the row's
#: figure something other than a cost.
EXPECTED_DECISION = {"control": "exit 0", "read": "allow", "bash": "allow", "mcp_read": "allow", "mcp_write": "allow"}
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
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, filter="data")
        else:  # an interpreter without the extraction filters (3.11 before 3.11.4)
            tar.extractall(dest)  # noqa: S202 -- git's own archive of this clone's commit
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


def child_env(project: Path | None, audit_dir: Path) -> dict:
    """The environment every spawn gets: no maintenance mode, no ``CLAUDE_*``
    variable but the spawn's own project, and an audit folder of the run's own."""
    env = {k: v for k, v in os.environ.items()
           if k != "ESPALIER_MAINTENANCE_MODE" and not k.startswith("CLAUDE_")}
    if project is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project)
    env["ESPALIER_AUDIT_DIR"] = str(audit_dir)
    return env


# -- --calls -----------------------------------------------------------------


def payload(kind: str, project: Path) -> dict:
    """The PreToolUse payload of one call kind, naming a file in ``project``."""
    notes = str(project / "notes.txt")
    base = {"session_id": "guard-cost-census", "hook_event_name": "PreToolUse", "cwd": str(project),
            "transcript_path": str(project / "transcript.jsonl"), "permission_mode": "default"}
    if kind == "read":
        base.update(tool_name="Read", tool_input={"file_path": notes})
    elif kind == "bash":
        base.update(tool_name="Bash", tool_input={"command": "ls -la", "description": "List files"})
    elif kind == "mcp_read":
        base.update(tool_name="mcp__filesystem__read_file", tool_input={"path": notes})
    elif kind == "mcp_write":
        base.update(tool_name="mcp__filesystem__write_file", tool_input={"path": notes, "content": "y\n"})
    else:
        raise ValueError(f"no payload for kind {kind!r}")
    return base


def decision(kind: str, returncode: int, stdout: str) -> str:
    """What the spawn answered: the control's exit; for the guard, ``allow``
    (exit 0, no decision), ``deny`` or ``ask``, ``deny (time budget)`` for a
    refusal at its deadline, ``nudge <CP-id>`` for a speed-bump checkpoint,
    ``block`` for exit 2, ``error`` otherwise."""
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
        if "time budget" in reason.lower():
            return f"{verdict} (time budget)"
        cp = next((w.strip(".,:;()[]`'\"") for w in reason.split() if w.strip("[(`'\"").startswith("CP-")), None)
        return f"nudge {cp}" if cp else str(verdict)
    return "allow (with context)" if out.get("additionalContext") else "allow"


def _new_project(base: Path) -> Path:
    project = Path(tempfile.mkdtemp(prefix="p-", dir=base))
    (project / "notes.txt").write_text("x\n", encoding="utf-8")
    return project


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
        project = _new_project(scratch)
        kind_of[project.name] = kind
        if kind == "control":
            argv, data = [sys.executable, "-B", "-c", "pass"], b""
        else:
            argv, data = [sys.executable, "-B", str(hook)], json.dumps(payload(kind, project)).encode("utf-8")
        started = time.perf_counter()
        try:
            proc = run_bounded(argv, input=data, capture_output=True, cwd=str(project),
                               env=child_env(project, audit), timeout=SPAWN_TIMEOUT_S)
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

#: Run in a fresh ``-I -B`` interpreter with the hooks folder as its argument:
#: the recorder is in place before the first hook module imports, and a compile
#: whose call stack passes through the hooks folder is the hooks' own.
COMPILE_CHILD = r'''
import json, os, re, sys
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
if not os.path.isfile(os.path.join(hooks, "write_guard.py")):
    method = "the two pattern modules imported; this tree has no write_guard.py"
else:
    import write_guard
    loader = getattr(write_guard, "_load_the_pattern_path", None)
    if loader is None:
        method = "imports alone: this tree's write_guard has no _load_the_pattern_path (before DEF-946)"
    else:
        loader()
        loader_ran = True
        method = "imports and write_guard._load_the_pattern_path"
re._compile = original
fragment = getattr(_bash_patterns, "_CMD_POS_NO_VERB", None)
cmd_pos = getattr(_bash_patterns, "_CMD_POS", None)
found = isinstance(fragment, str) and bool(fragment)
texts = [k[0] for k in seen if isinstance(k[0], str)]
embedding = [t for t in texts if found and fragment in t]
tools_cc = os.path.dirname(os.path.abspath(hooks))
modules = sorted({os.path.abspath(m.__file__) for m in list(sys.modules.values())
                  if isinstance(getattr(m, "__file__", None), str)
                  and os.path.abspath(m.__file__).startswith(os.path.join(tools_cc, ""))
                  and os.path.basename(m.__file__) != "write_guard.py"})
print(json.dumps({
    "method": method,
    "loader_ran": loader_ran,
    "fragment_found": found,
    "patterns": len(seen),
    "compiled_chars": sum(len(t) for t in texts),
    "hooks_patterns": len(ours),
    "hooks_chars": sum(len(k[0]) for k in ours if isinstance(k[0], str)),
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
                *, why: str = "", stream: TextIO | None = None) -> None:
    """One JSON line in ``<lock path>.log``, ``tests/_box_lock.py::log_outcome``'s shape."""
    end = datetime.now(timezone.utc)
    start = datetime.fromtimestamp(end.timestamp() - waited_s, tz=timezone.utc)
    line: dict = {"outcome": outcome,
                  "run": {k: (run or {}).get(k) for k in ("seat", "lane", "pid")},
                  "holder": {k: (holder or {}).get(k) for k in ("seat", "lane", "pid")},
                  "start": start.isoformat(timespec="seconds"), "end": end.isoformat(timespec="seconds"),
                  "waited_s": round(waited_s, 3)}
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
        who = f"{record.get('seat') or '?'} {record.get('lane') or '?'} (pid {shown}, held {held_min} min)"
    else:
        who = "no holder record"
    argv = [str(a) for a in ((record or {}).get("argv") or [])]
    if argv:
        argv[0] = os.path.basename(argv[0])
    head = " ".join(argv)[:80]
    return _ascii(f"box lock: waiting on {who}" + (f": {head}" if head else ""))


class BoxLock:
    """The census's hold on the box lock for the length of its timed work."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream if stream is not None else sys.stderr
        self.path: Path | None = None
        self.fh: TextIO | None = None
        self.record: dict | None = None
        self.held = False
        self.outcome = "unguarded"
        self.why = f"{LOCK_KEY} is not set"
        self.holder_seen: dict | None = None
        self.waited_s = 0.0

    def acquire(self) -> None:
        raw = os.environ.get(LOCK_KEY)
        if not raw:
            return
        try:
            self.path = Path(current_path(raw, stream=self.stream))
            self.record = build_record()
            self.path.parent.mkdir(exist_ok=True)
            self.fh = open(self.path, "a+", encoding="utf-8")
            self._acquire()
        except SystemExit:
            self._close()
            raise
        except Exception as exc:  # noqa: BLE001 -- a lock that cannot be taken costs the run its guard, never the run
            self.release()
            self.outcome, self.why = "unguarded", _ascii(f"{type(exc).__name__}: {exc}")
            print(f"box lock: not taken ({self.why}); this run is unguarded", file=self.stream, flush=True)
            if self.path is not None:
                log_outcome(self.path, "unguarded", self.record or {"pid": os.getpid()}, why=self.why,
                            stream=self.stream)

    def _acquire(self) -> None:
        assert self.fh is not None and self.path is not None and self.record is not None
        started = time.monotonic()
        bound = wait_bound(os.environ.get(WAIT_KEY), stream=self.stream)
        if bound is None:
            bound = DEFAULT_WAIT_S
        last_report: float | None = None
        while True:
            if _JSON_SAFE.try_lock_file(self.fh):
                self.held = True
                self.record["started"] = _now_stamp()
                self.fh.seek(0)
                self.fh.truncate()
                self.fh.write(json.dumps(self.record))
                self.fh.flush()
                if last_report is not None:
                    self.waited_s = time.monotonic() - started
                self.outcome, self.why = ("waited", "") if last_report is not None else ("taken", "")
                log_outcome(self.path, self.outcome, self.record, self.holder_seen, self.waited_s,
                            stream=self.stream)
                return
            record = read_record(self.path)
            if inside_holder(record):
                self.holder_seen = record
                self._close()
                self.outcome, self.why = "inside", ""
                log_outcome(self.path, "inside", self.record, record, stream=self.stream)
                return
            self.holder_seen = record or self.holder_seen
            now = time.monotonic()
            if last_report is None or now - last_report >= REPORT_S:
                print(waiting_line(record, now - started), file=self.stream, flush=True)
                if last_report is None:
                    print(f"box lock: the census waits at most {bound:g} s ({WAIT_KEY} sets it)",
                          file=self.stream, flush=True)
                last_report = now
            if time.monotonic() - started >= bound:
                waited = time.monotonic() - started
                log_outcome(self.path, "gave_up", self.record, self.holder_seen, waited,
                            why=f"{WAIT_KEY}={bound:g}", stream=self.stream)
                self._close()
                print(_ascii(f"box lock: did not run: waited {waited:.0f} s behind {_who(self.holder_seen)}, "
                             f"past {WAIT_KEY}={bound:g}; nothing was timed"), file=self.stream, flush=True)
                raise SystemExit(DID_NOT_RUN_EXIT)
            time.sleep(POLL_S)

    def _close(self) -> None:
        if self.fh is not None:
            self.fh.close()
            self.fh = None

    def release(self) -> None:
        if self.fh is None:
            return
        try:
            if self.held:
                self.fh.seek(0)
                self.fh.truncate()
                self.fh.flush()
                _JSON_SAFE.unlock_file(self.fh)
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
                  f"patterns compiled (distinct):      {c['patterns']} ({c['hooks_patterns']} from the hooks folder)",
                  f"characters compiled (distinct):    {c['compiled_chars']} ({c['hooks_chars']} from the hooks folder)",
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
        lines += ["project: an empty temp folder a spawn (no settings file, no espalier.toml)",
                  "cache:   " + (", ".join(f"{n} {s}" for s, n in counts.items()) or "no module read")
                  + " (the modules a spawn imports)",
                  f"n={result['n']} a kind, shuffled, ms per spawn; a guard call starts two interpreters, the control one",
                  f"{'kind':10} {'n':>3} {'median':>8} {'q1-q3':>17} {'min':>8} {'max':>8}  decisions"]
        for kind, row in result["kinds"].items():
            seen = ", ".join(f"{d} x{c}" for d, c in sorted(row["decisions"].items()))
            if row["budget_records"]:
                seen += f"; {row['budget_records']} budget record(s)"
            row_tags = run_tags + ([] if row["as_expected"] else ["decisions mixed"])
            iqr = f"{_ms(row['q1'])}-{_ms(row['q3'])}"
            lines.append(f"{kind:10} {row['n']:>3} {_ms(row['median']):>8} {iqr:>17} {_ms(row['min']):>8} "
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
    p = argparse.ArgumentParser(description="What write_guard costs a call (TP-707's instrument).")
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
