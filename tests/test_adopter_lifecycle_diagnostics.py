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
per stack (a module-scoped fixture parametrised over ``python`` and
``node``), every verb's output kept by name, the verbs run from the suite's
cwd with the repo passed as the argument -- the form
``tests/test_init_managed_markers.py`` drives ``init`` with.

Since 2026-10-10 (TP-474 1-A) the walk is the adopter's whole lifecycle in
the order TP-474's Task 0 drove it: ``init``, the ONB-1 code, a commit,
``install-ci``, a commit, the deployed ``ci_guard.py`` replaying that commit
as a push and the adopter's own ``ci.yml`` edit as a pull request, ``doctor``,
then the skew -- the helper kept without its marker and missing the two
budget names, twelve hooks staled, an agent body edited, a retired key in the
saved fingerprint -- ``write_guard.py`` on a Read, ``upgrade`` dry and
``--execute``, every wired hook launched once on a no-op input, ``doctor``, the
deep skew (two more names gone) with ``write_guard.py`` and ``doctor`` again, a
``99.0.0`` stamp dry run, a clone's ``doctor`` / ``upgrade --execute`` /
``doctor``, the helper re-marked, the uninstall, ``doctor`` twice. Each new
class names its ledger row. The classes whose fix is another TP-474 lane's
(upgrade 3-A to 3-D, CI 4-A and 4-B, onboarding 5-A) carry
``xfail(strict=True)`` naming the row: the Walk lands green on ``main`` with
those reds recorded, and the lane that fixes a row deletes its mark -- a fix
that lands without deleting it reds under ``strict``. The tree is
``build_adopter_tree(stack, tree="git")`` plus ``app.py`` (the print
``TestScanNamesItsReports`` counts) and the adopter's own
``.github/workflows/ci.yml``; every ``ESPALIER_*`` and ``CLAUDE*`` variable is
stripped from the children (a hook reads ``CLAUDE_PROJECT_DIR`` as its root,
and the suite's own session would otherwise hand it this checkout).
"""
# slow-exempt: the lifecycle walk, about sixty espalier and hook subprocesses per stack over two stacks plus the api walk, once per module, measured 2026-10-10: 43 s for the whole module on the Air, about 18 s per stack's fixture
# timeout-exempt: the raised ceiling is the walk fixture's setup on a slow host, not a slow test: 37 s on Ubuntu and 46 s on macOS under -n auto, past 60 s under -n auto on windows-latest (run 38874132596), 123-142 s on a loaded Windows host
from __future__ import annotations

import json
import re
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import espalier
from espalier.cli import _ONBOARDING_ROWS, _build_goal_md

from _adopter_tree import build_adopter_tree


#: The module's own per-test ceiling, on every host. Each walk is a module-scoped
#: fixture set up inside the first test that asks for it, and that setup alone is
#: most of the suite's 60 s: 37 s on Ubuntu and 46 s on macOS under ``-n auto``,
#: 38-53 s across 23 serial windows-latest cells and 56-59 s where it passed under
#: ``-n auto`` there, past 60 s in the 16 worker crashes run 38874132596 named
#: (2026-10-16, DEF-979's split; each replacement worker rebuilt the walk and
#: crashed again), and 123-142 s per stack on a loaded Windows host (2026-10-10).
#: A mark outranks ``--timeout`` and ``PYTEST_TIMEOUT``, so this is the ceiling a
#: loaded local run gets too, and it stays above the windows-latest cell's own
#: (tests/test_ci_job_bounds.py pins that no mark sits between the two); the 45 s
#: subprocess bounds below stay under it.
pytestmark = pytest.mark.timeout(300)


#: The children's environment: every ``ESPALIER_*`` and ``CLAUDE*`` variable
#: stripped. A hook resolves its root from ``CLAUDE_PROJECT_DIR`` and reads
#: ``ESPALIER_MAINTENANCE_MODE``; under the suite's own Claude Code session both
#: are set for THIS checkout, and a child that inherits them judges the wrong
#: tree with the zone check off. The CLI verbs get the same environment so the
#: two cannot drift.
_ENV = {k: v for k, v in os.environ.items() if not k.startswith(("ESPALIER", "CLAUDE"))}


def _espalier(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "espalier.cli", *args],
        # Under the per-test ceiling (this module's 300 s, `pytestmark` above;
        # the suite's is 60 s): a budget at or above it can never fire first.
        # Pinned by the per-test ceiling contract in tests/test_test_suite_contract.py.
        capture_output=True, text=True, encoding="utf-8", timeout=45, env=_ENV,
    )


def _run_in(tree: Path, args: list[str], *, stdin: str | None = None,
            **env_extra: str) -> subprocess.CompletedProcess:
    """A child run inside ``tree`` -- a deployed hook or guard, or a code snippet
    the tree's own text supplies -- with ``_ENV`` plus ``env_extra``."""
    return subprocess.run(
        args, cwd=str(tree), input=stdin, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=45, env={**_ENV, **env_extra},
        stdin=None if stdin is not None else subprocess.DEVNULL,
    )


def _git(tree: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args], cwd=str(tree), env=_ENV,
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout.strip()


def _commit_all(tree: Path, message: str) -> str:
    _git(tree, "add", "-A")
    _git(tree, "commit", "-qm", message)
    return _git(tree, "rev-parse", "HEAD")


#: The managed-marker comment line a deployed ``.py`` carries
#: (``espalier.managed_markers.MARKER_HASH_COMMENT``), matched as a whole line:
#: the helper's prose mentions the marker once too.
_MARKER_LINE = "# espalier:managed\n"

#: A no-op input per event, for launching a wired hook once: enough fields for
#: the hook to parse and judge nothing, never a write.
_NOOP_INPUT: dict[str, dict] = {
    "PreToolUse": {"tool_name": "Read", "tool_input": {"file_path": "notes.txt"}},
    "PostToolUse": {"tool_name": "Read", "tool_input": {"file_path": "notes.txt"}, "tool_response": {}},
    "PostToolUseFailure": {"tool_name": "Read", "tool_input": {"file_path": "notes.txt"}, "error": "x"},
    "UserPromptSubmit": {"prompt": "hello"},
    "Stop": {"stop_hook_active": False},
    "SessionStart": {"source": "startup"},
    "PostCompact": {"trigger": "manual"},
    "SubagentStart": {"agent_id": "a"},
    "SubagentStop": {"agent_id": "a"},
    "ConfigChange": {"source": "project_settings"},
}


def _wired_hooks(tree: Path) -> list[tuple[str, str]]:
    """``(event, script)`` for every hook ``.claude/settings.json`` wires, read
    the way the ``/smoke`` body reads it (the exec form's ``args`` and the legacy
    ``command``), never a literal count."""
    data = json.loads((tree / ".claude" / "settings.json").read_text(encoding="utf-8"))
    wired: list[tuple[str, str]] = []
    for event, entries in data.get("hooks", {}).items():
        for entry in entries:
            for h in entry.get("hooks", []):
                for p in [*h.get("args", []), h.get("command", "")]:
                    if isinstance(p, str) and p.endswith(".py") and "hooks/" in p:
                        wired.append((event, re.sub(r"^.*?PROJECT_DIR}?/", "", p)))
    return wired


def _launch_wired_hooks(tree: Path) -> dict[str, subprocess.CompletedProcess]:
    """Every wired hook once, on its event's no-op input, keyed by script name.
    The Stop gate runs light (no pytest); the root is the tree."""
    out: dict[str, subprocess.CompletedProcess] = {}
    for event, script in _wired_hooks(tree):
        payload = {"hook_event_name": event, "session_id": "walk", "cwd": str(tree), **_NOOP_INPUT.get(event, {})}
        if event == "ConfigChange":
            payload["file_path"] = str(tree / ".claude" / "settings.json")
        out[Path(script).name] = _run_in(
            tree, [sys.executable, str(tree / script)], stdin=json.dumps(payload),
            CLAUDE_PROJECT_DIR=str(tree), ESPALIER_STOP_GATE="light",
        )
    return out


def _ci_guard_replay(tree: Path, **env: str) -> subprocess.CompletedProcess:
    """The deployed ``tools/cc/ci_guard.py`` run as CI would run it, over the
    env a workflow sets (``GITHUB_EVENT_NAME``, ``BASE_SHA``, ``PR_TITLE``,
    ``PR_HEAD_SHA``)."""
    return _run_in(tree, [sys.executable, str(tree / "tools" / "cc" / "ci_guard.py")], **env)


def _onb1(tree: Path) -> str:
    """The ONB-1 onboarding code from ``espalier/cli.py::_ONBOARDING_ROWS``, run
    in the tree as the onboarding check runs it; its printed verdict."""
    code = next(r["code"] for r in _ONBOARDING_ROWS if r["id"] == "ONB-1")
    return _run_in(tree, [sys.executable, "-c", code]).stdout.strip()


@dataclass
class Walk:
    repo: Path
    stack: str = "python"
    outputs: dict[str, subprocess.CompletedProcess] = field(default_factory=dict)
    leftovers: list[str] = field(default_factory=list)
    #: ``{tag: {script name: run}}`` for the three launches of every wired hook.
    hooks: dict[str, dict[str, subprocess.CompletedProcess]] = field(default_factory=dict)
    onb1: dict[str, str] = field(default_factory=dict)
    clone: Path | None = None
    clone_commands_md_changed: bool | None = None
    helper_after_upgrade: dict[str, bool] = field(default_factory=dict)
    skewed_hooks: list[str] = field(default_factory=list)
    wired: list[tuple[str, str]] = field(default_factory=list)
    install_ci_files_after_uninstall: list[str] = field(default_factory=list)

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


@pytest.fixture(scope="module", params=("python", "node"), ids=lambda s: s)
def walked(request, tmp_path_factory) -> Walk:
    stack = request.param
    base = tmp_path_factory.mktemp(f"lifecycle-{stack}")
    repo = build_adopter_tree(base / "adopter", stack=stack, tree="git")
    # The two files the walk's own assertions need, on top of the stack row:
    # the print TestScanNamesItsReports counts, and the adopter's own workflow.
    (repo / "app.py").write_text('def f():\n    print("hi")\n', encoding="utf-8")
    own_ci = repo / ".github" / "workflows" / "ci.yml"
    own_ci.parent.mkdir(parents=True, exist_ok=True)
    own_ci.write_text(
        "name: ci\non: [push, pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: actions/checkout@v4\n      - run: npm test\n",
        encoding="utf-8",
    )
    _commit_all(repo, "the adopter's own files")
    walk = Walk(repo, stack=stack)
    walk.outputs["init"] = _espalier("init", str(repo))
    walk.wired = _wired_hooks(repo)
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

    # -- TP-474 Task 0's order from here ---------------------------------------
    # Every wired hook once on the tree as init left it (the detours above
    # restore their files; launched here so a SessionStart blueprint is not
    # the scaffolding bench's one session).
    walk.hooks["after_init"] = _launch_wired_hooks(repo)
    # ONB-1 with the goal written under `## Goal`; then with `goal_snapshot =
    # false` set and the skeleton kept (DEF-1032, DEF-1033).
    goal = repo / "cc" / "GOAL.md"
    skeleton = goal.read_text(encoding="utf-8")
    written = _build_goal_md()
    written = (written[:written.index("## Goal")] + "## Goal\n\nShip the demo CLI with tests.\n\n"
               "## Where we are / next gate\n\n(not set -- /handoff fills this in from the session work)\n")
    goal.write_text(written, encoding="utf-8")
    walk.onb1["goal_written"] = _onb1(repo)
    goal.write_text(skeleton, encoding="utf-8")
    toml = repo / "espalier.toml"
    toml.write_text(toml.read_text(encoding="utf-8") + "\ngoal_snapshot = false\n", encoding="utf-8")
    walk.onb1["key_set_skeleton_kept"] = _onb1(repo)
    init_commit = _commit_all(repo, "espalier init")
    walk.outputs["install_ci"] = _espalier("install-ci", str(repo))
    walk.hooks["after_install_ci"] = _launch_wired_hooks(repo)
    install_ci_commit = _commit_all(repo, "espalier install-ci")
    # The deployed guard replays the install-ci commit as a push from the init
    # commit (DEF-1050), then the adopter's own ci.yml edit as a pull request
    # whose title carries no marker (DEC-39).
    walk.outputs["replay_push"] = _ci_guard_replay(repo, GITHUB_EVENT_NAME="push", BASE_SHA=init_commit)
    own_ci.write_text(own_ci.read_text(encoding="utf-8") + "      - run: npm run lint\n", encoding="utf-8")
    head = _commit_all(repo, "ci: lint")
    walk.outputs["replay_pr_own_ci"] = _ci_guard_replay(
        repo, GITHUB_EVENT_NAME="pull_request", BASE_SHA=install_ci_commit, PR_TITLE="ci: lint", PR_HEAD_SHA=head,
    )
    walk.outputs["doctor_clean"] = _espalier("doctor", str(repo))
    # The skew: the helper kept as the adopter's (marker gone) and predating the
    # two budget names (DEF-1176); twelve other hooks staled by a comment; an
    # agent body edited with its marker kept (DEF-1064, DEF-1077); one retired
    # key in the saved fingerprint (DEF-1126).
    hooks_dir = repo / "tools" / "cc" / "hooks"
    helper = hooks_dir / "_hook_utils.py"
    lines = helper.read_text(encoding="utf-8").splitlines(keepends=True)
    assert lines.count(_MARKER_LINE) == 1, "the deployed helper carries one marker line"
    lines.remove(_MARKER_LINE)
    helper.write_text("".join(lines) + "\ndel spawn_timeout, STATE_WRITE_LOCK\n", encoding="utf-8")
    # Every other hook staled by a comment (Task 0 staled twelve, a sorted
    # glob's first twelve; every one is the same measurement with no magic slice).
    walk.skewed_hooks = sorted(p.name for p in hooks_dir.glob("*.py") if p.name != "_hook_utils.py")
    for name in walk.skewed_hooks:
        p = hooks_dir / name
        p.write_text(p.read_text(encoding="utf-8") + "#x\n", encoding="utf-8")
    body = repo / ".claude" / "agents" / "code-reviewer.md"
    body.write_text(body.read_text(encoding="utf-8") + "\nlane\n", encoding="utf-8")
    fingerprint = repo / "reports" / "repo_fingerprint.json"
    saved = json.loads(fingerprint.read_text(encoding="utf-8"))
    saved["retired_field"] = 1
    fingerprint.write_text(json.dumps(saved, indent=2), encoding="utf-8")
    walk.outputs["write_guard_skewed"] = _run_in(
        repo, [sys.executable, str(hooks_dir / "write_guard.py")],
        stdin=json.dumps({"tool_name": "Read", "tool_input": {"file_path": "notes.txt"}}),
        CLAUDE_PROJECT_DIR=str(repo),
    )
    walk.outputs["upgrade_dry"] = _espalier("upgrade", str(repo))
    walk.outputs["upgrade_execute"] = _espalier("upgrade", str(repo), "--execute")
    after = helper.read_text(encoding="utf-8")
    walk.helper_after_upgrade = {"marked": _MARKER_LINE in after.splitlines(keepends=True),
                                 "skewed": "del spawn_timeout, STATE_WRITE_LOCK" in after}
    walk.hooks["after_upgrade"] = _launch_wired_hooks(repo)
    walk.outputs["doctor_skewed"] = _espalier("doctor", str(repo))
    # The deep skew: a helper that also predates two names the hooks read at
    # module level (`payload_cwd` in write_guard, `hook_cwd` in session_start and
    # task_router -- a September copy lacks both). The budget names degrade, so
    # the skew above is judged; these are on the floor, so write_guard refuses
    # and doctor names the hooks that cannot start (DEF-1176, DEF-1188). Put back
    # before the stamp, the clone and the uninstall, which walk the budget skew
    # (asserted below, where a raise in between would otherwise leave it).
    skewed_text = helper.read_text(encoding="utf-8")
    helper.write_text(skewed_text + "del payload_cwd, hook_cwd\n", encoding="utf-8")
    walk.outputs["write_guard_deep"] = _run_in(
        repo, [sys.executable, str(hooks_dir / "write_guard.py")],
        stdin=json.dumps({"tool_name": "Read", "tool_input": {"file_path": "notes.txt"}}),
        CLAUDE_PROJECT_DIR=str(repo),
    )
    walk.outputs["doctor_deep"] = _espalier("doctor", str(repo))
    helper.write_text(skewed_text, encoding="utf-8")
    # The invariant the later verbs rest on, named where it would fail: the
    # stamp, the clone and the uninstall walk the budget skew, never the deep one.
    assert "payload_cwd, hook_cwd" not in helper.read_text(encoding="utf-8")
    # The deployed stamp rewritten to 99.0.0, a dry run, the stamp restored
    # (DEF-1104).
    manifest = repo / "cc" / "PACK_MANIFEST.txt"
    stamped = manifest.read_bytes()
    manifest.write_bytes(stamped.replace(espalier.__version__.encode(), b"99.0.0"))
    walk.outputs["upgrade_dry_99"] = _espalier("upgrade", str(repo))
    manifest.write_bytes(stamped)
    # A clone (no gitignored reports/): doctor, upgrade --execute, doctor
    # (DEF-1063). Made after the skew, so the clone carries it.
    _commit_all(repo, "skewed and upgraded")
    walk.clone = base / "clone"
    subprocess.run(["git", "clone", "-q", str(repo), str(walk.clone)], env=_ENV, check=True,
                   capture_output=True)
    walk.outputs["clone_doctor_before"] = _espalier("doctor", str(walk.clone))
    commands_md = (walk.clone / "cc" / "COMMANDS.md").read_bytes()
    walk.outputs["clone_upgrade_execute"] = _espalier("upgrade", str(walk.clone), "--execute")
    walk.outputs["clone_doctor_after"] = _espalier("doctor", str(walk.clone))
    walk.clone_commands_md_changed = (walk.clone / "cc" / "COMMANDS.md").read_bytes() != commands_md
    # The helper re-marked so the uninstall takes it; the uninstall; doctor;
    # the deletion doctor names; doctor again (DEF-770, DEF-1061).
    helper.write_text(_MARKER_LINE + helper.read_text(encoding="utf-8"), encoding="utf-8")
    walk.outputs["uninstall"] = _espalier("clean-generated", "--execute", str(repo))
    walk.outputs["doctor"] = _espalier("doctor", str(repo))
    walk.leftovers = _leftovers_named_by(walk.outputs["doctor"].stdout)
    # Read before the deletion below takes what doctor names (install-ci's
    # files among them since TP-474 2-C): the uninstall itself left them.
    walk.install_ci_files_after_uninstall = sorted(
        rel for rel in ("tools/cc/ci_guard.py", ".github/workflows/harness-guard.yml") if (repo / rel).is_file()
    )
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
    """Every verb exited as documented. A verb whose documented exit is another
    TP-474 lane's to earn (the pull-request replay under DEC-39 (b)) is pinned
    in its own bridged class, never here. The upgrade lane's two refusals --
    the clone's ``--execute`` with no saved plan (3-A) and the newer deployed
    stamp, refused in both modes (3-C) -- landed, so their exit is pinned here."""

    def test_every_verb_exited_as_documented(self, walked, api_walked):
        for name in ("init", "reinit", "scan", "help", "bench", "bench_again", "contracts",
                     "install_ci", "doctor_clean", "upgrade_dry", "upgrade_execute",
                     "clone_doctor_before", "uninstall", "doctor", "doctor_after_delete"):
            run = walked.outputs[name]
            assert run.returncode == 0, (name, run.stdout, run.stderr)
        for name in ("doctor_half", "doctor_one_command_gone"):
            run = walked.outputs[name]
            assert run.returncode == 1, (name, run.stdout, run.stderr)
        for name in ("upgrade_dry_99", "clone_upgrade_execute"):
            run = walked.outputs[name]
            assert run.returncode == 2, (name, run.stdout, run.stderr)
        # The install-ci commit changed protected paths with no marker: refused.
        assert walked.replay_push.returncode == 2, (walked.replay_push.stdout, walked.replay_push.stderr)
        for name in ("init", "audit"):
            run = api_walked.outputs[name]
            assert run.returncode == 0, (name, run.stdout, run.stderr)

    def test_the_wired_hook_count_is_derived_and_launched_three_times(self, walked):
        wired = walked.wired   # read from the tree init wrote, before the uninstall took it
        assert len(wired) >= 10, wired
        for tag in ("after_init", "after_install_ci", "after_upgrade"):
            assert set(walked.hooks[tag]) == {Path(s).name for _, s in wired}, (tag, sorted(walked.hooks[tag]))


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
    """DEF-766: the summary names the suggested agent that has no body, and
    `audit` after `init` no longer warns that LIVE_SURFACE.md omits it. Since
    2026-10-06 a bodiless agent is a suggestion the plan saves apart, never
    one of its agents."""

    def test_the_bodiless_recommendation_is_named_and_not_warned_about(self, api_walked):
        out = api_walked.init.stdout
        assert "Suggested agents" in out and "api-reviewer" in out, out
        assert not (api_walked.repo / ".claude" / "agents" / "api-reviewer.md").exists()
        audit = api_walked.audit.stdout + api_walked.audit.stderr
        assert "missing agent" not in audit, audit


# -- TP-474 1-A: the lifecycle classes. Each docstring names its row; a class
# whose fix is another lane's carries the strict xfail bridge (Decision 6).


def _bridge(row: str, claim: str):
    """The strict-xfail bridge: the class is red on ``main`` for the row's
    reason and the lane that fixes the row deletes the mark; a fix that lands
    without deleting it reds under ``strict``."""
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=f"{row}: {claim}")


