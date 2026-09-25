"""Gate for the gate: `bench/powershell_reachability_differential.py`.

The PowerShell twin of :mod:`tests.test_reachability_differential`, and it carries
one hazard its Bash sibling does not: **this gate stands down when `pwsh` is
absent, returning 0.** On a host without PowerShell — which includes this repo's
usual macOS dev machine — a wrapper that only asserted ``main() == 0`` would pass
without the gate ever running. That is the "comforting zero" the whole TP-445
family exists to refuse, reproduced inside the gate's own test.

So the tests below split deliberately:

* :class:`TestItStandsDownRatherThanFakingAGreen` — pins that a stood-down run is
  *distinguishable* from an earned one. This is the anti-vacuity core and it runs
  everywhere, `pwsh` or not.
* :class:`TestThePrecedingClassDerivesFromTheGuard` — pins §14 ("derive the list,
  don't test a hand-written copy") **and** §18.4: the derivation is checked
  against a floor that does not derive from its subject, so a guard that quietly
  narrows raises instead of silently attacking a smaller alphabet.
* :class:`TestTheGateRunsEndToEnd` — the only class gated on a real interpreter.

⚠ The `_derive_preceding_chars` mutation arms below are the ones that matter. At
authoring time the first version of that derivation took "the first character
class" and a pattern with the command-position class removed still matched the
trailing ``[ \\t]*`` whitespace run — so the gate would have gone on attacking a
two-character alphabet and reported no violations. Selection is by CONTENT now,
and all three refusal paths are driven here.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "bench" / "powershell_reachability_differential.py"


def _load():
    spec = importlib.util.spec_from_file_location("_ps_reach_diff", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def prd():
    return _load()


class TestItStandsDownRatherThanFakingAGreen:
    """A skipped run and an earned green must not look the same to a caller."""

    def test_absent_powershell_reports_skipped_not_a_pass(self, prd, monkeypatch,
                                                          capsys):
        monkeypatch.setattr(prd, "find_powershell", lambda: None)
        rc = prd.main(["--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["skipped"] is True, (
            "a host without `pwsh` must be reported as SKIPPED. Returning a bare 0 "
            "with no marker lets a CI wrapper read 'stood down' as 'no fail-opens'."
        )

    def test_the_skip_names_how_to_supply_an_interpreter(self, prd, monkeypatch,
                                                         capsys):
        monkeypatch.setattr(prd, "find_powershell", lambda: None)
        prd.main(["--json"])
        reason = json.loads(capsys.readouterr().out)["reason"]
        assert "ESPALIER_PWSH" in reason and "pwsh" in reason

    def test_a_stood_down_run_carries_no_interpreter_key(self, prd, monkeypatch,
                                                         capsys):
        """The positive discriminator: an earned run reports its interpreter.

        Asserting only on `skipped` would let a future refactor emit both keys and
        still satisfy the arm above.
        """
        monkeypatch.setattr(prd, "find_powershell", lambda: None)
        prd.main(["--json"])
        assert "interpreter" not in json.loads(capsys.readouterr().out)


class TestThePrecedingClassDerivesFromTheGuard:
    """§14 derive-don't-copy, plus the §18.4 floor that does not derive."""

    def test_the_live_derivation_covers_the_floor(self, prd):
        derived = set(prd._derive_preceding_chars())
        assert prd._REQUIRED_PRECEDING <= derived

    def test_a_stale_pattern_with_no_class_raises(self, prd, monkeypatch):
        monkeypatch.setattr(prd._bash_patterns, "_PS_CMD_POS_SEP", "nothing-here")
        with pytest.raises(prd.InstrumentBroken, match="no character class"):
            prd._derive_preceding_chars()

    def test_a_class_without_the_separators_is_refused(self, prd, monkeypatch):
        """THE MUTATION THAT ALMOST SHIPPED.

        A pattern whose command-position class is gone but which still carries the
        trailing whitespace run must NOT be accepted — selection is by content, so
        the gate refuses rather than attacking `[ \\t]`.
        """
        monkeypatch.setattr(prd._bash_patterns, "_PS_CMD_POS_SEP", r"[ \t]*")
        with pytest.raises(prd.InstrumentBroken, match="statement separators"):
            prd._derive_preceding_chars()

    def test_a_narrowed_class_raises_rather_than_reporting_green(self, prd,
                                                                 monkeypatch):
        """The floor. Removing `\\n` from the guard's own class must be loud."""
        keep = "".join(sorted(prd._REQUIRED_PRECEDING - {"\n"}))
        monkeypatch.setattr(
            prd._bash_patterns, "_PS_CMD_POS_SEP", f"[{keep}][ \t]*"
        )
        with pytest.raises(prd.InstrumentBroken, match="lost"):
            prd._derive_preceding_chars()


