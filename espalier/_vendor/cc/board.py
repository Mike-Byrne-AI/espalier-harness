#!/usr/bin/env python3
"""The board: one live read of what a seat needs before it states state.

Parallel seats (one session in its own named worktree, on any machine) state
what is open, merging, blocked or red. Three seats once each believed a
different branch was merging, because each read a
snapshot: its banner, a handoff note, the mail, its own context. This prints,
read now: the merge rules, the post-merge verdict on the base branch (and on a
red one, the pull request that turned it red and the revert), every open pull
request with its seat and what GitHub says holds it -- and, for one whose armed
auto-merge would land it on its own green CI, whether the base has moved near
its files since that CI ran -- the seats (every machine's last mail, and for
this clone's checkouts the live Claude Code sessions in each, two in one
checkout flagged), the dispatcher's live assignments, the asks (requests no
ack names, oldest first), the live claims, the overlaps between lanes of
different seats (which functions two of them both change), and the ledger's
live row count at the base branch's tip (a checkout that stops moving would
otherwise report its own). A seat with no checkout in this clone -- another
machine, another clone, or a worktree since removed, which the channel cannot
tell apart -- is its last mail and nothing more.

Read-only: it writes nothing into the tree, sends nothing, and moves no ref
beyond the mail fetch and the base branch's remote-tracking ref; it also
fetches the open pull requests' heads by object id, which lands objects and
moves no ref. All three are skipped with ``--no-fetch``; the ledger count reads
the base's files from a temporary directory outside the tree. Each section is
read on its own, and one that cannot be read says so on its own line instead
of hiding the rest.

    python tools/cc/board.py [--no-fetch] [--json] [--root PATH]

Stdlib-only (``tools/cc/`` runs standalone, zero espalier imports); every
spawn is ``record_merge.run``. Text is 7-bit ASCII. Exit 0, or 2 on a usage
error.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# Sibling helpers, reached through the script's own directory (all ship in the
# deploy set; tests/test_deploy_set_import_closure.py pins the reachability).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _merge_rules  # noqa: E402  the merge-rules read, shared with the SessionStart banner
import _symbols  # noqa: E402  the symbols a head changed and the one pair rule, shared with mail's claims
import mail  # noqa: E402  the claims and assignments folds
from _json_safe import os_error_text  # noqa: E402  an OSError rendered as its path and reason
from _record_fragments import LEDGER_DIR, LEDGER_FILE  # noqa: E402  the ledger and its rows, named once by the loader
from record_merge import Unresolvable, run  # noqa: E402  the one spawn and the named stop

Runner = Callable[..., tuple[int, str, str]]

#: The post-merge proof workflow (``.github/workflows/post-merge.yml``), the
#: same file ``ship.py``'s ``POST_MERGE_WORKFLOW`` names.
POST_MERGE_WORKFLOW = "post-merge.yml"
#: The conclusions that are a red verdict. Everything else a completed run can
#: conclude -- cancelled (by hand, or on a repository whose workflow cancels an
#: older run at a newer push), stale, skipped by a job-level `if`,
#: neutral, action required -- is no verdict, so a skipped run never reads as a
#: red base that asks a seat to revert someone's merge.
_RED = frozenset({"FAILURE", "TIMED_OUT", "STARTUP_FAILURE"})
#: How many post-merge runs to read back. Runs overlap (each push's goes to the
#: end, beside the next one), and a red or still-going run sits between a red
#: verdict and the last green before it, so the two can be several runs apart.
RUN_WINDOW = 20
#: A pull request's merge on the base: a merge commit ("Merge pull request
#: #158 from ...") or a squash ("subject (#158)"), read from the first line.
_PR_MERGE_RE = re.compile(r"^Merge pull request #(\d+)\b|\(#(\d+)\)\s*$")
GH_TIMEOUT = 15.0
OPEN_PR_LIMIT = 30
LEDGER = LEDGER_FILE
#: What the ledger count reads from the base tree: ``tools/cc`` (the generator
#: and every sibling it loads by path, the fragment loader among them), the
#: ledger, and its row files where the base keeps them.
BASE_COUNT_PATHS = ("tools/cc", LEDGER, LEDGER_DIR)
LEDGER_ROWS = LEDGER_DIR + "/"
CC = "tools/cc/"
#: The child that counts the base's ledger: a cold interpreter loading two
#: modules over a few hundred row texts.
BASE_COUNT_TIMEOUT = 60.0
#: Run (``-I``: no user site, no ``PYTHONPATH``, nothing from the working
#: directory) against the base's own top-level ``tools/cc`` modules, written to
#: a temporary directory, with the ledger and its row texts on stdin as ASCII
#: JSON (the child reads stdin in the locale's encoding on Windows): the base's
#: generator and fragment loader count them, so a checkout on older code reads
#: a newer base the way the base reads itself, and a base from before row files
#: (no ``record_fragments``) is its file alone. It also prints where the base's
#: loader keeps the ledger and its rows: the archive was cut by this checkout's
#: names, so a base that moved them is refused by name, never counted as the
#: file alone. A child, not an in-process load: the base's modules would
#: otherwise share ``sys.modules`` names with this checkout's. The names it
#: calls are pinned by tests/test_board_ledger_base.py and change by expand,
#: then contract (root CLAUDE.md Core Rule 15).
_BASE_COUNT = (
    "import importlib.util, json, sys\n"
    "from pathlib import Path\n"
    "spec = importlib.util.spec_from_file_location(\n"
    "    '_board_base_ledger_regions', Path(sys.argv[1]) / 'generate_ledger_regions.py')\n"
    "gen = importlib.util.module_from_spec(spec)\n"
    "sys.modules[spec.name] = gen\n"
    "spec.loader.exec_module(gen)\n"
    "data = json.loads(sys.stdin.read())\n"
    "text, where = data['ledger'], {}\n"
    "if hasattr(gen, 'record_fragments'):\n"
    "    rf = gen.record_fragments()\n"
    "    where = {'ledger_file': getattr(rf, 'LEDGER_FILE', None), 'ledger_dir': getattr(rf, 'LEDGER_DIR', None)}\n"
    "    if data['rows'] is not None:\n"
    "        text = rf.ledger_view_from_texts(text, [tuple(r) for r in data['rows']]).text\n"
    "print(json.dumps({'live': len(gen.live_member_ids(text)), **where}))\n"
)
#: How many unanswered requests the asks line names before "and N more".
ASKS_SHOWN = 6
#: The one fetch of every open pull request's head that is not here yet, by
#: object id (``fetch_heads``).
OVERLAP_FETCH_TIMEOUT = 60.0
#: How many overlap pairs the section prints before "and N more".
OVERLAPS_SHOWN = 12
#: The most files ``gh pr list --json files`` lists for one pull request: a
#: head not here is read from that list, so one at the cap may meet more.
GH_FILES_CAP = 100
#: A seat with no live session here, no live claim or job naming it, and no
#: mail for this many days folds into a count: a worktree seat's name outlives
#: its worktree, so one row per name ever used would grow without end
#: (``--json`` keeps every row). Nothing folds while a local reading is unread.
SEAT_QUIET_DAYS = 7
#: What two live sessions in one checkout share (root CLAUDE.md Core Rule 15
#: on the self-host tree: one seat is one session in its own checkout). The
#: registry lists headless, editor and background sessions as well as
#: windows, so the row names each by pid before anyone closes one.
_SHARED = ("TWO SESSIONS IN ONE CHECKOUT share its plan, index and mail cursor (one seat per checkout); the "
           "registry lists headless and editor sessions too, so tell which pid is which before closing one")
#: What GitHub's ``mergeStateStatus`` means for the seat reading it. UNSTABLE
#: is also what a check that is not required reads while it still runs:
#: measured 2026-10-15 on a pull request with every other check green, five
#: reads over twenty seconds while one optional check re-ran, then CLEAN.
MERGE_STATES: dict[str, str] = {
    "CLEAN": "ready",
    "HAS_HOOKS": "ready",
    "UNSTABLE": "ready; an optional check is red or still running",
    "BEHIND": "behind the base (holds only under the up-to-date rule)",
    "BLOCKED": "blocked: a required check or a review holds it",
    "DIRTY": "CONFLICTS with the base: its seat runs `python tools/cc/ship.py catch-up`",
    "DRAFT": "draft",
}


def _gh_json(root: Path, *args: str, run_: Runner) -> object:
    """A ``gh`` read parsed as JSON whatever the exit code; a named
    ``Unresolvable`` when it cannot run or answers no JSON."""
    rc, out, err = run_(["gh", *args], cwd=str(root), timeout=GH_TIMEOUT)
    try:
        return json.loads(out or "")  # json-dict-safe: ok every caller isinstance-checks the answer before a deref
    except ValueError:
        raise Unresolvable(f"gh {' '.join(args[:2])} answered rc={rc} with no JSON: "
                           f"{(err or out).strip()[:120] or 'nothing'}") from None


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


# ----------------------------------------------------------------- the reads --

def read_open_prs(root: Path, *, run_: Runner = run) -> list[dict]:
    answer = _gh_json(root, "pr", "list", "--state", "open", "--limit", str(OPEN_PR_LIMIT), "--json",
                      "number,headRefName,headRefOid,mergeStateStatus,isDraft,autoMergeRequest,title,files",
                      run_=run_)
    if not isinstance(answer, list):
        raise Unresolvable("gh pr list answered something other than a list")
    return [pr for pr in answer if isinstance(pr, dict) and isinstance(pr.get("number"), int)]


def read_post_merge(root: Path, base: str, *, run_: Runner = run) -> dict:
    """The newest post-merge run on ``base`` that reached a verdict:
    ``{"verdict": "green"|"red"|"none"|"absent", "sha", "url", "running",
    "between", "green_sha", "suspects", "suspects_unread"}``. ``running`` says
    a run newer than the verdict is going. On red, ``green_sha`` is the last
    green run before it and ``suspects`` the pull requests merged in between,
    several when a run between the two is red or still going (None when no
    green run is in the window); ``between`` holds the head of each run still
    going there, whose verdict can narrow the suspects (runs overlap since no
    newer push cancels an older one). A failed
    suspects read keeps the red and says so; it never turns red into unread."""
    out: dict = {"verdict": "none", "sha": "", "url": "", "running": False, "between": [], "green_sha": "",
                 "suspects": None, "suspects_unread": ""}
    try:
        runs = _gh_json(root, "run", "list", "--workflow", POST_MERGE_WORKFLOW, "--branch", base, "--event", "push",
                        "--limit", str(RUN_WINDOW), "--json", "databaseId,status,conclusion,headSha,url", run_=run_)
    except Unresolvable as exc:
        text = str(exc)
        if POST_MERGE_WORKFLOW in text and ("not found" in text.lower() or "could not find" in text.lower()):
            out["verdict"] = "absent"   # a repository with no post-merge proof: a state, not a failed read
            return out
        raise
    if not isinstance(runs, list):
        raise Unresolvable("gh run list answered something other than a list")
    for run_row in runs:   # newest first
        if not isinstance(run_row, dict):
            continue
        if str(run_row.get("status") or "").lower() != "completed":
            if out["verdict"] == "none":
                out["running"] = True
            elif out["verdict"] == "red":
                out["between"].append(str(run_row.get("headSha") or ""))
            continue
        conclusion = str(run_row.get("conclusion") or "").upper()
        sha = str(run_row.get("headSha") or "")
        if conclusion == "SUCCESS":
            if out["verdict"] == "none":
                out.update(verdict="green", sha=sha, url=str(run_row.get("url") or ""))
            else:
                out["green_sha"] = sha
            break
        if conclusion in _RED and out["verdict"] == "none":
            out.update(verdict="red", sha=sha, url=str(run_row.get("url") or ""))
    if out["verdict"] == "red":
        try:
            out["suspects"] = read_suspects(root, out["green_sha"], out["sha"], run_=run_)
        except Unresolvable as exc:
            out["suspects_unread"] = str(exc)
    return out


def read_suspects(root: Path, green_sha: str, red_sha: str, *, run_: Runner = run) -> list[dict] | None:
    """The pull requests merged after ``green_sha`` up to ``red_sha``, oldest
    first: ``[{"pr", "sha", "parents"}]``, read from GitHub's compare of the two
    and the merges' own first lines. None when there is no green run to compare
    from (every merge before the red one is then a suspect)."""
    if not green_sha or not red_sha:
        return None
    answer = _gh_json(root, "api", f"repos/{{owner}}/{{repo}}/compare/{green_sha}...{red_sha}", run_=run_)
    commits = answer.get("commits") if isinstance(answer, dict) else None
    if not isinstance(commits, list):
        raise Unresolvable("gh api compare answered no commit list")
    suspects: list[dict] = []
    for commit in commits:
        if not isinstance(commit, dict):
            continue
        message = str((commit.get("commit") or {}).get("message") or "")
        match = _PR_MERGE_RE.search(message.splitlines()[0] if message else "")
        if match:
            suspects.append({"pr": int(match.group(1) or match.group(2)), "sha": str(commit.get("sha") or ""),
                             "parents": len(commit.get("parents") or [])})
    return suspects


def read_ledger_live(root: Path) -> int | None:
    """The ledger's live member rows, through the generator's own parser
    (loaded by path under a private alias, as record_merge loads it), over
    the ledger's view (the file with any row files beside it placed in it,
    the generator's ``record_fragments`` loader); None where the tree keeps
    no ledger. The file stays after a repository's rows move to files (it
    holds the prose and the headers), so its absence still means no ledger."""
    ledger = root / LEDGER
    if not ledger.is_file():
        return None
    path = Path(__file__).resolve().parent / "generate_ledger_regions.py"
    spec = importlib.util.spec_from_file_location("_board_ledger_regions", path)
    if spec is None or spec.loader is None:
        raise Unresolvable("the ledger generator could not be loaded")
    gen = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gen
    spec.loader.exec_module(gen)
    text = ledger.read_bytes().decode("utf-8", errors="replace")
    return len(gen.live_member_ids(gen.record_fragments().ledger_view_at(ledger, ledger_text=text).text))


def _git_env() -> dict[str, str]:
    """The environment of the board's git calls: no repository-selecting
    override and no terminal prompt (``mail.git_env``, as the mail fetch runs),
    and no Git Credential Manager sign-in window, which on Windows would hold a
    read-only board read for the whole timeout (as ``checkout_sync`` fetches)."""
    return mail.git_env({"GCM_INTERACTIVE": "never"})


def _is_row(name: str) -> bool:
    return name.startswith(LEDGER_ROWS) and "/" not in name[len(LEDGER_ROWS):]


def _read_base_archive(archive: Path, modules: Path) -> tuple[str, list[tuple[str, str | None]] | None, set[str]]:
    """From the base's archive: the ledger's text (CRLF to LF, as the loader
    reads it); ``(name, text)`` for each file directly under its row directory
    (None where the archive holds none), decoded as the fragment loader reads a
    row file (strict UTF-8, None when it is not; CRLF to LF); and every regular
    file name the archive holds, which the caller checks against the tree.
    Only the base's top-level ``tools/cc`` modules are written, under
    ``modules``: on Windows a file's first read after it is written is the cost
    (570 extracted files read in 2.1 s, then in 0.14 s), so the row texts
    travel in memory, and no member is read before its name says it is wanted.
    Regular files only, a name that climbs out skipped: the archive is this
    repository's own."""
    ledger_text, rows, names = "", None, set()
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            name = member.name.replace("\\", "/")
            if not member.isfile() or name.startswith("/") or ".." in name.split("/"):
                continue
            names.add(name)
            module = name.startswith(CC) and name.endswith(".py") and "/" not in name[len(CC):]
            if not (name == LEDGER or _is_row(name) or module):
                continue
            source = tar.extractfile(member)
            data = source.read() if source is not None else b""
            if name == LEDGER:
                ledger_text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
            elif _is_row(name):
                try:
                    text: str | None = data.decode("utf-8").replace("\r\n", "\n")
                except UnicodeDecodeError:
                    text = None
                rows = [*(rows or []), (name[len(LEDGER_ROWS):], text)]
            else:
                modules.mkdir(parents=True, exist_ok=True)
                (modules / name[len(CC):]).write_bytes(data)
    return ledger_text, rows, names


