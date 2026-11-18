#!/usr/bin/env python3
"""Metamorphic guard gate: relations over a derived population, not expected values.

The third sibling of ``run_benchmark.py`` (curated corpus) and
``reachability_differential.py`` (generated population, real-shell oracle). This
one asserts **relations** — properties that must hold across a transformation —
so the author never has to predict which combination breaks.

WHY THIS EXISTS
---------------
Measured across 2026-08-24/25, the suite caught eight guard defects and missed
six, and the split was structural rather than sloppy:

* **Caught** — contracts that DERIVE their own population and assert an
  invariant over it. They fire on subjects the author never enumerated.
* **Missed** — example-based tests over hand-written rosters. All six misses
  were shapes absent from a roster written by the same person who wrote the code.

``reachability_differential.py`` already names its own residue: *"the blind spot
moved up a level, it did not vanish — WRAPPERS and BODIES are still
hand-written."* The worst miss of that week was a missing **combination**, not a
missing row: a ``cd`` wrapper was added in four spellings, all using ``&&``.
``&&`` re-arms head capture; a newline did not. The oracle written to prove the
change safe certified the safe variant of the shape the change had broken, and a
real shell went on to delete a victim directory, overwrite a guard file, and
write ``disableAllHooks`` into settings — with the full suite, the release
benchmark and the differential all green.

⚠ MEASURED, AND THE REASON ``&&`` COULD NOT FAIL: driven here at authoring time,
``&&`` reaches the delete in **2 of 10** prefix cases while ``;`` and a newline
reach **10 of 10**. ``&&`` short-circuits whenever the prefix exits non-zero, so
most ``&&`` rows never execute the delete at all and vouch for nothing. That is
not a property anyone chose — it is a property of the separator, and it is why
:data:`SEPARATORS` is a derived axis here rather than an author's pick.

WHAT A RELATION BUYS
--------------------
An expected-value row says *"this command must deny"* and can only fail where its
author already suspected trouble. A relation says *"this transformation must not
change the verdict"* and fails wherever the transformation is mishandled —
including where nobody looked.

Two relations, deliberately of opposite polarity, because relieving a false
positive and opening a fail-open are the same edit seen from two sides:

``R1`` — **Bash prefix invariance (must-deny).** For any head ``P`` drawn from
``_bash_patterns._NON_REPARSING_HEADS`` and any separator ``S``, if a real shell
still reaches the delete in ``P S C``, the guards must still deny it. Prefixing
an inert command must not disarm the guard.

``R2`` — **PowerShell inert-span invariance (must-allow).** Inside a string
literal or a comment, moving a prose word before or after the pattern cannot
change PowerShell's semantics, so it must not change the guard's verdict either.

``R2`` needs **no oracle at all** — it compares the guard against itself across a
transformation that is semantically null by construction. That makes it the
cheapest relation in this file and the one most likely to survive a refactor of
everything around it.

``R3`` — **a finished heredoc body is inert** whatever follows its terminator
(must-allow), with a heredoc fed to a re-parsing shell kept denied (must-deny).

``R4`` — **a stderr redirect among the operands (must-deny).** Each denied row of
``tests/test_write_guard.py::TestRemovedOrRelocatedOperandIsAMutation`` stays
denied, and each wall row of ``TestCatastrophicFindDelete`` stays walled, with
a stderr redirect (the file spelling and the merge, ``2>&1``) written at any
blank between its tokens after the command word, or on Bash before it. On
Bash each row is also laid inside each carrier the redirect view reads one
level down (a shell's ``-c`` word, ``eval``'s word, a double-quoted command
substitution's body: ``R4_CARRIERS``), and the places inside the carried
program are offered too, within the view's stated reach (``R4_REACH``; a row
outside it is counted apart, DEF-5126). Each
tool's own parser is the oracle that a place is null for what the verb is
handed (no row is executed), and the classes' own judges give the verdict, so
a reader that takes an operand by its place and loses it to the redirect reds
here without anyone naming it (DEF-5120, DEF-5122; the job DEF-5107, DEF-5108,
DEF-2088 and DEF-2087 fixed one reader set at a time). A red names its next
step (``R4_REMEDY``): see that the hard check the row reaches reads the
command with its error-stream redirects blanked, then put the reader that
takes the operand by its place on the redirect view, or, where the coverage
contract gives the row's job to the after-check, take it to the dispatcher
for the sort.

RUNNING IT
----------
::

    python3 bench/guard_metamorphic.py            # every relation
    python3 bench/guard_metamorphic.py --relation R4   # one of them
    python3 bench/guard_metamorphic.py --quick    # a sampled population, for CI
    python3 bench/guard_metamorphic.py --json     # machine-readable

Exit code is 1 when any relation is violated OR a separator's rows never reach
the delete, 0 otherwise. ``bench/`` is not collected by pytest
(``testpaths = ["tests"]``), so the suite reaches this gate through
:mod:`tests.test_guard_metamorphic`, which pins its liveness machinery and drives
``--quick`` end to end.

⚠ HISTORICAL, and left here because it dates the wrapper: this gate earned its red
on the tree it landed on (10 violations, exit 1), so no wrapper could be landed
until the class it reports was fixed. That class closed in ``8c61431`` and the
wrapper followed. If you are reading this line as a reason not to wrap something,
re-drive the gate first — the precondition it describes is spent.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"


def _bounded_spawn():
    """``run_bounded`` from this checkout's ``tools/cc/_json_safe.py``, loaded
    by path, never an installed engine's: ``subprocess.run`` whose timeout
    holds on Windows, where ``run`` waits on a grandchild holding its pipe
    (DEF-3004)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_json_safe_for_guard_metamorphic", REPO_ROOT / "tools" / "cc" / "_json_safe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_bounded


run_bounded = _bounded_spawn()

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HOOKS_DIR))

import _bash_patterns  # noqa: E402  (path is set immediately above)

# The project fixture is the rehearsal's (DEF-811). Same directory, so the
# import needs no package, and a second builder here would drift from the
# first the day one of them learned a new root shape or protected directory.
# The budget's reader comes the same way (DEF-5071).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from powershell_guard_rehearsal import (  # noqa: E402
    ROOT_SHAPES,
    BudgetMiss,
    judged_within_budget,
    throwaway_project,
)

#: The root shape ``guard_tier`` builds every project under: plain unless
#: ``--root-shape`` names another, so a run costs one shape's time.
ROOT_SHAPE = "plain"

# Assembled, never written literally: this file is itself scanned by the guards
# it tests, and a literal spelling would make the module unreadable through an
# ordinary `cat`. Same construction, and the same reason, as the sibling
# differential.
_RM = "rm" + " " + "-rf"
_TARGET = "__TARGET__"
_PS_REMOVE = "Remove-Item" + " " + "-Recurse" + " " + "-Force"


# ── R1: the Bash population, DERIVED ────────────────────────────────────────

#: Every head the guards treat as non-reparsing. Read from the module, never
#: copied — §14, "derive the list, don't test a hand-written copy of it". When
#: someone adds a head to that frozenset, this gate covers it on the next run
#: with no edit here. Since the Bash trio's third step the reader heads hold
#: the same privilege (`_head_hands_nothing_to_a_shell`), so their spellings
#: (`_READER_HEAD_SPELLINGS`) join the axis: a reader head added without its
#: own `_HEAD_ARGS` row reds the suite, as a roster head does.
HEADS: tuple[str, ...] = tuple(sorted(
    _bash_patterns._NON_REPARSING_HEADS | _bash_patterns._READER_HEAD_SPELLINGS
))

#: Statement separators. `&&` and `||` are CONDITIONAL and are kept for exactly
#: that reason: their reach counts are reported, so a population that collapses
#: to "nothing executed" is visible instead of silently green.
#: The `&&` axis is the one the per-head liveness check keys on, so its label
#: is a constant both sides read rather than a literal each side spells.
AND_SEPARATOR_NAME = "and"

SEPARATORS: tuple[tuple[str, str], ...] = (
    ("semicolon", "; "),
    ("newline", "\n"),
    (AND_SEPARATOR_NAME, " && "),
    ("or", " || "),
    ("background", " & "),
)

