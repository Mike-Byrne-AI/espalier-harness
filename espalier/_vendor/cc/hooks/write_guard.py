#!/usr/bin/env python3
"""PreToolUse hook -- friction layer for protected-zone writes.

DO NOT REFLOW: bytes 0-200 are SHA-pinned. After editing them run
`espalier _refresh-self-host-pin .` -- else is_self_host_repo() goes
False on this repo, the harness-dev posture silently vanishes, and the
provenance/pre-release/release-pack verbs stand down HERE as if this
were an adopter tree. This warning sits inside the pinned region on
purpose: deleting it is itself a pin change, so it cannot go quietly.
See docs/SHARP_EDGES.md "write_guard first-200-byte signal".

This layer raises the cost of casual bypass. It is NOT a sandbox.

After TP-79: bash + powershell path-extraction primitives live in the
sibling `_bash_patterns` module; protected-zone classification +
path normalization live in `_protected_zones`. This file is the
dispatcher: it composes those modules with the kill-switch gate,
dangerous-pattern checks, maintenance-mode bypass policy, and the
per-tool routing in `_run_main`.

Why it exists: keep the hooks from being trivially turned off mid-session.
The load-bearing case is the agent under load deciding a hook is "in the
way" and silencing friction -- writing `disableAllHooks` into a settings
file, overwriting a hook script, or redirecting a trusted read. Denying
writes to the harness zone keeps the path of least resistance "follow the
workflow," not "disable the safety and go." This is friction against drift,
not a defense against a motivated attacker -- a self-user won't attack
their own work.

Bypass scope, three levels (see `_bash_patterns` for the regex grammar):

(1) IN SCOPE -- caught by the pre-pass + path-extraction regexes:
    literal protected paths, single-variable substitution, common
    write verbs (redirect, tee, cp/mv, sed -i, git checkout/restore,
    inline interpreter -c source), a chmod/chown/chgrp/chflags/chattr/
    setfacl whose target is a protected path (the no-mode forms `chmod
    -E/-N/-I` and `setfacl -b/-k` included), and on the PowerShell tool
    Set-Content / Out-File / Add-Content / Tee-Object / New-Item, `>`
    redirects, and
    Copy-Item / Move-Item (with their aliases) by -Destination or the
    positional pair.

(2) DOCUMENTED OUT OF SCOPE -- not caught, by design: two-step
    subprocess, multi-step variable indirection, runtime path
    construction, ``$(...)`` command substitution.

(3) OUT OF SCOPE AND WON'T BE -- cannot be statically determined.

The deep crafted-equivalence coverage in `_protected_zones` (Class-A2
depth/node-bounded MCP leaf-walk, Class-A4 hardlink-inode backstop, the
filesystem-spelling folds) is DE-PRIORITIZED defense-in-depth: kept because
deleting it fails toward over-protect, but no self-user reaches these by
mistake -- the self-disable cascade does not route through an exotic MCP
payload or a hardlink. The primary target is the everyday slip and the
agent's own settings/hook edit, not a crafted bypass.

Real enforcement lives in:
  - .github/workflows/harness-guard.yml + branch protection
  - Claude Code managed-settings tier (out of scope for this project)

Matcher: "*" (all tools). Script filters internally via MUTATION_TOOLS.
Protected zone writes: DENY (exit 0 + permissionDecision="deny").
Dangerous bash/powershell patterns: DENY (exit 0 + permissionDecision="deny").
Protected-path Bash-write patterns: DENY (exit 0 + permissionDecision="deny").
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

# Co-located helper modules -- same zero-espalier-import pattern as other hooks.
sys.path.insert(0, str(Path(__file__).parent))
import _hook_utils  # noqa: E402
from _hook_utils import os_error_text  # noqa: E402
import _integrity  # noqa: E402
import _maintenance_mode  # noqa: E402
import _bash_patterns  # noqa: E402
import _denial_reasons  # noqa: E402
import _protected_zones  # noqa: E402
import _speedbump  # noqa: E402
import _reinject  # noqa: E402

MUTATION_TOOLS = _hook_utils.MUTATION_TOOLS

# Public re-exports for tests that pin the friction-layer surface
# (tests/test_redos.py, tests/test_contract_consumers.py,
# tests/test_write_guard.py). Don't reach into _bash_patterns or
# _protected_zones from tests directly -- keep the import path stable
# at the dispatcher boundary so future internal reshuffles stay
# test-transparent.
_REDIRECT_RE = _bash_patterns._REDIRECT_RE
_HEREDOC_RE = _bash_patterns._HEREDOC_RE
_TEE_RE = _bash_patterns._TEE_RE
_SED_INPLACE_RE = _bash_patterns._SED_INPLACE_RE
_CP_MV_RE = _bash_patterns._CP_MV_RE
_GIT_CHECKOUT_DASHDASH_RE = _bash_patterns._GIT_CHECKOUT_DASHDASH_RE
_GIT_CHECKOUT_BARE_RE = _bash_patterns._GIT_CHECKOUT_BARE_RE
_GIT_RESTORE_RE = _bash_patterns._GIT_RESTORE_RE
_LN_S_RE = _bash_patterns._LN_S_RE
_CP_SYMLINK_RE = _bash_patterns._CP_SYMLINK_RE
iter_hardlink_operands = _bash_patterns.iter_hardlink_operands
_PYTHON_DASH_C_RE = _bash_patterns._PYTHON_DASH_C_RE
_NODE_DASH_E_RE = _bash_patterns._NODE_DASH_E_RE
_RUBY_DASH_E_RE = _bash_patterns._RUBY_DASH_E_RE
_PERL_DASH_E_RE = _bash_patterns._PERL_DASH_E_RE
_INTERP_STDIN_RE = _bash_patterns._INTERP_STDIN_RE
# Inner write-target regexes (run over interpreter -e/-c bodies). Re-exported
# so tests/test_redos.py can pin them linear.
_PY_FILE_OPEN_RE = _bash_patterns._PY_FILE_OPEN_RE
_NODE_FS_WRITE_RE = _bash_patterns._NODE_FS_WRITE_RE
_RUBY_FILE_WRITE_RE = _bash_patterns._RUBY_FILE_WRITE_RE
_PERL_OPEN_RE = _bash_patterns._PERL_OPEN_RE
_PERL_OPEN3_RE = _bash_patterns._PERL_OPEN3_RE
_PY_PATH_WRITE_RE = _bash_patterns._PY_PATH_WRITE_RE
_PY_DEST_ARG_WRITE_RE = _bash_patterns._PY_DEST_ARG_WRITE_RE

PROTECTED_PREFIXES = _protected_zones.PROTECTED_PREFIXES
PROTECTED_FILES = _protected_zones.PROTECTED_FILES
ALLOWED_IN_PROTECTED = _protected_zones.ALLOWED_IN_PROTECTED
ALLOWED_PREFIXES_IN_PROTECTED = _protected_zones.ALLOWED_PREFIXES_IN_PROTECTED

# The two string normalisers stay the documented seam (tests drive them by
# name); the body reads through the `(base, rel)` owners beneath them so the
# hardlink backstop stats the checkout the target sits in (DEF-743).
_normalize_path = _hook_utils.normalize_path
_normalize_path_str = _hook_utils.normalize_path_str
_normalize_bash_path = _hook_utils.normalize_bash_path
_resolve_in_checkout = _hook_utils.resolve_in_checkout
_resolve_bash_in_checkout = _hook_utils.resolve_bash_in_checkout
_is_protected = _protected_zones._is_protected
_is_allowed = _protected_zones._is_allowed
_encloses_protected = _protected_zones._encloses_protected
_aliases_protected_inode = _protected_zones.aliases_protected_inode

# BC-028: Bash tool inline-assignment of harness env vars.
# Contract: set in parent shell BEFORE launching `claude`. Inline
# assignment via a Bash tool call sets the var for the immediate
# child process only -- it does NOT reach already-running hooks --
# so the syntax is pedagogically harmful (teaches the wrong mental
# model, ends up in committed scripts). Block at the friction layer.
#
# The deny requires COMMAND POSITION, not mere presence of the token:
# a bare `\b...=` would match the env literal even when it sits inside
# a quoted argument (a commit message, a
# `--description "...ESPALIER_MAINTENANCE_MODE=1..."`) -- denying the
# legitimate documentation of the very footgun. The token matches
# only at a command-position boundary:
#   BRANCH_A: start-of-string OR a command separator (`;` `&` `|`
#     newline, subshell `(`, brace-group `{`, backtick), then optional
#     horizontal ws, then an optional chain of command-position prefix
#     segments -- an `env`/`sudo` word (with flags) or a `NAME=val`
#     assignment (keeps `env -i VAR=1`, `ENV=x VAR=1`, and the
#     command-substitution `$(VAR= ...)` form denied);
#   BRANCH_B: a freestanding `\b(?:env|sudo)` (with flags) -- keeps
#     `/usr/bin/env VAR=1` and `sudo VAR=1` denied.
# Horizontal-only `[ \t]` anchors (never `\s`) keep newline out of any
# trailing whitespace run -> linear, no ReDoS on a multi-line body.
#
# Known limitation (BC-007 generic-shell-expansion class): the
# *obfuscated* forms -- `$'\x45SPALIER_...'`, IFS-indirection, and
# `eval $(echo ...)` where the literal token never appears -- still
# bypass any token-substring regex. Documented in docs/SHARP_EDGES.md
# and bench/corpus/BC-OOS-004-shell-expansion-env-prefix.json. The
# defense is friction for habit-formation, not adversary-proof.
# ⚠ Token runs are `[^\s;|&]`, never `\S`. `\S` matches `;`, so on a
# separator-dense command with no spaces (`x=1;x=1;x=1;...`) a greedy `\S*`
# scans to end-of-input, fails to find the required trailing space, and
# backtracks one character at a time -- from every start position. That is
# O(n^2) on an input the 32KB cap happily admits: measured >1s on 30KB, against
# a 5s hook timeout. Found by the derived ReDoS population gate in
# tests/test_redos.py, which covers this pattern for the first time -- it sat in
# the deny path with no linear-time budget. A shell token cannot span `;`, `|`
# or `&`, so the bound is also the semantically correct read.
# ⚠ ANCHORED ON THE SHARED `_CMD_POS`, NOT A HAND-ROLLED RIVAL. This used to be
# two alternatives: a separator-anchored branch, and a bare-`\b` branch carrying
# `env|sudo|export|declare`. The bare branch read a verb ANYWHERE, including
# inside a quoted argument, so `git commit -m "docs: drop export
# ESPALIER_STOP_GATE=full"` was HARD-DENIED -- and this tier dispatches before
# the maintenance gate, so there was no lever. The FP was spelling-dependent in a
# way nobody could predict: `...=full"` denied while `...=1 mid-session"` allowed,
# because the benign-occurrence check needs a following word to find a target.
#
# ⚠ THE OBVIOUS FIX IS NET-NEGATIVE AND WAS MEASURED SO. Deleting `export|declare`
# from the bare branch scores WORSE than the code it replaces (12/16 vs 14/16 on a
# driven matrix): it allows `bash -c "export VAR=1; claude"`, `sh -c '...'` and
# `eval "..."`, all of which genuinely export the variable into the environment
# the agent binary then inherits. `export VAR=1 claude` is inert, but
# `export VAR=1; claude` is a real reach, and the two differ by one character.
#
# `_CMD_POS` already draws exactly the line that matters, because
# `_CMD_POS_EXEC_QUOTE` models a shell-exec wrapper as OPENING a command position
# inside its quoted argument. So `bash -c "export ...` is a command position and
# `git commit -m "docs: ... export ...` is not -- no quote-masking pass required,
# and no second copy of a security-adjacent anchor to drift (STANDING_PRINCIPLES
# §8; same reuse as `_speedbump._GIT_CMD`). Measured 16/16, and it additionally
# closes `nohup ESPALIER_MAINTENANCE_MODE=1 claude`, a wrapper-prefixed launch the
# two-branch form allowed -- `_CMD_POS_WRAP_RUN` carries the wrapper roster this
# pattern was enumerating by hand. Linear-time budget is inherited from
# `_CMD_POS`'s own ReDoS gate rather than re-argued here.
# ⚠ NO SECOND `NAME=val` RUN HERE. `_CMD_POS` already consumes leading
# assignments (`_CMD_POS_ENV_ASSIGN` sits inside its starred group), so appending
# another starred `NAME=value` run gives two ADJACENT Kleene stars over
# the same token shape -- 2^n ways to partition one `X=1 Y=2 ` run, all of which
# the engine explores on a FAILING match. The first cut of this fix did exactly
# that and tests/test_redos.py reddened on it (two derived instances). The
# `export|declare` clause below is safe because those verbs are NOT in
# `_CMD_POS_WRAP_RUN`'s roster, so it cannot re-consume what `_CMD_POS` consumed.
_HARNESS_ENV_PREFIX_RE = re.compile(
    _bash_patterns._CMD_POS_NO_VERB
    + r"(?:(?:export|declare)(?:[ \t]+-[^\s;|&]+)*[ \t]+)?"
    + rf"(?:{re.escape(_maintenance_mode.ENV_VAR)}|ESPALIER_STOP_GATE)[ \t]*="
)

# ⚠ POLARITY. The deny above teaches a mental model -- "an inline assignment
# cannot reach the hooks of the ALREADY-RUNNING session" -- and that is true only
# when the assignment invokes NOTHING. When it PREFIXES a command, the variable
# does reach that command's process, exactly as written:
#   ESPALIER_MAINTENANCE_MODE=1 pytest -q              works
#   ESPALIER_MAINTENANCE_MODE=1 python3 <a hook>       works
#   ESPALIER_MAINTENANCE_MODE=1 claude                 works -- and it is the
#     relaunch THIS RULE'S OWN REMEDY prescribes (_denial_reasons
#     .HARNESS_ENV_PREFIX_INLINE spells it via _maintenance_mode.relaunch_hint(),
#     `ESPALIER_MAINTENANCE_MODE=1 claude --continue` on POSIX), so the un-carved
#     rule refused the command it told you to run.
# Measured, not reasoned: pre-carve-out all three denied while `export
# ESPALIER_MAINTENANCE_MODE=1` -- the form that genuinely cannot work -- was
# ALLOWED. The rule denied its correct usage and permitted the mistake it exists
# to prevent. It also blocked the canonical maintenance loop (edit a hook, then
# run it to see whether the edit worked), which is the workflow maintenance mode
# exists to serve.
#
# Applied to `command[match.end():]`, i.e. the text after the `=`: consume the
# assignment's VALUE, require horizontal space, skip any further `NAME=val`
# assignments, then demand one character of a real command word. A `&&`/`;`/`|`
# there is NOT a command word (`VAR=1 && pytest` does not pass the variable to
# pytest), so those correctly keep the deny.
# Each value is `_bash_patterns._ASSIGN_VALUE`, the assignment-value grammar's
# one home (DEF-848's lane): it ends at the first UNQUOTED blank, as bash ends the
# word, where the inline copy this replaced ended at any blank and read a word of
# a quoted value (`MSG='a b'`) as the invoked command. Whitespace stays
# horizontal-only `[ \t]` for the same linear-time reason the pattern above
# documents. group(1) = the command the assignment actually invokes, after its
# own value and any further NAME=val segments -- never one of those segments'
# NAMES: without the lookahead a separator right after a second assignment
# (`...=1 X=1; pytest`) backtracked onto `X` and read it as the command.
_BASH_ENV_PREFIX_TARGET_RE = re.compile(
    "^" + _bash_patterns._ASSIGN_VALUE + r"[ \t]+(?:[A-Za-z_]\w*="
    + _bash_patterns._ASSIGN_VALUE + r"[ \t]+)*(?![A-Za-z_]\w*=)([^\s;|&=]+)"
)

# ⚠ `claude` is the ONE target that must keep denying, and it is a real reach,
# not pedagogy: `ESPALIER_MAINTENANCE_MODE=1 claude -p "..."` launches a NESTED
# session whose write_guard skips the protected-zone check (the maintenance gate
# below), so an in-session actor could spawn an ungoverned agent to edit the very
# files this hook protects. bench/corpus/BC-028 classifies that as a bypass
# class, and the release-gating benchmark is what caught an earlier, wider
# carve-out that allowed it. Every other target -- pytest, python3 driving a
# hook -- gains nothing: the write_guard decision for THIS tool call is already
# made before the command runs, so the variable cannot loosen it.
# ⚠ A FIRST-WORD match here was a one-name denylist over an open domain: driven,
# only 3 of 16 spellings of the launch were shut -- `npx claude`, `nohup claude`,
# `exec claude`, `env claude`, `command claude`, `time claude`, `xargs claude`,
# `sh -c 'claude ...'`, `$(which claude)` and `CLAUDE` all delivered the variable.
# `CLAUDE` is not hypothetical: on a case-insensitive filesystem (APFS/NTFS)
# `command -v CLAUDE` resolves to the same binary. So the scan is token-level and
# BASENAME-keyed across the whole statement, which is closed under wrappers
# instead of enumerating them.
#
# Basename equality, never substring: a substring test would deny
# `pytest tests/test_folder_claude_md_routers.py` and re-block the maintenance
# loop for every test file with `claude` in its name -- this repo has several.
_CLAUDE_BASENAME = "claude"
_TOKEN_SPLIT_RE = re.compile(r"[\s;|&()`]+")

# ⚠ THE NORMALISER HAD THREE OF THE FOUR WAYS A TARGET IS WRITTEN, AND THE
# MISSING ONE IS THE ONLY ONE WINDOWS USES. It already folded a directory prefix
# (`./claude`, `$(which claude)`), a surrounding quote (`"claude"`) and letter
# case (`CLAUDE`, for the case-insensitive filesystems the comment above reasons
# about) -- and compared the result to a bare basename, so an EXECUTABLE SUFFIX
# walked straight through. Driven 2026-08-26 against the real hook: 6 of 7
# spellings of the launch were ALLOWED (`claude.exe`, `CLAUDE.EXE`, `Claude.Exe`,
# `claude.cmd`, `claude.bat`, `claude.ps1`), while `./claude`, `bin/claude`,
# `"claude"` and `'claude'` all correctly denied. The npm shim on Windows is
# literally `claude.cmd`, so on the platform this code reasons about the guard
# caught NOTHING -- and `bench/corpus/BC-028`'s three canonical attempts all
# spell the target bare `claude`, so the benchmark could not see it either.
#
# Same class as the record anchoring below: a population written by hand where a
# normaliser already existed (docs/STANDING_PRINCIPLES.md §14). The suffix belongs
# HERE, with the other three foldings, not in a roster of enumerated spellings.
#
# ⚠ `.com` IS DELIBERATELY EXCLUDED, as a stated trade rather than an oversight.
# Stripping it makes `curl https://claude.com` read as a launch, and under §2
# (friction guard, not adversary boundary) a false positive on ordinary work
# outranks a bypass spelling nothing ships. Add it -- knowingly -- if a `.com`
# build ever exists. The exclusion is pinned by a must-allow row in
# tests/test_write_guard_env_prefix_polarity.py.
_LAUNCHER_SUFFIXES = (".exe", ".cmd", ".bat", ".ps1")

# ⚠ SUBSTITUTION, NOT `.strip()`, AND THE `$` IS WHY. `.strip("\"'")` removes
# quotes only at the ENDS, so `$'claude'` normalised to `$'claude` -- a leading
# `$` the strip cannot reach -- and `$'cl'$'aude'` kept two interior quote pairs.
# Both ALLOWED at HEAD. Bash concatenates adjacent quoted runs into one word, so
# deleting the quote characters wherever they sit is what reproduces the shell's
# own reading of the token.
#
# ⚠ BOUNDARY, stated rather than implied: this folds the quote CHARACTERS only.
# `$'\x63laude'` decodes an ESCAPE after this regex has already run, and stays
# out of scope with the rest of its class (`bench/corpus/BC-OOS-004`, which
# declares shell-expansion name-hiding out of scope for the same reason).
_TOKEN_QUOTE_RE = re.compile(r"\$?[\"']")


def _normalise_target_token(raw: str) -> str:
    """Fold one token to the basename a shell would actually execute."""
    token = _TOKEN_QUOTE_RE.sub("", raw)
    token = token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    # ONE suffix, not a loop: a real launcher carries a single extension, and
    # stripping repeatedly would fold `claude.exe.bak` -- a backup file, not a
    # launcher -- into a launch.
    for suffix in _LAUNCHER_SUFFIXES:
        if token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _statement_launches_claude(segment: str) -> bool:
    """True when any token in one statement is a `claude` invocation.

    Shared by BOTH shells: `_ps_occurrence_is_benign` calls this same function,
    so a spelling added here closes the Bash and PowerShell legs at once. That
    sharing is pinned by
    tests/test_write_guard_env_prefix_polarity.py::test_powershell_target_spellings_share_the_bash_normaliser,
    so forking a PowerShell copy reds instead of silently diverging.
    """
    for raw in _TOKEN_SPLIT_RE.split(segment):
        if _normalise_target_token(raw) == _CLAUDE_BASENAME:
            return True
    return False


def _occurrence_is_benign(tail: str) -> bool:
    """Judge ONE assignment by the statement it heads.

    Scoped to the first statement of ``tail``: `VAR=1 pytest; claude` does NOT
    pass the variable across the `;`, so that `claude` is somebody else's
    business and must not make this occurrence deny.
    """
    # ⚠ A BACKSLASH-NEWLINE IS A CONTINUATION, NOT A STATEMENT BOUNDARY. Splicing
    # it out BEFORE the split is what keeps `VAR=1 \<nl>claude` one statement. Left
    # unspliced, the split yielded `1 \`, whose trailing `\` satisfies the target
    # regex as a "command word", so the occurrence was judged benign and the agent
    # launch on the next physical line was never seen — reopening the BC-028
    # bypass class with the benchmark still reporting green.
    #
    # Spliced here rather than by dropping `\n` from `_STATEMENT_SPLIT_RE`: that
    # alternative was measured to re-block the multi-line maintenance loop
    # (`VAR=1 pytest` and `VAR=1 python <hook>` on consecutive lines), because a
    # bare newline between two independent statements IS a boundary. Both are
    # newline handling; only one distinguishes continuation from separation.
    # Sibling precedent: `_bash_patterns.iter_rm_invocations` splices the same
    # sequence before segmenting, for the same reason.
    segment = _STATEMENT_SPLIT_RE.split(
        _bash_patterns.splice_line_continuations(tail), 1)[0]
    if _BASH_ENV_PREFIX_TARGET_RE.search(segment) is None:
        return False  # invokes nothing -> the deny stands
    return not _statement_launches_claude(segment)


_STATEMENT_SPLIT_RE = re.compile(r"[;\n]")


def _harness_env_prefix_is_benign(command: str) -> bool:
    """True when EVERY harness assignment in the command is benign.

    ⚠ ``finditer``/``all``, never ``search``: judging only the first match let
    `VAR=1 pytest; STOP_GATE=full` through -- an ordinary "run the tests, then arm
    the gate for next time" command whose SECOND assignment is exactly the inert
    form the deny message names. One benign occurrence must not license the rest.

    Fails toward the DENY on an unparseable tail: this layer is friction, and a
    missed step-aside costs a re-issue while a wrong one drops the lesson.
    """
    matches = list(_HARNESS_ENV_PREFIX_RE.finditer(command))
    if not matches:
        return False
    return all(_occurrence_is_benign(command[m.end():]) for m in matches)

# Pattern + message paired in one record so the message travels with the
# pattern -- a parallel `dict[re.Pattern, str]` would key by compiled-regex
# object identity, so re-compiling the same source inline would miss the
# lookup and silently fall through to the auto-generated form.
class BashPatternRecord(NamedTuple):
    pid: str  # short slug for debugging / future test reference
    pattern: re.Pattern[str]
    message: str = ""  # empty => use auto-generated default at deny time


# Dangerous bash patterns -- hard block (deny). Custom messages on
# entries that need them; the rest fall back to the
# "Dangerous command blocked: matches pattern '<source>'" default
# generated in check_bash_dangerous_patterns.
DANGEROUS_BASH_PATTERNS: tuple[BashPatternRecord, ...] = (
    # ⚠ ANCHORED 2026-08-24 (DEF-498), the other two sites of DEF-414f's class.
    # These are the LITERAL belt to `_bash_patterns.has_catastrophic_recursive_rm`'s
    # braces — that function is the flag-order- and spelling-independent superset,
    # so these two add nothing it misses, but as bare substrings they fired on any
    # command whose TEXT contained the spelling. That is the whole of
    # `echo 'the guard refuses rm -rf /'` being refused. Kept rather than deleted
    # (a named record carries its own message and the coupling gate pins it), but
    # anchored so a MENTION is not read as an INVOCATION.
    # ⚠ AND RIGHT-ANCHORED. `rm[ \t]+-rf[ \t]+/` matched the PREFIX of every absolute
    # path -- `rm -rf /tmp/x` contains `rm -rf /` -- so these records, not the
    # operand classifier, were what hard-denied an ordinary cleanup. Re-tiering
    # the classifier alone changed nothing until these were bounded, which is why
    # the ledger's own unit of work says "right-anchor the rm-rf-root record AND
    # stop _operand_can_be_catastrophic denying every absolute-path operand" --
    # two edits, one defect. `(?=\s|$)` keeps bare `/` and bare `*` (including
    # `rm -rf / 2> /dev/null`) and drops `/tmp/x` and `*.egg-info`.
    BashPatternRecord("rm-rf-root",
                      re.compile(_bash_patterns._CMD_POS + r"rm[ \t]+-rf[ \t]+/(?=\s|$)")),
    BashPatternRecord("rm-rf-star",
                      re.compile(_bash_patterns._CMD_POS + r"rm[ \t]+-rf[ \t]+\*(?=\s|$)")),
    # `git reset --hard` lives in the CP-DISCARD soft speed-bump (_speedbump.py),
    # not the hard-deny tier -- it discards uncommitted work (no reflog) but is a
    # routine operation, so a deny-once-then-allow reminder fits the governing
    # frame better than a wall that fires even in maintenance mode. The
    # catastrophic-rm forms above remain hard-denied.
    BashPatternRecord(
        "harness-env-prefix",
        _HARNESS_ENV_PREFIX_RE,
        # Message lives in the tested operator-facing template registry in
        # _denial_reasons so it carries the Don't/Do pairing under
        # test_template_contains_both_markers.
        _denial_reasons.HARNESS_ENV_PREFIX_INLINE,
    ),
)

# Dangerous PowerShell patterns -- mirrors DANGEROUS_BASH_PATTERNS shape.
# Tuple-of-records (not a plain list[re.Pattern]) so a PS pattern needing a
# custom message stays structurally paired with its pattern, foreclosing the
# parallel-dict bug class the Bash side avoids.
# PowerShell twin of _HARNESS_ENV_PREFIX_RE. Same wrong mental model -- setting
# a harness env var from inside the session, which cannot reach hooks that are
# already running -- expressed in the other shell, where it had no deny at all.
#
# Defined at MODULE level, not inlined in the record below, and that is
# load-bearing: the derived ReDoS population in tests/test_redos.py harvests
# module-level `*_RE` names, so an inlined pattern gets no linear-time budget.
# (The two Remove-Item records below are inlined and were invisible to it for
# that reason; the derivation now also harvests record patterns.)
#
# Three shapes, enumerated deliberately -- this is a friction guard, not an
# adversary boundary (docs/STANDING_PRINCIPLES.md §2), so what it covers is
# stated rather than implied:
#   $env:VAR = "1"; cmd        assignment prefix
#   Set-Item Env:\VAR 1        cmdlet form, with or without -Path
#   [Environment]::SetEnvironmentVariable("VAR", "1")
# All runs are bounded (`[^\s;|&]`, no unbounded `.`): an unbounded span here is
# a hook-runtime ReDoS, which the dot-star gate and the derived budget both
# enforce.
#
# ⚠ The `$env:` arm carries the COMMAND-POSITION anchor its Bash twin has always
# had and this one never did -- the sister-site gap, with PowerShell again the
# worse instance (the same shape as the recursive-delete deny messages). Without
# it a bare prose mention denied: `Write-Host 'set $env:<harness var>=1
# first'` was refused while the identical Bash sentence was allowed, so
# documenting this very footgun was blocked on one platform only.
#
# ⚠ THE ANCHOR IS NOW COMPOSED, AND IT WAS A HAND-ROLLED NEAR-COPY UNTIL
# 2026-08-26. It read `(?:^|[;&|\n({])[ \t]*` -- close enough to
# `_PS_CMD_POS_SEP` to look finished, and wrong in two ways at once. It dropped
# four members of that class (`\r`, `)`, `}` and `=`; a PowerShell assignment
# really does run its right-hand side, which is why `=` is in there), and it had
# no `_PS_CMD_POS_EXEC_QUOTE` arm at all -- the arm that exists SPECIFICALLY to
# keep a re-parsing wrapper fail-closed. Driven: `$env:<var>=1; claude` DENIED
# while `Invoke-Expression "$env:<var>=1; claude"` ALLOWED, and `iex` re-parses
# that string, so the quote made no difference to what ran. Same for `pwsh -c`
# and `cmd /c`. The two Remove-Item records eight lines below had composed
# `_PS_CMD_POS` all along, and `tests/test_guard_false_positives.py` already
# pinned `iex-double`/`iex-alias` as must-deny FOR THEM: the answer was in the
# repo and was never applied to the second record (STANDING_PRINCIPLES §14 --
# derive the list, don't test a hand-written copy of it).
#
# ⚠ STATED COST OF COMPOSING IT -- re-measured 2026-09-14, and the cost the
# first version of this note predicted did not materialise. It said prose that
# names `powershell` and then quotes an assignment would deny
# (`Write-Output "in powershell $env:<var>=1 does nothing"`), that the
# Remove-Item records already carried the same false positive, and that a
# strict xfail in tests/test_write_guard_env_prefix_polarity.py pinned the gap.
# Driven through check_powershell at HEAD: that command ALLOWS, and so does the
# Remove-Item prose twin (`Write-Output "use Remove-Item to delete"`); no such
# xfail exists in that file. Both prose allows are pinned there now, beside
# the `$env:` prose-allow test.
#
# The `Set-Item` / `SetEnvironmentVariable` arms are left unanchored: both are
# multi-token forms that read far less naturally inside prose, and widening the
# anchor to expression position is a bigger change than this defect earns.
_PS_HARNESS_ENV_PREFIX_RE = re.compile(
    r"(?:"
    r"(?P<envcolon>"
    + _bash_patterns._PS_CMD_POS
    + rf"\$env:(?:{re.escape(_maintenance_mode.ENV_VAR)}|ESPALIER_STOP_GATE)\s*=)"
    r"|Set-Item\s+(?:-Path\s+)?[\"']?Env:[\\/]?"
    rf"(?:{re.escape(_maintenance_mode.ENV_VAR)}|ESPALIER_STOP_GATE)\b"
    r"|SetEnvironmentVariable\(\s*[\"']"
    rf"(?:{re.escape(_maintenance_mode.ENV_VAR)}|ESPALIER_STOP_GATE)[\"']"
    r")",
    re.IGNORECASE,
)

# PowerShell twin of _BASH_ENV_PREFIX_INVOKES_RE. PowerShell separates statements
# with `;` or a newline rather than by juxtaposition, so "a command follows" means
# a separator and then a real token -- `$env:VAR=1; claude` invokes; a bare
# `$env:VAR='1'` does not. One rule covers all three arms above.
_PS_ENV_PREFIX_TARGET_RE = re.compile(r"^[^\n;|&]*[;\n][ \t]*([^\s;|&]+)")


def _ps_occurrence_is_benign(match: "re.Match[str]", command: str) -> bool:
    # ⚠ ONLY the anchored `$env:` arm gets the carve-out. `Set-Item` and
    # `SetEnvironmentVariable` are deliberately unanchored (they read far less
    # naturally inside prose), and handing THEM a carve-out keyed on a trailing
    # `;` gave them an accidental anchor made of punctuation: the same prose
    # sentence was refused or allowed depending on whether it happened to contain
    # a semicolon. Those two arms keep denying unconditionally, exactly as before
    # -- uniform per arm, and no regression against HEAD.
    if not match.group("envcolon"):
        return False
    tail = command[match.end():]
    target = _PS_ENV_PREFIX_TARGET_RE.search(tail)
    if target is None:
        return False  # invokes nothing -> the deny stands
    # ⚠ Scan the WHOLE tail, not the first token after the separator, and not one
    # statement. Two reasons, and they pull the same way. (a) `$env:VAR=1; npx
    # claude` hides the launch behind a wrapper, so a first-token check misses it
    # exactly as the Bash one did. (b) PowerShell semantics differ from Bash: a
    # Bash `VAR=1 cmd` prefix scopes to that ONE command, but `$env:VAR` mutates
    # the running process, so EVERY later statement inherits it -- the variable
    # really does reach a `claude` three statements down.
    return not _statement_launches_claude(tail)


def _ps_harness_env_prefix_is_benign(command: str) -> bool:
    """PowerShell twin of ``_harness_env_prefix_is_benign``; same
    fail-toward-deny contract, same `claude` exception, same every-occurrence
    rule."""
    matches = list(_PS_HARNESS_ENV_PREFIX_RE.finditer(command))
    if not matches:
        return False
    return all(_ps_occurrence_is_benign(m, command) for m in matches)

# The PowerShell command position lives in `_bash_patterns` with the other
# primitives, because BOTH tiers need it: the hard records below and
# `_speedbump._pred_rmrf`. It was defined here first and the soft tier kept
# matching bare -- so a `#` comment quoting the pattern cleared the hard deny
# and then tripped the speed bump instead. One definition, both tiers.
_PS_CMD_POS = _bash_patterns._PS_CMD_POS
#: Same reason, same module: the hard records below and `_speedbump._pred_rmrf`
#: must enrol an added alias at the same moment. Two FAIL-OPENS predating this
#: change were found by a must-deny corpus on 2026-08-24 and are closed by
#: building the records from it -- `ri -Recurse -Force C:\\` slipped because the
#: records demanded the literal cmdlet name, and `Remove-Item C:\\ -Force
#: -Recurse` slipped because both hard-coded Recurse-before-Force. Neither is a
#: friction bug; both are genuine catastrophic deletes the guard let through, at
#: HEAD and for as long as the records have existed.
_PS_REMOVE_VERB = _bash_patterns._PS_REMOVE_VERB


DANGEROUS_PS_PATTERNS: tuple[BashPatternRecord, ...] = (
    # The switches by every spelling that runs (DEF-822): the unambiguous
    # cmdlet prefixes (`-r -fo`), the long forms, and the /bin/rm clusters
    # pwsh hands the native binary on a POSIX host (`-rf`). The fragments
    # are `_bash_patterns`' so the soft tier and these records read one
    # spelling set; they spelled `-Recurse` and `-Force` in full until
    # 2026-09-16 and `ri -r -fo C:\` drew nothing.
    BashPatternRecord(
        "ps-remove-item-recurse-force-prefix",
        re.compile(
            _PS_CMD_POS + _PS_REMOVE_VERB + _bash_patterns._QUOTED_VERB_TAIL
            + r"\s+" + _bash_patterns._PS_RECURSE_SWITCH
            + r"\s+" + _bash_patterns._PS_FORCE_SWITCH, re.IGNORECASE,
        ),
    ),
    BashPatternRecord(
        "ps-remove-item-recurse-force-mixed",
        # Spans bounded `{0,200}` (not unbounded `.*`): an unbounded form is
        # quadratic on a repeated-token payload scanning toward an absent
        # `-Force` (a hook-runtime ReDoS — `tests/test_redos.py` dot-star gate).
        # Detection-preserving: real `Remove-Item … -Recurse … -Force` flag
        # clusters sit far inside 200 chars. The tail is the soft tier's:
        # either order, or one cluster carrying both letters.
        re.compile(
            _PS_CMD_POS + _PS_REMOVE_VERB + _bash_patterns._QUOTED_VERB_TAIL
            + r"\s+[^\n;|&]{0,200}?" + _bash_patterns._PS_RECURSIVE_FORCE_TAIL,
            re.IGNORECASE,
        ),
    ),
    BashPatternRecord(
        "ps-harness-env-prefix",
        _PS_HARNESS_ENV_PREFIX_RE,
        # Same message as the Bash twin: the operator-facing advice is identical
        # (set it in the parent shell before launching), and reusing the tested
        # template keeps this record inside test_template_contains_both_markers'
        # Don't/Do pairing check rather than growing a second, untested string.
        _denial_reasons.HARNESS_ENV_PREFIX_INLINE,
    ),
)


_resolve_project_root = _hook_utils.resolve_project_root


#: Secret-bearing paths denied at the HOOK layer -- for READS, not just writes.
#:
#: These are the exact five shapes espalier used to emit as Claude Code
#: `Read()` deny rules in `settings_profiles._DENY_DEFAULTS`. They moved here
#: because configuring ANY `Read()` deny rule arms a static-resolvability
#: requirement in Claude Code: it must prove which files a Bash command reads
#: before running it, and a command it cannot prove -- one with a `cd`, a
#: relative `--include` glob, or a glob over an unenumerable directory --
#: raises a permission prompt that `allow` rules and bypassPermissions cannot
#: override, because deny outranks both. Verified from the binary's own message
#: text: "cannot be resolved statically while a Read() deny rule is
#: configured". The Bash deny entries stay in settings; only `Read()` arms it.
#:
#: ⚠ FRICTION LAYER, NOT A SECURITY BOUNDARY (STANDING_PRINCIPLES §2). The Bash
#: arm matches literal path tokens. It catches `cat .env` and `grep -r x
#: secrets/`; it does NOT catch a token assembled at runtime, read through a
#: command substitution, or reached via a symlink. Motivated bypass was never
#: in scope for the `Read()` rules either -- those were a permission-layer
#: convenience, and this is the same coverage at the same honesty level.
_SECRET_PATH_LABEL = {
    "env": ".env / .env.*",
    "secrets": "secrets/**",
    "aws": "**/.aws/credentials",
    "creds": "**/credentials.json",
}
#: A dotenv TEMPLATE is secret-free by convention -- `.env.example`,
#: `.env.sample`, `.env.template`, `.env.dist` are the files a repo commits
#: so a newcomer can copy one to `.env` and fill it in. The read and move
#: legs took every `.env.` prefix, so `cat .env.example` and `mv
#: .env.example docs/` were refused as secret reads (DEF-816, driven at HEAD
#: 2026-09-15 on the Read tool, Bash and PowerShell). END-OF-NAME ONLY, so
#: `.env.example.bak` and `.env.local` stay refused: the suffix must be the
#: last thing the name says, or it is a real dotenv under another name.
_DOTENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")


def _secret_pattern_for(raw: str) -> str | None:
    """Return the secret-path label ``raw`` matches, else None.

    Token-precise rather than substring: `grep -n '\\.env\\b' file` must NOT
    match, or the guard would deny the very greps used to audit for secrets.
    The `secrets/` arm additionally REQUIRES a slash in the token, so the bare
    English word in `echo "no secrets here"` is not a path and does not deny.
    """
    # Strip shell quoting AND trailing punctuation. Measured: without the
    # second strip, the token `config/.env.production"},` (a path quoted inside
    # a larger literal) still matched `.env.*` -- a false positive that fired
    # on the guard's own test fixture.
    tok = raw.replace("\\", "/").strip().strip("'\"").rstrip(",;:)]}\"'")
    if not tok or tok.startswith("-"):
        return None
    stripped = tok.rstrip("/")
    if not stripped:
        return None
    name = stripped.rsplit("/", 1)[-1]
    # The dotenv NAME is compared case-folded (Windows and default macOS
    # volumes fold case, so `.ENV` is the dotenv file there; DEF-718 lane).
    # The other three arms stay case-sensitive on purpose: a first cut folded
    # the whole token and denied `Read src/Secrets/Config.java` on a
    # case-sensitive tree -- a routine directory name in .NET and Java
    # repos, and `Edit` is a content-surfacing tool too (review, driven).
    lname = name.lower()
    if (lname == ".env" or lname.startswith(".env.")) and not lname.endswith(
        _DOTENV_TEMPLATE_SUFFIXES
    ):
        return _SECRET_PATH_LABEL["env"]
    if name == "credentials.json":
        return _SECRET_PATH_LABEL["creds"]
    if stripped.endswith(".aws/credentials"):
        return _SECRET_PATH_LABEL["aws"]
    if "/" in tok and (
        stripped == "secrets"
        or stripped.startswith("secrets/")
        or "/secrets/" in "/" + stripped
    ):
        return _SECRET_PATH_LABEL["secrets"]
    return None


#: Bash verbs that READ a file's contents into the transcript. The Bash arm
#: requires one of these AND a secret path token in the same statement.
#: `_PS_SECRET_READ_VERBS` below is the PowerShell twin, class for class.
#:
#: ⚠ Scanning every token of the command instead was tried first and REJECTED on
#: measurement: it denied its own test script, because a heredoc that merely
#: MENTIONS `.env` contains the token. A guard that blocks writing the tests and
#: docs for itself is worse friction than the prompts it replaces -- and it
#: would have shipped, because the deny looked like the guard working.
_SECRET_READ_VERBS = frozenset({
    "cat", "bat", "less", "more", "head", "tail", "nl", "tac",
    "xxd", "od", "strings", "base64", "openssl",
    "cp", "scp", "rsync", "install",
    "source", ".", "dotenv", "env",
    # Stream editors print by effect (§C52, DEF-796's read-by-effect
    # sibling): `sed -n p <secret>` surfaces the file as `cat` does. The
    # in-place spelling is refused too -- a documented friction, not a leak.
    "sed", "awk", "gawk", "mawk", "nawk",
})
#: The copiers on the roster: their SOURCE is the read, their LAST positional
#: a destination, and a write to a secret path surfaces nothing (the leg's
#: own rule for `>` and `tee`), so `cp .env.example .env` -- the command
#: every README hands a newcomer -- must not be refused for its destination
#: (DEF-823, the code review of the DEF-816 lane; driven: the leg yielded
#: `['.env.example', '.env']` and the predicate took the second). Under a
#: target-directory flag (`-t DIR`, `-tDIR`, a cluster ending in `t`,
#: `--target-directory[=DIR]`) every positional is a source and nothing is
#: dropped; the over-read direction is the fail-safe one, so a flag's
#: separate value (`install -m 644`) stays a spurious read of a non-secret
#: token the predicate then ignores. `Copy-Item`'s twin is
#: `_ps_copier_sources`.
_COPIER_VERBS = frozenset({"cp", "scp", "rsync", "install"})
_PS_COPIER_VERBS = frozenset({"copy-item", "cpi", "copy", "cp", "robocopy", "xcopy"})


def _is_target_directory_flag(token: str) -> bool:
    if token.startswith("--"):
        return token.startswith("--target-directory")
    return token.startswith("-t") or (len(token) > 1 and token.rstrip("=")[-1] == "t")


def _copier_sources(operands: list[str]) -> list[str]:
    """``operands`` (the tokens after a copier verb, flags included) minus
    the destination: the last positional, unless a target-directory flag
    makes every positional a source or there is only one positional."""
    positionals = [t for t in operands if not t.startswith("-")]
    if len(positionals) < 2 or any(
        _is_target_directory_flag(t) for t in operands if t.startswith("-")
    ):
        return operands
    last = len(operands) - 1 - operands[::-1].index(positionals[-1])
    return operands[:last] + operands[last + 1:]


def _ps_copier_sources(tokens: list[str]) -> list[str]:
    """The PowerShell twin of `_copier_sources` over the tokens after a
    copier head: the value of a `-Destination` switch (any unambiguous
    prefix of three letters or more, blank- or colon-bound) is the
    destination, else the last positional is; every other operand and every
    other colon-bound switch value is read as the leg reads it."""
    out: list[str] = []
    positionals: list[str] = []
    dest_named = False
    take_next = False
    for token in tokens:
        if take_next:
            take_next = False
            continue
        if token.startswith(("#", ">")) or token in ("<", ">"):
            break
        if token.startswith("-"):
            name, _, value = token.lower().partition(":")
            if len(name) >= 3 and "-destination".startswith(name):
                dest_named = True
                take_next = not value
                continue
            if value:
                out.append(token.split(":", 1)[1])
            continue
        positionals.append(token)
        out.append(token)
    if not dest_named and len(positionals) >= 2:
        last = len(out) - 1 - out[::-1].index(positionals[-1])
        out = out[:last] + out[last + 1:]
    return out

#: The effects of the remove/relocate reader each leg consumes (§C52). The
#: zone check refuses a delete, a move, a narrowed `find` sweep rooted in
#: the zone, and a `git clean` that takes it; the secret check reads a move,
#: an archive or `dd` input, a link target and an interpreter literal read
#: -- each the slip `cp` already refuses, spelled differently: a copy by
#: effect of the same bytes. A delete or a write of a secret surfaces
#: nothing and stays out of the secret leg.
_ZONE_EFFECTS = frozenset({"delete", "move", "sweep", "clean"})
_SECRET_EFFECTS = frozenset({"move", "archive", "alias", "read"})
#: The stream editors: a print of the file is a read by effect; an in-place
#: edit (`-i`, `--in-place`, awk's `-i inplace`) is a write and surfaces
#: nothing, and the editor's PROGRAM operand is not a path (review: a `sed`
#: substitution that mentions `.env` read as the file).
_STREAM_EDITORS = frozenset({"sed", "awk", "gawk", "mawk", "nawk"})

_STATEMENT_BOUNDARY_RE = re.compile(r"[;\n]|\|\||&&|\|")

#: PowerShell verbs that READ a file's contents into the transcript -- the
#: bash roster's classes, spelled for the shell that will run them (DEF-718:
#: `Get-Content .env`, `gc .env`, `type .env` and `Get-Content
#: ~/.aws/credentials` all ALLOWED on the PowerShell tool while `cat .env`
#: denied on both, because `cat` happens to be a PowerShell alias with the
#: bash spelling and the roster was read through the bash statement grammar).
#: Lower-cased: PowerShell command names are case-insensitive. The bash roster
#: is INCLUDED whole: pwsh runs any executable on PATH, and `head -5 .env`,
#: `base64 .env` or `scp .env host:` (OpenSSH ships in-box on Windows) are
#: spellings an agent writes on this tool -- a first cut REPLACED the roster
#: and traded seventeen verbs for five (review, driven A/B). The class pin in
#: `tests/test_write_guard.py::TestSecretPathAccess` holds every bash verb to
#: this roster and every native verb to a bash class.
_PS_SECRET_READ_VERBS = _SECRET_READ_VERBS | frozenset({
    # viewers: cat / less / more / head / tail / nl / tac
    "get-content", "gc", "cat", "type", "more",
    # byte dumpers: xxd / od / strings / base64 / openssl
    "format-hex", "fhx", "certutil",
    # record readers: a dotenv read as records still lands in the transcript
    "import-csv", "ipcsv", "import-powershelldatafile",
    # copiers: cp / scp / rsync / install -- the SOURCE token is the read
    # (a move is read by EFFECT since §C52, through the remove/relocate
    # reader, not by this roster)
    "copy-item", "cpi", "copy", "cp", "robocopy", "xcopy",
    # dot-source: source / .
    ".",
})

#: PowerShell statement boundaries for the secret-read leg: the separator set
#: of `_bash_patterns._PS_CMD_POS_SEP` -- `=` opens a command position there
#: (`$x = Get-Content .env` RUNS the read), and so do `(` `{` and `&`. Every
#: one of these is blanked inside a string or a comment by the masker, which
#: is what keeps a mention (`Write-Host 'run Get-Content .env'`) a mention.
_PS_STATEMENT_BOUNDARY_RE = re.compile(r"[;\n\r(){}&|=]+")
#: A `(` glued to a word, `@` or `$` opens an ARGUMENT (`Get-Content(".env")`,
#: `gc(".env")`, `Get-Content @(".env")`, `$(".env")`), all ordinary
#: PowerShell that reads the file; as a statement boundary it severed the
#: operand from its head (review, driven ALLOWING). Replaced by a blank
#: before the cut; a `(` after a blank, `=` or `|` is still a boundary, so
#: `Invoke-Expression (Get-Content .env)` keeps its inner head.
_PS_GLUED_PAREN_RE = re.compile(r"(?<=[\w@$])\(")
#: Operands split on blanks AND commas: `Get-Content a.txt,.env` is an array
#: of two paths to PowerShell and one token to a blank splitter.
_PS_SECRET_TOKEN_SPLIT_RE = re.compile(r"[\s,]+")


def _secret_read_targets(command: str, _depth: int = 0) -> list[str]:
    """`_secret_read_targets_one` over every reading the walls judge
    (`_bash_patterns._wall_readings`): the command as spelled and, when a
    literal binding changes it, with the binding inlined. The union: a
    reading can only add a target. Until DEF-848's lane this leg read the
    spelling alone, and a secret read held in a variable the shell then runs
    (`eval "$v"`, `bash -c "$v"`) was refused only by accident -- the masker
    failed on the quoted value and the raw text put the read at a command
    position; the lane made the masker read the value, which took the
    accident away (the failure-mode review, measured)."""
    out: list[str] = []
    for text in _bash_patterns._wall_readings(command):
        for path in _secret_read_targets_one(text, _depth):
            if path not in out:
                out.append(path)
    return out


def _secret_read_targets_one(command: str, _depth: int = 0) -> list[str]:
    """Path tokens read by a recognized read verb, per statement.

    Statement-scoped so `ls docs/ && cat .env` is caught while
    `grep -rn '\\.env\\b' docs/` is not: grep is not a read verb, and its
    `.env` is a PATTERN, not a path. Pairing verb-with-path is what keeps this
    from denying ordinary work that names these files -- and the statements
    are cut from the MASKED command, so a bar inside that pattern
    (`"heredoc\\|cat \\.env"`) is not a boundary either.
    """
    # A HEREDOC BODY IS DATA, NOT COMMANDS. Measured: without this truncation
    # the guard denied its own test file being written, because
    # `cat >> tests/x.py <<'EOF'` followed by a body line containing
    # `"ls docs/ && cat .env",` splits into a statement whose verb IS `cat`.
    # Authoring a test or doc that QUOTES a secret-reading command is not
    # reading a secret, and a guard that cannot tell the difference blocks the
    # work of documenting itself.
    #
    # MASK FIRST, THEN SPLIT. The first version split the RAW command, so a
    # separator inside a quoted span was a statement boundary: `grep -rn
    # "heredoc\\|cat \\.env" docs/` produced a phantom statement whose verb IS
    # `cat`, and the guard denied a search for its own row's evidence (DEF-681,
    # three live hits in one session). The protected-zone leg had masked all
    # along; this leg is its sister and now does the same. The heredoc cut
    # keeps its job and moves: the `<<` is found in the MASKED string, where an
    # operator inside a quoted span has been blanked, and the cut lands at the
    # RAW newline at the same offset -- masking keeps offsets, and a masked
    # quoted heredoc body has lost its newlines, which is why a newline search
    # over the masked text found nothing and would have regressed the body
    # protection. Residue, stated: when a head is not on the non-reparsing
    # roster the masker returns the command raw, and a quoted separator in
    # such a command is still a boundary here.
    # This leg segments on newlines, so it must splice continuations FIRST or
    # `cat \` + newline + `.env` reads as two statements (the splicer's own
    # docstring names this class; DEF-701 reached the leg). Splice the RAW
    # command and derive the mask from it: the heredoc cut below indexes
    # `command` by a masked offset, so both must be the same text.
    command = _bash_patterns.splice_line_continuations(command)
    masked = _bash_patterns.mask_inert_syntax(command)
    scan = masked  # the uncut twin: a heredoc body IS the program for the shell arm below
    heredoc = masked.find("<<")
    if heredoc != -1:
        line_end = command.find("\n", heredoc)
        masked = masked[:line_end] if line_end != -1 else masked

    out: list[str] = []
    for statement in _STATEMENT_BOUNDARY_RE.split(masked):
        tokens = [t for t in _TOKEN_SPLIT_RE.split(statement.strip()) if t]
        if not tokens:
            continue
        verb = tokens[0].rsplit("/", 1)[-1]
        if verb not in _SECRET_READ_VERBS:
            continue
        if verb in _STREAM_EDITORS:
            if _stream_editor_in_place(tokens[1:]):
                continue                  # a write: it surfaces nothing
            tokens = [tokens[0]] + _stream_editor_file_operands(tokens[1:])
        # Stop at a redirect: in `cat .env > /tmp/x` the SOURCE is the read and
        # is still caught, but `/tmp/x` is a write target and must not be
        # mistaken for one -- otherwise `cat x > secrets/out` would report the
        # wrong path in the deny reason.
        read: list[str] = []
        for token in tokens[1:]:
            if token.startswith(">") or token in ("<", ">"):
                break
            # A `#` that starts a token opens a comment (the masker keeps the
            # character and blanks what follows), so `cat README.md # not
            # .env` names no secret; the PowerShell twin stops the same way.
            if token.startswith("#"):
                break
            read.append(token)
        # A copier's destination is a write, not a read (DEF-823).
        out.extend(_copier_sources(read) if verb in _COPIER_VERBS else read)
    # A PowerShell program behind `powershell` / `pwsh` (DEF-637): read with
    # the PowerShell roster and statement grammar, one level down. The
    # heredoc cut above is why `scan` is the uncut twin: for `pwsh -Command -
    # <<'EOF'` the body is the program, not data.
    if _depth < _bash_patterns._PS_STDIN_MAX_DEPTH:
        for program in _bash_patterns._shell_program_bodies(command, scan):
            out.extend(_ps_secret_read_targets(program, _depth + 1))
        # What a program under a reader head hands to a shell (447-A step 3):
        # `python3 -c 'os.system("cat .env")'`, `git -c core.pager='cat .env'`.
        for program in _bash_patterns._shell_out_program_bodies(command, scan):
            out.extend(_secret_read_targets(program, _depth + 1))
        # A POSIX shell's `-c` word (§C52): the roster above sees `sh` as the
        # statement's verb and nothing past it; the read sits in the program.
        for program in _bash_patterns._posix_shell_c_bodies(command, scan):
            out.extend(_secret_read_targets(program, _depth + 1))
    # The operands a verb relocates, archives, aliases or reads by an
    # interpreter literal (§C52, DEF-796): the same slip as `cp`, spelled
    # differently. Read once at the top level; the reader descends nested
    # programs itself.
    if _depth == 0:
        for effect, path in _bash_patterns.iter_removed_or_relocated_operands(command):
            if effect in _SECRET_EFFECTS:
                out.append(path)
    return out


def _stream_editor_in_place(args: list[str]) -> bool:
    """True for `sed -i[SUFFIX]`, `--in-place[=SUFFIX]` and awk's `-i inplace`."""
    return any(tok == "-i" or tok.startswith(("-i", "--in-place")) for tok in args)


