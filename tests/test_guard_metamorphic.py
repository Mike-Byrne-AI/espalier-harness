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

import builtins
import importlib.util
import io
import shutil
import sys
from pathlib import Path

import os

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "bench" / "guard_metamorphic.py"
#: The file R4's population is read from (`_operand_class`), named so the
#: proof tier's reader map brings this file with a change to it alone.
R4_POPULATION_SOURCE = "tests/test_write_guard.py"
#: The bench R4's judges build the class's projects from (`check_r4` imports
#: it by module name, which the reader map cannot read), named for the same
#: reason (the second failure-mode review's N-3).
R4_PROJECTS_SOURCE = "bench/powershell_guard_rehearsal.py"


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

    def test_a_refused_row_is_no_verdict_never_a_fail_open(self, gm, monkeypatch, capsys):
        """A row R1's confinement set refuses stops the run before bash sees
        it: exit 3, never the violations' 1 a traceback reads as (air's be8e74
        (3); the sibling differentials' test of the same name). The class is
        the one `bash_reaches` raises, read from its module."""
        from bench.reachability_differential import UnsafeToExecute

        def refused(quick=False):
            raise UnsafeToExecute("driven: a refused row")

        monkeypatch.setattr(gm, "check_r2", refused)
        assert gm.main(["--relation", "R2"]) == 3
        assert "a row the confinement set refuses" in capsys.readouterr().err


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

    def test_the_dead_message_leaves_no_scratch_dir(self, gm, tmp_path, monkeypatch):
        """DEF-5055: the drive behind a dead head's message ran in a dir made
        for it and never removed, so each dead report, this class's own rows
        among them, left an empty ``gm-dead-*`` in the system temp dir (66 on
        the Air, 2026-11-01)."""
        monkeypatch.setattr(gm.tempfile, "tempdir", str(tmp_path))
        dead, _absent = gm._assert_heads_are_live([{"head": "echo", "separator": "and", "reaches": False}])
        assert len(dead) == 1 and "rc=" in dead[0], dead
        assert not list(tmp_path.glob("gm-dead-*")), sorted(p.name for p in tmp_path.iterdir())

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

    @pytest.mark.skipif(
        sys.platform == "win32" or not (shutil.which("bash") and Path("/bin/bash").exists()),
        reason="the sh stub host, resolved by a real bash",
    )
    def test_a_store_alias_python3_is_the_hosts_absent_head(self, gm, tmp_path, monkeypatch):
        """The perturbed CI cell's host: ``python3`` on PATH is a Microsoft
        Store alias stub, which resolves and, run, exits 49 without running
        anything. Who: every lane whose tier put this file on that cell (a
        cheaper tier's own-serial line then; every full-tier run's tiered leg
        since DEF-5136), which red on `python3`'s `-c pass` as a dead spelling
        (#717, air's ack f06ec9). That head is this host's absent one, the
        other hosts' row, by the rule the reachability bench reads for the
        same names (`reachability_differential._MUST_ANSWER`); a `python3`
        that answers is present, and a head with no such probe still reads
        by resolving alone. RED before the fix: the stub read resolvable."""
        from tests._interpreter_hosts import PYTHON3_ONLY, SH, STORE_PYTHON3, build_host, path_with

        monkeypatch.setenv("PATH", path_with(build_host(tmp_path / "store", STORE_PYTHON3, SH)))
        assert gm._head_is_resolvable("python3") is False
        assert gm._head_is_resolvable("python") is True
        assert gm._head_is_resolvable("sed") is True
        monkeypatch.setenv("PATH", path_with(build_host(tmp_path / "only", PYTHON3_ONLY, SH)))
        assert gm._head_is_resolvable("python3") is True
        assert gm._head_is_resolvable("python") is False


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
    # 47 s serial on ubuntu-latest (2026-09-25) against the 60 s global
    # ceiling; under `-n auto` on the same runner it overran, and the thread
    # timeout method exits the xdist worker. scripts/proof_tier.py pins the
    # file to the serial leg (TIMEOUT_NEAR_SERIAL_FILES); the ceiling below is
    # the belt to that brace, for a slower runner. The file is slow-marked, so
    # the raise is allowed and the `not slow` slice never runs it.
    @pytest.mark.timeout(300)
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


# ── R4: a stderr redirect among the operands (DEF-5120) ─────────────────────

_needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="R4's Bash half reads bash's own parser")


def _pwsh_or_skip() -> str:
    from bench.powershell_reachability_differential import find_powershell
    found = find_powershell()
    if found is None:
        pytest.skip("R4's PowerShell half reads PowerShell's own parser, and none is here")
    return found[0]


