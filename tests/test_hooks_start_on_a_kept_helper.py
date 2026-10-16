"""The deny hooks start or refuse on a kept, older helper (TP-474 2-A; DEF-1176).

An upgrade keeps an unmarked ``tools/cc/hooks/_hook_utils.py`` as the adopter's
and regenerates its siblings, which may import names the kept copy predates.
Before this contract a deny hook died at its module top with exit 1, which the
hook protocol reads as a NON-BLOCKING error: every tool call proceeded with no
guard at all (measured 2026-10-07 and 2026-10-10 on a Node adopter tree, TP-474
Task 0). Now each deny hook imports its siblings and reads the helper names it
aliases under one module-top guard; under ``__main__`` a failure there is the
structured refusal ``_denial_reasons.refuse_on_helper_skew`` emits (exit 0, one
JSON object on stdout naming the repair), and an in-process importer sees the
real error. The two budget names (``spawn_timeout``, ``STATE_WRITE_LOCK``) are
read as attributes with a degrade in ``_speedbump.py`` and ``_reinject.py``,
because a verdict never depends on them, so a helper missing only those judges
on -- TP-474 Decision 3's one carve-out, measured here cell by cell.

The population is derived, never typed: the blocking hooks are the engine's
own roster (``harness_config.GOVERNANCE_BLOCKING_HOOKS``: the two PreToolUse
guards, the ConfigChange guard and the Stop gate -- a Stop hook that dies at
import runs no gate, and the stop goes through), each cross-checked to define a
``deny``/``block`` emitter; the names each reaches are every ``from _hook_utils
import`` name and every ``_hook_utils.<name>`` attribute read ANYWHERE in its
transitive sibling import graph (``ast.walk`` over the whole module: the first
cut read module-level attributes only, and a name a function reads -- the
dominant spelling, 17 to 20 per guard -- failed at call time inside the crash
guard with the re-issue remedy; the failure-mode review drove it on
``plan_guard``'s ``read_stdin_safely``). A name read with a getattr default
anywhere in the graph is a degraded name, never on the floor, and the two sets
are pinned disjoint: a degrade is whole or it is not one. Each cell copies
``tools/cc``, appends ``del <name>`` to the copy's helper and runs the hook on a
no-op input for its event: exit 0 with the refusal for a floor name, exit 0 and
judged for a budget name, never exit 1. The floor itself -- the helper
unimportable, or ``_denial_reasons`` -- is not this contract's skew: no cell
removes the file or breaks its syntax.

Controls: the intact copy judges; a sibling planted to raise at import is
refused the same way (the net is the import failure, not the helper's names);
the in-process import of a skewed copy raises (the ``__name__`` gate); and the
pre-fix shape, the guard disarmed by text surgery on a copy, exits 1 -- the red
this contract was written to catch, earned against the detector it uses.
"""
# slow-exempt: about a hundred short hook subprocesses from per-cell copies of tools/cc on a thread pool, once per module, measured 2026-10-10: 10.6 s for the module on the Air, 6.4 s of it the cells
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pytest

from espalier.harness_config import CANONICAL_HOOK_WIRING, GOVERNANCE_BLOCKING_HOOKS
from tests._live_tree import checkout_glob, copy_checkout

REPO_ROOT = Path(__file__).resolve().parent.parent
CC_DIR = REPO_ROOT / "tools" / "cc"
HOOKS_DIR = CC_DIR / "hooks"
HELPER = "_hook_utils"
REASONS = "_denial_reasons"

#: The names the blocking hooks' graphs read with a getattr default -- the two
#: budget names in ``_speedbump.py`` and ``_reinject.py``, the deadline setter
#: and the lock in ``write_guard.py``, two launcher names in ``_integrity.py``,
#: and the bounded spawn (2026-10-13) in ``_speedbump.py`` and ``_reinject.py``
#: -- so a helper missing one judges on (Decision 3 of TP-474). Derived per hook
#: by :func:`degraded_names`; this union is pinned so the degrade list grows
#: only by a deliberate edit here.
EXPECTED_DEGRADED_UNION = frozenset({
    "spawn_timeout", "STATE_WRITE_LOCK", "set_judgment_deadline",
    "is_python_launcher", "LAUNCHER_VERSION_FLAG", "run_bounded",
})

#: The measured skew (TP-474 Task 0): the two names the 2026-10-07 budget added
#: to the helper. The reporters are asserted on this skew alone -- a reporter's
#: death is not an opening; the Walk's launcher watches its other names.
BUDGET_NAMES = frozenset({"spawn_timeout", "STATE_WRITE_LOCK"})

#: The children's environment: every ``ESPALIER_*`` and ``CLAUDE*`` variable
#: stripped (a hook reads its root from ``CLAUDE_PROJECT_DIR``, and the suite's
#: own session sets it to this checkout). Each cell adds its own root, its own
#: audit directory and the light Stop gate.
_ENV = {k: v for k, v in os.environ.items() if not k.startswith(("ESPALIER", "CLAUDE"))}

_NOOP_INPUT: dict[str, dict] = {
    "PreToolUse": {"tool_name": "Read", "tool_input": {"file_path": "notes.txt"}},
    "PostToolUse": {"tool_name": "Read", "tool_input": {"file_path": "notes.txt"}, "tool_response": {}},
    "PostToolUseFailure": {"tool_name": "Read", "tool_input": {"file_path": "notes.txt"}, "error": "x"},
    "UserPromptSubmit": {"prompt": "hello"},
    "Stop": {"stop_hook_active": False},
    "SessionStart": {"source": "startup"},
    "PostCompact": {"trigger": "manual"},
    "SubagentStart": {"agent_id": "a"},
    "SubagentStop": {"agent_id": "a"},
    # The audit-only source: never blocked, so the intact and degraded cells
    # are judged allows. (A project-settings change at a root with no settings
    # file is, rightly, an unwiring the guard blocks.)
    "ConfigChange": {"source": "policy_settings"},
}


# ── the derivation ────────────────────────────────────────────────────────────

