"""The shipped bodies say what they stood down from (the forward ledger's
class on adopter-side stand-downs, skips and failures).

Each deployed body here was written on this repository and runs a check whose
input an adopter's tree supplies in another shape, then reads the gap as a
clean result. The harness-config-advisor took a hook's script from
``command`` alone, while ``espalier init`` writes every hook in exec form (the
interpreter alone in ``command``, the script in ``args[]``), so its inventory
printed each init-written hook as unresolvable and its dead-config pass printed
CLEAN over a deleted hook script: the branch that flags one could never fire.
The architecture-analyst keyed each of the harness's own checks on
``[ -d tools/cc/ ]``, a directory every adopter holds as the harness's deployed
copy, so on an adopter's tree it audited that copy and called it clean, and its
circular-import step imported the installed ``espalier`` in place of the
adopter's package; docs-maintainer's two ``tools/cc`` checks did the same. Each
now keys on the self-host block ``init`` strips, and its fallback says what it
skipped and why or reads the adopter's own packages. The repo-analyst's drift
block and docs-maintainer's docs probe read the fingerprint's baseline from
``git log -- reports/repo_fingerprint.json``, a history no default install has
(``init`` gitignores ``reports/``), so the one fell back to a five-commit window
and the other never fired; the fingerprint now records the commit it was taken
at, and both diff from it or say there is no baseline.

One oracle, the sibling module's (``tests/test_first_contact_diagnostics.py``):
``espalier init`` into the Python adopter tree ``tests/_adopter_tree.py``
builds, then each DEPLOYED program read from the init'd tree and run verbatim
from a tree's root (the advisor's under a Python with UTF-8 mode off, as the
sibling drives its dead-config pass; the bash fences under a real POSIX bash
and, where the host has one, zsh, whose unmatched glob aborts a command, with
``python`` on the path naming the interpreter running this suite). This
checkout is the control, its bodies keeping the blocks ``init`` strips. Every
expected line is written from what the tree holds, never from an engine
symbol, so a row reds by its assertion at a base whose body lacks the fix.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from _adopter_tree import build_adopter_tree
from _stubs import write_stub

REPO_ROOT = Path(__file__).resolve().parent.parent

ADVISOR = ".claude/agents/harness-config-advisor.md"
ANALYST = ".claude/agents/architecture-analyst.md"
DOCS_MAINTAINER = ".claude/agents/docs-maintainer.md"
#: The architecture-analyst's steps, by the heading each fence follows.
STEP = {n: f"### Step {n} " for n in range(2, 7)}
SHARP_EDGES = "**docs/SHARP_EDGES.md"
REPO_ANALYST = ".claude/agents/repo-analyst.md"
DRIFT = "### 6. DRIFT DETECTION"
FRESHNESS = "## Phase 1: Freshness Audit"
INVENTORY = "## Phase 1: Current Setup Inventory"
DEAD_CONFIG = "### Dead-Config Pass"
CLEAN = "Dead-config pass: CLEAN"

#: Below the suite's 60 s ceiling for a test, which the contract reads off
#: every wait budget in the module.
FENCE_TIMEOUT = 45


def _posix_bash() -> str | None:
    """A real POSIX bash: ``/bin/bash`` off Windows; on Windows, Git Bash found
    beside ``git``, never a bare ``bash`` (the WSL shim). The sibling module's
    lookup."""
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
_ZSH = shutil.which("zsh") if os.name != "nt" else None
_NEEDS_BASH = pytest.mark.skipif(
    not _BASH, reason="the deployed fences are bash; no POSIX bash on this host",
)
SHELLS = [pytest.param(_BASH, id="bash")] + (
    [pytest.param(_ZSH, id="zsh")] if _ZSH else []
)


@pytest.fixture(scope="module")
def pybin(tmp_path_factory) -> Path | None:
    """A folder whose ``python`` runs this suite's interpreter: the fences call
    ``python`` by name, and a host may ship only ``python3``. None on Windows,
    whose installs answer to ``python``."""
    if os.name == "nt":
        return None
    folder = tmp_path_factory.mktemp("pybin")
    write_stub(folder / "python", f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    return folder


@pytest.fixture(scope="module")
def adopter(tmp_path_factory) -> Path:
    """The init'd Python adopter tree, built once, read only."""
    return build_adopter_tree(tmp_path_factory.mktemp("stand-downs"), stack="python")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _fence_after(body: str, heading: str) -> str:
    """The first ```bash fence after ``heading``."""
    tail = body[body.index(heading):]
    match = re.search(r"```bash\n(.*?)```", tail, re.S)
    assert match, f"no bash fence after {heading!r}"
    return match.group(1)


