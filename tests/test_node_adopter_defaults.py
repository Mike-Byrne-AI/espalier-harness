"""The defaults a Node adopter inherits, read on the tree a Node adopter brings.

One oracle for the class of Python-shaped defaults (the forward ledger's
class on replacing them, 2026-10-06): ``espalier init`` into a throwaway tree
built by ``tests/_adopter_tree.py::build_adopter_tree`` (a Node project with
``test``, ``lint`` and ``build`` scripts, ``.mjs`` sources and an Astro page),
then the fingerprint, the saved plan, the rendered ``.claude/settings.json``,
``doctor`` and the DEPLOYED ``/preflight`` fences, run under a real POSIX bash
with stub ``ruff``, ``pytest``, ``npm``, ``pnpm`` and ``bun`` first on PATH.
The Node project is driven three times, with no lockfile (npm), with a
``pnpm-lock.yaml`` and with a ``bun.lock``, and every Node assertion names
the commands of that tree's own package manager. The Python adopter tree is
the control: every assertion is parametrised over the stack, so a default
that reads one stack right and another wrong reds here.

What each part refused before the fix, measured on the same trees:

* the fingerprint read the Node tree as no language (``.mjs`` and ``.astro``
  were unmapped) and its UI surface as absent (``astro`` was not a token);
* the workflow profile rendered ``Bash(npm *)`` beside the pytest, ruff and
  black rules, so ``npm install``, ``npm exec --yes`` and every script were
  pre-approved on a tree with no Python of its own;
* doctor's headline on a healthy install was a recommended agent no release
  ships a body for;
* ``/preflight`` Step 1 ran whatever ``ruff`` was first on PATH (on the Node
  tree, over the vendored ``tools/cc/``, leaving a ``.ruff_cache``), and
  Step 2 ran a ``pytest`` on PATH before the repository's ``npm test``.

The module pins each of those to the repository's own declarations and
guards against the drift back to a Python-shaped default, because every one
of them passed the suite while it was wrong: no test ran the harness on a
Node tree. The trees are built once per module (about 5 s each on the
Windows host) and read only; each fence run gets its own stub directory and
log, and the session test works on a copy.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from _adopter_tree import build_adopter_tree
from espalier.doctor import run_doctor_check
from espalier.settings_profiles import PYTHON_ONLY_ALLOWS
from tests import _interpreter_hosts as hosts

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The stacks this module drives: the Node tree the class was found on (under
#: npm, pnpm and Bun), the Python tree as its control, and since 2026-10-07
#: the Go and Rust trees (the stack-registry pack's Decision 6: their axis
#: cells are proven by the session test below, not by an install alone).
STACKS = ("python", "node", "node-pnpm", "node-bun", "go", "rust")

_LANGUAGE = {
    "python": "python", "node": "javascript", "node-pnpm": "javascript", "node-bun": "javascript",
    "go": "go", "rust": "rust",
}

#: Per stack with one test runner: the test command the fingerprint records
#: (the stack table's argv), and the lint /preflight falls back to when the
#: repository declares none and the linter is on PATH.
_TEST_COMMAND = {"python": "pytest -q", "go": "go test ./...", "rust": "cargo test"}
_LINT_FALLBACK = {
    "python": "ruff check --no-cache --extend-exclude tools/cc .",
    "go": "golangci-lint run ./...",
    "rust": "cargo clippy --all-targets -- -D warnings",
}
#: The verb the narrowed allow rules and the runner agents' tools lines carry
#: for a Go or Rust test command (`go test ./...` narrows to `go test`).
_RUNNER_VERB = {"go": "go test", "rust": "cargo test"}

#: Per Node stack: the commands its own package manager runs. Bun's are
#: `bun run <script>`: `bun test` is Bun's own test runner, not the script.
_NODE_COMMANDS = {
    "node": {"test": "npm test", "lint": "npm run lint", "build": "npm run build"},
    "node-pnpm": {"test": "pnpm test", "lint": "pnpm run lint", "build": "pnpm run build"},
    "node-bun": {"test": "bun run test", "lint": "bun run lint", "build": "bun run build"},
}

#: The package manager each stack's fingerprint names ("" for no package.json):
#: the second witness that the tree built is the stack's, since the registry
#: rule reads the parameter and cannot see the tree.
_PACKAGE_MANAGER = {
    "python": "", "node": "npm", "node-pnpm": "pnpm", "node-bun": "bun", "go": "", "rust": "",
}

#: Every Node package manager binary, for "no other manager's rule" checks.
_MANAGERS = ("npm", "pnpm", "yarn", "bun")


def _is_node(stack: str) -> bool:
    return stack in _NODE_COMMANDS


def _manager(stack: str) -> str:
    return _PACKAGE_MANAGER[stack]


def _posix_bash() -> str | None:
    """A real POSIX bash: ``/bin/bash`` off Windows; on Windows, Git Bash found
    beside ``git``, never a bare ``bash`` (a Windows subprocess resolves that
    to the WSL shim). The same lookup ``tests/test_interpreter_hosts.py``
    drives the shipped resolver line under."""
    if os.name != "nt":
        return "/bin/bash" if Path("/bin/bash").exists() else None
    git = shutil.which("git")
    if not git:
        return None
    for root in Path(git).resolve().parents:
        for cand in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
            if cand.is_file():
                return str(cand)
    return None


_BASH = _posix_bash()
_NEEDS_BASH = pytest.mark.skipif(
    not _BASH, reason="the deployed fences are bash; no POSIX bash on this host",
)


@pytest.fixture(scope="module")
def trees(tmp_path_factory):
    """One init'd tree per stack, built on first use, shared read-only."""
    cache: dict[str, Path] = {}

    def get(stack: str) -> Path:
        if stack not in cache:
            cache[stack] = build_adopter_tree(
                tmp_path_factory.mktemp(f"defaults-{stack}"), stack=stack,
            )
        return cache[stack]

    return get


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fences(tree: Path) -> list[str]:
    """The ```bash fences of the /preflight body init deployed into ``tree``."""
    body = (tree / ".claude" / "commands" / "preflight.md").read_text(encoding="utf-8")
    return re.findall(r"```bash\n(.*?)```", body, re.S)


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)


