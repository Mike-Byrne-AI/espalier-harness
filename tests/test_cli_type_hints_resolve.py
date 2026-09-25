"""TP-146 146-A: forward-reference annotations in `espalier/cli.py`
must resolve via `typing.get_type_hints()` without raising NameError.

Reason: ruff F821 caught `RepoFingerprint` and `BuildPlan` referenced as
string annotations across `_build_claude_md`, `_build_memory_md`, and
the deploy helpers without an `if TYPE_CHECKING:` import block. Any
caller using `inspect.get_type_hints()` or annotation-driven
serialization (e.g., a future adopter-facing API documenter) would
crash. The fix adds a `TYPE_CHECKING` block at the top of `cli.py`
importing both names from `espalier.models`. These tests pin the
resolution so re-introducing the bug surfaces immediately.
"""
from __future__ import annotations

import typing

import pytest

from espalier import cli


@pytest.mark.contract
def test_cli_build_claude_md_hints_resolve():
    hints = typing.get_type_hints(cli._build_claude_md)
    assert "fp" in hints, hints
    assert "harness" in hints, hints


@pytest.mark.contract
def test_cli_build_memory_md_hints_resolve():
    hints = typing.get_type_hints(cli._build_memory_md)
    assert "fp" in hints, hints
