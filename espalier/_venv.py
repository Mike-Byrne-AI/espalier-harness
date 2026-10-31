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


def entry_argv(command: object, args: object = None) -> tuple[str, list]:
    """``(argv[0], the words after it)`` of a settings.json hook entry.

    The FORM decides before the word (DEF-968). An entry carrying an ``args``
    list is exec form: Claude Code spawns ``command`` itself, with no shell and
    no tokenization on any platform (the upstream hooks page, section "Exec
    form and shell form"), so argv[0] is all of ``command`` -- a space in an
    interpreter path is part of the path, and a quote is part of the file
    name, which is why a quoted exec-form ``command`` cannot start -- and the
    words after it are ``args``. Without ``args`` the entry is shell form, and
    argv[0] is :func:`interpreter_token`'s first word, which agrees with
    ``sh -c`` and Git Bash -- with a leading ``~`` expanded, as the shell
    expands an unquoted one. A first-word reading of exec form named
    ``C:\\Program`` for an interpreter under ``C:\\Program Files``.

    Twin of ``tools/cc/hooks/session_start.py::_entry_argv`` (``espalier/``
    never imports ``tools/cc/``), pinned equal over one table of entry shapes
    by ``tests/test_hook_entry_argv.py``.
    """
    if isinstance(args, list):
        return (command if isinstance(command, str) else ""), list(args)
    cmd = command.strip() if isinstance(command, str) else ""
    head = interpreter_token(cmd)
    if not head:
        return "", []
    if cmd[:1] in ("'", '"'):
        end = cmd.find(cmd[0], 1)
        return head, (cmd[end + 1:].split() if end > 0 else [])
    return (os.path.expanduser(head) if head.startswith("~") else head), cmd.split()[1:]


def names_a_python(token: str) -> bool:
    """Does argv[0] ``token`` name a Python interpreter at all?

    Read on the file name -- either slash a separator, quotes off, lowercased,
    ``.exe`` dropped, and its first word only (an exec-form ``command`` of
    ``py -3`` or ``python -u`` names a Python it cannot start) -- so an
    absolute path to a below-floor interpreter is still asked (``DEF-636``).
    Not asked, on purpose: a ``$``-led head (``$HOME/.venv/bin/python``, which
    no reader here expands), ``pypy``, and a wrapper head (``uv run``,
    ``env``, ``poetry run``), whose interpreter is not argv[0]. Twin of
    ``tools/cc/hooks/session_start.py::_names_a_python`` (DEF-1024), pinned
    equal by ``tests/test_hook_entry_argv.py``.
    """
    if not token or token.startswith("$") or "${" in token:
        return False
    name = token.replace("\\", "/").rsplit("/", 1)[-1].strip("\"'").lower().split()
    base = name[0] if name else ""
    if base.endswith(".exe"):
        base = base[: -len(".exe")]
    return base == "py" or base.startswith("python")


def exec_name_has_space(command: str) -> bool:
    """Does an exec-form ``command``'s FILE NAME hold whitespace?

    Exec form spawns ``command`` as one file name, so a space in its
    directory is a real path's (``C:\\Program Files\\...``) while a space in
    the name (``py -3``, ``python -X utf8``) is a file no host has: the entry
    cannot start, and the launcher split of :func:`interpreter_argv` must not
    read it as ``py`` plus a flag (DEF-968). Twin of
    ``tools/cc/hooks/session_start.py::_exec_name_has_space``.
    """
    name = command.replace("\\", "/").rsplit("/", 1)[-1]
    return any(ch.isspace() for ch in name)


