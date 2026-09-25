"""The harness-env-prefix guard must refuse the inert form, not the working one.

TWO different things are refused here, for two different reasons, and conflating
them is what produced both the original defect and a wrong first fix.

1. INERT forms — a bare `VAR=1`, or `VAR=1 && cmd` / `VAR=1 ; cmd` where the
   variable is not passed past the separator. Nothing is reached. This half is a
   habit-formation nudge (docs/STANDING_PRINCIPLES.md §2 — friction guard, not
   adversary boundary).
2. `VAR=1 claude` — a REAL reach, and the reason this record is a
   bench/corpus/BC-028 bypass class. A nested session starts with the
   protected-zone check already bypassed, so an in-session actor can spawn an
   ungoverned agent to edit the files this hook protects.

What was wrong before: the guard also denied `VAR=1 pytest -q` and
`VAR=1 python3 <hook>`, where the variable genuinely reaches that process and
loosens nothing — the write_guard decision for that tool call is already made
before the command runs. That blocked the canonical maintenance loop (edit a
hook, then run it to see whether the edit worked), which is the workflow
maintenance mode exists to serve. The repo's own tests never felt it because they
pass an env dict to subprocess, so the suite stayed green while the operator was
blocked.

⚠ THE TRAP, worth more than the fix. The deny message says "Do: relaunch with
`ESPALIER_MAINTENANCE_MODE=1 claude --continue`", so the guard denying that exact string
reads as self-contradiction — and a first fix carved `claude` OUT on that basis,
removing a real bypass guard. It is not a contradiction: that advice is for the
OPERATOR in their own terminal, where no hook is watching. The same string typed
as a Bash tool call is an in-session actor spawning an ungoverned session. A deny
whose remedy looks self-contradictory may be distinguishing WHO is acting, not
contradicting itself. Caught by the release-gating benchmark (150/153), not by
review.

PowerShell was the worse instance and made it a class (the same shape as the
recursive-delete deny messages): it carried the inversion AND lacked the
command-position anchoring the Bash twin has always had, so a bare prose mention
denied on Windows while the identical Bash sentence was allowed.

`export VAR=1` WAS a known gap and is now closed — see
`test_export_and_declare_forms_are_matched`. (This paragraph used to say, in the
present tense, that it "is not matched at all", which contradicted that test in
the same file. Stale since the verbs were added; corrected 2026-08-23.)

⚠ THE ANCHOR IS SHARED, AND WHICH HALF OF IT YOU TAKE MATTERS. This record
matches an ASSIGNMENT, so it composes `_bash_patterns._CMD_POS_NO_VERB`, not the
full `_CMD_POS`. The difference is `_CMD_POS_VERB_PREFIX`'s optional quote, which
exists for a quoted VERB (`$'cp'`) and has no counterpart for an assignment —
`'VAR'=1` assigns nothing in any shell. Taking the full `_CMD_POS` makes `(` + `'`
a command position, and `(` is a separator, so a read-only
`python3 -c "...search('ESPALIER_MAINTENANCE_MODE=1')"` was hard-denied. Measured
live, not reasoned.

⚠ AND THE OBVIOUS FIX FOR THE PROSE FALSE POSITIVE IS NET-NEGATIVE. Deleting
`export|declare` from the unanchored branch — rather than anchoring it — scored
12/16 against the two-branch form's 14/16 on a driven matrix, because it allows
`bash -c "export VAR=1; claude"`. `export VAR=1 claude` is inert;
`export VAR=1; claude` is a real reach; they differ by one character, and only a
command-position notion tells them apart.
"""
# slow-exempt: pure in-process regex/dispatch calls, no child processes.
from __future__ import annotations

import contextlib
import io

import pytest

from tools.cc.hooks import write_guard as wg
from tools.cc.hooks._maintenance_mode import ENV_VAR

STOP = "ESPALIER_STOP_GATE"


