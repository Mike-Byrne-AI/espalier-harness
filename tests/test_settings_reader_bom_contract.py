"""Every reader of ``.claude/settings.json`` or of an operator-writable record
must decode BOM-tolerantly.

This contract pins the property that no settings reader can be added without
BOM tolerance, and it exists because the prose that used to assert that property
was both wrong and unenforced. Without this, the failure mode is silent: a
Windows adopter's file parses nowhere, and the reader that skipped the shared
decoder is found only when someone happens to drive it.

WHY THIS IS A CONTRACT AND NOT A REVIEW HABIT. On 2026-08-26 a new settings
reader was added to ``espalier/cli.py`` with a plain ``read_text(encoding="utf-8")``.
It shipped through a 9,266-test green suite and two review passes. An adversarial
pass found it: a UTF-16 file (Windows PowerShell's ``Out-File`` default) raised
``UnicodeDecodeError`` and crashed the command on a healthy repo, and a UTF-8 BOM
took the parse-failure path and restored the exact defect that reader was written
to close. The repo already had nine correct readers, one of them ninety-six lines
above the new one in the same file.

``docs/sharp-edges/deleted-governance-event-fail-open.md`` asserted in prose that
"All seven settings.json readers decode through a shared BOM-detecting helper."
Measured then (2026-08-26): sixteen readers, and the claim was never enforced by anything. A
sentence in a doc cannot notice the tenth reader. This test can.

DESIGN. An AST census of every ``read_text``/``read_bytes``/``open`` whose target
is a settings.json-shaped path or an operator-writable record, in ``espalier/``
and ``tools/cc/``. Each must either route through a BOM-decoding helper, or carry
a ``# bom-exempt: <reason>`` comment stating why not -- the idiom
``tools/cc/ci_guard.py`` already uses for a deliberate non-tolerant read. An
exemption with no reason is not an exemption.

WIDENED 2026-09-15 (ledger row DEF-797). The same shape recurred one surface
over. The Stop gate's relief record -- the file ``docs/TROUBLESHOOTING.md``
invites a blocked operator to write by hand -- was read strictly, and Windows
PowerShell 5.1's ``>`` and ``Out-File`` write UTF-16LE; the documented escape
hatch crashed the gate fail-closed (driven on the Windows host 2026-09-14). The
census now covers the records an operator is invited to write: the two relief
flags under ``.espalier-state/``, ``cc/GOAL.md`` and ``ESPALIER_MEMORY.md``. And
it reads the ENCLOSING FUNCTION'S NAME as well as the lines around the read,
because a helper's target is named at its call sites, not at its read:
``_relief_record(root, flag)`` reads ``STATE_DIR / flag`` and never spells the
flag, so a window-only census could not see the very site the widening was for
(measured before the widening: the vocabulary alone enrolled five new sites and
missed that one). ``decode_text_or_problem``, the owner of the decode-then-check
idiom and its one sentence, counts as a helper beside ``decode_bom``.

RE-KEYED 2026-09-16 (ledger row DEF-820). The first census marked a read
guarded when a helper's NAME appeared anywhere in its enclosing function or in
the lines around the call, so a second strict read added beside a guarded one
was auto-greened -- the exact shape the contract exists to catch, found by hand
in ``cmd_memory_prune`` (about 250 lines) during the failure-mode review of the
widening, not by the contract. The guard now follows the read's own bytes
(``_read_guard``): a read is guarded when the read call sits inside a BOM
helper's argument, or when the name its result is bound to (an assignment, an
annotated assignment, a walrus, a with-item; followed through an alias, an
attribute, a subscript, a method-call chain such as ``fh.read()``, an ``or``
default) is consumed by a helper while that definition still reaches the
consumer. A definition is cut off by a rebinding of the name at the same or an
enclosing level between it and the consumer, by a rebinding in the consumer's
own block at or before the consumer, and by a loop target, comprehension
target, parameter or ``except ... as`` whose region holds the consumer -- a
rebinding inside ``try: ... except: return`` counts at the try's own level,
because every path past the try ran it. A rebinding in a sibling branch, or in
a nested block the consumer is not in, does not cut a definition off: the old
value may reach. Only a bytes read can be guarded: ``read_text`` and a
text-mode ``open`` have decoded before any helper runs, so the fix for one is a
bytes read, never a helper around its text. Declared limits: calls are not
followed into other functions (a local wrapper that decodes is not a guard --
inline the read or exempt it naming the wrapper), a read in a nested function
decoded by the outer one reports unguarded, and an ``open`` whose mode is not a
literal is enrolled as a text read.

Measured before re-keying: a window-only rule would have flipped five enrolled
sites that bind the read in a ``try`` and decode the name after the handler;
the dataflow rule keeps all five (and the sixth bound site, whose decode sits
two lines down) with no exemption added. The ledger row counts six flips
against the pre-exemption tree: the four byte copies it names now carry
``# bom-exempt:`` and report the same either way, leaving five. The builtin
``open`` joined the read spellings in the same change (it had no live site; a
maintainer's ``with open(settings_path) as fh`` was invisible), an ``open``
whose mode literal writes is not a read, and findings report in file order.

⚠ ``espalier/_vendor/cc/`` is skipped: it is a verbatim byte-mirror of
``tools/cc/``, so a finding there is a duplicate of its source, and the mirror is
pinned by its own parity test.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Helpers that make a read BOM-tolerant. A read is guarded when the bytes it
#: produced reach one of them -- the read call inside the helper's argument, or
#: the name its result is bound to consumed by the helper while that binding is
#: live (``_read_guard``). The helper's name elsewhere in the function is not
#: a guard (DEF-820), and ``test_every_bom_helper_is_a_decoder`` pins that every
#: name here is a real decoder -- a local wrapper is never appended to silence a red.
_BOM_HELPERS = ("decode_bom", "_ci_decode_bom", "load_json_dict_safe", "decode_text_or_problem")

#: A read whose target expression -- the handful of lines above it, or the name
#: of the function it sits in -- names a settings file or an operator-writable
#: record. Deliberately broad: over-collecting costs a one-line exemption, while
#: under-collecting is the failure this test exists to prevent.
_SETTINGS_HINT = re.compile(
    r"settings\.json|settings_path|settings_file|SETTINGS_REL"
    # The operator-writable records (DEF-797): the memory file, the goal
    # snapshot, the Stop gate's two relief flags -- by file name, by the
    # constants the hooks spell them with, and by the reader's own name.
    r"|ESPALIER_MEMORY|_MEMORY_FILENAME|memory_path"
    r"|GOAL\.md|goal_path"
    r"|DOCS_REFRESHED|CODE_REVIEWED|RELIEF_FLAGS|relief_record"
    # The banner's general reader (it reads the memory file among others) and
    # the working summary, the third hand-rewritten continuity doc.
    r"|safe_read|_working_summary",
    re.IGNORECASE,
)

#: The read spellings: ``p.read_text()``, ``p.read_bytes()``, ``p.open()``,
#: and the builtin ``open(p)`` -- minus an ``open`` whose mode literal writes.
_READ_CALLS = {"read_text", "read_bytes", "open"}

#: An ``open`` carrying any of these in its mode literal opens the file to
#: write it; nothing is decoded there, so it is not a read.
_OPEN_WRITE_MODES = "wax"


_EXEMPT_RE = re.compile(r"#\s*bom-exempt:\s*(?P<reason>\S.*)")

_SCAN_ROOTS = ("espalier", "tools/cc")
_SKIP_PARTS = {"_vendor", "__pycache__", "assets"}


def _iter_python_files():
    for root in _SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if _SKIP_PARTS & set(path.parts):
                continue
            yield path


def _enclosing_function(tree: ast.AST, lineno: int):
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = node.end_lineno or node.lineno
            if node.lineno <= lineno <= end:
                if best is None or node.lineno > best.lineno:
                    best = node
    return best


def _is_open_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Attribute) and func.attr == "open") or (
        isinstance(func, ast.Name) and func.id == "open"
    )


def _open_mode(call: ast.Call) -> str | None:
    """The mode literal of an ``open`` call: ``"r"`` when omitted, None when
    it is not a string constant. The builtin takes the mode second; ``Path.open``
    takes it first."""
    positional = 1 if isinstance(call.func, ast.Name) else 0
    node: ast.AST | None = call.args[positional] if len(call.args) > positional else None
    for kw in call.keywords:
        if kw.arg == "mode":
            node = kw.value
    if node is None:
        return "r"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_read_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in _READ_CALLS - {"open"}:
        return True
    if _is_open_call(node):
        mode = _open_mode(node)
        return mode is None or not any(ch in mode for ch in _OPEN_WRITE_MODES)
    return False


def _read_yields_bytes(call: ast.Call) -> bool:
    """Only bytes can be guarded downstream. ``read_text`` and a text-mode
    ``open`` have already decoded -- and on a UTF-16 file already raised --
    before any helper runs, so their results never count as reaching one:
    the fix for such a read is a bytes read, not a helper around its text."""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == "read_bytes":
        return True
    if _is_open_call(call):
        mode = _open_mode(call)
        return mode is not None and "b" in mode
    return False


def _is_bom_helper_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in _BOM_HELPERS
    return isinstance(func, ast.Attribute) and func.attr in _BOM_HELPERS


def _helper_arguments(call: ast.Call):
    yield from call.args
    for kw in call.keywords:
        yield kw.value


def _chain(expr: ast.AST):
    """The expression and everything its value is built from without passing
    through a call that is not a helper: an attribute, a subscript, a method
    call's receiver (``fh.read()`` yields the call then ``fh``), an ``await``,
    and every operand of ``or``/``and``, ``x if c else y`` and a binary
    operator. A positional argument is NOT on the chain -- ``json.loads(raw)``
    yields the call then ``json`` -- and calls are never followed into other
    functions. So a read whose bytes go through a local wrapper that itself
    calls a helper reports unguarded: inline the read into the wrapper, or
    exempt it naming the wrapper. Never append the wrapper to ``_BOM_HELPERS``
    (``test_every_bom_helper_is_a_decoder`` pins the roster)."""
    stack = [expr]
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.Attribute, ast.Subscript, ast.Await)):
            stack.append(node.value)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            stack.append(node.func.value)
        elif isinstance(node, ast.BoolOp):
            stack.extend(node.values)
        elif isinstance(node, ast.IfExp):
            stack.extend((node.body, node.orelse))
        elif isinstance(node, ast.BinOp):
            stack.extend((node.left, node.right))


def _target_names(target: ast.AST) -> set[str]:
    """The plain names a target binds. ``state.text = ...`` binds nothing
    here: the container is not the read's bytes."""
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_target_names(e) for e in target.elts)) if target.elts else set()
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return set()


