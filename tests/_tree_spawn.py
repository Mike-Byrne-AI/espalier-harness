"""The tree-ending spawns for the suite's own nested runs, from this checkout.

A test that runs a child which is itself a tree of work -- a nested pytest, a
script that runs one -- bounds it with ``run_tree_bounded`` (or, for a
``Popen`` it has to hold itself, ``communicate_tree_bounded``), never
``subprocess.run``: on POSIX ``run``'s timeout kills the child alone, and the
pytest it was running, with its xdist workers, hooks and git, runs on at
parent 1 beside the next test (DEF-1179). Both come from this checkout's
``tools/cc/_json_safe.py``, loaded by path under an alias (never an installed
engine's copy, and never the bare name a test may replace), on first use: a
plain ``import tests._tree_spawn`` loads nothing, so a module that imports it
still loads beside a ``tools/cc`` that predates these names.

``tests/test_contracts.py::TestEveryTimedPytestEndsItsWholeTree`` holds every
timed pytest spawn under ``tests/`` and ``scripts/`` to a tree-ending call.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
JSON_SAFE = REPO_ROOT / "tools" / "cc" / "_json_safe.py"
#: The names this module hands on from ``_json_safe``.
EXPORTED = ("run_tree_bounded", "communicate_tree_bounded")

_loaded: list[ModuleType] = []


def json_safe() -> ModuleType:
    """This checkout's ``tools/cc/_json_safe.py``, loaded once by path."""
    if not _loaded:
        spec = importlib.util.spec_from_file_location("_json_safe_for_tree_spawn", JSON_SAFE)
        assert spec is not None and spec.loader is not None, JSON_SAFE
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _loaded.append(module)
    return _loaded[0]


def __getattr__(name: str) -> Any:
    if name in EXPORTED:
        return getattr(json_safe(), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def bounded_spawn_names() -> frozenset[str]:
    """The bounded spawns ``tools/cc/_json_safe.py`` defines that take an argv
    first, read from its source: each top-level ``run_*`` function. Every
    detector that reads a spawn's argv by the spawn's name holds this set
    (``tests/test_proof_tier.py``'s nested-run rule, ``tests/
    test_portability_contract.py``'s bare-interpreter scan), so a new one
    reds there until each reads it."""
    tree = ast.parse(JSON_SAFE.read_text(encoding="utf-8"))
    return frozenset(node.name for node in tree.body
                     if isinstance(node, ast.FunctionDef) and node.name.startswith("run_"))
