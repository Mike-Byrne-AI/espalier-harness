r"""ReDoS regression tests for write_guard inline-interpreter regexes.

Pre-fix (post-v0.6.5 adversarial review finding): the body alternation
``(?:\\.|(?!\1).)*`` in ``_PYTHON_DASH_C_RE``, ``_NODE_DASH_E_RE``,
``_RUBY_DASH_E_RE``, and ``_PERL_DASH_E_RE`` had overlapping branches —
``\\.`` matched ``\X`` (2 chars starting with backslash), and
``(?!\1).`` matched any non-quote char (including ``\``). A run of
backslashes with no closing quote produced catastrophic backtracking
(>500ms at n>=40 backslashes; CC's hook timeout is 5s, exceeded easily).

Fix: change the second branch to ``(?!\1)[^\\]`` so the two
alternatives are mutually exclusive (one consumes a leading backslash;
the other excludes backslash). Runs in linear time on worst-case input.

This module pins:

1. Each pattern completes within 100ms on a worst-case 32KB
   unclosed-quote backslash-run payload.
2. Legitimate inline-interpreter invocations still match.

Add new patterns to ``_REGEX_TARGETS`` if write_guard learns another
interpreter family.

TP-169 §13 #5 (R0 C2): the four *inner* write-target regexes
(``_PY_FILE_OPEN_RE``, ``_NODE_FS_WRITE_RE``, ``_RUBY_FILE_WRITE_RE``,
``_PERL_OPEN_RE``) run over the captured interpreter body and were
previously absent from this module — the "inner regexes are exempt"
assumption was wrong. ``_PERL_OPEN_RE`` carried a lazy
``([^'"]+?)\\s*\\1`` whose two whitespace-matching quantifiers backtracked
catastrophically on an unclosed inner quote (verified >2s @ 1k spaces,
reachable through ``_PERL_DASH_E_RE -> _PERL_OPEN_RE`` in
``_candidate_paths_from_bash`` = a live PreToolUse slow-hook fail-open).
Fixed to a greedy whitespace-excluding ``([^'"\\s]+)\\1`` capture. All four
inner regexes are now pinned linear below via ``_INNER_WRITE_TARGET_REGEXES``.
"""
from __future__ import annotations

import ast
import gc
import re
import signal
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks")
)
from write_guard import (  # noqa: E402
    _CP_MV_RE,
    _GIT_CHECKOUT_BARE_RE,
    _GIT_CHECKOUT_DASHDASH_RE,
    _GIT_RESTORE_RE,
    _HEREDOC_RE,
    _INTERP_STDIN_RE,
    _LN_S_RE,
    _NODE_DASH_E_RE,
    _NODE_FS_WRITE_RE,
    _PERL_DASH_E_RE,
    _PERL_OPEN3_RE,
    _PERL_OPEN_RE,
    _PY_DEST_ARG_WRITE_RE,
    _PY_FILE_OPEN_RE,
    _PY_PATH_WRITE_RE,
    _PYTHON_DASH_C_RE,
    _REDIRECT_RE,
    _RUBY_DASH_E_RE,
    _RUBY_FILE_WRITE_RE,
    _SED_INPLACE_RE,
    _TEE_RE,
)
import _bash_patterns  # noqa: E402
import _speedbump  # noqa: E402
import write_guard  # noqa: E402

_REGEX_TARGETS = [
    ("python", _PYTHON_DASH_C_RE, "-c"),
    ("node", _NODE_DASH_E_RE, "-e"),
    ("ruby", _RUBY_DASH_E_RE, "-e"),
    ("perl", _PERL_DASH_E_RE, "-e"),
]

# Extraction regexes that don't follow the inline-interpreter shape but
# also run over the (capped) Bash command body. None of these use a
# backreferenced quoted body — they extract simple word-shaped paths —
# so catastrophic backtracking is structurally unlikely. We still bound
# their worst-case time as belt-and-suspenders coverage.
_OTHER_BASH_EXTRACTION_REGEXES = [
    ("redirect", _REDIRECT_RE),
    ("heredoc", _HEREDOC_RE),
    ("tee", _TEE_RE),
    ("sed_inplace", _SED_INPLACE_RE),
    ("cp_mv", _CP_MV_RE),
    ("git_checkout_dashdash", _GIT_CHECKOUT_DASHDASH_RE),
    ("git_checkout_bare", _GIT_CHECKOUT_BARE_RE),
    ("git_restore", _GIT_RESTORE_RE),
    ("ln_s", _LN_S_RE),  # Round 3: symlink creation
    # DEF-698: the stdin-program opener -- a bounded argument run after `-`,
    # every adjacent quantifier pair mutually exclusive.
    ("interp_stdin", _INTERP_STDIN_RE),
    # The Bash trio's third step (447-A, 2026-09-11): the pipe-to-stdin
    # opener, the shell here-string opener, the three statement readers'
    # heads, and every call-head regex the shell-out readers run over a
    # PROGRAM body -- the literal after each is read by hand, never by a
    # regex, so these carry no literal capture to backtrack into.
    ("interp_pipe", _bash_patterns._INTERP_PIPE_RE),
    ("shell_herestring", _bash_patterns._SHELL_HERESTRING_RE),
    ("awk_head", _bash_patterns._AWK_HEAD_RE),
    ("sed_head", _bash_patterns._SED_HEAD_RE),
    ("git_head", _bash_patterns._GIT_HEAD_RE),
    ("py_shell_out_head", _bash_patterns._PY_SHELL_OUT_HEAD_RE),
    ("js_shell_out_head", _bash_patterns._JS_SHELL_OUT_HEAD_RE),
    ("perl_shell_out_head", _bash_patterns._PERL_SHELL_OUT_HEAD_RE),
    ("perl_open_pipe", _bash_patterns._PERL_OPEN_PIPE_RE),
    ("perl_qx", _bash_patterns._PERL_QX_RE),
    ("ruby_shell_out_head", _bash_patterns._RUBY_SHELL_OUT_HEAD_RE),
    ("ruby_percent_x", _bash_patterns._RUBY_PERCENT_X_RE),
    ("awk_system", _bash_patterns._AWK_SYSTEM_RE),
    ("awk_string", _bash_patterns._AWK_STRING_RE),
    ("awk_getline", _bash_patterns._AWK_GETLINE_RE),
    ("awk_pipe_to_cmd", _bash_patterns._AWK_PIPE_TO_CMD_RE),
    ("sed_e_command", _bash_patterns._SED_E_COMMAND_RE),
    ("sed_s_e_flag", _bash_patterns._SED_S_E_FLAG_RE),
    ("awk_redirect_write", _bash_patterns._AWK_REDIRECT_WRITE_RE),
    ("sed_w_command", _bash_patterns._SED_W_COMMAND_RE),
    ("sed_s_w_flag", _bash_patterns._SED_S_W_FLAG_RE),
    ("heredoc_operator", _bash_patterns._HEREDOC_OPERATOR_RE),
    # DEF-815: the find opener now also feeds the catastrophic tier (a
    # bounded span, the action and narrowing tests a second anchored pass).
    ("find_delete", _bash_patterns._FIND_DELETE_RE),
    ("find_delete_action", _bash_patterns._FIND_DELETE_ACTION_RE),
    ("find_narrowing", _bash_patterns._FIND_NARROWING_RE),
    # DEF-826: the enumerator piped through xargs into a remove verb (two
    # bounded spans, the carrier's switch run one arm per token) and its
    # witness gate
    ("piped_remove", _bash_patterns._PIPED_REMOVE_RE),
    ("piped_carrier_witness", _bash_patterns._PIPED_CARRIER_WITNESS_RE),
    # DEF-830: the loop carrier's three enumerator openers (the enumerator
    # span, the loop head with the read builtin's switch run, a bounded body
    # run before the remove verb), DEF-837's word-list opener (a bounded run
    # of words, each opening on a non-blank) and their witness gate
    ("loop_remove", _bash_patterns._LOOP_REMOVE_RE),
    ("for_subst_remove", _bash_patterns._FOR_SUBST_REMOVE_RE),
    ("tail_loop_remove", _bash_patterns._TAIL_LOOP_REMOVE_RE),
    ("for_words_remove", _bash_patterns._FOR_WORDS_REMOVE_RE),
    ("loop_carrier_witness", _bash_patterns._LOOP_CARRIER_WITNESS_RE),
]

# ``_BASH_COMMAND_CAP`` in write_guard.py caps inputs at 32 KB. The bench
# uses a body just under that cap so we exercise the realistic worst case.
_WORST_CASE_BODY_LEN = 30000
_BUDGET_MS = 100  # documented design budget (SoT for the "100ms budget" doc claim)
#
# THE WALL-CLOCK RULE, one statement for every ceiling this file asserts
# (TP-225-E set it for the regex rows; DEF-922 made it the file's, 2026-09-24):
# the design budget stays documented; the ASSERTED ceiling is a named constant
# no less than TEN times a named, dated floor -- the slowest row's timed
# window, the minimum of three serial passes on the 8 GB self-host Air,
# recorded beside it with the load it was read at; the SIGALRM bound is the
# runaway detector, and a scaling arm, where a population has one, the shape
# detector. Why ten: a shared ubuntu runner reads about 1.65x this box on
# ordinary rows and over 3x on one (Release CI 35932546999, 2026-09-23), so
# twice the floor was crossed the first day CI ran again, and three times the
# floor -- where the chain rows below sat behind the regex rows' shared line
# -- went red on the 3.14 clean-checkout cell of the release tree's closing
# witness (CI 35954967897, the `quoted_literal_flood` row, 2026-09-24). The
# rule is derived, never remembered: tests/test_proof_tier.py::
# test_every_wall_clock_ceiling_is_ten_times_a_dated_floor walks every
# `setitimer` and elapsed comparison in the serial timing files and reds on a
# literal bound, a ceiling `_WALL_CLOCK_FLOORS` does not pair, a pair no row
# asserts, a ceiling under ten times its floor, a floor whose constant and
# pairing disagree, or a floor without a past date. Two things the rule holds
# fixed (failure-mode review): the reference host is the 8 GB self-host Air
# -- a floor read elsewhere is a different number, not a re-pin -- and A
# CEILING NEVER DROPS: the pairing records each floor's value with its date,
# so a floor edited alone reds until both move together, and the contract's
# high-water table reds a ceiling below the value it was pinned at, so a floor
# re-measured on a faster host cannot lower the line a slower runner is read
# against. To re-pin: measure (three serial passes, the minimum, the load
# noted), then move the floor constant, the pairing's value and its date in
# one edit; the derived ceiling may only rise.
#
# Three tiers, keyed on the floor band of the rows that share them.
#
# The REGEX tier: an isolated compiled pattern, or a chain whose floor is
# under a tenth of the line. Floor: `test_find_delete_tier_linear_through_the_chain`'s
# `git_preopt_flood` at 82.8 ms (2026-09-24, load 1.4-1.9); the isolated
# patterns read 1-31 ms. A LINEAR pattern can momentarily exceed the 100 ms
# design budget on a loaded host; the catastrophic-backtracking regression
# these rows guard is seconds, so the line still reds a real ReDoS while
# absorbing scheduler jitter.
_REGEX_FLOOR_MS = 85
_CI_SAFE_BUDGET_MS = 1000
# The CHAIN tier: a row that drives a whole extractor or reader over a flood
# at the cap -- `_candidate_paths_from_bash`, `_candidate_paths_from_powershell`,
# the remove/relocate readers, the switch/value run, the discard-snapshot arm.
# Until 2026-09-24 these nine rows shared the regex line at three to eight
# times their floors, three of them on bare literals. Floor:
# `test_ps_program_body_linear_on_unclosed_runs`'s `quoted_literal_flood` at
# 337.6 ms (2026-09-24, load 1.4-1.9; linear: 78 / 163 / 336 ms at 7.5 / 15 /
# 30 KB); the next chain rows read 246, 231, 220 and 198 ms.
_CHAIN_FLOOR_MS = 340
_CHAIN_CEILING_MS = 10 * _CHAIN_FLOOR_MS
# The WALKER tier: the Bash inert-syntax walker's consumers at 64 KB
# (`test_bash_walker_linear_on_opener_flood` and the scaling arm beside it)
# and the three walk rows at the end of the file (the delete walk, the two
# var-expansion pre-passes) -- a live judge over a flood, memoised readers
# cleared. Floor: `test_the_delete_walk_stays_linear_through_the_chain`'s
# `heredoc_flood` at 874.8 ms (2026-09-24, load 1.4-1.9; 577 / 871 ms min /
# max of five on 2026-09-23); the walker's `mixed_openers` 606.9 ms the same
# day (605.1 on 2026-09-22 at load 1.7-1.9, 540.6 / 600 at TP-454's
# authoring). The ceiling was first set at no less than twice the walker's
# floor, and a shared ubuntu runner exceeded it on `close_brace_run` the first
# day CI ran again (Release CI 35932546999, 2026-09-23); it was ten times
# that floor from then, and since 2026-09-24 ten times the tier's slowest row
# -- still well under the minutes a quadratic walker took before the fix,
# which is all it has to catch: the scaling arm is the detector for SHAPE
# (DEF-817), and this ceiling only catches a runaway.
_WALKER_FLOOR_MS = 880
_WALKER_CEILING_MS = 10 * _WALKER_FLOOR_MS

#: Every ceiling this file asserts, paired with the floor it is sized against,
#: the date that floor was read, and the floor's value at the pin. The contract
#: derives the ceilings from the timer and comparison sites, so a ceiling
#: missing here, or listed here and asserted nowhere, reds; a bound that is not
#: one of these names reds too; and a floor constant that disagrees with the
#: value recorded here reds until the constant, the value and the date move
#: together.
_WALL_CLOCK_FLOORS: dict[str, tuple[str, str, int]] = {
    "_CI_SAFE_BUDGET_MS": ("_REGEX_FLOOR_MS", "2026-09-24", 85),
    "_CHAIN_CEILING_MS": ("_CHAIN_FLOOR_MS", "2026-09-24", 340),
    "_WALKER_CEILING_MS": ("_WALKER_FLOOR_MS", "2026-09-24", 880),
}


class _Timeout(Exception):
    pass


def _alarm(_signum, _frame) -> None:
    raise _Timeout()