#: Arguments that make each head terminate, EXIT 0, and read no terminal. This
#: table is HAND-WRITTEN and this docstring says so plainly: what the relation
#: derives is the COMBINATION space (head x separator), not the argument
#: spelling. `_assert_population_is_live` keeps a bad spelling from killing a
#: whole separator; `_assert_heads_are_live` keeps one from killing a single
#: head's `&&` row -- which is what a bad spelling actually does, and what the
#: separator aggregate cannot see.
#:
#: ⚠ EVERY SPELLING IS POSIX / BSD+GNU ON PURPOSE, AND THE TABLE IS TOTAL: every
#: head in HEADS has a row here (pinned by the suite), and there is no default.
#: The table used to default to `--version`, a GNU-ism, and spelled the greps
#: `-q probe /dev/null` (no match, rc 1 on every platform). Measured on macOS
#: 2026-09-05, the day the per-head check
#: landed: 25 of 68 present heads had a dead `&&` row -- `cat`, `head`, `tail`,
#: `wc`, `tee`, `tr`, `cut`, `uniq`, `sort`'s siblings, all three greps, and
#: `yes`, which never terminates and cost 15 s per row in timeouts -- while
#: the per-separator aggregate reported green throughout. A head absent from
#: the running platform (`chattr`/`setfacl` on macOS, `chflags`/`tac` on
#: Linux, `ag`/`rg` unless installed) is reported ABSENT and exercised where
#: it exists; a head that is present and dead GATES.
_HEAD_ARGS: dict[str, str] = {
    # The reader heads (the Bash trio's third step): a program that exits 0
    # and reads no terminal; an absent interpreter is reported ABSENT.
    "python": "-c pass",
    "python3": "-c pass",
    "pypy": "-c pass",
    "pypy3": "-c pass",
    "perl": "-e 1",
    "ruby": "-e 1",
    "node": "-e 0",
    "nodejs": "-e 0",
    "awk": "'BEGIN{}'",
    "gawk": "'BEGIN{}'",
    "mawk": "'BEGIN{}'",
    "nawk": "'BEGIN{}'",
    "sed": "-n p /dev/null",
    "gsed": "-n p /dev/null",
    "git": "--version",
    "[": "-d .  ]",
    "test": "-d .",
    "cd": ".",
    "mkdir": "-p probe_dir",
    "touch": "probe_file",
    "mktemp": "-u",
    "sleep": "0",
    "seq": "1",
    # `yes` alone never exits; behind a one-line `head` it gets SIGPIPE and the
    # pipeline's status is head's (0). Both heads are on the roster. The belt
    # is on `yes` ITSELF: `_prefix_for` appends one at the end of the string,
    # where it would bind to `head`, and the belt test reads the segment
    # before the first pipe (failure-mode pass: the substring check passed
    # for the wrong command).
    "yes": "x < /dev/null | head -n 1",
    "echo": "probe",
    "printf": "'%s' probe",
    "expr": "1 + 1",
    "jq": "--version",
    "date": "+%s",
    "df": ".",
    "du": "-s .",
    "diff": "/dev/null /dev/null",
    "comm": "/dev/null /dev/null",
    "join": "/dev/null /dev/null",
    # `-q probe /dev/null` selects no line and exits 1 on EVERY platform: the
    # three grep rows were dead everywhere. `/etc/passwd` exists on macOS and
    # Linux alike; the token is `:` because fgrep matches a LITERAL, every
    # entry line has colons, and a dot is a fact about one machine (a Mac's
    # comment block has four; the ubuntu runner's file has none, so fgrep died
    # there on 2026-09-06, the first Linux drive of this gate). What remains
    # assumed is a passwd file with at least one entry line: a container
    # without one exits 2 (no such file), a missing precondition, not a dead
    # spelling -- the dead message carries the rc so the two are told apart.
    "grep": "-q : /etc/passwd",
    "egrep": "-q : /etc/passwd",
    "fgrep": "-q : /etc/passwd",
    "ag": "--version",
    "rg": "--version",
    # BSD userland takes no `--version`: each of these is a POSIX invocation
    # over /dev/null (or `.`) that exits 0 and reads nothing.
    "cat": "/dev/null",
    "cksum": "/dev/null",
    "cut": "-c1 /dev/null",
    "expand": "/dev/null",
    "unexpand": "/dev/null",
    "fold": "/dev/null",
    "head": "-n 1 /dev/null",   # BSD head rejects a zero count
    "tail": "-n 0 /dev/null",
    "ls": "-d .",
    "nl": "/dev/null",
    "od": "/dev/null",
    "paste": "/dev/null",
    "pwd": "-L",
    "rev": "/dev/null",
    "strings": "/dev/null",
    "tee": "/dev/null",
    "tr": "a a",
    "uniq": "/dev/null",
    "wc": "-c /dev/null",
    # `--help` exits 1 on BSD rmdir; removing a directory this row just made
    # is the one rmdir that succeeds everywhere and leaves nothing behind.
    "rmdir": '"$(mktemp -d)"',
    # The permission verbs joined `_NON_REPARSING_HEADS` on 2026-09-05; BSD
    # chmod/chown/chgrp take no `--version`, so the default made all three rows
    # DEAD on macOS (rc 1, the `&&` row never reached its delete) while the
    # per-separator liveness aggregate stayed green on the other heads. Each is
    # a real no-op invocation that exits 0 on BSD and GNU alike.
    "chmod": "-f u+r .",
    # Numeric ids: `id -un` / `id -gn` resolve NAMES through the passwd and
    # group databases, which a container running an arbitrary UID lacks (the
    # environment docs/SHARP_EDGES.md already records under `Path.home()`), so
    # the substitution collapses to "" and GNU chown rejects the empty spec.
    # getuid()/getgid() need no database, and BSD and GNU chown both accept a
    # number (driven rc 0 on macOS; same class as the grep rows above).
    "chown": '-f "$(id -u)" .',
    "chgrp": '-f "$(id -g)" .',
    # DEF-695 (2026-09-05): the three are platform-split. `chflags` ships on
    # BSD/macOS only (`0` clears every flag on the sandbox cwd, which has none:
    # driven rc 0); `chattr` and `setfacl` ship on Linux only (`= .` sets the
    # attribute set to what a fresh directory already has; `-v` prints the
    # version and exits). A head the running platform lacks is reported
    # ABSENT by `_assert_heads_are_live`, not counted dead, so each row is
    # exercised on the platform that has it and vouches for nothing elsewhere.
    "chflags": "-f 0 .",
    "chattr": "-f = .",
    "setfacl": "-v",
    "basename": "/a/b",
    "dirname": "/a/b",
    "readlink": "-f .",
    "realpath": ".",
    "file": "/dev/null",
    "stat": "/dev/null",
    "column": "/dev/null",
    "numfmt": "--to=si 1000",
    # The rows that used to ride the `--version` default, made explicit so the
    # table is TOTAL over HEADS (pinned by the suite) and the default is gone.
    "false": "",           # inherent: AND_ROW_CANNOT_REACH; no spelling exits 0
    "true": "",
    "less": "-V",
    "more": "-V",
    "sort": "/dev/null",
    "tac": "/dev/null",
    "md5sum": "/dev/null",
    "sha256sum": "/dev/null",
    "shasum": "/dev/null",
    "xxd": "/dev/null",
}

#: Heads whose `&&` row can NEVER reach the delete, by the head's own meaning
#: rather than by a spelling: `false && rm …` runs no `rm` in any shell, so
#: that cell has nothing for R1 to assert and is not a dead spelling. Declared,
#: one member, with the reason -- and the direction of error is the same as
#: the roster's: a head wrongly added here hides a dead row, so it is not a
#: place to park a spelling one cannot get to exit 0.
AND_ROW_CANNOT_REACH: frozenset[str] = frozenset({"false"})

#: Heads whose spelling is a PIPELINE. A pipeline's status is its LAST
#: command's, so the head's own liveness cell cannot fail: `nosuchcmd x |
#: head -n 1` exits 0 (driven). `yes` needs the pipe (alone it never exits),
#: so it is declared here with the reason, the way `false` is declared above;
#: the suite pins that every piped spelling is a member, so the next piped row
#: is reasoned about rather than inherited.
AND_ROW_STATUS_IS_MASKED: frozenset[str] = frozenset({"yes"})


def _prefix_for(head: str) -> str:
    """A terminating, side-effect-free invocation of `head`.

    Everything gets ``< /dev/null`` as an anti-hang belt: several heads
    (``cat``, ``tee``, ``sort``, the pagers) read stdin when given no operand,
    and an inherited stdin would block until the timeout — turning a
    15-second-per-row stall into a population that looks unreachable. The
    belt is appended at the END of the string, so a piped spelling must carry
    its own on the first segment (see the `yes` row). A head with no row is a
    KeyError on purpose: the table is total, and a new head gets a driven
    spelling, not a default.
    """
    args = _HEAD_ARGS[head]
    return f"{head} {args} < /dev/null > /dev/null 2>&1"


def bash_rows(quick: bool = False) -> list[tuple[str, str, str]]:
    """The derived cross-product: (head, separator_name, command_template)."""
    heads = HEADS[::6] if quick else HEADS
    # The quick sample keeps `&&`: it is the axis the per-head liveness check
    # keys on, and `--quick` is the only path CI takes, so a sample without it
    # left `dead_heads` unreachable in every automated run (failure-mode pass,
    # driven: an all-dead quick population reported a clean bill).
    seps = SEPARATORS[:3] if quick else SEPARATORS
    body = f"{_RM} {_TARGET}"
    return [
        (head, sep_name, f"{_prefix_for(head)}{sep}{body}")
        for head in heads
        for sep_name, sep in seps
    ]


# ── R2: the PowerShell population, DERIVED ──────────────────────────────────

#: Inert containers, split by whether PowerShell INTERPOLATES inside them.
#: Verified against real pwsh 7.6.5 on 2026-08-25: `$(...)` inside an expandable
#: span genuinely executes, and inside a literal span genuinely does not.
#:
#: ⚠ THE SPLIT IS LOAD-BEARING. A masking pass that blanket-neutralises an
#: EXPANDABLE span turns a correct DENY into an ALLOW — the fail-open twin of
#: the false positive this relation exists to catch. R2 only asserts ALLOW for
#: the literal half; for the expandable half it asserts INVARIANCE, which holds
#: whichever verdict is correct.
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

#: The transformation R2 asserts is null: where the prose sits relative to the
#: pattern. PowerShell does not care; the guard must not either.
BODY_POSITIONS: tuple[tuple[str, str], ...] = (
    ("prose-before-and-after", "We refuse {pat} by design."),
    ("prose-before", "We refuse {pat}"),
    ("prose-after", "{pat} is refused by design."),
    ("pattern-alone", "{pat}"),
    ("pattern-indented", "   {pat}"),
)

#: Operand shapes. Held as an axis rather than fixed at one spelling, because
#: the corpus rows that hid this defect all used the TARGETLESS spelling.
TARGETS: tuple[tuple[str, str], ...] = (
    ("none", ""),
    ("relative-dot", " ./out"),
    ("relative-backslash", " .\\out"),
    ("absolute-drive", " C:\\"),
    ("glob", " *"),
)


def powershell_rows(quick: bool = False) -> list[tuple[str, str, str, bool, str]]:
    """(container, position, target, is_literal, command) — the cross-product."""
    positions = BODY_POSITIONS[:3] if quick else BODY_POSITIONS
    targets = TARGETS[:2] if quick else TARGETS
    rows = []
    for containers, is_literal in (
        (LITERAL_CONTAINERS, True),
        (EXPANDABLE_CONTAINERS, False),
    ):
        for cname, template in containers:
            for pname, body_t in positions:
                for tname, suffix in targets:
                    body = body_t.format(pat=_PS_REMOVE + suffix)
                    rows.append(
                        (cname, pname, tname, is_literal, template.format(body=body))
                    )
    return rows


# ── Oracles ─────────────────────────────────────────────────────────────────


class InstrumentBroken(RuntimeError):
    """The gate itself is wrong. Never reported as a tree result."""


def guard_tier(command: str, tool: str) -> str:
    """ALLOW / SOFT / HARD, by driving the real hook twice in one project.

    A soft speed-bump is deny-once-then-allow, so one invocation cannot tell it
    from a wall — the distinction that mattered when nine of fifteen ordinary
    relative cleans were HARD on PowerShell and SOFT on Bash.

    Reads the DECISION CHANNEL, and treats rc=1 as the script error it is: an
    earlier probe in this class counted rc=1 (an ImportError) as ALLOW and
    reported that HEAD permitted a catastrophic delete — the flattering answer,
    from a broken instrument.

    The project is the rehearsal's ``throwaway_project``: a root of
    ``ROOT_SHAPE`` carrying every protected directory the hook tree declares,
    so a deny is never missing because the fixture lacked the directory.
    """
    with throwaway_project(HOOKS_DIR / "write_guard.py", ROOT_SHAPE) as project:

        def once() -> bool:
            env = os.environ.copy()
            env["CLAUDE_PROJECT_DIR"] = str(project)
            env.pop("ESPALIER_MAINTENANCE_MODE", None)
            proc = judged_within_budget(lambda: run_bounded(
                [sys.executable, str(HOOKS_DIR / "write_guard.py")],
                input=json.dumps(
                    {"tool_name": tool, "tool_input": {"command": command}}
                ),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, env=env,
            ), HOOKS_DIR, project)
            if proc.returncode == 1 or "Traceback" in (proc.stderr or ""):
                raise InstrumentBroken(
                    "write_guard errored — the instrument is broken, not the "
                    "tree:\n" + (proc.stderr or "")[:600]
                )
            return '"deny"' in (proc.stdout or "") or proc.returncode == 2

        if not once():
            return "ALLOW"
        return "SOFT" if not once() else "HARD"


