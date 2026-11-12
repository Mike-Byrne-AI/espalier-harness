"""``scripts/guard_cost_census.py``, TP-707's instrument (1-A): its statistics on
fixed inputs, the compile proxy on fixture hooks folders whose counts are known,
one real ``--calls 1`` row per kind against this checkout's guard (the decision
only, never a time), and the box lock: a run behind a held lock waits and names
its holder, one inside the holder pair passes through, a free one is taken,
recorded and cleared, and what it writes is ``tests/_box_lock.py``'s shape.

Every spawn strips ``ESPALIER_BOX_LOCK`` and ``ESPALIER_BOX_LOCK_HOLDER`` from
the child's environment and sets them only to a fixture lock of its own, so a
run under a seat's tier never queues behind that tier, or another seat's, on the
real box lock.
"""
# slow-exempt: about a dozen census children, five of them each spawning the guard once (about 0.3 s on the Air)
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

from tests import _box_lock
from tests._interpreter_hosts import HOOK_PYTHON
from tests._wait_budget import scaled

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "guard_cost_census.py"
_CHILD_S = 30


def _load_census() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("guard_cost_census_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


census = _load_census()


def _run(*args: str, extra_env: dict | None = None, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in (_box_lock.LOCK_KEY, _box_lock.HOLDER_KEY, _box_lock.WAIT_KEY)}
    env.update(extra_env or {})
    return subprocess.run([HOOK_PYTHON, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, cwd=str(cwd), timeout=scaled(_CHILD_S))


class TestSummarize:
    def test_eight_values_read_their_median_and_exclusive_quartiles(self):
        assert census.summarize([5.0, 1.0, 8.0, 3.0, 2.0, 7.0, 4.0, 6.0]) == {
            "n": 8, "median": 4.5, "q1": 2.25, "q3": 6.75, "min": 1.0, "max": 8.0}

    def test_five_values_read_their_median_and_exclusive_quartiles(self):
        assert census.summarize([10.0, 30.0, 20.0, 50.0, 40.0]) == {
            "n": 5, "median": 30.0, "q1": 15.0, "q3": 45.0, "min": 10.0, "max": 50.0}

    def test_one_value_is_its_own_median_and_quartiles(self):
        assert census.summarize([7.5]) == {"n": 1, "median": 7.5, "q1": 7.5, "q3": 7.5, "min": 7.5, "max": 7.5}

    def test_no_values_read_none(self):
        assert census.summarize([]) == {"n": 0, "median": None, "q1": None, "q3": None, "min": None, "max": None}


class TestDecision:
    def _deny(self, reason: str) -> str:
        return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                  "permissionDecisionReason": reason}})

    def test_an_empty_exit_zero_is_an_allow(self):
        assert census.decision("read", 0, "") == "allow"

    def test_a_checkpoint_deny_is_a_nudge_named_by_its_id(self):
        assert census.decision("bash", 0, self._deny("[CP-RMRF] a recursive delete: re-issue to proceed")) == "nudge CP-RMRF"

    def test_a_deny_with_no_checkpoint_is_a_deny(self):
        assert census.decision("bash", 0, self._deny("Command blocked: a protected zone")) == "deny"

    def test_exit_two_is_a_block_and_another_exit_an_error(self):
        assert (census.decision("bash", 2, ""), census.decision("bash", 1, "")) == ("block (exit 2)", "error (exit 1)")

    def test_the_control_reads_its_exit(self):
        assert census.decision("control", 0, "") == "exit 0"


def _fixture_hooks(root: Path, *, write_guard: str | None) -> Path:
    """Two tiny pattern modules: four distinct compiles keyed by pattern and
    flags (``plain`` twice under two flags, and once more under the first,
    which is no new key), 28 characters, two of them embedding the 7-character
    fragment. ``write_guard`` is that file's text, or none is written."""
    hooks = root / "tools" / "cc" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "_bash_patterns.py").write_text(
        "import re\n"
        "_CMD_POS_NO_VERB = '(?:^|;)'\n"
        "_CMD_POS = _CMD_POS_NO_VERB + 'x'\n"
        "A = re.compile(_CMD_POS_NO_VERB + 'rm')\n"
        "B = re.compile('plain')\n", encoding="utf-8")
    (hooks / "_speedbump.py").write_text(
        "import re\n"
        "import _bash_patterns\n"
        "C = re.compile(_bash_patterns._CMD_POS_NO_VERB + 'mv', re.I)\n"
        "D = re.compile('plain', re.I)\n"
        "E = re.compile('plain')\n", encoding="utf-8")
    if write_guard is not None:
        (hooks / "write_guard.py").write_text(write_guard, encoding="utf-8")
    return root


