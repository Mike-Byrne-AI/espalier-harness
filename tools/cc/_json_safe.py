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
from typing import Any

_MISSING = object()


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
