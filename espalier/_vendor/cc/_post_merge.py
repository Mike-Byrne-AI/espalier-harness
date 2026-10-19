"""Post-merge check verdicts: the one home three readers share.

A check that is not required finishes after auto-merge has landed the lane
and reports to nobody unless something reads it. Three surfaces read it --
the ship driver's preflight (``post_merge_reds``), the SessionStart banner's
``Merged:`` line and the board's ``checks:`` line -- and until this module
each kept its own copy of the rule, with its own window, its own ownership
and its own words (a Windows red sat in GitHub's record for six hours on
2026-10-18 while the readers disagreed about it). The rule lives here once:

* ``check_outcome`` reads one ``statusCheckRollup`` row as green, running or
  red; a shape this reader does not know reads as running, never as a pass.
* ``latest_run_per_check`` keeps one row per check name, its latest run,
  since a push or a title edit re-runs a workflow and the rollup lists the
  superseded run beside the new one.
* ``verdicts`` is the banner's per-pull-request rule: a check name is owned
  by the newest merged pull request whose latest run of it reached a
  verdict, green or red; a leg still running, cancelled or stale on a newer
  merge supersedes nothing.
* ``transitions`` is the board's and the preflight's per-check rule: the
  merges walked in merge order, the owned verdict after each, and the merge
  at which it changed; a newer merge's green run takes the name from an
  older merge's red only when it STARTED after that red merge landed (the
  run contained the red change), else the green is carried beside the red.
  Replayed at an instant (``at``), a run that started after it is dropped
  and one that finished after it reads as still running.
* ``lines`` and ``board_lines`` are the words, 7-bit ASCII.

Standard library only, zero ``espalier`` imports: the hook loads this by
path under a private alias; the driver and the board import it as a sibling.
"""
from __future__ import annotations

import json
from typing import Any, Callable

#: One ``statusCheckRollup`` row is a CheckRun (``status`` + ``conclusion``)
#: or a legacy StatusContext (``state``). Not green and not still running
#: reads as red: a cancelled or timed-out cell holds a merge as a failure does.
CHECK_GREEN = frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})
CHECK_RUNNING = frozenset({"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"})
#: A completed CheckRun that reached no verdict. Open, ``check_outcome`` reads
#: it as red (a cancelled cell holds a merge); merged, the leg never reported.
NO_VERDICT = frozenset({"CANCELLED", "STALE"})
#: The ``gh pr checks`` buckets that hold a merge: a cancelled required cell
#: holds it as surely as a failed one (a job no runner picked up reads cancel).
RED_BUCKETS = frozenset({"fail", "cancel"})
#: The fields one merged listing carries for these readers.
MERGED_FIELDS = "number,mergedAt,statusCheckRollup"

Gh = Callable[[list[str]], object]


def ascii_(text: object) -> str:
    """ASCII-folded: the value lands in operator-facing text, and a non-ASCII
    check name would break that contract."""
    return str(text).encode("ascii", "replace").decode("ascii")


def check_outcome(row: object) -> str:
    """'green', 'running' or 'red' for one statusCheckRollup row. A row of a
    shape this reader does not know reads as running: unknown is not a pass."""
    if not isinstance(row, dict):
        return "running"
    state = row.get("state")
    if isinstance(state, str) and state:  # StatusContext
        s = state.upper()
        return "green" if s in CHECK_GREEN else "running" if s in CHECK_RUNNING else "red"
    if str(row.get("status") or "").upper() != "COMPLETED":
        return "running"
    return "green" if str(row.get("conclusion") or "").upper() in CHECK_GREEN else "red"


def _name(row: object) -> str:
    return str(row.get("name") or row.get("context") or "") if isinstance(row, dict) else ""


def latest_run_per_check(rows: list) -> list:
    """One row per check name, its latest run. A later ``startedAt`` wins;
    with none, the later row in the rollup wins. Rows with no name pass through."""
    keep: dict[str, tuple[str, int, object]] = {}
    order: list[tuple[str | None, object]] = []
    for i, r in enumerate(rows):
        name = _name(r)
        if not name:
            order.append((None, r))
            continue
        started = str(r.get("startedAt") or "")
        prev = keep.get(name)
        if prev is None:
            order.append((name, None))
        if prev is None or (started, i) >= (prev[0], prev[1]):
            keep[name] = (started, i, r)
    return [keep[n][2] if n is not None else r for n, r in order]


