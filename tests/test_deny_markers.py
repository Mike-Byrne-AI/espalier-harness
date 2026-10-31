"""Contract test: every hook deny phrase is recognised by the e2e
bench parser.

Pins the bridge between hook authoring and the end-to-end bench
parser. The TP-13 bench asserts on receiver-side behavior — does
the agent see and act on hook deny reasons?
``Transcript.deny_reason_received()`` matches against
``_DENY_REASON_MARKERS`` (a hand-curated tuple in
``bench/end_to_end/transcript.py``). When a hook adds a new deny
phrase that tuple must be updated, otherwise BCE-001 returns "no
deny reason found" and the scenario FAILs with a misleading
"friction layer is not teaching" — a silent false negative where
the hook is actually working but the parser doesn't recognise it.

This test scans the ``deny()`` and ``block()`` call sites in
``tools/cc/hooks/*.py`` for literal-string reason fragments and
asserts each is covered (substring match, either direction) by at
least one entry in ``_DENY_REASON_MARKERS``. New phrases either
need a marker added or an explicit ``_EXEMPT`` opt-out below.
Without this guard, every new deny phrase ships with a broken bench
signal that hides whether the hook is actually communicating to the
agent at all.

Pure AST + repo read; no subprocess, no network.
"""
from __future__ import annotations

import ast
import re
import sys
import warnings
from pathlib import Path

import pytest
from tests._live_tree import checkout_glob

# bench/end_to_end/ is dev tooling and is intentionally NOT included in
# the sdist (per MANIFEST.in). Skip this contract test when bench/end_to_end
# isn't present — it has nothing to verify in that environment.
REPO_ROOT = Path(__file__).resolve().parent.parent
if not (REPO_ROOT / "bench" / "end_to_end" / "__init__.py").is_file():
    pytest.skip(
        "bench/end_to_end/ is dev tooling not shipped in sdist; "
        "this contract test applies only to source-checkout / source-archive runs.",
        allow_module_level=True,
    )

from bench.end_to_end.transcript import _DENY_REASON_MARKERS  # noqa: E402
from _site_path import SitePath, nodes_flowing_past, preorder, site_path  # noqa: E402

HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"

# Functions whose `reason` argument reaches the agent. `deny()`/`block()` are
# the PreToolUse and Stop/ConfigChange shapes; `_audit_deny()` is the audited
# funnel that 15 protected-zone denials route through and that this contract
# walked ZERO of until it was widened; `_audit_block()` is the Stop hook's
# twin of it (record, then `block`), which every gate block routes through.
#
# The ARGUMENT POSITION is derived from each funnel's own signature (the
# parameter literally named ``reason``), never hand-written: `_audit_deny`
# and `_audit_block` take it third, `deny` first, and a hand-kept index is a
# declaration that goes stale the moment a signature is reordered — with the
# walk silently reading the wrong argument and finding nothing.
_FUNNEL_NAMES = frozenset({"deny", "block", "_audit_deny", "_audit_block"})

# Reason fragments that intentionally don't need a marker — typically
# very generic phrases that overlap with too many false-positive lines.
# Keep this list small and document each entry.
_EXEMPT_FRAGMENTS: tuple[str, ...] = (
    # The two platform remedies the stop gate interpolates into ONE reason,
    # `GATE_COMMAND_SPAWN_FAILED`, whose head ("Stop blocked once")
    # carries the marker. Neither reaches an agent on its own, so a marker
    # for either would be a marker for half a sentence.
    "which only a shell finds",
    "Name a program that is on PATH",
)

# Declared constants that are FRAGMENTS composed into another reason, never a
# standalone denial. They reach the agent only as part of a larger text that is
# itself covered, so requiring a marker for the fragment alone would force a
# marker matching half a sentence. `test_composed_fragments_are_still_composed`
# reds if one stops being appended to something.
# Empty from DEF-608 (the last fragment, GATE_CODE_REVIEW_FLAG_WRITE_FAILED_SUFFIX,
# retired with the stop_gate self-write it decorated) until 2026-10-07, when
# the recursive-delete wall texts gained two shared phrases, each composed into
# several reasons inside `_denial_reasons.py` itself.
_NOT_STANDALONE_REASONS: dict[str, str] = {
    "_NOT_REFUSED_HERE": "the what-is-not-refused clause of the seven recursive-delete wall texts",
    "_PS_CATASTROPHIC_TARGETS": "the PowerShell wall's target list, in its two wall texts and the forced remedy",
    "_SHALLOW_SYSTEM_PATHS": "the shallow-system-path clause, drive rule included, of both tools' meaning-judge wall texts",
    # DEF-910: the name-collision remedy, composed into every harness-zone
    # template, whose head carries the "protected harness" marker.
    "_NAME_COLLISION_WRITE": "the relocate remedy of the harness-zone write, symlink and hardlink templates",
    "_NAME_COLLISION_MUTATION": "the relocate remedy of the harness-zone delete and move templates",
    # The kill-switch deny's {ci_clause}, chosen by `kill_switch_ci_clause` on
    # whether the CI gate's files are present; the deny's head carries the marker.
    "KILL_SWITCH_CI_GATE_PRESENT": "the kill-switch deny's CI clause where the CI gate is installed",
    "KILL_SWITCH_CI_GATE_ABSENT": "the kill-switch deny's CI clause where no CI gate is installed",
    # The stop gate's per-source Don't and Do lines, interpolated into
    # GATE_COMMAND_SPAWN_FAILED (head "Stop blocked once") and the timeout's
    # Do line into GATE_COMMAND_TIMEOUT (head "Gate 1 ("); the shell-syntax
    # remedy rides the spawn-failed reason as its platform siblings do.
    "GATE_COMMAND_DO_ENV": "the Do line of the spawn-failed reason for the override",
    "GATE_COMMAND_DO_TOML": "the Do line of the spawn-failed reason for the declared command",
    "GATE_COMMAND_DO_FINGERPRINT": "the Do line of the spawn-failed reason for the detected command",
    "GATE_COMMAND_DONT_ENV": "the Don't line of the spawn-failed reason for the override",
    "GATE_COMMAND_DONT_TOML": "the Don't line of the spawn-failed reason for the declared command",
    "GATE_COMMAND_DONT_FINGERPRINT": "the Don't line of the spawn-failed reason for the detected command",
    "GATE_COMMAND_TIMEOUT_DO_ENV": "the Do line of the timeout reason for the override",
    "GATE_COMMAND_TIMEOUT_DO_TOML": "the Do line of the timeout reason for the declared command",
    "GATE_COMMAND_TIMEOUT_DO_FINGERPRINT": "the Do line of the timeout reason for the detected command",
    "GATE_COMMAND_SPAWN_REMEDY_SHELL_SYNTAX": "the shell-syntax remedy, interpolated into the spawn-failed reason",
}


