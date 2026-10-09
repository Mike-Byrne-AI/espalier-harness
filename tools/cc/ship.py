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
                         merges' post-merge reds, and (where handoff_push is
                         on) whether this lane carries its handoff row
    lane                 on the default branch: move the unmerged commits to a
                         lane named from the head subject (a no-op elsewhere)
    open                 push once; open the pull request WITH the approval
                         marker already in the title when the diff needs one
                         (one event, one run, no edit); arm auto-merge; read
                         the arming back. First, when the lane would conflict
                         with the base, merge the base in locally with the
                         record files resolved by shape (record_merge.py), so
                         the pull request is born mergeable and the merge
                         rides the one push
    rebind               after an exceptional second push: re-bind the title
                         to the pull request's head, forcing a fresh run
    catch-up             under an up-to-date rule: merge the base in -- on the
                         server when GitHub reads the lane clean, locally with
                         the record files resolved by shape when it reads it
                         CONFLICTING (the server honours no merge driver) --
                         then pull or push, and re-bind
    status               the pull request's state, merge state, required reds,
                         and apart from them the cells a lost runner ended
    rerun                re-run those cells once, when nothing else holds the
                         merge: the run is finished, was never re-run, and no
                         other red stands; otherwise says what does
    release vX.Y.Z       after the merge: tag the merge commit, push that one
                         tag, create the release
    handoff              /handoff's one push step: pushes only when
                         espalier.toml sets handoff_push = true (off by
                         default: a push is outward-facing), else says so

Stdlib-only (``tools/cc/`` runs standalone, zero espalier imports); the guard
it asks about (``tools/cc/ci_guard.py``, an install-ci artifact) is loaded by
path when present, never imported. Operator-facing text is 7-bit ASCII.
Exit 0 on success, 1 on a named refusal, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

# Sibling helpers, reached through the script's own directory (both ship in the
# deploy set; tests/test_deploy_set_import_closure.py pins the reachability).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _json_safe import decode_text_or_problem, fold_newlines, os_error_text  # noqa: E402
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
#: The banner's check-state sets (session_start.py), restated for a tool that
#: cannot import a hook: green and running states, and states that reach no
#: verdict; a red is any other state. sister-site: ok a two-site restatement, the hook cannot be imported from tools/cc/
_CHECK_GREEN = frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})
_CHECK_RUNNING = frozenset({"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"})
_NO_VERDICT = frozenset({"CANCELLED", "STALE"})
#: The workflow that proves the merged combination on the base branch after each
#: push (`.github/workflows/post-merge.yml`); a repository without it reads no runs.
POST_MERGE_WORKFLOW = "post-merge.yml"
#: The step the live-read workflow carries; its absence means the guard on
#: this tree judges the event payload's title.
LIVE_READ_STEP = "Read the pull request title as it is now"


def _check_outcome(row: object) -> str:
    """'green', 'running' or 'red' for one statusCheckRollup row, the banner's
    rule verbatim (tests/test_hook_constant_parity.py pins the sets equal): a
    row of a shape this reader does not know reads as running, not as a pass."""
    if not isinstance(row, dict):
        return "running"
    state = row.get("state")
    if isinstance(state, str) and state:  # StatusContext
        s = state.upper()
        return "green" if s in _CHECK_GREEN else "running" if s in _CHECK_RUNNING else "red"
    if str(row.get("status") or "").upper() != "COMPLETED":
        return "running"
    return "green" if str(row.get("conclusion") or "").upper() in _CHECK_GREEN else "red"