def read_ledger_at_base(root: Path, base: str, *, run_: Runner = run) -> dict | None:
    """The ledger's live member rows at ``origin/<base>``, as
    ``{"ref", "sha", "live"}`` (``live`` None where the base keeps no ledger),
    or None when this clone has no ``origin/<base>``; a ``why_not`` reason
    instead of ``live`` where the base's archive leaves out a file the count
    reads (an ``export-ignore`` attribute). On None or ``why_not`` the caller
    counts the working tree and says why. One ``git archive`` of the base's
    ``tools/cc`` and ledger lands in a temporary directory outside the tree,
    and a child interpreter counts the base's ledger with the base's own
    generator and fragment loader."""
    ref, env = f"origin/{base}", _git_env()
    rc, out, _err = run_(["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/{ref}^{{commit}}"],
                         cwd=str(root), timeout=GH_TIMEOUT, env=env)
    sha = out.strip() if rc == 0 else ""
    if not sha:
        return None
    rc, out, err = run_(["git", "ls-tree", "-r", "-z", "--name-only", sha, "--", *BASE_COUNT_PATHS],
                        cwd=str(root), timeout=GH_TIMEOUT, env=env)
    if rc != 0:
        raise Unresolvable(f"git ls-tree on {ref} failed: {err.strip()[:200]}")
    listed = {name for name in out.split("\0") if name}
    at: dict = {"ref": ref, "sha": sha, "live": None}
    if LEDGER not in listed:
        return at
    generator = CC + "generate_ledger_regions.py"
    if generator not in listed:
        raise Unresolvable(f"{ref} keeps a ledger but no {generator} to count it with")
    present = [p for p in BASE_COUNT_PATHS if p in listed or any(n.startswith(p + "/") for n in listed)]
    try:
        # ignore_cleanup_errors: a Windows rmtree stops on a file it cannot
        # remove, and a leftover temporary directory must not cost the line.
        with tempfile.TemporaryDirectory(prefix="board-base-", ignore_cleanup_errors=True) as scratch:
            archive = Path(scratch) / "base.tar"
            rc, _out, err = run_(["git", "archive", "--format=tar", "-o", str(archive), sha, "--", *present],
                                 cwd=str(root), timeout=GH_TIMEOUT, env=env)
            if rc != 0:
                raise Unresolvable(f"git archive of {ref} failed: {err.strip()[:200]}")
            modules = Path(scratch) / "cc"
            ledger_text, rows, archived = _read_base_archive(archive, modules)
            left_out = sorted(n for n in listed - archived if n in (LEDGER, generator) or _is_row(n))
            if left_out:
                at["why_not"] = (f"git archive of {ref} leaves out {len(left_out)} file(s) the count reads, "
                                 f"{left_out[0]} first: an export-ignore attribute at the base")
                return at
            rc, out, err = run_([sys.executable, "-I", "-c", _BASE_COUNT, str(modules)], cwd=scratch,
                                input=json.dumps({"ledger": ledger_text, "rows": rows}), timeout=BASE_COUNT_TIMEOUT)
    except (tarfile.TarError, EOFError, ValueError, TypeError) as exc:
        raise Unresolvable(f"the archive of {ref} could not be read: {type(exc).__name__}: {exc}") from exc
    try:
        answer = json.loads(out) if rc == 0 else None
    except ValueError:
        answer = None
    if not isinstance(answer, dict) or not isinstance(answer.get("live"), int):
        raise Unresolvable(f"the base's generator did not count its ledger: {(err or out).strip()[-200:]}")
    for key, mine in (("ledger_file", LEDGER), ("ledger_dir", LEDGER_DIR)):
        theirs = answer.get(key)
        if theirs is not None and theirs != mine:
            raise Unresolvable(f"{ref}'s ledger tools read {theirs} where this checkout reads {mine}: "
                               "catch this checkout up to count it")
    at["live"] = answer["live"]
    return at


