"""Command-position anchoring — the measured shape matrix, encoded as a gate.

This file IS the gate for the guard-precision class close. It exists because the
class's real population is a SHAPE axis, not a verb axis: the same write verb
behaves differently depending on whether it sits at a command position, inside a
quoted argument, behind a wrapper, or inside a substitution. A verb-only matrix
cannot see that, and the release-gating benchmark cannot either -- zero of the 83
Bash commands in ``bench/corpus/`` change match signature under the anchor, so a
green bench is a PREDICTION here, not a verification. These rows are the
verification.

Ten classes, each pinning a different property:

* :class:`TestGenuineWritesDenyAtEveryShape` -- ANTI-REGRESSION. Every row denied
  before the anchor and must keep denying. A row flipping DENY -> ALLOW is a
  bypass of the anti-self-disable floor, not a false-positive fix.
* :class:`TestReadOnlyVerbMentionIsAllowed` -- the EARN-THE-RED half. Every row
  denied before the anchor -- that is the friction the class close removes -- and
  must now ALLOW. These 80 rows were RED against the unfixed tree, by design.
* :class:`TestMeasuredFalsePositiveCorpus` -- the ten specific false positives
  measured against the live hook before the fix, kept separate from the sweep
  because they are the already-attested rows rather than generated combinations.
* :class:`TestCommandPositionControls` -- rows that must not move in EITHER
  direction. Without them the suite cannot tell "the anchor works" from "the
  anchor stopped matching anything": a pattern that never fires also has zero
  false positives.
* :class:`TestRedTeamCommandPositionEvasion` -- twelve routes an adversarial pass
  found AFTER the two classes above were green, plus eight that held. This class
  exists because a shape sweep and a whole-population differential were BOTH
  clean while those twelve genuine writes were allowed: both populations are
  drawn from commands that already exist, and neither exercised a carriage
  return, a `case` arm, a leading redirection, or an alias-suppressing backslash-cp.
* :class:`TestWrapperRosterIsPinnedAgainstDeletion` -- DEF-595. The five classes
  above all cover the wrapper vocabulary INCIDENTALLY, by naming whichever
  wrappers a shape or an evasion route happened to need; eleven of the
  twenty-two were pinned by no row at all. This class covers it ON PURPOSE, and
  from a hand-written roster rather than from the constant, so a REMOVAL reds.
* :class:`TestKeywordRosterIsPinnedAgainstDeletion` -- the same pin for
  `_CMD_POS_KEYWORD`, the anchor's other alternation constant. Found by asking
  DEF-595's class question one constant over instead of stopping at the filed
  site: dropping `else` was measured to open a genuine write with the stack green.
* :class:`TestExecOpenerRosterIsPinnedAgainstDeletion` -- the anchor's third and
  last alternation, `_CMD_POS_EXEC_QUOTE`. Found by an adversarial pass after the
  two above were closed. Worse than the filed defect: nothing derived from this
  constant, so dropping three shell spellings opened three genuine writes with
  the declared oracle bit-identically green -- not even a shrinking count.
* :class:`TestAnAssignmentValueIsReadAsTheShellReadsIt` -- DEF-848's class: a
  write verb named inside an assignment value is a mention, at every quote
  kind and name case, and every form in which the shell goes on to run the
  value still denies. The five `env_prefix_*` SHAPES are its other direction:
  a verb after a prefix whose quoted value holds a blank is at a command
  position and was read by no verb arm.
* :class:`TestThePinsAreLiteralsNotDerivations` -- guards the three roster classes above
  from the one edit that would silently undo them: regenerating a pin from the
  constant it polices. AST-checked, because the alternative was a comment.

The hook is driven as a real subprocess through the house helper rather than by
matching the regexes directly. Testing the patterns in isolation would witness
the pattern body and never the wiring, which is the failure this repo has hit
repeatedly: deleting a call site leaves helper-only tests green.

Maintenance mode would make every row ALLOW by bypassing the protected-zone
check. The suite is immunised at ``tests/conftest.py`` (autouse fixture deletes
``ESPALIER_MAINTENANCE_MODE``); ad-hoc probing of the same rows outside pytest
is NOT, and will read every row as ALLOW if run from a maintenance session.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest

from tests._hook_assertions import assert_hook_allowed, assert_hook_denied
from tests.test_write_guard import _run_ps_guard, run_bash_guard

PROTECTED_DIR = "tools/cc/hooks"
PROTECTED_FILE = "tools/cc/hooks/write_guard.py"
# Allowlisted *inside* a protected zone -- the symlink-forgery target named in
# _bash_patterns' own comment above _LN_S_RE.
BLUEPRINT = "cc/blueprints/latest.json"
UNPROTECTED_DIR = "scripts"


def _bare(cmd: str) -> str:
    return cmd


def _abs_path_verb(cmd: str) -> str:
    """``cp x y`` -> ``/usr/bin/cp x y`` (invocation by absolute path)."""
    verb, _, rest = cmd.partition(" ")
    return f"/usr/bin/{verb} {rest}"


#: (label, wrapper) -- every distinct way a verb can reach a command position.
#: Derived from what the pre-fix matrix measured, not from what looked likely.
SHAPES: list[tuple[str, object]] = [
    ("bare", _bare),
    ("semicolon", lambda c: f"x=1; {c}"),
    ("and_and", lambda c: f"echo hi && {c}"),
    ("or_or", lambda c: f"false || {c}"),
    ("pipe", lambda c: f"echo hi | {c}"),
    ("newline", lambda c: f"echo hi\n{c}"),
    ("leading_tab", lambda c: f"\t{c}"),
    # A backslash-newline CONTINUES the statement, so the verb must follow a
    # separator to sit at a command position: `echo hi \` + newline + `cp …`
    # is one `echo` with `cp` as an argument (bash prints it), and since the
    # extractor splices continuations first (DEF-701) that shape correctly
    # reads as a mention. `echo hi; \` + newline + `cp …` is the real shape.
    ("line_continuation", lambda c: f"echo hi; \\\n{c}"),
    ("cmd_substitution", lambda c: f"$({c})"),
    ("backtick", lambda c: f"`{c}`"),
    ("brace_group", lambda c: "{ " + c + "; }"),
    ("subshell", lambda c: f"( {c} )"),
    ("eval", lambda c: f'eval "{c}"'),
    ("bash_c", lambda c: f"bash -c '{c}'"),
    ("sh_c", lambda c: f'sh -c "{c}"'),
    ("sudo", lambda c: f"sudo {c}"),
    ("sudo_with_flag_arg", lambda c: f"sudo -u me {c}"),
    ("env", lambda c: f"env {c}"),
    ("command", lambda c: f"command {c}"),
    ("time", lambda c: f"time {c}"),
    ("nohup", lambda c: f"nohup {c}"),
    ("timeout", lambda c: f"timeout 5 {c}"),
    ("xargs", lambda c: f"echo x | xargs {c}"),
    ("abs_path_verb", _abs_path_verb),
    ("if_then", lambda c: f"if true; then {c}; fi"),
    ("for_do", lambda c: f"for f in a; do {c}; done"),
    ("while_do", lambda c: f"while :; do {c}; done"),
    # The CONDITION of a compound is a command position too, and `!` runs the
    # pipeline it negates (DEF-704 failure-mode review: all four were allowed
    # for every anchored verb, and had just been lost for the interpreters).
    ("if_cond", lambda c: f"if {c}; then :; fi"),
    ("while_cond", lambda c: f"while {c}; do break; done"),
    ("until_cond", lambda c: f"until {c}; do break; done"),
    ("negate", lambda c: f"! {c}"),
    # An assignment prefix whose value holds a quoted blank, a quoted
    # separator, an ANSI-C escape or an escaped blank: bash ends the
    # assignment word at the first UNQUOTED blank, so the verb after it is at
    # a command position. The grammar ended the word at the first blank of
    # any kind and read none of these verbs (DEF-848's lane, measured on a
    # neutral verb 2026-09-19).
    ("env_prefix_quoted_blank", lambda c: f"A='a b' {c}"),
    ("env_prefix_double_quoted_blank", lambda c: f'A="say \\"hi there\\"" {c}'),
    ("env_prefix_quoted_separator", lambda c: f"A='a; b' {c}"),
    ("env_prefix_ansi_c", lambda c: f"A=$'it\\'s a' {c}"),
    ("env_prefix_escaped_blank", lambda c: f"A=a\\ b {c}"),
]

#: Intent 1 -- a genuine write into a protected zone. Must stay DENY.
GENUINE_WRITES: dict[str, str] = {
    "cp": f"cp /tmp/x {PROTECTED_FILE}",
    "ln_s": f"ln -s /tmp/evil {BLUEPRINT}",
    "install": f"install -m 644 /tmp/x {PROTECTED_DIR}/y",
}

#: Intent 2 -- a read-only command that merely NAMES a write verb. Must ALLOW.
READ_ONLY_MENTIONS: dict[str, str] = {
    "grep_install": f'grep -rn "install" {PROTECTED_DIR}/',
    "git_grep_cp": f"git grep 'cp' -- {PROTECTED_DIR}/",
    "grep_tee": f"grep -rn tee {PROTECTED_DIR}/",
}

#: DEF-414b, CLOSED 2026-09-05. The `)` of `( cmd )`, a `-v`, a `2>/dev/null`
#: and a `# note` used to be read as the last positional by _LN_S_RE and
#: _INSTALL_CMD_RE, hiding the real target. The operand span is tokenised now
#: (`_positional_operands`: flags and redirections fall away, `_strip_span_tail`
#: cuts a comment or a subshell close), so every shape x verb pair is a plain
#: deny. The strict xfail that pinned the gap here fired the day it closed --
#: exactly what it was for.


# --------------------------------------------------------------------------
# DEF-595 -- the wrapper roster, pinned against silent REMOVAL.
# --------------------------------------------------------------------------
#: THE PIN. Hand-written on purpose -- and this is `STANDING_PRINCIPLES` §14
#: APPLIED, not excepted. §14 carries its own discriminator for exactly this:
#:
#:     "Derive the population and a narrowing is silent. Derive the expectation
#:      and a narrowing is loud."
#:
#: DEF-595 was a population derived from the subject -- the silent side. The
#: remedy is not to stop deriving; it is to move the derivation to the other
#: side of the assertion. So the population stays hand-written here, and
#: `_live_wrappers()` derives the ACTUAL that the equality row checks it
#: against. A narrowing of the constant is then loud in both directions.
#:
#: A population derived from `_CMD_POS_WRAPPER` enrols an ADDITION and is
#: structurally blind to a DELETION, and deletion is the regression direction an
#: edit to `_bash_patterns` actually threatens. Measured 2026-08-17: dropping the
#: eleven members marked below opened ELEVEN genuine protected-zone writes
#: (`doas cp /tmp/x <zone>/` and siblings, DENY -> ALLOW) while the entire gate
#: stack stayed green -- 992 passed against an honest baseline of 1025, the suite
#: having silently SHRUNK by 33 rows as every derived population contracted along
#: with its own subject. A green that gets smaller is not a green.
#:
#: So the rows below are generated from THIS literal, never from the constant:
#: delete a wrapper from `_bash_patterns` and its row survives here and reds.
_PINNED_WRAPPERS: frozenset[str] = frozenset({
    # pinned incidentally by a SHAPES row
    "command", "env", "nohup", "sudo", "time", "timeout", "xargs",
    # pinned incidentally by a red-team evasion row
    "script", "setsid", "strace", "watch",
    # pinned by NOTHING before DEF-595 -- the eleven driven DENY -> ALLOW
    "chrt", "doas", "exec", "ionice", "ltrace", "nice",
    "proxychains", "stdbuf", "taskset", "torify", "unbuffer",
})

#: A LITERAL, not `len(_PINNED_WRAPPERS)`. This is the tripwire on the obvious
#: wrong fix: regenerating the roster above from `_CMD_POS_WRAPPER` would make
#: the set-equality row tautological and restore the exact blindness DEF-595
#: describes. Bumping this number is the deliberate act that says a wrapper's
#: arrival or departure was intended.
_PINNED_WRAPPER_COUNT = 22

_BASH_PATTERNS = (
    Path(__file__).resolve().parent.parent
    / "tools" / "cc" / "hooks" / "_bash_patterns.py"
)


#: The keyword arm of the same anchor, and the same class -- `_CMD_POS_KEYWORD`
#: is a second alternation constant whose members each open a command position.
#: `SHAPES` covers `then` and `do` incidentally (via `if_then`/`for_do`) and
#: covers `else` and `elif` not at all. Measured 2026-08-17: deleting `else`
#: flips `if false; then :; else cp /tmp/x <zone>; fi` DENY -> ALLOW while the
#: whole gate stack stays green at 629 passed.
_PINNED_KEYWORDS: frozenset[str] = frozenset({
    "then", "do", "else", "elif", "if", "while", "until",
})

#: Literal, for the same anti-regeneration reason as `_PINNED_WRAPPER_COUNT`.
_PINNED_KEYWORD_COUNT = 7

#: One genuine protected-zone write per keyword, in a shell form where THAT
#: keyword is what puts the verb at a command position.
#:
#: ⚠ HISTORY, kept because the wrong version of this comment nearly shipped.
#: `elif`'s first shape here was `if false; then :; elif true; then cp ...; fi`,
#: whose write sits behind the arm's own `then` -- so deleting `elif` did not
#: flip it, and this comment asserted that no per-shape row COULD pin `elif`.
#: That was false, and stating it would have foreclosed the fix for whoever read
#: it next. `elif` takes a COMMAND LIST as its condition, so the verb can sit
#: directly at the `elif` command position. Measured on the shape below:
#: baseline DENY, and ALLOW with `elif` removed from the constant. All four rows
#: are load-bearing. A documented "this cannot be done" outlives a missing test.
_KEYWORD_WRITE_SHAPES: dict[str, str] = {
    "then": f"if true; then cp /tmp/x {PROTECTED_FILE}; fi",
    "do": f"for f in a; do cp /tmp/x {PROTECTED_FILE}; done",
    "else": f"if false; then :; else cp /tmp/x {PROTECTED_FILE}; fi",
    "elif": f"if false; then :; elif cp /tmp/x {PROTECTED_FILE}; then :; fi",
    "if": f"if cp /tmp/x {PROTECTED_FILE}; then :; fi",
    "while": f"while cp /tmp/x {PROTECTED_FILE}; do break; done",
    "until": f"until cp /tmp/x {PROTECTED_FILE}; do break; done",
}

#: The anchor's THIRD alternation, and the class's third member -- found by an
#: adversarial pass after the two above were closed, eleven lines away in the
#: same file. `_CMD_POS_EXEC_QUOTE` enumerates six shell-exec openers; `SHAPES`
#: covers `eval`, `bash -c` and `sh -c`, and `zsh -c` / `ksh -c` / `dash -c`
#: were covered by no row anywhere.
#:
#: ⚠ This one was WORSE than DEF-595's flagship. DEF-595 at least shrank the row
#: count, and that shrink is the tell it was caught by. Nothing derived from THIS
#: constant at all, so dropping `z|k|da` (a plausible "simplify the alternation"
#: edit) opened three genuine protected-zone writes with the declared oracle at
#: 232 passed -- bit-identical to baseline, nothing to notice.
_PINNED_EXEC_OPENERS: frozenset[str] = frozenset({
    "eval", "sh -c", "bash -c", "zsh -c", "ksh -c", "dash -c",
})

#: Literal, for the same anti-regeneration reason as the two counts above.
_PINNED_EXEC_OPENER_COUNT = 6

#: One genuine protected-zone write per opener, in the form that opener takes.
_EXEC_WRITE_SHAPES: dict[str, str] = {
    "eval": f'eval "cp /tmp/x {PROTECTED_FILE}"',
    "sh -c": f"sh -c 'cp /tmp/x {PROTECTED_FILE}'",
    "bash -c": f"bash -c 'cp /tmp/x {PROTECTED_FILE}'",
    "zsh -c": f"zsh -c 'cp /tmp/x {PROTECTED_FILE}'",
    "ksh -c": f"ksh -c 'cp /tmp/x {PROTECTED_FILE}'",
    "dash -c": f"dash -c 'cp /tmp/x {PROTECTED_FILE}'",
}

#: `_CMD_POS_EXEC_QUOTE` is not a flat alternation -- it nests an optional
#: prefix group, so `(?:ba|z|k|da)?sh` is FIVE spellings rather than four
#: members. `_live_alternation` cannot read it and must not be widened until
#: it can: this constant gets its own extractor.
_EXEC_QUOTE_SHAPE = re.compile(r"\(\?:eval\|\(\?:([a-z|]+)\)\?sh\[")


def _load_bash_patterns():
    """The live `_bash_patterns` module.

    Loaded via `spec_from_file_location` rather than a plain import: a plain
    import would need `tools/cc/hooks` on `sys.path`, and putting it there
    drags this suite into the hooks' zero-espalier-import graph (tests/CLAUDE.md).
    """
    spec = importlib.util.spec_from_file_location(
        "_bash_patterns_roster", _BASH_PATTERNS
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _live_alternation(attr: str) -> set[str]:
    """Members of a bare ``(?:a|b|c)`` alternation constant.

    ⚠ Deliberately NOT ``re.findall(r"[a-z]+", ...)``. That scrape tokenizes on
    lowercase runs, so any member carrying a digit or a hyphen DECOMPOSES --
    and if its leading run collides with a name already pinned, the addition
    enrols invisibly. Measured: adding `proxychains4` (the real Debian binary
    name, next to the `proxychains` already present) left the scrape returning
    22 members, the roster row green, and a live functional wrapper covered by
    nothing. That is this file's own defect, in its addition direction.

    So this parses the alternation structurally and REDS on any shape it cannot
    read, rather than silently returning whatever it managed to find.
    """
    raw = getattr(_load_bash_patterns(), attr)
    assert isinstance(raw, str) and raw.startswith("(?:") and raw.endswith(")"), (
        f"{attr} is no longer a bare (?:a|b|c) alternation ({raw!r}). The roster "
        f"pin cannot read it. Update this extractor deliberately -- do NOT widen "
        f"it to whatever the new shape happens to yield."
    )
    members = raw[3:-1].split("|")
    for member in members:
        assert re.fullmatch(r"[\w.-]+", member), (
            f"{attr} member {member!r} is not a literal word, so the pin cannot "
            f"cover it. If the constant grew a nested group, this extractor needs "
            f"a deliberate update, not a looser pattern."
        )
    return set(members)


def _live_wrappers() -> set[str]:
    return _live_alternation("_CMD_POS_WRAPPER")


def _live_keywords() -> set[str]:
    return _live_alternation("_CMD_POS_KEYWORD")


def _live_exec_openers() -> set[str]:
    """The shell-exec openers `_CMD_POS_EXEC_QUOTE` admits.

    Expands the optional prefix group rather than scraping words: the members
    are `eval` plus five spellings of `<shell> -c`, and a word scrape would
    return `ba`, `z`, `k`, `da` and `sh` as if they were openers.
    """
    raw = _load_bash_patterns()._CMD_POS_EXEC_QUOTE
    match = _EXEC_QUOTE_SHAPE.search(raw)
    assert match, (
        f"_CMD_POS_EXEC_QUOTE no longer has the shape this pin can read "
        f"({raw!r}). Update this extractor deliberately -- a pin that cannot "
        f"read its subject must red, not fall back to a looser pattern."
    )
    prefixes = [""] + match.group(1).split("|")
    return {"eval"} | {f"{prefix}sh -c" for prefix in prefixes}


def _write_params() -> list:
    params = []
    for shape_name, wrap in SHAPES:
        for verb, payload in GENUINE_WRITES.items():
            params.append(pytest.param(wrap(payload), id=f"{shape_name}-{verb}"))
    return params


def _read_params() -> list:
    return [
        pytest.param(wrap(payload), id=f"{shape_name}-{verb}")
        for shape_name, wrap in SHAPES
        for verb, payload in READ_ONLY_MENTIONS.items()
    ]


class TestGenuineWritesDenyAtEveryShape:
    """Anti-regression half: a genuine write denies at every command position.

    These rows are GREEN before the anchor lands and must stay green. A row
    flipping to ALLOW is a bypass, not a false-positive fix -- the anchor is
    allowed to remove friction, never to remove a deny.
    """

    @pytest.mark.parametrize("command", _write_params())
    def test_genuine_write_into_protected_zone_is_denied(self, command, tmp_path):
        assert_hook_denied(run_bash_guard(command, tmp_path))


#: DEF-848's class at every verb reader built on the command-position grammar:
#: a write verb named INSIDE an assignment value is text the current shell
#: stores, not a command it runs -- wherever the value sits, whatever quote
#: holds it, whatever case the name takes, and beside a head the masker cannot
#: read (the value is its own statement's data).
_VALUE_MENTIONS: list[tuple[str, object]] = [
    ("single_quoted", lambda c: f"MSG='note: {c}'; true"),
    ("double_quoted", lambda c: f'MSG="note: {c}"; true'),
    ("ansi_c", lambda c: f"MSG=$'note: {c}'; true"),
    ("lowercase", lambda c: f"msg='note: {c}'; true"),
    ("separator_inside", lambda c: f"MSG='note; {c}'; true"),
    ("prefix_to_a_reader", lambda c: f"MSG='note: {c}' git status"),
    ("into_a_commit_message", lambda c: f"MSG='note: {c}'; git commit -m \"$MSG\""),
    ("beside_an_unread_head", lambda c: f"MSG='note; {c}'; make"),
]

#: The twins: a value the shell goes on to RUN. Each is read through the
#: binding pre-pass, which substitutes the value at its use (DEF-847 reads
#: every case of name and the declaration builtins), so the write is judged
#: where it executes.
_VALUE_EXECUTED: list[tuple[str, object]] = [
    ("evaled", lambda c: f"MSG='{c}'; eval \"$MSG\""),
    ("shell_c", lambda c: f"msg='{c}'; bash -c \"$msg\""),
    ("as_the_command", lambda c: f"CMD='{c}'; $CMD"),
    ("separator_inside_evaled", lambda c: f"v='true; {c}'; eval \"$v\""),
    ("wrapper_inside_evaled", lambda c: f"v='sudo {c}'; eval \"$v\""),
    ("exported_to_a_child_shell", lambda c: f"export V='{c}'; bash -c 'eval \"$V\"'"),
]


#: The write verbs the value class drives: the shape matrix's three, and a
#: HARDLINK, whose reader read the raw command alone until the lane's review
#: (`iter_hardlink_operands` now takes the write extractor's reading).
_VALUE_VERBS: dict[str, str] = {
    **GENUINE_WRITES,
    "ln_hard": f"ln /tmp/src {PROTECTED_FILE}",
}


class TestAnAssignmentValueIsReadAsTheShellReadsIt:
    """DEF-848 at the command-position grammar. `_CMD_POS_ENV_ASSIGN` ended
    an assignment word at the first blank even inside the value's quotes, so
    a word inside the value opened a command position, and the masker
    stepped over the whole word, so a separator inside it stayed live. A
    value is the shell's DATA until something runs it; the executed twins
    keep every run form read."""

    @pytest.mark.parametrize("command", [
        pytest.param(wrap(payload), id=f"{label}-{verb}")
        for label, wrap in _VALUE_MENTIONS
        for verb, payload in _VALUE_VERBS.items()
    ])
    def test_a_write_named_in_an_assignment_value_is_a_mention(self, command, tmp_path):
        assert_hook_allowed(run_bash_guard(command, tmp_path))

    @pytest.mark.parametrize("command", [
        pytest.param(wrap(payload), id=f"{label}-{verb}")
        for label, wrap in _VALUE_EXECUTED
        for verb, payload in _VALUE_VERBS.items()
    ])
    def test_a_value_the_shell_runs_is_still_read(self, command, tmp_path):
        assert_hook_denied(run_bash_guard(command, tmp_path))

    @pytest.mark.parametrize("builtin", ["export", "local", "declare", "typeset", "readonly"])
    def test_a_declaration_builtins_value_keeps_its_separator_live(self, builtin, tmp_path):
        """docs/HOOKS.md's declared limit in the FRICTION direction, pinned
        as the exact pair so the day the builtins join the masker's roster
        the row reds and the sentence is rewritten on purpose: a value given
        to `export`, `local`, `declare`, `typeset` or `readonly` is an
        argument of that builtin, and a separator inside it is still read as
        a statement boundary -- so a message DECLARED with one of those,
        quoting a protected write behind a separator, is refused where the
        same message stored by a bare assignment is data. Not a simple
        oversight (measured on bash 3.2, 2026-09-19): under an array or an
        integer attribute bash evaluates such a value and a substitution
        inside it runs, so the relief cannot be handed to these builtins by
        name alone. Driven 2026-09-22 before it was written. The named user:
        the adopter whose agent declares a commit-message variable with
        `export` and meets a deny where the bare assignment sails through."""
        message = "'ok; echo x > tools/cc/hooks/x.py'"
        assert_hook_allowed(run_bash_guard(f"MSG={message}", tmp_path))
        assert_hook_denied(run_bash_guard(f"{builtin} MSG={message}", tmp_path))

    @pytest.mark.parametrize("command", [
        pytest.param(f"MSG=\"$X {payload}\"; eval \"$MSG\"",
                     id=f"unreadable-value-evaled-{verb}")
        for verb, payload in GENUINE_WRITES.items()
    ])
    def test_the_declared_limit_stays_a_limit(self, command, tmp_path):
        """docs/HOOKS.md's declared limit, pinned so a change to it is a
        deliberate act: a value the binding pre-pass cannot read (here a
        double-quoted value holding a parameter reference) that the shell
        later RUNS is not refused. A value that also holds a separator or a
        group character is still read by accident through it; this one holds
        neither. The quote-blind grammar refused a value like it until
        DEF-848's lane when a word came before the verb -- the one cost the
        operator accepted for reading an assignment word as bash does."""
        assert_hook_allowed(run_bash_guard(command, tmp_path))


class TestAContinuationIsNotACommandPosition:
    """`echo hi \\` + newline + `cp …`: bash continues the echo, so `cp` is an
    ARGUMENT and nothing is written. The extractor splices continuations first
    (DEF-701), so this reads as a mention; before that, the newline sat in
    `_CMD_POS`'s separator class and every such shape was a false deny. Pinned
    as an allow so the retired fixture's claim is mechanical, not prose."""

    @pytest.mark.parametrize("command", [
        f"echo hi \\\n{GENUINE_WRITES['cp']}",
        f"echo hi \\\n{GENUINE_WRITES['ln_s']}",
    ])
    def test_continued_verb_is_an_argument_not_a_command(self, command, tmp_path):
        assert_hook_allowed(run_bash_guard(command, tmp_path))