def _param_names(args: ast.arguments) -> set[str]:
    names = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
    if args.vararg is not None:
        names.add(args.vararg.arg)
    if args.kwarg is not None:
        names.add(args.kwarg.arg)
    return names


_BLOCK_FIELDS = {"body", "orelse", "finalbody", "handlers", "cases"}
_TERMINAL = (ast.Return, ast.Raise, ast.Continue, ast.Break)
_TRY_TYPES = tuple(t for t in (getattr(ast, "Try", None), getattr(ast, "TryStar", None)) if t)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)


def _bindings_of(stmt: ast.stmt) -> list[tuple[set[str], ast.AST, int]]:
    """Each (names bound, the expression whose value they take, its line) a
    statement performs: an assignment to plain names, an annotated assignment,
    a with-item, and a walrus in the statement's own expressions (not in a
    nested block -- a walrus inside an ``if`` body belongs to that body's
    statement)."""
    out: list[tuple[set[str], ast.AST, int]] = []
    if isinstance(stmt, ast.Assign):
        names = set().union(*(_target_names(t) for t in stmt.targets))
        out.append((names, stmt.value, stmt.lineno))
    elif (
        isinstance(stmt, ast.AnnAssign)
        and stmt.value is not None
        and isinstance(stmt.target, ast.Name)
    ):
        out.append(({stmt.target.id}, stmt.value, stmt.lineno))
    elif isinstance(stmt, (ast.With, ast.AsyncWith)):
        for item in stmt.items:
            names: set[str] = set()
            if item.optional_vars is not None:
                names = _target_names(item.optional_vars)
            out.append((names, item.context_expr, stmt.lineno))
    for field, value in ast.iter_fields(stmt):
        if field in _BLOCK_FIELDS:
            continue
        for sub in (value if isinstance(value, list) else [value]):
            if not isinstance(sub, ast.AST):
                continue
            for node in ast.walk(sub):
                if isinstance(node, ast.NamedExpr):
                    out.append(({node.target.id}, node.value, node.lineno))
    return out