def prs(data: object) -> list[dict]:
    """The pull requests a parsed ``gh pr list`` listing carries: a row that is
    not a dict with an integer ``number`` is skipped, so a foreign shape (an
    error page, a bare object, ``null``) yields nothing, never a crash."""
    if isinstance(data, str):
        try:
            data = json.loads(data) if data.strip() else []  # json-dict-safe: ok a LIST of rows; each row is isinstance-checked below
        except ValueError:
            return []
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict) and isinstance(row.get("number"), int)]


def read_merged(cwd: object, limit: int, gh: Gh | None = None, author: str | None = None) -> list[dict]:
    """The one ``gh pr list --state merged`` read, ``limit`` rows, with
    ``--author`` only when the caller gives one (the banner names your pull
    requests and passes ``@me``; the board and the preflight pass none). ``gh``
    takes the arguments after ``gh`` and returns the parsed JSON or None; the
    default runs the command in ``cwd``."""
    args = ["pr", "list", "--state", "merged", "--limit", str(limit), "--json", MERGED_FIELDS]
    if author:
        args[2:2] = ["--author", author]
    runner = gh if gh is not None else _default_gh(cwd)
    # A caller's runner keeps its own refusals (the driver refuses a gh that
    # answers without JSON, and the preflight must say so); the default one
    # answers None on any failure, which reads as no merges.
    return prs(runner(args))


def _default_gh(cwd: object) -> Gh:
    """A runner for callers that bring none: one bounded ``gh`` spawn through
    the sibling ``_json_safe.run_bounded`` (loaded by path, so this module
    stays importable by path with nothing on ``sys.path``), None on any
    failure. The driver, the board and the hook all bring their own."""
    import importlib.util
    import subprocess
    from pathlib import Path

    def run(args: list[str]) -> object:
        path = Path(__file__).resolve().with_name("_json_safe.py")
        spec = importlib.util.spec_from_file_location("_post_merge_json_safe", path)
        if spec is None or spec.loader is None:
            return None
        safe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(safe)
        try:
            result = safe.run_bounded(["gh", *args], capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", timeout=20, cwd=str(cwd) if cwd else None)
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout or "")  # json-dict-safe: ok a LIST of rows for `prs`, which isinstance-checks each
        except ValueError:
            return None
    return run


def by_merge_desc(merged: list[dict]) -> list[dict]:
    """Newest merge first, by ``mergedAt``; rows without one keep their listing
    order among themselves (a stable sort), and sort last."""
    return sorted(merged, key=lambda pr: str(pr.get("mergedAt") or ""), reverse=True)


def oldest_merge(merged: list[dict]) -> int | None:
    """The number of the EARLIEST merge read (the smallest ``mergedAt``; a row
    without one counts as oldest), never the lowest number: pull requests merge
    out of number order, and the oldest-read clause must name the merge the
    window actually opens on."""
    rows = by_merge_desc(merged)
    return rows[-1].get("number") if rows else None


def verdicts(merged: list[dict]) -> dict[int, tuple[list[str], list[str]]]:
    """Per merged pull request, in the order given (newest merge first): the
    check names it owns whose latest run is red, and those whose latest run
    reached no verdict. A check name is owned by the newest merged pull
    request whose latest run of it reached a VERDICT, green or red: ledger-only
    chores that never ran a leg cannot push a red code merge out of view, a
    later merge whose leg ran green supersedes an older red, and a leg still
    running, cancelled or stale on the newer merge supersedes nothing."""
    owned: set[str] = set()
    out: dict[int, tuple[list[str], list[str]]] = {}
    for pr in merged:
        rollup = pr.get("statusCheckRollup")
        reds: list[str] = []
        no_verdict: list[str] = []
        for row in latest_run_per_check(rollup if isinstance(rollup, list) else []):
            name = _name(row)
            if not name or name in owned:
                continue
            outcome = check_outcome(row)
            if outcome == "running":
                continue  # not a verdict yet: it supersedes nothing
            conclusion = str(row.get("conclusion") or "").upper()
            if conclusion in NO_VERDICT:
                no_verdict.append(f"{ascii_(name)} ({conclusion.lower()})")
                continue
            owned.add(name)
            if outcome == "red":
                reds.append(ascii_(name))
        if reds or no_verdict:
            out[pr["number"]] = (reds, no_verdict)
    return out


