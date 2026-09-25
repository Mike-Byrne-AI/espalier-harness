"""TP-116: enforce that every registered (producer, consumer-test)
pair has a parity test that drives the consumer with real producer
output.

The contract pins the parity-test FUNCTION name AND its body's
import/call pattern. Renaming, deleting, skipping, OR stubbing the
parity test fires.
"""
import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
from _closed_loop_registry import CLOSED_LOOP_REGISTRY


def _find_function(tree: ast.AST, function_name: str) -> ast.FunctionDef | None:
    """Return the FunctionDef node for the named function, or None.

    Walks the full AST so class-method, top-level, and decorated
    functions all match.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    return None


def _body_imports_module(fn: ast.FunctionDef, dotted_module: str) -> bool:
    """Return True if the function body contains an Import or
    ImportFrom matching ``dotted_module`` (e.g., 'espalier.analyze').

    Matches BOTH ``import espalier.analyze`` AND
    ``from espalier.analyze import detect_tests`` shapes.
    """
    target_top = dotted_module.split(".")[0]
    for node in ast.walk(fn):
        if isinstance(node, ast.Import):
            for n in node.names:
                if n.name == dotted_module or n.name.startswith(
                    dotted_module + "."
                ):
                    return True
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == dotted_module or mod.startswith(dotted_module + "."):
                return True
            # ``from espalier import analyze`` form: matches if the
            # imported name is the leaf module.
            if mod == target_top:
                for n in node.names:
                    if (
                        n.name == dotted_module.split(".")[-1]
                        and "." in dotted_module
                    ):
                        return True
    return False


def _body_calls_function(fn: ast.FunctionDef, function_name: str) -> bool:
    """Return True if the function body invokes ``function_name``.

    Matches ``function_name(...)`` and ``obj.function_name(...)``.
    """
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id == function_name:
                return True
            if isinstance(f, ast.Attribute) and f.attr == function_name:
                return True
    return False


def _parity_test_validates_producer(
    consumer_test_path: Path,
    function_name: str,
    producer_module: str,
    producer_function: str,
) -> tuple[bool, str]:
    """Return (ok, reason). Strict check: function exists AND its
    body imports the producer module AND calls the producer
    function. Returns the first failing condition as ``reason``.
    """
    try:
        tree = ast.parse(consumer_test_path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError) as e:
        return False, f"failed to parse {consumer_test_path}: {e}"
    fn = _find_function(tree, function_name)
    if fn is None:
        return False, f"function {function_name!r} not found"
    if not _body_imports_module(fn, producer_module):
        return False, (
            f"function {function_name!r} does not import "
            f"{producer_module!r} in its body"
        )
    if not _body_calls_function(fn, producer_function):
        return False, (
            f"function {function_name!r} does not call "
            f"{producer_function!r} in its body"
        )
    return True, ""


@pytest.mark.parametrize(
    "pair", CLOSED_LOOP_REGISTRY, ids=lambda p: p.name
)
def test_parity_test_validates_producer(pair):
    """The parity test must (a) exist by name, (b) import the
    producer module in its body, and (c) call the producer function
    in its body. A name-only function would pass a weaker contract
    but would defeat the whole point of the discipline."""
    consumer_test = REPO_ROOT / pair.consumer_test_path
    assert consumer_test.exists(), (
        f"Registered consumer test path does not exist: "
        f"{pair.consumer_test_path}"
    )
    ok, reason = _parity_test_validates_producer(
        consumer_test,
        pair.parity_test,
        pair.producer_module,
        pair.producer_function,
    )
    assert ok, (
        f"Closed-loop registry pair {pair.name!r} expects parity "
        f"test {pair.parity_test!r} in {pair.consumer_test_path} "
        f"to drive {pair.consumer_module}.{pair.consumer_function} "
        f"with REAL output from "
        f"{pair.producer_module}.{pair.producer_function}. "
        f"Verification failed: {reason}. "
        f"See docs/sharp-edges/closed-loop-verification-trap.md for "
        f"the de-circularization recipe. The body must import the "
        f"producer module AND call the producer function; a name-"
        f"only stub defeats the contract."
    )