def _stream_editor_file_operands(args: list[str]) -> list[str]:
    """The FILE operands of a sed/awk argument list: every `-e`/`-f`
    (`--expression`/`--file`) value is dropped, and when neither is given
    the first non-flag token is the program and is dropped too."""
    out: list[str] = []
    skip = False
    scripted = any(t in ("-e", "-f") or t.startswith(("--expression", "--file", "-e", "-f"))
                   for t in args)
    program_seen = scripted
    for tok in args:
        if skip:
            skip = False
            continue
        if tok in ("-e", "-f", "--expression", "--file"):
            skip = True
            continue
        if tok.startswith("-"):
            continue
        if not program_seen:
            program_seen = True
            continue
        out.append(tok)
    return out


def _ps_secret_read_targets(command: str, _depth: int = 0) -> list[str]:
    """Path tokens read by a recognized PowerShell read verb, per statement --
    the PowerShell twin of `_secret_read_targets` (DEF-718).

    Reads the scan text (`powershell_scan_text`: masked, backtick
    continuations joined), so a separator inside a string or a comment is not
    a boundary and a here-string's lines are one token run, then cuts
    statements on PowerShell's own separator set (`=` included: an assignment
    RUNS its right-hand side). The head is the first token with any quotes,
    path and `.exe` stripped (`& 'Get-Content' .env`, `C:\\Windows\\System32\\
    certutil.exe -encode .env x`); `return`/`throw` before it are skipped. A
    switch's colon-bound value (`-Path:.env`) is an operand; a bare `#` or a
    redirect ends the operands; a `(` glued to the head or to `@`/`$` opens
    an argument (`_PS_GLUED_PAREN_RE`), a free-standing one a statement.
    Declared limit: `foreach ($l in Get-Content .env)` -- `in` is a word,
    not a separator, and a word boundary cannot be masked inside a string,
    so it stays out of the cut set.
    """
    scan = _PS_GLUED_PAREN_RE.sub(" ", _bash_patterns.powershell_scan_text(command))
    out: list[str] = []
    for statement in _PS_STATEMENT_BOUNDARY_RE.split(scan):
        tokens = [t for t in _PS_SECRET_TOKEN_SPLIT_RE.split(statement.strip()) if t]
        if tokens and tokens[0].lower() in ("return", "throw"):
            tokens = tokens[1:]
        if not tokens:
            continue
        head = tokens[0].strip("'\"").replace("\\", "/").rsplit("/", 1)[-1].lower()
        if head.endswith(".exe"):
            head = head[:-4]
        if head not in _PS_SECRET_READ_VERBS:
            continue
        if head in _PS_COPIER_VERBS:
            out.extend(_ps_copier_sources(tokens[1:]))   # the destination is a write (DEF-823)
            continue
        for token in tokens[1:]:
            if token.startswith(("#", ">")) or token in ("<", ">"):
                break
            if token.startswith("-"):
                if ":" in token:
                    out.append(token.split(":", 1)[1])
                continue
            out.append(token)
    # A bash program behind `bash -c` / `sh -c` (DEF-637): read with the bash
    # roster and statement grammar, one level down.
    if _depth < _bash_patterns._PS_STDIN_MAX_DEPTH:
        raw, pair = _bash_patterns.powershell_scan_pair(command)
        for program in _bash_patterns._ps_shell_program_bodies(raw, pair):
            out.extend(_secret_read_targets(program, _depth + 1))
    # The PowerShell twin of the Bash leg's effect read (§C52, DEF-796).
    if _depth == 0:
        for effect, path in _bash_patterns.iter_ps_removed_or_relocated_operands(command):
            if effect in _SECRET_EFFECTS:
                out.append(path)
    return out


