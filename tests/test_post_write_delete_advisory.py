"""The 2026-09-17 incident's driver shape, said at the write.

``tools/cc/hooks/post_write_check.py`` reads a ``.py`` file Claude has just
written or edited, from disk, and on the self-host tree tells Claude (and the
operator, on their own line) when the file hands built text to a shell and holds
a recursive delete of a variable beside a glob: the scratch driver that wiped
the host (``docs/incidents/2026-09-17-real-shell-fixture-wipe.md``, rules 1 and
2). The predicates are frozen from the census that calibrated them.

Each row writes a file into a temp folder outside an isolated, self-host-shaped
project root, as the incident's scratchpad driver sat outside every checkout,
and drives the hook as Claude Code does, the file's path in the payload.
Nothing a row writes is ever executed: the hook reads text.
"""
from __future__ import annotations

import ast
import importlib.util
import itertools
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from tests._hook_runner import run_hook
from tests._live_tree import checkout_glob

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
HOOK = HOOKS_DIR / "post_write_check.py"

#: What every advisory line carries, and what the operator's line carries.
SAID = "the shape of the 2026-09-17 incident"
TOLD = "in the shape of the 2026-09-17 incident"

_DELETE = "rm -rf " + '"$V"' + "/*"
_ROW = "ROWS = [" + repr(_DELETE) + "]\n"
_SPAWN_HEAD = "import subprocess\n\n\ndef run(shell, cmd):\n"

#: The incident's driver: a shell named by a variable, the command built text.
DRIVER = _SPAWN_HEAD + '    return subprocess.run([shell, "-c", cmd], timeout=20)\n\n\n' + _ROW
LITERAL_HEAD = "import subprocess\n\n\ndef run(cmd):\n" + '    return subprocess.run(["bash", "-c", cmd])\n\n\n' + _ROW
POPEN = _SPAWN_HEAD + '    return subprocess.Popen([shell, "-c", cmd])\n\n\n' + _ROW
SHELL_TRUE = "import subprocess\n\n\ndef run(cmd):\n    return subprocess.run(cmd, shell=True)\n\n\n" + _ROW
BRACES = DRIVER.replace('"$V"', '"${V}"')
UNQUOTED = DRIVER.replace('"$V"', "$V")
LITERAL_COMMAND = DRIVER.replace("cmd], timeout", '"ls"], timeout')
NO_DELETE = DRIVER.replace(_ROW, "ROWS = ['ls -la']\n")
#: The guard test's own shape: the delete and a shell=True spelling inside
#: fixture strings, and powershell=True keywords to a helper -- a regex reading
#: takes the tail of the keyword for shell=True; the syntax tree does not.
FIXTURE = (
    "CASES = [\n    'subprocess.run(cmd, shell=True)',\n    " + repr(_DELETE) + ",\n]\n\n\n"
    "def test_rows(guard):\n    assert guard.judge(CASES[1], powershell=True)\n"
    "    assert guard.judge(CASES[0], powershell=True)\n"
)


def _row_line(source: str) -> int:
    return next(i for i, line in enumerate(source.splitlines(), 1) if "rm -rf" in line)


