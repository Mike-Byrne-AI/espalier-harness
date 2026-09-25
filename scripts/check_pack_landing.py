#!/usr/bin/env python3
"""Closeout lint for the ``## Landing`` stanza.

Every task pack ends with a ``## Landing`` stanza recording its own landing
state (``State: DRAFT | ROADMAP | LANDED | SCRAPPED``). A pack that has moved to
``task-packs/Done/`` is, by definition, finished -- so it should carry
``State: LANDED`` (or ``State: SCRAPPED`` for one that was deliberately
abandoned). This script reports any ``Done/`` pack that does not.

**Advisory, not a CI gate -- and deliberately so.** ``task-packs/Done/`` is gitignored
(the landed packs are maintainer scratch, carried on the record branch), so it is
absent in a clean CI checkout and cannot be a merge gate. The default behavior is **report and exit 0** -- a
maintainer runs it locally to see which finished packs still owe a landing stamp.
``--strict`` makes it exit 1, which is usable now that the back-fill is complete
and the offender count is zero (e.g. for a local pre-commit).

**It says what it scanned.** The report opens with a ``SCOPE`` line counting the
packs under each terminal folder, and on a zero-member population -- a public
checkout, where ``Done/`` and ``Scrapped/`` are local-only -- prints ``SCANNED
NOTHING`` with the remedy in place of the all-clear line. The exit code does not
move on that, in either mode: a red on every tree that lacks a local-only folder
is the permanently-red advisory the paragraph above warns about. Until
2026-09-22 the all-clear printed over an empty walk, and a ledger probe that
shells out to this script read it as "chore drained" (``DEF-858``).

Two tiers are reported alongside and are deliberately OUTSIDE ``--strict``:
``roadmap_packs`` (finished-as-a-roadmap; verify the children drained) and
``incomplete_landings`` (a pack that DID land but whose stanza is missing
``Commits:``/``Suite:``/``Date:``). Folding either into the exit code would put
this permanently red again -- and a permanently-red advisory trains the very
dismissal that hides its own true positives.

Usage:
    python scripts/check_pack_landing.py           # advisory: report, exit 0
    python scripts/check_pack_landing.py --strict  # exit 1 if any pack unstamped
"""
from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKS_ROOT = REPO_ROOT / "task-packs"
DONE_DIR = PACKS_ROOT / "Done"

# WHICH FOLDERS OWE A TERMINAL STANZA -- declared, and deliberately NOT derived.
#
# "Terminal" is a judgement about what a folder MEANS, and no filesystem walk
# supplies it. `Merged/` is the proof: its packs ARE finished, and its README
# says they are "preserved **unedited** as the provenance record", so requiring
# them to carry a stamp would demand editing files a documented invariant
# forbids editing. A rglob that "derived the terminal set" would sweep them in
# and be WRONG -- deriving is not automatically the safer choice.
#
# So the enumeration is GUARDED rather than derived: `unclassified_dirs()` reds
# when a folder exists that no row here claims. That is the property `DONE_DIR`
# alone lacked -- it could not fall behind the tree, because it never looked.
TERMINAL_DIRS = ("Done", "Scrapped")        # finished AND editable -> stamp required
NON_TERMINAL_DIRS = ("Deferred",)           # parked, not finished -> no stamp owed
UNSTAMPABLE_DIRS = ("Merged",)              # finished, but preserved unedited

# The ``State:`` marker inside a pack's ``## Landing`` stanza -- the SoT for
# whether a pack landed. The top-of-file ``## Status`` block carries its own
# ``State:`` (the authoring state, e.g. DRAFT), so landed_state() scopes to the
# Landing stanza before reading it. Anchored to line start (optional list dash +
# optional markdown-bold ``**``) so a prose mention ("the State: field") is not
# matched, and tolerant of both ``- State: LANDED`` and ``- **State:** LANDED``
# spellings (the canonical skill example is non-bold; packs author it bold).
_LANDING_RE = re.compile(r"^#{1,6}\s+Landing\b", re.MULTILINE)
_STATE_RE = re.compile(r"^\s*-?\s*\*{0,2}State:\*{0,2}\s*(\w+)", re.MULTILINE)
_LANDED_STATES = frozenset({"LANDED", "SCRAPPED"})