def check_secret_path_access(tool_name: str, tool_input: dict, root: Path) -> int:
    """Deny reads/writes of secret-bearing paths, for READ-ONLY tools too.

    Wired BEFORE ``_run_main``'s read-only early return, because ``Read`` and
    ``Grep`` are not in ``MUTATION_TOOLS`` and would otherwise pass untouched --
    which is the whole point: this replaces a Read()-tool deny rule.
    """
    candidates: list[str] = []
    if tool_name in _CONTENT_SURFACING_TOOLS:
        for key in ("file_path", "notebook_path", "path"):
            value = tool_input.get(key)
            if isinstance(value, str):
                candidates.append(value)
    command = tool_input.get("command")
    if isinstance(command, str):
        # The shell that will run the command decides the grammar (DEF-718):
        # the PowerShell tool's roster and statement cut, the bash ones for
        # Bash and for any other tool that carries a `command`.
        if tool_name == "PowerShell":
            candidates.extend(_ps_secret_read_targets(command))
        else:
            candidates.extend(_secret_read_targets(command))
    for raw in candidates:
        pattern = _secret_pattern_for(raw)
        if pattern:
            return _audit_deny(
                root,
                "pretooluse_blocked_secret_path",
                _denial_reasons.SECRET_PATH_ACCESS.format(
                    target=raw.strip().strip("'\"") or raw, shape=pattern,
                ),
                tool=tool_name,
                shape=pattern,  # the matched rule; the target itself stays out of the log
            )
    return 0