def _parse(module: str) -> ast.Module:
    path = HOOKS_DIR / f"{module}.py" if module != "_json_safe" else CC_DIR / "_json_safe.py"
    return ast.parse(path.read_text(encoding="utf-8"))


def _is_sibling(name: str) -> bool:
    return (HOOKS_DIR / f"{name}.py").is_file() or name == "_json_safe"


def _sibling_imports(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names if _is_sibling(a.name)}
        elif isinstance(node, ast.ImportFrom) and node.module and _is_sibling(node.module):
            out.add(node.module)
    return out


def import_graph(hook: str) -> set[str]:
    """The hook's module and every sibling it imports, transitively."""
    seen: set[str] = set()
    todo = [hook[:-3]]
    while todo:
        m = todo.pop()
        if m in seen:
            continue
        seen.add(m)
        todo.extend(_sibling_imports(_parse(m)) - seen)
    return seen


def helper_names_imported(tree: ast.Module) -> set[str]:
    """``from _hook_utils import <name>`` anywhere in the module (``ast.walk``,
    so a function-level import counts)."""
    return {
        a.name for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == HELPER
        for a in node.names
    }


def helper_attrs(tree: ast.Module) -> set[str]:
    """``_hook_utils.<name>`` read anywhere in the module: an alias line dies at
    import, a read in a function body dies at call time inside the crash guard
    with the re-issue remedy -- both are the kept helper's skew, and the guard
    reads every one once at import so the refusal names the repair."""
    return {
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == HELPER
    }


def helper_getattr_strings(tree: ast.Module) -> set[str]:
    """``getattr(_hook_utils, "<name>", <default>)`` anywhere: the degraded
    reads. A two-argument getattr has no default and raises like an attribute
    read, so it is not one (the engine's derivation in ``espalier/cli.py`` draws
    the same line)."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                and len(node.args) >= 3 and isinstance(node.args[0], ast.Name) and node.args[0].id == HELPER
                and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
            out.add(node.args[1].value)
    return out


def names_reached(hook: str) -> set[str]:
    """Every helper name a hook's import graph takes on the floor: by name
    import or by an attribute read, anywhere."""
    out: set[str] = set()
    for m in import_graph(hook):
        if m == HELPER:
            continue
        tree = _parse(m)
        out |= helper_names_imported(tree) | helper_attrs(tree)
    return out


def degraded_names(hook: str) -> set[str]:
    """The helper names a hook's import graph reads with a getattr default."""
    out: set[str] = set()
    for m in import_graph(hook):
        if m != HELPER:
            out |= helper_getattr_strings(_parse(m))
    return out


def helper_bindings() -> set[str]:
    """The names ``_hook_utils.py`` binds at module level (an assignment, a
    def, a class, an import), so a cell deletes only what the helper has."""
    out: set[str] = set()

    def visit(stmts: list[ast.stmt]) -> None:
        for s in stmts:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(s.name)
            elif isinstance(s, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = s.targets if isinstance(s, ast.Assign) else [s.target]
                for t in targets:
                    for n in ast.walk(t):
                        if isinstance(n, ast.Name):
                            out.add(n.id)
            elif isinstance(s, (ast.Import, ast.ImportFrom)):
                out.update((a.asname or a.name).split(".")[0] for a in s.names)
            elif isinstance(s, ast.Try):
                visit(s.body)
                for h in s.handlers:
                    visit(h.body)
                visit(s.orelse)
                visit(s.finalbody)
            elif isinstance(s, (ast.If, ast.With, ast.For, ast.While)):
                visit(s.body)
                visit(getattr(s, "orelse", []))

    visit(_parse(HELPER).body)
    return out


def deny_hooks() -> dict[str, str]:
    """``{hook file: event}`` for every blocking hook: the engine's own roster
    (``GOVERNANCE_BLOCKING_HOOKS``), which the governance wiring check and
    ``ci_guard`` already read, so a new blocking hook joins this contract the
    day it joins theirs. Each is cross-checked to define a ``deny``/``block``
    emitter at top level by :class:`TestTheDerivation`."""
    return {script: str(event) for script, event in sorted(GOVERNANCE_BLOCKING_HOOKS.items())}


def defines_an_emitter(hook: str) -> bool:
    return any(isinstance(n, ast.FunctionDef) and n.name in {"deny", "block"} for n in _parse(hook[:-3]).body)


def reporter_hooks() -> dict[str, str]:
    return {
        script: str(w["event"]) for script, w in sorted(CANONICAL_HOOK_WIRING.items())
        if script not in deny_hooks()
    }


def guard_roster(hook: str) -> tuple[str, ...] | None:
    """The tuple of helper names the hook's module-top guard reads once: the
    ``Assign`` of a tuple of string constants inside the first top-level ``try``
    whose body imports a sibling."""
    for stmt in _parse(hook[:-3]).body:
        if not isinstance(stmt, ast.Try):
            continue
        if not any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in stmt.body):
            continue
        for n in stmt.body:
            if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Tuple)
                    and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in n.value.elts)):
                return tuple(str(e.value) for e in n.value.elts)  # type: ignore[union-attr]
        return ()
    return None


# ── the cells ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Cell:
    hook: str
    event: str
    name: str | None
    kind: str        # "deny-hook" (a floor name gone) | "degraded" (a budget name gone) | "reporter" | "intact" | "planted"
    rc: int
    stdout: str
    stderr: str


def _copy_cc(root: Path) -> None:
    copy_checkout(CC_DIR, root / "tools" / "cc", ignore=shutil.ignore_patterns("__pycache__"))


def _run_hook(root: Path, hook: str, event: str, timeout: int = 45) -> subprocess.CompletedProcess:
    payload = {"hook_event_name": event, "session_id": "kept-helper", "cwd": str(root), **_NOOP_INPUT.get(event, {})}
    return subprocess.run(
        [sys.executable, str(root / "tools" / "cc" / "hooks" / hook)], input=json.dumps(payload),
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        env={**_ENV, "CLAUDE_PROJECT_DIR": str(root), "ESPALIER_AUDIT_DIR": str(root / "audit"),
             "ESPALIER_STOP_GATE": "light"},
    )