def _denies(fn, command: str) -> bool:
    """True when the dispatch denies. Captures stdout: a deny is emitted as
    permission JSON there, and letting it escape would corrupt pytest output."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn({"command": command})
    return bool(rc) or '"deny"' in buf.getvalue()


# ── Bash ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("command", [
    f"{ENV_VAR}=1 pytest -q",
    f"{ENV_VAR}=1 python3 tools/cc/hooks/write_guard.py",
    f"env {ENV_VAR}=1 pytest -q",
    f"{ENV_VAR}=1 {STOP}=full pytest",                  # chained assignments
    f"cat notes.md && {ENV_VAR}=1 pytest",              # after a separator
    # The prefix shapes tests/test_hooks.py pins on their INERT form. Their
    # command-position anchoring is still exercised there (each still asserts a
    # deny); these are the matching invoking forms, so the allow side of every
    # shape stays covered and the split cannot silently lose a case.
    f"/usr/bin/env {ENV_VAR}=1 pytest",
    f"sudo {ENV_VAR}=1 pytest",
    f"env -i {ENV_VAR}=1 pytest",
    f"ENV=x {ENV_VAR}=1 pytest",
    f"foo; {ENV_VAR}=1 bar",
    f'echo "$({STOP}=full pytest)"',                    # command substitution
    f"{STOP}=full pytest -q",                           # bare STOP prefix at start
    # A substring test for "claude" would deny this and re-block the maintenance
    # loop for every test file with `claude` in its name; the predicate is
    # basename-keyed precisely so it does not.
    f"{ENV_VAR}=1 pytest tests/test_folder_claude_md_routers.py",
    # The variable does NOT cross a `;` in bash, so a later `claude` is somebody
    # else's business and must not make this deny.
    f"{ENV_VAR}=1 pytest; claude",
    # DEF-848's lane: a further assignment whose quoted value holds a blank is
    # one word, and the invocation after it is read (the shared value grammar)
    f"{ENV_VAR}=1 MSG='a b' pytest -q",
    f"{ENV_VAR}='1' pytest -q",
])
def test_bash_env_prefix_on_a_real_invocation_is_allowed(command):
    assert not _denies(wg.check_bash_dangerous_patterns, command), (
        f"{command!r} passes the variable to the invoked process — denying it "
        f"refuses a form that works, and blocks the maintenance loop"
    )


@pytest.mark.parametrize("command", [
    f"{ENV_VAR}=1",                 # invokes nothing
    f"{ENV_VAR}=1 && pytest",       # `&&` does NOT pass the var on
    f"{ENV_VAR}=1 ; pytest",        # nor does `;`
    f"{STOP}=full",
    # A backslash-newline before `=` is ONE assignment to bash; the hard-deny
    # tier did not splice and let the nested launch through (DEF-701).
    f"{ENV_VAR}\\\n=1 claude",
    # THE REACH, not pedagogy: a nested session starts with the protected-zone
    # check already bypassed, so an in-session actor could spawn an ungoverned
    # agent to edit the files this hook protects. bench/corpus/BC-028 classifies
    # this as a bypass class.
    f"{ENV_VAR}=1 claude",
    f'{ENV_VAR}=1 claude -p "rewrite write_guard.py"',
    f"{ENV_VAR}=1 /usr/local/bin/claude -p x",
    f"env {ENV_VAR}=1 claude",
    f"{ENV_VAR}=1 {STOP}=light claude",
    # WRAPPERS. A first-word denylist shut only 3 of 16 spellings; every one of
    # these delivered the variable. Enumerating wrappers is a finite list over an
    # open domain, so the predicate is a basename token scan instead -- these are
    # the witnesses that it stayed closed under them, not the definition.
    f"{ENV_VAR}=1 npx claude -p x",
    f"{ENV_VAR}=1 nohup claude -p x",
    f"{ENV_VAR}=1 exec claude -p x",
    f"{ENV_VAR}=1 env claude -p x",
    f"{ENV_VAR}=1 command claude -p x",
    f"{ENV_VAR}=1 time claude -p x",
    f"{ENV_VAR}=1 xargs claude",
    f"{ENV_VAR}=1 sh -c 'claude -p x'",
    f"{ENV_VAR}=1 $(which claude) -p x",
    # Case variant: `command -v CLAUDE` resolves on a case-insensitive
    # filesystem (APFS/NTFS), so this is the same binary.
    f"{ENV_VAR}=1 CLAUDE -p x",
    # MULTI-OCCURRENCE. A benign first assignment must not license an inert
    # second one -- "run the tests, then arm the gate for next time".
    f"{ENV_VAR}=1 pytest; {STOP}=full",
    f"{ENV_VAR}=1 pytest && {STOP}=full",
    f"{STOP}=full pytest; {ENV_VAR}=1",
    # DEF-848's lane: a second assignment is not the command it prefixes,
    # and neither is a word inside a quoted value -- the target pattern
    # backtracked onto the second assignment's NAME, and ended a quoted value
    # at its first blank, and read either as an invocation (allowed, inert)
    f"{ENV_VAR}=1 X=1; pytest",
    f"{ENV_VAR}=1 MSG='a b'; pytest",
])
def test_bash_env_prefix_inert_or_nested_launch_still_denies(command):
    assert _denies(wg.check_bash_dangerous_patterns, command), (
        f"{command!r} is either inert or a nested-session launch — the two forms "
        f"this record exists for. Losing the `claude` case reopens a real bypass "
        f"(BC-028); losing the inert case empties the nudge."
    )


@pytest.mark.parametrize("command", [
    f"echo 'set {ENV_VAR}=1 before launching'",
    f"git commit -m 'document {ENV_VAR}=1 usage'",
    "FOO=1 pytest -q",
])
def test_bash_prose_and_unrelated_vars_are_allowed(command):
    assert not _denies(wg.check_bash_dangerous_patterns, command)


# ── PowerShell ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("command", [
    f"$env:{ENV_VAR}='1'; pytest -q",
    "$env:FOO=1; pytest",
])
def test_powershell_env_prefix_on_a_real_invocation_is_allowed(command):
    assert not _denies(wg.check_powershell, command)


@pytest.mark.parametrize("command", [
    f"$env:{ENV_VAR}='1'",
    f"Set-Item Env:\\{ENV_VAR} 1",
    f"$env:{ENV_VAR}=1; claude",            # the nested-session reach
    f"$env:{ENV_VAR}=1; claude -p x",
    # `$env:` mutates the RUNNING PowerShell process, so unlike a bash prefix the
    # variable reaches every later statement -- a wrapper or a distant statement
    # is still a real launch.
    f"$env:{ENV_VAR}=1; npx claude",
    f"$env:{ENV_VAR}=1; pytest; claude",
    # STATED COST, not an oversight: the carve-out is scoped to the anchored
    # `$env:` arm, so the cmdlet spelling of the maintenance loop keeps denying.
    # The alternative was handing the unanchored arms an accidental anchor made
    # of punctuation, where the same prose is refused or allowed on whether it
    # contains a `;`. This matches HEAD for these arms (no regression), and the
    # idiomatic `$env:` form above is carved out.
    f"Set-Item Env:\\{ENV_VAR} 1; pytest",
])
def test_powershell_env_prefix_inert_or_nested_launch_still_denies(command):
    assert _denies(wg.check_powershell, command)


@pytest.mark.parametrize("suffix", ["first'", "; then pytest'"])
def test_set_item_prose_decision_does_not_depend_on_a_semicolon(suffix):
    """The unanchored arms must not acquire an accidental anchor made of
    punctuation. Before the carve-out was scoped to the `$env:` arm, the same
    Set-Item prose was refused or allowed purely on whether the sentence happened
    to contain a `;`. Both spellings must land the same way."""
    command = f"Write-Host 'use Set-Item Env:\\{ENV_VAR} 1 {suffix}"
    assert _denies(wg.check_powershell, command), command


def test_powershell_prose_mention_is_allowed_like_its_bash_twin():
    """The sister-site gap: PowerShell lacked the command-position anchor, so
    documenting this footgun was refused on one platform only."""
    ps = f"Write-Host 'set $env:{ENV_VAR}=1 first'"
    bash = f"echo 'set {ENV_VAR}=1 first'"
    assert not _denies(wg.check_powershell, ps)
    assert not _denies(wg.check_bash_dangerous_patterns, bash), (
        "control: the Bash twin must still allow prose — if this reds, the "
        "comparison the PowerShell assertion rests on is meaningless"
    )


def test_powershell_remove_item_prose_is_allowed():
    """write_guard's STATED-COST note above `_PS_HARNESS_ENV_PREFIX_RE` once said
    the Remove-Item records carried a prose false positive and that a strict
    xfail in this file pinned it; driven 2026-09-14, the prose ALLOWS and no such
    xfail exists. This pins the driven verdict (a state, clean at HEAD) so the
    note's pin claim has a test behind it."""
    assert not _denies(wg.check_powershell, 'Write-Output "use Remove-Item to delete"')


