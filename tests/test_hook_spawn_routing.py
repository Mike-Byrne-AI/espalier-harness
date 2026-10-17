"""Where tests/_hook_spawn.py must be used, and what it must agree with
(DEF-2014). Contract rows: they read source, never spawn.

The routing pin derives its population from the tree: every spawn in a test
module that runs write_guard (the hook whose budget refusal a verdict row
reads as a wrong answer) or the statusline, under a fixed bound no longer than
the helper's, must go through ``run_hook_through``, so a new row cannot bring
the bare fixed bound back. A spawn runs one of them when its script, or the
local binding the script is built from, names it; or when the spawn sits in a
helper whose script is built from ``HOOKS_DIR`` and one of the helper's own
parameters, in a module that names write_guard (the generic hook runners).
Spawns with a longer bound keep it (they have the slack the 15 s rows lacked)
and spawns with none are not this class.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

from tests import _hook_spawn as hs
from tests._live_tree import checkout_glob

TESTS = Path(__file__).resolve().parent
HOOKS = TESTS.parent / "tools" / "cc" / "hooks"

_SPAWNS = {"run", "Popen", "check_output", "check_call"}
_NAMES = re.compile(r"write_guard|statusline|STATUSLINE")
#: Modules whose write_guard spawns stay bare, each with its reason.
_EXEMPT = {
    # It drives the budget's refusal on purpose, and times the process exit.
    "test_write_guard_time_budget.py",
}


def _number(node: ast.AST | None) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    return None


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {a.arg for a in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]}


def bare_spawns_of_the_class(path: Path) -> list[str]:
    """``line function`` for each spawn in ``path`` that runs write_guard or the
    statusline under a fixed bound no longer than the helper's, by hand."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    owner: dict[int, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for fn in functions:  # outer first, so an inner function's nodes end up its own
        for node in ast.walk(fn):
            owner[id(node)] = fn
    module_binds = {
        t.id: ast.unparse(n.value)
        for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None
        for t in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(t, ast.Name)
    }

    def names_write_guard(decorator: ast.expr) -> bool:
        text = ast.unparse(decorator)
        return "write_guard" in text or any(
            "write_guard" in module_binds.get(n.id, "") for n in ast.walk(decorator) if isinstance(n, ast.Name))

    def called_with_write_guard(name: str) -> bool:
        """A call of ``name`` passes write_guard: in its own arguments, or in a
        parameter its calling test takes from a parametrize list (written in
        the decorator, or a module-level list it names)."""
        for call in ast.walk(tree):
            if not (isinstance(call, ast.Call) and getattr(call.func, "id", getattr(call.func, "attr", None)) == name):
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
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        binds.setdefault(t.id, []).append(n.value)
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call) and getattr(call.func, "attr", None) in _SPAWNS
                    and owner.get(id(call)) is fn):
                continue
            argv = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "args"), None)
            if not (isinstance(argv, ast.List) and len(argv.elts) >= 2):
                continue
            bound = _number(next((k.value for k in call.keywords if k.arg == "timeout"), None))
            if bound is None or bound > hs.HOOK_S:
                continue
            exprs = [argv.elts[1]]
            for _ in range(2):  # the script's local binding, and one built from another
                names = {n.id for e in exprs for n in ast.walk(e) if isinstance(n, ast.Name)}
                exprs += [v for name in names for v in binds.get(name, []) if v not in exprs]
            names = {n.id for e in exprs for n in ast.walk(e) if isinstance(n, ast.Name)}
            direct = any(_NAMES.search(ast.unparse(e)) for e in exprs)
            generic = bool(names & _params(fn)) and called_with_write_guard(fn.name)
            if direct or generic:
                found.append(f"{call.lineno} {fn.name}")
    return found


def test_every_write_guard_and_statusline_spawn_routes_through_the_helper():
    stray = {
        path.name: rows
        for path in checkout_glob(TESTS, "test_*.py")
        if path.name not in _EXEMPT and (rows := bare_spawns_of_the_class(path))
    }
    assert not stray, (
        "run these through tests._hook_spawn.run_hook_through (DEF-2014), or give them a "
        f"bound past {hs.HOOK_S:.0f} s with the reason: {stray}")


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
        "    subprocess.run([sys.executable, str(script)], timeout=15)\n",
        encoding="utf-8")
    assert [row.split()[1] for row in bare_spawns_of_the_class(sample)] == [
        "direct", "bound", "generic", "by_param", "by_list", "line"]


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