class Refused(Exception):
    """A named stop. The message is the reason the operator reads; exit 1."""


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
        result = subprocess.run(
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


def lane_carries_memory_row(base: str, root: Path) -> bool | None:
    """Do this lane's own commits (``origin/<base>..HEAD``) touch
    ESPALIER_MEMORY.md? None when git cannot answer: no verdict is ever a
    refusal on a guess."""
    rc, out, _ = _git("log", "--format=%h", f"origin/{base}..HEAD", "--", "ESPALIER_MEMORY.md",
                      cwd=str(root))
    if rc != 0:
        return None
    return bool(out.strip())


def _second_push_message(how: str) -> str:
    return (f"{how}, and this lane's commits never touch ESPALIER_MEMORY.md: /handoff writes the row "
            "and ships the lane once. To ship before it, pass --early \"<reason>\" to `open` (the "
            "handoff's row then becomes a second push on this lane)")


def post_merge_reds(cwd: str | None = None) -> list[str]:
    """One line per recently merged pull request whose latest run of a check
    is red -- a check that is not required finishes after auto-merge has
    landed the lane and reports to nobody unless something reads it (the
    banner's `Merged:` rule, restated for a tool that cannot import the hook)."""
    rows = _gh_json("pr", "list", "--author", "@me", "--state", "merged", "--limit", str(POST_MERGE_ROWS),
                    "--json", "number,statusCheckRollup", cwd=cwd)
    lines: list[str] = []
    if not isinstance(rows, list):
        return lines
    for pr in rows:
        if not isinstance(pr, dict):
            continue
        latest: dict[str, tuple[str, dict]] = {}
        for row in pr.get("statusCheckRollup") or []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or row.get("context") or "?")
            started = str(row.get("startedAt") or "")
            if name not in latest or started >= latest[name][0]:
                latest[name] = (started, row)
        reds = []
        for name, (_, row) in sorted(latest.items()):
            if _check_outcome(row) != "red":
                continue
            if str(row.get("conclusion") or "").upper() in _NO_VERDICT:
                continue  # cancelled or stale: no verdict, the banner's Merged: rule
            reds.append(name)
        if reds:
            lines.append(f"red after merge: #{pr.get('number')} {', '.join(reds)}")
    return lines


def base_red_after_merge(base: str, cwd: str | None = None) -> str | None:
    """A line when the base branch's latest post-merge run on a push reached a red
    verdict -- the post-merge proof of the merged combination, which no pull
    request's rollup carries. Without the up-to-date rule, two lanes each green
    on its own base can red together, and this run is where that shows. A run
    still going, cancelled by a newer push, or stale is no verdict: the newer run
    proves a superset."""
    runs = _gh_json("run", "list", "--workflow", POST_MERGE_WORKFLOW, "--branch", base, "--event", "push",
                    "--limit", "5", "--json", "databaseId,status,conclusion,headSha,url", cwd=cwd)
    if not isinstance(runs, list):
        return None
    for run_ in runs:
        if not isinstance(run_, dict) or str(run_.get("status") or "").lower() != "completed":
            continue
        conclusion = str(run_.get("conclusion") or "").upper()
        if conclusion in _NO_VERDICT:
            continue
        if conclusion == "SUCCESS":
            return None
        return (f"{base} red after merge: {POST_MERGE_WORKFLOW} run {run_.get('databaseId')} on "
                f"{str(run_.get('headSha') or '')[:7]} concluded {conclusion.lower()} "
                f"({run_.get('url')}); read it before landing another lane on top")
    return None


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
        record = [n for n in names or [] if n in record_merge.ROSTER]
        other = [n for n in names or [] if n not in record_merge.ROSTER and n not in driven]
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
    base_red = base_red_after_merge(base, cwd=str(root))
    if base_red:
        _say(base_red)
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
            early: str | None = None) -> int:
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
    on, how = handoff_push_setting(root)
    if on and lane_carries_memory_row(base, root) is False:
        early_reason = (early or "").strip()
        if not early_reason:
            raise Refused(_second_push_message(how))
        _note(f"shipping before the handoff ({early_reason}): its row will be a second push on this lane")
    else:
        early_reason = ""
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
    # The merge-first step, then the marker's sha: a merge commit moves HEAD,
    # and a marker bound to the old head is the stall rebind exists to clear.
    _merge_base_first(root, base, dry_run=dry_run)
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
    if dry_run:
        _say("dry-run: " + " ".join(push))
        _say(f"dry-run: gh pr create --base {base} --title '{title}' --body-file <tmp>")
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
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".md", delete=False) as fh:
            fh.write(body)
            body_path = fh.name
        try:
            rc, out, err = _gh("pr", "create", "--base", base, "--title", title, "--body-file", body_path, cwd=str(root))
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
    except Refused:
        _release_claims(root, branch, "Lane pushed; claims closed.")
        raise
    _say(f"#{number} open, auto-merge armed, one push: {url}")
    _release_claims(root, branch, f"Lane shipped as #{number}; claims closed.")
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


