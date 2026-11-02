"""Remove, at a session's start, the temp dirs a killed test run left.

pytest numbers each session's base temp dir under ``<temp root>/pytest-of-<user>``
and writes the owning process's pid into its ``.lock``; at session finish it
drops the lock and removes the numbered dirs past the newest three (an exit
handler is the fallback). A run that ends before session finish -- a tool's
timeout kill, the timeout backstop's ``os._exit`` in a test that outlived its
ceiling, the low-memory reaper -- keeps its lock, and pytest's cleanup reads
only the lock's age (``LOCK_TIMEOUT``, 72 h), so each such dir stays three
days: 13 of them held 32 GB on the Air on 2026-11-01 (``DEF-5053``).

At the controller's configure, before any worker is spawned or base temp dir
made, this removes each dir under the prefixes below whose ``.lock`` names a
pid that ``tools/cc/checkout_sync.py::pid_alive`` says is gone. Kept: a live
pid, a pid this host cannot ask about (``None``, or a liveness check that
raises), a dir with no lock or an unreadable one, a symlink, an entry another
user owns, and ``pytest-current`` with the dir it names (the newest run's, for
whoever reads it next). The lock goes last, so a delete cut short -- by a fault
in one file, or past ``SWEEP_BUDGET_S`` -- is taken up again at the next start.
Two makers outside pytest's root write the same lock into the work dirs they
make in the system temp dir: ``scripts/archive_probe.py`` and
``tests/_live_tree.py::checkout_copy``. The first sweep on the Air removed 13
dirs, 32 GB and about 1.9 million inodes, in 150 s (2026-11-01, before the
budget), so a killed full tier's dir (about 450,000 files) costs the next start
about half a minute. The timeout backstop drops its own lock before it ends a
test's process by ``os._exit`` (:func:`release_own_lock`), which leaves that
dir to pytest's own cleanup like any finished run's.

Skipped without a word: an xdist worker; a run started inside a test
(``PYTEST_CURRENT_TEST`` inherited: a nested session must not spend its test's
ceiling on a delete); a run that runs no test (``--collect-only`` and its
kin). ``ESPALIER_TEMP_SWEEP`` set to anything but ``1`` turns it off, and the
terminal summary says so, since a switch left in a shell profile would bring
the pile back unseen. It keeps nothing from another seat's start on the same
box: copy a killed run's dir out to read it later. Before deleting, one stderr
line names what goes; after, the terminal summary says what went. A sweep that
cannot run is one line, and the session proceeds. Registered from
``tests/conftest.py::pytest_configure``; pinned by ``tests/test_temp_sweep.py``.
"""
from __future__ import annotations

import getpass
import importlib.util
import os
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

try:
    from tests._never_ran import NO_TEST_RUNS
except ImportError:  # the suite's conftest imports its helpers bare, with tests/ on sys.path
    from _never_ran import NO_TEST_RUNS  # type: ignore[no-redef]

PLUGIN_NAME = "espalier-temp-sweep"
#: Anything but unset, empty or ``1`` turns the sweep off.
SKIP_KEY = "ESPALIER_TEMP_SWEEP"
#: pytest's own lock file in a numbered dir, holding the owner's pid.
LOCK_NAME = ".lock"
#: Under pytest's root: its numbered dirs, and the ``garbage-*`` its own
#: cleanup renames a dir to before deleting it (left when that delete is cut).
PYTEST_PREFIXES = ("pytest-", "garbage-")
#: The link pytest points at its newest numbered dir.
CURRENT_LINK = "pytest-current"
#: Under the system temp dir: the makers that write ``LOCK_NAME`` into the
#: work dirs they make.
OWNED_PREFIXES = ("espalier-archive-probe-", "checkout-copy-")
#: The most a start spends deleting, checked between a dir's children: under a
#: tool call's two-minute default with a dir's child in flight; what is left
#: keeps its lock for the next start.
SWEEP_BUDGET_S = 60.0
#: Options under which configure runs but no test does.
_NO_TEST_OPTIONS = (*NO_TEST_RUNS, "help", "markers")
#: How many names a line spells before it counts the rest.
_NAMED = 5

_REPO = Path(__file__).resolve().parent.parent
_TOOLS_CC_PREFIX = os.path.normcase(str(_REPO / "tools" / "cc")).replace("\\", "/") + "/"


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def pytest_root() -> Path:
    """Where pytest numbers its base temp dirs, by ``_pytest.tmpdir``'s own
    rule: ``PYTEST_DEBUG_TEMPROOT``, else the system temp dir, then
    ``pytest-of-<user>``, or ``pytest-of-unknown`` where the user cannot be
    read or pytest fell back to it."""
    temproot = Path(os.environ.get("PYTEST_DEBUG_TEMPROOT") or tempfile.gettempdir()).resolve()
    try:
        user = getpass.getuser()
    except (ImportError, OSError, KeyError):
        user = None
    root = temproot / f"pytest-of-{user or 'unknown'}"
    unknown = temproot / "pytest-of-unknown"
    return unknown if not root.is_dir() and unknown.is_dir() else root


