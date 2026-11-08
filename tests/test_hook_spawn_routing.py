"""Where tests/_hook_spawn.py must be used, and what it must agree with
(DEF-2014). Contract rows: they read source, never spawn.

The routing pin derives its population from the tree: every spawn in a test
module that runs write_guard (the hook whose budget refusal a verdict row
reads as a wrong answer) or the statusline, under a fixed bound no longer than
the helper's, must go through ``run_hook_through``, so a new row cannot bring
the bare fixed bound back. A spawn runs one of them when its script, or the
local binding the script is built from, names it; or when the spawn sits in a
helper whose script is built from ``HOOKS_DIR`` and one of the helper's own
parameters, in a module that names write_guard (the generic hook runners). A
script's binding is read in the spawning function, else at the module's top
level (``HOOK = ... / "write_guard.py"`` hid ``_decide`` from this pin until
DEF-5066). Spawns with a longer bound, or none, keep it (they have the slack
the 15 s rows lacked) and a timeout is not retried; but write_guard's budget
refuses within its 4.0 s deadline whatever the bound, and its refusal is a
deny on the decision channel, so the second pin derives every write_guard
spawn by hand at any bound the same way and holds the function that spawns it
to write the spawn inside ``retry_a_budget_miss`` (one retry of the refusal,
DEF-2057) or hand the result to ``not_a_budget_miss``; either fails the row as
a miss instead of a verdict.
The bench pin holds the same line under bench/ (DEF-5071), keyed on the
reading rather than the spawn: a function that compares a value with ``deny``
reads the refusal apart through ``bench/run_benchmark.py``'s reader.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import NamedTuple

from tests import _hook_spawn as hs
from tests._live_tree import checkout_glob, checkout_rglob

TESTS = Path(__file__).resolve().parent
HOOKS = TESTS.parent / "tools" / "cc" / "hooks"
BENCH = TESTS.parent / "bench"
#: bench/run_benchmark.py's readers of write_guard's budget refusal (DEF-5071).
_BENCH_BUDGET_READERS = {"judged_within_budget", "budget_refused"}

_SPAWNS = {"run", "Popen", "check_output", "check_call"}
#: tests/_hook_spawn.py's readers of the budget's refusal: the one that
#: retries it, the spawn written inside its call (DEF-2057), and the one that
#: reads a finished result.
_READERS = {"retry_a_budget_miss", "not_a_budget_miss"}
_NAMES = re.compile(r"write_guard|statusline|STATUSLINE")
#: Modules whose write_guard spawns stay bare, each with its reason.
_EXEMPT = {
    # It drives the budget's refusal on purpose, and times the process exit.
    "test_write_guard_time_budget.py",
}
#: write_guard spawns by hand whose result no budget refusal can reach, each
#: with its reason. Not checked for liveness: with the up-to-date rule off, a
#: lane that routes or renames the spawn would merge clean and red main.
_UNREAD_SITES = {
    ("test_checkout_sync.py", "_wedge_restore"):
        "write_guard answers the wedge restore from its start refusal at import (a sibling it "
        "imports raises), before main() starts the budget",
}


def _number(node: ast.AST | None) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    return None


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {a.arg for a in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]}


def _callee(call: ast.Call) -> str | None:
    return getattr(call.func, "id", getattr(call.func, "attr", None))


class Spawn(NamedTuple):
    """One spawn of write_guard or the statusline, written by hand in a test module."""
    line: int
    function: str
    bound: float | None
    write_guard: bool  # the statusline otherwise
    read: bool  # the spawning function hands its result to not_a_budget_miss


def hook_spawns(path: Path) -> list[Spawn]:
    """Each spawn in ``path`` that runs write_guard or the statusline by hand,
    at any bound or none: its bound, which of the two it runs, and whether the
    function that spawns it hands the result to ``not_a_budget_miss`` (the
    spawn written inside that call, or the last value bound to a name the
    call is given). The argv is a list or tuple, written in the call or bound
    to a name; the script is its first element past the interpreter's flags.
    Not read: a script held in a closure, a class attribute, a fixture
    parameter or an import not spelled write_guard; a shell string; a binding
    by tuple unpacking, ``with`` or ``:=``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {a.asname or a.name for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "subprocess"
                for a in n.names if a.name in _SPAWNS}
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    owner: dict[int, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for fn in functions:  # outer first, so an inner function's nodes end up its own
        for node in ast.walk(fn):
            owner[id(node)] = fn
    module_values: dict[str, list[ast.expr]] = {}
    for n in tree.body:
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                if isinstance(t, ast.Name):
                    module_values.setdefault(t.id, []).append(n.value)
    module_binds = {name: " ".join(ast.unparse(v) for v in values) for name, values in module_values.items()}

    def names_write_guard(decorator: ast.expr) -> bool:
        text = ast.unparse(decorator)
        return "write_guard" in text or any(
            "write_guard" in module_binds.get(n.id, "") for n in ast.walk(decorator) if isinstance(n, ast.Name))

    def called_with_write_guard(name: str) -> bool:
        """A call of ``name`` passes write_guard: in its own arguments, or in a
        parameter its calling test takes from a parametrize list (written in
        the decorator, or a module-level list it names)."""
        for call in ast.walk(tree):
            if not (isinstance(call, ast.Call) and _callee(call) == name):
                continue
            if "write_guard" in ast.unparse(call):
                return True
            caller = owner.get(id(call))
            passed = {n.id for a in [*call.args, *(k.value for k in call.keywords)] for n in ast.walk(a)
                      if isinstance(n, ast.Name)}
            if caller is not None and passed & _params(caller) and any(
                    names_write_guard(d) for d in caller.decorator_list):
                return True
        return False

    found = []
    for fn in functions:
        binds: dict[str, list[ast.expr]] = {}
        assigns: dict[str, list[tuple[int, ast.expr]]] = {}  # name -> (line, value), plain and annotated
        for n in ast.walk(fn):
            targets = n.targets if isinstance(n, ast.Assign) else (
                [n.target] if isinstance(n, ast.AnnAssign) and n.value is not None else [])
            for t in targets:
                if isinstance(t, ast.Name):
                    binds.setdefault(t.id, []).append(n.value)
                    assigns.setdefault(t.id, []).append((n.lineno, n.value))
            if isinstance(n, (ast.For, ast.AsyncFor)) and isinstance(n.target, ast.Name):
                binds.setdefault(n.target.id, []).append(n.iter)

        def last_bound(name: str, line: int) -> ast.expr | None:
            earlier = [(at, v) for at, v in assigns.get(name, []) if at <= line]
            return max(earlier, key=lambda pair: pair[0])[1] if earlier else None

        inside: set[int] = set()
        read_values: set[int] = set()
        for c in ast.walk(fn):
            if isinstance(c, ast.Call) and _callee(c) in _READERS and owner.get(id(c)) is fn:
                for a in [*c.args, *(k.value for k in c.keywords)]:
                    for n in ast.walk(a):
                        inside.add(id(n))
                        if isinstance(n, ast.Name) and (value := last_bound(n.id, c.lineno)) is not None:
                            read_values.add(id(value))
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call) and owner.get(id(call)) is fn and (
                    getattr(call.func, "attr", None) in _SPAWNS
                    or (isinstance(call.func, ast.Name) and call.func.id in imported))):
                continue
            argv = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "args"), None)
            if isinstance(argv, ast.Name):
                argv = last_bound(argv.id, call.lineno) or (module_values.get(argv.id) or [None])[-1]
            if not (isinstance(argv, (ast.List, ast.Tuple)) and len(argv.elts) >= 2):
                continue
            at = 1  # past the interpreter's flags: -X utf8, -W error, -B, -I ...
            while at < len(argv.elts) and isinstance(argv.elts[at], ast.Constant) and \
                    str(argv.elts[at].value).startswith("-") and argv.elts[at].value not in ("-c", "-m"):
                at += 2 if argv.elts[at].value in ("-X", "-W") else 1
            if at >= len(argv.elts):
                continue
            bound = _number(next((k.value for k in call.keywords if k.arg == "timeout"), None))
            exprs = [argv.elts[at]]
            for _ in range(2):  # the script's binding (local, else top level), and one built from another
                names = {n.id for e in exprs for n in ast.walk(e) if isinstance(n, ast.Name)}
                exprs += [v for name in names for v in (binds.get(name) or module_values.get(name, []))
                          if v not in exprs]
            names = {n.id for e in exprs for n in ast.walk(e) if isinstance(n, ast.Name)}
            text = " ".join(ast.unparse(e) for e in exprs)
            write_guard = "write_guard" in text or (bool(names & _params(fn)) and called_with_write_guard(fn.name))
            if write_guard or _NAMES.search(text):
                read = id(call) in inside or id(call) in read_values
                found.append(Spawn(call.lineno, fn.name, bound, write_guard, read))
    return found


