"""Tiny text helpers for user-facing CLI output."""
from __future__ import annotations

import os
import sys


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
    the one quoting every shell this repo targets accepts for a program word,
    and the one a pasted path needs to survive as one argument. A double
    quote INSIDE the path is not escaped: it is illegal in a Windows filename
    (the platform this quoting is for) and rare enough on POSIX that a
    shell-specific escape would cost more than it saves."""
    return f'"{path}"' if any(ch.isspace() for ch in path) else path


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
