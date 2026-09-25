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

Values are deliberately NOT compared. A documented sample is a tidied,
truncated illustration ("truncated to the most-watched fields"), so pinning
values would red on any tree whose fingerprint differs. The honest property is
that a sample cannot claim a key the code does not emit.
"""
from __future__ import annotations

from typing import Any


def key_paths(node: Any, prefix: str = "") -> set[str]:
    """Every dotted key path reachable in a parsed JSON value.

    ``{"a": {"b": 1}}`` yields ``{"a", "a.b"}``.

    List elements collapse onto their container's path: a sample showing
    ``"failures": []`` is claiming the key exists, not that it is empty, and a
    sample showing two dicts in a list claims the union of their keys.
    """
    paths: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{prefix}.{key}" if prefix else str(key)
            paths.add(here)
            paths |= key_paths(value, here)
    elif isinstance(node, list):
        for item in node:
            paths |= key_paths(item, prefix)
    return paths
