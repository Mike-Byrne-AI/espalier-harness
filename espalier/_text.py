"""Tiny text helpers for user-facing CLI output."""
from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable


def pin_utf8_streams() -> None:
    """Read stdin and write stdout and stderr as UTF-8, whatever the code page.

    On Windows without UTF-8 mode a redirected stream (a pipe: Git Bash, CI,
    Claude Code's Bash tool) uses the ANSI code page, so the first character of
    operator content outside it -- a repository name, a tracked path, a commit
    subject -- raises ``UnicodeEncodeError`` mid-run, or reaches a file the
    caller appends to as bytes that are not UTF-8; a UTF-8 producer piped in is
    silently mis-decoded. Content may be any text; the messages around it stay
    7-bit ASCII by rule. stdin and stdout take ``errors="replace"``, so a lone
    surrogate (an undecodable file name) cannot end the run; stderr keeps its
    default ``backslashreplace``, so a diagnostic still shows what it could not
    encode. A stream without ``reconfigure`` (a test's ``StringIO``) or one
    already closed or detached is left alone, and a real console already uses
    the wide-character API, so pinning it changes nothing there.

    Twin of ``tools/cc/_json_safe.py::pin_utf8_streams`` -- ``tools/cc/`` cannot
    import ``espalier`` -- pinned equal by
    ``tests/test_surface_contract.py::test_pin_utf8_streams_two_copy_parity``.
    The stdlib-only scanners cannot import it either and pin inline.
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


def plural(n: int, singular: str, plural_form: str | None = None) -> str:
    """Return a ``"<n> <word>"`` string, pluralizing ``word`` on count.

    ``singular`` when ``n == 1``, else ``plural_form`` (default: ``singular``
    + ``"s"``). Renders the count too: ``plural(1, "warning")`` -> ``"1
    warning"``; ``plural(2, "warning")`` -> ``"2 warnings"``; ``plural(0,
    "file")`` -> ``"0 files"``. Pass ``plural_form`` for irregular plurals
    (e.g. ``plural(n, "entry", "entries")``).

    Byte-twin of ``tools/cc/hooks/_hook_utils.py::plural`` — kept a separate copy
    because ``tools/cc/`` cannot import ``espalier`` (the zero-espalier-import
    contract). Keep the two behaviorally equivalent; do NOT dedup them.
    """
    word = singular if n == 1 else (plural_form or f"{singular}s")
    return f"{n} {word}"


def quoted_if_spaced(path: str) -> str:
    """``path`` double-quoted when it carries whitespace, else unchanged --
    the one quoting a pasted path needs to survive as one ARGUMENT in every
    shell this repo targets: PowerShell, cmd and the POSIX shells (driven on
    Windows 11 with ``git -C "<spaced dir>"``; the bare spelling broke in all
    three). As a PROGRAM word it serves cmd and the POSIX shells only:
    PowerShell reads a quoted first word as a string and refuses the line, and
    its call operator ``& "<path>"`` is in turn a syntax error to bash, so no
    one QUOTED spelling of a spaced program runs in all of them (DEF-2060):
    a program word goes through :func:`program_word` instead. It quotes
    whitespace alone: a ``$`` stays live inside double quotes in PowerShell
    and bash, and an ``&`` in an unspaced path is left bare. A double
    quote INSIDE the path is not escaped: it is illegal in a Windows filename
    (the platform this quoting is for) and rare enough on POSIX that a
    shell-specific escape would cost more than it saves."""
    return f'"{path}"' if any(ch.isspace() for ch in path) else path


def program_word(path: str, short_path: Callable[[str], str | None] | None) -> str:
    """``path`` spelled as the PROGRAM word of a command the reader will type,
    given ``short_path``, a lookup of the path's 8.3 short form (None where
    the host has none). Unspaced, it is unchanged. Spaced, its short form with
    forward slashes when that holds no whitespace: one bare word that Windows
    PowerShell 5.1, cmd and Git Bash all run (driven on Windows 11; a backslash
    is an escape to bash, a quoted first word a string to PowerShell, so
    neither of those spellings serves all three, DEF-2060). Else, with no short
    form or one that still holds a space (8.3 names off on that volume), the
    double-quoted path, which cmd and the POSIX shells run and PowerShell needs
    ``&`` before: the caller says so once a run. Pure text: the lookup is a
    parameter, so the Windows call stays out of it."""
    if not any(ch.isspace() for ch in path):
        return path
    short = short_path(path) if short_path is not None else None
    if short:
        word = short.replace("\\", "/")
        # Only a drive-rooted word of plain characters: an 8.3 name keeps
        # `&`, `(`, `'` and `$`, which every one of the three shells reads
        # as grammar in a bare word (driven: `MY(PYT~1`, `JO&COT~1`), and a
        # UNC or `\\?\` form does not run with forward slashes.
        if _PLAIN_PROGRAM_WORD.fullmatch(word):
            return word
    return quoted_if_spaced(path)


_PLAIN_PROGRAM_WORD = re.compile(r"[A-Za-z]:/[A-Za-z0-9_.~+/-]+")


def windows_short_path(path: str) -> str | None:
    """The 8.3 short form of an existing ``path`` from ``GetShortPathNameW``
    (Windows only), else None: a path that does not exist, or any other
    failure, answers 0 there and None here. Two calls, the first asking the
    buffer size, so a long path is never cut at ``MAX_PATH``. It runs inside
    remedy printers, so a lookup that cannot load answers None, never a
    traceback in place of the repair text."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        get_short = ctypes.WinDLL("kernel32").GetShortPathNameW
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
    return buf.value


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

    Twin of ``tools/cc/_json_safe.py::os_error_text`` -- a separate copy because
    ``tools/cc/`` cannot import ``espalier`` (the zero-espalier-import
    contract); the two bodies are parity-pinned by tests. Keep them
    behaviourally equivalent; do NOT dedup them.
    """
    if not isinstance(exc, OSError) or exc.filename is None:
        return str(exc)
    winerror = getattr(exc, "winerror", None)
    code = f"WinError {winerror}" if winerror else f"Errno {exc.errno}"
    text = f"[{code}] {exc.strerror}: {_plain_path(exc.filename)}"
    if exc.filename2 is not None:
        text += f" -> {_plain_path(exc.filename2)}"
    return text
