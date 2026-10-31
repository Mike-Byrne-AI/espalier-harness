#!/usr/bin/env python3
"""Ship a lane as one pull request, the same on every device.

The /ship and /handoff command bodies call this script, one verb per step,
instead of pasting bash blocks: the mechanics of a pull-request flow are
order-sensitive (bind the marker after the last push; never rewrite a pushed
lane; re-bind after a push; read back what was armed), and an order that lives
only in prose is an order a hurried session, a second checkout or a Windows
shell gets wrong. Here each verb refuses, by name, the state it must not act
on, and every spawn goes through one runner the tests replace.

Verbs (each stands alone and derives what it needs from git and gh):

    preflight            the tree is clean, the range is non-empty, the last
                         merges' post-merge reds (a red base is one `open`
                         refuses), and (where handoff_push is on) whether
                         this lane carries its handoff row
    lane                 on the default branch: move the unmerged commits to a
                         lane named from the head subject (a no-op elsewhere)
    open                 push once; open the pull request WITH the approval
                         marker already in the title when the diff needs one
                         (one event, one run, no edit); arm auto-merge; read
                         the arming back. First, when the lane would conflict
                         with the base, merge the base in locally with the
                         record files resolved by shape (record_merge.py), so
                         the pull request is born mergeable and the merge
                         rides the one push. Refuses while the base's
                         post-merge proof is red (a revert/ lane excepted,
                         and --base-red-ruled <ack id> lets a lane through on
                         the dispatcher's ack naming the red run: a red no
                         revert can clear is fixed forward on that ruling),
                         and notes this seat's other open pull request
    rebind               after an exceptional second push: re-bind the title
                         to the pull request's head, forcing a fresh run
    catch-up             under an up-to-date rule: merge the base in -- on the
                         server when GitHub reads the lane clean, locally with
                         the record files resolved by shape when it reads it
                         CONFLICTING (the server honours no merge driver) --
                         then pull or push, re-arm the own-clear marker at the
                         new head (HEAD moved with nothing to hand off, and the
                         mod holds the clear on a moved head), and re-bind
    status               the pull request's state, merge state, required reds,
                         and apart from them the cells a lost runner ended;
                         with the up-to-date rule off, whether the base moved
                         near its files since its CI ran (then: catch-up)
    rerun                re-run those cells once, when nothing else holds the
                         merge: the run is finished, was never re-run, and no
                         other red stands; otherwise says what does
    release vX.Y.Z       after the merge: tag the merge commit, push that one
                         tag, create the release
    handoff              /handoff's one push step: pushes only when
                         espalier.toml sets handoff_push = true (off by
                         default: a push is outward-facing), else says so;
                         last, once the step has run to its end -- landed, or
                         refused by a red base or after a landed push -- arms
                         the own-clear marker for this session
                         (.espalier-state/own_clear.json), which the own-clear
                         mod a seat.py launch loads reads to clear and re-prime
                         the window; a held refusal rides the marker and the
                         lane to land first rides the brief
    arm [--why ...]      the same arm by hand, for a lane opened by hand
                         (gh pr create ran no verb): a clean tree, a lane on
                         origin; over a marker already armed for this session
                         it re-arms at HEAD when HEAD moved (a pull by hand),
                         the brief kept, and refuses otherwise

Stdlib-only (``tools/cc/`` runs standalone, zero espalier imports); the guard
it asks about (``tools/cc/ci_guard.py``, an install-ci artifact) is loaded by
path when present, never imported. Operator-facing text is 7-bit ASCII.
Exit 0 on success, 1 on a named refusal, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# Sibling helpers, reached through the script's own directory (both ship in the
# deploy set; tests/test_deploy_set_import_closure.py pins the reachability).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _json_safe import decode_text_or_problem, fold_newlines, os_error_text, run_bounded  # noqa: E402
import _merge_rules  # noqa: E402  the up-to-date rule and the stale-base read, shared with the board
import _post_merge  # noqa: E402  the post-merge check verdicts, shared with the board and the banner
import _paths  # noqa: E402  the hooks-module loader behind the checkout's wiring note
import record_merge  # noqa: E402  the shape-aware merge of the record files (a deployed sibling)

MARKER = "HARNESS-UPDATE-APPROVED"
#: A bound marker anywhere in a title: the word, `@`, a hex run of seven or
#: more (git's short form up to a full sha) not glued to another word.
_MARKER_RE = re.compile(r" *" + MARKER + r"@[0-9a-fA-F]{7,40}(?![A-Za-z0-9])")
#: The espalier.toml key that lets /handoff push the lane. Absent is OFF: a
#: push is outward-facing, so a repository opts in (two field-trial adopters
#: found that nothing but the agent's vigilance told a new user /handoff
#: pushes). Declared in espalier/config.py::FOREIGN_KEYS. Read by a top-level
#: line scan, as scripts/record_snapshot.py reads its flags, so this script
#: stays stdlib-only on the 3.10 floor, which has no tomllib.
HANDOFF_PUSH_KEY = "handoff_push"
#: A table header line, `[name]` or `[[name]]`: not merely a line opening with `[`,
#: which a nested array element inside a multi-line value also does.
_TOML_TABLE_HEADER_RE = re.compile(r"""^[ \t]*\[\[?[ \t]*[A-Za-z0-9_."'-][A-Za-z0-9_."' -]*\]\]?[ \t]*(#.*)?$""")

DEFAULT_TIMEOUT = 60.0
#: Waits are bounded and polled; a wait that ends without its condition says so.
RUN_WAIT_SECONDS = 30.0
HEAD_MOVE_WAIT_SECONDS = 30.0
POLL_SECONDS = 3.0
TITLE_MAX = 72
POST_MERGE_ROWS = 20
#: The check-state sets, read from their one home (tools/cc/_post_merge.py,
#: which the banner loads by path and the board imports): green and running
#: states, and states that reach no verdict; a red is any other state. Aliases,
#: never copies: tests/test_hook_constant_parity.py pins that no literal returns.
_CHECK_GREEN = _post_merge.CHECK_GREEN
_CHECK_RUNNING = _post_merge.CHECK_RUNNING
_NO_VERDICT = _post_merge.NO_VERDICT
#: The conclusions that make a post-merge run on the base RED, from the same
#: home (the board's `_RED` reads it too). Every other completed conclusion
#: (cancelled, stale, skipped by a job-level `if`, neutral, action required) is
#: no verdict, so a skipped run never reads as a red base that asks a seat to
#: revert a merge.
_RUN_RED = _post_merge.RUN_RED
#: The workflow that proves the merged combination on the base branch after each
#: push (`.github/workflows/post-merge.yml`); a repository without it reads no runs.
POST_MERGE_WORKFLOW = "post-merge.yml"
#: How many of the base's post-merge runs are read back, newest first: the
#: board's window (`board.py`'s `RUN_WINDOW`; tests/test_ship_driver.py pins the
#: two equal). Each push's proof runs to the end beside the next (DEF-2015), so
#: a burst of merges holds several runs still going above the newest verdict,
#: and the five this read once took could all be such runs, hiding a red.
POST_MERGE_RUN_WINDOW = 20
#: The step the live-read workflow carries; its absence means the guard on
#: this tree judges the event payload's title.
LIVE_READ_STEP = "Read the pull request title as it is now"


def _check_outcome(row: object) -> str:
    """'green', 'running' or 'red' for one statusCheckRollup row: the one rule
    in tools/cc/_post_merge.py (a row of a shape it does not know reads as
    running, not as a pass), kept under this name for the open pull-request
    path's callers."""
    return _post_merge.check_outcome(row)


class Refused(Exception):
    """A named stop. The message is the reason the operator reads; exit 1."""


class Held(Refused):
    """A refusal the handoff arms the own-clear on, then re-raises: the lane
    is whole -- its row written, its tracked tree clean (both refused before
    this) -- and the window is done with it. ``landed`` says where it waits:
    False, held here because the base is red (nothing lands on a red base;
    the push never ran); True, on origin, the push landed and a step after
    it refused (the head wait, the rebind, the pull request's creation or
    arming). Any other refusal is the window's to fix first, and arms nothing
    (DEF-4057: three seats sat past the threshold for 17.5 h on 2026-10-29,
    their handoffs refused on a red base and no marker to clear them)."""

    def __init__(self, message: str, *, landed: bool) -> None:
        super().__init__(message)
        self.landed = landed


# ---------------------------------------------------------------- spawning --

def run(argv: list[str], *, timeout: float = DEFAULT_TIMEOUT, input: str | None = None,
        cwd: str | None = None, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    """The one spawn. Resolves the program through PATH (so `gh.exe` on Windows
    is found by its bare name), never a shell, always a timeout, stdin closed
    unless input is given. A program that is missing, that cannot start or
    that outlives the timeout is a named refusal, not a traceback. ``env``
    replaces the child's environment when given (the record merge's prune
    step needs one of its own); None inherits."""
    prog = shutil.which(argv[0])
    if prog is None:
        raise Refused(f"{argv[0]} is not on PATH")
    stdin_kw: dict = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
    try:
        # subprocess-contract: ok the argv is the caller's by design (one runner for every verb); each verb's argv is pinned by tests/test_ship_driver.py through the injectable runner
        result = run_bounded(
            [prog, *argv[1:]], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, cwd=cwd, env=env, **stdin_kw,
        )
    except subprocess.TimeoutExpired:
        raise Refused(f"{' '.join(argv[:2])} took longer than {timeout:.0f}s") from None
    except OSError as exc:
        raise Refused(f"could not run {argv[0]}: {os_error_text(exc)}") from None
    return result.returncode, result.stdout, result.stderr


#: The runner every verb uses; tests replace it with a recording fake.
RUN: Callable[..., tuple[int, str, str]] = run


def _git(*args: str, cwd: str | None = None) -> tuple[int, str, str]:
    return RUN(["git", *args], cwd=cwd)


def _gh(*args: str, cwd: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> tuple[int, str, str]:
    return RUN(["gh", *args], cwd=cwd, timeout=timeout)


def _gh_json(*args: str, cwd: str | None = None) -> object:
    """A gh read whose stdout is JSON, parsed whatever the exit code: `gh pr
    checks` exits 1 on a failed check and 8 while one is pending, the states a
    caller reads it for. Unparseable output is a refusal that quotes stderr."""
    rc, out, err = _gh(*args, cwd=cwd)
    try:
        return json.loads(out or "")  # json-dict-safe: ok every caller isinstance-checks the answer before a deref (pr_for_branch, _read_required, open_pr, rebind)
    except ValueError:
        raise Refused(f"gh {' '.join(args[:2])} answered rc={rc} with no JSON: {err.strip() or out.strip() or 'nothing'}") from None


def _say(text: str) -> None:
    print(text)


def _note(text: str) -> None:
    print(f"note: {text}")


#: Said once per run: every verb that pushes asks (open, handoff, rebind,
#: catch-up), and handoff and catch-up call rebind, which then stands down.
_WIRING_NOTE = {"asked": False}


def _wiring_note(root: Path) -> None:
    """One note, once per run, when a Claude Code session launched in this
    checkout would run with the gates off (DEF-1192: a worktree checks out
    tracked files only, and the project settings file is gitignored, so a lane
    shipped from one used to say nothing about it -- and the operator's own
    practice runs catch-up from a hand-made scratch worktree of the lane). The
    reader is ``hooks/_integrity.checkout_wiring_notice``, loaded by path; when
    it is not beside this script (an older deploy, a fixture that copies a
    subset of tools/cc) the note stands down. Never a refusal: the push is the
    operator's call, and this names what the checkout did not enforce on the
    way to it."""
    if _WIRING_NOTE["asked"]:
        return
    _WIRING_NOTE["asked"] = True
    loader = getattr(_paths, "hooks_module", None)   # a kept, older _paths.py: stand down
    reader = getattr(loader("_integrity"), "checkout_wiring_notice", None) if loader else None
    if reader is None:
        return
    line = reader(root)
    if line:
        _note(line)


# ------------------------------------------------------------- the repo view --

def repo_root() -> Path:
    rc, out, _ = _git("rev-parse", "--show-toplevel")
    if rc != 0 or not out.strip():
        raise Refused("not inside a git checkout")
    return Path(out.strip())


def default_branch() -> str:
    rc, out, err = _gh("repo", "view", "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name")
    name = out.strip()
    if rc != 0 or not name:
        raise Refused("gh could not name the default branch: sign in (gh auth status) or fix the remote"
                      + (f" -- {err.strip()}" if err.strip() else ""))
    return name


def current_branch() -> str:
    rc, out, _ = _git("branch", "--show-current")
    name = out.strip()
    if rc != 0 or not name:
        raise Refused("detached HEAD: switch to the lane")
    return name


def head_sha() -> str:
    rc, out, _ = _git("rev-parse", "HEAD")
    sha = out.strip()
    if rc != 0 or not sha:
        raise Refused("git could not name HEAD")
    return sha


def pr_for_branch(branch: str, state: str = "open") -> dict | None:
    """The one pull request for ``branch`` in ``state`` (open by default: a
    merged or closed one with the same head name must never take an edit)."""
    rows = _gh_json("pr", "list", "--head", branch, "--state", state, "--limit", "1",
                    "--json", "number,title,url,state,headRefOid,baseRefName,mergeStateStatus,mergeable,"
                              "autoMergeRequest,mergeCommit")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    return rows[0]


def _require_open_pr(branch: str) -> dict:
    pr = pr_for_branch(branch, "open")
    if pr is None:
        raise Refused(f"no open pull request for {branch}: run `open` first, or switch to the lane")
    return pr


# ---------------------------------------------------------------- the guard --

def guard_predicate(root: Path) -> Callable[[str], bool] | None:
    """The harness guard's `is_protected`, loaded BY PATH from the tree (an
    install-ci artifact, outside init's deploy set, so never imported); None
    when the tree has no guard, which is a tree with no marker to bind. A guard
    that is present but will not load fails closed: the marker is bound, and
    the reason is printed (the old bash block's rule: a check that did not run
    binds the marker; a marker nobody needed costs nothing)."""
    guard = root / "tools" / "cc" / "ci_guard.py"
    if not guard.is_file():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("_ship_ci_guard", guard)
    if spec is None or spec.loader is None:
        _note("the harness guard could not be loaded; binding the marker anyway")
        return lambda _p: True
    module = importlib.util.module_from_spec(spec)
    sys.modules["_ship_ci_guard"] = module  # registered before exec: a dataclass in the module needs it (3.14)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 -- fail-CLOSED with voice: a guard that will not load binds the marker
        _note(f"the harness guard could not be loaded ({os_error_text(exc)}); binding the marker anyway")
        return lambda _p: True
    predicate = getattr(module, "is_protected", None)
    if not callable(predicate):
        _note("the harness guard has no is_protected; binding the marker anyway")
        return lambda _p: True
    return predicate


def marker_needed(root: Path, base: str) -> list[str]:
    """The protected paths in the lane's diff against the base; empty when the
    diff touches none, or the tree has no guard. An empty diff is a refusal:
    a diff that listed nothing is a failed diff, not an unprotected one."""
    rc, out, err = _git("diff", "--name-only", f"origin/{base}...HEAD", cwd=str(root))
    if rc != 0:
        raise Refused(f"git diff against origin/{base} failed: {err.strip()}")
    paths = [line.strip() for line in out.splitlines() if line.strip()]
    if not paths:
        raise Refused(f"the diff against origin/{base} listed no paths: nothing to ship, or the base is not fetched")
    predicate = guard_predicate(root)
    if predicate is None:
        _note("no harness guard on this tree (tools/cc/ci_guard.py): marker not required")
        return []
    return [p for p in paths if predicate(p)]


def bind(title: str, sha: str) -> str:
    """The title with exactly one marker, bound to ``sha``'s short form: every
    earlier binding is stripped first (a title that accumulates stale bindings
    stays green on all of them and defeats the per-head audit trail)."""
    stripped = _MARKER_RE.sub("", title).rstrip()
    return f"{stripped} {MARKER}@{sha[:7]}"


# ------------------------------------------------------------------- verbs --

def memory_problem(root: Path) -> str:
    """The one-sentence problem with ESPALIER_MEMORY.md's bytes, prefixed with
    the file's name, or "" when it is absent or decodes. An operator-written
    record: a PowerShell redirect writes UTF-16 with a mark (read), a Windows
    editor's default is cp1252 (refused by name, never a traceback)."""
    memory = root / "ESPALIER_MEMORY.md"
    try:
        raw = memory.read_bytes()
    except OSError:
        return ""
    _text, problem = decode_text_or_problem(raw)
    return f"ESPALIER_MEMORY.md: {problem}" if problem else ""


def handoff_push_setting(root: Path) -> tuple[bool, str]:
    """``(on, how it was read)`` for ``handoff_push`` in ``<root>/espalier.toml``.

    Only the bare word ``true`` turns it on. Any other value reads as off and is
    named in ``how``, so a typo is visible instead of silently deciding; a key
    under a ``[table]`` header is not the top-level setting."""
    cfg = root / "espalier.toml"
    try:
        raw = cfg.read_bytes()
    except FileNotFoundError:
        return False, f"there is no espalier.toml, so {HANDOFF_PUSH_KEY} is off (the default)"
    except OSError as exc:
        return False, f"espalier.toml could not be read ({os_error_text(exc)}), so {HANDOFF_PUSH_KEY} reads as off"
    text, problem = decode_text_or_problem(raw)
    if problem:
        return False, f"espalier.toml: {problem}; {HANDOFF_PUSH_KEY} reads as off"
    table = ""        # the header the scan is under; "" is the top level
    under = ""        # a table the key was found under, which is not the setting
    near = ""         # a top-level key one spelling away (`handoff-push`, `Handoff_Push`)
    for line in text.splitlines():
        if _TOML_TABLE_HEADER_RE.match(line):
            table = line.split("#", 1)[0].strip()
            continue
        key, sep, value = line.split("#", 1)[0].partition("=")
        if not sep:
            continue
        key = key.strip()
        if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
            key = key[1:-1]   # a quoted key is the same key
        if key == HANDOFF_PUSH_KEY and table:
            under = under or table
        elif key == HANDOFF_PUSH_KEY:
            value = value.strip()
            if value in ("true", "false"):
                return value == "true", f"espalier.toml sets {HANDOFF_PUSH_KEY} = {value}"
            return False, (f"espalier.toml sets {HANDOFF_PUSH_KEY} = {value}, which is neither true nor "
                           "false, so it reads as off")
        elif not table and key.replace("-", "_").lower() == HANDOFF_PUSH_KEY:
            near = near or key
    if under:
        return False, (f"espalier.toml sets {HANDOFF_PUSH_KEY} under {under}, where it is not the "
                       "top-level setting, so it is off")
    if near:
        return False, f"espalier.toml sets {near}, not {HANDOFF_PUSH_KEY}, so it is off (the default)"
    return False, f"espalier.toml does not set {HANDOFF_PUSH_KEY}, so it is off (the default)"


#: Where a handoff writes its row since the Session Log became one file per
#: row (``_record_fragments.SESSION_LOG_DIR``; pinned with the other copies).
SESSION_LOG_DIR = "memory/session-log.d/"


def lane_carries_memory_row(base: str, root: Path) -> bool | None:
    """Do this lane's own commits carry a Session Log row: a change to
    ESPALIER_MEMORY.md (the table, on a tree before the fragments), or a file
    added under ``memory/session-log.d/`` (a handoff's row since 2026-10-10)?
    Reading the memory file alone refused every lane whose handoff wrote its
    row as a file (review of the Wave C batch). A row a fold commit added
    (``_record_fragments.FOLD_TRAILER``) is another session's, parked and
    brought in at a push, and does not count. None when git cannot answer: no
    verdict is ever a refusal on a guess."""
    rc, out, _ = _git("log", "--format=%h", f"origin/{base}..HEAD", "--", "ESPALIER_MEMORY.md",
                      cwd=str(root))
    if rc != 0:
        return None
    if out.strip():
        return True
    added = _lane_added_rows(root, base)
    if added is None:
        return None
    return bool(added)


def _fold_trailer() -> tuple[str, str]:
    """The fold trailer's key and value (``_record_fragments.FOLD_TRAILER``), or
    two empty strings where the loader is not beside this script."""
    fragments = _fragments_module()
    trailer = getattr(fragments, "FOLD_TRAILER", "") if fragments is not None else ""
    key, _sep, value = trailer.partition(": ")
    return key, value


def _lane_added_rows(root: Path, base: str) -> list[str] | None:
    """The Session Log files this lane's own commits added (``origin/<base>..HEAD``),
    less those a fold commit added: the commit's trailer is read by key, so a
    body that quotes the trailer's text in prose is still the lane's own (both
    reviews of DEF-5007). None when git cannot answer."""
    key, value = _fold_trailer()
    shown = f"%(trailers:key={key},valueonly)" if key else ""
    rc, out, _ = _git("log", f"--format=%x1e{shown}%x1f", "--name-only", "--no-renames", "--full-history",
                      "--diff-filter=A", f"origin/{base}..HEAD", "--", SESSION_LOG_DIR, cwd=str(root))
    if rc != 0:
        return None
    rows: list[str] = []
    for record in out.split("\x1e")[1:]:
        trailers, _sep, names = record.partition("\x1f")
        if value and value in (ln.strip() for ln in trailers.splitlines()):
            continue
        rows += [ln.strip().replace("\\", "/") for ln in names.splitlines()
                 if ln.strip().replace("\\", "/").startswith(SESSION_LOG_DIR)]
    return rows


def _second_push_message(how: str) -> str:
    return (f"{how}, and this lane's commits carry no Session Log row (no change to ESPALIER_MEMORY.md "
            f"and no new file under {SESSION_LOG_DIR}): /handoff writes the row and ships the lane once. "
            "To ship before it, pass --early \"<reason>\" to `open` (the handoff's row then becomes a "
            f"second push on this lane); past {ROW_DEBT_CAP} lanes shipped since this seat's newest Session Log "
            "row, --early is refused until a row is committed on the lane (the cap)")


def post_merge_reds(cwd: str | None = None) -> list[str]:
    """One line per check whose owned verdict over the last POST_MERGE_ROWS
    merged pull requests is red -- a check that is not required finishes after
    auto-merge has landed the lane and reports to nobody unless something
    reads it. The rule and the words are tools/cc/_post_merge.py's, the one
    home the banner's `Merged:` line and the board's `checks:` line read too:
    the merge the red has held since, the leg's finish, the merge it was green
    on, and a newer green that started before the red merge, printed beside
    it, never over it. No author filter, on purpose: the lines describe the
    base's state, which every merged pull request shapes whoever pushed it,
    so on a team repository a colleague's red is named too."""
    merged = _post_merge.read_merged(cwd, POST_MERGE_ROWS, gh=lambda args: _gh_json(*args, cwd=cwd))
    return _post_merge.lines(_post_merge.transitions(merged), oldest=_post_merge.oldest_merge(merged))


def base_red_run(base: str, cwd: str | None = None) -> dict | None:
    """The base branch's newest post-merge run on a push that reached a
    verdict, when that verdict is red: its row (``databaseId``, ``headSha``,
    ``conclusion``, ``url``), else None -- a green there, no verdict in the
    window, or a read gh could not make. The post-merge proof is of the merged
    combination, which no pull request's rollup carries: without the
    up-to-date rule, two lanes each green on its own base can red together,
    and this run is where that shows. A run still going, cancelled (by hand:
    no newer push cancels one), stale, skipped or neutral is no verdict, and
    the read walks back past it through the board's window to the newest run
    that reached one; a green there proves a superset of any older red."""
    runs = _gh_json("run", "list", "--workflow", POST_MERGE_WORKFLOW, "--branch", base, "--event", "push",
                    "--limit", str(POST_MERGE_RUN_WINDOW), "--json", "databaseId,status,conclusion,headSha,url",
                    cwd=cwd)
    if not isinstance(runs, list):
        return None
    for run_ in runs:
        if not isinstance(run_, dict) or str(run_.get("status") or "").lower() != "completed":
            continue
        conclusion = str(run_.get("conclusion") or "").upper()
        if conclusion == "SUCCESS":
            return None
        if conclusion not in _RUN_RED:
            continue  # cancelled, stale, skipped, neutral, action required: no verdict
        return run_
    return None


def _red_base_words(base: str, run_: dict) -> str:
    """The one line that names a red base -- the run, the merge it proved, its
    verdict and its URL -- which the refusals, the notes and the ruling open with."""
    return (f"{base} red after merge: {POST_MERGE_WORKFLOW} run {run_.get('databaseId')} on "
            f"{str(run_.get('headSha') or '')[:7]} concluded {str(run_.get('conclusion') or '').lower()} "
            f"({run_.get('url')}); read it before landing another lane on top")


def base_red_after_merge(base: str, cwd: str | None = None) -> str | None:
    """:func:`base_red_run`'s row as the line :func:`_red_base_words` prints,
    or None where the base is not red."""
    run_ = base_red_run(base, cwd=cwd)
    return None if run_ is None else _red_base_words(base, run_)


def _open_prs(cwd: str) -> list[dict] | None:
    """Every open pull request's number, branch, head, labels and auto-merge
    state, for the red-base refusal, the one-per-seat advisory and the
    row-debt read; None when gh cannot say (the first two fail open on it: the
    refusal still stands on the red read itself; the debt reads it as unread,
    since a row riding this seat's open pull request is read from its head)."""
    try:
        rows = _gh_json("pr", "list", "--state", "open", "--limit", "50", "--json",
                        "number,headRefName,headRefOid,labels,autoMergeRequest", cwd=cwd)
    except Refused:
        return None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else None


#: The flag that lands a lane on a red base by the dispatcher's ruling, on
#: `open` and `handoff` alike; the refusal names it, with the run id the
#: ruling must name.
BASE_RED_RULED_FLAG = "--base-red-ruled"
#: The ruling's words are the mail channel's (tools/cc/mail.py: the gridlock
#: marker the seat-day census counts a ruling by, root CLAUDE.md Core Rule 15;
#: the fixed head a fix-forward ruling opens with, the run id read from it
#: alone since the marker carries no direction; and how much of its text a
#: reader repeats), and so is the reader (``fix_forward_ruling``), so this
#: driver and the board's red line agree on what rules. The three words stay
#: here as literals because the channel is loaded on first use, never at
#: import, and the refusal names the head on a tree where no ruling was given
#: (tests/test_ship_driver.py holds each equal to the channel's; the census's
#: table and the dispatcher's brief are held to the marker the same way).
RULING_PREFIX = "gridlock:"
RULING_HEAD = RULING_PREFIX + " fix forward run "
RULING_TEXT_CHARS = 160


def red_base_ruling(root: Path, ack_id: str, run_id: str, *, branch: str = "") -> tuple[str, str | None, str]:
    """``(sender, problem, text)``: whether the ack ``ack_id`` on the mail
    channel's local refs rules the red post-merge run ``run_id`` a
    fix-forward for this lane. A red whose failing test is outside every
    suspect's diff and reproduces at the last green base with the moved
    dependency has no merge to revert, so the revert that is the default
    clears nothing (pytest 9.2.0, 2026-10-29: every seat held about eleven
    hours, and the fix landed by a hand-opened pull request). The rule is the
    channel's ``fix_forward_ruling``, the one reader the board's red line
    reads too: the dispatcher's ack on its own ref (``dispatcher`` in
    espalier.toml; any seat's where none is named; the ref is the sender,
    never the message's ``from``), opening with the fixed head
    :data:`RULING_HEAD` and the red run's id, naming the fix lane, which must
    be this one. This driver reads the channel for it, and ``problem`` says,
    by name, what does not hold: no channel beside this script, a dispatcher
    setting that cannot be used, a channel that cannot be read, and each
    refusal the reader names -- an id of another shape, no such ack on the
    local refs (the read is of the refs the last fetch left; `python
    tools/cc/mail.py inbox` fetches), a request or a note with that id, an
    ack on another seat's ref, an ack under another head, an ack whose head
    names another run, an ack naming no lane or another lane; None where the
    ruling holds. ``sender`` is the ref's machine when the ack was found, else
    ''; ``text`` the ack's text on one line when found, else ''."""
    mail = _mail_module()
    if mail is None:
        return "", "tools/cc/mail.py is not beside this script, so no ruling can be read", ""
    reader = getattr(mail, "fix_forward_ruling", None)
    id_shape = getattr(mail, "MESSAGE_ID_RE", None)
    if reader is None or id_shape is None:
        # An upgrade keeps an adopter's edited mail.py beside the new driver.
        return "", ("tools/cc/mail.py beside this script predates the ruling reader (upgrade it), so no ruling "
                    "can be read"), ""
    if not id_shape.match(ack_id):   # the shape first, before any read of the channel
        return "", (f"{ack_id} is not a message id: a ruling is named by its full id as /inbox prints it "
                    "(<stamp>-<machine>-<6 hex>)"), ""
    try:
        dispatcher, how = mail.dispatcher_setting(root)
        if dispatcher == mail.DISPATCHER_UNUSABLE:
            return "", f"the dispatcher setting cannot be used ({how}), so no ruling counts", ""
        by_machine, _skipped = mail.read_mail(root)
    except Exception as exc:  # noqa: BLE001 -- a channel that cannot be read rules nothing, said by name, never a traceback
        return "", f"the mail channel could not be read ({os_error_text(exc)}), so no ruling counts", ""
    return reader(by_machine, dispatcher, ack_id, run_id, branch=branch)


def _revert_lane_ruling_note(base: str, cwd: str, root: Path | None) -> None:
    """A `revert/` lane is let through with no ruling; where the base's red
    run was ruled a fix-forward, say so, since the revert then undoes a merge
    the ruling found blameless (the board's line says the same, and a seat
    acting on an older read of it claims the lane anyway). Advisory: a tree
    without the reader, a base that does not read red and a channel that
    cannot be read each say nothing or why, and the revert goes on."""
    mail = _mail_module()
    reader = getattr(mail, "fix_forward_rulings", None) if mail is not None else None
    if reader is None:
        return
    run_ = base_red_run(base, cwd=cwd)
    if run_ is None:
        return
    where = root if root is not None else Path(cwd)
    try:
        dispatcher, _how = mail.dispatcher_setting(where)
        by_machine, _skipped = mail.read_mail(where)
        rulings = reader(by_machine, dispatcher, str(run_.get("databaseId")))
    except Exception as exc:  # noqa: BLE001 -- the note is advisory: a channel that cannot be read says so, never a traceback
        _note(f"the base's red run was not checked for a ruling (the mail channel could not be read: "
              f"{os_error_text(exc)})")
        return
    if rulings:
        last = rulings[-1]
        _note(f"the base's red run {run_.get('databaseId')} was ruled a fix-forward by {last.get('id')} for "
              f"{last.get('lane')}: this revert undoes a merge that ruling found blameless, and is let through "
              "as a revert/ lane is; make sure it is the dispatcher's call")


def red_base_verdict(base: str, branch: str, prs: list[dict], cwd: str, *, ruled: str | None = None,
                     root: Path | None = None) -> tuple[str | None, str | None]:
    """``(refusal, ruling)``: why `open` must not arm this lane now, or the
    line that says the dispatcher's ruling ``ruled`` (an ack id, given as
    :data:`BASE_RED_RULED_FLAG`) lets it land on the red base, with the
    ruling's text head. Both None on a base that does not read red (a flag
    given there is noted as not needed) and on a `revert/` lane, which the
    revert-first rule lets through without a flag (one given is noted as not
    read). Nothing else lands on a red base: the refusal names the revert,
    the re-run that clears a flake, the ruling with the rule that earns it
    and the run id the ack must name, and each pull request whose armed
    auto-merge would land on the red base with the command that disarms it;
    with the flag given and the ruling not holding, it says why first."""
    if branch.startswith("revert/"):
        if ruled:
            _note(f"a revert/ lane needs no ruling, so {BASE_RED_RULED_FLAG} {ruled} was not read")
        _revert_lane_ruling_note(base, cwd, root)
        return None, None
    run_ = base_red_run(base, cwd=cwd)
    if run_ is None:
        if ruled:
            _note(f"the base reads as not red (green, no verdict in the window, or gh could not say), so "
                  f"{BASE_RED_RULED_FLAG} {ruled} was not needed")
        return None, None
    red = _red_base_words(base, run_)
    run_id = str(run_.get("databaseId"))
    armed = [str(r.get("number")) for r in prs if r.get("autoMergeRequest") and str(r.get("headRefName")) != branch]
    armed_words = (("; armed now, and landing on the red base unless disarmed: "
                    + ", ".join(f"#{n} (gh pr merge --disable-auto {n})" for n in armed)) if armed else "")
    if ruled:
        sender, problem, text = red_base_ruling(root if root is not None else Path(cwd), ruled, run_id,
                                                branch=branch)
        if problem is None:
            return None, (f"{red} -- let through by the dispatcher's ruling {ruled} ({sender}'s gridlock ack "
                          f"naming run {run_id}: {text[:RULING_TEXT_CHARS]})")
        return (f"{red}. {BASE_RED_RULED_FLAG} {ruled}: {problem}. Nothing lands on a red base but the revert "
                "(from a revert/ lane, which `open` lets through), a re-run where the red was a flake, or a "
                "ruling that holds" + armed_words), None
    return (f"{red}. Nothing lands on a red base but the revert (from a revert/ lane, which `open` lets "
            "through), a re-run where the red was a flake, or, where the failing test is outside every "
            "suspect's diff and reproduces at the last green base, the fix landed forward on the "
            f"dispatcher's ruling: {BASE_RED_RULED_FLAG} <ack id> on `open` or `handoff`, the ack opening "
            f"`{RULING_HEAD}{run_id}` with --lane {branch}" + armed_words), None


def seat_open_prs(root: Path, branch: str, prs: list[dict]) -> tuple[str, list[str]]:
    """``(seat, ["#n (lane)", ...])``: this seat's open pull requests other
    than ``branch``'s, by the seat whose latest claim or release names each
    lane (``mail.lane_seats``, the board's own attribution). Every seat may
    push as one GitHub account, so the author cannot tell seats apart; the
    mail can. ``("", [])`` where the box is unnamed or the channel absent; a
    failed read, of the mail or of the box's name, is said and never stops
    the push."""
    if not any(str(r.get("headRefName") or "") != branch for r in prs):
        return "", []   # no other open pull request: nothing to attribute, no mail read
    try:
        mail = _mail_module()
        if mail is None:
            return "", []
        machine, how = mail.machine_setting(root)
        if not machine:
            unread = getattr(mail, "MACHINE_UNREAD", None)  # a channel module from before the phrase has none
            if unread and str(how).startswith(unread):
                _note(f"this seat's machine name could not be read ({how}), so its other open pull requests "
                      "were not checked (one open pull request per seat)")
            return "", []
        by_machine, _ = mail.read_mail(root)
        seats = mail.lane_seats(by_machine)
    except Exception as exc:  # noqa: BLE001 -- fail-open with voice: an advisory that cannot read says so
        _note(f"could not read which open pull requests are this seat's ({os_error_text(exc)})")
        return "", []
    mine = [f"#{r.get('number')} ({r.get('headRefName')})" for r in prs
            if str(r.get("headRefName") or "") != branch and _lane_seat(r, seats) == machine]
    return machine, mine


def _lane_seat(pr: dict, seat_of: dict[str, str]) -> str:
    """Whose lane a pull request is: the loader's ``lane_seat`` (the seat its
    claim names, else the seat its ``seat:`` label names, DEF-4044), or the
    claim alone where the kept loader predates the reader."""
    fragments = _fragments_module()
    reader = getattr(fragments, "lane_seat", None) if fragments is not None else None
    if reader is None:
        return seat_of.get(str(pr.get("headRefName") or ""), "")
    return str(reader(pr, seat_of) or "")


#: How many lanes a seat may ship past its newest Session Log row before
#: `open --early` refuses (pre-registered 2026-10-18 with the records line and
#: kept at its measurement, 2026-10-23: six seat-days with merges and no row
#: over 10-16 and 10-17, 60% of early ships followed by a row against the 80%
#: line; the refusal switched on 2026-10-30, after six days of board lines).
ROW_DEBT_CAP = 3


def _row_debt_reading(root: Path, base: str, prs: list[dict] | None = None) -> dict | None:
    """What the row-debt refusal reads, or None where git, gh or the mail
    channel cannot answer: ``{"machine", "count", "since", "where", "newest"}``
    -- this seat's name, its merged lanes since its newest Session Log row,
    that row's date ('' for none) and where it sits (one of the loader's
    ``ROW_PLACES``: on the base, parked on the records ref, riding one of the
    seat's own open pull requests, or pruned from the base and read from its
    history; '' for none), every seat's ``(date, where)`` for the words (a
    worktree seat renamed since its last row finds it under the old name) and
    the seats the mail channel names (``seats``).
    No verdict is never a refusal on a guess (the rule ``lane_carries_memory_row``
    keeps). Lanes are the merged pull requests the seat's claim or seat label
    names (``_record_fragments.lane_seat``), their merge day read in this
    clock's zone as the fragment names are; the rows are read by name alone,
    never from the working tree a seat can edit: the fragments on
    ``origin/<base>``, those parked on the records refs (``mail.pending``: a
    seat that wrote its row and parked it is not in debt, and the early arm
    runs before the fold that brings it in), those on the heads of this seat's
    open pull requests among ``prs`` (``_open_prs``: written, waiting for a
    merge) and those the fold's prunes deleted from the base, read from its
    history by the fold trailer (``pruned_rows_argv``, ``pruned_rows_from``:
    #354's prune took two seats' newest rows off the tree, 2026-10-30; a
    deletion by any other commit still counts as debt). The count is
    ``_record_fragments.lanes_since_row``, the board's ``records:`` line's own,
    through the one merged read (``_post_merge.read_merged``, the lane
    fields)."""
    # The local reads first, every one under the guard: a sibling that cannot
    # load or predates a name read here (an older kept loader's AttributeError),
    # a git that raised (the runner's Refused on a timeout or a missing git),
    # the channel's named stop. Unread, never a count, never a refusal.
    try:
        mail, fragments = _mail_module(), _fragments_module()
        if mail is None or fragments is None:
            return None
        machine, _how = mail.machine_setting(root)  # unread-name: ok both an unread name and no name read as None, no verdict
        if not machine:
            return None
        directory = fragments.SESSION_LOG_DIR
        rc, names, _ = _git("ls-tree", "--name-only", f"origin/{base}", "--", directory + "/", cwd=str(root))
        if rc != 0:
            return None
        rc, shallow, _ = _git(*fragments.SHALLOW_ARGV, cwd=str(root))
        if rc != 0 or shallow.strip() == "true":
            return None   # a cut history reads no pruned names: unread, never none
        rc, deleted, _ = _git(*fragments.pruned_rows_argv(f"origin/{base}"), cwd=str(root))
        if rc != 0:
            return None
        pruned = fragments.pruned_rows_from(deleted)
        parked_rows = mail.pending(root, directory, [f"origin/{base}"], trailer=fragments.FOLD_TRAILER)
        parked = [path for _machine, path, _ref in parked_rows]
        by_machine, _skipped = mail.read_mail(root)
        seat_of = mail.lane_seats(by_machine)
        heads = list(dict.fromkeys(str(pr.get("headRefOid") or "") for pr in (prs or [])
                                   if isinstance(pr, dict) and pr.get("headRefOid")
                                   and fragments.lane_seat(pr, seat_of) == machine))
        riding: list[str] = []
        if heads:
            # The seat's other open pull requests' heads, by object id (objects
            # only, no ref), then their Session Log names: a row riding one is
            # written and waits for a merge (the first lane's failure-mode review).
            rc, _out, _err = _git("fetch", "origin", *heads, "--quiet", cwd=str(root))
            if rc != 0:
                return None
            listed: list[tuple[str, list[str]]] = []
            for head in heads:
                rc, out, _ = _git("ls-tree", "--name-only", head, "--", directory + "/", cwd=str(root))
                if rc != 0:
                    return None
                listed.append((machine, out.split()))
            riding = fragments.riding_rows(listed)   # this seat's own rows on its heads, never the base's copies
        newest = fragments.newest_rows(names.split(), parked, riding=riding, pruned=pruned)
        since, where = newest.get(machine, ("", ""))
        window, fields, count = fragments.ROW_DEBT_WINDOW, _post_merge.LANE_FIELDS, fragments.lanes_since_row
        # The seats the records know: a mail ref, a records ref or a claimed
        # lane (the legacy pseudo-seat of the first fragments has none).
        seats = sorted(set(by_machine) | {str(m) for m, _p, _r in parked_rows} | set(seat_of.values()))
    except Exception:  # noqa: BLE001 -- see above: every local read's failure is one answer, None
        return None
    failed: list[str] = []

    def gh(args: list[str]) -> object:
        try:
            data = _gh_json(*args, cwd=str(root))
        except Refused as exc:
            failed.append(str(exc))
            return None
        if not isinstance(data, list):
            failed.append("gh pr list answered no list")   # prs() would read it as no merges
            return None
        return data

    merged = _post_merge.read_merged(str(root), window, gh=gh, fields=fields)
    if failed:
        return None
    return {"machine": machine, "count": count(merged, seat_of, machine, since), "since": since, "where": where,
            "newest": newest, "seats": seats}


def seat_row_debt(root: Path, base: str, prs: list[dict] | None = None) -> tuple[int, str, str] | None:
    """``(merged lanes since this seat's newest Session Log row, that row's
    date or '', where that row sits: 'base', 'parked', 'open', 'pruned' or
    '')``, or None where git, gh or the mail channel cannot answer -- the
    row-debt reading (``_row_debt_reading``) in the shape the first lane's
    readers took, the third element a place since the second lane (it was
    "parked", a bool). ``prs``: the open pull requests, whose heads this
    seat's lanes' rows are read from."""
    reading = _row_debt_reading(root, base, prs)
    if reading is None:
        return None
    return reading["count"], reading["since"], reading["where"]


def _row_place_words(since: str, where: str, base: str) -> str:
    if not since:
        return "none"
    tail = {"parked": ", parked on this seat's records ref until the next fold",
            "open": ", riding one of this seat's open pull requests",
            "pruned": f", pruned from origin/{base} since and read from its history"}.get(where, "")
    return since + tail


def _refuse_on_row_debt(root: Path, base: str, prs: list[dict] | None) -> None:
    """The early arm's one refusal that --early does not pass (the records
    line's second lane, 2026-10-30): a seat that has shipped ``ROW_DEBT_CAP`` or more lanes since
    its newest Session Log row is refused until a row is committed on this
    lane, which ``lane_carries_memory_row`` then reads as carried and the arm
    is not asked. The base and the records refs are fetched first: the early
    arm runs before ``open``'s base fetch and before the fold's records fetch,
    so a row merged forty minutes ago was not in the local base (the first
    lane's failure-mode review). A fetch, a read or a channel that cannot
    answer is said and --early is taken as given: no verdict is never a
    refusal on a guess."""
    unread = ""
    try:
        rc, _out, err = _git("fetch", "origin", base, "--quiet", cwd=str(root))
    except Refused as exc:   # the runner's timeout: unread, never a refusal
        rc, err = 1, str(exc)
    if rc != 0:
        unread = f"origin/{base} could not be fetched ({err.strip()[:120] or 'no reason printed'})"
    else:
        try:
            mail = _mail_module()
            if mail is None:
                ok, problem = False, "tools/cc/mail.py is not beside this script"
            else:
                machine, how = mail.machine_setting(root)
                if machine:
                    ok, problem = mail.fetch_records(root)
                elif str(how).startswith(getattr(mail, "MACHINE_UNREAD", "\0")):
                    ok, problem = False, ""   # a name read that failed is not an unnamed clone
                    unread = f"this clone's seat name could not be read ({how}), so no seat's rows are its own"
                else:
                    ok, problem = False, ""
                    unread = "this clone names no machine (git config espalier.machine), so no seat's rows are its own"
        except Exception as exc:  # noqa: BLE001 -- a channel that raised is unread, said below
            ok, problem = False, os_error_text(exc)
        if not ok and not unread:
            unread = f"the records refs could not be fetched ({problem})"
    if not unread and prs is None:
        unread = "the open pull requests could not be read (gh pr list answered no JSON)"
    reading = None if unread else _row_debt_reading(root, base, prs)
    if reading is None:
        _note(f"this seat's Session Log debt is unread ({unread or 'git, gh or the mail channel did not answer'}), "
              "so --early is taken as given")
        return
    count, since, where = int(reading["count"]), str(reading["since"]), str(reading["where"])
    if count < ROW_DEBT_CAP:
        return
    # The seats the mail channel knows (a records ref's name is a seat's; the
    # legacy pseudo-seat of the first fragments is not one).
    others = ", ".join(f"{seat} {date}" for seat, (date, _where) in sorted(reading["newest"].items())
                       if seat != reading["machine"] and seat in reading.get("seats", [seat]))
    raise Refused(f"this seat ({reading['machine']}) has {count} lane{'s' if count != 1 else ''} merged on the days "
                  f"after its newest Session Log row ({_row_place_words(since, where, base)}); the cap is {ROW_DEBT_CAP}. "
                  "Write the row on this lane (python tools/cc/_record_fragments.py new session-log names the file) "
                  "and commit it, and this question is not asked; --early does not pass this one. The rows were "
                  f"read under this clone's seat name, {reading['machine']} (git config espalier.machine); the other "
                  f"seats' newest rows: {others or 'none'} (a worktree seat renamed since its last row finds it "
                  "under the old name)")


def _seat_label(root: Path) -> str:
    """The ``seat:<machine>`` label ``open`` stamps on the pull request so a
    lane no claim names is still this seat's (``_record_fragments.lane_seat``
    reads it back from the merged listing; DEF-4044: a lane shipped without a
    claim was nobody's, and the row-debt cap was passed by not claiming). ''
    where the box is unnamed, the channel or the loader is absent or the name
    could not be read: the label is a fallback attribution, and an unnamed
    box is told so by the claims it cannot send, not here."""
    try:
        mail, fragments = _mail_module(), _fragments_module()
        if mail is None or fragments is None:
            return ""
        machine, how = mail.machine_setting(root)
        if not machine:
            if str(how).startswith(getattr(mail, "MACHINE_UNREAD", "\0")):
                _note(f"this clone's seat name could not be read ({how}), so the pull request carries no seat label")
            return ""
        return f"{fragments.SEAT_LABEL_PREFIX}{machine}"
    except Exception:  # noqa: BLE001 -- a channel or loader that raised stamps nothing; the claim still attributes
        return ""


def _ensure_seat_label(root: Path, label: str) -> str:
    """The repository's copy of ``label``, created or kept (``gh label create
    --force`` updates one that exists), before ``gh pr create --label`` names
    it: a label the repository does not hold fails the create whole. '' with a
    note when it could not be made, so the pull request opens without it and
    the lane is attributed by its claim alone."""
    if not label:
        return ""
    try:
        rc, _out, err = _gh("label", "create", label, "--force", "--color", "ededed", "--description",
                            f"lanes the seat {label.split(':', 1)[-1]} shipped (ship.py open stamps it)", cwd=str(root))
    except Refused as exc:   # the runner's timeout: the pull request still opens, without the label
        rc, err = 1, str(exc)
    if rc != 0:
        _note(f"the seat label {label} could not be created ({err.strip()[:120] or 'no reason printed'}); the pull "
              "request opens without it, so the Session Log debt attributes this lane by its claim alone")
        return ""
    return label


def stale_base_line(root: Path, base: str, pr: dict) -> str:
    """The stale-base advisory for an open pull request, or "" when its green
    stands: the up-to-date rule is on (GitHub holds a stale lane itself), the
    base has not moved since the CI ran, or it moved away from this pull
    request's files and their imports (``_merge_rules.stale_base``). A read
    that fails is said."""
    head = str(pr.get("headRefOid") or "")
    branch = str(pr.get("headRefName") or "") or current_branch()
    try:
        rc, out, _ = _gh("api", _merge_rules.protection_endpoint(base), cwd=str(root), timeout=15.0)
        if _merge_rules.strict(rc, out):
            return ""
        _git("fetch", "origin", base, branch, "--quiet", cwd=str(root))
        runs = _gh_json("run", "list", "--branch", branch, "--event", "pull_request", "--limit", "100",
                        "--json", "workflowName,createdAt,headSha,conclusion", cwd=str(root))
        rc, diff, err = _git("diff", "--name-only", "--no-renames", f"origin/{base}...{head}", cwd=str(root))
        if rc != 0:
            return f"stale-base check not read: git diff origin/{base}...{head[:7]} failed ({err.strip()[:120]})"
        result = _merge_rules.stale_base(root, base_ref=f"origin/{base}",
                                         tested_when=_merge_rules.tested_at(runs, head),
                                         pr_paths=[ln for ln in diff.splitlines() if ln.strip()],
                                         pr_rev=head, run_=RUN)
    except Refused as exc:
        return f"stale-base check not read: {exc}"
    return _merge_rules.stale_line(result, base, pr.get("number"))


def _refuse_a_dirty_tree(root: Path) -> None:
    rc, _, _ = _git("rev-parse", "-q", "--verify", "MERGE_HEAD", cwd=str(root))
    if rc == 0:
        # A merge in progress reads as a dirty tree, and "/commit first" would
        # commit its conflict markers: name the two ways out instead.
        raise Refused("a merge is in progress (MERGE_HEAD exists): finish it (resolve, git commit) or "
                      "abandon it (git merge --abort) first")
    rc, out, err = _git("status", "--porcelain", "-uno", cwd=str(root))
    if rc != 0:
        raise Refused(f"git status failed: {err.strip()}")
    if out.strip():
        raise Refused("the tracked tree is dirty: /commit first (ship moves commits, never a dirty tree)")


def record_file_markers(root: Path) -> list[str]:
    """The harness guard's record-file conflict-marker findings for the
    checkout at ``root`` (``path:line: head``), read through the guard itself,
    loaded BY PATH from the tree the way ``guard_predicate`` loads it: the same
    oracle the pull request's required cells run, so a lane the gate would
    refuse in every one of them (its check is unconditional; no marker waives
    it) is stopped here, before the push. Empty, with the reason said, when
    the tree has no guard, the guard predates the check, or it will not load:
    a pre-flight that could not run says so and leaves the question to the
    gate. Loaded fresh each call, never from ``sys.modules``: one call's tree
    is not the next call's."""
    guard = root / "tools" / "cc" / "ci_guard.py"
    if not guard.is_file():
        return []
    import importlib.util
    spec = importlib.util.spec_from_file_location("_ship_ci_guard", guard)
    if spec is None or spec.loader is None:
        _note("the harness guard could not be loaded; the record-file marker check is the gate's")
        return []
    module = importlib.util.module_from_spec(spec)
    sys.modules["_ship_ci_guard"] = module  # registered before exec: a dataclass in the module needs it (3.14)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 -- fail-open with voice: a pre-flight that cannot run says so; the gate still refuses
        _note(f"the harness guard could not be loaded ({os_error_text(exc)}); the record-file marker check is the gate's")
        return []
    check = getattr(module, "check_record_file_markers", None)
    if not callable(check):
        return []  # a guard from before the check: nothing to read here, the gate decides
    try:
        findings = check(cwd=str(root))
    except Exception as exc:  # noqa: BLE001 -- fail-open with voice: the gate still refuses
        _note(f"the harness guard's record-file marker check failed ({os_error_text(exc)}); the gate decides")
        return []
    return [str(f) for f in findings or []]


#: The mail channel (``tools/cc/mail.py``), loaded by path on first use and
#: never at import: a tree without the sibling ships as it did before the
#: channel. Tests stand a channel in here.
_MAIL = None


def _mail_module():
    global _MAIL
    if _MAIL is None:
        path = Path(__file__).resolve().parent / "mail.py"
        if not path.is_file():
            return None
        import importlib.util
        spec = importlib.util.spec_from_file_location("_ship_mail", path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_ship_mail"] = module  # registered before exec (3.14)
        spec.loader.exec_module(module)
        _MAIL = module
    return _MAIL


#: The board (``tools/cc/board.py``), loaded by path on first use and never at
#: import, as the mail channel is: its overlap notice is read after a push
#: lands, and a tree without it ships as before. Tests stand a board in here.
_BOARD = None


def _board_module():
    global _BOARD
    if _BOARD is None:
        path = Path(__file__).resolve().parent / "board.py"
        if not path.is_file():
            return None
        import importlib.util
        spec = importlib.util.spec_from_file_location("_ship_board", path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_ship_board"] = module  # registered before exec (3.14)
        spec.loader.exec_module(module)
        _BOARD = module
    return _BOARD


def _overlap_notice(root: Path, branch: str, base: str, number: object, head: str) -> None:
    """After a push lands: the lane's overlaps with every live claim of
    another seat and every open pull request, in the board's words. Advice
    only: nothing else here changes, and the second to merge still runs
    catch-up. A read that fails is one note, never a refusal of a push that
    landed."""
    try:
        board = _board_module()
        if board is None:
            return
        for line in board.lane_overlap_lines(root, base, branch, number, head):
            _say(line)
    except Exception as exc:  # noqa: BLE001 -- fail-open with voice: the lane is pushed; the notice is advice
        _note(f"the overlap notice was not read ({os_error_text(exc)}); the board (tools/cc/board.py) reads it")


#: The record loader (``tools/cc/_record_fragments.py``), loaded by path on first
#: use: the Session Log's directory, cap, prune and fold trailer.
_FRAGMENTS = None


def _fragments_module():
    global _FRAGMENTS
    if _FRAGMENTS is None:
        path = Path(__file__).resolve().parent / "_record_fragments.py"
        if not path.is_file():
            return None
        import importlib.util
        spec = importlib.util.spec_from_file_location("_ship_record_fragments", path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_ship_record_fragments"] = module  # registered before exec (3.14)
        spec.loader.exec_module(module)
        _FRAGMENTS = module
    return _FRAGMENTS


def _fold_session_log(root: Path, base: str, *, keep: int | None = None, slack: int | None = None,
                      dry_run: bool = False) -> tuple[int, int]:
    """The only place the Session Log is pruned, run before a lane's push (and
    by the ``fold`` verb, for a push ``open`` does not make): bring every row
    parked on the records refs that no history has added (``mail.pending``
    against ``origin/<base>`` and HEAD) into the lane, then, only when the
    fragments run past the cap plus ``SESSION_LOG_SLACK``, prune back to the
    cap, as two commits carrying ``FOLD_TRAILER``. Two commits, so a parked row
    older than the kept window enters history once and is never pending again.
    Until 2026-10-16 each lane held the cap in its own tree, at the write and at
    the handoff, and paid a prune commit for it (DEF-5007); two lanes off one
    base can still land a row or two past the slack's edge, and the next fold
    prunes. ``(folded, pruned)``. Never a refusal, and never a half-done tree: a
    missing channel or loader, uncommitted changes under the directory, records
    git cannot read, or a step that fails is said, the tree is put back as it
    was, and the lane's push goes ahead; the next push's fold heals the count."""
    mail, fragments = _mail_module(), _fragments_module()
    if mail is None or fragments is None:
        _note("the Session Log fold is skipped: tools/cc/mail.py or tools/cc/_record_fragments.py is not "
              "beside this script")
        return 0, 0
    directory = fragments.SESSION_LOG_DIR
    cap = fragments.SESSION_LOG_CAP if keep is None else keep
    over = getattr(fragments, "SESSION_LOG_SLACK", 0) if slack is None else slack
    rc, dirty, _ = _git("status", "--porcelain", "--untracked-files=all", "--", directory, cwd=str(root))
    if rc != 0 or dirty.strip():
        listed = ", ".join(ln[3:].strip() for ln in dirty.splitlines() if ln.strip())[:300]
        _note(f"the Session Log fold is skipped: {directory}/ has uncommitted changes ({listed or 'unread'}). "
              "Commit this session's own row; a row an earlier fold checked out and could not commit is "
              "another seat's: `git restore --staged -- <path>`, then delete the file. The next push folds")
        return 0, 0
    ok, problem = mail.fetch_records(root)
    if not ok:
        _note(f"the records refs were not fetched ({problem}): folding what this clone last fetched")
    trailer = fragments.FOLD_TRAILER
    try:
        # With the trailer, a row a revert took off the base is pending again
        # (DEF-4045); the prune's deletion, which carries it, stays final.
        rows = mail.pending(root, directory, [f"origin/{base}", "HEAD"], trailer=trailer)
    except mail.Unresolvable as exc:
        _note(f"the Session Log fold is skipped: {exc}")
        return 0, 0
    except TypeError as exc:   # a kept, older tools/cc/mail.py without the trailer read: never a refusal
        _note(f"the Session Log fold is skipped: tools/cc/mail.py predates the fold-trailer read ({exc}); "
              "upgrade it beside this script")
        return 0, 0
    if dry_run:
        if rows:
            _say(f"dry-run: fold {len(rows)} parked Session Log row(s) into the lane, then prune to {cap} "
                 f"once past {cap + over}")
        return 0, 0
    if rows:
        paths = [path for _machine, path, _ref in rows]
        failed = ""
        for _machine, path, ref in rows:
            rc, _out, err = _git("checkout", ref, "--", path, cwd=str(root))
            if rc != 0:
                failed = f"could not take {path} from {ref}: {err.strip()[:200]}"
                break
        if not failed:
            subject = f"chore(records): fold {len(rows)} parked Session Log row{'s' if len(rows) != 1 else ''}"
            message = subject + "\n\n" + "\n".join(f"- {path} ({machine})" for machine, path, _ref in rows) \
                + f"\n\n{trailer}\n"
            rc, _out, err = _git("commit", "--quiet", "-m", message, "--", *paths, cwd=str(root))
            if rc != 0:
                failed = f"its commit failed: {err.strip()[:200]}"
        if failed:
            # Another seat's rows never stay staged here: committed by hand
            # without the trailer, they would read as this lane's own.
            _git("reset", "-q", "--", *paths, cwd=str(root))
            for path in paths:
                try:
                    (root / path).unlink()
                except OSError:
                    pass
            _note(f"the Session Log fold did not run ({failed}); the tree is as it was, and the next push folds")
            return 0, 0
        _say(f"folded {len(rows)} parked Session Log row(s) into the lane: {', '.join(paths)}")
    named, _skipped = fragments.session_log_fragments(root)
    pruned = 0
    if len(named) > cap + over:
        try:
            left = fragments.prune_session_log(root, keep=cap)
        except OSError as exc:
            left, failed = [], f"the prune failed: {os_error_text(exc)}"
        else:
            failed = ""
        pruned = len(left)
        if pruned and not failed:
            for argv in (("add", "-A", "--", directory),
                         ("commit", "--quiet", "-m",
                          f"chore(records): prune the Session Log to its cap of {cap}\n\n{trailer}\n",
                          "--", directory)):
                rc, _out, err = _git(*argv, cwd=str(root))
                if rc != 0:
                    failed = f"the prune's commit failed: {err.strip()[:200]}"
                    break
        if failed:
            _git("reset", "-q", "--", directory, cwd=str(root))
            _git("checkout", "-q", "HEAD", "--", directory, cwd=str(root))
            _note(f"the Session Log prune did not run ({failed}); the fragments are as they were (the local "
                  f"archive, {fragments.ARCHIVE}, may hold their rows twice), and the next push prunes")
            return len(rows), 0
        if pruned:
            _say(f"pruned {pruned} Session Log row(s) back to the cap of {cap}, past {cap + over} "
                 f"(archived to {fragments.ARCHIVE})")
    return len(rows), pruned


def fold(dry_run: bool = False) -> int:
    """The fold on its own, for a push ``open`` and the handoff do not make: a
    repository whose default branch takes direct pushes runs it before its
    ``git push`` (/handoff's direct-push step), so its Session Log is kept by
    the same writer, at the same moment, as a pull-request tree's."""
    root = repo_root()
    base = default_branch()
    _git("fetch", "origin", base, "--quiet", cwd=str(root))
    folded, pruned = _fold_session_log(root, base, dry_run=dry_run)
    if not dry_run and not (folded or pruned):
        _say("nothing to fold: no parked row is pending and the Session Log is within its slack")
    return 0


def _park_the_row(root: Path, base: str, *, dry_run: bool = False) -> bool:
    """A handoff-only lane -- no open pull request, and nothing in its diff with
    ``origin/<base>`` but Session Log rows -- parks the rows it added on this
    seat's records ref (``mail.park``) instead of opening a pull request for
    them alone: seven such pull requests in two days before this (DEF-5007).
    Only rows added: a lane that edits or renames a row keeps today's path, so
    the change reaches a pull request (a park carries additions alone). The
    blob parked is the committed one (``HEAD:<path>``). Once every row is parked
    the branch moves back to its merge base with the base (``reset --keep``):
    the commits held nothing but those rows, now on origin's records ref, and a
    commit left ahead held the next SessionStart's catch-up on this lane and
    passed the --early question as a row of this lane's (both reviews). The
    dropped head is printed. True when parked. Any other lane, a seat with no
    name or one git could not read, or a park origin refused, keeps today's path
    and says why."""
    _git("fetch", "origin", base, "--quiet", cwd=str(root))
    rc, out, _ = _git("diff", "--name-status", "--no-renames", f"origin/{base}...HEAD", cwd=str(root))
    if rc != 0 or not out.strip():
        return False
    entries = [ln.split("\t", 1) for ln in out.splitlines() if ln.strip()]
    if any(len(e) != 2 or e[0].strip() != "A" or not e[1].replace("\\", "/").startswith(SESSION_LOG_DIR)
           for e in entries):
        return False
    added = [e[1].replace("\\", "/") for e in entries]
    mail = _mail_module()
    if mail is None:
        _note("tools/cc/mail.py is not beside this script, so the row is not parked: opening a pull request "
              "for it, as before")
        return False
    if dry_run:
        _say(f"dry-run: park {', '.join(added)} on this seat's records ref and move this branch back to its "
             f"merge base with origin/{base}; no pull request")
        return True
    fragments = _fragments_module()
    trailer = getattr(fragments, "FOLD_TRAILER", "") if fragments is not None else ""
    try:
        for rel in added:
            try:
                # The pending rule's drop (a reverted fold's row stays on the ref, DEF-4045).
                mail.park(root, rel, None, f"origin/{base}", from_rev="HEAD", say=_say, trailer=trailer)
            except TypeError:   # a kept, older channel without the trailer: the first rule
                mail.park(root, rel, None, f"origin/{base}", from_rev="HEAD", say=_say)
    except (mail.Unresolvable, OSError) as exc:
        _note(f"the row was not parked ({os_error_text(exc)}): opening a pull request for it, as before")
        return False
    head = _git("rev-parse", "HEAD", cwd=str(root))[1].strip()
    rc, merge_base, _ = _git("merge-base", f"origin/{base}", "HEAD", cwd=str(root))
    moved = rc == 0 and bool(merge_base.strip()) and \
        _git("reset", "--keep", "--quiet", merge_base.strip(), cwd=str(root))[0] == 0
    _say(f"No pull request opened: this lane carries only its Session Log row, now parked on this seat's "
         f"records ref. The next lane's push, any seat's, folds it into {base}; until then the banner's recent "
         f"rows, which read the tree, show it to no seat, this one's next session included.")
    if moved:
        _say(f"This branch moved back to {merge_base.strip()[:7]}, where {base} holds it; the row's commit, "
             f"{head[:7]}, is on the records ref (and in this checkout's reflog).")
    else:
        _note(f"this branch could not be moved back to its merge base with origin/{base}: the row's commit "
              f"{head[:7]} stays ahead, so SessionStart will not catch this checkout up until you move it "
              f"(`git reset --keep $(git merge-base origin/{base} HEAD)`)")
    return True


# ------------------------------------------------------------- the own-clear --

#: The own-clear marker under the state directory: the handoff's last act arms
#: it; the own-clear mod (``tools/cc/mods/own-clear``, loaded by ``seat.py
#: launch``) reads it at the turn's end to run the real /clear, then consumes
#: it on the clear's SessionStart and re-primes the window with its brief.
#: Keyed by the session id a Claude Code session exports to its tool shells,
#: so a marker another session left never clears a window;
#: tests/test_state_file_flag_parity.py lists the file.
STATE_DIR = ".espalier-state"
OWN_CLEAR_MARKER = "own_clear.json"
SESSION_ID_ENV = "CLAUDE_CODE_SESSION_ID"

#: The seat driver (``tools/cc/seat.py``), loaded by path on first use and
#: never at import, as the mail channel is: it composes the re-prime brief.
_SEAT = None


def _seat_module():
    global _SEAT
    if _SEAT is None:
        path = Path(__file__).resolve().parent / "seat.py"
        if not path.is_file():
            return None
        import importlib.util
        spec = importlib.util.spec_from_file_location("_ship_seat", path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_ship_seat"] = module  # registered before exec (3.14)
        spec.loader.exec_module(module)
        _SEAT = module
    return _SEAT


def _write_own_clear(root: Path, marker: dict) -> None:
    """The marker written whole and renamed into place: ASCII JSON ending in
    a newline, so the mod reads it with nothing beyond a JSON parse. The
    hooks' atomic writer (a tempfile beside the target, then os.replace),
    loaded by path as the wiring note's reader is: a mod reads the marker at
    a turn's end and must never see a torn one. A tree whose hooks utilities
    are not beside this script (a fixture copying a subset) writes it plain."""
    state_dir = root / STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    target = state_dir / OWN_CLEAR_MARKER
    text = json.dumps(marker, ensure_ascii=True, indent=2) + "\n"
    loader = getattr(_paths, "hooks_module", None)
    writer = getattr(loader("_hook_utils"), "atomic_write_text", None) if loader else None
    if writer is not None:
        writer(target, text)
    else:
        target.write_text(text, encoding="utf-8")


def arm_own_clear(root: Path, *, session_id: str, head: str, seat: str | None, role: str | None,
                  brief: str | None, landed: bool = True, outcome: str | None = None) -> str:
    """Write the marker for ``session_id`` (state ``armed``) whole, rename it
    into place, and return the one line the handoff says. ASCII JSON ending in
    a newline, so the mod reads it with nothing beyond a JSON parse; a second
    arm replaces the first. ``landed`` and ``outcome`` are the record of how
    the handoff ended (DEF-4057): True and None for a push that landed; False
    and the refusal for a lane held here by a red base; True and the refusal
    for a step that refused after the push landed; True and the reason for an
    arm by hand. The mod reads neither: the brief carries what the next window
    must do, and the marker on disk outlives the window that printed it."""
    marker = {
        "state": "armed", "session_id": session_id, "head": head, "seat": seat, "role": role,
        "brief": brief, "landed": landed, "outcome": outcome,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_own_clear(root, marker)
    who = f"seat {seat}, {role}" if seat and role else "no seat name, no brief"
    return (f"own-clear armed for session {session_id} ({who}): in a window seat.py launch started, the "
            "own-clear mod clears it at this turn's end and re-primes it")


def _reprime_brief(root: Path) -> tuple[str | None, str | None, str | None, str]:
    """``(seat, role, brief, how)``: the seat this checkout answers to (the
    mail channel's name) and the brief seat.py composes for it with its loop
    line replaced (``seat.reprime_text``), or ``None``s and the reason: the
    seat is unnamed, mail.py or seat.py is not beside this script, or the
    brief refuses (an unusable dispatcher setting). Never raises: the handoff
    has run to its end, and a marker with no brief still clears the window."""
    mail = _mail_module()
    if mail is None:
        return None, None, None, "tools/cc/mail.py is not beside this script"
    try:
        # unread-name: ok unset and unread alike arm a marker with no brief, and `how` rides the handoff's line
        name, how = mail.machine_setting(root)
    except Exception as exc:  # noqa: BLE001 -- fail-open with voice: the reason rides the handoff's line
        return None, None, None, f"the seat's name could not be read ({os_error_text(exc)})"
    if name is None:
        return None, None, None, how
    try:
        seat_driver = _seat_module()   # inside the try: a seat.py that will not load is said, never raised
        if seat_driver is None:
            return name, None, None, "tools/cc/seat.py is not beside this script"
        brief = seat_driver.compose_brief(root, name, root)
        return name, brief.role, seat_driver.reprime_text(brief), "composed"
    except Exception as exc:  # noqa: BLE001 -- fail-open with voice: the reason rides the handoff's line
        return name, None, None, f"the brief refused ({os_error_text(exc)})"


#: Set by ``seat.py launch`` in a session it started with the own-clear mod
#: (``seat.OWN_CLEAR_KEY``); any other window has no mod to read the marker.
OWN_CLEAR_ENV = "ESPALIER_OWN_CLEAR"


def _own_clear_gate() -> str | None:
    """Why nothing can be armed from this shell, or None. Not a window the
    launcher started with the mod (:data:`OWN_CLEAR_ENV`): nothing would read
    a marker, so the by-hand reset is said instead. No session id in the
    environment (a handoff run outside a session): a marker with no session
    would clear any window."""
    if os.environ.get(OWN_CLEAR_ENV, "").strip() != "1":
        return (f"own-clear not armed: this window did not load the own-clear mod ({OWN_CLEAR_ENV} is not set; "
                "seat.py launch sets it when the mod rides), so it needs a /clear by hand")
    if not os.environ.get(SESSION_ID_ENV, "").strip():
        return (f"own-clear not armed: no {SESSION_ID_ENV} in the environment (this shell is not a Claude "
                "Code session's), so no window is told to clear")
    return None


#: The first words of the brief's tail after a handoff that did not land: the
#: re-primed window lands the lane before any new job (DEF-4057).
LAND_FIRST = "THE HANDOFF DID NOT LAND THIS LANE."


def _brief_text(text: str) -> str:
    """A refusal's text as the brief may carry it: 7-bit ASCII (anything else
    becomes ``?``), no double quote and no percent -- the rules every brief
    keeps (tests/test_seat.py pins them on the composed one; a Windows
    PowerShell 5.1 launch line splits at a double quote and cmd.exe expands a
    percent). The marker's brief is submitted as a prompt, never typed, but
    one rule for every brief is the one that stays pinned."""
    folded = text.encode("ascii", "replace").decode("ascii")
    return folded.replace('"', "'").replace("%", " pct")


def _land_first_tail(held: Held, branch: str) -> str:
    """What the re-primed window reads after its role brief when the handoff
    did not land: the refusal, where the lane waits, and the verbs that land
    it. The row is written and the tree clean (the handoff refused before
    this otherwise), so the next window's first job is the lane, not a new
    one."""
    what = "The push landed and a step after it refused" if held.landed else "The push was refused"
    lane = _brief_text(branch)
    where = (f"The lane {lane} is on origin" if held.landed
             else f"The lane {lane} is committed in this checkout and unpushed")
    return (f"\n\n{LAND_FIRST} {what}: {_brief_text(str(held))}\n"
            f"{where}, its row written and the tree clean; the window that handed off is done with it, and "
            "this one lands it before any new job: python tools/cc/ship.py status says what is on origin; "
            "with no pull request yet, python tools/cc/ship.py open once the base is green (the board, "
            "/inbox board, says when); after a push that landed, python tools/cc/ship.py rebind, or the "
            "command the refusal above names (auto-merge that did not arm is armed by hand).")


#: The mod's own first line for a window with no role brief (register.ts
#: GENERIC_BRIEF says the same; tests/test_own_clear.py pins the two by
#: phrase). It rides before a held tail, so a window with no seat name still
#: hears that its loop survived the clear.
GENERIC_BRIEF = ("The previous session handed off and this window was cleared by the own-clear. Orient from "
                 "the banner and read live state before you state it. A loop that was running survived the "
                 "clear: start no second one.")


def arm_own_clear_here(root: Path, *, held: Held | None = None, by_hand: str | None = None) -> str:
    """Arm the marker for the session this shell belongs to: the id Claude
    Code exports (:data:`SESSION_ID_ENV`), HEAD, and the seat's re-prime brief
    -- with, after a handoff that did not land (``held``), the refusal in the
    marker and the lane to land first appended to the brief (an unnamed seat's
    window reads it after the mod's generic line); or, from the ``arm`` verb,
    why it was armed by hand. Only where :func:`_own_clear_gate` lets it:
    elsewhere nothing is armed and the reason is the line."""
    why_not = _own_clear_gate()
    if why_not:
        return why_not
    session_id = os.environ[SESSION_ID_ENV].strip()
    seat, role, role_brief, how = _reprime_brief(root)
    brief, landed, outcome = role_brief, True, None
    if held is not None:
        landed, outcome = held.landed, str(held)
        try:
            branch = current_branch()
        except Refused:
            branch = "(its branch could not be read)"
        brief = (role_brief or GENERIC_BRIEF) + _land_first_tail(held, branch)
    elif by_hand:
        outcome = f"armed by hand: {by_hand}"
    line = arm_own_clear(root, session_id=session_id, head=head_sha(), seat=seat, role=role, brief=brief,
                         landed=landed, outcome=outcome)
    if held is not None:
        line += ("; with the refusal in its brief: this window is done with the lane, and the next window "
                 "lands the lane first")
    elif by_hand:
        line += f" (by hand: {by_hand})"
    if role_brief is None:
        line += (f"; no brief of its own rides it ({how}), so the mod re-primes with "
                 + ("its generic line and the lane to land" if held is not None else "its own line"))
    return line


def _lane_not_on_origin(root: Path) -> str | None:
    """Why HEAD is not on origin, or None when it is: no upstream (the lane was
    never pushed), commits the upstream lacks, or a push state git could not
    read. The by-hand arm clears a window only over a lane that is on origin:
    a handoff refused for a reason the window must fix first (a lane behind
    its remote, a rejected push) could otherwise be cleared past with the
    plain role brief, the lane left unpushed and unmentioned (the failure-mode
    review, 2026-10-30)."""
    rc, upstream, _ = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", cwd=str(root))
    upstream = upstream.strip()
    if rc != 0 or not upstream:
        return "HEAD has no upstream: the lane was never pushed"
    rc, count, _ = _git("rev-list", "--count", f"{upstream}..HEAD", cwd=str(root))
    if rc != 0 or not count.strip().isdigit():
        return f"the push state against {upstream} could not be read"
    ahead = int(count.strip())
    if ahead:
        return f"HEAD holds {ahead} commit{'s' if ahead != 1 else ''} that {upstream} does not"
    return None


def _own_clear_marker(root: Path) -> dict | None:
    """The marker's record when it is armed for this shell's session, else
    None: a missing or unreadable marker, another session's, or one the mod
    has consumed or marked stale."""
    try:
        marker = json.loads((root / STATE_DIR / OWN_CLEAR_MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (isinstance(marker, dict) and marker.get("state") == "armed"
            and marker.get("session_id") == os.environ.get(SESSION_ID_ENV, "").strip()):
        return marker
    return None


def _armed_for_this_session(root: Path) -> str | None:
    """When the marker is armed for this shell's session, its ``written_at``
    (or ``earlier``); else None, a missing or unreadable marker included."""
    marker = _own_clear_marker(root)
    return None if marker is None else str(marker.get("written_at") or "earlier")


def rearm_own_clear_after_move(root: Path, *, by: str) -> str | None:
    """After a verb moved HEAD under a marker armed for this session with
    nothing left to hand off -- the catch-up's pull of the server's merge,
    its own record merge once pushed, or a pull by hand the ``arm`` verb is
    run after -- rewrite the marker's ``head`` to HEAD with every other field
    kept (the brief, how the handoff ended, and the record the mod writes: a
    refusal's count is what the banner's Own-clear: line and the prompt
    router read) and the move on the record (``rearmed_from``,
    ``rearmed_by``, ``rearmed_at``); the line that says so, or None when no
    marker is armed for this session or its head is HEAD already. The mod
    holds the clear on ``HEAD moved since the handoff``, and a handoff
    re-arms only over a commit: a pull leaves nothing to hand off, so the
    hold stood until a re-arm by hand (air-work's window sat held for 3 h 33
    min on 2026-10-31 after its tick's catch-up)."""
    marker = _own_clear_marker(root)
    if marker is None:
        return None
    head = head_sha()
    before = str(marker.get("head") or "")
    if before == head:
        return None
    marker.update({"head": head, "rearmed_from": before or None, "rearmed_by": by,
                   "rearmed_at": datetime.now(timezone.utc).isoformat()})
    _write_own_clear(root, marker)
    return (f"own-clear re-armed at {head[:7]} ({by} moved HEAD from {before[:7] or '?'}; the marker's brief and "
            "record are kept): the mod clears this window at the turn's end")


def _rearm_own_clear_or_note(root: Path, *, by: str) -> None:
    """The re-arm after a move that landed, said; a marker that cannot be
    rewritten, or a HEAD git cannot name, is a note with the by-hand verb,
    never a refusal of the verb whose move is already made."""
    try:
        line = rearm_own_clear_after_move(root, by=by)
    except (OSError, Refused) as exc:
        _note(f"the own-clear marker was not re-armed after the move ({os_error_text(exc)}): the mod holds "
              "the clear on HEAD moved; run python tools/cc/ship.py arm")
        return
    if line:
        _say(line)


def _refusals_on_marker(root: Path) -> int:
    """How many asks the engine refused on the marker's record (the own-clear
    mod writes ``clear_refusals``, DEF-5031); 0 for none, or no marker."""
    try:
        marker = json.loads((root / STATE_DIR / OWN_CLEAR_MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    count = marker.get("clear_refusals") if isinstance(marker, dict) else None
    return count if isinstance(count, int) and count > 0 else 0


def arm(why: str | None = None, dry_run: bool = False) -> int:
    """The handoff's last act by hand: arm the own-clear marker for this
    session, for a lane opened by hand (``gh pr create`` ran no verb, so no
    marker: air-work's #353, 2026-10-30, its window left past the threshold)
    or a handoff whose arm did not run. The handoff's gates
    (:func:`_own_clear_gate`) refuse by name here; a dirty tracked tree
    refuses first (the mod would hold the clear on it anyway, and this verb
    should not promise one); a lane that is not on origin refuses and names
    the verbs that land it (:func:`_lane_not_on_origin`); a marker already
    armed for this session is kept, since a second arm would drop what the
    first one's brief says -- unless HEAD moved under it (a pull by hand,
    with the lane on origin): then the marker follows HEAD with its brief
    kept (:func:`rearm_own_clear_after_move`), the hold the mod names on a
    moved head cleared. ``why`` rides the marker's ``outcome``."""
    root = repo_root()
    why_not = _own_clear_gate()
    if why_not:
        raise Refused(why_not)
    _refuse_a_dirty_tree(root)
    off = _lane_not_on_origin(root)
    if off:
        raise Refused(f"nothing armed: {off}. The handoff arms on its own end, held or landed: run /handoff, or "
                      "python tools/cc/ship.py open for a lane with no pull request; `arm` is for a lane already "
                      "on origin (opened by hand)")
    armed = _armed_for_this_session(root)
    if armed:
        refused = _refusals_on_marker(root)
        refused_tail = (f"; the engine has refused its clear {refused} time(s) (the marker's record): this window "
                        "needs /clear by hand" if refused else "")
        marker = _own_clear_marker(root) or {}
        head = head_sha()
        before = str(marker.get("head") or "")
        if before != head:
            if dry_run:
                _say(f"dry-run: the marker armed for this session ({armed}) would be re-armed at {head[:7]} "
                     f"(HEAD moved from {before[:7] or '?'}; its brief kept)" + (f" ({why})" if why else ""))
                return 0
            try:
                line = rearm_own_clear_after_move(root, by="arm")
            except OSError as exc:
                raise Refused(f"the marker could not be rewritten: {os_error_text(exc)}") from None
            if line is None:
                _say("nothing re-armed: the marker is no longer armed for this session")
                return 0
            _say(line + (f" (by hand: {why})" if why else "") + refused_tail)
            return 0
        tail = (refused_tail + ", and a second arm would drop what the first one's brief says" if refused else
                ": the mod clears this window at the turn's end, and a second arm would drop what the first one's "
                "brief says")
        raise Refused(f"the own-clear marker is already armed for this session ({armed}){tail}")
    if dry_run:
        _say("dry-run: the own-clear marker would be armed for this session by hand" + (f" ({why})" if why else ""))
        return 0
    try:
        _say(arm_own_clear_here(root, by_hand=why or "ship.py arm"))
    except OSError as exc:
        raise Refused(f"the marker could not be written: {os_error_text(exc)}") from None
    return 0


def _release_claims(root: Path, lane: str, text: str) -> None:
    """After a push lands: close this machine's live claims on ``lane`` on the
    mail channel, so a claim's lifetime is the lane's time on this machine --
    before this, a claim nobody released warned the other box forever, and
    ``/handoff`` sent no release of its own. Nothing where the box is unnamed,
    the channel is absent, or no claim is live; a refusal or a failure is
    said, with the one command that closes them by hand, and never fails the
    push that landed. The send runs on the channel's own runner: it is the
    channel's push to its own ref, not a spawn of this verb's story."""
    try:
        mail = _mail_module()   # inside the try: a channel present without its own sibling is said, never raised
        if mail is None:
            return
        mail.release_lane(root, lane, text, say=_say)
    except Exception as exc:  # noqa: BLE001 -- fail-open with voice: the lane is pushed; the claim stays live and the way to close it is said
        _note(f"the lane's claims on the mail channel were not released ({os_error_text(exc)}); "
              f"`python tools/cc/mail.py send --type release --lane {lane}` closes them")


#: The liveness oracle (``tools/cc/checkout_sync.py``), loaded by path on first
#: use and never at import, as the mail channel is: a tree without it ships as
#: it did before. Tests stand an oracle in here.
_SYNC = None


def _sync_module():
    global _SYNC
    if _SYNC is None:
        path = Path(__file__).resolve().parent / "checkout_sync.py"
        if not path.is_file():
            return None
        import importlib.util
        spec = importlib.util.spec_from_file_location("_ship_checkout_sync", path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_ship_checkout_sync"] = module  # registered before exec (3.14)
        spec.loader.exec_module(module)
        _SYNC = module
    return _SYNC


#: Set to a reason, it lets a push past a shared checkout and says so: the
#: way through a refusal the registry got wrong (an entry no process of its
#: own still holds), never a default.
SHARED_CHECKOUT_OK = "ESPALIER_SHARED_CHECKOUT_OK"
#: Asked once per run: open, handoff, lane and catch-up each ask, and handoff
#: calls lane and open.
_SHARED = {"asked": False}


def shared_checkout(root: Path) -> tuple[list[str] | None, str]:
    """``(the live sessions working in this checkout in words, or None; the
    reason it is None, else the hints for the words)``: those Claude Code's
    registry places here, plus the session running this when it acts here
    from a checkout of its own. None when the registry cannot place them:
    the session markers alone outlive a closed window by hours, so they never
    stop a push. Never raises."""
    try:
        sync = _sync_module()
        if sync is None:
            return [], ""
        occ = sync.occupancy(root)
        if occ.sessions is None or occ.oracle != "registry":
            return None, occ.note or "only the session markers answered"
        rows = occ.from_registry()
        caller = occ.caller
        if caller is not None and not any(r.get("pid") == caller.get("pid") for r in rows):
            rows = rows + [caller]
        hints = []
        if any(row.get("kind") == "background" for row in rows):
            hints.append("a background session is one Claude Code's daemon resumed: `claude daemon stop --any` ends it")
        if rows:
            hints.append(f"the entries are under {sync.claude_config_dir() / 'sessions'}")
        return [sync.describe_session(row) for row in rows], "; ".join(hints)
    except Exception as exc:  # noqa: BLE001 -- fail-open with voice: the reason is said by the caller
        return None, f"the session registry was not read ({os_error_text(exc)})"


def _shared_checkout_words(who: list[str], hints: str) -> str:
    return (f"{len(who)} live sessions work in this checkout ({'; '.join(who)}"
            + (f"; {hints}" if hints else "") + "): they share its branch and index, so a push from here ships "
            "the other's commits too. Close one (a window or an editor tab), or give it a checkout of its own (a "
            f"worktree), then push; {SHARED_CHECKOUT_OK}=<reason> lets this push through when an entry names a "
            "session that is not really there")


def _refuse_a_shared_checkout(root: Path) -> None:
    """Stop a push from a checkout two or more live sessions share, before
    anything here moves. A registry that cannot place them is a
    note, never a refusal: a push is reversible, and a false refusal under an
    unreadable registry would stop every seat at once. Asked once a run."""
    if _SHARED["asked"]:
        return
    _SHARED["asked"] = True
    who, why = shared_checkout(root)
    if who is None:
        _note(f"who else works in this checkout cannot be told ({why}); the push goes ahead -- two sessions "
              "in one checkout share its branch, and only you can see whether that is so here")
        return
    if len(who) >= 2:
        reason = os.environ.get(SHARED_CHECKOUT_OK, "").strip()
        if reason:
            _note(f"pushing beside {len(who)} live sessions in this checkout ({SHARED_CHECKOUT_OK}: {reason})")
            return
        raise Refused(_shared_checkout_words(who, why))


def _refuse_a_marked_record(root: Path) -> None:
    """Stop a push the gate would red in every required cell: a record file
    that carries a merge-conflict marker. Named by file and line, with the
    one remedy and the one escape hatch (the rule is column zero)."""
    findings = record_file_markers(root)
    if findings:
        raise Refused("a record file carries a merge-conflict marker, which the harness guard refuses in "
                      f"every required cell: {'; '.join(findings)}. Resolve the hunk and commit the file "
                      "whole (a line that only quotes a marker is read as one too: indent the quote by "
                      "one space)")


def _merge_base_first(root: Path, base: str, *, dry_run: bool) -> None:
    """Before a push: when a merge of ``origin/<base>`` into HEAD would
    conflict, make that merge here, with the record files resolved by shape,
    so the pull request is born mergeable and the merge commit rides the one
    push. GitHub's own merge honours no merge driver, so a lane that conflicts
    on the memory row or the ledger's counts would otherwise sit CONFLICTING
    until a hand resolved it. A path carrying a merge attribute that changed
    on both sides is the same case: the local probe reads it clean because the
    local merge honours the attribute, GitHub's does not.

    A conflict the resolver refuses is a NOTE, not a stop: the lane ships and
    reads DIRTY on GitHub exactly as it would have, and the note names the way
    back. ``catch-up`` is the verb that refuses, since it exists to clear the
    hold."""
    ref = f"origin/{base}"
    names = record_merge.probe_conflicts(root, ref, run=RUN)
    driven = record_merge.attribute_merged_paths(root, ref, run=RUN)
    if names is None and not driven:
        _note(f"could not probe the merge with {ref} (git 2.38+ has `merge-tree --write-tree`, and the "
              "ref must be fetched); a lane that conflicts reads DIRTY on GitHub -- then run catch-up")
        return
    reasons = sorted(set(names or []) | set(driven))
    if not reasons:
        return
    if dry_run:
        _say(f"dry-run: would merge {ref} into the lane first (conflicts on {', '.join(reasons)})")
        return
    _refuse_a_dirty_tree(root)
    try:
        report = record_merge.merge_ref_in(root, ref, run=RUN, say=_say)
    except record_merge.Unresolvable as exc:
        _note(f"the lane conflicts with {ref} beyond what the record merge resolves ({exc}); it ships now "
              f"and will read DIRTY: git merge {ref}, resolve, commit, push, then rebind")
        return
    for line in report.notes:
        _say(line)


def _known_mergeable(branch: str, pr: dict) -> tuple[str, str]:
    """``(mergeable, mergeStateStatus)`` for the pull request, upper-cased,
    waiting out UNKNOWN: GitHub recomputes mergeability after every push to
    the base and reports UNKNOWN meanwhile (read 2026-10-05 on #88 the moment
    #91 merged). Bounded by the head-move wait; still UNKNOWN after it is a
    refusal that says to come back, never a guess."""
    deadline = time.monotonic() + HEAD_MOVE_WAIT_SECONDS
    while True:
        mergeable = str(pr.get("mergeable") or "").upper()
        state = str(pr.get("mergeStateStatus") or "").upper()
        # A settled merge state is acted on even while `mergeable` is still
        # being computed: a BEHIND lane took the server path before this read
        # existed and still does. Only both unknown is a wait.
        if state not in ("", "UNKNOWN") or mergeable != "UNKNOWN":
            return mergeable, state
        if time.monotonic() >= deadline:
            raise Refused(f"GitHub has not finished computing #{pr.get('number')}'s mergeability "
                          f"within {HEAD_MOVE_WAIT_SECONDS:.0f}s: wait, then run catch-up again")
        time.sleep(POLL_SECONDS)
        pr = pr_for_branch(branch, "open") or pr


def preflight() -> int:
    root = repo_root()
    base = default_branch()
    _git("fetch", "origin", "--quiet", cwd=str(root))
    _refuse_a_dirty_tree(root)
    marked = record_file_markers(root)
    if marked:
        _note(f"`open` will refuse this lane: a record file carries a merge-conflict marker "
              f"({'; '.join(marked)}); resolve the hunk and commit the file whole")
    who, why = shared_checkout(root)
    if who is None:
        _note(f"who else works in this checkout cannot be told ({why}); `open` will push anyway")
    elif len(who) >= 2:
        _note(f"`open` will refuse this lane: {_shared_checkout_words(who, why)}")
    rc, untracked, _ = _git("status", "--porcelain", "--untracked-files=all", cwd=str(root))
    scratch = [ln[3:] for ln in untracked.splitlines() if ln.startswith("?? ")]
    if scratch:
        _note(f"{len(scratch)} untracked file(s) will not ship (git add them if they should): {', '.join(scratch[:5])}"
              + (" ..." if len(scratch) > 5 else ""))
    rc, log, _ = _git("log", "--oneline", f"origin/{base}..HEAD", cwd=str(root))
    commits = [ln for ln in log.splitlines() if ln.strip()]
    if not commits:
        raise Refused(f"nothing to ship: no commits ahead of origin/{base}")
    _say(f"{len(commits)} commit(s) ahead of origin/{base}:")
    for ln in commits:
        _say(f"  {ln}")
    names = record_merge.probe_conflicts(root, f"origin/{base}", run=RUN)
    driven = record_merge.attribute_merged_paths(root, f"origin/{base}", run=RUN)
    if names is None and not driven:
        _note(f"could not probe the merge with origin/{base} (git 2.38+ has `merge-tree --write-tree`, "
              "and the ref must be fetched)")
    elif not names and not driven:
        _say(f"merges clean with origin/{base}")
    else:
        # A fragment written twice under one name is on the roster but never
        # resolved by shape (record_merge refuses it), so it counts as by hand.
        record = [n for n in names or [] if record_merge.on_roster(n) and not record_merge.is_fragment(n)]
        other = [n for n in names or [] if n not in record and n not in driven]
        if other:
            _note(f"conflicts with origin/{base} on {', '.join(other)}: `open` pushes anyway and the pull "
                  f"request reads DIRTY until you merge by hand (git merge origin/{base})"
                  + (f"; the record files ({', '.join(record)}) resolve by shape" if record else "")
                  + (f"; {', '.join(driven)} merges by this repository's attribute" if driven else ""))
        else:
            how = []
            if record:
                how.append(f"{', '.join(record)} resolved by shape")
            if driven:
                how.append(f"{', '.join(driven)} merged by this repository's attribute (GitHub's merge "
                           "cannot)")
            _say(f"conflicts with origin/{base}: `open` merges the base in first, {'; '.join(how)}")
    for line in post_merge_reds(cwd=str(root)):
        _say(line)
    red_run = base_red_run(base, cwd=str(root))
    if red_run is not None:
        base_red = _red_base_words(base, red_run)
        try:
            branch = current_branch()
        except Refused:
            branch = ""
        if branch.startswith("revert/"):
            _say(f"{base_red} -- this is a revert/ lane, which `open` lets through")
        else:
            _note(f"`open` will refuse this lane: {base_red}. Nothing lands on a red base: revert first, "
                  f"from a revert/ lane, or land a fix forward the dispatcher ruled (`open "
                  f"{BASE_RED_RULED_FLAG} <ack id>`, the ack opening `{RULING_HEAD}{red_run.get('databaseId')}` "
                  f"with --lane {branch or 'this lane'})")
    on, how = handoff_push_setting(root)
    if on:
        problem = memory_problem(root)
        if problem:
            _note(problem)
        if lane_carries_memory_row(base, root) is False:
            _note(f"`open` will refuse this lane: {_second_push_message(how)}")
    return 0


def lane() -> int:
    root = repo_root()
    base = default_branch()
    branch = current_branch()
    if branch != base:
        _say(f"HEAD is {branch}, not {base}: nothing to move (a lane already) -- next: open")
        return 0
    _refuse_a_shared_checkout(root)   # the switch below moves every session in this checkout onto the lane
    rc, subject, _ = _git("log", "-1", "--format=%s", cwd=str(root))
    slug = re.sub(r"[^A-Za-z0-9]+", "-", subject.strip()).strip("-").lower()[:48].rstrip("-")
    if not slug:
        raise Refused("the head subject yields no lane name: pick one by hand (git switch -c lane/<name>)")
    name = f"lane/{slug}"
    rc, _, err = _git("branch", name, cwd=str(root))
    if rc != 0:
        raise Refused(f"could not create {name}: {err.strip()} (pick another name by hand)")
    rc, _, err = _git("switch", name, cwd=str(root))
    if rc != 0:
        raise Refused(f"could not switch to {name}: {err.strip()}")
    # Only now, with every commit reachable from the lane, point the local
    # default branch back at origin's.
    rc, _, err = _git("branch", "-f", base, f"origin/{base}", cwd=str(root))
    if rc != 0:
        raise Refused(f"the lane {name} holds the commits, but local {base} could not be reset: {err.strip()}")
    _say(f"moved the unmerged commits to {name}; local {base} is back at origin/{base}")
    return 0


def _remote_has_commits_we_lack(branch: str, cwd: str) -> int:
    """Commits on origin/<branch> that HEAD does not reach: a push would be
    rejected, and the only way past is a merge -- never a rebase or a force,
    which rewrites a pushed lane and is the precondition of the push/edit race."""
    rc, _, _ = _git("fetch", "origin", branch, "--quiet", cwd=cwd)
    if rc != 0:
        return 0  # the remote branch does not exist yet: a first push
    rc, out, _ = _git("rev-list", "--count", f"HEAD..origin/{branch}", cwd=cwd)
    try:
        return int(out.strip() or "0") if rc == 0 else 0
    except ValueError:
        return 0


def open_pr(title: str | None = None, body_file: str | None = None, dry_run: bool = False,
            early: str | None = None, base_red_ruled: str | None = None) -> int:
    root = repo_root()
    base = default_branch()
    branch = current_branch()
    if branch == base:
        raise Refused(f"HEAD is {base}: run `lane` first (a protected default branch takes no push)")
    if pr_for_branch(branch, "open") is not None:
        raise Refused(f"an open pull request already exists for {branch}: after a push, run `rebind`")
    behind = _remote_has_commits_we_lack(branch, str(root))
    if behind:
        raise Refused(f"origin/{branch} has {behind} commit(s) this HEAD does not reach: merge them in "
                      f"(git merge origin/{branch}); never rebase or force-push a pushed lane")
    _refuse_a_marked_record(root)
    _refuse_a_shared_checkout(root)
    # The open pull requests once, for the row-debt read (a row riding this
    # seat's own open pull request), the red-base refusal and the one-per-seat
    # advisory; None where gh could not say, which the first reads as unread
    # and the other two as none.
    prs = _open_prs(str(root))
    # The row question before the base's: a lane with no row is the window's
    # to fix, whatever the base reads, and the held refusal below promises the
    # next window a row written (both reviews, 2026-10-30).
    on, how = handoff_push_setting(root)
    if on and lane_carries_memory_row(base, root) is False:
        early_reason = (early or "").strip()
        if not early_reason:
            raise Refused(_second_push_message(how))
        _refuse_on_row_debt(root, base, prs)
        _note(f"shipping before the handoff ({early_reason}): its row will be a second push on this lane")
    else:
        early_reason = ""
    prs = prs or []
    refusal, ruling = red_base_verdict(base, branch, prs, str(root), ruled=base_red_ruled, root=root)
    if refusal:
        # The lane is whole and stays here: the handoff arms the own-clear on
        # this one (the next window lands the lane once the base is green, or
        # once the dispatcher's ruling names the red run).
        raise Held(refusal, landed=False)
    if ruling:
        _say(ruling)
    seat, mine = seat_open_prs(root, branch, prs)
    if mine:
        _note(f"this seat ({seat}) already has an open pull request: {', '.join(mine)}. One open pull request "
              "per seat keeps a seat's lanes off each other's base; this one opens beside it")
    _wiring_note(root)
    # The base is fetched here, before the merge-first question and the guard
    # question below (both read origin/<base> and neither needs the remote
    # again). The title and the body are read BEFORE the merge-first step: a
    # merge commit's subject is "Merge remote-tracking branch ...", and the
    # lane's story is the head it had before (both reviews, driven).
    _git("fetch", "origin", base, "--quiet", cwd=str(root))
    rc, subject, _ = _git("log", "-1", "--format=%s", cwd=str(root))
    title = (title or subject.strip())[:TITLE_MAX].rstrip()
    if not title:
        raise Refused("the head commit has no subject and no --title was given: a pull request needs a title")
    if body_file:
        try:
            raw = Path(body_file).read_bytes()
        except OSError as exc:
            raise Refused(f"could not read --body-file {body_file}: {os_error_text(exc)}") from None
        body, problem = decode_text_or_problem(raw)
        if problem:
            # An operator-written file: a Windows editor's default encoding is
            # refused by name before anything is pushed, never a traceback.
            raise Refused(f"--body-file {body_file}: {problem}")
    else:
        rc, log, _ = _git("log", "--format=- %s", f"origin/{base}..HEAD", cwd=str(root))
        body = log
    # Bare line feeds whatever wrote the body (fold_newlines is the one owner):
    # a CRLF body through a text-mode temp file reached GitHub with every line
    # break doubled. The temp file below is opened with newline="" so nothing
    # is translated on the way out either; a test pins each half, the keyword
    # by AST because a Linux cell cannot observe it.
    body = fold_newlines(body)
    if early_reason:
        # On the record, not only on a terminal: an --early that became a reflex
        # is visible in every pull request it shipped.
        body = body.rstrip("\n") + f"\n\nShipped before the handoff: {early_reason}\n"
    if ruling:
        # The same record for a lane landed on a red base: the ruling that let
        # it through, and the run it named, in every pull request it shipped.
        body = body.rstrip("\n") + f"\n\nLanded on a red base by ruling: {ruling}\n"
    # The merge-first step, then the fold, then the marker's sha: a merge or a
    # fold commit moves HEAD, and a marker bound to the old head is the stall
    # rebind exists to clear. The fold is the Session Log cap's one writer.
    _merge_base_first(root, base, dry_run=dry_run)
    _fold_session_log(root, base, dry_run=dry_run)
    sha = head_sha()
    # The guard question is asked BEFORE the push: the diff against the fetched
    # base needs nothing on the remote, so a diff that fails or lists nothing
    # refuses with the lane still unpushed, and a dry run can answer the one
    # question worth rehearsing -- which paths bind.
    hits = marker_needed(root, base)
    if hits:
        title = bind(title, sha)
        _say(f"marker required ({', '.join(hits[:3])}{', ...' if len(hits) > 3 else ''}): bound to {sha[:7]} in the title")
    push = ["git", "push", "-u", "origin", "HEAD"]
    label = _seat_label(root)
    if dry_run:
        _say("dry-run: " + " ".join(push))
        _say(f"dry-run: gh pr create --base {base} --title '{title}' --body-file <tmp>"
             + (f" --label {label}" if label else ""))
        _say("dry-run: gh pr merge <n> --auto --merge")
        return 0
    rc, _, err = RUN(push, cwd=str(root))
    if rc != 0:
        raise Refused(f"the push was rejected: {err.strip()}")
    # From here the lane is on origin, so its claims close whatever the pull
    # request's creation and arming do next: a refusal below still releases
    # (failure-mode review, 2026-10-05), the operator finishing by hand with
    # the claims already closed.
    try:
        label = _ensure_seat_label(root, label)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".md", delete=False) as fh:
            fh.write(body)
            body_path = fh.name
        try:
            rc, out, err = _gh("pr", "create", "--base", base, "--title", title, "--body-file", body_path,
                               *(["--label", label] if label else []), cwd=str(root))
        finally:
            try:
                Path(body_path).unlink()
            except OSError:
                pass
        if rc != 0:
            raise Refused(f"gh pr create failed: {err.strip()}")
        url = out.strip().splitlines()[-1] if out.strip() else ""
        tail = url.rstrip("/").rsplit("/", 1)[-1]
        if tail.isdigit():
            number = tail  # the URL gh printed, not a re-listing that can lag behind the create
        else:
            pr = pr_for_branch(branch, "open")
            if pr is None:
                raise Refused(f"the pull request was created ({url or 'no URL printed'}) but cannot be found by "
                              f"branch yet: arm it by hand once it lists (gh pr merge <n> --auto --merge)")
            number = str(pr["number"])
        rc, _, err = _gh("pr", "merge", number, "--auto", "--merge", cwd=str(root))
        if rc != 0:
            raise Refused(f"auto-merge did not arm for #{number} ({err.strip()}): merge by hand once the checks are green -- {url}")
        armed = _gh_json("pr", "view", number, "--json", "autoMergeRequest", cwd=str(root))
        if not isinstance(armed, dict) or not armed.get("autoMergeRequest"):
            raise Refused(f"auto-merge reads back as NOT armed on #{number}: arm it by hand (gh pr merge {number} --auto --merge) -- {url}")
    except Refused as exc:
        _release_claims(root, branch, "Lane pushed; claims closed.")
        # The lane is on origin: what refused is the next window's to finish,
        # and a handoff running this arms the own-clear on it.
        raise Held(f"the push landed, then: {exc}", landed=True) from None
    _say(f"#{number} open, auto-merge armed, one push: {url}")
    # The release first: a notice that is slow or interrupted never leaves the claims live.
    _release_claims(root, branch, f"Lane shipped as #{number}; claims closed.")
    _overlap_notice(root, branch, base, number, sha)
    return 0


def _run_ids(branch: str, cwd: str) -> set[int] | None:
    """The ids of the harness-guard runs GitHub has for ``branch``; None when
    the workflow is not there to ask (a tree without it, or a renamed file)."""
    rc, out, _ = _gh("run", "list", "--workflow", "harness-guard.yml", "--branch", branch,
                     "--limit", "10", "--json", "databaseId", cwd=cwd)
    if rc != 0:
        return None
    try:
        rows = json.loads(out or "[]")  # json-dict-safe: ok a list of run rows; each row is isinstance-checked in the comprehension below
    except ValueError:
        return None
    if not isinstance(rows, list):
        return None
    return {int(r["databaseId"]) for r in rows
            if isinstance(r, dict) and str(r.get("databaseId", "")).isdigit()}


def _wait_for_new_run(branch: str, cwd: str, known: set[int], wait: float = RUN_WAIT_SECONDS) -> bool:
    """Until GitHub has created a harness-guard run that was not there before
    (bounded). The push's own run already sits on this head, so "a run on the
    head" is satisfied at once; only a run that did not exist before the strip
    edit proves that edit's event was processed, and that is what puts the
    re-bind's run second in the concurrency group."""
    deadline = time.monotonic() + wait
    while True:
        ids = _run_ids(branch, cwd)
        if ids is not None and ids - known:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_SECONDS)


def gate_reads_the_title_live(root: Path) -> bool | None:
    """Does this tree's harness-guard workflow read the title at check time?
    False on an older workflow that judges the event payload's title (a
    newer one may sit parked as harness-guard.yml.new); None when the tree
    has no such workflow."""
    wf = root / ".github" / "workflows" / "harness-guard.yml"
    if not wf.is_file():
        return None
    try:
        return LIVE_READ_STEP in wf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def rebind(dry_run: bool = False) -> int:
    root = repo_root()
    _wiring_note(root)
    branch = current_branch()
    pr = _require_open_pr(branch)
    sha = head_sha()
    number = str(pr["number"])
    if not str(pr.get("headRefOid", "")).startswith(sha):
        raise Refused(f"push first: HEAD {sha[:7]} is not #{number}'s head {str(pr.get('headRefOid', ''))[:7]}")
    current = str(pr.get("title") or "")
    bound = bind(current, sha)
    if dry_run:
        _say(f"dry-run: gh pr edit {number} --title '{bound}'")
        return 0
    if bound == current.rstrip():
        # Already bound to this head. The verdict on record may still be red
        # (a run born from the push judged an older title): an identical edit
        # fires no event, so strip, let that event's run exist, then re-bind --
        # the second run is created after the first and wins the concurrency
        # group. Only safe where the gate reads the title live: on an older
        # workflow the marker-less title could be the one the surviving run
        # judges, which is the stall this verb exists to clear.
        live = gate_reads_the_title_live(root)
        if live is False:
            parked = (root / ".github" / "workflows" / "harness-guard.yml.new").is_file()
            _say(f"#{number} is already bound to {sha[:7]}, and the guard on this tree judges the event "
                 f"payload's title: an identical edit fires nothing, and a marker-less edit could be the "
                 f"title the surviving run judges. Re-run the red check from its Actions page, or push a "
                 f"commit and run rebind."
                 + (" A newer workflow is parked at .github/workflows/harness-guard.yml.new: merge it "
                    "over yours and the gate reads the title live." if parked else ""))
            return 0
        known = _run_ids(branch, str(root)) or set()
        stripped = _MARKER_RE.sub("", current).rstrip()
        _say(f"#{number} is already bound to {sha[:7]}; re-firing the check: strip, then re-bind")
        rc, _, err = _gh("pr", "edit", number, "--title", stripped, cwd=str(root))
        if rc != 0:
            raise Refused(f"gh pr edit failed: {err.strip()}")
        if not _wait_for_new_run(branch, str(root), known):
            _note("no new harness-guard run appeared for the stripped title within the wait"
                  + (" (this tree has no harness-guard workflow to run)" if live is None else "")
                  + "; re-binding anyway")
    rc, _, err = _gh("pr", "edit", number, "--title", bound, cwd=str(root))
    if rc != 0:
        raise Refused(f"gh pr edit failed: {err.strip()}")
    after = _gh_json("pr", "view", number, "--json", "title", cwd=str(root))
    title_now = str(after.get("title", "")) if isinstance(after, dict) else ""
    if len(_MARKER_RE.findall(title_now)) != 1 or not title_now.endswith(f"{MARKER}@{sha[:7]}"):
        raise Refused(f"the title did not take the binding: it reads '{title_now}'")
    _say(f"#{number} re-bound to {sha[:7]}: {title_now}")
    return 0


def _wait_for_pr_head(branch: str, sha: str) -> None:
    """After a push, wait until GitHub reports ``sha`` as the pull request's
    head: `rebind` read immediately after a push can see the old head and
    refuse with "push first" although the push landed (met 2026-10-03)."""
    deadline = time.monotonic() + HEAD_MOVE_WAIT_SECONDS
    while True:
        now = pr_for_branch(branch, "open")
        if now is not None and str(now.get("headRefOid", "")).startswith(sha):
            return
        if time.monotonic() >= deadline:
            raise Refused(f"pushed, but the pull request's head did not reach {sha[:7]} within "
                          f"{HEAD_MOVE_WAIT_SECONDS:.0f}s: run `rebind` again")
        time.sleep(POLL_SECONDS)


def handoff(title: str | None = None, body_file: str | None = None, dry_run: bool = False,
            base_red_ruled: str | None = None) -> int:
    """/handoff's one push step, then the own-clear's arm. The push
    (:func:`_handoff_push`) runs only when espalier.toml sets ``handoff_push =
    true``, else the commit stays local and the verb says how to push it. Once
    that step has run to its end -- the off path said (its commit stays local
    by design and the window is done with it), the row parked, the pull
    request opened or the push re-bound, or a refusal the window is done with
    (:class:`Held`: the base is red and the lane stays here whole, or the push
    landed and a step after it refused) -- the own-clear marker is armed for
    this session (:func:`arm_own_clear_here`), last; a held refusal rides the
    marker, the lane to land first rides the brief, and the refusal is
    re-raised (exit 1 still). A refusal the window must fix first -- a dirty
    tree, a shared checkout, a lane behind its remote, a rejected push --
    never arms, so no marker clears a window with work in it (DEF-4057: until
    this, no refusal armed, and three seats sat past the threshold with no
    clear). The arm itself never fails a handoff whose step has run: what
    stops it is said, with the by-hand reset. A dry run says what it would
    arm."""
    try:
        rc = _handoff_push(title, body_file, dry_run, base_red_ruled)
    except Held as whole:
        if dry_run:
            _say("dry-run: the own-clear marker would be armed for this session with this refusal in its brief")
            raise
        _arm_or_say(held=whole)
        raise
    if rc != 0:
        return rc
    if dry_run:
        _say("dry-run: the own-clear marker would be armed for this session, last")
        return 0
    _arm_or_say()
    return 0


def _arm_or_say(*, held: Held | None = None) -> None:
    """The handoff's arm, which never fails the handoff: what stops it, the
    root's own read included, is said, with the by-hand reset."""
    try:
        root = repo_root()
        _say(arm_own_clear_here(root, held=held) if held is not None else arm_own_clear_here(root))
    except Exception as exc:  # noqa: BLE001 -- fail-open with voice: the step has run; the reset is said instead
        _note(f"the own-clear marker was not armed ({os_error_text(exc)}); this window will not clear itself, "
              "so it needs a /clear by hand")


def _handoff_push(title: str | None, body_file: str | None, dry_run: bool,
                  base_red_ruled: str | None = None) -> int:
    """The push half of :func:`handoff`. Off: the handoff's commit stays local
    and this says how to push it and how to opt in -- and, when a pull request
    is already open for the branch, that it will merge WITHOUT this commit. On:
    the lane is opened as a pull request, or, when one is already open, this
    commit is pushed onto it and the marker re-bound to the new head.
    ``base_red_ruled`` (an ack id) is the dispatcher's ruling that lets the
    lane land on a red base: handed to `open`, which judges it; on a push onto
    an open pull request, read here, where the base's red is a note."""
    root = repo_root()
    on, how = handoff_push_setting(root)
    if not on:
        _say(f"handoff push is off: {how}.")
        try:
            branch = current_branch()
        except Refused:
            branch = ""
        pr = pr_for_branch(branch, "open") if branch else None
        if pr is not None:
            _say(f"#{pr.get('number')} is open for {branch} and will merge WITHOUT this commit: push "
                 "it onto the pull request yourself (`git push`, then `python tools/cc/ship.py "
                 "rebind`), or the handoff's row is left behind on a merged branch.")
        else:
            _say("This handoff's commit stays local. Push the lane when you choose with /ship "
                 "(`python tools/cc/ship.py lane`, then `open`); to have /handoff push it, set "
                 f"{HANDOFF_PUSH_KEY} = true in espalier.toml.")
        return 0
    _say(f"handoff push is on: {how}.")
    _refuse_a_dirty_tree(root)
    _refuse_a_marked_record(root)
    # Before `lane` below, which switches this checkout's branch: a second
    # session here would keep committing onto the lane it was moved to.
    _refuse_a_shared_checkout(root)
    base = default_branch()
    on_base = current_branch() == base
    pr = None if on_base else pr_for_branch(current_branch(), "open")
    # A handoff whose lane already merged carries its row alone: park it on the
    # records ref instead of opening a pull request for one row (DEF-5007).
    if pr is None and _park_the_row(root, base, dry_run=dry_run):
        return 0
    if on_base:
        if dry_run:
            _say("dry-run: `lane` would move the unmerged commits to a lane branch, then `open` "
                 "would push it as a pull request with auto-merge armed")
            return 0
        lane()
        pr = pr_for_branch(current_branch(), "open")
    branch = current_branch()
    if pr is None:
        return open_pr(title=title, body_file=body_file, dry_run=dry_run, base_red_ruled=base_red_ruled)
    behind = _remote_has_commits_we_lack(branch, str(root))
    if behind:
        raise Refused(f"origin/{branch} has {behind} commit(s) this HEAD does not reach: merge them in "
                      f"(git merge origin/{branch}); never rebase or force-push a pushed lane")
    # Before this path's push; the no-pull-request path above returns through
    # open_pr, which asks itself, and the rebind below asks and stands down.
    _wiring_note(root)
    # The handoff's push should leave the pull request mergeable, the same as a
    # first push would: merge ITS base in first when the lane would conflict.
    base = str(pr.get("baseRefName") or base)
    _git("fetch", "origin", base, "--quiet", cwd=str(root))
    _merge_base_first(root, base, dry_run=dry_run)
    _fold_session_log(root, base, dry_run=dry_run)
    red_run = base_red_run(base, cwd=str(root))
    if red_run is not None and pr.get("autoMergeRequest") and not branch.startswith("revert/"):
        # Not a refusal: the handoff's row must reach the pull request. Its
        # auto-merge was armed before the base went red, and lands on it -- by
        # the dispatcher's ruling where one is given and holds, else named with
        # the disarm.
        base_red = _red_base_words(base, red_run)
        number = pr.get("number")
        disarm = (f"#{number}'s auto-merge is armed and lands on the red base once this push is green: "
                  f"gh pr merge --disable-auto {number} until the revert merges")
        if base_red_ruled:
            sender, problem, text = red_base_ruling(root, base_red_ruled, str(red_run.get("databaseId")),
                                                    branch=branch)
            if problem is None:
                _say(f"{base_red} -- #{number} lands on it by the dispatcher's ruling {base_red_ruled} "
                     f"({sender}'s gridlock ack naming run {red_run.get('databaseId')}: "
                     f"{text[:RULING_TEXT_CHARS]})")
            else:
                _note(f"{base_red}. {BASE_RED_RULED_FLAG} {base_red_ruled}: {problem}. {disarm}")
        else:
            _note(f"{base_red}. {disarm}")
    if dry_run:
        _say(f"dry-run: git push origin {branch}; then rebind the marker to the new head")
        return 0
    rc, _, err = _git("push", "origin", branch, cwd=str(root))
    if rc != 0:
        raise Refused(f"git push failed: {err.strip()[:200]}")
    pushed = head_sha()
    # From here the push has landed: a refusal after it is the next window's
    # to finish (`rebind`), not this one's to fix, and the handoff arms on it.
    try:
        _wait_for_pr_head(branch, pushed)
        rc = rebind()
    except Refused as exc:
        # The claims close with the push, as open_pr's do (its 2026-10-05
        # rule): the next window runs `rebind`, which releases nothing.
        _release_claims(root, branch, "Handoff pushed onto the open pull request; claims closed.")
        raise Held(f"the push landed, then: {exc}", landed=True) from None
    if rc != 0:
        _release_claims(root, branch, "Handoff pushed onto the open pull request; claims closed.")
        raise Held(f"the push landed, then the rebind returned {rc}: run `python tools/cc/ship.py rebind`",
                   landed=True)
    _release_claims(root, branch, "Handoff pushed onto the open pull request; claims closed.")
    _overlap_notice(root, branch, base, pr.get("number"), pushed)
    return 0


def catch_up() -> int:
    """Bring the lane level with its base: on the server (``gh pr
    update-branch``, then a pull) when GitHub reads it clean, here (the
    record merge, then a push) when it reads CONFLICTING; then re-bind.
    Either way HEAD moves with nothing new to hand off, so a marker the
    handoff armed for this session is re-armed at the new head once the move
    landed (:func:`rearm_own_clear_after_move`): the own-clear mod holds the
    clear on a moved head, and the hold stood until a re-arm by hand."""
    root = repo_root()
    _refuse_a_shared_checkout(root)   # both paths below change this checkout's lane and push or pull it
    _wiring_note(root)
    branch = current_branch()
    pr = _require_open_pr(branch)
    number = str(pr["number"])
    mergeable, state = _known_mergeable(branch, pr)
    if mergeable == "CONFLICTING" or state == "DIRTY":
        # The server cannot make this merge: `gh pr update-branch` would answer
        # with the conflict, and GitHub honours no merge driver. Make it here,
        # with the record files resolved by shape, then push and re-bind. The
        # base is the pull request's own, not the default branch's name.
        base = str(pr.get("baseRefName") or default_branch())
        _refuse_a_dirty_tree(root)
        _git("fetch", "origin", base, "--quiet", cwd=str(root))
        try:
            report = record_merge.merge_ref_in(root, f"origin/{base}", run=RUN, say=_say)
        except record_merge.Unresolvable as exc:
            raise Refused(f"#{number} conflicts with {base} beyond what the record merge resolves: {exc}") from None
        for line in report.notes:
            _say(line)
        if not report.merged:
            raise Refused(f"#{number} reads {mergeable or state} on GitHub, yet HEAD already reaches "
                          f"origin/{base}: push what is here, then run `status`")
        rc, _, err = _git("push", "origin", branch, cwd=str(root))
        if rc != 0:
            raise Refused(f"git push failed after the merge: {err.strip()[:200]}")
        _rearm_own_clear_or_note(root, by="catch-up")   # the push landed: HEAD moved at the merge, nothing is ahead
        _wait_for_pr_head(branch, head_sha())
        return rebind()
    was = str(pr.get("headRefOid", ""))
    rc, out, err = _gh("pr", "update-branch", number, cwd=str(root))
    if rc != 0:
        if "up-to-date" in (out + err) or "up to date" in (out + err):
            _say(f"#{number} is not behind its base: the hold is something else -- run `status`")
            return 0
        if "conflict" in (out + err).lower():
            raise Refused(f"GitHub reports a conflict the server cannot merge (it read {state or 'no state'} "
                          f"a moment ago): run catch-up again once the merge state settles, and it merges "
                          "the base in here")
        raise Refused(f"gh pr update-branch failed ({err.strip()}): a gh older than 2.53 lacks the verb")
    deadline = time.monotonic() + HEAD_MOVE_WAIT_SECONDS
    moved = False
    while time.monotonic() < deadline:
        now = pr_for_branch(branch, "open")
        if now is not None and str(now.get("headRefOid", "")) != was:
            moved = True
            break
        time.sleep(POLL_SECONDS)
    if not moved:
        raise Refused(f"#{number}'s head did not move within {HEAD_MOVE_WAIT_SECONDS:.0f}s: wait, then run catch-up again")
    rc, _, err = _git("pull", "--ff-only", "origin", branch, cwd=str(root))
    if rc != 0:
        raise Refused(f"cannot fast-forward {branch}: an unpushed commit here ({err.strip()}); push it, then run catch-up again")
    _rearm_own_clear_or_note(root, by="catch-up")   # the pull moved HEAD onto origin's tip: nothing is ahead
    return rebind()


#: A required cell ends red for one of two reasons: its tests (or a person)
#: decided, or its runner never let them. Only the second is worth a re-run,
#: and only the two shapes of it measured 2026-10-05 over sixty pull-request
#: runs of the test workflow are recognised -- a positive list. A job no hosted
#: runner picked up ends `cancelled`, annotated so (two heads that day). A job
#: whose runner went away mid-step ends `failure` with a step `cancelled` and
#: none `failure`, annotated "The operation was canceled." (#99's two cells,
#: which held its merge until a session re-ran them by hand). The match is on
#: GitHub's own English, so a shape with the right outline and notes outside
#: these lists is reported as "cause not read", never as either answer: that
#: line is where a rewording shows up.
_NOT_ACQUIRED = "was not acquired by runner"
_OPERATION_CANCELED = "the operation was canceled"
#: Notes that make a cancelled or step-cancelled job a decision, read before
#: the two above: a run a newer one superseded, a hand cancellation, and a job
#: that outran its `timeout-minutes` (which carries "The operation was
#: canceled." too, and would otherwise read as a lost runner).
_DECIDED_NOTES = (
    ("higher priority waiting request", "a newer run superseded it"),
    ("was canceled by", "cancelled by hand"),
    ("exceeded the maximum execution time", "it outran its timeout"),
)
#: An Actions job's link as `gh pr checks --json link` gives it: run, then job.
_JOB_LINK_RE = re.compile(r"/actions/runs/(\d+)/job/(\d+)(?![0-9])")
#: The buckets of `gh pr checks` that hold a merge: a cancelled required cell
#: holds it as surely as a failed one. An alias of the one home's set
#: (tools/cc/_post_merge.py), never a copy.
_RED_BUCKETS = _post_merge.RED_BUCKETS
#: A finished job's conclusions that hold nothing, in the REST spelling.
_JOB_GREEN = frozenset(s.lower() for s in _CHECK_GREEN)


class _Reading:
    """The required checks of one pull request, sorted by what can be done.

    ``decided``: red cells whose tests or a person decided (and checks that are
    not Actions jobs, which nothing here re-runs). ``unread``: red cells this
    driver could not place, each with why and the command that shows its log.
    ``rerunnable``: run id -> the cells one re-run of that run retries.
    ``held``: lost cells the driver will not re-run now, each line saying why
    and what to do instead. ``pending``: still running. `status` prints this
    and `rerun` acts on it, so the two never disagree."""

    def __init__(self) -> None:
        self.decided: list[str] = []
        self.unread: list[str] = []
        self.rerunnable: dict[str, list[str]] = {}
        self.held: list[str] = []
        self.pending: list[str] = []


def _annotation_text(job_id: str, cwd: str) -> str | None:
    """A job's annotation messages, lower-cased and joined; None when they
    cannot be read."""
    rc, out, _ = _gh("api", f"repos/{{owner}}/{{repo}}/check-runs/{job_id}/annotations", cwd=cwd)
    if rc != 0:
        return None
    try:
        rows = json.loads(out or "")  # json-dict-safe: ok the list and each row are isinstance-checked below
    except ValueError:
        return None
    if not isinstance(rows, list):
        return None
    return " ".join(str(r.get("message") or "") for r in rows if isinstance(r, dict)).lower()


def _classify(job: dict | None, cwd: str) -> tuple[str, str]:
    """``("lost", why)`` when the runner, not the tests, ended this finished
    job; ``("decided", what)`` when its tests or a person did; ``("unread",
    why)`` when this driver cannot place it. The notes are read only when the
    steps leave the question open."""
    if job is None:
        return "unread", "its job is not in the run's latest attempt"
    conclusion = str(job.get("conclusion") or "").lower()
    steps = {str(s.get("conclusion") or "").lower() for s in job.get("steps") or [] if isinstance(s, dict)}
    if conclusion == "failure" and "failure" in steps:
        return "decided", "a step failed"
    if conclusion == "timed_out":
        return "decided", "it outran its timeout"
    if not (conclusion == "cancelled" or (conclusion == "failure" and "cancelled" in steps)):
        return "unread", f"it ended {conclusion or 'with no conclusion'}"
    job_id = str(job.get("databaseId") or "")
    notes = _annotation_text(job_id, cwd) if job_id.isdigit() else None
    if notes is None:
        return "unread", "its notes could not be read"
    for needle, what in _DECIDED_NOTES:
        if needle in notes:
            return "decided", what
    if conclusion == "cancelled" and _NOT_ACQUIRED in notes:
        return "lost", "no runner picked it up"
    if conclusion == "failure" and _OPERATION_CANCELED in notes:
        return "lost", "a step was cancelled, none failed"
    return "unread", f"{conclusion}, with notes this driver does not recognise"


def _job_name(job: dict) -> str:
    return str(job.get("name") or "?")


def _read_required(number: str, cwd: str, merge_state: str = "") -> _Reading | None:
    """The pull request's required checks as a ``_Reading``, or None when the
    answer could not be read -- a repository with no required checks at all
    answers rc=1 with no JSON, the common adopter posture, and that is "could
    not read", not a red.

    A lost cell is offered for a re-run only when its whole run can take one
    -- finished, never re-run (GitHub's attempt counter is the bound, so
    "once" holds across sessions and machines), and with no other red in it,
    since ``gh run rerun --failed`` retries every failed job in the run, a
    flaky decided one included -- and only when nothing else holds the merge:
    a decided or unread red, another lost run that is held, or a lane behind
    or in conflict with its base, where catch-up re-runs every cell anyway."""
    try:
        rows = _gh_json("pr", "checks", number, "--required", "--json", "name,bucket,link", cwd=cwd)
    except Refused:
        return None
    if not isinstance(rows, list):
        return None
    reading = _Reading()
    by_run: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "?")
        bucket = str(row.get("bucket") or "").lower()
        if bucket == "pending":
            reading.pending.append(name)
        elif bucket in _RED_BUCKETS:
            m = _JOB_LINK_RE.search(str(row.get("link") or ""))
            if m is None:
                reading.decided.append(name)  # not an Actions job: nothing here re-runs it
            else:
                by_run.setdefault(m.group(1), []).append((name, m.group(2)))
    for run_id, cells in sorted(by_run.items()):
        try:
            view = _gh_json("run", "view", run_id, "--json", "attempt,status,jobs", cwd=cwd)
        except Refused:
            view = None
        if not isinstance(view, dict):
            reading.unread.extend(f"{name} (run {run_id} could not be read: gh run view {run_id})"
                                  for name, _ in cells)
            continue
        jobs = [j for j in view.get("jobs") or [] if isinstance(j, dict)]
        by_id = {str(j.get("databaseId")): j for j in jobs}
        lost: list[tuple[str, str]] = []
        for name, job_id in cells:
            kind, why = _classify(by_id.get(job_id), cwd)
            if kind == "lost":
                lost.append((f"{name} ({why})", job_id))
            elif kind == "decided":
                reading.decided.append(name)
            else:
                reading.unread.append(f"{name} ({why}: gh run view {run_id} --job {job_id} --log)")
        if not lost:
            continue
        labels = ", ".join(label for label, _ in lost)
        attempt = view.get("attempt")
        if str(view.get("status") or "").lower() != "completed":
            reading.held.append(f"{labels}: run {run_id} is still running; run rerun once it finishes")
            continue
        if attempt != 1:
            reading.held.append(f"{labels}: run {run_id} was already re-run (attempt {attempt}); "
                                f"read its log (gh run view {run_id} --log-failed), or push")
            continue
        ours = {job_id for _, job_id in cells}
        extra: list[str] = []
        blocker = ""
        for job in jobs:
            if str(job.get("databaseId")) in ours or str(job.get("conclusion") or "").lower() in _JOB_GREEN:
                continue
            kind, why = _classify(job, cwd)
            if kind != "lost":
                blocker = f"{_job_name(job)} ({why})"
                break
            extra.append(f"{_job_name(job)} ({why}; not required)")
        if blocker:
            by_hand = "; ".join(f"gh run rerun {run_id} --job {job_id}" for _, job_id in lost)
            reading.held.append(f"{labels}: run {run_id} also holds {blocker}, which a re-run of its "
                                f"failed jobs would retry too; re-run the cell alone by hand ({by_hand}), "
                                "or push")
            continue
        reading.rerunnable[run_id] = [label for label, _ in lost] + extra
    if reading.rerunnable:
        if reading.decided or reading.unread:
            why = ("waits on the required red above: fix it, then run status again (a push re-runs "
                   "every cell, a rebind does not)")
        elif reading.held:
            why = "waits on the held run above, so one rerun takes them together"
        elif merge_state in ("BEHIND", "DIRTY"):
            why = (f"the lane is {'behind' if merge_state == 'BEHIND' else 'in conflict with'} its base; "
                   "catch-up re-runs every cell")
        else:
            why = ""
        if why:
            reading.held.extend(f"{', '.join(labels)}: {why}" for _, labels in sorted(reading.rerunnable.items()))
            reading.rerunnable = {}
    reading.decided.sort()
    return reading


def rerun(dry_run: bool = False) -> int:
    """Re-run, once, the required cells a lost runner ended.

    A CI trigger for this verb (a later lane) inherits two constraints: it
    must run outside the run it re-runs -- a run never reads `completed`
    while one of its own jobs is running, so from inside it is always "still
    running" -- and it needs `actions: write`, which the test workflow does
    not grant."""
    root = repo_root()
    branch = current_branch()
    pr = _require_open_pr(branch)
    number = str(pr["number"])
    reading = _read_required(number, str(root), str(pr.get("mergeStateStatus") or "").upper())
    if reading is None:
        raise Refused(f"could not read #{number}'s required checks: nothing re-run")
    stops: list[str] = []
    if reading.decided:
        stops.append(f"a required red its tests decided: {', '.join(reading.decided)} -- fix it, then run "
                     "status again (a push re-runs every cell, a rebind does not)")
    if reading.unread:
        stops.append(f"a required red whose cause was not read: {'; '.join(reading.unread)}")
    stops.extend(reading.held)
    if stops:
        raise Refused(f"#{number}: " + "; ".join(stops) + " -- nothing re-run")
    if not reading.rerunnable:
        still = f"; {len(reading.pending)} still running" if reading.pending else ""
        _say(f"#{number}: no required cell was ended by a lost runner{still} -- nothing to re-run")
        return 0
    for run_id, labels in sorted(reading.rerunnable.items()):
        if dry_run:
            _say(f"dry-run: gh run rerun {run_id} --failed ({', '.join(labels)})")
            continue
        rc, _, err = _gh("run", "rerun", run_id, "--failed", cwd=str(root))
        if rc != 0:
            raise Refused(f"gh run rerun {run_id} --failed failed: {err.strip()[:200]}")
        _say(f"re-ran run {run_id} once: {', '.join(labels)}")
    if not dry_run:
        _say("auto-merge is untouched; a cell a lost runner ends again is not re-run by the driver: "
             "read its log, or push")
    return 0


def status() -> int:
    root = repo_root()
    branch = current_branch()
    pr = pr_for_branch(branch, "open") or pr_for_branch(branch, "merged")
    if pr is None:
        _say(f"no pull request for {branch}")
        return 0
    number = str(pr["number"])
    armed = "armed" if pr.get("autoMergeRequest") else "not armed"
    _say(f"#{number} {pr.get('state')} merge-state={pr.get('mergeStateStatus')} auto-merge {armed} head={str(pr.get('headRefOid', ''))[:7]}")
    _say(f"title: {pr.get('title')}")
    if pr.get("state") == "OPEN":
        reading = _read_required(number, str(root), str(pr.get("mergeStateStatus") or "").upper())
        if reading is None:
            _say("could not read which checks are required")
        else:
            if reading.decided:
                _say(f"required red: {', '.join(reading.decided)} -- fix, push, rebind")
            for line in reading.unread:
                _say(f"required red, cause not read: {line}")
            for run_id, labels in sorted(reading.rerunnable.items()):
                _say(f"required, runner lost: {', '.join(labels)} -- `ship.py rerun` re-runs run {run_id} once")
            for line in reading.held:
                _say(f"required, runner lost: {line}")
            if not (reading.decided or reading.unread or reading.rerunnable or reading.held):
                _say("no required check is red")
        stale = stale_base_line(root, str(pr.get("baseRefName") or default_branch()), {**pr, "headRefName": branch})
        if stale:
            _say(stale)
    merge = pr.get("mergeCommit") or {}
    if isinstance(merge, dict) and merge.get("oid"):
        _say(f"merged as {str(merge['oid'])[:7]}")
    _say(str(pr.get("url", "")))
    return 0


def _tree_version(root: Path) -> str | None:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        text = pyproject.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # The [project] table's version, not the first `version =` in the file
    # (a tool table can carry one of its own).
    parts = text.split("\n[project]", 1)
    scope = parts[1].split("\n[", 1)[0] if len(parts) == 2 else text
    m = re.search(r'^version\s*=\s*"([^"]+)"', scope, re.M)
    return m.group(1) if m else None


def release(tag: str, dry_run: bool = False) -> int:
    root = repo_root()
    branch = current_branch()
    if not re.fullmatch(r"v\d[^\s]*", tag):
        raise Refused(f"'{tag}' is not a release tag (vX.Y.Z): stop")
    version = _tree_version(root)
    if version is None:
        raise Refused("could not read the tree's version from pyproject.toml: read it from where this tree keeps it, and compare by hand")
    if tag != f"v{version}":
        raise Refused(f"tag {tag} is not the tree's version v{version}: stop")
    pr = pr_for_branch(branch, "merged")
    merge = (pr or {}).get("mergeCommit") or {}
    oid = str(merge.get("oid", "")) if isinstance(merge, dict) else ""
    if pr is None or pr.get("state") != "MERGED" or not oid:
        raise Refused(f"no merged pull request for {branch}: run release from the lane branch the pull "
                      f"request was opened from (switch to the default branch after, not before), and only "
                      f"once it is MERGED -- the tag goes on the merge commit, never the lane")
    rc, _, _ = _git("rev-parse", "-q", "--verify", f"refs/tags/{tag}", cwd=str(root))
    if rc == 0:
        raise Refused(f"tag {tag} already exists locally: a prior attempt left it; inspect it (git show {tag}) before anything is pushed")
    rc, out, _ = _git("ls-remote", "--tags", "origin", tag, cwd=str(root))
    if out.strip():
        raise Refused(f"tag {tag} already exists on origin: a release for it was pushed before")
    if dry_run:
        _say(f"dry-run: git tag -a {tag} -m {tag} {oid[:7]}; git push origin {tag}; gh release create {tag} --notes-from-tag")
        return 0
    # The merge commit lives on origin; a lane checkout that never pulled the
    # base does not have it, and `git tag` on an absent object fails.
    _git("fetch", "origin", default_branch(), "--quiet", cwd=str(root))
    rc, _, err = _git("tag", "-a", tag, "-m", f"{tag}", oid, cwd=str(root))
    if rc != 0:
        raise Refused(f"git tag failed on {oid[:7]}: {err.strip()} (is the merge commit fetched?)")
    rc, _, err = _git("push", "origin", tag, cwd=str(root))
    if rc != 0:
        raise Refused(f"the tag push was rejected: {err.strip()}")
    rc, out, _ = _git("ls-remote", "--tags", "origin", tag, cwd=str(root))
    if not out.strip():
        raise Refused(f"tag {tag} does not read back from origin: stop before creating the release")
    rc, out, err = _gh("release", "create", tag, "--notes-from-tag", cwd=str(root))
    if rc != 0:
        raise Refused(f"gh release create failed: {err.strip()} (the tag is on origin; create the release by hand)")
    _say(f"{tag} on {oid[:7]}, pushed; release created: {out.strip()}")
    _say("watch the publish run: gh run list --limit 3")
    return 0


# -------------------------------------------------------------------- main --

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ship.py", description=__doc__.split("\n\n", 1)[0])
    sub = parser.add_subparsers(dest="verb", required=True)
    sub.add_parser("preflight", help="clean tree, non-empty range, post-merge reds, the per-lane handoff notice")
    sub.add_parser("lane", help="on the default branch, move the unmerged commits to a lane")
    p_open = sub.add_parser("open", help="push once, open the pull request (marker bound), arm auto-merge")
    p_open.add_argument("--title", help="the pull request title (default: the head commit's subject)")
    p_open.add_argument("--body-file", help="the pull request body (default: the commit subjects)")
    p_open.add_argument("--dry-run", action="store_true")
    p_open.add_argument("--early", metavar="REASON",
                        help="ship before the handoff where handoff_push is on, saying why")
    p_open.add_argument(BASE_RED_RULED_FLAG, metavar="ACK_ID", dest="base_red_ruled",
                        help="land on a red base by the dispatcher's ruling: the ack with this id, on the "
                             "mail channel, names the red post-merge run")
    p_rebind = sub.add_parser("rebind", help="re-bind the title marker to the pull request's head")
    p_rebind.add_argument("--dry-run", action="store_true")
    sub.add_parser("catch-up", help="merge the base in (on the server when clean; locally, record files "
                                    "resolved by shape, when GitHub reads the lane CONFLICTING), re-arm the "
                                    "own-clear marker at the new head, re-bind")
    sub.add_parser("status", help="state, merge state, required reds (a lost runner's apart), auto-merge")
    p_rerun = sub.add_parser("rerun", help="re-run once the required cells a lost runner ended")
    p_rerun.add_argument("--dry-run", action="store_true")
    p_rel = sub.add_parser("release", help="after the merge: tag the merge commit, push it, create the release")
    p_rel.add_argument("tag")
    p_rel.add_argument("--dry-run", action="store_true")
    p_fold = sub.add_parser("fold", help="bring the parked Session Log rows in and prune past the slack: "
                                         "the step before a push `open` does not make")
    p_fold.add_argument("--dry-run", action="store_true")
    p_hand = sub.add_parser("handoff", help="/handoff's push: only when espalier.toml sets handoff_push = true")
    p_hand.add_argument("--title", help="the pull request title (default: the head commit's subject)")
    p_hand.add_argument("--body-file", help="the pull request body (default: the commit subjects)")
    p_hand.add_argument("--dry-run", action="store_true")
    p_hand.add_argument(BASE_RED_RULED_FLAG, metavar="ACK_ID", dest="base_red_ruled",
                        help="land on a red base by the dispatcher's ruling, as `open` takes it")
    p_arm = sub.add_parser("arm", help="arm the own-clear marker for this session by hand: after a lane opened "
                                       "by hand (gh pr create), a handoff whose arm did not run, or a pull by "
                                       "hand that moved HEAD under the armed marker (re-armed at HEAD)")
    p_arm.add_argument("--why", help="why it is armed by hand (recorded in the marker)")
    p_arm.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verb == "preflight":
            return preflight()
        if args.verb == "lane":
            return lane()
        if args.verb == "open":
            return open_pr(title=args.title, body_file=args.body_file, dry_run=args.dry_run,
                           early=args.early, base_red_ruled=args.base_red_ruled)
        if args.verb == "rebind":
            return rebind(dry_run=args.dry_run)
        if args.verb == "catch-up":
            return catch_up()
        if args.verb == "status":
            return status()
        if args.verb == "rerun":
            return rerun(dry_run=args.dry_run)
        if args.verb == "release":
            return release(args.tag, dry_run=args.dry_run)
        if args.verb == "fold":
            return fold(dry_run=args.dry_run)
        if args.verb == "handoff":
            return handoff(title=args.title, body_file=args.body_file, dry_run=args.dry_run,
                           base_red_ruled=args.base_red_ruled)
        if args.verb == "arm":
            return arm(why=args.why, dry_run=args.dry_run)
    except Refused as stop:
        print(f"ship: refused -- {stop}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    from _json_safe import pin_utf8_streams

    pin_utf8_streams()
    sys.exit(main())