# POPULATION: only a task PACK can carry a Landing stanza. ``task-packs/CLAUDE.md``
# fixes the convention -- "Filename ``TP-<n>-<slug>.md``" -- and ``Done/`` also
# holds review records, runbooks and archives (BACKLOG_*, RUNBOOK_*, *_archive_*)
# that were never packs. Reporting those was a POPULATION-definition bug, not a
# parse bug, and it is why this tool's output got waved off wholesale as "the
# known advisory baseline" while real mis-stamps sat inside it. A lint whose
# population is wrong gets dismissed, and its true positives go down with it.
_PACK_NAME_RE = re.compile(r"^TP-\d+[a-z]*-", re.IGNORECASE)


def is_pack_file(name: str) -> bool:
    """True if ``name`` is a task pack by the ``TP-<n>-<slug>.md`` convention."""
    return bool(_PACK_NAME_RE.match(name))


def terminal_packs(folder: Path) -> list[Path]:
    """Every pack file directly under one terminal folder -- THE population the
    stamp check, the ROADMAP tier and the incomplete-Landing tier read, kept in
    one place so the ``SCOPE`` line ``main`` prints counts exactly what they saw.
    An absent folder is an empty population, never an error: ``Done/`` and
    ``Scrapped/`` are local-only and a public checkout carries neither.

    Deliberately NOT ``pack_files`` (the active-pack reader below): that one
    admits ``.markdown`` and a bare ``tp-`` stem for the orphan guard, and the
    ratchets in ``tests/test_check_pack_landing.py`` were calibrated on the
    ``is_pack_file`` convention this population has always used. Widening the
    terminal population is its own measured change, not a side effect of
    naming it.
    """
    if not folder.is_dir():
        return []
    return [p for p in sorted(folder.glob("*.md")) if is_pack_file(p.name)]


# THE SCOPE (OUT) READER AND THE ACTIVE POPULATION -- one home, two readers.
#
# A pack's ``## Scope (out)`` is where deferred work is parked ("deferred to
# §C32", "a §2.3 remainder", "the successor pack owns this"), and until 2026-09-21 nothing
# mechanical read it: ``scripts/ledger_row.py strike`` rewrote a row without
# looking at the packs, and the completeness contract built its populations
# from folders and ids, never from the sentence saying where the work went.
# Two ledger rows named the two missing readers -- DEF-412a (the strike verb: a
# section struck while an in-flight pack still defers into it) and DEF-412e
# (the gate: a Scope (out) naming a pack nobody has written). Both read the
# same region of the same population, so the region and the population are
# defined ONCE, here, beside the Landing-stanza parser the same two callers
# already share -- a guard and a gate that parsed "Scope (out)" separately
# would disagree the first time a heading gained a trailing note.
# Calibrated on the live population (2026-09-21): 217 of 221 packs write exactly
# ``## Scope (out)``, one landed pack writes ``## Scope-out``, three have no such
# section; every active pack uses the exact form. The pattern admits the hyphen
# and case variants so a pack that drifts to one is read, not silently skipped,
# and refuses ``Scope (outline)``-shaped near-misses via the trailing lookahead.
_SCOPE_OUT_RE = re.compile(
    r"^#{1,6}[ \t]+Scope[ \t-]*\(?out\)?(?![A-Za-z])[^\n]*\n(.*?)(?=^#{1,2}[ \t]|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})[^\n]*\n.*?^\1[ \t]*$", re.MULTILINE | re.DOTALL)


