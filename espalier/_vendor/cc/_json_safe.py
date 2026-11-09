"""Safe JSON-object parsing for tools/cc (the Class-B chokepoint).

A bare ``json.loads(...).get(...)`` fails OPEN. Valid-JSON-but-non-dict input
(``[]``, ``"s"``, ``42``, ``null``) parses cleanly, then ``.get(...)`` raises
``AttributeError`` -- which sails past the usual ``except json.JSONDecodeError``
handler, so the hook exits 1 and Claude Code fail-opens per the hook protocol
(see docs/external/cc-hook-protocol.md). Rather than patch each dict-expecting
parse site, route every one through this one chokepoint.

Lives at the ``tools/cc/`` level -- sibling to ``_paths`` / ``_freshness_cache``,
the other dual-scope helpers -- so BOTH ``tools/cc/*.py`` and
``tools/cc/hooks/*.py`` import it without reaching across the hooks/ boundary.
Hooks add ``tools/cc`` to ``sys.path`` (``parent.parent``) the same way they
already do for ``_paths`` / ``_freshness_cache``.

Stdlib only; zero espalier imports (tools/cc isolation rule). The sister helper
``_hook_utils.read_stdin_safely`` covers the stdin channel; this one covers
already-read file/string/bytes content.

The class-closing regression gate lives in ``tests/test_json_dict_safe.py``:
it AST-walks tools/cc and fails on any ``json.loads``/``json.load`` whose result
is dict-dereferenced or returned without an ``isinstance(x, dict)`` guard and
not routed through here.
"""
from __future__ import annotations

import codecs
import json
import os
import sys
import time
from typing import IO, TYPE_CHECKING, Any

if TYPE_CHECKING:  # the annotation only; subprocess stays a lazy import, as in _hook_utils
    import subprocess
    from collections.abc import Callable

_MISSING = object()


def pin_utf8_streams() -> None:
    """Read stdin and write stdout and stderr as UTF-8, whatever the code page.

    On Windows without UTF-8 mode a redirected stream (a pipe: Git Bash, CI,
    Claude Code's Bash tool) uses the ANSI code page, so the first character of
    operator content outside it -- a commit subject, a summary line, a recorded
    decision -- raises ``UnicodeEncodeError`` mid-run, or reaches a file the
    caller appends to as bytes that are not UTF-8; a UTF-8 producer piped in is
    silently mis-decoded. Content may be any text; the messages around it stay
    7-bit ASCII by rule. stdin and stdout take ``errors="replace"``, so a lone
    surrogate (an undecodable file name) cannot end the run; stderr keeps its
    default ``backslashreplace``, so a diagnostic still shows what it could not
    encode. A stream without ``reconfigure`` (a test's ``StringIO``) or one
    already closed or detached is left alone, and a real console already uses
    the wide-character API, so pinning it changes nothing there.

    Called first in each CLI's ``__main__`` block, where the script's own
    directory is on ``sys.path`` -- unless ``python -P`` or ``PYTHONSAFEPATH``
    removed it, so a CLI written to survive that inserts the directory first. Twin of ``espalier/_text.py::pin_utf8_streams``
    (this tree cannot import ``espalier``), pinned equal by
    ``tests/test_surface_contract.py::test_pin_utf8_streams_two_copy_parity``.
    """
    for stream, errors in ((sys.stdin, "replace"), (sys.stdout, "replace"),
                           (sys.stderr, "backslashreplace")):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors=errors)
        except ValueError:  # closed or detached: nothing left to pin
            pass


