"""Gate for the gate: `bench/guard_metamorphic.py`'s own liveness.

The sibling of :mod:`tests.test_reachability_differential`. That file pins a gate
whose failure mode is *executing something unconfined*; this one pins a gate whose
failure mode is *validating nothing while reporting zero*.

Both BLOCKs raised against this instrument at authoring time were the instrument's
own version of the defect it exists to catch, and both are pinned here:

* :class:`TestTheInstrumentIsLive` — ``assert_instrument_is_live`` originally
  calibrated only the **Bash** channel while ``R2`` drives only **PowerShell**.
  With a dead PowerShell branch every R2 group reads uniformly ALLOW, so R2a finds
  no variance and R2b gets the ALLOW it wants: zero violations, nothing tested.
* :class:`TestADeadPopulationGatesTheExitCode` — ``_assert_population_is_live``
  mechanises the ``&&`` lesson, but it originally **never reached the return
  value**, so a matrix that had stopped executing would exit 0 having validated
  nothing.

⚠ The point of every test below is that it can observe a REASSURING failure. A
guard that denies nothing, a population that executes nothing, and an axis that
has quietly narrowed all report success. Each is driven here with synthetic input
so the verdict path is seen non-empty rather than assumed.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import os

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "bench" / "guard_metamorphic.py"


def _load():
    spec = importlib.util.spec_from_file_location("_guard_metamorphic", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gm():
    return _load()


def _report(relation="R2", dead=(), violations=(), rows=1, dead_heads=(), absent_heads=()):
    """A minimal report shaped like the real ones, for driving `main`'s verdict."""
    return {
        "relation": relation,
        "description": "synthetic",
        "rows": rows,
        "dead_separators": list(dead),
        "dead_heads": list(dead_heads),
        "absent_heads": list(absent_heads),
        "violations": list(violations),
        "reach_census": {},
    }


class TestTheInstrumentIsLive:
    """A guard that denies nothing scores a comforting zero on every row."""

    def test_the_live_tree_calibrates(self, gm):
        gm.assert_instrument_is_live()

    def test_a_dead_bash_branch_is_caught(self, gm, monkeypatch):
        monkeypatch.setattr(gm, "guard_tier", lambda cmd, tool: "ALLOW")
        with pytest.raises(gm.InstrumentBroken, match="catastrophic delete"):
            gm.assert_instrument_is_live()

    def test_a_dead_powershell_branch_is_caught(self, gm, monkeypatch):
        """The BLOCK. Bash calibrates fine; only PowerShell is dead.

        This is the arm the first version of the function did not have, and it is
        the one that matters: R2 drives PowerShell exclusively.
        """
        real = gm.guard_tier
        monkeypatch.setattr(
            gm, "guard_tier",
            lambda cmd, tool: "ALLOW" if tool == "PowerShell" else real(cmd, tool),
        )
        with pytest.raises(gm.InstrumentBroken, match="PowerShell delete"):
            gm.assert_instrument_is_live()

    def test_an_over_denying_bash_branch_is_caught(self, gm, monkeypatch):
        monkeypatch.setattr(gm, "guard_tier", lambda cmd, tool: "HARD")
        with pytest.raises(gm.InstrumentBroken, match="ls -la"):
            gm.assert_instrument_is_live()

    def test_an_over_denying_powershell_branch_is_caught(self, gm, monkeypatch):
        real = gm.guard_tier
        monkeypatch.setattr(
            gm, "guard_tier",
            lambda cmd, tool: "HARD" if tool == "PowerShell" else real(cmd, tool),
        )
        with pytest.raises(gm.InstrumentBroken, match="Get-Date"):
            gm.assert_instrument_is_live()


class TestADeadPopulationGatesTheExitCode:
    """The `&&` lesson, and the BLOCK that it never reached the return value."""

    def test_a_separator_that_never_reaches_is_reported(self, gm):
        dead = gm._assert_population_is_live(
            [{"separator": "and", "reaches": False},
             {"separator": "and", "reaches": False}]
        )
        assert len(dead) == 1 and "vouches for nothing" in dead[0]

    def test_a_separator_that_reaches_once_is_not_reported(self, gm):
        """One reaching row is enough: the population is live, merely thin."""
        assert gm._assert_population_is_live(
            [{"separator": "and", "reaches": False},
             {"separator": "and", "reaches": True}]
        ) == []

    def test_a_dead_separator_reaches_the_exit_code(self, gm, monkeypatch):
        """The BLOCK: reporting a dead population is not enough — it must gate."""
        monkeypatch.setattr(
            gm, "check_r2",
            lambda quick=False: _report(dead=["and: 0/4 rows reach the delete"]),
        )
        assert gm.main(["--relation", "R2"]) == 1

    def test_a_violation_reaches_the_exit_code(self, gm, monkeypatch):
        monkeypatch.setattr(
            gm, "check_r2",
            lambda quick=False: _report(
                violations=[{"relation": "R2", "detail": "synthetic"}]),
        )
        assert gm.main(["--relation", "R2"]) == 1

    def test_a_clean_relation_exits_zero(self, gm, monkeypatch):
        """The non-vacuity twin: the two arms above must not pass trivially."""
        monkeypatch.setattr(gm, "check_r2", lambda quick=False: _report())
        assert gm.main(["--relation", "R2"]) == 0


