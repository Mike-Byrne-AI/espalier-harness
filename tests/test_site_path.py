"""Rows on ``tests/_site_path.py``: the statements that run on the way to one
site inside a function.

This is the DEF-828 block-prefix ascent, lifted out of the bare-emitter
census when DEF-833 and DEF-834 needed the same walk (the JSON dict-safety
census keys a guard on the deref's path, the deny-marker census resolves a
reason from the assignment that reaches the deny, the write-guard scan-reader
census reads the loop that binds a regex name). Four consumers share one
reading of "on the way", so its decisions are pinned here once, by name:
execution order (per level, the statements then the header; source order
within a statement), the enclosing headers, the two bounds, what a leaving
branch and a closure body prune, what ran before an ``else``, and the
``finally`` that only the record semantic asks for.
"""
# pytest-marker: default-unit  (pure-function AST rows; no subprocess, no tmp tree)
from __future__ import annotations

import ast
import sys

import pytest

from _site_path import SitePath, header_nodes, nodes_flowing_past, preorder, site_path


def _fn(src: str) -> ast.AST:
    tree = ast.parse(src)
    return next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "f"
    )


def _site(fn: ast.AST) -> ast.Call:
    """The one call spelled ``site(...)`` under ``fn``."""
    return next(
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "site"
    )


def _path(src: str, **kw) -> SitePath:
    fn = _fn(src)
    return site_path(fn, _site(fn), **kw)


def _assigned(nodes) -> list[str]:
    """The names bound by the ``Assign`` statements among ``nodes``, in order."""
    return [t.id for n in nodes if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]


def _names(nodes) -> list[str]:
    return [n.id for n in nodes if isinstance(n, ast.Name)]


def _calls(nodes) -> list[str]:
    return [n.func.id for n in nodes if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]


def _index(nodes, pred) -> int:
    return next(i for i, n in enumerate(nodes) if pred(n))


class TestExecutionOrder:
    def test_before_runs_outermost_first(self):
        p = _path(
            "def f(c):\n"
            "    a = 1\n"
            "    if c:\n"
            "        b = 2\n"
            "        site()\n"
            "    z = 9\n"
        )
        assert _assigned(p.before) == ["a", "b"]
        assert "z" not in _assigned(p.nodes())

    def test_the_site_statement_is_walked_whole(self):
        p = _path(
            "def f(d):\n"
            "    x = site() if isinstance(d, dict) else None\n"
        )
        assert p.before == ()
        assert "isinstance" in _calls(p.nodes())
        assert isinstance(p.site, ast.Assign)

    def test_nodes_interleaves_each_levels_before_and_header_in_execution_order(self):
        # The enclosing ``if``'s header runs BEFORE the statements inside it,
        # so it comes before them in ``nodes()`` -- not after every ``before``
        # of every level. A consumer that reads nearest-binding-wins over
        # ``nodes()`` depends on exactly this.
        p = _path(
            "def f(c, d):\n"
            "    a = 1\n"
            "    if isinstance(d, dict):\n"
            "        b = 2\n"
            "        site(c)\n"
        )
        nodes = p.nodes()
        a = _index(nodes, lambda n: isinstance(n, ast.Assign) and n.targets[0].id == "a")
        header = _index(nodes, lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "isinstance")
        b = _index(nodes, lambda n: isinstance(n, ast.Assign) and n.targets[0].id == "b")
        site = _index(nodes, lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "site")
        assert a < header < b < site
        assert len(p.levels) == 2 and _assigned(p.levels[0].before) == ["a"] and _assigned(p.levels[1].before) == ["b"]

    def test_nodes_flowing_past_and_preorder_are_in_source_order(self):
        # ``ast.walk`` is breadth-first; a consumer resolving ``reason = base
        # + '...'`` needs ``base`` bound first, so the walk is a pre-order in
        # field order and no consumer sorts.
        stmt = ast.parse("if c:\n    p = 1\n    q = 2\n    r = 3\n").body[0]
        assert _assigned(nodes_flowing_past(stmt)) == ["p", "q", "r"]
        expr = ast.parse("x = f(a, g(b), c)\n").body[0]
        assert _names(preorder(expr)) == ["x", "f", "a", "g", "b", "c"]

    def test_before_holds_whole_statements_not_their_contents(self):
        p = _path(
            "def f(c, d):\n"
            "    if c:\n"
            "        g = isinstance(d, dict)\n"
            "    site()\n"
        )
        assert _assigned(p.before) == [] and _assigned(p.nodes()) == ["g"], (
            "`before` holds whole statements; an assignment nested in a preceding "
            "branch is reached through nodes_flowing_past / nodes(), never by "
            "isinstance(stmt, ast.Assign) over `before` (DEF-834's own bug)"
        )