def _run_fence(tree: Path, fence: str, scratch: Path) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run one deployed fence from ``tree`` with stub ``ruff``, ``pytest``,
    the Node package managers, ``go``, ``cargo`` and ``golangci-lint`` first
    on PATH, each logging its argv and succeeding, ``ruff`` also leaving the
    cache directory a real one writes.
    A command whose stub is NOT on PATH fails the fence, so a passing call
    list proves the stub ran. The interpreter the
    fence's resolver picks is this one (a working ``python3`` stub from the
    shared interpreter-host builder) importing this checkout's engine."""
    bin_dir = hosts.build_host(scratch, hosts.PYTHON3_ONLY, hosts.SH)
    log = scratch / "stub.log"
    log_posix = log.as_posix()
    _stub(
        bin_dir, "ruff",
        f'echo "ruff $*" >> "{log_posix}"\n'
        'case " $* " in *" --no-cache "*) ;; *) mkdir -p .ruff_cache ;; esac',
    )
    _stub(bin_dir, "pytest", f'echo "pytest $*" >> "{log_posix}"')
    for binary in ("npm", "pnpm", "bun", "go", "cargo", "golangci-lint"):
        _stub(bin_dir, binary, f'echo "{binary} $*" >> "{log_posix}"')
    env = {
        **os.environ,
        "PATH": hosts.path_with(bin_dir),
        "PYTHONPATH": str(REPO_ROOT),
    }
    proc = subprocess.run(
        [_BASH, "-c", fence], cwd=str(tree), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, env=env,
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return proc, calls


class TestTheFingerprintReadsTheStack:
    @pytest.mark.parametrize("stack", STACKS)
    def test_the_language_and_the_ui_surface(self, trees, stack):
        fp = _read_json(trees(stack) / "reports" / "repo_fingerprint.json")
        assert _LANGUAGE[stack] in fp["languages"], fp["languages"]
        # The Node tree's only UI file is src/pages/index.astro beside an
        # `astro` dependency: neither read as a UI surface before.
        assert fp["ui_surface"] is _is_node(stack), fp["ui_surface"]

    @pytest.mark.parametrize("stack", STACKS)
    def test_the_package_manager(self, trees, stack):
        fp = _read_json(trees(stack) / "reports" / "repo_fingerprint.json")
        assert fp["package_manager"].get("name", "") == _manager(stack), fp["package_manager"]


class TestThePlanCarriesTheRepositorysCommands:
    @pytest.mark.parametrize("stack", STACKS)
    def test_lint_and_build_reach_stable_actions(self, trees, stack):
        plan = _read_json(trees(stack) / "reports" / "harness_config.json")
        actions = plan["stable_actions"]
        if _is_node(stack):
            commands = _NODE_COMMANDS[stack]
            assert actions["lint"] == [commands["lint"]], actions
            assert actions["build"] == [commands["build"]], actions
            assert actions["test"] == [commands["test"]], actions
        else:
            assert actions["test"] == [_TEST_COMMAND[stack]], actions
            assert "lint" not in actions and "build" not in actions, actions
        commands_md = (trees(stack) / "cc" / "COMMANDS.md").read_text(encoding="utf-8")
        for name, cmds in actions.items():
            if name in ("lint", "build"):
                assert f"`{cmds[0]}`" in commands_md, (name, commands_md)

    @pytest.mark.parametrize("stack", STACKS)
    def test_a_bodiless_agent_is_a_suggestion_never_an_agent(self, trees, stack):
        plan = _read_json(trees(stack) / "reports" / "harness_config.json")
        agents = [a["name"] for a in plan["agents"]]
        suggested = [a["name"] for a in plan["suggested_agents"]]
        assert "component-reviewer" not in agents, agents
        assert suggested == (["component-reviewer"] if _is_node(stack) else []), suggested
        for name in agents:
            assert (trees(stack) / ".claude" / "agents" / f"{name}.md").is_file(), name


class TestTheRenderedAllowRules:
    @pytest.mark.parametrize("stack", STACKS)
    def test_rules_are_narrow_and_python_rules_go_to_python_only(self, trees, stack):
        allow = _read_json(trees(stack) / ".claude" / "settings.json")["permissions"]["allow"]
        bash = {r for r in allow if r.startswith("Bash(")}
        bare = {
            r for r in bash
            if re.fullmatch(r"Bash\((npm|pnpm|yarn|bun|cargo|go|make|(npm|pnpm|yarn|bun) run) \*\)", r)
        }
        assert not bare, sorted(bare)
        if _is_node(stack):
            assert not (PYTHON_ONLY_ALLOWS & bash), sorted(PYTHON_ONLY_ALLOWS & bash)
            expected = {
                rule for command in _NODE_COMMANDS[stack].values()
                for rule in (f"Bash({command})", f"Bash({command} *)")
            }
            assert expected <= bash, sorted(expected - bash)
            others = [m for m in _MANAGERS if m != _manager(stack)]
            assert not any(r.startswith(f"Bash({m} ") for r in bash for m in others), sorted(bash)
        elif stack == "python":
            assert PYTHON_ONLY_ALLOWS <= bash, sorted(PYTHON_ONLY_ALLOWS - bash)
            assert not any(r.startswith(f"Bash({m}") for r in bash for m in _MANAGERS), sorted(bash)
        else:
            # A Go or Rust tree: its own narrowed test rules, no Python rule,
            # no Node manager's.
            verb = _RUNNER_VERB[stack]
            assert {f"Bash({verb})", f"Bash({verb} *)"} <= bash, sorted(bash)
            assert not (PYTHON_ONLY_ALLOWS & bash), sorted(PYTHON_ONLY_ALLOWS & bash)
            assert not any(r.startswith(f"Bash({m}") for r in bash for m in _MANAGERS), sorted(bash)


class TestTheRunnerAgentsRunTheRepositorysTests:
    @pytest.mark.parametrize("stack", STACKS)
    def test_the_deployed_tools_line_carries_the_runner(self, trees, stack):
        """The reviewer and the test-writer shipped with `python` and
        `pytest` only, so on a Node tree neither could run `npm test`."""
        from espalier.cli import preview_managed_surface

        tree = trees(stack)
        tools = {
            name: re.search(r"^tools:(.*)$", (tree / ".claude" / "agents" / f"{name}.md")
                            .read_text(encoding="utf-8"), re.M).group(1)
            for name in ("code-reviewer", "test-writer")
        }
        if _is_node(stack):
            test = _NODE_COMMANDS[stack]["test"]
            for name, line in tools.items():
                assert f"Bash({test} *)" in line, (name, line)
                assert not any(f"Bash({m} *)" in line for m in _MANAGERS), (name, line)
        elif stack == "python":
            assert "Bash(pytest -q *)" in tools["code-reviewer"], tools
            assert "Bash(pytest *)" in tools["test-writer"], tools
        else:
            verb = _RUNNER_VERB[stack]
            for name, line in tools.items():
                assert f"Bash({verb} *)" in line, (name, line)
                assert not any(f"Bash({m} *)" in line for m in _MANAGERS), (name, line)
        # The upgrade preview renders the same body, so a current tree is current.
        surface = preview_managed_surface(tree, goal_snapshot=True)
        stale = [p for p in surface["updated_managed"] if p.startswith(".claude/agents/")]
        assert not stale, stale


class TestDoctorsHeadline:
    @pytest.mark.parametrize("stack", STACKS)
    def test_a_healthy_install_headlines_a_next_step(self, trees, stack):
        result = run_doctor_check(trees(stack), skip_self_host=True)
        assert result["status"] == "pass", (result["failures"], result["warnings"])
        assert result["primary_reason"] in result["next_steps"], result["primary_reason"]
        assert not any("agent" in line for line in result["info"]), result["info"]
        assert not any("allow rule" in line for line in result["info"]), result["info"]


#: Per stack: a root-level source file, a source file under the tree, and a
#: documentation file in the stack's own docs format.
_SOURCES = {
    "python": ("app.py", "src/demo/app.py", "docs/guide.md"),
    "node": ("index.mjs", "src/index.mjs", "src/pages/guide.mdx"),
    "node-pnpm": ("index.mjs", "src/index.mjs", "src/pages/guide.mdx"),
    "node-bun": ("index.mjs", "src/index.mjs", "src/pages/guide.mdx"),
    "go": ("main.go", "internal/greet.go", "docs/guide.md"),
    "rust": ("build.rs", "src/lib.rs", "docs/guide.md"),
}


def _hook(tree: Path, name: str, payload: dict) -> subprocess.CompletedProcess:
    """Run the hook ``init`` DEPLOYED into ``tree`` on one event, rooted there,
    with the maintenance switch and the stop-gate mode of this shell removed
    (the lane that wrote this ran under maintenance mode; a gate under it
    proves nothing)."""
    env = {
        k: v for k, v in os.environ.items()
        if k not in ("ESPALIER_MAINTENANCE_MODE", "ESPALIER_STOP_GATE", "ESPALIER_STOP_GATE_TEST_CMD")
    }
    env["CLAUDE_PROJECT_DIR"] = str(tree)
    return subprocess.run(
        [hosts.HOOK_PYTHON, str(tree / "tools" / "cc" / "hooks" / name)],
        input=json.dumps({"session_id": "c57", "cwd": str(tree), **payload}),
        cwd=str(tree), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=60, env=env,
    )


class TestASessionOnTheTreeIsGoverned:
    @pytest.mark.parametrize("stack", STACKS)
    def test_the_hooks_govern_a_session_on_the_tree(self, trees, stack, tmp_path):
        """The chain the adopter-axes pack measured by hand (its Task 0-D), on
        a copy of each init'd tree: a root-level source file needs a plan; ten
        source writes arm the hygiene gates; Stop blocks at the docs gate; the
        adopter's own agents, declared in espalier.toml, relieve both gates;
        and Stop then lets the turn end. On the Node tree before the fix the
        root ``index.mjs`` was written with no plan, the write count never
        started and Stop allowed; only a reviewer named ``code-reviewer``
        relieved Gate 3, and a docs run that edited ``.mdx`` changed nothing.

        The tree is the stack's: its fingerprint names the stack's package
        manager (the axis registry reads the parameter and cannot see the
        tree, so this is the second witness)."""
        tree = Path(shutil.copytree(trees(stack), tmp_path / "tree"))
        root_file, source, doc = _SOURCES[stack]
        fp = _read_json(tree / "reports" / "repo_fingerprint.json")
        assert fp["package_manager"].get("name", "") == _manager(stack), fp["package_manager"]

        verdict = _hook(tree, "plan_guard.py", {
            "hook_event_name": "PreToolUse", "tool_name": "Write",
            "tool_input": {"file_path": str(tree / root_file), "content": "x = 1\n"},
        })
        assert '"permissionDecision": "deny"' in verdict.stdout, (verdict.stdout, verdict.stderr)

        for _ in range(10):
            _hook(tree, "reflect_trigger.py", {
                "hook_event_name": "PostToolUse", "tool_name": "Write",
                "tool_input": {"file_path": str(tree / source)},
                "tool_response": {"filePath": str(tree / source), "success": True},
            })
        count = tree / ".espalier-state" / "write_count"
        assert count.is_file() and count.read_text(encoding="utf-8").strip() == "10", (
            count.read_text(encoding="utf-8") if count.is_file() else "no write_count"
        )

        stop = _hook(tree, "stop_gate.py", {"hook_event_name": "Stop", "stop_hook_active": False})
        assert json.loads(stop.stdout)["decision"] == "block", (stop.stdout, stop.stderr)

        # The adopter's own agents, each with a body, declared for the gates.
        (tree / "espalier.toml").write_text(
            'code_review_agents = ["site-reviewer"]\ndocs_refresh_agents = ["site-docs"]\n',
            encoding="utf-8",
        )
        for name in ("site-reviewer", "site-docs"):
            (tree / ".claude" / "agents" / f"{name}.md").write_text(
                f"---\nname: {name}\ndescription: the adopter's own\n---\nbody\n", encoding="utf-8",
            )
        blocked = _hook(tree, "stop_gate.py", {"hook_event_name": "Stop", "stop_hook_active": False})
        assert "`site-docs`" in json.loads(blocked.stdout)["reason"], blocked.stdout
        # Commit what init and the setup wrote, so the docs evidence the
        # relief record lists is the one documentation edit below.
        for args in (["add", "-A"], ["commit", "-qm", "harness"]):
            subprocess.run(["git", *args], cwd=str(tree), check=True, capture_output=True)
        (tree / doc).parent.mkdir(parents=True, exist_ok=True)
        (tree / doc).write_text("# Guide\n", encoding="utf-8")
        for agent in ("site-docs", "site-reviewer"):
            ran = _hook(tree, "subagent_stop.py", {
                "hook_event_name": "SubagentStop", "agent_type": agent,
                "last_assistant_message": "Reviewed the change; no blocking findings.",
            })
            assert ran.returncode == 0, ran.stderr
        docs = json.loads((tree / ".espalier-state" / "docs_refreshed").read_text(encoding="utf-8"))
        assert docs["changed_docs"] == [doc], docs
        review = json.loads((tree / ".espalier-state" / "code_reviewed").read_text(encoding="utf-8"))
        assert review["agent"] == "site-reviewer", review

        stop = _hook(tree, "stop_gate.py", {"hook_event_name": "Stop", "stop_hook_active": False})
        assert '"decision": "block"' not in stop.stdout, stop.stdout


@_NEEDS_BASH
class TestTheDeployedPreflightFences:
    @pytest.mark.parametrize("stack", STACKS)
    def test_step_one_lints_with_the_repositorys_own_linter(self, trees, stack, tmp_path):
        tree = trees(stack)
        proc, calls = _run_fence(tree, _fences(tree)[0], tmp_path)
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        assert not any(c.startswith("pytest") for c in calls), calls
        assert not (tree / ".ruff_cache").exists(), "a ruff run left its cache in the adopter's tree"
        if _is_node(stack):
            # A Node project: no PATH ruff touches it, and its own script runs
            # under its own package manager.
            lint = _NODE_COMMANDS[stack]["lint"]
            assert calls == [lint], calls
            assert f"/preflight lint gate: {lint}" in proc.stderr, proc.stderr
        else:
            # The Python control configures no ruff, so the guarded fallback
            # for a Python project runs the PATH ruff -- without the harness's
            # vendored tools/cc/ and without a cache (the failure-mode review:
            # a Python adopter that keeps ruff only in its dev requirements).
            # The Go and Rust trees declare no lint either: the ladder's own
            # branch runs their linter when it is on PATH.
            assert calls == [_LINT_FALLBACK[stack]], calls

    @pytest.mark.parametrize("stack", STACKS)
    def test_step_two_runs_the_repositorys_tests_then_its_build(self, trees, stack, tmp_path):
        tree = trees(stack)
        proc, calls = _run_fence(tree, _fences(tree)[1], tmp_path)
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        if _is_node(stack):
            commands = _NODE_COMMANDS[stack]
            assert calls == [commands["test"], commands["build"]], calls
        else:
            assert calls == [_TEST_COMMAND[stack]], calls
            assert "No build command declared or detected" in proc.stdout, proc.stdout

    def test_a_failing_declared_lint_stops_the_run(self, trees, tmp_path):
        """The declared command's exit status is the gate's: a red lint is
        NO-GO, never a skip."""
        tree = trees("node")
        fence = _fences(tree)[0]
        bin_dir = hosts.build_host(tmp_path, hosts.PYTHON3_ONLY, hosts.SH)
        _stub(bin_dir, "npm", "exit 3")
        proc = subprocess.run(
            [_BASH, "-c", fence], cwd=str(tree), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
            env={**os.environ, "PATH": hosts.path_with(bin_dir), "PYTHONPATH": str(REPO_ROOT)},
        )
        assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
