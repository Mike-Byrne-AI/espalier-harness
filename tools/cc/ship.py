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
                         merges' post-merge reds, and every refusal in the
                         one list of state checks `open` runs before its
                         push, in `open`'s words (PRE_PUSH_CHECKS: a red
                         base, a missing handoff row where handoff_push is
                         on, this seat's other open pull request, ...)
    lane                 on the default branch: move the unmerged commits to a
                         lane named from the lane's own newest subject, never
                         a merge's or a row's (a no-op elsewhere)
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
                         (.espalier-state/own_clear.json in the checkout the
                         session was started in, at its HEAD, where the mod
                         reads it), which the own-clear
                         mod a seat.py launch loads reads to clear and re-prime
                         the window; a held refusal rides the marker and the
                         lane to land first rides the brief
    arm [--why ...]      the same arm by hand, for a lane opened by hand
                         (gh pr create ran no verb): a clean tree, a lane on
                         origin; over a marker already armed for this session
                         it re-arms at HEAD when a pull by hand moved it (no
                         commit of the lane's own in the move), the brief
                         kept, and refuses otherwise

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
from typing import Callable, NamedTuple

# A kept, older sibling is named with its repair, never a traceback that names
# an attribute: an uncaught exception loads hooks/_start_refusal.py by path and
# hands it to that module's refuse_kept_siblings. The one text of this block,
# and why each line is there, is tests/test_kept_sibling.py's ARM_BLOCK.
if __name__ == "__main__":
    from types import TracebackType as _KeptTraceback

    _KEPT_FROM = Path(__file__).resolve().parent
    _KEPT_SCRIPT = Path(__file__).name
    _KEPT_BEFORE = sys.excepthook

    def _name_a_kept_sibling(kind: type[BaseException], exc: BaseException, tb: _KeptTraceback | None) -> None:
        sys.excepthook = _KEPT_BEFORE
        try:
            import importlib.util
            at = (_KEPT_FROM if _KEPT_FROM.name == "hooks" else _KEPT_FROM / "hooks") / "_start_refusal.py"
            spec = importlib.util.spec_from_file_location("_start_refusal_by_path", at)
            if spec is not None and spec.loader is not None:
                reader = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = reader
                spec.loader.exec_module(reader)
                refuse = getattr(reader, "refuse_kept_siblings", None)
                if callable(refuse):
                    reconfigure = getattr(sys.stderr, "reconfigure", None)
                    if callable(reconfigure):
                        reconfigure(encoding="utf-8", errors="replace")
                    refuse(_KEPT_SCRIPT)
        # fail-open: ok deliberate without the reader a kept sibling keeps its traceback, as before
        except Exception:  # noqa: BLE001, S110
            pass
        sys.excepthook(kind, exc, tb)

    sys.excepthook = _name_a_kept_sibling

# The driver prints paths and branch names, and a kept sibling's refusal names a
# file: both streams take UTF-8 here, inline, before any sibling is read, since
# the layer's pin lives in a sibling that may be the kept one.
if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

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
#: pushes). Declared in espalier/config.py::FOREIGN_KEYS. Read with the
#: stdlib's tomllib (:func:`handoff_push_setting`).
HANDOFF_PUSH_KEY = "handoff_push"

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
    the push never ran) or because this seat's other pull request is open
    (one open pull request per seat, DEF-5038); True, on origin, the push
    landed and a step after it refused (the head wait, the rebind, the pull
    request's creation or arming). ``waits_for`` names what a lane held here
    opens after, where that is not the base going green ('#41 merges').
    Any other refusal is the window's to fix first, and arms nothing
    (DEF-4057: three seats sat past the threshold for 17.5 h on 2026-10-29,
    their handoffs refused on a red base and no marker to clear them)."""

    def __init__(self, message: str, *, landed: bool, waits_for: str = "") -> None:
        super().__init__(message)
        self.landed = landed
        self.waits_for = waits_for


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


def head_sha(cwd: Path | None = None) -> str:
    rc, out, _ = _git("rev-parse", "HEAD", cwd=str(cwd) if cwd is not None else None)
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


# ------------------------------------------------------------ the lane's shape --

#: How many paths a shape line lists before it counts the rest.
SHAPE_LISTED = 8
#: The statuses a shape line counts first, in this order; any other after.
_SHAPE_ORDER = "AMD"


def lane_shape(root: Path, base: str) -> dict:
    """The lane's diff with ``origin/<base>`` read for its shape, not only its
    paths (DEF-4064: #380's head, re-parented onto the base's tip with an
    older tree, carried 17 deletions and three merges' code reverted, and was
    pushed like any other lane). ``{"counts": {status: n}, "deleted": [...],
    "driver": [...], "modified": [...]}``: ``deleted`` is every deletion the
    driver did not make itself, ``driver`` the ones it did (:func:`_driver_deletions`),
    ``modified`` every modified path. The read is the three-dot diff the pull
    request shows; a read that fails is a refusal, as the marker's is."""
    rc, out, err = _git("diff", "--name-status", "--no-renames", f"origin/{base}...HEAD", cwd=str(root))
    if rc != 0:
        raise Refused(f"git diff --name-status against origin/{base} failed: {err.strip()[:200]}")
    counts: dict[str, int] = {}
    deleted: list[str] = []
    modified: list[str] = []
    for line in out.splitlines():
        status, _tab, path = line.partition("\t")
        status, path = status.strip()[:1], path.strip().replace("\\", "/")
        if not status or not path:
            continue
        counts[status] = counts.get(status, 0) + 1
        if status == "D":
            deleted.append(path)
        elif status == "M":
            modified.append(path)
    driver = _driver_deletions(root, base, deleted) if deleted else set()
    return {"counts": counts, "deleted": [p for p in deleted if p not in driver],
            "driver": [p for p in deleted if p in driver], "modified": modified}


def _driver_deletions(root: Path, base: str, deleted: list[str]) -> set[str]:
    """Which of ``deleted`` the driver made itself: a Session Log row a commit
    of this lane deleted under :data:`PRUNE_SUBJECT` (the fold's cap, which
    ``open`` and ``handoff`` commit before the push), and a probe whose row the
    head holds struck (``ledger_row.py strike`` drops a closed row's probe: 115
    of the 200 merges before this carried one). Any other deletion, one a
    merge made among them (``git log`` lists no merge's paths), is the lane's
    to name with ``--allow-deletions``."""
    rc, out, err = _git("log", "--format=%x1e%s", "--name-only", "--no-renames", "--diff-filter=D",
                        f"origin/{base}..HEAD", cwd=str(root))
    if rc != 0:
        _note(f"the deletions' commits could not be read ({err.strip()[:200]}): the driver's own Session Log "
              "prune is not told apart from the lane's deletions")
    pruned: set[str] = set()
    for block in out.split("\x1e") if rc == 0 else []:
        subject, _nl, names = block.partition("\n")
        if subject.startswith(PRUNE_SUBJECT):
            pruned |= {n.strip().replace("\\", "/") for n in names.splitlines()
                       if n.strip().replace("\\", "/").startswith(SESSION_LOG_DIR)}
    ours = {p for p in deleted if p in pruned}
    fragments = _fragments_module()
    probes, rows = getattr(fragments, "PROBES_DIR", ""), getattr(fragments, "LEDGER_DIR", "")
    if not probes or not rows:
        return ours
    for path in deleted:
        folder, _slash, name = path.rpartition("/")
        if folder != probes or not name.endswith(".json"):
            continue
        rid = name[:-len(".json")]
        rc, row, _ = _git("show", f"HEAD:{rows}/{rid}.md", cwd=str(root))
        if rc == 0 and re.search(_STRUCK_ROW_RE.format(id=re.escape(rid)), row, re.M):
            ours.add(path)
    return ours


def _listed(paths: list[str]) -> str:
    shown = ", ".join(paths[:SHAPE_LISTED])
    return shown + (f" and {len(paths) - SHAPE_LISTED} more" if len(paths) > SHAPE_LISTED else "")


def _unclaimed_modified(root: Path, modified: list[str]) -> tuple[str, str, list[str] | None]:
    """``(seat, lane, unclaimed)``: the modified paths no claim this seat sent
    on the lane names (``mail.unclaimed_paths``), None where it sent none;
    ``("", "", None)`` where nothing is compared (an unnamed box, no channel, a
    channel that predates the read, a detached HEAD, mail git could not read),
    the reason said where there is one."""
    mail = _mail_module()
    reader = getattr(mail, "unclaimed_paths", None) if mail is not None else None
    if reader is None or not modified:
        return "", "", None
    seat, problem = seat_name(root)
    if not seat:
        if problem:
            _note(f"the lane's modified paths are not compared against its claims: {problem}")
        return "", "", None
    try:
        lane = current_branch()
        by_machine, _skipped = mail.read_mail(root)
        unclaimed = reader(by_machine, seat, lane, modified)
    except Refused:
        return "", "", None
    except Exception as exc:  # noqa: BLE001 -- fail-open with voice: an advisory read never stops a push
        _note(f"the lane's claims could not be read ({os_error_text(exc)}): its modified paths are not compared")
        return "", "", None
    return seat, lane, unclaimed


def say_lane_shape(root: Path, base: str, shape: dict) -> None:
    """The shape's lines: the counts, the driver's own deletions, and the
    modified paths no claim of this seat's on the lane names. The deletions
    the driver did not make are each caller's to say (a note in ``preflight``,
    the refusal in ``open``)."""
    counts = shape["counts"]
    order = [s for s in _SHAPE_ORDER if s in counts] + sorted(s for s in counts if s not in _SHAPE_ORDER)
    driver = shape["driver"]
    _say(f"the lane's diff with origin/{base}: " + (", ".join(f"{counts[s]} {s}" for s in order) or "empty")
         + (f" ({len(driver)} the driver's own: the Session Log prune, a struck row's probe)" if driver else ""))
    seat, lane, unclaimed = _unclaimed_modified(root, shape["modified"])
    if not seat:
        return
    if unclaimed is None:
        _say(f"no claim of {seat}'s names {lane}, so its {len(shape['modified'])} modified path(s) are not "
             "compared against one")
    elif unclaimed:
        _note(f"{len(unclaimed)} modified path(s) no claim of {seat}'s on {lane} names (a revert the lane "
              f"never made reads here; read `git diff origin/{base}...HEAD -- <path>`): {_listed(unclaimed)}")


def _deletions_refusal(shape: dict, base: str) -> str:
    deleted = shape["deleted"]
    return (f"the lane deletes {len(deleted)} file(s) against origin/{base} that no step of the driver deleted: "
            f"{_listed(deleted)}. A head moved onto a newer base with an older tree deletes what other lanes "
            f"added since: read `git diff --name-status origin/{base}...HEAD`, and where the deletions are the "
            f"lane's own (a removed file, a rename, which reads as a deletion here, a release's fold of the "
            f"changelog fragments), ship with {ALLOW_DELETIONS_FLAG} <why>")


def refuse_unmade_deletions(shape: dict, base: str, allow: str | None, branch: str = "") -> str:
    """The push's refusal on a deletion the driver did not make, unless
    ``allow`` (``--allow-deletions``) says why; the line the pull request's
    body records where it does, '' where nothing was deleted. A ``revert/``
    lane is let through with the deletions named, as the red-base refusal lets
    it through: a revert removes what the reverted merge added by
    construction, and it is the path a red base waits on."""
    deleted = shape["deleted"]
    if not deleted:
        return ""
    why = (allow or "").strip()
    if not why and is_revert_lane(branch):
        _note(f"a revert/ lane: its {len(deleted)} deletion(s) go through ({_listed(deleted)})")
        return f"Deletions of a revert: {', '.join(deleted)}"
    if not why:
        raise Refused(_deletions_refusal(shape, base))
    _note(f"shipping {len(deleted)} deletion(s) the driver did not make ({why}): {_listed(deleted)}")
    return f"Deletions allowed: {why} ({', '.join(deleted)})"


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

    Only the boolean ``true`` turns it on. Any other value reads as off and is
    named in ``how`` as TOML spells it, so a typo is visible instead of silently
    deciding; a key under a table is not the top-level setting, and a file
    tomllib cannot parse reads as off with the parser's message (the engine
    refuses that file too). ``_record_fragments._top_level_switch`` reads its
    two switches by the same contract (a test pins the two agreeing)."""
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
    import tomllib  # here, not at the top: the driver still imports below the floor, where the hooks say the floor
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return False, f"espalier.toml could not be parsed ({exc}), so {HANDOFF_PUSH_KEY} reads as off"
    if HANDOFF_PUSH_KEY in data:
        value = data[HANDOFF_PUSH_KEY]
        if isinstance(value, bool):
            return value, f"espalier.toml sets {HANDOFF_PUSH_KEY} = {_toml_spelling(value)}"
        return False, (f"espalier.toml sets {HANDOFF_PUSH_KEY} = {_toml_spelling(value)}, which is neither true "
                       "nor false, so it reads as off")
    under = _toml_table_holding(data, HANDOFF_PUSH_KEY)
    if under:
        return False, (f"espalier.toml sets {HANDOFF_PUSH_KEY} under [{under}], where it is not the "
                       "top-level setting, so it is off")
    # a top-level key one spelling away (`handoff-push`, `Handoff_Push`)
    near = next((k for k in data if k.replace("-", "_").lower() == HANDOFF_PUSH_KEY), "")
    if near:
        return False, f"espalier.toml sets {near}, not {HANDOFF_PUSH_KEY}, so it is off (the default)"
    return False, f"espalier.toml does not set {HANDOFF_PUSH_KEY}, so it is off (the default)"


def _toml_spelling(value: object) -> str:
    """``value`` as TOML spells it, so a message names what the file says: a
    string keeps its quotes (``"true"``), a number reads as itself (``1``).
    One of three copies, in ``ship.py``, ``_record_fragments.py`` and
    ``mail.py``, which load no sibling for it (a test pins them equal)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        import json  # here, not at the top: _record_fragments.py keeps it off its Session Log readers' path
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_spelling(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k} = {_toml_spelling(v)}" for k, v in value.items()) + "}"
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else str(value)


def _toml_table_holding(table: dict, key: str, path: str = "") -> str:
    """The dotted path of the first table below ``table`` that holds ``key``
    (a nested table, an array of tables or an inline table), or ``""``.
    One of three copies, in ``ship.py``, ``_record_fragments.py`` and
    ``mail.py``, which load no sibling for it (a test pins them equal)."""
    for name, value in table.items():
        here = f"{path}.{name}" if path else name
        for sub in value if isinstance(value, list) else [value]:
            if isinstance(sub, dict):
                found = here if key in sub else _toml_table_holding(sub, key, here)
                if found:
                    return found
    return ""


#: Where a handoff writes its row since the Session Log became one file per
#: row (``_record_fragments.SESSION_LOG_DIR``; pinned with the other copies).
SESSION_LOG_DIR = "memory/session-log.d/"
#: The subject the driver's own Session Log prune commits under
#: (:func:`_fold_session_log`, the cap after it), read back by
#: :func:`lane_shape`, which lets the prune's deletions through by it: a check
#: that refused every deletion would refuse the driver itself (DEF-4064).
PRUNE_SUBJECT = "chore(records): prune the Session Log to its cap of"
#: A row's file holding it struck: the strike drops a closed row's probe, so
#: a deleted probe whose row reads so at the head is the strike's (DEF-4064).
_STRUCK_ROW_RE = r"^\|\s*~~`{id}`~~"


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
            "To ship before it, pass --early \"<reason>\" to `open`, and --body-file <path> where espalier.toml "
            "names a dispatcher, which refuses a code lane's body of subjects alone (the handoff's row then parks on this "
            "seat's records ref, read by no banner until the next lane's push folds it, or, where the handoff "
            f"adds more than rows, is a second push on this lane); past {ROW_DEBT_CAP} lanes shipped since this "
            "seat's newest Session Log "
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
    return newest_red_verdict(runs)


def newest_red_verdict(runs: object) -> dict | None:
    """The newest of ``runs`` (gh's post-merge run rows, newest first) that
    reached a verdict, when that verdict is red; None for a green there, no
    verdict in the rows, or rows that are not a list. The one reading of the
    base's verdict: :func:`base_red_run` and the Stop hook's handoff gate,
    which makes its own capped gh read of the rows (DEF-4076), both read it."""
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


#: What one `gh pr list` row carries for this driver's readers (the red-base
#: refusal, the one-per-seat advisory, the row-debt read) and for the Stop
#: hook's handoff gate, which asks gh in this field set and hands the rows to
#: ``seat_open_prs`` (DEF-4058): the one home, so a reader that grows a field
#: finds it from both.
OPEN_PR_FIELDS = "number,headRefName,headRefOid,labels,autoMergeRequest"


def _open_prs(cwd: str) -> list[dict] | None:
    """Every open pull request's number, branch, head, labels and auto-merge
    state, for the red-base refusal, the one-per-seat advisory and the
    row-debt read; None when gh cannot say (the first two fail open on it: the
    refusal still stands on the red read itself; the debt reads it as unread,
    since a row riding this seat's open pull request is read from its head)."""
    try:
        rows = _gh_json("pr", "list", "--state", "open", "--limit", "50", "--json",
                        OPEN_PR_FIELDS, cwd=cwd)
    except Refused:
        return None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else None


#: The flag that lands a lane on a red base by the dispatcher's ruling, on
#: `open` and `handoff` alike; the refusal names it, with the run id the
#: ruling must name.
BASE_RED_RULED_FLAG = "--base-red-ruled"
#: The flag that pushes a lane deleting files the driver did not delete, on
#: `open` and `handoff` alike, with the reason the pull request's body records.
ALLOW_DELETIONS_FLAG = "--allow-deletions"
#: The flag that ships a lane's commit subjects alone as its body where the
#: driver refuses that (:func:`_default_body`), on `open` and `handoff` alike,
#: with the reason the pull request's body records.
SUBJECTS_BODY_FLAG = "--subjects-body"
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
#: The branch prefix of a lane that reverts a red base: Core Rule 15 lands it
#: first, so the red-base refusal, the deletion check, the one-per-seat hold
#: and the post-push arming each let it through (:func:`is_revert_lane`).
REVERT_PREFIX = "revert/"


def is_revert_lane(branch: str) -> bool:
    """Whether ``branch`` is a lane that reverts a red base, by its name: the
    one predicate this driver's sites and the Stop hook's handoff gate read
    (DEF-4076: the gate held a revert/ lane like any other)."""
    return str(branch or "").startswith(REVERT_PREFIX)