def _resolve_text(node: ast.AST, local: dict[str, str]) -> str | None:
    """Best-effort static resolution of an AST node to its string value.

    Handles the shapes hook authors actually write. The two that used to be
    missing are the ones that mattered:

    * ``ast.JoinedStr`` — an implicit concatenation containing an f-string
      segment parses as a JoinedStr, not a Constant. A Constant-only lookup
      silently returned None for FOUR live reason templates, including the
      flagship protected-zone denial.
    * ``ast.Name`` — a local variable. Six call sites pass ``deny(reason)``
      after building ``reason`` above; a walk that only reads literals drops
      every one of them without a word.

    Formatted segments collapse to ``{...}`` because a marker must match the
    LITERAL parts of a rendered reason; the interpolated parts vary per call.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        return "".join(_resolve_text(v, local) or "{...}" for v in node.values)
    if isinstance(node, ast.FormattedValue):
        return "{...}"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve_text(node.left, local)
        right = _resolve_text(node.right, local)
        return (left or "") + (right or "") if (left or right) else None
    if isinstance(node, ast.BoolOp):
        # ``entry.message or _denial_reasons.format_x(...)`` — either branch can
        # reach the agent, so resolve to whichever is statically knowable.
        for v in node.values:
            got = _resolve_text(v, local)
            if got:
                return got
        return None
    if isinstance(node, ast.Name):
        return local.get(node.id)
    if isinstance(node, ast.Attribute):
        return _DECLARED_REASONS().get(node.attr) or local.get(node.attr)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "format":
            return _resolve_text(node.func.value, local)
    return None


def _dotted(node: ast.AST) -> str | None:
    """``_denial_reasons.format_dangerous_bash`` -> that dotted string.

    For ``entry.message or _denial_reasons.format_x(...)`` the CALL branch is
    the producer worth naming: ``entry.message`` is runtime data carried on a
    registry row, while the call names a template this contract can then cover
    on the site's behalf. Preferring the call is why the exemption key stays
    meaningful instead of degrading to a generic attribute name.
    """
    if isinstance(node, ast.BoolOp):
        for v in node.values:                      # calls first
            if isinstance(v, ast.Call):
                got = _dotted(v)
                if got:
                    return got
        for v in node.values:
            got = _dotted(v)
            if got:
                return got
        return None
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            # a same-module producer (`reason = _bash_dangerous_reason(...)`):
            # its bare name is the symbol; a bare NAME that is not a call is
            # left to `_producer_of`'s alias hop, so `x = y; deny(x)` still
            # follows `y` to its own assignment
            return node.func.id
        return _dotted(node.func)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return None


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = <str>`` bindings, resolved."""
    out: dict[str, str] = {}
    for node in tree.body:
        targets = (
            [node.target] if isinstance(node, ast.AnnAssign)
            else node.targets if isinstance(node, ast.Assign)
            else []
        )
        for target in targets:
            if isinstance(target, ast.Name):
                value = _resolve_text(node.value, {})
                if value is not None:
                    out[target.id] = value
    return out


_DECLARED_CACHE: dict[str, str] | None = None


def _reason_modules() -> list[Path]:
    """The hook modules that declare reason templates, by their own
    declaration of an operator-facing registry (``_OPERATOR_FACING_TEMPLATES``):
    the shared module and the start refusal's, which every deny hook imports
    first (DEF-3008). Derived as the portability contract's rule (e) is, so a
    third declares itself in."""
    return sorted(p for p in checkout_glob(HOOKS_DIR, "_*.py")
                  if "_OPERATOR_FACING_TEMPLATES" in p.read_text(encoding="utf-8"))


def _DECLARED_REASONS() -> dict[str, str]:
    """Every module-level string constant declared in :func:`_reason_modules`.

    This is the SECOND, independent derivation. The call-site walk below finds
    what is passed to a funnel; this finds what is declared as a reason. They
    catch different things and neither is complete alone — measured: one live
    reason reaches the agent through a rule table and is invisible to the walk,
    while another is built at a call site and is invisible here.
    """
    global _DECLARED_CACHE
    if _DECLARED_CACHE is None:
        _DECLARED_CACHE = {}
        for path in _reason_modules():
            _DECLARED_CACHE.update(_module_constants(ast.parse(path.read_text(encoding="utf-8"))))
    return _DECLARED_CACHE


def _reason_arg_index(tree: ast.Module) -> dict[str, int]:
    """Position of the ``reason`` parameter in each funnel defined here.

    Derived from the signature, never declared. ``_audit_deny(root,
    event_type, reason, **details)`` and its Stop-hook twin ``_audit_block``
    take it third; ``deny(reason)`` first.
    """
    out: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in _FUNNEL_NAMES:
            for i, arg in enumerate(node.args.args):
                if arg.arg == "reason":
                    out[node.name] = i
    return out


