"""The records two lanes both append to, read as one: the Session Log and
the changelog's ``[Unreleased]`` entries, each written as one file per change
and read beside the legacy section still in the big file.

Two lanes that each prepend a row to one table conflict at the merge; two
lanes that each add a file never do (measured 2026-10-10: 12 of 27 replayed
catch-ups conflicted on ESPALIER_MEMORY.md, 3 on CHANGELOG.md). So the writers
add a file, and every reader asks this module for the record instead of
applying a regex to one file -- a reader that still reads the file alone does
not red when an entry moves, it reads less and passes, which is why the
census in tests/test_record_fragments.py holds every reader to this module.

Expand, then contract. Readers take both forms now: the fragments and the
legacy rows, which stay where they are and are read as before. The legacy
Session Log table is frozen (no writer adds to it and the fragment prune never
touches it) until a later fold moves its rows into fragments.

Readers: the SessionStart digest (hooks/session_start.py), the write-time cap
(hooks/post_write_check.py), the handoff driver and landing check
(scripts/), the tag-parity gate, and the engine's changelog reader, which loads
the vendored copy of this file by path. Stdlib-only, zero espalier imports;
text is 7-bit ASCII.
"""
from __future__ import annotations

import argparse
import codecs
import datetime as _dt
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: The fragment directories, repo-relative with forward slashes, no trailing
#: slash. ``FRAGMENT_DIRS`` spells them with one, the form the record-file
#: lists use for a directory entry.
SESSION_LOG_DIR = "memory/session-log.d"
CHANGELOG_DIR = "changelog.d"
FRAGMENT_DIRS: tuple[str, ...] = (SESSION_LOG_DIR + "/", CHANGELOG_DIR + "/")

MEMORY_FILE = "ESPALIER_MEMORY.md"
CHANGELOG_FILE = "CHANGELOG.md"
#: Where pruned rows go: the same archive ``espalier memory prune`` appends
#: to (gitignored on the self-host tree), so evicted history has one home.
ARCHIVE = "docs/session-archive.md"

#: How many Session Log fragments the prune keeps. The legacy table held 28
#: rows when fragments began (2026-10-10); the legacy rows are frozen and do
#: not count toward this until the fold.
SESSION_LOG_CAP = 30

#: A Session Log row: ``| YYYY-MM-DD ...``. The same pattern as the other
#: consumers (tests/test_forced_copy_parity.py::TestMemoryDateRegexParity).
_MEMORY_DATE_RE = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})")

#: ``<YYYY-MM-DD>-<HHMMSS>-<seat>.md``, the writer's local clock (the row's own
#: date is the operator's local day): within one box name order is time order,
#: and the seat keeps two machines writing in one second apart. Across boxes in
#: different zones a same-day tie can order by hours wrong; the date, which
#: decides recency, does not.
SESSION_LOG_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(\d{6})-([a-z0-9][a-z0-9-]*)\.md$")
#: ``<YYYY-MM-DD>-<lane slug>.md``: one file per lane, edited in place by it.
CHANGELOG_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z0-9][a-z0-9._-]*)\.md$")

#: The ``[Unreleased]`` body, up to the next level-two heading. The same
#: pattern ``espalier/changelog.py::UNRELEASED_BODY_RE`` owns for the engine.
_UNRELEASED_BODY_RE = re.compile(
    r"##\s*\[Unreleased\](?P<body>.*?)(?=^##(?!#)|\Z)",
    re.DOTALL | re.MULTILINE,
)


def decode(raw: bytes) -> str:
    """Bytes as text with ``\\n`` line ends: a UTF-8 or UTF-16 byte-order mark
    is honoured, anything else reads as UTF-8 with bad bytes replaced. A
    record is read to be shown, so a stray byte costs a character, never the
    record. Line ends are folded because a checkout's ``core.autocrlf`` decides
    them per file: on a Windows box a fragment merged in from another lane is
    written CRLF beside this lane's own LF one (driven by the two-lane test)."""
    if raw.startswith(codecs.BOM_UTF8):
        text = raw[len(codecs.BOM_UTF8):].decode("utf-8", errors="replace")
    elif raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text = raw.decode("utf-16", errors="replace")
    else:
        text = raw.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n")


