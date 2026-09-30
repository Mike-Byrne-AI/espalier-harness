"""Every deciding fail-open handler in ``tools/cc/hooks/`` speaks, or declares
its kind.

The rule (decided with the operator, 2026-09-30): fail-open stays allowed in
the hooks -- a toolbelt, not a security boundary (STANDING_PRINCIPLES §2) --
but SILENT fail-open does not. A fault inside a guard that reads as "nothing
found" is a defect the user cannot see; the four blocking hooks' umbrella
crash guards stay fail-CLOSED (the DEF-803 class), and everything below the
umbrella is fail-open WITH VOICE.

The population is derived, never hand-listed (the completeness-gate rule):
an AST walk over every ``except`` handler classifies a *deciding handler* --
one whose body (a) returns a falsy literal, (b) assigns a falsy default to a
name the enclosing scope reads after the ``try``, or (c) falls through to a
falsy ``return`` right after the ``try``. ``pass``/``continue`` handlers with
no later read are telemetry-shaped and outside. The population counts
speaking and silent members alike, so it does not shrink as sites are fixed:
the FLOOR below is the number the walk found at first execution, and a
population below it means the walk broke or a site was deleted, not that the
tree got cleaner.

A member passes when it SPEAKS -- ``raise``, a call to one of ``SPEAKING``
(``warn``, ``warn_exc``, ``append_audit``, ``_audit_deny``, ``_audit_block``,
``deny``, ``block``, ``say_once``, ``say_bad_stdin``), ``print(...,
file=sys.stderr)`` or ``sys.stderr.write`` -- or when it DECLARES its kind
with ``# fail-open: ok <kind> <reason>`` on the ``except`` line or the line
above (``telemetry``, ``cleanup``, ``text-fallback``, ``deliberate``), or on
line 1 of the file for a file-level declaration (``_bash_patterns.py``: a
parser that coarsens a match, never disarms a decision).

Earn-the-red (recorded 2026-09-30): at first run the gate named 97 silent
sites; removing one ``say_once`` from ``write_guard`` reds it by name. The
first form of this walk is ``reports/tp461/failopen_census.py`` (a gitignored
record); the test is the gate.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[1] / "tools" / "cc" / "hooks"

# The deciding population the walk found at first execution, all files
# (129 = 118 outside _bash_patterns.py + 11 inside it). A walk that finds
# fewer broke, or a site vanished without this floor being lowered on purpose.
DECIDING_FLOOR = 129

SPEAKING = frozenset({
    "warn", "warn_exc", "append_audit", "_audit_deny", "_audit_block",
    "deny", "block", "say_once", "say_bad_stdin",
})
PRAGMA = "# fail-open: ok"
KINDS = frozenset({"telemetry", "cleanup", "text-fallback", "deliberate"})


def _is_falsy_literal(node: ast.expr | None) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Constant):
        return node.value in (None, 0, False, "") and not isinstance(node.value, float)
    if isinstance(node, (ast.List, ast.Tuple)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    return False


def _callee_name(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _attr_chain(node: ast.expr) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _walk_no_nested_defs(node: ast.AST):
    stack = list(ast.iter_child_nodes(node))
    while stack:
        n = stack.pop()
        yield n
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(n))


def _body_nodes(handler: ast.ExceptHandler):
    for stmt in handler.body:
        yield stmt
        yield from _walk_no_nested_defs(stmt)


def _speaks(handler: ast.ExceptHandler) -> bool:
    for n in _body_nodes(handler):
        if isinstance(n, ast.Raise):
            return True
        if isinstance(n, ast.Call):
            name = _callee_name(n)
            if name in SPEAKING:
                return True
            if name == "print" and any(
                kw.arg == "file" and _attr_chain(kw.value) == "sys.stderr" for kw in n.keywords
            ):
                return True
            if _attr_chain(n.func) == "sys.stderr.write":
                return True
    return False


def _exits(handler: ast.ExceptHandler) -> bool:
    last = handler.body[-1] if handler.body else None
    return isinstance(last, (ast.Return, ast.Raise, ast.Continue, ast.Break))


def _returns_falsy(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(n, ast.Return) and _is_falsy_literal(n.value) for n in _body_nodes(handler))


def _falsy_assigns(handler: ast.ExceptHandler) -> set[str]:
    names: set[str] = set()
    for n in _body_nodes(handler):
        if isinstance(n, ast.Assign) and _is_falsy_literal(n.value):
            names.update(t.id for t in n.targets if isinstance(t, ast.Name))
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and _is_falsy_literal(n.value):
            names.add(n.target.id)
    return names


class _Scoper(ast.NodeVisitor):
    """Every Try with its enclosing scope node and the statement list it sits in."""

    def __init__(self) -> None:
        self.scope_stack: list[ast.AST] = []
        self.tries: list[tuple[ast.Try, ast.AST, list[ast.stmt]]] = []

    def _visit_block(self, block: list[ast.stmt]) -> None:
        for stmt in block:
            if isinstance(stmt, ast.Try):
                self.tries.append((stmt, self.scope_stack[-1], block))
            self.visit(stmt)

    def visit_Module(self, node: ast.Module) -> None:
        self.scope_stack.append(node)
        self._visit_block(node.body)
        self.scope_stack.pop()

    def _visit_def(self, node) -> None:
        self.scope_stack.append(node)
        self._visit_block(node.body)
        self.scope_stack.pop()

    visit_FunctionDef = _visit_def
    visit_AsyncFunctionDef = _visit_def
    visit_ClassDef = _visit_def

    def generic_visit(self, node: ast.AST) -> None:
        for _field, value in ast.iter_fields(node):
            if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                self._visit_block(value)
            elif isinstance(value, ast.AST):
                self.visit(value)


def _loads_after(scope: ast.AST, after_line: int) -> set[str]:
    return {
        n.id for n in ast.walk(scope)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and getattr(n, "lineno", 0) > after_line
    }


def _next_stmt_returns_falsy(block: list[ast.stmt], try_node: ast.Try) -> bool:
    idx = block.index(try_node)
    if idx + 1 < len(block):
        nxt = block[idx + 1]
        return isinstance(nxt, ast.Return) and _is_falsy_literal(nxt.value)
    return False


def _pragma_kind(line: str) -> str | None:
    """The declared kind on a pragma line, or None when the line carries none."""
    if PRAGMA not in line:
        return None
    rest = line.split(PRAGMA, 1)[1].strip()
    return rest.split(" ", 1)[0] if rest else ""


def _pragma_reason(line: str) -> str:
    """The text after the kind: the declaration's reason, which must exist."""
    rest = line.split(PRAGMA, 1)[1].strip()
    parts = rest.split(" ", 1)
    return parts[1].strip(" -") if len(parts) > 1 else ""


