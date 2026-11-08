"""tests/_hook_spawn.py: the one spawn for the rows that run write_guard, or
the statusline, as a real child (DEF-2014). A miss (a timeout, or write_guard's
budget refusal) is retried once under the same bound, so a stalled runner
answers the second time and a hook that is slow every time reds; any other
answer is the first attempt's, so a wrong verdict is never retried away. These
rows pin each of those, because a retry that hid a regression would be worse
than the stall it absorbs. The children here are small scripts that count
their own runs. The rows that read
source (where the helper must be used, and what it agrees with) are
tests/test_hook_spawn_routing.py's, in the contract slice."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from tests import _hook_spawn as hs

# A child that counts its runs in the file it is given, then behaves by
# ``mode``: answer, sleep past the bound, print the budget's refusal, take
# 4.5 s every time, or (``-state``) write a one-shot flag under the project's
# .espalier-state, change one file there and remove another, then sleep past
# the bound, and answer with what it read there, as a speed bump reads its
# flag (``-cc``: write under the project's cc/ and sleep past the bound); the
# ``first-`` modes miss on the first run only.
_CHILD = r'''
import os, sys, time
from pathlib import Path
counter, mode = sys.argv[1], sys.argv[2]
with open(counter, "a", encoding="utf-8") as fh:
    fh.write("x")
runs = len(open(counter, encoding="utf-8").read())
project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
miss = mode.startswith("always-") or (mode.startswith("first-") and runs == 1)
if mode == "slow":
    time.sleep(4.5)
if mode.endswith("-state"):
    state = project / ".espalier-state"
    kept, gone, flag = state / "kept", state / "gone", state / "one-shot-flag"
    if miss:
        state.mkdir(parents=True, exist_ok=True)
        flag.write_text("x", encoding="utf-8")
        if kept.exists():
            kept.write_text("after", encoding="utf-8")
        if gone.exists():
            gone.unlink()
        time.sleep(30)
    print("re-issue" if flag.exists() else "first issue",
          kept.read_text(encoding="utf-8") if kept.exists() else "-", gone.exists())
    sys.exit(0)
if mode.endswith("-audit"):
    log = Path(os.environ["ESPALIER_AUDIT_DIR"]) / "repo-day.log"
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("{}\n")
    if miss:
        time.sleep(30)
    print(len(log.read_text(encoding="utf-8").splitlines()))
    sys.exit(0)
if miss and mode.endswith("-cc"):
    cc = project / "cc" / "blueprints"
    cc.mkdir(parents=True, exist_ok=True)
    (cc / "latest.json").write_text("{}", encoding="utf-8")
    time.sleep(30)
if miss and mode.endswith("-pycache"):
    cache = project / "hooks" / "__pycache__"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "sibling.cpython.pyc").write_bytes(b"x")
    time.sleep(30)
if miss and mode.endswith("-root"):
    (project / "reflect_ran.marker").write_text("x", encoding="utf-8")
    time.sleep(30)
if miss and mode.endswith("-grandchild"):
    late = ("import pathlib, sys, time; time.sleep(4); p = pathlib.Path(sys.argv[1]); "
            "p.mkdir(parents=True, exist_ok=True); (p / 'late').write_text('x')")
    import subprocess
    subprocess.Popen([sys.executable, "-c", late, str(project / ".espalier-state")],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(30)
if miss and mode.endswith("sleep"):
    time.sleep(30)
if mode.endswith("-flagbudget"):
    flag = project / ".espalier-state" / "one-shot-flag"
    if miss:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("x", encoding="utf-8")
        print('{"reason": "Command blocked: write_guard could not finish judging this command"}')
        sys.exit(0)
    print("re-issue" if flag.exists() else "first issue")
    sys.exit(0)
if miss and mode.endswith("fallback"):
    print('{"reason": "Command blocked: write_guard ran out of its 4.0 s time budget before it had judged this command"}')
    sys.exit(0)
if miss and mode.endswith("budget"):
    print('{"reason": "Command blocked: write_guard could not finish judging this command"}')
    sys.exit(0)
if mode == "deny":
    print('{"permissionDecision": "deny"}')
    sys.exit(2)
print("answered")
'''


@pytest.fixture
def child(tmp_path, monkeypatch):
    """(argv for ``mode`` on a fresh counter, a reader of that counter's runs);
    every bound 3 s, so a row that waits out two of them stays short."""
    script = tmp_path / "child.py"
    script.write_text(_CHILD, encoding="utf-8")
    monkeypatch.setattr(hs, "HOOK_S", 3.0)
    monkeypatch.setattr(hs, "STATUSLINE_S", 3.0)
    monkeypatch.setattr(hs, "_RETRIED", set())
    # A row with no project of its own resolves the working directory, this
    # checkout, where a live session's writes would refuse every retry.
    (tmp_path / "quiet").mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "quiet"))
    counters = []

    def argv(mode, counter="runs.txt"):
        counters.append(tmp_path / counter)
        return [sys.executable, str(script), str(tmp_path / counter), mode]

    def runs(counter="runs.txt"):
        path = tmp_path / counter
        return len(path.read_text(encoding="utf-8")) if path.is_file() else 0

    return argv, runs


class TestOneRetryOnAMiss:
    def test_an_answer_on_the_first_attempt_is_returned_with_no_retry(self, child):
        argv, runs = child
        result = hs.run_hook_through(argv("answer"), env=None, input="{}")
        assert (result.returncode, result.stdout.strip(), runs()) == (0, "answered", 1)

    def test_a_timeout_then_an_answer_returns_the_answer_and_warns(self, child):
        argv, runs = child
        with pytest.warns(hs.HookSpawnRetried, match="no answer in"):
            result = hs.run_hook_through(argv("first-sleep"), env=None, input="{}")
        assert (result.stdout.strip(), runs()) == ("answered", 2)

    def test_a_budget_refusal_then_an_answer_returns_the_answer_and_warns(self, child):
        argv, runs = child
        with pytest.warns(hs.HookSpawnRetried, match="budget's refusal"):
            result = hs.run_hook_through(argv("first-budget"), env=None, input="{}")
        assert (result.stdout.strip(), runs()) == ("answered", 2)

    def test_two_timeouts_fail_the_row_naming_both_times(self, child):
        argv, runs = child
        with pytest.raises(pytest.fail.Exception) as failed:
            hs.run_hook_through(argv("always-sleep"), env=None, input="{}")
        assert str(failed.value).count("no answer in") == 2, str(failed.value)
        assert runs() == 2

    def test_two_budget_refusals_fail_the_row_naming_both_times(self, child):
        argv, runs = child
        with pytest.raises(pytest.fail.Exception) as failed:
            hs.run_hook_through(argv("always-budget"), env=None, input="{}")
        assert str(failed.value).count("budget's refusal after") == 2, str(failed.value)
        assert runs() == 2

    def test_a_hook_slow_every_time_fails_every_time(self, child):
        """The retry gets no more time than the first attempt: a regression
        that makes the hook slow on every run reds on every runner, never
        passes on a longer second bound."""
        argv, runs = child
        with pytest.raises(pytest.fail.Exception, match="missed on both attempts"):
            hs.run_hook_through(argv("slow"), env=None, input="{}")
        assert runs() == 2

    def test_a_wrong_answer_is_never_retried(self, child):
        """A deny that is not the budget's is the hook's verdict: a guard
        regression must red on its first attempt, never be run again."""
        argv, runs = child
        result = hs.run_hook_through(argv("deny"), env=None, input="{}")
        assert (result.returncode, runs()) == (2, 1)


class TestTheRetrysLimits:
    def test_a_row_gets_one_retry_however_many_spawns_it_makes(self, child):
        """A row that spawns several times waits at most one bound longer than
        before: once its retry is spent, the next miss fails at once."""
        argv, runs = child
        with pytest.warns(hs.HookSpawnRetried):
            hs.run_hook_through(argv("first-sleep", "one.txt"), env=None, input="{}")
        with pytest.raises(pytest.fail.Exception, match="spent its one retry"):
            hs.run_hook_through(argv("first-sleep", "two.txt"), env=None, input="{}")
        assert (runs("one.txt"), runs("two.txt")) == (2, 1)

    def test_a_miss_that_left_state_is_retried_from_the_state_it_began_with(self, child, tmp_path):
        """A speed bump's one-shot flag the miss wrote would make the retry
        read as a re-issue: the state the first attempt began with is put back
        first (bytes and mtimes, what it added removed, what it removed
        written back), so the retry answers as the first attempt would have
        (DEF-2030)."""
        argv, runs = child
        project = tmp_path / "project"
        state = project / ".espalier-state"
        state.mkdir(parents=True)
        (state / "kept").write_text("before", encoding="utf-8")
        (state / "gone").write_text("x", encoding="utf-8")
        aged = 1_600_000_000_000_000_000
        os.utime(state / "kept", ns=(aged, aged))
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
        with pytest.warns(hs.HookSpawnRetried, match="from the .espalier-state it began with"):
            result = hs.run_hook_through(argv("first-state"), env=env, input="{}")
        assert (result.stdout.split(), runs()) == (["first", "issue", "before", "True"], 2)
        assert (state / "kept").stat().st_mtime_ns == aged
        assert sorted(p.name for p in state.iterdir()) == ["gone", "kept"]

    def test_a_state_tree_the_miss_created_is_gone_before_the_retry(self, child, tmp_path):
        argv, runs = child
        project = tmp_path / "project"
        project.mkdir()
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
        with pytest.warns(hs.HookSpawnRetried):
            result = hs.run_hook_through(argv("first-state"), env=env, input="{}")
        assert (result.stdout.split(), runs()) == (["first", "issue", "-", "False"], 2)
        assert not (project / ".espalier-state").exists()

    def test_a_row_counting_audit_records_never_counts_the_missed_attempts(self, child):
        """A judgment's audit record is read by no hook decision, but a row
        that counts records reads it: the test's own audit directory is put
        back too, so the retry's record is the only one."""
        argv, runs = child
        with pytest.warns(hs.HookSpawnRetried, match="from the audit it began with"):
            result = hs.run_hook_through(argv("first-audit"), env=dict(os.environ), input="{}")
        assert (result.stdout.strip(), runs()) == ("1", 2)

    def test_the_real_home_audit_log_is_never_put_back(self, monkeypatch, tmp_path):
        """Live sessions write the real home's audit log too: a child whose
        audit directory is that one, or under the suite's checkout, has it left
        alone; a row's own directory is the one put back."""
        monkeypatch.delenv("ESPALIER_AUDIT_DIR")
        home_var = "USERPROFILE" if os.name == "nt" else "HOME"
        assert hs._audit_dir({home_var: str(hs.Path.home())}) is None
        assert hs._audit_dir({"ESPALIER_AUDIT_DIR": str(hs.SUITE_CHECKOUT / "audit")}) is None
        assert hs._audit_dir({home_var: str(tmp_path)}) == tmp_path / ".espalier" / "audit"

    @pytest.mark.parametrize("mode", ["first-cc", "first-root"], ids=["cc-blueprint", "root-marker"])
    def test_a_miss_that_changed_the_project_elsewhere_is_not_retried(self, child, tmp_path, mode):
        """The restore reaches .espalier-state and the audit directory alone:
        session_start's blueprint chain under cc/, or a marker at the
        project's root, changed by the miss would be read by the retry, so
        such a miss fails, saying why, instead of being retried."""
        argv, runs = child
        project = tmp_path / "project"
        project.mkdir()
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
        with pytest.raises(pytest.fail.Exception, match="outside what the restore puts back"):
            hs.run_hook_through(argv(mode), env=env, input="{}")
        assert runs() == 1

    def test_a_miss_that_changed_nothing_retries_beside_a_folder_made_in_the_starts_tick(self, child, tmp_path):
        """The walk refuses an mtime after the start, never at it: a folder
        the row made just before the spawn shares the start's tick on Windows,
        and a miss that changed nothing still retries beside it."""
        argv, runs = child
        project = tmp_path / "project"
        (project / "made-just-now").mkdir(parents=True)
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
        with pytest.warns(hs.HookSpawnRetried):
            result = hs.run_hook_through(argv("first-sleep"), env=env, input="{}")
        assert (result.stdout.strip(), runs()) == ("answered", 2)

    def test_a_hooks_bytecode_cache_is_no_change_a_retry_reads(self, child, tmp_path):
        """A miss whose hook imported a sibling module wrote __pycache__ under
        the project: the interpreter's own cache, which no hook decision
        reads, so the miss still retries."""
        argv, runs = child
        project = tmp_path / "project"
        (project / "hooks").mkdir(parents=True)
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
        with pytest.warns(hs.HookSpawnRetried):
            result = hs.run_hook_through(argv("first-pycache"), env=env, input="{}")
        assert (result.stdout.strip(), runs()) == ("answered", 2)

    def test_an_interrupted_wait_leaves_no_child_running(self, child, monkeypatch):
        """Whatever leaves the wait (an interrupt, the per-test ceiling's
        signal) ends the child and its group, as subprocess.run's child was
        ended, never only a timeout."""
        argv, runs = child
        spawned: list[subprocess.Popen] = []

        class InterruptedOnce(subprocess.Popen):
            def communicate(self, *args, **kwargs):
                if spawned:
                    return super().communicate(*args, **kwargs)
                spawned.append(self)
                deadline = time.monotonic() + 10
                while runs() == 0 and time.monotonic() < deadline:
                    time.sleep(0.05)
                raise KeyboardInterrupt

        monkeypatch.setattr(hs.subprocess, "Popen", InterruptedOnce)
        try:
            with pytest.raises(KeyboardInterrupt):
                hs.run_hook_through(argv("first-sleep"), env=None, input="{}")
            assert spawned and spawned[0].poll() is not None, "the child outlived the interrupted wait"
        finally:
            for proc in spawned:
                if proc.poll() is None:
                    proc.kill()

    def test_the_project_is_the_working_directory_when_no_variable_names_it(self, child, tmp_path):
        """A hook with no CLAUDE_PROJECT_DIR resolves its project from its
        working directory, and so does the restore."""
        argv, runs = child
        project = tmp_path / "project"
        project.mkdir()
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        with pytest.warns(hs.HookSpawnRetried, match="from the .espalier-state it began with"):
            result = hs.run_hook_through(argv("first-state"), env=env, input="{}", cwd=str(project))
        assert (result.stdout.split(), runs()) == (["first", "issue", "-", "False"], 2)

    def test_a_grandchild_of_the_missed_attempt_writes_nothing_after_the_restore(self, child, tmp_path):
        """A process the missed attempt started (a reflect spawn, a git) would
        write after the restore and the retry would read it: the attempt's
        whole process group is ended at the miss."""
        argv, runs = child
        project = tmp_path / "project"
        project.mkdir()
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
        with pytest.warns(hs.HookSpawnRetried):
            hs.run_hook_through(argv("first-grandchild"), env=env, input="{}")
        time.sleep(3)   # past the grandchild's 4 s from its start, which began before the 3 s miss
        assert not (project / ".espalier-state" / "late").exists()
        assert runs() == 2

    def test_the_suites_own_checkout_is_never_put_back(self, child, tmp_path, monkeypatch):
        """A live session's hooks write the suite's own checkout's
        .espalier-state too, so a miss that left state there fails as before,
        and what lies there is left as the miss left it."""
        argv, runs = child
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.setattr(hs, "SUITE_CHECKOUT", project.resolve())
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
        with pytest.raises(pytest.fail.Exception, match="outside what the restore puts back"):
            hs.run_hook_through(argv("first-state"), env=env, input="{}")
        assert runs() == 1
        assert (project / ".espalier-state" / "one-shot-flag").is_file()

    def test_the_statusline_keeps_its_own_bound(self, child, monkeypatch):
        """The statusline's 5 s is its prompt-delay check: a statusline as slow
        as a hook may be still reds."""
        argv, _runs = child
        monkeypatch.setattr(hs, "HOOK_S", 9.0)
        assert hs.run_hook_through(argv("slow", "hook.txt"), env=None).stdout.strip() == "answered"
        with pytest.raises(pytest.fail.Exception, match="missed on both attempts"):
            hs.run_hook_through(argv("slow", "line.txt"), env=None, statusline=True)

    def test_bytes_in_is_bytes_out(self, child):
        """A row that sends raw bytes (an encoding-hostile payload) reads raw
        bytes back, as subprocess.run without text did."""
        argv, runs = child
        result = hs.run_hook_through(argv("answer"), env=None, input=b"\xef\xbb\xbf{}")
        assert (result.stdout.strip(), runs()) == (b"answered", 1)


def _deny(reason: str) -> str:
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}})


