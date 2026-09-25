#!/usr/bin/env python3
"""PowerShell differential: real-interpreter reachability vs. what the guards deny.

The PowerShell twin of ``reachability_differential.py``, and the successor
``powershell_guard_rehearsal.py`` names in its own docstring:

    "The durable fix is a ``pwsh``-gated differential that GENERATES shapes and
    asks a real interpreter; this is the floor under that."

WHY THIS EXISTS
---------------
The Bash guards have an oracle outside their author: hand a generated command to
``/bin/bash``, build a real victim directory, and ask whether it is gone. That
oracle once caught **63 fail-opens** in a change that 80 purpose-written tests, 8
mutations and a 154/154 release benchmark all reported green.

The PowerShell half had no such oracle. It was written and revised on machines
with no PowerShell, so every PowerShell verdict in the suite was a hand-written
expectation about a language nobody ran. Measured across 2026-08-24/25, **three
of six** guard defects that session were *premise-level* — claims about what
PowerShell does, not about what the code does. No static test can settle a
premise. This file settles them.

WHAT IT MEASURES
----------------
For each generated command, two bits — does a real PowerShell reach the delete,
and do the guards deny it:

    reaches and not denied      -> FAIL-OPEN      (a real protection is missing)
    not reaches and denied      -> FALSE POSITIVE (friction an adopter eats)
    otherwise                   -> agrees

Both directions are reported, and neither is subordinate. Relieving a false
positive and opening a fail-open are the same edit seen from two sides; a gate
that reports only one of them will certify the edit that breaks the other.

THE POPULATION IS DERIVED, NOT LISTED
-------------------------------------
``powershell_guard_rehearsal.py`` states its own limit honestly: *"The rows are
hand-written, so a shape nobody thought of is not covered."* Here the rows are a
cross-product of primitives, and one axis is derived from the guard's **own
source**: :data:`PRECEDING_CHARS` is extracted from the character class inside
``_bash_patterns._PS_CMD_POS_SEP``. Nobody chooses which characters to attack —
the regex chooses, and it keeps choosing after someone edits it.

That axis is not decoration. Measured 2026-08-25: the discriminator for whether
an inert PowerShell string is allowed is **the last non-space character before
the pattern**. A letter allows; ``)``, ``=`` and ``|`` HARD-deny; ``;`` and a
``1)`` list marker soft-deny. Every one of the 19 must-allow rows across
``tests/test_guard_false_positives.py`` and ``powershell_guard_rehearsal.py``
happens to put a letter there, so not one of them can fail on that axis.

⚠ THE LITERAL / EXPANDABLE SPLIT IS LOAD-BEARING. Verified against real pwsh
7.6.5: ``$(...)`` inside ``@"..."@`` or ``"..."`` genuinely EXECUTES, and inside
``@'...'@`` or ``'...'`` genuinely does not. A masking pass that blanket-blanks
an expandable span converts a correct DENY into an ALLOW. This file generates
both halves precisely so a fix cannot relieve the friction without being shown
the fail-open it opens.

GATING
------
Stands down where no PowerShell is installed and says so; fires on the Windows
runner and on any host with ``pwsh`` on PATH. Point it at an unpacked build with
``ESPALIER_PWSH=/path/to/pwsh``.

::

    python3 bench/powershell_reachability_differential.py
    python3 bench/powershell_reachability_differential.py --json
    ESPALIER_PWSH=~/pwsh/pwsh python3 bench/powershell_reachability_differential.py

Exit code: 1 if any FAIL-OPEN, 2 if only FALSE POSITIVEs, 0 if clean, 3 when
the instrument itself is broken (the interpreter or the guard stopped
answering -- never a tree verdict), and 0 with a SKIPPED banner when no
interpreter is present. Stdlib only.

⚠ EACH RUN OWNS ITS INTERPRETER CACHE. pwsh keeps a startup cache in the
user's profile (``~/.cache/powershell/StartupProfileData-NonInteractive``),
and two of these populations running concurrently corrupted it (2026-09-10):
every pwsh after that aborted on load, every later row read as not reaching,
and the run reported no fail-open on a tree with twenty-one. ``main()`` now
gives every spawn a private ``XDG_CACHE_HOME`` for the life of the run, so
there is no shared file to corrupt (POSIX; Windows keeps that cache under
``LOCALAPPDATA`` and is not redirected). The detector stays as the second
layer: ``run()`` retries an execution row that does not reach, re-drives the
bare calibration shape if it still does not, aborts with exit 3 and the
interpreter's stderr when that fails too, and asserts the calibration again
after the last row. If a user's own cache is ever corrupted (pwsh aborts on
"The given assembly name was invalid"), move the file aside; pwsh rebuilds
it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"

sys.path.insert(0, str(HOOKS_DIR))

import _bash_patterns  # noqa: E402  (path is set immediately above)

# Assembled, never spelled literally — this file is scanned by the guards it
# tests. Same construction, same reason, as the two sibling gates.
_RI = "Remove-Item" + " " + "-Recurse" + " " + "-Force"
_TARGET = "__TARGET__"

#: Every head whose operand a row may delete under: the remove verbs, and
#: (DEF-824, DEF-822) the sweep heads -- `find`, whose roots it deletes
#: under, and the enumerators, whose roots a piped remove verb deletes
#: under. The safety assertion below reads all of them BEFORE any sweep row
#: is handed to the interpreter; a head missing here is a root the
#: assertion cannot see.
#: DERIVED from the guard's own rosters (failure-mode review: a hand copy
#: was in sync the day it was written and would have drifted the next time
#: a verb joined `_PS_REMOVE_VERB` -- exactly what DEF-822 did to this
#: family), so a verb added there reaches this assertion the same day.
#: DEF-831: the carrier's head table holds multi-word heads no roster word
#: derives (the version-control listing, composed on the git head with its
#: global-option run), so their spellings join the alternation from the
#: table itself.
_HEADS = (
    r"(?<![\w-])(?:" + _bash_patterns._PS_REMOVE_VERB + r"|find|"
    + _bash_patterns._PS_ENUMERATE_VERB + r"|" + _bash_patterns._PIPED_MULTIWORD_HEADS
    + r")(?![\w-])"
)

#: Operands that must never reach a real interpreter, whatever else went wrong.
_CATASTROPHIC_OPERAND_RE = re.compile(
    _HEADS + r"(?:\s+-\S+)*\s+(?:[A-Za-z]:\\?|/|~|\*)(?=\s|$|['\"])",
    re.IGNORECASE,
)


#: Any delete whose operand is absolute, home-relative, parent-escaping or
#: globbed -- the general form of the four bare shapes above.
_ESCAPING_OPERAND_RE = re.compile(
    _HEADS + r"(?:\s+-\S+)*\s+['\"]?(?:[A-Za-z]:|/|~|\.\.[\\/])",
    re.IGNORECASE,
)


class UnsafeToExecute(RuntimeError):
    """A generated command was not provably confined to the sandbox."""


class InstrumentBroken(RuntimeError):
    """The gate itself is wrong. Never reported as a tree result."""


# ── Interpreter discovery ───────────────────────────────────────────────────


def find_powershell() -> tuple[str, str] | None:
    """Locate a PowerShell, or None. Returns (path, flavour).

    ``ESPALIER_PWSH`` wins so a build unpacked outside PATH can drive this
    without being installed system-wide — which is how it was first run.
    """
    override = os.environ.get("ESPALIER_PWSH")
    if override:
        expanded = Path(override).expanduser()
        if not expanded.exists():
            raise InstrumentBroken(
                f"ESPALIER_PWSH points at a path that does not exist: {expanded}"
            )
        return str(expanded), "pwsh (ESPALIER_PWSH)"
    for exe, flavour in (("pwsh", "pwsh 7+"), ("powershell", "Windows PowerShell 5.1")):
        found = shutil.which(exe)
        if found:
            return found, flavour
    return None


# ── The derived population ──────────────────────────────────────────────────


#: A floor the derived alphabet must clear. HAND-WRITTEN ON PURPOSE, and that is
#: the whole point: a population derived from the constant under test enrols an
#: ADDITION but is structurally blind to a DELETION, and equally blind to a
#: restructure that makes the derivation read the wrong class. This repo has that
#: recorded (`FAILURE_MODES` §18.4) after deleting 10 of 21 members of a
#: `_CMD_POS_WRAPPER` constant opened 10 genuine protected-zone writes with
#: nothing red. What closes it is a floor that does NOT derive from the subject.
_REQUIRED_PRECEDING = frozenset(";|\n\r(){}&")


def _derive_preceding_chars() -> tuple[str, ...]:
    """Pull the command-position character class out of the guard's own regex.

    ⚠ DERIVED ON PURPOSE, AND IT MUST FAIL LOUDLY. §14 — "derive the list, don't
    test a hand-written copy of it". Adding a character to ``_PS_CMD_POS_SEP``
    covers it here on the next run with no edit.

    ⚠ AND THE DERIVATION ALONE IS NOT ENOUGH. ``_PS_CMD_POS_SEP`` contains more
    than one bracket class — the command-position class AND the trailing
    ``[ \t]*`` whitespace run. Taking "the first class" is right today purely by
    ordering: driven at authoring time, a pattern with the command-position class
    removed still yielded a happy match on ``[ \t]``, so the gate would have gone
    on attacking a two-character whitespace alphabet and reported no violations.
    Every class is therefore considered, the one carrying the separators is
    selected by CONTENT rather than position, and the result is checked against
    a floor that does not derive from the subject.
    """
    source = _bash_patterns._PS_CMD_POS_SEP
    candidates = re.findall(r"\[([^\]]*(?:\\.[^\]]*)*)\]", source)
    if not candidates:
        raise InstrumentBroken(
            "no character class in _PS_CMD_POS_SEP -- the instrument is stale: "
            f"{source!r}"
        )

    def unescape(raw: str) -> list[str]:
        out, i = [], 0
        while i < len(raw):
            if raw[i] == "\\" and i + 1 < len(raw):
                out.append({"n": "\n", "r": "\r", "t": "\t"}.get(raw[i + 1], raw[i + 1]))
                i += 2
            else:
                out.append(raw[i])
                i += 1
        return out

    best: list[str] | None = None
    for raw in candidates:
        chars = unescape(raw)
        if ";" in chars and "|" in chars:
            best = chars
            break
    if best is None:
        raise InstrumentBroken(
            "no class in _PS_CMD_POS_SEP carries the statement separators -- the "
            f"derivation would attack the wrong alphabet: {source!r}"
        )

    missing = _REQUIRED_PRECEDING - set(best)
    if missing:
        raise InstrumentBroken(
            f"command-position class lost {sorted(missing)!r} -- either the guard "
            "narrowed (a fail-open worth a human decision) or this derivation is "
            "reading the wrong class. Refusing to report a green either way."
        )
    # `=` is spelled OUTSIDE the class in the same alternation; include it, and
    # append a letter as the CONTROL that must always allow.
    return tuple(best) + ("=", "X")


#: Characters placed immediately before the pattern inside an inert span.
PRECEDING_CHARS: tuple[str, ...] = _derive_preceding_chars()

#: Inert containers, split by whether PowerShell interpolates inside them.
#: The split is measured, not assumed — see the module docstring.
LITERAL_CONTAINERS: tuple[tuple[str, str], ...] = (
    ("here-string-literal", "$doc = @'\n{body}\n'@"),
    ("single-quoted", "$doc = '{body}'"),
    ("block-comment", "<#\n{body}\n#>\nGet-Date"),
    ("line-comment", "# {body}\nGet-Date"),
)

EXPANDABLE_CONTAINERS: tuple[tuple[str, str], ...] = (
    ("here-string-expandable", '$doc = @"\n{body}\n"@'),
    ("double-quoted", '$doc = "{body}"'),
)

#: Execution contexts. Each of these RUNS the command in real PowerShell —
#: verified against pwsh 7.6.5 — so every one must be denied.
EXECUTION_WRAPPERS: tuple[tuple[str, str], ...] = (
    ("bare", "{cmd}"),
    ("assignment", "$x = {cmd}"),
    ("typed-assignment", "[string]$x = {cmd}"),
    ("scoped-assignment", "$script:x = {cmd}"),
    ("global-assignment", "$global:x = {cmd}"),
    ("env-assignment", "$env:SOMETHING = {cmd}"),
    ("plus-equals", "$x = ''; $x += {cmd}"),
    ("chained-assignment", "$a = $b = {cmd}"),
    ("parenthesized", "$x = ({cmd})"),
    ("subexpression", "$x = $({cmd})"),
    ("array-subexpression", "$x = @({cmd})"),
    ("call-operator", "& {{ {cmd} }}"),
    ("semicolon-second", "Get-Date; {cmd}"),
    ("newline-second", "Get-Date\n{cmd}"),
    # ⚠ PowerShell 7's conditional chaining -- the direct analog of the Bash
    # `cd /tmp && ...` shape that produced this repo's worst recorded miss. The
    # LHS is pinned to a command that SUCCEEDS for `&&` and FAILS for `||`, so
    # each row actually reaches the delete instead of short-circuiting away and
    # vouching for nothing. That short-circuit is exactly how four `&&` rows
    # once certified a change that had broken the newline case.
    ("and-chained", "Get-Date > $null && {cmd}"),
    ("or-chained", "Get-Item ./nonexistent-xyz 2>$null || {cmd}"),
    ("pipeline-second", "Get-ChildItem | Out-Null; {cmd}"),
    ("subexpr-in-expandable-string", '$d = "note $({cmd})"'),
    ("subexpr-in-expandable-heredoc", '$d = @"\nnote $({cmd})\n"@'),
    # ⚠ A RE-PARSING WRAPPER AROUND AN EXPANDABLE SPAN (DEF-753). No row above
    # puts a re-parser in front of the span, so this population certified a
    # masker that blanked every expandable span's separators, re-parsed or
    # not -- on DEF-617's finding that `iex "$env:VAR=1; <cmd>"` sets nothing,
    # which is true of the ASSIGNMENT and false of the SEPARATOR. Each row
    # here varies the property the fix changed: the second statement runs
    # behind `;`, behind a pipe, in a here-string, after the backtick
    # newline the outer shell produces, after an interpolated first
    # statement, and inside a nested interpreter (the outer one's own
    # directory is on the child's PATH for that row).
    ("reparsed-expandable-second", 'iex "Get-Date; {cmd}"'),
    ("reparsed-expandable-long-opener", 'Invoke-Expression "Get-Date; {cmd}"'),
    ("reparsed-expandable-pipe-then-second", 'iex "Get-Item ./victim | Out-Null; {cmd}"'),
    ("reparsed-expandable-here-string", 'iex @"\nGet-Date; {cmd}\n"@'),
    ("reparsed-expandable-backtick-newline", 'iex "Get-Date`n{cmd}"'),
    ("reparsed-expandable-interpolated-first", '$x = "Get-Date"; iex "$x; {cmd}"'),
    ("reparsed-expandable-nested-interpreter", '{nested} -NoProfile -Command "Get-Date; {cmd}"'),
    # ⚠ A SCRIPT BLOCK BUILT FROM A STRING (DEF-760). The static `Create`
    # method is a re-parser that is not a word, so no row above put it in
    # front of a span and the roster gap certified. Driven, not assumed: a
    # block created from a string executes when invoked, in both quote kinds
    # and through `Invoke-Command`.
    ("scriptblock-create-invoked", '& ([scriptblock]::Create("Get-Date; {cmd}"))'),
    ("scriptblock-create-literal-invoked", "& ([scriptblock]::Create('Get-Date; {cmd}'))"),
    ("scriptblock-create-icm", 'Invoke-Command -ScriptBlock ([scriptblock]::Create("Get-Date; {cmd}"))'),
)

#: Operand spellings. Held as an axis because the corpus rows that hid the
#: 2026-08-25 defect all used the TARGETLESS spelling.
TARGETS: tuple[tuple[str, str], ...] = (
    ("relative-dot", "./victim"),
    ("relative-backslash", ".\\victim"),
    ("bare-relative", "victim"),
)


#: What sits immediately BEFORE a container's opener. Until 2026-08-25 every
#: roster in this repo pinned the opener at offset 0, so a guard bug in how a
#: span OPENS was invisible to all of them -- only bugs in what precedes the
#: pattern INSIDE the span could register. That blind spot shipped a hard-tier
#: fail-open: a `<#` glued to a bare word does NOT open a block comment in
#: PowerShell (the opener is absorbed into the argument token), but the masker
#: treated it as one and blanked a live `;`.
#:
#: The glued/spaced pair is the discriminator, and the derived alphabet rides
#: along so the axis widens with the guard's own class.
CONTAINER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("start-of-command", ""),
    ("spaced", "Write-Output note "),
    ("glued", "Write-Output note"),
) + tuple((f"after-{c!r}", "Write-Output note" + c) for c in PRECEDING_CHARS)


def opener_context_rows() -> list[dict]:
    """Every container, with its opener pushed off offset 0.

    Body held FIXED at the bare pattern on purpose: this axis is about the
    opener, and crossing it with the body axis would multiply the population
    without testing anything the body axis does not already cover.
    """
    rows = []
    for containers, literal in ((LITERAL_CONTAINERS, True),
                                (EXPANDABLE_CONTAINERS, False)):
        for cname, template in containers:
            for pname, prefix in CONTAINER_PREFIXES:
                rows.append({
                    "kind": "inert",
                    "container": cname + " @" + pname,
                    "literal": literal,
                    "preceding": pname,
                    "template": prefix + template.format(
                        body="; " + _RI + " " + _TARGET),
                })
    return rows


def inert_rows() -> list[dict]:
    """Rows that must NOT execute: the pattern held inside an inert span."""
    rows = []
    for containers, literal in ((LITERAL_CONTAINERS, True),
                                (EXPANDABLE_CONTAINERS, False)):
        for cname, template in containers:
            for char in PRECEDING_CHARS:
                # A newline before the pattern inside a single-line container is
                # not that container any more; skip rather than mislabel.
                if char in "\n\r" and "\\n" not in template and "\n" not in template:
                    continue
                body = f"note{char} {_RI} {_TARGET}"
                rows.append({
                    "kind": "inert",
                    "container": cname,
                    "literal": literal,
                    "preceding": repr(char),
                    "template": template.format(body=body),
                })
    return rows


#: DEF-753's inert side, hand-held because it is not a container: the one
#: character the re-parsed mode still blanks is the `=` bound to an
#: interpolated token, and no generated row spells that. Measured against pwsh
#: 7.6.5: with the variable unset the re-parser receives `=<delete>` as one
#: unknown command name and the delete is its argument, never run.
REPARSED_INERT_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("reparsed-expandable-assignment-rhs", 'iex "$x={cmd}"'),
    ("reparsed-expandable-env-assignment-rhs", 'iex "$env:ESPALIER_DIFF_UNSET={cmd}"'),
)


def reparsed_inert_rows() -> list[dict]:
    """Rows that must NOT execute: a delete as the right-hand side of an
    assignment whose left side the outer shell interpolates away."""
    return [
        {
            "kind": "inert",
            "container": name,
            "literal": False,
            "preceding": "'='",
            "template": template.format(cmd=f"{_RI} {_TARGET}"),
        }
        for name, template in REPARSED_INERT_TEMPLATES
    ]


#: The call operator with a quoted command name (DEF-791): ordinary
#: PowerShell, and the one spelling where a quote opens a command position.
#: Each execution wrapper is a real delete a real interpreter runs; the inert
#: templates hold the same text as data. Held apart from
#: :data:`EXECUTION_WRAPPERS` because those wrap a fixed verb spelling; this
#: axis varies the verb's own spelling.
CALL_OPERATOR_WRAPPERS: tuple[tuple[str, str], ...] = (
    ("call-operator-quoted-verb", "& 'Remove-Item' -Recurse -Force {target}"),
    ("call-operator-double-quoted-verb", '& "Remove-Item" -Recurse -Force {target}'),
    ("call-operator-quoted-alias", "& 'ri' -Recurse -Force {target}"),
    ("assignment-of-call-operator", "$x = & 'Remove-Item' -Recurse -Force {target}"),
    ("semicolon-then-call-operator", "Get-Date; & 'Remove-Item' -Recurse -Force {target}"),
)
CALL_OPERATOR_INERT: tuple[tuple[str, bool, str], ...] = (
    ("call-operator-in-single-quoted-string", True,
     "Write-Output '& \"Remove-Item\" -Recurse -Force {target}'"),
    ("call-operator-in-expandable-string", False,
     "Write-Output \"& 'Remove-Item' -Recurse -Force {target}\""),
)


def call_operator_rows() -> list[dict]:
    """Rows that MUST execute: the delete verb quoted behind the call
    operator (DEF-791), in each target spelling."""
    return [
        {
            "kind": "execution",
            "wrapper": wname,
            "target": tname,
            "template": wtemplate.format(target=target),
        }
        for wname, wtemplate in CALL_OPERATOR_WRAPPERS
        for tname, target in TARGETS
    ]


def call_operator_inert_rows() -> list[dict]:
    """Rows that must NOT execute: the quoted-verb spelling held as data."""
    return [
        {
            "kind": "inert",
            "container": name,
            "literal": literal,
            "preceding": "'&'",
            "template": template.format(target=_TARGET),
        }
        for name, literal, template in CALL_OPERATOR_INERT
    ]


_PLATFORM = "nt" if os.name == "nt" else "posix"

#: The sweeps this tool runs that spell the recursive force-delete (DEF-824,
#: DEF-822, and the native-rm sibling filed from the lane's own drive): each
#: MUST reach on the platform it is listed for, and the guard must deny it --
#: the relative victim is the soft tier's one nudge, so ``SOFT`` agrees.
#: ``(name, template, oracle, platforms)``. The oracle is `_run_pwsh`'s:
#: ``victim`` for a shape that removes the root, ``canary`` for a pipeline,
#: which removes the root's children. ``posix`` rows name /bin/rm and
#: /usr/bin/find, which pwsh resolves only on macOS and Linux (its alias
#: table is per platform: `rm` is Remove-Item on Windows, where `find.exe`
#: has no delete action); the rm-alias pipeline reaches on Windows alone.
#: Verified against pwsh 7.6.5 on macOS, 2026-09-16.
SWEEP_COMMANDS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("find-bare", "find " + _TARGET + " -delete", "victim", ("posix",)),
    # ⚠ THE BRACES ARE QUOTED, and the reason is a premise this gate settled
    # on its first run: a bare `{}` is a SCRIPT BLOCK to PowerShell, so
    # `find . -exec rm -rf {} +` as typed hands find no placeholder and is
    # inert (8 rows read as not reaching, 2026-09-16); `'{}'` is the spelling
    # that runs. The guard reads both alike, toward refusal.
    ("find-exec-rm", "find " + _TARGET + " -exec rm -rf '{}' +", "victim", ("posix",)),
    ("find-type-f", "find " + _TARGET + " -type f -delete", "canary", ("posix",)),
    ("find-call-operator", "& 'find' " + _TARGET + " -delete", "victim", ("posix",)),
    ("pipeline-recurse-both", "gci " + _TARGET + " -Recurse | ri -r -fo", "canary", ("posix", "nt")),
    ("pipeline-recurse-remove-only", "gci " + _TARGET + " | ri -r -fo", "canary", ("posix", "nt")),
    ("pipeline-files-only", "gci " + _TARGET + " -Recurse -File | ri", "canary", ("posix", "nt")),
    ("pipeline-spelled-out",
     "Get-ChildItem " + _TARGET + " -Recurse | Remove-Item -Recurse -Force", "canary", ("posix", "nt")),
    # the review batch: a pipe continues across a line break; a catch-all
    # filter value narrows nothing; -Attributes !Directory is files-only in
    # its other spelling; a recursive enumeration into a plain remove
    # deletes everything up to the first directory with children (the
    # victim holds one file, so it goes -- the guard's one nudge agrees)
    ("pipeline-newline-after-pipe", "gci " + _TARGET + " -Recurse -File |\nri", "canary", ("posix", "nt")),
    ("pipeline-catchall-include",
     "gci " + _TARGET + " -Recurse -Include * | ri -r -fo", "canary", ("posix", "nt")),
    ("pipeline-attributes-no-directory",
     "gci " + _TARGET + " -Recurse -Attributes !Directory | ri", "canary", ("posix", "nt")),
    ("pipeline-plain-remove", "gci " + _TARGET + " -Recurse | ri -fo", "canary", ("posix", "nt")),
    # UNDRIVEN -- nt only, and no Windows walk has run this population as of
    # 2026-09-16: the alias table says `rm` is Remove-Item there, and a false
    # MUST-reach reds loudly on the first Windows run.
    ("pipeline-rm-alias", "gci " + _TARGET + " -Recurse | rm -r -fo", "canary", ("nt",)),
    ("cmdlet-abbreviated", "ri -r -fo " + _TARGET, "victim", ("posix", "nt")),
    ("cmdlet-long-prefix", "Remove-Item -rec -forc " + _TARGET, "victim", ("posix", "nt")),
    ("native-rm-cluster", "rm -rf " + _TARGET, "victim", ("posix",)),
    ("native-rm-split", "rm -r -f " + _TARGET, "victim", ("posix",)),
    # THE CARRIER (DEF-826): an enumerator piped through xargs into the native
    # rm, on a POSIX host where pwsh resolves find, ls, xargs and rm to the
    # binaries. A find head lists its root first, so the victim goes and the
    # victim oracle reads it; a listing prints names relative to the current
    # location, so its row moves into the target and the canary reads it; the
    # cmdlet enumerator's names reach the native rm the same way (driven on
    # pwsh 7.6.5 before the lane: every one emptied a throwaway).
    ("carrier-find-print0", "find " + _TARGET + " -print0 | xargs -0 rm -rf", "victim", ("posix",)),
    ("carrier-find-plain", "find " + _TARGET + " | xargs rm -rf", "victim", ("posix",)),
    ("carrier-find-files-only", "find " + _TARGET + " -type f | xargs rm", "canary", ("posix",)),
    # (the catch-all name value is pinned by the rehearsal and the unit
    # matrix; this gate's safety assertion reads a bare `*` as a delete
    # operand wherever it sits, so the row is not listed here)
    ("carrier-listing-in-target", "Set-Location " + _TARGET + "; ls | xargs rm -rf", "canary", ("posix",)),
    ("carrier-cmdlet-names", "Set-Location " + _TARGET + "; gci -Recurse -Name | xargs rm -rf", "canary", ("posix",)),
    # DEF-831: the version-control listing prints names relative to the
    # current location, so its rows move into the target, set the repository
    # up inside it (the listing walks the index, so a staged canary is listed
    # with no commit) and the canary reads them -- through the carrier on a
    # POSIX host, and straight into the cmdlet on every host (the cmdlet binds
    # a path from the pipeline by value; driven on pwsh 7.6.5)
    ("carrier-tracked-listing-in-target",
     "Set-Location " + _TARGET + "; git init -q; git add -A; git ls-files | xargs rm -rf",
     "canary", ("posix",)),
    ("cmdlet-tracked-listing-in-target",
     "Set-Location " + _TARGET + "; git init -q; git add -A; git ls-files | Remove-Item",
     "canary", ("posix", "nt")),
)

#: The execution wrappers a sweep row rides in: the bare position, an
#: assignment (which INVOKES), a second statement, PowerShell 7's chain.
_SWEEP_WRAPPERS = ("bare", "assignment", "semicolon-second", "and-chained")


def sweep_rows(*, nested: str) -> list[dict]:
    """Rows that MUST execute (DEF-824, DEF-822): the sweeps, on this
    platform, in the wrappers above, on the two target spellings a native
    binary reads (`find .\\victim` is "No such file" to find on a POSIX host
    -- driven -- so the backslash spelling stays with the cmdlet rows)."""
    wrappers = dict(EXECUTION_WRAPPERS)
    return [
        {
            "kind": "execution",
            "wrapper": f"sweep:{cname}:{wname}",
            "target": tname,
            "oracle": oracle,
            "template": wrappers[wname].format(cmd=ctemplate, nested=nested).replace(_TARGET, target),
        }
        for cname, ctemplate, oracle, platforms in SWEEP_COMMANDS
        if _PLATFORM in platforms
        for wname in _SWEEP_WRAPPERS
        for tname, target in TARGETS
        if tname != "relative-backslash"
    ]


def execution_rows(*, nested: str) -> list[dict]:
    """Rows that MUST execute: the pattern in a genuine command position.

    ``nested`` is the head the nested-interpreter wrapper spells -- the
    running interpreter's own name (``pwsh`` or ``powershell``), so the row
    resolves on a host that ships only one of them. Required, keyword-only:
    a caller that forgot it would build a row whose head may not resolve and
    read the result as the tree's.
    """
    return [
        {
            "kind": "execution",
            "wrapper": wname,
            "target": tname,
            "template": wtemplate.format(
                cmd=f"{_RI} {_TARGET}", nested=nested,
            ).replace(_TARGET, target),
        }
        for wname, wtemplate in EXECUTION_WRAPPERS
        for tname, target in TARGETS
    ]


# ── Oracles ─────────────────────────────────────────────────────────────────


RI_VERB = "Remove-Item"

#: The delete verbs PowerShell accepts, including its default aliases, and
#: (DEF-824, DEF-822) the sweep heads whose roots a delete runs under: every
#: operand of every one of them is judged by the assertion below.
_PS_DELETE_VERBS = frozenset(
    w.lower() for w in re.findall(
        r"[\w-]+", _bash_patterns._PS_REMOVE_VERB + _bash_patterns._PS_ENUMERATE_VERB)
) | {"find"} | frozenset(
    # DEF-831: every word of the carrier's head keys, so the operands behind
    # a multi-word head (the version-control listing's pathspecs and its
    # explicit-repo value) are judged too
    w.lower() for w in re.findall(r"[\w-]+", " ".join(_bash_patterns._PIPED_ENUM_HEAD_KEYS))
)

#: A colon-bound parameter value (`-Path:/`, `-LiteralPath:~`): the guard's
#: own reader binds it, so the assertion must read it as the operand it is
#: (code review: two rows spelled this way would have executed).
_COLON_BOUND_RE = re.compile(r"^-[A-Za-z]+:(.+)$")

#: The enumerator's PATTERN-valued parameters: their value is a wildcard or a
#: number, never a root, so it is the one flag value the over-collection
#: below does not read (`-Include *` would otherwise refuse the catch-all
#: sweep row as a bare-glob delete). Every other flag's value is still
#: collected, and a root behind one of these is still read.
_ENUM_PATTERN_FLAGS = frozenset({"-include", "-filter", "-exclude", "-attributes", "-depth"})

#: Tokens that end a delete's operand list.
_PS_OPERAND_STOP = frozenset({";", "|", "&", "(", ")", "{", "}", "&&", "||"})


def _delete_operands(cmd: str) -> list[str]:
    """Every operand of every delete invocation in `cmd`.

    ⚠ THE FIRST OPERAND IS NOT THE ONLY OPERAND, and this is the twin of the same
    hole on the Bash leg. Both :data:`_CATASTROPHIC_OPERAND_RE` and
    :data:`_ESCAPING_OPERAND_RE` anchor on the verb plus ONE operand, so a second
    operand riding behind a declared one matched neither and was ACCEPTED.
    ``Remove-Item``'s positional ``-Path`` is ``string[]``, so PowerShell binds
    every one of them -- the extra operand is not decoration, it is a second
    delete. Found 2026-08-25 by the suite wrapper.

    Operands may also arrive comma-joined (``-Path a,b``), which is why each token
    is split on commas before it is judged. A command that cannot be lexed RAISES:
    a string this function cannot read is a string it must not vouch for.

    ⚠ DELIBERATELY OVER-COLLECTS. ``shlex`` knows nothing about PowerShell's
    ``<# #>`` block comments or its statement-ending newlines, so a trailing
    statement can land in this list. That is why the CALLER judges each operand
    with the catastrophic/escaping predicates rather than demanding a declared
    spelling: requiring the latter refused 43 well-formed rows whose delete sits
    inside a block comment. Over-collecting is safe here precisely because the
    test applied to each item is about danger, not about provenance.
    """
    lexer = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise UnsafeToExecute(
            f"cannot lex {cmd!r} to check its delete operands: {exc}") from None

    operands: list[str] = []
    i = 0
    while i < len(tokens):
        if tokens[i].lower() not in _PS_DELETE_VERBS:
            i += 1
            continue
        i += 1
        while i < len(tokens):
            tok = tokens[i]
            if tok in _PS_OPERAND_STOP:
                break
            low = tok.lower()
            if low in _ENUM_PATTERN_FLAGS:
                i += 2                    # the flag and its pattern value
                continue
            bound = _COLON_BOUND_RE.match(tok)
            if bound:
                if low.split(":", 1)[0] not in _ENUM_PATTERN_FLAGS:
                    operands.extend(part for part in bound.group(1).split(",") if part)
            elif not tok.startswith("-"):
                operands.extend(part for part in tok.split(",") if part)
            i += 1
    return operands


def assert_safe_to_execute(cmd: str, victim: Path, sandbox: Path) -> None:
    """Refuse to hand `cmd` to a real interpreter unless confined to `sandbox`.

    ⚠ THIS FUNCTION IS THE REASON THIS SCRIPT IS SAFE TO RUN. Everything below
    executes genuine recursive deletes. Four independent conditions, each fatal,
    mirroring the Bash sibling:

    1. the placeholder is gone (substitution happened at all)
    2. the victim path is present (it was substituted with the RIGHT thing)
    3. the victim really is inside the sandbox
    4. no delete in the final string takes a drive root, ``/``, ``~`` or a bare
       glob as operand

    (4) is the belt to (1)-(3)'s braces: it does not care HOW a catastrophic
    operand got there, only that one is present.
    """
    if _TARGET in cmd:
        raise UnsafeToExecute(f"placeholder never substituted: {cmd!r}")
    # ⚠ The rows deliberately use RELATIVE operands (the guard's operand parser
    # tiers on exactly that), so the Bash sibling's "absolute sandbox path must
    # appear" check cannot be reused verbatim -- it would reject every row. What
    # replaces it must not degrade to "the word victim appears somewhere": that
    # accepts the name as unrelated prose. Require one of the EXACT declared
    # spellings, and pair it with condition 5 below, which rejects any delete
    # operand that escapes the working directory however it got there.
    if not any(f" {spelling}" in cmd for _, spelling in TARGETS):
        raise UnsafeToExecute(
            f"no declared sandbox operand ({[t for _, t in TARGETS]}) in: {cmd!r}")
    try:
        victim.resolve().relative_to(sandbox.resolve())
    except ValueError:
        raise UnsafeToExecute(
            f"victim {victim} is outside sandbox {sandbox}") from None
    hit = _CATASTROPHIC_OPERAND_RE.search(cmd)
    if hit:
        raise UnsafeToExecute(
            f"refusing to execute a catastrophic operand {hit.group(0)!r}: {cmd!r}")
    # (5) ANY delete operand that is not plainly relative. The catastrophic
    # regex above only catches the four bare forms (`/`, `~`, a drive root, a
    # bare glob); it says nothing about `C:\Users\...` or `~/Documents`. This
    # is the general backstop, and it is what lets condition 2 stay narrow.
    escaped = _ESCAPING_OPERAND_RE.search(cmd)
    if escaped:
        raise UnsafeToExecute(
            f"delete operand escapes the sandbox {escaped.group(0)!r}: {cmd!r}")


    # (6) EVERY operand, not just the first. Conditions 2-5 all anchor on the verb
    # plus ONE operand, so a second operand riding behind a declared one was
    # invisible to every one of them -- and PowerShell's positional -Path is
    # string[], so it really does bind and really does delete.
    #
    # Each operand is re-tested with THIS FILE'S OWN predicates by synthesising a
    # single-operand delete around it. Reusing them keeps one definition of
    # "catastrophic" rather than growing a second that can drift.
    for operand in _delete_operands(cmd):
        probe = f"{RI_VERB} -Recurse -Force {operand}"
        if _CATASTROPHIC_OPERAND_RE.search(probe):
            raise UnsafeToExecute(
                f"catastrophic delete operand {operand!r} behind a valid one: "
                f"{cmd!r}")
        if _ESCAPING_OPERAND_RE.search(probe):
            raise UnsafeToExecute(
                f"escaping delete operand {operand!r} behind a valid one: "
                f"{cmd!r}")


#: Set by ``main()`` for the life of one run: a private cache directory for
#: the interpreter, so two runs can never share the startup cache that
#: concurrent runs corrupted on 2026-09-10 (see the module docstring). None
#: means the user's own cache -- a direct call from a test or a REPL.
_RUN_CACHE_DIR: str | None = None


def _child_env(pwsh: str, sandbox: Path | None = None) -> dict[str, str]:
    """The environment every interpreter spawn in this gate gets.

    The interpreter's own directory goes first on PATH -- applied to every
    row (the prepend is harmless for the rest) so the one row that nests a
    `pwsh -Command` resolves the build the outer one is; an unpacked build
    under ``ESPALIER_PWSH`` is off PATH by definition. And when a run owns a
    cache directory, ``XDG_CACHE_HOME`` points there: pwsh on POSIX keeps its
    startup cache under it (measured: the run's directory gained
    ``powershell/StartupProfileData-NonInteractive`` and the user's own cache
    was untouched), so no second process can corrupt this run's cache or be
    corrupted by it. Windows PowerShell keeps that cache under
    ``LOCALAPPDATA``, which this does not redirect; there the detector in
    ``run()`` is the guard.

    The git belt (DEF-831, the Bash differential's ``_sandbox_env`` brought
    over the day the first rows here ran git inside the sandbox): every
    inherited ``GIT_*`` variable is dropped and a ceiling is set above
    ``sandbox`` when one is given, so a row's ``git add`` can neither be
    routed into the operator's index by an inherited ``GIT_DIR`` /
    ``GIT_WORK_TREE`` (set by any hook, ``rebase --exec``, ``bisect run``)
    nor discover a checkout above a temp root that sits inside one; global
    and system config are off so no alias, template or hook of the
    operator's reaches in; no terminal prompt.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PATH"] = str(Path(pwsh).parent) + os.pathsep + env.get("PATH", "")
    if _RUN_CACHE_DIR is not None and os.name != "nt":
        env["XDG_CACHE_HOME"] = _RUN_CACHE_DIR
    if sandbox is not None:
        env["GIT_CEILING_DIRECTORIES"] = str(sandbox.resolve().parent)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run_pwsh(template: str, pwsh: str, oracle: str = "victim") -> tuple[bool, int | None, str]:
    """One row through a real PowerShell: ``(reached, returncode, stderr
    tail)``. ``returncode`` is ``None`` on the 30 s timeout. ``oracle``
    names what "reached" means: ``victim``, the victim directory is gone;
    ``canary``, the file inside it is -- an enumerator pipeline removes a
    root's CHILDREN and leaves the root standing (driven 2026-09-16: `gci
    ./v -Recurse | ri -r -fo` left `v` empty), so the victim oracle would
    read every such wipe as not reaching."""
    with tempfile.TemporaryDirectory() as sandbox_str:
        sandbox = Path(sandbox_str)
        victim = sandbox / "victim"
        victim.mkdir()
        canary = victim / "canary"
        canary.write_text("x", encoding="utf-8")
        cmd = template.replace(_TARGET, "./victim")
        assert_safe_to_execute(cmd, victim, sandbox)
        try:
            proc = subprocess.run(
                [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", cmd],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, cwd=str(sandbox), env=_child_env(pwsh, sandbox),
            )
        except (subprocess.TimeoutExpired, ValueError):
            return False, None, "timed out after 30s"
        gone = not canary.exists() if oracle == "canary" else not victim.exists()
        return gone, proc.returncode, (proc.stderr or "")[-300:]


def powershell_reaches(template: str, pwsh: str) -> bool:
    """Did a real PowerShell actually delete the victim? The oracle."""
    return _run_pwsh(template, pwsh)[0]


def guard_tier(command: str) -> str:
    """ALLOW / SOFT / HARD, by driving the real hook twice in one project.

    Reads the DECISION CHANNEL, and treats rc=1 as the script error it is —
    an earlier probe in this class counted rc=1 (an ImportError) as ALLOW and
    reported that HEAD permitted a catastrophic delete.
    """
    with tempfile.TemporaryDirectory() as td:
        project = Path(td)
        (project / ".claude").mkdir()

        def once() -> bool:
            env = os.environ.copy()
            env["CLAUDE_PROJECT_DIR"] = str(project)
            env.pop("ESPALIER_MAINTENANCE_MODE", None)
            proc = subprocess.run(
                [sys.executable, str(HOOKS_DIR / "write_guard.py")],
                input=json.dumps(
                    {"tool_name": "PowerShell", "tool_input": {"command": command}}),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, env=env,
            )
            if proc.returncode == 1 or "Traceback" in (proc.stderr or ""):
                raise InstrumentBroken(
                    "write_guard errored -- the instrument is broken, not the "
                    "tree:\n" + (proc.stderr or "")[:600])
            return '"deny"' in (proc.stdout or "") or proc.returncode == 2

        if not once():
            return "ALLOW"
        return "SOFT" if not once() else "HARD"


def assert_instrument_is_live(pwsh: str) -> None:
    """Both oracles calibrated before any row is believed.

    A guard that denies nothing scores a comforting zero on every row, and an
    interpreter that runs nothing reports every shape inert. The differential's
    own history is the argument: a baseline whose guard died on import wrote
    nothing to stdout, every row read as ALLOW, and the run reported 0
    fail-opens while 63 were live.
    """
    if guard_tier(f"{_RI} C:\\") == "ALLOW":
        raise InstrumentBroken("guard allows a drive-root delete -- instrument broken")
    if guard_tier("Get-Date") != "ALLOW":
        raise InstrumentBroken("guard denies `Get-Date` -- instrument broken")
    if not powershell_reaches(f"{_RI} {_TARGET}", pwsh):
        raise InstrumentBroken(
            "a bare delete did not remove the victim -- the interpreter oracle is "
            "broken, and every row would report inert")
    if powershell_reaches(f"$d = '{_RI} {_TARGET}'", pwsh):
        raise InstrumentBroken(
            "a quoted mention deleted the victim -- the interpreter oracle is broken")
    # DEF-831: the listing rows set a repository up inside the sandbox, a
    # second prerequisite the retry net cannot see -- with git off the
    # child PATH the setup fails silently, the canary survives and a landed
    # wall reads as a false positive (the failure-mode review). The
    # instrument, not the tree.
    if any("git init" in template for _id, template, _oracle, _platforms in SWEEP_COMMANDS):
        if shutil.which("git", path=_child_env(pwsh)["PATH"]) is None:
            raise InstrumentBroken(
                "git is not on the interpreter's PATH and the listing rows need it -- "
                "instrument broken (every such row would report inert)")


# ── Classification ──────────────────────────────────────────────────────────

FAIL_OPEN = "fail_open"
FALSE_POSITIVE = "false_positive"
AGREES = "agrees"


def classify(reaches: bool, tier: str) -> str:
    if reaches and tier == "ALLOW":
        return FAIL_OPEN
    if not reaches and tier != "ALLOW":
        return FALSE_POSITIVE
    return AGREES


def run(pwsh: str, quick: bool = False) -> list[dict]:
    rows = (inert_rows() + opener_context_rows() + reparsed_inert_rows()
            + call_operator_inert_rows()
            + execution_rows(nested=Path(pwsh).stem) + call_operator_rows()
            + sweep_rows(nested=Path(pwsh).stem))
    if quick:
        rows = rows[::3]
    out = []
    for row in rows:
        reaches, rc, tail = _run_pwsh(row["template"], pwsh, row.get("oracle", "victim"))
        if row["kind"] == "execution" and not reaches:
            # ⚠ AN EXECUTION ROW THAT DOES NOT REACH IS SUSPECT, AND THE
            # SUSPECT IS THE INSTRUMENT BEFORE THE TREE. Measured 2026-09-10:
            # two instances of this script running at once corrupted pwsh's
            # startup cache (~/.cache/powershell/StartupProfileData-
            # NonInteractive); every pwsh after that aborted on load, every
            # later row read `reaches=False`, and an ALLOWED execution row
            # therefore classified as AGREES -- the run reported FAIL-OPEN: 0
            # on a tree that had 21 real ones. The start-up calibration cannot
            # see a death mid-run, so the row is retried once (a slow start on
            # a loaded box is not a dead interpreter -- review) and, if it
            # still does not reach, the bare calibration shape is driven
            # again: a dead interpreter fails that too and the run is aborted
            # with the evidence; a live one means THIS ROW does not execute on
            # this flavour (the `&&` / `||` wrappers are PowerShell 7 syntax
            # and a parse error on Windows PowerShell 5.1 -- review) and it is
            # classified like any other row, as the friction it reads as.
            reaches, rc, tail = _run_pwsh(row["template"], pwsh, row.get("oracle", "victim"))
            if not reaches and not powershell_reaches(f"{_RI} {_TARGET}", pwsh):
                raise InstrumentBroken(
                    "the bare delete stopped reaching after execution row "
                    f"{row['wrapper']!r} ({row['target']}) read as not reaching "
                    f"(rc={rc}, stderr tail: {tail.strip()[-200:]!r}) -- the "
                    "interpreter died mid-run; no verdict from this run is "
                    "trustworthy. If pwsh aborts with 'The given assembly name "
                    "was invalid', move ~/.cache/powershell/StartupProfileData-"
                    "NonInteractive aside (it is rebuilt) and run ONE instance.")
        cmd = row["template"].replace(_TARGET, "./victim")
        tier = guard_tier(cmd)
        out.append({**row, "reaches": reaches, "tier": tier,
                    "verdict": classify(reaches, tier)})
    # A death during the inert rows -- the first 148 -- reads as agreement on
    # every one of them (they are not supposed to reach), so the calibration
    # is asserted again at the end: a corrupted cache persists, and this catches
    # it whichever row it happened on.
    assert_instrument_is_live(pwsh)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--quick", action="store_true", help="sampled population")
    args = parser.parse_args(argv)

    found = find_powershell()
    if found is None:
        msg = ("SKIPPED -- no PowerShell on this host. Install `pwsh`, or point "
               "ESPALIER_PWSH at an unpacked build. This gate stands down rather "
               "than reporting a green it did not earn.")
        print(json.dumps({"skipped": True, "reason": msg}) if args.json else msg)
        return 0
    pwsh, flavour = found

    global _RUN_CACHE_DIR
    with tempfile.TemporaryDirectory(prefix="espalier-pwsh-cache-") as cache_dir:
        _RUN_CACHE_DIR = cache_dir
        try:
            assert_instrument_is_live(pwsh)
            results = run(pwsh, args.quick)
        except InstrumentBroken as exc:
            # Never a tree verdict: exit 3, distinct from FAIL-OPEN (1) and
            # FALSE POSITIVE (2), so a CI consumer keying on the code cannot
            # read a broken oracle as a false allow (review).
            print(f"INSTRUMENT BROKEN -- no verdict: {exc}", file=sys.stderr)
            return 3
        finally:
            _RUN_CACHE_DIR = None

    fail_open = [r for r in results if r["verdict"] == FAIL_OPEN]
    false_pos = [r for r in results if r["verdict"] == FALSE_POSITIVE]

    if args.json:
        print(json.dumps({"interpreter": flavour, "rows": results}, indent=2))
    else:
        print(f"interpreter: {flavour} ({pwsh})")
        print(f"population:  {len(results)} rows "
              f"({sum(1 for r in results if r['reaches'])} reach the delete)\n")
        for label, group in (("FAIL-OPEN", fail_open), ("FALSE POSITIVE", false_pos)):
            print(f"{label}: {len(group)}")
            for r in group:
                what = r.get("wrapper") or f"{r['container']} preceded by {r['preceding']}"
                print(f"  {what:<52} reaches={r['reaches']!s:<5} tier={r['tier']}")
            print()
        print(f"agrees: {sum(1 for r in results if r['verdict'] == AGREES)}/{len(results)}")

    if fail_open:
        return 1
    return 2 if false_pos else 0


if __name__ == "__main__":
    raise SystemExit(main())
