"""Pin the filesystem-contracts scanner's behavioral contract.

Five checks: earn-the-gate (every documented write shape detected in
the fixture), output-path exemption (reports/ outputs do not count as
UNPINNED), live-repo zero-UNPINNED, build_report shape, and scanner
stdlib-only self-containment.

The earn-the-gate test calls ``_scan_file`` directly against the
fixture rather than running ``scan_repo`` -- the scanner's scoped walk
covers ``espalier/`` and ``tools/`` only, so the fixture under
``tests/fixtures/`` is structurally unreachable from ``scan_repo``.

Live-repo zero-UNPINNED prevents the scanner from regressing as new
modules add structured-file writes without a FILESYSTEM_CONTRACTS
entry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from espalier.scanners import filesystem_contracts as fc


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_filesystem_stealth_positives.py"
NEG_FIXTURE_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "test_filesystem_stealth_negatives.py"
)


def test_earn_the_gate_detects_every_fixture_shape() -> None:
    """_scan_file the fixture directly (it's outside scan_repo's scope)
    and assert each documented write shape produces at least one
    finding."""
    findings = list(fc._scan_file(FIXTURE_PATH, REPO_ROOT))
    # 8 shapes: write_text/.json, write_text/.toml, write_bytes/.yaml,
    # with-open json.dump, with-open pickle.dump, atomic_write_text,
    # atomic_write_json, dump_json wrapper. TP-190: pinned to the exact count
    # (was `>= 7`, 1 shape of slack) so a single dropped shape earns the red —
    # mirrors the exact-count assert in test_scanner_subprocess_contracts.
    assert len(findings) == 8, (
        f"earn-the-gate: expected exactly 8 fixture findings (one per documented "
        f"shape), got {len(findings)}. Findings: "
        f"{[(f.severity, f.file_path_hint) for f in findings]}"
    )
    # Severity, not just count: the stealth-positives fixture is all-UNPINNED by
    # construction. A relabel-defang (severity="UNPINNED" -> "PINNED" at
    # filesystem_contracts.py:414) keeps the count at 8 but empties the UNPINNED
    # class the scanner exists to flag. Pin it so that mutation goes red here.
    sev = [f.severity for f in findings]
    assert sev.count("UNPINNED") == 8, (
        f"earn-the-gate severity: expected all 8 UNPINNED, got "
        f"{sorted((f.severity, f.file_path_hint) for f in findings)}"
    )


def test_does_not_trip_on_negatives() -> None:
    """Must-NOT-trip: _scan_file the negatives fixture directly (it's
    outside scan_repo's scope) and assert ZERO findings. Every construct
    is a clean-but-tempting near-boundary variant of a positives shape
    (read-mode open, non-structured suffix, unresolvable variable path,
    in-memory serialization) that extracts no write target. This proves
    the green earn-the-gate result is non-vacuous: an over-firing or dead
    scanner would break here."""
    findings = list(fc._scan_file(NEG_FIXTURE_PATH, REPO_ROOT))
    assert findings == [], (
        f"scanner tripped on clean negatives corpus: "
        f"{[(f.severity, f.file_path_hint) for f in findings]}"
    )


def test_output_path_exemption_skips_reports() -> None:
    """Writes to reports/ output filenames must classify as
    UNSTRUCTURED, not UNPINNED -- these are scanner outputs, not
    coordination contracts."""
    assert fc._is_output_path("reports/scan_summary.json")
    assert fc._is_output_path("*/scan_summary.json")
    assert fc._is_output_path("*/repo_fingerprint.json")
    assert not fc._is_output_path("cc/blueprints/latest.json")


def test_no_unpinned_filesystem_contracts() -> None:
    """Live-repo zero-UNPINNED: every cross-module structured-file
    write under espalier/ or tools/ must be PINNED, UNSTRUCTURED, or
    routed through a known-output path."""
    findings = fc.scan_repo(REPO_ROOT)
    unpinned = [f for f in findings if f.severity == "UNPINNED"]
    if unpinned:
        msg = "\n".join(
            f"  {f.writer_path}:{f.writer_lineno} -- {f.file_path_hint}"
            for f in unpinned
        )
        pytest.fail(
            f"{len(unpinned)} unpinned filesystem contract(s):\n{msg}\n\n"
            f"Add FILESYSTEM_CONTRACTS entry + sister schema-parity test, "
            f"or route through reports/ if this is a scanner output."
        )


def test_cc_surface_gate_not_output_exempt() -> None:
    """TP-151 D-3: cc_surface_gate.json is a hook-read coordination file (the
    SessionStart hook seeds gate_status from it), not a human-only report. It
    must NOT receive the reports/ output exemption even when its write path
    fully resolves to ``reports/cc_surface_gate.json`` — otherwise un-pinning
    it again is one path-literal away."""
    assert not fc._is_output_path("reports/cc_surface_gate.json"), (
        "cc_surface_gate.json must be carved out of the reports/ exemption "
        "(COORDINATION_FILES) so it stays a schema contract surface."
    )
    # The other reports/ outputs keep their exemption.
    assert fc._is_output_path("reports/scan_summary.json")


def test_cc_surface_gate_write_is_pinned_contract() -> None:
    """TP-151 D-3: the scanner must SEE proofs.run_cc_surface_gate's write to
    reports/cc_surface_gate.json and classify it PINNED — not leave it
    invisible (unresolvable variable path) or output-exempt. Pre-fix the write
    used a bare ``out`` variable the resolver could not trace, so the
    coordination file was a stealth contract."""
    findings = fc.scan_repo(REPO_ROOT)
    gate_findings = [
        f for f in findings
        if str(f.writer_path).replace("\\", "/") == "espalier/proofs.py"
        and "cc_surface_gate" in f.file_path_hint
    ]
    assert gate_findings, (
        "scanner sees no cc_surface_gate.json write in proofs.py — inline the "
        "path literal so _resolve_path_target can resolve it (TP-151 D-3)."
    )
    assert all(f.severity == "PINNED" for f in gate_findings), (
        "cc_surface_gate.json write not PINNED: "
        f"{[(f.severity, f.file_path_hint) for f in gate_findings]}"
    )


def test_build_report_shape() -> None:
    report = fc.build_report(REPO_ROOT)
    assert isinstance(report, dict)
    assert "count" in report
    assert "findings" in report
    assert isinstance(report["findings"], list)


def test_temporary_path_segment_anchored() -> None:
    """TP-149 (E-1): _is_temporary_path matches tmp/temp on a path SEGMENT,
    not as a bare substring. A structured path that merely CONTAINS ``tmp``
    mid-word must NOT be demoted to UNSTRUCTURED."""
    # Positive controls — genuine temporary locations stay temporary.
    assert fc._is_temporary_path("/tmp/foo.json")
    assert fc._is_temporary_path("/var/folders/ab/cd/x.json")
    assert fc._is_temporary_path("data/tmp/x.json")        # whole segment
    assert fc._is_temporary_path("temp/x.json")            # whole segment
    assert fc._is_temporary_path("tmp_path/x.json")        # segment-prefix
    assert fc._is_temporary_path("data/tmpcache.json")     # segment-prefix
    assert fc._is_temporary_path("x = tempfile.mkstemp()")  # mkstemp hint
    # The fix — mid-word "tmp" substrings are no longer demoted.
    assert not fc._is_temporary_path("reports/notmp/output.json")
    assert not fc._is_temporary_path("src/footmp/data.json")
    assert not fc._is_temporary_path("cc/blueprints/latest.json")


def test_filesystem_contracts_parity_with_pinned_tests() -> None:
    """TP-149 (E-2): every FILESYSTEM_CONTRACTS value must point at a test
    file that exists (and, if a ``::function`` suffix is present, a real
    def/class of that name). Sister to the subprocess_contracts parity fix
    (tests/test_scanner_subprocess_contracts.py); without it the registry
    can name a deleted/renamed test and the 'this write is pinned' promise
    silently goes vacuous."""
    assert fc.FILESYSTEM_CONTRACTS, "registry must not be empty (vacuous parity)"
    for descriptor, test_path in fc.FILESYSTEM_CONTRACTS.items():
        file_path, _, test_name = test_path.partition("::")
        target = REPO_ROOT / file_path
        assert target.exists(), (
            f"FILESYSTEM_CONTRACTS[{descriptor!r}] points at missing "
            f"test file: {file_path}"
        )
        if test_name:
            source = target.read_text(encoding="utf-8")
            assert (
                f"def {test_name}" in source or f"class {test_name}" in source
            ), (
                f"FILESYSTEM_CONTRACTS[{descriptor!r}] references {test_name} "
                f"but no `def {test_name}`/`class {test_name}` in {file_path}. "
                f"Update either side."
            )


def test_recursive_walk_guard_flags_bare_rglob(tmp_path) -> None:
    """TP-194 earn-the-gate: the recurrence guard flags an UNannotated bare
    ``.rglob(...)`` and a literal-recursive ``.glob("**/...")``. Drives
    ``_scan_recursive_walks_file`` directly (the live walk is scoped to
    espalier/ + tools/, so a tmp file is structurally unreachable)."""
    src = tmp_path / "probe.py"
    src.write_text(
        "from pathlib import Path\n"
        "def f(root):\n"
        "    list(root.rglob('*.py'))\n"
        "    list(root.glob('docs/**/*.md'))\n", encoding="utf-8"
    )
    findings = list(fc._scan_recursive_walks_file(src, tmp_path))
    calls = sorted(f.call for f in findings)
    assert calls == ["glob(**)", "rglob"], (
        f"guard must flag both the bare rglob and the literal recursive glob; "
        f"got {[(f.call, f.lineno) for f in findings]}"
    )


def test_recursive_walk_guard_flags_oswalk_followlinks_true(tmp_path) -> None:
    """TP-194 (adversarial MAJOR #2): the symlink-following class includes
    ``os.walk(..., followlinks=True)`` — the same idiom the fix's helper uses
    with followlinks=False. The guard must flag the True form (keyword AND 4th
    positional) and must NOT flag a bare ``os.walk`` (default followlinks=False,
    safe on every version)."""
    src = tmp_path / "walk.py"
    src.write_text(
        "import os\n"
        "def f(root):\n"
        "    list(os.walk(root, followlinks=True))\n"        # keyword True -> flagged
        "    list(os.walk(root, True, None, True))\n"        # 4th positional True -> flagged
        "    list(os.walk(root))\n"                          # default False -> safe
        "    list(os.walk(root, followlinks=False))\n", encoding="utf-8"       # explicit False -> safe
    )
    findings = list(fc._scan_recursive_walks_file(src, tmp_path))
    calls = [f.call for f in findings]
    assert calls == ["os.walk(followlinks=True)", "os.walk(followlinks=True)"], (
        f"guard must flag exactly the two followlinks=True forms and neither safe "
        f"os.walk; got {[(f.call, f.lineno) for f in findings]}"
    )


def test_recursive_walk_guard_pragma_must_be_a_comment(tmp_path) -> None:
    """TP-194 (adversarial MINOR #2): the safe-walk pragma must only count
    inside a ``#`` comment. A string literal containing the marker text must NOT
    silently suppress a finding (an autoimmune guard-blinding shape)."""
    src = tmp_path / "stringy.py"
    src.write_text(
        "from pathlib import Path\n"
        "def f(root):\n"
        "    msg = 'espalier:safe-walk-ok this is a string not a comment'\n"
        "    list(root.rglob('*.py'))\n", encoding="utf-8"
    )
    findings = list(fc._scan_recursive_walks_file(src, tmp_path))
    assert [f.call for f in findings] == ["rglob"], (
        f"a string-literal marker must NOT suppress the finding; "
        f"got {[(f.call, f.lineno) for f in findings]}"
    )


def test_recursive_walk_guard_honors_safe_walk_pragma(tmp_path) -> None:
    """Must-NOT-trip: a trailing ``# espalier:safe-walk-ok <reason>`` pragma on
    the call line suppresses the finding, and a non-recursive ``glob`` / a
    ``safe_rglob`` call are never findings. Proves the green is non-vacuous."""
    src = tmp_path / "annotated.py"
    src.write_text(
        "from pathlib import Path\n"
        "def f(root):\n"
        "    list(root.rglob('*.py'))  # espalier:safe-walk-ok self-host, never an adopter tree\n"
        "    list(root.glob('*.py'))\n"          # non-recursive glob — not in class
        "    list(safe_rglob(root, '*.py'))\n", encoding="utf-8"   # already the safe replacement
    )
    findings = list(fc._scan_recursive_walks_file(src, tmp_path))
    assert findings == [], (
        f"guard tripped on annotated/benign constructs: "
        f"{[(f.call, f.lineno) for f in findings]}"
    )


def test_live_repo_has_no_unannotated_recursive_walks() -> None:
    """TP-194 live-repo zero: every bare ``rglob`` / literal-recursive ``glob``
    under espalier/ + tools/ must be CONVERTED to safe_rglob/_safe_rglob or
    carry a ``# espalier:safe-walk-ok <reason>`` pragma. A new unannotated bare
    recursive walk earns the red here (the recurrence guard's whole purpose)."""
    walks = fc.scan_recursive_walks(REPO_ROOT)
    if walks:
        msg = "\n".join(f"  {w.path}:{w.lineno} [{w.call}]" for w in walks)
        pytest.fail(
            f"{len(walks)} unannotated bare recursive walk(s) (follow dir symlinks "
            f"on CPython <3.13 → ELOOP on an adopter loop):\n{msg}\n\n"
            f"Replace with safe_rglob (espalier/) or an inline _safe_rglob "
            f"(scanners/tools-cc), OR add `# espalier:safe-walk-ok <reason>` if it "
            f"never walks an adopter tree."
        )


def _live_overlaid_scripts() -> tuple[str, ...]:
    """The HARNESS_INCLUDE'd scripts/*.py set, derived live from the manifest."""
    from espalier import fusion_manifest as fm
    return tuple(sorted(
        p for p in fm.HARNESS_INCLUDE
        if p.startswith("scripts/") and p.endswith(".py")
    ))


def test_overlaid_scripts_match_manifest() -> None:
    """TP-195 195-C-3 drift-pin: the hardcoded RGLOB_SCAN_OVERLAID_SCRIPTS must
    equal the live set of HARNESS_INCLUDE'd scripts/*.py. The scanner cannot
    import fusion_manifest (TestScannerSelfContainment), so this test is the only
    thing keeping the two in sync — it reds the moment a new overlaid script is
    added, forcing the scanner scope to be updated alongside it."""
    assert tuple(sorted(fc.RGLOB_SCAN_OVERLAID_SCRIPTS)) == _live_overlaid_scripts()


def test_overlaid_scripts_pin_bites(monkeypatch) -> None:
    """Prove the drift-pin actually catches a new overlaid script: inject a fake
    scripts/zzz.py into HARNESS_INCLUDE and confirm the live set then diverges
    from the (unchanged) hardcoded tuple."""
    from espalier import fusion_manifest as fm
    monkeypatch.setattr(
        fm, "HARNESS_INCLUDE", fm.HARNESS_INCLUDE + ("scripts/zzz_fake.py",)
    )
    assert tuple(sorted(fc.RGLOB_SCAN_OVERLAID_SCRIPTS)) != _live_overlaid_scripts()


def test_overlaid_script_in_scanner_scope() -> None:
    """TP-195 195-C-2: a bare rglob added to an overlaid scripts/ file is now in
    scope. Synthesise the finding by pointing the scanner at a tmp tree mirroring
    one overlaid path with an unannotated bare rglob."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        target = root / fc.RGLOB_SCAN_OVERLAID_SCRIPTS[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "from pathlib import Path\n"
            "def f(p: Path):\n"
            "    return list(p.rglob('*.py'))\n",
            encoding="utf-8",
        )
        walks = fc.scan_recursive_walks(root)
        assert any(
            str(w.path).replace("\\", "/").endswith(fc.RGLOB_SCAN_OVERLAID_SCRIPTS[0])
            for w in walks
        ), f"overlaid script not scanned; got {[str(w.path) for w in walks]}"


def test_scanner_no_espalier_import() -> None:
    """Reinforce the TestScannerSelfContainment contract
    (tests/test_scanners.py:58) at the new module's location."""
    target = REPO_ROOT / "espalier" / "scanners" / "filesystem_contracts.py"
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


def test_basename_collision_emits_ambiguous_not_pinned(monkeypatch, tmp_path):
    """Forward-guard (sweep T4-B): when two FILESYSTEM_CONTRACTS share a
    basename, a `*/X` partial hint resolves to AMBIGUOUS, not a falsely PINNED
    all-clear. No live collision today — synthesize one. `_classify`'s live
    signature is `_classify(path: Path, lineno, hint, root)` (it does
    `path.relative_to(root)` first)."""
    monkeypatch.setattr(fc, "FILESYSTEM_CONTRACTS", {
        "a/dir/state.json": "tests/test_a_parity.py",
        "b/dir/state.json": "tests/test_b_parity.py",
    })
    finding = fc._classify(tmp_path / "writer.py", 7, "*/state.json", tmp_path)
    assert finding.severity == "AMBIGUOUS", (
        f"expected AMBIGUOUS on basename collision, got {finding.severity}"
    )
    assert "a/dir/state.json" in finding.explanation
    assert "b/dir/state.json" in finding.explanation