def assert_instrument_is_live() -> None:
    """A guard that denies nothing scores a comforting zero on every row.

    The calibration pair, not a single probe: one command that MUST deny and one
    that MUST allow. The differential's own history is the argument — a baseline
    whose guard died on import wrote nothing to stdout, every row read as ALLOW,
    and the run reported 0 fail-opens while 63 were live.
    """
    if guard_tier(f"{_RM} /", "Bash") == "ALLOW":
        raise InstrumentBroken("guard allows a catastrophic delete — instrument broken")
    if guard_tier("ls -la", "Bash") != "ALLOW":
        raise InstrumentBroken("guard denies `ls -la` — instrument broken")
    # ⚠ BOTH CHANNELS, because R2 drives ONLY PowerShell and `write_guard`
    # dispatches Bash and PowerShell down independent branches that can break
    # independently. Calibrating Bash alone was the first version of this
    # function, and it left the exact hole it exists to close: with a dead
    # PowerShell branch every R2 group is uniformly ALLOW, so R2a finds no
    # variance and R2b gets the ALLOW it wants — zero violations, nothing tested.
    if guard_tier(f"{_PS_REMOVE} C:\\", "PowerShell") == "ALLOW":
        raise InstrumentBroken(
            "guard allows a drive-root PowerShell delete — instrument broken")
    if guard_tier("Get-Date", "PowerShell") != "ALLOW":
        raise InstrumentBroken("guard denies `Get-Date` — instrument broken")


def _assert_population_is_live(results: list[dict]) -> list[str]:
    """Report separators whose rows never reach the delete.

    ⚠ THIS IS THE ``&&`` LESSON, MECHANISED. A row whose command never executes
    the delete cannot fail R1 no matter how broken the guard is. Silently
    counting those rows as passes is how a gate certifies the safe variant of
    the shape it was written to catch. Reached counts are always reported.
    """
    by_sep: dict[str, list[bool]] = {}
    for row in results:
        by_sep.setdefault(row["separator"], []).append(row["reaches"])
    return [
        f"{sep}: 0/{len(reach)} rows reach the delete — this separator vouches "
        f"for nothing"
        for sep, reach in by_sep.items()
        if not any(reach)
    ]


#: bash builtins a head spelling can name; resolvable by definition.
_SHELL_BUILTIN_HEADS = frozenset({
    "cd", "echo", "test", "[", ":", "true", "false", "eval", "exec", "export",
    "set", "unset", "pwd", "printf", "read", "shift", "source", ".", "command",
})


def _head_is_resolvable(head: str) -> bool:
    """Ask bash itself whether `head` resolves -- a builtin (`cd`, `[`, `test`,
    `echo`) has no PATH entry, so `shutil.which` alone would call it absent.
    A head the reachability bench must also hear ANSWER
    (`reachability_differential._MUST_ANSWER`: `python3`, `python`) runs that
    probe too: a Microsoft Store alias stub resolves as `python3` and, run,
    exits 49 without running anything, so on that host the head is absent,
    never dead (the perturbed CI cell, air's ack f06ec9). The probe is the
    bench's own, not the head's `_HEAD_ARGS` spelling, so a bad spelling
    still reads dead where the interpreter answers."""
    if head in _SHELL_BUILTIN_HEADS:
        # a builtin has no PATH entry and, on a Windows runner, the bash
        # group below answered non-zero for `cd` and `echo` and called them
        # absent (Portability, 2026-09-23); the shell's own builtins are
        # present wherever the shell is
        return True
    if not shutil.which("bash"):
        return True  # no shell to ask; never classify as absent on a guess
    from bench.reachability_differential import _MUST_ANSWER, run_bash_group
    rc, _timed_out = run_bash_group(
        ["bash", "-c", 'command -v -- "$1" > /dev/null 2>&1', "_", head], timeout=10,
    )
    probe = _MUST_ANSWER.get(head)
    if rc != 0 or probe is None:
        return rc == 0
    rc, _timed_out = run_bash_group(
        ["bash", "-c", '"$@" > /dev/null 2>&1', "_", head, *probe], timeout=10,
    )
    return rc == 0


def _spelling_rc(head: str) -> int | str:
    """Drive the head's spelling once more, in a scratch cwd, for the exit code
    the dead message carries: a dead spelling and a missing precondition look
    the same in a boolean and different in an rc."""
    from bench.reachability_differential import run_bash_group
    with tempfile.TemporaryDirectory(prefix="gm-dead-", ignore_cleanup_errors=True) as scratch:
        rc, timed_out = run_bash_group(["/bin/bash", "-c", _prefix_for(head)], cwd=scratch, timeout=10)
    return "timeout" if timed_out else rc


def _assert_heads_are_live(results: list[dict]) -> tuple[list[str], list[str]]:
    """Per-HEAD liveness on the `&&` axis: ``(dead, absent)``.

    ⚠ THE PER-SEPARATOR AGGREGATE CANNOT SEE THIS. `_assert_population_is_live`
    is green as long as SOME head's `&&` row reaches, so one head whose no-op
    spelling exits non-zero is invisible there: its `&&` row never runs the
    delete and vouches for nothing, while `;`, newline, `||` and `&` still
    reach behind it (the delete does not wait on the head). That is exactly
    how the three DEF-638 permission verbs sat dead on macOS with the matrix
    reporting green -- and a hand-kept spelling table fails open for the
    member nobody drove. A head the running platform does not have at all
    (`chattr` / `setfacl` on macOS, `chflags` on Linux) cannot be live here
    and is reported ABSENT, never DEAD: the other platform's run is the one
    that exercises its spelling. Dead heads gate like dead separators do.
    """
    and_rows = {
        r["head"]: r["reaches"] for r in results if r["separator"] == AND_SEPARATOR_NAME
    }
    dead: list[str] = []
    absent: list[str] = []
    # A matrix without `&&` rows (the `--quick` sample keeps only the first two
    # separators) has nothing for this check to say; the label itself cannot
    # drift, since SEPARATORS and this filter read one constant.
    for head, reaches in sorted(and_rows.items()):
        if reaches or head in AND_ROW_CANNOT_REACH:
            continue
        if not _head_is_resolvable(head):
            absent.append(head)
            continue
        dead.append(
            f"{head}: its `&&` row never reaches the delete on this platform -- "
            f"the `_HEAD_ARGS` spelling exits rc={_spelling_rc(head)} (1 is the "
            f"spelling itself; 2 or 127 is a missing precondition, an absent file or "
            f"binary), so this head vouches for nothing"
        )
    return dead, absent


def reach_census(results: list[dict]) -> dict[str, str]:
    """Per-separator reach counts, always reported.

    `&&` reaching 2/10 is not an error, but it IS the number that explains why a
    roster built on `&&` cannot fail. Printing only the total would hide it.
    """
    by_sep: dict[str, list[bool]] = {}
    for row in results:
        by_sep.setdefault(row["separator"], []).append(row["reaches"])
    return {sep: f"{sum(r)}/{len(r)}" for sep, r in by_sep.items()}


# ── The relations ───────────────────────────────────────────────────────────


def check_r1(quick: bool = False) -> dict:
    """Bash prefix invariance: an inert prefix must not disarm the guard."""
    from bench.reachability_differential import bash_reaches

    rows, violations = [], []
    for head, sep_name, template in bash_rows(quick):
        reaches = bash_reaches(template)
        cmd = template.replace(_TARGET, "./victim")
        tier = guard_tier(cmd, "Bash")
        rows.append(
            {"head": head, "separator": sep_name, "reaches": reaches, "tier": tier}
        )
        if reaches and tier == "ALLOW":
            violations.append(
                {
                    "relation": "R1",
                    "head": head,
                    "separator": sep_name,
                    "detail": (
                        f"a real shell reaches the delete behind `{head}` "
                        f"separated by {sep_name}, and the guard ALLOWS it"
                    ),
                }
            )
    dead_heads, absent_heads = _assert_heads_are_live(rows)
    return {
        "relation": "R1",
        "description": "inert prefix must not disarm a reaching command",
        "rows": len(rows),
        "reaching": sum(1 for r in rows if r["reaches"]),
        "violations": violations,
        "dead_separators": _assert_population_is_live(rows),
        "dead_heads": dead_heads,
        "absent_heads": absent_heads,
        "reach_census": reach_census(rows),
    }


def check_r2(quick: bool = False) -> dict:
    """PowerShell inert-span invariance: prose position cannot change a verdict."""
    rows = powershell_rows(quick)
    graded = [
        {
            "container": c, "position": p, "target": t,
            "is_literal": lit, "tier": guard_tier(cmd, "PowerShell"),
        }
        for c, p, t, lit, cmd in rows
    ]

    violations = []

    # (a) INVARIANCE — needs no oracle. Group by (container, target); prose
    #     position is a semantically null transformation, so every member of a
    #     group must share one verdict.
    groups: dict[tuple[str, str], dict[str, str]] = {}
    for row in graded:
        groups.setdefault((row["container"], row["target"]), {})[row["position"]] = row["tier"]
    for (container, target), by_pos in groups.items():
        if len(set(by_pos.values())) > 1:
            violations.append(
                {
                    "relation": "R2a",
                    "container": container,
                    "target": target,
                    "detail": (
                        "verdict depends on where the prose sits inside an inert "
                        f"span: {by_pos}"
                    ),
                }
            )

    # (b) LITERAL spans never interpolate — verified against real pwsh — so
    #     every literal row must be ALLOW outright.
    for row in graded:
        if row["is_literal"] and row["tier"] != "ALLOW":
            violations.append(
                {
                    "relation": "R2b",
                    "container": row["container"],
                    "target": row["target"],
                    "detail": (
                        f"{row['container']} is a literal span (no interpolation) "
                        f"holding a MENTION, and the guard returned "
                        f"{row['tier']} at position {row['position']}"
                    ),
                }
            )

    return {
        "relation": "R2",
        "description": "prose position inside an inert span must not change the verdict",
        "rows": len(graded),
        "violations": violations,
        "dead_separators": [],
        "reach_census": {},
    }


