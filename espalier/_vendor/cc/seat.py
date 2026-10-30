#!/usr/bin/env python3
"""Launch, list and retire this clone's seats: one driver that sees who works where.

Why this exists
---------------
A seat is one Claude Code session in its own checkout: the clone itself, or a
worktree under ``.claude/worktrees/`` with a machine name of its own
(``git config --worktree espalier.machine``). Two sessions in one checkout
share its branch and index, so each one's commits and pushes carry the
other's. The hand procedure for starting a seat was a terminal, a ``cd``, an
environment variable and a ``claude`` that could land in a checkout another
session was already in, and nothing on the way in looked. Retiring one had a
hole: a worktree seat's claims can only be released under its own name, so
removing the worktree first left them live, warning every other seat forever.

Three verbs, each reading occupancy from ``checkout_sync.occupancy`` (Claude
Code's own session registry, plus the session markers, which can only add a
session) and every channel fact from ``mail.py``'s local refs:

* ``list`` -- the clone and each of its worktrees under ``.claude/worktrees/``:
  the seat name (its own, or the one SessionStart would derive), the branch
  and head, the live sessions with what launched them, the live claims and
  jobs on the mail channel, and whether ``checkout_sync``'s removal rules
  would let the worktree go.
* ``launch <seat>`` -- run from a terminal of the operator's own, never from
  inside a session. Resolve the seat to the clone or its worktree; create a
  missing worktree from ``origin/<base>`` with git and name it before the
  session starts; copy the gitignored files ``.worktreeinclude`` names into
  it (``git worktree add`` does not, and without ``.claude/settings.json`` a
  session there loads no hook); refuse a checkout a live session is in, and
  one whose occupancy cannot be told unless ``--unchecked``; set the
  maintenance switch only with ``--maintenance``; put the seat's own ``.venv``
  first on ``PATH``; then run ``claude`` there with the operator's arguments
  after ``--`` passed through unchanged and the seat's first message (``brief``)
  as its prompt after a ``--``, unless ``--no-brief``, or with ``--print``
  print the command line (the first message spans two lines inside its
  quotes). The brief is refused beside a flag that does not start a fresh
  session (``-p``, ``--resume`` and the like), a prompt of the operator's own,
  or a ``claude`` that is a ``.cmd`` shim. The own-clear mod beside this
  driver (``mods/own-clear``) rides first in claude's arguments as
  ``--plugin-dir``, unless ``--no-mod``: it runs the real ``/clear`` once the
  handoff's marker is armed and re-primes the window with the brief. The
  driver adds no permission flag of its own.
* ``brief <seat>`` -- print the seat's first message, the one ``launch`` passes:
  a worker's (its dispatcher, the reads to start with, its jobs, the worker
  loop) or the dispatcher's (its duties, the board loop), as the ``dispatcher``
  line of ``espalier.toml`` decides, so no operator pastes it.
* ``retire <seat>`` -- from the clone: refuse an occupied worktree; judge the
  removal first (``checkout_sync``'s rules for that one worktree: clean,
  merged, no plan in progress, nothing ignored it would lose), so a seat that
  must stay keeps its claims; refuse a seat that holds jobs unless
  ``--return-jobs`` hands them back to the dispatcher; then release the
  seat's live claims from inside its worktree, under its own name, each by
  its id; then remove it (a lock whose holder exited is released and said).

Verbs::

    python tools/cc/seat.py list [--json] [--no-fetch]
    python tools/cc/seat.py launch <seat> [--maintenance] [--unchecked] [--no-brief] [--no-mod]
                                          [--print [--shell S]] [-- <claude args>]
    python tools/cc/seat.py brief <seat>
    python tools/cc/seat.py retire <seat> [--dry-run] [--return-jobs] [--unchecked] [--no-fetch]

Stdlib-only (``tools/cc/`` runs standalone, zero espalier imports); imports
its deployed siblings ``checkout_sync`` and ``mail``. Every git call is
bounded through ``checkout_sync``; the one unbounded spawn is the operator's
own ``claude`` session. Operator-facing text is 7-bit ASCII. Exit 0 on
success, 1 on a named refusal, 2 on a usage error, 130 on an interrupt
(``launch`` exits with ``claude``'s own code).
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

# Sibling imports via this script's own directory (board.py's pattern): both
# ship in the deploy set beside this file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import checkout_sync as sync  # noqa: E402  occupancy, the worktree list, the removal rules
import mail  # noqa: E402  the seat names, the claims and jobs folds, the release
from _json_safe import os_error_text  # noqa: E402  an OSError's path spelled as a path

WORKTREES_REL = sync.WORKTREES_REL
INCLUDE_FILE = ".worktreeinclude"
SETTINGS_REL = ".claude/settings.json"
#: Claude Code's own branch name for a worktree it creates (``claude
#: --worktree <name>`` makes ``worktree-<name>``, read 2026-10-15), so a seat
#: this driver creates looks like one Claude Code created.
BRANCH_PREFIX = "worktree-"
MAINTENANCE_KEY = "ESPALIER_MAINTENANCE_MODE"
#: The box-wide lock file the suite's xdist runs take, so two seats on one
#: machine run one tier at a time: one path per host under the temp directory
#: (per user on both OSes), set by the launcher for every seat and never by
#: CI. The suite's plugin exports the holder's pid beside it
#: (``ESPALIER_BOX_LOCK_HOLDER``) to its own children; the launcher sets the
#: path alone.
BOX_LOCK_KEY = "ESPALIER_BOX_LOCK"
BOX_LOCK_NAME = "espalier-box.lock"


def box_lock_default() -> str:
    """The host's default lock path: the temp directory the interpreter
    resolves, which two seats of one user on one box resolve alike."""
    return os.path.join(tempfile.gettempdir(), BOX_LOCK_NAME)
#: What a running session sets in its children: the eleven names read in a
#: session's environment on 2.1.300 (2026-10-15) and the five more Claude Code
#: strips from a child session of its own. Carried into a session this driver
#: starts, they would make it a nested child of the session that ran the
#: driver, with that session's messaging token. Named, never a prefix:
#: ``CLAUDE_CODE_*`` also holds user configuration (a Bedrock or Vertex
#: switch) that the new session must keep.
SESSION_ENV = frozenset({
    "CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SSE_PORT",
    "AI_AGENT", "TRACEPARENT", "CLAUDE_CODE_SESSION_ACCESS_TOKEN", "CLAUDE_CODE_BRIDGE_SESSION_ID",
    "CLAUDE_CODE_WORKER_EPOCH",
})
#: PowerShell's single-quote characters (a typographic one closes a quoted
#: string as surely as the ASCII one), each escaped by doubling.
_PS_SINGLE = "'" + "".join(map(chr, (0x2018, 0x2019, 0x201A, 0x201B)))
#: Double quotes Windows PowerShell 5.1 re-splits a native program's argument at.
_PS_DOUBLE = '"' + "".join(map(chr, (0x201C, 0x201D, 0x201E)))
CREATE_WAIT_S = 120.0    # a worktree checkout of the whole tree; never killed, said when still running
FETCH_CAP_S = 20.0
GIT_CAP_S = 10.0


class Refused(Exception):
    """A named stop: the message is what the operator reads; exit 1."""


def say(text: str) -> None:
    print(sync._ascii(text))


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
    naming_note: str = ""           # why the name could not be read, where naming is "unread"


def _blocks(root: Path) -> list[dict[str, str]]:
    listing = _git(root, "worktree", "list", "--porcelain")
    if listing is None:
        raise Refused("git could not list this clone's worktrees")
    return sync.parse_worktrees(listing)


def _home(root: Path) -> Path:
    return root.joinpath(*WORKTREES_REL)


def _own_name(path: Path) -> tuple[str, str, str]:
    """``(the worktree's own name or '', state, why)``: git's per-worktree
    setting, read as :func:`mail.machine_setting` reads it. ``state`` is
    ``own``, ``unset``, ``refused`` (a value is set there that the channel
    does not take, which is no reason to derive one) or ``unread`` (the read
    failed, said, never taken for "no name of its own")."""
    own, how = mail.machine_setting(path, scope="worktree")
    if own:
        return own, "own", ""
    if how.startswith(mail.MACHINE_UNREAD):
        return "", "unread", how
    return "", ("refused" if mail.NAME_REFUSED in how else "unset"), how


def _seat_name(clone: str | None, path: Path, clone_unread: str = "") -> tuple[str, str, str]:
    """``(name, how, why)`` for a worktree: its own configured name, else the
    one SessionStart derives from its folder, else ''. ``how`` is ``unread``,
    with ``why``, where its own name, or the clone's it would derive from
    (``clone_unread``), could not be read: then no name is given, since a
    derived one could stand for another seat. A value of its own that the
    channel refuses is ``unnamed`` with ``why``: SessionStart will not name a
    worktree that holds one, so no derived name is offered for it either."""
    own, state, why = _own_name(path)
    if state == "unread":
        return "", "unread", why
    if state == "refused":
        return "", "unnamed", why
    if own:
        return own, "own", ""
    if clone_unread:
        return "", "unread", clone_unread
    derived = mail.worktree_seat_name(clone, path.name) if clone else None
    return (derived, "derived", "") if derived else ("", "unnamed", "")


CHANNEL_UNREAD = "the mail channel could not be read"


def _read_channel(root: Path, *, fetch: bool) -> tuple[list[dict], list[dict], str]:
    """``(live claims, live jobs, note)`` from the local mail refs, after one
    bounded fetch unless ``fetch`` is off. An unreadable channel is said in
    the note (opening :data:`CHANNEL_UNREAD`), never raised: the seats still
    list, and ``retire`` refuses on it."""
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
        return [], [], f"{CHANNEL_UNREAD} ({exc})"


def reap_inputs(root: Path, registry: list[dict] | None) -> tuple[list[dict] | None, Callable[[Path], bool]]:
    """The removal rules' inputs, as SessionStart's catch-up builds them: the
    registry's rows plus each live marker in the clone's own state directory
    (a session that moved into a worktree records the move only there), and a
    check for a live marker in the worktree itself."""
    def marker_live(tree: Path) -> bool:
        return bool(sync.marker_sessions(tree))

    if registry is None:
        return None, marker_live
    moved = [{"pid": m["pid"], "session_id": m["session_id"], "cwd": m["cwd"]} for m in sync.marker_sessions(root)]
    return registry + moved, marker_live


_READ = object()


def seats(root: Path, *, fetch: bool = True, sessions: object = _READ) -> tuple[list[Seat], str]:
    """Every seat of the clone at ``root``, the clone first, and one note on
    the channel read. ``sessions`` defaults to the live registry read."""
    clone, clone_how = mail.clone_machine(root)
    clone_unread = clone_how if clone is None and clone_how.startswith(mail.MACHINE_UNREAD) else ""
    blocks = _blocks(root)
    live = sync.live_sessions() if sessions is _READ else sessions
    registry = live if isinstance(live, list) else None
    checkouts = [Path(b["worktree"]) for b in blocks if b.get("worktree") and "prunable" not in b]
    claims, jobs, channel_note = _read_channel(root, fetch=fetch) if clone else ([], [], "")
    if clone_unread:
        channel_note = (f"the clone's machine name could not be read ({clone_unread}), so no seat's claims or "
                        "jobs were read")
    rows, marker_live = reap_inputs(root, registry)
    found: list[Seat] = []
    for index, block in enumerate(blocks):
        path = Path(block.get("worktree", ""))
        if index == 0:
            seat = Seat(clone or "", str(path), "the clone",
                        "clone" if clone else "unread" if clone_unread else "unnamed", naming_note=clone_unread)
        elif sync.within(path, _home(root)):
            name, how, why = _seat_name(clone, path, clone_unread)
            seat = Seat(name, str(path), "/".join(WORKTREES_REL + (path.name,)), how, naming_note=why)
        else:
            continue
        seat.branch = block.get("branch", "").replace("refs/heads/", "") or ("detached" if "detached" in block else "")
        seat.head = block.get("HEAD", "")[:7]
        occ = sync.occupancy(path, sessions=registry, checkouts=checkouts)
        seat.sessions, seat.oracle, seat.note = occ.sessions, occ.oracle, occ.note
        seat.claims = [c for c in claims if seat.name and c.get("from") == seat.name]
        seat.jobs = [j for j in jobs if seat.name and (j.get("re") or {}).get(mail.ASSIGN_SEAT_KEY) == seat.name]
        if index:
            seat.removal = _removal_verdict(root, path, rows, marker_live)
        found.append(seat)
    return found, channel_note


def _removal_verdict(root: Path, path: Path, rows: list[dict] | None, marker_live: Callable[[Path], bool]) -> str:
    report = sync.reap_worktrees(root, sessions=rows, own_cwd=Path.cwd(), marker_live=marker_live,
                                 dry_run=True, only=path)
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
    return words + (" [the registry could not be read: session markers only]" if seat.oracle == "markers" else "")


def render(found: list[Seat], channel_note: str) -> str:
    lines: list[str] = []
    for seat in found:
        on = f"on {seat.branch} at {seat.head}" if seat.branch else f"at {seat.head}"
        named = {"derived": " (name derived; SessionStart sets it)", "unnamed": " (no seat name)",
                 "unread": f" (seat name unread: {seat.naming_note})"}.get(seat.naming, "")
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
    clone, clone_how = mail.clone_machine(root)
    if not clone:
        if clone_how.startswith(mail.MACHINE_UNREAD):
            raise Refused(f"{clone_how}, so no seat of this clone can be resolved; {mail.RETRY_HINT}")
        raise Refused(f"this clone names no machine, so it has no seats: `git config {mail.MACHINE_KEY} <name>` "
                      "names it (lowercase letters, digits and hyphens)")
    if seat == clone:
        return Target(seat, root, True, True)
    registered: dict[str, tuple[Path, str]] = {}
    unread: list[str] = []
    for block in _blocks(root)[1:]:
        path = Path(block.get("worktree", ""))
        if not sync.within(path, _home(root)):
            continue
        name, how, why = _seat_name(clone, path) if path.is_dir() else ("", "gone", "")
        if name == seat:
            return Target(seat, path, True, False)
        if how == "unread":
            unread.append(f"{path} ({why})")
        registered[sync._norm(path)] = (path, name)
    if unread:
        raise Refused(f"the seat name of {'; '.join(unread)} could not be read, so whether it is {seat!r} cannot be "
                      f"told: nothing is resolved; {mail.RETRY_HINT}")
    prefix = f"{clone}-"
    folder = seat[len(prefix):] if seat.startswith(prefix) else ""
    if not folder or mail.worktree_seat_name(clone, folder) != seat:
        raise Refused(f"no seat {seat!r} here: this clone is {clone!r}, and a worktree seat is named "
                      f"{clone}-<folder> for a folder under .claude/worktrees/ (`seat.py list` shows them)")
    path = _home(root) / folder
    hit = registered.get(sync._norm(path))
    if hit is not None:
        answers = f"answers {hit[1]!r}" if hit[1] else "has no folder or no seat name"
        raise Refused(f"{path} is a registered worktree that {answers}, not {seat!r}: "
                      f"`seat.py list` shows what each answers ({hit[1] and f'launch {hit[1]}' or 'look at it first'})")
    if path.exists():
        raise Refused(f"{path} exists but git does not register it as a worktree: look at what is in it before "
                      "anything else (`git worktree list`; `git worktree repair` if it should be one)")
    return Target(seat, path, False, False)


def _occupants(occ: sync.Occupancy) -> str:
    who = "; ".join(sync.describe_session(row) for row in occ.sessions or [])
    hints = []
    if any(row.get("kind") == "background" for row in occ.sessions or []):
        hints.append("a background session is one Claude Code's daemon resumed: `claude daemon stop --any` ends it")
    if occ.from_registry():
        hints.append(f"their entries are under {sync.claude_config_dir() / 'sessions'}")
    return who + (f" ({'; '.join(hints)})" if hints else "")


def _refuse_occupied(seat: str, path: Path, *, unchecked: bool, verb: str) -> sync.Occupancy:
    """Refuse a checkout a session is in. The registry's sessions always
    refuse; a session only a marker names refuses unless ``--unchecked``
    (a marker outlives its window when its pid cannot be read); an answer no
    oracle can give refuses unless ``--unchecked`` for ``launch``, and always
    for ``retire``, which deletes."""
    occ = sync.occupancy(path)
    if occ.sessions is None:
        if unchecked and verb == "launch":
            return occ
        tail = "; --unchecked launches anyway" if verb == "launch" else ", so nothing is released or removed"
        raise Refused(f"who is in {path} cannot be told ({occ.note}){tail}")
    marked_only = bool(occ.sessions) and not occ.from_registry()
    if occ.sessions and not (marked_only and unchecked):
        tail = " (only a session marker names it: --unchecked passes it)" if marked_only else ""
        raise Refused(f"seat {seat} is occupied: {_occupants(occ)} is in {path}{tail}. One checkout holds one "
                      "session at a time: use that session, or close it first")
    return occ


# -- launch --------------------------------------------------------------------------

def session_refusal() -> str:
    """Why this process cannot start an interactive session, or ''. Inside a
    session the new one would be a hidden child of it; without a terminal on
    standard input nobody could type into it."""
    if os.environ.get("CLAUDECODE"):
        return ("this runs inside a Claude Code session, where the session it started would be a hidden child "
                "of this one: run it from a terminal of your own, or take the line --print gives")
    try:
        tty = sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):  # fail-open: ok deliberate -- an unreadable stdin is no terminal (the refusal side)
        tty = False
    if not tty:
        return ("standard input is not a terminal, so nobody could type into the session: run it from a "
                "terminal, or take the line --print gives")
    return ""


def _include_entries(root: Path) -> list[str]:
    """The entries ``.worktreeinclude`` lists (comments and blanks left out)."""
    try:
        text = (root / INCLUDE_FILE).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):  # fail-open: ok deliberate -- no list, nothing beyond the tracked files is copied (Claude Code's own behaviour without it)
        return []
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def _include_sources(root: Path, entry: str) -> list[Path]:
    """The root's files one entry names: a path relative to the root (a
    leading ``/`` anchors it there, as in a gitignore file) or a glob, never
    one inside another seat's worktree. Raises ValueError for an entry it
    does not take (a directory, an absolute path)."""
    pattern = entry.lstrip("/")
    if not pattern or pattern.endswith("/") or Path(pattern).is_absolute() or Path(pattern).drive:
        raise ValueError("a directory, an absolute path or an empty entry")
    if any(ch in pattern for ch in "*?["):
        home = _home(root)
        return [p for p in sorted(root.glob(pattern)) if not sync.within(p, home)]
    return [root / pattern]


def copy_includes(root: Path, worktree: Path) -> tuple[list[str], list[str]]:
    """Copy into ``worktree`` the gitignored files ``.worktreeinclude`` names,
    as Claude Code does for a worktree it creates: without
    ``.claude/settings.json`` a session there loads no hook at all (measured
    2026-10-08). Only a path git ignores is copied, never over a file.
    Returns ``(copied, skipped with why)``, repo-relative; an entry this
    cannot take is skipped and said, never raised."""
    copied: list[str] = []
    skipped: list[str] = []
    git = sync._Git(root, None)
    for entry in _include_entries(root):
        if entry.startswith("!"):
            skipped.append(f"{entry} (a negation)")
            continue
        try:
            for src in _include_sources(root, entry):
                if not src.is_file():
                    continue
                rel = src.relative_to(root).as_posix()
                dst = worktree / rel
                if dst.exists():
                    continue
                ignored = git.ask("check-ignore", "-q", "--", rel)
                if ignored is None or ignored.returncode != 0:
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied.append(rel)
        except (ValueError, NotImplementedError, OSError) as exc:
            skipped.append(f"{entry} ({sync._ascii(os_error_text(exc))[:80]})")
    return copied, skipped


def _settings_missing(root: Path, worktree: Path) -> bool:
    """True when ``.worktreeinclude`` lists the hooks' settings file, the clone
    has it, and the worktree does not: a session there would load no hook."""
    listed = any(e.lstrip("/") == SETTINGS_REL for e in _include_entries(root))
    return listed and (root / SETTINGS_REL).is_file() and not (worktree / SETTINGS_REL).is_file()


def create(root: Path, target: Target) -> None:
    """``git worktree add -b worktree-<dir> <path> origin/<base>``, never
    killed. Refused where ``.claude/worktrees/`` is not gitignored (the new
    checkout would show as untracked, and ``git add -A`` would commit it as a
    gitlink), where origin cannot be fetched, and where the branch is taken by
    unmerged work; a leftover branch already merged into the base is deleted
    first and said."""
    git = sync._Git(root, None)
    rel = "/".join(WORKTREES_REL + (target.path.name,))
    probe = git.ask("check-ignore", "-q", "--", f"{rel}/{INCLUDE_FILE}")
    if probe is None or probe.returncode != 0:
        raise Refused(f"{rel}/ is not ignored by git here, so a worktree there would show as untracked and "
                      "`git add -A` would commit it: add `.claude/worktrees/` to .gitignore first")
    base = sync.default_branch(git) or "main"
    fetched = git.ask("-c", "credential.interactive=never", "fetch", "--quiet", "--no-tags", sync.REMOTE,
                      cap=FETCH_CAP_S)
    if fetched is None or fetched.returncode != 0:
        raise Refused(f"origin could not be fetched, so the new seat would start from a stale {base}: retry")
    upstream = f"{sync.REMOTE}/{base}"
    branch = BRANCH_PREFIX + target.path.name
    if git.yes("rev-parse", "-q", "--verify", f"refs/heads/{branch}"):
        listing = git.out("worktree", "list", "--porcelain") or ""
        in_use = f"branch refs/heads/{branch}" in listing.splitlines()
        if in_use or not git.yes("merge-base", "--is-ancestor", f"refs/heads/{branch}", upstream):
            raise Refused(f"a branch {branch} already exists with work {upstream} lacks, or checked out elsewhere: "
                          f"look at it (`git log {upstream}..{branch}`), then delete it or launch another seat name")
        git.ask("branch", "-D", branch)
        say(f"deleted the leftover branch {branch} (merged into {upstream}, checked out nowhere)")
    target.path.parent.mkdir(parents=True, exist_ok=True)
    added = git.change("worktree", "add", "-b", branch, str(target.path), upstream, wait=CREATE_WAIT_S)
    if added is None:
        raise Refused("git worktree add could not be started")
    if not added.done:
        raise Refused(f"git worktree add is still running (git pid {added.pid}); launch again when it finishes")
    if added.returncode != 0 or not target.path.is_dir():
        raise Refused(f"git worktree add failed: {sync._err(added)}")
    target.exists = True
    say(f"created {target.path} on {branch} from {upstream}")


def venv_bindir(path: Path) -> Path | None:
    bindir = path / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    return bindir if bindir.is_dir() else None


def child_env(target: Target, *, maintenance: bool, base: dict[str, str] | None = None,
              own_clear: bool = False, own_clear_log: str | None = None) -> dict[str, str]:
    """The session's environment: this one minus what a session it may be
    launched from sets in its children (:data:`SESSION_ENV`; the config dir and
    user settings stay) and minus the own-clear's names (:data:`OWN_CLEAR_ENV`:
    a root or a log left exported in the operator's shell would aim every
    seat's mod at one checkout), the maintenance switch only when asked for,
    ``ESPALIER_OWN_CLEAR=1`` only when the own-clear mod rides this launch (so
    ``ship.py handoff`` can tell whether the window will clear itself), the
    mod's log (``own_clear_log``, :data:`OWN_CLEAR_LOG_KEY`) only beside that
    flag, and the seat's own ``.venv`` first on ``PATH`` and named in
    ``VIRTUAL_ENV`` -- or no ``VIRTUAL_ENV`` at all, since the inherited one
    names another checkout's (read 2026-10-15: a worktree session's named the
    main checkout's, where a ``uv pip install`` would land)."""
    env = {k: v for k, v in (os.environ if base is None else base).items()
           if k not in SESSION_ENV and k not in OWN_CLEAR_ENV}
    if maintenance:
        env[MAINTENANCE_KEY] = "1"
    else:
        env.pop(MAINTENANCE_KEY, None)
    if own_clear:
        env[OWN_CLEAR_KEY] = "1"
        if own_clear_log:
            env[OWN_CLEAR_LOG_KEY] = own_clear_log
    # The box lock: the inherited path when the parent named one, else the
    # host's default, so every launched seat on this machine locks one file.
    env.setdefault(BOX_LOCK_KEY, box_lock_default())
    bindir = venv_bindir(target.path)
    if bindir is not None:
        env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(bindir.parent)
    else:
        env.pop("VIRTUAL_ENV", None)
    return env


