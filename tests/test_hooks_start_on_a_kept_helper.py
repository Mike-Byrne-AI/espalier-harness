"""The deny hooks start or refuse on a kept, older helper (TP-474 2-A; DEF-1176).

An upgrade keeps an unmarked ``tools/cc/hooks/_hook_utils.py`` as the adopter's
and regenerates its siblings, which may import names the kept copy predates.
Before this contract a deny hook died at its module top with exit 1, which the
hook protocol reads as a NON-BLOCKING error: every tool call proceeded with no
guard at all (measured 2026-10-07 and 2026-10-10 on a Node adopter tree, TP-474
Task 0). Now each deny hook imports its siblings and reads the helper names it
aliases under one module-top guard; under ``__main__`` a failure there is the
structured refusal ``_start_refusal.refuse_on_helper_skew`` emits (exit 0, one
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
judged for a budget name, never exit 1. The floor itself -- the helper, the
reasons module and what each imports at its top -- joined the guard with
DEF-3008: its cells make each raise at import, and the start refusal
(``_start_refusal``), which every deny hook imports first and alone, falls to
a last resort of each hook's own.

Controls: the intact copy judges; a sibling planted to raise at import is
refused the same way (the net is the import failure, not the helper's names);
the in-process import of a skewed copy raises (the ``__name__`` gate); and the
pre-fix shape, the guard disarmed by text surgery on a copy, exits 1 -- the red
this contract was written to catch, earned against the detector it uses.
"""
# slow-exempt: about a hundred short hook subprocesses from per-cell copies of tools/cc on a thread pool, once per module, measured 2026-10-10: 10.6 s for the module on the Air, 6.4 s of it the cells; on loaded Linux CI cells the cells fixture alone took 21 to 48 s (2026-11-07/08, DEF-2056)
from __future__ import annotations

import ast
import atexit
import compileall
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pytest

from espalier.harness_config import CANONICAL_HOOK_WIRING, GOVERNANCE_BLOCKING_HOOKS
from tests._hook_spawn import RetryAllowance, retry_a_budget_miss
from tests._live_tree import checkout_glob, copy_checkout
from tests._temp_sweep import write_lock
from tests._wait_budget import scaled

# timeout-exempt: headroom, not cost -- the module-scoped `cells` fixture lands in the first `cells` test each xdist worker runs, 21 to 48 s of the ini's 60 s across 19 Linux full-tier cells (2026-11-07/08, DEF-2056), so each class whose tests request it carries this ceiling, and so does each class whose rows reach `_run_payload` or `_run_hook`, whose 45 s spawn retries a budget refusal once and so needs twice that under the ceiling less 10 s (DEF-2057, pinned in tests/test_test_suite_contract.py); the module stays in the fast slice and its other tests keep the ini's
_CELLS_CEILING_S = 180

REPO_ROOT = Path(__file__).resolve().parent.parent
CC_DIR = REPO_ROOT / "tools" / "cc"
HOOKS_DIR = CC_DIR / "hooks"
HELPER = "_hook_utils"
REASONS = "_denial_reasons"
#: The start refusal every deny hook imports first and alone (DEF-3008).
REFUSAL = "_start_refusal"
#: The floor plants (DEF-3008), each made to raise at import on every deny
#: hook: the helper, the reasons module, what each imports at its top, and the
#: start refusal itself, whose failure is each hook's own last resort.
FLOOR_PLANTS = (HELPER, REASONS, "_maintenance_mode", "_json_safe", REFUSAL)

#: The names the blocking hooks' graphs read with a getattr default -- the two
#: budget names in ``_speedbump.py`` and ``_reinject.py``, the deadline setter
#: and the lock in ``write_guard.py``, two launcher names in ``_integrity.py``,
#: and the bounded spawn (2026-10-13) in ``_speedbump.py`` and ``_reinject.py``,
#: and CP-KILL's reader, loader and checkout list (2026-11-02) in ``_speedbump.py``,
#: and the torn-line heal (2026-11-08) in ``_integrity.py``, ``_speedbump.py`` and
#: ``_born_weak.py`` -- so a helper missing one judges on (Decision 3 of TP-474).
#: Derived per hook by :func:`degraded_names`; this union is pinned so the
#: degrade list grows only by a deliberate edit here.
EXPECTED_DEGRADED_UNION = frozenset({
    "spawn_timeout", "STATE_WRITE_LOCK", "set_judgment_deadline",
    "is_python_launcher", "LAUNCHER_VERSION_FLAG", "run_bounded",
    "load_checkout_sync", "_load_beside_hooks", "sibling_checkouts",
    "own_line",
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
    return module_bindings(HELPER)


def module_bindings(module: str) -> set[str]:
    """The names a sibling binds at module level, read as ``helper_bindings``."""
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

    visit(_parse(module).body)
    return out


def _top_level_nodes(stmts: list[ast.stmt]):
    """Every node a module runs at import: inside its top-level blocks, never
    inside a def, a class or a lambda, and never under ``if TYPE_CHECKING``."""
    for s in stmts:
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(s, ast.If) and isinstance(s.test, ast.Name) and s.test.id == "TYPE_CHECKING":
            continue
        todo: list[ast.AST] = [s]
        while todo:
            node = todo.pop()
            yield node
            todo.extend(c for c in ast.iter_child_nodes(node)
                        if not isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)))


def import_time_reads(hook: str) -> dict[str, set[str]]:
    """``{sibling: names}``: every name the hook reads from a sibling while its
    module body runs -- ``from <sibling> import <name>``, or ``<sibling>.<name>``
    -- the helper and the start refusal included."""
    found: dict[str, set[str]] = {}
    aliases: dict[str, str] = {}
    nodes = list(_top_level_nodes(_parse(hook[:-3]).body))
    for node in nodes:
        if isinstance(node, ast.Import):
            aliases.update({a.asname or a.name: a.name for a in node.names if _is_sibling(a.name)})
        elif isinstance(node, ast.ImportFrom) and node.module and _is_sibling(node.module):
            found.setdefault(node.module, set()).update(a.name for a in node.names)
    for node in nodes:
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id in aliases):
            found.setdefault(aliases[node.value.id], set()).add(node.attr)
    return found


