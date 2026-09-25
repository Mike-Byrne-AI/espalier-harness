"""TP-146 146-D contract (TP-147 147-A canonical-template extension):
governance-hook audit-write `try/except: pass` sites must carry an
explicit `noqa: BLE001, S110 -- <reason>` annotation whose reason
mentions audit + stderr/hook.

These three sites wrap `_integrity.append_audit(...)` calls. PreToolUse
and ConfigChange hooks treat stderr as the deny reason per
`docs/external/cc-hook-protocol.md`, so adding a stderr log here would
break the hook protocol's channel-XOR rule. The silent swallow is
correct — the noqa pins the rationale so future ruff bumps don't
strip the suppression without thought.

TP-147 147-A added an additional assertion: each swallow line must
contain the canonical `tools.cc.hooks._hook_utils.HOOK_AUDIT_NOQA_TEMPLATE`
substring. Code order (`BLE001, S110`) is order-insensitive against
`scripts/check_exception_policy.py` but pinned for visual consistency
across all sister surfaces.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"


def _load_hook_audit_noqa_template() -> str:
    """Import the canonical template via the same sys.path the hooks use."""
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        import _hook_utils  # type: ignore
        return _hook_utils.HOOK_AUDIT_NOQA_TEMPLATE
    finally:
        sys.path.pop(0)


HOOK_AUDIT_NOQA_TEMPLATE = _load_hook_audit_noqa_template()

HOOK_FILES = (
    "tools/cc/hooks/config_guard.py",
    # TP-330 — plan_guard now routes its no-active-plan denials through
    # append_audit (4th sister surface).
    "tools/cc/hooks/plan_guard.py",
    "tools/cc/hooks/post_write_check.py",
    "tools/cc/hooks/write_guard.py",
)

# Tolerant of either `--` or `—` separator between codes and reason.
NOQA_RE = re.compile(r"noqa:\s*([A-Z0-9,\s]+?)(?:\s+(?:--|—)\s*(.+))?$")


def _audit_swallow_lines(tree: ast.AST) -> list[int]:
    """Return AST line numbers of `except: pass` blocks that wrap a
    `_integrity.append_audit(...)` call (in the same try body)."""
    matches = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        wraps_audit = any(
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr == "append_audit"
            for stmt in node.body
        )
        if not wraps_audit:
            continue
        for handler in node.handlers:
            if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                matches.append(handler.lineno)
    return matches


@pytest.mark.contract
@pytest.mark.parametrize("relpath", HOOK_FILES)
def test_hook_audit_swallow_sites_have_noqa_reason(relpath):
    text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    tree = ast.parse(text)
    source_lines = text.splitlines()
    swallow_lines = _audit_swallow_lines(tree)
    assert swallow_lines, (
        f"{relpath}: expected at least one append_audit try/except: pass "
        "site (TP-146 146-D contract). If you removed the audit-write "
        "swallow, also update this test's HOOK_FILES tuple."
    )
    for ln in swallow_lines:
        comment_line = source_lines[ln - 1]
        m = NOQA_RE.search(comment_line)
        assert m, (
            f"{relpath}:{ln}: append_audit swallow must carry "
            f"`noqa: BLE001, S110 -- <reason>` annotation; got: {comment_line!r}"
        )
        codes = {c.strip() for c in m.group(1).split(",")}
        assert {"S110", "BLE001"}.issubset(codes), (
            f"{relpath}:{ln}: noqa must include both S110 and BLE001; "
            f"got codes={sorted(codes)!r}"
        )
        reason = (m.group(2) or "").lower()
        mentions_audit = "audit" in reason
        mentions_stderr_or_hook = "stderr" in reason or "hook" in reason
        assert mentions_audit and mentions_stderr_or_hook, (
            f"{relpath}:{ln}: noqa reason must mention 'audit' and "
            f"'stderr' (or 'hook'); got reason={reason!r}"
        )
        # TP-147 147-A: additionally pin the canonical template substring.
        # Sites import the constant rather than hardcoding a divergent reason.
        comment_after_hash = comment_line.split("#", 1)[-1].strip()
        assert HOOK_AUDIT_NOQA_TEMPLATE in comment_after_hash, (
            f"{relpath}:{ln}: audit-write swallow line does not carry the "
            f"canonical template. Expected: {HOOK_AUDIT_NOQA_TEMPLATE!r}; "
            f"got: {comment_line!r}. Update via the TP-147 147-A pattern: "
            f"the noqa reason must equal the canonical template "
            f"(tools.cc.hooks._hook_utils.HOOK_AUDIT_NOQA_TEMPLATE)."
        )
