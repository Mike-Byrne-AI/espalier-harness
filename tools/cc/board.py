#!/usr/bin/env python3
"""The board: one live read of what a seat needs before it states state.

Parallel seats (one session in its own named worktree, on any machine) state
what is open, merging, blocked or red. Three seats once each believed a
different branch was merging, because each read a
snapshot: its banner, a handoff note, the mail, its own context. This prints,
read now: the merge rules, the post-merge verdict on the base branch (and on a
red one, the pull request that turned it red and the revert), every open pull
request with its seat and what GitHub says holds it, the dispatcher's live
assignments, the live claims, and the ledger's live row count.

Read-only: it writes nothing, sends nothing, and moves no ref beyond the
mail fetch (skipped with ``--no-fetch``). Each section is read on its own, and
one that cannot be read says so on its own line instead of hiding the rest.

    python tools/cc/board.py [--no-fetch] [--json] [--root PATH]

Stdlib-only (``tools/cc/`` runs standalone, zero espalier imports); every
spawn is ``record_merge.run``. Text is 7-bit ASCII. Exit 0, or 2 on a usage
error.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# Sibling helpers, reached through the script's own directory (all ship in the
# deploy set; tests/test_deploy_set_import_closure.py pins the reachability).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _merge_rules  # noqa: E402  the merge-rules read, shared with the SessionStart banner
import mail  # noqa: E402  the claims and assignments folds
from _json_safe import os_error_text  # noqa: E402  an OSError rendered as its path and reason
from record_merge import Unresolvable, run  # noqa: E402  the one spawn and the named stop

Runner = Callable[..., tuple[int, str, str]]

#: The post-merge proof workflow (``.github/workflows/post-merge.yml``), the
#: same file ``ship.py``'s ``POST_MERGE_WORKFLOW`` names.
POST_MERGE_WORKFLOW = "post-merge.yml"
#: The conclusions that are a red verdict. Everything else a completed run can
#: conclude -- cancelled by a newer push, stale, skipped by a job-level `if`,
#: neutral, action required -- is no verdict, so a skipped run never reads as a
#: red base that asks a seat to revert someone's merge.
_RED = frozenset({"FAILURE", "TIMED_OUT", "STARTUP_FAILURE"})
#: How many post-merge runs to read back. The workflow cancels an older run
#: when a newer push lands, so the verdict and the last green before it can be
#: several runs apart.
RUN_WINDOW = 20
#: A pull request's merge on the base: a merge commit ("Merge pull request
#: #158 from ...") or a squash ("subject (#158)"), read from the first line.
_PR_MERGE_RE = re.compile(r"^Merge pull request #(\d+)\b|\(#(\d+)\)\s*$")
GH_TIMEOUT = 15.0
OPEN_PR_LIMIT = 30
LEDGER = "task-packs/FORWARD_LEDGER.md"
#: What GitHub's ``mergeStateStatus`` means for the seat reading it.
MERGE_STATES: dict[str, str] = {
    "CLEAN": "ready",
    "HAS_HOOKS": "ready",
    "UNSTABLE": "ready; an optional check is red",
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
                      "number,headRefName,mergeStateStatus,isDraft,autoMergeRequest,title", run_=run_)
    if not isinstance(answer, list):
        raise Unresolvable("gh pr list answered something other than a list")
    return [pr for pr in answer if isinstance(pr, dict) and isinstance(pr.get("number"), int)]


def read_post_merge(root: Path, base: str, *, run_: Runner = run) -> dict:
    """The newest post-merge run on ``base`` that reached a verdict:
    ``{"verdict": "green"|"red"|"none"|"absent", "sha", "url", "running",
    "green_sha", "suspects", "suspects_unread"}``. ``running`` says a run newer
    than the verdict is going. On red, ``green_sha`` is the last green run
    before it and ``suspects`` the pull requests merged in between, since the
    workflow cancels an older run when a newer push lands and a red one can
    carry several merges (None when no green run is in the window). A failed
    suspects read keeps the red and says so; it never turns red into unread."""
    out: dict = {"verdict": "none", "sha": "", "url": "", "running": False, "green_sha": "",
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
    (loaded by path under a private alias, as record_merge loads it); None
    where the tree keeps no ledger."""
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
    return len(gen.live_member_ids(text))