def decode_bom(raw: bytes) -> str:
    """Decode bytes that may carry a UTF-8/16/32 byte-order mark (a PowerShell
    ``Out-File`` / editor re-encode of an otherwise byte-canonical file).
    No BOM → UTF-8. UTF-32 is checked BEFORE UTF-16 because the
    UTF-32-LE BOM (``ff fe 00 00``) starts with the UTF-16-LE BOM (``ff fe``).
    The generic ``utf-16``/``utf-32`` codecs detect endianness from the BOM and
    strip it; ``utf-8-sig`` strips a UTF-8 BOM or reads plain UTF-8. May raise
    ``UnicodeDecodeError`` on truncated/garbage bytes — callers already catch it.
    Stdlib only; mirrored in espalier.surface_contract.decode_bom and
    ci_guard._ci_decode_bom (parity-pinned)."""
    if raw[:4] in (codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE):
        return raw.decode("utf-32")
    if raw[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def fold_newlines(text: str) -> str:
    """``text`` with every CRLF and bare CR folded to a line feed: the text
    twin of ``_integrity.canonical_text_bytes`` (bytes: BOM + CRLF + CR), for
    text that is about to be handed to a tool as a file or a pipe. A body a
    Windows editor saved with CRLF went through a text-mode temp file and
    reached GitHub with every line break doubled; fold once here, write with
    ``newline=""`` there (or hand bytes over), and the host's line ending
    never enters the file."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def decode_text_or_problem(raw: bytes) -> tuple[str, str]:
    """``(text, "")`` when ``raw`` decodes through ``decode_bom`` and carries no
    NUL, else ``("", problem)`` -- ``problem`` names what is wrong and the
    encoding to re-save in, in one sentence every caller prefixes with the
    file's name. A NUL in decoded text is UTF-16 with no byte-order mark:
    ASCII in UTF-16 decodes as UTF-8 with a NUL after every character, and no
    text file the harness reads carries one on purpose.

    The one owner of that sentence for the files an operator writes by hand
    (the Stop gate's relief record, the goal snapshot, the memory file and its
    archive, the working summary; DEF-797), so the readers cannot drift apart
    on it. Mirrored in ``espalier.surface_contract.decode_text_or_problem``
    (parity-pinned beside the ``decode_bom`` pin)."""
    try:
        text = decode_bom(raw)
    except UnicodeDecodeError as exc:
        detail = f"{exc.reason} at byte {exc.start}"
    else:
        if "\x00" not in text:
            return text, ""
        detail = "NUL bytes -- UTF-16 without a byte-order mark?"
    return "", (
        f"not UTF-8 text ({detail}) -- re-save it as UTF-8; a UTF-8 or UTF-16 "
        "byte-order mark is read"
    )


def load_json_dict_safe(source: Any, *, default: Any = _MISSING) -> Any:
    """Parse ``source`` as JSON; return it iff it is a ``dict``, else ``default``.

    ``default`` is a FRESH ``{}`` when unspecified (no shared-mutable trap), so
    the caller can ``.get(...)`` the result unconditionally. Pass ``default=None``
    when "absent / invalid" must be distinguished from "empty" -- e.g. a loader
    typed ``dict | None`` whose callers branch on ``if x is None``.

    Every failure shape collapses to ``default``:
      * non-str / non-bytes input (e.g. ``None``);
      * bytes that do not decode: a UTF-8, UTF-16 or UTF-32 BOM is read through
        ``decode_bom`` (before 2026-09-15 only the UTF-8 mark was, and a UTF-16
        settings file read as the fallback -- fail-open for a reader counted as
        BOM-tolerant); bytes that are none of those fall back to a replacing
        UTF-8 decode, as before, so one bad byte inside an otherwise valid
        settings file still parses (a kill-switch scan must not miss the
        switch because of it) and only unparseable text reaches the fallback;
      * malformed JSON (``json.JSONDecodeError`` / ``ValueError``);
      * deeply-nested input on the pure-Python scanner (``RecursionError`` —
        the default C scanner is iterative and does not raise it, but a build
        without ``_json`` would; collapse it too so the guarantee is complete);
      * valid JSON that is not an object (list / string / number / ``null``).
    """
    fallback = {} if default is _MISSING else default
    if isinstance(source, (bytes, bytearray)):
        try:
            source = decode_bom(bytes(source))
        except UnicodeDecodeError:
            try:
                source = bytes(source).decode("utf-8-sig", errors="replace")
            except (UnicodeDecodeError, LookupError):
                return fallback
        except LookupError:
            return fallback
    if not isinstance(source, str):
        return fallback
    try:
        data = json.loads(source)
    except (json.JSONDecodeError, ValueError, RecursionError):
        return fallback
    return data if isinstance(data, dict) else fallback


def quoted_if_spaced(path: str) -> str:
    """``path`` double-quoted when it carries whitespace, else unchanged --
    the one quoting a pasted path needs to survive as one ARGUMENT in
    PowerShell, cmd and the POSIX shells. As a PROGRAM word it serves cmd and
    the POSIX shells only: PowerShell refuses a quoted first word, and its
    ``& "<path>"`` is a syntax error to bash (DEF-2060). It quotes whitespace
    alone: a ``$`` stays live inside double quotes in PowerShell and bash, and
    an ``&`` in an unspaced path is left bare. A double
    quote INSIDE the path is not escaped: it is illegal in a Windows filename
    (the platform this quoting is for) and rare enough on POSIX that a
    shell-specific escape would cost more than it saves."""
    return f'"{path}"' if any(ch.isspace() for ch in path) else path


def program_word(path: str, short_path: "Callable[[str], str | None] | None") -> str:
    """``path`` spelled as the PROGRAM word of a command the reader will type,
    given ``short_path``, a lookup of the path's 8.3 short form (None where the
    host has none). The hooks' twin of ``espalier/_text.py::program_word``
    (DEF-2062; tools/cc cannot import the engine), pinned to it by
    ``tests/test_json_safe_program_word.py``. A drive-rooted Windows path is
    spelled with forward slashes however it is spaced (DEF-2064): Git Bash
    drops an unquoted backslash as an escape, while PowerShell 5.1 and cmd run
    either slash. Unspaced, that is the whole change. Spaced, its short form
    with forward slashes when that is a drive-rooted word of plain characters:
    one bare word that Windows PowerShell 5.1, cmd and Git Bash all run
    (DEF-2060). Else the double-quoted path, which cmd and the POSIX shells run
    and PowerShell needs ``&`` before: a seen hook message says so through
    ``_hook_utils.powershell_call_note`` (ack 2e78b5), and a stderr line of an
    exit-0 hook takes no note, since nothing reads it. Pure text: the lookup is
    a parameter."""
    if not any(ch.isspace() for ch in path):
        return forward_if_drive_rooted(path)
    short = short_path(path) if short_path is not None else None
    if short:
        word = short.replace("\\", "/")
        # An 8.3 name keeps `&`, `(`, `'` and `$`, which each of the three
        # shells reads as grammar in a bare word, and a UNC or `\\?\` form
        # does not run with forward slashes (driven for DEF-2060).
        if _is_plain_program_word(word):
            return word
    return quoted_if_spaced(forward_if_drive_rooted(path))


def forward_if_drive_rooted(path: str) -> str:
    """``path`` with forward slashes when it is drive-rooted (``C:\\`` or
    ``C:/``, an ASCII drive letter), else unchanged: the twin of
    ``espalier/_text.py::forward_if_drive_rooted`` (DEF-2064). A UNC or
    ``\\\\?\\`` form does not run with forward slashes, and a POSIX path has no
    backslash separator to turn."""
    if len(path) >= 3 and path[0].isascii() and path[0].isalpha() and path[1] == ":" and path[2] in "\\/":
        return path.replace("\\", "/")
    return path


_PLAIN_WORD_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.~+/-")


def _is_plain_program_word(word: str) -> bool:
    """``[A-Za-z]:/[A-Za-z0-9_.~+/-]+`` without importing ``re`` here (every
    hook loads this module on every tool call)."""
    return (len(word) > 3 and word[0].isascii() and word[0].isalpha() and word[1:3] == ":/"
            and all(ch in _PLAIN_WORD_CHARS for ch in word[3:]))


def windows_short_path(path: str) -> "str | None":
    """The 8.3 short form of an existing ``path`` from ``GetShortPathNameW``
    (Windows only), else None: a path that does not exist, or any other
    failure, answers 0 there and None here. Two calls, the first asking the
    buffer size, so a long path is never cut at ``MAX_PATH``. ctypes loads in
    here, never at module level. It runs inside remedy printers, so a lookup
    that cannot load answers None, never a traceback in place of the text."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        get_short = ctypes.WinDLL("kernel32").GetShortPathNameW  # type: ignore[attr-defined]
        get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        get_short.restype = wintypes.DWORD
        size = get_short(path, None, 0)
        if not size:
            return None
        buf = ctypes.create_unicode_buffer(size)
        written = get_short(path, buf, size)
    except (ImportError, AttributeError, OSError, ValueError):
        return None
    if not written or written >= size:
        return None
    return str(buf.value)


