"""No test runs the surface gate against the live checkout.

`espalier.proofs.run_cc_surface_gate` rewrites `reports/cc_surface_gate.json`
through a temp file beside it, and every entry point that reaches it on an
initialized tree -- `run_self_host_check` and `self_hosting.main` in auto mode,
`doctor.run_doctor_check`, the `cmd_audit` / `cmd_doctor` / `cmd_self_host`
handlers and the `espalier audit` / `doctor` / `self-host` CLI verbs -- does the
same. Run on the live root, that write lands in the maintainer's `reports/` while
a sibling xdist worker's live-tree guard watches the directory, and the sibling
errors at teardown (DEF-973: sixteen such tests, eighteen entries on the
`tests/README.md` races line, 2026-09-06 to 2026-09-29). This module pins the
fix: such a call takes the `initialized_repo_root` fixture (an init'd copy) or
`mode="source-checkout"`, which never writes.

The census is keyed on what an argument IS, not how it is spelled: a name bound
to `Path(__file__)...parent.parent` (or `.parents[1]`) is the live root whatever
the module calls it (`REPO_ROOT`, `REPO`, `ROOT`, `_REPO` all occur), and so is
`str()` / `os.fspath()` / `Path()` / `.resolve()` of one. The guard in
`tests/conftest.py::_no_live_tree_writes` is the detector and stays as it is;
relieving it for the temp name would remove the detector, not the write.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Functions that run the surface gate on the tree they are handed.
WRITERS = frozenset({
    "run_self_host_check", "run_cc_surface_gate", "run_doctor_check",
    "cmd_audit", "cmd_doctor", "cmd_self_host",
})
#: CLI verbs that run it.
CLI_VERBS = frozenset({"audit", "doctor", "self-host"})
_ROOT_EXPR = re.compile(
    r"^(?:pathlib\.)?Path\(__file__\)(?:\.resolve\(\))?\.(?:parent\.parent|parents\[1\])$")
_WRAPPERS = frozenset({"str", "fspath", "Path", "resolve", "absolute"})


def _live_names(tree: ast.Module) -> set[str]:
    """Names bound (module or class level, plain or annotated) to the live root."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _ROOT_EXPR.match(ast.unparse(node.value)):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif (isinstance(node, ast.AnnAssign) and node.value is not None
              and isinstance(node.target, ast.Name) and _ROOT_EXPR.match(ast.unparse(node.value))):
            names.add(node.target.id)
    return names