def lane_fix_forward_rulings(root: Path, branch: str, *, timeout: float | None = None) -> dict[str, str]:
    """The dispatcher's fix-forward rulings naming the lane ``branch``, on any
    red run: ``{run id: ack id}``, the newest ack where two rule one run, read
    from the mail channel's local refs with no fetch by the channel's own
    rule (``fix_forward_rulings``: an ack on the dispatcher's ref, under
    :data:`RULING_HEAD` with the run's id, naming the lane). The Stop hook's
    handoff gate asks it before its one gh read, so a lane no ruling names
    costs no gh call (DEF-4076). Empty where no channel is beside this
    script; the channel's own faults raise, the caller's to say."""
    mail = _mail_module()
    reader = getattr(mail, "fix_forward_rulings", None) if mail is not None else None
    if reader is None or not branch:
        return {}
    dispatcher, _how = mail.dispatcher_setting(root)
    by_machine, _skipped = (mail.read_mail(root) if timeout is None else mail.read_mail(root, timeout=timeout))
    runs = sorted({mail.ruling_run(m) for messages in by_machine.values() for m in messages} - {""})
    ruled: dict[str, str] = {}
    for run_id in runs:
        for entry in reader(by_machine, dispatcher, run_id):
            if entry.get("lane") == branch:
                ruled[run_id] = str(entry.get("id") or "")   # oldest first: the newest stands
    return ruled


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
    if is_revert_lane(branch):
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


def seat_name(root: Path, *, timeout: float | None = None) -> tuple[str, str]:
    """``(name, problem)``: this seat's name as the mail channel reads it
    (``git config espalier.machine``), with ``problem`` the channel's unread
    phrase where the read could not be made (a config git did not answer in
    time) and '' otherwise. ``("", "")`` for an unnamed box or a tree without
    the channel: not a seat, and nothing to attribute. ``timeout`` bounds the
    one git read (a hook passes what is left of its budget)."""
    mail = _mail_module()
    if mail is None:
        return "", ""
    machine, how = mail.machine_setting(root, timeout=timeout) if timeout is not None else mail.machine_setting(root)
    if machine:
        return str(machine), ""
    unread = getattr(mail, "MACHINE_UNREAD", None)  # a channel module from before the phrase has none
    return "", str(how) if unread and str(how).startswith(unread) else ""


def seat_open_prs(root: Path, branch: str, prs: list[dict], *,
                  timeout: float | None = None) -> tuple[str, list[str]]:
    """``(seat, ["#n (lane)", ...])``: this seat's open pull requests other
    than ``branch``'s, by the seat whose latest claim or release names each
    lane (``mail.lane_seats``, the board's own attribution). Every seat may
    push as one GitHub account, so the author cannot tell seats apart; the
    mail can. ``("", [])`` where the box is unnamed or the channel absent; a
    failed read, of the mail or of the box's name, is said and never stops
    the push. ``timeout`` bounds each git read (the name, the local mail refs);
    the Stop hook's handoff gate passes its own cap, this driver's verbs the
    channel's default."""
    if not any(str(r.get("headRefName") or "") != branch for r in prs):
        return "", []   # no other open pull request: nothing to attribute, no mail read
    try:
        mail = _mail_module()
        if mail is None:
            return "", []
        machine, problem = seat_name(root, timeout=timeout)
        if not machine:
            if problem:
                _note(f"this seat's machine name could not be read ({problem}), so its other open pull "
                      "requests were not checked (one open pull request per seat)")
            return "", []
        by_machine, _ = mail.read_mail(root, timeout=timeout) if timeout is not None else mail.read_mail(root)
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


def stale_base_read(root: Path, base: str, pr: dict) -> dict | str | None:
    """The read behind :func:`stale_base_line`, apart so a caller can key on
    the result: None where the up-to-date rule is on (GitHub holds a stale
    lane itself), the reason where a read failed, else
    ``_merge_rules.stale_base``'s result, whose ``near`` names each meeting."""
    head = str(pr.get("headRefOid") or "")
    branch = str(pr.get("headRefName") or "") or current_branch()
    try:
        rc, out, _ = _gh("api", _merge_rules.protection_endpoint(base), cwd=str(root), timeout=15.0)
        if _merge_rules.strict(rc, out):
            return None
        _git("fetch", "origin", base, branch, "--quiet", cwd=str(root))
        runs = _gh_json("run", "list", "--branch", branch, "--event", "pull_request", "--limit", "100",
                        "--json", "workflowName,createdAt,headSha,conclusion", cwd=str(root))
        rc, diff, err = _git("diff", "--name-only", "--no-renames", f"origin/{base}...{head}", cwd=str(root))
        if rc != 0:
            return f"stale-base check not read: git diff origin/{base}...{head[:7]} failed ({err.strip()[:120]})"
        return _merge_rules.stale_base(root, base_ref=f"origin/{base}",
                                       tested_when=_merge_rules.tested_at(runs, head),
                                       pr_paths=[ln for ln in diff.splitlines() if ln.strip()],
                                       pr_rev=head, run_=RUN)
    except Refused as exc:
        return f"stale-base check not read: {exc}"