def command_line(target: Target, args: list[str], *, maintenance: bool, shell: str | None = None,
                 own_clear: bool = False, own_clear_log: str | None = None) -> str:
    """The one line that launches the seat by hand: PowerShell (the default on
    Windows) or a POSIX shell, setting what :func:`child_env` sets (the
    own-clear flag only with ``own_clear``, its log only beside that flag, its
    other names unset either way). Refused for PowerShell when an argument
    holds a double quote, which Windows PowerShell 5.1 re-splits a native
    program's argument at."""
    shell = shell or ("powershell" if os.name == "nt" else "posix")
    bindir = venv_bindir(target.path)
    log = own_clear_log if own_clear and own_clear_log else None
    own_clear_unsets = sorted(OWN_CLEAR_ENV - ({OWN_CLEAR_KEY} if own_clear else set())
                              - ({OWN_CLEAR_LOG_KEY} if log else set()))
    if shell == "powershell":
        bad = [a for a in args if any(ch in a for ch in _PS_DOUBLE)]
        if bad:
            raise Refused(f"an argument holds a double quote ({bad[0]!r}), which Windows PowerShell 5.1 splits for "
                          "a native program: launch without --print, or use --shell posix")

        def q(s: str) -> str:
            return "'" + "".join(ch * 2 if ch in _PS_SINGLE else ch for ch in s) + "'"
        parts = [f"Set-Location -LiteralPath {q(str(target.path))}"]
        parts.append(f"$env:{MAINTENANCE_KEY} = '1'" if maintenance
                     else f"Remove-Item Env:{MAINTENANCE_KEY} -ErrorAction SilentlyContinue")
        parts += [f"Remove-Item Env:{name} -ErrorAction SilentlyContinue" for name in own_clear_unsets]
        if own_clear:
            parts.append(f"$env:{OWN_CLEAR_KEY} = '1'")
            if log:
                parts.append(f"$env:{OWN_CLEAR_LOG_KEY} = {q(log)}")
        if bindir is not None:
            parts.append(f"$env:VIRTUAL_ENV = {q(str(bindir.parent))}")
            parts.append(f"$env:PATH = {q(str(bindir) + ';')} + $env:PATH")
        else:
            parts.append("Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue")
        # The host's default only where the terminal names no path of its own,
        # as child_env keeps an inherited one: two seats must lock one file.
        parts.append(f"if (-not $env:{BOX_LOCK_KEY}) {{ $env:{BOX_LOCK_KEY} = {q(box_lock_default())} }}")
        parts.append(" ".join(["claude", *(q(a) for a in args)]))
        return "; ".join(parts)
    # Every `-u` before the first assignment: BSD `env` (macOS) stops reading
    # options at the first assignment and runs `-u` as the program (exit 127,
    # driven 2026-10-26); GNU `env` permutes its arguments and takes either order.
    unsets = ([] if maintenance else [MAINTENANCE_KEY]) + own_clear_unsets
    assigns = (([f"{MAINTENANCE_KEY}=1"] if maintenance else []) + ([f"{OWN_CLEAR_KEY}=1"] if own_clear else [])
               + ([f"{OWN_CLEAR_LOG_KEY}={shlex.quote(log)}"] if log else []))
    if bindir is not None:
        assigns += [f"VIRTUAL_ENV={shlex.quote(str(bindir.parent))}", f'PATH={shlex.quote(str(bindir))}:"$PATH"']
    else:
        unsets.append("VIRTUAL_ENV")
    env = [f"-u {name}" for name in unsets] + assigns
    # An export, not an `env` word: `env`'s options precede its assignments, and
    # the exported path also puts a tier run from that terminal under the lock.
    # The terminal's own path wins where it names one (`${VAR:-default}`), as
    # child_env keeps an inherited one.
    return (f"cd {shlex.quote(str(target.path))} && export {BOX_LOCK_KEY}=${{{BOX_LOCK_KEY}:-{shlex.quote(box_lock_default())}}} && "
            f"env {' '.join(env)} claude {' '.join(shlex.quote(a) for a in args)}").rstrip()