class TestR4ThePopulationIsTheClasssDeniedRows:
    """R4's rows are read from the class, never copied (STANDING_PRINCIPLES
    §14): a row the class gains joins R4 with no edit in the bench."""

    @staticmethod
    def _tables(gm):
        cls = gm._operand_class()
        return cls, {name: getattr(cls, name) for name in ("_ZONE_ROWS", "_SECRET_ROWS")}

    def test_every_denied_form_and_every_wall_row_is_a_row(self, gm):
        """Each denied form of the operand class's two tables, and each wall
        row of the find class's matrix (DEF-5122), read from the class."""
        cls, tables = self._tables(gm)
        walls = gm._wall_class()._root_rows()
        expected = sum(len(cls._plain_forms(command)) for table in tables.values()
                       for _tool, expect, _arm, command in table.values() if expect == "deny")
        rows = gm.operand_rows()
        assert len(rows) == expected + len(walls)
        assert {r["table"] for r in rows} == set(tables) | {"_MATRIX"}
        assert {r["tool"] for r in rows} == {"Bash", "PowerShell"}
        matrix = [r for r in rows if r["table"] == "_MATRIX"]
        assert [r["command"] for r in matrix] == walls
        assert {(r["tool"], r["arm"], r["kind"]) for r in matrix} == {("Bash", gm.R4_WALL_ARM, "-")}
        assert "find / -exec rm -rf {} +" in walls, "DEF-5122's wall row left the matrix"

    def test_no_allowed_row_joins(self, gm):
        _cls, tables = self._tables(gm)
        allowed = {key for table in tables.values() for key, v in table.items() if v[1] != "deny"}
        assert allowed, "the class holds no allowed row: the filter below would test nothing"
        assert not allowed & {r["key"] for r in gm.operand_rows()}

    def test_the_quick_sample_keeps_both_tools_and_every_table(self, gm):
        rows = gm.operand_rows(quick=True)
        assert {r["tool"] for r in rows} == {"Bash", "PowerShell"}
        assert {r["table"] for r in rows} == {"_ZONE_ROWS", "_SECRET_ROWS", "_MATRIX"}

    def test_the_quick_sample_judges_every_row_once(self, gm):
        """One form per row, every row: CI judges each denied row, and a row
        added moves no other row's sample, since each row's entry is its own
        first form (the failure-mode review's F1; the second code review's N3
        for the second claim)."""
        sample = gm.operand_rows(quick=True)
        quick = [r["key"] for r in sample]
        assert len(quick) == len(set(quick))
        assert set(quick) == {r["key"] for r in gm.operand_rows()}
        first: dict[tuple, str] = {}
        for r in gm.operand_rows():
            first.setdefault((r["table"], r["key"]), r["command"])
        assert [r["command"] for r in sample] == [first[(r["table"], r["key"])] for r in sample]

    def test_the_population_source_is_named_for_the_tier(self, gm):
        """The class R4 reads its rows from is named here as a literal, so a
        change to that file alone brings this file to the proof tier's own
        line (`scripts/proof_tier.py::path_readers` reads names, never an
        import; the failure-mode review's F2): a row added there with a
        tests-only diff is judged by R4 before it merges."""
        module = sys.modules[gm._operand_class().__module__]
        assert Path(module.__file__).resolve().relative_to(REPO_ROOT).as_posix() == R4_POPULATION_SOURCE
        spec = importlib.util.spec_from_file_location("proof_tier_r4", REPO_ROOT / "scripts" / "proof_tier.py")
        pt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pt)
        assert "tests/test_guard_metamorphic.py" in pt.own_tests([R4_POPULATION_SOURCE], REPO_ROOT)
        # the projects' bench, imported by module name inside `check_r4`
        assert "import " + Path(R4_PROJECTS_SOURCE).stem in SCRIPT.read_text(encoding="utf-8")
        assert (REPO_ROOT / R4_PROJECTS_SOURCE).is_file()
        assert "tests/test_guard_metamorphic.py" in pt.own_tests([R4_PROJECTS_SOURCE], REPO_ROOT)

    def test_the_test_that_runs_r4_whole_rides_the_own_line(self, gm):
        """The one test that runs R4 over the whole quick population is the
        one the own line's `-m 'not heavy_e2e'` must keep: marked heavy, it
        would leave the literal above naming a file whose R4 never runs (the
        second failure-mode review's N-2). The mark is conftest's, by name."""
        conftest = next(m for m in list(sys.modules.values())
                        if getattr(m, "__file__", None)
                        and Path(m.__file__).resolve() == REPO_ROOT / "tests" / "conftest.py")
        name = TestTheGateRunsEndToEnd.test_quick_matrix_exits_clean_against_head.__name__
        assert name not in conftest._HEAVY_E2E_TESTS
        marks = [*getattr(TestTheGateRunsEndToEnd.test_quick_matrix_exits_clean_against_head, "pytestmark", []),
                 *getattr(TestTheGateRunsEndToEnd, "pytestmark", []),
                 *getattr(sys.modules[__name__], "pytestmark", [])]
        assert "heavy_e2e" not in {m.name for m in marks}


class TestR4OffersEachBlankAfterTheCommandWord:
    """The scan offers places; the parser decides which are null. These pin
    what is offered: each blank between tokens after the command word, each
    line's end after it, the end, and on Bash the command word's start, never
    inside a quote or a bracket."""

    def test_each_blank_after_the_command_word_and_the_end(self, gm):
        assert gm._token_blanks("rm -f x", "Bash") == [0, 2, 5, 7]

    def test_the_command_words_start_on_bash_and_nothing_inside_a_quote(self, gm):
        cmd = "  rm 'a b' \"c d\""
        assert gm._token_blanks(cmd, "Bash") == [2, 4, 10, len(cmd)]
        assert gm._token_blanks(cmd, "PowerShell") == [4, 10, len(cmd)]

    def test_a_powershell_escape_is_a_backtick(self, gm):
        cmd = "Remove-Item a` b c"
        assert gm._token_blanks(cmd, "PowerShell") == [11, 16, len(cmd)]

    def test_a_bracketed_span_offers_nothing_inside(self, gm):
        cmd = "Remove-Item (Join-Path a b) c"
        assert gm._token_blanks(cmd, "PowerShell") == [11, 27, len(cmd)]

    def test_the_redirect_is_written_at_the_place(self, gm):
        assert gm.insert_redirect("rm -f x", "Bash", 2) == "rm 2>/dev/null -f x"
        assert gm.insert_redirect("rm x", "PowerShell", 4) == "rm x 2>$null"
        assert gm.insert_redirect("rm -f x", "Bash", 0) == "2>/dev/null rm -f x"

    def test_each_spelling_is_written_at_the_place(self, gm):
        """The merge is written as each tool spells it, and every spelling a
        tool holds is written where its first one is (DEF-5122: the directory
        chain lost its anchor to `2>&1` alone)."""
        assert gm.R4_REDIRECTS["Bash"][0] == gm.R4_REDIRECT["Bash"]
        assert "2>&1" in gm.R4_REDIRECTS["Bash"] and "2>&1" in gm.R4_REDIRECTS["PowerShell"]
        assert gm.insert_redirect("cd cc && rm x", "Bash", 5, "2>&1") == "cd cc 2>&1 && rm x"
        assert gm.insert_redirect("rm -f x", "Bash", 0, "2>&1") == "2>&1 rm -f x"
        assert gm.insert_redirect("rm x", "PowerShell", 2, "2>&1") == "rm 2>&1 x"