class TestTheHeadAxisDerivesFromTheGuard:
    """`HEADS` is read out of the guard, not copied beside it."""

    def test_heads_are_the_guards_own_non_reparsing_set(self, gm):
        """Read through the gate's OWN handle on the guard, so a swap of the
        module it binds to is visible here rather than papered over by a second,
        independently-resolved import."""
        assert gm.HEADS == tuple(sorted(
            gm._bash_patterns._NON_REPARSING_HEADS
            | gm._bash_patterns._READER_HEAD_SPELLINGS))
        # every reader spelling resolves to a family the readers handle
        for head in gm._bash_patterns._READER_HEAD_SPELLINGS:
            assert gm._bash_patterns._reader_family(head) in gm._bash_patterns._READER_FAMILIES, head

    def test_every_head_has_an_explicit_spelling(self, gm):
        """The table is TOTAL and has no default: a head added to
        `_NON_REPARSING_HEADS` with no `_HEAD_ARGS` row used to inherit
        `--version`, a GNU-ism BSD userland rejects, and its `&&` row died
        silently on macOS. Now it is a KeyError at bench time and a red here."""
        missing = sorted(set(gm.HEADS) - set(gm._HEAD_ARGS))
        assert missing == [], f"heads with no `_HEAD_ARGS` row: {missing}"
        stale = sorted(set(gm._HEAD_ARGS) - set(gm.HEADS))
        assert stale == [], f"`_HEAD_ARGS` rows for heads no longer on the roster: {stale}"

    def test_every_derived_head_carries_the_stdin_anti_hang_belt(self, gm):
        """Several heads (`cat`, `tee`, `sort`, the pagers) read stdin when given
        no operand, and an inherited stdin blocks until the timeout — turning a
        stalled row into one that looks unreachable, which
        `_assert_population_is_live` then reads as a dead separator. The belt
        must be on the HEAD's own segment: `_prefix_for` appends one at the end
        of the string, which in a piped spelling binds to the last command, so
        a substring check passed for `yes x | head -n 1` while `yes` itself
        still inherited the terminal (failure-mode pass, driven: hung).
        """
        naked = [
            h for h in gm.HEADS
            if "< /dev/null" not in gm._prefix_for(h).split("|", 1)[0]
        ]
        assert not naked, (
            f"heads whose own segment can block on inherited stdin: {naked}. A "
            "blocked row is indistinguishable from an unreachable one."
        )

    def test_every_piped_spelling_is_declared_status_masked(self, gm):
        """A pipeline's status is its LAST command's, so a piped head's own
        liveness cell cannot fail (driven: `nosuchcmd x | head -n 1` exits 0).
        Such a row is declared with its reason, or it does not exist -- and a
        declared head must still be piped, so the set cannot rot either way."""
        piped = sorted(h for h in gm.HEADS if "|" in gm._HEAD_ARGS[h])
        assert piped == sorted(gm.AND_ROW_STATUS_IS_MASKED), (
            piped, sorted(gm.AND_ROW_STATUS_IS_MASKED)
        )

    def test_the_quick_population_keeps_the_and_axis(self, gm):
        """The per-head gate keys on `&&`, and `--quick` is the only path CI
        takes: a quick sample without it left `dead_heads` unreachable in every
        automated run (failure-mode pass, driven)."""
        assert any(sep == gm.AND_SEPARATOR_NAME for _, sep, _ in gm.bash_rows(quick=True))

    def test_the_separator_axis_is_not_empty(self, gm):
        assert len(gm.SEPARATORS) >= 5
        assert "\n" in dict(
            (name, sep) for name, sep in gm.SEPARATORS
        ).values(), "the newline separator is the one the 2026-08 defect lived on"