class TestReadOnlyVerbMentionIsAllowed:
    """Earn-the-red half: naming a write verb is not performing a write.

    Every row here DENIES before the anchor lands -- that denial is the
    friction the class close exists to remove, and it teaches an operator to
    relaunch in maintenance mode (lowering four other checks) just to run a
    grep. These tests are RED until the anchor lands, deliberately.
    """

    @pytest.mark.parametrize("command", _read_params())
    def test_read_only_command_naming_a_write_verb_is_allowed(self, command, tmp_path):
        result = run_bash_guard(command, tmp_path)
        assert result.returncode == 0, (
            f"hook errored on a read-only command: rc={result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert '"permissionDecision": "deny"' not in result.stdout, (
            f"read-only command denied as a write: {command!r}\n"
            f"stdout={result.stdout!r}"
        )


class TestMeasuredFalsePositiveCorpus:
    """The ten false positives measured against the live hook before the fix.

    Kept separate from the shape sweep because these are the specific
    already-attested rows: four flag-cluster forms where a `-cp`/`-ln` cluster
    reads as a verb, and six read-only forms where a verb name appears in an
    argument. Each denies at HEAD and must become ALLOW.
    """

    @pytest.mark.parametrize("command", [
        pytest.param(f"ls -cp somedir {PROTECTED_FILE}", id="cp-mv-flag-cluster"),
        pytest.param(f"grep -ln -s pattern {PROTECTED_FILE}", id="ln-s-flag-cluster-grep"),
        pytest.param(f"ls -ln -s somedir {PROTECTED_FILE}", id="ln-s-flag-cluster-ls"),
        pytest.param(f"ls -cp -s somedir {PROTECTED_FILE}", id="cp-symlink-flag-cluster"),
        pytest.param(f'grep -rn "install" {PROTECTED_DIR}/', id="install-read-only"),
        pytest.param(f'grep -rn "rsync" {PROTECTED_DIR}/', id="rsync-read-only"),
        pytest.param(f'grep -rn "truncate" {PROTECTED_DIR}/', id="truncate-read-only"),
        pytest.param(f'grep -rn "patch" {PROTECTED_DIR}/', id="patch-read-only"),
        pytest.param(f"grep -rn tee {PROTECTED_DIR}/", id="tee-read-only"),
        pytest.param(f'grep -rn "install" {PROTECTED_DIR}/x', id="install-target-dir-read-only"),
    ])
    def test_measured_false_positive_is_allowed(self, command, tmp_path):
        result = run_bash_guard(command, tmp_path)
        assert '"permissionDecision": "deny"' not in result.stdout, (
            f"measured false positive still denied: {command!r}\n"
            f"stdout={result.stdout!r}"
        )