class TestInstallCiNamesTheMarker:
    """DEF-1050: the adopter's first commit after ``install-ci`` is refused by
    the guard it just installed, so ``install-ci`` must say so and name the
    marker in both channel forms. The push replay still exits 2 (no
    first-install exemption, by the row's own choice) naming the same remedy."""

    def test_the_stdout_names_the_marker_in_both_channel_forms(self, walked):
        out = walked.install_ci.stdout
        assert "refuses the commit carrying" in out, out       # the helper's line, not a static banner
        assert "HARNESS-UPDATE-APPROVED in the HEAD commit message" in out, out
        assert "HARNESS-UPDATE-APPROVED@<sha> in the title" in out, out

    def test_the_push_replay_still_refuses_and_names_the_remedy(self, walked):
        r = walked.replay_push
        assert r.returncode == 2, (r.stdout, r.stderr)
        assert "HARNESS-UPDATE-APPROVED" in r.stdout + r.stderr, r.stdout + r.stderr


class TestUpgradeExecuteNamesTheMarker:
    """DEF-1052: ``upgrade --execute`` on an install-ci tree re-deploys hooks
    the guard gates, and the commit carrying them is refused unmarked, so the
    execute report names the marker in both channel forms."""

    def test_the_execute_report_names_the_marker_in_both_channel_forms(self, walked):
        out = walked.upgrade_execute.stdout
        assert "re-deployed" in out, out
        assert "HARNESS-UPDATE-APPROVED in the HEAD commit message" in out, out
        assert "HARNESS-UPDATE-APPROVED@<sha> in the title" in out, out


