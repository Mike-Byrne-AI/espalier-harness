"""`scripts/audit_dead_rules.py` walks every regex rule of `_bash_patterns`,
the first-use ones included (DEF-5116, DEF-2084).

Its collector kept the module-level names ending in `_RE` that hold an
`re.Pattern`: the three cached accessors were never walked (DEF-5116), and
since DEF-2084 every module-level pattern is a `_FirstUse` object, which that
check reads as none. Each population below is derived from the module, by
type and by signature, never from a name list, so a rule of either kind the
collector misses reds here.
"""
# pytest-marker: default-unit
from __future__ import annotations

import importlib.util
import inspect
import re
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _audit() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("audit_dead_rules_under_test",
                                                  REPO_ROOT / "scripts" / "audit_dead_rules.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestEveryFirstUsePatternIsARule:
    def test_every_first_use_object_named_re_is_a_rule(self):
        audit = _audit()
        bp = audit._bash_patterns
        objects = {n: o for n, o in vars(bp).items() if type(o) is getattr(bp, "_FirstUse", None) and n.endswith("_RE")}
        assert objects, "no first-use object named _RE in _bash_patterns: re-derive this row"
        got = dict(audit.collect_regex_rules())
        missing = sorted(n for n, o in objects.items()
                         if n not in got or (got[n].pattern, got[n].flags) != (o.pattern, o.flags))
        assert not missing, f"first-use extractors the audit does not walk: {missing}"

    def test_every_zero_argument_cached_accessor_is_a_rule(self):
        """The row's own probe: accessors found by signature, whatever their
        name, read by pattern and flags."""
        audit = _audit()
        bp = audit._bash_patterns
        accessors = [f for f in (getattr(bp, n) for n in dir(bp))
                     if callable(f) and hasattr(f, "cache_info") and not inspect.signature(f).parameters]
        patterns = [r for r in (f() for f in accessors) if isinstance(r, re.Pattern)]
        assert patterns, "no zero-argument cached accessor returns a pattern: re-derive this row"
        got = {(p.pattern, p.flags) for _, p in audit.collect_regex_rules()}
        missing = [r.pattern[:60] for r in patterns if (r.pattern, r.flags) not in got]
        assert not missing, f"accessor patterns the audit does not walk: {missing}"

    def test_the_count_line_says_what_each_source_gave(self, capsys):
        audit = _audit()
        named, accessors = len(audit.collect_named_rules()), len(audit.collect_accessor_rules())
        assert named and accessors
        assert audit.main() == 0
        out = capsys.readouterr().out
        assert f"{named + accessors} regex extractors ({named} named _RE, {accessors} first-use accessors)" in out, out
