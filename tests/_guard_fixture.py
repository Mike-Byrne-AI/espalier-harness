"""The protected tree a test lays into its project: the rehearsal's (DEF-811).

``bench/powershell_guard_rehearsal.py::carry_protected_tree`` makes every
directory the hook tree declares protected under a project a test already
holds, such as its ``tmp_path`` (the directories already there are kept; a
file or a dangling link at one of those names raises before the guard runs, a
directory link is followed, and a missing project is created). A project
without the tree judges a relative write from inside a protected directory
with the directory absent, so a deny the fixture suppressed reads as a correct
ALLOW. The project keeps the test's own root, so a suite fixture stays
plain-shaped; the rehearsal's ``throwaway_project`` is the shaped builder.

Loaded by path under a private name, never by the bare name: the bench pins in
``tests/test_write_guard.py`` register a fresh copy under the bare name and put
``sys.modules`` back after their class, and the copy held here stays out of
that. The import changes no ``sys.path``; the first call does, since it
executes the hook tree's ``_protected_zones.py``, which puts ``tools/cc`` and
``tools/cc/hooks`` on it and binds bare ``_hook_utils`` and ``_paths``.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REHEARSAL = Path(__file__).resolve().parent.parent / "bench" / "powershell_guard_rehearsal.py"
_NAME = "_guard_fixture_rehearsal"


def _load():
    spec = importlib.util.spec_from_file_location(_NAME, _REHEARSAL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_NAME] = module
    spec.loader.exec_module(module)
    return module


rehearsal = _load()
carry_protected_tree = rehearsal.carry_protected_tree
