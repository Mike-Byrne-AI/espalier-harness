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
    python3 scripts/guard_cost_census.py --import-time --rounds 10 [--json]
    python3 scripts/guard_cost_census.py --compile --at caae022 --json

``--calls N`` spawns the guard N times for each call kind (a bare interpreter
start as the control, a Read, a Bash ``ls -la``, an MCP read and an MCP write),
shuffled, each spawn in a temp project of its own, the way the wiring starts it
(``<python> -B <tools/cc/hooks/write_guard.py>``, the payload on stdin), and
prints each kind's median, IQR, min and max in milliseconds beside the decisions
it saw. A reader nets the interpreter's own start out with the control row. The
MCP write names a file inside its temp project, so the zone layer allows it; a
nudge is reported as the decision seen, never as a different cost. Each spawn's
project is its own, so a one-shot nudge an earlier spawn spent cannot change a
later one's decision, whatever the shuffle.

``--compile`` records every ``re._compile`` call while ``_bash_patterns``,
``_speedbump`` and ``write_guard`` import and ``_load_the_pattern_path`` runs, in
a fresh interpreter (``-I -B``): the distinct patterns (keyed by pattern and
flags), the characters of the distinct string patterns, the shared fragment
``_bash_patterns._CMD_POS_NO_VERB``'s length (and ``_CMD_POS``'s), and how many
of the patterns, and how many of their characters, embed it. A tree whose
``write_guard`` has no ``_load_the_pattern_path`` (before DEF-946, 2026-11-08) is
read by its imports alone, and the output says so. A run that records no pattern
at all exits 1: a loader that loaded nothing must not read as a small figure.

``--import-time --rounds N`` times the two pattern modules' import in N fresh
interpreters, each with no bytecode cache (``-B`` and a ``pycache_prefix`` at an
empty folder), so a checkout and an ``--at`` tree compare like for like.

``--at <sha>`` runs any of the three against ``git archive <sha> tools/cc`` in a
temp folder (a commit only a closed pull request reaches needs its ref fetched
first: ``git fetch origin pull/516/head``). ``--root <dir>`` reads another
folder's ``tools/cc`` instead (a fixture, a second checkout). ``--json`` prints
one JSON object.

**The box lock.** ``--calls`` and ``--import-time`` time, so they hold the box
lock the test tiers take (ruling 3a): the file ``$ESPALIER_BOX_LOCK`` names,
through ``tools/cc/_json_safe.py::try_lock_file``, loaded by path. ``tests/
_box_lock.py`` imports pytest, so this script keeps its own copy of what a holder
does there, pinned to it by ``tests/test_guard_cost_census.py``: the launcher's
old default path is read as its new one, the holder record carries
``build_record``'s keys and is stamped when the lock is taken, a waiter names its
holder at once and every ``REPORT_S``, ``ESPALIER_BOX_LOCK_WAIT_S`` bounds the
wait with ``DID_NOT_RUN_EXIT``, every outcome appends one line to
``<lock path>.log``, and the record is cleared at release. Inside a holder (the
inherited ``ESPALIER_BOX_LOCK_HOLDER`` names the live pid in the record) it
passes through. With the variable unset it runs unguarded and says
``unguarded`` beside every figure. ``--compile`` counts and takes no lock.

Every child's environment drops ``ESPALIER_MAINTENANCE_MODE`` and every
``CLAUDE_*`` variable, sets ``CLAUDE_PROJECT_DIR`` to the spawn's temp project and
``ESPALIER_AUDIT_DIR`` to a temp folder, so no state lands in the checkout, no
session's markers are touched and no record reaches ``~/.espalier/audit``.
Stdlib only, self-host; output is ASCII.
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
#: How long one spawn may take: the guard's own deadline is 4 s from its first
#: line and the wired timeout 5 s, so a spawn past this is a hang, not a cost.
SPAWN_TIMEOUT_S = 30.0
#: One fresh interpreter's compile or import read, which imports the hooks once.
CHILD_TIMEOUT_S = 120.0
GIT_TIMEOUT_S = 60.0