def _skew(root: Path, *names: str) -> None:
    helper = root / "tools" / "cc" / "hooks" / f"{HELPER}.py"
    helper.write_text(helper.read_text(encoding="utf-8") + f"\ndel {', '.join(names)}\n", encoding="utf-8")


def _cell(base: Path, job: tuple[str, str, str | None, str]) -> Cell:
    hook, event, name, kind = job
    root = base / f"{kind}-{hook[:-3]}-{name or 'none'}"
    _copy_cc(root)
    if kind == "planted":
        (root / "tools" / "cc" / "hooks" / f"{name}.py").write_text(
            'raise ImportError("planted: this sibling cannot import")\n', encoding="utf-8")
    elif kind in ("raised", "syntax"):
        sibling = root / "tools" / "cc" / "hooks" / f"{name}.py"
        tail = "\nraise KeyError(1)\n" if kind == "raised" else "\ndef (:\n"
        sibling.write_bytes(sibling.read_bytes() + tail.encode("utf-8"))
    elif name is not None:
        _skew(root, name)
    run = _run_hook(root, hook, event)
    shutil.rmtree(root, ignore_errors=True)
    return Cell(hook, event, name, kind, run.returncode, run.stdout, run.stderr)


@pytest.fixture(scope="module")
def cells(tmp_path_factory) -> list[Cell]:
    base = tmp_path_factory.mktemp("kept-helper")
    bound = helper_bindings()
    jobs: list[tuple[str, str, str | None, str]] = []
    for hook, event in deny_hooks().items():
        for name in sorted(names_reached(hook) & bound):
            jobs.append((hook, event, name, "deny-hook"))
        for name in sorted(degraded_names(hook) & bound):
            jobs.append((hook, event, name, "degraded"))
        jobs.append((hook, event, None, "intact"))
        jobs.append((hook, event, "_integrity", "planted"))
        jobs.append((hook, event, "_integrity", "raised"))
        jobs.append((hook, event, "_integrity", "syntax"))
    for hook, event in reporter_hooks().items():
        for name in sorted(BUDGET_NAMES):
            jobs.append((hook, event, name, "reporter"))
    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(lambda j: _cell(base, j), jobs))


def _decision(cell: Cell) -> dict | None:
    text = cell.stdout.strip()
    if not text.startswith("{"):
        return None
    try:
        return json.loads(text.splitlines()[-1])
    except ValueError:
        return None


def _is_refusal(cell: Cell) -> bool:
    d = _decision(cell)
    if not d:
        return False
    if cell.event in ("ConfigChange", "Stop"):
        return d.get("decision") == "block"
    return d.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def _reason(cell: Cell) -> str:
    d = _decision(cell) or {}
    return str(d.get("reason") or d.get("hookSpecificOutput", {}).get("permissionDecisionReason") or "")


def _summary(c: Cell) -> tuple:
    return (c.kind, c.hook, c.name, c.rc, c.stdout[-160:], c.stderr[-240:])


# ── the derivation holds ──────────────────────────────────────────────────────

class TestTheDerivation:
    def test_the_blocking_hooks_are_the_four_and_each_defines_an_emitter(self):
        assert deny_hooks() == {
            "config_guard.py": "ConfigChange", "plan_guard.py": "PreToolUse",
            "stop_gate.py": "Stop", "write_guard.py": "PreToolUse",
        }, deny_hooks()
        assert all(defines_an_emitter(h) for h in deny_hooks()), deny_hooks()
        # The cross-check both ways: a hook defining an emitter that the roster
        # does not list would be guarded by nothing here.
        emitters = {p.name for p in checkout_glob(HOOKS_DIR, "*.py") if p.name in CANONICAL_HOOK_WIRING and defines_an_emitter(p.name)}
        assert emitters == set(deny_hooks()), sorted(emitters ^ set(deny_hooks()))

    def test_every_reached_name_is_bound_by_todays_helper(self):
        # A name a hook reaches that the helper does not bind would already be a
        # NameError on every tree; the cells delete only what exists.
        bound = helper_bindings()
        unbound = {h: sorted(names_reached(h) - bound) for h in deny_hooks()}
        assert not any(unbound.values()), unbound

    @pytest.mark.parametrize("hook", sorted(deny_hooks()))
    def test_the_guard_roster_equals_every_name_the_graph_takes(self, hook):
        # Derive the list, never test a hand-written copy: the tuple the guard
        # reads once at import is pinned to the names the AST finds the hook's
        # whole import graph taking -- by name import or attribute read at any
        # depth (a function-level read would otherwise fail at call time, in the
        # crash guard, with the wrong remedy).
        roster = guard_roster(hook)
        assert roster is not None, f"{hook}: no module-top try that imports a sibling"
        assert set(roster) == names_reached(hook), (
            hook, sorted(set(roster) - names_reached(hook)), sorted(names_reached(hook) - set(roster)))
        assert len(roster) == len(set(roster)), roster

    @pytest.mark.parametrize("hook", sorted(deny_hooks()))
    def test_a_degraded_name_is_never_read_on_the_floor_in_the_same_graph(self, hook):
        # A degrade is whole or it is not one: a name read with a default in one
        # module and bare in another dies on the bare read, so the degrade only
        # moves where the failure lands (write_guard's own budget reads were
        # that shape until this lane routed them through the degraded forms).
        both = names_reached(hook) & degraded_names(hook)
        assert not both, (hook, sorted(both))

    def test_the_degrade_set_is_the_pinned_one(self):
        union = set().union(*(degraded_names(h) for h in deny_hooks()))
        assert union == EXPECTED_DEGRADED_UNION, (sorted(union - EXPECTED_DEGRADED_UNION), sorted(EXPECTED_DEGRADED_UNION - union))

    def test_the_whole_module_census_is_at_least_the_authored_figure(self):
        # TP-474 2-A measured 13 modules and 40 names on 2026-10-07, 13 and 42
        # on 2026-10-10 (two budget names now read by getattr). A body-only walk
        # read 12 and 35: the function-level imports it dropped are why ast.walk.
        per = {p.stem: helper_names_imported(_parse(p.stem)) | helper_getattr_strings(_parse(p.stem))
               for p in checkout_glob(HOOKS_DIR, "*.py")}
        per = {k: v for k, v in per.items() if v}
        assert len(per) >= 13 and len(set().union(*per.values())) >= 40, (len(per), len(set().union(*per.values())))

    def test_the_floor_is_wider_than_the_module_level_reads(self):
        # The gap the failure-mode review drove (2026-10-10): the function-level
        # attribute reads the first cut skipped are the larger part of the floor.
        for hook in deny_hooks():
            tree = _parse(hook[:-3])
            module_level = {
                n.attr for stmt in tree.body
                if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                for n in ast.walk(stmt)
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == HELPER
            }
            assert helper_attrs(tree) >= module_level and (hook == "config_guard.py" or len(helper_attrs(tree)) > len(module_level)), hook


