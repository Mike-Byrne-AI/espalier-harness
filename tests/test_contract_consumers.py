"""Anti-regression: contract-consumer parity (Pack 6 Task 6-B).

Every module that classifies paths or enumerates the harness surface must
read its truth from `espalier.surface_contract`. These tests assert the
consumers still do so — a consumer that silently hardcodes state or drifts
from the contract will make a test here fail.

The invariant is simple: if the contract moves, every consumer moves with
it. If these tests fail, the consumer is lying about its source of truth.
"""
from __future__ import annotations

# slow-exempt: the only child is a local `git init` + `git add` on a tmp tree
# (tens of milliseconds), which gives the archive builder the index it now
# enumerates; no network, no interpreter spawn.
import subprocess
import zipfile
from pathlib import Path


from espalier import (
    doctor,
    harness_config,
    managed_paths,
    pre_release,
    release_pack,
    surface_contract,
)
from espalier.analyze import fingerprint_repo


REPO_ROOT = Path(__file__).resolve().parent.parent


def _surface_owned_paths(repo_root: Path) -> set[str]:
    """All paths the contract claims as part of the self-host surface."""
    surface = surface_contract.discover_self_host_surface(repo_root)
    owned: set[str] = set()
    for key in (
        *surface_contract.CLAUDE_SURFACE_KINDS,
        "hooks", "managed_reports", "required_init_files",
    ):
        owned.update(surface.get(key, []))
    return owned


class TestManagedPathsReadsFromContract:
    """managed_paths is the harness-ownership authority for the self-host repo;
    every contract-owned path must appear in its output."""

    def test_managed_paths_superset_of_contract_surface(self):
        mp = set(managed_paths.managed_paths_for_repo(REPO_ROOT))
        owned = _surface_owned_paths(REPO_ROOT)
        missing = owned - mp
        assert not missing, (
            "managed_paths is missing contract-owned surface:\n  "
            + "\n  ".join(sorted(missing))
        )

    def test_self_host_managed_paths_superset_of_contract_surface(self):
        shp = set(managed_paths.self_host_managed_paths(REPO_ROOT))
        owned = _surface_owned_paths(REPO_ROOT)
        missing = owned - shp
        assert not missing, (
            "self_host_managed_paths is missing contract-owned surface:\n  "
            + "\n  ".join(sorted(missing))
        )


class TestDoctorReadsRequiredFromContract:
    """doctor must read required-init files from surface_contract, not hardcode."""

    def test_doctor_required_includes_contract_required(self):
        """Every file the contract marks as required-for-init appears in doctor's
        required list."""
        report = doctor.run_doctor_check(REPO_ROOT)
        required = set(report["checks"]["presence"]["required"])
        for rel in surface_contract.get_required_init_files():
            assert rel in required, (
                f"doctor required-list is missing contract-required file: {rel}"
            )

    def test_doctor_follows_monkeypatched_contract(self, monkeypatch):
        """Monkeypatch the contract and confirm doctor reports what the contract says.

        If doctor hardcoded its own required list, monkeypatching the contract
        would have no effect — this test fails in that case.
        """
        sentinel = ("cc/__SENTINEL_REQUIRED__.md", "cc/LIVE_SURFACE.md")
        monkeypatch.setattr(
            surface_contract, "get_required_init_files", lambda: sentinel
        )
        report = doctor.run_doctor_check(REPO_ROOT)
        required = report["checks"]["presence"]["required"]
        assert "cc/__SENTINEL_REQUIRED__.md" in required, (
            "doctor ignored monkeypatched contract — it is not reading from "
            "surface_contract.get_required_init_files()"
        )