class TestAnAdoptersOwnWorkflowIsTheirs:
    """DEC-39 (b): the ``.github/workflows/`` prefix is protected on the self-host
    repository alone; an adopter editing their own ``ci.yml`` passes the
    pull-request replay with no marker."""

    def test_the_pull_request_replay_passes(self, walked):
        r = walked.replay_pr_own_ci
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert "enforcement layer" not in r.stdout + r.stderr, r.stdout + r.stderr


class TestOnbOneReadsTheGoal:
    """DEF-1032, DEF-1033: the ONB-1 code reads the goal the way the harness's
    readers do -- ``False`` (done) with a goal written under ``## Goal``;
    ``True`` (open) with ``goal_snapshot = false`` set and the skeleton kept."""

    def test_false_with_the_goal_written(self, walked):
        assert walked.onb1["goal_written"] == "False", walked.onb1

    def test_true_with_the_key_set_and_the_skeleton_kept(self, walked):
        assert walked.onb1["key_set_skeleton_kept"] == "True", walked.onb1


def _is_deny(run: subprocess.CompletedProcess) -> bool:
    text = run.stdout.strip()
    if not text.startswith("{"):
        return False
    try:
        out = json.loads(text.splitlines()[-1])
    except ValueError:
        return False
    return out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def _is_decision_or_silent(run: subprocess.CompletedProcess) -> bool:
    """The channel rule: exit 0 (stdout is the hook's own channel -- a decision
    object, a reporter's plain-text context, or nothing; what opens as JSON
    must parse), or exit 2 with nothing on stdout (the text is stderr's)."""
    if run.returncode == 2:
        return run.stdout.strip() == ""
    if run.returncode != 0:
        return False
    text = run.stdout.strip()
    if not text.startswith("{"):
        return True        # a reporter's plain-text context, or nothing: exit 0's own channel
    try:
        json.loads(text.splitlines()[-1])
    except ValueError:
        return False
    return True