def _collect_deny_sites() -> tuple[list[tuple[Path, int, str]], list[tuple[Path, int, str]]]:
    """Return ``(resolved, unresolved)`` reason sites across every hook.

    Every module is walked, including ``_``-prefixed ones: the speed-bump
    reason lives in ``_speedbump.py`` and the old walk skipped that whole file.
    A funnel's OWN body is skipped, because ``return deny(reason)`` inside
    ``_audit_deny`` forwards its caller's reason rather than declaring one.

    Each site's reason is read from the assignments that reach it on its own
    path (``tests/_site_path.py``; DEF-834): one map built over the whole
    function, the walk's last assignment winning, read one arm's text twice
    and the other arm's never. A site can carry several texts (two binding
    arms falling through to one deny), each its own ``resolved`` row; a
    binding this walk cannot read is an ``unresolved`` row beside them, so a
    partially readable site still reds by name rather than vanishing.
    """
    resolved: list[tuple[Path, int, str]] = []
    unresolved: list[tuple[Path, int, str]] = []
    # Funnel signatures may be defined in any hook; collect them all first.
    arg_index: dict[str, int] = {"deny": 0, "block": 0}
    trees: dict[Path, ast.Module] = {}
    for hook in sorted(checkout_glob(HOOKS_DIR, "*.py")):
        trees[hook] = ast.parse(hook.read_text(encoding="utf-8"))
        arg_index.update(_reason_arg_index(trees[hook]))

    for hook, tree in trees.items():
        module_consts = _module_constants(tree)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name in _FUNNEL_NAMES:
                continue  # the funnel forwarding its caller's reason
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                name = (
                    node.func.id if isinstance(node.func, ast.Name)
                    else getattr(node.func, "attr", None)
                )
                if name not in _FUNNEL_NAMES:
                    continue
                idx = arg_index.get(name, 0)
                if len(node.args) <= idx:
                    continue
                arg = node.args[idx]
                try:
                    assigns = _assignments_on(site_path(fn, node))
                except ValueError:
                    unresolved.append((hook, node.lineno, "<not under the function body>"))
                    continue
                texts, unread = _reaching(arg, assigns, module_consts)
                resolved.extend((hook, node.lineno, text) for text in texts)
                if texts and not unread:
                    continue
                # Unresolvable: record the PRODUCER so the exemption can be
                # keyed on a stable symbol instead of a line number.
                if unread:
                    for value in unread:
                        producer = _dotted(value) or (
                            _producer_of(assigns, value) if isinstance(value, ast.Name) else None
                        )
                        unresolved.append((hook, node.lineno, producer or "<unknown>"))
                    continue
                producer = _dotted(arg) or _producer_of(assigns, arg)
                unresolved.append((hook, node.lineno, producer or "<unknown>"))
    return resolved, unresolved


def _assignments_on(path: SitePath) -> list[tuple[ast.Assign, bool]]:
    """The assignments that run before the site, in execution order, each
    with whether it is straight-line -- a statement of a block on the way,
    which supersedes an earlier binding of its name -- or nested in a
    preceding compound statement (a branch, a loop, a ``with``): a further
    candidate, because the rule is block-prefix, not control flow, and
    whether that branch ran is not asked. The site's own statement comes
    last, straight-line (``rc = deny(reason)`` binds nothing the deny reads).
    Source order within a statement is the helper's (``nodes_flowing_past``
    and ``preorder`` walk in field order, pinned in ``tests/test_site_path.py``),
    so ``base = 'x'`` is bound before ``reason = base + '...'`` reads it."""
    out: list[tuple[ast.Assign, bool]] = []
    for stmt in path.before:
        if isinstance(stmt, ast.Assign):
            out.append((stmt, True))
            continue
        out.extend((n, False) for n in nodes_flowing_past(stmt) if isinstance(n, ast.Assign))
    out.extend((n, True) for n in preorder(path.site) if isinstance(n, ast.Assign))
    return out


def _reaching(
    arg: ast.AST, assigns: list[tuple[ast.Assign, bool]], module_consts: dict[str, str]
) -> tuple[list[str], list[ast.AST]]:
    """``(texts, unread)`` for the reason ``arg`` at its site: every text it
    can carry, and every reaching binding this walk could not read (the
    value node, for the producer lookup). A bare name reads its candidates:
    a straight-line assignment replaces them, one nested in a preceding
    branch is added. Any other argument shape (a literal, an f-string, a
    declared constant, a ``+``) resolves against the nearest binding of
    each name it mentions, as before."""
    local: dict[str, str] = dict(module_consts)
    cands: dict[str, list[str | ast.AST]] = {}
    for node, straight in assigns:
        value = _resolve_text(node.value, local)
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            entry: str | ast.AST = value if value is not None else node.value
            if value is not None:
                local[target.id] = value
            else:
                local.pop(target.id, None)
            if straight:
                cands[target.id] = [entry]
            else:
                have = cands.setdefault(target.id, [])
                seen = {c if isinstance(c, str) else ast.dump(c) for c in have}
                if (entry if isinstance(entry, str) else ast.dump(entry)) not in seen:
                    have.append(entry)
    if isinstance(arg, ast.Name) and arg.id in cands:
        texts = [c for c in cands[arg.id] if isinstance(c, str)]
        unread = [c for c in cands[arg.id] if not isinstance(c, str)]
        return texts, unread
    text = _resolve_text(arg, local)
    return ([text] if text else []), []


def _producer_of(assigns: list[tuple[ast.Assign, bool]], arg: ast.AST, _hops: int = 0) -> str | None:
    """For ``x = <call>; deny(x)``, the dotted name of that call, read from
    the assignments that reach the site, nearest first (DEF-834: the first
    assignment anywhere in the function named one arm's producer for both).

    Also follows a tuple unpack and a name alias, each once: for
    ``pair = <call>; _id, x = pair; deny(x)`` the producer is still ``<call>``
    (the speed-bump site reads its reason out of the ``(id, reason)`` pair
    ``check_fired`` returns so the id can feed the audit record). Bounded so a
    self-referential assignment cannot loop.
    """
    if not isinstance(arg, ast.Name) or _hops > 2:
        return None
    for node, _straight in reversed(assigns):
        for target in node.targets:
            names = (
                [target] if isinstance(target, ast.Name)
                else [e for e in target.elts if isinstance(e, ast.Name)]
                if isinstance(target, ast.Tuple) else []
            )
            if not any(n.id == arg.id for n in names):
                continue
            got = _dotted(node.value)
            if got:
                return got
            if isinstance(node.value, ast.Name) and node.value.id != arg.id:
                return _producer_of(assigns, node.value, _hops + 1)
    return None


