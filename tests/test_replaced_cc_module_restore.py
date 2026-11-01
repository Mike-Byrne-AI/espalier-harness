"""Pin conftest's restore of a ``tools/cc`` module a test replaced under its bare name.

A module loaded at collection binds its siblings by their bare names, and
conftest's memo clears reach ``sys.modules.get("_hook_utils")``. A test that
registered a fresh ``_hook_utils`` there left the collection-time copy's
``say_once`` once-set uncleared for every later test, and the release gate's
serial leg redded ``tests/test_zone_watch.py`` after
``tests/test_state_file_flag_parity.py`` (DEF-2032). These tests drive the
fixture's own body around a replacement, since a second test reading what the
first left would split across xdist workers.
"""
# pytest-marker: default-unit  (drives one conftest fixture in-process; no subprocess, no tree write)
from __future__ import annotations

import sys
import types
from pathlib import Path

from tests import conftest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))
import _hook_utils  # noqa: E402
import _maintenance_mode  # noqa: E402

_HELD = ("_hook_utils", "_maintenance_mode")


def _drive(change) -> dict:
    """Run the restore fixture's setup, ``change()``, then its teardown, and
    return what ``sys.modules`` held for the two hook modules after it. A
    missing fixture is an assertion, so the pre-fix tree fails rather than
    errors; whatever the fixture did, the two modules go back after."""
    fixture = getattr(conftest, "_restore_replaced_tools_cc_modules", None)
    assert fixture is not None, "tests/conftest.py has no fixture restoring a replaced tools/cc module"
    held = {name: sys.modules.get(name) for name in _HELD}
    body = fixture.__wrapped__()
    try:
        next(body)
        change()
        next(body, None)
        return {name: sys.modules.get(name) for name in _HELD}
    finally:
        for name, mod in held.items():
            sys.modules[name] = mod


class TestAReplacedToolsCcModuleIsPutBack:
    def test_a_module_replaced_under_its_bare_name_is_restored_by_identity(self) -> None:
        """The parity loader's shape: a fresh copy registered where the
        collection-time one was. Mutation: compare by name, or restore nothing."""
        live = sys.modules["_hook_utils"]
        assert live is _hook_utils
        after = _drive(lambda: sys.modules.__setitem__("_hook_utils", types.ModuleType("_hook_utils")))
        assert after["_hook_utils"] is live

    def test_a_module_removed_from_sys_modules_is_restored(self) -> None:
        """A test that drops an entry to force a fresh import. Mutation:
        restore only the entries still present."""
        live = sys.modules["_maintenance_mode"]
        assert live is _maintenance_mode
        after = _drive(lambda: sys.modules.pop("_maintenance_mode"))
        assert after["_maintenance_mode"] is live

    def test_a_module_the_test_added_is_left(self) -> None:
        """An entry with no copy before the test is the test's to keep: a
        lazy first import under a bare name stays imported. Mutation: put the
        whole copy back."""
        name = "_restore_fixture_probe_added"

        def add() -> None:
            mod = types.ModuleType(name)
            mod.__file__ = str(HOOKS_DIR / f"{name}.py")
            sys.modules[name] = mod

        try:
            _drive(add)
            assert name in sys.modules
        finally:
            sys.modules.pop(name, None)

    def test_a_module_from_outside_tools_cc_is_left_as_the_test_made_it(self, tmp_path: Path) -> None:
        """The restore is scoped to tools/cc: a bare-name module from anywhere
        else that a test replaced stays replaced. Mutation: drop the path test."""
        name = "_restore_fixture_probe_elsewhere"
        first = types.ModuleType(name)
        first.__file__ = str(tmp_path / f"{name}.py")
        second = types.ModuleType(name)
        sys.modules[name] = first
        try:
            _drive(lambda: sys.modules.__setitem__(name, second))
            assert sys.modules[name] is second
        finally:
            sys.modules.pop(name, None)