# ── a deny hook on a kept helper ──────────────────────────────────────────────

class TestADenyHookOnAKeptHelper:
    def test_no_cell_exits_one(self, cells):
        ones = [_summary(c) for c in cells if c.rc == 1]
        assert not ones, ones

    def test_every_cell_keeps_one_channel(self, cells):
        # Exit 0 with stdout its own channel (a decision, a reporter's context,
        # or nothing); exit 2 with nothing on stdout. A refusal never writes stderr.
        bad = [_summary(c) for c in cells
               if c.rc not in (0, 2) or (c.rc == 2 and c.stdout.strip())
               or (_is_refusal(c) and c.stderr.strip())]
        assert not bad, bad

    def test_a_missing_floor_name_is_refused_naming_the_repair(self, cells):
        floor = [c for c in cells if c.kind == "deny-hook"]
        assert floor, "no floor-name cells: the derivation found nothing to delete"
        not_refused = [_summary(c) for c in floor if not (c.rc == 0 and _is_refusal(c))]
        assert not not_refused, not_refused
        for c in floor:
            reason = _reason(c)
            assert c.hook[:-3] in reason, (c.hook, reason)
            assert "tools/cc/hooks/_hook_utils.py" in reason and "espalier upgrade --execute" in reason, reason
            assert f"takes `{c.name}` from tools/cc/hooks/_hook_utils.py, which lacks it" in reason, reason
            assert "`git restore --source=HEAD -- tools/cc/hooks/" in reason, reason
            assert "Error" in reason, reason          # the exception's class, never through os_error_text

    def test_a_missing_degraded_name_is_judged_not_refused(self, cells):
        budget = [c for c in cells if c.kind == "degraded"]
        bound = helper_bindings()
        assert {(c.hook, c.name) for c in budget} == {
            (h, n) for h in deny_hooks() for n in degraded_names(h) & bound
        }, sorted({(c.hook, c.name) for c in budget})
        refused = [_summary(c) for c in budget if c.rc != 0 or _is_refusal(c)]
        assert not refused, refused

    def test_the_intact_copy_judges(self, cells):
        intact = [c for c in cells if c.kind == "intact"]
        assert {c.hook for c in intact} == set(deny_hooks())
        bad = [_summary(c) for c in intact if c.rc != 0 or _is_refusal(c)]
        assert not bad, bad

    def test_a_sibling_that_cannot_import_is_refused_the_same_way(self, cells):
        planted = [c for c in cells if c.kind == "planted"]
        assert {c.hook for c in planted} == set(deny_hooks())
        bad = [_summary(c) for c in planted if not (c.rc == 0 and _is_refusal(c) and "planted" in _reason(c))]
        assert not bad, bad
        # Named, and not blamed on the helper (DEF-2010): no name is missing.
        for c in planted:
            assert "tools/cc/hooks/_integrity.py raised ImportError" in _reason(c), _reason(c)
            assert "upgrade --execute" not in _reason(c), _reason(c)


class TestAReporterOnTheBudgetSkew:
    def test_every_reporter_starts_and_exits_zero(self, cells):
        # The realistic skew only (the two budget names): a reporter's death is
        # not an opening, so its other names are the Walk's launcher to watch.
        reporters = [c for c in cells if c.kind == "reporter"]
        assert {c.hook for c in reporters} == set(reporter_hooks()), sorted({c.hook for c in reporters})
        bad = [_summary(c) for c in reporters if c.rc != 0]
        assert not bad, bad


# ── a wedged guard names what raised, and lets one restore through ───────────
#
# DEF-2010: the refusal names the file that raised, its line and the exception,
# and offers the upgrade only on the kept-old-helper test. DEF-4025: on
# PreToolUse it reads the payload first and lets through exactly one shape, a
# Bash call that is one ``git restore`` or ``git checkout --`` to HEAD of a file
# it names, with context, no decision and a copy of the file saved first; the
# crash guard after the imports does the same. Each plant is one copy of
# ``tools/cc``; every payload in its table runs against it (the hook judges a
# restore, it never runs one, so the copy stays as planted).

_RAISE = "\nraise KeyError(1)\n"
#: The plants: (name, file under tools/cc/hooks, appended text). The crash
#: plant rebinds a helper write_guard aliases at import and calls on every
#: call, so the fault lands after the imports, inside the crash guard.
_WEDGE_PLANTS = {
    "raised": ("_reinject.py", _RAISE),
    "kept": (f"{HELPER}.py", "\ndel say_once\n"),
    "crash": (f"{HELPER}.py", "\ndef payload_cwd(*args, **kwargs):\n    raise KeyError(2)\n"),
    # A fault in the payload read itself: nothing was read, so nothing passes.
    "unread": (f"{HELPER}.py", "\ndef read_stdin_safely(*args, **kwargs):\n    raise KeyError(3)\n"),
}
#: The plants whose table rows run both ways (``unread`` lets nothing through).
_BOTH_WAYS = ("raised", "kept", "crash")
#: A deny hook file no plant puts on write_guard's traceback.
_UNRELATED = "tools/cc/hooks/session_start.py"
_REINJECT = "tools/cc/hooks/_reinject.py"


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