def _read(path: Path) -> str:
    try:
        return decode(path.read_bytes())
    except OSError:  # fail-open: ok telemetry -- a file that cannot be read (a lock, a permission) is no rows this read; the next read retries, and a reader that must not miss one checks the file itself
        return ""


def in_fragment_dir(rel: str) -> bool:
    """Whether a repo-relative path (either slash) is a file under a fragment
    directory, whatever its name (a reader takes only the names
    ``SESSION_LOG_NAME_RE`` and ``CHANGELOG_NAME_RE`` match)."""
    rel = rel.replace("\\", "/")
    return any(rel.startswith(d) and len(rel) > len(d) for d in FRAGMENT_DIRS)


# ---------------------------------------------------------------- Session Log


@dataclass(frozen=True)
class Row:
    """One Session Log row: its date, its whole line, and where it lives
    (a fragment's repo-relative path, or ``ESPALIER_MEMORY.md``)."""

    date: str
    line: str
    source: str


def session_log_fragments(root: Path) -> tuple[list[Path], list[str]]:
    """The Session Log fragment files oldest first by name, and the names
    under the directory that are not fragments (a ``README.md``, a typo'd
    name), so a reader can say it skipped them."""
    base = root / SESSION_LOG_DIR
    if not base.is_dir():
        return [], []
    good: list[Path] = []
    skipped: list[str] = []
    for p in sorted(base.iterdir()):
        if not p.is_file():
            continue
        if SESSION_LOG_NAME_RE.match(p.name):
            good.append(p)
        else:
            skipped.append(p.name)
    return good, skipped


def legacy_rows(text: str) -> list[str]:
    """The dated rows of the ``## Session Log`` section, in file order, or of
    the whole text when there is no such heading. Scoped to the section so a
    dated row in another table (the adopter template's decisions table puts a
    date in a column) cannot pass for a session."""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.strip() == "## Session Log"]
    if starts:
        section: list[str] = []
        for ln in lines[starts[0] + 1:]:
            if ln.startswith("## "):
                break
            section.append(ln)
        lines = section
    return [ln for ln in lines if _MEMORY_DATE_RE.match(ln)]


def session_log_rows(root: Path, memory_text: str | None = None) -> list[Row]:
    """Every Session Log row, newest first: the fragments' and the legacy
    table's.

    Newest is the date each row CARRIES (the digest's rule), with a stable sort
    so ties keep the order built here: fragments first, newest name first
    (name order is time order), then the legacy rows in file order (``/handoff``
    prepended, so the topmost same-day row is the newest). A fragment row and a
    legacy row on one date put the fragment first; a lane opened before the
    switch can still land a legacy row dated after a fragment, and the date
    sort places it.

    ``memory_text`` is the caller's own decode of the memory file, when it has
    one, so each reader keeps its own policy for a file it already refuses
    politely; without it the file is read here.
    """
    fragments, _skipped = session_log_fragments(root)
    if memory_text is None:
        memory_text = _read(root / MEMORY_FILE)
    return rows_from_texts([(p.name, _read(p)) for p in fragments], memory_text)


def rows_from_texts(fragments: list[tuple[str, str]], memory_text: str) -> list[Row]:
    """``session_log_rows`` over texts already in hand: ``(name, text)`` for
    each file under the fragment directory, in any order, and the memory
    file's text. For a reader of another commit (``git show <sha>:<path>``),
    which has no tree on disk. A name that is not a fragment name is not read."""
    rows: list[Row] = []
    named = sorted((name, text) for name, text in fragments if SESSION_LOG_NAME_RE.match(name))
    for name, text in reversed(named):
        rel = f"{SESSION_LOG_DIR}/{name}"
        for ln in text.replace("\r\n", "\n").splitlines():
            m = _MEMORY_DATE_RE.match(ln)
            if m:
                rows.append(Row(m.group(1), ln, rel))
    for ln in legacy_rows(memory_text):
        m = _MEMORY_DATE_RE.match(ln)
        if m:
            rows.append(Row(m.group(1), ln, MEMORY_FILE))
    return sorted(rows, key=lambda row: row.date, reverse=True)