@pytest.mark.parametrize("name,pattern,flag", _REGEX_TARGETS)
def test_regex_linear_on_backslash_run(name, pattern, flag):
    """Pattern completes within 100ms on a 30KB unclosed-quote
    backslash-run payload.

    POSIX-only — uses ``signal.alarm`` which is unavailable on Windows.
    """
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    body = "\\" * _WORST_CASE_BODY_LEN
    payload = f'{name} {flag} "{body}'

    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        pattern.findall(payload)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(
            f"{name} regex exceeded {_CI_SAFE_BUDGET_MS}ms on 30KB backslash-run "
            f"payload (catastrophic backtracking — ReDoS regressed)"
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, (
        f"{name} regex took {elapsed_ms:.1f}ms (budget {_CI_SAFE_BUDGET_MS}ms)"
    )


@pytest.mark.parametrize("name,pattern,flag", _REGEX_TARGETS)
def test_regex_linear_on_mixed_escape_run(name, pattern, flag):
    """Pattern completes within 100ms on a mixed escape-sequence + quote
    payload (the second known catastrophic-backtracking shape)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    chunk = '\\"abc\\\\'  # 8 chars: \" a b c \\ — each can be parsed as escape or literal
    body = chunk * (_WORST_CASE_BODY_LEN // len(chunk))
    payload = f'{name} {flag} "{body}'

    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        pattern.findall(payload)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(
            f"{name} regex exceeded {_CI_SAFE_BUDGET_MS}ms on mixed-escape payload"
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS


@pytest.mark.parametrize(
    "name,pattern,flag,payload",
    [
        ("python", _PYTHON_DASH_C_RE, "-c",
         'python -c "open(\'/etc/passwd\',\'w\')"'),
        ("python", _PYTHON_DASH_C_RE, "-c",
         'python3 -B -c "import os; os.makedirs(\'/tmp/x\')"'),
        ("node", _NODE_DASH_E_RE, "-e",
         'node -e "require(\'fs\').writeFileSync(\'/etc/passwd\',\'x\')"'),
        ("ruby", _RUBY_DASH_E_RE, "-e",
         'ruby -e "File.write(\'/etc/passwd\',\'x\')"'),
        ("perl", _PERL_DASH_E_RE, "-e",
         'perl -e "open(F,\'>\',\'/etc/passwd\')"'),
        ("python", _PYTHON_DASH_C_RE, "-c",
         'python -c "print(\\"hi\\")"'),  # escaped quote in body
        # DEF-832: a program operand of adjacent segments is one word
        ("python", _PYTHON_DASH_C_RE, "-c",
         "python3 -c 'import os; os.system(\"cp x '\"'\"'y'\"'\"'\")'"),
        ("python", _PYTHON_DASH_C_RE, "-c", "python3 -c 'print(1)'\"; print(2)\"'; print(3)'"),
        ("node", _NODE_DASH_E_RE, "-e", "node -e 'console.log(1)'x'; console.log(2)'"),
    ],
)
def test_regex_still_matches_legitimate_input(name, pattern, flag, payload):
    """The ReDoS fix must not regress the detection behavior."""
    assert pattern.search(payload) is not None, (
        f"{name} {flag} regex no longer matches legitimate payload "
        f"after ReDoS fix: {payload!r}"
    )


# ── Sister-site ReDoS coverage for other write_guard extraction regexes ─────
#
# Surfaced by the post-v0.6.6 adversarial review: the BOM bypass + ReDoS
# fixes covered the four inline-interpreter regexes, but adversarial-
# reviewer flagged that other extraction patterns running over the same
# 32KB-capped Bash command body should be audited too. None of these
# patterns use a backreferenced quoted body (the structural source of
# catastrophic backtracking we fixed), but bounding their worst-case
# time as a regression pin is cheap insurance against future refactor
# drift that might introduce the pattern shape.


@pytest.mark.parametrize("name,pattern", _OTHER_BASH_EXTRACTION_REGEXES)
def test_other_extraction_regex_linear_on_long_input(name, pattern):
    """Each non-interpreter extraction regex completes within
    ``_CI_SAFE_BUDGET_MS`` on a 30KB pathological-ish input (``_BUDGET_MS`` is
    the documented design budget; the asserted line is the CI-safe ceiling).

    We test three shapes:
      - very long whitespace (stresses ``\\s+`` quantifiers)
      - very long path-like word (stresses character classes like
        ``[^\\s<>|&;]+``)
      - long alternation of redirect / tee / pipe tokens
    """
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    payloads = [
        " " * _WORST_CASE_BODY_LEN,
        "a" * _WORST_CASE_BODY_LEN,
        ("> /tmp/foo " * (_WORST_CASE_BODY_LEN // 12))[:_WORST_CASE_BODY_LEN],
    ]
    for payload in payloads:
        signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
        t = time.time()
        try:
            pattern.findall(payload)
            elapsed_ms = (time.time() - t) * 1000
        except _Timeout:
            pytest.fail(
                f"{name} regex exceeded {_CI_SAFE_BUDGET_MS}ms on a "
                f"{_WORST_CASE_BODY_LEN}-byte payload"
            )
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        assert elapsed_ms < _CI_SAFE_BUDGET_MS, (
            f"{name} regex took {elapsed_ms:.1f}ms on a "
            f"{_WORST_CASE_BODY_LEN}-byte payload "
            f"(budget {_CI_SAFE_BUDGET_MS}ms)"
        )


# ── Inner write-target regex ReDoS coverage (TP-169 §13 #5 / R0 C2) ─────────
#
# The four inner regexes extract a quoted literal write path out of an
# interpreter ``-e``/``-c`` body (the OUTER regexes above capture the body;
# these scan it). Pre-TP-169 they were absent from this module on the wrong
# assumption that "literal-string-only" inner patterns can't ReDoS.
# ``_PERL_OPEN_RE`` disproved that: its lazy ``([^'"]+?)\s*\1`` had two
# whitespace-matching quantifiers straddling a single whitespace run, so an
# unclosed inner quote backtracked catastrophically. Each tuple's prefix opens
# the regex's quoted write-path literal but never closes it, so the path
# capture runs to the end of the payload — the worst case for backtracking.

_INNER_WRITE_TARGET_REGEXES = [
    ("py_open", _PY_FILE_OPEN_RE, "open('"),
    ("node_write", _NODE_FS_WRITE_RE, "writeFileSync('"),
    ("ruby_write", _RUBY_FILE_WRITE_RE, "File.write('"),
    ("perl_open", _PERL_OPEN_RE, "open(F, '>"),
    # DEF-813: the three-argument spelling; the path literal opens after the
    # second comma and never closes
    ("perl_open3", _PERL_OPEN3_RE, "open(my $fh, '>', '"),
    ("perl_open3_read", _bash_patterns._PERL_OPEN3_READ_RE, "open(my $fh, '<', '"),
    # DEF-698: the pathlib and destination-argument writers.
    ("py_path_write", _PY_PATH_WRITE_RE, "Path('"),
    ("py_dest_arg", _PY_DEST_ARG_WRITE_RE, "shutil.copy('/tmp/x', '"),
]


@pytest.mark.parametrize("name,pattern,prefix", _INNER_WRITE_TARGET_REGEXES)
def test_inner_write_target_regex_linear(name, pattern, prefix):
    """Each inner write-target regex completes within ``_CI_SAFE_BUDGET_MS`` (the
    asserted ceiling; ``_BUDGET_MS`` is the documented design budget) on a 30KB
    unclosed-quote payload, in both a whitespace-run and a printable-run shape.

    The whitespace-run shape is the exact pre-fix ``_PERL_OPEN_RE`` killer
    (a quote/whitespace overlap); the printable-run stresses the greedy class.
    POSIX-only — uses ``signal.alarm`` (unavailable on Windows).
    """
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    for body in (" " * _WORST_CASE_BODY_LEN, "a" * _WORST_CASE_BODY_LEN):
        payload = prefix + body
        signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
        t = time.time()
        try:
            pattern.findall(payload)
            elapsed_ms = (time.time() - t) * 1000
        except _Timeout:
            pytest.fail(
                f"{name} inner regex exceeded {_CI_SAFE_BUDGET_MS}ms on a 30KB "
                f"unclosed-quote payload (catastrophic backtracking — "
                f"ReDoS in an inner write-target regex)"
            )
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        assert elapsed_ms < _CI_SAFE_BUDGET_MS, (
            f"{name} inner regex took {elapsed_ms:.1f}ms (budget {_CI_SAFE_BUDGET_MS}ms)"
        )


def test_perl_open_re_earns_the_red_on_unclosed_inner_quote():
    """Earn-the-red for TP-169 R0 C2 directly through the live extraction
    chain: the documented attack (``perl -e "open(F, '> <space-run>"``, outer
    double-quote closing, inner single-quote unclosed) must complete fast.

    Pre-fix this hung >2s @ 1k spaces / timed out @ 2k (a PreToolUse
    slow-hook fail-open); the SIGALRM bound here is `_CI_SAFE_BUDGET_MS`, so the pre-fix regex
    fails this test and the fixed regex passes (measured <1ms).
    """
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    # Import the real extraction chain — proves reachability, not just the
    # isolated regex.
    from _bash_patterns import _candidate_paths_from_bash  # noqa: E402

    command = 'perl -e "open(F, ' + "'>" + (" " * 8000) + '"'
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        _candidate_paths_from_bash(command)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(
            f"_candidate_paths_from_bash exceeded {_CI_SAFE_BUDGET_MS}ms on the perl unclosed-"
            "inner-quote ReDoS payload — PreToolUse slow-hook fail-open "
            "(TP-169 R0 C2 regressed)"
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS


@pytest.mark.parametrize("mode_run", [">", "+", ">+"])
def test_perl_open_re_linear_on_mode_char_run(mode_run):
    """Regression for the v1 ReDoS that the first C2 fix re-introduced.

    The first fix (``[>+]+\\s*([^'"\\s]+)\\1``) traded the whitespace overlap for
    a mode-char overlap: ``[>+]`` is a subset of ``[^'"\\s]``, so an unclosed
    inner quote after a ``>``/``+`` run (``perl -e "open(F,'>>>>...``) split the
    mode run O(n) ways -> quadratic (3.7s @ 16k through the chain). The
    whitespace-run / ``'a'``-run cases above CANNOT catch this because their
    first path char is never a mode char. The v2 fix excludes mode chars from
    the path's first position. Driven end-to-end through the real chain with a
    CLOSED outer quote (so ``_PERL_DASH_E_RE`` matches and the inner regex runs).
    """
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    from _bash_patterns import _candidate_paths_from_bash  # noqa: E402

    n = 16000 // len(mode_run)
    # closed outer double-quote; unclosed inner single-quote; mode-char run
    command = 'perl -e "open(F,' + "'" + (mode_run * n) + '"'
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        _candidate_paths_from_bash(command)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(
            f"_candidate_paths_from_bash exceeded {_CI_SAFE_BUDGET_MS}ms on a {mode_run!r}-run "
            "perl ReDoS payload — the C2 fix re-introduced quadratic "
            "backtracking via a mode-char/path-class overlap (TP-169 §13 #5 v1)"
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS


@pytest.mark.parametrize(
    "shape,make_body",
    [
        # a1: leading-whitespace run between `open` and `(` (the v2 prefix
        # double-whitespace-around-optional-paren split).
        ("prefix-space-run", lambda n: "open" + " " * n + "(F,'>a"),
        # a2: many `open(` tokens — finditer retries at each, greedy \S+
        # backtracks (the v2 prefix; closed by the (-excluding filehandle).
        ("many-open-paren", lambda n: "open(" * (n // 5) + "X,'>a"),
        # b1: `openopen...` with no comma — finditer retries at every `open`
        # literal, each an O(remaining) scan (closed by the word-boundary
        # lookbehind so only the first `open` is a valid start).
        ("repeated-open-no-comma", lambda n: "open" * (n // 4)),
    ],
)
def test_perl_open_re_linear_on_prefix_shapes(shape, make_body):
    """Regression for the v2 PREFIX ReDoS the third C2 adversarial round found.

    v0/v1/v2 all hardened the regex TAIL; the prefix
    ``open\\s*\\(?\\s*\\S+\\s*,\\s*`` still went quadratic three ways — a leading
    space run (5s @ 31k = the 5s PreToolUse timeout = fail-open), many ``open(``
    tokens, and a comma-less ``openopen`` run (finditer re-scanning at every
    ``open``). The v3 fix (word-boundary lookbehind + single-whitespace prefix +
    paren/comma-excluding filehandle) makes all linear. Driven end-to-end through
    the real chain with a CLOSED outer quote so ``_PERL_DASH_E_RE`` matches.
    """
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    from _bash_patterns import _candidate_paths_from_bash  # noqa: E402

    command = 'perl -e "' + make_body(28000) + '"'
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        _candidate_paths_from_bash(command)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(
            f"_candidate_paths_from_bash exceeded {_CI_SAFE_BUDGET_MS}ms on the {shape!r} perl "
            "prefix ReDoS payload — _PERL_OPEN_RE prefix went quadratic "
            "(TP-169 §13 #5 v2)"
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS


@pytest.mark.parametrize(
    "name,pattern,payload,expected_path",
    [
        ("py_open", _PY_FILE_OPEN_RE,
         "python -c \"open('/etc/passwd', 'w')\"", "/etc/passwd"),
        ("node_write", _NODE_FS_WRITE_RE,
         "node -e \"require('fs').writeFileSync('/tmp/x', 'd')\"", "/tmp/x"),
        ("ruby_write", _RUBY_FILE_WRITE_RE,
         "ruby -e \"File.write('/tmp/y', 'd')\"", "/tmp/y"),
        # The four legit perl write forms must still extract their path.
        ("perl_open_trunc", _PERL_OPEN_RE,
         "perl -e \"open(FH, '>tools/cc/hooks/write_guard.py')\"",
         "tools/cc/hooks/write_guard.py"),
        ("perl_open_append", _PERL_OPEN_RE,
         "perl -e \"open(FH, '>>.claude/settings.json')\"",
         ".claude/settings.json"),
        ("perl_open_readwrite", _PERL_OPEN_RE,
         "perl -e \"open(FH, '+>/tmp/z')\"", "/tmp/z"),
        ("perl_open_lead_space", _PERL_OPEN_RE,
         "perl -e \"open(FH, '> cc/PACK_MANIFEST.txt')\"",
         "cc/PACK_MANIFEST.txt"),
        # DEF-698: the pathlib writers and the destination-argument family.
        ("py_path_write_text", _PY_PATH_WRITE_RE,
         "Path('tools/cc/hooks/x.py').write_text('x')", "tools/cc/hooks/x.py"),
        ("py_path_open_w", _PY_PATH_WRITE_RE,
         "pathlib.Path('.claude/settings.json').open('w')", ".claude/settings.json"),
        ("py_dest_shutil_copy", _PY_DEST_ARG_WRITE_RE,
         "shutil.copy('/tmp/x', 'tools/cc/hooks/x.py')", "tools/cc/hooks/x.py"),
        ("py_dest_os_replace", _PY_DEST_ARG_WRITE_RE,
         "os.replace(\"/tmp/s\", \".claude/settings.json\")", ".claude/settings.json"),
    ],
)
def test_inner_write_target_regex_still_matches(name, pattern, payload, expected_path):
    """The ReDoS fix must not regress inner-regex extraction: the legit write
    forms still match and the captured path is unchanged.

    ``_PERL_OPEN_RE``'s path is group 2 (group 1 is the quote); the py/node/
    ruby regexes also carry the path in group 2.
    """
    m = pattern.search(payload)
    assert m is not None, f"{name} no longer matches legitimate payload: {payload!r}"
    assert m.group(2) == expected_path, (
        f"{name} extracted {m.group(2)!r}, expected {expected_path!r}"
    )


# ── Verb-anchored extraction regex ReDoS class (TP-169 §13 #5) ──────────────
#
# Six extraction regexes shaped ``\bVERB...<span>...<required token>`` are
# quadratic on a repeated verb (``sed sed sed...``): finditer retries the verb
# at every space-separated occurrence, each scanning an unbounded span toward an
# ABSENT required token -> O(verbs * remaining). Measured ~2.5s through the chain
# at the 32KB cap (the third C2 adversarial round). The fix bounds each span
# (``{0,512}`` chars / ``{0,64}`` tokens). These pins drive the REAL chain (the
# authoritative reachability) and assert the chain ceiling on a ~28KB repeated-verb payload.
# `_SED_INPLACE_RE` / `_GIT_CHECKOUT_DASHDASH_RE` are already imported from
# write_guard above; `_DD_OF_RE` / `_TAR_C_RE` / `_PS_PATH_FLAG_RE` are not
# re-exported, so pull them from _bash_patterns. (`_CP_MV_INSTALL_TARGET_DIR_RE`
# was here until 2026-09-05: the target-directory flag is read by
# `_target_directory_value` on the tokenizer now, a linear walk, not a regex.)
from _bash_patterns import (  # noqa: E402
    _BASH_COMMAND_CAP,
    _CHMOD_CHOWN_RE,
    _candidate_paths_from_bash,
    _candidate_paths_from_powershell,
    _DD_OF_RE,
    _POWERSHELL_DASH_COMMAND_RE,
    _PS_BASH_DASH_C_RE,
    _PS_DOTNET_FILE_RE,
    _PS_ITEM_PROPERTY_ASSIGN_RE,
    _ROLE_MAP_CAP,
    mask_inert_syntax,
    _PS_COPY_MOVE_DEST_RE,
    _PS_COPY_MOVE_POSITIONAL_RE,
    _PS_COPY_MOVE_SRC_FLAG_RE,
    _PS_HERE_STRING_RE,
    _PS_INTERP_STDIN_RE,
    _PS_NODE_DASH_E_RE,
    _PS_PATH_FLAG_RE,
    _PS_PERL_DASH_E_RE,
    _PS_PERMISSION_RE,
    _PS_PROGRAM_STRING_RE,
    _PS_PYTHON_DASH_C_RE,
    _PS_RUBY_DASH_E_RE,
    _TAR_C_RE,
)

# (name, repeated-verb token that never completes the required token)
_VERB_EXTRACTION_REGEXES = [
    ("sed_inplace", _SED_INPLACE_RE, "sed"),
    ("dd_of", _DD_OF_RE, "dd"),
    ("tar_c", _TAR_C_RE, "tar"),
    ("git_dashdash", _GIT_CHECKOUT_DASHDASH_RE, "git checkout x"),
    # DEF-638 matcher, registered the day it landed.
    ("chmod_chown", _CHMOD_CHOWN_RE, "chmod"),
    # DEF-712 lane: the Bash inline openers took a valued switch run; a flood
    # of valued switches that never reaches `-c`.
    ("python_dash_c_switches", _PYTHON_DASH_C_RE, "python -W ignore"),
    # DEF-832: the program operand is a shell WORD of adjacent segments; a
    # flood of quoted-then-bare segments, of double-quoted ones, of ANSI-C
    # ones, a flood of openers each carrying a short word, and a word that
    # never closes its last quote -- on the interpreter opener, the POSIX
    # shell opener and the PowerShell command opener
    ("python_dash_c_segments", _PYTHON_DASH_C_RE, "python -c 'a'b"),
    ("python_dash_c_dq_segments", _PYTHON_DASH_C_RE, "python -c \"a\"b"),
    ("python_dash_c_ansi_segments", _PYTHON_DASH_C_RE, "python -c $'a'b"),
    ("python_dash_c_segment_flood", _PYTHON_DASH_C_RE, "'a'b"),
    ("python_dash_c_unclosed_tail", _PYTHON_DASH_C_RE, "python -c 'a'\"b"),
    ("shell_dash_c_segments", _bash_patterns._SHELL_DASH_C_RE, "sh -c 'a'b"),
    ("shell_dash_c_segment_flood", _bash_patterns._SHELL_DASH_C_RE, "'a'b"),
    ("powershell_dash_command_segments", _POWERSHELL_DASH_COMMAND_RE, "pwsh -Command 'a'b"),
    ("powershell_dash_command_segment_flood", _POWERSHELL_DASH_COMMAND_RE, "'a'b"),
    # DEF-827: the scan rewrite that resolves a discovered command to the
    # verb it names, registered the day it landed -- a flood of discovered
    # heads (each a `_CMD_POS_NO_VERB` prefix run with a failing tail once the
    # verb repeats), of unclosed substitutions, and of the backtick form
    ("bash_discovered_head", _bash_patterns._BASH_DISCOVERED_HEAD_RE, "$(which find)"),
    ("bash_discovered_head_unclosed", _bash_patterns._BASH_DISCOVERED_HEAD_RE, "$(which"),
    ("bash_discovered_head_backtick", _bash_patterns._BASH_DISCOVERED_HEAD_RE, "`which find`"),
]

# PowerShell verb regexes: same isolated pin, but their CHAIN arm must drive
# `_candidate_paths_from_powershell` -- `ps_path_flag` sat in the bash list and
# its chain arm timed the bash entrypoint, which never reaches these (DEF-638
# failure-mode pass). Nothing else times the PowerShell extractor end to end.
_PS_VERB_EXTRACTION_REGEXES = [
    ("ps_path_flag", _PS_PATH_FLAG_RE, "Set-Content"),
    # `truncate` on the PowerShell tool (the write extractor's native arm)
    ("ps_truncate", _bash_patterns._PS_TRUNCATE_RE, "truncate"),
    ("ps_truncate_sizes", _bash_patterns._PS_TRUNCATE_RE, "truncate -s 0"),
    # DEF-814's sibling: the three git materialise arms on the PowerShell
    # head, the Bash tails composed once (the Bash arms are budgeted above)
    ("ps_git_dashdash", _bash_patterns._PS_GIT_CHECKOUT_DASHDASH_RE, "git checkout x"),
    ("ps_git_bare", _bash_patterns._PS_GIT_CHECKOUT_BARE_RE, "git checkout -x"),
    ("ps_git_restore", _bash_patterns._PS_GIT_RESTORE_RE, "git restore -x"),
    # DEF-827: the scan rewrite that resolves a call on a command object to
    # the verb it names -- a flood of objects, of unclosed sub-expressions,
    # and of the -Name switch with no verb behind it
    ("ps_command_object_head", _bash_patterns._PS_COMMAND_OBJECT_HEAD_RE, "& (gcm find)"),
    ("ps_command_object_unclosed", _bash_patterns._PS_COMMAND_OBJECT_HEAD_RE, "& (Get-Command"),
    ("ps_command_object_name_switch", _bash_patterns._PS_COMMAND_OBJECT_HEAD_RE, "& (gcm -Name"),
    ("ps_copy_move_dest", _PS_COPY_MOVE_DEST_RE, "Copy-Item"),
    ("ps_copy_move_positional", _PS_COPY_MOVE_POSITIONAL_RE, "Copy-Item -x"),
    ("ps_copy_move_src_flag", _PS_COPY_MOVE_SRC_FLAG_RE, "-Path"),
    # The per-match statement-segment slice in the -Destination leg is O(n)
    # per match: a repeated ";"-terminated destination is its worst case, and
    # `_cap_for_scan` is what keeps the product linear.
    ("ps_copy_move_dest_segments", _PS_COPY_MOVE_DEST_RE, "Copy-Item -Destination x;"),
    # DEF-697 matcher, registered the day it landed: both grammars, since the
    # per-verb operand walk (`_ps_permission_targets`) runs on each match.
    ("ps_permission_attrib", _PS_PERMISSION_RE, "attrib +R"),
    # DEF-717: the exec-quote arm's switch run may carry one bare value per
    # switch (a nested quantifier). This repeated-opener row is the cheap
    # shape; the WORST case -- one opener, a long run of values holding `-` or
    # `/` -- is `test_ps_switch_value_run_linear_on_dash_bearing_values` below.
    ("ps_exec_switch_value_run", _PS_PATH_FLAG_RE, "powershell -Verb RunAs"),
    ("ps_permission_set_acl", _PS_PERMISSION_RE, "Set-Acl -Path:"),
    # DEF-712: the interpreter arm, registered the day it landed -- each
    # opener on its repeated head, the exe-path prefix on a repeated quoted
    # path, the piped-stdin opener on a repeated pipe.
    ("ps_python_dash_c", _PS_PYTHON_DASH_C_RE, "python -c"),
    ("ps_node_dash_e", _PS_NODE_DASH_E_RE, "node -e"),
    ("ps_ruby_dash_e", _PS_RUBY_DASH_E_RE, "ruby -e"),
    ("ps_perl_dash_e", _PS_PERL_DASH_E_RE, "perl -e"),
    ("ps_exe_prefix_quoted", _PS_PYTHON_DASH_C_RE, "& 'C:\\a\\b\\python.exe' -c"),
    ("ps_exe_prefix_bare", _PS_PERMISSION_RE, "C:\\a\\b\\attrib.exe +R"),
    ("ps_interp_stdin", _PS_INTERP_STDIN_RE, "| python -"),
    ("ps_interp_stdin_switches", _PS_INTERP_STDIN_RE, "| pwsh -NoProfile -Command -;"),
    ("ps_python_switch_values", _PS_PYTHON_DASH_C_RE, "python -W ignore"),
    # DEF-637 (§C49), registered the day they landed: the cross-shell openers
    # on their repeated heads and repeated switch runs, and the two coverage
    # matchers (DEF-730 / DEF-733) on a repeated head that never closes.
    ("ps_bash_dash_c", _PS_BASH_DASH_C_RE, "bash -c"),
    ("ps_bash_dash_c_switches", _PS_BASH_DASH_C_RE, "bash --norc -x"),
    # the clustered `-lc`: the switch run and the cluster arm overlap on it,
    # and the run gives it back one token at a time -- one pass (review)
    ("ps_bash_dash_lc_cluster", _PS_BASH_DASH_C_RE, "bash -lc"),
    ("ps_bash_cluster_flood", _PS_BASH_DASH_C_RE, "-lc"),
    ("ps_bash_exe_prefix", _PS_BASH_DASH_C_RE, "& 'C:\\a\\b\\bash.exe' -c"),
    ("ps_dotnet_file", _PS_DOTNET_FILE_RE, "[IO.File]::WriteAllText("),
    ("ps_item_property_assign", _PS_ITEM_PROPERTY_ASSIGN_RE, "(Get-Item x"),
    # A flood of re-parse openers whose switch VALUE is the next opener word
    # (`-Command powershell -Command powershell ...`): the shared switch run
    # read every following pair as switch-plus-value, O(n) at each of the n
    # command positions -- 24 s at 28 KB, one second at 6 KB, at HEAD before
    # DEF-637's witness row found it. The run is bounded at 64 tokens now
    # (the receipt's remedy); the DEF-717 dash-bearing rows could not see
    # this shape because their values were never opener words.
    ("ps_exec_switch_value_is_an_opener", _PS_PATH_FLAG_RE, "powershell -Command"),
]

# The Bash-tool shell opener's rows, in the BASH list: its chain arm drives
# `_candidate_paths_from_bash`, the entrypoint that runs it.
_VERB_EXTRACTION_REGEXES += [
    ("powershell_dash_command", _POWERSHELL_DASH_COMMAND_RE, "powershell -Command"),
    ("powershell_dash_command_switches", _POWERSHELL_DASH_COMMAND_RE, "pwsh -NoProfile -ExecutionPolicy Bypass"),
]

# §C52 (2026-09-14), registered the day they landed: the remove/relocate
# operand arms on both shells. Each on its repeated head (the isolated pin
# above), and below through the READER that runs it -- the zone check runs
# the readers beside the write extractor, so the write chain never reaches
# these arms.
_C52_BASH_ROWS = [
    ("destroy", _bash_patterns._DESTROY_RE, "rm"),
    ("destroy_quoted_verb", _bash_patterns._DESTROY_RE, '"rm"'),
    ("rename", _bash_patterns._RENAME_RE, "rename"),
    ("zip", _bash_patterns._ZIP_RE, "zip"),
    ("git_rm_mv", _bash_patterns._GIT_RM_MV_RE, "git rm"),
    ("tar_create", _bash_patterns._TAR_CREATE_RE, "tar"),
    ("find_delete", _bash_patterns._FIND_DELETE_RE, "find"),
    ("find_delete_predicates", _bash_patterns._FIND_DELETE_RE, "find x -name"),
    # DEF-826: the carrier pipeline -- a repeated head, a pipe flood, the
    # switch run on a repeated valued switch and on a bare-switch flood
    ("piped_remove", _bash_patterns._PIPED_REMOVE_RE, "find"),
    ("piped_remove_pipes", _bash_patterns._PIPED_REMOVE_RE, "find x |"),
    ("piped_remove_switches", _bash_patterns._PIPED_REMOVE_RE, "find . | xargs -n 1"),
    ("piped_remove_switch_flood", _bash_patterns._PIPED_REMOVE_RE, "-0"),
    ("piped_remove_wrappers", _bash_patterns._PIPED_REMOVE_RE, "find . | sudo xargs sudo"),
    # DEF-831: the version-control listing head -- the head flooded before
    # the pipe, a repeated global-option run before the subcommand, and the
    # whole head repeated
    ("piped_remove_listing_pipes", _bash_patterns._PIPED_REMOVE_RE, "git ls-files |"),
    ("piped_remove_listing_preopts", _bash_patterns._PIPED_REMOVE_RE, "git -C . "),
    ("piped_remove_listing_quoted_preopts", _bash_patterns._PIPED_REMOVE_RE, 'git -C "a b" '),
    ("piped_remove_listing_open_quote", _bash_patterns._PIPED_REMOVE_RE, 'git -C "a b '),
    ("piped_remove_listing_heads", _bash_patterns._PIPED_REMOVE_RE, "git ls-files"),
    # DEF-830: the loop carrier -- a repeated head, a pipe flood, the read
    # builtin's switch run, a flood of body statements before the verb, a
    # flood of keywords; the for head on a substitution flood; the tail-fed
    # head on a flood of loop closers
    ("loop_remove", _bash_patterns._LOOP_REMOVE_RE, "find"),
    ("loop_remove_pipes", _bash_patterns._LOOP_REMOVE_RE, "find x |"),
    ("loop_remove_heads", _bash_patterns._LOOP_REMOVE_RE, "find . | while read"),
    ("loop_remove_read_switches", _bash_patterns._LOOP_REMOVE_RE, "find . | while read -r"),
    ("loop_remove_body_statements", _bash_patterns._LOOP_REMOVE_RE, "find . | while read f; do echo;"),
    ("loop_remove_keywords", _bash_patterns._LOOP_REMOVE_RE, "do "),
    ("for_subst_remove", _bash_patterns._FOR_SUBST_REMOVE_RE, "for f in $(find"),
    ("for_subst_remove_heads", _bash_patterns._FOR_SUBST_REMOVE_RE, "for f in $("),
    ("for_subst_remove_body_statements", _bash_patterns._FOR_SUBST_REMOVE_RE, "for f in $(find .); do echo;"),
    ("tail_loop_remove", _bash_patterns._TAIL_LOOP_REMOVE_RE, "while read f; do rm -rf $f; done < <(find"),
    ("tail_loop_remove_closers", _bash_patterns._TAIL_LOOP_REMOVE_RE, "done <"),
    ("tail_loop_remove_heads", _bash_patterns._TAIL_LOOP_REMOVE_RE, "while read"),
    # DEF-837: the word-list head -- a repeated head (the later ones read as
    # WORDS behind the first, so the word run floods), a flood of heads each
    # on its own command position, an open double quote (the quoted-word
    # arm), a flood of body statements before the verb
    ("for_words_remove", _bash_patterns._FOR_WORDS_REMOVE_RE, "for f in"),
    ("for_words_remove_heads", _bash_patterns._FOR_WORDS_REMOVE_RE, "for f in x;"),
    ("for_words_remove_open_quote", _bash_patterns._FOR_WORDS_REMOVE_RE, 'for f in "a'),
    ("for_words_remove_escapes", _bash_patterns._FOR_WORDS_REMOVE_RE, "for f in \\x"),
    ("for_words_remove_body_statements", _bash_patterns._FOR_WORDS_REMOVE_RE, "for f in *; do echo;"),
    ("dd_if", _bash_patterns._DD_IF_RE, "dd"),
    # the Bash-tool shell opener: repeated heads, a switch run, the `-lc`
    # cluster the run and the cluster arm overlap on, and a bare cluster flood
    ("shell_dash_c", _bash_patterns._SHELL_DASH_C_RE, "sh -c"),
    ("shell_dash_c_switches", _bash_patterns._SHELL_DASH_C_RE, "bash --norc -x"),
    ("shell_dash_lc_cluster", _bash_patterns._SHELL_DASH_C_RE, "bash -lc"),
    ("shell_cluster_flood", _bash_patterns._SHELL_DASH_C_RE, "-lc"),
    # the review batch: a long option in the run, `c` first in the cluster,
    # and the git clean arm on its repeated head
    ("shell_dash_c_long_option", _bash_patterns._SHELL_DASH_C_RE, "bash --norc"),
    ("shell_dash_c_long_option_valued", _bash_patterns._SHELL_DASH_C_RE, "bash --rcfile x"),
    ("shell_dash_cx_cluster", _bash_patterns._SHELL_DASH_C_RE, "bash -cx"),
    ("git_clean", _bash_patterns._GIT_CLEAN_RE, "git clean"),
    # the here-string opener shares the switch run: its unbounded form read a
    # shell head word as a switch value and was quadratic on a repeated head
    # (4.0 s at 28 KB through the write extractor, witnessed by the row above
    # the day the `-c` opener landed beside it)
    ("shell_herestring_repeated_head", _bash_patterns._SHELL_HERESTRING_RE, "sh -c"),
    ("shell_herestring_switches", _bash_patterns._SHELL_HERESTRING_RE, "bash --norc -x"),
    ("shell_herestring_opener", _bash_patterns._SHELL_HERESTRING_RE, "bash <<<"),
]
_C52_PS_ROWS = [
    ("ps_rename", _bash_patterns._PS_RENAME_RE, "Rename-Item"),
    ("ps_piped_remove", _bash_patterns._PS_PIPED_REMOVE_RE, "Get-ChildItem"),
    ("ps_piped_remove_pipes", _bash_patterns._PS_PIPED_REMOVE_RE, "gci x |"),
    ("ps_piped_remove_carrier", _bash_patterns._PS_PIPED_REMOVE_RE, "gci . | xargs -n 1"),
    ("ps_piped_remove_carrier_flood", _bash_patterns._PS_PIPED_REMOVE_RE, "-0"),
    ("ps_piped_remove_listing", _bash_patterns._PS_PIPED_REMOVE_RE, "git -C . ls-files |"),
    ("ps_piped_remove_listing_heads", _bash_patterns._PS_PIPED_REMOVE_RE, "git ls-files"),
    ("ps_git_rm_mv", _bash_patterns._PS_GIT_RM_MV_RE, "git rm"),
    ("ps_compress_archive", _bash_patterns._PS_COMPRESS_ARCHIVE_RE, "Compress-Archive"),
    # the find family on the PowerShell tool (DEF-824): the head with its
    # wrapper run and exe prefix, and the predicate-flood shape
    ("ps_find_delete", _bash_patterns._PS_FIND_DELETE_RE, "find"),
    ("ps_find_delete_wrapped", _bash_patterns._PS_FIND_DELETE_RE, "sudo find"),
    ("ps_find_delete_predicates", _bash_patterns._PS_FIND_DELETE_RE, "find . -name x"),
    # the native single-file deletes and git clean on the PowerShell tool
    ("ps_native_destroy", _bash_patterns._PS_NATIVE_DESTROY_RE, "unlink"),
    ("ps_native_destroy_wrapped", _bash_patterns._PS_NATIVE_DESTROY_RE, "sudo shred -u"),
    ("ps_git_clean", _bash_patterns._PS_GIT_CLEAN_RE, "git clean"),
]
_VERB_EXTRACTION_REGEXES += _C52_BASH_ROWS
_PS_VERB_EXTRACTION_REGEXES += _C52_PS_ROWS
_INNER_WRITE_TARGET_REGEXES += [
    # the inner MUTATION and READ tables (§C52): the same unclosed-quote
    # prefix shape as the write rows above
    ("py_os_mutate", _bash_patterns._PY_OS_MUTATE_RE, "os.remove('"),
    ("py_path_mutate", _bash_patterns._PY_PATH_MUTATE_RE, "Path('"),
    ("node_mutate", _bash_patterns._NODE_FS_MUTATE_RE, "unlinkSync('"),
    ("ruby_mutate", _bash_patterns._RUBY_FILE_MUTATE_RE, "File.delete('"),
    ("perl_mutate", _bash_patterns._PERL_MUTATE_RE, "unlink '"),
    ("py_open_read", _bash_patterns._PY_FILE_OPEN_READ_RE, "open('"),
    ("py_path_read", _bash_patterns._PY_PATH_READ_RE, "Path('"),
    ("node_read", _bash_patterns._NODE_FS_READ_RE, "readFileSync('"),
    ("ruby_read", _bash_patterns._RUBY_FILE_READ_RE, "File.read('"),
    ("perl_open_read", _bash_patterns._PERL_OPEN_READ_RE, "open(F, '<"),
]


@pytest.mark.parametrize("tool,name,verb", (
    [("Bash", n, v) for n, _p, v in _C52_BASH_ROWS]
    + [("PowerShell", n, v) for n, _p, v in _C52_PS_ROWS]
))
def test_mutation_reader_linear_through_chain(tool, name, verb):
    """End-to-end for the remove/relocate readers (§C52): a ~28KB repeated-verb
    command stays inside the chain ceiling through `iter_removed_or_relocated_operands` /
    `iter_ps_removed_or_relocated_operands` -- the entry points the zone and
    secret checks run, with the mask, the cap, the per-match span readers and
    the nested-program recursion."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    reader = (
        _bash_patterns.iter_removed_or_relocated_operands if tool == "Bash"
        else _bash_patterns.iter_ps_removed_or_relocated_operands
    )
    command = (verb + " ") * (28000 // (len(verb) + 1))
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CHAIN_CEILING_MS / 1000.0)
    t = time.time()
    try:
        reader(command)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(
            f"the {tool} remove/relocate reader exceeded {_CHAIN_CEILING_MS}ms on a repeated {verb!r} "
            f"command -- verb-regex ReDoS class ({name}) regressed"
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CHAIN_CEILING_MS


@pytest.mark.parametrize("label,payload", [
    # DEF-637: the Bash-tool shell opener's three program arms, unclosed --
    # a single-quoted body of anything but a quote, a double-quoted body of
    # backslashes (every one an escape), the mixed run, and a bare program
    # that never meets a separator -- and a FLOOD of openers through the
    # whole Bash extractor, which is what the hook runs.
    ("sq_unclosed", "pwsh -c '" + "x" * _WORST_CASE_BODY_LEN),
    ("dq_backslash_run", 'pwsh -c "' + "\\" * _WORST_CASE_BODY_LEN),
    ("dq_mixed_run", 'pwsh -c "' + '\\"a\\\\' * (_WORST_CASE_BODY_LEN // 5)),
    ("ansi_backslash_run", "pwsh -c $'" + "\\" * _WORST_CASE_BODY_LEN),
    ("ansi_escaped_quote_run", "pwsh -c $'" + "\\'" * (_WORST_CASE_BODY_LEN // 2)),
    ("bare_unbounded", "powershell -Command " + "x " * (_WORST_CASE_BODY_LEN // 2)),
    ("switch_run_flood", "powershell " + "-Command x " * (_WORST_CASE_BODY_LEN // 11)),
    # an UNBOUNDED switch run that never reaches a program, then the switchless
    # positional form as a flood of openers
    ("switch_run_no_program", "pwsh " + "-NoLogo " * (_WORST_CASE_BODY_LEN // 8)),
    ("slash_switch_run_no_program", "powershell " + "/NoLogo " * (_WORST_CASE_BODY_LEN // 8)),
    ("positional_flood", "powershell 'x'; " * (_WORST_CASE_BODY_LEN // 16)),
    ("opener_flood", "pwsh -c 'x'; " * (_WORST_CASE_BODY_LEN // 13)),
    ("route_flood", "pwsh -c 'bash -c \"pwsh -c x\"'; " * (_WORST_CASE_BODY_LEN // 30)),
])
def test_shell_opener_linear_on_unclosed_runs(label, payload):
    """The cross-shell opener's arms are mutually exclusive (`[^']` closed by
    the quote; `\\\\.` vs `[^\\\\"]`; a bounded bare class), so an unclosed
    program costs one pass, and the routing is depth-bounded so a flood of
    nested openers costs a bounded number of extractor runs."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CHAIN_CEILING_MS / 1000.0)
    t = time.time()
    try:
        _POWERSHELL_DASH_COMMAND_RE.findall(payload)
        _candidate_paths_from_bash(payload)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(f"{label}: the shell opener exceeded {_CHAIN_CEILING_MS}ms")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CHAIN_CEILING_MS, f"{label}: {elapsed_ms:.1f}ms"


@pytest.mark.parametrize("pattern,payload", [
    (_POWERSHELL_DASH_COMMAND_RE, 'powershell -Command "Set-Content -Path x -Value 1"'),
    (_POWERSHELL_DASH_COMMAND_RE, "pwsh -NoProfile -c 'Get-Date'"),
    (_POWERSHELL_DASH_COMMAND_RE, "powershell -Command Get-Date"),
    (_PS_BASH_DASH_C_RE, 'bash -c "echo x > y"'),
    (_PS_BASH_DASH_C_RE, "& 'C:\\Program Files\\Git\\bin\\bash.exe' -c 'ls'"),
    (_PS_DOTNET_FILE_RE, "[IO.File]::WriteAllText('x', 'y')"),
    (_PS_DOTNET_FILE_RE, "[System.IO.Directory]::Delete('x', $true)"),
    (_PS_ITEM_PROPERTY_ASSIGN_RE, "(Get-Item x).IsReadOnly = $true"),
    (_PS_ITEM_PROPERTY_ASSIGN_RE, "(gi -Path x).Attributes += 'Hidden'"),
])
def test_shell_routing_and_coverage_regexes_still_match(pattern, payload):
    assert pattern.search(payload) is not None, payload


# The program string's worst cases, each a builder over the body length so
# the ceiling row and the scaling arm below drive the same shapes at two
# sizes: an unclosed single-quoted body made of doubled quotes (escape or
# close, at every pair), an unclosed double-quoted body of backticks (every
# one an escape), and the mixed run; the opener never completes, so every
# branch is exercised.
_PS_BODY_FLOODS: list[tuple[str, Callable[[int], str]]] = [
    ("sq_doubled_quote_run", lambda n: "python -c '" + "''" * (n // 2)),
    ("dq_backtick_run", lambda n: 'python -c "' + "`" * n),
    ("dq_mixed_run", lambda n: 'python -c "' + '`"a""' * (n // 5)),
    # a segment full of here-string openers with ONE terminator at the end
    ("here_string_openers", lambda n: "@'\n" * (n // 3) + "'@ | pwsh -c -"),
    # a FLOOD of piped-stdin openers through the extractor, which is what the
    # hook runs: the first cut read the whole prefix as each opener's segment
    # and re-scanned it for every shell head -- seven seconds on 856 bytes,
    # past the hook's timeout, with a real protected write in front (review,
    # driven). The isolated-regex rows above could not see it.
    ("stdin_pwsh_flood",
     lambda n: "Set-Content -Path tools/cc/hooks/x.py -Value x" + "|pwsh" * (n // 5)),
    ("stdin_py_flood", lambda n: "x" + "|py -" * (n // 5)),
    ("stdin_here_string_flood", lambda n: "@'\nx\n'@|pwsh -c -;" * (n // 16)),
    # a flood of LITERAL spans with no pipe at all: the masker's re-parse
    # lookbehind read the whole prefix for every one (quadratic; 1.6 s at
    # this size before the lookback was bounded)
    ("literal_span_flood", lambda n: "$a = @'\nx\n'@; " * (n // 16)),
    ("quoted_literal_flood", lambda n: "$a = 'x'; " * (n // 10)),
    # a flood of EXPANDABLE spans (DEF-753): the double-quoted branch now asks
    # the same bounded lookbehind, but only for a span with a separator or an
    # escape in it -- an ordinary quoted argument is masked identically in
    # both modes and skips it (review, measured 4.4 ms to 83 ms at 32 KB
    # before the skip). The second row has a separator in every span, so the
    # lookback is asked for each and its cost has a witness.
    ("dq_span_flood", lambda n: "".join('Write-Output "a%d"; ' % i for i in range(n // 20))),
    ("dq_separator_span_flood", lambda n: 'Write-Output "a;1"; ' * (n // 20)),
]


def _ps_body(payload: str) -> None:
    """What the ceiling row and the scaling arm time: the two program-body
    patterns, then the whole extractor, which is what the hook runs."""
    _PS_PROGRAM_STRING_RE.findall(payload)
    _PS_HERE_STRING_RE.search(payload)
    _candidate_paths_from_powershell(payload)


@pytest.mark.parametrize("label,make", _PS_BODY_FLOODS)
def test_ps_program_body_linear_on_unclosed_runs(label, make):
    """DEF-712: the PowerShell program string and the here-string body are
    mutually-exclusive alternations, so an unclosed literal costs one pass,
    and a flood of piped-stdin openers costs one boundary pass. Driven
    through the whole extractor, which is what the hook runs. A CHAIN row:
    `quoted_literal_flood` is the chain tier's recorded floor, and at the
    regex rows' shared 1 s line it read red on a 3.14 clean-checkout runner
    (DEF-922's fifth site, CI 35954967897, 2026-09-24)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    payload = make(_WORST_CASE_BODY_LEN)
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CHAIN_CEILING_MS / 1000.0)
    t = time.time()
    try:
        _ps_body(payload)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(f"{label}: the PowerShell program body exceeded {_CHAIN_CEILING_MS}ms")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CHAIN_CEILING_MS, f"{label}: {elapsed_ms:.1f}ms"


# The scaling arm beside the chain ceiling: the detector for SHAPE (DEF-817),
# in the speedbump file's pair form. A flood at the cap costs at most
# `_PS_BODY_LINEAR_RATIO` times the same flood at half the cap plus a noise
# floor, both judged net of the per-call cost measured on THIS host (the
# walker row's lesson: a memoised reader's rebuild scales with the host, not
# the payload -- about 1 ms here, over a hundred on a shared runner). A pair
# whose half-cap reading is under the sample floor is not judged: single-digit
# milliseconds are clock noise on this box.
_PS_BODY_LINEAR_RATIO = 3.0
_PS_BODY_NOISE_FLOOR_MS = 1.0
_PS_BODY_MIN_SAMPLE_MS = 5.0
_PS_BODY_SAMPLES = 3


def _min_ps_body_ms(fn: Callable[[str], object], payload: str) -> float | None:
    """The floor of `_PS_BODY_SAMPLES` timings of one call, the memoised
    readers cleared before each and the cyclic collector paused throughout,
    restored after (the walker discipline); None when a call overran
    `_CHAIN_CEILING_MS`."""
    best: float | None = None
    collector_was_on = gc.isenabled()
    gc.disable()
    try:
        for _ in range(_PS_BODY_SAMPLES):
            _clear_walker_caches()
            signal.signal(signal.SIGALRM, _alarm)
            signal.setitimer(signal.ITIMER_REAL, _CHAIN_CEILING_MS / 1000.0)
            t0 = time.perf_counter()
            try:
                fn(payload)
                signal.setitimer(signal.ITIMER_REAL, 0)
                elapsed_ms = (time.perf_counter() - t0) * 1000
            except _Timeout:
                return None
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
            best = elapsed_ms if best is None else min(best, elapsed_ms)
    finally:
        if collector_was_on:
            gc.enable()
    return best


def _ps_body_scaling_verdict(
    fn: Callable[[str], object], big: str, small: str, zero: str,
) -> str | None:
    """None when the pair reads linear; otherwise the sentence naming the
    reading -- super-linear on two windows, an overrun, or a half-cap sample
    under the floor, which is a RED with its remedy and never a silent pass
    (the walker arm's discipline; the speedbump arm's None-under-the-floor is
    right for regex rows whose whole cost is single-digit milliseconds and
    wrong for a population whose smallest label reads 14 ms net -- failure-mode
    review). A pair over the bound is asked again as a second window judged on
    its own, and the window with the lower ratio is the estimate (noise
    inflates the big sample). ``zero`` is the warm, near-empty call whose cost
    is the per-call rebuild on this host, subtracted from every sample."""
    t_zero = _min_ps_body_ms(fn, zero)
    if t_zero is None:
        return f"exceeded {_CHAIN_CEILING_MS}ms on the zero-payload call"

    def window() -> tuple[float, float] | None:
        t_s = _min_ps_body_ms(fn, small)
        t_b = _min_ps_body_ms(fn, big)
        return None if t_s is None or t_b is None else (t_s, t_b)

    def under_floor(t_s: float, which: str) -> str:
        return (
            f"{t_s:.1f}ms at {len(small)} bytes ({t_s - t_zero:.1f}ms net of the {t_zero:.1f}ms "
            f"per-call cost) is under the {_PS_BODY_MIN_SAMPLE_MS}ms sample floor{which}, so its "
            "ratio cannot be judged: this host is much faster than the one the floors were "
            "measured on (re-measure), the body got cheaper (re-measure), or the payload is "
            "too small for its shape (resize it); never widen the bound"
        )

    first = window()
    if first is None:
        return f"exceeded {_CHAIN_CEILING_MS}ms"
    t_small, t_big = first
    net_small, net_big = t_small - t_zero, t_big - t_zero
    if net_small < _PS_BODY_MIN_SAMPLE_MS:
        return under_floor(t_small, "")
    bound = _PS_BODY_LINEAR_RATIO * net_small + _PS_BODY_NOISE_FLOOR_MS
    if net_big <= bound:
        return None
    second = window()
    if second is None:
        return f"exceeded {_CHAIN_CEILING_MS}ms on the second window"
    t_small_2, t_big_2 = second
    net_small_2, net_big_2 = t_small_2 - t_zero, t_big_2 - t_zero
    if net_small_2 < _PS_BODY_MIN_SAMPLE_MS:
        return under_floor(t_small_2, " on the second window")
    if net_big_2 / net_small_2 < net_big / net_small:
        net_small, net_big = net_small_2, net_big_2
        bound = _PS_BODY_LINEAR_RATIO * net_small + _PS_BODY_NOISE_FLOOR_MS
        if net_big <= bound:
            return None
    return (
        f"{net_small:.1f}ms at {len(small)} bytes -> {net_big:.1f}ms at {len(big)} bytes, "
        f"net of the {t_zero:.1f}ms per-call cost (ratio {net_big / net_small:.2f}, "
        f"bound {bound:.1f}ms): super-linear on two windows"
    )


@pytest.mark.parametrize("label,make", _PS_BODY_FLOODS)
def test_ps_program_body_scales_linearly_on_unclosed_runs(label, make):
    """The shape detector beside the chain ceiling: at one size the ceiling
    cannot tell a linear body that is slow from a quadratic one that is
    short, and a ceiling ten times the floor hides a real ten-fold regression
    outright. Each flood at the cap is judged against the same flood at half
    the cap (measured 2026-09-24: `quoted_literal_flood` 78 / 163 / 336 ms at
    7.5 / 15 / 30 KB, ratio about two; the smallest label reads 14 ms net at
    half the cap). A pair under the sample floor reds naming the remedy,
    never passes silently. Who: the adopter whose hook a quadratic body
    would time out on a pasted command the ceiling still passed."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    verdict = _ps_body_scaling_verdict(
        _ps_body, make(_WORST_CASE_BODY_LEN), make(_WORST_CASE_BODY_LEN // 2), make(64),
    )
    assert verdict is None, f"{label}: {verdict}"


def test_ps_body_scaling_rule_still_reds_a_quadratic_stand_in():
    """The must-trip control for the pair rule, on every host: a stand-in
    whose cost is quadratic in the payload -- 40 ms at the cap, 10 at half,
    spun on the clock and never slept, so the reading does not depend on the
    host's speed -- reads about four on both windows, and the rule names it
    at sizes the ceiling row alone would pass."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    n_big = _WORST_CASE_BODY_LEN

    def quadratic(payload: str) -> None:
        cost = 40.0 * (len(payload) / n_big) ** 2
        end = time.perf_counter() + cost / 1000.0
        while time.perf_counter() < end:
            pass

    verdict = _ps_body_scaling_verdict(quadratic, "x" * n_big, "x" * (n_big // 2), "x" * 64)
    assert verdict is not None and "super-linear" in verdict, verdict


def test_ps_body_scaling_rule_reds_a_pair_under_the_sample_floor():
    """A body too cheap to judge is a red with its remedy, not a silent pass:
    a stand-in that costs nothing reads under the sample floor at half the
    cap, and the rule says so rather than acquitting it."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    n_big = _WORST_CASE_BODY_LEN
    verdict = _ps_body_scaling_verdict(lambda _p: None, "x" * n_big, "x" * (n_big // 2), "x" * 64)
    assert verdict is not None and "sample floor" in verdict and "never widen" in verdict, verdict


def test_the_ps_body_scaling_arm_cannot_outlast_the_per_test_timeout():
    """A re-pin that lifts `_CHAIN_CEILING_MS` could let one label's worst case
    -- the zero call and two windows of two sizes, `_PS_BODY_SAMPLES` each,
    every call capped by the alarm at the ceiling -- outlast pytest's per-test
    `timeout`, and a timeout kill reports no reading at all (failure-mode
    review). Derived from pyproject.toml, never copied."""
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"^\s*timeout\s*=\s*(\d+)\s*$", text, re.MULTILINE)
    assert match, "pyproject.toml declares no pytest timeout"
    worst_ms = _PS_BODY_SAMPLES * 5 * _CHAIN_CEILING_MS
    assert worst_ms < int(match.group(1)) * 1000, (worst_ms, match.group(1))


# ── the Bash inert-syntax WALKER, not a regex (DEF-754) ──────────────────────
#
# Every budget above times a compiled pattern; the walker that fronts them --
# `mask_inert_syntax` -> `_walk_shell_roles` -- is a function, so no ReDoS gate
# could see it. Measured 2026-09-10 on the self-host box: on a run of unmatched
# grouping characters the head capture scanned the whole remainder once per
# character (53 ms at 1 KB, 3.3 s at 8 KB, about 53 s at 32 KB), ahead of the
# recursive-delete check, the protected-write extractors and every speed-bump
# predicate -- a slow-hook shape on the tier maintenance mode cannot bypass.
#
# The flood is sized to the WALKER'S bound, `_ROLE_MAP_CAP` (64 KB), not the
# 32 KB `_BASH_COMMAND_CAP`: that cap is `_cap_for_scan`'s, which the
# extraction leg applies, while the dangerous-reason leg and the speed-bump
# predicates hand the walker the raw command (review) -- though part of each
# of those walks is extraction-capped too, which is why the SCALING row
# below sizes every consumer by the cap it is DECLARED under in
# `_WALKER_CONSUMERS` (by measurement) while this ceiling row runs them all
# at the walker's own bound. Derived, so it follows the cap if it moves --
# the sibling `_SPEEDBUMP_FLOOD_LEN` in tests/test_speedbump_irreversible.py
# carries the same reasoning.
_WALKER_FLOOD_LEN = _ROLE_MAP_CAP - 64

# One MAKER per flood, a function of the byte count, so one list sizes both
# walker rows: the ceiling row's population is every maker at
# `_WALKER_FLOOD_LEN`, and the scaling row sizes each consumer at a half and a
# quarter of its own cap. Derived, not copied (a flood added here is in both
# rows), and the ceiling row's payloads are byte-for-byte the literals this
# list replaced -- asserted against the previous module at the change
# (TP-454 3-C).
_WALKER_FLOOD_MAKERS = [
    ("open_paren_run", lambda n: "iex " + "(" * n),
    ("close_paren_run", lambda n: "iex " + ")" * n),
    ("open_brace_run", lambda n: "iex " + "{" * n),
    ("close_brace_run", lambda n: "iex " + "}" * n),
    # the pasted stack of command substitutions the ledger row names
    ("substitution_stack", lambda n: "echo " + "$(" * (n // 2)),
    ("mixed_openers", lambda n: "x" + "({" * (n // 2)),
    # a run of `#` behind a glued brace: `_opens_comment` refuses the opener
    # (a brace is not in its opener set), so the comment branch scanned the
    # run once per `#` and stayed armed (failure-mode review)
    ("hash_run_after_brace", lambda n: "echo hi{" + "#" * n),
    ("hash_run_after_bare_brace", lambda n: "a>{" + "#" * n),
    # DEF-848's lane: the walker steps over an assignment word to where bash
    # ends it, masking each quoted piece of the value, and the command-position
    # arm reads the same pieces -- every quote kind, an escaped blank, a
    # separator inside the value, and a run that ends on an unterminated quote
    ("single_quoted_assignment_run", lambda n: "A='a b' " * (n // 8)),
    ("double_quoted_assignment_run", lambda n: 'A="a b" ' * (n // 8)),
    ("ansi_c_assignment_run", lambda n: "A=$'a b' " * (n // 9)),
    ("escaped_blank_assignment_run", lambda n: "A=a\\ b " * (n // 7)),
    ("separator_in_value_run", lambda n: "A='a;b'; " * (n // 9)),
    ("assignment_run_then_unterminated", lambda n: "A='a b' " * (n // 8 - 1) + "A='x"),
]

_WALKER_FLOODS = [(label, make(_WALKER_FLOOD_LEN)) for label, make in _WALKER_FLOOD_MAKERS]

# The five consumers the PreToolUse path pays for a Bash command, each reaching
# the walker through its own string: the masker itself; the protected-write
# extractor (through `_cap_for_scan`'s head-and-tail splice); the
# dangerous-reason leg (raw); a speed-bump predicate (through
# `_masked_command`, raw); the zone tier's removed-or-relocated reader.
# Hand-listed with that reason, the way the sibling populations name theirs:
# the other `_masked_command` call sites share the one walk these rows time.
#
# The third field is the CAP the consumer's walk is bounded by, which sizes
# the scaling row's two payloads (`_walker_sizes`: the largest flood under
# the cap, and half of it): above its cap a consumer measures flat, and a
# quadratic part hides there. A consumer is
# declared under the SMALLEST cap any part of its walk is bounded by, and the
# declaration is by measurement, not by reading the outer call path. The two
# ratios beside each entry are its per-doubling times from 16 KB to 32 KB and
# from 32 KB to 64 KB on `open_brace_run` under the scaling row's own
# discipline (warm, caches cleared, the minimum of three), 2026-09-22 on the
# self-host box at load 1.7 (TP-454 3-C): near 2 is linear, near 1 is the
# cap. `bash_dangerous_reason` and `speedbump_forcepush` hand the walker the
# raw command, yet part of each walk is extraction-capped (1.62 and 1.31
# above 32 KB against 2.0 below it), so both are declared under
# `_BASH_COMMAND_CAP`; only the masker is linear to `_ROLE_MAP_CAP`.
_WALKER_CONSUMERS = [
    # 2.02 / 2.09 -- linear to the walker's own cap
    ("mask_inert_syntax", lambda cmd, root: mask_inert_syntax(cmd), _ROLE_MAP_CAP),
    # 2.00 / 1.01 -- `_extractor_pair` -> `_cap_for_scan`
    ("candidate_paths_from_bash", lambda cmd, root: _candidate_paths_from_bash(cmd),
     _BASH_COMMAND_CAP),
    # 2.05 / 1.62 -- partly capped
    ("bash_dangerous_reason", lambda cmd, root: write_guard._bash_dangerous_reason(cmd, root),
     _BASH_COMMAND_CAP),
    # 2.05 / 1.31 -- partly capped
    ("speedbump_forcepush",
     lambda cmd, root: _speedbump._pred_forcepush("Bash", {"command": cmd}, root),
     _BASH_COMMAND_CAP),
    # the zone tier's removed-or-relocated reader (the fifth consumer, DEF-830's
    # review: it runs every mutation arm on every Bash call, the loop openers
    # behind their witness gate among them, and was never timed here)
    # 2.01 / 1.00 -- `_extractor_pair` -> `_cap_for_scan`
    ("removed_or_relocated_operands",
     lambda cmd, root: _bash_patterns.iter_removed_or_relocated_operands(cmd),
     _BASH_COMMAND_CAP),
]


def test_bash_walker_consumers_still_do_the_work(tmp_path):
    """The must-trip control for the budget rows below: a consumer that
    short-circuited on the bare root they run under would pass a timing row
    without walking anything (failure-mode review)."""
    assert write_guard._bash_dangerous_reason("rm -rf /", tmp_path) is not None
    assert _speedbump._pred_forcepush(
        "Bash", {"command": "git push --force origin main"}, tmp_path) is True
    assert _candidate_paths_from_bash("echo x > tools/cc/hooks/x.py")
    assert mask_inert_syntax("echo 'a;b'") == "echo 'a b'"
    assert ("delete", "tools/cc/hooks/x.py") in _bash_patterns.iter_removed_or_relocated_operands(
        "rm -rf tools/cc/hooks/x.py")


@pytest.mark.parametrize("label,payload", _WALKER_FLOODS, ids=[r[0] for r in _WALKER_FLOODS])
def test_bash_walker_linear_on_opener_flood(label, payload, tmp_path):
    """The walker and every consumer in front of the verdict finish a
    64 KB grouping-character flood inside the walker ceiling. RED before the
    fix on every row: the alarm fired at one second of a run that would have
    taken minutes. Every consumer is measured even after one overruns, so a
    red names all of them (failure-mode review). The ceiling is
    `_WALKER_CEILING_MS`, ten times the recorded floor, and catches only a
    runaway: the scaling row below is the detector for shape (DEF-817)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    overruns: list[str] = []
    for name, consumer, _cap in _WALKER_CONSUMERS:
        signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, _WALKER_CEILING_MS / 1000.0)
        t = time.perf_counter()
        try:
            consumer(payload, tmp_path)
            elapsed_ms = (time.perf_counter() - t) * 1000
        except _Timeout:
            overruns.append(f"{name}: exceeded {_WALKER_CEILING_MS}ms")
            continue
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        if elapsed_ms >= _WALKER_CEILING_MS:
            overruns.append(f"{name}: {elapsed_ms:.1f}ms")
    assert not overruns, f"{label}: " + "; ".join(overruns)


# The scaling arm (DEF-817). The ceiling row above cannot tell a linear
# consumer that is slow from a quadratic one that is short: its worst consumer
# spends more than half of a 1 s budget on a quiet box, so a loaded host reds
# a watch row that saw no regression, while a quadratic consumer that happens
# to finish inside the ceiling passes it. This arm times each consumer at
# the largest flood under the cap its walk is bounded by (the third field
# of `_WALKER_CONSUMERS`; the ceiling row's own sizing rule, so the masker's
# large payload IS the ceiling row's) and at half of that, and holds the
# large time to `_WALKER_LINEAR_RATIO` times the small one plus a noise
# allowance: a linear consumer measures about 2 per doubling, a quadratic
# one about 4, and three is the midpoint. Evidence for the bound, measured
# 2026-09-22 on the 8 GB self-host box at load 1.7 under exactly this
# discipline (TP-454 3-C quotes the driver): 2.00-2.05 per doubling for
# every consumer from 16 KB to 32 KB under the cap and 2.09 for the masker
# from 32 KB to 64 KB, while the extraction-capped consumers went flat
# (1.00-1.01) above 32 KB -- the cap each declaration records. Sizing
# from a quarter and a half of the cap instead (the first draft) put the
# masker at 4.3 ms on its cheapest floods, under any floor that can judge
# it. The timing discipline, each part pinned or driven below:
#   * each consumer is WARMED once on a 64-byte payload before it is timed
#     (the first call pays regex compilation: cold, the speed-bump predicate
#     measured five times its warm cost at the pack's authoring);
#   * the walker's memoised readers (`_WALKER_MEMOISED_READERS`: every
#     `lru_cache` the hook modules define, derived rather than listed) are
#     cleared before EVERY timed call, so a repeated payload cannot read back
#     from a cache (0.0 ms on a second call at authoring);
#   * each payload is timed `_WALKER_SAMPLES` times and the MINIMUM kept: the
#     cost of a deterministic walk is its floor, and a scheduler spike on one
#     call is additive noise (a single 16 KB masker call read 25.8 ms against
#     4.5, 18.9 and 35.7 at the neighbouring sizes on the execution day);
#   * a small-size time under `_WALKER_MIN_SAMPLE_MS` is a RED naming the
#     consumer and its sizes, never a pass: a consumer in the noise cannot be
#     judged, and the fix is to re-declare its cap, never to widen the bound;
#   * the cyclic collector is PAUSED (`gc.disable`, restored after) around
#     every sample: its full collections cost in proportion to the host's live
#     heap, and a larger payload's allocations cross a collection threshold
#     the smaller one's do not, so inside a long pytest process the large
#     sample alone carries the host's collection cost and a linear consumer
#     reads super-linear. Measured 2026-09-23: the release matrix's serial
#     stage 02 (45 minutes of suite in one process) read
#     `_bash_dangerous_reason` at 162.7 -> 496.1 ms on open_paren_run (ratio
#     3.05; 162.9 -> 498.4 the run before, so not a burst -- the first draft
#     called it one and added the second window below on that reading), while
#     a fresh process reads 163 -> 331 (2.03) on the dev tree and on the
#     extracted archive alike; a 4M-object ballast heap in a fresh process
#     moved only the large sample (162 -> 359, 2.22); with the collector
#     paused under the same ballast, 158 -> 319 (2.02). `gc.freeze` reads the
#     same (2.01) but its thaw promotes the young generations into the oldest
#     one (verified on 3.14), a residue the pause does not leave. A hook
#     process starts with a small heap and never pays that term, so it is not
#     the consumer's cost. The CEILING row above deliberately stays a single
#     unpaused sample: its 2000 ms sits at more than three times the recorded
#     floor and only has to catch a runaway, so the host term eats margin it
#     can spare -- do not pause it for symmetry, and do not widen the ceiling
#     on a stage-02 reading; this arm is the shape detector;
#   * a super-linear reading is CONFIRMED on a second, later window before it
#     reds, and the windows are judged as PAIRS -- the window with the lower
#     ratio is the estimate, and the sample floor is asked again of a chosen
#     second window. Taking the fastest small and the fastest big across
#     windows cannot read below the better window's own ratio
#     (min_big / min_small >= min(r1, r2) under either assignment of the
#     minima), so the mixed estimate the first draft used could confirm a red
#     and never rescue one. The cost of the pair rule, stated beside its
#     benefit: it is strictly MORE permissive -- one clean window now acquits
#     a reading the mixed estimate would have confirmed -- which is why the
#     rows below drive a quadratic stand-in through it (about 4 on EVERY
#     window, still red) as the must-trip control. The second window survives
#     the burst story that first justified it because a one-sided stall (fast
#     small samples, large ones at cost) is a real shape, pinned below.
# The two floors are coupled by the detection inequality: a quadratic
# consumer at small time t measures about 4t, and the bound admits
# 3t + noise, so it is caught only while t exceeds the noise floor; the
# sample floor is twice the noise floor so a consumer judged at the floor
# still overruns the bound by a full noise floor. (The first draft set both
# at 5 ms, where a quadratic consumer at the floor passes exactly; the
# second set 2 and 4 ms, which left the masker's cheapest floods 2.1x over
# the sample floor -- a box twice as fast would red them.) A 1 ms allowance
# is the per-call overhead plus the jitter that survives a minimum of three:
# the warm table's minima agreed to a few tenths of a millisecond, and the
# masker's cheapest small sample (8.6 ms at 32 KB) sits 4x over the floor.
# The FLAT bound is the other refutation: a consumer that measures near 1
# per doubling between its two sizes is bounded by a SMALLER cap than the
# one declared beside it (a length guard added later, say) and measured
# nothing -- the row reds naming it, so the declaration is re-measured
# instead of the detector retiring silently (failure-mode review). Linear
# consumers measured 2.00-2.09; the partly-capped two measured 1.31 and
# 1.62 ABOVE the 32 KB cap they are declared under: the shape this catches.
_WALKER_LINEAR_RATIO = 3.0
_WALKER_FLAT_RATIO = 1.5
_WALKER_NOISE_FLOOR_MS = 1.0  # jitter, additive; the per-call cost is MEASURED per run (see the scaling row)
_WALKER_MIN_SAMPLE_MS = 2 * _WALKER_NOISE_FLOOR_MS
_WALKER_SAMPLES = 3


def _walker_sizes(cap: int) -> tuple[int, int]:
    """The scaling row's (large, small) byte counts for a consumer bounded
    by ``cap``: the largest flood under the cap by the ceiling row's own rule
    (``_WALKER_FLOOD_LEN`` is ``_ROLE_MAP_CAP - 64``), and half of it."""
    big = cap - 64
    return big, big // 2

# Every lru_cache-wrapped callable the three hook modules define -- the
# readers a repeated payload would hit. Derived from the modules so a reader
# memoised tomorrow is cleared without an edit here; the pin below names the
# five that existed at authoring so a renamed one is caught.
_WALKER_MEMOISED_READERS = tuple(
    obj
    for mod in (_bash_patterns, write_guard, _speedbump)
    for obj in vars(mod).values()
    if hasattr(obj, "cache_clear")
    and getattr(getattr(obj, "__wrapped__", None), "__module__", None) == mod.__name__
)


def _clear_walker_caches() -> None:
    for reader in _WALKER_MEMOISED_READERS:
        reader.cache_clear()


def _min_walker_ms(
    consumer: Callable[[str, Path], object], payload: str, root: Path,
) -> float | None:
    """The floor of `_WALKER_SAMPLES` timings of one call, caches cleared
    before each and the cyclic collector paused throughout, restored after
    (the discipline above: a long pytest process's full collections are the
    host's cost, and only the larger payload triggers them); None when a call overran
    `_WALKER_CEILING_MS` (the alarm fires inside the call, so a runaway
    costs one ceiling, not minutes)."""
    best: float | None = None
    collector_was_on = gc.isenabled()
    gc.disable()
    try:
        for _ in range(_WALKER_SAMPLES):
            _clear_walker_caches()
            signal.signal(signal.SIGALRM, _alarm)
            signal.setitimer(signal.ITIMER_REAL, _WALKER_CEILING_MS / 1000.0)
            t0 = time.perf_counter()
            try:
                consumer(payload, root)
                elapsed_ms = (time.perf_counter() - t0) * 1000
            except _Timeout:
                return None
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
            best = elapsed_ms if best is None else min(best, elapsed_ms)
    finally:
        if collector_was_on:
            gc.enable()
    return best


@pytest.mark.parametrize("label,make", _WALKER_FLOOD_MAKERS, ids=[r[0] for r in _WALKER_FLOOD_MAKERS])
def test_bash_walker_scales_linearly_on_opener_flood(label, make, tmp_path):
    """Each consumer's cost at the largest flood under its cap is at most
    `_WALKER_LINEAR_RATIO` times its cost at half of that, plus the noise floor,
    and no less than `_WALKER_FLAT_RATIO` times it (a flat reading says the walk
    is bounded below its declared cap and nothing was measured) -- DEF-817:
    the ceiling row cannot tell a linear consumer that is slow from
    a quadratic one that is short, and this row can. Who: the maintainer whose
    tier reds on the ceiling row under load and spends a run bisecting a
    regression that is not there, and the adopter whose hook a quadratic
    walker would time out on a pasted command the ceiling still passed. RED
    against a stand-in consumer that rescans the remainder once per position
    (ratio about 4) while the ceiling row passes it at `_WALKER_CEILING_MS`,
    and GREEN again on the same stand-in with the ratio at 5.0, so the bound
    is load-bearing (TP-454 3-C records both runs). Every consumer is
    measured even after one fails, so a red names all of them.

    Both ratios are judged NET of a measured per-call cost, and both arms get
    a second window. The first CI runs after Actions came back (2026-09-23)
    read `mixed_openers` on a shared 3.13 runner as 241.5 -> 284.2 ms, ratio
    1.18, and called it flat: every sample clears the memoised readers and
    pays their rebuild, a cost that scales with the host, not the payload --
    about 1 ms here, which the additive noise floor was sized for, and well
    over a hundred on that runner, where it swamped the half-cap window. The
    zero-payload call (`make(64)`, the same warm call as before) measures
    that cost on the host the row runs on; a truly flat walk still reads
    about one after the subtraction, and the quadratic stand-in the twin
    below drives still reads about four."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    problems: list[str] = []
    for name, consumer, cap in _WALKER_CONSUMERS:
        n_big, n_small = _walker_sizes(cap)
        big, small = make(n_big), make(n_small)
        if len(big) >= cap:  # a problem, not an assert: every consumer is still measured
            problems.append(
                f"{name}: {len(big)} bytes is not under the {cap}-byte cap the "
                "consumer is declared under -- above it the walk is flat"
            )
            continue
        _clear_walker_caches()
        consumer(make(64), tmp_path)  # warm: the first call pays compilation
        t_zero = _min_walker_ms(consumer, make(64), tmp_path)  # the per-call cost on THIS host

        def window() -> tuple[float, float] | None:
            t_s = _min_walker_ms(consumer, small, tmp_path)
            t_b = _min_walker_ms(consumer, big, tmp_path)
            if t_s is None or t_b is None:
                return None
            return t_s, t_b

        first = window()
        if t_zero is None or first is None:
            problems.append(f"{name}: exceeded {_WALKER_CEILING_MS}ms")
            continue
        t_small, t_big = first
        net_small, net_big = t_small - t_zero, t_big - t_zero
        if net_small < _WALKER_MIN_SAMPLE_MS:
            problems.append(
                f"{name}: {t_small:.1f}ms at {len(small)} bytes ({net_small:.1f}ms net of "
                f"the {t_zero:.1f}ms per-call cost) is under the {_WALKER_MIN_SAMPLE_MS}ms "
                "sample floor, so its ratio cannot be judged: this box is much faster "
                "than the one the floors were measured on (re-measure, lower both floors "
                "together), the consumer got cheaper (re-measure), or its declared cap is "
                "too small for its walk (re-declare it); never widen the bound"
            )
            continue
        bound = _WALKER_LINEAR_RATIO * net_small + _WALKER_NOISE_FLOOR_MS
        windows = ""
        if net_big > bound or net_big < _WALKER_FLAT_RATIO * net_small:
            # a second, later window, judged as its OWN pair. For the
            # super-linear question the window with the LOWER ratio is the
            # estimate (noise inflates the big sample); for the flat question
            # the HIGHER (noise inflates the small one). Mixing the fastest
            # small with the fastest big across windows cannot read below the
            # better window's own ratio -- the discipline above.
            second = window()
            if second is None:
                problems.append(f"{name}: exceeded {_WALKER_CEILING_MS}ms on the second window")
                continue
            t_small_2, t_big_2 = second
            net_small_2, net_big_2 = t_small_2 - t_zero, t_big_2 - t_zero
            r1 = net_big / net_small
            r2 = net_big_2 / net_small_2 if net_small_2 >= _WALKER_MIN_SAMPLE_MS else None
            if r2 is None:
                problems.append(
                    f"{name}: {t_small_2:.1f}ms at {len(small)} bytes on the second window "
                    f"({net_small_2:.1f}ms net) is under the {_WALKER_MIN_SAMPLE_MS}ms sample "
                    f"floor, so its ratio cannot be judged (the first window read "
                    f"{t_small:.1f} -> {t_big:.1f}ms); re-measure, never widen the bound"
                )
                continue
            chosen_lower = net_big > bound and r2 < r1
            chosen_higher = net_big < _WALKER_FLAT_RATIO * net_small and r2 > r1
            if chosen_lower or chosen_higher:
                t_small, t_big, net_small, net_big = t_small_2, t_big_2, net_small_2, net_big_2
                bound = _WALKER_LINEAR_RATIO * net_small + _WALKER_NOISE_FLOOR_MS
                windows = (
                    f"; the first window read {first[0]:.1f} -> {first[1]:.1f}ms (ratio {r1:.2f} net) "
                    f"and the second was chosen for its {'lower' if chosen_lower else 'higher'} ratio"
                )
        ratio = net_big / net_small
        if net_big > bound:
            problems.append(
                f"{name}: {t_small:.1f}ms at {len(small)} bytes -> {t_big:.1f}ms "
                f"at {len(big)} bytes ({net_small:.1f} -> {net_big:.1f}ms net of the "
                f"{t_zero:.1f}ms per-call cost; ratio {ratio:.2f}, bound {bound:.1f}ms): "
                f"super-linear on two windows{windows}"
            )
        elif net_big < _WALKER_FLAT_RATIO * net_small:
            problems.append(
                f"{name}: {t_small:.1f}ms at {len(small)} bytes -> {t_big:.1f}ms "
                f"at {len(big)} bytes ({net_small:.1f} -> {net_big:.1f}ms net of the "
                f"{t_zero:.1f}ms per-call cost; ratio {ratio:.2f}, under {_WALKER_FLAT_RATIO}): "
                "flat on two windows, so the walk is bounded by a smaller cap than the one "
                f"declared beside the consumer and this row measured nothing; re-declare it{windows}"
            )
    assert not problems, f"{label}: " + "; ".join(problems)


def test_walker_sizes_follow_the_ceiling_rows_rule():
    """The masker's large payload in the scaling row is the ceiling row's
    own flood, so the two rows read one size rule and one cap; a consumer
    under the extraction cap is sized under it with the same margin."""
    assert _walker_sizes(_ROLE_MAP_CAP) == (_WALKER_FLOOD_LEN, _WALKER_FLOOD_LEN // 2)
    big, small = _walker_sizes(_BASH_COMMAND_CAP)
    assert small < big < _BASH_COMMAND_CAP and _BASH_COMMAND_CAP - big == _ROLE_MAP_CAP - _WALKER_FLOOD_LEN
    assert _WALKER_MIN_SAMPLE_MS > _WALKER_NOISE_FLOOR_MS  # the detection inequality
    # the two ratio bounds bracket a linear consumer (2) and exclude a quadratic one (4)
    assert 1.0 < _WALKER_FLAT_RATIO < 2.0 < _WALKER_LINEAR_RATIO < 4.0


def test_walker_scaling_row_clears_the_memoised_readers():
    """The scaling row's clear empties every memoised reader the consumers run
    through, driven by the cache's own counters rather than by timing (a
    best-of-three with a repeated payload read `removed_or_relocated_operands`
    back at 0.0 ms at the pack's authoring, which is the false green the clear
    exists to foreclose). The derived roster covers the five readers that
    existed at authoring, so a renamed one is caught here."""
    named = {
        "_removed_or_relocated_cached", "_wall_readings", "_relief_applies",
        "_nested_shell_programs_cached", "_resolve_bash_discovered_heads",
    }
    roster = {reader.__wrapped__.__name__ for reader in _WALKER_MEMOISED_READERS}
    assert named <= roster, sorted(named - roster)
    reader = _bash_patterns._removed_or_relocated_cached
    payload = "rm -rf tools/cc/hooks/x.py; " * 16
    _clear_walker_caches()
    _bash_patterns.iter_removed_or_relocated_operands(payload)
    assert reader.cache_info().currsize >= 1  # the reader memoised the payload
    _bash_patterns.iter_removed_or_relocated_operands(payload)
    assert reader.cache_info().hits >= 1  # the second call read it back
    _clear_walker_caches()
    info = reader.cache_info()
    assert (info.currsize, info.hits, info.misses) == (0, 0, 0), info


def test_walker_scaling_row_samples_with_the_collector_paused():
    """`_min_walker_ms` pauses the cyclic collector around its samples and
    restores it after. The collector's full collections cost in proportion
    to the live heap and only the larger payload's allocations trigger one,
    so a long pytest process reads a linear consumer as super-linear: the
    release matrix's stage 02 read 162.7 -> 496.1 ms (ratio 3.05) on
    2026-09-23 where a fresh process reads 2.03, a 4M-object ballast
    reproduced it at 2.22 and the pause under the ballast read 2.02. Driven
    by the collector's own switch rather than by timing: the consumer sees it
    off on every sample, the caller sees it as it was before and after."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    seen: list[bool] = []

    def consumer(payload: str, root: Path) -> None:
        seen.append(gc.isenabled())

    was_on = gc.isenabled()
    assert _min_walker_ms(consumer, "x", Path(".")) is not None
    assert len(seen) == _WALKER_SAMPLES and not any(seen), seen
    assert gc.isenabled() == was_on


def test_walker_scaling_row_judges_the_two_windows_as_pairs(tmp_path, monkeypatch):
    """A window whose small samples ran at a quarter cost and whose large ones
    ran at cost (the shape a one-sided stall leaves) reads 8.0 as a pair and
    is not rescued by MIXING it with a clean second window: the fastest small
    with the fastest big across windows is 8.0 again, which is what the first
    draft computed and why a clean second window could never clear a red.
    The pair rule reads the clean window's 2.0 and passes. The mixed estimate
    is recomputed below from the same scheduled costs and shown over the
    bound it would have been judged by, so this row is red under the draft's
    rule by construction. The length assertion is the PRECONDITION (window
    one must exceed the bound for a second to be taken), not the subject: a
    red there on a loaded box is read as scheduling first."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    cap = _BASH_COMMAND_CAP
    n_big, n_small = _walker_sizes(cap)
    unit_ms = 40.0 / n_big  # the large payload costs 40 ms at cost, the small 20
    calls: list[tuple[int, float]] = []

    def stand_in(payload: str, root: Path) -> None:
        # the first _WALKER_SAMPLES SMALL calls are window one's small samples
        # at a quarter cost; every other call -- the warm and the zero-payload
        # calls at 64 bytes, window one's big samples, all of window two --
        # runs at cost, so window one reads 8.0 and window two 2.0. Keyed on
        # the small calls seen, not on call position: the row measures its
        # per-call cost on a 64-byte payload before window one (2026-09-23),
        # and a position-keyed schedule put the quarter on those calls and
        # never took a second window. A spin on the monotonic clock, not a
        # sleep: macOS coalesces short sleeps by milliseconds, which lifted a
        # 5 ms sample over the bound.
        smalls_seen = sum(1 for size, _ in calls if size == n_small)
        quarter = len(payload) == n_small and smalls_seen < _WALKER_SAMPLES
        cost = len(payload) * unit_ms * (0.25 if quarter else 1.0)
        calls.append((len(payload), cost))
        end = time.perf_counter() + cost / 1000.0
        while time.perf_counter() < end:
            pass

    monkeypatch.setattr(sys.modules[__name__], "_WALKER_CONSUMERS", [("stand_in", stand_in, cap)])
    test_bash_walker_scales_linearly_on_opener_flood("pairs", lambda n: "x" * n, tmp_path)
    smalls = [c for size, c in calls[1:] if size == n_small]
    bigs = [c for size, c in calls[1:] if size == n_big]
    assert len(smalls) == len(bigs) == 2 * _WALKER_SAMPLES, calls  # two windows were taken
    # the draft's estimate, on these same scheduled costs, is over the bound it
    # would have judged them by
    assert min(bigs) > _WALKER_LINEAR_RATIO * min(smalls) + _WALKER_NOISE_FLOOR_MS, (smalls, bigs)


def test_walker_scaling_row_still_reds_a_quadratic_consumer_under_the_pair_rule(tmp_path, monkeypatch):
    """The must-trip control for the pair rule, which is more permissive than
    the mixed estimate it replaced (one clean window can now acquit a reading
    two windows confirmed): a stand-in whose cost is quadratic in the payload
    reads about 4 on BOTH windows, and the row reds naming it."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    cap = _BASH_COMMAND_CAP
    n_big, _n_small = _walker_sizes(cap)

    def quadratic(payload: str, root: Path) -> None:
        cost = 40.0 * (len(payload) / n_big) ** 2  # 40 ms at the large size, 10 at half
        end = time.perf_counter() + cost / 1000.0
        while time.perf_counter() < end:
            pass

    monkeypatch.setattr(sys.modules[__name__], "_WALKER_CONSUMERS", [("quadratic", quadratic, cap)])
    with pytest.raises(AssertionError, match="super-linear on two windows"):
        test_bash_walker_scales_linearly_on_opener_flood("quadratic", lambda n: "x" * n, tmp_path)


@pytest.mark.parametrize("pattern,payload", [
    (_PS_PYTHON_DASH_C_RE, 'python -c "open(\'x\',\'w\')"'),
    (_PS_PYTHON_DASH_C_RE, "py -3.12 -c 'open(\"x\",\"w\")'"),
    (_PS_PYTHON_DASH_C_RE, '& "C:\\Program Files\\Python312\\python.exe" -c "open(\'x\',\'w\')"'),
    (_PS_NODE_DASH_E_RE, "node -e 'require(\"fs\").writeFileSync(\"x\",\"y\")'"),
    (_PS_RUBY_DASH_E_RE, "ruby -e 'File.write(\"x\",\"y\")'"),
    (_PS_PERL_DASH_E_RE, "perl -e 'open(F, \">x\")'"),
    (_PS_INTERP_STDIN_RE, "@'\nx\n'@ | python -"),
    (_PS_INTERP_STDIN_RE, "'x' | pwsh -NoProfile -ExecutionPolicy Bypass -Command -"),
    (_PS_HERE_STRING_RE, "$x = @'\nline one\nline two\n'@"),
])
def test_ps_interpreter_regex_still_matches(pattern, payload):
    assert pattern.search(payload) is not None, payload


@pytest.mark.parametrize(
    "name,pattern,verb", _VERB_EXTRACTION_REGEXES + _PS_VERB_EXTRACTION_REGEXES,
)
def test_verb_extraction_regex_linear_on_repeated_verb(name, pattern, verb):
    """Each verb-anchored extraction regex stays linear on a 30KB repeated-verb
    payload (the quadratic shape the third C2 adversarial round found).

    Isolated-regex pin (the chain re-confirmation is below); pre-fix these hit
    hundreds of ms to seconds. POSIX-only (signal.alarm)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    payload = (verb + " ") * (_WORST_CASE_BODY_LEN // (len(verb) + 1))
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        pattern.findall(payload)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(
            f"{name} regex exceeded {_CI_SAFE_BUDGET_MS}ms on a 30KB repeated-verb "
            f"payload (quadratic — verb-regex ReDoS class regressed)"
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, f"{name} took {elapsed_ms:.1f}ms"


@pytest.mark.parametrize("label,seed", [
    # a value holding `-`: two parses per token before the DEF-717 lookahead
    ("dash-value", "-a b-c "),
    # a value holding `/` AND `-`: more split points -- an ordinary Windows
    # argument (`c:/my-dir/run.ps1`), which is why this is not academic
    ("slash-dash-value", "-ArgumentList c:/x-y "),
])
def test_ps_switch_value_run_linear_on_dash_bearing_values(label, seed):
    """DEF-717's switch run lets a value's tail `[^\\s]*` admit `-` and `/`, the
    same characters that lead the next iteration. Without the trailing
    `(?=[ \\t]|$)` every such token has two parses inside one `*` loop and the
    run is exponential on failure: the first cut hung the deployed hook for
    20 s on a 305-byte command while a dash-free timing pin stayed green (code
    review, driven). ONE opener, a long run that never reaches a payload,
    isolated and through the real extractor. POSIX-only (signal.alarm)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    payload = "Start-Process powershell " + seed * (_WORST_CASE_BODY_LEN // len(seed))
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CHAIN_CEILING_MS / 1000.0)
    t = time.time()
    try:
        _PS_PATH_FLAG_RE.findall(payload)
        _candidate_paths_from_powershell(payload)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(
            f"the PowerShell switch/value run exceeded {_CHAIN_CEILING_MS}ms on a "
            f"30KB {label} run (exponential -- the DEF-717 lookahead regressed)"
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CHAIN_CEILING_MS, f"{label} took {elapsed_ms:.1f}ms"


@pytest.mark.parametrize("name,_pattern,verb", _VERB_EXTRACTION_REGEXES)
def test_verb_extraction_regex_linear_through_chain(name, _pattern, verb):
    """End-to-end: a ~28KB repeated-verb command stays inside the chain ceiling through the real
    bp._candidate_paths_from_bash entrypoint (the authoritative reachability)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    from _bash_patterns import _candidate_paths_from_bash  # noqa: E402

    command = (verb + " ") * (28000 // (len(verb) + 1))
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CHAIN_CEILING_MS / 1000.0)
    t = time.time()
    try:
        _candidate_paths_from_bash(command)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(
            f"_candidate_paths_from_bash exceeded {_CHAIN_CEILING_MS}ms on a repeated {verb!r} "
            f"command — verb-regex ReDoS class ({name}) regressed (TP-169 §13 #5)"
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CHAIN_CEILING_MS


@pytest.mark.parametrize("name,_pattern,verb", _PS_VERB_EXTRACTION_REGEXES)
def test_ps_verb_extraction_regex_linear_through_chain(name, _pattern, verb):
    """End-to-end for the PowerShell rows: a ~28KB repeated-verb command stays
    inside the chain ceiling through `_candidate_paths_from_powershell` -- the entrypoint that
    actually runs these regexes (masking, cap, per-match segment slice)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    from _bash_patterns import _candidate_paths_from_powershell  # noqa: E402

    command = (verb + " ") * (28000 // (len(verb) + 1))
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CHAIN_CEILING_MS / 1000.0)
    t = time.time()
    try:
        _candidate_paths_from_powershell(command)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(
            f"_candidate_paths_from_powershell exceeded {_CHAIN_CEILING_MS}ms on a repeated {verb!r} "
            f"command -- verb-regex ReDoS class ({name}) regressed"
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CHAIN_CEILING_MS


@pytest.mark.parametrize(
    "name,pattern,command,expected",
    [
        ("sed_inplace", _SED_INPLACE_RE,
         "sed -i 's/a/b/' tools/cc/hooks/write_guard.py",
         "tools/cc/hooks/write_guard.py"),
        # The bound must not regress the realistic `sudo dd of=...` prefix.
        ("dd_of", _DD_OF_RE,
         "sudo dd if=/dev/zero of=.claude/settings.json", ".claude/settings.json"),
        ("tar_c", _TAR_C_RE, "tar xf a.tar -C .claude/", ".claude/"),
        ("git_dashdash", _GIT_CHECKOUT_DASHDASH_RE,
         "git checkout origin/main feat -- .claude/settings.json",
         ".claude/settings.json"),
        ("ps_path_flag", _PS_PATH_FLAG_RE,
         "Set-Content -Path .claude/settings.json -Value x",
         ".claude/settings.json"),
    ],
)
def test_verb_extraction_regex_still_matches(name, pattern, command, expected):
    """The span bound must not regress legitimate target extraction (group 1)."""
    m = pattern.search(command)
    assert m is not None, f"{name} no longer matches: {command!r}"
    assert m.group(1) == expected, (
        f"{name} extracted {m.group(1)!r}, expected {expected!r}"
    )


#: Every consumer that runs the binding pre-pass on a Bash command: the
#: extractor, and since DEF-846 the walls (the dangerous-reason leg) and the
#: nudge's deferral to them. The walls ran it on the UNCAPPED text, four times
#: per tier, until both reviews measured a flood of bindings past the hook
#: timeout; `_wall_readings` now caps its input and is cached per text.
_PREPASS_CONSUMERS = [
    ("candidate_paths_from_bash", lambda cmd, root: _candidate_paths_from_bash(cmd)),
    ("bash_dangerous_reason", lambda cmd, root: write_guard._bash_dangerous_reason(cmd, root)),
    ("speedbump_rmrf", lambda cmd, root: _speedbump._pred_rmrf("Bash", {"command": cmd}, root)),
]


@pytest.mark.parametrize("name, consumer", _PREPASS_CONSUMERS, ids=[c[0] for c in _PREPASS_CONSUMERS])
def test_var_expansion_prepass_bounded_by_cap(name, consumer, tmp_path):
    """`_expand_simple_var_assignments` is O(distinct_names * len) — a documented
    known-minor (pre-TP-169). It is NOT a fail-open because `_cap_for_scan` trims
    the input to 32KB before it runs, holding the worst case to a few hundred ms
    (measured ~130ms in the extractor, well under the 5s hook timeout). This pin
    guards that bound for EVERY consumer (DEF-846's review: the walls read it
    uncapped, 16 times the cost at HEAD with bindings): if a future change
    removes the cap or balloons the constant, a many-distinct-VAR command would
    regress toward a multi-second stall. Asserts the walker ceiling (about
    500 ms here at HEAD; see the class note above the chain row), far under
    the 5s timeout. POSIX-only (signal.alarm)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")

    # ~64KB raw (cap engages) of distinct `Vn=x` assignments + `${Vn}` refs —
    # the O(distinct_names * len) worst case -- then a delete of a bound name,
    # so the walls judge the inlined reading rather than stepping aside.
    assigns, refs, i, size = [], [], 0, 0
    while size < 64000:
        nm = f"V{i}"
        assigns.append(f"{nm}=x")
        refs.append("${%s}" % nm)
        size += len(nm) + 8
        i += 1
    command = ";".join(assigns) + ";" + " ".join(refs) + "; rm -r $V0"

    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _WALKER_CEILING_MS / 1000.0)
    t = time.time()
    try:
        consumer(command, tmp_path)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(
            f"{name} exceeded {_WALKER_CEILING_MS}ms on a many-distinct-VAR command — the "
            "_cap_for_scan bound on _expand_simple_var_assignments regressed "
            "(TP-169 §13 #5 known-minor; DEF-846 for the walls)"
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _WALKER_CEILING_MS, (name, elapsed_ms)


def _binding_start_flood_probes() -> list[tuple[str, str]]:
    """The binding pre-pass's anchor runs (DEF-847), each against a failing
    tail. DERIVED where the fragment names words: the declaration builtins
    are read out of `_DECL_BUILTIN_PREFIX`, so a builtin added later is
    flooded without anyone enrolling it. The separators and the exec openers
    are HAND-LISTED (a character class cannot be read back into spellings
    honestly), so the separator group is PINNED below: a separator added to
    `_BINDING_START` reds this list until it is enrolled here (the
    failure-mode review; STANDING_PRINCIPLES §14, the expectation derived).
    The blank-run rows are the shape the horizontal-only class after a
    separator exists for: a whitespace class there re-scanned a run of
    blank lines once per newline."""
    import re as _re
    import _bash_patterns

    start = _bash_patterns._BINDING_START
    assert start.startswith(r"(?:(?:^|;|\&\&|\|\||\n|(?<!\$)[{(])"), (
        "_BINDING_START's separator group changed: enrol the new anchor's "
        "flood below, then update this pin"
    )
    builtins = _re.findall(r"[a-z]{4,}", _bash_patterns._DECL_BUILTIN_PREFIX)
    assert builtins, "the declaration-builtin fragment names no builtin"
    n = _WORST_CASE_BODY_LEN
    probes: list[tuple[str, str]] = []
    for sep, spelled in (("\n", "\\n"), ("{", "{"), ("(", "("), ("||", "\\|\\|"),
                         ("&&", "\\&\\&"), (";", ";")):
        assert spelled in start, f"{sep!r} is no longer a binding start"
        probes.append((f"run-of-{sep!r}", sep * (n // len(sep)) + "zzz"))
        probes.append((f"{sep!r}-then-blanks", sep + " " * n + "zzz"))
    probes.append(("blank-lines", "\n \n" * (n // 3) + "zzz"))
    for word in builtins:
        probes.append((f"run-of-{word}", (word + " ") * (n // (len(word) + 1)) + "zzz"))
        probes.append((f"{word}-flag-run", word + " -a" * (n // 3) + " zzz"))
        probes.append((f"{word}-then-blanks", word + " " * n + "zzz"))
    for opener in ("eval ", "sh -c '", 'bash -c "', "eval '"):
        probes.append((f"run-of-{opener!r}", opener * (n // len(opener)) + "zzz"))
    # the child-scope events (DEF-848's lane): a scope opened per paren with
    # many bindings in force -- copying the bindings per scope was the
    # quadratic shape the undo journal replaces -- and a run of `-c` programs,
    # each a scope of its own, each rebinding the name
    probes.append(("bindings-then-paren-run",
                   "".join(f"a{k}=x;" for k in range(n // 16)) + "(" * (n // 2) + "$a1"))
    probes.append(("scoped-rebinding-run", "a=x; " + "sh -c 'a=y; echo $a'; " * (n // 24)))
    return probes


_BINDING_START_FLOODS = _binding_start_flood_probes()


@pytest.mark.parametrize("shape, probe", _BINDING_START_FLOODS,
                         ids=[s for s, _ in _BINDING_START_FLOODS])
def test_binding_pre_pass_linear_on_its_anchor_runs(shape, probe):
    """DEF-847 widened where a binding can start (every name case, the
    declaration builtins, a newline, `||`, a brace or paren, a `-c` or `eval`
    program). Both pre-pass patterns and the pre-pass itself stay under the
    per-pattern budget on a long run of each anchor. POSIX-only
    (signal.alarm)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    import _bash_patterns

    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        list(_bash_patterns._VAR_ANY_ASSIGN_RE.finditer(probe))
        _bash_patterns._VAR_ASSIGN_RE.search(probe)
        _bash_patterns._expand_simple_var_assignments(probe)
    except _Timeout:
        pytest.fail(f"the binding pre-pass exceeded {_CI_SAFE_BUDGET_MS}ms on {shape}")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    elapsed_ms = (time.time() - t) * 1000
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, f"{shape}: {elapsed_ms:.1f}ms"


def test_ps_var_expansion_prepass_bounded():
    """The PowerShell twin (`_expand_simple_ps_var_assignments`, DEF-801) is
    not capped first -- the PowerShell leg masks before it caps, so a span
    the cap cut in two must never be masked -- and bounds itself instead:
    it stands down past the scan cap and abandons an expansion that would
    add more than the cap. Three floods under the walker ceiling the Bash row also asserts: many
    distinct bindings and references just under the cap (the names * len
    shape), a quote flood against the binding regex's `''` escape with no
    terminator, and one short name bound to a long value and referenced
    thousands of times (the growth guard, on both twins: the Bash one built
    the megabytes and threw them away until 2026-09-15). POSIX-only
    (signal.alarm)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    from _bash_patterns import (  # noqa: E402
        _BASH_COMMAND_CAP, _candidate_paths_from_bash, _candidate_paths_from_powershell,
        _expand_simple_ps_var_assignments, _expand_simple_var_assignments,
    )
    assigns, refs, i, size = [], [], 0, 0
    while size < _BASH_COMMAND_CAP - 2048:
        nm = f"v{i}"
        assigns.append(f"${nm}='x'")
        refs.append("${%s}" % nm)
        size += 2 * len(nm) + 10
        i += 1
    floods = {
        "distinct names": ";".join(assigns) + ";" + " ".join(refs),
        "quote flood": ";$p=" + "'" * 30000,
        "growth": "$p='" + "a" * 20000 + "'; " + " ".join(["$p"] * 3000),
        # many small segments, each under the budget on its own and the sum
        # far past it: the shape the code review drove against the Bash twin
        # (32 KB -> 28 MB and 52 s under a per-segment budget, 2026-09-15)
        "growth across segments": "$a='" + "x" * 8000 + "'; " + "$a; $x=1; " * 1500,
    }
    growth_bash = {
        "growth": "P=" + "a" * 20000 + "; " + " ".join(["$P"] * 3000),
        "growth across segments": "A='" + "x" * 8000 + "'; " + "$A; X=1; " * 1500,
    }
    signal.signal(signal.SIGALRM, _alarm)
    for label, command in floods.items():
        signal.setitimer(signal.ITIMER_REAL, _WALKER_CEILING_MS / 1000.0)
        t = time.time()
        try:
            _candidate_paths_from_powershell(command)
            elapsed_ms = (time.time() - t) * 1000
        except _Timeout:
            pytest.fail(f"_candidate_paths_from_powershell exceeded {_WALKER_CEILING_MS}ms on the {label} flood")
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        assert elapsed_ms < _WALKER_CEILING_MS, (label, elapsed_ms)
    for label, command in growth_bash.items():
        signal.setitimer(signal.ITIMER_REAL, _WALKER_CEILING_MS / 1000.0)
        t = time.time()
        try:
            _candidate_paths_from_bash(command)
            elapsed_ms = (time.time() - t) * 1000
        except _Timeout:
            pytest.fail(f"_candidate_paths_from_bash exceeded {_WALKER_CEILING_MS}ms on the {label} flood")
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        assert elapsed_ms < _WALKER_CEILING_MS, (label, elapsed_ms)
    # the growth guard stood down on both twins rather than expanding -- one
    # budget across the whole command, not one per segment
    for label in ("growth", "growth across segments"):
        assert _expand_simple_ps_var_assignments(floods[label]) == floods[label], label
        assert _expand_simple_var_assignments(growth_bash[label]) == growth_bash[label], label


# ── TP-170 §4.1 / §7d: dot-star completeness gate over the hook-runtime regex
#    surface ────────────────────────────────────────────────────────────────
#
# Root cause of the #5 ReDoS whack-a-mole: every budget test above pins a
# hand-curated target list (the ``_bash_patterns`` extraction regexes). A NEW
# dot-star regex compiled in any OTHER hook file was never forced into review —
# and two shipped live and quadratic at hook runtime on model-emitted commands:
# ``write_guard.py`` ``Remove-Item\s+.*-Recurse.*-Force`` and ``plan_guard.py``
# ``_SHELL_MUTATE_RE``'s ``\bperl\b.*-\w*p\w*i\b`` arm. The ``_bash_patterns``-
# scoped budget never saw them. This gate closes the CLASS rather than the two
# instances: it statically walks every ``re.compile(...)`` in
# ``tools/cc/hooks/*.py`` — the complete hook-runtime regex surface (hooks carry
# zero ``espalier`` imports per the isolation rule, so no ``espalier`` regex ever
# executes inside a hook event) — and fails if any reconstructed pattern carries
# an UNBOUNDED dot-quantifier (``.*`` / ``.+`` / ``.*?`` / ``.+?``) that is not in
# ``_DOTSTAR_ALLOWLIST`` with a ReDoS-review reason. ``.{0,N}``-bounded spans are
# exempt — that is exactly the §7b/§7c fix shape.
#
# Scope (honest limitation): the gate catches the dot-star family — the shape
# that bit in #5 (a ``.*`` span scanning toward an ABSENT required token,
# super-linear on a repeated token). It does NOT catch nested-quantifier ReDoS
# (``(a+)+``) or non-dot unbounded quantifiers (``\w*``, ``[^x]*``) — including
# the ``[^x]*TOKEN[^x]*`` double-negated-class spelling, which is the SAME
# ReDoS class in a different costume (see ``_MARKER_SUBSTRING_RE`` below, found
# live by the TP-170 §7 verification pass). Those remain the job of the
# per-pattern SIGALRM budget tests, which must EXPLICITLY enumerate each such
# pattern — there is no automatic sweep, so a new ``[^x]*TOKEN[^x]*`` hook regex
# needs a budget pin added by hand. The two layers are complementary; neither
# substitutes for the other. An auto-fuzz gate was evaluated and REJECTED (§7d): a
# generic fuzzer false-negatives on ``Remove-Item ...-Recurse`` because it cannot
# reconstruct the dashed-token worst case. A static dot-star ban is the reliable,
# tractable source-fix.

_HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"

# (filename, EXACT reconstructed pattern) -> ReDoS-review reason. An entry is an
# attestation that a human walked the pattern and bounded its worst case. The key
# is the pattern TEXT (not a line number) so a benign edit elsewhere in the file
# never false-fails the gate — but if the regex itself changes, the key no longer
# matches and the gate re-fails, forcing re-review of the modified regex (the
# intended friction).
_DOTSTAR_ALLOWLIST: dict[tuple[str, str], str] = {
    ("_recall.py", r"^## +(.*)$"): (
        "Anchored ^...$ single-line heading parse. With no DOTALL the greedy "
        "`.*` runs to end-of-line and nothing follows it but `$`, so there is "
        "no trailing-token ambiguity to backtrack on -> linear. Runs over "
        "bounded memory-file headings, never model-emitted input."
    ),
    ("_recall.py", r"^###[ \t]+(\S.*)$"): (
        "TP-187: same shape as the `## ` heading parse above — anchored ^...$ "
        "single-line `### ` coinage-heading capture, no DOTALL, greedy `.*` runs "
        "to end-of-line with only `$` after it -> linear. Runs over bounded "
        "FAILURE_MODES.md headings, never model-emitted input."
    ),
}

# Unbounded dot-quantifier `.` (metachar) immediately followed by `*`/`+` (with
# optional lazy `?`). `.{0,N}` is exempt (the `.` is followed by `{`). We detect
# escape-aware rather than with a one-char lookbehind: a single `(?<!\\)` would
# MISS `\\.*` (a literal backslash `\\` then a genuine dot-metachar) — the gate's
# whole point is completeness, so that blind spot is unacceptable. The cleaner
# `_strip_escapes_and_classes` consumes each backslash-escaped PAIR (`\\`, `\.`,
# `\s`, …) and each `[...]` character-class span (where `.`/`*` are literals), so
# only true metacharacters survive to the final scan.
_BARE_DOTSTAR_RE = re.compile(r"\.[*+]\??")


def _strip_escapes_and_classes(pattern: str) -> str:
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "\\":  # escaped pair — drop both chars (handles \\, \., \s, …)
            i += 2
            continue
        if c == "[":  # character-class span — `.`/`*` inside are literals
            j = i + 1
            if j < n and pattern[j] == "^":
                j += 1
            if j < n and pattern[j] == "]":  # literal `]` as first class member
                j += 1
            while j < n and pattern[j] != "]":
                j += 2 if pattern[j] == "\\" else 1
            i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _pattern_has_unbounded_dotstar(pattern: str) -> bool:
    return bool(_BARE_DOTSTAR_RE.search(_strip_escapes_and_classes(pattern)))


class _UnresolvablePattern(Exception):
    """Raised when a re.compile() argument cannot be statically reconstructed."""


def _module_level_strings(tree: ast.Module) -> dict[str, ast.expr]:
    """Map module-level ``NAME = <expr>`` so the reconstructor can resolve a
    regex assembled from string constants (``_GIT_PUSH = ... ; X = _GIT_PUSH + ...``)."""
    env: dict[str, ast.expr] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            env[node.targets[0].id] = node.value
    return env


_SIBLING_ENV_CACHE: dict[str, dict[str, ast.expr]] = {}


def _sibling_module_strings(module_name: str) -> dict[str, ast.expr]:
    """Module-level assignments of a SIBLING hook module, for cross-module
    fragment references.

    Hooks share regex fragments by importing a sibling
    (``_speedbump`` composes ``_bash_patterns._CMD_POS``), which reaches the
    reconstructor as an ``ast.Attribute`` it could not resolve — so the gate
    failed CLOSED on four real, safe patterns. Resolving the sibling keeps the
    gate's guarantee (it still PROVES the absence of a dot-star) instead of
    forcing an allowlist entry, which would have waived the proof entirely.

    Fails closed for anything that is not a sibling hook file.
    """
    if module_name not in _SIBLING_ENV_CACHE:
        sibling = _HOOKS_DIR / f"{module_name}.py"
        if not sibling.is_file():
            raise _UnresolvablePattern(f"not a sibling hook module: {module_name!r}")
        _SIBLING_ENV_CACHE[module_name] = _module_level_strings(
            ast.parse(sibling.read_text(encoding="utf-8"))
        )
    return _SIBLING_ENV_CACHE[module_name]


def _reconstruct_pattern(node: ast.expr, env: dict[str, ast.expr], depth: int = 0) -> str:
    """Best-effort static value of a re.compile() pattern argument.

    Resolves: str literals, ``+`` concatenation, module-level Name references
    (recursively), and f-strings whose interpolations are ``re.escape(...)``
    (escaped output is provably dot-star-free, so it contributes the empty
    string). Anything else — a genuinely dynamic interpolation, a non-string
    constant, an unresolved Name — raises so the gate forces an explicit review
    (it cannot prove the absence of a dot-star it cannot see)."""
    if depth > 50:
        raise _UnresolvablePattern("reconstruction too deep")
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return (
            _reconstruct_pattern(node.left, env, depth + 1)
            + _reconstruct_pattern(node.right, env, depth + 1)
        )
    if isinstance(node, ast.Name):
        if node.id in env:
            return _reconstruct_pattern(env[node.id], env, depth + 1)
        raise _UnresolvablePattern(f"unresolved name {node.id!r}")
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        # `_bash_patterns._CMD_POS` — a fragment shared from a sibling hook
        # module. Resolved in the SIBLING's own env, not this file's.
        sibling_env = _sibling_module_strings(node.value.id)
        if node.attr not in sibling_env:
            raise _UnresolvablePattern(
                f"unresolved attribute {node.value.id}.{node.attr}"
            )
        return _reconstruct_pattern(sibling_env[node.attr], sibling_env, depth + 1)
    if isinstance(node, ast.JoinedStr):  # f-string
        parts: list[str] = []
        for piece in node.values:
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                parts.append(piece.value)
            elif isinstance(piece, ast.FormattedValue):
                call = piece.value
                is_re_escape = (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "escape"
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "re"
                )
                if is_re_escape:
                    parts.append("")  # re.escape(...) yields no dot-star
                else:
                    raise _UnresolvablePattern("dynamic f-string interpolation")
            else:
                raise _UnresolvablePattern("unrecognized f-string component")
        return "".join(parts)
    raise _UnresolvablePattern(f"unsupported node {type(node).__name__}")


def _re_compile_bindings(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Discover every name under which this module can reach ``re.compile``.

    A gate that only recognizes the literal ``re.compile`` spelling has clean
    bypasses (``import re as X``; ``from re import compile``; a module-level
    rebind ``_c = re.compile``) — a future hook could ship an unbounded dot-star
    through any of them and the gate would pass GREEN. We resolve the binding
    instead of pinning the name. Returns ``(re_module_names, compile_call_names)``:
    names ``X`` where ``X.compile`` is ``re.compile``, and bare names ``Y`` where
    ``Y(...)`` is ``re.compile(...)``."""
    re_module_names: set[str] = set()
    compile_call_names: set[str] = set()
    for node in ast.walk(tree):  # walk (not just body) — catches scoped imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "re":
                    re_module_names.add(alias.asname or "re")
        elif isinstance(node, ast.ImportFrom) and node.module == "re":
            for alias in node.names:
                if alias.name == "compile":
                    compile_call_names.add(alias.asname or "compile")
    for node in tree.body:  # module-level rebind: Z = re.compile / Z = X.compile
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "compile"
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id in re_module_names
        ):
            compile_call_names.add(node.targets[0].id)
    return re_module_names, compile_call_names


def _compile_pattern_arg(node: ast.Call) -> ast.expr:
    """The pattern argument of a compile call — positional or ``pattern=`` kwarg.
    Raises ``_UnresolvablePattern`` if neither is present (e.g. a ``*args`` splat)
    so the gate fails CLOSED rather than silently skipping the call."""
    if node.args:
        return node.args[0]
    for kw in node.keywords:
        if kw.arg == "pattern":
            return kw.value
    raise _UnresolvablePattern("no positional or pattern= argument")


def _iter_hook_compiled_patterns(path: Path):
    """Yield ``(lineno, pattern_or_None)`` for each regex-compile call in a hook
    file, recognizing ``re.compile`` under any binding (alias / from-import /
    rebind) and the ``pattern=`` kwarg form. ``pattern`` is ``None`` when the
    argument is not statically reconstructable (gate then fails closed)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    env = _module_level_strings(tree)
    re_module_names, compile_call_names = _re_compile_bindings(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_compile = (
            isinstance(func, ast.Attribute)
            and func.attr == "compile"
            and isinstance(func.value, ast.Name)
            and func.value.id in re_module_names
        ) or (isinstance(func, ast.Name) and func.id in compile_call_names)
        if not is_compile:
            continue
        try:
            yield node.lineno, _reconstruct_pattern(_compile_pattern_arg(node), env)
        except _UnresolvablePattern:
            yield node.lineno, None


def test_no_unreviewed_dotstar_in_hook_regexes():
    """Every ``re.compile`` in ``tools/cc/hooks/*.py`` either carries no unbounded
    dot-quantifier or is in ``_DOTSTAR_ALLOWLIST`` with a ReDoS-review reason.

    Earn-the-red: against pre-§7b/§7c HEAD this fails listing
    ``write_guard.py::DANGEROUS_BASH_PATTERNS`` and ``plan_guard.py::_ROOT_SOURCE_HINT`` (un-allowlisted dot-star);
    after the spans are bounded only the allowlisted ``_recall.py`` survivor
    remains and the gate passes."""
    offenders: list[str] = []
    unresolved: list[str] = []
    hook_files = sorted(_HOOKS_DIR.glob("*.py"))
    assert hook_files, f"no hook files found under {_HOOKS_DIR}"
    for path in hook_files:
        for lineno, pattern in _iter_hook_compiled_patterns(path):
            if pattern is None:
                unresolved.append(f"{path.name}:{lineno}")
                continue
            if _pattern_has_unbounded_dotstar(pattern):
                if (path.name, pattern) not in _DOTSTAR_ALLOWLIST:
                    offenders.append(f"{path.name}:{lineno}  {pattern!r}")
    assert not unresolved, (
        "re.compile() with a statically un-reconstructable pattern in a hook "
        "file — the dot-star gate cannot prove it is ReDoS-safe. Make the "
        "pattern a module-level string literal (the gate resolves Name refs, "
        "`+` concatenation, and re.escape() f-strings) or extend the "
        "reconstructor:\n  " + "\n  ".join(unresolved)
    )
    assert not offenders, (
        "Unbounded dot-quantifier (.* / .+ / .*? / .+?) in a hook-runtime regex "
        "not in _DOTSTAR_ALLOWLIST — this is the #5 ReDoS class. Bound the span "
        "(.{0,N}) or, if provably linear, add (filename, pattern) to "
        "_DOTSTAR_ALLOWLIST with a ReDoS-review reason:\n  " + "\n  ".join(offenders)
    )


def test_dotstar_detector_self_check():
    """The detector flags unbounded dot-quantifiers and exempts the §7b/§7c fix
    shape — guards the gate against a detector that quietly stops detecting."""
    for pat in (
        r"a.*b",
        r"x.+y",
        r".*?",
        r".+?",
        r"^## +(.*)$",
        r"\\.*",  # literal backslash `\\` then a REAL dot-metachar (the
        # one-char-lookbehind blind spot that motivated the escape-aware scan)
    ):
        assert _pattern_has_unbounded_dotstar(pat), f"missed dot-star in {pat!r}"
    for pat in (
        r"a.{0,200}b",  # bounded span (the fix)
        r"\.*literal",  # escaped dot then literal * (no metachar dot)
        r"[.*]+",  # dot+star are literals inside a character class
        r"\w*p\w*i",  # non-dot unbounded quantifiers (out of scope)
        r"[^\n;|&]*?",  # negated-class lazy (out of scope)
        r"\\\.* ",  # escaped backslash THEN escaped dot -> literal, no metachar
    ):
        assert not _pattern_has_unbounded_dotstar(pat), f"false dot-star in {pat!r}"


@pytest.mark.parametrize(
    "name,src",
    [
        ("alias", "import re as _ra\nP = _ra.compile(r'v.*danger')\n"),
        ("from_import", "from re import compile\nP = compile(r'v.*danger')\n"),
        ("from_import_as", "from re import compile as _c\nP = _c(r'v.*danger')\n"),
        ("rebind", "import re\n_c = re.compile\nP = _c(r'v.*danger')\n"),
        ("kwarg", "import re\nP = re.compile(pattern=r'v.*danger')\n"),
    ],
)
def test_gate_sees_aliased_compile_spellings(tmp_path, name, src):
    """The completeness gate must recognize ``re.compile`` under aliasing, a
    from-import, a module-level rebind, and the ``pattern=`` kwarg — each is a
    CLEAN bypass of a literal ``re.compile`` matcher (TP-170 §7 verification,
    gate-evasion). Earn-the-red: against the pre-hardening matcher these snippets
    yield NOTHING and the dot-star ships unreviewed; the resolved matcher flags
    the ``v.*danger`` each hides."""
    f = tmp_path / f"_probe_{name}.py"
    f.write_text(src, encoding="utf-8")
    patterns = [p for _, p in _iter_hook_compiled_patterns(f)]
    assert any(p and _pattern_has_unbounded_dotstar(p) for p in patterns), (
        f"gate blind to dot-star via {name!r} compile spelling; saw {patterns!r}"
    )


def test_gate_fails_closed_on_unresolvable_compile_arg(tmp_path):
    """A compile call with no statically-resolvable pattern (``*args`` splat) must
    fail CLOSED — yield ``None`` so the gate's ``unresolved`` assert fires —
    rather than be silently skipped."""
    f = tmp_path / "_probe_splat.py"
    f.write_text("import re\nargs = (r'x',)\nP = re.compile(*args)\n", encoding="utf-8")
    patterns = [p for _, p in _iter_hook_compiled_patterns(f)]
    assert None in patterns, f"splat compile must fail closed (None); saw {patterns!r}"


# ── TP-170 §7d: crafted worst-case pins on the two §7b/§7c-fixed arms ─────────
#
# The completeness gate above is the deterministic earn-the-red for the class.
# These timing pins are the worst-case complement on the SPECIFIC fixed arms,
# driven against the LIVE compiled objects (identity-faithful: exactly what
# check_powershell / bash_has_write_intent run at hook runtime). Measured this
# session: the perl arm was strongly quadratic (1.49s @ 16KB isolated) and earns
# the red here too; Remove-Item was only mildly quadratic (~62ms @ the 32KB cap)
# and the sed arm was already LINEAR (§7c bounds it only for consistency) — for
# those two the GATE, not this timing pin, is what catches a dot-star
# re-introduction. All three are pinned forward regardless.

import plan_guard  # noqa: E402
from write_guard import DANGEROUS_PS_PATTERNS  # noqa: E402

_PS_REMOVE_ITEM_MIXED = next(
    e.pattern
    for e in DANGEROUS_PS_PATTERNS
    if e.pid == "ps-remove-item-recurse-force-mixed"
)


def _assert_search_under_budget(label, fn, payload, budget_s):
    """Run ``fn(payload)`` under a SIGALRM budget; fail on timeout or overrun."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, budget_s)
    t = time.time()
    try:
        fn(payload)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(
            f"{label} exceeded {budget_s * 1000:.0f}ms on a {len(payload)}-byte "
            f"payload (catastrophic backtracking — dot-star ReDoS)"
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < budget_s * 1000, f"{label} took {elapsed_ms:.1f}ms"


def test_plan_guard_perl_arm_linear_isolated():
    """``_SHELL_MUTATE_RE``'s perl arm stays linear on a 20KB ``-pppp…`` run.

    Pre-§7c (``\\bperl\\b.*-\\w*p\\w*i\\b``) this measured ~2.3s on this payload
    (>1s SIGALRM budget = earn-the-red); the ``.{0,200}`` / ``\\w{0,40}`` bound
    drops it to <1ms."""
    payload = "perl -" + "p" * 20000
    _assert_search_under_budget(
        "_SHELL_MUTATE_RE perl arm", plan_guard._SHELL_MUTATE_RE.search, payload,
        _CI_SAFE_BUDGET_MS / 1000.0,
    )


def test_plan_guard_perl_arm_linear_through_chain():
    """Same payload through the real ``bash_has_write_intent`` entrypoint — the
    authoritative hook-runtime reachability (PreToolUse plan-gate)."""
    payload = "perl -" + "p" * 20000
    _assert_search_under_budget(
        "bash_has_write_intent(perl ReDoS)",
        plan_guard.bash_has_write_intent,
        payload,
        _CI_SAFE_BUDGET_MS / 1000.0,
    )


def test_ps_remove_item_mixed_linear_forward_pin():
    """Forward worst-case pin on the live ``Remove-Item`` mixed PS record.

    The GATE is this arm's earn-the-red (it was only ~62ms-quadratic at the 32KB
    cap, under a timing budget). Post-§7b ``.{0,200}`` bounding holds it to
    <1ms; this pin catches a future unbounded re-introduction or a worse-than-
    quadratic regression."""
    payload = "Remove-Item " + "-Recurse" * 3700  # ~30KB, the realistic cap
    _assert_search_under_budget(
        "Remove-Item mixed", _PS_REMOVE_ITEM_MIXED.search, payload, _CI_SAFE_BUDGET_MS / 1000.0
    )


@pytest.mark.parametrize("label, payload", [
    # DEF-822: the switch fragments admit abbreviations and /bin/rm clusters.
    # Each flood aims a fragment's quantifier at its worst case: a run of
    # abbreviated switches scanning toward an absent force, one 30 KB cluster
    # that fails on its last letter (the lookahead form must stay one linear
    # scan), a flood of near-miss clusters, and the colon-bound spelling.
    ("abbreviated-recurse-flood", "Remove-Item " + "-r " * 9000),
    ("one-giant-cluster", "rm -" + "r" * 30000 + "i"),
    ("giant-cluster-force-then-i", "rm -" + "rf" * 15000 + "i"),
    ("near-miss-clusters", "rm " + "-rfi " * 6000),
    ("colon-bound-recurse-flood", "ri " + "-Recurse:$x " * 2500),
    # the code review's shape: MANY command positions, each with a maximal
    # lazy span scanning toward an absent force -- 22x the literal records'
    # constant factor and linear; the pins above are one command position
    # each and certify a 20x cheaper shape (73 ms at 30 KB, measured)
    ("statement-flood-of-abbreviated-removes", ("ri " + "-r " * 70 + ";") * 140),
])
def test_ps_recursive_force_spellings_linear_forward_pin(label, payload):
    """Forward pins on the three consumers of the shared switch fragments:
    the two hard records and the soft tier's regex, then the hard tier's
    entry point that runs the records (`_ps_dangerous_reason`)."""
    from _bash_patterns import _PS_RECURSIVE_FORCE_RE  # noqa: E402
    for name, fn in (
        ("mixed record", _PS_REMOVE_ITEM_MIXED.search),
        ("prefix record", next(e.pattern for e in DANGEROUS_PS_PATTERNS
                               if e.pid == "ps-remove-item-recurse-force-prefix").search),
        ("soft-tier regex", _PS_RECURSIVE_FORCE_RE.search),
        ("_ps_dangerous_reason", lambda p: write_guard._ps_dangerous_reason(p, None)),
    ):
        _assert_search_under_budget(
            f"{name} on {label}", fn, payload, _CHAIN_CEILING_MS / 1000.0)


@pytest.mark.parametrize("label, payload", [
    # DEF-824: the PowerShell sweep classifier walks the directory chain and
    # places every find in its statement; each flood aims at one cost -- the
    # predicate span, the per-statement placement (a cursor, not a rescan),
    # the wrapper run, the root list.
    ("find-predicate-flood", "find . " + "-name x " * 4000 + "-delete"),
    ("find-statement-flood", "find . -delete; " * 1800),
    ("find-wrapper-flood", "sudo env nice find . -delete; " * 900),
    ("find-root-flood", "find " + "a " * 14000 + "-delete"),
    # DEF-822: the pipeline reader -- a flood of pipelines, of enumerator
    # switches scanning toward the pipe, of pipes scanning toward an absent
    # remove verb, and of comma-joined roots
    ("pipeline-flood", "gci -r | ri -r -fo; " * 1500),
    ("enumerator-switch-flood", "gci " + "-r " * 8000 + "| ri -r -fo"),
    ("pipe-flood", "gci " + "| " * 14000 + "x"),
    ("root-list-flood", "gci " + "a," * 12000 + " -r | ri -r -fo"),
    # the review batch: a pipe followed by a line break, a flood of .NET
    # directory deletes, a flood of catch-all filters
    ("pipe-newline-flood", "gci |\n" * 6000),
    ("dotnet-delete-flood", '[IO.Directory]::Delete("x", $true); ' * 800),
    ("catchall-filter-flood", "gci " + "-Include * " * 2500 + "| ri -r -fo"),
])
def test_ps_sweep_classifier_linear_forward_pin(label, payload):
    from _bash_patterns import has_catastrophic_ps_sweep  # noqa: E402
    for name, fn in (
        ("has_catastrophic_ps_sweep", lambda p: has_catastrophic_ps_sweep(p, "/tmp/x")),
        ("_ps_dangerous_reason", lambda p: write_guard._ps_dangerous_reason(p, None)),
    ):
        _assert_search_under_budget(
            f"{name} on {label}", fn, payload, _CI_SAFE_BUDGET_MS / 1000.0)


def test_plan_guard_sed_arm_linear_forward_pin():
    """Forward linearity pin on ``_SHELL_MUTATE_RE``'s sed arm. The sed arm was
    already linear pre-§7c (measured 0.38ms @ 30KB); the ``.{0,200}`` bound is
    for consistency. Pins it so a future change can't quietly make it quadratic."""
    payload = "sed " + "a" * 30000
    _assert_search_under_budget(
        "_SHELL_MUTATE_RE sed arm",
        plan_guard._SHELL_MUTATE_RE.search,
        payload,
        _CI_SAFE_BUDGET_MS / 1000.0,
    )


@pytest.mark.parametrize(
    "command,should_match",
    [
        # §7b: Remove-Item mixed must still catch the spaced-flag form.
        ("Remove-Item -Path C:\\x -Recurse -Force", True),
        ("Remove-Item -Recurse -Force", True),  # also caught by the prefix record
        ("Get-ChildItem -Recurse", False),  # no Remove-Item / -Force
    ],
)
def test_remove_item_mixed_detection_preserved(command, should_match):
    """The §7b span bound must not regress Remove-Item detection."""
    assert bool(_PS_REMOVE_ITEM_MIXED.search(command)) is should_match, (
        f"Remove-Item mixed detection changed for {command!r}"
    )


@pytest.mark.parametrize(
    "command,should_match",
    [
        ("sed -i 's/a/b/' f.txt", True),
        ("sed -e 's/a/b/' -i f.txt", True),
        ("perl -pi -e 's/a/b/' f.txt", True),
        ("perl -pi f.txt", True),
        ("tee out.txt", True),
        ("rm f.txt", True),
        ("echo hi", False),
    ],
)
def test_shell_mutate_detection_preserved(command, should_match):
    """The §7c span bound must not regress ``_SHELL_MUTATE_RE`` detection — all
    of §7c's enumerated mutating forms still match; ``echo hi`` still does not."""
    assert bool(plan_guard._SHELL_MUTATE_RE.search(command)) is should_match, (
        f"_SHELL_MUTATE_RE detection changed for {command!r}"
    )


# ── TP-170 §7-followup: budget pin for the [^x]*TOKEN[^x]* ReDoS the dot-star
#    gate is out-of-scope for (found live by the §7 verification pass) ─────────
#
# _reinject._MARKER_SUBSTRING_RE = ["'][^"']{0,200}MANAGED[^"']{0,200}["']\s+in\b
# was unbounded ([^"']*…[^"']*) and quadratic on a repeated-`MANAGED` quoted run
# (the SAME class as #5 in the double-negated-class spelling). It runs at
# PostToolUse over _reinject._new_content — which is UNCAPPED, unlike write_guard's
# 32KB bash cap — so a large attacker-authored write stalled past the hook timeout
# (measured ~60s @ 256KB end-to-end) = slow-hook fail-open. The dot-star gate
# CANNOT see it (negated-class, not `.`-metachar), so THIS budget pin is the
# pattern's only ReDoS net — it makes the gate docstring's "[^x]* shapes are the
# budget tests' job" claim true for this pattern specifically.

from _reinject import _MARKER_SUBSTRING_RE  # noqa: E402


def test_reinject_marker_substring_re_linear():
    """`_MARKER_SUBSTRING_RE` stays linear on the repeated-`MANAGED` quoted run
    that was quadratic pre-bound. Pre-§7-followup this measured ~1s @ 32KB
    isolated / ~60s @ 256KB through the uncapped PostToolUse path; the
    `[^"']{0,200}` bound holds it to well under the budget."""
    payload = '"' + "MANAGED" * (_WORST_CASE_BODY_LEN // 7)
    _assert_search_under_budget(
        "_MARKER_SUBSTRING_RE", _MARKER_SUBSTRING_RE.search, payload, _CI_SAFE_BUDGET_MS / 1000.0
    )


@pytest.mark.parametrize(
    "text,should_match",
    [
        ('"ESPALIER:MANAGED" in line', True),
        ("'# ESPALIER MANAGED BLOCK' in text", True),
        ('"hello world" in line', False),  # no marker token
    ],
)
def test_reinject_marker_substring_detection_preserved(text, should_match):
    """The `[^"']{0,200}` bound must not regress the forgeable-marker advisory:
    real ``"…MANAGED…" in`` substring tests still match (marker strings are far
    inside 200 chars); a non-marker membership test still does not."""
    assert bool(_MARKER_SUBSTRING_RE.search(text)) is should_match, (
        f"_MARKER_SUBSTRING_RE detection changed for {text!r}"
    )


# ---------------------------------------------------------------------------
# Derived ReDoS population — every extraction regex carries a linear-time budget
#
# Closes DEF-374a. The budget harness above is four HAND-MAINTAINED lists, so a
# regex enrols only if an author remembers. Measured at the time this landed:
# 35 module-level compiled patterns across the two extraction modules, 21 in a
# parametrized list, **14 with no budget at all** -- including four verb regexes
# in the live deny path and `_HARNESS_ENV_PREFIX_RE`, which is the grammar the
# command-position anchor is derived from.
#
# "A subset hard-coded where the actual set should be derived" is the same
# enumeration-integrity defect this repo has now fixed several times. The fix is
# to DERIVE the population from the modules so a new regex self-enrols by
# construction rather than by memory.
#
# This is not theoretical. The command-position anchor shipped a genuine O(n^2)
# regression -- a greedy `\S*` run that scanned past `;` to end-of-input and
# backtracked one character at a time -- and it was caught only because it
# happened to sit in a regex that one older test exercised. Six of the anchored
# regexes had no budget at all and would have carried the same defect unmeasured.


def _derived_extraction_regexes() -> list[tuple[str, "re.Pattern[str]"]]:
    """Every module-level compiled pattern in the two extraction modules.

    Derived, deliberately: the point is that a regex added tomorrow is covered
    without anyone editing a list. Both modules are unioned because the budget
    harness imports from ``write_guard`` while most patterns live in
    ``_bash_patterns`` -- a single-module derivation silently drops
    ``_HARNESS_ENV_PREFIX_RE``, the one pattern the anchor is derived from.
    """
    import _bash_patterns  # noqa: E402

    import write_guard as _wg  # noqa: E402

    found: dict[str, "re.Pattern[str]"] = {}
    for module in (_bash_patterns, _wg):
        for attr, value in vars(module).items():
            if isinstance(value, re.Pattern) and attr.endswith("_RE"):
                found.setdefault(attr, value)
    # Also harvest patterns held INSIDE the dangerous-pattern registries. Those
    # records may inline `re.compile(...)` rather than referencing a
    # module-level name, and an inlined pattern is invisible to the scan above
    # — which is exactly how `ps-remove-item-recurse-force-*` sat in the deny
    # path with no linear-time budget. Found while adding the PowerShell
    # harness-env twin: the new pattern was given a module-level name so it
    # would self-enrol, and that raised the question of what else would not.
    for registry in ("DANGEROUS_BASH_PATTERNS", "DANGEROUS_PS_PATTERNS"):
        for record in getattr(_wg, registry, ()) or ():
            pattern = getattr(record, "pattern", None)
            if isinstance(pattern, re.Pattern):
                found.setdefault(f"{registry}:{record.pid}", pattern)
    return sorted(found.items())


_DERIVED_REGEXES = _derived_extraction_regexes()

#: Floor for the derived population. A derivation that silently returns nothing
#: would make every test below vacuously pass, which is the failure mode this
#: whole block exists to remove -- so pin the count and pin known members.
_DERIVED_POPULATION_FLOOR = 30
_DERIVED_MUST_INCLUDE = frozenset({
    "_CP_MV_RE",              # anchored verb regex
    "_LN_S_RE",               # symlink creation into a governed zone
    "_LN_CP_INVOCATION_RE",   # DEF-374a: the regex that had no budget
    "_HARNESS_ENV_PREFIX_RE", # lives in write_guard, not _bash_patterns
})

#: Adversarial payload shapes. Each is a repeated token run chosen to stress a
#: DIFFERENT quantifier family. The env-assignment and separator runs are the
#: shapes that caught the anchor's O(n^2) regression; do not drop them.
_ADVERSARIAL_SHAPES: list[tuple[str, str]] = [
    ("space-run", " " * _WORST_CASE_BODY_LEN),
    ("word-run", "a" * _WORST_CASE_BODY_LEN),
    ("path-run", ("a/" * (_WORST_CASE_BODY_LEN // 2))[:_WORST_CASE_BODY_LEN]),
    ("env-assign-run", ("A=1 " * (_WORST_CASE_BODY_LEN // 4))[:_WORST_CASE_BODY_LEN]),
    ("assign-separator-run", ("x=1;" * (_WORST_CASE_BODY_LEN // 4))[:_WORST_CASE_BODY_LEN]),
    ("wrapper-run", ("sudo -u me " * (_WORST_CASE_BODY_LEN // 11))[:_WORST_CASE_BODY_LEN]),
    ("flag-run", ("-a " * (_WORST_CASE_BODY_LEN // 3))[:_WORST_CASE_BODY_LEN]),
    ("quote-run", "'" * _WORST_CASE_BODY_LEN),
]


def test_derived_regex_population_is_non_vacuous():
    """The derivation itself is load-bearing, so pin it both ways.

    A count floor alone is not enough: a derivation that returned the wrong
    module's patterns could still clear it. Pin membership too.
    """
    names = {name for name, _ in _DERIVED_REGEXES}
    assert len(_DERIVED_REGEXES) >= _DERIVED_POPULATION_FLOOR, (
        f"derived ReDoS population collapsed to {len(_DERIVED_REGEXES)} "
        f"(floor {_DERIVED_POPULATION_FLOOR}) — the derivation is broken, not "
        f"the modules. Every budget test below would now pass vacuously."
    )
    missing = _DERIVED_MUST_INCLUDE - names
    assert not missing, (
        f"derived population lost known members {sorted(missing)} — a "
        f"single-module derivation drops _HARNESS_ENV_PREFIX_RE, which is the "
        f"grammar _CMD_POS is derived from"
    )


@pytest.mark.parametrize("name,pattern", _DERIVED_REGEXES)
def test_every_derived_regex_is_linear_on_adversarial_runs(name, pattern):
    """Every derived extraction regex stays inside the budget on every shape.

    Self-enrolling: a regex added to either module is covered here with no edit.
    """
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    for shape_name, payload in _ADVERSARIAL_SHAPES:
        signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
        start = time.time()
        try:
            pattern.search(payload)
            elapsed_ms = (time.time() - start) * 1000
        except _Timeout:
            pytest.fail(
                f"{name} exceeded {_CI_SAFE_BUDGET_MS}ms on the {shape_name} "
                f"payload ({len(payload)} chars). A greedy run that can cross a "
                f"command separator is quadratic by construction — bound the "
                f"token class to [^\\s;|&] rather than \\S."
            )
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        assert elapsed_ms < _CI_SAFE_BUDGET_MS, (
            f"{name} took {elapsed_ms:.1f}ms on {shape_name} "
            f"(budget {_CI_SAFE_BUDGET_MS}ms)"
        )


# ── _CMD_POS prefix-run budget ────────────────────────────────────────────────
#
# The command-position fragment sits in front of THIRTEEN write_guard extraction
# regexes on the PreToolUse path, so a super-linear shape in it is a hang on
# every tool call — and a hang is NOT caught by write_guard's `except
# BaseException` crash guard, which only sees exceptions. The population above
# never exercised a repeated PREFIX run (it varies the quoted body), which is
# why this shape survived: `_CMD_POS_EXEC_QUOTE` carried `[ \t]*[\"']?[ \t]*`,
# two adjacent whitespace runs split by an optional quote, so each `eval ` could
# be partitioned two ways and `(?:…)*` explored 2^n of them on a failing match.
#
# Every prefix token that `_CMD_POS` admits is driven, not just the one that
# blew up, so a future widening of any arm is budgeted by construction.
def _prefix_run_tokens() -> list[str]:
    """DERIVED from `_CMD_POS`'s own arms, not hand-listed.

    ⚠ A hand-written list is what let this gate overclaim. Its first version
    named six tokens and its docstring said "every prefix token `_CMD_POS`
    admits is driven" — but it omitted the wrapper-WITH-FLAG-ARGUMENT spelling,
    and `env -i ` / `nice -n 10 ` / `xargs -0 ` / `strace -f ` were all still
    exponential (>5000 ms at 30 repetitions) while the gate reported green.
    Deriving the population means a wrapper added to `_CMD_POS_WRAPPER` later is
    budgeted without anyone remembering to enrol it.
    """
    import re as _re
    import _bash_patterns

    wrappers = _re.findall(r"[a-z]+", _bash_patterns._CMD_POS_WRAPPER)
    keywords = _re.findall(r"[a-z]+", _bash_patterns._CMD_POS_KEYWORD)
    tokens = ["eval ", "sh -c ", "A=1 ", "> f "]
    # the INNER length of a redirect target, not only the repetition count:
    # the DEF-794 gate hung on one thirty-character bare target while every
    # row here repeated a four-character one (both reviews, driven)
    tokens += [">" + "a" * n + " " for n in (30, 64, 512)]
    tokens += ['>"' + "a b" * 8 + '" ', "> " + "a" * 64 + " "]
    # DEF-848's lane: one assignment prefix per piece the value arm admits --
    # single, double and ANSI-C quotes holding a blank, a backslash escape, a
    # lone `$`, a separator inside a quote -- and the three quote openers left
    # unterminated, the failing shape for a quoted piece
    tokens += ["A='a b' ", 'A="a b" ', "A=$'a b' ", "A=a\\ b ", "A=$x ", "A='a;b' "]
    tokens += ["A='", 'A="', "A=$'"]
    tokens += [f"{w} " for w in wrappers]
    # The shapes that actually blew up: a flag, and a flag with an argument.
    tokens += [f"{w} -i " for w in wrappers]
    tokens += [f"{w} -n 10 " for w in wrappers]
    tokens += [f"{k} " for k in keywords]
    return tokens


_PREFIX_RUN_TOKENS = _prefix_run_tokens()


@pytest.mark.parametrize("token", _PREFIX_RUN_TOKENS)
def test_cmd_pos_linear_on_repeated_prefix_run(token):
    """`_CMD_POS` stays linear on a long run of any prefix token it accepts.

    Driven against a FAILING tail: a successful match short-circuits and hides
    the blowup, which is exactly why the defect went unmeasured.
    """
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    import _bash_patterns

    probe = token * (_WORST_CASE_BODY_LEN // max(len(token), 1)) + "cp /a /b"
    rx = re.compile(_bash_patterns._CMD_POS + r"zzz\b")

    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        rx.search(probe)
    except _Timeout:
        pytest.fail(
            f"_CMD_POS exceeded {_CI_SAFE_BUDGET_MS}ms on a repeated {token!r} "
            "prefix run — catastrophic backtracking in the command-position "
            "fragment hangs every PreToolUse call"
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    elapsed_ms = (time.time() - t) * 1000
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, (
        f"_CMD_POS took {elapsed_ms:.1f}ms on a {token!r} run "
        f"(budget {_CI_SAFE_BUDGET_MS}ms)"
    )


def test_reconstructor_resolves_a_sibling_module_fragment(tmp_path):
    """A cross-module fragment reference must RESOLVE, not fail closed.

    `_speedbump` composes `_bash_patterns._CMD_POS`. Before the reconstructor
    understood attribute access, four safe patterns came back unresolved and the
    gate failed closed on them — correct behaviour, but the remedy is to teach
    the reconstructor, not to allowlist away the proof.
    """
    f = tmp_path / "probe.py"
    f.write_text(
        "import re\nimport _bash_patterns\n"
        "_X = _bash_patterns._CMD_POS + r'git\\b'\n"
        "R = re.compile(_X)\n",
        encoding="utf-8",
    )
    patterns = [p for _, p in _iter_hook_compiled_patterns(f)]
    assert patterns and patterns[0] is not None, "sibling fragment failed to resolve"
    import _bash_patterns as _bp
    assert patterns[0] == _bp._CMD_POS + r"git\b"


def test_reconstructor_fails_closed_on_a_non_sibling_attribute(tmp_path):
    """The widening must not become a hole: an attribute on anything that is not
    a sibling hook module still yields None (gate fails closed)."""
    f = tmp_path / "probe2.py"
    f.write_text(
        "import re\nimport os\nR = re.compile(os.sep + '.*')\n", encoding="utf-8"
    )
    assert [p for _, p in _iter_hook_compiled_patterns(f)] == [None]


def test_reconstructor_fails_closed_on_unknown_sibling_name(tmp_path):
    """A sibling module that exists but lacks the referenced name fails closed."""
    f = tmp_path / "probe3.py"
    f.write_text(
        "import re\nimport _bash_patterns\n"
        "R = re.compile(_bash_patterns._NO_SUCH_FRAGMENT)\n",
        encoding="utf-8",
    )
    assert [p for _, p in _iter_hook_compiled_patterns(f)] == [None]


# ── DEF-794: the shapes the root-shape fix touched ─────────────────────────
# The redirect operator gained `>|`, the leading-redirect gate inside every
# `_CMD_POS`-anchored arm gained a quote-aware target run, and the perl open
# path class admits spaces. Each is driven on the flood its own shape invites:
# an unterminated quote after the operator, and the operator repeated. The
# extractor is driven whole on the same floods, because the raw-operand
# reader that follows each match does a BOUNDED find for a quote's close.
_ROOT_SHAPE_TARGETS = [
    ("redirect-quote-flood", _REDIRECT_RE, '>"' * (_WORST_CASE_BODY_LEN // 2)),
    ("redirect-unterminated-quote", _REDIRECT_RE, '> "' + "a" * _WORST_CASE_BODY_LEN),
    ("redirect-clobber-flood", _REDIRECT_RE, '>| "a" ' * (_WORST_CASE_BODY_LEN // 7)),
    # ⚠ FAILING tails (`zzz`), and ONE LONG BARE TARGET as well as floods: a
    # matching tail short-circuits and hides the blowup, and the first cut of
    # these rows both ended in `cp x y` and spaced the operator from the target
    # (which the gate then forbade), so a 428-green suite shipped a gate that
    # hung for twenty seconds on a thirty-character target (both reviews).
    ("gate-quoted-flood", _CP_MV_RE, '>"a b" ' * (_WORST_CASE_BODY_LEN // 7) + "zzz"),
    ("gate-unterminated-quote", _CP_MV_RE,
     '>"' + "a b " * (_WORST_CASE_BODY_LEN // 4) + "zzz"),
    ("gate-clobber-flood", _TEE_RE, '>| a ' * (_WORST_CASE_BODY_LEN // 5) + "zzz"),
    ("gate-bare-run-30", _CP_MV_RE, ";>" + "a" * 30 + " zzz"),
    ("gate-bare-run-512", _CP_MV_RE, ";>" + "a" * 512 + " zzz"),
    ("gate-bare-run-8000", _CP_MV_RE, ";>" + "a" * 8000 + " zzz"),
    ("gate-spaced-bare-run", _CP_MV_RE, ";> " + "a" * 8000 + " zzz"),
    ("gate-spaced-flood", _CP_MV_RE, "> a " * (_WORST_CASE_BODY_LEN // 4) + "zzz"),
    ("perl-open-space-run", _bash_patterns._PERL_OPEN_RE,
     "open(F,'>" + " a" * (_WORST_CASE_BODY_LEN // 2)),
]


@pytest.mark.parametrize("name,pattern,payload", _ROOT_SHAPE_TARGETS)
def test_root_shape_regexes_linear_on_their_own_floods(name, pattern, payload):
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        pattern.findall(payload)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(f"{name} regex exceeded {_CI_SAFE_BUDGET_MS}ms on its flood payload")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, f"{name} took {elapsed_ms:.1f}ms"


@pytest.mark.parametrize("name,payload", [
    ("extractor-redirect-quote-flood", '>"' * (_WORST_CASE_BODY_LEN // 2)),
    ("extractor-unterminated-quote", 'echo x > "' + "a " * (_WORST_CASE_BODY_LEN // 2)),
    ("extractor-gate-quoted-flood", '> "a b" ' * (_WORST_CASE_BODY_LEN // 8) + "cp x y"),
])
def test_bash_extractor_linear_on_root_shape_floods(name, payload):
    """The whole Bash extractor, raw-operand readers included, on the floods
    above: `raw_operand`'s quote extension is a bounded `str.find`, so a
    flood of unterminated quotes costs a bounded scan per match."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CHAIN_CEILING_MS / 1000.0)
    t = time.time()
    try:
        _bash_patterns._candidate_paths_from_bash(payload)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(f"{name}: the extractor exceeded {_CHAIN_CEILING_MS}ms")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CHAIN_CEILING_MS, f"{name} took {elapsed_ms:.1f}ms"


@pytest.mark.parametrize("shape", [
    "path_space_run", "path_printable_run", "mode_run", "layer_run", "my_run", "handle_run",
])
def test_perl_open3_re_linear_through_the_chain(shape):
    """DEF-813: the three-argument perl open through the live extraction
    chain (`_PERL_DASH_E_RE` -> the inner table), on every run the pattern
    admits -- an unclosed path after the second comma (the two-argument
    killer's shape), a mode-character run (bounded at two, so no split), a
    `:`-led layer run (bounded at 64), a `my ` run before the handle and a
    handle-character run -- each closed by the outer double quote so the
    head arm matches and the inner arm runs."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    from _bash_patterns import _candidate_paths_from_bash  # noqa: E402

    n = 16000
    body = {
        "path_space_run": "open(my $fh, '>', '" + " " * n,
        "path_printable_run": "open(my $fh, '>', '" + "a" * n,
        "mode_run": "open(my $fh, '" + ">" * n,
        "layer_run": "open(my $fh, '>:" + "a" * n,
        "my_run": "open(" + "my " * (n // 3) + ", '>', 'x",
        "handle_run": "open(" + "h" * n + ", '>', 'x",
    }[shape]
    command = 'perl -e "' + body + '"'
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        _candidate_paths_from_bash(command)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(f"_candidate_paths_from_bash exceeded {_CI_SAFE_BUDGET_MS}ms on the perl three-argument {shape} payload")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, f"{shape}: {elapsed_ms:.1f}ms"


@pytest.mark.parametrize("shape", ["head_flood", "root_flood", "predicate_flood", "git_preopt_flood"])
def test_find_delete_tier_linear_through_the_chain(shape, tmp_path):
    """DEF-815: the catastrophic find tier runs the opener over the masked
    scan, the directory chain over the statements and the root classifier
    over every root, so a flood of any of the three must stay under the
    per-consumer budget through the live entry point (the wall runs even
    under maintenance mode, so a slow path here is a slow hook for every
    Bash call). Each statement stays under the opener's 512-character span
    so the root and predicate floods really reach the classifier (review:
    a single 30 KB statement fell outside the span and timed only the
    pre-check). The fourth shape is DEF-814's review: a repeated git head
    with a global-option run before the subcommand, through the write
    extractor."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    import _bash_patterns as bp

    n = _WORST_CASE_BODY_LEN
    command = {
        "head_flood": ("find . -delete; " * (n // 16))[:n],
        "root_flood": ("find " + ("a/" * 200) + " -delete; ") * (n // 420),
        # attribute tests never narrow, so every statement's root still
        # reaches the classifier (a `-name` flood would be a sweep)
        "predicate_flood": ("find . " + ("-type f " * 50) + "-delete; ") * (n // 420),
        "git_preopt_flood": ("git -C x " * (n // 9)) + "checkout -- tools/cc/hooks/x.py",
    }[shape]
    if shape == "git_preopt_flood":
        signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
        t = time.time()
        try:
            bp._candidate_paths_from_bash(command)
            elapsed_ms = (time.time() - t) * 1000
        except _Timeout:
            pytest.fail(f"write extractor exceeded {_CI_SAFE_BUDGET_MS}ms on a git global-option flood")
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        assert elapsed_ms < _CI_SAFE_BUDGET_MS, f"git_preopt_flood took {elapsed_ms:.1f}ms"
        return
    if shape != "head_flood":
        assert sum(1 for _ in bp.iter_unnarrowed_find_delete_roots(command)) >= 60, shape
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        bp.has_catastrophic_find_delete(command, str(tmp_path), cwd=tmp_path)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(f"find tier ({shape}) exceeded {_CI_SAFE_BUDGET_MS}ms")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, f"find tier ({shape}) took {elapsed_ms:.1f}ms"


def test_the_nested_run_the_gate_once_carried_is_caught_by_these_rows():
    """The must-trip witness: the first cut's fragment -- a bare RUN inside the
    `+`, i.e. `(a+)+` -- blows the budget on the bare-run row above, so the
    row is proven to reach the shape it budgets (a row that cannot fail is
    not a gate)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    import _bash_patterns as bp

    nested = bp._CMD_POS_REDIRECT.replace(
        r"[^\s;|&\"'])+[ \t]+", r"[^\s;|&\"']+)+[ \t]+")
    assert nested != bp._CMD_POS_REDIRECT, "the live fragment is not the single-character form"
    anchor = bp._CMD_POS.replace(bp._CMD_POS_REDIRECT, nested)
    rx = re.compile(anchor + r"zzz\b")
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, 0.5)  # wall-clock-exempt: must-trip witness, the alarm firing is the pass
    try:
        rx.search(";>" + "a" * 26)          # no trailing blank: the tail FAILS, so it backtracks
    except _Timeout:
        return  # the witness fired: the row reaches the shape
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    pytest.fail("the nested-run fragment finished within half a second: the row no longer reaches the shape")


@pytest.mark.parametrize("label, build", [
    ("a loop-dense command near the scan cap", lambda: "for f in a b c; do echo x; done; " * 850),
    ("a loop past the cap, padded far beyond it", lambda: "for f in a; do echo x; done; echo " + "y " * 100000),
])
def test_the_discard_snapshot_arm_stays_within_budget(tmp_path, label, build):
    """DEF-837's lane gave the discard-snapshot arm the loop reader: every
    command that names a delete verb now also pays a loop scan. Both reviews
    flagged the cost (a 128k-word list measured 5.0 s through the arm before
    the loop reading was CAPPED as the wall's readers are). The arm, end to
    end, on a loop-dense command and on one padded far past the cap, stays
    inside the chain ceiling; a row that cannot fail is not a gate, so the
    text carries a delete verb and the loop witness each time."""
    import _speedbump

    command = build() + "; rm -f z"
    assert "do " in command and "rm " in command
    t = time.time()
    _speedbump._removal_snapshot_targets("Bash", {"command": command}, tmp_path)
    elapsed_ms = (time.time() - t) * 1000
    assert elapsed_ms < _CHAIN_CEILING_MS, f"{label}: {elapsed_ms:.1f}ms"


# The three rows below time a WALK -- a live judge or pre-pass over a flood at
# the command cap -- and until 2026-09-23 asserted the regex rows' 1 s budget,
# which the `_WALKER_CEILING_MS` comment above already explains is the wrong
# ceiling for a consumer whose floor is hundreds of milliseconds. Measured on
# the self-host Air (min / max of five, warm): the chain row's heredoc flood
# 577 / 871 ms, gone_flood 284 / 317, capped_middle 120 / 124, ps_block 34 / 40;
# the Bash pre-pass row about 500 ms, the PowerShell one's four floods under
# 400 ms each. A shared ubuntu runner read about 1.65x this box on two Release
# CI runs the same day, and the heredoc flood crossed 1 s on the second
# (run 35926017352) after passing the first -- a flake by margin, not a
# regression. They assert the walker tier's ceiling, and since 2026-09-24 the
# heredoc flood IS that tier's recorded floor (`_WALKER_FLOOR_MS`): ten times
# it, so a loaded runner cannot red a linear walk, and far under the minutes a
# quadratic one costs.
@pytest.mark.parametrize("shape", ["gone_flood", "capped_middle", "heredoc_flood", "ps_block_flood"])
def test_the_delete_walk_stays_linear_through_the_chain(shape, tmp_path):
    """The lane's review (its cost finding): the directory walk's removed set
    grows one entry per removal and every directory verb asks it, a patterned
    entry through an fnmatch per ancestor; past the scan cap the whole command
    is masked once for the middle; the walk reads every heredoc body and every
    PowerShell block. Each flood PRE-REGISTERS that its stressor reaches the
    walk (the counts below), then is timed through the live entry point under
    the per-consumer budget -- the wall runs even under maintenance mode, so a
    slow path here is a slow hook, and a hook timeout lets the command run."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    import _bash_patterns as bp

    n = _WORST_CASE_BODY_LEN
    tool = "Bash"
    if shape == "gone_flood":
        command = "".join(f"rm -rf a{i}x*; cd b{i}; " for i in range(n // 22))
        assert command.count("; cd b") >= 1000 and command.count("rm -rf a") >= 1000
    elif shape == "capped_middle":
        # past the 32 KB cap, under the masker's own 64 KB one: the whole
        # command is masked for the middle
        command = "echo x; " * 7500 + "rm -rf ./build"
        assert bp._BASH_COMMAND_CAP < len(command) <= bp._ROLE_MAP_CAP
        assert bp._capped_whole(command) is not None
    elif shape == "heredoc_flood":
        command = "".join(f"cat <<'E{i}'\nline\nE{i}\n" for i in range(n // 22)) + "rm -rf ./build"
        assert len(bp._heredoc_body_spans(command)) >= 1000
    else:
        tool = "PowerShell"
        command = "& { Set-Location a }; " * (n // 22) + "Remove-Item -Recurse ./build"
        assert command.count("{ Set-Location") >= 1000
    judge = bp.has_catastrophic_recursive_rm if tool == "Bash" else bp.powershell_recursive_removal_is_catastrophic
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _WALKER_CEILING_MS / 1000.0)
    t = time.time()
    try:
        judge(command, str(tmp_path), tmp_path)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(f"{shape}: the delete walk exceeded {_WALKER_CEILING_MS}ms")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _WALKER_CEILING_MS, f"{shape}: {elapsed_ms:.1f}ms"