class TestEveryWiredHookStarts:
    """DEF-1176: every hook ``settings.json`` wires starts on its event's no-op
    input and exits 0 or 2 under the channel rule -- after ``init``, after
    ``install-ci`` and after ``upgrade --execute`` on the skewed tree. The
    measured skew (the two budget names) is JUDGED: those names degrade in the
    two helper modules, so the guard judges on and the reporters start. The deep
    skew (a floor name gone too) is REFUSED: a structured deny with exit 0 naming
    the repair, never exit 1, which the protocol reads as non-blocking."""

    def test_every_launch_exits_zero_or_two_under_the_channel_rule(self, walked):
        bad = {
            (tag, name): (run.returncode, run.stdout[-200:], run.stderr[-300:])
            for tag, runs in walked.hooks.items()
            for name, run in runs.items()
            if not _is_decision_or_silent(run)
        }
        assert not bad, bad

    def test_write_guard_on_the_budget_skew_judges_the_call(self, walked):
        # Decision 3's carve-out, measured: a helper missing only the two budget
        # names is judged on (a harmless Read is allowed), not refused and not
        # a traceback.
        r = walked.write_guard_skewed
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        assert "Traceback" not in r.stderr, r.stderr
        assert not _is_deny(r), r.stdout

    def test_the_budget_skew_launch_agrees_with_the_direct_run(self, walked):
        r = walked.hooks["after_upgrade"]["write_guard.py"]
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        assert not _is_deny(r), r.stdout

    def test_write_guard_on_the_deep_skew_refuses_naming_the_repair(self, walked):
        r = walked.write_guard_deep
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        assert r.stderr.strip() == "", r.stderr           # one channel per deny
        assert _is_deny(r), r.stdout
        reason = json.loads(r.stdout.strip().splitlines()[-1])["hookSpecificOutput"]["permissionDecisionReason"]
        # The kept-helper text (DEF-2010): the taking file, the name the helper
        # lacks, then the upgrade the kept-old-helper test earns.
        assert "cannot start:" in reason and "from tools/cc/hooks/_hook_utils.py, which lacks it" in reason, reason
        assert "tools/cc/hooks/_hook_utils.py" in reason and "upgrade --execute" in reason, reason
        assert "payload_cwd" in reason, reason          # the exception names the missing name