def lock_pid(directory: Path) -> int | None:
    """The pid in ``directory``'s lock, or None: no lock, an unreadable one,
    or one that does not hold a positive number."""
    try:
        text = (directory / LOCK_NAME).read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return int(text) if text.isdigit() and int(text) > 0 else None


def write_lock(directory: Path) -> None:
    """Mark ``directory`` as this process's, in pytest's lock shape."""
    (directory / LOCK_NAME).write_text(str(os.getpid()), encoding="ascii")


def release_own_lock(root: Path | None = None) -> list[str]:
    """Drop the lock of each numbered dir under pytest's root (``root`` when
    given) that names this process, as pytest's session finish would, for a
    process about to end by ``os._exit`` before it. Returns the names whose
    lock went."""
    root = pytest_root() if root is None else root
    pid = os.getpid()
    dropped: list[str] = []
    try:
        entries = sorted(os.scandir(root), key=lambda entry: entry.name)
    except OSError:
        return dropped
    for entry in entries:
        try:
            if not entry.name.startswith("pytest-") or entry.is_symlink():
                continue
            path = Path(entry.path)
            if lock_pid(path) != pid:
                continue
            (path / LOCK_NAME).unlink()
        except OSError:
            continue
        dropped.append(entry.name)
    return dropped


def current_target(root: Path) -> Path | None:
    """The dir ``root``'s ``pytest-current`` link names, or None."""
    link = root / CURRENT_LINK
    return Path(os.path.realpath(link)) if link.is_symlink() else None