# -- Runtime reason producers, derived from the producer's own body (DEF-750) --
#
# A site whose reason is produced at RUNTIME by a function
# (``reason = _zone_reason(...); deny(reason)``) is unreadable to the static
# walk above, which records the PRODUCER's symbol instead (`_dotted`,
# `_producer_of`). Until DEF-750 a hand-kept dict mapped each producer name to
# the one template it rendered. Keyed by name, so a rename or a split of a
# producer re-keyed it and redded the tier on a name that had moved, and the
# maintainer's only repair was editing the map, again on the next rename.
# Measured at the change: two of its four entries named DICTS
# (`DANGEROUS_BASH_PLAIN`, `DANGEROUS_PS_PLAIN`, the fallback's ``{what}``),
# which no string lookup finds, so they covered nothing; the zone entry named
# one of the seven templates `_zone_reason` renders; only the speed-bump entry
# added a text no other path covers. The templates are now read out of the
# producer's own return flow, so a new, renamed or split producer is covered
# with no edit here, and one that renders no declared template reds by name.

_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _tree_of(path: Path, trees: dict[Path, ast.Module]) -> ast.Module:
    if path not in trees:
        trees[path] = ast.parse(path.read_text(encoding="utf-8"))
    return trees[path]


def _module_function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The module-level function ``name`` of ``tree``, or None."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _own_nodes(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    """Every node of ``fn``'s body, not descending into a nested def, lambda
    or class: a return there is another function's."""
    out: list[ast.AST] = []
    stack: list[ast.AST] = [n for n in fn.body if not isinstance(n, _NESTED_SCOPES)]
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(c for c in ast.iter_child_nodes(node) if not isinstance(c, _NESTED_SCOPES))
    return out


def _producer_function(
    hook: Path, producer: str, trees: dict[Path, ast.Module]
) -> tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef] | None:
    """``(module path, function)`` for a producer symbol as `_dotted` and
    `_producer_of` name it -- a bare name is a function of the denying hook's
    own module, ``module.func`` one of ``HOOKS_DIR / module.py`` -- or None
    when no module-level function of that name is there to read (the
    ``<unknown>`` and ``<not under the function body>`` rows included)."""
    module, _, name = producer.rpartition(".")
    path = HOOKS_DIR / f"{module}.py" if module else hook
    if not path.is_file():
        return None
    fn = _module_function(_tree_of(path, trees), name)
    return None if fn is None else (path, fn)


def _producer_templates(
    hook: Path, producer: str, trees: dict[Path, ast.Module] | None = None
) -> dict[str, str] | None:
    """The declared templates a runtime producer renders, as
    ``{"module.NAME": text}``; None when the producer is no function this walk
    can read (`test_no_deny_site_is_silently_unreadable` names that site).

    Reads the producer's RETURN FLOW. A returned expression is followed through
    ``X.format(...)`` (to ``X``), ``a or b``, ``a if c else b``, a tuple
    (``check_fired`` returns ``(id, reason)``), ``a + b``, a local name (to
    every value the function binds to it), and a call to a module-level
    function -- same-module by bare name, or ``mod.func`` of a hook module --
    whose own return flow is read in turn. It collects module-level string
    constants: a bare name of the module being read (``_REASON_TEMPLATE`` in
    ``_speedbump.py``), or ``mod.NAME`` of a hook module
    (``_denial_reasons.CATASTROPHIC_RM``).

    Not every name the body mentions: a body walk reaches ``_flag_name`` from
    ``check_fired`` and collects ``_FLAG_PREFIX = "speedbump_"``, a state-file
    prefix that reaches no agent, and ``_zone_hint`` from ``_zone_reason``,
    whose text is a ``{hint}`` interpolated into the template. Format
    ARGUMENTS are fragments for the same reason, so a dict such as
    ``DANGEROUS_BASH_PLAIN`` (the fallback's ``{what}``) is never collected:
    the fallback template that carries it is. A returned literal is not a
    declared template and is not collected either; a producer that renders
    only literals reds in
    `test_every_runtime_producer_renders_a_declared_template`.

    Terminates on the visited set (each function is read once, so the
    cross-shell recursion, Bash tier to PowerShell tier and back, stops where
    it closes). There is no hop cap: with the visited set it could only drop a
    template silently. The deepest chain today is four calls
    (``_bash_dangerous_reason`` to ``format_dangerous_ps``).
    """
    trees = {} if trees is None else trees
    start = _producer_function(hook, producer, trees)
    if start is None:
        return None
    found: dict[str, str] = {}
    visited: set[tuple[Path, str]] = set()
    work = [start]
    while work:
        path, fn = work.pop()
        if (path, fn.name) in visited:
            continue
        visited.add((path, fn.name))
        tree = _tree_of(path, trees)
        consts = _module_constants(tree)
        own = _own_nodes(fn)
        binds: dict[str, list[ast.AST]] = {}
        for node in own:
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        binds.setdefault(target.id, []).append(node.value)
        todo: list[ast.AST] = [n.value for n in own if isinstance(n, ast.Return) and n.value is not None]
        followed: set[str] = set()
        while todo:
            expr = todo.pop()
            if isinstance(expr, ast.Name):
                if expr.id in binds:
                    if expr.id not in followed:
                        followed.add(expr.id)
                        todo.extend(binds[expr.id])
                elif expr.id in consts:
                    found[f"{path.stem}.{expr.id}"] = consts[expr.id]
            elif isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
                other = HOOKS_DIR / f"{expr.value.id}.py"
                if other.is_file():
                    text = _module_constants(_tree_of(other, trees)).get(expr.attr)
                    if text is not None:
                        found[f"{expr.value.id}.{expr.attr}"] = text
            elif isinstance(expr, ast.Call):
                func = expr.func
                if isinstance(func, ast.Attribute) and func.attr == "format":
                    todo.append(func.value)
                elif isinstance(func, ast.Name):
                    callee = _module_function(tree, func.id)
                    if callee is not None:
                        work.append((path, callee))
                elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    other = HOOKS_DIR / f"{func.value.id}.py"
                    callee = _module_function(_tree_of(other, trees), func.attr) if other.is_file() else None
                    if callee is not None:
                        work.append((other, callee))
            elif isinstance(expr, ast.BoolOp):
                todo.extend(expr.values)
            elif isinstance(expr, ast.IfExp):
                todo.extend((expr.body, expr.orelse))
            elif isinstance(expr, (ast.Tuple, ast.List)):
                todo.extend(expr.elts)
            elif isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
                todo.extend((expr.left, expr.right))
    return found