def lane_seats(by_machine: dict[str, list[dict]]) -> dict[str, str]:
    """``{lane: machine}``: the machine whose LATEST claim or release names the
    lane. A release counts because the ship driver releases a lane's claims
    once its push lands, so the open pull request a seat just shipped has no
    live claim left; the release still says whose lane it was."""
    latest: dict[str, tuple[str, str, int, str]] = {}
    for machine, messages in by_machine.items():
        for i, m in enumerate(messages):
            lane = str((m.get("re") or {}).get("lane") or "")
            if not lane or m.get("type") not in ("claim", "release"):
                continue
            key = (str(m.get("at") or ""), str(m.get("from") or machine), i, str(m.get("from") or machine))
            if lane not in latest or key[:3] > latest[lane][:3]:
                latest[lane] = key
    return {lane: key[3] for lane, key in latest.items()}


def collect(root: Path, *, fetch: bool = True, run_: Runner = run) -> dict:
    """Every section, each read on its own: a section that cannot be read is
    ``{"unread": reason}`` and the rest still come back."""
    board: dict = {"read_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    base = _merge_rules.base_branch(root)
    board["base"] = base
    board["merging"] = _merge_rules.line(*_merge_rules.read(root, None, base))
    machine, _how = mail.machine_setting(root, run=run_)
    board["seat"] = machine or ""
    by_machine: dict = {}
    board["mail_note"] = ""
    try:
        if fetch and machine:
            ok, problem = mail.fetch_mail(root, run=run_)
            if not ok:
                board["mail_note"] = f"the fetch failed ({problem}), so mail is the local refs as last fetched"
        elif fetch:
            board["mail_note"] = "this clone names no machine, so the mail refs were not fetched"
        by_machine, _skipped = mail.read_mail(root, run=run_)
    except Unresolvable as exc:
        board["mail_unread"] = str(exc)
    dispatcher, how = mail.dispatcher_setting(root)
    board["dispatcher"] = {"name": dispatcher or "", "how": how}
    claims = mail.live_claims(by_machine)
    board["claims"] = claims
    board["assignments"] = mail.live_assignments(by_machine, dispatcher)
    seat_of_lane = lane_seats(by_machine)
    try:
        prs = read_open_prs(root, run_=run_)
        for pr in prs:
            pr["seat"] = (seat_of_lane.get(str(pr.get("headRefName") or ""), "")
                          if not board.get("mail_unread") else None)
        board["open_prs"] = prs
    except Unresolvable as exc:
        board["open_prs"] = {"unread": str(exc)}
    try:
        board["post_merge"] = read_post_merge(root, base, run_=run_)
    except Unresolvable as exc:
        board["post_merge"] = {"unread": str(exc)}
    try:
        board["ledger_live"] = read_ledger_live(root)
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
    """The red base and what to do about it. The post-merge workflow cancels an
    older run when a newer push lands, so a red run can carry every merge since
    the last green one: the revert is printed only when exactly one pull
    request merged in between, and otherwise the suspects are named."""
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
        lines.extend(("open PRs: " if i == 0 else "          ") + _pr_line(pr) for i, pr in enumerate(prs))
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
    if board.get("mail_unread"):
        lines.append(head + f"unread (the mail could not be read: {board['mail_unread']})")
    elif not jobs:
        lines.append(head + "no live assignments")
    else:
        for i, a in enumerate(jobs):
            re_ = a.get("re") or {}
            lines.append((head if i == 0 else "          ") + f"{re_.get('seat')}: {_job(re_)} (since {a.get('at')})")
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
    live = board.get("ledger_live")
    if isinstance(live, int):
        lines.append(f"ledger:   {live} live rows")
    elif isinstance(live, dict):
        lines.append(f"ledger:   unread ({live.get('unread')})")
    return "\n".join(_ascii(line) for line in lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="board.py", description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--root", default=None, help="the checkout (default: the one around the cwd)")
    parser.add_argument("--no-fetch", action="store_true", help="read the local mail refs only")
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
