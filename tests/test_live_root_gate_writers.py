"""No test runs the surface gate against the live checkout.

`espalier.proofs.run_cc_surface_gate` rewrites `reports/cc_surface_gate.json`
through a temp file beside it, and every entry point that reaches it on an
initialized tree does the same: the functions in `espalier/` that call it, or
call one that does (derived below from the source, never listed by hand),
`self_hosting.main`, and the CLI verbs their `cmd_*` handlers serve. Run on the
live root, that write lands in the maintainer's `reports/` while a sibling xdist
worker's live-tree guard watches the directory, and the sibling errors at
teardown (DEF-973: seventeen such tests; the `tests/README.md` races line names
the temp file 26 times, 2026-09-06 to 2026-10-09). This module pins the fix: such
a call takes the `initialized_repo_root` fixture (an init'd copy), or the
non-writing mode where its entry point has one, spelled as that entry point reads
it: `mode="source-checkout"` for the self-host check, its `main` and the
`self-host` verb; `mode="source_checkout"` (the repo-mode constant) for
`doctor.run_doctor_check`.

The census is keyed on what an argument IS, not how it is spelled: a path
expression is evaluated against the scanned module's own location
(`Path(__file__)` and its `.parent`, `.parents[n]`, `/ "part"`, `.resolve()`,
`.absolute()`; `os.path.dirname`, `abspath`, `realpath`; `str()`, `os.fspath()`,
`Path()`; and names bound to any of those, in any order), and the live root is
whatever evaluates to the repository root (`REPO_ROOT`, `ROOT`, `_REPO`,
`_HOOKS_DIR.parent.parent.parent` all occur). Not seen, by construction: a root
that reaches a writer through a helper's parameter or `*args`
(`_espalier(*args)`), an attribute (`self.root`), and a subprocess that runs a
verb with no path and no `cwd`, or an argv held in a variable with a relative
path and `cwd=` the live root; a root built by an f-string, string
concatenation or `os.getcwd()`; a `global` rebinding. The writer list is keyed
by bare function name, so a future same-named helper that calls a writer joins
it (a loud false red, never a silent pass). The guard in `tests/conftest.py::_no_live_tree_writes`
is the runtime detector and stays as it is; relieving it for the temp name would
remove the detector, not the write.
"""
from __future__ import annotations

import ast
import functools
from pathlib import Path
from tests._live_tree import checkout_glob, checkout_rglob

ROOT = Path(__file__).resolve().parent.parent

#: Writers by name whose gate runs on a tree other than the one they are handed.
_GATE_ON_ANOTHER_TREE = {
    "fuse_repos": "its cmd_init runs on the fused output directory, never the host it takes first",
    "cmd_fuse": "the same, through fuse_repos",
}
#: Entry points with a mode that never writes, and how each spells it.
_NON_WRITING_MODE = {
    "run_self_host_check": "source-checkout",
    "cmd_self_host": "source-checkout",
    "run_doctor_check": "source_checkout",
}
_SELF_HOST_VERB = "self-host"
#: The scanned modules' own directory, relative to the repository root.
_HERE = ("tests",)


def _name_of(func: ast.AST) -> str:
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


@functools.lru_cache(maxsize=None)
def gate_writers() -> frozenset[str]:
    """Every function in `espalier/` that runs the surface gate:
    `run_cc_surface_gate` and, transitively, each function that calls one by
    name. `main` is left out (a dozen modules define one); `self_hosting.main`
    is matched by its import instead."""
    calls: dict[str, set[str]] = {}
    for p in sorted(checkout_rglob(ROOT / "espalier", "*.py")):
        if {"_vendor", "assets"} & set(p.relative_to(ROOT).parts):
            continue
        for fn in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                calls.setdefault(fn.name, set()).update(
                    _name_of(c.func) for c in ast.walk(fn) if isinstance(c, ast.Call))
    writers = {"run_cc_surface_gate"}
    while new := {f for f, called in calls.items() if called & writers and f != "main"} - writers:
        writers |= new
    return frozenset(writers - set(_GATE_ON_ANOTHER_TREE))


def gate_verbs() -> frozenset[str]:
    """The CLI verbs whose `cmd_*` handler is a gate writer."""
    return frozenset(w[len("cmd_"):].replace("_", "-") for w in gate_writers() if w.startswith("cmd_"))


