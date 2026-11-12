"""``scripts/guard_cost_census.py``, TP-707's instrument (1-A): its statistics on
fixed inputs, the compile proxy on fixture hooks folders whose counts are known,
one real ``--calls 1`` row per kind against this checkout's guard (the decision
only, never a time), a fixture guard whose decisions are not a cost, the cache
and tree reads, and the box lock: a run behind a held lock waits and names its
holder, one inside the holder pair passes through, a free one is taken, recorded
while held and cleared, and what it writes is ``tests/_box_lock.py``'s shape.

Every spawn strips ``ESPALIER_BOX_LOCK`` and ``ESPALIER_BOX_LOCK_HOLDER`` from
the child's environment and sets them only to a fixture lock of its own, so a
run under a seat's tier never queues behind that tier, or another seat's, on the
real box lock.
"""
# slow-exempt: about fifteen census children, the guard rows each spawning the guard once or twice (about 0.3 s each on the Air)
from __future__ import annotations

import importlib.util
import io
import json
import os
import py_compile
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

import pytest

from tests import _box_lock
from tests._interpreter_hosts import HOOK_PYTHON
from tests._wait_budget import scaled

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "guard_cost_census.py"
_CHILD_S = 30
_BUDGET_SKIP = ("the guard ran out of its time budget on this runner: a load reading, "
                "not a census defect (the deadline is the guard's, TP-707 Scope out)")


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
    def test_eight_values_read_their_median_and_inclusive_quartiles(self):
        assert census.summarize([5.0, 1.0, 8.0, 3.0, 2.0, 7.0, 4.0, 6.0]) == {
            "n": 8, "median": 4.5, "q1": 2.75, "q3": 6.25, "min": 1.0, "max": 8.0}

    def test_five_values_read_their_median_and_inclusive_quartiles(self):
        assert census.summarize([10.0, 30.0, 20.0, 50.0, 40.0]) == {
            "n": 5, "median": 30.0, "q1": 20.0, "q3": 40.0, "min": 10.0, "max": 50.0}

    def test_two_values_keep_their_quartiles_inside_min_and_max(self):
        got = census.summarize([46.8, 50.0])
        assert got["min"] <= got["q1"] <= got["q3"] <= got["max"], got

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

    def test_a_deny_at_the_deadline_names_the_budget(self):
        reason = "Command blocked: write_guard ran out of its 4.0 s time budget before it had judged this command"
        assert census.decision("bash", 0, self._deny(reason)) == "deny (time budget)"

    def test_a_deny_with_no_checkpoint_is_a_deny(self):
        assert census.decision("bash", 0, self._deny("Command blocked: a protected zone")) == "deny"

    def test_output_that_is_not_one_object_is_unreadable(self):
        assert (census.decision("read", 0, "[1, 2]"), census.decision("read", 0, "not json")) == (
            "unreadable output", "unreadable output")

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


_FIGURES = ("method", "loader_ran", "fragment_found", "patterns", "compiled_chars", "hooks_patterns", "hooks_chars",
            "fragment_len", "cmd_pos_len", "embedding_patterns", "embedding_chars")


