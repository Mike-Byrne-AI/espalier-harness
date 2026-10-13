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
    shutil.copytree(CC_DIR, root / "tools" / "cc", ignore=shutil.ignore_patterns("__pycache__"))


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
        emitters = {p.name for p in HOOKS_DIR.glob("*.py") if p.name in CANONICAL_HOOK_WIRING and defines_an_emitter(p.name)}
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
               for p in HOOKS_DIR.glob("*.py")}
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
            assert "cannot start: a sibling helper import failed" in reason, reason
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


class TestAReporterOnTheBudgetSkew:
    def test_every_reporter_starts_and_exits_zero(self, cells):
        # The realistic skew only (the two budget names): a reporter's death is
        # not an opening, so its other names are the Walk's launcher to watch.
        reporters = [c for c in cells if c.kind == "reporter"]
        assert {c.hook for c in reporters} == set(reporter_hooks()), sorted({c.hook for c in reporters})
        bad = [_summary(c) for c in reporters if c.rc != 0]
        assert not bad, bad


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