class TestCompile:
    def _compile(self, root: Path) -> dict:
        proc = _run("--compile", "--root", str(root), "--json")
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)["compile"]

    def test_two_modules_read_their_known_counts(self, tmp_path):
        assert self._compile(_fixture_hooks(tmp_path, write_guard=None)) == {
            "method": "the two pattern modules imported; this tree has no write_guard.py",
            "patterns": 4, "compiled_chars": 28, "fragment_len": 7, "cmd_pos_len": 8,
            "embedding_patterns": 2, "embedding_chars": 18}

    def test_the_loader_s_own_compiles_are_counted(self, tmp_path):
        guard = ("import re\n"
                 "import _bash_patterns\n"
                 "def _load_the_pattern_path():\n"
                 "    global F\n"
                 "    F = re.compile(_bash_patterns._CMD_POS_NO_VERB + 'cp')\n")
        got = self._compile(_fixture_hooks(tmp_path, write_guard=guard))
        assert (got["method"], got["patterns"], got["compiled_chars"], got["embedding_patterns"],
                got["embedding_chars"]) == ("imports and write_guard._load_the_pattern_path", 5, 37, 3, 27)

    def test_a_guard_without_the_loader_is_read_by_its_imports_and_says_so(self, tmp_path):
        guard = "import re\nimport _speedbump\nG = re.compile('at-import')\n"
        got = self._compile(_fixture_hooks(tmp_path, write_guard=guard))
        assert got["method"].startswith("imports alone: this tree's write_guard has no _load_the_pattern_path")
        assert (got["patterns"], got["compiled_chars"]) == (5, 37)

    def test_a_path_that_compiles_nothing_exits_one(self, tmp_path):
        hooks = tmp_path / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "_bash_patterns.py").write_text("_CMD_POS_NO_VERB = '(?:^|;)'\n", encoding="utf-8")
        (hooks / "_speedbump.py").write_text("X = 1\n", encoding="utf-8")
        proc = _run("--compile", "--root", str(tmp_path))
        assert proc.returncode == 1
        assert "recorded no pattern at all" in proc.stderr


class TestCallsAgainstTheCheckout:
    @pytest.mark.parametrize("kind,seen", [
        ("control", "exit 0"), ("read", "allow"), ("bash", "allow"), ("mcp_read", "allow"), ("mcp_write", "allow"),
    ])
    def test_one_call_of_each_kind_reads_its_decision(self, kind, seen):
        proc = _run("--calls", "1", "--kind", kind, "--json")
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout)
        assert result["kinds"][kind]["decisions"] == {seen: 1}
        assert (result["unguarded"], result["lock"]["outcome"]) == (True, "unguarded")

    def test_an_unguarded_run_says_so_beside_every_figure(self):
        proc = _run("--calls", "1", "--kind", "control")
        assert proc.returncode == 0, proc.stderr
        lines = proc.stdout.splitlines()
        rows = [line for line in lines if line.startswith("control ")]
        assert rows and all(line.endswith("[unguarded]") for line in rows), lines
        assert "lock:    unguarded (ESPALIER_BOX_LOCK is not set)" in lines


@pytest.fixture
def held_lock(tmp_path):
    """A fixture lock this test process holds, with a holder record naming it."""
    path = tmp_path / "box.lock"
    primitive = _box_lock._primitive()
    fh = open(path, "a+", encoding="utf-8")
    assert primitive.try_lock_file(fh)
    record = {"seat": "fixture-seat", "lane": "lane/fixture", "checkout": str(tmp_path), "pid": os.getpid(),
              "started": "2026-11-12T00:00:00+00:00", "argv": ["pytest", "-q"]}
    fh.seek(0)
    fh.truncate()
    fh.write(json.dumps(record))
    fh.flush()
    try:
        yield path, record
    finally:
        primitive.unlock_file(fh)
        fh.close()


def _log_lines(lock: Path) -> list[dict]:
    log = Path(f"{lock}.log")
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