class TestCompile:
    def _compile(self, root: Path) -> dict:
        proc = _run("--compile", "--root", str(root), "--json")
        assert proc.returncode == 0, proc.stderr
        got = json.loads(proc.stdout)["compile"]
        assert sorted(Path(m).name for m in got["modules"]) == sorted(
            p.name for p in (root / "tools" / "cc" / "hooks").glob("_*.py"))
        return {k: got[k] for k in _FIGURES}

    def test_two_modules_read_their_known_counts(self, tmp_path):
        assert self._compile(_fixture_hooks(tmp_path, write_guard=None)) == {
            "method": "the two pattern modules imported; this tree has no write_guard.py",
            "loader_ran": False, "fragment_found": True, "patterns": 4, "compiled_chars": 28,
            "hooks_patterns": 4, "hooks_chars": 28, "fragment_len": 7, "cmd_pos_len": 8,
            "embedding_patterns": 2, "embedding_chars": 18}

    def test_the_loader_s_own_compiles_are_counted(self, tmp_path):
        guard = ("import re\n"
                 "import _bash_patterns\n"
                 "def _load_the_pattern_path():\n"
                 "    global F\n"
                 "    F = re.compile(_bash_patterns._CMD_POS_NO_VERB + 'cp')\n")
        got = self._compile(_fixture_hooks(tmp_path, write_guard=guard))
        assert (got["method"], got["loader_ran"], got["patterns"], got["compiled_chars"], got["hooks_chars"],
                got["embedding_patterns"], got["embedding_chars"]) == (
            "imports and write_guard._load_the_pattern_path", True, 5, 37, 37, 3, 27)

    def test_a_guard_without_the_loader_is_read_by_its_imports_and_says_so(self, tmp_path):
        guard = "import re\nimport _speedbump\nG = re.compile('at-import')\n"
        got = self._compile(_fixture_hooks(tmp_path, write_guard=guard))
        assert got["method"].startswith("imports alone: this tree's write_guard has no _load_the_pattern_path")
        assert (got["loader_ran"], got["patterns"], got["compiled_chars"]) == (False, 5, 37)

    def test_a_missing_fragment_says_so(self, tmp_path):
        root = _fixture_hooks(tmp_path, write_guard=None)
        bp = root / "tools" / "cc" / "hooks" / "_bash_patterns.py"
        bp.write_text(bp.read_text(encoding="utf-8").replace("_CMD_POS_NO_VERB", "_RENAMED"), encoding="utf-8")
        (root / "tools" / "cc" / "hooks" / "_speedbump.py").write_text("import re\nC = re.compile('mv')\n",
                                                                       encoding="utf-8")
        got = self._compile(root)
        assert (got["fragment_found"], got["fragment_len"], got["embedding_patterns"]) == (False, None, 0)

    def test_a_path_that_compiles_nothing_prints_no_figure_and_exits_one(self, tmp_path):
        hooks = tmp_path / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "_bash_patterns.py").write_text("_CMD_POS_NO_VERB = '(?:^|;)'\n", encoding="utf-8")
        (hooks / "_speedbump.py").write_text("X = 1\n", encoding="utf-8")
        proc = _run("--compile", "--root", str(tmp_path), "--json")
        assert (proc.returncode, proc.stdout) == (1, "")
        assert "recorded no pattern at all" in proc.stderr

    def test_a_checkout_whose_guard_has_no_loader_is_refused(self, tmp_path, monkeypatch, capsys):
        guard = "import re\nimport _speedbump\nG = re.compile('at-import')\n"
        monkeypatch.setattr(census, "REPO_ROOT", _fixture_hooks(tmp_path, write_guard=guard))
        assert census.main(["--compile", "--json"]) == 1
        captured = capsys.readouterr()
        assert captured.out == "" and "has no _load_the_pattern_path" in captured.err

    def test_this_checkout_runs_the_loader(self):
        proc = _run("--compile", "--json")
        assert proc.returncode == 0, proc.stderr
        got = json.loads(proc.stdout)["compile"]
        assert got["loader_ran"] and got["fragment_found"] and got["hooks_patterns"] > 100, got


class TestCallsAgainstTheCheckout:
    @pytest.mark.parametrize("kind", ["read", "bash", "mcp_read", "mcp_write"])
    def test_one_call_of_each_kind_reads_its_decision(self, kind):
        proc = _run("--calls", "1", "--kind", kind, "--json")
        result = json.loads(proc.stdout) if proc.stdout.strip() else {}
        seen = result.get("kinds", {}).get(kind, {}).get("decisions")
        if seen == {"deny (time budget)": 1}:
            pytest.skip(_BUDGET_SKIP)
        assert proc.returncode == 0, proc.stderr
        assert (seen, result["kinds"]["control"]["decisions"]) == ({"allow": 1}, {"exit 0": 1})
        assert (result["unguarded"], result["lock"]["outcome"], result["decisions_as_expected"]) == (
            True, "unguarded", True)
        assert set(result["bytecode_cache"].values()) <= {"fresh", "stale", "absent", "hashed"}

    def test_an_unguarded_run_says_so_beside_every_figure(self):
        proc = _run("--calls", "1", "--kind", "read")
        if "deny (time budget)" in proc.stdout:
            pytest.skip(_BUDGET_SKIP)
        assert proc.returncode == 0, proc.stderr
        lines = proc.stdout.splitlines()
        rows = [line for line in lines if line.startswith(("control ", "read "))]
        assert len(rows) == 2 and all("unguarded" in line.rsplit("[", 1)[-1] for line in rows), lines
        assert "lock:    unguarded (ESPALIER_BOX_LOCK is not set)" in lines

    def test_options_outside_their_mode_are_refused(self):
        for args in (("--compile", "--kind", "bash"), ("--calls", "1", "--rounds", "3"), ("--compile", "--at", " ")):
            proc = _run(*args)
            assert proc.returncode == 2 and "guard_cost_census:" in proc.stderr, (args, proc.stderr)