class TestUpgradeNamesTheKeptHelperSkew:
    """DEF-1176 (2-B): where ``upgrade`` keeps ``_hook_utils.py`` as the
    adopter's, it compares the names the packaged hooks import from it with the
    names the kept copy defines and names the missing ones with the remedy, in
    the dry run and the execute report both."""

    @pytest.mark.parametrize("arm", ["upgrade_dry", "upgrade_execute"])
    def test_the_kept_helper_line_names_the_missing_names(self, walked, arm):
        out = walked.outputs[arm].stdout
        assert "tools/cc/hooks/_hook_utils.py" in out, out
        assert "spawn_timeout" in out and "STATE_WRITE_LOCK" in out, out
        assert "upgrade --execute" in out or "marker" in out, out

    def test_the_helper_was_kept_unmarked_and_skewed(self, walked):
        # The contract 2-B names, not prevents: keeping an unmarked file is the
        # documented behaviour, and the Walk's clone and uninstall rely on it.
        assert walked.helper_after_upgrade == {"marked": False, "skewed": True}, walked.helper_after_upgrade


class TestUpgradeNamesWhatItReplaces:
    """DEF-1064, DEF-1077: the dry run and the execute report name
    ``.claude/agents/code-reviewer.md``; the edit is gone (the documented
    contract) and the report says what the marker would have done."""

    @pytest.mark.parametrize("arm", ["upgrade_dry", "upgrade_execute"])
    def test_the_edited_body_is_named(self, walked, arm):
        out = walked.outputs[arm].stdout
        assert ".claude/agents/code-reviewer.md" in out, out

    def test_the_report_says_what_the_marker_did_to_the_body(self, walked):
        # The line that names the body also says the marker handed it to the
        # upgrade -- the kept-as-yours line about the helper is not that line.
        lines = [ln for ln in walked.upgrade_execute.stdout.splitlines() if ".claude/agents/code-reviewer.md" in ln]
        assert lines and any("marker" in ln for ln in lines), walked.upgrade_execute.stdout