class TestTheBoxLock:
    def test_a_run_behind_a_held_lock_waits_names_its_holder_and_gives_up_past_the_bound(self, held_lock):
        path, record = held_lock
        proc = _run("--calls", "1", "--kind", "control",
                    extra_env={_box_lock.LOCK_KEY: str(path), _box_lock.WAIT_KEY: "0.5"})
        assert proc.returncode == _box_lock.DID_NOT_RUN_EXIT, proc.stderr
        assert f"box lock: waiting on fixture-seat lane/fixture (pid {record['pid']}, held " in proc.stderr
        assert "did not run" in proc.stderr and "nothing was timed" in proc.stderr
        assert [line["outcome"] for line in _log_lines(path)] == ["gave_up"]
        assert _log_lines(path)[0]["holder"] == {"seat": "fixture-seat", "lane": "lane/fixture", "pid": record["pid"]}

    def test_inside_the_holder_pair_it_passes_through(self, held_lock):
        path, record = held_lock
        proc = _run("--calls", "1", "--kind", "control", "--json",
                    extra_env={_box_lock.LOCK_KEY: str(path), _box_lock.HOLDER_KEY: str(record["pid"]),
                               _box_lock.WAIT_KEY: "5"})  # a broken pass-through gives up, never waits out the child's bound
        assert proc.returncode == 0, proc.stderr
        lock = json.loads(proc.stdout)["lock"]
        assert (lock["outcome"], lock["holder"]["seat"]) == ("inside", "fixture-seat")
        assert [line["outcome"] for line in _log_lines(path)] == ["inside"]

    def test_a_free_lock_is_taken_recorded_and_cleared(self, tmp_path):
        path = tmp_path / "box.lock"
        proc = _run("--calls", "1", "--kind", "control", "--json", extra_env={_box_lock.LOCK_KEY: str(path)})
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["lock"]["outcome"] == "taken"
        (line,) = _log_lines(path)
        assert line["outcome"] == "taken" and line["run"]["pid"] not in (None, os.getpid())
        assert path.read_text(encoding="utf-8") == ""


class TestTheHolderIsTheBoxLocksShape:
    """The census cannot import ``tests/_box_lock.py`` (it imports pytest), so
    these hold its copy of a holder's behaviour to the plugin's."""

    def test_the_names_and_the_exit_status_are_the_plugins(self):
        assert (census.LOCK_KEY, census.HOLDER_KEY, census.WAIT_KEY, census.DID_NOT_RUN_EXIT, census.POLL_S,
                census.REPORT_S) == (_box_lock.LOCK_KEY, _box_lock.HOLDER_KEY, _box_lock.WAIT_KEY,
                                     _box_lock.DID_NOT_RUN_EXIT, _box_lock.POLL_S, _box_lock.REPORT_S)

    def test_the_holder_record_carries_build_records_keys(self, tmp_path):
        config = types.SimpleNamespace(rootpath=tmp_path)
        assert set(census.build_record()) == set(_box_lock.build_record(config, _box_lock._primitive()))

    def test_the_launchers_old_default_reads_as_the_new_one_in_both(self):
        old = os.path.join(tempfile.gettempdir(), "espalier-box.lock")
        assert census.current_path(old, stream=io.StringIO()) == _box_lock.current_path(old, stream=io.StringIO())
        assert census.current_path(old, stream=io.StringIO()) == _box_lock.home_default()
        assert census.current_path("/elsewhere/box.lock") == "/elsewhere/box.lock"

    def test_the_wait_bound_reads_as_the_plugins(self):
        for raw in (None, "", " ", "2.5", "0", "-1", "nan", "inf", "soon"):
            assert census.wait_bound(raw, stream=io.StringIO()) == _box_lock.wait_bound(raw, stream=io.StringIO()), raw

    def test_the_holder_pair_reads_as_the_plugins(self, monkeypatch):
        me = {"pid": os.getpid()}
        dead = {"pid": 2 ** 22 + 12345}
        for env_pid, record in ((str(os.getpid()), me), (str(dead["pid"]), dead), ("", me), ("x", me),
                                (str(os.getpid()), None), (str(os.getpid()), {"pid": "other"})):
            monkeypatch.setenv(_box_lock.HOLDER_KEY, env_pid)
            assert census.inside_holder(record) == _box_lock.inside_holder(record), (env_pid, record)
        monkeypatch.setenv(_box_lock.HOLDER_KEY, str(os.getpid()))
        assert census.inside_holder(me) is True

    def test_the_log_line_has_the_plugins_shape(self, tmp_path):
        run, holder = {"seat": "s", "lane": "l", "pid": 1}, {"seat": "h", "lane": "m", "pid": 2}
        census.log_outcome(tmp_path / "a", "waited", run, holder, 3.25, why="w")
        _box_lock.log_outcome(tmp_path / "b", "waited", run, holder, 3.25, why="w")
        (ours,) = _log_lines(tmp_path / "a")
        (theirs,) = _log_lines(tmp_path / "b")
        assert set(ours) == set(theirs)
        assert {k: ours[k] for k in ("outcome", "run", "holder", "waited_s", "why")} == {
            k: theirs[k] for k in ("outcome", "run", "holder", "waited_s", "why")}


def test_the_census_is_stdlib_only():
    """No import outside the standard library: the script runs on a bare interpreter."""
    import ast
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module.split(".")[0] for node in ast.walk(tree)
              if isinstance(node, ast.ImportFrom) and node.module and node.level == 0}
    assert names - {"__future__"} <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)