# The box lock, as tests/_box_lock.py names it (pinned equal by the test).
LOCK_KEY = "ESPALIER_BOX_LOCK"
HOLDER_KEY = "ESPALIER_BOX_LOCK_HOLDER"
WAIT_KEY = "ESPALIER_BOX_LOCK_WAIT_S"
DID_NOT_RUN_EXIT = 75
POLL_S = 0.25
REPORT_S = 30.0


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
    """``n``, median, the quartiles (``statistics.quantiles``' exclusive method,
    named so a default change cannot move it; one value is its own quartiles),
    min and max."""
    data = sorted(values)
    if not data:
        return {"n": 0, "median": None, "q1": None, "q3": None, "min": None, "max": None}
    if len(data) == 1:
        q1 = q3 = data[0]
    else:
        q1, _, q3 = statistics.quantiles(data, n=4, method="exclusive")
    return {"n": len(data), "median": statistics.median(data), "q1": q1, "q3": q3,
            "min": data[0], "max": data[-1]}


def load_average() -> list[float] | None:
    """The 1, 5 and 15 minute load averages, or None where the platform has none."""
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except (AttributeError, OSError):
        return None


# -- The tree a run reads ----------------------------------------------------


def _git(*args: str, cwd: Path = REPO_ROOT, text: bool = True, timeout: float = GIT_TIMEOUT_S) -> Any:
    return run_bounded(["git", *args], cwd=str(cwd), capture_output=True, text=text, timeout=timeout,
                       **({"encoding": "utf-8", "errors": "replace"} if text else {}))


def checkout_tree() -> dict:
    """This checkout: its HEAD and whether ``tools/cc`` holds uncommitted edits
    (a figure from such a tree is not HEAD's)."""
    head = _git("rev-parse", "HEAD")
    dirty = _git("status", "--porcelain", "--", "tools/cc")
    return {"kind": "checkout", "root": str(REPO_ROOT),
            "head": head.stdout.strip() if head.returncode == 0 else None,
            "tools_cc_edited": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None}


def archive_tree(at: str, dest: Path) -> dict:
    """``git archive <at> tools/cc`` extracted under ``dest``. Raises
    ``SystemExit`` with a reason where ``at`` names no commit here."""
    resolved = _git("rev-parse", "--verify", "--quiet", f"{at}^{{commit}}")
    if resolved.returncode != 0 or not resolved.stdout.strip():
        raise SystemExit(f"guard_cost_census: {at!r} names no commit in this clone; a commit only a closed "
                         "pull request reaches needs its ref fetched first (git fetch origin pull/<n>/head)")
    sha = resolved.stdout.strip()
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


def bytecode_cache_present(hooks: Path) -> bool:
    """Whether the hooks folder holds this interpreter's compiled ``write_guard``:
    a spawn reads it where it is there (``-B`` only stops a write)."""
    return (hooks / "__pycache__" / f"write_guard.{sys.implementation.cache_tag}.pyc").is_file()


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
    (exit 0, no decision), ``deny`` or ``ask``, ``nudge <CP-id>`` for a
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
    out = doc.get("hookSpecificOutput") if isinstance(doc, dict) else None
    out = out if isinstance(out, dict) else {}
    verdict = out.get("permissionDecision")
    if verdict in ("deny", "ask"):
        reason = str(out.get("permissionDecisionReason", ""))
        cp = next((w.strip(".,:;()[]`'\"") for w in reason.split() if w.strip("[(`'\"").startswith("CP-")), None)
        return f"nudge {cp}" if cp else str(verdict)
    return "allow (with context)" if out.get("additionalContext") else "allow"


def _new_project(base: Path) -> Path:
    project = Path(tempfile.mkdtemp(prefix="p-", dir=base))
    (project / "notes.txt").write_text("x\n", encoding="utf-8")
    return project