def kept_sibling_reads(hook: str) -> dict[str, str]:
    """``{sibling: name}``: for each sibling other than the helper and the start
    refusal (which each deny hook imports first and alone) that the hook reads
    a name from at import -- ``from <sibling> import <name>``, or
    ``<sibling>.<name>`` -- the first such name, sorted, of those the sibling
    binds and never reads itself. Deleting it there is the kept-old-file skew
    for a file that is not the helper (DEF-5087); a name the sibling's own code
    reads cannot stand for a kept copy, since an older copy that lacks the name
    lacks the code that reads it too (``_denial_reasons`` calls
    ``_maintenance_mode.relaunch_hint()`` at import, which reads ``ENV_VAR``:
    deleting that raised a NameError in the sibling, no kept copy's shape).
    Discovered from the hook's source, so a sibling the hook starts reading at
    import joins the cells the day it does."""
    skip = {HELPER, REFUSAL}
    out: dict[str, str] = {}
    for sibling, names in sorted(import_time_reads(hook).items()):
        if sibling in skip:
            continue
        own = {n.id for n in ast.walk(_parse(sibling)) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        bound = sorted((names & module_bindings(sibling)) - own)
        if bound:
            out[sibling] = bound[0]
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
    whose body imports the helper (the start refusal's own ``try``, before it,
    imports that module alone: DEF-3008)."""
    for stmt in _parse(hook[:-3]).body:
        if not isinstance(stmt, ast.Try):
            continue
        if not any(isinstance(n, ast.Import) and any(a.name == HELPER for a in n.names) for n in stmt.body):
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
    kind: str        # "deny-hook" (a floor name gone) | "degraded" (a budget name gone) | "reporter" | "intact" | "planted" | "raised" | "syntax" | "floor" (a floor module raising) | "body" (the hook's own module body raising) | "kept" (a name gone from a sibling that is not the helper; name is "<sibling>:<name>")
    rc: int
    stdout: str
    stderr: str
    audit: str = ""  # the cell's audit records, read before its tree goes


#: The width of the two fixtures' spawn pools (`cells`, `restores`): six, or
#: the runner's cores where it has fewer. Six threads on windows-latest's four
#: vCPUs each started a guard whose 4.0 s budget the others' CPU ate; 12 of the
#: leg's 20 budget misses in 15 runs were this file's (DEF-4114). Not divided by
#: the xdist worker count: at one thread `cells` would run about six times its
#: 21 to 48 s against `_CELLS_CEILING_S`.
_POOL_WIDTH = max(1, min(6, os.cpu_count() or 1))

_WARM_LOCK = threading.Lock()
_WARM: list[Path] = []


def _warm_cc() -> Path:
    """One copy of ``tools/cc`` per test process, its bytecode compiled once.
    ``copy_checkout`` copies git's tracked files alone, so a copy starts with
    no bytecode and its first mutating spawn compiled ``_bash_patterns`` and
    its siblings inside the guard's budget. Built under a lock: the pools'
    threads reach it at once. Its dir carries this process's pid lock, so a
    killed run's copy (about 5 MB a worker) goes at the suite's next session
    start (tests/_temp_sweep.py); a run that ends removes it at exit."""
    with _WARM_LOCK:
        if not _WARM:
            template = Path(tempfile.mkdtemp(prefix="kept-helper-cc-")) / "cc"
            write_lock(template.parent)
            copy_checkout(CC_DIR, template, ignore=shutil.ignore_patterns("__pycache__"))
            compileall.compile_dir(str(template), quiet=2)
            atexit.register(shutil.rmtree, template.parent, True)
            _WARM.append(template)
        return _WARM[0]


def _copy_cc(root: Path) -> None:
    """``tools/cc`` under ``root``, warm: a copy of `_warm_cc`'s template with
    its mtimes kept, so each module's bytecode stays valid. A plant changes its
    file's size, which invalidates that file's bytecode, so the planted source
    is what runs (`TestTheCopiedTreeIsWarm` pins both)."""
    shutil.copytree(_warm_cc(), root / "tools" / "cc", dirs_exist_ok=True)


def _run_hook(root: Path, hook: str, event: str, timeout: int = 45,
              allowance: RetryAllowance | None = None) -> subprocess.CompletedProcess:
    payload = {"hook_event_name": event, "session_id": "kept-helper", "cwd": str(root), **_NOOP_INPUT.get(event, {})}
    env = {**_ENV, "CLAUDE_PROJECT_DIR": str(root), "ESPALIER_AUDIT_DIR": str(root / "audit"),
           "ESPALIER_STOP_GATE": "light"}
    return retry_a_budget_miss(lambda: subprocess.run(
        [sys.executable, str(root / "tools" / "cc" / "hooks" / hook)], input=json.dumps(payload),
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        env=env,
    ), env=env, cwd=str(root), allowance=allowance)


def _skew(root: Path, *names: str) -> None:
    helper = root / "tools" / "cc" / "hooks" / f"{HELPER}.py"
    helper.write_text(helper.read_text(encoding="utf-8") + f"\ndel {', '.join(names)}\n", encoding="utf-8")


def _floor_rel(name: str) -> str:
    """A floor plant's file as the repository spells it."""
    return "tools/cc/_json_safe.py" if name == "_json_safe" else f"tools/cc/hooks/{name}.py"


#: write_guard's block that splits the hook process from its judging child.
_SPLIT = 'if __name__ == "__main__":\n    if sys.argv[1:2] == [_JUDGE_FLAG]:\n'


def _plant_in_the_body(path: Path, text: str, before: str | None = None) -> None:
    """Put ``text`` into a hook's own module body: before ``before`` (one
    place in the file), else before its last ``__main__`` block."""
    source = path.read_text(encoding="utf-8")
    if before is None:
        at = source.rindex('\nif __name__ == "__main__":\n')
    else:
        assert source.count(before) == 1, f"{path.name}: the plant's place moved"
        at = source.index(before)
    path.write_text(source[:at] + text + source[at:], encoding="utf-8")


def _cell(base: Path, job: tuple[str, str, str | None, str], allowance: RetryAllowance) -> Cell:
    hook, event, name, kind = job
    root = base / f"{kind}-{hook[:-3]}-{(name or 'none').replace(':', '-')}"
    _copy_cc(root)
    if kind == "kept" and name is not None:
        sibling, gone = name.split(":")
        kept = root / _floor_rel(sibling)
        kept.write_bytes(kept.read_bytes() + f"\ndel {gone}\n".encode("utf-8"))
    elif kind == "planted":
        (root / "tools" / "cc" / "hooks" / f"{name}.py").write_text(
            'raise ImportError("planted: this sibling cannot import")\n', encoding="utf-8")
    elif kind == "floor" and name is not None:
        floor = root / _floor_rel(name)
        floor.write_bytes(floor.read_bytes() + _RAISE.encode("utf-8"))
    elif kind in ("raised", "syntax"):
        sibling = root / "tools" / "cc" / "hooks" / f"{name}.py"
        tail = "\nraise KeyError(1)\n" if kind == "raised" else "\ndef (:\n"
        sibling.write_bytes(sibling.read_bytes() + tail.encode("utf-8"))
    elif kind == "body":
        # Before the hook's last `__main__` block (each ends in a
        # `raise SystemExit(...main(...))`, so a raise placed after it never
        # runs); `split` is write_guard's other place, before the block that
        # splits the hook process from its judging child, after the
        # module-level constants the hard bound reads.
        _plant_in_the_body(root / "tools" / "cc" / "hooks" / hook, _RAISE, before=_SPLIT if name == "split" else None)
    elif name is not None:
        _skew(root, name)
    run = _run_hook(root, hook, event, allowance=allowance)
    records = root / "audit"
    audit = "".join(p.read_text(encoding="utf-8", errors="replace")
                    for p in (sorted(records.iterdir()) if records.is_dir() else []) if p.is_file())
    shutil.rmtree(root, ignore_errors=True)
    return Cell(hook, event, name, kind, run.returncode, run.stdout, run.stderr, audit)


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
        jobs.append((hook, event, None, "body"))
        if hook == "write_guard.py":
            jobs.append((hook, event, "split", "body"))
        for name in FLOOR_PLANTS:
            jobs.append((hook, event, name, "floor"))
        for sibling, name in kept_sibling_reads(hook).items():
            jobs.append((hook, event, f"{sibling}:{name}", "kept"))
    for hook, event in reporter_hooks().items():
        for name in sorted(BUDGET_NAMES):
            jobs.append((hook, event, name, "reporter"))
    allowance = RetryAllowance()  # the build's budget retries, shared by its threads (DEF-2057)
    with ThreadPoolExecutor(max_workers=_POOL_WIDTH) as pool:
        return list(pool.map(lambda j: _cell(base, j, allowance), jobs))


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

    def test_the_upgrade_reads_every_name_a_deny_hook_takes_at_import(self):
        # The failure-mode review on DEF-5087: the upgrade's walker read each
        # deny hook's start guard (`except Exception:` then the refusal) as a
        # degrade, so a kept sibling lacking a name a hook takes at import was
        # named by nothing at upgrade while the hook refused every call (a kept
        # _hook_contract.py lacking STOP_INNER_BUDGET; stop_gate). Every such
        # name, of every sibling, must be a take the upgrade reads.
        from espalier.cli import _sibling_takes
        names, _keywords = _sibling_takes(HOOKS_DIR.parent)
        pairs = [(hook, sibling, name) for hook in sorted(deny_hooks())
                 for sibling, taken in sorted(import_time_reads(hook).items()) for name in sorted(taken)]
        assert len(pairs) >= 60, pairs   # the floor at authoring (68): the four hooks' module-top takes
        missed = [p for p in pairs if f"tools/cc/hooks/{p[0]}" not in names.get(p[1], {}).get(p[2], set())]
        assert not missed, missed

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
            assert helper_attrs(tree) >= module_level and len(helper_attrs(tree)) > len(module_level), hook


# ── a deny hook on a kept helper ──────────────────────────────────────────────

@pytest.mark.timeout(_CELLS_CEILING_S)
class TestADenyHookOnAKeptHelper:
    def test_no_cell_exits_one(self, cells):
        ones = [_summary(c) for c in cells if c.rc == 1]
        assert not ones, ones
        # A raise in a hook's own module body, after its siblings imported, is
        # the start refusal too: named as the body's, never as an import, with
        # no upgrade offered or ruled out, and recorded as the body's.
        body = [c for c in cells if c.kind == "body"]
        assert {c.hook for c in body} == set(deny_hooks()), sorted(c.hook for c in body)
        for c in body:
            reason = _reason(c)
            assert c.rc == 0 and _is_refusal(c), _summary(c)
            assert f"tools/cc/hooks/{c.hook} raised KeyError" in reason, reason
            assert "while the hook's own module body ran" in reason, reason
            assert "imported its siblings" not in reason and "upgrade" not in reason, reason
            assert '"skew": "module body"' in c.audit, (c.hook, c.audit[-400:])

    def test_a_raise_past_the_module_body_is_never_named_as_the_bodys(self, tmp_path):
        # The module-body refusal ends where the body does (`body_done`). A
        # raise escaping `main` once it has read the payload keeps the hook's
        # own handling: a body refusal there could not read the Stop loop
        # signal (a lockout, driven by the code review). And nothing after
        # write_guard's parent writes a decision adds a second document. Both
        # keep today's exit, so they are judged on what they print, apart from
        # the cells, which assert every exit.
        for hook, event in sorted(deny_hooks().items()):
            root = tmp_path / f"main-{hook[:-3]}"
            _copy_cc(root)
            path = root / "tools" / "cc" / "hooks" / hook
            source = path.read_text(encoding="utf-8")
            main = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "main")
            guard = next(n for n in main.body if isinstance(n, ast.Try))
            lines = source.splitlines(keepends=True)
            lines.insert(guard.lineno - 1, "    sys.stdin.read()\n    raise KeyError(1)\n")
            path.write_text("".join(lines), encoding="utf-8")
            run = _run_hook(root, hook, event)
            audit = _audit_text(root / "audit")
            assert "module body" not in run.stdout, (hook, run.stdout)
            assert '"skew": "module body"' not in audit, (hook, audit[-400:])
        root = tmp_path / "relay"
        _copy_cc(root)
        (root / ".env").write_text("TOKEN=x\n", encoding="utf-8")
        relay = "        sys.stdout.buffer.write(out)\n        sys.stdout.flush()\n"
        guard_file = root / "tools" / "cc" / "hooks" / "write_guard.py"
        source = guard_file.read_text(encoding="utf-8")
        assert source.count(relay) == 1, "the parent's relay moved; update this plant with it"
        guard_file.write_text(source.replace(relay, relay + "        raise KeyError(1)\n"), encoding="utf-8")
        run = _run_payload(root, "write_guard.py", {"tool_name": "Read", "tool_input": {"file_path": ".env"}},
                           root / "audit")
        documents = [line for line in run.stdout.splitlines() if line.strip().startswith("{")]
        assert len(documents) == 1 and '"permissionDecision": "deny"' in documents[0], (run.stdout, run.stderr[-400:])

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

    def test_a_name_a_kept_sibling_lacks_is_refused_naming_that_file(self, cells):
        # DEF-5087 (air's ruling e8d934): the kept-old-file test reads any
        # tools/cc module, so a kept sibling that is not the helper is named
        # with the upgrade repair, never told the upgrade would not repair it.
        kept = [c for c in cells if c.kind == "kept"]
        assert {(c.hook, str(c.name)) for c in kept} == {
            (h, f"{s}:{n}") for h in deny_hooks() for s, n in kept_sibling_reads(h).items()}
        # The floor at authoring (2026-11-08): stop_gate reads three such
        # siblings and write_guard two; config_guard and plan_guard read only
        # names their sibling's own code reads, so the reader's unit rows in
        # tests/test_kept_sibling.py stand for them.
        assert len(kept) >= 5 and len({c.hook for c in kept}) >= 2, sorted((c.hook, c.name) for c in kept)
        for c in kept:
            sibling, name = str(c.name).split(":")
            rel = _floor_rel(sibling)
            reason = _reason(c)
            assert c.rc == 0 and _is_refusal(c), _summary(c)
            assert f"takes `{name}` from {rel}, which lacks it" in reason, reason
            assert f"If an upgrade kept {rel.rsplit('/', 1)[1]} as yours" in reason, reason
            assert "espalier upgrade --execute" in reason and "would not repair" not in reason, reason
            # The record is best-effort: its writer, _integrity, imports from
            # _json_safe, so a kept _json_safe leaves the decision and no record.
            if sibling != "_json_safe":
                assert f'"kept": "{rel}"' in c.audit, (c.hook, c.audit[-400:])

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


