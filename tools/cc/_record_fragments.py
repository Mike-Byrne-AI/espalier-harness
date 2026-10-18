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
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # the bounded spawn beside this file; it is also loaded where that sibling is not importable
    from _json_safe import os_error_text, run_bounded
except ImportError:  # fail-open: ok deliberate -- tools/cc is not on sys.path (copied alone, or loaded by path): subprocess.run, a bound everywhere but Windows
    def run_bounded(
        args: Any, *, timeout: float | None = None, input: Any = None,
        capture_output: bool = False, check: bool = False, **kwargs: Any,
    ) -> "subprocess.CompletedProcess[Any]":
        """``subprocess.run``, read when called, so a replaced one is honoured as ``run_bounded`` honours it."""
        return subprocess.run(  # spawn: ok the bounded spawn's fallback where _json_safe.py is not importable
            args, timeout=timeout, input=input, capture_output=capture_output, check=check, **kwargs)

    def os_error_text(exc: BaseException) -> str:
        """``str(exc)``, where the sibling that spells an error's path as a path is not importable."""
        return str(exc)

#: The fragment directories, repo-relative with forward slashes, no trailing
#: slash. ``FRAGMENT_DIRS`` spells them with one, the form the record-file
#: lists use for a directory entry. The forward ledger's two (its rows and its
#: probes) are defined with the ledger section below.
SESSION_LOG_DIR = "memory/session-log.d"
CHANGELOG_DIR = "changelog.d"
LEDGER_DIR = "task-packs/ledger.d"
PROBES_DIR = "task-packs/probes.d"
FRAGMENT_DIRS: tuple[str, ...] = (SESSION_LOG_DIR + "/", CHANGELOG_DIR + "/",
                                  LEDGER_DIR + "/", PROBES_DIR + "/")

MEMORY_FILE = "ESPALIER_MEMORY.md"
CHANGELOG_FILE = "CHANGELOG.md"
#: Where pruned rows go: the same archive ``espalier memory prune`` appends
#: to (gitignored on the self-host tree), so evicted history has one home.
ARCHIVE = "docs/session-archive.md"

#: How many Session Log fragments the prune keeps. The legacy table held 28
#: rows when fragments began (2026-10-10); the legacy rows are frozen and do
#: not count toward this until the fold.
SESSION_LOG_CAP = 30
#: How far past the cap the fold lets the fragments run before it prunes back to
#: the cap (``tools/cc/ship.py``). With an exact cap every lane carrying a row
#: off a full main paid a prune commit of its own (eight on main from 10-13 to
#: 10-15); with the slack a prune lands about once in six rows, and two lanes off
#: one base usually stay inside it. Air fc87ad on DEF-5007, 2026-10-16.
SESSION_LOG_SLACK = 5

#: The trailer on the commits a lane's push makes to fold the parked rows in and
#: prune to the cap (``tools/cc/ship.py``, the one writer of the count): the
#: lane's own-row readers skip the rows those commits add, which are other
#: sessions' rows, never this lane's.
FOLD_TRAILER = "Espalier-Fold: session-log"

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


class SeatNameUnread(Exception):
    """This seat's machine name could not be read (git timing out, a config
    git cannot parse): naming the fragment ``local`` would be a guess."""