class TestTheEnclosingHeaders:
    def test_the_headers_of_every_enclosing_compound_statement_are_on_the_path(self):
        p = _path(
            "def f(d, e, xs):\n"
            "    if isinstance(d, dict):\n"
            "        while e:\n"
            "            for x in xs:\n"
            "                site()\n"
        )
        assert _calls(p.headers) == ["isinstance"]
        assert {"e", "xs", "x"} <= set(_names(p.headers))
        assert "isinstance" in _calls(p.nodes())

    def test_the_headers_are_ordered_outermost_first(self):
        p = _path(
            "def f(d, e):\n"
            "    if isinstance(d, dict):\n"
            "        while e:\n"
            "            site()\n"
        )
        outer = _index(p.headers, lambda n: isinstance(n, ast.Call))
        inner = _index(p.headers, lambda n: isinstance(n, ast.Name) and n.id == "e")
        assert outer < inner

    def test_a_header_holds_no_statement_of_the_blocks_it_owns(self):
        stmt = ast.parse("if c:\n    b = 2\nelse:\n    e = 3\n").body[0]
        nodes = header_nodes(stmt, stmt)
        assert _names(nodes) == ["c"]
        assert _assigned(nodes) == []
        assert stmt not in nodes

    def test_the_on_chain_handler_header_is_kept_and_a_sibling_handler_is_not(self):
        p = _path(
            "def f():\n"
            "    try:\n"
            "        a = 1\n"
            "    except KeyError:\n"
            "        k = 1\n"
            "    except ValueError as err:\n"
            "        site()\n"
        )
        assert "ValueError" in _names(p.headers)
        assert "KeyError" not in _names(p.nodes())
        assert "k" not in _assigned(p.nodes())

    def test_the_handler_clause_sits_above_the_handler_bound(self):
        # Under the record semantic's bound the handler's own ``except``
        # clause is not returned: the bound is the handler's BODY, and the
        # clause is the statement above it.
        src = (
            "def f():\n"
            "    try:\n"
            "        a = 1\n"
            "    except ValueError as err:\n"
            "        site()\n"
        )
        assert "ValueError" in _names(_path(src).headers)
        assert "ValueError" not in _names(_path(src, bound_at_handler=True).headers)

    def test_the_with_items_are_the_header(self):
        p = _path(
            "def f(p):\n"
            "    with open(p) as fh:\n"
            "        site()\n"
        )
        assert _calls(p.headers) == ["open"]
        assert "fh" in _names(p.headers)

    def test_an_async_with_is_read_like_a_with(self):
        p = _path(
            "async def f(p):\n"
            "    async with open(p) as fh:\n"
            "        site()\n"
        )
        assert _calls(p.headers) == ["open"]
        assert "fh" in _names(p.headers)

    def test_a_match_subject_and_the_on_chain_case_are_the_header_and_a_sibling_case_is_not(self):
        p = _path(
            "def f(m, flag):\n"
            "    match m:\n"
            "        case {'a': a} if flag:\n"
            "            site()\n"
            "        case [k]:\n"
            "            z = 1\n"
        )
        assert {"m", "flag"} <= set(_names(p.headers))
        assert "z" not in _assigned(p.nodes())
        assert not any(isinstance(n, ast.MatchSequence) for n in p.nodes())

    @pytest.mark.skipif(sys.version_info < (3, 11), reason="except* is 3.11+")
    def test_a_try_star_handler_is_read_like_a_try_handler(self):
        p = _path(
            "def f():\n"
            "    try:\n"
            "        a = 1\n"
            "    except* KeyError:\n"
            "        k = 1\n"
            "    except* ValueError:\n"
            "        site()\n"
        )
        assert "ValueError" in _names(p.headers)
        assert "KeyError" not in _names(p.nodes())
        assert "k" not in _assigned(p.nodes())
        assert "a" not in _assigned(p.nodes())

    def test_a_closure_body_in_a_header_is_not_on_the_path(self):
        p = _path(
            "def f(d):\n"
            "    with ctx(lambda: isinstance(d, dict)) as fh:\n"
            "        site()\n"
        )
        assert "ctx" in _calls(p.headers)
        assert "isinstance" not in _calls(p.nodes())