# -- brief ---------------------------------------------------------------------------

#: A seat's first message is composed here, never pasted: one template per role
#: (``espalier.toml``'s ``dispatcher`` line decides which a seat gets), filled
#: with the seat, the dispatcher, the base branch and what the seat's checkout
#: holds. Its last line is the seat's loop: driven on Claude Code 2.1.301
#: (2026-10-15), a first message whose last line is a ``/loop`` line starts that
#: loop with no second message, and the loop survives ``/clear``. No double
#: quote (Windows PowerShell 5.1 splits a native argument there), no ``%``
#: (cmd.exe expands it) and 7-bit ASCII; ``tests/test_seat.py`` pins all three.
#: On this repository the worker loop renders to the operator's tick byte for
#: byte (``tests/test_seat.py::_OPERATOR_TICK``): the tick the operator ran by
#: hand on 2026-10-15, its review step read from the diff since 2026-10-16 on
#: the operator's yes, and since 2026-10-24 (the operator's yes on the mail
#: channel) the mail driver's refresh sentence after the lane step and the
#: proceed clause in place of the STOP clause. The proceed clause is this
#: repository's rule (the protocol's *Assign authority*, "The seat's side of
#: it"), so it renders on this repository alone (``SELF_HOST_PROCEED``); an
#: adopter's seat keeps the stop-and-ask form (``ADOPTER_PROCEED``), as its
#: dispatcher proposes every assign. Every figure in a template is rendered
#: from ``DISPATCHER_TICK``, never typed. A change to the tick changes what
#: every worker seat does, which is the operator's decision; a seat already
#: looping keeps its old tick until its loop is started again from a brief
#: composed from a checkout that holds the change.
WORKER_BRIEF = (
    "You are seat {seat}, a worker under {dispatcher_phrase} ({protocol}). Orient from the banner, then run "
    "/inbox (mark read) and /inbox board, and read live state before you state it. Your jobs are the live "
    "assigns for this seat that /inbox board lists; take no other work. When the operator ends your session, "
    "or when the prompt router's threshold ask says to (a lane in hand finishes through its own landing first; "
    "the ask never ships a half-done lane), run /handoff: it writes your Session Log row{handoff_ship}; after "
    "a threshold handoff take no new job until the window is cleared. Then start the worker loop on the next "
    "line with no further message from the operator."
)
WORKER_TICK = (
    "/loop 10m Worker tick. Run /inbox (mark read) and /inbox board and read live state. Act only on what is "
    "yours, in this order: your own open PR red, in conflict or stale (fix it, or ship.py catch-up); a new "
    "assign or note from {dispatcher}; continue your current lane through its full procedure (plan, {review}, "
    "one fix batch, {tier}, one open PR per seat, every step listed with "
    "its evidence in the PR body; a skipped step is a stop), then run mail.py refresh once; it writes nothing "
    "when nothing is new; where mail.py answers invalid choice, this checkout predates the verb: skip it until "
    "the lane merges main, not a stop; then your next assigned job, unless the prompt router has asked for the "
    "threshold handoff: then finish the lane in hand, hand off, and take no new job until the window is "
    "cleared. {proceed} Never unassigned work, never "
    "another seat's branch. A quiet tick is one line."
)
#: The fork rule, by tree. This repository's seat proceeds on its own
#: recommendation after the dispatcher's tick (the protocol's seat's-side
#: paragraph as it reads: the request's age is on the board's asks line, a
#: redirect: ack re-aims, a row is never a stop, the shelved: note names the
#: job the push closed since the push released the claims, and a shelved lane
#: is not re-fixed every tick); an adopter's seat stops and asks. Since
#: 2026-10-25 (the operator's words, in the dispatcher session) it ends with the
#: dispatch-model sentence (the protocol's "The model on a dispatch"
#: paragraph): a model below the seat's own on a subagent dispatch only for a
#: kind named on an allowance: line of the job's assign; a kind word anywhere
#: else is the job's text; a dispatch no such line names runs at the seat's
#: own model; a named agent runs at its own pin; the higher choice is never a
#: finding. The marker follows OPERATOR CALL:, redirect: and shelved:, because
#: the four kind words are ordinary assign vocabulary (54 of the dispatcher's
#: first 129 assigns carried one as plain instruction, read 2026-10-25). The
#: kinds render from DISPATCH_KINDS, one source for the tick and the
#: dispatcher brief, which a test holds the protocol paragraph to.
#: The kinds of sub-task a dispatcher may hand to a subagent below the seat's
#: own model, in the order the tick says them.
DISPATCH_KINDS = ("anchors", "drive", "census", "mutants")


