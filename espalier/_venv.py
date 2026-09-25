"""Virtualenv-awareness shared by the interpreter resolver and the doctor check.

An activated virtualenv puts its own ``bin/`` first on ``PATH``, and that
directory holds BOTH a ``python`` and a ``python3`` shim regardless of which
name created it. A plain ``shutil.which`` probe therefore cannot tell a
host-wide interpreter from one that disappears at ``deactivate`` — which
matters because ``.claude/settings.json`` outlives the shell that wrote it.

Both consumers need the same containment question ("is this PATH entry inside
that venv?") but ask *different* questions of the interpreter itself:

- ``cli`` asks the CANDIDATE for its own ``sys.prefix``/``sys.base_prefix``
  before wiring a name, because ``init`` is often run by a python outside the
  venv that is first on ``PATH``.
- ``doctor`` asks whether an ALREADY-WIRED name resolves into a venv, keyed on
  the raw ``shutil.which`` result.

Only the containment predicate is common; it lives here so the two cannot
drift into near-identical helpers with different preconditions.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path


def path_is_under(entry: str, root: Path) -> bool:
    """True when ``PATH`` entry ``entry`` lives inside ``root``.

    Both sides are resolved: on macOS ``/tmp`` is a symlink to ``/private/tmp``,
    so comparing a resolved path against an unresolved root silently never
    matches and any caller filtering on it goes inert. ``RuntimeError`` is
    caught because ``Path.resolve`` raises it on a symlink loop and it is NOT
    an ``OSError`` subclass.
    """
    try:
        return Path(entry).resolve().is_relative_to(root.resolve())
    except (OSError, ValueError, RuntimeError):
        return False


def venv_root_of(interpreter_path: str) -> Path | None:
    """Venv root for an interpreter path, or ``None`` if it is not a venv shim.

    Keys on the RAW ``shutil.which`` result — never ``Path(...).resolve()``. A
    POSIX venv's ``bin/python`` is a symlink chain out to the base install, so
    resolving the FILE lands outside the venv every time and the check is dead
    on arrival.

    Layout-agnostic: ``bin/`` on POSIX and ``Scripts/`` on Windows both carry
    ``pyvenv.cfg`` one level above the interpreter's directory.
    """
    if not interpreter_path:
        return None
    root = Path(interpreter_path).parent.parent
    return root if (root / "pyvenv.cfg").is_file() else None


def path_without(root: Path) -> str:
    """The current ``PATH`` with every entry inside ``root`` removed."""
    return os.pathsep.join(
        p for p in os.environ.get("PATH", "").split(os.pathsep)
        if p and not path_is_under(p, root)
    )


def resolves_only_inside(name: str) -> bool:
    """True when ``name`` resolves on ``PATH`` ONLY via a virtualenv.

    The wired-name question: it resolves for the shell asking, and will not
    resolve for the shell Claude Code is actually launched from. Returns False
    when the name does not resolve at all — that is a different finding, owned
    by the existing unresolvable-interpreter check.
    """
    hit = shutil.which(name)
    if not hit:
        return False
    root = venv_root_of(hit)
    if root is None:
        active = os.environ.get("VIRTUAL_ENV")
        if not active:
            return False
        try:
            if not Path(hit).is_relative_to(Path(active)):
                return False
        except (OSError, ValueError):
            return False
        root = Path(active)
    return shutil.which(name, path=path_without(root)) is None


def interpreter_token(command: str) -> str:
    """argv[0] of a settings.json command string.

    Deliberately not ``shlex``: it mangles backslashes in posix mode, so a
    Windows interpreter path arrives corrupted and then fails to resolve —
    a spurious warning every run. Mirrors the extractor in
    ``tools/cc/hooks/session_start.py``, which cannot be imported from here
    (``espalier/`` never imports ``tools/cc/``).
    """
    cmd = (command or "").strip()
    if not cmd:
        return ""
    if cmd[:1] in ("'", '"'):
        end = cmd.find(cmd[0], 1)
        return cmd[1:end] if end > 0 else cmd[1:]
    return cmd.split(None, 1)[0]


def is_statusline_shim_head(token: str) -> bool:
    """Is ``token`` (an unquoted argv[0]) the Windows statusline shim?

    ``init`` on Windows wires ``statusLine.command`` as
    ``"${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" <interpreter>``
    (DEF-729): the shim is the head so batch's or-operator can print the
    fallback line when the interpreter is gone, and the interpreter is its
    first ARGUMENT. Matched on the tail so a drive-absolute or a
    backslash spelling from a hand edit still reads as the shim.
    """
    from espalier.managed_paths import STATUSLINE_SHIM  # one spelling; lazy: keep this module stdlib-light

    # Case-insensitive: the string runs on Windows, whose filesystem is, so
    # a hand-edited `STATUSLINE.CMD` head runs the shim and must read as it.
    return token.replace("\\", "/").lower().endswith(STATUSLINE_SHIM)


def after_head_index(command: str, head: str) -> int:
    """The index in ``command`` (unstripped) just past its leading ``head``
    token and the quote that closed it; ``-1`` when ``head`` is not there.

    Measured on the ORIGINAL string, never a stripped copy: an offset taken
    from a stripped tail's length is short by the trailing whitespace a hand
    edit leaves, and the rewire then searched past the interpreter word and
    silently changed nothing (both reviewers, 2026-09-13).
    """
    if not head:
        return -1
    idx = command.find(head)
    if idx < 0:
        return -1
    end = idx + len(head)
    quote = command[idx - 1] if idx > 0 else ""
    if quote in ("'", '"') and end < len(command) and command[end] == quote:
        end += 1
    return end


def rest_after_token(command: str, token: str) -> str:
    """``command`` after its leading ``token`` and the quote that closed it."""
    end = after_head_index(command or "", token)
    if end < 0:
        return ""
    return command[end:].strip()


def interpreter_site_token(command: str) -> str:
    """The interpreter a settings.json command string runs.

    argv[0] for every hook entry and for a POSIX statusLine; argv[1] when
    argv[0] is the Windows statusline shim. BOTH readers of a statusLine --
    ``doctor``'s resolver check and ``cli.rewire_interpreter_in_settings``
    -- take the token from here, so they cannot disagree about which word is
    the interpreter (the disagreement DEF-620 measured on the legacy shell
    form, one level over).
    """
    head = interpreter_token(command)
    if not is_statusline_shim_head(head):
        return head
    return interpreter_token(rest_after_token(command, head))
