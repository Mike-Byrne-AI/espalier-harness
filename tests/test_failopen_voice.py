"""Every deciding fail-open handler in ``tools/cc/hooks/`` speaks where it is
seen, or declares its kind; and every stderr line there pairs with a seen
speaker, or declares that the debug log is where it belongs.

The rule (decided with the operator, 2026-09-30): fail-open stays allowed in
the hooks -- a toolbelt, not a security boundary (STANDING_PRINCIPLES §2) --
but SILENT fail-open does not. A fault inside a guard that reads as "nothing
found" is a defect the user cannot see; the four blocking hooks' umbrella
crash guards stay fail-CLOSED (the DEF-803 class), and everything below the
umbrella is fail-open WITH VOICE.

WHAT COUNTS AS VOICE (corrected 2026-10-06). The protocol pin
(``docs/external/cc-hook-protocol.md``) sends the stderr of a hook that exits
0 to the debug log only: Claude never sees it and the transcript never shows
it. Until this date the gate counted a ``warn`` or a stderr print as speech,
so exit-0 handlers that left no record and showed nothing passed as voiced.
A speaker is now one of two kinds:

* SEEN -- ``RECORDED`` (a record ``/status --log`` counts, or the deny/block
  decision object the pin delivers) or ``COLLECTED`` (a line kept for the
  additionalContext of the hook's ONE stdout JSON object: ``_hook_utils.advise``
  and its two faces, rendered by the hooks that call them).
* STDERR-ONLY -- ``warn``, ``warn_exc``, ``print(..., file=sys.stderr)``,
  ``sys.stderr.write``: the debug log.

Part one, the handler census. The population is derived, never hand-listed
(the completeness-gate rule): an AST walk over every ``except`` handler
classifies a *deciding handler* -- one whose body (a) returns a falsy literal,
(b) assigns a falsy default to a name the enclosing scope reads after the
``try``, or (c) falls through to a falsy ``return`` right after the ``try``.
``pass``/``continue`` handlers with no later read are telemetry-shaped and
outside. The population counts speaking and silent members alike, so it does
not shrink as sites are fixed: the FLOOR below is the number the walk found at
first execution. A member passes when it raises or calls a SEEN speaker, or
DECLARES its kind with ``# fail-open: ok <kind> <reason>`` on the ``except``
line or the line above (``telemetry``, ``cleanup``, ``text-fallback``,
``deliberate``), or on line 1 of the file (``_bash_patterns.py`` alone). A
member that speaks only on stderr reds unless that line is declared below.

Part two, the call-site census. Most stderr lines sit outside any deciding
handler (a reporter's warning, a crash guard's line), so part one never sees
them. Every ``warn``, ``warn_exc``, ``print(..., file=sys.stderr)`` and
``sys.stderr.write`` call in ``tools/cc/hooks/`` pairs, within its enclosing
statement block, with a SEEN speaker -- or declares ``# voice: <kind>
<reason>`` on its line or the line above, the kind one of ``VOICE_KINDS``. The
block is the statement list the call sits in, widened through a ``try`` body,
a ``finally`` and a ``with`` body (code that runs whenever the line does) and
no further: function scope is too wide, because ``stop_gate._gate_pytest``
records on other branches beside both Gate 1 skips. A collector counts only in
a hook that renders it (``TestCollectedAdvisoriesAreRendered``).

Earn-the-red (recorded 2026-09-30): at first run the gate named 97 silent
sites; removing one ``say_once`` from ``write_guard`` reds it by name. Recorded
2026-10-06: on the tree before the voice repairs, part one named 29 of 145
deciding handlers that spoke only on stderr, and part two named 110 of 118
stderr lines that paired with nothing and declared nothing. The first form of
the handler walk is
``reports/tp461/failopen_census.py`` (a gitignored record); the test is the
gate.
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

# The stderr call-site population after the 2026-10-06 voice repairs moved the
# reporters' lines into ``advise`` and the crash guards' into ``say_once``: a
# walk that finds fewer broke, or a line was removed without this floor being
# lowered on purpose in the same change.
STDERR_FLOOR = 50

#: Speakers that leave a record ``/status --log`` counts, or the decision
#: object the pin delivers to Claude (a PreToolUse deny, a Stop or ConfigChange
#: block).
RECORDED = frozenset({
    "say_once", "say_bad_stdin", "append_audit", "_audit_deny", "_audit_block",
    "deny", "block",
})
#: Speakers that keep a line for the additionalContext of the hook's ONE
#: stdout JSON object (``_hook_utils.advise``); seen only where the hook renders
#: them, which ``TestCollectedAdvisoriesAreRendered`` checks.
COLLECTED = frozenset({"advise", "advise_warn", "advise_exc"})
SEEN = RECORDED | COLLECTED
#: Speakers whose only channel is stderr: the debug log, for an exit-0 hook.
STDERR_ONLY = frozenset({"warn", "warn_exc"})
#: The calls that render a hook's collected advisories into its JSON object.
RENDERERS = frozenset({"take_advisories", "emit_advisories"})

PRAGMA = "# fail-open: ok"
KINDS = frozenset({"telemetry", "cleanup", "text-fallback", "deliberate"})

VOICE_PRAGMA = "# voice:"
#: ``sink`` -- the body of a speaker other code calls (warn, warn_exc,
#: say_once, advise, append_audit); ``decision`` -- the line rides a deny, a
#: block or an exit the pin shows (exit 2, a fail-closed path); ``twin`` -- the
#: same fact already reaches a seen channel on this path (the hook's JSON
#: object, a record written above, the SessionStart banner); ``debug-log`` --
#: the debug log on purpose, the reason saying why; ``cli`` -- reached only
#: from a command-line program, whose stderr is the operator's terminal.
VOICE_KINDS = frozenset({"sink", "decision", "twin", "debug-log", "cli"})


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


def _is_stderr_call(call: ast.Call) -> bool:
    """A call whose only channel is stderr: ``warn``, ``warn_exc``, a print to
    ``sys.stderr`` or ``sys.stderr.write``."""
    name = _callee_name(call)
    if name in STDERR_ONLY:
        return True
    if name == "print" and any(
        kw.arg == "file" and _attr_chain(kw.value) == "sys.stderr" for kw in call.keywords
    ):
        return True
    return _attr_chain(call.func) == "sys.stderr.write"


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


def _voice(handler: ast.ExceptHandler) -> str | None:
    """``"seen"`` when the handler raises or calls a SEEN speaker, ``"stderr"``
    when its only speech is a stderr call, ``None`` when it is silent."""
    stderr = False
    for n in _body_nodes(handler):
        if isinstance(n, ast.Raise):
            return "seen"
        if isinstance(n, ast.Call):
            if _callee_name(n) in SEEN:
                return "seen"
            if _is_stderr_call(n):
                stderr = True
    return "stderr" if stderr else None


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


def _voice_declaration(lines: list[str], lineno: int) -> tuple[str | None, str]:
    """``(kind, reason)`` of a ``# voice:`` pragma on line ``lineno`` (1-based)
    or the line above it; ``(None, "")`` when neither carries one."""
    for i in (lineno - 1, lineno - 2):
        if 0 <= i < len(lines) and VOICE_PRAGMA in lines[i]:
            rest = lines[i].split(VOICE_PRAGMA, 1)[1].strip()
            parts = rest.split(" ", 1)
            return parts[0], (parts[1].strip(" -") if len(parts) > 1 else "")
    return None, ""


def census(path: Path) -> list[dict]:
    """Every deciding handler in ``path`` with how it speaks or what it declares."""
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
            voice = _voice(h)
            stderr_lines = [
                n for n in _body_nodes(h) if isinstance(n, ast.Call) and _is_stderr_call(n)
            ]
            out.append({
                "file": path.name, "lineno": h.lineno, "scope": getattr(scope, "name", "<module>"),
                "kinds": kinds, "speaks": voice is not None, "voice": voice,
                "declared": declared, "reason": reason,
                # A stderr-only handler is declared when every one of its lines is.
                "voice_declared": bool(stderr_lines) and all(
                    _voice_declaration(lines, n.lineno)[0] is not None for n in stderr_lines
                ),
            })
    return out


def _population() -> list[dict]:
    sites: list[dict] = []
    for f in sorted(HOOKS_DIR.glob("*.py")):
        sites.extend(census(f))
    return sites


# ── Part two: the call-site census ─────────────────────────────────────────────

#: A statement list nested here runs whenever the statement holding it does, so
#: it belongs to the same pairing unit as the list that statement sits in.
_UNCONDITIONAL = {
    ast.Try: ("body", "finalbody"),
    ast.With: ("body",),
    ast.AsyncWith: ("body",),
}
if hasattr(ast, "TryStar"):  # 3.11+
    _UNCONDITIONAL[ast.TryStar] = ("body", "finalbody")


def _own_nodes(stmt: ast.stmt):
    """The nodes of ``stmt`` itself: its expressions, never a nested statement
    list (a branch, a loop body, a handler) and never a nested definition."""
    stack = [c for c in ast.iter_child_nodes(stmt) if not isinstance(c, (ast.stmt, ast.excepthandler))]
    while stack:
        n = stack.pop()
        yield n
        if isinstance(n, ast.Lambda):
            continue
        stack.extend(ast.iter_child_nodes(n))


def _unit_calls(block: list[ast.stmt]):
    """Every call a pairing unit makes: the block's statements' own calls, and
    the calls of the unconditional statement lists nested in them."""
    for stmt in block:
        for n in _own_nodes(stmt):
            if isinstance(n, ast.Call):
                yield n
        for field in _UNCONDITIONAL.get(type(stmt), ()):
            yield from _unit_calls(getattr(stmt, field))


class _Blocks(ast.NodeVisitor):
    """Every statement list with its pairing unit and enclosing scope name."""

    def __init__(self) -> None:
        self.scope: list[str] = []
        self.sites: list[tuple[ast.Call, list[ast.stmt], str]] = []

    def _block(self, block: list[ast.stmt], unit: list[ast.stmt]) -> None:
        for stmt in block:
            for n in _own_nodes(stmt):
                if isinstance(n, ast.Call) and _is_stderr_call(n):
                    self.sites.append((n, unit, ".".join(self.scope) or "<module>"))
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.scope.append(stmt.name)
                self._block(stmt.body, stmt.body)
                self.scope.pop()
                continue
            widened = _UNCONDITIONAL.get(type(stmt), ())
            for field, value in ast.iter_fields(stmt):
                if field in widened:
                    self._block(value, unit)
                elif isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                    self._block(value, value)
                elif isinstance(value, list) and value and isinstance(value[0], (ast.excepthandler, ast.match_case)):
                    for h in value:
                        self._block(h.body, h.body)

    def visit_Module(self, node: ast.Module) -> None:
        self._block(node.body, node.body)


def stderr_sites(path: Path) -> list[dict]:
    """Every stderr-only call in ``path`` with whether its pairing unit holds a
    SEEN speaker, and what it declares."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    walker = _Blocks()
    walker.visit(ast.parse(text))
    out: list[dict] = []
    for call, unit, scope in walker.sites:
        kind, reason = _voice_declaration(lines, call.lineno)
        out.append({
            "file": path.name, "lineno": call.lineno, "scope": scope,
            "call": _callee_name(call),
            "paired": any(_callee_name(c) in SEEN for c in _unit_calls(unit)),
            "declared": kind, "reason": reason,
        })
    return out