class TestUpgradeSaysOlderNotUnreadable:
    """DEF-1126: one retired key in ``reports/repo_fingerprint.json`` is an
    older report, filtered by the declared fields -- never 'unreadable'."""

    def test_the_dry_run_says_older(self, walked):
        out = walked.upgrade_dry.stdout
        assert "absent or unreadable" not in out, out
        # The phrase, not the word: "older" alone is also in "folder".
        assert "saved by an older release" in out and "retired_field" in out, out


class TestUpgradeRefusesADowngrade:
    """DEF-1104: the ``99.0.0`` dry run names the deployed side as newer and
    would overwrite nothing."""

    def test_the_dry_run_names_the_newer_deployed_side_and_overwrites_nothing(self, walked):
        assert walked.upgrade_dry_99.returncode == 2, (walked.upgrade_dry_99.stdout, walked.upgrade_dry_99.stderr)
        out = walked.upgrade_dry_99.stdout
        assert "99.0.0" in out, out
        assert "newer" in out, out
        assert "would re-deploy" not in out and "would update" not in out, out


class TestUpgradeRefusesWithoutTheSavedPlan:
    """DEF-1063: in a clone (no gitignored ``reports/``), ``--execute`` exits
    non-zero naming ``init .``, ``doctor`` still passes, and ``cc/COMMANDS.md``
    is byte-unchanged."""

    def test_the_execute_is_refused_and_the_tree_is_untouched(self, walked):
        r = walked.clone_upgrade_execute
        assert r.returncode == 2, (r.stdout, r.stderr)
        assert "init ." in r.stdout + r.stderr, r.stdout + r.stderr
        assert walked.clone_doctor_after.returncode == 0, (walked.clone_doctor_after.stdout, walked.clone_doctor_after.stderr)
        assert walked.clone_commands_md_changed is False


class TestDoctorOnTheSkewedTreeNamesTheDeadHooks:
    """DEF-1188: ``doctor`` on the deep skew, where wired hooks die at import,
    exits 1 with one failure per hook that cannot start, each naming the hook
    and the repair; on the clean tree and on the budget skew (cured by the
    degrade) the check adds no line."""

    def test_doctor_fails_naming_each_hook_that_cannot_start(self, walked):
        d = walked.doctor_deep
        both = d.stdout + d.stderr
        assert d.returncode == 1, both
        assert "cannot start" in both, both
        for script in ("write_guard.py", "session_start.py"):
            assert script in both, (script, both)
        assert "upgrade --execute" in both, both

    @pytest.mark.parametrize("verb", ["doctor_clean", "doctor_skewed"])
    def test_a_tree_whose_hooks_start_adds_no_line(self, walked, verb):
        d = walked.outputs[verb]
        assert d.returncode == 0, (verb, d.stdout + d.stderr)
        assert "cannot start" not in d.stdout + d.stderr, (verb, d.stdout)


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
            capture_output=True, text=True, encoding="utf-8", timeout=45,
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
            capture_output=True, text=True, encoding="utf-8", timeout=45,
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

    def test_install_ci_files_still_on_disk_are_named_as_install_ci_s(self, walked):
        """DEF-1061: the uninstall takes what carries the marker; ``install-ci``'s
        two files do not, so they stay, and doctor says whose they are and that
        the gate keeps running until they go -- instead of reading the tree as
        a broken install missing ``cc/COMMANDS.md``."""
        d = walked.doctor
        assert walked.install_ci_files_after_uninstall == [
            ".github/workflows/harness-guard.yml", "tools/cc/ci_guard.py",
        ], walked.install_ci_files_after_uninstall
        assert "harness not on disk" in d.stdout, d.stdout + d.stderr
        assert "tools/cc/ci_guard.py" in d.stdout, d.stdout
        assert ".github/workflows/harness-guard.yml" in d.stdout, d.stdout
        assert "install-ci" in d.stdout, d.stdout
        assert {"tools/cc/ci_guard.py", ".github/workflows/harness-guard.yml"} <= set(walked.leftovers), walked.leftovers

    def test_deleting_the_named_state_lands_on_the_never_initialized_text(self, walked):
        assert (walked.repo / ".claude" / "settings.json").is_file()   # the adopter's, kept
        d = walked.doctor_after_delete
        both = d.stdout + d.stderr
        assert "not initialized for Espalier-Harness" in d.stdout, both
        assert "harness not on disk" not in d.stdout, both
        assert "missing required managed surface" not in both, both
        assert not d.stdout.lstrip().startswith("{"), both