def replay(merged: list[dict], at: str) -> list[dict]:
    """The merged rows as the record stood at the instant ``at`` (an ISO
    stamp, compared as text, so the stamps' own format is the clock): a merge
    after it is dropped, a run that started after it is dropped, and a run
    that finished after it reads as still running. Contexts, which carry no
    stamps, pass through."""
    out: list[dict] = []
    for pr in merged:
        if str(pr.get("mergedAt") or "") > at:
            continue
        rows: list[dict] = []
        for row in pr.get("statusCheckRollup") or []:
            if not isinstance(row, dict):
                continue
            started = str(row.get("startedAt") or "")
            if started and started > at:
                continue
            completed = str(row.get("completedAt") or "")
            if completed and completed > at:
                row = {**row, "status": "IN_PROGRESS", "conclusion": None, "completedAt": None}
            rows.append(row)
        out.append({**pr, "statusCheckRollup": rows})
    return out


def _owner(pr: dict, row: dict, verdict: str) -> dict:
    return {"pr": pr.get("number"), "merged_at": str(pr.get("mergedAt") or ""),
            "started_at": str(row.get("startedAt") or ""), "completed_at": str(row.get("completedAt") or ""),
            "verdict": verdict}


def transitions(merged: list[dict], *, at: str | None = None) -> dict[str, dict]:
    """Per check name, the owned verdict after the merges were walked in merge
    order, oldest first (a row without ``mergedAt`` sorts oldest, in listing
    order), and how it got there:

    ``verdict``: green or red, or None where no run reached one;
    ``owner``: the merge whose run holds the verdict (the newest of its kind);
    ``since``: the merge at which the verdict last changed, with its run's
    ``started_at`` and ``completed_at`` (the leg's finish);
    ``previous``: the owner before that change, or None when the window
    opened on this verdict;
    ``green_beside``: newer merges whose green run started before the owning
    red merge landed, carried beside the red, never over it;
    ``no_verdict``: merges whose latest run reached no verdict (cancelled or
    stale), named beside the owner;
    ``running``: merges whose latest run is still going;
    ``changes``: every change in order, for the transitions log.
    """
    rows = replay(merged, at) if at is not None else list(merged)
    # Oldest first; two rows with one stamp keep the listing's newest-first
    # order reversed, the same tie rule the banner's newest-first walk uses.
    rows = by_merge_desc(rows)[::-1]
    checks: dict[str, dict] = {}
    for pr in rows:
        rollup = pr.get("statusCheckRollup")
        for row in latest_run_per_check(rollup if isinstance(rollup, list) else []):
            name = _name(row)
            if not name:
                continue
            c = checks.setdefault(name, {
                "name": ascii_(name), "verdict": None, "owner": None, "since": None, "previous": None,
                "green_beside": [], "no_verdict": [], "running": [], "changes": [],
            })
            outcome = check_outcome(row)
            if outcome == "running":
                c["running"].append(pr.get("number"))
                continue
            conclusion = str(row.get("conclusion") or "").upper()
            if conclusion in NO_VERDICT:
                c["no_verdict"].append({"pr": pr.get("number"), "conclusion": conclusion.lower(),
                                        "merged_at": str(pr.get("mergedAt") or "")})
                continue
            if conclusion == "SKIPPED":
                continue  # a path-filtered leg that tested nothing: it supersedes nothing and is not named
            owner = c["owner"]
            started = str(row.get("startedAt") or "")
            if owner and owner["verdict"] == "red" and outcome == "green" and started <= owner["merged_at"]:
                c["green_beside"].append({"pr": pr.get("number"), "started_at": started})
                continue
            new = _owner(pr, row, outcome)
            if owner is None or owner["verdict"] != outcome:
                c["changes"].append({**new, "from_pr": owner["pr"] if owner else None,
                                     "from_verdict": owner["verdict"] if owner else None})
                c["since"] = new
                c["previous"] = owner
            # What stood beside the previous owner was read against that merge;
            # a new owner, of either verdict, starts its own beside lists.
            c["green_beside"] = []
            c["no_verdict"] = []
            c["owner"] = new
            c["verdict"] = outcome
    return checks


def _stamp(iso: str) -> str:
    """``2026-10-18T13:26:32Z`` as ``2026-10-18 13:26Z``; anything else as given."""
    if len(iso) >= 17 and iso[10] == "T":
        return f"{iso[:10]} {iso[11:16]}Z"
    return iso


def _finish(since: dict) -> str:
    """The leg's finish beside its merge: the time alone on the merge's day."""
    done, merged = since.get("completed_at") or "", since.get("merged_at") or ""
    if not done:
        return ""
    if done[:10] == merged[:10] and len(done) >= 16:
        return f"{done[11:16]}Z"
    return _stamp(done)