def _unreadable_producer_sites() -> list[str]:
    """Unresolved sites whose producer is no function the walk can read."""
    trees: dict[Path, ast.Module] = {}
    return [
        f"{p.name}:{ln} (producer: {producer})"
        for p, ln, producer in _collect_deny_sites()[1]
        if _producer_function(p, producer, trees) is None
    ]


def _producers_rendering_nothing() -> list[str]:
    """Unresolved sites whose producer reads, but renders no declared template."""
    trees: dict[Path, ast.Module] = {}
    return [
        f"{p.name}:{ln} ({producer})"
        for p, ln, producer in _collect_deny_sites()[1]
        if _producer_templates(p, producer, trees) == {}
    ]


def _reachable_reason_texts() -> list[tuple[str, str]]:
    """Every text that can reach an agent, as ``(origin, text)``.

    The union of the two independent derivations plus every declared template
    a runtime producer renders (`_producer_templates`, one row per producer
    and template) -- so a reason is covered no matter which of the three
    paths it takes to the agent.
    """
    resolved, unresolved = _collect_deny_sites()
    out: list[tuple[str, str]] = []
    for path, lineno, text in resolved:
        out.append((f"{path.name}:{lineno}", text))
    for name, text in _DECLARED_REASONS().items():
        if name in _NOT_STANDALONE_REASONS:
            continue
        out.append((f"_denial_reasons.{name}", text))
    trees: dict[Path, ast.Module] = {}
    seen: set[tuple[Path, str]] = set()
    for hook, _lineno, producer in unresolved:
        for template, text in sorted((_producer_templates(hook, producer, trees) or {}).items()):
            origin = f"{producer} -> {template}"
            if (hook, origin) not in seen:
                seen.add((hook, origin))
                out.append((origin, text))
    return out


def _is_covered(reason_text: str) -> bool:
    """A reason is covered if any marker is a substring of the reason."""
    if any(frag in reason_text for frag in _EXEMPT_FRAGMENTS):
        return True
    lower = reason_text.lower()
    for marker in _DENY_REASON_MARKERS:
        if marker.lower() in lower:
            return True
    return False


def test_the_blocking_tier_is_exactly_the_set_of_hooks_that_deny():
    """Sanity floor, now in both directions (DEF-619): every blocking hook
    calls deny/block, AND every hook that calls deny/block is in the blocking
    tier. The reporter tier is derived as the complement, so a new hook that
    denies but was never added to GOVERNANCE_BLOCKING_HOOKS would land in the
    reporter tier -- excluded from the enforcement claim and narrated by init
    as one that "never blocks" -- with every count pin bumped and nothing red.
    This walk over the deny sites is the derived oracle that reds instead."""
    from espalier.harness_config import GOVERNANCE_BLOCKING_HOOKS

    reasons_by_file: dict[str, list[str]] = {}
    for path, _, text in _collect_deny_sites()[0]:
        reasons_by_file.setdefault(path.name, []).append(text)
    assert set(reasons_by_file) == set(GOVERNANCE_BLOCKING_HOOKS), (
        "hooks with deny()/block() call sites and GOVERNANCE_BLOCKING_HOOKS "
        f"disagree: deny sites in {sorted(reasons_by_file)}, tier "
        f"{sorted(GOVERNANCE_BLOCKING_HOOKS)} -- a hook that denies must be in "
        "the blocking tier (and mirrored in tools/cc/ci_guard.py)"
    )


def test_no_deny_site_is_silently_unreadable():
    """A reason this walk cannot read must FAIL, not vanish.

    The defect that made this contract worthless was not a wrong answer, it
    was a shrinking population: the walk read 14 of 33 sites and reported
    success over the 19 it could not parse. Any argument shape the resolver
    does not understand now reds by name, so the population can only ever be
    narrowed on purpose and in the open.

    A site whose reason a named producer renders is read through that
    producer (`_producer_templates`, DEF-750); what reds here is a site whose
    producer is no module-level function the walk can find -- a runtime
    attribute (``entry.message``), a call into a module that is not a hook, a
    nested function, or no producer at all (``<unknown>``).
    """
    orphans = _unreadable_producer_sites()
    assert not orphans, (
        "deny/block/_audit_deny call sites whose reason this contract cannot "
        "read, and whose producer is no module-level hook function the "
        "producer walk can read:\n  "
        + "\n  ".join(orphans)
        + "\n\nEither teach `_resolve_text` the shape, or bind the reason from "
        "a named module-level producer (``reason = _x_reason(...); "
        "deny(reason)``) that renders a declared template; `_producer_templates` "
        "reads its return flow. Do NOT widen the resolver to return a partial "
        "string -- a half-read reason matches a marker by accident and puts "
        "this contract back to sleep."
    )


def test_every_reachable_reason_has_a_marker():
    """Every text that can reach an agent must be recognised by a marker.

    Union of two INDEPENDENT derivations plus the runtime producers, because
    each is blind where the other sees: a reason registered in a rule table
    never appears at a `deny(...)` call site, and a reason assembled at a call
    site is not a declared constant. Measured — one live example of each.
    """
    uncovered: list[str] = []
    for origin, text in _reachable_reason_texts():
        if _is_covered(text):
            continue
        snippet = " ".join(text.split())
        if len(snippet) > 110:
            snippet = snippet[:110] + "..."
        uncovered.append(f"{origin}: {snippet!r}")
    assert not uncovered, (
        "Reasons that can reach an agent but match no entry in "
        "`bench/end_to_end/transcript.py::_DENY_REASON_MARKERS`. BCE-001's "
        "`deny_reason_received()` returns None for these, so the bench reports "
        "'friction layer is not teaching' about a hook that is teaching "
        "correctly:\n  "
        + "\n  ".join(sorted(set(uncovered)))
    )