@pytest.mark.skipif(os.name == "nt", reason="the liveness helper drives bash through the POSIX group runner (setsid/killpg); a bash child's Windows spelling is unmeasured -- FileNotFoundError on the runner, 2026-09-23")
class TestADeadHeadIsToldFromAnAbsentOne:
    """DEF-695: the per-separator aggregate is green while one head's `&&` row
    is dead, because every other head still reaches -- so a bad `_HEAD_ARGS`
    spelling vouched for nothing invisibly (the three DEF-638 verbs, for a
    day). Per-head liveness on the `&&` axis closes that, and a head the
    platform lacks is ABSENT, never DEAD, so a Linux-only verb does not red
    the macOS run and vice versa."""

    def test_a_present_head_whose_and_row_never_reaches_is_dead(self, gm):
        dead, absent = gm._assert_heads_are_live(
            [{"head": "echo", "separator": "and", "reaches": False},
             {"head": "echo", "separator": "semicolon", "reaches": True}]
        )
        assert absent == []
        assert len(dead) == 1 and dead[0].startswith("echo:") and "vouches for nothing" in dead[0]

    def test_a_builtin_is_present_even_without_a_path_entry(self, gm):
        """`cd` has no binary; a which()-only test would call it absent and
        hide a dead row behind the most common prefix an agent writes."""
        dead, absent = gm._assert_heads_are_live(
            [{"head": "cd", "separator": "and", "reaches": False}]
        )
        assert absent == [] and len(dead) == 1

    def test_an_absent_head_is_reported_absent_not_dead(self, gm):
        dead, absent = gm._assert_heads_are_live(
            [{"head": "no-such-head-espalier-xyz", "separator": "and", "reaches": False}]
        )
        assert dead == [] and absent == ["no-such-head-espalier-xyz"]

    def test_a_head_whose_and_row_reaches_is_neither(self, gm):
        assert gm._assert_heads_are_live(
            [{"head": "echo", "separator": gm.AND_SEPARATOR_NAME, "reaches": True}]
        ) == ([], [])

    def test_a_matrix_without_and_rows_has_nothing_to_say(self, gm):
        """The `--quick` sample keeps only the first two separators; per-head
        liveness on the `&&` axis is then vacuous, not dead."""
        assert gm._assert_heads_are_live(
            [{"head": "echo", "separator": "semicolon", "reaches": True}]
        ) == ([], [])

    def test_the_and_label_is_the_one_bash_rows_emits(self, gm):
        assert gm.AND_SEPARATOR_NAME in dict(gm.SEPARATORS)
        assert dict(gm.SEPARATORS)[gm.AND_SEPARATOR_NAME].strip() == "&&"

    def test_a_dead_head_reaches_the_exit_code(self, gm, monkeypatch):
        monkeypatch.setattr(
            gm, "check_r2",
            lambda quick=False: _report(dead_heads=["echo: its `&&` row never reaches"]),
        )
        assert gm.main(["--relation", "R2"]) == 1

    def test_an_absent_head_does_not_gate(self, gm, monkeypatch):
        monkeypatch.setattr(
            gm, "check_r2", lambda quick=False: _report(absent_heads=["chattr"]),
        )
        assert gm.main(["--relation", "R2"]) == 0

    @pytest.mark.skipif(
        not (shutil.which("bash") and Path("/bin/bash").exists()),
        reason="R1's ground truth is a real /bin/bash",
    )
    def test_every_permission_head_is_live_or_absent_on_this_platform(self, gm):
        """The rows this lane added, DRIVEN through the real oracle: each of the
        six permission heads either reaches the delete behind `&&` (its no-op
        spelling exits 0 here) or is absent from this platform. A present head
        that does not reach is the fail-open this class is made of."""
        from bench.reachability_differential import bash_reaches
        heads = ("chmod", "chown", "chgrp", "chflags", "chattr", "setfacl")
        rows = [
            {"head": h, "separator": sep, "reaches": bash_reaches(tpl)}
            for h, sep, tpl in gm.bash_rows() if h in heads and sep == gm.AND_SEPARATOR_NAME
        ]
        assert {r["head"] for r in rows} == set(heads), "a permission head left the roster"
        dead, absent = gm._assert_heads_are_live(rows)
        assert dead == [], dead
        assert set(absent) <= {"chflags", "chattr", "setfacl"}, absent
        # and at least one of the platform-split three is present HERE, or this
        # run exercised none of the new spellings
        assert len(absent) < 3, "no platform ships none of chflags/chattr/setfacl"


