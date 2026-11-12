"""A fixture's temp path in shell text, quoted for that shell only when it must be.

pytest's ``tmp_path`` is plain on every CI cell today, but a contributor's
``--basetemp`` or temp root can hold a space (``TMPDIR=/Users/x/axis
basetemp``), and a path pasted bare into a command is then two words to every
shell: ``cd /x/axis basetemp/t`` fails, the delete after it runs where the
command stood, and the guard's verdict on that text moves while the fixture's
claim did not (DEF-5082: 155 tests in nine files red under one spaced
``--basetemp``, measured on 2026-11-03 and 2026-11-04). The fix is the
fixture's, never the guard's: a path goes into shell text the way an operator
types one, quoted when it holds whitespace -- and ONLY then, so a plain root
keeps today's bytes and a spaced root adds the quoted coverage instead of
replacing the bare one.

Three shells, one quote. Double quotes are the one quoting bash, PowerShell and
cmd.exe all read as one word (the product's ``quoted_if_spaced`` makes the same
choice for the same reason), and they stay literal inside a PowerShell
single-quoted program string (``Start-Process cmd -ArgumentList '/c rd /s /q
"..."'``). What differs is where a glob goes: bash expands ``*`` only outside
quotes, so a glob tail stays out (``"/x/a b/repo"/*``); PowerShell's cmdlets
expand their own wildcards and read ``"a b"/x`` as TWO arguments (measured on
pwsh 7.6, 2026-11-04), so the whole word goes inside, and cmd.exe takes the
whole word too. A path holding a double quote, a ``$`` or a backtick is not
quoted right by this; no temp path pytest makes holds one, and the quoting
that would is per shell and costs more than it saves.

Not a test module (leading underscore) -- no marker classification needed.
"""
from __future__ import annotations

import re

import pytest

#: The shell a fill is for: the Bash tool's ``sh``, the PowerShell tool's
#: ``ps``, and ``cmd`` for a cmd.exe program on either tool.
SH = "sh"
PS = "ps"
CMD = "cmd"

_GLOB = frozenset("*?[")
#: Where a shell word ends: whitespace, the operators of the three shells, the
#: quotes, PowerShell's array comma and the braces of a block or a list. A
#: backtick is a word character: PowerShell's escape, which a path row can carry.
_WORD_END = frozenset(" \t\r\n;|&<>()'\",{}")


def spaced(path: object) -> bool:
    """Does ``path`` hold whitespace, so a shell reads it bare as two words?"""
    return any(ch.isspace() for ch in str(path))


def quoted(word: str, shell: str = SH) -> str:
    """``word`` -- a path, or a path and what follows it to the end of its
    shell word -- double-quoted when it holds whitespace, else unchanged.
    For ``SH`` a glob tail stays outside the quotes, from the last ``/``
    before the first ``*``, ``?`` or ``[``, where bash expands it; for ``PS``
    and ``CMD`` the whole word goes inside."""
    if not spaced(word):
        return word
    if shell == SH:
        glob_at = next((i for i, ch in enumerate(word) if ch in _GLOB), -1)
        cut = word.rfind("/", 0, glob_at) if glob_at > 0 else -1
        if cut > 0:
            return f'"{word[:cut]}"{word[cut:]}'
    return f'"{word}"'


def _open_quote(text: str) -> tuple[str, int]:
    """The quote ``text`` leaves open at its end (``'``, ``"`` or ``""``) and
    the index it opened at (-1 when none is open)."""
    state, opened = "", -1
    for at, ch in enumerate(text):
        if not state and ch in "'\"":
            state, opened = ch, at
        elif ch == state:
            state, opened = "", -1
    return state, opened


#: cmd.exe's program switch at the end of the text before a quote: ``/c`` or
#: ``/k`` (``//c`` as Git Bash spells it), after a blank or at the start.
_CMD_PROGRAM_SWITCH_END = re.compile(r"(?:^|\s)//?[ckCK]\s+$")


def fill(template: str, name: str, path: str, shell: str = SH) -> str:
    """``template`` with each ``name`` placeholder (``{t}``, ``{abs}``)
    replaced by ``path``, the shell word the placeholder begins quoted per
    :func:`quoted` where the path holds whitespace. A placeholder the fixture
    quoted itself is filled bare: one that opens a quoted string
    (``'{scratch}/a,b'``) or sits inside a double-quoted one (``"src,
    {scratch}/x"``). One inside a single-quoted string is a word of a program
    handed to another shell (``-ArgumentList '/c rd /s /q {t}'``), so it is
    double-quoted, which that shell reads and the outer one keeps literal.

    For ``CMD``, a double-quoted string that opens right after cmd's ``/c``
    or ``/k`` quotes nothing: cmd strips that outer pair and reads the
    program inside it bare (``cmd --% /c "rd /s /q {t}"``), so a placeholder
    in it is quoted as a bare one is (``... /q "<path>""``), which keeps the
    spaced path one word to cmd (#608's four ``ps-cmd-stopparse-quoted-*``
    rows, red under a spaced ``--basetemp`` before this)."""
    out: list[str] = []
    at = 0
    while True:
        found = template.find(name, at)
        if found < 0:
            out.append(template[at:])
            return "".join(out)
        out.append(template[at:found])
        end = found + len(name)
        stop = end
        while stop < len(template) and template[stop] not in _WORD_END:
            stop += 1
        word = path + template[end:stop]
        state, opened = _open_quote(template[:found])
        cmd_strips = (shell == CMD and state == '"'
                      and _CMD_PROGRAM_SWITCH_END.search(template[:opened]) is not None)
        opens = found > 0 and template[found - 1] in "'\""
        bare = (opens or state == '"') and not cmd_strips
        out.append(word if bare else quoted(word, shell))
        at = stop


def skip_unless_plain(path: object, row: str) -> None:
    """Skip, saying why, a row that spells ``path`` bare ON PURPOSE -- an
    unquoted binding or reference the row is about -- when the path holds
    whitespace: the shell splits it there, and the row's claim is about a
    one-word path (DEF-5082). The spaced twin is an always-spaced row of its
    own, never this one quoted; a bare skip would hide which rows the root
    took out."""
    if spaced(path):
        pytest.skip(f"{row}: pytest's temp path {str(path)!r} holds whitespace and this row "
                    "spells it bare on purpose, so the shell splits it (DEF-5082); the "
                    "always-spaced twin row pins the split")
