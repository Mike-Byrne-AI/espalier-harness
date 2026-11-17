"""Where a hook module's functions search a pattern, read from their source.

The hooks search a pattern in two call shapes: a method call on the pattern
(``RX.finditer(text)``, ``.search``, ``.match``, ``.fullmatch``) and the
scan-and-view helper ``_bash_patterns._scan_and_view_matches(RX, scan,
view)``, which searches its first argument over the scan and over the same
text with its redirects blanked (DEF-2087). A structural pin that knows one
shape goes blind on the other: the pins below each counted the method call
alone until the lane moved readers onto the helper, and one site pin stayed
green with a second, helper-routed search site of its pattern planted beside
it (DEF-2087's failure-mode review, S2). Every pin that asks which patterns
a function searches, or which functions search a pattern, asks here:

- `tests/test_write_guard.py::TestQuotedTargetSurvivesTheRoot::
  test_no_operand_is_read_off_the_scan_again`
- `tests/test_write_guard.py::TestRemovedOrRelocatedOperandIsAMutation::
  test_the_consumption_tuples_are_the_readers_free_names`
- `tests/test_write_guard.py::TestCatastrophicLoopCarrier::
  test_the_piped_remove_regex_has_exactly_its_two_readers_loop`
- `tests/test_write_guard.py::TestCatastrophicLoopCarrier::
  test_the_loop_openers_are_one_derived_roster_loop`
- `tests/test_bash_inert_syntax_mask.py::TestMaskControlsAndFailClosed::
  test_only_the_interpreter_sites_read_the_raw_command`
"""
from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import NamedTuple

#: The pattern methods that search a text.
SEARCH_METHODS = ("finditer", "search", "match", "fullmatch")
#: The helper that searches its pattern over a scan and its redirect view.
SCAN_AND_VIEW = "_scan_and_view_matches"


class RegexSearch(NamedTuple):
    """One search of a pattern: the pattern's name (``"?"`` when it is no
    bare name), how it is searched (a method name, or `SCAN_AND_VIEW`), the
    texts it searches (the method's first argument; the helper's scan and
    view), and the call itself."""
    regex: str
    shape: str
    texts: tuple[ast.expr, ...]
    call: ast.Call


def regex_search(call: ast.AST) -> RegexSearch | None:
    """``call`` as a search of a pattern in either shape, or None."""
    if not isinstance(call, ast.Call):
        return None
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in SEARCH_METHODS:
        name = func.value.id if isinstance(func.value, ast.Name) else "?"
        return RegexSearch(name, func.attr, tuple(call.args[:1]), call)
    if isinstance(func, ast.Name) and func.id == SCAN_AND_VIEW and call.args:
        head = call.args[0]
        name = head.id if isinstance(head, ast.Name) else "?"
        return RegexSearch(name, SCAN_AND_VIEW, tuple(call.args[1:3]), call)
    return None


def regex_searches(node: ast.AST) -> Iterator[RegexSearch]:
    """Every search of a pattern under ``node``, in either shape."""
    for sub in ast.walk(node):
        found = regex_search(sub)
        if found is not None:
            yield found


def text_names(search: RegexSearch) -> set[str]:
    """The bare names among the texts ``search`` searches."""
    return {t.id for t in search.texts if isinstance(t, ast.Name)}


def search_sites(tree: ast.AST, regex: str) -> set[str]:
    """The names of the functions under ``tree`` whose bodies search
    ``regex`` in either shape (a nested function counts for each function
    that holds it)."""
    return {fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
            and any(s.regex == regex for s in regex_searches(fn))}