def read_stale(root: Path, base: str, pr: dict, *, run_: Runner = run) -> str:
    """The stale-base advisory for one armed pull request, or "": GitHub's
    files list is its paths, and its imports are read at its head when that
    commit is here, else at the base (another seat's head is seldom fetched;
    a file the base lacks is then judged by its path alone)."""
    head = str(pr.get("headRefOid") or "")
    paths = [str(f.get("path")) for f in pr.get("files") or [] if isinstance(f, dict) and f.get("path")]
    runs = _gh_json(root, "run", "list", "--branch", str(pr.get("headRefName") or ""), "--event", "pull_request",
                    "--limit", "100", "--json", "workflowName,createdAt,headSha,conclusion", run_=run_)
    rc, _, _ = run_(["git", "cat-file", "-e", f"{head}^{{commit}}"], cwd=str(root), timeout=GH_TIMEOUT)
    result = _merge_rules.stale_base(root, base_ref=f"origin/{base}", tested_when=_merge_rules.tested_at(runs, head),
                                     pr_paths=paths, pr_rev=head if rc == 0 and head else f"origin/{base}", run_=run_)
    return _merge_rules.stale_line(result, base, pr.get("number"))


def read_stale_section(root: Path, base: str, prs: list[dict], strict: bool | None, *, fetch: bool,
                       run_: Runner = run) -> None:
    """``pr["stale"]`` on each pull request whose armed auto-merge would land
    it on its own green CI: under the up-to-date rule GitHub holds a stale one
    itself, and one not armed lands only when a seat merges it. With ``fetch``
    the base is fetched first, so "now" is GitHub's base and not this clone's
    last fetch; ``collect`` fetches it once per read for every section and
    passes False. One read that fails costs only its own line."""
    armed = [pr for pr in prs if pr.get("autoMergeRequest") and not pr.get("isDraft")]
    if strict or not armed:
        return
    if fetch:
        fetch_base(root, base, run_=run_)   # a failed fetch reads the base as last fetched
    for pr in armed:
        try:
            pr["stale"] = read_stale(root, base, pr, run_=run_)
        except Unresolvable as exc:
            pr["stale"] = f"stale-base check not read for #{pr.get('number')}: {exc}"


def fetch_base(root: Path, base: str, *, run_: Runner = run) -> tuple[bool, str]:
    """``origin/<base>`` brought up to GitHub's, once per read, for the stale
    check and the ledger count alike (with no pull request armed nothing else
    would refresh it): ``(True, "")``, or ``(False, why)`` when the fetch
    failed and the base stays as last fetched, which the ledger line says."""
    try:
        rc, out, err = run_(["git", "fetch", "origin", base, "--quiet"], cwd=str(root), timeout=GH_TIMEOUT,
                            env=_git_env())
    except Unresolvable as exc:
        return False, str(exc)
    if rc != 0:
        lines = (err.strip() or out.strip()).splitlines()
        return False, (lines[-1] if lines else f"git fetch exited {rc}")[:160]
    return True, ""


# ------------------------------------------------------------- the overlaps --

def _have(root: Path, oid: str, *, run_: Runner) -> bool:
    try:
        rc, _, _ = run_(["git", "cat-file", "-e", f"{oid}^{{commit}}"], cwd=str(root), timeout=GH_TIMEOUT)
    except Unresolvable:
        return False
    return rc == 0


def _whole(path: str) -> dict:
    """A file claimed without the symbols that say where in it: every line of
    it could be the lane's, so it certifies nothing."""
    if path.endswith(".py"):
        return {"kind": "python", "symbols": set(), "changed": 1, "unplaced": 1}
    return {"kind": "path", "symbols": {path}, "changed": 0, "unplaced": 0}


def _claim_place(claims: list[dict]) -> dict[str, dict]:
    """One seat's lane, from its live claims, as ``{folded path:
    placement}``, each claim read by ``mail.claim_view``, the claims
    matcher's own rule. A Python file is whole (unplaced) unless the lane
    names symbols in it, no claim of it holds the file whole (a path given by
    hand, or a directory over it, with no symbol of that claim under it),
    none marks it unplaced and no count of left-out symbols stands; the
    symbols it names still meet. Every list another seat wrote is read
    shape-checked."""
    paths: set[str] = set()
    symbols: set[str] = set()
    whole: set[str] = set()
    unplaced: set[str] = set()
    more = 0
    for claim in claims:
        re_ = claim.get("re") or {}
        syms, left, held, marked = mail.claim_view(re_)
        paths |= {_symbols.canonical(p) for p in mail._str_list(re_.get("paths"))}
        symbols |= syms
        whole |= held
        unplaced |= marked
        more += left
    module = f"::{_symbols.MODULE}"
    place: dict[str, dict] = {}
    for path in sorted(paths | {s.split("::", 1)[0] for s in symbols}):
        if not path.endswith(".py"):
            place[path] = _whole(path)
            continue
        named = {s for s in symbols if s.split("::", 1)[0] == path and not s.endswith(module)}
        partial = (not named or bool(more) or path in unplaced
                   or any(mail._touches(w, path) for w in whole))
        place[path] = {"kind": "python", "symbols": named, "changed": max(1, len(named)),
                       "unplaced": 1 if partial else 0}
    return place


def _covered(place: dict[str, dict], path: str) -> dict | None:
    """``path``'s placement on one side: its own, or whole under a directory
    the side claims (a claim past the path cap names folders), else None."""
    if path in place:
        return place[path]
    if any(path.startswith(d.rstrip("/") + "/") for d in place):
        return _whole(path)
    return None


