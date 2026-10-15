#!/usr/bin/env python3
"""Launch, list and retire this clone's seats: one driver that sees who works where.

Why this exists
---------------
A seat is one Claude Code session in its own checkout: the clone itself, or a
worktree under ``.claude/worktrees/`` with a machine name of its own
(``git config --worktree espalier.machine``; root CLAUDE.md Core Rule 15). The
hand procedure for starting one was a terminal, a ``cd``, an environment
variable and a ``claude`` that could land in a checkout another session was
already in -- two sessions in one checkout are one seat, the state the rule
exists to prevent, and nothing on the way in looked. Retiring one had a hole
the protocol named: a worktree seat's claims can only be released under its
own name, so removing the worktree first left them live, warning every other
seat forever.

Three verbs, each reading occupancy from ``checkout_sync.occupancy`` (Claude
Code's own session registry, the session markers only when it cannot be read)
and every channel fact from ``mail.py``'s local refs:

* ``list`` -- the clone and each of its worktrees under ``.claude/worktrees/``:
  the seat name (its own, or the one SessionStart would derive), the branch
  and head, the live sessions with what launched them, the live claims and
  jobs on the mail channel, and whether ``checkout_sync``'s removal rules
  would let the worktree go.
* ``launch <seat>`` -- resolve the seat to the clone or its worktree; create a
  missing worktree from ``origin/<base>`` with git (copying the gitignored
  files ``.worktreeinclude`` names, which ``git worktree add`` does not) and
  name it before the session starts; refuse a checkout a live session is in,
  and one whose occupancy cannot be told unless ``--unchecked``; set the
  maintenance switch only with ``--maintenance``; put the seat's own ``.venv``
  first on ``PATH``; then run ``claude`` there with the operator's arguments
  after ``--`` passed through unchanged, or with ``--print`` print the one
  command line. The driver adds no permission flag of its own.
* ``retire <seat>`` -- from the clone: refuse an occupied worktree; release
  the seat's live claims from inside its worktree, under its own name, while
  the worktree still exists; name its live jobs (the dispatcher's to release
  or reassign); then remove the worktree under ``checkout_sync``'s rules for
  that one worktree (clean, merged, no plan in progress, nothing ignored it
  would lose; a lock whose holder exited is released and said).

Verbs::

    python tools/cc/seat.py list [--json] [--no-fetch]
    python tools/cc/seat.py launch <seat> [--maintenance] [--unchecked] [--print] [-- <claude args>]
    python tools/cc/seat.py retire <seat> [--dry-run] [--no-fetch]

Stdlib-only (``tools/cc/`` runs standalone, zero espalier imports); imports
its deployed siblings ``checkout_sync`` and ``mail``. Every git call is
bounded through ``checkout_sync``; the one unbounded spawn is the operator's
own ``claude`` session. Operator-facing text is 7-bit ASCII. Exit 0 on
success, 1 on a named refusal, 2 on a usage error (``launch`` exits with
``claude``'s own code).
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Sibling imports via this script's own directory (board.py's pattern): both
# ship in the deploy set beside this file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import checkout_sync as sync  # noqa: E402  occupancy, the worktree list, the removal rules
import mail  # noqa: E402  the seat names, the claims and jobs folds, the release

WORKTREES_REL = sync.WORKTREES_REL
INCLUDE_FILE = ".worktreeinclude"
#: Claude Code's own branch name for a worktree it creates (``claude
#: --worktree <name>`` makes ``worktree-<name>``, read 2026-10-15), so a seat
#: this driver creates looks like one Claude Code created.
BRANCH_PREFIX = "worktree-"
MAINTENANCE_KEY = "ESPALIER_MAINTENANCE_MODE"
#: What a running session sets in its children (read 2026-10-15 on 2.1.300):
#: carried into a session this driver starts, they would make it a nested
#: child of the session that ran the driver, with that session's messaging
#: token. Named, not a prefix: ``CLAUDE_CODE_*`` also holds user configuration
#: (a Bedrock or Vertex switch) that the new session must keep.
SESSION_ENV = frozenset({
    "CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SSE_PORT",
})
CREATE_WAIT_S = 120.0    # a worktree checkout of the whole tree; never killed, said when still running
FETCH_CAP_S = 20.0
GIT_CAP_S = 10.0


class Refused(Exception):
    """A named stop: the message is what the operator reads; exit 1."""


# -- reading the clone --------------------------------------------------------------

def _git(cwd: Path, *args: str, cap: float = GIT_CAP_S) -> str | None:
    return sync._Git(cwd, None).out(*args, cap=cap)


def clone_root(start: Path) -> Path:
    """The clone's main checkout, from inside it or any of its worktrees."""
    common = _git(start, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common and Path(common).name == ".git":
        return Path(common).parent
    top = _git(start, "rev-parse", "--show-toplevel")
    if not top:
        raise Refused(f"{start} is not inside a git checkout")
    return Path(top)


@dataclass
class Seat:
    """One checkout of the clone and what is known about it."""
    name: str
    path: str
    where: str                      # "the clone" or ".claude/worktrees/<dir>"
    naming: str                     # own | derived | clone | unnamed
    branch: str = ""
    head: str = ""
    oracle: str = ""
    sessions: list[dict] | None = None
    note: str = ""
    claims: list[dict] = field(default_factory=list)
    jobs: list[dict] = field(default_factory=list)
    removal: str = ""               # '' for the clone; "removable" or the reason it stays


def _blocks(root: Path) -> list[dict[str, str]]:
    listing = _git(root, "worktree", "list", "--porcelain")
    if listing is None:
        raise Refused("git could not list this clone's worktrees")
    return sync.parse_worktrees(listing)


def _home(root: Path) -> Path:
    return root.joinpath(*WORKTREES_REL)


def _own_name(path: Path) -> str:
    return _git(path, "config", "--worktree", "--get", mail.MACHINE_KEY) or ""


def _seat_name(clone: str | None, path: Path) -> tuple[str, str]:
    """``(name, how)`` for a worktree: its own configured name, else the one
    SessionStart derives from its folder, else ''."""
    own = _own_name(path)
    if own:
        return own, "own"
    derived = mail.worktree_seat_name(clone, path.name) if clone else None
    return (derived, "derived") if derived else ("", "unnamed")


def _read_channel(root: Path, *, fetch: bool) -> tuple[list[dict], list[dict], str]:
    """``(live claims, live jobs, note)`` from the local mail refs, after one
    bounded fetch unless ``fetch`` is off. An unreadable channel is said,
    never raised: the seats still list."""
    try:
        if fetch:
            ok, problem = mail.fetch_mail(root, timeout=FETCH_CAP_S)
            note = "" if ok else f"the mail fetch failed ({problem}); claims and jobs as last fetched"
        else:
            note = "claims and jobs as last fetched (--no-fetch)"
        by_machine, _skipped = mail.read_mail(root, timeout=GIT_CAP_S)
        dispatcher, _how = mail.dispatcher_setting(root)
        return mail.live_claims(by_machine), mail.live_assignments(by_machine, dispatcher), note
    except mail.Unresolvable as exc:
        return [], [], f"the mail channel could not be read ({exc})"


_READ = object()


def seats(root: Path, *, fetch: bool = True, sessions: object = _READ) -> tuple[list[Seat], str]:
    """Every seat of the clone at ``root``, the clone first, and one note on
    the channel read. ``sessions`` defaults to the live registry read."""
    clone = mail.clone_machine(root)
    blocks = _blocks(root)
    live = sync.live_sessions() if sessions is _READ else sessions
    checkouts = [Path(b["worktree"]) for b in blocks if b.get("worktree") and "prunable" not in b]
    claims, jobs, channel_note = _read_channel(root, fetch=fetch) if clone else ([], [], "")
    found: list[Seat] = []
    for index, block in enumerate(blocks):
        path = Path(block.get("worktree", ""))
        if index == 0:
            seat = Seat(clone or "", str(path), "the clone", "clone" if clone else "unnamed")
        elif sync.within(path, _home(root)):
            name, how = _seat_name(clone, path)
            seat = Seat(name, str(path), "/".join(WORKTREES_REL + (path.name,)), how)
        else:
            continue
        seat.branch = block.get("branch", "").replace("refs/heads/", "") or ("detached" if "detached" in block else "")
        seat.head = block.get("HEAD", "")[:7]
        occ = sync.occupancy(path, sessions=live if isinstance(live, list) else None, checkouts=checkouts)
        seat.sessions, seat.oracle, seat.note = occ.sessions, occ.oracle, occ.note
        seat.claims = [c for c in claims if seat.name and c.get("from") == seat.name]
        seat.jobs = [j for j in jobs if seat.name and (j.get("re") or {}).get(mail.ASSIGN_SEAT_KEY) == seat.name]
        if index:
            seat.removal = _removal_verdict(root, path, live if isinstance(live, list) else None)
        found.append(seat)
    return found, channel_note


def _removal_verdict(root: Path, path: Path, live: list[dict] | None) -> str:
    report = sync.reap_worktrees(root, sessions=live, own_cwd=Path.cwd(), dry_run=True, only=path)
    if report.would_remove:
        return "removable"
    if report.note:
        return report.note
    return report.kept[0][1] if report.kept else "not checked"


# -- list --------------------------------------------------------------------------

def _lanes(messages: list[dict]) -> str:
    lanes = [str((m.get("re") or {}).get("lane") or "") or str(m.get("id", ""))[-6:] for m in messages]
    return ", ".join(lanes) if lanes else "none"


def _sessions_words(seat: Seat) -> str:
    if seat.sessions is None:
        return f"cannot tell ({seat.note})"
    if not seat.sessions:
        return "none"
    words = "; ".join(sync.describe_session(row) for row in seat.sessions)
    return words + (" [session markers: the registry could not be read]" if seat.oracle == "markers" else "")


def render(found: list[Seat], channel_note: str) -> str:
    lines: list[str] = []
    for seat in found:
        on = f"on {seat.branch} at {seat.head}" if seat.branch else f"at {seat.head}"
        named = {"derived": " (name derived; SessionStart sets it)", "unnamed": " (no seat name)"}.get(seat.naming, "")
        lines.append(f"seat {seat.name or '?'}{named} -- {seat.where} ({seat.path}), {on}")
        lines.append(f"  sessions: {_sessions_words(seat)}")
        lines.append(f"  claims:   {_lanes(seat.claims)}")
        lines.append(f"  jobs:     {_lanes(seat.jobs)}")
        if seat.where != "the clone":
            lines.append(f"  retire:   {'would remove it' if seat.removal == 'removable' else 'kept -- ' + seat.removal}")
    if channel_note:
        lines.append(f"({channel_note})")
    return sync._ascii("\n".join(lines))


def cmd_list(root: Path, *, as_json: bool, fetch: bool) -> int:
    found, note = seats(root, fetch=fetch)
    if as_json:
        print(json.dumps({"seats": [asdict(s) for s in found], "note": note}, indent=2))
    else:
        print(render(found, note))
    return 0


# -- resolving a seat ----------------------------------------------------------------

@dataclass
class Target:
    seat: str
    path: Path
    exists: bool
    is_clone: bool


def resolve(root: Path, seat: str) -> Target:
    """The checkout a seat name means: the clone's own name, a worktree whose
    own name is ``seat``, one whose derived name is (it has none of its own
    yet), or -- for a name of the form ``<clone>-<dir>`` -- a worktree at
    ``.claude/worktrees/<dir>`` that does not exist yet."""
    clone = mail.clone_machine(root)
    if not clone:
        raise Refused(f"this clone names no machine, so it has no seats: `git config {mail.MACHINE_KEY} <name>` "
                      "names it (lowercase letters, digits and hyphens)")
    if seat == clone:
        return Target(seat, root, True, True)
    blocks = _blocks(root)
    for block in blocks[1:]:
        path = Path(block.get("worktree", ""))
        if not sync.within(path, _home(root)) or not path.is_dir():
            continue
        name, _how = _seat_name(clone, path)
        if name == seat:
            return Target(seat, path, True, False)
    prefix = f"{clone}-"
    folder = seat[len(prefix):] if seat.startswith(prefix) else ""
    if not folder or mail.worktree_seat_name(clone, folder) != seat:
        raise Refused(f"no seat {seat!r} here: this clone is {clone!r}, and a worktree seat is named "
                      f"{clone}-<folder> for a folder under .claude/worktrees/ (`seat.py list` shows them)")
    path = _home(root) / folder
    if path.exists():
        raise Refused(f"{path} exists but git does not register it as a worktree answering {seat!r}: "
                      "look at it, then remove or repair it by hand (`git worktree repair`)")
    return Target(seat, path, False, False)


def _refuse_occupied(target: Target, *, unchecked: bool) -> None:
    occ = sync.occupancy(target.path)
    if occ.sessions:
        who = "; ".join(sync.describe_session(row) for row in occ.sessions)
        raise Refused(f"seat {target.seat} is occupied: {who} is in {target.path}. One checkout, one session "
                      "(root CLAUDE.md Core Rule 15): use that session, or end it first")
    if occ.sessions is None and not unchecked:
        raise Refused(f"who is in {target.path} cannot be told ({occ.note}); --unchecked launches anyway")


# -- launch --------------------------------------------------------------------------

def _include_entries(root: Path) -> list[str]:
    """The paths ``.worktreeinclude`` names (comments and blanks left out)."""
    try:
        text = (root / INCLUDE_FILE).read_text(encoding="utf-8")
    except OSError:  # fail-open: ok deliberate -- no list, nothing beyond the tracked files is copied (Claude Code's own behaviour without it)
        return []
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def copy_includes(root: Path, worktree: Path) -> list[str]:
    """Copy into a worktree ``git worktree add`` made the gitignored files
    ``.worktreeinclude`` names, as Claude Code does for a worktree it creates:
    without ``.claude/settings.json`` a session there loads no hook at all
    (measured 2026-10-08). Only a path git ignores is copied, never over a
    file. Returns what was copied, repo-relative."""
    copied: list[str] = []
    for entry in _include_entries(root):
        sources = sorted(root.glob(entry)) if any(ch in entry for ch in "*?[") else [root / entry]
        for src in sources:
            rel = src.relative_to(root).as_posix()
            dst = worktree / rel
            if not src.is_file() or dst.exists():
                continue
            ignored = sync._Git(root, None).ask("check-ignore", "-q", "--", rel)
            if ignored is None or ignored.returncode != 0:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(rel)
    return copied


def create(root: Path, target: Target) -> list[str]:
    """``git worktree add -b worktree-<dir> <path> origin/<base>``, never
    killed, then the ``.worktreeinclude`` copies and the seat's name."""
    git = sync._Git(root, None)
    base = sync.default_branch(git) or "main"
    branch = BRANCH_PREFIX + target.path.name
    if git.yes("rev-parse", "-q", "--verify", f"refs/heads/{branch}"):
        raise Refused(f"a branch {branch} already exists (a removed seat's?): look at it (`git log {branch}`), "
                      f"then delete it (`git branch -d {branch}`) or launch a seat with another name")
    fetched = git.ask("-c", "credential.interactive=never", "fetch", "--quiet", "--no-tags", sync.REMOTE,
                      cap=FETCH_CAP_S)
    if fetched is None or fetched.returncode != 0:
        raise Refused(f"origin could not be fetched, so the new seat would start from a stale {base}: retry")
    target.path.parent.mkdir(parents=True, exist_ok=True)
    added = git.change("worktree", "add", "-b", branch, str(target.path), f"{sync.REMOTE}/{base}", wait=CREATE_WAIT_S)
    if added is None:
        raise Refused("git worktree add could not be started")
    if not added.done:
        raise Refused(f"git worktree add is still running (git pid {added.pid}); launch again when it finishes")
    if added.returncode != 0 or not target.path.is_dir():
        raise Refused(f"git worktree add failed: {sync._err(added)}")
    target.exists = True
    return copy_includes(root, target.path)


def child_env(target: Target, *, maintenance: bool, base: dict[str, str] | None = None) -> dict[str, str]:
    """The session's environment: this one minus what a session it may be
    launched from sets in its children (:data:`SESSION_ENV`; the config dir and
    user settings stay), the maintenance switch only when asked for, and the
    seat's own ``.venv`` first on ``PATH``."""
    env = {k: v for k, v in (os.environ if base is None else base).items() if k not in SESSION_ENV}
    if maintenance:
        env[MAINTENANCE_KEY] = "1"
    else:
        env.pop(MAINTENANCE_KEY, None)
    bindir = venv_bindir(target.path)
    if bindir is not None:
        env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    return env


def venv_bindir(path: Path) -> Path | None:
    bindir = path / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    return bindir if bindir.is_dir() else None


def command_line(target: Target, args: list[str], *, maintenance: bool, windows: bool | None = None) -> str:
    """The one line that launches the seat by hand, for this host's shell:
    PowerShell on Windows, a POSIX shell elsewhere."""
    windows = os.name == "nt" if windows is None else windows
    bindir = venv_bindir(target.path)
    if windows:
        def q(s: str) -> str:
            return "'" + s.replace("'", "''") + "'"
        parts = [f"Set-Location -LiteralPath {q(str(target.path))}"]
        parts.append(f"$env:{MAINTENANCE_KEY} = '1'" if maintenance
                     else f"Remove-Item Env:{MAINTENANCE_KEY} -ErrorAction SilentlyContinue")
        if bindir is not None:
            parts.append(f"$env:PATH = {q(str(bindir) + os.pathsep)} + $env:PATH")
        parts.append(" ".join(["claude", *(q(a) for a in args)]))
        return "; ".join(parts)
    env = [f"{MAINTENANCE_KEY}=1"] if maintenance else [f"-u {MAINTENANCE_KEY}"]
    if bindir is not None:
        env.append(f'PATH={shlex.quote(str(bindir))}:"$PATH"')
    return f"cd {shlex.quote(str(target.path))} && env {' '.join(env)} claude {' '.join(shlex.quote(a) for a in args)}".rstrip()


def cmd_launch(root: Path, seat: str, args: list[str], *, maintenance: bool, unchecked: bool,
               print_only: bool) -> int:
    target = resolve(root, seat)
    if target.exists:
        _refuse_occupied(target, unchecked=unchecked)
    elif print_only:
        print(f"seat {seat} has no worktree yet: `seat.py launch {seat}` creates .claude/worktrees/"
              f"{target.path.name} from origin before it starts the session")
        return 1
    else:
        copied = create(root, target)
        print(f"created {target.path} on {BRANCH_PREFIX}{target.path.name}"
              + (f"; copied {', '.join(copied)}" if copied else ""))
    if not target.is_clone:
        name, said = mail.name_this_worktree(target.path)
        if said:
            print(sync._ascii(said))
        if name is None and _own_name(target.path) != seat:
            raise Refused(f"{target.path} does not answer {seat!r} and could not be named: {said or 'no reason given'}")
    if venv_bindir(target.path) is None and (target.path / "espalier" / "__init__.py").is_file():
        print(f"note: {target.path} has no .venv, so a test run there imports espalier from wherever `python` "
              "finds it (the banner's Engine: line); a .venv of its own with an editable install fixes it")
    if print_only:
        print(command_line(target, args, maintenance=maintenance))
        return 0
    env = child_env(target, maintenance=maintenance)
    claude = shutil.which("claude", path=env.get("PATH"))
    if claude is None:
        raise Refused("claude is not on PATH; --print gives the line to run where it is")
    print(f"launching seat {seat} in {target.path}" + (" (maintenance mode)" if maintenance else ""))
    sys.stdout.flush()
    return run_session([claude, *args], cwd=target.path, env=env)


def run_session(argv: list[str], *, cwd: Path, env: dict[str, str]) -> int:
    """The operator's own session: interactive, stdio inherited, no timeout
    (it ends when they end it); the one spawn here not bounded through
    checkout_sync. Tests replace this function, never ``subprocess``."""
    return subprocess.call(argv, cwd=str(cwd), env=env)


# -- retire --------------------------------------------------------------------------

def by_hand_release(clone: str, seat: str, lanes: list[str]) -> str:
    folder = seat[len(clone) + 1:] if seat.startswith(clone + "-") else "<folder>"
    return (f"its worktree is gone and only the name {seat} can release them (protocol item 5): "
            f"git worktree add --detach .claude/worktrees/{folder} origin/main, then "
            f"git -C .claude/worktrees/{folder} config --worktree {mail.MACHINE_KEY} {seat}, then in it "
            + ", ".join(f"python tools/cc/mail.py send --type release --lane {lane}" for lane in lanes or ["<lane>"])
            + f", then python tools/cc/seat.py retire {seat}")


def release_claims(path: Path, seat: str, claims: list[dict], text: str) -> list[str]:
    """Release ``claims`` from inside ``path`` under its own name: one release
    per lane, one per claim that names no lane. Returns what was sent."""
    if mail.machine_setting(path)[0] != seat:
        raise Refused(f"{path} does not answer the name {seat}, so a release sent from it would not close "
                      f"{seat}'s claims")
    sent: list[str] = []
    for lane in sorted({str((c.get("re") or {}).get("lane") or "") for c in claims} - {""}):
        mail.send(path, mail.new_message(seat, "release", text, lane=lane), say=lambda s: sent.append(s))
    for claim in claims:
        if not (claim.get("re") or {}).get("lane"):
            mail.send(path, mail.new_message(seat, "release", text, ack=str(claim.get("id"))),
                      say=lambda s: sent.append(s))
    return sent


def cmd_retire(root: Path, seat: str, *, dry_run: bool, fetch: bool) -> int:
    clone = mail.clone_machine(root) or ""
    if seat == clone:
        raise Refused(f"{seat} is the clone itself: its checkout is the repository, never retired")
    claims, jobs, note = _read_channel(root, fetch=fetch)
    if note:
        print(f"({note})")
    mine = [c for c in claims if c.get("from") == seat]
    held = [j for j in jobs if (j.get("re") or {}).get(mail.ASSIGN_SEAT_KEY) == seat]
    try:
        target = resolve(root, seat)
    except Refused:
        if mine:
            lanes = sorted({str((c.get("re") or {}).get("lane") or "") for c in mine} - {""})
            raise Refused(f"seat {seat} holds {len(mine)} live claim(s) and {by_hand_release(clone, seat, lanes)}")
        raise
    if not target.exists:
        if mine:
            lanes = sorted({str((c.get("re") or {}).get("lane") or "") for c in mine} - {""})
            raise Refused(f"seat {seat} holds {len(mine)} live claim(s) and {by_hand_release(clone, seat, lanes)}")
        raise Refused(f"seat {seat} has no worktree and nothing on the channel: nothing to retire")
    occ = sync.occupancy(target.path)
    if occ.sessions:
        who = "; ".join(sync.describe_session(row) for row in occ.sessions)
        raise Refused(f"seat {seat} is occupied: {who} is in {target.path}; end that session first")
    if occ.sessions is None:
        raise Refused(f"who is in {target.path} cannot be told ({occ.note}), so nothing is released or removed")
    if held:
        print(f"still assigned to {seat}: {_lanes(held)} (the dispatcher releases or reassigns them; "
              "retire leaves jobs alone)")
    if mine and dry_run:
        print(f"dry-run: would release {len(mine)} claim(s) of {seat} ({_lanes(mine)}) from {target.path}")
    elif mine:
        try:
            sent = release_claims(target.path, seat, mine, "Seat retired; claims closed.")
        except mail.Unresolvable as exc:
            raise Refused(f"the release of {seat}'s claims was not sent ({exc}); the worktree is kept") from None
        for line in sent:
            print(sync._ascii(line))
        if fetch:
            mail.fetch_mail(root, timeout=FETCH_CAP_S)
        left = [c for c in _read_channel(root, fetch=False)[0] if c.get("from") == seat]
        if left:
            raise Refused(f"{len(left)} claim(s) of {seat} are still live after the release ({_lanes(left)}); "
                          "the worktree is kept")
    sessions = occ_sessions_for_reap()
    report = sync.reap_worktrees(root, sessions=sessions, own_cwd=Path.cwd(), only=target.path, dry_run=dry_run)
    for name in report.unlocked:
        print(f"unlocked {name}: the lock's holder has exited")
    if dry_run:
        if report.would_remove:
            print(f"dry-run: would remove {target.path}")
        else:
            reason = report.kept[0][1] if report.kept else (report.note or "the removal was not reached")
            after = " (judged now; the release above comes first)" if mine else ""
            print(sync._ascii(f"dry-run: {target.path} would be kept: {reason}{after}"))
        return 0
    if report.removed:
        saved = f"; its session notes saved under cc/blueprints/ ({len(report.saved)} file(s))" if report.saved else ""
        print(f"retired {seat}: removed {target.path}{saved}")
        return 0
    reason = report.kept[0][1] if report.kept else (report.note or "the removal was not reached")
    raise Refused(sync._ascii(f"{target.path} is kept: {reason}"))


def occ_sessions_for_reap() -> list[dict] | None:
    """The registry rows the removal re-checks against: read again at the
    moment of removal, never carried from the occupancy read above."""
    return sync.live_sessions()


# -- the CLI -------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seat.py", description=(__doc__ or "").split("\n", 1)[0])
    sub = parser.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("list", help="the clone and its worktree seats: sessions, claims, jobs, removability")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-fetch", action="store_true", help="read the mail refs as last fetched")
    p = sub.add_parser("launch", help="start a session in a seat's checkout (creating a worktree seat when absent)")
    p.add_argument("seat")
    p.add_argument("--maintenance", action="store_true", help=f"set {MAINTENANCE_KEY}=1 for the session")
    p.add_argument("--unchecked", action="store_true", help="launch when the occupancy cannot be told")
    p.add_argument("--print", dest="print_only", action="store_true", help="print the command line instead")
    p = sub.add_parser("retire", help="release a worktree seat's claims, then remove its worktree")
    p.add_argument("seat")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-fetch", action="store_true")
    return parser


def split_claude_args(argv: list[str]) -> tuple[list[str], list[str]]:
    """``(the driver's own arguments, claude's)``, split at the first ``--``
    before the parser sees either: a remainder argument would also take the
    driver's own flags that follow the seat (``launch x --print`` once ran
    ``claude --print``), and claude's flags must never reach the parser."""
    if "--" in argv:
        at = argv.index("--")
        return argv[:at], argv[at + 1:]
    return argv, []


def main(argv: list[str] | None = None) -> int:
    own, claude_args = split_claude_args(list(sys.argv[1:] if argv is None else argv))
    args = build_parser().parse_args(own)
    if claude_args and args.verb != "launch":
        build_parser().error(f"`--` and what follows belong to launch, not {args.verb}")
    try:
        root = clone_root(Path.cwd())
        if args.verb == "list":
            return cmd_list(root, as_json=args.json, fetch=not args.no_fetch)
        if args.verb == "launch":
            return cmd_launch(root, args.seat, claude_args, maintenance=args.maintenance, unchecked=args.unchecked,
                              print_only=args.print_only)
        return cmd_retire(root, args.seat, dry_run=args.dry_run, fetch=not args.no_fetch)
    except (Refused, mail.Unresolvable) as exc:
        print(f"seat.py: {sync._ascii(str(exc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    from _json_safe import pin_utf8_streams

    pin_utf8_streams()
    sys.exit(main())