def handoff(title: str | None = None, body_file: str | None = None, dry_run: bool = False) -> int:
    """/handoff's one push step. Pushes only when espalier.toml sets
    ``handoff_push = true``; otherwise the handoff's commit stays local and this
    says how to push it and how to opt in -- and, when a pull request is already
    open for the branch, that it will merge WITHOUT this commit. On: the lane is
    opened as a pull request, or, when one is already open, this commit is pushed
    onto it and the marker re-bound to the new head."""
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
    base = default_branch()
    if current_branch() == base:
        if dry_run:
            _say("dry-run: `lane` would move the unmerged commits to a lane branch, then `open` "
                 "would push it as a pull request with auto-merge armed")
            return 0
        lane()
    branch = current_branch()
    pr = pr_for_branch(branch, "open")
    if pr is None:
        return open_pr(title=title, body_file=body_file, dry_run=dry_run)
    behind = _remote_has_commits_we_lack(branch, str(root))
    if behind:
        raise Refused(f"origin/{branch} has {behind} commit(s) this HEAD does not reach: merge them in "
                      f"(git merge origin/{branch}); never rebase or force-push a pushed lane")
    # The handoff's push should leave the pull request mergeable, the same as a
    # first push would: merge ITS base in first when the lane would conflict.
    base = str(pr.get("baseRefName") or base)
    _git("fetch", "origin", base, "--quiet", cwd=str(root))
    _merge_base_first(root, base, dry_run=dry_run)
    if dry_run:
        _say(f"dry-run: git push origin {branch}; then rebind the marker to the new head")
        return 0
    rc, _, err = _git("push", "origin", branch, cwd=str(root))
    if rc != 0:
        raise Refused(f"git push failed: {err.strip()[:200]}")
    _wait_for_pr_head(branch, head_sha())
    rc = rebind()
    if rc == 0:
        _release_claims(root, branch, "Handoff pushed onto the open pull request; claims closed.")
    return rc


def catch_up() -> int:
    root = repo_root()
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
#: holds it as surely as a failed one. sister-site: ok the banner's twin, pinned equal by tests/test_hook_constant_parity.py
_RED_BUCKETS = frozenset({"fail", "cancel"})
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
    p_rebind = sub.add_parser("rebind", help="re-bind the title marker to the pull request's head")
    p_rebind.add_argument("--dry-run", action="store_true")
    sub.add_parser("catch-up", help="merge the base in (on the server when clean; locally, record files "
                                    "resolved by shape, when GitHub reads the lane CONFLICTING), re-bind")
    sub.add_parser("status", help="state, merge state, required reds (a lost runner's apart), auto-merge")
    p_rerun = sub.add_parser("rerun", help="re-run once the required cells a lost runner ended")
    p_rerun.add_argument("--dry-run", action="store_true")
    p_rel = sub.add_parser("release", help="after the merge: tag the merge commit, push it, create the release")
    p_rel.add_argument("tag")
    p_rel.add_argument("--dry-run", action="store_true")
    p_hand = sub.add_parser("handoff", help="/handoff's push: only when espalier.toml sets handoff_push = true")
    p_hand.add_argument("--title", help="the pull request title (default: the head commit's subject)")
    p_hand.add_argument("--body-file", help="the pull request body (default: the commit subjects)")
    p_hand.add_argument("--dry-run", action="store_true")
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
                           early=args.early)
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
        if args.verb == "handoff":
            return handoff(title=args.title, body_file=args.body_file, dry_run=args.dry_run)
    except Refused as stop:
        print(f"ship: refused -- {stop}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    from _json_safe import pin_utf8_streams

    pin_utf8_streams()
    sys.exit(main())
