"""The statements that run on the way to one site inside a function -- the
block-prefix ascent the per-site censuses share.

A per-site classifier asks, for one site, "is this one guarded / recorded /
bound?". Keyed on a token found anywhere in the enclosing function it greens
every site once one site is compliant (``docs/FAILURE_MODES.md`` 18.15:
DEF-820 on the BOM census, DEF-828 on the bare-emitter census, DEF-833 on
the JSON dict-safety census, DEF-834 on the deny-marker census). Keyed on
the path to the site it does not, and this module is that path, derived
once, as ``levels`` outermost first -- one per block on the chain from the
function body down to the site's own -- each holding:

* ``before`` -- the WHOLE statements of that block before the one on the
  chain, up to the first that leaves (a ``return`` or a ``raise``, or an
  ``if``/``else`` whose arms both leave). A ``continue`` or ``break`` is not
  a terminator (a binding before a ``continue`` survives past the loop), and
  neither is ``sys.exit(...)``: what leaves any other way is read as flowing
  on, the conservative direction for a preceding branch. A consumer that
  tests ``isinstance(stmt, ast.Assign)`` over ``before`` sees only the
  top-level assignments and misses one nested in a preceding ``if`` -- which
  is DEF-834's own bug; ``nodes_flowing_past(stmt)`` is the way in, and it
  prunes what never flows on to the site: a sub-block that leaves (a branch
  that returned never reaches the site, and what follows its return is
  dead), and the body of a ``def`` or a ``lambda`` (it runs when called, not
  on the way past; its decorators, defaults and a class body do run). For a
  ``try``'s ``else`` the ``try`` body is on the path whole (the ``else``
  runs only when it completed); for a loop's ``else`` the loop body is
  (block-prefix: it may have run); for an ``if``'s ``else`` the other arm is
  not.
* ``header`` -- when the chain goes on below the statement, the expressions
  that run before its block: an ``if``/``while`` test, a ``for`` target and
  iterable, the ``with`` items, the on-chain ``except`` clause's type (a
  sibling handler is not on the path; under ``bound_at_handler`` the
  handler's own clause sits above the bound and is not returned), a
  ``match`` subject and the on-chain case's pattern and guard. A guard
  written as the test of the ``if`` around a deref is on the way to it.

Then ``site`` -- the statement holding the site, read whole (a closure
inside it is not pruned: the site may be in one) -- and ``after``, the
``finally`` blocks that run on the way out of the site's ``try`` body or
handler. Only a record semantic wants those (a flag-guarded audit record in
a ``finally`` reaches every arm's emit), so ``nodes()`` leaves them out
unless asked (``with_finally=True``). ``nodes()`` is in execution order:
each level's ``before`` (each statement in source order, pruned as above)
then its ``header``, outermost level first, then the site's statement, then
on request the ``finally`` blocks.

The bound is the function body. A site inside a nested ``def`` sees the
enclosing scope's statements above the ``def`` (they ran before the closure
existed; what ran between its definition and its call is not asked, the
conservative direction being to credit the prefix that certainly ran). On
request (``bound_at_handler=True``) the bound is the nearest ``except``
handler's body: the bare-emitter census wants a crash guard's record in the
handler itself and credits nothing above the ``try``. The ``try`` body above
a handler is off the path in both modes: which of its statements ran before
the raise is unknown. Block-prefix, not control flow: a statement in a
preceding branch that falls through counts whether or not the branch was
taken, and a header's polarity (``if not isinstance(...)``) is not read.

Consumers: ``tests/test_governance_audit_log.py`` (a record on the emit's
path; both opt-ins), ``tests/test_json_dict_safe.py`` (a guard on the
deref's path), ``tests/test_deny_markers.py`` (the assignment that reaches
the deny), ``tests/test_write_guard.py`` (the loop that binds a regex name,
through ``stmt_chain``). Rows: ``tests/test_site_path.py``.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass

#: A scope whose body runs when called, never on the way past.
_CALLED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def statement_lists(stmt: ast.AST) -> list[tuple[ast.AST, list[ast.stmt]]]:
    """``(owner, statements)`` for every statement list directly under
    ``stmt``: its ``body`` / ``orelse`` / ``finalbody`` (owned by ``stmt``),
    each except handler's body (owned by the handler) and each match case's
    body (owned by the case)."""
    out: list[tuple[ast.AST, list[ast.stmt]]] = []
    for field in ("body", "orelse", "finalbody"):
        val = getattr(stmt, field, None)
        if isinstance(val, list) and val and isinstance(val[0], ast.stmt):
            out.append((stmt, val))
    for handler in getattr(stmt, "handlers", None) or []:
        out.append((handler, handler.body))
    for case in getattr(stmt, "cases", None) or []:
        out.append((case, case.body))
    return out


def stmt_chain(
    owner: ast.AST, stmts: list[ast.stmt], target: ast.AST
) -> list[tuple[ast.AST, list[ast.stmt], int]]:
    """``[(owner, statements, index), ...]`` from ``stmts`` down to the
    innermost statement list holding ``target``, outermost first; empty when
    ``target`` is not under ``stmts``."""
    for idx, stmt in enumerate(stmts):
        if not any(node is target for node in ast.walk(stmt)):
            continue
        chain = [(owner, stmts, idx)]
        for sub_owner, sub_stmts in statement_lists(stmt):
            tail = stmt_chain(sub_owner, sub_stmts, target)
            if tail:
                return chain + tail
        return chain
    return []


def leaves(stmt: ast.stmt) -> bool:
    """A statement after which nothing in its block runs: a ``return`` or a
    ``raise``, or an ``if`` whose body and else branch both leave. The
    terminator set is exactly those; a ``continue`` or ``break`` is NOT one
    (a binding before a ``continue`` survives past the loop -- the retry-loop
    shape, pinned), and neither is ``sys.exit(...)`` nor a call whose result
    is bound (``rc = deny(...)``): a block that leaves any other way is read
    as flowing on, the conservative direction for a preceding branch. Asked
    of a block, never of a nested ``def``'s body (that body is pruned whole
    by ``nodes_flowing_past``, so a ``return`` inside it leaves nothing)."""
    if isinstance(stmt, (ast.Return, ast.Raise)):
        return True
    if isinstance(stmt, ast.If) and stmt.orelse:
        return block_leaves(stmt.body) and block_leaves(stmt.orelse)
    return False


def block_leaves(stmts: list[ast.stmt]) -> bool:
    """A block one of whose statements leaves left the function: what follows
    that statement is dead, and none of the block flows past its owner."""
    return any(leaves(s) for s in stmts)


def flowing(stmts: list[ast.stmt]) -> list[ast.stmt]:
    """The statements of a block that run before it leaves: everything up to
    the first leaving statement, exclusive. A statement after a ``return``
    or after an if/else whose arms both return is dead, and never on a path."""
    out: list[ast.stmt] = []
    for s in stmts:
        if leaves(s):
            break
        out.append(s)
    return out


def _children_that_run(node: ast.AST) -> list[ast.AST]:
    """The children of ``node`` that run on the way past it: not a statement
    list under it that leaves, not the body of a ``def`` or a ``lambda`` (its
    decorators, defaults and annotations do run at definition, and a class
    body runs at definition too)."""
    left = {id(s) for _owner, block in statement_lists(node) if block_leaves(block) for s in block}
    if isinstance(node, _CALLED_SCOPES):
        body = node.body if isinstance(node.body, list) else [node.body]
        left |= {id(n) for n in body}
    return [child for child in ast.iter_child_nodes(node) if id(child) not in left]


def preorder(root: ast.AST) -> list[ast.AST]:
    """Every node under ``root`` in source order (a pre-order walk in field
    order; ``ast.walk`` is breadth-first and is not), nothing pruned."""
    out: list[ast.AST] = []
    stack: list[ast.AST] = [root]
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(reversed(list(ast.iter_child_nodes(node))))
    return out


def nodes_flowing_past(stmt: ast.stmt) -> list[ast.AST]:
    """The nodes of a preceding statement that can run and then flow on to
    the statement after it, in source order: its subtree minus every
    statement list under it that leaves the function (a branch that returned
    or raised never reaches the site below, and what follows its return is
    dead) and minus the body of every ``def`` and ``lambda`` in it (a closure
    runs when called, not on the way past)."""
    out: list[ast.AST] = []
    stack: list[ast.AST] = [stmt]
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(reversed(_children_that_run(node)))
    return out


def header_nodes(compound: ast.AST, inner_owner: ast.AST) -> list[ast.AST]:
    """The nodes of ``compound`` that run before the block ``inner_owner``
    owns, in source order: everything under the statement that is not under
    one of its own statement lists, less every ``except`` handler and
    ``match`` case that is not ``inner_owner`` (a sibling clause is not on
    the way) and less a closure body in a header expression. The compound
    node itself is not returned: a header is expressions."""
    skip: set[int] = set()
    for _owner, stmts in statement_lists(compound):
        for s in stmts:
            skip.add(id(s))
    clauses = list(getattr(compound, "handlers", None) or []) + list(getattr(compound, "cases", None) or [])
    for clause in clauses:
        if clause is not inner_owner:
            skip.add(id(clause))
    out: list[ast.AST] = []
    stack: list[ast.AST] = [compound]
    while stack:
        node = stack.pop()
        if node is not compound:
            out.append(node)
        stack.extend(reversed([c for c in _children_that_run(node) if id(c) not in skip]))
    return out


@dataclass(frozen=True)
class Level:
    """One block on the chain: the whole statements before the one on the
    chain, and the header of that statement when the chain goes on below."""

    before: tuple[ast.stmt, ...]
    header: tuple[ast.AST, ...]


@dataclass(frozen=True)
class SitePath:
    """The way to one site: see the module docstring for each field."""

    levels: tuple[Level, ...]
    site: ast.stmt
    after: tuple[ast.stmt, ...]

    @property
    def before(self) -> tuple[ast.stmt, ...]:
        """Every level's ``before``, outermost level first: the whole
        statements that run before the site's own, in execution order."""
        return tuple(s for level in self.levels for s in level.before)

    @property
    def headers(self) -> tuple[ast.AST, ...]:
        """Every level's ``header``, outermost level first."""
        return tuple(n for level in self.levels for n in level.header)

    def nodes(self, *, with_finally: bool = False) -> list[ast.AST]:
        """Every node on the path, in execution order: per level, the
        ``before`` statements (each pruned by ``nodes_flowing_past``) then the
        header, outermost level first; then the site's statement whole; then
        -- on request -- the ``finally`` blocks on the way out."""
        out: list[ast.AST] = []
        for level in self.levels:
            for stmt in level.before:
                out.extend(nodes_flowing_past(stmt))
            out.extend(level.header)
        out.extend(preorder(self.site))
        if with_finally:
            for stmt in self.after:
                out.extend(nodes_flowing_past(stmt))
        return out