def _seat(root: Path) -> str:
    """This seat's name for a fragment: ``git config espalier.machine`` (a
    linked worktree's own name where it has one), lower-cased to the name
    pattern, else ``local``."""
    try:
        result = subprocess.run(  # spawn: ok a name lookup: a git that cannot answer names the fragment local
            ["git", "config", "--get", "espalier.machine"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5, cwd=str(root),
        )
        name = result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):  # fail-open: ok text-fallback -- no git answer names the fragment local
        name = ""
    name = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return name or "local"


def session_log_name(now: _dt.datetime, seat: str) -> str:
    """The fragment name for a row written at ``now`` by ``seat``, from
    ``now``'s own wall clock, never converted. The writer passes the LOCAL
    time, because the row inside is dated by the operator's local day and the
    handoff driver refuses a name and row that disagree: a UTC name on a box
    four hours behind it named an evening handoff for tomorrow (code review,
    2026-10-10)."""
    return f"{now:%Y-%m-%d}-{now:%H%M%S}-{seat}.md"


def new_session_log_path(root: Path, seat: str | None = None,
                         now: _dt.datetime | None = None) -> Path:
    """Where the next Session Log row goes; the directory is made, the file
    is not. The name is this box's local clock and the seat's, never typed;
    the row is dated with the date the name starts with."""
    now = now or _dt.datetime.now().astimezone()
    base = root / SESSION_LOG_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base / session_log_name(now, seat or _seat(root))


def this_sessions_row(root: Path, seat: str, now: _dt.datetime | None = None) -> Path | None:
    """This seat's uncommitted Session Log fragment dated today, if one is
    there: the row a handoff step already started (the reflect skill writes a
    promoted note's back-link into it), so the next ``new session-log``
    names the same file rather than a second one the handoff then refuses
    (review of the Wave C batch). The newest by name when several are; None
    when git cannot list the untracked files."""
    today = (now or _dt.datetime.now().astimezone()).date().isoformat()
    out = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", SESSION_LOG_DIR + "/"],
                         cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        return None
    mine = []
    for rel in out.stdout.splitlines():
        name = rel.strip().rsplit("/", 1)[-1]
        m = SESSION_LOG_NAME_RE.match(name)
        if m and m.group(1) == today and m.group(3) == seat:
            mine.append(name)
    return root / SESSION_LOG_DIR / max(mine) if mine else None


def prune_session_log(root: Path, keep: int = SESSION_LOG_CAP, archive: str = ARCHIVE,
                      today: str | None = None, dry_run: bool = False) -> list[Row]:
    """Delete the oldest Session Log fragments beyond ``keep``, after
    appending their rows to the archive; return the rows that left.

    Oldest is name order, which is time order. The legacy table is never
    touched (frozen until the fold). The archive is written first, so an
    interrupt between the two duplicates a row rather than losing one. Two
    lanes that each delete the same oldest fragment merge cleanly: a file
    deleted on both sides is no conflict.
    """
    fragments, _skipped = session_log_fragments(root)
    excess = len(fragments) - max(0, keep)
    if excess <= 0:
        return []
    leaving = fragments[:excess]
    rows = [
        Row(m.group(1), ln, f"{SESSION_LOG_DIR}/{p.name}")
        for p in leaving
        for ln in _read(p).splitlines()
        if (m := _MEMORY_DATE_RE.match(ln))
    ]
    if dry_run:
        return rows
    archive_path = root / archive
    stamp = today or _dt.date.today().isoformat()
    chunk = (
        "\n"
        f"## Pruned {stamp} (via _record_fragments prune)\n\n"
        "| Date | What Happened | Notes |\n"
        "|------|--------------|-------|\n"
        + "".join(row.line + "\n" for row in rows)
    )
    # An append, not a rewrite: the archive is a local, gitignored log that
    # only ever grows, so a fifth copy of the atomic-replace helper (with its
    # own file mode to get right) would buy nothing here (code review of the
    # writers roster, 2026-10-10). An interrupted append leaves a partial
    # chunk, and the fragments are deleted only after it returns.
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    lead = ""
    if archive_path.is_file() and archive_path.stat().st_size:
        with open(archive_path, "rb") as fh:
            fh.seek(-1, os.SEEK_END)
            lead = "" if fh.read(1) == b"\n" else "\n"
    with open(archive_path, "ab") as fh:
        fh.write((lead + chunk).encode("utf-8"))
    for p in leaving:
        p.unlink()
    return rows