class TestCommandPositionControls:
    """Rows that must not move in either direction.

    Without these the suite cannot distinguish "the anchor works" from "the
    anchor stopped matching anything" -- a pattern that never fires also has
    zero false positives.
    """

    @pytest.mark.parametrize("command", [
        pytest.param(f"cp /tmp/x {UNPROTECTED_DIR}/", id="write-to-unprotected-path"),
        pytest.param(f"git grep 'mv' -- {UNPROTECTED_DIR}/", id="read-unprotected-path"),
        pytest.param("grep -rm 1 foo /tmp", id="rm-flag-cluster-not-a-verb"),
    ])
    def test_unprotected_command_is_allowed(self, command, tmp_path):
        result = run_bash_guard(command, tmp_path)
        assert '"permissionDecision": "deny"' not in result.stdout, (
            f"control row denied: {command!r}\nstdout={result.stdout!r}"
        )

    @pytest.mark.parametrize("command", [
        pytest.param(f"cp /tmp/x {PROTECTED_FILE}", id="bare-cp"),
        pytest.param(f"'cp' /tmp/x {PROTECTED_FILE}", id="quoted-verb"),
        pytest.param(f"sudo -n cp /tmp/x {PROTECTED_FILE}", id="wrapper-flag-without-arg"),
        pytest.param(f"ln /tmp/src {PROTECTED_FILE}", id="hardlink"),
    ])
    def test_anchor_still_fires_on_the_plainest_writes(self, command, tmp_path):
        """A too-strict anchor is as broken as a too-loose one, and quieter.

        ``sudo -n cp`` is the backtracking control: the anchor's wrapper run
        greedily tries to swallow ``cp`` as the argument to ``-n``, and must
        backtrack so the verb still matches.
        """
        assert_hook_denied(run_bash_guard(command, tmp_path))


