"""TP-147 147-A: every surface that references the hook-audit noqa
annotation must use the canonical ``HOOK_AUDIT_NOQA_TEMPLATE``.

Surfaces pinned here:

- 3 hook source files (``config_guard``, ``post_write_check``,
  ``write_guard``) — substring check on the file body.
- 1 markdown surface (``docs/SHARP_EDGES.md``) — substring check on
  the file body. (``CHANGELOG.md`` was formerly pinned here, but its
  public dated history — including the release note that referenced
  this template — was collapsed and de-provenanced for the OSS launch,
  so it no longer references the annotation and is not a sister-site.)

A 6th surface, ``tests/test_hook_audit_noqa_annotations.py``,
references the template via Python import; that wiring is exercised
the moment the test module loads (an import error would surface as a
collection error before this test runs). It is intentionally not in
the substring sweep.

The companion scanner at ``scripts/check_exception_policy.py`` is
order-insensitive after TP-147 147-A, so the order ``BLE001, S110``
won't silently break the hook-source noqa lookups if it drifts. The
template still pins display order — the negative-direction assertion
below catches the wrong-order spelling (``noqa: S110, BLE001``)
anywhere in a pinned surface, so a prose mention that drifts to the
wrong order is caught structurally instead of by ``grep``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"


def _load_hook_audit_noqa_template() -> str:
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        import _hook_utils  # type: ignore
        return _hook_utils.HOOK_AUDIT_NOQA_TEMPLATE
    finally:
        sys.path.pop(0)


HOOK_AUDIT_NOQA_TEMPLATE = _load_hook_audit_noqa_template()

SOURCE_FILES = (
    "tools/cc/hooks/config_guard.py",
    # TP-330 — plan_guard gained an append_audit swallow (no-active-plan denials).
    "tools/cc/hooks/plan_guard.py",
    "tools/cc/hooks/post_write_check.py",
    "tools/cc/hooks/write_guard.py",
)
DOC_FILES = (
    "docs/SHARP_EDGES.md",
)

WRONG_ORDER_SUBSTRING = "noqa: S110, BLE001"


@pytest.mark.parametrize("relpath", SOURCE_FILES)
def test_source_file_contains_canonical_template(relpath: str) -> None:
    text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    assert HOOK_AUDIT_NOQA_TEMPLATE in text, (
        f"TP-147 147-A: {relpath} missing canonical "
        f"HOOK_AUDIT_NOQA_TEMPLATE substring "
        f"({HOOK_AUDIT_NOQA_TEMPLATE!r}). The hook-audit swallow noqa "
        f"line must equal the canonical template."
    )


@pytest.mark.parametrize("relpath", DOC_FILES)
def test_doc_file_contains_canonical_template(relpath: str) -> None:
    text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    assert HOOK_AUDIT_NOQA_TEMPLATE in text, (
        f"TP-147 147-A: {relpath} missing canonical "
        f"HOOK_AUDIT_NOQA_TEMPLATE substring — most likely the "
        f"`BLE001, S110` order drifted back to `S110, BLE001` or the "
        f"template was line-wrapped in the middle. Re-flow so the "
        f"full template fits on one line."
    )


@pytest.mark.parametrize("relpath", SOURCE_FILES + DOC_FILES)
def test_no_wrong_order_noqa_substring(relpath: str) -> None:
    """Inverse-direction guard: the wrong-order spelling
    ``noqa: S110, BLE001`` must not appear in any tracked sister
    surface. Catches prose-only mentions and split-line drift that
    the positive substring check would miss.
    """
    text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    assert WRONG_ORDER_SUBSTRING not in text, (
        f"TP-147 147-A: {relpath} contains wrong-order noqa spelling "
        f"{WRONG_ORDER_SUBSTRING!r}. Swap to the canonical "
        f"`BLE001, S110` order; the scanner is order-insensitive but "
        f"display order is pinned across all sister surfaces."
    )