# ── the carve-out must not leak to any other record ─────────────────────────

@pytest.mark.parametrize("fn,command", [
    (wg.check_bash_dangerous_patterns, "rm -rf /"),
    (wg.check_bash_dangerous_patterns, "rm -rf /*"),
    (wg.check_powershell, "Remove-Item -Recurse -Force C:\\Windows"),
])
def test_unrelated_hard_denies_still_fire(fn, command):
    """`continue` in the dispatch loop skips only the env-prefix record. If the
    pid gate were wrong, a catastrophic pattern could fall through it."""
    assert _denies(fn, command)


def test_env_prefix_pid_roster_is_derived_and_covers_both_shells():
    """§14 — derive the list. A new shell's env-prefix record must be enrolled by
    its pid, not by someone remembering to add it here."""
    assert wg._ENV_PREFIX_PIDS == {"harness-env-prefix", "ps-harness-env-prefix"}, (
        f"roster drifted: {wg._ENV_PREFIX_PIDS}. It is derived from pids ending "
        f"in 'harness-env-prefix' across both pattern tuples."
    )


def test_export_and_declare_forms_are_matched():
    """Was pinned as an accepted gap; that pin was a green negative-twin.

    `export VAR=1; claude` delivers byte-identical reach to the plain prefix this
    record refuses as a real bypass, so accepting `export` while denying the
    plain form meant the guard shipped a passing test proving the opposite of its
    own contract. Both `export` and `declare -x` are now matched, which closes the
    detour and the inert form together.
    """
    for command in (
        f"export {ENV_VAR}=1",
        f"declare -x {ENV_VAR}=1",
        f"export {ENV_VAR}=1; claude -p x",
        f"declare -x {ENV_VAR}=1; claude -p x",
    ):
        assert _denies(wg.check_bash_dangerous_patterns, command), command


