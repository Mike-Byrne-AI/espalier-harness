"""Recursive key-path extraction for documented-JSON-sample gates.

Shared by the two gates that check a doc's doctor sample against live output
(``test_quickstart_doctor_example`` and
``test_documented_claims::TestReadmeDoctorExampleMatchesLiveOutput``). One
home, because they enforce ONE policy and had already drifted into two
independently-written copies of it — both comparing ``set(parsed.keys())``
against ``set(live_obj.keys())``.

⚠ Why this module exists: that shared shape was DEPTH-1. It compared only the
outermost keys, so ``docs/QUICKSTART.md``'s sample could print
``"checks": {"presence": {"status": "pass", …}}`` — a ``status`` key the
six-key presence dict has never had — and both gates stayed green, because
``checks`` itself is a real top-level key and neither looked inside it
(DEF-468, §C5: green because it cannot fail, not because the property holds).
The docstrings promised "only keys the live command emits" while checking one
layer of a three-layer claim.

⚠ And each path carries the KIND of the value at it (DEF-585). A bare path set
let a sample collapse a whole dict into a single word: ``"checks": "ok"``
yields the path ``checks`` alone, a strict subset of the live paths, and both
gates stayed green over a sample that shows a scalar where the command emits a
nested dict. The kind lives here, in the one home both gates compare with, so
neither gate can compare paths without it.

Values are deliberately NOT compared. A documented sample is a tidied,
truncated illustration ("truncated to the most-watched fields"), so pinning
values would red on any tree whose fingerprint differs. The honest property is
that a sample cannot claim a key the code does not emit, nor a container shape
the code does not emit at that key: a string, a number, a boolean and null are
one kind, ``scalar``, since a sample may tidy one into another.
"""
from __future__ import annotations

from typing import Any


def kind_of(value: Any) -> str:
    """``object``, ``array`` or ``scalar``: the container shape of a JSON value."""
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "scalar"


def key_paths(node: Any, prefix: str = "") -> set[tuple[str, str]]:
    """Every dotted key path reachable in a parsed JSON value, with the kind
    of the value at it.

    ``{"a": {"b": 1}}`` yields ``{("a", "object"), ("a.b", "scalar")}``.

    List elements collapse onto their container's path: a sample showing
    ``"failures": []`` is claiming the key exists, and holds an array, not that
    it is empty, and a sample showing two dicts in a list claims the union of
    their keys.
    """
    paths: set[tuple[str, str]] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{prefix}.{key}" if prefix else str(key)
            paths.add((here, kind_of(value)))
            paths |= key_paths(value, here)
    elif isinstance(node, list):
        for item in node:
            paths |= key_paths(item, prefix)
    return paths


def describe_unknown(unknown: set[tuple[str, str]], live: set[tuple[str, str]]) -> list[str]:
    """One line per sample path the live output does not hold, naming the
    kind the live output has at that path where it has the path at all."""
    live_kinds: dict[str, set[str]] = {}
    for path, kind in live:
        live_kinds.setdefault(path, set()).add(kind)
    lines = []
    for path, kind in sorted(unknown):
        if path in live_kinds:
            lines.append(f"{path}: the sample shows {kind}, the live output "
                         f"{' or '.join(sorted(live_kinds[path]))}")
        else:
            lines.append(f"{path}: not in the live output")
    return lines