def test_no_dead_markers():
    """The other direction: a marker matching nothing is not protection.

    Without this arm the expectation side rots invisibly. Measured before it
    existed: 8 of 20 markers could be deleted with the suite still green, and
    3 matched no live reason at all — two of them because the reason's WORDING
    had moved underneath them ('Run @code-reviewer' after the text became
    'invoke the code-reviewer agent', 'no active plan' after it became 'No
    active execution plan'). A marker is a claim about live text; when the text
    moves, the claim must red rather than quietly stop matching.
    """
    texts = [text for _, text in _reachable_reason_texts()]
    dead = [
        m for m in _DENY_REASON_MARKERS
        if not any(m.lower() in t.lower() for t in texts)
    ]
    assert not dead, (
        f"{len(dead)} of {len(_DENY_REASON_MARKERS)} deny markers match no "
        "reason that can reach an agent:\n  "
        + "\n  ".join(repr(m) for m in dead)
        + "\n\nRepoint each at the live wording or delete it. A marker that "
        "matches nothing cannot fail, and cannot protect the bench signal."
    )


def test_every_runtime_producer_renders_a_declared_template():
    """The floor under the derived producer population (DEF-750).

    The hand-kept producer map this replaces needed a self-expiry test (an
    entry outliving its site); a population read off the live sites holds no
    dead entry, so that test went with the map. What a derivation CAN do is
    narrow silently: a producer whose walk finds no declared template adds
    nothing to the marker arm while its site still denies. That reds here, by
    site and producer. A producer that loses ONE template of several passes
    here: a template declared in a reason module stays covered by the
    declared pass on its own, and the speed-bump template, the one text only
    this walk reaches today, also reds `test_no_dead_markers` (its
    "Speed-bump" marker matches no other text; measured by inlining it). The
    residual silent case is a module-local template of a non-reason module,
    dropped from a producer that still renders another.
    """
    empty = _producers_rendering_nothing()
    assert not empty, (
        "runtime reason producers whose return flow renders no declared "
        "template, so the marker contract covers nothing on their sites' "
        "behalf:\n  "
        + "\n  ".join(empty)
        + "\n\nRender the reason from a module-level string constant (a "
        "`_denial_reasons.py` template, or one of the producer's own module) "
        "or teach `_producer_templates` the return shape. A literal built "
        "inline is no declared template."
    )


def test_composed_fragments_are_still_composed():
    """Self-expiry for `_NOT_STANDALONE_REASONS`.

    A fragment is exempt from needing its own marker only while it is genuinely
    appended to something else. If a refactor makes one a standalone reason, the
    exemption silently hides an uncovered denial — so require that each name is
    still referenced somewhere outside its own declaration -- in another hook,
    or composed into another constant of `_denial_reasons.py` (a reference
    there beyond the declaring assignment; 2026-10-07).
    """
    referenced: set[str] = set()
    for hook in sorted(checkout_glob(HOOKS_DIR, "*.py")):
        text = hook.read_text(encoding="utf-8")
        for name in _NOT_STANDALONE_REASONS:
            uses = len(re.findall(rf"\b{re.escape(name)}\b", text))
            if uses > (1 if hook.name == "_denial_reasons.py" else 0):
                referenced.add(name)
    orphaned = sorted(set(_NOT_STANDALONE_REASONS) - referenced)
    assert not orphaned, (
        f"{len(orphaned)} `_NOT_STANDALONE_REASONS` entries are referenced by "
        f"no hook: {orphaned}. Either they are now standalone reasons that need "
        "their own marker, or they are dead constants. Delete the exemption "
        "either way."
    )


def test_reason_population_has_not_collapsed():
    """A floor, so a resolver regression cannot empty the population.

    Every arm above iterates a derived set; all of them pass vacuously over an
    empty one. This is a FLOOR, not a pin — the set may grow freely.
    """
    resolved, _ = _collect_deny_sites()
    assert len(resolved) >= 25, (
        f"only {len(resolved)} readable deny sites found (floor 25). The walk "
        "collapsed; every coverage arm above is now asserting over almost "
        "nothing while still reporting success."
    )
    assert len(_DECLARED_REASONS()) >= 25, (
        f"only {len(_DECLARED_REASONS())} declared reason constants resolved "
        "(floor 25) — the second derivation collapsed."
    )


def test_marker_redundancy_is_surfaced():
    """Markers are substrings, so a marker contained in another is dead
    weight. We don't FAIL on redundancy (a longer marker can carry a
    distinct reason a shorter one would over-match) — we surface it as a
    warning so the list stays tight without a brittle equality assert."""
    markers = list(_DENY_REASON_MARKERS)

    def _detect_and_surface() -> list[str]:
        redundant: list[str] = []
        for i, m in enumerate(markers):
            for j, n in enumerate(markers):
                if i == j:
                    continue
                if m != n and m.lower() in n.lower() and len(m) < len(n):
                    # m is a strict substring of n; surface as informational.
                    redundant.append(f"{n!r} fully contains {m!r}")
        if redundant:
            warnings.warn(
                "Redundant deny-reason markers (informational): "
                + "; ".join(redundant),
                stacklevel=2,
            )
        return redundant

    # Behavioral contract: redundancy is SURFACED (a warning), never silent.
    # The live marker set carries at least one strict-substring pair today, so
    # the warn path must fire — a no-op or deleted ``warnings.warn`` makes this
    # RED. (If the set is ever cleaned to zero redundancy, flip to
    # ``warnings.catch_warnings(record=True)`` and assert ``recorded == []``.)
    with pytest.warns(UserWarning, match="Redundant deny-reason markers"):
        redundant = _detect_and_surface()

    # Detection is correct, not merely non-empty: every surfaced pair is a true
    # strict-substring containment. An inverted length predicate would either
    # empty the list (failing the warns above) or report a non-containment here.
    assert redundant, "expected the live substring redundancy to be detected"
    for entry in redundant:
        longer, _, shorter = entry.partition(" fully contains ")
        assert shorter.strip("'").lower() in longer.strip("'").lower()
        assert len(shorter.strip("'")) < len(longer.strip("'"))


