#!/usr/bin/env python3
"""Bash + PowerShell path-extraction primitives for write_guard.

Stdlib plus the `_hook_utils` sibling (one shared path helper); zero outward
dependencies. Returns raw path strings; the dispatcher passes them to
_protected_zones for normalization + zone classification.

Bypass scope, three levels:

(1) IN SCOPE - caught by the pre-pass + path-extraction regexes:
  - Literal protected paths in the command body (redirect, tee, cp/mv,
    sed -i, git checkout/restore, inline interpreter -c source, and a
    chmod/chown/chgrp/chflags/chattr/setfacl whose target is a protected path -- a permission
    change is the quietest way to silence a hook).
  - PowerShell: Set-Content/Out-File/Add-Content/Tee-Object/New-Item, the
    `>` redirects, Copy-Item/Move-Item (plus the cpi/copy/cp/mi/move/mv
    aliases) by -Destination or by the positional `src dst` pair, and the
    permission verbs icacls/attrib/Set-Acl/Set-ItemProperty (alias sp) --
    the Windows twins of the chmod line above; a backtick line-continuation
    is joined after masking, so a path split across lines is read whole.
  - Single-variable substitution where the variable is assigned a literal
    protected path on the same command line, e.g.
        F=.claude/settings.json; echo x > "$F"
    The pre-pass (``_expand_simple_var_assignments``) inlines literal
    NAME=value bindings -- any case of name, behind a declaration builtin,
    at any statement start -- before regex extraction.

(2) DOCUMENTED OUT OF SCOPE - not caught, by design:
  - Two-step subprocess: Write to /tmp/x.py, then Bash ``python /tmp/x.py``.
  - Multi-step variable indirection across separate commands.
  - $(...) command substitution, ${VAR:-default} parameter expansion.

(3) OUT OF SCOPE AND WON'T BE - cannot be statically determined.
"""
from __future__ import annotations

import os
import posixpath
import bisect
import contextlib
import contextvars
import fnmatch
import functools
import re
import shlex
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple, TypedDict

# Co-located sibling, the one shared path helper (`_msys_drive_to_windows`,
# DEF-731). This module is imported under TWO spellings: bare, with the hooks
# directory already on sys.path (write_guard and post_write_check insert their
# own directory; the tests' loader inserts it), and as
# `tools.cc.hooks._bash_patterns` from the repo root, where nothing has. So it
# puts its own directory on sys.path the way write_guard does instead of
# trusting every importer to have done so -- both reviewers reproduced the
# standalone collection error of the trusting form on 2026-09-10, hidden in
# the full suite only by collection order.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import _hook_utils  # noqa: E402

# Bash-write extraction patterns. Each produces a candidate path to check.
# Order matters: heredoc before plain redirect so we match the path before `<<`.
# `>|` is bash's clobber spelling (past `set -o noclobber`); it was absent, so
# that spelling allowed on ANY root (DEF-794, driven). The capture stays a bare
# run over the MASKED scan -- it locates the operand -- and the consumer reads
# the operand's characters from the raw text at those offsets (`raw_operand`),
# extended to a quote's close: that, not a quote-aware regex, is what survives
# a target with a space or a blanked inert character without a new backtracking
# surface on an operator that is retried at every `>`.
_REDIRECT_RE = re.compile(r">>?\|?\s*([^\s<>|&;]+)")
# The capture admits a quoted target (one quoted span, or a bare run): with
# `([^\s]+)` alone the arm never matched `cat > "<root with a space>/x" <<EOF`
# and the row passed through the redirect arm instead (review, DEF-794).
_HEREDOC_RE = re.compile(r"""cat\s*>\s*((?:"[^"\n]*"|'[^'\n]*'|[^\s"']+))\s*<<""")
# ---------------------------------------------------------------------------
# Command-position anchor.
#
# A verb only writes when it sits at a COMMAND position. Matching `\bcp\b`
# anywhere means a read-only `grep -rn "install" <zone>/` is read as a write,
# which denies an ordinary search of the harness's own source and teaches the
# operator to relaunch in maintenance mode -- lowering four other checks -- to
# run a grep.
#
# DERIVED from write_guard._HARNESS_ENV_PREFIX_RE rather than authored fresh:
# that sibling solves the same sub-problem and is already exercised by the
# release-gating benchmark. Inherited from it are its separator class -- note
# `(`, backtick and `{`, each of which is a real command position -- and the
# flag-tolerant wrapper run. That inherited set is a STARTING POINT, not the
# final one: the class below is wider (see the separator comment further down,
# which lists what a red-team added and why). Added here, each forced by a measured bypass
# rather than by guesswork: the wider wrapper vocabulary, flag-with-argument
# (`sudo -u me cp`), shell keywords (`then`/`do`), an optional path prefix
# (`/usr/bin/cp`), an optional opening quote (`'cp'`), and a separate branch for
# shell-exec wrappers.
#
# That last branch is the subtle one. A quote is NOT a general command-position
# opener -- treating it as one makes every quoted string a command position and
# re-opens the `grep -rn "install"` false positive this anchor exists to close.
# A quote opens a command position only BEHIND a shell-exec wrapper, so
# `eval "cp ..."` anchors while `grep -rn "install"` does not.
#
# The optional flag-argument is greedy, which is safe because of backtracking:
# on `sudo -n cp x <zone>/` the engine tries `-n cp` as flag+argument, fails to
# find the verb, backtracks, and the verb matches. Pinned by the
# `wrapper-flag-without-arg` control.
#
# Scope, stated honestly: this is a GRAMMAR ENUMERATION and is only as complete
# as the shapes that were measured. Token-level obfuscation is not covered and
# is not meant to be -- the deny is friction for habit-formation, not an
# adversary boundary. All capture groups are non-capturing so `.group(1)` at
# every call site is unchanged -- with TWO exceptions: `_CHMOD_CHOWN_RE`
# captures its verb as group(1) and its argument span as group(2), because
# `_permission_targets` dispatches on the verb (swapping the two returns an
# empty target list, not an error; the shape is pinned in
# tests/test_write_guard.py::TestPermissionVerbs), and `_PS_PERMISSION_RE` on
# the PowerShell leg has the same shape for the same reason (pinned in
# tests/test_write_guard.py::TestPowerShellPermissionVerbs).
_CMD_POS_WRAPPER = (
    r"(?:env|sudo|doas|command|time|nohup|timeout|xargs|exec|nice|ionice|stdbuf"
    # added after the step-11 red-team drove each of these as a real write:
    r"|setsid|strace|ltrace|watch|script|chrt|taskset|unbuffer|torify|proxychains)"
)
# A leading redirection is a command-position prefix: `>/dev/null cp x zone/`
# runs cp. Red-teamed; it denied at HEAD and the first anchor let it through.
# The target is a run of quoted spans and SINGLE bare characters, the operator
# optionally spaced from it: a bare `[^\s;|&]+` stopped at the first blank
# inside a quoted target, the gate then failed to reach the verb, and the `cp`
# after `>"<root with a space>/a.py"` was never examined -- one space disarmed
# eleven verbs at once (DEF-794, driven). `[ \t]*` after the operator admits
# `> file cp x <zone>`, which never opened the gate before (the target had to
# be glued); the target's characters exclude whitespace, so the run after the
# blanks has one parse. The quoted arms exclude a newline: an operand span
# stops at a line boundary here as everywhere else.
# ⚠ ONE CHARACTER PER ITERATION, NOT `[^...]+`. The first cut wrote the bare
# arm as a run inside the `+`, i.e. `(a+)+`: a bare target of n characters has
# 2^(n-1) partitions and `_CMD_POS`'s enclosing `(?:...)*` explored them all on
# a failing match -- `make clean; >build/artifacts/generated.log` wedged the
# PreToolUse path for over twenty seconds (both reviews, driven; 0.3 ms at
# HEAD), on every anchored arm and the speed bump's git checkpoints, and a
# wedged hook is not a deny: Claude Code times it out and runs the command.
# A single character per iteration gives each position exactly one parse
# (0.8 ms at n=8000). The ReDoS rows for this fragment carry a FAILING tail
# and a long bare target, which is the shape the first cut's rows lacked.
# `[&|]?` admits `>|` (the clobber spelling); its `&` branch is reached only
# by `_speedbump`, whose masked text is not ampersand-neutralised -- the
# extractor blanks `>&` before any anchored arm runs.
_CMD_POS_REDIRECT = (
    r"(?:[0-9]?[<>]{1,2}[&|]?[ \t]*(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s;|&\"'])+[ \t]+)"
)
# ⚠ Every token run below is `[^\s;|&]`, never `\S`. `\S` matches `;`, so a
# greedy `\S*` run scans PAST the command separator to end-of-input and then
# backtracks one character at a time looking for the required trailing space.
# On a long command with many `NAME=value;` segments that is O(n^2) — measured:
# it blew the 1s budget in
# tests/test_redos.py::test_var_expansion_prepass_bounded_by_cap on a 64KB
# input. Bounding to "not a separator" is also the semantically correct read: a
# shell token cannot span `;`, `|` or `&`.
# A wrapper flag may carry its own argument (`sudo -u me`, `timeout 5`).
#
# ⚠ THE TWO LOOKAHEADS ARE A ReDoS FIX, NOT STYLE. The flag-ARGUMENT arm
# overlapped two siblings, giving a repeated wrapper token two parses each and
# 2^n partitions on a FAILING match:
#   * a wrapper word — `env -i env` could read `env` as -i's argument OR as the
#     next wrapper. Measured on `"env -i " * 30`: >5000 ms.
#   * a bare numeric — `nice -n 10 nice` could read `10` as -n's argument OR via
#     the `\d[^\s;|&]*` arm. Measured on `"nice -n 10 " * 30`: >5000 ms.
# `xargs -0 ` and `strace -f ` blew up the same way. Declining both shapes makes
# the parse deterministic: each token has exactly one arm that can own it.
# After: 5.3 ms at 2000 repetitions, and 29 accept/reject shapes are unchanged.
#
# This fragment fronts every command-position consumer, and a wedged regex is a
# HANG — write_guard's `except BaseException` catches exceptions, not a hang, so
# the PreToolUse call never returns. Budgeted by
# tests/test_redos.py::test_cmd_pos_linear_on_repeated_prefix_run, whose token
# list is DERIVED from the arms below so a future wrapper enrols by itself.
_CMD_POS_WRAP_RUN = (
    "(?:" + _CMD_POS_WRAPPER
    + r"(?:[ \t]+(?:-[^\s;|&]+(?:[ \t]+(?!" + _CMD_POS_WRAPPER
    + r"[ \t])(?!\d)[^-\s;|&][^\s;|&]*)?|\d[^\s;|&]*))*[ \t]+)"
)
# An assignment prefix, ended where bash ends the word: at the first UNQUOTED
# blank (DEF-848's lane). The value is a run of pieces -- a plain character,
# a backslash and the character it escapes, a lone `$`, an ANSI-C `$'...'`,
# a single-quoted span, a double-quoted span -- each opening on a character
# no other piece opens on, so every adjacent pair is mutually exclusive (the
# ReDoS rule) and the run can split one way only. Until 2026-09-19 the value
# was `[^\s;|&]*`, which ended at the first blank of ANY kind: a word inside
# a quoted value opened a command position (`MSG='fix: <verb> ...'` read the
# verb as run -- a false wall on a message variable), and a verb after a
# prefix whose quoted value held a blank was at no command position at all
# (`A='a b' <verb> ...` -- read by no verb arm). A `$(...)` in a value still
# ends at its first blank, as before: its nesting is not regular.
#: The value of an assignment word as bash reads it -- the one home of the
#: piece grammar above; `_CMD_POS_ENV_ASSIGN` and write_guard's
#: `_BASH_ENV_PREFIX_TARGET_RE` both read it from here.
_ASSIGN_VALUE = (
    r"""(?:[^\s;|&'"$\\]|\\.|\$(?!')|\$'(?:[^'\\]|\\.)*'|'[^']*'|"(?:[^"\\]|\\.)*")*"""
)
_CMD_POS_ENV_ASSIGN = r"(?:[A-Za-z_]\w*=" + _ASSIGN_VALUE + r"[ \t]+)"
# `if` / `while` / `until` open a command position in their CONDITION, not
# only in the body `then` / `do` open; `!` negates a pipeline and runs it.
# All four were denied by the unanchored interpreter openers and ALLOWED by
# the first anchored cut (DEF-704 failure-mode review, driven: `if python3 -c
# "<kill-switch write>"; then :; fi`), and had been allowed for every other
# anchored verb all along. `!` has its own arm because the keyword roster is
# scraped as words by its pin.
_CMD_POS_KEYWORD = r"(?:then|do|else|elif|if|while|until)"
_CMD_POS_NEGATE = r"(?:![ \t]+)"
# a shell-exec wrapper DOES open a command position inside its quoted argument.
#
# The trailing run is ONE whitespace run plus an optional quote that OWNS its own
# trailing run -- deliberately NOT `[ \t]*[\"']?[ \t]*`. That earlier form had two
# adjacent whitespace runs separated by an OPTIONAL quote, so a single `eval `
# could be partitioned two ways (space in the first run, or quote-absent and
# space in the second). Under `_CMD_POS`'s `(?:...)*` that is 2^n partitions, and
# on a FAILING match the engine explores all of them: measured >5s at 40
# repetitions of `eval `, against 0.5ms at 2000 repetitions after this change.
#
# It is a hang, not a deny -- write_guard's `except BaseException` crash guard
# catches exceptions, not a wedged regex -- and this fragment fronts every
# command-position consumer on the PreToolUse path, so it would stall every tool
# call. CONSUMERS: the extraction regexes in this module PLUS `_speedbump`'s
# four git checkpoints, which import `_CMD_POS` across the module boundary --
# a dependency no file-overlap scan can see, and the reason the count is
# described rather than written as a number here (the previous wording said
# THIRTEEN and was stale on the day it landed).
# Budgeted by tests/test_redos.py::test_cmd_pos_linear_on_repeated_prefix_run,
# which drives every prefix token this fragment admits against a FAILING tail
# (a matching tail short-circuits and hides the blowup, which is why the older
# quoted-body population never caught it).
_CMD_POS_EXEC_QUOTE = r"(?:\b(?:eval|(?:ba|z|k|da)?sh[ \t]+-c)[ \t]*(?:[\"'][ \t]*)?)"
# Assembled with ``+`` concatenation of module-level names, NOT f-strings.
# That is a hard requirement, not a style choice: the ReDoS dot-star gate
# (tests/test_redos.py::test_no_unreviewed_dotstar_in_hook_regexes) statically
# reconstructs every hook regex to prove it carries no unbounded dot-quantifier,
# and its reconstructor resolves literals, ``+`` concatenation and module-level
# Name references recursively -- but NOT a general f-string interpolation. An
# f-string-assembled pattern is unresolvable, so the gate fails closed and the
# regex ships unproven. Keep this form.
#
# Separator class and the whitespace that may follow it. Both were widened by
# the step-11 red-team, which drove each shape below as a genuine write and
# found it denied at HEAD but allowed by the first anchor:
#   \r      `echo hi\r cp …`            (CR as a line separator)
#   )       `case x in y) cp …;;`       (a case arm opens a command)
#   }       `f() { cp …; }`             (close of a compound)
#   \v \f   `echo hi;<VT>cp …`          (vertical tab / form feed after `;`)
# The verb may also be prefixed by `\` (alias-suppression idiom `\cp`) or by
# `$` (ANSI-C quoting `$'cp'`) -- both are ordinary shell, both denied at HEAD.
# The directory before the verb, DEF-704: `/`- or `\`-separated, a drive
# letter in front, and -- inside a quote -- spaces (`"C:\Program
# Files\Python312\python.exe" -c`, `"/opt/my tools/python3" -c`), or
# escaped spaces unquoted (`C:\Program\ Files\...`). The unanchored
# interpreter openers accepted all of these and the first anchored cut lost
# them (failure-mode review, driven). The colon is a drive letter only: a
# bare `:` in the run let `http://x/cp` and `key:value/cp` open a command
# position bash never runs (code review). Both quoted arms are bounded and
# every adjacent quantifier pair is mutually exclusive, for the ReDoS gate.
_CMD_POS_SEP = r"[;&|\n\r(){}`]"
_CMD_POS_WS = r"[ \t\r\v\f]*"
_CMD_POS_VERB_PREFIX = (
    r"\\?\$?(?:[\"'][^\"'\n]{0,256}[/\\]"
    r"|[\"']?(?:(?:[A-Za-z]:)?(?:[\w./-]|\\ ?)*[/\\])?)"
)
# ⚠ SPLIT, NOT COPIED. `_CMD_POS_NO_VERB` is every command-position arm WITHOUT
# the trailing verb prefix; `_CMD_POS` is that plus the prefix, so every existing
# consumer sees a byte-identical pattern and no test churns.
#
# The split exists because `_CMD_POS_VERB_PREFIX`'s optional `["']` is there for a
# quoted VERB (`$'cp'`, `"cp"`) -- and a consumer matching an ENV ASSIGNMENT has
# no such shape: `'VAR'=1` is not an assignment in any shell. For those consumers
# the quote arm is pure false-positive surface, because `(` is a separator, so
# `(` + `'` reads as a command position inside any quoted argument to a non-shell
# command. Measured live: `python3 -c "...search('ESPALIER_MAINTENANCE_MODE=1')"`
# -- a read-only introspection of this very module -- was DENIED when
# `_HARNESS_ENV_PREFIX_RE` was first anchored on the full `_CMD_POS`.
# Assignment-matching consumers take `_CMD_POS_NO_VERB`; verb-matching consumers
# (every extraction regex here, `_speedbump`'s git checkpoints) keep `_CMD_POS`.
#
# The CLOSING quote of a quoted verb. `_CMD_POS_VERB_PREFIX` admits the OPENING
# one (`"tee"`, `'git'`: shell quote-removal invokes the bare verb), but an arm
# whose grammar continues at whitespace right after the verb -- `tee`, the
# `git` verbs, the statement-reader heads -- stopped at the closing quote and
# ALLOWED `"tee" -a <hook>` beside a denied `tee -a <hook>` (DEF-410q, §C4;
# measured 2026-09-13 over every `_CMD_POS`-anchored arm: the arms that demand
# whitespace missed, the rest carried an ad hoc copy of this class or a span
# that swallowed the quote). One home: every verb arm below and
# `_speedbump._GIT_CMD` read it from here, and
# `tests/test_write_guard.py::TestQuotedVerbTailIsUniform` walks the anchored
# arms with the bare control beside each quoted spelling. A single optional
# character, so no adjacent quantifier can share its input (the ReDoS rule).
_QUOTED_VERB_TAIL = r"""["']?"""
_CMD_POS_NO_VERB = (
    r"(?:(?:^|" + _CMD_POS_SEP + ")" + _CMD_POS_WS + "(?:"
    + _CMD_POS_WRAP_RUN + "|" + _CMD_POS_ENV_ASSIGN
    + "|" + _CMD_POS_KEYWORD + r"[ \t]+"
    + "|" + _CMD_POS_NEGATE
    + "|" + _CMD_POS_REDIRECT
    + "|" + _CMD_POS_EXEC_QUOTE + ")*"
    + r"|(?<=/)" + _CMD_POS_WRAP_RUN + "(?:" + _CMD_POS_ENV_ASSIGN + ")*"
    + "|" + _CMD_POS_EXEC_QUOTE + ")"
)
# ⚠ THE WRAPPER ARM WAS NARROWED FROM `\b` TO `(?<=/)` ON 2026-08-26, and the
# first attempt DELETED it, which was a fail-open caught by a single test.
#
# Reading the keyword defect below as a general "unanchored arms are stray
# restatements" is what produced that attempt. It is false here.
# `test_hooks.py::test_usr_bin_env_prefix_still_denied` pins `/usr/bin/env
# ESPALIER_MAINTENANCE_MODE=1`: a PATH-QUALIFIED wrapper is a genuine command
# position whose preceding character is `/`, not a statement separator, so arm 1
# cannot reach it and deleting this arm let the harness env-prefix bypass
# through. That row exists because an adversarial pass put it there.
#
# But `\b` was far wider than that reason needed. A word boundary also fires
# after a SPACE, so the ordinary prose `echo "you could sudo <delete> / and lose
# the tree"` opened a command position and hard-denied -- the wrapper twin of the
# keyword defect below, found by asking the class question. `(?<=/)` keeps
# exactly the spelling the pinned row is about and drops the prose: an
# unqualified wrapper at a real command position is already arm 1's job.
#
# The THIRD unanchored arm, `_CMD_POS_EXEC_QUOTE`, is DELIBERATELY UNTOUCHED.
# Driven: `echo "never eval <delete> /"` and the `sh -c` spelling already ALLOW,
# because `mask_inert_syntax` relieves exec-opener mentions separately
# (`TestExecOpenerMentionsAreRelievedInsideInertCommands`). It carries no false
# positive, and narrowing it would lose the quoted-argument command position it
# exists for. Three unanchored arms, three different right answers: delete one,
# narrow one, keep one. That spread is why the class question decides the UNIT of
# work and never the verdict -- each member still has to be driven on its own.
#
# ⚠ A FOURTH ARM, `\b` + `_CMD_POS_KEYWORD` + `[ \t]+`, WAS REMOVED 2026-08-26.
# It restated the keyword arm three lines up WITHOUT the separator prefix, so a
# bare `\b(?:then|do|else|elif)` opened a command position anywhere the word
# appeared -- including inside a quoted string, a `#` comment, a quoted heredoc
# body and a commit message. The ordinary English word "then" was enough.
#
# THE MASK COULD NOT REACH IT, WHICH IS WHY IT SURVIVED THE ANCHORING SWEEP.
# `mask_inert_syntax` neutralises CHARACTERS in `_INERTABLE_SYNTAX`; this is a
# WORD, so no masking change of any kind could have relieved it. Driven with a
# connector x punctuation matrix, the punctuation column was perfectly flat:
# `then`/`do`/`else`/`elif` denied at every punctuation setting including none,
# and `next`/`later`/`when` allowed at every one. The axis was never the
# punctuation the finding was filed under.
#
# ⚠ AND IT FRONTED THE HARD TIER. `has_catastrophic_recursive_rm` feeds the
# no-re-issue tier `ESPALIER_MAINTENANCE_MODE=1` cannot bypass, and it returned
# True for `git commit -m "docs: then <delete> / is refused"`.
#
# ⚠ REMOVING IT LOSES NOTHING, and the reason is grammatical rather than
# empirical: bash recognises `then`/`do`/`else`/`elif` as reserved words ONLY at
# a command position, and every character that opens one -- `;` `&` `|` newline
# `(` `{` `` ` `` -- is already in `_CMD_POS_SEP`, so the anchored arm above
# covers every real grammar. Confirmed against all four rows of
# `_KEYWORD_WRITE_SHAPES` in `tests/test_write_guard_command_position.py`, which
# place their keyword behind `;` precisely because that is where bash puts it.
# Both arms arrived in the same hunk (`e28952a`, 2026-08-03); this one was a
# redundant restatement, never a carve-out with a reason.
_CMD_POS = _CMD_POS_NO_VERB + _CMD_POS_VERB_PREFIX

# ── a command DISCOVERED by the shell and invoked (DEF-827's Bash twin) ──────
#: `$(which find) . -delete`, `"$(command -v rm)" -rf .`, `$(type -P find)`,
#: the backtick form, behind a wrapper word -- and under zsh, which is the
#: Bash tool's shell on a macOS host (the tool runs the operator's login
#: shell), `$(whence find)`, `$(where find)` and the equals expansion
#: `=find`: the substitution IS the command word, and the walker reads its
#: `(` as the command position of `which`, never of the verb -- driven on
#: /bin/bash and /bin/zsh 2026-09-16, each wiped a throwaway and no tier saw
#: it (thirty-one of the thirty-six `_CMD_POS`-anchored arms with a
#: quoted-verb fixture allowed the discovered spelling beside a denied bare
#: one; the five that held deny through another reader). Resolved ONCE, as
#: the second stage of `splice_line_continuations`, the raw pre-pass every
#: Bash reader applies (`_resolve_bash_discovered_heads`): the command
#: position is kept verbatim, the verb keeps its offset, the substitution's
#: own characters -- the quote, `$(`, the discovery verb and its switches,
#: `)` -- are blanked, same length, so every anchored head reads the verb
#: where the shell runs it and a span read from the raw text by offset lands
#: on the operands, never on the substitution's close (the masker is the
#: wrong home: a reader masks a text it has already spliced, and reads its
#: operands from the spliced raw one). Anchored on `_CMD_POS_NO_VERB` (a
#: wrapper word, an env assignment and the exec-quote arm admitted; the verb
#: prefix not -- the quote before `$(` is the substitution's, blanked with
#: it), so it fires ONLY when the substitution is itself the head: `echo
#: "$(which find) . -delete"` and `rm -rf $(which find)` keep their operand
#: reading. The outer quote is PAIRED (`(?P<q>"?)` ... `(?P=q)`; a double
#: quote only, a single-quoted substitution does not expand): an unpaired
#: optional quote ate the closer of `echo ";$(which find)" . -delete`, the
#: masker bailed on the unbalanced command and the mention drew a HARD wall
#: (code review, driven). Inside the substitution: one wrapper word (`env`,
#: `builtin`), the alias-suppression backslash, a path to the discovery
#: verb, a quoted discovery verb or verb, `which -a`, `command -pv`, `--`, a
#: trailing `2>/dev/null`. Declared limits, each a DECLARED matrix row: a
#: pipeline or a list inside the substitution (`$(which -a find | head
#: -1)`, `$(hash -t find || which find)`), a parameter as the discovery verb
#: (`${WHICH:-which}`), and the path held in a VARIABLE (`x=$(which find);
#: $x . -delete`), the twin of the PowerShell object-in-a-variable limit.
#: Every adjacent quantifier pair is mutually exclusive; the budget rows are
#: in tests/test_redos.py. Built by `+` from names for the static ReDoS gate.
_DISCOVERED_VERB = r"[\w.][\w.-]*"
_BASH_DISCOVERY_VERB = (
    r"(?:(?:env|builtin|exec|sudo|command)[ \t]+)?"
    r"\\?(?:[\w./-]*/)?[\"']?"
    r"(?:which|whence|where|command[ \t]+-(?:pv|vp|v)|type[ \t]+-[a-zA-Z]{1,3})[\"']?"
    r"(?:[ \t]+-[a-zA-Z]+)*[ \t]+(?:--[ \t]+)?"
)
_BASH_DISCOVERED_SUBSTITUTION = (
    r"\$\([ \t]*" + _BASH_DISCOVERY_VERB
    + r"(?P<vq_s>[\"']?)(?P<verb_s>" + _DISCOVERED_VERB + r")(?P=vq_s)"
    + r"(?:[ \t]+2>/dev/null)?[ \t]*\)"
)
_BASH_DISCOVERED_BACKTICK = (
    r"`[ \t]*" + _BASH_DISCOVERY_VERB
    + r"(?P<vq_b>[\"']?)(?P<verb_b>" + _DISCOVERED_VERB + r")(?P=vq_b)"
    + r"(?:[ \t]+2>/dev/null)?[ \t]*`"
)
_BASH_DISCOVERED_EQUALS = r"=(?P<verb_e>" + _DISCOVERED_VERB + r")"
_BASH_DISCOVERED_HEAD_RE = re.compile(
    "(?P<pos>" + _CMD_POS_NO_VERB + r")"
    r"(?:(?P<q>\"?)(?:" + _BASH_DISCOVERED_SUBSTITUTION + "|" + _BASH_DISCOVERED_BACKTICK
    + r")(?P=q)|" + _BASH_DISCOVERED_EQUALS + r")"
)


def _keep_the_verb(m: "re.Match[str]") -> str:
    """The match with its ``pos`` group kept verbatim, the one ``verb*``
    group that matched kept at its offset and every other character
    blanked: same length, so a consumer reading offsets across the raw and
    scan texts still lands on the operands. The verb groups are DERIVED
    from the pattern (``groupindex``), never listed at the call: a listed
    set that missed a branch blanked the verb with it, and a resolution that
    deletes the head is an allow (failure-mode review, driven). No verb
    group matched: the match is returned as it is -- no resolution, never
    half of one."""
    start = m.start()
    verbs = [g for g in m.re.groupindex if g.startswith("verb") and m.group(g) is not None]
    if len(verbs) != 1:
        return m.group(0)
    out = [" "] * (m.end() - start)
    out[m.start("pos") - start: m.end("pos") - start] = m.group("pos")
    out[m.start(verbs[0]) - start: m.end(verbs[0]) - start] = m.group(verbs[0])
    return "".join(out)


@functools.lru_cache(maxsize=64)
def _resolve_bash_discovered_heads(scan: str) -> str:
    """``scan`` with every command the shell discovered and invoked at a
    command position read as the command it names (DEF-827). Same length.
    Memoised: the dangerous tier splices the same text once per statement
    it places (1,507 calls on an 18 KB command, measured by the code
    review), so the pass is paid once per distinct text."""
    if "$(" not in scan and "`" not in scan and "=" not in scan:
        return scan
    return _BASH_DISCOVERED_HEAD_RE.sub(_keep_the_verb, scan)
# ---------------------------------------------------------------------------

# Tee with any number of flag tokens; multi-arg extraction lives in
# `_candidate_paths_from_bash`.
# The bare arm admits `<>` on purpose: `tee 2> 1 <hook>` (the neutralised
# `2>&1`) must reach `_operands`, which drops the redirect and its target; with
# `<>` excluded the run stopped at `2` and the hook was never read.
_TEE_RE = re.compile(
    _CMD_POS + r"\btee\b" + _QUOTED_VERB_TAIL + r"((?:[ \t]+-\S+|[ \t]+[^-\s][^\s|;&]*)*)"
)
# Verb-regex class: the six extraction regexes shaped
# ``\bVERB...<unbounded span>...<required token>`` (sed -i / dd of= / tar -C /
# cp|mv|install -t / PS -Path / git checkout --) are QUADRATIC on a repeated
# verb. ``finditer`` retries the verb at every space-separated occurrence, and
# at each one an unbounded ``[^|;&]*?`` / ``(?:...)*`` span scans toward a
# required token that is ABSENT -> O(verbs * remaining) = O(n^2). Adding a word-
# boundary lookbehind does NOT help (space-separated verbs are all word-starts).
# Fix: BOUND each span -- ``{0,512}`` chars or ``{0,64}`` tokens -- so per-start
# work is O(1), total O(verbs) = linear. The bound is far larger than any real
# invocation's option string, so legitimate writes (incl. ``sudo dd of=...``,
# multi-ref ``git checkout a b -- path``) still extract.
# DOCUMENTED RESIDUAL (friction-layer, CI/harness-guard.yml backstops a
# committed write regardless): a protected target pushed >512 chars / >64 tokens
# PAST its verb is not extracted -- contrived padding, not a real command shape.
# See docs/sharp-edges/protected-zone-path-equivalence.md sibling note.
_SED_INPLACE_RE = re.compile(
    _CMD_POS + r"""sed""" + _QUOTED_VERB_TAIL
    + r"""[ \t]+(?:[^\s]+[ \t]+){0,64}(?:-i|--in-place)"""  # {0,64}: bound the option run
    r"""(?:[ \t]+(?:''|"")|[ \t]+\S+)?"""   # optional backup extension (incl. macOS '' form)
    r"""(?:[ \t]+'[^']*'|[ \t]+"[^"]*"){0,64}"""  # skip quoted sed expressions ({0,64}: bound)
    r"""[ \t]+([^\s'"]+)"""               # capture target file
)

# ── In-place edit extraction: a TOKENIZER, not a grammar regex ───────────────
# `_SED_INPLACE_RE` above is RETAINED deliberately, and the honest reason is
# LINKAGE PLUS FAIL-SAFE OVER-YIELD -- not unique coverage. Measured over a 240-row
# delimiter x in-place x pre-flag population, it catches 16 rows the tokenizer does
# not; driven through a real `/bin/bash`, ALL SIXTEEN are shapes that never write
# (`sed -i s|a|b| victim.txt` is a PIPELINE and `sed -i s;a;b; victim.txt` is three
# commands -- victim.txt is unmodified in both, verified). So the tokenizer covers
# every real invocation the regex does, and the regex's extra hits are harmless
# over-extraction. What genuinely forbids deleting it is that `write_guard.py`
# re-exports it and `tests/test_redos.py` imports it BY NAME -- a removal breaks
# COLLECTION of that whole file rather than failing one assertion.
# ⚠ Do not "clean up" the union on the theory that the tokenizer dominates. It
# does, on real invocations -- but `TestTheRetainedRegexIsWitnessed` pins that
# claim so the next reader inherits the measurement instead of re-deriving it.
# It is no longer the only extractor: it modelled sed's option grammar in one pattern and
# got it wrong in both directions. Its optional backup-extension group does double
# duty -- with GNU `-i` it happens to consume the script so the capture lands on
# the file; with BSD `-i ''` it consumes the `''`, and the expression-skip that
# follows handles only QUOTED scripts, so an unquoted script was captured as the
# target. A glued `-i.bak` leaves no whitespace for the backup arm and never
# matched at all. Measured against a DERIVED population (pre-flag run x in-place
# spelling x script delivery x target count), 237 of 333 sed spellings and 37 of
# 37 perl spellings reached a protected path unchecked.
#
# The two loops run in UNION, which is why this is safe: the regex keeps every
# capture it already had, so no currently-denied spelling can regress, and the
# tokenizer adds the rest. Over-yield is fail-safe here -- the caller filters
# through the protected-zone check, and a spurious `s/a/b/` matches no zone.
# ⚠ THE SPAN MUST BE QUOTE-AWARE, and the first cut was not. A plain
# `[^\n;|&]{0,512}` class truncates the segment at the first `|`, `;` or `&` --
# which are the three commonest sed/perl SUBSTITUTION characters, inert to the
# shell inside a quoted script and used constantly to avoid escaping paths.
# Driven, the naive class let `sed -i.bak 's|a|b|' <protected>` and
# `perl -pi -e 's|a|b|' .claude/settings.json` through: the filename fell outside
# the segment entirely, so the tokenizer saw no operands at all. Deleting the
# separators from the class is the WRONG repair -- it would swallow a genuine
# `sed -i '' s/a/b/ notes.md; cat cc/x` into one segment. A quoted run is consumed
# as ONE unit instead, so a separator inside quotes is script text and a separator
# outside them still ends the command.
# {0,512} / {0,256}: verb-regex class bounds (see _SED_INPLACE_RE comment).
# ⚠ The bound is a silent EXTRACTION CLIFF, not a no-match: unlike `_DD_OF_RE`
# and `_TAR_C_RE`, which anchor on a required trailing token so overflow means
# "no match, no claim", this segment IS the operand list -- so a target pushed
# past the bound drops every operand and fails OPEN. Pinned by a boundary test.
_INPLACE_VERB_ALT = r"(?:sed|perl)"
_INPLACE_SEGMENT_RE = re.compile(
    # `_QUOTED_VERB_TAIL` tolerates a quoted verb (`'sed' -i ...`), which shell
    # quote-removal collapses back to a plain `sed` -- the one home every verb
    # arm reads. IGNORECASE for a case-insensitive filesystem
    # (`SED` resolves on APFS), matching `_LN_CP_INVOCATION_RE`.
    _CMD_POS + r"(?P<seg>" + _INPLACE_VERB_ALT + _QUOTED_VERB_TAIL + r"\b(?!=)"
    # A same-line comment is cut from the captured segment by
    # `_strip_span_tail` before tokenising (see the `_INSTALL_CMD_RE` block).
    # `#` is NOT excluded from the bare arm: a `#` inside a filename is literal,
    # and excluding it cut the segment there and dropped every later operand.
    + r"""(?:'[^'\n]{0,256}'|"[^"\n]{0,256}"|[^\n;|&]){0,512})""",
    re.IGNORECASE,
)


class _InplaceProfile(TypedDict):
    """The per-verb option grammar the tokenizer walks.

    Declared rather than inferred: a bare dict literal types every value as
    ``object``, and the membership tests below (``name in
    profile["long_inplace"]``) then have no element type to check against.
    """

    long_inplace: tuple[str, ...]
    long_script: tuple[str, ...]
    script_letters: frozenset[str]
    inplace_letters: frozenset[str]
    positional_script: bool
    separable_suffix: bool


# ⚠ KEYED ON THE VERB DELIBERATELY. sed and perl spell the same idiom with
# DIFFERENT rules, and sharing a row reintroduces the defect this replaces:
#
#   * script slot -- sed takes ONE bare script argument unless `-e`/`-f`/
#     `--expression` supplied it. perl has NO bare-script slot; absent `-e`/`-E`
#     its first non-option token is a script FILE. Inherit sed's "no -e seen ->
#     the next token is the script" rule for perl and `perl -i '' <protected>`
#     swallows the protected file itself, yielding zero candidates -- a silent
#     fail-open with the same shape as the original bug.
#   * `-i` suffix -- BSD/macOS sed accepts a SEPARATE token (`-i ''`); GNU sed and
#     perl accept a GLUED one only (`-i.bak`). sed must accept either, because the
#     extractor cannot know which dialect will run; perl must not.
#
# `separable_suffix` consumes the next token ONLY when it is an empty quote pair,
# never a bare word -- a bare `.bak` is indistinguishable from a filename, and
# under-yield is the failure mode that matters.
_INPLACE_PROFILES: dict[str, _InplaceProfile] = {
    "sed": {
        "long_inplace": ("--in-place",),
        "long_script": ("--expression", "--file"),
        "script_letters": frozenset("ef"),
        # ⚠ `-I` is BSD sed's in-place flag (files as one stream), one shift key
        # from `-i` and real on this host -- driven, `sed -I '' s/a/b/ f` writes.
        # perl's `-I` is an INCLUDE PATH and must not be read as in-place, which
        # is why this is per-profile rather than a shared `letter in "iI"`.
        "inplace_letters": frozenset("iI"),
        "positional_script": True,
        "separable_suffix": True,
    },
    "perl": {
        "long_inplace": (),
        "long_script": (),
        "script_letters": frozenset("eE"),
        "inplace_letters": frozenset("i"),   # perl -I is an include path
        "positional_script": False,
        "separable_suffix": False,
    },
}
_EMPTY_QUOTE_PAIRS = ("''", '""')
# cp/mv: capture the operand SPAN; the consumer tokenises it
# (`_positional_operands`), takes the LAST positional as the destination and
# every earlier one as a source, so a directory destination (`cp x .claude/`)
# lands `<dst>/<basename(src)>` for each source. The regex used to capture the
# first two operands literally, which was three fail-opens at once (driven at
# this tree, verification pass): a multi-source `cp a b <hooks>/` read `b` as
# the destination; a value flag before the pair (`cp -S .bak src <settings>`)
# read `.bak` as the source and `src` as the destination; and a redirect whose
# operator carries `&` before the destination (`cp evil.json 2>&1 <settings>`)
# ended the span class before the destination was read (see
# `_REDIRECT_AMPERSAND_RE`). The lessons below still hold, inside the tokenizer.
# ['"]? tolerates a quoted verb (`'cp' src dst`), which shell quote-removal
# collapses back to a plain `cp` -- otherwise the required whitespace sits
# after the closing quote and the verb yields no match (a fail-closed miss).
# Whitespace after is still required, so a `cp=`/`mv=` variable assignment
# (`=` is not a quote) still yields no match and stays allowed.
# ⚠ Long flags: `-[a-zA-Z]+` cannot match `--force` (after the first `-` it
# demands a letter and finds the second `-`), and the option run that first
# modelled them read `--force` as the SOURCE and lost the destination (driven:
# `cp --force src.py <protected>` ALLOWED while `-f` denied). The tokenizer
# drops every `-`-prefixed token, long or short, glued value or not.
# A quoted operand with a space is ONE positional: `(\S+)` split
# `cp "my file.txt" <protected>` into two fake sources and the protected
# destination never entered the match (DEF-638 review, driven live: allow).
# The bare arm of `_QUOTED_OR_BARE_OPERAND` excludes quote characters on
# purpose: with `\S+` the engine could re-read a quoted operand as a bare token
# whenever a LATER mandatory part failed, and did -- `ln -s /tmp/evil
# "tools/cc/hooks/my file.py"` backed off the quoted alternative and captured
# `file.py"` as the linkname. The span is one run of quote-aware operands
# (disjoint alternatives, linear), so a quoted `|` inside a source survives.
_QUOTED_OR_BARE_OPERAND = r"(?:\"[^\"]*\"|'[^']*'|[^\s\"']+)"
#: The quote-aware operand SPAN a verb's arguments make -- flags, sources
#: and a destination as one run of quoted-or-bare operands (linear: the
#: alternatives are disjoint on their first character). `_CP_MV_RE` spells
#: it inline below; the remove/relocate arms compose it by name (§C52).
_OPERAND_SPAN = (
    r"((?:\"[^\"]*\"|'[^']*'|[^\s;|&\"']+)"
    r"(?:[ \t]+(?:\"[^\"]*\"|'[^']*'|[^\s;|&\"']+))*)"
)
_CP_MV_RE = re.compile(
    # `verb` is a named group (§C52): a move's SOURCE is a relocated operand
    # the remove/relocate reader classifies, a copy's source is a read. The
    # operand span is group 2 from here on.
    _CMD_POS + r"\b(?P<verb>cp|mv)" + _QUOTED_VERB_TAIL + r"[ \t]+"
    r"((?:\"[^\"]*\"|'[^']*'|[^\s;|&\"']+)"            # the operand span:
    r"(?:[ \t]+(?:\"[^\"]*\"|'[^']*'|[^\s;|&\"']+))*)"     # flags, sources, destination
)
# The operand a verb REMOVES (§C52, DEF-795): the same span on the remove
# verbs. The safety tier keeps its own reader (`_RM_SEGMENT_RE` +
# `rm_recursive_force_operands`: the recursion flags and the catastrophic
# operands, whitespace-split); this arm answers the zone's question -- WHICH
# path goes -- and is quote-aware like every write arm, so a target under a
# root with a space is one operand. `\b(?!=)` skips an assignment (`rm=...`)
# and never narrows to whitespace: a quoted verb must still fire.
_DESTROY_RE = re.compile(
    _CMD_POS + r"\b(?:rm|unlink|rmdir|shred)\b(?!=)" + _QUOTED_VERB_TAIL + r"[ \t]+" + _OPERAND_SPAN
)
# `rename [opts] <expression-or-from> [<to>] files...` (the perl and the
# util-linux spellings): every positional after the first is relocated.
_RENAME_RE = re.compile(
    _CMD_POS + r"\brename\b(?!=)" + _QUOTED_VERB_TAIL + r"[ \t]+" + _OPERAND_SPAN
)
# `zip [opts] <archive> inputs...`: the inputs are copied by effect (the
# secret leg reads them; the zone leg does not -- an archive reads).
_ZIP_RE = re.compile(
    _CMD_POS + r"\bzip\b(?!=)" + _QUOTED_VERB_TAIL + r"[ \t]+" + _OPERAND_SPAN
)

# Write verbs not covered by _CP_MV_RE / _TEE_RE / _REDIRECT_RE.
# Each captures the final write target so it can be normalised and
# checked against _is_protected like the existing verbs.
# {0,512}: verb-regex class bound (see _SED_INPLACE_RE comment).
# \b(?!=): exclude a `dd=…` shell assignment (`=` is a word boundary a bare `\bdd\b`
# false-matched), but NOT a quoted `'dd' …` real command. Same guard across the verbs.
_DD_OF_RE = re.compile(_CMD_POS + r"\bdd\b(?!=)[^|;&\n]{0,512}?\bof=([^\s|;&]+)")
# The INPUT of `dd` (`if=`): its source is copied by effect (§C52's secret
# leg). Same shape and bound as the output arm above.
_DD_IF_RE = re.compile(_CMD_POS + r"\bdd\b(?!=)[^|;&\n]{0,512}?\bif=([^\s|;&]+)")
# \b(?!=) on these two as well: `cp`/`mv`/`install`/`tar` are valid shell var
# names, so a `cp=…`/`tar=…` assignment whose value contains `-t <path>` /
# `-C <path>` / `--target-directory=` / `--directory=` text false-matched the
# bare `\bVERB\b` and read that path as a target-directory write. Same class,
# same guard as the sibling verbs above (exclude `=`, not a quoted real command).
# `-t DIR` / `--target-directory DIR` on cp, mv and install is read by
# `_target_directory_value` on the tokenizer's option view -- NOT by a regex of
# its own. There was one (`_CP_MV_INSTALL_TARGET_DIR_RE`, `-t\s+` or the full
# long spelling followed by `=`), and once the token-view predicate learned GNU's
# abbreviations the two disagreed: a QUOTED flag (`cp "--targ" <hooks>/ a`)
# tripped the skip and matched no regex, so nothing read the destination; the
# glued `-tDIR` matched neither. One concept, two matchers is the drift this
# module's single-source rule exists to prevent (a later review pass).
_TARGET_DIRECTORY_LONG = "--target-directory"
#: Short options of cp / mv / install that REQUIRE A VALUE: cp/mv `-S SUFFIX`,
#: install `-g GROUP -m MODE -o OWNER -S SUFFIX`. Inside a cluster the letters
#: after one of these are its value, not more flags (`-St` is a suffix `t`,
#: `-mt` a mode); as the LAST letter (`-S`, `-vS`) the value is the NEXT token,
#: whatever it looks like -- `cp -S -t a <hooks>/` has a suffix `-t` and the
#: zone path is its destination (a later review pass, driven: ten spellings
#: read the suffix as the target flag and lost the destination). cp's `-Z`
#: takes no value (the optional form is long-only).
_VALUE_SHORT_OPTIONS = frozenset("Sgmo")
#: Long options of cp / mv / install with a REQUIRED value (getopt_long
#: `required_argument`), so `--suffix -t` binds the next token: matched by
#: unambiguous prefix like the target-directory rule. `--backup`, `--reflink`,
#: `--preserve` and `--context` take an OPTIONAL value, which getopt_long binds
#: only when glued with `=` -- so `cp --backup -t a <hook>` really names `a` as
#: the target directory and must NOT consume a token.
_VALUE_LONG_OPTIONS = (
    "--suffix", "--sparse", "--no-preserve", "--mode", "--group", "--owner",
    "--strip-program",
)
#: An exact long option wins over a prefix of a value-taking sibling: install's
#: `--strip` takes no value and is not `--strip-program`. ⚠ Precision, not
#: safety: every SHORTER abbreviation of a no-value option that prefixes a
#: roster member (`--st`/`--str`/`--stri` for cp's `--strip-trailing-slashes`,
#: `--o` for cp's `--one-file-system`) collides the same way, and a later
#: review pass drove six of them eating the `-t`. The rosters cannot be made
#: complete by hand, so `_target_directory_readings` reads a span BOTH ways and
#: reports a disagreement instead of resolving it.
_NO_VALUE_LONG_EXACT = frozenset({"--strip"})
#: Short options KNOWN to take no value, per verb, on GNU and BSD alike (a
#: letter one platform gives a value -- install's `-S` is a suffix on GNU and a
#: safe-copy switch on BSD, `-D` a directory on BSD and a switch on GNU -- is
#: left OUT; a letter one platform rejects outright is harmless to list). This
#: is the roster that makes the readings safe: a flag standing immediately
#: before the target flag that is NOT known valueless might have taken `-t` as
#: its value (BSD `install -B -t a <hooks>/`: suffix `-t`, and the zone path is
#: the destination -- a later review pass, nine driven, where both readings
#: agreed on `a` and agreement silenced the pick). Such a span is AMBIGUOUS and
#: the pick runs too. An incomplete roster here costs a denied read; an
#: incomplete VALUE roster never costs a missed write.
_CP_MV_VALUELESS_SHORT = frozenset("abcdfHhiLlNnPpRrsTuvXxZ")
_INSTALL_VALUELESS_SHORT = frozenset("bcCdpsUv")
#: Long options known to take no separated value (exact spellings; an
#: abbreviation is unknown and therefore ambiguous). Optional-value options
#: belong here: getopt_long binds their value only when glued with `=`.
_VALUELESS_LONG_EXACT = frozenset({
    "--archive", "--attributes-only", "--backup", "--compare", "--context",
    "--copy-contents", "--debug", "--dereference", "--directory", "--force",
    "--help", "--interactive", "--link", "--no-clobber", "--no-copy",
    "--no-dereference", "--no-target-directory", "--one-file-system", "--parents",
    "--preserve", "--preserve-context", "--preserve-timestamps", "--recursive",
    "--reflink", "--remove-destination", "--strip", "--strip-trailing-slashes",
    "--symbolic-link", "--update", "--verbose", "--version",
})


def _did_not_take_the_next_token(tok: str, valueless_short: frozenset[str]) -> bool:
    """True when the flag ``tok`` certainly did NOT take the next token as its
    value: a glued `=VALUE` or an exact valueless long option; a short cluster
    whose letters are all known valueless, or whose first value-taking letter
    has its value glued on (`-Sv` is a suffix `v`, self-contained). A cluster
    ENDING in a value-taking letter took the next token; an unknown letter may
    have -- both are False, and False means ambiguous."""
    if tok.startswith("--"):
        return "=" in tok or tok in _VALUELESS_LONG_EXACT
    body = tok[1:]
    for position, letter in enumerate(body):
        if letter in _VALUE_SHORT_OPTIONS:
            return position < len(body) - 1
        if letter not in valueless_short:
            return False
    return True


def _certainly_takes_separated_value(tok: str) -> bool:
    """`_takes_separated_value` restricted to the CERTAIN spellings: a short
    cluster ending in a value-taking letter, or an EXACT value-taking long
    option. A long abbreviation may be a no-value option's (`--st`), so a token
    it swallowed is not trusted as a value by `_target_directory_readings`."""
    if tok.startswith("--"):
        return tok in _VALUE_LONG_OPTIONS
    return _takes_separated_value(tok)


def _takes_separated_value(tok: str) -> bool:
    """True when ``tok`` is a flag whose REQUIRED value is the next token: a
    short cluster whose LAST letter is value-taking (`-S`, `-vS`; `-St` has
    already glued its value), or a value-taking long option with no `=`."""
    if tok.startswith("--"):
        if "=" in tok or tok in _NO_VALUE_LONG_EXACT or len(tok) < 3:
            return False
        return any(name.startswith(tok) for name in _VALUE_LONG_OPTIONS)
    body = tok[1:]
    for position, letter in enumerate(body):
        if letter in _VALUE_SHORT_OPTIONS:
            # By POSITION, as `_did_not_take_the_next_token` compares: `-SS` is a
            # glued suffix `S`, and comparing the CHARACTER read it as separated
            # (the final review pass, a denied read). ⚠ Reconcile the twins in
            # this direction only -- a character-based twin would fail OPEN.
            return position == len(body) - 1
    return False


def _is_target_directory_long(tok: str) -> bool:
    """Any unambiguous GNU abbreviation of `--target-directory`, with or without
    a glued `=VALUE` -- getopt_long accepts every unambiguous prefix, and
    `--target-directory` is the only `--t…` option cp, mv and install define
    (`--no-target-directory` sorts under `--n`). `--t` is the shortest."""
    name = tok.split("=", 1)[0]
    return len(name) >= 3 and name.startswith("--t") and _TARGET_DIRECTORY_LONG.startswith(name)


def _target_directory_value(args: str, *, consume_values: bool = True) -> str | None:
    """ONE reading of the DIR; `_target_directory_readings` is what a consumer
    calls. See `_target_directory_walk`."""
    return _target_directory_walk(_operands(args), consume_values)[0]


def _target_directory_walk(
    tokens: list[str], consume_values: bool,
) -> tuple[str | None, int, frozenset[int]]:
    """ONE reading of the DIR a cp / mv / install invocation names as its target
    directory, with the index of the flag token that named it (None, -1 when no
    flag does) and the indices of the tokens CERTAINLY swallowed as a flag's
    value (`_certainly_takes_separated_value`). With ``consume_values`` a flag that requires a separated value
    swallows the next token first (`-S -t a` has a suffix `-t`); without it,
    nothing is swallowed (`--st -t d/` abbreviates a no-value option). The DIR:
    `-t DIR`, glued `-tDIR`, a cluster ending in or continuing past `t`
    (`-vt DIR`, `-vtDIR`; a value-taking letter before `t` makes the rest a
    value, so `-St` is a suffix), and `--target-directory` in any GNU
    abbreviation, `=` or space bound. Read from the same token stream the
    positional view reads -- quotes already stripped, `--` ending the options --
    so a quoted flag cannot trip one reader and miss another, and a file named
    `-t` after `--` is a file. A flag that REQUIRES a separated value
    (`_takes_separated_value`) consumes the next token first, so a suffix,
    mode, owner or group literally `-t` is a value, not this flag. With DIR
    present every positional is a SOURCE and DIR is the one destination (each
    source lands `DIR/basename`)."""
    swallowed: set[int] = set()
    i = 0
    while i < len(tokens):
        at = i
        tok = tokens[i]
        i += 1
        if tok == "--":
            return None, -1, frozenset(swallowed)
        if not tok.startswith("-") or tok == "-":
            continue
        if consume_values and _takes_separated_value(tok):
            if _certainly_takes_separated_value(tok):
                swallowed.add(i)
            i += 1                                     # its value, whatever it looks like
            continue
        following = tokens[i] if i < len(tokens) and tokens[i] != "--" else None
        if tok.startswith("--"):
            if _is_target_directory_long(tok):
                return (tok.split("=", 1)[1] if "=" in tok else following), at, frozenset(swallowed)
            continue
        body = tok[1:]
        for position, letter in enumerate(body):
            if letter in _VALUE_SHORT_OPTIONS:
                break                              # the rest is that flag's value
            if letter == "t":
                rest = body[position + 1:]
                return (rest if rest else following), at, frozenset(swallowed)
    return None, -1, frozenset(swallowed)
_TAR_C_RE = re.compile(
    _CMD_POS + r"\btar\b(?!=)[^|;&\n]{0,512}?(?:-C[ \t]+|--directory=)([^\s|;&]+)"
)
# A tar CREATE's inputs (§C52's secret leg): the argument span, read by
# `_tar_create_inputs`, which walks the option clusters (`-cf out.tar`,
# `czf out.tgz`, `--create --file=out.tar`, `-c -f out.tar`) and returns
# the positionals that are neither the archive nor a flag's value. One
# bounded quantifier: linear.
_TAR_CREATE_RE = re.compile(
    _CMD_POS + r"\btar\b(?!=)" + _QUOTED_VERB_TAIL + r"[ \t]+([^|;&\n]{0,512})"
)
# For verbs where the protected target is the final positional and
# flags may take separate arguments (`-s 0`) or glued ones (`-p1`),
# capture the verb's arg span and pick the last non-flag token in
# Python. The regex form `(?:-\S+(?:\s+\S+)?\s+)*` doesn't handle
# long flags or glued short flags consistently.
# \b(?!=): exclude a `install=…`/`rsync=…`/… shell assignment (`=` is a word
# boundary a bare `\bVERB\b` false-matched, reading a path in the value as the
# write target), but NOT a quoted `'install' …` real command. Capture unchanged.
# A same-line comment is cut from every argument span below -- and from the
# sed/perl segment in `_INPLACE_SEGMENT_RE` and the permission span -- by
# `_strip_span_tail` before tokenising: the classes read past a comment, and
# neither the inert-syntax mask nor the head roster blanks a comment's WORD
# content, so `install x README.md # tools/cc/hooks/write_guard.py` handed the
# comment's last word to `_last_non_flag_token` and denied an ordinary command
# (driven by the DEF-638 code-reviewer on `sed -i`; DEF-693, fixed as the class).
# ⚠ The first fix excluded `#` from these classes, and that was a fail-OPEN at
# every site: a `#` opens a comment only at a word start (`_opens_comment`; real
# bash: `echo file#1 realarg` prints both words), so `install -m 644 file#1
# <hook>` cut the span at `file` and dropped the hook (code-reviewer, driven
# old-vs-new at all five verbs). The classes stay `#`-blind so a `#` inside a
# filename survives; the scanner cuts at a word-start `#` outside quotes.
_INSTALL_CMD_RE = re.compile(_CMD_POS + r"\binstall\b(?!=)([^|;&\n]+)")
_RSYNC_CMD_RE = re.compile(_CMD_POS + r"\brsync\b(?!=)([^|;&\n]+)")
_TRUNCATE_CMD_RE = re.compile(_CMD_POS + r"\btruncate\b(?!=)([^|;&\n]+)")
# `patch [opts] [originalfile [patchfile]]`: the WRITE target is the FIRST
# positional and the last is the patchfile READ, so the last-token pick the three
# verbs above share read `patch <hook> p.diff` as a write to `p.diff` and allowed
# it (driven at HEAD by the DEF-693 review's own row). Every positional is a
# candidate for patch, with a glued `--output=`/`--directory=` value
# (`_patch_targets`): a patchfile named like a protected path is friction, a
# missed originalfile is an unchecked write.
_PATCH_CMD_RE = re.compile(_CMD_POS + r"\bpatch\b(?!=)([^|;&\n<]+)")
# `find <roots...> ... -delete` and `-exec rm {} \;` (§C52): the roots are
# the leading positionals before the first predicate; `_find_delete_roots`
# yields them only when a delete action sits in the span. Bounded like the
# sibling spans; the action test is a second, anchored pass over the span.
# IGNORECASE on the verb (DEF-815's review): `FIND` runs on the two
# case-insensitive platforms this harness supports, as `RM` does and
# `_RM_SEGMENT_RE` admits; the predicates below stay case-sensitive, since
# find itself rejects `-DELETE`.
_FIND_DELETE_RE = re.compile(
    _CMD_POS + r"\bfind\b(?!=)" + _QUOTED_VERB_TAIL + r"[ \t]+([^|;&\n]{0,512})",
    re.IGNORECASE,
)
#: The remove verb behind `-exec`, spelled as the rm arm's tokenizer admits
#: it (DEF-815's review): behind a wrapper word, a directory prefix, a
#: leading backslash or a quote -- `-exec /bin/rm`, `-exec env rm`, `-exec
#: \rm` and `-exec 'rm'` all run rm. The wrapper run is bounded, the prefix
#: run is on the bounded separator class and must end in `/`.
_FIND_EXEC_VERB = (
    r"(?:(?:env|sudo|command|nice|nohup|busybox|doas)[ \t]+){0,3}"
    r"""["']?\\?(?:[^\s;|&"']*/)?(?:rm|unlink|rmdir|shred|mv)\b"""
)
_FIND_DELETE_ACTION_RE = re.compile(
    r"(?<![\w-])-delete\b|(?<![\w-])-(?:exec|execdir|ok|okdir)[ \t]+" + _FIND_EXEC_VERB
)
#: A predicate that NARROWS what a `find` removes BY NAME OR PATH: with one
#: in force the root is a starting point, not the operand (`find . -name
#: '*.pyc' -delete` from the repo root is an everyday command and takes no
#: protected file); the consumer then asks only whether the root itself is
#: protected. `_find_is_narrowed` decides whether one is in force: find
#: evaluates its expression left to right, so a predicate AFTER the action
#: steers nothing (`find . -delete -name zzz` deletes everything first), a
#: negated one (`! -name zzz`, `-not -name zzz`) selects nearly everything,
#: and an `-o` whose right operand is not itself a narrowing predicate
#: re-widens the walk (`-name zzz -o -delete`); a grouped alternation of
#: names (`\( -name a -o -name b \)`) still narrows. NOT in the set
#: (DEF-815 and its review): `-type` (`-type f` from the root takes every
#: hook file; `-type d` alone removes only empty directories) and the
#: attribute predicates (`-size`, `-perm`, `-mtime`, `-user`, `-links`,
#: `-newer`, ...), each of which a hook file satisfies -- every one of them
#: was a one-token exit from the catastrophic wall in the first cut. An
#: un-narrowed root reaches the catastrophic tier
#: (`has_catastrophic_find_delete`) as an rm operand reaches its classifier.
_FIND_NARROWING_RE = re.compile(
    r"(?<![\w-])-i?(?:name|path|regex|wholename|lname|samefile|inum|empty|prune)\b"
)
#: `-o` / `-or` and the token after it, the alternation's right operand.
_FIND_OR_RE = re.compile(r"(?<![\w-])-or?[ \t]+([^\s;|&]+)")
#: A negation directly before a predicate (`! -name`, `-not -name`), or an
#: `-o` with nothing after it inside the slice (its right operand is the
#: action itself): applied to the text BEFORE the predicate or the action.
_FIND_NEGATED_RE = re.compile(r"(?:(?<![\w-])-not|!)[ \t]*$")
_FIND_OR_AT_END_RE = re.compile(r"(?<![\w-])-or?[ \t]*$")
#: GNU `find`'s global options, which sit BEFORE the starting points.
_FIND_GLOBAL_OPTIONS = frozenset({"-H", "-L", "-P"})


#: A name-or-path VALUE that selects everything (`-name '*'`, `-path '*'`,
#: `-regex '.*'`): the predicate is present and narrows nothing, and the
#: first cut read presence -- the failure-mode review drove `find . -name
#: '*' -delete` to a wipe with no tier fired. One class with the PowerShell
#: twin `_PS_ENUM_CATCHALL_FILTER`.
_FIND_CATCHALL_VALUES = frozenset({"*", "**", "*/*", "*.*"})
_FIND_REGEX_CATCHALL_VALUES = frozenset({".*", ".+", ".*/.*", "^.*$"})
_FIND_VALUED_NARROWING = ("name", "path", "wholename", "lname", "regex")


# ── git's head: the verb and its global-option run (ONE home) ────────────────
# Placed here, before the carrier, because the version-control listing head
# composes on it (DEF-831); the git subcommand arms further down read it too.
#: The git verb: `git`, or `git.exe` under Git Bash and behind the PowerShell
#: call operator (DEF-791) -- ONE home for the three checkout/restore arms,
#: `_GIT_HEAD_RE`, the listing head above the carrier, and `_speedbump`'s
#: `_GIT_CMD` / `_PS_GIT_CMD` (failure-mode review: the extension had been
#: admitted on one arm of five).
_GIT_VERB = r"git(?:\.exe)?"
#: git's global options, which may sit BETWEEN `git` and the subcommand
#: (`git -C <dir> checkout`, `git -c k=v restore`, `git --no-pager rm`,
#: `git --git-dir=<d> clean`): a spelling Claude emits routinely when it
#: wants to be explicit about the repo, and one that defeated every git arm
#: in this module and the discard bump until DEF-814's review (driven
#: 2026-09-15: `git -C . checkout -- <hook>` extracted nothing on either
#: shell and drew no nudge). ONE home, moved from `_speedbump` (which
#: carried it for `push` and `clean` alone -- the one-arm-of-five shape
#: `_GIT_VERB` moved for): an arg-taking option consumes the following
#: token, a bare flag does not; every arm starts with `-` (prefix-disjoint),
#: the value runs are on the bounded separator class (rule 2 of the module:
#: never `\S` for a token run), and the run is bounded at eight
#: (`_GIT_PREOPT_RUN`) so a repeated head stays linear. A value is bare or
#: quoted in either kind (DEF-831: the row probe drove `-C "<a root with a
#: blank>"` to no tier on every git arm, since the bare class stops at the
#: blank); the three value arms are disjoint on their first character.
_GIT_PREOPT_VALUE = r"""(?:"[^"\n]*"|'[^'\n]*'|[^\s;|&"'][^\s;|&]*)"""
_GIT_PREOPT = (
    r"(?:"
    r"-[Cc][ \t]+" + _GIT_PREOPT_VALUE                          # -C <path>, -c <name=value>
    + r"|--(?:git-dir|work-tree|namespace|exec-path|super-prefix)(?:=|[ \t]+)" + _GIT_PREOPT_VALUE
    + r"|--(?:no-pager|paginate|bare|literal-pathspecs|glob-pathspecs"
    r"|noglob-pathspecs|icase-pathspecs|no-replace-objects|no-optional-locks)"
    r"|-[pP]"
    r")[ \t]+"
)
_GIT_PREOPT_RUN = "(?:" + _GIT_PREOPT + "){0,8}"
#: The head every git subcommand arm composes, on either shell's command
#: position: the verb (quoted or bare), a blank, the global-option run. The
#: subcommand word follows directly.
_GIT_SUBCOMMAND_AT = _GIT_VERB + _QUOTED_VERB_TAIL + r"[ \t]+" + _GIT_PREOPT_RUN


# ── the enumerator piped through xargs into a remove verb (DEF-826) ──────────
# `find . -print0 | xargs -0 rm -rf`, `find . | xargs rm -rf`, `ls | xargs rm
# -rf`, `ls -R | xargs rm -rf`, `find . -type f | xargs rm`: the whole-tree
# wipe with its operands arriving on stdin, the single most-typed spelling of
# one in agent-authored shell. Until 2026-09-16 no tier saw it on either
# tool: the find arm needs a delete action and this find carries none, the
# remove verb behind the carrier has no operand for the zone check or the
# rm tiers to read, and the speed bump had nothing to bump (driven on fresh
# throwaways under /bin/bash and pwsh 7.6.5: every spelling left the root
# standing and empty). The reading is the PowerShell tool's (DEF-822): the
# ENUMERATOR's roots are the remove verb's operands, judged through the
# same three tiers. A stage between the enumerator and the carrier
# (`find . | grep x | xargs rm`) is a declared limit; the loop carrier (the
# enumerator's output bound to a loop variable and removed in the body) is
# read by its own openers below (DEF-830); a single stdin path (`echo one |
# xargs rm`) is the zone class's, honest for one path.
#: The enumerator heads, ONE home (DEF-831): ``(key, spelling)`` for every
#: head the carrier reads. Both openers' head groups, the dispatch table
#: (`_PIPED_ENUM_HEAD_READERS`, checked against the keys at import) and the
#: roster test derive from this tuple, so a head added here without a
#: roots reader refuses at import and a reader with no head is unreachable
#: by construction (the failure-mode review drove a fourth roster word to
#: the `ls` branch's grammar with every gate green). `find` is a walk
#: (recursive by default, roots before the first predicate, `.` when none);
#: `ls` a listing (`-R` walks); the version-control listing (`git
#: ls-files`) walks the index whole under the current location, files only,
#: and composes on the git head's one home (`_GIT_SUBCOMMAND_AT`, defined
#: above for that reason) so a global option before the subcommand (`git -C
#: . ls-files`, the explicit spelling an agent emits -- the tracked-files
#: listing piped through the carrier reached on both tools and drew no tier
#: until this row) is read. A one-word key is a roster word the
#: assignment-prefix scrape derives (the roster sits behind one guard in
#: the Bash opener); a key with a blank is a spelling behind a guard of its
#: own. `_enum_head_key` maps a matched head text to its key.
#: Case-insensitive on the verb as `_FIND_DELETE_RE` is.
#: UNCLAIMED heads, not declared limits (a declared limit earns a row;
#: these earn a ledger line the day one shows up in agent-authored shell):
#: a search tool's file-list modes, a filesystem-usage walk, a tree
#: printer, a locate query, a list read from a file (the loop fed from a
#: file, `done < list.txt`, is this one too: the list is not an
#: enumerator's). The loop carrier over these heads is read (DEF-830).
_PIPED_ENUM_HEAD_SPELLINGS: tuple[tuple[str, str], ...] = (
    ("find", r"find"),
    ("ls", r"ls"),
    ("git ls-files", _GIT_SUBCOMMAND_AT + r"ls-files"),
)
_PIPED_ENUM_HEAD_KEYS: tuple[str, ...] = tuple(k for k, _ in _PIPED_ENUM_HEAD_SPELLINGS)
#: The one-word roster (the scrape's) and the multi-word spellings, composed
#: into both openers' head groups. Spelled as literal concatenations, not
#: joined from the table: the dot-star gate reconstructs every compiled
#: pattern statically from module-level literals and names, and a join over
#: the table is a call it cannot read (the tier drove both openers to
#: "un-reconstructable"). The check below refuses at import when either
#: literal and the table disagree, so the table stays the one home.
_PIPED_ENUM_HEADS = r"find|ls"
_PIPED_MULTIWORD_HEADS = _GIT_SUBCOMMAND_AT + r"ls-files"
if (_PIPED_ENUM_HEADS != "|".join(s for k, s in _PIPED_ENUM_HEAD_SPELLINGS if " " not in k)
        or _PIPED_MULTIWORD_HEADS != "|".join(s for k, s in _PIPED_ENUM_HEAD_SPELLINGS if " " in k)):
    raise RuntimeError("enumerator head roster drift: the head table and the openers' spellings disagree")
#: Every head spelling as one alternation: the roster test's spelling
#: oracle. The openers cannot use it as is -- each composes its head group
#: per alternative, the roster behind one assignment guard and each
#: multi-word spelling behind its own, so the scrape keeps deriving the
#: roster words.
_PIPED_ENUM_VERB = r"(?:" + _PIPED_ENUM_HEADS + r"|" + _PIPED_MULTIWORD_HEADS + r")"
_PIPED_ENUM_HEAD_GROUP = (
    r"(?P<head>(?:" + _PIPED_ENUM_HEADS + r")\b(?!=)|" + _PIPED_MULTIWORD_HEADS + r"\b(?!=))"
)


def _sweep_is_wipe(recursive: bool, files_only: bool, walks: bool, native: bool) -> bool:
    """ONE rule for what an enumerator pipeline takes, on both tools: every
    file under the root when the remove verb recurses, when the enumeration
    is files-only, or when the walk recurses INTO A NATIVE remove verb --
    `/bin/rm` takes every file a walk hands it (driven), where a cmdlet fed
    the same walk prompts on a directory with children and aborts. The hard
    tier walls a wipe from a catastrophic root; the soft tier nudges every
    un-narrowed sweep, wipe or not. `native` is always True on the Bash tool
    and, on the PowerShell tool, True behind the carrier (DEF-826)."""
    return recursive or files_only or (walks and native)
#: The carrier's switch run: every switch token is ONE arm. A VALUED switch
#: spelled alone (`-n`, `-I`, `-P`, `-d`, `-s`, `-L`, `-E`, `-a`, or its long
#: form) takes the next token as its value -- one that is not a switch, a
#: wrapper word or the remove verb; every other token (`-0`, `-r`, `-0r`,
#: `-n1`, `-I{}`, `--null`, `--max-args=1`, a glued count) takes none, so
#: `xargs -n1 echo rm` keeps `echo` as the command. The generic arm excludes
#: exactly the bare valued spellings, so each token has one parse (the rule
#: `_CMD_POS_WRAP_RUN` learned).
#: `J` is BSD xargs's placeholder switch, the direct twin of GNU's `-I` and
#: the one macOS ships (the code review drove its spelling to no tier at all
#: on the self-host Darwin box: its placeholder became a phantom operand and
#: the opener never reached the remove verb).
_XARGS_VALUED = r"(?:[nIJPdsLEa]|-(?:max-args|replace|max-procs|delimiter|max-chars|max-lines|eof|arg-file))"
_XARGS_VALUE = (
    r"[ \t]+(?!-)(?!(?:env|sudo|command|nice|nohup|busybox|doas)\b)"
    r"(?!(?:rm|unlink|rmdir|shred|mv)\b)[^\s;|&-][^\s;|&]*"
)
_XARGS_SWITCH_RUN = (
    r"(?:[ \t]+(?:-" + _XARGS_VALUED + r"(?![^\s;|&])(?:" + _XARGS_VALUE + r")?"
    r"|-(?!" + _XARGS_VALUED + r"(?![^\s;|&]))[^\s;|&]+))*"
)
#: The post-pipe half of the carrier: the pipe, an optional wrapper run,
#: `xargs` with its switches, up to the remove verb. ONE definition, shared
#: by the pipeline carrier below and by the loop body's carrier-fed arm
#: (DEF-836, `_LOOP_FEED_PREFIX`) -- a near-copy in the second place would be
#: a regression against a calibrated pattern that nothing would red.
_XARGS_CARRIER_TAIL = (
    r"\|[ \t]*(?:" + _CMD_POS_WRAP_RUN + r")?"
    r"\bxargs\b(?!=)" + _XARGS_SWITCH_RUN + r"[ \t]+"
)
#: Enumerator, one pipe ON THE LINE (bash continues a pipeline after a line
#: break, but a Bash-tool joiner never crosses a newline -- the statement
#: census's rule, since the chain splits there; the line-break spelling is a
#: declared limit, pinned as an allow row, and the PowerShell twin reads it
#: under its own census), an optional
#: wrapper run, `xargs` with its switches, the remove verb as `-exec` admits
#: it (`_FIND_EXEC_VERB`: behind a wrapper word, a directory prefix, a
#: backslash or a quote), and the verb's own span (its cluster read by the rm
#: tier's tokenizer; a `{}` placeholder there is not an operand). Two bounded
#: spans; the narrowing test on the enumerator span is `_bash_pipeline_roots`.
_PIPED_REMOVE_RE = re.compile(
    _CMD_POS + _PIPED_ENUM_HEAD_GROUP + _QUOTED_VERB_TAIL
    + r"(?P<args>[^\n;|&]{0,512})" + _XARGS_CARRIER_TAIL
    + r"(?P<verb>" + _FIND_EXEC_VERB + r")(?P<rmargs>[^\n;|&]{0,200})",
    re.IGNORECASE,
)
#: The cheapest witness of the carrier for the pre-check both tiers run
#: before any walk (a GATE, as `_PS_SWEEP_WITNESS_RE` is; the anchored
#: opener above selects the operands).
_PIPED_CARRIER_WITNESS = (
    r"\|[ \t\r\n]*(?:(?:env|sudo|doas|command|nice|nohup|time|timeout)[ \t]+)*\bxargs\b"
)
_PIPED_CARRIER_WITNESS_RE = re.compile(_PIPED_CARRIER_WITNESS, re.IGNORECASE)
#: ── The loop carrier (DEF-830) ───────────────────────────────────────────
#: The enumerator's output bound to a loop variable and removed in the body
#: is the carrier wipe spelled as a compound statement, which no pipeline
#: reader sees: the remove verb's operand is the variable, not the stdin,
#: so from a catastrophic root the hard tier answered nothing and the soft
#: tier answered with its variable-operand nudge (driven at the hook when
#: the row was filed). Four heads, each an opener on its own command
#: position. Three compose the enumerator head group (so the head keeps its
#: offset for placement and its spelling for the roots reader): the pipe
#: into a read loop, the for loop over a command substitution (either
#: spelling), the read loop fed at its tail by a process substitution or a
#: here-string of a substitution. The fourth (DEF-837) has no enumerator at
#: all: the for loop over a bare WORD LIST, whose roots are the list's words,
#: each the rm tier's own operand -- so `for f in *` meets the verdict
#: `rm -rf *` meets and `for f in build/*` stays the soft tier's, the OPERAND
#: deciding and never the loop shape. The body is read on the RAW text at the
#: match's offsets, the verb's cluster by the rm tier's tokenizer
#: (`_bash_loop_reading`); the operand that expands the loop variable is the
#: carrier's placeholder, as `{}` is behind xargs, and its siblings are
#: removed as spelled. The keywords are matched in lower case only -- bash
#: reserves them so, and a mis-cased keyword is a command bash cannot run --
#: and only where bash reserves them: `do` and `done` behind a separator.
#: Declared limits, each pinned as a row: a stage between the enumerator and
#: the loop, the pipe on the line after the enumerator (the joiner never
#: crosses a newline), a loop fed from a file (`done < list.txt`: the list is
#: not an enumerator's), a word list beside a command substitution (read by
#: neither head, so a catastrophic word beside one draws the variable
#: operand's nudge where its direct twin walls), and the PowerShell
#: statement-form loop (asked at the hook: the remove cmdlet's wall already).
#: Behind the carrier-fed body, a stage between and a word list beside a
#: substitution draw NOTHING -- silent allows, declared with their ledger row
#: rather than hidden behind "each draws the nudge".
#: The read builtin's switch run, one arm per token as the carrier's is: a
#: token whose LAST letter is a valued switch (`-d`, `-n`, `-N`, `-t`, `-u`,
#: `-p`, `-a`, `-i` -- alone or glued behind others, `-rd`) takes one value
#: (a quoted or bare word; the empty quotes of `-d ''` and the ANSI-C `$'\0'`
#: included); a token whose last letter is not valued takes none; a long
#: option takes none. Each token has one parse: the three arms are told
#: apart by their last letter or their second dash.
_READ_VALUED = r"[dnNtupai]"
_READ_VALUE = r"""(?:'[^'\n]{0,64}'|"[^"\n]{0,64}"|\$'[^'\n]{0,64}'|[^\s;|&'"$-][^\s;|&]{0,63})"""
_READ_SWITCH_RUN = (
    r"(?:[ \t]+-(?:[A-Za-z]*" + _READ_VALUED + r"(?![^\s;|&])(?:[ \t]+" + _READ_VALUE + r")?"
    r"|[A-Za-z]*(?<!" + _READ_VALUED + r")(?![^\s;|&])"
    r"|-[a-z-]{1,32}(?![^\s;|&])))*"
)
#: A name the loop binds; the read head's run of them (the last takes the
#: rest of the line, the body may name any) or, with none, `REPLY`.
_LOOP_VAR = r"[A-Za-z_][A-Za-z0-9_]{0,63}"
_WHILE_READ_HEAD = (
    r"(?-i:while)[ \t]+(?:IFS=[^\s;|&]{0,32}[ \t]+)?(?:builtin[ \t]+)?(?-i:read)\b(?!=)"
    + _READ_SWITCH_RUN
    + r"(?:[ \t]+(?P<vars>" + _LOOP_VAR + r"(?:[ \t]+" + _LOOP_VAR + r"){0,4}))?"
)
#: A statement separator bash reserves a keyword behind.
_LOOP_SEP = r"(?:;|\n|&&|\|\|)"
#: The body: the separator bash requires before `do`, the keyword, up to
#: four statements that are not the remove (a bounded run, each opening on a
#: non-blank so it shares no input with the whitespace before it, and never
#: on the remove verb or on the closer -- the code review drove a later
#: removal past the closer into the verb group, where the loop's own remove
#: had been consumed as a statement and the carrier dropped as "not the
#: carrier"), an optional `then` or `else` for the guarded body, the remove
#: verb as `-exec` admits it, and its own span.
_LOOP_BODY_STATEMENT = (
    r"(?!" + _FIND_EXEC_VERB + r")(?!(?-i:done)\b)[^\s;|&][^\n;|&]{0,199}" + _LOOP_SEP + r"[ \t\n]{0,64}"
)
#: The body's CARRIER-FED remove (DEF-836): the item emitted and piped into
#: the carrier inside the loop body -- `do echo "$f" | xargs rm -rf; done`.
#: Until 2026-09-18 this was a SILENT ALLOW, and it is the composition of two
#: honest limits rather than a hole in either: the body's statement run and
#: its `rmargs` span both stop at a pipe and `_LOOP_SEP` reserves no bare
#: one, so no loop reader matched at all; the pipeline carrier then saw a
#: single stdin path, which is its own declared limit (DEF-826). The same
#: wipe spelled WITHOUT the loop (`find . | xargs rm -rf`) is the wall, so
#: the loop shape was deciding the verdict where the OPERAND should.
#:
#: Written as an OPTIONAL PREFIX on the body's remove rather than a second
#: branch, so the verb and its span keep ONE group set (two branches cannot
#: both name `verb`/`rmargs`) and the consumer tells the arms apart by
#: whether `feed` participated. The post-pipe half is the pipeline carrier's
#: own fragment, lifted to `_XARGS_CARRIER_TAIL` and shared -- a near-copy
#: here would be a regression against a calibrated pattern that nothing
#: would red (`memory/derive-a-guard-from-its-calibrated-sibling.md`).
#:
#: `feed` is captured as a bare word and resolved by `_loop_variable_named`,
#: the same helper the direct arm's operands go through, so the variable's
#: spellings (bare, braced, double-quoted) have ONE definition.
#: Each bounded run opens on a non-blank so it shares no input with the
#: whitespace before it -- the adjacent-quantifier rule the ReDoS receipt
#: states and `_LOOP_BODY_STATEMENT` already follows.
_LOOP_EMIT_ARGS = r"(?:[ \t]+[^\s;|&]{1,64}){0,3}"
_LOOP_FEED_PREFIX = (
    r"(?:(?-i:echo|printf)" + _LOOP_EMIT_ARGS
    + r"[ \t]+(?P<feed>[^\s;|&]{1,80})[ \t]*" + _XARGS_CARRIER_TAIL + r")?"
)
_DO_BODY = (
    r"[ \t]*(?:;|\n)[ \t\n]{0,64}(?-i:do)(?=\s)[ \t\n]{0,64}"
    r"(?:" + _LOOP_BODY_STATEMENT + r"){0,4}"
    r"(?:(?-i:then|else)[ \t\n]{1,64})?"
    + _LOOP_FEED_PREFIX
    + r"(?P<verb>" + _FIND_EXEC_VERB + r")(?P<rmargs>[^\n;|&]{0,200})"
)
#: (1) the enumerator piped into the read loop, the pipe ON THE LINE as the
#: carrier's is.
_LOOP_REMOVE_RE = re.compile(
    _CMD_POS + _PIPED_ENUM_HEAD_GROUP + _QUOTED_VERB_TAIL
    + r"(?P<args>[^\n;|&]{0,512})\|[ \t]*" + _WHILE_READ_HEAD + _DO_BODY,
    re.IGNORECASE,
)
#: The enumerator span inside a substitution: up to its close, an escaped
#: paren (find's grouping) and a quoted word (a root with a paren in it,
#: the row probe's shaped root) carried whole; the four arms are told apart
#: by their first character.
_SUBST_ENUM_ARGS = (
    r"""(?P<args>(?:[^\n;|&`)\\"']|\\.|"[^"\n]{0,256}"|'[^'\n]{0,256}'){0,512})"""
)
#: (2) the for loop over a command substitution, either spelling, UNQUOTED
#: (a quoted substitution is one word, not a list).
_FOR_SUBST_REMOVE_RE = re.compile(
    _CMD_POS + r"(?-i:for)[ \t]+(?P<vars>" + _LOOP_VAR + r")[ \t]+(?-i:in)[ \t]+(?:\$\(|`)[ \t]*"
    + _PIPED_ENUM_HEAD_GROUP + _QUOTED_VERB_TAIL
    + _SUBST_ENUM_ARGS + r"(?:\)|`)" + _DO_BODY,
    re.IGNORECASE,
)
#: (3) the read loop fed at its tail: `done < <(find .)`, `done <<< "$(ls)"`;
#: up to four statements between the remove and `done`.
_TAIL_LOOP_REMOVE_RE = re.compile(
    _CMD_POS + _WHILE_READ_HEAD + _DO_BODY
    + _LOOP_SEP + r"[ \t\n]{0,64}(?:" + _LOOP_BODY_STATEMENT + r"){0,4}"
    + r"(?-i:done)[ \t]*(?:<[ \t]*<\(|<<<[ \t]*\"?\$\()[ \t]*"
    + _PIPED_ENUM_HEAD_GROUP + _QUOTED_VERB_TAIL
    + _SUBST_ENUM_ARGS + r"\)",
    re.IGNORECASE,
)
#: (4) the for loop over a bare WORD LIST (DEF-837): no enumerator, so the
#: roots are the list's words, read as the rm arm reads a plain remove's
#: operands and judged one per word by the rm tier's own rule
#: (`_bash_loop_reading`). `head` is the `for` keyword -- the statement's
#: offset, for placement -- and `args` the list: the two spans every compound
#: opener carries. One word, its arms told apart by the first character:
#: anything but a blank, a separator, a quote, a backslash, a backtick, a
#: dollar, a paren or a redirection; a dollar that opens no substitution
#: (`$d`, `${a[@]}`, `"$@"` -- an unknowable word, judged as its direct twin
#: judges it, which does not end the list); an escaped character; a
#: double-quoted segment holding no substitution; a single-quoted one. A
#: command substitution in ANY spelling fails every arm, so head (2) keeps
#: its own shape and a list beside a substitution is read by neither (a
#: declared limit, above). A word never holds a blank, so the words and the
#: blanks between them share no input.
#:
#: Every run is UNBOUNDED, with the receipt `_INTERP_SWITCH_RUN`'s note
#: demands. The first cut bounded them (64 words, 256 characters a word or a
#: quoted segment), and each bound was a cliff past which the WHOLE head
#: stopped matching: a 65th word, or one path longer than 256 characters (a
#: deep `node_modules` path is), turned the wall back into the bump and hid a
#: protected path from the zone check (the code review drove the first; the
#: other two are its siblings). The arms are disjoint by their first
#: character and the words are cut by mandatory blanks, so the run has one
#: parse: measured linear to 32 KB (the scan cap) on five flood shapes.
#: The bare arm stops at blanks and metacharacters named explicitly, never
#: the whitespace class -- a form feed is no word break to bash (the rule
#: `_BASH_BARE_SEGMENT` learned). Why not reuse that calibrated family
#: (`_BASH_QUOTED_WORD`): its word must OPEN on a quoted segment, its quoted
#: segment crosses a newline (the compound census requires this head's
#: operand spans to stop at their line), its bare `$` admits a command
#: substitution (which would read head 2's shape as a path), and it cuts at
#: a brace (`for f in {a,*}` is one word, its twin `rm -rf {a,*}` a wall).
_FOR_LIST_WORD = (
    r"""(?:[^ \t\n\r;|&`$\\"'()<>]|\$(?!\()|\\.|"""
    r'''"(?:[^"\n$`\\]|\$(?!\()|\\.)*"|'[^'\n]*')+'''
)
#: The same word, compiled to SPLIT the matched list, run on the SCAN span
#: that matched and read from the raw text at each word's offsets (the
#: match-on-scan, read-raw rule): the regex that parsed the list is the one
#: that cuts it, so a word is one bash word -- `"a b"` and `"$root"/*` each
#: stay whole. A whitespace split breaks the first; a quote-aware token
#: stream breaks the second into `$root` and `/*`, and the phantom `/*`
#: judged as the filesystem root walled a loop whose direct twin draws the
#: nudge (driven under every root shape, 2026-09-18). Cutting the RAW text
#: instead would re-open that the day the masker blanks a quoted span the
#: scan matched. A tokenizer, never run over a whole command.
_FOR_LIST_WORD_RE = re.compile(_FOR_LIST_WORD)
_FOR_WORDS_REMOVE_RE = re.compile(
    _CMD_POS + r"(?P<head>(?-i:for))[ \t]+(?P<vars>" + _LOOP_VAR + r")[ \t]+(?-i:in)"
    + r"(?P<args>(?:[ \t]+" + _FOR_LIST_WORD + r")+)" + _DO_BODY,
    re.IGNORECASE,
)
#: The loop carrier's openers and the roots shape each reads: ONE home for a
#: roster three sites share -- the reading (`_bash_loop_reading`), the zone
#: reader's unquote (`_extend_loop_operands`) and the sweep iterator's
#: wipes-only gate (`_iter_loop_sweeps`) -- which DEF-837's failure-mode
#: review found kept by hand in each. A lookup, not an identity test, so an
#: opener missing here raises instead of falling to the enumerator's reader.
#: The population is DERIVED in `tests/test_write_guard.py` (every pattern
#: whose source carries `_DO_BODY`), and the zone reader, which spells each
#: opener by name for the arm census, is pinned equal to it there.
_LOOP_OPENERS: tuple[tuple["re.Pattern[str]", str], ...] = (
    (_LOOP_REMOVE_RE, "enumerator"),
    (_FOR_SUBST_REMOVE_RE, "enumerator"),
    (_TAIL_LOOP_REMOVE_RE, "enumerator"),
    (_FOR_WORDS_REMOVE_RE, "words"),
)
_LOOP_OPENER_SHAPE: dict["re.Pattern[str]", str] = dict(_LOOP_OPENERS)
#: The cheapest witness of the loop carrier for the pre-check both tiers run
#: before any walk (a GATE, as `_PIPED_CARRIER_WITNESS_RE` is): the `do`
#: keyword where bash reserves it, behind a separator, at most two line
#: breaks away (so a flood of separators pays one bounded scan each).
_LOOP_CARRIER_WITNESS = r"(?:;|\n)[ \t]*(?:\n[ \t]*){0,2}do(?=\s)"
_LOOP_CARRIER_WITNESS_RE = re.compile(_LOOP_CARRIER_WITNESS)
#: ONE operand token that is exactly the expansion of a name -- bare,
#: braced, or double-quoted (a single-quoted one is a literal): the loop
#: variable's spelling in the body. `"$f"/sub` and `"$f".bak` name a path
#: beside the item and are not it.
_LOOP_OPERAND_RE = re.compile(
    r'^"?\$(?:\{(' + _LOOP_VAR + r')\}|(' + _LOOP_VAR + r'))"?$'
)
#: Inside an enumerator span the anchored opener selected: `-type f` (the
#: files-only walk, every file under the root) and ls's recursion flag.
_FIND_TYPE_F_RE = re.compile(r"(?<![\w-])-type[ \t]+f\b")
_LS_WALK_RE = re.compile(r"(?<![\w-])-[A-Za-z]*R[A-Za-z]*\b|(?<![\w-])--recursive\b")


def _find_predicate_value_is_catchall(before: str, word: str, at: int) -> bool:
    """True when the narrowing predicate ``word`` (`name`, `iname`, `regex`,
    ...) whose value starts at ``at`` in ``before`` selects everything."""
    word = word.lower()
    if word[:1] == "i" and word[1:] in _FIND_VALUED_NARROWING:
        word = word[1:]
    if word not in _FIND_VALUED_NARROWING:
        return False
    toks = _OPERAND_TOKEN_RE.findall(before[at:])
    value = _shell_unquote(toks[0]) if toks else ""
    return value in (_FIND_REGEX_CATCHALL_VALUES if word == "regex" else _FIND_CATCHALL_VALUES)


def _find_is_narrowed(span: str, action_at: int) -> bool:
    """True when a name-or-path predicate steers the walk before the delete
    action at ``action_at`` and nothing re-widens it -- the rule
    `_FIND_NARROWING_RE` states, by the predicate's VALUE: a catch-all
    narrows nothing. Fails toward `delete`: whatever this cannot read as
    narrowing is not narrowing, and the root is the operand."""
    before = span[:action_at]
    if not any(
        not _FIND_NEGATED_RE.search(before[:m.start()])
        and not _find_predicate_value_is_catchall(before, m.group(0)[1:], m.end())
        for m in _FIND_NARROWING_RE.finditer(before)
    ):
        return False
    if _FIND_NEGATED_RE.search(before) or _FIND_OR_AT_END_RE.search(before):
        return False                      # `! -delete`, `-o -delete`: the action is the operand
    for m in _FIND_OR_RE.finditer(before):
        right = m.group(1)
        if not _FIND_NARROWING_RE.fullmatch(right) or _FIND_NEGATED_RE.search(before[:m.start(1)]):
            return False                  # `-o -size +0c`, `-o ! -name x`: re-widened
        if _find_predicate_value_is_catchall(before, right[1:], m.end()):
            return False                  # `-o -name '*'`: re-widened by the value
    return True

# chmod / chown / chgrp / chflags / chattr / setfacl: a permission, ownership,
# flag, attribute or ACL change on a hook is the quietest way to silence it --
# `chmod 000 tools/cc/hooks/write_guard.py` leaves the file in place and
# unreadable, so the hook never runs and nothing reports it. The verb roster in
# tests/test_speedbump_irreversible.py carried `chmod` and `chown` for months
# with no matcher behind either (DEF-638; driven: both ALLOWED on a hook while
# `cp evil.json .claude/settings.json` denied). `chflags uchg <hook>` is the
# macOS-native spelling (immutable AND undeletable), `chattr +i` and `setfacl`
# the Linux ones; all three allowed beside a denied `chmod 000` until
# 2026-09-05 (DEF-695). Targets are every non-flag positional AFTER the
# mode/owner/flags token; `--reference=FILE` supplies the mode, so with it
# every positional is a target; `setfacl` names no mode positional at all
# (``_permission_targets``, which reads the verb from group 1).
# Command-position anchored like every sibling; \b(?!=) excludes a
# `chmod=...` shell assignment; {0,512} bounds the span.
# A same-line comment is cut from the span by `_strip_span_tail` (inside
# `_operands`): this helper reads EVERY positional, so a trailing comment that
# mentions a protected path (`chmod 644 README.md # never chmod 000 <hook>`) was
# folded into the targets and denied an ordinary command (review, driven live).
# This matcher was born excluding `#` from its class instead, which was a
# fail-open the `_INSTALL_CMD_RE` block explains (`chmod 000 a#b
# .claude/settings.json` -> allow); the class is `#`-blind now like its siblings.
_CHMOD_CHOWN_RE = re.compile(
    _CMD_POS + r"\b(chmod|chown|chgrp|chflags|chattr|setfacl)\b(?!=)([^|;&\n]{0,512})"
)

_ACL_VERBS = frozenset({"setfacl"})
"""Permission verbs whose EVERY positional is a file. ``setfacl`` carries its
ACL spec on a flag (``-m``/``-x``/``--set``/``--modify``/``--remove``; the
spec value reads as a positional too, harmlessly -- an ACL spec is never a
protected path) and ``setfacl -b <file>`` / ``-k <file>`` carry no spec at
all, so the skip-the-first rule the others need would drop the only operand
there (driven: ``setfacl -b <hook>`` -> allow under that rule). The
exception to "harmlessly": ``-M FILE`` / ``-X FILE`` / ``--restore=FILE``
name spec FILES, so a spec file kept inside a governed zone denies an
ordinary ``setfacl`` on a public file -- accepted friction, because the
alternative is a per-flag value table; the glued ``--restore=`` form is not
a positional and does not."""

_NO_MODE_POSITIONAL_FLAGS = frozenset({"-E", "-N", "-I"})
"""Flags under which a verb that normally names its mode first names NO mode
in THIS invocation -- the ``setfacl -b`` shape inside ``chmod`` itself. macOS
``chmod -E <file>`` reads an ACL from stdin and applies it (a deny ACE makes a
hook unreadable: the second macOS-native silencer), ``-N`` / ``-I`` strip or
inherit ACLs. Every positional is a file under any of them; driven, all four
allowed on a hook beside a denied ``chmod 000`` (failure-mode pass)."""


def _permission_targets(args: str, verb: str) -> list[str]:
    """The paths a permission-verb argument span acts on: every non-flag
    operand after the first (the mode / owner / flags / attributes), or
    every non-flag operand when the invocation names no mode positional --
    a ``--reference=`` flag supplies the mode, the verb takes none
    (``_ACL_VERBS``), or a flag says so for this call
    (``_NO_MODE_POSITIONAL_FLAGS``). A value-taking flag the tokenizer cannot
    know (``chattr -v 5``, ``chattr -p 7``) leaves its value in the
    positionals, which only ADDS a candidate -- the direction of error that
    costs friction on an ACL spec, never a missed hook. Operands come from
    ``_operands`` so a quoted path with a space is one target (a whitespace
    split dropped the real path on exactly that input at the sibling helper
    -- see ``_last_non_flag_token``)."""
    tokens = _operands(args)
    positionals = [t for t in tokens if not t.startswith("-")]
    if (
        verb in _ACL_VERBS
        or any(t in _NO_MODE_POSITIONAL_FLAGS for t in tokens)
        or any(t.startswith("--reference") for t in tokens)
    ):
        return positionals
    return positionals[1:]

# PowerShell write extraction lives further down, next to `_PS_CMD_POS`, because
# it is anchored on the command position exactly as its bash siblings above are.
# See `_PS_PATH_FLAG_RE` / `_PS_POSITIONAL_RE` below the PowerShell anchor block.
# git checkout/restore: any form that materializes a tracked file.
#   git checkout [ref] -- <path>          (any preceding refs/options)
#   git checkout <path>                   (bare; relies on _is_protected to filter branches)
#   git restore [opts] <path>             (modern form; always file-mode)
# {0,64}: verb-regex class bound (see _SED_INPLACE_RE comment).
# Command-position anchored, like every other verb in this module. These three
# were the LAST bare `\bgit\b` sites in the harness and they sit on the
# HARD-DENY tier, so a read-only mention did not earn a retry — it was refused:
# `grep -rn "git restore tools/cc/hooks/write_guard.py" docs/` returned
# `permissionDecision: deny`, which is verbatim the false positive this anchor
# exists to close, on the harness's own source.
#
# They survived the earlier anchoring sweep and the `_speedbump` class close
# because both scoped their populations to a MODULE rather than to the idiom:
# the speed-bump
# gate derives from `vars(_speedbump)`, so three git regexes living in the file
# that OWNS _CMD_POS were invisible to it. The gate is now derived over both
# modules (tests/test_speedbump_irreversible.py) so a fourth site cannot hide
# the same way. Class-fix scope is the idiom's population, not one file.
#: The git verb (`_GIT_VERB`), its global-option run (`_GIT_PREOPT`,
#: `_GIT_PREOPT_RUN`) and the head every subcommand arm composes
#: (`_GIT_SUBCOMMAND_AT`) live beside the find family above, before the
#: carrier that composes on them (DEF-831); the arms below read them from
#: there.
#: The `--` separator as an agent may spell it (DEF-814): bare, or quoted in
#: either kind -- `git checkout "--" <path>` hands git a bare `--` after
#: quote-removal on both shells, and some command generators quote every
#: argv word. The separator arm required the bare spelling and the bare-path
#: arm took the quoted one AS the path, so the hook path after it was
#: judged by neither and an uncommitted hook edit was discarded with no wall
#: and no nudge (driven at HEAD 2026-09-15: `['--']` from the extractor).
#: Exactly the three spellings, never a mismatched pair (review). ONE home:
#: the three tails below, `_speedbump._DISCARD_TAIL`.
_GIT_DASHDASH_SEP = r"""(?:"--"|'--'|--)"""
#: The three git materialise tails, spelled ONCE and composed on each shell's
#: `_GIT_SUBCOMMAND_AT` (`_GIT_CHECKOUT_DASHDASH_RE` and its `_PS_` twin, and
#: so on) the way `_speedbump._DISCARD_TAIL` is -- the PowerShell write leg
#: had no checkout or restore arm at all until DEF-814's lane (`git checkout
#: -- <hook>` and `git restore <hook>` passed unquoted on that tool, driven
#: 2026-09-15). The bare-path and restore arms skip a flag whether or not it
#: is quoted and refuse a quoted dash as the path (`"-b" feature` names no
#: file); `restore`'s `-s`/`--source` takes a separate value the generic
#: flag run would read as the path (review: `git restore -s HEAD~1 <hook>`
#: extracted `HEAD~1`). `{0,64}` and the `*` over a blank-terminated flag
#: run are the bounds the ReDoS rows budget.
_GIT_CHECKOUT_DASHDASH_TAIL = (
    r"checkout(?:[ \t]+\S+){0,64}?[ \t]+" + _GIT_DASHDASH_SEP + r"[ \t]+([^\s;|&]+)"
)
_GIT_CHECKOUT_BARE_TAIL = (
    r"""checkout[ \t]+(?:["']?-\S+[ \t]+)*(?!["']?-)([^\s;|&]+)"""
)
_GIT_RESTORE_TAIL = (
    r"""restore[ \t]+(?:["']?(?:-s|--source)[ \t]+[^\s;|&]+[ \t]+|["']?-\S+[ \t]+)*"""
    r"""(?!["']?-)([^\s;|&]+)"""
)
_GIT_CHECKOUT_DASHDASH_RE = re.compile(_CMD_POS + _GIT_SUBCOMMAND_AT + _GIT_CHECKOUT_DASHDASH_TAIL)
_GIT_CHECKOUT_BARE_RE = re.compile(_CMD_POS + _GIT_SUBCOMMAND_AT + _GIT_CHECKOUT_BARE_TAIL)
_GIT_RESTORE_RE = re.compile(_CMD_POS + _GIT_SUBCOMMAND_AT + _GIT_RESTORE_TAIL)
# `git rm` / `git mv` (§C52): the operands leave the tracked tree or move
# within it. Group 1 is the subcommand, group 2 the quote-aware operand span.
_GIT_RM_MV_RE = re.compile(
    _CMD_POS + _GIT_SUBCOMMAND_AT + r"(rm|mv)[ \t]+" + _OPERAND_SPAN
)
# `git clean` (§C52, the failure-mode review): with the ignored-files flag it
# takes the gitignored protected files (the settings file, the integrity and
# freshness manifests) -- the same slip as a plain delete. `_git_clean_operands`
# reads the span: a dry run yields nothing; a path operand is classified as
# spelled; the no-operand form with `-x`/`-X` and a force flag is the whole
# tree (`.`), which the consumer refuses as a tree that holds a protected
# path. Without the ignored-files flag the no-operand form stays the speed
# bump's (the zones hold no untracked-unignored file in a normal session).
_GIT_CLEAN_RE = re.compile(
    _CMD_POS + _GIT_SUBCOMMAND_AT + r"clean\b([^\n;|&]{0,512})"
)
# ``ln [opts] target linkname`` -- symlink creation into protected zones
# (or zones allowed inside protected, e.g. ``cc/blueprints/``) lets an
# attacker plant a symlink whose target is attacker-controlled, then have
# the harness follow it on next read. The classic case: forge
# ``cc/blueprints/latest.json`` -> ``/tmp/evil.json`` to ingest forged
# session context. ``cognitive_blueprint._load_latest`` refuses symlinks;
# this is the upstream defense that prevents the symlink from being created
# in the first place.
#
# The symlink flag is a short cluster containing ``s`` in ANY position OR
# ``--symbolic``; flags between it and the positionals are absorbed; the
# CAPTURED group is the operand SPAN, and `symlink_linkname` tokenises it
# (`_positional_operands`) and takes the last of at least two positionals --
# a 1-arg ``ln -s target`` links into CWD and names no location. The regex used
# to capture the last positional itself, so any trailing token -- ``-v``,
# ``2>/dev/null``, ``# note``, the ``)`` of ``( ln -s ... )`` -- became the
# "linkname" and the real one was never checked (DEF-414b, live from July
# until 2026-09-05; its ``cp -s`` twin DEF-596 was fixed first and the
# original outlived it). The span is one greedy run of quote-aware operands
# (disjoint alternatives, linear). KNOWN-LIMIT: ``-t``/``--target-directory``
# (the dir is the FLAG's argument, before the sources) is not modelled -- the
# tokenizer reads the dir as a positional (see
# docs/sharp-edges/protected-zone-symlink-backstop.md); reader-side symlink
# refusal is the decisive defense.
_LN_S_RE = re.compile(
    _CMD_POS + r"\bln" + _QUOTED_VERB_TAIL + r"[ \t]+"       # the tail tolerates a quoted verb `'ln'`
    r"(?:-[a-zA-Z]+[ \t]+|--[a-z-]+[ \t]+)*"        # leading flags (short or long)
    r"(?:-[a-zA-Z]*s[a-zA-Z]*|--symbolic)"     # symlink flag: cluster w/ s, or --symbolic
    # The operand SPAN, quote-aware (a linkname with a space is one operand --
    # DEF-638 review). Flags after the operands, `--`, a redirect, a comment and
    # a subshell close all land in it and fall away in `symlink_linkname`.
    r"((?:[ \t]+(?:\"[^\"]*\"|'[^']*'|[^\s;|&\"']+))+)"
)

# ``cp -s`` / ``cp --symbolic-link`` ALSO creates symlinks -- the same
# allowlist-blind treatment as ``ln -s``. _CP_MV_RE models only a plain
# copy/move and is allowlist-AWARE, so a cp-symlink into an
# allowlisted-in-protected path (cc/blueprints/, cc/execution_plan.json) slipped
# the protected-zone check. Same flag-cluster grammar as _LN_S_RE; the captured
# group is the operand span, tokenised by the same `symlink_linkname`.
_CP_SYMLINK_RE = re.compile(
    _CMD_POS + r"\bcp" + _QUOTED_VERB_TAIL + r"[ \t]+"            # the tail tolerates a quoted verb `'cp'`
    r"(?:-[a-zA-Z]+[ \t]+|--[a-z-]+[ \t]+)*"             # leading flags
    r"(?:-[a-zA-Z]*s[a-zA-Z]*|--symbolic-link)"    # symlink flag: cluster w/ s, or --symbolic-link
    r"((?:[ \t]+(?:\"[^\"]*\"|'[^']*'|[^\s;|&\"']+))+)"   # the operand span (see _LN_S_RE)
)


def symlink_linkname(span: str) -> str | None:
    """The link location an `ln -s` / `cp -s` operand span names: the LAST of
    at least two positionals (one operand links into CWD and names none).
    Through `_positional_operands`, so a trailing flag, a redirection, a
    comment and a subshell close -- every trailing token DEF-414b listed --
    fall away before the pick."""
    positionals = _positional_operands(span)
    return positionals[-1] if len(positionals) >= 2 else None

# PowerShell ``New-Item -ItemType SymbolicLink`` symlink creation lives further
# down, next to `_PS_CMD_POS`, for the same reason the PowerShell write
# extraction does: its verb members are anchored on the command position exactly
# as the bash symlink twins above are. See `powershell_symlink_linknames` below
# the PowerShell anchor block.


# HARDLINK creation. A hardlink aliases an inode under
# a second name; `ln <protected> alias; echo evil > alias` rewrites the protected
# file's bytes while the write lands on an UNPROTECTED path string (Path.resolve
# cannot follow a hardlink). The dangerous positional is the SOURCE (the protected
# file aliased OUT), the INVERSE of _LN_S_RE's linkname capture -- so this is a
# genuinely distinct code path, not a regex widening. ``ln`` creates a hardlink by
# DEFAULT (symlink only with -s/--symbolic); ``cp`` creates a hardlink ONLY with
# -l/--link (symlink with -s/--symbolic-link). A tokenizer (not a fixed-positional
# regex) classifies by flag membership in ANY order -- the same robust, ReDoS-free
# shape as rm_recursive_force_operands -- and yields ALL positionals so the caller
# can deny a hardlink touching a governed zone at EITHER end (allowlist-aware: the
# threat is aliasing a protected-NOT-allowed file; an alias of an allowlisted file
# confers nothing). The decisive close is the inode-aware write-through backstop
# (_protected_zones.aliases_protected_inode); this creation deny is early friction.
# KNOWN-LIMIT: ``-t``/``--target-directory`` takes the link DIR as the flag's
# argument (modelled only incidentally -- it falls through as a checked operand);
# arg-taking flags like ``-S suffix`` leave the suffix as a harmless extra operand.
# ``\b(?!=)``: exclude only a shell variable assignment ``ln=…``/``cp=…`` (``=`` is a
# word boundary, so a bare ``\b(ln|cp)\b`` false-matched the assignment and read a path
# in its value as a hardlink operand). A trailing QUOTE (``'ln' …``, collapsed back to
# ``ln`` by shell quote-removal) or whitespace is still a real command, so the guard
# excludes ONLY ``=`` -- a ``(?=\s)`` "require whitespace" guard would blind a
# quote-obfuscated verb, a false-negative in a fail-closed check. Capture unchanged.
# THE FLAG FORM is rejected by `_CMD_POS`, not by a lookbehind. `ls -ln <zone>` /
# `grep -ln <file>` embed `ln` after a `-`, and the path would otherwise be read
# as a hardlink operand and wrongly denied; a real hardlink command has the verb
# at a command position (start, after `;`/`|`/`&`), never `-`-prefixed, so the
# anchor excludes it. This comment described a `(?<!-)` lookbehind for months
# after `e28952a` replaced it with `_CMD_POS` -- the OUTCOME stayed correct
# (driven: `ls -ln <protected>` and `grep -ln foo <protected>` both ALLOW) but the
# stated mechanism was gone, which is worse than no comment: a reader trusts it
# and reasons from a guard that is not there.
_LN_CP_INVOCATION_RE = re.compile(_CMD_POS + r"\b(ln|cp)\b(?!=)([^;\n|&]*)", re.IGNORECASE)


def iter_hardlink_operands(command: str) -> Iterator[str]:
    """Yield each positional operand of a HARDLINK-creating ``ln``/``cp -l``
    invocation in ``command`` (line-continuations spliced, like the rm iterator).

    ``ln`` is a hardlink UNLESS it carries a symlink flag (``-s`` cluster or
    ``--symbolic``); ``cp`` is a hardlink ONLY with a link flag (``-l`` cluster
    or ``--link``) and no symlink flag. Operands are returned RAW; the caller
    normalises + classifies each against the protected zone. A same-line
    comment is cut first (`_strip_span_tail`): `ln a b # <hook>` handed the
    comment's last word to the protected-source check and denied a mention.
    """
    # ONE splicer for every leg: this iterator's own `re.sub` joined a CRLF
    # pseudo-continuation too, which `splice_line_continuations` had already
    # measured against bash as TWO statements (DEF-701 sibling-site sweep).
    # The write extractor's reading (`_extractor_pair`, DEF-848's lane): until
    # then this leg read the raw command alone, so a hardlink named through a
    # variable the shell runs was never read, and a separator inside a quoted
    # value opened a command position -- a message variable naming a link was
    # refused. Matched on the masked scan; the verb and the operand span are
    # read from the raw text at the match's offsets.
    raw, scan = _extractor_pair(command)
    for m in _LN_CP_INVOCATION_RE.finditer(scan):
        verb = raw_span(raw, m, 1).lower()
        symlink = hardlink_flag = end_opts = False
        operands: list[str] = []
        span = neutralise_redirect_ampersands(raw_span(raw, m, 2))
        for tok in _OPERAND_TOKEN_RE.findall(_strip_span_tail(span)):
            # one quoted operand, not a whitespace split: `ln x "<root with a
            # space>/hooks/x.py"` fell into three fragments, none protected
            # (DEF-794, driven); this leg already reads the raw command. The
            # flag tests read the token AS SPELLED: a quoted `"-s"` is not the
            # symlink flag to the symlink leg (`_LN_S_RE` wants it bare), so
            # stripping first sent `ln "-s" x <hook>` to neither leg (review,
            # driven). The value appended is the unquoted operand.
            operand = tok.strip('"').strip("'")
            if not end_opts and tok == "--":
                end_opts = True
                continue
            if not end_opts and tok.startswith("--"):
                name = tok[2:].split("=", 1)[0].lower()
                if name.startswith("symbolic"):   # --symbolic / --symbolic-link
                    symlink = True
                elif name == "link":
                    hardlink_flag = True
                continue
            if not end_opts and tok.startswith("-") and len(tok) > 1:
                body = tok[1:]
                if "s" in body:           # lowercase s only: -fs/-sf symlink,
                    symlink = True        # NOT -S (suffix, uppercase)
                if "l" in body:           # lowercase l only: cp -l/-al/-rl link,
                    hardlink_flag = True  # NOT -L (dereference, uppercase)
                continue
            operands.append(operand)
        is_hardlink = (
            (verb == "ln" and not symlink)
            or (verb == "cp" and hardlink_flag and not symlink)
        )
        if is_hardlink:
            yield from operands
# Inline interpreter -e/-c source: capture the body, then run an
# inner language-specific regex to extract literal write paths.
#
# Body alternation ``(?:\\.|(?!\1)[^\\])*`` is mutually exclusive on its
# two branches -- ``\\.`` consumes ``\X`` (2 chars starting with backslash);
# ``(?!\1)[^\\]`` consumes 1 non-backslash, non-quote char. Pre-fix the
# second branch was ``(?!\1).`` (any non-quote, including ``\``) which
# overlapped with the first branch -- a run of backslashes with no closing
# quote produced catastrophic backtracking (>500ms at n>=40 backslashes,
# benchmarked in ``tests/test_redos.py``). Mutual exclusion eliminates
# the ambiguity; the regex now runs in linear time on worst-case inputs.
# DEF-704 (bash leg; the PowerShell twins live beside `_PS_CMD_POS` below --
# DEF-712): the four openers carry `_CMD_POS` and are matched on the MASKED
# string, so a `#` comment or a quoted mention behind a roster head is text,
# not an invocation; the BODY is sliced out of the RAW command by offset
# (`_inline_program_bodies`, the discipline the stdin-program arm landed
# with). Joiners are `[ \t]+`: `\s+` reached past a newline and read a `-c`
# at the start of line two as this line's flag. The quoted body itself may
# span lines -- bash keeps a newline inside quotes -- which is why these four
# sit in the newline census's allowlist with exactly that reason. Driven
# 2026-09-06: `ls # python3 -c "open('<hook>','w')"` and the split spelling
# both yielded the hook path; both fail toward friction, never open.
# `["']?` after the name: a quoted interpreter path closes its quote there
# (`"C:\Python312\python.exe" -c`), which `\S*` used to swallow.
# The switch run before `-c`/`-e`: one bare value per switch (`-W ignore -c`,
# `-X utf8 -c`), the Bash spelling of the PowerShell arm's `_PS_SWITCH_RUN`
# -- the review of DEF-712 drove `python3 -W ignore -c <write>` ALLOWING on
# Bash while the PowerShell twin denied, the inverse of the asymmetry that
# lane closed. A value starts with a token character that is not `-` or a
# quote and runs to the blank that ends it (no `\s`: the newline census
# reads these openers), so a following switch or the program's quote is
# never eaten as a value and every adjacent quantifier pair is exclusive.
# Unbounded on purpose, and the reason is a measurement, not a preference.
# DEF-637's lane first bounded this run `{0,64}` against a flood whose switch
# VALUES were the next opener word; the code review then drove `python3`
# with sixty-five `-B` switches before `-c "open('<hook>','w')"` -- a command
# that RUNS -- and the bound had turned that deny into an allow, on both
# legs, while buying nothing: the Bash leg's openers sit on a command
# position, so a flood without separators has one opener and the run is one
# pass, and the PowerShell twin's quadratic was the opener-word value, fixed
# there by refusing it. A bound here is a coverage hole with no receipt.
_INTERP_SWITCH_RUN = r"(?:-[\w.-]+(?:[ \t]+[\w./:=,@%+~][\w./:=,@%+~-]*)?[ \t]+)*"
#: A program operand is ONE bash WORD (DEF-832), not one quoted span: bash
#: concatenates adjacent segments -- a single-quoted span, an ANSI-C span, a
#: double-quoted or locale span, a bare run -- with each segment's quote
#: removal into the one argument the program receives, so a path quoted
#: inside a single-quoted program (spelled by ending the outer quote, spliced
#: or naively) reaches the program as a bare path while a reader of the first
#: quoted span sees nothing (driven at the hook and on a throwaway, on the
#: interpreter, the POSIX shell and the PowerShell command operand). The word
#: starts with a quoted segment (a bare program names nothing, as before); a
#: bare run never sits beside another bare run, each quote arm is
#: self-delimited and the bare arm excludes every quote start (a `$` only
#: when no quote follows it, so the ANSI-C and locale arms own theirs), so the
#: alternation has one parse and an unclosed quote fails in one pass. The
#: run is UNBOUNDED on purpose, with the receipt `_INTERP_SWITCH_RUN`'s note
#: demands: a bound was a fail-open cliff (past it the opener still matched
#: on a truncated word and the reader yielded the truncated text -- padding
#: with empty segments, driven to a landed write; the code review), and it
#: bought nothing, since every iteration consumes a self-delimited quoted
#: segment and the arms are disjoint (measured linear at twenty thousand
#: segments; the flood rows in `tests/test_redos.py` pin it). The bare
#: arm's stop set is `_read_shell_word`'s explicit blanks and
#: metacharacters, never the whitespace class (a form feed or a vertical
#: tab is not a word break to bash, and the class cut a word the shell kept
#: whole -- driven; the two sets are pinned equal by a derived test). ONE
#: home for the six openers below; `_bash_word_text` is its one quote
#: removal.
_BASH_BARE_SEGMENT = r"""(?:\\[^\n]|[^ \t\n\r;|&<>(){}`'"\\$]|\$(?!['"]))+"""
_BASH_QUOTED_SEGMENT = r"""(?:'[^']*'|\$'(?:\\.|[^\\'])*'|\$?"(?:\\.|[^\\"])*")"""
_BASH_QUOTED_WORD = (
    _BASH_QUOTED_SEGMENT
    + r"(?:(?:" + _BASH_BARE_SEGMENT + r")?" + _BASH_QUOTED_SEGMENT + r")*"
    + r"(?:" + _BASH_BARE_SEGMENT + r")?"
)
_INLINE_C_TAIL = (
    r"""[\w.-]*""" + _QUOTED_VERB_TAIL + r"""[ \t]+""" + _INTERP_SWITCH_RUN
    + r"""-c[ \t]+(?P<word>""" + _BASH_QUOTED_WORD + r""")"""
)
_INLINE_E_TAIL = (
    r"""[\w.-]*""" + _QUOTED_VERB_TAIL + r"""[ \t]+""" + _INTERP_SWITCH_RUN
    + r"""-e[ \t]+(?P<word>""" + _BASH_QUOTED_WORD + r""")"""
)
# `(?i:...)` on the NAME only: a whole-pattern IGNORECASE leaked onto
# `_CMD_POS`'s wrapper and keyword arms for this one opener (code review).
_PYTHON_DASH_C_RE = re.compile(
    _CMD_POS + r"(?i:python|pypy)" + _INLINE_C_TAIL,
    re.DOTALL,
)
_NODE_DASH_E_RE = re.compile(_CMD_POS + r"node" + _INLINE_E_TAIL, re.DOTALL)
_RUBY_DASH_E_RE = re.compile(_CMD_POS + r"ruby" + _INLINE_E_TAIL, re.DOTALL)
_PERL_DASH_E_RE = re.compile(_CMD_POS + r"perl" + _INLINE_E_TAIL, re.DOTALL)

# ── Cross-shell routing: a program handed to the OTHER shell (DEF-637, §C49) ──
#
# `write_guard` dispatches on `tool_name`, so a PowerShell program behind
# `powershell -Command "..."` on the Bash tool was read with the bash grammar:
# no bash verb, no redirect, nothing -- while the identical cmdlet on the
# PowerShell tool denied. Driven on a Windows host (walk 2, W2-2): the
# protected write landed and the dotenv read echoed its contents. `python -c`
# under the same tool already denied, so the Bash extractor DOES walk nested
# interpreters; what it lacked was the shell head. The same asymmetry runs the
# other way (`bash -c "..."` on the PowerShell tool) and both directions take
# the DEF-704/DEF-712 discipline: the opener is anchored on the command
# position and matched on the masked scan, the program body is sliced from
# the raw twin at the same offsets and unescaped the way the OUTER shell hands
# it over, then handed WHOLE to the other shell's extractor
# (`_candidate_paths_from_powershell` / `_candidate_paths_from_bash`), read
# roster (`write_guard._secret_read_targets` and its twin) and dangerous
# records -- three consumers, one program-body helper per direction. The
# recursion is bounded by `_PS_STDIN_MAX_DEPTH`, so a program that re-enters
# the first shell is read one level down and no further.
#
# Two literals, both shells' rosters derived from them and pinned equal by
# `tests/test_speedbump_irreversible.py`: the PowerShell heads are what the
# Bash leg routes OUT and what the PowerShell stdin arm already re-scans; the
# POSIX heads are what the PowerShell leg routes out. Plain strings joined
# with `+`, never an f-string, so the ReDoS gate can reconstruct the openers.
_POWERSHELL_HEADS = "powershell|pwsh"
_POSIX_SHELL_HEADS = "bash|sh|zsh|dash|ksh"
#: The heads whose stdin program is PowerShell (re-scanned, never
#: pattern-matched); the stdin arm's dispatch table has no row for them.
_STDIN_SHELL_HEADS = frozenset(_POWERSHELL_HEADS.split("|"))
# The `-Command` switch and every unambiguous prefix PowerShell binds
# (`-c`, `-co`, ... `-command`), case-insensitive, with a `-` or `/` lead
# (`powershell /Command`, `/c` are the same switch on that command line),
# followed by the blank that separates it from the program. Nested
# optionals, no quantifier: one parse. The switch is OPTIONAL: Windows
# PowerShell reads a positional argument as `-Command` (`powershell
# "Set-Content ..."` runs it; documented upstream as the PowerShell 7
# breaking change that made `pwsh`'s first positional `-File` instead), so
# the switchless spelling is the same invocation with one token removed --
# both reviews drove it ALLOWING; on `pwsh` a positional is a file name and
# routing it can only over-deny a file named like a write, a command that
# fails on its own. Not driven on the walk host; owed there (ledger).
# The switch run before it is the shell's own (`_SHELL_SWITCH_RUN`): the
# interpreter run's shape with the `/` lead admitted (`/NoProfile -Command`),
# and LAZY, because the switch is optional: a greedy run reads `-Command
# Set-Content` as switch-plus-value and leaves `1` as the program (driven:
# the bare form went from deny to allow the moment the switch became
# optional). The shortest run that lets a switch or a program follow is the
# parse PowerShell makes; a flood of switches with no program is extended
# one token at a time and a switch never reads as a value, so it stays one
# pass (registered) -- which is why the value class here drops the `/` lead
# the interpreter run's admits: with `/` a switch lead AND a value lead, a
# `/NoLogo /NoLogo ...` flood had two parses per token and the registered
# row blew the budget; a `/`-led token now reads as a switch, and a
# `/`-led path value (`-WorkingDirectory /tmp`) is crossed the same way.
# The program is either ONE quoted word -- by bash's OWN quote rules, which
# differ per quote kind: inside single quotes nothing escapes and the word
# ends at the next `'` (a PowerShell path ends in a backslash as often as
# not, `'... C:\'`, and the interpreter arms' shared `\\.` alternation would
# swallow that closing quote -- driven, the record never fired); inside
# double quotes a backslash escapes the next character; `$'...'` is ANSI-C
# quoting, one word whose escapes bash decodes (the failure-mode review
# drove `pwsh -c $'Set-Content ...'` ALLOWING: the bare arm took it and the
# other shell read a string); `$"..."` is the locale form of `"..."`; each
# body is unescaped by `_bash_unescape_program` -- or BARE: PowerShell joins
# the rest of the line into one command (`powershell -Command Set-Content
# -Path x -Value 1`), so the bare arm runs to the statement separator. The
# bare arm refuses a leading quote or `$` (the quoted arms' job; a `$var`
# program is the indirection class), a leading `-` or `/` (a `-` is the
# stdin spelling `-Command - <<'EOF'`, the stdin arm's job; either is a
# switch the lazy run must be allowed to extend over -- `/NoProfile
# /Command "..."` read `/NoProfile` as the program until it refused) and is
# bounded.
# `-EncodedCommand` (base64, the indirection class) and `-File <script>` (the
# file is the program) have no opener here and are declared limits, pinned;
# so is a program PIPED to `-Command -` (the stdin arm reads `<<` only, on
# every interpreter -- its own row).
# Every branch is exclusive of its neighbour (`\\.` vs `[^\\"]`; `[^']`
# closed by the literal quote), so an unclosed body fails in one pass.
_SHELL_COMMAND_SWITCH = r"[-/](?i:c(?:o(?:m(?:m(?:a(?:n(?:d)?)?)?)?)?)?)"
_SHELL_SWITCH_RUN = r"(?:[-/][\w.-]+(?:[ \t]+[\w.:=,@%+~][\w./:=,@%+~-]*)?[ \t]+)*?"
_SHELL_COMMAND_TAIL = (
    r"""[\w.-]*""" + _QUOTED_VERB_TAIL + r"""[ \t]+""" + _SHELL_SWITCH_RUN
    + r"""(?:""" + _SHELL_COMMAND_SWITCH + r"""[ \t]+)?"""
    # the quoted program as one bash word of adjacent segments (DEF-832), or
    # a bare program; exclusive on the first character
    + r"""(?:(?P<word>""" + _BASH_QUOTED_WORD + r""")"""
    + r"""|(?P<bare>[^;|&\n\r"'\-$/][^;|&\n\r]{0,4095}))"""
)
_POWERSHELL_DASH_COMMAND_RE = re.compile(
    _CMD_POS + r"(?i:" + _POWERSHELL_HEADS + r")" + _SHELL_COMMAND_TAIL,
    re.DOTALL,
)
# A POSIX shell's `-c` program on the Bash tool (§C52): `sh -c '...'`,
# `bash -lc "..."`. The head and quoted-verb tail, the here-string opener's
# switch run (`_SHELL_HERESTRING_RE`), a cluster ending in `c`, then the
# program as ONE bash word that starts with a quoted segment (DEF-832:
# adjacent segments concatenated by the shell; no bare-first arm -- a bare
# program is one word and names nothing).
#: A POSIX shell's switch run before its program operand, ONE home for the
#: `-c` opener below and the here-string opener (`_SHELL_HERESTRING_RE`):
#: each switch may carry one bare value, never a shell head word (`sh -c sh
#: -c ...` read every following pair as switch-plus-value, O(n) at each of
#: n heads -- 4.0 s at 28 KB through the write extractor, a pre-existing
#: shape the §C52 rows witnessed), and the run is bounded at 64 tokens (the
#: DEF-637 receipt's remedy for the PowerShell twin).
_SHELL_SWITCH_RUN_BOUNDED = (
    # a short cluster or a long option (`--norc`, `--rcfile FILE`): exclusive
    # on the second character; the review drove `bash --norc -c` past the
    # short-only run
    r"(?:[ \t]+(?:-[A-Za-z]+|--[A-Za-z][\w-]*)(?:[ \t]+(?!(?:" + _POSIX_SHELL_HEADS
    + r")(?=[ \t]|$))[\w.=/][\w.=/-]*)?){0,64}"
)
_SHELL_DASH_C_RE = re.compile(
    _CMD_POS + r"(?:" + _POSIX_SHELL_HEADS + r")\b" + _QUOTED_VERB_TAIL
    # `c` anywhere in the cluster (`-cx`, `-xc`, `-lc`): both runs bounded, so
    # the adjacent pair has at most 81 parses (review: `bash -cx` was missed)
    + _SHELL_SWITCH_RUN_BOUNDED + r"[ \t]+-[A-Za-z]{0,8}c[A-Za-z]{0,8}[ \t]+"
    + r"(?P<word>" + _BASH_QUOTED_WORD + r")"
)


def _posix_shell_c_bodies(command: str, scan: str) -> Iterator[str]:
    """Yield the program a `sh -c '...'` / `bash -lc "..."` on the Bash tool
    runs: opener on the scan, the word from the raw text at the match's
    offsets, its quote removal by `_bash_word_text` (DEF-832: a program
    operand is one bash word of adjacent segments; a path quoted inside a
    single-quoted program reached the shell as a bare path and this reader
    saw the first span alone). The write leg reads a single-span program
    raw already -- a POSIX-shell head is off the masker's roster, so a
    redirect inside its quoted program is a redirect to the scan -- and
    takes this reader only for the concatenated spelling, one level down
    (`_candidate_paths_from_bash`, the double read deliberate); a
    verb-roster reader (the secret leg) sees `sh` as the statement's verb and
    nothing past it, and the remove/relocate reader judges a nested delete
    by the grammar that runs it."""
    if len(scan) != len(command):
        scan = command
    for m in _SHELL_DASH_C_RE.finditer(scan):
        yield _bash_word_text(command[m.start("word"):m.end("word")])


# Inner write-target patterns per language. Each captures a quoted literal
# write path out of an interpreter -e/-c body. ReDoS safety: the path capture
# must be a greedy, quote-AND-whitespace-excluding class closed directly by the
# backreference (``([^'"\s]+)\1``) -- NEVER a lazy class with a trailing ``\s*``
# before the close (``([^'"]+?)\s*\1``), whose two quantifiers overlap on a
# whitespace run and backtrack catastrophically on an unclosed inner quote.
# All four are pinned linear by ``tests/test_redos.py``.
#
# `_PY_STR_PREFIX`: a raw, bytes, unicode or f-string prefix before the quote
# (`open(r'tools\cc\hooks\x.py', 'w')` is how a Windows agent spells a
# backslash path, and `\(\s*(['"])` stopped dead at the `r`). One or two
# prefix letters, then the quote; the class is exclusive of `\s` and of the
# quote, so nothing here gains a second parse. An f-string whose body has no
# brace is a literal; a brace in the LEADING segment yields a path that
# normalises outside every zone (the computed-path boundary the arm already
# declares), while a brace in the tail still lands inside one and denies --
# both the direction wanted, which is why `f` stays in the class (DEF-712).
_PY_STR_PREFIX = r"(?:[rRbBuUfF]{1,2})?"
_PY_FILE_OPEN_RE = re.compile(
    r"""open\s*\(\s*""" + _PY_STR_PREFIX + r"""(['"])([^'"]+)\1\s*,\s*(['"])[wax]"""
)
# The pathlib writers: `Path(<lit>).write_text(` / `.write_bytes(` / `.open('w')`
# (`pathlib.Path(...)` reaches the same `\bPath`). Same ReDoS shape as
# `_PY_FILE_OPEN_RE`: a greedy quote-excluding path class closed directly by
# the backreference, one deterministic token at a time after it.
_PY_PATH_WRITE_RE = re.compile(
    r"""\bPath\s*\(\s*""" + _PY_STR_PREFIX + r"""(['"])([^'"]+)\1\s*\)\s*\.\s*"""
    r"""(?:write_text|write_bytes|open\s*\(\s*['"][wax])"""
)
# Destination-argument writers: `shutil.copy(src, <lit>)` and its siblings,
# `os.rename` / `os.replace`. The FIRST argument is a quoted literal stepped
# over WITHOUT a backreference (a quote of the other kind inside it is a miss,
# never a backtrack), so the destination is group(2) like every other inner
# pattern and the caller needs no per-pattern group table.
_PY_DEST_ARG_WRITE_RE = re.compile(
    r"""\b(?:shutil\s*\.\s*(?:copyfile|copytree|copy2|copy|move)|os\s*\.\s*(?:rename|replace))"""
    r"""\s*\(\s*""" + _PY_STR_PREFIX + r"""['"][^'"]*['"]\s*,\s*"""
    + _PY_STR_PREFIX + r"""(['"])([^'"]+)\1"""
)
_NODE_FS_WRITE_RE = re.compile(
    r"""\b(?:writeFileSync|appendFileSync|createWriteStream|"""
    r"""writeFile|appendFile)\s*\(\s*(['"])([^'"]+)\1"""
)
_RUBY_FILE_WRITE_RE = re.compile(
    r"""File\.(?:open|write|new)\s*\(\s*(['"])([^'"]+)\1"""
    r"""(?:\s*,\s*(['"])(?:w|a)['"]?)?"""
)
# This regex must be provably linear -- a single 2-arg-perl-open extractor with
# several greedy/overlapping quantifiers run via ``finditer`` over attacker text
# is a nest of catastrophic-backtracking shapes. The structural rules it obeys:
# (a) EVERY adjacent quantifier pair must be mutually exclusive (no ambiguous
# partition to backtrack over), and (b) the leading literal must carry a
# word-boundary lookbehind so ``finditer`` cannot re-trigger an O(remaining) scan
# at every repeat of it. The three structural fixes that make it linear on ALL
# shapes:
#   - ``(?<![A-Za-z0-9_])`` before ``open`` -- a repeated ``open`` has ONE valid
#     start (mirrors the outer interpreter regexes), so ``finditer`` cannot
#     re-scan O(remaining) at each repeat (``openopen...``).
#   - ``\s*(?:\(\s*)?`` (one leading ``\s*``, the ``(`` and its trailing space as
#     a single optional unit) -- no ambiguous split of a leading space run
#     (``open<sp×n>(``).
#   - ``[^\s,('"]+`` filehandle (excludes space/comma/paren/quote) instead of
#     ``\S+`` -- stops deterministically at the comma and fails O(1) on
#     ``open(open(...``; no backtrack-to-find-comma.
# The four legit perl write forms (``>`` ``>>`` ``+>`` ``+<``) still extract;
# group(2) is still the path, and its class admits internal SPACES since
# DEF-794 (a path under a spaced project root; the first character still
# excludes whitespace so the leading ``\s*`` keeps one parse). NOT extracted
# (harmless -- no protected zone matches): a first char of ``>``/``+``, a
# lexical-``my $fh`` filehandle, or an ``open`` glued to a leading identifier
# char.
_PERL_OPEN_RE = re.compile(
    r"""(?<![A-Za-z0-9_])open\s*(?:\(\s*)?[^\s,('"]+\s*,\s*(['"])\s*[>+]+\s*([^'"\s>+][^'"\n]*)\1"""
)
#: The THREE-argument perl `open` (DEF-813): the mode and the path in
#: separate strings -- `open(my $fh, ">", "path")`, `open(FH, '>>', 'path')`,
#: `open my $fh, '+<', 'path' or die` -- which perl's own documentation
#: recommends and a lexical filehandle forces. The two-argument arm above
#: reads only the shared string, so every modern spelling reached a
#: protected path unchecked (driven at HEAD 2026-09-15: `[]` from the
#: extractor beside the two-argument twin's path, on both shells). Linear by
#: the same rules as its sibling: one start per `open` (the lookbehind), the
#: paren and its blank one optional unit, `(?:my[ \t]+)?` before a handle
#: class that cannot start with a blank, `\s*,\s*` split by the comma, the
#: mode alternation exclusive on its first character (`>`, `>>`, `+<`, `+>`,
#: `+>>`) then an optional `:`-led layer (`>:encoding(UTF-8)`, `>:raw`)
#: bounded at 64, the blank run then the closing quote -- spelled per quote
#: kind so no backreference sits before the path group, which stays
#: group(2) as every inner write arm's does -- and the path whose first
#: character excludes a blank and the mode characters, closed by its own
#: quote. A computed path (`$path`, a concatenation) is the declared limit
#: every inner arm shares. The read twin, `_PERL_OPEN3_READ_RE`, sits with
#: the read table below.
_PERL_OPEN3_HEAD = r"""(?<![A-Za-z0-9_])open\s*(?:\(\s*)?(?:my[ \t]+)?[^\s,('"]+\s*,\s*"""
_PERL_OPEN3_WRITE_MODE = r"""(?:>>?|\+(?:<|>>?))(?::[^'"\s]{0,64})?"""
_PERL_OPEN3_RE = re.compile(
    _PERL_OPEN3_HEAD
    + r"""(?:'\s*""" + _PERL_OPEN3_WRITE_MODE + r"""\s*'|"\s*""" + _PERL_OPEN3_WRITE_MODE + r"""\s*")"""
    + r"""\s*,\s*(['"])([^'"\s<>+][^'"\n]*)\1"""
)
#: Every perl inner write pattern, applied to the `-e` arm, the stdin
#: program and the PowerShell twin alike; each carries its path in group(2).
_PERL_WRITE_RES: tuple[re.Pattern[str], ...] = (_PERL_OPEN_RE, _PERL_OPEN3_RE)
#: Every Python inner write pattern, applied to BOTH Python arms (`-c` and the
#: stdin program below); each carries its path in group(2).
_PY_WRITE_RES: tuple[re.Pattern[str], ...] = (
    _PY_FILE_OPEN_RE, _PY_PATH_WRITE_RE, _PY_DEST_ARG_WRITE_RE,
)

# ── Interpreter PROGRAM on stdin: heredoc or here-string ─────────────────────
#
# `python3 - <<'PY' … PY`, `python3 <<EOF … EOF`, `node - <<'JS'`, `ruby <<'RB'`,
# `perl <<'PL'` and the here-string `python3 - <<< "…"` all hand the interpreter
# its PROGRAM on stdin. That is the `-c`/`-e` shape with a different spelling,
# and its body sits between the operator and the terminator inside the very
# string this hook receives. BC-OOS-003 filed it beside the two-step subprocess
# class as if the body were invisible to the shell text; it never was (DEF-698,
# driven 2026-09-06: the `-c` spelling of the same write denied, this allowed).
#
# The two halves the `_PYTHON_DASH_C_RE` roster note prescribes, applied here
# from the start rather than retrofitted:
#   * the OPENER is `_CMD_POS`-anchored and matched on `scan` (the masked
#     string), so `python3 - <<'X'` inside a quoted-delimiter documentation
#     heredoc -- its `<<` blanked by the mask -- or behind a `#` is a mention,
#     not an invocation;
#   * the BODY is sliced out of the RAW `command` by offset (the mask preserves
#     length), because the body's own syntax characters are what the inner
#     patterns read.
# Grammar: interpreter, optional single-letter flags, then EITHER nothing OR a
# `-` operand (optionally followed by a bounded run of script arguments), then
# `<<`. A script or module operand (`python3 script.py <<EOF`, `python3 -m
# json.tool <<EOF`) does not match: there the body is DATA, not the program.
# An assignment whose name collides with an interpreter (`python3=/opt/bin/py`)
# is excluded by the grammar itself, not by a `(?!=)` guard: after the name only
# blanks, `-`+letters, a `-` operand or `<<` may follow, and none of them can
# consume the `=`. Whitespace is never REQUIRED (SHARP_EDGES: exclude `=`, never
# require whitespace -- `python3<<'PY'` is a real invocation). Known misses,
# named rather than widened: a valued flag before the operand (`-W ignore -
# <<EOF`) and a redirect between the operand and the operator (`- 2>/dev/null
# <<EOF`). Three over-captures, also named (each fails toward friction, never
# open): (1) the mask relief above holds only when EVERY top-level head of the
# command is on `_NON_REPARSING_HEADS` -- `sed <<'MD' > notes.md`, `awk`, `git`
# or an interpreter as head leaves the whole command raw, and a documentation
# body mentioning this shape is read as an invocation; (2) a SECOND heredoc
# queued on the same opening line (`cat > n.md <<'MD' && python3 - <<'PY'`):
# the body slice starts at the first newline after the operator, so the
# preceding heredoc's body is attributed to the interpreter; (3) the suffix
# class `[\w.-]*` that admits `python3.12` and `pypy3` also admits `nodemon`,
# `perlbrew`, `rubygems` -- deliberate, since a version-suffix class would drop
# real spellings for no measured gain.
# ReDoS: every adjacent quantifier pair is mutually exclusive (`[\w.-]` vs
# `[ \t]`, `-`+letter vs `-`+space, a token vs its trailing spaces) and the
# argument run is bounded, so the pattern is linear on any input; pinned in
# `tests/test_redos.py` beside the other extraction regexes.
#: The interpreters that read their program from stdin. ONE literal: the opener's
#: alternation and the dispatch table's keys are both derived from it, and the
#: assert below the table refuses an interpreter added to one side only (the
#: KeyError that would otherwise surface as an internal-error deny on every Bash
#: command naming it). A plain string, not a join(), so the ReDoS gate can still
#: reconstruct the pattern statically.
#: The two PowerShell heads join the alternation (DEF-637): `pwsh -Command -
#: <<'EOF'` feeds the shell its program on stdin exactly as `python3 - <<'PY'`
#: does, and the body is PowerShell -- re-scanned by `_shell_program_bodies`,
#: not pattern-matched, so the dispatch table below has no row for them and
#: the drift check subtracts them. Case-insensitive on the head only: the
#: Windows spelling is `PowerShell`, and the inline opener already folds.
_INTERP_ALTERNATION = "python|pypy|node|ruby|perl|" + _POWERSHELL_HEADS
_INTERP_STDIN_RE = re.compile(
    _CMD_POS
    + r"\b((?i:" + _INTERP_ALTERNATION + r"))[\w.-]*" + _QUOTED_VERB_TAIL
    + r"[ \t]*(?:-[A-Za-z]+[ \t]+)*"
    + r"(?:-[ \t]+(?:[^\s<>;|&][^\s<>;|&]*[ \t]+){0,8}|-)?<<"
)

#: Inner write patterns per interpreter for a program delivered on stdin. The
#: `-c`/`-e` arms below are the other consumer of the same regexes.
_STDIN_PROGRAM_WRITE_RES: dict[str, tuple[re.Pattern[str], ...]] = {
    "python": _PY_WRITE_RES,
    "pypy": _PY_WRITE_RES,
    "node": (_NODE_FS_WRITE_RE,),
    "ruby": (_RUBY_FILE_WRITE_RE,),
    "perl": _PERL_WRITE_RES,
}
if set(_INTERP_ALTERNATION.split("|")) != (set(_STDIN_PROGRAM_WRITE_RES) | _STDIN_SHELL_HEADS):
    # `raise`, not `assert`: an interpreter started with `-O` drops an assert,
    # and the drift would then surface as a KeyError inside the hook -- an
    # rc=1 script error, which the protocol reads as an allow (review).
    raise RuntimeError(
        "stdin-program interpreter roster drift: the opener alternation and "
        "the dispatch table must name the same interpreters"
    )

# ── Inner MUTATION and READ patterns per language (§C52) ─────────────────────
#
# The same discipline as the write tables above: a quoted literal path in
# group(2), a greedy quote-excluding class closed directly by the
# backreference, every adjacent quantifier pair exclusive. A mutation is a
# delete (`os.remove`, `Path(x).unlink`, `fs.rmSync`, `File.delete`, perl
# `unlink`) or a relocation of its FIRST argument (`os.rename`, `shutil.move`,
# `fs.renameSync`, `File.rename`, perl `rename`) -- the write tables read the
# DESTINATION of the same relocations; a read (`open(x)` without a write
# mode, `Path(x).read_text`, `fs.readFileSync`, `File.read`, perl `open(F,
# '<x')`) surfaces the file, which the secret leg reads by effect.
_PY_OS_MUTATE_RE = re.compile(
    r"""\b(?:os\s*\.\s*(?:remove|unlink|rmdir|removedirs|rename|replace)"""
    r"""|shutil\s*\.\s*(?:rmtree|move))\s*\(\s*""" + _PY_STR_PREFIX + r"""(['"])([^'"]+)\1"""
)
_PY_PATH_MUTATE_RE = re.compile(
    r"""\bPath\s*\(\s*""" + _PY_STR_PREFIX + r"""(['"])([^'"]+)\1\s*\)\s*\.\s*"""
    r"""(?:unlink|rmdir|rename|replace)\b"""
)
_PY_MUTATE_RES: tuple[re.Pattern[str], ...] = (_PY_OS_MUTATE_RE, _PY_PATH_MUTATE_RE)
_NODE_FS_MUTATE_RE = re.compile(
    r"""\b(?:unlinkSync|rmSync|rmdirSync|renameSync|unlink|rm|rmdir|rename)\s*\(\s*(['"])([^'"]+)\1"""
)
_RUBY_FILE_MUTATE_RE = re.compile(
    r"""\b(?:File\s*\.\s*(?:delete|unlink|rename)"""
    r"""|FileUtils\s*\.\s*(?:rm_rf|rm_r|rm_f|rm|remove_dir|remove_entry|remove|rmdir|mv|move))"""
    r"""\s*\(\s*(['"])([^'"]+)\1"""
)
# `\s*(?:\(\s*)?`: the paren and its trailing blank as one optional unit, the
# `_PERL_OPEN_RE` shape (two adjacent blank runs would be the ambiguous pair).
_PERL_MUTATE_RE = re.compile(
    r"""(?<![A-Za-z0-9_])(?:unlink|rename|rmdir|rmtree|remove_tree)\s*(?:\(\s*)?(['"])([^'"]+)\1"""
)
# A read: `open(<lit>)` closed at once or followed by a mode that starts
# with `r`; `\1\s*` then `\)` or `,` -- exclusive. `(?<![\w.])` keeps the
# pathlib spelling for the path pattern beside it.
_PY_FILE_OPEN_READ_RE = re.compile(
    r"""(?<![A-Za-z0-9_.])open\s*\(\s*""" + _PY_STR_PREFIX + r"""(['"])([^'"]+)\1\s*"""
    r"""(?:\)|,\s*(?:mode\s*=\s*)?['"]r)"""
)
_PY_PATH_READ_RE = re.compile(
    r"""\bPath\s*\(\s*""" + _PY_STR_PREFIX + r"""(['"])([^'"]+)\1\s*\)\s*\.\s*"""
    r"""(?:read_text|read_bytes|open\s*\(\s*(?:\)|['"]r))"""
)
_PY_READ_RES: tuple[re.Pattern[str], ...] = (_PY_FILE_OPEN_READ_RE, _PY_PATH_READ_RE)
_NODE_FS_READ_RE = re.compile(
    r"""\b(?:readFileSync|readFile|createReadStream)\s*\(\s*(['"])([^'"]+)\1"""
)
_RUBY_FILE_READ_RE = re.compile(
    r"""\b(?:File|IO)\s*\.\s*(?:read|readlines|foreach|binread)\s*\(\s*(['"])([^'"]+)\1"""
)
# The `<` mode of a two-argument perl open; the first path character excludes
# a blank and the mode characters, so the blank run before it keeps one parse.
_PERL_OPEN_READ_RE = re.compile(
    r"""(?<![A-Za-z0-9_])open\s*(?:\(\s*)?[^\s,('"]+\s*,\s*(['"])\s*<\s*([^'"\s<>+][^'"\n]*)\1"""
)
# The three-argument read (DEF-813, the twin of `_PERL_OPEN3_RE`): the `<`
# mode in its own string, an optional `:`-led layer, the path in the next.
# `+<` is read-write and the write arm's; the `<` here follows the quote
# directly, so the two arms are exclusive on the mode's first character.
_PERL_OPEN3_READ_MODE = r"""<(?::[^'"\s]{0,64})?"""
_PERL_OPEN3_READ_RE = re.compile(
    _PERL_OPEN3_HEAD
    + r"""(?:'\s*""" + _PERL_OPEN3_READ_MODE + r"""\s*'|"\s*""" + _PERL_OPEN3_READ_MODE + r"""\s*")"""
    + r"""\s*,\s*(['"])([^'"\s<>+][^'"\n]*)\1"""
)
_PERL_READ_RES: tuple[re.Pattern[str], ...] = (_PERL_OPEN_READ_RE, _PERL_OPEN3_READ_RE)
#: Dispatch BY NAME (not by object): the contract test blinds an arm by
#: replacing the module attribute, and a table bound to the tuple object
#: would keep reading the original. `_inner_arm` resolves at call time.
_STDIN_PROGRAM_MUTATE_RES: dict[str, str] = {
    "python": "_PY_MUTATE_RES", "pypy": "_PY_MUTATE_RES", "node": "_NODE_FS_MUTATE_RE",
    "ruby": "_RUBY_FILE_MUTATE_RE", "perl": "_PERL_MUTATE_RE",
}
_STDIN_PROGRAM_READ_RES: dict[str, str] = {
    "python": "_PY_READ_RES", "pypy": "_PY_READ_RES", "node": "_NODE_FS_READ_RE",
    "ruby": "_RUBY_FILE_READ_RE", "perl": "_PERL_READ_RES",
}
if set(_STDIN_PROGRAM_MUTATE_RES) != set(_STDIN_PROGRAM_WRITE_RES) or (
    set(_STDIN_PROGRAM_READ_RES) != set(_STDIN_PROGRAM_WRITE_RES)
):
    raise RuntimeError(
        "inner-pattern roster drift: the mutate and read dispatch tables must "
        "name the interpreters the write table names"
    )
#: The inner arms the readers consume, derived from the two tables.
_MUTATION_INNER_ARMS: tuple[str, ...] = tuple(sorted(
    set(_STDIN_PROGRAM_MUTATE_RES.values()) | set(_STDIN_PROGRAM_READ_RES.values())
))
if not all(name in globals() for name in _MUTATION_INNER_ARMS):
    raise RuntimeError(
        "inner-pattern dispatch names an arm this module lacks: "
        + ", ".join(n for n in _MUTATION_INNER_ARMS if n not in globals())
    )
_INNER_MOVE_WORD_RE = re.compile(r"\bmove\b|\bmv\b|rename|replace")


def _inner_arm(name: str) -> tuple[re.Pattern[str], ...]:
    value = globals()[name]
    return value if isinstance(value, tuple) else (value,)


def _inner_effect(m: "re.Match[str]") -> str:
    """`move` when an interpreter mutation names a relocation, else `delete`
    -- read from the METHOD text before the path group, never from the path
    (review: `shutil.rmtree('tools/cc/renamed')` read as a move)."""
    head = m.group(0)[:m.start(2) - m.start(0)]
    return "move" if _INNER_MOVE_WORD_RE.search(head) else "delete"


def _program_effects(family: str, body: str) -> list[tuple[str, str]]:
    """The (effect, path) pairs one interpreter program body yields: its
    literal mutations, and its literal reads (the secret leg's effect)."""
    out: list[tuple[str, str]] = []
    mutate = _STDIN_PROGRAM_MUTATE_RES.get(family)
    if mutate is not None:
        for rx in _inner_arm(mutate):
            for om in rx.finditer(body):
                out.append((_inner_effect(om), om.group(2)))
    read = _STDIN_PROGRAM_READ_RES.get(family)
    if read is not None:
        for rx in _inner_arm(read):
            for om in rx.finditer(body):
                out.append(("read", om.group(2)))
    return out

# Variable-indirect expansion (literal-only). Recognises `NAME=word` and
# `NAME='single'` and `NAME="double-no-dollar"` assignments at a statement
# start. `$NAME` and `${NAME}` references in
# the segments AFTER a binding are expanded, each taking the most recent
# binding before it (sequential since 2026-09-15 -- until then the last
# binding on the line won for every reference, so a rebinding after the
# write allowed it; DEF-801's lane). A later assignment whose value is not
# a literal (`NAME=$(...)`) UNBINDS the name for what follows. Anything
# fancier (command substitution, parameter expansion, arrays, a second
# assignment in one statement) remains documented out-of-scope. The
# PowerShell twin is
# `_PS_VAR_ASSIGN_RE` / `_expand_simple_ps_var_assignments`. A plain word
# may start with a tilde, but only the walls' reading binds one
# (`_bound_value`, DEF-846); every other reader unbinds it, as before.
#
# DEF-847: until 2026-09-19 the pattern read only an UPPERCASE name after
# `^`, `;` or `&&`, so a lowercase name -- the spelling an agent writes
# most -- a binding behind a declaration builtin, one on an earlier line,
# one inside a brace or paren group, and one inside a program handed to
# `eval` or a shell's `-c` all left the reference raw, and the walls met a
# bare variable operand (the nudge) where the uppercase twin walled. The
# name is any shell name now, and the three fragments below say where a
# binding the shell keeps can start.
#: The builtins that take an assignment as an operand and bind the name in
#: the current shell (DEF-847), each with any run of flags before the name.
_DECL_BUILTIN_PREFIX = (
    r"(?:(?:export|local|declare|typeset|readonly)(?:[ \t]+-[A-Za-z]+)*[ \t]+)?"
)
#: Where a binding can start: the start of the text, a separator the shell
#: continues past (`;`, `&&`, `||`, a newline), a brace or paren that is not
#: a parameter or command expansion's (`${`, `$(` are not group openers:
#: `${X=v}` assigns only when X is unset), or the opener of a program handed
#: to `eval` or a shell's `-c` (`_CMD_POS_EXEC_QUOTE`, which owns its
#: trailing blanks) -- that program is read in place, where the walls read
#: it. The pattern alone cannot tell a LIVE anchor from one inside a quoted
#: argument or a comment: `_expand_simple_var_assignments` searches it over
#: the MASKED text, where an inert span's separators, groups and exec openers
#: are blank, and a binding made inside a child scope ends when that scope
#: closes (`_binding_scope_events`). The blank run after a separator is the
#: horizontal class ONLY: a newline is an anchor itself, and a whitespace
#: class that took one would let every newline in a run of blank lines
#: re-scan the rest of the run (quadratic; the ReDoS rule).
_BINDING_START = (
    r"(?:(?:^|;|\&\&|\|\||\n|(?<!\$)[{(])" + _CMD_POS_WS + "|" + _CMD_POS_EXEC_QUOTE + ")"
)
_BINDING_NAME = r"([A-Za-z_][A-Za-z0-9_]*)"
_VAR_ASSIGN_RE = re.compile(
    _BINDING_START + _DECL_BUILTIN_PREFIX + _BINDING_NAME + r"""\s*=\s*"""
    r"""(?:'([^'$]*)'|\"([^\"$]*)\"|(~[A-Za-z0-9_./\-]*|[A-Za-z0-9_./\-]+))"""
)


def _bound_value(lit: "re.Match[str]", command: str, wall: bool) -> str | None:
    """The value one literal binding stores, as the inlined text should spell
    it -- or ``None``, which unbinds the name.

    For every reader but the walls, the reading it had before DEF-846: a
    quoted value or a plain word as spelled, and a plain word that starts
    with a tilde unbinds (the pattern did not admit one, so the name was
    unknown). That keeps the zone reader and the write extractor where they
    were: a value re-parsed by `bash -c` or `eval` tilde-expands there, which
    no rewrite here can model (the failure-mode review drove a protected
    write the quoted rewrite below let through when every reader took it).

    For the walls (``wall``: `_wall_readings`), two rules more. A value that
    runs on past its literal (`D=~/"a b"`, `O=./$N`) is NOT bound: the
    pattern matched only its prefix, and inlining the prefix walled the home
    directory or the checkout on an everyday spelling (the code review,
    driven). And bash tilde-expands an UNQUOTED value at assignment, so
    `H=~` binds the home -- as spelled, which every reader takes as the home,
    in a quoted reference too -- while a QUOTED tilde is the literal
    character, a file of that name in the working directory, bound as
    `./~...` so the wall never reads it as the home."""
    if lit.group(2) is not None:
        value, quoted = lit.group(2), True
    elif lit.group(3) is not None:
        value, quoted = lit.group(3), True
    else:
        value, quoted = lit.group(4), False
    if not wall:
        return None if (not quoted and value.startswith("~")) else value
    end = lit.end()
    if end < len(command) and command[end] not in " \t\r\n;&|)":
        return None
    if quoted and value.startswith("~"):
        return "./" + value
    return value


#: Every `NAME=` at a statement start, literal value or not: the sites the
#: sequential pre-pass walks. One that `_VAR_ASSIGN_RE` also matches binds;
#: any other unbinds the name (its value is computed, so a later reference
#: is unknown rather than stale -- a stale binding is the only way this
#: pre-pass could REFUSE a write that lands elsewhere).
_VAR_ANY_ASSIGN_RE = re.compile(_BINDING_START + _DECL_BUILTIN_PREFIX + _BINDING_NAME + "=")

_BASH_COMMAND_CAP = 32_768  # bytes (total scan budget head + tail combined)
_BASH_COMMAND_HALF_CAP = _BASH_COMMAND_CAP // 2  # 16384 each side


# ── Shell role map: which separator characters are SYNTAX, which are TEXT ──
#
# The guards scan a flat command string for verbs and redirect targets. They had
# no quoting awareness at all, so text that MENTIONS a command was read as an
# INVOCATION of it: `grep -n "> tools/cc/hooks/write_guard.py" docs/` denied as a
# protected-zone write, a `<<'EOF'` body denied as a catastrophic delete, a `#`
# comment denied as a git checkpoint. Measured 2026-08-24 by driving the real
# hooks: 6/6 inert redirect shapes and 3/4 inert delete shapes were refused.
#
# ⚠ THIS IS A ROLE MAP, NOT A BLANKING MASK, AND THE DIFFERENCE IS THE WHOLE
# DESIGN. An earlier attempt blanked quoted-span CONTENTS and was rejected because
# it destroyed six catastrophic-rm classes -- `rm -r"f" /`, `"rm" -rf /`,
# `rm'' -rf /`, `\rm -rf /`, `rm -rf "/"`, `'rm' -rf /`. Those splice quotes INSIDE
# a word, and the shell concatenates them away; blanking the span deletes the verb.
# All six were re-measured here: NONE carries a separator character inside a quoted
# span. So this pass substitutes ONLY separator/operator characters that are
# literal-by-position, leaves every byte of token content alone, and preserves the
# string's LENGTH and offsets. All six still deny.
#
# What stays LIVE (verified against real bash, not recalled):
#   backtick and $( ... )   -- expand inside double quotes AND inside an unquoted
#                              heredoc body, so those spans are stepped over
#   ${ ... }                -- a live parameter expansion, stepped over because it
#                              genuinely expands. ⚠ NOT currently load-bearing at
#                              any wired call site, and the honest note is worth
#                              more than the flattering one: removing this branch
#                              was DRIVEN and changed no verdict, because
#                              `_candidate_paths_from_bash` runs
#                              `_expand_simple_var_assignments` BEFORE masking, so
#                              `"${F}"` is already a literal path by the time the
#                              walker sees it. It reads as insurance for a future
#                              caller that masks before expanding -- do not cite it
#                              as the fix for any corpus attempt.
# What becomes TEXT:
#   ( ) { } ; | & < > newline #  inside single quotes, inside the inert part of
#   double quotes, inside a quoted-delimiter heredoc body, and after an unquoted `#`
#
# ⚠ NOT A BLANKET PRE-FILTER. The inline-interpreter extractors
# (_PYTHON_DASH_C_RE / _NODE_DASH_E_RE / _RUBY_DASH_E_RE / _PERL_DASH_E_RE) read a
# QUOTED SCRIPT BODY as their payload, and reading the BODY off the masked
# string fail-opens the writes inside it (its quotes and parens are what the
# inner patterns match). So the OPENER is matched on the masked string and the
# body is sliced from the raw command by offset -- see _inline_program_bodies
# (DEF-704), the discipline the stdin arm landed with (DEF-698).
#
# ⚠ NOT FOR THE POWERSHELL LEG. A posix lexer corrupts backslash paths into a
# fail-open; the PowerShell extractors keep raw input.

#: Characters that are shell syntax unquoted and inert text when quoted.
#: `$` and `\` are deliberately absent -- neither ever acts as a separator.
_INERTABLE_SYNTAX = frozenset("`(){};|&<>\n\r#")

#: Constructs that hand a heredoc body to a consumer the head roster can never
#: see: command substitution captures it into a buffer the ENCLOSING command
#: re-parses (`eval $(cat <<'EOF' ...)`), and a process substitution used as a
#: redirect target delivers it straight to a shell (`cat <<'EOF' > >(bash)`).
#: Neither consumer is a pipeline head, so no owner set can contain it. Matched
#: against everything BEFORE THE BODY -- which must include the operator line,
#: because `cat <<'EOF' > >(bash)` puts the process substitution AFTER the `<<`.
#: Scanning only up to the operator left exactly that shape open. Stopping at
#: the body rather than scanning the whole command is what keeps a documentation
#: heredoc whose BODY quotes a backtick relieved.
_CAPTURING_PREFIX_RE = re.compile(r"\$\(|`|[<>]\(")

#: Above this size the walker is skipped and the raw command returned. The scan
#: cap (_cap_for_scan) already trims to 32KB; this is the belt for callers that
#: reach the walker directly.
_ROLE_MAP_CAP = 64 * 1024


class _UnresolvedShellSyntax(Exception):
    """The walker met a construct it cannot resolve (unterminated quote/heredoc)."""


#: Commands that do NOT hand their quoted argument or heredoc body back to a shell
#: for re-parsing. ⚠ THIS IS AN ALLOWLIST AND THE DIRECTION IS THE WHOLE SAFETY
#: ARGUMENT. A quoted span is inert only if nothing re-parses it, and the set of
#: things that DO re-parse is open-ended -- `eval`, every `sh`/`bash`/`zsh`/`ksh`
#: /`dash -c`, `ssh`, `su -c`, `xargs sh -c`, `find -exec sh -c`, `watch`,
#: `docker run ... sh -c`, a heredoc or here-string piped into any shell, and the
#: next one someone invents. Enumerating THAT set fails open every time it is
#: incomplete. Enumerating this one fails toward friction: a benign command missing
#: here keeps today's false positive and costs a re-issue, which is the error this
#: whole pass exists to reduce and is still strictly the safer direction.
#:
#: `awk` (has `system()`), `python`/`node`/`ruby`/`perl` (all can shell out, and the
#: inline-interpreter extractors already read them RAW) and `git` (`submodule
#: foreach` runs a shell) are deliberately ABSENT.
#:
#: ⚠ A SECOND READER (2026-09-19): the glob relief's plain-command gate
#: (`_relief_applies`) counts a command plain only when every head is on this
#: roster, is a reader head, or is `_PLAIN_RELIEF_HEADS`. A name added here
#: also widens where a bare glob is read as the directory it runs in, so
#: `TestReliefAppliesToAPlainCommandOnly.test_the_plain_head_set_is_pinned`
#: reds until the widening is decided for both readers.
_NON_REPARSING_HEADS = frozenset({
    "echo", "printf", "cat", "grep", "egrep", "fgrep", "rg", "ag",
    "head", "tail", "wc", "sort", "uniq", "diff", "comm", "cut", "tr",
    "jq", "less", "more", "true", "false", "ls", "pwd", "date",
    "tee", "column", "fold", "nl", "rev", "basename", "dirname",
    # ── Added 2026-08-24, and `cd` is the whole reason ────────────────────
    # The roster is ALL-or-nothing: `mask_inert_syntax` returns the command RAW
    # unless EVERY top-level head word is here. So one `cd /tmp &&` prefix
    # disabled the entire pass, and `cd … &&` is the most common prefix an agent
    # writes. Measured: an identical heredoc body was ALLOWED behind `cat` and
    # REFUSED behind `cd /tmp && cat` -- the defence was real and one of the two
    # most common command shapes in this repo walked straight past it.
    #
    # Every name below is here on the same single test the roster has always
    # applied: CAN THIS COMMAND HAND AN ARGUMENT TO A SHELL? If yes it stays off,
    # whatever else is true of it. `cd`/`mkdir`/`touch` take operands and change
    # state; `test`/`[` evaluate an expression; the rest read or transform bytes.
    # None of them has an -exec, a -c, a system(), or a config hook that runs a
    # command. `find`, `xargs`, `env`, `timeout`, `nohup`, `watch`, `ssh`, `su`,
    # `docker` and `make` were all considered and REJECTED for the opposite
    # reason, alongside the standing `awk`/`sed`/`git`/`python` exclusions above.
    #
    # Direction of error, restated because it INVERTS for additions: a name
    # MISSING from this roster costs friction, but a name wrongly ADDED costs a
    # fail-open. So this list is not a guess -- bench/reachability_differential.py
    # re-runs against a real bash after every change here, and a `cd … &&`
    # wrapper is now in its matrix so this specific relief has to keep answering
    # to the shell.
    "cd", "mkdir", "rmdir", "touch", "test", "[", "sleep", "mktemp",
    "realpath", "readlink", "stat", "file", "du", "df",
    "md5sum", "shasum", "sha256sum", "cksum",
    "seq", "yes", "expr", "tac", "paste", "join", "numfmt", "od", "xxd",
    "strings", "expand", "unexpand",
    # ── Added 2026-09-05 with the DEF-638 permission-verb matcher. Same single
    # test: none of the three has an -exec, a -c, a system() or a hook that runs
    # a command; they read a mode/owner and operands. Off the roster the whole
    # pass returned RAW for a line headed by them, so `chmod "a;b" 000 <hook>`
    # kept its quoted `;` and the matcher's span stopped at it -- a one-token
    # decoy defeated the matcher (review, driven live).
    "chmod", "chown", "chgrp",
    # ── Added 2026-09-05 with DEF-695, on the same single test. `chflags` (BSD)
    # reads flags and operands; `chattr` reads attributes and operands (its
    # `-v`/`-p` take a number); `setfacl` reads an ACL spec from a flag or a
    # file (`-M`/`--restore`), never from a shell. Each has a live no-op row
    # in bench/guard_metamorphic.py `_HEAD_ARGS` on the platform that ships
    # it, and the bench now reports a head absent on the running platform
    # apart from one whose row is dead.
    "chflags", "chattr", "setfacl",
})

#: Words that open a shell for whatever follows them.
#:
#: ⚠ Blanked ONLY inside a command whose head words are all in
#: `_NON_REPARSING_HEADS`, i.e. one already proven not to hand its arguments to a
#: shell. Under that precondition an `eval` or `sh -c` in the string is
#: necessarily part of an ARGUMENT (the head-word scan runs at top level and steps
#: over quoted spans), so it cannot be a real command position and blanking it
#: cannot hide a live invocation.
#:
#: This is the one place the pass touches token content, and it is why prose that
#: quotes an exec form is no longer refused. The alternative -- anchoring
#: `_CMD_POS_EXEC_QUOTE`, whose unanchored arm is what creates the command
#: position -- was measured and REJECTED: it loses `find -exec sh -c`,
#: `ssh host '...'`, a flag-embedded `--wrap='eval ...'` and a `git` alias body
#: (four genuinely-executing shapes) to relieve three inert ones. Wrong trade.
_EXEC_OPENER_RE = re.compile(r"\b(?:eval|(?:ba|z|k|da)?sh[ \t]+-c)\b")

#: Prefix words that do not themselves consume the argument -- step over them and
#: keep looking for the real head.
_HEAD_SKIP_WORDS = frozenset({"command", "builtin", "time", "nice", "stdbuf"})

#: The heads whose PROGRAM is read for what it hands to a shell (447-A step
#: 3, §C5; the reader block below `_shell_program_bodies`). A reader head is
#: on the non-re-parsing side of rule (2) -- its quoted arguments, heredoc
#: bodies and comments are data -- and a head joins `_reader_family` only
#: with an executing row in `bench/reachability_differential.py` that runs
#: the idiom its reader knows. The versioned interpreters take a version
#: suffix (`python3.12`, `python3.13t`, `pypy3`, `perl5`, `ruby3.2`); the
#: rest are spelled out. String tests, not a regex: a pattern naming `git`
#: would enrol in the git-regex census, which wants an anchor this test --
#: applied to a head word the walker already isolated -- has no use for.
_READER_HEAD_VERSIONED = (("python", "python"), ("pypy", "python"),
                          ("perl", "perl"), ("ruby", "ruby"))
_READER_HEAD_SPELLED = {
    "node": "node", "nodejs": "node",
    "awk": "awk", "gawk": "awk", "mawk": "awk", "nawk": "awk",
    "sed": "sed", "gsed": "sed",
    "git": "git",
}
#: The families a reader exists for: the four whose PROGRAM BODY is read
#: (`_shell_outs_in`) and the three whose STATEMENT is read
#: (`_awk_shell_out_texts`, `_sed_shell_out_texts`, `_git_program_bodies`).
#: THE ENROLMENT CONTRACT, stated by both reviews of the step that added the
#: tables: joining `_reader_family` costs the raw-scan catch on EVERY door a
#: head has, so a head joins only when each of its shell-out doors has a
#: reader and an executing row in `bench/reachability_differential.py` or a
#: declared limit in `docs/HOOKS.md` -- one door's row vouches for nothing but
#: itself (the first cut read git's `-c` and `config` doors and lost
#: `submodule foreach`, `rebase --exec` and `filter-branch`; driven with a
#: marker before the doors were added).
_BODY_READER_FAMILIES = frozenset({"python", "perl", "node", "ruby"})
_STATEMENT_READER_FAMILIES = frozenset({"awk", "sed", "git"})
_READER_FAMILIES = _BODY_READER_FAMILIES | _STATEMENT_READER_FAMILIES
if not ({f for f in _READER_HEAD_SPELLED.values()}
        | {f for _, f in _READER_HEAD_VERSIONED}) <= _READER_FAMILIES:
    # `raise`, not `assert`: a head naming a family no reader handles would
    # take rule (2)'s relief and yield nothing, silently -- the drift the
    # sibling tables above refuse the same way.
    raise RuntimeError(
        "reader head roster drift: a head names a family no reader handles"
    )
#: The spellings the metamorphic bench walks as reader heads (R1 in
#: `bench/guard_metamorphic.py`): the spelled table's keys and the bare and
#: `3` forms of the versioned prefixes, each with its own `_HEAD_ARGS` row.
_READER_HEAD_SPELLINGS = frozenset(_READER_HEAD_SPELLED) | frozenset({
    "python", "python3", "pypy", "pypy3", "perl", "ruby",
})
#: The longest head spelling the family test admits; folded into the walker's
#: length cap so `python3.12` is recorded as a word rather than as the sentinel.
_READER_HEAD_LEN_CAP = 16


def _reader_family(head: str) -> str | None:
    """The reader a head word dispatches to (`python`, `perl`, `node`, `ruby`,
    `awk`, `sed`, `git`), or None for a head that has none. A versioned
    prefix takes digits and dots, and the free-threaded `t` only after a
    version (`python3.13t`; a bare `pythont` is nothing)."""
    if not head or len(head) > _READER_HEAD_LEN_CAP:
        return None
    spelled = _READER_HEAD_SPELLED.get(head)
    if spelled is not None:
        return spelled
    for prefix, family in _READER_HEAD_VERSIONED:
        if head.startswith(prefix):
            suffix = head[len(prefix):]
            if suffix.endswith("t") and len(suffix) > 1:
                suffix = suffix[:-1]
            if all(ch.isdigit() or ch == "." for ch in suffix):
                return family
    return None


def _head_hands_nothing_to_a_shell(head: str) -> bool:
    """Rule (2)'s test, per head: on `_NON_REPARSING_HEADS`, or a reader head
    whose shell-outs are read instead of scanned by accident."""
    return head in _NON_REPARSING_HEADS or _reader_family(head) is not None


#: The longest word either roster above can match. A head word longer than this
#: is on neither, so the walker can stand a sentinel in for it instead of
#: building the string (DEF-754: see the head capture in `_walk_shell_roles`).
#: The reader heads' cap joins the maximum: a `python3.12` cut to the sentinel
#: would be an unrostered head, and its program would go unread.
_MAX_ROSTERED_HEAD_LEN = max(
    max(len(w) for w in _NON_REPARSING_HEADS | _HEAD_SKIP_WORDS), _READER_HEAD_LEN_CAP,
)

#: Stands in, inside `heads` and a pipeline's owner set, for a head word that is
#: longer than any rostered word: on no roster, exactly like the word it
#: replaces, and never a real command name (a NUL cannot appear in one).
_UNROSTERED_HEAD = "\x00unrostered"


def mask_inert_syntax(command: str) -> str:
    """Return `command` with literal-by-position syntax characters spaced out.

    Same length, same offsets, same token content.

    ⚠ FAILS CLOSED TWICE OVER, and the second one was learned the hard way.
    (1) On any construct the walker cannot resolve it returns the raw command.
    (2) On any command whose head words are not ALL non-re-parsing -- on
    :data:`_NON_REPARSING_HEADS`, or a READER head whose program is read for
    its shell-out calls (`_reader_family`, 447-A step 3) -- it returns the
    raw command -- except for the spans of the STATEMENTS that are
    non-re-parsing, which come back masked:
    a quoted-delimiter heredoc body (since 2026-08-24), a quoted argument or a
    comment (since 2026-09-11, the Bash trio's per-statement step). The rule
    is read per statement, never per command: see the rule-(2) branch below.

    Rule (2) exists because the first version of this pass had a false premise:
    that a separator inside a quoted span is inert. It is inert *for the current
    shell* -- but `eval "ls; <delete> /"`, `bash -c "cd /tmp; <delete> /"` and
    `bash <<'EOF'` hand that span to a shell that RE-PARSES it, so those separators
    are live. Spacing them out deleted the command position of every statement
    after the first. Measured against a real-bash reachability oracle (bash truly
    deleted a real victim): **63 of 140 wrapper x body combinations flipped
    DENY -> ALLOW**, on the tier `ESPALIER_MAINTENANCE_MODE=1` cannot bypass.

    None of it was visible to the 80-row regression file or to the 154/154 release
    benchmark, because every hand-written exec-quote row used a SINGLE-statement
    body -- and a single statement has no separator to lose. The gate is
    differential fuzzing against the shell itself, not a roster.
    """
    if not command or len(command) > _ROLE_MAP_CAP:
        return command
    try:
        masked, heads, safe_spans = _walk_shell_roles(command)
    except (_UnresolvedShellSyntax, IndexError):
        return command
    if not heads or any(not _head_hands_nothing_to_a_shell(h) for h in heads):
        # Rule (2) failed -- but it is a property of the COMMAND, and a quoted
        # heredoc body is a property of ITS OWN STATEMENT. An identical body was
        # ALLOWed bare and denied the moment `python3 n.py` followed the
        # terminator, because this gate was all-or-nothing over the union of
        # heads. Write-a-script-then-run-it is among the commonest shapes in
        # this repo and maintenance mode does not relieve it.
        #
        # THE ENFORCED CONTRACT, stated as what the code actually checks --
        # an earlier version of this comment claimed only "the body is inert
        # data handed to this statement's stdin", which is broader than the
        # code's reach in two ways bash really exercises, and all three routes
        # below shipped as fail-opens under it. A span is recorded only when:
        #
        #   1. the delimiter is QUOTED (no expansion), and
        #   2. every head in the heredoc's own PIPELINE -- the owner set held by
        #      reference from the `<<` operator, which a `|` extends and a
        #      statement separator cannot replace -- is non-re-parsing, and
        #   3. the operator and the terminator both sit at group/subshell depth
        #      0, because a consumer can attach after the terminator, and
        #   4. nothing before the body opens a command substitution or a process
        #      substitution, because those deliver the body to a consumer that
        #      is never a head and no roster can see.
        #
        # This does NOT widen the threat model, and that was measured rather
        # than assumed: file-mediated execution is already out of scope. Driven
        # against a real bash, the `echo`, `printf`, `sh` and `tee` spellings of
        # "write a script then run it" all delete a real victim and are all
        # ALLOWED today. The heredoc spelling was denied only as a side effect
        # of this gate, never by policy, so scoping it per-statement makes the
        # guard consistent rather than opening a route.
        #
        # THE SAME RULE FOR A QUOTED ARGUMENT AND A COMMENT (2026-09-11, the
        # Bash trio's per-statement step). `echo "true; <delete>"; python3 -c pass` was
        # refused and `echo "true; <delete>"` was not: the roster was read
        # over the UNION of every statement's heads, so one interpreter
        # anywhere in the command turned the mask off for text that an
        # on-roster statement owned outright (the differential's 18
        # cross-statement mention rows, and the two exec-quote bodies of its
        # write-then-run row). Recorded by the walker and settled AFTER the
        # walk, when every by-reference owner set is final
        # (`_settle_statement_spans`), a span is kept masked only when:
        #
        #   a. for a quoted span, every head of ITS OWN PIPELINE -- the same
        #      by-reference set a heredoc holds -- is non-re-parsing (a
        #      comment needs no head: the shell drops it before any head
        #      reads its arguments), and
        #   b. it sits at group/subshell depth 0, because `{ echo "…"; } |
        #      sh` pipes the GROUP and no owner set inside it can see the
        #      shell, and
        #   c. its statement's MASKED text holds no command or process
        #      substitution -- ``x=`echo "…"`; eval "$x"`` captures the span
        #      for a consumer that is never a head, `echo "…" > >(sh)` hands
        #      it to one; the masked text is read so a substitution quoted
        #      INSIDE the span is already blank and a live one, inside the
        #      span or beside it, still shows.
        #
        # Inside a kept span an exec opener is argument text -- the argument
        # the whole-command path below makes, scoped to the span -- so it is
        # blanked too; that is what relieves `echo "eval '…'"; python3 x`.
        # The walker's own masked text is spliced over each span rather than
        # re-blanked from the raw command: a double-quoted span keeps a live
        # `$(…)` unmasked, and a blanket pass over the raw text would hide it.
        if not safe_spans:
            return command
        out = list(command)
        for start, stop in safe_spans:
            stop = min(stop, len(command))
            out[start:stop] = _EXEC_OPENER_RE.sub(
                lambda m: " " * len(m.group(0)), masked[start:stop],
            )
        return "".join(out)
    # Every head word is known not to re-parse, so an exec opener here can only be
    # argument text. Same-length substitution keeps offsets intact.
    return _EXEC_OPENER_RE.sub(lambda m: " " * len(m.group(0)), masked)


def _walk_shell_roles(s: str) -> tuple[str, set[str], list[tuple[int, int]]]:
    """Return (masked_string, head_words_of_every_top_level_command,
    safe_spans) -- the third is every [start, end) range whose masking
    survives rule (2) of `mask_inert_syntax`."""
    out = list(s)
    i, n = 0, len(s)
    heads: set[str] = set()
    expect_head = True
    #: Every head in the PIPELINE being parsed right now, as opposed to
    #: `heads`, which is the union over the whole command. A heredoc body
    #: belongs to its own pipeline -- not to whatever else the command goes on
    #: to do, and not merely to the statement that opened it, because a pipe
    #: carries that body into every downstream head.
    current_pipeline: set[str] = set()
    #: Group/subshell depth. A heredoc opened inside `{ … }` or `( … )` can be
    #: consumed by something attached AFTER the terminator, which no owner set
    #: can see, so a span is only ever recorded at depth 0.
    nesting = 0
    #: [start, end) ranges blanked inside a QUOTED-delimiter heredoc body whose
    #: own statement head is non-re-parsing. These stay masked even when some
    #: other statement in the command is unrecognised -- see `mask_inert_syntax`.
    safe_spans: list[tuple[int, int]] = []
    #: Every quoted span and comment met at the top level, with the pipeline
    #: that owns it (BY REFERENCE, exactly as a heredoc holds its owner), the
    #: group depth it sat at, the statement it belongs to, whether it is a
    #: comment, and whether it is a quoted piece of an ASSIGNMENT value
    #: (DEF-848) -- a `_SpanCandidate`, its two flags passed by keyword at
    #: every site. Settled after the walk, once every owner set is final, by
    #: `_settle_statement_spans` -- a pipe after the span still extends the
    #: set it holds.
    candidates: list[_SpanCandidate] = []
    #: [start, end) of every statement in walk order: what lies between two
    #: rebinds of `current_pipeline`. The separator that ends a statement is
    #: INSIDE it, so `> >(sh)` reads whole when the `(` is the rebind.
    statements: list[list[int]] = [[0, n]]
    #: A single `|` (or `|&`) has been read and no word has followed it yet.
    #: bash continues the pipeline across the newline that follows -- and
    #: across a trailing comment, a blank line and a heredoc body in between
    #: (driven 2026-09-11 on /bin/bash 3.2, a marker written by the second
    #: line) -- so the newline branch must not rebind the owner set while
    #: this is set. An assignment-only line ends it (driven: the line after
    #: it was NOT the pipe's target).
    pipe_pending = False
    # (delimiter, expands, strip_tabs, owner_set_BY_REFERENCE, depth_at_operator)
    pending: list = []
    #: The last word the head capture scanned, as `_scan_head_word` returned
    #: it: where it started and ended in `s`, its quote-and-backslash-stripped
    #: text, the map from each raw offset inside it to the stripped offset, and
    #: the last `/` and `=` in the stripped text. A capture armed at a position
    #: INSIDE that word derives what a read from there returns from these, in
    #: constant time -- see the capture below (DEF-754).
    span_start = span_after = -1
    span_buf = ""
    span_at: list[int] = []
    span_last_slash = span_last_eq = -1

    def neutralise(a: int, b: int, keep_newline: bool = False) -> None:
        for k in range(a, b):
            if s[k] in _INERTABLE_SYNTAX:
                if keep_newline and s[k] in "\n\r":
                    continue
                out[k] = " "

    def step_over_assignment(a: int) -> int:
        """The index past the assignment word at ``a``, where bash ends it:
        the first blank or separator OUTSIDE a quote. Each quoted piece of
        the value -- single, double, ANSI-C -- is masked as the top-level
        quote branches mask one and recorded as a VALUE span of the current
        statement (DEF-848); a backslash escapes the next character, and an
        escaped separator is blanked as the top-level branch blanks one. A
        `$(` or a backtick is an ordinary character here, as it was: the
        word still stops at the first blank inside one, and
        `_depth_after_step_over` counts its parenthesis. An unterminated
        quote raises, as the top-level branches do."""
        k = a
        while k < n and s[k] not in " \t\n\r;|&<>":
            c = s[k]
            if c == "\\":
                if k + 1 < n and s[k + 1] in _INERTABLE_SYNTAX and s[k + 1] not in "\n\r":
                    out[k + 1] = " "
                k += 2
                continue
            if c == "'":
                j = s.find("'", k + 1)
                if j < 0:
                    raise _UnresolvedShellSyntax("unterminated single quote")
                neutralise(k + 1, j)
                lo = k + 1
            elif c == '"':
                j = _close_double_quote(s, k)
                _neutralise_expanding_span(s, out, k + 1, j)
                lo = k + 1
            elif c == "$" and k + 1 < n and s[k + 1] == "'":
                j = _close_ansi_c_quote(s, k + 1)
                neutralise(k + 2, j)
                lo = k + 2
            else:
                k += 1
                continue
            candidates.append(_SpanCandidate(lo, j, current_pipeline, nesting,
                                             len(statements) - 1,
                                             is_comment=False, is_value=True))
            k = j + 1
        return k

    while i < n:
        c = s[i]

        # Head-word capture. Runs BEFORE the span branches so a quoted verb
        # (`'rm' -rf /`) is still seen as the head. Does not advance `i` -- the
        # branches below still process these characters normally.
        if expect_head and c not in " \t" and i < span_after:
            # ⚠ THE RE-ARM CAME FROM A GROUPING CHARACTER GLUED INSIDE THE WORD
            # JUST SCANNED. `_scan_head_word` stops on blanks and on `;|&<>`,
            # not on `(){}`, so `((((cmd` is scanned whole at the first paren;
            # the paren branch below then re-arms the capture, and the next
            # position would scan `(((cmd` -- the same word minus one
            # character -- then `((cmd`, and so on: one full scan per opener,
            # quadratic (measured 2026-09-10 on the self-host box: 53 ms at
            # 1 KB, 3.3 s at 8 KB, about 53 s at the 32 KB command cap, and the
            # walker's own bound is 64 KB), ahead of every tier (DEF-754). A
            # run of `#` behind a glued `{` or `}` paid the same way through
            # the comment branch below, which scans and stays armed.
            #
            # A read from a position inside the scanned word yields a SUFFIX of
            # its stripped text (the lexing is context-free: quotes are skipped
            # and a backslash escapes the next character, from wherever the
            # read starts), so every branch of the read below can be decided
            # here from the stored scan in constant time, and the flow and the
            # sets it produced are reproduced exactly -- an env-assignment
            # suffix steps over the word, a skip word steps over it, a `#`
            # leaves the capture armed, an empty basename steps over it, and a
            # real word is recorded in `heads` and in the pipeline current at
            # THIS position (the grouping branch rebound it, and a later `|`
            # can extend that same set to a heredoc's owner: review, driven)
            # before the capture disarms. The one representational change: a
            # suffix longer than any rostered word is recorded as
            # `_UNROSTERED_HEAD` rather than built, which is on no roster
            # exactly as the string would be, so neither predicate the sets
            # feed can tell them apart; a suffix short enough to be rostered is
            # recorded as itself. Proven by the oracle, not by this argument:
            # the 360-shape Bash differential against the unfixed walker moved
            # no verdict, and the masker gate pins the sets for the glued
            # shapes both reviews named.
            m = span_at[i - span_start]
            if c in "\n\r;|&<>":
                # an escaped terminator: a read here consumes nothing (the
                # progress guard's case below) and the capture stays armed
                pass
            elif span_last_eq >= m:
                nesting = _depth_after_step_over(s, i, span_after, nesting)
                pipe_pending = False
                i = span_after
                continue
            else:
                base = span_last_slash + 1 if span_last_slash >= m else m
                if base >= len(span_buf):
                    nesting = _depth_after_step_over(s, i, span_after, nesting)
                    pipe_pending = False
                    i = span_after
                    continue
                if span_buf[base] == "#":
                    pass
                else:
                    rec = (span_buf[base:] if len(span_buf) - base <= _MAX_ROSTERED_HEAD_LEN
                           else _UNROSTERED_HEAD)
                    if rec in _HEAD_SKIP_WORDS:
                        nesting = _depth_after_step_over(s, i, span_after, nesting)
                        pipe_pending = False
                        i = span_after
                        continue
                    heads.add(rec)
                    current_pipeline.add(rec)
                    expect_head = False
                    pipe_pending = False
        elif expect_head and c not in " \t":
            span_buf, after, span_at = _scan_head_word(s, i)
            if after > i:
                span_start, span_after = i, after
                span_last_slash, span_last_eq = span_buf.rfind("/"), span_buf.rfind("=")
            word = "" if "=" in span_buf else span_buf.rsplit("/", 1)[-1]
            if after <= i:
                # ⚠ PROGRESS GUARD, AND IT IS LOAD-BEARING. `_read_head_word`
                # stops ON its terminator set, so when `c` is itself `&`, `;`,
                # `|`, `<` or `>` it consumes nothing and returns the same index.
                # The first cut did `i = after; continue` unconditionally, which
                # spun forever on the second `&` of any `cd x && ls`. The hook
                # carries a 5-second timeout in settings.json, so the wedge did
                # not merely hang -- it FAILED OPEN on every `&&` command, and
                # took the release benchmark from 154/154 to 150/154 on four
                # TimeoutExpired rows. Leave `expect_head` armed and let the
                # branches below advance `i` normally.
                pass
            elif word in _HEAD_SKIP_WORDS:
                nesting = _depth_after_step_over(s, i, after, nesting)
                pipe_pending = False
                i = after
                continue
            elif word.startswith("#"):
                # A comment is not a command. Leave `expect_head` armed so the
                # next real statement is the one that gets classified -- without
                # this, `# note\nls` reported a head of `#`, matched nothing on
                # the allowlist, and lost comment masking entirely.
                pass
            elif word:
                heads.add(word)
                current_pipeline.add(word)
                expect_head = False
                pipe_pending = False
            else:
                # An inline `VAR=value` prefix. Step over it and keep looking:
                # `FOO=1 echo hi` must classify as `echo`, not as nothing.
                #
                # ⚠ A STEP-OVER SKIPS THE GROUPING CHARACTERS INSIDE THE WORD.
                # `x=$(echo` is one word to the scan (it stops at the blank),
                # so the `(` that opens the substitution never reaches the
                # grouping branch below and `nesting` stayed 0 for everything
                # up to the `)` -- a separator inside the substitution then
                # opened a statement of its own, and a quoted span there
                # passed both the depth and the capture reads of the rule-(2)
                # settle (failure-mode review, driven live 2026-09-11). Every
                # step-over now carries the word's net depth change forward.
                #
                # ⚠ THE WORD ENDS AT THE FIRST UNQUOTED BLANK (DEF-848).
                # `_scan_head_word` stops at a blank or a separator INSIDE a
                # quote too, so `MSG='fix: x'` was stepped over as `MSG='fix:`:
                # the value's next word was recorded as a head and its closing
                # quote read as an opening one, the walk raised, and the whole
                # command came back raw -- a separator inside the value stayed
                # live. `step_over_assignment` walks to where bash ends the
                # word, masking and recording each quoted piece of the value.
                end = step_over_assignment(i)
                nesting = _depth_after_step_over(s, i, end, nesting)
                pipe_pending = False
                i = end
                continue

        if c == "\\":
            # A backslash-escaped character is LITERAL, so an escaped separator
            # is not a command position. Stepping over both without blanking
            # left an escaped separator live: driven against a real /bin/bash,
            # `echo a\\; <delete>` printed `a; <delete>` and the victim stood,
            # while the guard denied it. This was the last type-(b) residue in
            # an otherwise span-masked pass.
            #
            # WARNING: A LINE TERMINATOR IS EXCLUDED ON PURPOSE. A backslash
            # before a newline is a LINE CONTINUATION, and `mask_inert_syntax`
            # runs BEFORE `splice_line_continuations` (see its caller). Blanking
            # that newline stops the splice firing, so a continued
            # `<delete> \\<newline> /` would never rejoin and its catastrophic
            # operand would go unread -- friction traded for a fail-open. Blank
            # the ESCAPED character, never the backslash: the backslash is not
            # in the separator class, so blanking it would change nothing.
            if i + 1 < n and s[i + 1] in _INERTABLE_SYNTAX and s[i + 1] not in "\n\r":
                out[i + 1] = " "
            i += 2
            continue

        if c == "'":
            j = s.find("'", i + 1)
            if j < 0:
                raise _UnresolvedShellSyntax("unterminated single quote")
            neutralise(i + 1, j)
            candidates.append(_SpanCandidate(i + 1, j, current_pipeline, nesting,
                                             len(statements) - 1,
                                             is_comment=False, is_value=False))
            i = j + 1
            continue

        if c == '"':
            j = _close_double_quote(s, i)
            _neutralise_expanding_span(s, out, i + 1, j)
            candidates.append(_SpanCandidate(i + 1, j, current_pipeline, nesting,
                                             len(statements) - 1,
                                             is_comment=False, is_value=False))
            i = j + 1
            continue

        if c == "$" and i + 1 < n and s[i + 1] == "'":
            j = _close_ansi_c_quote(s, i + 1)
            neutralise(i + 2, j)
            candidates.append(_SpanCandidate(i + 2, j, current_pipeline, nesting,
                                             len(statements) - 1,
                                             is_comment=False, is_value=False))
            i = j + 1
            continue

        if c == "#" and _opens_comment(s, i):
            j = s.find("\n", i)
            j = n if j < 0 else j
            # ⚠ START AT i+1 -- the `#` ITSELF MUST SURVIVE. Blanking it was a real
            # defect: `_CMD_POS` matches a separator followed by `_CMD_POS_WS`
            # (`[ \t\r\v\f]*`), so a blanked `#` leaves an unbroken whitespace run
            # from the `;` straight to the comment's first word, and
            # `true; # <delete literal>` was still hard-denied. A surviving `#` is
            # in neither the separator class nor the whitespace class, so it ends
            # the run — the same way an ordinary prose word does, which is why a
            # comment that began with prose was already allowed and one that began
            # with the trigger was not. Found by an adversarial pass, not by
            # reading, and not by the 54 tests that were green at the time: every
            # comment row in them happened to start with a prose word.
            neutralise(i + 1, j, keep_newline=True)
            candidates.append(_SpanCandidate(i + 1, j, current_pipeline, nesting,
                                             len(statements) - 1,
                                             is_comment=True, is_value=False))
            i = j
            continue

        if c == "<" and i + 1 < n and s[i + 1] == "<":
            i, spec = _read_heredoc_operator(s, i)
            if spec is not None:
                # ⚠ CAPTURE THE OWNER SET BY REFERENCE, AND NEITHER BY VALUE NOR
                # AT CONSUME TIME. Both of those were tried and both were
                # fail-opens, in opposite directions:
                #
                #   by value at the operator  -- `cat <<'EOF' | bash` reads the
                #       operator before `| bash` exists, so the snapshot held
                #       only `cat` and the body was masked into a shell.
                #   at consume time           -- `bash <<'EOF' && ls` discards
                #       `bash` at the `&&` and lets `ls` vouch for a script bash
                #       really executes. Driven: 23 shapes went DENY -> ALLOW,
                #       six of them writing a kill switch into settings or
                #       overwriting write_guard.py itself.
                #
                # A reference gets both: `|` keeps mutating this same set, so a
                # downstream shell still joins it, while a statement separator
                # REBINDS `current_pipeline` to a fresh set and leaves this
                # heredoc pointing at the owner it actually had.
                #
                # `nesting` and the prefix scan close the two routes that reach
                # a shell without ever being a pipeline head -- see the consume
                # site below.
                pending.append((*spec, current_pipeline, nesting))
            continue

        if c == "\n":
            if pending:
                # ⚠ This newline OPENS a heredoc body; it does not separate two
                # commands (the next command starts after the terminator). Left
                # syntactic it puts the body's first line at a command position,
                # which is how a ```-fenced block inside a <<'EOF' body was still
                # read as an invocation.
                out[i] = " "
            i += 1
            while pending:
                delim, expands, strip_tabs, owners, op_depth = pending.pop(0)
                body_start = i
                i, body_end = _consume_heredoc_body(
                    s, out, i, delim, expands, strip_tabs, neutralise,
                )
                # A QUOTED delimiter means bash performs no expansion, so the
                # body is inert data handed to this statement's stdin. If that
                # statement's own head does not re-parse, the body cannot become
                # code no matter what the REST of the command does.
                #
                # ⚠ THE SPAN STOPS AT THE TERMINATOR LINE, NOT PAST IT. Reaching
                # one character further would blank the newline that separates
                # the heredoc from whatever follows, and `...EOF\n<delete> /`
                # would lose the command position of live code -- relief traded
                # for a fail-open, which is this surface's signature mistake.
                # ⚠ THE OWNER READ IS NOT MADE HERE. It was, and `cat <<'EOF' |`
                # newline, body, terminator, `bash` re-parsed its body (driven
                # 2026-09-11): the pipe's target joins the owner set AFTER the
                # terminator, so a read at consume time saw `{cat}` alone.
                # The body is recorded as a candidate and its owners are read
                # once the walk is over, by `_settle_statement_spans`.
                if (
                    not expands
                    # ⚠ DEPTH 0 AT BOTH ENDS. Inside a group or a subshell the
                    # consumer can attach AFTER the terminator, where no head is
                    # in the owner set yet: `{ cat <<'EOF' … EOF` newline `} |
                    # bash` really executes and was ALLOWed. The single-line twin
                    # `{ cat <<'EOF' ; } | bash` was already denied, and that
                    # asymmetry is the tell -- same mistake, displaced past the
                    # terminator instead of past the pipe.
                    and op_depth == 0
                    and nesting == 0
                    # ⚠ AND THE BODY MUST NOT BE CAPTURED BY A SUBSTITUTION OR
                    # HANDED TO A PROCESS SUBSTITUTION. `eval $(cat <<'EOF' …)`
                    # delivers it to a capture buffer the ENCLOSING eval
                    # re-parses, and `cat <<'EOF' > >(bash) ; ls` delivers it to
                    # a redirect target that is a shell. Neither consumer is ever
                    # a head, so the roster cannot see either one. Scoped to the
                    # statement prefix, not the whole command, so a doc heredoc
                    # whose BODY quotes a backtick stays relieved.
                    and not _CAPTURING_PREFIX_RE.search(s[:body_start])
                ):
                    # Reach back over the ONE newline that opens the body. It
                    # ends the heredoc's own opening statement, so nothing live
                    # sits at it -- and leaving it out was measured to relieve
                    # nothing at all: the body's first line stayed at a command
                    # position and the false positive survived the fix.
                    body_span_start = body_start
                    if body_span_start > 0 and s[body_span_start - 1] in "\n\r":
                        body_span_start -= 1
                    candidates.append(_SpanCandidate(
                        body_span_start, body_end, owners, 0, len(statements) - 1,
                        is_comment=False, is_value=False))
            # ⚠ A NEWLINE IS A STATEMENT SEPARATOR AND MUST RE-ARM HEAD CAPTURE.
            # It did not, so in a multi-line command only the FIRST statement's
            # head was ever collected -- and `mask_inert_syntax` masks whenever
            # every head it collected is non-re-parsing. One safe first line
            # therefore vouched for every line after it.
            #
            # Latent until 2026-08-24, when `cd`/`mkdir`/`touch`/`test` joined
            # the roster and made the most common prefix in this repo a key to
            # it. Driven against a real bash, `cd /tmp\nbash <<'EOF'\n<delete>\nEOF`
            # went DENY -> ALLOW and the shell really did remove the victim; the
            # same shape overwrote `tools/cc/hooks/write_guard.py` and wrote
            # `{"disableAllHooks": true}` into `.claude/settings.json` -- a
            # kill-switch past the hook whose stated job is to prevent one.
            #
            # ⚠ AND THE GATE COULD NOT SEE IT. All four `cd` wrappers added to
            # bench/reachability_differential.py that day used `cd /tmp && …`,
            # and `&&` is in the `;|&(){}` class below, so it re-armed and stayed
            # DENY. The oracle certified the safe variant of the broken shape.
            # Newline-separated wrappers are in that matrix now, because a `&&`
            # row is structurally incapable of failing here.
            #
            # Placed AFTER the heredoc-body loop on purpose: a newline that OPENS
            # a body must not arm the body's first line as a command position.
            expect_head = True
            if pipe_pending:
                # ⚠ THE PIPELINE IS STILL OPEN. A newline after a lone `|`
                # (or `|&`) is not a statement boundary to bash: the next
                # word is the pipe's target and must JOIN this owner set, not
                # start a fresh one. Rebinding here left `echo "…" |` newline
                # `sh` with `{echo}` as the span's owner -- the ampersand
                # defect of this same step, displaced to the newline (code
                # review, driven live 2026-09-11). The newline stays live in
                # the masked text: the target is at a command position.
                continue
            current_pipeline = set()
            # `i` is past any heredoc body the newline opened, so the bodies
            # belong to the statement that opened them.
            statements[-1][1] = i
            statements.append([i, n])
            continue

        if c == "&" and _is_redirect_dup_ampersand(s, i):
            # ⚠ THE AMPERSAND OF A REDIRECT-DUPLICATION OPERATOR IS NOT A
            # SEPARATOR. `2>&1`, `>&2`, `<&0`, `&>f`, `&>>f` and the bash-4
            # pipe `|&` all carry one, and the branch below read every `&` as
            # a statement boundary: it re-armed the head capture and REBOUND
            # the pipeline's owner set, so in `cat <<'EOF' 2>&1 | bash` the
            # shell joined a fresh set while the body still pointed at `{cat}`
            # -- and was masked into the shell that runs it. Both pipe
            # spellings ALLOWED at 6b128c0, driven live 2026-09-11 with
            # maintenance mode stripped; the differential carries `2>&1 |` as
            # an executing row (this host's /bin/bash predates `|&`). Step
            # over the character: no re-arm, no rebind, no depth change.
            i += 1
            continue

        if c in ";|&(){}":
            expect_head = True
            if c in "({":
                nesting += 1
            elif c in ")}":
                nesting = max(0, nesting - 1)
            # ⚠ A SINGLE `|` DOES NOT END THE PIPELINE, AND THAT DISTINCTION IS
            # A FAIL-OPEN. `cat <<'EOF' | bash` opens the heredoc under `cat`,
            # which is on the roster -- but the body flows down the pipe into a
            # shell that RE-PARSES it, so the pipe must keep extending the SAME
            # owner set rather than starting a new one. `||` is a statement
            # separator, not a pipe, so it rebinds.
            #
            # REBIND, never `.clear()`: a pending heredoc holds a reference to
            # the set it was opened under, and clearing in place would empty the
            # owner out from under it.
            # A lone `|` opens a pipe whose target may sit on the next line
            # (see `pipe_pending`); the second bar of `||` is not one.
            pipe_pending = (c == "|"
                            and not (i + 1 < n and s[i + 1] == "|")
                            and not (i > 0 and s[i - 1] == "|"))
            if c != "|" or (i + 1 < n and s[i + 1] == "|"):
                current_pipeline = set()
                statements[-1][1] = i + 1
                statements.append([i + 1, n])

        i += 1

    masked = "".join(out)
    _settle_statement_spans(masked, candidates, statements, safe_spans)
    return masked, heads, safe_spans


def _is_redirect_dup_ampersand(s: str, i: int) -> bool:
    """`s[i]` is the `&` of a redirect-duplication operator or of the bash-4
    pipe `|&`: glued to a `|`, `<` or `>` before it, or to a `>` after it
    (`&>`, `&>>`). Neither `&&` nor a background `&` is."""
    return (i > 0 and s[i - 1] in "|<>") or (
        i + 1 < len(s) and s[i + 1] == ">" and not (i > 0 and s[i - 1] == "&"))


def _depth_after_step_over(s: str, a: int, b: int, nesting: int) -> int:
    """`nesting` after the head capture steps over the raw word `s[a:b]`
    without visiting its characters: every grouping character the grouping
    branch would have counted, counted here instead. A backslash escapes the
    next character; nothing inside single quotes counts; inside double quotes
    only a `$(` and the parentheses of the substitution it opens count (a
    bare `(` there is text). A closer never takes the depth below zero, as
    the grouping branch's own clamp does. Linear in the word: each raw
    character is stepped over at most once."""
    depth = nesting
    quote: str | None = None
    subst = 0
    i = a
    while i < b:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if quote == "'":
            if c == "'":
                quote = None
        elif quote == '"':
            if c == "$" and i + 1 < b and s[i + 1] == "(":
                subst += 1
                depth += 1
                i += 2
                continue
            if subst and c == "(":
                subst += 1
                depth += 1
            elif subst and c == ")":
                subst -= 1
                depth = max(0, depth - 1)
            elif c == '"' and not subst:
                quote = None
        elif c == "'":
            quote = "'"
        elif c == '"':
            quote = '"'
        elif c in "({":
            depth += 1
        elif c in ")}":
            depth = max(0, depth - 1)
        i += 1
    return depth


class _SpanCandidate(NamedTuple):
    """One quoted span, comment or assignment-value piece the walker met,
    with the pipeline that owns it (BY REFERENCE: a later pipe extends the
    set, and the settle keys on its identity), the group depth it sat at and
    its statement. Built with the two flags by KEYWORD at every site: a
    positional pair of adjacent booleans swaps silently and still
    type-checks (the failure-mode review)."""
    start: int
    end: int
    owners: set[str]
    depth: int
    statement: int
    is_comment: bool
    is_value: bool


def _settle_statement_spans(
    masked: str,
    candidates: list[_SpanCandidate],
    statements: list[list[int]],
    safe_spans: list[tuple[int, int]],
) -> None:
    """Append to `safe_spans` every recorded quoted span or comment that is
    inert data of a statement handing it to nobody -- the rule-(2) contract
    in `mask_inert_syntax` (a, b, c). Runs after the walk on purpose: an
    owner set is held by reference and a pipe after the span still extends
    it, so the earliest moment the read is correct is the end. Each owner
    set and each statement is judged once, whatever the number of spans:
    a 64 KB command of quoted spans in one pipeline stays linear (the
    DEF-754 discipline).

    An assignment VALUE whose pipeline has no head at all (DEF-848) is
    handed to nobody: the statement only stores it in the current shell, so
    it is data by (a) without a roster read -- a quoted argument or a
    redirect target with no head keeps the read it had (no owner, no
    relief). A value that prefixes a head, or whose statement a pipe
    extends to one, is judged by its owners like any quoted argument; (b)
    and (c) hold for every kind. A value the shell later RUNS (`eval
    "$MSG"`, `bash -c "$msg"`, `$CMD`) is read where it runs: the binding
    pre-pass substitutes it at the use."""
    # Keyed by `id(owners)`: sound only because `candidates` holds a strong
    # reference to every owner set for the whole settle, so no id is reused.
    # A refactor that stores an index or a copy instead must key differently.
    rostered: dict[int, bool] = {}
    capturing: dict[int, bool] = {}
    for c in candidates:
        if c.depth != 0:
            continue
        if not c.is_comment and not (c.is_value and not c.owners):
            key = id(c.owners)
            if key not in rostered:
                rostered[key] = bool(c.owners) and all(
                    _head_hands_nothing_to_a_shell(h) for h in c.owners)
            if not rostered[key]:
                continue
        si = c.statement
        if si not in capturing:
            a, b = statements[si]
            capturing[si] = _CAPTURING_PREFIX_RE.search(masked, a, b) is not None
        if capturing[si]:
            continue
        safe_spans.append((c.start, c.end))


#: The characters that open a PowerShell COMMAND POSITION -- the class
#: ``_PS_CMD_POS_SEP`` keys on, plus ``=``, which that pattern spells outside the
#: class. Blanking one of these inside an inert span is precisely what stops a
#: string literal from reading as code.
#:
#: WARNING: an explicit literal, not parsed back out of the regex. This runs on
#: the PreToolUse hot path and a derivation that raised here would fail the hook
#: rather than the check. ``tests/test_powershell_inert_span_mask.py`` derives
#: the class from ``_PS_CMD_POS_SEP`` and asserts the two agree, so a narrowing
#: reds the suite instead of silently shrinking the mask.
# ⚠ `<` AND `>` ADDED 2026-08-26, and their absence was the whole reason the
# PowerShell redirect mention could not be relieved by anchoring. The bash twin
# `_INERTABLE_SYNTAX` has carried both since it was written; this set was
# assembled from the STATEMENT separators and the redirect operators were never
# on the list. `_REDIRECT_RE` names no verb -- it matches the operator itself --
# so no command-position anchor can reach it, and blanking the operator inside an
# inert span is the only lever there is. Driven with maintenance mode cleared:
# `Write-Host 'echo x > <protected>'`, the double-quoted and here-string
# spellings, a `#` comment and a `$doc = '...'` assignment were 6 of 6 refused.
# SAFE inside an inert span for the same reason as bash: PowerShell performs no
# redirection inside a quoted string or a comment, so the character is literal
# there and blanking it removes a FAKE operator, never a live one. The way this
# goes wrong is a span the masker reads as inert and PowerShell does not, which
# is the `glued-block-comment-opener` shape `_PS_TOKEN_BOUNDARY` exists for and
# the must-deny corpus pins in both directions.
_PS_INERTABLE_SYNTAX = frozenset(";|(){}&=<>\n\r")

#: Characters after which a PowerShell comment opener really starts a token.
#: Measured against pwsh 7.6.5 by tokenising `Write-Output note<CH><# ... #>`
#: for every candidate: 17 of 27 characters leave the opener glued to the
#: argument, where it opens nothing. Only whitespace and true delimiters start
#: a token. Being NARROWER than the language here costs friction; being wider
#: blanks live code, and that is the only one of the two that is a fail-open.
_PS_TOKEN_BOUNDARY = frozenset(" \t\n\r;|&(){},")


def _ps_at_line_start(s: str, i: int) -> bool:
    """A here-string terminator counts only in column 0.

    Measured against pwsh 7.6.5: an INDENTED terminator does not close the
    string -- the body swallowed everything after it. Treating an indented
    terminator as a close would end the span early and leave real code masked
    as string content.
    """
    return i == 0 or s[i - 1] in "\n\r"


def _ps_close_double_quote(s: str, i: int) -> int:
    """Index of the double quote closing the expandable string opened at ``i``.

    Both escapes are real and both were verified against pwsh 7.6.5: a leading
    backtick escapes the closing quote, and a doubled quote escapes it. Either
    one continues the span. A ``$( ... )`` subexpression may itself contain
    quotes, so its nesting is tracked rather than scanned through.
    """
    n, j, depth = len(s), i + 1, 0
    while j < n:
        c = s[j]
        if c == "`":
            j += 2
            continue
        if c == "$" and j + 1 < n and s[j + 1] == "(":
            depth += 1
            j += 2
            continue
        if depth:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            j += 1
            continue
        if c == '"':
            if j + 1 < n and s[j + 1] == '"':
                j += 2
                continue
            return j
        j += 1
    raise _UnresolvedShellSyntax("unterminated double quote")


def _ps_blank_literal(s: str, out: list, a: int, b: int) -> None:
    """Blank every command-position character in ``s[a:b]``. Same length."""
    for k in range(a, b):
        if s[k] in _PS_INERTABLE_SYNTAX:
            out[k] = " "


def _ps_blank_bound_assignment(s: str, out: list, start: int, b: int) -> int:
    """Blank the ``=`` an interpolated token is the left side of; return the
    index past it, or ``start`` when there is none.

    The token ending at ``start`` is interpolated away by the OUTER shell
    before the re-parser receives the text, so the assignment it spells is
    not the assignment that runs. Measured against pwsh 7.6.5 (DEF-753) with
    ``=1`` and with a delete as the right-hand side: with the variable unset
    the re-parser receives ``=<rhs>; <cmd>`` and ``=<rhs>`` is one unknown
    command name whose arguments are the rest of the statement; set to a word
    it receives ``foo=<rhs>; <cmd>``, the same; set to ``1`` it receives
    ``1=<rhs>; <cmd>`` and refuses to parse. Nothing is assigned and the
    right-hand side does not run in any of the three, which is what the
    env-prefix record guards against, so this ``=`` is blanked. The separator
    AFTER it is NOT blanked: in the first two cases the next statement runs.

    Declared, not covered: a variable whose VALUE is itself ``$``-led
    (``$x = '$y'; iex "$x=<cmd>"``) re-parses to a real assignment whose
    right-hand side runs. The value is unknowable here; that is BC-OOS-002's
    indirection class, the same declaration the literal branch carries for
    ``$s = @'...'@; iex $s``.
    """
    m = start
    while m < b and s[m] in " \t":
        m += 1
    if m < b and s[m] == "=":
        out[m] = " "
        return m + 1
    return start


def _ps_blank_expandable(
    s: str, out: list, a: int, b: int, *, reparsed: bool = False,
) -> None:
    """Blank ``s[a:b]`` EXCEPT the ``$( ... )`` subexpressions inside it.

    WARNING: THIS SPLIT IS THE WHOLE SAFETY ARGUMENT, AND IT IS MEASURED.
    Against pwsh 7.6.5 a subexpression inside an EXPANDABLE span (a double-quoted
    string, or a here-string opened with a double quote) genuinely EXECUTES -- a
    real victim directory was deleted -- while inside a LITERAL span (single
    quoted, either form) it genuinely does not. An expandable span is therefore
    not uniformly inert: it is literal text interleaved with live code. Blanking
    it wholesale would take a correct DENY to an ALLOW, which is the fail-open
    twin of the false positive this pass exists to relieve.

    A backtick before the dollar sign suppresses the expansion (verified inert),
    so the escape is consumed first and the parenthesis that follows is blanked
    as the literal it now is.

    ``${...}`` is KEPT WHOLE, like the ``$(...)`` subexpression and like the
    bash twin ``_walk_double_quoted``. Until DEF-716's review it was
    deliberately blanked, on the argument that a variable reference is not a
    command position so blanking its braces cannot hide an execution -- true,
    and beside the point: blanking them split the PATH TOKEN the variable sat
    in, so ``-Path "${env:CLAUDE_PROJECT_DIR}/<hook>"`` reached the extractor
    as ``"$ env:... /<hook>"``, the candidate it yielded was ``"$``, and the
    write ALLOWED (driven; the bash spelling ``"${CLAUDE_PROJECT_DIR}/<hook>"``
    on the PowerShell tool allowed the same way). The braces are found by hand
    with the backtick as the only escape -- the bash ``_match_delimiter``
    honours a backslash, which is a path separator here (walk 3's
    POSIX-unquoter trap).

    WARNING: ``reparsed`` INVERTS WHAT IS BLANKED, AND THE INVERSION IS
    MEASURED (DEF-753). A span handed to a re-parser -- ``iex "..."``,
    ``powershell -Command "..."``, the ``@"..."@`` twin -- is executed AFTER the
    outer shell interpolates it, so its separators, its pipes, its call
    operator and its redirects are all live and none of them is blanked. The
    only character blanked in this mode is the ``=`` that makes an
    interpolated token the left side of an assignment
    (``_ps_blank_bound_assignment`` carries the measurement): that assignment
    can never happen, and leaving it live would re-fire the env-prefix record
    on the shape DEF-617 pinned as ordinary. The subexpression and the braced
    variable are skipped whole in both modes. Every escaping backtick is
    blanked in this mode (the outer shell consumes it; the re-parser never
    sees it), so an escaped ``$`` leaves a bare ``$``-led assignment live in
    the scan text: that spelling really does hand the assignment to the
    re-parser (BC-OOS-004's class), so the deny it now draws is the right
    direction. Same length, same offsets, in both modes; in this mode the
    scan text differs from the raw where an escape stood.
    """
    k = a
    while k < b:
        c = s[k]
        if c == "`":
            if reparsed and k + 1 < b:
                # The outer shell consumes EVERY escape in an expandable span
                # before the re-parser sees the text, so the backtick itself is
                # never part of what runs: blank it. Leaving it in place let
                # `_PS_BACKTICK_CONTINUATION_RE` (which joins backtick, blanks
                # and a newline AFTER masking) eat the line terminator written
                # below whenever an escaped space preceded it -- review, driven
                # through the hook: `iex "<stmt>` `n<cmd>"` allowed while the
                # plain twin denied. A backtick before a REAL newline is the
                # same case: inside an expandable string the escaped newline
                # is kept (measured: length 3, code 10), so the newline stays
                # and the backtick goes.
                out[k] = " "
                if s[k + 1] in "nr":
                    # The escape that denotes a line terminator: the re-parser
                    # meets a statement boundary there, so the scan text
                    # carries the character it denotes. Same length, and no
                    # consumer reads the content of a separator. Lowercase
                    # only, as PowerShell spells it: the uppercase form is a
                    # literal letter (measured against pwsh 7.6.5, where
                    # "a`Nb" is not "a`nb" and its middle character is the
                    # letter).
                    out[k + 1] = "\n" if s[k + 1] == "n" else "\r"
            k += 2
            continue
        if c == "$" and k + 1 < b and s[k + 1] == "(":
            depth, j = 0, k + 1
            while j < b:
                if s[j] == "(":
                    depth += 1
                elif s[j] == ")":
                    depth -= 1
                    if not depth:
                        break
                j += 1
            if depth:
                raise _UnresolvedShellSyntax("unbalanced subexpression in span")
            k = j + 1
            continue
        if c == "$" and k + 1 < b and s[k + 1] == "{":
            # A `${name}` variable token: keep it whole (see the docstring).
            j = k + 2
            while j < b and s[j] != "}":
                j += 2 if s[j] == "`" else 1
            if j >= b:
                raise _UnresolvedShellSyntax("unterminated ${...} variable in span")
            k = j + 1
            if reparsed:
                k = _ps_blank_bound_assignment(s, out, k, b)
            continue
        if reparsed:
            if c == "$":
                # A bare `$name` / `$scope:name` token: interpolated by the
                # outer shell before the re-parser reads the text.
                j = k + 1
                while j < b and (s[j] in "_:" or s[j].isalnum()):
                    j += 1
                if j > k + 1:
                    k = _ps_blank_bound_assignment(s, out, j, b)
                    continue
            k += 1
            continue
        if c in _PS_INERTABLE_SYNTAX:
            out[k] = " "
        k += 1


def mask_powershell_inert_syntax(command: str) -> str:
    """PowerShell twin of :func:`mask_inert_syntax`.

    Blank the command-position characters that sit inside a string literal or a
    comment. Same length, same offsets -- every consumer that reports a slice
    of the original keeps working. Token content survives everywhere except
    inside an expandable span handed to a re-parser, where the escapes the
    outer shell consumes are blanked and a backtick line terminator becomes
    the character it denotes (DEF-753; ``_ps_blank_expandable``).

    WHY IT EXISTS. The PowerShell leg had **no masking pass at all**: its
    records, its speed-bump predicates and its path extractors all read the raw
    command, where their Bash twins read a masked one. The whole verdict
    therefore rested on ``_PS_CMD_POS``, and the discriminator for an inert
    string came out as *the last non-space character before the pattern*. A
    letter allowed; a closing parenthesis, an equals sign and a pipe hard-denied;
    a semicolon and a ``1)`` list marker soft-denied. Measured 2026-08-25 by
    driving the real hook: **54 of 113 generated rows were false positives**,
    across every inert container, on a tier ``ESPALIER_MAINTENANCE_MODE=1``
    cannot bypass. Documenting the harness's own launch line inside a
    here-string was refused.

    WARNING: AND THE ROSTERS COULD NOT SEE IT. All 19 must-allow rows across
    ``tests/test_guard_false_positives.py`` and
    ``bench/powershell_guard_rehearsal.py`` happen to put a letter immediately
    before the pattern, so not one of them can fail on that axis.
    ``bench/powershell_reachability_differential.py`` derives the axis from
    ``_PS_CMD_POS_SEP`` itself instead of listing it.

    WARNING: FAILS CLOSED. Any span this cannot resolve returns the raw command,
    exactly as the Bash pass does -- an unreadable command keeps its separators
    and stays denied.

    WARNING: DELIBERATELY NARROWER THAN POWERSHELL ON ONE POINT. PowerShell
    opens a comment at a hash glued to the previous token (verified: an
    assignment ending ``2#3`` swallowed the rest of the line). This pass requires
    start-of-input, whitespace or a semicolon before the hash. Masking *less*
    than the language does is friction; masking *more* would blank live code.
    Only one of those two errors is a fail-open.
    """
    if not command or len(command) > _ROLE_MAP_CAP:
        return command
    try:
        return _walk_powershell_spans(command)
    except (_UnresolvedShellSyntax, IndexError):
        return command


def _walk_powershell_spans(s: str, spans: "list[tuple[int, int, str]] | None" = None) -> str:
    """The masker's walk. ``spans``, when given, receives every string it
    steps over as ``(open, close, kind)`` -- the opening quote's offset (the
    at-sign of a here-string), the closing quote's, and ``'``, ``"``, ``@'``
    or ``@"`` -- in offset order: PowerShell's quoting read by the ONE walk
    the mask is, for `_ps_quote_cursor`."""
    n, i = len(s), 0
    out = list(s)
    while i < n:
        c = s[i]

        # A top-level backtick escapes the next character, which therefore is
        # not a separator. Step over both.
        if c == "`":
            i += 2
            continue

        # Here-string opener: an at-sign followed by a quote and then the end of
        # the line. A hashtable and an array subexpression also start with an
        # at-sign and must fall through untouched.
        if c == "@" and i + 1 < n and s[i + 1] in "'\"":
            quote = s[i + 1]
            j = i + 2
            while j < n and s[j] in " \t":
                j += 1
            if j < n and s[j] in "\n\r":
                terminator, k, end = quote + "@", j, -1
                while True:
                    k = s.find(terminator, k)
                    if k < 0:
                        break
                    if _ps_at_line_start(s, k):
                        end = k
                        break
                    k += 1
                if end < 0:
                    raise _UnresolvedShellSyntax("unterminated here-string")
                # KNOWN DIVERGENCE, LATENT NOT EXPLOITABLE. When the header is
                # followed by anything other than whitespace-then-EOL this
                # branch falls through and the quote is treated as an ordinary
                # string opener, which can pair with the quote inside the
                # eventual terminator and swallow whole lines. PowerShell
                # instead raises UnexpectedCharactersAfterHereStringHeader.
                # Measured: 48 divergences in 144 targeted shapes, and every one
                # is a pwsh PARSE ERROR, so nothing executes. It becomes live
                # the moment a new header form is accepted -- same class as the
                # glued-opener fail-open above (the span outrunning the
                # language), which is why it is written down rather than left
                # for someone to rediscover.
                if quote == "'":
                    # Same rule as the single-quote branch: literal + re-parsed
                    # means live. The `$s = @'...'@; iex $s` spelling is NOT
                    # reached here (the opener is not adjacent) and is declared
                    # out of scope with the indirection class.
                    if not _ps_span_is_reparsed(s, i):
                        _ps_blank_literal(s, out, j, end)
                else:
                    # An expandable body behind a re-parser keeps its
                    # separators (DEF-753; the double-quoted branch below
                    # carries the measurement).
                    _ps_blank_expandable(
                        s, out, j, end,
                        reparsed=_ps_expandable_is_reparsed(s, i, j, end),
                    )
                if spans is not None:
                    spans.append((i, end, "@" + quote))
                i = end + 2
                continue

        if c == "'":
            j = i + 1
            while j < n:
                if s[j] == "'":
                    if j + 1 < n and s[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            if j >= n:
                raise _UnresolvedShellSyntax("unterminated single quote")
            # A literal span handed to a re-parser is LIVE -- blanking it hid a
            # real invocation. Driven: `iex '$env:VAR=1; <cmd>'` sets the
            # variable and runs the command against real pwsh.
            if not _ps_span_is_reparsed(s, i):
                _ps_blank_literal(s, out, i + 1, j)
            if spans is not None:
                spans.append((i, j, "'"))
            i = j + 1
            continue

        if c == '"':
            j = _ps_close_double_quote(s, i)
            # An expandable span handed to a re-parser is code minus its
            # interpolated tokens, not data: the second statement of
            # `iex "<stmt>; <cmd>"` RUNS against real pwsh (DEF-753, driven
            # 2026-09-10), so its separators stay live and only the assignment
            # bound to an interpolated token is blanked. Before this branch
            # asked, every expandable span was blanked wholesale and the
            # double-quoted twin of a HARD single-quoted program ALLOWED.
            _ps_blank_expandable(
                s, out, i + 1, j, reparsed=_ps_expandable_is_reparsed(s, i, i + 1, j),
            )
            if spans is not None:
                spans.append((i, j, '"'))
            i = j + 1
            continue

        if (
            c == "<"
            and i + 1 < n
            and s[i + 1] == "#"
            and (i == 0 or s[i - 1] in _PS_TOKEN_BOUNDARY)
        ):
            # Block comments do NOT nest in PowerShell -- verified: the first
            # closing marker ends the comment, and code after it runs.
            #
            # WARNING: THE TOKEN-START PRECONDITION IS LOAD-BEARING AND ITS
            # ABSENCE WAS A HARD-TIER FAIL-OPEN. PowerShell opens a block
            # comment only where the opener starts a token; glued to a bare word
            # in argument position it is absorbed into that argument and opens
            # nothing. Driven against pwsh 7.6.5:
            # `Write-Output note<# ; <delete> C:\ #>` really deletes, because the
            # `;` is a LIVE separator -- and without this check the pass blanked
            # it and the guard returned ALLOW on a drive-root delete.
            # The sibling `#` branch below was written with its precondition in
            # the same change; this one was not. Sister-site miss, found by an
            # adversarial pass rather than by 9051 tests.
            end = s.find("#>", i + 2)
            if end < 0:
                raise _UnresolvedShellSyntax("unterminated block comment")
            _ps_blank_literal(s, out, i + 2, end)
            i = end + 2
            continue

        if c == "#" and (i == 0 or s[i - 1] in _PS_TOKEN_BOUNDARY):
            # WARNING: START AT i+1 -- the hash ITSELF MUST SURVIVE, for the same
            # reason the Bash pass keeps it: a blanked hash leaves an unbroken
            # whitespace run from the separator straight to the comment's first
            # word, so a commented-out delete would stay denied.
            # WARNING: EITHER TERMINATOR ENDS IT, and a carriage return is one.
            # Taking only the newline blanked a REAL command position: driven
            # against pwsh 7.6.5, `# note<CR><delete>` genuinely deletes, because
            # the comment stopped at the CR -- and blanking that CR turned a
            # correct DENY into an ALLOW. Caught by
            # bench/powershell_reachability_differential.py minutes after this
            # pass was wired in, on the first run against a real interpreter.
            # Ending a span EARLIER masks less, which is friction; ending it
            # later masks live code, which is a fail-open.
            end = min(
                (x for x in (s.find("\n", i), s.find("\r", i)) if x >= 0),
                default=n,
            )
            _ps_blank_literal(s, out, i + 1, end)
            i = end
            continue

        i += 1

    return "".join(out)


def _scan_head_word(s: str, i: int) -> tuple[str, int, list[int]]:
    """Scan the command word starting at ``i``: return its quote-and-backslash
    stripped text, the index past it, and the map from every raw offset in
    ``[i, after]`` to the stripped offset reached there.

    The map is what makes the walker's head capture linear (DEF-754): the
    lexing is context-free, so a read starting at any raw offset inside the
    word yields the stripped text from the mapped offset on -- a suffix -- and
    the walker derives it instead of scanning again. A quote character maps
    to the offset it was skipped at; a backslash and the character it escapes
    both map to the offset before that character was appended, because a read
    from either produces the same text from there on.
    """
    n, j = len(s), i
    buf: list[str] = []
    at: list[int] = []
    while j < n and s[j] not in " \t\n\r;|&<>":
        ch = s[j]
        at.append(len(buf))
        if ch == '"' or ch == "'":
            j += 1
            continue
        if ch == "\\":
            if j + 1 < n:
                at.append(len(buf))
                buf.append(s[j + 1])
            j += 2
            continue
        buf.append(ch)
        j += 1
    at.append(len(buf))
    return "".join(buf), j, at


def _read_head_word(s: str, i: int) -> tuple[str, int]:
    """Read the command word starting at ``i``; return (word, index past it).

    Quotes and backslashes are stripped rather than treated as terminators, so
    ``'rm' -rf /`` and ``\\rm -rf /`` both report ``rm`` -- the same spellings the
    catastrophic-delete classifier exists to see through. A leading path is
    dropped (``/usr/bin/echo`` -> ``echo``) and an ``env``-assignment prefix
    reports nothing, so the real head is picked up on the next pass.
    """
    word, j, _ = _scan_head_word(s, i)
    if "=" in word:  # an inline env assignment is a prefix, not the head
        return "", j
    return word.rsplit("/", 1)[-1], j


def _close_double_quote(s: str, start: int) -> int:
    i, n = start + 1, len(s)
    while i < n:
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == '"':
            return i
        i += 1
    raise _UnresolvedShellSyntax("unterminated double quote")


def _neutralise_expanding_span(s: str, out: list, a: int, b: int) -> None:
    """Neutralise the inert characters of a span where `$`/backtick still expand.

    Shared by double-quoted spans and unquoted-delimiter heredoc bodies, which
    have identical expansion rules.
    """
    i = a
    while i < b:
        c = s[i]
        if c == "\\":
            # Inside an expanding span a backslash escapes only `$`, a backtick,
            # `"`, `\\` and a newline; any OTHER escaped character is literal
            # text, and a literal separator is as inert as an unescaped one.
            # Skipping both characters left `"heredoc\\|cat \\.env"`'s bar live,
            # and the secret-read leg split a phantom `cat` statement out of a
            # grep pattern (the double-quoted arm of DEF-681). Blank the ESCAPED
            # character, never the backslash, and never a newline -- the same
            # rule the top-level branch in `_walk_shell_roles` gives.
            if i + 1 < b and s[i + 1] in _INERTABLE_SYNTAX and s[i + 1] not in "\n\r":
                out[i + 1] = " "
            i += 2
            continue
        if c == "`":
            j = s.find("`", i + 1)
            if j < 0 or j >= b:
                raise _UnresolvedShellSyntax("unterminated backtick substitution")
            i = j + 1  # live substitution: leave the whole span alone
            continue
        if c == "$" and i + 1 < b and s[i + 1] == "(":
            i = _match_delimiter(s, i + 1, b, "(", ")") + 1
            continue
        if c == "$" and i + 1 < b and s[i + 1] == "{":
            i = _match_delimiter(s, i + 1, b, "{", "}") + 1
            continue
        if c in _INERTABLE_SYNTAX:
            out[i] = " "
        i += 1


def _match_delimiter(s: str, open_idx: int, limit: int, opener: str,
                     closer: str) -> int:
    depth, i = 0, open_idx
    while i < limit:
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == opener:
            depth += 1
        elif s[i] == closer:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise _UnresolvedShellSyntax("unbalanced %s%s expansion" % (opener, closer))


def _close_ansi_c_quote(s: str, quote_idx: int) -> int:
    i, n = quote_idx + 1, len(s)
    while i < n:
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == "'":
            return i
        i += 1
    raise _UnresolvedShellSyntax("unterminated $'' span")


#: Characters after which a `#` starts a comment. Verified against real bash rather
#: than copied from `_CMD_POS_SEP`: a backtick DOES open a fresh command context, so
#: ``echo `#note ...` `` comments out the rest of that line -- and leaving it out
#: meant a backtick-glued comment stayed entirely unmasked, so the UNANCHORED
#: `_REDIRECT_RE` read its text as a real protected-zone write. `>` and `<` are
#: deliberately ABSENT: `echo hi >#f` is a redirect to a file named `#f` in bash, not
#: a comment (driven -- bash rejects the line outright), so admitting them would mask
#: a genuine redirect target.
_COMMENT_OPENERS = " \t\n\r;|&()`"


def _opens_comment(s: str, i: int) -> bool:
    """`#` opens a comment only at a word start -- `a#b` and `foo.py#L1` do not."""
    return i == 0 or s[i - 1] in _COMMENT_OPENERS


def _read_heredoc_operator(
    s: str, i: int,
) -> tuple[int, tuple[str, bool, bool] | None]:
    """Parse `<<` / `<<-` and its delimiter. Returns (next_index, spec_or_None)."""
    n = len(s)
    j = i + 2
    if j < n and s[j] == "<":
        return j + 1, None  # `<<<` here-STRING, not a heredoc
    strip_tabs = False
    if j < n and s[j] == "-":
        strip_tabs, j = True, j + 1
    while j < n and s[j] in " \t":
        j += 1
    if j >= n:
        return j, None
    if s[j] in "'\"":
        quote = s[j]
        k = s.find(quote, j + 1)
        if k < 0:
            raise _UnresolvedShellSyntax("unterminated heredoc delimiter quote")
        return k + 1, (s[j + 1:k], False, strip_tabs)
    expands = True
    if s[j] == "\\":
        j += 1
        expands = False
    k = j
    while k < n and (s[k].isalnum() or s[k] in "_-."):
        k += 1
    if k == j:
        return j, None
    return k, (s[j:k], expands, strip_tabs)


def _consume_heredoc_body(
    s: str,
    out: list,
    i: int,
    delim: str,
    expands: bool,
    strip_tabs: bool,
    neutralise: Callable[[int, int], None],
) -> tuple[int, int]:
    """Neutralise one heredoc body up to its terminator.

    Returns (index to resume parsing at, index where the BODY ended). The second
    is the terminator LINE START, and the caller records a safe span with it --
    one character further would swallow the newline separating this heredoc from
    whatever follows, so `...EOF` + newline + a live delete would lose its
    command position. Relief traded for a fail-open is this surface's signature
    mistake; the two indices exist to keep them apart.
    """
    n = len(s)
    #: The previous line of an UNQUOTED body ended in a backslash: bash joins
    #: it to this one, so this line cannot be the terminator -- `x\` + newline
    #: + `EOF` is the body line `xEOF` and the delimiter is still open (the
    #: splicer reads the same rule; driven with a marker, 2026-09-11: the
    #: statement after that first `EOF` did not run). A QUOTED body keeps its
    #: backslash, and there the next line can close it.
    continued = False
    while i <= n:
        end = s.find("\n", i)
        line_end = n if end < 0 else end
        line = s[i:line_end]
        probe = line.lstrip("\t") if strip_tabs else line
        if not continued and probe.strip() == delim:
            return (line_end + 1 if end >= 0 else n), i
        if expands:
            _neutralise_expanding_span(s, out, i, line_end)
            continued = _continuation(line) == "join"
        else:
            neutralise(i, line_end)
        if end < 0:
            raise _UnresolvedShellSyntax("unterminated heredoc")
        if s[line_end] in _INERTABLE_SYNTAX:
            out[line_end] = " "
        i = line_end + 1
    raise _UnresolvedShellSyntax("unterminated heredoc")


#: One operand per match: a double- or single-quoted span, or a bare token.
#: The tokenizer every last-positional and every-positional helper below uses,
#: so a quoted operand with a space is ONE operand at every site. Defined at
#: `_QUOTED_OR_BARE_OPERAND` beside the cp/mv pair that first needed it.
_OPERAND_TOKEN_RE = re.compile(_QUOTED_OR_BARE_OPERAND)

def raw_operand(raw: str, m: "re.Match[str]", group: int = 1, *,
                keep_quotes: bool = False, word: bool = False) -> str:
    """The operand a scan match captured, read from the RAW text at the
    match's offsets and, when the capture begins with a quote, extended to
    that quote's close. Outer quotes stripped -- unless ``keep_quotes``, for a
    consumer that re-tokenises the operand quote-aware and would otherwise
    split an unquoted `hooks/my file.py` in two (the speed bump's git probe).
    With ``word`` (the Bash write leg's sites, DEF-832) a capture that
    starts with a quote or the ANSI-C or locale marker is read to the end
    of its bash WORD -- adjacent segments concatenated with the shell's
    quote removal -- because a target quoted by ending an enclosing single
    quote read here as its first, empty span. OPT-IN, never the default:
    this reader serves the PowerShell leg too, where a comma joins a path
    list and a backslash is a separator, not an escape, and the bash word
    grammar there lost a listed protected file and a quoted directory with
    a trailing separator (both reviews, driven old-vs-new).

    Every extraction regex runs over the MASKED scan (`mask_inert_syntax`:
    same length, same offsets), so an operator or a verb inside a quoted
    span, a comment or a heredoc body is never read as a write. But the
    OPERAND has to come back from the raw text. A bare `[^\\s...]+` capture
    stops at the first blank inside a quoted span and keeps the prefix
    (`"/tmp/esp` of `"/tmp/esp rehearsal x/tools/cc/hooks/x.py"`), and a
    quote-aware capture spans the right characters but the masker has
    blanked the span's inert ones (`repo (x86)` reads `repo  x86 `), so a
    consumer that takes `m.group()` off the scan compares a path that exists
    nowhere against the zone. Measured 2026-09-14 by driving every arm on
    both shells (DEF-794): 48 of 72 fixtures leaked by one of those two
    mechanisms, and six arms held only because their heads are off the
    masker's roster. The glued spelling (`"a b"c`) joined the word reading
    below with DEF-832 for a capture that starts with a quote; a bare-first
    operand with a backslash-escaped blank stays out of scope, as the row
    records.
    """
    start, end = m.start(group), m.end(group)
    if start < 0:
        return ""
    quote = raw[start:start + 1]
    if word and quote in ('"', "'", "$"):
        # The operand is one bash WORD: from the capture's start, every
        # adjacent segment with the shell's quote removal (DEF-832: a target
        # quoted by ending an enclosing single quote -- spliced or naively --
        # read here as its first, EMPTY span, an allow on a zone path; the
        # glued spelling `"a b"c` the row above kept out of scope joins).
        # Bounded by the capped text; an unclosed quote matches no word and
        # falls to the close-based read below.
        wm = _BASH_WORD_AT_RE.match(raw, start)
        if wm is not None:
            return wm.group(0) if keep_quotes else _bash_word_text(wm.group(0))
    if quote in ('"', "'"):
        # An unclosed quote (the word above needs a close): the close-based
        # read, bounded by the text, which every caller has already capped
        # (`_cap_for_scan`, 32 KB): a bound of its own was a cliff past which
        # the read fell back to the bare prefix -- the pre-fix defect, at a
        # threshold nothing named (review). A flood of opening quotes stays
        # linear because each supplies the close the previous find stops at.
        close = raw.find(quote, start + 1)
        if close != -1:
            return raw[start:close + 1] if keep_quotes else raw[start + 1:close]
    text = raw[start:end]
    return text if keep_quotes else text.strip('"').strip("'")


def raw_span(raw: str, m: "re.Match[str]", group: int = 1) -> str:
    """The SPAN a scan match captured, read from the raw text at the same
    offsets, for the tokenised consumers (`_operands` and its views): they
    are quote-aware readers and need the span's real characters, not the
    masker's blanks (DEF-794; see `raw_operand`) -- and for ANY group whose
    text a reader inspects, a head, a verb or a flag, not only the tokenised
    spans: the mask rewrites characters a reader keys on (DEF-831: a quoted
    `-C` value on the listing head, read from the match text, carried the
    mask's rewrite and lost the root)."""
    start, end = m.start(group), m.end(group)
    return raw[start:end] if start >= 0 else ""


#: Characters after which a `#` starts a comment INSIDE AN ARGUMENT SPAN:
#: whitespace or a statement separator. ⚠ Deliberately NOT `_COMMENT_OPENERS`,
#: the masker's set, which also holds `(`, `)` and a backtick. Those are right
#: for the masker -- a backtick opens a fresh command context, so ``echo `#note
#: ...` `` really does comment -- and wrong inside a span, where a `)` or a
#: backtick is the TAIL of a substitution glued into the current word: bash
#: prints `echo b$(echo X)#y` as `bX#y`, one word. The first cut of the scanner
#: reused the masker's set by name and cut `install a b$(echo X)#y <hook>` at
#: `X)`, dropping the hook at five sites (failure-mode pass, driven old-vs-new).
_SPAN_COMMENT_OPENERS = " \t\n\r;|&"


def _strip_span_tail(span: str) -> str:
    """Cut an argument span where the shell stops reading operands: at a `#`
    that opens a comment (a word start -- start of span, or after one of
    `_SPAN_COMMENT_OPENERS` -- outside single or double quotes and not
    backslash-escaped), at an unquoted `)` with no unquoted `(` open in the
    span (the close of `( install x <hook> )`), or at an unquoted backtick with
    no partner in the span (the close of an enclosing substitution). `a#b`,
    `foo.py#L1`, `\\#x`, `b$(x)#y`, `'s/ #/x/'` and `$(basename x)` are operand
    text and survive; `README.md # <hook>` loses the comment and `<hook> )`
    loses the paren.

    The ONE predicate for every tokenised span consumer (`_operands`, so every
    last-positional and every-positional helper, `_tee_targets`, the hardlink
    tokenizer, and the sed/perl tokenizer); the symlink pair reaches it through
    `symlink_linkname`. The alternative -- excluding `#` or `)` from a span's
    character class -- cuts at a `#` inside an earlier filename or at the `)`
    of a live `$(...)` and drops every operand after it, a fail-open driven at
    six sites (DEF-693's first fix). Before the paren rule, `( install x <hook>
    )` and `( ln -s /tmp/evil <link> )` read `)` as the target (DEF-414b). An
    unterminated quote runs to the end of the span, so nothing after it is cut;
    the masker has already blanked a `#` inside a quoted span when the head is
    on the non-reparsing roster, and the quote walk here covers the raw case
    when it is not."""
    i, n, depth = 0, len(span), 0
    while i < n:
        c = span[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            j = span.find("'", i + 1)
            if j < 0:
                return span
            i = j + 1
            continue
        if c == '"':
            j = i + 1
            while j < n and span[j] != '"':
                j += 2 if span[j] == "\\" else 1
            if j >= n:
                return span
            i = j + 1
            continue
        if c == "`":
            j = span.find("`", i + 1)
            if j < 0:
                return span[:i]
            i = j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            if depth == 0:
                return span[:i]
            depth -= 1
        elif c == "#" and (i == 0 or span[i - 1] in _SPAN_COMMENT_OPENERS):
            return span[:i]
        i += 1
    return span


#: A redirection token inside an argument span -- `>x`, `2>/dev/null`, `>>log`,
#: `<f`, `<<EOF` -- and the bare-operator twin (`>`, `2>`, `>>`) whose TARGET
#: is the next token. Neither is an operand of the verb: `install x <hook>
#: 2>/dev/null` read `2>/dev/null` as the last positional and hid the hook, at
#: every last-positional site (DEF-414b, driven). The span consumers read the
#: RAW span since DEF-794, where `&>` and `&>>` arrive whole (the scan had
#: blanked their `&`, and `_operands` was calibrated against that): without
#: the `&>` arm, `cp x <hook> &>/dev/null` kept `&>/dev/null` as a positional
#: and the hook fell out of the last-positional pick on EVERY root (review,
#: driven: 720 regressions across cp/mv/install/rsync/truncate, 0 after).
_REDIRECT_TOKEN_RE = re.compile(r"^(?:[0-9]*[<>]{1,3}|&>{1,2})")
_BARE_REDIRECT_OPERATOR_RE = re.compile(r"^(?:[0-9]*[<>]{1,3}[&|]?|&>{1,2})$")

#: The `&` of a redirect operator: any `&` glued to the RIGHT of `<`/`>` (the
#: descriptor forms `2>&1`, `>&2`, `<&0`, `>&-`, and bash's csh-style
#: both-streams `>&file` / `>& file`), or glued to the LEFT of `>` (`&>f`,
#: `&>>f`). `&` ends every span class, so written BEFORE the operands
#: (`install evil.json 2>&1 <hook>`, and bash does create the file) the target
#: sat OUTSIDE the span the tokenizer reads and fifteen write verbs allowed it
#: (verification pass, driven old-vs-new; pre-existing). The first cut of this
#: rule was six literals with a `[0-9-]` lookahead and missed `>&file`, the one
#: spelling that is itself a WRITE (`echo y >&<hook>` created the file, driven).
#: `neutralise_redirect_ampersands` replaces that `&` with a space before the
#: verb extractors run: `2> 1` and `>& out` are then a bare operator plus its
#: target, which `_operands` drops, and `>&<hook>` becomes `> <hook>`, which the
#: redirect leg reads. The lookarounds need a redirect operator on one side
#: and refuse `&&`/`&|` on the other, so `&&`, a background `&` and an `a&b`
#: inside a pattern are untouched; the masker has already blanked a quoted `&`
#: when the head is on the non-reparsing roster.
_REDIRECT_AMPERSAND_RE = re.compile(r"(?<=[<>])&(?![&|])|&(?=>)")


def neutralise_redirect_ampersands(text: str) -> str:
    """Space out the `&` of every redirect operator (`2>&1`, `&>`) so the span
    classes read past it; same length, same offsets."""
    return _REDIRECT_AMPERSAND_RE.sub(" ", text)


def _operands(args: str) -> list[str]:
    """Split an argument span into operands, quotes stripped -- a quoted
    span with a space is one operand, not two -- after cutting the span's
    shell-level tail (`_strip_span_tail`: a comment, an unmatched close) and
    dropping every redirection (`_REDIRECT_TOKEN_RE`, with the target of a
    bare operator), so neither a comment's words nor a `2>/dev/null` is ever
    an operand. The redirect leg reads redirections on its own.

    ⚠ This is the RAW token stream: it does not know that `--` ends option
    parsing. A consumer that asks "is there a flag" or "what are the
    positionals" reads one of the two views that do -- `_option_tokens` and
    `_positional_operands` -- never this list. One fix taught the `--` rule to
    the positional view and the next wrote a flag test against this stream: a
    file named `-t` after `--` disarmed the whole cp/mv leg (verification pass,
    driven; HEAD denied). The third fix in this lane that was right at the site
    and blind at the view one call away, which is why the views are named."""
    out: list[str] = []
    skip_next = False
    for tok in _OPERAND_TOKEN_RE.findall(_strip_span_tail(args)):
        if skip_next:
            skip_next = False
            continue
        if _REDIRECT_TOKEN_RE.match(tok):
            skip_next = _BARE_REDIRECT_OPERATOR_RE.match(tok) is not None
            continue
        out.append(tok.strip('"').strip("'"))
    return out


def _positional_operands(args: str) -> list[str]:
    """Every operand in ``args`` that is not a flag (does not start with `-`),
    where `--` ends option parsing: every token after it is an operand however
    it starts -- `cp -- -weird <hook>` is a copy of a dash-leading file, and
    filtering by the first character alone dropped both `--` and `-weird`,
    left one positional and lost the destination (a regression a later
    review pass drove old-vs-new; the hardlink tokenizer had the rule all
    along). The value of a separated flag (`-s 0`, `-i p.diff`) is NOT filtered
    -- the callers tolerate an extra unprotected candidate (over-yield is
    fail-safe)."""
    out: list[str] = []
    end_opts = False
    for tok in _operands(args):
        if not end_opts and tok == "--":
            end_opts = True
            continue
        if end_opts or not tok.startswith("-"):
            out.append(tok)
    return out


def _target_directory_readings(
    args: str, valueless_short: frozenset[str],
) -> tuple[list[str], bool]:
    """Every DIR the span can be read as naming, and whether the span is
    AMBIGUOUS. Two sources of ambiguity, both reported rather than resolved:

    * the two readings disagree -- a value-taking flag's following token starts
      with `-` (`-S -t d/` has a suffix `-t`; `--st -t d/` abbreviates cp's
      no-value `--strip-trailing-slashes` while also prefixing the roster's
      `--strip-program`), and only the verb's full option table tells them
      apart (a later review pass: six abbreviations ate the `-t`);
    * the readings AGREE, but the token standing immediately before the target
      flag is a flag that is not known to have left the next token alone
      (`_did_not_take_the_next_token`, the verb's valueless roster) -- it may
      have taken `-t` as its value and nothing here would know (a later
      review pass: BSD `install -B -t a <hooks>/`, nine driven, where the
      value roster was short and agreement silenced the pick). A token the
      consuming reading CERTAINLY swallowed as a value (`cp -S -S -t d/`: the
      second `-S` is a suffix) is not a flag and is not asked.

    Five review passes in a row each ended on a hand-kept set being short, so the sets
    are now placed where incompleteness fails SAFE: an unknown flag is
    ambiguous, and an ambiguous span makes the consumer take every DIR it got
    AND the last-positional pick. A short valueless roster costs a denied read;
    a short value roster costs junk candidates; neither costs a missed write."""
    tokens = _operands(args)
    consumed, _, swallowed = _target_directory_walk(tokens, True)
    plain, at, _ = _target_directory_walk(tokens, False)
    dirs = [d for d in dict.fromkeys((consumed, plain)) if d is not None]
    ambiguous = consumed != plain
    if at > 0 and (at - 1) not in swallowed:
        before = tokens[at - 1]
        if (
            before.startswith("-") and before not in ("-", "--")
            and not _did_not_take_the_next_token(before, valueless_short)
        ):
            ambiguous = True
    return dirs, ambiguous


def _landed_under(directory: str, sources: list[str]) -> list[str]:
    """Where each source lands when copied INTO ``directory``:
    `<directory>/<basename(source)>`, so a directory destination names the file
    it will hold (`cp -t .claude/ settings.json` -> `.claude/settings.json`,
    the protected exact file the bare directory never was)."""
    out: list[str] = []
    stem = directory if directory.endswith("/") else directory + "/"
    for src in sources:
        base = src.rstrip("/").rsplit("/", 1)[-1]
        if base:
            out.append(stem + base)
    return out


def _option_tokens(args: str) -> list[str]:
    """Every flag token in ``args`` -- the `-`-prefixed tokens BEFORE `--`; a
    dash-leading token after `--` is an operand (`cp -- -t src dir/` copies a
    file named `-t`). The twin of `_positional_operands`: between them every
    token before `--` is classified once, by its first character, and nothing
    after it is ever a flag. Known limit, stated: a separated flag's VALUE that
    happens to start with `-` (`cp -S -t a dir/`, a backup suffix literally
    `-t`) reads as a flag here and as a positional there -- a value-flag roster
    per verb would be the fix, and no live shape has needed it."""
    out: list[str] = []
    for tok in _operands(args):
        if tok == "--":
            break
        if tok.startswith("-"):
            out.append(tok)
    return out


def _patch_targets(args: str) -> list[str]:
    """Every candidate a `patch` invocation writes: each positional (the
    originalfile is the FIRST, `patch [opts] [originalfile [patchfile]]`; the
    patchfile read is the last and over-yields) plus the value of a glued long
    flag -- `--output=FILE` IS the write target, `--directory=DIR` is where the
    patched paths land, `--input=`/`--reject-file=` over-yield. A separated `-o
    FILE` / `-d DIR` value is already a positional. Driven: `patch
    --output=<hook> orig p.diff` and `patch --directory=tools/cc/hooks -i p.diff`
    both ALLOWED under the positional pick alone (failure-mode pass)."""
    out = _positional_operands(args)
    for tok in _operands(args):
        if tok.startswith("--") and "=" in tok:
            value = tok.split("=", 1)[1]
            if value:
                out.append(value)
    return out


def _last_non_flag_token(args: str) -> str | None:
    """Return the last operand in ``args`` that doesn't start with `-`.
    Used for verbs (install, rsync, truncate) where the protected target is
    the final positional and flags can take separate or glued arguments.
    `patch` is NOT one of them -- its originalfile is the first positional, so
    `_candidate_paths_from_bash` takes every positional for it.

    ⚠ The first version split on whitespace and called itself conservative
    ("false positives are harmless extra _is_protected checks, false
    negatives would leak"). On `install evil.json "tools/cc/hooks/my file.py"`
    it returned the tail fragment `file.py"` and DROPPED the real path -- a
    false negative, the exact direction the claim said could not happen. A
    Windows-shaped path is the everyday trigger. Found by the DEF-638
    failure-mode pass at five sibling sites after the cp/mv pair was fixed;
    the operand tokenizer is now the one shape at every site."""
    candidates = _positional_operands(args)
    return candidates[-1] if candidates else None


def _expand_simple_var_assignments(command: str, *, wall: bool = False) -> str:
    """Pre-pass: inline literal `VAR=value` assignments before extraction.

    ``wall`` asks for the walls' reading (DEF-846, `_wall_readings`): a
    value must end where its literal ends, and a tilde value is bound as
    bash stores it (`_bound_value` has both rules and why the other readers
    keep the reading they had).

    Scope: an assignment at a statement start (`_BINDING_START`: after `;`,
    `&&`, `||`, a newline, a group opener, or at the head of an `eval` or
    `-c` program), any case of name, bare or behind a declaration builtin
    (DEF-847), where the value is a
    plain word, single-quoted, or double-quoted with no `$` inside. After
    binding, `$VAR` and `${VAR}` references in the LATER segments of the
    same command line are substituted -- each reference takes the most
    recent binding before it, as the shell does, so `P=<hook>; echo x > $P;
    P=notes.txt` still names the hook (until 2026-09-15 the last binding on
    the line won for every reference and that spelling allowed; the
    PowerShell twin `_expand_simple_ps_var_assignments` was written
    sequential and this one was brought level, DEF-801's lane). A later
    assignment with a computed value unbinds the name. Anything fancier --
    `$(...)`, `${VAR:-default}`, arithmetic expansion, a second assignment in
    one statement -- is intentionally not handled. The expander is
    best-effort: ambiguous cases
    return the command unchanged so the rest of extraction still runs
    against the original, and an expansion that would grow the text past
    twice the scan cap is abandoned the same way (a long value referenced
    many times would hand the masker megabytes: the cap bounds the input,
    this bounds the output).

    Only a LIVE site binds (DEF-848's lane, both reviews): the sites are
    searched over the masked text (`mask_inert_syntax`), where a quoted
    argument's or a comment's separators, groups and exec openers are blank,
    so a mention such as a commit message saying `(F=b)` is not a binding;
    the value is still read from the raw text at the same offset. And a
    binding made inside a child scope -- a subshell or a command
    substitution, a program handed to a shell's `-c` -- ends when the scope
    closes (`_binding_scope_events`): until then a phantom rebinding there
    replaced a real earlier literal for every later reference. An `eval`
    program runs in the current shell, so its bindings stay.
    """
    # Every live site is a raw one (the mask only blanks), so a command with
    # no raw site pays for no masking walk: the walls ask for this reading on
    # every Bash call, and a heredoc flood made the extra walk the budget's
    # margin (the ReDoS chain row, measured 0.88 s to 1.01 s).
    if _VAR_ANY_ASSIGN_RE.search(command) is None:
        return command
    live = mask_inert_syntax(command)
    if len(live) != len(command):
        live = command
    sites = list(_VAR_ANY_ASSIGN_RE.finditer(live))
    if not sites:
        return command
    # Rebuild left to right: the text between two events is expanded with
    # the bindings in force there. A site's assignment is copied through and
    # its binding (or unbinding) takes effect after it; a scope opener starts
    # an undo mark, its closer undoes every change made since (a journal, so
    # the cost is the number of changes, never scopes times bindings).
    events: list[tuple[int, int, "re.Match[str] | bool"]] = [
        (site.start(1), 1, site) for site in sites
    ]
    events.extend((offset, 0, opens) for offset, opens in _binding_scope_events(command, live))
    events.sort(key=lambda event: (event[0], event[1]))
    out: list[str] = []
    bindings: dict[str, str] = {}
    journal: list[tuple[str, str | None]] = []
    marks: list[int] = []
    at = 0
    # ONE budget across every segment: a per-segment budget let many small
    # segments sum past it (review, driven: 32 KB of `$A; X=1;` pairs against
    # an 8 KB value became 28 MB and 52 s in the extractor).
    grown = 0

    def bind(name: str, value: str | None) -> None:
        if marks:
            journal.append((name, bindings.get(name)))
        if value is None:
            bindings.pop(name, None)
        else:
            bindings[name] = value

    for offset, _rank, item in events:
        if offset < at:
            continue  # inside an assignment already copied through
        try:
            piece, grown = _substitute_bash_refs(command[at:offset], bindings, grown)
        except _ExpansionTooLarge:
            return command
        out.append(piece)
        at = offset
        if isinstance(item, bool):
            if item:
                marks.append(len(journal))
            elif marks:
                undo_to = marks.pop()
                while len(journal) > undo_to:
                    name, before = journal.pop()
                    if before is None:
                        bindings.pop(name, None)
                    else:
                        bindings[name] = before
            continue
        site = item
        lit = _VAR_ASSIGN_RE.match(command, site.start())
        if lit is not None and lit.start(1) == site.start(1):
            out.append(command[site.start(1):lit.end()])
            at = lit.end()
            bind(lit.group(1), _bound_value(lit, command, wall))
        else:
            out.append(command[site.start(1):site.end()])
            at = site.end()
            bind(site.group(1), None)
    try:
        piece, grown = _substitute_bash_refs(command[at:], bindings, grown)
    except _ExpansionTooLarge:
        return command
    out.append(piece)
    return "".join(out)


#: The characters that open or close a child scope for the binding pre-pass:
#: a subshell `( )` and a command substitution `$( )`, read on the masked text
#: (a quoted or commented paren is blank there). A case arm's lone `)` closes
#: nothing when no scope is open.
_BINDING_SCOPE_CHAR_RE = re.compile(r"[()]")
#: The opener of a program handed to a POSIX shell's `-c` in a quoted word:
#: the program runs in a CHILD shell, so its bindings end at its closing
#: quote. `eval` is not here: it runs its program in the current shell.
_SHELL_C_BODY_OPEN_RE = re.compile(r"\b(?:ba|z|k|da)?sh[ \t]+-c[ \t]*(['\"])")


def _binding_scope_events(command: str, live: str) -> list[tuple[int, bool]]:
    """``(offset, opens)`` for every child scope the binding pre-pass honours
    in ``command`` (``live`` is its masked twin, same length): each live
    paren, and the quoted program of a shell's `-c` from its opening quote to
    its closing one. An unterminated program opens nothing."""
    events = [(m.start(), live[m.start()] == "(") for m in _BINDING_SCOPE_CHAR_RE.finditer(live)]
    for m in _SHELL_C_BODY_OPEN_RE.finditer(live):
        quote_at = m.start(1)
        if command[quote_at] == "'":
            close = command.find("'", quote_at + 1)
        else:
            try:
                close = _close_double_quote(command, quote_at)
            except _UnresolvedShellSyntax:
                close = -1
        if close < 0:
            continue
        events.append((quote_at + 1, True))
        events.append((close, False))
    return events


class _ExpansionTooLarge(Exception):
    """A pre-pass would grow the text past twice the scan cap: abandoned, the
    command is scanned as written (a long value referenced many times would
    otherwise hand the masker megabytes; the cap bounds the input, this
    bounds the output)."""


def _substitute_bash_refs(
    text: str, bindings: dict[str, str], grown: int = 0,
) -> tuple[str, int]:
    """`$NAME` and `${NAME}` in ``text`` replaced by their bound values, and
    the growth budget carried in and out: ``grown`` is what the whole
    command's expansion has added so far, one budget across every segment.
    ONE pass (`_BASH_REF_RE`), the name read greedily as bash reads it, so
    `$FOOBAR` is FOOBAR's and never FOO's; until DEF-848's lane it was one
    pass per bound name, which cost names times length on EVERY segment and
    the scope events cut the text into many. The replacement is a callable,
    so a backslash in a value is a character and not a `re.sub` escape (a
    `\\q` in a single-quoted value raised inside the guard until
    2026-09-15)."""
    if not bindings or "$" not in text:
        return text, grown
    total = grown

    def value_of(m: "re.Match[str]") -> str:
        nonlocal total
        value = bindings.get(m.group(1) or m.group(2))
        if value is None:
            return m.group(0)
        total += len(value)
        if total > _BASH_COMMAND_CAP:
            raise _ExpansionTooLarge()
        return value

    return _BASH_REF_RE.sub(value_of, text), total


#: A reference the pre-pass may substitute: `${NAME}` or `$NAME`, the name
#: read greedily. `${NAME:-x}` and every other parameter expansion match
#: neither arm and stay as written.
_BASH_REF_RE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")


def _tee_targets(tee_args_blob: str) -> list[str]:
    """Every positional (non-flag) operand of a tee invocation -- through the
    shared operand tokenizer, so a quoted path with a space is one target and a
    same-line comment is cut (`tee build.log # never tee into <hook>` was
    denied: `tee` is ON the non-reparsing roster, the masker keeps a comment's
    words, and the whitespace split here read them as targets)."""
    return _positional_operands(tee_args_blob)


def _cap_for_scan(command: str) -> str:
    """Trim command for path-extraction scanning.

    Cap at 32KB to bound regex latency on multi-MB heredoc bodies, split
    into head + tail (16KB each) so trailing redirects past the front-32KB
    cap are still scanned. A plain front truncation (`command[:32_768]`)
    would let an attacker pad the prefix with 33KB of harmless text and hide
    a trailing `echo x > tools/cc/hooks/write_guard.py` after the cap. A
    ``\\n`` separator between halves prevents the regex from spuriously
    matching across the split.
    """
    if len(command) <= _BASH_COMMAND_CAP:
        return command
    return (
        command[:_BASH_COMMAND_HALF_CAP]
        + "\n"
        + command[-_BASH_COMMAND_HALF_CAP:]
    )


def iter_inplace_edit_targets(command: str, raw: str | None = None) -> Iterator[str]:
    r"""Yield candidate write targets of every in-place ``sed``/``perl`` edit.

    ``command`` is the text the verb is FOUND on (the masked scan); ``raw``,
    when given and the same length, is where the segment's CHARACTERS come
    from, by offset (DEF-794: the masker blanks a quoted operand's parens).

    A tokenizer, not a grammar regex -- see the ``_INPLACE_PROFILES`` comment for
    why the option grammar is keyed per verb rather than shared. Walks the tokens
    after the verb: consumes options (including glued ``-i.bak``, bundled
    ``-Ei.bak``, and ``--long=value``), consumes the script slot per profile, then
    treats EVERY remaining token as a candidate path -- so
    ``sed -i '' s/a/b/ a.py b.py`` is fully covered rather than first-operand only.

    Yields nothing when no in-place flag is present, so a read (``sed -n '1,5p'``,
    ``perl -ne 'print'``) contributes no candidates.

    The caller filters through the protected-zone check, so OVER-yield is fail-safe
    and under-yield is not: a spurious ``s/a/b/`` matches no protected zone, while
    a missed operand is an unchecked write.
    """
    for match in _INPLACE_SEGMENT_RE.finditer(command):
        text = raw if raw is not None and len(raw) == len(command) else command
        segment = _strip_span_tail(text[match.start("seg"):match.end("seg")])
        # Quote-aware, like every operand tokenizer here: `'s|<hook>|x|'` is
        # ONE token (a whitespace split once turned it into three and named
        # the hook a write target -- the tier's red). The verb is found on the
        # masked scan; the characters come from the raw twin, so a quoted
        # operand's parens are its own and not the masker's blanks (DEF-794).
        # A quoted VERB (`'sed' -i ...`) opens the segment after its own
        # opening quote, so the verb's closing quote would pair with the
        # script's: drop that stray quote first (driven: ten quoted-verb
        # spellings of the derived population lost their target without it).
        end = next((k for k, ch in enumerate(segment) if ch in " \t"), len(segment))
        head = segment[:end]
        if head and head[-1] in "'\"" and head[0] not in "'\"" and head.count(head[-1]) == 1:
            segment = head[:-1] + segment[end:]
        tokens = _OPERAND_TOKEN_RE.findall(segment)
        if not tokens:
            continue
        # strip a quoted verb (`'sed'`) and fold case (`SED` on APFS) so both
        # reach the table -- the regex admits them, and a lookup miss here would
        # silently drop the whole segment.
        profile = _INPLACE_PROFILES.get(tokens[0].strip("'\"").lower())
        if profile is None:
            continue

        in_place = False
        script_seen = False
        script_taken = False
        operands: list[str] = []
        index = 1
        while index < len(tokens):
            token = tokens[index]
            index += 1

            if token == "--":                      # end of options
                operands.extend(tokens[index:])
                break

            if token.startswith("--"):
                name, equals, value = token.partition("=")
                if name in profile["long_inplace"]:
                    in_place = True
                    if not equals and profile["separable_suffix"]:
                        if index < len(tokens) and tokens[index] in _EMPTY_QUOTE_PAIRS:
                            index += 1             # `--in-place ''`
                elif name in profile["long_script"]:
                    script_seen = True
                    if not equals:
                        index += 1                 # the script is the next token
                continue

            if token.startswith("-") and len(token) > 1:
                body = token[1:]
                for position, letter in enumerate(body):
                    if letter in profile["inplace_letters"]:
                        in_place = True
                        # Everything after `i` in THIS token is the backup suffix
                        # (`-i.bak`, `-Ei.bak`), never more flags -- stop scanning.
                        if not body[position + 1:] and profile["separable_suffix"]:
                            if index < len(tokens) and tokens[index] in _EMPTY_QUOTE_PAIRS:
                                index += 1         # `-i ''`
                        break
                    if letter in profile["script_letters"]:
                        script_seen = True
                        if not body[position + 1:]:
                            index += 1             # `-e s/a/b/`
                        break                      # else the script is glued on
                continue

            if profile["positional_script"] and not script_seen and not script_taken:
                script_taken = True                # sed's one bare script argument
                continue
            operands.append(token)

        if not in_place:
            continue
        for operand in operands:
            cleaned = operand.strip("'\"")
            if cleaned:
                yield cleaned


#: The inline-program openers, keyed by the `_STDIN_PROGRAM_WRITE_RES`
#: interpreter they dispatch to (`pypy -c` is the python arm).
_INLINE_PROGRAM_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("python", _PYTHON_DASH_C_RE),
    ("node", _NODE_DASH_E_RE),
    ("ruby", _RUBY_DASH_E_RE),
    ("perl", _PERL_DASH_E_RE),
)
if not {interp for interp, _ in _INLINE_PROGRAM_RES} <= set(_STDIN_PROGRAM_WRITE_RES):
    raise RuntimeError(
        "inline-program interpreter roster drift: an opener added here without "
        "a dispatch key would raise KeyError inside the guard"
    )


def _inline_program_bodies(command: str, scan: str) -> Iterator[tuple[str, str]]:
    """Yield ``(interpreter, program_text)`` for every ``-c`` / ``-e`` inline
    program (DEF-704).

    The opener is found on ``scan``, where the mask has already turned a
    ``#`` comment or a quoted mention behind a roster head into text; the
    body is read from ``command`` at the same offsets, because its own
    syntax characters are what the inner write patterns match. Same
    two-string discipline as :func:`_stdin_program_bodies`, same length guard:
    if the strings ever disagree the raw command is searched, since a false
    match there costs a denial and a missed one a write.
    """
    if len(scan) != len(command):
        scan = command
    for interp, rx in _INLINE_PROGRAM_RES:
        for m in rx.finditer(scan):
            # the program is the WORD's text -- adjacent segments concatenated
            # with the shell's quote removal (DEF-832), so the inner readers
            # see what the interpreter receives
            yield interp, _bash_word_text(command[m.start("word"):m.end("word")])


def _stdin_program_bodies(command: str, scan: str) -> Iterator[tuple[str, str]]:
    """Yield ``(interpreter, program_text)`` for every interpreter fed its
    program on stdin -- a heredoc body or a here-string word (see
    :data:`_INTERP_STDIN_RE` for the grammar and the two-string discipline).

    The opener is found on ``scan``; the body is read from ``command`` at the
    same offsets. An unterminated heredoc yields the body to the end of the
    command, because bash warns and RUNS it -- stopping short would be the
    fail-open. If the two strings ever disagree in length the raw command is
    searched instead: a false match there costs a denial, a missed one a write.
    """
    if len(scan) != len(command):
        scan = command
    n = len(command)
    for m in _INTERP_STDIN_RE.finditer(scan):
        interp = m.group(1).lower()
        op = m.end() - 2                       # index of `<<` in both strings
        if command[op:op + 3] == "<<<":        # here-string: one word is the program
            j = op + 3
            while j < n and command[j] in " \t":
                j += 1
            if j < n and command[j] in "'\"":
                # A single-quoted word has no escapes; a double-quoted one does,
                # and a bare `find` stopped at the first escaped quote inside a
                # `print(\"debug\")` and dropped the write behind it (review,
                # 2026-09-06). Unterminated: the program runs to the end.
                if command[j] == "'":
                    k = command.find("'", j + 1)
                else:
                    try:
                        k = _close_double_quote(command, j)
                    except _UnresolvedShellSyntax:
                        k = -1
                word = command[j + 1:k] if k >= 0 else command[j + 1:]
                # The text the interpreter RECEIVES: bash removes the escapes
                # of a double-quoted word, so `\"` reaches the program as a
                # quote (the shell-out reader's literal opens on it).
                yield interp, word if command[j] == "'" else _bash_unescape_program(word, '"')
            else:
                k = j
                while k < n and command[k] not in " \t\n\r;|&":
                    k += 1
                yield interp, command[j:k]
            continue
        body = _heredoc_body_after(command, op)
        if body is not None:
            yield interp, body


def _heredoc_body_after(command: str, op: int) -> str | None:
    """The body of the heredoc whose `<<` sits at `op` in the RAW command, to
    its terminator or -- bash warns and RUNS an unterminated body, so stopping
    short would be the fail-open -- to the end; None when the operator has no
    body on this command."""
    try:
        _, spec = _read_heredoc_operator(command, op)
    except _UnresolvedShellSyntax:
        return None
    if spec is None:
        return None
    delim, _expands, strip_tabs = spec
    nl = command.find("\n", op)
    if nl < 0:
        return None                            # operator with no body on this command
    n = len(command)
    i, lines = nl + 1, []
    while i < n:
        end = command.find("\n", i)
        line_end = n if end < 0 else end
        line = command[i:line_end]
        probe = line.lstrip("\t") if strip_tabs else line
        if probe.strip() == delim:
            break
        lines.append(line)
        if end < 0:
            break
        i = line_end + 1
    return "\n".join(lines)


def _heredoc_body_spans(text: str) -> list[tuple[int, int]]:
    """``[start, end)`` of every heredoc body in ``text``, in order. The
    bodies of several operators on one line follow one another, as bash
    reads them, so each line is scanned once (linear); an operator inside a
    body already read is body text; an unterminated body runs to the end,
    as bash runs it. The directory walk reads these: a body the masker left
    live belongs to a program that re-parses it (a shell, `ssh`), so a
    statement inside it is another shell's (the lane's review, its major)."""
    spans: list[tuple[int, int]] = []
    n, body_from = len(text), 0
    for m in _HEREDOC_OPERATOR_RE.finditer(text):
        op = m.start()
        if spans and spans[-1][0] <= op < body_from:
            continue
        try:
            _, spec = _read_heredoc_operator(text, op)
        except _UnresolvedShellSyntax:
            continue
        nl = text.find("\n", op)
        if spec is None or nl < 0:
            continue
        delim, _expands, strip_tabs = spec
        start = i = max(nl + 1, body_from)
        end, body_from = start, n
        while i < n:
            e = text.find("\n", i)
            line_end = n if e < 0 else e
            line = text[i:line_end]
            if (line.lstrip("\t") if strip_tabs else line).strip() == delim:
                body_from = min(line_end + 1, n)
                break
            end = line_end
            i = line_end + 1
        spans.append((start, end))
    return spans


def _heredoc_cursor(text: str) -> "Callable[[int], bool]":
    """``at(i)``: is offset ``i`` inside a heredoc body of ``text``
    (`_heredoc_body_spans`)? The spans are read on the first ask, and only
    when the text holds a heredoc operator at all."""
    spans: list[tuple[int, int]] | None = None
    starts: list[int] = []

    def at(i: int) -> bool:
        nonlocal spans
        if spans is None:
            spans = _heredoc_body_spans(text) if "<<" in text else []
            starts.extend(s for s, _e in spans)
        k = bisect.bisect_right(starts, i) - 1
        return k >= 0 and spans[k][0] <= i < spans[k][1]

    return at


#: The ANSI-C escapes `$'...'` decodes that change what the other shell
#: parses; the rest (`\xHH`, `\uHHHH`, `\a`, ...) are left as typed, an
#: under-decode the other shell reads as literal characters -- safe, because
#: none of them can HIDE a separator or a quote the way `\'` and `\\` can.
_ANSI_C_ESCAPES = {"'": "'", '"': '"', "\\": "\\", "n": "\n", "t": "\t", "r": "\r"}


def _bash_unescape_program(body: str, quote: str) -> str:
    """The text bash hands the program behind a quoted word, by the word's
    quote kind. Inside single quotes nothing is an escape. Inside double
    quotes (`"` and the locale form `$"`) a backslash escapes only `"`,
    `\\`, `$`, a backtick and a newline (the pair is removed); before any
    other character it is literal, which is why a Windows path spelled
    `tools\\cc\\hooks` survives (`\\c` is two characters to bash). Inside
    `$'...'` (ANSI-C quoting, ONE word) a backslash escapes the next
    character by the C table (`_ANSI_C_ESCAPES`; an escape not in it stays
    as typed). This reads ONE segment: the `'...'\\''...'` concatenation is
    several segments of one word, joined by `_bash_word_text` (DEF-832)."""
    if quote == "'":
        return body
    out: list[str] = []
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c == "\\" and i + 1 < n:
            nxt = body[i + 1]
            if quote == "$'":
                out.append(_ANSI_C_ESCAPES.get(nxt, "\\" + nxt))
                i += 2
                continue
            if nxt in '"\\$`':
                out.append(nxt)
                i += 2
                continue
            if nxt == "\n":
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


#: The whole word from an operand capture's start (`raw_operand`): the word
#: grammar the openers carry, anchored by `match` at a start an anchored
#: reader selected -- a TOKENIZER over that span, declared as such in the
#: anchor census.
_BASH_WORD_AT_RE = re.compile(_BASH_QUOTED_WORD, re.DOTALL)


def _bash_word_text(word: str) -> str:
    """The text bash hands a program for the WORD ``word`` (DEF-832): the
    quote-removed view of `_read_shell_word`, the one bash-word reader (the
    here-string arm's), over a span the word grammar selected -- a
    single-quoted segment verbatim, an ANSI-C or double-quoted one by
    `_bash_unescape_program`, a backslash dropped before the character it
    escapes. The grammar and the reader stop on the same characters."""
    return _read_shell_word(word, 0)[0]


def _shell_program_bodies(command: str, scan: str) -> Iterator[str]:
    """Yield every PowerShell program a Bash command hands to `powershell` /
    `pwsh` (DEF-637): the quoted or bare `-Command` operand, and a heredoc
    or here-string fed to the shell on stdin. Opener on ``scan``, body from
    ``command`` at the same offsets, the two-string discipline of
    :func:`_inline_program_bodies`; the same length guard. The yielded text
    is what the OTHER shell receives -- unescaped for the quoted arm, verbatim
    for the bare and stdin arms -- so the consumer runs its own masker on it.
    """
    if len(scan) != len(command):
        scan = command
    for m in _POWERSHELL_DASH_COMMAND_RE.finditer(scan):
        # the quoted program is one bash word of adjacent segments (DEF-832),
        # its quote removal by `_bash_word_text`; a bare program verbatim
        if m.group("word") is not None:
            yield _bash_word_text(command[m.start("word"):m.end("word")])
        else:
            yield command[m.start("bare"):m.end("bare")]
    for interp, body in _stdin_program_bodies(command, scan):
        if interp in _STDIN_SHELL_HEADS:
            yield body
    # The same shells fed by a PIPE (DEF-745): the stage before the pipe.
    for head, body in _piped_program_bodies(command):
        if head in _STDIN_SHELL_HEADS:
            yield body


# ── A program's SHELL-OUT calls (447-A step 3, §C5; 2026-09-11) ─────────────
#
# An interpreter head (`python3`, `perl`, `node`, `ruby`, `awk`, `sed`, `git`)
# used to turn `mask_inert_syntax` off for the WHOLE command: rule (2)
# returned the raw text, every separator inside the program synthesised a
# command position, and a program that only MENTIONED a delete was refused on
# the tier maintenance mode cannot bypass -- DEF-616's named user, a heredoc
# trim script carrying the harness's own relaunch line, three re-issues in one
# lane on 2026-09-06 -- while a one-statement program that really HANDED the
# delete to a shell was not refused, because nothing in the program's syntax
# put a command position before the verb (DEF-761: 34 reaching rows unrefused
# at c7b46b9 once the step-3 bench rows were enrolled). The roster's cover on
# these heads came from the body's own separators: eight bodies in nine, and
# the ninth by luck.
#
# The reader replaces the accident. A reader head is on the non-re-parsing
# side of rule (2) -- its quoted arguments, heredoc bodies and comments are
# data, like a rostered head's -- and what its program hands to a shell is
# READ and scanned as a program one level down, exactly as a PowerShell
# program behind `pwsh -Command` is handed to the PowerShell consumers
# (DEF-637): the dangerous records, the write extractor, the secret-read
# roster and, by the operator's widening of §C49's carve-out (2026-09-11),
# the speed-bump predicates, all under `_PS_STDIN_MAX_DEPTH`. What is read:
#   - the literal a shell-out CALL receives: python's `os.system`, `os.popen`,
#     the `subprocess` family, `os.exec*` / `os.spawn*`; perl's `system`,
#     `exec`, backticks, `qx`, a piped `open`; node's `child_process` family;
#     ruby's `system`, `exec`, `spawn`, backticks, `%x`, `IO.popen`, `Open3`;
#     awk's `system`, a `print` into a command, a command into `getline`;
#     GNU sed's `e`; a git alias, credential helper or exec-valued config key
#     given with `-c` or written by `git config`;
#   - an argv LIST joined into a line, a `shlex.split` / `.split()` literal;
#   - the INPUT STREAM of an awk or sed program that executes it (`system`
#     on a non-literal, a bare `e`, `s///e`), with awk's `-v` values;
#   - a program on a POSIX shell's stdin by here-string, and on any reader's
#     or shell's stdin by PIPE (DEF-745): the stage before the pipe -- its
#     heredoc body, its here-string, its last quoted literal, an `echo`'s
#     bare words.
#
# Direction of error, stated: a reader head whose program shells out through
# an idiom no reader knows is SILENT where the raw scan refused it by
# accident. Every idiom above is pinned by an executing row in
# `bench/reachability_differential.py`, and a head joins `_reader_family`
# only with such a row. A head with no reader (`bash`, `sh`, `eval`, `env`,
# `find`, `xargs`, `timeout`, `ssh`, `make`, ...) stays where it was: off
# the roster, its command scanned raw. Declared limits: a shell-out whose
# argument is not a literal; a program read from a FILE (`python3 x.py`,
# `awk -f`, `sed -f`, a git hook, an alias run later); a git config key
# outside the exec-valued set; a shell-out spelled INSIDE another string of
# the same program, which is read as the call it spells (the over-read
# direction, a refusal); program arguments after a piped `-`.

#: Statement boundaries on the MASKED text, for the stage before a pipe: the
#: characters `_CMD_POS_SEP` names (a quoted one has been blanked). The pipe
#: IS a boundary -- a piped program is the stage immediately before its
#: consumer -- and one boundary list per call is searched by bisection, the
#: `_PS_STDIN_SEGMENT_BOUNDARY_RE` discipline.
_STDIN_SEGMENT_BOUNDARY_RE = re.compile(r"[;\n\r(){}&|`]")

#: The POSIX shell heads as a set, for the consumers that dispatch on a
#: piped program's head.
_POSIX_SHELL_HEAD_SET = frozenset(_POSIX_SHELL_HEADS.split("|"))

#: `| <interpreter or shell> [switches] [-]` ending a statement, the target
#: on the same line or -- bash continues a pipeline across it -- after a
#: newline and an optional comment: the program is the stage BEFORE the pipe
#: (DEF-745). Group 1 is an interpreter head (a version or bundle suffix
#: admitted, as the stdin opener admits it), group 2 a POSIX shell head with
#: no suffix (`shasum` and `shellcheck` are not shells). A switch that GIVES
#: the program (`-c`, `-e`, `-m`, `-E`, `-f`, `-F`, `-File`, a `-Command`
#: with a value) refuses the match: the pipe is data then. A bare operand is
#: a script and refuses it too. ReDoS: every adjacent quantifier pair is
#: mutually exclusive (a path prefix ends on `/`, a switch starts on `-`, a
#: value on a non-dash, the trailing `-` sits alone before the lookahead).
_INTERP_PIPE_RE = re.compile(
    r"\|[ \t]*(?:(?:#[^\n]*)?\n[ \t]*)?(?:[\w./-]*/)?"
    r"(?:((?i:" + _INTERP_ALTERNATION + r"))[\w.-]*|(" + _POSIX_SHELL_HEADS + r")\b)"
    r"(?:[ \t]+-(?!(?:c|e|m|E|f|F|File)(?:[ \t]|$))[\w.-]+"
    r"(?:[ \t]+[\w./:=,@%+~][\w./:=,@%+~-]*)?)*"
    r"(?:[ \t]+-)?(?=[ \t]*(?:$|[;|&\n\r)}]))"
)

#: A POSIX shell fed its program by here-string (`bash <<< "..."`, bare or
#: valued switches between, the operator glued or spaced -- bash accepts
#: `sh<<<'...'`, so the arm must not REQUIRE the blank). The heredoc
#: spelling needs no arm -- behind a shell head the body stays raw and the
#: whole-command scan reads it -- and the pipe spelling is `_INTERP_PIPE_RE`'s.
_SHELL_HERESTRING_RE = re.compile(
    _CMD_POS + r"(?:" + _POSIX_SHELL_HEADS + r")\b" + _QUOTED_VERB_TAIL
    # the bounded run (§C52): the unbounded one was quadratic on a repeated
    # head, see `_SHELL_SWITCH_RUN_BOUNDED`
    + _SHELL_SWITCH_RUN_BOUNDED + r"[ \t]*<<<[ \t]*"
)

#: The three statement readers' heads, on the masked text at a command
#: position; the words after each are read from the raw command.
_AWK_HEAD_RE = re.compile(_CMD_POS + r"(?:[gmn]?awk)\b" + _QUOTED_VERB_TAIL)
_SED_HEAD_RE = re.compile(_CMD_POS + r"(?:g?sed)\b" + _QUOTED_VERB_TAIL)
_GIT_HEAD_RE = re.compile(_CMD_POS + _GIT_VERB + r"\b" + _QUOTED_VERB_TAIL)

#: git config keys whose value is a program run through a shell. An `alias.*`
#: or `credential[.<url>].helper` value is a program only behind a leading
#: `!`. The subsection shapes (`filter.<name>.clean`, `difftool.<tool>.cmd`)
#: are matched by prefix and suffix around a non-empty middle.
_GIT_EXEC_VALUED_KEYS = frozenset({
    "core.pager", "core.editor", "core.sshcommand", "core.fsmonitor",
    "core.askpass", "diff.external", "sequence.editor", "gpg.program",
    "gpg.ssh.program", "uploadpack.packobjectshook",
})
_GIT_EXEC_VALUED_KEY_SHAPES = (
    ("filter.", ".clean"), ("filter.", ".smudge"), ("filter.", ".process"),
    ("diff.", ".textconv"), ("diff.", ".command"),
    ("difftool.", ".cmd"), ("mergetool.", ".cmd"),
)
#: The `filter-branch` options whose value is a shell filter.
_GIT_FILTER_OPTIONS = frozenset({
    "--tree-filter", "--index-filter", "--env-filter", "--commit-filter",
    "--msg-filter", "--parent-filter", "--tag-name-filter",
})

#: Inside a PROGRAM: the call heads. The argument after each is read by hand
#: (`_read_call_args`), so no regex ever reads a literal -- the linear-time
#: discipline the ReDoS receipt asks of every body regex.
_PY_SHELL_OUT_HEAD_RE = re.compile(
    r"(?<![\w.])(?:os[ \t]*\.[ \t]*(?:system|popen|exec[lvpe]{1,3}|spawn[lvpe]{1,3})"
    r"|subprocess[ \t]*\.[ \t]*(?:run|call|check_call|check_output|Popen|getoutput"
    r"|getstatusoutput)|commands[ \t]*\.[ \t]*getoutput"
    r"|run|call|check_call|check_output|Popen|system|popen|getoutput)[ \t]*\([ \t]*"
)
_JS_SHELL_OUT_HEAD_RE = re.compile(
    r"\b(?:exec|execSync|spawn|spawnSync|execFile|execFileSync)[ \t]*\([ \t]*"
)
_PERL_SHELL_OUT_HEAD_RE = re.compile(
    r"(?<![\w$@%])(?:system|exec)[ \t]*(?:\([ \t]*)?"
)
_PERL_OPEN_PIPE_RE = re.compile(
    r"(?<![\w$@%])open[ \t]*(?:\([ \t]*)?(?:my[ \t]+)?[\w$:]+[ \t]*,[ \t]*"
)
_PERL_QX_RE = re.compile(r"(?<![\w$@%])qx(?=[ \t]*[^\w\s])")
_RUBY_SHELL_OUT_HEAD_RE = re.compile(
    r"(?<![\w.:@$])(?:system|exec|spawn|IO[ \t]*\.[ \t]*popen"
    r"|Open3[ \t]*\.[ \t]*\w+|Kernel[ \t]*\.[ \t]*(?:system|exec|spawn))[ \t]*(?:\([ \t]*)?"
)
_RUBY_PERCENT_X_RE = re.compile(r"%x(?=[^\w\s])")
_AWK_SYSTEM_RE = re.compile(r"\bsystem[ \t]*\([ \t]*")
_AWK_STRING_RE = re.compile(r"\"((?:[^\"\\\n]|\\[\s\S])*)\"")
_AWK_GETLINE_RE = re.compile(r"\"((?:[^\"\\\n]|\\[\s\S])*)\"[ \t]*\|[ \t]*getline\b")
_AWK_PIPE_TO_CMD_RE = re.compile(r"\|[ \t]*\"((?:[^\"\\\n]|\\[\s\S])*)\"")
#: GNU sed's `e`: with text it runs that text; bare (or as the `e` flag of a
#: substitution) it runs the PATTERN SPACE -- the input stream, line by line.
_SED_E_COMMAND_RE = re.compile(
    r"(?:^|[;\n{])[ \t]*e(?:[ \t]+([^\n]+)|(?=[ \t]*(?:[;\n}]|$)))"
)
_SED_S_E_FLAG_RE = re.compile(
    r"(?:^|[;\n{])[ \t]*s(.)(?:\\[\s\S]|(?!\1)[^\\\n])*\1(?:\\[\s\S]|(?!\1)[^\\\n])*\1"
    r"[0-9gpiImMw]*e"
)
#: The file WRITES an awk or sed program makes with no shell at all -- read
#: by the write extractor, because a reader head's program is data to the
#: raw scan now (the failure-mode review drove an awk redirect into a hook
#: landing behind the relief). awk: `print ... > "path"` and `>>`; sed: the
#: `w path` command (to end of line) and the `w path` flag of a substitution.
_AWK_REDIRECT_WRITE_RE = re.compile(r"(?<![<>])>>?[ \t]*\"((?:[^\"\\\n]|\\[\s\S])*)\"")
_SED_W_COMMAND_RE = re.compile(r"(?:^|[;\n{])[ \t]*w[ \t]+([^\n]+)")
_SED_S_W_FLAG_RE = re.compile(
    r"(?:^|[;\n{])[ \t]*s(.)(?:\\[\s\S]|(?!\1)[^\\\n])*\1(?:\\[\s\S]|(?!\1)[^\\\n])*\1"
    r"[0-9gpiImMe]*w[ \t]+([^\n]+)"
)

_BRACKET_CLOSER = {"(": ")", "[": "]", "{": "}", "<": ">"}


def _read_shell_word(command: str, i: int) -> tuple[str, int]:
    """One bash word from `i`: its quote-removed text and the index past it.
    A single-quoted run is verbatim; a double-quoted or `$'...'` run is
    unescaped the way bash hands it over (`_bash_unescape_program`); a
    backslash escapes the next character; the word ends at unquoted
    whitespace or at a separator, grouping or redirect character. An
    unterminated quote runs to the end (bash would wait for more input; the
    hook reads what it was given)."""
    n = len(command)
    out: list[str] = []
    j = i
    while j < n:
        c = command[j]
        if c == "'":
            k = command.find("'", j + 1)
            out.append(command[j + 1:] if k < 0 else command[j + 1:k])
            j = n if k < 0 else k + 1
            continue
        if c == "$" and j + 1 < n and command[j + 1] == "'":
            k = j + 2
            while k < n and command[k] != "'":
                k += 2 if command[k] == "\\" else 1
            out.append(_bash_unescape_program(command[j + 2:k], "$'"))
            j = k + 1
            continue
        if c == "$" and j + 1 < n and command[j + 1] == '"':
            # the locale form `$"..."`: bash drops the marker and reads the
            # double-quoted segment (DEF-832's review: the word grammar
            # admitted the form and this reader handed the marker on, so a
            # program's first word was a verb that does not exist)
            j += 1
            continue
        if c == '"':
            try:
                k = _close_double_quote(command, j)
            except _UnresolvedShellSyntax:
                k = -1
            out.append(_bash_unescape_program(
                command[j + 1:] if k < 0 else command[j + 1:k], '"'))
            j = n if k < 0 else k + 1
            continue
        if c == "\\" and j + 1 < n:
            out.append(command[j + 1])
            j += 2
            continue
        if c in " \t\n\r;|&<>(){}`":
            break
        out.append(c)
        j += 1
    return "".join(out), j


def _statement_words(
    command: str, scan: str, start: int,
) -> tuple[list[str], int | None, str | None]:
    """The arguments of the statement whose head ends at `start`: each word
    quote-removed from the RAW command; the offset of a heredoc operator in
    the statement, if any; a here-string word, if any. A redirect and its
    target are stepped over. The statement ends at the first character the
    MASKED twin leaves as live syntax, so a separator inside a quoted word
    never ends it."""
    words: list[str] = []
    heredoc_op: int | None = None
    herestring: str | None = None
    n = len(command)
    j = start
    while j < n:
        c = scan[j]
        if c in " \t":
            j += 1
            continue
        if c in ";|&\n\r(){}`":
            break
        if c in "<>" or (c.isdigit() and j + 1 < n and scan[j + 1] in "<>"):
            if command.startswith("<<<", j):
                k = j + 3
                while k < n and command[k] in " \t":
                    k += 1
                herestring, j = _read_shell_word(command, k)
                continue
            if command.startswith("<<", j):
                if heredoc_op is None:
                    heredoc_op = j
                try:
                    j, _spec = _read_heredoc_operator(command, j)
                except _UnresolvedShellSyntax:
                    j += 2
                continue
            while j < n and command[j] in "<>0123456789":
                j += 1
            if j < n and command[j] == "&":         # `2>&1`: the target is a descriptor
                j += 1
                while j < n and command[j] in "0123456789-":
                    j += 1
                continue
            while j < n and command[j] in " \t":
                j += 1
            if j < n and command[j] not in ";|&\n\r(){}`":
                _, j = _read_shell_word(command, j)
            continue
        text, after = _read_shell_word(command, j)
        if after <= j:
            j += 1
            continue
        words.append(text)
        j = after
    return words, heredoc_op, herestring


def _pipe_scan(command: str) -> str:
    """The command with every quoted span (single, double, ANSI-C), every
    backslash-escaped character and every comment blanked to spaces, the
    same length, newlines outside them kept: the text the pipe arm reads
    separators and consumers from, independent of rule (2). A heredoc body
    is not blanked here (a pipe on a body line would be read as a consumer:
    the over-read direction, a scan of data as a program)."""
    out = list(command)
    n = len(command)
    i = 0
    while i < n:
        c = command[i]
        if c == "\\" and i + 1 < n:
            out[i] = " "
            if command[i + 1] != "\n":
                out[i + 1] = " "
            i += 2
            continue
        # A command or arithmetic substitution, and a backtick one: blanked
        # whole, so its parentheses and backticks are not stage boundaries (a
        # stage carrying `$(date)` after its literal was cut at the `(` and
        # the literal went unread: failure-mode review).
        if c == "$" and i + 1 < n and command[i + 1] == "(":
            depth = 0
            j = i + 1
            while j < n:
                if command[j] == "\\":
                    j += 2
                    continue
                if command[j] == "(":
                    depth += 1
                elif command[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            for k in range(i, min(j + 1, n)):
                out[k] = " "
            i = j + 1
            continue
        if c == "`":
            j = i + 1
            while j < n and command[j] != "`":
                j += 2 if command[j] == "\\" else 1
            for k in range(i, min(j + 1, n)):
                out[k] = " "
            i = j + 1
            continue
        if c == "'" or (c == "$" and i + 1 < n and command[i + 1] == "'"):
            ansi = c == "$"
            j = i + (2 if ansi else 1)
            while j < n and command[j] != "'":
                j += 2 if (ansi and command[j] == "\\") else 1
            for k in range(i, min(j + 1, n)):
                out[k] = " "
            i = j + 1
            continue
        if c == '"':
            try:
                j = _close_double_quote(command, i)
            except _UnresolvedShellSyntax:
                j = n - 1
            for k in range(i, j + 1):
                out[k] = " "
            i = j + 1
            continue
        if c == "#" and (i == 0 or command[i - 1] in " \t\n;|&("):
            j = command.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def _stage_boundaries(scan: str, end: int | None = None) -> list[int]:
    """The statement boundaries on the pipe arm's scan, up to `end`: every
    separator, grouping or pipe character EXCEPT the ampersand of a redirect
    duplication (`2>&1`, `&>`), which is part of its operator -- the reading
    the walker settled one step earlier, inherited here (the failure-mode
    review drove `2>&1 |` before an interpreter cutting the stage to one
    character, on the tier maintenance mode cannot bypass)."""
    return [
        b.start() for b in _STDIN_SEGMENT_BOUNDARY_RE.finditer(
            scan, 0, len(scan) if end is None else end)
        if scan[b.start()] != "&" or not _is_redirect_dup_ampersand(scan, b.start())
    ]


def _stage_before(scan: str, at: int, boundaries: list[int]) -> int:
    """The start of the pipeline stage that ends at the boundary at `at`."""
    i = bisect.bisect_left(boundaries, at)
    return boundaries[i - 1] + 1 if i else 0


def _last_quoted_literal(command: str, start: int, end: int) -> str | None:
    """The last quoted word in `command[start:end]`, quote-removed."""
    j = start
    last: str | None = None
    while j < end:
        c = command[j]
        if c == "\\":
            j += 2
            continue
        if c in "'\"" or (c == "$" and j + 1 < end and command[j + 1] == "'"):
            text, after = _read_shell_word(command, j)
            last = text
            j = max(after, j + 1)
            continue
        j += 1
    return last


def _stage_program(command: str, scan: str, start: int, end: int) -> str | None:
    """The program a pipeline stage `command[start:end]` hands on: its heredoc
    body, its here-string word, else its last quoted literal, else -- under
    an `echo` or `printf` head, whose bare words are the text -- the words
    after the head and its options (a `printf` format holding `%` is dropped
    when arguments follow it). None for a stage that produces its output
    some other way (`cat file | sh`: file-mediated, out of scope)."""
    piece = scan[start:end]
    at = piece.find("<<<")
    if at >= 0:
        k = start + at + 3
        while k < end and command[k] in " \t":
            k += 1
        return _read_shell_word(command, k)[0]
    at = piece.find("<<")
    if at >= 0:
        return _heredoc_body_after(command, start + at)
    literal = _last_quoted_literal(command, start, end)
    if literal is not None:
        return literal
    k = start
    while k < end and command[k] in " \t\n\r":
        k += 1
    head, after = _read_shell_word(command, k)
    head = head.rsplit("/", 1)[-1]
    if head not in ("echo", "printf") or after > end:
        return None
    words, _op, _hs = _statement_words(command, scan, after)
    while words and head == "echo" and words[0].startswith("-") and len(words[0]) > 1:
        words.pop(0)
    if head == "printf" and len(words) > 1 and "%" in words[0]:
        words.pop(0)
    return " ".join(words) if words else None


def _piped_program_bodies(command: str) -> Iterator[tuple[str, str]]:
    """Yield ``(head, program)`` for every interpreter or shell that reads its
    program from a PIPE (DEF-745): the head lower-cased, the program the
    stage before the pipe (`_stage_program`). Opener on the arm's own masked
    twin, program from ``command`` by offset.

    The masked twin is the arm's OWN (`_pipe_scan`), not the walker's -- which
    is why this helper takes no `scan`, unlike its siblings: behind a shell
    head the walker returns the whole command raw (rule 2), so a quoted `|
    sh` inside the very literal being piped would be a stage boundary and
    the stage would be read from the wrong place; and the walker blanks the
    newline that ends a heredoc's operator line, so a piped consumer on that
    line (`cat <<'EOF' | sh`) would never meet the opener's end-of-statement
    lookahead. Same length, quotes, substitutions and comments blanked,
    every raw newline kept."""
    scan = _pipe_scan(command)
    boundaries = _stage_boundaries(scan)
    for m in _INTERP_PIPE_RE.finditer(scan):
        head = (m.group(1) or m.group(2) or "").lower()
        start = _stage_before(scan, m.start(), boundaries)
        if not command[start:m.start()].strip():
            continue
        program = _stage_program(command, scan, start, m.start())
        if program is not None:
            yield head, program


def _read_delimited(
    body: str, i: int, close: str, *, escapes: bool = True,
    opener: str | None = None, line_bound: bool = False,
) -> tuple[str, int]:
    """The text of a literal opened just before `i`, to its closer `close`
    (a bracket pair balanced when `opener` is given), and the index past
    the closer. A backslash escapes the next character when `escapes`
    (`\\n` and `\\t` become the characters they name, the rest keep the
    character they escape). A `line_bound` literal ends at a newline, as a
    single-quoted Python or JavaScript string does. Unterminated: to the end."""
    out: list[str] = []
    depth = 0
    n = len(body)
    j = i
    while j < n:
        c = body[j]
        if escapes and c == "\\" and j + 1 < n:
            nxt = body[j + 1]
            out.append("\n" if nxt == "n" else "\t" if nxt == "t" else nxt)
            j += 2
            continue
        if line_bound and c == "\n":
            return "".join(out), j
        if opener is not None and c == opener:
            depth += 1
        elif c == close:
            if depth == 0:
                return "".join(out), j + 1
            depth -= 1
        out.append(c)
        j += 1
    return "".join(out), n


def _read_triple(body: str, i: int, quote: str, escapes: bool) -> tuple[str, int]:
    """A Python triple-quoted literal from `i` (just past the opener)."""
    triple = quote * 3
    out: list[str] = []
    n = len(body)
    j = i
    while j < n:
        c = body[j]
        if escapes and c == "\\" and j + 1 < n:
            nxt = body[j + 1]
            out.append("\n" if nxt == "n" else "\t" if nxt == "t" else nxt)
            j += 2
            continue
        if body.startswith(triple, j):
            return "".join(out), j + 3
        out.append(c)
        j += 1
    return "".join(out), n


def _read_literal(body: str, i: int, family: str) -> tuple[str, int] | None:
    """A string literal of `family` starting at `i` -- its text as the
    program would hand it on, and the index past it -- or None when `i` does
    not open one. Python: an optional prefix, triple or single quotes (a raw
    literal keeps its backslashes). JavaScript: quotes or a template literal.
    Perl: quotes, `q`/`qq`/`qw`/`qx` with any delimiter, backticks. Ruby:
    quotes, `%q`/`%Q`/`%w`/`%W`/`%x`/`%` with any delimiter, backticks. awk:
    double quotes."""
    n = len(body)
    if i >= n:
        return None
    c = body[i]
    if family == "python":
        k = i
        while k < n and k - i < 2 and body[k] in "rRbBuUfF":
            k += 1
        if k >= n or body[k] not in "'\"":
            return None
        raw = "r" in body[i:k].lower()
        q = body[k]
        if body.startswith(q * 3, k):
            return _read_triple(body, k + 3, q, not raw)
        return _read_delimited(body, k + 1, q, escapes=not raw, line_bound=True)
    if family == "node":
        if c in "'\"":
            return _read_delimited(body, i + 1, c, line_bound=True)
        if c == "`":
            return _read_delimited(body, i + 1, "`")
        return None
    if family in ("perl", "ruby"):
        if c in "'\"`":
            return _read_delimited(body, i + 1, c, escapes=c != "'")
        if (family == "perl" and c == "q") or (family == "ruby" and c == "%"):
            k = i + 1
            if k < n and body[k] in ("qwx" if family == "perl" else "qQwWx"):
                k += 1
            if family == "perl":
                while k < n and body[k] in " \t":
                    k += 1
            if k >= n or body[k].isalnum() or body[k] in " \t_":
                return None
            d = body[k]
            return _read_delimited(body, k + 1, _BRACKET_CLOSER.get(d, d),
                                   opener=d if d in _BRACKET_CLOSER else None)
        return None
    if family == "awk" and c == '"':
        return _read_delimited(body, i + 1, '"', line_bound=True)
    return None


def _argv_element(word: str) -> str:
    """One element of an argv LIST (or one word of a `.split()` literal) as
    the readers should see it. A word that IS a shell operator token -- a
    pipe, a chain, a separator, a redirection, with or without a descriptor
    digit -- is DATA to the process, not syntax: ``subprocess.run(["find",
    ".", "|", "xargs", "rm"])`` hands find a literal pipe and runs nothing
    behind it (the differential's argv-list wrappers read as inert; the
    carrier arm drew four new false denies from them and twelve older ones
    stood before this, DEF-826). Such a word becomes a bare dash, a word no
    reader takes as syntax or as a verb, so the verb after it is off command
    position and a pipe before it is no pipe. A word with a BLANK in it is
    one argument -- a program body handed to a shell's `-c` -- and is
    re-quoted in a form the nested-shell reader re-parses: single quotes,
    or double quotes when the word holds a single quote and nothing the
    double quotes would expand (the first cut spelled an embedded quote with
    the POSIX escape, which no reader re-parses, and a protected-path write
    inside such a body went unread). Every other word -- a path, a switch, a
    word carrying a separator -- is joined as it was, because quoting a
    separator truncates the rm tier's span (both from the review of the
    first cut)."""
    core = word.strip("0123456789")
    if core and all(ch in "|;&<>" for ch in core):
        return "-"
    if any(ch in word for ch in " \t\n"):
        # one argument with a blank in it is one argument: re-quoted in a
        # form the nested-shell reader re-parses (never the POSIX escape of
        # an embedded quote, which no reader re-parses -- that hid a
        # protected-path write inside a -c body)
        if "'" not in word:
            return "'" + word + "'"
        if not any(ch in word for ch in '"$`'):
            return '"' + word + '"'
    return word


def _read_call_args(body: str, i: int, family: str) -> str:
    """The text a call hands to a shell, read from its argument list at `i`:
    every leading literal (a string, an argv list `[...]`, a `shlex.split`
    or `.split()` of a literal), joined with spaces, stopping at the first
    argument that is not one. Empty when the first argument is not a literal
    (a variable, an f-string with a name inside it: a declared limit). A list
    element or a split word is one process argument, spelled as such
    (`_argv_element`); a plain string literal is the shell line it is."""
    n = len(body)
    texts: list[str] = []
    j = i
    while True:
        while j < n and body[j] in " \t\n":
            j += 1
        if body.startswith("shlex.split", j):
            j = body.find("(", j)
            if j < 0:
                break
            j += 1
            while j < n and body[j] in " \t":
                j += 1
            lit = _read_literal(body, j, family)
            if lit is None:
                break
            # a shlex.split literal is an argv list too: split as the process
            # will see it, each word one argument (a pipe word is data; a body
            # with blanks is one word, re-quoted); an unlexable literal is the
            # shell line it spells
            try:
                words = shlex.split(lit[0])
            except ValueError:
                words = None
            texts.append(lit[0] if words is None else " ".join(_argv_element(w) for w in words))
            j = lit[1]
            while j < n and body[j] in " \t":
                j += 1
            if j < n and body[j] == ")":
                j += 1
        elif j < n and body[j] == "[":
            k = j + 1
            elems: list[str] = []
            while True:
                while k < n and body[k] in " \t\n":
                    k += 1
                lit = _read_literal(body, k, family)
                if lit is None:
                    break
                elems.append(lit[0])
                k = lit[1]
                while k < n and body[k] in " \t\n":
                    k += 1
                if k < n and body[k] == ",":
                    k += 1
                    continue
                break
            if not elems:
                break
            texts.append(" ".join(_argv_element(e) for e in elems))
            if k < n and body[k] == "]":
                k += 1
            j = k
        else:
            lit = _read_literal(body, j, family)
            if lit is None:
                break
            j = lit[1]
            while j < n and body[j] in " \t":
                j += 1
            if body.startswith(".split(", j):
                # a split literal is an argv list: each word one argument
                texts.append(" ".join(_argv_element(w) for w in lit[0].split()))
                k = body.find(")", j)
                j = n if k < 0 else k + 1
            else:
                texts.append(lit[0])
        while j < n and body[j] in " \t\n":
            j += 1
        if j < n and body[j] == ",":
            j += 1
            continue
        break
    return " ".join(t for t in texts if t)


def _backtick_texts(body: str) -> list[str]:
    """Every backtick-quoted command in a perl or ruby program."""
    out: list[str] = []
    n = len(body)
    j = 0
    while j < n:
        c = body[j]
        if c == "\\":
            j += 2
            continue
        if c == "`":
            text, j = _read_delimited(body, j + 1, "`")
            if text.strip():
                out.append(text)
            continue
        j += 1
    return out


def _python_shell_outs(body: str) -> list[str]:
    return [t for m in _PY_SHELL_OUT_HEAD_RE.finditer(body)
            if (t := _read_call_args(body, m.end(), "python"))]


def _node_shell_outs(body: str) -> list[str]:
    return [t for m in _JS_SHELL_OUT_HEAD_RE.finditer(body)
            if (t := _read_call_args(body, m.end(), "node"))]


def _perl_shell_outs(body: str) -> list[str]:
    out = [t for m in _PERL_SHELL_OUT_HEAD_RE.finditer(body)
           if (t := _read_call_args(body, m.end(), "perl"))]
    for m in _PERL_QX_RE.finditer(body):
        lit = _read_literal(body, m.start(), "perl")
        if lit is not None and lit[0].strip():
            out.append(lit[0])
    out.extend(_backtick_texts(body))
    for m in _PERL_OPEN_PIPE_RE.finditer(body):
        # `open(FH, "cmd |")`, `open(FH, "| cmd")`, `open(FH, "-|", "cmd")`
        first = _read_literal(body, m.end(), "perl")
        if first is None:
            continue
        mode = first[0].strip()
        if mode in ("-|", "|-"):
            k = first[1]
            while k < len(body) and body[k] in " \t":
                k += 1
            if k < len(body) and body[k] == ",":
                k += 1
                while k < len(body) and body[k] in " \t\n":
                    k += 1
                second = _read_literal(body, k, "perl")
                if second is not None and second[0].strip():
                    out.append(second[0])
        elif mode.endswith("|"):
            out.append(mode[:-1])
        elif mode.startswith("|"):
            out.append(mode[1:])
    return out


def _ruby_shell_outs(body: str) -> list[str]:
    out = [t for m in _RUBY_SHELL_OUT_HEAD_RE.finditer(body)
           if (t := _read_call_args(body, m.end(), "ruby"))]
    for m in _RUBY_PERCENT_X_RE.finditer(body):
        lit = _read_literal(body, m.start(), "ruby")
        if lit is not None and lit[0].strip():
            out.append(lit[0])
    out.extend(_backtick_texts(body))
    return out


def _shell_outs_in(family: str, body: str) -> list[str]:
    """Every literal a program of `family` hands to a shell."""
    if family == "python":
        return _python_shell_outs(body)
    if family == "node":
        return _node_shell_outs(body)
    if family == "perl":
        return _perl_shell_outs(body)
    if family == "ruby":
        return _ruby_shell_outs(body)
    return []


def _awk_unescape(text: str) -> str:
    return _read_delimited(text + '"', 0, '"')[0]


def _awk_shell_outs(program: str) -> tuple[list[str], bool]:
    """(the literals an awk program hands to a shell, whether its INPUT is
    one): `system` on a literal, a command into `getline`, a `print` into a
    command -- and, when the command is a shell, what is printed; `system`
    on a non-literal (`$0`, a variable) makes the input stream and the `-v`
    values live."""
    texts: list[str] = []
    stream_live = False
    for m in _AWK_SYSTEM_RE.finditer(program):
        lit = _read_literal(program, m.end(), "awk")
        if lit is None:
            stream_live = True
        elif lit[0].strip():
            texts.append(lit[0])
    for m in _AWK_GETLINE_RE.finditer(program):
        texts.append(_awk_unescape(m.group(1)))
    literal_starts: list[int] = []
    literal_ends: list[int] = []
    for s in _AWK_STRING_RE.finditer(program):
        literal_starts.append(s.start())
        literal_ends.append(s.end())
    for m in _AWK_PIPE_TO_CMD_RE.finditer(program):
        cmd = _awk_unescape(m.group(1))
        texts.append(cmd)
        head = cmd.split()[0].rsplit("/", 1)[-1] if cmd.split() else ""
        if head in _POSIX_SHELL_HEAD_SET:
            # The print statement's start: the last `;`, `{` or newline before
            # the pipe that sits OUTSIDE a string literal. A separator inside
            # the printed text (`print "true; <delete>" | "sh"`) cut the
            # segment short and the printed program went unread -- four
            # fail-opens in the differential's first run of this reader.
            k = m.start() - 1
            while k >= 0:
                if program[k] in ";{\n":
                    idx = bisect.bisect_right(literal_starts, k) - 1
                    if idx < 0 or k >= literal_ends[idx]:
                        break
                k -= 1
            printed = [_awk_unescape(s) for s in
                       _AWK_STRING_RE.findall(program[k + 1:m.start()])]
            if printed:
                texts.append(" ".join(printed))
            else:
                # A VARIABLE printed into the shell (`x = "..."; print x |
                # "sh"`, `print $0 | "sh"`): what it holds came from a literal
                # elsewhere in the program, a `-v` value or the input -- all
                # of them live (code review, driven with a marker).
                texts.extend(_awk_unescape(s) for s in _AWK_STRING_RE.findall(program))
                stream_live = True
    return texts, stream_live


def _sed_shell_outs(script: str) -> tuple[list[str], bool]:
    """(the commands a sed script runs through GNU `e`, whether the pattern
    space -- the input stream -- is run)."""
    texts: list[str] = []
    stream_live = False
    for m in _SED_E_COMMAND_RE.finditer(script):
        if m.group(1):
            texts.append(m.group(1))
        else:
            stream_live = True
    if _SED_S_E_FLAG_RE.search(script):
        stream_live = True
    return texts, stream_live


def _pipe_into(scan: str, at: int) -> int | None:
    """The offset of the `|` that hands its stage to the head opened at `at`
    (the separator a `_CMD_POS` match starts on), across a newline and
    blanks; None when the head did not open at a pipe."""
    n = len(scan)
    if at < n and scan[at] == "|":
        return at
    if at < n and scan[at] in "\n\r":
        k = at - 1
        while k >= 0 and scan[k] in " \t\r":
            k -= 1
        if k >= 0 and scan[k] == "|":
            return k
    return None


def _stream_of(
    command: str, scan: str, at: int, heredoc_op: int | None, herestring: str | None,
) -> str | None:
    """The input stream of the statement whose head opened at `at`: its
    here-string, its heredoc body, or the stage piped into it."""
    if herestring is not None:
        return herestring
    if heredoc_op is not None:
        return _heredoc_body_after(command, heredoc_op)
    pipe = _pipe_into(scan, at)
    if pipe is None:
        return None
    # The stage is segmented on the pipe arm's own scan, as `_piped_program_
    # bodies` does and for the same reason (a quoted separator in the stage
    # is not a boundary; a redirect duplication's ampersand is not either).
    pscan = _pipe_scan(command)
    return _stage_program(command, pscan, _stage_before(pscan, pipe, _stage_boundaries(pscan, pipe)), pipe)


def _awk_program_bodies(
    command: str, scan: str,
) -> Iterator[tuple[str, list[str], int, int | None, str | None]]:
    """Yield ``(program, -v values, head offset, heredoc operator offset,
    here-string)`` for every awk statement: the program word quote-removed
    from the RAW command, the opener matched on ``scan`` at a command
    position. The shell-out and file-write readers both consume it. A
    program in a file (`-f`) is a declared limit."""
    if len(scan) != len(command):
        scan = command
    for m in _AWK_HEAD_RE.finditer(scan):
        if not command[m.end():].strip():
            continue
        words, heredoc_op, herestring = _statement_words(command, scan, m.end())
        program: str | None = None
        values: list[str] = []
        i = 0
        while i < len(words):
            w = words[i]
            if w == "--":
                program = words[i + 1] if i + 1 < len(words) else None
                break
            if w in ("-F", "-f"):
                i += 2
                continue
            if w == "-v":
                if i + 1 < len(words):
                    values.append(words[i + 1].split("=", 1)[-1])
                i += 2
                continue
            if w.startswith("-v") and "=" in w:
                values.append(w[2:].split("=", 1)[-1])
                i += 1
                continue
            if w.startswith("-"):
                i += 1
                continue
            program = w
            break
        if program is not None:
            yield program, values, m.start(), heredoc_op, herestring


def _awk_shell_out_texts(command: str, scan: str) -> Iterator[str]:
    """What an awk statement hands to a shell: the literals its program gives
    `system`, pipes into a command or reads through `getline`, and -- when
    `system` or a print into a shell takes a non-literal -- the `-v` values
    and the input stream."""
    for program, values, at, heredoc_op, herestring in _awk_program_bodies(command, scan):
        texts, stream_live = _awk_shell_outs(program)
        yield from texts
        if stream_live:
            yield from (v for v in values if v.strip())
            stream = _stream_of(command, scan, at, heredoc_op, herestring)
            if stream and stream.strip():
                yield stream


def _awk_sed_write_paths(command: str, scan: str) -> list[str]:
    """The files an awk or sed program writes with no shell at all: awk's
    `print ... > "path"` / `>>`, sed's `w path` command and the `w path`
    flag of a substitution. Read by the write extractor because a reader
    head's program is data to the raw scan now."""
    paths: list[str] = []
    for program, _values, _at, _op, _hs in _awk_program_bodies(command, scan):
        paths.extend(_awk_unescape(m.group(1)) for m in _AWK_REDIRECT_WRITE_RE.finditer(program))
    for script, _at, _op, _hs in _sed_program_bodies(command, scan):
        paths.extend(m.group(1).strip() for m in _SED_W_COMMAND_RE.finditer(script))
        paths.extend(m.group(2).strip() for m in _SED_S_W_FLAG_RE.finditer(script))
    return [p for p in paths if p]


def _sed_shell_out_texts(command: str, scan: str) -> Iterator[str]:
    """What a sed statement runs through GNU `e`: the command text of an `e`
    with an argument, and -- under a bare `e` or an `s///e` -- the input
    stream."""
    for script, at, heredoc_op, herestring in _sed_program_bodies(command, scan):
        texts, stream_live = _sed_shell_outs(script)
        yield from texts
        if stream_live:
            stream = _stream_of(command, scan, at, heredoc_op, herestring)
            if stream and stream.strip():
                yield stream


def _sed_program_bodies(
    command: str, scan: str,
) -> Iterator[tuple[str, int, int | None, str | None]]:
    """Yield ``(script, head offset, heredoc operator offset, here-string)``
    for every sed statement: the script is every `-e` / `--expression` value
    joined by newlines, else the first positional word, quote-removed from
    the RAW command, the opener matched on ``scan`` at a command position.
    The shell-out and file-write readers both consume it. A script in a
    file (`-f`) is a declared limit."""
    if len(scan) != len(command):
        scan = command
    for m in _SED_HEAD_RE.finditer(scan):
        if not command[m.end():].strip():
            continue
        words, heredoc_op, herestring = _statement_words(command, scan, m.end())
        scripts: list[str] = []
        positional: str | None = None
        i = 0
        while i < len(words):
            w = words[i]
            if w == "--":
                if positional is None and i + 1 < len(words):
                    positional = words[i + 1]
                break
            if w in ("-e", "--expression"):
                if i + 1 < len(words):
                    scripts.append(words[i + 1])
                i += 2
                continue
            if w.startswith("--expression="):
                scripts.append(w[len("--expression="):])
                i += 1
                continue
            if w.startswith("--"):
                i += 2 if w in ("--file", "--line-length") else 1
                continue
            if w.startswith("-") and len(w) > 1:
                cluster = w[1:]
                if "e" in cluster:
                    rest = cluster.split("e", 1)[1]
                    if rest:
                        scripts.append(rest)
                        i += 1
                    elif i + 1 < len(words):
                        scripts.append(words[i + 1])
                        i += 2
                    else:
                        i += 1
                    continue
                i += 2 if ("f" in cluster or cluster == "l") else 1
                continue
            if positional is None:
                positional = w
                break
            i += 1
        if not scripts and positional is not None:
            scripts.append(positional)
        if scripts:
            yield "\n".join(scripts), m.start(), heredoc_op, herestring


def _git_config_program(assignment: str) -> str | None:
    """The program a `key=value` git setting runs, or None: an `alias.*` or
    `credential[.<url>].helper` value behind a leading `!`, an exec-valued
    key's value as it stands."""
    key, sep, value = assignment.partition("=")
    if not sep:
        return None
    k = key.strip().lower()
    if k.startswith("alias.") or (k.startswith("credential.") and k.endswith(".helper")) \
            or k == "credential.helper":
        return value[1:] if value.startswith("!") else None
    if k in _GIT_EXEC_VALUED_KEYS or any(
            k.startswith(p) and k.endswith(s) and len(k) > len(p) + len(s)
            for p, s in _GIT_EXEC_VALUED_KEY_SHAPES):
        return value or None
    return None


def _git_program_bodies(command: str, scan: str) -> Iterator[str]:
    """Yield the programs a git statement runs through a shell: a `-c`
    setting's value and a `git config` write's value, for an alias or a
    credential helper behind `!` and for the exec-valued keys. Opener on
    ``scan`` at a command position; the words after it from ``command``."""
    if len(scan) != len(command):
        scan = command
    for m in _GIT_HEAD_RE.finditer(scan):
        if not command[m.end():].strip():
            continue
        words, _op, _hs = _statement_words(command, scan, m.end())
        i = 0
        while i < len(words):
            w = words[i]
            if w == "-c":
                if i + 1 < len(words):
                    program = _git_config_program(words[i + 1])
                    if program:
                        yield program
                i += 2
                continue
            if w.startswith("-c") and "=" in w:
                program = _git_config_program(w[2:])
                if program:
                    yield program
                i += 1
                continue
            if w in ("-C", "--git-dir", "--work-tree", "--namespace", "--exec-path"):
                i += 2
                continue
            if w.startswith("-"):
                i += 1
                continue
            rest = words[i + 1:]
            if w == "config":
                k = 0
                while k < len(rest) and rest[k].startswith("-"):
                    k += 2 if rest[k] in ("-f", "--file") else 1
                if k + 1 < len(rest):
                    program = _git_config_program(rest[k] + "=" + rest[k + 1])
                    if program:
                        yield program
            # The subcommand doors: each hands its argument to a shell (git
            # joins `submodule foreach`'s and `bisect run`'s words into one
            # line first). Both reviews drove `rebase --exec` and `submodule
            # foreach` into a hook after `git` joined the readers with the
            # `-c` and `config` doors alone.
            elif w == "submodule":
                if rest and rest[0] == "foreach":
                    k = 1
                    while k < len(rest) and rest[k].startswith("-"):
                        k += 1
                    if k < len(rest):
                        yield " ".join(rest[k:])
            elif w == "filter-branch":
                for k, r in enumerate(rest):
                    if r in _GIT_FILTER_OPTIONS and k + 1 < len(rest):
                        yield rest[k + 1]
                    elif r.startswith("--") and "-filter=" in r:
                        if r.split("=", 1)[0] in _GIT_FILTER_OPTIONS:
                            yield r.split("=", 1)[1]
            elif w == "rebase":
                for k, r in enumerate(rest):
                    if r in ("--exec", "-x") and k + 1 < len(rest):
                        yield rest[k + 1]
                    elif r.startswith("--exec="):
                        yield r[len("--exec="):]
            elif w == "bisect":
                if len(rest) > 1 and rest[0] == "run":
                    yield " ".join(rest[1:])
            elif w == "difftool":
                for k, r in enumerate(rest):
                    if r in ("--extcmd", "-x") and k + 1 < len(rest):
                        yield rest[k + 1]
                    elif r.startswith("--extcmd="):
                        yield r[len("--extcmd="):]
            break


def _reader_program_bodies(command: str, scan: str) -> Iterator[tuple[str, str]]:
    """Yield ``(family, program)`` for every interpreter program a reader can
    read: inline (`-c` / `-e`, the program operand as the one bash WORD it
    is, its quote removal by `_bash_word_text` -- DEF-832), on stdin (a
    heredoc body or here-string) and piped. Opener on ``scan``, program from
    ``command`` by offset, the two-string discipline."""
    if len(scan) != len(command):
        scan = command
    for interp, rx in _INLINE_PROGRAM_RES:
        for m in rx.finditer(scan):
            yield interp, _bash_word_text(command[m.start("word"):m.end("word")])
    for interp, body in _stdin_program_bodies(command, scan):
        if interp not in _STDIN_SHELL_HEADS:
            yield _reader_family(interp) or interp, body
    for head, body in _piped_program_bodies(command):
        family = _reader_family(head)
        if family in _BODY_READER_FAMILIES:
            yield family, body


def _shell_out_program_bodies(command: str, scan: str) -> Iterator[str]:
    """Yield every program a Bash command hands to a shell through a reader
    head: the shell-out literals of its python, perl, node and ruby programs,
    what its awk, sed and git statements run, and a program on a POSIX
    shell's stdin by here-string or pipe. Each is bash text, scanned by the
    Bash consumers one level down. Opener on ``scan``, text from ``command``;
    both capped as the write extractor caps its input (`_cap_for_scan`, the
    same slice of each so the offsets still agree), because an uncapped
    reader pass on a multi-megabyte heredoc is seconds on the hot path."""
    if len(scan) != len(command):
        scan = command
    command, scan = _cap_for_scan(command), _cap_for_scan(scan)
    for family, body in _reader_program_bodies(command, scan):
        yield from _shell_outs_in(family, body)
    yield from _awk_shell_out_texts(command, scan)
    yield from _sed_shell_out_texts(command, scan)
    yield from _git_program_bodies(command, scan)
    for m in _SHELL_HERESTRING_RE.finditer(scan):
        j = m.end()
        while j < len(command) and command[j] in " \t":
            j += 1
        text, _ = _read_shell_word(command, j)
        if text.strip():
            yield text
    for head, body in _piped_program_bodies(command):
        if head in _POSIX_SHELL_HEAD_SET:
            yield body


def nested_shell_programs(command: str) -> list[str]:
    """Every program a Bash command hands to a shell through a reader,
    recursively to `_PS_STDIN_MAX_DEPTH`: the texts a Bash-tool speed bump
    reads beside the command itself (the operator's widening of the §C49
    carve-out, 2026-09-11 -- a delete a PROGRAM hands to a shell bumps as the
    bare spelling does). Computed once per command and remembered: six
    predicates and the discard snapshot ask for the same list on one tool
    call, and a hook process serves one call."""
    return list(_nested_shell_programs_cached(command))


@functools.lru_cache(maxsize=8)
def _nested_shell_programs_cached(command: str) -> tuple[str, ...]:
    return tuple(_nested_shell_programs(command, 0))


def _nested_shell_programs(command: str, _depth: int) -> list[str]:
    """Splice first, then mask, so the two strings the readers hold line up
    by offset; the reader caps its own input. Read over every reading the
    walls judge (`_wall_readings`, DEF-848's lane): a value the shell expands
    into a program before the interpreter starts (`os.system('$v')` inside a
    double-quoted program) is in the inlined reading only, and every
    speed-bump consumer of this list -- the nudge, the discard arms, the
    snapshot -- reads it from here. The hard tier reads the same readings
    in `write_guard._bash_dangerous_reason_here`."""
    if _depth >= _PS_STDIN_MAX_DEPTH:
        return []
    out: list[str] = []
    for reading in _wall_readings(command):
        spliced = splice_line_continuations(reading)
        pair = mask_inert_syntax(spliced)
        for program in _shell_out_program_bodies(spliced, pair):
            out.append(program)
            out.extend(_nested_shell_programs(program, _depth + 1))
    return list(dict.fromkeys(out))


# ── The directory a statement runs in (DEF-509) ─────────────────────────────
#
# A relative write was judged against the checkout root, which is wrong as
# soon as the command has changed directory: `cd tools/cc && echo x >
# hooks/f.py` ALLOWED (the write lands in the protected tree) and `cd /tmp &&
# echo x > tools/cc/hooks/f.py` DENIED (it does not), both driven 2026-09-13.
# The chain below follows `cd`, `pushd` and `popd` across the statements of
# the masked, spliced command -- masked, so a separator inside a quoted word
# or a heredoc body never opens a statement -- and a `(` pushes the directory
# for its `)` to pop, because a subshell's `cd` does not outlive it (a `{ }`
# group's does, so braces are boundaries only). A target the walk cannot
# read (`cd -`, a variable, a substitution) makes the directory UNKNOWN, and
# an unknown directory resolves as the root did: the indirection class,
# declared here and pinned at that verdict. The hook payload's `cwd` -- the
# directory Claude is in, which follows a `cd` from an EARLIER call -- is the
# caller's starting point, not this walk's business. Each spelling is returned
# as the command spelled it (relative to that start, or absolute, or `~`),
# for the caller's one resolver to join and fold; nothing here touches disk.
#: Matched against one statement, right-stripped and shorn of its trailing
#: redirections: every optional piece after the verb begins with its own
#: whitespace run and a non-space character, so no two adjacent quantifiers
#: share an input (the ReDoS rule). `builtin cd` is spelled here because
#: `builtin` is not on `_CMD_POS`'s wrapper run (`command cd` is; the
#: asymmetry was driven by the failure-mode review).
_DIR_VERB_RE = re.compile(
    _CMD_POS + r"(?:builtin[ \t]+)?\b(cd|pushd|popd)" + _QUOTED_VERB_TAIL
    + r"(?:[ \t]+-[A-Za-z@]{1,8}|[ \t]+--){0,4}"
    + r"(?:[ \t]+(?:(['\"])([^'\"\n]{0,512})\2|(-|[^\s'\"<>-][^\s'\"<>]{0,511})))?$"
)
#: The statement boundaries the chain walks -- a SYNTAX TOKEN, not an
#: invocation decider (declared in the class-close census). A single `&` and
#: a single `|` stay apart from `&&` / `||`: they mean different things to a
#: `cd` (see `_directory_chain`). A brace is a boundary only as the group
#: word bash reads it as -- `{` before a blank, `}` after a blank or a
#: terminator; inside a word it is brace expansion or `${...}` and part of
#: the word. Until 2026-09-18 every brace was one, so a delete of a brace
#: list under the checkout (`./{a,b}`) was sliced to `./` and walled as the
#: whole checkout, and `${HOME}` reached the wall only through the net.
_CHAIN_BOUNDARY_RE = re.compile(r"&&|\|\||[;|&\n()`]|\{(?=[ \t\n]|$)|(?<=[ \t\n;&|])\}")
# The PowerShell twin (`_PS_DIR_VERB_RE`, `_PS_CHAIN_BOUNDARY_RE`,
# `_PS_DIR_VERBS`) is defined beside `_PS_CMD_POS`, the anchor it composes,
# further down; `powershell_directory_chain` below reads it at call time.
#: More candidate directories than this and the walk gives up on the
#: statement (``None``: the root, as before) rather than judge a write in a
#: dozen places.
_MAX_DIRECTORY_CANDIDATES = 8
#: The directories a judge site reads where the walk placed nothing -- it
#: faulted, its text is not the one the reader scanned, or no statement holds
#: the offset (blocker condition 5): the start AND the unknown directory, the
#: same superset an unreadable `cd` gets, never the start alone.
_UNPLACED_DIRS: "tuple[str | None, ...]" = (".", None)
#: True while write_guard judges a program one shell hands another -- a
#: `pwsh -Command` program from Bash, a `bash -c` one from PowerShell, a
#: shell-out from python or awk (`another_shells_program`). The receiving
#: process places it: its start switch, a directory change in its own
#: language the walk never reads. So every statement's bases ADD the unknown
#: directory, as a delete inside a string does (blocker condition 2, its
#: cross-shell arm). Read at the ONE home every relief site shares,
#: `_statement_bases`, so a future judge honours it with nothing threaded
#: through it; the plain-command gate beside it (`_relief_applies`) is a
#: REQUIRED keyword instead, which no site can leave out either.
_ANOTHER_SHELLS_PROGRAM: "contextvars.ContextVar[bool]" = contextvars.ContextVar(
    "_ANOTHER_SHELLS_PROGRAM", default=False)


@contextlib.contextmanager
def another_shells_program() -> Iterator[None]:
    """Judge the enclosed program as one another shell was handed
    (`_ANOTHER_SHELLS_PROGRAM`); the flag is reset on the way out."""
    token = _ANOTHER_SHELLS_PROGRAM.set(True)
    try:
        yield
    finally:
        _ANOTHER_SHELLS_PROGRAM.reset(token)


#: At most this many PATTERNED removals, and this many made directories, does
#: the directory walk hold: past it every later directory change is unknown
#: (the removals) or unrecorded (the makes) -- the wall's direction both
#: times -- where holding them all made a flood of removals and directory
#: changes quadratic (the lane's review, measured past the hook's budget).
_WALK_SET_CAP = 64
#: A removal operand that names more than one path: the walk's ``gone`` set
#: (blocker condition 4) matches it as a pattern, not a spelling.
_GLOB_CHARS_RE = re.compile(r"[*?\[]")
#: A `mkdir` statement and its operands: a directory an EARLIER statement of
#: the same command makes is credited as there when a later `cd` enters it,
#: because the disk cannot know it yet when the hook runs and the
#: make-then-enter idiom (`mkdir -p sandbox && cd sandbox && ...`) is
#: ordinary scratch work (failure-mode re-check, driven). Not a write arm:
#: the roster test declares it so.
_MKDIR_RE = re.compile(
    _CMD_POS + r"(?:builtin[ \t]+)?\bmkdir" + _QUOTED_VERB_TAIL
    + r"(?:[ \t]+(?:-[A-Za-z]{1,8}|--[a-z-]{1,32}(?:=[^\s'\"]{0,256})?)){0,8}"
    + r"((?:[ \t]+(?:'[^'\n]{0,512}'|\"[^\"\n]{0,512}\"|[^\s'\"<>-][^\s'\"<>]{0,511})){1,32})"
)
#: The keyword conditionals: a `cd` between `if` / `case` / `while` / `until`
#: / `for` and its `fi` / `esac` / `done` may not run (`if false; then cd
#: /tmp; fi` -- driven: the shell wrote in the old directory), so it is
#: conditional exactly as a `cd` after `||` is. Statement-leading words on
#: the masked text; nesting counted.
_CONDITIONAL_OPENERS = ("if", "case", "while", "until", "for")
_CONDITIONAL_CLOSERS = ("fi", "esac", "done")
#: The PowerShell twin, turned around: the operators that run a script block
#: HERE, now -- the call operator and dot-sourcing, as the text before the
#: block's `{` ends. A location change inside any other block is one the
#: command may not make in this runspace: a branch or a loop that may run no
#: times, a stored block, a function or filter body (run only when called), a
#: job's block (another process), a pipeline's (its input may be empty). The
#: first cut listed the conditional keywords instead, and a stored, a job's
#: and a `%` block each moved the walk (the lane's review, its major).
_PS_IN_PLACE_BLOCK_INVOKERS = ("&", ".")
#: The statement heads after which the walk cannot know the directory
#: (blocker condition 3): Bash runs `eval`'s and `source`'s text in THIS
#: shell, and PowerShell keeps a script's `Set-Location` in the caller
#: (driven in pwsh 7.6.5: `& ./move.ps1` left the caller in the directory
#: the script entered), as it does `iex`'s and a dot-sourced file's. A
#: function the command itself defined is the fourth head (Bash; a
#: PowerShell script block's `Set-Location` already moves the walk).
_BASH_UNSEEN_DIRECTORY_HEADS = frozenset({"eval", "source", "."})
_PS_UNSEEN_DIRECTORY_HEADS = frozenset({"iex", "invoke-expression", "."})
#: Words before a statement's head that leave it in this shell.
_BASH_HEAD_PREFIX_WORDS = frozenset({
    "builtin", "command", "if", "then", "else", "elif", "do", "while", "until", "!", "time",
})


def _changes_directory_unseen(stmt: str, *, bash: bool, functions: "set[str]") -> bool:
    """Does ``stmt`` (one statement's raw text) run code in THIS shell that
    may change directory where the walk cannot read it -- `eval`, `source` /
    `.`, a call to a function the command defined, and on PowerShell `iex`,
    a dot-source or a `.ps1` script? Its first word past the keywords, the
    wrappers and the leading assignments, read as words (no pattern: the
    head is the statement's own first word, not a search). On Bash the words
    are the ones bash forms (`_shell_word_spans`, DEF-843): a leading
    assignment whose quoted value holds a blank is ONE word, where a
    whitespace split read the value's second word as the head and missed an
    `eval` or `source` behind it (DEF-848's lane, the failure-mode review);
    an unterminated quote keeps the whitespace split."""
    spans = _shell_word_spans(stmt) if bash else None
    words = spans[:9] if spans is not None else stmt.split(None, 8)
    i = 0
    while i < len(words) and (
        (words[i] == "&" if not bash else words[i] in _BASH_HEAD_PREFIX_WORDS)
        or (bash and "=" in words[i] and words[i].split("=", 1)[0].isidentifier())
    ):
        i += 1
    if i >= len(words):
        return False
    head = words[i].strip("'\"")
    if bash:
        return head in _BASH_UNSEEN_DIRECTORY_HEADS or head in functions
    low = head.lower()
    return low in _PS_UNSEEN_DIRECTORY_HEADS or low.endswith(".ps1")


def _strip_trailing_redirects(seg: str) -> str:
    """``seg`` without its trailing redirections -- `2>/dev/null`, `>&2`, and
    the spaced form `2> /dev/null` -- read with the operand tokenizer's own
    redirect classifiers (`_REDIRECT_TOKEN_RE` / `_BARE_REDIRECT_OPERATOR_RE`,
    DEF-414b) token by token from the end: a `$`-anchored search retries from
    every start position and is quadratic on a long statement (the ReDoS
    gate reddened the first cut). Without this, `cd 'tools/cc' 2>/dev/null
    && echo x > hooks/f.py` read the `cd` as an ordinary command and the
    directory never moved (driven)."""
    for _ in range(4):
        parts = seg.rsplit(None, 1)
        if len(parts) < 2:
            break
        head, tok = parts
        if _REDIRECT_TOKEN_RE.match(tok):
            seg = head
            continue
        # the spaced form: `2> /dev/null` is two tokens, the operator first
        earlier = head.rsplit(None, 1)
        if len(earlier) == 2 and _BARE_REDIRECT_OPERATOR_RE.match(earlier[1]):
            seg = earlier[0]
            continue
        break
    return seg.rstrip()


def _step_one(
    target: str | None, cwd: str | None, exists: "Callable[[str], bool] | None",
) -> str | None:
    """The directory after one `cd <target>` from ``cwd``. A readable target
    the ``exists`` oracle refuses leaves the directory where it was, as a
    failed `cd` does (driven: `cd /nonexistent; echo x > <hook>` writes in
    the old directory); without an oracle every readable target is assumed
    to succeed."""
    if not target:
        new: str | None = "~"                   # `cd` alone goes home
    elif target == "-" or "$" in target or "`" in target:
        return None                             # the indirection class
    else:
        target = target.replace("\\", "/")
        if target.startswith(("~", "/")) or _DRIVE_OR_UNC_ABSOLUTE_RE.match(target):
            new = target
        elif cwd is None:
            return None
        else:
            new = posixpath.normpath(posixpath.join(cwd, target))
    if new is not None and exists is not None and not exists(new):
        return cwd                              # the shell stays put
    return new


def _self_and_ancestors(spelled: str) -> Iterator[str]:
    """``a``, ``a/b``, ``a/b/c`` for ``a/b/c`` (an absolute spelling keeps its
    leading slash): every directory a `cd` to ``spelled`` passes through, so
    a removal pattern that took an ancestor is seen as taking it too."""
    parts = spelled.split("/")
    for i in range(1, len(parts) + 1):
        head = "/".join(parts[:i])
        if head:
            yield head


def _merge_candidates(*groups: "list[str | None]") -> list[str | None]:
    out: list[str | None] = []
    for group in groups:
        for d in group:
            if d not in out:
                out.append(d)
    return out if len(out) <= _MAX_DIRECTORY_CANDIDATES else [None]


def _step_directories(
    verb: str, target: str | None, cwds: list[str | None],
    stack: list[list[str | None]], exists: "Callable[[str], bool] | None",
) -> list[str | None]:
    """The candidate directories after one `cd` / `pushd` / `popd`; mutates
    ``stack`` (the `pushd` stack, one entry per push, each a candidate list)."""
    if verb == "popd":
        return stack.pop() if stack else cwds
    if verb == "pushd":
        if not target:
            if not stack:
                return [None]
            top, stack[-1] = stack[-1], list(cwds)   # `pushd` alone swaps the top two
            return top
        stack.append(list(cwds))
    return _merge_candidates([_step_one(target, cwd, exists) for cwd in cwds])


def _is_function_header(text: str, at: int) -> bool:
    """Is the `{` at ``at`` the body of a function DEFINITION -- `f() {`,
    `function f {` -- whose statements run only when the function is later
    called (driven: `f(){ cd /tmp; }; echo x > <hook>` writes in the old
    directory)? String work over a bounded tail: a `$`-anchored search
    pattern would be quadratic under the ReDoS gate."""
    return _function_header_name(text, at) is not None


def _function_header_name(text: str, at: int) -> str | None:
    """The name `_is_function_header` reads before the `{` at ``at``, or
    ``None`` when that `{` opens no function definition. The walk keeps the
    names so a later call to one is seen (blocker condition 3)."""
    tail = text[max(0, at - 256):at].rstrip()
    if tail.endswith(")"):
        inner = tail[:-1].rstrip()
        if not inner.endswith("("):
            return None
        name = re.split(r"[;\n&|(){}`]", inner[:-1])[-1].strip()
        if not name or re.fullmatch(r"(?:function[ \t]+)?[\w.-]+", name) is None:
            return None
    else:
        name = re.split(r"[;\n&|(){}`]", tail)[-1].strip()
        if re.fullmatch(r"function[ \t]+[\w.-]+", name) is None:
            return None
    return name.split()[-1]


def _directory_chain(
    text: str, boundary_re: "re.Pattern[str]", verb_re: "re.Pattern[str]",
    *, bash: bool, verbs: dict[str, str] | None,
    exists: "Callable[[str], bool] | None", raw: str | None = None,
) -> list[tuple[int, int, tuple[str | None, ...]]]:
    """Walk the statements of ``text`` and record, for each one that is not
    itself a directory verb, the CANDIDATE directories it runs in.

    ``raw``, when given and the same length as ``text``, is where a directory
    operand's CHARACTERS come from: ``text`` is the masked scan, and a quoted
    `cd` operand read off it carries the masker's blanks where its parens
    were, so the base joined onto `hooks/x.py` existed nowhere (DEF-794).

    Bash semantics (``bash=True``; a PowerShell location change is process-
    wide, so the pipeline, background, subshell and function-frame rules do
    not apply -- the CONDITIONAL rules do, in its own spelling: the pwsh 7
    chain operators, and any block not invoked in place,
    `_PS_IN_PLACE_BLOCK_INVOKERS`): a `cd` in a pipeline stage or backgrounded
    with `&` moved a child shell, not this one; a `cd` after `&&` or `||` is
    conditional, so the statements after it are judged in both the old and
    the new directory unless they are `&&`-joined to a `&&`-preceded `cd`
    (then the cd's success gated them); a `(` pushes the directories for its
    `)` to pop, and so does a backtick substitution; a `{` that opens a
    function definition does the same, a brace GROUP's `cd` outlives its
    `}` -- unless the group is backgrounded or a pipeline stage, a child
    shell's (both directories stand). The five shapes named here all
    wrote into the protected tree past the first cut (failure-mode review,
    driven against /bin/bash).

    Both shells: a directory verb inside a string another process re-parses
    (a `bash -c` program; on PowerShell a program handed to pwsh, `iex` or
    Start-Process, which the masker keeps live) moves that process, so it
    merges like a conditional `cd` (blocker condition 2). PowerShell's
    quoting is read by `_ps_quote_cursor`, the masker's own walk.

    Both shells: the disk answers "is it there?" for the moment the hook
    runs, before this command's own earlier statements removed or moved
    anything. ``gone`` is the twin of ``made`` -- what an earlier statement
    removes or moves, read by the one removal reader each shell has and
    spelled as ``made`` is -- and a `cd` into it, or under it, ADDS the
    unknown directory (``None``) to its candidates: a superset, never a
    replacement, so the caller's start reading (the failed `cd` stays put)
    and the moved reading both stand. The removals are read lazily, when a
    directory verb needs them, so a command with no `cd` pays nothing. A
    removal the walk cannot spell (a variable it cannot inline) makes every
    later `cd` unknown. Declared limit: ``gone`` matches by spelling, as
    ``made`` does -- a removal spelled absolute and a `cd` spelled relative
    to the same directory are not joined (the walk knows no start).

    Code run in THIS shell that the walk never reads -- `eval`, `source`,
    a call to a function the command defined, a PowerShell script -- ADDS
    the unknown directory to every statement after it
    (`_changes_directory_unseen`). Declared limit: a function defined by an
    EARLIER call (the shell snapshot's) is not known to the walk."""
    statements: list[tuple[int, int, tuple[str | None, ...]]] = []
    cwds: list[str | None] = ["."]
    stack: list[list[str | None]] = []
    frames: list[tuple[str, list[str | None], list[list[str | None]]]] = []
    made: set[str] = set()                      # directories this command makes
    gone: set[str] = set()                      # ... and removes or moves (blocker condition 4)
    gone_patterns: list[str] = []               # ... by a pattern, capped (`_WALK_SET_CAP`)
    gone_unread = False                         # a removal operand the walk cannot spell
    functions: set[str] = set()                 # names this command defines (condition 3)
    pending: list[tuple[str, list[str | None]]] = []   # statements whose removals are unread
    depth = 0                                   # keyword conditionals open
    ps_blocks: list[bool] = []                  # PowerShell braces open: conditional?
    pos = 0
    prev_tok = ""
    # where a statement's own characters come from: the raw twin when it
    # indexes the scan, else the scan (whose slice at the span IS ``seg``)
    stmt_src: str = raw if raw is not None and len(raw) == len(text) else text
    # the uncached Bash reader: a walk's per-statement slices must not evict
    # the whole-command memo the zone and secret checks share
    removals = _iter_removed_or_relocated_operands if bash else iter_ps_removed_or_relocated_operands
    quote_at = _quote_cursor(text)              # asked in increasing order (condition 2)
    ps_string_at = _ps_quote_cursor(stmt_src)   # its PowerShell twin, over the raw twin
    heredoc_at = _heredoc_cursor(text)          # a body the masker left live: another shell's

    def known(spelled: str) -> bool:
        return spelled in made or exists is None or exists(spelled)

    def read_removals() -> None:
        nonlocal gone_unread
        for seg_raw, seg_cwds in pending:
            for effect, operand in removals(seg_raw):
                if effect not in ("delete", "move") or not operand.strip("'\""):
                    continue
                for cwd in seg_cwds:
                    spelled = _step_one(operand.strip("'\""), cwd, None)
                    if spelled is None:
                        gone_unread = True
                        continue
                    if _GLOB_CHARS_RE.search(spelled) is None:
                        gone.add(spelled)
                    elif len(gone_patterns) < _WALK_SET_CAP:
                        gone_patterns.append(spelled)
                    else:
                        gone_unread = True      # past the cap: every later cd unknown
                    if made:
                        made.difference_update(
                            [d for d in made if d == spelled or d.startswith(spelled + "/")])
        pending.clear()

    def is_gone(spelled: str) -> bool:
        # the exact spellings by the ancestors' own lookup (linear in depth);
        # only the capped patterns are matched one by one (the lane's review:
        # a flood of removals and directory changes was quadratic here)
        if gone_unread:
            return True
        ancestors = list(_self_and_ancestors(spelled))
        return any(p in gone for p in ancestors) or any(
            fnmatch.fnmatchcase(p, g) for g in gone_patterns for p in ancestors)

    oracle = known if exists is not None else None
    bounds = [*boundary_re.finditer(text), None]
    for idx, b in enumerate(bounds):
        end = len(text) if b is None else b.start()
        tok = "" if b is None else b.group(0)
        seg = _strip_trailing_redirects(text[pos:end].rstrip())
        if seg.strip():
            head = seg.split(None, 1)[0].lower() if bash else ""
            if head in _CONDITIONAL_OPENERS:
                depth += 1
            m = verb_re.search(seg)
            if m:
                verb = m.group(1).lower()
                verb = verbs[verb] if verbs else verb
                group = 3 if m.group(3) is not None else 4
                target = m.group(group)
                if raw is not None and len(raw) == len(text):
                    target = raw_operand(raw[pos:pos + len(seg)], m, group, word=bash)
                if bash and (tok in ("|", "&") or prev_tok == "|"):
                    pass                        # a child shell moved, not this one
                else:
                    if pending:
                        read_removals()
                    stepped = _step_directories(verb, target, cwds, stack, oracle)
                    if (gone or gone_patterns or gone_unread) and any(
                            d is not None and is_gone(d) for d in stepped):
                        stepped = _merge_candidates(stepped, [None])
                    gated = prev_tok == "&&" and tok == "&&"
                    # a `cd` inside a string another shell re-parses (the
                    # masker leaves a `bash -c` program raw) moves that shell
                    # only: this one keeps its directories BESIDE the moved
                    # ones, as for a conditional `cd` -- the statements after
                    # it inside the string run in the moved one, those after
                    # the string where this shell stood (blocker condition 2).
                    # A quoted VERB -- its quote closes right after it -- is
                    # this shell's own. On PowerShell the program is one
                    # handed to pwsh / iex / Start-Process (the masker keeps
                    # it live), read by PowerShell's quoting over the raw twin.
                    # PowerShell's other conditionals: the pwsh 7 chain
                    # operators, as Bash's, and any block not invoked in place
                    # (`_PS_IN_PLACE_BLOCK_INVOKERS`). A heredoc body the
                    # masker left live is a string another shell re-parses.
                    verb_at = pos + m.start(1)
                    if bash:
                        quote = quote_at(verb_at)
                        in_string = (quote is not None and (
                            text[pos + m.end(1):pos + m.end(1) + 1] != _QUOTE_CLOSER[quote])
                        ) or heredoc_at(verb_at)
                    else:
                        span = ps_string_at(verb_at)
                        in_string = span is not None and span[1] != pos + m.end(1)
                    conditional = in_string or depth > 0 or any(ps_blocks) or (
                        prev_tok in ("&&", "||") and not gated)
                    if conditional:
                        cwds = _merge_candidates(cwds, stepped)
                    else:
                        cwds = stepped
            else:
                statements.append((pos, end, tuple(cwds)))
                mk = _MKDIR_RE.search(seg) if bash else None
                if mk:
                    # quote-aware, from the raw twin: `mkdir -p "<root with a
                    # paren>/tools/cc/hooks"` split into three fragments off the
                    # masked text and `made` never held the directory (review;
                    # the same two mechanisms as DEF-794, one call away)
                    made_seg = (raw[pos:pos + len(seg)]
                                if raw is not None and len(raw) == len(text) else seg)
                    if pending:
                        read_removals()         # an earlier removal, then this make
                    for operand in _OPERAND_TOKEN_RE.findall(made_seg[mk.start(1):mk.end(1)]):
                        for cwd in cwds:
                            spelled = _step_one(operand.strip("'\""), cwd, None)
                            if spelled is not None and len(made) < _WALK_SET_CAP:
                                # past the cap a make goes unrecorded: a later
                                # cd into it then reads as failed -- more
                                # walls, never fewer
                                made.add(spelled)
                                # made again undoes the removal of that exact
                                # spelling only: a make under a removed ancestor
                                # fails without `-p`, and the walk does not read
                                # the flag, so the ancestor stays gone (walls)
                                gone.discard(spelled)
                stmt_raw = stmt_src[pos:pos + len(seg)]
                pending.append((stmt_raw, list(cwds)))
                child = bash and (tok in ("|", "&") or prev_tok == "|")
                if not child and _changes_directory_unseen(stmt_raw, bash=bash, functions=functions):
                    cwds = _merge_candidates(cwds, [None])      # blocker condition 3
            if head in _CONDITIONAL_CLOSERS and depth:
                depth -= 1
        if b is None:
            break
        if bash:
            if tok == "(":
                frames.append(("sub", list(cwds), [list(s) for s in stack]))
            elif tok == "`":
                # a backtick substitution is a subshell, as `$(` is: the
                # opening one pushes a frame, the closing one restores it
                # (the lane's review, its major -- backticks do not nest)
                if any(kind == "tick" for kind, _c, _s in frames):
                    while frames:
                        kind, saved_cwds, saved_stack = frames.pop()
                        if kind == "tick":
                            cwds, stack = saved_cwds, saved_stack
                            break
                else:
                    frames.append(("tick", list(cwds), [list(s) for s in stack]))
            elif tok == "{":
                fn_name = _function_header_name(text, b.start())
                if fn_name is not None:
                    functions.add(fn_name)
                # a group opened as a later pipeline stage runs in a child
                kind = "fn" if fn_name is not None else ("grp|" if prev_tok == "|" else "grp")
                frames.append((kind, list(cwds), [list(s) for s in stack]))
            elif tok == ")":
                while frames:
                    kind, saved_cwds, saved_stack = frames.pop()
                    if kind == "sub":
                        cwds, stack = saved_cwds, saved_stack
                        break
            elif tok == "}" and frames:
                kind, saved_cwds, saved_stack = frames.pop()
                nxt = bounds[idx + 1] if idx + 1 < len(bounds) else None
                if kind == "fn":
                    cwds, stack = saved_cwds, saved_stack
                elif kind == "grp|" or (
                        kind == "grp" and nxt is not None and nxt.group(0) in ("|", "&")):
                    # a group put in the background or into a pipeline ran in
                    # a child shell -- or, as a pipeline's last stage under
                    # `lastpipe` or zsh, maybe in this one: both directories
                    cwds = _merge_candidates(saved_cwds, cwds)
        elif tok == "{":
            ps_blocks.append(not seg.rstrip().endswith(_PS_IN_PLACE_BLOCK_INVOKERS))
        elif tok == "}" and ps_blocks:
            ps_blocks.pop()
        prev_tok = tok
        pos = b.end()
    return statements


def bash_directory_chain(
    command: str, exists: "Callable[[str], bool] | None" = None,
) -> tuple[str, list[tuple[int, int, tuple[str | None, ...]]]]:
    """``(text, statements)`` for a Bash command: the masked, spliced text the
    offsets index and, for every statement that is not itself a directory
    verb, ``(start, end, directories)`` -- the candidate directories in
    effect while it runs (``"."`` for the command's start, else as the
    command spelled it; ``None`` for one that cannot be read). ``exists``
    answers "is this spelled directory there?" for the caller that can join
    it to a real start; the walk itself touches no disk. See the block
    comment above."""
    raw = splice_line_continuations(_cap_for_scan(command))
    text = mask_inert_syntax(raw)
    return text, _directory_chain(
        text, _CHAIN_BOUNDARY_RE, _DIR_VERB_RE, bash=True, verbs=None, exists=exists,
        raw=raw,
    )


def powershell_directory_chain(
    command: str, exists: "Callable[[str], bool] | None" = None,
) -> tuple[str, list[tuple[int, int, tuple[str | None, ...]]]]:
    """The PowerShell twin of `bash_directory_chain`, over the PowerShell scan
    text; `Set-Location` and its aliases, `Push-Location` / `Pop-Location`.
    A location change is process-wide, so the pipeline, background and
    function rules of the Bash walk do not apply. The .NET file API resolves
    against the PROCESS directory, which `Set-Location` never moves -- its
    candidates are the caller's to exempt (`powershell_dotnet_paths`)."""
    raw, text = powershell_scan_pair(command)
    return text, _directory_chain(
        text, _PS_CHAIN_BOUNDARY_RE, _PS_DIR_VERB_RE, bash=False, verbs=_PS_DIR_VERBS,
        exists=exists, raw=raw,
    )


def statement_directories(
    text: str, statements: list[tuple[int, int, tuple[str | None, ...]]], raw: str,
) -> list[str | None]:
    """The directories a captured spelling may resolve against: those of the
    statements whose text carries it, else every directory the chain visited
    (a spelling the walk cannot place -- an expanded variable, an interpreter
    body -- is judged in each of them, and denied if any hits). ``"."`` when
    nothing changed directory. Deduplicated, order kept."""
    needle = raw.strip().strip("'\"")
    hits = [ds for s, e, ds in statements if needle and needle in text[s:e]]
    out: list[str | None] = []
    for ds in hits or [ds for _s, _e, ds in statements] or [(".",)]:
        for d in ds:
            if d not in out:
                out.append(d)
    return out


# ── The directories a command's spellings resolve against (DEF-509, DEF-790) ──
# ONE home for write_guard (the verdict), post_write_check (the registry
# payloads) and the speed bump (its defer to the hard tier): the start -- the
# payload's `cwd`, else the root -- moved by the command's own `cd` / `pushd`
# chain, as a `raw -> [Path]` callable keyed by the spelling. Lived in
# write_guard until 2026-09-13; the rm hard tier and `_speedbump._pred_rmrf`
# read it too, and `_speedbump` cannot import write_guard (write_guard
# imports it).
Bases = Callable[[str], "list[Path]"]


def command_bases(
    chain: "tuple[str, list[tuple[int, int, tuple[str | None, ...]]]] | None",
    start: Path, fixed: frozenset = frozenset(),
) -> Bases:
    """``raw -> [Path]``: the directories a captured spelling resolves against
    (DEF-509) -- the start (the payload's ``cwd``, else the root), moved by
    the command's own ``cd`` / ``pushd`` chain. Without a chain, the start
    alone: the rule every caller had until 2026-09-13. A spelling in
    ``fixed`` resolves against the start whatever the chain says: the .NET
    file API on PowerShell reads the PROCESS directory, which `Set-Location`
    never moves (driven in pwsh 7.6.5 by the failure-mode review)."""
    if chain is None:
        return lambda raw: [start]
    text, statements = chain

    def bases(raw: str) -> list[Path]:
        if raw in fixed:
            return [start]
        out: list[Path] = []
        for spelled in statement_directories(text, statements, raw):
            at = _hook_utils.join_directory(start, spelled)
            if at not in out:
                out.append(at)
        return out
    return bases


def bash_bases(command: str, root: Path, cwd: Path | None) -> Bases:
    """`command_bases` over the Bash chain, from the payload ``cwd`` (else
    the root); a fault in the walk degrades to the start, never to a deny."""
    start = cwd or root
    try:
        chain = bash_directory_chain(command, _hook_utils.directory_exists(start))
    except Exception:  # noqa: BLE001 -- the walk is advisory to the resolver
        chain = None
    return command_bases(chain, start)


def powershell_bases(command: str, root: Path, cwd: Path | None) -> Bases:
    """The PowerShell twin of `bash_bases`, with the .NET file API's
    candidates fixed to the start (`powershell_dotnet_paths`)."""
    start = cwd or root
    try:
        chain = powershell_directory_chain(command, _hook_utils.directory_exists(start))
        fixed = frozenset(powershell_dotnet_paths(command))
    except Exception:  # noqa: BLE001 -- as above
        chain, fixed = None, frozenset()
    return command_bases(chain, start, fixed)


def _extractor_pair(command: str) -> tuple[str, str]:
    """``(raw, scan)``: the reading every write-verb reader of a Bash command
    takes -- `_candidate_paths_from_bash`, the symlink reader
    (`write_guard.check_bash_for_protected_symlinks`) and the hardlink reader
    (`iter_hardlink_operands`), one owner since DEF-848's lane, where the two
    link readers were found reading the raw command alone. ``raw`` is the
    capped command, continuations spliced, its literal bindings inlined;
    ``scan`` its masked twin with redirect ampersands neutralised, the same
    length: the readers MATCH on ``scan`` and read each operand from ``raw``
    at the match's offsets. Why each step is there, and in that order: the
    notes in `_candidate_paths_from_bash`."""
    raw = _expand_simple_var_assignments(splice_line_continuations(_cap_for_scan(command)))
    scan = neutralise_redirect_ampersands(mask_inert_syntax(raw))
    if len(scan) != len(raw):
        # Cannot happen (both transforms keep length), but every reader
        # slices ``raw`` at ``scan``'s offsets and a one-character drift reads
        # `ools/cc/hooks/write_guard.py` and ALLOWS (review, driven with a
        # shifted masker): scan the raw command instead -- the friction
        # direction, as `powershell_scan_pair`, the in-place tokenizer, the
        # directory chain and the .NET arms already do.
        scan = raw
    return raw, scan


def _candidate_paths_from_bash(command: str, _depth: int = 0) -> list[str]:
    """Extract candidate write-target paths from a Bash command.

    ``_depth`` is the cross-shell recursion level (DEF-637): a PowerShell
    program behind `powershell -Command` is handed to the PowerShell
    extractor one level down, and that extractor hands a `bash -c` program
    back here, until `_PS_STDIN_MAX_DEPTH` stops it.

    Runs `_expand_simple_var_assignments` first so that simple
    `VAR=value; ... > $VAR` patterns surface their literal targets.

    Cap the input at 32KB before the regex passes. 15+ compiled regexes
    (incl. DOTALL patterns) over a 1MB+ heredoc body add measurable latency
    to every Bash tool call. Scan head + tail (16KB each) rather than first
    32KB only, so trailing redirects past the front cap are still extracted.
    """
    # The reading is `_extractor_pair`'s (one owner since DEF-848's lane: the
    # symlink and hardlink readers take the same one). The notes below say why
    # each step is there and in that order.
    #
    # A backslash-newline is a CONTINUATION; a bare newline is a statement
    # boundary. Splice the former FIRST, on the text every reader below derives
    # from -- the masked `scan` and the raw `command` must stay the same length
    # for the by-offset interpreter arm -- so that `cp src \` + newline + `<hook>`
    # is one statement to every span regex, while `cp a b` + newline + `<hook>`
    # is two. Until 2026-09-06 (DEF-701) the spans were joined with `\s`, which
    # matched the newline: the continuation held only by accident, and a real
    # destination on line one was displaced by whatever line two said. The
    # splicer leaves a quoted-delimiter heredoc body unspliced and joins an
    # unquoted body's continuation as bash does (447-A step 3; pinned by the
    # heredoc rows of `TestBashOperandSpansStopAtNewline` and of the mask
    # tests' GENUINE and INERT lists).
    # ⚠ This order is the REVERSE of `iter_rm_invocations` and of the speed
    # bump's `_masked_command`, which mask first and splice the masked text:
    # they only SEARCH the result, so offsets need not survive there. Here two
    # strings are read by offset against each other, so both must derive from
    # the one spliced text. Neither order is the wrong one; each serves its
    # consumer, and this note is the reason they differ.
    command, scan = _extractor_pair(command)
    # ⚠ TWO INPUTS, DELIBERATELY. `scan` is the role-mapped string: every redirect
    # and write-verb extractor below reads it, so a `>` or a verb sitting inside a
    # quoted span, a comment or a heredoc body is no longer read as a real write.
    # `command` stays RAW for the interpreter PROGRAM BODIES (`-c` / `-e` and
    # stdin): their opener is matched on `scan` too, but the body is sliced out
    # of `command` by offset, because the body's own syntax characters are what
    # the inner write patterns read (DEF-698, DEF-704). Order matters: mask AFTER
    # the cap and the variable expansion, so offsets line up with what is scanned.
    paths: list[str] = []

    # ⚠ EVERY consumer below matches on `scan` and reads its OPERAND from
    # `command` at the match's offsets (`raw_operand` / `raw_span`, DEF-794):
    # the two strings are the same length by construction, and the operand's
    # real characters are only in the raw one.

    # Heredoc first so the `<<` terminator isn't captured by the plain redirect.
    for m in _HEREDOC_RE.finditer(scan):
        paths.append(raw_operand(command, m, word=True))

    # Blank the heredoc's redirect so the plain-redirect pass does not match it
    # twice -- LENGTH-PRESERVING, because that pass reads `command` by offset
    # (the old `"cat <<"` substitution shortened the text; measured 25 -> 15).
    stripped = _HEREDOC_RE.sub(lambda hm: " " * (hm.end() - hm.start()), scan)

    for m in _REDIRECT_RE.finditer(stripped):
        paths.append(raw_operand(command, m, word=True))

    # Tee: capture every positional arg (multi-arg tee writes to all of them).
    for m in _TEE_RE.finditer(scan):
        for tok in _tee_targets(raw_span(command, m)):
            paths.append(tok)

    for m in _SED_INPLACE_RE.finditer(scan):
        paths.append(raw_operand(command, m, word=True))

    # UNION with the regex above, deliberately: the regex keeps every capture it
    # already had (so no currently-denied spelling regresses) and the tokenizer
    # adds the option forms the grammar model never reached, on both verbs.
    paths.extend(iter_inplace_edit_targets(scan, raw=command))

    for m in _CP_MV_RE.finditer(scan):
        span = raw_span(command, m, 2)   # group 1 is the verb (§C52)
        positionals = _positional_operands(span)
        # `-t DIR` (any spelling `_target_directory_value` reads): every
        # positional is a SOURCE and DIR is the one destination, so the last
        # positional is a file being READ (`cp -t backups/ <hook>`, a false
        # positive Rule 6 ranks above a bypass) and each source lands under DIR
        # (`cp -t .claude/ settings.json` names the protected file the bare
        # directory never did). Read from the token view: a raw regex beside it
        # disagreed on a quoted flag and on glued `-tDIR` (a later review pass).
        target_dirs, ambiguous = _target_directory_readings(span, _CP_MV_VALUELESS_SHORT)
        for target_dir in target_dirs:
            paths.append(target_dir)
            # the space-bound DIR is itself in the positional view; not a source
            sources = [p for p in positionals if p != target_dir]
            paths.extend(_landed_under(target_dir, sources))
        if target_dirs and not ambiguous:
            continue                      # one reading; an ambiguous span ALSO takes the pick below
        if len(positionals) < 2:
            continue
        dst = positionals[-1]
        paths.append(dst)
        # Directory destination: EVERY source lands at `<dst>/<basename(src)>`.
        if dst.endswith("/"):
            paths.extend(_landed_under(dst, positionals[:-1]))

    # Additional write verbs not covered by _CP_MV_RE / _TEE_RE.
    for m in _DD_OF_RE.finditer(scan):
        paths.append(raw_operand(command, m, word=True))

    for m in _TAR_C_RE.finditer(scan):
        paths.append(raw_operand(command, m, word=True))

    # install / rsync / truncate -- last non-flag positional. `install -t DIR`
    # makes every positional a source landing under DIR, exactly as cp/mv above
    # (the same reader, `_target_directory_value`).
    for cmd_re in (_INSTALL_CMD_RE, _RSYNC_CMD_RE, _TRUNCATE_CMD_RE):
        for m in cmd_re.finditer(scan):
            span = raw_span(command, m)
            if cmd_re is _INSTALL_CMD_RE:
                target_dirs, ambiguous = _target_directory_readings(
                    span, _INSTALL_VALUELESS_SHORT,
                )
                for target_dir in target_dirs:
                    paths.append(target_dir)
                    sources = [p for p in _positional_operands(span) if p != target_dir]
                    paths.extend(_landed_under(target_dir, sources))
                if target_dirs and not ambiguous:
                    continue
            tail = _last_non_flag_token(span)
            if tail:
                paths.append(tail)

    # patch -- EVERY positional plus glued `--output=`/`--directory=` values:
    # the originalfile written is the FIRST and the patchfile read is the last,
    # so the last-token pick read `patch <hook> p.diff` as a write to `p.diff`
    # (see the `_PATCH_CMD_RE` comment and `_patch_targets`).
    for m in _PATCH_CMD_RE.finditer(scan):
        paths.extend(_patch_targets(raw_span(command, m)))

    # chmod / chown / chgrp / chflags / chattr / setfacl -- every positional
    # after the mode/owner/flags (every positional for setfacl). A permission
    # change on a hook silences it as surely as a write.
    for m in _CHMOD_CHOWN_RE.finditer(scan):
        paths.extend(_permission_targets(raw_span(command, m, 2), m.group(1)))

    for m in _GIT_CHECKOUT_DASHDASH_RE.finditer(scan):
        paths.append(raw_operand(command, m, word=True))

    for m in _GIT_CHECKOUT_BARE_RE.finditer(scan):
        paths.append(raw_operand(command, m, word=True))

    for m in _GIT_RESTORE_RE.finditer(scan):
        paths.append(raw_operand(command, m, word=True))

    # Inline interpreter source bodies (`-c` / `-e`), and the same interpreters
    # fed their program on stdin (heredoc / here-string). Both arms: opener on
    # `scan`, body from `command` by offset -- see `_inline_program_bodies`
    # and `_stdin_program_bodies`. Each interpreter has its own literal-string
    # write pattern; nothing here chases variables or template literals.
    for interp, body in _inline_program_bodies(command, scan):
        for rx in _STDIN_PROGRAM_WRITE_RES[interp]:
            for om in rx.finditer(body):
                paths.append(om.group(2))

    for interp, body in _stdin_program_bodies(command, scan):
        if interp in _STDIN_SHELL_HEADS:
            continue  # a PowerShell program: `_shell_program_bodies` below
        for rx in _STDIN_PROGRAM_WRITE_RES[interp]:
            for om in rx.finditer(body):
                paths.append(om.group(2))

    # The same interpreters fed their program by PIPE (DEF-745): the stage
    # before the pipe, read by the same inner patterns.
    for head, body in _piped_program_bodies(command):
        family = _reader_family(head)
        if family is not None and family in _STDIN_PROGRAM_WRITE_RES:
            for rx in _STDIN_PROGRAM_WRITE_RES[family]:
                for om in rx.finditer(body):
                    paths.append(om.group(2))

    # An awk or sed program's OWN file writes, made with no shell (447-A
    # step 3, the failure-mode review): a reader head's program is data to
    # the raw scan, so its redirect into a hook needs a reader of its own.
    paths.extend(_awk_sed_write_paths(command, scan))

    # A PowerShell program behind `powershell` / `pwsh` (DEF-637): judged by
    # the grammar that will run it, one level down. The other shell's
    # extractor masks and caps the program itself.
    if _depth < _PS_STDIN_MAX_DEPTH:
        for program in _shell_program_bodies(command, scan):
            paths.extend(_candidate_paths_from_powershell(program, _depth + 1))
        # What a program under a reader head hands to a SHELL (447-A step 3):
        # scanned by this extractor one level down, under the same bound.
        for program in _shell_out_program_bodies(command, scan):
            paths.extend(_candidate_paths_from_bash(program, _depth + 1))
        # A POSIX shell's `-c` word (DEF-832): the raw scan reads a
        # single-span program already (the head is off the masker's roster),
        # but a program spelled as adjacent segments reaches the shell as
        # their concatenation, which only the word reader sees -- scanned
        # here as the text the inner shell receives, the secret leg's pairing.
        # A single-span program is therefore read twice (raw, and here);
        # the duplicate costs work inside the depth bound, never a decision.
        for program in _posix_shell_c_bodies(command, scan):
            paths.extend(_candidate_paths_from_bash(program, _depth + 1))

    return paths


# ── The operand a verb REMOVES or RELOCATES (§C52, DEF-795 + DEF-796) ────────
#
# The write extractor above classifies the operand a verb WRITES. A protected
# zone refuses ANY mutation from any entry point unless maintenance mode is on
# (the operator's framing, 2026-09-14), so the operand a verb removes or
# relocates is classified beside it -- by the same discipline: match on the
# scan, read the operand from the raw text at the match's offsets. The reader
# is a SIBLING, not a widening of the write list: `post_write_check` and the
# dead-rule audit read the write list as "files written", and a deleted path
# is not one. The zone check consumes `delete` and `move`; the secret-path
# check consumes `move`, `archive`, `alias` and `read` (a secret relocated,
# copied by effect, aliased, or surfaced by an interpreter literal read).
#: Long options of `tar` that take a value the next token supplies when not
#: glued with `=`.
_TAR_VALUED_LONG = frozenset({
    "file", "directory", "exclude", "exclude-from", "files-from", "transform",
    "owner", "group", "mode", "mtime", "format", "strip-components",
    "listed-incremental", "newer", "after-date", "suffix",
    "use-compress-program", "to-command",
})


def _tar_create_inputs(span: str) -> list[str]:
    """The inputs of a `tar` CREATE: every operand that is neither the
    archive (`-f`/`--file`) nor a flag's value; `[]` when the span creates
    nothing (an extract or a listing reads the archive; `-C DIR` on an
    extract is the write arm's). Old-style clusters (`czf out.tgz`), dashed
    clusters (`-cvf`), separated (`-c -f out.tar`) and long (`--create
    --file=out.tar`) spellings read alike: `c` anywhere in a cluster creates;
    a cluster ending in `f`, `C` or `T` takes the next token as its value; a
    valued long option without `=` takes the next token."""
    create = skip = end_opts = False
    inputs: list[str] = []
    for i, tok in enumerate(_operands(span)):
        if skip:
            skip = False
            continue
        if not end_opts and tok == "--":
            end_opts = True
            continue
        if not end_opts and tok.startswith("--"):
            name, eq, _value = tok[2:].partition("=")
            if name in ("create", "append", "update"):
                create = True             # append and update read the inputs too
            elif name in _TAR_VALUED_LONG and not eq:
                skip = True
            continue
        if not end_opts and (tok.startswith("-") or (i == 0 and tok.isalpha())):
            letters = tok.lstrip("-")
            if "c" in letters or "r" in letters or "u" in letters:
                create = True
            if letters and letters[-1] in "fCT":
                skip = True
            continue
        inputs.append(tok)
    return inputs if create else []


def _remove_effect(verb: str) -> str:
    """What a remove-roster verb does to its operands: `move` for the
    relocation verb by any spelling or case, `delete` for the rest -- ONE
    rule for the find arm, the carrier and the loop carrier (the review found
    it spelled three times, the find arm's without the case fold)."""
    return "move" if verb.lower().endswith("mv") else "delete"


def _find_delete_roots(span: str) -> tuple[list[str], str]:
    """The starting points of a `find` whose span carries a delete action,
    and the EFFECT they carry: `delete` (or `move` for an `-exec mv`) when
    nothing narrows the walk, `sweep` when a predicate does -- the root is
    then a starting point the consumer judges by itself, not by what it
    encloses. GNU's global options (`-H`, `-L`, `-P`, `-O<n>`, `-D <opts>`)
    sit before the roots and are stepped over; no root means `.` (GNU's
    default). `([], "")` when the span removes nothing."""
    action = _FIND_DELETE_ACTION_RE.search(span)
    if not action:
        return [], ""
    toks = _operands(span)
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok in _FIND_GLOBAL_OPTIONS or tok.startswith("-O"):
            i += 1
        elif tok == "-D":
            i += 2
        else:
            break
    roots: list[str] = []
    while i < len(toks) and not toks[i].startswith(("-", "(", "!")):
        roots.append(toks[i])
        i += 1
    effect = "sweep" if _find_is_narrowed(span, action.start()) else _remove_effect(action.group(0))
    return (roots or ["."]), effect


def _enum_head_key(head: str) -> str:
    """The dispatch key of one matched enumerator head text (DEF-831): a
    one-word head keys to itself; a multi-word head keys by its verb, by any
    spelling of that verb (quoted, `.exe`) and whatever global-option run
    sits between it and the subcommand. ONE mapping for both tools' readers,
    pinned against `_PIPED_ENUM_HEAD_KEYS` by the roster test."""
    words = head.split()
    word = words[0].lower().strip("\"'") if words else ""
    verb = word[:-4] if word.endswith(".exe") else word
    for key in _PIPED_ENUM_HEAD_KEYS:
        if " " in key and key.split()[0] == verb:
            return key
    return word


def _listing_roots(positionals: list[str]) -> tuple[list[str], bool]:
    """``(roots, narrowed)`` for a listing's positionals -- `ls` operands, or
    the version-control listing's positive pathspecs (DEF-831): `.` when
    none; a root whose leaf is a bare `*` is its directory; a bounded
    wildcard root narrows."""
    narrowed = False
    resolved: list[str] = []
    for r in positionals:
        bare = _shell_unquote(r)
        # a trailing separator names the same level (`*/` is every directory
        # under `.`, not a bounded wildcard -- the review drove it to a wipe)
        bare = bare.rstrip("/") or bare
        head_dir, _sep, leaf = bare.rpartition("/")
        if leaf in ("*", "**"):
            resolved.append(head_dir or ".")     # `*`, `./*`, `sub/*`: the directory itself
        else:
            if any(ch in bare for ch in "*?["):
                narrowed = True                  # a bounded wildcard root narrows
            resolved.append(r)
    return (resolved or ["."]), narrowed


#: The version-control listing's options that take a value as the NEXT token
#: when spelled alone (`-x PATTERN`, `-X FILE`, `--exclude PATTERN`; a `=`
#: form or a glued short value carries it). Every other switch is a flag.
#: The population selectors are ADDITIVE: `o` (others -- the untracked
#: files, the ignored ones included unless the standard excludes are
#: applied), `i` (the ignored ones, with `-o` or `-c`), and the tracked
#: family (`c` cached, `d` deleted, `m` modified, `s` stage, `u` unmerged,
#: `k` killed), any one of which beside `-o` makes the population wider
#: than untracked-only (the code review drove the cached-plus-others idiom,
#: the everyday "every non-ignored file" listing, from the wall to the
#: nudge when only the others selector was read).
_LS_FILES_VALUED_SHORT = frozenset("xX")
_LS_FILES_VALUED_LONG = frozenset({"exclude", "exclude-from", "with-tree", "format"})
_LS_FILES_TRACKED_SHORT = frozenset("cdmsuk")
_LS_FILES_TRACKED_LONG = frozenset({"cached", "deleted", "modified", "stage", "unmerged", "killed"})


def _git_c_base(head: str) -> str:
    """The `-C <dir>` run on a git head text, joined in order (git applies
    each relative to the one before it); empty when none."""
    base = ""
    toks = _OPERAND_TOKEN_RE.findall(head)
    for i, tok in enumerate(toks):
        if tok == "-C" and i + 1 < len(toks):
            nxt = _shell_unquote(toks[i + 1])
            base = nxt if (not base or nxt.startswith("/")) else base.rstrip("/") + "/" + nxt
    return base


def _git_listing_roots(head: str, args: str) -> tuple[list[str], bool, bool, bool]:
    """``(roots, narrowed, files_only, walks)`` for the version-control
    listing behind the carrier (DEF-831). The listing walks the index whole
    under the current location and prints files only, so the tracked
    population (the default, and every selector but the untracked-only one)
    and the ignored population (`-i`) are files-only walks: from the
    checkout root every tracked file goes (driven on both tools 2026-09-16).
    The untracked-only population (`-o` without `-i`) lists the ignored
    files too unless the standard excludes are applied (driven), so without
    them it is `git clean`'s ignored form -- the whole tree by that reader's
    rule (`_git_clean_operands`) -- and a files-only walk here; with them
    (`--exclude-standard`, or the per-directory spelling of the same) it is
    `git clean`'s untracked form, which that reader hands to the speed bump
    alone, so it sets neither flag: an un-narrowed sweep the soft tier
    nudges, a wipe only when the remove verb recurses (the one predicate's
    first arm, as for a listing); any tracked-family selector beside `-o`
    (`_LS_FILES_TRACKED_SHORT`) widens the population past untracked-only,
    so it is the whole again. Roots: the positive pathspecs by the listing
    rule (`_listing_roots`), `.` when none; an exclude-magic pathspec
    (`:!x`, `:^x`, `:(exclude)x`) is not a root and narrows nothing (the
    listing prints everything else); a redirection in the span is never a
    pathspec (as `_operands` has it; the code review drove a silenced
    stderr to the root). A `-C <dir>` global option on the head is the
    roots' base -- read as the root because the judge asks where the names
    can point, not where they were listed: the remove verb runs in the
    shell's directory, not the listing's, so the reading errs toward the
    nudge for a subdirectory value and is exact for `.` and the checkout
    root. A valued option consumes its value and `--` ends options. A
    pathspec outside the repository is refused by git itself (driven), so
    the listing never reads outside it. DECLARED LIMITS, pinned as rows: a
    top-magic pathspec (`:/`, `:(top)`) is judged from the current location
    (from a subdirectory the listing prints parent-relative names that
    reach the parent, and the wall stands only where the location itself is
    catastrophic); a `--git-dir` or `--work-tree` global option is not a
    root (`_git_c_base` reads `-C` alone -- those two move git, not where
    the remove verb's names resolve); a long option abbreviated to a prefix
    is unread, which leaves the selectors unset and reads the tracked whole
    -- over-refusal, never under."""
    others = ignored = standard = tracked = end_opts = skip = False
    paths: list[str] = []
    for tok in _OPERAND_TOKEN_RE.findall(_strip_span_tail(args)):
        if skip:
            skip = False
            continue
        if _REDIRECT_TOKEN_RE.match(tok):
            skip = _BARE_REDIRECT_OPERATOR_RE.match(tok) is not None   # and a bare operator's target
            continue
        if not end_opts and tok == "--":
            end_opts = True
            continue
        if not end_opts and tok.startswith("--"):
            name, eq, _value = tok[2:].partition("=")
            if name == "others":
                others = True
            elif name == "ignored":
                ignored = True
            elif name in _LS_FILES_TRACKED_LONG:
                tracked = True
            elif name in ("exclude-standard", "exclude-per-directory"):
                standard = True
                skip = name == "exclude-per-directory" and not eq
            elif not eq and name in _LS_FILES_VALUED_LONG:
                skip = True               # `--exclude PATTERN`: the next token is its value
            continue
        if not end_opts and tok.startswith("-") and len(tok) > 1:
            letters = tok[1:]
            for j, ch in enumerate(letters):
                if ch == "o":
                    others = True
                elif ch == "i":
                    ignored = True
                elif ch in _LS_FILES_TRACKED_SHORT:
                    tracked = True
                elif ch in _LS_FILES_VALUED_SHORT:
                    skip = j == len(letters) - 1   # `-x PATTERN` takes the next token; `-xPATTERN` carries it
                    break
            continue
        paths.append(tok)
    positives: list[str] = []
    for tok in paths:
        spec = _shell_unquote(tok)
        if spec.startswith(":"):
            magic, rest = "", spec[1:]
            if rest.startswith("("):
                magic, _close, rest = rest[1:].partition(")")
            elif rest[:1] in ("!", "^"):
                magic, rest = "exclude", rest[1:]
            elif rest.startswith("/"):
                magic, rest = "top", rest[1:]
            if "exclude" in magic.split(","):
                continue                  # not a root, and it narrows nothing
            spec = rest or "."            # `:/`, `:(top)`: the current location (declared limit)
        positives.append(spec)
    roots, narrowed = _listing_roots(positives)
    base = _git_c_base(head)
    if base:
        roots = [r if r.startswith("/") else (base if r == "." else base.rstrip("/") + "/" + r)
                 for r in roots]
    whole = not (others and standard and not ignored and not tracked)
    return roots, narrowed, whole, whole


def _find_head_roots(_head: str, args: str) -> tuple[list[str], bool, bool, bool]:
    """``(roots, narrowed, files_only, walks)`` for a `find` span behind the
    carrier: the roots are the leading positionals after GNU's global
    options, `.` when none; ``narrowed`` when a name-or-path predicate with
    a value that excludes something is in force (`_find_is_narrowed` over
    the whole span -- there is no action to stop at); ``files_only`` on
    `-type f`; a find always walks. The same roots the delete-action arm
    reads."""
    toks = _operands(args)
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok in _FIND_GLOBAL_OPTIONS or tok.startswith("-O"):
            i += 1
        elif tok == "-D":
            i += 2
        else:
            break
    roots: list[str] = []
    while i < len(toks) and not toks[i].startswith(("-", "(", "!")):
        roots.append(toks[i])
        i += 1
    narrowed = _find_is_narrowed(args, len(args))
    return (roots or ["."]), narrowed, bool(_FIND_TYPE_F_RE.search(args)), True


def _ls_head_roots(_head: str, args: str) -> tuple[list[str], bool, bool, bool]:
    """``(roots, narrowed, files_only, walks)`` for an `ls` span behind the
    carrier: the positionals that are not flags by the listing rule
    (`_listing_roots`); `-R` walks."""
    roots, narrowed = _listing_roots([tok for tok in _operands(args) if not tok.startswith("-")])
    return roots, narrowed, False, bool(_LS_WALK_RE.search(args))


#: One roots reader per head key -- the dispatch the openers' head groups
#: and the roster test derive from (`_PIPED_ENUM_HEAD_SPELLINGS`).
_PIPED_ENUM_HEAD_READERS: dict[str, Callable[[str, str], tuple[list[str], bool, bool, bool]]] = {
    "find": _find_head_roots,
    "ls": _ls_head_roots,
    "git ls-files": _git_listing_roots,
}
if set(_PIPED_ENUM_HEAD_READERS) != set(_PIPED_ENUM_HEAD_KEYS):
    # `raise`, not `assert`: a head with no reader of its own would fall to
    # whichever branch came last and read a wrong root silently (the
    # failure-mode review drove a fourth roster word through the `ls`
    # grammar with every gate green); the reader-head roster refusal above
    # is the precedent.
    raise RuntimeError("enumerator head roster drift: the head keys and the roots readers disagree")


def _bash_pipeline_roots(head: str, args: str) -> tuple[list[str], bool, bool, bool]:
    """``(roots, narrowed, files_only, walks)`` for one enumerator span behind
    the carrier (DEF-826), by the reader of the head's key (`_enum_head_key`,
    `_PIPED_ENUM_HEAD_READERS`): `find` and `ls` from the span alone, the
    version-control listing (DEF-831) from the head text (its `-C`) and the
    span. A key with no reader is unreachable: the openers compose their
    head groups from the same table the readers are checked against."""
    return _PIPED_ENUM_HEAD_READERS[_enum_head_key(head)](head, args)


def _bash_pipeline_reading(
    command: str, m: "re.Match[str]",
) -> tuple[list[str], bool, bool, str, list[str]]:
    """One matched carrier pipeline, read from the RAW text at the match's
    offsets: ``(roots, narrowed, wipe, effect, extra)``. ``wipe`` when the
    remove verb recurses, the walk recurses (find; `ls -R` -- on bash a
    recursive walk into a plain rm takes every file, driven) or the
    enumeration is files-only; ``effect`` is `move` behind `mv`, else
    `delete`; ``extra`` is any explicit operand on the remove verb beside the
    stdin ones (`xargs rm -rf ./also`), the `{}` placeholder excluded."""
    # the head from the RAW text, as the spans are: a `-C` value on the
    # listing head carries the root, which the mask may have rewritten (the
    # row probe's paren shape drove the PowerShell twin to a nudge)
    head = _named_span(command, m, "head")
    args = _named_span(command, m, "args")
    roots, narrowed, files_only, walks = _bash_pipeline_roots(head, args)
    verb = _named_span(command, m, "verb")
    rmargs = _named_span(command, m, "rmargs")
    recursive, _force, operands = rm_recursive_force_operands("rm" + rmargs)
    # the placeholder is the carrier's, not an operand: the braces, and the
    # value of a placeholder switch by either spelling (`-I %`, `-J %`)
    carrier = command[m.end("args"):m.start("verb")]
    placeholders = {"{}"} | set(re.findall(r"-[IJ][ \t]*([^\s;|&]+)", carrier))
    extra = [op for op in operands if _shell_unquote(op) not in placeholders]
    effect = _remove_effect(verb)
    wipe = _sweep_is_wipe(recursive, files_only, walks, native=True)
    return roots, narrowed, wipe, effect, extra


def _loop_variable_named(op: str) -> "str | None":
    """The name an rm operand expands when it is exactly one parameter
    expansion (bare, braced, double-quoted): the loop's placeholder."""
    m = _LOOP_OPERAND_RE.match(op)
    return (m.group(1) or m.group(2)) if m else None


def _bash_loop_reading(
    command: str, m: "re.Match[str]",
) -> tuple[list[str], bool, bool, str, list[str]]:
    """One matched loop carrier (DEF-830), read from the RAW text at the
    match's offsets: ``(roots, narrowed, wipe, effect, extra)`` as
    `_bash_pipeline_reading` returns them. The body's verb must take an
    operand that expands a name the loop head binds (`REPLY` when the read
    names none) -- that operand is the carrier's placeholder -- or the loop
    is not the carrier and ``effect`` is `none` (the body removes a fixed
    operand: the rm tier's own). Every other operand of a remove is removed
    as spelled (``extra``); a move's other operand is its destination.

    Two roots shapes, one wipe rule (DEF-837), the shape read from
    `_LOOP_OPENERS`. An ENUMERATOR head's roots are the carrier reader's. The
    WORD-LIST head has no enumerator: its roots are the list's words as bash
    reads them, cut by the word regex on the SCAN span that matched and read
    from the raw text at each word's offsets, kept RAW -- the form the rm
    tier hands its own judge (quoting decides a glob); the zone reader
    unquotes them, as every other producer's paths arrive. A word list
    narrows nothing as a whole (a bounded word narrows only itself). The
    wipe is ONE rule for the family (`_sweep_is_wipe`): a recursing remove
    takes everything under each item it is handed, forced or not -- rm
    prompts only for an unwritable file and only on a terminal, so `rm -r`
    in an agent's shell is the wipe `rm -rf` is. The rm tier reads the same
    threshold since DEF-842 (it read recursive AND forced until then, and
    the direct `rm -r *` drew nothing while this head walled its loop); the
    non-recursive pair stays silent on both."""
    roots, narrowed, files_only, walks = _loop_head_reading(command, m)
    verb = _named_span(command, m, "verb")
    rmargs = _named_span(command, m, "rmargs")
    recursive, _force, operands = rm_recursive_force_operands("rm" + rmargs)
    names = set(_named_span(command, m, "vars").split()) or {"REPLY"}
    # The placeholder sits in one of two places, and `feed` says which.
    # Direct arm: an OPERAND of the body's remove expands a bound name.
    # Carrier-fed arm (DEF-836): the remove takes its items from stdin, so
    # the verb has no operand at all -- the placeholder is the word emitted
    # into the carrier, and asking the operands would answer "not the
    # carrier" for a body that is exactly the carrier. Both go through
    # `_loop_variable_named`, so the variable's spellings keep one home.
    feed = _named_span(command, m, "feed")
    if feed:
        if _loop_variable_named(feed) not in names:
            return roots, narrowed, False, "none", []
    elif not any(_loop_variable_named(op) in names for op in operands):
        return roots, narrowed, False, "none", []
    effect = _remove_effect(verb)
    extra: list[str] = [] if effect == "move" else [
        op for op in operands if _loop_variable_named(op) not in names
    ]
    wipe = _sweep_is_wipe(recursive, files_only, walks, native=True)
    return roots, narrowed, wipe, effect, extra


def _loop_head_reading(command: str, m: "re.Match[str]") -> tuple[list[str], bool, bool, bool]:
    """``(roots, narrowed, files_only, walks)`` for one matched loop head,
    the shape read from `_LOOP_OPENERS`: an ENUMERATOR's by the carrier's
    reader; a WORD LIST's words cut by the word regex on the SCAN span that
    matched and read raw from ``command`` at each word's offsets -- never
    narrowed as a whole, no walk, each word a named target."""
    if _LOOP_OPENER_SHAPE[m.re] == "words":
        roots = [
            command[w.start():w.end()]
            for w in _FOR_LIST_WORD_RE.finditer(m.string, m.start("args"), m.end("args"))
        ]
        return roots, False, False, False
    return _bash_pipeline_roots(_named_span(command, m, "head"), _named_span(command, m, "args"))


class _LoopRemoval(NamedTuple):
    """One matched loop carrier as PATH values (`_loop_removal_paths`), read
    BY NAME: two fields are effect strings, and a positional swap of them
    type-checked and silently dropped every narrowed loop (DEF-837's review)."""
    root_effect: str        # `delete` or `move`; `sweep` when the head is narrowed
    effect: str             # the body verb's own effect
    roots: list[str]        # the head's roots as path values
    extra: list[str]        # fixed operands beside the variable, as spelled
    whole: bool             # each root is taken WHOLE: a named word, or an
                            # enumeration reaching every file under it


def _loop_removal_paths(command: str, m: "re.Match[str]") -> "_LoopRemoval | None":
    """One matched loop carrier as PATH values, for the two readers that
    compare paths rather than judge words -- the zone check and the
    discard-snapshot arm; None when the body removes a fixed operand instead
    of the variable (the rm arm reads that operand on its own). A word
    list's roots arrive RAW, as the wall judges them; a path reader wants
    their values, as the enumerator heads hand them. ``whole`` is whether
    the head hands the body every file under each root: a word is named
    whole; an enumeration is whole when it is files-only or walks
    (`find`, `ls -R`, the full version-control listing) -- an untracked-only
    listing or one level of `ls` is not."""
    roots, narrowed, _wipe, effect, extra = _bash_loop_reading(command, m)
    if effect == "none":
        return None
    if _LOOP_OPENER_SHAPE[m.re] == "words":
        roots = [_shell_unquote(p) for p in roots]
        whole = True
    else:
        _roots, _narrowed, files_only, walks = _loop_head_reading(command, m)
        whole = files_only or walks
    return _LoopRemoval("sweep" if narrowed else effect, effect, roots, extra, whole)


def _extend_loop_operands(out: list[tuple[str, str]], command: str, m: "re.Match[str]") -> None:
    """The zone check's reading of one matched loop carrier (DEF-830): the
    roots as `delete` or `move` (a `sweep` when narrowed, its root judged by
    itself as the find arm's is), the fixed siblings beside the variable as
    spelled; nothing when the body removes a fixed operand instead."""
    read = _loop_removal_paths(command, m)
    if read is None:
        return
    out.extend((read.root_effect, p) for p in read.roots)
    out.extend((read.effect, p) for p in read.extra)


def _git_clean_operands(span: str) -> list[str]:
    """What a `git clean` span removes: its path operands; `.` (the whole
    tree) for the no-operand form that carries a force flag AND the
    ignored-files flag (`-x`/`-X`); nothing for a dry run or for the
    untracked-only no-operand form (the speed bump's)."""
    force = ignored = dry = end_opts = skip = False
    paths: list[str] = []
    for tok in _OPERAND_TOKEN_RE.findall(_strip_span_tail(span)):
        if skip:
            skip = False
            continue
        if _REDIRECT_TOKEN_RE.match(tok):
            # a redirection (and a bare operator's target) is never a path,
            # as `_operands` has it: the DEF-831 review drove a silenced
            # stderr to this reader's whole-tree operand -- the same hole
            # the listing reader had, one class
            skip = _BARE_REDIRECT_OPERATOR_RE.match(tok) is not None
            continue
        if not end_opts and tok == "--":
            end_opts = True
            continue
        if not end_opts and tok.startswith("--"):
            name = tok[2:]
            if name == "force":
                force = True
            elif name == "dry-run":
                dry = True
            elif name == "exclude":
                skip = True
            continue
        if not end_opts and tok.startswith("-") and len(tok) > 1:
            letters = tok[1:]
            force = force or "f" in letters
            dry = dry or "n" in letters
            ignored = ignored or "x" in letters or "X" in letters
            if letters.endswith("e"):
                skip = True               # `-e PATTERN`: the next token is its value
            continue
        paths.append(tok.strip('"').strip("'"))
    if dry:
        return []
    if paths:
        return paths
    return ["."] if force and ignored else []


def _ln_symlink_flagged(span: str) -> bool:
    """True when an `ln` span carries the symlink flag (the symlink leg's
    arm reads that one; this test keeps the two arms from reading one row)."""
    for tok in _OPERAND_TOKEN_RE.findall(span):
        if tok == "--":
            return False
        if tok.startswith("--"):
            if tok[2:].lower().startswith("symbolic"):
                return True
        elif tok.startswith("-") and "s" in tok[1:]:
            return True
    return False


def iter_removed_or_relocated_operands(command: str, _depth: int = 0) -> list[tuple[str, str]]:
    """Every operand a Bash command removes, relocates, archives, aliases or
    reads by an interpreter literal, as ``(effect, path)`` pairs: `delete`
    (the remove verbs, `git rm`, a `find` with a delete action and nothing
    narrowing it, the interpreter delete literals), `sweep` (a `find` root
    under a narrowing predicate -- judged by itself, not by what it
    encloses), `clean` (`git clean`: a path operand, or `.` for the
    no-operand ignored-files form), `move` (a `mv` source -- every source
    under a target-directory flag -- `git mv`, `rename`, a `find -exec mv`,
    the interpreter rename literals), `archive` (a tar create's, append's or
    update's inputs, `zip`'s, `dd`'s input), `alias` (the target of `ln` and
    `ln -s`) and `read` (an interpreter literal read). Nested programs -- a
    POSIX shell's `-c` word, a PowerShell program, what a reader head hands
    to a shell -- are read by the grammar that runs them, one level down, to
    the same bound as the write extractor. Same prologue as
    `_candidate_paths_from_bash`. Memoised per command: the zone check and
    the secret check both ask on one tool call."""
    return list(_removed_or_relocated_cached(command, _depth))


@functools.lru_cache(maxsize=8)
def _removed_or_relocated_cached(command: str, _depth: int) -> tuple[tuple[str, str], ...]:
    return tuple(_iter_removed_or_relocated_operands(command, _depth))


def _iter_removed_or_relocated_operands(command: str, _depth: int = 0) -> list[tuple[str, str]]:
    command, scan = _extractor_pair(command)
    out: list[tuple[str, str]] = []
    for m in _DESTROY_RE.finditer(scan):
        out.extend(("delete", p) for p in _positional_operands(raw_span(command, m)))
    for m in _CP_MV_RE.finditer(scan):
        if m.group("verb").lower() != "mv":
            continue
        span = raw_span(command, m, 2)
        positionals = _positional_operands(span)
        target_dirs, ambiguous = _target_directory_readings(span, _CP_MV_VALUELESS_SHORT)
        sources = [p for p in positionals if p not in target_dirs] if target_dirs else []
        if not target_dirs or ambiguous:
            sources.extend(positionals[:-1])
        out.extend(("move", p) for p in dict.fromkeys(sources))
    for m in _GIT_RM_MV_RE.finditer(scan):
        effect = "delete" if m.group(1).lower() == "rm" else "move"
        out.extend((effect, p) for p in _positional_operands(raw_span(command, m, 2)))
    for m in _RENAME_RE.finditer(scan):
        out.extend(("move", p) for p in _positional_operands(raw_span(command, m))[1:])
    for m in _FIND_DELETE_RE.finditer(scan):
        roots, effect = _find_delete_roots(raw_span(command, m))
        out.extend((effect, p) for p in roots)
    # DEF-826: the enumerator piped through xargs into a remove verb -- the
    # enumerator's roots are the operands (a narrowed one is a `sweep`, its
    # root judged by itself as the find arm's is), and an explicit operand
    # beside the stdin ones is removed too.
    for m in _PIPED_REMOVE_RE.finditer(scan):
        roots, narrowed, _wipe, effect, extra = _bash_pipeline_reading(command, m)
        # narrowing wins over the verb, as `_find_delete_roots` has it: a
        # narrowed enumerator's root is judged by itself whether the verb
        # behind the carrier removes or relocates
        root_effect = "sweep" if narrowed else effect
        out.extend((root_effect, p) for p in roots)
        out.extend((effect, p) for p in extra)
    # DEF-830: the loop carrier -- the enumerator's output bound to a loop
    # variable and removed in the body, three enumerator heads -- read as
    # the carrier is; a body that removes a fixed operand instead of the
    # variable is not the carrier (the rm arm above reads that operand on
    # its own). DEF-837: the fourth head, the for loop over a word list,
    # hands this reader its words as the rm arm reads a plain remove's
    # operands, wipe or not -- until it did, a list naming a protected path
    # was allowed where the direct remove was refused
    # -- each opener spelled by name, as every arm here is, so the roster
    # census (`_MUTATION_ARMS`, pinned by an AST walk over these calls) sees
    # it; gated on the witness as the two tiers are (the review)
    if _loop_carrier_witnessed(command):
        for m in _LOOP_REMOVE_RE.finditer(scan):
            _extend_loop_operands(out, command, m)
        for m in _FOR_SUBST_REMOVE_RE.finditer(scan):
            _extend_loop_operands(out, command, m)
        for m in _TAIL_LOOP_REMOVE_RE.finditer(scan):
            _extend_loop_operands(out, command, m)
        for m in _FOR_WORDS_REMOVE_RE.finditer(scan):
            _extend_loop_operands(out, command, m)
    for m in _GIT_CLEAN_RE.finditer(scan):
        out.extend(("clean", p) for p in _git_clean_operands(raw_span(command, m)))
    for m in _TAR_CREATE_RE.finditer(scan):
        out.extend(("archive", p) for p in _tar_create_inputs(raw_span(command, m)))
    for m in _ZIP_RE.finditer(scan):
        out.extend(("archive", p) for p in _positional_operands(raw_span(command, m))[1:])
    for m in _DD_IF_RE.finditer(scan):
        out.append(("archive", raw_operand(command, m, word=True)))
    for m in _LN_S_RE.finditer(scan):
        ops = _positional_operands(raw_span(command, m))
        if len(ops) >= 2:
            out.append(("alias", ops[0]))
    for m in _LN_CP_INVOCATION_RE.finditer(scan):
        if m.group(1).lower() != "ln":
            continue
        span = raw_span(command, m, 2)
        if _ln_symlink_flagged(span):
            continue
        ops = _positional_operands(span)
        if len(ops) >= 2:
            out.append(("alias", ops[0]))
    for interp, body in _inline_program_bodies(command, scan):
        out.extend(_program_effects(interp, body))
    for interp, body in _stdin_program_bodies(command, scan):
        if interp in _STDIN_SHELL_HEADS:
            continue
        out.extend(_program_effects(interp, body))
    for head, body in _piped_program_bodies(command):
        family = _reader_family(head)
        if family is not None:
            out.extend(_program_effects(family, body))
    if _depth < _PS_STDIN_MAX_DEPTH:
        for program in _posix_shell_c_bodies(command, scan):
            out.extend(iter_removed_or_relocated_operands(program, _depth + 1))
        for program in _shell_program_bodies(command, scan):
            out.extend(iter_ps_removed_or_relocated_operands(program, _depth + 1))
        for program in _shell_out_program_bodies(command, scan):
            out.extend(iter_removed_or_relocated_operands(program, _depth + 1))
    return out


# ── Catastrophic recursive delete detection (flag-order-independent; forced or not, DEF-842) ──
#
# write_guard.DANGEROUS_BASH_PATTERNS hard-denies `rm -rf /` and `rm -rf *` with
# two literal regexes. Those match ONLY the glued `-rf` flag order against a bare
# `/`/`*`; every other spelling bypasses them. The gap is not just flag-order --
# it spans target SPELLING and command STRUCTURE. A safety hard-deny for the
# irreversible tier must apply the statically-decodable shell transforms before
# classifying, not regex one fixed surface. Classes caught here (each working in
# bash/zsh):
#   - flag order/spelling:  rm -fr /, rm -r -f /, rm --recursive --force /,
#                           rm -rvf /, rm -Rf /, rm -rf -- /, rm -rf x /
#   - escaped target:       rm -rf \/ , rm -rf \/etc
#   - quote-spliced target: rm -rf '/'etc , rm -rf "/"etc , rm -rf ''/ , rm -rf '/'*
#   - brace-expanded:       rm -rf {/bin,/etc} , {,}{/etc,/var} (multi-group/empty-alt)
#   - brace ASCII sequence: rm -rf {.../}etc  ({c1..c2} range straddling / or *)
#   - line continuation:    rm -rf \<newline>/ , rm -r\<newline>f /
#   - command case (NTFS/   RM -rf /   (case-insensitive FS resolves RM->/bin/rm;
#     APFS):                cf. corpus BC-025, the sister case-insensitive bypass)
#
# Still OUT OF SCOPE (documented module-wide above; cannot be statically
# resolved): $(...) command substitution, ${VAR:-default} parameter expansion,
# $'...' ANSI-C quoting, two-step write-then-exec, cross-command variable
# indirection. `rm -fr/` (glob/path glued onto the flag cluster) is a shell
# SYNTAX ERROR (rm rejects the invalid option), not a working bypass.
#
# Target semantics mirror the two regexes, generalized: a POST-TRANSFORM operand
# that starts with "/" (any absolute path) or "*" (cwd glob / *.ext / /*).
# cwd-relative `.`/`./`, `~`/`$VAR`, and source/build paths are NOT hard-denied
# here -- they are the soft speed-bump tier's concern (CP-RMRF).

# \b(?!=): match the `rm` COMMAND but exclude a `rm=…` shell assignment (`=` is a
# word boundary a bare `\brm\b` false-matched, feeding the assignment value to the
# rm operand iterator). Excluding ONLY `=` (not every non-space char) is critical:
# a quoted `'rm' -rf /` collapses to a real root delete, and a `(?=\s)` guard would
# blind this catastrophic-rm hard-deny -- a fail-closed false-negative.
#: Recognized-safe RELATIVE ephemeral directories -- the ONE roster, shared by
#: the Bash soft tier (`_speedbump._pred_rmrf`) and the PowerShell hard-deny
#: carve-out (`powershell_removal_is_recognized_safe`). Kept here because this
#: module is already the declared single source of truth for the flag tokenizer
#: and the rm-invocation iteration; a second copy is how the two tiers drift.
SAFE_EPHEMERAL_DIRS: tuple[str, ...] = (
    "tmp/", "node_modules", ".cache", "dist", "build",
    ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache",
)

# ── PowerShell command position ────────────────────────────────────────────
# The Bash records have carried `_CMD_POS` for months; the PowerShell twins never
# did, and the cost was measured on 2026-08-24: SIXTEEN of sixteen inert shapes
# were refused -- 100%. A `#` comment, a `$doc = '...'` assignment, a
# `<# .SYNOPSIS #>` help block, `Select-String` searching the docs FOR the
# pattern, and `git commit -m` describing it all denied, on the tier maintenance
# mode cannot bypass. A Windows adopter grepping their own documentation was
# blocked, and a guard that refuses ten harmless things before it earns its keep
# gets switched off -- at which point it protects nobody.
#
# `_PS_CMD_POS_SEP` is the statement-separator arm: a real invocation sits at the
# start, or after `;` `|` newline `(` `{` `}` or the `&` call operator.
#
# `_PS_CMD_POS_EXEC_QUOTE` is the arm that keeps this fail-CLOSED, and it is
# deliberately UNANCHORED for the same reason its Bash counterpart is (see
# `_bash_patterns._EXEC_OPENER_RE`): `Invoke-Expression "Remove-Item …"` reaches a
# parser from inside another command's ARGUMENT, where no separator precedes it.
# Anchoring on the separator alone would relieve the prose and open every
# re-parsing form in the same stroke. Dropping this arm is the one edit here that
# converts a friction fix into a fail-open.
# ⚠ `=` IS A COMMAND POSITION IN POWERSHELL. Assigning a command's output RUNS
# the command, so `$x = Remove-Item -Recurse -Force C:\` executes exactly as the
# bare form does -- and with `=` missing from this class it went DENY -> ALLOW.
# `$null =`, `$script:x =`, `[void]$x =` and `+=` all ride the same character.
# Relieving `$pattern = 'Remove-Item …'` is unaffected: the quote sits between
# `=` and the verb and `[ \t]*` cannot cross it, so the MENTION stays allowed
# while the USE is caught. `return`/`throw` take an expression that is evaluated
# the same way. Found by an adversarial pass, not by the corpus -- the corpus had
# the quoted assignment as a must-ALLOW row with no unquoted must-DENY twin,
# which is the born-weak shape: relief and blind spot shipped in one edit.
#
# The CALL OPERATOR with a quoted command name (DEF-791): `& 'git' reset
# --hard`, `& "Set-Content" <hook> x`, `& 'C:\Program Files\Git\cmd\git.exe'
# ...` -- ordinary PowerShell for a command whose name or path carries a
# space, and the one spelling where a quote opens a command position (a
# quoted string after `;` or at the start of a statement is an expression,
# never a call, so the quote belongs to `&` alone and NOT to the `=` arm,
# where it would undo the mention relief above). The masker keeps token
# content, so the quoted verb reaches the matcher; the arm is the PowerShell
# twin of the Bash `_CMD_POS_VERB_PREFIX` quote-and-path form, bounded the
# same way, and every verb arm composed on `_PS_CMD_POS` closes it with
# `_QUOTED_VERB_TAIL`. Measured through the live hook 2026-09-13: ten of
# sixteen bare/quoted pairs flipped from deny or bump to allow -- every
# cmdlet arm and the git discard bump; the arms behind `_PS_EXE_PREFIX`,
# which carries its own copy of this form, already held.
#: The call operator with a quoted command name or path (`& 'git'`, `& "C:\x\
#: git.exe"`): ONE home for the separator arm below and for `_PS_EXE_PREFIX`'s
#: first arm, which carried the same form before this arm existed (code
#: review, 2026-09-13: two literal copies of a shared shape drift apart).
_PS_CALL_OPERATOR_QUOTE = r"&[ \t]*[\"'](?:[^\"'\n]{0,256}[/\\])?"
_PS_CMD_POS_SEP = (
    r"(?:(?:^|[;|\n\r(){}&]|=)[ \t]*"
    "|" + _PS_CALL_OPERATOR_QUOTE +
    r"|\b(?:return|throw)[ \t]+)"
)
# The run of switches between a re-parsing opener and its quoted payload,
# shared by the exec-quote arm below and by `_PS_REPARSED_SPAN_BEFORE` (which
# looks BACKWARDS over the same run to decide whether a literal span is live).
# ONE constant, two consumers, pinned to each other: the two sites carrying
# different runs is exactly the split DEF-717's single-quoted row fell through.
#
# `[-/]`, not `-`. Driven 2026-08-24: with `-` alone, `cmd /c "Remove-Item
# -Recurse -Force C:\"` went DENY -> ALLOW -- a fail-open introduced in the same
# edit that relieved the prose, caught only because the must-deny corpus ran
# against a CALIBRATED baseline. Windows flags are slash-led.
#
# ONE BARE VALUE PER SWITCH (DEF-717). The run used to be `(?:[-/][\w:]+[ \t]*)*`
# and stopped at a switch's bare value, so no command position opened after
# `-Verb RunAs` (Windows's sudo -- the spelling an agent uses exactly when it
# needs to change a hook it does not own), `-ExecutionPolicy Bypass` (every
# script-runner snippet) or `-WindowStyle Hidden`, and the payload behind them
# was inert to EVERY matcher; the same command with `-ArgumentList` first
# denied. The value token may not start with a switch lead or a quote, so a
# following switch or the payload quote can never be eaten as a value.
#
# ⚠ THE VALUE MUST CONSUME ITS WHOLE TOKEN -- the `(?=[ \t]|$)` is the ReDoS
# fix, not decoration. The value's tail `[^\s]*` admits `-` and `/`, so a value
# holding either (`b-c`, `c:/x-y` -- an ordinary Windows argument) had two
# parses: the value swallows the token, or it stops early and the remainder
# is re-read as further switches. Inside one `*` loop that is exponential on
# failure: the first cut hung the deployed hook for 20 s on a 305-byte
# command (code review, driven -- a PreToolUse slow-hook fail-open), while
# the timing pin that shipped with it used dash-free values and stayed green.
# Forcing the value to end at whitespace leaves one parse per token: 0.04 ms
# at the shape that took 42 s, under 10 ms at 63 KB (`tests/test_redos.py`
# drives both dash-bearing shapes under the SIGALRM watchdog).
#
# DECLARED LIMITS, pinned in `test_write_guard_command_position`: a value that
# is a QUOTED string (`-Verb "RunAs"`, `-WindowStyle "Hidden"`), an `=`-bound
# value (`-ArgumentList="..."`) and the array spelling (`-ArgumentList
# "-Command","<write>"`) end the run before the payload, so the payload stays
# inert -- the fail-open direction, declared rather than claimed.
# `[\w:.-]+`, not `[\w:]+`: the Windows launcher's version switch is `-3.12`
# and node's are double-dash (`--no-warnings`, `--stack-size 2000`) -- DEF-712's
# interpreter arm composes this run before `-c`/`-e` -- and a dot or a dash
# inside the token is exclusive of the whitespace that ends it, so no second
# parse opens; a value still may not START with a dash, so a following switch
# is never read as a value.
#
# `{0,64}`, not `*` (DEF-637's witness row, a sister of the DEF-717 fix
# above): a run whose VALUES are the next opener word -- `powershell -Command
# powershell -Command ...` -- is one parse per token, as the fix promised, but
# it is read to the END of the command as switch-plus-value pairs, O(n), at
# each of the n command positions the opener is tried from. Quadratic:
# driven at HEAD, 24 s on 28 KB and one second on 6 KB, the slow-hook
# fail-open shape, invisible to the dash-bearing rows because their values
# were never opener words. No real command carries sixty-four switches
# before its payload; the bound makes each attempt O(64) and the flood linear.
#
# AND (DEF-637's witness row, the sister of the DEF-717 fix above) a
# switch's value may not be a re-parsing opener word. A flood of
# `-Command powershell -Command powershell ...` -- or `iex -x iex -x ...`,
# which carries no values at all, yet `iex` after `-x` READ as one -- was
# read as switch-plus-value pairs to the END of the command, O(n), at each
# of the n opener positions, and every matcher composing `_PS_CMD_POS`
# walked it again: 24 s on 28 KB and one second on 6 KB, driven at HEAD, the
# slow-hook fail-open shape. With the opener words refused as values
# (`_PS_REPARSE_OPENER_WORDS`, the roster spelled once) the run stops at
# the next opener, each attempt is O(1) and the flood is one pass -- 70 ms;
# a real `-Verb RunAs` or `-ExecutionPolicy Bypass` value is untouched.
# The run stays UNBOUNDED: a `{0,64}` bound was tried first and measured
# twice -- it left the flood at 20 s (the product above is the cost, not the
# run's length) and it turned `python -B` x65 `-c "<write>"`, a command that
# runs, from a deny into an allow (code review, driven on both legs). A
# bound here is a coverage hole with no receipt.
_PS_REPARSE_OPENER_WORDS = (
    r"(?:Invoke-Expression|iex|Invoke-Command|icm|Start-Process|saps"
    r"|powershell(?:\.exe)?|pwsh(?:\.exe)?|cmd(?:\.exe)?)"
)
_PS_SWITCH_RUN = (
    r"[ \t]*(?:[-/][\w:.-]+(?:[ \t]+(?!" + _PS_REPARSE_OPENER_WORDS
    + r"(?=[ \t]|$))[^\s\"'\-/][^\s]*(?=[ \t]|$))?[ \t]*)*"
)

# A script block built from a string literal is a PROGRAM (DEF-760, §C5):
# `& ([scriptblock]::Create("Get-Date; <delete> C:\"))` runs the string, and
# so does the single-quoted twin, yet neither the masker's lookbehind nor the
# records' anchor saw the span, because the static `Create` method is not a
# WORD the roster above could hold (`\b` cannot open before `[`). It joins
# the openers as its own branch, and UNCONDITIONALLY: the string is code
# whether or not this statement invokes it, so `$sb = [scriptblock]::Create(
# "...")` is refused too -- the ordinary assign-then-invoke spelling
# (`; & $sb`) hands the block over through a variable the indirection class
# declares unreadable, and conditioning on an invocation in the same
# expression would have let exactly that form through (operator decision,
# 2026-09-13). The bare type in prose (`Write-Output "[scriptblock]::Create
# builds..."`) opens nothing: there is no `(` and no span. The switch run
# above keeps its WORD roster -- this opener has no switches. Bounded
# literal, one optional whitespace run before the paren.
_PS_SCRIPTBLOCK_CREATE = (
    r"(?i:\[(?:System\.Management\.Automation\.)?scriptblock\]::Create)[ \t]*\("
)

# The re-parsing openers, hoisted for the same reason as the run: the arm
# and the lookbehind must roster the SAME openers, and two literal copies
# were one edit away from the DEF-717 split with the run pin still green
# (failure-mode review). The pin covers both constants, and the `Create`
# branch beside the words.
_PS_REPARSE_OPENERS = (
    r"(?:\b" + _PS_REPARSE_OPENER_WORDS + r"\b|" + _PS_SCRIPTBLOCK_CREATE + r")"
)

_PS_CMD_POS_EXEC_QUOTE = _PS_REPARSE_OPENERS + _PS_SWITCH_RUN + r"[\"\']?[ \t]*"

# Built by `+` concatenation of module-level names, NOT an f-string. The
# dot-star ReDoS gate reconstructs a pattern statically from Name refs and `+`;
# an f-string is opaque to it, so every record built on this one reported as
# "statically un-reconstructable" and the gate could not prove them safe. Same
# construction as `_CMD_POS` above, for the same reason.
_PS_CMD_POS = "(?:(?:" + _PS_CMD_POS_SEP + ")|(?:" + _PS_CMD_POS_EXEC_QUOTE + "))"

#: The PowerShell twin of `_DIR_VERB_RE` (DEF-509; the Bash block above
#: `_candidate_paths_from_bash` is the home of the reasoning), over
#: `powershell_scan_text`: the location cmdlets and their aliases, an optional
#: `-Path` / `-LiteralPath` before the operand, trailing switches
#: (`-PassThru`) stepped over. Matched against one right-stripped statement;
#: every optional piece begins with its own whitespace run. A script block's
#: `Set-Location` persists in the caller, so braces push nothing.
_PS_DIR_VERB_RE = re.compile(
    _PS_CMD_POS
    + r"(Set-Location|Push-Location|Pop-Location|chdir|pushd|popd|cd|sl)(?![-\w])"
    + _QUOTED_VERB_TAIL
    + r"(?:[ \t]+-(?:Path|LiteralPath|PSPath))?"
    + r"(?:[ \t]+(?:(['\"])([^'\"\n]{0,512})\2|(-|[^\s'\"<>-][^\s'\"<>]{0,511})))?"
    + r"(?:[ \t]+-\w{1,32}){0,4}$",
    re.IGNORECASE,
)
_PS_CHAIN_BOUNDARY_RE = re.compile(r"&&|\|\||[;|\n{}]")
_PS_DIR_VERBS = {
    "set-location": "cd", "cd": "cd", "sl": "cd", "chdir": "cd",
    "push-location": "pushd", "pushd": "pushd", "pop-location": "popd", "popd": "popd",
}

# An executable given by PATH before a matched head -- the PowerShell twin of
# `_CMD_POS_VERB_PREFIX`. `& "C:\Python312\python.exe" -c ...`,
# `.\venv\Scripts\python.exe -c ...`, `& 'C:\Program Files\...\python.exe'`
# and `C:\Windows\System32\icacls.exe <hook> /deny ...` all name the head at
# the end of a path, and every PowerShell matcher required the head to START
# the token (DEF-697 declared it; DEF-712 closes it). Three arms, exclusive:
#   * the CALL OPERATOR then a quoted token, with or without a path in it
#     (`& "python"`, `& 'C:\Program Files\...\python.exe'`; spaces allowed,
#     bounded). The `&` is part of this arm on purpose: a quoted token at a
#     command position WITHOUT it is an expression, not an invocation, so
#     `$doc = "icacls <hook> /deny ..."` is a string -- the first cut let a
#     bare quote open the head and denied that mention (driven);
#   * a bare path of separator-terminated segments, drive letter optional
#     (each segment is exclusive of the separator that ends it, so `//` is
#     two empty segments and the parse is unique);
#   * nothing, at a token start (the lookbehind refuses `xicacls` and
#     `my-python`; `\b` cannot follow a re-parser's quote, which
#     `_PS_CMD_POS_EXEC_QUOTE` has already consumed).
# The head's closing quote, when the first arm opened one, is the consumer's
# (`[\"']?` after the head). The quoted arm's bounded class admits the
# separator, so a quoted prefix has as many parses as it has separators --
# the same bounded shape `_CMD_POS_VERB_PREFIX` carries, pinned linear by
# `test_cmd_pos_linear_on_repeated_prefix_run` and here by its PS twin.
_PS_EXE_PREFIX = (
    "(?:" + _PS_CALL_OPERATOR_QUOTE +
    r"|(?:[A-Za-z]:)?(?:[\w.~-]*[/\\])+"
    r"|(?<![\w.~/\\-]))"
)

# ⚠ THE SAME OPENER ROSTER, LOOKING BACKWARDS, AND THE SPLIT IS MEASURED NOT
# REASONED. `_PS_CMD_POS_EXEC_QUOTE` above asks "is a command position opening
# here"; this asks "is the span I am about to blank one that a re-parser will
# execute". Driven against real pwsh 7.6.5 on 2026-08-26, writing a marker file
# from inside the span:
#
#   iex '$env:VAR=1; <cmd>'        LITERAL     -> RUNS
#   iex @'...'@                    LITERAL     -> RUNS
#   iex "$env:VAR=1; <cmd>"        EXPANDABLE  -> sets NOTHING (see below)
#   iex "`$env:VAR=1; <cmd>"       escaped $   -> RUNS
#
# The expandable row is the surprise: PowerShell interpolates `$env:VAR` at
# parse time, before `iex` receives the string, so the ASSIGNMENT is gone and
# nothing is set. Until 2026-09-10 that row was read as "does NOT run" and this
# lookbehind was scoped to LITERAL spans only, with every expandable span
# blanked wholesale -- and the double-quoted twin of a HARD single-quoted
# program ALLOWED (DEF-753). Re-driven with a marker written from the SECOND
# statement: `iex "<stmt>; <cmd>"` runs <cmd>; so does `iex "$env:VAR=1; <cmd>"`
# with VAR unset (`=1` is read as an unknown command name and the next
# statement runs), while VAR set to `1` is a parse error and nothing runs.
# Either way nothing is assigned and the separator after the token is live.
# So this lookbehind now serves BOTH span kinds: a literal span behind an
# opener is kept live whole; an expandable span behind an opener keeps its
# separators and blanks only the `=` bound to an interpolated token
# (`_ps_blank_expandable(reparsed=True)`), which is what keeps the DEF-617
# env-assignment rows ALLOW. (The delete records were caught inside a
# double-quoted span at the FIRST statement all along -- the exec-quote arm
# gives it a command position -- which is why the gap hid behind a first
# statement.)
#
# ⚠ TWO LIVE SPELLINGS WERE LEFT OPEN, DECLARED RATHER THAN MISSED:
#   * `iex "`$env:..."` -- the escape defeats interpolation. This is the
#     escape-obfuscation class `bench/corpus/BC-OOS-004` already scopes out.
#     Since DEF-753 the re-parsed mode blanks the escaping backtick, so this
#     spelling reads as the bare assignment it hands over and DENIES -- a side
#     effect in the right direction, not a claim on the class.
#   * `$s = @'...'@; iex $s` -- the span is not adjacent to the opener; that is
#     variable indirection, `BC-OOS-002`'s class. Still open, with its
#     expandable-span sibling (`$x = '$y'; iex "$x=<cmd>"`).
# Both are motivated bypass, not ordinary work; the shape below is the one an
# operator writes by hand.
_PS_REPARSED_SPAN_BEFORE = re.compile(
    # the SAME openers and the SAME switch run as the exec-quote arm (DEF-717):
    # a valued switch between the opener and a literal span used to read as
    # "not re-parsed", so `-Verb RunAs -ArgumentList '<write>'` was blanked
    # before any matcher saw it while the double-quoted twin was caught.
    _PS_REPARSE_OPENERS + _PS_SWITCH_RUN + r"$",
    re.IGNORECASE,
)


#: How far before a literal span the re-parse lookbehind reads. The first
#: form sliced and searched the WHOLE prefix for every literal span, so a
#: flood of literals cost the masker alone 1.6 s on a 30 KB command (the
#: DEF-712 review's here-string flood, and the quoted-executable chain row):
#: quadratic, and the masker fronts every PowerShell tier. A re-parser's
#: opener and switch run sit within a few hundred bytes of the span they
#: hand over; a literal further than this from its opener reads as a mention,
#: the friction direction, and no ordinary command carries that run.
_PS_REPARSE_LOOKBACK = 2048


def _ps_span_is_reparsed(s: str, opener: int) -> bool:
    """True when the span opening at ``opener`` is handed to a re-parser.
    Searched with ``pos``/``endpos`` (the ``$`` anchor holds at ``endpos``),
    never on a slice, and over a bounded lookback."""
    return bool(_PS_REPARSED_SPAN_BEFORE.search(s, max(0, opener - _PS_REPARSE_LOOKBACK), opener))


def _ps_expandable_is_reparsed(s: str, opener: int, a: int, b: int) -> bool:
    """`_ps_span_is_reparsed` for an EXPANDABLE span ``s[a:b]``, asked only
    when the answer can change the mask. The two modes of
    ``_ps_blank_expandable`` differ only on command-position characters and
    on escapes, so a span holding neither (an ordinary quoted argument) is
    masked identically either way and the lookback is skipped -- that lookback
    reads up to ``_PS_REPARSE_LOOKBACK`` bytes per span, and asking it for
    every double-quoted argument cost 18x on a 32 KB flood of them (review,
    measured 4.4 ms to 83 ms) on the hottest PowerShell path."""
    for k in range(a, b):
        ch = s[k]
        if ch == "`" or ch in _PS_INERTABLE_SYNTAX:
            return _ps_span_is_reparsed(s, opener)
    return False


#: Every spelling PowerShell resolves to `Remove-Item`. Single source of truth:
#: `write_guard.DANGEROUS_PS_PATTERNS` builds its records from this and
#: `_speedbump._pred_rmrf` tests against it, so an alias added here is enrolled
#: in the hard tier and the soft tier at once.
_PS_REMOVE_VERB = r"(?:Remove-Item|rmdir|erase|ri|rm|rd|del)"

#: The recurse and force switches BY EVERY SPELLING THAT RUNS (DEF-822): the
#: hard records and the soft tier spelled both in full until 2026-09-16, so
#: `ri -r -fo C:\` and `Remove-Item -rec -forc .` -- the abbreviations
#: PowerShell binds (any unambiguous prefix; no other Remove-Item parameter
#: starts with `r`, and `-fo` is the shortest unambiguous prefix of `-Force`
#: beside `-Filter`) -- drew nothing from either tier, while the two rows
#: of `TestTheDirectoryADeleteRunsIn` that read `-r -fo` as switches were
#: green. The other spelling is the native one: pwsh on macOS and Linux
#: resolves `rm` and `rmdir` to `/bin/rm` and `/bin/rmdir` (its alias table
#: is per platform -- `ri`, `del`, `rd`, `gci` and `dir` stay aliases, and
#: on Windows `rm` is `Remove-Item`), so `rm -rf ~` on the PowerShell tool
#: runs the real delete. The short cluster reads as /bin/rm reads it: the
#: letters are rm's own (`f i I r R v d P W x`), a cluster is recursive
#: when it carries `r` or `R`, and force when it carries an `f` with no `i`
#: after it (the last of `-f`/`-i` wins, so `-rfi` prompts and `-rif`
#: forces). The clusters are case-SENSITIVE inside the IGNORECASE consumers
#: (`(?-i:...)`): `I` is not `i` and `F` is not a flag. Two fragments and a
#: third for ONE cluster carrying both letters (`-rf`, `-fr`, `-rvf`), which
#: neither ordered pair can read because the second switch has no `-` of
#: its own to start at. Every consumer composes these; the readers'
#: switch tokenizer (`_ps_removal_target_tokens`) reads the same clusters
#: as switches through `_PS_RM_CLUSTER_RE`. Deterministic by construction
#: (the ReDoS rule): a leading class that excludes the pivot letter, a
#: pivot, a trailing class -- so a 30 KB cluster is one linear scan.
_PS_RECURSE_SWITCH = (
    r"(?<![\w-])(?:-r(?:e(?:c(?:u(?:r(?:s(?:e)?)?)?)?)?)?|--recursive"
    r"|(?-i:-[fvdiIPWx]*[rR][fvdiIPWxrR]*))(?![\w-])"
)
_PS_FORCE_SWITCH = (
    r"(?<![\w-])(?:-fo(?:r(?:c(?:e)?)?)?|--force"
    r"|(?-i:-[fvdiIPWxrR]*f[vdIPWxrR]*))(?![\w-])"
)
_PS_RECURSIVE_FORCE_CLUSTER = (
    r"(?<![\w-])(?-i:-(?=[fvdiIPWxrR]*[rR])(?=[fvdiIPWxrR]*f[vdIPWxrR]*(?![\w-]))"
    r"[fvdiIPWxrR]+)(?![\w-])"
)
#: The switch pair in either order, or one cluster carrying both: the tail
#: every recursive-force consumer composes after the verb.
_PS_RECURSIVE_FORCE_TAIL = (
    r"(?:" + _PS_RECURSE_SWITCH + r"[^\n;|&]{0,200}?" + _PS_FORCE_SWITCH
    + r"|" + _PS_FORCE_SWITCH + r"[^\n;|&]{0,200}?" + _PS_RECURSE_SWITCH
    + r"|" + _PS_RECURSIVE_FORCE_CLUSTER + r")"
)
#: A /bin/rm short cluster as ONE token (`-rf`, `-r`, `-f`, `-rvf`): the
#: switch tokenizer reads it as a switch that takes no value. Case-sensitive
#: as the fragments are. `-r`, `-v` and `-d` were switches already (prefixes
#: of `-Recurse`, `-Verbose`, `-Debug`); `-f`, `-i`, `-I`, `-P`, `-W` and `-x`
#: were read as value-taking -- ambiguous or unknown to Remove-Item, so no
#: working cmdlet spelling carries them -- and swallowed the operand, which
#: is how `rm -rf ~` reached no rung with a target. The GNU long forms ride
#: along (pwsh on Linux hands them to GNU rm; BSD rm has none).
_PS_RM_CLUSTER_RE = re.compile(r"-[fvdiIPWxrR]+|--(?:recursive|force)")

#: A recursive force-delete in either flag order or one cluster. Used by the
#: soft tier to ask "is this the shape the hard tier just stepped aside
#: from?" without importing write_guard (hooks load siblings flat; the
#: dependency would be circular).
_PS_RECURSIVE_FORCE_RE = re.compile(
    _PS_CMD_POS + _PS_REMOVE_VERB + r"\b" + _QUOTED_VERB_TAIL
    + r"[^\n;|&]{0,200}?" + _PS_RECURSIVE_FORCE_TAIL,
    re.IGNORECASE,
)
#: A drive-qualified PowerShell path (`C:`, `C:\x`, `c:/x`): the prefix the
#: sweep tier's judge reads by its Windows meaning on every host (DEF-842's
#: arm). The recurse switch DEF-842's readers search in one invocation's
#: argument span is `_PS_RECURSE_SWITCH_RE`, below -- the pipeline reader's,
#: reused, never through a bounded verb-to-switch span whose bound would be
#: a cliff past which the switch is not seen.
_PS_DRIVE_QUALIFIED_RE = re.compile(r"[A-Za-z]:")

# ⚠ BUILT FROM THE SHARED VERB, not a second spelling of the same concept. This
# read only the literal `Remove-Item` while the DETECTOR matched seven aliases,
# so `Remove-Item -Recurse -Force .\build; ri -Recurse -Force C:\` parsed the
# safe half, vouched for the whole command, and never looked at the drive-root
# delete in the alias statement. Two functions naming one concept differently is
# the drift this module's single-source-of-truth rule exists to prevent, and the
# comment claiming they were already shared was measured false.
_PS_REMOVE_ITEM_RE = re.compile(
    _PS_CMD_POS + _PS_REMOVE_VERB + r"\b" + _QUOTED_VERB_TAIL
    + r"(?P<args>[^\n;|&]*)", re.IGNORECASE
)
# The remove/relocate operand class on the PowerShell tool (§C52). Each reads
# a bounded argument span like `_PS_REMOVE_ITEM_RE`'s; the tokens that NAME a
# target come from `_ps_removal_target_tokens` over a quote-aware split, so
# an operand with a space is one target. `\b` after the verb keeps
# `Rename-ItemProperty` and `Remove-ItemProperty` (registry verbs) out.
_PS_RENAME_VERB = r"(?:Rename-Item|ren|rni)"
_PS_RENAME_RE = re.compile(
    _PS_CMD_POS + _PS_RENAME_VERB + r"\b" + _QUOTED_VERB_TAIL + r"(?P<args>[^\n;|&]{0,512})",
    re.IGNORECASE,
)
# A pipeline whose SINK is a remove verb: what its head enumerates goes. The
# span excludes the pipe, so the `\|` that follows it has one parse.
#: `find` joins the roster on this tool (DEF-826): GNU/BSD find runs
#: verbatim under pwsh on a POSIX host, and a find with no action piped
#: through xargs into the native rm is the same wipe; its span is read by the
#: Bash roots reader (`_ps_pipeline_reading` routes on the head word).
_PS_ENUMERATE_VERB = r"(?:Get-ChildItem|gci|ls|dir|Get-Item|gi|find)"
#: The carrier on this tool (DEF-826): `xargs` with its switch run and an
#: optional wrapper run on either side, before the remove verb -- the native
#: rm behind it reads by the DEF-825 cluster rule (`-rf` recurses).
_PS_PIPE_CARRIER = (
    r"(?P<carrier>(?:" + _CMD_POS_WRAP_RUN + r")?\bxargs\b(?!=)" + _XARGS_SWITCH_RUN
    + r"[ \t]+(?:(?:env|sudo|command|nice|nohup|busybox|doas)[ \t]+){0,3}"
    + r"""["']?\\?(?:[^\s;|&"']*/)?)"""
)
#: The remove stage behind the pipe: the carrier and then a verb from the
#: UNION of the cmdlet roster and the find arm's `-exec` roster (`unlink`,
#: `shred`, `mv` run natively behind xargs on a POSIX host -- the review drove
#: both to a false allow when only the cmdlet roster followed the carrier),
#: or the direct pipe into a cmdlet verb, the call operator admitted. The two
#: branches start on different words, so a token has one parse.
_PS_PIPE_REMOVE_STAGE = (
    r"(?:" + _PS_PIPE_CARRIER + r"(?:" + _PS_REMOVE_VERB + r"|unlink|shred|mv)\b" + _QUOTED_VERB_TAIL
    + r"|(?:&[ \t]*[\"']?)?" + _PS_REMOVE_VERB + r"\b" + _QUOTED_VERB_TAIL + r")"
)
#: An enumerator piped straight into a remove verb. Two spans (DEF-822): the
#: enumerator's, which `_ps_pipeline_roots` reads for the roots (the current
#: location when it names none -- `Get-ChildItem` defaults to `.` as GNU
#: find does, and until 2026-09-16 a rootless enumerator yielded no operand
#: to any tier) and for what narrows the walk; and the remove verb's own,
#: read for the recurse switch that makes the pipeline the whole-tree wipe
#: (`gci | ri -r -fo` wipes, driven on pwsh 7.6.5; `gci -Recurse | ri -fo`
#: aborts on the non-interactive prompt and deletes nothing). A call
#: operator and a quote may front the remove verb behind the pipe.
#: ⚠ The pipe admits a LINE BREAK after it: PowerShell continues a pipeline
#: across a newline that follows `|`, and the ordinary multi-line spelling
#: an agent emits (`gci -Recurse -File |` newline `ri`) reached no tier
#: when this stopped at `[ \t]` (the code review drove it to a wipe). The
#: two operand spans stay `[^\n;|&]`, so the change widens neither. A quote
#: fronts the remove verb only behind the call operator: `| 'ri'` emits a
#: string and invokes nothing.
#: The multi-word heads of the carrier's table (DEF-831: the version-control
#: listing) join the head position by the Bash tool's spellings
#: (`_PIPED_MULTIWORD_HEADS`): native on every host, the listing reaches
#: into the cmdlet as into the carrier -- the cmdlet binds a path from the
#: pipeline by value (driven on pwsh 7.6.5: the tracked files went, the
#: untracked one stayed).
_PS_PIPED_REMOVE_RE = re.compile(
    _PS_CMD_POS + r"(?P<head>" + _PS_ENUMERATE_VERB + r"|" + _PIPED_MULTIWORD_HEADS + r")\b" + _QUOTED_VERB_TAIL
    + r"(?P<args>[^\n;|&]{0,512})\|[ \t\r\n]*" + _PS_PIPE_REMOVE_STAGE
    + r"(?P<rmargs>[^\n;|&]{0,200})",
    re.IGNORECASE,
)
#: The cheapest witness of a sweep on this tool -- a pipe into a remove
#: verb, a .NET directory delete -- for the pre-check the classifier and the
#: speed bump run before any walk. A GATE, not a matcher: the anchored
#: readers above and `_PS_DOTNET_FILE_RE` select the operands (declared as
#: such in tests/test_speedbump_irreversible.py).
_PS_SWEEP_WITNESS_RE = re.compile(
    r"\|[ \t\r\n]*(?:&[ \t]*[\"']?)?" + _PS_REMOVE_VERB + r"\b|Directory\]::Delete[ \t]*\("
    + r"|" + _PIPED_CARRIER_WITNESS,
    re.IGNORECASE,
)
#: The recurse switch alone, compiled: the pipeline reader asks the remove
#: verb's span for it (a flag matcher over a span an anchored reader
#: selected, never a command matcher).
_PS_RECURSE_SWITCH_RE = re.compile(_PS_RECURSE_SWITCH, re.IGNORECASE)
_PS_GIT_RM_MV_RE = re.compile(
    _PS_CMD_POS + _GIT_SUBCOMMAND_AT + r"(rm|mv)[ \t]+(?P<args>[^\n;|&]{0,512})",
    re.IGNORECASE,
)
# ── the find family on the PowerShell tool (DEF-824) ──────────────────────
#: The wrapper words pwsh hands a native command through on a POSIX host
#: (`sudo find . -delete` runs find as `sudo rm` runs rm): the Bash run
#: whole, bounded -- a roster spelled for the other shell UNIONs, it never
#: replaces (memory/hook-authoring.md).
_PS_NATIVE_WRAP_RUN = r"(?:" + _CMD_POS_WRAP_RUN + r"){0,3}"
#: `find <roots...> ... -delete` on the PowerShell tool. GNU and BSD find run
#: verbatim under pwsh on macOS and Linux (no alias stands in front of them;
#: `find.exe` on Windows has no delete action), and until 2026-09-16 this
#: tool had none of the three arms the Bash tool gave the shape (DEF-815):
#: the catastrophic tier, the zone effect, the CP-RMRF nudge -- driven at
#: HEAD, `find . -delete` wiped a throwaway under pwsh 7.6.5 and the hard
#: tier answered None. Composed on `_PS_CMD_POS` as every arm on this tool
#: is (a Bash-anchored regex over PowerShell text opens a command position
#: inside a literal), the head admitting the wrapper run, an executable
#: path or a quoted verb behind the call operator (`_PS_EXE_PREFIX`, the
#: permission verbs' head); the span is the Bash arm's and
#: `_find_delete_roots` reads it, so both tools keep ONE reading of what a
#: find takes and what narrows it. IGNORECASE on the head as the Bash twin.
_PS_FIND_DELETE_RE = re.compile(
    _PS_CMD_POS + _PS_NATIVE_WRAP_RUN + _PS_EXE_PREFIX + r"\bfind\b(?!=)" + _QUOTED_VERB_TAIL
    + r"[ \t]+(?P<args>[^|;&\n]{0,512})",
    re.IGNORECASE,
)
#: The native single-file deletes pwsh runs on a POSIX host (`/bin/unlink`,
#: GNU `shred -u`): the Bash `_DESTROY_RE` verbs the PowerShell zone reader
#: lacked (failure-mode review, driven: `unlink <hook>` deleted the hook
#: while the Bash tool refused it). `rm` and `rmdir` are `_PS_REMOVE_VERB`'s.
_PS_NATIVE_DESTROY_RE = re.compile(
    _PS_CMD_POS + _PS_NATIVE_WRAP_RUN + _PS_EXE_PREFIX + r"\b(?:unlink|shred)\b(?!=)"
    + _QUOTED_VERB_TAIL + r"(?P<args>[^\n;|&]{0,512})",
    re.IGNORECASE,
)
#: `git clean` on the PowerShell head: the Bash `_GIT_CLEAN_RE` tail on
#: `_GIT_SUBCOMMAND_AT`, as the other git arms on this tool compose it, its
#: operands read by the one `_git_clean_operands` (the same review: `git
#: clean -fdx` allowed here, refused on Bash).
_PS_GIT_CLEAN_RE = re.compile(
    _PS_CMD_POS + _GIT_SUBCOMMAND_AT + r"clean\b(?P<args>[^\n;|&]{0,512})", re.IGNORECASE,
)
#: `truncate` on the PowerShell head (`/usr/bin/truncate` under pwsh on a
#: POSIX host empties a hook as surely as a write): the write extractor's
#: arm, every positional but a size or reference value a target.
_PS_TRUNCATE_RE = re.compile(
    _PS_CMD_POS + _PS_NATIVE_WRAP_RUN + _PS_EXE_PREFIX + r"\btruncate\b(?!=)"
    + _QUOTED_VERB_TAIL + r"(?P<args>[^\n;|&]{0,512})",
    re.IGNORECASE,
)
_PS_TRUNCATE_VALUED = ("-s", "--size", "-r", "--reference")


def _ps_truncate_targets(args: str) -> list[str]:
    """The files a `truncate` span writes: every positional, the value of
    `-s` / `--size` / `-r` / `--reference` dropped; a glued value (`-s0`,
    `--size=0`) is one token and drops itself."""
    out: list[str] = []
    skip = False
    for tok in _ps_operand_tokens(args):
        if skip:
            skip = False
            continue
        if tok in _PS_TRUNCATE_VALUED:
            skip = True
            continue
        if tok.startswith("-"):
            continue
        out.append(_ps_unquote(tok))
    return out
# git checkout / restore on the PowerShell tool (DEF-814's sibling, 2026-09-15):
# the write leg had no arm for the three materialise forms, so `git checkout
# -- <hook>` and `git restore <hook>` passed unquoted on that tool while the
# Bash arms refused them. The tails are the Bash arms' own, composed on the
# PowerShell head the way `_PS_GIT_RM_MV_RE` is (IGNORECASE for the head
# word and the anchor's keywords, as that sibling; the over-capture of a
# mis-cased subcommand git would reject is the fail-safe direction).
_PS_GIT_CHECKOUT_DASHDASH_RE = re.compile(
    _PS_CMD_POS + _GIT_SUBCOMMAND_AT + _GIT_CHECKOUT_DASHDASH_TAIL, re.IGNORECASE,
)
_PS_GIT_CHECKOUT_BARE_RE = re.compile(
    _PS_CMD_POS + _GIT_SUBCOMMAND_AT + _GIT_CHECKOUT_BARE_TAIL, re.IGNORECASE,
)
_PS_GIT_RESTORE_RE = re.compile(
    _PS_CMD_POS + _GIT_SUBCOMMAND_AT + _GIT_RESTORE_TAIL, re.IGNORECASE,
)
_PS_COMPRESS_ARCHIVE_RE = re.compile(
    _PS_CMD_POS + r"Compress-Archive\b" + _QUOTED_VERB_TAIL + r"(?P<args>[^\n;|&]{0,512})",
    re.IGNORECASE,
)


# PowerShell write extraction. cmdlet names and flag names are case-insensitive.
# Three shapes covered: explicit -Path / -FilePath / -LiteralPath flag, positional
# first arg (Set-Content X ...), and the `>` / `>>` redirect form (which shares
# _REDIRECT_RE with bash).
#
# ⚠ ANCHORED ON `_PS_CMD_POS`, and these two were the last write-extractors in the
# module that were not. The carve-out that excused them said PowerShell had no
# `_CMD_POS` equivalent -- true when it was written, and false from the moment
# `_PS_CMD_POS_SEP` landed. Nobody re-read the reason once the machinery existed,
# so the exemption outlived its own premise. Measured unanchored, with maintenance
# mode cleared: 4 of 4 plain MENTIONS of a protected write were refused -- a
# single-quoted string, a `#` comment and a `$doc = "..."` assignment among them,
# every one of them inert in PowerShell. Their bash siblings twenty lines up have
# carried `_CMD_POS` all along and score 0 of 4 on the same probe.
#
# Group 1 stays the path: every group inside `_PS_CMD_POS` is non-capturing, and
# ``powershell_write_targets`` reads ``m.group(1)``.
# A PowerShell backtick before a newline is a LINE CONTINUATION. Every path
# matcher below is bounded by a class that stops at the newline, and the bare
# operand arm read the lone backtick as an operand, so `Set-Content -Path` +
# backtick-newline + `<hook>` -- and the Out-File, New-Item and Copy-Item
# spellings -- all ALLOWED while the plain-newline spelling denied (driven by
# the DEF-638 failure-mode pass; DEF-694). Joined into a single space AFTER
# masking: inside a string a backtick is an escape, not a continuation, and the
# masker has already blanked what a string holds, so a continuation seen here
# is a live one. The one span kind that keeps its newlines -- an expandable
# span handed to a re-parser (DEF-753) -- has every escaping backtick blanked
# by the masker for exactly this reason: a surviving backtick before a kept or
# written newline would let this join swallow a live statement boundary
# (review, driven). Bash's twin is `splice_line_continuations`, with its own
# CRLF caveat; PowerShell's continuation is the backtick, so CR is simply
# optional.
_PS_BACKTICK_CONTINUATION_RE = re.compile(r"`[ \t]*\r?\n[ \t]*")


# ── the call operator on a COMMAND OBJECT (DEF-827) ─────────────────────────
#: `& (Get-Command find) . -delete`, `& (gcm ri) -Recurse -Force .`, the
#: dot-source operator, `-Name` or `-CommandType Application` on either side
#: of the verb, a quoted verb, a doubled paren, a call operator inside the
#: sub-expression, the object's `.Source`, `[0]` or `.Source.ToString()`
#: (a member or index run): the idiomatic PowerShell call on a command it
#: discovered.
#: Driven on pwsh 7.6.5 2026-09-16, each wiped a throwaway, and every head on
#: this tool answered nothing, because the sub-expression's paren opens a
#: command position for `Get-Command`, never for the verb. Resolved ONCE, on
#: the scan half of `powershell_scan_pair` (`_resolve_ps_command_objects`):
#: the position before the operator is kept verbatim, the verb keeps its
#: offset, every other character of the spelling is blanked in BOTH texts of
#: the pair at the offsets the scan matched, same length -- so every head
#: anchored on `_PS_CMD_POS` reads the verb at the position the operator's
#: own statement opened (`^`, a separator, `=`, a re-parser's quote), and a
#: span read from the raw twin by offset lands on the operands, never on the
#: sub-expression's close paren (the first cut resolved the scan alone, and
#: the pipeline reader, whose operands begin at the blank after the verb,
#: read the `)` as one). The row proposed an arm on `_PS_EXE_PREFIX`; that serves the
#: native-verb heads only and leaves the cmdlet heads open (`& (gcm ri)`).
#: The operator is admitted only at a command position -- `_PS_CMD_POS`
#: itself, never a restatement of its class (the census's SELF-ANCHORED
#: hazard): a `.` operand before a sub-expression argument (`gci .
#: (Get-Command x)`) is not the dot operator, a mention's `&` is already
#: blanked by the masker, and a re-parser's quote (`iex "& (gcm find) ..."`)
#: opens the position through the exec-quote arm. The verb's quotes are
#: paired (a backreference), the member run is consumed whole (one member
#: read alone left `[0]` and `.ToString()` as phantom roots, and `& (gcm
#: ri)[0] -Recurse -Force build` -- an ordinary build clean -- drew the wall
#: maintenance mode cannot bypass; failure-mode review, driven). Every
#: adjacent quantifier pair is mutually exclusive; the switch runs are
#: bounded; the repeated-head rows are in tests/test_redos.py. Declared
#: limits, each a DECLARED matrix row: the object held in a VARIABLE (`$f =
#: Get-Command find; & $f`, a variable-tracking pass the guard does not
#: have -- also the rehearsal's `sweep-find-command-variable` gap), a
#: pipeline inside the sub-expression (`(Get-Command find | Select-Object
#: -First 1)`), and a discovery that is not `Get-Command` (`(Get-Item
#: /usr/bin/find)`, a `[System.IO.FileInfo]` literal).
_PS_COMMAND_OBJECT_SWITCH_RUN = r"(?:[ \t]+-\w+(?:[ \t]+[\w.]+)?){0,3}"
_PS_COMMAND_OBJECT_HEAD_RE = re.compile(
    "(?P<pos>" + _PS_CMD_POS + r")[&.][ \t]*\({1,2}[ \t]*(?:&[ \t]*)?"
    r"[\"']?(?:Get-Command|gcm)[\"']?" + _PS_COMMAND_OBJECT_SWITCH_RUN
    + r"[ \t]+(?P<vq>[\"']?)(?P<verb>" + _DISCOVERED_VERB + r")(?P=vq)"
    + _PS_COMMAND_OBJECT_SWITCH_RUN
    + r"[ \t]*\)(?:\.\w{1,32}(?:\(\))?|\[[^\]\n]{0,16}\]){0,4}[ \t]*\)?",
    re.IGNORECASE,
)


def _blank_where_changed(other: str, before: str, after: str) -> str:
    """``other`` with a blank at every offset where ``after`` blanked
    ``before`` -- the same-length twin of a rewrite, edited at the same
    offsets and nowhere else."""
    return "".join(
        " " if b != a else o for o, b, a in zip(other, before, after)
    )


def _resolve_ps_command_objects(raw: str, scan: str) -> tuple[str, str]:
    """The pair with every call on a command object read as the command it
    names (DEF-827): matched on ``scan`` (a mention's operator is already
    blanked there), the verb kept at its offset, the operator, the
    sub-expression and the member run blanked in BOTH texts at the offsets
    the scan matched -- a span read from the raw twin by offset must not
    meet the sub-expression's close paren (the pipeline reader's operands
    begin at the blank after the verb, and a `)` there is an operand). Same
    length; the operands' own characters are untouched. A pair whose halves
    differ in length (cannot happen: both are built by one index loop over
    a length-keeping masker) is returned unresolved -- never the scan
    resolved and the raw not, which is the half-state the first cut shipped."""
    lowered = scan.lower()
    if "get-command" not in lowered and "gcm" not in lowered:
        return raw, scan
    if len(raw) != len(scan):
        return raw, scan
    resolved = _PS_COMMAND_OBJECT_HEAD_RE.sub(_keep_the_verb, scan)
    if resolved == scan:
        return raw, scan
    return _blank_where_changed(raw, scan, resolved), resolved


def powershell_scan_pair(command: str) -> tuple[str, str]:
    """``(raw, scan)`` for the PowerShell leg: the raw command and its scan
    text, the SAME LENGTH, so a consumer can find an opener on ``scan`` and
    read the body at the same offsets in ``raw`` (the two-string discipline
    the Bash interpreter arms carry -- DEF-698, DEF-704 -- brought to this
    leg by DEF-712). Both halves then have every call on a command object
    resolved to the command it names (`_resolve_ps_command_objects`,
    DEF-827): matched on the scan, blanked in both at the same offsets, the
    verb at its offset -- same length still.

    The masker keeps length. The backtick-continuation join does not: it
    replaces a backtick, optional blanks and a newline with ONE space. So the
    join is found on the MASKED text -- inside a string the masker has either
    blanked the newline or, in a re-parsed expandable span, blanked the
    backtick (DEF-753), so a backtick that survives masking is never inside a
    string -- and the same span is replaced in BOTH strings, which keeps them
    aligned.
    ``powershell_scan_text`` is the masked half of this pair, byte-for-byte
    what it always returned (pinned).
    """
    masked = mask_powershell_inert_syntax(command)
    if len(masked) != len(command):
        # Cannot happen (the masker returns the command or a same-length
        # transform), but a consumer reading offsets across a length
        # mismatch would slice the wrong bytes, and the friction direction
        # is to scan the raw command.
        masked = command
    raw_parts: list[str] = []
    scan_parts: list[str] = []
    last = 0
    for m in _PS_BACKTICK_CONTINUATION_RE.finditer(masked):
        raw_parts.append(command[last:m.start()])
        scan_parts.append(masked[last:m.start()])
        raw_parts.append(" ")
        scan_parts.append(" ")
        last = m.end()
    raw_parts.append(command[last:])
    scan_parts.append(masked[last:])
    return _resolve_ps_command_objects("".join(raw_parts), "".join(scan_parts))


def powershell_scan_text(command: str) -> str:
    """The ONE text every PowerShell consumer scans: `mask_powershell_inert_syntax`,
    then backtick line-continuations joined into a single space.

    Every entry point reads this -- the write leg (`_candidate_paths_from_powershell`),
    the allowlist-blind symlink leg (`powershell_symlink_linknames`, which read the
    RAW command until now), the hard-deny tier (`write_guard.check_powershell`) and
    the speed bump's PowerShell arm (`_speedbump._pred_rmrf`). The join landed on
    the write leg alone first, and the failure-mode pass drove BC-048's canonical
    forge (`New-Item -ItemType SymbolicLink -Path` + backtick-newline +
    `cc/blueprints/latest.json`) and `Remove-Item -Recurse` + backtick-newline +
    `-Force /` straight past the other three -- the write leg could not backstop
    the forge because `cc/blueprints/` is legitimately writable there.

    ⚠ The join SHORTENS the string. The masker's same-length, same-offset
    contract does not survive it, so nothing downstream may report an offset into
    this text against the raw command; every consumer reads slices of THIS text
    -- except the interpreter arm, which reads `powershell_scan_pair` and gets
    a raw twin joined at the same offsets.
    """
    return powershell_scan_pair(command)[1]

# `Clear-Content` truncates: a write with no value (driven ALLOW at HEAD on
# the PowerShell tool while `Set-Content <hook> ''` denied; §C52's sibling).
_PS_PATH_FLAG_RE = re.compile(
    _PS_CMD_POS + r"\b(?:Set-Content|Out-File|Add-Content|Tee-Object|New-Item|Clear-Content)\b"
    + _QUOTED_VERB_TAIL
    # {0,512}: verb-regex class bound (see _SED_INPLACE_RE comment).
    + r"[^|;&\n]{0,512}?-(?:Path|FilePath|LiteralPath)\s+([^\s|;&]+)",
    re.IGNORECASE,
)
_PS_POSITIONAL_RE = re.compile(
    _PS_CMD_POS + r"\b(?:Set-Content|Out-File|Add-Content|Clear-Content)" + _QUOTED_VERB_TAIL
    + r"\s+(?!-)([^\s|;&]+)",
    re.IGNORECASE,
)

# Copy-Item / Move-Item, and the cpi/copy/cp and mi/move/mv aliases PowerShell
# defines for them: the idiomatic copy and move had no protected-zone matcher
# while Set-Content on the same path did (DEF-638; driven at HEAD:
# `Copy-Item -Destination .claude/settings.json` and
# `Move-Item -Destination tools/cc/hooks/x.py` ALLOWED). Two shapes, both
# anchored on `_PS_CMD_POS` like the write verbs above: the `-Destination` flag
# anywhere in the argument span, and the positional pair `VERB [switches] src
# dst`. In the positional form a run of switch tokens is skipped (`-Recurse`,
# `-Force`, a bare `-Path` before its value); a VALUE-taking switch before the
# pair (`-Filter *.py src dst`) reads its value as the source and misses -- a
# documented limit, and the `-Destination` spelling is the covered one. A
# directory destination lands `basename(src)` inside it; the caller computes
# that from the (src, dst) pair, as the bash cp/mv twin does. Case-insensitive
# like every PowerShell matcher. Group 1 of the -Destination form is the path.
# `(?![-\w])`: the verb must END there -- `move`/`copy` + `\b` alone matched the
# first hyphen-segment of `Move-ItemProperty` / `Copy-ItemProperty` (registry
# cmdlets whose -Destination is not a file), and the -Destination leg needs no
# whitespace after the verb, so those denied (failure-mode pass, driven).
#: `verb` is a named group (§C52): the remove/relocate reader keeps a move's
#: SOURCE and skips a copy's. The operand groups that follow it in the two
#: regexes below are numbered from 2.
_PS_COPY_MOVE_VERB = r"(?P<verb>Copy-Item|Move-Item|cpi|copy|cp|mi|move|mv)(?![-\w])"
_PS_MOVE_VERB_NAMES = frozenset({"move-item", "mi", "move", "mv"})
# One operand: a double- or single-quoted span (a Windows path with a space is
# ONE argument -- `Move-Item "my file.txt" <hook>` split into two fake
# positionals and missed; review, driven live) or a bare token.
_PS_OPERAND = r"(?:\"[^\"]*\"|'[^']*'|[^\s|;&\"']+)"
# PowerShell binds any UNAMBIGUOUS parameter-name prefix and accepts `-Name:value`
# as well as `-Name value`. `-Des` is the shortest unambiguous prefix of
# `-Destination` (`-De` collides with the common `-Debug`); written out longest
# first, literally, so the ReDoS gate can reconstruct the pattern statically.
_PS_DESTINATION_FLAG = (
    r"-(?:Destination|Destinatio|Destinati|Destinat|Destina|Destin|Desti|Dest|Des)"
    r":?\s*"
)
_PS_COPY_MOVE_DEST_RE = re.compile(
    _PS_CMD_POS + r"\b" + _PS_COPY_MOVE_VERB + r"\b" + _QUOTED_VERB_TAIL
    # {0,512}: verb-regex class bound (see _SED_INPLACE_RE comment).
    # `pre`: what sits between the verb and the flag -- a positional source
    # or a `-Path` source the remove/relocate reader classifies; the
    # destination is group 3.
    + r"(?P<pre>[^|;&\n]{0,512}?)" + _PS_DESTINATION_FLAG + r"(" + _PS_OPERAND + r")",
    re.IGNORECASE,
)
# Positional pair: a run of switch tokens may sit before the source AND between
# the source and the destination (`Copy-Item src -Force dst` is ordinary
# PowerShell). A VALUE-taking switch in either run (`-Filter *.py`) reads its
# value as an operand and the pair misses -- the documented limit; the
# `-Destination` spelling is the covered one.
_PS_COPY_MOVE_POSITIONAL_RE = re.compile(
    _PS_CMD_POS + r"\b" + _PS_COPY_MOVE_VERB + r"\b" + _QUOTED_VERB_TAIL + r"\s+"
    r"(?:-\w+\s+)*(?!-)(" + _PS_OPERAND + r")\s+"
    r"(?:-\w+\s+)*(?!-)(" + _PS_OPERAND + r")",
    re.IGNORECASE,
)
# The source of a `-Destination <dir>` copy, read from the whole statement
# segment so the landed file can be computed (`Copy-Item -Path settings.json
# -Destination .claude/` lands `.claude/settings.json`; the directory alone is
# not protected, the landed file is). `-Pat` is the shortest unambiguous prefix
# of `-Path` (`-Pa` collides with `-PassThru`); `-L` already resolves to
# `-LiteralPath`. Driven red before this existed.
_PS_COPY_MOVE_SRC_FLAG_RE = re.compile(
    r"-(?:Path|Pat|LiteralPath|LiteralPat|LiteralPa|LiteralP|Literal|Litera"
    r"|Liter|Lite|Lit|Li|L):?\s*(" + _PS_OPERAND + r")",
    re.IGNORECASE,
)


def _ps_landed_path(src: str, dst: str) -> str | None:
    """``Copy-Item x .claude\\`` lands ``x`` INSIDE the directory: return
    ``<dst><basename(src)>`` when ``dst`` ends with a separator, else None."""
    if not dst.endswith(("/", "\\")):
        return None
    base = src.strip().strip('"').strip("'").replace("\\", "/").rsplit("/", 1)[-1]
    return dst + base if base else None


# icacls / cacls / takeown / attrib / Set-Acl / Set-ItemProperty: the Windows
# twins of the chmod line (`_CHMOD_CHOWN_RE`). A permission, ownership,
# attribute or ACL change on a hook silences it without writing it --
# `attrib +R <hook>` and `icacls <hook> /deny Everyone:(R)` are the spellings a
# Windows agent reaches for -- and every one of them ALLOWED on the PowerShell
# tool while `chmod 000 <hook>` denied on Bash and `Set-Content <hook>` denied
# on this very leg (DEF-697; driven at HEAD, filed by the DEF-695 failure-mode
# pass; `takeown`, the `chown` twin, and `cacls`, the deprecated `icacls`,
# were the review round's sister sites). Anchored on `_PS_CMD_POS` like every
# PowerShell matcher. Group 1 is the VERB and group 2 the argument span, the
# `_CHMOD_CHOWN_RE` shape, because the verbs do not share a grammar and
# `_ps_permission_targets` dispatches on the verb through
# `_PS_PERMISSION_RULES`:
#   - `icacls PATH /grant|/deny|/remove|/setowner|/reset|/inheritance|...`
#     (and `cacls PATH /G|/P|/R|/D ...`) is path-FIRST and slash-switched.
#     `icacls PATH` alone DISPLAYS the ACL (a read, like `Get-Acl`), so a
#     target is yielded only under a switch that is not on the READ list
#     (`_ICACLS_READ_SWITCHES`) -- an allow-list of reads, never a list of
#     writes, so a switch nobody here has heard of is a write; `/save FILE`
#     reads the ACL but writes FILE, so that value is yielded.
#   - `attrib [+X|-X ...] PATH [/S /D]` names its attributes as `+`/`-` tokens
#     in either order around the path. `attrib PATH` alone displays (a read),
#     so a target is yielded only when an attribute token is present.
#   - `takeown /f PATH [/r /d y]` is always a write; every operand that is not
#     a slash switch is a candidate.
#   - `cipher /e|/d [/s:DIR] PATH...` encrypts or decrypts under EFS: every
#     operand that is not a slash switch, plus the `/s:` tree, is a candidate
#     under `/e` or `/d`; a bare `cipher PATH` displays the state (a read) and
#     the key-management switches name no path. Directory-scoped on the walk
#     host (W2-16), so the directory operand is what lands (DEF-730).
#   - `Set-Acl [-Path] PATH [-AclObject] ACL` and `Set-ItemProperty [-Path]
#     PATH [-Name] NAME [-Value] VALUE` (alias `sp`) are always writes: every
#     operand that is not a `-` switch is a candidate (the ACL object, the
#     property name and its value read as operands too, harmlessly -- none is
#     ever a protected path), and a colon-bound `-Path:PATH` yields PATH.
# Over-yield is the fail-safe direction (`_positional_operands`); what this
# rule must never do is read a WRITE as a read, which is why the two
# display-form exemptions key on switches and attributes the tokenizer has
# ALREADY unquoted (`attrib "+R" <hook>` and `icacls <hook> "/deny" ...` walked
# past the first cut, which unquoted only at the yield -- both reviews, driven;
# the bash twin strips at tokenize time and never had the gap). A trailing `#`
# comment's words are not operands: the masker keeps a comment's text (it
# blanks separators only), and the bash twin was driven denying `chmod 644
# README.md # never chmod 000 <hook>` before its span learned to stop there.
# `(?![-\w])`: the verb must END there, so `sp` does not match `split` and
# `Set-Acl` does not match a longer cmdlet name; `(?:\.exe)?` takes the
# explicit executable spelling of the Win32 tools.
# The property-assignment form `(Get-Item <hook>).IsReadOnly = $true` is NOT
# a limit any more (DEF-733): it sat here as "no cmdlet to anchor on" while
# its sanctioned undo, `attrib -R <hook>`, was a rostered verb and denied --
# so a session could set read-only on the enforcement file THROUGH the guard
# and then find the documented undo blocked, with a maintenance-mode relaunch
# the only exit (walk 2, W2-14, driven on the host). There is an anchor: `(`
# is a command position and `Get-Item` sits at it. `_PS_ITEM_PROPERTY_ASSIGN_RE`
# covers the form in BOTH directions (a clearing assignment is no less a
# change of the file, exactly as `attrib -R` is), so the state cannot be
# entered through the guard and the trap cannot arise from it; a read of the
# property and the `-eq` comparison stay reads. The exit for a file made
# read-only OUTSIDE the guard is the one every protected-zone deny already
# names: exit and relaunch with the maintenance-mode variable set. The .NET
# static file API (`[IO.File]::SetAttributes`, `::WriteAllText`, `::Copy`,
# `::Delete` and the rest -- driven ALLOWING on the walk host, W2-13) is
# `_PS_DOTNET_FILE_RE` (DEF-730).
# Documented limits, shared with the copy/move twin: a computed or piped path
# (`Get-Item <hook> | Set-Acl`, `-InputObject (Get-Item <hook>)`), the item
# held in a variable (`$f = Get-Item <hook>; $f.IsReadOnly = $true` -- the
# indirection class BC-OOS-002) and an UNBOUND variable holding the path -- a
# literal binding is inlined first since DEF-801 (an executable given by path,
# quoted or bare, is matched through `_PS_EXE_PREFIX` since DEF-712 -- and,
# since DEF-753, behind an EXPANDABLE wrapper span too: `powershell -Command
# "& 'C:\...\icacls.exe' <hook> /deny ..."` keeps its call operator live
# because the masker no longer blanks a re-parsed expandable span, so the
# quoted arm sees the `&` it keys on; both wrapper twins deny, pinned); and the
# Bash tool's Git Bash twin (`attrib`/`icacls` are reachable from MSYS bash on
# Windows) is not matched -- an agent in a bash shell types `chmod`, which is,
# and the two heads need a `_HEAD_ARGS` row only a Windows bash can vouch for.
_PS_PERMISSION_VERB = (
    r"(icacls(?:\.exe)?|cacls(?:\.exe)?|takeown(?:\.exe)?|attrib(?:\.exe)?"
    r"|cipher(?:\.exe)?|Set-Acl|Set-ItemProperty|sp)(?![-\w])"
)
_PS_PERMISSION_RE = re.compile(
    # `_PS_EXE_PREFIX`, not `\b`: the head may end a quoted or bare path
    # (`& "C:\Windows\System32\icacls.exe" <hook> /deny ...`), the limit
    # DEF-697 declared and the DEF-712 lane closed; the optional quote after
    # the verb closes the one the prefix opened, so the span starts clean.
    _PS_CMD_POS + _PS_EXE_PREFIX + _PS_PERMISSION_VERB + _QUOTED_VERB_TAIL
    # {0,512}: verb-regex class bound (see _SED_INPLACE_RE comment).
    + r"([^|;&\n]{0,512})",
    re.IGNORECASE,
)
#: One PowerShell operand at a time out of a span an anchored matcher already
#: selected -- `_PS_OPERAND` compiled. The bash `_operands` tokenizer is NOT
#: reusable here: it reads a backslash as an escape, and a PowerShell path IS
#: backslashes (`tools\cc\hooks\x.py` would read as `toolscchooksx.py`, the
#: posix-lexer-on-PowerShell fail-open memory/a-class-one-fix-is-a-claim.md
#: records).
_PS_OPERAND_RE = re.compile(_PS_OPERAND)
#: icacls / cacls switches that only READ, compared on the part before any
#: `:`. A bare `icacls PATH` displays, and so does one carrying only these.
#: Every OTHER switch is a write: the set is an allow-list of reads on purpose,
#: so a switch this table has never heard of -- `/substitute`, driven ALLOWING
#: under the list of writes it replaced (failure-mode pass), and the next one
#: Microsoft adds -- is a write until someone declares it a read. `/save`
#: reads the ACL but WRITES the file it names, yielded apart.
_ICACLS_READ_SWITCHES = frozenset({
    "/save", "/verify", "/findsid", "/t", "/c", "/l", "/q", "/?", "/help",
})
#: The operand rule per head, keyed by the lower-cased verb without `.exe`.
#: Pinned against `_PS_PERMISSION_VERB` and the anchor census's verb roster in
#: BOTH directions (`tests/test_speedbump_irreversible.py`): a verb added to
#: the alternation without a row here would otherwise take the widest rule
#: silently -- fail-safe for a write verb, a false-positive source for a read
#: one -- and a row without its verb would never fire.
_PS_PERMISSION_RULES: dict[str, str] = {
    "icacls": "acl-switch",
    "cacls": "acl-switch",
    "attrib": "attribute",
    "takeown": "slash-switched-write",
    "cipher": "cipher",
    "set-acl": "cmdlet",
    "set-itemproperty": "cmdlet",
    "sp": "cmdlet",
}


def _ps_unquote(token: str) -> str:
    return token.strip('"').strip("'")


def _ps_is_slash_switch(token: str) -> bool:
    """A `/`-led token with no further `/` is a Win32 switch (`/deny`,
    `/inheritance:r`); one with more is a POSIX-style absolute path, which
    pwsh on macOS or Linux does hand these tools (review, driven: the icacls
    and attrib branches dropped it as a switch while `Set-Acl -Path` on the
    same path denied)."""
    return token.startswith("/") and "/" not in token[1:]


def _ps_permission_operands(span: str) -> list[str]:
    """Quote-aware operands of a span, quotes stripped AT COLLECTION so the
    classifiers in `_ps_permission_targets` see `+R` and `/deny` whether or
    not they were quoted; a bare `#` token starts a trailing comment and ends
    the operands. A quoted span holding whitespace is ALSO split and its
    parts appended, because that is the whole argument list of
    `Start-Process icacls -ArgumentList "<hook> /deny ..."` -- the elevation
    idiom, `-Verb RunAs` being Windows's `sudo`, whose payload carries no verb
    of its own for the re-parse anchor to catch (review, driven); the whole
    token stays a candidate too, so `attrib +R "my file.py"` keeps its one
    target."""
    out: list[str] = []
    for tok in _PS_OPERAND_RE.findall(span):
        if tok.startswith("#"):
            break
        bare = _ps_unquote(tok)
        out.append(bare)
        if tok != bare and any(c.isspace() for c in bare):
            out.extend(_ps_unquote(t) for t in _PS_OPERAND_RE.findall(bare))
    return out


def _ps_permission_targets(span: str, verb: str) -> list[str]:
    """The paths a PowerShell permission-verb argument span acts on, by the
    per-head rule `_PS_PERMISSION_RULES` names (the `_PS_PERMISSION_RE`
    comment states each); ``[]`` for the two display (read) forms. A head the
    table does not know takes the widest rule, the fail-safe direction."""
    tokens = _ps_permission_operands(span)
    head = verb.lower()
    if head.endswith(".exe"):
        head = head[:-4]
    rule = _PS_PERMISSION_RULES.get(head, "cmdlet")
    if rule == "acl-switch":
        switches = {
            t.lower().split(":", 1)[0] for t in tokens if _ps_is_slash_switch(t)
        }
        out: list[str] = []
        if switches - _ICACLS_READ_SWITCHES:
            out.extend(t for t in tokens if not _ps_is_slash_switch(t))
        for i, t in enumerate(tokens[:-1]):
            if t.lower() == "/save":
                out.append(tokens[i + 1])
        return out
    if rule == "attribute":
        if not any(t[:1] in "+-" and len(t) > 1 for t in tokens):
            return []
        return [t for t in tokens if t[:1] not in "+-" and not _ps_is_slash_switch(t)]
    if rule == "slash-switched-write":
        return [t for t in tokens if not _ps_is_slash_switch(t)]
    if rule == "cipher":
        # `/s:DIR` carries a path and so is not a switch to the tokenizer's
        # one-slash rule; read it apart before the switch census.
        trees = [t.split(":", 1)[1] for t in tokens if t.lower().startswith("/s:")]
        rest = [t for t in tokens if not t.lower().startswith("/s:")]
        switches = {t.lower().split(":", 1)[0] for t in rest if _ps_is_slash_switch(t)}
        if not switches & {"/e", "/d"}:
            return []
        return trees + [t for t in rest if not _ps_is_slash_switch(t)]
    out = []
    for t in tokens:
        if t.startswith("-"):
            if ":" in t:
                out.append(t.split(":", 1)[1])
            continue
        out.append(t)
    return out


# The property-assignment permission form (DEF-733, §C49): `(Get-Item <hook>)
# .IsReadOnly = $true` and the `Attributes` twin, either direction, `=` or the
# compound assignments. `(` is a command position, so the cmdlet is anchored;
# the operand span runs to the closing paren and takes the cmdlet operand rule
# (`-Path` / `-LiteralPath` / colon-bound / positional). A read of the property
# has no `=`, and `-eq` has none either (PowerShell has no `==`; a reader who
# writes one has a syntax error, and matching it costs nothing). Bounded
# span, one parse. No `(?!=)` guard here on purpose: that text is the Bash
# verb regexes' "not an assignment" marker and a derivation scrapes for it.
_PS_ITEM_PROPERTY_ASSIGN_RE = re.compile(
    _PS_CMD_POS
    + r"(?:Get-Item|gi|Get-ChildItem|gci|ls|dir)(?![-\w])" + _QUOTED_VERB_TAIL
    + r"([^()\n]{0,256})\)"
    + r"[ \t]*\.[ \t]*(?:IsReadOnly|Attributes)[ \t]*[-+]?=",
    re.IGNORECASE,
)

# The .NET static file API (DEF-730, §C49): `[System.IO.File]::SetAttributes`
# and `cipher` were driven ALLOWING on the walk host against a hook path while
# `attrib +R` denied in the same run (W2-13), and the write family beside
# SetAttributes -- `WriteAllText`, `AppendAllText`, `Copy`, `Move`, `Delete`,
# `Create`, `Encrypt` -- had never been asked and had zero coverage. One
# matcher, anchored on the command position, matched on the scan text: the
# method name and the argument span up to the first paren. The rule keys on
# a READ allow-list (`_PS_DOTNET_FILE_READS`): every other method yields its
# first quoted argument, except `Copy` / `Move` / `Replace`, which yield the
# DESTINATION (the second; `Replace` writes its backup path, the third, as
# well) -- the source is what is read, exactly as the `Copy-Item` /
# `Move-Item` twin reads it -- so a method this table has never heard of is a
# write until someone declares it a read, the `icacls` switch rule's
# discipline. Declared limits, pinned: the `[IO.FileInfo]` / `[IO.DirectoryInfo]`
# object spelling (`::new(<path>).Delete()`; a bare `::new` is a read, so it
# needs its own matcher -- its own row), a call whose arguments continue on
# the next line, a comma inside the path literal, and, as everywhere here,
# a path held in an UNBOUND variable (a literal binding is inlined
# first since DEF-801) or built by an expression (the indirection
# class), and a stream opened through `New-Object`. `\w{1,64}` then `[ \t]*`
# then the literal paren: every adjacent pair exclusive, bounded span.
_PS_DOTNET_FILE_RE = re.compile(
    _PS_CMD_POS
    + r"\[(?:System\.)?IO\.(?:File|Directory)\]::(\w{1,64})[ \t]*\(([^()\n]{0,512})",
    re.IGNORECASE,
)
_PS_DOTNET_FILE_READS = frozenset({
    "exists", "readalltext", "readalllines", "readallbytes", "readlines",
    "readalltextasync", "readalllinesasync", "readallbytesasync",
    "openread", "opentext", "getattributes", "getaccesscontrol",
    "getcreationtime", "getcreationtimeutc", "getlastwritetime",
    "getlastwritetimeutc", "getlastaccesstime", "getlastaccesstimeutc",
    "getfiles", "getdirectories", "getfilesystementries", "enumeratefiles",
    "enumeratedirectories", "enumeratefilesystementries", "getparent",
    "getdirectoryroot", "getcurrentdirectory", "getlogicaldrives",
})
#: Method -> the argument indices it writes; every other write method writes
#: its first argument. `Replace(source, destination, backup)` writes two.
_PS_DOTNET_WRITE_ARGS: dict[str, tuple[int, ...]] = {
    "copy": (1,), "move": (1,), "replace": (1, 2),
}

# The OBJECT spelling of the same API (DEF-746, §C49): `[IO.FileInfo]::new(
# <path>).Delete()`, `[System.IO.DirectoryInfo]::new(<path>).Delete($true)`,
# the cast twin `([IO.FileInfo]'<path>').Delete()`, and the property
# assignment `([IO.FileInfo]'<path>').IsReadOnly = $true` (DEF-733's
# `Get-Item` form, built from the type instead). Driven 2026-09-09 by the
# C49 failure-mode review and re-measured 2026-09-13: every one ALLOWED
# beside the denied static spelling, because the static matcher keys on
# `[IO.File]` / `[IO.Directory]` and a bare `::new(<path>)` constructs an
# object, which is a READ -- the write is the METHOD chained after the
# constructor, so the object spelling needs its own matcher rather than a
# token in the static alternation. The cast form is matched only inside
# parentheses: without them PowerShell binds the method to the string, not
# the object, and nothing runs. Same discipline as the static matcher: a
# read allow-list, everything else writes the constructed path; `CopyTo`
# reads it and writes its destination, `MoveTo` and `Replace` write both. A
# property with no call (`.Exists`, `.Length`) is a read by shape. Two
# patterns rather than one alternation so the groups stay fixed: (1) quote,
# (2) path, (3) method, (4) argument span. Every adjacent pair exclusive: a
# quote then a run that excludes quotes, a literal paren then a dot, and the
# optional wrapping paren is bound to its own whitespace run.
_PS_DOTNET_INFO_TYPE = r"\[(?:System\.)?IO\.(?:File|Directory)Info\]"
_PS_DOTNET_INFO_NEW_RE = re.compile(
    _PS_CMD_POS + r"\(?" + _PS_DOTNET_INFO_TYPE
    + r"::new[ \t]*\([ \t]*(['\"])([^'\"\n]{1,512})\1[ \t]*\)\)?"
    + r"\.(\w{1,64})[ \t]*\(([^()\n]{0,512})",
    re.IGNORECASE,
)
_PS_DOTNET_INFO_CAST_RE = re.compile(
    _PS_CMD_POS + r"\(" + _PS_DOTNET_INFO_TYPE
    + r"[ \t]*(['\"])([^'\"\n]{1,512})\1[ \t]*\)"
    + r"\.(\w{1,64})[ \t]*\(([^()\n]{0,512})",
    re.IGNORECASE,
)
#: `[IO.FileInfo]::new('<path>').IsReadOnly = $true` (parens optional: the
#: setter binds to the constructed object without them -- driven in pwsh
#: 7.6.5 by the failure-mode review) and the cast twin
#: `([IO.FileInfo]'<path>').IsReadOnly = $true` (parens required, as above)
#: -- the attribute write `_PS_ITEM_PROPERTY_ASSIGN_RE` catches on a
#: `Get-Item` object, built from the type instead. Groups: (2) the
#: constructor's path, (4) the cast's. The `=` is spelled as that sibling
#: spells it (`[-+]?=`, no `(?!=)` guard: that text is the Bash verb regexes'
#: "not an assignment" marker and a derivation scrapes for it; PowerShell
#: has no `==`, and `-eq` carries no `=`).
_PS_DOTNET_INFO_ATTR_ASSIGN_RE = re.compile(
    _PS_CMD_POS
    + r"(?:\(?" + _PS_DOTNET_INFO_TYPE
    + r"::new[ \t]*\([ \t]*(['\"])([^'\"\n]{1,512})\1[ \t]*\)\)?"
    + r"|\(" + _PS_DOTNET_INFO_TYPE
    + r"[ \t]*(['\"])([^'\"\n]{1,512})\3[ \t]*\))"
    + r"\.(?:IsReadOnly|Attributes)[ \t]*[-+]?=",
    re.IGNORECASE,
)
_PS_DOTNET_INFO_READS = frozenset({
    "refresh", "tostring", "gettype", "equals", "gethashcode", "getobjectdata",
    "openread", "opentext", "getaccesscontrol",
    "getfiles", "getdirectories", "getfilesysteminfos",
    "enumeratefiles", "enumeratedirectories", "enumeratefilesysteminfos",
})
#: Instance method -> the argument indices it writes beside the constructed
#: path (`MoveTo`, `Replace`) or instead of it (`CopyTo` reads the object).
_PS_DOTNET_INFO_DEST_ARGS: dict[str, tuple[int, ...]] = {
    "copyto": (0,), "moveto": (0,), "replace": (0, 1),
}
_PS_DOTNET_INFO_SELF_IS_READ = frozenset({"copyto"})


def _ps_dotnet_info_targets(method: str, path: str, span: str) -> list[str]:
    """The paths a `[IO.FileInfo]::new(<path>).<method>(...)` call (or its
    cast twin) writes: the constructed path unless the method only reads the
    object, plus the quoted destination (and backup) for the methods that
    name one; a read method yields nothing."""
    name = method.lower()
    if name in _PS_DOTNET_INFO_READS:
        return []
    out: list[str] = [] if name in _PS_DOTNET_INFO_SELF_IS_READ else [path]
    args = [a.strip() for a in span.split(",")]
    for index in _PS_DOTNET_INFO_DEST_ARGS.get(name, ()):
        if len(args) <= index:
            continue
        arg = args[index]
        if len(arg) >= 2 and arg[0] in "'\"" and arg[-1] == arg[0]:
            out.append(arg[1:-1])
    return out


def _ps_dotnet_file_targets(method: str, span: str) -> list[str]:
    """The paths a `[IO.File]::<method>(...)` call writes: the first quoted
    argument, or the destination (and backup) for the methods that name
    one; a read method, or an argument that is not a string literal, yields
    nothing."""
    name = method.lower()
    if name in _PS_DOTNET_FILE_READS:
        return []
    args = [a.strip() for a in span.split(",")]
    out: list[str] = []
    for index in _PS_DOTNET_WRITE_ARGS.get(name, (0,)):
        if len(args) <= index:
            continue
        arg = args[index]
        if len(arg) >= 2 and arg[0] in "'\"" and arg[-1] == arg[0]:
            out.append(_ps_unquote(arg))
    return out


# ── PowerShell interpreter arm (DEF-712) ──────────────────────────────────
#
# `python -c "open('<hook>','w')"`, `& "C:\Python312\python.exe" -c ...`,
# `node -e '...'`, `py -3 -c "..."` and a program PIPED to the interpreter
# (`@'...'@ | python -`, `"..." | node -`, `@'...'@ | pwsh -Command -`) all
# ALLOWED on the PowerShell tool while the identical write denied on Bash
# (driven 2026-09-07 in the DEF-704 failure-mode review). The Bash arms
# (`_PYTHON_DASH_C_RE` and siblings, `_INTERP_STDIN_RE`) had no PowerShell
# twin: DEF-698 scoped the twin out of the stdin arm and pointed at DEF-697,
# which is about permission verbs, so the leg had no row until the review.
#
# The same discipline as the Bash arms, in PowerShell's grammar:
#   * the OPENER is `_PS_CMD_POS`-anchored and matched on the scan text, so a
#     `# python -c ...` comment, a `Write-Host '...'` string or a `$doc = @'...'@`
#     here-string is a mention;
#   * the BODY is read from the RAW twin at the same offsets
#     (`powershell_scan_pair`), because its own quotes and parens are what the
#     inner write patterns match, and a PowerShell string's escapes are undone
#     first (`''` in a single-quoted string; `""` and a backtick before a quote
#     or `$` in a double-quoted one) so `open(""x"", ""w"")` reads as the
#     program Python receives;
#   * the body is dispatched through the SAME inner write tables the Bash arms
#     use (`_STDIN_PROGRAM_WRITE_RES`), so a Python writer learned once is
#     learned for both shells.
# The head may be an executable given by path (`_PS_EXE_PREFIX`) and may
# carry valued switches before `-c` (`python -W ignore -c ...`, `py -3.12 -c`):
# `_PS_SWITCH_RUN` is the run, one bare value per switch, the DEF-717
# constant, composed here after a lookahead that demands the blank the run's
# own leading `[ \t]*` then consumes -- two adjacent blank quantifiers would
# be the ambiguous pair the ReDoS receipt forbids.
#
# THE STDIN SPELLING HAS NO HEREDOC. PowerShell feeds a program on stdin only
# through a pipe, so the opener is `| <interpreter> [switches] [-]` at the END
# of its statement (a script or module operand after the head means the piped
# text is DATA, and the lookahead refuses it), and the body is the statement
# BEFORE the pipe: for python, node, ruby and perl the whole raw segment is
# handed to the inner patterns (a literal write is found wherever it sits, and
# nothing else in the segment can match them); for `powershell`/`pwsh` reading
# `-Command -`, `-File -` or bare stdin the program is PowerShell, so the
# here-string or the last quoted string before the pipe is extracted and the
# PowerShell extractor runs on it once more (depth-bounded) -- the masker would
# otherwise blank the very separators that make `Set-Content` a command
# position inside the literal.
#
# Declared limits, pinned in `TestPowerShellInterpreterProgram`: a variable
# holding the program (`$code | python -`, `python -c $code`), a program read
# from a file (`Get-Content x.py | python -`) -- the indirection classes
# BC-OOS-001/002 already scope out; `Start-Process python -ArgumentList "-c
# ..."` (the `-c` sits inside the quoted argument list, no opener shape); a
# here-string as the `-c` argument (`python -c @'...'@`: the program string
# is a quoted literal); a QUOTED switch value (`-W "ignore" -c`, the run's
# own declared limit); and a module operand (`python -m x`) is read as a
# stdin consumer, the over-capture direction: the piped text is scanned for
# a literal write and ordinary data never carries one. For the two shells a
# `-File <script>` names the program, so the piped text is data and the
# match is dropped (`_PS_STDIN_FILE_SWITCH_RE`).
#
# ReDoS: the program string's branches are mutually exclusive (`''` vs
# `[^']`; a backtick-led pair vs `""` vs neither); the flag run is
# `_PS_SWITCH_RUN`, pinned under the watchdog by DEF-717; the here-string
# body is `[^\n]` vs a newline NOT followed by the terminator, so one parse.
# All registered in `tests/test_redos.py`.

#: One PowerShell string literal holding a program: single-quoted (the only
#: escape is a doubled quote) or double-quoted (a backtick escapes the next
#: character, a doubled quote is a quote). The body is `sq` or `dq`. An
#: optional backtick before the opening quote is the nested spelling --
#: `powershell -Command "python -c `"open(...)`""` -- where the program's
#: quotes are escaped for the OUTER string; the closing `"` of the outer
#: string then ends the body, and the unescape folds the backtick pair.
#: NOT the bash word grammar (DEF-832 stops at this shell): PowerShell does
#: not concatenate adjacent quoted segments into one argument the way bash
#: does (a doubled quote is an escape inside a string, and a quoted string
#: glued to a bare word is its own token), so the segment-concatenation
#: class does not transfer; this program string stays two arms, and the
#: Bash-tool rows on the PowerShell leg pin its reading unchanged.
_PS_PROGRAM_STRING = (
    r"(?:`?'(?P<sq>(?:''|[^'])*)'"
    r"|`?\"(?P<dq>(?:`.|\"\"|[^`\"])*)\")"
)
#: The head's suffix and closing quote (`python3.12`, `python.exe"`), then the
#: blank the switch run consumes.
_PS_INTERP_HEAD_TAIL = r"[\w.-]*" + _QUOTED_VERB_TAIL + r"(?=[ \t])"
_PS_INLINE_C_TAIL = _PS_INTERP_HEAD_TAIL + _PS_SWITCH_RUN + r"-c[ \t]+" + _PS_PROGRAM_STRING
_PS_INLINE_E_TAIL = _PS_INTERP_HEAD_TAIL + _PS_SWITCH_RUN + r"-e[ \t]+" + _PS_PROGRAM_STRING
# `py` is the Windows launcher (`py -3 -c "..."` is python); it is the python
# arm. Case-insensitive like every PowerShell matcher; DOTALL for the
# backtick-escaped newline a double-quoted program may hold.
_PS_PYTHON_DASH_C_RE = re.compile(
    _PS_CMD_POS + _PS_EXE_PREFIX + r"(?:python|pypy|py)" + _PS_INLINE_C_TAIL,
    re.IGNORECASE | re.DOTALL,
)
_PS_NODE_DASH_E_RE = re.compile(
    _PS_CMD_POS + _PS_EXE_PREFIX + r"node" + _PS_INLINE_E_TAIL, re.IGNORECASE | re.DOTALL,
)
_PS_RUBY_DASH_E_RE = re.compile(
    _PS_CMD_POS + _PS_EXE_PREFIX + r"ruby" + _PS_INLINE_E_TAIL, re.IGNORECASE | re.DOTALL,
)
_PS_PERL_DASH_E_RE = re.compile(
    _PS_CMD_POS + _PS_EXE_PREFIX + r"perl" + _PS_INLINE_E_TAIL, re.IGNORECASE | re.DOTALL,
)
#: The inline openers, keyed by the `_STDIN_PROGRAM_WRITE_RES` table they
#: dispatch to (the python opener covers `pypy` and the `py` launcher).
_PS_INLINE_PROGRAM_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("python", _PS_PYTHON_DASH_C_RE),
    ("node", _PS_NODE_DASH_E_RE),
    ("ruby", _PS_RUBY_DASH_E_RE),
    ("perl", _PS_PERL_DASH_E_RE),
)
if not {interp for interp, _ in _PS_INLINE_PROGRAM_RES} <= set(_STDIN_PROGRAM_WRITE_RES):
    raise RuntimeError(
        "PowerShell inline-program roster drift: an opener without a dispatch "
        "key would raise KeyError inside the guard"
    )

#: The heads that read a program from stdin when piped to, ONE literal: the
#: opener's alternation and the dispatch below are both derived from it.
_PS_STDIN_HEAD_ALTERNATION = "python|pypy|py|node|ruby|perl|" + _POWERSHELL_HEADS
#: Head -> `_STDIN_PROGRAM_WRITE_RES` key; the two shells are absent because
#: their program is PowerShell and is re-scanned, not pattern-matched.
_PS_STDIN_DISPATCH: dict[str, str] = {
    "python": "python", "pypy": "pypy", "py": "python",
    "node": "node", "ruby": "ruby", "perl": "perl",
}
#: The same roster the Bash leg routes out to (DEF-637): one literal, two legs.
_PS_STDIN_SHELL_HEADS = _STDIN_SHELL_HEADS
#: A bash program behind `bash -c` / `sh -c` on the PowerShell tool (DEF-637,
#: the other direction): the head may be an executable given by path
#: (`& 'C:\Program Files\Git\bin\bash.exe' -c "..."`), the switch run is
#: crossed, the program is ONE PowerShell string literal (`_PS_INLINE_C_TAIL`,
#: the interpreter arm's tail verbatim) whose escapes are undone before the
#: Bash extractor reads it. `bash` is deliberately NOT a `_PS_REPARSE_OPENERS`
#: member: that roster un-blanks a literal span for the PowerShell matchers,
#: and a bash program must never be read by them -- the routing hands it to
#: its own grammar instead. `wsl bash -c` (a wrapper the command position
#: does not roster) is a declared limit, pinned. The tail is the shell's
#: own, not the interpreter arm's: a POSIX shell CLUSTERS short options, and
#: `bash -lc "..."` -- the login-shell one-liner -- is the idiomatic spelling
#: (both reviews drove it ALLOWING against a denying `bash -l -c`); the
#: cluster ends in `c`, so `-[A-Za-z]{0,8}c` takes `-lc`, `-ec`, `-xc` and
#: the bare `-c`. The run before it may also consume a cluster as a switch;
#: the run gives it back, and a flood of clusters is one pass (registered).
_PS_SHELL_C_TAIL = (
    _PS_INTERP_HEAD_TAIL + _PS_SWITCH_RUN + r"-[A-Za-z]{0,8}c[ \t]+" + _PS_PROGRAM_STRING
)
_PS_BASH_DASH_C_RE = re.compile(
    _PS_CMD_POS + _PS_EXE_PREFIX + r"(?:" + _POSIX_SHELL_HEADS + r")" + _PS_SHELL_C_TAIL,
    re.IGNORECASE | re.DOTALL,
)
if set(_PS_STDIN_HEAD_ALTERNATION.split("|")) != (
    set(_PS_STDIN_DISPATCH) | _PS_STDIN_SHELL_HEADS
):
    raise RuntimeError(
        "PowerShell stdin-head roster drift: the alternation and the dispatch disagree"
    )
if not set(_PS_STDIN_DISPATCH.values()) <= set(_STDIN_PROGRAM_WRITE_RES):
    raise RuntimeError(
        "PowerShell stdin dispatch names an interpreter with no inner write table"
    )
#: `| <head> [switches] [-]` at the end of a statement. Group 1 is the head,
#: `run` the switch run. The run may carry values (`-NoProfile
#: -ExecutionPolicy Bypass -Command -`, `python -W ignore -`); a `-` operand
#: is optional (`| python` with piped stdin runs the program too); a BARE
#: operand is a script and the lookahead refuses the match. A switch's value
#: is not refused: `-m json.tool` matches, the over-capture direction the
#: comment above records, and `-File x.ps1` on a shell head matches too and
#: is dropped by the consumer, since the file is the program there.
_PS_INTERP_STDIN_RE = re.compile(
    _PS_CMD_POS + _PS_EXE_PREFIX + r"(" + _PS_STDIN_HEAD_ALTERNATION + r")"
    + r"[\w.-]*" + _QUOTED_VERB_TAIL
    + r"(?:(?=[ \t])(?P<run>" + _PS_SWITCH_RUN + r")(?:-[ \t]*)?)?"
    + r"(?=$|[;|&\n\r)}])",
    re.IGNORECASE,
)
#: A `-File <script>` (or `/f`) switch with a value that is not `-`: the
#: shell's program is that file, and what is piped to it is data.
_PS_STDIN_FILE_SWITCH_RE = re.compile(r"[-/]f(?:ile)?[ \t]+[^\s\"'\-/]", re.IGNORECASE)
#: A here-string, either quote kind: `@'` + EOL, the body, EOL + `'@`. The body
#: admits any character but a newline, or a newline NOT followed by the
#: terminator -- exclusive branches, one parse. Searched only when the segment
#: ends in a terminator, so an opener never scans to an absent close.
_PS_HERE_STRING_RE = re.compile(
    r"@(['\"])[ \t]*\r?\n((?:[^\n]|\n(?![ \t]*\1@))*)\r?\n[ \t]*\1@"
)
_PS_PROGRAM_STRING_RE = re.compile(_PS_PROGRAM_STRING)
#: Statement boundaries for the segment before a pipe: the separator set of
#: `_PS_CMD_POS_SEP` less `=` (the body may sit on the right of an
#: assignment, `$x = @'...'@ | python -`). The pipe IS a boundary: the
#: piped program is the stage immediately before the interpreter, and the
#: first cut, which read the whole prefix, cost O(n) per match and a
#: re-scan of it for every `|pwsh` -- 7 s on an 856-byte command, past
#: the hook's timeout, with a real protected write in front of the flood
#: (review, driven). One boundary list is built per call and searched by
#: bisection, so a flood of openers costs one pass.
_PS_STDIN_SEGMENT_BOUNDARY_RE = re.compile(r"[;\n\r(){}&|]")
#: How deep a piped PowerShell program is re-scanned. One level is the shape
#: an agent writes; two covers a program that pipes to a second shell; the
#: bound exists so a body can never recurse on its own length.
_PS_STDIN_MAX_DEPTH = 2


def _ps_unescape_program(body: str) -> str:
    """The program text PowerShell hands the interpreter, from the literal's
    source. A doubled quote is one quote; in a double-quoted string a backtick
    before a quote or a dollar is an escape. ALL four forms are undone
    whatever kind the innermost literal is, because a program behind a
    re-parsing wrapper carries the OUTER span's escapes too --
    ``powershell -Command "python -c 'open(''<hook>'',''w'')'"`` hands the
    inner shell ``''`` that it, not this leg, collapses -- and one level of
    nesting is the shape an agent writes. The cost is a program that itself
    holds a doubled quote beside a protected path (``open(''+'<hook>','w')``),
    which reads wrong here (a miss); the Bash leg misses that spelling the
    same way, so it opens no class of its own (review, driven)."""
    return (body.replace("''", "'").replace('""', '"')
                .replace('`"', '"').replace("`'", "'").replace("`$", "$"))


def _ps_inline_program_bodies(command: str, scan: str) -> Iterator[tuple[str, str]]:
    """Yield ``(interpreter, program_text)`` for every ``-c`` / ``-e`` inline
    program on the PowerShell leg. The opener is found on ``scan``; the body
    is read from the raw ``command`` at the same offsets and unescaped. If the
    two strings ever disagree in length the raw command is searched instead:
    a false match there costs a denial, a missed one a write."""
    if len(scan) != len(command):
        scan = command
    for interp, rx in _PS_INLINE_PROGRAM_RES:
        for m in rx.finditer(scan):
            kind = "sq" if m.group("sq") is not None else "dq"
            yield interp, _ps_unescape_program(command[m.start(kind):m.end(kind)])


def _ps_program_literal_before_pipe(segment: str) -> str:
    """The PowerShell program a piped shell receives: the here-string in the
    raw segment when the segment ends in one, else the last quoted string,
    else the whole segment (nothing literal to extract -- `Get-Content x |
    pwsh -c -` -- and a re-scan of the segment finds nothing, correctly)."""
    if segment.rstrip().endswith(("'@", '"@')):
        # The LAST here-string, as the quoted-string branch takes the last
        # literal: a comma array of two here-strings pipes both, and the
        # first cut extracted the first and never scanned the second
        # (review, driven ALLOWING).
        last_hs = None
        for last_hs in _PS_HERE_STRING_RE.finditer(segment):
            pass
        if last_hs is not None:
            return last_hs.group(2)
    last = None
    for last in _PS_PROGRAM_STRING_RE.finditer(segment):
        pass
    if last is not None:
        kind = "sq" if last.group("sq") is not None else "dq"
        return _ps_unescape_program(last.group(kind))
    return segment


def _ps_shell_program_bodies(command: str, scan: str) -> Iterator[str]:
    """Yield every bash program a PowerShell command hands to `bash` / `sh`
    (DEF-637): the quoted `-c` operand, opener on ``scan``, body from the raw
    ``command`` at the same offsets and unescaped the way PowerShell hands it
    over; the same length guard as the interpreter arm. The yielded text is
    what bash receives, so the Bash extractor runs its own masker on it."""
    if len(scan) != len(command):
        scan = command
    for m in _PS_BASH_DASH_C_RE.finditer(scan):
        # By the literal's OWN kind, not `_ps_unescape_program`'s
        # all-four-forms fold: inside a single-quoted PowerShell string `""`
        # is two literal characters, and folding them made `bash -c 'echo ""
        # > <hook> ""'` -- a command that truncates the file -- read as one
        # balanced `"..."` span that hid the redirect from the bash masker
        # (code review, driven). The interpreter arm keeps the fold: a program
        # in a language whose strings it pattern-matches is a different
        # consumer, with the miss its docstring declares.
        if m.group("sq") is not None:
            yield command[m.start("sq"):m.end("sq")].replace("''", "'")
        else:
            yield _ps_unescape_program(command[m.start("dq"):m.end("dq")])


def _ps_stdin_program_bodies(command: str, scan: str) -> Iterator[tuple[str, str]]:
    """Yield ``(head, segment_text)`` for every interpreter or shell that reads
    its program from a PIPE on the PowerShell leg. The opener must have opened
    at a pipe -- `_PS_CMD_POS` also opens after `;`, a newline or a re-parsing
    wrapper, where the head has no stdin program -- and the body is the raw
    ``command``'s text of the pipeline stage before it."""
    if len(scan) != len(command):
        scan = command
    boundaries = [b.start() for b in _PS_STDIN_SEGMENT_BOUNDARY_RE.finditer(scan)]
    for m in _PS_INTERP_STDIN_RE.finditer(scan):
        if scan[m.start()] != "|":
            continue
        head = m.group(1).lower()
        run = m.group("run") or ""
        if head in _PS_STDIN_SHELL_HEADS and _PS_STDIN_FILE_SWITCH_RE.search(run):
            continue  # `-File x.ps1`: the file is the program, the pipe is data
        i = bisect.bisect_left(boundaries, m.start())
        start = boundaries[i - 1] + 1 if i else 0
        yield head, command[start:m.start()]


# PowerShell ``New-Item -ItemType SymbolicLink`` symlink creation.
# Order-flexible: require New-Item + the SymbolicLink ItemType, then capture the
# link location from -Path / -Name (the link, NOT -Target/-Value which is where
# it points). Allowlist-blind like the ln/cp twins. ``New-Item`` plus its ``ni``
# alias (the positional and alias forms evade a -Path/-Name-only literal).
#
# ⚠ MOVED HERE FROM BESIDE `_CP_SYMLINK_RE` AND ANCHORED, 2026-08-26. This chain
# was the last unanchored command matcher in the module, and it survived the
# 2026-08-25 sweep that anchored every other one for a reason worth recording:
# the gate that pins the property could not see it. `_COMMAND_VERBS` in
# `tests/test_speedbump_irreversible.py` is a hand-written roster that omits
# `New-Item`/`ni`, so all four members sat outside the census population while
# the gate reported "every command matcher is anchored, zero exceptions" -- true
# of the population it could see, false of the module. Measured with maintenance
# mode cleared: 6 of 8 plain MENTIONS of a protected symlink were refused (a
# double- and a single-quoted string, a line comment, a trailing comment, a
# `$doc = "..."` assignment, and the `ni` alias in a string) on the tier
# maintenance mode does NOT relieve, while the `Set-Content` siblings twenty
# lines up scored 0 of 4 on the same probe. Same finding as those siblings, one
# matcher over -- see their block above.
#
# ⚠ ONLY THE VERB MEMBERS TAKE THE ANCHOR. A command-position anchor on a FLAG
# is meaningless: `-ItemType SymbolicLink` and `-Path`/`-Name` are arguments,
# never the head of a statement, and anchoring them would match nothing. The
# call site is a conjunction gated on the verb, so anchoring the verb is what
# decides whether the flags are ever consulted. Anchor what is a command; leave
# what is an argument.
#
# Group 1 stays the path in `_PS_POSITIONAL_PATH_RE`: every group inside
# `_PS_CMD_POS` is non-capturing, exactly as for `_PS_PATH_FLAG_RE` above.
_PS_NEW_ITEM_RE = re.compile(
    _PS_CMD_POS + r"\b(?:New-Item|ni)\b" + _QUOTED_VERB_TAIL, re.IGNORECASE
)
_PS_SYMLINK_ITEMTYPE_RE = re.compile(r"-ItemType\s+SymbolicLink\b", re.IGNORECASE)
_PS_LINK_LOCATION_RE = re.compile(r"-(?:Path|Name)\s+([^\s;|&]+)", re.IGNORECASE)
# Positional -Path: the first non-flag token right after New-Item/ni
# (``New-Item <path> -ItemType SymbolicLink``) -- the positional form evades the
# -Path/-Name-only capture.
_PS_POSITIONAL_PATH_RE = re.compile(
    _PS_CMD_POS + r"\b(?:New-Item|ni)" + _QUOTED_VERB_TAIL
    + r"\s+([^\s;|&-][^\s;|&]*)", re.IGNORECASE
)


def powershell_symlink_linknames(command: str) -> list[str]:
    """Return the link-location args of a PowerShell ``New-Item -ItemType
    SymbolicLink`` (or ``ni`` alias) command -- the symlink being created -- else ``[]``.

    Captures ``-Path`` / ``-Name`` AND a positional path (the link), NOT
    ``-Target`` / ``-Value`` (where it points). Scans `powershell_scan_text`:
    this leg read the RAW command until the DEF-694 failure-mode pass drove the
    canonical `cc/blueprints/latest.json` forge past it on a backtick-continued
    `-Path`.
    """
    raw, command = powershell_scan_pair(command)
    if not (_PS_NEW_ITEM_RE.search(command) and _PS_SYMLINK_ITEMTYPE_RE.search(command)):
        return []
    # found on the scan, read from the raw twin at the same offsets (DEF-794)
    names = [raw_operand(raw, m) for m in _PS_LINK_LOCATION_RE.finditer(command)]
    positional = _PS_POSITIONAL_PATH_RE.search(command)
    if positional:
        names.append(raw_operand(raw, positional))
    return names


def powershell_removal_is_recognized_safe(command: str) -> bool:
    r"""True only when EVERY ``Remove-Item`` in *command* targets nothing but
    recognized-safe RELATIVE ephemeral directories.

    ⚠ WHY THIS EXISTS. The PS records carry NO operand analysis at all --
    ``Remove-Item\s+-Recurse\s+-Force`` matches whatever follows -- so the hard
    deny fired on ``Remove-Item -Recurse -Force .\build``, a target its Bash twin
    allows outright. Measured 2026-08-22. On the platform with the least
    execution coverage in this repo, an ordinary build clean was unrunnable, and
    maintenance mode does not bypass a hard stop.

    ⚠ THIS IS A CARVE-OUT, NOT A RE-TIERING, AND THE DIFFERENCE IS THE SAFETY
    ARGUMENT. Bash narrows by asking "can this operand be absolute?" and drops
    everything else to the soft speed-bump. PowerShell has NO soft tier
    (``_speedbump`` predicates are all ``tool_name != "Bash"`` guarded), so
    narrowing the same way would leave relative Windows targets with no guard at
    all. Instead the deny STANDS by default and steps aside only for an
    already-calibrated allowlist. Windows therefore stays STRICTER than Bash: a
    relative SOURCE directory still denies here where the Bash twin only
    speed-bumps. That asymmetry is deliberate and is the fail-closed direction.

    FAILS CLOSED on anything it cannot parse with confidence -- a variable, a
    drive or PS-provider qualifier, a wildcard, a parent-dir segment, a UNC or
    rooted path, or any bare token it does not recognize (including the VALUE of
    a flag such as ``-ErrorAction SilentlyContinue``, which keeps the deny).
    Over-strict by construction: a false deny costs one retry, a false allow
    costs a tree.
    """
    targets = _powershell_removal_targets(command)
    if targets is None:
        return False
    safe = {p.rstrip("/") for p in SAFE_EPHEMERAL_DIRS}
    return all(t.split("/", 1)[0] in safe for t in targets)


def powershell_removal_is_plainly_relative(command: str) -> bool:
    """True when every ``Remove-Item`` operand parses confidently as a plain
    RELATIVE path inside the working tree -- whether or not it is on the
    ephemeral roster.

    The second of two questions over ONE parser, and the split is the whole
    point. ``..._is_recognized_safe`` asks "is this target on the allowlist";
    this asks "can I see the target at all, and is it plainly local". They were
    a single function until 2026-08-24, which forced one answer onto three
    different situations and made an ordinary build clean unrunnable on Windows.

    Measured that day: of fifteen ordinary relative cleans, PowerShell HARD-denied
    nine (`.\\out`, `.\\bin`, `.\\obj`, `.\\target`, `.\\coverage`, `.\\.venv`,
    `.\\artifacts`, `.\\logs`, `.\\reports`) -- twice in a row, so no re-issue
    cleared them, on a tier maintenance mode does not bypass. Bash soft-bumped
    every one of the same nine and let the second attempt through. A Windows
    developer cleaning a build directory had no move left except turning the
    hooks off, which is the failure this whole pass exists to prevent.

    ⚠ The carve-out's original note argued the asymmetry was the fail-closed
    direction *because PowerShell had no soft tier*. That premise is what
    changed: the tier now exists (`_speedbump._pred_rmrf` accepts PowerShell),
    so the honest tiering is the same one Bash has had throughout -- absolute,
    globbed, qualified or unparseable stays HARD-denied; roster-ephemeral is
    allowed outright; and everything in between is a re-issuable speed bump
    rather than a wall.
    """
    return _powershell_removal_targets(command) is not None


#: Remove-Item's parameters, for the landing probe alone: the switches (no
#: value), the value-taking ones, and the two whose value IS a target. An
#: unambiguous prefix resolves as PowerShell resolves it. Needed because
#: `_powershell_removal_targets` deliberately over-collects a flag's value
#: (its docstring: that only ever TIGHTENS the roster and the bump) -- on the
#: wall it would have refused `-ErrorAction Stop` at a shallow cwd as the
#: target `Stop` (failure-mode review, driven, 2026-09-13).
_PS_REMOVE_SWITCHES = ("recurse", "force", "whatif", "confirm", "verbose", "debug")
_PS_REMOVE_VALUED = (
    "path", "literalpath", "filter", "include", "exclude", "credential", "stream",
    "erroraction", "errorvariable", "informationaction", "informationvariable",
    "outvariable", "outbuffer", "pipelinevariable", "progressaction",
    "warningaction", "warningvariable",
    # the common parameters' aliases (DEF-842's review: `-ea 0 build` read
    # `0` as a target once an unknown flag stopped taking a value)
    "ea", "ev", "ia", "iv", "ov", "ob", "pv", "wa", "wv",
)
_PS_REMOVE_TARGET_FLAGS = ("path", "literalpath")

#: The enumerator's parameters (`Get-ChildItem`, `Get-Item`, and the `dir`,
#: `gci`, `gi` aliases; `ls` is /bin/ls under pwsh on a POSIX host and its
#: `-R` reads as the recurse cluster) -- for `_ps_pipeline_roots`. A
#: switch takes no value; a valued parameter takes the next token or a
#: `:`-bound one; `-Filter` and `-Include` NARROW the walk (`-Exclude` does
#: not, as `! -name` does not; `-File` and `-Directory` do not, as `-type`
#: does not); `-Path` / `-LiteralPath` name the roots, else the first
#: positional does, and a SECOND positional is `-Filter` (Get-ChildItem's
#: positional 1). An ambiguous or unknown flag is a switch here -- the
#: direction that keeps the root readable -- and PowerShell refuses the
#: ambiguous ones anyway (`-fi` is File or Filter; driven).
_PS_ENUM_SWITCHES = (
    "recurse", "force", "name", "directory", "file", "hidden", "readonly", "system",
    "followsymlink", "whatif", "confirm", "verbose", "debug",
)
_PS_ENUM_VALUED = (
    "path", "literalpath", "filter", "include", "exclude", "depth", "attributes",
    "stream", "credential", "erroraction", "errorvariable", "informationaction",
    "informationvariable", "outvariable", "outbuffer", "pipelinevariable",
    "progressaction", "warningaction", "warningvariable",
)
_PS_ENUM_NARROWING = ("filter", "include")
_PS_ENUM_ROOT_FLAGS = ("path", "literalpath")
#: A filter value that EXCLUDES NOTHING: `-Include *`, `-Filter *.*` (the
#: legacy every-file pattern), `**`. A narrowing predicate narrows by its
#: value, not its presence -- the first cut read presence, and the
#: failure-mode review drove `gci -Recurse -Include * | ri -r -fo` to a
#: wipe on pwsh 7.6.5 with no tier fired, while the deny text told the
#: operator to add `-Include`. The find twin is `_FIND_CATCHALL_VALUES`.
_PS_ENUM_CATCHALL_FILTER = frozenset({"*", "**", "*.*"})
#: A wildcard ROOT whose leaf is a bare `*` names its directory (`gci *
#: -Recurse` and `gci ./* -Recurse -File` take everything under `.`); a
#: bounded one (`*.tmp`, `src/*.log`) narrows.
_PS_ENUM_CATCHALL_LEAF = frozenset({"*", "**"})
#: `-Attributes !Directory` (any case, `!D` too): the files-only enumeration
#: in PowerShell's other spelling, the twin of `-File` (failure-mode review,
#: driven to every file gone).
_PS_ATTR_NO_DIRECTORY_RE = re.compile(r"!\s*d(?:irectory)?(?![a-z])", re.IGNORECASE)
#: A parenthesised first argument to `[IO.Directory]::Delete` followed by
#: the recursion flag -- one nesting level, bounded -- read on the raw text
#: past the arm's own argument group, which stops at the nested paren.
_PS_DOTNET_SUBEXPR_RECURSIVE_RE = re.compile(
    r"\((?:[^()\n]{0,256}|\([^()\n]{0,256}\)){0,4}\)[ \t]*,[ \t]*\$true\b", re.IGNORECASE,
)


def _ps_filter_is_catchall(value: str) -> bool:
    """True when a `-Filter` / `-Include` value (or the positional filter)
    excludes nothing: a catch-all pattern, or an array holding one."""
    parts = [p.strip() for p in _ps_unquote(value).split(",")]
    return any(p in _PS_ENUM_CATCHALL_FILTER for p in parts)


def _ps_split_roots(token: str) -> list[str]:
    """One enumerator operand as its roots: a comma builds an array, a QUOTED
    operand is one root however many commas it holds (the code review drove
    `"a,b"` split into two), unquoted the PowerShell way, the separator
    normalised."""
    if token[:1] in "\"'":
        parts = [_ps_unquote(token)]
    else:
        parts = [p for p in token.split(",") if p]
    return [p.replace("\\", "/") for p in parts]


def _ps_pipeline_roots(args: str) -> tuple[list[str], bool, bool]:
    """``(roots, narrowed, files_only)`` for one enumerator span (DEF-822):
    the roots by `-Path` / `-LiteralPath` or the first positional (a comma
    builds an array; a quoted operand is one root), the current location
    when none is named; ``narrowed`` when a `-Filter` or `-Include` value,
    the positional filter, or a wildcard root actually EXCLUDES something
    (a catch-all narrows nothing; a root whose leaf is a bare `*` is its
    directory); ``files_only`` on `-File` or `-Attributes !Directory`, the
    enumerations that take every file under the root without a recursive
    remove."""
    tokens = _ps_operand_tokens(args)
    flagged: list[str] = []
    positionals: list[str] = []
    narrowed = files_only = False
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if not tok.startswith("-"):
            positionals.append(tok)
            continue
        name, colon, attached = tok[1:].partition(":")
        name = name.lower()
        switches = [s for s in _PS_ENUM_SWITCHES if s.startswith(name)]
        valued = [v for v in _PS_ENUM_VALUED if v.startswith(name)]
        exact = name in _PS_ENUM_SWITCHES or name in _PS_ENUM_VALUED
        if exact:
            switches = [name] if name in _PS_ENUM_SWITCHES else []
            valued = [name] if name in _PS_ENUM_VALUED else []
        if valued and not switches:
            value = attached if colon else (tokens[i] if i < len(tokens) else "")
            if not colon:
                i += 1
            if all(v in _PS_ENUM_ROOT_FLAGS for v in valued):
                flagged.extend(_ps_split_roots(value))
            elif all(v in _PS_ENUM_NARROWING for v in valued):
                narrowed = narrowed or not _ps_filter_is_catchall(value)
            elif valued == ["attributes"] and _PS_ATTR_NO_DIRECTORY_RE.search(_ps_unquote(value)):
                files_only = True
            continue
        if switches and not valued and switches == ["file"]:
            files_only = True
        # a switch, or an ambiguous or unknown flag read as one: no value
    if flagged:
        roots = flagged
        if positionals and not _ps_filter_is_catchall(positionals[0]):
            narrowed = True               # `-Path x *.log`: the positional binds to -Filter
    else:
        roots = _ps_split_roots(positionals[0]) if positionals else []
        if len(positionals) > 1 and not _ps_filter_is_catchall(positionals[1]):
            narrowed = True
    resolved: list[str] = []
    for r in roots:
        head, _sep, leaf = r.rpartition("/")
        if leaf in _PS_ENUM_CATCHALL_LEAF:
            resolved.append(head or ".")  # `*`, `./*`, `sub/*`: the directory itself
        else:
            if any(ch in r for ch in "*?["):
                narrowed = True           # a bounded wildcard root narrows
            resolved.append(r)
    return (resolved or ["."]), narrowed, files_only


def _ps_removal_target_tokens(
    args: str, tokens: list[str] | None = None, *, unknown_takes_value: bool = True,
) -> list[str]:
    """The tokens of one ``Remove-Item`` argument span that NAME a target:
    the positional operands and the value of ``-Path`` / ``-LiteralPath``
    (spaced or ``-Path:x``), every other flag's value dropped. An ambiguous
    or unknown flag is read as value-taking, so the token after it is not a
    target -- the direction that cannot add a wall."""
    # `tokens`: a quote-aware split the zone reader supplies (§C52), so a
    # target with a space is one token; the speed bump keeps the whitespace
    # split it measured against.
    tokens = args.split() if tokens is None else list(tokens)
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if not tok.startswith("-"):
            out.append(tok)
            continue
        name, colon, attached = tok[1:].partition(":")
        name = name.lower()
        switches = [s for s in _PS_REMOVE_SWITCHES if s.startswith(name)]
        valued = [v for v in _PS_REMOVE_VALUED if v.startswith(name)]
        # A /bin/rm cluster (`-rf`, `-f`) is a switch that takes no value
        # (DEF-822) -- unless the cmdlet reads the token as an unambiguous
        # VALUED parameter, which is the reading that runs: `-fi` is
        # `-Filter`, so its value is not a target, while `-f` (ambiguous:
        # Filter or Force, refused by PowerShell) and `-rf` (unknown to the
        # cmdlet) are the native binary's.
        if (switches or not valued) and _PS_RM_CLUSTER_RE.fullmatch(tok):
            continue
        names_a_target = bool(valued) and not switches and all(
            v in _PS_REMOVE_TARGET_FLAGS for v in valued)
        if colon:
            if attached and names_a_target:
                out.append(attached)
            continue
        if switches and not valued:
            continue                      # a switch: nothing follows it
        if not switches and not valued and not unknown_takes_value:
            # An UNKNOWN flag read as value-taking drops the next token -- the
            # direction that cannot add a wall for the speed bump, and the
            # direction that removes one for a zone deny (review: `-File`,
            # `-PassThru`, `-Update` each swallowed the operand). The zone and
            # secret readers ask for the over-yield reading instead.
            continue
        if i < len(tokens):
            value = tokens[i]
            i += 1
            if names_a_target:
                out.append(value)
    return out


def powershell_removal_lands_catastrophic(
    command: str, root: str | None, cwd: "str | os.PathLike[str] | None" = None,
) -> bool:
    """True when a plainly relative ``Remove-Item`` target, read from the
    directory the command runs in (DEF-790: ``cwd``, the payload's, else
    ``root``, moved by the command's own `Set-Location` chain), lands on a
    catastrophic target -- the repo or a parent of it, home, a shallow
    system path (`_target_is_catastrophic`). The PowerShell twin of the rule
    `has_catastrophic_recursive_rm` applies to a Bash operand: the hard tier
    asks it before the roster and the soft rung, and the speed bump defers
    on the same answer. Each invocation is placed in its statement BY OFFSET
    on the one scan text the chain and the matcher share -- never by
    searching the target's spelling, which the backslash spelling defeats
    and an unrelated mention of the name mis-places (failure-mode review,
    driven, 2026-09-13) -- and only the tokens that NAME a target are read
    (`_ps_removal_target_tokens`). A token the parser cannot vouch for stays
    the hard tier's by the existing rule. ``command`` is the raw text."""
    start = cwd or root
    if start is None:
        return False
    at = Path(start)
    try:
        text, statements = powershell_directory_chain(
            command, _hook_utils.directory_exists(at))
    except Exception:  # noqa: BLE001 -- the walk is advisory; a fault degrades to the start
        text, statements = powershell_scan_text(command), []
    fed = {m.start("rmargs"): m for m in _PS_PIPED_REMOVE_RE.finditer(text)}
    for m in _PS_REMOVE_ITEM_RE.finditer(text):
        here = m.start("args")
        dirs = next((ds for s, e, ds in statements if s <= here < e), (".",))
        bases = [str(_hook_utils.join_directory(at, d)) for d in dirs]
        # quote-aware, as the unforced twin reads the same span (the lane's
        # review): a quoted relative name with a space is ONE target
        args = m.group("args")
        tokens = _ps_removal_target_tokens(args, tokens=_ps_operand_tokens(args))
        if not tokens and here in fed:
            # fed by an enumerator pipe (DEF-822): the un-narrowed roots
            # are the targets; a narrowed pipeline is the zone check's. By
            # the dispatching reader, so a multi-word head (DEF-831) reads
            # by its own grammar here as in the sweep classifier (the
            # failure-mode review found this site and the record rung's
            # reading the cmdlet grammar over every head); the raw text
            # when the chain's text indexes it, else the chain's
            roots, narrowed, _files_only, _walks = _ps_pipeline_reading(
                command if len(command) == len(text) else text, fed[here])
            tokens = [] if narrowed else roots
        for raw in tokens:
            parts = _ps_removal_token_targets(raw)
            if parts is None:
                continue                  # not a plainly relative spelling: the existing rule's
            if any(_target_is_catastrophic(t, root, b) for t in parts for b in bases):
                return True
    return False


#: The home directory by the variables PowerShell names it with (`$HOME`,
#: `$env:USERPROFILE`, `$env:HOME`, `$env:HOMEPATH`, braced or not), at the
#: head of a target: DEF-842's arm reads it as `~` (operator, 2026-09-18: an
#: ordinary variable is one nudge; one that names the home is the wall).
_PS_HOME_VAR_RE = re.compile(
    r"\$(?:\{(?:HOME|env:(?:HOME|USERPROFILE|HOMEPATH))\}"
    r"|(?:HOME|env:(?:HOME|USERPROFILE|HOMEPATH))\b)",
    re.IGNORECASE,
)
#: `$PWD` at the head of a target by PowerShell's spelling (any case, braced
#: or not): the location the statement runs in, which the judge's ``base``
#: already is -- `_PWD_PREFIX_RE`'s reading, in parity (DEF-843; operator).
#: `$env:PWD` is the environment's copy, the parent's value that
#: Set-Location never moves: a variable like any other.
_PS_PWD_PREFIX_RE = re.compile(r"^(?:\$\{PWD\}|\$PWD)(?=/|$)", re.IGNORECASE)


def _outside_quotes(span: str) -> str:
    """``span`` with every quoted run blanked (same length): a switch is
    looked for outside the quotes, since a quoted operand is not one."""
    out: list[str] = []
    quote = ""
    for ch in span:
        if quote:
            out.append(" ")
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def _ps_unforced_recursive_removes(text: str) -> Iterator[tuple[int, list[str]]]:
    """``(offset, targets)`` for every ``Remove-Item`` (any alias, or the
    native rm) in ``text`` that carries a recurse switch and is NOT the
    records' recurse-and-force shape (DEF-842): the invocations the records
    and their rungs do not own, so neither tier pays a second pass for one
    they do. The switch is looked for outside quoted runs; the targets are
    the tokens that NAME one (`_ps_removal_target_tokens`, an unknown flag
    taking no value, so `--` or a GNU long option never hides the operand
    after it -- the code review), each unquoted, split on the array comma,
    separators normalized, a parenthesis stripped, and a brace stripped only
    when unbalanced (a statement's, never a braced variable's). ONE reading
    for the wall and the nudge."""
    for m in _PS_REMOVE_ITEM_RE.finditer(text):
        args = m.group("args")
        if not _PS_RECURSE_SWITCH_RE.search(_outside_quotes(args)):
            continue
        if _PS_RECURSIVE_FORCE_RE.search(text, m.start(), m.end()):
            continue
        parts: list[str] = []
        # quote-aware, as the zone reader splits the same span (the review's
        # item 4): a quoted target with a space is ONE target -- the checkout
        # by a path that holds one walls, and a bounded name like
        # `"* - Copy"` is no bare glob
        for token in _ps_removal_target_tokens(
                args, tokens=_ps_operand_tokens(args), unknown_takes_value=False):
            for part in token.replace('"', "").replace("'", "").split(","):
                part = part.replace("\\", "/").strip("()")
                if part.count("{") != part.count("}"):
                    part = part.strip("{}")      # a statement brace, never `${HOME}`'s own
                if part:
                    parts.append(part)
        yield m.start("args"), parts


def _ps_unforced_target_is_catastrophic(part: str, root: str | None, base: str | None) -> bool:
    """One target of a recursive remove without the force switch, by
    meaning (DEF-842's arm; operator, 2026-09-18): a variable that names the
    home directory is read as `~`; any other variable is the nudge's -- the
    Bash tier's reading of `$VAR` -- where the force form and the sweep
    judge refuse every variable; everything else by the sweep tier's judge."""
    m = _PS_HOME_VAR_RE.match(part)
    if m and (m.end() == len(part) or part[m.end()] == "/"):
        part = "~" + part[m.end():]
    # the location variable is the statement's own directory (DEF-843, the
    # Bash judge's reading): with nowhere to stand it stays a variable
    pwd = _PS_PWD_PREFIX_RE.match(part)
    if pwd and base is not None:
        part = "." + part[pwd.end():]
    elif pwd and not part[pwd.end():].strip("/*"):
        return True                        # from nowhere: as a bare wildcard is
    if "$" in part:
        return False
    return _ps_sweep_root_is_catastrophic(part, root, base)


def powershell_unforced_removal_off_roster(scan: str) -> bool:
    """True when a recursive remove without the force switch names a target
    off the ephemeral roster -- the nudge's question, asked of the reading
    the wall uses (`_ps_unforced_recursive_removes`, DEF-842). A roster
    target passes as its Bash twin does: its first component on
    `SAFE_EPHEMERAL_DIRS`, a wildcard under it included (`build/*`); a
    variable, an absolute path or a `..` step is off it."""
    safe = {p.rstrip("/") for p in SAFE_EPHEMERAL_DIRS}
    for _at, parts in _ps_unforced_recursive_removes(scan):
        for part in parts:
            p = part[2:] if part.startswith("./") else part
            if ".." in p.split("/") or p.split("/", 1)[0] not in safe:
                return True
    return False


def powershell_recursive_removal_is_catastrophic(
    command: str, root: str | None, cwd: "str | os.PathLike[str] | None" = None,
) -> bool:
    """DEF-842's PowerShell arm: True when a recursive remove without the
    force switch (`_ps_unforced_recursive_removes`; the records and their
    rungs own the recurse-and-force shape) names a target that is
    catastrophic BY MEANING (`_ps_unforced_target_is_catastrophic`: a
    variable that names the home is the home, any other variable is the
    nudge's, everything else the sweep tier's judge) from the directory the
    command runs in, each invocation placed in its statement by offset on
    the chain's one scan text, as `powershell_removal_lands_catastrophic`
    places it (a cursor, so a flood of statements stays linear). Read on the
    command as spelled and with its literal bindings inlined
    (`_expand_simple_ps_var_assignments`), a wall on either.

    Why the force switch is not the threshold: without it the remove still
    takes every item that is not hidden or read-only, with no prompt when no
    terminal is attached (driven on pwsh 7.6.5, 2026-09-18) -- the working
    tree of a checkout, the documents of a home directory. Until then the
    records matched only recurse-and-force, so the unforced spelling met no
    tier at all. A piped remove names no target here; it is the sweep
    tier's. ``command`` is the raw text."""
    if not any(True for _ in _ps_unforced_recursive_removes(powershell_scan_text(command))):
        return False
    inlined = _expand_simple_ps_var_assignments(command)
    readings = (command,) if inlined == command else (command, inlined)
    return any(_ps_unforced_lands_catastrophic(text, root, cwd) for text in readings)


def _ps_unforced_lands_catastrophic(
    command: str, root: str | None, cwd: "str | os.PathLike[str] | None",
) -> bool:
    """One reading of `powershell_recursive_removal_is_catastrophic`."""
    start = cwd or root
    at = Path(start) if start is not None else None
    statements: list[tuple[int, int, tuple[str | None, ...]]] = []
    raw, text = powershell_scan_pair(command)
    if at is not None:
        try:
            text, statements = powershell_directory_chain(
                command, _hook_utils.directory_exists(at))
        except Exception:  # noqa: BLE001 -- the walk is advisory; a fault places nothing
            statements = []
    string_at = _ps_quote_cursor(raw if len(raw) == len(text) else "")
    idx = 0
    for here, parts in _ps_unforced_recursive_removes(text):
        bases: list[str | None]
        if at is None:
            bases = [None]
        else:
            while idx < len(statements) and statements[idx][1] <= here:
                idx += 1
            dirs: tuple[str | None, ...] = _UNPLACED_DIRS
            if idx < len(statements) and statements[idx][0] <= here < statements[idx][1]:
                dirs = statements[idx][2]
            # in parity with the Bash unforced twin: a bare wildcard after an
            # unknown location walls from nowhere (`_statement_bases`)
            bases = _statement_bases(at, dirs, relief=_relief_applies(command, bash=False))
            # a remove whose arguments sit inside a program handed to another
            # process (pwsh -Command, Start-Process: the masker keeps it live)
            # runs where that process puts it -- its start switch, its own
            # location changes -- so the unknown directory is added, as the
            # Bash twin adds it for a delete inside a string (blocker
            # condition 2). A quoted verb's quote closes before its arguments.
            if None not in bases and string_at(here) is not None:
                bases.append(None)
        for part in parts:
            if any(_ps_unforced_target_is_catastrophic(part, root, b) for b in bases):
                return True
    return False


def _ps_removal_token_targets(raw: str) -> list[str] | None:
    """One ``Remove-Item`` operand token as the plainly relative target(s) it
    spells, or ``None`` when it cannot be vouched for -- the rule
    `_powershell_removal_targets` applies to every token, in one home."""
    # ⚠ NOT `_shell_unquote`. That helper is POSIX: it treats a
    # backslash as an ESCAPE and drops it, so `.\build` collapsed to
    # `.build` and this carve-out silently never fired for the very
    # form it exists for -- green, and doing nothing. In PowerShell the
    # escape character is a BACKTICK; a backslash is a separator. Strip
    # quotes only, then normalize separators. (Caught by driving the
    # hook, 2026-08-22; no test would have shown it.)
    # A BACKTICK IS POWERSHELL'S ESCAPE AND ITS LINE CONTINUATION. A
    # trailing one meant the real target sat on the NEXT line, which
    # `[^\n;|&]*` never reaches -- so the lone backtick was read as a
    # plainly-relative target and a drive-root delete dropped from HARD
    # to a re-issuable bump. Fail closed on any token containing one.
    if "`" in raw:
        return None
    tok = raw.replace('"', "").replace("'", "").replace("\\", "/")
    if tok.startswith("./"):
        tok = tok[2:]
    out: list[str] = []
    # A COMMA BUILDS AN ARRAY: `-Path a,..\x` is two targets, and
    # checking the joined token let `..` hide inside `a,..`. Split first,
    # then apply every check to each element.
    for part in tok.split(","):
        if part.startswith("./"):
            part = part[2:]
        if not part or part.startswith("/") or part.startswith("~"):
            return None
        # `[` is a PowerShell wildcard metacharacter and belonged with
        # `*` and `?` from the start.
        if any(ch in part for ch in ":$*?["):
            return None
        if ".." in part.split("/"):
            return None
        out.append(part)
    return out


def _powershell_removal_targets(command: str) -> list[str] | None:
    r"""Normalised operands of every ``Remove-Item`` in *command*, or ``None``
    when any one of them cannot be vouched for.

    ``None`` means "cannot parse with confidence" and is the fail-closed answer:
    a variable, a drive or PS-provider qualifier, a wildcard (``*``, ``?``,
    ``[``), a backtick, a parent-dir segment, a UNC or rooted path, or a home
    reference. Over-strict by construction -- a false deny costs one retry, a
    false allow costs a tree.

    ⚠ STATED LIMIT, because the prose used to claim otherwise: a flag's VALUE is
    collected as an operand (``-ErrorAction Stop`` contributes ``Stop``). That
    direction only ever TIGHTENS -- every operand must pass, so an extra token
    can turn a safe target into a bump but never a dangerous one into a pass --
    and it costs friction on a long flag cluster. Recorded rather than claimed
    fixed; a docstring that disagrees with its code is worse than none, because
    the reader reasons from a guard that is not there.
    """
    invocations = list(_PS_REMOVE_ITEM_RE.finditer(command))
    if not invocations:
        return None
    # A remove verb fed by an enumerator pipe takes the enumerator's roots
    # as its operands (DEF-822): placed by OFFSET -- the piped reader's
    # remove-verb span opens where this reader's argument span does. A
    # NARROWED pipeline vouches for itself (the zone check judges its root
    # by itself, as it does a narrowed find) and contributes nothing here.
    fed = {m.start("rmargs"): m for m in _PS_PIPED_REMOVE_RE.finditer(command)}
    out: list[str] = []
    for m in invocations:
        args = m.group("args")
        operands = [tok for tok in args.split() if not tok.startswith("-")]
        if not operands:
            pipe = fed.get(m.start("args"))
            if pipe is None:
                return None  # no parsable target -> cannot vouch for it
            # by the dispatching reader (DEF-831): one reader per head
            roots, narrowed, _files_only, _walks = _ps_pipeline_reading(command, pipe)
            if narrowed:
                continue
            operands = roots
        for raw in operands:
            parts = _ps_removal_token_targets(raw)   # the per-token rule, one home
            if parts is None:
                return None
            out.extend(parts)
    return out


# ⚠ ANCHORED 2026-08-24 (DEF-414f). This was the LAST bare-verb scan in the hook
# tree — a `\brm\b` that matched the token wherever it appeared, including inside
# a quoted grep pattern, an echo, or a commit message. Because it feeds the
# hard-deny tier, which dispatches AHEAD of the maintenance gate, the resulting
# false positive had no lever at all: `ESPALIER_MAINTENANCE_MODE=1` did not
# relieve it and the only remaining move was `disableAllHooks` — i.e. the deny
# trained the TOTAL bypass rather than the scoped one. 46 tracked files carry the
# literal, including CLAUDE.md, README.md and three adopter-deployed assets, so
# the doc documenting the guard could not be grepped for the thing it documents.
#
# Held open deliberately for a long time because anchoring NARROWS the one tier
# maintenance mode cannot bypass. The operator took that trade on 2026-08-24. The
# sibling precedent is the git tier, which has carried `_CMD_POS` throughout at
# no measured cost to the release-gating benchmark.
#
# ⚠ THE CAPTURE GROUP IS LOAD-BEARING, NOT STYLE. `iter_rm_invocations` passes the
# match text to a tokenizer that treats every non-flag token as a DELETE OPERAND.
# `_CMD_POS` matches the prefix too (`sudo `, `; `, `env FOO=1 `), so yielding
# `group(0)` would feed those words in as targets — `sudo rm -rf x` would report
# an operand `sudo`. Yield the named group, which starts at the verb.
#: The segment runs to a statement separator; the `&` of a redirect-duplication
#: operator (`2>&1`, `>&2`, `&>f`) is not one, and stopping there dropped every
#: operand after it -- a target written after the operator was never read
#: (failure-mode review, driven live 2026-09-11; the tokenizer already reads
#: the glued operator as consuming nothing). The alternatives are exclusive
#: on the character, so the run stays linear.
_RM_SEGMENT_RE = re.compile(
    _CMD_POS + r"(?P<seg>rm\b(?!=)(?:[^\n;|&]|(?<=[<>])&|&(?=>))*)", re.IGNORECASE
)


def _shell_unquote(token: str) -> str:
    r"""Static shell quote-removal on a single token: drop ``'``/``"`` quoting
    and backslash escapes, concatenating the pieces -- so ``'/'etc``, ``"/"etc``,
    ``\/``, ``''/`` resolve to what the shell hands rm (``/etc``, ``/etc``,
    ``/``, ``/``). Does NOT evaluate ``$``-expansions (variables, command /
    parameter substitution, ``$'...'`` ANSI-C) -- the documented dynamic,
    statically-undecidable classes."""
    out: list[str] = []
    i, n = 0, len(token)
    while i < n:
        c = token[i]
        if c == "\\":
            if i + 1 < n:
                out.append(token[i + 1])
                i += 2
            else:
                i += 1  # trailing backslash: drop
            continue
        if c in "'\"":
            j = token.find(c, i + 1)
            if j == -1:  # unterminated quote: rest is literal, minus the quote
                out.append(token[i + 1:])
                break
            out.append(token[i + 1:j])
            i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


_BRACE_ANALYSIS_BUDGET = 512  # recursion budget for the structural target probe


def _sequence_straddle_chars(inner: str) -> set[str]:
    r"""For a single-char ASCII *sequence* brace body ``c1..c2`` (optional
    ``..incr``), the subset of ``{'/', '*'}`` its range can produce -- because
    bash 4.0+/zsh expand ``{c1..c2}`` over the raw ASCII ordinal span, so e.g.
    ``{.../}`` -> ``.`` ``/`` (ord 46..47) and ``{)..*}`` -> ``)`` ``*`` (41..42).
    Empty for numeric ranges (``{1..9}`` -> digits, never ``/``/``*``), multi-char
    endpoints, or non-sequences. The increment is ignored (fail closed)."""
    m = re.fullmatch(r"(.)\.\.(.)(?:\.\.-?\d+)?", inner)
    if not m:
        return set()
    lo, hi = sorted((ord(m.group(1)), ord(m.group(2))))
    out: set[str] = set()
    if lo <= ord("/") <= hi:
        out.add("/")
    if lo <= ord("*") <= hi:
        out.add("*")
    return out


def _first_brace_group(token: str) -> tuple[int, int, list[str]] | None:
    r"""First brace group that can EXPAND to a leading ``/`` or ``*``:
    a TOP-LEVEL comma group -> ``(lo, hi, comma-alternatives)``; or a single-char
    ASCII *sequence* ``{c1..c2}`` whose range straddles ``/``/``*`` ->
    ``(lo, hi, [the producible '/' and/or '*'])``. Nesting-aware. Literal braces,
    numeric/non-straddling sequences, and no-comma groups are skipped so a LATER
    expandable group is still found (``{abc}{/a,/b}``, ``{.../}{a,b}``). Returns
    ``None`` if there is no such group."""
    n = len(token)
    i = 0
    while i < n:
        if token[i] != "{":
            i += 1
            continue
        depth, hi = 0, -1
        for k in range(i, n):
            if token[k] == "{":
                depth += 1
            elif token[k] == "}":
                depth -= 1
                if depth == 0:
                    hi = k
                    break
        if hi == -1:
            return None  # unbalanced from here on
        inner = token[i + 1:hi]
        alts, d, start, has_comma = [], 0, 0, False
        for k, ch in enumerate(inner):
            if ch == "{":
                d += 1
            elif ch == "}":
                d -= 1
            elif ch == "," and d == 0:
                has_comma = True
                alts.append(inner[start:k])
                start = k + 1
        alts.append(inner[start:])
        if has_comma:
            return i, hi, alts
        straddle = _sequence_straddle_chars(inner)
        if straddle:  # a sequence whose ASCII range yields '/' and/or '*'
            return i, hi, sorted(straddle)
        i = hi + 1  # literal / numeric / non-straddling -> skip, look for next
    return None


# Ephemeral roots. A delete UNDER one of these is scratch by construction, and
# the harness's own session contract mandates an absolute scratchpad path beneath
# one of them — so refusing it made the harness refuse the cleanup it requires.
# `/tmp/../../etc` is why an earlier prefix carve-out was rejected; that objection
# is answered by normalising BEFORE the containment test, not by declining to
# carve out at all.
_TEMP_ROOTS: tuple[str, ...] = (
    "/tmp", "/private/tmp", "/var/tmp", "/private/var/tmp",
    "/var/folders", "/private/var/folders", "/dev/shm",
)

_HOME_PREFIX_RE = re.compile(r"^(?:~|\$\{HOME\}|\$HOME)(?=/|$)")
#: `$PWD` at the head of a target (DEF-843): the directory the command runs
#: in, which the caller's ``base`` already is -- the one variable besides the
#: home whose value the guard knows without the shell.
_PWD_PREFIX_RE = re.compile(r"^(?:\$\{PWD\}|\$PWD)(?=/|$)")


def _posix(path: str) -> str:
    """Separator-normalised, symlink-resolved, `..`-resolved, no trailing slash.

    ⚠ `realpath` IS REQUIRED, not tidiness. macOS symlinks `/tmp` -> `/private/tmp`
    and `/var` -> `/private/var`, so the path a human types and the path the hook
    resolves for the repo root are DIFFERENT STRINGS for the same directory.
    Without this, `target == site` never fired for any repo under a temp root and
    the identity rule silently did nothing — measured, not predicted. `realpath`
    resolves what exists and leaves a non-existent tail alone, which is the right
    behaviour for a delete target that may already be gone.
    """
    if not path:
        return path
    # NORMALISE ON BOTH SIDES OF `realpath`, not just the input. On Windows
    # `os.path.realpath` IS `ntpath.realpath`, which returns backslash
    # separators whatever it was handed -- so replacing only on the way in
    # left `posixpath.normpath` looking at a single component. Every
    # comparison downstream then broke at once: the temp carve-out and the
    # identity/containment rules stopped matching, and the depth rule counted
    # 1 for every absolute target, so the safety-biased `min()` refused all
    # of them. Measured under emulated ntpath semantics, not predicted.
    #
    # And TRANSLATE THE GIT BASH DRIVE PREFIX BEFORE `realpath` (DEF-731).
    # `/c/Users/<u>` is what the Bash tool's own `pwd` returns on Windows; to
    # `ntpath` it is rooted but drive-less, so `realpath` anchors it onto the
    # current drive as the fabricated `C:/c/Users/<u>`, and the identity,
    # ancestor and containment compares against the drive-spelled home and
    # repo root all miss -- home and every repo ancestor fell to the clearable
    # tier in that spelling while `C:/Users/<u>` and `~` were refused (walk 2,
    # driven). The depth rule in `_target_is_catastrophic` is deliberately NOT
    # the fix: it reads the path as TYPED, and lowering its threshold would
    # re-refuse the `<repo>/build` class the 2026-08-24 re-tier released.
    # Windows-only, and the one helper the write-guard chokepoint uses, so the
    # two spellings cannot drift apart between the guards.
    return posixpath.normpath(
        os.path.realpath(
            _hook_utils._msys_drive_to_windows(path.replace("\\", "/"))
        ).replace("\\", "/")
    )


# `C:/...` (drive-absolute) and `//server/share` (UNC) are ABSOLUTE, and a bare
# leading-slash test reads them as relative. That is not academic: the home
# records are reached by expanding a tilde, and `os.path.expanduser` returns a
# drive path on Windows -- so the leading-slash test dropped the newly added
# home rows out of the hard tier entirely, and a recursive force-delete aimed
# at the home directory fell back to the clearable soft nudge. The
# POSIX-shaped assumption held for the rule this replaced, whose absolute test
# expanded nothing; expanding a tilde is exactly what routes a target into the
# drive form.
_DRIVE_OR_UNC_ABSOLUTE_RE = re.compile(r"^(?:[A-Za-z]:/|//)")


def _is_unbounded_glob(component: str) -> bool:
    """A path component that names every entry of the directory it expands
    in: nothing but ``*`` and ``?`` with at least one ``*`` (``**`` too: bash
    reads it as ``*`` without ``globstar`` and as a deeper walk with it;
    ``?*`` is every name of one character or more -- the review's item 9).
    Question marks alone name a length, a bounded set."""
    return "*" in component and not component.strip("*?")


def _target_is_catastrophic(
    norm: str, root: str | None, base: str | None = None, *, net: bool = False,
) -> bool:
    r"""Is this resolved delete target catastrophic, by MEANING?

    ⚠ THIS REPLACED A FIRST-CHARACTER TEST, AND THE TEST WAS ANTI-CORRELATED WITH
    DANGER. The old rule was ``norm.startswith("/") or norm.startswith("*")``,
    which made the one UNBYPASSABLE tier fire on `<repo>/build`, on `/tmp/x`, on
    the session's own mandated absolute scratchpad, and on `*.egg-info` — while
    `rm -rf ~` and `rm -rf $HOME`, which really do wipe a home directory, were
    merely relative-looking and fell to a nudge the actor clears by re-issuing.
    Measured on matched pairs: 12 rows too strict, 2 too lax. Re-tiered on the
    operator's decision, 2026-08-24.

    Catastrophic means: the filesystem root, anything that IS or CONTAINS
    `$HOME` or the repo, or a shallow path outside all of them (so `/etc`,
    `/usr`, `/bin` stay refused). A bare unbounded glob is judged AS the
    directory it expands in and `$PWD` as the directory the command runs in
    (DEF-849, DEF-843) -- so each walls where that directory is one of these,
    and from nowhere a bare leading glob walls as it always did. Everything else — including
    every path *inside* the repo or *inside* `$HOME`, and anything under a temp
    root — falls to CP-RMRF's deny-once-then-allow nudge, which is the tier that
    already owns "you probably meant this, confirm it".

    ⚠ NOT POSIX-ONLY, though the rule this replaced was. The absolute test
    admits `C:/...` and `//server/share` as well as a leading `/`, because
    expanding a tilde produces a drive path on Windows and the home records
    are worthless without it. A backslash-spelled `C:\...` still does not
    arrive here -- bash quote-removal collapses it -- and that spelling remains
    the PowerShell leg's to own.

    ``base`` (DEF-790) is the directory the command runs in -- the payload
    ``cwd`` moved by the command's own ``cd`` chain, the same base the
    protected-write checks read (DEF-509). A RELATIVE target is joined to it
    and then judged by the rules above, so ``cd .. && rm -rf <repo>`` names
    the repo and ``cd / && rm -rf etc`` a shallow system path; without a base
    a relative target is the soft tier's, as it was for every caller until
    2026-09-13.
    """
    if not norm:
        return False
    match = _HOME_PREFIX_RE.match(norm)
    expanded = (os.path.expanduser("~") + norm[match.end():]) if match else norm
    expanded = expanded.replace("\\", "/")
    # `$PWD` is the directory the command runs in (DEF-843): until 2026-09-18
    # it was read as a relative name inside that directory, so the checkout
    # removed through `$PWD` from its root drew the nudge where its plain
    # spelling walls. With nowhere to stand it keeps that reading. Read as
    # `.`, so the lexical join below resolves a parent step after it (the
    # review's item 7): the base spliced in whole made an absolute path with a
    # `..` in it, which the traversal rule walls even inside the checkout.
    pwd = _PWD_PREFIX_RE.match(expanded)
    if pwd and base is not None:
        expanded = "." + expanded[pwd.end():]
    elif pwd and not expanded[pwd.end():].strip("/*"):
        # nowhere to stand: the directory itself (or everything in it) is
        # judged as a bare glob from nowhere is -- the wall, except in the
        # net, whose placed pass judged it (the lane's review: the deny texts
        # give the glob and `$PWD` one rule)
        return not net

    # An UNBOUNDED glob can name anything in the directory it expands in, so
    # it is judged AS that directory (DEF-849, DEF-843): a leading one (`*`,
    # `*/x`) is the directory the command runs in, a trailing one (`<dir>/*`,
    # `/*`) is `<dir>`. Until 2026-09-18 a leading glob was catastrophic
    # wherever it ran -- clearing a build directory's contents from inside it
    # met the wall -- while the same wipe spelled by its absolute root
    # (`<repo>/*`, `~/*`) read as a path INSIDE the checkout or the home and
    # drew the nudge. A BOUNDED glob (`*.egg-info`) names a suffix, not
    # everything, and stays a path: refusing it was pure friction.
    parts = (expanded.rstrip("/") or expanded).split("/")
    if _is_unbounded_glob(parts[0]):
        if base is None:
            # Nowhere to stand: the wall, as it always was -- except in the
            # net under a directory walk (``net``), whose placed pass already
            # judged this glob in the directory its statement runs in.
            return not net
        if len(parts) == 1:
            # Separator-normalised like the operand above it was: the base is
            # the hook payload's cwd, backslash-spelled on every Windows host,
            # and spliced in raw it failed the drive-absolute test below, was
            # joined under itself as if relative, and `rm -rf *` at the
            # checkout root drew the nudge instead of the wall -- 45 of the 61
            # reds on the first Portability run to finish the suite on
            # windows-latest (2026-09-23), reproduced with the spelling alone.
            expanded = base.replace("\\", "/")
        # ... and only a BARE glob is that directory (the review's item 6): one
        # followed by more path names that path under each entry, so it joins
        # below as a literal component and parent steps resolve -- `*/build`
        # is inside the checkout, as `./*/build` read; `*/..` is the base.
    elif len(parts) > 1 and _is_unbounded_glob(parts[-1]):
        expanded = "/".join(parts[:-1]) + "/"
    if not (expanded.startswith("/") or _DRIVE_OR_UNC_ABSOLUTE_RE.match(expanded)):
        if base is None:
            return False                  # relative, nowhere to stand -> the soft tier owns it
        # Joined LEXICALLY (operator decision, 2026-09-13): `../scratch` typed
        # at the root lands beside the repo and stays soft, `../<repo>` lands
        # on it and is a wall -- the reading the chain already gives `cd ..`.
        # A symlink crossed by a `..` can land elsewhere on disk; the soft
        # tier still fires there. The `..` rule below then sees none, and the
        # containment test resolves symlinks as it always did.
        expanded = posixpath.normpath(posixpath.join(
            base.replace("\\", "/").rstrip("/") or "/", expanded,
        ))

    if ".." in expanded.split("/"):
        return True                       # unresolvable traversal -> fail closed

    # TWO forms, and the split is load-bearing. Identity/containment must compare
    # symlink-RESOLVED paths or `/tmp` never equals `/private/tmp`. But "is this a
    # shallow system path" is a question about the path as TYPED: macOS resolves
    # `/etc` to `/private/etc`, so judging depth on the resolved form silently
    # demoted `/etc/passwd` from depth 2 to depth 3 and stopped refusing it.
    literal = posixpath.normpath(expanded)
    target = _posix(expanded)
    if target == "/" or literal == "/":
        return True

    sensitive = [_posix(os.path.expanduser("~"))]
    if root:
        sensitive.append(_posix(str(root)))
    # (a) the target IS home/the repo, or is an ANCESTOR of one -> catastrophic.
    # ⚠ THIS OUTRANKS THE TEMP CARVE-OUT BELOW, deliberately. A repo checked out
    # under a temp root (CI runners and this project's own driven-install
    # fixtures do exactly that) would otherwise have `rm -rf <the repo>` waved
    # through as "scratch by construction". An explicit identity match must beat
    # a location heuristic.
    for site in sensitive:
        if target == site or site.startswith(target.rstrip("/") + "/"):
            return True
    if any(target == _posix(t) or target.startswith(_posix(t) + "/")
           for t in _TEMP_ROOTS):
        return False                      # scratch by construction
    # (b) the target is strictly INSIDE home or the repo -> recoverable, soft tier
    for site in sensitive:
        if target.startswith(site.rstrip("/") + "/"):
            return False
    # (c) absolute, outside home / repo / temp: shallow means system-level.
    # Judged on whichever form is SHALLOWER — failing toward the refusal, since a
    # symlink that lengthens a path must not be able to buy leniency.
    return min(
        len([c for c in literal.split("/") if c]),
        len([c for c in target.split("/") if c]),
    ) <= 2


def _operand_can_be_catastrophic(
    token: str, budget: list[int] | None = None, root: str | None = None,
    base: str | None = None, *, net: bool = False,
) -> bool:
    r"""True if the shell can brace-expand + quote-remove ``token`` into an
    argument that STARTS WITH ``/`` (absolute) or ``*`` (leading glob).

    STRUCTURAL, not enumerative: it asks "can the leading character be ``/``/``*``?"
    by walking the brace structure, so it is immune to the cartesian blowup AND
    the cap-truncation evasion that sink an enumerate-then-check approach. An
    enumerate-then-check approach can be padded (``{/,x}{,0,1,...,256}`` past a
    256-result cap so the bare ``/`` is generated then DISCARDED) -- this never
    enumerates, so there is no cap to pad past. Recursion is deduped per distinct
    ``alt+suffix`` and bounded by ``_BRACE_ANALYSIS_BUDGET``; on exhaustion it
    FAILS CLOSED (returns True -- the hard-deny is safety, so an
    unanalyzably-complex operand is denied, not waved through)."""
    if budget is None:
        budget = [_BRACE_ANALYSIS_BUDGET]
    budget[0] -= 1
    if budget[0] <= 0:
        return True  # too complex to analyze -> fail closed (safety, not friction)
    group = _first_brace_group(token)
    if group is None:
        return _target_is_catastrophic(_shell_unquote(token), root, base, net=net)
    lo, hi, alts = group
    raw_prefix = token[:lo]
    prefix = _shell_unquote(raw_prefix)
    suffix = token[hi + 1:]
    if prefix and ".." not in token[lo:] and not _target_is_catastrophic(
        prefix, root, base, net=net,
    ) and (prefix.endswith("/") or not _brace_prefix_completes_a_site(prefix, root, base)):
        # FAST PATH: a prefix that ends at a separator fixes the leading path
        # and the braces can only go DEEPER. One that stops mid-name completes
        # that name into SIBLINGS, and a sibling can be the home or the
        # checkout itself (`<checkout minus a letter>{<letter>,}`; the review's
        # item 8) -- the one way a sibling of a harmless name is not harmless,
        # so only then do the expansions get probed
        # (`_brace_prefix_completes_a_site`). And nothing deeper than a target that is not
        # catastrophic can be one (the rules are monotone going down: inside
        # a temp root, the home or the checkout stays inside; a depth only
        # grows). So a prefix that is NOT catastrophic answers for every
        # expansion. One that IS falls through to the expansions: until
        # 2026-09-18 its answer stood for them too, so the checkout's own
        # path, `./` or `~/` before a brace list of subdirectories walled as
        # if the whole directory were the target -- the class DEF-849 and
        # DEF-843 name, one analysis up.
        #
        # ⚠ NOT taken when the braces contain `..`, because then they can climb
        # back OUT: `<repo>/build{/../../..}` has a prefix that is safely inside
        # the repo and an expansion that is not. Falling through expands each
        # alternative and resolves it properly, which is strictly better than the
        # first cut of this guard -- that returned True outright and false-fired
        # on `x{.../}etc`, where `..` is bash's RANGE operator, not a parent
        # directory. A `..` test on raw brace text cannot tell those apart;
        # expanding first makes the question disappear.
        return False
    # Probe each expansion, deduped (``{,}`` has two identical empty alts -> probe
    # the suffix once). The RAW prefix is carried so quoting is resolved once, at
    # the leaf, rather than twice.
    seen: set[str] = set()
    for alt in alts:
        key = raw_prefix + alt + suffix
        if key in seen:
            continue
        seen.add(key)
        if _operand_can_be_catastrophic(key, budget, root, base, net=net):
            return True
    return False


def _brace_prefix_completes_a_site(prefix: str, root: str | None, base: str | None) -> bool:
    """Can a brace list right after ``prefix`` -- which stops mid-name --
    complete that name into the home directory or the checkout? True when
    one of them sits in the prefix's directory under a name that starts
    with the prefix's partial one, read by `_target_is_catastrophic`'s own
    resolution (the home by `~`, a relative prefix joined to ``base``) in
    both the typed and the symlink-resolved form. A relative prefix with
    nowhere to stand names no site (the soft tier's, every expansion); a
    `$PWD` one is probed rather than read."""
    m = _HOME_PREFIX_RE.match(prefix)
    p = ((os.path.expanduser("~") + prefix[m.end():]) if m else prefix).replace("\\", "/")
    if _PWD_PREFIX_RE.match(p):
        return True
    if not (p.startswith("/") or _DRIVE_OR_UNC_ABSOLUTE_RE.match(p)):
        if base is None:
            return False
        p = posixpath.join(base.replace("\\", "/").rstrip("/") or "/", p)
    forms = {posixpath.normpath(p), _posix(p)}
    sites = [os.path.expanduser("~")] + ([str(root)] if root else [])
    return any(
        s.startswith(f) and "/" not in s[len(f):]
        for site in sites for s in {posixpath.normpath(site.replace("\\", "/")), _posix(site)}
        for f in forms
    )


def _shell_word_spans(text: str) -> list[str] | None:
    r"""``text`` split into bash WORDS, each returned RAW -- quotes and
    escapes kept -- or ``None`` when a quote opened in ``text`` does not
    close in it (DEF-843).

    A blank ends a word only outside quotes: a single-quoted span, a
    double-quoted span (a backslash escapes inside it), an ANSI-C ``$'...'``
    span (likewise) and a backslash-escaped character are all part of the
    word they touch, so a quoted operand holding a blank is ONE word, as the
    shell hands it over. The blank set is `str.isspace`'s, the set the
    whitespace split this replaced used, so the only change from that split
    is that quoting and escaping now glue.

    ``None`` is the caller's cue to keep the whitespace split: an
    unterminated quote in a segment means the segment is not self-contained
    (its quotes belong to a string around it, as when a shell is handed the
    text to re-parse), and pairing them anyway would read a word the shell
    never forms. Linear: each quote is closed by one forward scan, and the
    first one that does not close ends the read."""
    words: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        j = i
        while j < n and not text[j].isspace():
            c = text[j]
            if c == "\\":
                j += 2                    # the escaped character, a blank too
                continue
            if c == "$" and text[j + 1:j + 2] == "'":
                k = j + 2
                while k < n and text[k] != "'":
                    k += 2 if text[k] == "\\" else 1
                if k >= n:
                    return None
                j = k + 1
                continue
            if c == "'":
                k = text.find("'", j + 1)
                if k < 0:
                    return None
                j = k + 1
                continue
            if c == '"':
                try:
                    j = _close_double_quote(text, j) + 1
                except _UnresolvedShellSyntax:
                    return None
                continue
            j += 1
        words.append(text[i:min(j, n)])
        i = j
    return words


def rm_recursive_force_operands(
    segment: str, *, words: bool = True,
) -> tuple[bool, bool, list[str]]:
    """Tokenize one ``rm ...`` segment -> ``(recursive?, force?, [operands])``.

    Only dash-prefixed WORDS are treated as flags, so an ``-r`` inside an
    operand (``my-report/``) never trips recursion. A word is judged as rm
    receives it (quote-removed), so a quoted flag is a flag. Short flags are
    character-bundled in any order (``-rf``, ``-fr``, ``-rvf``, ``-R``); long
    flags ``--recursive`` / ``--force`` and their unambiguous GNU
    abbreviations (``--rec``, ``--f``) set the bit; any other long flag
    (``--one-file-system``) is ignored. A bare ``--`` ends option parsing:
    every word after it is an operand, however it starts.
    Operands are returned RAW -- the hard-deny applies brace + quote
    analysis structurally via ``_operand_can_be_catastrophic``; the CP-RMRF soft
    bump shell-unquotes them itself for its safe-prefix check.

    ``words`` (DEF-843): split quote-aware (`_shell_word_spans`), so a quoted
    operand holding a blank is one operand -- the whitespace split read the
    second half of such a word as an operand of its own and walled a path
    the shell never names. The caller passes ``False`` when the segment is
    not self-contained (`iter_rm_invocations`: it starts inside a quote), and
    a segment with an unterminated quote falls back on its own; both keep
    the whitespace split, the reading every caller had before.

    Single source of truth: write_guard's hard-deny
    (``has_catastrophic_recursive_rm``) and the CP-RMRF soft speed-bump both
    consume this -- one tokenizer, no drift between the two tiers.
    """
    recursive = force = False
    operands: list[str] = []
    tokens = (_shell_word_spans(segment) if words else None) or segment.split()
    end_of_options = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        text = _shell_unquote(token)
        if text.lower() == "rm":  # command token; also skips RM on case-insens FS
            continue
        # ⚠ A REDIRECTION IS NOT A DELETE TARGET. `rm -rf build 2> /dev/null`
        # tokenizes to ['build', '2>', '/dev/null'], and `/dev/null` is an
        # ABSOLUTE path, so `_operand_can_be_catastrophic` fired and the command
        # was HARD-DENIED -- an unbypassable wall (this tier dispatches ahead of
        # the maintenance gate) on an ordinary build clean. The glued spelling
        # `2>/dev/null` became the single operand `2>/dev/null`, which is not
        # absolute, so it escaped the hard tier but still failed CP-RMRF's
        # ephemeral-dir allowlist and earned a soft bump. Two spellings of one
        # command, two different verdicts, neither of them right.
        #
        # Shape mirrors the existing `_CMD_POS_REDIRECT` fragment: an optional fd
        # number, the operator, then a target that is either GLUED to the operator
        # or is the following token. `2>&1` and `>&2` are glued and consume nothing
        # extra; a bare `>` or `2>` consumes the next token as its target.
        redirect = _REDIRECT_OPERATOR_RE.match(token)
        if redirect:
            if redirect.end() == len(token):
                index += 1        # bare operator: the next token is ITS target
            continue              # else the target was glued on; nothing extra
        if end_of_options:
            operands.append(token)
            continue
        if text == "--":
            end_of_options = True
            continue
        if text.startswith("--"):
            # GNU getopt takes any unambiguous prefix of a long option; among
            # rm's, `--r...` can only be --recursive and `--f...` --force
            if len(text) > 2 and "--recursive".startswith(text):
                recursive = True
            elif len(text) > 2 and "--force".startswith(text):
                force = True
            # any other long flag is irrelevant to the gate
            continue
        if text.startswith("-") and len(text) > 1:
            body = text[1:]
            if "r" in body or "R" in body:
                recursive = True
            if "f" in body:
                force = True
            continue
        operands.append(token)
    return recursive, force, operands


# The OPERATOR half of a redirection token: optional fd, then the operator.
# Deliberately does NOT capture the target -- a `(?P<target>.*)$` tail is an
# unbounded dot-quantifier on the PreToolUse hot path and
# tests/test_redos.py::test_no_unreviewed_dotstar_in_hook_regexes reds on it.
# Whether the target is GLUED (`2>/dev/null`, `2>&1`) or absent (`2>`, target is
# the next token) is read from whether the match consumed the whole token, which
# needs no capture and stays linear. Anchored at token start so a filename that
# merely contains `>` is never mistaken for a redirect.
_REDIRECT_OPERATOR_RE = re.compile(r"^[0-9]*(?:&>>?|>>?&?|<<?&?)")

#: WARNING: NO `\r?` HERE, AND THAT IS MEASURED. A bash line continuation is a
#: backslash immediately followed by a newline. With CRLF the backslash escapes
#: the CARRIAGE RETURN and the newline stays a LIVE statement separator --
#: driven against /bin/bash, `echo a\<CR><LF><delete> victim` printed `a` and
#: deleted the victim. Splicing that away joined the two statements and the
#: guard returned ALLOW. Windows operators are the population that produces
#: CRLF, so this fired exactly where it was least likely to be noticed.
_LINE_CONTINUATION_RE = re.compile(r"\\(\r?)\n")
#: A heredoc operator (not a here-string's `<<<`), found on a line's
#: quote-blanked twin by the splicer so it can leave a quoted body alone.
_HEREDOC_OPERATOR_RE = re.compile(r"(?<!<)<<(?!<)")


def _splice_replacement(match: "re.Match[str]") -> str:
    """A CRLF continuation is NOT one, so it collapses to a SEPARATOR.

    Driven against /bin/bash and read back with `od -c`:
    `echo a\\<CR><LF>echo b` emits `a \\r \\n b` -- two commands, because the
    backslash escaped the CARRIAGE RETURN and the newline stayed live. Joining
    the lines therefore invents a statement bash never runs, and it cost a
    fail-open: `echo a\\<CR><LF><delete> /` really deleted and the guard, seeing
    one spliced `echo`, allowed it.

    Dropping the escaped CR while KEEPING the newline is what serves both
    consumers: the delete stays at a command position and stays denied, and the
    env-prefix detector still sees `VAR=1` and the launch on the next line
    rather than a trailing backslash it reads as a command word.
    """
    return "\n" if match.group(1) else ""


def splice_line_continuations(command: str) -> str:
    r"""The Bash readers' ONE raw pre-pass: `_splice_line_continuations`
    (its docstring is the contract -- the order rule, the heredoc rule), then
    `_resolve_bash_discovered_heads` over the spliced text (DEF-827), so a
    command the shell discovered and invoked at a command position
    (`$(which find) . -delete`) reads as the command it names on every
    anchored head. Here and not in the masker, because every reader derives
    both of its texts from this one pass -- the offset readers splice the
    raw text before masking, the search-only readers splice the masked text
    -- and a span read from the RAW text by offset must not meet the
    substitution's close paren: the first cut resolved the masked text alone,
    and every arm whose span begins at the blank after the verb read
    `) -a <hook>`, which `_strip_span_tail` cuts at the unmatched close --
    nine of the roster's thirty-six arms allowed the discovered spelling
    beside a denied bare one (driven). The resolver moves nothing and keeps
    length; the splice is the stage that shortens. The resolver is
    heredoc-BLIND on purpose: it rewrites a quoted-delimiter body the
    splicer left alone, which is right for a body a re-parser runs (`bash
    <<'EOF'`, sliced from this spliced text by `_shell_program_bodies`) and
    inert for a data body, which the masker blanks afterwards."""
    return _resolve_bash_discovered_heads(_splice_line_continuations(command))


def _splice_line_continuations(command: str) -> str:
    r"""Join physical lines a trailing backslash continues, into logical ones.

    ⚠ Callers want the public `splice_line_continuations`: this one does NOT
    resolve a discovered head (DEF-827), and a reader built on it alone
    reads `$(which find) . -delete` as `which`'s.

    A ``\`` at end of line means the next physical line is a CONTINUATION of this
    statement, not a new one. Any consumer that segments on newlines must splice
    first or it will read one statement as two — and both failure directions are
    attested here:

    * ``iter_rm_invocations`` splices so ``rm -rf \<nl>/`` is seen as
      ``rm -rf /`` rather than a flagless ``rm -rf`` with no operand.
    * ``write_guard._occurrence_is_benign`` did NOT splice, so
      ``VAR=1 \<nl>claude`` split into ``1 \``, whose trailing backslash passed
      as a command word — the occurrence was judged benign and the agent launch
      on the following line was never inspected (a BC-028 bypass class,
      benchmark green throughout).

    ONE owner for the concept, per this folder's contract: a second inline
    ``re.sub`` in the other caller is exactly the divergent copy the
    concept-overlap probe flags, and the two sites had already drifted (one
    spliced, one did not). ``iter_hardlink_operands`` carried a third copy that
    joined a CRLF pseudo-continuation; it uses this function now (DEF-701).

    THE ORDER RULE, since two orders exist on purpose. Splice BEFORE masking
    when a downstream reader slices by offset into the raw string -- the masked
    and raw texts must then derive from one spliced text (``_candidate_paths_
    from_bash``, whose stdin-program arm reads both; ``_secret_read_targets``,
    whose heredoc cut indexes the raw text by a masked offset). Splice AFTER
    masking when the reader only searches the result -- splice-first joins a
    heredoc body line ending in ``\`` to its terminator and breaks terminator
    detection, so the mask should see the original lines (``iter_rm_
    invocations``, ``check_bash_dangerous_patterns``, ``_speedbump._masked_
    command``). Legs with no mask splice the raw text (``check_bash_for_
    protected_symlinks``, ``iter_hardlink_operands``, ``_is_writing_bash``).

    ⚠ A QUOTED-DELIMITER HEREDOC BODY IS NOT SPLICED (2026-09-11, the Bash
    trio's third step). bash keeps a backslash-newline inside such a body --
    driven with a marker: ``cat <<'EOF'``, a body line ending in ``\``, the
    terminator, then a ``touch`` -- the marker appeared, so the statement
    after the terminator RUNS. Joining that line to its terminator loses the
    terminator, and when a later line spells the delimiter again the walker
    closes the body THERE and masks every live statement between: a copy
    into a hook behind ``cat`` was allowed at c7b46b9, and behind ``python3``
    the moment it became a reader head. An UNQUOTED body is spliced as
    before, which is what bash does with the pair there (driven: the same
    shape unquoted ran nothing). The operators are read outside quotes and
    comments (``_pipe_scan``), so a quoted mention of ``<<EOF`` opens no body.
    """
    if "\\" not in command:
        return command
    lines = command.split("\n")
    parts: list[str] = []
    #: (delimiter, quoted, strip_tabs) of every heredoc opened on the logical
    #: line being assembled; their bodies begin once that line ends.
    queue: list[tuple[str, bool, bool]] = []
    body: tuple[str, bool, bool] | None = None
    #: The previous body line was joined to this one (an unquoted body's
    #: backslash-newline): bash reads the two as ONE line, so this physical
    #: line cannot be the terminator -- `x\` + newline + `EOF` is the body
    #: line `xEOF`, and the delimiter is still open (driven with a marker).
    continued = False
    #: The operators are read on the WHOLE command's quote-blanked twin,
    #: sliced per line by offset (`_pipe_scan` keeps the length), never on a
    #: line's own: a quoted span that opened on an earlier line hid nothing
    #: from a per-line scan, so a heredoc operator mentioned inside a
    #: multi-line commit message opened a body that never closed and no
    #: continuation after it was spliced again (both reviews, driven with a
    #: marker into a hook).
    scan = _pipe_scan(command)
    last = len(lines) - 1
    offset = 0
    for idx, line in enumerate(lines):
        scan_line = scan[offset:offset + len(line)]
        offset += len(line) + 1
        if body is not None:
            delim, quoted, strip = body
            probe = line.lstrip("\t") if strip else line
            if not continued and probe.rstrip("\r").strip() == delim:
                body = queue.pop(0) if queue else None
                parts.append(line)
            elif quoted:
                parts.append(line)
                continued = False
            else:
                text, joined = _spliced_line(line, idx == last)
                parts.append(text)
                continued = joined
                if joined and idx < last:
                    continue
            if idx < last:
                parts.append("\n")
            continue
        for op in _HEREDOC_OPERATOR_RE.finditer(scan_line):
            try:
                _, spec = _read_heredoc_operator(line, op.start())
            except _UnresolvedShellSyntax:
                spec = None
            if spec is not None:
                queue.append((spec[0], not spec[1], spec[2]))
        text, joined = _spliced_line(line, idx == last)
        parts.append(text)
        if joined and idx < last:
            continue
        if idx < last:
            parts.append("\n")
        if queue:
            body = queue.pop(0)
    return "".join(parts)


def _continuation(line: str) -> str | None:
    """How a physical line ends: ``"join"`` when an ODD run of backslashes
    precedes the newline (bash joins the next line), ``"cr"`` when that run
    precedes a carriage return instead (bash escapes the CR: the backslash
    and the CR go, the newline stays a separator), None when the line does
    not continue -- an even run is a literal backslash and the next line is
    its own (the failure-mode review drove the even run: bash closed the
    heredoc on the next line and ran the statement after it)."""
    body = line[:-1] if line.endswith("\r") else line
    run = len(body) - len(body.rstrip("\\"))
    if run % 2 == 0:
        return None
    return "cr" if line.endswith("\r") else "join"


def _spliced_line(line: str, last: bool) -> tuple[str, bool]:
    """A physical line with its continuation resolved: ``(text, joined)`` --
    the text to emit, and whether the newline after it is consumed. The last
    line of the input has no newline after it, so nothing there is a
    continuation (the regex this replaced required the newline too)."""
    kind = None if last else _continuation(line)
    if kind == "join":
        return line[:-1], True
    if kind == "cr":
        return line[:-2], False
    return line, False


def iter_rm_invocations(
    command: str, *, start_quote: str | None = None,
) -> Iterator[tuple[bool, bool, list[str]]]:
    r"""Yield ``(recursive, force, operands)`` for each ``rm`` segment in
    ``command`` after splicing backslash-newline line continuations (a ``\`` at
    end of a physical line joins the next -- ``rm -rf \<nl>/`` is ``rm -rf /``;
    ``rm -r\<nl>f /`` is ``rm -rf /``). Segments are bounded by ``; | &`` and
    newlines. Both write_guard's hard-deny and CP-RMRF iterate this, so the two
    tiers see identical rm invocations (one SoT, no drift).

    ⚠ SAFETY TIER. Input is role-mapped first (`mask_inert_syntax`) so a delete
    MENTIONED inside a quoted span, a `#` comment or a `<<'EOF'` body is no longer
    segmented as an invocation -- that false positive is unbypassable, since this
    path runs even under ESPALIER_MAINTENANCE_MODE=1, so its only remaining remedy
    was `disableAllHooks`. The mask substitutes separator characters ONLY and never
    token content, which is what keeps every quote-splice class
    (`rm -r"f" /`, `"rm" -rf /`, `rm'' -rf /`, `\rm -rf /`) denied. Masking runs
    BEFORE splicing: splice-first would join heredoc body lines and break
    terminator detection. ⚠ `_candidate_paths_from_bash` deliberately does the
    REVERSE (splice, then mask) because it reads a masked and a raw string
    against each other by offset; this function only searches, so the order
    that protects the terminator wins here. See the note at that call site.
    """
    for recursive, force, operands, _in_string in _iter_rm_invocations_placed(
            command, start_quote):
        yield recursive, force, operands


def _iter_rm_invocations_placed(
    command: str, start_quote: str | None = None,
) -> Iterator[tuple[bool, bool, list[str], bool]]:
    """`iter_rm_invocations` with a fourth field: is the segment's verb
    inside a string handed to another program (not a quoted verb)? That
    delete runs wherever the program puts it -- another shell's `cd`, a
    remote home over `ssh`, each submodule under `git submodule foreach` --
    so the wall adds the unknown directory to its bases (blocker
    condition 2)."""
    spliced = splice_line_continuations(mask_inert_syntax(command))
    # ``start_quote``: a statement slice that starts inside a string another
    # shell re-parses (`_statement_start_quotes`) is read from that quote
    quote_at = _quote_cursor(spliced, start_quote)
    for match in _RM_SEGMENT_RE.finditer(spliced):
        # `seg` starts at the verb; group(0) would include the command-position
        # prefix and the tokenizer would read `sudo`/`env` as delete operands.
        seg = match.group("seg")
        # DEF-843: the words are read quote-aware only when the segment is
        # self-contained. A verb inside a quote is either a quoted verb (the
        # quote closes right after it: read the rest as words) or text a
        # shell is handed to re-parse, whose quotes belong to the string
        # around it -- there the whitespace split every caller had stands.
        quote = quote_at(match.start("seg"))
        if quote is None:
            yield (*rm_recursive_force_operands(seg), False)
        elif seg[2:3] == _QUOTE_CLOSER[quote]:
            yield (*rm_recursive_force_operands(seg[:2] + seg[3:]), False)
        else:
            yield (*rm_recursive_force_operands(seg, words=False), True)


#: The character that closes each quote `_quote_cursor` can be inside.
_QUOTE_CLOSER = {"'": "'", '"': '"', "$'": "'"}


def _quote_cursor(text: str, start: str | None = None) -> "Callable[[int], str | None]":
    r"""``at(i) -> quote``: the quote ``text`` is inside at offset ``i`` --
    ``"'"``, ``'"'``, ``"$'"`` or ``None`` -- read by the rules
    `_shell_word_spans` splits on (a backslash escapes outside a single
    quote), from ``start``: the quote the text's first character is already
    inside, for a slice cut out of a longer text (`_statement_start_quotes`).
    Offsets must be asked in increasing order: the cursor resumes where the
    last ask stopped, so a flood of segments costs one pass over the text,
    never one per segment. A `#` that begins a word outside a quote runs to
    the newline, as the shell reads a comment: an apostrophe in one flipped
    the cursor and read a string's segment quote-aware (code review). A
    heredoc body is not modelled."""
    pos = 0
    inside: str | None = start

    def at(target: int) -> str | None:
        nonlocal pos, inside
        i, quote = pos, inside
        while i < target:
            c = text[i]
            if quote is None:
                if c == "\\":
                    i += 2
                    continue
                if c == "#" and (i == 0 or text[i - 1] in " \t\n;&|()"):
                    newline = text.find("\n", i)
                    i = len(text) if newline < 0 else newline
                    continue
                if c == "$" and text[i + 1:i + 2] == "'":
                    quote = "$'"
                    i += 2
                    continue
                if c in "'\"":
                    quote = c
            elif quote == "'":
                if c == "'":
                    quote = None
            else:
                if c == "\\":
                    i += 2
                    continue
                if c == _QUOTE_CLOSER[quote]:
                    quote = None
            i += 1
        pos, inside = i, quote
        return quote

    return at


def _ps_quote_cursor(raw: str) -> "Callable[[int], tuple[int, int, str] | None]":
    """``at(i) -> (open, close, kind)``: the PowerShell string ``raw`` is
    inside at offset ``i``, strictly between its quotes, else ``None`` -- the
    twin of `_quote_cursor`, read by the masker's OWN walk
    (`_walk_powershell_spans`' ``spans``) so the two cannot disagree: a
    backtick escapes outside a single quote, a doubled quote stays inside,
    a here-string closes only at a column-0 terminator, a ``$( )``
    subexpression's quotes are its own, a comment opens nothing. ``raw`` is
    the RAW half of `powershell_scan_pair`, which indexes the scan: in a
    re-parsed double-quoted program the scan blanks the escaping backtick
    and keeps the quote it escaped. The closing offset answers the
    quoted-VERB question exactly (a string that closes where the verb ends
    is the verb's own quote). Any order of asks; the spans are read on the
    first. A command the masker cannot read (an unterminated string, past
    the length cap) has no spans: every offset reads as outside, the
    reading every caller had."""
    spans: list[tuple[int, int, str]] | None = None
    opens: list[int] = []

    def at(i: int) -> "tuple[int, int, str] | None":
        nonlocal spans
        if spans is None:
            spans = []
            if raw and len(raw) <= _ROLE_MAP_CAP:
                try:
                    _walk_powershell_spans(raw, spans)
                except (_UnresolvedShellSyntax, IndexError):
                    spans = []
            opens.extend(s[0] for s in spans)
        k = bisect.bisect_left(opens, i) - 1
        if k >= 0 and spans[k][0] < i < spans[k][1]:
            return spans[k]
        return None

    return at


def _statement_start_quotes(
    text: str, statements: list[tuple[int, int, tuple[str | None, ...]]],
) -> list[str | None]:
    """The quote each statement of a directory walk STARTS inside, one per
    statement, off the walk's own ``text`` (blocker condition 2). The masker
    leaves a program handed to `bash -c` raw so its delete is read, which
    lets the walk split statements INSIDE that string; such a statement is
    another shell's, and its slice must be read from the quote it starts in
    (`iter_rm_invocations`' ``start_quote``) -- restarting outside a quote
    paired the program's closing quote with a later argument's opening one."""
    at = _quote_cursor(text)
    return [at(s) for s, _e, _dirs in statements]


def has_catastrophic_recursive_rm(
    command: str, root: str | None = None,
    cwd: "str | os.PathLike[str] | None" = None,
) -> bool:
    r"""True if any ``rm`` invocation in ``command`` is a recursive delete,
    forced or not, whose POST-TRANSFORM target is catastrophic BY MEANING --
    see :func:`_target_is_catastrophic` -- in ANY flag order, spelling,
    quoting, escaping, brace, line-continuation, or command-case form.

    Recursion alone is the threshold (DEF-842). rm prompts only for a file
    whose permissions do not permit writing, and only when stdin is a
    terminal, so in an agent's shell ``rm -r`` removes every writable file
    under its target without asking (driven 2026-09-18 on a throwaway with
    no terminal: a read-only file and a dotfile went too, exit 0). Until
    then this read recursive AND force, so the unforced spelling at the
    root, home or the checkout met no tier at all while its own loop, under
    the loop family's one wipe rule, met the wall. The interactive flag is
    not carved out: it asks even without a terminal, but a piped answer
    clears it, and nobody needs it on a catastrophic target.

    The flag-order- AND spelling-independent superset of write_guard's two
    literal ``-rf`` regexes; closes the bypass classes ``rm -fr /``,
    ``rm -rf \/``, ``rm -rf '/'etc``, ``rm -rf {/bin,/etc}``, ``rm -rf \<nl>/``,
    ``RM -rf /``. ``$``-expansions beyond ``$HOME`` and two-step write-then-exec
    remain out of scope (statically undecidable).

    ``root`` is the repo root, optional so the ~37 existing call sites keep
    working unchanged. Supplying it adds one rule: the repo directory itself, and
    any ancestor of it, is catastrophic. WITHOUT it the home and filesystem-root
    rules still apply, so omitting ``root`` narrows coverage rather than
    inverting it -- a caller that cannot supply a root degrades, it does not
    fail open on ``/`` or ``~``.

    ``cwd`` (DEF-790) is the directory the command runs in -- the hook
    payload's, else ``root``. From it the command's own ``cd`` chain is
    walked (`bash_directory_chain`) and EACH DELETE IS READ IN ITS OWN
    STATEMENT'S DIRECTORIES: ``cd .. && rm -rf <repo>`` names the repo, ``cd
    / && rm -rf etc`` a shallow system path, a conditional ``cd`` leaves both
    directories and the delete is refused if either lands on a catastrophic
    target. Pairing is by statement slice, never by searching the operand's
    spelling across the text: the first cut used `statement_directories`,
    whose needle match placed ``cd / ; ls usr ; cd ~ ; rm -rf usr`` at ``/``
    as well as at home and walled a target the soft tier owns (failure-mode
    review, driven, 2026-09-13). A delete the walk does not place -- past the
    scan cap, or when the walk faults -- keeps the reading every caller had
    before the chain: absolute operands by the rules above, relative ones
    the soft tier's. With neither ``cwd`` nor ``root``, that older reading
    for every operand.

    The walk is the one the find classifier shares (`_bash_sweep_walk`,
    whose body this function carried line for line until DEF-846), so a
    literal binding is read here as it is there: a catastrophic
    target named through ``X=/; rm -rf $X`` meets the wall, where it drew
    only the nudge (the snapshot arm, the zone reader and the write
    extractor inlined the binding; this tier read ``$X`` raw)."""
    return _bash_sweep_walk(command, root, cwd, _rm_lands_catastrophic)


def _rm_lands_catastrophic(
    text: str, root: str | None, bases: "list[str | None]",
    start_quote: str | None = None, net: bool = False,
) -> bool:
    """Every recursive delete in ``text``, forced or not (DEF-842), each
    operand judged from each of ``bases``. ``[None]``: from nowhere -- a
    relative operand is the soft tier's, an absolute one the rules', an
    unbounded leading glob the wall. ``net``: the net under a directory
    walk (`_bash_walk_one`) -- the same, except that a leading glob is left
    to the placed pass, which judged it where its statement runs.
    ``start_quote``: the quote a statement slice starts inside
    (`_statement_start_quotes`), so its words are read from there."""
    candidates: list[str | None] = list(bases) or [None]
    for recursive, _force, operands, in_string in _iter_rm_invocations_placed(text, start_quote):
        if not recursive:
            continue
        # a delete handed to another program runs where it puts it: add the
        # unknown directory (a superset; the net keeps its own reading)
        here = candidates + [None] if in_string and not net and None not in candidates else candidates
        for op in operands:
            for base in here:
                if _operand_can_be_catastrophic(op, None, root, base, net=net):
                    return True
    return False


def iter_unnarrowed_find_delete_roots(command: str) -> Iterator[list[str]]:
    """The starting points of every ``find`` in ``command`` that carries a
    delete action and no narrowing predicate -- the roots `_find_delete_roots`
    tags `delete` (DEF-815). Read the way the write extractor reads its
    operands: the opener matched on the masked scan, the span from the raw
    text at the match's offsets (DEF-794), after the cap and the splice. A
    narrowed find (`sweep`) and a `find -exec mv` (`move`) yield nothing
    here: the first is judged by its root alone in the zone check, the
    second is a relocation the zone check reads as one. Uncapped, as
    `iter_rm_invocations` is: the write extractor's head-and-tail cap would
    drop a find in the middle of a long command that the rm twin's net
    still catches (review, driven at 52 KB); the span is bounded by the
    opener and the masker is linear, so the cost is the text's length."""
    command = splice_line_continuations(command)
    scan = mask_inert_syntax(command)
    if len(scan) != len(command):
        scan = command
    for m in _FIND_DELETE_RE.finditer(scan):
        roots, effect = _find_delete_roots(raw_span(command, m))
        if effect == "delete":
            yield roots


def has_catastrophic_find_delete(
    command: str, root: str | None = None,
    cwd: "str | os.PathLike[str] | None" = None,
) -> bool:
    r"""True if any un-narrowed ``find`` with a delete action in ``command``
    starts from a catastrophic root -- :func:`_target_is_catastrophic`, the
    rule `has_catastrophic_recursive_rm` applies to an rm operand -- read
    from the directory the command runs in, moved by its own ``cd`` chain
    (DEF-790), each find placed in its own statement.

    DEF-815: `find . -delete` (and `find -delete`, GNU's default root; `find
    . -exec rm -rf {} +`; `find . -type f -delete`) from the repo root is the
    recursive force-delete of the checkout spelled through an enumerator,
    and until 2026-09-15 no tier saw it: the zone check judges an
    un-narrowed root by what it encloses and the repo root answers False by
    design, this classifier's rule was reached only from the rm-shaped arms,
    and the speed bump had no find predicate -- so the one tier maintenance
    mode never bypasses let the whole tree go, hooks included, while the rm
    spelling of the same wipe was refused with the catastrophic text.

    The roots are judged through `_operand_can_be_catastrophic` (brace and
    quote analysis, fail-closed on an unanalysable operand) from every base
    the chain gives the statement; ``None`` for both ``cwd`` and ``root``
    keeps the reading every caller had -- an absolute root by the rules, a
    relative one the soft tier's. A find whose action is not a remove verb,
    a narrowed find, and a mention inside a quoted span, a comment or a
    heredoc body yield nothing (the opener is command-position anchored on
    the masked scan).

    The directory walk is the cost, and the rm classifier pays it once
    already for every Bash call; this tier walks only when the spliced text
    carries a delete action at all, so a command with no find in it adds
    one linear search and nothing else (the opener-flood budget row in
    tests/test_redos.py sits at eighty percent of its ceiling without this,
    DEF-817). The search runs over the UNCAPPED text: the cap would hide a
    find in the middle of a long command from this tier alone (review)."""
    if not _FIND_DELETE_ACTION_RE.search(splice_line_continuations(command)):
        return False
    return _bash_sweep_walk(command, root, cwd, _find_lands_catastrophic)


@functools.lru_cache(maxsize=64)
def _wall_readings(command: str) -> tuple[str, ...]:
    """The texts the Bash walls judge (DEF-846): the command as spelled and,
    when a literal binding changes it, the command with the
    binding inlined (`_expand_simple_var_assignments` in its walls' mode) --
    the reading the snapshot arm, the zone reader and the write extractor
    already take, with two rules of the walls' own (`_bound_value`). A wall
    on EITHER is the wall, so the inlined reading can only add one: a
    binding the pre-pass cannot read whole is left unbound, and the reading
    as spelled is always judged.

    The inlined reading is of the CAPPED text (`_cap_for_scan`), as the
    other pre-pass consumers' is: the pre-pass costs names times length, and
    on the uncapped text a flood of bindings ran the hook past its timeout
    (both reviews, measured). Cached per text: the four walls and the
    nudge's deferral each ask for the same one."""
    capped = _cap_for_scan(command)
    inlined = _expand_simple_var_assignments(capped, wall=True)
    return (command,) if inlined == capped else (command, inlined)


def _bash_sweep_walk(
    command: str, root: str | None, cwd: "str | os.PathLike[str] | None",
    lands: "Callable[[str, str | None, list[str | None], str | None, bool], bool]",
) -> bool:
    """The directory walk the rm tier and the find classifier share (the
    carrier and loop walls place by offset and loop over `_wall_readings`
    themselves), over every reading `_wall_readings` gives (DEF-846:
    until then the walls read a same-line binding raw, so a catastrophic
    target named through one drew only the nudge). ``lands`` is the arm's
    own judge over one text."""
    return any(_bash_walk_one(text, root, cwd, lands) for text in _wall_readings(command))


#: The Bash grammar's reserved words that open or continue a compound command
#: (the manual's list, less `!`, `time`, `in` and `[[` / `]]`, which open
#: none, and `{` / `}`, which `_CHAIN_BOUNDARY_RE` reads as the group word). A
#: statement that opens with one is not plain (`_relief_applies`).
_BASH_COMPOUND_WORDS = frozenset({
    "case", "coproc", "do", "done", "elif", "else", "esac", "fi", "for",
    "function", "if", "select", "then", "until", "while",
})
#: The only boundaries a plain command joins its statements with.
_PLAIN_JOINERS = frozenset({";", "&&", "||", "\n"})
#: The relief's own verb. `rm` passes the head roster's single test -- it
#: hands no argument to a shell -- but `_NON_REPARSING_HEADS` never took it:
#: that roster gates the MASK, and adding a name there changes what every
#: remove reader sees in a quoted operand, a wider change than this gate. So
#: the gate allows it beside the roster; every other head off it is not plain.
_PLAIN_RELIEF_HEADS = frozenset({"rm"})


@functools.lru_cache(maxsize=8)
def _relief_applies(command: str, *, bash: bool) -> bool:
    """Is ``command`` PLAIN, so the glob relief may read a bare leading glob
    or the location variable as the directory its statement runs in? The
    operator's allowlist (2026-09-19). It replaced a list of the places the
    walk cannot know the directory, which every review round lengthened: a
    list of the cases that are not plain never closes (STANDING_PRINCIPLES
    §15), a description of the ones that are does.

    Plain: statements joined only by `;`, `&&`, `||` or a newline, and
    nothing that groups, substitutes, pipes, backgrounds, reads a heredoc,
    re-parses a string or runs code in this shell the walk cannot read.
    Bash (`_bash_is_plain`): the role walk resolves the command; every head
    is on `_NON_REPARSING_HEADS`, is a reader head (its shell-outs are read
    and judged as another shell's program, and a child process cannot move
    this shell) or is the relief's own verb (`_PLAIN_RELIEF_HEADS`) --
    `eval`, `source`, `.`, the wrappers and the build tools are on none, so
    a clean and a rebuild in one command is not plain; its masked text
    holds no boundary but the joiners and a redirection's `&`, no heredoc
    operator; and no statement opens with a compound reserved word. The
    head set is the operator's strict call (2026-09-19), pinned by
    `test_the_plain_head_set_is_pinned`. PowerShell
    (`_ps_is_plain`): the masker reads the command, its scan holds no
    parenthesis, pipe, brace, call or background `&`, every joiner sits
    outside a string (one inside is a re-parsed program's), and no
    statement's head -- nor an assignment's value, a command too -- is a
    re-parse opener or runs code in this session. A command past the Bash
    walk's scan cap is not plain on either shell.

    ``False`` keeps the reading the command had before the relief: the
    wall. Remembered per command -- each relief site asks once per
    reading, and a hook process serves one call."""
    if not command or len(command) > _BASH_COMMAND_CAP:
        return False
    return _bash_is_plain(command) if bash else _ps_is_plain(command)


def _bash_is_plain(command: str) -> bool:
    """The Bash half of `_relief_applies`, read off the role walk's own
    masked text: a quoted span is blank there, and a live `$( )` inside a
    double-quoted one still shows. An assignment is no head: a statement
    that only stores a value adds nothing to the head set, and its quoted
    value is data in the masked text (DEF-848's lane -- until then the walk
    raised on a quoted value holding a blank and such a command was never
    plain). A variable the shell RUNS is a head on no roster."""
    try:
        masked, heads, _spans = _walk_shell_roles(splice_line_continuations(command))
    except (_UnresolvedShellSyntax, IndexError):
        return False
    if not heads or not all(
        h in _PLAIN_RELIEF_HEADS or _head_hands_nothing_to_a_shell(h) for h in heads
    ):
        return False
    if "<<" in masked:
        return False
    pieces: list[str] = []
    begin = 0
    for m in _CHAIN_BOUNDARY_RE.finditer(masked):
        tok = m.group()
        if tok == "&" and (
            masked[m.start() - 1:m.start()] in ("<", ">") or masked[m.end():m.end() + 1] == ">"
        ):
            continue                      # a redirection's `&`: `2>&1`, `&>file`
        if tok not in _PLAIN_JOINERS:
            return False
        pieces.append(masked[begin:m.start()])
        begin = m.end()
    pieces.append(masked[begin:])
    for piece in pieces:
        words = piece.split()
        while words and words[0] in ("!", "time", "-p"):
            words.pop(0)
        if words and words[0] in _BASH_COMPOUND_WORDS:
            return False
    return True


def _ps_is_plain(command: str) -> bool:
    """The PowerShell half of `_relief_applies`. The masker's walk must
    read the ORIGINAL command: where it cannot, the scan is the raw text
    and a quoted separator would pass for a joiner."""
    try:
        _walk_powershell_spans(command)
    except (_UnresolvedShellSyntax, IndexError):
        return False
    raw, scan = powershell_scan_pair(command)
    if len(raw) != len(scan) or "(" in scan or ")" in scan:
        return False
    i = scan.find("&")
    while i != -1:
        if scan.startswith("&&", i):
            i = scan.find("&", i + 2)
            continue
        if scan[i - 1:i] != ">":
            return False                  # the call operator, or a background job
        i = scan.find("&", i + 1)         # a redirection's `&`: `2>&1`
    string_at = _ps_quote_cursor(raw)
    pieces: list[str] = []
    begin = 0
    for m in _PS_CHAIN_BOUNDARY_RE.finditer(scan):
        if m.group() not in _PLAIN_JOINERS or string_at(m.start()) is not None:
            return False
        pieces.append(raw[begin:m.start()])
        begin = m.end()
    pieces.append(raw[begin:])
    for piece in pieces:
        value = piece.strip()
        while value[:1] in ("$", "[") and "=" in value:
            value = value.split("=", 1)[1].strip()   # `$x = <command>`
        words = value.split(None, 1)
        if not words:
            continue
        if re.fullmatch(_PS_REPARSE_OPENER_WORDS, words[0].strip("'\""), re.IGNORECASE):
            return False
        if _changes_directory_unseen(value, bash=False, functions=set()):
            return False
    return True


def _statement_bases(
    at: Path, dirs: "tuple[str | None, ...]", *, relief: bool,
) -> list[str | None]:
    """The bases one statement's delete operands are judged from: each of its
    candidate directories joined to the start, and ``None`` ADDED when any is
    unknown -- an unreadable directory change (a `cd $VAR`, `cd -`, `cd
    $(...)`), a `cd` into what an earlier statement removed, or a walk that
    placed nothing (`_UNPLACED_DIRS`). A SUPERSET of the assume-start
    reading, never fewer walls: the start base (an unknown directory joins
    as the start) still walls an absolute or a `.` that names the checkout,
    and the added ``None`` walls a leading glob FROM NOWHERE. So the glob
    relief (DEF-849/843) is WITHHELD where the directory is unknown -- the
    reading it had before the relief (code review): a known `cd` still
    nudges its glob, an unknown one after which `rm -rf *` could clear any
    directory the `cd` reached walls. ONE home for the Bash rm walk, the
    placed sweeps and both PowerShell unforced readers, so no two drift.
    Inside `another_shells_program` every statement is unplaced as well: the
    receiving process put the program where the walk cannot follow.

    ``relief`` is `_relief_applies` of the whole command (the operator's
    allowlist, 2026-09-19): ``False`` adds ``None`` whatever the walk
    placed, so outside a plain command a bare leading glob and the location
    variable wall as they did before the relief. REQUIRED, so a new site
    cannot leave it out and inherit the relief by default."""
    bases: list[str | None] = []
    for d in dirs:
        joined = str(_hook_utils.join_directory(at, d))
        if joined not in bases:
            bases.append(joined)
    if not relief or any(d is None for d in dirs) or _ANOTHER_SHELLS_PROGRAM.get():
        bases.append(None)
    return bases


def _bash_walk_one(
    command: str, root: str | None, cwd: "str | os.PathLike[str] | None",
    lands: "Callable[[str, str | None, list[str | None], str | None, bool], bool]",
) -> bool:
    """One reading's walk: each statement judged from the directories its
    own `cd` chain gives it, from the payload cwd (or the root); ``None``
    for both keeps the reading every caller had; and the net under the
    walk, as for rm -- an absolute catastrophic root anywhere in the
    command, placed or not, is refused as it would be without the chain.
    ``lands(text, root, bases, start_quote, net)``: ``net`` names the net's
    reading, where the bases list alone once meant it (``None`` against
    ``[None]``, the review's item 11)."""
    start = cwd or root
    if start is None:
        return lands(command, root, [None], None, False)
    at = Path(start)
    relief = _relief_applies(command, bash=True)
    try:
        text, statements = bash_directory_chain(command, _hook_utils.directory_exists(at))
    except Exception:  # noqa: BLE001 -- the walk is advisory; a fault places nothing
        text, statements = command, []
    if not statements:
        return lands(command, root, _statement_bases(at, _UNPLACED_DIRS, relief=relief), None, False)
    capped = _capped_whole(command)
    in_heredoc = _heredoc_cursor(text)
    for (s, e, dirs), quote in zip(statements, _statement_start_quotes(text, statements)):
        bases = _statement_bases(at, dirs, relief=relief)
        if (quote is not None or in_heredoc(s)) and None not in bases:
            # another shell's statement (blocker condition 2): inside a string
            # it re-parses, or inside a heredoc body the masker left live
            bases.append(None)
        stmt = text[s:e]
        if capped is not None:
            whole, cut, _hi = capped
            if e > cut and None not in bases:
                # past the cut the walk never saw the middle, whose own
                # directory changes are unknown (the lane's review, item 2)
                bases.append(None)
            if s < cut <= e and whole[:cut] == text[:cut]:
                # the head's last statement, divided by the cut: read whole
                # off the whole command -- its fragment named a folder inside
                # the home as the home itself -- from the same directories
                end = _CHAIN_BOUNDARY_RE.search(whole, cut)
                stmt = whole[s:end.start() if end else len(whole)]
        if lands(stmt, root, bases, quote, False):
            return True
    # The net: an absolute catastrophic target anywhere in the command,
    # placed or not. A leading glob is not the net's (DEF-849): the placed
    # pass judged it in the directory its statement runs in, and the net read
    # it from nowhere and walled a build directory cleared from inside. What
    # the walk placed nowhere is judged from nowhere, as every caller did
    # before the chain (``[None]``, a leading glob the wall).
    if lands(command, root, [None], None, True):
        return True
    return any(lands(piece, root, [None], None, False)
               for piece in _unplaced_text(command, text, statements, capped))


def _capped_whole(command: str) -> "tuple[str, int, int] | None":
    """``(whole, lo, hi)`` for a command past the scan cap, else ``None``:
    the WHOLE command's masked, spliced text -- the net's reading -- and the
    offsets in it where the head the walk read ends and the tail it read
    begins (`_cap_for_scan` keeps the head and the tail, each spliced on its
    own here). ``lo`` is also where the walk's own text joins them."""
    if len(command) <= _BASH_COMMAND_CAP:
        return None
    whole = mask_inert_syntax(splice_line_continuations(command))
    lo = len(splice_line_continuations(command[:_BASH_COMMAND_HALF_CAP]))
    hi = len(whole) - len(splice_line_continuations(
        command[len(command) - _BASH_COMMAND_HALF_CAP:]))
    return whole, lo, hi


def _unplaced_text(
    command: str, text: str, statements: list[tuple[int, int, tuple[str | None, ...]]],
    capped: "tuple[str, int, int] | None" = None,
) -> Iterator[str]:
    """The text of ``command`` no statement of its directory walk covers:
    past the scan cap, the middle the walk never saw (`_cap_for_scan` keeps
    the head and the tail); then the stretches of the walk's ``text``
    between its statements -- a directory verb's own statement, which the
    walk does not list, and the separators.

    The middle is read off the WHOLE command's masked text -- the net's
    reading -- widened out to the nearest live statement boundary outside
    any quote on each side, so the piece starts where the quoting is known
    and the judge's cursor walks it from there. It was the raw middle,
    re-masked on its own: quoting the head opened was lost at the cut, and a
    mention in a long heredoc or string read as a live delete and walled
    from nowhere (the lane's review, item 2). One piece, one judge call, as
    before: a call per statement would cost a generated script's line
    count. Declared limit: past the masker's own cap (`_ROLE_MAP_CAP`) the
    whole command is the raw text, as the net reads it there. ``capped`` is
    the walk's own `_capped_whole`, so the whole command is masked once."""
    if capped is None:
        capped = _capped_whole(command)
    if capped is not None:
        whole, lo, hi = capped
        quote_at = _quote_cursor(whole)
        a, b = 0, len(whole)
        for m in _CHAIN_BOUNDARY_RE.finditer(whole):
            if quote_at(m.start()) is not None:
                continue            # inside a program another shell re-parses
            if m.end() <= lo:
                a = m.end()
            elif m.start() >= hi:
                b = m.start()
                break
        if a < b:
            yield whole[a:b]
    covered = 0
    for s, e, _dirs in statements:
        if s > covered:
            yield text[covered:s]
        covered = max(covered, e)
    if covered < len(text):
        yield text[covered:]


def _bash_scan_pair(command: str) -> tuple[str, str]:
    """``(raw, scan)`` for the Bash sweep readers: the spliced text and its
    masked twin, one length by construction (the raw text stands in when
    the mask moved an offset)."""
    raw = splice_line_continuations(command)
    scan = mask_inert_syntax(raw)
    return raw, (scan if len(scan) == len(raw) else raw)


def _iter_piped_sweeps(raw: str, scan: str, *, wipes_only: bool) -> Iterator[tuple[int, list[str]]]:
    """``(offset, roots)`` for every un-narrowed enumerator piped through
    xargs into a remove verb on the pair (DEF-826), in offset order; the
    roots carry any explicit operand beside the stdin ones. ``wipes_only``
    keeps the pipelines that take every file under the root (the hard
    tier's); the soft tier reads them all."""
    for m in _PIPED_REMOVE_RE.finditer(scan):
        roots, narrowed, wipe, effect, extra = _bash_pipeline_reading(raw, m)
        if effect != "delete" or narrowed or (wipes_only and not wipe):
            continue
        yield m.start("head"), roots + extra


def iter_unnarrowed_piped_remove_roots(
    command: str, *, wipes_only: bool,
) -> Iterator[list[str]]:
    """The roots of every un-narrowed enumerator piped through xargs into a
    remove verb in ``command`` (DEF-826). Read as the find iterator reads:
    the opener on the masked scan, the spans from the raw text, uncapped;
    gated on the cheapest witness of the carrier."""
    raw, scan = _bash_scan_pair(command)
    if not _PIPED_CARRIER_WITNESS_RE.search(raw):
        return
    for _at, roots in _iter_piped_sweeps(raw, scan, wipes_only=wipes_only):
        yield roots


def iter_unnarrowed_bash_sweep_roots(command: str) -> Iterator[list[str]]:
    """Every un-narrowed sweep on the Bash tool for the speed bump's roster
    test: the find family (DEF-815), the carrier pipeline (DEF-826) and the
    loop carrier (DEF-830), so the two tiers keep one reading of what a
    sweep takes."""
    yield from iter_unnarrowed_find_delete_roots(command)
    yield from iter_unnarrowed_piped_remove_roots(command, wipes_only=False)
    yield from iter_unnarrowed_loop_remove_roots(command, wipes_only=False)


def has_catastrophic_piped_remove(
    command: str, root: str | None = None,
    cwd: "str | os.PathLike[str] | None" = None,
) -> bool:
    r"""True if any un-narrowed enumerator piped through xargs into a remove
    verb in ``command`` takes every file under a catastrophic root (DEF-826)
    -- `find . -print0 | xargs -0 rm -rf`, `ls | xargs rm -rf` and `git
    ls-files | xargs rm -rf` (DEF-831) from the checkout, `find ~ | xargs rm
    -rf`, `find . -type f | xargs rm` -- the
    roots judged by `_target_is_catastrophic` as an rm operand is, from the
    directory the command runs in through its own cd chain. A pipeline
    spans the chain's statements (the pipe is a statement boundary to the
    walk), so each sweep is PLACED by the offset of its enumerator in the
    statement that holds it -- one scan text by construction, the start
    alone when the chain's text differs -- the way `has_catastrophic_ps_sweep`
    places its pipelines; never a per-statement slice, which would hold
    half a pipeline. Gated on the cheapest witness of the carrier. Judged on
    every reading `_wall_readings` gives (DEF-846), as every Bash wall is."""
    return any(_piped_remove_one(text, root, cwd) for text in _wall_readings(command))


def _piped_remove_one(
    command: str, root: str | None, cwd: "str | os.PathLike[str] | None",
) -> bool:
    """One reading of `has_catastrophic_piped_remove`."""
    # the pair is CAPPED as the chain's text is, so the two index one text
    # and the walk is never discarded past the cap (the review's note)
    raw, scan = _bash_scan_pair(_cap_for_scan(command))
    if not _PIPED_CARRIER_WITNESS_RE.search(raw):
        return False
    sweeps = list(_iter_piped_sweeps(raw, scan, wipes_only=True))
    if not sweeps:
        return False
    return _placed_sweeps_land_catastrophic(command, scan, sweeps, root, cwd)


def _placed_sweeps(
    command: str, scan: str, sweeps: list[tuple[int, list[str]]],
    root: str | None, cwd: "str | os.PathLike[str] | None",
) -> list[tuple[list[str], list[str | None]]]:
    """``(roots, bases)`` for every ``(offset, roots)`` sweep in offset
    order, placed in the statement of the directory chain that holds its
    offset (one scan text by construction; `_UNPLACED_DIRS` -- the start and
    the unknown -- when the chain's text differs, the walk faults, or no
    statement holds it); ``[None]`` when there is no start to place from. THE one
    placement for every sweep that crosses a statement boundary -- the
    carrier pipeline (DEF-826), the loop carrier (DEF-830) and the
    discard-snapshot arm's reading of a loop's roots (DEF-837's lane) -- so
    no two readers drift on where a sweep runs."""
    start = cwd or root
    at = Path(start) if start is not None else None
    statements: list[tuple[int, int, tuple[str | None, ...]]] = []
    if at is not None:
        try:
            text, statements = bash_directory_chain(command, _hook_utils.directory_exists(at))
            if text != scan:
                statements = []           # one scan text by construction; placed nowhere if not
        except Exception:  # noqa: BLE001 -- the walk is advisory; a fault places nothing
            statements = []
    placed: list[tuple[list[str], list[str | None]]] = []
    idx = 0
    quote_at = _quote_cursor(scan)              # sweeps arrive in offset order
    for here, roots in sweeps:
        bases: list[str | None]
        if at is None:
            bases = [None]
        else:
            while idx < len(statements) and statements[idx][1] <= here:
                idx += 1
            dirs: tuple[str | None, ...] = _UNPLACED_DIRS
            if idx < len(statements) and statements[idx][0] <= here < statements[idx][1]:
                dirs = statements[idx][2]
            bases = _statement_bases(at, dirs, relief=_relief_applies(command, bash=True))
            # a sweep inside a string handed to another program runs where
            # that program puts it (blocker condition 2; `_rm_lands_catastrophic`)
            if quote_at(here) is not None and None not in bases:
                bases.append(None)
        placed.append((roots, bases))
    return placed


def _placed_sweeps_land_catastrophic(
    command: str, scan: str, sweeps: list[tuple[int, list[str]]],
    root: str | None, cwd: "str | os.PathLike[str] | None",
) -> bool:
    """Every sweep placed by `_placed_sweeps` and each root judged from its
    statement's directories; then the net under the walk, as for rm: an
    absolute catastrophic root anywhere in the command, placed or not -- a
    leading glob excepted, which every sweep's placed pass already judged
    where its statement runs (DEF-849; `_placed_sweeps` places each one)."""
    for roots, bases in _placed_sweeps(command, scan, sweeps, root, cwd):
        for op in roots:
            for base in bases:
                if _operand_can_be_catastrophic(op, None, root, base):
                    return True
    return any(
        _operand_can_be_catastrophic(op, None, root, None, net=True)
        for _here, roots in sweeps for op in roots
    )


def iter_placed_loop_removals(
    command: str, at: "str | os.PathLike[str]",
) -> Iterator[tuple[str, list[str]]]:
    """``(path, directories)`` for what a loop carrier's body REMOVES WHOLE,
    wipe or not -- the discard-snapshot arm's reading (DEF-837's lane),
    whose promise covers a plain delete of a dirty file as it does a
    recursive one. The body's own operand is the loop variable and names
    nothing on disk; the roots are what the loop removes. The promise is
    exactly as wide as what the loop takes, so a root is yielded only when
    the head is not narrowed AND hands the body every file under it
    (`_LoopRemoval.whole`): a narrowed find removes only what its predicate
    selects, and an untracked-only listing takes no tracked content -- both
    promised a snapshot for content the loop never touched until the
    failure-mode review. The fixed siblings beside the variable are removed
    as spelled, as a direct operand is. Read as the zone check reads them
    and placed by the wall's own placement (`_placed_sweeps`); a move keeps
    its content and is not yielded. CAPPED as the wall's readers are, so the
    placement's chain and the scan are one text (uncapped, a command past
    the cap placed EVERY loop at the start -- the review drove a `cd` lost);
    gated on the cheapest witness before the scan pair is paid."""
    capped = _cap_for_scan(command)
    if not _loop_carrier_witnessed(capped):
        return
    raw, scan = _bash_scan_pair(capped)
    found: list[tuple[int, list[str]]] = []
    for rx, _shape in _LOOP_OPENERS:
        for m in rx.finditer(scan):
            read = _loop_removal_paths(raw, m)
            if read is None or read.effect != "delete":
                continue
            roots = read.roots if read.root_effect != "sweep" and read.whole else []
            if roots or read.extra:
                found.append((m.start("head"), roots + read.extra))
    found.sort(key=lambda t: t[0])
    for paths, bases in _placed_sweeps(command, scan, found, None, at):
        dirs = [b for b in bases if b is not None]
        for path in paths:
            yield path, dirs


def _loop_carrier_witnessed(text: str) -> bool:
    """The loop carrier's witness gate (`_LOOP_CARRIER_WITNESS_RE`) as the
    three consumers ask it -- the two tiers and the zone reader -- so the
    consumed-arm census, which collects the regex names a reader searches
    with, reads the gate as what it is: a gate, not an operand arm."""
    return _LOOP_CARRIER_WITNESS_RE.search(text) is not None


def _iter_loop_sweeps(raw: str, scan: str, *, wipes_only: bool) -> Iterator[tuple[int, list[str]]]:
    """``(offset, roots)`` for every un-narrowed loop carrier on the pair
    (DEF-830), in offset order across the four openers; the offset is the
    head's (the tail-fed loop's enumerator sits after `done`, in the
    statement whose directory it runs in; the word list's head is its `for`
    keyword). ``wipes_only`` as `_iter_piped_sweeps` has it -- except that
    the word-list head (DEF-837) yields ONLY a wipe, whatever the caller
    asks. The soft tier's sweep pass exists for an enumerator's unseen tree
    and its roster fires on `*` and `*.pyc`, so an un-gated word list would
    nudge the narrowed everyday loop that the rm tier, reading the body's
    own remove, leaves alone -- as it leaves the direct remove of the same
    words."""
    found: list[tuple[int, list[str]]] = []
    for rx, shape in _LOOP_OPENERS:
        only_wipes = wipes_only or shape == "words"
        for m in rx.finditer(scan):
            roots, narrowed, wipe, effect, extra = _bash_loop_reading(raw, m)
            if effect != "delete" or narrowed or (only_wipes and not wipe):
                continue
            found.append((m.start("head"), roots + extra))
    found.sort(key=lambda t: t[0])
    return iter(found)


def iter_unnarrowed_loop_remove_roots(
    command: str, *, wipes_only: bool,
) -> Iterator[list[str]]:
    """The roots of every un-narrowed loop carrier in ``command`` (DEF-830),
    read as the carrier iterator reads: the openers on the masked scan, the
    spans from the raw text, uncapped; gated on the cheapest witness."""
    raw, scan = _bash_scan_pair(command)
    if not _loop_carrier_witnessed(raw):
        return
    for _at, roots in _iter_loop_sweeps(raw, scan, wipes_only=wipes_only):
        yield roots


def has_catastrophic_loop_remove(
    command: str, root: str | None = None,
    cwd: "str | os.PathLike[str] | None" = None,
) -> bool:
    """True if any un-narrowed enumerator bound to a loop variable and
    removed in the loop's body takes every file under a catastrophic root
    (DEF-830) -- `find . | while read f; do rm -rf "$f"; done`, `for f in
    $(find .); do rm -rf "$f"; done`, `while read f; do rm -rf "$f"; done <
    <(find .)` from the checkout -- or any word of a for loop's bare word
    list recursed into (DEF-837: `for f in *; do rm -rf "$f"; done`) --
    the roots judged as the carrier's are,
    from the directory the command runs in through its own cd chain, each
    sweep placed by its head's offset. Gated on the cheapest witness.
    Judged on every reading `_wall_readings` gives (DEF-846), as every Bash
    wall is."""
    return any(_loop_remove_one(text, root, cwd) for text in _wall_readings(command))


def _loop_remove_one(
    command: str, root: str | None, cwd: "str | os.PathLike[str] | None",
) -> bool:
    """One reading of `has_catastrophic_loop_remove`."""
    raw, scan = _bash_scan_pair(_cap_for_scan(command))
    if not _loop_carrier_witnessed(raw):
        return False
    sweeps = list(_iter_loop_sweeps(raw, scan, wipes_only=True))
    if not sweeps:
        return False
    return _placed_sweeps_land_catastrophic(command, scan, sweeps, root, cwd)


def has_catastrophic_bash_sweep(
    command: str, root: str | None = None,
    cwd: "str | os.PathLike[str] | None" = None,
) -> bool:
    """The union the speed bump steps aside from: a find with a delete action
    (`has_catastrophic_find_delete`), an enumerator piped through xargs
    into a remove verb (`has_catastrophic_piped_remove`) or bound to a loop
    variable and removed in the loop's body (`has_catastrophic_loop_remove`),
    each from a catastrophic root -- the Bash twin of
    `has_catastrophic_ps_sweep`."""
    return (
        has_catastrophic_find_delete(command, root, cwd)
        or has_catastrophic_piped_remove(command, root, cwd)
        or has_catastrophic_loop_remove(command, root, cwd)
    )


def _find_lands_catastrophic(
    text: str, root: str | None, bases: "list[str | None]",
    start_quote: str | None = None, net: bool = False,
) -> bool:
    """Every un-narrowed find delete in ``text``, each root judged from each
    of ``bases`` -- ``[None]`` and ``net`` read as `_rm_lands_catastrophic`
    reads them (from nowhere; the net under a walk). ``start_quote`` is taken
    for the walk's one judge shape and unused: a find's roots are read off
    the raw span at the opener, with no quote cursor to restart."""
    del start_quote
    candidates: list[str | None] = list(bases) or [None]
    for roots in iter_unnarrowed_find_delete_roots(text):
        for op in roots:
            for base in candidates:
                if _operand_can_be_catastrophic(op, None, root, base, net=net):
                    return True
    return False


# ── the sweeps on the PowerShell tool (DEF-824, DEF-822) ─────────────────


def _ps_find_sweeps(raw: str, scan: str) -> Iterator[tuple[int, list[str], str]]:
    """``(offset, roots, effect)`` for every ``find`` with a delete action on
    the PowerShell pair: the opener matched on the scan text, the span read
    from the raw twin at the same offsets (DEF-794), the roots unquoted the
    PowerShell way with the separator normalised, the effect
    `_find_delete_roots`'s (`delete`, `sweep`, `move`)."""
    for m in _PS_FIND_DELETE_RE.finditer(scan):
        roots, effect = _find_delete_roots(_named_span(raw, m, "args"))
        yield m.start("args"), [_ps_unquote(r).replace("\\", "/") for r in roots], effect


def _ps_pipeline_reading(raw: str, m: "re.Match[str]") -> tuple[list[str], bool, bool, bool]:
    """``(roots, narrowed, files_only, walks)`` for one enumerator pipeline
    on the PowerShell tool: a `find` head reads by the Bash roots reader
    (its span is find's grammar, not the cmdlet's -- `-type f` would
    otherwise read as a narrowing positional); every other head by
    `_ps_pipeline_roots`. ``walks`` is True for a find (a recursive walk
    into the native rm behind the carrier takes every file, driven)."""
    args = _named_span(raw, m, "args")
    # the head from the RAW text at its own group's offsets, as the spans are
    # (a search over the match's masked text read a `-C` value on the listing
    # head with the mask's rewrite: the row probe's paren shape drove it to a
    # nudge)
    head = _named_span(raw, m, "head")
    key = _enum_head_key(head)
    # a find is never a cmdlet; a listing behind the carrier is the native
    # binary on the host where the carrier runs (the review drove the
    # directory glob with a trailing separator to a false allow through the
    # cmdlet reader); the version-control listing is native on every host
    # and into the cmdlet as into the carrier (DEF-831) -- each read by the
    # Bash roots reader
    if key in ("find", "git ls-files") or (key == "ls" and m.group("carrier") is not None):
        roots, narrowed, files_only, walks = _bash_pipeline_roots(head, args)
        # this tool's normalisation, as `_ps_find_sweeps` applies it
        return [_ps_unquote(r).replace("\\", "/") for r in roots], narrowed, files_only, walks
    roots, narrowed, files_only = _ps_pipeline_roots(args)
    # the recurse switch by any spelling that runs is the walk (the review
    # drove the recursive listing into a plain native remove to a nudge here
    # and a wall on the Bash tool with the flag hardcoded off)
    return roots, narrowed, files_only, bool(_PS_RECURSE_SWITCH_RE.search(args))


def _ps_pipeline_sweeps(raw: str, scan: str) -> Iterator[tuple[int, list[str], bool, bool]]:
    """``(offset, roots, narrowed, wipe)`` for every enumerator piped into a
    remove verb on the pair (DEF-822): ``wipe`` when the remove verb carries
    the recurse switch by any spelling, or the enumeration is files-only --
    the two shapes that take every file under the root (driven: a recursive
    enumeration into a plain remove aborts on the non-interactive prompt)."""
    for m in _PS_PIPED_REMOVE_RE.finditer(scan):
        roots, narrowed, files_only, walks = _ps_pipeline_reading(raw, m)
        recursive = bool(_PS_RECURSE_SWITCH_RE.search(_named_span(raw, m, "rmargs")))
        # behind the carrier the remove verb is the native binary, which takes
        # every file a walk hands it (DEF-826); a cmdlet fed directly prompts
        # on a directory with children, so a walk alone is not its wipe
        carried = m.group("carrier") is not None
        yield m.start("args"), roots, narrowed, _sweep_is_wipe(recursive, files_only, walks, native=carried)


def _ps_unnarrowed_sweeps(raw: str, scan: str, *, wipes_only: bool) -> list[tuple[int, list[str]]]:
    """Every un-narrowed sweep on the pair -- a find with a delete action,
    an enumerator piped into a remove verb -- as ``(offset, roots)`` in
    offset order. ``wipes_only`` keeps the pipelines that take the whole
    tree (the hard tier's); the speed bump reads every one, because a
    recursive enumeration into a plain remove deletes everything enumerated
    before the first directory with children (the failure-mode review drove
    two fixtures: a tree of empty directories went whole) and earns the
    nudge an un-narrowed root earns."""
    out = [(at, roots) for at, roots, effect in _ps_find_sweeps(raw, scan) if effect == "delete"]
    out.extend((at, roots) for at, roots, narrowed, wipe in _ps_pipeline_sweeps(raw, scan)
               if not narrowed and (wipe or not wipes_only))
    out.sort(key=lambda item: item[0])
    return out


def _ps_dotnet_sweeps(raw: str, scan: str) -> list[tuple[int, list[str]]]:
    """``(offset, roots)`` for every recursive .NET directory delete --
    `[IO.Directory]::Delete(<path>, $true)` -- the third spelling of the
    wipe on this tool (failure-mode review, driven: the run directory
    itself went). The root is the first argument when it is a string
    literal, else a token the judge refuses (a variable, a sub-expression:
    fail closed, this tool's rule). The .NET API resolves a relative path
    against the PROCESS directory, which `Set-Location` never moves, so
    these are judged from the start alone, never through the chain."""
    out: list[tuple[int, list[str]]] = []
    for m in _PS_DOTNET_FILE_RE.finditer(scan):
        if m.group(1).lower() != "delete" or "directory]::" not in m.group(0).lower():
            continue
        span = raw_span(raw, m, 2)
        if not span.strip():
            # The argument group stops at a nested paren: a SUB-EXPRESSION
            # root (`(Get-Location)`, `(Join-Path ...)`) reads as nothing.
            # Read the recursion flag past it on the raw text; the root is
            # then a token the judge refuses (fail closed).
            tail = raw[m.start(2):m.start(2) + 512]
            if not _PS_DOTNET_SUBEXPR_RECURSIVE_RE.match(tail):
                continue
            out.append((m.start(2), ["$"]))
            continue
        parts = [p.strip() for p in span.split(",")]
        if len(parts) < 2 or parts[1].lower() != "$true":
            continue                      # non-recursive: removes an empty directory only
        args = _ps_dotnet_literal_args(span)
        root = args[0].replace("\\", "/") if args and args[0] else "$"
        out.append((m.start(2), [root]))
    return out


def _ps_has_sweep_witness(command: str) -> bool:
    """The pre-check every sweep consumer runs before a walk: a find delete
    action, a pipe into a remove verb, or a .NET directory delete, anywhere
    in the uncapped text."""
    return bool(_FIND_DELETE_ACTION_RE.search(command) or _PS_SWEEP_WITNESS_RE.search(command))


def iter_ps_unnarrowed_find_delete_roots(command: str) -> Iterator[list[str]]:
    """The PowerShell twin of `iter_unnarrowed_find_delete_roots` (DEF-824):
    the roots of every un-narrowed ``find`` with a delete action, read from
    the scan pair and uncapped, as the Bash reader is."""
    if not _FIND_DELETE_ACTION_RE.search(command):
        return
    raw, scan = powershell_scan_pair(command)
    if len(scan) != len(raw):
        scan = raw
    for _at, roots, effect in _ps_find_sweeps(raw, scan):
        if effect == "delete":
            yield roots


def iter_ps_unnarrowed_sweep_roots(command: str) -> Iterator[list[str]]:
    """The roots of every un-narrowed sweep on the PowerShell tool -- the
    find family (DEF-824) and the enumerator pipeline (DEF-822) -- for the
    speed bump's roster test; the hard tier reads the same sweeps with
    their offsets (`has_catastrophic_ps_sweep`), so the two tiers keep one
    reading of what a sweep takes. The recursive .NET directory delete is
    the hard tier's alone: a deliberate API call is not the recursive-force
    spelling habit the nudge exists for, and a relative root inside the
    tree is the zone check's on the first issue (the DEF-730 pin)."""
    if not _ps_has_sweep_witness(command):
        return
    raw, scan = powershell_scan_pair(command)
    if len(scan) != len(raw):
        scan = raw
    for _at, roots in _ps_unnarrowed_sweeps(raw, scan, wipes_only=False):
        yield roots


def _ps_sweep_root_is_catastrophic(token: str, root: str | None, base: str | None) -> bool:
    """A sweep's root on the PowerShell tool, by MEANING: a variable or a
    backtick is refused as the Remove-Item tier refuses them (fail closed --
    the value is pwsh's to expand, `$HOME` and `$env:USERPROFILE` name the
    home, and the guard cannot read it), a drive-qualified path by its
    Windows meaning on every host (the step below, DEF-842's arm), and
    everything else by `_target_is_catastrophic` from ``base`` (pwsh expands `~` for a native
    command too -- driven -- so the home rule holds on `find ~ -delete`).
    PowerShell has no brace expansion, so the Bash operand analysis is not
    consulted: `{a,b}` is a literal here."""
    if not token:
        return False
    if "$" in token or "`" in token:
        return True
    # A drive-qualified path by its meaning on ANY host (DEF-842's arm): the
    # drive root, the drive's current directory (`C:` alone, `C:x`), or a
    # path at most two levels under the root (`C:\Windows\System32`,
    # `C:\Users\me`) is catastrophic -- the Bash depth rule's twin for `/etc`
    # and `/usr/local` (the code review: one level was a level short).
    # `_target_is_catastrophic` resolves a drive path against the process
    # directory on a POSIX host, so `C:\` read as a name inside the home
    # directory there and drew the nudge where Windows walls it; its
    # docstring leaves the backslash spelling to this leg. Separators are
    # each caller's to normalize, as its own reader does (the unforced
    # remove reader and the sweep readers hand them over as `/`).
    bare = token.strip("'\"")
    if _PS_DRIVE_QUALIFIED_RE.match(bare):
        if len([c for c in re.split(r"[\\/]+", bare[2:]) if c]) <= 2:
            return True
    return _target_is_catastrophic(token, root, base)


def has_catastrophic_ps_sweep(
    command: str, root: str | None = None,
    cwd: "str | os.PathLike[str] | None" = None,
) -> bool:
    r"""True if any un-narrowed sweep in ``command`` on the PowerShell tool
    starts from a catastrophic root -- the twin of
    `has_catastrophic_find_delete`, read from the directory the command
    runs in through the PowerShell chain (`Set-Location` moves it, per
    statement, by offset on the one scan text the chain and the matcher
    share -- never by the root's spelling).

    DEF-824: GNU find runs verbatim under pwsh on macOS and Linux, and
    until 2026-09-16 `find . -delete` from the checkout drew nothing on
    this tool -- the Bash tier's wall, nudge and roster pass all missing --
    on the one tier maintenance mode never bypasses. DEF-822: the same
    wipe spelled through an enumerator pipe -- `gci -Recurse | ri -r -fo`
    from the checkout, rootless and abbreviated -- drew nothing from any
    tier either: the records spelled the switches in full, the piped reader
    yielded no operand for a rootless enumerator, and nothing judged the
    pipeline's root. The roots are judged by
    `_ps_sweep_root_is_catastrophic` from every base the chain gives the
    statement; ``None`` for both ``cwd`` and ``root`` keeps the reading the
    Bash twin has without a start: an absolute root by the rules, a
    relative one the soft tier's. Gated on the cheapest witness over the
    uncapped text (a delete action, a pipe into a remove verb), as the Bash
    tier is, so a command with no sweep in it pays one linear search."""
    if not _ps_has_sweep_witness(command):
        return False
    raw, scan = powershell_scan_pair(command)
    if len(scan) != len(raw):
        scan = raw
    start = cwd or root
    at = Path(start) if start is not None else None
    statements: list[tuple[int, int, tuple[str | None, ...]]] = []
    if at is not None:
        try:
            text, statements = powershell_directory_chain(
                command, _hook_utils.directory_exists(at))
            if text != scan:
                statements = []           # one scan text by construction; placed nowhere if not
        except Exception:  # noqa: BLE001 -- the walk is advisory; a fault places nothing
            statements = []
    string_at = _ps_quote_cursor(raw)
    # The .NET directory delete reads the process directory, never the
    # chain: judged from the start alone.
    for _at, roots in _ps_dotnet_sweeps(raw, scan):
        for op in roots:
            if _ps_sweep_root_is_catastrophic(op, root, str(at) if at is not None else None):
                return True
    idx = 0
    for here, roots in _ps_unnarrowed_sweeps(raw, scan, wipes_only=True):
        bases: list[str | None]
        if at is None:
            bases = [None]
        else:
            # Statements and sweeps both arrive in offset order, so one
            # cursor places every sweep (a flood of statements stays linear;
            # the ReDoS suite's consumer-cost class).
            while idx < len(statements) and statements[idx][1] <= here:
                idx += 1
            dirs: tuple[str | None, ...] = _UNPLACED_DIRS
            if idx < len(statements) and statements[idx][0] <= here < statements[idx][1]:
                dirs = statements[idx][2]
            # `_statement_bases` adds ``None`` for an unknown location: a
            # find's root can be a bare glob, which then walls from nowhere,
            # while a `.` root from an unknown location stays the deny-once
            # nudge, as it does on the Bash twin. A sweep inside a program
            # handed to another process runs where that process puts it: the
            # unknown directory as well, as its two siblings add it (the
            # lane's review; `_ps_unforced_lands_catastrophic`, `_placed_sweeps`).
            bases = _statement_bases(at, dirs, relief=_relief_applies(command, bash=False))
            if None not in bases and string_at(here) is not None:
                bases.append(None)
        for op in roots:
            for base in bases:
                if _ps_sweep_root_is_catastrophic(op, root, base):
                    return True
    return False


def _ps_dotnet_paths(scan: str, raw: str | None = None) -> list[str]:
    """The paths the .NET file API writes: the static `[IO.File]` /
    `[IO.Directory]` spelling (DEF-730) by its first-argument rule, and the
    object spelling (DEF-746) -- the constructed or cast path, a destination
    for MoveTo / CopyTo / Replace, the attribute assignment on such an
    object. Matched on the scan text; the operands are read from ``raw`` at
    the match's offsets when the caller has it (DEF-794: the PowerShell
    masker blanks a string's parens, and a path read off the scan existed
    nowhere). ONE home: the extractor and `powershell_dotnet_paths`
    (write_guard's process-directory exemption) must yield the same
    strings."""
    text = raw if raw is not None and len(raw) == len(scan) else scan
    paths: list[str] = []
    for m in _PS_DOTNET_FILE_RE.finditer(scan):
        paths.extend(_ps_dotnet_file_targets(m.group(1), raw_span(text, m, 2)))
    for rx in (_PS_DOTNET_INFO_NEW_RE, _PS_DOTNET_INFO_CAST_RE):
        for m in rx.finditer(scan):
            paths.extend(_ps_dotnet_info_targets(
                m.group(3), raw_span(text, m, 2), raw_span(text, m, 4)))
    for m in _PS_DOTNET_INFO_ATTR_ASSIGN_RE.finditer(scan):
        group = 2 if m.group(2) is not None else 4
        paths.append(raw_span(text, m, group))
    return paths


# ── PowerShell same-line variable indirection (DEF-801) ────────────────────
#
# The twin of `_VAR_ASSIGN_RE` / `_expand_simple_var_assignments` in
# PowerShell's grammar, and as narrow: a single-hop literal binding on the
# same command, nothing computed. Driven on the byte-identical hook 2026-09-14
# (walk 3, leg 4-B): `$p='<hook>'; Set-Content -Path $p -Value 1` and the
# `[IO.File]::WriteAllText($p, ...)` spelling ALLOWED while the Bash spelling
# `P=<hook>; echo x > $P` DENIED -- an ordinary two-line scaffolding step,
# caught on one tool and missed on the other. The .NET arm reads only a string
# LITERAL argument (a bare `$p` yields nothing by design), so the twin
# substitutes the bound literal WITH ITS QUOTES outside a string -- which is
# also what keeps a mention inert: `$doc = 'Set-Content -Path <hook>'`
# followed by `Write-Host $doc` becomes `Write-Host 'Set-Content ...'`, a
# literal the masker blanks. Inside an expandable (double-quoted) string the
# bare value is interpolated, escaped the way PowerShell would need it
# spelled (`"` doubled, a backtick and a `$` backtick-escaped), so `"$d/x.py"`
# and `python -c "$code"` read as the text the command produces.
#
# Binding: `$name = 'literal'` or `$name = "literal"` (no `$` or backtick in
# the double-quoted form) at a statement start, and the literal must END the
# statement: `$p = 'a' + 'b'`, `$p = 'a'.Trim()`, a `-join`, a subexpression,
# a bare word (a COMMAND in PowerShell) and a scope-qualified name
# (`$script:p`, `$env:X`) are not bindings. Names are case-insensitive, as
# PowerShell's are. Every reference takes the most recent binding before it;
# a later assignment with a computed value unbinds the name. A reference
# before its binding, an unbound name, a here-string body and a `$(...)`
# inside a string are left alone -- the declared limits, each pinned by an
# allow row in `TestPowerShellVariableIndirectLiteral`.
#
# Sequencing (the ledger row's warning): this runs on the RAW command BEFORE
# `powershell_scan_pair`, so the scan text and its raw twin are both derived
# from the expanded text and every offset read downstream stays valid; it
# never touches the scan text, whose backtick join has already shortened it.
# It is not capped first (the PowerShell leg masks before it caps, so a span
# the cap cut in two is never masked); instead it stands down on a command
# past the scan cap and abandons an expansion that would grow past twice it
# -- the bounds the Bash twin gets from capping first.
#
# ReDoS: `[ \t]*` then `\$`, the name run then `[ \t]*`, `=` then a quote --
# every adjacent pair exclusive; the single-quoted body is `[^']` against `''`
# (exclusive on the first character) and the double-quoted body a negated
# class; the terminator lookahead is anchored on the closing quote. Budget
# row: `tests/test_redos.py::test_ps_var_expansion_prepass_bounded`.
_PS_VAR_ASSIGN_RE = re.compile(
    r"(?:^|[;\r\n{]|&&|\|\|)[ \t]*"
    r"\$([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*"
    r"('(?:[^']|'')*'|\"[^\"$`]*\")"
    r"(?=[ \t]*(?:$|[;\r\n|&#}]))"
)
#: A `$name` / `${name}` reference; the lookahead refuses a scope qualifier.
_PS_VAR_REF_RE = re.compile(
    r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))(?![A-Za-z0-9_:])"
)
#: An assignment operator after a reference: the name is being REBOUND to
#: something the pre-pass cannot read, so it is unbound from here on. The
#: lookahead is spelled `(?![=])`, not `(?!=)`: the latter literal is the
#: assignment-prefix guard the verb-regex census enrols by
#: (`test_assignment_prefix_extracts_no_protected_path`), and this is not a
#: verb regex. `(?<![ \t])`: an attempt never starts inside a blank run, so
#: a `search` over a blank flood is linear (the ReDoS suite drives every
#: derived regex with `search`; the walker itself calls `match` at the
#: reference's end, where the character before is the name's last one).
_PS_REBIND_RE = re.compile(r"(?<![ \t])[ \t]*[-+*/%]?=(?![=])")


def _expand_simple_ps_var_assignments(command: str) -> str:
    """Pre-pass for the PowerShell legs: inline literal `$name = '...'`
    bindings before extraction (the block above). Best-effort: a text the
    walk cannot resolve (an unterminated string, a here-string with no
    terminator), one past the scan cap, or one whose expansion would add
    more than the cap is returned unchanged."""
    if "$" not in command or len(command) > _BASH_COMMAND_CAP:
        return command
    sites = {m.start(1) - 1: m for m in _PS_VAR_ASSIGN_RE.finditer(command)}
    if not sites:
        return command
    try:
        return _ps_walk_and_expand(command, sites)
    except (_UnresolvedShellSyntax, _ExpansionTooLarge):
        return command


def _ps_close_single_quote(s: str, i: int) -> int:
    """Index of the single quote closing the literal string opened at ``i``;
    a doubled quote is the one escape and continues the span."""
    n, j = len(s), i + 1
    while j < n:
        if s[j] == "'":
            if j + 1 < n and s[j + 1] == "'":
                j += 2
                continue
            return j
        j += 1
    raise _UnresolvedShellSyntax("unterminated single quote")


def _ps_literal_value(literal: str) -> str:
    """The text a bound literal spells: quotes off, a doubled single quote
    undone (the double-quoted form admits no escape by construction)."""
    body = literal[1:-1]
    return body.replace("''", "'") if literal[0] == "'" else body


def _ps_escape_expandable(value: str) -> str:
    """``value`` spelled as the characters of a double-quoted string."""
    return value.replace("`", "``").replace('"', '""').replace("$", "`$")


def _ps_interpolate_refs(body: str, bindings: dict[str, tuple[str, str]]) -> str:
    """Bound references inside an expandable string's body, replaced by
    their escaped values; from the first `$(` on, the rest is live code and
    is left alone."""
    if not bindings or "$" not in body:
        return body
    out: list[str] = []
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c == "`":
            out.append(body[i:i + 2])
            i += 2
            continue
        if c == "$":
            if i + 1 < n and body[i + 1] == "(":
                out.append(body[i:])
                break
            r = _PS_VAR_REF_RE.match(body, i)
            if r is not None:
                bound = bindings.get((r.group(1) or r.group(2)).lower())
                if bound is not None:
                    out.append(_ps_escape_expandable(bound[1]))
                    i = r.end()
                    continue
        out.append(c)
        i += 1
    return "".join(out)


def _ps_here_string_opens(s: str, i: int) -> bool:
    """True when only blanks separate ``s[i:]`` from the end of its line: a
    here-string opener (`@'` / `@"`) must end the line, the rule the masker's
    span walk applies; anything else after it is an ordinary `@` token and
    the quote that follows is read as a string."""
    j = i
    while j < len(s) and s[j] in " \t":
        j += 1
    return j < len(s) and s[j] in "\r\n"


def _ps_walk_and_expand(s: str, sites: "dict[int, re.Match[str]]") -> str:
    """One left-to-right pass: strings, here-strings and comments are copied
    (an expandable string with its references interpolated), a binding site
    reached at command level takes effect for what follows it, and a bound
    reference at command level becomes the bound literal, quotes and all."""
    out: list[str] = []
    bindings: dict[str, tuple[str, str]] = {}
    grown = 0
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "<" and s.startswith("<#", i):
            j = s.find("#>", i + 2)
            j = n if j < 0 else j + 2
            out.append(s[i:j])
            i = j
            continue
        if c == "#":
            j = s.find("\n", i)
            j = n if j < 0 else j
            out.append(s[i:j])
            i = j
            continue
        if c == "@" and i + 1 < n and s[i + 1] in "'\"" and _ps_here_string_opens(s, i + 2):
            j = s.find("\n" + s[i + 1] + "@", i + 2)
            if j < 0:
                raise _UnresolvedShellSyntax("unterminated here-string")
            j += 3
            out.append(s[i:j])
            i = j
            continue
        if c == "'":
            j = _ps_close_single_quote(s, i)
            out.append(s[i:j + 1])
            i = j + 1
            continue
        if c == '"':
            j = _ps_close_double_quote(s, i)
            body = _ps_interpolate_refs(s[i + 1:j], bindings)
            grown += len(body) - (j - i - 1)
            if grown > _BASH_COMMAND_CAP:
                raise _ExpansionTooLarge()
            out.append('"' + body + '"')
            i = j + 1
            continue
        if c == "`":
            out.append(s[i:i + 2])
            i += 2
            continue
        if c == "$":
            m = sites.get(i)
            if m is not None:
                out.append(s[i:m.end()])
                literal = m.group(2)
                bindings[m.group(1).lower()] = (literal, _ps_literal_value(literal))
                i = m.end()
                continue
            r = _PS_VAR_REF_RE.match(s, i)
            if r is not None:
                name = (r.group(1) or r.group(2)).lower()
                if _PS_REBIND_RE.match(s, r.end()):
                    bindings.pop(name, None)
                elif name in bindings:
                    grown += len(bindings[name][0]) - (r.end() - i)
                    if grown > _BASH_COMMAND_CAP:
                        raise _ExpansionTooLarge()
                    out.append(bindings[name][0])
                    i = r.end()
                    continue
        out.append(c)
        i += 1
    return "".join(out)


def powershell_dotnet_paths(command: str) -> list[str]:
    """`_ps_dotnet_paths` over the command's own scan pair, capped as the
    extractor caps it: the candidates that resolve against the PROCESS
    directory rather than PowerShell's location, which `Set-Location` alone
    moves (DEF-509; driven in pwsh 7.6.5 by the failure-mode review:
    `[IO.Directory]::GetCurrentDirectory()` did not follow it)."""
    # The same pre-pass as the write leg, or the two disagree: the failure-mode
    # review drove `Set-Location docs; $p='<hook>'; [IO.File]::WriteAllText($p,
    # ...)` to a write-leg candidate this set did not hold, so the chain placed
    # it under `docs/` and the hook ALLOWED it (DEF-801's review, 2026-09-15).
    command = _expand_simple_ps_var_assignments(command)
    raw, scan = powershell_scan_pair(command)
    return _ps_dotnet_paths(_cap_for_scan(scan), _cap_for_scan(raw))


def _candidate_paths_from_powershell(command: str, _depth: int = 0) -> list[str]:
    """Extract write-path candidates from a PowerShell command.

    Covers Set-Content / Out-File / Add-Content / Tee-Object / New-Item
    with -Path / -FilePath / -LiteralPath, the positional first-arg form
    of Set-Content / Out-File / Add-Content, `>` / `>>` redirects
    (shared with bash via _REDIRECT_RE), Copy-Item / Move-Item (plus
    their aliases) by -Destination or the positional pair, with a
    directory destination landing the source's basename inside it, and
    the permission verbs icacls / attrib / Set-Acl / Set-ItemProperty
    (alias sp) by their per-verb operand rule (`_ps_permission_targets`),
    and an interpreter program -- inline (`python -c`, `node -e`, `ruby -e`,
    `perl -e`, the `py` launcher) or piped to the interpreter or to a
    PowerShell reading stdin -- by the literal write paths inside it
    (`_ps_inline_program_bodies`, `_ps_stdin_program_bodies`; DEF-712).

    Head + tail scan via ``_cap_for_scan`` mirrors the bash extractor so
    trailing redirects past the cap are still caught. A same-line literal
    binding is inlined first, on the raw command and before the scan pair
    is derived (`_expand_simple_ps_var_assignments`, DEF-801), so `$p =
    '<hook>'; Set-Content -Path $p` reads as the write it is, as the Bash
    twin's `_expand_simple_var_assignments` has done since April.

    ⚠ MASKED, 2026-08-26, and it was the LAST of the four PowerShell legs to be.
    `mask_powershell_inert_syntax` landed on 2026-08-25 and was wired into the
    dangerous-PS records (`write_guard.check_powershell`) and the PS rm predicate
    (`_speedbump`) but not here and not into the symlink leg -- two of four, with
    nothing naming the other two. Driven with maintenance mode cleared, this leg
    refused `Write-Host 'echo x > <protected>'`, the same line as a `#` comment,
    the double-quoted spelling and a `$doc = '...'` assignment: 4 of 4 plain
    MENTIONS of a protected write, on the tier maintenance mode does NOT relieve.
    Its bash twin has masked since 2026-08-25 (`_candidate_paths_from_bash`) and
    scores 0 of 4 on the same probe.

    ⚠ `_REDIRECT_RE` is why an anchor could not do this alone. It carries no verb
    at all -- it matches the `>` operator -- so there is no command position to
    pin it to, and only neutralising the separator inside the inert span makes
    the mention inert. Mask and anchor are one mechanism in two halves: the mask
    removes the FAKE command positions, the anchor requires a REAL one. A matcher
    with neither is read as an invocation wherever it appears.

    Order matters: mask FIRST, then join backtick line-continuations
    (`powershell_scan_text`), then cap. `_cap_for_scan` splices a head and a
    tail, and masking a spliced string can straddle a span the splice cut in two;
    the join runs on masked text so a backtick inside a string (an escape) is
    never mistaken for a continuation.

    TWO INPUTS from here on (DEF-712): ``command`` is the scan text every
    matcher below reads; ``raw`` is its same-length twin, joined at the same
    offsets, that the interpreter arms slice a program body out of. The cap
    is a function of length alone, so it cuts both at the same place.
    """
    command = _expand_simple_ps_var_assignments(command)   # DEF-801: raw, before the pair
    raw, command = powershell_scan_pair(command)
    raw, command = _cap_for_scan(raw), _cap_for_scan(command)
    paths: list[str] = []
    # ⚠ EVERY consumer below matches on `command` (the scan text) and reads
    # its OPERAND from `raw` at the match's offsets (`raw_operand` /
    # `raw_span`, DEF-794): the PowerShell masker blanks a string's parens
    # and a bare capture stops at its first blank, so an operand read off
    # the scan was a path that existed nowhere.
    for m in _PS_PATH_FLAG_RE.finditer(command):
        paths.append(raw_operand(raw, m))
    for m in _PS_POSITIONAL_RE.finditer(command):
        paths.append(raw_operand(raw, m))
    # `truncate` under pwsh on a POSIX host empties a file (the native
    # binary; the failure-mode review drove a hook to zero bytes)
    for m in _PS_TRUNCATE_RE.finditer(command):
        paths.extend(_ps_truncate_targets(_named_span(raw, m, "args")))
    # git checkout / restore materialise a tracked file (DEF-814's sibling):
    # the three Bash tails on the PowerShell head, the operand from the raw
    # text at the match's offsets and unquoted the PowerShell way.
    for rx in (_PS_GIT_CHECKOUT_DASHDASH_RE, _PS_GIT_CHECKOUT_BARE_RE, _PS_GIT_RESTORE_RE):
        for m in rx.finditer(command):
            paths.append(_ps_unquote(raw_operand(raw, m, keep_quotes=True)))
    for m in _PS_COPY_MOVE_DEST_RE.finditer(command):
        dst = _ps_unquote(raw_span(raw, m, 3))   # 1 is the verb, 2 the pre span (§C52)
        paths.append(dst)
        # The source flag may sit AFTER -Destination, outside the match span:
        # found on the scan's statement segment (a separator inside a string
        # is a blank there), read from the raw text at the same offsets.
        segment = re.split(r"[|;&\n]", command[m.start():], maxsplit=1)[0]
        src_flag = _PS_COPY_MOVE_SRC_FLAG_RE.search(segment)
        src = raw[m.start() + src_flag.start(1):m.start() + src_flag.end(1)] if src_flag else None
        landed = _ps_landed_path(src, dst) if src is not None else None
        if landed:
            paths.append(landed)
    for m in _PS_COPY_MOVE_POSITIONAL_RE.finditer(command):
        src, dst = raw_span(raw, m, 2), _ps_unquote(raw_span(raw, m, 3))   # 1 is the verb (§C52)
        paths.append(dst)
        landed = _ps_landed_path(src, dst)
        if landed:
            paths.append(landed)
    # icacls / attrib / Set-Acl / Set-ItemProperty -- a permission, attribute
    # or ACL change on a hook silences it as surely as a write. Per-verb
    # operand rule; the two display forms are reads (`_ps_permission_targets`).
    for m in _PS_PERMISSION_RE.finditer(command):
        paths.extend(_ps_permission_targets(raw_span(raw, m, 2), m.group(1)))
    # `(Get-Item <hook>).IsReadOnly = $true` (DEF-733) takes the cmdlet
    # operand rule; the .NET static file API (DEF-730) its own first-argument
    # rule, keyed on a read allow-list.
    for m in _PS_ITEM_PROPERTY_ASSIGN_RE.finditer(command):
        paths.extend(_ps_permission_targets(raw_span(raw, m, 1), "set-itemproperty"))
    paths.extend(_ps_dotnet_paths(command, raw))
    for m in _REDIRECT_RE.finditer(command):
        paths.append(raw_operand(raw, m))
    # Interpreter programs: opener on `command` (the scan text), body from
    # `raw` by offset, dispatched through the inner write tables the Bash
    # arms use. A piped PowerShell program is re-scanned by this function.
    for interp, body in _ps_inline_program_bodies(raw, command):
        for rx in _STDIN_PROGRAM_WRITE_RES[interp]:
            for om in rx.finditer(body):
                paths.append(om.group(2))
    for head, segment in _ps_stdin_program_bodies(raw, command):
        if head in _PS_STDIN_SHELL_HEADS:
            if _depth < _PS_STDIN_MAX_DEPTH:
                program = _ps_program_literal_before_pipe(segment)
                paths.extend(_candidate_paths_from_powershell(program, _depth + 1))
            continue
        for rx in _STDIN_PROGRAM_WRITE_RES[_PS_STDIN_DISPATCH[head]]:
            for om in rx.finditer(segment):
                paths.append(om.group(2))
    # A bash program behind `bash -c` / `sh -c` (DEF-637): judged by the
    # grammar that will run it, one level down.
    if _depth < _PS_STDIN_MAX_DEPTH:
        for program in _ps_shell_program_bodies(raw, command):
            paths.extend(_candidate_paths_from_bash(program, _depth + 1))
    return paths


def _named_span(raw: str, m: "re.Match[str]", name: str) -> str:
    """`raw_span` for a NAMED group."""
    start, end = m.start(name), m.end(name)
    return raw[start:end] if start >= 0 else ""


def _ps_operand_tokens(args: str) -> list[str]:
    """A PowerShell argument span as quote-aware tokens, quotes KEPT: the
    flag tests read a token as spelled, and the caller unquotes what the
    tokenizer yields."""
    return _OPERAND_TOKEN_RE.findall(args)


def _ps_dotnet_literal_args(span: str) -> list[str]:
    """The comma-separated arguments of a .NET call, string literals
    unquoted in order and every other argument as ''."""
    out: list[str] = []
    for arg in span.split(","):
        arg = arg.strip()
        literal = len(arg) >= 2 and arg[0] in "'\"" and arg[-1] == arg[0]
        out.append(_ps_unquote(arg) if literal else "")
    return out


def iter_ps_removed_or_relocated_operands(command: str, _depth: int = 0) -> list[tuple[str, str]]:
    """The PowerShell twin of `iter_removed_or_relocated_operands` (§C52):
    `delete` (the remove verbs by positional, `-Path` or `-LiteralPath`, a
    pipeline into a remove verb, `git rm`, `[IO.File]::Delete` and
    `[IO.Directory]::Delete`, the interpreter delete literals), `move`
    (a move verb's source by positional or `-Path`, `Rename-Item`, `git mv`,
    `[IO.File]::Move`'s source, the interpreter rename literals), `archive`
    (`Compress-Archive`'s input) and `read` (an interpreter literal read).
    Same-line literal bindings inlined first, then scan pair and cap, as the
    write extractor's; a `bash -c` program and a piped PowerShell program
    are read one level down."""
    command = _expand_simple_ps_var_assignments(command)   # DEF-801: raw, before the pair
    raw, scan = powershell_scan_pair(command)
    raw, scan = _cap_for_scan(raw), _cap_for_scan(scan)
    out: list[tuple[str, str]] = []

    def named_targets(m: "re.Match[str]") -> list[str]:
        args = _named_span(raw, m, "args")
        tokens = _ps_removal_target_tokens(
            args, tokens=_ps_operand_tokens(args), unknown_takes_value=False,
        )
        return [_ps_unquote(t) for t in tokens]

    for m in _PS_REMOVE_ITEM_RE.finditer(scan):
        out.extend(("delete", p) for p in named_targets(m))
    for m in _PS_PIPED_REMOVE_RE.finditer(scan):
        # the enumerator's roots, the current location when it names none
        # (DEF-822); a narrowed pipeline is a `sweep` -- its root judged by
        # itself, as a narrowed find's is
        roots, narrowed, _files_only, _walks = _ps_pipeline_reading(raw, m)
        out.extend(("sweep" if narrowed else "delete", p) for p in roots)
    for m in _PS_FIND_DELETE_RE.finditer(scan):
        # the find family on this tool (DEF-824): the Bash arm's span reader,
        # so `delete`, `sweep` and `move` mean what they mean on Bash
        roots, effect = _find_delete_roots(_named_span(raw, m, "args"))
        out.extend((effect, _ps_unquote(p)) for p in roots)
    for m in _PS_NATIVE_DESTROY_RE.finditer(scan):
        # the native single-file deletes (`unlink`, `shred`) on this tool
        out.extend(("delete", p) for p in named_targets(m))
    for m in _PS_GIT_CLEAN_RE.finditer(scan):
        out.extend(("clean", p) for p in _git_clean_operands(_named_span(raw, m, "args")))
    for m in _PS_COPY_MOVE_POSITIONAL_RE.finditer(scan):
        if m.group("verb").lower() in _PS_MOVE_VERB_NAMES:
            out.append(("move", _ps_unquote(raw_span(raw, m, 2))))
    for m in _PS_COPY_MOVE_DEST_RE.finditer(scan):
        if m.group("verb").lower() not in _PS_MOVE_VERB_NAMES:
            continue
        pre = _named_span(raw, m, "pre")
        sources = [_ps_unquote(t) for t in _ps_removal_target_tokens(
            pre, tokens=_ps_operand_tokens(pre), unknown_takes_value=False,
        )]
        # The source flag may sit AFTER the destination flag: the write arm's
        # statement-segment search, scan for the offsets, raw for the text.
        segment = re.split(r"[|;&\n]", scan[m.start():], maxsplit=1)[0]
        src_flag = _PS_COPY_MOVE_SRC_FLAG_RE.search(segment)
        if src_flag:
            sources.append(_ps_unquote(raw[m.start() + src_flag.start(1):m.start() + src_flag.end(1)]))
        out.extend(("move", p) for p in sources)
    for m in _PS_RENAME_RE.finditer(scan):
        # every named token: the new name is one of them and lands nowhere
        # protected, and the pick of a "first" would miss a source that sits
        # after `-NewName` (over-yield is the fail-safe direction)
        out.extend(("move", p) for p in named_targets(m))
    for m in _PS_GIT_RM_MV_RE.finditer(scan):
        effect = "delete" if m.group(1).lower() == "rm" else "move"
        for tok in _ps_operand_tokens(_named_span(raw, m, "args")):
            if not tok.startswith("-"):
                out.append((effect, _ps_unquote(tok)))
    for m in _PS_DOTNET_FILE_RE.finditer(scan):
        method = m.group(1).lower()
        args = _ps_dotnet_literal_args(raw_span(raw, m, 2))
        if method == "delete" and args and args[0]:
            out.append(("delete", args[0]))
        elif method == "move" and args and args[0]:
            out.append(("move", args[0]))
    for m in _PS_COMPRESS_ARCHIVE_RE.finditer(scan):
        out.extend(("archive", p) for p in named_targets(m))
    for interp, body in _ps_inline_program_bodies(raw, scan):
        out.extend(_program_effects(interp, body))
    for head, segment in _ps_stdin_program_bodies(raw, scan):
        if head in _PS_STDIN_SHELL_HEADS:
            if _depth < _PS_STDIN_MAX_DEPTH:
                program = _ps_program_literal_before_pipe(segment)
                out.extend(iter_ps_removed_or_relocated_operands(program, _depth + 1))
            continue
        out.extend(_program_effects(_PS_STDIN_DISPATCH[head], segment))
    if _depth < _PS_STDIN_MAX_DEPTH:
        for program in _ps_shell_program_bodies(raw, scan):
            out.extend(iter_removed_or_relocated_operands(program, _depth + 1))
    return out


#: The arms the two readers consume, by name -- the contract test's derived
#: roster (`TestRemovedOrRelocatedOperandIsAMutation`): an arm here without a
#: row there reds, and so does a row naming an arm that is not here. The
#: zone check consumes the first tuple's effects; the secret check the
#: second's (and the move effects of the first).
#: ⚠ Hand-written, PINNED to the readers by an AST walk in the contract test
#: (`test_the_consumption_tuples_are_the_readers_free_names`): every `_RE`
#: name a reader searches with must be here, and nothing else.
_MUTATION_ARMS: tuple[str, ...] = (
    "_DESTROY_RE", "_CP_MV_RE", "_GIT_RM_MV_RE", "_GIT_CLEAN_RE", "_RENAME_RE",
    "_FIND_DELETE_RE", "_PIPED_REMOVE_RE",
    "_LOOP_REMOVE_RE", "_FOR_SUBST_REMOVE_RE", "_TAIL_LOOP_REMOVE_RE", "_FOR_WORDS_REMOVE_RE",
    "_PS_REMOVE_ITEM_RE", "_PS_PIPED_REMOVE_RE", "_PS_FIND_DELETE_RE", "_PS_NATIVE_DESTROY_RE",
    "_PS_GIT_CLEAN_RE", "_PS_COPY_MOVE_POSITIONAL_RE",
    "_PS_COPY_MOVE_DEST_RE", "_PS_COPY_MOVE_SRC_FLAG_RE", "_PS_RENAME_RE",
    "_PS_GIT_RM_MV_RE", "_PS_DOTNET_FILE_RE",
)
_SECRET_EFFECT_ARMS: tuple[str, ...] = (
    "_TAR_CREATE_RE", "_ZIP_RE", "_DD_IF_RE", "_LN_S_RE", "_LN_CP_INVOCATION_RE",
    "_PS_COMPRESS_ARCHIVE_RE",
)
