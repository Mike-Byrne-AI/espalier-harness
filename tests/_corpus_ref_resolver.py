"""Stdlib-only resolver for corpus ``documented_in`` refs (BC-034).

Extracted from tests/test_corpus_documented_in_resolves.py so that
bench/run_benchmark.py's BC-034 verifier can load the resolver WITHOUT
importing pytest -- keeping the benchmark runner genuinely runnable on a
fresh clone with no third-party packages installed (README's
"stdlib-only" claim). The test module re-imports these helpers unchanged.

Resolver tolerates the human-readable patterns used in the existing corpus:

* Parenthetical annotations -- ``TestKillSwitchScan (inner-empty cases)``
  or ``TestX (8 tests covering A + B + C)``. All ``(...)`` sub-strings
  are stripped before splitting on separators (otherwise a ``+`` inside
  the annotation would split a single ref into garbage fragments).
* Combo refs joined by ``+``, ``;``, or the literal word ``plus`` --
  ``TestA + tests/test_b.py::TestB``. Each segment is tried
  independently; at least one must resolve.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_PAREN_ANNOTATION = re.compile(r"\s*\([^)]*\)")
_SEGMENT_SPLIT = re.compile(r"\s*(?:\+|;|\bplus\b)\s*")


def _resolve_single_ref(ref: str, repo_root: Path) -> bool:
    """``tests/test_foo.py::TestBar`` or ``tests/test_foo.py::TestBar::test_baz``."""
    ref = ref.strip().rstrip(".").strip()
    if "::" not in ref:
        return False
    parts = ref.split("::")
    file_part, syms = parts[0], parts[1:]
    test_file = repo_root / file_part
    if not test_file.is_file():
        return False
    try:
        tree = ast.parse(test_file.read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return False
    names = {
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    # Only the top-level symbol must resolve -- ``Class::method`` is
    # treated as "the Class exists; method existence is asserted by
    # pytest at collection time, not here."
    return syms[0].strip() in names


def _resolve_test_ref(ref: str, repo_root: Path) -> bool:
    """Resolve a possibly-combo ref. At least one segment must resolve.

    Strip parenthetical annotations FIRST so that ``+`` chars inside
    them do not become spurious split points.
    """
    cleaned = _PAREN_ANNOTATION.sub("", ref).strip()
    for segment in _SEGMENT_SPLIT.split(cleaned):
        if _resolve_single_ref(segment, repo_root):
            return True
    return False