@pytest.mark.timeout(_CELLS_CEILING_S)
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
    # DEF-3008: the floor raising at import -- the reasons module, the helper
    # itself, and the start refusal, whose failure is the hook's last resort.
    "floor": (f"{REASONS}.py", _RAISE),
    "helper": (f"{HELPER}.py", _RAISE),
    # the seam under the helper, and a name gone from one floor module that
    # another reads at import (the failure-mode review)
    "seam": ("../_json_safe.py", _RAISE),
    "renamed": ("_maintenance_mode.py", "\ndel relaunch_hint\n"),
    "refusal": (f"{REFUSAL}.py", _RAISE),
    # a raise in write_guard's own module body, after its imports: put in
    # before its last `__main__` block, never appended (an appended raise
    # comes after the one that ends the process, and never runs)
    "body": ("write_guard.py", _RAISE),
}
#: The plants put into the hook's own body rather than appended.
_IN_THE_BODY = frozenset({"body"})
#: The plants whose table rows run both ways (``unread`` lets nothing through).
_BOTH_WAYS = ("raised", "kept", "crash", "floor", "helper", "seam", "renamed", "refusal", "body")
#: The plant whose pass saves no copy, by the words its context says it in:
#: the start refusal itself is what failed (DEF-3008).
_NO_COPY = {"refusal": "No copy of the file was saved first"}
#: The plants whose pass writes no record: the audit writer imports the
#: helper, which did not import (DEF-3008), or the start refusal failed.
_NO_RECORD = frozenset({"helper", "seam", "refusal"})
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
    # DEF-3008: a floor module that raises is refused like any sibling, and its
    # restore passes, with its copy even where the helper (or the seam under
    # it) is what raised; a name gone from one floor module names that module;
    # the start refusal's own raise passes one exact command, through the last
    # resort, from any directory of the checkout.
    ("floor", _bash(f"git restore --source=HEAD -- tools/cc/hooks/{REASONS}.py"), True),
    ("floor", _bash(f"git restore {_REINJECT}"), False),
    ("helper", _bash(f"git restore --source=HEAD -- tools/cc/hooks/{HELPER}.py"), True),
    ("helper", _bash(f"git restore {_UNRELATED}"), False),
    ("seam", _bash("git restore --source=HEAD -- tools/cc/_json_safe.py"), True),
    ("seam", _bash(f"git restore {_UNRELATED}"), False),
    ("renamed", _bash("git restore --source=HEAD -- tools/cc/hooks/_maintenance_mode.py"), True),
    ("renamed", _bash(f"git restore {_REINJECT}"), False),
    ("refusal", _bash(f"git restore --source=HEAD -- :/tools/cc/hooks/{REFUSAL}.py"), True),
    ("refusal", {**_bash(f"git restore --source=HEAD -- :/tools/cc/hooks/{REFUSAL}.py"), "cwd": "tools/cc/hooks"},
     True),
    ("refusal", _bash(f"git restore --source=HEAD -- tools/cc/hooks/{REFUSAL}.py"), False),
    ("refusal", _bash(f"git restore :/tools/cc/hooks/{REFUSAL}.py"), False),
    ("refusal", _bash(f"git restore --source=HEAD -- :/tools/cc/hooks/{REFUSAL}.py; ls"), False),
    ("refusal", _bash(f"git restore --source=HEAD -- :/tools/cc/hooks/{REFUSAL}.py "), False),
    ("refusal", _bash("git restore --source=HEAD -- :/tools/cc/hooks/write_guard.py"), False),
    ("refusal", {"tool_name": "PowerShell",
                 "tool_input": {"command": f"git restore --source=HEAD -- :/tools/cc/hooks/{REFUSAL}.py"}}, False),
    ("refusal", {"tool_name": "Write", "tool_input": {"file_path": f"tools/cc/hooks/{REFUSAL}.py", "content": ""}},
     False),
    # a call the last resort cannot read is no restore
    ("refusal", {"tool_name": "Bash", "tool_input": {}}, False),
    ("unread", _bash(f"git restore --source=HEAD -- tools/cc/hooks/{HELPER}.py"), False),
    # a raise in the guard's own module body: its own restore passes, with its copy
    ("body", _bash("git restore --source=HEAD -- tools/cc/hooks/write_guard.py"), True),
    ("body", _bash(f"git restore {_UNRELATED}"), False),
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
    if plant in _IN_THE_BODY:
        _plant_in_the_body(target, text)
        return
    target.write_bytes(target.read_bytes() + text.encode("utf-8"))