def blank_fences(text: str) -> str:
    """``text`` with every fenced code block replaced by spaces, newlines kept, so
    offsets and line numbers are those of the original. A fenced shell snippet's
    ``# comment`` would otherwise read as a heading and end the section, and a
    pack quoting the skill template inside a fence would read as the section
    itself (both latent on 2026-09-21: zero of 221 packs hit either; the code
    review drove both on a synthetic pack)."""
    return _FENCE_RE.sub(lambda m: "".join("\n" if ch == "\n" else " " for ch in m.group(0)), text)


def scope_out_spans(pack_text: str) -> list[tuple[int, int]]:
    """``(start, end)`` character offsets into ``pack_text`` of every Scope (out)
    body -- one per heading, so a pack with two such sections (one landed pack
    has two) is read whole. Fences are blanked before matching; the offsets index the
    ORIGINAL text, so a caller can count lines into it."""
    return [(m.start(1), m.end(1)) for m in _SCOPE_OUT_RE.finditer(blank_fences(pack_text))]


def scope_out(pack_text: str) -> str:
    """The body of the pack's ``## Scope (out)`` section(s), fenced blocks blanked,
    or ``""`` when it has none.

    Each body runs from its heading line to the next h1/h2 heading, so ``###``
    sub-headings inside the section stay inside it. The heading may carry a
    trailing note (``## Scope (out) -- deferred, with reasons``) and may be
    spelled ``Scope-out`` or ``Scope (Out)``; only a heading is keyed on, never a
    prose mention, and never a heading inside a fence.
    """
    blanked = blank_fences(pack_text)
    return "\n".join(blanked[s:e] for s, e in scope_out_spans(pack_text))


def active_pack_dirs(packs_root: Path) -> tuple[Path, ...]:
    """The folders whose packs are ACTIVE and ship: the root plus every
    NON-TERMINAL folder (``Deferred/``). Never ``Done/``, ``Scrapped/`` or
    ``Merged/`` -- landed and dead work has left the ledger by its own contract
    rule, so a citation there is history, not a deferral. Derived from the
    guarded enumeration above, so a folder that gains a row there joins or
    leaves this population by the same edit."""
    return (packs_root, *(packs_root / d for d in NON_TERMINAL_DIRS))


def pack_files(pack_dirs: Path | Iterable[Path]) -> list[Path]:
    """Every pack file DIRECTLY under each of ``pack_dirs``: ``.md`` or
    ``.markdown``, stem opening ``tp-`` case-insensitively; a directory that does
    not exist contributes nothing (an empty population, never an error).

    ``iterdir()`` with explicit suffix/stem checks, not ``glob("TP-*.md")``: the
    glob let an off-convention orphan -- a lowercase ``tp-`` name or a
    ``.markdown`` extension -- escape the completeness guard uncounted (the
    orphan detector's own earn-the-red case),
    and the escape was platform-dependent (APFS globs case-insensitively, Linux
    CI does not). Two deliberate sibling copies exist: the orphan detector in
    ``tests/test_forward_ledger_completeness.py::_pack_files`` (it must run on a
    tree without ``scripts/``) and ``tests/test_cross_pack_assertions.py::_pack_index``
    (it walks all four status folders, not the active two). This one is the copy
    the strike verb and the deferral gate share.
    """
    dirs = [pack_dirs] if isinstance(pack_dirs, Path) else list(pack_dirs)
    return sorted(
        p for d in dirs if d.is_dir() for p in d.iterdir()
        if p.is_file()
        and p.suffix.lower() in {".md", ".markdown"}
        and p.stem.lower().startswith("tp-")
    )


# A ROADMAP in Done/ is finished-as-a-roadmap: it spawned lettered children and
# each child carries its own terminal stanza. It is NOT unstamped, but it is also
# not self-evidently drained, so it gets its own reported tier rather than being
# folded into _LANDED_STATES (which would make it silently invisible).
_ROADMAP_STATE = "ROADMAP"

