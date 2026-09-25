#!/usr/bin/env python3
"""Verify what a session writes LAST, after its last verification ran.

``/handoff`` writes the ``ESPALIER_MEMORY.md`` row at step 2, commits at step 5,
and then keeps writing: the working summary at step 6, the goal doc at step 7, the
record snapshot at step 7b. The session's suite ran before ALL of it. So every
handoff artifact lands after the last verification, and nothing re-checks any of
them -- which is how commits that changed no code reddened ``main``.

Measured history, five occurrences:

* Four on ``ESPALIER_MEMORY.md``, a TRACKED file, so each was a real CI red on a
  commit that changed no code. The most recent (``911eb70``) cited a scratch
  directory embedding the running user's home path.
* One on ``task-packs/FORWARD_LEDGER.md`` (2026-09-01), which was gitignored at
  the time (tracked since 2026-09-21), so its tests skipped in CI and the red was
  local-only -- invisible to CI, and present every time the operator ran the suite.

This is the missing re-check. It is deliberately NOT the full suite: at ~14
minutes nobody runs it after a handoff, and a gate nobody runs is not a gate.
The selection below is the subset that has actually caught this class, and it
runs in about twenty seconds on a session that touched no test module,
and about seventy when it did -- the derived-population census is ~48s of the
difference and is run conditionally for exactly that reason.

A fourth arm (2026-09-05, DEF-685) reads the newest ``ESPALIER_MEMORY.md`` row's
cited reflect-candidate keys against ``.espalier/memory_candidate_log.jsonl``:
a handoff had called five keys "logged" that were in no log, and the candidate
pass -- which re-proposes only from the log -- printed none the next session.

Exit codes follow the repo convention: 0 clean, 2 a real violation, 1 a bug in
this script.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The gates that have caught this class, each with the reason it is here. A
# hand-written list CAN stale (docs/FAILURE_MODES.md 13.25 -- a guard whose
# population silently drops to zero reports success forever), so
# ``_resolve_selection`` refuses a name that no longer resolves rather than
# quietly running a shorter list.
SELECTION: dict[str, str] = {
    "tests/test_no_internal_codenames.py":
        "machine-local paths in tracked files -- the 911eb70 red, 4 occurrences",
    "tests/test_no_provenance_in_shipped_code.py":
        "internal build-history ids on shipping surfaces",
    "tests/test_adopter_verb_stand_down.py":
        "the provenance census must not stand down on self-host",
    "tests/test_forward_ledger_completeness.py":
        "ledger row obligations -- counts, index, probes (2026-09-01 red)",
    "tests/test_catalog_self_consistency.py":
        "symbol anchors into rotating hosts",
    "tests/test_adopter_pointer_resolution.py":
        "pointers to files absent from an adopter tree",
    "tests/test_documented_claims.py":
        "changelog structure + internal ids in [Unreleased]",
    "tests/test_doc_source_citations.py":
        "citation rot on non-record doc surfaces",
    "tests/test_deploy_doc_parity.py":
        "docs/ vs its shipped mirror",
    "tests/test_check_memory_md_tag_parity.py":
        "every released tag is narrated somewhere tracked",

    # ---- REGISTRATION obligations -------------------------------------------
    # The ten members above are CONTENT-DRIFT gates, and that is not a
    # coincidence: this selection was originally derived from the artifacts
    # /handoff writes last, so it could see only the class it was derived from.
    # Measured 2026-09-01: of the nine gates that caught something real in the
    # session that built this file, FOUR were outside it -- and all four fire on
    # what a session ADDS rather than on what it rewrites. A population derived
    # from one failure mode is blind to the others (STANDING_PRINCIPLES 17, and
    # docs/FAILURE_MODES.md 18.4). Each entry below earned its place by actually
    # catching something that day, which is the bar for adding one.
    "tests/test_test_suite_contract.py":
        "a new test module's marker + slow classification (caught twice, ~5.2s)",
    "tests/test_scanner_subprocess_contracts.py":
        "the subprocess-contract pragma budget (~2.3s)",
    "tests/test_check_ledger_probes.py":
        "a probe pinning a line-number-shaped value (~0.4s)",
}

#: Members that run ONLY when the session touched something they could fire on.
#: ``{path: (reason, trigger prefixes)}``.
#:
#: The first member is here for a measured reason: it is 47.7s of what would
#: otherwise be a 68s gate -- 70% of the runtime -- and it can only fire when a
#: test module's derived-population loops change or the census map itself is
#: edited. On a docs-only session it is 47.7s that cannot catch anything.
#:
#: ⚠ NOT swapped for the cheaper script, and the measurement is why. Running
#: ``scripts/derived_population_census.py`` directly costs 15.8s instead of
#: 47.7s, and it MISSES what the module catches: driven 2026-09-01, corrupting
#: ``ADJUDICATED_FILE_COUNT`` leaves the script at rc 0 while the module reds.
#: The script is cheaper because it checks less -- it runs the health arm but
#: not the paired-literal contract, which caught this author twice in one
#: session. Cheaper is only better when it catches the same thing.
CONDITIONAL: dict[str, tuple[str, tuple[str, ...]]] = {
    "tests/test_derived_population_census.py": (
        "a new derived population with no adjudicated entry, and the paired "
        "counts drifting from the map (~47.7s)",
        ("tests/", "scripts/derived_population_census.py"),
    ),
    # The second member is the opposite shape: about a second, and it fires
    # on the commit every /handoff makes. The recall engine's pasted counts
    # (corpus size, heading arm, stripped arm) age when the corpus grows, and
    # measured 2026-09-09 a memory commit pushed all three past the count band
    # then in force with nothing red until the full tier three commits later
    # (STANDING_PRINCIPLES 17: the expensive net caught it, so the catch moves
    # earlier). The band is tests/_recall_pins.py's: the larger of five
    # documents or a tenth of the pasted value, so a re-paste is owed when the
    # corpus has materially grown, not on every note. The triggers are the corpus roots
    # tools/cc/hooks/_recall.py::_iter_corpus reads -- the module itself checks
    # that no corpus root sits outside them -- plus the three pasted sites, so
    # a wrong re-paste is caught by the same member.
    "tests/test_recall_pasted_counts.py": (
        "the three pasted recall counts drifting past their band (5 documents "
        "or 10% of the pasted value) when the corpus grows (~1s)",
        ("memory/", "docs/SHARP_EDGES.md", "docs/sharp-edges/",
         "docs/STANDING_PRINCIPLES.md", "docs/FAILURE_MODES.md",
         "tools/cc/hooks/_recall.py", "scripts/recall_eval.py",
         ".claude/commands/recall.md"),
    ),
}

# Where the co-author trailer convention is written down. Parsed rather than
# restated, so this script cannot disagree with the canon it enforces.
CANON_DOC = "memory/task-packs.md"
_CANON_RE = re.compile(r"`(Co-Authored-By:[^`]+)`")


def _session_changed_paths() -> list[str] | None:
    """Repo-relative paths this session touched, or ``None`` if git cannot say.

    ⚠ ``None`` MEANS RUN EVERYTHING. An undeterminable condition must never read
    as "nothing to do". That is the precise bug this gate shipped with on
    2026-09-01: its first probe defaulted git's output instead of reading git's
    exit status, so a repository with no ``origin`` reported a live item DONE.
    A conditional member is the same shape with a bigger blast radius -- a
    silently-skipped gate looks exactly like a passing one.

    Union of the unpushed commits and the working tree, because at handoff the
    commit has already happened (step 5) but later steps are still writing.
    """
    # Two LITERAL argvs rather than a loop over a tuple of them. The loop form
    # reads as a dynamic argv to the subprocess-contract scanner, which then
    # wants a pragma -- and that budget is a deliberate ratchet. Written out, each
    # call is pinnable and costs nothing.
    try:
        committed = subprocess.run(
            ["git", "diff", "--name-only", "origin/HEAD...HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        working = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if committed.returncode != 0 or working.returncode != 0:
        return None

    paths: set[str] = set()
    for line in committed.stdout.splitlines():
        if line.strip():
            paths.add(line.strip())
    for line in working.stdout.splitlines():
        # `status --porcelain` prefixes a two-character status code.
        stripped = line[3:].strip() if len(line) > 3 else line.strip()
        if stripped:
            paths.add(stripped)
    return sorted(paths)


def _conditional_members() -> tuple[list[str], list[str]]:
    """``(members to run, human-readable notes)``."""
    changed = _session_changed_paths()
    run, notes = [], []
    for path, (why, triggers) in CONDITIONAL.items():
        if not (REPO_ROOT / path).is_file():
            notes.append(f"{path}: SKIPPED, no longer present")
            continue
        if changed is None:
            run.append(path)
            notes.append(f"{path}: RUN (git could not report changed paths -- "
                         "an unanswerable condition runs the gate)")
            continue
        hit = [c for c in changed if any(c.startswith(t) for t in triggers)]
        if hit:
            run.append(path)
            notes.append(f"{path}: RUN ({len(hit)} changed path(s) match)")
        else:
            notes.append(f"{path}: skipped, nothing touched {triggers} -- {why}")
    return run, notes


def _resolve_selection() -> list[str]:
    """The selection, or raise if any member has moved."""
    missing = [p for p in SELECTION if not (REPO_ROOT / p).is_file()]
    if missing:
        raise SystemExit(
            "check_handoff_landing: these gates no longer resolve, so the "
            "selection would silently run short:\n  "
            + "\n  ".join(missing)
            + "\nRe-point SELECTION at where they moved -- do not just delete "
              "the row, or the class it covers stops being checked."
        )
    return list(SELECTION)


def canonical_trailer() -> str | None:
    """The one trailer ``memory/task-packs.md`` declares, or None."""
    doc = REPO_ROOT / CANON_DOC
    if not doc.is_file():
        return None
    hits = _CANON_RE.findall(doc.read_text(encoding="utf-8"))
    return hits[0].strip() if len(hits) == 1 else None


def check_trailer(rev: str = "HEAD") -> list[str]:
    """Problems with ``rev``'s co-author trailer, as human-readable lines."""
    want = canonical_trailer()
    if want is None:
        return [
            f"{CANON_DOC} does not declare exactly one `Co-Authored-By: ...` "
            "trailer, so there is nothing to enforce. Declare one."
        ]
    try:
        body = subprocess.run(
            ["git", "log", "-1", "--format=%B", rev],
            cwd=REPO_ROOT, capture_output=True, text=True,
            # errors="replace" matches the probe runner next door. A commit body
            # under a non-UTF-8 i18n.commitEncoding otherwise raises
            # UnicodeDecodeError, which the except clause below does not cover --
            # the gate would traceback instead of reporting.
            encoding="utf-8", errors="replace", check=True,
        ).stdout
    except (subprocess.CalledProcessError, OSError) as exc:
        return [f"could not read {rev}: {exc}"]
    found = [ln.strip() for ln in body.splitlines()
             if ln.startswith("Co-Authored-By:")]
    if not found:
        return [f"{rev} carries no Co-Authored-By trailer; canon is `{want}`"]
    wrong = [f for f in found if f != want]
    if wrong:
        return [f"{rev} trailer is `{w}`; canon ({CANON_DOC}) is `{want}`"
                for w in wrong]
    return []


