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

    def test_every_denied_form_of_both_tables_is_a_row(self, gm):
        cls, tables = self._tables(gm)
        expected = sum(len(cls._plain_forms(command)) for table in tables.values()
                       for _tool, expect, _arm, command in table.values() if expect == "deny")
        rows = gm.operand_rows()
        assert len(rows) == expected
        assert {r["table"] for r in rows} == set(tables)
        assert {r["tool"] for r in rows} == {"Bash", "PowerShell"}

    def test_no_allowed_row_joins(self, gm):
        _cls, tables = self._tables(gm)
        allowed = {key for table in tables.values() for key, v in table.items() if v[1] != "deny"}
        assert allowed, "the class holds no allowed row: the filter below would test nothing"
        assert not allowed & {r["key"] for r in gm.operand_rows()}

    def test_the_quick_sample_keeps_both_tools_and_both_tables(self, gm):
        rows = gm.operand_rows(quick=True)
        assert {r["tool"] for r in rows} == {"Bash", "PowerShell"}
        assert {r["table"] for r in rows} == {"_ZONE_ROWS", "_SECRET_ROWS"}


class TestR4OffersEachBlankAfterTheCommandWord:
    """The scan offers places; the parser decides which are null. These pin
    what is offered: each blank between tokens after the command word, each
    line's end after it, and the end, never inside a quote or a bracket."""

    def test_each_blank_after_the_command_word_and_the_end(self, gm):
        assert gm._token_blanks("rm -f x", "Bash") == [2, 5, 7]

    def test_nothing_before_the_first_word_or_inside_a_quote(self, gm):
        cmd = "  rm 'a b' \"c d\""
        assert gm._token_blanks(cmd, "Bash") == [4, 10, len(cmd)]

    def test_a_powershell_escape_is_a_backtick(self, gm):
        cmd = "Remove-Item a` b c"
        assert gm._token_blanks(cmd, "PowerShell") == [11, 16, len(cmd)]

    def test_a_bracketed_span_offers_nothing_inside(self, gm):
        cmd = "Remove-Item (Join-Path a b) c"
        assert gm._token_blanks(cmd, "PowerShell") == [11, 27, len(cmd)]

    def test_the_redirect_is_written_at_the_place(self, gm):
        assert gm.insert_redirect("rm -f x", "Bash", 2) == "rm 2>/dev/null -f x"
        assert gm.insert_redirect("rm x", "PowerShell", 4) == "rm x 2>$null"


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

    def test_a_rejected_text_gets_no_form_and_its_neighbours_keep_theirs(self, gm):
        forms = gm.bash_parsed_forms(["printf %s a", "printf %s (", "cat <<EOF\nno end", "printf %s b"],
                                     shutil.which("bash"))
        assert forms[0] is not None and forms[3] is not None
        assert forms[1] is None, "a syntax error is the text's own"
        assert forms[2] is None, "a heredoc left open takes the function's brace: one text's reject, not the batch's"

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


@_needs_bash
class TestR4ExcludesARowByNameAndRedsAStaleExclusion:
    """The coverage contract's exclusion (DEF-5120): a row whose job is the
    after-check's is held out of R4 by name, still judged, its reds reported
    apart; an exclusion whose row holds everywhere is a violation, so the day
    a reader closes it the entry goes."""

    @staticmethod
    def _rows(gm, key):
        rows = [r for r in gm.operand_rows() if r["key"] == key]
        assert rows, f"the class's {key} row is gone: re-read R4_EXCLUDED"
        return rows

    def test_every_exclusion_names_a_denied_row_of_the_class(self, gm):
        keys = {r["key"] for r in gm.operand_rows()}
        assert gm.R4_EXCLUDED, "R4 excludes nothing: drop this class with the map"
        assert set(gm.R4_EXCLUDED) <= keys, set(gm.R4_EXCLUDED) - keys

    def test_an_excluded_rows_red_is_reported_apart(self, gm):
        report = gm.check_r4(rows=self._rows(gm, "bash-delete-python-stdin"))
        assert not report["violations"], report["violations"]
        assert {e["key"] for e in report["excluded"]} == {"bash-delete-python-stdin"}

    def test_an_exclusion_whose_row_holds_is_a_violation(self, gm, monkeypatch):
        monkeypatch.setitem(gm.R4_EXCLUDED, "bash-delete-plain", "a row that holds")
        report = gm.check_r4(rows=self._rows(gm, "bash-delete-plain"))
        assert not report["excluded"]
        assert [v["key"] for v in report["violations"]] == ["bash-delete-plain"]
        assert "drop the exclusion" in report["violations"][0]["detail"]
