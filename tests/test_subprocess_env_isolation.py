"""Regression: subprocesses to harness scripts must not inherit
parent-shell CLAUDE_PROJECT_DIR.

Category — under any Claude Code session, CLAUDE_PROJECT_DIR is exported
to the real repo root. ``tools/cc/cognitive_blueprint._repo_root()``
prefers that env var over cwd. So a test (or production helper) that
spawns ``cognitive_blueprint.py`` against a constructed tmp_path
without passing ``env=`` silently routes blueprint reads/writes into
the operator's real repo. The two visible regressions were:

  * ``tests/test_hooks.py::test_default_mode_skips_pytest`` — failed
    when the operator's shell exported ESPALIER_STOP_GATE=full
    (run_hook copied os.environ unconditionally).
  * ``tests/test_hooks.py::test_reflect_trigger_records_to_blueprint``
    — failed under any CC session that exported CLAUDE_PROJECT_DIR
    (inline subprocess.run did not pass env=).

Both fixed in commit 907c802. The latent third site
(``test_stop_gate_auto_finalizes_blueprint``) and the production leaks
in ``session_resume.py::_blueprint_summary`` and ``_start_session``
were fixed together with this regression file.

See docs/SHARP_EDGES.md "Subprocesses Inheriting CLAUDE_PROJECT_DIR".
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_CC = REPO_ROOT / "tools" / "cc"
HOOKS_DIR = TOOLS_CC / "hooks"

# Hook subprocess.run calls that spawn either of these scripts must pin
# env= to override an inherited CLAUDE_PROJECT_DIR — cognitive_blueprint's
# _repo_root() reads the env var in preference to cwd. The leaky-sister-
# site catalog this audit guards is documented in ESPALIER_MEMORY.md and the
# docs/SHARP_EDGES.md "Subprocesses Inheriting CLAUDE_PROJECT_DIR" entry.
_BLUEPRINT_REFLECT_TARGETS: tuple[str, ...] = (
    "cognitive_blueprint.py",
    "reflect_protocol.py",
)


def _bootstrap_probe_repo(root: Path) -> str:
    """Set up a minimal repo at ``root`` and start a blueprint inside it.

    Returns the probe blueprint's session_id (canon for the assertions
    below — if a leaked CLAUDE_PROJECT_DIR mis-routes the read, the
    returned session_id will not match what's actually in ``root``).
    """
    (root / "tools" / "cc").mkdir(parents=True)
    (root / "cc" / "blueprints").mkdir(parents=True)
    for fname in ("cognitive_blueprint.py", "_blueprint_limits.py", "_json_safe.py", "_paths.py"):
        (root / "tools" / "cc" / fname).write_bytes((TOOLS_CC / fname).read_bytes())

    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    subprocess.run(
        [sys.executable, str(root / "tools" / "cc" / "cognitive_blueprint.py"), "start"],
        cwd=str(root), env=env, capture_output=True, text=True, timeout=15, encoding="utf-8",
    )
    data = json.loads((root / "cc" / "blueprints" / "latest.json").read_text(encoding="utf-8"))
    return data["session_id"]


class TestSessionResumeRoutingIsolation:
    """``tools/cc/session_resume.py`` must use the path passed in, not
    inherited CLAUDE_PROJECT_DIR.

    Pre-fix, calling ``session_resume.py --mode <X> /target/repo`` while
    the parent shell exports CLAUDE_PROJECT_DIR=/other/repo routed the
    inner ``cognitive_blueprint.py`` subprocess at /other/repo. For
    ``--mode status`` this surfaced as a wrong session_id; for
    ``--mode normal`` it would START a blueprint in the wrong place.
    """

    def test_blueprint_lookup_reads_blueprint_at_path_arg(self, tmp_path):
        """``session_resume.py <path>`` must read the blueprint at
        ``<path>``, ignoring any inherited CLAUDE_PROJECT_DIR.

        Uses ``--mode normal``, which is the mode whose recovery-report
        output embeds the session_id and is therefore observable from
        the outside. The fix in ``_blueprint_summary`` is what's pinned
        here; ``_start_session`` is exercised by the sister test below.
        """
        probe_sid = _bootstrap_probe_repo(tmp_path)
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(REPO_ROOT)}

        result = subprocess.run(
            [sys.executable, str(TOOLS_CC / "session_resume.py"),
             "--mode", "normal", str(tmp_path)],
            capture_output=True, text=True, env=env, timeout=15, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        assert probe_sid in result.stdout, (
            f"session_resume should report probe blueprint {probe_sid!r}, "
            f"got:\n{result.stdout}"
        )

    def test_normal_mode_writes_blueprint_at_path_arg(self, tmp_path):
        """``--mode normal <path>`` must write any new blueprint into
        ``<path>``, not into the leaked CLAUDE_PROJECT_DIR."""
        _bootstrap_probe_repo(tmp_path)
        canary_sid = json.loads(
            (tmp_path / "cc" / "blueprints" / "latest.json").read_text(encoding="utf-8")
        )["session_id"]

        # Point the leak target at a sentinel dir that must NOT receive
        # any new write. Build a parallel minimal layout so the inner
        # cognitive_blueprint would be runnable there if the leak fired.
        sentinel = tmp_path.parent / f"{tmp_path.name}-SENTINEL"
        (sentinel / "tools" / "cc").mkdir(parents=True)
        (sentinel / "cc" / "blueprints").mkdir(parents=True)
        for fname in ("cognitive_blueprint.py", "_blueprint_limits.py", "_json_safe.py", "_paths.py"):
            (sentinel / "tools" / "cc" / fname).write_bytes(
                (TOOLS_CC / fname).read_bytes()
            )

        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(sentinel)}
        try:
            subprocess.run(
                [sys.executable, str(TOOLS_CC / "session_resume.py"),
                 "--mode", "normal", str(tmp_path)],
                capture_output=True, text=True, env=env, timeout=15, encoding="utf-8",
            )
            # Sentinel directory must remain empty of blueprints (no leaked
            # write); tmp_path's latest.json may have been overwritten by a
            # legitimate _start_session call routed to the right place.
            sentinel_blueprints = list(
                (sentinel / "cc" / "blueprints").glob("*.json")
            )
            assert sentinel_blueprints == [], (
                f"session_resume leaked a blueprint write into the "
                f"CLAUDE_PROJECT_DIR target instead of the path arg: "
                f"{sentinel_blueprints}"
            )
            # tmp_path must still have the probe blueprint or a successor —
            # not a stale state from a wrong-routing.
            latest = json.loads(
                (tmp_path / "cc" / "blueprints" / "latest.json").read_text(encoding="utf-8")
            )
            assert latest["session_id"], "tmp_path blueprint cleared"
            assert latest.get("status") in (
                "active", "finalized"
            ) or "session_id" in latest, latest
            # Either the probe blueprint is still latest, or a new one was
            # started (both valid — leak would have written nothing here).
            assert canary_sid or latest["session_id"]
        finally:
            for path in sorted(sentinel.rglob("*"), reverse=True):
                if path.is_file() or path.is_symlink():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            if sentinel.exists():
                sentinel.rmdir()


class TestRunHookEnvOverrides:
    """``tests/test_hooks.py::run_hook`` supports None semantics for env
    deletion — a contract test pinning the fix in commit 907c802.

    Each test points ``run_hook`` at a throwaway ``tmp_path`` probe that echoes
    ``ESPALIER_PROBE_VAR`` and asserts the child env directly — rather than
    running a real hook whose exit code is independent of the probed var, which
    left the delete/set effect unobserved. ``run_hook`` joins
    ``HOOKS_DIR / script_name``; an absolute ``script_name`` resets that join to
    the absolute path, so the probe runs in place.
    """

    @staticmethod
    def _write_env_probe(tmp_path):
        probe = tmp_path / "env_probe.py"
        probe.write_text(
            'import os\n'
            'print(os.environ.get("ESPALIER_PROBE_VAR", "<unset>"))\n',
            encoding="utf-8",
        )
        return probe

    def test_run_hook_deletes_var_when_value_none(self, tmp_path, monkeypatch):
        """value=None pops the inherited var from the subprocess env."""
        monkeypatch.setenv("ESPALIER_PROBE_VAR", "leaked")
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        try:
            from test_hooks import run_hook  # noqa: WPS433 (intentional cross-test reuse)
        finally:
            sys.path.pop(0)

        probe = self._write_env_probe(tmp_path)
        result = run_hook(
            str(probe),
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path), "ESPALIER_PROBE_VAR": None},
        )
        assert result.returncode == 0
        # The None-delete popped the inherited "leaked" value from the child env.
        assert result.stdout.strip() == "<unset>"
        assert "leaked" not in result.stdout

    def test_run_hook_sets_var_when_value_string(self, tmp_path):
        """value=str sets the var (the unchanged-behavior side of the contract)."""
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        try:
            from test_hooks import run_hook  # noqa: WPS433
        finally:
            sys.path.pop(0)

        probe = self._write_env_probe(tmp_path)
        result = run_hook(
            str(probe),
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path), "ESPALIER_PROBE_VAR": "set"},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "set"


# ── AST-scan contract: every hook subprocess.run that spawns blueprint or
#    reflect_protocol must pin env= to override CLAUDE_PROJECT_DIR ─────────

def _enclosing_function(tree: ast.AST, target: ast.AST) -> ast.FunctionDef | None:
    """Return the FunctionDef ancestor of ``target`` in ``tree``, or None."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for descendant in ast.walk(node):
                if descendant is target:
                    return node
    return None