def dispatch_kinds_phrase() -> str:
    """The kinds as the tick says them: ``anchors, drive, census and mutants``."""
    return ", ".join(DISPATCH_KINDS[:-1]) + " and " + DISPATCH_KINDS[-1]


SELF_HOST_PROCEED = (
    "On a choice the assign does not settle, send {dispatcher} one request with your Task 0 recommendation and "
    "its citation, then proceed on it after {wait} minutes (the dispatcher's tick; the board's asks line shows "
    "your request's age) with no answer; a request with no recommendation keeps the stop, and an ack from "
    "{dispatcher} beginning redirect: re-aims you at once. STOP and only re-read mail for what the assign "
    "authority reserves for the operator (a new pack, a scope change, a release or tag, a revert that is not "
    "the red-main revert, an open operator call on your fork), a platform stop, a refusal you cannot resolve, "
    "or a conflict outside your own files; a row to file is never a stop. A red you cannot fix in two "
    "attempts: shelve the lane (one note beginning shelved: says what was tried and names any job your push "
    "closed; a shelved lane waits for the dispatcher, not your next tick), take your next assigned job (after "
    "the threshold ask: hand off instead). Pass a "
    "model below your own on a subagent dispatch only for a kind named on an allowance: line of the assign for "
    "the job in hand (the kinds are {kinds}); a kind word anywhere else is the job's text, a dispatch no "
    "allowance: line names runs at your own model, a named agent runs at its own pin and needs no allowance, "
    "and choosing your own model where a lower one was allowed is never a finding."
)
ADOPTER_PROCEED = (
    "STOP and send {dispatcher} one request, then only re-read mail until it is answered, on anything not "
    "green: a red you cannot fix in two attempts, a choice the assign does not settle, a refusal you cannot "
    "resolve, a conflict outside your own files, anything that is the operator's decision."
)
#: The one exception to the operator's decisions, this repository's own (the
#: operator's standing rule, 2026-10-30, after seats held eleven hours on
#: 10-29 and seven calls sat two and a half hours on 10-30 waiting on
#: decisions): a gridlock, where no seat can advance its assigned job and the
#: next step is a decision, is resolved by the dispatcher seat, which has the
#: context to see every seat and the authority to act; the protocol's Assign
#: authority paragraph is its home, and a test holds this sentence to it. It
#: renders right after the operator's sentence, and an adopter's brief
#: carries nothing in the slot, as with SELF_HOST_FIGURES.
SELF_HOST_GRIDLOCK = (
    "A gridlock, where no seat can advance its assigned job and the next step is a decision (a red main no "
    "revert clears, two lanes in conflict, a ruling a worker waits on past the hour), is yours to resolve, the "
    "one exception to what you propose to the operator: rule, act and report the ruling as an ack with the "
    "facts you read, instead of filing an operator call and waiting; the operator can reverse it, and a new "
    "pack, a scope change, a release or tag stay the operator's. "
)
DISPATCHER_BRIEF = (
    "You are the dispatcher seat {seat} ({protocol}). Orient from the banner{goal}, then run /inbox (mark "
    "read) and /inbox board. Your duties: read the board every {every} minutes (the loop on the next line), "
    "answer every worker request within the hour with facts, {assign}, {red}, write the Landing lines of the "
    "packs in flight from the seats' merged PR bodies. {figures}Decisions stay the operator's. {gridlock}At the "
    "operator's word, or when the prompt router's threshold ask says to (a lane in hand finishes through its "
    "own landing first), run /handoff; it writes your row{row_source}; after a threshold handoff take no new "
    "job until the window is cleared (a red main's revert is not a new job). Start the loop on the next line "
    "with no "
    "further message from the operator."
)
DISPATCHER_TICK = "/loop 15m /inbox board"
#: The dispatcher's interval in minutes, read from its loop line: the one
#: figure both briefs quote, so a changed loop re-renders every mention.
TICK_MINUTES = DISPATCHER_TICK.split()[1].rstrip("m")
#: Where the seat procedure lives, the first a checkout holds: this
#: repository's protocol, else the seeded workflow guide's section.
PROTOCOL_HOMES = (
    ("memory/parallel-work-protocol.md", "Core Rule 15, memory/parallel-work-protocol.md"),
    ("docs/WORKFLOW.md", "docs/WORKFLOW.md, Parallel seats"),
)
PROTOCOL_FALLBACK = "the /inbox command's body"
#: The proof a worker's lane runs: the tier script where the checkout has one,
#: else the change command's own proof step.
TIER_SCRIPT = "scripts/proof_tier.py"
GOAL_NOTES = "cc/GOAL.md"
#: The phrases that differ where the checkout holds this repository's own
#: protocol (its first home above) from an adopter's: the review procedure
#: (a snapshot clone is defined here only) and a red base (reverting first is
#: this repository's rule; an adopter's dispatcher proposes it).
#: The review a lane runs is the one its diff earns (air, 2026-10-16, the
#: operator's yes): on this repository the tier script prints it on its
#: `review:` line (none, code-reviewer or both, /implement-task step 6's rule
#: computed); elsewhere step 6's rule, read from the body. A reviewer the diff
#: does not earn is not a skipped step.
SELF_HOST_REVIEW = "red-team the reviewers scripts/proof_tier.py --base origin/{base} names, on a snapshot clone"
ADOPTER_REVIEW = "the reviewers the diff earns, dispatched at once with your edits frozen, per /implement-task step 6"
SELF_HOST_RED = "revert first on a red {base}"
ADOPTER_RED = "propose the revert to the operator on a red {base}"
#: The dispatcher's assign authority: this repository's operator decided it
#: on 2026-10-15 (the protocol's Assign authority paragraph is its home); an
#: adopter's dispatcher proposes every assign, as before.
SELF_HOST_ASSIGN = (
    "assign, re-sequence and release jobs within approved packs and live ledger rows on your own and "
    "report each at your next tick, each assign in its shape (the job, why now, what it waits for, "
    "the operator's constraints, an edge with its citation, an allowance: line naming the kinds a subagent may "
    "run below your model (the kinds are {kinds}) or no such line; never the tier or the reviewers, which "
    "the tier script prints; under 900 characters), propose the rest to the operator (a new pack, a "
    "scope change, a release or tag, a revert that is not the red-main revert, and every open operator "
    "call, which you send as a request opening with OPERATOR CALL: so the board's asks line lists it "
    "for every seat until your ack naming its id carries the ruling; the protocol's Assign authority paragraph)"
)
ADOPTER_ASSIGN = "propose assigns and releases to the operator and send them on a yes"
#: The rules a dispatcher's report keeps, this repository's own (the operator,
#: 2026-10-20): its workers corrected figures carried by hand, settings restated
#: from memory and counts with no population. The census it names is this
#: repository's script, so an adopter's brief carries nothing in the slot.
SELF_HOST_FIGURES = (
    "Every count you state names its population, every setting a tool computes is quoted from the tool, and "
    "the day's figures come from scripts/seat_day_census.py, never carried by hand. "
)
#: What a seat's /handoff does beyond writing its Session Log row, this
#: repository's own: the push onto the open lane or the park on the seat's
#: records ref (`handoff_push` in espalier.toml), and the dispatcher's row
#: derived from the mail and the merges (scripts/seat_day_census.py). An
#: adopter's /handoff writes the row, so its briefs say that alone.
SELF_HOST_HANDOFF_SHIP = " and ships it on your open lane or parks it"
SELF_HOST_ROW_SOURCE = ", derived from the mail and the merges"
#: Flags after which claude is not starting a fresh session from a first
#: message (a one-shot, a resumed or a continued conversation, a session
#: brought over): the brief is refused beside them, never passed.
SESSION_MODE_FLAGS = frozenset({"-p", "--print", "-c", "--continue", "-r", "--resume", "--from-pr", "--teleport"})
#: The own-clear mod beside this driver (a Claude Code plugin of function
#: hooks): ``launch`` loads it with ``--plugin-dir``, first in claude's
#: arguments, when its manifest is there (this repository's seats; an adopter
#: tree's deploy does not carry it yet), unless ``--no-mod``. Once ``ship.py
#: handoff`` has armed its marker the mod runs the real ``/clear`` at the
#: turn's end, refuses the duplicate compaction meanwhile, and re-primes the
#: window with the brief (``reprime_text``); its README says the rest.
MOD_DIR = Path(__file__).resolve().parent / "mods" / "own-clear"
#: Set to ``1`` in a session this driver launched with the mod, and nowhere
#: else: ``ship.py handoff`` arms the own-clear marker only where it is set,
#: so the line it prints is true of the window it runs in.
OWN_CLEAR_KEY = "ESPALIER_OWN_CLEAR"
#: The checkout the mod reads the marker in (a test's or a drive's), and the
#: file it appends one JSON line per event to -- set for a session only by
#: ``launch --own-clear-log`` (bare: :data:`OWN_CLEAR_LOG_DEFAULT` under the
#: seat's checkout), after the deferred clear of 2026-10-30 had to be read
#: from the transcript's queue rows for want of the mod's own record.
OWN_CLEAR_ROOT_KEY = "ESPALIER_OWN_CLEAR_ROOT"
OWN_CLEAR_LOG_KEY = "ESPALIER_OWN_CLEAR_LOG"
OWN_CLEAR_LOG_DEFAULT = ".espalier-state/own_clear.log"
#: The own-clear's names, never inherited by a launched session: the flag
#: above, and the root and log a drive or a test aims the mod with.
OWN_CLEAR_ENV = frozenset({OWN_CLEAR_KEY, OWN_CLEAR_ROOT_KEY, OWN_CLEAR_LOG_KEY})


