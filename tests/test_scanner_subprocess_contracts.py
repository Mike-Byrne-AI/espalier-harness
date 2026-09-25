"""Pin the subprocess-contracts scanner's behavioral contract.

Six checks: earn-the-gate (every documented subprocess shape detected
in the fixture), pragma cap, _canonicalize unit, _is_os_binary unit,
live-repo zero-UNPINNED, TP-137 parity (every SUBPROCESS_CONTRACTS
value names a real test), and scanner stdlib-only self-containment.

The earn-the-gate test is the TP-105 pattern: without it, a future
scanner change that silently breaks detection passes CI. The fixture
at tests/fixtures/test_subprocess_stealth_positives.py contains one
known-positive per shape; monkeypatching EXEMPT_PREFIXES off lets the
scanner walk the fixture.

Live-repo zero-UNPINNED prevents the scanner from regressing as new
hooks or scripts add internal subprocess invocations without a
pinning entry.

TP-137 parity prevents the SUBPROCESS_CONTRACTS registry from drifting
away from the actual test functions it claims to point at. Without it,
the registry is prose-only and silently rots.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from espalier.scanners import subprocess_contracts as sc


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_subprocess_stealth_positives.py"
NEG_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_subprocess_stealth_negatives.py"


def test_canonicalize_strips_arg_values() -> None:
    assert sc._canonicalize(
        "espalier memory prune --rows ${N} --root ${root} --allow-empty"
    ) == "espalier memory prune --rows --root --allow-empty"


def test_is_os_binary_recognises_os_utilities() -> None:
    assert sc._is_os_binary("git status")
    assert sc._is_os_binary("pytest tests/")
    assert sc._is_os_binary("/usr/bin/git rev-parse")
    assert not sc._is_os_binary("espalier memory prune")
    assert not sc._is_os_binary("python tools/cc/cognitive_blueprint.py finalize")


def test_earn_the_gate_detects_every_fixture_shape() -> None:
    """_scan_file the fixture directly -- scan_repo walks production
    scope only (espalier/tools/scripts), so the fixture under tests/
    is structurally unreachable. Earn-the-gate proves the scanner sees
    each documented shape."""
    findings = list(sc._scan_file(FIXTURE_PATH, REPO_ROOT))
    # TP-174b R25: the scanner emits one finding per detected call site,
    # and the positive fixture yields exactly 9 (2 PINNED cognitive_blueprint
    # calls + 7 UNPINNED espalier calls). Assert the exact count so dropping
    # any detection branch (8 findings) goes red — the prior >=7 tolerated a
    # silent two-shape regression.
    assert len(findings) == 9, (
        f"earn-the-gate: expected exactly 9 fixture findings, got "
        f"{len(findings)}. Findings: "
        f"{[(f.severity, f.callee_descriptor) for f in findings]}"
    )
    # Severity is the load-bearing signal, not just the count: a relabel-defang
    # (severity="UNPINNED" -> "PINNED" at subprocess_contracts.py:558) keeps the
    # count at 9 but empties the UNPINNED class the scanner exists to flag. Pin
    # the distribution so that mutation goes red here.
    sev = [f.severity for f in findings]
    assert sev.count("UNPINNED") == 7 and sev.count("PINNED") == 2, (
        f"earn-the-gate severity: expected 7 UNPINNED + 2 PINNED, got "
        f"{sorted((f.severity, f.callee_descriptor) for f in findings)}"
    )


def test_does_not_trip_on_negatives() -> None:
    """Must-NOT-trip: clean-but-tempting subprocess shapes must produce
    ZERO findings. Mirrors the earn-the-gate direct-call (_scan_file on
    the fixture path) so it is immune to live-tree drift. The negatives
    corpus at tests/fixtures/test_subprocess_stealth_negatives.py holds
    OS-binary calls, non-espalier targets, and a pragma-suppressed
    dynamic argv -- each defangs one detection branch. Without this, the
    scanner over-firing on legitimate subprocess use would pass CI."""
    findings = list(sc._scan_file(NEG_FIXTURE_PATH, REPO_ROOT))
    assert findings == [], (
        f"negatives corpus must yield zero findings, got {len(findings)}: "
        f"{[(f.severity, f.callee_descriptor, f.caller_lineno) for f in findings]}"
    )


def test_pragma_count_within_cap() -> None:
    """Pragma usage across scanned scope must not exceed MAX_PRAGMA_COUNT."""
    actual = sc.count_pragmas(REPO_ROOT)
    assert actual <= sc.MAX_PRAGMA_COUNT, (
        f"Subprocess-contract pragma count ({actual}) exceeds cap "
        f"({sc.MAX_PRAGMA_COUNT}). Either close pragmas via refactor, "
        f"or raise MAX_PRAGMA_COUNT explicitly."
    )


def test_no_unpinned_subprocess_contracts() -> None:
    """Live-repo zero-UNPINNED: every internal subprocess call in
    production scope (espalier/tools/scripts) must be pinned by
    SUBPROCESS_CONTRACTS, a sister test, or a pragma."""
    findings = sc.scan_repo(REPO_ROOT)
    unpinned = [
        f for f in findings
        if f.severity in {"UNPINNED", "UNRESOLVED"}
    ]
    if unpinned:
        msg = "\n".join(
            f"  {f.severity}: {f.caller_path}:{f.caller_lineno} "
            f"-- {f.callee_descriptor}"
            for f in unpinned
        )
        pytest.fail(
            f"{len(unpinned)} unpinned/unresolved subprocess contract(s):\n"
            f"{msg}\n\nAdd SUBPROCESS_CONTRACTS entry + sister test, OR a "
            f"`# subprocess-contract: ok <reason>` pragma."
        )


def test_subprocess_contracts_parity_with_pinned_tests() -> None:
    """TP-137 parity: every SUBPROCESS_CONTRACTS value must point at a
    test function that actually exists in the referenced file. Drift in
    either direction fails this contract."""
    for descriptor, test_path in sc.SUBPROCESS_CONTRACTS.items():
        file_path, _, test_name = test_path.partition("::")
        target = REPO_ROOT / file_path
        assert target.exists(), (
            f"SUBPROCESS_CONTRACTS[{descriptor!r}] points at missing "
            f"test file: {file_path}"
        )
        source = target.read_text(encoding="utf-8")
        assert (
            f"def {test_name}" in source
            or f"class {test_name}" in source
        ), (
            f"SUBPROCESS_CONTRACTS[{descriptor!r}] references "
            f"{test_name} but no `def {test_name}` or "
            f"`class {test_name}` in {file_path}. Update either side."
        )


def test_scanner_no_espalier_import() -> None:
    """Reinforce the existing TestScannerSelfContainment contract
    (tests/test_scanners.py::TestScannerSelfContainment at line 58)
    at the new module's location."""
    target = REPO_ROOT / "espalier" / "scanners" / "subprocess_contracts.py"
    source = target.read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "from espalier" not in stripped, (
            f"Scanner violates self-containment: {stripped}"
        )
        assert "import espalier" not in stripped, (
            f"Scanner violates self-containment: {stripped}"
        )