def shell_cut_path(command: str) -> str | None:
    """The Python path a shell-form ``command`` names unquoted across a space,
    which the shell cuts at that space; None when it does not.

    ``C:\\Program Files\\Python312\\python.exe x.py`` runs ``C:\\Program``
    under ``sh -c`` and Git Bash (exit 127, every guard fails open), and the
    cut word names no Python, so a reader that asks only argv[0] whether it
    is one skips the entry. This finds the longer word-prefix that does name
    a Python (not a ``.py``/``.sh`` script), where argv[0] is a path that is
    not a file. The rewire must DECLINE such an entry: swapping the cut word
    wrote ``python Envs/py312/bin/python3 ...``, which exits 2 -- a block on
    every tool call (failure-mode review, driven). Twin of
    ``tools/cc/hooks/session_start.py::_shell_cut_path``.
    """
    cmd = command.strip() if isinstance(command, str) else ""
    if not cmd or cmd[:1] in ("'", '"'):
        return None
    words = cmd.split()
    head = os.path.expanduser(words[0]) if words[0].startswith("~") else words[0]
    if not any(sep in head for sep in ("/", "\\")) or os.path.isfile(head):
        return None
    for end in range(2, len(words) + 1):
        prefix = " ".join(words[:end])
        if not prefix.endswith((".py", ".sh")) and names_a_python(prefix):
            return prefix
    return None


def is_statusline_shim_head(token: str) -> bool:
    """Is ``token`` (an unquoted argv[0]) the Windows statusline shim?

    ``init`` on Windows wires ``statusLine.command`` as
    ``. "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" <interpreter>``
    (DEF-729, DEF-3017; the operator before it is
    :func:`statusline_shim_end`'s to read): the shim is the head so batch's
    or-operator can print the
    fallback line when the interpreter is gone, and the interpreter is its
    first ARGUMENT. Matched on the tail so a drive-absolute or a
    backslash spelling from a hand edit still reads as the shim.
    """
    from espalier.managed_paths import STATUSLINE_SHIM  # one spelling; lazy: keep this module stdlib-light

    # Case-insensitive: the string runs on Windows, whose filesystem is, so
    # a hand-edited `STATUSLINE.CMD` head runs the shim and must read as it.
    return token.replace("\\", "/").lower().endswith(STATUSLINE_SHIM)


#: Where Claude Code looks for Git Bash before it asks PATH: the two literals
#: in its lookup (read from the 2.1.316 binary), drive letter and all.
GIT_BASH_DEFAULT_PATHS = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
)


def _settings_git_bash_paths(repo_root: Path | None) -> list[str]:
    """``env.CLAUDE_CODE_GIT_BASH_PATH`` from the settings files Claude Code
    applies to its own environment before its lookup (the 2.1.316 binary
    special-cases this variable in its settings-env filter), highest
    precedence first: the project's ``settings.local.json`` and
    ``settings.json``, then the user's. A file that cannot be read or
    parsed names nothing. Bytes through ``decode_bom``: a file written from
    Windows PowerShell 5.1 is UTF-16 with a BOM, and an editor's has UTF-8's."""
    import json

    from espalier.surface_contract import decode_bom  # lazy: keep this module stdlib-light

    files = [Path.home() / ".claude" / "settings.json"]
    if repo_root is not None:
        files[:0] = [repo_root / ".claude" / "settings.local.json",
                     repo_root / ".claude" / "settings.json"]
    found: list[str] = []
    for path in files:
        try:
            data = json.loads(decode_bom(path.read_bytes()))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        env = data.get("env") if isinstance(data, dict) else None
        value = env.get("CLAUDE_CODE_GIT_BASH_PATH") if isinstance(env, dict) else None
        if isinstance(value, str) and value:
            found.append(value)
    return found


