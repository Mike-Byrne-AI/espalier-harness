"""Class-of-bug guard: post-TP-70 Gate-5 / state-gates stragglers.

TP-70 removed stop_gate Gate 5 ("session state saved") on 2026-05-18.
TP-77 swept the docs. TP-84 swept the code. This contract pins the
sweep going forward: any code or test that names a removed gate must
explicitly tag the reference as historical (mention 'TP-70' in the
same line or the line immediately before) or fail CI.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
SCAN_ROOTS = [
    REPO_ROOT / "tools",
    REPO_ROOT / "espalier",
    REPO_ROOT / "tests",
]

_TRIGGER_PATTERNS = [
    re.compile(r"\bGate\s*5\b", re.IGNORECASE),
    re.compile(r"\bgates?\s*2/3/5\b"),
    re.compile(r"\b5-gate\b"),
    re.compile(r"\bstate\s+gates?\b"),
]

_SELF_PATH = Path(__file__).resolve()


def _is_historical(line: str, prior_line: str) -> bool:
    """A trigger occurrence is historical if 'TP-70' appears on the
    same line or the immediately-preceding non-blank line."""
    return "TP-70" in line or "TP-70" in prior_line


def test_no_stale_gate_five_references() -> None:
    failures: list[str] = []
    for root in SCAN_ROOTS:
        for py_file in root.rglob("*.py"):
            if py_file.resolve() == _SELF_PATH:
                continue
            try:
                lines = py_file.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines):
                for pattern in _TRIGGER_PATTERNS:
                    if pattern.search(line):
                        prior = lines[i - 1] if i > 0 else ""
                        if not _is_historical(line, prior):
                            failures.append(
                                f"{py_file.relative_to(REPO_ROOT)}:{i + 1}: "
                                f"{line.strip()}"
                            )
    assert not failures, (
        "Stale Gate-5 / state-gates references found (TP-70 removed "
        "stop_gate Gate 5 on 2026-05-18). Either fix the reference or "
        "tag the line with 'TP-70' to mark it historical:\n"
        + "\n".join(failures)
    )