#: Tools whose use SURFACES a file's contents into the transcript. This set IS
#: the parity boundary with the `Read()` deny rules this check replaces.
#:
#: Excludes `Write` deliberately. The rationale for denying a secret path is
#: exfiltration, not tamper: whatever is READ is persisted to the transcript on
#: disk, sent to the API, and can reach a committed blueprint or memory row.
#: `Write` creates or overwrites and surfaces nothing, so denying it buys no
#: confidentiality while costing a common, legitimate operation.
#:
#: MEASURED, not reasoned: a first cut collected `file_path` for EVERY tool and
#: denied `Write .env.example` -- a template with no secrets in it that the
#: rules being replaced never blocked. That would have shipped as a silent
#: scope EXPANSION underneath a README line claiming "reads of those paths are
#: denied", i.e. a doc that was false about its own guard.
#:
#: `Edit`/`NotebookEdit` ARE included: both need the file's existing content to
#: compute their change, so they read it.
_CONTENT_SURFACING_TOOLS = frozenset({"Read", "Edit", "NotebookEdit", "Grep"})


def deny(reason: str) -> int:
    """Print deny JSON and return exit 0.

    Per Claude Code hook protocol: JSON on stdout is only processed on exit 0.
    Exit 2 would be ignored. See docs/SHARP_EDGES.md "Hook Exit Codes -- Channel XOR".
    """
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output))
    # Truthy-zero so `rc = check(...); if rc: return rc` dispatch short-circuits
    # after a deny (no second decision JSON), while the exit code stays 0
    # (channel-XOR). See _hook_utils._DeniedExit.
    return _hook_utils.DENIED


