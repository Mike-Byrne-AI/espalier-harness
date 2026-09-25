"""Tests for espalier/self_hosting.py.

Anti-regression: exact self-host shape invariants (Pack 6 Task 6-A).

The shape assertions in TestSelfHostShapeInvariants are brittle by design.
They fail when the real surface changes. When they fail:

1. Update the count in this test.
2. Update operator docs (cc/LIVE_SURFACE.md, docs/CHEAT-SHEET.md, docs/TASK_RECIPES.md)
   to reflect the new surface.
3. Regenerate reports/harness_config.json (espalier diff should flag it).
4. Run `espalier integrity refresh` to update .espalier/integrity.json.

The brittleness is the value — these steps would otherwise be forgotten.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from espalier import self_hosting as sh
from espalier import surface_contract
from espalier.self_hosting import main, run_self_host_check


REPO_ROOT = Path(__file__).parent.parent


class TestRunSelfHostCheck:
    def test_returns_dict(self):
        result = run_self_host_check(REPO_ROOT)
        assert isinstance(result, dict)

    @pytest.mark.parametrize(
        "key, expected_type",
        [
            ("repo_root", str),
            ("profiles", list),
            ("surface_gate_status", str),
            ("gate_details", dict),
        ],
    )
    def test_required_field_present_with_expected_type(self, key, expected_type):
        """Every required field is present and carries the documented type."""
        result = run_self_host_check(REPO_ROOT)
        assert key in result, f"required field {key!r} missing"
        assert isinstance(result[key], expected_type), (
            f"field {key!r} expected {expected_type.__name__}, got "
            f"{type(result[key]).__name__}"
        )

    def test_profiles_non_empty_and_all_strings(self):
        """TP-174b R17: ``profiles`` must be a non-empty list of strings on
        the live repo. The isinstance-only parametrize above passes on an
        empty/garbage list, silently disarming profile detection. Stay
        value-agnostic (so the R16 languages→profiles swap doesn't break
        this) — only assert non-empty + all-string."""
        result = run_self_host_check(REPO_ROOT)
        profiles = result["profiles"]
        assert isinstance(profiles, list) and profiles, (
            f"expected a non-empty profiles list on the live repo, got {profiles!r}"
        )
        assert all(isinstance(p, str) for p in profiles), (
            f"every profile must be a string: {profiles!r}"
        )

    def test_profiles_key_emits_profiles_not_languages(self):
        """TP-174b R16: the 'profiles' key must carry fp.profiles, not the
        raw fp.languages list (the two differ — languages=['python', ...]
        vs profiles=['python_library', ...])."""
        from espalier.analyze import fingerprint_repo
        result = run_self_host_check(REPO_ROOT)
        fp = fingerprint_repo(REPO_ROOT)
        assert result["profiles"] == list(fp.profiles), (
            f"profiles key emitted {result['profiles']!r}, "
            f"expected fp.profiles {list(fp.profiles)!r}"
        )

    def test_repo_root_value_is_absolute(self):
        result = run_self_host_check(REPO_ROOT)
        assert Path(result["repo_root"]).is_absolute()

    def test_resolves_relative_path(self, monkeypatch):
        # Pass a genuinely RELATIVE path so the relative→absolute resolve
        # (self_hosting.py:42, repo_root = repo_root.resolve()) is actually
        # exercised. The old test passed an already-absolute REPO_ROOT, so
        # deleting that resolve() stayed green.
        monkeypatch.chdir(REPO_ROOT)
        result = run_self_host_check(Path("."))
        assert Path(result["repo_root"]).is_absolute()
        assert result["repo_root"] == str(REPO_ROOT.resolve())

    def test_uninitialized_is_not_a_failure_and_keeps_its_reason(self):
        """`run_self_host_check` returns `uninitialized` as a deliberate
        structured first-run hint carrying the one actionable sentence. The
        single owner must classify it as a NON-failure, and consumers must be
        able to recover that sentence -- collapsing it to a generic failure
        string is how an operator lost the only instruction they needed.
        """
        report = {
            "surface_gate_status": "uninitialized",
            "gate_details": {
                "status": "uninitialized",
                "primary_reason": "repo has not been initialized; run `espalier init .` first",
            },
        }
        assert sh.gate_failure_reason(report) is None

    def test_real_failure_carries_primary_reason_when_present(self):
        report = {
            "surface_gate_status": "fail",
            "gate_details": {"primary_reason": "3 manifest entries missing"},
        }
        reason = sh.gate_failure_reason(report)
        assert reason is not None
        assert "3 manifest entries missing" in reason, (
            f"the producer's actionable sentence was dropped: {reason!r}"
        )

    def test_real_failure_without_a_reason_still_names_the_status(self):
        reason = sh.gate_failure_reason({"surface_gate_status": "fail"})
        assert reason is not None and "fail" in reason

    def test_every_rc_zero_status_is_a_declared_non_failure(self):
        """DERIVED, not restated: the statuses `main`/`cmd_self_host` return 0 for
        must be exactly the set the shared owner calls non-failures. Four
        consumers used to carry four hand-written accept-sets; this pins them to
        one so they cannot drift apart again."""
        for status in ("pass", "uninitialized", "skipped_release_export"):
            assert status in sh.GATE_STATUS_NON_FAILURES, (
                f"{status!r} returns rc=0 to the operator but is not in the "
                "shared non-failure set"
            )

    def test_pre_release_does_not_fail_an_uninitialized_tree(self, tmp_path, monkeypatch):
        """CONSUMER pin. The owner-level tests above pass whether or not
        `pre_release` actually reads the shared accept-set -- measured: reverting
        it to `!= "pass"` left the whole suite green. So pin the consumer's
        BEHAVIOUR, not just the helper it is supposed to call.
        """
        from espalier import pre_release as pr
        from espalier import self_hosting as _sh

        monkeypatch.setattr(_sh, "run_self_host_check", lambda root: {
            "surface_gate_status": "uninitialized",
            "gate_details": {
                "status": "uninitialized",
                "primary_reason": "run `espalier init .` first",
            },
        })
        monkeypatch.setattr(pr, "_run_command", lambda command, cwd, *, timeout_seconds=None: {
            "command": " ".join(command), "returncode": 0, "stdout": "",
            "stderr": "", "timed_out": False, "timeout_seconds": timeout_seconds,
        })
        report = pr.run_pre_release_check(
            tmp_path, skip_tests=True, skip_pack=True, skip_parity=True
        )
        self_host_failures = [f for f in report["failures"] if "self-host" in f.lower()]
        assert not self_host_failures, (
            "an uninitialized tree was reported as a self-host FAILURE; the "
            f"deliberate first-run hint was collapsed: {self_host_failures}"
        )
        assert "init" in report["self_host"].get("reason", ""), (
            "the producer's actionable sentence never reached the report: "
            f"{report['self_host']!r}"
        )

    def test_the_accept_set_has_exactly_one_home(self):
        """CLASS pin. Four modules each carried their own `surface_gate_status`
        accept-set and two of them disagreed with the CLI. Reading the value to
        REPORT it is fine; COMPARING it anywhere but the owner re-creates the
        divergence this fix collapsed.

        AST, not a line-local regex. The pre-fix `cli.cmd_self_host` and
        `self_hosting.main` both spelled the accept-set across TWO statements
        (`status = report.get("surface_gate_status")` then `if status == "pass"`),
        which a single-line pattern cannot see -- so the guard would have caught
        2 of the 4 sites its own message promises. Bind the read, then look for
        any comparison of what it bound.

        SCOPE. `espalier/*.py` PLUS this test module, and the second half was
        added the hard way. The population was `espalier/*.py` alone, so the
        guard could not see a fork inside `tests/` -- and on 2026-08-14 the fifth
        accept-set turned out to be `test_main_zero_on_passing_gate`, forty lines
        below this one, in the guard's own file. A class pin that cannot inspect
        the module it lives in has a blind spot shaped exactly like itself.

        Still a real limit worth naming: `tools/cc/session_resume.py::
        assess_repo_state` carries a reader (`surface_gate_status.lower() !=
        "pass"`) which structurally CANNOT import this owner -- `tools/cc/` has
        zero espalier imports by contract. Not a live divergence today
        (`run_cc_surface_gate` emits only pass/fail), but it is the one consumer
        this guard can never cover.
        """
        import ast

        def _reads_the_status(node: ast.AST) -> bool:
            """`x.get("surface_gate_status")` or `x["surface_gate_status"]`."""
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Attribute) and fn.attr == "get" and node.args:
                    arg = node.args[0]
                    return (
                        isinstance(arg, ast.Constant)
                        and arg.value == "surface_gate_status"
                    )
            if isinstance(node, ast.Subscript):
                sl = node.slice
                return isinstance(sl, ast.Constant) and sl.value == "surface_gate_status"
            return False

        owner = Path(sh.__file__).resolve()
        # This module is in the population deliberately -- see SCOPE above; the
        # fork that motivated the widening lived here, not in espalier/.
        population = [*sorted(owner.parent.glob("*.py")), Path(__file__).resolve()]
        offenders: list[str] = []
        for path in population:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            # In the owner file the ONE sanctioned comparison lives inside
            # gate_failure_reason; everything else, including main(), is a
            # consumer and must route through it.
            sanctioned: set[int] = set()
            if path.resolve() == owner:
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.FunctionDef)
                        and node.name == "gate_failure_reason"
                    ):
                        sanctioned = set(
                            range(node.lineno, (node.end_lineno or node.lineno) + 1)
                        )
            if path.resolve() == Path(__file__).resolve():
                # In THIS module, a comparison inside an `assert` is a test
                # pinning one known status for one constructed input -- the job
                # of a test, not a policy. The fork that motivated widening the
                # population was an ASSIGNMENT deriving pass/fail from an
                # arbitrary live status (`expected_rc = 0 if ... == "pass"
                # else 1`), and that is what must stay caught.
                #
                # Calibrated, not assumed: widening without this discriminator
                # flagged 4 sites (:270, :454, :484, :568), all of them
                # legitimate expected-value assertions. A class pin that reds on
                # correct code is one that gets switched off.
                for node in ast.walk(tree):
                    if isinstance(node, ast.Assert):
                        sanctioned.update(
                            range(node.lineno, (node.end_lineno or node.lineno) + 1)
                        )
            bound: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and _reads_the_status(node.value):
                    bound.update(
                        t.id for t in node.targets if isinstance(t, ast.Name)
                    )
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare) or node.lineno in sanctioned:
                    continue
                for operand in (node.left, *node.comparators):
                    if _reads_the_status(operand) or (
                        isinstance(operand, ast.Name) and operand.id in bound
                    ):
                        offenders.append(
                            f"{path.name}:{node.lineno}: compares surface_gate_status"
                        )
                        break
        assert not offenders, (
            "a second accept-set for surface_gate_status appeared; route it "
            "through self_hosting.gate_failure_reason instead:\n  "
            + "\n  ".join(offenders)
        )

    def test_surface_gate_status_not_unknown_on_live_repo(self):
        result = run_self_host_check(REPO_ROOT)
        # The degradation this guards is the "unknown" fallback
        # (self_hosting.py:72, str(gate.get("status", "unknown"))). The old
        # `!= ""` could not discriminate that — the SUT never emits "".
        #
        # Assert exactly that, not `== "pass"`. `== "pass"` is strictly stronger
        # than the named degradation and rejects every legitimate stand-down, so
        # it reddened on an export and was briefly registered as a full-tree
        # invariant (2026-08-14) — silencing this guard in the ARTIFACT, where
        # `espalier/self_hosting.py` ships and the fallback can still fire. The
        # weaker assertion is the correct one: it holds on the dev tree, a fresh
        # clone AND an export, so the guard runs everywhere the code does.
        assert result["surface_gate_status"] != "unknown"


class TestMainExitCode:
    def test_main_returns_int(self):
        # main() should return 0 or 1, never raise
        ret = main([str(REPO_ROOT)])
        assert isinstance(ret, int)
        assert ret in (0, 1)

    def test_main_zero_on_passing_gate(self):
        """`main` exits 0 on a non-failing gate -- routed through the SAME
        classifier `main` uses, not a private re-statement of it.

        This computed `0 if status == "pass" else 1`, which is a FIFTH accept-set
        (see `GATE_STATUS_NON_FAILURES`, whose docstring says "Single owner ...
        was read by four independently-written accept-sets"). It was narrower
        than the shipped policy by three statuses, so it disagreed with `main`
        on every tree where the gate legitimately stands down.

        The 2026-08-14 export run CAUGHT that: `main` returned 0 for
        `skipped_release_export` and this computed 1. The first response was to
        register the test as a full-tree invariant -- silencing a true positive.
        The invariant ("main exits 0 when the gate is not a failure") holds
        everywhere; only this test's private definition of "not a failure" was
        dev-tree-specific. Found by the adversarial pass, not by the suite.
        """
        result = run_self_host_check(REPO_ROOT)
        expected_rc = 0 if sh.gate_failure_reason(result) is None else 1
        actual_rc = main([str(REPO_ROOT)])
        assert actual_rc == expected_rc

    def test_main_prints_json_to_stdout(self, capsys):
        main([str(REPO_ROOT)])
        captured = capsys.readouterr()
        # Output must be valid JSON
        parsed = json.loads(captured.out)
        assert isinstance(parsed, dict)

    def test_main_json_contains_expected_keys(self, capsys):
        main([str(REPO_ROOT)])
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        for key in ("repo_root", "profiles", "surface_gate_status", "gate_details"):
            assert key in parsed


# ---------------------------------------------------------------------------
# Task 6-A — Self-host shape invariants (anti-regression, brittle by design)
# ---------------------------------------------------------------------------

# Surface cardinalities are sourced from tests/_surface_expected.py per
# TP-11 Task 11-B — single source of truth; bump there, not here.
from tests._surface_expected import (
    EXPECTED_AGENT_COUNT_MIN,
    EXPECTED_COMMAND_COUNT,
    EXPECTED_HOOK_COUNT,
    EXPECTED_UNIVERSAL_AGENTS,
)

EXPECTED_HOOK_PATHS = {
    "tools/cc/hooks/session_start.py",
    "tools/cc/hooks/task_router.py",
    "tools/cc/hooks/plan_guard.py",
    "tools/cc/hooks/write_guard.py",
    "tools/cc/hooks/config_guard.py",
    "tools/cc/hooks/post_write_check.py",
    "tools/cc/hooks/reflect_trigger.py",
    "tools/cc/hooks/stop_gate.py",
    "tools/cc/hooks/subagent_stop.py",  # TP-40
    "tools/cc/hooks/post_compact.py",
    "tools/cc/hooks/subagent_start.py",  # TP-163
    "tools/cc/hooks/context_reinject_failure.py",  # TP-163
}


class TestSelfHostShapeInvariants:
    """Anti-regression: exact shape of the live self-host surface."""

    def test_command_count_is_exact(self):
        commands = surface_contract.discover_installed_commands(REPO_ROOT)
        assert len(commands) == EXPECTED_COMMAND_COUNT, (
            f"Expected {EXPECTED_COMMAND_COUNT} commands, got {len(commands)}. "
            "Update count + operator docs + harness_config.json + integrity manifest."
        )

    def test_agent_count_meets_universal_floor(self):
        """At least the universal canonical agents must be deployed.

        Profile-aware OPTIONAL_AGENTS layer on top per fingerprint match,
        so the assertion is `>=` not `==`. Per TP-13-B deploy-all
        semantics + TP-11 Task 11-B SSoT extraction.
        """
        agents = surface_contract.discover_installed_agents(REPO_ROOT)
        assert len(agents) >= EXPECTED_AGENT_COUNT_MIN, (
            f"Expected at least {EXPECTED_AGENT_COUNT_MIN} agents (universal floor), "
            f"got {len(agents)}."
        )
        deployed_names = {Path(a).stem for a in agents}
        missing = EXPECTED_UNIVERSAL_AGENTS - deployed_names
        assert not missing, f"Missing universal agents: {missing}"

    def test_hook_count_is_exact(self, initialized_repo_root):
        hooks = surface_contract.discover_wired_hooks(initialized_repo_root)
        assert len(hooks) == EXPECTED_HOOK_COUNT, (
            f"Expected {EXPECTED_HOOK_COUNT} hooks, got {len(hooks)}. "
            "Update count + operator docs + harness_config.json + integrity manifest."
        )

    def test_hook_set_matches_canonical_paths(self, initialized_repo_root):
        """Exact set of wired hook paths — no additions, no removals, no renames."""
        hooks = set(surface_contract.discover_wired_hooks(initialized_repo_root))
        # Normalize for windows path separators — contract already returns posix
        assert hooks == EXPECTED_HOOK_PATHS, (
            f"Wired hook set drifted.\n"
            f"Missing: {EXPECTED_HOOK_PATHS - hooks}\n"
            f"Unexpected: {hooks - EXPECTED_HOOK_PATHS}"
        )

    def test_phantom_convention_monitor_agent_absent(self):
        """Pack 2 removed .claude/agents/convention-monitor.md — must stay gone."""
        agents = surface_contract.discover_installed_agents(REPO_ROOT)
        for agent_path in agents:
            assert "convention-monitor" not in agent_path, (
                f"Phantom agent convention-monitor reappeared at {agent_path}"
            )

    def test_phantom_diff_review_command_absent(self):
        """Pack 2 removed /diff-review — must stay gone."""
        commands = surface_contract.discover_installed_commands(REPO_ROOT)
        for cmd_path in commands:
            assert "diff-review" not in cmd_path, (
                f"Phantom command /diff-review reappeared at {cmd_path}"
            )


# ---------------------------------------------------------------------------
# TP-RELEASE-18 — Mode awareness
# ---------------------------------------------------------------------------


class TestSelfHostModeAwareness:
    """run_self_host_check must respect the mode argument."""

    def test_signature_accepts_mode_kwonly(self):
        import inspect
        sig = inspect.signature(run_self_host_check)
        assert "mode" in sig.parameters
        assert sig.parameters["mode"].kind.name == "KEYWORD_ONLY"
        assert sig.parameters["mode"].default == "auto"

    def test_source_checkout_mode_does_not_require_runtime_files(self, tmp_path):
        """Source-checkout mode passes on a tree with committed surface
        but no init-generated runtime files."""
        import shutil

        # Create a fresh-archive-like target by copying the repo root
        # minus runtime markers.
        target = tmp_path / "fresh"
        shutil.copytree(
            REPO_ROOT,
            target,
            ignore=shutil.ignore_patterns(
                ".git",
                ".espalier",
                "reports",
                "__pycache__",
                ".pytest_cache",
                ".mypy_cache",
                ".ruff_cache",
                "dist",
                "build",
                "*.egg-info",
                ".venv",
                "venv",
            ),
        )
        # Remove the runtime settings.json if it was copied
        settings = target / ".claude" / "settings.json"
        if settings.exists():
            settings.unlink()

        report = run_self_host_check(target, mode="source-checkout")
        assert report["mode_resolved"] == "source_checkout"
        assert report["surface_gate_status"] == "pass", (
            f"source-checkout failed: {report['gate_details'].get('findings', [])}"
        )

    def test_a_latin1_manifest_is_read_not_a_traceback(self, tmp_path):
        """Ledger DEF-829: cc/PACK_MANIFEST.txt re-saved in a Windows code page.
        The reader had no handler at all and doctor died with a
        UnicodeDecodeError on a tree that was otherwise fine. The entries are
        names: read with a replacement character, the stray one is reported
        missing, which is the honest answer."""
        import shutil

        target = tmp_path / "cp1252"
        shutil.copytree(
            REPO_ROOT,
            target,
            ignore=shutil.ignore_patterns(
                ".git", ".espalier", "reports", "__pycache__",
                ".pytest_cache", ".mypy_cache", ".ruff_cache",
                "dist", "build", "*.egg-info", ".venv", "venv",
            ),
        )
        manifest = target / "cc" / "PACK_MANIFEST.txt"
        manifest.write_bytes(manifest.read_bytes() + b"docs/caf\xe9.md\n")

        report = run_self_host_check(target, mode="source-checkout")
        assert "manifest entry missing from source: docs/caf\ufffd.md" in report["gate_details"]["findings"]

    def test_source_checkout_mode_detects_missing_manifest_entry(self, tmp_path):
        """Source-checkout mode reports missing manifest entries.

        TP-31 removed plan-derived agent deploy and rich agents from the
        managed inventory; the test now deletes a managed hook script
        (still in the manifest) instead of an agent file (no longer
        promised by the manifest).
        """
        import shutil

        target = tmp_path / "broken"
        shutil.copytree(
            REPO_ROOT,
            target,
            ignore=shutil.ignore_patterns(
                ".git", ".espalier", "reports", "__pycache__",
                ".pytest_cache", ".mypy_cache", ".ruff_cache",
                "dist", "build", "*.egg-info", ".venv", "venv",
            ),
        )
        # Delete a managed hook script that the manifest promises
        deleted = target / "tools" / "cc" / "hooks" / "write_guard.py"
        assert deleted.exists(), "test setup: write_guard.py expected in copied tree"
        deleted.unlink()

        report = run_self_host_check(target, mode="source-checkout")
        assert report["surface_gate_status"] == "fail"
        findings = report["gate_details"]["findings"]
        assert any("write_guard" in f for f in findings), (
            f"expected finding about missing write_guard: {findings}"
        )

    def test_source_checkout_stands_down_on_release_export(self, tmp_path):
        """A source-release export ships the self-host layout but prunes the
        export-ignore'd dev content (ESPALIER_MEMORY.md, docs/* sentinels). The
        source-checkout gate must detect that via is_release_export and stand
        down (`skipped_release_export`, exit 0) instead of emitting false
        `manifest entry missing from source` findings.

        Earn-the-red: without the is_release_export guard the gate reports
        `fail` with a `manifest entry missing from source: ESPALIER_MEMORY.md` finding
        (the export pruned it) — the category error the release matrix's
        stage-02 `self-host --mode source-checkout` hit on the extracted
        archive.
        """
        import shutil

        from espalier import surface_contract
        from espalier.self_hosting import main as self_host_main

        target = tmp_path / "export"
        # Prune the tracked export-ignore'd plain-file sentinels so the copy is a
        # faithful shipping export (is_release_export -> True).
        #
        # This fixture is a SETUP step, not the alarm. It derives its prune set
        # from .gitattributes using is_release_export's own predicate, which
        # makes the assert below true by construction -- deliberately. A 2026-08-13
        # attempt to treat the old five-basename hand-list as the sister-site
        # drift alarm was wrong in BOTH directions: as a hand-list it was the
        # §C1 declared-population shape, and as a derivation it is the closed-loop
        # trap (docs/sharp-edges/closed-loop-verification-trap.md) -- oracle and
        # subject reading one source. The alarm belongs somewhere the subject does
        # not reach, so it lives in test_git_archive_parity.py::
        # test_every_plain_file_export_ignore_is_registered, which binds
        # .gitattributes against an INDEPENDENTLY hand-kept registry. §C1 tier 2:
        # two independently-written sides, not one side twice.
        #
        # Keyed on REPO-RELATIVE PATH, never basename: shutil.ignore_patterns
        # matches a bare name at every depth, so a future entry like
        # `/task-packs/CLAUDE.md` would silently prune all twelve folder routers
        # and leave the fixture a hollow tree that still passes.
        sentinel_rels = {
            pat for pat in surface_contract.export_ignore_patterns(REPO_ROOT)
            if not pat.endswith("/") and not any(ch in pat for ch in "*?[")
        }
        assert sentinel_rels, (
            "test setup: .gitattributes yielded no plain-file export-ignore "
            "sentinels, so this fixture would prove nothing"
        )
        scaffold = shutil.ignore_patterns(
            ".git", ".espalier", "reports", "__pycache__",
            ".pytest_cache", ".mypy_cache", ".ruff_cache",
            "dist", "build", "*.egg-info", ".venv", "venv",
        )

        def _ignore(dirpath, names):
            # NO .resolve(): copytree builds every child path by joining onto the
            # `src` it was handed, so relative_to(REPO_ROOT) cannot raise, and a
            # symlinked directory keeps its LINK path -- which is the path the
            # sentinel is declared under. Resolving first made a symlink pointing
            # outside the repo raise a bare `is not in the subpath of` ValueError
            # on a test about release exports, and made an in-repo symlink resolve
            # to the target's prefix so a declared sentinel silently went unpruned.
            rel_dir = Path(dirpath).relative_to(REPO_ROOT).as_posix()
            prefix = "" if rel_dir == "." else f"{rel_dir}/"
            sentinels = {n for n in names if f"{prefix}{n}" in sentinel_rels}
            return sentinels | set(scaffold(dirpath, names))

        shutil.copytree(REPO_ROOT, target, ignore=_ignore)
        settings = target / ".claude" / "settings.json"
        if settings.exists():
            settings.unlink()

        assert surface_contract.is_release_export(target), (
            "test setup: synthesized tree must be detected as a release export "
            "(self-host layout present, every plain-file sentinel pruned)"
        )

        report = run_self_host_check(target, mode="source-checkout")
        assert report["mode_resolved"] == "source_checkout"
        assert report["surface_gate_status"] == "skipped_release_export", (
            f"expected export stand-down, got "
            f"{report['surface_gate_status']!r}: "
            f"{report['gate_details'].get('findings', [])}"
        )
        assert report["gate_details"]["findings"] == []
        # The stand-down is a success exit, mirroring 'uninitialized'.
        assert self_host_main([str(target), "--mode", "source-checkout"]) == 0

    def test_mode_auto_resolves_for_self_host_repo(self):
        """On the live self-host repo with runtime files present, auto
        mode resolves to initialized_self_host."""
        # The live repo has reports/ and .espalier/, so it resolves
        # to an initialized state. Auto mode follows.
        report = run_self_host_check(REPO_ROOT, mode="auto")
        assert report["mode_requested"] == "auto"
        assert report["mode_resolved"] in (
            "initialized_self_host",
            "source_checkout",  # if a fresh checkout, no reports yet
        )


class TestTheGateIsNamedForTheTreeItRanOn:
    """DEF-785 (TP-449 Tier 2, 2026-09-12): `doctor` on a consumer tree
    missing one cc/ doc listed `self-host surface gate: fail` beside the
    presence failure and counted two errors for one. The status-only form
    now names the gate by the report's resolved mode, and a failing
    initialized report forwards its first error-level finding; doctor's own
    stand-down on a missing surface is pinned in tests/test_doctor.py."""

    @pytest.mark.parametrize("mode", ["initialized_consumer_repo", "source_checkout", "initialized_self_host"])
    def test_a_report_off_the_self_host_repo_names_the_managed_surface_gate(self, mode):
        """The name follows the TREE, not the mode: an adopter's fresh clone of
        a repo that commits its surface is a source_checkout too."""
        reason = sh.gate_failure_reason({
            "surface_gate_status": "fail", "mode_resolved": mode, "self_host_repo": False,
        })
        assert reason is not None and reason.startswith("managed surface gate"), reason
        assert "self-host" not in reason, reason

    @pytest.mark.parametrize("flag", [True, None])
    def test_the_self_host_repo_and_a_hand_built_report_keep_the_self_host_name(self, flag):
        report = {"surface_gate_status": "fail", "mode_resolved": "source_checkout"}
        if flag is not None:
            report["self_host_repo"] = flag
        reason = sh.gate_failure_reason(report)
        assert reason is not None and reason.startswith("self-host surface gate"), reason

    def test_the_producer_records_the_self_host_fact(self, tmp_path, monkeypatch):
        import espalier.repo_mode as rm
        monkeypatch.setattr(rm, "resolve_mode", lambda mode, root: rm.REPO_MODE_INITIALIZED_CONSUMER)
        monkeypatch.setattr(sh, "run_cc_surface_gate", lambda root: {"status": "pass", "findings": []})
        assert sh.run_self_host_check(tmp_path)["self_host_repo"] is False
        assert sh.run_self_host_check(REPO_ROOT, mode="source-checkout")["self_host_repo"] is True

    def test_a_failing_initialized_report_forwards_its_first_error_finding(self, tmp_path, monkeypatch):
        import espalier.repo_mode as rm
        monkeypatch.setattr(rm, "resolve_mode", lambda mode, root: rm.REPO_MODE_INITIALIZED_CONSUMER)
        monkeypatch.setattr(sh, "run_cc_surface_gate", lambda root: {
            "status": "fail",
            "findings": [
                {"level": "warning", "check": "live_surface",
                 "detail": "LIVE_SURFACE.md missing action: test"},
                {"level": "error", "check": "generated_docs",
                 "detail": "missing generated doc promised by build plan: .claude/commands/x.md"},
            ],
        })
        report = sh.run_self_host_check(tmp_path)
        reason = sh.gate_failure_reason(report)
        assert reason is not None and reason.startswith("managed surface gate (fail): "), reason
        assert "missing generated doc promised by build plan" in reason, reason
        assert "missing action" not in reason, "a warning was forwarded as the reason"

    def test_a_passing_initialized_report_carries_no_reason(self, tmp_path, monkeypatch):
        """An error-level finding beside a PASS (a producer that grades
        leniently) is not forwarded as a reason: the reason follows the
        verdict, not the finding list."""
        import espalier.repo_mode as rm
        monkeypatch.setattr(rm, "resolve_mode", lambda mode, root: rm.REPO_MODE_INITIALIZED_CONSUMER)
        monkeypatch.setattr(sh, "run_cc_surface_gate", lambda root: {
            "status": "pass",
            "findings": [{"level": "error", "check": "x", "detail": "an error on a passing gate"}],
        })
        report = sh.run_self_host_check(tmp_path)
        assert sh.gate_failure_reason(report) is None
        assert "primary_reason" not in report["gate_details"], report["gate_details"]