#: (plant, payload, passes). Every refused row is one way past the shape the
#: rows name: a second command, an operator, an expansion, another ref, the
#: index, another file, two files, a glob, another tool, an unquoted backslash
#: path (the shell eats the backslashes, so git would read another path).
_RESTORE_TABLE: list[tuple[str, dict, bool]] = [
    ("raised", _bash(f"git restore {_REINJECT}"), True),
    ("raised", _bash(f"git restore -- {_REINJECT}"), True),
    ("raised", _bash(f"git restore --source=HEAD -- {_REINJECT}"), True),
    ("raised", _bash(f"git restore -s HEAD {_REINJECT}"), True),
    ("raised", _bash(f"git restore --worktree {_REINJECT}"), True),
    ("raised", _bash(f"git checkout -- {_REINJECT}"), True),
    ("raised", _bash(f"git checkout HEAD -- {_REINJECT}"), True),
    ("raised", _bash(f"git restore ./{_REINJECT}"), True),
    ("raised", _bash("git restore 'tools\\cc\\hooks\\_reinject.py'"), True),
    ("raised", _bash(f'git restore "{_REINJECT}"'), True),
    ("raised", _bash(f"git restore {_REINJECT}; ls"), False),
    ("raised", _bash(f"git restore {_REINJECT} && echo done"), False),
    ("raised", _bash(f"git restore {_REINJECT} | cat"), False),
    ("raised", _bash(f"git restore {_REINJECT} > out.txt"), False),
    ("raised", _bash(f"git restore {_REINJECT}\nls"), False),
    ("raised", _bash("git restore $(echo tools/cc/hooks/_reinject.py)"), False),
    ("raised", _bash("git restore `echo tools/cc/hooks/_reinject.py`"), False),
    ("raised", _bash(f"git checkout main -- {_REINJECT}"), False),
    ("raised", _bash(f"git restore --source=main -- {_REINJECT}"), False),
    ("raised", _bash(f"git restore --source HEAD~1 {_REINJECT}"), False),
    ("raised", _bash(f"git restore --source main {_REINJECT}"), False),
    ("raised", _bash(f"git restore -s origin/main -- {_REINJECT}"), False),
    ("raised", _bash(f"git restore --staged {_REINJECT}"), False),
    ("raised", _bash(f"git checkout {_REINJECT}"), False),
    ("raised", _bash(f"git -C . restore {_REINJECT}"), False),
    ("raised", _bash("git restore --source=HEAD -- tools/cc/hooks/write_guard.py"), True),
    ("raised", _bash(f"git restore {_UNRELATED}"), False),
    ("raised", _bash("git restore tools/_reinject.py"), False),
    ("raised", _bash(f'git restore "{_REINJECT} "'), False),
    ("raised", _bash(f"git restore {_REINJECT}."), False),
    ("raised", _bash(f"git restore {_REINJECT}\x00"), False),
    # A relative operand resolves against the payload's cwd (the Bash tool's
    # directory), not the hook's: the same words pass from one and not the other.
    ("raised", {**_bash("git restore cc/hooks/_reinject.py"), "cwd": "tools"}, True),
    ("raised", {**_bash(f"git restore {_REINJECT}"), "cwd": "tools"}, False),
    ("raised", _bash(f"git restore {_REINJECT} tools/cc/hooks/_speedbump.py"), False),
    ("raised", _bash("git restore tools/cc/hooks/_rein*.py"), False),
    ("raised", _bash("git restore tools\\cc\\hooks\\_reinject.py"), False),
    ("raised", {"tool_name": "PowerShell", "tool_input": {"command": f"git restore {_REINJECT}"}}, False),
    ("raised", {"tool_name": "Edit", "tool_input": {"file_path": _REINJECT, "old_string": "a", "new_string": "b"}}, False),
    ("raised", {"tool_name": "Write", "tool_input": {"file_path": _REINJECT, "content": ""}}, False),
    ("kept", _bash(f"git restore tools/cc/hooks/{HELPER}.py"), True),
    # {taker} is read from the plant's own refusal: the module that takes the
    # missing name first is an import-order fact, not this row's.
    ("kept", _bash("git restore --source=HEAD -- {taker}"), True),
    ("kept", _bash(f"git restore {_UNRELATED}"), False),
    ("crash", _bash(f"git restore tools/cc/hooks/{HELPER}.py"), True),
    ("crash", _bash("git restore tools/cc/hooks/write_guard.py"), True),
    ("crash", _bash(f"git restore {_UNRELATED}"), False),
    ("unread", _bash(f"git restore --source=HEAD -- tools/cc/hooks/{HELPER}.py"), False),
]


@dataclass
class Restore:
    plant: str
    payload: dict
    passes: bool
    rc: int
    stdout: str
    stderr: str
    copies: list[str]
    audit: str


def _plant(root: Path, plant: str) -> None:
    _copy_cc(root)
    name, text = _WEDGE_PLANTS[plant]
    target = root / "tools" / "cc" / "hooks" / name
    target.write_bytes(target.read_bytes() + text.encode("utf-8"))


def _run_payload(root: Path, hook: str, payload: dict, audit: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(root / "tools" / "cc" / "hooks" / hook)],
        input=json.dumps({"hook_event_name": "PreToolUse", "session_id": "wedged", "cwd": str(root), **payload}),
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
        env={**_ENV, "CLAUDE_PROJECT_DIR": str(root), "ESPALIER_AUDIT_DIR": str(audit)},
    )