#: The live owed-list and its probes. Both are gitignored session state, so a
#: repo without them simply skips this arm -- as with ``cc/GOAL.md`` itself.
GOAL_DOC = "cc/GOAL.md"
OWED_PROBES = "cc/GOAL_OWED.json"


def _probe_runner():
    """The sibling probe runner, or None.

    REUSED, not reimplemented. ``scripts/check_ledger_probes.py`` already runs
    exactly this schema (`cmd` / `open_value` / `why_not`, plus the optional
    footing keys `subject` and `inputs`: an owed item whose command reads a
    local-only path names it in `inputs`, or a checkout without that path
    grades the item DONE -- DEF-858) and is hardened in ways
    a second copy would have to re-earn: it splits with ``shlex`` and never uses a
    shell, treats an erroring probe as UNRESOLVED rather than as a fixed defect,
    and reads the LAST stdout line so a chatty probe does not compare unequal by
    accident. Writing a second runner also spent a
    ``# subprocess-contract: ok`` pragma, and that budget is a deliberate ratchet
    -- reuse keeps it closed instead of raising the cap for a duplicate.
    """
    try:
        import importlib.util
        path = Path(__file__).resolve().parent / "check_ledger_probes.py"
        if not path.is_file():
            return None
        spec = importlib.util.spec_from_file_location("_clp_runner", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:          # pragma: no cover - defensive
        return None


_OWED_MARKER = re.compile(r"<!--\s*owed:([\w.-]+)\s*-->")


def _goal_owed_ids(text: str) -> list[str | None]:
    """Identity of each top-level bullet under ``## Still owed``, in order.

    ``None`` marks a bullet carrying no ``<!--owed:id-->`` marker.

    BOTH bullet spellings are accepted. Counting only ``- `` made the check fail
    OPEN: a ``* `` bullet -- equally valid CommonMark -- was invisible, so an
    unprobed item passed silently while the goal doc claimed the gate would red.
    An under-count is the unsafe direction here, because the missing bullet is
    exactly the unchecked one.

    Identity, not cardinality. Equal counts do not mean correspondence: step 7
    rewrites the bullets and the probes in one pass, so a deleted item plus a
    new one keeps the count and silently re-points the survivor's probe at prose
    that no longer describes it -- the original laundering failure, one layer up.
    """
    out: list[str | None] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## Still owed"
            continue
        if inside and (line.startswith("- ") or line.startswith("* ")):
            m = _OWED_MARKER.search(line)
            out.append(m.group(1) if m else None)
    return out


def check_owed() -> list[str]:
    """Owed items that have actually landed, plus list/probe divergence.

    THE FAILURE THIS EXISTS FOR, measured 2026-08-31: an item that had landed
    3h20m earlier was written into the session record as "still owed", copied
    into the goal doc, injected at every SessionStart, and believed for two
    sessions. The handoff instruction meant to prevent it prescribed
    ``git log origin/<branch>..<branch>`` -- an UNPUSHED-only range -- and the
    item had landed in a PUSHED commit, so the prescribed check could not see
    it. A commit-range oracle answers "what changed recently"; an owed-list
    needs "is this done". These probes ask the second question.
    """
    goal = REPO_ROOT / GOAL_DOC
    probes_path = REPO_ROOT / OWED_PROBES
    if not goal.is_file() and not probes_path.is_file():
        return []  # repo keeps no goal doc -- nothing to check
    problems: list[str] = []
    if goal.is_file() and not probes_path.is_file():
        return [f"{GOAL_DOC} has an owed-list but {OWED_PROBES} is absent, so no "
                "owed item is re-derived. That is exactly how a landed item "
                "survives as 'owed' across sessions."]
    try:
        data = json.loads(probes_path.read_text(encoding="utf-8"))
        owed = data["owed"]
    except (OSError, ValueError, KeyError) as exc:
        return [f"{OWED_PROBES} is unreadable: {exc}"]

    # Both limbs the sibling runner was BURNED into growing, carried across
    # deliberately: a declared count that disagrees with the list, and an empty
    # list. Zero probes is indistinguishable from zero stale items, which is the
    # false green this whole file exists to stop.
    declared = data.get("_count")
    if isinstance(declared, int) and declared != len(owed):
        problems.append(
            f"{OWED_PROBES} declares _count={declared} but carries {len(owed)} "
            "entries. Re-derive the cell from the list."
        )
    if not owed:
        problems.append(
            f"{OWED_PROBES} declares no owed items at all. Zero probes is "
            "indistinguishable from zero stale items -- if nothing is owed, say "
            f"so in {GOAL_DOC} and remove this file."
        )

    if goal.is_file():
        ids = _goal_owed_ids(goal.read_text(encoding="utf-8"))
        unmarked = sum(1 for i in ids if i is None)
        if unmarked:
            problems.append(
                f"{GOAL_DOC} has {unmarked} owed bullet(s) with no "
                "`<!--owed:id-->` marker, so they correspond to no probe and are "
                "unchecked."
            )
        elif ids != [i.get("id") for i in owed]:
            problems.append(
                f"{GOAL_DOC} owed bullets {ids} do not match {OWED_PROBES} ids "
                f"{[i.get('id') for i in owed]}. Same items, same order -- equal "
                "counts alone would let a swapped bullet inherit another item's "
                "probe."
            )

    runner = _probe_runner()
    if runner is None:
        return problems + [
            "scripts/check_ledger_probes.py could not be loaded, so no owed item "
            "was re-derived. That is an UNCHECKED owed-list, not a clean one."
        ]

    for item in owed:
        oid = item.get("id", "?")
        if item.get("cmd") == "":
            problems.append(
                f"owed item {oid!r} has an EMPTY `cmd`. That is a broken probe "
                "wearing the shape of a declared one -- set a real command or "
                "remove `cmd` and state `why_not`."
            )
            continue
        if not item.get("cmd") and not item.get("why_not"):
            problems.append(
                f"owed item {oid!r} has neither a `cmd` nor a `why_not`. Declare "
                "why it has no local oracle -- there is no third option."
            )
            continue
        verdict, detail = runner.run_probe(item)
        if verdict == runner.STRIKE_CANDIDATE:
            problems.append(
                f"owed item {oid!r} looks DONE -- {detail}. CONFIRM, then remove "
                f"its bullet from {GOAL_DOC} and its entry here. This is a "
                "candidate needing a human, not a verdict: a probe can print the "
                "wrong thing for reasons that have nothing to do with the work."
            )
        elif verdict == runner.UNRESOLVED:
            problems.append(
                f"owed item {oid!r} could not be re-derived ({detail}). A probe "
                "that errors is not a probe that says DONE."
            )
    return problems


#: The memory row is the LAST thing a handoff writes, and the candidate log is
#: the only place a reflect candidate survives the session gap (DEF-685).
MEMORY_DOC = "ESPALIER_MEMORY.md"
CANDIDATE_LOG = ".espalier/memory_candidate_log.jsonl"

# A Session Log row begins `| YYYY-MM-DD`; recency is the date the row CARRIES,
# never its position -- the rule session_start.py's digest and
# cli.py::cmd_memory_prune both arrived at after reading position as recency.
_MEMORY_DATE_RE = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})")
_HEX12_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{12}(?![0-9a-fA-F])")
# A 12-hex token is read as a candidate key only in the company of a word a
# handoff uses when it makes a claim about the candidate log: the base words
# below PLUS every disposition name the pass reads, so "promoted 8c0c57061b76"
# is a claim and the vocabulary cannot lag the enumeration. Without the window
# every ledger `row_sha` and long commit abbreviation in a row would be read as
# a key; known row_sha values and resolvable commits are excluded outright.
# Stated heuristic, both failure directions named: a key cited with none of
# these words is not checked; a hex token cited beside one of them that is
# neither a commit this clone resolves nor a known row_sha reads as a red whose
# message names the way out (`--skip-keys`, or keep the words apart).
_KEY_CONTEXT_BASE = ("key", "keys", "candidate", "candidates", "logged",
                     "proposal", "proposals", "promotion", "promotions",
                     "disposition", "dispositioned", "reflect")
