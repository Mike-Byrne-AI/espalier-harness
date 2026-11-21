"""As many pytest tiers at once on one machine as its slots (one by default), by construction.

Two seats (Claude Code sessions in two checkouts of one clone) on one box ran
one tier at a time by a note protocol on the mail channel: a ``START`` before,
an ``END`` after, and the other seat reading the mail first. On 2026-10-18 that
protocol was 87 of the day's 240 worker messages, crossed three times, corrected
four times, and a seat the low-memory reaper killed never sent its ``END``.
Core Rule 14 says serialise only what cannot be isolated, and never by
remembering: two full tiers on an 8 GB box cannot be isolated, so a lock the
kernel holds serialises them.

When ``ESPALIER_BOX_LOCK`` names a path (the seat launcher sets it; CI never
does) and this run is an xdist run that will run tests (``numprocesses`` read
from the config, so ``PYTEST_ADDOPTS=-n`` counts and ``-n 0`` takes none; every
tier line is an xdist run, the contract slice included, and a tier's lines each
take and release the lock, so two tiers interleave line by line; a run without
``-n``, as a reviewer's or an agent's node-id or file run is, takes no lock and
never waits past a Bash call's cap), the controller takes a lock on that file
before any worker is spawned, through the primitive's non-blocking
``try_lock_file``. While another run holds it, this one polls, says who holds
it (seat, lane, pid, how long it has held since it took the lock) on stderr at
once and then once per report interval; once the holder itself is past a
ceiling, an inspect command, and the stop command only where the holder's
checkout holds no live Claude Code session (else: ask its seat on the mail).
``ESPALIER_BOX_LOCK_WAIT_S`` bounds the wait: past it the run ends before any
test, with its own exit status. Every gated run appends one JSON line to
``<lock path>.log`` saying what the lock did -- taken at once, waited (how
long, behind whom), passed through inside its holder, gave up past the
waiter's bound, or unguarded (why) --
so the record the roadmap's re-measure reads is empty only where no gated
run came, never merely where none waited (DEF-4053). A run that held the
lock appends one more line at its release, ``released`` with how long it
held, written while it still holds, so a hold's two lines pair in file order
and the log reads how full the box was, not only how long its waiters queued
(DEF-3084); a holder that is killed leaves its acquire line alone. The launcher's old
default (the temp directory's file) is read as its new one, said on stderr,
so a seat launched before the move locks what its relaunched sibling locks.
The run's terminal summary says
what the lock did: waited, passed through, or unguarded. Once held it writes its own record into the file and exports
``ESPALIER_BOX_LOCK_HOLDER=<pid>`` to every child, so a nested run (xdist's
workers, the stage-one smoke) that inherits the pair and finds the record's pid
alive passes through; a dead holder's pid in the pair is no pass, and an empty
or unreadable record under a held lock is said and waited on. The lock goes
when the handle closes or the process dies, so a killed holder frees its
waiter at once (3 to 14 ms over five kills on macOS, 2026-10-25); an orphaned
pytest tree keeps it and is named, which is the remedy.

A box may hold more than one tier at once (DEF-2105, the shape the review in
air's 8dda84 fixed). How many is one whole number in the file beside the lock,
``<lock path>.slots``, read through ``tools/cc/_json_safe.py::box_lock_slots``:
absent, the box has one slot, the lock file itself, as every box ran before;
slot k from 2 on is ``<lock path>.slot<k>``. The count lives in a file of the
box, never in a seat's environment, where one stray export would put two tiers
on a box that holds one. A parallel line takes the first free slot, and waits
at slot 1 unless slot 1 holds another parallel line's record (a serial line's,
an older checkout's with no slot, or one caught mid-write all stop it). A
serial line, any run at one worker (``-n auto`` that resolves to one
included; the files ``scripts/proof_tier.py`` keeps off parallel load for their
wall-clock budgets run so), takes every slot, in order, holding each as it
comes, so it does not run beside another seat's pool (DEF-4062's shape), and
while it waits for the rest its record in the slots it holds says so. The
inherited pair is read over every slot file there is, the count's and any later
one, before any try, so a nested run passes through its parent's slot and never
takes one of its own. Each log line names its slot (``every`` for a serial
hold) and the box's count; on a box of several slots two holds' lines
interleave, so a hold's acquire and release pair by the run's pid. A checkout
that predates the slots locks the lock file alone whatever the count says, so
the count is written only once every checkout that runs tiers on the box has
this code.

Registered from ``tests/conftest.py::pytest_configure`` beside the never-ran
count, or by ``-p tests._box_lock`` on a scratch run; never on an xdist worker.
A failure inside the plugin is one stderr line and one summary line, and the
run proceeds unguarded, since a lock that cannot be taken must not cost a seat
its tier. The primitive
is ``tools/cc/_json_safe.py``, loaded by path as the suite's helpers do.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, NoReturn, TextIO

import pytest

try:
    from tests._never_ran import NO_TEST_RUNS
    from tests._temp_sweep import _load as _load_restoring, restoring_imports
except ImportError:  # the suite's conftest imports its helpers bare, with tests/ on sys.path
    from _never_ran import NO_TEST_RUNS  # type: ignore[no-redef]
    from _temp_sweep import _load as _load_restoring, restoring_imports  # type: ignore[no-redef]

#: The name the plugin object is registered under.
PLUGIN_NAME = "espalier-box-lock"
LOCK_KEY = "ESPALIER_BOX_LOCK"
HOLDER_KEY = "ESPALIER_BOX_LOCK_HOLDER"
#: The waiter's own bound, in seconds; unset, a run waits for as long as the
#: holder runs (DEF-4056). An agent's run under a Bash call's cap sets it, so
#: the cap never reads a run that never started as a verdict.
WAIT_KEY = "ESPALIER_BOX_LOCK_WAIT_S"
#: The status of a run that gave up past ``WAIT_KEY``: sysexits' EX_TEMPFAIL
#: (a resource busy, try later). pytest's own statuses are 0 to 5, so a reader
#: of the status tells a run that never started from a red.
DID_NOT_RUN_EXIT = 75
#: How long the read of the holder's checkout's sessions may take.
SESSIONS_READ_S = 5.0
#: How often a waiter tries the lock, and how often it repeats the holder line.
POLL_S = 0.25
REPORT_S = 30.0
#: A holder past this age is named with the inspect and stop commands: above
#: every post-merge proof worst scripts/ci_job_bounds_census.py reads as ok at
#: that job's bound (its bound over the census's factor, past which the census
#: asks a raise: 155 / 1.5 = 103.3 when this was set, 2026-11-14), since only a
#: raise moves the measured worst the dict records (92.2 minutes over its last
#: 20 green runs, 2026-11-14; 88.1 on 2026-11-12, 86.6 on 2026-11-11, 70.7 on
#: 2026-11-08, and 48.2 over ten to 2026-10-16, when this read 60), and a worst
#: the census read above the dict's figure and under that bound sat over a
#: ceiling of 95 with every test green (95.5, 2026-11-14 21:50Z).
#: tests/test_ci_job_bounds.py holds it over both. Keyed on the holder's own age,
#: never on this waiter's wait: the lock is not fair, and a waiter that lost
#: several races must not be told to end a healthy holder two minutes into its
#: line.
WAIT_CEILING_MIN = 105
#: A serial line's slot, in its record and on its log lines: every slot.
EVERY_SLOT = "every"
#: Options under which configure runs but no test does: the never-ran count's
#: collect-only set, plus ``--help`` and ``--markers``.
_NO_TEST_OPTIONS = (*NO_TEST_RUNS, "help", "markers")

_TOOLS_CC = Path(__file__).resolve().parent.parent / "tools" / "cc"
#: The pair as a builder names it: the literal, or the constant this plugin
#: (``LOCK_KEY``, ``HOLDER_KEY``) or the launcher (``tools/cc/seat.py``'s
#: ``BOX_LOCK_KEY``) spells it with (DEF-2034). A word boundary keeps the
#: holder and the wait bound, which share the lock's prefix, out of the lock.
_LOCK_WORD = re.compile(r"\bESPALIER_BOX_LOCK\b|\bLOCK_KEY\b|\bBOX_LOCK_KEY\b")
_HOLDER_WORD = re.compile(r"\bESPALIER_BOX_LOCK_HOLDER\b|\bHOLDER_KEY\b")
_PREFIX_STRIP = re.compile(r"""startswith\(\s*\(?\s*(?:['"]ESPALIER_BOX_LOCK['"]|(?:\w+\.)*(?:BOX_)?LOCK_KEY\b)""")


def _primitive() -> Any:
    """``tools/cc/_json_safe.py`` by path, under a private name: the suite loads
    the same file under its plain name elsewhere and must keep that instance."""
    spec = importlib.util.spec_from_file_location("_box_lock_json_safe", _TOOLS_CC / "_json_safe.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def gated(config: Any) -> bool:
    """Whether this run takes the lock: an xdist run (``numprocesses`` on the
    config is not None and not 0; the option, never the argv, so an addopts
    ``-n`` counts) under none of the collect-only options."""
    opt = getattr(config, "option", None)
    if opt is None:  # a stub config (the suite's own configure tests)
        return False
    if any(getattr(opt, name, False) for name in _NO_TEST_OPTIONS):
        return False
    return getattr(opt, "numprocesses", None) not in (None, 0)


def takes_every_slot(config: Any) -> bool:
    """Whether a gated run is a serial line, which takes every slot of the box:
    xdist at one worker (``numprocesses`` 1 on the config, which xdist has
    turned from ``auto`` into its count before configure). The serial files
    run at one worker because their placement was measured off parallel load
    (wall-clock budgets, the timeout-near gates, the nested runs), so beside
    another seat's pool they would meet the load they were moved away from
    (DEF-4062's shape). Any other value is a parallel line's one slot."""
    opt = getattr(config, "option", None)
    try:
        return int(getattr(opt, "numprocesses", None)) == 1  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def every_slot_record(record: dict | None) -> bool:
    """Whether a slot's record is a serial line's, whose hold is every slot."""
    return isinstance(record, dict) and record.get("slot") == EVERY_SLOT


def parallel_record(record: dict | None) -> bool:
    """Whether a slot's record is a parallel line's, the one record slot 1 may
    hold while a parallel line goes on to the next slot: its slot is a number.
    A serial line's, an older checkout's (no slot) and an empty one are not."""
    return isinstance(record, dict) and isinstance(record.get("slot"), int) and not isinstance(record.get("slot"), bool)


def pair_paths(lock: Path, slot_paths: list[Path], most: int) -> list[Path]:
    """The slot files the inherited pair is read in: every slot the count
    names, then each later ``<lock>.slot<k>`` up to ``most`` that is there, so
    a nested run whose parent took slot 2 passes through after the count was
    lowered (the failure-mode review). A pass cannot be forged by reading
    more: it needs the record's pid to be the inherited one and alive."""
    extra = [Path(f"{lock}.slot{k}") for k in range(len(slot_paths) + 1, most + 1)]
    return [*slot_paths, *(p for p in extra if p.is_file())]


def holder_alive(pid: int) -> bool:
    """Whether ``pid`` is a live process: ``kill -0`` on POSIX, an opened
    handle whose exit code is still-active on Windows."""
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
        query = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
        handle = kernel32.OpenProcess(query, False, pid)
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
    """The holder record in the lock file, or None when it is empty, missing
    or not one JSON object (a holder that died between the lock and its
    write, or a reader that caught the write half-way)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):  # a UnicodeDecodeError is a ValueError
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
    and that pid is alive. Nothing else passes: a child that inherited the
    variable is a child of the run that set it, and a dead holder's pid, a
    forged one or an empty record is a wait."""
    env_pid = os.environ.get(HOLDER_KEY)
    if not env_pid or not record:
        return False
    try:
        pid = int(env_pid)
    except ValueError:
        return False
    return str(record.get("pid")) == env_pid and holder_alive(pid)


def waiting_line(record: dict | None, *, waited_s: float,
                 read_seat: Callable[[dict], bool | None] | None = None) -> str:
    """The line a waiter prints: the holder's seat, lane and pid, how long it
    has held (from its record's start, else this waiter's wait), the head of
    its argv, and past the ceiling what to do about it (:func:`_past_ceiling`,
    which alone calls ``read_seat``); ``no holder record`` where the file is
    empty or unreadable. ASCII only."""
    held_min = int(waited_s // 60)
    pid: int | None = None
    if record and "pid" in record:
        try:
            pid = int(record.get("pid"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pid = None
        started = record.get("started")
        if isinstance(started, str):
            try:
                # The holder's own age, never this waiter's wait, is what the
                # ceiling reads; the wait stands in only for a record with no
                # readable start.
                since = datetime.fromisoformat(started.replace("Z", "+00:00"))
                held_min = int((datetime.now(timezone.utc) - since).total_seconds() // 60)
            except ValueError:
                pass
        shown = pid if pid is not None else "?"
        # A serial line still taking the box's slots holds some and waits for
        # the rest: its age is a queue's, so it is never handed the ceiling.
        held = "taking every slot" if record.get("draining") else f"held {held_min} min"
        who = f"{record.get('seat') or '?'} {record.get('lane') or '?'} (pid {shown}, {held})"
    else:
        who = "no holder record"
    head = _argv_head((record or {}).get("argv") or [])
    line = f"box lock: waiting on {who}" + (f": {head}" if head else "")
    if record and pid is not None and held_min >= WAIT_CEILING_MIN and not record.get("draining"):
        line += " -- " + _past_ceiling(record, pid, read_seat)
    return _ascii(line)


def _past_ceiling(record: dict, pid: int, read_seat: Callable[[dict], bool | None] | None) -> str:
    """What a waiter is told about a holder past the ceiling. Past it is the
    ordinary case for a seat's tier on a loaded box (a full-tier leg runs 25 to
    50 minutes, with two seats' tiers queued), and on 2026-10-31 a window ended
    a live seat's leg by pid as a stray, so the stop command goes only to a
    live pid whose checkout holds no live Claude Code session (``read_seat``
    False: DEF-4077). A seat with a session, or one ``read_seat`` cannot read
    (None, or no reader), is asked on the mail. A dead pid gets no command: there
    is nothing to end by it, and a pid reused since would be a stranger."""
    if sys.platform == "win32":
        look, stop = f"tasklist /FI \"PID eq {pid}\"", f"taskkill /T /F /PID {pid}"
    else:
        look, stop = f"ps -p {pid} -o etime,command", f"kill -9 {pid}"
    past = f"the holder is past {WAIT_CEILING_MIN} min"
    if not holder_alive(pid):
        # The lock goes with the process that took it, so the holder is a
        # descendant that outlived it, or this read raced the release.
        return (f"{past}, but pid {pid} has exited, so this record does not name the lock's holder: "
                "find the real one among the box's pytest processes and their parents")
    seat = record.get("seat")
    if not isinstance(seat, str) or seat in ("", "?"):
        # A run in a checkout that answers no seat name (a fresh-clone gate
        # leg, a scratch clone's run) is a seat's run all the same, and its
        # checkout holds no session of its own (both reviews, 2026-11-02).
        return (f"{past} and it names no seat, so whose run it is could not be read: inspect it with `{look}` "
                "and read its parents before anything ends it")
    live = read_seat(record) if read_seat is not None else None
    if live is False:
        return f"{past} and its checkout holds no live Claude Code session: inspect it with `{look}`; a stuck one ends with `{stop}`"
    why = "its seat has a live session" if live else "whether its seat has a live session could not be read"
    return (f"{past}; {why}: inspect it with `{look}` and ask {seat} on the mail "
            "(`python tools/cc/mail.py send --type request`) rather than end it")


def holder_seat_live(record: dict, *, config_dir: Path | None = None) -> bool | None:
    """Whether the holder's checkout (its record's ``checkout``) holds a live
    Claude Code session: ``tools/cc/checkout_sync.py::sessions_in`` over
    Claude Code's registry (``config_dir`` in place of its own, for tests),
    its git read bounded at ``SESSIONS_READ_S``. Loaded the temp sweep's way,
    under the sweep's own alias: ``sys.path`` and the bare ``tools/cc`` names
    its imports, and its call, add are put back (where git cannot list the
    checkouts, the call loads ``hooks/_hook_utils.py``), so a read while this
    run waits, before collection, changes nothing a test resolves. None,
    cannot tell, for a
    record with no checkout (an older plugin's), a reader that does not load
    or raises, and a registry it cannot read whole."""
    checkout = record.get("checkout")
    if not isinstance(checkout, str) or checkout in ("", "?"):
        return None
    try:
        sync = _load_restoring(_TOOLS_CC / "checkout_sync.py", "_temp_sweep_checkout_sync")
        with restoring_imports():
            sessions = sync.live_sessions(config_dir)
            found = None if sessions is None else sync.sessions_in(
                Path(checkout), sessions=sessions, deadline=time.monotonic() + SESSIONS_READ_S)
    except Exception:  # noqa: BLE001 -- a reader that cannot answer is "cannot tell", never "no session"
        return None
    return None if found is None else bool(found)


def _argv_head(argv: list) -> str:
    """The holder's command as a waiter can read it: the program's basename
    (the tier spawns the venv's ``pytest`` by its absolute path) and the first
    arguments, cut to 80 characters."""
    words = [str(a) for a in argv]
    if words:
        words[0] = os.path.basename(words[0])
    return " ".join(words)[:80]


def pair_asymmetry(text: str) -> str | None:
    """The census rule over a file that spawns pytest: the one of the pair
    ``text`` names without the other, else None. A child's environment that
    keeps the path and loses the holder would wait on its own parent, so a
    builder that names one name must name both (a ``startswith`` strip of the
    path's prefix drops both and passes); a builder that names neither
    inherits both and passes."""
    if _PREFIX_STRIP.search(text):
        return None
    lock, holder = bool(_LOCK_WORD.search(text)), bool(_HOLDER_WORD.search(text))
    if lock and not holder:
        return LOCK_KEY
    if holder and not lock:
        return HOLDER_KEY
    return None


def build_record(config: Any, primitive: Any) -> dict:
    """This run's holder record, built before the try: seat, lane and checkout
    (the folder a waiter reads the seat's sessions in) from git, two seconds
    each, ``?`` on failure; pid; the start in UTC, stamped again when the lock
    is taken (:meth:`BoxLock._acquire`); the argv head."""
    cwd = str(getattr(config, "rootpath", None) or Path.cwd())

    def git(*args: str) -> str:
        try:
            proc = primitive.run_bounded(["git", *args], cwd=cwd, capture_output=True, text=True,
                                         encoding="utf-8", errors="replace", timeout=2.0)
        except (OSError, subprocess.SubprocessError):
            return "?"
        return (proc.stdout.strip() or "?") if proc.returncode == 0 else "?"

    return {"seat": git("config", "espalier.machine"), "lane": git("rev-parse", "--abbrev-ref", "HEAD"),
            "checkout": git("rev-parse", "--show-toplevel"), "pid": os.getpid(), "started": _now_stamp(),
            "argv": [os.path.basename(str(sys.argv[0])), *[str(a) for a in sys.argv[1:9]]] if sys.argv else []}


def _now_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def wait_bound(raw: str | None, *, stream: TextIO | None = None) -> float | None:
    """``ESPALIER_BOX_LOCK_WAIT_S`` as a bound in seconds: None, wait for as
    long as the holder runs, where it is unset or blank; otherwise a finite
    number at or above 0. Any other value is said on stderr and read as unset:
    a typo must not end a run that would have waited."""
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


def home_default() -> str | None:
    """The launcher's default lock path (``tools/cc/seat.py::box_lock_default``,
    whose rule this mirrors and a test pins equal): ``~/.espalier/espalier-box.lock``,
    or None where no usable home can be told."""
    try:
        home = Path.home()
    except RuntimeError:
        return None
    if not home.is_absolute() or home.parent == home:
        return None
    return str(home / ".espalier" / "espalier-box.lock")


def current_path(path: str, *, stream: TextIO | None = None) -> str:
    """``path``, unless it is the launcher's default from before it moved to
    the home directory (``espalier-box.lock`` under the temp directory): a
    seat launched then keeps that path in its environment until it is
    relaunched, and a ``/clear`` keeps the process, so for days one seat would
    lock the old file and its relaunched sibling the new one, the split the
    move closed (DEF-4053's failure-mode review). That one path is read as the
    home default, said on stderr; any other path is the operator's own."""
    old = os.path.join(tempfile.gettempdir(), "espalier-box.lock")
    new = home_default()
    if new is None or os.path.normcase(os.path.abspath(path)) != os.path.normcase(os.path.abspath(old)):
        return path
    print(f"box lock: {path} is the launcher's old default; this run locks {new} (a relaunched seat drops this line)",
          file=stream if stream is not None else sys.stderr, flush=True)
    return new


def log_outcome(lock: Path, outcome: str, run: dict | None, holder: dict | None = None, waited_s: float = 0.0,
                *, why: str = "", held_s: float | None = None, slot: int | str | None = None,
                slots: int | None = None, stream: TextIO | None = None) -> None:
    """One JSON line in ``<lock path>.log`` for every gated run, whatever the
    lock did: ``taken`` at once, ``waited`` behind a holder
    (the wait's start, end and length), ``inside`` its holder (passed
    through), ``gave_up`` past the waiter's own bound (``why`` names it), or
    ``unguarded`` (not taken, and ``why``); and one more for every hold,
    ``released`` (:meth:`BoxLock.release`), whose ``held_s`` is the hold's
    length and whose start is the take, its wait left on its acquire line.
    The log held waits alone, so an empty one could not say whether no run
    waited or no run was gated (DEF-4053); now it is empty only where no gated
    run came. Every line names its ``slot`` (the slot a parallel line took,
    ``every`` for a serial line's hold, the holder's slot a nested run passed
    through, None where none was taken) and ``slots``, the box's count as the
    run read it (None where it was never read), so the log reads how full a
    box of several slots was (DEF-2105). One log serves every slot. A log that
    cannot be written is one stderr line, never the run's cost."""
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
    except (OSError, ValueError) as exc:  # a ValueError: a path open() refuses outright (an embedded NUL)
        print(f"box lock: the log could not be written ({exc.__class__.__name__})",
              file=stream if stream is not None else sys.stderr, flush=True)


class BoxLock:
    """The hold: taken at configure on the controller, released at unconfigure.
    ``every`` is a serial line's hold, every slot of the box; otherwise the
    first slot free (:func:`takes_every_slot`)."""

    def __init__(self, path: Path, record: dict, primitive: Any, *, stream: TextIO | None = None,
                 every: bool = False) -> None:
        self.path, self.record, self.primitive = path, record, primitive
        self.stream = stream if stream is not None else sys.stderr
        self.every = every
        self.slot_paths: list[Path] = [path]
        # Each slot's open handle by its number (1 is the lock file itself),
        # and the slots this run holds, in the order it took them: a serial
        # line's are always 1 to k, since it takes them in order.
        self.handles: dict[int, TextIO] = {}
        self.taken: list[int] = []
        self.held = False  # every slot this run came for is held
        self.passed_through = False
        self.waited_s = 0.0
        # time.monotonic() at the take, set once the acquire line is logged:
        # the release's held_s reads it, and None writes no release line.
        self.taken_at: float | None = None
        self.holder_seen: dict | None = None
        self._seen: dict[int, dict] = {}  # the last record each refusing slot held

    @property
    def fh(self) -> TextIO | None:
        """The first open handle (slot 1's), None once every one is closed."""
        return next(iter(self.handles.values()), None)

    def _slot_label(self) -> int | str | None:
        return EVERY_SLOT if self.every else (self.taken[0] if self.taken else None)

    def acquire(self) -> None:
        """Take the slots, or pass through on the inherited pair. A failure
        after a handle is open releases what was taken and closes every handle
        before it is re-raised, so a run that goes unguarded never keeps the
        box. The lock's own folder is made where it is missing (the launcher's
        default, ``~/.espalier``, is not there until a first run makes it:
        DEF-4053), one level and never a chain, so a mistyped path still goes
        unguarded and says so rather than building folders."""
        self.path.parent.mkdir(exist_ok=True)
        try:
            paths, note = self.primitive.box_lock_slots(str(self.path))
            if note:
                print(note, file=self.stream, flush=True)
            self.slot_paths = [Path(p) for p in paths]
            for number, slot in enumerate(self.slot_paths, 1):
                self.handles[number] = open(slot, "a+", encoding="utf-8")
            self._acquire()
        except BaseException:
            self.release()
            raise

    def _write(self, number: int, *, draining: bool = False) -> None:
        """This run's record into the slot it holds, with that slot's label;
        ``draining`` while a serial line waits for the rest of the box."""
        fh = self.handles[number]
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps({**self.record, "slot": self._slot_label() if self.every else number,
                             **({"draining": True} if draining else {})}))
        fh.flush()

    def _try_take(self) -> tuple[bool, list[dict | None]]:
        """One try at the slots this run comes for: whether it now holds them
        all, and the records of the slots that refused it, read after the
        refusal. A serial line takes the slots in order and keeps each it gets,
        so two serial lines never hold half the box each; a parallel line
        takes the first free slot, and stops at slot 1 when a serial line's
        record is there, so it waits behind that line rather than beside it."""
        refused: list[dict | None] = []
        for number in range(1, len(self.slot_paths) + 1):
            if number in self.taken:
                continue
            if self.primitive.try_lock_file(self.handles[number]):
                self.taken.append(number)
                if not self.every:
                    return True, refused
                if len(self.taken) < len(self.slot_paths):
                    # Stamped at this take, rewritten whole at the last one.
                    self.record["started"] = _now_stamp()
                    self._write(number, draining=True)
                continue
            record = read_record(self.slot_paths[number - 1])
            if record:
                self._seen[number] = record
            refused.append(record)
            if self.every:
                return False, refused  # in order, or two serial lines could each hold half the box
            if number == 1 and not parallel_record(record):
                # A serial line's record, an older checkout's (which locks the
                # lock file alone, whatever the count, and writes no slot), or
                # one caught between a take and its write: wait, never beside
                # it. Behind it, the later slots' holders are named too, the
                # one a serial line waits for among them (both reviews).
                refused += [read_record(slot) for slot in self.slot_paths[1:]]
                return False, refused
        return bool(self.taken) and len(self.taken) == (len(self.slot_paths) if self.every else 1), refused

    def _acquire(self) -> None:
        started = time.monotonic()
        bound = wait_bound(os.environ.get(WAIT_KEY), stream=self.stream)
        last_report: float | None = None
        while True:
            # The inherited pair before any slot (8dda84's review): tried
            # first, a nested run whose parent holds slot 2 would take slot 1.
            if not self.taken:
                for number, slot in enumerate(pair_paths(self.path, self.slot_paths,
                                                         self.primitive.BOX_LOCK_MAX_SLOTS), 1):
                    record = read_record(slot)
                    if inside_holder(record):
                        assert record is not None
                        self.passed_through = True
                        self.holder_seen = record
                        self.release()
                        log_outcome(self.path, "inside", self.record, record, slot=record.get("slot", number),
                                    slots=len(self.slot_paths), stream=self.stream)
                        return
            done, refused = self._try_take()
            if done:
                self.held = True
                taken_at = time.monotonic()
                # The hold's age, never the queue's: stamped at configure, a
                # run that queued forty minutes read forty minutes older than
                # it was, and past the ceiling sooner (DEF-4077).
                self.record["started"] = _now_stamp()
                for number in self.taken:
                    self._write(number)
                os.environ[HOLDER_KEY] = str(os.getpid())
                if last_report is not None:
                    self.waited_s = time.monotonic() - started
                self.holder_seen = self._seen.get(self.taken[-1]) or self.holder_seen
                log_outcome(self.path, "waited" if last_report is not None else "taken", self.record,
                            self.holder_seen, self.waited_s, slot=self._slot_label(),
                            slots=len(self.slot_paths), stream=self.stream)
                # Set once the acquire line is down, so a failure between the
                # take and that line releases without an orphan release line.
                self.taken_at = taken_at
                return
            self.holder_seen = next((r for r in reversed(refused) if r), None) or self.holder_seen
            now = time.monotonic()
            if last_report is None or now - last_report >= REPORT_S:
                # One line for each holder in the way, each named once; one
                # "no holder record" line where no refusing slot had a record.
                named: list[dict] = []
                for record in refused:
                    if record and all(r.get("pid") != record.get("pid") for r in named):
                        named.append(record)
                for shown in named or [None]:
                    print(waiting_line(shown, waited_s=now - started, read_seat=holder_seat_live),
                          file=self.stream, flush=True)
                last_report = now
            # The bound reads the clock after the line, whose seat read past
            # the ceiling takes time of its own.
            if bound is not None and time.monotonic() - started >= bound:
                self._give_up(time.monotonic() - started, bound)
            time.sleep(POLL_S)

    def _give_up(self, waited_s: float, bound: float) -> NoReturn:
        """Past the waiter's bound the run ends before any test, distinctly: a
        log line, then ``pytest.exit`` with ``DID_NOT_RUN_EXIT``, which pytest
        writes on stderr at configure; ``pytest_configure`` lets it through
        (DEF-4056)."""
        self.waited_s = waited_s
        log_outcome(self.path, "gave_up", self.record, self.holder_seen, waited_s,
                    why=f"{WAIT_KEY}={bound:g}", slots=len(self.slot_paths), stream=self.stream)
        holder = self.holder_seen
        who = (f"{holder.get('seat') or '?'} {holder.get('lane') or '?'} (pid {holder.get('pid')})"
               if holder else "a holder that left no record")
        pytest.exit(_ascii(f"box lock: did not run: waited {waited_s:.0f} s behind {who}, past "
                           f"{WAIT_KEY}={bound:g}; no test ran"), returncode=DID_NOT_RUN_EXIT)

    def pytest_terminal_summary(self, terminalreporter: Any) -> None:
        """What the lock did, in the line ``-q`` keeps (the never-ran count's
        pattern): nothing for a run that took the lock at once, and nothing
        under ``--no-summary`` (pytest 9.2.0 calls the hook under it too and
        leaves the gating to the plugin)."""
        if getattr(terminalreporter, "no_summary", False):
            return
        holder = self.holder_seen or {}
        who = f"{holder.get('seat') or '?'} {holder.get('lane') or '?'} (pid {holder.get('pid')})"
        if self.passed_through:
            terminalreporter.write_line(_ascii(f"box lock: inside the holder {who}"))
        elif self.waited_s:
            terminalreporter.write_line(_ascii(f"box lock: waited {self.waited_s:.0f} s behind {who}"))

    def release(self) -> None:
        """Clear the record in every slot this run holds, log the hold's
        ``released`` line, unlock them, and close every handle. The line is
        written while the slots are still held, so in the log it comes before
        the next run's acquire line and a reader pairs each hold's two lines
        in file order; written after the unlock, a waiter's ``waited`` line
        could land first (DEF-3084). A run that never held writes none, nor
        one whose acquire failed before its acquire line (a serial line that
        gave up holding part of the box among them: its slots are cleared and
        unlocked all the same), and neither does a holder that is killed: the
        kernel frees its locks with the process, so its acquire line stands
        alone and its hold's end is bounded only by the next acquire."""
        if not self.handles:
            return
        try:
            for number in self.taken:
                fh = self.handles[number]
                fh.seek(0)
                fh.truncate()
                fh.flush()
            if self.held and self.taken_at is not None:
                log_outcome(self.path, "released", self.record, held_s=time.monotonic() - self.taken_at,
                            slot=self._slot_label(), slots=len(self.slot_paths), stream=self.stream)
            for number in self.taken:
                self.primitive.unlock_file(self.handles[number])
        finally:
            for fh in self.handles.values():
                try:
                    fh.close()
                except OSError:  # one handle's close never keeps the others' slots
                    pass
            self.handles.clear()
            self.taken.clear()
            self.held = False

    def pytest_unconfigure(self, config: Any) -> None:
        self.release()


class _Unguarded:
    """The summary line of a run the lock could not be taken for: the one
    stderr line at configure scrolls off a 30-minute run, this one does not."""

    def __init__(self, why: str) -> None:
        self.why = why

    def pytest_terminal_summary(self, terminalreporter: Any) -> None:
        """Nothing under ``--no-summary``, as :meth:`BoxLock.pytest_terminal_summary`."""
        if getattr(terminalreporter, "no_summary", False):
            return
        terminalreporter.write_line(_ascii(f"box lock: unguarded ({self.why})"))


def pytest_configure(config: Any) -> None:
    """Take the box lock on the process that runs the controller, once: never
    on an xdist worker (it inherits the pair), never without the variable,
    never on a run the gate leaves alone. Every read of the config sits inside
    the try: a stub config with no options (the suite's own configure tests)
    takes nothing and raises nothing."""
    if hasattr(config, "workerinput"):
        return
    path = os.environ.get(LOCK_KEY)
    if not path:
        return
    manager = getattr(config, "pluginmanager", None)
    if manager is None or manager.hasplugin(PLUGIN_NAME):
        return
    record: dict | None = None
    try:
        if not gated(config):
            return
        path = current_path(path)
        primitive = _primitive()
        record = build_record(config, primitive)
        lock = BoxLock(Path(path), record, primitive, every=takes_every_slot(config))
        lock.acquire()
    except pytest.exit.Exception:
        # The bounded wait's end (DEF-4056). pytest's Exit subclasses
        # Exception, so the clause below would swallow it and run unguarded.
        raise
    except Exception as exc:  # noqa: BLE001 -- a lock that cannot be taken must not cost a seat its tier
        why = f"{type(exc).__name__}: {_ascii(str(exc))}"
        print(f"box lock: not taken ({why}); this run is unguarded", file=sys.stderr, flush=True)
        log_outcome(Path(path), "unguarded", record or {"pid": os.getpid()}, why=why)
        manager.register(_Unguarded(why), PLUGIN_NAME)
        return
    manager.register(lock, PLUGIN_NAME)