def _audit(root: Path, event_type: str, **details: object) -> None:
    """Best-effort append to the ``~/.espalier/audit`` log. Visibility layer,
    not a security boundary — a write failure must never make the hook raise,
    and the hook protocol forbids stderr noise on a deny path (channel-XOR).
    Single owner of write_guard's audit-swallow: the kill-switch, every
    protected-zone deny, the secret-path deny, the speed-bump fire and the
    dangerous-command dispatch all route here, so a newly-added denial site
    can't silently diverge from the log (``tests/test_governance_audit_log.py``
    discovers every bare ``deny`` and requires it audited or fail-closed)."""
    try:
        # ``quiet``: the writer's own OSError branch would otherwise warn on
        # stderr, beside the deny JSON on stdout.
        _integrity.append_audit(root, {"event_type": event_type, "details": details}, quiet=True)
    except Exception:  # noqa: BLE001, S110 -- audit best-effort; hook protocol forbids stderr noise
        pass


def _record_maintenance_bypass(root: Path) -> None:
    """One advisory audit record per session when MAINTENANCE_MODE switches the
    protected-zone check off (DEF-789; plan_guard and stop_gate write the
    sibling records for theirs). Nothing was blocked, so it is in neither tier
    of ``/status --log`` and is counted on its own line -- without it a day on
    which the anti-self-disable floor was bypassed all day reads as clean.
    Record first, then the shared per-hook guard ``_integrity`` owns and
    session_start clears; everything best-effort, because a reporter on the
    allow path never raises and never prints."""
    try:
        if _integrity.maintenance_bypass_recorded(root, "write_guard"):
            return
        _audit(root, "pretooluse_bypassed_maintenance_mode", hook="write_guard", check="protected-zone")
        _integrity.mark_maintenance_bypass_recorded(root, "write_guard")
    except Exception:  # noqa: BLE001, S110 -- audit best-effort; the allow path stays silent
        pass


def _audit_deny(root: Path, event_type: str, reason: str, **details: object) -> int:
    """``_audit`` then ``deny`` — the audited-denial funnel. Every classified
    protected-zone deny routes through here (details are metadata-only: the
    channel, the repo-relative path, and the matched rule — never file
    contents)."""
    _audit(root, event_type, **details)
    return deny(reason)


def _checkout_note(base: Path, root: Path) -> "tuple[str, dict[str, object]]":
    """``(suffix, details)`` naming the checkout a denied target sits in when it
    is not the project root -- a registered worktree (DEF-743). The deny reason
    gets `` (in checkout <spelling>)`` after the path and the audit row a
    ``checkout`` field, because a path relative to the worktree reads exactly
    like the root's copy of the same file: an operator shown ``espalier/cli.py``
    blocked looks at the root, finds nothing wrong there, and blames the guard.
    The spelling is root-relative for a worktree under the root, absolute for
    one beside it."""
    if base == root:
        return "", {}
    base_posix = str(base).replace("\\", "/")
    rel = _hook_utils._rel_under_root(base_posix, str(root).replace("\\", "/").rstrip("/"))
    spelling = rel or base_posix
    return f" (in checkout {spelling})", {"checkout": spelling}


# Adopter escape hint appended to protected-zone denies. Names the legitimate
# bypass (ESPALIER_MAINTENANCE_MODE) and the precondition (parent-shell env
# at launch). Mid-session export does not propagate to already-running hook
# subprocesses; the env var is read at the parent shell that spawns Claude
# Code. See CLAUDE.md "Maintenance mode".
# The relaunch is spelled by _maintenance_mode.relaunch_hint(): host-keyed
# (PowerShell first on Windows -- the POSIX prefix is a parse error there) and
# carrying `--continue`, so following the remedy keeps the session the deny
# happened in instead of starting a fresh conversation (DEF-640 / DEF-676).
# Evaluated ONCE at import -- fine for a hook (each run is a fresh process),
# but a platform-sensitive test must reload this module via importlib, not
# monkeypatch sys.platform after a normal import.
_PROTECTED_ZONE_HINT = (
    " Harness self-edits: exit and relaunch with "
    f"{_maintenance_mode.relaunch_hint()} "
    "(env read at launch; mid-session export is ignored; --continue keeps "
    "this session). "
    "Do NOT disable hooks to proceed -- that loosens future safety."
)

def check_write_edit(tool_input: dict, root: Path) -> int:
    """Check Write/Edit/NotebookEdit tool calls.

    C1: missing or empty-string path is allowed (no path to act on,
    matches v0.6.x behavior). Truthy non-str payloads (int, list, dict,
    bool, None) are malformed and fail-closed via deny() -- the pre-fix
    shape raised TypeError, exited 1, and let the tool through per the
    Claude Code hook protocol (BC-023).

    Channel coverage: Write and Edit carry the target as ``file_path``, but
    ``NotebookEdit`` carries it as ``notebook_path`` (per the Claude Code Agent
    SDK reference). Reading ONLY ``file_path`` would skip EVERY NotebookEdit --
    both the protected-zone string check AND the inode backstop. So read BOTH,
    ``file_path`` first (precedence keeps Write/Edit unaffected; the fallback
    only fires when ``file_path`` is absent). plan_guard's twin extraction
    (``_run_main`` Write/Edit/NotebookEdit branch) shares this shape.
    """
    # Prefer file_path (Write/Edit); fall back to notebook_path (NotebookEdit)
    # ONLY when file_path is ENTIRELY ABSENT -- a present-but-null file_path must
    # still fail closed as malformed (BC-023 / test_null_file_path_denied), so use
    # `in` membership, not `.get()` (which conflates absent with present-null).
    if "file_path" in tool_input:
        file_path = tool_input["file_path"]
    elif "notebook_path" in tool_input:
        file_path = tool_input["notebook_path"]
    else:
        return 0
    if file_path == "":
        return 0
    if not isinstance(file_path, str):
        return deny(_denial_reasons.MALFORMED_WRITE_PAYLOAD.format(
            type_name=type(file_path).__name__,
        ))

    base, rel_path = _resolve_in_checkout(file_path, root)
    where, note = _checkout_note(base, root)

    if _is_protected(rel_path, root) and not _is_allowed(rel_path):
        return _audit_deny(
            root, "pretooluse_blocked_protected_zone",
            _denial_reasons.PROTECTED_ZONE_WRITE.format(
                path=rel_path + where, hint=_PROTECTED_ZONE_HINT,
            ),
            tool="write_edit", path=rel_path, rule="protected_write", **note,
        )

    # The path string is unprotected, but if it is a hardlink alias of a
    # protected file the write rewrites protected bytes (resolve() cannot follow
    # a hardlink). Inode-keyed backstop, gated on st_nlink>=2, stat-ed in the
    # checkout the target sits in.
    if _aliases_protected_inode(rel_path, root, base=base):
        return _audit_deny(
            root, "pretooluse_blocked_protected_zone",
            _denial_reasons.PROTECTED_ZONE_HARDLINK_INODE.format(path=rel_path + where),
            tool="write_edit", path=rel_path, rule="hardlink_inode", **note,
        )

    return 0


# The directory a command runs in (DEF-509): the payload's `cwd` and the
# command's own chain, read the same way by post_write_check -- both through
# `_hook_utils`, so the verdict and the registry payload name one place.
_payload_cwd = _hook_utils.payload_cwd
_join_directory = _hook_utils.join_directory
# One home since DEF-790 (`_bash_patterns.command_bases` and its two
# builders, moved out of this hook): the rm hard tier and the speed bump's
# defer read the same directories the protected-write checks below do, and
# `_speedbump` cannot import this hook (this hook imports it).
_Bases = _bash_patterns.Bases
_command_bases = _bash_patterns.command_bases
_directory_exists = _hook_utils.directory_exists   # the chain's oracle, one home
_bash_bases = _bash_patterns.bash_bases
_powershell_bases = _bash_patterns.powershell_bases


def check_bash_for_protected_mutations(command: str, root: Path, cwd: Path | None = None) -> int:
    """Deny Bash commands that MUTATE a protected path: a write into it by
    the common patterns, and (§C52) a delete of it or a move of it out of
    the zone, including of a directory that encloses it.

    ``cwd`` is the directory the command runs in (the hook payload's, which
    follows a ``cd`` from an earlier call); a ``cd`` inside the command moves
    the base for the statements after it (DEF-509)."""
    bases = _bash_bases(command, root, cwd)
    for raw in _bash_patterns._candidate_paths_from_bash(command):
        for at in bases(raw):
            base, rel = _resolve_bash_in_checkout(raw, root, base=at)
            where, note = _checkout_note(base, root)
            if _is_protected(rel, root) and not _is_allowed(rel):
                return _audit_deny(
                    root, "pretooluse_blocked_protected_zone",
                    _denial_reasons.PROTECTED_ZONE_WRITE_BASH.format(
                        path=rel + where, hint=_PROTECTED_ZONE_HINT,
                    ),
                    tool="bash", path=rel, rule="protected_write", **note,
                )
            # A redirect/tee/etc. target whose string is unprotected but whose
            # inode is a protected file's (a hardlink alias) rewrites protected
            # bytes -- catch the write-through (`echo evil > wg_alias`).
            if _aliases_protected_inode(rel, root, base=base):
                return _audit_deny(
                    root, "pretooluse_blocked_protected_zone",
                    _denial_reasons.PROTECTED_ZONE_HARDLINK_INODE.format(path=rel + where),
                    tool="bash", path=rel, rule="hardlink_inode", **note,
                )
    # The operand a verb REMOVES or RELOCATES (§C52, DEF-795): a delete of a
    # protected file or a move of it out of the zone is the write's twin --
    # the same slip, spelled differently -- and a directory that ENCLOSES a
    # protected path goes with it. The precedent in this file is the hardlink
    # check below, source-keyed since BC-015. The allowlist holds as for a
    # write. A recursive spelling on a zone directory, forced or not since
    # DEF-842, reaches here on its re-issue: the speed bump fires first, ahead of the maintenance
    # gate, keyed on the spelling and not on the operand -- it is not zone
    # coverage, and this loop is.
    for effect, raw in _bash_patterns.iter_removed_or_relocated_operands(command):
        if effect not in _ZONE_EFFECTS:
            continue
        for at in bases(raw):
            base, rel = _resolve_bash_in_checkout(raw, root, base=at)
            where, note = _checkout_note(base, root)
            if _mutated_zone(effect, rel, root):
                return _audit_deny(
                    root, "pretooluse_blocked_protected_zone",
                    _denial_reasons.PROTECTED_ZONE_MUTATION_BASH.format(
                        effect=_EFFECT_WORD.get(effect, effect), path=rel + where,
                        hint=_PROTECTED_ZONE_HINT,
                    ),
                    tool="bash", path=rel, rule="protected_" + effect, **note,
                )
    return 0


#: The operator-facing word for an effect the reader tags more finely.
_EFFECT_WORD = {"sweep": "delete", "clean": "delete"}


def _mutated_zone(effect: str, rel: str, root: Path) -> bool:
    """The zone verdict for one removed or relocated operand, by effect: a
    protected operand is refused for every effect; an ENCLOSING directory
    for a delete, a move or a `git clean` (the tree goes with it), never for
    a `sweep` (a narrowed `find` judges its root by itself: `find . -name
    '*.pyc' -delete` from the repo root is an everyday command); and the
    whole tree (`.`) only for a `git clean` with the ignored-files flag,
    which takes the gitignored protected files. The allowlist holds as for
    a write."""
    if _is_allowed(rel):
        return False
    if _is_protected(rel, root):
        return True
    if effect in ("delete", "move", "clean") and _encloses_protected(rel, root):
        return True
    return effect == "clean" and rel.strip("/") in ("", ".")