# A bold VALUE (``- State: **LANDED**``) is a convention violation, deliberately
# NOT parsed: ``.claude/commands/implement-pack.md`` requires a bare value, and
# widening _STATE_RE to accept it was considered and rejected. But reading as
# "(no State: line)" made the violation indistinguishable from a genuinely
# unstamped pack -- and landed_state is no longer advisory-only
# (tests/test_forward_ledger_completeness.py imports it), so a silent None is a
# fail-open in a recurrence guard. Name it instead: same parse, legible diagnostic.
_BOLD_VALUE_RE = re.compile(r"^\s*-?\s*State:\s*\*{1,2}\s*(\w+)", re.MULTILINE)


def bold_value_state(pack_text: str) -> str | None:
    """The bold-VALUE state a pack carries in violation of the bare-value convention.

    Returns ``None`` when a conforming ``State:`` line exists (it wins) or when
    there is no bold-value line either. Diagnostic only -- ``landed_state`` is
    deliberately unchanged, so a bold-value pack stays an offender until the
    record is de-bolded.
    """
    landing = _LANDING_RE.search(pack_text)
    region = pack_text[landing.start():] if landing else pack_text
    if _STATE_RE.search(region):
        return None                      # a conforming State: line wins
    m = _BOLD_VALUE_RE.search(region)
    return m.group(1).upper() if m else None


_STATUS_RE = re.compile(r"^#{1,6}\s+Status\b", re.MULTILINE)


def status_state(pack_text: str) -> str | None:
    """The ``State:`` from the top-of-file ``## Status`` block (the AUTHORING state).

    The sibling of ``landed_state``, scoped to the OTHER stanza. Bounded at the
    ``## Landing`` heading so it never reads the landing value by accident --
    without that bound the two readers return the same string and the
    contradiction check below can never fire.

    Reads a bold value too, unlike ``landed_state``. Here a bold ``**SCRAPPED**``
    is still the author saying "retired", and treating it as absent would hide
    exactly the contradiction this exists to surface.
    """
    status = _STATUS_RE.search(pack_text)
    if not status:
        return None
    landing = _LANDING_RE.search(pack_text)
    end = landing.start() if landing and landing.start() > status.start() else len(pack_text)
    region = pack_text[status.start():end]
    m = _STATE_RE.search(region) or _BOLD_VALUE_RE.search(region)
    return m.group(1).upper() if m else None