# ── DEF-834: a deny's reason is the assignment that reaches it on its own path ──


def _deny_sites_of(monkeypatch, tmp_path: Path, src: str):
    """``(resolved, unresolved)`` over one synthetic hook, the walk pointed at
    a throwaway tree. The declared-reasons cache is reset around the call so
    the throwaway's empty set is neither read in place of the live one nor
    left behind for the live rows."""
    (tmp_path / "synthetic.py").write_text(src, encoding="utf-8")
    here = sys.modules[__name__]
    monkeypatch.setattr(here, "HOOKS_DIR", tmp_path)
    monkeypatch.setattr(here, "_DECLARED_CACHE", None)
    return _collect_deny_sites()


_TWO_ARMS = [
    (
        "the-marker-less-arm-second",
        "def deny(reason):\n"
        "    return 0\n"
        "def _run_main(flag):\n"
        "    if flag:\n"
        "        reason = 'first arm. What to do: the first thing'\n"
        "        return deny(reason)\n"
        "    reason = 'second arm, no marker'\n"
        "    return deny(reason)\n",
        {6: "first arm. What to do: the first thing", 8: "second arm, no marker"},
    ),
    (
        "the-marker-less-arm-first",
        "def deny(reason):\n"
        "    return 0\n"
        "def _run_main(flag):\n"
        "    if flag:\n"
        "        reason = 'first arm, no marker'\n"
        "        return deny(reason)\n"
        "    reason = 'second arm. What to do: the second thing'\n"
        "    return deny(reason)\n",
        {6: "first arm, no marker", 8: "second arm. What to do: the second thing"},
    ),
]


@pytest.mark.parametrize("shape, src, expected", _TWO_ARMS, ids=[shape for shape, _, _ in _TWO_ARMS])
def test_two_arms_each_binding_the_reason_resolve_to_their_own_text(monkeypatch, tmp_path, shape, src, expected):
    # DEF-834: one map built over the whole function (the walk's last
    # assignment wins) read one arm's text twice and the other's never, so
    # the marker contract greened a marker-less arm. Each deny now reads the
    # assignment that reaches it on its own path; the arm order must not
    # matter, which is why the row runs both ways.
    resolved, unresolved = _deny_sites_of(monkeypatch, tmp_path, src)
    assert unresolved == [], (shape, unresolved)
    assert {ln: text for _p, ln, text in resolved} == expected, shape


def test_a_deny_after_two_binding_arms_carries_both_texts(monkeypatch, tmp_path):
    # Two arms bind the reason and fall through to ONE deny: both texts reach
    # the agent, so both are resolved at that site (the rule is block-prefix,
    # not control flow -- an assignment in a preceding branch is a further
    # candidate, never the one that wins).
    src = (
        "def deny(reason):\n"
        "    return 0\n"
        "def _run_main(flag):\n"
        "    if flag:\n"
        "        reason = 'A text'\n"
        "    else:\n"
        "        reason = 'B text'\n"
        "    return deny(reason)\n"
    )
    resolved, unresolved = _deny_sites_of(monkeypatch, tmp_path, src)
    assert unresolved == []
    assert sorted(text for _p, ln, text in resolved if ln == 8) == ["A text", "B text"]
    assert len(resolved) == 2


def test_a_straight_line_reassignment_replaces_the_earlier_text(monkeypatch, tmp_path):
    # A second assignment in the same block supersedes the first: the dead
    # text is not a reason that can reach the agent, and a marker for it
    # would be dead weight.
    src = (
        "def deny(reason):\n"
        "    return 0\n"
        "def _run_main():\n"
        "    reason = 'dead text'\n"
        "    reason = 'live text. What to do: the live thing'\n"
        "    return deny(reason)\n"
    )
    resolved, unresolved = _deny_sites_of(monkeypatch, tmp_path, src)
    assert unresolved == []
    assert [text for _p, _ln, text in resolved] == ["live text. What to do: the live thing"]


def test_an_assignment_before_the_try_reaches_a_deny_in_the_handler(monkeypatch, tmp_path):
    # The path is not bounded at the handler for an assignment: what was
    # bound before the try is what the handler denies with. (The bare-emitter
    # census bounds its RECORD there on purpose; that is its opt-in.)
    src = (
        "def deny(reason):\n"
        "    return 0\n"
        "def _run_main():\n"
        "    reason = 'set before the try. What to do: retry'\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:\n"
        "        return deny(reason)\n"
    )
    resolved, unresolved = _deny_sites_of(monkeypatch, tmp_path, src)
    assert unresolved == []
    assert {ln: text for _p, ln, text in resolved} == {8: "set before the try. What to do: retry"}


def test_an_unreadable_reason_names_the_producer_that_reaches_its_own_site(monkeypatch, tmp_path):
    # The unresolved arm reads the same path: two arms that each bind the
    # name from a different producer name their own producer, not the first
    # assignment the function holds.
    src = (
        "def deny(reason):\n"
        "    return 0\n"
        "def _run_main(flag):\n"
        "    if flag:\n"
        "        x = _first.make()\n"
        "        return deny(x)\n"
        "    x = _second.make()\n"
        "    return deny(x)\n"
    )
    resolved, unresolved = _deny_sites_of(monkeypatch, tmp_path, src)
    assert resolved == []
    assert {(ln, producer) for _p, ln, producer in unresolved} == {(6, "_first.make"), (8, "_second.make")}


