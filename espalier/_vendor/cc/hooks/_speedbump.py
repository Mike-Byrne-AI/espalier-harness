"""Speed-bump: a before-effect, deny-once-then-allow meta-cognitive checkpoint.

A speed-bump fires `deny` ONCE per (checkpoint[, flag-key], session) with a reminder
as the PreToolUse permissionDecisionReason, sets a flag, and allows the immediate
retry. The flag set IS the retry-allow (the proven reflect_trigger one-shot idiom).

Friction is the scarce budget: a global session cap bounds the
total fires, EXCEPT for `cap_exempt` checkpoints — the safety-critical keystone fires
are NEVER budget-suppressed. Stdlib, zero espalier imports.

The predicates are keyed on the TOOL, on purpose, where the hard tiers are not:
since DEF-637 a program handed to the other shell (`bash -c` on the PowerShell
tool, `powershell -Command` on Bash) meets the other shell's extractor, read
roster and dangerous records, but not these checkpoints -- a bump is friction
that clears on re-issue, and a bump that fires on a nested program would spend
the session's budget on the rarer spelling. The one half that is recovery
rather than ceremony, `snapshot_discard` + CP-DISCARD, is the exception
(DEF-747, 2026-09-13): on the PowerShell tool the discard arms read the
command's own scan text and every bash program it hands to `bash -c` / `sh -c`
(`_ps_discard_readings`, over the C49 routing helper): the own text behind
the PowerShell command position, each program masked as the Bash side masks
a nested program, so a `git reset --hard` typed on that tool or
spelled behind `bash -c` is snapshotted and bumped as the Bash tool would.
Until then both discarded without the stash. Every other checkpoint stays
tool-keyed.

On the Bash tool the carve-out was narrowed by the operator on 2026-09-11 (the
Bash trio's third step, §C5): a program a READER head hands to a shell --
python's `os.system`, a perl or awk `system`, a git alias, a literal piped into
`sh` (`_bash_patterns.nested_shell_programs`) -- is read beside the command by
every Bash predicate that searches the masked command, and by the snapshot
(`_scan_texts`; CP-COMPACT's advisory arm reads the raw text as it always
did), so a delete or a force-push spelled inside such a program bumps exactly
as the bare spelling does, and a mention inside the program is data. The list
is computed once per command and remembered on the reader's side. The
PowerShell-tool half of the carve-out stands as written above for every
checkpoint but CP-DISCARD and its snapshot.

This is a SEPARATE mechanism from the recall engine (`_reinject.py`): it does not
recall from the corpus, it gates an action with a fixed reminder. It rides the
already-wired PreToolUse `*` matcher via one call site in `write_guard` — no new hook,
no hook-count delta.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import time
from pathlib import Path
from typing import Callable, Iterator, NamedTuple
# NamedTuple (not @dataclass) for the value types below: `dataclasses` eagerly
# imports `inspect` (~4 ms), and this module is on the PreToolUse('*') hot path,
# so it would re-pay that on every tool call. typing is already loaded; NamedTuple
# gives the same frozen-by-construction value type without the inspect import.

from _hook_utils import (
    STATE_DIR, _read_counter, _write_counter, directory_exists, join_directory,
    resolve_in_checkout,
)
import _bash_patterns
# The CP-GATEWEAKEN body names the maintenance-mode relaunch; pin the env-var to
# the SoT (_maintenance_mode.ENV_VAR) via an f-string rather than a literal, per
# the no-literal contract. Sibling import — the importing hook (write_guard) has
# already inserted hooks_dir on sys.path.
import _maintenance_mode  # type: ignore[import-not-found]

SPEEDBUMP_SESSION_CAP = 4
SPEEDBUMP_COUNTER = "speedbump_count"
_FLAG_PREFIX = "speedbump_"
# Fixed, contract-tested reason template. The "re-issue ... to proceed" clause is
# load-bearing — it makes the deny SOFT (a lever, never a wall). <= 512 bytes.
_REASON_TEMPLATE = (
    "Speed-bump [{id}]: {body}. If this is still correct, re-issue the same "
    "command to proceed."
)


class SpeedBump(NamedTuple):
    id: str
    # (tool_name, tool_input, root, cwd) -> fire? `cwd` is the directory the
    # command runs in (the payload's, DEF-790); a predicate that does not read
    # it takes it with a default, so a direct call may still pass three.
    predicate: Callable[[str, dict, Path, "Path | None"], bool]
    body: str                               # reminder body; the COMPOSED reason is held to <= 512 B by tests, nothing truncates
    cap_exempt: bool = False                # keystone/irreversible -> never suppressed
    fires_in_maintenance: bool = True       # all current bumps fire under MAINTENANCE
    # custom flag suffix: (tool_name, tool_input) -> per file, per invocation
    # or per tool. The tool name joined the signature on 2026-09-13 (DEF-8):
    # tool_input carries no reliable per-tool discriminator for an MCP tool.
    flag_key: Callable[[str, dict], str] | None = None
    # The reminder body for THIS fire, when it depends on what the hook did a
    # moment earlier (DEF-802: CP-RMRF and CP-DISCARD say a snapshot was taken
    # only when `snapshot_discard` recorded one for this command). `body` stays
    # the static text every reader and pin sees. Trailing and defaulted, so a
    # positional construction keeps working.
    body_for: Callable[[str, dict, Path, "Path | None"], str] | None = None

# NOTE: predicates take `root` (not just tool_name+tool_input) so a flag-dependent
# checkpoint like CP-COMPACT can read .espalier-state/post_compact_pending. Keep
# predicates O(cheap) — a string/regex match + at most one flag `exists()` check.


# ── The irreversible-external tier (six cap_exempt checkpoints) ──
# Actions whose harm is sealed the instant they run, with no recovery path.
# All six are cap_exempt: one-shot per (checkpoint, invocation, session) via
# their own keyed flag, so exempting them cannot storm.

# git global options that may sit BETWEEN `git` and the `push` subcommand
# (`git -C <dir> push`, `git -c k=v push`, `git --git-dir=<d> push`). A bare
# `\bgit\s+push\b` anchor misses all of them, so the keystone force-push / tag-
# push gate would be bypassable. Arg-taking opts consume the
# following token; bare flags do not. Prefix-disjoint alternation (every arm
# starts with `-`, ends on a greedy `\S+`/`\s+` over disjoint char classes) means
# no nested ambiguous quantifier -> ReDoS-safe (earned by the <50ms timing test).
#: ONE home since DEF-814's review: `_bash_patterns._GIT_PREOPT`, which every
#: git arm in that module composes too (the write arms and the zone arms
#: missed `git -C . checkout -- <hook>` while this run served push and clean
#: alone). Same name kept for the two consumers below.
_GIT_PREOPT = _bash_patterns._GIT_PREOPT
# A `git` token is only a COMMAND when it begins a command segment. A bare
# `\bgit\b` matches the token WHEREVER it appears -- inside a quoted grep
# pattern, an echo argument, a `#` comment -- so a read-only command that merely
# MENTIONS a destructive form earns a deny-once. All four git checkpoints are
# cap_exempt and two are keyed by a per-command sha256, so every distinct
# mentioning command re-fires forever; the ceiling is one retry each, but the
# recurrence is unbounded.
#
# Reuses write_guard's shared command-position fragment rather than a rival copy
# -- same class, same fix, sibling module (STANDING_PRINCIPLES §8). Composed
# VERBATIM: operator decision D-3 asked whether to widen the separator class to
# recover `$(...)`/backtick substitution, and that fork is MOOT -- the landed
# _CMD_POS_SEP already contains `(`, `)`, `{`, `}` and a backtick, so all three
# substitution shapes still fire under the plain fragment. A divergent copy of a
# security-adjacent regex is worse than anything it would buy.
_GIT_CMD = (
    _bash_patterns._CMD_POS + _bash_patterns._GIT_VERB + r"\b" + _bash_patterns._QUOTED_VERB_TAIL
)
#: The PowerShell tool's twin of the head (DEF-747): the same verb tails behind
#: the PowerShell command position, for CP-DISCARD and its snapshot alone. A
#: Bash-anchored regex over PowerShell text would open a command position at
#: the Bash exec-quote arm (`bash -c "`) inside a PowerShell LITERAL, so
#: `Write-Output 'bash -c "git reset --hard"'` bumped as a discard; behind the
#: PowerShell anchor a literal is data, and the bash PROGRAM a real `bash -c`
#: hands over is read separately, as bash receives it, by the Bash regexes.
#: `_GIT_VERB` admits `git.exe`: behind the call operator the command is often
#: the full path to the executable, extension and all (DEF-791).
_PS_GIT_CMD = (
    _bash_patterns._PS_CMD_POS + _bash_patterns._GIT_VERB + r"\b" + _bash_patterns._QUOTED_VERB_TAIL
)

_GIT_PUSH = _GIT_CMD + r"[ \t]+(?:" + _GIT_PREOPT + r")*push\b[^\n;|&]*?"

# CP-FORCEPUSH -- `git push --force` / glued `-f` cluster destroys remote commits;
# silent on `--force-with-lease` (the safe form). The `-[a-eg-z]*f[a-z]*` arm fires
# `-f`/`-fv`/`-vf` (glued short flags) but NOT `-v` (the `f` class excludes `f`
# from the prefix run, forcing a literal `f`).
_FORCE_PUSH_RE = re.compile(
    _GIT_PUSH + r"(?:--force(?!-with-lease)|(?<![\w-])-[a-eg-z]*f[a-z]*\b)"
)


def _masked_command(tool_input: dict) -> str:
    """The command with inert shell syntax spaced out -- see
    `_bash_patterns.mask_inert_syntax`.

    Every git checkpoint below is command-position anchored, and the anchor treats
    ``` ` ( ) { } ; | & ``` and newline as command-position characters. Those are
    also the characters prose ABOUT a command is made of, so a markdown code span,
    a `#` comment or a heredoc body synthesised a command position out of text that
    never executes: ``echo "call run(git push --force) here"`` fired CP-FORCEPUSH,
    ``# doc: `git stash drop` is destructive`` fired CP-DISCARD. Measured 2026-08-24
    against the live predicates.

    A checkpoint costs one re-issue, and a false one SPENDS the protection: the
    flag is per-invocation but a benign fire still burns that invocation's nudge.
    """
    # Mask, THEN splice continuations (the rm segmenter's order): the detectors
    # only search this text, so offsets need not survive, and a `git push \`
    # + newline + `--force` is one statement to them (DEF-701 sibling sweep).
    # `_bash_patterns._candidate_paths_from_bash` splices FIRST for its own
    # reason (two strings read by offset); the two orders are both deliberate.
    return _bash_patterns.splice_line_continuations(
        _bash_patterns.mask_inert_syntax(tool_input.get("command", ""))
    )


def _scan_texts(tool_input: dict) -> list[str]:
    """The masked command and, beside it, every program it hands to a shell
    through a reader head (`_bash_patterns.nested_shell_programs`), each
    masked the same way -- the operator's widening of the §C49 carve-out
    (2026-09-11, the Bash trio's third step): a delete or a force-push a
    PROGRAM hands to a shell bumps as the bare spelling does, and a mention
    inside the program is data."""
    texts = [_masked_command(tool_input)]
    for program in _bash_patterns.nested_shell_programs(tool_input.get("command", "")):
        texts.append(_bash_patterns.splice_line_continuations(
            _bash_patterns.mask_inert_syntax(program)))
    return texts


def _bash_reading(text: str) -> tuple[str, str]:
    """``(scan, raw)`` for a Bash text the discard arms read: spliced FIRST,
    then masked -- the extractor's order, not `_masked_command`'s -- so the
    two are the same length and the bare-checkout arm can read its operand
    from the raw twin at the scan match's offsets (DEF-794's sister site).
    The other checkpoints only SEARCH their text and keep `_scan_texts`."""
    raw = _bash_patterns.splice_line_continuations(text)
    return _bash_patterns.mask_inert_syntax(raw), raw


def _ps_discard_readings(tool_input: dict) -> list[tuple[str, str | None, bool]]:
    """What the discard arms read on the PowerShell tool (DEF-747), each
    paired with the grammar that reads it: the command's own scan text
    (``False``: the PowerShell-anchored twins, so a literal stays data; no
    raw twin, the PowerShell arms read no operand), then every bash program
    the command hands to `bash -c` / `sh -c` through the C49 routing helper,
    as a `_bash_reading` pair (``True``: the Bash regexes, as bash receives
    it). The recovery half of the tool-keyed carve-out (see the module
    docstring); the other checkpoints do not read this."""
    raw = tool_input.get("command", "")
    scan = _bash_patterns.powershell_scan_text(raw)
    readings: list[tuple[str, str | None, bool]] = [(scan, None, False)]
    for body in _bash_patterns._ps_shell_program_bodies(raw, scan):
        readings.append((*_bash_reading(body), True))
    return readings


def _discard_readings(tool_name: str, tool_input: dict) -> list[tuple[str, str | None, bool]]:
    """``(scan, raw twin or None, is_bash_text)`` for everything CP-DISCARD
    and its snapshot search, by tool; empty for a tool neither reads (Write,
    Edit, an MCP tool). Every Bash reading -- the command and each program it
    hands to a shell -- carries its raw twin, so a quoted pathspec inside a
    nested program is read whole too (review: `echo 'git checkout "hooks/my
    file.py"' | bash` kept the truncated capture while the bare spelling
    was fixed)."""
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        readings: list[tuple[str, str | None, bool]] = [(*_bash_reading(command), True)]
        for program in _bash_patterns.nested_shell_programs(command):
            readings.append((*_bash_reading(program), True))
        return readings
    if tool_name == "PowerShell":
        return _ps_discard_readings(tool_input)
    return []


def _pred_forcepush(tool_name: str, tool_input: dict, root: Path, cwd: Path | None = None) -> bool:
    if tool_name != "Bash":
        return False
    return any(_FORCE_PUSH_RE.search(cmd) for cmd in _scan_texts(tool_input))


# CP-RELEASE -- a v<digit> tag reaching the remote burns a PyPI version
# (.github/workflows/publish.yml: `on: push: tags: ['v*']`). Catch the tag-push
# paths AND `gh release create` (which creates+pushes the tag); skip `--draft`.
# FAIL TOWARD FRICTION: a branch named `v2-foo` over-fires (one retry) but a real
# tag push is never missed (an unrecoverable burn is the strictly worse error) --
# true through git global options too (`git -C <d> push origin v1.2.3`).
_RELEASE_TAGPUSH_RE = re.compile(
    _GIT_PUSH + r"(?:--tags\b|--follow-tags\b|\bv\d[\w.\-]*)"
)


# ⚠ ANCHORED, unlike the bare `"gh release create" in cmd` substring test this
# replaces. That test read the phrase ANYWHERE, so a read-only
# `command grep -rn 'gh release create' docs/RELEASE_CHECKLIST.md` -- or a commit
# message naming the command -- fired the checkpoint. The cost was not the one
# retry: CP-RELEASE is `cap_exempt` with an id-only flag, so the first fire
# retires it for the whole session, and the properly-anchored TAG-PUSH arm rides
# the SAME flag. Grepping the release checklist therefore disarmed the PyPI-burn
# keystone in both directions, and the next real `git push origin v1.2.3` passed
# silently.
#
# The global-option run allows a flag AND its argument, mirroring
# `_CMD_POS_WRAP_RUN`'s shape rather than inventing a third. A flag-ONLY run
# silently missed `gh -R owner/repo release create` — the spelling a release
# actually gets driven with from a non-default checkout. Every iteration begins
# with `-` and the optional argument begins with a NON-`-` class, so the run
# stays prefix-disjoint and linear (no nested ambiguous quantifier).
_GH_RELEASE_CREATE_RE = re.compile(
    _bash_patterns._CMD_POS
    + r"gh[ \t]+(?:-[^\s;|&]+[ \t]+(?:[^-\s;|&][^\s;|&]*[ \t]+)?)*release[ \t]+create\b"
)


def _pred_release(tool_name: str, tool_input: dict, root: Path, cwd: Path | None = None) -> bool:
    if tool_name != "Bash":
        return False
    for cmd in _scan_texts(tool_input):
        if _GH_RELEASE_CREATE_RE.search(cmd) and "--draft" not in cmd:
            return True
        if _RELEASE_TAGPUSH_RE.search(cmd):
            return True
    return False


# CP-DISCARD -- explicit working-tree / stash discard forms ONLY (no bare-`checkout
# <tok>` arm: it false-fires on a safe branch switch when a branch name matches a
# dir). `git reset --hard` fires HERE (soft, deny-once-then-allow) instead of
# write_guard's hard-deny wall -- it discards uncommitted work (no reflog) but is
# routine; a reminder beats a wall.
#: The discarding verbs, spelled ONCE for the Bash head and the PowerShell head.
#: `checkout --` admits the quoted separator (DEF-814): `_GIT_DASHDASH_SEP`
#: is the one spelling the write arms and this tail share; the global-option
#: run before the subcommand is the write arms' too (`git -C . reset --hard`
#: drew no nudge, review).
_DISCARD_TAIL = (
    r"[ \t]+" + _bash_patterns._GIT_PREOPT_RUN
    + r"(?:checkout[ \t]+(?:" + _bash_patterns._GIT_DASHDASH_SEP + r"|\.)"
    r"|reset[ \t]+--hard"                          # discards uncommitted changes
    r"|restore\b[^\n;|&]*--worktree"            # worktree discard fires EVEN w/ --staged
    r"|restore\b(?![^\n;|&]*--staged)"          # bare restore (worktree is the default target)
    r"|stash[ \t]+(?:drop|clear))"
)
_DISCARD_RE = re.compile(_GIT_CMD + _DISCARD_TAIL)
#: The PowerShell tool's own text (DEF-747; see `_PS_GIT_CMD`). IGNORECASE for
#: the opener words, as the module's other PowerShell twins.
_PS_DISCARD_RE = re.compile(_PS_GIT_CMD + _DISCARD_TAIL, re.IGNORECASE)


# The BARE `checkout <tok>` form -- `git checkout path/to/file.py`, no `--`. It
# was deliberately left out of _DISCARD_RE above because a blind arm false-fires
# on a safe branch switch whenever a branch name also names a directory. That
# reasoning was right about the REGEX and wrong about the CONCLUSION: the
# ambiguity git itself resolves is resolvable here too, so the form does not have
# to stay uncovered. It is also the form most likely to be typed, and it was
# measured passing silently while `git checkout -- <same file>` fired.
#
# REUSES `_bash_patterns._GIT_CHECKOUT_BARE_RE` -- the sibling that already
# extracts this exact token for write_guard's protected-zone check -- rather than
# authoring a rival. A first cut of this arm DID author one; the enumeration gate
# in tests/test_speedbump_irreversible.py surfaced it, which is the gate working.
# Same class, same fix, sibling module (STANDING_PRINCIPLES §8), and the shared
# copy already carries the command-position anchor and the ReDoS bound.
#
# It captures ONE token (the first non-flag operand), so `git checkout <tree-ish>
# <path>` is not fully discriminated. That is acceptable and deliberate: the
# PREDICATE only has to catch the common form, because `snapshot_discard` below
# is the actual protection and its trigger is deliberately wider.
#
# Referenced at the use site rather than aliased here on purpose: binding a
# module-level name would enter this pattern into `vars(_speedbump)` a SECOND
# time, inflating the git-regex census the enumeration gate pins and making one
# object look like two sites.


def _git_rc(root: Path, *args: str) -> int | None:
    """Return `git <args>`'s exit code, or None if it could not run at all.

    None is NOT an exit code: callers must distinguish "git answered no" from
    "git could not answer". Collapsing the two is what made the first cut of
    this predicate fire on `git checkout -b feature` in a plain directory —
    `git diff` exits 128 outside a repo, which a boolean read as "dirty".
    """
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, timeout=5,
        ).returncode
    except (OSError, subprocess.SubprocessError):
        return None


def _destroys_uncommitted_work(
    root: Path, arg_span: str, bases: "list[Path] | None" = None,
) -> bool:
    """True when a bare `git checkout <arg_span>` would discard real work.

    ``bases`` (DEF-790) are the directories the command runs the checkout
    from -- the payload cwd moved by its own cd chain, the statement's own --
    so the probe asks git there, as git reads a pathspec; without them, the
    root. A base OUTSIDE this checkout is skipped: the snapshot that backs
    this bump's promise (`snapshot_discard`) stashes THIS repo, so a discard
    run inside another one must not draw a nudge that names a snapshot it
    never took (failure-mode review, 2026-09-13).

    Two probes, in the order that makes each cheap:

    1. A token that resolves as a commit-ish is a REF -- a branch switch, which
       keeps working-tree changes. Silent.
    2. Otherwise it is a pathspec. `git diff --quiet -- <tok>` decides whether
       anything would actually be lost: against a CLEAN path the checkout is a
       no-op, and firing there would be noise. Only a DIRTY path destroys
       content that has no reflog.

    This is strictly more precise than the `checkout .` arm above, which fires
    even on a spotless tree.

    Fires only on POSITIVE confirmation. `git diff --quiet` exits 1 for "there
    are differences" and 128 for "I could not look" (not a repo, bad pathspec);
    only the 1 means work would be lost. Anything else -- including git being
    absent -- stays silent, because a checkpoint that fires when it cannot tell
    is noise, and noise is how a checkpoint gets ignored.
    """
    # quote-aware: a quoted pathspec with a space is ONE operand (DEF-794's
    # sister site; a whitespace split asked git about `hooks/my` and stayed
    # silent while `hooks/my file.py` was discarded)
    tokens = [t.strip('"').strip("'")
              for t in _bash_patterns._OPERAND_TOKEN_RE.findall(arg_span)]
    if "--" in tokens:
        return False          # explicit form: _DISCARD_RE already owns it
    if _git_rc(root, "rev-parse", "--git-dir") != 0:
        return False          # not a repo -- nothing here can discard anything
    for tok in (t for t in tokens if not t.startswith("-")):
        if _git_rc(root, "rev-parse", "--verify", "--quiet", f"{tok}^{{commit}}") == 0:
            continue          # a ref -- branch switch, working tree preserved
        for at in (bases if bases is not None else [root]):
            if not _inside(at, root):
                continue      # another checkout's: not this hook's promise to keep
            if _git_rc(at, "diff", "--quiet", "--", tok) == 1:
                return True   # a pathspec carrying uncommitted changes
    return False


def _inside(at: Path, root: Path) -> bool:
    """Is ``at`` the checkout root or under it (resolved, so a symlinked
    checkout still counts)? A path that cannot be resolved is not."""
    try:
        return at.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def _pred_discard(tool_name: str, tool_input: dict, root: Path, cwd: Path | None = None) -> bool:
    # Bash, and (DEF-747) the PowerShell tool's own text plus the bash programs
    # it hands to `bash -c`: the one checkpoint whose deny is a recovery
    # artifact rather than ceremony, so it is not tool-keyed like the others.
    for scan, raw, is_bash in _discard_readings(tool_name, tool_input):
        if (_DISCARD_RE if is_bash else _PS_DISCARD_RE).search(scan):
            return True
        if not is_bash:
            continue
        # NOTE (deliberate exception to the "predicates stay O(cheap)" rule
        # above): this arm shells out to git, ~19ms for the probe pair. It is
        # gated behind the regex, so only a command that already looks like
        # `git checkout <tok>` ever pays it, and the alternative -- leaving the
        # most-typed destructive form uncovered -- cost a real, unrecoverable
        # loss of uncommitted work.
        m = _bash_patterns._GIT_CHECKOUT_BARE_RE.search(scan)
        if m and _destroys_uncommitted_work(
            root, _checkout_operand(scan, raw, m),
            _statement_directories(scan, m.start(1), root, cwd),
        ):
            return True
    return False


def _checkout_operand(scan: str, raw: str | None, m: "re.Match[str]") -> str:
    """The pathspec of the bare-checkout arm, AS SPELLED, from the reading's
    raw twin at the scan match's offsets (DEF-794's sister site).

    `_GIT_CHECKOUT_BARE_RE`'s capture is a bare run over masked text, so a
    quoted pathspec came back as its prefix (`"hooks/my` of `"hooks/my
    file.py"`) or as the masker's blanks (`rep  x86 .py`), `git diff` found
    no such file, and the discard checkpoint stayed silent on every quoted
    spelling -- `git checkout "hooks/x.py"` destroyed uncommitted work with
    no re-issue prompt (failure-mode review, driven); a first fix reached
    only the command's own reading and left a nested program's checkout
    truncated (review, driven). Every Bash reading now carries its twin
    (`_bash_reading`), and the operand keeps its quotes because
    `_destroys_uncommitted_work` re-tokenises it quote-aware. A reading
    without a twin, or one whose lengths disagree, keeps the masked capture.
    """
    if raw is None or len(raw) != len(scan):
        return m.group(1)
    return _bash_patterns.raw_operand(raw, m, keep_quotes=True)


def _statement_directories(cmd: str, offset: int, root: Path, cwd: Path | None) -> list[Path]:
    """The directories the statement at ``offset`` of ``cmd`` runs in (DEF-790):
    the payload cwd (else the root) moved by the command's own cd chain, read
    by the statement's OFFSET on the chain's own text -- never by searching a
    token's spelling across statements, which placed a pathspec wherever its
    name was mentioned (failure-mode review, 2026-09-13). ``cmd`` is the
    masked, spliced text the discard arms search; the chain re-derives that
    text from it byte-for-byte below the scan cap, so the offsets agree, and
    past the cap (or on a fault) the start is the answer, as it always was."""
    start = cwd or root
    try:
        text, statements = _bash_patterns.bash_directory_chain(cmd, directory_exists(start))
    except Exception:  # noqa: BLE001 -- the walk is advisory
        return [start]
    if len(text) != len(cmd):
        return [start]
    for s, e, dirs in statements:
        if s <= offset < e:
            return [join_directory(start, d) for d in dirs]
    return [start]


def _discard_key(tool_name: str, tool_input: dict) -> str:
    # per-INVOCATION keying. Without a flag_key, CP-DISCARD fires ONCE per
    # session for its id alone -- the first `git reset --hard` (or ANY discard form)
    # then silences EVERY later discard for the rest of the session, including a
    # `git checkout -- <file>` against different, uncommitted work an agent never saw
    # the reminder for. Keying the one-shot to the normalized command makes each
    # DISTINCT destructive command earn its own reminder, while an identical re-issue
    # (the deny-once-then-allow retry) maps to the same key and still passes.
    # KNOWN LIMIT: an *identical* command repeated LATER in the session stays silent
    # -- the flag is session-scoped; re-nudging identical repeats would need a TTL the
    # mechanism deliberately omits. This closes the cross-command/cross-target gap,
    # which is the one that bites. The command carries spaces/slashes, so hash it to a
    # filesystem-safe suffix (the suffix becomes part of the flag FILE name).
    cmd = " ".join((tool_input.get("command") or "").split())
    return hashlib.sha256(cmd.encode("utf-8")).hexdigest()[:16]


# CP-GITCLEAN -- `git clean -f` PERMANENTLY deletes UNTRACKED files (with `-x`,
# ignored files too). Unlike CP-DISCARD's tracked-change discards, this destroys
# content that was NEVER in git -- no reflog AND no object to recover -- so it is
# the one irreversible working-tree gap CP-DISCARD misses (verified absent from
# _DISCARD_RE). Rides _GIT_PREOPT so `git -C <dir> clean -fd` is covered too, like
# the force-push / release gates. Fires ONLY when the command WILL delete: a force
# flag is present (git refuses to delete without one under the default
# clean.requireForce) AND no dry-run (`-n`/`--dry-run`, which only LISTS) is set.
_GITCLEAN_RE = re.compile(
    _GIT_CMD + r"[ \t]+(?:" + _GIT_PREOPT + r")*clean\b([^\n;|&]*)"
)
# Token tests over the captured arg span. Short clusters use the CP-FORCEPUSH glued
# idiom -- `(?<![\w-])-[a-zA-Z]*<flag>[a-zA-Z]*` fires on <flag> anywhere in a boolean
# short cluster (`-fd`, `-xdf`) but never across a `--long` option or inside a
# non-flag operand. The char-class MUST include uppercase: `git clean -X` (remove
# ignored files) rides in a real force cluster (`-fdX`), and an `[a-z]`-only run
# could neither span nor terminate across the `X`, silently missing the delete
# (deliberately WIDER than the CP-FORCEPUSH sibling, which has no uppercase short
# flag to glue). Linear, prefix-anchored -> ReDoS-safe.
_GITCLEAN_FORCE_RE = re.compile(r"--force\b|(?<![\w-])-[a-zA-Z]*f[a-zA-Z]*\b")
_GITCLEAN_DRYRUN_RE = re.compile(r"--dry-run\b|(?<![\w-])-[a-zA-Z]*n[a-zA-Z]*\b")


def _pred_gitclean(tool_name: str, tool_input: dict, root: Path, cwd: Path | None = None) -> bool:
    if tool_name != "Bash":
        return False
    for cmd in _scan_texts(tool_input):
        m = _GITCLEAN_RE.search(cmd)
        if m is None:
            continue
        args = m.group(1)
        # A dry run only LISTS -- never fire (`-n` wins even if `-f` is also present).
        if _GITCLEAN_DRYRUN_RE.search(args):
            continue
        # Fire only when it will actually delete (force present). A bare `git clean`
        # errors out under default clean.requireForce, so nudging it is pure friction;
        # a `clean.requireForce=false` host is an accepted under-fire (fail toward less
        # friction on the safe-by-default form).
        if _GITCLEAN_FORCE_RE.search(args):
            return True
    return False


# CP-RMRF -- the SOFT tier: recursive delete, forced or not (DEF-842), of RELATIVE / `~` / `$VAR` targets
# that are NOT recognized-safe ephemeral dirs. write_guard's hard-deny
# (`_bash_patterns.has_catastrophic_recursive_rm`) owns absolute (`/...`) and leading-
# glob (`*...`) targets in ALL flag orders/spellings -- CP-RMRF DEFERS to it (stays
# silent) so the two tiers never double-fire. The flag tokenizer + the rm-invocation
# iteration are the SHARED single source of truth in `_bash_patterns` (no duplicate
# tokenizer). Recognized-safe RELATIVE ephemeral dirs only (absolute `/tmp/...` is owned
# by write_guard, which refuses a `/tmp/` carve-out so `/tmp/../../etc` can't traverse):
#: The roster moved to `_bash_patterns.SAFE_EPHEMERAL_DIRS` when the PowerShell
#: hard-deny carve-out became a second consumer (2026-08-22). Referenced at its
#: use site rather than re-bound here: a local alias under a DIFFERENT name is
#: exactly what `sister_site_probe` flags as an alias-miss, and it re-creates
#: the two-names-one-roster drift the move exists to remove.


def _rm_invocations_across(texts: list[str]) -> Iterator[tuple[bool, bool, list[str]]]:
    """Every `rm` invocation in the command and in each nested program."""
    for text in texts:
        yield from _bash_patterns.iter_rm_invocations(text)


def _pred_rmrf(tool_name: str, tool_input: dict, root: Path, cwd: Path | None = None) -> bool:
    if tool_name == "PowerShell":
        # The middle rung write_guard.check_powershell now falls through to.
        # Same three-way shape as the Bash arm below: the hard tier keeps
        # absolute/globbed/qualified/unparseable targets, the roster-ephemeral
        # ones are allowed outright, and what is left -- a plainly relative
        # directory that is not on the roster -- is worth one question rather
        # than a wall. Before this, nine of fifteen ordinary relative cleans
        # were unrunnable on Windows with no re-issue and no maintenance bypass.
        # Masked, for the same reason `_masked_command` exists on the Bash side:
        # a checkpoint costs a re-issue and a false one SPENDS the protection.
        # This arm read the raw string until 2026-08-25, and the masked string
        # without the continuation join until 2026-09-05.
        raw = tool_input.get("command", "")
        cmd = _bash_patterns.powershell_scan_text(raw)
        # DEF-842: the wall owns a recursive remove of a catastrophic target,
        # forced or not; the hard tier asks this same predicate, so stepping
        # aside here never leaves such a remove with no tier.
        if _bash_patterns.powershell_recursive_removal_is_catastrophic(raw, str(root), cwd or root):
            return False
        # DEF-842: recursion WITHOUT the force switch takes every ordinary
        # item under its target with no prompt (driven on pwsh 7.6.5), so off
        # the roster it is one nudge for any target the wall did not take --
        # an ordinary variable included (operator, 2026-09-18) -- read by the
        # wall's own reader, only the recursive invocations, so a roster
        # clean beside a plain remove stays silent as its Bash twin does. The
        # force form keeps its wider wall for an absolute or variable target
        # (the records): a declared difference, pinned in the tier corpus.
        if _bash_patterns.powershell_unforced_removal_off_roster(cmd):
            return True
        if _bash_patterns._PS_RECURSIVE_FORCE_RE.search(cmd):
            # Defer to the hard tier on a relative target that lands on the
            # repo, its parent, home or a shallow system path once read from
            # the directory the command runs in (DEF-790) -- the Bash arm's
            # rule. A roster-ephemeral target falls through to the sweep arm
            # below (the two shapes can share a command).
            if _bash_patterns.powershell_removal_lands_catastrophic(raw, str(root), cwd or root):
                return False
            if not _bash_patterns.powershell_removal_is_recognized_safe(cmd):
                return _bash_patterns.powershell_removal_is_plainly_relative(cmd)
        # DEF-824 / DEF-822: the sweeps on this tool -- the find family (GNU
        # find runs verbatim under pwsh on a POSIX host), the enumerator
        # piped into a remove verb (`gci src -r -File | ri`, the shape the
        # recursive-force regex above never sees; and `gci src -Recurse |
        # ri -fo`, which deletes everything enumerated before the first
        # directory with children -- a tree of empty directories goes
        # whole, driven) -- take the three-way reading the Bash arm gives a
        # find: the wall for a catastrophic root (deferred, one classifier
        # with the hard tier), no friction for a roster-ephemeral root, one
        # nudge for the rest; a narrowed sweep never bumps. The recursive
        # .NET directory delete meets the wall but never the nudge: a
        # deliberate API call is not the spelling habit, and its relative
        # root is the zone check's on the first issue. The roots come from
        # the reader the hard tier uses.
        if _bash_patterns.has_catastrophic_ps_sweep(raw, str(root), cwd or root):
            return False
        for roots in _bash_patterns.iter_ps_unnarrowed_sweep_roots(raw):
            if _off_the_ephemeral_roster(roots):
                return True
        return False
    if tool_name != "Bash":
        return False
    # The command and every program it hands to a shell through a reader
    # head (the Bash trio's third step); the tokenizer masks each itself.
    # The list carries the programs of every reading the walls judge (a value
    # expanded into a program is in the inlined one: DEF-848's lane); the
    # command itself is read as spelled, as before, so a bound operand still
    # bumps as the variable it is.
    texts = [tool_input.get("command", "")]
    texts.extend(_bash_patterns.nested_shell_programs(texts[0]))
    # Defer entirely to write_guard's hard-deny on catastrophic targets -- the
    # root, home or the repo, shallow system paths, and a bare glob or `$PWD`
    # that names one of them where it runs, in any spelling
    # (`_target_is_catastrophic`); every other target is this tier's.
    # check_bash_dangerous_patterns already preempts those before the speed-bump
    # runs; this guard keeps the predicate correct under direct unit test --
    # except for a nested program, which the hard tier judges flagged
    # (`another_shells_program`, from the unknown directory as well) and this
    # defer reads unflagged: a narrower defer, so this tier may bump what the
    # hard tier walls, never the reverse (the lane's review).
    # Read from the directory the command runs in (DEF-790), as the hard tier
    # reads it: the payload cwd moved by the command's own cd chain.
    if any(_bash_patterns.has_catastrophic_recursive_rm(t, str(root), cwd=cwd or root)
           or _bash_patterns.has_catastrophic_bash_sweep(t, str(root), cwd=cwd or root)
           for t in texts):
        return False
    for rec, _force, operands in _rm_invocations_across(texts):
        # Need recursion AND at least one operand. Recursion alone, forced or
        # not (DEF-842): rm prompts only for an unwritable file and only on a
        # terminal, so the unforced spelling takes what the forced one takes.
        # An operand-less form (`rm -rf/` globs the slash onto the flag
        # cluster: a syntax error rm rejects, no target) has nothing to bump.
        if not rec or not operands:
            continue
        if _off_the_ephemeral_roster(operands):
            return True
    # DEF-815: an un-narrowed `find` with a delete action is the recursive
    # force-delete of its root by effect, and takes the same three-way
    # reading -- the wall for a catastrophic root (deferred above), no
    # friction for a roster-ephemeral root (`find build -delete`), one nudge
    # for the rest (`find src -delete`, `find ~/scratch -delete`). A NARROWED
    # find never bumps: its root is a starting point the zone check judges by
    # itself, and `find . -name '*.pyc' -delete` is an everyday command. The
    # roots come from the reader the hard tier uses, so the two tiers keep
    # one reading of what a find takes. No snapshot promise rides a find or
    # a pipeline into xargs: `_removal_snapshot_targets` places rm operands
    # and a loop's whole roots (DEF-837's lane), not a find's or a carrier's,
    # so their body is the plain one -- a stated limit, its own ledger row
    # (`DEF-845`).
    for text in texts:
        # the find family (DEF-815) and the enumerator piped through xargs
        # into a remove verb (DEF-826), one iterator: never empty, the
        # rootless form is `.`
        for roots in _bash_patterns.iter_unnarrowed_bash_sweep_roots(text):
            if _off_the_ephemeral_roster(roots):
                return True
    return False


def _off_the_ephemeral_roster(operands: list[str]) -> bool:
    """True when these delete targets are worth one nudge: any of them is
    not a recognized-safe RELATIVE ephemeral directory. The roster's own
    targets pass without friction; everything else fires (a relative source
    dir, `~`, `$VAR`, a multi-token operand). Fail toward friction: a soft
    over-fire costs one retry; an under-fire an unrecoverable tree. ONE home
    for the rm operands and the find roots (DEF-815)."""
    norm = []
    for t in operands:
        s = _bash_patterns._shell_unquote(t)
        s = s[2:] if s.startswith("./") else s   # prefix strip, NOT lstrip char-set:
        norm.append(s)                           # lstrip("./") ate `.pytest_cache`->`pytest_cache`
    # A `..` segment escapes the allowlist (tmp/../src traversal) -> never "safe".
    if any(".." in s.split("/") for s in norm):
        return True
    safe = {p.rstrip("/") for p in _bash_patterns.SAFE_EPHEMERAL_DIRS}
    # Component-boundary match: `buildsrc/` must NOT match the `build` prefix.
    # Compare the FIRST path component, not a raw startswith.
    return not all(s.split("/", 1)[0] in safe for s in norm)


# ⚠ ALL FOUR IRREVERSIBLE CHECKPOINTS ARE PER-INVOCATION KEYED. `cap_exempt`
# means "never budget-suppressed"; it says nothing about the one-shot FLAG, and
# an id-only flag retires the checkpoint on its FIRST fire for the rest of the
# session. `CP_DISCARD` and `CP_GITCLEAN` were keyed for exactly that reason and
# the other two were not, which made the irreversible tier inconsistent with
# itself. Measured live: `speedbump_CP-RMRF` was set two minutes into a session
# by a read-only grep, after which `rm -rf ~/<a real source tree>` passed with no
# nudge at all -- a false positive converting into a false negative. Keying only
# ADDS fires (an identical re-issue still maps to the same key and passes), so it
# cannot cost coverage.
#
# ⚠ ORDERING: key an UNANCHORED predicate and one nudge becomes unbounded nudges
# (a corpus finding, now on the record branch). CP-RELEASE's substring arm was anchored
# immediately above BEFORE this was applied, and CP-FORCEPUSH rides `_GIT_CMD`.
#
# ⚠ CP-RMRF IS THE HONEST EXCEPTION AND THE TRADE IS DELIBERATE. `_pred_rmrf`
# iterates the shared tokenizer, but that tokenizer segments with
# `_RM_SEGMENT_RE`, which is UNANCHORED by the DEF-414f carve-out -- so a
# read-only `grep` whose PATTERN quotes the delete spelling really does fire it.
# Keying therefore RAISES this checkpoint's false-positive friction: previously
# one bump per session, now one per DISTINCT mentioning command.
#
# Taken anyway, because the two costs are not comparable. The old behaviour was
# not "less friction" -- it was the FIRST mention silently retiring the
# checkpoint, so a later genuine `rm -rf ~/<tree>` drew nothing. A repeated nudge
# is recoverable by re-issuing; a missing nudge on an unrecoverable delete is
# not. Base rate says the added friction is small: 52 CP-RMRF denies across 166
# recorded sessions (~0.3/session), and identical re-issues share a key.
#
# The real fix is anchoring `_RM_SEGMENT_RE`, which is the ledgered operator
# decision this must not pre-empt. Until then this is a friction/coverage trade
# made with eyes open, not an oversight.
CP_FORCEPUSH = SpeedBump(
    id="CP-FORCEPUSH",
    predicate=_pred_forcepush,
    body="git push --force destroys remote commits not in your local tree; prefer "
         "--force-with-lease",
    cap_exempt=True,
    flag_key=_discard_key,      # per-invocation: a force-push to a DIFFERENT
                                # remote/branch is a different irreversible act
)

CP_RELEASE = SpeedBump(
    id="CP-RELEASE",
    predicate=_pred_release,
    body="this pushes a release tag (or runs `gh release create`) -> publish.yml burns "
         "a PyPI version that can never be replaced; verify the tag + CHANGELOG narrative "
         "first",
    cap_exempt=True,
    flag_key=_discard_key,      # per-invocation: each distinct tag burns a
                                # DIFFERENT version, so each earns its own nudge
)

# ── The snapshot record (DEF-802) ────────────────────────────────────────────
#
# A speed bump's text is a PROMISE, and two of them name a snapshot. Until
# 2026-09-15 CP-DISCARD said "a snapshot was taken first" whether or not
# `git stash create` had answered, and CP-RMRF -- the one whose target has no
# other net -- took none at all: on the Windows host (walk 3, leg 4-B) a
# recursive-force `Remove-Item` on a directory holding a dirty tracked line
# destroyed it unsnapshotted, and the later CP-DISCARD snapshot captured a
# tree that no longer had it. `snapshot_discard` runs before `check_fired`
# in write_guard and records what it took for which command; each body reads
# that record and says a snapshot exists only when one does. The static
# `body` is what every reader and pin sees; `body_for` is what the agent
# reads on the fire. (The record is per process -- a hook run is one tool
# call -- and the tests reset it.)
_last_snapshot: tuple[str, str, str, str] | None = None   # (tool, command key, root, sha)


def _record_snapshot(tool_name: str, tool_input: dict, root: Path, sha: str) -> None:
    global _last_snapshot
    _last_snapshot = (tool_name, _discard_key(tool_name, tool_input), str(root), sha)


def _snapshot_taken_for(tool_name: str, tool_input: dict, root: Path) -> str | None:
    """The sha `snapshot_discard` recorded for THIS tool call in THIS
    checkout, else None. (Under pytest the process spans the suite, so
    `tests/conftest.py` resets the record before every test.)"""
    if _last_snapshot is None:
        return None
    tool, key, at, sha = _last_snapshot
    wanted = (tool_name, _discard_key(tool_name, tool_input), str(root))
    return sha if (tool, key, at) == wanted else None


_DISCARD_BODY = (
    "discarding uncommitted working-tree changes has no reflog. A snapshot was "
    "taken first -- see the last line of cc/discard_snapshots.log and recover with "
    "`git show <sha>:<path>`"
)
_DISCARD_NO_SNAPSHOT_BODY = (
    "discarding uncommitted working-tree changes has no reflog, and NO snapshot "
    "was taken (nothing dirty to save, or git did not answer) -- check `git status` "
    "before re-issuing"
)
# The pinned phrases (`tests/test_denial_reasons.py`) name the hard tier's
# rules and this tier's; both variants carry them, and both composed reasons
# stay under the 512 bytes the irreversible tier's record-shape pin allows --
# a contract size whose rationale is not recorded; ask before raising it. The
# snapshot variant sits 2 bytes under it: its word "tracked-edit" scopes the
# promise (an untracked file is not in the snapshot) and is pinned, so a
# trim back under the limit must not take it.
# The hard tier's claim is qualified by what it can READ (DEF-837's lane,
# plan step 5): the unqualified text told a command that IS the repo in a
# spelling the guard cannot read -- a loop list beside a substitution
# (DEF-844; `$PWD` was one too until DEF-843 read it) -- that the repo
# itself is hard-blocked, at the moment it was not. A nudge means "not
# walled", never "not catastrophic".
_RMRF_TAIL = (
    "; write_guard hard-blocks the root, your home directory, the repo itself and "
    "shallow system paths if it can read them; this covers the rest -- a tree "
    "inside the repo or home, a $VAR path other than $HOME, or a spelling it "
    "cannot read, possibly one of those -- confirm the target"
)
_RMRF_BODY = "recursive delete has no recovery" + _RMRF_TAIL
_RMRF_SNAPSHOT_BODY = (
    "recursive delete has no recovery except the tracked-edit snapshot just "
    "taken (cc/discard_snapshots.log, last line; `git show <sha>:<path>`)" + _RMRF_TAIL
)


def _discard_body(tool_name: str, tool_input: dict, root: Path, cwd: Path | None = None) -> str:
    return _DISCARD_BODY if _snapshot_taken_for(tool_name, tool_input, root) else _DISCARD_NO_SNAPSHOT_BODY


def _rmrf_body(tool_name: str, tool_input: dict, root: Path, cwd: Path | None = None) -> str:
    return _RMRF_SNAPSHOT_BODY if _snapshot_taken_for(tool_name, tool_input, root) else _RMRF_BODY


CP_DISCARD = SpeedBump(
    id="CP-DISCARD",
    predicate=_pred_discard,
    body=_DISCARD_BODY,
    body_for=_discard_body,
    cap_exempt=True,
    flag_key=_discard_key,      # per-invocation one-shot: a 2nd DISTINCT discard
                                # re-nudges; an identical re-issue still passes
)

CP_GITCLEAN = SpeedBump(
    id="CP-GITCLEAN",
    predicate=_pred_gitclean,
    body="git clean -f permanently deletes UNTRACKED files (with -x, ignored files "
         "too); they were never in git, so there is no reflog or object to recover "
         "-- confirm the target, or preview first with `git clean -n`",
    cap_exempt=True,
    flag_key=_discard_key,      # per-invocation one-shot (shares CP-DISCARD's command
                                # hash; the id namespaces the flag file, so no clash):
                                # a 2nd DISTINCT clean re-nudges; an identical re-issue
                                # maps to the same key and passes (the flag IS the allow)
)

CP_RMRF = SpeedBump(
    id="CP-RMRF",
    predicate=_pred_rmrf,
    body=_RMRF_BODY,
    body_for=_rmrf_body,          # names the snapshot only when one was taken (DEF-802)
    cap_exempt=True,
    flag_key=_discard_key,      # per-invocation: deleting a DIFFERENT tree is a
                                # different irreversible act and must re-nudge
)


# CP-FETCHEXEC -- the download-and-execute class, on BOTH shells: remote text
# handed straight to an interpreter in ONE statement, so it runs before anyone
# reads it. Soft, not a `DANGEROUS_*_PATTERNS` record, and that is deliberate:
# the parity gate (`tests/test_write_guard_pattern_message_coupling.py`) holds
# every hard record to a twin on the other shell, and a wall would make every
# installer pipeline (`irm get.scoop.sh | iex`, the Homebrew `bash -c "$(curl
# ...)"`) impossible under the harness with no re-issue and no maintenance
# bypass -- the shape that gets the hooks switched off. Driven at HEAD before
# this row: every shape below ALLOWED on its tool, while the two POSIX
# permission defaults (`settings_profiles._DENY_DEFAULTS`: `curl * | sh`,
# `wget * | sh`) implied a coverage the hook layer never had (DEF-738).
#
# Both arms read the masked text (Bash) / the joined scan text (PowerShell)
# and every pattern is command-position anchored, so a grep, an echo, a
# SINGLE-LINE commit message, a `$doc = '...'` assignment or a `Select-String`
# pattern quoting the idiom is silent. The idiom on a commit BODY line or a
# heredoc body line fires: the Bash masker returns the raw text for any
# command whose head can re-parse an argument (`git`, `python3`) and a
# newline is a command position -- the tier-wide rule every checkpoint here
# shares (CP-RMRF's attested 2026-08-10 false fire), pinned as firing rows and
# keyed per invocation so it costs a rewrite, never the protection. Every span
# is a class that excludes its own delimiter and is bounded, and every
# adjacent quantifier pair is mutually exclusive (the ReDoS receipt in
# docs/SHARP_EDGES.md); the five patterns sit outside BOTH derived ReDoS
# populations (`tests/test_redos.py` harvests `_bash_patterns` and
# `write_guard`; the git census keys on the substring `git`), so
# `tests/test_speedbump_irreversible.py` budgets EVERY compiled pattern in
# this module, per probe, at the 32 KB command cap.
#
# Declared limits, pinned as silent rows: the two-statement form (download to
# a file, then run it -- it leaves an artifact to read), a fetch held in a
# variable, the `-ArgumentList` ARRAY spelling (the exec-quote arm's own
# DEF-717 limit), nine pipe hops or a 2048-byte span (the bounds), and a
# program handed to the OTHER shell (the soft tier stays tool-keyed -- see the
# module docstring). A DOUBLE-quoted program handed to `powershell -Command` /
# `iex` on the PowerShell tool was a limit here until DEF-753: the shared
# masker blanked the separators of every expandable span, re-parsed or not,
# so the `|` never reached this arm nor the hard tier's; it keeps them live
# now, and both quote kinds fire.

#: The fetch heads, and the two kinds of target. On the pipe arm a SHELL runs
#: whatever arrives on stdin, so it fires with any arguments (`bash -s --
#: --yes`); a scripting interpreter runs stdin only when it is given NO
#: program -- bare, or the explicit `-` -- because `curl ... | python3 -m
#: json.tool` and `| perl -pe 's/a/b/'` hand the fetched text to LOCAL code as
#: data, the opposite of the class (code review, driven: `| python3 -m
#: json.tool` drew a nudge while `| jq` did not). A process substitution is a
#: FILE, so on that arm every interpreter runs it.
_FETCH_VERB = r"(?:curl|wget)"
_FETCH_SHELL = r"(?:ba|z|k|da)?sh"
_FETCH_SCRIPTER = r"(?:python[0-9.]*|perl|ruby|node)"
_FETCH_INTERPRETER = r"(?:" + _FETCH_SHELL + r"|" + _FETCH_SCRIPTER + r")"
#: The scripter fires only when its next token is absent or is the bare `-`:
#: two negative lookaheads (not followed by a token starting with anything
#: but `-`; not followed by a `-` token longer than the dash), spelled with
#: negated classes so the newline census can see that nothing here reads
#: past a line end.
_FETCH_PIPE_TARGET = (
    r"(?:" + _FETCH_SHELL + r"\b"
    r"|" + _FETCH_SCRIPTER + r"\b(?![ \t]*[^ \t;&|\r\n-])(?![ \t]*-[^ \t;&|\r\n]))"
)

#: A pipe broken over a newline is ONE pipeline in both shells' grammar
#: (`curl ... |` + newline + `sh`; ordinary in bash, idiomatic in
#: PowerShell). Joined into `| ` before the arms match, exactly as the
#: PowerShell scan text joins a backtick continuation, so every arm stays
#: single-line and the newline census can hold it to that. A `|` inside an
#: inert span has already been blanked by the masker, so only a live pipe is
#: ever joined. SYNTAX token: names no verb, declared as such in the
#: anchored-or-declared census.
_PIPE_CONTINUATION_RE = re.compile(r"\|(?!\|)[ \t]*\r?\n[ \t]*")

# `curl ... | sh`, `wget -qO- ... | sudo -E bash -`, `curl ... 2>&1 | sh`,
# `curl ... | tee log | sh`, `curl ... | /usr/bin/env bash`: a fetch at
# command position, one to eight pipe hops -- each hop a span that excludes
# `|` and every `&` but a redirect's (`2>&1`), so the hops are delimited
# without ambiguity and `||` is a fallback, not a pipe -- then the shared
# wrapper run (`sudo -E`, `env`, `nohup`, bare or path-qualified) and the
# target, bare or path-qualified via the shared verb prefix. Case-insensitive:
# `CURL` runs on a case-insensitive filesystem, which both platforms the
# harness ships to have. The hop count and the span are BOUNDED (ReDoS); the
# shapes past them are pinned as silent rows so a widening is a decision on
# the record.
_FETCH_EXEC_PIPE_RE = re.compile(
    _bash_patterns._CMD_POS + _FETCH_VERB + r"\b"
    r"(?:(?:[^\n;&|]|(?<=>)&){0,2048}\|(?!\|)){1,8}[ \t]*"
    # `_CMD_POS_WRAP_RUN` is ONE wrapper with its flags (the anchor stars it
    # inside a wider alternation); starred here, bounded, behind an optional
    # path that must be followed by a wrapper word (`/usr/bin/env bash`).
    r"(?:[\w./-]*/(?=" + _bash_patterns._CMD_POS_WRAPPER + r"\b))?"
    r"(?:" + _bash_patterns._CMD_POS_WRAP_RUN + r"){0,4}"
    + _bash_patterns._CMD_POS_VERB_PREFIX + _FETCH_PIPE_TARGET,
    re.IGNORECASE,
)

# `bash <(curl ...)`, `source <(curl ...)`, `. <(wget -qO- ...)`, `python3
# <(curl ...)`: the interpreter (or `source` / `.`) at command position with a
# fetch inside a process substitution among its arguments.
_FETCH_EXEC_PROCSUB_RE = re.compile(
    _bash_patterns._CMD_POS + r"(?:" + _FETCH_INTERPRETER + r"|source|\.)"
    r"(?:[ \t]+-[^\s;&|]+){0,8}[ \t]+<\([ \t]*" + _FETCH_VERB + r"\b",
    re.IGNORECASE,
)

# `bash -c "$(curl ...)"`, `bash -lc "$(curl ...)"`, `sh -ec "$(wget ...)"`,
# `eval "$(curl ...)"`, the backtick spelling of the same: the fetch's OUTPUT
# becomes the program. The `-c` may sit in a cluster (`-lc`, `-ec`).
_FETCH_EXEC_SUBST_RE = re.compile(
    _bash_patterns._CMD_POS
    + r"(?:eval|(?:" + _FETCH_SHELL + r"|python[0-9.]*)[ \t]+-[A-Za-z]*c\b)"
    r"[ \t]+[\"']?(?:\$\(|`)[ \t]*" + _FETCH_VERB + r"\b",
    re.IGNORECASE,
)

#: The PowerShell fetch heads: the two cmdlets and their aliases (`curl` and
#: `wget` resolve to Invoke-WebRequest on Windows PowerShell), and the .NET
#: WebClient's `DownloadString` / `DownloadData`, constructed either way.
_PS_FETCH_HEAD = (
    r"(?:(?:irm|iwr|Invoke-RestMethod|Invoke-WebRequest|curl|wget)\b"
    r"|(?:New-Object[ \t]+(?:-TypeName[ \t]+)?(?:System\.)?Net\.WebClient"
    r"|\[(?:System\.)?Net\.WebClient\]::new\(\))\)?\.Download(?:String|Data)\()"
)
_PS_EXEC_HEAD = r"(?:iex|Invoke-Expression)"
#: One opening paren -- `(`, the `$(` subexpression or the `@(` array -- and
#: the spaces after it. Every run of these is BOUNDED where it is used: every
#: `(` is also a command-position separator, so an unbounded run is quadratic
#: on a paren flood (each `(` a fresh start that walks the rest of the run).
_PS_PAREN = r"(?:[$@]?\([ \t]*)"

# `irm ... | iex`, `iwr -useb ... | iex`, `(New-Object Net.WebClient)
# .DownloadString('...') | iex`, `iwr ... | Select-Object -ExpandProperty
# Content | iex`: a fetch at command position, one to eight pipe hops, then
# the executor.
_PS_FETCH_EXEC_PIPE_RE = re.compile(
    _bash_patterns._PS_CMD_POS + _PS_PAREN + r"{0,8}" + _PS_FETCH_HEAD
    + r"(?:[^\n;|]{0,2048}\|){1,8}[ \t]*" + _PS_EXEC_HEAD + r"\b",
    re.IGNORECASE,
)

# `iex (irm ...)`, `iex $(irm ...)`, `iex ((New-Object Net.WebClient)
# .DownloadString('...'))`, `iex ([Text.Encoding]::UTF8.GetString((New-Object
# Net.WebClient).DownloadData('...')))`, `& ([scriptblock]::Create((irm ...)))`:
# the executor wrapping the fetch, directly or through one static-method
# decoder. `(` is itself a separator, so the `& (` and `-ScriptBlock (`
# spellings put `[scriptblock]::Create` at a command position of its own.
_PS_FETCH_EXEC_WRAP_RE = re.compile(
    _bash_patterns._PS_CMD_POS
    + r"(?:" + _PS_EXEC_HEAD + r"|\[scriptblock\]::Create)[ \t]*"
    + _PS_PAREN + r"{1,8}"
    r"(?:\[[\w.]+\]::[\w.]+\([ \t]*(?:\([ \t]*)?)?"
    + _PS_FETCH_HEAD,
    re.IGNORECASE,
)


def _pred_fetchexec(tool_name: str, tool_input: dict, root: Path, cwd: Path | None = None) -> bool:
    if tool_name == "PowerShell":
        # The joined scan text, like `_pred_rmrf`'s PowerShell arm: masked, and
        # backtick continuations folded, so `irm ...` + backtick-newline +
        # `| iex` is one statement here too; then the bare pipe continuation.
        cmd = _PIPE_CONTINUATION_RE.sub(
            "| ", _bash_patterns.powershell_scan_text(tool_input.get("command", "")))
        return bool(_PS_FETCH_EXEC_PIPE_RE.search(cmd)
                    or _PS_FETCH_EXEC_WRAP_RE.search(cmd))
    if tool_name != "Bash":
        return False
    for text in _scan_texts(tool_input):
        cmd = _PIPE_CONTINUATION_RE.sub("| ", text)
        if (_FETCH_EXEC_PIPE_RE.search(cmd)
                or _FETCH_EXEC_PROCSUB_RE.search(cmd)
                or _FETCH_EXEC_SUBST_RE.search(cmd)):
            return True
    return False


CP_FETCHEXEC = SpeedBump(
    id="CP-FETCHEXEC",
    predicate=_pred_fetchexec,
    body="this fetches remote content and hands it straight to an interpreter, "
         "unread -- a moved or hijacked URL runs as you, with nothing on disk to "
         "inspect; pin a version or checksum, or download to a file and read it "
         "before running",
    cap_exempt=True,            # the code runs before anyone reads it: irreversible
    flag_key=_discard_key,      # per-invocation: a DIFFERENT script from a
                                # different URL is a different act and must re-nudge
)


# ── The meta-cognitive tier (CP-GATEWEAKEN keystone + CP-COMPACT) ──
# Fires on EPISTEMIC failure modes, not irreversible-external ones: a silently-
# weakened gate riding green-local to merge, and the first mutation on a post-
# compaction plan that was rebuilt-from-summary, not retained.

_MUTATING_TOOLS = ("Write", "Edit", "NotebookEdit")  # shared by both predicates


# CP-GATEWEAKEN -- the keystone. A weakened blocking-hook deny
# path goes green-local and rides to merge INVISIBLY. It must fire under
# MAINTENANCE_MODE (the speed-bump call site precedes write_guard's maintenance
# gate), the exact session class where guard edits arrive in bursts.
# The predicate is a SYNTACTIC pre-edit proxy: the deny
# count-delta is NOT cheaply computable at PreToolUse (the edit has not applied),
# so we fire when `new_string` REMOVES / replaces a deny token relative to
# `old_string` -- cheap, no file read. NOTE the proxy is removal-only: a deny
# line commented in place keeps the token substring, so its count is unchanged
# and the proxy does not catch in-place commenting (catching that cheaply would
# need a file read -- the design accepts the gap).
# sister-site: ok purpose-scoped: gate-weaken keystone's guard subset (EXCLUDES _speedbump.py itself), not the wired-hook roster
_GUARD_FILES = ("write_guard.py", "plan_guard.py", "config_guard.py", "stop_gate.py")
# config_guard.py and stop_gate.py deny via `return block(...)`, not
# `deny(...)`. Without `block(`/`return block` the removal proxy would be blind
# to a real deny-path removal in those two in-list guard files. The advisory
# proxy stays soft (cap-exempt, per-file one-shot). (NOTE: _protected_zones.py /
# _bash_patterns.py deny via bare
# `return True` from named predicates — no deny-token substring — so adding
# them to _GUARD_FILES would be inert, and a `return True` token would over-fire
# on every benign `return True` removal. Detecting their predicate-flip needs a
# separate named-predicate mechanism; deferred, not bolted on here.)
# sister-site: ok purpose-scoped: superset of _born_weak._BW_DENY_TOKENS; a _ helper may carry the exit-2 tokens
_DENY_TOKENS = ("return deny", "deny(", "return block", "block(", "permissionDecision", "return 2", "exit(2)", "exit 2")


# A full-file Write carries no pre-image, so the comparison has to come from
# disk. Capped, because this sits on the PreToolUse path -- though only after the
# guard-file name check below, so the read is paid on guard-file writes ONLY, not
# on every Write in the session.
_GATEWEAKEN_PREIMAGE_CAP = 1_000_000  # bytes


def _gateweaken_preimage(tool_input: dict, path: str, root: Path) -> str:
    """The text this mutation REPLACES.

    An Edit states it (`old_string`). A Write does not: it replaces the WHOLE
    file, and the pre-image is what is currently on disk.

    Every failure returns `""`, which yields no fire. That is the correct
    direction for all three cases that reach it: a file that does not exist yet
    cannot have its gate weakened, an unreadable file is not evidence of
    weakening, and a speed-bump must never become a wall on an I/O error.
    """
    old = tool_input.get("old_string")
    if isinstance(old, str):
        return old                      # Edit / NotebookEdit state their own
    # The checkout the target sits in, not the root: a worktree session's guard
    # file is the worktree's copy, and reading the root's copy (a different
    # commit) as the pre-image turned a harmless worktree edit into a deny --
    # driven by the DEF-743 failure-mode review against a worktree behind main.
    base, rel = resolve_in_checkout(path, root)
    if rel == "<invalid>":
        return ""
    try:
        target = base / rel
        if target.stat().st_size > _GATEWEAKEN_PREIMAGE_CAP:
            return ""
        return target.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""


def _pred_gateweaken(tool_name: str, tool_input: dict, root: Path, cwd: Path | None = None) -> bool:
    if tool_name not in _MUTATING_TOOLS:
        return False
    path = (tool_input.get("file_path") or "").replace("\\", "/")
    # Edit carries new_string; Write carries content -- accept either shape.
    new = (tool_input.get("new_string") or "") + (tool_input.get("content") or "")
    # disableAllHooks in any settings.json is a gate-weakening of last resort.
    if path.endswith("settings.json") and "disableAllHooks" in new:
        return True
    # The guard file itself, not a file that merely ends in its name: a
    # suffix match read `tests/test_write_guard.py` as `write_guard.py` and
    # bumped an edit that dropped a deny token from a TEST (driven 2026-09-13
    # while the DEF-790 rows were written).
    if not any(path == g or path.endswith("/" + g) for g in _GUARD_FILES):
        return False
    # ⚠ THE PRECISION WAS INVERTED, AND THE SILENT HALF WAS THE WORSE ONE. This
    # arm used to read `old_string` directly, so a full-file Write -- which has
    # none -- compared 0 against N and could never fire. Driven with flags
    # cleared: a Write of `def main(): return 0` over write_guard.py, DELETING
    # EVERY DENY PATH IN THE KEYSTONE, was SILENT, while narrow Edits that merely
    # reflowed a docstring containing a deny token FIRED. The comment this
    # replaces called a full-file Write not "cheaply comparable" and reasoned that
    # "the realistic weakening vector is a targeted Edit" -- but the Write tool is
    # the ordinary way to rewrite a file, so the arm that was dismissed as
    # unrealistic was the one that removed the most.
    old = _gateweaken_preimage(tool_input, path, root)
    # Fire when the mutation reduces a deny-token count (removal / replacement).
    return any(old.count(tok) > new.count(tok) for tok in _DENY_TOKENS)


def _gateweaken_key(tool_name: str, tool_input: dict) -> str:
    # per-FILE keying: a maintenance burst across the four
    # guard files fires once PER FILE, not once total -- else edits 2..N each
    # weaken a different gate with no reminder. settings.json shares one key.
    path = (tool_input.get("file_path") or "").replace("\\", "/")
    return path.rsplit("/", 1)[-1] or "settings"


CP_GATEWEAKEN = SpeedBump(
    id="CP-GATEWEAKEN",
    predicate=_pred_gateweaken,
    body="this edit weakens a blocking hook (removes a deny/exit-2 path) or sets "
         "disableAllHooks -- both loosen future safety and drop plan_guard. Drive "
         "guard changes through /implement-task and prove the KEPT deny still fires "
         "with a regression test THIS session (consider /adversarial); for a legit "
         f"harness self-edit, relaunch with {_maintenance_mode.relaunch_hint()} "
         "instead of disabling hooks",
    cap_exempt=True,            # NEVER budget-suppressed (the keystone)
    flag_key=_gateweaken_key,   # per-file one-shot
    # fires_in_maintenance is left at its default: the "fires under MAINTENANCE"
    # property comes from the write_guard call-site ordering (pre-maintenance
    # gate), NOT this field, which check() does not consult.
)


# CP-COMPACT -- the first mutating action after compaction lands on a plan that
# was REBUILT from a summary, not retained. It is the one v1 checkpoint that is
# cap-GOVERNED (cap_exempt=False, dispositional not irreversible) and the one that
# needs a producer: post_compact.py drops `post_compact_pending`,
# session_start clears it. The window is best-effort, convention-pinned: the live
# hook protocol does not contractually guarantee PostCompact runs to completion
# before the first post-compaction PreToolUse (docs/external/cc-hook-protocol.md
# marks PostCompact "N/A -- nothing to block"; HOOK_ASSUMPTIONS A4 is
# convention-only). In practice PostCompact is a synchronous hook that completes
# at the compaction boundary before the conversation resumes, so the flag is
# present for the next tool call; if that ever failed, CP-COMPACT simply would
# not fire (fail toward no-nudge, never a false deny).

# Cheap write-verb heuristic: a read-only Bash (grep/cat/ls/git status) must NOT
# consume the post-compaction window; a writing Bash should. Fail toward NOT
# firing -- a missed write costs one un-nudged mutation (the re-orient is
# dispositional), never a false deny. _speedbump cannot import write_guard's
# write-verb detectors (write_guard imports _speedbump -> circular), so this is a
# self-contained regex, not a reuse.
# ⚠ THE VERB ARMS ARE ANCHORED; THE REDIRECT ARM IS NOT, AND THAT IS DELIBERATE.
# A write VERB is only a write when it sits at a command position -- a bare
# `\bcp\b` fires on `grep -rn 'cp ' docs/`, on a commit message mentioning `mv`,
# and on any prose naming `touch` or `patch`, none of which mutate anything.
# A REDIRECT has no command position to sit at: `>` is an operator, it is the
# write, and it appears mid-command by construction. Anchoring it would blind the
# most common write idiom there is, so that arm keeps its bare form and accepts
# the quoted-mention over-fire -- this predicate only decides whether the
# post-compaction re-orient window is consumed, so over-firing costs a nudge and
# under-firing costs an un-nudged mutation.
_WRITING_BASH_RE = re.compile(
    r">>?"                                              # output redirect (see above)
    r"|" + _bash_patterns._CMD_POS + r"tee\b"           # tee
    r"|" + _bash_patterns._CMD_POS + r"sed\b[^|;&\n]*[ \t]-i"   # sed -i (in-place)
    r"|" + _bash_patterns._CMD_POS
    + r"(?:cp|mv|dd|install|rsync|truncate|patch|mkdir|touch|ln)\b"
)


def _is_writing_bash(tool_input: dict) -> bool:
    # Raw by design (a mention still counts for this advisory), but continuations
    # spliced so `sed \` + newline + `-i` is one statement here too (DEF-701).
    return bool(_WRITING_BASH_RE.search(
        _bash_patterns.splice_line_continuations(tool_input.get("command", ""))
    ))


def _pred_compact(tool_name: str, tool_input: dict, root: Path, cwd: Path | None = None) -> bool:
    # Only a MUTATING action consumes the window. A read-only Bash/Read
    # re-orienting BEFORE a read is friction-negative -> must NOT fire.
    if tool_name not in _MUTATING_TOOLS and not (
        tool_name == "Bash" and _is_writing_bash(tool_input)
    ):
        return False
    return (root / STATE_DIR / "post_compact_pending").exists()


CP_COMPACT = SpeedBump(
    id="CP-COMPACT",
    predicate=_pred_compact,
    body="context was compacted -- your plan was rebuilt from a summary, not "
         "retained; re-verify the live goal and the last decisions before mutating "
         "(consider /reflect)",
    cap_exempt=False,   # the one cap-GOVERNED v1 checkpoint (dispositional, not irreversible)
)


# ── The v1.1 rescued tier (CP-MCP-SIDEEFFECT) ──
# MCP external-side-effect writes (send/delete/trigger/post/create/...) reach OUTSIDE the
# repo -- a sent email, a deleted remote resource, a triggered webhook -- irreversible by a
# DIFFERENT axis than git, and plan_guard does not gate mcp__ at all.

# mcp__<server>__<action> -- the <server> segment may itself contain underscores
# (e.g. mcp__claude_ai_Gmail__send_email), so DO NOT anchor on [^_]+. Match the action verb
# as a COMPLETE LEADING TOKEN on the FINAL segment with .match: `(?:verb...)(?:_|$)`. The
# `(?:_|$)` boundary, NOT a bare stem, for two reasons: (1) DO NOT use \b -- underscore is a
# word char, so \bsend never matches right after `__`; (2) a bare stem OVER-fires on read
# names that merely START with a verb substring (`post`->postpone_event, `update`->
# updates_feed, `move`->movements, `archive`->archived_items). The boundary fires
# `update_record` / `create_preview` (verb leads a real token) but stays silent on
# `updates_feed` -- making the silent-bias posture below honest. The accepted residual is
# the OTHER direction: verb-not-leading forms (`bulk_delete`, `batch_send`) fall silent --
# the v1.1 under-fire (external-irreversible but not harm-sealed at the PyPI-burn tier, so
# an under-fire is the cheaper error; tighten from observed data).
# Local-filesystem path fields ONLY (mcp__filesystem__*). A narrowed subset of the
# shared _hook_utils.MCP_PATH_FIELDS: it deliberately DROPS the generic external-payload
# fields (source/target/uri/target_uri) so send/trigger/post side effects that leave the
# repo still get nudged. A real mcp__filesystem__move_file carries
# `destination`, so it continues to defer to write_guard via that field.
_LOCAL_FS_FIELDS = ("path", "file_path", "destination", "new_path", "src", "dst")

_MCP_SIDEEFFECT_VERB_RE = re.compile(
    r"(?:send|delete|remove|trigger|post|create|update|publish|archive|move)(?:_|$)", re.I
)
# Read/neutral verbs that must stay SILENT, incl. the auth-flow verbs in this env's
# claude_ai_* servers (authenticate / complete_authentication) -- not data mutations worth
# a deny. Same token-boundary discipline.
_MCP_READ_VERB_RE = re.compile(
    r"(?:get|list|search|read|fetch|view|describe|authenticate|complete)(?:_|$)", re.I
)


def _pred_mcp_sideeffect(tool_name: str, tool_input: dict, root: Path, cwd: Path | None = None) -> bool:
    if not tool_name.startswith("mcp__"):
        return False
    # DEFER to write_guard only for LOCAL-filesystem MCP ops (mcp__filesystem__*),
    # which carry a local path field (write_guard.py:449 protected-zone domain). Those
    # are NOT external side effects -- staying silent lets the hard-deny own them in ONE
    # round and keeps the nudge body ("leaves the repo") factually true. Sister to CP-RMRF
    # deferring to write_guard's rm hard-deny.
    #
    # The defer must NOT key on generic external-payload fields. The broad
    # _hook_utils.MCP_PATH_FIELDS includes target/uri/target_uri -- so send_email{target},
    # trigger_webhook{uri}, send_sms{target} were silently deferred and got NO nudge from
    # either tier. Narrow to a local-fs-only subset here (do NOT mutate the shared
    # MCP_PATH_FIELDS -- other callers rely on its breadth).
    if isinstance(tool_input, dict) and any(tool_input.get(f) for f in _LOCAL_FS_FIELDS):
        return False
    parts = tool_name.split("__")
    action = parts[-1] if len(parts) >= 3 else ""   # mcp__<server>__<action>
    if _MCP_READ_VERB_RE.match(action):
        return False
    return bool(_MCP_SIDEEFFECT_VERB_RE.match(action))


def _mcp_tool_key(tool_name: str, tool_input: dict) -> str:
    # per-TOOL keying (DEF-8): the WHOLE `mcp__<server>__<action>` name, never
    # the action segment alone -- two servers' `send` are two tools, each with
    # its own target and payload to confirm. Until 2026-09-13 this checkpoint
    # carried no key at all, so the first MCP side-effect of a session nudged
    # and the second and third DIFFERENT side-effecting tools went unchallenged
    # (the SpeedBump contract handed flag_key tool_input only; the tool name
    # joined it for this row). An identical re-issue maps to the same key, so
    # the deny-once-then-allow retry still passes; the session cap still bounds
    # the total. Folded to a filesystem-safe suffix (the suffix is part of the
    # flag FILE name) and bounded, since a server name is operator-chosen text;
    # a long name keeps a readable head and a hash of the whole, so two names
    # sharing a long prefix never share a flag (failure-mode review).
    safe = re.sub(r"[^\w.-]", "_", tool_name)
    if len(safe) <= 80:
        return safe
    return safe[:64] + "_" + hashlib.sha256(tool_name.encode("utf-8")).hexdigest()[:16]


CP_MCP_SIDEEFFECT = SpeedBump(
    id="CP-MCP-SIDEEFFECT",
    predicate=_pred_mcp_sideeffect,
    body="this MCP tool has an external side effect (send/delete/trigger) that leaves the "
         "repo and may be irreversible -- confirm the target + payload before it runs",
    cap_exempt=False,   # dispositional -> cap-GOVERNED (an MCP write is not the
                        # release/force-push tier; one cap slot, not exempt)
    flag_key=_mcp_tool_key,     # per-tool one-shot (sister to CP-GATEWEAKEN's per-file key)
)


# Registry consumed by `check()` (default arg) + write_guard's dispatch.
SPEEDBUMPS: tuple[SpeedBump, ...] = (
    CP_FORCEPUSH, CP_RELEASE, CP_DISCARD, CP_GITCLEAN, CP_RMRF, CP_FETCHEXEC,   # irreversible-external
    CP_GATEWEAKEN, CP_COMPACT,                        # meta-cognitive
    CP_MCP_SIDEEFFECT,                               # v1.1 rescued (MCP side-effect)
)


def _flag_name(bump: "SpeedBump", tool_name: str, tool_input: dict) -> str:
    suffix = ""
    if bump.flag_key is not None:
        try:
            suffix = bump.flag_key(tool_name, tool_input) or ""
        except Exception:  # noqa: BLE001 -- a bad key never blocks; degrade to id-only
            suffix = ""
    base = f"{_FLAG_PREFIX}{bump.id}"
    return f"{base}_{suffix}" if suffix else base


def _compare_and_increment(state_dir: Path, cap: int) -> bool:
    """Read the session speed-bump counter; if < cap, increment and return True
    (fire); else return False (suppressed) WITHOUT incrementing. Not serialized on
    its own — callers wrap it in the flock below (or accept the documented
    Windows/flock-less non-atomic degrade, same posture as _locked_increment)."""
    current = _read_counter(state_dir, SPEEDBUMP_COUNTER)
    if current >= cap:
        return False
    try:
        _write_counter(state_dir, current + 1, SPEEDBUMP_COUNTER)
    except OSError:
        # Couldn't persist the slot; fail toward firing (the one-shot flag the
        # caller writes still bounds it to once per checkpoint).
        return True
    return True


def _locked_check_and_increment(state_dir: Path, cap: int) -> bool:
    """Atomically: if the session counter < cap, increment and return True (fire);
    else return False (suppressed) WITHOUT incrementing. The flock guarantees two
    concurrent PreToolUse hooks cannot both consume the same slot (no peek-then-
    increment race that would over-fire and worsen the storm the cap prevents).

    Models `_hook_utils._locked_increment`'s flock discipline but branches on the
    compare INSIDE the lock so a suppressed call does not inflate the count.
    """
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Read-only state dir: can't track the cap. Return True (fire-allowed); the
        # caller's one-shot flag write will then also fail and yield None -> no
        # deny. Net fail-toward-allow on an unwritable host, no state change.
        return True
    try:
        import fcntl  # POSIX only
    except ImportError:
        # Windows: non-serialized compare-then-write (documented limit, mirrors
        # _locked_increment). Cap is still enforced per-process, just not race-safe.
        return _compare_and_increment(state_dir, cap)
    lock_path = state_dir / (SPEEDBUMP_COUNTER + ".lock")
    try:
        with open(lock_path, "a+", encoding="utf-8") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            try:
                return _compare_and_increment(state_dir, cap)
            finally:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        # flock-less FS (some NFS / network mounts): degrade to best-effort
        # non-serialized compare-then-write rather than crash the PreToolUse hook.
        return _compare_and_increment(state_dir, cap)


# Any git verb that can discard TRACKED working-tree content. Wider than the
# reminder's trigger on purpose: a snapshot is cheap and harmless, so it should
# not depend on the reminder's precision -- including for forms neither regex has
# learned yet.
_SNAPSHOTABLE_TAIL = (
    r"[ \t]+(?:" + _GIT_PREOPT + r")*"
    r"(?:checkout|restore|reset\b[^\n;|&]*--hard|stash[ \t]+(?:drop|clear))"
)
_SNAPSHOTABLE_RE = re.compile(_GIT_CMD + _SNAPSHOTABLE_TAIL)
#: The PowerShell tool's own text (DEF-747; see `_PS_GIT_CMD`).
_PS_SNAPSHOTABLE_RE = re.compile(_PS_GIT_CMD + _SNAPSHOTABLE_TAIL, re.IGNORECASE)

SNAPSHOT_LOG = "cc/discard_snapshots.log"

#: The cheap gate before the removal arm walks anything: a delete verb of
#: either shell, by name, anywhere in the raw text -- but not the `-ri` of
#: `grep -ri` or the `--rm` of `docker run --rm` (`(?<![\w-])`; review).
_REMOVAL_HINT_RE = re.compile(
    r"(?<![\w-])(?:rm|rmdir|rd|ri|del|erase|remove-item)\b", re.IGNORECASE,
)
#: Distinct in-repo candidates the arm reads per command. Past it the promise
#: UNDER-states (a dirty target the arm did not reach draws the honest text),
#: the safe direction; a 500-operand delete is not the shape the row names.
_REMOVAL_CANDIDATE_CAP = 64


def _git_changed_paths(root: Path, pathspecs: list[str]) -> list[Path]:
    """The tracked files under ``pathspecs`` that differ from the index --
    `git diff --name-only`, ONE call for every candidate (the review measured
    one `--quiet` per candidate at 7.9 s for 500 operands). Empty when git
    could not answer: no promise is made on a non-answer."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", "-z", "--", *pathspecs],
            capture_output=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    names = [n for n in proc.stdout.decode("utf-8", "replace").split("\0") if n]
    return [(root / n).resolve() for n in names]