def bare_spawns_of_the_class(path: Path) -> list[str]:
    """``line function`` for each spawn in ``path`` that runs write_guard or the
    statusline under a fixed bound no longer than the helper's, by hand."""
    return [f"{s.line} {s.function}" for s in hook_spawns(path) if s.bound is not None and s.bound <= hs.HOOK_S]


def refusals_read_as_verdicts(path: Path) -> list[str]:
    """``line function`` for each write_guard spawn in ``path`` by hand, at any
    bound or none, whose result the spawning function never hands to
    ``not_a_budget_miss``."""
    return [f"{s.line} {s.function}" for s in hook_spawns(path) if s.write_guard and not s.read]


def test_every_write_guard_and_statusline_spawn_routes_through_the_helper():
    stray = {
        path.name: rows
        for path in checkout_glob(TESTS, "test_*.py")
        if path.name not in _EXEMPT and (rows := bare_spawns_of_the_class(path))
    }
    assert not stray, (
        "run these through tests._hook_spawn.run_hook_through (DEF-2014), or give them a "
        f"bound past {hs.HOOK_S:.0f} s with the reason and hand a write_guard result to "
        f"not_a_budget_miss: {stray}")


def test_every_bare_write_guard_spawn_reads_the_budgets_refusal_apart():
    """DEF-5066: a write_guard spawn kept out of the helper by its longer bound,
    or by none, read the budget's refusal as the verdict it looks like, so a
    loaded windows-latest runner redded an ALLOW row as SOFT
    (``test_guard_false_positives.py::_decide``, run 41439992695) and a
    must-deny row passed on a judgment that never finished. The function that
    spawns hands the result to ``not_a_budget_miss``, or the spawn goes
    through ``run_hook_through``; a site no refusal can reach says why."""
    stray = {
        path.name: rows
        for path in checkout_glob(TESTS, "test_*.py")
        if path.name not in _EXEMPT and (rows := [
            row for row in refusals_read_as_verdicts(path) if (path.name, row.split()[1]) not in _UNREAD_SITES])
    }
    assert not stray, (
        "write each spawn inside tests._hook_spawn.retry_a_budget_miss (or hand its result to "
        "not_a_budget_miss) in the function that spawns it, or route the spawn through "
        f"run_hook_through (DEF-5066, DEF-2057): {stray}")