# ── The command-position anchor on the assignment record ────────────────────
# Every case below is driven through `check_bash_dangerous_patterns`, the real
# dispatch, rather than against `_HARNESS_ENV_PREFIX_RE`. A regex-level
# assertion here would pin the PATTERN and never the WIRING, which is the exact
# shape of two inert regression tests this repo shipped in one prior session.


@pytest.mark.parametrize("command", [
    # The reported defect: prose about the guard, refused by the guard. This
    # tier dispatches before the maintenance gate, so the deny had no lever.
    f'git commit -m "docs: drop export {STOP}=full"',
    f'git commit -m "docs: never export {ENV_VAR}=1 mid-session"',
    f"echo 'do not declare {ENV_VAR}=1 inline'",
    f"command grep -rn 'export {STOP}=full' docs/",
    # A quoted assignment sitting after `(`. `(` IS a command separator, so this
    # allows only because an assignment record must not treat a following quote
    # as a verb prefix. Regressing to the full `_CMD_POS` reds this row.
    f"""python3 -c "print(RE.search('{ENV_VAR}=1'))" """,
    f"""python3 -c 'print(re.search("{ENV_VAR}=1", s))' """,
])
def test_quoted_mention_is_not_a_command_position(command):
    """Prose ABOUT the rule must not be read as an invocation OF it."""
    assert not _denies(wg.check_bash_dangerous_patterns, command), command


@pytest.mark.parametrize("command", [
    # A shell-exec wrapper opens a real command position inside its quoted
    # argument, and the exported variable is inherited by the agent it then
    # launches. Deleting the verbs from the pattern — the tempting fix for the
    # false positives above — allows all three.
    f'bash -c "export {ENV_VAR}=1; claude -p x"',
    f"sh -c 'export {STOP}=full; claude'",
    f'eval "export {ENV_VAR}=1; claude"',
    # Wrapper-prefixed launch. The hand-rolled two-branch anchor enumerated its
    # own wrapper list and missed this; the shared anchor carries the roster.
    f"nohup {ENV_VAR}=1 claude",
    f"command {ENV_VAR}=1 claude",
])
def test_reaching_forms_behind_a_wrapper_still_deny(command):
    """A form that genuinely delivers the variable to the agent binary."""
    assert _denies(wg.check_bash_dangerous_patterns, command), command