def _statement_index(scope: ast.AST) -> dict[int, tuple[int, int, ast.stmt | None]]:
    """For every statement under ``scope``: the block (statement list) it is a
    direct element of, its index there, and the statement that block belongs
    to (None for the scope's own body). A handler's or a case's body belongs
    to the ``try`` or ``match`` statement."""
    loc: dict[int, tuple[int, int, ast.stmt | None]] = {}

    def visit(owner: ast.AST, owner_stmt: ast.stmt | None) -> None:
        for _field, value in ast.iter_fields(owner):
            if isinstance(value, list):
                for i, sub in enumerate(value):
                    if isinstance(sub, ast.stmt):
                        loc[id(sub)] = (id(value), i, owner_stmt)
                        visit(sub, sub)
                    elif isinstance(sub, ast.AST) and not isinstance(sub, ast.expr):
                        visit(sub, owner_stmt)  # ExceptHandler, match_case
            elif isinstance(value, ast.AST) and not isinstance(value, ast.expr):
                visit(value, owner_stmt)

    visit(scope, None)
    return loc


def _runs_on_every_path_after(owner: ast.stmt, block_id: int) -> bool:
    """True when every path that reaches the code after ``owner`` ran this
    block's statements: a with-body; a try's ``finally``; a try's body and
    ``else`` when every handler ends by leaving (return, raise, continue,
    break) -- the tree's ``try: raw = path.read_bytes() / except OSError:
    return`` idiom. An ``if`` body, a loop body and a handler body are not."""
    if isinstance(owner, (ast.With, ast.AsyncWith)):
        return block_id == id(owner.body)
    if isinstance(owner, _TRY_TYPES):
        if block_id == id(owner.finalbody):
            return True
        if block_id in (id(owner.body), id(owner.orelse)):
            return all(h.body and isinstance(h.body[-1], _TERMINAL) for h in owner.handlers)
    return False


class _Scope:
    """One function's (or the module's) statements, their positions, and every
    way a name gets bound in it -- the fixed part of the reaching test."""

    def __init__(self, node: ast.AST) -> None:
        self.node = node
        self.parent_of: dict[int, ast.AST] = {}
        for parent in ast.walk(node):
            for child in ast.iter_child_nodes(parent):
                self.parent_of[id(child)] = parent
        self.loc = _statement_index(node)
        statements = [s for s in ast.walk(node) if isinstance(s, ast.stmt) and id(s) in self.loc]
        #: Bindings whose value is an expression: they carry taint and kill.
        self.binders: list[tuple[ast.stmt, set[str], ast.AST, int]] = []
        #: Every positional rebinding of a name, with the expression that
        #: still sees the old value (None when there is none).
        self.rebinders: list[tuple[ast.stmt, set[str], ast.AST | None, int]] = []
        #: Bindings visible only inside a region: a loop target, a comprehension
        #: target, a function's or lambda's parameters, ``except ... as``.
        self.scoped: list[tuple[ast.AST, set[str], int]] = []
        for stmt in statements:
            for names, value, line in _bindings_of(stmt):
                self.binders.append((stmt, names, value, line))
                self.rebinders.append((stmt, names, value, line))
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                names = {(a.asname or a.name).split(".")[0] for a in stmt.names}
                self.rebinders.append((stmt, names, None, stmt.lineno))
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.rebinders.append((stmt, {stmt.name}, None, stmt.lineno))
                if not isinstance(stmt, ast.ClassDef):
                    self.scoped.append((stmt, _param_names(stmt.args), stmt.lineno))
            elif isinstance(stmt, ast.Delete):
                names = set().union(*(_target_names(t) for t in stmt.targets))
                self.rebinders.append((stmt, names, None, stmt.lineno))
            elif isinstance(stmt, (ast.For, ast.AsyncFor)):
                self.scoped.append((stmt, _target_names(stmt.target), stmt.lineno))
            elif isinstance(stmt, _TRY_TYPES):
                for handler in stmt.handlers:
                    if handler.name:
                        self.scoped.append((handler, {handler.name}, handler.lineno))
        for sub in ast.walk(node):
            if isinstance(sub, ast.Lambda):
                self.scoped.append((sub, _param_names(sub.args), sub.lineno))
            elif isinstance(sub, _COMPREHENSIONS):
                names = set().union(*(_target_names(g.target) for g in sub.generators))
                self.scoped.append((sub, names, sub.lineno))

    def within(self, node: ast.AST, region: ast.AST) -> bool:
        cursor: ast.AST | None = node
        while cursor is not None and cursor is not self.node:
            if cursor is region:
                return True
            cursor = self.parent_of.get(id(cursor))
        return False

    def stmt_of(self, node: ast.AST) -> ast.stmt | None:
        cursor: ast.AST | None = node
        while cursor is not None and cursor is not self.node:
            if isinstance(cursor, ast.stmt) and id(cursor) in self.loc:
                return cursor
            cursor = self.parent_of.get(id(cursor))
        return None

    def chain(self, stmt: ast.stmt | None) -> dict[int, int]:
        """Block -> index, for the statement and each statement it sits in."""
        out: dict[int, int] = {}
        cursor = stmt
        while cursor is not None:
            block_id, idx, owner = self.loc[id(cursor)]
            out[block_id] = idx
            cursor = owner
        return out

    def effective(self, stmt: ast.stmt) -> tuple[int, int]:
        """A statement's position after climbing out of every block that runs
        on every path to the code after its owner, so a rebinding inside
        ``try: ... except: return`` counts as the try's own position."""
        block_id, idx, owner = self.loc[id(stmt)]
        while owner is not None and _runs_on_every_path_after(owner, block_id):
            block_id, idx, owner = self.loc[id(owner)]
        return block_id, idx

    def reaches(
        self, defn: tuple[str, ast.stmt, ast.AST, int], consumer: ast.AST
    ) -> bool:
        """Does the definition ``(name, statement, value, line)`` still hold
        ``name`` where ``consumer`` reads it? Yes unless the consumer comes
        first, sits inside the definition's own value, or is cut off by a
        rebinding of the name: one at the same or an enclosing level after
        the definition and before the consumer; one in the consumer's own
        block (or a block it sits in) at or before the consumer's position;
        or a scoped binding -- loop target, comprehension target, parameter,
        ``except ... as`` -- whose region holds the consumer but not the
        definition. A rebinding in a sibling branch, or in a nested block the
        consumer is not in, does not cut it off: the old value may reach."""
        name, d_stmt, d_value, d_line = defn
        if consumer.lineno < d_line or self.within(consumer, d_value):
            return False
        d_chain = self.chain(d_stmt)
        c_chain = self.chain(self.stmt_of(consumer))
        for r_stmt, names, r_value, r_line in self.rebinders:
            if name not in names or r_stmt is d_stmt or r_line <= d_line:
                continue
            if consumer.lineno < r_line or (r_value is not None and self.within(consumer, r_value)):
                continue
            block_id, idx = self.effective(r_stmt)
            if block_id in d_chain and idx > d_chain[block_id]:
                return False
            if block_id in c_chain and idx <= c_chain[block_id]:
                return False
        for region, names, r_line in self.scoped:
            if (
                name in names
                and r_line > d_line
                and self.within(consumer, region)
                and not self.within(d_stmt, region)
            ):
                return False
        return True


