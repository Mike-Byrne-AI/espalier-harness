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
                         merges' post-merge reds, and whether the handoff has run
    lane                 on the default branch: move the unmerged commits to a
                         lane named from the head subject (a no-op elsewhere)
    open                 push once; open the pull request WITH the approval
                         marker already in the title when the diff needs one
                         (one event, one run, no edit); arm auto-merge; read
                         the arming back
    rebind               after an exceptional second push: re-bind the title
                         to the pull request's head, forcing a fresh run
    catch-up             under an up-to-date rule: merge the base in on the
                         server, pull, re-bind
    status               the pull request's state, merge state, required reds
    release vX.Y.Z       after the merge: tag the merge commit, push that one
                         tag, create the release

Stdlib-only (``tools/cc/`` runs standalone, zero espalier imports); the guard
it asks about (``tools/cc/ci_guard.py``, an install-ci artifact) is loaded by
path when present, never imported. Operator-facing text is 7-bit ASCII.
Exit 0 on success, 1 on a named refusal, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import datetime as _dt
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

MARKER = "HARNESS-UPDATE-APPROVED"
#: A bound marker anywhere in a title: the word, `@`, a hex run of seven or
#: more (git's short form up to a full sha) not glued to another word.
_MARKER_RE = re.compile(r" *" + MARKER + r"@[0-9a-fA-F]{7,40}(?![A-Za-z0-9])")
_MEMORY_ROW_DATE_RE = re.compile(r"^\| (\d{4}-\d{2}-\d{2}) \|", re.M)

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
        cwd: str | None = None) -> tuple[int, str, str]:
    """The one spawn. Resolves the program through PATH (so `gh.exe` on Windows
    is found by its bare name), never a shell, always a timeout, stdin closed
    unless input is given. A program that is missing, that cannot start or
    that outlives the timeout is a named refusal, not a traceback."""
    prog = shutil.which(argv[0])
    if prog is None:
        raise Refused(f"{argv[0]} is not on PATH")
    stdin_kw: dict = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
    try:
        # subprocess-contract: ok the argv is the caller's by design (one runner for every verb); each verb's argv is pinned by tests/test_ship_driver.py through the injectable runner
        result = subprocess.run(
            [prog, *argv[1:]], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, cwd=cwd, **stdin_kw,
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
        return json.loads(out or "")  # json-dict-safe: ok every caller isinstance-checks the answer before a deref (pr_for_branch, _required_reds, open_pr, rebind)
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
                    "--json", "number,title,url,state,headRefOid,mergeStateStatus,autoMergeRequest,mergeCommit")
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


def newest_memory_row_date(root: Path) -> str | None:
    memory = root / "ESPALIER_MEMORY.md"
    if not memory.is_file():
        return None
    try:
        raw = memory.read_bytes()
    except OSError:
        return None
    text, problem = decode_text_or_problem(raw)
    if problem:
        return None  # memory_problem names it; the date question has no answer
    dates = _MEMORY_ROW_DATE_RE.findall(text)
    return max(dates) if dates else None


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


def preflight(today: str | None = None) -> int:
    root = repo_root()
    base = default_branch()
    _git("fetch", "origin", "--quiet", cwd=str(root))
    rc, out, err = _git("status", "--porcelain", "-uno", cwd=str(root))
    if rc != 0:
        raise Refused(f"git status failed: {err.strip()}")
    if out.strip():
        raise Refused("the tracked tree is dirty: /commit first (ship moves commits, never a dirty tree)")
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
    for line in post_merge_reds(cwd=str(root)):
        _say(line)
    newest = newest_memory_row_date(root)
    today = today or _dt.date.today().isoformat()
    if newest is None:
        _note(memory_problem(root)
              or "cannot tell whether the handoff has run: ESPALIER_MEMORY.md is absent or carries no dated row")
    elif newest != today:
        _note(f"the newest ESPALIER_MEMORY.md row is dated {newest}, not today: the handoff has not run this "
              f"session, so shipping now makes its row a second push (a tier restart and a re-bind). "
              f"/handoff ships the lane once; ship early only when the next lane needs this merge "
              f"(a second lane on the same day gets no notice: the row's date is all this reads).")
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


def open_pr(title: str | None = None, body_file: str | None = None, dry_run: bool = False) -> int:
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
    sha = head_sha()
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
    # The base is fetched and the guard question asked BEFORE the push: the
    # diff against the fetched base needs nothing on the remote, so a diff
    # that fails or lists nothing refuses with the lane still unpushed, and a
    # dry run can answer the one question worth rehearsing -- which paths bind.
    _git("fetch", "origin", base, "--quiet", cwd=str(root))
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
    _say(f"#{number} open, auto-merge armed, one push: {url}")
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


def catch_up() -> int:
    root = repo_root()
    branch = current_branch()
    pr = _require_open_pr(branch)
    number = str(pr["number"])
    was = str(pr.get("headRefOid", ""))
    rc, out, err = _gh("pr", "update-branch", number, cwd=str(root))
    if rc != 0:
        if "up-to-date" in (out + err) or "up to date" in (out + err):
            _say(f"#{number} is not behind its base: the hold is something else -- run `status`")
            return 0
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


def _required_reds(number: str, cwd: str) -> list[str] | None:
    """The required checks that are red, or None when the answer could not be
    read -- a repository with no required checks at all answers rc=1 with no
    JSON, the common adopter posture, and that is "could not read", not a red."""
    try:
        rows = _gh_json("pr", "checks", number, "--required", "--json", "name,bucket", cwd=cwd)
    except Refused:
        return None
    if not isinstance(rows, list):
        return None
    return sorted(str(r.get("name") or "?") for r in rows
                  if isinstance(r, dict) and str(r.get("bucket") or "").lower() == "fail")


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
        reds = _required_reds(number, str(root))
        if reds:
            _say(f"required red: {', '.join(reds)} -- fix, push, rebind")
        elif reds is None:
            _say("could not read which checks are required")
        else:
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
    sub.add_parser("preflight", help="clean tree, non-empty range, post-merge reds, the handoff notice")
    sub.add_parser("lane", help="on the default branch, move the unmerged commits to a lane")
    p_open = sub.add_parser("open", help="push once, open the pull request (marker bound), arm auto-merge")
    p_open.add_argument("--title", help="the pull request title (default: the head commit's subject)")
    p_open.add_argument("--body-file", help="the pull request body (default: the commit subjects)")
    p_open.add_argument("--dry-run", action="store_true")
    p_rebind = sub.add_parser("rebind", help="re-bind the title marker to the pull request's head")
    p_rebind.add_argument("--dry-run", action="store_true")
    sub.add_parser("catch-up", help="merge the base in on the server, pull, re-bind")
    sub.add_parser("status", help="state, merge state, required reds, auto-merge")
    p_rel = sub.add_parser("release", help="after the merge: tag the merge commit, push it, create the release")
    p_rel.add_argument("tag")
    p_rel.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verb == "preflight":
            return preflight()
        if args.verb == "lane":
            return lane()
        if args.verb == "open":
            return open_pr(title=args.title, body_file=args.body_file, dry_run=args.dry_run)
        if args.verb == "rebind":
            return rebind(dry_run=args.dry_run)
        if args.verb == "catch-up":
            return catch_up()
        if args.verb == "status":
            return status()
        if args.verb == "release":
            return release(args.tag, dry_run=args.dry_run)
    except Refused as stop:
        print(f"ship: refused -- {stop}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