@pytest.mark.parametrize("command", [
    # A backslash-newline JOINS these two physical lines, so the agent launch is
    # part of the same statement as the assignment and the variable reaches it.
    f"{ENV_VAR}=1 \\\nclaude -p 'go'",
    f"{ENV_VAR}=1 \\\nnohup claude -p 'go'",
    f"{STOP}=full \\\nclaude",
    # CRLF spelling of the same continuation.
    f"{ENV_VAR}=1 \\\r\nclaude",
])
def test_line_continuation_does_not_hide_the_launch(command):
    """bench/corpus/BC-028-a3.

    Splitting the tail on a bare newline made `VAR=1 \\<nl>claude` look like the
    statement `1 \\` — a trailing backslash satisfies the "invokes something"
    target regex — so the occurrence was judged benign and the `claude` on the
    joined line was never inspected. The benchmark reported green throughout,
    because no corpus attempt spelled the reach this way.
    """
    assert _denies(wg.check_bash_dangerous_patterns, command), command


@pytest.mark.parametrize("command", [
    # A BARE newline between two statements IS a boundary, and each of these is
    # an independently benign prefixed command. The fix must not re-block the
    # multi-line maintenance loop, which is what dropping `\n` from the
    # statement split (the other candidate) was measured to do.
    f"{ENV_VAR}=1 pytest -q\n{ENV_VAR}=1 python3 tools/cc/hooks/write_guard.py",
    f"{ENV_VAR}=1 pytest -q\n{ENV_VAR}=1 ruff check .",
])
def test_bare_newline_between_statements_is_still_a_boundary(command):
    """The continuation splice must not swallow real statement separation."""
    assert not _denies(wg.check_bash_dangerous_patterns, command), command


def test_continuation_splice_has_one_owner():
    """§8 — the concept is owned by `_bash_patterns`, not inlined twice.

    Both consumers that segment a command on newlines must splice through the
    same helper. They had already drifted: `iter_rm_invocations` spliced with an
    inline `re.sub` while `_occurrence_is_benign` did not splice at all, which is
    the bypass above.
    """
    from tools.cc.hooks import _bash_patterns as bp

    assert bp.splice_line_continuations("a \\\nb") == "a b"
    # ⚠ CRLF IS NOT A CONTINUATION, AND THIS ROW USED TO ASSERT THAT IT WAS.
    # Driven against /bin/bash and read back with `od -c`, `echo a\\<CR><LF>echo b`
    # emits `a \\r \\n b` -- TWO commands, because the backslash escapes the
    # carriage return and the newline stays live. Splicing invented a statement
    # bash never runs and it cost a fail-open: `echo a\\<CR><LF><delete> /` really
    # deleted while the guard, seeing one spliced `echo`, allowed it.
    #
    # The escaped CR is dropped and the SEPARATOR kept, which is what serves
    # both consumers -- the delete above stays denied, and
    # `test_line_continuation_does_not_hide_the_launch` still denies the CRLF
    # launch because the env prefix and the launch are still on either side of a
    # newline rather than behind a trailing backslash.
    #
    # This corrects a premise; it does not relax a check. The must-deny half is
    # STRENGTHENED in the same change by `crlf-is-not-a-continuation` in
    # tests/test_guard_false_positives.py::GENUINE_BASH.
    assert bp.splice_line_continuations("a \\\r\nb") == "a \nb"
    # a bare newline is NOT a continuation and must survive
    assert bp.splice_line_continuations("a\nb") == "a\nb"


def test_shared_anchor_is_split_not_copied():
    """§8 — one anchor, two entry points; never a divergent second copy.

    `_CMD_POS` must remain exactly `_CMD_POS_NO_VERB` plus the verb prefix, so
    the ~13 verb-matching consumers see a byte-identical pattern and only the
    assignment-matching consumers take the shorter form. If someone edits one
    half into a rival spelling, this reds instead of the drift shipping.
    """
    from tools.cc.hooks import _bash_patterns as bp

    assert bp._CMD_POS == bp._CMD_POS_NO_VERB + bp._CMD_POS_VERB_PREFIX
    assert wg._HARNESS_ENV_PREFIX_RE.pattern.startswith(bp._CMD_POS_NO_VERB)
    assert not wg._HARNESS_ENV_PREFIX_RE.pattern.startswith(bp._CMD_POS), (
        "the assignment record took the verb-prefix form; that re-opens the "
        "quoted-assignment-after-a-paren false positive"
    )