#: At most this many expansions of an operand's brace lists are read for the
#: removal snapshot; past it the operand is cut at its first brace instead.
_SNAPSHOT_EXPANSION_CAP = 16
_PATTERN_CHARS = "*?[{"


def _snapshot_spellings(spelled: str, *, braces: bool = True) -> list[str]:
    """The paths one delete operand takes, for the removal snapshot's
    positive confirmation (the review's item 10): its brace lists expanded
    (`_first_brace_group`'s comma groups, at most `_SNAPSHOT_EXPANSION_CAP`
    results), then each cut back at its first component carrying a pattern
    or a brace -- the directory the pattern expands in, which holds all it
    takes. Joined as spelled, `build/*` named no path a changed file lies
    under, so the deletes the glob relief now nudges took no backup. A cut
    that lands on the checkout root meets the store rule (no promise), which
    is right for a pattern there: `.*` can take `.git`. ``braces=False`` for
    PowerShell, where a brace in a path is a literal character."""
    pending, done = [spelled], []   # type: list[str], list[str]
    while pending:
        s = pending.pop()
        group = _bash_patterns._first_brace_group(s) if braces else None
        if group is not None:
            lo, hi, alts = group
            comma = len(alts) > 1 and ",".join(alts) == s[lo + 1:hi]
            if comma and len(done) + len(pending) + len(alts) <= _SNAPSHOT_EXPANSION_CAP:
                pending.extend(s[:lo] + alt + s[hi + 1:] for alt in reversed(alts))
                continue
        done.append(s)
    pattern_chars = _PATTERN_CHARS if braces else _PATTERN_CHARS.replace("{", "")
    out: list[str] = []
    for s in done:
        parts = s.split("/")
        for i, component in enumerate(parts):
            if any(ch in component for ch in pattern_chars):
                s = "/".join(parts[:i]) or ("/" if s.startswith("/") else ".")
                break
        if s not in out:
            out.append(s)
    return out