class TestRedTeamCommandPositionEvasion:
    """Adversarial shapes from the step-11 red-team, encoded.

    Every row here was driven against the real hook and **denied before the
    anchor landed**. The anchor's first form allowed **twelve of them** — a
    verb reaches a command position by more routes than the obvious ones, and
    an anchor is an enumeration of those routes. They are pinned because an
    enumeration silently loses a member on the next refactor, and because a
    red-team that lives only in a session transcript is not a test.

    None of these were reachable by the shape sweep above: that sweep varies
    the wrapper around a known-good command, while these vary the *lexical
    route* by which the verb becomes a command word.
    """

    @pytest.mark.parametrize("command", [
        # separators the first anchor did not recognise
        pytest.param(f"echo hi\r cp /tmp/x {PROTECTED_FILE}", id="carriage-return"),
        pytest.param(f"case x in y) cp /tmp/x {PROTECTED_FILE};; esac", id="case-arm-paren"),
        pytest.param(f"echo hi;\x0bcp /tmp/x {PROTECTED_FILE}", id="vertical-tab"),
        pytest.param(f"echo hi;\x0ccp /tmp/x {PROTECTED_FILE}", id="form-feed"),
        pytest.param(f">/dev/null cp /tmp/x {PROTECTED_FILE}", id="leading-redirect"),
        # wrappers outside the first vocabulary
        pytest.param(f"setsid cp /tmp/x {PROTECTED_FILE}", id="wrapper-setsid"),
        pytest.param(f"strace -f cp /tmp/x {PROTECTED_FILE}", id="wrapper-strace"),
        pytest.param(f"watch -n1 cp /tmp/x {PROTECTED_FILE}", id="wrapper-watch"),
        pytest.param(f"script -c 'cp /tmp/x {PROTECTED_FILE}' /dev/null", id="wrapper-script-c"),
        # verb spelling that still invokes the verb
        pytest.param(f"\\cp /tmp/x {PROTECTED_FILE}", id="backslash-alias-suppression"),
        pytest.param(f"$'cp' /tmp/x {PROTECTED_FILE}", id="ansi-c-quoted-verb"),
        # shapes that held from the first form -- pinned so widening cannot lose them
        pytest.param(f"echo hi |& cp /tmp/x {PROTECTED_FILE}", id="pipe-ampersand"),
        pytest.param(f"echo $(echo $(cp /tmp/x {PROTECTED_FILE}))", id="nested-substitution"),
        pytest.param(f"until false; do cp /tmp/x {PROTECTED_FILE}; done", id="until-do"),
        pytest.param(f"f() {{ cp /tmp/x {PROTECTED_FILE}; }}; f", id="function-body"),
        pytest.param(f"time sudo env cp /tmp/x {PROTECTED_FILE}", id="chained-wrappers"),
        pytest.param(f"sudo -n cp /tmp/x {PROTECTED_FILE}", id="wrapper-flag-no-arg"),
        pytest.param(f"/bin/cp /tmp/x {PROTECTED_FILE}", id="absolute-path-verb"),
        pytest.param("cp /tmp/x tools/./cc/hooks/write_guard.py", id="dot-segment-target"),
        pytest.param("cp /tmp/x tools/cc/../cc/hooks/write_guard.py", id="traversal-target"),
    ])
    def test_evasion_shape_is_still_denied(self, command, tmp_path):
        assert_hook_denied(run_bash_guard(command, tmp_path))

    @pytest.mark.parametrize("command", [
        pytest.param(f"ln -s /tmp/evil {BLUEPRINT} 2>/dev/null", id="trailing-redirect"),
        pytest.param(f"ln -s /tmp/evil {BLUEPRINT} # note", id="trailing-comment"),
        pytest.param(f"ln -s /tmp/evil {BLUEPRINT} -v", id="trailing-flag"),
        pytest.param(f"( ln -s /tmp/evil {BLUEPRINT} )", id="subshell-close"),
        pytest.param(f"install -m 644 /tmp/x {PROTECTED_DIR}/y 2>/dev/null", id="install-trailing-redirect"),
        pytest.param(f"install -m 644 /tmp/x {PROTECTED_DIR}/y > /dev/null", id="install-separate-redirect"),
    ])
    def test_trailing_token_does_not_hide_the_target(self, command, tmp_path):
        """DEF-414b, closed: the operand span is tokenised, so nothing after the
        real target shifts the last-positional pick. The first two rows were a
        strict xfail for a month, and it fired the day the class closed."""
        assert_hook_denied(run_bash_guard(command, tmp_path))