def check_bash_for_protected_hardlinks(command: str, root: Path, cwd: Path | None = None) -> int:
    """Deny ``ln``/``cp -l`` whose SOURCE (or any positional) is a protected-not-
    allowed file -- a hardlink aliases its bytes under a second name, so a later
    write through the alias rewrites the protected file.

    The dangerous positional is the SOURCE (the file aliased OUT), the INVERSE of
    ``check_bash_for_protected_symlinks``'s linkname capture -- a genuinely
    distinct check, not a widening of the symlink one. Allowlist-AWARE: aliasing
    an allowlist-writable file confers nothing; only a protected-NOT-allowed
    source is denied (mirrors the write-through semantics). The decisive close is
    the inode write-through backstop in ``aliases_protected_inode``; this is the
    early, clearer-message friction at creation time.
    """
    bases = _bash_bases(command, root, cwd)
    for raw in iter_hardlink_operands(command):
        for at in bases(raw):
            rel = _normalize_bash_path(raw, root, base=at)
            if _is_protected(rel, root) and not _is_allowed(rel):
                return _audit_deny(
                    root, "pretooluse_blocked_protected_zone",
                    _denial_reasons.PROTECTED_ZONE_HARDLINK_BASH.format(path=rel),
                    tool="bash", path=rel, rule="hardlink",
                )
    return 0


def check_bash_for_protected_symlinks(command: str, root: Path, cwd: Path | None = None) -> int:
    """Deny ``ln -s <target> <linkname>`` where ``linkname`` lands in a
    governed zone -- protected OR allowed-in-protected.

    Symlink creation is special: an allowlisted destination like
    ``cc/blueprints/`` legitimately accepts JSON file writes, but a
    SYMLINK at that path is an attack shape (it lets the reader follow
    the link to attacker-controlled content). The general bash-write
    check honors the allowlist (legitimate session_id JSON files land
    in ``cc/blueprints/``); this check explicitly bypasses the
    allowlist so a symlink can NEVER land in a governed zone.

    Corpus row BC-015. The matcher covers the glued (``ln -fs``), GNU long
    (``ln --symbolic``), and flag-separated (``ln -s -f t link``) spellings;
    the captured group is the operand span and `symlink_linkname` takes the
    last of at least two positionals, so a trailing flag, redirect, comment or
    subshell close cannot shift the pick (DEF-414b: `ln -s /tmp/evil <link> -v`
    read `-v` as the linkname and allowed the forge).

    Also covers ``cp -s`` / ``cp --symbolic-link`` (the other Bash
    symlink-creation verb), same allowlist-blind treatment.

    Reads the command the way the write extractor reads it
    (`_candidate_paths_from_bash`, through `_bash_patterns._extractor_pair`):
    capped, continuations spliced, literal bindings inlined, matched on the MASKED scan and the operand span
    read from the raw text at the match's offsets -- as its PowerShell twin
    `powershell_symlink_linknames` scans the masked text. Until 2026-09-19
    (DEF-848's lane) it read the raw command alone: a link named through a
    variable the shell goes on to run (`eval "$L"`, `bash -c "$l"`) was never
    read, and a separator inside a quoted value opened a command position
    there, so a message variable naming the forge was refused.
    """
    # Continuations spliced first, as the write extractor does (DEF-701): the
    # span regexes below now stop at a newline, so `ln -s t \` + newline +
    # `<link>` must be joined here or the link name is lost. The cap bounds the
    # binding pre-pass, which costs names times length.
    bases = _bash_bases(command, root, cwd)
    raw, scan = _bash_patterns._extractor_pair(command)
    for pattern in (_LN_S_RE, _CP_SYMLINK_RE):
        for m in pattern.finditer(scan):
            linkname = _bash_patterns.symlink_linkname(
                _bash_patterns.neutralise_redirect_ampersands(_bash_patterns.raw_span(raw, m, 1))
            )
            if linkname is None:
                continue
            for at in bases(linkname):
                rel = _normalize_bash_path(linkname, root, base=at)
                if _is_protected(rel, root):
                    return _audit_deny(
                        root, "pretooluse_blocked_protected_zone",
                        _denial_reasons.PROTECTED_ZONE_SYMLINK_BASH.format(
                            path=rel,
                        ),
                        tool="bash", path=rel, rule="symlink",
                    )
    return 0


def check_bash_dangerous_patterns(
    tool_input: dict, root: Path | None = None, cwd: Path | None = None,
) -> int:
    """Check Bash for dangerous patterns ONLY.

    ``cwd`` is the directory the command runs in (the payload's, DEF-790):
    with ``root``, a relative delete operand is read from it, moved by the
    command's own ``cd`` chain, before the recursive-delete classifier judges
    it -- so a ``cd ..`` followed by a delete of the checkout by its own name
    is the repo. Without it, the root.

    Separated from protected-path checks (see ``check_bash_for_protected_mutations``)
    so the MAINTENANCE_MODE bypass scopes only to friction (protected zones),
    not safety (rm -rf, fork bombs, etc.).

    ``root`` is optional so the existing call sites (and ~16 in tests) keep
    working. It is forwarded to the recursive-delete classifier, which uses it
    for one rule only: the repo directory and its ancestors are catastrophic.
    Omitting it narrows that classifier, never inverts it.
    """
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    reason = _bash_dangerous_reason(command, root, cwd=cwd)
    return deny(reason) if reason else 0


def _bash_dangerous_reason(
    command: str, root: Path | None, _depth: int = 0, cwd: Path | None = None,
) -> str | None:
    """`_bash_dangerous_reason_here`, judged inside
    `_bash_patterns.another_shells_program` one level down: every call with
    ``_depth > 0`` is a program another shell was handed (a `bash -c` body
    from PowerShell, a shell-out from another interpreter), which that shell
    places where the walk cannot follow. Derived here, never at the call
    site, so a new nested reader is flagged by construction (the lane's
    review: three hand-placed wraps, and no test for a fourth)."""
    if _depth > 0:
        with _bash_patterns.another_shells_program():
            return _bash_dangerous_reason_here(command, root, _depth, cwd)
    return _bash_dangerous_reason_here(command, root, _depth, cwd)


def _bash_dangerous_reason_here(
    command: str, root: Path | None, _depth: int = 0, cwd: Path | None = None,
) -> str | None:
    """The deny reason the Bash dangerous tier owes ``command``, or None.

    Split from ``check_bash_dangerous_patterns`` so the PowerShell tier can
    hand it a ``bash -c`` program (DEF-637) and it can hand a ``powershell
    -Command`` program back, each one level down; ``_depth`` bounds the
    exchange.
    """
    # Role-mapped so a MENTION is not read as an INVOCATION: the two literal
    # records below are command-position-anchored, and a markdown backtick, a `(`
    # inside double quotes or a `<<'EOF'` body all synthesised a command position
    # out of inert text. `mask_inert_syntax` substitutes separator characters only
    # -- token content is untouched, so the quote-splice spellings these records
    # exist to catch still match. It fails closed to the raw string.
    # Mask, then splice continuations (the segmenter's order; this tier only
    # searches): `ESPALIER_MAINTENANCE_MODE\` + newline + `=1 claude` is ONE
    # assignment to bash and was allowed here until 2026-09-06 (DEF-701).
    scan = _bash_patterns.splice_line_continuations(
        _bash_patterns.mask_inert_syntax(command)
    )
    for entry in DANGEROUS_BASH_PATTERNS:
        if entry.pattern.search(scan):
            # The env-prefix record is a habit-formation nudge, not a hazard, and
            # its lesson is false when the assignment actually invokes something.
            # Step aside there; every other record denies unconditionally.
            if entry.pid in _ENV_PREFIX_PIDS and _harness_env_prefix_is_benign(scan):
                continue
            # The literal star record reads the glob wherever it runs; the
            # classifier below reads it in the directory its statement runs
            # in (DEF-849). Step aside where the classifier finds no wall, so
            # a build directory cleared from inside meets the nudge, as the
            # classifier's own spellings of the same delete do.
            if entry.pid == "rm-rf-star" and not _bash_patterns.has_catastrophic_recursive_rm(
                command, str(root) if root else None, cwd=cwd or root,
            ):
                continue
            return entry.message or _denial_reasons.format_dangerous_bash(entry.pid)
    # Flag-order-independent backstop for the catastrophic recursive-delete
    # class. The two literal `rm -rf /` / `rm -rf *` records above match ONLY
    # the glued `-rf` order; `rm -fr /`, `rm -r -f /`, `rm --recursive --force /`,
    # `rm -rvf /*`, multi-operand `rm -rf x /`, and quoted `rm -rf "/"` bypass
    # them. _bash_patterns tokenizes each rm segment so the hard-deny is flag-
    # order-independent. Safety (not friction): this whole function runs even
    # under MAINTENANCE_MODE. See docs/SHARP_EDGES.md.
    # A relative operand is read from the directory the command runs in
    # (DEF-790): the payload cwd, moved per statement by the command's own
    # cd chain, each delete placed in its own statement. A nested program (a
    # `bash -c` body) starts from the payload cwd; the outer scan still reads
    # the delete it carries at the outer statement's directory. A program
    # handed ACROSS shells (a `pwsh -Command` body here, a `bash -c` body on
    # the PowerShell tool, a shell-out from another interpreter) has no outer
    # reading in its own language: it is judged inside
    # `_bash_patterns.another_shells_program`, from the unknown directory as
    # well as the payload cwd. Declared limit: not from the outer statement's
    # own directory, which only a non-glob target (`.`) would need.
    if _bash_patterns.has_catastrophic_recursive_rm(
        command, str(root) if root else None, cwd=cwd or root,
    ):
        return _denial_reasons.CATASTROPHIC_RM
    # The same wipe spelled through an enumerator (DEF-815): an un-narrowed
    # `find` with a delete action -- `find . -delete`, the rootless form,
    # `-exec` with a remove verb, `-type f` -- from a catastrophic root, read
    # from the same directory chain. Until 2026-09-15 no tier saw it: the
    # zone check judges the root by what it encloses and the repo root
    # answers False by design, and the classifier above is reached only from
    # the rm-shaped arms. A narrowed find is the zone check's (its root
    # judged by itself); every other root is the CP-RMRF nudge's.
    if _bash_patterns.has_catastrophic_find_delete(
        command, str(root) if root else None, cwd=cwd or root,
    ):
        return _denial_reasons.CATASTROPHIC_FIND_DELETE
    # The same wipe with its operands arriving on stdin (DEF-826): an
    # un-narrowed enumerator -- a find with no action, `ls` -- piped through
    # `xargs` into a remove verb, from a catastrophic root, read from the
    # same directory chain. Until 2026-09-16 no tier saw it on either tool:
    # the find arm needs a delete action, the remove verb behind the carrier
    # has no operand, and the speed bump had nothing to bump.
    if _bash_patterns.has_catastrophic_piped_remove(
        command, str(root) if root else None, cwd=cwd or root,
    ):
        return _denial_reasons.CATASTROPHIC_PIPED_REMOVE
    # The same wipe as a compound statement (DEF-830): the enumerator bound
    # to a loop variable and removed in the loop's body -- the pipe into a
    # read loop, a for loop over the substitution, a read loop fed at its
    # tail -- from a catastrophic root, read from the same directory chain.
    # Until 2026-09-17 the hard tier saw nothing here (the remove verb's
    # operand is the variable, not a path) and the soft tier answered with
    # its variable-operand nudge: one re-issue in front of the wipe. DEF-837
    # (2026-09-18): a for loop over a bare word list meets the same wall, its
    # words judged as the direct remove of the same words is.
    if _bash_patterns.has_catastrophic_loop_remove(
        command, str(root) if root else None, cwd=cwd or root,
    ):
        return _denial_reasons.CATASTROPHIC_LOOP_REMOVE
    # A PowerShell program behind `powershell` / `pwsh` (DEF-637) meets the
    # PowerShell records, one level down. A SECOND pair, in the extractor's
    # order (splice, then mask), so the two strings line up by offset for the
    # body slice; it need not equal `scan` above, which the records only
    # search. The pair is same-length by construction -- one spliced text,
    # and the masker preserves length -- whatever the head roster holds, and
    # `_shell_program_bodies` falls back to the raw text if that ever breaks.
    if _depth < _bash_patterns._PS_STDIN_MAX_DEPTH:
        # Over every reading the walls judge (`_wall_readings`): a program
        # that names a value through a variable the shell expands before the
        # interpreter starts (`os.system('$v')` inside a double-quoted
        # program) carries the value only in the inlined reading. Until
        # 2026-09-19 that program was refused by accident -- the masker failed
        # on the quoted assignment and the raw scan read the value's verb --
        # and DEF-848's lane took the accident away. A wall on either reading
        # is the wall, so the inlined one can only add a refusal.
        for text in _bash_patterns._wall_readings(command):
            spliced = _bash_patterns.splice_line_continuations(text)
            pair = _bash_patterns.mask_inert_syntax(spliced)
            # Each program is ANOTHER shell's: the receiving process places it
            # (its start switch, its own directory change), so the relief
            # judges it from the unknown directory as well (blocker condition
            # 2, its cross-shell arm) -- flagged by the reason function itself
            # at ``_depth > 0``.
            for program in _bash_patterns._shell_program_bodies(spliced, pair):
                reason = _ps_dangerous_reason(program, root, _depth + 1, cwd=cwd)
                if reason:
                    return reason
            # What a program under a reader head hands to a shell (447-A step
            # 3, DEF-761): the same records one level down. The text starts at
            # a command position of its own, which is what the raw scan behind
            # an off-roster head never gave a one-statement program.
            for program in _bash_patterns._shell_out_program_bodies(spliced, pair):
                reason = _bash_dangerous_reason(program, root, _depth + 1, cwd=cwd)
                if reason:
                    return reason
    return None


#: The DANGEROUS_PS_PATTERNS records the ephemeral-directory carve-out applies
#: to. DERIVED, never hand-listed: any record whose pid names the recursive
#: force-delete concept. A new recursive-delete record is enrolled on arrival
#: instead of quietly keeping the un-carved behaviour.
_PS_RECURSIVE_DELETE_PIDS = frozenset(
    e.pid for e in DANGEROUS_PS_PATTERNS if "remove-item-recurse-force" in e.pid
)

#: The records the "does the assignment actually invoke something?" carve-out
#: applies to, across BOTH shells. DERIVED from the pid, never hand-listed, so a
#: future shell's env-prefix record is enrolled on arrival rather than quietly
#: keeping the un-carved behaviour -- same discipline as the roster above.
_ENV_PREFIX_PIDS = frozenset(
    e.pid
    for e in (*DANGEROUS_BASH_PATTERNS, *DANGEROUS_PS_PATTERNS)
    if e.pid.endswith("harness-env-prefix")
)