def census(path: Path) -> list[dict]:
    """Every deciding handler in ``path`` with whether it speaks or declares."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    tree = ast.parse(text)
    file_kind = _pragma_kind(lines[0]) if lines else None
    scoper = _Scoper()
    scoper.visit(tree)
    out: list[dict] = []
    for try_node, scope, block in scoper.tries:
        for h in try_node.handlers:
            kinds: list[str] = []
            if _returns_falsy(h):
                kinds.append("a")
            assigned = _falsy_assigns(h)
            if assigned & _loads_after(scope, try_node.end_lineno or h.lineno):
                kinds.append("b")
            if not _exits(h) and _next_stmt_returns_falsy(block, try_node):
                kinds.append("c")
            if not kinds:
                continue
            declared = file_kind
            reason = _pragma_reason(lines[0]) if file_kind is not None else ""
            for i in (h.lineno - 1, h.lineno - 2):
                if 0 <= i < len(lines) and declared is None:
                    declared = _pragma_kind(lines[i])
                    if declared is not None:
                        reason = _pragma_reason(lines[i])
            out.append({
                "file": path.name, "lineno": h.lineno, "scope": getattr(scope, "name", "<module>"),
                "kinds": kinds, "speaks": _speaks(h), "declared": declared, "reason": reason,
            })
    return out


def _population() -> list[dict]:
    sites: list[dict] = []
    for f in sorted(HOOKS_DIR.glob("*.py")):
        sites.extend(census(f))
    return sites


class TestFailOpenVoice:
    def test_the_walk_finds_the_population(self):
        n = len(_population())
        assert n >= DECIDING_FLOOR, (
            f"the deciding population is {n}, below the floor {DECIDING_FLOOR} recorded at "
            "first execution: the walk broke, or a site was deleted -- lower the floor on "
            "purpose in the same change, with the site named"
        )

    def test_every_deciding_fail_open_speaks_or_declares(self):
        silent = [s for s in _population() if not s["speaks"] and s["declared"] is None]
        assert not silent, (
            f"{len(silent)} deciding fail-open handler(s) neither speak nor declare a kind. "
            "Each must call one of the speaking set (say_once for a blocking hook, so the "
            "record exists), or carry `# fail-open: ok <kind> <reason>` on the except line or "
            "the line above (kinds: telemetry, cleanup, text-fallback, deliberate):\n  "
            + "\n  ".join(f"{s['file']}:{s['lineno']} {s['scope']} ({''.join(s['kinds'])})" for s in silent)
        )

    def test_every_declaration_names_a_known_kind(self):
        bad = [s for s in _population() if s["declared"] is not None and s["declared"] not in KINDS]
        assert not bad, (
            "a `# fail-open: ok` pragma must name a kind from "
            f"{sorted(KINDS)}: " + ", ".join(f"{s['file']}:{s['lineno']} ({s['declared']!r})" for s in bad)
        )

    def test_every_declaration_carries_a_reason(self):
        """The kind alone is wallpaper (`deliberate` fits every handler); the
        reason is the declaration. A bare `# fail-open: ok deliberate` reds."""
        bare = [s for s in _population() if s["declared"] is not None and len(s["reason"].split()) < 3]
        assert not bare, (
            "a `# fail-open: ok <kind>` pragma must carry a reason after the kind "
            "(three words or more): "
            + ", ".join(f"{s['file']}:{s['lineno']} ({s['reason']!r})" for s in bare)
        )

    def test_the_file_level_declaration_is_the_parsers_alone(self):
        """A line-1 declaration waives every deciding handler in the file at
        once. One file earns it -- the shell-syntax parser, whose fallbacks
        coarsen a match and never disarm a decision -- and a second one would
        turn the gate off for a whole hook without a red."""
        declared_files = {
            f.name for f in HOOKS_DIR.glob("*.py")
            if (lines := f.read_text(encoding="utf-8").splitlines()) and _pragma_kind(lines[0]) is not None
        }
        assert declared_files == {"_bash_patterns.py"}, declared_files

    def test_the_predicate_sees_the_verified_shapes(self, tmp_path):
        """The three fixture shapes the census was calibrated on, driven on a
        synthetic module: a falsy return, a falsy default read later, a
        fall-through to a falsy return; a pass-only handler is telemetry."""
        src = (
            "def a():\n    try:\n        x()\n    except OSError:\n        return {}\n"
            "def b():\n    try:\n        y = x()\n    except OSError:\n        y = []\n    return len(y)\n"
            "def c():\n    try:\n        x()\n    except OSError:\n        pass\n    return None\n"
            "def d():\n    try:\n        x()\n    except OSError:\n        pass\n    return 1\n"
            "def e():\n    try:\n        x()\n    except OSError:  # fail-open: ok telemetry a counter only\n        return 0\n"
            "def f():\n    try:\n        x()\n    except OSError:\n        warn('said')\n        return 0\n"
        )
        mod = tmp_path / "synthetic.py"
        mod.write_text(src, encoding="utf-8")
        sites = census(mod)
        by_scope = {s["scope"]: s for s in sites}
        assert set(by_scope) == {"a", "b", "c", "e", "f"}, sorted(by_scope)
        assert by_scope["a"]["kinds"] == ["a"] and not by_scope["a"]["speaks"]
        assert by_scope["b"]["kinds"] == ["b"]
        assert by_scope["c"]["kinds"] == ["c"]
        assert by_scope["e"]["declared"] == "telemetry"
        assert by_scope["f"]["speaks"]

    @pytest.mark.parametrize("event_type", [
        "pretooluse_failed_open_integrity_scan",
        "pretooluse_failed_open_speedbump",
    ])
    def test_the_two_verified_write_guard_sites_speak_through_say_once(self, event_type):
        """The two sites the census was calibrated on speak by name -- the
        mutation is deleting either call, which the gate above then names.
        Read by AST (the event type is a string argument of a `say_once` call),
        so a reformat cannot red it and a comment cannot green it."""
        tree = ast.parse((HOOKS_DIR / "write_guard.py").read_text(encoding="utf-8"))
        spoken = {
            arg.value for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _callee_name(node) == "say_once"
            for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        }
        assert event_type in spoken, f"write_guard.py lost its say_once for {event_type}"