class TestALongerBoundReadsTheRefusalApart:
    """A spawn past the helper's bound hands its result to ``not_a_budget_miss``
    (DEF-5066): the budget's refusal fails the row as a miss, whichever way the
    row reads a deny, and every other answer, a deny included, comes back as
    it was. Built results, no child: the reader spawns nothing."""

    ARGV = [sys.executable, "write_guard.py"]

    def test_the_budgets_refusal_fails_as_a_miss_not_a_verdict(self):
        refused = subprocess.CompletedProcess(
            self.ARGV, 0, stdout=_deny(f"Command blocked: write_guard {hs.BUDGET_REFUSAL} this command"), stderr="")
        with pytest.raises(pytest.fail.Exception, match="a miss, not a verdict"):
            hs.not_a_budget_miss(refused)

    def test_a_verdict_comes_back_as_it_was(self):
        for result in (
            subprocess.CompletedProcess(self.ARGV, 0, stdout="", stderr=""),
            subprocess.CompletedProcess(self.ARGV, 0, stdout=_deny("a protected zone"), stderr=""),
            subprocess.CompletedProcess(self.ARGV, 2, stdout="", stderr="blocked"),
            subprocess.CompletedProcess(self.ARGV, 1, stdout="", stderr="Traceback"),
        ):
            assert hs.not_a_budget_miss(result) is result

    def test_bytes_out_is_read_and_no_capture_is_no_refusal(self):
        refused = subprocess.CompletedProcess(self.ARGV, 0, stdout=hs.BUDGET_REFUSAL.encode("utf-8"), stderr=b"")
        with pytest.raises(pytest.fail.Exception, match="a miss, not a verdict"):
            hs.not_a_budget_miss(refused)
        uncaptured = subprocess.CompletedProcess(self.ARGV, 0)
        assert hs.not_a_budget_miss(uncaptured) is uncaptured

    def test_the_parents_fallback_refusal_fails_as_a_miss(self):
        fallback = subprocess.CompletedProcess(
            self.ARGV, 0, stdout=_deny(f"Command blocked: write_guard ran out of its 4.0 s {hs.BUDGET_FALLBACK} judged"),
            stderr="")
        with pytest.raises(pytest.fail.Exception, match="a miss, not a verdict"):
            hs.not_a_budget_miss(fallback)