class TestClassificationIsExhaustive:
    """Every (reaches, tier) corner has a declared verdict."""

    @pytest.mark.parametrize(
        "reaches,tier,expected",
        [
            (True, "ALLOW", "fail_open"),
            (True, "HARD", "agrees"),
            (False, "HARD", "false_positive"),
            (False, "ALLOW", "agrees"),
        ],
    )
    def test_classification(self, prd, reaches, tier, expected):
        assert prd.classify(reaches, tier) == expected

    def test_a_fail_open_is_the_only_verdict_that_can_pass_silently(self, prd):
        """Naming the asymmetry: a fail-open is a real delete the guard allowed."""
        assert prd.classify(True, "ALLOW") == prd.FAIL_OPEN
        assert prd.FAIL_OPEN != prd.AGREES


class TestRefusesToExecuteAnythingUnconfined:
    """This script hands real deletes to a real interpreter."""

    def test_accepts_a_properly_confined_command(self, prd, tmp_path):
        """⚠ RELATIVE by design. The rows use relative operands because the
        guard's operand parser tiers on exactly that, so the Bash sibling's
        "absolute sandbox path must appear" check is NOT reusable here."""
        victim = tmp_path / "victim"
        victim.mkdir()
        prd.assert_safe_to_execute("Remove-Item -Recurse -Force ./victim",
                                   victim, tmp_path)

    def test_refuses_an_unsubstituted_placeholder(self, prd, tmp_path):
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match="placeholder"):
            prd.assert_safe_to_execute(
                f"Remove-Item -Recurse -Force {prd._TARGET}", victim, tmp_path)

    def test_refuses_a_command_with_no_declared_sandbox_operand(self, prd,
                                                                tmp_path):
        """The replacement for the absolute-path check, and it must not degrade
        to "the word victim appears somewhere"."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match="declared sandbox operand"):
            prd.assert_safe_to_execute(
                "Remove-Item -Recurse -Force /somewhere/else", victim, tmp_path)

    @pytest.mark.parametrize(
        "trailing",
        ["/", "~", "C:" + chr(92), ",/", ",~"],
        ids=["root", "home", "drive-root", "comma-root", "comma-home"],
    )
    def test_refuses_a_catastrophic_operand_riding_alongside_a_declared_one(
        self, prd, tmp_path, trailing
    ):
        """⚠ REGRESSION PIN. Found by this wrapper on the day it was written, and
        confirmed on BOTH legs before it was fixed.

        Every one of conditions 2-5 anchors on the delete verb plus its FIRST
        operand, so a second operand riding behind a declared one was invisible to
        all of them: `Remove-Item -Recurse -Force ./victim /` was ACCEPTED, and the
        Bash sibling accepted a home-directory delete. PowerShell's positional
        `-Path` is `string[]`, so both operands really do bind and really do
        delete. The comma spellings are here because `-Path a,b` is the other way
        an operand list arrives.
        """
        victim = tmp_path / "victim"
        victim.mkdir()
        joiner = "" if trailing.startswith(",") else " "
        with pytest.raises(prd.UnsafeToExecute, match="operand"):
            prd.assert_safe_to_execute(
                f"Remove-Item -Recurse -Force ./victim{joiner}{trailing}",
                victim, tmp_path)

    @pytest.mark.parametrize("command", [
        "gci -Path:/ -Recurse | ri -r -fo ; echo ./victim",
        "gci ./victim -Recurse | ri -r -fo -LiteralPath:/",
        "find / ./victim -delete",
        "gci ./victim,/ -Recurse | ri -r -fo",
        "Get-ChildItem -Path ~ -Recurse | Remove-Item -Recurse -Force ./victim",
    ], ids=["colon-bound-root", "colon-bound-remove", "find-second-root",
            "comma-root", "enumerator-home"])
    def test_refuses_a_catastrophic_root_under_a_sweep_head(self, prd, tmp_path, command):
        """The sweep rows (DEF-824, DEF-822) delete under an ENUMERATOR's or
        find's roots, so every head and every operand spelling must reach
        the assertion -- including a colon-bound `-Path:/`, which the first
        cut's tokenizer dropped as a flag while the guard's own reader binds
        it (code review, driven: two such rows would have executed)."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match="operand"):
            prd.assert_safe_to_execute(command, victim, tmp_path)

    def test_a_pattern_flags_value_is_not_a_root_but_a_root_behind_it_is(self, prd, tmp_path):
        """`-Include *` is a pattern the enumerator applies, never a delete
        root, so the sweep row that spells the catch-all is accepted; the
        one flag value the over-collection skips must not hide a root that
        rides behind the flag."""
        victim = tmp_path / "victim"
        victim.mkdir()
        prd.assert_safe_to_execute("gci ./victim -Recurse -Include * | ri -r -fo", victim, tmp_path)
        prd.assert_safe_to_execute("gci ./victim -Recurse -Include:* | ri -r -fo", victim, tmp_path)
        with pytest.raises(prd.UnsafeToExecute, match="operand"):
            prd.assert_safe_to_execute("gci -Include * / -Recurse | ri -r -fo ; echo ./victim",
                                       victim, tmp_path)
        with pytest.raises(prd.UnsafeToExecute, match="operand"):
            prd.assert_safe_to_execute("gci -Include * -Path:~ -Recurse | ri -r -fo ; echo ./victim",
                                       victim, tmp_path)

    def test_the_head_rosters_derive_from_the_guard(self, prd):
        """The safety assertion's heads are the guard's own verb rosters, not
        a hand copy (failure-mode review): a verb added to `_PS_REMOVE_VERB`
        or `_PS_ENUMERATE_VERB`, or a head added to the carrier's head table
        (DEF-831: the version-control listing, a multi-word spelling no
        roster word derives), reaches the assertion the same day."""
        import re
        bp = prd._bash_patterns
        canon = {
            w.lower() for w in re.findall(r"[\w-]+", bp._PS_REMOVE_VERB + bp._PS_ENUMERATE_VERB)
        } | {"find"} | {
            w.lower() for w in re.findall(r"[\w-]+", " ".join(bp._PIPED_ENUM_HEAD_KEYS))
        }
        assert prd._PS_DELETE_VERBS == canon
        multiword = [k for k in bp._PIPED_ENUM_HEAD_KEYS if " " in k]
        for verb in canon - {w for k in multiword for w in k.split()}:
            assert re.search(prd._HEADS, verb + " x", re.IGNORECASE), verb
        for key in multiword:
            assert re.search(prd._HEADS, key + " x", re.IGNORECASE), key
            assert re.search(prd._HEADS, key.split()[0] + " -C . " + key.split(None, 1)[1] + " x",
                             re.IGNORECASE), key

    @pytest.mark.parametrize("command", [
        "git ls-files ~ | xargs rm -rf ; echo ./victim",
        "git -C / ls-files | xargs rm -rf ; echo ./victim",
        "git ls-files / | Remove-Item ; echo ./victim",
    ], ids=["listing-home-pathspec", "listing-root-global-option", "listing-root-into-cmdlet"])
    def test_refuses_a_catastrophic_root_under_the_listing_head(self, prd, tmp_path, command):
        """The version-control listing (DEF-831) is a sweep head whose roots
        a piped remove deletes under; a catastrophic pathspec or a
        catastrophic explicit-repo value must reach the assertion as the
        cmdlet enumerators' roots do (git refuses a pathspec outside the
        repository, but the belt does not lean on that)."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match="operand"):
            prd.assert_safe_to_execute(command, victim, tmp_path)

    def test_the_child_env_carries_the_git_belt(self, prd, tmp_path, monkeypatch):
        """The listing rows (DEF-831) are the first on this gate to run git
        inside the sandbox, so the child env wears the Bash differential's
        belt: every inherited GIT_* variable dropped (a hook's GIT_DIR would
        route the row's staging into the operator's index), a ceiling above
        the sandbox, global and system config off, no terminal prompt."""
        monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere"))
        monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path))
        env = prd._child_env("pwsh", tmp_path / "sandbox")
        assert not any(k.startswith("GIT_") and k not in (
            "GIT_CEILING_DIRECTORIES", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM",
            "GIT_TERMINAL_PROMPT") for k in env)
        assert env["GIT_CEILING_DIRECTORIES"] == str((tmp_path / "sandbox").resolve().parent)
        assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_TERMINAL_PROMPT"] == "0"
        assert env["GIT_CONFIG_GLOBAL"] == prd.os.devnull
        assert "GIT_DIR" not in prd._child_env("pwsh")

    def test_a_command_it_cannot_lex_is_refused_not_waved_through(self, prd,
                                                                  tmp_path):
        """The conservative default: unreadable is not the same as harmless."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match="cannot lex"):
            prd.assert_safe_to_execute(
                "Remove-Item -Recurse -Force ./victim 'unclosed", victim, tmp_path)