def check_powershell(
    tool_input: dict, root: Path | None = None, cwd: Path | None = None,
) -> int:
    """Check PowerShell tool calls for dangerous patterns.

    ``cwd`` is the directory the command runs in (DEF-790): with ``root``, a
    plainly relative ``Remove-Item`` target is read from it, moved by the
    command's own ``Set-Location`` chain, and refused when it lands on the
    repo, a parent, home or a shallow system path. Without it, the root.

    ``root`` is optional like the Bash twin's: it reaches the Bash
    catastrophic-delete classifier only through a ``bash -c`` program
    (DEF-637), and omitting it narrows that classifier, never inverts it.

    Reads the MASKED command, exactly as `check_bash` reads
    `mask_inert_syntax(command)`. Until 2026-08-25 this leg read the raw string
    and was the only one that did, so its whole verdict rested on
    `_PS_CMD_POS` -- and the discriminator for an inert string turned out to be
    the last non-space character before the pattern. Driven against the real
    hook, 54 of 113 generated rows were false positives, every inert container
    among them, on the tier maintenance mode cannot bypass.

    The mask preserves length and offsets; the backtick-continuation join that
    follows it (`_bash_patterns.powershell_scan_text`) does not, so every
    operand helper below reads slices of the joined text and never an offset
    into `raw`. Without the join, `Remove-Item -Recurse` + backtick-newline +
    `-Force /` walked past the tier maintenance mode cannot bypass (driven).
    """
    raw = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    reason = _ps_dangerous_reason(raw, root, cwd=cwd)
    return deny(reason) if reason else 0


def _ps_dangerous_reason(
    raw: str, root: Path | None, _depth: int = 0, cwd: Path | None = None,
) -> str | None:
    """`_ps_dangerous_reason_here`, flagged one level down exactly as
    `_bash_dangerous_reason` is (a `pwsh -Command` body from Bash)."""
    if _depth > 0:
        with _bash_patterns.another_shells_program():
            return _ps_dangerous_reason_here(raw, root, _depth, cwd)
    return _ps_dangerous_reason_here(raw, root, _depth, cwd)


def _ps_dangerous_reason_here(
    raw: str, root: Path | None, _depth: int = 0, cwd: Path | None = None,
) -> str | None:
    """The deny reason the PowerShell dangerous tier owes ``raw``, or None --
    the twin of ``_bash_dangerous_reason``, split out for the same exchange."""
    # The pair, not the joined text alone: `_ps_shell_program_bodies` slices a
    # `bash -c` program out of the raw twin by offset (DEF-637).
    raw, command = _bash_patterns.powershell_scan_pair(raw)
    for entry in DANGEROUS_PS_PATTERNS:
        if entry.pattern.search(command):
            # ⚠ THREE-WAY TIERING, matching the Bash twin. The records carry no
            # operand analysis of their own -- `Remove-Item -Recurse -Force`
            # matches whatever follows -- so every one of these decisions is the
            # operand parser's, and its default is deny.
            #
            #   roster-ephemeral (`.\build`, `node_modules`)  -> allow outright
            #   plainly relative but not on the roster        -> FALL THROUGH to
            #       `_speedbump._pred_rmrf`, which asks once and clears on
            #       re-issue
            #   absolute / globbed / qualified / unparseable  -> hard deny
            #
            # The middle rung is new on 2026-08-24 and it is why: measured that
            # day, PowerShell HARD-denied nine of fifteen ordinary relative build
            # cleans, twice in a row, on the tier maintenance mode cannot bypass,
            # while Bash soft-bumped every one of the same nine and let the
            # second attempt through. The remaining move on Windows was to turn
            # the hooks off. A guard that refuses an ordinary build clean with no
            # way through does not get obeyed, it gets disabled.
            if entry.pid in _PS_RECURSIVE_DELETE_PIDS:
                # A relative target read from the directory the command runs
                # in (DEF-790: the payload cwd moved by its own Set-Location
                # chain) that lands on the repo, a parent, home or a shallow
                # system path is the wall whatever the roster says -- the
                # rule the Bash classifier applies first. Then the rungs.
                if _bash_patterns.powershell_removal_lands_catastrophic(
                    raw, str(root) if root else None, cwd or root,
                ):
                    return entry.message or _denial_reasons.format_dangerous_ps(entry.pid)
                if _bash_patterns.powershell_removal_is_recognized_safe(command):
                    continue
                if _bash_patterns.powershell_removal_is_plainly_relative(command):
                    continue  # -> soft speed-bump, not a wall
            # Same carve-out as the Bash twin: the env-prefix lesson is false
            # when the assignment actually invokes something.
            if (
                entry.pid in _ENV_PREFIX_PIDS
                and _ps_harness_env_prefix_is_benign(command)
            ):
                continue
            return entry.message or _denial_reasons.format_dangerous_ps(entry.pid)
    # A recursive remove WITHOUT the force switch (DEF-842), which the records
    # above never match: it still takes every item that is not hidden or
    # read-only, with no prompt when no terminal is attached (driven on pwsh
    # 7.6.5), so it meets the wall on a catastrophic target -- judged by the
    # sweep tier's judge, from the directory the command runs in. Every other
    # target is the CP-RMRF nudge's. Ahead of the maintenance gate, as the
    # records are.
    if _bash_patterns.powershell_recursive_removal_is_catastrophic(
        raw, str(root) if root else None, cwd or root,
    ):
        return _denial_reasons.CATASTROPHIC_PS_RECURSIVE_REMOVE
    # The sweeps pwsh runs that spell the same wipe (DEF-824, DEF-822): an
    # un-narrowed `find` with a delete action -- GNU find runs verbatim
    # under pwsh on a POSIX host, and until 2026-09-16 this tool had no arm
    # for it while the Bash tool walled it -- and an un-narrowed enumerator
    # piped into a remove verb that takes the whole tree (`gci -Recurse |
    # ri -r -fo`, `gci -r -File | ri`), each from a catastrophic root read
    # through the PowerShell directory chain. Ahead of the maintenance
    # gate, as the records are; the recursive-force pipeline meets the
    # records first, which read the enumerator's roots as its operands.
    if _bash_patterns.has_catastrophic_ps_sweep(
        raw, str(root) if root else None, cwd or root,
    ):
        return _denial_reasons.CATASTROPHIC_PS_SWEEP
    # A bash program behind `bash -c` / `sh -c` (DEF-637) meets the Bash
    # records and the catastrophic-delete classifier, one level down.
    if _depth < _bash_patterns._PS_STDIN_MAX_DEPTH:
        for program in _bash_patterns._ps_shell_program_bodies(raw, command):
            # another shell's program: judged from the unknown directory as
            # well (flagged by `_bash_dangerous_reason` at ``_depth > 0``)
            reason = _bash_dangerous_reason(program, root, _depth + 1, cwd=cwd)
            if reason:
                return reason
    return None


def check_powershell_for_protected_mutations(
    command: str, root: Path, cwd: Path | None = None,
) -> int:
    """Deny PowerShell commands that MUTATE a protected path (§C52: a
    delete of it, a move of it out of the zone, or of a directory that
    encloses it -- the second loop below), or that write to it via
    Set-Content / Out-File / Add-Content / redirect / Copy-Item /
    Move-Item (and their aliases) / the permission verbs icacls / attrib /
    Set-Acl / Set-ItemProperty (a permission change silences a hook as
    surely as a write) / etc. ``cwd`` and a ``Set-Location`` inside the
    command move the base a relative spelling resolves against (DEF-509)."""
    bases = _powershell_bases(command, root, cwd)
    for raw in _bash_patterns._candidate_paths_from_powershell(command):
        for at in bases(raw):
            # The Bash twin's shape, base included: the failure-mode review
            # drove this site as the sixth of a five-site fix (a worktree alias
            # allowed here while the Bash redirect beside it denied).
            base, rel = _resolve_bash_in_checkout(raw, root, base=at)
            where, note = _checkout_note(base, root)
            if _is_protected(rel, root) and not _is_allowed(rel):
                return _audit_deny(
                    root, "pretooluse_blocked_protected_zone",
                    _denial_reasons.PROTECTED_ZONE_WRITE.format(
                        path=rel + where, hint=_PROTECTED_ZONE_HINT,
                    ),
                    tool="powershell", path=rel, rule="protected_write", **note,
                )
            # Write-through to a hardlink alias of a protected file.
            if _aliases_protected_inode(rel, root, base=base):
                return _audit_deny(
                    root, "pretooluse_blocked_protected_zone",
                    _denial_reasons.PROTECTED_ZONE_HARDLINK_INODE.format(path=rel + where),
                    tool="powershell", path=rel, rule="hardlink_inode", **note,
                )
    # The Bash twin's second loop (§C52): the operand a verb removes or
    # relocates, and the directory that encloses a protected path.
    for effect, raw in _bash_patterns.iter_ps_removed_or_relocated_operands(command):
        if effect not in _ZONE_EFFECTS:
            continue
        for at in bases(raw):
            base, rel = _resolve_bash_in_checkout(raw, root, base=at)
            where, note = _checkout_note(base, root)
            if _mutated_zone(effect, rel, root):
                return _audit_deny(
                    root, "pretooluse_blocked_protected_zone",
                    _denial_reasons.PROTECTED_ZONE_MUTATION.format(
                        effect=_EFFECT_WORD.get(effect, effect).capitalize(),
                        path=rel + where, hint=_PROTECTED_ZONE_HINT,
                    ),
                    tool="powershell", path=rel, rule="protected_" + effect, **note,
                )
    return 0


def check_powershell_for_protected_symlinks(
    command: str, root: Path, cwd: Path | None = None,
) -> int:
    """Deny PowerShell ``New-Item -ItemType SymbolicLink`` whose link location
    (``-Path``/``-Name``) lands in a governed zone -- allowlist-blind, the
    PowerShell twin of ``check_bash_for_protected_symlinks``.
    The general write check is allowlist-AWARE, so a symlink into an
    allowlisted-in-protected path slipped through before."""
    bases = _powershell_bases(command, root, cwd)
    for raw in _bash_patterns.powershell_symlink_linknames(command):
        for at in bases(raw):
            rel = _normalize_bash_path(raw, root, base=at)
            if _is_protected(rel, root):
                return _audit_deny(
                    root, "pretooluse_blocked_protected_zone",
                    _denial_reasons.PROTECTED_ZONE_SYMLINK_PS.format(path=rel),
                    tool="powershell", path=rel, rule="symlink",
                )
    return 0


# MCP symlink-creation verbs. A symlink may NEVER land in a governed zone
# regardless of channel, so check_mcp treats a symlink-verb tool allowlist-BLIND
# (deny on _is_protected alone, like the Bash/PS twins). Matched on the action
# segment of mcp__<server>__<action>, separator-normalised so create_symlink /
# createSymlink / symbolic_link all match. ``unlink`` (delete) and ``hardlink``
# (the separate inode fix) are deliberately excluded.
def _is_mcp_symlink_verb(tool_name: str) -> bool:
    parts = tool_name.split("__")
    # >=2 so a non-canonical 2-segment name (mcp__symlink) still classifies.
    # Canonical is mcp__<server>__<action>; the action is the last segment
    # regardless of how many segments precede it.
    action = (parts[-1] if len(parts) >= 2 else "").lower()
    norm = action.replace("_", "").replace("-", "")
    if "hardlink" in norm or "unlink" in norm:
        return False
    # The real symlink-ish terms: symbolic links, soft links, Windows mklink,
    # NTFS junctions / reparse points. Verb-name classification is inherently a
    # heuristic enumeration (you cannot allowlist-blind ALL MCP writes -- that
    # breaks legitimate allowlisted-zone writes -- so the symlink question must
    # key on the verb); an exotic unknown symlink verb landing a FILE-symlink at
    # an ALLOWLISTED path is a documented reader-mitigated residual. See
    # docs/sharp-edges/protected-zone-symlink-backstop.md.
    return (
        any(v in norm for v in ("symlink", "symbolic", "softlink", "junction", "reparse", "mklink"))
        or norm in ("link", "ln", "createlink", "makelink")
    )


def _is_mcp_remove_or_relocate_verb(tool_name: str) -> bool:
    """A tool whose action segment removes or relocates its path operand
    (§C52): a delete or a move of a directory takes what it encloses."""
    parts = tool_name.split("__")
    action = (parts[-1] if len(parts) >= 2 else "").lower()
    norm = action.replace("_", "").replace("-", "")
    return any(v in norm for v in ("delete", "remove", "unlink", "move", "rename", "trash"))


def _mcp_leaf_denied(
    rel_path: str, root: Path, *, symlink_verb: bool, removes: bool = False,
) -> bool:
    """Protected-zone verdict for one MCP leaf. For a symlink-creation verb the
    allowlist is IGNORED (a symlink may never land in/point at a governed zone);
    for a normal write the allowlist applies; for a remove/relocate verb a
    directory that ENCLOSES a protected path is refused as the shells refuse
    it (§C52; the failure-mode review drove `{"path": "tools"}` allowed)."""
    if symlink_verb and _is_protected(rel_path, root):
        return True
    if _is_allowed(rel_path):
        return False
    if _is_protected(rel_path, root):
        return True
    return removes and _encloses_protected(rel_path, root)