def contradictory_packs(packs_root: Path = PACKS_ROOT) -> list[tuple[str, str, str | None]]:
    """``(relpath, status_state, landing_state)`` where the header says retired and
    the Landing stanza does not.

    LOCATION-INDEPENDENT, and that is the whole point. The shape this exists for
    sat in ``task-packs/`` ROOT with ``## Status`` reading SCRAPPED while its
    ``## Landing`` stanza still read ``State: DRAFT``. It was in neither ``Done/``
    nor ``Scrapped/``, so no amount of widening the folder scan would have caught
    it -- the pack looked retired to a reader and stayed executable by
    ``/implement-pack``.

    ONE DIRECTION ONLY. A pack whose Landing says LANDED while its Status still
    says DRAFT is the ordinary case -- the Status block records the authoring
    state and is rarely revised on landing. The dangerous direction is the
    reverse: a header claiming terminal while the SoT stanza says otherwise,
    because the header is what a human reads and the stanza is what the tooling
    keys on.
    """
    if not packs_root.is_dir():
        return []
    out: list[tuple[str, str, str | None]] = []
    for pack in sorted(packs_root.rglob("*.md")):
        rel = pack.relative_to(packs_root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if rel.parts[0] in UNSTAMPABLE_DIRS:
            continue                      # preserved unedited -- not ours to police
        if not is_pack_file(pack.name):
            continue
        text = pack.read_text(encoding="utf-8")
        declared, landed = status_state(text), landed_state(text)
        if declared in _LANDED_STATES and landed not in _LANDED_STATES:
            out.append((rel.as_posix(), declared, landed))
    return out


def unclassified_dirs(packs_root: Path = PACKS_ROOT) -> list[str]:
    """Folders under ``task-packs/`` that no classification above claims.

    The guard that replaces deriving. A new status folder is invisible to a
    hand-written list by construction -- that is how ``Scrapped/`` went unscanned
    -- so the list is allowed to stay hand-written only because this reds the
    moment it falls behind the tree.
    """
    if not packs_root.is_dir():
        return []
    known = set(TERMINAL_DIRS) | set(NON_TERMINAL_DIRS) | set(UNSTAMPABLE_DIRS)
    return sorted(
        d.name for d in packs_root.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name not in known
    )


def roadmap_packs(done_dir: Path = DONE_DIR) -> list[str]:
    """``Done/`` packs whose Landing state is ROADMAP -- verify children are drained."""
    return [
        pack.name
        for pack in terminal_packs(done_dir)
        if landed_state(pack.read_text(encoding="utf-8")) == _ROADMAP_STATE
    ]


def landed_state(pack_text: str) -> str | None:
    """The ``State:`` value from the pack's ``## Landing`` stanza, upper-cased,
    or ``None`` if absent.

    Scoped to the ``## Landing`` stanza: the top-of-file ``## Status`` block
    carries its own ``State:`` (the authoring state, usually ``DRAFT``), and the
    Landing stanza is the documented SoT for whether a pack landed. A pack with
    no Landing stanza has not landed, so the fallback whole-text scan surfaces
    the (non-terminal) Status ``State:``. Tolerates markdown-bold ``**State:**``.
    """
    landing = _LANDING_RE.search(pack_text)
    region = pack_text[landing.start():] if landing else pack_text
    m = _STATE_RE.search(region)
    return m.group(1).upper() if m else None


def unstamped_packs(done_dir: Path = DONE_DIR) -> list[tuple[str, str | None]]:
    """``(filename, state)`` for every ``Done/`` pack not in a terminal state.

    A pack is "unstamped" if it has no ``State:`` line, or its state is not one
    of LANDED / SCRAPPED. Returns an empty list when ``Done/`` is absent.

    Non-pack files in ``Done/`` (runbooks, review records, archives) are skipped:
    they have no Landing stanza by construction, so reporting them is noise that
    buries the real findings. ROADMAP packs are skipped too -- see roadmap_packs,
    which reports them as their own tier.
    """
    out: list[tuple[str, str | None]] = []
    for pack in terminal_packs(done_dir):  # never a review record, runbook or archive
        state = landed_state(pack.read_text(encoding="utf-8"))
        if state == _ROADMAP_STATE:
            continue                      # finished-as-a-roadmap; own tier
        if state not in _LANDED_STATES:
            out.append((pack.name, state))
    return out


_LANDING_FIELDS = ("Commits", "Suite", "Date")
# ``[ \t]``, never ``\s``: ``\s`` matches a NEWLINE, so on ``- Commits:\n- Suite:``
# the run would cross the line break and the trailing ``\S`` would match the NEXT
# line's ``-`` -- an EMPTY field reading as filled. That turns this reporter into a
# line-PRESENCE check, which is the adjacent question, and it is the same
# born-weak shape the population fix above exists to remove from this tool.
_LANDING_FIELD_RE_TMPL = r"^[ \t]*-?[ \t]*\*{{0,2}}{field}:\*{{0,2}}[ \t]*\S"


def incomplete_landings(done_dir: Path = DONE_DIR) -> list[tuple[str, list[str]]]:
    """``(filename, missing_fields)`` for LANDED packs whose stanza is field-incomplete.

    ``landed_state`` answers only "did it land?" -- deliberately, since a recurrence
    guard (tests/test_forward_ledger_completeness.py) depends on that answer, and
    making it stricter would make that guard skip MORE. This answers the separate
    question "is the record complete?" and is reported, never folded in.

    A driver-landed pack always is complete (``scripts/run_pack_chain.sh::finalize_landing``
    loops set_field over State/Commits/Suite/Date), so the residual population is
    hand-landed packs. A field present-but-EMPTY counts as missing: an unfilled
    ``- Commits:`` is exactly the incompleteness this reports.
    """
    out: list[tuple[str, list[str]]] = []
    for pack in terminal_packs(done_dir):
        text = pack.read_text(encoding="utf-8")
        if landed_state(text) != "LANDED":
            continue
        landing = _LANDING_RE.search(text)
        region = text[landing.start():] if landing else ""
        missing = [
            f for f in _LANDING_FIELDS
            if not re.search(
                _LANDING_FIELD_RE_TMPL.format(field=f), region, re.MULTILINE
            )
        ]
        if missing:
            out.append((pack.name, missing))
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    strict = "--strict" in argv

    if not PACKS_ROOT.is_dir():
        print("check_pack_landing: no task-packs/ (a tree without the pack folders) -- nothing to check.")
        return 0

    # The enumeration guard runs FIRST and is reported even when everything else
    # is clean: a folder nobody classified is the failure that hid `Scrapped/`,
    # and it is silent by construction in every check downstream of it.
    # PACKS_ROOT passed EXPLICITLY, never left to the default. A default
    # argument binds once at def time, so a caller (or a test) that rebinds
    # the module global would be silently answered about the real tree
    # instead of its own -- measured while earning the red on this change.
    unknown = unclassified_dirs(PACKS_ROOT)
    if unknown:
        print(
            f"check_pack_landing: {len(unknown)} task-packs/ folder(s) match no "
            "classification in this script -- packs there are checked by NOTHING:"
        )
        for name in unknown:
            print(f"  - task-packs/{name}/")
        print(
            "  Add each to TERMINAL_DIRS, NON_TERMINAL_DIRS or UNSTAMPABLE_DIRS "
            "with the reason.\n"
        )

    # SCOPE before any verdict, and SCANNED NOTHING in place of the all-clear
    # when the population is empty. `Done/` and `Scrapped/` are local-only: on
    # a public checkout every folder walk below runs over nothing and, until
    # 2026-09-22, this printed the same all-clear line as a tree holding 148
    # stamped packs, so a ledger probe shelling out to it read "chore drained"
    # and two live rows graded STRIKE_CANDIDATE (DEF-858). The exit code does
    # not move on an empty population, in either mode: a red on every checkout
    # that lacks a folder it cannot carry is the permanently-red advisory the
    # docstring warns trains dismissal. The line carries the fact instead.
    population = {d: terminal_packs(PACKS_ROOT / d) for d in TERMINAL_DIRS}
    print(
        "check_pack_landing: SCOPE -- "
        + ", ".join(f"{len(v)} pack(s) under task-packs/{d}/" for d, v in population.items())
        + "."
    )
    scanned_nothing = not any(population.values())
    if scanned_nothing:
        # This line speaks for the terminal-State check, whose population is
        # every terminal folder. The two secondary tiers read Done/ ALONE and
        # say so for themselves (`_report_secondary_tiers`): with packs in
        # Scrapped/ and none in Done/ this stays silent while the tiers still
        # walked nothing (both reviewers, 2026-09-22).
        print(
            "  SCANNED NOTHING: no pack under " + "/, ".join(TERMINAL_DIRS) + "/ -- the "
            "terminal-State check ran over an empty population."
        )
        print(
            "  A clean exit here says nothing about the landed packs. Those folders are "
            "local-only (carried on the record branch) and absent on a public checkout; "
            "run this on the development tree that carries them."
        )

    # Scanned across every TERMINAL folder, not just Done/. `Scrapped/` is as
    # finished as `Done/` and owed the same stamp; it went unscanned for as long
    # as the scope was a single hardcoded directory (DEF-624).
    unstamped: list[tuple[str, str | None]] = []
    for _d in TERMINAL_DIRS:
        _dir = PACKS_ROOT / _d
        unstamped += [(f"{_d}/{n}", st) for n, st in unstamped_packs(_dir)]
    if unstamped:
        print(
            f"check_pack_landing: {len(unstamped)} terminal-folder pack(s) missing a terminal "
            "## Landing State: (expected LANDED or SCRAPPED):"
        )
        for name, state in unstamped:
            if state:
                shown = state
            else:
                bold = bold_value_state((PACKS_ROOT / name).read_text(encoding="utf-8"))
                shown = (
                    f"(bold State: value **{bold}** -- write a BARE value; see "
                    ".claude/commands/implement-pack.md)"
                    if bold else "(no State: line)"
                )
            print(f"  - {name}: {shown}")
        print(
            "\nThis is ADVISORY (task-packs/Done/ is gitignored; not a CI gate). "
            "Run with --strict to make this exit non-zero."
        )
    elif not scanned_nothing:
        # The all-clear is a claim about packs that were read; over an empty
        # population the SCANNED NOTHING block above has already spoken.
        print(
            "check_pack_landing: all packs in "
            + "/, ".join(TERMINAL_DIRS) + "/ carry a terminal State: (LANDED/SCRAPPED)."
        )

    # The header-vs-stanza contradiction, reported wherever the pack lives --
    # including task-packs/ root, which no folder scan reaches and which is where
    # the incident that motivated this actually sat.
    contradictions = contradictory_packs(PACKS_ROOT)
    if contradictions:
        print(
            f"\ncheck_pack_landing: {len(contradictions)} pack(s) whose ## Status "
            "says retired while ## Landing does not:"
        )
        for rel, declared, landed in contradictions:
            print(f"  - {rel}: Status={declared}, Landing={landed or '(none)'}")
        print(
            "  A reader sees the header and treats the pack as retired; "
            "/implement-pack keys on the Landing stanza and will still run it."
        )

    _report_secondary_tiers(PACKS_ROOT / TERMINAL_DIRS[0])
    return 1 if (strict and (unstamped or contradictions or unknown)) else 0


def _report_secondary_tiers(done_dir: Path | None = None) -> None:
    """Reported alongside, never folded into the --strict exit code.

    Takes the directory rather than reading the module default, for the same
    reason `main` passes PACKS_ROOT explicitly: a default binds at def time, so
    this reported the REAL tree while every other check in the same run reported
    a fixture. Both halves of a run must be answering about one tree.

    Both tiers are informational: a ROADMAP is legitimately finished, and an
    incomplete field set is a record-quality nit on a pack that DID land. Folding
    either into the gate would put it permanently red again -- the failure mode
    this tool was rescued from.
    """
    done_dir = DONE_DIR if done_dir is None else done_dir
    if not terminal_packs(done_dir):
        # Both tiers read this folder alone; over an empty population they print
        # nothing, which a reader -- and the ledger probe that greps their two
        # headings -- took for "drained". Say it, on a line the probe keys on to
        # refuse its answer (DEF-858). Its own predicate, not `main`'s: Scrapped/
        # holding a pack keeps the all-clear honest and leaves these two walks
        # empty (both reviewers, 2026-09-22).
        print(
            "\n  SCANNED NOTHING: task-packs/Done/ holds no pack -- the ROADMAP tier and "
            "the incomplete-Landing tier ran over an empty population; a clean exit "
            "says nothing about either."
        )
        return
    roadmaps = roadmap_packs(done_dir)
    if roadmaps:
        print(f"\nROADMAP packs in Done/ ({len(roadmaps)}) -- verify their children are drained:")
        for name in roadmaps:
            print(f"  - {name}")

    incomplete = incomplete_landings(done_dir)
    if incomplete:
        print(
            f"\nLANDED packs with an incomplete Landing stanza ({len(incomplete)}) "
            "-- advisory, NOT part of --strict:"
        )
        for name, missing in incomplete:
            print(f"  - {name}: missing {', '.join(missing)}")


if __name__ == "__main__":
    sys.exit(main())
