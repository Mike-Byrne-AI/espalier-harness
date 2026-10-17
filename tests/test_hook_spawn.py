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

import os
import sys

import pytest

from tests import _hook_spawn as hs

# A child that counts its runs in the file it is given, then behaves by
# ``mode``: answer, sleep past the bound, print the budget's refusal, leave a
# file under the project's .espalier-state, or take 4.5 s every time; the
# ``first-`` modes miss on the first run only.
_CHILD = r'''
import os, sys, time
from pathlib import Path
counter, mode = sys.argv[1], sys.argv[2]
with open(counter, "a", encoding="utf-8") as fh:
    fh.write("x")
runs = len(open(counter, encoding="utf-8").read())
miss = mode.startswith("always-") or (mode.startswith("first-") and runs == 1)
if mode == "slow":
    time.sleep(4.5)
if miss and mode.endswith("-state"):
    state = Path(os.environ["CLAUDE_PROJECT_DIR"]) / ".espalier-state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "one-shot-flag").write_text("x", encoding="utf-8")
    time.sleep(30)
if miss and mode.endswith("sleep"):
    time.sleep(30)
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

    def test_a_miss_that_left_state_is_not_retried(self, child, tmp_path):
        """A speed bump's one-shot flag written before the miss would make the
        retry read as a re-issue and answer differently; such a miss fails,
        saying why, instead of being retried."""
        argv, runs = child
        project = tmp_path / "project"
        project.mkdir()
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
        with pytest.raises(pytest.fail.Exception, match="leaving state under .espalier-state"):
            hs.run_hook_through(argv("first-state"), env=env, input="{}")
        assert runs() == 1

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