def _seat(root: Path) -> str:
    """This seat's name for a fragment: ``git config espalier.machine`` (a
    linked worktree's own name where it has one), lower-cased to the name
    pattern, else ``local`` where no name is set. A read that failed raises
    :class:`SeatNameUnread`: the name also decides which of today's started
    rows is this seat's, so ``local`` there would take another seat's row or
    start a second one the handoff refuses."""
    try:
        # unread-name: ok exit 1 alone is "not set" (named local); no answer, or any other exit, raises below
        result = run_bounded(  # spawn: ok a name lookup, bounded; a read that fails refuses the fragment
            ["git", "config", "--get", "espalier.machine"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5, cwd=str(root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SeatNameUnread(f"this seat's machine name could not be read ({os_error_text(exc)})") from None
    if result.returncode not in (0, 1):
        lines = (result.stderr or "").strip().splitlines()
        raise SeatNameUnread(f"this seat's machine name could not be read (git exited {result.returncode}"
                             + (f": {lines[-1][:160]}" if lines else "") + ")")
    name = result.stdout.strip() if result.returncode == 0 else ""
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
    return _top_level_switch(root, CHANGELOG_FRAGMENTS_KEY)


def _top_level_switch(root: Path, key_name: str) -> tuple[bool, str]:
    """``(on, how it was read)`` for a top-level ``key_name = true`` in
    ``<root>/espalier.toml``, by a line scan (the 3.10 floor has no tomllib):
    the one reader for both fragment switches."""
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
        result = run_bounded(  # spawn: ok a name lookup: no branch names the fragment local
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5, cwd=str(root),
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):  # fail-open: ok text-fallback -- no git answer names the fragment local
        return ""


# ---------------------------------------------------------------- forward ledger
#
# One file per ledger row and one per probe, where espalier.toml opts in. Two
# lanes that each file a row into one class wrote neighbouring lines of the
# ledger and the probe roster's tail, and GitHub's merge, which honours no
# merge driver, read the pair as conflicting until a seat caught up (driven
# 2026-10-13: two filings after one anchor met on the member row, its Appendix
# B index row and the roster's tail). A row file holds its class, its member
# line and its index lines; a probe file holds one roster entry.
#
# Readers take the VIEW: the ledger's own text with each row file's lines
# placed where the verbs used to write them, and the roster with each probe
# file's entry after its own. The view is built in memory on every read and
# never written back -- a stored copy is what two lanes would both rewrite.
# The legacy rows in the two files are read as before; on this repository a
# later fold moves them into files, and an adopter's tree keeps the file form.
#
# The grammar below is a copy of tools/cc/generate_ledger_regions.py's (this
# module is loaded by path from the engine and from scripts, so it imports no
# sibling); tests/test_ledger_fragments.py pins each copy equal to its home.

LEDGER_FILE = "task-packs/FORWARD_LEDGER.md"
PROBES_FILE = "task-packs/LEDGER_PROBES.json"
#: Each directory (``LEDGER_DIR``, ``PROBES_DIR``, above) sits beside its
#: file: the verbs take the two file paths and find the directories from them.
LEDGER_FRAGMENTS_KEY = "ledger_fragments"

#: ``generate_ledger_regions._ID_SHAPE``: ``DEF-536``, ``LG-1``, ``DEF-371a``.
_ID_SHAPE = r"[A-Z]{2,5}-\d+[a-z]*"
LEDGER_NAME_RE = re.compile(rf"^({_ID_SHAPE})\.md$")
PROBE_NAME_RE = re.compile(rf"^({_ID_SHAPE})\.json$")
#: The one other name either directory may hold: its own README, which no
#: reader takes as a record and no gate calls a stray.
DIRECTORY_README = "README.md"
#: A directory's own documents, in any case: its README and the folder
#: ``CLAUDE.md`` this repository writes beside the files it governs.
_DIRECTORY_DOCS = frozenset(name.lower() for name in (DIRECTORY_README, "CLAUDE.md"))
#: Names an operating system or an editor leaves in any directory it opens.
_OS_DROPPINGS = frozenset({"Thumbs.db", "desktop.ini"})
#: A byte-order mark, spelled by code point so no editor folds it away.
_BOM = chr(0xFEFF)


def never_a_record(name: str) -> bool:
    """Whether a name under a fragment directory is one no writer here makes
    and no reader takes as a record, so it is skipped without a word: a
    dotfile (Finder's ``.DS_Store``, a macOS ``._`` file, a vim swap file,
    ``.gitkeep``), an editor's backup (``name~``, ``#name#``), Windows's
    ``Thumbs.db``, or the directory's own README or ``CLAUDE.md``. The
    repository's ``.gitignore`` already ignores the droppings, so CI never sees
    one; counted as strays, one Finder visit stopped every ledger verb on the
    box (review, driven 2026-10-13). Any other name that is not a record's is
    a stray, and the views name it."""
    return (name.startswith(".") or name.endswith("~") or (len(name) > 1 and name[0] == name[-1] == "#")
            or name in _OS_DROPPINGS or name.lower() in _DIRECTORY_DOCS)
#: The name a writer gives a file under each fragment directory: a dated name
#: for the Session Log and the changelog, the row's or probe's id for the
#: ledger's two. The record-file lists' copies (``ci_guard``, ``_hook_utils``,
#: ``record_merge``) read one pattern per directory and are pinned to these,
#: so another tool's file in a directory of the same name is not a record file.
FRAGMENT_NAMES: dict[str, "re.Pattern[str]"] = {
    SESSION_LOG_DIR + "/": SESSION_LOG_NAME_RE,
    CHANGELOG_DIR + "/": CHANGELOG_NAME_RE,
    LEDGER_DIR + "/": LEDGER_NAME_RE,
    PROBES_DIR + "/": PROBE_NAME_RE,
}
#: ``generate_ledger_regions._SECTION_HEADING``.
_SECTION_HEADING_RE = re.compile(r"^### (§C\d+)\b")
#: ``generate_ledger_regions._MEMBER_ROW``: a table row opening with an id.
_MEMBER_ROW_RE = re.compile(r"^\|\s*(~~)?`")
#: ``generate_ledger_regions._APPENDIX_B_ROW``.
_APPENDIX_B_ROW_RE = re.compile(r"^\|\s*(~~)?`([^`]+)`(~~)?\s*\|\s*(§C\d+)\s*\|")
#: A row file's first line: the class its row belongs to.
_CLASS_LINE_RE = re.compile(r"^<!-- class: (§C\d+) -->[ \t]*$")
_CELL_ID_RE = re.compile(r"`([^`]+)`")
_ID_SHAPE_RE = re.compile(rf"^{_ID_SHAPE}$")
_ID_PARTS_RE = re.compile(r"^([A-Z]+)-(\d+)([a-z]*)$")


def is_ledger_record(rel: str) -> bool:
    """Whether a repo-relative path (either slash) is the forward ledger's
    record wherever a row lives: the ledger, its roster, or a file under one of
    their two directories. The one answer for a rule that exempts (or reads)
    the ledger by name, so a row in its own file is held the same way."""
    rel = rel.replace("\\", "/")
    return rel in (LEDGER_FILE, PROBES_FILE) or rel.startswith((LEDGER_DIR + "/", PROBES_DIR + "/"))


def is_dated_fragment(rel: str) -> bool:
    """Whether a repo-relative path (either slash) is under the Session Log's
    or the changelog's fragment directory: the dated records a rule that
    exempts ``ESPALIER_MEMORY.md`` or ``CHANGELOG.md`` exempts too."""
    rel = rel.replace("\\", "/")
    return rel.startswith((SESSION_LOG_DIR + "/", CHANGELOG_DIR + "/"))


def ledger_fragments_setting(root: Path) -> tuple[bool, str]:
    """``(on, how it was read)`` for ``ledger_fragments`` at the top level of
    ``<root>/espalier.toml``: on, the ledger verbs write row and probe files;
    off (the default), they write the two files as before. The loader reads
    both forms either way."""
    return _top_level_switch(root, LEDGER_FRAGMENTS_KEY)


def _id_key(rid: str) -> tuple[str, int, str]:
    """An id's sort key: kind, number, suffix (``DEF-9`` before ``DEF-10``)."""
    m = _ID_PARTS_RE.match(rid)
    return (m.group(1), int(m.group(2)), m.group(3)) if m else (rid, 0, "")


def row_ids(line: str) -> list[str]:
    """Every id in a member row's FIRST cell, in cell order: the ids the row
    is addressed by (``generate_ledger_regions.cell_ids``)."""
    if not _MEMBER_ROW_RE.match(line):
        return []
    first = re.split(r"(?<!\\)\|", line.strip()[1:], maxsplit=1)[0]
    return [tok for tok in _CELL_ID_RE.findall(first) if _ID_SHAPE_RE.match(tok)]


@dataclass(frozen=True)
class LedgerFragment:
    """One row file: its name, its class, its member line and its index
    lines (one per id the row carries)."""

    name: str
    section: str
    member: str
    index: tuple[str, ...]

    @property
    def rid(self) -> str:
        return self.name[: -len(".md")]


@dataclass
class LedgerView:
    """The ledger as its readers see it. ``problems`` are row files the view
    could not place (a gate reports them; nothing is dropped silently), and
    ``skipped`` the names under the directory that are not row-file names."""

    text: str
    fragments: list[LedgerFragment]
    skipped: list[str]
    problems: list[str]


def parse_ledger_fragment(name: str, text: str) -> LedgerFragment | str:
    """A row file's parts, or why it cannot be read: its first line names a
    class, its second is a member row whose first id is the file's name, and
    every later table line is an index line for one of the row's ids."""
    # A byte-order mark is not part of the class line, whether the text came
    # from a file (``strict_text`` drops it) or from a blob a trend reader
    # decoded as plain UTF-8.
    text = text[1:] if text.startswith(_BOM) else text
    lines = [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    if len(lines) < 2:
        return f"{name}: a row file holds a class line and a member row"
    m = _CLASS_LINE_RE.match(lines[0])
    if not m:
        return f"{name}: its first line is not '<!-- class: §Cn -->'"
    member = lines[1]
    ids = row_ids(member)
    if not ids or ids[0] != name[: -len(".md")]:
        return f"{name}: its member row's first id is {ids[0] if ids else 'missing'}, not its name"
    index = tuple(lines[2:])
    for ln in index:
        im = _APPENDIX_B_ROW_RE.match(ln)
        if not im or im.group(2) not in ids or im.group(4) != m.group(1):
            return f"{name}: {ln[:60]!r} is not an index line for this row and class"
    return LedgerFragment(name, m.group(1), member, index)


def _table_end(lines: list[str], start: int, end: int, row_re: "re.Pattern[str]") -> int | None:
    """The line index after the last ``row_re`` line in ``[start, end)``, or
    after the first table rule before any heading when no row matches: where
    the verbs append a row (``ledger_row._first_row_slot`` and
    ``_appendix_b_slot``)."""
    rows = [j for j in range(start, end) if row_re.match(lines[j])]
    if rows:
        return rows[-1] + 1
    for j in range(start, end):
        if lines[j].startswith(("### ", "## ")):
            return None
        if lines[j].startswith("|---"):
            return j + 1
    return None


def _section_bounds(lines: list[str]) -> dict[str, tuple[int, int]]:
    """``{'§C1': (first line after the heading, end)}``: a section ends at the
    next class heading, the last one at the next ``## `` (the bounds of
    ``generate_ledger_regions.ledger_sections``)."""
    heads = [(i, m.group(1)) for i, ln in enumerate(lines) if (m := _SECTION_HEADING_RE.match(ln))]
    out: dict[str, tuple[int, int]] = {}
    for k, (i, name) in enumerate(heads):
        if k + 1 < len(heads):
            end = heads[k + 1][0]
        else:
            end = next((j for j in range(i + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
        out[name] = (i + 1, end)
    return out


def ledger_view_from_texts(ledger_text: str, fragments: "Sequence[tuple[str, str | None]]") -> LedgerView:
    """The view over texts already in hand: the ledger file's text and
    ``(name, text)`` for each file under ``task-packs/ledger.d/``, in any
    order. For a reader of another commit and for a writer's pending view."""
    parsed: list[LedgerFragment] = []
    skipped: list[str] = []
    problems: list[str] = []
    seen: dict[str, str] = {}
    for name, text in sorted(fragments, key=lambda pair: pair[0]):
        if not LEDGER_NAME_RE.match(name):
            skipped.append(name)
            if not never_a_record(name):
                # A verb writes a row file through <name>.tmp and retires its
                # probe first, so a .tmp is a write that never finished: the
                # verb, run again, writes it whole.
                problems.append(f"{name}: not a row-file name (<id>.md) -- a mis-cased id: rename it to "
                                "<id>.md; a crashed write's .tmp: delete it and run the verb again; a backup "
                                f"(a merge tool's .orig): delete it or move it out of {LEDGER_DIR}/")
            continue
        if text is None:
            problems.append(f"{name}: unreadable, or not UTF-8")
            continue
        frag = parse_ledger_fragment(name, text)
        if isinstance(frag, str):
            problems.append(frag)
            continue
        for rid in row_ids(frag.member):
            if rid in seen:
                problems.append(f"{name}: {rid} also has a row in {seen[rid]}")
            seen[rid] = name
        parsed.append(frag)
    lines = ledger_text.replace("\r\n", "\n").split("\n")
    bounds = _section_bounds(lines)
    for start, end in bounds.values():
        for j in range(start, end):
            for rid in row_ids(lines[j]):
                if rid in seen:
                    problems.append(f"{seen[rid]}: {rid} also has a row in {LEDGER_FILE}")
    app = next((i for i, ln in enumerate(lines) if ln.startswith("## Appendix B")), None)
    inserts: list[tuple[int, list[str]]] = []
    placed: list[LedgerFragment] = []
    by_class: dict[str, list[LedgerFragment]] = {}
    for frag in sorted(parsed, key=lambda f: _id_key(f.rid)):
        by_class.setdefault(frag.section, []).append(frag)
    for section, frags in by_class.items():
        at = _table_end(lines, *bounds[section], _MEMBER_ROW_RE) if section in bounds else None
        if at is None:
            why = "has no section" if section not in bounds else "has no member table"
            problems.extend(f"{f.name}: class {section} {why} in {LEDGER_FILE}" for f in frags)
            continue
        inserts.append((at, [f.member for f in frags]))
        placed.extend(frags)
    index_lines = [ln for f in sorted(placed, key=lambda f: _id_key(f.rid)) for ln in f.index]
    if index_lines:
        end = len(lines) if app is None else next(
            (j for j in range(app + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
        at = None if app is None else _table_end(lines, app + 1, end, _APPENDIX_B_ROW_RE)
        if at is None:
            # One problem per row file, named: a verb's refusal keys on the
            # rows it touches, and one line for every file named none of them.
            problems.extend(f"{f.name}: {LEDGER_FILE} has no Appendix B table for its index lines"
                            for f in placed if f.index)
        else:
            inserts.append((at, index_lines))
    for at, block in sorted(inserts, key=lambda p: p[0], reverse=True):
        lines[at:at] = block
    return LedgerView("\n".join(lines), parsed, skipped, problems)


def ledger_text_from_texts(ledger_text: str, fragments: "Sequence[tuple[str, str | None]]") -> str:
    """``ledger_view_from_texts(...).text``."""
    return ledger_view_from_texts(ledger_text, fragments).text


def strict_text(path: Path) -> str:
    """A ledger record's text, decoded strictly. The ledger's readers fail
    CLOSED on bytes that are not UTF-8 (a structured answer, never a reading
    with a replaced character: ``DEF-829``), unlike the Session Log's, which
    are only shown. Raises ``OSError`` or ``UnicodeDecodeError``."""
    # Plain utf-8, as every verb reads the two files: a reader that dropped a
    # byte-order mark the verbs' own reads keep passed a marked roster in CI
    # while every verb crashed on it (failure-mode review, driven 2026-10-13). A
    # row or probe file's mark is dropped where the file is parsed.
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def fragment_texts(base: Path) -> list[tuple[str, str | None]]:
    """``(name, text)`` for each file under ``base``; the text is None for a
    file that cannot be read or is not UTF-8, which the view names."""
    if not base.is_dir():
        return []
    out: list[tuple[str, str | None]] = []
    for p in sorted(base.iterdir()):
        if not p.is_file():
            continue
        try:
            out.append((p.name, strict_text(p)))
        except (OSError, UnicodeDecodeError):
            out.append((p.name, None))
    return out


def ledger_fragment_dir(ledger: Path) -> Path:
    """The row-file directory beside a ledger file."""
    return ledger.parent / LEDGER_DIR.rsplit("/", 1)[1]


def probe_fragment_dir(probes: Path) -> Path:
    """The probe-file directory beside a roster file."""
    return probes.parent / PROBES_DIR.rsplit("/", 1)[1]


def ledger_view_at(ledger: Path, ledger_text: str | None = None) -> LedgerView:
    """The view of the ledger at ``ledger`` and the row files beside it.
    ``ledger_text`` is the caller's own read of the file, when it has one, so
    each reader keeps its own policy for a file it cannot read."""
    if ledger_text is None:
        ledger_text = strict_text(ledger)
    texts = fragment_texts(ledger_fragment_dir(ledger))
    return ledger_view_from_texts(ledger_text, texts)


def ledger_text(root: Path) -> str:
    """The ledger's view at ``root``: ``task-packs/FORWARD_LEDGER.md`` with
    ``task-packs/ledger.d/`` placed in it. Raises ``OSError`` when the file
    cannot be read and ``UnicodeDecodeError`` when it is not UTF-8, as the
    file's own strict read did."""
    return ledger_view_at(root / LEDGER_FILE).text


def fragment_for(ledger: Path, rid: str) -> Path | None:
    """The row file whose member row carries ``rid`` anywhere in its id cell,
    or None: a co-id row is addressed by any of its ids, as a legacy row is."""
    base = ledger_fragment_dir(ledger)
    if not base.is_dir():
        return None
    for p in sorted(base.iterdir()):
        if not (p.is_file() and LEDGER_NAME_RE.match(p.name)):
            continue
        try:
            frag = parse_ledger_fragment(p.name, strict_text(p))
        except (OSError, UnicodeDecodeError):
            continue
        if not isinstance(frag, str) and rid in row_ids(frag.member):
            return p
    return None


@dataclass
class ProbeRoster:
    """The probe roster as its readers see it: the file's object with each
    probe file's entry after the file's own, and what could not be read."""

    data: dict
    skipped: list[str]
    problems: list[str]


def probe_roster_from_texts(roster_text: str | None,
                            fragments: "Sequence[tuple[str, str | None]]") -> ProbeRoster:
    """The roster over texts in hand: the roster file's text (None when there
    is no file: an empty legacy list) and ``(name, text)`` for each file under
    ``task-packs/probes.d/``. Raises ``ValueError`` on a roster file that is
    not JSON, as a reader of the file alone did."""
    import json  # stdlib, imported here: the Session Log readers never need it

    data = json.loads(roster_text) if roster_text is not None else {"probes": []}
    if not isinstance(data, dict):
        raise ValueError(f"{PROBES_FILE} is JSON but not an object")
    data = dict(data)
    # A missing or renamed `probes` key reads as an empty legacy list, as a
    # reader's `.get("probes", [])` always did: whether an empty roster beside
    # live rows was LOST is the reader's rule to apply, not the loader's.
    legacy = data.get("probes")
    data["probes"] = list(legacy) if isinstance(legacy, list) else []
    skipped: list[str] = []
    problems: list[str] = []
    # One probe per id, wherever it lives: a second entry for an id in the file,
    # or a probe file for an id the file already carries, is a second home --
    # a re-pin would stamp one and leave the other stale, unseen.
    homes: dict[str, str] = {}
    for entry in data["probes"]:
        rid = entry.get("id") if isinstance(entry, dict) else None
        if not rid:
            # A verb looks every entry up by its id; one without stopped every
            # strike with a KeyError while every reader passed it (failure-mode review).
            problems.append(f"{PROBES_FILE}: an entry carries no id -- give it its row's id, or delete it")
            continue
        if rid in homes:
            problems.append(f"{PROBES_FILE}: {rid} has two entries -- keep one")
        homes[rid] = PROBES_FILE
    entries: list[tuple[tuple[str, int, str], dict]] = []
    for name, text in sorted(fragments, key=lambda pair: pair[0]):
        m = PROBE_NAME_RE.match(name)
        if not m:
            skipped.append(name)
            if not never_a_record(name):
                # A filing writes its probe file last: a .tmp here is a filing
                # that died after its row, which the same filing run again
                # finishes once the .tmp is gone (it writes only the probe).
                problems.append(f"{name}: not a probe-file name (<id>.json) -- a mis-cased id: rename it to "
                                "<id>.json; a crashed write's .tmp: delete it and run the filing again (a "
                                "filing that died here left its row with no probe, and the same `ledger_row.py "
                                "file` command writes only the probe); a backup: delete it "
                                f"or move it out of {PROBES_DIR}/")
            continue
        if m.group(1) in homes:
            problems.append(f"{name}: {m.group(1)} also has a probe in {homes[m.group(1)]} -- keep one: "
                            "delete this file, or the entry there")
        if text is None:
            problems.append(f"{name}: unreadable, or not UTF-8")
            continue
        try:
            entry = json.loads(text[1:] if text.startswith(_BOM) else text)
        except json.JSONDecodeError as exc:
            problems.append(f"{name}: not JSON ({exc.msg})")
            continue
        if not isinstance(entry, dict) or entry.get("id") != m.group(1):
            problems.append(f"{name}: its entry's id is not {m.group(1)}")
            continue
        entries.append((_id_key(m.group(1)), entry))
    data["probes"].extend(e for _k, e in sorted(entries, key=lambda p: p[0]))
    return ProbeRoster(data, skipped, problems)


def probe_roster_at(probes: Path) -> ProbeRoster:
    """The roster at ``probes`` and the probe files beside it; a missing
    roster file is an empty legacy list."""
    roster_text = strict_text(probes) if probes.is_file() else None
    return probe_roster_from_texts(roster_text, fragment_texts(probe_fragment_dir(probes)))


def probe_roster(root: Path) -> dict:
    """The roster's view at ``root``: ``task-packs/LEDGER_PROBES.json`` with
    ``task-packs/probes.d/`` after it."""
    return probe_roster_at(root / PROBES_FILE).data


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
    sub.add_parser("ledger", help="print the forward ledger as its readers see it: the file with "
                                  "task-packs/ledger.d/ placed in it (never written back)")
    sub.add_parser("probes", help="print the probe roster as its readers see it: the file's entries, "
                                  "then task-packs/probes.d/ (never written back)")
    prune = sub.add_parser("prune", help="archive and delete the Session Log fragments beyond the cap")
    prune.add_argument("--keep", type=int, default=SESSION_LOG_CAP)
    prune.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    if args.verb == "new":
        if args.record == "session-log":
            try:
                seat = args.seat or _seat(root)
            except SeatNameUnread as exc:
                print(f"{exc}, so no Session Log row is named: run it again once git answers (a config git "
                      "cannot parse never will: fix it first), or name the seat with --seat", file=sys.stderr)
                return 2
            path = this_sessions_row(root, seat)
            if path is not None:
                print("(this seat's row from today is already here, not yet committed: edit it, "
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
            # As the session-log verb does: an opted-in tree with no directory
            # yet gets one, so the path printed can be written (review of #179).
            path.parent.mkdir(parents=True, exist_ok=True)
        print(path.relative_to(root).as_posix())
        return 0
    if args.verb == "rows":
        _fragments, skipped = session_log_fragments(root)
        for row in session_log_rows(root):
            print(row.line)
        if skipped:
            print(f"(skipped, not fragment names: {', '.join(skipped)})", file=sys.stderr)
        return 0
    if args.verb == "ledger":
        try:
            view = ledger_view_at(root / LEDGER_FILE)
        except OSError as exc:
            print(f"cannot read {LEDGER_FILE}: {exc.strerror or type(exc).__name__}", file=sys.stderr)
            return 2
        sys.stdout.write(view.text if view.text.endswith("\n") else view.text + "\n")
        if view.skipped:
            print(f"(skipped, not row-file names: {', '.join(view.skipped)})", file=sys.stderr)
        for problem in view.problems:
            print(f"(not placed: {problem})", file=sys.stderr)
        return 1 if view.problems else 0
    if args.verb == "probes":
        import json  # stdlib, imported here as the roster's reader does

        try:
            roster = probe_roster_at(root / PROBES_FILE)
        except OSError as exc:
            print(f"cannot read {PROBES_FILE}: {exc.strerror or type(exc).__name__}", file=sys.stderr)
            return 2
        except ValueError as exc:  # not JSON, or not UTF-8 (the strict decode)
            print(f"cannot read {PROBES_FILE}: {type(exc).__name__}", file=sys.stderr)
            return 2
        sys.stdout.write(json.dumps(roster.data, indent=1, ensure_ascii=False) + "\n")
        for problem in roster.problems:
            print(f"(not read: {problem})", file=sys.stderr)
        return 1 if roster.problems else 0
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