def _pr_place(root: Path, base: str, pr: dict, present: set[str], *, run_: Runner) -> tuple[dict, str]:
    """A pull request's lane from its head, ``(placement, "")``; where the
    head is not here or cannot be read, GitHub's file list as paths and the
    reason, so the pair says the symbols were not read."""
    head = str(pr.get("headRefOid") or "")
    listed = {_symbols.canonical(str(f.get("path"))): {"kind": "unread", "symbols": set(), "changed": 0,
                                                       "unplaced": 0}
              for f in pr.get("files") or [] if isinstance(f, dict) and f.get("path")}
    if not head or head not in present:
        return listed, "head not here"
    try:
        rc, out, err = run_(["git", "merge-base", f"origin/{base}", head], cwd=str(root), timeout=GH_TIMEOUT,
                            env=_git_env())
        if rc != 0 or not out.strip():
            return listed, f"no merge base with origin/{base} ({(err.strip() or out.strip())[:120] or rc})"
        return _symbols.symbols_between(out.strip(), head, root=root, run=run_, env=_git_env()), ""
    except Unresolvable as exc:
        return listed, str(exc)


def fetch_heads(root: Path, prs: list[dict], *, run_: Runner = run) -> list[str]:
    """The open pull requests' heads that are not here, fetched in one
    bounded call by object id: it lands objects and moves no ref (it rewrites
    ``FETCH_HEAD``, as the base and mail fetches do). Returns what failed, as
    notes; ``--no-fetch`` never calls it."""
    heads = list(dict.fromkeys(str(pr.get("headRefOid") or "") for pr in prs if pr.get("headRefOid")))
    missing = [h for h in heads if not _have(root, h, run_=run_)]
    if not missing:
        return []
    what = f"fetching {len(missing)} head{'s' if len(missing) != 1 else ''} failed"
    try:
        rc, out, err = run_(["git", "fetch", "origin", *missing], cwd=str(root), timeout=OVERLAP_FETCH_TIMEOUT,
                            env=_git_env())
    except Unresolvable as exc:
        return [f"{what}: {exc}"]
    if rc != 0:
        lines = (err.strip() or out.strip()).splitlines()
        return [f"{what}: {(lines[-1] if lines else f'git fetch exited {rc}')[:160]}"]
    return []


#: The pair verdicts in the order the section prints them: what a seat must
#: answer first. Every verdict ``_symbols.pair_verdict`` gives has a place.
_VERDICT_ORDER = ("shared symbol", "not read", "unplaced", "path only", "different functions", "none")


def read_overlaps_section(root: Path, base: str, claims: list[dict], prs: list[dict], *,
                          run_: Runner = run, fetch: bool = True, seat: str = "",
                          known: dict[str, tuple[dict, str]] | None = None) -> dict:
    """``{"pairs", "notes", "partial", "unread_lanes"}``: every pair of lanes
    from different seats that change a file in common, among the live claims
    (united per seat and lane) and the open pull requests (read from their
    heads, which replace their own seat's claims on their lane), each with the
    verdict ``_symbols.pair_verdict`` gives it, ``seat``'s own pairs first and
    the rest by what must be answered first. With ``fetch`` the heads not here
    are fetched first (``fetch_heads``); a head still not here, or one that
    cannot be read, is a path-level side whose symbols were not read, and a
    side that names no file at all is a note, never silence. ``partial``
    says something was not read, so "none" is only none among what was."""
    notes: list[str] = fetch_heads(root, prs, run_=run_) if fetch else []
    heads = {str(pr.get("headRefOid") or "") for pr in prs if pr.get("headRefOid")}
    present = {h for h in heads if _have(root, h, run_=run_)}
    owner = {str(pr.get("headRefName") or ""): pr.get("seat") for pr in prs}
    lanes: dict[tuple[str, str], list[dict]] = {}
    for claim in claims:
        lane = str((claim.get("re") or {}).get("lane") or "")
        if lane in owner and (not owner[lane] or owner[lane] == claim.get("from")):
            continue   # the pull request's head replaces its own seat's claims on its lane
        lanes.setdefault((str(claim.get("from") or ""), lane), []).append(claim)
    sides: list[dict] = []
    for (who, lane), on_lane in lanes.items():
        ids = list(dict.fromkeys(i for c in on_lane for i in mail._str_list((c.get("re") or {}).get("ids"))))
        label = f"{who} ({', '.join([lane or '(no lane)', *ids])})"
        sides.append({"seat": who, "who": who, "lane": lane, "label": label, "place": _claim_place(on_lane),
                      "not_read": "",
                      "stale": [str(c.get("id") or "") for c in on_lane if mail.other_rule(c.get("re") or {})]})
    unread_lanes: list[str] = []
    for pr in prs:
        head = str(pr.get("headRefOid") or "")
        place, why = (known or {}).get(head) or _pr_place(root, base, pr, present, run_=run_)
        number, branch, owned = pr.get("number"), str(pr.get("headRefName") or ""), pr.get("seat")
        label = (f"#{number} {owned} ({branch})" if owned else
                 f"#{number} ({branch}; seat unread)" if owned is None else
                 f"#{number} ({branch}; no seat's claim names it)")
        sides.append({"seat": owned or "", "who": f"#{number}", "lane": branch, "label": label, "place": place,
                      "not_read": f"#{number}: {why}" if why else ""})
        if why:
            unread_lanes.append(branch)
            if not place:
                notes.append(f"#{number}: symbols not read ({why}) and no file listed, so its overlaps are unknown")
            elif len(pr.get("files") or []) >= GH_FILES_CAP:
                notes.append(f"#{number}: GitHub lists at most {GH_FILES_CAP} files, so more of it may meet")
    pairs = []
    for i, a in enumerate(sides):
        for b in sides[i + 1:]:
            if a["seat"] and a["seat"] == b["seat"]:
                continue   # a seat never meets itself
            one, two = {}, {}
            for path in sorted(set(a["place"]) | set(b["place"])):
                pa, pb = _covered(a["place"], path), _covered(b["place"], path)
                if pa is not None and pb is not None:
                    one[path], two[path] = pa, pb
            if not one:
                continue
            pair = {"a": a["label"], "b": b["label"], "seats": [a["seat"], b["seat"]], "lanes": [a["lane"], b["lane"]],
                    "files": sorted(one), "paths": [], "shared": [], "unplaced_on": [],
                    "not_read": "; ".join(s["not_read"] for s in (a, b) if s["not_read"])}
            if pair["not_read"]:
                pairs.append({**pair, "verdict": "not read"})
                continue
            verdict = _symbols.pair_verdict(one, two)
            key = {"shared symbol": "shared", "unplaced": "unplaced", "different functions": "certified",
                   "path only": "paths"}.get(verdict["verdict"], "files")
            pair.update(verdict=verdict["verdict"], files=verdict[key], shared=verdict["shared"],
                        paths=[] if key == "paths" else verdict["paths"])
            if verdict["verdict"] == "unplaced":
                declining = [s for s, place in ((a, one), (b, two))
                             if any(place[f]["unplaced"] or place[f].get("beside")
                                    or not place[f]["changed"] for f in verdict["unplaced"])]
                pair["unplaced_on"] = [s["who"] for s in declining]
                pair["unplaced_labels"] = [s["label"] for s in declining]
            pairs.append(pair)
    rank = {v: n for n, v in enumerate(_VERDICT_ORDER)}
    pairs.sort(key=lambda p: (0 if seat and seat in p["seats"] else 1, rank.get(p["verdict"], len(rank))))
    # A claim placed under another symbol rule is read, whole: no part of the read is missing,
    # so it leaves "partial" alone; its note is keyed by its side, said only beside a pair of it.
    return {"pairs": pairs, "notes": notes, "partial": bool(notes or unread_lanes), "unread_lanes": unread_lanes,
            "stale_rule": {s["label"]: s["stale"] for s in sides if s.get("stale")}}


def _symbol_words(symbol: str) -> str:
    """A symbol as the line names it: the mapper's own words for its marks."""
    return _symbols.mark_words(symbol)


def _path_words(paths: list[str]) -> str:
    """Paths read with no symbols: a file that is not Python, or a folder a
    claim holds whole. Which one is not guessed from the spelling (a
    ``Makefile`` has no dot, a folder may have one)."""
    return f"{', '.join(paths)} (no symbols: not Python, or a folder claimed whole)"