def test_the_read_population_is_not_empty():
    """The second pin's non-vacuity: the spawns that hand their result over,
    counted the same way, must be there. 2026-11-03: 6 to 5, when the
    launcher-only write_guard row moved onto the shared wired launcher, which
    the next test pins."""
    read = sum(1 for path in checkout_glob(TESTS, "test_*.py") if path.name not in _EXEMPT
               for spawn in hook_spawns(path) if spawn.write_guard and spawn.read)
    assert read >= 5, (
        f"{read} write_guard spawns hand their result to not_a_budget_miss, under the floor of 5: "
        "if one now goes through run_hook_through, lower the floor to the count left, never to 0")


def test_the_wired_launcher_reads_the_budgets_refusal_apart():
    """``tests/_hook_runner.py::run_hook_as_wired`` launches whichever hook a
    tree's settings wire, write_guard among them, under a bound past the
    helper's. Its script comes from the settings file, so the pins above, which
    read a script by its name, cannot tell it is write_guard's: its one spawn
    sits inside ``not_a_budget_miss`` instead, read here."""
    tree = ast.parse((TESTS / "_hook_runner.py").read_text(encoding="utf-8"))
    launcher = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_hook_as_wired")
    spawns = [c for c in ast.walk(launcher) if isinstance(c, ast.Call) and getattr(c.func, "attr", None) in _SPAWNS]
    read = {id(n) for c in ast.walk(launcher) if isinstance(c, ast.Call) and _callee(c) in _READERS
            for n in ast.walk(c)}
    assert len(spawns) == 1, f"run_hook_as_wired spawns {len(spawns)} times; the pin reads one"
    assert id(spawns[0]) in read, (
        "run_hook_as_wired's spawn is not handed to not_a_budget_miss, so a write_guard budget "
        "refusal on a wired launch reads as a deny (DEF-5066)")