def _placed_rm_operands(text: str, at: Path) -> Iterator[tuple[str, list[Path]]]:
    """Every `rm` operand in a Bash text with the directories its statement
    runs in -- the payload's, moved by the command's own cd chain, placed by
    statement slice the way the hard tier places a delete (DEF-790); a walk
    that faults, or a text past the cap, places every operand at the start.
    The literal bindings are inlined first, as the write leg
    inlines them (`DIR=src; rm -rf $DIR` took no snapshot until the review
    drove it)."""
    text = _bash_patterns._expand_simple_var_assignments(text)
    try:
        chained, statements = _bash_patterns.bash_directory_chain(text, directory_exists(at))
    except Exception:  # noqa: BLE001 -- the walk is advisory; a fault degrades to the start
        chained, statements = text, []
    if not statements:
        for _rec, _force, operands in _bash_patterns.iter_rm_invocations(text):
            yield from ((op, [at]) for op in operands)
    else:
        for s, e, dirs in statements:
            bases = [join_directory(at, d) for d in dirs]
            for _rec, _force, operands in _bash_patterns.iter_rm_invocations(chained[s:e]):
                yield from ((op, bases) for op in operands)
    # The loop carrier (DEF-837's lane): the body's remove takes the loop
    # VARIABLE, which names nothing on disk, so the operands above placed
    # `<at>/$f`, found nothing dirty under it, and took no snapshot -- the
    # net absent exactly where the loop drew only a nudge. The loop's roots
    # are what it removes, read by the loop reader and placed by the wall's
    # own placement helper. Its own fault boundary: a fault in the loop
    # reader must not cost the direct operands above their snapshot.
    try:
        loops = list(_bash_patterns.iter_placed_loop_removals(text, at))
    except Exception:  # noqa: BLE001 -- a recovery aid; the loop arm's fault is no loop candidate, never a lost direct one
        loops = []
    for path, dirs in loops:
        yield path, ([Path(d) for d in dirs] or [at])