def _plain_path(value: object) -> str:
    """An ``OSError.filename`` as text a shell reads back as the same path:
    ``os.fsdecode`` for bytes, ``os.fspath`` for a path-like, ``str`` for
    anything else (an integer file descriptor); quoted only when spaced."""
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if isinstance(value, bytes):
        value = os.fsdecode(value)
    return quoted_if_spaced(str(value))


def os_error_text(exc: BaseException) -> str:
    """``str(exc)`` with its path spelled as a path, for an operator to paste.

    ``OSError.__str__`` renders ``filename`` (and ``filename2``) through
    ``repr``: ``[Errno 13] Permission denied: 'C:\\\\repo\\\\.claude'`` -- the
    backslashes doubled and the path quoted, so on Windows the shell says no
    such file when the operator pastes the path the message names (DEF-799;
    driven on the Windows walk, and reproducible on POSIX with a
    backslash-carrying filename, because ``repr`` doubles on every platform).
    Everything else is kept exactly as Python renders it -- the ``[Errno N]``
    or ``[WinError N]`` bracket, the strerror, the ``->`` between two paths --
    so a reader who knows the shape still recognises it. An exception with no
    ``filename`` (or one that is not an ``OSError`` at all: the handler tuples
    this is called from also catch ``subprocess.TimeoutExpired`` and
    ``json.JSONDecodeError``) is returned as ``str(exc)`` unchanged, so every
    ``except (...) as exc`` site can route through here without a type check.
    A path with whitespace is double-quoted (:func:`quoted_if_spaced`).

    Lives here, at the ``tools/cc/`` level, for the same reason the JSON
    chokepoint does: both ``tools/cc/*.py`` and ``tools/cc/hooks/*.py`` import
    it without reaching across the hooks/ boundary. Twin of
    ``espalier/_text.py::os_error_text`` -- a separate copy because ``tools/cc/``
    cannot import ``espalier`` (the zero-espalier-import contract); the two
    bodies are parity-pinned by tests. Keep them behaviourally equivalent; do
    NOT dedup them.
    """
    if not isinstance(exc, OSError) or exc.filename is None:
        return str(exc)
    winerror = getattr(exc, "winerror", None)
    code = f"WinError {winerror}" if winerror else f"Errno {exc.errno}"
    text = f"[{code}] {exc.strerror}: {_plain_path(exc.filename)}"
    if exc.filename2 is not None:
        text += f" -> {_plain_path(exc.filename2)}"
    return text


#: Windows locks one byte this far into the file. ``LockFileEx`` locks are
#: mandatory for I/O on their range, unlike ``flock``, so a lock on byte 0 of a
#: log would make every reader of that log fail; no data reaches this offset.
_LOCK_OFFSET_HIGH = 0x7FFFFFFF
_LOCKFILE_EXCLUSIVE_LOCK = 0x2
_ERROR_NOT_LOCKED = 158
#: ``LockFileEx``'s fail-immediately flag, and the error a byte another process
#: holds answers with under it: :func:`try_lock_file` reads that pair as False.
_LOCKFILE_FAIL_IMMEDIATELY = 0x1
_ERROR_LOCK_VIOLATION = 33


def lock_file(fh: IO[Any], *, shared: bool = False) -> None:
    """Block until this process holds a lock on ``fh``'s file -- exclusive, or
    shared with other shared holders -- the way ``fcntl.flock`` does.

    POSIX is ``flock`` itself. Windows is ``LockFileEx`` on one byte far past
    any data (``_LOCK_OFFSET_HIGH``), which gives the same three properties
    across processes: an exclusive lock waits for every other holder, shared
    locks coexist, and the lock goes when the handle closes or the process
    dies. Before this, every lock site imported ``fcntl`` and ran unlocked on
    Windows, and parallel hooks lost updates there (14 of 200 counter
    increments survived eight writers, driven 2026-10-02).

    Raises ``OSError`` when the lock cannot be taken (a flock-less mount, a
    handle Windows refuses); each caller keeps its own degrade path for that.
    Never sleeps and never writes to a stream. Twin of the copy in
    ``espalier/_atomic_io.py`` (this tree cannot import ``espalier``), held equal
    by ``tests/test_surface_contract.py::test_lock_file_two_copy_parity``;
    ``tests/test_file_lock.py`` drives both across processes.
    """
    if sys.platform == "win32":
        _lock_byte(fh, 0 if shared else _LOCKFILE_EXCLUSIVE_LOCK, unlock=False)
    else:
        try:
            import fcntl
        except ImportError as exc:  # a POSIX build without fcntl: no lock to take
            raise OSError(f"no file locking on this platform: {exc}") from exc
        fcntl.flock(fh.fileno(), fcntl.LOCK_SH if shared else fcntl.LOCK_EX)


