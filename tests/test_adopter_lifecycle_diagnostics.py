"""The adopter lifecycle, driven: init, a hand edit and re-init, scan,
scaffolding-bench twice, the deployed-tree contracts, doctor with one cc/
doc removed, ``clean-generated --execute``, doctor, then the deletion doctor
names and doctor again -- one scratch tree, real subprocesses, the output
read as an adopter reads it (TP-449 Tier 2: the §C6 class, the read-only
diagnostics report the real state and hand back a usable next step; then
the driven-verb lane, the adopter verbs leave the tree and the terminal as
they say). A second, two-verb walk (init then audit on an API repo) covers
the one case the plain tree cannot reach.

Each case is the driven instance behind a unit pin elsewhere:

- DEF-770: ``tests/test_doctor.py::TestDoctorUninstalledTree``
- DEF-773: ``tests/test_cli_commands.py::TestCmdScan``
- DEF-774: ``tests/test_init_managed_markers.py::TestReinitNamesTheRegeneratedFile``
  and ``tests/test_init_upgrade_paths.py::TestUpgradePreviewNamesTheSeedsItWouldRefresh``
- DEF-772: ``tests/test_cli_commands.py::TestHelpListsTheDocumentedVerbs``
- DEF-567: ``tests/test_scaffolding_canon.py::TestScaffoldingBenchWriteHygiene``
- DEF-785: ``tests/test_doctor.py::TestDoctorOnAHalfInstalledConsumerTree``
  and ``tests/test_self_hosting.py::TestTheGateIsNamedForTheTreeItRanOn``
- DEF-735: ``tests/test_selfcheck.py`` (the C-2 deployed-form cases) and
  ``tests/test_cli_commands.py::TestSelfcheckContractsFlag``
- DEF-766: ``tests/test_proofs.py::TestRunCcSurfaceGateLiveSurface`` and
  ``tests/test_init_summary_matches_filesystem.py``

The unit pins build the state by hand; this module earns it through the
verbs, so a change to what a verb leaves behind reds here first. One walk
per module (a module-scoped fixture), every verb's output kept by name, the
verbs run from the suite's cwd with the repo passed as the argument -- the
form ``tests/test_init_managed_markers.py`` drives ``init`` with.
"""
# slow-exempt: fourteen espalier subprocesses over two scratch trees, once per module, measured 3.4s
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest


def _espalier(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "espalier.cli", *args],
        # 60, the suite's own ceiling (pyproject `timeout = 60`, thread method):
        # a larger budget here cannot fire first and only grows DEF-665's count.
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )


@dataclass
class Walk:
    repo: Path
    outputs: dict[str, subprocess.CompletedProcess] = field(default_factory=dict)
    leftovers: list[str] = field(default_factory=list)

    def __getattr__(self, name: str) -> subprocess.CompletedProcess:
        try:
            return self.outputs[name]
        except KeyError:
            raise AttributeError(name) from None


def _leftovers_named_by(doctor_stdout: str) -> list[str]:
    """The paths doctor's uninstalled text names, read from the output the
    adopter reads -- not re-derived from the engine."""
    for line in doctor_stdout.splitlines():
        if line.startswith("Runtime state still here"):
            return [p.strip() for p in line.split(": ", 1)[1].split(",")]
    return []