#: Heads that DO re-parse what they are handed. A quoted-delimiter heredoc fed
#: to one of these is live code, not data, and must stay denied however the mask
#: is scoped. Hand-written and short on purpose: this is the must-deny arm, and
#: a floor that does not derive from the roster under test is exactly what keeps
#: a widening of that roster from silently relieving a real protection.
REPARSING_HEADS: tuple[str, ...] = ("bash", "sh", "zsh")

#: Trailing commands appended AFTER a heredoc's terminator. The split is the
#: point: the on-roster half is drawn from the module's own frozenset, the
#: off-roster half is spelled out. Both halves must behave identically, because
#: what follows a finished heredoc cannot reach back into its body.
_OFF_ROSTER_TRAILERS: tuple[str, ...] = (
    "python3 n.py", "git add n.py", "find . -name n.py", "make build",
)


def trailing_rows() -> list[dict]:
    """(label, with_trailer, without_trailer) for the R3 invariance check."""
    on_roster = [f"{h} n.py" for h in sorted(_bash_patterns._NON_REPARSING_HEADS)[:4]]
    base = "cat > n.py <<'EOF'\n{body}\nEOF"
    bodies = [
        ("pattern-alone", f"{_RM} /"),
        ("prose-first", f"the guard refuses {_RM} /"),
        ("pattern-then-prose", f"{_RM} / is refused"),
    ]
    rows = []
    for bname, body in bodies:
        head = base.format(body=body)
        for trailer in list(_OFF_ROSTER_TRAILERS) + on_roster:
            rows.append({
                "body": bname,
                "trailer": trailer,
                "off_roster": trailer in _OFF_ROSTER_TRAILERS,
                "bare": head,
                "with_trailer": head + "\n" + trailer,
            })
    return rows


def check_r3(quick: bool = False) -> dict:
    """A finished heredoc body cannot be re-armed by what comes after it.

    R3a (invariance, no oracle needed): appending a command AFTER a quoted
    heredoc's terminator cannot change what that body means, so it must not
    change the verdict. Measured 2026-08-25, it did: an identical body was
    ALLOWed bare and SOFT-denied once `python3 n.py` followed the terminator,
    because the mask was gated all-or-nothing on the union of every head in the
    command. Write-a-script-then-run-it is among the commonest shapes in this
    repo, and maintenance mode does not relieve it.

    R3b (must-deny) is the other half, and it is why R3a is safe to assert. A
    heredoc fed to a shell IS re-parsed -- that is the premise the whole masking
    pass was built on after 63 fail-opens -- so a body handed to `bash` must
    stay denied. Relieving R3a without R3b would be the same edit that opened
    those fail-opens, seen from the friction side.
    """
    rows = trailing_rows()
    if quick:
        rows = rows[::3]
    violations = []

    for row in rows:
        bare = guard_tier(row["bare"], "Bash")
        witht = guard_tier(row["with_trailer"], "Bash")
        if bare != witht:
            violations.append({
                "relation": "R3a",
                "detail": (
                    f"a trailing `{row['trailer']}` changed the verdict of an "
                    f"unchanged heredoc body ({row['body']}): {bare} -> {witht}"
                ),
            })

    # R3b -- the safety half. A heredoc fed to a re-parser is live code.
    for head in REPARSING_HEADS:
        cmd = f"{head} <<'EOF'\n{_RM} /\nEOF"
        tier = guard_tier(cmd, "Bash")
        if tier == "ALLOW":
            violations.append({
                "relation": "R3b",
                "detail": (
                    f"a heredoc fed to `{head}` is RE-PARSED and executes, and "
                    f"the guard allowed it -- the mask has over-reached"
                ),
            })

    return {
        "relation": "R3",
        "description": "a finished heredoc body is inert whatever follows it",
        "rows": len(rows) + len(REPARSING_HEADS),
        "violations": violations,
        "dead_separators": [],
        "reach_census": {},
    }


# ── R4: a stderr redirect among the operands, DERIVED ───────────────────────
#
# The job four lanes fixed one reader set at a time (DEF-5107, DEF-5108,
# DEF-2088, DEF-2087): a reader that takes a verb's operands by their place
# must see the operands the shell hands the verb, wherever a redirect sits
# among them. R4 is that job's oracle (DEF-5120). Its population is the
# denied rows of `tests/test_write_guard.py::TestRemovedOrRelocatedOperandIsAMutation`
# (`_ZONE_ROWS`, `_SECRET_ROWS`), read from the class, never copied, each
# spelled under the plain root for every protected kind the class spells it
# for, and the wall rows of `TestCatastrophicFindDelete` (`_root_rows`: its
# matrix's catastrophic rows from the checkout itself, DEF-5122). Its
# transformation is a stderr redirect, each of the tool's spellings, written
# at each blank between tokens after the command word, at the end, and on
# Bash before the command word. Its relation: a denied row stays denied.
#
# The transformation is proved null per row and per place by the tool's own
# parser, never assumed: bash parses both spellings syntax-only (`bash -n`)
# and prints each parsed form (`declare -f` of a function holding it; the
# function is defined and printed, never called), and the spelling is null
# where the two printed forms differ by the redirect alone (a spelling bash
# prints as written, `2>&1`, is proved on a twin it prints otherwise and must
# parse to the twin's form: `R4_BASH_TWINS`); PowerShell's
# `Parser::ParseInput` gives each command's elements, and the spelling is null
# where they are equal and the one redirection more is the one written. No
# row is executed: a parser decides what a verb is handed, and a redirect is
# never a word. A place the parser rejects, or reads as changing a word (a
# blank inside a heredoc body, a comment), is out of the relation's domain and
# counted apart, never judged.
#
# The judges are the classes' own (`_zone_denied`, `_secret_denied`,
# `_wall_denied`): the zone checks, the secret check and the Bash hard tier
# in-process on the operand class's own projects (`built_projects`), with the
# speed bump and the maintenance gate out of the loop, as the classes pin
# them. In-process also lets a suite test blind the redirect view, or the
# hard checks' redirect-free reading, and watch this relation go red.

#: The stderr redirects written into each place, per tool: the file spelling,
#: and the merge, whose `&` a reader can take for a background `&` (DEF-5122:
#: the directory chain lost its anchor to `2>&1` alone, which R4 never wrote).
#: An error stream is never where a verb reads its operands from, so each is
#: null for what the verb is handed wherever the parser accepts it.
R4_REDIRECTS: dict[str, tuple[str, ...]] = {
    "Bash": ("2>/dev/null", "2>&1"), "PowerShell": ("2>$null", "2>&1")}
#: Each tool's first spelling, the default where a caller names none.
R4_REDIRECT: dict[str, str] = {tool: spellings[0] for tool, spellings in R4_REDIRECTS.items()}

#: The Bash spellings whose null proof is read from a twin. bash's printed
#: form proves a parse only where it differs from the written text
#: (`2>/dev/null` prints as `2> /dev/null`); `2>&1` prints as written, so its
#: text read back from a quoted word would pass for a parse. The twin `2>& 1`
#: is the same operator and word and prints as `2>&1`: its place is proved null
#: as any spelling's is, and the spelling's own form must then equal the
#: twin's, so both are one parse (`_bash_proof`, `check_r4`).
R4_BASH_TWINS: dict[str, str] = {"2>&1": "2>& 1"}


def _bash_proof(redirect: str) -> str:
    """The text whose parse proves ``redirect``'s place null: its twin, or
    the spelling itself."""
    return R4_BASH_TWINS.get(redirect, redirect)

#: What a red asks next, printed under R4's violations (DEF-5120). R4 holds no
#: exclusion: a row held out by name hid the kinds no after-check watches
#: (both reviews), and a red quick run lists every kind of its red rows
#: (`check_r4`), so a red that shows only a watched zone is never read as the
#: after-check's job. The helper names are pinned to the hooks module.
R4_REMEDY_HELPERS = ("_redirects_blanked", "_scan_and_view_matches", "stderr_redirect_free_command")
R4_REMEDY = (
    "next: see that the hard check the row reaches is judged on the command with its error-stream "
    f"redirects blanked as well (`_also_stderr_redirect_free` in tools/cc/hooks/write_guard.py, "
    f"over `{R4_REMEDY_HELPERS[2]}`); where it is, match the reader that takes this operand by its "
    f"place on the redirect view as well (`{R4_REMEDY_HELPERS[0]}`, `{R4_REMEDY_HELPERS[1]}` in "
    "tools/cc/hooks/_bash_patterns.py; the row's arm names the class's reader); R4 holds no "
    "exclusion, so a red no reader fix meets goes to the dispatcher as a ledger row and the run "
    "stays red: never a skip by key written into R4"
)


def _operand_class():
    """`TestRemovedOrRelocatedOperandIsAMutation`, imported from the suite.

    Read from the class so a row the class gains joins R4 with no edit here
    (§14); `bench/` is dev-only and runs where pytest is installed. A tree
    without tests/ (an adopter's, the wheel's) has no population: R4's
    instrument is broken there, never a pass."""
    try:
        from tests.test_write_guard import TestRemovedOrRelocatedOperandIsAMutation
    except ImportError as exc:
        raise InstrumentBroken(f"R4 reads its rows from tests/test_write_guard.py, absent here: {exc}") from exc
    return TestRemovedOrRelocatedOperandIsAMutation


def _wall_class():
    """`TestCatastrophicFindDelete`, imported from the suite as the operand
    class is: its matrix's root rows are R4's wall rows (DEF-5122), and its
    `_wall_denied` their judge."""
    try:
        from tests.test_write_guard import TestCatastrophicFindDelete
    except ImportError as exc:
        raise InstrumentBroken(f"R4 reads its wall rows from tests/test_write_guard.py, absent here: {exc}") from exc
    return TestCatastrophicFindDelete


#: The arm a wall row names: the classifier the Bash hard tier asks.
R4_WALL_ARM = "has_catastrophic_find_delete"