# ── the target spelling is a DERIVED population, not one hand-written word ───
#
# ⚠ THE DEFECT THIS SECTION EXISTS FOR. `_statement_launches_claude` normalised
# three ways a target can be written — a directory prefix (`./claude`,
# `bin/claude`), a surrounding quote (`"claude"`), and letter case (`CLAUDE`, for
# the case-insensitive filesystems the code comment reasons about) — and missed
# the fourth: an EXECUTABLE SUFFIX. Every Windows spelling carries one. Driven
# 2026-08-26 against the real hook, 6 of 7 spellings of the launch walked
# through, and the npm shim on Windows is literally `claude.cmd`, so on the
# platform the code comment names the guard caught nothing at all.
#
# This is the same shape as `bench/corpus/BC-028`'s three canonical attempts,
# which all spell the target bare `claude`: a population written by hand where a
# normaliser already existed. The fix belongs in the normaliser, so the roster
# below is the WITNESS that it stayed closed under these spellings, never the
# definition — exactly as the wrapper rows above say of themselves.

#: Windows PATHEXT members that really carry the CLI, plus PowerShell's own.
#: ⚠ `.com` is DELIBERATELY EXCLUDED and this is a declared trade, not an
#: oversight: stripping it makes `curl https://claude.com` read as a launch, and
#: under docs/STANDING_PRINCIPLES.md §2 a false positive on ordinary work outranks
#: a bypass spelling nobody ships. If a `.com` build ever exists, add it here and
#: accept the URL cost knowingly.
_WINDOWS_LAUNCHER_SUFFIXES = (".exe", ".cmd", ".bat", ".ps1")


@pytest.mark.parametrize("spelling", [
    *(f"claude{s}" for s in _WINDOWS_LAUNCHER_SUFFIXES),
    "CLAUDE.EXE",            # case-insensitive FS, upper spelling
    "Claude.Exe",            # and the mixed one a Windows shell tab-completes
    "./claude.cmd",          # suffix AND a directory prefix, both normalisers
    "C:/tools/claude.exe",
])
def test_windows_launcher_spellings_are_the_same_reach(spelling):
    """A suffixed launcher is the identical nested-session reach as bare
    `claude`; only the spelling differs. RED before 2026-08-26."""
    assert _denies(wg.check_bash_dangerous_patterns, f"{ENV_VAR}=1 {spelling}"), (
        f"{spelling!r} is the Windows spelling of the BC-028 reach"
    )


@pytest.mark.parametrize("spelling", ["$'claude'", "$'cl'$'aude'"])
def test_ansi_c_quoted_target_is_the_same_reach(spelling):
    """`$'...'` is a QUOTE form, so it belongs to the normaliser that already
    strips `"` and `'` — `.strip("\\"'")` left `$'claude` and missed it.

    ⚠ BOUNDARY, stated rather than implied: this covers the quote CHARACTERS
    only. `$'\\x63laude'` decodes an ESCAPE after the regex has run and stays
    out of scope with the rest of its class (`bench/corpus/BC-OOS-004`)."""
    assert _denies(wg.check_bash_dangerous_patterns, f"{ENV_VAR}=1 {spelling}")


@pytest.mark.parametrize("command", [
    # ⚠ THE REGRESSION THIS GUARDS. The comment above `_CLAUDE_BASENAME` records
    # that a substring test denied `pytest tests/test_folder_claude_md_routers.py`
    # and re-blocked the maintenance loop for every test file with `claude` in its
    # name — this repo has several. Widening the normaliser must not re-open it.
    f"{STOP}=full pytest tests/test_folder_claude_md_routers.py",
    f"{STOP}=full pytest tests/claude.py",          # a source suffix is NOT a launcher
    f"{ENV_VAR}=1 pytest tests/claude.md",
    f"{ENV_VAR}=1 curl https://claude.com",         # the declared `.com` trade
])
def test_non_executable_suffixes_are_not_a_launch(command):
    assert not _denies(wg.check_bash_dangerous_patterns, command), (
        "the suffix roster must cover launchers only; a source or document "
        "extension that happens to sit on a `claude`-named file is ordinary work"
    )