# ---------------------------------------------------------------- changelog


#: The team setting that turns a lane's changelog file on. The loader is
#: deployed on every tree and a ``changelog.d/`` directory alone may be another
#: tool's (scriv, towncrier), so the writer names a fragment only where
#: ``espalier.toml`` says so (review of #179). Read as ship.py reads
#: ``handoff_push``, by a line scan: the 3.10 floor has no tomllib.
CHANGELOG_FRAGMENTS_KEY = "changelog_fragments"
_TOML_TABLE_HEADER_RE = re.compile(r"""^[ \t]*\[\[?[ \t]*[A-Za-z0-9_."'-][A-Za-z0-9_."' -]*\]\]?[ \t]*(#.*)?$""")


def changelog_fragments_setting(root: Path) -> tuple[bool, str]:
    """``(on, how it was read)`` for ``changelog_fragments`` at the top level
    of ``<root>/espalier.toml``. Only the bare word ``true`` turns it on; any
    other reading is off, with the reason named, the contract of
    ``ship.handoff_push_setting`` (a test pins the two agreeing)."""
    key_name = CHANGELOG_FRAGMENTS_KEY
    try:
        text = decode((root / "espalier.toml").read_bytes())
    except FileNotFoundError:
        return False, f"there is no espalier.toml, so {key_name} is off (the default)"
    except OSError as exc:
        return False, f"espalier.toml could not be read ({exc.strerror or type(exc).__name__}), so {key_name} reads as off"
    table = ""
    for line in text.splitlines():
        if _TOML_TABLE_HEADER_RE.match(line):
            table = line.split("#", 1)[0].strip()
            continue
        key, sep, value = line.split("#", 1)[0].partition("=")
        key = key.strip()
        if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
            key = key[1:-1]
        if not sep or key != key_name:
            continue
        if table:
            return False, f"espalier.toml sets {key_name} under {table}, where it is not the top-level setting, so it is off"
        value = value.strip()
        if value in ("true", "false"):
            return value == "true", f"espalier.toml sets {key_name} = {value}"
        return False, f"espalier.toml sets {key_name} = {value}, which is neither true nor false, so it reads as off"
    return False, f"espalier.toml does not set {key_name}, so it is off (the default)"


def changelog_fragments(root: Path) -> tuple[list[Path], list[str]]:
    """The changelog fragment files by name, and the names under the
    directory that are not fragments."""
    base = root / CHANGELOG_DIR
    if not base.is_dir():
        return [], []
    good: list[Path] = []
    skipped: list[str] = []
    for p in sorted(base.iterdir()):
        if not p.is_file():
            continue
        if CHANGELOG_NAME_RE.match(p.name):
            good.append(p)
        else:
            skipped.append(p.name)
    return good, skipped


def unreleased_body(changelog_text: str) -> str:
    """The ``[Unreleased]`` section's body in ``changelog_text``, or ``''``."""
    m = _UNRELEASED_BODY_RE.search(changelog_text)
    return m.group("body") if m else ""


def unreleased_text(root: Path, changelog_text: str | None = None) -> str:
    """Every unreleased entry: ``[Unreleased]``'s body in the file, then each
    fragment by name, each starting on its own line. What a gate over the
    live entries reads; a gate that reads the file alone sees less.

    A ``*.md`` file under the directory whose name is not a fragment name is
    read too, after the named ones: an entry in a misnamed file is still
    unreleased, and dropping it would hide it from the release gate and the
    provenance guard (code review, 2026-10-10).

    The directory is read only where ``espalier.toml`` opts in
    (``changelog_fragments = true``), the same setting the writer needs: a
    ``changelog.d/`` alone may be another changelog tool's, whose entries are
    not this changelog's (review of the Wave C batch)."""
    if changelog_text is None:
        changelog_text = _read(root / CHANGELOG_FILE)
    parts = [unreleased_body(changelog_text)]
    if not changelog_fragments_setting(root)[0]:
        return parts[0]
    fragments, skipped = changelog_fragments(root)
    base = root / CHANGELOG_DIR
    for p in [*fragments, *(base / name for name in skipped if name.endswith(".md"))]:
        text = _read(p)
        parts.append(text if text.endswith("\n") else text + "\n")
    joined = parts[0]
    for part in parts[1:]:
        if joined and not joined.endswith("\n"):
            joined += "\n"
        joined += "\n" + part
    return joined