def _run_payload(root: Path, hook: str, payload: dict, audit: Path,
                 allowance: RetryAllowance | None = None) -> subprocess.CompletedProcess:
    env = {**_ENV, "CLAUDE_PROJECT_DIR": str(root), "ESPALIER_AUDIT_DIR": str(audit)}
    return retry_a_budget_miss(lambda: subprocess.run(
        [sys.executable, str(root / "tools" / "cc" / "hooks" / hook)],
        input=json.dumps({"hook_event_name": "PreToolUse", "session_id": "wedged", "cwd": str(root), **payload}),
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
        env=env,
    ), env=env, cwd=str(root), allowance=allowance)


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
    allowance = RetryAllowance()  # the build's budget retries, shared by its threads (DEF-2057)

    def one(job: tuple[int, tuple[str, dict, bool]]) -> Restore:
        i, (plant, payload, passes) = job
        root = base / f"{i:02d}-{plant}"
        _plant(root, plant)
        audit = root / "audit"
        if "cwd" in payload:  # a row's cwd is relative to its own copy
            payload = {**payload, "cwd": str(root / payload["cwd"])}
        if "{taker}" in payload["tool_input"].get("command", ""):
            taker = _taker(_run_payload(root, "write_guard.py", _NOOP_INPUT["PreToolUse"], root / "taker",
                                        allowance))
            payload = _bash(payload["tool_input"]["command"].replace("{taker}", taker))
        run = _run_payload(root, "write_guard.py", payload, audit, allowance)
        result = Restore(plant, payload, passes, run.returncode, run.stdout, run.stderr,
                         _wedge_copies(root), _audit_text(audit))
        shutil.rmtree(root, ignore_errors=True)
        return result

    with ThreadPoolExecutor(max_workers=_POOL_WIDTH) as pool:
        return list(pool.map(one, enumerate(_RESTORE_TABLE)))


def _output(run: Restore) -> dict:
    text = run.stdout.strip()
    assert text.startswith("{") and len(text.splitlines()) == 1, (run.payload, run.stdout, run.stderr)
    return json.loads(text)["hookSpecificOutput"]