@_needs_bash
class TestR4TheBashParserIsTheOracle:
    """bash's own parse decides that a place is null: syntax-only, then each
    text defined as a function and printed, never called."""

    def test_a_redirect_among_the_words_is_null_and_a_quoted_one_is_not(self, gm):
        bash = shutil.which("bash")
        form = gm.assert_parsers_are_live(bash, None)
        texts = ["printf %s a b", "printf %s 2>/dev/null a b", "printf %s 'a b'", "printf %s 'a 2>/dev/null b'",
                 "cat <<'EOF'\na b\nEOF", "cat <<'EOF'\na 2>/dev/null b\nEOF"]
        plain, moved, quoted, quoted_moved, body, body_moved = gm.bash_parsed_forms(texts, bash)
        assert gm.bash_insertion_is_null(plain, moved, form)
        assert not gm.bash_insertion_is_null(quoted, quoted_moved, form)
        assert not gm.bash_insertion_is_null(body, body_moved, form), "a heredoc body is data, not a place"

    def test_the_merge_is_proved_on_its_twin_and_parses_as_it(self, gm):
        """bash prints `2>&1` as written, so its own text read back from a
        quoted word reads as a parse: the place is proved on the twin `2>& 1`,
        which bash prints as `2>&1`, and the spelling's own form must equal
        the twin's (DEF-5122's first run: the calibration caught the quoted
        merge read as a redirect)."""
        bash = shutil.which("bash")
        gm.assert_parsers_are_live(bash, None)
        form = gm._bash_redirect_form(bash, "2>&1")
        assert gm._bash_proof("2>&1") == "2>& 1" and gm._bash_proof("2>/dev/null") == "2>/dev/null"
        plain, twin, own, quoted, quoted_twin, quoted_own, body, body_twin = gm.bash_parsed_forms(
            ["cd cc && rm x", "cd cc 2>& 1 && rm x", "cd cc 2>&1 && rm x",
             "printf %s 'a b'", "printf %s 'a 2>& 1 b'", "printf %s 'a 2>&1 b'",
             "cat <<'EOF'\na b\nEOF", "cat <<'EOF'\na 2>& 1 b\nEOF"], bash)
        assert gm.bash_insertion_is_null(plain, twin, form) and own == twin
        assert not gm.bash_insertion_is_null(quoted, quoted_twin, form)
        assert quoted_own != quoted_twin, "a quoted merge is the word's text, not the twin's parse"
        assert gm.bash_insertion_is_null(quoted, quoted_own, form), (
            "the read-back the twin exists for: the merge's own quoted text passes the text test")
        assert not gm.bash_insertion_is_null(body, body_twin, form), "a heredoc body is data, not a place"

    def test_a_spelling_printed_as_written_with_no_twin_is_refused(self, gm, monkeypatch):
        monkeypatch.setattr(gm, "R4_BASH_TWINS", {})
        with pytest.raises(gm.InstrumentBroken, match="as written"):
            gm.assert_parsers_are_live(shutil.which("bash"), None)

    def test_a_twin_that_parses_otherwise_is_refused(self, gm, monkeypatch):
        """A twin is the spelling's proof only while the two parse alike: one
        whose printed difference holds the merge but which parses to more (a
        second merge beside it) passes every check before the last and is
        refused there (the code review's NIT 1: a file-spelling twin was
        refused earlier, for not being the redirect, and left this one
        unpinned)."""
        monkeypatch.setattr(gm, "R4_BASH_TWINS", {"2>&1": "2>&1 2>& 1"})
        with pytest.raises(gm.InstrumentBroken, match="otherwise than its twin"):
            gm.assert_parsers_are_live(shutil.which("bash"), None)

    def test_a_quoted_merge_among_the_candidates_is_no_null_place(self, gm, monkeypatch):
        """In `check_r4`, a merge offered inside a quoted word (a scan that
        offered one) reads as no null place, since its own form differs from
        its twin's: the read-back never reaches a judge."""
        rows = [r for r in gm.operand_rows() if r["tool"] == "Bash" and r["key"] == "bash-delete-plain"][:1]
        assert rows, "the class's plain Bash delete row is gone: pick another anchor"
        row = dict(rows[0], command="printf %s 'a b'", key="quoted-probe")
        # every original is denied, so each null place is counted and none reds
        monkeypatch.setattr(gm._operand_class(), "_zone_denied", staticmethod(lambda *_a: True))
        monkeypatch.setattr(gm, "R4_REDIRECTS", {"Bash": ("2>&1",), "PowerShell": ("2>&1",)})
        census = {}
        for name, place in (("quoted", " b'"), ("control", " 'a")):
            monkeypatch.setattr(gm, "_token_blanks", lambda command, _tool, p=place: [command.index(p)])
            census[name] = gm.check_r4(rows=[row])["null_census"]["Bash"]
        assert census["quoted"].startswith("0/1 places null over 1 "), census
        assert census["control"].startswith("1/1 places null over 1 "), census

    def test_a_rejected_text_gets_no_form_and_its_neighbours_keep_theirs(self, gm):
        forms = gm.bash_parsed_forms(["printf %s a", "printf %s (", "cat <<EOF\nno end", "printf %s b"],
                                     shutil.which("bash"))
        assert forms[0] is not None and forms[3] is not None
        assert forms[1] is None, "a syntax error is the text's own"
        assert forms[2] is None, "a heredoc left open takes the function's brace: one text's reject, not the batch's"

    def test_an_open_heredoc_never_takes_a_neighbours_form(self, gm):
        """A heredoc left open by R4's place after its terminator, between two
        heredoc texts that each close: in one batch it took the closing brace
        and the next text up to that text's terminator, so it got that form
        and the next text an empty one (the code review's first finding)."""
        bash = shutil.which("bash")
        texts = ["cat <<'EOF'\na\nEOF", "cat <<'EOF'\nb\nEOF 2>/dev/null", "cat <<'EOF'\nc\nEOF"]
        alone = [gm.bash_parsed_forms([text], bash)[0] for text in texts]
        assert alone[0] is not None and alone[1] is None and alone[2] is not None, alone
        assert gm.bash_parsed_forms(texts, bash) == alone

    def test_a_batch_past_the_argument_limit_still_prints(self, gm):
        """Each text and each batch's script reach bash on its standard input,
        never as one argument: R4's full population, with the merge spelling
        and its twins, passed the platform's argument limit and the full run
        stopped on a traceback (DEF-5122's first full run). Twelve texts of
        140 KB each pass macOS's 1 MB limit together, and one apiece passes
        Linux's 128 KB for one argument and Windows' 32,767 characters, where
        the syntax pass's `bash -n -c <text>` stopped on WinError 206
        (post-merge-windows run 44168215720)."""
        texts = [f"printf %s {chr(97 + i) * 140_000}" for i in range(12)]
        forms = gm.bash_parsed_forms(texts, shutil.which("bash"))
        assert all(forms), [i for i, f in enumerate(forms) if not f]

    def test_no_text_is_an_argument_and_bash_reads_its_own_bytes(self, gm, monkeypatch):
        """The channel, on every platform: no spawn's argv holds a text, no
        spawn has a pipe for stdin, the parse's PATH directory is empty at
        every spawn, and the syntax pass feeds bash each text's own UTF-8
        bytes. Every text-mode write here is made as Windows makes it (each
        newline as CRLF), so a feed written in text mode reds on every
        platform, not on the Windows leg alone (the reviews' shared finding)."""
        real_open = io.open
        names = ("buffering", "encoding", "errors", "newline", "closefd", "opener")

        def windows_open(file, mode="r", *args, **kwargs):
            kwargs.update(zip(names, args))
            if "b" not in mode and set(mode) & set("wax+") and kwargs.get("newline") is None:
                kwargs["newline"] = "\r\n"
            return real_open(file, mode, **kwargs)

        calls = []
        real = gm.run_bounded

        def recording(argv, **kwargs):
            handle = kwargs.get("stdin")
            fed = None
            if handle is not None:
                fed = handle.read()
                handle.seek(0)  # read() drained the whole file, so 0 is where bash must start
            empty_path = not any(Path(kwargs["env"]["PATH"]).iterdir())
            calls.append((list(argv), fed, kwargs.get("input"), empty_path))
            return real(argv, **kwargs)

        monkeypatch.setattr(io, "open", windows_open)
        monkeypatch.setattr(builtins, "open", windows_open)
        monkeypatch.setattr(gm, "run_bounded", recording)
        texts = ["printf %s 'é marker-a'", "cat <<'EOF'\nmarker-b\nEOF", "printf %s ( marker-c"]
        forms = gm.bash_parsed_forms(texts, shutil.which("bash"))
        assert calls, "the parse spawned nothing"
        assert forms[0] and forms[1] and forms[2] is None, forms
        assert all(given is None for _argv, _fed, given, _empty in calls), "a pipe carried a text"
        assert not [argv for argv, _fed, _given, _empty in calls if any("marker" in part for part in argv)]
        assert all(empty for _argv, _fed, _given, empty in calls), "the parse's PATH directory held a file"
        assert [fed for argv, fed, _given, _empty in calls if "-n" in argv] == [t.encode("utf-8") for t in texts]
        assert all(fed is not None and b"\r" not in fed for _argv, fed, _given, _empty in calls)

    def test_no_text_is_run(self, gm, tmp_path):
        marker = tmp_path / "ran"
        forms = gm.bash_parsed_forms([f"touch '{marker}'", f"printf x > '{marker}'"], shutil.which("bash"))
        assert all(forms)
        assert not marker.exists()