class TestEveryPresentHeadHasALiveSpelling:
    """The suite-side twin of the bench's per-head gate: one `/bin/bash -c
    <prefix>` per roster head in its own scratch cwd, no delete, no matrix. A
    head the platform lacks is skipped (that is the other platform's row); a
    declared cannot-reach head (`false`) is skipped; every other head's
    spelling must exit 0 here. Where it actually runs: on every push on the
    ubuntu leg, which is what drove the Linux-only rows (`chattr -f = .`,
    `setfacl -v`) green on 2026-09-06 and found `fgrep` dead; on macOS only
    when `portability.yml` is dispatched (a measured cost decision), so the
    BSD-only row (`chflags`) has no automatic executor -- drive it locally when
    you touch it; never on the Windows leg (no `/bin/bash`, the skipif below).
    Same interpreter and per-head cwd as the bench, so this green means the
    bench's."""

    @pytest.mark.skipif(
        not (shutil.which("bash") and Path("/bin/bash").exists()),
        reason="the spellings are bash invocations",
    )
    def test_every_present_head_prefix_exits_zero_on_this_platform(self, gm, tmp_path):
        from bench.reachability_differential import run_bash_group
        # cwd is a scratch dir on purpose: several spellings act on `.` (`chmod
        # -f u+r .`, `chflags -f 0 .`, `chattr -f = .`) or create a probe file
        # or dir, and a probe run from the repo root left `probe_file` and
        # `probe_dir` at the root (review, driven). The runner is the bench's
        # group-killing one: a plain subprocess.run(timeout=) left six `yes x`
        # spinning for 34 minutes when a spelling never terminated.
        failing, absent = [], []
        assert len(gm.HEADS) > 40, "the roster shrank -- this floor is the vacuity guard"
        for i, head in enumerate(gm.HEADS):
            if head in gm.AND_ROW_CANNOT_REACH:
                continue
            if not gm._head_is_resolvable(head):
                absent.append(head)
                continue
            scratch = tmp_path / f"head-{i}"   # one cwd per head: rows that touch `.`
            scratch.mkdir()                     # or create files cannot trip a later row
            rc, timed_out = run_bash_group(
                ["/bin/bash", "-c", gm._prefix_for(head)], cwd=scratch, timeout=10,
            )
            if timed_out:
                rc = "timeout"
            if rc != 0:
                failing.append((head, rc, gm._HEAD_ARGS[head]))
        assert not failing, (
            "heads whose `_HEAD_ARGS` spelling does not exit 0 on this platform -- their "
            f"`&&` rows vouch for nothing: {failing}"
        )
        assert len(absent) < len(gm.HEADS) // 2, f"most heads absent? {absent}"


@pytest.mark.skipif(os.name == "nt", reason="the group runner is POSIX by construction (setsid/killpg); on Windows it cannot kill a group and read `exit 3` as rc 1, 2026-09-23")
class TestATimedOutProbeLeavesNoOrphan:
    """`subprocess.run(timeout=)` kills the direct child only. A `bash -c`
    whose spelling never terminates leaves its grandchild running after bash
    is gone -- measured 2026-09-06 as six `yes x` at full CPU for 34 minutes.
    `run_bash_group` runs the probe in its own session and kills the GROUP on
    timeout; this plants a uniquely named grandchild behind `&` and proves it
    does not survive. The marker sleeps five seconds so a regression here
    self-heals instead of pinning a core."""

    @pytest.mark.skipif(
        not (shutil.which("bash") and Path("/bin/bash").exists()),
        reason="needs a real bash and POSIX process groups",
    )
    def test_the_grandchild_dies_with_the_group(self, tmp_path):
        import subprocess
        import uuid
        from bench.reachability_differential import run_bash_group
        marker = f"espalier-orphan-{uuid.uuid4().hex[:12]}"
        cmd = f"exec -a {marker} sleep 5 & wait"
        rc, timed_out = run_bash_group(["bash", "-c", cmd], cwd=tmp_path, timeout=1)
        assert timed_out and rc is None
        survivors = subprocess.run(
            ["ps", "-axo", "command"], capture_output=True, text=True, encoding="utf-8",
        ).stdout
        assert marker not in survivors, (
            f"the grandchild outlived the timed-out probe: {marker}"
        )

    def test_a_terminating_probe_reports_its_status(self, tmp_path):
        from bench.reachability_differential import run_bash_group
        assert run_bash_group(["bash", "-c", "exit 3"], cwd=tmp_path, timeout=5) == (3, False)
        assert run_bash_group(["bash", "-c", "true"], cwd=tmp_path, timeout=5) == (0, False)


class TestTheGateRunsEndToEnd:
    def test_quick_matrix_exits_clean_against_head(self, gm):
        assert gm.main(["--quick"]) == 0


class TestReachCensusIsAlwaysReported:
    def test_census_counts_every_separator_present(self, gm):
        census = gm.reach_census(
            [{"separator": "and", "reaches": True},
             {"separator": "and", "reaches": False},
             {"separator": "semicolon", "reaches": True}]
        )
        assert census == {"and": "1/2", "semicolon": "1/1"}
