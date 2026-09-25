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

RUNNING IT
----------
::

    python3 bench/guard_metamorphic.py            # both relations
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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HOOKS_DIR))

import _bash_patterns  # noqa: E402  (path is set immediately above)

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
                    {"tool_name": tool, "tool_input": {"command": command}}
                ),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, env=env,
            )
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
    `echo`) has no PATH entry, so `shutil.which` alone would call it absent."""
    if head in _SHELL_BUILTIN_HEADS:
        # a builtin has no PATH entry and, on a Windows runner, the bash
        # group below answered non-zero for `cd` and `echo` and called them
        # absent (Portability, 2026-09-23); the shell's own builtins are
        # present wherever the shell is
        return True
    if not shutil.which("bash"):
        return True  # no shell to ask; never classify as absent on a guess
    from bench.reachability_differential import run_bash_group
    rc, _timed_out = run_bash_group(
        ["bash", "-c", 'command -v -- "$1" > /dev/null 2>&1', "_", head], timeout=10,
    )
    return rc == 0


def _spelling_rc(head: str) -> int | str:
    """Drive the head's spelling once more, in a scratch cwd, for the exit code
    the dead message carries: a dead spelling and a missing precondition look
    the same in a boolean and different in an rc."""
    from bench.reachability_differential import run_bash_group
    rc, timed_out = run_bash_group(
        ["/bin/bash", "-c", _prefix_for(head)],
        cwd=tempfile.mkdtemp(prefix="gm-dead-"), timeout=10,
    )
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true",
                        help="sampled population — for CI, not for a release gate")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--relation", choices=["R1", "R2", "R3"],
                        help="run one relation")
    args = parser.parse_args(argv)

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

    if args.json:
        print(json.dumps({"quick": args.quick, "reports": reports}, indent=2))
    else:
        for rep in reports:
            print(f"\n{rep['relation']} — {rep['description']}")
            print(f"  population: {rep['rows']} rows", end="")
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
            if not rep["violations"]:
                print("  no violations")
            for v in rep["violations"]:
                print(f"  ✗ [{v['relation']}] {v['detail']}")
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