_KEY_CONTEXT_WINDOW = 160
_SCRIPT_REPO = Path(__file__).resolve().parent.parent
_LEDGER_PROBES = "task-packs/LEDGER_PROBES.json"


def _dispositions() -> "frozenset[str] | None":
    """The disposition names the candidate pass READS -- loaded from the pass,
    never restated here, so a fifth disposition reaches this gate the day it
    lands. None when the hook-side module cannot be loaded."""
    try:
        import importlib.util
        path = _SCRIPT_REPO / "tools" / "cc" / "reflect_protocol.py"
        spec = importlib.util.spec_from_file_location("_chl_reflect_protocol", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return frozenset(mod.RESOLVED_DISPOSITIONS) | {mod.HELD_DISPOSITION}
    except Exception:  # noqa: BLE001 -- reported by the caller as a problem
        return None


def _key_context_re(dispositions: "frozenset[str]") -> "re.Pattern[str]":
    words = sorted(set(_KEY_CONTEXT_BASE) | set(dispositions))
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b",
                      re.IGNORECASE)


def _session_log_lines(text: str) -> list[str]:
    """The lines under ``## Session Log`` up to the next ``## `` heading, or the
    whole file when the heading is absent. Scoped so a dated row in a Harness
    Decisions table (the adopter template carries one) cannot win the scan."""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.strip() == "## Session Log"]
    if not starts:
        return lines
    out: list[str] = []
    for ln in lines[starts[0] + 1:]:
        if ln.startswith("## "):
            break
        out.append(ln)
    return out