def _up(parts: tuple[str, ...], n: int) -> tuple[str, ...]:
    for _ in range(n):
        parts = parts[:-1] if parts and parts[-1] != ".." else parts + ("..",)
    return parts


def _join(parts: tuple[str, ...], rel: str) -> tuple[str, ...]:
    for seg in rel.replace("\\", "/").split("/"):
        if seg == "..":
            parts = _up(parts, 1)
        elif seg not in ("", "."):
            parts = parts + (seg,)
    return parts


def _path_of(node: ast.AST, env: dict[str, tuple[str, ...]]) -> tuple[str, ...] | None:
    """The path ``node`` evaluates to, as parts relative to the repository root
    (``()`` is the root itself), or None when it is not built from the scanned
    module's own location."""
    if isinstance(node, ast.Name):
        return _HERE + ("<module>",) if node.id == "__file__" else env.get(node.id)
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        base = _path_of(node.value, env)
        return None if base is None else _up(base, 1)
    if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
            and node.value.attr == "parents" and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, int)):
        base = _path_of(node.value.value, env)
        return None if base is None else _up(base, node.slice.value + 1)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        base = _path_of(node.left, env)
        if base is None or not (isinstance(node.right, ast.Constant) and isinstance(node.right.value, str)):
            return None
        return _join(base, node.right.value)
    if isinstance(node, ast.Call):
        f, name = node.func, _name_of(node.func)
        if isinstance(f, ast.Attribute) and name in ("resolve", "absolute") and not node.args:
            return _path_of(f.value, env)
        if name in ("str", "fspath", "Path", "abspath", "realpath", "normpath") and len(node.args) == 1:
            return _path_of(node.args[0], env)
        parts = node.args[1:] if name in ("Path", "join") else node.args if name == "joinpath" else None
        if parts is not None and all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in parts):
            base = (_path_of(f.value, env) if name == "joinpath" and isinstance(f, ast.Attribute)
                    else _path_of(node.args[0], env) if node.args and name != "joinpath" else None)
            for part in parts:
                base = None if base is None else _join(base, part.value)
            return base
        if name == "dirname" and len(node.args) == 1:
            base = _path_of(node.args[0], env)
            return None if base is None else _up(base, 1)
    return None


_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _scope_nodes(owner: ast.AST) -> list[ast.AST]:
    """The nodes of ``owner``'s own scope: class bodies in, nested function
    bodies out (each function is a scope of its own)."""
    out, stack = [], list(ast.iter_child_nodes(owner))
    while stack:
        node = stack.pop()
        out.append(node)
        if not isinstance(node, _FUNCS):
            stack.extend(ast.iter_child_nodes(node))
    return out


def _bound(nodes: list[ast.AST], outer: dict[str, tuple[str, ...]],
           local: set[str]) -> dict[str, tuple[str, ...]]:
    """``outer`` less the names this scope binds itself, plus this scope's
    bindings that evaluate to a path built from the module's own location. A
    name bound to the root anywhere in the scope stays the root (the
    conservative read); a name bound only to something else is not a path."""
    binds = sorted([(n.lineno, t.id, n.value) for n in nodes if isinstance(n, ast.Assign)
                    for t in n.targets if isinstance(t, ast.Name)]
                   + [(n.lineno, n.target.id, n.value) for n in nodes if isinstance(n, ast.AnnAssign)
                      and n.value is not None and isinstance(n.target, ast.Name)],
                   key=lambda b: b[0])
    env = {k: v for k, v in outer.items() if k not in local | {name for _line, name, _v in binds}}
    for _ in range(4):  # a name used before the line that binds it
        for _line, name, value in binds:
            path = _path_of(value, env)
            if path is not None and env.get(name) != ():
                env[name] = path
    return env