def _overlap_text(pair: dict) -> str:
    who = f"{pair.get('a')} and {pair.get('b')}"
    files = ", ".join(pair.get("files") or [])
    verdict = pair.get("verdict")
    also = f"; also both changed {_path_words(pair['paths'])}" if pair.get("paths") else ""
    if verdict == "shared symbol":
        return f"{who} meet at {', '.join(_symbol_words(s) for s in pair.get('shared') or [])}{also}"
    if verdict == "different functions":
        return f"{who} both changed {files}: different functions, none shared or next to the other's{also}"
    if verdict == "unplaced":
        on = pair.get("unplaced_on") or []
        sides = " and ".join(f"{w}'s" for w in on) + (" sides" if len(on) > 1 else " side")
        return f"{who} both changed {files}: unplaced lines" + (f" on {sides}" if on else "") + also
    if verdict == "not read":
        return f"{who} both changed {files} (symbols not read for {pair.get('not_read')})"
    if verdict == "path only":
        return f"{who} both changed {_path_words(pair.get('files') or [])}"
    return f"{who} both changed {files}: {verdict}{also}"


def overlap_lines(section: object) -> list[str]:
    """The ``overlaps:`` lines, 7-bit ASCII: one per pair, then the notes;
    ``none`` when no two lanes of different seats change a file in common,
    and ``none among what was read`` when something was not read."""
    if not isinstance(section, dict) or "unread" in section:
        why = section.get("unread") if isinstance(section, dict) else "not read"
        return [_ascii(f"overlaps: unread ({why})")]
    pairs = section.get("pairs") or []
    texts = [_overlap_text(p) for p in pairs[:OVERLAPS_SHOWN]] or [
        "none among what was read" if section.get("partial") else "none"]
    if len(pairs) > OVERLAPS_SHOWN:
        texts.append(f"and {len(pairs) - OVERLAPS_SHOWN} more (--json lists them)")
    texts += [str(n) for n in section.get("notes") or []]
    # Said only beside a shown pair it declines (only an unplaced pair names the sides it
    # declines on): a release and a new claim change no other.
    stale = section.get("stale_rule") or {}
    said = list(dict.fromkeys(label for p in pairs[:OVERLAPS_SHOWN]
                              for label in p.get("unplaced_labels") or [] if label in stale))
    texts += [f"{label}: claim {', '.join(stale[label])} was placed under another symbol rule and reads whole "
              "(its files as unplaced lines) until its seat releases it and claims again" if len(stale[label]) == 1
              else f"{label}: claims {', '.join(stale[label])} were placed under another symbol rule and read whole "
              "(their files as unplaced lines) until their seat releases them and claims again" for label in said]
    return [_ascii(("overlaps: " if i == 0 else "          ") + t) for i, t in enumerate(texts)]


def _overlaps_or_unread(root: Path, base: str, claims: list[dict], prs: list[dict], notes: list[str], *,
                        run_: Runner, fetch: bool = True, seat: str = "",
                        known: dict[str, tuple[dict, str]] | None = None) -> dict:
    """The section read on its own: a failure is its own line, never the board's."""
    try:
        section = read_overlaps_section(root, base, claims, prs, run_=run_, fetch=fetch, seat=seat, known=known)
    except Unresolvable as exc:
        return {"unread": str(exc)}
    except Exception as exc:  # noqa: BLE001 -- each section is read on its own; the overlaps line says unread and why
        return {"unread": f"{type(exc).__name__}: {os_error_text(exc)}"}
    section["notes"] = [*section.get("notes", []), *notes]
    section["partial"] = bool(section.get("partial") or notes)
    return section


def lane_overlap_lines(root: Path, base: str, lane: str, number: object, head: str, *,
                       run_: Runner = run) -> list[str]:
    """The ship notice: ``lane`` (just pushed, ``head``) against every live
    claim of another seat and every open pull request, in the board's words.
    The lane's side is read from ``head`` here, never from a listing that can
    lag behind the create; only the pairs it is in are printed, and when there
    are any, the rule they leave: the second to merge runs catch-up."""
    machine, how = mail.machine_setting(root, run=run_)
    # The pushed lane first: it is here, and a head that cannot be read is the
    # answer, before any network read.
    mine = {"number": number, "headRefName": lane, "headRefOid": head, "seat": machine or "", "files": []}
    own, why = _pr_place(root, base, mine, {head} if _have(root, head, run_=run_) else set(), run_=run_)
    if why:
        return overlap_lines({"unread": f"the pushed head {head[:7]} could not be read: {why}"})
    notes: list[str] = []
    if how.startswith(mail.MACHINE_UNREAD):
        notes.append(f"this checkout's seat name could not be read ({how}), so its own other lanes read as "
                     "another seat's")
    claims: list[dict] = []
    seat_of_lane: dict = {}
    try:
        if machine:
            ok, problem = mail.fetch_mail(root, run=run_)
            if not ok:
                notes.append(f"the mail fetch failed ({problem}), so the claims are as last fetched")
        by_machine, _skipped = mail.read_mail(root, run=run_)
        claims, seat_of_lane = mail.live_claims(by_machine), mail.lane_seats(by_machine)
    except Unresolvable as exc:
        notes.append(f"the claims are unread ({exc})")
    try:
        prs = [pr for pr in read_open_prs(root, run_=run_) if pr.get("headRefName") != lane]
    except Unresolvable as exc:
        prs = []
        notes.append(f"the open pull requests are unread ({exc})")
    # Only a pull request whose files meet the lane's needs its head read: the
    # notice prints the lane's pairs alone.
    # A list at GitHub's cap may hold back the very file that meets, so it is read.
    prs = [pr for pr in prs
           if len(pr.get("files") or []) >= GH_FILES_CAP
           or any(mail._touches(_symbols.canonical(str(f.get("path"))), p)
                  for f in pr.get("files") or [] if isinstance(f, dict) and f.get("path") for p in own)]
    for pr in prs:
        pr["seat"] = seat_of_lane.get(str(pr.get("headRefName") or ""), "")
    section = _overlaps_or_unread(root, base, claims, [mine, *prs], notes, run_=run_, seat=machine or "",
                                  known={head: (own, "")})
    if "unread" in section:
        return overlap_lines(section)
    pairs = [p for p in section.get("pairs") or [] if lane in (p.get("lanes") or [])]
    lines = overlap_lines({"pairs": pairs, "notes": section.get("notes") or [],
                           "partial": section.get("partial"), "stale_rule": section.get("stale_rule") or {}})
    if pairs:
        lines.append("          the rule stands: the second of these to merge runs the ship driver's catch-up")
    return lines