def _rendered_smoke_check(number: int) -> str:
    """The bash fence under `### <number>.` of the `/smoke` body, verbatim."""
    text = _SMOKE_BODY.read_text(encoding="utf-8")
    m = re.search(rf"^### {number}\. [^\n]*\n```bash\n(.*?)\n```", text, re.S | re.M)
    assert m, f"smoke.md check {number} fence not found"
    return m.group(1)


def _run_smoke_check(number: int, tree: Path) -> str:
    result = subprocess.run(
        ["bash", "-c", _rendered_smoke_check(number)], cwd=tree,
        capture_output=True, text=True, encoding="utf-8", timeout=45,
    )
    return result.stdout + result.stderr


def _copy_of(tree: Path, dest: Path) -> Path:
    """A private copy of the session-scoped adopter tree, so a shape that
    mutates files never writes into the shared fixture."""
    target = dest / "tree"
    shutil.copytree(tree, target, symlinks=True)
    return target


@pytest.mark.skipif(
    not (shutil.which("bash") and Path("/bin/bash").exists()),
    reason="the /smoke fences run under a POSIX bash; a Windows subprocess resolves a bare `bash` to the WSL shim",
)
class TestSmokeInventoryChecksOnAnAdopterCLAUDEMd:
    """Checks 1, 2 and 4 of `/smoke` read the inventory espalier owns
    (cc/COMMANDS.md, regenerated on every init), never the root CLAUDE.md's
    tables: an adopter who keeps their own CLAUDE.md as an `@`-import shell
    carries no tables there, and the old checks printed nothing for checks 1
    and 2 (a vacuous pass) and `[FAIL] MISMATCH` for check 4 on every run.

    The fences are driven through ``bash -c``, so the class skips itself where
    no POSIX bash stands at ``/bin/bash``. On Windows a subprocess resolves an
    unqualified ``bash`` through System32 before PATH, so it gets the WSL shim
    (a UTF-16 "no installed distributions" line) whatever ``shutil.which``
    answers; the ``/bin/bash`` conjunct is what carries the gate there, a
    drive-relative path native Python never finds. These five tests, and
    nothing else, failed the portability cell on every run since the class
    landed (runs 36847287839 and 36862925725, read in full on 2026-10-01).
    The spelling is ``tests/test_guard_metamorphic.py``'s. Forfeit, stated:
    no cell drives the fences under Git Bash, where a Windows adopter runs
    them."""

    def test_the_init_skeleton_passes_all_three(self, adopter_tree):
        for n in (1, 2, 4):
            out = _run_smoke_check(n, adopter_tree)
            assert "[FAIL]" not in out, (n, out)
            assert "[OK]" in out, (n, out)

    def test_an_import_only_claude_md_passes_and_says_skip_for_the_agent_table(self, adopter_tree, tmp_path):
        tree = _copy_of(adopter_tree, tmp_path)
        (tree / "AGENTS.md").write_text("# my-app\n", encoding="utf-8")
        (tree / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        out1, out2, out4 = (_run_smoke_check(n, tree) for n in (1, 2, 4))
        assert "[FAIL]" not in out1 + out2 + out4, (out1, out2, out4)
        assert "[OK]" in out1, out1
        assert "[SKIP]" in out2 and "adopter-owned" in out2, out2
        assert "[OK]" in out4 and "MISMATCH" not in out4, out4

    def test_an_adopters_own_command_file_is_kept_and_named_not_failed(self, adopter_tree, tmp_path):
        tree = _copy_of(adopter_tree, tmp_path)
        (tree / ".claude" / "commands" / "mine.md").write_text("# mine\n", encoding="utf-8")
        out1, out4 = _run_smoke_check(1, tree), _run_smoke_check(4, tree)
        assert "[FAIL]" not in out1 + out4, (out1, out4)
        assert "/mine" in out4 and "[INFO]" in out4, out4

    def test_a_deleted_managed_command_still_fails_by_name(self, adopter_tree, tmp_path):
        tree = _copy_of(adopter_tree, tmp_path)
        (tree / ".claude" / "commands" / "smoke.md").unlink()
        out = _run_smoke_check(1, tree)
        assert "[FAIL] /smoke" in out, out

    def test_a_tree_with_no_inventory_says_skip_not_ok(self, adopter_tree, tmp_path):
        tree = _copy_of(adopter_tree, tmp_path)
        (tree / "cc" / "COMMANDS.md").unlink()
        for n in (1, 4):
            out = _run_smoke_check(n, tree)
            assert "[SKIP]" in out and "[OK]" not in out, (n, out)


def _run_smoke_check_with_python(number: int, tree: Path, shim_dir: Path) -> str:
    """The fence, with a ``python`` that answers: the bodies spell the
    interpreter as ``python`` by the cross-platform convention, and this box
    may answer only to ``python3`` (the DEF-999 ledger probe shims it the
    same way)."""
    shim_dir.mkdir(parents=True, exist_ok=True)
    from tests._stubs import write_stub
    shim = write_stub(shim_dir / "python",
                      "#!/bin/sh\nexec \"%s\" \"$@\"\n" % sys.executable.replace("\\", "/"))
    env = dict(os.environ)
    env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        ["bash", "-c", _rendered_smoke_check(number)], cwd=tree, env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=45,
    )
    return result.stdout + result.stderr