def check_mcp(tool_input: dict, tool_name: str, root: Path) -> int:
    """Deny an MCP tool call that writes to a protected harness zone.

    Two layers:

    1. **Canonical top-level fields** (``_hook_utils.MCP_PATH_FIELDS``) — the
       BC-023 malformed-payload fail-closed (a truthy non-str where a path is
       expected) + the protected-zone check, resolve()-normalised and
       attributed to the precise field name.

    2. **Class-A2 leaf-walk** — the protected-zone MCP check cannot be
       closed by enumerating a finite key set (a write keyed
       ``output_path`` slips past the field set) OR a finite nesting depth
       (``{files:[{path}]}`` / ``{batch:{files:[{path}]}}`` nest
       arbitrarily). So walk EVERY
       string leaf, key-agnostic, depth/node-bounded, deny the first
       protected-not-allowed leaf, fail CLOSED if the payload exceeds the walk
       bounds. ``MCP_CONTENT_KEYS`` direct string leaves are skipped (a data
       blob is not a write target) — a nested ``path`` UNDER a content key
       still resolves to its own governing key and is checked.

    The leaf-walk uses the FS-free ``normalize_path_str`` (normpath, not
    resolve) — a many/long-leaf payload through resolve() would be a slow-hook
    fail-open (cf. the _PERL_OPEN_RE ReDoS critical).
    """
    if not isinstance(tool_input, dict):
        return 0
    # A symlink-creation verb is allowlist-BLIND (a symlink may never land
    # in/point at a governed zone) -- mirrors the Bash/PS ln twins.
    symlink_verb = _is_mcp_symlink_verb(tool_name)
    removes = _is_mcp_remove_or_relocate_verb(tool_name)
    # Layer 1 — canonical fields (malformed + protected, resolve-normalised).
    for field_name in _hook_utils.MCP_PATH_FIELDS:
        field_value = tool_input.get(field_name, "")
        if not field_value:
            continue
        if not isinstance(field_value, str):
            return deny(_denial_reasons.MALFORMED_MCP_PAYLOAD.format(
                field_name=field_name,
                tool_name=tool_name,
                type_name=type(field_value).__name__,
            ))
        base, rel_path = _resolve_in_checkout(field_value, root)
        if _mcp_leaf_denied(rel_path, root, symlink_verb=symlink_verb, removes=removes):
            return _deny_mcp(rel_path, tool_name, field_name, symlink_verb, root, base=base)
        # An MCP write whose canonical path field is a hardlink alias of a
        # protected file. Scoped to the bounded canonical fields, NOT the
        # unbounded leaf-walk, to preserve the Class-A2 FS-syscall-free guarantee
        # (a per-leaf stat would re-introduce the slow-hook vector). Residual
        # (alias buried in a nested non-canonical key) is CI-backstopped --
        # enumerated in docs/sharp-edges/protected-zone-hardlink-backstop.md.
        # Run UNCONDITIONALLY (not gated on `not symlink_verb`): gating it would
        # let a WRITE-semantics tool whose name merely CONTAINS a symlink
        # substring (write_symlink_data / update_symlink_target ->
        # _is_mcp_symlink_verb True) skip the backstop and rewrite protected
        # bytes via its `path`. A true symlink-CREATE at an existing nlink>=2 file
        # would EEXIST anyway, so the check is harmless there; suppressing it on a
        # misclassified writer is the live gap. The inode check fires only on
        # nlink>=2 (fast-path else).
        if _aliases_protected_inode(rel_path, root, base=base):
            where, note = _checkout_note(base, root)
            return _audit_deny(
                root, "pretooluse_blocked_protected_zone",
                _denial_reasons.PROTECTED_ZONE_HARDLINK_INODE.format(path=rel_path + where),
                tool=tool_name, path=rel_path, rule="hardlink_inode", **note,
            )
    # Layer 2 — Class-A2 key-agnostic, bounded leaf-walk.
    try:
        for key, location, leaf in _hook_utils.iter_mcp_path_leaves(tool_input):
            # casefold the membership test: the protected check (_fs_equiv) is
            # case-insensitive, so the content-skip must be too, else a
            # capitalized content key ("Content"/"TEXT") is not skipped and a
            # path-shaped DATA value under it spuriously denies (a fail-closed
            # over-block).
            # Do NOT skip content keys for a SYMLINK verb -- a symlink tool's
            # args are all path-shaped, so a content-keyed linkname must still be
            # checked (no data-blob exemption applies).
            if not symlink_verb and key.casefold() in _hook_utils.MCP_CONTENT_KEYS:
                continue  # data payload, not a write target
            rel_path = _normalize_path_str(leaf, root)
            if _mcp_leaf_denied(rel_path, root, symlink_verb=symlink_verb, removes=removes):
                return _deny_mcp(rel_path, tool_name, location, symlink_verb, root)
    except _hook_utils.MCPPayloadUnverifiable:
        return deny(_denial_reasons.MCP_PAYLOAD_UNVERIFIABLE.format(
            tool_name=tool_name, hint=_PROTECTED_ZONE_HINT,
        ))
    return 0


def _deny_mcp(
    rel_path: str, tool_name: str, field_name: str, symlink_verb: bool, root: Path,
    *, base: Path | None = None,
) -> int:
    """Emit the protected-zone MCP deny (symlink vs ordinary write reason).
    ``base`` is the checkout a canonical-field path resolved in (Layer 1); the
    FS-free leaf-walk (Layer 2) has none and names the path alone."""
    where, note = _checkout_note(base, root) if base is not None else ("", {})
    if symlink_verb:
        return _audit_deny(
            root, "pretooluse_blocked_protected_zone",
            _denial_reasons.PROTECTED_ZONE_SYMLINK_MCP.format(
                path=rel_path + where, tool_name=tool_name,
            ),
            tool=tool_name, path=rel_path, rule="symlink", **note,
        )
    return _audit_deny(
        root, "pretooluse_blocked_protected_zone",
        _denial_reasons.PROTECTED_ZONE_WRITE_MCP.format(
            path=rel_path + where, tool_name=tool_name,
            field_name=field_name, hint=_PROTECTED_ZONE_HINT,
        ),
        tool=tool_name, path=rel_path, rule="protected_write", **note,
    )


def main() -> int:
    """Public entry-point. Umbrella try/except catches any uncaught
    exception in _run_main and converts it to a deny() -- the Claude
    Code hook protocol treats exit 1 as a non-blocking script error,
    so we MUST fail-closed inside the hook process itself.
    """
    try:
        return _run_main()
    except BaseException as exc:  # noqa: BLE001 -- fail-closed crash guard
        # [broad-except] fail-closed: any unhandled error here would
        # otherwise raise to sys.exit(1) per the protocol, which Claude
        # Code treats as non-blocking. We must deny on internal error.
        # check_exception_policy.py exempts BaseException at hook
        # entrypoints; this noqa is documentary.
        error_type = type(exc).__name__
        print(
            f"[ERROR] write_guard crashed: {error_type}: {os_error_text(exc)}",
            file=sys.stderr,
        )
        # Through the audited funnel (DEF-803, the class): a wedged guard
        # denies every tool call, including the one that could repair it
        # (observed 2026-09-08), and that day was invisible in
        # ``/status --log``. The root is resolved best-effort here -- the
        # crash may have been in resolving it -- and the record carries the
        # exception's class, never its message (a message can quote a path
        # or a file's contents). One refusal per denied call while wedged;
        # the reader's day-wide by-type line is the count.
        #
        # INVARIANT: nothing between this ``except`` and the emit may prevent
        # the emit. The root fallback and the record write both swallow what
        # they can; a KeyboardInterrupt inside them is the one thing that
        # escapes, and the hook then exits non-zero, which the protocol reads
        # as allow. That is also why an interrupt inside ``_run_main`` is
        # denied here rather than re-raised the way stop_gate re-raises it:
        # for a PreToolUse guard a propagated interrupt is an allow, and for
        # the Stop hook a re-block of the Stop the operator is interrupting
        # is hostile. Add nothing here that can raise past those handlers.
        try:
            root = _resolve_project_root()
        except BaseException:  # noqa: BLE001 -- best-effort; never mask the deny
            root = Path(".")
        return _audit_deny(
            root, "pretooluse_blocked_internal_error",
            _denial_reasons.WRITE_GUARD_INTERNAL_ERROR,
            hook="write_guard", error=error_type,
        )


def _run_main() -> int:
    data = _hook_utils.read_stdin_safely()

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}
    root = _resolve_project_root()
    # The directory Claude is in (DEF-509). Claude Code's payload `cwd` follows
    # a `cd` from an EARLIER Bash call (the Bash tool's directory persists
    # across calls), so a relative spelling in THIS call resolves against it,
    # not the checkout root; absent or unreadable, the root as before.
    cwd = _payload_cwd(data, root)

    # Kill-switch gate -- runs ALWAYS, including under MAINTENANCE_MODE. The
    # maintenance bypass exists to reduce friction during harness self-edits,
    # NOT to defeat the integrity check that flags a tampered settings file.
    # Per Claude Code hook protocol, SessionStart cannot block; this is the
    # first surface that can.
    try:
        kill_switch_findings = _integrity.scan_for_kill_switches(root)
    except Exception:  # noqa: BLE001 -- never crash on integrity scan
        kill_switch_findings = []
    if kill_switch_findings:
        _audit(root, "pretooluse_blocked_kill_switch",
               findings=kill_switch_findings, tool_name=tool_name)
        return deny(_denial_reasons.KILL_SWITCH_DETECTED.format(
            context="", findings=kill_switch_findings,
        ))

    # Secret-bearing paths -- fires ALWAYS, including under MAINTENANCE_MODE and
    # including for READ-ONLY tools, so it must precede the early return below.
    # Maintenance mode reduces friction for harness self-edits; reading an
    # adopter's `.env` into the transcript is not that friction, and this is the
    # hook-layer replacement for the `Read()` deny rules espalier no longer
    # emits (see `check_secret_path_access` for why they had to go).
    rc = check_secret_path_access(tool_name, tool_input, root)
    if rc:
        return rc

    # Pass read-only tools immediately
    if tool_name not in MUTATION_TOOLS and not tool_name.startswith("mcp__"):
        return 0

    # Dangerous-command patterns -- fire ALWAYS, even under MAINTENANCE_MODE.
    # These guard against operations that are dangerous regardless of whether
    # the harness is in maintenance: rm -rf /, fork bombs, hostile PowerShell.
    if tool_name == "Bash":
        rc = check_bash_dangerous_patterns(tool_input, root, cwd=cwd)
        if rc:
            _audit(root, "pretooluse_blocked_dangerous_command", tool="Bash")
            return rc
    elif tool_name == "PowerShell":
        rc = check_powershell(tool_input, root, cwd=cwd)
        if rc:
            _audit(root, "pretooluse_blocked_dangerous_command", tool="PowerShell")
            return rc

    # Speed-bump -- before-effect meta-cognitive checkpoints. Placed AFTER the
    # dangerous-pattern hard-denies (so write_guard still owns rm -rf / etc.) and
    # BEFORE the maintenance gate (so CP-GATEWEAKEN fires during harness
    # self-edit sessions -- the exact session class where gates get weakened).
    # deny-once-then-allow: the flag set inside check_fired() means the immediate
    # retry falls through to proceed. The registry holds 9 live checkpoints (six
    # irreversible + two meta-cognitive + the MCP tier).
    # Snapshot BEFORE the speed-bump, and independently of it. The bump is
    # deny-once-then-allow, so the run that actually discards is the RE-ISSUE --
    # the one where check_fired() returns None. Snapshotting here catches both
    # passes, and also covers any discard form the reminder has not learned.
    # The removal arm (DEF-802) snapshots a delete whose target holds dirty
    # tracked content inside this checkout -- placed from `cwd`, the way the
    # hard tier places a delete -- and records what it took, so CP-RMRF's
    # text names a snapshot only when one exists: that record is why this
    # call runs BEFORE check_fired and takes the payload cwd.
    # Never raises, never denies; a failed snapshot must not block the tool.
    # Guarded at THIS boundary too, the same way as check_fired below: the
    # snapshot's own try covers git, not a name the module no longer has, and
    # on 2026-09-13 a half-landed rename inside it raised before that try and
    # wedged every mutating tool call behind WRITE_GUARD_INTERNAL_ERROR -- the
    # 2026-09-08 fix's missed sibling, one call above it. The three calls
    # ABOVE the maintenance gate that stay unwrapped -- the secret-path read
    # check, the Bash dangerous patterns, the PowerShell hard tier -- own
    # denies and fail CLOSED on purpose: a fault there must not become an
    # allow. Only the two friction helpers fail toward allow.
    try:
        _speedbump.snapshot_discard(tool_name, tool_input, root, cwd=cwd)
    except Exception as exc:  # noqa: BLE001 -- recovery aid only; a snapshot fault must not wedge the session
        # Named on stderr like the maintenance bypass, so a wedge turned allow
        # is observable in the transcript rather than silent.
        print(f"[write_guard] discard snapshot skipped: {type(exc).__name__}", file=sys.stderr)

    # Same posture at this boundary: _speedbump fails toward allow on every
    # internal path (predicate error, unwritable state, a one-shot it cannot
    # persist), and the hard denies above already ran, so a fault HERE -- a
    # sibling a version behind after a partial upgrade, a name the module no
    # longer has -- must not reach main()'s crash guard and wedge every tool
    # call behind WRITE_GUARD_INTERNAL_ERROR (observed 2026-09-08).
    try:
        _sb_fire = _speedbump.check_fired(tool_name, tool_input, root, cwd=cwd)
    except Exception:  # noqa: BLE001 -- friction only; a speed-bump fault must not wedge the session
        _sb_fire = None
    if _sb_fire is not None:
        _sb_id, _sb_reason = _sb_fire
        # Audited like every other deny this hook makes: ``/status --log``
        # answers "what did the harness just block", and a speed-bump blocked
        # this call once. Metadata only -- the tool and the checkpoint that
        # matched -- never the reminder text, never the command.
        return _audit_deny(
            root, "pretooluse_blocked_speed_bump", _sb_reason,
            tool=tool_name, checkpoint=_sb_id,
        )

    # Protected-zone path checks -- BYPASSED under MAINTENANCE_MODE so harness
    # self-edits work without ceremony. Kill-switch + dangerous patterns above
    # ran regardless. See _maintenance_mode.py for env-var contract and
    # tests/test_maintenance_mode.py for the coherence contract.
    if _maintenance_mode.is_active("write_guard", action="protected-zone check bypassed"):
        _record_maintenance_bypass(root)
        return 0

    if tool_name in ("Write", "Edit", "NotebookEdit"):
        return check_write_edit(tool_input, root)

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        # Symlink-creation check FIRST so it isn't masked by the
        # allowlist-aware general write check (legitimate JSON writes to
        # ``cc/blueprints/`` are allowed; symlinks to that prefix are not).
        rc = check_bash_for_protected_symlinks(command, root, cwd=cwd)
        if rc:
            return rc
        # Hardlink-creation check (allowlist-aware, source-keyed) before the
        # general write check, mirroring the symlink ordering.
        rc = check_bash_for_protected_hardlinks(command, root, cwd=cwd)
        if rc:
            return rc
        return check_bash_for_protected_mutations(command, root, cwd=cwd)

    if tool_name == "PowerShell":
        command = tool_input.get("command", "")
        # Symlink-creation check FIRST (allowlist-blind), like the Bash branch,
        # so a New-Item SymbolicLink into an allowlisted-in-protected path isn't
        # masked by the allowlist-aware write check.
        rc = check_powershell_for_protected_symlinks(command, root, cwd=cwd)
        if rc:
            return rc
        return check_powershell_for_protected_mutations(command, root, cwd=cwd)

    # MCP tools -- protected-zone check across canonical fields AND the
    # Class-A2 key-agnostic, depth-bounded leaf-walk (move/rename via
    # destination; non-canonical key; arbitrary nesting). See check_mcp.
    # Returns non-zero (deny) on a hit; 0 falls through to reinject.
    if tool_name.startswith("mcp__"):
        rc = check_mcp(tool_input, tool_name, root)
        if rc:
            return rc

    # Advisory PreToolUse reinject on the fall-through ALLOW path. Emitted ONLY
    # here (a clean allow, no deny printed) -- NEVER beside a deny() above
    # (channel-XOR: two stdout JSONs would corrupt the decision). BEST-EFFORT: the
    # earlier allow returns (the read-only-tool early-return, the maintenance-mode
    # bypass, the mutation-tool branches) bypass this, so a rule keyed on those
    # tools re-fires next turn.
    # additionalContext-ONLY (no permissionDecision) so it injects context without
    # auto-approving a tool that should prompt (cc-hook-protocol.md: additionalContext
    # reaches the model on PreToolUse next to the tool result). An empty PreToolUse
    # registry => [] => no print; rules extend the registry per-rule (see SHARP_EDGES).
    _reinject_payloads = _reinject.check("PreToolUse", tool_name, tool_input, root)
    if _reinject_payloads:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": "\n".join(_reinject_payloads),
            }
        }))
    return 0


if __name__ == "__main__":
    raise SystemExit(int(main()))  # coerce the truthy-zero sentinel to a plain 0