#: A stand-in guard that refuses on its deadline and writes the record. Its log
#: is named as tools/cc/hooks/_integrity.py::audit_path names the real one, by
#: ``_safe_slug``'s rule, which strips a trailing ``_``: a raw folder name left a
#: mkdtemp name ending in ``_`` (one in 37) uncounted, a red on about one run in
#: nineteen (run 43251681324, the perturbed cell).
_BUDGET_GUARD = '''\
import json, os, re, sys
from datetime import datetime, timezone
if __name__ == "__main__":
    sys.stdin.read()
    name = os.path.basename(os.environ["CLAUDE_PROJECT_DIR"])
    project = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "repo"
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    with open(os.path.join(os.environ["ESPALIER_AUDIT_DIR"], f"{project}-{day}.log"), "a", encoding="utf-8") as log:
        log.write(json.dumps({"event_type": "pretooluse_blocked_time_budget", "details": {}}) + "\\n")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                      "permissionDecisionReason": "write_guard ran out of its 4.0 s time budget"}}))
'''


class TestDecisionsThatAreNotACost:
    def test_a_budget_refusal_is_named_counted_tagged_and_exits_three(self, tmp_path):
        root = _fixture_hooks(tmp_path, write_guard=_BUDGET_GUARD)
        proc = _run("--calls", "2", "--kind", "bash", "--root", str(root), "--json")
        assert proc.returncode == census.DECISIONS_MIXED_EXIT, proc.stderr
        result = json.loads(proc.stdout)
        row = result["kinds"]["bash"]
        assert (row["decisions"], row["budget_records"], row["as_expected"]) == ({"deny (time budget)": 2}, 2, False)
        assert (result["kinds"]["control"]["as_expected"], result["decisions_as_expected"]) == (True, False)

    def test_a_project_name_ending_in_an_underscore_is_counted(self, tmp_path, monkeypatch):
        # The draw the two tests here leave to tempfile, fixed: the stand-in
        # guard's record for a folder named with a trailing `_` is counted
        # under its own kind (it read "unknown" with the raw folder name).
        import runpy
        guard = tmp_path / "budget_guard.py"
        guard.write_text(_BUDGET_GUARD, encoding="utf-8")
        audit = tmp_path / "census-audit"   # the suite's own fixtures hold `audit`
        audit.mkdir()
        project = tmp_path / "p-abcdefg_"
        project.mkdir()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(audit))
        monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
        runpy.run_path(str(guard), run_name="__main__")
        assert census.budget_records(audit, {project.name: "bash"}) == {"bash": 1}

    def test_the_text_tags_the_mixed_row_alone(self, tmp_path):
        root = _fixture_hooks(tmp_path, write_guard=_BUDGET_GUARD)
        proc = _run("--calls", "1", "--kind", "read", "--root", str(root))
        assert proc.returncode == census.DECISIONS_MIXED_EXIT, proc.stderr
        lines = proc.stdout.splitlines()
        read = next(line for line in lines if line.startswith("read "))
        control = next(line for line in lines if line.startswith("control "))
        assert "decisions mixed" in read and "1 budget record(s)" in read and "decisions mixed" not in control