def _ps_absolute_parts(token: str) -> list[str]:
    """The plain ABSOLUTE targets one PowerShell remove token spells --
    rooted, drive-qualified or home-relative, each element of an array --
    for the removal snapshot (DEF-842). Nothing for a token carrying a
    variable, a backtick or a wildcard: the guard cannot read its value, and
    the promise stays positive-confirmation only."""
    bare = token.replace('"', "").replace("'", "")
    if any(ch in bare for ch in "$`*?["):
        return []
    out: list[str] = []
    for part in bare.split(","):
        p = part.replace("\\", "/")
        if p == "~" or p.startswith("~/"):
            # normalized AFTER the expansion: on Windows it yields backslashes
            # and the drive test below would miss it (the code review)
            p = str(Path(p).expanduser()).replace("\\", "/")
        if p.startswith("/") or _bash_patterns._DRIVE_OR_UNC_ABSOLUTE_RE.match(p):
            out.append(p)
    return out


def _removal_snapshot_targets(
    tool_name: str, tool_input: dict, root: Path, cwd: Path | None = None,
) -> list[str]:
    """The paths a delete in the command would take that hold uncommitted
    TRACKED edits inside this checkout -- the content `git stash create` can
    save and nothing else can (DEF-802).

    Bash `rm` in any spelling the shared tokenizer reads (a plain `rm` of a
    dirty file is the same loss as the recursive-force form, so the arm is
    wider than CP-RMRF's trigger, as the discard arm is wider than
    CP-DISCARD's), the roots a loop carrier's body removes WHOLE (DEF-837's
    lane: never a narrowed head's, nor an untracked-only listing's -- the
    promise is as wide as what the loop takes), and PowerShell `Remove-Item`
    and its aliases by the plainly relative tokens
    `_ps_removal_token_targets` vouches for and the plain absolute ones
    `_ps_absolute_parts` reads (DEF-842: the recursive remove without the
    force switch reaches the bump with an absolute target, where the force
    form is walled; a variable, backtick or wildcard spelling takes none). A
    find with a delete action and a pipeline into xargs are NOT read: a
    stated limit, `DEF-845`. Each operand is placed in its own statement's
    directory, and a program the command hands to a shell is read as bash
    receives it, and the literal bindings inlined first on both
    shells. Positive confirmation only: a candidate outside the checkout is
    skipped (the snapshot stashes THIS repo), a command that takes the
    snapshot's own store (the root, `.git`, the log) earns none, and a
    target counts only when `git diff --name-only` lists a tracked file at
    or under it -- one git call for every candidate, the first
    `_REMOVAL_CANDIDATE_CAP` distinct ones; a non-answer from git earns no
    promise. Empty on any tool but the two shells, and before any git call
    when the text names no delete verb."""
    command = tool_input.get("command", "")
    if tool_name not in ("Bash", "PowerShell") or not _REMOVAL_HINT_RE.search(command):
        return []
    at = Path(cwd or root)
    candidates: list[Path] = []
    if tool_name == "Bash":
        texts = [command, *_bash_patterns.nested_shell_programs(command)]
        for text in texts:
            for operand, bases in _placed_rm_operands(text, at):
                spelled = _bash_patterns._shell_unquote(operand)
                if not spelled or spelled.startswith("-"):
                    continue
                candidates.extend(join_directory(base, path)
                                  for path in _snapshot_spellings(spelled) for base in bases)
    else:
        command = _bash_patterns._expand_simple_ps_var_assignments(command)   # DEF-801's twin
        try:
            text, statements = _bash_patterns.powershell_directory_chain(
                command, directory_exists(at))
        except Exception:  # noqa: BLE001 -- the walk is advisory; a fault degrades to the start
            text, statements = _bash_patterns.powershell_scan_text(command), []
        for m in _bash_patterns._PS_REMOVE_ITEM_RE.finditer(text):
            here = m.start("args")
            dirs = next((ds for s, e, ds in statements if s <= here < e), (".",))
            bases = [join_directory(at, d) for d in dirs]
            args = m.group("args")
            # quote-aware, as the wall's reader splits the same span (the
            # lane's review): a quoted target with a space is ONE target
            for tok in _bash_patterns._ps_removal_target_tokens(
                    args, tokens=_bash_patterns._ps_operand_tokens(args)):
                elements = [tok]
                if "$" not in tok and "`" not in tok:
                    # a wildcard is read as the directory it expands in, as
                    # the Bash arm reads one (the review's item 10), each
                    # element of an array on its own; PowerShell has no brace
                    # lists, so only the pattern cut applies
                    bare = tok.replace('"', "").replace("'", "").replace("\\", "/")
                    if any(ch in bare for ch in "*?["):
                        elements = [_snapshot_spellings(e, braces=False)[0]
                                    for e in bare.split(",") if e]
                for element in elements:
                    parts = _bash_patterns._ps_removal_token_targets(element)
                    if parts is None:
                        # DEF-842: a recursive remove without the force switch
                        # reaches the nudge with an absolute target too (the
                        # force form walls one), so the promise reads a plain
                        # absolute spelling as the Bash arm reads one; the
                        # checkout test below keeps only what lies inside.
                        parts = _ps_absolute_parts(element)
                    candidates.extend(join_directory(base, part) for part in parts for base in bases)
        scan = _bash_patterns.powershell_scan_text(command)
        for body in _bash_patterns._ps_shell_program_bodies(command, scan):
            for operand, bases in _placed_rm_operands(body, at):
                spelled = _bash_patterns._shell_unquote(operand)
                if not spelled or spelled.startswith("-"):
                    continue
                candidates.extend(join_directory(base, path)
                                  for path in _snapshot_spellings(spelled) for base in bases)
    inside: list[str] = []
    for candidate in candidates:
        if len(inside) >= _REMOVAL_CANDIDATE_CAP:
            break
        if not _inside(candidate, root):
            continue
        spelled = str(candidate)
        if spelled not in inside:
            inside.append(spelled)
    if not inside:
        return []
    # A delete that takes the snapshot's own store gets NO promise: the stash
    # commit lives in the checkout's `.git` and the log under it, so a
    # command that removes the root, `.git` or the log destroys the net it
    # would be told it has (DEF-837's failure-mode review: `rm -rf .git src`,
    # and a same-line binding that names the checkout -- the wall could not
    # read one then; DEF-846 has it read a literal one now -- both promised a
    # snapshot the re-issue deleted). Under-promising is the
    # safe direction, as the candidate cap's note has it.
    home = root.resolve()
    store = (home / ".git", home / SNAPSHOT_LOG)
    for spelled in inside:
        here = Path(spelled).resolve()
        if here == home or any(s == here or here in s.parents for s in store):
            return []
    if _git_rc(root, "rev-parse", "--git-dir") != 0:
        return []
    changed = _git_changed_paths(root, inside)     # one call, every candidate
    if not changed:
        return []
    out: list[str] = []
    for spelled in inside:
        here = Path(spelled).resolve()
        if any(path == here or here in path.parents for path in changed):
            out.append(spelled)
    return out