class TestR4ThePowerShellParserIsTheOracle:
    """PowerShell's `Parser::ParseInput` decides that a place is null: the
    commands' elements are unchanged and the one redirection more is the one
    written. It executes nothing."""

    def test_the_parse_reads_null_and_not_null_and_runs_nothing(self, gm, tmp_path):
        pwsh = _pwsh_or_skip()
        gm.assert_parsers_are_live(None, pwsh)
        marker = tmp_path / "ran"
        texts = ["Remove-Item a b", "Remove-Item a 2>$null b", "Remove-Item 'a b'", "Remove-Item 'a 2>$null b'",
                 "Remove-Item (", f"New-Item -ItemType File -Path '{marker}'"]
        plain, moved, quoted, quoted_moved, broken, new_item = gm.powershell_parsed_forms(texts, pwsh)
        assert gm.powershell_insertion_is_null(plain, moved)
        assert not gm.powershell_insertion_is_null(quoted, quoted_moved)
        assert broken is None
        assert new_item is not None and not marker.exists()

    def test_the_merge_reads_null_among_the_words_and_not_inside_a_quote(self, gm):
        """PowerShell's parse names the redirection by its extent, so the merge
        needs no twin there: among the words it is the one redirection more,
        inside a quote it is no redirection (DEF-5122)."""
        pwsh = _pwsh_or_skip()
        plain, moved, quoted, quoted_moved, file_spelling = gm.powershell_parsed_forms(
            ["Remove-Item a b", "Remove-Item a 2>&1 b", "Remove-Item 'a b'", "Remove-Item 'a 2>&1 b'",
             "Remove-Item a 2>$null b"], pwsh)
        assert gm.powershell_insertion_is_null(plain, moved, "2>&1")
        assert not gm.powershell_insertion_is_null(quoted, quoted_moved, "2>&1")
        assert not gm.powershell_insertion_is_null(plain, file_spelling, "2>&1"), "the extent is the spelling's own"