def time_calls(root: Path, n: int, kinds: tuple[str, ...], scratch: Path,
               *, shuffle: Callable[[list], None] = random.shuffle) -> dict:
    """N spawns of each kind, in ``shuffle``'s order, each in a project of its own."""
    hook = hooks_of(root) / "write_guard.py"
    audit = scratch / "audit"
    audit.mkdir(exist_ok=True)
    order = [k for k in kinds for _ in range(n)]
    shuffle(order)
    times: dict[str, list[float]] = {k: [] for k in kinds}
    seen: dict[str, dict[str, int]] = {k: {} for k in kinds}
    for kind in order:
        project = _new_project(scratch)
        if kind == "control":
            argv, data = [sys.executable, "-B", "-c", "pass"], b""
        else:
            argv, data = [sys.executable, "-B", str(hook)], json.dumps(payload(kind, project)).encode("utf-8")
        started = time.perf_counter()
        proc = run_bounded(argv, input=data, capture_output=True, cwd=str(project),
                           env=child_env(project, audit), timeout=SPAWN_TIMEOUT_S)
        times[kind].append((time.perf_counter() - started) * 1000.0)
        said = decision(kind, proc.returncode, proc.stdout.decode("utf-8", "replace"))
        seen[kind][said] = seen[kind].get(said, 0) + 1
    return {k: {**summarize(times[k]), "decisions": seen[k]} for k in kinds}


# -- --compile ---------------------------------------------------------------

#: Run in a fresh ``-I -B`` interpreter with the hooks folder as its argument:
#: the recorder is in place before the first hook module imports.
COMPILE_CHILD = r'''
import json, os, re, sys
hooks = sys.argv[1]
sys.path.insert(0, hooks)
seen = {}
original = re._compile
def record(pattern, flags):
    text = pattern if isinstance(pattern, (str, bytes)) else getattr(pattern, "pattern", repr(pattern))
    key = (text, int(flags))
    seen[key] = seen.get(key, 0) + 1
    return original(pattern, flags)
re._compile = record
re.purge()
import _bash_patterns
import _speedbump
if not os.path.isfile(os.path.join(hooks, "write_guard.py")):
    method = "the two pattern modules imported; this tree has no write_guard.py"
else:
    import write_guard
    loader = getattr(write_guard, "_load_the_pattern_path", None)
    if loader is None:
        method = "imports alone: this tree's write_guard has no _load_the_pattern_path (before DEF-946)"
    else:
        loader()
        method = "imports and write_guard._load_the_pattern_path"
re._compile = original
fragment = getattr(_bash_patterns, "_CMD_POS_NO_VERB", None)
cmd_pos = getattr(_bash_patterns, "_CMD_POS", None)
texts = [k[0] for k in seen if isinstance(k[0], str)]
embedding = [t for t in texts if isinstance(fragment, str) and fragment and fragment in t]
print(json.dumps({
    "method": method,
    "patterns": len(seen),
    "compiled_chars": sum(len(t) for t in texts),
    "fragment_len": len(fragment) if isinstance(fragment, str) else None,
    "cmd_pos_len": len(cmd_pos) if isinstance(cmd_pos, str) else None,
    "embedding_patterns": len(embedding),
    "embedding_chars": sum(len(t) for t in embedding),
}))
'''

#: Run in a fresh ``-I -B`` interpreter with no bytecode cache to read: the two
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