def _read_guard(read_call: ast.Call, scope_node: ast.AST) -> str | None:
    """How the bytes ``read_call`` produced reach a BOM helper within
    ``scope_node`` (the enclosing function, or the module for a top-level
    read): ``"nested"`` when the read call sits inside a helper's argument,
    ``"bound"`` when its result is bound to a name that a helper consumes
    while that binding still reaches the consumer (``_Scope.reaches``), None
    when they never do. Taint follows an alias, an attribute, a subscript, a
    method-call chain (``raw = fh.read()``, ``raw = raw.strip()``) and the
    operands ``_chain`` lists, never a positional argument to a non-helper.
    A text read is never guarded (``_read_yields_bytes``)."""
    if not _read_yields_bytes(read_call):
        return None
    for node in ast.walk(scope_node):
        if _is_bom_helper_call(node) and any(
            n is read_call for arg in _helper_arguments(node) for n in ast.walk(arg)
        ):
            return "nested"

    scope = _Scope(scope_node)
    defs: list[tuple[str, ast.stmt, ast.AST, int]] = []
    seen: set[tuple[str, int]] = set()

    def define(names: set[str], stmt: ast.stmt, value: ast.AST, line: int) -> bool:
        added = False
        for name in names:
            if (name, id(stmt)) not in seen:
                seen.add((name, id(stmt)))
                defs.append((name, stmt, value, line))
                added = True
        return added

    def reached_by_a_definition(node: ast.Name) -> bool:
        return isinstance(node.ctx, ast.Load) and any(
            d[0] == node.id and scope.reaches(d, node) for d in defs
        )

    for stmt, names, value, line in scope.binders:
        if any(n is read_call for n in _chain(value)):
            define(names, stmt, value, line)
    if not defs:
        return None

    changed = True
    while changed:
        changed = False
        for stmt, names, value, line in scope.binders:
            if any(isinstance(n, ast.Name) and reached_by_a_definition(n) for n in _chain(value)):
                if define(names, stmt, value, line):
                    changed = True

    for node in ast.walk(scope_node):
        if not _is_bom_helper_call(node):
            continue
        for arg in _helper_arguments(node):
            if any(isinstance(n, ast.Name) and reached_by_a_definition(n) for n in ast.walk(arg)):
                return "bound"
    return None


def _readers_in(text: str, rel: str) -> list[dict]:
    """Every settings- or record-shaped read in one module's source, with its
    guard status. Pure over the text so the census can be proven on a
    synthetic module; ``rel`` is the path the findings are reported under."""
    found: list[dict] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:  # pragma: no cover - a syntax error is another test's job
        return found
    lines = text.split("\n")
    for node in ast.walk(tree):
        if not _is_read_call(node):
            continue
        call_line = lines[node.lineno - 1]
        window = "\n".join(lines[max(0, node.lineno - 6):node.lineno + 2])
        fn = _enclosing_function(tree, node.lineno)
        # The read's own lines, or the name of the function it sits in: a
        # helper that reads ``root / STATE_DIR / flag`` names its file only
        # at its call sites (DEF-797).
        named = (
            _SETTINGS_HINT.search(call_line)
            or _SETTINGS_HINT.search(window)
            or (fn is not None and _SETTINGS_HINT.search(fn.name))
        )
        if not named:
            continue

        # The guard is the read's own: its bytes reach a helper (DEF-820). A
        # helper's name elsewhere in the function is not a guard.
        guard = _read_guard(node, fn if fn is not None else tree)
        # An exemption is looked for on the call line and the five lines
        # above it, so a reasoned block comment above the read counts.
        exempt_block = "\n".join(lines[max(0, node.lineno - 6):node.lineno])
        m = _EXEMPT_RE.search(call_line) or _EXEMPT_RE.search(exempt_block)
        found.append({
            "path": rel,
            "line": node.lineno,
            "function": fn.name if fn is not None else "<module>",
            "guarded": guard is not None,
            "guard": guard,
            "exempt_reason": (m.group("reason").strip() if m else None),
            "snippet": call_line.strip(),
        })
    # ``ast.walk`` is breadth-first, so a read nested inside a helper call
    # would otherwise report after a shallower read on a later line.
    found.sort(key=lambda r: r["line"])
    return found