class TestTheBounds:
    SRC = (
        "def f():\n"
        "    a = 1\n"
        "    try:\n"
        "        t = 2\n"
        "    except Exception:\n"
        "        h = 3\n"
        "        site()\n"
    )

    def test_the_try_body_above_the_handler_is_off_the_path(self):
        p = _path(self.SRC)
        assert "t" not in _assigned(p.nodes())

    def test_the_path_reaches_the_function_body_by_default(self):
        # An assignment before the try is what a handler denies with; a
        # guard before the try is what protects a deref inside it.
        assert _assigned(_path(self.SRC).before) == ["a", "h"]

    def test_the_path_stops_at_the_handler_on_request(self):
        # The record semantic (DEF-828): a crash guard's record must be in
        # the handler itself, so the bare-emitter census bounds the path
        # there and nothing above the try is credited.
        assert _assigned(_path(self.SRC, bound_at_handler=True).before) == ["h"]

    def test_a_site_in_a_nested_def_sees_the_enclosing_prefix_above_the_def(self):
        # The statements above the ``def`` ran before the closure existed;
        # what ran between its definition and its call is not asked.
        p = _path(
            "def f():\n"
            "    a = 1\n"
            "    def g():\n"
            "        b = 2\n"
            "        site()\n"
            "    c = 3\n"
            "    return g\n"
        )
        assert _assigned(p.before) == ["a", "b"]
        assert "c" not in _assigned(p.nodes())

    def test_a_site_outside_the_function_is_refused_by_name(self):
        fn = _fn("def f():\n    return 1\n")
        stray = ast.parse("site()").body[0].value
        with pytest.raises(ValueError, match=r"line 1 .* body of f"):
            site_path(fn, stray)


class TestWhatRanBeforeAnElse:
    def test_the_try_body_is_on_the_path_to_its_else(self):
        p = _path(
            "def f():\n"
            "    try:\n"
            "        a = 1\n"
            "    except ValueError:\n"
            "        return None\n"
            "    else:\n"
            "        site()\n"
        )
        assert _assigned(p.before) == ["a"]

    def test_a_loop_body_is_on_the_path_to_its_else(self):
        # Block-prefix: the body may have run, and a binding in it counts.
        p = _path(
            "def f(xs):\n"
            "    for x in xs:\n"
            "        a = 1\n"
            "    else:\n"
            "        site()\n"
        )
        assert _assigned(p.before) == ["a"]

    def test_an_ifs_body_is_not_on_the_path_to_its_else(self):
        p = _path(
            "def f(c):\n"
            "    if c:\n"
            "        a = 1\n"
            "    else:\n"
            "        site()\n"
        )
        assert "a" not in _assigned(p.nodes())
        assert "c" in _names(p.headers)