def test_a_dependent_pair_in_one_branch_resolves_in_source_order(monkeypatch, tmp_path):
    # ``base`` is bound before ``reason`` reads it inside the same branch;
    # the walk is in source order (the helper's pre-order, not ast.walk's
    # breadth-first), so the composed text resolves whole. A partial text
    # here would be resolved, not unresolved -- silently wrong.
    src = (
        "def deny(reason):\n"
        "    return 0\n"
        "def _run_main(flag):\n"
        "    if flag:\n"
        "        base = 'prefix'\n"
        "        reason = base + ' tail. What to do: x'\n"
        "    return deny(reason)\n"
    )
    resolved, unresolved = _deny_sites_of(monkeypatch, tmp_path, src)
    assert unresolved == []
    assert [text for _p, _ln, text in resolved] == ["prefix tail. What to do: x"]


def test_the_same_unreadable_producer_in_two_arms_is_one_unresolved_row(monkeypatch, tmp_path):
    src = (
        "def deny(reason):\n"
        "    return 0\n"
        "def _run_main(flag):\n"
        "    if flag:\n"
        "        reason = mk.make()\n"
        "    else:\n"
        "        reason = mk.make()\n"
        "    return deny(reason)\n"
    )
    resolved, unresolved = _deny_sites_of(monkeypatch, tmp_path, src)
    assert resolved == []
    assert [(ln, producer) for _p, ln, producer in unresolved] == [(8, "mk.make")]


# -- DEF-750: a runtime producer's templates come from its own return flow --

_SYNTHETIC_REASONS = (
    "_OPERATOR_FACING_TEMPLATES = ()\n"
    "PROBE_TEMPLATE = 'Probe blocked: {cmd}. What to do: the probe thing'\n"
)

_NEW_PRODUCER = (
    "import _denial_reasons\n"
    "_LOCAL_TEMPLATE = 'Local probe blocked: {cmd}'\n"
    "def deny(reason):\n"
    "    return 0\n"
    "def PRODUCER(cmd, flag):\n"
    "    if flag:\n"
    "        return _denial_reasons.PROBE_TEMPLATE.format(cmd=cmd)\n"
    "    text = _local_text(cmd)\n"
    "    return text\n"
    "def _local_text(cmd):\n"
    "    return _LOCAL_TEMPLATE.format(cmd=cmd)\n"
    "def _run_main(cmd, flag):\n"
    "    reason = PRODUCER(cmd, flag)\n"
    "    return deny(reason)\n"
)


def _producer_sites_of(monkeypatch, tmp_path: Path, src: str):
    """`_deny_sites_of` with a reason module beside the synthetic hook: it
    declares itself one (``_OPERATOR_FACING_TEMPLATES``), as the live ones do."""
    (tmp_path / "_denial_reasons.py").write_text(_SYNTHETIC_REASONS, encoding="utf-8")
    return _deny_sites_of(monkeypatch, tmp_path, src)


@pytest.mark.parametrize("producer", ["_probe_reason", "_probe_reason_renamed"])
def test_a_new_runtime_producer_is_covered_with_no_roster_edit(monkeypatch, tmp_path, producer):
    # The class's acceptance criterion: a producer nobody registered, under
    # any name (the row's "who" is the maintainer whose rename re-keyed the
    # hand-kept map), is read through its return flow -- a declared template
    # of the reason module, and a same-module template reached through a
    # local name and a callee -- and both reach the marker arm's population.
    resolved, unresolved = _producer_sites_of(
        monkeypatch, tmp_path, _NEW_PRODUCER.replace("PRODUCER", producer)
    )
    assert resolved == []
    assert [(ln, name) for _p, ln, name in unresolved] == [(14, producer)]
    assert _producer_templates(tmp_path / "synthetic.py", producer) == {
        "_denial_reasons.PROBE_TEMPLATE": "Probe blocked: {cmd}. What to do: the probe thing",
        "synthetic._LOCAL_TEMPLATE": "Local probe blocked: {cmd}",
    }
    reachable = dict(_reachable_reason_texts())
    assert reachable[f"{producer} -> synthetic._LOCAL_TEMPLATE"] == "Local probe blocked: {cmd}"
    assert f"{producer} -> _denial_reasons.PROBE_TEMPLATE" in reachable
    assert _unreadable_producer_sites() == []
    assert _producers_rendering_nothing() == []


def test_a_producer_rendering_no_declared_template_is_named(monkeypatch, tmp_path):
    # The floor's own red: a producer that builds its reason inline reads
    # fine but renders no declared template, so it would add nothing to the
    # marker arm while its site still denies.
    src = (
        "def deny(reason):\n"
        "    return 0\n"
        "def _probe_reason(cmd):\n"
        "    return 'Probe inline: ' + cmd\n"
        "def _run_main(cmd):\n"
        "    return deny(_probe_reason(cmd))\n"
    )
    _resolved, unresolved = _producer_sites_of(monkeypatch, tmp_path, src)
    assert [(ln, name) for _p, ln, name in unresolved] == [(6, "_probe_reason")]
    assert _producer_templates(tmp_path / "synthetic.py", "_probe_reason") == {}
    assert _producers_rendering_nothing() == ["synthetic.py:6 (_probe_reason)"]
    assert _unreadable_producer_sites() == []


def test_a_producer_the_walk_cannot_find_is_named_as_unreadable(monkeypatch, tmp_path):
    # A producer in a module that is not a hook has no body to read: the
    # site reds as unreadable by name, never as a covered one.
    src = (
        "def deny(reason):\n"
        "    return 0\n"
        "def _run_main():\n"
        "    x = mk.make()\n"
        "    return deny(x)\n"
    )
    _resolved, unresolved = _producer_sites_of(monkeypatch, tmp_path, src)
    assert [(ln, name) for _p, ln, name in unresolved] == [(5, "mk.make")]
    assert _producer_templates(tmp_path / "synthetic.py", "mk.make") is None
    assert _unreadable_producer_sites() == ["synthetic.py:5 (producer: mk.make)"]
    assert _producers_rendering_nothing() == []