def _stderr_population() -> list[dict]:
    sites: list[dict] = []
    for f in sorted(HOOKS_DIR.glob("*.py")):
        sites.extend(stderr_sites(f))
    return sites


def _calls_in(path: Path) -> set[str]:
    return {
        _callee_name(n) for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(n, ast.Call)
    }


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

    def test_no_deciding_fail_open_speaks_only_to_the_debug_log(self):
        """A handler whose only speech is a stderr line is silent to Claude and
        to the transcript (the pin: exit-0 stderr reaches the debug log only).
        It routes through a SEEN speaker -- say_once, or advise in a hook that
        renders it -- or declares its kind, or declares each stderr line's voice."""
        unseen = [
            s for s in _population()
            if s["voice"] == "stderr" and s["declared"] is None and not s["voice_declared"]
        ]
        assert not unseen, (
            f"{len(unseen)} deciding fail-open handler(s) speak only on stderr, which an exit-0 "
            "hook sends to the debug log (docs/external/cc-hook-protocol.md). Route each "
            "through say_once (a record /status --log counts) or _hook_utils.advise (the "
            "hook's JSON object), or declare it:\n  "
            + "\n  ".join(f"{s['file']}:{s['lineno']} {s['scope']} ({''.join(s['kinds'])})" for s in unseen)
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
        fall-through to a falsy return; a pass-only handler is telemetry. A
        handler that only warns is voiced to the debug log, not seen."""
        src = (
            "def a():\n    try:\n        x()\n    except OSError:\n        return {}\n"
            "def b():\n    try:\n        y = x()\n    except OSError:\n        y = []\n    return len(y)\n"
            "def c():\n    try:\n        x()\n    except OSError:\n        pass\n    return None\n"
            "def d():\n    try:\n        x()\n    except OSError:\n        pass\n    return 1\n"
            "def e():\n    try:\n        x()\n    except OSError:  # fail-open: ok telemetry a counter only\n        return 0\n"
            "def f():\n    try:\n        x()\n    except OSError:\n        warn('said')\n        return 0\n"
            "def g():\n    try:\n        x()\n    except OSError:\n        say_once(r, 'k', 'h', 'e', 'm')\n        return 0\n"
            "def h():\n    try:\n        x()\n    except OSError:\n        # voice: debug-log a hand-run probe's own notice\n"
            "        warn('said')\n        return 0\n"
        )
        mod = tmp_path / "synthetic.py"
        mod.write_text(src, encoding="utf-8")
        sites = census(mod)
        by_scope = {s["scope"]: s for s in sites}
        assert set(by_scope) == {"a", "b", "c", "e", "f", "g", "h"}, sorted(by_scope)
        assert by_scope["a"]["kinds"] == ["a"] and not by_scope["a"]["speaks"]
        assert by_scope["b"]["kinds"] == ["b"]
        assert by_scope["c"]["kinds"] == ["c"]
        assert by_scope["e"]["declared"] == "telemetry"
        assert by_scope["f"]["speaks"] and by_scope["f"]["voice"] == "stderr"
        assert not by_scope["f"]["voice_declared"]
        assert by_scope["g"]["voice"] == "seen"
        assert by_scope["h"]["voice"] == "stderr" and by_scope["h"]["voice_declared"]

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


class TestStderrLinesAreSeenOrDeclared:
    """Part two: every stderr-only line in the hooks pairs with a SEEN speaker
    in its block, or declares its voice."""

    def test_the_census_finds_the_population(self):
        n = len(_stderr_population())
        assert n >= STDERR_FLOOR, (
            f"the stderr call-site population is {n}, below the floor {STDERR_FLOOR}: the "
            "walk broke, or a line was removed -- lower the floor on purpose in the same "
            "change, with the line named"
        )

    def test_every_stderr_line_pairs_with_a_seen_speaker_or_declares(self):
        unseen = [s for s in _stderr_population() if not s["paired"] and s["declared"] is None]
        assert not unseen, (
            f"{len(unseen)} stderr line(s) in tools/cc/hooks/ reach only the debug log on an "
            "exit-0 path (docs/external/cc-hook-protocol.md) and declare nothing. Pair each, in "
            "the same block, with a seen speaker -- _hook_utils.advise in a hook that renders "
            "it into its JSON object, or say_once / append_audit for a record -- or carry "
            "`# voice: <kind> <reason>` on its line or the line above (kinds: "
            f"{', '.join(sorted(VOICE_KINDS))}):\n  "
            + "\n  ".join(f"{s['file']}:{s['lineno']} {s['scope']} ({s['call']})" for s in unseen)
        )

    def test_every_voice_declaration_names_a_known_kind(self):
        bad = [s for s in _stderr_population() if s["declared"] is not None and s["declared"] not in VOICE_KINDS]
        assert not bad, (
            f"a `# voice:` pragma must name a kind from {sorted(VOICE_KINDS)}: "
            + ", ".join(f"{s['file']}:{s['lineno']} ({s['declared']!r})" for s in bad)
        )

    def test_every_voice_declaration_carries_a_reason(self):
        """`debug-log` alone fits every line; the reason is the declaration."""
        bare = [s for s in _stderr_population() if s["declared"] is not None and len(s["reason"].split()) < 3]
        assert not bare, (
            "a `# voice: <kind>` pragma must carry a reason after the kind (three words or "
            "more): " + ", ".join(f"{s['file']}:{s['lineno']} ({s['reason']!r})" for s in bare)
        )

    def test_the_census_predicate_sees_the_verified_shapes(self, tmp_path):
        """The shapes the census was calibrated on, on a synthetic module: a
        lone warn reds; a warn beside a record in its block pairs; a warn on one
        branch with the record on its sibling (the Gate 1 shape) does not; a
        warn in a try body with the record in the block around it pairs; a
        declared line passes on the line above and on its own line."""
        src = (
            "def lone():\n    warn('x')\n"
            "def beside():\n    warn('x')\n    say_once(r, 'k', 'h', 'e', 'm')\n"
            "def sibling(c):\n    if c:\n        sys.stderr.write('x')\n        return 0\n"
            "    say_once(r, 'k', 'h', 'e', 'm')\n    return 0\n"
            "def in_try():\n    try:\n        print('x', file=sys.stderr)\n    except OSError:\n        pass\n"
            "    append_audit(r, {})\n"
            "def collected():\n    warn('x')\n    advise('x')\n"
            "def above():\n    # voice: debug-log a hand-run probe's notice\n    warn('x')\n"
            "def inline():\n    warn('x')  # voice: cli the usage line of a program\n"
        )
        mod = tmp_path / "synthetic.py"
        mod.write_text(src, encoding="utf-8")
        by_scope = {s["scope"]: s for s in stderr_sites(mod)}
        assert set(by_scope) == {"lone", "beside", "sibling", "in_try", "collected", "above", "inline"}
        assert not by_scope["lone"]["paired"] and by_scope["lone"]["declared"] is None
        assert by_scope["beside"]["paired"]
        assert not by_scope["sibling"]["paired"]
        assert by_scope["in_try"]["paired"]
        assert by_scope["collected"]["paired"]
        assert by_scope["above"]["declared"] == "debug-log"
        assert by_scope["inline"]["declared"] == "cli"


class TestCollectedAdvisoriesAreRendered:
    """``advise`` keeps a line for the hook's ONE stdout JSON object, so it is
    seen only where the hook renders the collector. A hook that collects and
    never renders turns every advisory back into a debug-log line while the
    census above counts it as seen."""

    def test_every_hook_that_collects_renders(self):
        unrendered = sorted(
            f.name for f in HOOKS_DIR.glob("*.py")
            if not f.name.startswith("_") and (calls := _calls_in(f)) & COLLECTED and not calls & RENDERERS
        )
        assert not unrendered, (
            f"{unrendered} call _hook_utils.advise but never render the collector "
            "(take_advisories into the banner, or emit_advisories into the one JSON object)"
        )

    def test_no_shared_helper_collects(self):
        """A helper module runs inside every hook that imports it, and most of
        those hooks render nothing: a collected line there is a debug-log line
        in a write_guard process. The collector's own home is the exception."""
        helpers = sorted(
            f.name for f in HOOKS_DIR.glob("_*.py")
            if f.name != "_hook_utils.py" and _calls_in(f) & COLLECTED
        )
        assert not helpers, f"{helpers} call _hook_utils.advise from a shared helper"