# slow-exempt: the only `subprocess.`-needle occurrence below is a fixture
# STRING the scanner AST-parses — this test spawns no child process (in-process
# `sc._scan_file` only), so it does not belong in conftest._SLOW_FILES.
def test_sibling_function_list_binding_does_not_leak(tmp_path) -> None:
    """TP-192 W4-1: a `cmd = [...]` literal in function A must NOT resolve a
    same-named, dynamically-built `cmd` in SIBLING function B. Pre-fix the
    module-flat binding dict (last-write-wins by bare name) let B borrow A's
    literal, bypassing the UNRESOLVED safety net and contradicting the
    per-function-scope docstring."""
    src = (
        "import subprocess\n"
        "def a():\n"
        "    cmd = ['ls', '-la']\n"        # literal list in A (an os binary -> cleared)
        "    subprocess.run(cmd)\n"
        "def b(parts):\n"
        "    cmd = build(parts)\n"          # dynamic in B -> not a list literal
        "    subprocess.run(cmd)\n"
    )
    f = tmp_path / "mod.py"
    f.write_text(src, encoding="utf-8")
    findings = list(sc._scan_file(f, tmp_path))
    # B's run(cmd) (line 7) must be UNRESOLVED — it must NOT borrow A's literal.
    assert any(
        x.severity == "UNRESOLVED" and x.caller_lineno == 7 for x in findings
    ), f"B's dynamic cmd must be UNRESOLVED; got {[(x.severity, x.caller_lineno) for x in findings]}"
    # A's own run(cmd) (line 4) still resolves to the literal os binary -> cleared.
    assert not any(x.caller_lineno == 4 for x in findings), (
        "A's same-function literal cmd must still resolve and clear"
    )


def test_build_report_shape() -> None:
    """build_report must return the dict-of-counts shape cmd_scan expects."""
    report = sc.build_report(REPO_ROOT)
    assert isinstance(report, dict)
    assert "count" in report
    assert "findings" in report
    assert isinstance(report["findings"], list)