def _newest_memory_row(text: str) -> str | None:
    """The Session Log row carrying the newest date, or None when none is dated.

    Not clamped to today: a wall-clock inside a gate is its own defect, and the
    suite already reds a future-dated row (``test_no_session_log_row_is_future_dated``).
    An unpadded or space-led date is invisible here exactly as it is to the
    banner digest, which reads the same anchor."""
    dated = []
    for ln in _session_log_lines(text):
        m = _MEMORY_DATE_RE.match(ln)
        if m:
            dated.append((m.group(1), ln))
    if not dated:
        return None
    # A stable sort on the date STRING: equal dates keep file order, and
    # `/handoff` prepends, so the topmost same-day row is the newest.
    return sorted(dated, key=lambda pair: pair[0], reverse=True)[0][1]


def _cited_candidate_keys(row: str, context: "re.Pattern[str]") -> list[str]:
    """12-hex tokens in ``row`` within the window of a candidate-log word, in order."""
    out: list[str] = []
    for m in _HEX12_RE.finditer(row):
        lo = max(0, m.start() - _KEY_CONTEXT_WINDOW)
        hi = m.end() + _KEY_CONTEXT_WINDOW
        if context.search(row[lo:hi]) and m.group(0) not in out:
            out.append(m.group(0))
    return out