def unlock_file(fh: IO[Any]) -> None:
    """Release :func:`lock_file`'s lock. Unlocking a file this process does not
    hold is a no-op, as ``flock(LOCK_UN)`` is."""
    if sys.platform == "win32":
        _lock_byte(fh, 0, unlock=True)
    else:
        try:
            import fcntl
        except ImportError:  # fail-open: ok deliberate -- without fcntl lock_file raised, so no lock is held
            return
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def try_lock_file(fh: IO[Any], *, shared: bool = False) -> bool:
    """:func:`lock_file` without the wait: True when the lock is now held,
    False when another process holds it. Raises where ``lock_file`` would.

    POSIX adds ``LOCK_NB`` to the ``flock`` and reads ``BlockingIOError`` as
    False; Windows adds the fail-immediately flag to the ``LockFileEx`` call
    and reads the lock-violation error as False. The box lock the test suite
    takes between two seats on one machine polls this, so a waiter can name
    the holder and its age instead of sitting silent inside a blocking call.
    Held equal to the twin copy by the same parity test as ``lock_file``."""
    if sys.platform == "win32":
        return _lock_byte(fh, (0 if shared else _LOCKFILE_EXCLUSIVE_LOCK) | _LOCKFILE_FAIL_IMMEDIATELY,
                          unlock=False)
    try:
        import fcntl
    except ImportError as exc:  # a POSIX build without fcntl: no lock to take
        raise OSError(f"no file locking on this platform: {exc}") from exc
    try:
        fcntl.flock(fh.fileno(), (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _lock_byte(fh: IO[Any], flags: int, *, unlock: bool) -> bool:
    """``LockFileEx`` / ``UnlockFileEx`` on the one lock byte (Windows only).
    A synchronous handle makes ``LockFileEx`` wait until the lock is granted;
    with the fail-immediately flag in ``flags`` a held byte answers at once,
    and that one error, under that one flag, is read as False, so a blocking
    caller's errors still raise. True when the call succeeded."""
    if sys.platform != "win32":  # pragma: no cover - the callers branch first
        raise OSError("LockFileEx is Windows-only")
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _Overlapped(ctypes.Structure):
        _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                    ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                    ("hEvent", wintypes.HANDLE)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(fh.fileno()))
    overlapped = _Overlapped(0, 0, 0, _LOCK_OFFSET_HIGH, None)
    if unlock:
        ok = kernel32.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped))
    else:
        ok = kernel32.LockFileEx(handle, flags, 0, 1, 0, ctypes.byref(overlapped))
    if not ok:
        error = ctypes.get_last_error()
        if unlock and error == _ERROR_NOT_LOCKED:
            return True
        if flags & _LOCKFILE_FAIL_IMMEDIATELY and error == _ERROR_LOCK_VIOLATION:
            return False
        raise ctypes.WinError(error)
    return True


#: What :func:`run_bounded` adds to a timeout on Windows, and
#: :func:`run_tree_bounded` (and :func:`communicate_tree_bounded`) on every
#: OS: one deadline for the tree kill, the drain of what was written and the
#: reap of the child.
SPAWN_KILL_GRACE_SECONDS = 2.0