def mod_args(mod_dir: Path = MOD_DIR) -> list[str]:
    """``--plugin-dir <dir>`` when the own-clear mod's manifest is at
    ``mod_dir``, else nothing: claude refuses a plugin directory with no
    manifest, so a half-deployed one is left out rather than passed."""
    return ["--plugin-dir", str(mod_dir)] if (mod_dir / ".claude-plugin" / "plugin.json").is_file() else []


@dataclass
class Brief:
    """A seat's first message: its role, the whole text, and the loop line."""
    role: str
    text: str
    loop: str


def compose_brief(root: Path, seat: str, checkout: Path | None = None) -> Brief:
    """The first message for ``seat``: the dispatcher form when
    ``espalier.toml`` names this seat as the dispatcher, else the worker form
    under the dispatcher it names (or under the operator where none is named).
    ``checkout`` is the seat's own checkout when it exists (its
    ``espalier.toml`` names the dispatcher, as its banner's reads do, and
    what it holds picks the protocol's home and the phrases), else the clone.
    Refused where the dispatcher setting is there but unusable: the brief
    would name a dispatcher no seat is."""
    where = checkout if checkout is not None and checkout.is_dir() else root
    dispatcher, how = mail.dispatcher_setting(where)
    if dispatcher == mail.DISPATCHER_UNUSABLE:
        raise Refused(f"the brief names the dispatcher, and {how}")
    home = next(((rel, words) for rel, words in PROTOCOL_HOMES if (where / rel).is_file()), ("", PROTOCOL_FALLBACK))
    protocol, self_host = home[1], home[0] == PROTOCOL_HOMES[0][0]
    base = sync.default_branch(sync._Git(root, None)) or "main"
    if dispatcher is not None and dispatcher == seat:
        goal = f" and {GOAL_NOTES}'s notes" if (where / GOAL_NOTES).is_file() else ""
        red = (SELF_HOST_RED if self_host else ADOPTER_RED).format(base=base)
        assign = SELF_HOST_ASSIGN.format(kinds=dispatch_kinds_phrase()) if self_host else ADOPTER_ASSIGN
        figures = SELF_HOST_FIGURES if self_host else ""
        text = DISPATCHER_BRIEF.format(seat=seat, protocol=protocol, goal=goal, assign=assign, red=red,
                                       figures=figures, gridlock=SELF_HOST_GRIDLOCK if self_host else "",
                                       every=TICK_MINUTES,
                                       row_source=SELF_HOST_ROW_SOURCE if self_host else "")
        return Brief("dispatcher", text + "\n" + DISPATCHER_TICK, DISPATCHER_TICK)
    has_tier_script = (where / TIER_SCRIPT).is_file()
    tier = (f"the tier the diff earns with --base origin/{base}" if has_tier_script
            else "the proof the change earns per /implement-task step 7")
    phrase = f"the dispatcher {dispatcher}" if dispatcher else "the operator (espalier.toml names no dispatcher)"
    # The fork rule by tree (SELF_HOST_PROCEED / ADOPTER_PROCEED), rendered first
    # so its own fields are filled before the tick takes it whole; the kinds
    # render from DISPATCH_KINDS (the adopter form has no such field and
    # ignores the keyword).
    proceed = (SELF_HOST_PROCEED if self_host else ADOPTER_PROCEED).format(
        dispatcher=dispatcher or "the operator", wait=TICK_MINUTES, kinds=dispatch_kinds_phrase())
    loop = WORKER_TICK.format(dispatcher=dispatcher or "the operator", tier=tier, proceed=proceed,
                              review=(SELF_HOST_REVIEW.format(base=base) if self_host and has_tier_script
                                      else ADOPTER_REVIEW))
    first = WORKER_BRIEF.format(seat=seat, dispatcher_phrase=phrase, protocol=protocol,
                                handoff_ship=SELF_HOST_HANDOFF_SHIP if self_host else "")
    return Brief("worker", first + "\n" + loop, loop)