def snapshot_discard(
    tool_name: str, tool_input: dict, root: Path, cwd: Path | None = None,
) -> str | None:
    """Capture dirty tracked content before a discard runs. Returns the sha, else None.

    A speed-bump is deny-once-then-allow, so re-issuing steps past it in one
    line -- which makes a reminder weak protection for content that has no
    reflog. This does not ask anyone to heed anything: it turns an
    unrecoverable loss into a recoverable one.

    ``git stash create`` is the right primitive and was verified to be
    side-effect-free: it writes a dangling commit holding the dirty worktree,
    leaves the working tree byte-identical, and adds ZERO entries to
    ``git stash list`` (so it cannot disturb an operator's own stashes). On a
    clean tree it prints nothing, so this is a natural no-op.

    Recovery is ``git show <sha>:<path>``.

    KNOWN LIMIT: ``stash create`` captures tracked modifications only. It does
    NOT cover untracked files, which is the ``git clean -f`` hazard CP-GITCLEAN
    guards -- that content was never in git, so there is no object to make.
    That limit is why the REMOVAL arm (DEF-802) is conditional: a delete is
    snapshotted only when its target holds dirty tracked content inside this
    checkout (`_removal_snapshot_targets`, placed from ``cwd``), and CP-RMRF
    names the snapshot only then -- an unconditional widening would have the
    text promise a net that was never cast for an untracked or out-of-repo
    target. What was taken is recorded for the bump (`_record_snapshot`).
    Never raises: a failed snapshot must not block the tool call.
    """
    readings = _discard_readings(tool_name, tool_input)   # Bash, or PowerShell (DEF-747)
    if not readings:
        return None
    cmd = tool_input.get("command", "")
    # ⚠ MATCH ON THE MASKED TEXT, LOG THE RAW. This was the only one of the five
    # discard-family readers scanning `tool_input["command"]` directly while its
    # four siblings all went through `_masked_command`, so a command whose quoted
    # PROSE mentioned a discard verb reached the snapshot path. It does not block
    # -- but it shells out to `git stash create` and appends a line to
    # `cc/discard_snapshots.log`, so the miss was a silent write rather than a
    # visible refusal, which is why nothing surfaced it. Observed doing exactly
    # that on 2026-08-24 while auditing this class.
    wanted = any((_SNAPSHOTABLE_RE if is_bash else _PS_SNAPSHOTABLE_RE).search(text)
                 for text, _raw, is_bash in readings)
    if not wanted:
        try:
            wanted = bool(_removal_snapshot_targets(tool_name, tool_input, root, cwd))
        except Exception:  # noqa: BLE001 -- a recovery aid; a fault in the removal arm is no snapshot, never a wedge
            wanted = False
    if not wanted:
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "stash", "create"],
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
        sha = (proc.stdout or "").strip()
        if proc.returncode != 0 or not sha:
            return None       # clean tree, or not a repo -- nothing to save
        log = root / SNAPSHOT_LOG
        log.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp}\t{sha}\t{' '.join(cmd.split())}\n")
        _record_snapshot(tool_name, tool_input, root, sha)
        return sha
    except (OSError, subprocess.SubprocessError, ValueError):  # strict decode: a structured answer (DEF-821)
        return None