def run_bounded(
    args: Any, *, timeout: float | None = None, input: Any = None,
    capture_output: bool = False, check: bool = False, **kwargs: Any,
) -> "subprocess.CompletedProcess[Any]":
    """``subprocess.run``, whose ``timeout`` bounds the call on Windows too.

    On Windows, ``subprocess.run`` kills only the child at the timeout and then
    reads the pipes with no timeout (CPython's ``run``: ``process.kill()``,
    then ``process.communicate()``), so a grandchild that inherited a pipe sets
    the real bound. Two such grandchildren are common: the program a ``.bat``
    shim starts (pyenv-win's ``python.bat``), and git itself, because Git for
    Windows's ``cmd\\git.exe`` is a launcher that runs the real git as its
    child, and a network read adds ``git-remote-https`` below that. Driven on
    Windows 11 with CPython 3.11.9 (2026-10-12): a 2 s cap returned after
    20.1 s through a shim whose python slept 20 s, and a 1 s cap on
    ``git ls-remote`` to an unroutable host after 21.1 s.

    So on Windows with a ``timeout`` the child starts under ``Popen``; at the
    timeout ``taskkill /T /F`` ends its whole tree, and the drain and the reap
    share :data:`SPAWN_KILL_GRACE_SECONDS`. The call returns within ``timeout``
    plus that grace even when the tree kill misses a holder: that holder keeps
    its pipe, and the reader threads, which are daemons, are left behind.
    ``TimeoutExpired`` is raised as ``run`` raises it, carrying what was read.
    Everywhere else this IS ``subprocess.run``: on POSIX, where ``run`` only
    waits for the killed child; with no ``timeout``; and where
    ``subprocess.run`` has been replaced (a test's fake: :func:`_is_stdlib_run`),
    since the bound belongs to a real process tree and a fake has none. So on
    POSIX the timeout kills the child alone and what it started runs on: for a
    child that is itself a tree (a pytest, a script that runs one) call
    :func:`run_tree_bounded`, whose timeout ends the whole tree on every OS.

    Three edges, each as ``run`` has it or narrower. A child that exited while
    a grandchild it detached still holds the pipe ends in ``TimeoutExpired``
    (``run``'s would come when the grandchild ends). At a timeout the tree kill
    ends every process the child started, a daemon git spawned included. And a
    test that swaps a module's own ``subprocess`` name for a stand-in no longer
    reaches a call routed here: patch ``subprocess.run`` itself, or the
    module's ``run_bounded``.

    Lives here, beside ``lock_file``, because both ``tools/cc/*.py`` and the
    hooks import this module; ``_hook_utils.spawn_checked`` is built on it, and
    ``tests/test_spawn_chokepoint.py`` holds every timed spawn under
    ``tools/cc`` to one of the two. ``scripts/``, ``bench/`` and the top-level
    ``tools/`` load this copy by path. Twin of ``espalier/_spawn.py`` (this
    tree cannot import ``espalier``) and of the inline copy in the stdlib-only
    ``espalier/scanners/freshness.py``; ``tests/test_contracts.py::
    TestTheBoundedSpawnTwins`` holds the three equal, so change them together.
    """
    import subprocess

    if timeout is None or sys.platform != "win32" or not _is_stdlib_run(subprocess.run, subprocess):
        return subprocess.run(args, timeout=timeout, input=input,  # spawn: ok the bounded spawn itself
                              capture_output=capture_output, check=check, **kwargs)
    if input is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used.")
        kwargs["stdin"] = subprocess.PIPE
    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("stdout and stderr arguments may not be used with capture_output.")
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    proc = subprocess.Popen(args, **kwargs)  # spawn: ok the bounded spawn itself -- Windows with a timeout
    try:
        stdout, stderr = proc.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        end = time.monotonic() + SPAWN_KILL_GRACE_SECONDS
        _end_tree(proc, end)
        try:
            exc.stdout, exc.stderr = proc.communicate(timeout=max(0.05, end - time.monotonic()))
        except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- a holder the tree kill missed keeps its pipe; the bound holds and the TimeoutExpired below says what happened
            pass
        try:
            proc.wait(timeout=max(0.05, end - time.monotonic()))
        except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- a child that outlives TerminateProcess is the OS's now
            pass
        raise
    except BaseException:  # noqa: BLE001 -- Ctrl-C or a write error mid-call: the tree ends under the grace and the error goes on, as run's own handler kills and re-raises
        _end_tree(proc, time.monotonic() + SPAWN_KILL_GRACE_SECONDS)
        try:
            proc.wait(timeout=SPAWN_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- a child that outlives TerminateProcess is the OS's now; the original error is the one to raise
            pass
        raise
    retcode = proc.wait()  # communicate() returned, so it reaped the child: this answers at once
    if check and retcode:
        raise subprocess.CalledProcessError(retcode, proc.args, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(proc.args, retcode, stdout, stderr)


def _is_stdlib_run(run: Any, subprocess_module: Any) -> bool:
    """Whether ``run`` is the standard library's own ``subprocess.run``: its
    code was compiled from the ``subprocess`` module's own file. A stand-in
    defined anywhere else is not -- a lambda, a ``MagicMock`` (no code at all),
    or a ``functools.wraps`` spy, which copies the name and the module but not
    the code. An interpreter whose library is zipped may spell the two paths
    apart; ``run`` is then taken for a stand-in and the call is ``run``'s own,
    unbounded on Windows as before, never a refusal."""
    code = getattr(run, "__code__", None)
    origin = getattr(subprocess_module, "__file__", None)
    if code is None or not origin:
        return False
    return os.path.normcase(os.path.abspath(code.co_filename)) == os.path.normcase(os.path.abspath(origin))


def _end_tree(proc: "subprocess.Popen[Any]", end: float) -> None:
    """End ``proc`` and every process below it (Windows): ``taskkill /T /F``
    by pid, from System32 so no PATH entry can stand in for it, with no pipe
    of its own to wait on; then ``kill`` the child itself, which covers a
    ``taskkill`` that could not start or found the tree already gone."""
    import subprocess

    taskkill = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
    try:
        subprocess.run(  # spawn: ok the bounded spawn's tree kill -- no pipes, its own timeout
            [taskkill, "/T", "/F", "/PID", str(proc.pid)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=max(0.05, end - time.monotonic()),
        )
    except (OSError, subprocess.SubprocessError):  # fail-open: ok deliberate -- the kill below still ends the child, and the drain's deadline holds either way
        pass
    try:
        proc.kill()
    except OSError:  # fail-open: ok deliberate -- the child already ended
        pass


def run_tree_bounded(
    args: Any, *, timeout: float | None = None, input: Any = None,
    capture_output: bool = False, check: bool = False, **kwargs: Any,
) -> "subprocess.CompletedProcess[Any]":
    """:func:`run_bounded`, whose timeout ends the child's whole tree on every OS.

    For a child that is itself a tree of work -- a pytest that spawns hooks and
    git, a script that runs a pytest of its own -- where ``subprocess.run``'s
    kill of the child alone leaves the rest running at parent 1 on POSIX
    (``scripts/verify_pins.py``'s inner pytest, and the suite's runs of that
    script). At the timeout, and on any exception while it waits (a Ctrl-C, or
    the per-test ceiling's), the child and every process below it are ended,
    and ``TimeoutExpired`` (or that exception) is raised. The kill, the drain
    of what was written and the reap share :data:`SPAWN_KILL_GRACE_SECONDS`.
    ``TimeoutExpired`` carries what the drain read, decoded as the call asked:
    a ``str`` under ``text=True``, where ``run`` on POSIX carries ``bytes``;
    where the drain itself times out (a holder the walk missed keeps its pipe),
    it carries what the first wait read, as ``bytes`` on POSIX, as ``run``'s
    does.

    The child starts in no session or process group of its own, so the kill of
    any ancestor's group still reaches the whole tree: a session at this level
    would hide everything below it from the group kills of
    ``scripts/fresh_clone_gate.py`` and ``scripts/archive_probe.py``, and a
    group kill does not reach into another session, so groups compose at one
    level only. So ``start_new_session``, ``process_group`` and ``preexec_fn``
    are refused on POSIX, and the kill walks the tree instead, which composes
    at any depth. On Windows the child goes into the kill-on-close job object
    :func:`run_tree_to_deadline` uses (:func:`_kill_on_close_job`), and the
    kill is :func:`_end_the_tree_now`: ``taskkill /T`` while every parent in
    the tree is alive, then ``TerminateJobObject``. The job also outlives a
    child that exits on its own: on Windows what that child left running stays
    in the job and is ended when the caller exits (the job's handle, one per
    call, closes with the caller), where on POSIX it runs on. On POSIX
    (:func:`_end_the_whole_tree`) it reads the process table (``ps``), stops
    the child and every process below it, reads again until a read finds none
    it has not already tried to stop, then kills each one, and the group of each process in
    the tree that leads one (never the caller's), which takes what a nested
    session (a :func:`run_tree_to_deadline` below) left behind its leader.

    Three edges. A process whose parent and group leader both ended before the
    walk is no longer below the child or in a group the walk knows, and runs
    on; if it holds a pipe, the drain still ends at the grace and the call
    returns. Where ``ps`` cannot answer, the kill is of the child, and of its
    group where it leads one. And a test that replaces ``subprocess.run``
    reaches it as is (:func:`_is_stdlib_run`): a stand-in has no tree.
    """
    import subprocess

    if sys.platform != "win32":
        held = [name for name, given in (("start_new_session", bool(kwargs.get("start_new_session"))),
                                         ("process_group", kwargs.get("process_group") is not None),
                                         ("preexec_fn", kwargs.get("preexec_fn") is not None)) if given]
        if held:
            raise ValueError(
                f"run_tree_bounded refuses {', '.join(held)}: its child starts in the caller's own "
                "process group so an ancestor's group kill (scripts/fresh_clone_gate.py's, "
                "scripts/archive_probe.py's) still reaches the tree, and its own kill walks the tree")
    if not _is_stdlib_run(subprocess.run, subprocess):
        return subprocess.run(args, timeout=timeout, input=input,  # spawn: ok a test's stand-in for run, which has no tree
                              capture_output=capture_output, check=check, **kwargs)
    if input is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used.")
        kwargs["stdin"] = subprocess.PIPE
    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("stdout and stderr arguments may not be used with capture_output.")
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    proc = subprocess.Popen(args, **kwargs)  # spawn: ok the tree-bounded run itself
    job = _kill_on_close_job(proc) if sys.platform == "win32" else None
    stdout, stderr = _communicate_or_end_the_tree(proc, input, timeout, job)
    retcode = proc.wait()  # communicate() returned, so it reaped the child: this answers at once
    if check and retcode:
        raise subprocess.CalledProcessError(retcode, proc.args, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(proc.args, retcode, stdout, stderr)


def communicate_tree_bounded(proc: Any, input: Any = None, *, timeout: float | None = None) -> "tuple[Any, Any]":
    """``proc.communicate(input, timeout=timeout)`` for a ``Popen`` the caller
    holds, whose timeout, and any exception while it waits, ends ``proc``'s
    whole tree as :func:`run_tree_bounded`'s does, then raises.
    ``communicate`` alone raises at its timeout and leaves the child and all
    it started running. For a child the caller had to start itself (it reads
    one pipe on a thread of its own while the child runs); a child started
    here goes through :func:`run_tree_bounded`. On Windows ``proc`` goes into
    the kill-on-close job object at entry (:func:`_kill_on_close_job`), so the
    kill is ``taskkill /T`` then the job, as :func:`run_tree_bounded`'s is; a
    process ``proc`` started before this call is reached by the ``taskkill``
    walk alone. Start ``proc`` in the caller's own process group: a child in
    a session of its own is ended here through its group, but that session
    hides the whole tree from every ancestor's group kill
    (``scripts/fresh_clone_gate.py``'s, ``scripts/archive_probe.py``'s), the
    reason :func:`run_tree_bounded` refuses one."""
    job = _kill_on_close_job(proc) if sys.platform == "win32" else None
    return _communicate_or_end_the_tree(proc, input, timeout, job)


def _communicate_or_end_the_tree(proc: Any, input: Any, timeout: "float | None", job: Any) -> "tuple[Any, Any]":
    """``proc``'s output by ``timeout``; at the timeout, or on any exception
    while it waits, its whole tree ended (:func:`_end_the_whole_tree`), and
    the drain and the reap held to one grace from the kill."""
    import subprocess

    try:
        return proc.communicate(input, timeout=timeout)  # spawn: ok the tree-bounded wait itself
    except subprocess.TimeoutExpired as exc:
        end = time.monotonic() + SPAWN_KILL_GRACE_SECONDS
        _end_the_whole_tree(proc, end, job)
        try:
            exc.stdout, exc.stderr = proc.communicate(timeout=max(0.05, end - time.monotonic()))  # spawn: ok the drain after the tree kill
        except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- a holder the walk missed keeps its pipe; the bound holds and the TimeoutExpired below says what happened
            pass
        try:
            proc.wait(timeout=max(0.05, end - time.monotonic()))
        except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- a child that outlives SIGKILL is the OS's now
            pass
        raise
    except BaseException:  # noqa: BLE001 -- Ctrl-C or the per-test ceiling mid-wait: the tree ends under the grace and the error goes on, where run's own handler kills the child alone
        end = time.monotonic() + SPAWN_KILL_GRACE_SECONDS
        _end_the_whole_tree(proc, end, job)
        try:
            proc.wait(timeout=max(0.05, end - time.monotonic()))
        except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- a child that outlives SIGKILL is the OS's now; the original error is the one to raise
            pass
        raise


def _end_the_whole_tree(proc: Any, end: float, job: Any = None) -> None:
    """End ``proc`` and every process below it by ``end``, from no group of
    its own.

    Windows: :func:`_end_the_tree_now` (``taskkill /T`` by pid, then the job),
    or the job alone once ``proc`` is reaped, since its pid may then name
    another process. POSIX: the walk runs only while ``proc`` is unreaped and
    the table names this process as its parent (a reaped pid may already be
    another process's). It stops the child and each process below it, reads
    again until a read finds none it has not tried, each read bounded by
    ``end``, then kills every process it stopped, and the group of each one
    that leads a group other than the caller's. A pid joins the stopped set
    just before its stop and leaves it when the stop fails, so a stop that
    failed widens nothing, and an exception mid-walk, even one landing just
    after a stop, still kills every process that may be stopped. Where the
    first read found no table, an unreaped child that leads its own group is
    ended through it; where the table named another parent, nothing but
    ``proc.kill()`` runs, since a group the pid leads may be another
    process's. The child's own state is read from ``returncode``, never
    ``poll()``, which would reap an exited child and hand its children to
    parent 1 before the walk could read them below it. Last,
    ``proc.kill()``, which ``Popen`` itself skips for a reaped child."""
    if sys.platform == "win32":
        if proc.returncode is None:
            _end_the_tree_now(proc, job, end)
        elif job is not None:
            _terminate_job(job)
        return
    import signal

    me, my_group = os.getpid(), os.getpgid(0)
    tried: set[int] = set()
    stopped: set[int] = set()
    leaders: set[int] = set()
    walked = unread = False
    try:
        while proc.returncode is None and time.monotonic() < end:
            read = _process_table(end)
            if read is None:
                unread = not walked
                break
            if read.get(proc.pid, (None, None))[0] != me:
                break
            walked = True
            new = _below(proc.pid, read) - tried - {me}
            if not new:
                break
            for pid in new:
                tried.add(pid)
                leads = read[pid][1] == pid
                # Recorded before the stop, so an interrupt landing just after
                # it still finds the pid in the set the kill below reads.
                stopped.add(pid)
                if leads:
                    leaders.add(pid)
                try:
                    os.kill(pid, signal.SIGSTOP)
                except OSError:  # fail-open: ok deliberate -- it ended between the read and the stop, or is not ours to stop; it leaves both sets
                    stopped.discard(pid)
                    leaders.discard(pid)
    finally:
        for pid in stopped:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:  # fail-open: ok deliberate -- it already ended
                pass
        if unread and proc.returncode is None:
            try:
                if os.getpgid(proc.pid) == proc.pid:
                    leaders.add(proc.pid)
            except OSError:  # fail-open: ok deliberate -- the child already ended
                pass
        for group in leaders - {my_group}:
            try:
                os.killpg(group, signal.SIGKILL)
            except OSError:  # fail-open: ok deliberate -- the group already ended
                pass
        try:
            proc.kill()
        except OSError:  # fail-open: ok deliberate -- the child already ended
            pass


#: The process-table read: every process's pid, parent pid and process group,
#: no header, each column its own ``-o`` (POSIX reads the text after ``=`` as
#: the header for the rest of its argument, so ``pid=,ppid=,pgid=`` is one
#: column where a ps follows that, BusyBox's among them). One spelling for
#: this module's walk and ``checkout_sync._parent_map``, parsed by
#: :func:`parse_process_table`.
PS_TABLE_ARGV = ("ps", "-A", "-o", "pid=", "-o", "ppid=", "-o", "pgid=")


def parse_process_table(text: str) -> "dict[int, tuple[int, int]] | None":
    """``ps`` output in the :data:`PS_TABLE_ARGV` shape as ``pid -> (ppid,
    pgid)``; ``None`` for a table with no rows, which no host has (the reader
    is in it), never ``{}``, which reads as a host with no processes."""
    table: "dict[int, tuple[int, int]]" = {}
    for line in text.splitlines():
        cells = line.split()
        if len(cells) == 3 and all(c.isdigit() for c in cells):
            table[int(cells[0])] = (int(cells[1]), int(cells[2]))
    return table or None


def _process_table(end: float) -> "dict[int, tuple[int, int]] | None":
    """Every process as ``pid -> (ppid, pgid)``, read from ``ps`` by ``end``
    (``/bin/ps`` first, so no PATH entry can stand in for it); ``None`` where
    it cannot be read. Every pid in it is real: a test that hands the walk a
    table of its own makes the walk signal those pids, so it replaces the
    module's ``os`` with a recorder too."""
    import shutil
    import subprocess

    ps = "/bin/ps" if os.path.exists("/bin/ps") else shutil.which("ps")
    if not ps:
        return None
    try:
        # The shared spelling, its program name first; ``executable`` is the
        # program that runs.
        out = subprocess.run(  # spawn: ok the tree walk's table read -- no input, its own timeout
            ["ps", *PS_TABLE_ARGV[1:]], executable=ps,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=max(0.05, end - time.monotonic()),
        )
    except (OSError, subprocess.SubprocessError):  # fail-open: ok deliberate -- the kill of the child alone still runs
        return None
    if out.returncode != 0:
        return None
    return parse_process_table(out.stdout)


def _below(root: int, table: "dict[int, tuple[int, int]]") -> "set[int]":
    """``root`` and every process below it in ``table``, by parent pid."""
    children: "dict[int, list[int]]" = {}
    for pid, (ppid, _group) in table.items():
        children.setdefault(ppid, []).append(pid)
    tree, todo = {root}, [root]
    while todo:
        for child in children.get(todo.pop(), ()):
            if child not in tree:
                tree.add(child)
                todo.append(child)
    return tree


#: How long :func:`run_tree_to_deadline` gives the kill, the drain and the
#: reap once its deadline has passed: one budget from the moment of the kill,
#: which a Windows tree walk and the pipes' close share, so nothing there
#: waits past the deadline plus this.
TREE_DRAIN_SECONDS = 0.25


class TreeStartError(OSError):
    """:func:`run_tree_to_deadline` could not start its child at all. Nothing
    after the start raises it, so a caller can tell a child that never ran
    from one that ran and whose answer was lost."""


def run_tree_to_deadline(
    args: "list[str]", *, deadline: float, input: bytes, env: "dict[str, str] | None" = None,
) -> "tuple[int, bytes, bytes] | None":
    """Run ``args`` until ``deadline`` (a ``time.monotonic()`` value) and return
    its ``(returncode, stdout, stderr)``; at the deadline end the child and
    every process below it and return ``None``. A child that cannot start at
    all raises :class:`TreeStartError`.

    For a parent that must answer by a fixed time whatever its child is doing:
    ``write_guard``'s judgment runs in such a child, because a compiled
    pattern's search holds the interpreter lock for its whole call, so no
    thread in the judging process can answer by a deadline (DEF-3048). Nothing
    here waits past ``deadline`` plus :data:`TREE_DRAIN_SECONDS`. The input
    goes in from a thread of its own, never through ``communicate``: on Windows
    CPython 3.11 and 3.12 write ``communicate``'s input before the timed
    joins, so a child that has not read a payload larger than the pipe holds
    that write past any timeout.

    The tree: on POSIX the child starts in a session of its own and the kill is
    ``killpg`` with ``SIGKILL`` (which also takes the git a judgment started).
    On Windows the child goes into a job object that kills its processes when
    its last handle closes, so the tree also ends with this process, however
    this process ends. The kill walks the tree first (:func:`_end_tree`,
    ``taskkill /T``) while every parent in it is still alive, which reaches a
    process the child started before it was assigned to the job (a venv's
    ``python.exe`` redirector starts the real interpreter at once), then ends
    what is left in the job with ``TerminateJobObject``. A child that exited on
    its own while a process it left still held a pipe is answered with what it
    wrote, once the kill has closed that pipe.

    Lives here, beside :func:`run_bounded`, as the other home a raw timed spawn
    may stand in (``tests/test_spawn_chokepoint.py``'s ``BOUNDED_HOME``).
    """
    import subprocess
    import threading

    kwargs: dict[str, Any] = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
                              "stderr": subprocess.PIPE, "env": env}
    if os.name != "nt":
        kwargs["start_new_session"] = True
    try:
        # subprocess-contract: ok the argv is the caller's by design (write_guard's judging child); the tree bound is pinned by tests/test_bounded_spawn.py::TestTheTreeBoundEndsEveryProcessAtTheDeadline and the child by tests/test_write_guard_time_budget.py's real-hook rows
        proc = subprocess.Popen(args, **kwargs)  # spawn: ok the tree-bounded spawn itself
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise TreeStartError(type(exc).__name__) from exc  # the cause carries the detail
    job = None
    # The feeder owns the input; `communicate` sees no stdin and only reads.
    stdin, proc.stdin = proc.stdin, None
    try:
        if os.name == "nt":
            job = _kill_on_close_job(proc)
        threading.Thread(target=_feed, args=(stdin, input), daemon=True).start()
        out, err = proc.communicate(timeout=max(0.0, deadline - time.monotonic()))  # spawn: ok its own deadline
    except subprocess.TimeoutExpired:
        end = time.monotonic() + TREE_DRAIN_SECONDS
        ended_alone = proc.poll() is not None
        _end_the_tree_now(proc, job, end)
        try:
            out, err = proc.communicate(timeout=max(0.0, end - time.monotonic()))  # spawn: ok the drain after the kill
        except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- a pipe the kill could not close; the deadline still holds and the call is answered as unfinished
            return None
        return (proc.returncode, out, err) if ended_alone else None
    except BaseException:  # noqa: BLE001 -- Ctrl-C or a read error mid-call: the tree ends, then the error goes on
        _end_the_tree_now(proc, job, time.monotonic() + TREE_DRAIN_SECONDS)
        raise
    return proc.returncode, out, err


def _feed(pipe: "IO[bytes] | None", data: bytes) -> None:
    """Write ``data`` to a child's stdin and close it, from a thread of its own.
    A child that closed its stdin or ended first is answered by its exit or by
    the deadline, never by this write."""
    if pipe is None:
        return
    try:
        pipe.write(data)
    except (OSError, ValueError):  # fail-open: ok deliberate -- the child closed its stdin or ended; its exit or the deadline decides
        pass
    finally:
        try:
            pipe.close()
        except (OSError, ValueError):  # fail-open: ok deliberate -- a pipe already broken has nothing left to send
            pass


def _end_the_tree_now(proc: Any, job: Any, end: float) -> None:
    """Kill ``proc`` and every process below it, by ``end``: ``killpg`` of its
    own session on POSIX; on Windows the tree walk (``taskkill /T``, then the
    child itself) while every parent in the tree is alive, then
    ``TerminateJobObject`` for whatever the walk left in the job."""
    if os.name == "nt":
        _end_tree(proc, end)
        if job is not None:
            _terminate_job(job)
        return
    import signal

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:  # fail-open: ok deliberate -- the group is already gone; the kill below covers a child outside it
        pass
    try:
        proc.kill()
    except OSError:  # fail-open: ok deliberate -- the child already ended
        pass


def _terminate_job(job: Any) -> None:
    """End every process in the Windows job object ``job`` (a handle from
    :func:`_kill_on_close_job`); the handle stays open, as that function
    says."""
    import ctypes

    ctypes.WinDLL("kernel32", use_last_error=True).TerminateJobObject(ctypes.c_void_p(job), 1)


def _kill_on_close_job(proc: Any) -> "int | None":
    """A Windows job object holding ``proc``, set to kill every process in it
    when its last handle closes, as its handle; ``None`` where one cannot be
    made or assigned (the kill's ``taskkill /T`` walk still runs; only the
    close-time backstop is lost). The
    handle is never closed here: it closes with this process, which is the
    backstop that ends the tree when this process is ended from outside."""
    try:
        import ctypes
        from ctypes import wintypes

        class _Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", ctypes.c_ulonglong * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, wintypes.UINT]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        extended_limit_information = 9
        if (kernel32.SetInformationJobObject(job, extended_limit_information, ctypes.byref(info), ctypes.sizeof(info))
                and kernel32.AssignProcessToJobObject(job, int(proc._handle))):
            return int(job)
        kernel32.CloseHandle(job)
    except (ImportError, OSError, AttributeError, ValueError, TypeError):  # fail-open: ok deliberate -- no job object: the kill's taskkill /T walk still runs, and only the close-time backstop is lost
        pass
    return None