def git_bash_path(repo_root: Path | None = None) -> str | None:
    """A Git Bash Claude Code can find on this host, or None.

    On Windows Claude Code runs a shell-form command -- the statusLine
    among them -- under Git Bash when its lookup finds one and under
    PowerShell when it does not, and the statusLine schema has no field to
    pin either (DEF-929). Its lookup, in order (read from the 2.1.316
    binary): ``CLAUDE_CODE_GIT_BASH_PATH`` when its file name is ``bash``,
    ``sh``, ``bash.exe`` or ``sh.exe`` and the path exists, else the two
    :data:`GIT_BASH_DEFAULT_PATHS`, else ``bin\\bash.exe`` two levels above
    the first ``git`` ``where.exe`` names.

    ``init`` no longer reads it: its render runs in both shells (DEF-3017).
    ``doctor`` does, to name a bare or ``&`` line an older install carries
    for the shell this host does not run. Followed in that order and
    WIDENED, because the two wrong answers cost differently there: a None
    where Claude Code finds Git Bash names a working bare line and asks for
    the dot, which also works; a path where it finds none stays silent over
    a bare line PowerShell blanks. So the variable is also read from the settings files
    Claude Code applies to its environment (``repo_root``'s and the
    user's), and every ``git`` on PATH is asked, not the first: a Git Bash
    terminal puts ``mingw64\\bin`` first, and a Claude Code launched from
    the Start menu reads ``cmd`` first. ``shutil.which`` in place of
    ``where.exe``, so nothing is spawned and ``doctor`` reads it on the
    healthy path (DEF-715). A variable set only in the shell that launches
    Claude Code is still unseen from any other shell.
    """
    names = ("bash.exe", "sh.exe", "bash", "sh")
    env = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    for value in ([env] if env else []) + _settings_git_bash_paths(repo_root):
        name = value.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if name in names and os.path.exists(value):
            return value
    for path in GIT_BASH_DEFAULT_PATHS:
        if os.path.exists(path):
            return path
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        git = shutil.which("git", path=entry) if entry else None
        if git:
            # Lexical, as Claude Code's path.win32 join is: `<git>\..\..\bin`.
            bash = os.path.normpath(os.path.join(git, "..", "..", "bin", "bash.exe"))
            if os.path.exists(bash):
                return bash
    return None


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


def _dot_operator(body: str) -> bool:
    """Does ``body`` (left-stripped) open with the dot operator: a ``.``
    and then whitespace? Glued to what follows, bash reads one word and
    not its builtin, and ``./x`` is a relative path."""
    return body[:1] == "." and body[1:2].isspace()


def statusline_shim_end(command: str) -> int:
    """The index in ``command`` (unstripped) just past its Windows statusline
    shim head and the quote that closed it, the operator before the head
    included; ``-1`` when the shim is not the head.

    ``init`` renders ``. "<shim>" <interpreter>``: the dot is an operator in
    both shells Claude Code picks between on Windows, so one line runs in
    either (DEF-3017). An install can carry the two forms before it: the
    bare head, which only Git Bash runs, and ``& "<shim>" <interpreter>``,
    PowerShell's call operator, which only PowerShell runs (DEF-929). Every
    reader of the head asks here -- :func:`interpreter_site_token`, the
    rewire's swap and its launcher-flag read, ``doctor``'s fallback notes --
    so none reads an operator as the interpreter, and none decides
    "shim-headed" by a copy of its own.
    """
    text = command or ""
    body = text.lstrip()
    if body[:1] == "&" or _dot_operator(body):
        body = body[1:].lstrip()
    head = interpreter_token(body)
    if not is_statusline_shim_head(head):
        return -1
    end = after_head_index(body, head)
    return -1 if end < 0 else len(text) - len(body) + end


def statusline_shim_called(command: str) -> bool:
    """Is ``command`` headed by the Windows statusline shim behind
    PowerShell's call operator -- the form ``init`` rendered, from DEF-929
    until DEF-3017, where Claude Code found no Git Bash? Read beside
    :func:`statusline_shim_end`, so the forms are told apart in one place."""
    return statusline_shim_end(command) >= 0 and (command or "").lstrip()[:1] == "&"


def statusline_shim_dotted(command: str) -> bool:
    """Is ``command`` headed by the Windows statusline shim behind the dot,
    the one form ``init`` renders, which runs under Git Bash and PowerShell
    alike (DEF-3017)? Read beside :func:`statusline_shim_end`."""
    return statusline_shim_end(command) >= 0 and _dot_operator((command or "").lstrip())


def interpreter_site_token(command: str) -> str:
    """The interpreter a settings.json command string runs.

    argv[0] for every hook entry and for a POSIX statusLine; the word after
    the Windows statusline shim when the shim is the head, bare, called or
    dotted (:func:`statusline_shim_end`). BOTH readers of a statusLine --
    ``doctor``'s resolver check and ``cli.rewire_interpreter_in_settings``
    -- take the token from here, so they cannot disagree about which word is
    the interpreter (the disagreement DEF-620 measured on the legacy shell
    form, one level over).
    """
    end = statusline_shim_end(command)
    if end < 0:
        return interpreter_token(command)
    return interpreter_token(command[end:])