def _taker(run: subprocess.CompletedProcess) -> str:
    """The file a kept-helper refusal says takes the missing name."""
    reason = json.loads(run.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    head = reason.split(" takes `", 1)[0]
    assert head != reason and head.startswith("write_guard cannot start: "), reason
    return head[len("write_guard cannot start: "):]


def _wedge_copies(root: Path) -> list[str]:
    saved = root / ".espalier-state" / "wedge-restore"
    return sorted(p.name for p in saved.iterdir()) if saved.is_dir() else []


def _audit_text(audit: Path) -> str:
    return "".join(p.read_text(encoding="utf-8", errors="replace") for p in audit.rglob("*") if p.is_file()) \
        if audit.is_dir() else ""


@pytest.fixture(scope="module")
def restores(tmp_path_factory) -> list[Restore]:
    base = tmp_path_factory.mktemp("wedged")

    def one(job: tuple[int, tuple[str, dict, bool]]) -> Restore:
        i, (plant, payload, passes) = job
        root = base / f"{i:02d}-{plant}"
        _plant(root, plant)
        audit = root / "audit"
        if "cwd" in payload:  # a row's cwd is relative to its own copy
            payload = {**payload, "cwd": str(root / payload["cwd"])}
        if "{taker}" in payload["tool_input"].get("command", ""):
            taker = _taker(_run_payload(root, "write_guard.py", _NOOP_INPUT["PreToolUse"], root / "taker"))
            payload = _bash(payload["tool_input"]["command"].replace("{taker}", taker))
        run = _run_payload(root, "write_guard.py", payload, audit)
        result = Restore(plant, payload, passes, run.returncode, run.stdout, run.stderr,
                         _wedge_copies(root), _audit_text(audit))
        shutil.rmtree(root, ignore_errors=True)
        return result

    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(one, enumerate(_RESTORE_TABLE)))


def _output(run: Restore) -> dict:
    text = run.stdout.strip()
    assert text.startswith("{") and len(text.splitlines()) == 1, (run.payload, run.stdout, run.stderr)
    return json.loads(text)["hookSpecificOutput"]


class TestAWedgedGuardNamesWhatRaised:
    def test_a_sibling_that_raises_at_import_is_named_and_the_upgrade_is_not(self, cells):
        # The row's probe shape, on every deny hook: a sibling's module body
        # raises. The refusal names the file, its line and the exception, and
        # never sends the reader to the upgrade, which would regenerate the
        # file under edit (DEF-2010).
        raised = [c for c in cells if c.kind == "raised"]
        assert {c.hook for c in raised} == set(deny_hooks())
        for c in raised:
            reason = _reason(c)
            assert c.rc == 0 and _is_refusal(c), _summary(c)
            assert "tools/cc/hooks/_integrity.py raised KeyError: 1 at line " in reason, reason
            assert "upgrade --execute" not in reason and "managed" not in reason, reason
            assert "`git restore --source=HEAD -- tools/cc/hooks/_integrity.py`" in reason, reason

    def test_a_sibling_that_does_not_parse_is_named_by_its_own_line(self, cells):
        # A SyntaxError has no frame in the file it names, so the file is read
        # from the error itself.
        broken = [c for c in cells if c.kind == "syntax"]
        assert {c.hook for c in broken} == set(deny_hooks())
        for c in broken:
            reason = _reason(c)
            assert c.rc == 0 and _is_refusal(c), _summary(c)
            assert "tools/cc/hooks/_integrity.py raised SyntaxError" in reason, reason
            assert "upgrade --execute" not in reason, reason

    def test_only_the_hook_a_bash_call_reaches_offers_the_call_it_lets_through(self, cells):
        # plan_guard matches Write, Edit and NotebookEdit, and the ConfigChange
        # and Stop guards judge no tool call, so their text sends the restore
        # to a terminal: a Bash call meets write_guard, which judges it.
        for c in (c for c in cells if c.kind == "raised"):
            lets = "is the one call this hook lets through" in _reason(c)
            assert lets == (c.hook == "write_guard.py"), (c.hook, _reason(c))
            if not lets:
                assert "run from a terminal" in _reason(c), (c.hook, _reason(c))