def _ran_before_this_block(owner: ast.AST, stmts: list[ast.stmt]) -> list[ast.stmt]:
    """The sibling block that ran before ``stmts`` when ``stmts`` is an
    ``else``: a ``try``'s body (it completed, or the ``else`` would not run)
    and a loop's body (block-prefix: it may have run). An ``if``'s body is
    the other arm and did not."""
    if stmts is not getattr(owner, "orelse", None):
        return []
    if isinstance(owner, (ast.For, ast.AsyncFor, ast.While)) or hasattr(owner, "finalbody"):
        return flowing(owner.body)
    return []


def site_path(fn: ast.AST, site: ast.AST, *, bound_at_handler: bool = False) -> SitePath:
    """The path to ``site`` under ``fn`` (a function node; its ``body`` is
    the outermost block). Raises ``ValueError`` naming the site's line and
    the function when the site is not under the body (a decorator, a default
    argument) -- a walk that lost its site must say so, never answer with an
    empty path a consumer would read as "nothing guards it"."""
    chain = stmt_chain(fn, fn.body, site)  # type: ignore[attr-defined]
    if not chain:
        raise ValueError(
            f"the site at line {getattr(site, 'lineno', '?')} is not under the body of "
            f"{getattr(fn, 'name', '?')} (a decorator or a default argument is not on any path)"
        )
    start = 0
    if bound_at_handler:
        start = max([0] + [i for i, (owner, _stmts, _idx) in enumerate(chain) if isinstance(owner, ast.ExceptHandler)])
    levels: list[Level] = []
    for i in range(start, len(chain)):
        owner, stmts, idx = chain[i]
        before = _ran_before_this_block(owner, stmts) + flowing(stmts[:idx])
        header: list[ast.AST] = []
        if i + 1 < len(chain):
            header = header_nodes(stmts[idx], chain[i + 1][0])
        levels.append(Level(tuple(before), tuple(header)))
    _owner, stmts, idx = chain[-1]
    site_stmt = stmts[idx]
    after: list[ast.stmt] = []
    for i in range(len(chain) - 1, start - 1, -1):
        owner, stmts, _idx = chain[i]
        finalbody: list[ast.stmt] = []
        if isinstance(owner, ast.ExceptHandler) and i >= 1:
            _outer, outer_stmts, outer_idx = chain[i - 1]
            finalbody = getattr(outer_stmts[outer_idx], "finalbody", None) or []
        elif hasattr(owner, "finalbody") and stmts is not owner.finalbody:
            finalbody = owner.finalbody
        after.extend(flowing(finalbody))
    return SitePath(tuple(levels), site_stmt, tuple(after))
