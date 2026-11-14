"""The patterns a hook module compiles on first use behind a cache.

A census that walks a module's namespace for compiled patterns
(``vars(module)``) cannot see a pattern held as a source string and compiled
by a cached zero-argument accessor: `_bash_patterns._carrier_fed_remove_re`
(DEF-3063), and `_shell_c_body_open_re` and `_ps_interp_stdin_re`, moved to
first use for DEF-3078/3079's per-call cost. A census that must hold every
pattern of its kind unions these in, each named as its accessor's call
(``_ps_interp_stdin_re()``), so an entry naming one reads as a call and never
as a module attribute. The rule matches the compile ratchet's
(`tests/test_guard_compile_ratchet.py::first_use_compiles`): a function behind
``functools.lru_cache`` or ``functools.cache`` whose body calls ``compile``;
only a zero-argument one is called here, and only a compiled pattern it
returns is kept.
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
