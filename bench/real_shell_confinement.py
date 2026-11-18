"""The one condition set a real-shell drive in ``bench/`` runs before it hands
a row to an interpreter.

⚠ THIS MODULE IS THE REASON THE DIFFERENTIALS ARE SAFE TO RUN. The Bash
differential (``reachability_differential.py``) and its PowerShell twin
(``powershell_reachability_differential.py``) execute genuine recursive deletes
inside a throwaway directory. If a template ever reached the interpreter with
its placeholder unsubstituted, or with an operand that lands outside the
throwaway, the command run would be a delete against the real filesystem: the
2026-09-17 incident (``docs/incidents/2026-09-17-real-shell-fixture-wipe.md``)
was a fixture variable expanded by the wrong layer, naming the root.

ONE SET, TWO SHELLS (DEF-5085). Each differential held its own hand-written
copy until 2026-11-17, so a condition strengthened on one shell's drive was not
strengthened on the other's: DEF-830 gave the Bash copy its binding condition,
and the PowerShell copy went on accepting ``$HOME`` behind its declared
operand. Every condition lives here and runs for both shells. What differs
between them is data, a :class:`Shell` profile each differential declares
beside its operand reader, and a profile field that leaves part of a condition
out says why where it is declared. Add a condition here, never in a profile.

This is confinement for a test fixture, not a security boundary: it guards
against a mis-substituted template, not against hostile input.

Stdlib only, and it imports nothing from the hook tree or the rest of
``bench/``.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Callable

#: Substituted with the throwaway victim before anything is executed.
PLACEHOLDER = "__TARGET__"


class UnsafeToExecute(RuntimeError):
    """The command about to be executed is not provably confined to the sandbox."""


#: A parameter expansion by name, bare or braced (a command substitution
#: `$(`, an ANSI-C quote `$'` and the special parameters are not names; a
#: delete operand that carries one is condition (9)'s).
PARAMETER_EXPANSION_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")

#: The expansions condition (9) reads as names: a bare ``$name`` and a whole
#: ``${name}``, nothing else. ``PARAMETER_EXPANSION_RE`` reads a name inside a
#: braced form with an operator too (``${name:+/}``), and that form expands to
#: whatever follows its operator, so it is a substitution, not a name.
_WHOLE_EXPANSION_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})")

#: The characters bash reads in a BARE word as something other than the word:
#: its metacharacters (a blank, a tab, a newline, ``|&;()<>``), the quotes,
#: the expansions' ``$`` and backtick, and the glob characters. A victim path
#: carrying one is not one operand to every row: a consumer that splits on
#: whitespace (``find | xargs``, ``for x in $(find …)``) hands the remove verb
#: the PREFIX before the blank -- the real directory beside a spaced temp root
#: (``/x/axis`` beside ``/x/axis tmp``) -- which conditions (5) to (9) cannot
#: see, since that operand arrives on stdin or in a variable the loop binds
#: (driven 2026-11-04, DEF-4093). The rehearsal's ``_INERT`` (what a plain
#: root may not carry) is a subset, and the Bash differential builds its
#: sandbox under the rehearsal's plain temp root, so condition (4) never fires
#: there; it is the belt to that brace. PowerShell's spellings are the three
#: declared relatives, which carry none of these.
BARE_WORD_HAZARDS = frozenset(" \t\n|&;()<>'\"$`*?[")

#: The word forms an interpreter makes into other words or another path
#: before its delete sees them, which an operand reader keeps as ONE name
#: (DEF-2100). Read as text, each resolves inside the sandbox, so condition
#: (7) passed it; condition (9) refuses it on a shell whose profile names the
#: form. Driven 2026-11-17, echo-only, on Windows PowerShell 5.1 and on WSL
#: Ubuntu 24.04's bash 5.2.
EXPANSIONS: dict[str, re.Pattern[str]] = {
    # bash's brace expansion: `{~,x}` is the home directory and `x`, `{x,/}`
    # the root, and a nested pair (`{{x},/}`) expands its outer level. A
    # formed one carries a comma or a `..` sequence, so find's `{}` is none;
    # the pattern spans pairs, so it over-reads a comma between two of them.
    "brace": re.compile(r"\{.*(?:,|\.\.).*\}"),
    # a glob in a path component that opens with a dot: where the shell does
    # not skip dots (every bash before 5.2, the Mac's /bin/bash 3.2 among
    # them, and 5.2 with `globskipdots` off) `.?` matches `..` and `.*`
    # matches `.` and `..`, a walk out of the directory. It over-reads
    # `.hidden*`, which cannot.
    "dot-glob": re.compile(r"(?:^|/)\.[^/]*[*?[]"),
    # a drive the interpreter maps through its own table: a provider-qualified
    # path (`FileSystem::/`, `Microsoft.PowerShell.Core\FileSystem::`), or a
    # drive name longer than one letter (`HKCU:` is the registry, `Env:` the
    # environment, PowerShell 7's `Temp:` the temp directory). A one-letter
    # drive is a path this host resolves.
    "mapped-drive": re.compile(r"^[A-Za-z][\w./\\-]*::|^[A-Za-z][\w.-]+:"),
}

#: The steps condition (10) cannot place, by the group a profile's
#: `directory_changes` names each with, and why each is not read. A step
#: matched by one of these refuses every relative delete operand in the row.
UNREAD_MOVES: dict[str, str] = {
    "stack": "it returns to a place the row's directory stack holds",
    "fixed": "it moves to a place its own name fixes (the parent, the drive root)",
    "script": "it runs a script whose text this set does not read",
}


@dataclass(frozen=True)
class Shell:
    """What one shell's drive hands the conditions: how its rows name the
    victim, how its deletes are spelled, and how its operands are read."""

    #: Named in a refusal.
    name: str
    #: Every operand of every delete head in a command: the seam, each shell's
    #: own lexer and head roster. Raises :class:`UnsafeToExecute` on a string
    #: it cannot lex.
    delete_operands: Callable[[str], list[str]]
    #: The delete operands condition (10) judges where the row moves its
    #: directory. A reader's over-read that (7) passes, since it resolves
    #: against the sandbox, reads as a relative name behind a move; a profile
    #: whose reader does that names a narrower reading here and says why.
    #: None from it: that reading cannot read this command, and (10) judges
    #: `delete_operands`' instead.
    moved_operands: Callable[[str], "list[str] | None"]
    #: The texts a row of this shell names the victim by, given its path.
    victim_spellings: Callable[[Path], tuple[str, ...]]
    #: True where a spelling must open a word (a blank before it): a relative
    #: spelling is otherwise found inside unrelated prose.
    spelling_opens_a_word: bool
    #: A delete whose FIRST operand is a root, home or bare glob, over the
    #: whole string.
    catastrophic: re.Pattern[str]
    #: A delete whose first operand is absolute, home-relative or
    #: parent-escaping, over the whole string; None for a shell whose rows
    #: spell the victim absolute, where condition (7)'s resolution reads it.
    escaping: re.Pattern[str] | None
    #: The delete a lone operand is re-asked under (condition 7).
    lone_delete: str
    #: The characters that open a substitution in an operand, or that the
    #: reader hands over for an argument the interpreter computes (condition 9).
    substitution_marks: str
    #: Each step of the row that changes where a relative operand lands
    #: (condition 10), over the whole string: a match is one move, and its
    #: destination is the first word after the match that is not one of
    #: `move_switches`. A match in which one of :data:`UNREAD_MOVES`' groups
    #: took part is a step whose landing is not in its words (a pop, a script
    #: the row runs), refused under that group's reason; a link the row makes
    #: is `makes_links`', which refuses every delete operand, not only a
    #: relative one.
    #: None: this leg does not read its moves, so condition (10) refuses
    #: every relative delete operand, move or no move; the profile says why.
    directory_changes: "re.Pattern[str] | None"
    #: The words after a move that are not its destination, lowercased: its
    #: switches, and the parameter names a destination follows.
    move_switches: frozenset[str]
    #: The word of the row that makes a link, or None (condition 10): a link
    #: is made when the row runs, after condition (7) resolved each operand
    #: on a disk that does not hold it yet, so a delete through it, spelled
    #: absolute or not, lands where no condition read. The profile says which
    #: spellings it reads and which it does not.
    makes_links: Callable[[str], "str | None"]
    #: Names the interpreter binds itself to no path (condition 8).
    self_bound: frozenset[str] = frozenset()
    #: The characters this shell separates path components with; condition
    #: (7) reads each as `/` before it resolves an operand.
    separators: str = "/"
    #: The forms of :data:`EXPANSIONS` this shell's interpreter performs
    #: (condition 9). A profile that leaves a form out says why.
    expansions: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        unknown = self.expansions - EXPANSIONS.keys()
        if unknown:
            raise ValueError(
                f"{self.name}: no expansion form {sorted(unknown)} in the set, "
                f"which holds {sorted(EXPANSIONS)}")
        groups = set(self.directory_changes.groupindex) if self.directory_changes else set()
        if groups - UNREAD_MOVES.keys():
            raise ValueError(
                f"{self.name}: no unread move {sorted(groups - UNREAD_MOVES.keys())} in the "
                f"set, which holds {sorted(UNREAD_MOVES)}")


def _path_text(word: str, shell: Shell, env: "dict[str, str] | None") -> str:
    """`word` with each whole parameter expansion `env` binds put in, read
    with `shell`'s separators. A name `env` does not bind is left as written,
    so it reads as a relative name."""
    def bound(match: "re.Match[str]") -> str:
        return (env or {}).get(match.group(0).lstrip("$").strip("{}"), match.group(0))
    text = _WHOLE_EXPANSION_RE.sub(bound, word)
    for separator in shell.separators:
        text = text.replace(separator, "/")
    return text


#: The pieces of the text after a move, in order: a run of blanks (a newline
#: among them ends the command), a separator, a word (quoted pieces and plain
#: characters glued together), or a quote no piece closes.
_MOVE_PIECE_RE = re.compile(
    r"""(?P<blank>\s+)|(?P<end>[;&|(){}])"""
    r"""|(?P<word>(?:'[^']*'|"[^"]*"|[^\s;&|(){}'"])+)|(?P<open>['"])""")


def _move_destination(
    cmd: str, move: "re.Match[str]", shell: Shell, env: "dict[str, str] | None",
    root: Path,
) -> "Path | str":
    """Where `move` takes the row, resolved, or why that cannot be read.

    Read the way condition (7) reads an operand: one bare word, quoted whole
    or not at all, bound expansions put in, the shell's separators read.
    Anything else is a destination this set does not read: a step one of
    :data:`UNREAD_MOVES` names; no word; a comment or a redirect where the
    word would be (the destination is then a later word, or none); a word
    glued to a character the piece reading ends at, which the shell may read
    on with (a brace, an opener, a quote); an option it does not know, ``-``
    or ``+N`` (a place the row's history or stack holds); a substitution, an
    expansion or a wildcard (PowerShell's location cmdlets expand one); and a
    drive, read with neither host's rules (below).

    ⚠ WRITTEN FOR POWERSHELL'S GRAMMAR, the one leg that reads its moves (its
    test file pins that the Bash profile reads none). A leg that starts
    reading them brings what its shell adds here: bash's ``CDPATH`` search and
    its backslash escape were dropped as dead code (code review of DEF-2099).
    """
    for group, reason in UNREAD_MOVES.items():
        if move.groupdict().get(group) is not None:
            return reason
    found = None
    for piece in _MOVE_PIECE_RE.finditer(cmd, move.end()):
        if piece.lastgroup == "blank":
            if "\n" in piece.group(0):
                break
            continue
        if piece.lastgroup != "word":
            break
        if piece.group(0).lower() in shell.move_switches:
            continue
        found = piece
        break
    if found is None:
        return "it names no destination"
    word, after = found.group(0), cmd[found.end():found.end() + 1]
    if word[0] == "#":
        return f"{word!r} opens a comment, so the move names no destination on its line"
    if set("<>") & set(word):
        return f"{word!r} is or holds a redirect, not the destination"
    if after and not after.isspace() and after not in ";&|)}":
        return f"{word!r} is glued to {after!r}, which the shell may read as part of it"
    if word[0] in "-+":
        return f"{word!r} is an option or a place its history holds"
    if len(word) >= 2 and word[0] == word[-1] and word[0] in "'\"" and word[0] not in word[1:-1]:
        word = word[1:-1]
    if "'" in word or '"' in word:
        return f"{word!r} is quoted in part"
    stripped = _WHOLE_EXPANSION_RE.sub("", word)
    if set(shell.substitution_marks) & set(stripped) or set("*?[") & set(stripped):
        return f"{word!r} holds a substitution or a wildcard"
    if any(EXPANSIONS[form].search(stripped) for form in shell.expansions):
        return f"{word!r} holds an expansion"
    if any(name not in (env or {}) for name in PARAMETER_EXPANSION_RE.findall(word)):
        return f"{word!r} names an unbound variable"
    text = _path_text(word, shell, env)
    # `X:` moves to drive X's current directory and `X:/a` under its root:
    # Windows' path rules place the second, and the host's would read both as
    # a relative name on POSIX, inside the sandbox (failure-mode review of
    # DEF-2099), so on a leg that reads a backslash as a separator a drive
    # is placed only where it is absolute on a Windows host
    drive = PureWindowsPath(text)
    if "\\" in shell.separators and drive.drive and not (os.name == "nt" and drive.is_absolute()):
        return f"{word!r} names a drive, which this host's path rules do not place"
    try:
        path = Path(text).expanduser()
    except RuntimeError:
        return f"{word!r} names an unknown home directory"
    if not path.is_absolute():
        if ".." in Path(text).parts:
            return f"{word!r} climbs out of the directory it starts in"
        path = root / path
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return f"{word!r} does not resolve"


def _is_relative(operand: str, shell: Shell, env: "dict[str, str] | None", cmd: str) -> bool:
    """Whether condition (10) reads `operand` as relative: not the
    interpreter's own name, and not absolute once `env`'s names are put in.
    A home this host cannot name is refused here, as (7) refuses it: an
    operand only the moved reading sees reaches this first."""
    if any(operand in (f"${n}", f"${{{n}}}") for n in shell.self_bound):
        return False
    try:
        return not Path(_path_text(operand, shell, env)).expanduser().is_absolute()
    except (OSError, RuntimeError):
        raise UnsafeToExecute(f"unresolvable delete operand {operand!r}: {cmd!r}") from None


def assert_confined(
    cmd: str, victim: Path, sandbox: Path, shell: Shell,
    env: "dict[str, str] | None" = None,
) -> None:
    """Refuse to hand `cmd` to `shell`'s interpreter unless it is confined to
    `sandbox`. Ten independent conditions, each fatal, each run for every
    shell:

    1. the placeholder is gone (substitution happened at all)
    2. the victim is named by one of the shell's spellings (it was substituted
       with the RIGHT thing)
    3. the victim really is inside the sandbox
    4. every spelling of the victim is one bare word (none of
       `BARE_WORD_HAZARDS`) -- a consumer that splits on whitespace would hand
       the delete the prefix before a blank, an operand (5) to (9) never see
       (DEF-4093)
    5. no delete in the final string takes a root, `~`, a drive root or a bare
       glob as its first operand
    6. no delete in the final string takes an absolute, home-relative or
       parent-escaping first operand, on a shell whose rows spell the victim
       relative
    7. EVERY delete operand, not just the first: each resolves inside the
       sandbox, read with the shell's own separators, and each, asked alone,
       is neither (5)'s nor (6)'s
    8. every parameter expansion inside a delete operand names a variable
       `env` binds to a path inside the sandbox, or one the interpreter binds
       itself to no path -- the literal-operand conditions cannot see what a
       shell will substitute for `$name`, and an unbound fixture variable is
       the 2026-09-17 incident's shape; an expansion elsewhere in the row (the
       git rows' environment probes) is not a delete's operand and is left to
       the shell
    9. no substitution and no expansion is left in a delete operand once (8)
       has read its names: the shell's substitution marks, and the forms of
       `EXPANSIONS` it performs. Its value is unknown until the shell runs
       it, so the row is classifier-only (the incident's rules 1 and 2)
    10. a relative delete operand (the profile's `moved_operands`) is
       vouched for only where the leg reads its moves (the profile's
       `directory_changes`, None on a leg that does not, which refuses
       every one) and, where the row moves, every move's destination is
       read, inside the sandbox and, spelled relative, climbs no `..`, and
       the relative operand climbs none either -- (7) resolves against the
       sandbox, where a row starts, and a real shell resolves against
       wherever the row moved to (DEF-2099); and a row that makes a link (the
       profile's `makes_links`) has no delete vouched for, since (7) resolved
       its operands before the link existed

    (5) and (6) are the belt to (1)-(3)'s braces: they do not care HOW a
    catastrophic operand got there, only that one is present, and they read
    the raw string, so they also see a delete inside a quoted span the operand
    reader lexes as one word (PowerShell runs a `$(...)` inside double quotes).

    ⚠ (7) to (10) read the delete as a bare shell word. Inside an interpreter
    program (`python3 -c '... os.system("<delete>")'`) it is ONE quoted token
    to the lexer, so none of them sees an operand there: those rows are
    confined by (1)-(6) alone ((1)-(5) on a shell with no escaping form), which
    is why a Bash body, read bare, names no operand but the victim (its test
    file pins it, and that no wrapper names one of its own).
    What an operand reader keeps as a harmless name though the interpreter
    computes it is (7)'s separators and (9)'s marks and expansions since
    DEF-2100. A delete head the reader does not read as a literal word (the
    Bash reader reads `rm` alone; a head spelled by path or computed, on
    either shell) is that row's remainder.
    """
    if PLACEHOLDER in cmd:
        raise UnsafeToExecute(f"placeholder never substituted: {cmd!r}")
    spellings = shell.victim_spellings(victim)
    opener = " " if shell.spelling_opens_a_word else ""
    if not any(f"{opener}{spelling}" in cmd for spelling in spellings):
        raise UnsafeToExecute(
            f"victim path absent from command: no declared sandbox operand "
            f"({list(spellings)}) in: {cmd!r}")
    try:
        victim.resolve().relative_to(sandbox.resolve())
    except ValueError:
        raise UnsafeToExecute(
            f"victim {victim} is outside sandbox {sandbox}") from None
    # (4) The victim's spelling is ONE bare word. Quoted, a spaced path is one
    # operand to the delete and (5) to (9) pass; but a consumer that splits on
    # whitespace (`find | xargs`, `for x in $(find …)`) hands the remove verb
    # the prefix before the blank -- the real directory beside the spaced temp
    # root -- and that operand is never in the text. Only the spelling itself
    # can be read, so it is read here (DEF-4093).
    for spelling in spellings:
        hazards = BARE_WORD_HAZARDS & set(spelling)
        if hazards:
            raise UnsafeToExecute(
                f"victim path {spelling!r} carries {sorted(hazards)}: a row reads it as "
                f"more than one shell word, and a consumer that splits on whitespace would "
                f"hand the delete the prefix before it, a path outside the sandbox: {cmd!r}")
    hit = shell.catastrophic.search(cmd)
    if hit:
        raise UnsafeToExecute(
            f"refusing to execute a catastrophic operand {hit.group(0)!r}: {cmd!r}")
    # (6) ANY first operand that is not plainly relative, on a shell whose rows
    # spell the victim relative. (5) catches only the bare forms (`/`, `~`, a
    # drive root, a bare glob); it says nothing about `C:\Users\...` or
    # `~/Documents`.
    if shell.escaping is not None:
        escaped = shell.escaping.search(cmd)
        if escaped:
            raise UnsafeToExecute(
                f"delete operand escapes the sandbox {escaped.group(0)!r}: {cmd!r}")
    # (7) EVERY operand, not just the first. (5) and (6) anchor on the verb
    # plus ONE operand, so a second operand riding behind a valid path was
    # invisible to them -- and `rm` takes a list, and PowerShell's positional
    # -Path is string[], so the second operand really does bind and delete.
    #
    # ⚠ RESOLVED AGAINST THE SANDBOX, NOT THE PROCESS CWD. Both drives run
    # their rows with cwd set to the sandbox, so a bare relative operand IS
    # confined; judging it against the caller's cwd would refuse well-formed
    # rows (a heredoc terminator lexes as a trailing bare word) while proving
    # nothing. A row that moves first leaves that premise: condition (10)
    # reads where it moves, or refuses the operand on a leg that does not
    # read its moves; a glob it expands there is the lone re-ask's.
    #
    # Each operand is then re-asked ALONE with this shell's own patterns, by
    # synthesising a one-operand delete around it: one definition of
    # "catastrophic", never a second that can drift.
    #
    # Read with the SHELL's separators, not the host's: PowerShell's provider
    # reads `..\outside` as a parent walk on every host, and a POSIX path
    # reads its backslash as a name character (DEF-2100).
    root = sandbox.resolve()
    operands = shell.delete_operands(cmd)
    for operand in operands:
        path_text = operand
        for separator in shell.separators:
            path_text = path_text.replace(separator, "/")
        try:
            expanded = Path(path_text).expanduser()
            candidate = expanded if expanded.is_absolute() else root / expanded
            resolved = candidate.resolve()
        except (OSError, RuntimeError):
            raise UnsafeToExecute(
                f"unresolvable delete operand {operand!r}: {cmd!r}") from None
        try:
            resolved.relative_to(root)
        except ValueError:
            raise UnsafeToExecute(
                f"delete operand {operand!r} resolves outside sandbox {sandbox}: "
                f"{cmd!r}") from None
        probe = f"{shell.lone_delete} {operand}"
        if shell.catastrophic.search(probe):
            raise UnsafeToExecute(
                f"catastrophic delete operand {operand!r} behind a valid one: {cmd!r}")
        if shell.escaping is not None and shell.escaping.search(probe):
            raise UnsafeToExecute(
                f"escaping delete operand {operand!r} behind a valid one: {cmd!r}")
    # (8) EVERY parameter expansion inside a delete operand, bound or refused.
    # The Bash loop-carrier bodies (DEF-830) carry one; a double-quoting
    # wrapper expands it in the OUTER shell before the loop's `read` or `for`
    # binds it, so its value is the row's environment's or nothing. (5) to (7)
    # read the literal token and pass for any value the shell later
    # substitutes; this one asks the environment. An unbound name is refused
    # whatever the shell would have made of it. Scoped to the delete operands
    # because that is where the hazard is: the git rows probe their
    # environment with expansions that are no delete's operand.
    for operand in operands:
        for name in PARAMETER_EXPANSION_RE.findall(operand):
            # the interpreter's own name only as the WHOLE operand: `$null/..`
            # is the parent walk it expands to, not the null it starts with
            if name in shell.self_bound and operand in (f"${name}", f"${{{name}}}"):
                continue
            value = (env or {}).get(name)
            if value is None:
                raise UnsafeToExecute(
                    f"unbound parameter expansion ${name} in a delete operand: {cmd!r}")
            try:
                Path(value).resolve().relative_to(root)
            except (ValueError, OSError, RuntimeError):
                raise UnsafeToExecute(
                    f"${name} is bound outside sandbox {sandbox}: {cmd!r}") from None
    # (9) Whatever substitution is left once (8) has read the whole names: a
    # command substitution, a braced form with an operator (`${name:+/}`
    # expands to what follows it), a special parameter, and on a shell whose
    # backtick substitutes, a backtick. None has a value before the shell runs
    # it (DEF-5085; until then `$(echo ~)` passed both copies). Then the
    # expansions the shell performs, which no mark opens (DEF-2100).
    for operand in operands:
        stripped = _WHOLE_EXPANSION_RE.sub("", operand)
        left = sorted(set(shell.substitution_marks) & set(stripped))
        if left:
            raise UnsafeToExecute(
                f"a substitution ({''.join(left)}) in delete operand {operand!r}: its value "
                f"is unknown until the {shell.name} interpreter runs it: {cmd!r}")
        for form in sorted(shell.expansions):
            hit = EXPANSIONS[form].search(stripped)
            if hit:
                raise UnsafeToExecute(
                    f"an expansion ({form}, {hit.group(0)!r}) in delete operand {operand!r}: "
                    f"the {shell.name} interpreter makes it into other words or another path, "
                    f"unknown until it runs: {cmd!r}")
    # (10) A relative operand in a row that moves its directory (DEF-2099).
    # (7) resolves a relative operand against the sandbox, where both drives
    # start a row, and a row that moves first leaves that premise: a real
    # shell removes the name under the directory moved to. A leg that does
    # not read its moves (`directory_changes` None) cannot tell a row that
    # stays from one that moves, so it vouches for no relative operand. On a
    # leg that reads them, where the row moves and a delete operand is
    # relative, every move is read: its destination must be read, lie inside
    # the sandbox and, spelled relative, climb no `..`; and the relative
    # operand climbs no `..` either. Every directory the row can then stand
    # in is the sandbox or a place under it, for every move the profile
    # reads, whatever order the moves run in and whichever a subshell undoes,
    # and an operand that only descends from one stays inside. A move
    # anywhere in the row counts, one after the delete too: an over-read,
    # priced by the population pins. The operands are the profile's
    # `moved_operands` (a delete that names none, reading its names from a
    # pipe, is judged by whether the listing that feeds it is relative; where
    # an absolute listing starts is no condition's, `DEF-2101`), or the ones
    # (7) read where that reading cannot read the command.
    #
    # A row that makes a link has no delete vouched for, absolute or relative
    # (the profile's `makes_links`; the dispatcher's note on DEF-2099): (7)
    # resolved each operand before the link existed, so `ln -s / <victim>/l`
    # then a delete of `<victim>/l/` read as inside the sandbox.
    reads_moves = shell.directory_changes is not None
    moves = list(shell.directory_changes.finditer(cmd)) if shell.directory_changes else []
    judged = shell.moved_operands(cmd)
    deletes = operands if judged is None else judged
    link = shell.makes_links(cmd) if deletes else None
    if link is not None:
        raise UnsafeToExecute(
            f"delete operand {deletes[0]!r} in a row that makes a link ({link!r}): the link "
            f"is made after this set resolved the operand, so where a delete through it "
            f"lands is not read: {cmd!r}")
    relative = [operand for operand in deletes if _is_relative(operand, shell, env, cmd)
                ] if moves or not reads_moves else []
    if relative and not reads_moves:
        raise UnsafeToExecute(
            f"relative delete operand {relative[0]!r}: the {shell.name} leg does not read "
            f"where a row moves its directory, so it vouches for no relative operand; spell "
            f"the operand, or the listing a delete reads its names from, from the "
            f"placeholder, the victim's absolute path: {cmd!r}")
    if moves and relative:
        for move in moves:
            where = _move_destination(cmd, move, shell, env, root)
            if isinstance(where, str):
                raise UnsafeToExecute(
                    f"relative delete operand {relative[0]!r} in a row that moves its "
                    f"directory ({move.group(0).strip()!r}) to a place this set does not "
                    f"read: {where}: {cmd!r}")
            try:
                where.relative_to(root)
            except ValueError:
                raise UnsafeToExecute(
                    f"relative delete operand {relative[0]!r} in a row that moves its "
                    f"directory ({move.group(0).strip()!r}) to {where}, outside sandbox "
                    f"{sandbox}: {cmd!r}") from None
        for operand in relative:
            if ".." in Path(_path_text(operand, shell, env)).parts:
                raise UnsafeToExecute(
                    f"relative delete operand {operand!r} climbs with `..` in a row that "
                    f"moves its directory ({moves[0].group(0).strip()!r}): {cmd!r}")