@pytest.mark.parametrize("spelling", ["claude.exe", "claude.cmd", "$'claude'"])
def test_powershell_target_spellings_share_the_bash_normaliser(spelling):
    """§8 — `_ps_occurrence_is_benign` calls the SAME `_statement_launches_claude`,
    so one fix closes both shells. This row is what proves the sharing is real
    rather than assumed: if someone forks a PowerShell copy, it reds."""
    assert _denies(wg.check_powershell, f"$env:{ENV_VAR}=1; {spelling}")


# ── the PowerShell anchor must be DERIVED, not a hand-inlined copy ───────────
#
# ⚠ `_PS_CMD_POS` is `_PS_CMD_POS_SEP | _PS_CMD_POS_EXEC_QUOTE`, and the
# exec-quote arm exists SPECIFICALLY to keep `Invoke-Expression "..."` fail-closed
# — `_bash_patterns.py` says so where the arm is defined. The env-prefix record
# hand-inlined `(?:^|[;&|\n({])[ \t]*` instead of composing `_PS_CMD_POS`, so it
# had no exec-quote arm at all, and its hand-written separator class also dropped
# `\r`, `)`, `}` and `=`.
#
# `tests/test_guard_false_positives.py` already pins `iex-double` / `iex-alias` as
# must-deny FOR THE REMOVE-ITEM RECORDS. The answer was in the repo; it was never
# applied to the second record. STANDING_PRINCIPLES §14.

# ── a re-parsed span is live -- but only when it is LITERAL ─────────────────
#
# ⚠ THIS BLOCK ASSERTED THE OPPOSITE UNTIL 2026-08-26, AS FIVE `xfail(strict=True)`
# ROWS, AND THE WHOLE PREMISE WAS WRONG. It was filed as "a re-parsing wrapper's
# span is live, so `iex \"$env:<VAR>=1; claude\"` is a fail-open the mask hides".
# Every PowerShell verdict in this repo had been a hand-written expectation about
# a language nobody ran; PowerShell was installed on this machine for the first
# time on 2026-08-26 and refuted it in one command.
#
# Driven against real pwsh 7.6.5, writing a marker file from inside the span:
#
#     iex '$env:<VAR>=1; <cmd>'        LITERAL       -> RUNS
#     iex @'...'@                      LITERAL       -> RUNS
#     Invoke-Command -ScriptBlock { }  script block  -> RUNS
#     iex "$env:<VAR>=1; <cmd>"        EXPANDABLE    -> sets NOTHING (see below)
#     pwsh -c "$env:<VAR>=1; <cmd>"    EXPANDABLE    -> ParserError
#
# A double-quoted PowerShell string is EXPANDABLE: `$env:<VAR>` is interpolated
# at PARSE time, before the re-parser is handed the string, so the assignment is
# gone and nothing is set. Denying it would refuse a command that provably does
# not set the variable -- the guard was right and the reported gap did not exist.
#
# ⚠ RE-DRIVEN 2026-09-10 (DEF-753), AND THE 08-26 READING WAS HALF RIGHT. Those
# runs had <VAR> SET in the ambient shell (this is the self-host, relaunched in
# maintenance mode), so the re-parser received `1=1; <cmd>` -- a parse error,
# nothing ran. With <VAR> UNSET, the adopter's case, it receives `=1; <cmd>`:
# `=1` is an unknown command name and <cmd> RUNS, without the variable. Either
# way the assignment never happens, which is what this record guards, so the
# verdict below stands -- but the SEPARATOR after an interpolated token is
# live, and the masker no longer blanks it (only the `=` bound to the token).
#
# ⚠ The delete records are unaffected and that asymmetry is not a contradiction:
# `Remove-Item -Recurse -Force` carries no `$`, so there is nothing to
# interpolate and an expandable span really does deliver it. The rule is about
# the PAYLOAD's leading token, not about the quote.

