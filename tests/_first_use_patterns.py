"""The patterns a hook module compiles on first use behind a cache.

A census that walks a module's namespace for compiled patterns
(``vars(module)``) cannot see a pattern held as a source string and compiled
by a cached zero-argument accessor: `_bash_patterns._carrier_fed_remove_re`
(DEF-3063) sat outside every such census until DEF-3078's lane found it. A
census that must hold every pattern of its kind unions these in, each named
as its accessor's call (``_carrier_fed_remove_re()``), so an entry naming one
reads as a call and never as a module attribute. The rule approximates the
compile ratchet's (`tests/test_guard_compile_ratchet.py::first_use_compiles`):
a module-level function behind ``functools.lru_cache`` or ``functools.cache``
whose body names ``compile``. It is narrower where a census needs one
pattern: only a zero-argument accessor is called, never a nested function or
a method, and only a compiled pattern it returns is kept; a cached compile
that takes arguments stays the ratchet's alone.
"""
from __future__ import annotations

import re
from types import ModuleType


def first_use_patterns(module: ModuleType) -> dict[str, re.Pattern[str]]:
    """``{"<accessor>()": pattern}`` for every first-use compile ``module``
    defines (not one it imports), each accessor called once."""
    found: dict[str, re.Pattern[str]] = {}
    for name, obj in vars(module).items():
        wrapped = getattr(obj, "__wrapped__", None)
        code = getattr(wrapped, "__code__", None)
        if not hasattr(obj, "cache_info") or code is None:
            continue
        if getattr(wrapped, "__module__", None) != module.__name__:
            continue
        if code.co_argcount or code.co_kwonlyargcount or "compile" not in code.co_names:
            continue
        value = obj()
        if isinstance(value, re.Pattern):
            found[f"{name}()"] = value
    return found
