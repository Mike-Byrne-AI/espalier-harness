"""The referents the recall engine's pointer rows name must exist, and their
operator-doc population must be the portability contract's.

A pointer that names a missing test file, a renamed constant or a reworded
SHARP_EDGES heading is a lie the next reader follows. These are pure file
reads, so they live in a `contract`-marked module: the per-batch tier a
docs-only change runs (`pytest -m contract`) is exactly the tier that must
catch a reworded heading, and the fire/silent matrices next door are
`integration` and would not run for it (failure-mode pass).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _reinject  # noqa: E402


class TestOperatorDocPopulation:
    def test_the_population_is_the_portability_contracts(self):
        """The rule restates the doc population its test scans (a hook cannot
        import tests/); pin the two together by driving the test's own list."""
        src = (REPO / "tests" / "test_portability_contract.py").read_text(encoding="utf-8")
        block = src[src.index("active_docs = ["):src.index("]", src.index("active_docs = ["))]
        paths = []
        for line in block.splitlines():
            segments = re.findall(r'"([^"]+)"', line)
            if not segments:
                continue
            if "glob(" in line:
                # a globbed directory: every member must be in the rule's population
                m = re.search(r'glob\("([^"]+)"\)', line)
                if m is None:
                    pytest.fail(f"unpinned glob member in the portability population: {line.strip()}")
                directory = "/".join(seg for seg in segments if seg != m.group(1))
                paths.append(directory + "/" + m.group(1).replace("*", "probe"))
            else:
                paths.append("/".join(segments))
        assert paths, "the portability test's population could not be read"
        for rel in paths:
            assert _reinject._OPERATOR_DOC_RE.search(rel), rel
        assert not _reinject._OPERATOR_DOC_RE.search(".claude/skills/review/SKILL.md")




class TestTheReferentsExist:
    """A pointer that names a missing test, constant or heading is a lie."""

    def test_named_files_and_symbols_exist(self):
        conftest = (REPO / "tests" / "conftest.py").read_text(encoding="utf-8")
        assert "_MARKER_RULES" in conftest and "_SLOW_FILES" in conftest
        expected = (REPO / "tests" / "_surface_expected.py").read_text(encoding="utf-8")
        assert "EXPECTED_SCRIPT_COUNT" in expected and "EXPECTED_SCRIPT_NAMES" in expected
        port = (REPO / "tests" / "test_portability_contract.py").read_text(encoding="utf-8")
        assert "def test_operator_docs_no_unix_only_default_workflows" in port
        assert (REPO / "scripts" / "generate_ledger_regions.py").is_file()
        for f in ("test_marker_taxonomy.py", "test_test_suite_contract.py"):
            assert (REPO / "tests" / f).is_file()

    def test_named_catalog_headings_exist(self):
        edges = (REPO / "docs" / "SHARP_EDGES.md").read_text(encoding="utf-8")
        for heading in (
            "## New Test Files Default to `unit` Silently",
            "## A Hand-Maintained Doc Enumeration With No Code-Pinned Parity Test Rots Silently",
            "## Two operator-doc contracts can collide on one line",
            "## Markdown Escaped Pipes Silently Drop Matrix Rows",
        ):
            assert heading in edges, heading