def _project(tmp_path: Path, *, self_host: bool = True) -> Path:
    """An isolated project root: self-host-shaped (the five signals the hooks
    read), or an adopter's tree."""
    root = tmp_path / "project"
    for part in ("espalier", "bench", "tools/cc/hooks"):
        (root / part).mkdir(parents=True)
    name = "espalier-harness" if self_host else "my-app"
    (root / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n', encoding="utf-8")
    if self_host:
        shutil.copy(HOOKS_DIR / "write_guard.py", root / "tools" / "cc" / "hooks" / "write_guard.py")
    return root


def _scratch(tmp_path: Path, name: str, source: str) -> Path:
    """A file outside the project root, as the incident's driver was."""
    folder = tmp_path / "scratch"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_text(source, encoding="utf-8")
    return path


def _drive(root: Path, payload: dict, audit: Path) -> subprocess.CompletedProcess:
    """The hook as Claude Code runs it (the suite's ``run_hook``): JSON on
    stdin, the project at ``root``, an audit folder of its own, and the
    launching shell's maintenance mode off."""
    result = run_hook("post_write_check.py", payload, env_overrides={
        "CLAUDE_PROJECT_DIR": str(root), "ESPALIER_AUDIT_DIR": str(audit),
        "ESPALIER_MAINTENANCE_MODE": None,
    })
    assert result.returncode == 0, result.stderr
    return result


def _write(root: Path, path: Path, session: str = "s1") -> dict:
    return {"session_id": session, "hook_event_name": "PostToolUse", "tool_name": "Write",
            "cwd": str(root),
            "tool_input": {"file_path": str(path), "content": path.read_text(encoding="utf-8")},
            "tool_response": {"filePath": str(path)}}


def _edit(root: Path, path: Path, old: str, new: str, session: str = "s1") -> dict:
    return {"session_id": session, "hook_event_name": "PostToolUse", "tool_name": "Edit",
            "cwd": str(root),
            "tool_input": {"file_path": str(path), "old_string": old, "new_string": new},
            "tool_response": {"filePath": str(path)}}


def _object(stdout: str) -> dict:
    """The ONE JSON object the hook printed, or {} when it printed none."""
    text = stdout.strip()
    if not text:
        return {}
    assert len(text.splitlines()) == 1, f"more than one stdout line: {text!r}"
    return json.loads(text)


def _said_to_claude(result: subprocess.CompletedProcess) -> list[str]:
    context = _object(result.stdout).get("hookSpecificOutput", {}).get("additionalContext", "")
    return [line for line in context.splitlines() if SAID in line]


def _told_operator(result: subprocess.CompletedProcess) -> list[str]:
    return [line for line in _object(result.stdout).get("systemMessage", "").splitlines() if TOLD in line]


def _records(audit: Path, event_type: str) -> list[dict]:
    out = []
    for log in audit.glob("*.log"):
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("event_type") == event_type:
                out.append(json.loads(line))
    return out


def _load_hook():
    """The hook module under an alias, for the rows that ask its predicates directly."""
    spec = importlib.util.spec_from_file_location("_delete_advisory_hook", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestTheIncidentShapeIsSaidAtTheWrite:
    """Fire rows: each shape the census's predicates read, said once with the
    file and the delete's line, and the operator told on their own line."""

    @pytest.mark.parametrize("name,source", [
        ("incident", DRIVER),
        ("literal shell head", LITERAL_HEAD),
        ("Popen", POPEN),
        ("shell=True on built text", SHELL_TRUE),
        ("braced variable", BRACES),
        ("unquoted variable", UNQUOTED),
    ])
    def test_a_write_of_the_shape_is_said(self, tmp_path, name, source):
        root = _project(tmp_path)
        path = _scratch(tmp_path, "drive.py", source)
        result = _drive(root, _write(root, path), tmp_path / "audit")
        said = _said_to_claude(result)
        assert len(said) == 1, f"{name}: {result.stdout!r}"
        assert f"{path}, line {_row_line(source)}:" in said[0], said[0]
        assert "docs/incidents/2026-09-17-real-shell-fixture-wipe.md" in said[0]
        assert len(_told_operator(result)) == 1, result.stdout
        assert _records(tmp_path / "audit", "posttooluse_incident_driver_shape")

    def test_an_edit_that_adds_only_the_row_is_said_from_the_file(self, tmp_path):
        """The load-bearing row: the incident's dangerous Edit added rows and no
        shell call, so its payload alone holds one predicate; the file on disk
        holds both."""
        root = _project(tmp_path)
        path = _scratch(tmp_path, "drive.py", DRIVER)
        result = _drive(root, _edit(root, path, "ROWS = [", _ROW), tmp_path / "audit")
        said = _said_to_claude(result)
        assert len(said) == 1, result.stdout
        assert f"{path}, line {_row_line(DRIVER)}:" in said[0], said[0]

    def test_it_is_said_once_a_session_for_one_file_and_delete(self, tmp_path):
        root = _project(tmp_path)
        path = _scratch(tmp_path, "drive.py", DRIVER)
        first = _drive(root, _write(root, path), tmp_path / "audit")
        second = _drive(root, _edit(root, path, "timeout=20", "timeout=30"), tmp_path / "audit")
        other_session = _drive(root, _write(root, path, session="s2"), tmp_path / "audit")
        assert len(_said_to_claude(first)) == 1 and len(_told_operator(first)) == 1, first.stdout
        assert _said_to_claude(second) == [] and _told_operator(second) == [], second.stdout
        assert len(_said_to_claude(other_session)) == 1, other_session.stdout


class TestOtherFilesDrawNoWord:
    """Silent rows: one predicate without the other, a file the hook does not
    read, a file it cannot parse, and a tree that is not the harness's own."""

    @pytest.mark.parametrize("name,source", [
        ("a literal command", LITERAL_COMMAND),
        ("the guard test's fixture strings", FIXTURE),
        ("a shell call with no delete", NO_DELETE),
        ("a file that does not parse", DRIVER + "def broken(:\n"),
        ("a file past the read cap", DRIVER + "# " + "x" * (128 * 1024) + "\n"),
    ])
    def test_a_python_file_without_the_whole_shape_is_silent(self, tmp_path, name, source):
        root = _project(tmp_path)
        path = _scratch(tmp_path, "drive.py", source)
        result = _drive(root, _write(root, path), tmp_path / "audit")
        assert _said_to_claude(result) == [], f"{name}: {result.stdout!r}"
        assert _told_operator(result) == [], f"{name}: {result.stdout!r}"

    def test_a_deep_expression_the_parser_refuses_costs_nothing(self, tmp_path):
        """A unary chain the parser refuses on every supported interpreter
        (MemoryError, measured on 3.10 to 3.14): silent, and no crash reaches
        the hook's umbrella, so the write's other checks still run."""
        root = _project(tmp_path)
        path = _scratch(tmp_path, "drive.py", DRIVER + "DEEP = " + "-" * 40_000 + "1\n")
        audit = tmp_path / "audit"
        result = _drive(root, _write(root, path), audit)
        assert _said_to_claude(result) == [], result.stdout
        assert _records(audit, "posttooluse_failed_open_crash") == [], result.stderr

    def test_the_shape_in_a_file_that_is_not_python_is_silent(self, tmp_path):
        root = _project(tmp_path)
        path = _scratch(tmp_path, "drive.txt", DRIVER)
        result = _drive(root, _write(root, path), tmp_path / "audit")
        assert _said_to_claude(result) == [], result.stdout

    def test_the_shape_on_an_adopter_tree_is_silent(self, tmp_path):
        """Self-host only: the calibration is this repository's."""
        root = _project(tmp_path, self_host=False)
        path = _scratch(tmp_path, "drive.py", DRIVER)
        result = _drive(root, _write(root, path), tmp_path / "audit")
        assert _said_to_claude(result) == [], result.stdout
        assert _told_operator(result) == [], result.stdout


#: The census's own spelling of predicate 2 (TP-450's appendix, ``DANGER``),
#: whose flag class backtracks quadratically; the hook re-spells the flag run.
_CENSUS_DELETE_RE = re.compile(r'\brm\s+-[A-Za-z]*[rRf][A-Za-z]*\s+[^\n]{0,20}?["\']?\$\{?\w+\}?["\']?/?\*')


class TestTheLinearSpellingReadsWhatTheCensusRead:
    def test_the_two_spellings_match_the_same_strings(self):
        hook = _load_hook()
        heads = ["rm -rf ", "rm -fr ", "rm -r ", "rm -f ", "rm -R ", "rm -x ", "rm -rfv ", "rm  -Rf\t",
                 "xrm -rf ", "rm -rf", "rm -", "rm -1rf ", "rm -x rm -rf ", "rm -rf\n"]
        gaps = ["", "x ", "-- ", "a" * 19, "a" * 20, "a" * 21, "\n", "'"]
        names = ['"$V"', "$V", "${V}", "'${HOME}'", "$", "${", "$1", '"$V']
        tails = ["/*", "*", "/", "/x*", "", "/**"]
        cases = ["".join(parts) for parts in itertools.product(heads, gaps, names, tails)]
        differ = [s for s in cases
                  if bool(_CENSUS_DELETE_RE.search(s)) != bool(hook._DRIVER_DELETE_RE.search(s))]
        assert len(cases) > 5000 and any(_CENSUS_DELETE_RE.search(s) for s in cases)
        assert differ == [], differ[:5]


class TestTheTrackedTreeDrawsNoWord:
    @pytest.mark.contract
    def test_no_python_file_in_the_checkout_holds_the_shape(self):
        """The next file that holds both halves is seen at its commit, whoever
        wrote it; a file that does not parse is skipped, as the hook skips it.

        The zero is narrower than it looks: tests/test_write_guard.py already
        holds the delete text in fixture strings, and its PowerShell spawns
        list flags before -Command, which predicate 1 does not read. A red here
        on a file that runs no such row means the predicates need tightening,
        a re-raise with a census; never exempt the file (the advisory would
        then speak on every edit of it, and be learned to ignore)."""
        hook = _load_hook()
        read, fires = 0, []
        for path in checkout_glob(REPO_ROOT, "**/*.py"):
            try:
                tree = ast.parse(path.read_bytes())
            except (SyntaxError, ValueError, RecursionError, MemoryError):
                continue
            read += 1
            if hook._runs_a_shell_on_built_text(tree) and hook._first_delete_beside_a_glob(tree):
                fires.append(path.relative_to(REPO_ROOT).as_posix())
        assert read > 500, f"read {read} Python files: the walk lost the tree"
        assert fires == [], fires