#: What a window the own-clear re-primes is told in place of its loop line: a
#: seat's interval loop survives a /clear (DEF-4052, measured 2026-10-15), so a
#: brief that still ended with the loop line would start a second loop beside
#: the first. The loop's interval is named so the seat can tell its tick.
REPRIME_NOTE = (
    "This window was cleared by the own-clear after your handoff and re-primed with this message. The loop "
    "line is left out on purpose: if {what} (every {every}) was started in this window it survived the clear "
    "and is still running, so start no second one; where none was started, this window is the operator's own "
    "and starts none now. Read live state before you state it: the board, the mail and this message are "
    "snapshots."
)


def reprime_text(brief: Brief) -> str:
    """The first message for a window the own-clear mod re-primes after the
    handoff (``tools/cc/mods/own-clear``, read from the marker ``ship.py
    handoff`` arms): ``brief`` with its loop line replaced by
    :data:`REPRIME_NOTE`, since the loop survives the clear and a second would
    tick beside it. A brief whose text does not end with its loop line keeps
    the text whole and gains the note."""
    text = brief.text
    tail = "\n" + brief.loop
    if text.endswith(tail):
        text = text[: -len(tail)]
    words = brief.loop.split(" ", 2)
    every = words[1] if brief.loop.startswith("/loop ") and len(words) > 1 else "its interval"
    what = "the board loop" if brief.role == "dispatcher" else "the worker loop"
    return text + "\n" + REPRIME_NOTE.format(what=what, every=every)


def brief_line(role: str, seat: str, python: str = "") -> str:
    """The short form of the same brief, for the SessionStart banner's
    ``Orders:`` line: the two reads to start with, the loop it ends with and
    its interval, and the command that prints the whole message (``python``
    is the interpreter spelling the caller resolved; '' leaves the command
    out). Read from the templates alone, with no git, so a hook can afford it."""
    loop = DISPATCHER_TICK if role == "dispatcher" else WORKER_TICK
    every = loop.split(" ", 2)[1]
    what = "the board loop" if role == "dispatcher" else "the worker loop"
    tail = f"; {python} tools/cc/seat.py brief {seat} prints the first message" if python else ""
    return f"run /inbox, then /inbox board, then start {what} (/loop {every}){tail}"