def _since_clause(c: dict, oldest: int | None) -> str:
    since = c["since"] or {}
    pr = since.get("pr")
    if not since.get("merged_at"):
        return ""
    if origin_unknown(c, oldest):
        return f" since #{pr} or earlier (the oldest merge read)"
    text = f" since {_stamp(since['merged_at'])}"
    finish = _finish(since)
    if finish:
        text += f" (the leg finished {finish})"
    return text


def _beside(c: dict) -> list[str]:
    parts: list[str] = []
    prev = c["previous"]
    if prev is not None and prev.get("verdict") == "green":
        parts.append(f"green on #{prev['pr']}")
    for n in c["no_verdict"]:
        parts.append(f"#{n['pr']} no verdict ({n['conclusion']})")
    for g in c["green_beside"]:
        parts.append(f"#{g['pr']} green on a run that started before #{c['owner']['pr']} merged")
    return parts


def reds(checks: dict[str, dict]) -> list[dict]:
    """The red checks, newest red first (by the merge the red is since)."""
    out = [c for c in checks.values() if c["verdict"] == "red" and c["owner"]]
    return sorted(out, key=lambda c: (str((c["since"] or {}).get("merged_at") or ""), c["name"]), reverse=True)


def never_judged(checks: dict[str, dict]) -> list[dict]:
    """The checks whose latest run reached no verdict on every merge read
    (cancelled or stale each time): named, never green and never red."""
    return sorted((c for c in checks.values() if c["verdict"] is None and c["no_verdict"]),
                  key=lambda c: c["name"])


def origin_unknown(c: dict, oldest: int | None) -> bool:
    """True when the red has held since the window opened: the merge it is
    since is the oldest read and nothing before it was read, so the origin
    is at that merge or earlier, never a dated first mention."""
    since = c["since"] or {}
    return c["previous"] is None and oldest is not None and since.get("pr") == oldest


def lines(checks: dict[str, dict], *, oldest: int | None = None) -> list[str]:
    """The preflight's words: one line per red check, ``red after merge: #N
    <check>`` (N the merge whose run holds the red now) then the since clause
    (the merge the red was first owned at, which is older than N when a later
    merge's run was red too) and what stands beside it; then one line per
    check that reached no verdict on every merge read."""
    out: list[str] = []
    for c in reds(checks):
        text = f"red after merge: #{c['owner']['pr']} {c['name']}{_since_clause(c, oldest)}"
        beside = _beside(c)
        if beside:
            text += ", " + "; ".join(beside)
        out.append(ascii_(text))
    for c in never_judged(checks):
        last = c["no_verdict"][-1]
        out.append(ascii_(f"no verdict after merge: {c['name']} ({last['conclusion']} on #{last['pr']}, "
                          f"and on every merge read)"))
    return out


def board_lines(checks: dict[str, dict], *, window: int, oldest: int | None = None,
                new: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """The board's ``checks:`` entries: one per red check name, with the merge
    it went red on, the leg's finish and what stands beside it (``new:`` ahead
    of one this read printed for the first time); one per check that reached
    no verdict on every merge read; one line saying none when nothing is red.
    Pull-request legs, not required checks: the board prints, never reverts."""
    out: list[str] = []
    for c in reds(checks):
        since = c["since"] or {}
        if origin_unknown(c, oldest):
            where = f"red since #{since['pr']} or earlier (the oldest merge read)"
        elif since.get("merged_at"):
            where = f"red since #{since['pr']} (merged {_stamp(since['merged_at'])}"
            finish = _finish(since)
            where += f", the leg finished {finish})" if finish else ")"
        else:
            where = f"red on #{c['owner']['pr']}"
        text = f"{'new: ' if c['name'] in new else ''}{c['name']}: {where}"
        beside = _beside(c)
        if beside:
            text += ", " + "; ".join(beside)
        out.append(ascii_(text))
    for c in never_judged(checks):
        kinds = sorted({n["conclusion"] for n in c["no_verdict"]})
        out.append(ascii_(f"{c['name']}: no verdict on every merge read ({', '.join(kinds)})"))
    if not out:
        out.append(f"none red among the last {window} merges")
    return out


def summary(checks: dict[str, dict]) -> dict[str, Any]:
    """The transitions as data, for ``--json`` and the board's key."""
    return {name: {k: v for k, v in c.items()} for name, c in checks.items()}