class TestHarnessConfigHooksFromContract:
    """Every hook script in the generated harness config plan must be canonical."""

    def test_every_plan_hook_script_is_canonical(self):
        fp = fingerprint_repo(REPO_ROOT)
        plan = harness_config.build_harness_config(fp)
        for hook in plan.hooks:
            # Formatter hooks (ruff/black) are shell COMMANDS, not script paths —
            # exempt by design (see harness_config._build_hooks: "those are shell
            # commands, not script paths, so the existing-file guarantee doesn't
            # apply"). Only the canonical tools/cc/hooks/ scripts carry an
            # on-disk-file guarantee, so scope the check to them; asserting the
            # prefix on EVERY hook would false-fail a repo whose pyproject enables
            # [tool.ruff.format]/[tool.black].
            if not hook.script.startswith("tools/cc/hooks/"):
                continue
            # Filesystem provenance, independent of the canonical constant the
            # plan is wired FROM: a wired canonical hook must resolve to a real
            # file. Asserting "script name in get_canonical_hook_scripts()" was
            # subset-by-construction — the plan can only wire names it read from
            # that same constant, so a hook renamed in _CANONICAL_HOOK_SCRIPTS +
            # CANONICAL_HOOK_WIRING but not on disk still passed. Against the
            # filesystem, a name with no backing file reds.
            script_path = REPO_ROOT / hook.script
            assert script_path.is_file(), (
                f"Plan wires a canonical hook script with no backing file under "
                f"tools/cc/hooks/: {hook.script!r} (resolved to {script_path}). "
                "A canonical hook name must name a real hook script."
            )

    def test_plan_hook_count_matches_canonical_count(self):
        fp = fingerprint_repo(REPO_ROOT)
        plan = harness_config.build_harness_config(fp)
        assert len(plan.hooks) == len(surface_contract.get_canonical_hook_scripts()), (
            f"Plan has {len(plan.hooks)} hooks but contract declares "
            f"{len(surface_contract.get_canonical_hook_scripts())} canonical"
        )