def test_the_routed_population_is_not_empty():
    """A detector that finds nothing reads like a clean tree: the helper's
    callers, counted the same way, must be there."""
    routed = sum(
        1 for path in checkout_glob(TESTS, "test_*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "run_hook_through"
    )
    assert routed >= 30, routed


def test_the_detector_sees_each_shape_it_routes(tmp_path):
    """Calibration: a direct spawn, one built from a local binding, a generic
    hook runner called with write_guard (directly and through a parametrize
    list), the statusline; and the ones it must pass over: a longer bound, no
    bound, a generic runner only ever called with other hooks, and another
    hook by name."""
    sample = tmp_path / "test_sample.py"
    sample.write_text(
        "import pytest, subprocess, sys\n"
        "HOOKS_DIR = None\n"
        "def direct():\n"
        "    subprocess.run([sys.executable, str(HOOKS_DIR / 'write_guard.py')], timeout=15)\n"
        "def bound():\n"
        "    script = HOOKS_DIR / 'write_guard.py'\n"
        "    subprocess.run([sys.executable, str(script)], timeout=10)\n"
        "def generic(name):\n"
        "    script = HOOKS_DIR / name\n"
        "    subprocess.run([sys.executable, str(script)], timeout=15)\n"
        "def caller():\n"
        "    generic('write_guard.py')\n"
        "def by_param(hook):\n"
        "    subprocess.run([sys.executable, str(HOOKS_DIR / hook)], timeout=15)\n"
        "@pytest.mark.parametrize('hook', ['write_guard.py', 'plan_guard.py'])\n"
        "def test_rows(hook):\n"
        "    by_param(hook)\n"
        "CASES = [('write_guard.py', {}), ('plan_guard.py', {})]\n"
        "def by_list(hook, payload):\n"
        "    subprocess.run([sys.executable, str(HOOKS_DIR / hook)], timeout=15)\n"
        "@pytest.mark.parametrize(('hook', 'payload'), CASES)\n"
        "def test_listed(hook, payload):\n"
        "    by_list(hook, payload)\n"
        "def line():\n"
        "    subprocess.run([sys.executable, str(STATUSLINE)], timeout=5)\n"
        "def longer():\n"
        "    subprocess.run([sys.executable, str(HOOKS_DIR / 'write_guard.py')], timeout=45)\n"
        "def unbounded():\n"
        "    subprocess.run([sys.executable, str(HOOKS_DIR / 'write_guard.py')])\n"
        "def other_hooks(name):\n"
        "    subprocess.run([sys.executable, str(HOOKS_DIR / name)], timeout=15)\n"
        "def other_caller():\n"
        "    other_hooks('session_start.py')\n"
        "def named(py):\n"
        "    script = HOOKS_DIR / 'stop_gate.py'\n"
        "    subprocess.run([sys.executable, str(script)], timeout=15)\n"
        "HOOK = HOOKS_DIR / 'write_guard.py'\n"
        "def top_level():\n"
        "    subprocess.run([sys.executable, str(HOOK)], timeout=15)\n"
        "def shadowed():\n"
        "    HOOK = HOOKS_DIR / 'plan_guard.py'\n"
        "    subprocess.run([sys.executable, str(HOOK)], timeout=15)\n",
        encoding="utf-8")
    assert [row.split()[1] for row in bare_spawns_of_the_class(sample)] == [
        "direct", "bound", "generic", "by_param", "by_list", "line", "top_level"]


def test_the_refusal_pin_sees_each_shape_it_holds(tmp_path):
    """Calibration of the second pin: write_guard by hand at a longer bound,
    at none, from a top-level binding and through a generic runner, each
    unread; and the ones it must pass over: a result handed to
    ``not_a_budget_miss`` inside the call or by the name it is bound to (bare
    or through the module), a runner that hands its own result over, the
    statusline (no budget), and another hook. A result handed over by a
    caller is not read where it was spawned, so it stays unread."""
    sample = tmp_path / "test_sample.py"
    sample.write_text(
        "import subprocess, sys\n"
        "from subprocess import run\n"
        "from tests import _hook_spawn as hs\n"
        "from tests._hook_spawn import not_a_budget_miss, retry_a_budget_miss\n"
        "HOOKS_DIR = None\n"
        "HOOK = HOOKS_DIR / 'write_guard.py'\n"
        "def longer():\n"
        "    subprocess.run([sys.executable, str(HOOKS_DIR / 'write_guard.py')], timeout=45)\n"
        "def unbounded():\n"
        "    subprocess.run([sys.executable, str(HOOKS_DIR / 'write_guard.py')])\n"
        "def top_level():\n"
        "    return subprocess.run([sys.executable, str(HOOK)], timeout=30)\n"
        "def runner(name):\n"
        "    return subprocess.run([sys.executable, str(HOOKS_DIR / name)], timeout=45)\n"
        "def runs():\n"
        "    runner('write_guard.py')\n"
        "def handed_by_a_caller():\n"
        "    result = subprocess.run([sys.executable, str(HOOK)], timeout=45)\n"
        "    return result\n"
        "def caller():\n"
        "    return not_a_budget_miss(handed_by_a_caller())\n"
        "def retried():\n"
        "    return retry_a_budget_miss(lambda: subprocess.run([sys.executable, str(HOOK)], timeout=45))\n"
        "def wrapped():\n"
        "    return not_a_budget_miss(subprocess.run([sys.executable, str(HOOK)], timeout=45))\n"
        "def by_name():\n"
        "    result = subprocess.run([sys.executable, str(HOOK)])\n"
        "    hs.not_a_budget_miss(result)\n"
        "def runner_read(name):\n"
        "    return not_a_budget_miss(subprocess.run([sys.executable, str(HOOKS_DIR / name)], timeout=45))\n"
        "def runs_read():\n"
        "    runner_read('write_guard.py')\n"
        "def line():\n"
        "    subprocess.run([sys.executable, str(STATUSLINE)], timeout=30)\n"
        "def other():\n"
        "    subprocess.run([sys.executable, str(HOOKS_DIR / 'plan_guard.py')], timeout=45)\n"
        "def argv_name():\n"
        "    argv = [sys.executable, str(HOOK)]\n"
        "    subprocess.run(argv, timeout=45)\n"
        "def flags():\n"
        "    subprocess.run([sys.executable, '-X', 'utf8', '-B', str(HOOK)], timeout=45)\n"
        "def loop():\n"
        "    for hook in ('write_guard.py', 'plan_guard.py'):\n"
        "        subprocess.run([sys.executable, str(HOOKS_DIR / hook)], timeout=45)\n"
        "def from_import():\n"
        "    run([sys.executable, str(HOOK)], timeout=45)\n"
        "def tuple_argv():\n"
        "    subprocess.run((sys.executable, str(HOOK)), timeout=45)\n"
        "def reused():\n"
        "    r = subprocess.run([sys.executable, str(HOOK)], timeout=45)\n"
        "    r = subprocess.run([sys.executable, str(HOOKS_DIR / 'plan_guard.py')], timeout=45)\n"
        "    not_a_budget_miss(r)\n"
        "def annotated():\n"
        "    r: object = subprocess.run([sys.executable, str(HOOK)], timeout=45)\n"
        "    return not_a_budget_miss(r)\n"
        "def imported_in_process():\n"
        "    subprocess.run([sys.executable, '-c', 'import write_guard'], timeout=45)\n",
        encoding="utf-8")
    assert [row.split()[1] for row in refusals_read_as_verdicts(sample)] == [
        "longer", "unbounded", "top_level", "runner", "handed_by_a_caller",
        "argv_name", "flags", "loop", "from_import", "tuple_argv", "reused"]


def test_the_budget_refusal_phrase_is_write_guards_and_only_its():
    """The retry knows the budget's refusal by a phrase of its message: a
    rewording would stop the retry without a red, and the same phrase in any
    other hook text would make a wrong answer look like a miss."""
    sys.path.insert(0, str(HOOKS))
    try:
        import _denial_reasons
    finally:
        sys.path.remove(str(HOOKS))
    assert hs.BUDGET_REFUSAL in _denial_reasons.WRITE_GUARD_TIME_BUDGET
    holders = [p.name for p in sorted(checkout_glob(HOOKS, "*.py"))
               if hs.BUDGET_REFUSAL in p.read_text(encoding="utf-8")]
    assert holders == ["_denial_reasons.py"], holders


def _names_deny(node: ast.AST) -> bool:
    """``node`` is a string naming the decision ``deny`` as a word (``deny``,
    ``'"deny"'``, ``'"permissionDecision": "deny"'``), or a literal list,
    tuple or set holding one."""
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(_names_deny(e) for e in node.elts)
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and bool(
        re.search(r"(?<![\w.-])deny(?![\w-])", node.value))


def bench_deny_readers(path: Path) -> list[tuple[str, bool]]:
    """``("line function", reads)`` for each function in ``path`` that compares
    a value with ``deny`` (``'"deny"' in out``, ``"deny" in out``, ``== "deny"``,
    ``in ("deny", ...)``), the innermost function holding the comparison, and
    whether that same function calls one of the bench's budget readers
    (``bench/run_benchmark.py``'s ``judged_within_budget`` or
    ``budget_refused``, bare or through a module). Not read: a deny matched by
    a regex or a method call, or compared at module level."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    owner: dict[int, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for fn in functions:  # outer first, so an inner function's nodes end up its own
        for node in ast.walk(fn):
            owner[id(node)] = fn
    readers = {id(fn): fn for node in ast.walk(tree)
               if isinstance(node, ast.Compare) and any(_names_deny(x) for x in [node.left, *node.comparators])
               and (fn := owner.get(id(node))) is not None}
    return [
        (f"{fn.lineno} {fn.name}", any(
            isinstance(c, ast.Call) and owner.get(id(c)) is fn and _callee(c) in _BENCH_BUDGET_READERS
            for c in ast.walk(fn)))
        for fn in sorted(readers.values(), key=lambda f: f.lineno)]


def test_every_bench_reader_of_a_deny_reads_the_budgets_refusal_apart():
    """DEF-5071: the second pin's class outside tests/. Five bench readers of
    write_guard's decision channel read the budget's refusal as a judged deny,
    so the live-tree calibration of tests/test_guard_metamorphic.py on a
    loaded runner would read `ls -la` as SOFT and call the instrument broken,
    and the release gate would count a judgment that never finished as a
    block. A function under bench/ that compares a value with ``deny`` reads
    the refusal apart in that same function, through
    ``bench/run_benchmark.py``'s reader (the one bench file the sdist ships)."""
    stray = {
        path.relative_to(BENCH).as_posix(): rows
        for path in checkout_rglob(BENCH, "*.py")
        if (rows := [row for row, reads in bench_deny_readers(path) if not reads])
    }
    assert not stray, (
        "spawn write_guard through judged_within_budget, or read its answer with "
        f"budget_refused, in the function that reads the deny (DEF-5071): {stray}")


def test_the_bench_reader_population_is_not_empty():
    """The bench pin's non-vacuity: the readers that read the refusal apart,
    counted the same way, must be there."""
    read = sum(1 for path in checkout_rglob(BENCH, "*.py") for _row, reads in bench_deny_readers(path) if reads)
    assert read >= 5, (
        f"{read} bench readers of a deny read the budget's refusal apart, under the floor of 5: "
        "if one was retired, lower the floor to the count left, never to 0")


def test_the_bench_pin_sees_each_shape_it_holds(tmp_path):
    """Calibration of the bench pin: a deny read by the JSON-quoted word, the
    bare word, an equality and a literal tuple, each unread; and the ones it
    must pass over: a reader that spawns through ``judged_within_budget`` (an
    inner function, as the tier helpers' ``once`` is) or calls
    ``budget_refused`` through a module, and a function that compares nothing
    with ``deny``. A budget reader called by the enclosing function does not
    read the inner function's comparison."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import json\n"
        "def quoted(proc):\n"
        "    return '\"deny\"' in proc.stdout\n"
        "def bare(result):\n"
        "    return 'deny' in result.stdout\n"
        "def equal(stdout):\n"
        "    return json.loads(stdout)['decision'] == 'deny'\n"
        "def listed(stdout):\n"
        "    return json.loads(stdout)['decision'] in ('deny', 'ask')\n"
        "def keyed(out):\n"
        "    return '\"permissionDecision\": \"deny\"' in out\n"
        "def other_word(out):\n"
        "    return 'denylist' in out or 'permissions.deny' in out\n"
        "def tier(run, project):\n"
        "    def once():\n"
        "        proc = judged_within_budget(lambda: run(), HOOKS_DIR, project)\n"
        "        return '\"deny\"' in proc.stdout\n"
        "    return once()\n"
        "def through_a_module(stdout, rc):\n"
        "    if rb.budget_refused(stdout, HOOKS_DIR):\n"
        "        raise RuntimeError(stdout)\n"
        "    return rc == 2 or 'deny' in stdout\n"
        "def allow(proc):\n"
        "    return 'allow' in proc.stdout\n"
        "def outer(stdout):\n"
        "    def inner():\n"
        "        return 'deny' in stdout\n"
        "    budget_refused(stdout, HOOKS_DIR)\n"
        "    return inner()\n",
        encoding="utf-8")
    assert [(row.split()[1], reads) for row, reads in bench_deny_readers(sample)] == [
        ("quoted", False), ("bare", False), ("equal", False), ("listed", False), ("keyed", False),
        ("once", True), ("through_a_module", True), ("inner", False)]


class _Reporter:
    def __init__(self, warnings):
        self.stats = {"warnings": warnings}
        self.lines: list[str] = []

    def write_line(self, line):
        self.lines.append(line)


class _Warned:
    def __init__(self, nodeid, message):
        self.nodeid, self.message = nodeid, message


def test_the_run_summary_counts_the_retried_rows(monkeypatch):
    """Each retried row once, however many of its spawns retried; other
    warnings left out; under GitHub Actions an annotation as well."""
    from tests.conftest import report_hook_spawn_retries

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    reporter = _Reporter([
        _Warned("tests/test_a.py::T::one", "tests/test_a.py:9: HookSpawnRetried: write_guard.py: ..."),
        _Warned("tests/test_a.py::T::one", "tests/test_a.py:9: HookSpawnRetried: write_guard.py: ..."),
        _Warned("tests/test_b.py::two", "tests/test_b.py:3: PytestRemovedIn10Warning: ..."),
    ])
    report_hook_spawn_retries(reporter)
    assert reporter.lines == [
        "hook spawn retries: 1 row(s) missed once and answered on the retry:",
        "  tests/test_a.py::T::one",
        "::warning::hook spawn retries: 1 row(s) missed once and answered on the retry: tests/test_a.py::T::one",
    ]
    quiet = _Reporter([_Warned("tests/test_b.py::two", "PytestRemovedIn10Warning: ...")])
    report_hook_spawn_retries(quiet)
    assert quiet.lines == []


def test_a_row_with_a_spent_retry_fits_every_per_test_ceiling():
    """A row's worst case is three bounds: a miss, its retry answering at the
    bound, then a later miss that fails at once (the one retry spent). It must
    fail by the helper's message, with room for the kill and the teardown,
    never by the ceiling's kill: the suite's
    ceiling (``pyproject.toml``) and the windows-latest cell's
    (``PYTEST_TIMEOUT`` in its workflow), read where they are set."""
    ini = re.search(r"(?m)^timeout = (\d+)$", (TESTS.parent / "pyproject.toml").read_text(encoding="utf-8"))
    cell = re.search(r"PYTEST_TIMEOUT=(\d+)",
                     (TESTS.parent / ".github" / "workflows" / "portability.yml").read_text(encoding="utf-8"))
    assert ini and cell, "a ceiling moved: re-read where it is set"
    for ceiling in (int(ini.group(1)), int(cell.group(1))):
        assert 3 * hs.HOOK_S <= ceiling - 10, (hs.HOOK_S, ceiling)