@_needs_bash
class TestR4ADeadOracleOrJudgeGates:
    """Each way R4 could report no violation while judging nothing reds:
    a parser calibration that cannot tell null from not, a population with
    no null place, and a judge that denies no original."""

    def test_a_parser_that_reads_every_place_null_is_caught(self, gm, monkeypatch):
        monkeypatch.setattr(gm, "bash_insertion_is_null", lambda *_a: True)
        with pytest.raises(gm.InstrumentBroken):
            gm.assert_parsers_are_live(shutil.which("bash"), None)

    def test_a_parser_that_reads_no_place_null_is_caught(self, gm, monkeypatch):
        monkeypatch.setattr(gm, "bash_insertion_is_null", lambda *_a: False)
        with pytest.raises(gm.InstrumentBroken):
            gm.assert_parsers_are_live(shutil.which("bash"), None)

    @staticmethod
    def _rows(gm):
        rows = [r for r in gm.operand_rows() if r["tool"] == "Bash" and r["key"] == "bash-delete-plain"]
        assert rows, "the class's plain Bash delete row is gone: pick another anchor"
        return rows

    def test_a_population_with_no_null_place_reads_dead(self, gm, monkeypatch):
        monkeypatch.setattr(gm, "_token_blanks", lambda _command, _tool: [])
        report = gm.check_r4(rows=self._rows(gm))
        assert any("Bash" in d and "null" in d for d in report["dead_separators"]), report

    def test_a_spelling_proved_null_nowhere_reads_dead_beside_a_live_one(self, gm, monkeypatch):
        """A spelling, or a table, whose places the parser never proves null
        reds even while another keeps its tool's total live (the failure-mode
        review's gap 3: the merge went unwritten behind the file spelling's
        count before DEF-5122)."""
        real = gm.bash_insertion_is_null
        monkeypatch.setattr(gm, "assert_parsers_are_live", lambda *_a: None)
        monkeypatch.setattr(gm, "bash_insertion_is_null", lambda o, i, f: "&" not in f and real(o, i, f))
        report = gm.check_r4(rows=self._rows(gm))
        assert report["null_by_part"]["Bash spelling 2>&1"] == 0 < report["null_by_part"]["Bash spelling 2>/dev/null"]
        assert any("spelling 2>&1" in d for d in report["dead_separators"]), report["dead_separators"]
        assert not any("spelling 2>/dev/null" in d or "table" in d for d in report["dead_separators"])

    def test_each_spelling_is_one_the_guard_blanks(self, gm):
        """R4 writes only spellings the guard's second reading blanks, so a
        red on a spelling never points at a helper that leaves it by design
        (the failure-mode review's NIT 4: `&>` and `*>` take the success
        stream, and the reading keeps them)."""
        for tool, spellings in gm.R4_REDIRECTS.items():
            for spelling in spellings:
                command = f"rm {spelling} x"
                free = gm._bash_patterns.stderr_redirect_free_command(command, powershell=tool == "PowerShell")
                assert free.split() == ["rm", "x"], (tool, spelling, free)

    def test_a_judge_that_denies_no_original_reads_dead(self, gm, monkeypatch):
        cls = gm._operand_class()
        monkeypatch.setattr(cls, "_zone_denied", staticmethod(lambda *_a: False))
        report = gm.check_r4(rows=self._rows(gm))
        assert any("judge is dead" in d for d in report["dead_separators"]), report
        assert report["undenied_originals"]