class TestWrapperRosterIsPinnedAgainstDeletion:
    """DEF-595 -- the anchor's wrapper vocabulary, pinned in BOTH directions.

    The classes above cover wrappers incidentally: a shape row names the seven a
    shape happened to need, the red-team rows name four more, and the remaining
    eleven were pinned by nothing. Every population that DID reference the
    vocabulary derived itself from `_CMD_POS_WRAPPER`, so removing a member
    removed its own coverage and the stack stayed green while eleven genuine
    writes into a guarded zone were allowed.

    These three rows are the floor that does not derive from its subject.
    """

    def test_live_roster_matches_the_pin_exactly(self):
        """Reds on a removal AND on an addition -- the whole point of the pin."""
        live = _live_wrappers()
        removed = sorted(_PINNED_WRAPPERS - live)
        added = sorted(live - _PINNED_WRAPPERS)
        assert not removed, (
            f"wrapper(s) REMOVED from _CMD_POS_WRAPPER: {removed}. Each one opens a "
            f"genuine protected-zone write behind that wrapper -- "
            f"`{removed[0]} cp /tmp/x {PROTECTED_DIR}/` now ALLOWs.\n"
            f"THE FIX IS ALMOST CERTAINLY TO RESTORE THE WRAPPER. This row fires on "
            f"an accidental drop during a refactor of _bash_patterns far more often "
            f"than on a deliberate retirement.\n"
            f"Do NOT reach for _PINNED_WRAPPERS first: editing the pin to match the "
            f"constant is the low-friction move that silences the alarm and KEEPS "
            f"the hole -- it is DEF-595 rebuilt by hand. Change the pin only after "
            f"you can state why that wrapper can no longer reach a command position."
        )
        assert not added, (
            f"wrapper(s) ADDED to _CMD_POS_WRAPPER without a correctness row: "
            f"{added}. Add each to _PINNED_WRAPPERS and bump "
            f"_PINNED_WRAPPER_COUNT; the per-wrapper deny row below then covers it."
        )

    def test_pinned_roster_size_is_a_literal(self):
        """Tripwire on the wrong fix.

        Regenerating `_PINNED_WRAPPERS` from `_CMD_POS_WRAPPER` would make the
        equality above tautological and restore DEF-595 exactly.

        ⚠ This row does NOT hold that property on its own, and the earlier
        docstring here claimed it did. Measured: regenerate the roster and
        nothing reds; regenerate it and THEN delete two wrappers, and the only
        red is this row's terse count message, which a one-character edit
        (22 -> 20) clears with the hole still open. It is
        `TestThePinsAreLiteralsNotDerivations` that makes the pair sound. Read
        the two together -- and do not prune that class as redundant to this one.
        """
        assert len(_PINNED_WRAPPERS) == _PINNED_WRAPPER_COUNT, (
            f"roster holds {len(_PINNED_WRAPPERS)} names but the pinned count is "
            f"{_PINNED_WRAPPER_COUNT}. If _PINNED_WRAPPERS was regenerated from "
            f"_CMD_POS_WRAPPER, revert that: a derived roster cannot see a deletion."
        )

    @pytest.mark.parametrize("wrapper", sorted(_PINNED_WRAPPERS))
    def test_genuine_write_behind_each_pinned_wrapper_is_denied(
        self, wrapper, tmp_path
    ):
        """One correctness row per wrapper, parametrized from the PIN.

        Parametrizing from `_CMD_POS_WRAPPER` instead would delete a wrapper's
        row along with the wrapper -- the failure this class exists to close.
        """
        assert_hook_denied(
            run_bash_guard(f"{wrapper} cp /tmp/x {PROTECTED_FILE}", tmp_path)
        )