def read_sessions(root: Path, *, run_: Runner = run, config_dir: Path | None = None,
                  inside_session: bool | None = None) -> dict:
    """This clone's checkouts with the live Claude Code sessions in each:
    ``{"checkouts": [{"path", "main", "seat", "gone", "name_unread", "naming",
    "sessions"}], "unread": "", "checked", "registry", "clone"}``
    (``naming``: what naming a present linked worktree takes, read there by
    ``mail.naming_steps``, the one owner, in its form for a reader in another
    checkout; '' for the main checkout and a folder that is gone), or no
    checkouts and ``unread`` naming why. The sessions are Claude Code's own
    registry (``checkout_sync.live_sessions``: an entry whose process is
    alive), each counted for the DEEPEST checkout that holds its cwd, since a
    worktree sits inside the main checkout's folder. A checkout's seat is the
    name it answers (``mail.machine_setting`` run in it, the name its mail
    ref is written under: a worktree named by hand, or one still answering
    its clone's name, reads as what it is); '' where it answers none (a name
    the channel refuses turns it off there), with ``name_unread`` saying why
    where git could not be asked at all; and ``<clone>-<directory>``
    (SessionStart's naming) only for a listed worktree whose folder is gone,
    which keeps its sessions (``gone``). Unread, never empty, where the
    registry cannot be read in full, where the clone's own name cannot be
    read (a worktree answering it could not be told from one named by hand),
    or
    where this runs inside a session the registry does not list (then it is
    not the registry that session writes to: ``checkout_sync.main``'s own
    check). ``checked`` is False outside a session, where that check cannot
    run and ``registry`` says which directory was read. ``inside_session``
    None reads ``CLAUDECODE``; ``config_dir`` is for tests."""
    try:
        import checkout_sync   # lazily: a fixture that copies the board without it costs this read only
    except ImportError as exc:
        return {"checkouts": [], "unread": f"checkout_sync.py could not be loaded beside the board ({exc})"}
    rc, listing, err = run_(["git", "worktree", "list", "--porcelain"], cwd=str(root), timeout=GH_TIMEOUT,
                            env=_git_env())
    if rc != 0:
        return {"checkouts": [], "unread": f"git could not list this clone's checkouts: {err.strip()[:160]}"}
    sessions = checkout_sync.live_sessions(config_dir)
    if sessions is None:
        return {"checkouts": [], "unread": "Claude Code's session registry could not be read in full"}
    if inside_session is None:
        inside_session = bool(os.environ.get("CLAUDECODE"))
    if inside_session and checkout_sync.own_entry(sessions) is None:
        return {"checkouts": [], "unread": "Claude Code's session registry does not list this session, so it is "
                                           "not the registry this session writes to"}
    dirs = [config_dir] if config_dir is not None else checkout_sync.claude_config_dirs()
    registry = ", ".join(str(Path(d) / "sessions") for d in dirs)
    named_clone, clone_how = mail.clone_machine(root, run=run_)
    if clone_how.startswith(mail.MACHINE_UNREAD):
        return {"checkouts": [], "unread": f"this clone's own machine name could not be read ({clone_how})"}
    clone = named_clone or ""
    checkouts: list[dict] = []
    for i, block in enumerate(checkout_sync.parse_worktrees(listing)):
        path = block.get("worktree") or ""
        if not path or "bare" in block:
            continue
        # A folder removed under a running session (Assumption 6's 2026-10-08
        # cleanup) is still listed and still holds that session, so it stays;
        # with no folder to ask, its seat is the derived name. A folder that is
        # there answers its own name, or none (a name the channel refuses turns
        # the channel off there), and none is no seat name, never a derived one.
        gone = not Path(path).is_dir()
        name_unread = naming = ""
        if gone:
            seat = clone if i == 0 else ((mail.worktree_seat_name(clone, Path(path).name) or "") if clone else "")
        else:
            named, how = mail.machine_setting(Path(path), run=run_)
            seat = named or ""
            name_unread = how if named is None and how.startswith(mail.MACHINE_UNREAD) else ""
            if i:
                # Read in the worktree itself: whether its clone's shared config
                # sets core.bare or core.worktree is the one owner's call, as is
                # the config.worktree path (--git-common-dir; the listing strips
                # a trailing /.git from a bare repository's path).
                naming = mail.naming_steps(Path(path), run=run_, at=path)
        checkouts.append({"path": path, "main": i == 0, "seat": seat, "gone": gone, "name_unread": name_unread,
                          "naming": naming, "sessions": []})
    for session in sessions:
        cwd = str(session.get("cwd") or "")
        holders = [c for c in checkouts if checkout_sync.within(cwd, c["path"])]
        if holders:
            deepest = max(holders, key=lambda c: len(Path(c["path"]).parts))
            deepest["sessions"].append({"pid": session.get("pid"), "session_id": session.get("session_id") or ""})
    return {"checkouts": checkouts, "unread": "", "checked": bool(inside_session), "registry": registry,
            "clone": clone}


def unread_names(local: dict) -> list[dict]:
    """``[{"path", "why"}]`` for each checkout whose name git could not be
    asked about: while any is unread, the board folds no seat away (its real
    seat's row would read as quiet while it holds a session)."""
    return [{"path": c.get("path"), "why": c.get("name_unread")}
            for c in local.get("checkouts") or [] if c.get("name_unread")]


def seat_rows(by_machine: dict[str, list[dict]], local: dict, now: datetime | None = None) -> list[dict]:
    """One row per seat, by name: every machine with mail (its last message's
    type and age) and every checkout of this clone holding a live session.
    ``checkout`` and ``sessions`` are None on a row this clone holds no
    checkout for -- another machine, another clone, or a worktree since
    removed: the channel cannot tell which -- and on every row when the local
    read was unread. ``shared`` flags two or more live sessions in one
    checkout. ``name`` is the bare name the row answers ('' for none). A
    worktree answering a name another checkout holds -- one shown already,
    the clone's own (it was never named), or the main checkout's -- gets a
    row of its own, keyed ``<name> [<checkout>]`` with ``name_shared_with``
    (the two write one mail ref) and ``remedy`` (the checkout's ``naming``: the
    two quoted ``git -C`` commands that name it, or, where the clone's shared
    config sets core.bare or core.worktree, the one change, that key moved into
    the main worktree's config.worktree, then a fresh session), and only
    while it holds a session: it never overwrites the
    first. A main checkout answering other than its clone's name gets a
    ``note``; ``name_unread`` carries why a checkout's name could not be read."""
    rows: dict[str, dict] = {}
    for machine, messages in by_machine.items():
        last = messages[-1] if messages else None
        rows[machine] = {"seat": machine, "name": machine, "checkout": None, "path": None, "sessions": None,
                         "shared": False, "last_mail": None if last is None else {
                             "id": last.get("id"), "type": last.get("type"), "at": last.get("at"),
                             "age_s": mail.age_seconds(last, now)}}
    checkouts = local.get("checkouts") or []
    clone = str(local.get("clone") or "")
    main = next((c["path"] for c in checkouts if c.get("main")), "")
    main_seat = next((c.get("seat") or "" for c in checkouts if c.get("main")), "")
    for checkout in checkouts:
        sessions = checkout.get("sessions") or []
        path = str(checkout.get("path") or "")
        name = checkout.get("seat") or ""
        key = name or (f"(seat name unread) {path}" if checkout.get("name_unread") else f"(no seat name) {path}")
        held = key in rows and rows[key].get("path") is not None
        # A worktree still answering its CLONE's name (never named, or named
        # back) shares the clone's mail ref whatever the main checkout answers
        # now: a naming command pasted in the main checkout renames that one.
        inherited = bool(name) and not checkout.get("main") and name in (clone, main_seat)
        if not sessions and (held or inherited or key not in rows):
            continue
        try:
            where = Path(path).relative_to(main).as_posix() if main else path
        except ValueError:
            where = path   # a worktree outside the main checkout's folder: its own path
        where = "the main checkout" if checkout.get("main") else where.replace("\\", "/")
        gone = (" (its folder is gone, so its seat name is the derived one)" if name else " (its folder is gone)")
        label = where + (gone if checkout.get("gone") else "")
        if held or inherited:
            first = rows[key]["checkout"] if held else ("the main checkout" if name == main_seat else "the clone")
            key = f"{key} [{where}]"
            # The steps mail.naming_steps read in that worktree (read_sessions):
            # a second owner here once handed a core.worktree clone the pair,
            # which points the worktree at the main checkout's files.
            naming = checkout.get("naming") or ""
            remedy = f"name it: {naming}" if naming else ""
            row = rows.setdefault(key, {"seat": key, "last_mail": None, "name_shared_with": first, "remedy": remedy})
        else:
            row = rows.setdefault(key, {"seat": key, "last_mail": None})
        if checkout.get("main") and clone and name and name != clone:
            row["note"] = f"it answers {name}, not its clone's name {clone} (a --worktree name was set here)"
        row.update(name=name, checkout=label, path=path, sessions=sessions, shared=len(sessions) >= 2,
                   name_unread=checkout.get("name_unread") or "")
    return [rows[k] for k in sorted(rows)]