def lane_slug(branch: str) -> str:
    """A branch name as a fragment slug: ``lane/`` dropped, every run of
    other characters one hyphen."""
    if branch.startswith("lane/"):
        branch = branch[len("lane/"):]
    # Stripped of every leading and trailing separator, so the slug always
    # starts with what CHANGELOG_NAME_RE requires (`lane/_x` once gave `_x`).
    return re.sub(r"[^a-z0-9._-]+", "-", branch.lower()).strip("-._") or "local"


def changelog_path(root: Path, branch: str, today: str | None = None) -> Path:
    """This lane's changelog fragment: the existing one for its slug, or a
    new name dated today. One file per lane, so a lane edits its own."""
    slug = lane_slug(branch)
    fragments, _skipped = changelog_fragments(root)
    for p in fragments:
        m = CHANGELOG_NAME_RE.match(p.name)
        if m and m.group(2) == slug:
            return p
    stamp = today or _dt.date.today().isoformat()
    return root / CHANGELOG_DIR / f"{stamp}-{slug}.md"


def _branch(root: Path) -> str:
    try:
        result = subprocess.run(  # spawn: ok a name lookup: no branch names the fragment local
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5, cwd=str(root),
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):  # fail-open: ok text-fallback -- no git answer names the fragment local
        return ""


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="_record_fragments.py",
        description="The Session Log and changelog fragments: where to write one, "
                    "the rows as read, and the Session Log prune.",
    )
    parser.add_argument("--root", default=".", help="the repository root (default: .)")
    sub = parser.add_subparsers(dest="verb", required=True)
    new = sub.add_parser("new", help="print where the next fragment goes")
    new.add_argument("record", choices=("session-log", "changelog"))
    new.add_argument("--seat", help="the seat for a Session Log fragment (default: git config espalier.machine)")
    new.add_argument("--branch", help="the lane for a changelog fragment (default: the current branch)")
    sub.add_parser("rows", help="print the Session Log rows, newest first, as the readers see them")
    prune = sub.add_parser("prune", help="archive and delete the Session Log fragments beyond the cap")
    prune.add_argument("--keep", type=int, default=SESSION_LOG_CAP)
    prune.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    if args.verb == "new":
        if args.record == "session-log":
            seat = args.seat or _seat(root)
            path = this_sessions_row(root, seat)
            if path is not None:
                print(f"(this seat's row from today is already here, not yet committed: edit it, "
                      "one row in the file)", file=sys.stderr)
            else:
                path = new_session_log_path(root, seat=seat)
        else:
            on, how = changelog_fragments_setting(root)
            if not on:
                print(f"changelog fragments are off here: {how}. Record the change under "
                      "[Unreleased] in the changelog, if this repository keeps one, or, if "
                      f"{CHANGELOG_DIR}/ is this harness's and not another changelog tool's, set "
                      f"{CHANGELOG_FRAGMENTS_KEY} = true at the top of espalier.toml", file=sys.stderr)
                return 2
            path = changelog_path(root, args.branch or _branch(root))
        print(path.relative_to(root).as_posix())
        return 0
    if args.verb == "rows":
        _fragments, skipped = session_log_fragments(root)
        for row in session_log_rows(root):
            print(row.line)
        if skipped:
            print(f"(skipped, not fragment names: {', '.join(skipped)})", file=sys.stderr)
        return 0
    rows = prune_session_log(root, keep=args.keep, dry_run=args.dry_run)
    verb = "would prune" if args.dry_run else "pruned"
    if rows:
        print(f"{verb} {len(rows)} Session Log fragment row(s) to {ARCHIVE} "
              f"(dated {', '.join(row.date for row in rows)})")
    else:
        print(f"nothing to prune (at or under {args.keep} fragments)")
    return 0


if __name__ == "__main__":
    # Rows are the operator's text and carry non-ASCII (dashes, arrows), which
    # a redirected Windows stream would encode in the ANSI page or refuse. The
    # sibling is imported here only, so the engine's by-path load of this file
    # never needs it beside the copy.
    from _json_safe import pin_utf8_streams

    pin_utf8_streams()
    sys.exit(main())