@pytest.mark.parametrize("wrapper", [
    "iex '{body}'",
    "Invoke-Expression '{body}'",
    "iex @'\n{body}\n'@",
    "Invoke-Command -ScriptBlock {{ {body} }}",
    # DEF-717: the same literal span behind a valued switch. The lookbehind's
    # switch run could not cross `RunAs`, so this span was blanked as inert.
    "Start-Process powershell -Verb RunAs -ArgumentList '{body}'",
])
def test_a_literal_reparsed_span_is_a_live_command_position(wrapper):
    """These spellings really execute; the guard must refuse them.

    RED before 2026-08-26: the masking pass blanked the `=` and `;` inside every
    quoted span, so the record scanned an assignment with no assignment in it.
    """
    command = wrapper.format(body=f"$env:{ENV_VAR}=1; claude")
    assert _denies(wg.check_powershell, command), command


@pytest.mark.parametrize("wrapper", [
    'iex "{body}"',
    'Invoke-Expression "{body}"',
    'powershell -Command "{body}"',
    'pwsh -c "{body}"',
    'cmd /c "{body}"',
    # DEF-717: crossing a valued switch must not change the polarity rule --
    # an expandable span behind `-ExecutionPolicy Bypass` interpolates the
    # variable away exactly as the bare `-Command` form does.
    'powershell -ExecutionPolicy Bypass -Command "{body}"',
    'Start-Process powershell -Verb RunAs -ArgumentList "{body}"',
])
def test_an_expandable_reparsed_span_is_inert_for_a_variable_payload(wrapper):
    """⚠ A MUST-ALLOW ROW THAT WAS A MUST-DENY XFAIL, corrected by measurement.

    Not a relaxation: driven against real pwsh, none of these sets the
    variable (with it unset the command after the separator does run, without
    it -- see the block above). A guard that denied them would be refusing an
    assignment that provably never happens, which is the friction half of the
    same edit. Since DEF-753 the masker keeps the rest of such a span live
    and blanks only the `=` bound to the interpolated token, so this row is
    the pin that keeps that one blank in place.
    """
    command = wrapper.format(body=f"$env:{ENV_VAR}=1; claude")
    assert not _denies(wg.check_powershell, command), command


def test_an_expandable_span_still_denies_a_payload_with_nothing_to_interpolate():
    """The control that keeps the row above from being read too widely: the
    relief is about `$`-led payloads, never about the quote character."""
    assert _denies(wg.check_powershell,
                   'Invoke-Expression "Remove-Item -Recurse -Force C:\\"')


@pytest.mark.parametrize("separator", ["\r", ")", "}", "="])
def test_powershell_hand_written_separator_class_dropped_four_members(separator):
    """The four `_PS_CMD_POS_SEP` members the hand-inlined class omitted."""
    command = f"$x{separator}$env:{ENV_VAR}=1; claude"
    assert _denies(wg.check_powershell, command), command


@pytest.mark.parametrize("command", [
    # ⚠ THE RISK THE DERIVATION CARRIES, pinned as a control. `_PS_CMD_POS_SEP`
    # admits `=` as a command position (a PowerShell assignment really does run
    # the right-hand side), so composing it could re-block the ordinary mention
    # `$pattern = "$env:VAR=1"`. It must not: the quote sits between the `=` and
    # the token and `[ \t]*` cannot cross it. Driven, not reasoned — the same
    # relief `_bash_patterns` claims for the Remove-Item records, asserted here
    # for this one.
    '$pattern = "$env:{v}=1"',
    "$pattern = '$env:{v}=1; claude'",
    "Write-Host \"launch with $env:{v}=1 from the parent shell\"",
    "# $env:{v}=1; claude",
])
def test_powershell_quoted_mention_survives_the_derived_anchor(command):
    assert not _denies(wg.check_powershell, command.format(v=ENV_VAR)), command


def test_powershell_anchor_is_derived_not_hand_inlined():
    """§14 — derive the list, don't test a hand-written copy of it.

    A structural pin, not a behavioural one: behavioural rows only catch the
    spellings someone thought of, and the whole defect was a spelling nobody did.
    If a future edit re-inlines a separator class, this reds on the spot.
    """
    from tools.cc.hooks import _bash_patterns as bp

    assert bp._PS_CMD_POS in wg._PS_HARNESS_ENV_PREFIX_RE.pattern, (
        "the `$env:` arm must COMPOSE `_PS_CMD_POS`, not restate part of it — "
        "the hand-inlined class had no exec-quote arm and dropped four separators"
    )