def cmd_brief(root: Path, seat: str) -> int:
    target = resolve(root, seat)
    print(compose_brief(root, seat, target.path if target.exists else None).text)
    return 0


def brief_refusal(args: list[str], claude: str | None, root: Path, checkout: Path | None) -> str:
    """Why the first message cannot ride with these arguments ('' when it
    can), checked before anything is created. Beside a flag that makes the
    session a one-shot, a resumed or continued one, or one brought over
    (:data:`SESSION_MODE_FLAGS`), or a prompt of the operator's own (a second
    ``--``, or a bare first argument, which no flag can be taking: a bare word
    later may be a list flag's value, ``--add-dir a b``, so it is not read as
    one), claude would get two prompts or none; through a ``.cmd``/``.bat``
    shim (an npm install on Windows) cmd.exe
    cuts an argument at its line break, so the loop line would never arrive;
    an unusable dispatcher setting names no dispatcher."""
    hint = "; --no-brief launches without the first message (`seat.py brief` prints it to paste)"
    flags = sorted({a.split("=", 1)[0] for a in args} & SESSION_MODE_FLAGS)
    if flags:
        return f"{', '.join(flags)} does not start a fresh session, so the first message has nowhere to go{hint}"
    bare = args[:1] if args and not args[0].startswith("-") else []
    if "--" in args or bare:
        return f"the arguments carry a prompt of their own ({(bare or ['--'])[0]!r}), beside the first message{hint}"
    if claude is not None and Path(claude).suffix.lower() in (".cmd", ".bat"):
        return (f"claude resolves to {claude}, a script cmd.exe runs, which cuts an argument at its line break, "
                f"so the first message's loop line would be lost{hint}, or install the native claude")
    where = checkout if checkout is not None and checkout.is_dir() else root
    if mail.dispatcher_setting(where)[0] == mail.DISPATCHER_UNUSABLE:
        return f"the brief names the dispatcher, and {mail.dispatcher_setting(where)[1]}{hint}"
    return ""


def cmd_launch(root: Path, seat: str, args: list[str], *, maintenance: bool, unchecked: bool,
               print_only: bool, shell: str | None = None, brief: bool = True, mod: bool = True,
               own_clear_log: str | None = None) -> int:
    """``own_clear_log``: None, no log; ``""`` (the switch given bare),
    :data:`OWN_CLEAR_LOG_DEFAULT` under the seat's checkout; else the path
    given. Set for the session only when the mod rides (``mod``), since the
    mod is what writes it."""
    target = resolve(root, seat)
    # A path given is resolved where the operator typed it (the session's own
    # directory is the seat's checkout, where a relative file would land as an
    # untracked one); bare, the seat's own state file.
    log = None if own_clear_log is None else (
        os.path.abspath(os.path.expanduser(own_clear_log)) if own_clear_log
        else str(target.path / OWN_CLEAR_LOG_DEFAULT))
    claude = None
    if not print_only:
        why = session_refusal()
        if why:
            raise Refused(why)
    claude = shutil.which("claude", path=child_env(target, maintenance=maintenance).get("PATH"))
    if claude is None and not print_only:
        raise Refused("claude is not on PATH; --print gives the line to run where it is")
    if brief:
        why = brief_refusal(args, claude, root, target.path if target.exists else None)
        if why:
            raise Refused(why)
    if target.exists:
        _refuse_occupied(seat, target.path, unchecked=unchecked, verb="launch")
    elif print_only:
        say(f"seat {seat} has no worktree yet: `seat.py launch {seat}`, from a terminal, creates .claude/worktrees/"
            f"{target.path.name} from origin before it starts the session")
        return 1
    else:
        create(root, target)
    if not target.is_clone:
        copied, skipped = copy_includes(root, target.path)
        if copied:
            say(f"copied {', '.join(copied)} from the clone (.worktreeinclude)")
        if skipped:
            say(f"skipped .worktreeinclude entries: {'; '.join(skipped)}")
        if _settings_missing(root, target.path):
            raise Refused(f"{target.path} has no {SETTINGS_REL}, so a session there would load no hook: copy the "
                          f"clone's into it, then launch again")
        name, said = mail.name_this_worktree(target.path)
        if said:
            say(said)
        if name is None:
            own, state, why = _own_name(target.path)
            if state == "unread":
                raise Refused(f"{target.path}'s own seat name could not be read ({why}), so whether it answers "
                              f"{seat!r} cannot be told: nothing is launched; {mail.RETRY_HINT}")
            if own != seat:
                raise Refused(f"{target.path} does not answer {seat!r} and could not be named: "
                              f"{said or 'no reason given'}")
    if venv_bindir(target.path) is None and (target.path / "espalier" / "__init__.py").is_file():
        say(f"note: {target.path} has no .venv, so a test run there imports espalier from wherever `python` "
            "finds it (the banner's Engine: line); a .venv of its own with an editable install fixes it")
    # The own-clear mod first, before the operator's own arguments and the
    # brief's `--`, so neither can take its directory as a value: the seat's
    # own copy (a lane there that edits the mod runs its edit), else the
    # launcher's.
    own_copy = target.path / "tools" / "cc" / "mods" / "own-clear"
    loaded = (mod_args(own_copy) or mod_args()) if mod else []
    argv = loaded + list(args)
    if brief:
        # The first message rides as claude's prompt after a `--`, so no option
        # the operator passed can take it as a value: driven on 2.1.301,
        # `--add-dir <dir> <prompt>` read the prompt as a second directory and
        # started with none, while `--add-dir <dir> -- <prompt>` answered it.
        try:
            argv += ["--", compose_brief(root, seat, target.path).text]
        except Refused as exc:
            raise Refused(f"{exc}; --no-brief launches without the first message") from None
    no_log = "; --own-clear-log names nothing without it" if log else ""
    if loaded:
        say(f"own-clear mod loaded from {MOD_DIR}: the window clears itself once the handoff lands"
            + (f"; its log: {log}" if log else ""))
    elif mod:
        say(f"no own-clear mod: nothing at {MOD_DIR}; the window will not clear itself after the handoff{no_log}")
    else:
        say(f"no own-clear mod (--no-mod): the window will not clear itself after the handoff{no_log}")
    if print_only:
        say(command_line(target, argv, maintenance=maintenance, shell=shell, own_clear=bool(loaded),
                         own_clear_log=log))
        return 0
    env = child_env(target, maintenance=maintenance, own_clear=bool(loaded), own_clear_log=log)
    say(f"launching seat {seat} in {target.path}" + (" (maintenance mode)" if maintenance else "")
        + ("" if brief else ", no first message"))
    sys.stdout.flush()
    assert claude is not None
    return run_session([claude, *argv], cwd=target.path, env=env)


def run_session(argv: list[str], *, cwd: Path, env: dict[str, str]) -> int:
    """The operator's own session: interactive, stdio inherited, no timeout
    (it ends when they end it); the one spawn here not bounded through
    checkout_sync. Tests replace this function, never ``subprocess``."""
    # subprocess-contract: ok the operator's own interactive claude session: argv is the resolved claude plus the operator's arguments passed through unchanged, stdio inherited, no capture and no timeout by design; tests/test_seat.py pins the argv through command_line and replaces this function
    return subprocess.call(argv, cwd=str(cwd), env=env)


# -- retire --------------------------------------------------------------------------

def by_hand_release(root: Path, clone: str, seat: str, claim_ids: list[str]) -> str:
    """The recipe for a seat whose worktree is gone: name a fresh worktree
    after it and release its claims by their ids, never by lane, since a lane
    release from the seat reads as its lane shipped and closes a job it was
    given (``mail.live_assignments``); its jobs stay for the retire to hand
    back."""
    folder = seat[len(clone) + 1:] if seat.startswith(clone + "-") else "<folder>"
    base = sync.default_branch(sync._Git(root, None)) or "main"
    return (f"its worktree is gone, and only the name {seat} can release them: "
            f"git worktree add --detach .claude/worktrees/{folder} {sync.REMOTE}/{base}, then "
            f"git -C .claude/worktrees/{folder} config --worktree {mail.MACHINE_KEY} {seat}, then in it "
            + ", ".join(f"python tools/cc/mail.py send --type release --ack {cid}" for cid in claim_ids or ["<claim id>"])
            + f", then python tools/cc/seat.py retire {seat}")