def _scopes(tree: ast.Module) -> list[tuple[list[ast.AST], dict[str, tuple[str, ...]]]]:
    """Each scope's own nodes with the paths its names hold there: the module
    (with its class bodies), then every function, whose parameters and own
    assignments shadow what encloses it."""
    module = _scope_nodes(tree)
    out = [(module, _bound(module, {}, set()))]
    stack = [(fn, out[0][1]) for fn in module if isinstance(fn, _FUNCS)]
    while stack:
        fn, outer = stack.pop()
        a = fn.args
        params = {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
        params |= {x.arg for x in (a.vararg, a.kwarg) if x is not None}
        nodes = _scope_nodes(fn)
        stored = {n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        stored |= {n.name for n in nodes if isinstance(n, ast.ExceptHandler) and n.name}
        env = _bound(nodes, outer, params | stored)
        out.append((nodes, env))
        stack += [(inner, env) for inner in nodes if isinstance(inner, _FUNCS)]
    return out


def _passes_mode(node: ast.AST, mode: str) -> bool:
    """``node`` passes ``mode`` as a mode argument: ``mode=`` on a call in it (a
    `Namespace` included), or ``--mode <mode>`` in an argv in it."""

    def is_mode(v: ast.AST) -> bool:
        return ((isinstance(v, ast.Constant) and v.value == mode)
                or (mode == "source_checkout" and _name_of(v) == "REPO_MODE_SOURCE_CHECKOUT"))

    for n in ast.walk(node):
        if isinstance(n, ast.Call) and any(kw.arg == "mode" and is_mode(kw.value) for kw in n.keywords):
            return True
        if isinstance(n, (ast.List, ast.Tuple)) and any(
                isinstance(a, ast.Constant) and a.value == "--mode" and is_mode(b)
                for a, b in zip(n.elts, n.elts[1:])):
            return True
    return False


def _non_writing(call: ast.Call, entry: str) -> bool:
    """The call passes its entry point's non-writing mode, as that entry point spells it."""
    mode = _NON_WRITING_MODE.get(entry)
    return mode is not None and _passes_mode(call, mode)


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


def _runs_espalier_verb(consts: list[object], verbs: frozenset[str]) -> str | None:
    """The gate verb an argv's constants run, when they invoke espalier itself
    (`espalier`, or `espalier.cli` after `-m`) before it; None otherwise (git's
    own `init` is not espalier's)."""
    at = next((i for i, v in enumerate(consts)
               if isinstance(v, str) and (v == "espalier" or v.startswith("espalier."))), None)
    return None if at is None else next((v for v in consts[at + 1:] if v in verbs), None)


def find_live_root_gate_calls(source: str, path: str = "<src>") -> list[str]:
    """Every call in ``source`` that runs the surface gate on the live root, and
    every espalier argv that names a gate verb with the live root, as
    ``path:line: text``; each entry point's non-writing mode is exempt."""
    tree = ast.parse(source)
    writers, verbs = gate_writers(), gate_verbs()
    mains, sh_mods = _self_hosting_mains(tree)
    hits: dict[tuple[int, str], None] = {}

    def hit(node: ast.AST) -> None:
        hits[(node.lineno, f"{path}:{node.lineno}: {ast.unparse(node)[:140]}")] = None

    for nodes, env in _scopes(tree):
        def live(node: ast.AST, env: dict[str, tuple[str, ...]] = env) -> bool:
            return _path_of(node, env) == ()

        for node in nodes:
            if isinstance(node, (ast.List, ast.Tuple)):
                consts = [e.value for e in node.elts if isinstance(e, ast.Constant)]
                verb = _runs_espalier_verb(consts, verbs)
                if verb and any(live(e) for e in node.elts) and not (
                        verb == _SELF_HOST_VERB and _passes_mode(node, _NON_WRITING_MODE["run_self_host_check"])):
                    hit(node)
                continue
            if not isinstance(node, ast.Call):
                continue
            f, fname = node.func, _name_of(node.func)
            if fname in writers and not _non_writing(node, fname):
                roots = list(node.args[:1]) + [kw.value for kw in node.keywords
                                               if kw.arg in ("repo", "repo_root", "root", "path")]
                if node.args and isinstance(node.args[0], ast.Call):
                    # cmd_doctor(Namespace(repo=ROOT, ...)): the tree rides a keyword
                    roots += [kw.value for kw in node.args[0].keywords
                              if kw.arg in ("repo", "repo_root", "path")]
                if any(live(r) for r in roots):
                    hit(node)
            is_main = (isinstance(f, ast.Name) and f.id in mains) or (
                isinstance(f, ast.Attribute) and f.attr == "main"
                and isinstance(f.value, ast.Name) and f.value.id in sh_mods)
            argv_items = [e for a in node.args if isinstance(a, ast.List) for e in a.elts]
            if is_main and any(live(e) for e in argv_items) and not _non_writing(node, "run_self_host_check"):
                hit(node)
            cwd_live = any(kw.arg == "cwd" and live(kw.value) for kw in node.keywords)
            consts = [e.value for e in argv_items if isinstance(e, ast.Constant)]
            if cwd_live and "." in consts and _runs_espalier_verb(consts, verbs):
                hit(node)
        # The relative spelling: a scope that chdir's to the live root and then
        # hands a writer "." (test_resolves_relative_path took that shape).
        calls = [c for c in nodes if isinstance(c, ast.Call)]
        if any(_name_of(c.func) == "chdir" and c.args and live(c.args[0]) for c in calls):
            for c in calls:
                fname = _name_of(c.func)
                if (fname in writers and c.args and not _non_writing(c, fname)
                        and ast.unparse(c.args[0]).replace('"', "'") in ("'.'", "Path('.')")):
                    hit(c)
    return [text for _line, text in sorted(hits)]


def _test_sources() -> list[Path]:
    tests = ROOT / "tests"
    return sorted(p for p in checkout_glob(tests, "*.py") if p.name != Path(__file__).name)


class TestNoTestRunsTheGateOnTheLiveRoot:
    def test_the_census_is_empty(self):
        """Dies to: a test that calls a gate writer, `self_hosting.main` or a
        gate-running CLI verb on the live root outside its non-writing mode."""
        hits: list[str] = []
        for p in _test_sources():
            hits += find_live_root_gate_calls(p.read_text(encoding="utf-8"), p.relative_to(ROOT).as_posix())
        assert not hits, (
            "these run the surface gate on the live checkout, rewriting "
            "reports/cc_surface_gate.json under a sibling worker's live-tree guard "
            "(DEF-973); take the `initialized_repo_root` fixture, or pass the entry "
            "point's non-writing mode where the subject is the committed tree "
            "(mode='source-checkout' for the self-host check, "
            "mode='source_checkout' for run_doctor_check):\n  " + "\n  ".join(hits))

    def test_the_census_sees_the_population_it_guards(self):
        """A floor, so the census cannot pass by reading nothing: the modules
        that drive these writers are in the scan, and each still calls one."""
        sources = {p.name: p.read_text(encoding="utf-8") for p in _test_sources()}
        for name, writer in (("test_self_hosting.py", "run_self_host_check("),
                             ("test_documented_claims.py", '"doctor"')):
            assert name in sources and writer in sources[name], (name, writer)

    def test_the_writers_are_derived_from_the_engine(self):
        """A floor for the derivation, so it cannot pass by reading nothing:
        the entry points DEF-973 found, and the two a hand-kept list missed."""
        assert {"run_cc_surface_gate", "run_self_host_check", "run_doctor_check", "cmd_audit",
                "cmd_doctor", "cmd_self_host", "run_pre_release_check", "cmd_init"} <= gate_writers()
        assert {"audit", "doctor", "self-host", "pre-release", "init"} <= gate_verbs()


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
        assert self._hits("run_self_host_check(repo_root=TOP)\n")
        assert self._hits("run_pre_release_check(TOP)\n")

    def test_a_root_reached_by_a_chain_or_os_path_is_caught(self):
        assert self._hits("HOOKS = Path(__file__).resolve().parents[1] / 'tools' / 'cc' / 'hooks'\n"
                          "R = HOOKS.parent.parent.parent\nrun_doctor_check(R)\n")
        assert self._hits("R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
                          "run_cc_surface_gate(R)\n")
        assert self._hits("run_self_host_check(LATER)\nLATER = TOP\n")

    def test_self_hosting_main_and_the_cli_verbs_are_caught(self):
        assert self._hits("from espalier.self_hosting import main\nmain([str(TOP)])\n")
        assert self._hits("from espalier import self_hosting as sh\nsh.main([str(TOP)])\n")
        assert self._hits("subprocess.run([sys.executable, '-m', 'espalier.cli', 'doctor', str(TOP)])\n")
        assert self._hits("subprocess.run(['espalier', 'audit', '.'], cwd=TOP)\n")
        assert self._hits("cmd = ['espalier', 'doctor', str(TOP)]\nsubprocess.run(cmd)\n")
        assert self._hits("subprocess.run(['espalier', 'pre-release', str(TOP)])\n")

    def test_doctor_with_the_self_host_spelling_of_the_mode_is_caught(self):
        """Doctor reads the repo-mode constant, `source_checkout`; the self-host
        spelling falls through to the gate and writes."""
        assert self._hits("run_doctor_check(TOP, mode='source-checkout')\n")
        assert not self._hits("run_doctor_check(TOP, mode='source_checkout')\n")
        assert not self._hits("run_doctor_check(TOP, mode=REPO_MODE_SOURCE_CHECKOUT)\n")

    def test_a_relative_root_after_a_chdir_to_the_live_root_is_caught(self):
        body = ("def test_x(monkeypatch):\n"
                "    monkeypatch.chdir(TOP)\n"
                "    run_self_host_check(Path('.'))\n")
        assert self._hits(body)
        assert not self._hits(body.replace("chdir(TOP)", "chdir(tmp_path)"))

    def test_source_checkout_mode_and_another_tree_are_left_alone(self):
        assert not self._hits("run_self_host_check(TOP, mode='source-checkout')\n")
        assert not self._hits("main([str(TOP), '--mode', 'source-checkout'])\n")
        assert not self._hits("subprocess.run(['espalier', 'self-host', str(TOP), '--mode', 'source-checkout'])\n")
        assert not self._hits("run_self_host_check(initialized_repo_root)\n")
        assert not self._hits("run_self_host_check(tmp_path)\n")
        assert not self._hits("subprocess.run(['espalier', 'doctor', str(tmp_path)])\n")
        assert not self._hits("run_doctor_check(Path(__file__).parent)\n")
        assert not self._hits("run_doctor_check(TOP / 'examples' / 'dogfooding')\n")
        assert not self._hits("unrelated(TOP)\n")

    def test_a_name_is_read_in_its_own_scope(self):
        """A function's own `root`, or a parameter of that name, shadows the
        module's live root, and another function's binding is not this one's;
        git's `init` is not espalier's."""
        body = ("root = TOP\n"
                "def a():\n    other = TOP\n"
                "def b(tmp_path):\n    root = tmp_path / 'repo'\n"
                "    subprocess.run(['espalier', 'doctor', str(root)])\n"
                "def c(root):\n    run_doctor_check(root)\n"
                "def d():\n    run_doctor_check(other)\n")
        assert not self._hits(body)
        assert self._hits(body.replace("tmp_path / 'repo'", "TOP"))
        assert self._hits(body + "def e():\n    run_doctor_check(root)\n")
        assert not self._hits("subprocess.run(['git', 'init', '-q', str(TOP)])\n")
        assert self._hits("subprocess.run(['espalier', 'init', str(TOP)])\n")

    def test_every_rebinding_shadows_and_every_join_evaluates(self):
        """A for / with / except / walrus / unpacking target shadows the module
        root; joinpath, os.path.join and Path(a, *parts) reach it."""
        for rebind in ("for TOP in [tmp_path]:\n        pass", "with open(p) as TOP:\n        pass",
                       "(TOP := tmp_path)", "TOP, other = tmp_path, 1",
                       "try:\n        pass\n    except OSError as TOP:\n        pass"):
            assert not self._hits(f"def f(tmp_path, p):\n    {rebind}\n    run_self_host_check(TOP)\n"), rebind
        assert self._hits("run_doctor_check(Path(__file__).parent.joinpath('..'))\n")
        assert self._hits("run_doctor_check(os.path.join(os.path.dirname(__file__), '..'))\n")
        assert self._hits("run_doctor_check(Path(Path(__file__).parent, '..'))\n")
        assert not self._hits("run_doctor_check(TOP.joinpath('examples'))\n")

    def test_the_mode_counts_only_as_a_mode_argument(self):
        assert self._hits("run_self_host_check(TOP, note='source-checkout')\n")
        assert self._hits("run_doctor_check(TOP, label='source_checkout')\n")
        assert not self._hits("cmd_self_host(Namespace(repo=str(TOP), mode='source-checkout'))\n")
        assert self._hits("subprocess.run(['espalier', 'self-host', str(TOP), '--why', 'source-checkout'])\n")

    def test_fuse_writes_its_output_tree_not_its_host(self):
        assert not self._hits("fuse_repos(TOP, tmp_path / 'out')\n")