def _run(tree: Path, fence: str, pybin: Path | None, shell: str | None = None) -> subprocess.CompletedProcess:
    """One deployed fence from ``tree``'s root under ``shell`` (bash by default)."""
    env = dict(os.environ)
    if pybin is not None:
        env["PATH"] = str(pybin) + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [shell or _BASH, "-c", fence], cwd=str(tree), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=FENCE_TIMEOUT, env=env,
    )


#: A grep hit on a harness file: what a stood-down check must never print.
HARNESS_HIT = re.compile(r"^tools/cc/\S+\.py:\d+:", re.M)


def _heredoc_after(body: str, heading: str) -> str:
    """The first ``python - <<'EOF'`` program after ``heading``."""
    tail = body[body.index(heading):]
    match = re.search(r"python3? - <<'EOF'\n(.*?)\nEOF", tail, re.S)
    assert match, f"no python heredoc after {heading!r}"
    return match.group(1)


def _advisor(tree: Path, program: str) -> subprocess.CompletedProcess:
    """One of the advisor's programs, from ``tree``'s root, UTF-8 mode off."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUTF8"}
    env.update(PYTHONIOENCODING="utf-8", LC_ALL="C", PYTHONCOERCECLOCALE="0")
    return subprocess.run(
        [sys.executable, "-X", "utf8=0", "-c", program], cwd=str(tree),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=FENCE_TIMEOUT, env=env,
    )


def _hooks(tree: Path) -> list[tuple[str, dict]]:
    data = json.loads(_read(tree / ".claude" / "settings.json"))
    return [
        (event, h) for event, entries in data["hooks"].items()
        for entry in entries for h in entry["hooks"]
    ]


def _wire(tree: Path, hooks: dict) -> Path:
    """A tree whose only wiring is ``hooks`` (event -> commands)."""
    settings = {"hooks": {
        event: [{"hooks": [{"type": "command", **h} for h in handlers]}]
        for event, handlers in hooks.items()
    }}
    (tree / ".claude").mkdir(parents=True)
    (tree / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    return tree


class TestTheAdvisorReadsTheScriptWhereInitWritesIt:
    """The inventory and the dead-config pass read a hook's script from
    ``args[]`` and from ``command``, as ``/smoke``'s hook check does, and a hook
    that names no script file is reported as not checked, never as clean."""

    def test_init_writes_the_script_in_args(self, adopter):
        """The premise the advisor missed: a bare interpreter in ``command``."""
        hooks = _hooks(adopter)
        assert len(hooks) >= 10, hooks
        for event, h in hooks:
            assert not h["command"].endswith(".py"), (event, h)
            assert h["args"][-1].endswith(".py"), (event, h)

    def test_the_inventory_names_every_hook_script_on_the_adopters_tree(self, adopter):
        proc = _advisor(adopter, _heredoc_after(_read(adopter / ADVISOR), INVENTORY))
        assert proc.returncode == 0, proc.stderr[-800:]
        rows = [line for line in proc.stdout.splitlines() if " timeout=" in line]
        hooks = _hooks(adopter)
        assert len(rows) == len(hooks), proc.stdout
        for event, h in hooks:
            row = f"  {event}: {Path(h['args'][-1]).name} [OK] timeout="
            assert any(line.startswith(row) for line in rows), (row, proc.stdout)
        assert "unresolvable" not in proc.stdout and "not checked" not in proc.stdout, proc.stdout

    def test_a_deleted_hook_script_is_named_by_both_programs(self, adopter, tmp_path):
        tree = tmp_path / "tree"
        shutil.copytree(adopter / ".claude", tree / ".claude")
        shutil.copytree(adopter / "tools", tree / "tools")
        (tree / "tools" / "cc" / "hooks" / "stop_gate.py").unlink()
        body = _read(adopter / ADVISOR)
        inventory = _advisor(tree, _heredoc_after(body, INVENTORY))
        assert inventory.returncode == 0, inventory.stderr[-800:]
        assert "  Stop: stop_gate.py [MISSING]" in inventory.stdout, inventory.stdout
        dead = _advisor(tree, _heredoc_after(body, DEAD_CONFIG))
        assert dead.returncode == 0, dead.stderr[-800:]
        assert "DEAD CONFIG (1 issues):" in dead.stdout, dead.stdout
        assert "DEAD HOOK: Stop -> stop_gate.py not found at" in dead.stdout, dead.stdout
        total = len(_hooks(adopter))
        assert f"Hook scripts: {total} of {total} hooks checked" in dead.stdout, dead.stdout
        assert CLEAN not in dead.stdout, dead.stdout

    def test_a_hook_naming_no_script_file_is_never_read_as_clean(self, adopter, tmp_path):
        tree = _wire(tmp_path / "tree", {"PostToolUse": [{"command": "npx prettier --write ."}]})
        body = _read(adopter / ADVISOR)
        dead = _advisor(tree, _heredoc_after(body, DEAD_CONFIG))
        assert dead.returncode == 0, dead.stderr[-800:]
        assert "Hook scripts: 0 of 1 hooks checked" in dead.stdout, dead.stdout
        assert "NOT CHECKED (1 hooks name no script file" in dead.stdout, dead.stdout
        assert "  ? PostToolUse: npx prettier --write ." in dead.stdout, dead.stdout
        assert CLEAN not in dead.stdout, dead.stdout
        inventory = _advisor(tree, _heredoc_after(body, INVENTORY))
        assert "PostToolUse: npx prettier --write . [names no script file: not checked]" in (
            inventory.stdout), inventory.stdout

    def test_a_shell_form_hook_is_read_from_its_command(self, adopter, tmp_path):
        """The legacy shell form: a quoted script, a bare one, and one present."""
        tree = _wire(tmp_path / "tree", {
            "PreToolUse": [{"command": 'python3 "${CLAUDE_PROJECT_DIR}/hooks/quoted_gone.py"'}],
            "Stop": [{"command": "python3 hooks/bare_gone.py --strict"}],
            "SessionStart": [{"command": "bash hooks/here.sh"}],
            # the quoting Claude Code's docs use: the variable is one shell word with the path
            "PostToolUse": [{"command": 'python3 "$CLAUDE_PROJECT_DIR"/hooks/quoted_here.py'}],
        })
        (tree / "hooks").mkdir()
        (tree / "hooks" / "here.sh").write_text("exit 0\n", encoding="utf-8")
        (tree / "hooks" / "quoted_here.py").write_text("x = 1\n", encoding="utf-8")
        dead = _advisor(tree, _heredoc_after(_read(adopter / ADVISOR), DEAD_CONFIG))
        assert dead.returncode == 0, dead.stderr[-800:]
        assert "Hook scripts: 4 of 4 hooks checked" in dead.stdout, dead.stdout
        assert "DEAD CONFIG (2 issues):" in dead.stdout, dead.stdout
        assert "DEAD HOOK: PreToolUse -> quoted_gone.py not found at" in dead.stdout, dead.stdout
        assert "DEAD HOOK: Stop -> bare_gone.py not found at" in dead.stdout, dead.stdout
        assert "here.sh" not in dead.stdout and "quoted_here" not in dead.stdout, dead.stdout

    def test_a_tree_without_settings_says_no_wiring_was_checked(self, adopter, tmp_path):
        tree = tmp_path / "tree"
        (tree / ".claude").mkdir(parents=True)
        dead = _advisor(tree, _heredoc_after(_read(adopter / ADVISOR), DEAD_CONFIG))
        assert dead.returncode == 0, dead.stderr[-800:]
        assert "Hook scripts: no .claude/settings.json, so no hook wiring was checked" in (
            dead.stdout), dead.stdout

    def test_on_this_checkout(self):
        """The control: a gitignored settings file is present on a working
        checkout and absent on a CI one; either way the pass says which."""
        dead = _advisor(REPO_ROOT, _heredoc_after(_read(REPO_ROOT / ADVISOR), DEAD_CONFIG))
        assert dead.returncode == 0, dead.stderr[-800:]
        assert re.search(r"^Hook scripts: (\d+) of \1 hooks checked$|^Hook scripts: no ",
                         dead.stdout, re.M), dead.stdout
        assert CLEAN in dead.stdout, dead.stdout


@_NEEDS_BASH
class TestTheArchitectureChecksKeyOnTheRepository:
    """Steps 2 to 6 run the harness's own checks inside the self-host block and,
    where ``init`` stripped it, say what they skipped or read the adopter's
    packages; under zsh no step aborts on a glob."""

    @pytest.mark.parametrize("shell", SHELLS)
    @pytest.mark.parametrize("step", (2, 3, 4))
    def test_the_harness_rules_stand_down_in_words_on_the_adopters_tree(
        self, adopter, pybin, step, shell,
    ):
        proc = _run(adopter, _fence_after(_read(adopter / ANALYST), STEP[step]), pybin, shell)
        assert "  SKIPPED: " in proc.stdout, (proc.stdout, proc.stderr)
        assert "CLEAN" not in proc.stdout, proc.stdout
        assert not HARNESS_HIT.search(proc.stdout), proc.stdout
        assert "no matches found" not in proc.stderr, proc.stderr

    @pytest.mark.parametrize("shell", SHELLS)
    def test_step_5_imports_the_adopters_package(self, adopter, pybin, shell):
        proc = _run(adopter, _fence_after(_read(adopter / ANALYST), STEP[5]), pybin, shell)
        assert "  demo: No circular imports detected (smoke check only)" in proc.stdout, (
            proc.stdout, proc.stderr)
        assert "espalier" not in proc.stdout, proc.stdout

    @pytest.mark.parametrize("shell", SHELLS)
    def test_step_6_sizes_the_adopters_packages(self, adopter, pybin, shell):
        proc = _run(adopter, _fence_after(_read(adopter / ANALYST), STEP[6]), pybin, shell)
        modules = len(list((adopter / "src" / "demo").rglob("*.py")))
        assert f"  src/demo/: {modules} files" in proc.stdout, (proc.stdout, proc.stderr)
        assert "(engine)" not in proc.stdout and "(enforcement)" not in proc.stdout, proc.stdout
        # The tree holds its one initial commit: no window, and it says so.
        assert "  fewer than four commits (or no git): no three-commit window to read" in (
            proc.stdout), proc.stdout
        assert "no matches found" not in proc.stderr, proc.stderr

    @pytest.mark.parametrize("step", (5, 6))
    def test_a_tree_without_a_package_says_so(self, adopter, pybin, tmp_path, step):
        tree = tmp_path / "tree"
        (tree / "lib").mkdir(parents=True)
        (tree / "lib" / "loose.py").write_text("x = 1\n", encoding="utf-8")
        proc = _run(tree, _fence_after(_read(adopter / ANALYST), STEP[step]), pybin)
        assert "no top-level Python package here (a folder holding __init__.py at the root" in (
            proc.stdout), (proc.stdout, proc.stderr)

    def test_on_this_checkout(self, pybin):
        """The control: the blocks are kept, so every step runs the harness's
        own check and none stands down."""
        body = _read(REPO_ROOT / ANALYST)
        outs = {n: _run(REPO_ROOT, _fence_after(body, STEP[n]), pybin).stdout for n in STEP}
        assert not [n for n, out in outs.items() if "SKIPPED" in out], outs
        # A lead grep: on this tree it reads comments that name the rule.
        assert "  CLEAN" in outs[2] or HARNESS_HIT.search(outs[2]), outs[2]
        assert "=== Non-stdlib imports in scanners (should be empty) ===" in outs[3], outs[3]
        assert "=== Hook stdout usage" in outs[4], outs[4]
        assert "  espalier: No circular imports detected (smoke check only)" in outs[5], outs[5]
        assert "  espalier/ (engine): " in outs[6] and "  tools/cc/ (enforcement): " in outs[6], outs[6]


@_NEEDS_BASH
class TestTheDocsMaintainersHarnessChecksStandDown:
    """The exit-1 and isolation checks read ``tools/cc/`` on this repository
    alone, and say so where ``init`` stripped them."""

    @pytest.mark.parametrize("shell", SHELLS)
    def test_on_the_adopters_tree(self, adopter, pybin, shell):
        proc = _run(adopter, _fence_after(_read(adopter / DOCS_MAINTAINER), SHARP_EDGES), pybin, shell)
        assert "=== Harness source checks ===" in proc.stdout, (proc.stdout, proc.stderr)
        assert "  SKIPPED: the exit-1 and isolation checks read the harness's own tools/cc/" in (
            proc.stdout), proc.stdout
        assert "isolation check (documented sharp edge)" not in proc.stdout, proc.stdout
        assert not HARNESS_HIT.search(proc.stdout), proc.stdout

    def test_on_this_checkout(self, pybin):
        proc = _run(REPO_ROOT, _fence_after(_read(REPO_ROOT / DOCS_MAINTAINER), SHARP_EDGES), pybin)
        assert "=== Hook exit code 1 check (documented sharp edge) ===" in proc.stdout, proc.stdout
        assert "=== tools/cc/ isolation check (documented sharp edge) ===" in proc.stdout, proc.stdout
        assert "SKIPPED" not in proc.stdout, proc.stdout


def _git(tree: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(tree), check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout.strip()


@pytest.fixture
def committed_since(adopter, tmp_path) -> tuple[Path, str]:
    """A copy of the adopter tree with one commit made after ``init`` took its
    fingerprint (a module and a doc), and the commit the fingerprint names."""
    tree = tmp_path / "tree"
    shutil.copytree(adopter, tree, symlinks=True)
    taken = json.loads(_read(tree / "reports" / "repo_fingerprint.json")).get("head_sha", "")
    (tree / "src" / "demo" / "added.py").write_text("y = 2\n", encoding="utf-8")
    (tree / "GUIDE.md").write_text("# Guide\n", encoding="utf-8")
    _git(tree, "add", "src/demo/added.py", "GUIDE.md")
    _git(tree, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "later")
    return tree, taken


@_NEEDS_BASH
class TestTheDriftBaselineIsTheCommitTheFingerprintWasTakenAt:
    """``init`` writes the fingerprint with the commit it was taken at; the two
    drift probes diff from that commit, and with none recorded they say there
    is no baseline instead of substituting a recent-commits window."""

    def test_init_records_the_commit(self, adopter):
        fingerprint = json.loads(_read(adopter / "reports" / "repo_fingerprint.json"))
        assert fingerprint.get("head_sha") == _git(adopter, "rev-parse", "HEAD"), fingerprint.get("head_sha")
        assert _git(adopter, "check-ignore", "reports/repo_fingerprint.json")

    @pytest.mark.parametrize("shell", SHELLS)
    def test_the_repo_analyst_diffs_from_it(self, adopter, committed_since, pybin, shell):
        tree, taken = committed_since
        proc = _run(tree, _fence_after(_read(adopter / REPO_ANALYST), DRIFT), pybin, shell)
        out = proc.stdout
        assert f"  Comparing against the commit the fingerprint was taken at: {taken}" in out, (
            out, proc.stderr)
        assert "src/demo/added.py" in out.splitlines(), out
        assert f"  taken at {taken} (" in out, out
        assert "HEAD~5" not in out and "no baseline" not in out, out

    @pytest.mark.parametrize("shell", SHELLS)
    def test_docs_maintainer_lists_the_docs_changed_since(self, adopter, committed_since, pybin, shell):
        tree, _ = committed_since
        proc = _run(tree, _fence_after(_read(adopter / DOCS_MAINTAINER), FRESHNESS), pybin, shell)
        section = proc.stdout.split("=== Docs changed since last fingerprint ===", 1)[1]
        assert section.split() == ["GUIDE.md"], (section, proc.stderr)

    def test_a_host_whose_python_is_python3_alone_reads_the_baseline(
        self, adopter, committed_since, tmp_path,
    ):
        """The probes find an interpreter as the bodies' resolver does: a
        ``python`` that answers nothing (stock macOS ships ``python3`` alone)
        leaves the baseline read, never reported missing."""
        tree, taken = committed_since
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for name, body in (("python", "exit 127\n"), ("python3", f'exec "{sys.executable}" "$@"\n')):
            write_stub(bin_dir / name, "#!/bin/sh\n" + body)
        drift = _run(tree, _fence_after(_read(adopter / REPO_ANALYST), DRIFT), bin_dir).stdout
        assert f"  Comparing against the commit the fingerprint was taken at: {taken}" in drift, drift
        docs = _run(tree, _fence_after(_read(adopter / DOCS_MAINTAINER), FRESHNESS), bin_dir).stdout
        assert docs.split("=== Docs changed since last fingerprint ===", 1)[1].split() == ["GUIDE.md"], docs

    @pytest.mark.parametrize("recorded", ["", "0" * 40], ids=["none-recorded", "not-in-this-clone"])
    def test_without_a_baseline_both_say_so(self, adopter, committed_since, pybin, recorded):
        tree, _ = committed_since
        path = tree / "reports" / "repo_fingerprint.json"
        fingerprint = json.loads(_read(path))
        if recorded:
            fingerprint["head_sha"] = recorded
        else:
            fingerprint.pop("head_sha", None)  # a report an older release wrote
        path.write_text(json.dumps(fingerprint), encoding="utf-8")
        drift = _run(tree, _fence_after(_read(adopter / REPO_ANALYST), DRIFT), pybin).stdout
        assert "  no baseline: the saved fingerprint records no commit this clone holds" in drift, drift
        assert "  NOT EVALUATED: no baseline commit (above)" in drift, drift
        assert "HEAD~5" not in drift and "src/demo/added.py" not in drift, drift
        docs = _run(tree, _fence_after(_read(adopter / DOCS_MAINTAINER), FRESHNESS), pybin).stdout
        assert "no fingerprint baseline: reports/repo_fingerprint.json records no commit" in docs, docs
        assert "GUIDE.md" not in docs, docs

    def test_a_tree_outside_git_records_none(self, tmp_path):
        from espalier.analyze import fingerprint_repo

        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        assert fingerprint_repo(tmp_path).to_dict().get("head_sha") == ""