class TestReleaseAndPreReleaseParity:
    """release_pack excludes and pre_release fails for the *same* internal paths.

    Shared-outcome invariant: both consumers classify identically on the same
    input. If they ever drift, a public release could either leak internal
    material or reject a file pre_release would have accepted.
    """

    def _seed_tree(self, root: Path) -> dict[str, list[str]]:
        """Seed a minimal synthetic tree with one file per classification class."""
        files = {
            "internal": [
                "docs/internal/notes.md",
                "TASK_PACK_SAMPLE.md",
            ],
            "local_only": [
                ".claude/settings.local.json",
                "reports/analysis.json",
            ],
            "transient": [
                "__pycache__/foo.pyc",
                "dist/x.whl",
            ],
            "public": [
                "README.md",
                "LICENSE",
                "pyproject.toml",
                "espalier/x.py",
                "tools/cc/hooks/x.py",
            ],
        }
        for group in files.values():
            for rel in group:
                full = root / rel
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_text("sample\n", encoding="utf-8")
        # Git-backed and STAGED: the archive is the git index, classified, so
        # this parity holds on the branch that ships only if the samples are
        # tracked (a tracked `__pycache__/foo.pyc` is what the contract must
        # still refuse; an untracked one never reaches the builder).
        subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
        # `-f`: this machine's global git ignore excludes `**/.claude/settings.local.json`,
        # and any machine may exclude more; a fixture that lets the global excludes
        # decide what is tracked proves the contract on whatever survived them.
        # Junk must be TRACKED here, or the index never enumerates it.
        subprocess.run(["git", "-C", str(root), "add", "-A", "-f"], check=True, capture_output=True)
        assert surface_contract.tracked_paths(root) is not None
        return files

    def test_internal_classification_matches_between_consumers(self, tmp_path):
        files = self._seed_tree(tmp_path)

        gate = pre_release.run_cleanliness_gate(tmp_path)
        pre_internal = set(gate["internal_leaks"])

        out_zip = tmp_path / "dist" / "out.zip"
        summary = release_pack.create_release_zip(tmp_path, out_zip)
        pack_internal = set(summary.skipped_internal)

        # Both consumers must identify the same internal files. Strict equality
        # is the parity lock — if either diverges, release safety breaks.
        assert pre_internal == pack_internal, (
            f"pre_release and release_pack disagree on internal classification.\n"
            f"pre_release only: {pre_internal - pack_internal}\n"
            f"release_pack only: {pack_internal - pre_internal}"
        )

        # Sanity: both saw the seeded internal samples.
        for rel in files["internal"]:
            assert rel in pre_internal, f"pre_release missed internal: {rel}"

    def test_public_files_pass_both_checks(self, tmp_path):
        files = self._seed_tree(tmp_path)
        gate = pre_release.run_cleanliness_gate(tmp_path)
        out_zip = tmp_path / "dist" / "out.zip"
        summary = release_pack.create_release_zip(tmp_path, out_zip)

        leaks = set(gate["internal_leaks"])
        # Read the real archive, not the skip list. A walk-time prune removes a
        # path from BOTH, so `rel not in skipped_entries` passes for free on
        # exactly the files that silently stopped shipping -- the same
        # label-instead-of-fact defect as its sibling in
        # test_release_surface_parity.py, and the one that lets a one-line
        # widening of release_pack._is_pruned_from_walk drop 47 files from the
        # release archive with the full suite green.
        with zipfile.ZipFile(out_zip) as zf:
            members = set(zf.namelist())
        for rel in files["public"]:
            assert rel not in leaks, f"public file flagged as leak: {rel}"
            assert rel in members, (
                f"public file missing from the release zip: {rel} "
                f"(files_written={summary.files_written})"
            )

    def test_transient_files_excluded_from_zip(self, tmp_path):
        files = self._seed_tree(tmp_path)
        out_zip = tmp_path / "dist" / "out.zip"
        summary = release_pack.create_release_zip(tmp_path, out_zip)
        skipped = set(summary.skipped_entries)
        for rel in files["transient"]:
            assert rel in skipped, f"transient file not excluded: {rel}"

    def test_local_only_files_excluded_from_zip(self, tmp_path):
        files = self._seed_tree(tmp_path)
        out_zip = tmp_path / "dist" / "out.zip"
        summary = release_pack.create_release_zip(tmp_path, out_zip)
        skipped = set(summary.skipped_entries)
        for rel in files["local_only"]:
            assert rel in skipped, f"local-only file not excluded: {rel}"

    def test_contract_classifies_random_sample_consistently(self, tmp_path):
        """Sample 20 paths across classes — every consumer's classification
        matches what the contract declares directly."""
        samples = [
            ("docs/internal/x.md", "internal"),
            ("docs/session-archive.md", "internal"),
            ("TASK_PACK_1.md", "internal"),
            ("BLUEPRINT_NOTES.md", "internal"),
            (".claude/settings.local.json", "local_only"),
            ("reports/analysis.json", "local_only"),
            ("reports/cc_surface_gate.json", "local_only"),
            ("__pycache__/foo.pyc", "transient"),
            (".DS_Store", "transient"),
            ("dist/wheel.whl", "transient"),
            ("build/lib/x.py", "transient"),
            (".pytest_cache/README.md", "transient"),
            (".git/HEAD", "transient"),
            (".espalier-state/x.json", "transient"),
            ("README.md", "public"),
            ("LICENSE", "public"),
            ("pyproject.toml", "public"),
            ("espalier/x.py", "public"),
            ("tools/cc/hooks/x.py", "public"),
            ("tests/test_x.py", "public"),
        ]
        assert len(samples) == 20  # locked sample size

        for rel, expected in samples:
            if expected == "internal":
                assert surface_contract.is_internal_release_leak(rel), (
                    f"{rel}: expected internal, contract says not-internal"
                )
                assert not surface_contract.is_public_release_allowed(rel), (
                    f"{rel}: internal must not be public-release-allowed"
                )
            elif expected == "local_only":
                assert surface_contract.is_local_only(rel), (
                    f"{rel}: expected local-only"
                )
            elif expected == "transient":
                assert surface_contract.is_transient(rel), (
                    f"{rel}: expected transient"
                )
            elif expected == "public":
                assert surface_contract.is_public_release_allowed(rel), (
                    f"{rel}: expected public, contract disallows"
                )
                assert not surface_contract.is_internal_release_leak(rel), (
                    f"{rel}: public must not be an internal leak"
                )


