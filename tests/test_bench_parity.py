"""Parity tests between bench/baselines/* and the friction layer's PROTECTED_FILES.

The benchmark's `settings-deny-only` and `minimal-hooks` baselines hardcode
their own protected-path lists. If PROTECTED_FILES adds a new entry and
the baselines don't track it, the comparison silently becomes unfair:
espalier catches a class the baselines could have caught too if their
lists had been kept current.

TP-79: PROTECTED_FILES moved from write_guard.py to
tools/cc/hooks/_protected_zones.py during the dispatcher extraction.
write_guard.py re-exports the constant for the test imports that pin
the public surface, but the LITERAL set definition lives in the
extracted helper -- this parity test grep targets that file.

These tests assert that every PROTECTED_FILES entry appears in both
baseline configs. They do NOT assert the inverse -- the baselines may
include additional paths (and should, to mirror coverage of the
PROTECTED_PREFIXES).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTECTED_ZONES = REPO_ROOT / "tools" / "cc" / "hooks" / "_protected_zones.py"
SETTINGS_DENY_SH = REPO_ROOT / "bench" / "baselines" / "settings-deny-only" / "setup.sh"
MINIMAL_HOOKS_SH = REPO_ROOT / "bench" / "baselines" / "minimal-hooks" / "setup.sh"


def _extract_protected_files() -> set[str]:
    """Parse the PROTECTED_FILES literal set out of _protected_zones.py."""
    text = PROTECTED_ZONES.read_text(encoding="utf-8")
    match = re.search(r"PROTECTED_FILES\s*=\s*\{([^}]+)\}", text, re.DOTALL)
    assert match, "could not locate PROTECTED_FILES literal in _protected_zones.py"
    body = match.group(1)
    return {m.group(1) for m in re.finditer(r'"([^"]+)"', body)}


def _extract_settings_deny_paths() -> set[str]:
    """Parse the JSON deny block from settings-deny-only/setup.sh and
    return the set of paths covered by Write() / Edit() rules."""
    text = SETTINGS_DENY_SH.read_text(encoding="utf-8")
    match = re.search(r"<<'JSON'\s*\n(.*?)\nJSON\s*$", text, re.DOTALL | re.MULTILINE)
    assert match, "could not locate JSON heredoc in settings-deny-only/setup.sh"
    data = json.loads(match.group(1))
    deny = data.get("permissions", {}).get("deny", [])
    paths: set[str] = set()
    for rule in deny:
        m = re.match(r"^(?:Write|Edit)\(([^)]+)\)$", rule)
        if m:
            paths.add(m.group(1))
    return paths


def _extract_minimal_hooks_paths() -> set[str]:
    """Parse the PROTECTED list literal embedded in minimal-hooks/setup.sh."""
    text = MINIMAL_HOOKS_SH.read_text(encoding="utf-8")
    match = re.search(r"PROTECTED\s*=\s*\[([^\]]+)\]", text, re.DOTALL)
    assert match, "could not locate PROTECTED list in minimal-hooks/setup.sh"
    body = match.group(1)
    return {m.group(1) for m in re.finditer(r'"([^"]+)"', body)}


class TestBaselineParity:
    """write_guard.PROTECTED_FILES must be a subset of every baseline's list.

    Adding a new entry to PROTECTED_FILES without updating the baselines
    leaves the benchmark comparison unfair (espalier claims a block the
    naive baselines would have caught if their lists were current)."""

    def test_settings_deny_only_covers_protected_files(self):
        protected = _extract_protected_files()
        deny = _extract_settings_deny_paths()
        missing = protected - deny
        assert not missing, (
            f"settings-deny-only baseline missing deny rules for: {sorted(missing)}. "
            f"Add Write(<path>) and Edit(<path>) entries to "
            f"bench/baselines/settings-deny-only/setup.sh."
        )

    def test_minimal_hooks_covers_protected_files(self):
        protected = _extract_protected_files()
        listed = _extract_minimal_hooks_paths()
        missing = protected - listed
        assert not missing, (
            f"minimal-hooks baseline missing PROTECTED entries for: {sorted(missing)}. "
            f"Add to the PROTECTED list in "
            f"bench/baselines/minimal-hooks/setup.sh."
        )

    def test_protected_files_set_is_nonempty(self):
        """Sanity: parser must find at least the canonical settings.json entry."""
        protected = _extract_protected_files()
        assert ".claude/settings.json" in protected, (
            f"PROTECTED_FILES parser failed; got {protected!r}"
        )