def _is_live(node: ast.AST, names: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in names
    if _ROOT_EXPR.match(ast.unparse(node)):
        return True
    if isinstance(node, ast.Call):
        f = node.func
        fname = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
        if fname in _WRAPPERS:
            if node.args and _is_live(node.args[0], names):
                return True  # str(ROOT), os.fspath(ROOT), Path(ROOT)
            if isinstance(f, ast.Attribute) and _is_live(f.value, names):
                return True  # ROOT.resolve()
    return False


def _source_checkout(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and kw.value.value == "source-checkout":
            return True
    return any(isinstance(n, ast.Constant) and n.value == "source-checkout" for n in ast.walk(call))


def _self_hosting_mains(tree: ast.Module) -> tuple[set[str], set[str]]:
    """(names bound to `espalier.self_hosting.main`, aliases of the module)."""
    funcs, mods = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "espalier.self_hosting":
            funcs |= {a.asname or a.name for a in node.names if a.name == "main"}
        elif isinstance(node, ast.ImportFrom) and node.module == "espalier":
            mods |= {a.asname or a.name for a in node.names if a.name == "self_hosting"}
        elif isinstance(node, ast.Import):
            mods |= {a.asname for a in node.names if a.name == "espalier.self_hosting" and a.asname}
    return funcs, mods


def find_live_root_gate_calls(source: str, path: str = "<src>") -> list[str]:
    """Every call in ``source`` that runs the surface gate on the live root,
    as ``path:line: text``; source-checkout mode is exempt."""
    tree = ast.parse(source)
    names = _live_names(tree)
    mains, sh_mods = _self_hosting_mains(tree)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _source_checkout(node):
            continue
        f = node.func
        fname = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
        live_arg = bool(node.args) and _is_live(node.args[0], names)
        if fname in WRITERS and node.args and isinstance(node.args[0], ast.Call):
            # cmd_doctor(Namespace(repo=ROOT, ...)): the tree rides a keyword
            live_arg = live_arg or any(_is_live(kw.value, names) for kw in node.args[0].keywords
                                       if kw.arg in ("repo", "repo_root", "path"))
        is_main = (isinstance(f, ast.Name) and f.id in mains) or (
            isinstance(f, ast.Attribute) and f.attr == "main"
            and isinstance(f.value, ast.Name) and f.value.id in sh_mods)
        argv = [a for a in node.args if isinstance(a, ast.List)]
        argv_items = [e for lst in argv for e in lst.elts]
        verb = any(isinstance(e, ast.Constant) and e.value in CLI_VERBS for e in argv_items)
        cwd_live = any(kw.arg == "cwd" and _is_live(kw.value, names) for kw in node.keywords)
        dot = any(isinstance(e, ast.Constant) and e.value == "." for e in argv_items)
        if ((fname in WRITERS and live_arg)
                or (is_main and any(_is_live(e, names) for e in argv_items))
                or (verb and (any(_is_live(e, names) for e in argv_items) or (cwd_live and dot)))):
            hits.append(f"{path}:{node.lineno}: {ast.unparse(node)[:140]}")
    # The relative spelling: a function that chdir's to the live root and then
    # hands a writer "." (test_resolves_relative_path took that shape).
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
        if not any(isinstance(c.func, ast.Attribute) and c.func.attr == "chdir"
                   and c.args and _is_live(c.args[0], names) for c in calls):
            continue
        for c in calls:
            f = c.func
            fname = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if (fname in WRITERS and c.args and not _source_checkout(c)
                    and ast.unparse(c.args[0]).replace('"', "'") in ("'.'", "Path('.')")):
                hits.append(f"{path}:{c.lineno}: {ast.unparse(c)[:140]}")
    return hits


def _test_sources() -> list[Path]:
    tests = ROOT / "tests"
    return sorted(p for p in tests.glob("*.py") if p.name != Path(__file__).name)


class TestNoTestRunsTheGateOnTheLiveRoot:
    def test_the_census_is_empty(self):
        """Dies to: a test that calls a gate writer, `self_hosting.main` or a
        gate-running CLI verb on the live root outside source-checkout mode."""
        hits: list[str] = []
        for p in _test_sources():
            hits += find_live_root_gate_calls(p.read_text(encoding="utf-8"), p.relative_to(ROOT).as_posix())
        assert not hits, (
            "these run the surface gate on the live checkout, rewriting "
            "reports/cc_surface_gate.json under a sibling worker's live-tree guard "
            "(DEF-973); take the `initialized_repo_root` fixture, or pass "
            "mode='source-checkout' where the subject is the committed tree:\n  "
            + "\n  ".join(hits))

    def test_the_census_sees_the_population_it_guards(self):
        """A floor, so the census cannot pass by reading nothing: the modules
        that drive these writers are in the scan, and each still calls one."""
        sources = {p.name: p.read_text(encoding="utf-8") for p in _test_sources()}
        for name, writer in (("test_self_hosting.py", "run_self_host_check("),
                             ("test_documented_claims.py", '"doctor"')):
            assert name in sources and writer in sources[name], (name, writer)


class TestTheScannerKeysOnTheArgument:
    """The scanner's own rows: each shape it must catch, and what it must not."""

    _HEAD = "from pathlib import Path\nTOP = Path(__file__).resolve().parents[1]\n"

    def _hits(self, body: str) -> list[str]:
        return find_live_root_gate_calls(self._HEAD + body)

    def test_a_writer_on_any_spelling_of_the_live_root_is_caught(self):
        assert self._hits("run_self_host_check(TOP)\n")
        assert self._hits("run_cc_surface_gate(str(TOP))\n")
        assert self._hits("run_doctor_check(TOP.resolve())\n")
        assert self._hits("run_self_host_check(Path(__file__).parent.parent)\n")
        assert self._hits("cmd_doctor(Namespace(repo=str(TOP)))\n")

    def test_self_hosting_main_and_the_cli_verbs_are_caught(self):
        assert self._hits("from espalier.self_hosting import main\nmain([str(TOP)])\n")
        assert self._hits("from espalier import self_hosting as sh\nsh.main([str(TOP)])\n")
        assert self._hits("subprocess.run([sys.executable, '-m', 'espalier.cli', 'doctor', str(TOP)])\n")
        assert self._hits("subprocess.run(['espalier', 'audit', '.'], cwd=TOP)\n")

    def test_a_relative_root_after_a_chdir_to_the_live_root_is_caught(self):
        body = ("def test_x(monkeypatch):\n"
                "    monkeypatch.chdir(TOP)\n"
                "    run_self_host_check(Path('.'))\n")
        assert self._hits(body)
        assert not self._hits(body.replace("chdir(TOP)", "chdir(tmp_path)"))

    def test_source_checkout_mode_and_another_tree_are_left_alone(self):
        assert not self._hits("run_self_host_check(TOP, mode='source-checkout')\n")
        assert not self._hits("main([str(TOP), '--mode', 'source-checkout'])\n")
        assert not self._hits("run_self_host_check(initialized_repo_root)\n")
        assert not self._hits("run_self_host_check(tmp_path)\n")
        assert not self._hits("subprocess.run(['espalier', 'doctor', str(tmp_path)])\n")
        assert not self._hits("unrelated(TOP)\n")