@_needs_bash
class TestR4RedsAReaderOffTheView:
    """The relation's purpose: with the redirect view blinded, the readers
    DEF-2087 put on it lose their operands, and R4 names their rows; on the
    tree as it is, those rows are clean."""

    def test_a_blinded_view_reds_the_rows_it_hid(self, gm, monkeypatch):
        rows = [r for r in gm.operand_rows() if r["tool"] == "Bash" and r["key"].startswith("bash-delete-git-rm")]
        assert rows, "the class's git-rm rows are gone: pick another reader the view feeds"
        assert not gm.check_r4(rows=rows)["violations"]
        monkeypatch.setattr(gm._bash_patterns, "_redirects_blanked", lambda scan, *, powershell: scan)
        blinded = gm.check_r4(rows=rows)
        assert blinded["violations"], "a blinded view left every git-rm row denied: R4 cannot see the job"

    def test_a_red_names_its_next_step(self, gm, monkeypatch, capsys):
        """The red prints its next step: the mechanism a reader goes on, the
        row's arm, and that a red no reader fix meets goes to the dispatcher
        (the failure-mode review's F5: a bare `assert 1 == 0` over a row name
        sent the next session to an exclusion map). The helpers it names are
        the hooks module's own (the second failure-mode review's N-4)."""
        for helper in gm.R4_REMEDY_HELPERS:
            assert callable(getattr(gm._bash_patterns, helper, None)), helper
        import bench.powershell_reachability_differential as differential
        rows = [r for r in gm.operand_rows() if r["tool"] == "Bash" and r["key"].startswith("bash-delete-git-rm")]
        monkeypatch.setattr(gm, "operand_rows", lambda quick=False: rows)
        monkeypatch.setattr(differential, "find_powershell", lambda: None)
        monkeypatch.setattr(gm._bash_patterns, "_redirects_blanked", lambda scan, *, powershell: scan)
        assert gm.main(["--relation", "R4"]) == 1
        out = capsys.readouterr().out
        assert "✗ [R4]" in out, out
        assert "_scan_and_view_matches" in out and "dispatcher" in out, out
        assert f"arm {rows[0]['arm']}" in out, out

    def test_a_quick_red_lists_every_kind_of_its_row(self, gm, monkeypatch):
        """A quick run judges each row on its first kind, a `tools/` path the
        after-check watches; a red there is re-judged on the row's other
        kinds before it reports, so the kinds no after-check watches show
        too, and a red is never read as the after-check's job from the
        sample (the second failure-mode review's SF-1)."""
        real = gm.operand_rows
        monkeypatch.setattr(gm, "operand_rows", lambda quick=False: [
            r for r in real(quick) if r["tool"] == "Bash" and r["key"] == "bash-delete-git-rm"])
        rows = gm.operand_rows()
        assert len(rows) > 1 and rows[0]["kind"].startswith("tools/"), rows
        monkeypatch.setattr(gm._bash_patterns, "_redirects_blanked", lambda scan, *, powershell: scan)
        report = gm.check_r4(quick=True)
        kinds = {v["kind"] for v in report["violations"]}
        assert report["rejudged_kinds"] == len(rows) - 1, report
        assert kinds == {r["kind"] for r in rows}, kinds
        assert any(not k.startswith("tools") for k in kinds), kinds

    def test_a_quick_reds_rejudge_reads_no_tool_dead(self, gm, monkeypatch):
        """The re-judge covers the red rows alone, so a tool it holds none of
        read dead there, and a Bash-only red printed a false "judge is dead"
        line for PowerShell (the third code review's S1, driven with pwsh)."""
        pwsh = _pwsh_or_skip()
        real = gm.operand_rows
        # with a row each carrier takes, since a derived run carrying nothing
        # reads that carrier dead (DEF-5126)
        keep = {("Bash", "bash-delete-git-rm"), ("Bash", "bash-delete-after-a-cd"),
                ("PowerShell", "ps-delete-find-file")}
        monkeypatch.setattr(gm, "operand_rows", lambda quick=False: [
            r for r in real(quick) if (r["tool"], r["key"]) in keep])
        assert {(r["tool"], r["key"]) for r in gm.operand_rows(quick=True)} == keep, "an anchor row is gone"
        bp = gm._bash_patterns
        view = bp._redirects_blanked
        monkeypatch.setattr(bp, "_redirects_blanked",
                            lambda scan, *, powershell: view(scan, powershell=True) if powershell else scan)
        report = gm.check_r4(quick=True, pwsh=pwsh)
        assert {v["tool"] for v in report["violations"]} == {"Bash"}, report["violations"]
        assert report["rejudged_kinds"], report
        assert not report["dead_separators"], report["dead_separators"]


@_needs_bash
class TestR4RedsAHardCheckOffTheStderrFreeReading:
    """DEF-5122's purpose: the readers outside R4's first population held
    their verdict with a redirect among the operands once each hard check was
    judged again on the command with its error-stream redirects blanked
    (`write_guard._also_stderr_redirect_free`). With that reading blinded,
    R4 names their rows, and the directory chain reds on the merge alone, the
    spelling R4 did not write before this lane; on the tree as it is, they
    are clean."""

    _BASH = ("bash-symlink-into-zone", "bash-delete-after-a-cd", "find / -exec rm -rf {} +")
    _POWERSHELL = ("ps-start-process-carried", "ps-iex-carried", "ps-pwsh-command-carried")

    @staticmethod
    def _rows(gm, keys):
        rows = [r for r in gm.operand_rows(quick=True) if r["key"] in keys]
        assert {r["key"] for r in rows} == set(keys), "an anchor row is gone: re-read which rows DEF-5122 enrolled"
        return rows

    @staticmethod
    def _blind(gm, monkeypatch):
        """The judges' own write_guard (each imports it by name from the hooks
        folder the bench puts on the path), its second reading made the first."""
        assert gm._bash_patterns.__name__ == "_bash_patterns"
        import write_guard as wg
        assert callable(getattr(wg, "_also_stderr_redirect_free", None)), "R4_REMEDY names a helper that is gone"
        monkeypatch.setattr(wg, "_stderr_redirect_free", lambda command, powershell: command)

    def test_a_blinded_reading_reds_the_bash_rows_it_held(self, gm, monkeypatch):
        rows = self._rows(gm, self._BASH)
        assert not gm.check_r4(rows=rows)["violations"]
        self._blind(gm, monkeypatch)
        blinded = gm.check_r4(rows=rows)
        assert {v["key"] for v in blinded["violations"]} == set(self._BASH), blinded["violations"]
        chain = [v["detail"] for v in blinded["violations"] if v["key"] == "bash-delete-after-a-cd"]
        assert chain and all("2>&1" in d for d in chain), chain
        assert "_also_stderr_redirect_free" in blinded["remedy"]

    def test_a_blinded_reading_reds_the_powershell_rows_it_held(self, gm, monkeypatch):
        pwsh = _pwsh_or_skip()
        rows = self._rows(gm, self._POWERSHELL)
        assert not gm.check_r4(rows=rows, pwsh=pwsh)["violations"]
        self._blind(gm, monkeypatch)
        blinded = gm.check_r4(rows=rows, pwsh=pwsh)
        assert {v["key"] for v in blinded["violations"]} == set(self._POWERSHELL), blinded["violations"]