class TestThePopulationIsDerived:
    def test_the_population_is_non_empty_and_multi_source(self, prd):
        """A generator that regressed to nothing would score a perfect zero."""
        assert len(prd.inert_rows()) > 0
        assert len(prd.opener_context_rows()) > 0
        assert len(prd.execution_rows(nested="pwsh")) > 0

    def test_the_population_counts_the_cost_comment_cites(self, prd):
        """The cost comment on the end-to-end gate states the arithmetic of the
        population; these are the numbers it cites, so an axis added without
        updating that comment reds here instead of drifting silently (review)."""
        assert len(prd.inert_rows()) == 62
        assert len(prd.opener_context_rows()) == 84
        assert len(prd.reparsed_inert_rows()) == 2
        # 78 -> 87 on 2026-09-13: three scriptblock-Create wrappers (DEF-760)
        # joined the execution axis, times the three targets.
        assert len(prd.execution_rows(nested="pwsh")) == 87
        # DEF-791 (2026-09-13): the call operator with a quoted command name
        # is its own axis -- five wrappers by the three targets, plus two
        # inert containers holding the same text as data.
        assert len(prd.call_operator_rows()) == 15
        assert len(prd.call_operator_inert_rows()) == 2

    def test_the_nested_interpreter_row_spells_the_running_head(self, prd):
        """The nested wrapper resolves whichever build is driving the run."""
        rows = [r for r in prd.execution_rows(nested="powershell")
                if r["wrapper"] == "reparsed-expandable-nested-interpreter"]
        assert rows and all(r["template"].startswith("powershell ") for r in rows)