def _send_releases(path: Path, seat: str, ids: list[str], text: str) -> None:
    """One release per id, from inside ``path`` under its own name: by id,
    never by lane, since a lane release from a seat also closes a job the
    dispatcher gave it on that lane. Each sent line is said as it goes, so a
    failure part way leaves an exact account."""
    named, how = mail.machine_setting(path)
    unread = getattr(mail, "MACHINE_UNREAD", None)  # a kept mail.py from before the phrase has none
    if named is None and unread and str(how).startswith(unread):
        # A read that failed is not another name: renaming the seat would not help.
        raise Refused(f"{path}'s machine name could not be read ({how}), so the releases stop here (what was "
                      "sent stays sent); run retire again once git answers (a config git cannot parse never "
                      "will: fix it first)")
    if named != seat:
        raise Refused(f"{path} does not answer the name {seat}, so a release sent from it would not close "
                      f"{seat}'s messages")
    for n, mid in enumerate(ids):
        try:
            mail.send(path, mail.new_message(seat, "release", text, ack=mid), say=say)
        except mail.Unresolvable as exc:
            raise Refused(f"the release stopped after {n} of {len(ids)} ({exc}); the worktree is kept: run "
                          "retire again (what was sent stays sent)") from None


def cmd_retire(root: Path, seat: str, *, dry_run: bool, fetch: bool, return_jobs: bool = False,
               unchecked: bool = False) -> int:
    named_clone, clone_how = mail.clone_machine(root)
    if named_clone is None and clone_how.startswith(mail.MACHINE_UNREAD):
        raise Refused(f"{clone_how}, so {seat!r} cannot be told from the clone itself: nothing is released or "
                      f"removed; {mail.RETRY_HINT}")
    clone = named_clone or ""
    if seat == clone:
        raise Refused(f"{seat} is the clone itself: its checkout is the repository, never retired")
    claims, jobs, note = _read_channel(root, fetch=fetch)
    if note.startswith(CHANNEL_UNREAD):
        raise Refused(f"{note}, so the seat's claims cannot be read: nothing is released or removed")
    if note:
        say(f"({note})")
    mine = [c for c in claims if c.get("from") == seat]
    held = [j for j in jobs if (j.get("re") or {}).get(mail.ASSIGN_SEAT_KEY) == seat]
    claim_ids = [str(c.get("id")) for c in mine]
    try:
        target = resolve(root, seat)
    except Refused:
        if mine:
            raise Refused(f"seat {seat} holds {len(mine)} live claim(s) and "
                          f"{by_hand_release(root, clone, seat, claim_ids)}") from None
        raise
    if not target.exists:
        if mine:
            raise Refused(f"seat {seat} holds {len(mine)} live claim(s) and "
                          f"{by_hand_release(root, clone, seat, claim_ids)}")
        raise Refused(f"seat {seat} has no worktree and nothing on the channel: nothing to retire")
    _refuse_occupied(seat, target.path, unchecked=unchecked, verb="retire")
    if held and not return_jobs:
        raise Refused(f"seat {seat} holds {len(held)} job(s) from the dispatcher ({_lanes(held)}): retired, nobody "
                      "would work them. Ask the dispatcher to release or reassign them, or --return-jobs releases "
                      "them with this retire (the release says why)")
    git = sync._Git(root, None)
    base = sync.default_branch(git) or "main"
    if fetch:
        fetched = git.ask("-c", "credential.interactive=never", "fetch", "--quiet", "--no-tags", sync.REMOTE, base,
                          cap=FETCH_CAP_S)
        if fetched is None or fetched.returncode != 0:
            say(f"(origin could not be fetched: {sync.REMOTE}/{base} as last fetched)")
    rows, marker_live = reap_inputs(root, sync.live_sessions())
    verdict = sync.reap_worktrees(root, sessions=rows, own_cwd=Path.cwd(), marker_live=marker_live,
                                  only=target.path, dry_run=True)
    if not verdict.would_remove:
        reason = verdict.note or (verdict.kept[0][1] if verdict.kept else "the removal was not reached")
        if not reason.startswith(f"its seat {seat} holds "):
            raise Refused(f"{target.path} would be kept ({reason}), so nothing was released: settle that, then "
                          "retire again")
    if dry_run:
        say(f"dry-run: would release {len(mine)} claim(s) of {seat} ({_lanes(mine)}) from {target.path}, "
            + (f"return {len(held)} job(s) ({_lanes(held)}), " if held else "") + f"then remove {target.path}")
        return 0
    busy = sync.held_open(target.path)
    if busy:
        raise Refused(f"{target.path} is kept: {busy}; nothing was released")
    _send_releases(target.path, seat, [str(c.get("id")) for c in mine], "Seat retired; claims closed.")
    if held:
        _send_releases(target.path, seat, [str(j.get("id")) for j in held],
                       f"Seat {seat} retired; this job goes back to the dispatcher.")
    if mine or held:
        mail.fetch_mail(root, timeout=FETCH_CAP_S)
        left_claims, left_jobs, _note = _read_channel(root, fetch=False)
        left = [c for c in left_claims if c.get("from") == seat]
        left += [j for j in left_jobs if (j.get("re") or {}).get(mail.ASSIGN_SEAT_KEY) == seat]
        if left:
            raise Refused(f"{len(left)} message(s) of {seat} are still live after the release ({_lanes(left)}); "
                          "the worktree is kept")
    rows, marker_live = reap_inputs(root, sync.live_sessions())
    report = sync.reap_worktrees(root, sessions=rows, own_cwd=Path.cwd(), marker_live=marker_live,
                                 only=target.path)
    for name in report.unlocked:
        say(f"unlocked {name}: the lock's holder has exited")
    if report.removed:
        saved = f"; its session notes saved under cc/blueprints/ ({len(report.saved)} file(s))" if report.saved else ""
        say(f"retired {seat}: removed {target.path}{saved}")
        return 0
    reason = report.kept[0][1] if report.kept else (report.note or "the removal was not reached")
    raise Refused(f"{target.path} is kept: {reason} (its claims were released)")


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
    p.add_argument("--unchecked", action="store_true",
                   help="launch when the occupancy cannot be told, or only a session marker names a session")
    p.add_argument("--print", dest="print_only", action="store_true", help="print the command line instead")
    p.add_argument("--shell", choices=("powershell", "posix"), help="the shell --print writes for")
    p.add_argument("--no-brief", dest="brief", action="store_false",
                   help="start the session without the composed first message (`brief` prints it)")
    p.add_argument("--no-mod", dest="mod", action="store_false",
                   help="start the session without the own-clear mod (mods/own-clear beside this driver)")
    p.add_argument("--own-clear-log", nargs="?", const="", metavar="PATH",
                   help=f"set {OWN_CLEAR_LOG_KEY} for the session, the file the own-clear mod appends one JSON "
                        f"line per event to (bare: {OWN_CLEAR_LOG_DEFAULT} under the seat's checkout)")
    p = sub.add_parser("brief", help="print a seat's first message: its role, the reads to start with, its loop")
    p.add_argument("seat")
    p = sub.add_parser("retire", help="release a worktree seat's claims, then remove its worktree")
    p.add_argument("seat")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--return-jobs", action="store_true", help="release the seat's jobs back to the dispatcher too")
    p.add_argument("--unchecked", action="store_true", help="pass a session only a session marker names")
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
                              print_only=args.print_only, shell=args.shell, brief=args.brief, mod=args.mod,
                              own_clear_log=args.own_clear_log)
        if args.verb == "brief":
            return cmd_brief(root, args.seat)
        return cmd_retire(root, args.seat, dry_run=args.dry_run, fetch=not args.no_fetch,
                          return_jobs=args.return_jobs, unchecked=args.unchecked)
    except (Refused, mail.Unresolvable) as exc:
        print(f"seat.py: {sync._ascii(str(exc))}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    from _json_safe import pin_utf8_streams

    pin_utf8_streams()
    sys.exit(main())
