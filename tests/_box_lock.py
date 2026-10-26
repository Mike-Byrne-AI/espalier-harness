"""One pytest tier at a time on one machine, by construction.

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
from the config, so ``PYTEST_ADDOPTS=-n`` counts and ``-n 0`` takes none; a
node-id, file or contract-slice run takes no lock, so a reviewer's or an agent's
run never waits past a Bash call's cap), the controller takes a lock on that
file before any worker is spawned, through the primitive's non-blocking
``try_lock_file``. While another run holds it, this one polls, says who holds
it (seat, lane, pid, how long) on stderr at once and then once per report
interval, past a ceiling with the command that kills the holder by pid, and
appends one JSON line per wait to ``<lock path>.log`` (the record the roadmap's
re-measure reads). Once held it writes its own record into the file and exports
``ESPALIER_BOX_LOCK_HOLDER=<pid>`` to every child, so a nested run (xdist's
workers, the stage-one smoke) that inherits the pair and finds the record's pid
alive passes through; a dead holder's pid in the pair is no pass, and an empty
or unreadable record under a held lock is said and waited on. The lock goes
when the handle closes or the process dies, so a killed holder frees its
waiter at once (3 to 14 ms over five kills on macOS, 2026-10-25); an orphaned
pytest tree keeps it and is named, which is the remedy.

Registered from ``tests/conftest.py::pytest_configure`` beside the never-ran
count, or by ``-p tests._box_lock`` on a scratch run; never on an xdist worker.
A failure inside the plugin is one stderr line and the run proceeds unguarded,
since a lock that cannot be taken must not cost a seat its tier. The primitive
is ``tools/cc/_json_safe.py``, loaded by path as the suite's helpers do.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

try:
    from tests._never_ran import NO_TEST_RUNS
except ImportError:  # the suite's conftest imports its helpers bare, with tests/ on sys.path
    from _never_ran import NO_TEST_RUNS  # type: ignore[no-redef]

#: The name the plugin object is registered under.
PLUGIN_NAME = "espalier-box-lock"
LOCK_KEY = "ESPALIER_BOX_LOCK"
HOLDER_KEY = "ESPALIER_BOX_LOCK_HOLDER"
#: How often a waiter tries the lock, and how often it repeats the holder line.
POLL_S = 0.25
REPORT_S = 30.0
#: Past this wait the line carries the kill command: above the post-merge
#: proof's measured worst case (48.2 minutes over ten runs to 2026-10-16).
WAIT_CEILING_MIN = 60

_TOOLS_CC = Path(__file__).resolve().parent.parent / "tools" / "cc"
_LOCK_WORD = re.compile(r"\bESPALIER_BOX_LOCK\b")
_HOLDER_WORD = re.compile(r"\bESPALIER_BOX_LOCK_HOLDER\b")
_PREFIX_STRIP = re.compile(r"""startswith\(\s*\(?\s*['"]ESPALIER_BOX_LOCK['"]""")


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
    opt = config.option
    if any(getattr(opt, name, False) for name in NO_TEST_RUNS):
        return False
    return getattr(opt, "numprocesses", None) not in (None, 0)


def holder_alive(pid: int) -> bool:
    """Whether ``pid`` is a live process: ``kill -0`` on POSIX, an opened
    handle whose exit code is still-active on Windows."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
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
    except OSError:
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


def waiting_line(record: dict | None, *, waited_s: float) -> str:
    """The line a waiter prints: the holder's seat, lane and pid, how long it
    has held (from its record's start, else this waiter's wait), the head of
    its argv, and past the ceiling the command that kills it by pid; ``no
    holder record`` where the file is empty or unreadable. ASCII only."""
    held_min = int(waited_s // 60)
    if record and "pid" in record:
        pid: Any = record.get("pid")
        started = record.get("started")
        if isinstance(started, str):
            try:
                since = datetime.fromisoformat(started.replace("Z", "+00:00"))
                held_min = max(held_min, int((datetime.now(timezone.utc) - since).total_seconds() // 60))
            except ValueError:
                pass
        who = f"{record.get('seat') or '?'} {record.get('lane') or '?'} (pid {pid}, held {held_min} min)"
    else:
        pid, who = None, "no holder record"
    head = " ".join(str(a) for a in (record or {}).get("argv") or [])[:60]
    line = f"box lock: waiting on {who}" + (f": {head}" if head else "")
    if pid is not None and waited_s >= WAIT_CEILING_MIN * 60:
        cmd = f"taskkill /T /F /PID {pid}" if sys.platform == "win32" else f"kill -9 {pid}"
        line += f" -- past {WAIT_CEILING_MIN} min; a dead or stuck holder is freed with: {cmd}"
    return _ascii(line)


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
    """This run's holder record, built before the try: seat and lane from git
    (two seconds each, ``?`` on failure), pid, the start in UTC, the argv head."""
    cwd = str(getattr(config, "rootpath", None) or Path.cwd())

    def git(*args: str) -> str:
        try:
            proc = primitive.run_bounded(["git", *args], cwd=cwd, capture_output=True, text=True,
                                         encoding="utf-8", errors="replace", timeout=2.0)
        except (OSError, subprocess.SubprocessError):
            return "?"
        return (proc.stdout.strip() or "?") if proc.returncode == 0 else "?"

    return {"seat": git("config", "espalier.machine"), "lane": git("rev-parse", "--abbrev-ref", "HEAD"),
            "pid": os.getpid(), "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "argv": [str(a) for a in sys.argv[:8]]}


class BoxLock:
    """The hold: taken at configure on the controller, released at unconfigure."""

    def __init__(self, path: Path, record: dict, primitive: Any, *, stream: TextIO | None = None) -> None:
        self.path, self.record, self.primitive = path, record, primitive
        self.stream = stream if stream is not None else sys.stderr
        self.fh: TextIO | None = None
        self.held = False
        self.passed_through = False

    def acquire(self) -> None:
        self.fh = open(self.path, "a+", encoding="utf-8")
        started = time.monotonic()
        last_report: float | None = None
        holder_seen: dict | None = None
        while True:
            if self.primitive.try_lock_file(self.fh):
                self.held = True
                self.fh.seek(0)
                self.fh.truncate()
                self.fh.write(json.dumps(self.record))
                self.fh.flush()
                os.environ[HOLDER_KEY] = str(os.getpid())
                if last_report is not None:
                    self._log_wait(holder_seen, time.monotonic() - started)
                return
            record = read_record(self.path)
            if inside_holder(record):
                self.passed_through = True
                self.fh.close()
                self.fh = None
                return
            holder_seen = record or holder_seen
            now = time.monotonic()
            if last_report is None or now - last_report >= REPORT_S:
                print(waiting_line(record, waited_s=now - started), file=self.stream, flush=True)
                last_report = now
            time.sleep(POLL_S)

    def _log_wait(self, holder: dict | None, waited_s: float) -> None:
        end = datetime.now(timezone.utc)
        line = {"waiter": {k: self.record.get(k) for k in ("seat", "lane", "pid")},
                "holder": {k: (holder or {}).get(k) for k in ("seat", "lane", "pid")},
                "start": (end.timestamp() - waited_s), "end": end.isoformat(timespec="seconds"),
                "waited_s": round(waited_s, 3)}
        line["start"] = datetime.fromtimestamp(line["start"], tz=timezone.utc).isoformat(timespec="seconds")
        try:
            with open(f"{self.path}.log", "a", encoding="utf-8") as log:
                log.write(json.dumps(line) + "\n")
        except OSError as exc:
            print(f"box lock: the wait log could not be written ({exc.__class__.__name__})", file=self.stream, flush=True)

    def release(self) -> None:
        if self.fh is None or not self.held:
            return
        try:
            self.fh.seek(0)
            self.fh.truncate()
            self.fh.flush()
            self.primitive.unlock_file(self.fh)
        finally:
            self.fh.close()
            self.fh = None
            self.held = False

    def pytest_unconfigure(self, config: Any) -> None:
        self.release()


def pytest_configure(config: Any) -> None:
    """Take the box lock on the process that runs the controller, once: never
    on an xdist worker (it inherits the pair), never without the variable,
    never on a run the gate leaves alone."""
    if hasattr(config, "workerinput"):
        return
    path = os.environ.get(LOCK_KEY)
    if not path or config.pluginmanager.hasplugin(PLUGIN_NAME) or not gated(config):
        return
    try:
        primitive = _primitive()
        lock = BoxLock(Path(path), build_record(config, primitive), primitive)
        lock.acquire()
    except Exception as exc:  # noqa: BLE001 -- a lock that cannot be taken must not cost a seat its tier
        print(f"box lock: not taken ({type(exc).__name__}: {_ascii(str(exc))}); this run is unguarded",
              file=sys.stderr, flush=True)
        return
    config.pluginmanager.register(lock, PLUGIN_NAME)
