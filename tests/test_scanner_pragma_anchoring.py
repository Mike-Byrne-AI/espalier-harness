"""All generative-scanner PRAGMA_RE patterns must be anchored to start-of-line.

Reason: an unanchored pragma regex matches inline comments on flagged code lines
(e.g., `x = 1  # theater: ok reason`), giving a trivial suppression bypass.
SHARP_EDGES requires `^#` anchoring; this contract walks every scanner module
and pins it.

The contract was added by TP-145 after a sister-site regression where
`convergence_theater.py` and `magic_depth.py` both shipped unanchored
PRAGMA_RE patterns the same week as the TP-138/139 lesson should have
prevented exactly that.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest

import espalier.scanners as scanners_pkg
from espalier.scanners import (
    convergence_theater,
    encoding_contracts,
    magic_depth,
    subprocess_contracts,
)


def test_all_generative_pragma_regexes_are_anchored():
    drifted: list[tuple[str, str]] = []
    for mod_info in pkgutil.iter_modules(scanners_pkg.__path__):
        mod = importlib.import_module(f"espalier.scanners.{mod_info.name}")
        pragma_re = getattr(mod, "PRAGMA_RE", None)
        if pragma_re is None:
            continue
        if not pragma_re.pattern.startswith("^#"):
            drifted.append((mod_info.name, pragma_re.pattern))
    assert not drifted, (
        "Scanner PRAGMA_RE patterns must start with '^#' anchor; drift in: "
        f"{drifted}"
    )


# TP-150 §10.9 (effect-path vs accounting-path normalization asymmetry):
# each generative scanner pairs a count_pragmas (cap ACCOUNTING) reader with a
# _has_pragma_above (exemption EFFECT) reader. Before E-1, convergence_theater
# and magic_depth normalized only in the exemption path -- an indented pragma
# was honored as an exemption yet invisible to the cap counter, so the
# discipline the cap encodes was silently unenforced. The contract: ONE shared
# normalization helper (`_pragma_in_line`) backs both readers, so an indented
# pragma is seen by BOTH or NEITHER.
_PRAGMA_SCANNERS = [
    (convergence_theater, "# theater: ok shared-normalization regression guard"),
    (magic_depth, "# magic-depth: ok shared-normalization regression guard"),
    (subprocess_contracts, "# subprocess-contract: ok shared-normalization guard"),
    (encoding_contracts, "# encoding-locale-ok: shared-normalization regression guard"),
]
_PRAGMA_SCANNER_IDS = ["convergence_theater", "magic_depth", "subprocess_contracts", "encoding_contracts"]


@pytest.mark.parametrize("mod, pragma", _PRAGMA_SCANNERS, ids=_PRAGMA_SCANNER_IDS)
def test_indented_pragma_seen_by_both_readers(mod, pragma):
    """The shared helper normalizes indentation, and the exemption reader
    routes through it -- so an indented pragma is honored as an exemption."""
    indented = "    " + pragma
    assert mod._pragma_in_line(indented) is True
    # _has_pragma_above wants the pragma on the line directly above the
    # asserting statement (1-based lineno of that statement).
    lines = ["def test_x():", indented, "    assert foo == bar"]
    assert mod._has_pragma_above(lines, 3) is True


@pytest.mark.parametrize("mod, pragma", _PRAGMA_SCANNERS, ids=_PRAGMA_SCANNER_IDS)
def test_count_pragmas_counts_indented_pragma(mod, pragma, tmp_path: Path):
    """The cap ACCOUNTING path counts an indented pragma. Earn-the-red:
    pre-E-1 convergence_theater / magic_depth matched the raw line against
    the ^#-anchored PRAGMA_RE and counted 0 for any indented pragma."""
    block = "def test_x():\n" f"    {pragma}\n" "    assert 1 == 1\n"
    # The three scanners' count_pragmas walk different scopes: convergence
    # only tests/test_*.py; subprocess only espalier/tools/scripts (TP-152
    # E-8); magic_depth both. Drop the pragma in BOTH a tests/ and a tools/
    # file so whichever scope the scanner walks finds at least one.
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_fixture.py").write_text(block, encoding="utf-8")
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "fixture.py").write_text(block, encoding="utf-8")
    assert mod.count_pragmas(tmp_path) >= 1


@pytest.mark.parametrize("mod, pragma", _PRAGMA_SCANNERS, ids=_PRAGMA_SCANNER_IDS)
def test_count_pragmas_skips_exempt_fixture(mod, pragma, tmp_path: Path):
    """TP-152 C-4: a pragma in an EXEMPT fixture file must NOT count toward
    the cap. Earn-the-red: pre-fix count_pragmas ignored the EXEMPT_PREFIXES
    filter the detector honors, so a fixture pragma silently ate the
    MAX_PRAGMA_COUNT budget (the scope axis of the TP-150 §10.9 asymmetry)."""
    fixtures = tmp_path / "tests" / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "test_exempt.py").write_text(
        "def test_x():\n"
        f"    {pragma}\n"
        "    assert 1 == 1\n",
        encoding="utf-8",
    )
    assert mod.count_pragmas(tmp_path) == 0


def test_count_pragmas_skips_exempt_file(tmp_path: Path):
    """TP-313b ITEM F-1: a pragma in an EXEMPT_FILES-listed file must NOT count
    toward the cap. Earn-the-red: pre-fix count_pragmas/collect_pragmas filtered
    only EXEMPT_PREFIXES (not EXEMPT_FILES), so a pragma in a file scan_repo
    skips entirely still ate the MAX_PRAGMA_COUNT budget and broke the
    ``len(collect_pragmas) == count_pragmas`` invariant. (EXEMPT_FILES is
    convergence_theater-specific, so this is not parametrized.)"""
    exempt_rel = "tests/test_manifest_truth.py"
    assert exempt_rel in convergence_theater.EXEMPT_FILES  # membership sanity
    target = tmp_path / exempt_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "def test_x():\n"
        "    # theater: ok exempt-file cap regression guard\n"
        "    assert 1 == 1\n",
        encoding="utf-8",
    )
    assert convergence_theater.count_pragmas(tmp_path) == 0
    assert convergence_theater.collect_pragmas(tmp_path) == []