def collect(root: Path, *, fetch: bool = True, run_: Runner = run, now: datetime | None = None) -> dict:
    """Every section, each read on its own: a section that cannot be read is
    ``{"unread": reason}`` and the rest still come back. ``now`` is for tests."""
    now = now or datetime.now(timezone.utc)
    board: dict = {"read_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    base = _merge_rules.base_branch(root)
    board["base"] = base
    rules = _merge_rules.read(root, None, base)
    board["merging"] = _merge_rules.line(*rules)
    machine, machine_how = mail.machine_setting(root, run=run_)
    board["seat"] = machine or ""
    by_machine: dict = {}
    board["mail_note"] = ""
    try:
        if fetch and machine:
            ok, problem = mail.fetch_mail(root, run=run_)
            if not ok:
                board["mail_note"] = f"the fetch failed ({problem}), so mail is the local refs as last fetched"
        elif fetch:
            board["mail_note"] = (f"this checkout's machine name could not be read ({machine_how}), so the mail refs "
                                  "were not fetched" if machine_how.startswith(mail.MACHINE_UNREAD) else
                                  "this clone names no machine, so the mail refs were not fetched")
        by_machine, _skipped = mail.read_mail(root, run=run_)
    except Unresolvable as exc:
        board["mail_unread"] = str(exc)
    dispatcher, how = mail.dispatcher_setting(root)
    board["dispatcher"] = {"name": dispatcher or "", "how": how}
    claims = mail.live_claims(by_machine)
    board["claims"] = claims
    board["assignments"] = mail.live_assignments(by_machine, dispatcher)
    board["asks"] = mail.live_requests(by_machine, now=now)
    try:
        local = read_sessions(root, run_=run_)
    except Unresolvable as exc:
        local = {"checkouts": [], "unread": str(exc)}
    except Exception as exc:  # noqa: BLE001 -- each section is read on its own; the seats line says unread and why
        local = {"checkouts": [], "unread": f"{type(exc).__name__}: {os_error_text(exc)}"}
    board["seats"] = {"rows": seat_rows(by_machine, local, now), "unread": local.get("unread") or "",
                      "checked": local.get("checked", True), "registry": local.get("registry", ""),
                      "names_unread": unread_names(local)}
    # A seat a live claim or job names is never folded away as quiet, and its
    # row says why it stays.
    claimed = {str(c.get("from") or "") for c in claims}
    jobbed = {str((a.get("re") or {}).get(mail.ASSIGN_SEAT_KEY) or "") for a in board["assignments"]}
    for row in board["seats"]["rows"]:
        name = row.get("name") or ""
        row["busy"] = (f"it holds a live claim (only {name} can release it)" if name and name in claimed
                       else "a live job names it" if name and name in jobbed else "")
    seat_of_lane = mail.lane_seats(by_machine)
    board["base_fetch"] = {"state": "skipped", "problem": ""}
    if fetch:
        ok, problem = fetch_base(root, base, run_=run_)
        board["base_fetch"] = {"state": "ok" if ok else "failed", "problem": problem}
    overlap_claims = [] if board.get("mail_unread") else claims
    overlap_notes = ["the claims are unread (the mail could not be read)"] if board.get("mail_unread") else []
    try:
        prs = read_open_prs(root, run_=run_)
        for pr in prs:
            pr["seat"] = (seat_of_lane.get(str(pr.get("headRefName") or ""), "")
                          if not board.get("mail_unread") else None)
        # The heads first, so the stale clause and the overlaps read the same ones;
        # --no-fetch reads them as they are here.
        head_notes = fetch_heads(root, prs, run_=run_) if fetch else []
        read_stale_section(root, base, prs, _merge_rules.strict(rules[1], rules[2]), fetch=False, run_=run_)
        board["overlaps"] = _overlaps_or_unread(root, base, overlap_claims, prs, [*overlap_notes, *head_notes],
                                                run_=run_, fetch=False, seat=board["seat"])
        for pr in prs:
            pr.pop("files", None)   # read for the stale and overlap checks; the JSON carries verdicts, not the list
        board["open_prs"] = prs
    except Unresolvable as exc:
        board["open_prs"] = {"unread": str(exc)}
        board["overlaps"] = _overlaps_or_unread(root, base, overlap_claims, [],
                                                [*overlap_notes, "the open pull requests are unread"], run_=run_,
                                                fetch=False, seat=board["seat"])
    try:
        board["post_merge"] = read_post_merge(root, base, run_=run_)
    except Unresolvable as exc:
        board["post_merge"] = {"unread": str(exc)}
    try:
        at = read_ledger_at_base(root, base, run_=run_)
        if at is None or at.get("why_not"):
            board["ledger_live"] = read_ledger_live(root)
            board["ledger_at"] = {"working_tree": at["why_not"] if at else f"origin/{base} is not in this clone"}
        else:
            board["ledger_live"] = at["live"]
            board["ledger_at"] = {"ref": at["ref"], "sha": at["sha"]}
    except OSError as exc:
        board["ledger_live"] = {"unread": os_error_text(exc)}
    except (Unresolvable, AttributeError) as exc:
        board["ledger_live"] = {"unread": str(exc)}
    return board


# ---------------------------------------------------------------- the render --

def _pr_line(pr: dict) -> str:
    state = str(pr.get("mergeStateStatus") or "UNKNOWN").upper()
    meaning = MERGE_STATES.get(state, f"GitHub is still computing it ({state.lower()})")
    if pr.get("isDraft"):
        meaning = "draft"
    auto = "auto-merge armed" if pr.get("autoMergeRequest") else "auto-merge not armed"
    if pr.get("seat") is None:
        seat = " [seat unread: the mail could not be read]"
    else:
        seat = f" [{pr['seat']}]" if pr.get("seat") else " [no seat's claim names this branch]"
    return f"#{pr.get('number')} {pr.get('headRefName')}{seat}: {meaning}; {auto}"


def _red_line(pm: dict, base: str, prs: object) -> str:
    """The red base and what to do about it. A red run's suspects are the
    merges since the last green run before it, several when a run between the
    two is red or still going: the revert is printed only when exactly one
    pull request merged in between, and otherwise the suspects are named."""
    sha = str(pm.get("sha") or "")[:7]
    head = f"RED (post-merge proof on {sha}, {pm.get('url')})"
    suspects = pm.get("suspects")
    green = str(pm.get("green_sha") or "")[:7]
    if pm.get("suspects_unread"):
        text = f"{head}; the suspects could not be read ({pm['suspects_unread']}): read the run before reverting"
    elif suspects is None:
        text = (f"{head}; no green run in the last {RUN_WINDOW}, so every merge before it is a suspect: "
                "read the run before reverting")
    elif not suspects:
        text = (f"{head}; no pull request merged since the last green run on {green}: a flake or a change "
                "outside a pull request, so re-run it before reverting anything")
    elif len(suspects) == 1:
        one = suspects[0]
        msha = str(one.get("sha") or "")[:7]
        mflag = "-m 1 " if int(one.get("parents") or 0) > 1 else ""
        text = (f"RED after #{one['pr']} (post-merge proof on {sha}, {pm.get('url')}). Revert first: "
                f"git switch -c revert/{msha} origin/{base} && git revert {mflag}{msha}, then /ship; "
                "nothing lands on a red base")
    else:
        names = ", ".join(f"#{s['pr']}" for s in suspects)
        text = (f"{head}; suspects {names} (merged since the last green run on {green}): read the run to find "
                "which, then revert that one first")
    armed = [pr.get("number") for pr in prs if isinstance(pr, dict) and pr.get("autoMergeRequest")] \
        if isinstance(prs, list) else []
    if armed:
        text += ("; auto-merge is armed on " + ", ".join(f"#{n}" for n in armed)
                 + ", which lands on the red base unless disarmed (gh pr merge --disable-auto <n>)")
    between = [str(sha)[:7] for sha in pm.get("between") or [] if sha]
    if between:
        text += ("; a run between it and the last green is still going (on " + ", ".join(between)
                 + "), and its verdict can narrow the suspects")
    if pm.get("running"):
        # Runs overlap (no newer push cancels an older one), so a newer tip's
        # proof is often in flight beside a red: say so, as the green line does.
        text += "; a newer run is going, and its verdict will supersede this one"
    return text


def _age(seconds: object) -> str:
    """'under 1 min', '4 min', '6 h 20 min', '2 d 3 h'; 'an unread time'
    where the stamp did not parse."""
    if not isinstance(seconds, int) or isinstance(seconds, bool):
        return "an unread time"
    m = max(0, seconds) // 60
    if m < 1:
        return "under 1 min"
    if m < 60:
        return f"{m} min"
    if m < 24 * 60:
        return f"{m // 60} h {m % 60} min"
    return f"{m // (24 * 60)} d {m % (24 * 60) // 60} h"


def _ago(seconds: object) -> str:
    return f"{_age(seconds)} ago" if isinstance(seconds, int) and not isinstance(seconds, bool) else "at an unread time"


def _quiet(row: dict) -> bool:
    """No live session here, no live claim or job naming it (``busy``), and no
    mail for :data:`SEAT_QUIET_DAYS`; a row whose stamp did not parse is never
    folded away, and the caller folds nothing while the registry or any
    checkout's name is unread."""
    age = (row.get("last_mail") or {}).get("age_s")
    return (not row.get("sessions") and not row.get("busy") and isinstance(age, int)
            and age > SEAT_QUIET_DAYS * 86400)


def _seat_line(row: dict, mail_unread: bool) -> str:
    """One seat: its last mail (the only thing the channel says about a seat
    with no checkout here, so such a row says nothing of liveness), then, for
    a checkout of this clone, its live sessions from Claude Code's registry,
    each named by pid and session id where two share the checkout."""
    last = row.get("last_mail")
    if row.get("name_shared_with"):
        text = f"{row.get('seat')}: the seat name of {row['name_shared_with']} too (one mail ref for both)"
    elif last:
        text = f"{row.get('seat')}: last mail {_ago(last.get('age_s'))} ({last.get('type')})"
        age = last.get("age_s")
        if row.get("busy") and isinstance(age, int) and age > SEAT_QUIET_DAYS * 86400:
            text += f"; kept: {row['busy']}"
    else:
        # A row whose name git could not answer has an unknown mail ref.
        mail_state = "mail unread" if mail_unread else ("mail unknown" if row.get("name_unread") else "no mail")
        text = f"{row.get('seat')}: {mail_state}"
    sessions = row.get("sessions")
    if sessions is not None and not sessions:
        text += f"; no live session in {row.get('checkout')}"
    elif sessions:
        n = len(sessions)
        text += f"; {n} live session{'s' if n != 1 else ''} in {row.get('checkout')}"
        if row.get("shared"):
            named = ", ".join(f"pid {s.get('pid')} session {str(s.get('session_id') or '?')[:8]}" for s in sessions)
            text += f" ({named}): {_SHARED}"
    for extra in (row.get("note"), row.get("remedy")):
        if extra:
            text += f"; {extra}"
    return text


def _job(re_: dict) -> str:
    parts = [str(re_.get("lane") or "")] + [str(c) for c in re_.get("classes") or []] + [
        str(i) for i in re_.get("ids") or []]
    return ", ".join(p for p in parts if p) or "?"


def render(board: dict) -> str:
    lines = [f"board -- read live {board.get('read_at')}" + (f" by {board['seat']}" if board.get("seat") else "")]
    lines.append(f"merging:  {board.get('merging') or 'unread (no branch-protection answer)'}")
    pm = board.get("post_merge") or {}
    base = board.get("base") or "main"
    label = f"{base + ':':<10}"
    if "unread" in pm:
        lines.append(f"{label}post-merge proof unread ({pm['unread']})")
    elif pm.get("verdict") == "red":
        lines.append(label + _red_line(pm, base, board.get("open_prs")))
    elif pm.get("verdict") == "absent":
        lines.append(f"{label}no post-merge proof here ({POST_MERGE_WORKFLOW} is not in this repository), so two "
                     "merges that break together show only on the next pull request's CI")
    elif pm.get("verdict") == "green":
        lines.append(f"{label}post-merge proof green on {str(pm.get('sha') or '')[:7]}"
                     + ("; a newer run is going" if pm.get("running") else ""))
    else:
        lines.append(f"{label}no post-merge verdict yet" + ("; a run is going" if pm.get("running") else ""))
    prs = board.get("open_prs")
    if isinstance(prs, dict):
        lines.append(f"open PRs: unread ({prs.get('unread')})")
    elif not prs:
        lines.append("open PRs: none")
    else:
        for i, pr in enumerate(prs):
            lines.append(("open PRs: " if i == 0 else "          ") + _pr_line(pr))
            if pr.get("stale"):
                lines.append(f"            stale: {pr['stale']}")
    disp = board.get("dispatcher") or {}
    jobs = board.get("assignments") or []
    if disp.get("name") == mail.DISPATCHER_UNUSABLE:
        head = f"jobs:     (the dispatcher setting is unusable: {disp.get('how')}) "
    elif disp.get("name"):
        head = f"jobs:     (dispatcher {disp['name']}) "
    else:
        head = "jobs:     (no dispatcher named, so every seat's assigns count) "
    if board.get("mail_note"):
        lines.append(f"mail:     {board['mail_note']}")
    seats = board.get("seats") or {}
    rows = seats.get("rows") or []
    # No fold while any local reading is unread: the registry, or any
    # checkout's name, with or without a session in it (its real seat's row
    # would then read as quiet while it holds one); the line says which.
    names_unread = seats.get("names_unread") or [
        {"path": row.get("path"), "why": row.get("name_unread")} for row in rows if row.get("name_unread")]
    quiet = [] if seats.get("unread") or names_unread else [row for row in rows if _quiet(row)]
    seat_lines = [_seat_line(row, bool(board.get("mail_unread"))) for row in rows if not any(row is q for q in quiet)]
    if quiet:
        seat_lines.append(f"and {len(quiet)} seat{'s' if len(quiet) != 1 else ''} with no mail in "
                          f"{SEAT_QUIET_DAYS} d and no live session here (--json lists them)")
    if names_unread:
        first = names_unread[0]
        more = f", and {len(names_unread) - 1} more" if len(names_unread) > 1 else ""
        seat_lines.append(f"nothing folds: the seat name of {first.get('path')} is unread ({first.get('why')}){more}")
    if board.get("mail_unread"):
        seat_lines.append(f"other seats unread (the mail could not be read: {board['mail_unread']})")
    if seats.get("unread"):
        seat_lines.append(f"live sessions here unread: {seats['unread']}")
    elif seats.get("checked") is False:
        seat_lines.append(f"live sessions per {seats.get('registry') or 'the default registry'}: run outside a "
                          "session, so not checked against one")
    for i, text in enumerate(seat_lines or ["none: no machine has mail and no checkout here holds a live session"]):
        lines.append(("seats:    " if i == 0 else "          ") + text)
    if board.get("mail_unread"):
        lines.append(head + f"unread (the mail could not be read: {board['mail_unread']})")
    elif not jobs:
        lines.append(head + "no live assignments")
    else:
        for i, a in enumerate(jobs):
            re_ = a.get("re") or {}
            lines.append((head if i == 0 else "          ") + f"{re_.get('seat')}: {_job(re_)} (since {a.get('at')}; assign {a.get('id')})")
    asks = board.get("asks") or []
    if board.get("mail_unread"):
        lines.append(f"asks:     unread (the mail could not be read: {board['mail_unread']})")
    elif not asks:
        lines.append("asks:     none open (every request has an ack naming it)")
    else:
        # The full id, as the jobs row prints the assign's: the fold closes a
        # request on its full id only, and an ack naming a suffix is accepted
        # and closes nothing on an append-only record.
        ask_rows = [f"{m.get('id')} {m.get('from')} {(m.get('re') or {}).get('lane') or '-'}: {_age(m.get('age_s'))}"
                    for m in asks[:ASKS_SHOWN]]
        if len(asks) > ASKS_SHOWN:
            ask_rows.append(f"and {len(asks) - ASKS_SHOWN} more")
        for i, text in enumerate(ask_rows):
            lines.append((f"asks:     {len(asks)} open (requests no ack names, oldest first): " if i == 0
                          else "          ") + text)
    claims = board.get("claims") or []
    if board.get("mail_unread"):
        lines.append(f"claims:   unread ({board['mail_unread']})")
    elif not claims:
        lines.append("claims:   none live")
    else:
        for i, c in enumerate(claims):
            re_ = c.get("re") or {}
            n = len(re_.get("paths") or [])
            lines.append(("claims:   " if i == 0 else "          ")
                         + f"{c.get('from')}: {re_.get('lane') or '(no lane)'} ({n} path{'s' if n != 1 else ''}"
                         + (f", ids {', '.join(re_.get('ids'))}" if re_.get("ids") else "") + f") since {c.get('at')}")
    if "overlaps" in board:
        lines += overlap_lines(board["overlaps"])
    live = board.get("ledger_live")
    at = board.get("ledger_at") or {}
    if at.get("ref") and (live is None or isinstance(live, int)):
        count = "no ledger" if live is None else f"{live} live rows"
        line = f"ledger:   {count} at {at['ref']} ({str(at.get('sha') or '')[:7]})"
        fetched = board.get("base_fetch") or {}
        if fetched.get("state") == "skipped":
            line += ", as last fetched (--no-fetch)"
        elif fetched.get("state") == "failed":
            line += f", as last fetched (the fetch failed: {fetched.get('problem')})"
        lines.append(line)
    elif isinstance(live, int):
        where = f" in this working tree ({at['working_tree']})" if at.get("working_tree") else ""
        lines.append(f"ledger:   {live} live rows{where}")
    elif isinstance(live, dict):
        lines.append(f"ledger:   unread ({live.get('unread')})")
    return "\n".join(_ascii(line) for line in lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="board.py", description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--root", default=None, help="the checkout (default: the one around the cwd)")
    parser.add_argument("--no-fetch", action="store_true",
                        help="read the local mail refs and the base branch as last fetched")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = mail._repo_root(args.root)
    except Unresolvable as exc:
        print(f"board: {exc}", file=sys.stderr)
        return 2
    board = collect(root, fetch=not args.no_fetch)
    print(json.dumps(board, indent=1) if args.json else render(board))
    return 0


if __name__ == "__main__":
    from _json_safe import pin_utf8_streams

    pin_utf8_streams()
    sys.exit(main())