class TestKeywordRosterIsPinnedAgainstDeletion:
    """The keyword arm of the same anchor -- the class's second member.

    `_CMD_POS_KEYWORD` is the sibling alternation to `_CMD_POS_WRAPPER` and had
    the identical blindness: `SHAPES` names `then` and `do` only incidentally,
    names `else` and `elif` not at all, and nothing derived a floor from either.
    Found by asking DEF-595's class question one constant over rather than
    stopping at the site that was filed.
    """

    def test_live_keywords_match_the_pin_exactly(self):
        live = _live_keywords()
        removed = sorted(_PINNED_KEYWORDS - live)
        added = sorted(live - _PINNED_KEYWORDS)
        assert not removed, (
            f"keyword(s) REMOVED from _CMD_POS_KEYWORD: {removed}. Each one opens "
            f"a command position -- dropping `else` was measured to flip "
            f"`if false; then :; else cp /tmp/x {PROTECTED_DIR}/; fi` to ALLOW "
            f"with the whole gate stack still green.\n"
            f"THE FIX IS ALMOST CERTAINLY TO RESTORE THE KEYWORD, not to edit "
            f"_PINNED_KEYWORDS to match -- see TestWrapperRosterIsPinnedAgainstDeletion."
        )
        assert not added, (
            f"keyword(s) ADDED to _CMD_POS_KEYWORD without a correctness row: "
            f"{added}. Add each to _PINNED_KEYWORDS, bump _PINNED_KEYWORD_COUNT, "
            f"and give it a shell form in _KEYWORD_WRITE_SHAPES where THAT keyword "
            f"is what puts the verb at a command position."
        )

    def test_pinned_keyword_roster_size_is_a_literal(self):
        assert len(_PINNED_KEYWORDS) == _PINNED_KEYWORD_COUNT, (
            f"roster holds {len(_PINNED_KEYWORDS)} names but the pinned count is "
            f"{_PINNED_KEYWORD_COUNT}. A roster regenerated from _CMD_POS_KEYWORD "
            f"cannot see a deletion."
        )

    def test_every_pinned_keyword_has_a_write_shape(self):
        """The shapes dict is the coverage; an unshaped keyword is an unpinned one."""
        missing = sorted(_PINNED_KEYWORDS - set(_KEYWORD_WRITE_SHAPES))
        assert not missing, f"pinned keyword(s) with no write shape: {missing}"

    def test_each_shape_puts_its_own_keyword_at_the_command_position(self):
        """A shape whose verb sits behind a DIFFERENT keyword is an inert row.

        This is the `added`-branch instruction above made mechanical. The first
        `elif` shape shipped here was exactly this mistake, and the comment
        explaining why it was unavoidable is what would have preserved it --
        so the rule is now a check rather than a sentence someone must read.
        """
        for keyword, shape in _KEYWORD_WRITE_SHAPES.items():
            assert re.search(rf"\b{re.escape(keyword)}\s+cp\b", shape), (
                f"{keyword!r}'s shape does not place the verb directly behind "
                f"{keyword!r}, so the row cannot fail when {keyword!r} is removed "
                f"from the constant: {shape!r}"
            )

    @pytest.mark.parametrize("keyword", sorted(_PINNED_KEYWORDS))
    def test_genuine_write_behind_each_pinned_keyword_is_denied(
        self, keyword, tmp_path
    ):
        assert_hook_denied(
            run_bash_guard(_KEYWORD_WRITE_SHAPES[keyword], tmp_path)
        )


class TestExecOpenerRosterIsPinnedAgainstDeletion:
    """The anchor's third alternation, pinned the same way as the other two.

    `SHAPES` names `eval`, `bash -c` and `sh -c` incidentally, because those are
    the openers a shape happened to need. `zsh -c`, `ksh -c` and `dash -c` were
    pinned by nothing until an adversarial pass drove them.
    """

    def test_live_exec_openers_match_the_pin_exactly(self):
        live = _live_exec_openers()
        removed = sorted(_PINNED_EXEC_OPENERS - live)
        added = sorted(live - _PINNED_EXEC_OPENERS)
        assert not removed, (
            f"shell-exec opener(s) REMOVED from _CMD_POS_EXEC_QUOTE: {removed}. "
            f"Each one opens a command position inside its quoted argument -- "
            f"dropping the `z|k|da` prefixes was measured to open `zsh -c`, "
            f"`ksh -c` and `dash -c` with the entire declared oracle green.\n"
            f"THE FIX IS ALMOST CERTAINLY TO RESTORE THE OPENER, not to edit "
            f"_PINNED_EXEC_OPENERS to match."
        )
        assert not added, (
            f"shell-exec opener(s) ADDED without a correctness row: {added}. Add "
            f"each to _PINNED_EXEC_OPENERS, bump _PINNED_EXEC_OPENER_COUNT, and "
            f"give it a write shape in _EXEC_WRITE_SHAPES."
        )

    def test_pinned_exec_opener_roster_size_is_a_literal(self):
        assert len(_PINNED_EXEC_OPENERS) == _PINNED_EXEC_OPENER_COUNT, (
            f"roster holds {len(_PINNED_EXEC_OPENERS)} openers but the pinned "
            f"count is {_PINNED_EXEC_OPENER_COUNT}. Read together with "
            f"TestThePinsAreLiteralsNotDerivations."
        )

    def test_every_pinned_opener_has_a_write_shape(self):
        missing = sorted(_PINNED_EXEC_OPENERS - set(_EXEC_WRITE_SHAPES))
        assert not missing, f"pinned opener(s) with no write shape: {missing}"

    @pytest.mark.parametrize("opener", sorted(_PINNED_EXEC_OPENERS))
    def test_genuine_write_behind_each_pinned_opener_is_denied(
        self, opener, tmp_path
    ):
        assert_hook_denied(run_bash_guard(_EXEC_WRITE_SHAPES[opener], tmp_path))


