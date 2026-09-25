"""TP-94 §C — adopter-facing cheat-sheet denylist contract.

`docs/CHEAT-SHEET.md` is an adopter-facing quick-reference doc. Internal
pack IDs (`TP-NN`, `TP-XXX-NN`) and bypass-class IDs (`BC-NN`) leak
implementation history without value to OSS readers; the doc must
stay clean.

Sibling-shape to TP-78's
``TestCommonTierAssetHygiene::test_common_tier_assets_have_no_internal_pack_ids``
at ``tests/test_init_tier_split.py::test_common_tier_assets_have_no_internal_pack_ids``. Same denylist pattern,
different surface (single file vs directory tree).

Scan covers the FULL file body — no code-fence stripping. Code-block
comments that anchored a command's provenance with `(TP-NN)` were
rewritten in 94-C to neutral phrasing; new comments must follow the
same discipline.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHEAT_SHEET = REPO_ROOT / "docs" / "CHEAT-SHEET.md"

FORBIDDEN_PATTERNS: tuple[str, ...] = (
    r"TP-\d+",
    r"TP-[A-Z]+-\d+",
    r"BC-\d+",
)


class TestCheatSheetNoInternalIds:
    """CHEAT-SHEET must not leak internal pack or bypass-class IDs."""

    def test_no_internal_pack_or_bypass_ids(self) -> None:
        assert CHEAT_SHEET.exists(), (
            f"docs/CHEAT-SHEET.md missing at {CHEAT_SHEET}"
        )
        body = CHEAT_SHEET.read_text(encoding="utf-8")
        compiled = [(re.compile(p), p) for p in FORBIDDEN_PATTERNS]
        offenders: list[tuple[int, str, str]] = []
        for lineno, line in enumerate(body.splitlines(), start=1):
            for pattern, source in compiled:
                for hit in pattern.findall(line):
                    offenders.append((lineno, hit, source))
        assert not offenders, (
            "docs/CHEAT-SHEET.md leaks internal IDs:\n"
            + "\n".join(
                f"  L{lineno}: {hit}  (matched {pat})"
                for lineno, hit, pat in offenders
            )
            + "\nRewrite the line to neutral phrasing (drop the paren-tag "
            "or replace with descriptive language); see TP-94 §C."
        )
