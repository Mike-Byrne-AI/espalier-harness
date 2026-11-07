"""The ledger's content rules, as predicates the tests and the ledger verb share.

A row that breaks one of these rules was written, converged, and redded only in
the contract tier afterwards, because the rules lived in test methods alone:
each red cost a ``repin --text-file`` and another tier run (DEF-1121, hit on
2026-09-29 and 2026-10-03). The predicate now lives here once. The tests that
own each rule call it over the tracked tree, and ``tools/cc/ledger_row.py``
loads this file from the tree it writes into and calls :func:`breaks` over the
drafted row before it writes, and in its dry run, naming the rule by the test
that owns it. A tree without this file (an adopter's) runs no rule, since the
rules are this repository's own.

Stdlib and the suite's light helpers only, never pytest at import: the verb
imports it outside a test session. Five rules run. Over the drafted row's text:
the maintenance switch named beside two or more of its bypass hooks but not all
(``TestBypassRosterCarriers``), a restated memory line cap
(``TestMemoryCapPopulation``), and a cited production-source path or symbol
the tree does not hold (``TestDocSourceCitations``). Over the drafted probe:
the probe-shape ratchet's two rules (``TestProbeShapesAreRatcheted``), a probe
that reads text out of its own subject and one whose program spawns a bare
interpreter, each with its per-id baseline, which lives here. The cited-path
rule calls its finder where it lives, in a test module that imports pytest,
and only when that rule runs: its resolver's caches and root are globals the
sibling module's own tests patch, so moving it would leave those patches
patching nothing. Where it cannot run, the others still do and it says so.
Not run here: a pack id the tree cannot resolve and a relative link the
release archive does not hold, whose baselines are locals of their tests'
bodies or whose presence is an extracted archive's (DEF-1121's successor row).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Callable, Iterable

_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = _ROOT / "tools" / "cc" / "hooks"

#: The owning test of each rule, the name a break is reported under.
BYPASS_ROSTER_RULE = "tests/test_maintenance_mode.py::TestBypassRosterCarriers"
MEMORY_CAP_RULE = "tests/test_documented_claims.py::TestMemoryCapPopulation"
CITED_PATH_RULE = "tests/test_doc_source_citations.py::TestDocSourceCitations::test_every_source_citation_resolves"
PAPERWORK_PROBE_RULE = ("tests/test_check_ledger_probes.py::TestProbeShapesAreRatcheted::"
                        "test_no_new_probe_is_satisfiable_by_its_own_fixs_paperwork")
LITERAL_SPAWN_RULE = ("tests/test_check_ledger_probes.py::TestProbeShapesAreRatcheted::"
                      "test_no_new_probe_spawns_a_literal_interpreter_inside_its_program")


def maintenance_bypass_callers(hooks_dir: Path = HOOKS_DIR,
                               listing: Callable[[Path, str], Iterable[Path]] | None = None) -> set[str]:
    """DERIVED, not enumerated: every hook module whose SOURCE calls
    ``_maintenance_mode.is_active`` -- the logging bypass entry point -- through
    any spelling of the import (``_maintenance_mode.is_active(...)``, an
    ``import _maintenance_mode as mm`` alias, or ``from _maintenance_mode import
    is_active``). An AST walk, so a docstring or comment that merely mentions the
    name does not count. Readers of the raw predicate or of ``ENV_VAR`` (the
    session-start warning, ``_explain_path``'s explanation) are not bypasses: a
    hook that early-returned on those would be a bypass that never logs, which
    the helper's own contract forbids. ``listing`` lists the hook files; the
    default is git's view of the checkout (``tests/_live_tree.py``), so an
    untracked scratch hook is never read."""
    if listing is None:
        from tests._live_tree import checkout_glob as listing
    callers: set[str] = set()
    paths = listing(hooks_dir, "*.py")
    for path in sorted(paths):
        if path.name == "_maintenance_mode.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_aliases = {"_maintenance_mode"}
        bare_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "_maintenance_mode":
                        module_aliases.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module == "_maintenance_mode":
                for alias in node.names:
                    if alias.name == "is_active":
                        bare_names.add(alias.asname or alias.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "is_active"
                and isinstance(func.value, ast.Name)
                and func.value.id in module_aliases
            ) or (isinstance(func, ast.Name) and func.id in bare_names):
                callers.add(path.stem)
    return callers


def roster_units(text: str) -> Iterable[str]:
    """Roster-claim units: each markdown table row on its own, otherwise a
    blank-line-separated paragraph (a table is one paragraph, but each row scopes
    one thing)."""
    for para in re.split(r"\n\s*\n", text):
        lines = para.splitlines()
        if lines and all(line.lstrip().startswith("|") for line in lines if line.strip()):
            yield from lines
        else:
            yield para


# Units that name the env var and two or more roster hooks WITHOUT being a
# statement of what the flag bypasses. Each entry is (tracked path, a substring
# of the unit) with its reason; the sweep asserts every entry still matches, so
# a stale exclusion reds instead of silently widening the blind spot.
NOT_A_ROSTER_CLAIM = (
    (".claude/commands/implement-pack.md", "enforce protected-zone and plan-required"),  # a guard explainer plus the relaunch line
    ("bench/README.md", "A caveat the numbers do not carry"),  # a dated measurement narrative
    ("docs/HOOKS.md", "Every gate block also lands one record"),  # which hooks WRITE an audit record on bypass; subagent_stop writes none
    ("docs/SURFACE_SUPPORT_MATRIX.md", "Main session Write/Edit/NotebookEdit"),  # one surface's guards, "hard-blocked unless" the flag; not the flag's roster
    ("task-packs/FORWARD_LEDGER.md", "write_guard and plan_guard driven with"),  # DEF-992's driven evidence: which hooks were run with the padded value, not which bypass
)


def partial_rosters(rel: str, text: str, callers: set[str]) -> list[tuple[str, set[str], tuple[str, str] | None]]:
    """Each unit of ``text`` (the file at ``rel``) that names the maintenance
    switch and two or more of ``callers`` but not all of them, with the names
    it omits and the exclusion that covers it, or None. An exclusion naming the
    ledger file covers its rows wherever they live (a file each under
    task-packs/ledger.d/ since the fold)."""
    from tests._record_paths import is_ledger_record

    found = []
    for unit in roster_units(text):
        if "MAINTENANCE_MODE" not in unit:
            continue
        named = {n for n in callers if re.search(rf"\b{re.escape(n)}\b", unit)}
        if len(named) < 2 or named == callers:
            continue
        excl = next(((p, sub) for p, sub in NOT_A_ROSTER_CLAIM
                     if (p == rel or (p == "task-packs/FORWARD_LEDGER.md" and is_ledger_record(rel)))
                     and sub in unit), None)
        found.append((unit, callers - named, excl))
    return found


#: The shapes a statement of the memory line cap takes, each a regex carrying
#: one ``{value}`` placeholder (``tests._contracts.NumericPopulation``).
CAP_CONTEXT_SHAPES: tuple[str, ...] = (
    # cap verb + number
    r"(?:at most|under|capped at|caps it at|bounded at|past the|over the"
    r"|stay at|--expected-value)\s*~?{value}\b",
    # comparison
    r"[≤<]=?\s*{value}\s+lines?\b",
    # hyphenated compound: "120-line cap", "~120-line index"
    r"~?{value}-line\b",
    # terminal element of a documented cap-history chain (60 → 75 → 80 → 120),
    # which is what makes a raise self-documenting: the history must be
    # APPENDED to rather than silently overwritten.
    r"(?:→|->)\s*{value}\b",
)


def cap_restatements(text: str) -> list[str]:
    """Each statement of the memory line cap in ``text``, through the cap
    population's own matcher, so a drafted row is read as the census reads a
    tracked file (no ledger path carries a cap exclusion)."""
    from tests._contracts import NumericPopulation
    from tests._surface_expected import EXPECTED_MEMORY_MD_CAP

    matcher = NumericPopulation(name="ESPALIER_MEMORY.md line cap (population)", rule_id="memory-cap-population",
                                expected_value=EXPECTED_MEMORY_MD_CAP, context_shapes=CAP_CONTEXT_SHAPES,
                                required=()).matcher()
    return [m.group(0) for line in text.splitlines() for m in matcher.finditer(line)]


# The probe-shape ratchet (``tests/test_check_ledger_probes.py``,
# ``TestProbeShapesAreRatcheted``): its baselines and detectors, read by the
# ratchet over the live roster and by the verb over a drafted probe. The
# strike verb finds an id here by parsing this file, as it does the probe
# test's own tables (DEF-1172), so each table stays a literal set.

#: Probes reading their own subject's TEXT, measured 2026-09-02 over 222.
#: Shrink this set freely; every addition needs a reason in the diff.
#:
#: DEF-672 is the one deliberate addition since. Its row's DELIVERABLE is
#: text -- four items dropped from a runbook have to be written back -- so a
#: text predicate is the honest oracle rather than a shortcut. It is keyed on
#: the stray-tag sweep's COMMAND (`for-each-ref` + `refs/tags`), not on the
#: topic, so prose about lightweight tags does not close it; only restoring
#: the command does. That narrowing is what earns the baseline slot.
#:
#: Shrunk 2026-09-20 by the third rebuild's live write (TP-452 1-D): seven
#: ids left with their rows -- DEF-451, DEF-529, DEF-581, DEF-6, DEF-666 and
#: LG-8 struck by the rebuild's adjudication, TP-332 re-keyed to DEF-864 by
#: the structural cut (same probe, same slot, carried below, not added) --
#: and the five text probes 1-C had filed (DEF-857, 858, 859, 861, 862) were
#: re-pointed at `ast` predicates by `ledger_row.py repin --probe-cmd`
#: instead of being baselined, so the set did not grow.
# DEF-625 left this set on 2026-09-26 with its row (struck by TP-457 4-A when the
# dated review scaffolds stayed in the archive).
# DEF-487 left this set on 2026-10-04 with its row (struck: the wheel-metadata
# licence test it asked for had landed with v0.8.0b2).
# DEF-479, DEF-489 and DEF-663 left this set on 2026-10-06 with their rows
# (struck by lane c28-test-tree-enumeration: the hidden-name predicate and
# the churn roster; their probes keyed on a spelling of the fix).
# DEF-343a left this set on 2026-10-08 with its row (struck by lane
# ledger-oldest-a: the actionability checks tightened; its probe keyed on the
# old regex's spelling).
# DEF-4065 and DEF-4066 left this set on 2026-10-31 with their rows (struck by
# lane the-deployed-censuses-read-the-adopters-own-files: the code-reviewer's
# census reads the adopter's modules, and the census walk prunes what the
# harness wrote on the tree; each struck on a guard red at the base).
# DEF-4070 left this set on 2026-10-31 with its row (struck by lane
# the-reap-reads-a-pids-checkout-before-a-kill: the reap recipe reads a
# pid's cwd and parents before a kill, and the Loose: line names the
# checkout; struck on a guard red at the base).
TEXT_OVER_OWN_SUBJECT = {
    "CONV-3", "DEC-29", "DEF-20",
    # DEF-378a and DEF-661 left on 2026-10-09 with their rows (struck by lane
    # ledger-decisions on the operator's calls: a check that a pack-led row
    # names a pack in flight; the census's declared limit).
    "DEF-346c",
    # DEF-383b left on 2026-10-16 with its row (struck by lane
    # wired-interpreter-argv: doctor asks the remedy once per call; its
    # probe counted the call's spelling in the function's text).
    "DEF-392c", "DEF-392d",
    "DEF-393a", "DEF-400b", "DEF-413a", "DEF-415b",
    "DEF-415f", "DEF-415h", "DEF-416b",
    # DEF-419c, DEF-419e and DEF-477 left on 2026-11-02 with their rows (struck
    # by lane the-mirror-census-diagnoses-each-mutant, the C34 class: the census
    # reads identical bytes, the curated-name pin reads the hook's own pattern,
    # an unscripted mirror row reads as a diagnosis).
    "DEF-417h", "DEF-418b",
    "DEF-424b", "DEF-424g",
    # DEF-437 and its co-id LG-12 left on 2026-11-07 with their row, and DEF-485
    # with its own (struck by lane ci-the-action-bumps-reach-the-packaged-workflow:
    # the dependabot entry names the packaged harness-guard source, held by a test
    # over the mirror registry; the SHA-pin check reads every workflow file).
    # DEF-438 and DEF-439 left on 2026-11-02 with their rows (struck by lane
    # the-pre-flight-derives-each-demand-from-its-enforcer, the C30 class: the
    # two harness-guard advisories carry one refusal statement held to the
    # script; the hook-count sites are held to the docs their audits read).
    "DEF-449",
    # DEF-486 and DEF-561 left on 2026-10-30 with their rows (struck by lane
    # gate-populations-derive-from-the-live-source, the C37 class-fix: the
    # README's skip list is a generated region; the status guard reads the
    # gate_details spelling; their probes keyed on the old text's spelling).
    "DEF-450", "DEF-476", "DEF-483", "DEF-488",
    # DEF-519 and DEF-593 left on 2026-10-08 with their rows (struck by lane
    # ledger-oldest-c: contract rule 2 names the live gate; the index parser
    # names the rows it cannot read).
    "DEF-516",
    "DEF-523", "DEF-543",
    "DEF-564",
    "DEF-576", "DEF-579", "DEF-588", "DEF-590", "DEF-623", "DEF-629",
    "DEF-644",  # DEF-631 struck 2026-10-09 (the landing-gate lane); its probe retired with it
    "DEF-645", "DEF-649", "DEF-660",
    # DEF-662 left on 2026-10-08 with its row (struck by lane
    # ledger-oldest-b: the doc-to-probe direction landed).
    "DEF-864",  # TP-332's slot, re-keyed 2026-09-20 (see above)
    #: DEF-874 (filed 2026-09-21 at the corpus fold): the row's deliverable is the
    #: wording of a release-checklist headline itself, so the probe quotes the exact
    #: bulk-push promise the fix must delete (the only occurrence in the file) and no
    #: enforcer exists to key on instead -- none of the contract test's functions reads
    #: that headline. DEF-672's shape: same subject file, same reason, earns the slot.
    #: DEF-885 (filed 2026-09-21 at the corpus fold): the deliverable is the operator
    #: procedure text of the release checklist's tag-count gate; the contract test pins
    #: push FORMS only, so no enforcer subject can flip for a doc-only fix. The probe keys
    #: on the measurement stage line and the code line after it inside the fenced block,
    #: comments skipped, holding no status guard -- driven: a guard inserted after the
    #: measurement flips it, a comment inside the block or prose outside it does not.
    "DEF-885",
    #: DEF-889 (filed 2026-09-21 at the corpus fold): the deliverable IS a markdown link
    #: in docs/README.md; the probe reads it through the engine's own link extractor
    #: (reflect_protocol._extract_local_links), keyed on a link whose target resolves to
    #: the orphaned doc -- driven: a Reference-table row with that link flips it, a prose
    #: sentence naming the path does not, so no comment or pointer can satisfy it.
    "DEF-889",
    #: DEF-896 and DEF-878 left this set on 2026-09-22: both struck (the link form
    #: deleted and the archive gate gained an absolute-link arm; the staging check
    #: re-based on `git diff --name-only` and pinned by the checklist contract), so
    #: their probes retired and a baseline slot for a retired probe is dead.
    #: DEF-628, DEF-633, PR-3 and PR-5 left this set on 2026-09-26: struck by the
    #: first post-cut ledger pack (the 2026-09-25 retiering restated the carve's
    #: clause and retired the five cost-gate comments; the fold landed with the
    #: seed), so their probes retired and their slots here were dead.
    #: SUP-2 left this set on 2026-09-26: struck by TP-457 4-A (the goalie scaffold
    #: stayed in the archive at the seed), so its probe retired with it.
    #: DEF-931 (filed 2026-09-26 at the walk-4 fold, TP-458): the row sits in §C20, whose
    #: rule is "run the verb, then make the sentence match", so the deliverable may be the
    #: three doc sentences themselves rather than the doctor slice. The probe reads the
    #: claim out of its own subject beside the engine's slice, and no enforcer keys on
    #: those sentences. Driven: rewriting one copy leaves the others and the probe stays
    #: open; it closes only when every copy is gone or doctor's `lacking[:3]` slice is
    #: widened (read from espalier/doctor.py, a declared input, not from the allow list).
    "DEF-931",
    #: DEF-933 (filed 2026-09-26 at the walk-4 fold, TP-458): the deliverable IS the
    #: 8.3 sentence of known-limit 3 in docs/sharp-edges/protected-zone-path-equivalence.md,
    #: so the probe quotes its mechanism clause (the only occurrence in the file) and no
    #: enforcer keys on it. The DEF-672 shape: same reason, earns the slot.
    "DEF-933",
    #: DEF-944 (re-keyed 2026-09-29 when its staging half landed): what stays open
    #: is the commit body prescribing a fixed type list whatever the repository's
    #: history uses, and the deliverable is that body's text, instructions an agent
    #: reads, with no code behind them to parse. The probe keys on the type-list
    #: line itself together with the absence of the `freeform` branch, so a pointer
    #: or a changelog line does not move it; writing the branch into the body does,
    #: which is the fix. The DEF-672 shape: same reason, earns the slot. The body
    #: contract the fix brings (beside the staging one) is what will hold it after.
    "DEF-944",
    #: DEF-1002 and DEF-1003 (filed 2026-10-01 from the post-flip review) left this
    #: set on 2026-10-31: struck by lane first-contact-diagnostics-read-the-adopters-tree
    #: (their fenced commands, the /analyze coverage loop and the dead-config pass,
    #: now census the adopter's tree), so their probes retired with them.
    #: LG-12 left this set on 2026-11-07 with DEF-437's row (its co-id; the note
    #: beside DEF-437's slot above names the lane).
    #: DEF-5058 (filed 2026-11-02 by lane c75-wave-3, re-keyed the same day when this
    #: ratchet caught its first probe, which counted the NEW reader's name and so
    #: closed on a "see read_ledger_trend" pointer): the deliverable IS the seed
    #: protocol's two sentences naming the critic's reader, prose with no code to
    #: parse. The probe counts the bare `read_ledger` name those sentences carry,
    #: so a pointer or a changelog line leaves it open; rewording them closes it,
    #: which is the fix. The DEF-933 shape: same reason, earns the slot.
    "DEF-5058",
}

#: Ways a probe reads text rather than asking a structural question. The
#: first three were the whole shipped detector; the rest are what it missed.
TEXT_READS = ("findall", "count(", "grep", ".read()", "read_text",
               "in open(", "splitlines")

#: ⚠ A predicate built on `ast.parse` is STRUCTURAL even though it reads the
#: file, and exempting it is not a loosening. The trap is that the paperwork
#: of a fix -- a comment, a changelog line, a "see X" pointer -- satisfies the
#: predicate while the defect stands. Comments do not survive parsing: they
#: produce no AST node at all, so no amount of prose moves an assertion about
#: `ast.Call` or `ast.FunctionDef`. Satisfying one of these takes writing the
#: code it names, which is the fix.
#:
#: The exemption is deliberately narrow -- the command must actually call
#: `ast.parse(`, not merely mention the module -- and
#: `test_reading_a_file_to_parse_it_is_not_the_trap` pins both directions, so
#: a probe that parses AND separately counts vocabulary is still caught.
STRUCTURAL_READS = ("ast.parse(",)


def is_trap_shaped(probe: dict) -> bool:
    """True when the predicate reads text out of the file its fix edits."""
    cmd = probe.get("cmd") or ""
    subject = (probe.get("subject") or "").strip()
    if not cmd or not subject or subject not in cmd:
        return False
    if any(marker in cmd for marker in STRUCTURAL_READS):
        return False
    return any(marker in cmd for marker in TEXT_READS)


#: Probes whose PROGRAM spawns an interpreter by its bare name -- a
#: `['python3', ...]` argv inside the -c payload -- which the runner's own
#: resolution cannot reach (`_under_this_interpreter` rewrites argv[0], not
#: the program): such a probe reads UNRESOLVED on a python-only host (the
#: inner spawn raises, rc 1). Empty since 2026-11-03, when DEF-411a and
#: DEF-412h were re-pinned to `sys.executable` on a tree that carries
#: `task-packs/Done/`, their declared input, as DEF-751 was on 2026-09-28; an
#: addition is a new probe spelling a literal interpreter, and the fix is
#: `sys.executable`.
SPAWNS_A_LITERAL_INTERPRETER: frozenset[str] = frozenset()
LITERAL_SPAWN_RE = re.compile(r"""\[\s*['"]python3?['"]\s*,""")


def cited_path_phantoms(rel: str, text: str) -> list[tuple[str, str]]:
    """``(citation, kind)`` for each backtick production-source citation in
    ``text`` (the row at ``rel``) that the tree does not resolve, through the
    citation test's own finder and git's list of tracked files, as that test
    reads a tracked doc: ``kind`` is ``file`` (not tracked) or ``symbol`` (a
    ``.py`` target that does not define it); a struck row cites the paths of
    its day and is read as nothing. Raises where the finder cannot be
    imported, and ``LookupError`` where git lists nothing."""
    from tests.test_doc_source_citations import _find_source_phantoms, _tracked_files

    tracked = _tracked_files()
    if not tracked:
        raise LookupError("`git ls-files` listed nothing in the tree")
    return [(cite, kind) for _rel, _line, cite, kind in _find_source_phantoms(rel, text.splitlines(), tracked)]


def _roster_breaks(rel: str, text: str, hooks_dir: Path) -> list[str]:
    return [f"names the maintenance switch beside some of its bypass hooks but omits {sorted(omitted)}: "
            "name them all, or none"
            for _unit, omitted, excl in partial_rosters(rel, text, maintenance_bypass_callers(hooks_dir))
            if excl is None]


def _cap_breaks(rel: str, text: str) -> list[str]:
    """A statement of the cap anywhere but a census site breaks the rule; a
    census site (``EXPECTED_MEMORY_CAP_SITES``, two ledger rows among them)
    must state it exactly as often as the census says, as its test asks."""
    from tests._surface_expected import EXPECTED_MEMORY_CAP_SITES

    said = cap_restatements(text)
    if rel in EXPECTED_MEMORY_CAP_SITES:
        want = EXPECTED_MEMORY_CAP_SITES[rel]
        return [] if len(said) == want else [
            f"states the memory line cap {len(said)} time(s) where the census holds it to {want} "
            "(EXPECTED_MEMORY_CAP_SITES in tests/_surface_expected.py)"]
    return [f"restates the memory line cap ({s!r}); name ESPALIER_MEMORY.md's cap without its number" for s in said]


def _cited_path_breaks(rel: str, text: str) -> list[str]:
    return [f"cites {cite}, a file git does not track (a new file: git add it first)" if kind == "file" else
            f"cites {cite}, a symbol its file does not define" for cite, kind in cited_path_phantoms(rel, text)]


def _paperwork_breaks(probe: dict) -> list[str]:
    if not is_trap_shaped(probe) or (probe.get("id") or "") in TEXT_OVER_OWN_SUBJECT:
        return []
    return [f"the probe reads text out of its own subject ({probe.get('subject')}), so a comment or a "
            "changelog line closes it while the defect stands; ask a structural question (an ast.parse "
            "predicate) or read another file, or, where the deliverable is the text itself, mint the id, "
            "add it to TEXT_OVER_OWN_SUBJECT in tests/_ledger_rules.py with its reason, and file with that id"]


def _spawn_breaks(probe: dict) -> list[str]:
    if not LITERAL_SPAWN_RE.search(probe["cmd"]) or (probe.get("id") or "") in SPAWNS_A_LITERAL_INTERPRETER:
        return []
    return ["the probe's program spawns a bare python or python3, which the runner's interpreter resolution "
            "cannot reach; spell sys.executable there"]


def breaks(rel: str, text: str, probe: dict | None = None, *, notes: list[str] | None = None,
           hooks_dir: Path = HOOKS_DIR) -> list[tuple[str, str]]:
    """``(owning test, what)`` for each content rule the row file's ``text``
    at ``rel`` (as the verb is about to write it; empty where only the probe
    is judged), or the ``probe`` entry it is about to write (its ``id``,
    ``subject`` and ``cmd``), breaks, else ``[]``: the verb's one entry point.
    Each rule runs on its own: one that cannot run here is said in ``notes``,
    naming it, and the others still run; with no ``notes`` its error is
    raised."""
    rules: list[tuple[str, Callable[[], list[str]]]] = []
    if text:
        rules += [(BYPASS_ROSTER_RULE, lambda: _roster_breaks(rel, text, hooks_dir)),
                  (MEMORY_CAP_RULE, lambda: _cap_breaks(rel, text)),
                  (CITED_PATH_RULE, lambda: _cited_path_breaks(rel, text))]
    if probe and probe.get("cmd"):
        rules += [(PAPERWORK_PROBE_RULE, lambda: _paperwork_breaks(probe)),
                  (LITERAL_SPAWN_RULE, lambda: _spawn_breaks(probe))]
    found: list[tuple[str, str]] = []
    for rule, run in rules:
        try:
            found += [(rule, what) for what in run()]
        except Exception as exc:  # noqa: BLE001 -- a rule that cannot run here is said, never a refusal
            if notes is None:
                raise
            notes.append(f"{rule} was not run ({type(exc).__name__}: {exc})")
    return found
