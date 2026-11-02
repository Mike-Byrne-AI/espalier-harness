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
from the config, so ``PYTEST_ADDOPTS=-n`` counts and ``-n 0`` takes none; every
tier line is an xdist run, the contract slice included, and a tier's lines each
take and release the lock, so two tiers interleave line by line; a run without
``-n``, as a reviewer's or an agent's node-id or file run is, takes no lock and
never waits past a Bash call's cap), the controller takes a lock on that file
before any worker is spawned, through the primitive's non-blocking
``try_lock_file``. While another run holds it, this one polls, says who holds
it (seat, lane, pid, how long) on stderr at once and then once per report
interval, with an inspect command and the stop command once the holder itself
is past a ceiling. Every gated run appends one JSON line to
``<lock path>.log`` saying what the lock did -- taken at once, waited (how
long, behind whom), passed through inside its holder, or unguarded (why) --
so the record the roadmap's re-measure reads is empty only where no gated
run came, never merely where none waited (DEF-4053). The launcher's old
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
import os
import re
import subprocess
import sys
import tempfile
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
#: A holder past this age is named with the inspect and stop commands: above
#: the post-merge proof's measured worst case (48.2 minutes over ten runs to
#: 2026-10-16). Keyed on the holder's own age, never on this waiter's wait: the
#: lock is not fair, and a waiter that lost several races must not be told to
#: end a healthy holder two minutes into its line.
WAIT_CEILING_MIN = 60
#: Options under which configure runs but no test does: the never-ran count's
#: collect-only set, plus ``--help`` and ``--markers``.
_NO_TEST_OPTIONS = (*NO_TEST_RUNS, "help", "markers")

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
    opt = getattr(config, "option", None)
    if opt is None:  # a stub config (the suite's own configure tests)
        return False
    if any(getattr(opt, name, False) for name in _NO_TEST_OPTIONS):
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


def waiting_line(record: dict | None, *, waited_s: float) -> str:
    """The line a waiter prints: the holder's seat, lane and pid, how long it
    has held (from its record's start, else this waiter's wait), the head of
    its argv, and past the ceiling the command that kills it by pid; ``no
    holder record`` where the file is empty or unreadable. ASCII only."""
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
        who = f"{record.get('seat') or '?'} {record.get('lane') or '?'} (pid {shown}, held {held_min} min)"
    else:
        who = "no holder record"
    head = _argv_head((record or {}).get("argv") or [])
    line = f"box lock: waiting on {who}" + (f": {head}" if head else "")
    if pid is not None and held_min >= WAIT_CEILING_MIN:
        if sys.platform == "win32":
            look, stop = f"tasklist /FI \"PID eq {pid}\"", f"taskkill /T /F /PID {pid}"
        else:
            look, stop = f"ps -p {pid} -o etime,command", f"kill -9 {pid}"
        line += f" -- the holder is past {WAIT_CEILING_MIN} min: inspect it with `{look}`; a stuck one ends with `{stop}`"
    return _ascii(line)


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
            "argv": [os.path.basename(str(sys.argv[0])), *[str(a) for a in sys.argv[1:9]]] if sys.argv else []}


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
                *, why: str = "", stream: TextIO | None = None) -> None:
    """One JSON line in ``<lock path>.log`` for every gated run, whatever the
    lock did: ``taken`` at once, ``waited`` behind a holder
    (the wait's start, end and length), ``inside`` its holder (passed
    through), or ``unguarded`` (not taken, and ``why``). The log held waits
    alone, so an empty one could not say whether no run waited or no run was
    gated (DEF-4053); now it is empty only where no gated run came. A log that
    cannot be written is one stderr line, never the run's cost."""
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
    except (OSError, ValueError) as exc:  # a ValueError: a path open() refuses outright (an embedded NUL)
        print(f"box lock: the log could not be written ({exc.__class__.__name__})",
              file=stream if stream is not None else sys.stderr, flush=True)


class BoxLock:
    """The hold: taken at configure on the controller, released at unconfigure."""

    def __init__(self, path: Path, record: dict, primitive: Any, *, stream: TextIO | None = None) -> None:
        self.path, self.record, self.primitive = path, record, primitive
        self.stream = stream if stream is not None else sys.stderr
        self.fh: TextIO | None = None
        self.held = False
        self.passed_through = False
        self.waited_s = 0.0
        self.holder_seen: dict | None = None

    def acquire(self) -> None:
        """Take the lock, or pass through on the inherited pair. A failure
        after the handle is open releases or closes it before it is re-raised,
        so a run that goes unguarded never keeps the box. The lock's own
        folder is made where it is missing (the launcher's default,
        ``~/.espalier``, is not there until a first run makes it: DEF-4053),
        one level and never a chain, so a mistyped path still goes unguarded
        and says so rather than building folders."""
        self.path.parent.mkdir(exist_ok=True)
        self.fh = open(self.path, "a+", encoding="utf-8")
        try:
            self._acquire()
        except BaseException:
            if self.held:
                self.release()
            elif self.fh is not None:
                self.fh.close()
                self.fh = None
            raise

    def _acquire(self) -> None:
        assert self.fh is not None
        started = time.monotonic()
        last_report: float | None = None
        while True:
            if self.primitive.try_lock_file(self.fh):
                self.held = True
                self.fh.seek(0)
                self.fh.truncate()
                self.fh.write(json.dumps(self.record))
                self.fh.flush()
                os.environ[HOLDER_KEY] = str(os.getpid())
                if last_report is not None:
                    self.waited_s = time.monotonic() - started
                log_outcome(self.path, "waited" if last_report is not None else "taken", self.record,
                            self.holder_seen, self.waited_s, stream=self.stream)
                return
            record = read_record(self.path)
            if inside_holder(record):
                self.passed_through = True
                self.holder_seen = record
                self.fh.close()
                self.fh = None
                log_outcome(self.path, "inside", self.record, record, stream=self.stream)
                return
            self.holder_seen = record or self.holder_seen
            now = time.monotonic()
            if last_report is None or now - last_report >= REPORT_S:
                print(waiting_line(record, waited_s=now - started), file=self.stream, flush=True)
                last_report = now
            time.sleep(POLL_S)

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
        lock = BoxLock(Path(path), record, primitive)
        lock.acquire()
    except Exception as exc:  # noqa: BLE001 -- a lock that cannot be taken must not cost a seat its tier
        why = f"{type(exc).__name__}: {_ascii(str(exc))}"
        print(f"box lock: not taken ({why}); this run is unguarded", file=sys.stderr, flush=True)
        log_outcome(Path(path), "unguarded", record or {"pid": os.getpid()}, why=why)
        manager.register(_Unguarded(why), PLUGIN_NAME)
        return
    manager.register(lock, PLUGIN_NAME)