class TestTheTreeAndTheCache:
    def test_a_cache_is_fresh_then_stale_then_absent(self, tmp_path):
        source = tmp_path / "mod.py"
        source.write_text("X = 1\n", encoding="utf-8")
        cached = importlib.util.cache_from_source(str(source))
        py_compile.compile(str(source), cfile=cached, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
        assert census.pyc_state(source) == "fresh"
        source.write_text("X = 22\n", encoding="utf-8")
        later = time.time() + 5
        os.utime(source, (later, later))
        assert census.pyc_state(source) == "stale"
        os.remove(cached)
        assert census.pyc_state(source) == "absent"

    def test_this_checkout_says_whether_its_tools_cc_is_origin_main(self):
        tree = census.checkout_tree()
        assert tree["kind"] == "checkout" and tree["head"] and tree["tools_cc_is_origin_main"] in (True, False, None)

    @pytest.mark.skipif(sys.platform != "win32", reason="GetSystemTimes is Windows-only; POSIX reads the load average")
    def test_windows_reads_the_cpu_busy_share(self):
        start = census.system_times()
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:
            pass
        busy = census.cpu_busy(start, census.system_times())
        assert busy is not None and 0.0 <= busy <= 1.0


@pytest.fixture
def held_lock(tmp_path, monkeypatch):
    """A fixture lock this test process holds through the tiers' own plugin
    (``tests/_box_lock.py::BoxLock``), so a change to what a tier locks reaches
    these rows; the holder variable it exports is put back after the test."""
    monkeypatch.delenv(_box_lock.HOLDER_KEY, raising=False)
    path = tmp_path / "box.lock"
    record = {"seat": "fixture-seat", "lane": "lane/fixture", "checkout": str(tmp_path), "pid": os.getpid(),
              "started": "2026-11-12T00:00:00+00:00", "argv": ["pytest", "-q"]}
    holder = _box_lock.BoxLock(path, dict(record), _box_lock._primitive(), stream=io.StringIO())
    holder.acquire()
    assert holder.held
    try:
        yield path, holder.record
    finally:
        holder.release()


def _log_lines(lock: Path) -> list[dict]:
    log = Path(f"{lock}.log")
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


class TestTheBoxLock:
    def test_a_run_behind_a_held_lock_waits_names_its_holder_and_gives_up_past_the_bound(self, held_lock):
        path, record = held_lock
        proc = _run("--calls", "1", "--kind", "read",
                    extra_env={_box_lock.LOCK_KEY: str(path), _box_lock.WAIT_KEY: "0.5"})
        assert proc.returncode == _box_lock.DID_NOT_RUN_EXIT, proc.stderr
        assert f"box lock: waiting on fixture-seat lane/fixture (pid {record['pid']}, held " in proc.stderr
        assert "did not run" in proc.stderr and "nothing was timed" in proc.stderr
        lines = _log_lines(path)
        assert [line["outcome"] for line in lines][-1:] == ["gave_up"]
        assert lines[-1]["holder"] == {"seat": "fixture-seat", "lane": "lane/fixture", "pid": record["pid"]}

    def test_with_no_bound_set_the_census_waits_its_own_default(self, held_lock, monkeypatch):
        path, _ = held_lock
        monkeypatch.setenv(_box_lock.LOCK_KEY, str(path))
        monkeypatch.delenv(_box_lock.WAIT_KEY, raising=False)
        monkeypatch.delenv(_box_lock.HOLDER_KEY, raising=False)  # the fixture's holder exported this pid
        monkeypatch.setattr(census, "DEFAULT_WAIT_S", 0.3)
        lock = census.BoxLock(stream=io.StringIO())
        with pytest.raises(SystemExit) as stopped:
            lock.acquire()
        assert stopped.value.code == census.DID_NOT_RUN_EXIT
        assert "waits at most 0.3 s" in lock.stream.getvalue()

    def test_inside_the_holder_pair_it_passes_through(self, held_lock):
        path, record = held_lock
        proc = _run("--calls", "1", "--kind", "read", "--json",
                    extra_env={_box_lock.LOCK_KEY: str(path), _box_lock.HOLDER_KEY: str(record["pid"]),
                               _box_lock.WAIT_KEY: "5"})  # a broken pass-through gives up, never waits out the child's bound
        if "deny (time budget)" in proc.stdout:
            pytest.skip(_BUDGET_SKIP)
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout)
        assert (result["lock"]["outcome"], result["lock"]["holder"]["seat"]) == ("inside", "fixture-seat")
        assert "inside a holder" in result["tags"]
        assert [line["outcome"] for line in _log_lines(path)][-1:] == ["inside"]

    def test_a_free_lock_is_taken_recorded_while_held_and_cleared(self, tmp_path, monkeypatch):
        path = tmp_path / "box.lock"
        monkeypatch.setenv(_box_lock.LOCK_KEY, str(path))
        monkeypatch.delenv(_box_lock.HOLDER_KEY, raising=False)
        monkeypatch.delenv(_box_lock.WAIT_KEY, raising=False)
        lock = census.BoxLock(stream=io.StringIO())
        lock.acquire()
        try:
            assert lock.outcome == "taken"
            record = _box_lock.read_record(path)
            assert record is not None and record["pid"] == os.getpid()
            assert set(record) == set(_box_lock.build_record(types.SimpleNamespace(rootpath=tmp_path),
                                                             _box_lock._primitive()))
            with open(path, "a+", encoding="utf-8") as other:
                assert _box_lock._primitive().try_lock_file(other) is False
            assert census.waiting_line(record, 0.0) == _box_lock.waiting_line(record, waited_s=0.0)
        finally:
            lock.release()
        assert path.read_text(encoding="utf-8") == ""
        assert [line["outcome"] for line in _log_lines(path)] == ["taken"]

    def test_a_census_run_takes_and_clears_a_free_lock(self, tmp_path):
        path = tmp_path / "box.lock"
        proc = _run("--calls", "1", "--kind", "read", "--json", extra_env={_box_lock.LOCK_KEY: str(path)})
        if "deny (time budget)" in proc.stdout:
            pytest.skip(_BUDGET_SKIP)
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

    def test_the_waiting_line_reads_as_the_plugins_under_its_ceiling(self):
        for record in (None, {}, {"seat": "s", "lane": "l", "pid": 7, "argv": ["/x/bin/pytest", "-q", "-n", "4"]},
                       {"seat": "s", "lane": "l", "pid": 7, "started": "not a stamp"}, {"seat": "s"},
                       {"seat": "s", "pid": "abc", "started": "2026-11-12T00:00:00+00:00"}):
            assert census.waiting_line(record, 61.0) == _box_lock.waiting_line(record, waited_s=61.0), record

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