class TestWhatLeavesIsPruned:
    def test_a_preceding_branch_that_returns_is_pruned_but_its_test_is_kept(self):
        p = _path(
            "def f(c, d):\n"
            "    if c:\n"
            "        g = isinstance(d, dict)\n"
            "        return None\n"
            "    site()\n"
        )
        assert len(p.before) == 1 and isinstance(p.before[0], ast.If)
        assert "g" not in _assigned(p.nodes())
        assert "isinstance" not in _calls(p.nodes())
        assert "c" in _names(p.nodes())

    def test_a_preceding_branch_that_falls_through_is_kept_whole(self):
        # Block-prefix, not control flow: whether the branch was taken is
        # not asked.
        p = _path(
            "def f(c, d):\n"
            "    if c:\n"
            "        g = isinstance(d, dict)\n"
            "    site()\n"
        )
        assert "g" in _assigned(p.nodes())

    def test_a_closure_body_on_the_path_is_not_credited(self):
        # A ``def`` or a ``lambda`` runs when called, not on the way past:
        # a guard inside one greens nothing. Its default arguments run at
        # definition and a class body runs at definition, so those count.
        p = _path(
            "def f(d, e):\n"
            "    ok = lambda: isinstance(d, dict)\n"
            "    def chk(x=isinstance(e, dict)):\n"
            "        g = isinstance(d, dict)\n"
            "    class K:\n"
            "        h = isinstance(d, dict)\n"
            "    site()\n"
        )
        assert _calls(p.nodes()).count("isinstance") == 2
        assert "g" not in _assigned(p.nodes())
        assert "h" in _assigned(p.nodes())

    def test_a_nested_def_that_returns_does_not_end_the_prefix(self):
        p = _path(
            "def f():\n"
            "    def chk():\n"
            "        return 1\n"
            "    a = 1\n"
            "    site()\n"
        )
        assert "a" in _assigned(p.before)

    def test_dead_code_after_a_return_is_never_on_the_path(self):
        p = _path(
            "def f():\n"
            "    a = 1\n"
            "    return None\n"
            "    b = 2\n"
            "    site()\n"
        )
        assert _assigned(p.before) == ["a"]

    def test_an_if_else_whose_arms_both_leave_ends_the_prefix(self):
        p = _path(
            "def f(c):\n"
            "    a = 1\n"
            "    if c:\n"
            "        return 1\n"
            "    else:\n"
            "        raise ValueError\n"
            "    b = 2\n"
            "    site()\n"
        )
        assert _assigned(p.before) == ["a"]

    def test_a_continue_is_not_a_terminator(self):
        # A binding before a ``continue`` survives past the loop (the
        # retry-loop shape DEF-828 pinned).
        p = _path(
            "def f(xs):\n"
            "    for x in xs:\n"
            "        if x:\n"
            "            a = 1\n"
            "            continue\n"
            "        site()\n"
        )
        assert "a" in _assigned(p.nodes())


class TestTheFinallyIsAnOptIn:
    def test_the_finally_on_the_way_out_of_a_handler_is_after_the_site(self):
        p = _path(
            "def f():\n"
            "    try:\n"
            "        a = 1\n"
            "    except Exception:\n"
            "        site()\n"
            "    finally:\n"
            "        z = 0\n"
        )
        assert _assigned(p.after) == ["z"]
        assert "z" not in _assigned(p.nodes())
        assert "z" in _assigned(p.nodes(with_finally=True))

    def test_the_finally_on_the_way_out_of_the_try_body_is_after_the_site(self):
        p = _path(
            "def f():\n"
            "    try:\n"
            "        site()\n"
            "    finally:\n"
            "        z = 0\n"
        )
        assert _assigned(p.after) == ["z"]

    def test_a_site_inside_the_finally_does_not_credit_itself(self):
        p = _path(
            "def f():\n"
            "    try:\n"
            "        a = 1\n"
            "    finally:\n"
            "        site()\n"
        )
        assert p.after == ()