def _settings_readers() -> list[dict]:
    """Every settings- or record-shaped read in the scanned tree, with its guard
    status."""
    found: list[dict] = []
    for path in _iter_python_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        found += _readers_in(text, str(path.relative_to(REPO_ROOT)).replace("\\", "/"))
    return found


class TestSettingsReadersDecodeBOM:
    def test_the_census_finds_readers_at_all(self):
        """Guard the instrument. A census that silently collects nothing would
        make every assertion below vacuously true -- the shape this repo keeps
        catching, and the reason this test exists at all."""
        readers = _settings_readers()
        assert len(readers) >= 10, (
            "the settings-reader census collected "
            f"{len(readers)} sites, which is implausibly few -- the detector has "
            "probably stopped matching (a rename? a new read idiom?). Fix the "
            "census before trusting anything else in this module."
        )
        # Both trees, not one: a narrowing that drops most of one tree passes
        # the total (measured 2026-09-16: 25 under espalier/, 9 under tools/cc/).
        engine = [r for r in readers if r["path"].startswith("espalier/")]
        hooks = [r for r in readers if r["path"].startswith("tools/cc/")]
        assert len(engine) >= 15 and len(hooks) >= 5, (
            f"the census sees {len(engine)} engine and {len(hooks)} tools/cc readers; "
            "one tree has mostly vanished from it -- a scan root or a hint narrowed."
        )

    def test_the_census_sees_the_operator_record_readers(self):
        """Guard the widening. The readers DEF-797 was filed on must be in the
        census, or the contract is blind to the sites it was widened for. The
        relief reader and the banner's general reader name their file only at
        their call sites, which is why the census reads function names (the
        failure-mode review of the widening found the banner reader fixed by
        hand and enrolled by nothing); the others are the goal snapshot's, the
        memory file's in the PostToolUse hook and the engine's prune verb, and
        the working summary's."""
        seen = {(r["path"], r["function"]) for r in _settings_readers()}
        for path, fn in (
            ("tools/cc/hooks/stop_gate.py", "_relief_record"),
            ("tools/cc/hooks/session_start.py", "_goal_section"),
            ("tools/cc/hooks/session_start.py", "_safe_read"),
            ("tools/cc/hooks/post_write_check.py", "_read_memory_text"),
            ("espalier/cli.py", "cmd_memory_prune"),
            ("tools/cc/read_summary.py", "main"),
        ):
            assert (path, fn) in seen, f"the census no longer sees {fn}() in {path}"

    def test_the_census_enrolls_a_reader_by_its_function_name(self):
        """Earn the red on the shape that hid the driven site: a helper whose
        callers name the record and whose own read window does not. The same
        body under a neutral name is NOT enrolled -- the arm keys on the name."""
        src = (
            "def _relief_record(root, flag):\n"
            "    path = root / STATE_DIR / flag\n"
            "    try:\n"
            "        raw = path.read_text(encoding='utf-8')\n"
            "    except OSError:\n"
            "        return None\n"
            "    return raw\n"
        )
        readers = _readers_in(src, "synthetic.py")
        assert [(r["function"], r["guarded"], r["exempt_reason"]) for r in readers] == [
            ("_relief_record", False, None)
        ]
        assert _readers_in(src.replace("_relief_record", "_read_flag"), "synthetic.py") == []

    def test_a_bom_helper_is_reachable_from_both_trees(self):
        """Both halves of the codebase must HAVE a helper to route through."""
        assert (REPO_ROOT / "espalier" / "surface_contract.py").is_file()
        assert (REPO_ROOT / "tools" / "cc" / "_json_safe.py").is_file()
        engine = (REPO_ROOT / "espalier" / "surface_contract.py").read_text(
            encoding="utf-8"
        )
        hookside = (REPO_ROOT / "tools" / "cc" / "_json_safe.py").read_text(
            encoding="utf-8"
        )
        assert "def decode_bom" in engine, "engine-side helper vanished"
        assert "def decode_bom" in hookside, "hook-side helper vanished"

    def test_every_bom_helper_is_a_decoder(self):
        """A name in ``_BOM_HELPERS`` greens every read whose bytes reach it,
        so appending a local wrapper's name to silence a red would green reads
        the wrapper never decodes. Each roster name must be defined under a
        scanned root, and every definition must name a byte-order mark or hand
        its bytes to another roster helper."""
        marks = ("utf-8-sig", "\\xef\\xbb\\xbf", "codecs.BOM", "BOM_UTF")
        for helper in _BOM_HELPERS:
            bodies: list[tuple[str, str]] = []
            for path in _iter_python_files():
                src = path.read_text(encoding="utf-8", errors="replace")
                try:
                    tree = ast.parse(src)
                except SyntaxError:  # pragma: no cover - another test's job
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name == helper:
                        bodies.append((str(path), ast.get_source_segment(src, node) or ""))
            assert bodies, f"{helper} is on the roster but defined nowhere under the scanned roots"
            others = [h for h in _BOM_HELPERS if h != helper]
            for where, body in bodies:
                assert any(m in body for m in marks) or any(f"{o}(" in body for o in others), (
                    f"{helper} in {where} neither names a byte-order mark nor hands its "
                    "bytes to another roster helper -- a roster entry must be a decoder"
                )

    def test_every_settings_reader_is_bom_tolerant_or_declared(self):
        offenders = [
            r for r in _settings_readers()
            if not r["guarded"] and not r["exempt_reason"]
        ]
        rendered = "\n".join(
            f"  {r['path']}:{r['line']} in {r['function']}()\n      {r['snippet']}"
            for r in offenders
        )
        assert not offenders, (
            f"{len(offenders)} reader(s) of a settings file or an operator-writable "
            "record decode neither through a BOM-tolerant helper nor under a "
            "declared exemption:\n"
            f"{rendered}\n\n"
            "A file a Windows adopter writes from PowerShell 5.1 (`>`, `Out-File`) "
            "is UTF-16LE by default, and editors add a UTF-8 BOM. Read BYTES and route "
            "them through `surface_contract.decode_bom` (engine) or `_json_safe.decode_bom` "
            "(tools/cc) -- a `read_text` or a text-mode `open` has already decoded, so a "
            "helper around its result is not a fix; for a `with open(...)` reader, open "
            "in 'rb' and decode `fh.read()`. If non-tolerance is deliberate, add "
            "`# bom-exempt: <why>` and say why, the way tools/cc/ci_guard.py does."
        )

    def test_every_exemption_states_a_reason(self):
        """`# bom-exempt:` with nothing after it is not a declaration."""
        thin = [
            r for r in _settings_readers()
            if r["exempt_reason"] is not None and len(r["exempt_reason"]) < 25
        ]
        assert not thin, (
            "these exemptions carry no usable reason -- an exemption whose "
            "justification is a word is how a suppression outlives the argument "
            f"for it: {[(r['path'], r['line'], r['exempt_reason']) for r in thin]}"
        )