def _known_row_shas() -> "set[str]":
    """Every ``row_sha`` the ledger probes carry -- 12-hex by construction and
    routinely discussed in a handoff row -- so none is mistaken for a key."""
    path = REPO_ROOT / _LEDGER_PROBES
    if not path.is_file():
        return set()
    try:
        probes = json.loads(path.read_text(encoding="utf-8")).get("probes", [])
    except (OSError, ValueError, AttributeError):
        return set()
    return {p.get("row_sha") for p in probes
            if isinstance(p, dict) and isinstance(p.get("row_sha"), str)}


def _is_commit(token: str) -> bool:
    """True when ``token`` abbreviates a commit of this repo -- the one other
    12-hex population a memory row cites. Any failure reads as "not a commit",
    so an unresolvable token is checked rather than waved through."""
    try:
        return subprocess.run(
            ["git", "cat-file", "-e", f"{token}^{{commit}}"],
            cwd=REPO_ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _logged_keys() -> "dict[str, str] | None":
    """Every ``key`` in the candidate log mapped to its LAST disposition (any
    string, so the caller can tell "present but unreadable" from "absent");
    None when the log does not exist on this tree."""
    log = REPO_ROOT / CANDIDATE_LOG
    if not log.is_file():
        return None
    keys: dict[str, str] = {}
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a torn append is not a missing key -- see _unreadable_log_text
        if isinstance(row, dict) and isinstance(row.get("key"), str):
            d = row.get("disposition")
            keys[row["key"]] = d if isinstance(d, str) else ""
    return keys


def _unreadable_log_text() -> str:
    """The log's lines that are NOT JSON, joined -- so a cited key that sits in
    a torn row is reported as unreadable rather than absent. The candidate
    pass skips such a line (never fatal) and so re-proposes the key as
    undecided (DEF-764); the fix is a rewrite, not an append."""
    log = REPO_ROOT / CANDIDATE_LOG
    if not log.is_file():
        return ""
    torn: list[str] = []
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            json.loads(line)
        except ValueError:
            torn.append(line)
    return "\n".join(torn)


def check_candidate_keys(notes: "list[str] | None" = None) -> list[str]:
    """Cited reflect-candidate keys that have no row in the candidate log.

    THE FAILURE THIS EXISTS FOR, measured 2026-09-05 (DEF-685): a handoff row
    cited five 12-hex keys as "logged as proposals, not promoted". Zero were in
    the log -- the pass had printed them and nothing had written them. The
    candidate pass re-proposes only from the log, and the lineage walk forgets
    a blueprint past the session gap, so the next session's pass printed
    `MEMORY CANDIDATES: none` and the two lessons the row called promotable
    survived only as prose. A key in the memory row is a claim about a file;
    this arm reads the file. Only the NEWEST row is read: an older row's dead
    key is history, and editing a record to satisfy a checker falsifies it.

    A key that IS in the log but under a disposition the pass cannot read
    (``hold``, ``HOLD --``, ``Held``) is the same defect with a row present --
    not suppressed, not re-proposed, out of the skip-rate -- so presence alone
    never satisfies this arm; the disposition must be one the pass reads.

    An ABSENT log is a note, not a red (``notes`` collects it): the log is
    machine-local and gitignored, so a fresh clone or a second worktree cannot
    verify a claim the authoring tree logged, and a red there would ask the
    author to falsify the record or the log. The false claim this arm exists
    for had a log present and rows missing.

    Scope, stated: ``cc/_working_summary.md`` restates the row and is not read
    here -- it is rewritten at every boundary from the session, and a session
    that reads a stale claim there also reads the row, which is checked.
    """
    doc = REPO_ROOT / MEMORY_DOC
    if not doc.is_file():
        return []  # repo keeps no memory doc -- nothing to check
    row = _newest_memory_row(doc.read_text(encoding="utf-8", errors="replace"))
    if row is None:
        return []
    dispositions = _dispositions()
    if dispositions is None:
        return ["could not load the disposition enumeration from "
                "tools/cc/reflect_protocol.py, so no cited candidate key can be "
                "checked against what the pass reads."]
    context = _key_context_re(dispositions)
    known_shas = _known_row_shas()
    cited = [tok for tok in _cited_candidate_keys(row, context)
             if tok not in known_shas and not _is_commit(tok)]
    if not cited:
        return []
    logged = _logged_keys()
    if logged is None:
        if notes is not None:
            notes.append(
                f"{CANDIDATE_LOG} is absent on this tree, so the {len(cited)} "
                f"candidate key(s) the newest {MEMORY_DOC} row cites cannot be "
                "verified here -- the log is machine-local; run this on the tree "
                "that logged them, or pass --skip-keys."
            )
        return []
    readable = " / ".join(sorted(dispositions))
    torn = _unreadable_log_text()
    problems: list[str] = []
    for tok in cited:
        if tok not in logged and tok in torn:
            problems.append(
                f"{MEMORY_DOC}'s newest row cites candidate key `{tok}` and the "
                f"only {CANDIDATE_LOG} row carrying it does not parse as JSON (a "
                "torn or multi-line append). The candidate pass skips that line "
                "and re-proposes the key as undecided, so the disposition is lost "
                "exactly as if the row were missing. Rewrite it as ONE json.dumps "
                "line for the key."
            )
        elif tok not in logged:
            problems.append(
                f"{MEMORY_DOC}'s newest row cites candidate key `{tok}` and "
                f"{CANDIDATE_LOG} has no row for it. A cited key must be a log row "
                f"({readable}): the candidate pass re-proposes only from the log, "
                "so a key that lives in prose evaporates past the session gap "
                "(DEF-685). Append the row, or drop the citation. If this token is "
                "a ledger row_sha or a commit this clone cannot resolve, it is not a "
                "candidate key: keep candidate words further than "
                f"{_KEY_CONTEXT_WINDOW} characters from it, or re-run with --skip-keys."
            )
        elif logged[tok] not in dispositions:
            problems.append(
                f"{MEMORY_DOC}'s newest row cites candidate key `{tok}`, and "
                f"{CANDIDATE_LOG} holds it under disposition `{logged[tok]}`, which "
                f"the candidate pass cannot read (it reads {readable}): not "
                "suppressed, not re-proposed, out of the skip-rate -- the hold is "
                "lost exactly as if the row were missing. Append a row with a "
                "readable disposition."
            )
    return problems


#: The codename gate's local pattern arm (DEF-708). Gitignored and classified
#: local_only, so it exists only where the operator put it.
LOCAL_CODENAMES = ".local-codenames.txt"


def _local_codename_patterns(path: Path) -> list[str]:
    """The non-comment, non-blank lines of the local arm.

    The gate module (``tests/test_no_internal_codenames.py``) owns the format;
    this restates only the two skip rules and the ``utf-8-sig`` read (a BOM
    must not count as a pattern), because importing a test module here would
    drag pytest into a handoff script.
    """
    return [ln.strip() for ln in path.read_text(encoding="utf-8-sig").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def check_local_codename_arm(notes: "list[str] | None" = None) -> list[str]:
    """The stressor must exist before its green means anything.

    ``tests/test_no_internal_codenames.py`` reads the operator's own terms from
    a gitignored root file and runs on the tracked list alone when the file is
    absent -- so on a fresh clone, a second worktree, or a machine that never
    had the file, the gate is green for every term that lives only there, and
    nothing in the suite can tell "not armed" from "nothing to enforce". A
    file present but holding only comments is the same silent green with a
    file on disk.

    A red only where this is the operator's tree -- the tell is the one the
    owed-list arm already keys on, a goal doc at ``cc/GOAL.md`` (gitignored,
    written by ``/handoff``). Anywhere else -- a contributor's clone of the
    public repo running ``/commit``, a reviewer's shared clone, the Windows
    walk worktree -- the absence is a printed note, the shape
    ``check_candidate_keys`` uses for its machine-local log, because the file's
    content is by construction not theirs to recreate. A file that exists but
    cannot be read is a red everywhere: the gate module raises on it too. The
    clean path reports the armed count, so a file truncated to one line is
    visible where a 0-or-more check would read clean.
    """
    path = REPO_ROOT / LOCAL_CODENAMES
    operator_tree = (REPO_ROOT / GOAL_DOC).is_file()

    def _report(problem: str) -> list[str]:
        if operator_tree:
            return [problem]
        if notes is not None:
            notes.append(f"{problem} (a note, not a red: this tree keeps no "
                         f"{GOAL_DOC}, so it is not the operator's)")
        return []

    if not path.is_file():
        return _report(
            f"{LOCAL_CODENAMES} is absent, so the codename gate ran on its tracked "
            "list alone and every term the operator keeps only there is "
            "unenforced on this tree. Recreate it -- memory/local-codename-arm.md "
            "says how -- before trusting the green, or pass --skip-local-arm on a "
            "tree that is not the operator's."
        )
    try:
        patterns = _local_codename_patterns(path)
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{LOCAL_CODENAMES} is unreadable ({type(exc).__name__}); the "
                "gate module raises on it too."]
    if not patterns:
        return _report(
            f"{LOCAL_CODENAMES} carries no patterns (comments and blank lines "
            "only), so the local arm is off with the file present -- the same "
            "silent green as an absent file."
        )
    if notes is not None:
        notes.append(f"local arm: {len(patterns)} pattern(s) from {LOCAL_CODENAMES}")
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rev", default="HEAD",
                    help="commit whose trailer is checked (default: HEAD)")
    ap.add_argument("--skip-tests", action="store_true",
                    help="check only the trailer")
    ap.add_argument("--skip-trailer", action="store_true",
                    help="run only the gate selection")
    ap.add_argument("--skip-owed", action="store_true",
                    help="do not re-derive the goal doc's owed-list")
    ap.add_argument("--skip-keys", action="store_true",
                    help="do not resolve the memory row's cited candidate keys "
                         "against the candidate log")
    ap.add_argument("--skip-local-arm", action="store_true",
                    help="do not require the codename gate's local pattern file "
                         "(a tree that is not the operator's)")
    args = ap.parse_args(argv)

    problems: list[str] = []

    if not args.skip_tests:
        selection = _resolve_selection()
        extra, notes = _conditional_members()
        for note in notes:
            print(f"  conditional: {note}", flush=True)
        selection = selection + extra
        print(f"check_handoff_landing: {len(selection)} gates", flush=True)
        # A member that collects ZERO tests is the 13.25 shape the selection is
        # supposed to be immune to: `is_file()` still passes, the aggregate stays
        # green, and the class silently stops being covered. One member of this
        # set skips wholesale when the ledger is absent, which is the standing
        # state in CI -- so this is a live configuration, not a hypothetical.
        for member in selection:
            probe = subprocess.run(
                [sys.executable, "-m", "pytest", member, "--collect-only", "-q",
                 "-p", "no:cacheprovider"],
                cwd=REPO_ROOT, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            if " tests collected" not in probe.stdout and "test" not in probe.stdout:
                problems.append(
                    f"{member} collects no tests, so it contributes nothing to "
                    "this gate while still looking like coverage."
                )
        run = subprocess.run(
            [sys.executable, "-m", "pytest", *selection, "-q"],
            cwd=REPO_ROOT,
        )
        if run.returncode != 0:
            problems.append(
                f"the post-handoff gate selection failed (pytest exit "
                f"{run.returncode}). These run in ~20-70s and cover what a session "
                "writes AFTER its suite ran -- read the failures above; they are "
                "about the handoff's own artifacts, not about code."
            )

    if not args.skip_trailer:
        problems.extend(check_trailer(args.rev))

    if not args.skip_owed:
        problems.extend(check_owed())

    if not args.skip_keys:
        key_notes: list[str] = []
        problems.extend(check_candidate_keys(key_notes))
        for note in key_notes:
            print(f"  note: {note}", flush=True)

    if not args.skip_local_arm:
        arm_notes: list[str] = []
        problems.extend(check_local_codename_arm(arm_notes))
        for note in arm_notes:
            print(f"  note: {note}", flush=True)

    if problems:
        print("\ncheck_handoff_landing: NOT CLEAN", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2
    if (args.skip_tests and args.skip_trailer and args.skip_owed and args.skip_keys
            and args.skip_local_arm):
        print("check_handoff_landing: NOTHING CHECKED -- every arm was skipped",
              file=sys.stderr)
        return 2
    print("check_handoff_landing: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