def _child(code: str, hooks: Path, scratch: Path, *extra: str) -> dict:
    """One fresh interpreter running ``code`` over ``hooks``; its last stdout
    line as JSON. Raises ``SystemExit`` naming the child's error otherwise."""
    proc = run_bounded([sys.executable, "-I", "-B", *extra, "-c", code, str(hooks)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", cwd=str(scratch),
                       env=child_env(None, scratch / "audit"), timeout=CHILD_TIMEOUT_S)
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if proc.returncode != 0 or not lines:
        tail = " | ".join(proc.stderr.strip().splitlines()[-3:])
        raise SystemExit(_ascii(f"guard_cost_census: the child over {hooks} exited {proc.returncode}: {tail}"))
    return json.loads(lines[-1])


def compile_counts(hooks: Path, scratch: Path) -> dict:
    return _child(COMPILE_CHILD, hooks, scratch)


def import_times(hooks: Path, rounds: int, scratch: Path) -> dict:
    """``rounds`` fresh interpreters, each with a ``pycache_prefix`` at an empty
    folder of its own, so none reads a bytecode cache."""
    per: dict[str, list[float]] = {"bash_patterns": [], "speedbump": [], "both": []}
    for i in range(rounds):
        empty = scratch / f"pycache-{i}"
        empty.mkdir()
        got = _child(IMPORT_CHILD, hooks, scratch, "-X", f"pycache_prefix={empty}")
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
    held (its record's start, else this wait), then the head of its argv."""
    held_min = int(waited_s // 60)
    started = (record or {}).get("started")
    if isinstance(started, str):
        try:
            since = datetime.fromisoformat(started.replace("Z", "+00:00"))
            held_min = int((datetime.now(timezone.utc) - since).total_seconds() // 60)
        except ValueError:
            pass
    if record:
        who = f"{record.get('seat') or '?'} {record.get('lane') or '?'} (pid {record.get('pid')}, held {held_min} min)"
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
                last_report = now
            if bound is not None and time.monotonic() - started >= bound:
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

    @property
    def unguarded(self) -> bool:
        return self.outcome == "unguarded"


# -- Rendering ---------------------------------------------------------------


def _ms(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def _load_text(load: list[float] | None) -> str:
    return "n/a (no load average on this platform)" if load is None else " ".join(f"{x:.2f}" for x in load)


def _tree_text(tree: dict) -> str:
    if tree["kind"] == "checkout":
        edited = {True: ", tools/cc edited", False: "", None: ", tools/cc state unread"}[tree["tools_cc_edited"]]
        return f"checkout {tree['root']} at {(tree['head'] or '?')[:12]}{edited}"
    if tree["kind"] == "archive":
        return f"git archive of {tree['commit'][:12]} ({tree['at']}) tools/cc"
    return f"folder {tree['root']}"


def _lock_text(lock: dict) -> str:
    text = lock["outcome"]
    if lock.get("holder"):
        h = lock["holder"]
        text += f" ({'behind' if lock['outcome'] == 'waited' else 'holder'} {h.get('seat')} {h.get('lane')} pid {h.get('pid')})"
    if lock.get("why"):
        text += f" ({lock['why']})"
    return text


def render(result: dict) -> str:
    head = [f"guard cost census -- {result['mode']}",
            f"tree:    {_tree_text(result['tree'])}",
            f"python:  {result['python']['version']} ({result['python']['executable']})"]
    tag = "  [unguarded]" if result.get("lock", {}).get("outcome") == "unguarded" else ""
    if result["mode"] == "compile":
        c = result["compile"]
        head += [f"method:  {c['method']}",
                 f"patterns compiled (distinct):      {c['patterns']}",
                 f"characters compiled (distinct):    {c['compiled_chars']}",
                 f"_CMD_POS_NO_VERB length:           {c['fragment_len']}",
                 f"_CMD_POS length:                   {c['cmd_pos_len']}",
                 f"patterns embedding the fragment:   {c['embedding_patterns']}",
                 f"characters in those patterns:      {c['embedding_chars']}"]
        return "\n".join(head)
    head += [f"lock:    {_lock_text(result['lock'])}",
             f"load:    {_load_text(result['load']['start'])} at the start, {_load_text(result['load']['end'])} at the end"]
    if result["mode"] == "calls":
        head += [f"bytecode cache for write_guard: {'present' if result['bytecode_cache'] else 'absent'}",
                 f"n={result['n']} a kind, shuffled, ms per spawn",
                 f"{'kind':10} {'n':>3} {'median':>8} {'q1-q3':>17} {'min':>8} {'max':>8}  decisions"]
        for kind, row in result["kinds"].items():
            seen = ", ".join(f"{d} x{c}" for d, c in sorted(row["decisions"].items()))
            iqr = f"{_ms(row['q1'])}-{_ms(row['q3'])}"
            head.append(f"{kind:10} {row['n']:>3} {_ms(row['median']):>8} {iqr:>17} {_ms(row['min']):>8} "
                        f"{_ms(row['max']):>8}  {seen}{tag}")
    else:
        head += [f"rounds={result['rounds']}, a fresh interpreter each, no bytecode cache, ms",
                 f"{'module':14} {'median':>8} {'q1-q3':>17} {'min':>8} {'max':>8}"]
        for name, row in result["import_time"].items():
            iqr = f"{_ms(row['q1'])}-{_ms(row['q3'])}"
            head.append(f"{name:14} {_ms(row['median']):>8} {iqr:>17} {_ms(row['min']):>8} {_ms(row['max']):>8}{tag}")
    return _ascii("\n".join(head))


# -- Main --------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="What write_guard costs a call (TP-707's instrument).")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--calls", type=int, metavar="N", help="time N spawns of each call kind")
    mode.add_argument("--compile", action="store_true", help="the compile proxy, from a fresh interpreter")
    mode.add_argument("--import-time", action="store_true", help="time the two pattern modules' import")
    p.add_argument("--rounds", type=int, default=10, help="--import-time's fresh interpreters (default 10)")
    p.add_argument("--kind", action="append", choices=KINDS, help="--calls: only this kind (repeatable)")
    where = p.add_mutually_exclusive_group()
    where.add_argument("--at", metavar="SHA", help="read git archive SHA tools/cc instead of this checkout")
    where.add_argument("--root", type=Path, help="read DIR/tools/cc instead of this checkout")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.calls is not None and args.calls < 1:
        print("guard_cost_census: --calls takes 1 or more", file=sys.stderr)
        return 2
    if args.rounds < 1:
        print("guard_cost_census: --rounds takes 1 or more", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="guard-cost-census-") as tmp:
        # Resolved: on macOS the temp folder is under /var, a link to /private/var,
        # and a payload path spelled through the link sits outside the root the
        # guard resolves, which no real project's own path does.
        scratch = Path(tmp).resolve()
        (scratch / "audit").mkdir()
        if args.at:
            tree = archive_tree(args.at, scratch / "tree")
            root = scratch / "tree"
        elif args.root:
            root = args.root.resolve()
            tree = {"kind": "folder", "root": str(root)}
        else:
            root, tree = REPO_ROOT, checkout_tree()
        hooks = hooks_of(root)
        if not (hooks / "_bash_patterns.py").is_file():
            print(f"guard_cost_census: {hooks} holds no _bash_patterns.py", file=sys.stderr)
            return 2
        result: dict = {"tree": tree, "python": {"version": platform.python_version(),
                                                  "executable": sys.executable}}
        if args.compile:
            result.update(mode="compile", compile=compile_counts(hooks, scratch))
            if not result["compile"]["patterns"]:
                print(render(result) if not args.json else json.dumps(result, indent=1))
                print("guard_cost_census: the pattern path recorded no pattern at all: the loader loaded "
                      "nothing, which is no figure", file=sys.stderr)
                return 1
        else:
            lock = BoxLock()
            lock.acquire()
            try:
                start = load_average()
                if args.calls is not None:
                    kinds = tuple(k for k in KINDS if not args.kind or k in args.kind)
                    result.update(mode="calls", n=args.calls, bytecode_cache=bytecode_cache_present(hooks),
                                  kinds=time_calls(root, args.calls, kinds, scratch))
                else:
                    result.update(mode="import-time", rounds=args.rounds,
                                  import_time=import_times(hooks, args.rounds, scratch))
                end = load_average()
            finally:
                lock.release()
            result.update(lock=lock.summary(), load={"start": start, "end": end}, unguarded=lock.unguarded)
    print(json.dumps(result, indent=1) if args.json else render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