@_needs_bash
class TestR4TheStdinProgramRowHoldsOnEveryKind:
    """The row the stdin reader missed on every kind, three of them no
    after-check watches (`cc/` and the two settings files): a redirect before
    the `-` operand hid the heredoc program, until the opener matched on the
    redirect view with the heredoc operator kept (DEF-5120). Judged here
    whole, since the quick sample crosses it on one kind at most."""

    def test_every_kind_holds_its_deny_under_every_null_place(self, gm):
        rows = [r for r in gm.operand_rows() if r["key"] == "bash-delete-python-stdin"]
        assert len(rows) >= 7, "the class's stdin-program row lost kinds: re-read which ones R4 judges"
        report = gm.check_r4(rows=rows)
        assert not report["violations"], report["violations"]
        # each kind has a null place of its own: a total over the kinds would
        # pass with one kind judged on none (the second code review's N6)
        assert {r["kind"] for r in rows} == {k for k, n in report["null_by_kind"].items() if n}, report


class TestR4OffersThePlacesInsideACarriedProgram:
    """DEF-5126: R4 lays each denied Bash row inside each carrier the redirect
    view reads one level down, and offers the places inside the carried
    program as well as the command's own, within the view's stated reach (air's
    ruling fd58a2), each proved null on the program's own parse."""

    @staticmethod
    def _inner(gm, command):
        return [at for at, span in gm.r4_places(command, "Bash") if span is not None]

    def test_each_carrier_offers_its_programs_places(self, gm):
        """Each blank of the carried program after its command word and its
        end; a substitution body also its command word's start, where a word's
        is left out (a redirect there opens the word on a prefix)."""
        for name, (before, after) in gm.R4_CARRIERS.items():
            command = before + "rm -f x" + after
            k = len(before)
            first = [k] if gm._R4_CARRIER_KIND[name] == "body" else []
            assert self._inner(gm, command) == first + [k + 2, k + 5, k + 7], name

    def test_a_double_quoted_exec_word_is_carried_too(self, gm):
        """The filed probe's spelling: a double-quoted `-c` word holding none of
        the four characters special inside double quotes hands its inside down."""
        command = 'bash -c "git status --short"'
        assert self._inner(gm, command), command

    def test_nothing_is_offered_outside_the_stated_reach(self, gm):
        """A word holding a `$` or a quote, a word opening on a prefix, a body
        holding a double quote, and a quoted word no shell or `eval` takes:
        none is a program the view reads in place, so none gets a place."""
        for command in ("bash -c 'rm -f $x'", "eval 'rm \"x\"'", "bash -c 'sudo rm x'",
                        "bash -c 'X=1 rm x'", 'echo "$(rm "x")"', "git -c 'rm x'", "printf %s 'rm x'"):
            assert self._inner(gm, command) == [], command

    def test_a_carrier_head_counts_only_at_a_command_position(self, gm):
        """A `-c` shell or an `eval` hands its word down only where it opens a
        statement (the code review's M1): as another command's argument it
        hands nothing down, and after a separator it does."""
        assert self._inner(gm, "echo eval 'rm -f x'") == []
        assert self._inner(gm, "echo bash -c 'rm -f x'") == []
        assert self._inner(gm, "cd d && bash -c 'rm -f x'")
        assert self._inner(gm, "true; eval 'rm -f x'")
        assert self._inner(gm, "rm y 2>&1 eval 'rm -f x'") == [], "a redirect's & opened a statement"

    def test_one_level_only(self, gm):
        """R4 reads one level down, its own limit: the view also reads one
        exec-quoted word inside a body, pinned there by the hand rows of
        `tests/test_write_guard.py::TestARedirectInsideAHandedDownProgramKeepsTheVerdict`
        (the failure-mode review's MINOR 6); R4 offers the body and not the
        word inside it."""
        command = "echo \"$(bash -c 'rm -f x')\""
        quote = command.index("'")
        inner = self._inner(gm, command)
        assert inner and not any(quote < at < command.rindex("'") for at in inner), inner

    def test_every_plain_place_is_kept(self, gm):
        """Every place R4 offered before DEF-5126 is still offered, read the
        same way: the command's own places are `_token_blanks`' own."""
        for row in gm.operand_rows(quick=True):
            own = [at for at, span in gm.r4_places(row["command"], row["tool"]) if span is None]
            assert own == gm._token_blanks(row["command"], row["tool"]), row["key"]

    def test_the_carried_rows_are_the_class_rows_carried(self, gm):
        """Read from the class, never copied: each Bash row is carried in each
        carrier or counted outside its reach, a PowerShell row never, and a
        carried row is never carried again."""
        plain = gm.operand_rows(quick=True)
        bash = [r for r in plain if r["tool"] == "Bash"]
        carried, outside = gm.carried_rows(plain)
        for name, (before, after) in gm.R4_CARRIERS.items():
            mine = [r for r in carried if r["carrier"] == name]
            assert mine, f"no row is carried in {name}: R4 vouches for nothing there"
            assert len(mine) + outside[name] == len(bash), name
            assert all(r["command"].startswith(before) and r["command"].endswith(after) for r in mine)
        assert not gm.carried_rows(carried)[0]

    def test_each_prefix_word_is_one_the_view_reads(self, gm):
        """R4's own prefix list names only what the view's family reads as a
        prefix, so a word left here after the view stopped reading it cannot
        hide a carried row the view reads (the blind direction)."""
        assert "sudo" in gm.R4_WORD_PREFIXES
        for word in [*gm.R4_WORD_PREFIXES, "X=1", "!", "2>x", "<x"]:
            assert gm._R4_WORD_PREFIX_RE.match(word + " rm x"), word
            assert gm._bash_patterns._PROGRAM_OPENS_ON_PREFIX_RE.match("'" + word + " rm x'"), word

    def test_the_reach_characters_are_the_views(self, gm):
        """Each character R4's reach leaves out is one the view reads no
        program across, and a program free of them is read (the failure-mode
        review's MAJOR 1): a view that widens to read past one reds here and
        names `R4_REACH`, so R4 cannot stay blind to the rows it now reads."""
        handed = gm._bash_patterns._programs_handed_down

        def spans(command, start):
            return handed(command, start, len(command))

        assert spans("bash -c 'rm -f x'", 8), "the view reads no plain -c word: the controls are dead"
        assert spans('echo "$(rm -f x)"', 5), "the view reads no plain body: the controls are dead"
        for ch in gm.R4_REACH["word"]:
            quote = '"' if ch == "'" else "'"
            word = f"{quote}rm -f x{ch}y{quote}"
            assert spans("bash -c " + word, 8) == [], f"R4_REACH['word'] leaves out {ch!r}, the view reads it"
        for ch in gm.R4_REACH["body"]:
            body = "rm -f x" + ("\\y" if ch == "\\" else f"{ch}y{ch}")
            command = 'echo "$(' + body + ')"'
            assert spans(command, 5) == [], f"R4_REACH['body'] leaves out {ch!r}, the view reads it"

    def test_each_spelling_stays_inside_the_reach(self, gm):
        """A spelling R4 writes adds none of the reach's characters to a
        carried program, so the carrier still hands it down whole (the
        failure-mode review's MINOR 7)."""
        for spelling in gm.R4_REDIRECTS["Bash"] + tuple(gm.R4_BASH_TWINS.values()):
            for kind in gm.R4_REACH:
                assert gm._in_reach("rm " + spelling + " x", kind), (spelling, kind)