class TestTheGuardKeysOnTheReadsOwnBytes:
    """The guard is a property of ONE read: the bytes it produced reach a BOM
    helper. It is not a property of the function the read sits in (DEF-820:
    the first census greened every read in a function that decoded one file
    through the helper, so a second strict read added beside a guarded one --
    the shape found by hand in ``cmd_memory_prune`` -- reported guarded).

    Rows are synthetic modules driven through ``_readers_in``; every read is
    enrolled by ``settings_path`` on its own call line, so the rows exercise
    the guard arm alone. The must-red rows were driven before the rule
    changed (2026-09-16): the first five were green under the shipped rule,
    and the nested-rebinding rows were green under the first dataflow cut,
    whose kill saw only a rebinding at the same or an enclosing level (both
    reviewers drove it: a rebinding one indent deeper -- inside an ``if``, a
    ``try``, a loop, the other branch -- kept the earlier strict definition
    alive for a decode it never reached). The must-stay-guarded rows are the
    legitimate shapes, eight of them on the live tree, including the six
    sites that bind the read and decode the name later, which a window-only
    census would have flipped."""

    @staticmethod
    def _status(src: str) -> list[tuple[str, bool]]:
        return [(r["function"], r["guarded"]) for r in _readers_in(src, "synthetic.py")]

    # -- must red: the helper's presence is not the read's guard ------------

    def test_a_second_strict_read_beside_a_guarded_one_is_unguarded(self):
        src = (
            "def _read_pair(settings_path):\n"
            "    existing = json.loads(decode_bom(settings_path.read_bytes()))\n"
            "    archive = settings_path.with_suffix('.bak').read_text(encoding='utf-8')\n"
            "    return existing, archive\n"
        )
        assert self._status(src) == [("_read_pair", True), ("_read_pair", False)]

    def test_a_same_name_rebinding_after_the_decode_is_unguarded(self):
        src = (
            "def _read_twice(settings_path):\n"
            "    raw = settings_path.read_bytes()\n"
            "    existing = json.loads(decode_bom(raw))\n"
            "    raw = settings_path.with_suffix('.bak').read_bytes()\n"
            "    return existing, json.loads(raw)\n"
        )
        assert self._status(src) == [("_read_twice", True), ("_read_twice", False)]

    def test_a_strict_first_read_is_not_guarded_by_a_later_rebindings_decode(self):
        src = (
            "def _read_twice(settings_path):\n"
            "    raw = settings_path.read_bytes()\n"
            "    first = json.loads(raw)\n"
            "    raw = settings_path.with_suffix('.bak').read_bytes()\n"
            "    second = json.loads(decode_bom(raw))\n"
            "    return first, second\n"
        )
        assert self._status(src) == [("_read_twice", False), ("_read_twice", True)]

    def test_a_helper_consuming_another_value_does_not_guard_the_read(self):
        src = (
            "def _read_settings(settings_path, other):\n"
            "    raw = settings_path.read_bytes()\n"
            "    text = decode_bom(other)\n"
            "    return json.loads(raw), text\n"
        )
        assert self._status(src) == [("_read_settings", False)]

    def test_a_helper_on_the_next_line_consuming_nothing_of_the_read(self):
        """The shipped rule also read the helper's name in the lines around
        the call; adjacency is not consumption."""
        src = (
            "def _read_settings(settings_path):\n"
            "    raw = settings_path.read_bytes()\n"
            "    empty = decode_bom(b'')\n"
            "    return json.loads(raw), empty\n"
        )
        assert self._status(src) == [("_read_settings", False)]

    # -- must red: a rebinding one indent deeper still cuts the old value off

    def test_a_rebinding_inside_an_if_decoded_inside_the_if_cuts_the_strict_read_off(self):
        """The decode consumes the rebound value: every path to it ran the
        rebinding. The earlier strict read is not what it decodes."""
        src = (
            "def _read_settings(settings_path, cond):\n"
            "    raw = settings_path.read_bytes()\n"
            "    data = json.loads(raw)\n"
            "    if cond:\n"
            "        raw = settings_path.with_suffix('.bak').read_bytes()\n"
            "        text = decode_bom(raw)\n"
            "    return data\n"
        )
        assert self._status(src) == [("_read_settings", False), ("_read_settings", True)]

    def test_a_rebinding_inside_a_loop_decoded_inside_the_loop_cuts_the_strict_read_off(self):
        src = (
            "def _read_settings(settings_path, others):\n"
            "    raw = settings_path.read_bytes()\n"
            "    data = json.loads(raw)\n"
            "    for settings_path in others:\n"
            "        raw = settings_path.read_bytes()\n"
            "        text = decode_bom(raw)\n"
            "    return data\n"
        )
        assert self._status(src) == [("_read_settings", False), ("_read_settings", True)]

    def test_a_decode_in_the_other_branch_does_not_guard_this_branchs_read(self):
        src = (
            "def _read_settings(settings_path, other, flag):\n"
            "    if flag:\n"
            "        raw = settings_path.read_bytes()\n"
            "        return json.loads(raw)\n"
            "    else:\n"
            "        raw = other.read_bytes()\n"
            "        return json.loads(decode_bom(raw))\n"
        )
        assert self._status(src) == [("_read_settings", False), ("_read_settings", True)]

    def test_a_rebinding_in_a_try_whose_handler_returns_cuts_the_strict_read_off(self):
        """The tree's own idiom. Every path to the decode ran the try body,
        because the only other way out of the try is the handler's return."""
        src = (
            "def _read_settings(settings_path):\n"
            "    raw = settings_path.read_bytes()\n"
            "    data = json.loads(raw)\n"
            "    try:\n"
            "        raw = settings_path.with_suffix('.bak').read_bytes()\n"
            "    except OSError:\n"
            "        return None\n"
            "    text = decode_bom(raw)\n"
            "    return data, text\n"
        )
        assert self._status(src) == [("_read_settings", False), ("_read_settings", True)]

    def test_a_loop_target_of_the_same_name_shadows_the_read_inside_the_loop(self):
        src = (
            "def _read_settings(settings_path, chunks):\n"
            "    raw = settings_path.read_bytes()\n"
            "    data = json.loads(raw)\n"
            "    for raw in chunks:\n"
            "        text = decode_bom(raw)\n"
            "    return data\n"
        )
        assert self._status(src) == [("_read_settings", False)]

    def test_a_comprehension_target_of_the_same_name_shadows_the_read(self):
        src = (
            "def _read_settings(settings_path, chunks):\n"
            "    raw = settings_path.read_bytes()\n"
            "    texts = [decode_bom(raw) for raw in chunks]\n"
            "    return json.loads(raw), texts\n"
        )
        assert self._status(src) == [("_read_settings", False)]

    def test_a_nested_functions_parameter_of_the_same_name_shadows_the_read(self):
        src = (
            "def _read_settings(settings_path):\n"
            "    raw = settings_path.read_bytes()\n"
            "    def parse(raw):\n"
            "        return json.loads(decode_bom(raw))\n"
            "    return json.loads(raw)\n"
        )
        assert self._status(src) == [("_read_settings", False)]

    def test_a_module_level_read_is_not_guarded_by_a_functions_parameter(self):
        src = (
            "RAW = SETTINGS_PATH.read_bytes()\n"
            "\n"
            "\n"
            "def parse(RAW):\n"
            "    return json.loads(decode_bom(RAW))\n"
        )
        # Enrolled by the constant's name, which the hint reads case-insensitively.
        assert self._status(src) == [("<module>", False)]

    def test_an_attribute_target_does_not_taint_its_container(self):
        src = (
            "def _read_settings(settings_path, state):\n"
            "    state.text = settings_path.read_bytes()\n"
            "    return decode_bom(state.other)\n"
        )
        assert self._status(src) == [("_read_settings", False)]

    def test_a_text_read_is_never_guarded_by_a_helper_downstream(self):
        """``read_text`` has decoded -- and on a UTF-16 file raised -- before
        any helper runs. The fix is a bytes read, and the census says so
        rather than greening a helper wrapped around text."""
        bound = (
            "def _read_settings(settings_path):\n"
            "    raw = settings_path.read_text(encoding='utf-8')\n"
            "    return json.loads(decode_bom(raw))\n"
        )
        nested = (
            "def _read_settings(settings_path):\n"
            "    return json.loads(decode_bom(settings_path.read_text(encoding='utf-8')))\n"
        )
        assert self._status(bound) == [("_read_settings", False)]
        assert self._status(nested) == [("_read_settings", False)]

    def test_a_builtin_open_is_a_read_the_census_sees(self):
        """``with open(settings_path) as fh`` is the same strict read spelled
        through the builtin; the first census enrolled only the attribute
        spellings (``read_text``, ``read_bytes``, ``Path.open``)."""
        src = (
            "def _read_settings(settings_path):\n"
            "    with open(settings_path, encoding='utf-8') as fh:\n"
            "        return json.load(fh)\n"
        )
        assert self._status(src) == [("_read_settings", False)]

    def test_an_open_that_writes_is_not_a_read(self):
        """A settings writer decodes nothing; enrolling it would make the
        honest response an exemption, and the exemption bucket is where a
        contract stops being read."""
        builtin = (
            "def _write_settings(settings_path, payload):\n"
            "    with open(settings_path, 'w', encoding='utf-8') as fh:\n"
            "        json.dump(payload, fh)\n"
        )
        method = (
            "def _write_settings(settings_path, payload):\n"
            "    with settings_path.open(mode='a') as fh:\n"
            "        fh.write(payload)\n"
        )
        assert self._status(builtin) == []
        assert self._status(method) == []

    # -- must stay guarded: every legitimate shape ----------------------------

    def test_direct_nesting_in_the_helper_is_guarded(self):
        src = (
            "def _read_settings(settings_path):\n"
            "    return json.loads(decode_bom(settings_path.read_bytes()))\n"
        )
        assert self._status(src) == [("_read_settings", True)]

    def test_a_bound_read_unpacked_from_the_helper_is_guarded(self):
        """Binds first, then unpacks the helper's pair -- the bound route
        through a tuple target, not a duplicate of direct nesting."""
        src = (
            "def _read_settings(settings_path):\n"
            "    raw = settings_path.read_bytes()\n"
            "    text, problem = decode_text_or_problem(raw)\n"
            "    return text, problem\n"
        )
        assert self._status(src) == [("_read_settings", True)]

    def test_a_read_bound_in_a_try_and_decoded_after_the_handler_is_guarded(self):
        """The live sites the shape decision was measured on."""
        src = (
            "def _read_settings(settings_path):\n"
            "    try:\n"
            "        raw = settings_path.read_bytes()\n"
            "    except OSError:\n"
            "        return None\n"
            "    return json.loads(decode_bom(raw))\n"
        )
        assert self._status(src) == [("_read_settings", True)]

    def test_two_reads_in_sibling_branches_decoded_once_are_both_guarded(self):
        """A rebinding in a sibling branch never ran on the path that took
        this branch, so it does not cut this read's definition off."""
        src = (
            "def _read_settings(settings_path, fallback):\n"
            "    if settings_path.is_file():\n"
            "        raw = settings_path.read_bytes()\n"
            "    else:\n"
            "        raw = fallback.read_bytes()\n"
            "    return json.loads(decode_bom(raw))\n"
        )
        assert self._status(src) == [("_read_settings", True), ("_read_settings", True)]

    def test_a_conditional_rebinding_does_not_end_the_first_reads_definition(self):
        src = (
            "def _read_settings(settings_path, override):\n"
            "    raw = settings_path.read_bytes()\n"
            "    if override is not None:\n"
            "        raw = override.read_bytes()\n"
            "    return json.loads(decode_bom(raw))\n"
        )
        assert self._status(src) == [("_read_settings", True), ("_read_settings", True)]

    def test_a_rebinding_in_a_try_whose_handler_falls_through_keeps_the_first_read_alive(self):
        """When the second read fails the handler continues, so the decode
        after the try may receive the first read's bytes: both are guarded."""
        src = (
            "def _read_settings(settings_path, fallback):\n"
            "    raw = settings_path.read_bytes()\n"
            "    try:\n"
            "        raw = fallback.read_bytes()\n"
            "    except OSError:\n"
            "        pass\n"
            "    return json.loads(decode_bom(raw))\n"
        )
        assert self._status(src) == [("_read_settings", True), ("_read_settings", True)]

    def test_a_handle_read_through_a_with_item_is_guarded(self):
        src = (
            "def _read_settings(settings_path):\n"
            "    with settings_path.open('rb') as fh:\n"
            "        raw = fh.read()\n"
            "    return json.loads(decode_bom(raw))\n"
        )
        assert self._status(src) == [("_read_settings", True)]

    def test_a_builtin_open_handle_decoded_through_the_helper_is_guarded(self):
        src = (
            "def _read_settings(settings_path):\n"
            "    with open(settings_path, 'rb') as fh:\n"
            "        raw = fh.read()\n"
            "    return json.loads(decode_bom(raw))\n"
        )
        assert self._status(src) == [("_read_settings", True)]

    def test_a_read_in_a_loop_body_is_guarded(self):
        src = (
            "def _read_all(paths):\n"
            "    out = []\n"
            "    for settings_path in paths:\n"
            "        raw = settings_path.read_bytes()\n"
            "        out.append(json.loads(decode_bom(raw)))\n"
            "    return out\n"
        )
        assert self._status(src) == [("_read_all", True)]

    def test_a_method_chain_on_the_read_is_guarded(self):
        src = (
            "def _read_settings(settings_path):\n"
            "    raw = settings_path.read_bytes().lstrip(b'\\xef\\xbb\\xbf')\n"
            "    return json.loads(decode_bom(raw))\n"
        )
        assert self._status(src) == [("_read_settings", True)]

    def test_a_read_behind_an_or_default_is_guarded(self):
        src = (
            "def _read_settings(settings_path):\n"
            "    raw = settings_path.read_bytes() or b'{}'\n"
            "    return json.loads(decode_bom(raw))\n"
        )
        assert self._status(src) == [("_read_settings", True)]

    def test_a_keyword_argument_to_the_helper_is_guarded(self):
        src = (
            "def _read_settings(settings_path):\n"
            "    raw = settings_path.read_bytes()\n"
            "    return json.loads(decode_bom(raw=raw))\n"
        )
        assert self._status(src) == [("_read_settings", True)]

    def test_the_bound_then_decoded_sites_on_the_live_tree_stay_guarded(self):
        """The population the shape decision was measured on, derived rather
        than listed: every enrolled site whose read is bound to a name and
        decoded later (``guard == "bound"``). Measured 2026-09-16: six -- five
        bind inside a ``try`` and decode after the handler, one decodes two
        lines down. Under a window-only rule five flipped; under the dataflow
        rule every one stays guarded and none needs an exemption. A site that
        leaves this set by being refactored to nest its read is fine; one
        that leaves it by losing its guard is caught by the offender test."""
        readers = _settings_readers()
        bound = [r for r in readers if r["guard"] == "bound"]
        rendered = "\n".join(f"  {r['path']}:{r['line']} in {r['function']}()" for r in bound)
        assert len(bound) >= 6, (
            "the census sees fewer bound-then-decoded readers than the tree "
            f"held when the rule was re-keyed (six):\n{rendered}\n"
            "either a site was refactored (fine -- update the floor with the "
            "date) or the bound route stopped reaching (not fine -- fix the rule)."
        )
        exempted = [r for r in bound if r["exempt_reason"]]
        assert not exempted, (
            "a bound-then-decoded reader carries an exemption it does not need: "
            f"{[(r['path'], r['line']) for r in exempted]}"
        )