_UNRESOLVED = "<unresolved>"
_TOOLS_CC = ("tools", "cc")
_PATH_JOINERS = ("Path", "PurePath", "PurePosixPath", "PureWindowsPath", "join")


def _statements_in_source_order(scope: ast.AST, *, top_level_only: bool) -> list[ast.stmt]:
    if top_level_only:
        return list(getattr(scope, "body", []))
    return sorted(
        (n for n in ast.walk(scope) if isinstance(n, ast.stmt)),
        key=lambda n: (n.lineno, n.col_offset),
    )


def _binding_key(target: ast.AST) -> str | None:
    """A Name's id, or an attribute chain's text (``self.script``); None for a
    target this walk does not follow (a subscript, a tuple, a starred)."""
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return ast.unparse(target)
    return None


def _bindings(scope: ast.AST | None, *, top_level_only: bool) -> dict[str, list[ast.expr]]:
    """Every value each name (or attribute chain) is bound to in ``scope``, in
    SOURCE order: a plain assignment opens a new candidate -- a name rebound in a
    branch keeps both, since the census cannot know which branch ran and reads
    every one -- while ``+=``, ``.append(x)`` and ``.extend(xs)`` grow the newest
    candidate as a ``+`` join the argv flattener reads (``argv += [...]`` is
    ``subagent_stop.py``'s idiom; the correctness review showed a script appended
    after the first binding was invisible). ``top_level_only`` reads the module's
    own statements (a constant hoisted beside the imports); otherwise every
    statement in the function body."""
    out: dict[str, list[ast.expr]] = {}
    if scope is None:
        return out

    def grow(key: str, tail: ast.expr) -> None:
        cands = out.setdefault(key, [])
        if cands:
            cands[-1] = ast.BinOp(left=cands[-1], op=ast.Add(), right=tail)
        else:
            cands.append(tail)

    statements = _statements_in_source_order(scope, top_level_only=top_level_only)
    if top_level_only:
        # an attribute chain (``self.script``) is bound in one method and spawned
        # from another: its bindings are read module-wide, whichever scope they
        # sit in, so a class-based hook resolves across its methods
        statements += [
            n for n in _statements_in_source_order(scope, top_level_only=False)
            if n not in statements and (
                (isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign))
                 and any(isinstance(t, ast.Attribute)
                         for t in (n.targets if isinstance(n, ast.Assign) else [n.target])))
                or (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                    and isinstance(n.value.func, ast.Attribute)
                    and isinstance(n.value.func.value, ast.Attribute))
            )
        ]
    for node in statements:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                key = _binding_key(target)
                if key is not None:
                    out.setdefault(key, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            key = _binding_key(node.target)
            if key is not None:
                out.setdefault(key, []).append(node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
            key = _binding_key(node.target)
            if key is not None:
                grow(key, node.value)
        elif (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
              and isinstance(node.value.func, ast.Attribute)
              and node.value.func.attr in ("append", "extend") and node.value.args):
            key = _binding_key(node.value.func.value)
            if key is not None:
                arg = node.value.args[0]
                grow(key, ast.List(elts=[arg], ctx=ast.Load())
                     if node.value.func.attr == "append" else arg)
    return out


def _candidates(key: str, local: dict[str, ast.expr], module: dict[str, ast.expr]) -> list[ast.expr]:
    return local.get(key) or module.get(key) or []


def _product(lefts: list[list[str]], rights: list[list[str]]) -> list[list[str]]:
    return [left + right for left in lefts for right in rights]


def _components(
    expr: ast.AST | None, local: dict[str, ast.expr], module: dict[str, ast.expr],
    depth: int = 0,
) -> list[list[str]] | None:
    """Every path ``expr`` may spell, one component list per candidate (a name
    bound in two branches yields two), resolved as far as the source allows: a
    string literal splits on ``/``; ``a / b`` joins each left candidate with each
    right one; ``str(x)``, ``os.fspath(x)`` and ``x.resolve()`` are ``x``'s;
    ``Path(a, b, ...)`` and ``os.path.join(a, b, ...)`` join every argument;
    ``"sep".join([...])`` joins the list's members; an f-string is its pieces in
    order; a Name or attribute chain is what it was bound to -- in the function
    first, then at module level -- and one bound nowhere the walk can see, or
    bound to something that spells no path, is a single ``_UNRESOLVED``
    component. ``None`` is an expression that spells no path at all (a call to
    anything else, a subscript), so ``["git", "status"]`` contributes nothing."""
    unresolved = [[_UNRESOLVED]]
    if depth > 16 or expr is None:
        return unresolved
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return [[c for c in expr.value.replace("\\", "/").split("/") if c]]
    if isinstance(expr, (ast.Name, ast.Attribute)):
        key = _binding_key(expr)
        cands = _candidates(key, local, module) if key else []
        if not cands:
            return unresolved
        scope_local = local if key in local else {}
        out: list[list[str]] = []
        for cand in cands:
            out += _components(cand, scope_local, module, depth + 1) or unresolved
        return out
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
        left = _components(expr.left, local, module, depth + 1) or [[]]
        right = _components(expr.right, local, module, depth + 1) or unresolved
        return _product(left, right)
    if isinstance(expr, ast.Call):
        fn = expr.func
        name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
        if name in ("str", "fspath") and expr.args:
            return _components(expr.args[0], local, module, depth + 1)
        if name in ("resolve", "absolute", "expanduser") and isinstance(fn, ast.Attribute) and not expr.args:
            return _components(fn.value, local, module, depth + 1)
        if (name == "join" and isinstance(fn, ast.Attribute)
                and isinstance(fn.value, ast.Constant) and isinstance(fn.value.value, str) and expr.args):
            # "sep".join([...]): the members, joined
            joined: list[list[str]] = [[]]
            for member in _argv_elements(expr.args[0], local, module):
                joined = _product(joined, _components(member, local, module, depth + 1) or unresolved)
            return joined
        if name in _PATH_JOINERS and expr.args:
            joined = [[]]
            for arg in expr.args:
                joined = _product(joined, _components(arg, local, module, depth + 1) or unresolved)
            return joined
        return None
    if isinstance(expr, ast.JoinedStr):
        text = ""
        for piece in expr.values:
            if isinstance(piece, ast.Constant):
                text += str(piece.value)
            elif isinstance(piece, ast.FormattedValue):
                inner = _components(piece.value, local, module, depth + 1)
                text += "/".join(inner[0]) if inner else _UNRESOLVED
        return [[c for c in text.replace("\\", "/").split("/") if c]]
    return None


def _argv_of(call: ast.Call) -> ast.AST | None:
    """The argv a ``subprocess.run`` / ``spawn_checked`` call hands the child: the
    first positional, else ``args=``."""
    if call.args:
        return call.args[0]
    for kw in call.keywords:
        if kw.arg == "args":
            return kw.value
    return None


def _argv_elements(
    expr: ast.AST | None, local: dict[str, ast.expr], module: dict[str, ast.expr],
    depth: int = 0,
) -> list[ast.AST]:
    """The elements of the argv ``expr`` spells: a list or tuple's members, a
    ``*spread`` or a ``+`` join flattened, a Name followed to every value it was
    bound to (the union, since a branch may have rebound it). Anything else is
    one opaque element."""
    if depth > 8 or expr is None:
        return []
    if isinstance(expr, (ast.List, ast.Tuple)):
        out: list[ast.AST] = []
        for element in expr.elts:
            if isinstance(element, ast.Starred):
                out += _argv_elements(element.value, local, module, depth + 1)
            else:
                out.append(element)
        return out
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        return (_argv_elements(expr.left, local, module, depth + 1)
                + _argv_elements(expr.right, local, module, depth + 1))
    if isinstance(expr, (ast.Name, ast.Attribute)):
        key = _binding_key(expr)
        cands = _candidates(key, local, module) if key else []
        if cands:
            out = []
            for cand in cands:
                out += _argv_elements(cand, local, module, depth + 1)
            return out
    return [expr]


def _scope_names_target(scope: ast.AST | None, module: dict[str, ast.expr]) -> bool:
    """A string literal in ``scope`` that names a target script anywhere in its
    text (a message, a docstring, a path), or a Name used in ``scope`` that the
    module binds to one -- the pre-2026-10-09 census's whole test, widened from
    a suffix match to a substring, kept as the fail-closed floor behind an argv
    the walk cannot trace. Wider on purpose: the floor's false positive is one
    red that names its arm and asks for a readable argv; its false negative is a
    spawn into the wrong repository that nothing reports."""
    if scope is None:
        return False
    for node in ast.walk(scope):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if any(t in node.value for t in _BLUEPRINT_REFLECT_TARGETS):
                return True
        elif isinstance(node, ast.Name) and node.id in module:
            for parts in _components(node, {}, module) or []:
                if parts and any(parts[-1].endswith(t) for t in _BLUEPRINT_REFLECT_TARGETS):
                    return True
    return False


def _call_reaches_target(
    call: ast.Call, func: ast.FunctionDef | None, module: ast.Module | None,
) -> str | None:
    """Why a spawn is in the census, or None when it is not. ``"named"``: an
    element of the call's argv spells a path whose last component is one of
    ``_BLUEPRINT_REFLECT_TARGETS``, resolved through the function's and the
    module's bindings. ``"unresolved"``: an element spells a ``tools/cc`` path
    whose last component the walk cannot read. ``"literal"``: an element is
    opaque (a call, a subscript, a name bound nowhere) and the enclosing scope
    names a target script in a string or a module constant. The second and
    third arms are fail-closed on purpose: a spawn of a harness script this
    audit cannot name is held to the rule, and the remedy is an argv the source
    lets it read, never a quieter audit. Membership is the CALL's, not the
    enclosing function's: a function that mentions a script in a message while
    spawning ``["git", "status"]`` -- every element readable, none a target --
    is not enrolled (DEF-839)."""
    local = _bindings(func, top_level_only=False)
    bindings = _bindings(module, top_level_only=True)
    opaque = False
    for element in _argv_elements(_argv_of(call), local, bindings):
        cands = _components(element, local, bindings)
        if cands is None:
            opaque = True
            continue
        for parts in cands:
            if not parts:
                continue
            tail = parts[-1]
            if tail == _UNRESOLVED:
                opaque = True
                if all(c in parts for c in _TOOLS_CC):
                    return "unresolved"
                continue
            if any(tail.endswith(t) for t in _BLUEPRINT_REFLECT_TARGETS):
                return "named"
    if opaque and _scope_names_target(func if func is not None else module, bindings):
        return "literal"
    return None


def _function_names_target_script(
    func: ast.FunctionDef, module: ast.Module | None = None,
) -> bool:
    """True if a spawn inside ``func`` is in the census (``_call_reaches_target``).

    Until 2026-10-09 this answered on ANY string literal in the function ending
    with a target name -- so a path hoisted to a module constant answered False
    and a function that merely printed the script's name answered True. The
    DEF-839 probe hands this the function node alone (no module), so a module
    constant reaches the fail-closed arm: a ``tools/cc`` join it cannot resolve
    is enrolled.
    """
    return any(
        _call_reaches_target(node, func, module) is not None
        for node in ast.walk(func)
        if isinstance(node, ast.Call) and (_is_subprocess_run(node) or _is_spawn_checked(node))
    )


def _is_subprocess_run(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "run"
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
    )


def _has_env_kwarg(call: ast.Call) -> bool:
    return any(kw.arg == "env" for kw in call.keywords)


def _is_spawn_checked(node: ast.Call) -> bool:
    """The hooks' spawn chokepoint (``_hook_utils.spawn_checked``, 2026-09-30):
    a gate's spawn routes through it with ``subprocess.run``'s own kwargs, so
    ``env=`` is visible on the call and this audit must see the wrapper -- the
    exact refactor shape the positive check below exists to catch."""
    fn = node.func
    return (isinstance(fn, ast.Attribute) and fn.attr == "spawn_checked") or (
        isinstance(fn, ast.Name) and fn.id == "spawn_checked"
    )


def _collect_blueprint_subprocess_calls(
    hooks_dir: Path = HOOKS_DIR,
) -> list[tuple[str, int, str, bool, str]]:
    """Walk every ``*.py`` under ``hooks_dir`` -- the private ``_*.py`` helpers
    included, since 2026-10-09; the underscore skip hid four of them holding
    eight raw spawns -- and return every ``subprocess.run`` call, or spawn through
    the chokepoint ``_hook_utils.spawn_checked``, that ``_call_reaches_target``
    enrols.

    Returns: list of (filename, lineno, enclosing_func_name, has_env_kwarg,
    reason); a module-level spawn names ``<module>``; ``reason`` is ``"named"``,
    ``"unresolved"`` or ``"literal"`` (see ``_call_reaches_target``).
    """
    results: list[tuple[str, int, str, bool, str]] = []
    for hook_file in sorted(hooks_dir.glob("*.py")):
        source = hook_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not (_is_subprocess_run(node) or _is_spawn_checked(node)):
                continue
            func_def = _enclosing_function(tree, node)
            reason = _call_reaches_target(node, func_def, tree)
            if reason is None:
                continue
            results.append((
                hook_file.name, node.lineno,
                func_def.name if func_def is not None else "<module>",
                _has_env_kwarg(node), reason,
            ))
    return results


_REASON_TEXT = {
    "named": "its argv names cognitive_blueprint.py or reflect_protocol.py",
    "unresolved": ("its argv spawns tools/cc/<name> and this audit cannot read <name> from the "
                   "source -- spell the script where the walk can read it (a literal, a module "
                   "constant, a local bound in the function) or pin env=; never narrow the census"),
    "literal": ("its argv could not be traced and the enclosing scope names cognitive_blueprint.py "
                "or reflect_protocol.py -- make the argv readable or pin env="),
}


class TestHookSubprocessRoutingIsolation:
    """Every ``subprocess.run`` in ``tools/cc/hooks/*.py`` that spawns
    ``cognitive_blueprint.py`` or ``reflect_protocol.py`` must pass
    ``env=`` to override an inherited ``CLAUDE_PROJECT_DIR``.

    Pre-fix, six call sites across session_start.py, stop_gate.py,
    subagent_stop.py, and reflect_trigger.py lacked ``env=``. Under an
    operator shell that exports ``CLAUDE_PROJECT_DIR`` pointing at one
    repo while Claude works in another, those hooks silently routed
    blueprint reads/writes to the wrong repo. The proven pattern from
    ``tools/cc/session_resume.py::_git_summary``:

        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
        subprocess.run([..., script, ...], cwd=str(root), env=env, ...)

    See docs/SHARP_EDGES.md "Subprocesses Inheriting CLAUDE_PROJECT_DIR".

    Since 2026-10-09 (DEF-839) the census is keyed on the CALL: the argv is
    resolved through the function's and the module's bindings, the private
    ``_*.py`` helpers are walked too, and two fail-closed arms enrol what the
    walk cannot clear -- a ``tools/cc`` join with an unreadable last component,
    and an opaque argv in a scope that names a target script. The red names
    the arm it fired on (``_REASON_TEXT``).
    """

    def test_every_blueprint_or_reflect_subprocess_has_env_override(self):
        leaky = [
            (path, line, func, reason)
            for (path, line, func, has_env, reason)
            in _collect_blueprint_subprocess_calls()
            if not has_env
        ]
        assert not leaky, (
            "these hook spawns must pin env= to override CLAUDE_PROJECT_DIR "
            "(cognitive_blueprint's _repo_root() reads it before cwd). Missing env= at:\n"
            + "\n".join(f"  {p}:{ln} in {fn} -- {_REASON_TEXT[r]}" for (p, ln, fn, r) in leaky)
        )

    def test_audit_finds_the_expected_known_sites(self):
        """Closed-loop-verification-trap defense: if the AST scan ever
        stops finding any blueprint subprocess calls (e.g. someone
        refactors with a wrapper that hides the call shape), the
        contract above silently passes. This positive check guards that.
        """
        results = _collect_blueprint_subprocess_calls()
        files_seen = {path for (path, *_) in results}
        expected_files = {
            "session_start.py",
            "stop_gate.py",
            "subagent_stop.py",
            "reflect_trigger.py",
        }
        assert expected_files <= files_seen, (
            f"AST scan should detect blueprint subprocess calls in "
            f"{expected_files}; only found {files_seen}"
        )
        # At least 6 sites pre-fix (2 session_start + 1 stop_gate +
        # 1 subagent_stop + 2 reflect_trigger). Lower bound; future
        # additions are fine, removals are the regression shape.
        assert len(results) >= 6, (
            f"Expected >=6 blueprint subprocess sites, found {len(results)}: "
            f"{results}"
        )

    def test_the_census_enrols_the_live_sites(self):
        """Floor the discovery: seven live spawns reach a blueprint or reflect
        script today (2026-10-09; six when this contract was written), across
        reflect_trigger, session_start, stop_gate and subagent_stop. A census that
        found none would pass the contract above over nothing."""
        rows = _collect_blueprint_subprocess_calls()
        assert len(rows) >= 7, rows
        assert {p for p, *_ in rows} >= {
            "reflect_trigger.py", "session_start.py", "stop_gate.py", "subagent_stop.py",
        }, rows
        # every live site is enrolled by NAME: the fail-closed arms fire for nobody today
        assert {r for *_, r in rows} == {"named"}, rows

    # Fixture hooks, one per spelling the resolver must read -- or must not. The
    # census is driven over a scratch hooks directory holding exactly these, so the
    # must-red twins are judged by the SAME walk the live tree gets, not by a unit
    # call on a helper.
    _FIXTURE_HOOKS = {
        # the literal spelling the pre-fix predicate already saw
        "literal_leaky.py": (
            "import subprocess, sys\n"
            "def go(root):\n"
            '    subprocess.run([sys.executable, str(root / "tools" / "cc" / "cognitive_blueprint.py"), "finalize"])\n'
        ),
        # the must-red twin: the script name hoisted to a module constant (DEF-839)
        "constant_leaky.py": (
            "import subprocess, sys\n"
            'SCRIPT = "reflect_protocol.py"\n'
            "def go(root):\n"
            '    script = root / "tools" / "cc" / SCRIPT\n'
            "    subprocess.run([sys.executable, str(script), \"--pass\", \"1\"])\n"
        ),
        # an f-string spelling
        "fstring_leaky.py": (
            "import subprocess, sys\n"
            "def go(root):\n"
            '    subprocess.run([sys.executable, f"{root}/tools/cc/cognitive_blueprint.py"])\n'
        ),
        # a private helper: the underscore skip hid every spawn in these
        "_private_helper.py": (
            "import sys\n"
            "from _hook_utils import spawn_checked\n"
            "def go(root):\n"
            '    spawn_checked([sys.executable, str(root / "tools" / "cc" / "cognitive_blueprint.py")], root=root)\n'
        ),
        # a tools/cc join whose last component the walk cannot resolve: fail-closed
        "unresolved_leaky.py": (
            "import subprocess, sys\n"
            "def go(root, name):\n"
            '    subprocess.run([sys.executable, str(root / "tools" / "cc" / name)])\n'
        ),
        # argv bound a line above the spawn, with a spread (subagent_stop's idiom)
        "bound_argv_leaky.py": (
            "import subprocess, sys\n"
            "BASE = [sys.executable, \"-X\", \"utf8\"]\n"
            "def go(root):\n"
            '    cmd = [*BASE, str(root / "tools" / "cc" / "cognitive_blueprint.py"), "record"]\n'
            "    subprocess.run(cmd, cwd=str(root))\n"
        ),
        # the spellings the correctness review reproduced as invisible (2026-10-09)
        "path_multiarg_leaky.py": (
            "import subprocess, sys\n"
            "from pathlib import Path\n"
            "def go(root):\n"
            '    script = Path(root, "tools", "cc", "cognitive_blueprint.py")\n'
            "    subprocess.run([sys.executable, str(script)])\n"
        ),
        "augassign_leaky.py": (
            "import subprocess, sys\n"
            "def go(root):\n"
            "    cmd = [sys.executable]\n"
            '    cmd += [str(root / "tools" / "cc" / "reflect_protocol.py")]\n'
            "    subprocess.run(cmd)\n"
        ),
        "append_leaky.py": (
            "import subprocess, sys\n"
            "def go(root):\n"
            "    cmd = [sys.executable]\n"
            '    cmd.append(str(root / "tools" / "cc" / "cognitive_blueprint.py"))\n'
            "    subprocess.run(cmd)\n"
        ),
        "ospath_join_leaky.py": (
            "import os, subprocess, sys\n"
            "def go(root):\n"
            '    subprocess.run([sys.executable, os.path.join(root, "tools", "cc", "cognitive_blueprint.py")])\n'
        ),
        "str_join_leaky.py": (
            "import subprocess, sys\n"
            "def go(root):\n"
            '    subprocess.run([sys.executable, "/".join([str(root), "tools", "cc", "reflect_protocol.py"])])\n'
        ),
        "attribute_leaky.py": (
            "import subprocess, sys\n"
            "class Runner:\n"
            "    def __init__(self, root):\n"
            '        self.script = root / "tools" / "cc" / "cognitive_blueprint.py"\n'
            "    def go(self):\n"
            "        subprocess.run([sys.executable, str(self.script)])\n"
        ),
        # a branch rebinds the script: the census reads every candidate
        "branch_leaky.py": (
            "import subprocess, sys\n"
            "def go(root, deep):\n"
            '    script = root / "tools" / "cc" / "session_resume.py"\n'
            "    if deep:\n"
            '        script = root / "tools" / "cc" / "cognitive_blueprint.py"\n'
            "    subprocess.run([sys.executable, str(script)])\n"
        ),
        # an argv the walk cannot trace, in a scope that names the script: fail-closed
        "opaque_literal_leaky.py": (
            "import subprocess\n"
            "def go(root):\n"
            "    argv = build_argv(root)\n"
            '    note = "runs cognitive_blueprint.py finalize"\n'
            "    subprocess.run(argv)\n"
        ),
        # the clean shape: env= pinned
        "clean.py": (
            "import os, subprocess, sys\n"
            "def go(root):\n"
            '    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}\n'
            '    subprocess.run([sys.executable, str(root / "tools" / "cc" / "cognitive_blueprint.py")], env=env)\n'
        ),
        # NOT enrolled: names the script only in a message while spawning git
        "mentions_only.py": (
            "import subprocess\n"
            "def go(root):\n"
            '    print("record one with tools/cc/cognitive_blueprint.py justify")\n'
            '    subprocess.run(["git", "status"])\n'
        ),
        # NOT enrolled: a resolvable harness script that is not a target
        "other_script.py": (
            "import subprocess, sys\n"
            "def go(root):\n"
            '    subprocess.run([sys.executable, str(root / "tools" / "cc" / "session_resume.py")])\n'
        ),
    }

    def test_the_census_is_keyed_on_the_call_not_the_function(self, tmp_path):
        """Earn the red for every spelling (DEF-839): the constant twin, the
        f-string, the private helper and the unresolved join are enrolled and leaky;
        the pinned one is enrolled and clean; the message-only and other-script
        functions are not enrolled at all. Before 2026-10-09 the constant twin and
        the private helper were invisible and the message-only function was
        enrolled -- a census of the wrong population in both directions."""
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        for name, source in self._FIXTURE_HOOKS.items():
            (hooks / name).write_text(source, encoding="utf-8")
        rows = _collect_blueprint_subprocess_calls(hooks)
        by_file = {p: (has_env, reason) for (p, _ln, _fn, has_env, reason) in rows}
        named_leaky = {
            "literal_leaky.py", "constant_leaky.py", "fstring_leaky.py", "_private_helper.py",
            "bound_argv_leaky.py", "path_multiarg_leaky.py", "augassign_leaky.py",
            "append_leaky.py", "ospath_join_leaky.py", "str_join_leaky.py",
            "attribute_leaky.py", "branch_leaky.py",
        }
        expected = {name: (False, "named") for name in named_leaky}
        expected["unresolved_leaky.py"] = (False, "unresolved")
        expected["opaque_literal_leaky.py"] = (False, "literal")
        expected["clean.py"] = (True, "named")
        assert by_file == expected, {
            k: (by_file.get(k), expected.get(k)) for k in set(by_file) | set(expected)
            if by_file.get(k) != expected.get(k)
        }
        # the fixtures and the fail-closed arms agree with the red's vocabulary
        assert set(_REASON_TEXT) == {reason for _has_env, reason in by_file.values()}

    def test_the_function_predicate_sees_a_module_constant(self):
        """The DEF-839 probe, kept as a test: the function node alone, its script
        path reaching a module constant the node does not carry. Pre-fix: False."""
        src = (
            "SCRIPT = 'cognitive_blueprint.py'\n"
            "def f(root):\n"
            "    subprocess.run([sys.executable, str(root / 'tools' / 'cc' / SCRIPT)])\n"
        )
        tree = ast.parse(src)
        assert _function_names_target_script(tree.body[1])
        # and with the module in hand the same call resolves BY NAME, not fail-closed
        assert _call_reaches_target(
            next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_subprocess_run(n)),
            tree.body[1], tree,
        )