def operand_rows(quick: bool = False) -> list[dict]:
    """Every denied row of the two tables, spelled under the plain root, one
    entry per (row, kind), and every wall row of the find class's matrix
    (table ``_MATRIX``, kind ``-``, keyed by its text): ``table``, ``key``,
    ``tool``, ``arm``, ``kind``, ``command``. ``quick`` (the suite's only path) keeps each row's first
    kind, so every row is judged in CI and a row added moves no other row's
    sample: a stride over the forms left 72 of 252 rows unjudged there, two
    of the lane's readers could leave the view with the suite green, and a
    red left in an unsampled row surfaced on the next lane to shift the
    stride (the failure-mode review's F1). The first kind is a `tools/` path
    in every table, which the after-check watches; a red quick run re-judges
    its red rows on every kind (`check_r4`). The full population runs by hand
    only (`--relation R4` without `--quick`, about 26 s on the Air): no CI
    job runs it, and on the guard before DEF-5120 no row was red on only some
    of its kinds (the second failure-mode review, measured)."""
    cls = _operand_class()
    rows = []
    for table in ("_ZONE_ROWS", "_SECRET_ROWS"):
        for key, (tool, expect, arm, command) in getattr(cls, table).items():
            if expect != "deny":
                continue
            forms = cls._plain_forms(command)
            for kind, spelled in forms[:1] if quick else forms:
                rows.append({"table": table, "key": key, "tool": tool, "arm": arm,
                             "kind": kind, "command": spelled})
    for command in _wall_class()._root_rows():
        rows.append({"table": "_MATRIX", "key": command, "tool": "Bash", "arm": R4_WALL_ARM,
                     "kind": "-", "command": command})
    return rows


def _token_blanks(command: str, tool: str) -> list[int]:
    """The offsets where R4 writes the redirect: on Bash the start of the
    command word, then the start of each run of blanks between two tokens
    after the command word, the end of each line after it, and the end of
    the command. Only places outside every quote, escape and bracket (a
    subexpression, a group, a script block, a brace expansion) are offered;
    the parser decides which of them are null, so this scan errs toward
    offering a place, never toward deciding one. The place before the
    command word is Bash's alone: PowerShell's parser read none of its 594
    null, and on Bash it is the one a command-position prefix reads past
    (the failure-mode review's F6: 639 of 660 null, none offered)."""
    powershell = tool == "PowerShell"
    escape = "`" if powershell else "\\"
    points: list[int] = []
    depth = 0
    quote: str | None = None
    first_word_done = False
    in_word = False
    i, n = 0, len(command)
    while i < n:
        ch = command[i]
        if quote is not None:
            if powershell and quote in ("@'", '@"'):
                closer = "\n" + quote[1] + "@"
                end = command.find(closer, i)
                i = n if end < 0 else end + len(closer)
                quote = None
                continue
            if ch == escape and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch == escape:
            i += 2
            in_word = True
            continue
        if powershell and command.startswith(("@'\n", '@"\n'), i):
            quote = command[i:i + 2]
            in_word = True
            i += 3
            continue
        if ch in ("'", '"'):
            quote = ch
            in_word = True
            i += 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if depth == 0 and ch in " \t":
            if in_word:
                first_word_done = True
            if first_word_done:
                points.append(i)
            while i < n and command[i] in " \t":
                i += 1
            in_word = False
            continue
        if depth == 0 and ch == "\n":
            if in_word:
                first_word_done = True
            if first_word_done and (not points or points[-1] != i):
                points.append(i)
            in_word = False
            i += 1
            continue
        in_word = True
        i += 1
    if first_word_done or in_word:
        points.append(n)
        lead = n - len(command.lstrip(" \t"))
        if not powershell and lead < n:
            points.append(lead)
    return sorted(set(points))


#: The carriers R4 lays each denied Bash row inside (DEF-5126): the three
#: ways a Bash command hands a program down one level that the redirect view
#: reads (DEF-5121, `_programs_handed_down` in tools/cc/hooks/_bash_patterns.py),
#: each as the text before and after the program, named by the kind of span
#: it carries (`R4_REACH`).
R4_CARRIERS: dict[str, tuple[str, str]] = {
    "shell -c": ("bash -c '", "'"),
    "eval": ("eval '", "'"),
    "substitution": ('echo "$(', ')"'),
}
#: Each carrier's kind of span: an exec-quoted word, or a substitution body.
_R4_CARRIER_KIND = {"shell -c": "word", "eval": "word", "substitution": "body"}

#: The view's stated reach one level down, held here as R4's own rule and
#: never read from the view's code (air's ruling fd58a2): the characters a
#: carried program may not hold for the view to read it in place. A word a
#: shell's `-c` or `eval` takes is read where it holds no quote, backslash,
#: `$` or backtick, so its quote removal is its inside (`_exec_quoted_program`);
#: a substitution body is read where it holds no double quote, backslash or
#: backtick (`_substitution_close`). A carried row outside the reach is
#: counted apart and never judged; a view that narrows its reach reds here,
#: and one that widens it is untested until this rule follows.
R4_REACH: dict[str, str] = {"word": "'\"\\$`", "body": '"\\`'}

#: The other half of a word's reach: the view reads in place no word that
#: opens on a prefix (`_PROGRAM_OPENS_ON_PREFIX_RE`: a wrapper run, an
#: assignment, a keyword, `!` or a redirect), so R4 carries no row whose
#: program opens on one and offers no place before a carried word's command
#: word. R4's own list, each a prefix the view's family reads (pinned by
#: `tests/test_guard_metamorphic.py`), and narrower than that family by
#: design: a row opening on a prefix the list lacks is carried, and where it
#: reds, the remedy is the word added here; a word here the view stopped
#: reading would hide a row, which the pin refuses.
R4_WORD_PREFIXES = ("sudo", "doas", "env", "nohup", "nice", "time", "timeout", "exec", "command",
                    "xargs", "if", "while")
_R4_WORD_PREFIX_RE = re.compile(
    r"[ \t]*(?:[A-Za-z_][A-Za-z0-9_]*=|!|[0-9]*[<>]|(?:" + "|".join(R4_WORD_PREFIXES) + r")(?=[ \t]|$))")

#: The shells whose `-c` word `_carried_spans` reads as a program: the POSIX
#: family the view's exec quote names.
_R4_SHELLS = frozenset({"bash", "sh", "dash", "zsh", "ksh"})


def _in_reach(program: str, kind: str) -> bool:
    """Whether the view's stated reach takes ``program``, carried in a span
    of ``kind``: none of `R4_REACH`'s characters, and for a word no opening
    prefix (`_R4_WORD_PREFIX_RE`)."""
    if any(ch in program for ch in R4_REACH[kind]):
        return False
    return kind != "word" or _R4_WORD_PREFIX_RE.match(program) is None