@pytest.mark.skipif(
    not (shutil.which("bash") and Path("/bin/bash").exists()),
    reason="the /smoke fences run under a POSIX bash; a Windows subprocess resolves a bare `bash` to the WSL shim",
)
class TestSmokeChecksGradeOnlyTheHarnessOwnFiles:
    """DEF-999: checks 3 and 5 of `/smoke` read the files espalier owns under
    `.claude/`, never a foreign tool's. On probelab, four malformed
    `.claude/.session-state/<id>/reads.json` files a retired Trellis hook left
    behind made check 3 print `[FAIL]` on every run, and a foreign `.md`
    holding a template token does the same to check 5 -- a red that is always
    red is a red nobody reads. Check 3 grades the two settings files by path
    (and the `reports/` the harness writes); check 5 grades the marker-bearing
    bodies and the root CLAUDE.md, in an ERE so the alternation reads the same
    under BSD, GNU and ugrep (the BRE `\\|` it used is GNU-only: vacuous on a
    stock macOS grep and a self-match on GNU, where the body's own pattern text
    carried the tokens it hunts)."""

    def test_a_foreign_malformed_json_under_claude_passes_check_3(self, adopter_tree, tmp_path):
        tree = _copy_of(adopter_tree, tmp_path)
        junk = tree / ".claude" / ".session-state" / "abc123" / "reads.json"
        junk.parent.mkdir(parents=True)
        junk.write_text("{not json", encoding="utf-8")
        out = _run_smoke_check_with_python(3, tree, tmp_path / "bin")
        assert "[FAIL]" not in out, out
        assert "[OK] .claude/settings.json" in out, out

    def test_a_malformed_settings_file_still_fails_check_3(self, adopter_tree, tmp_path):
        tree = _copy_of(adopter_tree, tmp_path)
        (tree / ".claude" / "settings.local.json").write_text("{oops", encoding="utf-8")
        out = _run_smoke_check_with_python(3, tree, tmp_path / "bin")
        assert "[FAIL] .claude/settings.local.json" in out, out

    def test_a_malformed_report_still_fails_check_3(self, adopter_tree, tmp_path):
        tree = _copy_of(adopter_tree, tmp_path)
        (tree / "reports").mkdir(exist_ok=True)
        (tree / "reports" / "broken.json").write_text("[", encoding="utf-8")
        out = _run_smoke_check_with_python(3, tree, tmp_path / "bin")
        assert "[FAIL] reports/broken.json" in out, out

    def test_a_foreign_markdown_with_a_template_token_passes_check_5(self, adopter_tree, tmp_path):
        tree = _copy_of(adopter_tree, tmp_path)
        (tree / ".claude" / "notes.md").write_text("Project: {PROJECT_NAME}\n", encoding="utf-8")
        out = _run_smoke_check(5, tree)
        assert "[OK] none" in out, out

    def test_a_token_left_in_a_managed_body_still_fails_check_5(self, adopter_tree, tmp_path):
        tree = _copy_of(adopter_tree, tmp_path)
        body = tree / ".claude" / "commands" / "status.md"
        body.write_text(body.read_text(encoding="utf-8") + "\nOwner: {YOUR_NAME}\n", encoding="utf-8")
        out = _run_smoke_check(5, tree)
        assert "[FAIL] found" in out, out
        assert "status.md" in out, out

    def test_a_token_in_the_root_claude_md_still_fails_check_5(self, adopter_tree, tmp_path):
        tree = _copy_of(adopter_tree, tmp_path)
        claude_md = tree / "CLAUDE.md"
        claude_md.write_text(claude_md.read_text(encoding="utf-8") + "\n{TODO: describe}\n", encoding="utf-8")
        out = _run_smoke_check(5, tree)
        assert "[FAIL] found" in out, out

    def test_a_tree_with_no_marker_body_and_no_claude_md_says_ok(self, tmp_path):
        """BSD xargs runs nothing on an empty list, which the old pipe read as
        a find; the operand list is never empty now (failure-mode review)."""
        (tmp_path / ".claude").mkdir()
        out = _run_smoke_check(5, tmp_path)
        assert "[OK] none" in out and "[FAIL]" not in out, out

    def test_the_clean_skeleton_passes_both(self, adopter_tree, tmp_path):
        for n in (3, 5):
            out = _run_smoke_check_with_python(n, adopter_tree, tmp_path / "bin")
            assert "[FAIL]" not in out, (n, out)
            assert "[OK]" in out, (n, out)