class TestThePinsAreLiteralsNotDerivations:
    """The anti-regeneration invariant, enforced mechanically instead of by comment.

    The comments on the pins say "a LITERAL, not `len(...)`". A comment is
    advice a future editor may decline, and the decline is invisible: convert
    BOTH a roster and its count to derived values in one edit and DEF-595 is
    reproduced exactly, with every row above still green -- the equality check
    goes tautological and the per-member rows vanish with their members.

    This class is the gate that comment could not be. It parses THIS file and
    refuses a pin that has turned into a computation.

    Precedent for the shape: `tests/test_release_denylist.py::TestNoSharedImports`,
    which AST-walks to prove two witnesses have not collapsed into one.
    """

    @staticmethod
    def _module_level_assignments() -> dict[str, ast.expr]:
        # encoding pinned: this file carries §, — and ⚠, and on a runner with an
        # unset locale a bare read_text() resolves to US-ASCII and reds all four
        # rows on a CORRECT tree. A false red in the one class whose job is to be
        # believed teaches the reader to distrust it.
        tree = ast.parse(Path(__file__).resolve().read_text(encoding="utf-8"))
        found: dict[str, ast.expr] = {}
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    found[node.target.id] = node.value
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found[target.id] = node.value
        return found

    @pytest.mark.parametrize(
        "name",
        ["_PINNED_WRAPPERS", "_PINNED_KEYWORDS", "_PINNED_EXEC_OPENERS"],
    )
    def test_roster_is_a_literal_set_of_string_constants(self, name):
        value = self._module_level_assignments()[name]
        why = (
            f"{name} must stay a hand-written `frozenset({{...}})` of string "
            f"literals. It is the floor that does NOT derive from the constant "
            f"it polices -- deriving it restores DEF-595 with the suite green."
        )
        assert isinstance(value, ast.Call), why
        assert getattr(value.func, "id", None) == "frozenset", why
        assert len(value.args) == 1 and isinstance(value.args[0], ast.Set), why
        assert all(
            isinstance(element, ast.Constant) and isinstance(element.value, str)
            for element in value.args[0].elts
        ), why

    @pytest.mark.parametrize(
        "name",
        [
            "_PINNED_WRAPPER_COUNT",
            "_PINNED_KEYWORD_COUNT",
            "_PINNED_EXEC_OPENER_COUNT",
        ],
    )
    def test_count_is_an_integer_literal(self, name):
        value = self._module_level_assignments()[name]
        assert isinstance(value, ast.Constant) and isinstance(value.value, int), (
            f"{name} must stay an integer literal. Written as `len(...)` of the "
            f"roster it tracks, it can never disagree with it -- and disagreeing "
            f"is its entire job: it is the tripwire that catches a roster which "
            f"was regenerated from the subject."
        )


# ── PowerShell: a re-parsing wrapper's switch run carries a VALUE ─────────────
# The exec-quote arm `_PS_CMD_POS_EXEC_QUOTE` (and its lookbehind twin
# `_PS_REPARSED_SPAN_BEFORE`) walk a run of switches from the opener to the
# quoted payload. Until DEF-717 that run was `(?:[-/][\w:]+[ \t]*)*` and could
# not cross a switch's bare VALUE, so no command position opened after
# `-Verb RunAs`, `-ExecutionPolicy Bypass` or `-WindowStyle Hidden` and the
# payload was inert to every matcher -- the elevation and policy idioms an
# agent reaches for exactly when it needs to touch a hook it does not own.
# Measured 2026-09-07 through the real hook at c1b3aee: every row in
# `_PS_VALUED_WRAPPER_WRITES` ALLOWED while the same command with
# `-ArgumentList` first, or with a valueless `-NoProfile`, DENIED.

_PS_HOOK_WRITE = "Set-Content -Path tools/cc/hooks/x.py -Value evil"

_PS_VALUED_WRAPPER_WRITES = [
    ("verb-runas-double", f'Start-Process powershell -Verb RunAs -ArgumentList "{_PS_HOOK_WRITE}"'),
    # a LITERAL payload behind the valued switch: the second site. The
    # lookbehind decides whether the single-quoted span is handed to a
    # re-parser; with the run unable to cross `RunAs` it said no and the span
    # was blanked before any matcher saw it.
    ("verb-runas-single", f"Start-Process powershell -Verb RunAs -ArgumentList '{_PS_HOOK_WRITE}'"),
    ("execpolicy-bypass", f'powershell -ExecutionPolicy Bypass -Command "{_PS_HOOK_WRITE}"'),
    ("pwsh-execpolicy-c", f'pwsh -ExecutionPolicy Bypass -c "{_PS_HOOK_WRITE}"'),
    ("windowstyle-hidden", f'Start-Process powershell -WindowStyle Hidden -ArgumentList "{_PS_HOOK_WRITE}"'),
    ("three-switches-two-values", f'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "{_PS_HOOK_WRITE}"'),
    ("value-is-a-path", f'powershell -File C:\\x.ps1 -Command "{_PS_HOOK_WRITE}"'),
    ("value-with-exe-suffix", f'Start-Process -FilePath powershell.exe -Verb RunAs -ArgumentList "{_PS_HOOK_WRITE}"'),
]

_PS_VALUELESS_WRAPPER_WRITES = [
    # the controls the measured rows were compared against: no bare value to
    # cross, so these denied before the change and must keep denying
    ("noprofile", f'powershell -NoProfile -Command "{_PS_HOOK_WRITE}"'),
    ("arglist-first", f'Start-Process powershell -ArgumentList "{_PS_HOOK_WRITE}" -Verb RunAs'),
    ("colon-bound-value", f'powershell -ExecutionPolicy:Bypass -Command "{_PS_HOOK_WRITE}"'),
    ("cmd-d-c", f'cmd /d /c "{_PS_HOOK_WRITE}"'),
]

_PS_VALUED_WRAPPER_MENTIONS = [
    # a valued switch with no write behind it, and a quoted value that IS the
    # payload: the run may cross a value, but a value alone opens nothing
    ("elevation-idiom-prose", 'Write-Output "elevate with Start-Process powershell -Verb RunAs before you touch a hook"'),
    ("quoted-value-only", 'Start-Process notepad -Verb "RunAs"'),
    ("value-then-safe-verb", "powershell -ExecutionPolicy Bypass -Command Get-Date"),
]

