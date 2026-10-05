#!/usr/bin/env python3
"""Merge a ref into the lane and resolve, by shape, the record files that two
machines' lanes conflict on by construction.

Why this exists
---------------
A ``/handoff`` on each of two machines prepends a Session Log row to
``ESPALIER_MEMORY.md`` at the same anchor and evicts a row at the same tail; a
ledger verb on each files a member row into the same first-row slot of a
class and rewrites the same derived counts; both re-derive the probes file's
``_count``. Two lanes landed between syncs therefore conflict on those files
every time -- eight of thirty-three catch-ups since the 2026-09-25 cut
(measured 2026-10-04) and three more on 2026-10-05 -- and GitHub's server-side
merge, the one ``gh pr update-branch`` runs, honours no merge driver, so the
lane reads CONFLICTING until someone resolves it by hand. The shapes are known,
so the resolution is mechanical:

* a Session Log hunk keeps every row either side ADDED and drops every row
  either side EVICTED, then the file is pruned back to its cap with the
  merged-in rows reserved;
* a ledger hunk keeps both sides' member and index rows (by id) and keeps
  ours for the derived lines, then the generator re-derives every count and
  the merge is refused if anything still drifts;
* the probes file is unioned by probe id and its ``_count`` re-derived;
* after ANY merge, clean or conflicted, the probes file's ``_count`` is
  settled against its list (a roster git merges clean as text can carry the
  field one side left behind) and a moved count rides the same merge commit.

Anything else -- a prose edit on both sides, a row changed on both sides, an
id filed on both machines, a path off the roster, an add/add or delete/modify
-- is refused BY NAME with the merge aborted, which leaves exactly the state
the operator had before: a clean tree and a lane that still needs a hand.

The merge runs in the live checkout (``git merge <ref>``), the command the
ship body told the operator to type by hand; a refusal runs ``git merge
--abort`` so the tree is clean again. ``tools/cc/ship.py`` calls
:func:`merge_ref_in` from ``catch-up`` and before the push in ``open`` and
``handoff``; the verb here is for the operator by hand::

    python tools/cc/record_merge.py origin/main            # merge and resolve
    python tools/cc/record_merge.py --probe origin/main    # only name the conflicts

Stdlib-only (``tools/cc/`` runs standalone, zero espalier imports). The ledger
grammar is the generator's own (``generate_ledger_regions.py``, loaded as a
sibling, never restated); the memory cap is read from the hook that enforces
it. Operator-facing text is 7-bit ASCII. Exit 0 when the merge landed or there
was nothing to merge, 1 on a named refusal, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Sibling helpers, reached through the script's own directory (both ship in the
# deploy set; tests/test_deploy_set_import_closure.py pins the reachability).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _json_safe import decode_text_or_problem, os_error_text  # noqa: E402

#: The record files this tool knows the shape of, repo-relative with forward
#: slashes. A conflict anywhere else is the operator's.
MEMORY = "ESPALIER_MEMORY.md"
LEDGER = "task-packs/FORWARD_LEDGER.md"
PROBES = "task-packs/LEDGER_PROBES.json"
ROSTER: tuple[str, ...] = (MEMORY, LEDGER, PROBES)
#: Where ``espalier memory prune`` archives the rows the cap step evicts
#: (``espalier/cli.py::cmd_memory_prune``'s default). Gitignored on the
#: self-host tree; an adopter that tracks it gets it in the merge commit.
ARCHIVE = "docs/session-archive.md"

DEFAULT_TIMEOUT = 60.0
#: ``git merge-file`` exits with the conflict count (capped at 127) and 255 on
#: an error; a subprocess reports -1 as 255.
_MERGE_FILE_ERROR = 255

#: A Session Log row: the date is the row marker. The same pattern as
#: ``espalier/cli.py::_MEMORY_DATE_RE`` and ``session_start.py``'s copy, which
#: tests/test_forced_copy_parity.py::TestMemoryDateRegexParity pins equal; a
#: row is matched as a WHOLE LINE and never split on pipes, so an escaped pipe
#: inside a cell is text, not a column (docs/SHARP_EDGES.md, escaped pipes).
_SESSION_ROW_RE = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})")
#: The hook constant that caps the memory file, read textually from the hook
#: source (never imported: a hook is loaded by Claude Code, not by a tool).
_HOOK_CAP_RE = re.compile(r"^_MEMORY_MD_CAP\s*=\s*(\d+)\s*$", re.M)
#: The memory file's own policy sentence, the fallback when no hook is there.
_POLICY_CAP_RE = re.compile(r"Bounded at (\d+) lines")
#: The generator's compiled patterns for lines whose VALUES it re-derives. Read
#: from the loaded module by name, never restated here; a name the generator
#: no longer has simply stops classifying as derived (then the hunk refuses).
_DERIVED_PATTERN_NAMES = (
    "_HEADLINE", "_HEADLINE_ADOPTER", "_SECTION2_HEADER", "_MEMBERS_LINE",
    "_POPULATION_TABLE_ROW", "_AUDIENCE_TABLE_ROW",
)

_MARK_OURS = "<<<<<<<"
_MARK_BASE = "|||||||"
_MARK_SEP = "======="
_MARK_THEIRS = ">>>>>>>"


class Unresolvable(Exception):
    """A named stop. The merge has been aborted (or never started); the message
    is the reason the operator reads."""


# ---------------------------------------------------------------- spawning --

def run(argv: list[str], *, timeout: float = DEFAULT_TIMEOUT, cwd: str | None = None,
        env: dict[str, str] | None = None, input: str | None = None) -> tuple[int, str, str]:
    """The one spawn. Resolves the program through PATH (so ``git.exe`` on
    Windows is found by its bare name), never a shell, always a timeout, stdin
    closed unless input is given, UTF-8 on both streams. A program that is
    missing, cannot start or outlives the timeout is a named refusal."""
    prog = shutil.which(argv[0])
    if prog is None:
        raise Unresolvable(f"{argv[0]} is not on PATH")
    stdin_kw: dict = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
    try:
        # subprocess-contract: ok the argv is the caller's by design (one runner for every step); each step's argv is pinned by tests/test_record_merge.py through the injectable runner and the real-git cases
        result = subprocess.run(
            [prog, *argv[1:]], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, cwd=cwd, env=env, **stdin_kw,
        )
    except subprocess.TimeoutExpired:
        raise Unresolvable(f"{' '.join(argv[:2])} took longer than {timeout:.0f}s") from None
    except OSError as exc:
        raise Unresolvable(f"could not run {argv[0]}: {os_error_text(exc)}") from None
    return result.returncode, result.stdout, result.stderr


Runner = Callable[..., tuple[int, str, str]]


def _load_sibling(name: str):
    """A sibling ``tools/cc`` module by path (the ledger verbs' own way to reach
    the generator): never an import, so the deploy set's import closure is the
    file beside this one and nothing else. Registered under a PRIVATE alias:
    a test module shares one instance of the generator under its bare name,
    and an instance this tool had pointed at a merge's probes file would
    answer every later caller with an absent roster, which the generator
    reads as an empty one (failure-mode review, driven 2026-10-05)."""
    path = Path(__file__).resolve().parent / f"{name}.py"
    alias = f"_record_merge_{name}"
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:
        raise Unresolvable(f"{name}.py is not beside this script: the deploy set is incomplete")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------- conflict hunks --

@dataclass
class Hunk:
    """One conflict region of a ``git merge-file`` output. ``base`` is None when
    the output carried no base section (the two-sided ``merge`` style)."""
    ours: list[str]
    base: list[str] | None
    theirs: list[str]

    def all_lines(self) -> list[str]:
        return self.ours + (self.base or []) + self.theirs

    def head(self) -> str:
        """The first line of each side, for a refusal the operator can find."""
        o = (self.ours or [""])[0][:70]
        t = (self.theirs or [""])[0][:70]
        return f"ours {o!r} / theirs {t!r}"


Segment = tuple  # ("text", [lines]) or ("conflict", Hunk)


def parse_conflicts(text: str) -> list[Segment]:
    """Split a ``git merge-file -p`` output into plain segments and hunks.
    Reads both marker styles: ``merge`` (ours, separator, theirs) and
    ``diff3``/``zdiff3`` (ours, base, separator, theirs). Marker lines are
    matched by their seven-character prefix at column 0, which no markdown
    table row or JSON line starts with."""
    lines = text.split("\n")
    segments: list[Segment] = []
    plain: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith(_MARK_OURS):
            plain.append(line)
            i += 1
            continue
        if plain:
            segments.append(("text", plain))
            plain = []
        ours: list[str] = []
        base: list[str] | None = None
        theirs: list[str] = []
        side = "ours"
        i += 1
        closed = False
        while i < len(lines):
            line = lines[i]
            if side == "ours" and line.startswith(_MARK_BASE):
                base = []
                side = "base"
            elif side in ("ours", "base") and line == _MARK_SEP:
                side = "theirs"
            elif side == "theirs" and line.startswith(_MARK_THEIRS):
                closed = True
                i += 1
                break
            elif side == "ours":
                ours.append(line)
            elif side == "base":
                assert base is not None
                base.append(line)
            else:
                theirs.append(line)
            i += 1
        if not closed:
            raise Unresolvable("the merge output has an unterminated conflict marker")
        segments.append(("conflict", Hunk(ours, base, theirs)))
    if plain:
        segments.append(("text", plain))
    return segments


def _join(segments: list[Segment], resolve: Callable[[Hunk], list[str]]) -> str:
    out: list[str] = []
    for kind, payload in segments:
        if kind == "text":
            out.extend(payload)
        else:
            out.extend(resolve(payload))
    return "\n".join(out)


def _dedupe(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            kept.append(line)
    return kept


# ------------------------------------------------------- ESPALIER_MEMORY.md --

def _no_base(path: str, hunk: Hunk) -> Unresolvable:
    return Unresolvable(f"{path}: the merge output carried no base section ({hunk.head()}); this tool "
                        "reads `git merge-file --diff3` output and nothing else -- resolve by hand")


def resolve_memory_hunk(hunk: Hunk) -> tuple[list[str], list[str]]:
    """The rows a Session Log hunk keeps, and which of them are NEW (added by
    either side), for the cap step's reservation and its check.

    Three-way row algebra: a row in a side but not in the base was added there
    and is kept; a row in the base but missing from either side was evicted
    (or rewritten) there and is dropped; a row in all three is kept once.
    Added rows come first, in ours-then-theirs order, because the anchor is
    the top of the table; the readers sort by the date a row carries, never
    by position, so the order within a day is a convention and not a
    contract. A hunk with no base section is refused: a two-sided rule ("rows
    against nothing keeps nothing") would silently drop one side's rows the
    day a reader of the worktree's own markers replaced the diff3 call.

    Every non-blank line of every side must be a Session Log row; a hunk that
    reaches into the prose around the table is the operator's."""
    def rows(lines: list[str]) -> list[str]:
        return [ln for ln in lines if ln.strip()]

    if hunk.base is None:
        raise _no_base(MEMORY, hunk)
    ours, theirs, base = rows(hunk.ours), rows(hunk.theirs), rows(hunk.base)
    for line in ours + theirs + base:
        if not _SESSION_ROW_RE.match(line):
            raise Unresolvable(f"{MEMORY}: a conflict outside the Session Log rows ({hunk.head()}) -- "
                               "resolve by hand")
    base_set = set(base)
    new_ours = [ln for ln in ours if ln not in base_set]
    new_theirs = [ln for ln in theirs if ln not in base_set and ln not in new_ours]
    kept_common = [ln for ln in base if ln in ours and ln in theirs]
    return _dedupe(new_ours + new_theirs + kept_common), _dedupe(new_ours + new_theirs)


def resolve_memory_text(merged: str) -> tuple[str, list[str]]:
    """The resolved memory file from a ``git merge-file -p --diff3`` output,
    and the merged-in rows (new on either side), in the order they were kept."""
    new_rows: list[str] = []

    def resolve(hunk: Hunk) -> list[str]:
        kept, added = resolve_memory_hunk(hunk)
        new_rows.extend(added)
        return kept

    return _join(parse_conflicts(merged), resolve), new_rows


def memory_cap(root: Path) -> int | None:
    """The Session Log line cap: the constant in the hook that enforces it
    (``tools/cc/hooks/post_write_check.py``, read as text), else the memory
    file's own policy sentence, else None (no cap this tool can read)."""
    hook = root / "tools" / "cc" / "hooks" / "post_write_check.py"
    try:
        m = _HOOK_CAP_RE.search(hook.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        m = None
    if m:
        return int(m.group(1))
    try:
        m = _POLICY_CAP_RE.search((root / MEMORY).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return int(m.group(1)) if m else None


def _prune_invocations(root: Path) -> tuple[list[list[str]], dict[str, str]]:
    """The ``espalier`` CLI, tried as the PATH binary then as this interpreter's
    module; the same ladder the autoprune hook climbs. Any inherited PYTHONPATH
    is dropped (a second checkout open in another session must not answer for
    this one) and, beside an ``espalier/`` source tree, that tree is put on it
    so the self-host repository runs its own engine."""
    invocations: list[list[str]] = []
    espalier_bin = shutil.which("espalier")
    if espalier_bin is not None:
        invocations.append([espalier_bin])
    invocations.append([sys.executable, "-m", "espalier.cli"])
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    if (root / "espalier" / "__init__.py").is_file():
        env["PYTHONPATH"] = str(root)
    return invocations, env


def _read_memory(root: Path, say: Callable[[str], None]) -> str | None:
    try:
        text, problem = decode_text_or_problem((root / MEMORY).read_bytes())
    except OSError as exc:
        say(f"note: {MEMORY} could not be re-read for the cap ({os_error_text(exc)})")
        return None
    if problem:
        say(f"note: {MEMORY}: {problem}; the cap step was skipped")
        return None
    return text


def restore_memory_cap(root: Path, *, new_rows: list[str], run: Runner = run,
                       say: Callable[[str], None] = print) -> bool:
    """Prune the merged memory file back to its cap with the merged-in rows
    reserved, through ``espalier memory prune`` (the one owner of the eviction
    rule and the archive's shape). ``--keep-newest`` is the merged-in row count
    because the autoprune footgun is exactly this: the row just written is the
    one a positional eviction takes. The reservation is by date rank, so a
    merged-in row whose date reads older than the rows around it can still be
    archived; the file is re-read afterwards and such a row is named. True when
    the file is at or under the cap afterwards; False, with the way back said,
    when it could not be. Never raises for a runner's failure: the runner's
    exception class is the caller's (ship.py's is not this module's), and a
    prune that could not run is a note, never a lost merge."""
    cap = memory_cap(root)
    text = _read_memory(root, say)
    if text is None:
        return False
    count = len(text.splitlines())
    if cap is None:
        say(f"note: no memory cap could be read (no hook constant, no policy sentence); "
            f"{MEMORY} has {count} lines after the merge")
        return False
    excess = count - cap
    if excess <= 0:
        return True
    invocations, env = _prune_invocations(root)
    last = ""
    pruned = False
    for head in invocations:
        argv = head + ["memory", "prune", "--rows", str(excess), "--root", str(root),
                       "--allow-empty", "--keep-newest", str(max(len(new_rows), 1))]
        try:
            rc, _out, err = run(argv, cwd=str(root), env=env, timeout=30)
        except Exception as exc:  # noqa: BLE001 -- the runner is the caller's (ship.py raises its own class); a prune that cannot run is this note, never a lost merge
            last = os_error_text(exc)
            continue
        if rc == 0:
            pruned = True
            break
        last = err.strip() or f"rc={rc}"
    if not pruned:
        say(f"note: {MEMORY} is {excess} line(s) over its cap of {cap} and `espalier memory prune` "
            f"could not run ({last[:160]}): run it by hand, then amend the merge commit")
        return False
    after = _read_memory(root, say)
    if after is not None:
        for row in new_rows:
            if row not in after:
                say(f"note: the cap step archived a merged-in row whose date reads older than the rows kept "
                    f"({row[:70]!r}); it is in the session archive `espalier memory prune` keeps -- move it "
                    "back by hand if it belongs")
    return True


# ------------------------------------------------------- FORWARD_LEDGER.md --

def _keyed(line: str, gen) -> tuple[str, str] | None:
    """``(kind, key)`` for a line the ledger merge treats as a keyed row:
    ``("row", id)`` for a member or Appendix B row, ``("class", section)`` for
    a class-index row. None for anything else."""
    m = gen._MEMBER_ID.match(line)
    if m:
        return "row", m.group(2)
    m = gen._CLASS_TABLE_ROW.match(line)
    if m:
        return "class", m.group(1)
    return None


def _is_derived(line: str, gen) -> bool:
    for name in _DERIVED_PATTERN_NAMES:
        pattern = getattr(gen, name, None)
        if pattern is not None and pattern.match(line):
            return True
    return False


def resolve_ledger_hunk(hunk: Hunk, gen) -> list[str]:
    """The lines a ledger hunk keeps.

    Lines are keyed rows (member and Appendix B rows by id, class-index rows by
    section), derived lines (the headline, the section-2 header, the Members
    lines, the population and audience tables -- values the generator rewrites
    after the merge) or blank. A line that is none of those is prose edited on
    both sides and is the operator's.

    Rows merge three-way by key: added on either side is kept; dropped on a
    side that did not also change it is dropped; equal on both sides is kept
    once; the same text on one side and the base takes the other side's. A row
    that differs on BOTH sides is refused by its id -- and when the base lacks
    the id altogether that is two machines filing the same id, which only a
    renumber on one of them can fix. A class-index row that differs on both
    sides takes ours: its cells are counts the generator re-derives.

    Assembly keeps ours' structure (its derived lines in place, its rows
    resolved), then inserts theirs' kept rows right after the last row ours
    had; when ours had no rows at all the hunk takes theirs' structure instead,
    so a row never lands outside its table. For that to hold, a side's rows
    must be ONE block: a hunk whose rows sit in two tables (a derived or blank
    line between two row groups) is refused, because a row appended after the
    last one would land in the second table and the generator would then
    converge the counts around the misfiling (code review, driven)."""
    def classify(lines: list[str]) -> list[tuple[str, str | None, str]]:
        out = []
        for line in lines:
            keyed = _keyed(line, gen)
            if keyed is not None:
                out.append((keyed[0], keyed[1], line))
            elif not line.strip():
                out.append(("blank", None, line))
            elif _is_derived(line, gen):
                out.append(("derived", None, line))
            else:
                raise Unresolvable(f"{LEDGER}: a conflict in prose, not in rows or derived lines "
                                   f"({hunk.head()}) -- resolve by hand")
        keyed_at = [i for i, (_k, key, _l) in enumerate(out) if key is not None]
        if keyed_at and any(out[i][1] is None for i in range(keyed_at[0], keyed_at[-1] + 1)):
            raise Unresolvable(f"{LEDGER}: one conflict spans rows of more than one table ({hunk.head()}) "
                               "-- resolve by hand")
        return out

    if hunk.base is None:
        raise _no_base(LEDGER, hunk)
    ours_c, theirs_c, base_c = classify(hunk.ours), classify(hunk.theirs), classify(hunk.base)

    def rows_of(classified) -> dict[str, tuple[str, str]]:
        table: dict[str, tuple[str, str]] = {}
        for kind, key, line in classified:
            if key is None:
                continue
            if key in table:
                raise Unresolvable(f"{LEDGER}: {key} appears twice on one side of a conflict -- resolve by hand")
            table[key] = (kind, line)
        return table

    ours_rows, theirs_rows, base_rows = rows_of(ours_c), rows_of(theirs_c), rows_of(base_c)
    resolved: dict[str, str] = {}
    order: list[str] = list(ours_rows) + [k for k in theirs_rows if k not in ours_rows]
    for key in order:
        in_o, in_t, in_b = key in ours_rows, key in theirs_rows, key in base_rows
        if in_o and in_t:
            kind, o_line = ours_rows[key]
            t_line = theirs_rows[key][1]
            if o_line == t_line:
                resolved[key] = o_line
            elif kind == "class":
                resolved[key] = o_line  # counts: re-derived below the hunk level
            elif in_b and o_line == base_rows[key][1]:
                resolved[key] = t_line
            elif in_b and t_line == base_rows[key][1]:
                resolved[key] = o_line
            elif not in_b:
                raise Unresolvable(f"{LEDGER}: {key} was filed on both sides with different text "
                                   "(the same id minted on two machines): renumber one side with "
                                   "ledger_row.py, then merge again")
            else:
                raise Unresolvable(f"{LEDGER}: {key} was changed on both sides -- resolve by hand")
        elif in_o:
            if in_b:
                if ours_rows[key][1] != base_rows[key][1]:
                    raise Unresolvable(f"{LEDGER}: {key} was changed on one side and removed on the "
                                       "other -- resolve by hand")
                continue  # removed by theirs
            resolved[key] = ours_rows[key][1]  # added by ours
        else:
            if in_b:
                if theirs_rows[key][1] != base_rows[key][1]:
                    raise Unresolvable(f"{LEDGER}: {key} was changed on one side and removed on the "
                                       "other -- resolve by hand")
                continue  # removed by ours
            resolved[key] = theirs_rows[key][1]

    # Ours' structure unless ours has no rows and theirs does: a derived-only
    # hunk keeps ours, a hunk that only theirs put rows into keeps the lines
    # around those rows.
    structure, other = (theirs_c, ours_c) if (theirs_rows and not ours_rows) else (ours_c, theirs_c)
    out: list[str] = []
    emitted: set[str] = set()
    last_row_at = -1
    for kind, key, line in structure:
        if key is None:
            out.append(line)
            continue
        if key in resolved:
            out.append(resolved[key])
            emitted.add(key)
            last_row_at = len(out) - 1
    extra = [resolved[key] for _k, key, _l in other
             if key is not None and key in resolved and key not in emitted]
    if extra:
        at = last_row_at + 1 if last_row_at >= 0 else len(out)
        out[at:at] = extra
    return out


def resolve_ledger_text(merged: str, gen) -> str:
    return _join(parse_conflicts(merged), lambda h: resolve_ledger_hunk(h, gen))


def regenerate_ledger(text: str, gen, probes_path: Path) -> str:
    """Re-derive every derived region against the probes file now on disk and
    refuse if anything still drifts: a merged ledger the generator cannot
    converge is not one to commit. The generator's probes path is pointed at
    this tree for the call and put back after, as the generator's own verbs
    do with their path globals."""
    was = getattr(gen, "_PROBES", None)
    gen._PROBES = probes_path
    try:
        drift = gen.find_drift(text)
        text, _applied = gen.apply_writable(text, drift)
        residual = gen.find_drift(text)
    finally:
        gen._PROBES = was
    if residual:
        shown = "; ".join(f"{d.get('region')} at line {d.get('line')}" for d in residual[:5])
        more = f" (+{len(residual) - 5} more)" if len(residual) > 5 else ""
        raise Unresolvable(f"{LEDGER}: the merged ledger does not converge ({shown}{more}) -- "
                           "resolve by hand, then `python tools/cc/generate_ledger_regions.py --write`")
    return text


# ------------------------------------------------------- LEDGER_PROBES.json --

def _probe_roster(text: str, label: str) -> tuple[dict, dict[str, dict], list[str]]:
    try:
        data = json.loads(text)  # json-dict-safe: ok shape-checked on the next lines before any deref
    except ValueError:
        raise Unresolvable(f"{PROBES} ({label}) is not JSON -- resolve by hand") from None
    if not isinstance(data, dict) or not isinstance(data.get("probes"), list):
        raise Unresolvable(f"{PROBES} ({label}) is not a probe roster (an object with a probes list)")
    by_id: dict[str, dict] = {}
    order: list[str] = []
    for entry in data["probes"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise Unresolvable(f"{PROBES} ({label}) has a probe without an id -- resolve by hand")
        if entry["id"] in by_id:
            raise Unresolvable(f"{PROBES} ({label}) lists {entry['id']} twice -- resolve by hand")
        by_id[entry["id"]] = entry
        order.append(entry["id"])
    return data, by_id, order


def resolve_probes(base_text: str, ours_text: str, theirs_text: str) -> str:
    """The probes file unioned by probe id, three-way: added on a side is kept,
    removed on a side that did not change it is dropped (a strike retires a
    probe with its row), equal is kept once, changed on one side takes that
    side, changed on both refuses by id. The top-level annotations keep ours
    when both sides changed them. ``_count`` is re-derived, and the bytes are
    the ledger verb's own serializer so the roster stays byte-stable."""
    base, b_ids, _ = _probe_roster(base_text, "base")
    ours, o_ids, o_order = _probe_roster(ours_text, "ours")
    theirs, t_ids, t_order = _probe_roster(theirs_text, "theirs")
    kept: list[dict] = []
    for pid in o_order + [p for p in t_order if p not in o_ids]:
        in_o, in_t, in_b = pid in o_ids, pid in t_ids, pid in b_ids
        if in_o and in_t:
            if o_ids[pid] == t_ids[pid]:
                kept.append(o_ids[pid])
            elif in_b and o_ids[pid] == b_ids[pid]:
                kept.append(t_ids[pid])
            elif in_b and t_ids[pid] == b_ids[pid]:
                kept.append(o_ids[pid])
            else:
                raise Unresolvable(f"{PROBES}: the probe for {pid} was changed on both sides -- resolve by hand")
        elif in_o:
            if in_b:
                if o_ids[pid] != b_ids[pid]:
                    raise Unresolvable(f"{PROBES}: the probe for {pid} was changed on one side and "
                                       "retired on the other -- resolve by hand")
                continue
            kept.append(o_ids[pid])
        else:
            if in_b:
                if t_ids[pid] != b_ids[pid]:
                    raise Unresolvable(f"{PROBES}: the probe for {pid} was changed on one side and "
                                       "retired on the other -- resolve by hand")
                continue
            kept.append(t_ids[pid])
    # Ours' key order, with the roster and its count substituted in place, so
    # the bytes differ from ours only where the merge changed a value.
    out: dict = {}
    for key in list(ours) + [k for k in theirs if k not in ours]:
        if key == "probes":
            out[key] = kept
            continue
        if key == "_count":
            out[key] = len(kept)
            continue
        o_val, t_val, b_val = ours.get(key), theirs.get(key), base.get(key)
        if key not in ours:
            if key in base and t_val == b_val:
                continue  # ours removed it, theirs left it alone: removed
            out[key] = t_val
        elif key not in theirs:
            if key in base and o_val == b_val:
                continue  # theirs removed it, ours left it alone: removed
            out[key] = o_val
        elif o_val == t_val or o_val != b_val:
            out[key] = o_val
        else:
            out[key] = t_val
    out.setdefault("_count", len(kept))
    out.setdefault("probes", kept)
    # The same call ledger_row.py::_commit_both writes the roster with (a
    # source-text pin in tests/test_record_merge.py keeps the two spellings
    # equal); the file is LF by attribute and the writer passes newline="\n".
    return json.dumps(out, indent=1, ensure_ascii=False) + "\n"


def settle_probes_count(root: Path, gen, *, say: Callable[[str], None] = print,
                        regenerate: bool = True) -> tuple[list[str], str | None]:
    """After ANY merge: ``_count`` re-derived from the probe list on disk and,
    when it moved, the roster rewritten through the verbs' serializer and the
    ledger's derived regions re-derived against it. ``(paths rewritten, the
    note)``; ``([], None)`` when nothing moved. The caller holds the ledger
    lock.

    The three-way union above re-derives the count only when the roster
    itself conflicted. A roster git merges clean as text can still carry a
    stale count: on this tool's first live run (2026-10-05) main held 330
    over 327 (a hand merge had struck four probes and added one without
    touching the field), the lane had bumped the field to 331 for its one new
    probe, git kept the lane's line over the merged list of 328, and the merge
    commit declared 331 -- which ``check_ledger_probes.py`` then refused
    wholesale (``DEF-1128``). A roster this tool cannot read is a note, never
    a refusal of the merge: the checker names it next. ``regenerate=False``
    leaves the ledger to a caller about to resolve it (its text on disk still
    carries conflict markers)."""
    probes_path = root / PROBES
    if not probes_path.is_file():
        return [], None
    text, problem = decode_text_or_problem(probes_path.read_bytes())
    if problem:
        say(f"note: {PROBES}: {problem}; the count was not settled")
        return [], None
    try:
        data, _by_id, order = _probe_roster(text, "merged")
    except Unresolvable as exc:
        say(f"note: {exc}; the count was not settled")
        return [], None
    before = data.get("_count")
    if before == len(order):
        return [], None
    data["_count"] = len(order)
    gen._atomic_write(probes_path, json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    rewritten = [PROBES]
    note = f"{PROBES}: _count settled {before} -> {len(order)} (the list is the count)"
    ledger_path = root / LEDGER
    if regenerate and ledger_path.is_file():
        ledger_before, problem = decode_text_or_problem(ledger_path.read_bytes())
        if problem:
            raise Unresolvable(f"{LEDGER}: {problem}")
        after = regenerate_ledger(ledger_before, gen, probes_path)
        if after != ledger_before:
            gen._atomic_write(ledger_path, after)
            rewritten.append(LEDGER)
    return rewritten, note


# ------------------------------------------------------------- the merge --

@dataclass
class MergeReport:
    merged: bool                      # a merge commit was made
    resolved: list[str] = field(default_factory=list)  # roster paths this tool resolved
    notes: list[str] = field(default_factory=list)


def probe_conflicts(root: Path, ref: str, *, run: Runner = run) -> list[str] | None:
    """The paths a merge of ``ref`` into HEAD would conflict on, without
    touching the tree: ``[]`` when it merges clean, None when this git cannot
    say (``merge-tree --write-tree`` arrived in git 2.38). Attributes such as a
    union driver may not be honoured here, so a path this names can still merge
    clean in the real merge; the real merge decides."""
    rc, out, _err = run(["git", "merge-tree", "--write-tree", "--name-only", ref, "HEAD"], cwd=str(root))
    if rc == 0:
        return []
    if rc != 1 or not out.strip():
        # rc 1 with nothing on stdout is "not something we can merge" (a ref
        # this checkout lacks), not a conflict report: say "cannot say", never
        # "clean" (code review, driven 2026-10-05).
        return None
    names: list[str] = []
    for line in out.split("\n")[1:]:
        if not line.strip():
            break
        names.append(line.strip().replace("\\", "/"))
    return names


def attribute_merged_paths(root: Path, ref: str, *, run: Runner = run) -> list[str]:
    """Paths changed on BOTH sides since the merge base that carry a ``merge``
    attribute (this repository gives ``CHANGELOG.md`` ``union``). A local merge
    honours the attribute, and so does ``git merge-tree``, which therefore
    reports such a lane clean; GitHub's merge does not, so the lane would be
    born CONFLICTING on that one file. The callers treat these paths as a
    reason to merge first. Empty when git cannot answer: a path this misses
    reads CONFLICTING on GitHub, which catch-up then takes."""
    rc1, ours_out, _ = run(["git", "diff", "--name-only", f"{ref}...HEAD"], cwd=str(root))
    rc2, theirs_out, _ = run(["git", "diff", "--name-only", f"HEAD...{ref}"], cwd=str(root))
    if rc1 != 0 or rc2 != 0:
        return []
    ours = {ln.strip().replace("\\", "/") for ln in ours_out.splitlines() if ln.strip()}
    theirs = {ln.strip().replace("\\", "/") for ln in theirs_out.splitlines() if ln.strip()}
    both = sorted(ours & theirs)
    if not both:
        return []
    rc, out, _ = run(["git", "check-attr", "merge", "--", *both], cwd=str(root))
    if rc != 0:
        return []
    found: list[str] = []
    for line in out.splitlines():
        head, sep, value = line.rpartition(": ")       # `<path>: merge: <value>`
        path, sep2, _attr = head.rpartition(": ")
        if sep and sep2 and value.strip() not in ("unspecified", "unset", ""):
            found.append(path.strip().replace("\\", "/"))
    return found


def _three_way(run: Runner, root: Path, ours: str, base: str, theirs: str) -> str:
    """``git merge-file -p --diff3`` over the three versions: the conflict
    output this tool parses, in a style it chose rather than the one the
    checkout's ``merge.conflictStyle`` happens to set."""
    with tempfile.TemporaryDirectory(prefix="record-merge-") as tmp:
        paths = []
        for label, text in (("ours", ours), ("base", base), ("theirs", theirs)):
            p = Path(tmp) / label
            p.write_text(text, encoding="utf-8", newline="\n")
            paths.append(str(p))
        rc, out, err = run(["git", "merge-file", "-p", "--diff3", "-L", "ours", "-L", "base", "-L", "theirs",
                            *paths], cwd=str(root), timeout=DEFAULT_TIMEOUT)
    if rc == _MERGE_FILE_ERROR or rc < 0:
        raise Unresolvable(f"git merge-file failed: {err.strip()[:200]}")
    return out


def _abort(run: Runner, root: Path, say: Callable[[str], None]) -> None:
    try:
        rc, _out, err = run(["git", "merge", "--abort"], cwd=str(root))
    except Exception as exc:  # noqa: BLE001 -- the runner's own class is the caller's; the refusal in flight must reach the operator, not be replaced by this one
        say(f"note: git merge --abort could not run ({os_error_text(exc)}): the tree holds a half-merged "
            "state (git merge --abort by hand)")
        return
    if rc != 0:
        say(f"note: git merge --abort failed ({err.strip()[:160]}): the tree holds a half-merged state "
            "(git merge --abort by hand)")


def _restore_archive(root: Path, before: bytes | None) -> None:
    """Undo the cap step's archive append when the merge it belonged to is
    aborted: the evicted rows are live again in the restored memory file, and
    an archive that also lists them would be a record of a merge that never
    landed."""
    archive = root / ARCHIVE
    try:
        if before is None:
            if archive.is_file():
                archive.unlink()
        else:
            archive.write_bytes(before)
    except OSError:
        pass  # fail-open: ok a best-effort undo; the refusal in flight is the message


def _undo_merge(run: Runner, root: Path, say: Callable[[str], None]) -> None:
    """Put a merge git already committed back: ``git reset --hard ORIG_HEAD``,
    the HEAD git recorded before the merge. Only ever reached after the
    clean-tree precondition held, so nothing of the operator's is discarded;
    what goes is the merge commit and the settle step's half-written files."""
    try:
        rc, _out, err = run(["git", "reset", "--hard", "ORIG_HEAD"], cwd=str(root))
    except Exception as exc:  # noqa: BLE001 -- the runner's own class is the caller's; the refusal in flight must reach the operator, not be replaced by this one
        say(f"note: git reset --hard ORIG_HEAD could not run ({os_error_text(exc)}): the merge commit stands "
            "with the settle step half done (git reset --hard ORIG_HEAD by hand)")
        return
    if rc != 0:
        say(f"note: git reset --hard ORIG_HEAD failed ({err.strip()[:160]}): the merge commit stands with "
            "the settle step half done (undo it by hand)")


def _settle_after_clean_merge(root: Path, ref: str, report: MergeReport, *, run: Runner,
                              say: Callable[[str], None]) -> None:
    """The settle step on a merge git made itself. A roster whose count moved
    is folded into the merge commit git just made by an amend (``HEAD^2``
    names its second parent); a fast-forward made no merge commit and HEAD is
    the base's own, which an amend would rewrite, so the settle then rides a
    commit of its own. A settle that cannot run -- the ledger lock held, the
    ledger not converging -- undoes the merge to ORIG_HEAD so a refusal
    leaves what the operator had (``DEF-1128``)."""
    if not (root / PROBES).is_file():
        return
    try:
        # Inside the undo's reach: a deploy set without the generator is a
        # settle that cannot run, and the merge goes back with it (failure-
        # mode review, driven 2026-10-05).
        gen = _load_sibling("generate_ledger_regions")
        try:
            with gen.ledger_lock(root / LEDGER):
                rewritten, note = settle_probes_count(root, gen, say=say)
        except gen.LedgerBusy as exc:
            raise Unresolvable(f"{exc} -- if no ledger verb is running, delete that lock file and merge "
                               "again") from None
        if not rewritten:
            return
        rc, _out, err = run(["git", "add", "--", *rewritten], cwd=str(root))
        if rc != 0:
            raise Unresolvable(f"git add failed after the settle step: {err.strip()[:160]}")
        rc, _out, _err = run(["git", "rev-parse", "-q", "--verify", "HEAD^2"], cwd=str(root))
        if rc == 0:
            argv = ["git", "commit", "--amend", "--no-edit"]
        else:
            argv = ["git", "commit", "-m", f"chore(ledger): settle the probes count after merging {ref}"]
        rc, _out, err = run(argv, cwd=str(root))
        if rc != 0:
            raise Unresolvable(f"the settle step's commit failed: {err.strip()[:200]}")
    except (Exception, KeyboardInterrupt):
        _undo_merge(run, root, say)
        raise
    report.resolved.extend(rewritten)
    report.notes.append(f"{note}, folded into the merge commit")


def merge_ref_in(root: Path, ref: str, *, run: Runner = run,
                 say: Callable[[str], None] = print) -> MergeReport:
    """Merge ``ref`` into HEAD in the checkout at ``root``, resolving the
    record files by shape; everything else is refused by name with the merge
    aborted. The tree must be clean and ``ref`` fetched (``origin/main`` after
    a ``git fetch``). Raises :class:`Unresolvable`."""
    root = Path(root)
    rc, _out, _err = run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=str(root))
    if rc == 0:
        # A merge already in progress reads as a dirty tree, and "commit first"
        # would commit the conflict markers (failure-mode review, driven).
        raise Unresolvable("a merge is already in progress (MERGE_HEAD exists): finish it (resolve, "
                           "git commit) or abandon it (git merge --abort) first")
    rc, out, err = run(["git", "status", "--porcelain", "-uno"], cwd=str(root))
    if rc != 0:
        raise Unresolvable(f"git status failed: {err.strip()[:160]}")
    if out.strip():
        raise Unresolvable("the tracked tree is dirty: commit first (a merge needs a clean tree)")
    rc, out, err = run(["git", "rev-list", "--count", f"HEAD..{ref}"], cwd=str(root))
    if rc != 0:
        raise Unresolvable(f"{ref} is not a ref this checkout has: fetch it first ({err.strip()[:120]})")
    if int(out.strip() or "0") == 0:
        return MergeReport(False, notes=[f"nothing to merge: HEAD already reaches {ref}"])
    rc, out, err = run(["git", "merge", "--no-edit", ref], cwd=str(root))
    if rc == 0:
        report = MergeReport(True, notes=[f"merged {ref} cleanly"])
        _settle_after_clean_merge(root, ref, report, run=run, say=say)
        return report
    rc2, unmerged_out, _ = run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=str(root))
    unmerged = [ln.strip().replace("\\", "/") for ln in unmerged_out.splitlines() if ln.strip()]
    if rc2 != 0 or not unmerged:
        _abort(run, root, say)
        raise Unresolvable(f"git merge {ref} failed with no conflict to resolve: "
                           f"{(err.strip() or out.strip())[:200]}")
    try:
        return _resolve_unmerged(root, ref, unmerged, run=run, say=say)
    except (Exception, KeyboardInterrupt):
        _abort(run, root, say)
        raise


def _resolve_unmerged(root: Path, ref: str, unmerged: list[str], *, run: Runner,
                      say: Callable[[str], None]) -> MergeReport:
    off = [p for p in unmerged if p not in ROSTER]
    if off:
        raise Unresolvable(f"conflicts outside the record files: {', '.join(off)} -- resolve by hand "
                           f"(git merge {ref})")
    rc, listing, err = run(["git", "ls-files", "-u", "--", *unmerged], cwd=str(root))
    if rc != 0:
        raise Unresolvable(f"git ls-files -u failed: {err.strip()[:160]}")
    stages: dict[str, set[str]] = {p: set() for p in unmerged}
    for line in listing.splitlines():
        meta, _tab, path = line.partition("\t")
        parts = meta.split()
        path = path.strip().replace("\\", "/")
        if len(parts) >= 3 and path in stages:
            stages[path].add(parts[2])
    for path in unmerged:
        if stages[path] != {"1", "2", "3"}:
            raise Unresolvable(f"{path}: not a content conflict (added or deleted on one side) -- resolve by hand")

    def stage(n: int, path: str) -> str:
        rc, out, err = run(["git", "show", f":{n}:{path}"], cwd=str(root))
        if rc != 0:
            raise Unresolvable(f"could not read stage {n} of {path}: {err.strip()[:160]}")
        return out

    versions = {p: (stage(1, p), stage(2, p), stage(3, p)) for p in unmerged}  # base, ours, theirs
    # The generator is the owner of the atomic writer and the ledger lock,
    # whichever record file conflicted.
    gen = _load_sibling("generate_ledger_regions")
    report = MergeReport(True)
    new_rows: list[str] = []
    if PROBES in versions or LEDGER in versions or (root / PROBES).is_file():
        # One lock across both files, the ledger verbs' own discipline: the
        # pair tore once when the roster was written outside it (2026-09-30).
        try:
            with gen.ledger_lock(root / LEDGER):
                if PROBES in versions:
                    base, ours, theirs = versions[PROBES]
                    gen._atomic_write(root / PROBES, resolve_probes(base, ours, theirs))
                    report.resolved.append(PROBES)
                # A roster git merged clean as text may still carry a stale
                # count (DEF-1128); after the union above this is a no-op.
                settled, settle_note = settle_probes_count(root, gen, say=say,
                                                           regenerate=LEDGER not in versions)
                for path in settled:
                    if path not in report.resolved:
                        report.resolved.append(path)
                if settle_note:
                    report.notes.append(f"{settle_note}, folded into the merge commit")
                if LEDGER in versions:
                    base, ours, theirs = versions[LEDGER]
                    text = resolve_ledger_text(_three_way(run, root, ours, base, theirs), gen)
                    gen._atomic_write(root / LEDGER, regenerate_ledger(text, gen, root / PROBES))
                    report.resolved.append(LEDGER)
                elif PROBES in versions and (root / LEDGER).is_file():
                    # The roster changed under a ledger git merged clean; the
                    # derived regions read that roster, so re-derive them too.
                    before, problem = decode_text_or_problem((root / LEDGER).read_bytes())
                    if problem:
                        raise Unresolvable(f"{LEDGER}: {problem}")
                    after = regenerate_ledger(before, gen, root / PROBES)
                    if after != before:
                        gen._atomic_write(root / LEDGER, after)
                        report.resolved.append(LEDGER)
                        report.notes.append(f"{LEDGER}: counts re-derived after the probes merge")
        except gen.LedgerBusy as exc:
            raise Unresolvable(f"{exc} -- if no ledger verb is running, delete that lock file and merge "
                               "again") from None
    archive_before: bytes | None = None
    if MEMORY in versions:
        base, ours, theirs = versions[MEMORY]
        text, new_rows = resolve_memory_text(_three_way(run, root, ours, base, theirs))
        gen._atomic_write(root / MEMORY, text)
        report.resolved.append(MEMORY)
        archive = root / ARCHIVE
        archive_before = archive.read_bytes() if archive.is_file() else None
        if not restore_memory_cap(root, new_rows=new_rows, run=run, say=say):
            report.notes.append(f"{MEMORY} may sit over its cap: see the note above")
        if archive.is_file() and (archive_before is None or archive.read_bytes() != archive_before):
            # Tracked on this tree (an adopter's choice; gitignored here): the
            # eviction rides the merge commit instead of dirtying the tree. The
            # path is named only when git says the file is there.
            rc, _out, _err = run(["git", "ls-files", "--error-unmatch", "--", ARCHIVE], cwd=str(root))
            tracked_archive = str(archive.relative_to(root)).replace("\\", "/") if rc == 0 else None
            if tracked_archive is not None:
                report.resolved.append(tracked_archive)
    try:
        rc, _out, err = run(["git", "add", "--", *report.resolved], cwd=str(root))
        if rc != 0:
            raise Unresolvable(f"git add failed after resolving: {err.strip()[:160]}")
        rc, _out, err = run(["git", "commit", "--no-edit"], cwd=str(root))
        if rc != 0:
            raise Unresolvable(f"the merge commit failed: {err.strip()[:200]}")
    except Exception:  # noqa: BLE001 -- undo the cap step's archive append on ANY failure, then re-raise for the abort
        if MEMORY in versions:
            _restore_archive(root, archive_before)
        raise
    report.notes.append(f"merged {ref}; resolved by shape: {', '.join(report.resolved)}"
                        + (f" ({len(new_rows)} session row(s) merged in)" if MEMORY in versions else ""))
    return report


# -------------------------------------------------------------------- CLI --

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="record_merge.py", description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("ref", help="the ref to merge into HEAD (origin/main after a fetch)")
    parser.add_argument("--probe", action="store_true",
                        help="only name the paths the merge would conflict on; touch nothing")
    parser.add_argument("--root", default=None, help="the checkout (default: the one around the cwd)")
    return parser


def _repo_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    rc, out, err = run(["git", "rev-parse", "--show-toplevel"])
    if rc != 0:
        raise Unresolvable(f"not inside a git checkout: {err.strip()[:120]}")
    return Path(out.strip()).resolve()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = _repo_root(args.root)
        if args.probe:
            names = probe_conflicts(root, args.ref)
            if names is None:
                print("cannot probe: this git lacks `merge-tree --write-tree` (2.38+); run the merge")
                return 0
            if not names:
                print(f"{args.ref} merges clean into HEAD")
                return 0
            record = [n for n in names if n in ROSTER]
            other = [n for n in names if n not in ROSTER]
            print("would conflict on: " + ", ".join(names))
            if record:
                print("record files (resolved by shape): " + ", ".join(record))
            if other:
                print("other files (resolve by hand): " + ", ".join(other))
            return 0
        report = merge_ref_in(root, args.ref)
        for note in report.notes:
            print(note)
        return 0
    except Unresolvable as stop:
        print(f"record_merge: refused -- {stop}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    from _json_safe import pin_utf8_streams

    pin_utf8_streams()
    sys.exit(main())