class TestWriteGuardSurfaceParity:
    """write_guard.py duplicates surface_contract's protected-path inventory
    by design (the zero-espalier-import rule prevents importing it). This
    test enforces the invariant that the duplicated inventory remains a
    *superset* of surface_contract.get_protected_mutation_paths(). If a
    new protected file is added to surface_contract, this test fails until
    write_guard is updated to cover it."""

    def _load_write_guard(self):
        """Import write_guard.py without going through espalier.* (matches
        how Claude Code itself loads it)."""
        import sys as _sys
        from pathlib import Path as _Path
        hooks_dir = _Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
        _sys.path.insert(0, str(hooks_dir))
        try:
            import write_guard as wg
            return wg
        finally:
            _sys.path.pop(0)

    def test_write_guard_covers_all_surface_contract_protected_paths(self):
        wg = self._load_write_guard()
        contract_paths = set(surface_contract.get_protected_mutation_paths())

        # Build write_guard's effective coverage: every path in PROTECTED_FILES
        # plus every path that starts with one of PROTECTED_PREFIXES.
        wg_files = set(wg.PROTECTED_FILES)
        wg_prefixes = tuple(wg.PROTECTED_PREFIXES)

        uncovered = []
        for path in contract_paths:
            if path in wg_files:
                continue
            if any(path.startswith(p) for p in wg_prefixes):
                continue
            uncovered.append(path)

        assert not uncovered, (
            "write_guard inventory does not cover surface_contract paths:\n  "
            + "\n  ".join(uncovered)
            + "\nUpdate PROTECTED_FILES or PROTECTED_PREFIXES in "
              "tools/cc/hooks/write_guard.py."
        )

    def test_write_guard_prefixes_minimal(self):
        """Sanity: each PROTECTED_PREFIXES entry should actually be hit by at
        least one surface_contract path. Catches dead prefixes if surface_contract
        ever drops a category."""
        wg = self._load_write_guard()
        contract_paths = set(surface_contract.get_protected_mutation_paths())
        contract_prefixes = set(surface_contract.get_protected_mutation_prefixes())

        for prefix in wg.PROTECTED_PREFIXES:
            # Either some contract file lives under it, or surface_contract
            # itself declares the prefix as protected.
            assert (
                prefix in contract_prefixes
                or any(p.startswith(prefix) for p in contract_paths)
            ), (
                f"PROTECTED_PREFIXES entry {prefix!r} has no corresponding "
                "surface_contract coverage — drift or dead prefix."
            )

    def test_surface_contract_covers_all_hook_exact_files(self):
        """TP-151 151-B (W22): reverse-parity. Every exact file the hook
        (_protected_zones.PROTECTED_FILES, re-exported as wg.PROTECTED_FILES)
        guards must ALSO be an exact entry in the engine SoT
        (get_protected_mutation_paths). The forward test above pins
        write_guard ⊇ engine; this pins engine ⊇ hook so the two SoTs cannot
        diverge in either direction. FAILS pre-fix: the hook guarded
        ``.espalier/freshness.json`` but the engine omitted it."""
        wg = self._load_write_guard()
        engine_paths = set(surface_contract.get_protected_mutation_paths())
        hook_exact = set(wg.PROTECTED_FILES)

        missing = sorted(hook_exact - engine_paths)
        assert not missing, (
            "engine get_protected_mutation_paths() is missing exact files that "
            "the hook _protected_zones.PROTECTED_FILES guards:\n  "
            + "\n  ".join(missing)
            + "\nAdd them to surface_contract._PROTECTED_MUTATION_NONHOOK (non-hook) "
            "or the managed_inventory hook SoT (tools/cc/hooks/ files derive from it)."
        )


