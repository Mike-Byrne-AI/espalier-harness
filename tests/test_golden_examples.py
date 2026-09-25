"""Meta-test: the golden examples (examples/golden/) cannot silently rot.

The full suite does NOT collect examples/golden/ (pyproject testpaths = ["tests"]),
so this drives them explicitly and pins the README <-> files bijection, the
per-file GUARDS header, and G1's negative corpus.
"""
from __future__ import annotations


import re
import subprocess
import sys
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent.parent / "examples" / "golden"
# Files are named test_g*.py (not G*.py): pytest's default python_files pattern
# is test_*.py, so `pytest <dir>` only collects test_-prefixed files. A G*.py
# name collects only when passed as an explicit file arg — the same footgun an
# adopter would hit copying the example. The naming is part of the lesson.
GN_FILES = sorted(GOLDEN.glob("test_g*.py"))


def test_golden_dir_has_the_expected_examples():
    # Guard against a golden file silently disappearing.
    assert len(GN_FILES) >= 4, f"expected >=4 golden examples, found {GN_FILES}"


def test_golden_examples_pass_under_bare_pytest():
    # Closed-loop proof of pass-criterion 2: they actually pass under real pytest
    # (a directory invocation, exactly how an adopter runs them).
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(GOLDEN), "-q"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_every_gn_header_names_its_guard():
    for f in GN_FILES:
        head = f.read_text(encoding="utf-8")[:1200]
        assert "GUARDS:" in head, f"{f.name} header omits its GUARDS line"


def test_readme_and_files_are_bijective():
    readme = (GOLDEN / "README.md").read_text(encoding="utf-8")
    have = {f.name for f in GN_FILES}
    # forward: every golden file is documented (no orphan file)
    for name in have:
        assert name in readme, f"README does not reference {name}"
    # reverse: every filename the README cites exists (no dangling row)
    cited = set(re.findall(r"test_g\w+\.py", readme))
    assert cited <= have, f"README references missing files: {cited - have}"


def test_g1_ships_a_negative_corpus():
    body = (GOLDEN / "test_g1_earn_the_gate.py").read_text(encoding="utf-8")
    assert "MUST_NOT_FLAG" in body, "G1 lost its must-not-trip negative corpus"