def carried_rows(rows: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Each Bash row of ``rows`` laid inside each carrier whose span the view
    reads it in (`_in_reach`): the row's own entry with ``carrier`` set and
    the carried text as its ``command``, so a row the class gains is carried
    with no edit here (DEF-5126); and, per carrier, the count of rows left
    outside the reach. A row already carried is not carried again: R4 reads
    one level down (`_carried_spans`)."""
    out: list[dict] = []
    outside = dict.fromkeys(R4_CARRIERS, 0)
    for row in rows:
        if row["tool"] != "Bash" or row.get("carrier"):
            continue
        for name, (before, after) in R4_CARRIERS.items():
            if _in_reach(row["command"], _R4_CARRIER_KIND[name]):
                out.append({**row, "carrier": name, "command": before + row["command"] + after})
            else:
                outside[name] += 1
    return out, outside


def _substitution_body_end(command: str, at: int) -> int:
    """The offset of the `)` closing the command substitution whose body
    starts at ``at``, or -1: parentheses counted, a single-quoted span passed
    over whole, and -1 at a character the body's reach leaves out
    (`R4_REACH`), since the view reads no such body. bash's acceptance of the
    carried text and of the body alone stay the proof (`check_r4`); this
    scan only says where to look. Where it ends a body before bash would (a
    case pattern's `)`), the body alone fails to parse and its places read
    not null; ending one after bash would take a stray `)` past the real
    close, which no row holds (the code review's M2)."""
    depth, i, n = 1, at, len(command)
    while i < n:
        ch = command[i]
        if ch in R4_REACH["body"]:
            return -1
        if ch == "'":
            close = command.find("'", i + 1)
            if close < 0:
                return -1
            i = close + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _carried_spans(command: str) -> list[tuple[int, int, str]]:
    """The spans of each program a Bash command hands down one level within
    the view's stated reach (`R4_REACH`), its quotes and a substitution's
    `$(` and `)` left out, each with its kind (DEF-5126): a quoted word after
    a shell's `-c` or after `eval` (``word``), and the body of each command
    substitution inside a double-quoted span outside every bracket, in order
    up to the first the reach leaves out (``body``; an arithmetic `$((` is not
    a program). A word counts only where its shell or its `eval` opens a
    statement. The scan says where a carried program is, and bash's parse of
    that program alone, and of the carried row, then proves each place inside
    it (`check_r4`); a word span rests on this scan's reading of the head.
    One level only, R4's own limit: the view reads one exec-quoted word inside
    a body as well (`_nested_programs_blanked`), pinned there by the hand rows
    of `tests/test_write_guard.py::TestARedirectInsideAHandedDownProgramKeepsTheVerdict`,
    and R4 offers no place in it."""
    spans: list[tuple[int, int, str]] = []
    # each word with whether it opens a statement: a `-c` shell or an `eval`
    # hands its word down only at a command position (the code review's M1)
    words: list[tuple[int, int, bool]] = []
    i, n, depth = 0, len(command), 0
    start: int | None = None
    opens = True
    while i < n:
        ch = command[i]
        if ch == "\\":
            start = i if start is None else start
            i += 2
            continue
        if ch == "'":
            start = i if start is None else start
            close = command.find("'", i + 1)
            i = n if close < 0 else close + 1
            continue
        if ch == '"':
            start = i if start is None else start
            j, reading = i + 1, depth == 0
            while j < n and command[j] != '"':
                if command[j] == "\\":
                    j += 2
                    continue
                if reading and command.startswith("$(", j):
                    close = -1 if command.startswith("$((", j) else _substitution_body_end(command, j + 2)
                    if close < 0:
                        # the bodies are read in order up to the first the
                        # reach leaves out, as the view reads them
                        reading = False
                        j += 1
                        continue
                    spans.append((j + 2, close, "body"))
                    j = close + 1
                    continue
                j += 1
            i = j + 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if depth == 0 and ch in " \t\n;&|":
            if start is not None:
                words.append((start, i, opens))
                start = None
                opens = False
            # a redirect's `&` (`2>&1`) separates nothing
            if ch in "\n;|" or (ch == "&" and command[i - 1:i] not in ("<", ">")):
                opens = True
            i += 1
            continue
        start = i if start is None else start
        i += 1
    if start is not None:
        words.append((start, n, opens))
    for k, (lo, hi, _opens) in enumerate(words):
        word = command[lo:hi]
        if (k == 0 or len(word) < 2 or word[0] not in "'\"" or word[-1] != word[0]
                or not _in_reach(word[1:-1], "word")):
            continue
        head = command[words[k - 1][0]:words[k - 1][1]]
        shell = (k >= 2 and head == "-c" and words[k - 2][2]
                 and command[words[k - 2][0]:words[k - 2][1]].rsplit("/", 1)[-1] in _R4_SHELLS)
        if shell or (head == "eval" and words[k - 1][2]):
            spans.append((lo + 1, hi - 1, "word"))
    return sorted(spans)


def r4_places(command: str, tool: str) -> list[tuple[int, tuple[int, int] | None]]:
    """Each place R4 writes the redirect, with the carried program's span
    for a place inside one (None for a place among the command's own words):
    `_token_blanks` over the command, and on Bash each carried program's own
    places (`_token_blanks` over its text, shifted to its offset), one level
    down (DEF-5126), the place before a carried word's command word left out
    (a redirect there opens the word on a prefix, outside the view's stated
    reach: `R4_REACH`). A place inside a carried program is proved null by
    the program's own parse (`check_r4`)."""
    places: list[tuple[int, tuple[int, int] | None]] = [(at, None) for at in _token_blanks(command, tool)]
    if tool == "Bash":
        for lo, hi, kind in _carried_spans(command):
            program = command[lo:hi]
            lead = len(program) - len(program.lstrip(" \t"))
            places += [(lo + at, (lo, hi)) for at in _token_blanks(program, tool)
                       if not (kind == "word" and at == lead)]
    return places


def insert_redirect(command: str, tool: str, at: int, redirect: str | None = None) -> str:
    """``command`` with a stderr redirect (``redirect``, else the tool's first
    spelling) written at offset ``at``: after a blank before a blank or the
    end, and before a blank at a word's start (the place before the command
    word), so it never glues to a word."""
    redirect = redirect or R4_REDIRECT[tool]
    if at < len(command) and command[at] not in " \t\n":
        return command[:at] + redirect + " " + command[at:]
    return command[:at] + " " + redirect + command[at:]


def insert_redirect_at(command: str, tool: str, at: int, span: tuple[int, int] | None,
                       redirect: str | None = None) -> str:
    """``command`` with the redirect written at ``at``: among the command's
    words where ``span`` is None, else inside the carried program
    ``command[span[0]:span[1]]``, written into that program's text as
    :func:`insert_redirect` writes it, so it glues to none of its words and
    never to the carrier's closing quote (DEF-5126)."""
    if span is None:
        return insert_redirect(command, tool, at, redirect)
    lo, hi = span
    return command[:lo] + insert_redirect(command[lo:hi], tool, at - lo, redirect) + command[hi:]


def _scratch_env(scratch: Path) -> dict[str, str]:
    """A parse's environment: nothing on PATH but an empty directory, so a
    spelling that somehow ran would find no program (belt, not brace: the
    parse executes no row)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "BASH_FUNC_"))}
    env["PATH"] = str(scratch)
    env.pop("ENV", None)
    env.pop("BASH_ENV", None)
    return env


def _bash_reading(argv: list[str], text: str, feed_dir: str, scratch: str, env: dict[str, str], timeout: float):
    """``argv`` run with ``text`` on its standard input, from a file of its
    own in ``feed_dir`` holding the text's UTF-8 bytes exactly (strict: a
    text UTF-8 cannot carry stops the run rather than parse as another).
    Never one argument: a 100 KB text passed Windows' 32,767-character
    command line and the syntax pass's `bash -n -c` stopped on WinError 206
    (post-merge-windows run 44168215720). Never a pipe either: a text-mode
    one writes each newline as CRLF on Windows (the Git Bash runs read the
    batch right through it; bash 3.2 gives every form None), and bash reads
    any pipe a byte at a time where it reads a file in blocks (a 1.2 MB
    batch, median 0.338 s piped against 0.035 s from a file on the Air, the
    code review). ``feed_dir`` is a directory apart from ``scratch``, the
    parse's PATH and cwd, so that PATH stays empty; one file a spawn, so no
    two spawns share one."""
    fd, name = tempfile.mkstemp(dir=feed_dir)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(text.encode("utf-8"))
        with open(name, "rb") as handle:
            return run_bounded(argv, stdin=handle, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout, cwd=scratch, env=env)
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass  # the directory's own cleanup takes what is left


def bash_parsed_forms(texts: list[str], bash: str, drops: list[int] | None = None) -> list[str | None]:
    """Each text's form as bash prints it after parsing, or None where bash
    rejects it. Syntax-only first (`bash -n`, one text per run, so a reject is
    the text's own); the accepted ones are then each defined as a function and
    printed with `declare -f` in one restricted run (`bash -r`, an empty PATH
    and cwd). Defining a function runs none of its body, and a text `bash -n`
    accepted is a complete list, so it cannot close the function early. A
    text holding a heredoc is printed in a run of its own: one left open in a
    batch (R4's place after its terminator) took the closing brace and the
    next text's definition up to that text's own terminator, and the batch
    still printed, so the open text got its neighbour's form and the
    neighbour an empty one (the code review, driven). A form the safeguard
    below refuses is no form, and its index joins ``drops`` where the caller
    gives one, so a batch that goes wrong in a new shape is counted rather
    than read as a place that is not null (the second failure-mode review's
    N-5: the census reds only at zero null places). Every text, and every
    batch's script, reaches bash on its standard input from a file
    (``_bash_reading``)."""
    out: list[str | None] = [None] * len(texts)
    with tempfile.TemporaryDirectory(prefix="gm-r4-bash-") as scratch, \
            tempfile.TemporaryDirectory(prefix="gm-r4-feed-") as feed_dir:
        env = _scratch_env(Path(scratch))
        accepted = []
        for idx, text in enumerate(texts):
            proc = _bash_reading([bash, "-n"], text, feed_dir, scratch, env, timeout=15)
            if proc.returncode == 0:
                accepted.append(idx)
        sep = "__R4_FORM_END__"

        def print_forms(batch: list[int]) -> None:
            # A text `bash -n` accepts alone can still fail inside a function
            # body (a heredoc delimited by the end of input takes the closing
            # brace with it), so a batch that fails is halved until each
            # failure is one text's own, and that text gets no form.
            if not batch:
                return
            script = "".join(f"__r4_{idx}() {{\n{texts[idx]}\n}}\n" for idx in batch)
            script += "".join(f"declare -f __r4_{idx}\nprintf '%s\\n' {sep}\n" for idx in batch)
            # never one argument: R4's full population passed the platform's
            # argument limit (DEF-5122's first full run)
            proc = _bash_reading([bash, "-r"], script, feed_dir, scratch, env, timeout=60)
            forms = proc.stdout.split(sep + "\n") if proc.returncode == 0 else []
            if len(forms) == len(batch) + 1:
                for idx, form in zip(batch, forms):
                    # the function's name is the one thing two texts' forms must not share
                    named = form.replace(f"__r4_{idx} ()", "__r4 ()", 1)
                    # an empty form, or one holding another text's definition,
                    # is a batch that went wrong past bash's notice: no form
                    if named.strip() and "__r4_" not in named:
                        out[idx] = named
                    elif drops is not None:
                        drops.append(idx)
            elif len(batch) > 1:
                half = len(batch) // 2
                print_forms(batch[:half])
                print_forms(batch[half:])

        for idx in accepted:
            if "<<" in texts[idx]:
                print_forms([idx])
        print_forms([idx for idx in accepted if "<<" not in texts[idx]])
    return out


#: The PowerShell parse: each text's errors, its commands' elements (or a
#: command expression's text) in tree order, and its redirections. Written
#: for Windows PowerShell 5.1 as well as pwsh 7 (no `u{}` escape).
_PS_PARSE = r"""
$sep = [string][char]31
$texts = Get-Content -Raw -LiteralPath $args[0] -Encoding UTF8 | ConvertFrom-Json
$out = foreach ($text in $texts) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput([string]$text, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) { [pscustomobject]@{ ok = $false; shape = @(); redirections = @() }; continue }
    $commands = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandBaseAst] }, $true)
    $shape = @(foreach ($c in $commands) {
        if ($c -is [System.Management.Automation.Language.CommandAst]) {
            'C:' + (@($c.CommandElements | ForEach-Object { $_.Extent.Text }) -join $sep)
        } else { 'E:' + $c.Expression.Extent.Text }
    })
    $redirections = @(foreach ($c in $commands) { foreach ($r in $c.Redirections) { $r.Extent.Text } })
    [pscustomobject]@{ ok = $true; shape = $shape; redirections = $redirections }
}
ConvertTo-Json -InputObject @($out) -Depth 5 -Compress
"""


def powershell_parsed_forms(texts: list[str], pwsh: str) -> list[dict | None]:
    """Each text's parse as PowerShell reads it, or None where it rejects it:
    ``{"shape": [...], "redirections": [...]}``. One interpreter for every
    text; `ParseInput` executes nothing."""
    with tempfile.TemporaryDirectory(prefix="gm-r4-pwsh-") as scratch:
        src = Path(scratch) / "texts.json"
        src.write_text(json.dumps(texts), encoding="utf-8")
        script = Path(scratch) / "parse.ps1"
        script.write_text(_PS_PARSE, encoding="utf-8")
        env = os.environ.copy()
        if os.name != "nt":
            # One writer per startup cache (Core Rule 14; the differential's
            # 2026-09-10 corruption): this run's pwsh keeps its own.
            env["XDG_CACHE_HOME"] = str(Path(scratch) / "cache")
        proc = run_bounded([pwsh, "-NoProfile", "-NonInteractive", "-File", str(script), str(src)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=300, cwd=scratch, env=env)
    if proc.returncode != 0:
        raise InstrumentBroken(
            f"PowerShell's parser did not answer (rc={proc.returncode}): {(proc.stderr or '')[:400]}")
    try:
        parsed = json.loads(proc.stdout)
    except ValueError as exc:
        raise InstrumentBroken(f"PowerShell's parse is not JSON: {exc}: {proc.stdout[:200]!r}") from exc
    if not isinstance(parsed, list) or len(parsed) != len(texts):
        raise InstrumentBroken(f"PowerShell parsed {len(parsed)} of {len(texts)} texts")
    return [{"shape": p["shape"] or [], "redirections": p["redirections"] or []} if p["ok"] else None
            for p in parsed]


def _bash_redirect_form(bash: str, redirect: str | None = None) -> str:
    """The redirect (``redirect``, else Bash's first spelling) as bash prints
    it in a parsed form, read from bash: the one difference between a
    calibration command and the same with the redirect's proof text
    (`_bash_proof`) written among its words. A form the proof text holds as
    written is refused: removing it from a quoted word's text would read as
    a parse."""
    redirect = redirect or R4_REDIRECT["Bash"]
    proof = _bash_proof(redirect)
    plain, moved = bash_parsed_forms(["printf %s a b", f"printf %s a {proof} b"], bash)
    if plain is None or moved is None or moved == plain:
        raise InstrumentBroken(f"bash printed no redirect for the calibration command ({redirect})")
    head = 0
    while head < len(plain) and plain[head] == moved[head]:
        head += 1
    tail = 0
    while tail < len(plain) - head and plain[-1 - tail] == moved[-1 - tail]:
        tail += 1
    form = moved[head:len(moved) - tail]
    if redirect.replace(" ", "") not in form.replace(" ", ""):
        raise InstrumentBroken(f"bash's printed difference is not the redirect: {form!r}")
    if form.strip() in proof:
        raise InstrumentBroken(
            f"bash prints {proof!r} as written ({form.strip()!r}), so its parse cannot be told from its "
            "text in a quoted word: give the spelling a twin bash prints otherwise (R4_BASH_TWINS)")
    return form


def bash_insertion_is_null(original: str | None, inserted: str | None, form: str) -> bool:
    """The redirect was read as a redirect and nothing else moved: removing one
    printed redirect from the inserted form gives the original form."""
    if original is None or inserted is None:
        return False
    start = inserted.find(form)
    while start >= 0:
        if inserted[:start] + inserted[start + len(form):] == original:
            return True
        start = inserted.find(form, start + 1)
    return False


def powershell_insertion_is_null(original: dict | None, inserted: dict | None,
                                 redirect: str | None = None) -> bool:
    """The commands' elements are unchanged and the one redirection more is
    the one written (``redirect``, else PowerShell's first spelling)."""
    if original is None or inserted is None or original["shape"] != inserted["shape"]:
        return False
    extra = list(inserted["redirections"])
    for r in original["redirections"]:
        if r not in extra:
            return False
        extra.remove(r)
    return extra == [redirect or R4_REDIRECT["PowerShell"]]


def assert_parsers_are_live(bash: str | None, pwsh: str | None) -> str | None:
    """The calibration pair per parser and per spelling, so a parser that
    reads every place as null (or none) cannot vouch for any spelling R4
    writes: a redirect among the words is null, and the same characters
    inside a quoted word are not. Returns bash's printed form of its first
    spelling (None without bash)."""
    form = None
    if bash:
        for redirect in R4_REDIRECTS["Bash"]:
            printed = _bash_redirect_form(bash, redirect)
            form = form or printed
            proof = _bash_proof(redirect)
            plain, moved, quoted, quoted_moved, own = bash_parsed_forms(
                ["printf %s a b", f"printf %s {proof} a b",
                 "printf %s 'a b'", f"printf %s 'a {proof} b'", f"printf %s {redirect} a b"], bash)
            if not bash_insertion_is_null(plain, moved, printed):
                raise InstrumentBroken(f"bash's parse does not read {proof} among the words as null")
            if bash_insertion_is_null(quoted, quoted_moved, printed):
                raise InstrumentBroken(f"bash's parse reads a quoted {proof} as a redirect")
            if own is None or own != moved:
                raise InstrumentBroken(f"bash parses {redirect} otherwise than its twin {proof}")
    if pwsh:
        for redirect in R4_REDIRECTS["PowerShell"]:
            plain, moved, quoted, quoted_moved = powershell_parsed_forms(
                ["Write-Output a b", f"Write-Output a {redirect} b",
                 "Write-Output 'a b'", f"Write-Output 'a {redirect} b'"], pwsh)
            if not powershell_insertion_is_null(plain, moved, redirect):
                raise InstrumentBroken(f"PowerShell's parse does not read {redirect} among the words as null")
            if powershell_insertion_is_null(quoted, quoted_moved, redirect):
                raise InstrumentBroken(f"PowerShell's parse reads a quoted {redirect} as a redirect")
    return form


def check_r4(quick: bool = False, pwsh: str | None = None, rows: list[dict] | None = None) -> dict:
    """A stderr redirect among a denied row's operands never lowers its verdict.

    ``rows`` replaces the derived population (a suite test drives a few rows
    under a blinded reader); left out, it is :func:`operand_rows`, and a
    quick run that finds a red judges each red row's other kinds as well
    before it reports, so the red lists the kinds the after-check does not
    watch (`cc/`, the settings files) beside the `tools/` one the sample
    holds (the second failure-mode review's SF-1: 94 such places on the
    guard before DEF-5120 showed in the full run alone)."""
    bash = shutil.which("bash")
    assert_parsers_are_live(bash, pwsh)
    printed = {r: _bash_redirect_form(bash, r) for r in R4_REDIRECTS["Bash"]} if bash else {}
    cls = _operand_class()
    wall = _wall_class()
    derived = rows is None
    outside_reach = dict.fromkeys(R4_CARRIERS, 0)
    if rows is None:
        plain = operand_rows(quick)
        carried, outside_reach = carried_rows(plain)
        rows = plain + carried
    drops: list[int] = []
    tools_run = {"Bash": bash is not None, "PowerShell": pwsh is not None}
    # (row, at, text, redirect, span): ``span`` is the carried program's for a
    # place inside one (DEF-5126), None for a place among the command's words
    candidates = []
    for row in rows:
        if tools_run[row["tool"]]:
            for at, span in r4_places(row["command"], row["tool"]):
                for redirect in R4_REDIRECTS[row["tool"]]:
                    candidates.append((row, at, insert_redirect_at(row["command"], row["tool"], at, span, redirect),
                                       redirect, span))

    null_by_text: dict[str, bool] = {}
    rejected: set[str] = set()
    for tool in ("Bash", "PowerShell"):
        if not tools_run[tool]:
            continue
        mine = [c for c in candidates if c[0]["tool"] == tool]
        if tool == "Bash":
            # Each place is proved on the program the verb's shell parses: the
            # command for a place among its words, the carried program's own
            # text for a place inside one, since the carrier hands that text
            # down whole and bash's printed form of the carrier holds a quoted
            # word as written (DEF-5126). A twinned spelling's place is proved
            # on its twin's text, and its own text must parse to the twin's
            # form (R4_BASH_TWINS). A place inside a carried program also
            # needs bash to accept the carried row itself; the redirect adds
            # no quote, escape, bracket or comment to the carrier.
            proving = []    # (text, original, inserted, proof, redirect, carried)
            for row, at, text, redirect, span in mine:
                lo, hi = span if span is not None else (0, len(row["command"]))
                original = row["command"][lo:hi]
                inserted = insert_redirect(original, tool, at - lo, redirect)
                proof = insert_redirect(original, tool, at - lo, _bash_proof(redirect))
                proving.append((text, original, inserted, proof, redirect,
                                row["command"] if span is not None else None))
            texts = sorted({t for p in proving for t in (p[1], p[2], p[3]) + ((p[5],) if p[5] else ())})
            forms = bash_parsed_forms(texts, bash, drops)
            parsed = dict(zip(texts, forms))
            # a carried row bash rejects proves none of its inner places: counted
            # per carrier, never lost inside a live carrier (the failure-mode
            # review's MINOR 9: a heredoc row in the substitution)
            rejected.update(p[5] for p in proving if p[5] and parsed[p[5]] is None)
            for text, original, inserted, proof, redirect, carried in proving:
                null_by_text[text] = (
                    bash_insertion_is_null(parsed[original], parsed[proof], printed[redirect])
                    and parsed[inserted] is not None and parsed[inserted] == parsed[proof]
                    and (carried is None or parsed[carried] is not None))
        else:
            originals = sorted({c[0]["command"] for c in mine})
            texts = originals + [c[2] for c in mine]
            forms = powershell_parsed_forms(texts, pwsh)
            parsed = dict(zip(texts, forms))
            for row, _at, text, redirect, _span in mine:
                null_by_text[text] = powershell_insertion_is_null(parsed[row["command"]], parsed[text], redirect)

    census = {tool: {"rows": 0, "places": 0, "null": 0, "originals_denied": 0} for tool in tools_run}
    # the carried rows apart, per carrier, so the plain line counts the
    # class's own rows and a carrier the guard never denies is seen (DEF-5126)
    carried_census = {name: {"rows": 0, "places": 0, "null": 0, "originals_denied": 0,
                             "inner": 0, "inner_null": 0, "rejected": 0}
                      for name in R4_CARRIERS}
    carried_undenied: list[str] = []
    null_by_kind: dict[str, int] = {}
    # per (tool, spelling) and (tool, table) over the denied rows' places: a
    # spelling or a table proved null nowhere beside a live one reds, never
    # hides in its tool's total (the failure-mode review's gap 3)
    null_by_part: dict[tuple[str, str], int] = {}
    violations, undenied = [], []
    saved = os.environ.pop("ESPALIER_MAINTENANCE_MODE", None)
    try:
        import powershell_guard_rehearsal as rehearsal
        with cls.built_projects(rehearsal) as projects:
            project = projects["plain"]

            judges = {"_ZONE_ROWS": cls._zone_denied, "_SECRET_ROWS": cls._secret_denied,
                      "_MATRIX": wall._wall_denied}

            def denied(row: dict, text: str) -> bool:
                return judges[row["table"]](row["tool"], text, project)

            by_row: dict[int, list] = {}
            for cand in candidates:
                by_row.setdefault(id(cand[0]), []).append(cand)
            for row in rows:
                if not tools_run[row["tool"]]:
                    continue
                carrier = row.get("carrier")
                stats = census[row["tool"]] if carrier is None else carried_census[carrier]
                stats["rows"] += 1
                mine = by_row.get(id(row), [])
                stats["places"] += len(mine)
                if carrier is not None and row["command"] in rejected:
                    stats["rejected"] += 1
                if not denied(row, row["command"]):
                    if carrier is None:
                        undenied.append(f"{row['key']} on {row['kind']}")
                    else:
                        # outside R4's relation (a denied row stays denied):
                        # counted, never judged (DEF-5126)
                        carried_undenied.append(f"{row['key']} on {row['kind']} in {carrier}")
                    continue
                stats["originals_denied"] += 1
                for _row, _at, text, redirect, span in mine:
                    parts = [(row["tool"], f"spelling {redirect}"), (row["tool"], f"table {row['table']}")]
                    if carrier is not None:
                        parts.append((row["tool"], f"carrier {carrier}"))
                    for part in parts:
                        null_by_part.setdefault(part, 0)
                    inner = carrier is not None and span is not None
                    stats["inner"] = stats.get("inner", 0) + inner
                    if not null_by_text[text]:
                        continue
                    for part in parts:
                        null_by_part[part] += 1
                    stats["null"] += 1
                    stats["inner_null"] = stats.get("inner_null", 0) + inner
                    null_by_kind[row["kind"]] = null_by_kind.get(row["kind"], 0) + 1
                    if not denied(row, text):
                        where = "" if carrier is None else f", in {carrier}"
                        inside = "" if span is None else ", inside the carried program"
                        violations.append({
                            "relation": "R4",
                            "key": row["key"],
                            "tool": row["tool"],
                            "kind": row["kind"],
                            "carrier": carrier,
                            "inside": span is not None,
                            "detail": (f"{row['key']} ({row['tool']}, {row['kind']}{where}, arm "
                                       f"{row.get('arm', '?')}): a stderr redirect the parser reads as "
                                       f"null{inside} lowers the verdict: {text!r}"),
                        })
    finally:
        if saved is not None:
            os.environ["ESPALIER_MAINTENANCE_MODE"] = saved

    dead = [f"{tool}: no denied row has a place the parser proves null -- R4 vouches for nothing there"
            for tool, stats in census.items() if tools_run[tool] and stats["null"] == 0]
    dead += [f"{tool}: no original row is denied on the class's own projects -- the judge is dead"
             for tool, stats in census.items() if tools_run[tool] and stats["originals_denied"] == 0]
    dead += [f"{tool}: the {part} has places on denied rows and the parser proves none null -- "
             "R4 vouches for nothing there"
             for (tool, part), count in sorted(null_by_part.items())
             if count == 0 and census[tool]["null"] > 0]
    # a carrier whose rows the judge never denies, or whose places the parser
    # never proves null, vouches for nothing: it gates as a dead part does
    dead += [f"Bash: no row carried in {name} is denied on the class's own projects -- "
             "R4 vouches for nothing there"
             for name, stats in carried_census.items()
             if tools_run["Bash"] and stats["rows"] and stats["originals_denied"] == 0]
    # the carrier's own outer places stay null if the inner proof breaks, so
    # the inner places gate apart (the failure-mode review's MINOR 3, the
    # code review's M3); and a derived run's carrier holding no row at all is
    # dead too (MINOR 4: a population change can push every row out of it)
    dead += [f"Bash: no place inside a program carried in {name} is proved null -- "
             "R4 vouches for nothing there"
             for name, stats in carried_census.items()
             if tools_run["Bash"] and stats["originals_denied"] and stats["inner_null"] == 0]
    if derived and census["Bash"]["rows"]:
        dead += [f"Bash: no row is carried in {name} -- R4 vouches for nothing there"
                 for name, stats in carried_census.items() if tools_run["Bash"] and not stats["rows"]]
    if drops:
        dead.append(f"Bash: {len(drops)} parsed form(s) dropped as empty or foreign -- a batch went "
                    "wrong past bash's notice, and those places were never judged")
    rejudged = 0
    if quick and derived and violations:
        red = {(v["key"], v["tool"]) for v in violations}
        judged = {(r["key"], r["tool"], r["kind"]) for r in rows if r.get("carrier") is None}
        others = [r for r in operand_rows(quick=False)
                  if (r["key"], r["tool"]) in red and (r["key"], r["tool"], r["kind"]) not in judged]
        if others:
            # each red row's other kinds, plain and carried alike (DEF-5126)
            more = check_r4(quick=False, pwsh=pwsh, rows=others + carried_rows(others)[0])
            violations += more["violations"]
            undenied += more["undenied_originals"]
            carried_undenied += more["carried_undenied"]
            # the inner run's census covers the red rows alone, so a tool
            # with none reads dead there: only its dropped forms carry over
            # (the third code review, S1)
            dead += [d for d in more["dead_separators"] if "dropped" in d]
            rejudged = len(others)
    return {
        "relation": "R4",
        "description": "a stderr redirect among a denied row's operands must not lower its verdict",
        "rows": sum(s["rows"] for s in census.values()),
        "violations": violations,
        "dead_separators": dead,
        "reach_census": {},
        "null_census": {tool: f"{s['null']}/{s['places']} places null over {s['originals_denied']} denied rows"
                        for tool, s in census.items() if tools_run[tool]},
        "carried_rows": sum(s["rows"] for s in carried_census.values()),
        "carried_census": {name: f"{s['null']}/{s['places']} places null ({s['inner_null']}/{s['inner']} "
                                 f"inside the carried program) over {s['originals_denied']} of "
                                 f"{s['rows']} carried rows denied; {s['rejected']} carried rows bash "
                                 f"rejects; {outside_reach[name]} rows outside the view's stated reach, "
                                 "not carried"
                           for name, s in carried_census.items() if tools_run["Bash"]},
        "skipped_tools": [tool for tool, ran in tools_run.items() if not ran],
        "undenied_originals": undenied,
        "carried_undenied": carried_undenied,
        "null_by_kind": null_by_kind,
        "null_by_part": {f"{tool} {part}": count for (tool, part), count in sorted(null_by_part.items())},
        "rejudged_kinds": rejudged,
        "remedy": R4_REMEDY,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true",
                        help="sampled population — for CI, not for a release gate")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--relation", choices=["R1", "R2", "R3", "R4"],
                        help="run one relation")
    parser.add_argument("--root-shape", default="plain", choices=list(ROOT_SHAPES),
                        help="the project root's shape (the rehearsal's ROOT_SHAPES); default plain")
    args = parser.parse_args(argv)

    # The shape holds for this run alone: a later in-process caller of
    # guard_tier (a test) gets plain again.
    global ROOT_SHAPE
    ROOT_SHAPE = args.root_shape
    # R1's real-shell oracle (`bash_reaches`) refuses a row its confinement set
    # cannot prove confined, before bash sees it: the class it raises, read from
    # the module that raises it (the sibling differential's DEF-5085 rule).
    from bench.reachability_differential import UnsafeToExecute
    try:
        assert_instrument_is_live()

        # R1's oracle is a real `/bin/bash`. Stand down rather than crash where it is
        # absent -- the sibling differential does the same (it did not until
        # 2026-09-01; it checked only `which`), and a Windows host has
        # no `/bin/bash` at that exact path even when a shell is installed.
        run_r1 = args.relation in (None, "R1")
        if run_r1 and not (shutil.which("bash") and Path("/bin/bash").exists()):
            print("R1 SKIPPED -- no /bin/bash; R1's ground truth is a real shell.")
            run_r1 = False

        reports = []
        if run_r1:
            reports.append(check_r1(args.quick))
        if args.relation in (None, "R2"):
            reports.append(check_r2(args.quick))
        if args.relation in (None, "R3"):
            reports.append(check_r3(args.quick))
        if args.relation in (None, "R4"):
            # The parsers are R4's oracle for "the redirect is null here", one
            # per tool; a tool without its parser sits out and is named.
            from bench.powershell_reachability_differential import find_powershell
            found = find_powershell()
            reports.append(check_r4(args.quick, found[0] if found else None))
    except BudgetMiss as exc:
        # A judgment that never finished: exit 3, never the violations' 1.
        print(f"NO VERDICT -- {exc}", file=sys.stderr)
        return 3
    except UnsafeToExecute as exc:
        # A row never run is no verdict either: a traceback's exit 1 reads as
        # violations (air's be8e74 (3)).
        print(f"NO VERDICT -- a row the confinement set refuses: {exc}", file=sys.stderr)
        return 3
    finally:
        ROOT_SHAPE = "plain"

    if args.json:
        print(json.dumps({"quick": args.quick, "root_shape": args.root_shape, "reports": reports},
                         indent=2))
    else:
        print(f"root shape: {args.root_shape}")
        for rep in reports:
            print(f"\n{rep['relation']} — {rep['description']}")
            print(f"  population: {rep['rows']} rows", end="")
            if rep.get("carried_rows"):
                print(f" (+{rep['carried_rows']} carried)", end="")
            if "reaching" in rep:
                print(f"  ({rep['reaching']} reach the delete)", end="")
            print()
            if rep.get("reach_census"):
                census = "  ".join(f"{k}={v}" for k, v in rep["reach_census"].items())
                print(f"  reach by separator: {census}")
            for dead in rep["dead_separators"]:
                print(f"  ✗ DEAD POPULATION — {dead}")
            for dead in rep.get("dead_heads", ()):
                print(f"  ✗ DEAD HEAD — {dead}")
            if rep.get("absent_heads"):
                print(f"  absent on this platform (not counted): "
                      f"{', '.join(rep['absent_heads'])}")
            for tool, line in rep.get("null_census", {}).items():
                print(f"  {tool}: {line}")
            for carrier, line in rep.get("carried_census", {}).items():
                print(f"  Bash in {carrier}: {line}")
            if rep.get("carried_undenied"):
                print(f"  {len(rep['carried_undenied'])} carried row(s) not denied here (outside R4's "
                      f"relation, counted and never judged): {', '.join(rep['carried_undenied'][:5])}")
            for tool in rep.get("skipped_tools", ()):
                print(f"  {tool} SKIPPED -- its parser is not on this host; its rows are not judged here")
            if rep.get("undenied_originals"):
                print(f"  {len(rep['undenied_originals'])} original row(s) not denied here "
                      f"(the class's own pin, not R4's): {', '.join(rep['undenied_originals'][:5])}")
            if not rep["violations"]:
                print("  no violations")
            for v in rep["violations"]:
                print(f"  ✗ [{v['relation']}] {v['detail']}")
            if rep.get("rejudged_kinds"):
                print(f"  the red rows' other {rep['rejudged_kinds']} kind(s) judged too, listed above")
            if rep["violations"] and rep.get("remedy"):
                print(f"  {rep['remedy']}")
        total = sum(len(r["violations"]) for r in reports)
        print(f"\ntotal violations: {total}")

    # ⚠ A DEAD SEPARATOR GATES, it does not merely warn. A row that never
    # reaches the delete cannot register a violation, so a matrix that stopped
    # executing would exit 0 having validated nothing -- the "comforting zero"
    # this file's docstring narrates. The mechanism is only mechanised if it
    # reaches the return value.
    if any(r["dead_separators"] for r in reports):
        return 1
    # A DEAD HEAD gates for the same reason: a present head whose `&&` row
    # never reaches has certified nothing about the guard behind it.
    if any(r.get("dead_heads") for r in reports):
        return 1
    return 1 if any(r["violations"] for r in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