class TestTheOneRestoreAWedgedGuardLetsThrough:
    def test_the_table_is_both_polarities_on_each_plant(self):
        assert set(_WEDGE_PLANTS) == set(_BOTH_WAYS) | {"unread"}
        for plant in _BOTH_WAYS:
            seen = {passes for p, _payload, passes in _RESTORE_TABLE if p == plant}
            assert seen == {True, False}, plant

    def test_each_row_passes_or_is_refused_as_written(self, restores):
        wrong = [(r.plant, r.payload, r.passes, r.stdout[-200:], r.stderr[-200:]) for r in restores
                 if r.rc != 0 or ("permissionDecision" in _output(r)) == r.passes]
        assert not wrong, wrong

    def test_a_restore_that_passes_carries_context_and_no_decision(self, restores):
        # No permissionDecision: the operator's permission mode decides the
        # call as it would any other; the context says why it passed.
        for r in (r for r in restores if r.passes):
            out = _output(r)
            assert set(out) == {"hookEventName", "additionalContext"}, out
            assert "is wedged" in out["additionalContext"] and "was let through" in out["additionalContext"], out

    def test_a_restore_that_passes_saves_the_file_first_and_records_it(self, restores):
        for r in (r for r in restores if r.passes):
            assert len(r.copies) == 1 and r.copies[0].endswith(".py.txt"), (r.payload, r.copies)
            assert r.copies[0] in _output(r)["additionalContext"], _output(r)
            assert "pretooluse_failed_open_wedge_restore" in r.audit, r.audit[-400:]
        assert not [r.copies for r in restores if not r.passes and r.copies]

    def test_the_copy_holds_the_bytes_the_restore_discards(self, tmp_path):
        root = tmp_path / "copy"
        _plant(root, "raised")
        run = _run_payload(root, "write_guard.py", _bash(f"git restore {_REINJECT}"), root / "audit")
        assert "additionalContext" in run.stdout, run.stdout
        (copy,) = (root / ".espalier-state" / "wedge-restore").iterdir()
        assert copy.read_bytes() == (root / _REINJECT).read_bytes()
        assert copy.read_bytes().endswith(_RAISE.encode("utf-8"))

    def test_a_copy_that_cannot_be_written_never_blocks_the_restore(self, tmp_path):
        root = tmp_path / "nocopy"
        _plant(root, "raised")
        (root / ".espalier-state").write_text("a file where the directory goes\n", encoding="utf-8")
        run = _run_payload(root, "write_guard.py", _bash(f"git restore {_REINJECT}"), root / "audit")
        out = json.loads(run.stdout)["hookSpecificOutput"]
        assert "permissionDecision" not in out and "No copy was saved first" in out["additionalContext"], out

    def test_the_kept_helper_refusal_names_both_files_and_the_upgrade(self, restores):
        refused = next(r for r in restores if r.plant == "kept" and not r.passes)
        reason = _output(refused)["permissionDecisionReason"]
        assert "takes `say_once` from tools/cc/hooks/_hook_utils.py" in reason, reason
        assert "espalier upgrade --execute" in reason, reason
        assert "(or the same command for the file you edited, if it is tools/cc/hooks/_hook_utils.py or " in reason, reason

    def test_a_quoted_shell_operator_refuses_even_where_the_path_would_match(self, tmp_path):
        # The operator check is its own refusal, not the operand count's: a
        # restorable file whose name holds `;` is refused when quoted. Driven
        # in a child, the hook modules' loader contract (never in-suite).
        script = (
            "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); import _denial_reasons as d\n"
            "cc = Path(sys.argv[1]).resolve().parent\n"
            "r = d._SkewReading(cc / 'hooks' / 'a;b.py', 1, None, [cc / 'hooks' / 'a;b.py'], cc)\n"
            "pay = lambda c: {'tool_name': 'Bash', 'tool_input': {'command': c}, 'cwd': str(cc.parent.parent)}\n"
            "print(d._restore_target(pay(\"git restore 'tools/cc/hooks/a;b.py'\"), r))\n"
            "r2 = d._SkewReading(cc / 'hooks' / 'ab.py', 1, None, [cc / 'hooks' / 'ab.py'], cc)\n"
            "print(d._restore_target(pay(\"git restore 'tools/cc/hooks/ab.py'\"), r2) is not None)\n"
        )
        out = subprocess.run([sys.executable, "-c", script, str(HOOKS_DIR)], capture_output=True, text=True,
                             encoding="utf-8", env=_ENV, cwd=str(REPO_ROOT), timeout=45)
        assert out.stdout.split() == ["None", "True"], (out.stdout, out.stderr)

    def test_an_error_naming_a_helper_name_that_exists_is_no_kept_helper(self):
        # The kept-old-helper test checks the module, not only the error's
        # fields: an AttributeError that names a name the helper has (raised by
        # hand, or by any code path but a missing name) is a plain raise.
        script = (
            "import sys; sys.path.insert(0, sys.argv[1]); import _hook_utils as h, _denial_reasons as d\n"
            "print(d._missing_helper_name(AttributeError('x', name='STATE_DIR', obj=h)))\n"
            "print(d._missing_helper_name(AttributeError('x', name='no_such_helper_name', obj=h)))\n"
        )
        out = subprocess.run([sys.executable, "-c", script, str(HOOKS_DIR)], capture_output=True, text=True,
                             encoding="utf-8", env=_ENV, cwd=str(REPO_ROOT), timeout=45)
        assert out.stdout.split() == ["None", "no_such_helper_name"], (out.stdout, out.stderr)

    def test_the_crash_guard_names_the_frame_and_never_the_message(self, restores):
        refused = next(r for r in restores if r.plant == "crash" and not r.passes)
        reason = _output(refused)["permissionDecisionReason"]
        assert "write_guard internal error (KeyError at tools/cc/hooks/_hook_utils.py:" in reason, reason
        assert "KeyError: 2" not in reason, reason
        assert "`git restore --source=HEAD -- tools/cc/hooks/_hook_utils.py`" in reason, reason
        assert "is the one call this hook lets through" in reason, reason

    def test_a_crash_in_the_payload_read_offers_no_pass(self, restores):
        # Nothing was read, so nothing can be let through: the text says the
        # terminal, never the pass the next call would be refused.
        refused = next(r for r in restores if r.plant == "unread")
        reason = _output(refused)["permissionDecisionReason"]
        assert "write_guard internal error (KeyError at tools/cc/hooks/_hook_utils.py:" in reason, reason
        assert "lets through" not in reason and "run from a terminal" in reason, reason

    def test_an_unplaced_failure_and_an_unformattable_template_still_refuse(self, tmp_path):
        # The refusal's own text can never be the exit 1 it replaces: a failure
        # with no traceback reads the unplaced template, and a template that
        # cannot format falls back to plain words.
        script = (
            "import sys, json; sys.path.insert(0, sys.argv[1]); import _hook_utils, _denial_reasons as d\n"
            "if sys.argv[2] == 'broken': d.SIBLING_RAISED_UNPLACED = '{no_such_key}'\n"
            "d.refuse_on_helper_skew('plan_guard', 'PreToolUse', KeyError(9))\n"
        )
        for mode, words in (("intact", "no file under tools/cc/ is on its traceback"),
                            ("broken", "its text could not be composed")):
            out = subprocess.run([sys.executable, "-c", script, str(HOOKS_DIR), mode], capture_output=True,
                                 text=True, encoding="utf-8", timeout=45, input="", cwd=str(tmp_path),
                                 env={**_ENV, "CLAUDE_PROJECT_DIR": str(tmp_path),
                                      "ESPALIER_AUDIT_DIR": str(tmp_path / "audit")})
            assert out.returncode == 0 and not out.stderr.strip(), (mode, out.returncode, out.stderr)
            decision = json.loads(out.stdout)["hookSpecificOutput"]
            assert decision["permissionDecision"] == "deny" and words in decision["permissionDecisionReason"], decision


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "core.autocrlf=false", "-c", "user.name=wedge", "-c", "user.email=wedge@example.invalid",
         *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)


def _committed_copy(root: Path) -> None:
    _copy_cc(root)
    for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        assert _git(root, *args).returncode == 0, args