def check_fired(
    tool_name: str,
    tool_input: dict,
    root: Path,
    *,
    bumps: tuple["SpeedBump", ...] = SPEEDBUMPS,
    cwd: Path | None = None,
) -> tuple[str, str] | None:
    """``(checkpoint id, deny-reason)`` for the first matching un-fired
    checkpoint, else None. ``cwd`` is the directory the command runs in
    (the hook payload's; DEF-790), handed to every predicate.

    Sets the one-shot flag as a side effect (the flag set IS the retry-allow). A
    `cap_exempt` bump bypasses the session cap entirely AND does not consume a slot,
    so a storm of benign bumps can never suppress the keystone.

    The id travels beside the reason so the caller can audit the fire under the
    rule that matched (``details.checkpoint``) without parsing it back out of
    the reminder text. ``check`` is the reason-only view.
    """
    state_dir = root / STATE_DIR
    for bump in bumps:
        try:
            if not bump.predicate(tool_name, tool_input, root, cwd):
                continue
        except Exception:  # noqa: BLE001 -- a predicate error never blocks the tool
            continue
        flag = state_dir / _flag_name(bump, tool_name, tool_input)
        if flag.exists():
            continue  # already fired this (checkpoint[, key], session) -> allow

        if not bump.cap_exempt:
            if not _locked_check_and_increment(state_dir, SPEEDBUMP_SESSION_CAP):
                continue  # budget exhausted -> allow (non-exempt only)

        try:
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text(bump.id, encoding="utf-8")
        except OSError:
            # If we cannot persist the one-shot, do NOT deny — a deny we can't
            # remember would storm every retry. Fail toward allow.
            return None
        body = bump.body
        if bump.body_for is not None:
            try:
                body = bump.body_for(tool_name, tool_input, root, cwd)
            except Exception:  # noqa: BLE001 -- the fire stands; a fault in the per-fire text falls back to the static body
                body = bump.body
        return bump.id, _REASON_TEMPLATE.format(id=bump.id, body=body)
    return None


def check(
    tool_name: str,
    tool_input: dict,
    root: Path,
    *,
    bumps: tuple["SpeedBump", ...] = SPEEDBUMPS,
    cwd: Path | None = None,
) -> str | None:
    """Return a deny-reason for the first matching un-fired checkpoint, else None.

    Reason-only view of ``check_fired`` (same side effects, same cap rules),
    kept for the tests that read the reminder text. A HOOK must not call it:
    the fire it reports carries no checkpoint id, so nothing can audit it --
    the unlogged speed-bump deny this repo already shipped once. Call
    ``check_fired`` and route the fire through the audited funnel
    (``tests/test_governance_audit_log.py`` pins that no hook calls ``check``).
    """
    fired = check_fired(tool_name, tool_input, root, bumps=bumps, cwd=cwd)
    return None if fired is None else fired[1]