class TestProtectedListsDeriveFromInventory:
    """TP-204f 2-B: the tools/cc/hooks/ portion of the protected exact-file
    lists is DERIVED from managed_inventory's entry+helper SoT. Pin that the
    derivation reproduces the hand-list it replaced, and that the only
    mutation/integrity divergence is the documented _denial_reasons.py omission."""

    # Golden: the tools/cc/hooks/ files that MUST stay under integrity
    # coverage. Hand-maintained HERE, deliberately NOT derived from
    # managed_inventory — it is the independent-provenance operand for
    # ``integ_hooks`` below, which derives from the same entry+helper SoT the
    # manifest-coverage list does. A prior version compared that coverage list
    # to ``managed_inventory`` directly (A == A): dropping a hook from the SoT
    # shrank BOTH sides and stayed green while the hook silently fell out of
    # integrity coverage. Against this golden, a dropped hook diverges and reds.
    # When you legitimately add or retire a hook, update this literal in the
    # SAME reviewed commit — that update IS the review gate.
    _INTEGRITY_HOOK_GOLDEN = frozenset({
        "tools/cc/hooks/_bash_patterns.py",
        "tools/cc/hooks/_born_weak.py",
        "tools/cc/hooks/_denial_reasons.py",
        "tools/cc/hooks/_explain_path.py",
        "tools/cc/hooks/_hook_contract.py",
        "tools/cc/hooks/_hook_utils.py",
        "tools/cc/hooks/_integrity.py",
        "tools/cc/hooks/_maintenance_mode.py",
        "tools/cc/hooks/_protected_zones.py",
        "tools/cc/hooks/_recall.py",
        "tools/cc/hooks/_reinject.py",
        "tools/cc/hooks/_self_host_fingerprint.py",
        "tools/cc/hooks/_speedbump.py",
        "tools/cc/hooks/config_guard.py",
        "tools/cc/hooks/context_reinject_failure.py",
        "tools/cc/hooks/plan_guard.py",
        "tools/cc/hooks/post_compact.py",
        "tools/cc/hooks/post_write_check.py",
        "tools/cc/hooks/reflect_trigger.py",
        "tools/cc/hooks/session_start.py",
        "tools/cc/hooks/stop_gate.py",
        "tools/cc/hooks/subagent_start.py",
        "tools/cc/hooks/subagent_stop.py",
        "tools/cc/hooks/task_router.py",
        "tools/cc/hooks/write_guard.py",
    })

    def test_integrity_hook_portion_equals_inventory(self):
        integ_hooks = {
            p for p in surface_contract.get_protected_integrity_paths()
            if p.startswith("tools/cc/hooks/")
        }
        assert integ_hooks == self._INTEGRITY_HOOK_GOLDEN, (
            "The tools/cc/hooks/ portion of the integrity-protected paths drifted "
            "from the hand-maintained golden.\n"
            f"  in coverage, not in golden: {sorted(integ_hooks - self._INTEGRITY_HOOK_GOLDEN)}\n"
            f"  in golden, not in coverage: {sorted(self._INTEGRITY_HOOK_GOLDEN - integ_hooks)}\n"
            "If you added/retired a hook, update _INTEGRITY_HOOK_GOLDEN in this "
            "same commit — it is the reviewed artifact that keeps a dropped hook "
            "from silently falling out of integrity coverage."
        )

    def test_mutation_omits_only_denial_reasons(self):
        integ_hooks = {
            p for p in surface_contract.get_protected_integrity_paths()
            if p.startswith("tools/cc/hooks/")
        }
        mut_hooks = {
            p for p in surface_contract.get_protected_mutation_paths()
            if p.startswith("tools/cc/hooks/")
        }
        assert integ_hooks - mut_hooks == {"tools/cc/hooks/_denial_reasons.py"}
        assert mut_hooks - integ_hooks == set()