@pytest.mark.timeout(_CELLS_CEILING_S)
class TestAWedgedGuardNamesWhatRaised:
    def test_a_name_a_kept_pattern_module_lacks_names_it_on_the_first_mutation(self, tmp_path):
        # The failure-mode review on DEF-5087: write_guard loads _bash_patterns
        # on a mutation's first use, so a kept older copy lacking a name read
        # there met the crash guard, which said "restore write_guard.py". The
        # name is one the module binds and never reads itself (an older copy
        # lacks the name, not the code around it); a read-only call still passes.
        root = tmp_path / "kept-patterns"
        _copy_cc(root)
        _append(root, "tools/cc/hooks/_bash_patterns.py", "\ndel has_catastrophic_recursive_rm\n")
        audit = root / "audit"
        refused = _run_payload(root, "write_guard.py", _bash("touch notes.txt"), audit)
        out = json.loads(refused.stdout)["hookSpecificOutput"]
        reason = out["permissionDecisionReason"]
        assert refused.returncode == 0 and out["permissionDecision"] == "deny", (refused.stdout, refused.stderr[-300:])
        assert reason.startswith("write_guard internal error (AttributeError at tools/cc/hooks/write_guard.py:"), reason
        assert ("takes `has_catastrophic_recursive_rm` from tools/cc/hooks/_bash_patterns.py, which lacks it"
                in reason), reason
        assert "If an upgrade kept _bash_patterns.py as yours" in reason, reason
        assert "`espalier upgrade --execute .`" in reason and "tools/cc/hooks/_bash_patterns.py" in reason, reason
        assert '"kept": "tools/cc/hooks/_bash_patterns.py"' in _audit_text(audit), _audit_text(audit)[-400:]
        read = _run_payload(root, "write_guard.py", _NOOP_INPUT["PreToolUse"], audit)
        assert read.returncode == 0 and not read.stdout.strip(), (read.stdout, read.stderr[-300:])

    def test_a_kept_reasons_module_without_the_template_keeps_the_placed_text(self, tmp_path):
        # The fix batch's failure-mode review: a kept _denial_reasons.py from
        # before the kept-file template is the likeliest kept file on this
        # path, and a bare read of the template raised into the catch-all,
        # whose text names no file, no line and no restore. It keeps the
        # placed crash text instead.
        root = tmp_path / "kept-reasons"
        _copy_cc(root)
        _append(root, "tools/cc/hooks/_bash_patterns.py", "\ndel has_catastrophic_recursive_rm\n")
        _append(root, "tools/cc/hooks/_denial_reasons.py", "\ndel WRITE_GUARD_CRASHED_ON_A_KEPT_FILE\n")
        refused = _run_payload(root, "write_guard.py", _bash("touch notes.txt"), root / "audit")
        reason = json.loads(refused.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        assert reason.startswith("write_guard internal error (AttributeError at tools/cc/hooks/write_guard.py:"), reason
        assert "`git restore --source=HEAD -- tools/cc/hooks/write_guard.py`" in reason, reason

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


@pytest.mark.timeout(_CELLS_CEILING_S)
class TestAFloorThatRaisesIsRefused:
    """DEF-3008: the floor of the guard -- the helper, with
    ``tools/cc/_json_safe.py`` under it, and the reasons module, with
    ``_maintenance_mode`` under it -- imported outside it, so a floor module
    that raised was exit 1 on every deny hook (driven 2026-10-16, 16 of 16).
    Now each deny hook imports the start refusal first and alone, and the floor
    joins the guard; the start refusal's own failure is each hook's last
    resort."""

    def test_every_floor_plant_on_every_deny_hook_is_refused_never_exit_one(self, cells):
        floor = [c for c in cells if c.kind == "floor"]
        assert {(c.hook, c.name) for c in floor} == {(h, n) for h in deny_hooks() for n in FLOOR_PLANTS}
        bad = [_summary(c) for c in floor if not (c.rc == 0 and _is_refusal(c) and not c.stderr.strip()
                                                  and len(c.stdout.strip().splitlines()) == 1)]
        assert not bad, bad

    def test_a_floor_module_that_raises_is_named_with_its_line_and_restore(self, cells):
        for c in (c for c in cells if c.kind == "floor" and c.name != REFUSAL):
            reason, rel = _reason(c), _floor_rel(c.name)
            assert reason.startswith(f"{c.hook[:-3]} cannot start: {rel} raised KeyError: 1 at line "), reason
            assert f"`git restore --source=HEAD -- {rel}`" in reason, reason
            assert "upgrade --execute" not in reason, reason

    def test_a_start_refusal_that_cannot_import_is_each_hooks_last_resort(self, cells):
        # The last resort names the one file, the one command (read from the
        # top of the checkout, so it runs from any directory) and the upgrade
        # for a HEAD without the file, and ends on the clause the end-to-end
        # bench reads a start refusal by.
        for c in (c for c in cells if c.kind == "floor" and c.name == REFUSAL):
            reason = _reason(c)
            assert reason.startswith(
                f"{c.hook[:-3]} cannot start: tools/cc/hooks/{REFUSAL}.py raised KeyError;"), reason
            assert f"`git restore --source=HEAD -- :/tools/cc/hooks/{REFUSAL}.py`" in reason, reason
            assert "`espalier upgrade --execute .`" in reason, reason
            assert reason.endswith("Every call this hook judges is refused until then."), reason

    @pytest.mark.parametrize("plant", [REASONS, REFUSAL, "body"])
    def test_a_stop_refused_at_start_lets_the_loop_signal_through(self, plant, tmp_path):
        # The protocol's loop signal: the Stop a start refusal blocked is
        # continued with stop_hook_active set, and that one goes through, so a
        # broken start pauses a Stop once and never locks it (the
        # failure-mode review: both refusals re-blocked it). `body`: a raise
        # in the Stop hook's own module body, refused the same way.
        root = tmp_path / f"loop-{plant}"
        _copy_cc(root)
        if plant == "body":
            _plant_in_the_body(root / "tools" / "cc" / "hooks" / "stop_gate.py", _RAISE)
        else:
            _append(root, _floor_rel(plant), _RAISE)
        runs = {}
        for active in (False, True):
            runs[active] = subprocess.run(
                [sys.executable, str(root / "tools" / "cc" / "hooks" / "stop_gate.py")],
                input=json.dumps({"hook_event_name": "Stop", "session_id": "loop", "cwd": str(root),
                                  "stop_hook_active": active}),
                cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
                env={**_ENV, "CLAUDE_PROJECT_DIR": str(root), "ESPALIER_AUDIT_DIR": str(root / "audit"),
                     "ESPALIER_STOP_GATE": "light"})
        assert runs[False].returncode == 0 and json.loads(runs[False].stdout)["decision"] == "block", runs[False]
        assert runs[True].returncode == 0 and not runs[True].stdout.strip() and not runs[True].stderr.strip(), \
            runs[True]

    def test_a_kept_deny_hook_that_calls_the_refusals_old_home_is_still_refused(self, tmp_path):
        # An upgrade keeps a deny hook the adopter edited and regenerates the
        # reasons module; a kept hook from before the move calls the refusal
        # there, so the name stays reachable there (the failure-mode review:
        # exit 1 on 4 of 4 without it).
        root = tmp_path / "kept-hook"
        _copy_cc(root)
        hook = root / "tools" / "cc" / "hooks" / "write_guard.py"
        text = hook.read_text(encoding="utf-8")
        moved = f'{REFUSAL}.refuse_on_helper_skew("write_guard"'
        assert text.count(moved) == 1, "the handler's shape moved; update this control with it"
        hook.write_text(text.replace(moved, f'{REASONS}.refuse_on_helper_skew("write_guard"'), encoding="utf-8")
        _append(root, "tools/cc/hooks/_integrity.py", _RAISE)
        run = _run_hook(root, "write_guard.py", "PreToolUse")
        out = json.loads(run.stdout)["hookSpecificOutput"]
        assert run.returncode == 0 and out["permissionDecision"] == "deny", (run.returncode, run.stdout, run.stderr)
        assert "tools/cc/hooks/_integrity.py raised KeyError" in out["permissionDecisionReason"], out

    def test_the_start_refusal_deploys_before_the_hooks_that_import_it(self):
        # init and upgrade write the deploy list in its order, so a deploy that
        # stops partway never leaves a new deny hook without the module it
        # imports first (the failure-mode review: the helpers came last).
        from espalier.cli import INIT_HOOK_SCRIPTS
        first = INIT_HOOK_SCRIPTS.index(f"tools/cc/hooks/{REFUSAL}.py")
        assert all(first < INIT_HOOK_SCRIPTS.index(f"tools/cc/hooks/{h}") for h in deny_hooks()), INIT_HOOK_SCRIPTS

    @pytest.mark.parametrize("hook", sorted(deny_hooks()))
    def test_no_sibling_imports_at_the_module_top_outside_a_guard(self, hook):
        # The class, read from the source: a module-level import of a sibling
        # outside every `try` is one whose failure is exit 1, and so is one
        # under a `try` that catches less than Exception (the `_json_safe`
        # shape under the helper: a KeyError passes `except ImportError`). An
        # `if TYPE_CHECKING:` body never runs, so only its `else` is read
        # (write_guard's type-only imports of the pattern path, DEF-946).
        bare: list[str] = []

        def visit(stmts: list[ast.stmt]) -> None:
            for s in stmts:
                if isinstance(s, ast.Import):
                    bare.extend(a.name for a in s.names if _is_sibling(a.name))
                elif isinstance(s, ast.ImportFrom) and s.module and _is_sibling(s.module):
                    bare.append(s.module)
                elif isinstance(s, ast.If) and isinstance(s.test, ast.Name) and s.test.id == "TYPE_CHECKING":
                    visit(s.orelse)
                elif isinstance(s, (ast.If, ast.With)):
                    visit(s.body)
                    visit(getattr(s, "orelse", []))

        tree = _parse(hook[:-3])
        visit(tree.body)
        assert not bare, (hook, bare)
        for s in tree.body:
            if isinstance(s, ast.Try) and _sibling_imports(ast.Module(body=s.body, type_ignores=[])):
                caught = {h.type.id for h in s.handlers if isinstance(h.type, ast.Name)}
                assert caught & {"Exception", "BaseException"}, (hook, s.lineno, sorted(caught))

    @pytest.mark.parametrize("hook", sorted(deny_hooks()))
    def test_the_start_refusal_imports_first_and_alone(self, hook):
        first = next(s for s in _parse(hook[:-3]).body
                     if isinstance(s, ast.Try) and _sibling_imports(ast.Module(body=s.body, type_ignores=[])))
        assert _sibling_imports(ast.Module(body=first.body, type_ignores=[])) == {REFUSAL}, hook
        # and its last resort ends the process at exit 0: one that ran on
        # would judge the call too, a second decision on the channel
        (handler,) = first.handlers
        last = handler.body[-1]
        assert (isinstance(last, ast.Raise) and isinstance(last.exc, ast.Call)
                and isinstance(last.exc.func, ast.Name) and last.exc.func.id == "SystemExit"
                and [ast.literal_eval(a) for a in last.exc.args] == [0]), (hook, ast.dump(last))

    def test_the_start_refusal_imports_no_sibling_at_its_top(self):
        # Any sibling may be the one that failed, so the refusal reads them
        # lazily, inside the functions that use them.
        top = [n for s in _parse(REFUSAL).body
               if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
               for n in ast.walk(s) if isinstance(n, (ast.Import, ast.ImportFrom))]
        assert top and not _sibling_imports(ast.Module(body=top, type_ignores=[])), [ast.dump(n) for n in top]


@pytest.mark.timeout(_CELLS_CEILING_S)
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
        for r in (r for r in restores if r.passes and r.plant not in _NO_COPY):
            assert len(r.copies) == 1 and r.copies[0].endswith(".py.txt"), (r.plant, r.payload, r.copies)
            assert r.copies[0] in _output(r)["additionalContext"], _output(r)
            # the audit writer imports the helper, so where the helper did not
            # import there is no record, and nothing says there is (DEF-3008)
            recorded = "pretooluse_failed_open_wedge_restore" in r.audit
            assert recorded == (r.plant not in _NO_RECORD), (r.plant, r.audit[-400:])
        # The pass that cannot copy says so in its context: the start refusal,
        # which saves the copy, is the module that failed (DEF-3008).
        for r in (r for r in restores if r.passes and r.plant in _NO_COPY):
            assert r.copies == [] and _NO_COPY[r.plant] in _output(r)["additionalContext"], (r.plant, _output(r))
            assert "pretooluse_failed_open_wedge_restore" not in r.audit, r.audit[-400:]
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
        # Both files: the taker's restore first, then the helper as the file you
        # edited. Which file takes the name first is an import-order fact (the
        # eager name read, since the pattern modules load on first use, DEF-946).
        assert "(or the same command for the file you edited, if it is tools/cc/hooks/_hook_utils.py" in reason, reason
        assert "`git restore --source=HEAD -- tools/cc/hooks/_hook_utils.py`" not in reason, reason
        # The taker is write_guard itself: its eager helper-name read runs
        # before any pattern module loads, so the restore it names first is its own.
        assert "git restore --source=HEAD -- tools/cc/hooks/write_guard.py" in reason, reason

    def test_a_quoted_shell_operator_refuses_even_where_the_path_would_match(self, tmp_path):
        # The operator check is its own refusal, not the operand count's: a
        # restorable file whose name holds `;` is refused when quoted. Driven
        # in a child, the hook modules' loader contract (never in-suite).
        script = (
            "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); import _start_refusal as d\n"
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
            "import sys; sys.path.insert(0, sys.argv[1]); import _hook_utils as h, _start_refusal as d\n"
            "from pathlib import Path; cc = Path(d.__file__).resolve().parent.parent\n"
            "print(d._missing_sibling_name(AttributeError('x', name='STATE_DIR', obj=h), cc))\n"
            "r = d._missing_sibling_name(AttributeError('x', name='no_such_helper_name', obj=h), cc)\n"
            "print(r[0], r[1].name)\n"
        )
        out = subprocess.run([sys.executable, "-c", script, str(HOOKS_DIR)], capture_output=True, text=True,
                             encoding="utf-8", env=_ENV, cwd=str(REPO_ROOT), timeout=45)
        assert out.stdout.split() == ["None", "no_such_helper_name", "_hook_utils.py"], (out.stdout, out.stderr)

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
            "import sys, json; sys.path.insert(0, sys.argv[1]); import _hook_utils, _start_refusal as d\n"
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
         *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)