@pytest.fixture(scope="module")
def walked(tmp_path_factory) -> Walk:
    repo = tmp_path_factory.mktemp("lifecycle") / "adopter"
    repo.mkdir()
    (repo / "README.md").write_text("# adopter\n", encoding="utf-8")
    (repo / "app.py").write_text('def f():\n    print("hi")\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    walk = Walk(repo)
    walk.outputs["init"] = _espalier("init", str(repo))
    edited = repo / ".claude" / "commands" / "status.md"
    edited.write_text(edited.read_text(encoding="utf-8") + "\nmy edit\n", encoding="utf-8")
    walk.outputs["reinit"] = _espalier("init", str(repo))
    walk.outputs["scan"] = _espalier("scan", str(repo))
    walk.outputs["help"] = _espalier("--help")
    walk.outputs["bench"] = _espalier("scaffolding-bench", str(repo))
    walk.outputs["bench_again"] = _espalier("scaffolding-bench", str(repo))
    walk.outputs["contracts"] = _espalier("selfcheck", "--contracts", str(repo))
    # One cc/ doc removed, doctor, the doc put back: the uninstall below
    # takes the whole surface, so the half-installed state is a detour.
    removed = repo / "cc" / "LIVE_SURFACE.md"
    kept = removed.read_bytes()
    removed.unlink()
    walk.outputs["doctor_half"] = _espalier("doctor", str(repo))
    removed.write_bytes(kept)
    # A command file removed with the surface otherwise present: the audit,
    # the self-host check and the recovery check all see it; put back after.
    removed = repo / ".claude" / "commands" / "smoke.md"
    kept = removed.read_bytes()
    removed.unlink()
    walk.outputs["doctor_one_command_gone"] = _espalier("doctor", str(repo))
    removed.write_bytes(kept)
    walk.outputs["uninstall"] = _espalier("clean-generated", "--execute", str(repo))
    walk.outputs["doctor"] = _espalier("doctor", str(repo))
    walk.leftovers = _leftovers_named_by(walk.outputs["doctor"].stdout)
    for rel in walk.leftovers:
        (repo / rel).unlink()
    walk.outputs["doctor_after_delete"] = _espalier("doctor", str(repo))
    return walk


@pytest.fixture(scope="module")
def api_walked(tmp_path_factory) -> Walk:
    """An API repo: the plan recommends ``api-reviewer``, an agent no release
    ships a body for. Two verbs, init then audit."""
    repo = tmp_path_factory.mktemp("lifecycle") / "api"
    repo.mkdir()
    (repo / "README.md").write_text("# api\n", encoding="utf-8")
    (repo / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    walk = Walk(repo)
    walk.outputs["init"] = _espalier("init", str(repo))
    walk.outputs["audit"] = _espalier("audit", str(repo))
    return walk


class TestTheWalkRan:
    def test_every_verb_exited_as_documented(self, walked, api_walked):
        for name in ("init", "reinit", "scan", "help", "bench", "bench_again",
                     "contracts", "uninstall", "doctor", "doctor_after_delete"):
            run = walked.outputs[name]
            assert run.returncode == 0, (name, run.stdout, run.stderr)
        for name in ("doctor_half", "doctor_one_command_gone"):
            run = walked.outputs[name]
            assert run.returncode == 1, (name, run.stdout, run.stderr)
        for name in ("init", "audit"):
            run = api_walked.outputs[name]
            assert run.returncode == 0, (name, run.stdout, run.stderr)


class TestReinitNamesWhatItRegenerated:
    """DEF-774: the count is not the next step; the path is."""

    def test_the_hand_edited_command_is_named_beside_the_count(self, walked):
        out = walked.reinit.stdout
        assert "updated_managed: 1" in out, out
        assert "regenerated from the packaged copy" in out, out
        assert ".claude/commands/status.md" in out, out

    def test_seed_lines_are_root_relative(self, walked):
        # Two seeds are README.md files; by basename they were one line twice.
        err = walked.reinit.stderr
        assert "skip (exists): docs/CONVENTIONS.md" in err, err
        assert "skip (exists): memory/README.md" in err, err
        assert not any(
            line.strip().endswith("): README.md") for line in err.splitlines()
        ), err


class TestScanNamesItsReports:
    """DEF-773: the report behind a non-zero count is named on the terminal."""

    def test_the_report_behind_the_nonzero_count_is_named(self, walked):
        out = walked.scan.stdout
        assert "Prints: 1" in out, out
        assert "scan_prints.json" in out, out
        assert str(walked.repo / "reports") in out, out   # scanned repo is not the cwd
        assert (walked.repo / "reports" / "scan_prints.json").is_file()


class TestHelpListsTheAdopterVerbs:
    """DEF-772: the three adopter verbs are listed; the stand-down gate is not.
    Read from the rendered text, as an adopter reads it; the unit twin reads
    the parser's own choices list."""

    def test_the_three_documented_verbs_are_listed_and_the_gate_is_not(self, walked):
        heads = {
            line.strip().split(" ")[0]
            for line in walked.help.stdout.splitlines() if line.startswith("    ")
        }
        assert {"blueprint", "reflect-deep", "worktree-plan"} <= heads, sorted(heads)
        assert "pre-release" not in heads, sorted(heads)


class TestScaffoldingBenchLeavesNoChurn:
    """DEF-567: two runs with nothing to report leave the current report and
    no snapshot; the second run rewrites nothing and says so."""

    def test_two_runs_with_nothing_to_report_leave_no_snapshot(self, walked):
        assert "nothing to report" in walked.bench.stdout, walked.bench.stdout
        assert "[ok] unchanged" in walked.bench_again.stdout, walked.bench_again.stdout
        assert (walked.repo / "reports" / "scaffolding_canon.json").is_file()
        assert not (walked.repo / "reports" / "scaffolding_canon").exists()


class TestTheDeployedTreeContractsAreReachable:
    """DEF-735: `selfcheck --contracts` runs the three contracts that read
    the deployed tree, and a fresh init passes all three -- including the
    upstream-parity compare that read every marked hook copy as drift."""

    def test_selfcheck_contracts_passes_on_the_fresh_tree(self, walked):
        c = walked.contracts
        report = json.loads(c.stdout)
        assert report["status"] == "pass", c.stdout
        assert [x["name"] for x in report["checks"]] == [
            "C-1 live-deny-path", "C-2 upstream-parity", "C-3 live-kill-switch-absent",
        ], report


class TestDoctorOnAHalfInstalledTree:
    """DEF-785: one missing doc is one error, and no line names a self-host
    gate on a consumer tree."""

    def test_one_missing_doc_is_one_error_and_no_self_host_text(self, walked):
        d = walked.doctor_half
        both = d.stdout + d.stderr
        assert "doctor: fail -- 1 error;" in d.stderr, d.stderr
        assert "cc/LIVE_SURFACE.md" in d.stdout, d.stdout
        assert "self-host" not in both, both

    def test_one_missing_command_is_one_gate_line_that_names_it(self, walked):
        """The sister site: with the surface present, the audit and the
        self-host check run the SAME gate. Before 2026-09-12 that was two
        failure lines (one nameless, one `self-host surface gate: fail`)
        beside the recovery check's, three errors for one file; now the
        audit line carries the finding and the gate line is withheld."""
        d = walked.doctor_one_command_gone
        report = json.loads(d.stdout)
        gate_lines = [f for f in report["failures"] if "gate" in f]
        assert len(gate_lines) == 1, report["failures"]
        assert gate_lines[0].startswith("audit (surface gate) did not pass: "), gate_lines
        assert ".claude/commands/smoke.md" in gate_lines[0], gate_lines
        assert report["primary_reason"] == gate_lines[0], report["primary_reason"]
        assert "self-host" not in d.stdout + d.stderr


class TestInitOnAnApiRepo:
    """DEF-766: the summary names the recommendation that has no body, and
    `audit` after `init` no longer warns that LIVE_SURFACE.md omits it."""

    def test_the_bodiless_recommendation_is_named_and_not_warned_about(self, api_walked):
        out = api_walked.init.stdout
        assert "recorded as a recommendation only" in out and "api-reviewer" in out, out
        assert not (api_walked.repo / ".claude" / "agents" / "api-reviewer.md").exists()
        audit = api_walked.audit.stdout + api_walked.audit.stderr
        assert "missing agent" not in audit, audit


_SMOKE_BODY = Path(__file__).resolve().parent.parent / ".claude" / "commands" / "smoke.md"


def _rendered_hook_wiring_check(project_dir: Path, *, substitute: bool) -> str:
    """The `/smoke` hook-wiring Python, as the reader's shell receives it.

    Two renderings, because the body reaches the shell through the command
    loader: observed 2026-09-12, the loader substitutes `${CLAUDE_PROJECT_DIR}`
    in a command body with the absolute path before bash sees it (DEF-787:
    the old prefix loop spelled that variable as a literal and so could never
    match the path init writes). A loader that leaves the variable alone is
    the other rendering. The check must pass under both.
    """
    text = _SMOKE_BODY.read_text(encoding="utf-8")
    if substitute:
        text = text.replace("${CLAUDE_PROJECT_DIR}", str(project_dir))
    text = text[text.index("Hook wiring"):]
    m = re.search(r'python -c "(.*?)\n"', text, re.S)
    assert m, "the hook-wiring fence was not found in smoke.md"
    # What bash makes of a double-quoted string: \" \$ \\ \` are unescaped.
    return (
        m.group(1)
        .replace('\\"', '"').replace("\\$", "$").replace("\\\\", "\\").replace("\\`", "`")
    )


class TestSmokeHookWiringOnTheRenderedBody:
    """DEF-787: `/smoke` reported every deployed hook MISSING on a healthy
    tree. Driven through the rendered body against a real init tree, with
    the settings.json init wrote."""

    @pytest.mark.parametrize("substitute", [True, False], ids=["loader-substitutes", "loader-leaves-it"])
    def test_every_wired_hook_is_found(self, adopter_tree, substitute):
        settings = json.loads((adopter_tree / ".claude" / "settings.json").read_text(encoding="utf-8"))
        wired = sum(
            1 for entries in settings["hooks"].values()
            for entry in entries for _h in entry.get("hooks", [])
        )
        assert wired > 0, "the driven tree has no hook wiring to check"
        src = _rendered_hook_wiring_check(adopter_tree, substitute=substitute)
        result = subprocess.run(
            [sys.executable, "-c", src], cwd=adopter_tree,
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        out = result.stdout + result.stderr
        assert result.returncode == 0, out
        assert "MISSING" not in out, out
        assert out.count("[OK]") == wired, (wired, out)
        assert "no hook scripts parsed" not in out, out

    def test_the_body_does_not_depend_on_loader_substitution(self):
        """The mechanical form of the two renderings agreeing: the body spells
        the project-dir variable nowhere, so there is nothing for the loader
        to rewrite. (The parametrize above stays as the guard for the day a
        literal comes back.)"""
        assert "${CLAUDE_PROJECT_DIR}" not in _SMOKE_BODY.read_text(encoding="utf-8")

    def test_an_adopters_own_hook_outside_tools_cc_is_found_too(self, tmp_path):
        """The prefix is stripped by its tail, so a hook the adopter wired
        under their own directory (merge-settings exists for that) is checked
        on disk like ours -- the first cut kept the literal for anything not
        under tools/cc/ and reported it MISSING (review-driven)."""
        for rel in ("tools/cc/hooks/write_guard.py", ".claude/hooks/my_hook.py"):
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text("print('hi')\n", encoding="utf-8")
        (tmp_path / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {"PreToolUse": [{"hooks": [
                {"type": "command", "command": "python3",
                 "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"]},
                {"type": "command", "command": "python3",
                 "args": ["${CLAUDE_PROJECT_DIR}/.claude/hooks/my_hook.py"]},
            ]}]}
        }), encoding="utf-8")
        src = _rendered_hook_wiring_check(tmp_path, substitute=True)
        result = subprocess.run(
            [sys.executable, "-c", src], cwd=tmp_path,
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        out = result.stdout + result.stderr
        assert result.returncode == 0 and "MISSING" not in out, out
        assert out.count("[OK]") == 2, out


class TestDoctorAfterUninstall:
    """DEF-770: an uninstalled tree is uninstalled, not a broken install --
    and the advice is terminal: following it lands on the never-initialized
    text, not back on the fail wall."""

    def test_the_uninstall_emptied_the_deployed_surface(self, walked):
        assert not (walked.repo / "cc" / "COMMANDS.md").exists()
        assert not (walked.repo / "tools" / "cc" / "hooks").exists()
        assert not (walked.repo / ".claude" / "skills").exists()

    def test_doctor_reads_the_tree_as_uninstalled_and_names_the_runtime_state(self, walked):
        d = walked.doctor
        both = d.stdout + d.stderr
        assert "harness not on disk" in d.stdout, both
        assert "reports/harness_config.json" in walked.leftovers, walked.leftovers
        assert "missing required managed surface" not in both, both
        assert "stale saved-plan" not in both, both
        assert not d.stdout.lstrip().startswith("{"), both

    def test_deleting_the_named_state_lands_on_the_never_initialized_text(self, walked):
        assert (walked.repo / ".claude" / "settings.json").is_file()   # the adopter's, kept
        d = walked.doctor_after_delete
        both = d.stdout + d.stderr
        assert "not initialized for Espalier-Harness" in d.stdout, both
        assert "harness not on disk" not in d.stdout, both
        assert "missing required managed surface" not in both, both
        assert not d.stdout.lstrip().startswith("{"), both
