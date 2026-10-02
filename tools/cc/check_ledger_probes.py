#!/usr/bin/env python3
"""Re-derive every FORWARD_LEDGER.md row's claim and report the strike candidates.

Why this exists. On 2026-08-20 a nine-agent census found **41 of 222** ledger rows
were no longer live -- already fixed, premise refuted, or filed against a declared
record surface. The 2026-08-05 rebuild had measured ~12% dead at fifteen days; this
one measured ~18%. Nothing re-derived a row's claim after it was written, so a row
went false silently and stayed. That is the ledger's own §C11 class, and the ledger
was its largest instance.

A probe is a one-line READ-ONLY command that re-derives one row's claim, plus the
value it prints WHILE THE DEFECT IS OPEN. When a probe stops printing that value,
the row is a STRIKE CANDIDATE -- a prompt to re-verify by hand, never an
instruction to delete.

⚠ THE VERDICT IS THREE-WAY, AND THAT IS THE WHOLE SAFETY DESIGN.
An earlier cut of this runner reported STRIKE for a row whose cited FILE NO LONGER
EXISTED -- it read "the probe stopped saying True" as "the defect is fixed", when
the truth was "the probe lost its subject". The ledger was gitignored until
2026-09-21 -- no git undo, so a wrong strike destroyed live work outright -- and a
tracked file still loses it once the strike is committed unread. Every probe therefore
names a `subject` that must resolve BEFORE its answer counts for anything, and a
missing subject reports UNRESOLVED. A probe whose COMMAND reads paths the subject
does not name -- a local-only folder the public checkout ships without -- declares
them in `inputs`, and a missing member reports UNRESOLVED the same way: the first
strike run on a checkout without `task-packs/Done/` graded two live rows as fixed
because the tool they shell out to gave its all-clear over an empty folder
(`DEF-858`, measured 2026-09-22). Never collapse this to a boolean.

A tree that keeps no ledger exits 0 with a note. A probes file that is missing or
empty passes only while the ledger has no live row: every row `ledger_row.py` files
gets a roster entry, so a live row beside no roster means the roster was LOST, and
the run refuses rather than report zero strikes over it.

Usage:
    python3 tools/cc/check_ledger_probes.py            # report
    python3 tools/cc/check_ledger_probes.py --json     # machine-readable
    python3 tools/cc/check_ledger_probes.py --strikes  # exit 1 if any strike candidate
    python3 tools/cc/check_ledger_probes.py --root DIR # another checkout
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Iterable

_GRAMMAR = None


def _grammar():
    """``generate_ledger_regions`` -- the ledger grammar's one home -- loaded by
    path, so a row's id cell is read here exactly as the generator and the verbs
    read it (``cell_ids``; ``DEF-863``) and the root is found by the same walk
    (``find_root``). Loaded at import since the root comes from it; private-named
    because this module is imported as a plain module by its tests and the
    generator is a sibling script, not a package."""
    global _GRAMMAR
    if _GRAMMAR is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_check_ledger_probes_grammar", Path(__file__).resolve().parent / "generate_ledger_regions.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        _GRAMMAR = mod
    return _GRAMMAR


_ROOT = _grammar().find_root()
_PROBES = _ROOT / "task-packs" / "LEDGER_PROBES.json"
_TIMEOUT = 30

STILL_OPEN = "STILL_OPEN"
STRIKE_CANDIDATE = "STRIKE_CANDIDATE"
UNRESOLVED = "UNRESOLVED"
NO_ORACLE = "NO_ORACLE"

#: The bare interpreter names a probe may open with. A probe spelled with one
#: of these runs under THE INTERPRETER RUNNING THIS CHECKER, never under
#: whatever the name resolves to on PATH -- or fails to. Every probe in the
#: file was authored on a macOS host as `python3 -c ...`, and a stock Windows
#: install ships only `python`: measured 2026-09-28 on such a host, 181 of 188
#: probes read UNRESOLVED (`could not execute: [WinError 2]`), twelve cases in
#: this module's own contract went red, and `ledger_row.py file` refused every
#: row because the probe it must drive first could not start. The mirror-image
#: sweep (rewriting the data to `python`) strands the macOS host the same way;
#: the two portability twins in `tests/test_portability_contract.py` forbid
#: both literals in operator text for exactly that reason, and the stop gate
#: already runs its pytest under `sys.executable`. Those guards read operator
#: text and settings.json; command text stored as data is a third surface, and
#: this is where it is resolved. An explicit spelling (`python3.11`, a path) is
#: a pin the author chose and passes through as written.
_BARE_INTERPRETERS = frozenset({"python", "python3"})
#: The Windows launcher spelling a probe authored on a launcher-only host
#: opens with (`py -3 -c ...`): the launcher plus one version flag, resolved
#: here like a bare name. Twin of espalier._python_floor.LAUNCHER_VERSION_FLAG.
_LAUNCHER_VERSION_FLAG = re.compile(r"-3(\.\d+)?(-(32|64|arm64))?")


def _under_this_interpreter(argv: list[str]) -> list[str]:
    """``argv`` with a bare leading interpreter name replaced by ``sys.executable``.

    ``-X utf8`` rides along: a probe reads repo files as text, and on a Windows
    host whose code page is not UTF-8 six of them decode a 0x8f/0x90 byte to a
    ``UnicodeDecodeError`` instead of a verdict (measured 2026-09-28 with
    ``PYTHONUTF8`` unset). The verdict must not depend on the host's code page;
    the flag is a no-op where UTF-8 is already the default.
    """
    if argv and argv[0] in _BARE_INTERPRETERS:
        return [sys.executable, "-X", "utf8", *argv[1:]]
    if len(argv) > 1 and argv[0] == "py" and _LAUNCHER_VERSION_FLAG.fullmatch(argv[1]):
        return [sys.executable, "-X", "utf8", *argv[2:]]
    return argv

#: The ledger this probe file re-derives. Read ONLY for the staleness axis
#: below; the verdict machinery never touches it.
_LEDGER = _ROOT / "task-packs" / "FORWARD_LEDGER.md"

#: A tree-walking probe answers over whatever the filesystem holds, so a
#: generated DUPLICATE of tracked source makes it count that source twice.
#:
#: ⚠ MEASURED 2026-09-02, and this is why the check exists. `DEF-636`'s probe
#: counts a literal across ``Path('.').rglob('*.py')`` excluding only
#: ``_vendor``. It printed **5** at 17:40 and **3** at 18:50 with NO change to
#: the code it claims to measure -- the difference was `build/lib/espalier/`, a
#: setuptools staging copy of `cli.py` and `doctor.py` that one test run created
#: and a later one cleaned. A probe whose answer depends on whether someone
#: recently ran a build is not an oracle; at 5 it reported STRIKE_CANDIDATE on a
#: row whose defect was untouched, and the ledger was gitignored at the time, so
#: acting on that verdict destroyed live work `git checkout` could not bring back
#: (tracked since 2026-09-21; the verdict is no less wrong). 23 of
#: 222 probes walk the
#: tree and none of them excluded it.
#:
#: ⚠ THE POPULATION IS DERIVED, NOT LISTED, and the first cut of this check got
#: that wrong. A hand-written tuple (`build`, `dist`, `.venv`, the three caches)
#: moved 22 probes to UNRESOLVED on a healthy tree: measured, `.venv` holds 405
#: `.py` files that duplicate ZERO tracked source (an editable install links
#: rather than copies) and the caches hold none at all. Only a directory that
#: actually contains a duplicate contaminates, so that is what gets tested --
#: `STANDING_PRINCIPLES` §14, derive the list rather than testing a copy of it.
#: ⚠ `.glob(` is here because `Path(x).glob("**/*.py")` is a recursive walk that
#: the first four markers all miss -- it reaches a `build/` exactly as `rglob`
#: does. Over-matching is the safe direction: a non-recursive `.glob("*.py")`
#: that gets gated costs one UNRESOLVED; a recursive one that does not costs a
#: wrong verdict on a row -- and until 2026-09-21, in a file `git status` never
#: showed as dirty.
#:
#: ⚠ The recovery route for the tracked ledger is git itself: `git checkout`
#: for an uncommitted strike, `git log -p -- task-packs/FORWARD_LEDGER.md` for
#: one committed unread (every committed state is there). The orphan
#: `refs/heads/record` ref `scripts/record_snapshot.py` writes covers the
#: gitignored siblings and the snapshots from before 2026-09-21 -- NOT the
#: tracked file, which `build_add_list` subtracts as already tracked (the
#: failure-mode lane drove it). A record-branch route recovers only back to
#: the LAST SNAPSHOT: measured 2026-09-02, the ref held 533,177 bytes
#: while the working file held 542,326. Everything since the last snapshot is
#: still lost, which is why the gate refuses rather than guesses.
#: ⚠ Matched as CALLS, not bare tokens, and `.glob(` is in the set. Measured
#: over the live 222: the bare-token form gated FOUR probes that never walk
#: anything -- DEF-20, DEF-417g, DEF-489 and DEF-576 open ONE file and search
#: its text for the literal string `rglob` -- while missing FIVE that really do
#: walk (DEF-324c, DEF-345a, DEF-646, DEF-648, DEF-668, all spelled `.glob(`).
#: Net 22 -> 23. Gating a probe that cannot be contaminated costs a correct
#: verdict for no safety, and a report degraded on the common path is the
#: "trains reviewers to ignore red CI" outcome this design exists to avoid;
#: missing a real walk costs a wrong verdict, which is the worse half.
#: Re-derive with `_walks_the_tree` rather than trusting this figure.
#:
#: ⚠ OPERATIONALLY: the test suite CREATES the tree this gate refuses over.
#: `tests/test_wheel_payload.py` builds an sdist into `build/`, so running this
#: script straight after a full suite reports ~18 of 23 walkers UNRESOLVED --
#: correct (192 files there, including byte-copies of `espalier/*.py`), but
#: degraded. Driven 2026-09-02: `build/` present -> 18 UNRESOLVED; removed ->
#: 0, with nothing else changed. If a run looks unexpectedly gated, that is
#: the first thing to check, and deleting `build/` is the whole remedy.
_TREE_WALK_MARKERS: tuple[str, ...] = (
    "rglob(", "os.walk(", "iglob(", "glob.glob(", ".glob(",
)

#: Cap the per-directory scan. A duplicate lives near the top of a staging tree
#: (``build/lib/<pkg>/``), so this bounds `.venv`-sized walks without missing
#: the case the check exists for.
_DUPE_SCAN_LIMIT = 4000


class _GitUnavailable(RuntimeError):
    """git could not answer "what is tracked here?".

    A distinct type because the caller must NOT read it as "nothing is
    tracked". Both readings produce an empty index; only one of them means the
    tree is clean. Conflating them is how this check would fail open -- see
    `_contaminating_trees`.
    """


def _tracked_by_basename() -> dict[str, list[str]]:
    """Tracked source relpaths, indexed by basename.

    ⚠ EVERY tracked path is indexed, with no extension filter. A six-extension
    whitelist (`.py .md .json .toml .yml .yaml`) shipped here first and was
    measured to make three live probes PERMANENTLY ungateable: `DEF-539` and
    `LG-6` walk `*.gif`, `DEF-625` walks `*.js`, and no `.gif` or `.js` file
    could enter the index, so no duplicate of one was findable by construction.
    Package data is exactly what a wheel build stages, so those are the walks
    most exposed to a staging copy, not least. The filter bought nothing an
    index this size needs.

    ⚠ Raises `_GitUnavailable` rather than returning `{}` when git cannot
    answer. The empty dict is a real answer ("no tracked file has a directory
    component"); a failed `git ls-files` is not an answer at all, and returning
    `{}` for it silently disabled this entire check -- the fail-open shape it
    was written to prevent, reproduced inside the fix. The returncode went
    unchecked in the first cut, so no exception was even needed to trigger it.

    ⚠ Indexed by basename and matched by SUFFIX, not by a fixed number of
    trailing segments. The first cut keyed on the trailing 3 segments and was
    VACUOUS: a staging copy sits one level deeper than its original
    (``build/lib/espalier/cli.py`` -> ``lib/espalier/cli.py``) so it never
    equalled the tracked key ``espalier/cli.py``. It reported a clean tree with
    a planted duplicate sitting in it -- the exact defect this check exists to
    catch. Proven by planting one and watching the check stay green.
    """
    try:
        proc = subprocess.run(
            ["git", "ls-files"], cwd=_ROOT, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as err:   # pragma: no cover
        raise _GitUnavailable("git ls-files could not be run") from err
    if proc.returncode != 0:
        raise _GitUnavailable(f"git ls-files exited {proc.returncode}")
    out = proc.stdout.split()
    if not out:
        raise _GitUnavailable("git ls-files returned nothing")
    index: dict[str, list[str]] = {}
    for rel in out:
        # A ROOT-level tracked file is skipped: `README.md` as a suffix matches
        # any file called README.md anywhere, and `.pytest_cache/README.md`
        # duly flagged the cache as a duplicate of the repo (measured). Only a
        # path carrying its directory (`espalier/cli.py`) is specific enough to
        # mean "this is a copy of that".
        if "/" not in rel:
            continue
        index.setdefault(rel.rsplit("/", 1)[-1], []).append(rel)
    return index


def _safe_rglob(root: Path, pattern: str = "*") -> "Iterable[Path]":
    """Every path under ``root``, never descending a symlinked directory (local
    copy -- ``tools/cc/`` has zero espalier imports; ``espalier/_safe_walk.py``
    holds the canonical one). A bare ``rglob`` follows directory symlinks on
    CPython 3.10-3.12, so a link loop in an ignored folder of an adopter's tree
    -- a ``.venv``, a ``node_modules`` -- ends the walk with ``ELOOP``."""
    import fnmatch
    import os
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        for name in (*dirnames, *filenames):
            if fnmatch.fnmatch(name, pattern):
                yield base / name


def _ignored_root_dirs() -> list[str]:
    """Root-level directories git ignores -- the only place a dupe can hide."""
    names = []
    for child in sorted(_ROOT.iterdir()):
        if not child.is_dir() or child.name == ".git":
            continue
        try:
            ignored = subprocess.run(
                ["git", "check-ignore", "-q", child.name],
                cwd=_ROOT, timeout=_TIMEOUT,
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):   # pragma: no cover
            continue
        if ignored:
            names.append(child.name)
    return names


def _contaminating_trees() -> dict[str, set[str]]:
    """Ignored root dirs holding a duplicate of tracked source -> its suffixes.

    Derived on every call: a tree contaminates only while the duplicate is
    really there, so a cleaned `build/` stops being reported without anyone
    editing a list.

    ⚠ The SUFFIXES matter as much as the directory, and gating on the directory
    alone was measured wrong. `build/` is recreated by the test suite itself
    (`tests/test_wheel_payload.py` builds an sdist), so a presence-only gate put
    23 probes into UNRESOLVED after every full run -- and `build/` oscillates as
    tests create and clean it, making the gating intermittent. A report that is
    degraded in the common case is the "trains reviewers to ignore red CI" shape
    the repo names elsewhere. A probe counting `*.md` is simply not affected by
    a staging tree that holds only `.py`, so the extensions are carried through
    and the gate intersects them with what the probe actually walks.

    Recurrence to expect (2026-09-26): a parked copy of a tracked file under a
    RECORD_ROOT such as `reports/seed-carry-2026-09-25/` becomes a duplicate the
    day the original is tracked again, and every `.md`-walking probe goes
    UNRESOLVED at once. The remedy is to rename the parked copy out of the
    suffix (`<name>.md.adopted-<date>`), never to widen this gate.
    """
    index = _tracked_by_basename()   # raises _GitUnavailable -- deliberately
    hits: dict[str, set[str]] = {}
    for name in _ignored_root_dirs():
        seen = 0
        for path in _safe_rglob(_ROOT / name):
            if not path.is_file():
                continue
            seen += 1
            if seen > _DUPE_SCAN_LIMIT:
                break
            candidates = index.get(path.name)
            if not candidates:
                continue
            rel = path.as_posix()
            # A real duplicate ends with the tracked path it copies.
            if any(rel.endswith("/" + tracked) for tracked in candidates):
                hits.setdefault(name, set()).add(path.suffix)
    return hits


def _suffixes_walked(cmd: str) -> set[str]:
    """File suffixes a probe's glob names, e.g. {'.py'} for ``rglob('*.py')``.

    An empty set means the probe walks without naming a type, and the caller
    treats that conservatively -- unknown breadth is gated.
    """
    return {"." + ext for ext in re.findall(r"\*\.(\w+)", cmd)}


#: `_contaminating_trees()` memoised. `None` = not computed yet; the string
#: `_GIT_UNKNOWN` = git could not be consulted, which gates conservatively.
_GIT_UNKNOWN = "git-unavailable"
_CONTAMINATION: "dict[str, set[str]] | str | None" = None


def _contamination_cache() -> "dict[str, set[str]] | str":
    """`_contaminating_trees()` once per process -- it walks the filesystem.

    ⚠ Memoised for the process, and the docstring above says "derived on every
    call" of the function, not of this accessor. A run takes ~90s and `build/`
    is created and removed by the suite inside that window, so the population is
    a point sample taken at the first tree-walking probe. That is deliberate: a
    per-probe re-derivation would walk the filesystem 22 times, and a gate whose
    answer changes mid-report is worse than one that is consistently stale. The
    residual exposure is a duplicate that appears AFTER the sample.
    """
    global _CONTAMINATION
    if _CONTAMINATION is None:
        try:
            _CONTAMINATION = _contaminating_trees()
        except _GitUnavailable:
            _CONTAMINATION = _GIT_UNKNOWN
    return _CONTAMINATION


def _walks_the_tree(cmd: str) -> bool:
    return any(marker in cmd for marker in _TREE_WALK_MARKERS)


def _excludes(cmd: str, names: "Iterable[str]") -> bool:
    """True when the probe already filters every contaminating tree itself.

    ⚠ Matched on a token boundary, not as a bare substring. `name in cmd` read
    the word `rebuild` -- or `build_release_archive`, a real path in this
    repo -- as "this probe already filters `build/`", silently waiving the gate
    for a probe that does no such thing. That is the fail-open shape this whole
    check exists to prevent, one function below the check.
    """
    return all(
        re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", cmd)
        for name in names
    )


def _row_line(rid: str, text: str) -> str | None:
    """The unstruck member line for ``rid``, or None.

    ⚠ UNSTRUCK ONLY, and deliberately. Striking a row rewrites its line, so a
    struck row would report STALE_CLAIM forever -- demanding a re-derivation of
    a claim that is already retired. A struck row is done; it has nothing left
    to re-measure.
    """
    # ⚠ MEMBER ROWS ONLY, AND THE MUTATION THAT FORCED THIS IS WORTH KEEPING.
    # The first cut took the first line whose opening cell was the backticked id.
    # An id appears TWICE in this file -- once as its member row and once as an
    # Appendix B index row (`| `DEF-N` | §C5 | path |`) -- so striking the member
    # row made the search fall through to the index row, whose text differs, and
    # reported STALE_CLAIM for a row that had just been retired. Exactly the
    # false alarm the unstruck-only rule above exists to prevent, arriving through
    # a door that rule could not see. Discriminate on the SECOND cell: an index
    # row's is a bare `§CN` back-reference, a member row's is a source site.
    #
    # The id cell may carry more than one id (`| `DEF-539` `LG-6` | ...`, the
    # multi-id shape). Until 2026-09-20 this demanded a lone id before the
    # pipe, so such a row was found by NEITHER id: a rewrite of it was never
    # reported and a pin stamped on it was inert (`DEF-863`). The cell is read
    # by the grammar's own reader, so any of its ids addresses the row.
    grammar = _grammar()
    for m in re.finditer(r"^\|[^\n]*`" + re.escape(rid) + r"`[^\n]*$", text, re.M):
        line = m.group(0).rstrip()
        if rid not in grammar.cell_ids(line) or grammar._is_struck(line):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)]
        if len(cells) > 2 and re.fullmatch(r"§C\d+", cells[2]):
            continue
        return line
    return None


def retired_ids(probes: list[dict]) -> set[str]:
    """Probe ids whose ledger row is already STRUCK.

    A struck row that stops reproducing is not news -- somebody already acted on
    it. Before this filter the strike list mixed the two, and on 2026-08-26 it
    read as eight candidates when five needed a human and three had been retired
    weeks earlier. That ratio is how a real signal gets skimmed: the list looked
    long enough to be somebody else's problem, and one of the five had been
    written into a class as live earlier the same day.

    Still RUN, never skipped -- a retired row that starts reproducing again is
    worth seeing. Only the reporting is separated.
    """
    if not _LEDGER.is_file():
        return set()
    text = _LEDGER.read_text(encoding="utf-8", errors="replace")
    grammar = _grammar()
    out = set()
    for probe in probes:
        rid = probe.get("id", "")
        if not rid:
            continue
        # The strike marker sits on every id of a struck cell (`| ~~`DEF-538`~~
        # ~~`LG-5`~~ | ...`); keyed on a lone leading id, a co-id's probe read
        # as a candidate rather than as retired (`DEF-863`).
        for m in re.finditer(r"^\|[^\n]*~~`" + re.escape(rid) + r"`~~[^\n]*$", text, re.M):
            if grammar._is_struck(m.group(0)) and rid in grammar.cell_ids(m.group(0)):
                out.add(rid)
                break
    return out


def row_sha(line: str) -> str:
    """The pin over a whole member line -- the reader's definition, and the
    writer's (``ledger_row.py`` imports it; the two used to differ by an
    ``rstrip``, so a row with trailing whitespace was stale forever)."""
    return hashlib.sha256(line.encode("utf-8")).hexdigest()[:12]


def text_sha(line: str) -> str:
    """The pin over the row's TEXT cell only. ``row_sha`` covers the whole
    line, so a structural edit -- the §C0 table gaining its tag cells on
    2026-09-08 re-pinned 37 rows -- is indistinguishable from a claim rewrite.
    A probe that carries ``text_sha`` is judged on it; the claim is the text."""
    cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip()[1:-1])]
    return hashlib.sha256((cells[2] if len(cells) > 2 else line).encode("utf-8")).hexdigest()[:12]


def stale_claims(probes: list[dict]) -> list[tuple[str, str, str]]:
    """Probes whose row PROSE changed after the probe was written.

    ⚠ THIS IS A SEPARATE AXIS FROM THE VERDICT, not a fourth verdict, and the
    distinction is the whole point. A row can be STILL_OPEN *and* stale at the
    same time -- which is exactly what happened to DEF-493: its probe drove the
    original redirect symptom and correctly reported STILL_OPEN for five days
    while the row's prose carried a cause that measurement had already refuted.
    A liveness check cannot see a misattribution. This can see that the claim was
    REWRITTEN and never re-measured, which is the reachable half.

    What it does NOT do, stated so nobody reads more into a green: it cannot tell
    you a stated cause is WRONG. Only that one changed without its oracle.
    """
    if not _LEDGER.is_file():
        return []
    text = _LEDGER.read_text(encoding="utf-8", errors="replace")
    out: list[tuple[str, str, str]] = []
    for probe in probes:
        stored = probe.get("text_sha") or probe.get("row_sha")
        if not stored:
            continue
        line = _row_line(probe.get("id", ""), text)
        if line is None:
            # Struck, renamed or absent -- not a staleness signal. Tier 2's gate
            # in tests/ is what notices an unprobed live row; conflating the two
            # here would make a strike look like drift.
            continue
        actual = text_sha(line) if probe.get("text_sha") else row_sha(line)
        if actual != stored:
            out.append((probe.get("id", "?"), stored, actual))
    return out


def run_probe(probe: dict) -> tuple[str, str]:
    """Return ``(verdict, detail)`` for one probe. Never raises."""
    cmd = probe.get("cmd")
    if not cmd:
        return NO_ORACLE, (probe.get("why_not") or "no local oracle")

    # The subject gate. A probe whose subject moved answers a question about a
    # file that is not there -- which is NOT evidence the defect was fixed.
    subject = probe.get("subject")
    if subject and not (_ROOT / subject).exists():
        return UNRESOLVED, f"subject missing: {subject} (re-anchor the row)"

    # The inputs gate: the subject gate's twin for the paths the COMMAND reads.
    # The subject is the file the fix edits; the command may read others -- a
    # probe shelling out to `check_pack_landing.py` answers about
    # `task-packs/Done/`, which the public checkout does not carry. There the
    # tool gave a clean all-clear over nothing, the probe printed `False`, and
    # two live rows graded STRIKE_CANDIDATE on the first run (`DEF-858`). A
    # probe declares those paths; a missing one is UNRESOLVED, never a verdict.
    # The shape is checked before the walk: a bare string would be iterated one
    # character at a time and fail on `R` -- by accident, not by design.
    inputs = probe.get("inputs")
    if inputs is not None:
        if not isinstance(inputs, list) or not all(isinstance(p, str) and p for p in inputs):
            return UNRESOLVED, (
                "inputs is not a list of non-empty paths (declare each path the "
                "command reads as one string)"
            )
        # Repo-relative, forward slashes -- the convention every path comparison
        # in this repo uses. An absolute member resolves OUTSIDE this checkout
        # (`root / "/etc/x"` is `/etc/x`) and pins the row to one machine; `..`
        # and `~` escape the same way. Refused by shape, never silently resolved.
        norm = [p.replace("\\", "/") for p in inputs]
        escaping = [
            p for p in norm
            if p.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", p) or ".." in Path(p).parts
        ]
        if escaping:
            return UNRESOLVED, (
                f"inputs must be repo-relative paths: {', '.join(escaping)} (an "
                "absolute or escaping member resolves outside this checkout)"
            )
        missing = [p for p in norm if not (_ROOT / p).exists()]
        if missing:
            return UNRESOLVED, (
                f"input missing: {', '.join(missing)} (the command reads it and "
                "this checkout does not carry it; run on a tree that does)"
            )
        # A declared DIRECTORY holds what the command reads, so one that exists
        # and holds nothing is as absent as a missing one. Reachable by hand:
        # the pack-landing checklist's `mkdir -p task-packs/Done && mv ...`
        # leaves the folder behind when zsh aborts the `mv` on an unmatched
        # glob (failure-mode pass, 2026-09-22) -- present, empty, and the tool
        # the probe runs then says SCANNED NOTHING over it.
        empty = [p for p in norm if (_ROOT / p).is_dir() and not any((_ROOT / p).iterdir())]
        if empty:
            return UNRESOLVED, (
                f"input empty: {', '.join(empty)} (the directory exists and holds "
                "nothing, so the command's answer would be about nothing)"
            )

    # The contamination gate, and it belongs beside the subject gate for the
    # same reason: both describe a probe that has lost its footing, which is
    # NOT evidence about the defect. A tree-walking probe run over a generated
    # duplicate of the source counts that source twice, so its number answers a
    # question about the build directory rather than about the row. Fail to
    # UNRESOLVED -- never to a verdict -- so no one strikes a live row on it.
    if _walks_the_tree(cmd):
        dupes = _contamination_cache()
        if dupes == _GIT_UNKNOWN:
            return UNRESOLVED, (
                "tree-walking probe cannot be trusted: git could not be "
                "consulted about what is tracked, so a generated duplicate of "
                "the source would be invisible to this check."
            )
        walked = _suffixes_walked(cmd)
        # Gate only where the duplicate is of a type this probe actually counts.
        # An unfiltered walk (no `*.ext` in the command) has unknown breadth, so
        # it is gated against every contaminating tree.
        relevant = {
            name: suffixes for name, suffixes in dupes.items()
            if not walked or (suffixes & walked)
        }
        if relevant and not _excludes(cmd, relevant):
            joined = ", ".join(
                f"{d}/ ({', '.join(sorted(s))})" for d, s in sorted(relevant.items())
            )
            return UNRESOLVED, (
                f"tree-walking probe cannot be trusted while {joined} "
                f"hold(s) generated duplicates of tracked source. Remove them, "
                f"or teach this probe to exclude them."
            )

    try:
        argv = shlex.split(cmd)
    except ValueError as exc:
        # `shlex.split` raises on unbalanced quotes. Before this guard one
        # malformed row aborted the WHOLE batch -- so a typo in the probes data
        # file silently cost every other probe its verdict, which is the opposite
        # of the per-probe isolation the three-way verdict exists to give.
        return UNRESOLVED, f"probe command is not parseable: {exc}"
    argv = _under_this_interpreter(argv)

    try:
        # NO shell. The argv is data (one probe per ledger row), so a shell here
        # would be real injection surface for no gain: all 191 probes were run
        # both ways and produced byte-identical output, because a probe is a
        # single command with no pipe, redirect or expansion. Still dynamic --
        # the argv comes from a file -- hence the pragma.
        # subprocess-contract: ok data-driven-probe-argv-from-LEDGER_PROBES-json
        proc = subprocess.run(
            argv, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=_TIMEOUT, cwd=_ROOT,
        )
    except subprocess.TimeoutExpired:
        return UNRESOLVED, f"timed out after {_TIMEOUT}s"
    except OSError as exc:                       # pragma: no cover - platform
        return UNRESOLVED, f"could not execute: {_grammar().json_safe().os_error_text(exc)}"

    lines = (proc.stdout or "").strip().splitlines()
    got = lines[-1] if lines else "<no output>"
    expected = probe.get("open_value")
    if got == expected:
        return STILL_OPEN, ""
    if not lines and proc.returncode != 0:
        # An erroring probe is not a fixed defect; it is a broken probe.
        err = (proc.stderr or "").strip().splitlines()
        return UNRESOLVED, f"rc={proc.returncode}: {err[-1][:80] if err else 'no output'}"
    return STRIKE_CANDIDATE, f"prints {got!r}, open_value is {expected!r}"


def main(argv: list[str] | None = None) -> int:
    # Drift details and probe output carry the ledger's own text, which is not
    # ASCII; on a cp1252 console or redirected stdout that raised
    # UnicodeEncodeError mid-report (driven 2026-09-30). A replaced glyph is
    # the right trade; a traceback is not.
    # UTF-8, not only replace: a parent appending this output to a file reads
    # it as UTF-8, and the encoding is the half a replaced glyph does not fix.
    # Pinned here rather than through _json_safe because tests load this file
    # by path and call main() with no sibling directory on sys.path.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--strikes", action="store_true",
                    help="exit 1 when any row is a strike candidate OR carries a "
                         "stale claim (both need a human; neither is a verdict)")
    ap.add_argument("--id", action="append", help="probe only these ids")
    ap.add_argument("--root", help="the checkout whose ledger to probe (default: found by "
                                   "walking up from the working directory)")
    args = ap.parse_args(argv)
    if args.root is None:
        return _run(args)
    # For this call only: the tests share one instance of this module, so a
    # --root that rebound the paths for good would redirect every later caller.
    global _ROOT, _PROBES, _LEDGER, _CONTAMINATION
    saved = _ROOT, _PROBES, _LEDGER, _CONTAMINATION
    _ROOT = _grammar().find_root(args.root)
    _PROBES = _ROOT / "task-packs" / "LEDGER_PROBES.json"
    _LEDGER = _ROOT / "task-packs" / "FORWARD_LEDGER.md"
    _CONTAMINATION = None  # the memo is per tree
    try:
        return _run(args)
    finally:
        _ROOT, _PROBES, _LEDGER, _CONTAMINATION = saved


def _ledger_live_rows() -> "int | None":
    """Live member rows in the ledger the roster serves, or None when there is
    no ledger. Raises ``OSError``/``ValueError`` when it exists and cannot be
    read; the caller refuses."""
    if not _LEDGER.is_file():
        return None
    return len(_grammar().live_member_ids(_LEDGER.read_text(encoding="utf-8")))


def _empty_roster_verdict(what: str) -> "int | None":
    """The empty-roster rule: 0 when the ledger has no live row (a note),
    1 when it has live rows or cannot be read (the roster was lost), None when
    there is no ledger at all. ``what`` names the roster's state for the
    message. The refusal exists because a LOST roster must never read as
    "nothing to strike"; a ledger with nothing live has nothing to probe."""
    try:
        live = _ledger_live_rows()
    except (OSError, ValueError) as exc:
        print(f"{what}, and {_LEDGER.name} cannot be read: "
              f"{_grammar().json_safe().os_error_text(exc)}")
        print("refusing to report -- the roster cannot be checked against its ledger")
        return 1
    if live is None:
        return None
    if live == 0:
        print(f"NOTE: no probes -- {what}, and the ledger has no live row")
        return 0
    print(f"{what}, but the ledger has {live} live row(s) -- every filed row has a "
          "roster entry, so the roster was lost; restore it from git")
    print("refusing to report -- zero probes is indistinguishable from zero strikes, "
          "which is the false green this runner exists to stop")
    return 1


def _run(args: argparse.Namespace) -> int:
    if not _PROBES.is_file():
        # `relative_to` RAISES for a path outside the root, so building the
        # message could crash the very branch whose job is to degrade quietly.
        try:
            shown = _PROBES.relative_to(_ROOT)
        except ValueError:
            shown = _PROBES
        rc = _empty_roster_verdict(f"no probe file at {shown}")
        if rc is None:
            print(f"no ledger and no probe file at {shown} -- nothing to do")
            return 0
        return rc

    try:
        _doc = json.loads(_PROBES.read_text(encoding="utf-8"))
        if not isinstance(_doc, dict):
            raise ValueError("the file is JSON but not an object")
        probes = _doc.get("probes", [])
        # A file that PARSES can still be empty or renamed-key, which reported
        # "0 probes re-derived" and exited 0 -- a clean green over a file whose
        # own `_count` said 181. Closing only the unparseable limb left the
        # quieter half of the same false-green open.
        declared = _doc.get("_count")
        if isinstance(declared, int) and declared != len(probes):
            print(f"{_PROBES.name} declares _count={declared} but carries "
                  f"{len(probes)} probe(s)")
            print("refusing to report -- a probe file that disagrees with itself "
                  "is not an honest null")
            return 1
        if not probes:
            what = (f"{_PROBES.name} parsed but yielded no probes "
                    "(empty list, or the `probes` key was renamed)")
            rc = _empty_roster_verdict(what)
            if rc is None:
                # A roster with no ledger beside it answers for nothing: refuse.
                print(what)
                print("refusing to report -- zero probes is indistinguishable from "
                      "zero strikes, which is the false green this runner exists to stop")
                return 1
            return rc
    except (OSError, ValueError, AttributeError) as exc:  # strict decode: a structured answer (DEF-829)
        # Fail CLOSED and LOUD. A corrupt probes file must never read as "no
        # probes to run" -- that would print a clean zero-strike report over a
        # file nobody checked, the exact false-green this runner exists to stop.
        print(f"cannot read {_PROBES.name}: {_grammar().json_safe().os_error_text(exc)}")
        print("refusing to report -- a probe file that will not parse is not an honest null")
        return 1
    if args.id:
        wanted = set(args.id)
        probes = [p for p in probes if p.get("id") in wanted]
        # The file-level empty check above cannot see this: it ran BEFORE the
        # filter. A typo'd --id therefore reported "0 probes re-derived" and
        # exited 0 -- the same false green as an empty file, three lines later.
        if not probes:
            print(f"no probe matches --id {', '.join(sorted(wanted))}")
            print("refusing to report -- an unmatched filter is not zero strikes")
            return 1

    results = []
    for probe in probes:
        verdict, detail = run_probe(probe)
        results.append({"id": probe.get("id"), "verdict": verdict, "detail": detail})

    stale = stale_claims(probes)
    retired = retired_ids(probes)

    if args.json:
        print(json.dumps({
            "results": results,
            "total": len(results),
            "stale_claims": [{"id": i, "stored": s, "actual": a} for i, s, a in stale],
        }, indent=1))
    else:
        counts: dict[str, int] = {}
        for r in results:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        print(f"ledger probes re-derived: {len(results)}")
        for key in (STILL_OPEN, STRIKE_CANDIDATE, UNRESOLVED, NO_ORACLE):
            print(f"  {key:<18} {counts.get(key, 0)}")
        # Printed as its own line, never folded into the verdict counts: a row
        # can be STILL_OPEN and stale at once, so adding these would double-count
        # and, worse, imply the two answer the same question.
        print(f"  {'STALE_CLAIM':<18} {len(stale)}  (orthogonal to the verdict above)")
        for key in (STRIKE_CANDIDATE, UNRESOLVED):
            rows = [r for r in results if r["verdict"] == key]
            if key == STRIKE_CANDIDATE:
                live = [r for r in rows if r["id"] not in retired]
                done = [r for r in rows if r["id"] in retired]
                if live:
                    print(f"\n--- {key} ({len(live)}) ---")
                    print("    re-verify by hand before striking; a probe is evidence, not a verdict")
                    for r in live:
                        print(f"    {r['id']:<18} {r['detail']}")
                if done:
                    print(f"\n    ({len(done)} more stopped reproducing but are ALREADY "
                          f"struck -- no action: {', '.join(r['id'] for r in done)})")
                continue
            if rows:
                print(f"\n--- {key} ({len(rows)}) ---")
                for r in rows:
                    print(f"    {r['id']:<18} {r['detail']}")
        if stale:
            print(f"\n--- STALE_CLAIM ({len(stale)}) ---")
            print("    the row's PROSE changed and its probe did not. Re-derive the")
            print("    probe against the claim the row makes NOW, or re-declare it.")
            # ASCII only: this reaches a Windows console, where cp1252 turns a
            # non-ASCII glyph into mojibake that reads as a bug in the tool.
            print("    NOTE: this says the claim was rewritten without being")
            print("    re-measured. It does NOT say the new claim is wrong.")
            print("    Nothing mechanical can say that; a pack's Task 0 still has to.")
            for rid, stored, actual in stale:
                print(f"    {rid:<18} probe pinned {stored}, row is now {actual}")

    if args.strikes and (
        any(r["verdict"] == STRIKE_CANDIDATE and r["id"] not in retired for r in results)
        or stale
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