def _load(path: Path, alias: str) -> Any:
    """``path`` as a module under ``alias``, once. ``sys.path`` and the bare
    ``tools/cc`` names its imports add are put back, so a load at configure
    changes nothing a test resolves later (``checkout_sync`` puts its own
    directory first on ``sys.path`` and imports ``_json_safe`` bare)."""
    if alias in sys.modules:
        return sys.modules[alias]
    saved_path, saved = list(sys.path), set(sys.modules)
    spec = importlib.util.spec_from_file_location(alias, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(alias, None)
        raise
    finally:
        sys.path[:] = saved_path
        for name in set(sys.modules) - saved - {alias}:
            where = os.path.normcase(getattr(sys.modules[name], "__file__", None) or "").replace("\\", "/")
            if where.startswith(_TOOLS_CC_PREFIX):
                del sys.modules[name]
    return mod


def pid_alive() -> Callable[[object], bool | None]:
    """``tools/cc/checkout_sync.py::pid_alive``: never ``os.kill(pid, 0)`` on
    Windows, where signal 0 interrupts the process instead of asking."""
    return _load(_REPO / "tools" / "cc" / "checkout_sync.py", "_temp_sweep_checkout_sync").pid_alive


def deleter() -> Any:
    """``espalier/_rmtree.py``, whose deletes clear the read-only bit Windows
    puts on every git packfile before they retry."""
    return _load(_REPO / "espalier" / "_rmtree.py", "_temp_sweep_rmtree")


def remove(directory: Path, rm: Any, *, deadline: float | None = None) -> bool:
    """Delete ``directory``'s contents, then its lock, then the dir; True once
    it is gone. While anything else in it would not go, or once ``deadline``
    (a ``time.monotonic`` reading) has passed, the lock stays, so the next
    start takes it up again."""
    try:
        for child in directory.iterdir():
            if child.name == LOCK_NAME:
                continue
            if deadline is not None and time.monotonic() > deadline:
                return False
            if child.is_dir() and not child.is_symlink():
                rm.remove_tree(child, best_effort=True)
            else:
                rm.remove_file(child, best_effort=True)
        if any(child.name != LOCK_NAME for child in directory.iterdir()):
            return False
        (directory / LOCK_NAME).unlink(missing_ok=True)
        directory.rmdir()
    except OSError:
        return False
    return True


def dead_dirs(root: Path, prefixes: Iterable[str], *, alive: Callable[[object], bool | None],
              keep: Iterable[Path] = ()) -> list[Path]:
    """The dirs directly under ``root`` named with one of ``prefixes`` whose
    lock names a pid ``alive`` answers False for (a check that raises keeps
    the dir)."""
    prefixes = tuple(prefixes)
    kept = {os.path.normcase(str(path)) for path in keep}
    uid = os.getuid() if hasattr(os, "getuid") else None
    found: list[Path] = []
    try:
        entries = sorted(os.scandir(root), key=lambda entry: entry.name)
    except OSError:
        return found
    for entry in entries:
        if not entry.name.startswith(prefixes):
            continue
        try:
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                continue
            if uid is not None and entry.stat(follow_symlinks=False).st_uid != uid:
                continue
            path = Path(entry.path)
            if os.path.normcase(str(path)) in kept:
                continue
            pid = lock_pid(path)
            if pid is None or alive(pid) is not False:
                continue
        except Exception:  # noqa: BLE001 -- one entry this host cannot read is kept, and the rest are still read
            continue
        found.append(path)
    return found


def remove_all(paths: Iterable[Path], rm: Any, *, deadline: float | None = None) -> tuple[list[str], list[str]]:
    """Remove each of ``paths``; the names that went and the names left (a
    fault in one is that one left, and the rest are still tried)."""
    removed: list[str] = []
    left: list[str] = []
    for path in paths:
        try:
            gone = remove(path, rm, deadline=deadline)
        except Exception:  # noqa: BLE001 -- a delete that faults leaves its lock for the next start
            gone = False
        (removed if gone else left).append(path.name)
    return removed, left


def sweep(root: Path, prefixes: Iterable[str], *, alive: Callable[[object], bool | None], rm: Any,
          keep: Iterable[Path] = (), deadline: float | None = None) -> tuple[list[str], list[str]]:
    """:func:`dead_dirs` under ``root``, then :func:`remove_all` of them."""
    return remove_all(dead_dirs(root, prefixes, alive=alive, keep=keep), rm, deadline=deadline)


def _names(names: list[str]) -> str:
    shown = ", ".join(names[:_NAMED])
    return shown + (f" and {len(names) - _NAMED} more" if len(names) > _NAMED else "")


def summary(removed: list[str], left: list[str], seconds: float) -> str | None:
    """The line a sweep prints at the end, or None when it touched nothing."""
    if not removed and not left:
        return None
    parts = []
    if removed:
        parts.append(f"removed {len(removed)} dir(s) a dead run left ({_names(removed)}) in {seconds:.1f} s")
    if left:
        parts.append(f"{len(left)} left for the next start ({_names(left)}): past the "
                     f"{SWEEP_BUDGET_S:g} s budget, or a file that would not go")
    return "temp sweep: " + "; ".join(parts)


def switched_off() -> str | None:
    """The switch's value when it turns the sweep off, else None."""
    value = os.environ.get(SKIP_KEY)
    return None if value in (None, "", "1") else value


def skipped(config: Any) -> bool:
    """Whether this session leaves the temp dirs alone without a word (the
    module docstring says when)."""
    if hasattr(config, "workerinput"):
        return True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    opt = getattr(config, "option", None)
    if opt is None:  # a stub config (the suite's own configure tests)
        return True
    return any(getattr(opt, name, False) for name in _NO_TEST_OPTIONS)


def run() -> str | None:
    """Sweep pytest's root and the system temp dir; the summary line."""
    started = time.monotonic()
    alive, rm = pid_alive(), deleter()
    root = pytest_root()
    current = current_target(root)
    found = (dead_dirs(root, PYTEST_PREFIXES, alive=alive, keep=[current] if current else [])
             + dead_dirs(Path(tempfile.gettempdir()).resolve(), OWNED_PREFIXES, alive=alive))
    if not found:
        return None
    print(_ascii(f"temp sweep: removing {len(found)} dir(s) a dead run left "
                 f"({_names([p.name for p in found])}), for at most {SWEEP_BUDGET_S:g} s"),
          file=sys.stderr, flush=True)
    removed, left = remove_all(found, rm, deadline=started + SWEEP_BUDGET_S)
    return summary(removed, left, time.monotonic() - started)


class _Said:
    """The sweep's line again at the end: the stderr line at configure
    scrolls off a long run."""

    def __init__(self, line: str) -> None:
        self.line = line

    def pytest_terminal_summary(self, terminalreporter: Any) -> None:
        if getattr(terminalreporter, "no_summary", False):
            return
        terminalreporter.write_line(self.line)


def pytest_configure(config: Any) -> None:
    """Sweep once, on the process that runs the controller."""
    if skipped(config):
        return
    manager = getattr(config, "pluginmanager", None)
    if manager is None or manager.hasplugin(PLUGIN_NAME):
        return
    value = switched_off()
    if value is not None:
        line: str | None = (f"temp sweep: off ({SKIP_KEY}={value!r}); the dirs a dead run left stay "
                            "until it is unset")
    else:
        try:
            line = run()
        except Exception as exc:  # noqa: BLE001 -- a sweep that cannot run must not cost the session
            line = f"temp sweep: did not run ({type(exc).__name__}: {exc})"
        if line is not None:
            print(_ascii(line), file=sys.stderr, flush=True)
    if line is not None:
        manager.register(_Said(_ascii(line)), PLUGIN_NAME)