def stale_base_line(root: Path, base: str, pr: dict) -> str:
    """The stale-base advisory for an open pull request, or "" when its green
    stands: the up-to-date rule is on (GitHub holds a stale lane itself), the
    base has not moved since the CI ran, or it moved away from this pull
    request's files and their imports (``_merge_rules.stale_base``). A read
    that fails is said."""
    result = stale_base_read(root, base, pr)
    if result is None or isinstance(result, str):
        return result or ""
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
                         ("commit", "--quiet", "-m", f"{PRUNE_SUBJECT} {cap}\n\n{trailer}\n",
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


def _unmoved_after_park(root: Path, since: str, number: object, err: str) -> str:
    """The note for a park whose move to ``since`` (``origin/<branch>``)
    failed: git's own reason, and where that head holds commits HEAD does not
    reach, that the push refuses below (:func:`_origin_ahead_refusal`) with
    what stands in the way first. The usual cause is an untracked file at a
    path those commits add, and the merge the refusal names fails on the same
    file, so the files to move are named from the trees -- ``reset --keep``
    names only the first, and an ignored file is overwritten, not refused
    (both read on git 2.39) -- before that merge."""
    why = " ".join(err.split())[:300] or "no reason printed"
    head = f"the rows are parked, but this branch could not be moved to {since} ({why})"
    ahead = _commits_head_lacks(since, str(root))
    if not ahead:
        return f"{head}: they ride the push onto #{number} as before"
    # -z on both reads: without it git quotes a non-ASCII or newline path in
    # the diff, and the quoted name never meets ls-files' raw one.
    rc, added, _ = _git("diff", "--name-only", "--no-renames", "--diff-filter=A", "-z", "HEAD", since,
                        cwd=str(root))
    incoming = {p for p in added.split("\0") if p} if rc == 0 else set()
    rc, others, _ = _git("ls-files", "--others", "--exclude-standard", "-z", cwd=str(root)) if incoming else \
        (1, "", "")
    # A file where a directory arrives, or one inside a directory where a
    # file arrives, stands in the way as much as the same path does.
    in_way = sorted(p for p in others.split("\0") if p and any(
        p == q or q.startswith(p + "/") or p.startswith(q + "/") for q in incoming)) if rc == 0 else []
    shown = ", ".join(in_way[:5]) + (f" and {len(in_way) - 5} more" if len(in_way) > 5 else "")
    first = f"move {shown} out of the way, then " if in_way else \
        "move what git's error above names out of the way, then "
    return (f"{head}. {since} holds {ahead} commit(s) this HEAD does not reach, so the push onto #{number} "
            f"refuses below: {first}run `git merge {since}` and `python tools/cc/ship.py handoff` again")


def _park_the_row(root: Path, base: str, *, dry_run: bool = False, branch: str | None = None,
                  pr: dict | None = None) -> bool:
    """A handoff that carries Session Log rows alone parks the rows it added on
    this seat's records ref (``mail.park``) instead of pushing them: the next
    lane's push, any seat's, folds them in. Two shapes. With no pull request
    open (``branch`` None), the lane already merged and nothing in its diff
    with ``origin/<base>`` is anything else: no pull request is opened for the
    row alone (seven such in two days before this). With one open for
    ``branch`` (``number``), the commits since ``origin/<branch>``, the pull
    request's head read fresh, are the rows: nothing is pushed onto it, so its
    running checks are not cancelled and restarted for a record. Two lanes are
    left to today's path: one that conflicts with its base, whose merge-first
    push the pull request needs to merge at all (a run that push cancels could
    not have landed it), and one whose base moved near its files since its CI
    ran (:func:`stale_base_read`'s meetings), whose push re-runs that CI on the
    combination, the catch-up the board's stale: line would ask for. A probe or
    a read that cannot answer parks, and says so. After the reset a marker
    bound to another head is re-bound (:func:`rebind`), as the push's end
    would have. Only rows added: a lane that edits or renames a row
    keeps today's path, so the change reaches a pull request (a park carries
    additions alone). The blob parked is the committed one (``HEAD:<path>``).
    Once every row is parked the branch moves back (``reset --keep``) to its
    merge base with the base, or to ``origin/<branch>``: the commits held
    nothing but those rows, now on origin's records ref, and a commit left
    ahead held the next SessionStart's catch-up on this lane, passed the
    --early question as a row of this lane's (both reviews), and read as
    unpushed to the Stop hook's handoff gate. Never the base's merge base with
    a pull request open: that would drop the lane's own commits. The dropped
    head is printed. True when parked. Any other lane, a seat with no name or
    one git could not read, a remote head that cannot be fetched, or a park
    origin refused, keeps today's path and says why; so does a reset to
    ``origin/<branch>`` that fails after the park, whose rows then ride the
    push as well, since a commit left ahead there would ask the Stop hook's
    handoff gate for a handoff each new row answers the same way. Where that
    head holds commits HEAD lacks, the push refuses instead, and the note
    names git's error, the untracked files in the way and the merge to run
    (:func:`_unmoved_after_park`)."""
    _git("fetch", "origin", base, "--quiet", cwd=str(root))
    since = f"origin/{base}"
    if branch is not None:
        # The pull request's head as origin holds it now: a stale tracking ref
        # would let a pushed commit read as one of the rows, or the reset land
        # behind origin.
        if _git("fetch", "origin", branch, "--quiet", cwd=str(root))[0] != 0:
            return False
        since = f"origin/{branch}"
    rc, out, _ = _git("diff", "--name-status", "--no-renames", f"{since}...HEAD", cwd=str(root))
    if rc != 0 or not out.strip():
        return False
    entries = [ln.split("\t", 1) for ln in out.splitlines() if ln.strip()]
    if any(len(e) != 2 or e[0].strip() != "A" or not e[1].replace("\\", "/").startswith(SESSION_LOG_DIR)
           for e in entries):
        return False
    added = [e[1].replace("\\", "/") for e in entries]
    pr = pr or {}
    number = pr.get("number")
    where = "opening a pull request for it" if branch is None else f"pushing it onto #{number}"
    if branch is not None:
        reasons = _merge_first_reasons(root, f"origin/{base}")
        if reasons:
            _say(f"the commits since {since} carry only Session Log rows, but the lane conflicts with "
                 f"origin/{base} ({', '.join(reasons)}): the base is merged in first and the rows ride that "
                 "push, which the pull request needs to merge at all")
            return False
        if reasons is None:
            _note(f"could not probe the merge with origin/{base} (git 2.38+ has `merge-tree --write-tree`): "
                  f"parking the rows; if #{number} reads DIRTY on GitHub, run catch-up")
        # A base that moved near the lane's files since its CI ran: the push
        # re-runs that CI on the combination, the catch-up the board's stale:
        # line would ask for, which cancels by design. Keyed on the read's
        # meetings; a read that failed parks, and the board stays the backstop.
        stale = stale_base_read(root, base, {**pr, "headRefName": branch})
        if isinstance(stale, dict) and stale.get("near"):
            near = "; ".join(stale["near"][:3]) + (f"; and {len(stale['near']) - 3} more"
                                                    if len(stale["near"]) > 3 else "")
            _say(f"the commits since {since} carry only Session Log rows, but {base} moved near #{number}'s "
                 f"files since its CI ran ({near}): the rows ride the push, which re-runs that CI on the "
                 "combination, as the board's stale: line would ask")
            return False
        if isinstance(stale, str):
            _note(f"{stale}; parking the rows, and the board's stale: line stays the backstop")
        elif isinstance(stale, dict) and stale.get("unread"):
            # The read ran and could not judge (no run on the head reached a
            # verdict, a base commit it could not place): it parks as a failed
            # read does, and says so.
            _note(f"stale-base check not read: {stale['unread']}; parking the rows, and the board's stale: "
                  "line stays the backstop")
    mail = _mail_module()
    if mail is None:
        _note(f"tools/cc/mail.py is not beside this script, so the row is not parked: {where}, as before")
        return False
    if dry_run:
        if branch is None:
            _say(f"dry-run: park {', '.join(added)} on this seat's records ref and move this branch back to its "
                 f"merge base with origin/{base}; no pull request")
        else:
            _say(f"dry-run: park {', '.join(added)} on this seat's records ref and move this branch to "
                 f"{since}, #{number}'s head; nothing pushed")
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
        _note(f"the row was not parked ({os_error_text(exc)}): {where}, as before")
        return False
    head = _git("rev-parse", "HEAD", cwd=str(root))[1].strip()
    if branch is not None:
        rc, target, _ = _git("rev-parse", "--verify", "--quiet", f"{since}^{{commit}}", cwd=str(root))
        target = target.strip() if rc == 0 else ""
        rc, _, err = _git("reset", "--keep", "--quiet", target, cwd=str(root)) if target else \
            (1, "", f"{since} could not be read")
        if rc != 0:
            # Parked, but the row's commit is still ahead: a park that returned
            # here would leave the Stop hook's handoff gate asking for a handoff
            # each new row would answer the same way. The rows ride the push
            # instead; the parked copy leaves the records ref once the base
            # holds it.
            _note(_unmoved_after_park(root, since, number, err))
            return False
        _say(f"Nothing pushed onto #{number}: the commits since {since} carry only Session Log rows, now "
             f"parked on this seat's records ref, so its running checks are not restarted for a record. The "
             f"next lane's push, any seat's, folds them into {base}; until then the banner's recent rows, "
             f"which read the tree, show them to no seat, this one's next session included.")
        _say(f"This branch is at {since} ({target[:7]}), #{number}'s head; the row's commit, {head[:7]}, is "
             f"on the records ref (and in this checkout's reflog).")
        # A marker bound to another head: an update-branch made outside
        # catch-up, or an earlier re-bind that refused. The push this park
        # replaces ended in a re-bind; the park makes it where one is owed.
        title = str(pr.get("title") or "")
        if _MARKER_RE.search(title) and bind(title, target) != title.rstrip():
            try:
                if rebind() != 0:
                    _note(f"#{number}'s re-bind did not finish: run `python tools/cc/ship.py rebind`")
            except Refused as exc:
                _note(f"#{number}'s marker names another head and the re-bind refused ({exc}): run "
                      "`python tools/cc/ship.py rebind`")
        return True
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


_PLAN = None


def _plan_module():
    """``execution_plan.py`` beside this script, loaded by path on the
    unfinished handoff's first need of it (the demotion of a plan in
    progress); None where it is not here or will not load (a fixture copying
    a subset of tools/cc, a kept older copy), which that handoff refuses on
    before anything moves."""
    global _PLAN
    if _PLAN is None:
        path = Path(__file__).resolve().parent / "execution_plan.py"
        if not path.is_file():
            return None
        import importlib.util
        spec = importlib.util.spec_from_file_location("_ship_execution_plan", path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_ship_execution_plan"] = module  # registered before exec (3.14)
        try:
            spec.loader.exec_module(module)
        except Exception:  # noqa: BLE001 -- fail-open with voice: the unfinished handoff names the missing demotion and refuses
            sys.modules.pop("_ship_execution_plan", None)
            return None
        _PLAN = module
    return _PLAN if callable(getattr(_PLAN, "demote_plan", None)) else None


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


#: Where a drive or a test points the mod at a marker (``register.ts::repoRoot``
#: reads it first); read first here too, so the two never disagree.
OWN_CLEAR_ROOT_ENV = "ESPALIER_OWN_CLEAR_ROOT"


def _same_checkout(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))
    except OSError:
        return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _git_common_dir(checkout: Path) -> Path | None:
    rc, out, _ = _git("rev-parse", "--git-common-dir", cwd=str(checkout))
    return (checkout / out.strip()) if rc == 0 and out.strip() else None


def own_clear_checkout(root: Path) -> tuple[Path, str | None]:
    """``(the checkout the session's own-clear mod reads the marker in, a note
    or None)``. The mod (``register.ts::repoRoot``) reads
    :data:`OWN_CLEAR_ROOT_ENV`, else the top of the directory the session was
    started in, and holds the clear while that checkout's HEAD is not the
    marker's ``head``; this verb runs in ``root``, which is another checkout
    when a session hands off a lane from a linked worktree of its clone
    (DEF-5046: the dispatcher's window sat uncleared after #402's handoff from
    one). So: the variable, else this session's entry in Claude Code's
    session registry (``checkout_sync.live_sessions``, matched by
    ``caller_entry``: the exported id, then the exported window pid, then
    the nearest registered ancestor, so a registry still carrying the id
    from before a clear places the window by its pid), its directory's top,
    when that is a checkout of this clone; else ``root``, with the note
    saying why where the registry could not place the session or placed it
    outside this clone. A test process run inside a live seat has that
    seat as an ancestor: the same-clone rule is what keeps a scratch
    repository's case off the live checkout."""
    given = os.environ.get(OWN_CLEAR_ROOT_ENV, "").strip()
    if given:
        return Path(given), None
    fallback = "so it is armed in this checkout; a window started in another needs /clear by hand"
    try:
        sync = _sync_module()
        sessions = sync.live_sessions() if sync is not None else None
        sid = os.environ.get(SESSION_ID_ENV, "").strip()
        # A kept older checkout_sync cannot say a process table that did not answer.
        find = getattr(sync, "find_caller", None)
        entry, read = ((find(sessions, sid) if find is not None else (sync.caller_entry(sessions, sid), True))
                       if sessions is not None else (None, True))
    except Exception as exc:  # noqa: BLE001 -- fail-open with voice: the note rides the arm's line
        return root, f"the session registry could not be read ({os_error_text(exc)}), {fallback}"
    if sync is None:
        return root, f"tools/cc/checkout_sync.py is not beside this script, {fallback}"
    if sessions is None:
        return root, f"Claude Code's session registry could not be read in full, {fallback}"
    if entry is None:
        why = "Claude Code's session registry does not list this session" if read else sync.TABLE_UNREAD
        return root, f"{why}, {fallback}"
    started = Path(str(entry.get("cwd")))
    try:
        rc, out, _ = _git("rev-parse", "--show-toplevel", cwd=str(started))
        top = Path(out.strip()) if rc == 0 and out.strip() else None
        if top is None or _same_checkout(top, root):
            mine = theirs = None
        else:
            mine, theirs = _git_common_dir(root), _git_common_dir(top)
    except Refused as exc:   # the directory is gone, or git would not start there
        return root, f"the checkout this session was started in ({started}) could not be read ({exc}), {fallback}"
    if top is None:
        return root, f"the directory this session was started in ({started}) is in no git checkout, {fallback}"
    if _same_checkout(top, root):
        return root, None
    if mine is None or theirs is None or not _same_checkout(mine, theirs):
        return root, f"this session was started in {top}, which is not a checkout of this clone, {fallback}"
    return top, None


def _window_checkout_holds(where: Path, *, with_plan: bool = True) -> str | None:
    """Why the session's own checkout ``where`` must not be armed from
    another checkout, or None: commits origin does not hold (a lane of its
    own, unpushed: the Stop hook's handoff gate reads a marker armed at that
    HEAD as the lane handed off, and the mod, which never counts unpushed
    commits, would clear past it; :func:`_commits_off_origin`, DEF-2042), a
    tracked edit, or a plan in progress (the mod holds the clear on either,
    so a line promising one would be false). The handoff and ``arm`` read it
    the same way; the unfinished handoff reads it with ``with_plan=False`` before
    anything moves, since it sets that checkout's plan aside itself."""
    ahead = _commits_off_origin(where)
    if isinstance(ahead, str):
        return f"its unpushed commits could not be counted ({ahead})"
    if ahead:
        return (f"it holds {ahead} commit{'s' if ahead != 1 else ''} origin does not have, a lane of its own that a "
                "marker there would clear past (hand that lane off first)")
    rc, out, _ = _git("status", "--porcelain", "-uno", cwd=str(where))
    if rc != 0:
        return "its tree could not be read (git status failed there)"
    if out.strip():
        return "it has a tracked edit, and the mod holds the clear on it"
    if not with_plan:
        return None
    try:
        plan = json.loads((where / "cc" / "execution_plan.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):  # fail-open: ok deliberate -- no plan file, or one that does not parse: the mod reads that as nothing in progress too
        return None
    if isinstance(plan, dict) and plan.get("status") == "in_progress" and plan.get("steps"):
        return "a plan is in progress there, and the mod holds the clear on it"
    return None


#: The first words of the brief's tail after a handoff that did not land: the
#: re-primed window lands the lane before any new job (DEF-4057).
LAND_FIRST = "THE HANDOFF DID NOT LAND THIS LANE."

#: The first words of the brief's tail after the handoff of an unfinished lane
#: (:func:`_hand_off_unfinished`): the re-primed window finishes the lane
#: before any new job (DEF-4104).
FINISH_FIRST = "THE HANDOFF LEFT THIS LANE UNFINISHED."

#: The handoff's flag for a lane its window cannot finish, and the subject of
#: the one commit it makes of the lane's tracked edits, which the next window
#: takes back with a soft reset.
UNFINISHED_FLAG = "--unfinished"
UNFINISHED_SUBJECT = "chore(lane): set the unfinished lane's edits aside at the threshold"

#: The trailer that commit carries, valued with the lane's branch: every push
#: of the lane refuses while ``origin/<base>..HEAD`` holds a commit with it
#: (:func:`_unfinished_on_lane`), so the set-aside edits never ride a push.
UNFINISHED_TRAILER = "Espalier-Unfinished"

#: The read of that trailer over the lane's commits: a record per commit, its
#: sha and parents before the trailer's value (empty on any other commit).
UNFINISHED_LOG_FORMAT = f"%x1e%H %P%x1f%(trailers:key={UNFINISHED_TRAILER},valueonly)"

#: How many untracked file names the brief and the line show before a count.
UNFINISHED_UNTRACKED_SHOWN = 8

#: The opening of the marker's ``outcome`` after the handoff of an unfinished
#: lane: the prompt router keys the held clear's verb on it
#: (task_router._UNFINISHED_OUTCOME; tests/test_own_clear.py pins the two).
UNFINISHED_OUTCOME = "left unfinished: "

#: The commit body's lines that carry the set-aside plan's record and task,
#: read back by a second run whose plan is already in the cold store.
UNFINISHED_PLAN_LINE = "Plan set aside: "
UNFINISHED_TASK_LINE = "Plan task: "


class Unfinished(NamedTuple):
    """What the handoff of an unfinished lane left, for the brief that names
    it to the next window: the lane, what is left of it in the window's
    words, the set-aside commit and its parent, the set-aside plan's record
    (named from the root, or whole where the session's checkout is not the
    lane's) and its task (empty where none was in progress), the untracked
    files left beside it, whether the commit is empty (the tracked tree
    was clean: it carries the trailer alone, so the push guard still holds),
    whether the lane's branch is on origin (its remote-tracking ref, as
    last fetched: a pull request may then be open on it), and whether this
    tree's Harness Guard fails a pull request holding the commit
    (:func:`_guard_fails_unfinished`)."""
    branch: str
    text: str
    commit: str
    parent: str
    plan_record: str
    plan_task: str
    untracked: tuple[str, ...]
    empty: bool = False
    on_origin: bool = False
    guarded: bool = False


#: The name the Harness Guard's gate (``tools/cc/ci_guard.py``) defines where
#: it fails a pull request holding the set-aside commit (DEF-5102): its copy
#: of :data:`UNFINISHED_TRAILER`, pinned equal by tests/test_ci_guard.py.
UNFINISHED_GUARD_NAME = "_CI_UNFINISHED_TRAILER"


def _guard_fails_unfinished(root: Path) -> bool:
    """Does this tree's Harness Guard fail a pull request holding the
    set-aside commit? Read from the tree, offline: the workflow is there and
    its gate carries the arm (:data:`UNFINISHED_GUARD_NAME`). An install-ci
    tree from before the arm keeps its older gate (``upgrade`` never refreshes
    it), and an init-only tree has no gate: there nothing checks a hand push.
    Whether ``verify`` is a required check is GitHub's to say, not the
    tree's, so the brief names that condition rather than claim it."""
    workflow = root / ".github" / "workflows" / "harness-guard.yml"
    gate = root / "tools" / "cc" / "ci_guard.py"
    try:
        # The workflow runs the gate: an adopter's own harness-guard.yml, with
        # espalier's parked beside it as .new, may never run it.
        return (workflow.is_file() and "tools/cc/ci_guard.py" in workflow.read_text(encoding="utf-8",
                                                                                     errors="replace")
                and UNFINISHED_GUARD_NAME in gate.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False


def _brief_text(text: str) -> str:
    """A refusal's text as the brief may carry it: 7-bit ASCII (anything else
    becomes ``?``), no double quote and no percent -- the rules every brief
    keeps (tests/test_seat.py pins them on the composed one; a Windows
    PowerShell 5.1 launch line splits at a double quote and cmd.exe expands a
    percent). The marker's brief is submitted as a prompt, never typed, but
    one rule for every brief is the one that stays pinned."""
    folded = text.encode("ascii", "replace").decode("ascii")
    return folded.replace('"', "'").replace("%", " pct")


def _land_first_tail(held: Held, branch: str, lane_checkout: Path | None = None) -> str:
    """What the re-primed window reads after its role brief when the handoff
    did not land: the refusal, where the lane waits, and the verbs that land
    it. The row is written and the tree clean (the handoff refused before
    this otherwise), so the next window's first job is the lane, not a new
    one. ``lane_checkout`` is the lane's checkout when it is not the one the
    window was started in (DEF-5046): the tail names it, since the verbs run
    there."""
    if held.landed:
        what = "The push landed and a step after it refused"
    else:
        what = "The push was held" if held.waits_for else "The push was refused"
    lane = _brief_text(branch)
    if lane_checkout is None:
        where = (f"The lane {lane} is on origin" if held.landed
                 else f"The lane {lane} is committed in this checkout and unpushed")
    else:
        spot = _brief_text(str(lane_checkout))
        where = (f"The lane {lane} is on origin, its checkout {spot}" if held.landed
                 else f"The lane {lane} is committed in {spot} and unpushed") + " (run the verbs below there)"
    waits = _brief_text(held.waits_for) if held.waits_for else "the base is green"
    # A lane held behind the seat's other pull request is opened before a new
    # job is begun: a new branch drops the Stop hook's hold on this one, the
    # one mechanical reminder left after the clear (DEF-5038).
    branch_note = (" (stay on this branch until then: a new branch drops the Stop hook's hold on it, which "
                   "asks for the lane once that pull request is gone)") if held.waits_for else ""
    if held.waits_for and lane_checkout is not None:
        # The Stop hook's hold is written in the lane's checkout, and this
        # window's hooks read their own: nothing there asks for the lane.
        branch_note = (f" (no hook in this window watches {_brief_text(str(lane_checkout))}: this brief is the "
                       "one reminder of the lane)")
    return (f"\n\n{LAND_FIRST} {what}: {_brief_text(str(held))}\n"
            f"{where}, its row written and the tree clean; the window that handed off is done with it, and "
            "this one lands it before any new job: python tools/cc/ship.py status says what is on origin; "
            f"with no pull request yet, python tools/cc/ship.py open once {waits} (the board, "
            f"/inbox board, says when){branch_note}; after a push that landed, python tools/cc/ship.py rebind, "
            "or the command the refusal above names (auto-merge that did not arm is armed by hand).")


def _soft_reset_words(commit: str, parent: str, *, empty: bool = False) -> str:
    """The one move that takes back the set-aside edits, guarded by the HEAD
    it is right for: a soft reset to the commit's parent, run only while HEAD
    is that commit (a reset from elsewhere would take back other work). An
    empty commit holds the trailer alone, and the reset drops it."""
    if empty:
        return (f"while HEAD is {commit[:12]}, git reset --soft {parent[:12]} drops it (it holds no edits: "
                "the tracked tree was clean, and it carries the trailer alone)")
    return (f"while HEAD is {commit[:12]}, git reset --soft {parent[:12]} takes back the tracked edits it "
            "set aside")


def _restore_words(record: str) -> str:
    """The command that puts a set-aside plan back, spelled with the
    interpreter this host resolves (DEF-383a: a bare name is not on every
    host); where none clears the floor the script is named alone, with why."""
    hint = _shared_reader("python_command_hint")
    word = hint() if hint is not None else ""
    if word:
        return f"{word} tools/cc/execution_plan.py restore {record}"
    return (f"tools/cc/execution_plan.py restore {record} (run by a Python the harness supports; none was "
            "found here to name)")


def _finish_first_tail(unfinished: Unfinished, lane_checkout: Path | None = None) -> str:
    """What the re-primed window reads after its role brief when the handoff
    left a lane unfinished (:func:`_hand_off_unfinished`): what is left, where
    the lane waits (here, its claims and job live; unpushed with no pull
    request, or, where its branch is on origin, with a pull request perhaps
    open on it, which a hand push would land the set-aside edits on, so the
    soft reset comes before any push), and the moves that give it back as
    it was -- the soft reset of the
    set-aside commit, named by its sha and parent, and the restore of the
    set-aside plan -- before the lane's own procedure resumes. ``lane_checkout``
    is the lane's checkout when it is not the one the window was started in
    (DEF-5046): the tail names it."""
    lane = _brief_text(unfinished.branch)
    spot = "this checkout" if lane_checkout is None else _brief_text(str(lane_checkout))
    # The plan was set aside in the session's own checkout, which this window
    # starts in; the soft reset is the lane checkout's.
    there = "" if lane_checkout is None else " (run the soft reset there; the restore runs from this checkout)"
    moves = []
    hand_push = ("a hand git push skips the driver, and the Harness Guard check then fails the pull request, "
                 "which holds its merge where verify is a required check, until a force push takes the commit off"
                 if unfinished.guarded else
                 "a hand git push skips the driver, and nothing in this tree checks it")
    if unfinished.commit:
        moves.append(_soft_reset_words(unfinished.commit, unfinished.parent, empty=unfinished.empty)
                     + f" (every ship-driver push of the lane -- open, handoff, catch-up, rebind -- refuses while "
                       f"its {UNFINISHED_TRAILER} commit is on it; {hand_push}, so never push it by hand)")
    else:
        moves.append("no commit was made")
    if unfinished.plan_record:
        moves.append(f"{_brief_text(_restore_words(unfinished.plan_record))} puts back the plan it set aside "
                     f"({_brief_text(unfinished.plan_task)})")
    if unfinished.untracked:
        shown = ", ".join(_brief_text(name) for name in unfinished.untracked[:UNFINISHED_UNTRACKED_SHOWN])
        more = len(unfinished.untracked) - UNFINISHED_UNTRACKED_SHOWN
        moves.append(f"{len(unfinished.untracked)} untracked file(s) sit beside it, uncommitted: {shown}"
                     + (f" and {more} more" if more > 0 else ""))
    # The seat's own red pull request is the likely lane at the threshold, and
    # the red-cell recipe is fix, commit, git push, then rebind: a hand push
    # lands the set-aside edits on the open pull request before rebind refuses.
    landing = ("where the Harness Guard check fails on them (auto-merge merges them on the required checks' green "
               "where verify is not one of them)" if unfinished.guarded else
               "where auto-merge merges them on green (nothing in this tree checks them)")
    waits = (f"The lane {lane} is committed in {spot}, and its branch is on origin (as last fetched), so a pull "
             "request may be open on it: a hand git push there lands the set-aside edits on that pull request, "
             f"{landing} and only a force push takes them off, so soft-reset first, before any push; its row is "
             "written" if unfinished.on_origin else
             f"The lane {lane} is committed in {spot} and unpushed, with no pull request, its row written")
    return (f"\n\n{FINISH_FIRST} What is left: {_brief_text(unfinished.text)}\n"
            f"{waits}; its claims and its job stay live{there}. Stay on this branch until the lane is "
            "finished, and switch "
            "back to it first if this window starts on another: nothing but this brief names it, and a red "
            "pull request on another lane is worked before the soft reset below, not after (staged edits ride "
            "a branch switch). The window that handed off had no room left to finish it; this one finishes it "
            "before any new job, through its full procedure and its own landing (/handoff opens it): first, "
            + "; ".join(moves) + ".")


#: The mod's own first line for a window with no role brief (register.ts
#: GENERIC_BRIEF says the same; tests/test_own_clear.py pins the two by
#: phrase). It rides before a held tail, so a window with no seat name still
#: hears that its loop survived the clear.
GENERIC_BRIEF = ("The previous session handed off and this window was cleared by the own-clear. Orient from "
                 "the banner and read live state before you state it. A loop that was running survived the "
                 "clear: start no second one.")


def arm_own_clear_here(root: Path, *, held: Held | None = None, by_hand: str | None = None,
                       unfinished: Unfinished | None = None) -> str:
    """Arm the marker for the session this shell belongs to: the id Claude
    Code exports (:data:`SESSION_ID_ENV`), HEAD, and the seat's re-prime brief
    -- with, after a handoff that did not land (``held``), the refusal in the
    marker and the lane to land first appended to the brief (an unnamed seat's
    window reads it after the mod's generic line); after the handoff of an
    unfinished lane (``unfinished``), the lane to finish appended the same
    way; or, from the ``arm`` verb,
    why it was armed by hand. Only where :func:`_own_clear_gate` lets it:
    elsewhere nothing is armed and the reason is the line."""
    why_not = _own_clear_gate()
    if why_not:
        return why_not
    session_id = os.environ[SESSION_ID_ENV].strip()
    # The window's facts (where its mod reads, its HEAD, its seat's brief) are
    # the session's checkout's; the lane's (its branch, the refusal) are root's.
    where, unplaced = own_clear_checkout(root)
    elsewhere = not _same_checkout(where, root)
    if elsewhere:
        hold = _window_checkout_holds(where)
        if hold:
            return (f"own-clear not armed: {where}, the checkout this session's mod reads, {hold}; this window "
                    "needs a /clear by hand once that is settled, or python tools/cc/ship.py arm then")
    seat, role, role_brief, how = _reprime_brief(where)
    brief, landed, outcome = role_brief, True, None
    if held is not None:
        landed, outcome = held.landed, str(held)
        try:
            branch = current_branch()
        except Refused:
            branch = "(its branch could not be read)"
        brief = (role_brief or GENERIC_BRIEF) + _land_first_tail(held, branch, lane_checkout=root if elsewhere else None)
    elif unfinished is not None:
        landed, outcome = False, f"{UNFINISHED_OUTCOME}{unfinished.text}"
        brief = (role_brief or GENERIC_BRIEF) + _finish_first_tail(unfinished,
                                                                   lane_checkout=root if elsewhere else None)
    elif by_hand:
        outcome = f"armed by hand: {by_hand}"
    line = arm_own_clear(where, session_id=session_id, head=head_sha(where), seat=seat, role=role, brief=brief,
                         landed=landed, outcome=outcome)
    if elsewhere:
        line += f" (armed in {where}, where this session's mod reads it, at its HEAD; the lane is in {root})"
    elif unplaced:
        line += f" ({unplaced})"
    if held is not None:
        line += ("; with the refusal in its brief: this window is done with the lane, and the next window "
                 "lands the lane first")
    elif unfinished is not None:
        line += "; with the lane to finish in its brief: the next window finishes it before any new job"
    elif by_hand:
        line += f" (by hand: {by_hand})"
    if role_brief is None:
        line += (f"; no brief of its own rides it ({how}), so the mod re-primes with "
                 + ("its generic line and the lane to land" if held is not None or unfinished is not None
                    else "its own line"))
    return line


#: Why the lane's push state is unread where the shared reading is not beside
#: this script (:func:`_lane_upstream`).
_LANE_UPSTREAM_UNREAD = ("tools/cc/hooks/_hook_utils.py is not beside this script, does not load, or is an "
                         "older one without lane_upstream; espalier upgrade --execute . brings it level")
#: The same where the off-origin reading is not beside it (:func:`_commits_off_origin`).
_OFF_ORIGIN_UNREAD = ("tools/cc/hooks/_hook_utils.py is not beside this script, does not load, or is an "
                      "older one without commits_off_origin; espalier upgrade --execute . brings it level")


def _shared_reader(name: str):
    """The shared ``_hook_utils`` reader ``name`` beside this script, or None
    (a kept, older ``_paths.py`` or ``_hook_utils.py``, a fixture copying a
    subset of tools/cc): each caller says so, and no copy of the rule stands in."""
    loader = getattr(_paths, "hooks_module", None)   # a kept, older _paths.py: unread
    return getattr(loader("_hook_utils"), name, None) if loader else None


def _git_ask(root: Path):
    """``ask(*args)`` as the shared readers take it: ``git <args>`` at
    ``root``, its stdout stripped on exit 0, None on any other exit."""
    def ask(*args: str) -> str | None:
        rc, out, _ = _git(*args, cwd=str(root))
        return out.strip() if rc == 0 else None

    return ask


def _lane_upstream(root: Path, branch: str) -> tuple[str | None, bool] | None:
    """``_hook_utils.lane_upstream`` at ``root``: ``(upstream, own)``, the ref
    the lane's unpushed commits are counted against and whether it is the
    lane's own remote branch, read where the Stop hook's handoff gate reads it,
    so the two cannot disagree on whether a lane is a seat's second (DEF-4081).
    None where that reader is not beside this script: each caller says so
    (``_LANE_UPSTREAM_UNREAD``)."""
    reading = _shared_reader("lane_upstream")
    return None if reading is None else reading(_git_ask(root), branch)


def _commits_off_origin(root: Path) -> int | str:
    """The commits HEAD holds that no ref of origin does, by
    ``_hook_utils.commits_off_origin`` at ``root`` (DEF-2042: ``@{u}`` names
    what the branch tracks, not what origin holds), the one reading the
    by-hand arm (:func:`_lane_not_on_origin`) and the window check
    (:func:`_window_checkout_holds`) share; where it cannot be read, a word
    saying why."""
    reading = _shared_reader("commits_off_origin")
    if reading is None:
        return _OFF_ORIGIN_UNREAD
    count = reading(_git_ask(root))
    return "git could not count them" if count is None else count


def _lane_not_on_origin(root: Path) -> str | None:
    """Why HEAD is not on origin, or None when it is: every commit of HEAD on
    some ref of origin (:func:`_commits_off_origin`: a lane pushed with or
    without ``-u``, or merged and pruned, whose ``@{u}`` git reads as gone,
    DEF-2042); else no upstream (the lane was never pushed), commits the
    upstream lacks, or a push state that could not be read. The upstream is
    the lane's own remote branch wherever origin holds one, a push without
    ``-u`` included (:func:`_lane_upstream`, DEF-4086).
    The by-hand arm clears a window only over a lane that is on origin:
    a handoff refused for a reason the window must fix first (a lane behind
    its remote, a rejected push) could otherwise be cleared past with the
    plain role brief, the lane left unpushed and unmentioned (the failure-mode
    review, 2026-10-30)."""
    if _commits_off_origin(root) == 0:
        return None
    rc, branch, _ = _git("branch", "--show-current", cwd=str(root))
    reading = _lane_upstream(root, branch.strip() if rc == 0 else "")
    if reading is None:
        return f"the push state could not be read ({_LANE_UPSTREAM_UNREAD})"
    upstream = reading[0]
    if not upstream:
        return "HEAD has no upstream: the lane was never pushed"
    rc, count, _ = _git("rev-list", "--count", f"{upstream}..HEAD", cwd=str(root))
    if rc != 0 or not count.strip().isdigit():
        return f"the push state against {upstream} could not be read"
    ahead = int(count.strip())
    if ahead:
        return f"HEAD holds {ahead} commit{'s' if ahead != 1 else ''} that {upstream} does not"
    return None


def _read_own_clear(root: Path) -> dict | None:
    """The marker's record as it is on disk, whatever its state and session;
    None for a missing or unreadable one."""
    try:
        marker = json.loads((root / STATE_DIR / OWN_CLEAR_MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return marker if isinstance(marker, dict) else None


def _own_clear_marker(root: Path) -> dict | None:
    """The marker's record when it is armed for this shell's session, else
    None: a missing or unreadable marker, another session's, or one the mod
    has consumed or marked stale."""
    marker = _read_own_clear(root)
    if (marker is not None and marker.get("state") == "armed"
            and marker.get("session_id") == os.environ.get(SESSION_ID_ENV, "").strip()):
        return marker
    return None


def _armed_for_this_session(root: Path) -> str | None:
    """When the marker is armed for this shell's session, its ``written_at``
    (or ``earlier``); else None, a missing or unreadable marker included."""
    marker = _own_clear_marker(root)
    return None if marker is None else str(marker.get("written_at") or "earlier")


def rearm_own_clear_after_move(root: Path, *, by: str, moved_from: str | None = None,
                               refusal: str | None = None, why: str | None = None) -> str | None:
    """After a verb moved HEAD under a marker armed for this session with
    nothing left to hand off, rewrite the marker's ``head`` to HEAD with every
    other field kept (the brief, how the handoff ended, and the record the
    mod writes: a refusal's count is what the banner's Own-clear: line and
    the prompt router read) and the move on the record (``rearmed_from``,
    ``rearmed_by``, ``rearmed_at``, and ``rearmed_why`` from ``why``). The
    callers: the catch-up after its pull of the server's merge or its own
    record merge once pushed, with ``moved_from`` the HEAD it started from --
    the marker must have been armed there, else a commit after the handoff
    moved HEAD first, that handoff (which re-arms) is owed, and the marker
    stays (the review's case: a re-arm over it would clear the window with no
    row for the commit); and ``arm`` after a pull by hand, which tests the
    move itself first (:func:`_lanes_own_commits_in`). A refusal a step after
    the move raised rides the brief (``refusal``), so the window the mod
    clears hands it on instead of clearing over it. The line that says so;
    None when no marker is armed for this session or its head is HEAD
    already; a marker armed for another session at ``moved_from`` is a line
    naming it, since only its window can re-arm it. HEAD is read before the
    marker, so nothing runs between the marker's read and its write. The mod
    holds the clear on ``HEAD moved since the handoff``, and a pull leaves
    nothing to hand off: until this the hold stood until a re-arm by hand
    (air-work's window sat held for 3 h 33 min on 2026-10-31 after its tick's
    catch-up). The marker and the HEAD it follows are the session's checkout's
    (:func:`own_clear_checkout`): a move in another checkout of the clone, the
    lane's worktree, leaves that HEAD where it was, so nothing is re-armed."""
    if _own_clear_gate():
        return None   # no mod in this window, so this session armed nothing to follow
    where, _unplaced = own_clear_checkout(root)   # the first arm said an unplaced session; a re-arm follows it
    if moved_from is not None and not _same_checkout(where, root):
        return None   # the move was the lane's checkout's; the window's HEAD, which the marker follows, is not
    head = head_sha(where)
    raw = _read_own_clear(where)
    if raw is None or raw.get("state") != "armed":
        return None
    was = str(raw.get("head") or "")
    if was == head:
        return None
    if raw.get("session_id") != os.environ.get(SESSION_ID_ENV, "").strip():
        if moved_from is not None and was == moved_from:
            return (f"the own-clear marker armed for session {str(raw.get('session_id') or '?')[:8]} at {was[:7]} "
                    "was not re-armed (this shell is not its session): python tools/cc/ship.py arm, run in that "
                    f"window, re-arms it at {head[:7]}")
        return None
    if moved_from is not None and was != moved_from:
        return (f"the own-clear marker stays armed at {was[:7] or '?'}: HEAD had moved from it before this {by} "
                "(a commit after the handoff owes one, and that handoff re-arms the marker; the mod holds the "
                "clear until it runs)")
    marker = dict(raw)
    marker.update({"head": head, "rearmed_from": was or None, "rearmed_by": by,
                   "rearmed_at": datetime.now(timezone.utc).isoformat()})
    if why:
        marker["rearmed_why"] = why
    tails = []
    if refusal:
        tails.append(f"own-clear: after the {by} moved HEAD a step refused: {_brief_text(refusal)}. The move "
                     "landed; python tools/cc/ship.py status says what is on origin, then the verb the refusal "
                     "names.")
    if by == "arm" and marker.get("landed") is False:
        tails.append("own-clear: re-armed by hand after the lane reached origin; the tail above predates it: "
                     "python tools/cc/ship.py status says what is on origin.")
    if tails:
        marker["brief"] = "\n\n".join([marker.get("brief") or GENERIC_BRIEF, *tails])
    _write_own_clear(where, marker)
    return (f"own-clear re-armed at {head[:7]}: HEAD moved from {was[:7] or '?'} ({by}); the marker's brief and "
            f"record are kept{'; the refusal rides its brief' if refusal else ''}; the mod clears this window at "
            "the turn's end")


def _rearm_own_clear_or_note(root: Path, *, by: str, moved_from: str | None = None,
                             refusal: str | None = None) -> None:
    """The re-arm after a move that landed, said; a marker that cannot be
    rewritten, or a HEAD git cannot name, is a note with the by-hand verb,
    never a refusal of the verb whose move is already made."""
    try:
        line = rearm_own_clear_after_move(root, by=by, moved_from=moved_from, refusal=refusal)
    except (OSError, Refused) as exc:
        _note(f"the own-clear marker was not re-armed after the move ({os_error_text(exc)}): the mod holds "
              "the clear on HEAD moved; run python tools/cc/ship.py arm")
        return
    if line:
        _say(line)


def _base_ref_offline(root: Path) -> str | None:
    """``origin/<default branch>`` as this checkout holds it, with no network
    and no gh: the remote's HEAD symref, else origin/main, else origin/master;
    None when none is here."""
    rc, out, _ = _git("symbolic-ref", "-q", "refs/remotes/origin/HEAD", cwd=str(root))
    if rc == 0 and out.strip().startswith("refs/remotes/"):
        return out.strip()[len("refs/remotes/"):]
    for name in ("origin/main", "origin/master"):
        rc, _, _ = _git("rev-parse", "-q", "--verify", f"refs/remotes/{name}", cwd=str(root))
        if rc == 0:
            return name
    return None


def _lanes_own_commits_in(root: Path, was: str, head: str) -> str | None:
    """Why the move from ``was`` to ``head`` is not a pull alone, or None when
    it is: a non-merge commit there that the base (``origin/<default
    branch>``, as last fetched) does not hold is the lane's own -- a commit
    after the handoff, pushed by hand, which owes a handoff (the review's
    case: a re-arm over it would clear the window with no row for it). The
    server's merge of the base is a merge commit and the base's own commits
    are on its ref, so a pull leaves the list empty; a base ref that is not
    here, or a read that fails, is said and keeps the refusal."""
    base = _base_ref_offline(root)
    if base is None:
        return "no origin/<default branch> ref is here to tell a pull from a commit"
    rc, out, err = _git("rev-list", "--no-merges", head, f"^{was}", f"^{base}", cwd=str(root))
    if rc != 0:
        return f"the commits between the marker's head and HEAD could not be read ({err.strip()[:120]})"
    own = out.split()
    if own:
        return (f"{len(own)} commit{'s' if len(own) != 1 else ''} of this lane's own since the marker's head "
                f"({own[0][:7]}{', ...' if len(own) > 1 else ''}): a handoff is owed, and it re-arms the marker")
    return None


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
    first one's brief says -- unless a pull by hand moved HEAD under it with
    the lane on origin and no commit of the lane's own in the move
    (:func:`_lanes_own_commits_in`): then the marker follows HEAD with its
    brief kept (:func:`rearm_own_clear_after_move`), the hold the mod names
    on a moved head cleared; a commit of the lane's own keeps the refusal,
    since the handoff it owes re-arms the marker. ``why`` rides the marker's
    ``outcome`` on a fresh arm and ``rearmed_why`` on a re-arm."""
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
    # The marker, and the tree and HEAD the mod holds the clear on, are the
    # session's checkout's (DEF-5046); the lane read above is root's.
    where, _unplaced = own_clear_checkout(root)
    hold = None if _same_checkout(where, root) else _window_checkout_holds(where)
    if hold:
        raise Refused(f"nothing armed: {where}, the checkout this session's mod reads, {hold}: settle it there first")
    armed = _armed_for_this_session(where)
    if armed:
        refused = _refusals_on_marker(where)
        refused_tail = (f"; the engine has refused its clear {refused} time(s) (the marker's record): this window "
                        "needs /clear by hand" if refused else "")
        marker = _own_clear_marker(where) or {}
        head = head_sha(where)
        before = str(marker.get("head") or "")
        if before != head:
            own = _lanes_own_commits_in(where, before, head) if before else None
            if own:
                raise Refused(f"nothing re-armed: the own-clear marker is armed at {before[:7]}, and HEAD "
                              f"{head[:7]} holds {own}; run /handoff (a second arm would drop what the first "
                              "one's brief says)")
            if dry_run:
                _say(f"dry-run: the marker armed for this session ({armed}) would be re-armed at {head[:7]} "
                     f"(HEAD moved from {before[:7] or '?'} by a pull; its brief kept)" + (f" ({why})" if why else ""))
                return 0
            try:
                line = rearm_own_clear_after_move(root, by="arm", why=why)
            except OSError as exc:
                raise Refused(f"the marker could not be rewritten: {os_error_text(exc)}") from None
            if line is None:
                _say("nothing re-armed: the marker is no longer armed for this session")
                return 0
            _say(line + refused_tail)
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


def _shared_checkout_refusal(root: Path) -> str | None:
    """Why a push from this checkout must stop before anything here moves --
    two or more live sessions share it -- or None. A registry that cannot
    place them is a note, never a refusal: a push is reversible, and a false
    refusal under an unreadable registry would stop every seat at once. Asked
    once a run; `open` asks it as one of :data:`PRE_PUSH_CHECKS`, and
    ``lane``, ``catch-up`` and the handoff's push through
    :func:`_refuse_a_shared_checkout`."""
    if _SHARED["asked"]:
        return None
    _SHARED["asked"] = True
    who, why = shared_checkout(root)
    if who is None:
        _note(f"who else works in this checkout cannot be told ({why}); the push goes ahead -- two sessions "
              "in one checkout share its branch, and only you can see whether that is so here")
        return None
    if len(who) >= 2:
        reason = os.environ.get(SHARED_CHECKOUT_OK, "").strip()
        if reason:
            _note(f"pushing beside {len(who)} live sessions in this checkout ({SHARED_CHECKOUT_OK}: {reason})")
            return None
        return _shared_checkout_words(who, why)
    return None


def _refuse_a_shared_checkout(root: Path) -> None:
    """Stop a push from a checkout two or more live sessions share, before
    anything here moves (:func:`_shared_checkout_refusal`, the one reading)."""
    refusal = _shared_checkout_refusal(root)
    if refusal:
        raise Refused(refusal)


def _marked_record_refusal(root: Path) -> str | None:
    """Why a push the gate would red in every required cell must stop -- a
    record file that carries a merge-conflict marker -- or None. Named by file
    and line, with the one remedy and the one escape hatch (the rule is column
    zero)."""
    findings = record_file_markers(root)
    if not findings:
        return None
    return ("a record file carries a merge-conflict marker, which the harness guard refuses in "
            f"every required cell: {'; '.join(findings)}. Resolve the hunk and commit the file "
            "whole (a line that only quotes a marker is read as one too: indent the quote by "
            "one space)")


def _refuse_a_marked_record(root: Path) -> None:
    """Stop a push on a record file carrying a merge-conflict marker
    (:func:`_marked_record_refusal`, the one reading): the handoff's push
    asks it before its own reads; `open` asks it as one of
    :data:`PRE_PUSH_CHECKS`."""
    refusal = _marked_record_refusal(root)
    if refusal:
        raise Refused(refusal)


def _merge_first_reasons(root: Path, ref: str) -> list[str] | None:
    """The paths that make a merge of ``ref`` into HEAD one to make here
    before a push: those it would conflict on, and those carrying a merge
    attribute changed on both sides (GitHub's merge honours no driver).
    ``[]`` when it merges clean on GitHub too; None when git cannot say."""
    names = record_merge.probe_conflicts(root, ref, run=RUN)
    driven = record_merge.attribute_merged_paths(root, ref, run=RUN)
    if names is None and not driven:
        return None
    return sorted(set(names or []) | set(driven))


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
    reasons = _merge_first_reasons(root, ref)
    if reasons is None:
        _note(f"could not probe the merge with {ref} (git 2.38+ has `merge-tree --write-tree`, and the "
              "ref must be fetched); a lane that conflicts reads DIRTY on GitHub -- then run catch-up")
        return
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
    """What /ship's first step reads before anything moves: refuses a dirty
    tracked tree and an empty range, and says the rest -- the untracked files,
    the commits, the lane's shape, the merge with the base, the last merges'
    post-merge reds -- and every refusal in the one list of state checks
    `open` runs before its push, each in `open`'s own words
    (:data:`PRE_PUSH_CHECKS`, DEF-4082: a hand-kept copy of the forecasts
    missed the last-added refusal). The steps `open` takes after the list
    refuse where they happen; of theirs, only the deletion check is
    forecast, from the shape before the merge-first step. On the default
    branch ``lane`` is said as the next step, and the checks read the lane
    it would make, the branch `open` then pushes."""
    root = repo_root()
    base = default_branch()
    _git("fetch", "origin", "--quiet", cwd=str(root))
    _refuse_a_dirty_tree(root)
    try:
        branch = current_branch()
    except Refused as exc:
        branch = ""   # a detached HEAD: `open` stops on the same read, before any check
        _note(f"`open` will refuse this lane: {exc}")
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
    # The shape before the push, so /ship sees a deletion before `open`
    # refuses it (DEF-4064); /handoff runs no preflight and meets the refusal.
    try:
        shape = lane_shape(root, base)
    except Refused as exc:
        _note(f"{exc}: `open` will refuse this lane on the same read")
    else:
        say_lane_shape(root, base, shape)
        if shape["deleted"] and not is_revert_lane(branch):
            _note(f"`open` will refuse this lane: {_deletions_refusal(shape, base)}")
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
    if branch:
        _forecast_pre_push(root, base, branch)
    on, how = handoff_push_setting(root)
    if on:
        problem = memory_problem(root)
        if problem:
            _note(problem)
    return 0


def _forecast_pre_push(root: Path, base: str, branch: str) -> None:
    """Every refusal `open` would make before its push, said in its words:
    each of :data:`PRE_PUSH_CHECKS` read once, over one
    :class:`PrePushState` (no title, ruling or --early: preflight takes none),
    and each that refuses noted as "`open` will refuse this lane: <its
    text>". A read that raises is one `open` makes the same way and stops on,
    said once. The gate's hold record is `open`'s alone to write, so no
    check's ``record`` runs here. On the default branch the checks read the
    lane ``lane`` would name (from :func:`lane_subject`), as `open` will after
    it: /ship runs this before ``lane``, and the branch `open` pushes is
    that lane, never pushed (DEF-4082's second-lane seat). ``lane`` is said
    as the next step there, never as `open`'s refusal: /ship's usual path
    runs from the default branch, and a "will refuse" line on every run
    teaches a reader to skip them. Where the subject names no lane,
    ``lane`` cannot move the commits, and HEAD's refusal is forecast."""
    lane_branch = branch
    if branch == base:
        lane_branch = _lane_name_for(lane_subject(root, base)) or branch
        if lane_branch != branch:
            _say(f"HEAD is {base}: `lane` moves the commits to {lane_branch} first, and `open`'s checks below "
                 "read that lane")
    state = PrePushState(root, base, lane_branch)
    said: set[str] = set()
    for check in PRE_PUSH_CHECKS:
        try:
            refusal = check.read(state)
        except Refused as exc:
            if str(exc) not in said:
                said.add(str(exc))
                _note(f"{exc}: `open` will refuse this lane on the same read")
            continue
        if refusal:
            _note(f"`open` will refuse this lane: {refusal}")
    _seat_notes(state)
    if is_revert_lane(lane_branch):
        red_run = base_red_run(base, cwd=str(root))
        if red_run is not None:
            _say(f"{_red_base_words(base, red_run)} -- this is a revert/ lane, which `open` lets through")


def lane_subject(root: Path, base: str) -> str:
    """The subject that names a lane: its pull request's default title, and
    the branch ``lane`` makes. The newest commit on HEAD's first-parent line
    that ``origin/<base>`` lacks and that is the lane's own change -- neither
    a merge (the base merged in by hand, or a catch-up) nor a commit touching
    nothing outside the record folders (the loader's ``FRAGMENT_DIRS``: the
    handoff's row, a fold or prune, a ledger filing or strike), each of which
    sits at HEAD in the usual flows and named the lane in its place. A lane of
    records alone is named by its newest commit outside the Session Log (a
    filing lane by its filing, not the handoff's row), else by its newest
    non-merge commit; HEAD's own subject where it holds none, or where git
    cannot read the range (no ``origin/<base>``). First parents alone: the
    title is read before `open` fetches the base, and a stale
    ``origin/<base>`` would otherwise let a commit the base's merge brought in
    title the lane. The pathspecs are anchored at the top, whatever folder
    ``root`` names."""
    fragments = _fragments_module()
    records = tuple(getattr(fragments, "FRAGMENT_DIRS", ())) or (SESSION_LOG_DIR,)
    tiers = [records] + ([(SESSION_LOG_DIR,)] if records != (SESSION_LOG_DIR,) else []) + [()]
    for excluded in tiers:
        spec = ["--", ":/", *(f":(top,exclude){d.rstrip('/')}" for d in excluded)] if excluded else []
        rc, out, _ = _git("log", "-1", "--first-parent", "--no-merges", "--format=%s",
                          f"origin/{base}..HEAD", *spec, cwd=str(root))
        if rc != 0:
            break   # the range cannot be read: HEAD's subject, as before
        if out.strip():
            return out.strip()
    rc, out, _ = _git("log", "-1", "--format=%s", cwd=str(root))
    return out.strip() if rc == 0 else ""


def _lane_name_for(subject: str) -> str:
    """The lane ``lane`` names from a subject (:func:`lane_subject`'s)
    (``lane/<slug>``), or '' where the subject yields no slug."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", subject.strip()).strip("-").lower()[:48].rstrip("-")
    return f"lane/{slug}" if slug else ""


def lane() -> int:
    root = repo_root()
    base = default_branch()
    branch = current_branch()
    if branch != base:
        _say(f"HEAD is {branch}, not {base}: nothing to move (a lane already) -- next: open")
        return 0
    _refuse_a_shared_checkout(root)   # the switch below moves every session in this checkout onto the lane
    name = _lane_name_for(lane_subject(root, base))
    if not name:
        raise Refused("the lane's subject yields no lane name: pick one by hand (git switch -c lane/<name>)")
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


def _hold_for_the_gate(root: Path, base: str, branch: str, seat: str, mine: list[str]) -> None:
    """The Stop hook's handoff-gate hold for HEAD, written through the gate's
    own writer (``stop_gate._hold_write``, the record's one format owner):
    a handoff held here arms the own-clear at this HEAD, so the gate passes it
    and writes no hold of its own, and the next SessionStart keeps only a
    hold naming HEAD -- without this one it seeds the flag past the lane, and
    no hook asks for it once the window is cleared (the failure-mode review,
    2026-11-01). A tree whose hooks are not beside this script says so."""
    loader = getattr(_paths, "hooks_module", None)
    gate = loader("stop_gate") if loader else None
    writer = getattr(gate, "_hold_write", None) if gate is not None else None
    if writer is None:
        _note("the Stop hook's hold for this lane was not written (tools/cc/hooks/stop_gate.py is not beside "
              "this script), so after a clear only the own-clear's brief names it")
        return
    rc, out, _ = _git("rev-list", "--count", f"origin/{base}..HEAD", cwd=str(root))
    ahead = int(out.strip()) if rc == 0 and out.strip().isdigit() else 0
    writer(root, head_sha(), branch, seat, list(mine), ahead)


def _has_own_upstream(root: Path, branch: str) -> bool | None:
    """Whether origin holds ``branch`` as its own remote branch
    (``origin/<branch>``: a lane already pushed, with ``-u`` or without), read
    by :func:`_lane_upstream`, the one reading the Stop hook's handoff gate
    shares (``stop_gate._unpushed_commits``). A branch started from
    ``origin/main`` tracks origin/main by git's default autoSetupMerge, an
    upstream that is not its own, and reads False until a push lands it; None
    where the shared reading is not beside this script."""
    reading = _lane_upstream(root, branch)
    return None if reading is None else reading[1]


def _remote_has_commits_we_lack(branch: str, cwd: str) -> int:
    """Commits on origin/<branch> that HEAD does not reach: a push would be
    rejected, and the only way past is a merge -- never a rebase or a force,
    which rewrites a pushed lane and is the precondition of the push/edit race."""
    rc, _, _ = _git("fetch", "origin", branch, "--quiet", cwd=cwd)
    if rc != 0:
        return 0  # the remote branch does not exist yet: a first push
    return _commits_head_lacks(f"origin/{branch}", cwd)


def _commits_head_lacks(ref: str, cwd: str) -> int:
    """How many commits ``ref`` holds that HEAD does not reach, 0 where git
    cannot say: the one count behind :func:`_remote_has_commits_we_lack`'s
    refusal and the park's note that the push will meet it."""
    rc, out, _ = _git("rev-list", "--count", f"HEAD..{ref}", cwd=cwd)
    try:
        return int(out.strip() or "0") if rc == 0 else 0
    except ValueError:
        return 0


def _origin_ahead_refusal(branch: str, cwd: str) -> str | None:
    """Why a push of ``branch`` would be rejected -- origin's copy holds
    commits HEAD does not reach (:func:`_remote_has_commits_we_lack`) -- with
    the one way past, or None. `open` asks it as one of
    :data:`PRE_PUSH_CHECKS`, and the handoff's push onto an open pull
    request in the same words.

    The words are :func:`_ahead_words`', the one home of what a push of a
    lane origin is ahead of must do first; where its read of the commits
    gives none although the count found some, the merge, as before."""
    behind = _remote_has_commits_we_lack(branch, cwd)
    if not behind:
        return None
    return _ahead_words(branch, cwd) or (
        f"origin/{branch} has {behind} commit(s) this HEAD does not reach, and git could not list them: read git "
        f"log HEAD..origin/{branch} first; where one carries {UNFINISHED_TRAILER}, a merge brings that set-aside "
        f"commit back, and the brief's soft reset then the lease push take it off; else merge them in (git merge "
        f"origin/{branch}); never rebase or force-push a pushed lane")


def _refuse_set_aside_on_origin(root: Path, branch: str) -> None:
    """Stop a verb that moves this branch onto origin's copy, or has GitHub
    move that copy (the handoff's park onto an open pull request, which
    resets to it; catch-up, whose server arm updates it and pulls it here),
    while that copy holds a set-aside commit HEAD lacks: the move brings the
    commit back here (DEF-5102's failure-mode re-review, the park driven).
    Origin's copy is read as last fetched, offline, as the lane's own
    refusal reads it: a hand push from this checkout moves that ref itself,
    and one from another clone is seen from the next fetch. A read git
    cannot answer is no verdict. The words are :func:`_ahead_words`'."""
    records = _commit_records(str(root), f"HEAD..origin/{branch}") or []
    if any(record[2] for record in records):
        raise Refused("this verb would move the lane onto origin's copy and bring its set-aside commit back: "
                      + (_ahead_words(branch, str(root)) or "read git log HEAD..origin/" + branch))


def _ahead_words(branch: str, cwd: str) -> str | None:
    """What a push of ``branch`` must do first where origin's copy (as last
    fetched) holds commits HEAD does not reach, or None where it holds none
    (a plain push goes) or git cannot say. A plain push is then rejected and
    git's own hint is a pull, so every text that names a push asks here
    (DEF-5102: :func:`_origin_ahead_refusal`, the open pull request's and
    rebind's push first, catch-up's fast-forward refusal).

    The way past is a merge, except where a commit there carries
    :data:`UNFINISHED_TRAILER`: a hand push put the threshold handoff's
    set-aside commit on origin, and the next window took it back with the
    brief's soft reset. A merge brings the set-aside edits back, and
    :func:`_unfinished_on_lane` then names the reset again: with the lease
    unnamed the two refusals alternated (driven two rounds). The lease push
    the driver never makes itself is named only where every commit origin
    holds and HEAD lacks was once on this branch here (its reflog: the
    window held it and took it back), bound to origin's head as read (the
    range's first record). Where one was never here (another clone pushed
    it), the lease would drop it on a push git calls a success, so the merge
    is named: it brings the set-aside commit back, the unfinished-lane
    refusal names the merge-base reset, and the reflog then holds the merge,
    so the next read names the lease. The reflog is a floor: an entry it
    has expired reads as a commit never held, and names the merge."""
    records = _commit_records(cwd, f"HEAD..origin/{branch}")
    if not records:
        return None
    merge = f"merge them in (git merge origin/{branch}); never rebase or force-push a pushed lane"
    found = [record for record in records if record[2]]
    if not found:
        return f"origin/{branch} has {len(records)} commit(s) this HEAD does not reach: {merge}"
    sha, _parent, lane = found[-1]
    held = (f"origin/{branch} holds {sha[:12]}, the commit the threshold handoff made of an unfinished lane's "
            f"tracked edits ({UNFINISHED_TRAILER}: {lane}), which a hand push put there")
    rc, reflog, _ = _git("reflog", "show", "--format=%H", f"refs/heads/{branch}", cwd=cwd)
    never = None
    if rc == 0:
        rc, left, _ = _git("rev-list", f"origin/{branch}", "--not", "HEAD", *reflog.split(), cwd=cwd)
        never = left.split() if rc == 0 else None
    if never != []:
        unheld = (f"{len(never)} commit(s) there were never on this branch here, by its reflog" if never
                  else "this branch's reflog could not be read")
        return (f"{held}, and {unheld}, so a lease push would drop them: {merge}. The merge brings the set-aside "
                "commit back, the unfinished-lane refusal then names the reset, and after it the driver names "
                "the lease push")
    tip = records[0][0]
    others = len(records) - len(found)
    replaced = (f"; it replaces the {others} other commit(s) there too, each once on this branch here" if others
                else "")
    return (f"{held}, and a merge of origin/{branch} would bring those edits back: once the lane is finished and "
            f"committed without it (the brief's soft reset first), git push --force-with-lease={branch}:{tip} "
            f"origin HEAD:{branch} takes it off (the lease refuses if origin's branch moved since this "
            f"read{replaced})")


# ------------------------------------------------ open's refusals before its push --

class PrePushState:
    """What `open`'s refusals before its push read, for one run: the checkout,
    the base, the lane `open` pushes (``branch``: HEAD's branch in `open`;
    the lane ``lane`` would make where `preflight` reads ahead of it on the
    default branch), and the arguments a check judges (the title, the
    ruling's ack id, the --early reason; preflight passes none). The
    three reads more than one check needs -- the open pull requests
    (:func:`_open_prs`), the red base's verdict (:func:`red_base_verdict`)
    and this seat's share of them (:func:`seat_open_prs`) -- are each made
    once, the first time a check asks, which is where `open` made each
    before its checks were a list. The checks write back what `open`'s steps
    after them use: the --early reason taken, the title, whether the lane
    has an upstream of its own (``own``), whether the one-per-seat hold was
    judged, and what a held lane waits for."""

    def __init__(self, root: Path, base: str, branch: str, *, title: str | None = None,
                 ruled: str | None = None, early: str | None = None) -> None:
        self.root = root
        self.base = base
        self.branch = branch
        self.title_given = title
        self.ruled = ruled
        self.early = early
        self.early_reason = ""
        self.title = ""
        self.own: bool | None = None
        self.hold_judged = False
        self.waits_for = ""
        self._reads: dict[str, object] = {}

    def prs(self) -> list[dict] | None:
        """Every open pull request, None where gh could not say: the row-debt
        read takes None as unread, the red base and the seat as none."""
        if "prs" not in self._reads:
            self._reads["prs"] = _open_prs(str(self.root))
        return self._reads["prs"]  # type: ignore[return-value]

    def verdict(self) -> tuple[str | None, str | None]:
        """``(refusal, ruling)`` for the red base (:func:`red_base_verdict`)."""
        if "verdict" not in self._reads:
            self._reads["verdict"] = red_base_verdict(self.base, self.branch, self.prs() or [], str(self.root),
                                                      ruled=self.ruled, root=self.root)
        return self._reads["verdict"]  # type: ignore[return-value]

    def seat(self) -> tuple[str, list[str]]:
        """``(seat, ["#n (lane)", ...])``: this seat's other open pull requests."""
        if "seat" not in self._reads:
            self._reads["seat"] = seat_open_prs(self.root, self.branch, self.prs() or [])
        return self._reads["seat"]  # type: ignore[return-value]

    def clearing(self) -> bool:
        """Whether the lane clears a red base -- a revert, or the fix a
        ruling names -- which lands first (Core Rule 15)."""
        return is_revert_lane(self.branch) or bool(self.verdict()[1])

    def others(self) -> str:
        seat, mine = self.seat()
        return f"this seat ({seat}) already has an open pull request: {', '.join(mine)}"


def _head_is_base_refusal(st: PrePushState) -> str | None:
    """`open` run on the default branch. `preflight` there reads the lane
    ``lane`` would make, so it forecasts this only where the lane's subject
    (:func:`lane_subject`) names no lane (``lane`` refuses that subject too)."""
    if st.branch != st.base:
        return None
    return f"HEAD is {st.base}: run `lane` first (a protected default branch takes no push)"


def _open_pull_request_refusal(st: PrePushState) -> str | None:
    if pr_for_branch(st.branch, "open") is None:
        return None
    ahead = _ahead_words(st.branch, str(st.root))
    return (f"an open pull request already exists for {st.branch}: after a push, run `rebind`"
            + (f"; before the push, {ahead}" if ahead else ""))


def _row_refusal(st: PrePushState) -> str | None:
    """The second-push question where handoff_push is on, asked before the
    base's: a lane with no row is the window's to fix, whatever the base
    reads, and the red base's held refusal promises the next window a row
    written (both reviews, 2026-10-30). With --early the Session Log debt is
    asked (:func:`_refuse_on_row_debt`, which refuses by itself) and the
    early ship is said. The open pull requests are read first, where `open`
    read them before this question: the debt reads a row riding this seat's
    own open pull request."""
    prs = st.prs()
    on, how = handoff_push_setting(st.root)
    if not on or lane_carries_memory_row(st.base, st.root) is not False:
        return None
    reason = (st.early or "").strip()
    if not reason:
        return _second_push_message(how)
    _refuse_on_row_debt(st.root, st.base, prs)
    _note(f"shipping before the handoff ({reason}): its row will park on this seat's records ref until the "
          "next lane's push folds it, or be a second push on this lane where the handoff adds more than rows")
    st.early_reason = reason
    return None


def _red_base_refusal(st: PrePushState) -> str | None:
    """Nothing lands on a red base (:func:`red_base_verdict`): held, the lane
    whole here, and the handoff arms the own-clear on it (the next window
    lands it once the base is green, or once the dispatcher's ruling names
    the red run). A ruling that lets the lane through is said."""
    refusal, ruling = st.verdict()
    if refusal:
        return refusal
    if ruling:
        _say(ruling)
    return None


def _seat_hold_refusal(st: PrePushState) -> str | None:
    """One open pull request per seat, as the Stop hook holds it (DEF-5038):
    held while this seat has another pull request open and the lane has no
    upstream of its own (never pushed). A red base's clearing is never held,
    and a push state that cannot be read never holds (the notes after the
    checks say so, :func:`_seat_notes`). The text names the pull requests
    and the by-hand way past a wrong attribution."""
    seat, mine = st.seat()
    st.own = _has_own_upstream(st.root, st.branch) if mine and not st.clearing() else None
    st.hold_judged = True
    if st.own is not False:
        return None
    numbers = ", ".join(entry.split(" ", 1)[0] for entry in mine)
    st.waits_for = numbers + (" merges or closes" if len(mine) == 1 else " merge or close")
    return (f"{st.others()}. One open pull request per seat: the lane is held here, committed and unpushed, "
            f"and is opened once {st.waits_for} (python tools/cc/ship.py open then). Where {numbers} is not this "
            "seat's (/inbox board names whose it is), or the lane must land beside it, push it by hand "
            "(git push -u origin HEAD) and `open` opens it beside, noted")


def _record_the_seat_hold(st: PrePushState) -> None:
    seat, mine = st.seat()
    _hold_for_the_gate(st.root, st.base, st.branch, seat, mine)


def _title_refusal(st: PrePushState) -> str | None:
    """The pull request's title: --title, else the lane's own subject
    (:func:`lane_subject`: a merge of the base at HEAD, or the handoff's row
    there, is passed over), read before the merge-first step, whose merge
    would otherwise be HEAD."""
    st.title = (st.title_given or lane_subject(st.root, st.base))[:TITLE_MAX].rstrip()
    if st.title:
        return None
    return "the head commit has no subject and no --title was given: a pull request needs a title"


class PrePushCheck(NamedTuple):
    """One of `open`'s refusals before its push. ``read`` returns the
    refusal's text, or None where the lane passes; ``held`` raises it as a
    :class:`Held` (the lane whole, waiting on something outside the window:
    the handoff arms the own-clear on it) rather than a :class:`Refused` (the
    window's to fix); ``record`` is what `open` writes before it raises a held
    one, on a run that is not a dry run (preflight never runs it)."""

    name: str
    read: Callable[[PrePushState], str | None]
    held: bool = False
    record: Callable[[PrePushState], None] | None = None


#: `open`'s refusals of the lane's state before its push, as ONE list in the
#: order `open` asks them: `open` raises the first that refuses, and
#: `preflight` says each that would, as "`open` will refuse this lane: " and
#: the same text. The forecasts were a hand-kept copy of `open`'s checks, and
#: the last-added refusal slipped through it (DEF-4082: five forecast, five
#: not, the one-open-pull-request hold among them). tests/test_ship_driver.py
#: derives from this list both ways: every refusal `open` raises before its
#: push, in its own body or in any of this module's functions it calls there
#: (followed down every call), is this list's or one named outside it with
#: its reason, and every entry made to refuse is forecast in `open`'s words.
#: Outside it, on purpose: the --body-file refusals (an argument, not the
#: lane's state); the reads before the lane is known (the checkout, the base,
#: a detached HEAD), which preflight makes first; and the steps after the
#: list, which refuse where they happen -- the merge-first step's tree check,
#: a deletion the lane never made (:func:`refuse_unmade_deletions`), read from
#: the shape AFTER the merge-first step and the fold move the head (preflight
#: forecasts it from the shape before them, DEF-4064), and the marker's diff.
#: A check's own callee that refuses (the --early debt) refuses inside the
#: list, raised from the check's read; preflight takes no --early, so that one
#: is never forecast.
PRE_PUSH_CHECKS: tuple[PrePushCheck, ...] = (
    PrePushCheck("head-is-base", _head_is_base_refusal),
    PrePushCheck("open-pull-request", _open_pull_request_refusal),
    PrePushCheck("origin-ahead", lambda st: _origin_ahead_refusal(st.branch, str(st.root))),
    PrePushCheck("unfinished-commit", lambda st: _unfinished_on_lane(st.root, f"origin/{st.base}")),
    PrePushCheck("marked-record", lambda st: _marked_record_refusal(st.root)),
    PrePushCheck("shared-checkout", lambda st: _shared_checkout_refusal(st.root)),
    PrePushCheck("no-session-log-row", _row_refusal),
    PrePushCheck("red-base", _red_base_refusal, held=True),
    PrePushCheck("one-open-pull-request-per-seat", _seat_hold_refusal, held=True, record=_record_the_seat_hold),
    PrePushCheck("no-title", _title_refusal),
)


def _seat_notes(st: PrePushState) -> None:
    """What `open` says of this seat's other open pull requests once the
    one-per-seat hold was judged and did not hold, and `preflight` says the
    same: a list gh could not give, a clearing lane opening beside them, a
    push state that could not be read (never a hold on a guess), a lane whose
    push already landed once. Silent where the hold was not judged (a read
    before it refused) or held."""
    if not st.hold_judged:
        return
    seat, mine = st.seat()
    if st.prs() is None:
        _note("the open pull requests could not be read (gh pr list), so this seat's other open pull requests "
              "were not checked (one open pull request per seat); the lane opens")
    elif mine and st.clearing():
        first = "a revert/ lane" if is_revert_lane(st.branch) else "the fix the ruling names"
        _note(f"{st.others()}. This lane opens beside it: {first} lands first")
    elif mine and st.own is None:
        # Never a hold on a guess, as for an unread list above.
        _note(f"{st.others()}. Whether this lane was pushed could not be read ({_LANE_UPSTREAM_UNREAD}), so the "
              "one open pull request per seat hold was not judged; the lane opens beside it")
    elif mine and st.own:
        _note(f"{st.others()}. This lane's push already landed once, so it opens beside it; one open pull "
              "request per seat keeps a seat's lanes off each other's base")


#: A task pack: a record for the body's question, as the record merge's roster
#: is (a pack lane carries its story in the pack itself).
_PACK_FILE_RE = re.compile(r"^task-packs/(?:[^/]+/)?TP-[^/]*\.md$")
#: A Session Log row's cells after its date (the loader reads the row and its
#: date): ``| <date> | <headline> | <text> |``, the headline running to the
#: first pipe no backslash escapes.
_ROW_CELLS_RE = re.compile(r"^\|[^|]*\|\s*(.*?)\s*(?<!\\)\|\s*(.*?)\s*\|\s*$")


def _outside_the_records(root: Path, base: str) -> list[str] | None:
    """The paths the lane changes (the three-dot diff the pull request shows)
    outside the record files: the record merge's roster (``record_merge.ROSTER``:
    the memory file, the forward ledger and its probes, the fragment folders)
    and a task pack. None where git cannot say."""
    rc, out, _ = _git("diff", "--name-only", "--no-renames", f"origin/{base}...HEAD", cwd=str(root))
    if rc != 0:
        return None
    roster = tuple(record_merge.ROSTER)
    outside: list[str] = []
    for line in out.splitlines():
        path = line.strip().replace("\\", "/")
        if not path or _PACK_FILE_RE.match(path):
            continue
        if any(path == entry or (entry.endswith("/") and path.startswith(entry)) for entry in roster):
            continue
        outside.append(path)
    return outside


def _seat_rows(root: Path, base: str) -> list[str] | None:
    """This seat's own Session Log rows on the lane: the files the lane's own
    commits added (:func:`_lane_added_rows`, where a fold's rows, other
    seats' and this seat's parked ones, are left out), and of those, where the
    box is named, the ones named for it (``-<seat>.md``), so a row another
    seat's commit carries (a lane built on that seat's head) is not this
    lane's evidence. None where git cannot say."""
    added = _lane_added_rows(root, base)
    if not added:
        return added
    seat, problem = seat_name(root)
    if problem:
        _note(f"this seat's name could not be read ({problem}), so every Session Log row the lane's own "
              "commits added is read as this seat's for the pull request's body")
        return added
    # An unnamed box writes its rows as `local` (the fragment loader's own name for it).
    seat = seat or "local"
    # The name's own shape, <date>-<HHMMSS>-<seat>.md: a seat `work` is not `air-work`.
    own = re.compile(rf"-\d{{6}}-{re.escape(seat)}\.md$")
    return [path for path in added if own.search(path)]


def _row_text(root: Path, path: str) -> str:
    """A Session Log row file at HEAD as the body shows it: each row the
    fragment loader reads in it (``rows_from_texts``) as its date and
    headline, then its text, a paragraph each; a row not in that shape as its
    line. '' where git or the loader cannot read it, said."""
    rc, out, err = _git("show", f"HEAD:{path}", cwd=str(root))
    fragments = _fragments_module()
    reader = getattr(fragments, "rows_from_texts", None) if fragments is not None else None
    if rc != 0 or reader is None:
        _note(f"the Session Log row {path} could not be read ({err.strip()[:120] or 'no loader beside this script'}), "
              "so the pull request's body does not carry it")
        return ""
    shown: list[str] = []
    for row in reader([(path.rsplit("/", 1)[-1], fold_newlines(out))], ""):
        cells = _ROW_CELLS_RE.match(row.line.strip())
        shown.append(f"{row.date}: {cells.group(1)}\n\n{cells.group(2)}" if cells else row.line.strip())
    return "\n\n".join(shown)


def _audit_setting(root: Path) -> str | None:
    """How ``espalier.toml`` names the dispatcher who audits a merged lane from
    its body (``mail.dispatcher_setting``'s words), or None where it names
    none, where the setting cannot be used (the same answer as a file that
    does not parse, which may name no dispatcher at all: no refusal on a
    guess), or the channel is not beside this script. A file read, no spawn."""
    mail = _mail_module()
    reader = getattr(mail, "dispatcher_setting", None) if mail is not None else None
    if reader is None:
        return None
    dispatcher, how = reader(root)
    if dispatcher is None or dispatcher == getattr(mail, "DISPATCHER_UNUSABLE", None):
        return None
    return str(how)


def _subjects_body_refusal(root: Path, base: str, branch: str, rows: list[str] | None) -> str | None:
    """Why the commit subjects alone may not be the body, or None: a lane a
    dispatcher audits from its body (:func:`_audit_setting`), changing a file
    outside the records (:func:`_outside_the_records`), not a revert/ lane
    (the red base's revert stays fast), and carrying no Session Log row of
    this seat (``rows``, read by the caller). A read that cannot be made never
    refuses: no verdict is a refusal on a guess."""
    if rows is None or rows or is_revert_lane(branch):
        return None
    how = _audit_setting(root)
    if how is None:
        return None
    outside = _outside_the_records(root, base)
    if not outside:
        return None
    shown = ", ".join(outside[:3]) + (", ..." if len(outside) > 3 else "")
    return (f"the pull request's body would be the commit subjects alone, on a tree whose dispatcher audits a "
            f"merged lane from its body ({how}): this lane changes {len(outside)} file(s) outside the records "
            f"({shown}) and carries no Session Log row of this seat. Write the lane's evidence to a file and pass --body-file <path>, "
            "or commit this seat's row on the lane (/handoff writes it, and the default body then carries it), "
            f"or pass {SUBJECTS_BODY_FLAG} \"<why>\" to ship the subjects alone with the reason in the body")


def _default_body(root: Path, base: str, branch: str, subjects_body: str | None = None) -> str:
    """The pull request's body where no --body-file gives one: this seat's own
    Session Log rows on the lane (:func:`_seat_rows`), each as
    :func:`_row_text` shows it, then the commit subjects; the subjects alone
    where the lane carries no such row. Refused before anything moves where
    the subjects alone would ship on a lane a dispatcher audits
    (:func:`_subjects_body_refusal`), unless --subjects-body says why, and the
    why then rides the body. `open` reads it in place of the subjects, and
    the handoff's push from the default branch reads it before ``lane``
    moves the commits."""
    rc, log, _ = _git("log", "--format=- %s", f"origin/{base}..HEAD", cwd=str(root))
    subjects = fold_newlines(log) if rc == 0 else ""
    rows = _seat_rows(root, base)
    texts = [text for text in (_row_text(root, path) for path in rows or []) if text]
    why = (subjects_body or "").strip()
    if texts:
        if why:
            _note(f"{SUBJECTS_BODY_FLAG} is not used: the body carries this seat's Session Log row")
        heading = "## This seat's Session Log row" + ("s" if len(texts) > 1 else "")
        return heading + "\n\n" + "\n\n".join(texts) + "\n\n## Commits\n\n" + subjects.strip("\n") + "\n"
    if why:
        return subjects.rstrip("\n") + f"\n\nShipped with the commit subjects alone: {why}\n"
    refusal = _subjects_body_refusal(root, base, branch, rows)
    if refusal:
        raise Refused(refusal)
    return subjects


def open_pr(title: str | None = None, body_file: str | None = None, dry_run: bool = False,
            early: str | None = None, base_red_ruled: str | None = None,
            allow_deletions: str | None = None, subjects_body: str | None = None) -> int:
    root = repo_root()
    base = default_branch()
    branch = current_branch()
    # The lane's state, refused before anything moves by the one list
    # `preflight` forecasts: the first refusal stops the verb.
    state = PrePushState(root, base, branch, title=title, ruled=base_red_ruled, early=early)
    for check in PRE_PUSH_CHECKS:
        refusal = check.read(state)
        if not refusal:
            continue
        if not check.held:
            raise Refused(refusal)
        if check.record is not None and not dry_run:
            check.record(state)
        raise Held(refusal, landed=False, waits_for=state.waits_for)
    title = state.title
    early_reason = state.early_reason
    ruling = state.verdict()[1]
    _seat_notes(state)
    _wiring_note(root)
    # The base is fetched here, before the merge-first question and the guard
    # question below (both read origin/<base> and neither needs the remote
    # again). The title (read by the checks above) and the body are read
    # BEFORE the merge-first step: a merge commit's subject is "Merge
    # remote-tracking branch ...", and the lane's story is the head it had
    # before (both reviews, driven).
    _git("fetch", "origin", base, "--quiet", cwd=str(root))
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
        if (subjects_body or "").strip():
            _note(f"{SUBJECTS_BODY_FLAG} is not used: --body-file gives the body")
    else:
        body = _default_body(root, base, branch, subjects_body)
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
    # The shape of what is pushed, after the merge and the fold have moved the
    # head: a deletion the driver did not make refuses the push unless
    # --allow-deletions says why, and the why rides the body (DEF-4064).
    shape = lane_shape(root, base)
    say_lane_shape(root, base, shape)
    allowed = refuse_unmade_deletions(shape, base, allow_deletions, branch)
    if allowed:
        body = body.rstrip("\n") + f"\n\n{allowed}\n"
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
    # A hand `git push` then `rebind` (the red-cell recipe) would bind the
    # marker over an unfinished lane's set-aside edits: the push itself is not
    # the driver's to check, so the re-bind after it asks.
    named = str(pr.get("baseRefName") or "")
    _refuse_an_unfinished_lane(root, f"origin/{named}" if named else (_base_ref_offline(root) or "origin/main"))
    sha = head_sha()
    number = str(pr["number"])
    if not str(pr.get("headRefOid", "")).startswith(sha):
        ahead = _ahead_words(branch, str(root))
        raise Refused(f"push first: HEAD {sha[:7]} is not #{number}'s head {str(pr.get('headRefOid', ''))[:7]}"
                      + (f"; before the push, {ahead}" if ahead else ""))
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


def _unfinished_refusal(text: str) -> Refused:
    return Refused(f"nothing set aside: {text}")


def _lane_commit_records(root: Path, base_ref: str) -> list[tuple[str, str, str]] | None:
    """Every commit of the lane (``base_ref..HEAD``), newest first -- HEAD's
    the first -- as :func:`_commit_records` gives them; None when git cannot
    answer. One read."""
    return _commit_records(str(root), f"{base_ref}..HEAD")


def _commit_records(cwd: str, revisions: str) -> list[tuple[str, str, str]] | None:
    """Every commit of ``revisions`` (a range), newest first, as ``(sha,
    first parent, the value of its :data:`UNFINISHED_TRAILER`, '' on a commit
    without one)``; None when git cannot answer. One read: the lane's own
    (:func:`_lane_commit_records`) and origin's commits HEAD lacks
    (:func:`_origin_ahead_refusal`)."""
    rc, out, _ = _git("log", f"--format={UNFINISHED_LOG_FORMAT}", revisions, cwd=cwd)
    if rc != 0:
        return None
    records = []
    for record in out.split("\x1e")[1:]:
        ids, _sep, value = record.partition("\x1f")
        shas, value = ids.split(), value.strip()
        if shas:
            records.append((shas[0], shas[1] if len(shas) > 1 else "",
                            value.splitlines()[0].strip() if value else ""))
    return records


def _unfinished_commits(root: Path, base_ref: str) -> list[tuple[str, str, str]] | None:
    """The lane's commits that carry :data:`UNFINISHED_TRAILER`, newest
    first, as :func:`_lane_commit_records` gives them; None when git cannot
    answer."""
    records = _lane_commit_records(root, base_ref)
    return None if records is None else [record for record in records if record[2]]


def _moved_past_reset_words(root: Path, base_ref: str, sha: str, parent: str) -> str:
    """The soft reset for a lane whose HEAD has moved past its set-aside
    commit: to that commit's parent while no merge follows it; after a merge
    (of the base, or of origin's copy of the lane: either can stage the
    base's tree), to the lane's merge-base with the base, since a reset to the
    parent stages the merged base's tree as the lane's own change and a file
    the base has since removed rides the landing back in. A git that cannot
    say which is the merge-base, named as a command: it is right either way,
    and folds every commit of the lane into the one recommit."""
    rc, merges, _ = _git("rev-list", "--merges", f"{sha}..HEAD", cwd=str(root))
    if rc == 0 and not merges.strip():
        return (f"HEAD has moved past it: git reset --soft {parent[:12]} takes it back with every commit after "
                "it, staged, to recommit the finished work without its trailer")
    rc_base, below, _ = _git("merge-base", base_ref, "HEAD", cwd=str(root)) if rc == 0 else (1, "", "")
    target = below.strip()[:12] if rc_base == 0 and below.strip() else f"$(git merge-base {base_ref} HEAD)"
    return (f"HEAD has moved past it, and a merge follows it: git reset --soft {target} (the "
            f"lane's merge-base with {base_ref}; a reset to its parent would stage the base's merged changes "
            "as the lane's own) takes it back with every commit of the lane, staged, to recommit the finished "
            "work without its trailer")


def _unfinished_on_lane(root: Path, base_ref: str) -> str | None:
    """Why the lane at ``root`` must not be pushed, or None: it holds the
    commit the threshold handoff made of an unfinished lane's tracked edits
    (:func:`_hand_off_unfinished`, its :data:`UNFINISHED_TRAILER`), which the
    next window takes back with a soft reset before the lane is finished. A
    push would carry those edits to origin half-made, and an open pull
    request's armed auto-merge would land them (the re-primed window's loop
    ranks its own red pull request first, ahead of the brief, and the
    catch-up and the handoff push HEAD). The one reading every push of the
    lane asks (``open`` through :data:`PRE_PUSH_CHECKS`, the handoff's push
    onto an open pull request, ``catch-up``); a git that cannot answer is no
    verdict, never a refusal on a guess."""
    records = _lane_commit_records(root, base_ref)
    found = [record for record in records or [] if record[2]]
    if not records or not found:
        return None
    sha, parent, lane = found[-1]   # the oldest: a reset below it takes back every one after it
    at_head = records[0][0] == sha and len(found) == 1
    move = (_soft_reset_words(sha, parent) if at_head else _moved_past_reset_words(root, base_ref, sha, parent))
    # A hand push already put it on origin (as last fetched): after the reset
    # a plain push is rejected and git's hint is a pull, which brings it back
    # (the same rule as _ahead_words, read before the reset it cannot see).
    rc, here, _ = _git("branch", "--show-current", cwd=str(root))
    branch = here.strip() if rc == 0 else ""
    pushed = bool(branch) and _git("merge-base", "--is-ancestor", sha, f"refs/remotes/origin/{branch}",
                                   cwd=str(root))[0] == 0
    push = (f"push it: origin/{branch} holds it too, so the push is then the git push --force-with-lease the "
            f"driver's push refusal names, never a merge of origin/{branch}, which brings it back" if pushed
            else "push it")
    return (f"the lane holds {sha[:12]}, the commit the threshold handoff made of the unfinished lane "
            f"{lane}'s tracked edits ({UNFINISHED_TRAILER}: {lane}), and a push would carry them half-made: "
            f"{move}, then finish the lane and {push}")


def _refuse_an_unfinished_lane(root: Path, base_ref: str) -> None:
    """Stop a push of a lane holding an unfinished commit
    (:func:`_unfinished_on_lane`, the one reading)."""
    refusal = _unfinished_on_lane(root, base_ref)
    if refusal:
        raise Refused(refusal)


def _operation_in_progress(root: Path) -> str | None:
    """The half-done git operation in ``root`` by name (a merge, a rebase, a
    cherry-pick or revert, a sequence, a bisect), read by the checkout
    catch-up's own reading (``checkout_sync._mid_operation``, loaded by path),
    or the reason it cannot be read: a commit in the middle of one would seal
    it half-made into the lane. None when nothing is in progress."""
    try:
        sync = _sync_module()
    except Exception as exc:  # noqa: BLE001 -- fail-open with voice: the read is refused by name below
        sync, why = None, f"it will not load ({type(exc).__name__})"
    else:
        why = "it is not beside this script or is an older one without _mid_operation"
    reader, git = getattr(sync, "_mid_operation", None), getattr(sync, "_Git", None)
    if not callable(reader) or git is None:
        return f"an operation tools/cc/checkout_sync.py could not rule out ({why})"
    return reader(git(root, None))


def _hand_off_unfinished(root: Path, text: str, *, dry_run: bool) -> Unfinished:
    """The threshold handoff of a lane its window cannot finish (DEF-4104):
    the plain handoff's push would open the half-built lane's pull request
    with auto-merge armed, which the threshold rule forbids, and ``arm``
    refuses a lane that is not on origin, so until this nothing armed and the
    seat idled until a hand /clear. This pushes nothing, opens nothing and
    releases no claim (the lane's job stays live): it sets a plan in progress
    aside in the cold store (``execution_plan.demote_plan``, loaded by path),
    commits the tracked edits as one commit (:data:`UNFINISHED_SUBJECT`)
    carrying :data:`UNFINISHED_TRAILER`, which every push of the lane refuses
    on until it is taken back (:func:`_unfinished_on_lane`), names the
    untracked files, and returns what the brief tells the next window
    (:func:`_finish_first_tail`), which ``handoff`` then arms, last. Those
    are the three things the own-clear mod holds a clear on (a tracked edit,
    a plan in progress, HEAD off the marker), and the marker is armed at the
    HEAD this leaves. The origin rule is the by-hand arm's alone
    (:func:`_lane_not_on_origin`: a lane cleared past unpushed and
    unmentioned); this lane is named in the brief, as a held handoff's is.

    Refused before anything moves, each the window's to settle: no text; a
    window whose mod would read no marker (left as it is, the lane is what
    that window reads); a session the prompt router never asked for the
    threshold handoff (its first-ask record, ``_hook_utils.recorded_handoff_ask``:
    with no escape, so this never becomes the everyday way past the plain
    handoff's dirty-tree refusal); a checkout two live sessions share; a
    record file with a conflict marker; a merge, rebase, cherry-pick, revert
    or bisect in progress (:func:`_operation_in_progress`); a detached HEAD
    or the default branch (no lane to name); a lane whose commits carry no
    Session Log row (the brief promises it, as the held tail does); an
    unfinished commit below HEAD (take it back first); a plan in progress
    the driver cannot set aside; and, where the session was started in
    another checkout of the clone (DEF-5046), a commit origin lacks or a
    tracked edit in that checkout, which the arm would refuse on after the
    lane had moved. The plan set aside is the one in the session's checkout,
    which the mod reads and execution_plan.py writes. The commit is made
    even on a clean tracked tree (empty, the trailer alone), so the push
    guard holds where only a review is owed. The plan is demoted first and
    the commit made second: a demotion that fails changes nothing, and a
    commit that fails puts the plan back; the commit's body names the plan's
    record. Run again with HEAD already the unfinished commit, it amends
    that commit with the edits made since (or, with none, reads it as the
    one to name, its plan's record read back from its body)."""
    what = " ".join((text or "").split())
    if not what:
        raise _unfinished_refusal(f"{UNFINISHED_FLAG} takes what is left of the lane, in words the next window "
                                  "reads (the review owed, the step it stopped at)")
    why_not = _own_clear_gate()
    if why_not:
        raise _unfinished_refusal(f"{why_not}. {UNFINISHED_FLAG} arms the clear for a window whose own-clear mod "
                                  "clears it; elsewhere the window is cleared by hand, and the lane left as it "
                                  "is -- its edits, its plan -- is what the next window reads")
    where, _unplaced = own_clear_checkout(root)
    asked = _shared_reader("recorded_handoff_ask")
    if asked is None:
        raise _unfinished_refusal("tools/cc/hooks/_hook_utils.py is not beside this script, does not load, or is "
                                  "an older one without recorded_handoff_ask, so whether the prompt router asked "
                                  "this session for the threshold handoff cannot be read; espalier upgrade "
                                  "--execute . brings it level")
    if asked(where, os.environ.get(SESSION_ID_ENV, "")) is None:
        raise _unfinished_refusal(f"the prompt router has not asked this session for the threshold handoff (no "
                                  f"first-ask record for it in {where}), and {UNFINISHED_FLAG} is for a window "
                                  "past that threshold with no room left to finish its lane: finish the lane "
                                  "through its own landing, then /handoff")
    elsewhere = not _same_checkout(where, root)
    if elsewhere:
        # The arm reads this checkout's holds after the lane has moved; read
        # them first (its plan is the one set aside below, so not that).
        hold = _window_checkout_holds(where, with_plan=False)
        if hold:
            raise _unfinished_refusal(f"{where}, the checkout this session's mod reads, {hold}: settle it there "
                                      "first, then run it again")
    _refuse_a_shared_checkout(root)
    _refuse_a_marked_record(root)
    operation = _operation_in_progress(root)
    if operation:
        raise _unfinished_refusal(f"{operation} is in progress: finish or abandon it first; a commit now would "
                                  "seal it half-made into the lane")
    branch = current_branch()
    base_ref = _base_ref_offline(root)
    if base_ref is None:
        raise _unfinished_refusal("no origin/<default branch> ref is here to tell the lane from the base: "
                                  "git fetch origin, then run it again")
    base = base_ref.split("/", 1)[1]
    if branch == base:
        raise _unfinished_refusal(f"HEAD is {base}, the default branch, so no lane is there to name: commit the "
                                  "edits (/commit), python tools/cc/ship.py lane moves them to a lane branch, "
                                  "then run it again there")
    carries = lane_carries_memory_row(base, root)
    if carries is False:
        raise _unfinished_refusal(f"this lane's commits carry no Session Log row (no new file under "
                                  f"{SESSION_LOG_DIR}): /handoff writes it before this step, and the brief that "
                                  "clears this window says it is written")
    if carries is None:
        _note("whether the lane carries its Session Log row could not be read; going ahead without that check")
    rc, status, err = _git("status", "--porcelain", "-uno", cwd=str(root))
    if rc != 0:
        raise _unfinished_refusal(f"git status failed: {err.strip()[:200]}")
    edits = [line for line in status.splitlines() if line.strip()]
    head = head_sha(root)
    earlier = _unfinished_commits(root, base_ref) or []
    again = bool(earlier) and earlier[0][0] == head and len(earlier) == 1
    if earlier and not again:
        raise _unfinished_refusal(f"the lane already holds the unfinished commit {earlier[-1][0][:12]} below HEAD: "
                                  f"{_unfinished_on_lane(root, base_ref)}")
    rc, others, _ = _git("ls-files", "--others", "--exclude-standard", cwd=str(root))
    untracked = tuple(line.strip() for line in others.splitlines() if line.strip()) if rc == 0 else ()
    # Offline: the remote-tracking ref as last fetched (no fetch, no gh). On
    # origin, a pull request may be open, and the brief says so.
    rc, _, _ = _git("rev-parse", "-q", "--verify", f"refs/remotes/origin/{branch}", cwd=str(root))
    on_origin = rc == 0
    guarded = _guard_fails_unfinished(root)
    # The plan the mod holds on, and execution_plan.py writes, is the session's
    # checkout's: the lane checkout's own is it only where the two are one.
    plan_path = (where if elsewhere else root) / "cc" / "execution_plan.json"
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # fail-open: ok deliberate -- no plan file, or one that does not parse: the mod reads that as nothing in progress too
        plan = None
    in_progress = isinstance(plan, dict) and plan.get("status") == "in_progress" and bool(plan.get("steps"))
    task = str(plan.get("task") or "its task unnamed") if in_progress and isinstance(plan, dict) else ""
    module = _plan_module() if in_progress else None
    if in_progress and module is None:
        raise _unfinished_refusal("a plan is in progress and tools/cc/execution_plan.py, which sets it aside, is "
                                  "not beside this script or will not load; the mod holds the clear on the plan")
    if dry_run:
        plural = "s" if len(edits) != 1 else ""
        _say(f"dry-run: {UNFINISHED_FLAG} would set "
             + (f"the plan ({task}) aside in cc/_cold/, " if in_progress else "no plan aside (none in progress), ")
             + f"commit {len(edits)} tracked edit{plural} of {branch} as {UNFINISHED_SUBJECT!r} with its "
             f"{UNFINISHED_TRAILER} trailer, leave {len(untracked)} untracked file(s) beside it, and push nothing")
        return Unfinished(branch, what, "", "", "", task, untracked, on_origin=on_origin, guarded=guarded)
    plan_record, moved = "", None
    if in_progress and module is not None:
        try:
            moved = module.demote_plan(plan_path)
        except OSError as exc:
            raise _unfinished_refusal(f"the plan could not be set aside ({os_error_text(exc)}), and the mod holds "
                                      "the clear on it; nothing was committed") from None
        if moved is not None:
            # Whole where the session's checkout is not the lane's: the restore
            # then runs from the window's checkout, wherever this record sits.
            try:
                plan_record = (str(Path(moved).resolve()) if elsewhere
                               else Path(moved).resolve().relative_to(root.resolve()).as_posix())
            except ValueError:
                plan_record = str(moved)
    if again and not plan_record:
        # A second run whose plan is already in the cold store: the first
        # run's commit named it, and the brief names it again from there.
        plan_record, named_task = _plan_named_in(root, head)
        task = named_task or task
    lines = [f"What is left: {what}", "",
             "The threshold handoff set this unfinished lane aside. The window it clears takes it back "
             "with a soft reset to this commit's parent while HEAD is this commit; every ship-driver push of "
             "the lane refuses until then."]
    if plan_record:
        lines += ["", f"{UNFINISHED_PLAN_LINE}{plan_record}", f"{UNFINISHED_TASK_LINE}{task}",
                  f"It comes back with {_restore_words(plan_record)}."]
    commit, parent = (head, "") if again else ("", "")
    if edits or not again:
        # Always one commit: on a clean tracked tree an empty one, the trailer
        # alone, so the push guard holds where only a review is owed.
        made = ["-a"] if edits else ["--allow-empty"]
        amend = ["--amend"] if again else []
        rc, _, err = _git("commit", "--quiet", *made, *amend, "-m", UNFINISHED_SUBJECT, "-m", "\n".join(lines),
                          "-m", f"{UNFINISHED_TRAILER}: {branch}", cwd=str(root))
        if rc != 0:
            back = ""
            if moved is not None:
                try:
                    (getattr(_paths, "replace_retrying", None) or os.replace)(moved, plan_path)
                    back = "; the plan is back where it was"
                except OSError as exc:
                    back = (f"; the plan could not be put back ({os_error_text(exc)}): "
                            f"{_restore_words(plan_record)} restores it")
            raise _unfinished_refusal(f"git commit failed: {err.strip()[:200]}{back}")
        commit = head_sha(root)
    rc, out, _ = _git("rev-parse", f"{commit}^", cwd=str(root))
    parent = out.strip() if rc == 0 else ""
    rc, names, _ = _git("show", "--format=", "--name-only", commit, cwd=str(root))
    empty = rc == 0 and not names.strip()
    shown = (", ".join(untracked[:UNFINISHED_UNTRACKED_SHOWN])
             + (" and more" if len(untracked) > UNFINISHED_UNTRACKED_SHOWN else ""))
    _say(f"left {branch} unfinished: "
         + (f"{len(edits)} tracked edit(s) committed as {commit[:12]}" if edits else
            f"the unfinished commit {commit[:12]} kept" if again else
            f"an empty commit {commit[:12]} made (the tracked tree was clean; it carries the trailer)")
         + (f"; the plan ({task}) set aside at {plan_record}" if plan_record else "")
         + (f"; {len(untracked)} untracked file(s) left beside it ({shown})" if untracked else "")
         + "; nothing pushed, and the lane's claims stay live")
    return Unfinished(branch, what, commit, parent, plan_record, task, untracked, empty, on_origin, guarded)


def _plan_named_in(root: Path, commit: str) -> tuple[str, str]:
    """``(the plan record, its task)`` the unfinished commit's body names
    (:data:`UNFINISHED_PLAN_LINE`, :data:`UNFINISHED_TASK_LINE`), or two empty
    strings where it names none or git cannot read it."""
    rc, out, _ = _git("log", "-1", "--format=%B", commit, cwd=str(root))
    record = task = ""
    for line in (out.splitlines() if rc == 0 else []):
        if line.startswith(UNFINISHED_PLAN_LINE):
            record = line[len(UNFINISHED_PLAN_LINE):].strip()
        elif line.startswith(UNFINISHED_TASK_LINE):
            task = line[len(UNFINISHED_TASK_LINE):].strip()
    return record, task


def handoff(title: str | None = None, body_file: str | None = None, dry_run: bool = False,
            base_red_ruled: str | None = None, allow_deletions: str | None = None,
            subjects_body: str | None = None, unfinished: str | None = None) -> int:
    """/handoff's one push step, then the own-clear's arm. The push
    (:func:`_handoff_push`) runs only when espalier.toml sets ``handoff_push =
    true``, else the commit stays local and the verb says how to push it. Once
    that step has run to its end -- the off path said (its commit stays local
    by design and the window is done with it), the row parked, the pull
    request opened or the push re-bound, or a refusal the window is done with
    (:class:`Held`: the base is red, or this seat's other pull request is open,
    and the lane stays here whole; or the push landed and a step after it
    refused) -- the own-clear marker is armed for
    this session (:func:`arm_own_clear_here`), last; a held refusal rides the
    marker, the lane to land first rides the brief, and the refusal is
    re-raised (exit 1 still). A refusal the window must fix first -- a dirty
    tree, a shared checkout, a lane behind its remote, a rejected push --
    never arms, so no marker clears a window with work in it (DEF-4057: until
    this, no refusal armed, and three seats sat past the threshold with no
    clear). The arm itself never fails a handoff whose step has run: what
    stops it is said, with the by-hand reset. A dry run says what it would
    arm. ``unfinished`` (what is left, in the window's words) takes the place
    of the push for a lane the window cannot finish
    (:func:`_hand_off_unfinished`): nothing is pushed, and the marker is armed
    with the lane to finish."""
    if unfinished is not None:
        flags = [flag for flag, given in (("--title", title), ("--body-file", body_file),
                                          (BASE_RED_RULED_FLAG, base_red_ruled),
                                          (ALLOW_DELETIONS_FLAG, allow_deletions),
                                          (SUBJECTS_BODY_FLAG, subjects_body)) if given]
        if flags:
            raise _unfinished_refusal(f"{UNFINISHED_FLAG} pushes nothing, so {', '.join(flags)} has nothing to "
                                      "act on: drop it")
        root = repo_root()
        left = _hand_off_unfinished(root, unfinished, dry_run=dry_run)
        if dry_run:
            _say("dry-run: the own-clear marker would be armed for this session with the lane to finish in "
                 "its brief")
            return 0
        if _arm_or_say(unfinished=left):
            return 0
        # The arm is the whole point of this verb (the push handoff's is a
        # courtesy): the moves go where the window a hand /clear starts can
        # read them -- here, and the commit's body -- and the exit says so.
        where, _unplaced = own_clear_checkout(root)
        _say("the lane is set aside, but no marker clears this window: after a /clear by hand, the next window "
             "takes these moves first, or run it again once what stopped the arm is settled (it reads its own "
             "commit and arms):"
             + _finish_first_tail(left, lane_checkout=None if _same_checkout(where, root) else root))
        return 1
    try:
        rc = _handoff_push(title, body_file, dry_run, base_red_ruled, allow_deletions, subjects_body)
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


def _arm_or_say(*, held: Held | None = None, unfinished: Unfinished | None = None) -> bool:
    """The handoff's arm, which never fails the handoff: what stops it, the
    root's own read included, is said, with the by-hand reset. True where
    the marker was armed (the line :func:`arm_own_clear` writes)."""
    try:
        root = repo_root()
        if held is not None:
            line = arm_own_clear_here(root, held=held)
        elif unfinished is not None:
            line = arm_own_clear_here(root, unfinished=unfinished)
        else:
            line = arm_own_clear_here(root)
    except Exception as exc:  # noqa: BLE001 -- fail-open with voice: the step has run; the reset is said instead
        _note(f"the own-clear marker was not armed ({os_error_text(exc)}); this window will not clear itself, "
              "so it needs a /clear by hand")
        return False
    _say(line)
    return line.startswith("own-clear armed")


def _red_base_note(root: Path, base: str, pr: dict, branch: str, base_red_ruled: str | None) -> None:
    """A handoff onto an open pull request whose auto-merge was armed before
    the base went red: not a refusal (the handoff's row must reach the pull
    request, or park), but the armed merge lands on the red base -- by the
    dispatcher's ruling where one is given and holds, else named with the
    disarm. Said on the push and on the park alike."""
    red_run = base_red_run(base, cwd=str(root))
    if red_run is None or not pr.get("autoMergeRequest") or is_revert_lane(branch):
        return
    base_red = _red_base_words(base, red_run)
    number = pr.get("number")
    disarm = (f"#{number}'s auto-merge is armed and lands on the red base once its checks are green: "
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


def _handoff_push(title: str | None, body_file: str | None, dry_run: bool,
                  base_red_ruled: str | None = None, allow_deletions: str | None = None,
                  subjects_body: str | None = None) -> int:
    """The push half of :func:`handoff`. Off: the handoff's commit stays local
    and this says how to push it and how to opt in -- and, when a pull request
    is already open for the branch, that it will merge WITHOUT this commit. On:
    the lane is opened as a pull request, or, when one is already open, this
    commit is pushed onto it and the marker re-bound to the new head.
    ``base_red_ruled`` (an ack id) is the dispatcher's ruling that lets the
    lane land on a red base: handed to `open`, which judges it; on a push onto
    an open pull request, read here, where the base's red is a note.
    ``allow_deletions`` is `open`'s ``--allow-deletions``, judged on either
    push (DEF-4064)."""
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
    # The set-aside edits of an unfinished lane never ride a push (an open pull
    # request's armed auto-merge would land them), and its trailer commit is
    # never read as rows alone and parked away: asked before both row parks.
    # `open` asks the same reading in PRE_PUSH_CHECKS, catch-up and rebind too.
    _refuse_an_unfinished_lane(root, f"origin/{(pr or {}).get('baseRefName') or base}")
    # A handoff whose lane already merged carries its row alone: park it on the
    # records ref instead of opening a pull request for one row (DEF-5007).
    if pr is None and _park_the_row(root, base, dry_run=dry_run):
        return 0
    if on_base:
        if not body_file and _audit_setting(root) is not None:
            # `open`'s body question, asked before `lane` moves the commits
            # off the default branch: a refusal here leaves them where they were.
            _default_body(root, base, base, subjects_body)
        if dry_run:
            name = _lane_name_for(lane_subject(root, base)) or "a lane branch"
            _say(f"dry-run: `lane` would move the unmerged commits to {name}, then `open` "
                 "would push it as a pull request with auto-merge armed")
            return 0
        lane()
        pr = pr_for_branch(current_branch(), "open")
    branch = current_branch()
    if pr is None:
        return open_pr(title=title, body_file=body_file, dry_run=dry_run, base_red_ruled=base_red_ruled,
                       allow_deletions=allow_deletions, subjects_body=subjects_body)
    # A handoff whose commits since the pull request's head are rows alone
    # parks them rather than push a record onto the lane's running checks:
    # ahead of the merge-first and the fold below, each a push that cancels.
    # The park moves this branch onto origin's copy (reset --keep), which a
    # hand push may have left holding the set-aside commit: refused first.
    _refuse_set_aside_on_origin(root, branch)
    if _park_the_row(root, str(pr.get("baseRefName") or base), dry_run=dry_run, branch=branch, pr=pr):
        _red_base_note(root, str(pr.get("baseRefName") or base), pr, branch, base_red_ruled)
        if not dry_run:
            _release_claims(root, branch, "Handoff parked its rows; the lane is on its open pull request; "
                                          "claims closed.")
        return 0
    behind = _origin_ahead_refusal(branch, str(root))
    if behind:
        raise Refused(behind)
    # Before this path's push; the no-pull-request path above returns through
    # open_pr, which asks itself, and the rebind below asks and stands down.
    _wiring_note(root)
    # The handoff's push should leave the pull request mergeable, the same as a
    # first push would: merge ITS base in first when the lane would conflict.
    base = str(pr.get("baseRefName") or base)
    _git("fetch", "origin", base, "--quiet", cwd=str(root))
    _merge_base_first(root, base, dry_run=dry_run)
    _fold_session_log(root, base, dry_run=dry_run)
    # The same shape read as `open`'s, on the push onto the open pull request;
    # an allowed deletion is said here (the body was written at the open).
    shape = lane_shape(root, base)
    say_lane_shape(root, base, shape)
    refuse_unmade_deletions(shape, base, allow_deletions, branch)
    _red_base_note(root, base, pr, branch, base_red_ruled)
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
    handoff armed for this session at the HEAD this verb started from is
    re-armed at the new head once the move landed and the re-bind ran or
    refused (:func:`_rebind_then_rearm_own_clear`): the own-clear mod holds
    the clear on a moved head, and the hold stood until a re-arm by hand; a
    marker armed at an older head means a commit after the handoff moved HEAD
    first, and that handoff, which re-arms, is owed."""
    root = repo_root()
    _refuse_a_shared_checkout(root)   # both paths below change this checkout's lane and push or pull it
    _wiring_note(root)
    branch = current_branch()
    before = head_sha()   # the HEAD this verb starts from: the own-clear's re-arm follows the move only from here
    pr = _require_open_pr(branch)
    # Before either path moves anything: the conflicting arm pushes HEAD, and
    # the server's arm pulls onto it, so an unfinished lane's set-aside edits
    # would ride the next push (the re-primed window's loop ranks its own red
    # pull request first, ahead of the brief that says to take them back).
    _refuse_an_unfinished_lane(root, f"origin/{pr.get('baseRefName') or default_branch()}")
    # ...and origin's copy: the server's arm updates the branch holding a
    # set-aside commit a hand push put there, then pulls it back here.
    _refuse_set_aside_on_origin(root, branch)
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
        return _rebind_then_rearm_own_clear(root, branch, before, await_head=True)
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
        ahead = _ahead_words(branch, str(root))
        raise Refused(f"cannot fast-forward {branch}: an unpushed commit here ({err.strip()}); "
                      + (ahead or "push it") + ", then run catch-up again")
    return _rebind_then_rearm_own_clear(root, branch, before, await_head=False)


def _rebind_then_rearm_own_clear(root: Path, branch: str, moved_from: str, *, await_head: bool) -> int:
    """After a catch-up moved HEAD: the pull request's head awaited where this
    checkout pushed it, the re-bind, then the own-clear's re-arm
    (:func:`rearm_own_clear_after_move`) whether the re-bind ran or refused --
    the move landed either way, and a refusal rides the marker's brief, so
    the window the mod clears hands it on instead of clearing over it."""
    try:
        if await_head:
            _wait_for_pr_head(branch, head_sha())
        rc = rebind()
    except Refused as exc:
        _rearm_own_clear_or_note(root, by="catch-up", moved_from=moved_from, refusal=str(exc))
        raise
    _rearm_own_clear_or_note(root, by="catch-up", moved_from=moved_from)
    return rc


#: A required cell ends red for one of two reasons: its tests (or a person)
#: decided, or its runner never let them. Only the second is worth a re-run,
#: and only the shapes of it measured are recognised -- a positive list: the
#: two below, measured 2026-10-05 over sixty pull-request runs of the test
#: workflow, and a full disk (``_DISK_ERRNOS``, 2026-11-03). A job no hosted
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
#: Why ``_classify`` calls a cancelled job decided when its note says a newer
#: run superseded it: the one reason ``_read_required`` re-reads, since the
#: runs read is the rule and the note at most its second signal (DEF-3035).
_SUPERSEDED_BY_NOTE = "a newer run superseded it"
_DECIDED_NOTES = (
    ("higher priority waiting request", _SUPERSEDED_BY_NOTE),
    ("was canceled by", "cancelled by hand"),
    ("exceeded the maximum execution time", "it outran its timeout"),
)
#: A third shape the runner ends, and the one a failed step hides: measured
#: 2026-11-03 on four required cells on GitHub's AWS-hosted pool (#464's
#: `test (3.11)`, `test (3.14)` and `portability (ubuntu-latest)`, #470's
#: `test (3.13)`), where the runner's temp disk filled mid-suite, pytest died
#: of an internal error and the step exited 3 with 578 to 847 tests reported
#: failed, while the same diff was green on the Azure pool. The job ends
#: `failure` with a failed step, as a test red does, and its one note is the
#: generic "Process completed with exit code 3.", so the job's log alone tells
#: them apart. A section of the log runs from a step's `Run` group header to
#: the runner's exit line for that step, never above the exit line before it;
#: an exit line with no header in that span opens no section. A failed step is
#: the runner's only when the sections that exited 3 (pytest's internal-error
#: code, which the tier step passes through as its worst leg's) and hold an
#: internal-error line naming one of these errnos number at least the failed
#: steps the job API lists: counted, not matched step by step, since a
#: continue-on-error step writes an exit line too while the API calls it a
#: success. Anything else in a log that was read is the tests' verdict (a
#: wrapper that remaps pytest's exit, or a disk error outside an internal
#: error, reads so); a log that cannot be read is "cause not read". Since the
#: suite's temp dir moved to the runner's root disk, a full disk may be the
#: diff's own doing, so the words say the disk filled, not whose it was; the
#: one re-run is the bound. The words printed are this table's, never the log's.
_DISK_ERRNOS = (
    ("[Errno 122]", "[Errno 122] Disk quota exceeded"),
    ("[Errno 28]", "[Errno 28] No space left on device"),
)
_INTERNAL_ERROR = "INTERNALERROR>"
_PYTEST_INTERNAL_EXIT = "3"
#: The runner's own line ending a step that exited non-zero, and a step's
#: header, each matched at the start of one log line (a timestamp, a space,
#: the text), so a test's output that echoes a log never opens either.
_STEP_EXIT_RE = re.compile(r"(?:\S+ )?##\[error\]Process completed with exit code (\d+)\.")
_STEP_HEADER_RE = re.compile(r"(?:\S+ )?##\[group\]Run ")
#: The first gh release whose `gh api` takes --allow-escape-sequences (its
#: release notes, 2026-07-31); an older gh refuses the flag, and every job log
#: holds the runner's colour codes, so a job log needs the flag. How much of
#: gh's own refusal a reason quotes.
_GH_LOG_FLOOR = "2.97.0"
_GH_REASON_CHARS = 160
#: An Actions job's link as `gh pr checks --json link` gives it: run, then job.
#: The home's (tools/cc/_post_merge.py, whose ``read_required`` asks for the
#: link and reads the run from it, DEF-3035), so the two never drift.
_JOB_LINK_RE = _post_merge.JOB_LINK_RE
#: A finished job's conclusions that hold nothing, in the REST spelling.
_JOB_GREEN = frozenset(s.lower() for s in _CHECK_GREEN)


class _Reading:
    """The required checks of one pull request, sorted by what can be done.

    ``decided``: red cells whose tests or a person decided (and checks that are
    not Actions jobs, which nothing here re-runs). ``unread``: red cells this
    driver could not place, each with why and the command that shows its log.
    ``rerunnable``: run id -> the cells one re-run of that run retries.
    ``held``: lost cells the driver will not re-run now, each line saying why
    and what to do instead. ``pending``: still running. ``superseded``:
    cancelled cells a newer run of their workflow on this head supersedes
    (``_post_merge.superseded_runs``), a wait on that run, never a red to fix
    or re-run (DEF-3035). `status` prints this and `rerun` acts on it, so the
    two never disagree."""

    def __init__(self) -> None:
        self.decided: list[str] = []
        self.unread: list[str] = []
        self.rerunnable: dict[str, list[str]] = {}
        self.held: list[str] = []
        self.pending: list[str] = []
        self.superseded: list[str] = []


def _annotation_text(job_id: str, cwd: str) -> str | None:
    """A job's annotation messages, lower-cased and joined; None when they
    cannot be read (a read that outlives its wait included, as a log's)."""
    try:
        rc, out, _ = _gh("api", f"repos/{{owner}}/{{repo}}/check-runs/{job_id}/annotations", cwd=cwd)
    except Refused:
        return None
    if rc != 0:
        return None
    try:
        rows = json.loads(out or "")  # json-dict-safe: ok the list and each row are isinstance-checked below
    except ValueError:
        return None
    if not isinstance(rows, list):
        return None
    return " ".join(str(r.get("message") or "") for r in rows if isinstance(r, dict)).lower()


def _job_log(job_id: str, cwd: str) -> tuple[str | None, str]:
    """A finished job's log and ``""``, or None and why it could not be read.
    The jobs API serves it while the run's other jobs still go (`gh run view
    --log` waits for the whole run). gh from ``_GH_LOG_FLOOR`` on refuses a
    body holding an escape sequence without --allow-escape-sequences, and the
    runner colours every log, so the flag is what makes the read answer; an
    older gh refuses the flag, which the reason says, with the update."""
    try:
        rc, out, err = _gh("api", "--allow-escape-sequences",
                           f"repos/{{owner}}/{{repo}}/actions/jobs/{job_id}/logs", cwd=cwd)
    except Refused as exc:
        return None, str(exc)
    if rc == 0 and out.strip():
        return out, ""
    first = (err.strip().splitlines() or [f"gh exited {rc} with no log"])[0]
    if "unknown flag" in first.lower():
        return None, f"gh older than {_GH_LOG_FLOOR} cannot read a job's log: update gh"
    return None, first.encode("ascii", "replace").decode("ascii")[:_GH_REASON_CHARS]


def _runner_disk_full(log: str, failed_steps: int) -> str:
    """The errno's words (``_DISK_ERRNOS``) when the log's full-disk sections
    number at least the job's ``failed_steps`` (one or more), else ``""``."""
    lines = log.splitlines()
    found: list[str] = []
    floor = -1  # the previous exit line: no section reaches above it
    for end, line in enumerate(lines):
        m = _STEP_EXIT_RE.match(line)
        if m is None:
            continue
        above, floor = floor, end
        if m.group(1) != _PYTEST_INTERNAL_EXIT:
            continue
        start = next((i for i in range(end - 1, above, -1) if _STEP_HEADER_RE.match(lines[i])), None)
        if start is None:
            continue
        words = next((w for text in lines[start:end] if _INTERNAL_ERROR in text
                      for needle, w in _DISK_ERRNOS if needle in text), "")
        if words:
            found.append(words)
    return found[0] if failed_steps and len(found) >= failed_steps else ""


def _classify(job: dict | None, cwd: str) -> tuple[str, str]:
    """``("lost", why)`` when the runner, not the tests, ended this finished
    job; ``("decided", what)`` when its tests or a person did; ``("unread",
    why)`` when this driver cannot place it. The notes are read only when the
    steps leave the question open; a failed step's log is read for the one
    runner shape a failed step hides (``_DISK_ERRNOS``)."""
    if job is None:
        return "unread", "its job is not in the run's latest attempt"
    conclusion = str(job.get("conclusion") or "").lower()
    each = [str(s.get("conclusion") or "").lower() for s in job.get("steps") or [] if isinstance(s, dict)]
    steps = set(each)
    if conclusion == "failure" and "failure" in steps:
        job_id = str(job.get("databaseId") or "")
        log, why = _job_log(job_id, cwd) if job_id.isdigit() else (None, "the job has no id")
        if log is None:
            return "unread", f"a step failed and its log could not be read [{why}]"
        words = _runner_disk_full(log, each.count("failure"))
        if words:
            return "lost", f"the disk filled: {words}"
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


def _read_required(number: str, cwd: str, merge_state: str = "", head: str = "") -> _Reading | None:
    """The pull request's required checks as a ``_Reading``, or None when the
    answer could not be read -- a repository with no required checks at all
    answers rc=1 with no JSON, the common adopter posture, and that is "could
    not read", not a red.

    ``head`` is the pull request's head commit, whose runs tell a cancelled
    cell a newer run supersedes (``_post_merge.superseded_runs``): a wait,
    never a red (DEF-3035). A cancelled cell whose own run that read did not
    list (it was not made, did not answer with a listing, or the run lies
    past it) is not known to be free of a newer run: where its note says a
    newer run superseded it, or offers a re-run (no runner picked it up),
    the cell is unread, never decided or re-run. The note alone is not the
    rule (a cell cancelled before it starts carries none), and both "fix,
    push, rebind" and a re-run would cancel a newer run going.

    A lost cell is offered for a re-run only when its whole run can take one
    -- finished, never re-run (GitHub's attempt counter is the bound, so
    "once" holds across sessions and machines), and with no other red in it,
    since ``gh run rerun --failed`` retries every failed job in the run, a
    flaky decided one included -- and only when nothing else holds the merge:
    a decided or unread red, another lost run that is held, or a lane behind
    or in conflict with its base, where catch-up re-runs every cell anyway."""
    def runs(args: list[str]) -> object:
        try:
            return _gh_json(*args, cwd=cwd)
        except Refused:
            return None

    try:
        required = _post_merge.read_required(number, lambda args: _gh_json(*args, cwd=cwd), head=head, runs=runs)
    except Refused:
        return None
    if required is None:
        return None
    reading = _Reading()
    reading.pending.extend(str(row.get("name") or "?") for row in required["running"])
    reading.superseded.extend(sorted(str(row.get("name") or "?") for row in required["superseded"]))
    by_run: dict[str, list[tuple[str, str]]] = {}
    #: The cancelled cells whose own run the runs read did not list: whether a
    #: newer run supersedes them is not known (DEF-3035), so neither a note
    #: saying so nor one offering a re-run decides them.
    unconfirmed: set[tuple[str, str]] = set()
    for row in required["red"]:
        name = str(row.get("name") or "?")
        m = _JOB_LINK_RE.search(str(row.get("link") or ""))
        if m is None:
            reading.decided.append(name)  # not an Actions job: nothing here re-runs it
        else:
            by_run.setdefault(m.group(1), []).append((name, m.group(2)))
            if str(row.get("bucket") or "").lower() == "cancel" and m.group(1) not in required["listed"]:
                unconfirmed.add((name, m.group(2)))
    where = f"gh api {' '.join(_post_merge.runs_on_head(head)[1:])}" if head else "no head commit was read"
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
            if (name, job_id) in unconfirmed and (kind == "lost" or why == _SUPERSEDED_BY_NOTE):
                # A re-run here would cancel a newer run going, and a push
                # made on "fix" would too: only the runs read settles it.
                reading.unread.append(f"{name} ({why}, by its notes, and the runs on its head did not list its "
                                      f"run to say whether a newer one supersedes it: {where})")
            elif kind == "lost":
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


def _superseded_wait(cells: list[str]) -> str:
    """The words ``status`` and ``rerun`` give the cells a newer run of their
    workflow on this head supersedes: a wait, never a fix (DEF-3035). The
    rule sees that the newer run is going, not that it will report the job,
    so the words say what is known and when to read again."""
    one = len(cells) == 1
    return (f"{', '.join(cells)} -- a newer run of {'its' if one else 'their'} workflow on this head is still "
            "going; re-read when it ends")


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
    reading = _read_required(number, str(root), str(pr.get("mergeStateStatus") or "").upper(),
                             str(pr.get("headRefOid") or ""))
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
        if reading.superseded:
            still += f"; {_superseded_wait(reading.superseded)}"
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
    if reading.superseded:
        _say(f"#{number}: not re-run, superseded: {_superseded_wait(reading.superseded)}")
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
        reading = _read_required(number, str(root), str(pr.get("mergeStateStatus") or "").upper(),
                                 str(pr.get("headRefOid") or ""))
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
            if reading.superseded:
                _say(f"required, superseded: {_superseded_wait(reading.superseded)}")
            if not (reading.decided or reading.unread or reading.rerunnable or reading.held or reading.superseded):
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

#: `open`'s and `handoff`'s --body-file help: the default it replaces is
#: :func:`_default_body`'s.
_BODY_FILE_HELP = ("the pull request body (default: this seat's Session Log rows on the lane, then the commit "
                   "subjects; the subjects alone where it carries none)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ship.py", description=__doc__.split("\n\n", 1)[0])
    sub = parser.add_subparsers(dest="verb", required=True)
    sub.add_parser("preflight", help="clean tree, non-empty range, post-merge reds, the per-lane handoff notice")
    sub.add_parser("lane", help="on the default branch, move the unmerged commits to a lane")
    p_open = sub.add_parser("open", help="push once, open the pull request (marker bound), arm auto-merge")
    p_open.add_argument("--title", help="the pull request title (default: the subject of the lane's newest commit "
                        "that is neither a merge nor a Session Log row alone; HEAD's where it has none)")
    p_open.add_argument("--body-file", help=_BODY_FILE_HELP)
    p_open.add_argument("--dry-run", action="store_true")
    p_open.add_argument("--early", metavar="REASON",
                        help="ship before the handoff where handoff_push is on, saying why (with "
                             "--body-file where espalier.toml names a dispatcher: the lane carries no row)")
    p_open.add_argument(BASE_RED_RULED_FLAG, metavar="ACK_ID", dest="base_red_ruled",
                        help="land on a red base by the dispatcher's ruling: the ack with this id, on the "
                             "mail channel, names the red post-merge run")
    p_open.add_argument(ALLOW_DELETIONS_FLAG, metavar="WHY", dest="allow_deletions",
                        help="push a lane that deletes files the driver did not delete, saying why (the "
                             "pull request's body records it)")
    p_open.add_argument(SUBJECTS_BODY_FLAG, metavar="WHY", dest="subjects_body",
                        help="ship the commit subjects alone as the body where espalier.toml names a "
                             "dispatcher and the lane carries code and no row of this seat, saying why "
                             "(the body records it)")
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
    p_hand.add_argument("--title", help="the pull request title (default: the subject of the lane's newest commit "
                        "that is neither a merge nor a Session Log row alone; HEAD's where it has none)")
    p_hand.add_argument("--body-file", help=_BODY_FILE_HELP)
    p_hand.add_argument("--dry-run", action="store_true")
    p_hand.add_argument(BASE_RED_RULED_FLAG, metavar="ACK_ID", dest="base_red_ruled",
                        help="land on a red base by the dispatcher's ruling, as `open` takes it")
    p_hand.add_argument(ALLOW_DELETIONS_FLAG, metavar="WHY", dest="allow_deletions",
                        help="push deletions the driver did not make, saying why, as `open` takes it")
    p_hand.add_argument(SUBJECTS_BODY_FLAG, metavar="WHY", dest="subjects_body",
                        help="ship the commit subjects alone as the body, saying why, as `open` takes it")
    p_hand.add_argument(UNFINISHED_FLAG, metavar="WHAT_IS_LEFT", dest="unfinished",
                        help="the threshold handoff of a lane this window cannot finish: set its plan aside, "
                             "commit its tracked edits, push nothing, and arm the own-clear with the lane to "
                             "finish in the brief (only after the prompt router's threshold ask)")
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
                           early=args.early, base_red_ruled=args.base_red_ruled,
                           allow_deletions=args.allow_deletions, subjects_body=args.subjects_body)
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
                           base_red_ruled=args.base_red_ruled, allow_deletions=args.allow_deletions,
                           subjects_body=args.subjects_body, unfinished=args.unfinished)
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