_PS_DECLARED_LIMITS = [
    # measured ALLOW before and after the change (failure-mode review)
    ("quoted-verb-value", f'Start-Process powershell -Verb "RunAs" -ArgumentList "{_PS_HOOK_WRITE}"'),
    ("quoted-windowstyle-value", f'Start-Process powershell -WindowStyle "Hidden" -ArgumentList "{_PS_HOOK_WRITE}"'),
    ("quoted-workingdirectory-value", f'Start-Process powershell -WorkingDirectory "C:\\Temp" -ArgumentList "{_PS_HOOK_WRITE}"'),
    ("quoted-filepath-value", f'Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList "{_PS_HOOK_WRITE}"'),
    ("equals-bound-arglist", f'Start-Process powershell -Verb RunAs -ArgumentList="{_PS_HOOK_WRITE}"'),
    ("array-arglist-double", f'Start-Process powershell -Verb RunAs -ArgumentList "-Command","{_PS_HOOK_WRITE}"'),
    ("array-arglist-single", f"Start-Process powershell -Verb RunAs -ArgumentList '-Command','{_PS_HOOK_WRITE}'"),
]

_PS_WIDENED_MENTION_TRADE = [
    ("mention-with-valued-switch-and-payload",
     "Write-Output 'Start-Process powershell -Verb RunAs Set-Content -Path tools/cc/hooks/x.py'"),
    ("commit-message-with-policy-idiom-and-payload",
     'git commit -m "powershell -ExecutionPolicy Bypass -Command Set-Content -Path tools/cc/hooks/x.py"'),
]


class TestPowerShellReparsingWrapperCarriesASwitchValue:
    """DEF-717: one bare value per switch, at both sites, no new prose refused."""

    @pytest.mark.parametrize("cmd", [c for _, c in _PS_VALUED_WRAPPER_WRITES],
                             ids=[i for i, _ in _PS_VALUED_WRAPPER_WRITES])
    def test_a_write_behind_a_valued_switch_is_denied(self, cmd, tmp_path):
        assert_hook_denied(_run_ps_guard(cmd, tmp_path))

    @pytest.mark.parametrize("cmd", [c for _, c in _PS_VALUELESS_WRAPPER_WRITES],
                             ids=[i for i, _ in _PS_VALUELESS_WRAPPER_WRITES])
    def test_the_valueless_controls_keep_denying(self, cmd, tmp_path):
        assert_hook_denied(_run_ps_guard(cmd, tmp_path))

    @pytest.mark.parametrize("cmd", [c for _, c in _PS_VALUED_WRAPPER_MENTIONS],
                             ids=[i for i, _ in _PS_VALUED_WRAPPER_MENTIONS])
    def test_a_value_alone_opens_nothing(self, cmd, tmp_path):
        assert_hook_allowed(_run_ps_guard(cmd, tmp_path))

    def test_the_lookbehind_and_the_arm_share_the_run(self):
        """The two sites must carry the SAME switch run: one crossing a value
        the other cannot is exactly the split the single-quoted row above
        fell through. Pinned on the pattern text, so an edit to one that
        forgets the other reds here before it reds a row."""
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "cc" / "hooks"))
        import _bash_patterns as bp
        run = bp._PS_SWITCH_RUN
        assert run in bp._PS_CMD_POS_EXEC_QUOTE
        assert run in bp._PS_REPARSED_SPAN_BEFORE.pattern
        # ... and the same OPENER roster: two literal copies were one edit
        # away from the same split with this pin green (failure-mode review)
        openers = bp._PS_REPARSE_OPENERS
        assert bp._PS_CMD_POS_EXEC_QUOTE.startswith(openers)
        assert bp._PS_REPARSED_SPAN_BEFORE.pattern.startswith(openers)
        # the value must end at whitespace: the lookahead is the ReDoS fix
        assert "(?=[ \\t]|$))?" in run, run
        # the value arm: one bare token that cannot start with a switch lead
        # or a quote, so a following switch or the payload quote is never
        # eaten as a value -- and (DEF-637's witness) cannot be a re-parsing
        # opener WORD, or a flood of openers reads each one as the value of
        # the switch before it and every matcher walks the run from every
        # opener (20 s at 28 KB, driven). One roster spells the refusal, the
        # arm and the lookbehind: `_PS_REPARSE_OPENER_WORDS`.
        words = bp._PS_REPARSE_OPENER_WORDS
        value_arm = "(?:[ \\t]+(?!" + words + "(?=[ \\t]|$))[^"
        assert value_arm in run and "][^\\s]*(?=[ \\t]|$))?" in run, run
        # ... plus the one opener that is not a word: a script block built
        # from a string literal (`[scriptblock]::Create(`, DEF-760) is a
        # program in both quote kinds, so it sits beside the word roster as
        # its own branch and both consumers see it through this one name.
        # (a shape, not a literal: the word roster opens the alternation, the
        # Create branch is a member, and a third non-word opener joins the
        # same alternation without this line being retyped)
        assert openers.startswith("(?:\\b" + words + "\\b|") and openers.endswith(")"), openers
        assert bp._PS_SCRIPTBLOCK_CREATE in openers, openers
        assert bp._PS_SCRIPTBLOCK_CREATE not in run   # the run's refusal stays on the words
        # and the run stays UNBOUNDED: a `{0,64}` bound was measured to buy
        # nothing once the refusal was in (the product above is the cost,
        # not the run's length) and to turn `python -B` x65 `-c "<write>"`
        # -- a command that runs -- from a deny into an allow (code review,
        # driven). `TestCrossShellRouting::test_a_long_switch_run_does_not_
        # hide_the_program` is the row a future bound reds on.
        assert run.endswith(")*"), run

    # The ReDoS pin for the run lives in `tests/test_redos.py`
    # (`test_ps_switch_value_run_linear_on_dash_bearing_values`), under the
    # SIGALRM watchdog and the CI-safe budget every timing assert there uses.
    # A first cut pinned it here, on dash-free values, with the design budget:
    # it stayed green on a regex that hung the deployed hook for 20 s.

    @pytest.mark.parametrize("cmd", [c for _, c in _PS_DECLARED_LIMITS],
                             ids=[i for i, _ in _PS_DECLARED_LIMITS])
    def test_the_declared_limits_are_pinned(self, cmd, tmp_path):
        """A quoted value, an `=`-bound value and the array spelling end the
        run before the payload, and the payload stays inert -- the fail-open
        direction, declared so nobody reads the close as the whole class.
        Detection for one of these must revise the skill and HOOKS.md, not
        just flip the row."""
        assert_hook_allowed(_run_ps_guard(cmd, tmp_path))

    @pytest.mark.parametrize("cmd", [c for _, c in _PS_WIDENED_MENTION_TRADE],
                             ids=[i for i, _ in _PS_WIDENED_MENTION_TRADE])
    def test_the_widened_mention_trade_is_recorded(self, cmd, tmp_path):
        """The exec-quote arm is deliberately unanchored, so a quoted MENTION
        that carries an opener and a write verb has always denied
        (`"powershell -Command Set-Content -Path <hook>"` inside a string).
        Crossing a valued switch widens that accepted trade to these shapes.
        Recorded, not endorsed: relieving them means anchoring the arm on a
        separator, which is the edit the module comment names as the one
        that turns the friction fix into a fail-open."""
        assert_hook_denied(_run_ps_guard(cmd, tmp_path))