@_needs_bash
class TestR4RedsTheNestedReadingOffTheView:
    """The relation's new axis is live (`memory/a-gate-can-be-blind-along-a-whole-dimension.md`):
    with the view's one-level reading blinded, the carried rows red in every
    carrier; on the tree as it is, they are clean."""

    @staticmethod
    def _rows(gm):
        # the plain rows beside their carried ones, as a derived run has them:
        # a run of carried rows alone reads the plain census dead
        plain = [r for r in gm.operand_rows() if r["tool"] == "Bash" and r["key"] == "bash-delete-after-a-cd"]
        assert plain, "the class's delete-after-a-cd row is gone: pick another row the view carries"
        return plain + gm.carried_rows(plain)[0]

    def test_a_blinded_nested_reading_reds_every_carrier(self, gm, monkeypatch):
        rows = self._rows(gm)
        report = gm.check_r4(rows=rows)
        assert not report["violations"], report["violations"]
        assert not report["dead_separators"], report["dead_separators"]
        monkeypatch.setattr(gm._bash_patterns, "_nested_programs_blanked", lambda scan, start, end, chars: chars)
        blinded = gm.check_r4(rows=rows)
        assert {v["carrier"] for v in blinded["violations"]} == set(gm.R4_CARRIERS), blinded["violations"]
        assert all(v["inside"] for v in blinded["violations"])

    def test_the_derived_run_carries_the_rows_it_judges(self, gm, monkeypatch):
        """R4's own derived run lays its rows in the carriers: with the view's
        one-level reading blinded it reds on a row whose plain form that
        blinding leaves denied. Before DEF-5126 R4 offered no place inside a
        carried program, and this run stayed green (the row's guard, through
        the names the bench had then)."""
        real = gm.operand_rows
        monkeypatch.setattr(gm, "operand_rows", lambda quick=False: [
            r for r in real(quick) if r["tool"] == "Bash" and r["key"] == "bash-delete-after-a-cd"])
        monkeypatch.setattr(gm._bash_patterns, "_nested_programs_blanked", lambda scan, start, end, chars: chars)
        report = gm.check_r4(quick=True)
        assert report["violations"], "R4's derived run offered no place inside a carried program"

    def test_a_carrier_the_judge_never_denies_reads_dead(self, gm, monkeypatch):
        cls = gm._operand_class()
        real = cls._zone_denied
        monkeypatch.setattr(cls, "_zone_denied",
                            staticmethod(lambda tool, text, project: not text.startswith("eval ")
                                         and real(tool, text, project)))
        report = gm.check_r4(rows=self._rows(gm))
        assert any("carried in eval" in d for d in report["dead_separators"]), report["dead_separators"]
        assert report["carried_undenied"] and all(x.endswith("in eval") for x in report["carried_undenied"])

    def test_a_carrier_whose_inner_places_vanish_reads_dead(self, gm, monkeypatch):
        """The carrier's own outer places stay null when its inner places are
        lost, so the inner places gate apart (the failure-mode review's
        MINOR 3, the code review's M3)."""
        monkeypatch.setattr(gm, "_carried_spans", lambda _command: [])
        report = gm.check_r4(rows=self._rows(gm))
        assert {name for name in gm.R4_CARRIERS
                if any(f"carried in {name} is proved null" in d for d in report["dead_separators"])} \
            == set(gm.R4_CARRIERS), report["dead_separators"]