def _append(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.write_bytes(path.read_bytes() + text.encode("utf-8"))


def _after_future(root: Path, rel: str, line: str) -> None:
    """Insert ``line`` after the module's ``from __future__`` import."""
    path = root / rel
    head, sep, tail = path.read_bytes().decode("utf-8").partition("from __future__ import annotations\n")
    assert sep, rel
    path.write_bytes((head + sep + line + tail).encode("utf-8"))


def _staged_name_error(root: Path) -> str:
    # The 2026-10-16 04:20Z shape: a decorator before its import, staged.
    _append(root, "tools/cc/hooks/_speedbump.py", "\n@functools_not_yet_imported.lru_cache\ndef _probe():\n    return 0\n")
    assert _git(root, "add", "tools/cc/hooks/_speedbump.py").returncode == 0
    return "tools/cc/hooks/_speedbump.py"


def _circular(root: Path) -> str:
    # The edited module re-enters one that imports it; the raise lands there.
    _after_future(root, "tools/cc/hooks/_bash_patterns.py", "import _speedbump  # noqa: F401\n")
    return "tools/cc/hooks/_bash_patterns.py"


def _new_module(root: Path) -> str:
    # The edited module imports a new, untracked one that raises.
    (root / "tools" / "cc" / "hooks" / "_wedge_new.py").write_text("raise KeyError(4)\n", encoding="utf-8")
    _after_future(root, "tools/cc/hooks/_speedbump.py", "import _wedge_new  # noqa: F401\n")
    return "tools/cc/hooks/_speedbump.py"


def _merge_conflict(root: Path) -> str:
    # A merge that conflicts in a hook file leaves markers, a SyntaxError.
    rel = "tools/cc/hooks/_reinject.py"
    for branch, text in (("side", "\nSIDE = 1\n"), ("main", "\nSIDE = 2\n")):
        if branch == "side":
            assert _git(root, "switch", "-q", "-c", "side").returncode == 0
        else:
            assert _git(root, "switch", "-q", "main").returncode == 0
        _append(root, rel, text)
        assert _git(root, "commit", "-q", "-am", branch).returncode == 0
    assert _git(root, "merge", "-q", "side").returncode != 0
    return rel


_SCENARIOS = {"staged": _staged_name_error, "circular": _circular, "new-module": _new_module,
              "merge-conflict": _merge_conflict}


class TestTheNamedRestoreRepairsTheGuard:
    """End to end, with real git: the refusal names a restore of the edited
    file, the wedged guard lets that command through, git runs it, and the
    guard starts again. The table above judges the hook's JSON; this is the
    oracle that the command it names is the repair."""

    @pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
    def test_the_command_the_refusal_names_repairs_the_wedge(self, tmp_path, scenario):
        root = tmp_path / scenario
        _committed_copy(root)
        edited = _SCENARIOS[scenario](root)
        audit = root / "audit"
        refused = _run_payload(root, "write_guard.py", _NOOP_INPUT["PreToolUse"], audit)
        reason = json.loads(refused.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        assert "cannot start" in reason and edited in reason, reason
        command = f"git restore --source=HEAD -- {edited}"
        assert "`git restore --source=HEAD -- " in reason, reason
        passed = _run_payload(root, "write_guard.py", _bash(command), audit)
        out = json.loads(passed.stdout)["hookSpecificOutput"]
        assert "permissionDecision" not in out and "was let through" in out["additionalContext"], out
        ran = _git(root, *command.split()[1:])
        assert ran.returncode == 0, ran.stderr
        judged = _run_payload(root, "write_guard.py", _NOOP_INPUT["PreToolUse"], audit)
        assert judged.returncode == 0 and "deny" not in judged.stdout, (judged.stdout, judged.stderr[-300:])


# ── the guard is reachable, and earns its red ────────────────────────────────

class TestTheGuardIsReachable:
    @pytest.mark.parametrize("hook", sorted(deny_hooks()))
    def test_the_hook_imports_under_both_spellings_on_the_intact_tree(self, hook):
        # The loader contract (memory/hook-authoring.md): bare, with the hooks
        # directory on the path; and dotted from the repository root. A fresh
        # process each, never an in-suite import.
        bare = subprocess.run(
            [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(HOOKS_DIR)!r}); import {hook[:-3]}"],
            capture_output=True, text=True, encoding="utf-8", env=_ENV, cwd=str(REPO_ROOT), timeout=45)
        dotted = subprocess.run(
            [sys.executable, "-c", f"import tools.cc.hooks.{hook[:-3]}"],
            capture_output=True, text=True, encoding="utf-8", env=_ENV, cwd=str(REPO_ROOT), timeout=45)
        assert bare.returncode == 0, bare.stderr
        assert dotted.returncode == 0, dotted.stderr

    def test_an_in_process_importer_of_a_skewed_copy_sees_the_real_error(self, tmp_path):
        # The __name__ gate: imported rather than run, the guard re-raises, so a
        # test or a tool that loads the module learns the truth instead of a deny.
        root = tmp_path / "imported"
        _copy_cc(root)
        _skew(root, "payload_cwd")
        hooks = root / "tools" / "cc" / "hooks"
        r = subprocess.run(
            [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(hooks)!r}); import write_guard"],
            capture_output=True, text=True, encoding="utf-8", env={**_ENV, "CLAUDE_PROJECT_DIR": str(root)},
            cwd=str(root), timeout=45)
        assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
        assert "payload_cwd" in r.stderr and ("AttributeError" in r.stderr or "ImportError" in r.stderr), r.stderr

    def test_the_pre_fix_shape_exits_one_so_the_detector_can_red(self, tmp_path):
        # Earn the red: disarm write_guard's guard on a copy (the handler call
        # becomes a bare re-raise, the bare-import shape this lane replaced) and
        # delete a floor name; the hook dies with exit 1 -- exactly what
        # test_no_cell_exits_one exists to catch.
        root = tmp_path / "prefix"
        _copy_cc(root)
        hook = root / "tools" / "cc" / "hooks" / "write_guard.py"
        text = hook.read_text(encoding="utf-8")
        armed = '    if __name__ != "__main__":\n        raise\n    _denial_reasons.refuse_on_helper_skew("write_guard", "PreToolUse", _skew)\n'
        assert text.count(armed) == 1, "the guard's shape moved; update this control with it"
        hook.write_text(text.replace(armed, "    raise\n"), encoding="utf-8")
        _skew(root, "payload_cwd")
        run = _run_hook(root, "write_guard.py", "PreToolUse")
        assert run.returncode == 1, (run.returncode, run.stdout, run.stderr)
        assert run.stdout.strip() == "", run.stdout
