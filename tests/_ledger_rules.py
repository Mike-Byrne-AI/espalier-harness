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

Stdlib and the suite's light helpers only, never pytest: the verb imports it
outside a test session. Two rules run, the two the row's anchor names: the
maintenance switch named beside two or more of its bypass hooks but not all
(``TestBypassRosterCarriers``), and a restated memory line cap
(``TestMemoryCapPopulation``).
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
    the helper's own contract forbids. ``listing`` lists the hook files (the
    tests pass git's view of the checkout; the default is the folder's)."""
    callers: set[str] = set()
    paths = listing(hooks_dir, "*.py") if listing is not None else hooks_dir.glob("*.py")
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


def roster_units(text: str):
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


def breaks(rel: str, text: str, *, hooks_dir: Path = HOOKS_DIR) -> list[tuple[str, str]]:
    """``(owning test, what)`` for each content rule the drafted ``text`` at
    ``rel`` breaks, else ``[]``: the verb's one entry point."""
    found: list[tuple[str, str]] = []
    for unit, omitted, excl in partial_rosters(rel, text, maintenance_bypass_callers(hooks_dir)):
        if excl is None:
            found.append((BYPASS_ROSTER_RULE, f"names the maintenance switch beside some of its bypass hooks but "
                                              f"omits {sorted(omitted)}: name them all, or none"))
    for said in cap_restatements(text):
        found.append((MEMORY_CAP_RULE, f"restates the memory line cap ({said!r}); name ESPALIER_MEMORY.md's cap "
                                       "without its number"))
    return found