def _committed_copy(root: Path) -> None:
    _copy_cc(root)
    # The warm copy's bytecode is never committed, as a real checkout's is not:
    # a tracked `.pyc` that a spawn rewrites would be a modified file to git.
    (root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
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


def _merge_conflict(root: Path, rel: str = "tools/cc/hooks/_reinject.py") -> str:
    # A merge that conflicts in a hook file leaves markers, a SyntaxError.
    for branch, text in (("side", "\nSIDE = 1\n"), ("main", "\nSIDE = 2\n")):
        if branch == "side":
            assert _git(root, "switch", "-q", "-c", "side").returncode == 0
        else:
            assert _git(root, "switch", "-q", "main").returncode == 0
        _append(root, rel, text)
        assert _git(root, "commit", "-q", "-am", branch).returncode == 0
    assert _git(root, "merge", "-q", "side").returncode != 0
    return rel


def _floor_raises(root: Path) -> str:
    # DEF-3008: a floor module raises at import, outside every sibling's frame.
    _append(root, "tools/cc/hooks/_denial_reasons.py", "\nraise KeyError(5)\n")
    return "tools/cc/hooks/_denial_reasons.py"


def _floor_name_gone(root: Path) -> str:
    # A name gone from one floor module raises in the module that reads it;
    # the file to restore is the one the name left (the failure-mode review).
    _append(root, "tools/cc/hooks/_maintenance_mode.py", "\ndel relaunch_hint\n")
    return "tools/cc/hooks/_maintenance_mode.py"


def _pattern_merge_conflict(root: Path) -> str:
    # The same markers in a module the guard loads on first use: a SyntaxError
    # raised at that load, which the crash guard reads by its filename.
    return _merge_conflict(root, "tools/cc/hooks/_speedbump.py")


_SCENARIOS = {"staged": _staged_name_error, "circular": _circular, "new-module": _new_module,
              "merge-conflict": _merge_conflict, "pattern-merge-conflict": _pattern_merge_conflict,
              "floor": _floor_raises, "floor-name-gone": _floor_name_gone}


@pytest.mark.timeout(_CELLS_CEILING_S)
class TestTheNamedRestoreRepairsTheGuard:
    """End to end, with real git: the refusal names a restore of the edited
    file, the wedged guard lets that command through, git runs it, and the
    guard starts again. The table above judges the hook's JSON; this is the
    oracle that the command it names is the repair."""

    #: The scenarios that break `_bash_patterns` or `_speedbump`, which the
    #: guard loads on a mutation's first use (DEF-946): a read-only call passes
    #: while they are broken, so the file can be read, and a mutation meets the
    #: crash guard, which names the file and lets the same restore through.
    _ON_THE_PATTERN_PATH = frozenset({"staged", "circular", "new-module", "pattern-merge-conflict"})
    _MUTATION = {"tool_name": "Edit", "tool_input": {"file_path": "notes.txt", "old_string": "a", "new_string": "b"}}

    @pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
    def test_the_command_the_refusal_names_repairs_the_wedge(self, tmp_path, scenario):
        root = tmp_path / scenario
        _committed_copy(root)
        edited = _SCENARIOS[scenario](root)
        audit = root / "audit"
        on_the_path = scenario in self._ON_THE_PATTERN_PATH
        payload = self._MUTATION if on_the_path else _NOOP_INPUT["PreToolUse"]
        refused = _run_payload(root, "write_guard.py", payload, audit)
        reason = json.loads(refused.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        assert ("internal error" if on_the_path else "cannot start") in reason and edited in reason, reason
        if on_the_path:
            read = _run_payload(root, "write_guard.py", _NOOP_INPUT["PreToolUse"], audit)
            assert read.returncode == 0 and not read.stdout.strip(), (read.stdout, read.stderr[-300:])
        command = f"git restore --source=HEAD -- {edited}"
        assert "`git restore --source=HEAD -- " in reason, reason
        passed = _run_payload(root, "write_guard.py", _bash(command), audit)
        out = json.loads(passed.stdout)["hookSpecificOutput"]
        assert "permissionDecision" not in out and "was let through" in out["additionalContext"], out
        ran = _git(root, *command.split()[1:])
        assert ran.returncode == 0, ran.stderr
        judged = _run_payload(root, "write_guard.py", payload, audit)
        assert judged.returncode == 0 and "deny" not in judged.stdout, (judged.stdout, judged.stderr[-300:])

    def test_the_last_resorts_command_repairs_it_from_any_directory(self, tmp_path):
        # DEF-3008: the start refusal itself cannot import. The last resort
        # names one command; the guard lets exactly it through; git runs it
        # from the hooks directory, where a maintainer editing them stands
        # (the failure-mode review: a root-relative path failed there); and
        # the guard judges again.
        root = tmp_path / "last-resort"
        _committed_copy(root)
        _append(root, f"tools/cc/hooks/{REFUSAL}.py", _RAISE)
        audit = root / "audit"
        refused = _run_payload(root, "write_guard.py", _NOOP_INPUT["PreToolUse"], audit)
        reason = json.loads(refused.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        command = reason.split("Restore it to HEAD: `", 1)[1].split("`", 1)[0]
        assert command == f"git restore --source=HEAD -- :/tools/cc/hooks/{REFUSAL}.py", reason
        passed = _run_payload(root, "write_guard.py", _bash(command), audit)
        out = json.loads(passed.stdout)["hookSpecificOutput"]
        assert "permissionDecision" not in out and "was let through" in out["additionalContext"], out
        ran = _git(root / "tools" / "cc" / "hooks", *command.split()[1:])
        assert ran.returncode == 0, ran.stderr
        judged = _run_payload(root, "write_guard.py", _NOOP_INPUT["PreToolUse"], audit)
        assert judged.returncode == 0 and "deny" not in judged.stdout, (judged.stdout, judged.stderr[-300:])


# ── the guard is reachable, and earns its red ────────────────────────────────

@pytest.mark.timeout(_CELLS_CEILING_S)
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
        # becomes a bare re-raise, the bare-import shape this lane replaced, and
        # the module-body exception hook is not installed) and delete a floor
        # name; the hook dies with exit 1 -- exactly what test_no_cell_exits_one
        # exists to catch. Then the body cells' red: the exception hook alone
        # disarmed and a raise planted in the hook's own body, exit 1 again.
        hooked = '    _start_refusal.refuse_on_body_raise("write_guard", "PreToolUse")\n'
        armed = '    if __name__ != "__main__":\n        raise\n    _start_refusal.refuse_on_helper_skew("write_guard", "PreToolUse", _skew)\n'
        for shape in ("import", "body"):
            root = tmp_path / f"prefix-{shape}"
            _copy_cc(root)
            hook = root / "tools" / "cc" / "hooks" / "write_guard.py"
            text = hook.read_text(encoding="utf-8")
            assert text.count(armed) == 1 and text.count(hooked) == 1, "the guard's shape moved; update this control with it"
            text = text.replace(hooked, "")
            if shape == "import":
                text = text.replace(armed, "    raise\n")
                _skew(root, "payload_cwd")
            else:
                at = text.rindex('\nif __name__ == "__main__":\n')
                text = text[:at] + _RAISE + text[at:]
            hook.write_text(text, encoding="utf-8")
            run = _run_hook(root, "write_guard.py", "PreToolUse")
            assert run.returncode == 1, (shape, run.returncode, run.stdout, run.stderr)
            assert run.stdout.strip() == "", (shape, run.stdout)

    def test_the_last_resort_disarmed_exits_one_so_the_floor_cells_can_red(self, tmp_path):
        # Earn the last resort's red (DEF-3008): on a copy, its handler becomes
        # a bare re-raise and the start refusal raises at import; the hook dies
        # with exit 1, the shape the floor cells exist to catch.
        root = tmp_path / "lastresort"
        _copy_cc(root)
        hook = root / "tools" / "cc" / "hooks" / "write_guard.py"
        text = hook.read_text(encoding="utf-8")
        armed = '    if __name__ != "__main__":\n        raise\n    _LAST_RESTORE = '
        assert text.count(armed) == 1, "the last resort's shape moved; update this control with it"
        hook.write_text(text.replace(armed, "    raise\n    _LAST_RESTORE = "), encoding="utf-8")
        refusal = root / "tools" / "cc" / "hooks" / f"{REFUSAL}.py"
        refusal.write_bytes(refusal.read_bytes() + _RAISE.encode("utf-8"))
        run = _run_hook(root, "write_guard.py", "PreToolUse")
        assert run.returncode == 1 and run.stdout.strip() == "", (run.returncode, run.stdout, run.stderr)

    def test_an_in_process_importer_of_a_broken_start_refusal_sees_the_real_error(self, tmp_path):
        # The last resort keeps the __name__ gate: imported rather than run,
        # each deny hook re-raises the start refusal's own error.
        root = tmp_path / "imported-refusal"
        _copy_cc(root)
        hooks = root / "tools" / "cc" / "hooks"
        refusal = hooks / f"{REFUSAL}.py"
        refusal.write_bytes(refusal.read_bytes() + _RAISE.encode("utf-8"))
        for hook in sorted(deny_hooks()):
            r = subprocess.run(
                [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(hooks)!r}); import {hook[:-3]}"],
                capture_output=True, text=True, encoding="utf-8", env={**_ENV, "CLAUDE_PROJECT_DIR": str(root)},
                cwd=str(root), timeout=45)
            assert r.returncode == 1 and "KeyError" in r.stderr and not r.stdout.strip(), (hook, r.stdout, r.stderr)


class TestTheCopiedTreeIsWarm:
    """DEF-4114: the copies these spawns run in carry valid bytecode, a plant
    still runs its own source, and the two spawn pools are no wider than the
    runner's cores."""

    def test_a_copied_tree_carries_valid_bytecode_for_the_pattern_module(self, tmp_path):
        _copy_cc(tmp_path)
        src = tmp_path / "tools" / "cc" / "hooks" / "_bash_patterns.py"
        pyc = Path(importlib.util.cache_from_source(str(src)))
        assert pyc.is_file(), f"no bytecode beside the copy's {src.name}: its first spawn compiles it in the budget"
        data = pyc.read_bytes()
        assert data[:4] == importlib.util.MAGIC_NUMBER, "bytecode of another interpreter"
        flags = int.from_bytes(data[4:8], "little")
        if flags == 0:  # timestamp bytecode: the copy's own mtime and size
            st = src.stat()
            assert int.from_bytes(data[8:12], "little") == int(st.st_mtime) & 0xFFFFFFFF
            assert int.from_bytes(data[12:16], "little") == st.st_size & 0xFFFFFFFF
        else:  # hash bytecode (SOURCE_DATE_EPOCH set): the copy's own bytes
            assert data[8:16] == importlib.util.source_hash(src.read_bytes())

    def test_a_plant_in_a_warm_copy_runs_its_own_source_at_the_same_mtime(self, tmp_path):
        # The plant keeps the source's mtime, so only its size tells the
        # bytecode it is stale: what every plant in this file relies on.
        _copy_cc(tmp_path)
        hooks = tmp_path / "tools" / "cc" / "hooks"
        module = hooks / "_maintenance_mode.py"
        before = module.stat()
        module.write_bytes(module.read_bytes() + b"\nPLANTED_HERE = 1\n")
        os.utime(module, ns=(before.st_atime_ns, before.st_mtime_ns))
        r = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, {str(hooks)!r}); import _maintenance_mode as m; "
             "print(getattr(m, 'PLANTED_HERE', 0))"],
            capture_output=True, text=True, encoding="utf-8", env=_ENV, cwd=str(tmp_path), timeout=scaled(45))
        assert r.returncode == 0 and r.stdout.strip() == "1", (r.stdout, r.stderr)

    def test_the_warm_template_carries_this_processs_lock_under_an_owned_prefix(self):
        from tests import _temp_sweep

        work = _warm_cc().parent
        assert work.name.startswith(_temp_sweep.OWNED_PREFIXES), work.name
        assert _temp_sweep.lock_is_ours(work), "a killed run's warm copy would never be swept"

    def test_the_spawn_pools_are_no_wider_than_the_cores(self):
        assert 1 <= _POOL_WIDTH <= min(6, os.cpu_count() or 1)
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        widths = [kw.value for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and getattr(node.func, "id", None) == "ThreadPoolExecutor"
                  for kw in node.keywords if kw.arg == "max_workers"]
        assert len(widths) == 2 and all(isinstance(w, ast.Name) and w.id == "_POOL_WIDTH" for w in widths), \
            [ast.dump(w) for w in widths]