class TestEachRunOwnsItsInterpreterCache:
    """Two concurrent runs corrupted pwsh's shared startup cache on 2026-09-10
    and the second half of both populations read as inert. The fix is
    isolation, not a warning: every spawn in a run gets a private cache
    directory, so there is no file to share (memory: one writer per shared
    state)."""

    def test_a_run_points_the_interpreter_cache_at_its_own_directory(self, prd, monkeypatch, tmp_path):
        import os
        monkeypatch.setattr(prd, "_RUN_CACHE_DIR", str(tmp_path))
        env = prd._child_env(str(tmp_path / "bin" / "pwsh"))
        assert env["PATH"].split(os.pathsep)[0] == str(tmp_path / "bin")
        if os.name == "nt":
            assert env.get("XDG_CACHE_HOME") == os.environ.get("XDG_CACHE_HOME")
        else:
            assert env["XDG_CACHE_HOME"] == str(tmp_path)

    def test_a_direct_call_outside_a_run_keeps_the_users_cache(self, prd):
        import os
        assert prd._RUN_CACHE_DIR is None
        env = prd._child_env("/nowhere/pwsh")
        assert env.get("XDG_CACHE_HOME") == os.environ.get("XDG_CACHE_HOME")


class TestTheGateRunsEndToEnd:
    # COST + CEILING. The numbers below are MEASURED on the dev host, not
    # estimated -- an earlier draft of this comment estimated them and was wrong
    # in the direction that flatters the fix, so they were driven instead.
    #
    # `main([])` takes no `--quick`, so it drives the whole derived population:
    # 62 inert + 84 opener-context + 2 re-parsed inert + 2 call-operator inert
    # + 87 execution + 15 call-operator execution = 252 rows (226 until the
    # DEF-760 and DEF-791 axes of 2026-09-13; 57 execution rows until DEF-753
    # added the re-parsing wrapper axis,
    # seven wrappers by three targets; the counts are pinned by
    # `TestThePopulationIsDerived`). Each row spawns a real `pwsh` for the
    # reachability oracle and drives the hook twice for the guard tier. Driven
    # end to end here: 58.66s wall (independently 59.31s) at 203 rows, 203/203
    # agreeing, against a 60s global ceiling; 80.1s at 224 rows on 2026-09-10,
    # 224/224 agreeing, run ALONE -- two instances at once corrupt pwsh's
    # startup cache, and the script's own docstring says so.
    #
    # So it is NOT hopeless-by-an-order-of-magnitude; it is a HAIR under the
    # ceiling on a fast laptop, which is worse. It sits close enough to 60s that
    # pytest's own import and fixture overhead pushes it over, and a 2-core CI
    # runner has no chance -- which is exactly what happened on 2026-09-01, its
    # first execution after landing 2026-08-25 inside the Actions blackout.
    # 900s is headroom against that runner, not against this one.
    #
    # Why no local run ever said so: `pwsh` IS on this machine, but off PATH, so
    # `find_powershell()` returns None and the skipif below fires. Export
    # ESPALIER_PWSH to drive it locally -- the gate was one env var from being
    # runnable here the whole time.
    #
    # A `slow` marker is NOT what was missing, and adding one would be
    # decorative: this module is already in `conftest._SLOW_FILES`, whose own
    # entry notes the `pwsh` spawn. That membership satisfies the suite contract
    # (test_every_self_declared_slow_site_is_slow_or_exempt) and already keeps
    # the test out of the `-m "not slow"` pull-request slice. It did not save the
    # push run, because push-to-main runs `pytest -q` in FULL -- only
    # pull_request narrows to the fast slice. So the ceiling is the whole fix.
    @pytest.mark.timeout(900)
    @pytest.mark.skipif(
        _load().find_powershell() is None,
        reason="no `pwsh` on this host; set ESPALIER_PWSH to an unpacked build",
    )
    def test_the_gate_completes_against_head(self, prd):
        assert prd.main([]) in (0, 1, 2)