def _spawn(argv: list[str], env: dict | None = None):
    # A bound past the child's 3 s helper bound, as the long-bound sites keep
    # theirs past HOOK_S; written at the call, as the suite contract reads it.
    return lambda: subprocess.run(argv, input="{}", capture_output=True, text=True, encoding="utf-8",
                                  env=env, timeout=10)


class TestALongerBoundRetriesTheRefusalOnce:
    """A spawn past the helper's bound is written inside ``retry_a_budget_miss``
    (DEF-2057): the budget's refusal, which comes back within the parent's
    deadline, is retried once from the state the first attempt began with; a
    timeout is not retried; any other answer, a deny included, is the first
    attempt's; a second refusal fails the row naming both; one retry per
    row, or a pooled build's shared allowance. Before it, the kept-helper
    module's pooled fixtures failed on one refusal and errored every test
    that requested them (#516, job 128669691983)."""

    def test_a_refusal_then_an_answer_returns_the_answer_and_warns(self, child):
        argv, runs = child
        with pytest.warns(hs.HookSpawnRetried, match="budget's refusal"):
            result = hs.retry_a_budget_miss(_spawn(argv("first-budget")), env=None)
        assert (result.stdout.strip(), runs()) == ("answered", 2)

    def test_an_answer_on_the_first_attempt_is_returned_with_no_retry(self, child):
        argv, runs = child
        result = hs.retry_a_budget_miss(_spawn(argv("answer")), env=None)
        assert (result.returncode, result.stdout.strip(), runs()) == (0, "answered", 1)

    def test_two_refusals_fail_the_row_naming_both(self, child):
        argv, runs = child
        with pytest.raises(pytest.fail.Exception, match="budget refusal on both attempts"):
            hs.retry_a_budget_miss(_spawn(argv("always-budget")), env=None)
        assert runs() == 2

    def test_a_deny_is_never_retried(self, child):
        argv, runs = child
        result = hs.retry_a_budget_miss(_spawn(argv("deny")), env=None)
        assert (result.returncode, runs()) == (2, 1)

    def test_a_timeout_is_not_retried(self, child):
        argv, runs = child
        sleeper = argv("first-sleep")
        with pytest.raises(subprocess.TimeoutExpired):
            hs.retry_a_budget_miss(lambda: subprocess.run(sleeper, input="{}", capture_output=True, text=True,
                                                          timeout=2), env=None)
        assert runs() == 1

    def test_the_retry_starts_from_the_state_the_first_attempt_began_with(self, child, tmp_path):
        """A one-shot flag the refused attempt wrote would read as a re-issue:
        the project's .espalier-state is put back first (DEF-2030)."""
        argv, runs = child
        project = tmp_path / "project"
        project.mkdir()
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
        with pytest.warns(hs.HookSpawnRetried, match="from the .espalier-state it began with"):
            result = hs.retry_a_budget_miss(_spawn(argv("first-flagbudget"), env), env=env)
        assert (result.stdout.strip(), runs()) == ("first issue", 2)
        assert not (project / ".espalier-state").exists()

    def test_one_retry_per_row_shared_with_the_short_bound_helper(self, child):
        """The row record is run_hook_through's: a row that spent its retry in
        either helper waits at most one more spawn, never two."""
        argv, runs = child
        with pytest.warns(hs.HookSpawnRetried):
            hs.retry_a_budget_miss(_spawn(argv("first-budget", "one.txt")), env=None)
        with pytest.raises(pytest.fail.Exception, match="spent its one retry"):
            hs.run_hook_through(argv("first-budget", "two.txt"), env=None, input="{}")
        with pytest.raises(pytest.fail.Exception, match="spent its one retry"):
            hs.retry_a_budget_miss(_spawn(argv("first-budget", "three.txt")), env=None)
        assert (runs("one.txt"), runs("two.txt"), runs("three.txt")) == (2, 1, 1)

    def test_a_pooled_build_shares_an_allowance_of_two_across_its_threads(self, child):
        """A fixture spawning on a thread pool runs every job under one row:
        its build passes one RetryAllowance, which its threads spend under a
        lock, and the miss past it fails naming the count."""
        from concurrent.futures import ThreadPoolExecutor

        argv, runs = child
        allowance = hs.RetryAllowance()
        jobs = [argv("first-budget", f"job{i}.txt") for i in range(3)]

        def one(job):
            try:
                return hs.retry_a_budget_miss(_spawn(job), env=None, allowance=allowance).stdout.strip()
            except pytest.fail.Exception as exc:
                return str(exc)

        with pytest.warns(hs.HookSpawnRetried):
            with ThreadPoolExecutor(max_workers=3) as pool:
                out = list(pool.map(one, jobs))
        assert sorted(out)[:2] == ["answered", "answered"], out
        assert "spent its 2 budget retries: 3 misses in one build" in sorted(out)[2], out
        assert (allowance.spent, sum(runs(f"job{i}.txt") for i in range(3))) == (2, 5)

    def test_the_parents_fallback_refusal_is_a_miss_too(self, child):
        """DEF-2057: where the parent cannot import _denial_reasons it refuses
        in plain words with no BUDGET_REFUSAL; both readers and the short-bound
        helper take it as the miss it is."""
        argv, runs = child
        with pytest.warns(hs.HookSpawnRetried, match="budget's refusal"):
            result = hs.retry_a_budget_miss(_spawn(argv("first-fallback")), env=None)
        assert (result.stdout.strip(), runs()) == ("answered", 2)

    def test_the_short_bound_helper_retries_the_fallback_refusal(self, child):
        argv, runs = child
        with pytest.warns(hs.HookSpawnRetried, match="budget's refusal"):
            again = hs.run_hook_through(argv("first-fallback", "short.txt"), env=None, input="{}")
        assert (again.stdout.strip(), runs("short.txt")) == ("answered", 2)
