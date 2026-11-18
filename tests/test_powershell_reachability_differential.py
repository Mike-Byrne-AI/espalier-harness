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
import re
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


#: What condition (10)'s allowlist says when it refuses a row (`_allowlisted`
#: in `bench/real_shell_confinement.py`), one reason per rule.
_ALLOWLIST_REFUSAL = ("a non-ASCII character|no row of the PowerShell population holds"
                      "|an escape|a move this set does not admit")


def _holding(prd, *texts):
    """The leg's profile with its allowlist also holding `texts`' characters
    and words, so a test reaches the rule or the condition behind it."""
    import dataclasses

    held = prd.POWERSHELL.allowlist
    extra = prd.derive_allowlist(set(texts))
    return dataclasses.replace(prd.POWERSHELL, allowlist=dataclasses.replace(
        held, alphabet=held.alphabet | frozenset(extra["alphabet"]),
        words=held.words | frozenset(extra["words"])))


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

    def test_the_victims_name_inside_another_word_is_no_declared_operand(self, prd, tmp_path):
        """A declared spelling must open a word: `victim` inside
        `./not-the-victim` is prose to this check, never the sandbox's
        operand, or any row that mentions the name would pass condition (2)."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match="declared sandbox operand"):
            prd.assert_safe_to_execute(
                "Remove-Item -Recurse -Force ./not-the-victim", victim, tmp_path)

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

        Every whole-string condition anchors on the delete verb plus its FIRST
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
        for kept in ("gci ./victim -Recurse -Include * | ri -r -fo",
                     "gci ./victim -Recurse -Include:* | ri -r -fo"):
            prd._confinement.assert_confined(kept, victim, tmp_path, _holding(prd, kept))
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
            w.lower() for w in re.findall(r"[\w-]+", bp._PS_REMOVE_VERB_WORDS + bp._PS_ENUMERATE_VERB)
        } | {"find"} | {
            w.lower() for w in re.findall(r"[\w-]+", " ".join(bp._PIPED_ENUM_HEAD_KEYS))
        }
        assert prd._PS_DELETE_VERBS == canon
        multiword = [k for k in bp._PIPED_ENUM_HEAD_KEYS if " " in k]
        for verb in canon - {w for k in multiword for w in k.split()}:
            assert re.search(prd._HEADS, verb + " x", re.IGNORECASE), verb
        # DEF-1123: the native rm by file name or path is a head no word list
        # holds; the guard's verb matcher, composed into the heads, reads it,
        # and the operand reader asks the same matcher (its POSIX lexer drops a
        # backslash, so the backslash spelling is the heads' alone)
        for spelling in ("rm.exe", "RM.EXE", "/bin/rm", "C:\\Git\\usr\\bin\\rm.exe"):
            assert re.search(prd._HEADS, spelling + " x", re.IGNORECASE), spelling
        for spelling in ("rm.exe", "RM.EXE", "/bin/rm", "C:/Git/usr/bin/rm.exe"):
            assert prd._delete_operands(spelling + " -rf ./victim ~") == ["./victim", "~"], spelling
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

    def test_refuses_a_victim_outside_the_sandbox(self, prd, tmp_path):
        """Condition (3) on this leg: a victim built outside the throwaway
        directory is refused whatever the command says."""
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        outside = tmp_path / "victim"
        outside.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match="outside sandbox"):
            prd.assert_safe_to_execute("Remove-Item -Recurse -Force ./victim", outside, sandbox)

    @pytest.mark.parametrize(("operand", "says"), [
        ("*", "catastrophic operand"),
        ("../outside", "escapes the sandbox"),
        (chr(92), "catastrophic operand"),
        (chr(92) + "Windows", "escapes the sandbox"),
    ], ids=["bare-glob", "parent-walk", "drive-root", "drive-root-child"])
    def test_refuses_a_delete_inside_a_quoted_subexpression(self, prd, tmp_path, operand, says):
        """PowerShell runs a `$(...)` inside a double-quoted string, and the
        operand reader lexes that string as ONE word, so it reads no operand
        there: the whole-string scans are what see this delete. Each spelling
        is refused by one of them alone (a glob is no escaping form, a parent
        walk no catastrophic one), so each scan has a red of its own."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match=says):
            prd.assert_safe_to_execute(
                f'Write-Output "$(Remove-Item -Recurse -Force {operand} )" ./victim', victim, tmp_path)

    @pytest.mark.parametrize(("trailing", "says"), [
        ("*", "catastrophic delete operand"),
        ("{absolute}", "escaping delete operand"),
    ], ids=["bare-glob", "absolute-inside-the-sandbox"])
    def test_each_lone_operand_scan_refuses_what_the_other_does_not(
            self, prd, tmp_path, trailing, says):
        """The re-ask of each operand alone, one red per scan: a bare glob
        behind the declared operand is catastrophic and not escaping; an
        absolute spelling is escaping and not catastrophic, and is refused even
        where it lands inside the sandbox, since the rows are relative by
        design and an absolute operand is none the population declared."""
        victim = tmp_path / "victim"
        victim.mkdir()
        # quoted: a spaced basetemp (the perturbed CI leg) would split it in two
        trailing = trailing.format(absolute=f"'{victim.as_posix()}'")
        with pytest.raises(prd.UnsafeToExecute, match=says):
            prd.assert_safe_to_execute(
                f"Remove-Item -Recurse -Force ./victim {trailing}", victim, tmp_path)

    @pytest.mark.parametrize("trailing", ["$HOME", "$env:USERPROFILE", "${env:USERPROFILE}"],
                             ids=["home", "env-drive", "braced-env-drive"])
    def test_refuses_a_variable_behind_the_declared_operand(self, prd, tmp_path, trailing):
        """The Bash leg's binding condition, this leg's too since the two
        share one condition set (DEF-5085). The interpreter fills a variable
        in after this assertion has read the text, and nothing binds one for
        a PowerShell row, so every name but `$null` is refused. Before the
        merge this leg ACCEPTED all three -- neither pattern scan reads a
        `$` -- and `$HOME` is the home directory: the 2026-09-17 incident's
        shape on the other shell."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match="unbound parameter expansion"):
            prd.assert_safe_to_execute(
                f"Remove-Item -Recurse -Force ./victim {trailing}", victim, tmp_path)

    def test_refuses_a_parent_walk_that_starts_inside_the_sandbox(self, prd, tmp_path):
        """The Bash leg's resolution condition, this leg's too (DEF-5085):
        the escaping scan reads a LEADING `../` only, so a walk out that
        starts with the victim's own name was ACCEPTED; resolving each
        operand against the sandbox reads where it lands."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match="resolves outside sandbox"):
            prd.assert_safe_to_execute(
                "Remove-Item -Recurse -Force ./victim victim/../../outside", victim, tmp_path)

    # Condition (10), DEF-2099: each spelling of a move PowerShell 5.1 was
    # driven through, echo-only, on 2026-11-17, every one moving where a bare
    # name resolved; the move goes out of the sandbox, or to a place the set
    # does not read. This leg's rows spell the victim relative.
    @pytest.mark.parametrize("move", [
        "Set-Location {out};", "cd {out};", "sl {out};", "chdir {out};", "Push-Location {out};",
        "pushd {out};", "CD {out};", "Set-Location -Path {out};",
        "Microsoft.PowerShell.Management{bs}Set-Location {out};", "Pop-Location;", "popd;",
        "cd..;", "cd{bs};", "Set-Location;", "Set-Location ~;", "Set-Location (Get-Location);",
        "Set-Location {out}/p*;", "cd sub{bs}..;",
        "Set-Location > $null {out};", "cd>$null {out};", "Set-Location <# x #> ~\n",
        "Set-Location # x\n", "Set-Location sub(x);", "Set-Location -Path:{out};",
        "Set-Location -Pa {out};", ". ./moves.ps1;",
        "Set-Location ./victim\nSet-Location ../..\n",
    ], ids=["Set-Location", "cd", "sl", "chdir", "Push-Location", "pushd", "upper-case",
            "path-parameter", "module-qualified", "Pop-Location", "popd", "parent-function",
            "root-function", "bare", "home", "argument-expression", "wildcard",
            "climbing-destination", "redirect-before-destination", "redirect-glued-to-head",
            "block-comment-before-destination", "comment-after-bare", "glued-opener",
            "colon-bound-path", "abbreviated-parameter", "dot-sourced-script",
            "earlier-lines"])
    def test_refuses_a_relative_operand_where_the_row_moves_away(self, prd, tmp_path, move):
        """Condition (7) resolves a relative operand against the sandbox,
        where the drive starts a row, and the provider resolves it where the
        row moved to: ACCEPTED before (10) (DEF-2099; the Bash leg's probe).
        The second block was accepted by (10)'s first reading of a move (both
        reviews): a redirect or a comment where the destination would be, a
        word glued to an opener, a script whose landing the text does not
        hold. Each is refused by the allowlist that replaced that reading,
        which admits one move and reads no other (the dispatcher's ruling on
        DEF-2099)."""
        victim = tmp_path / "victim"
        victim.mkdir()
        rendered = move.format(out=tmp_path.parent.as_posix(), bs=chr(92))
        with pytest.raises(prd.UnsafeToExecute, match=_ALLOWLIST_REFUSAL):
            prd.assert_safe_to_execute(f"{rendered} {prd._RI} ./victim", victim, tmp_path)

    @pytest.mark.parametrize("move", [
        "Set-Location ./victim;", "Set-Location .{bs}victim;", "Set-Location victim;",
    ], ids=["dot-spelling", "backslash-spelling", "bare-spelling"])
    def test_keeps_a_relative_operand_after_the_admitted_move(self, prd, tmp_path, move):
        """The sweep rows move into the target before their delete: the one
        move the allowlist admits is Set-Location to a declared spelling,
        ending its statement, which descends, so it costs no row (0 of this
        leg's 1568 on either platform, in memory, 2026-11-18)."""
        victim = tmp_path / "victim"
        victim.mkdir()
        rendered = move.format(bs=chr(92))
        prd.assert_safe_to_execute(f"{rendered} {prd._RI} ./victim", victim, tmp_path)

    @pytest.mark.parametrize("move", [
        "Set-Location {sb}/sub;", "cd sub;", "Push-Location .{bs}sub;",
        "Set-Location -LiteralPath sub;", "Set-Location -PassThru sub;", "Set-Location ./victim",
        "set-location ./victim;", "Set-Location ./victim |", "Set-Location sub;",
    ], ids=["absolute", "relative", "backslash", "literal-path", "switch", "no-statement-end",
            "lower-case", "piped", "an-undeclared-name"])
    def test_refuses_a_move_inside_the_sandbox_the_allowlist_does_not_admit(
            self, prd, tmp_path, move):
        """Each stays inside the sandbox, and the hand list of moves this
        replaced read each so and kept it; the allowlist admits one move and
        reads no other, so each refuses, at the cost of no population row.
        Held to the profile's words as well, so the admitted-move rule, not
        the word rule, is what refuses."""
        victim = tmp_path / "victim"
        victim.mkdir()
        cmd = f"{move.format(sb=tmp_path.as_posix(), bs=chr(92))} {prd._RI} ./victim"
        with pytest.raises(prd.UnsafeToExecute, match=_ALLOWLIST_REFUSAL):
            prd.assert_safe_to_execute(cmd, victim, tmp_path)
        if "et-location" in move.lower():
            with pytest.raises(prd.UnsafeToExecute, match="a move this set does not admit"):
                prd._confinement.assert_confined(cmd, victim, tmp_path, _holding(prd, cmd))

    @pytest.mark.parametrize("cmd", [
        "Set-Location ./victim; Set-Location ../..; Get-ChildItem | {ri} -Recurse",
        "Set-Location ./victim/../..; git ls-files | {ri}",
    ], ids=["listing-after-a-climb", "version-control-listing-after-a-climb"])
    def test_refuses_a_delete_fed_from_a_listing_where_the_row_moved_out(self, prd, tmp_path, cmd):
        """A delete or enumerator head that names no operand reads where the
        row stands, so it is judged as `.`: before, a carrier that climbed out
        first was judged by nothing (DEF-2099's failure-mode review). The
        climb is a move the allowlist does not admit."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match=_ALLOWLIST_REFUSAL):
            prd.assert_safe_to_execute(cmd.format(ri=prd._RI), victim, tmp_path)

    @pytest.mark.parametrize("cmd", [
        "Set-Location ./victim; git init -q; git add -A; git ls-files | {ri}",
        "Set-Location ./victim; Get-ChildItem | {ri} -Recurse",
    ], ids=["version-control-carrier", "listing-carrier"])
    def test_keeps_a_delete_fed_from_a_listing_inside_the_target(self, prd, tmp_path, cmd):
        """The calibration twins: the sweep rows move into the target and
        delete what it lists."""
        victim = tmp_path / "victim"
        victim.mkdir()
        prd.assert_safe_to_execute(cmd.format(ri=prd._RI), victim, tmp_path)

    @pytest.mark.parametrize(("cmd", "held_says"), [
        ("Set-Location ./victim; {ri} ./../../{parent}/{name}/x", "climbs with `..`"),
        ("Set-Location ./victim/..; {ri} ./victim", "a move this set does not admit"),
        ("Set-Location {sb}/victim/../..; {ri} ./victim", "a move this set does not admit"),
    ], ids=["operand-climbs-back-in", "destination-climbs", "absolute-destination-climbs-out"])
    def test_refuses_a_climb_where_the_row_moves(self, prd, tmp_path, cmd, held_says):
        """With a move, which directory the row stands in depends on the
        order the moves run in and on what a subshell undoes; a step that only
        descends lands inside from any of them, and a `..` step need not. The
        first operand climbs out and back in by the sandbox's own names (led
        by `./`, since (6) refuses a leading `..`): from the sandbox it lands
        inside it, which is all (7) reads, and from the target it lands inside
        the sandbox's parent, under a folder named after that parent. The
        allowlist refuses each (a word no row holds, or a move it does not
        admit); held to the profile's words, the climbing destinations are
        still moves it does not admit, and the climbing operand behind the
        admitted move is (10)'s own `..` reading, the belt for a held word
        that climbs."""
        victim = tmp_path / "victim"
        victim.mkdir()
        rendered = cmd.format(ri=prd._RI, sb=tmp_path.as_posix(),
                              parent=tmp_path.resolve().parent.name, name=tmp_path.resolve().name)
        with pytest.raises(prd.UnsafeToExecute, match=_ALLOWLIST_REFUSAL):
            prd.assert_safe_to_execute(rendered, victim, tmp_path)
        with pytest.raises(prd.UnsafeToExecute, match=held_says):
            prd._confinement.assert_confined(rendered, victim, tmp_path, _holding(prd, rendered))

    @pytest.mark.parametrize("move", [
        "Set-Location ./vic*;", "Set-Location 'vic'tim;", "Set-Location HKCU:{bs};",
        "Set-Location $d;", "Set-Location X:;", "Set-Location X:sub;", "Set-Location C:/x;",
    ], ids=["wildcard", "quoted-in-part", "mapped-drive", "unbound-variable", "drive",
            "drive-relative", "absolute-drive"])
    def test_each_destination_the_move_list_could_not_place_is_refused(self, prd, tmp_path, move):
        """Each destination the hand list of moves read and could not place,
        on a destination that would lie inside the sandbox read as a plain
        name (code review of DEF-2099), and the drive it placed by the host's
        path rules (failure-mode review: `X:` and `C:/x` are plain names on
        POSIX and drives on Windows). The allowlist reads none of them and no
        host's rules: each is a move it does not admit, on every host, held
        to the profile's words or not."""
        victim = tmp_path / "victim"
        victim.mkdir()
        cmd = f"{move.format(bs=chr(92))} {prd._RI} ./victim"
        with pytest.raises(prd.UnsafeToExecute, match=_ALLOWLIST_REFUSAL):
            prd.assert_safe_to_execute(cmd, victim, tmp_path)
        with pytest.raises(prd.UnsafeToExecute, match="a move this set does not admit"):
            prd._confinement.assert_confined(cmd, victim, tmp_path, _holding(prd, cmd))

    @pytest.mark.parametrize("link", [
        "New-Item -ItemType SymbolicLink -Path ./victim/l -Target {out};",
        "New-Item -ItemType Junction -Path ./victim/l -Target {out};",
        "[IO.File]::CreateHardLink('./victim/l', '{out}/f');",
        "cmd /c mklink /d victim{bs}l {out};", "ln -s {out} ./victim/l;",
    ], ids=["symbolic-link", "junction", "dotnet-hard-link", "mklink", "ln"])
    def test_refuses_every_delete_in_a_row_that_makes_a_link(self, prd, tmp_path, link):
        """The link is made when the row runs, after (7) resolved the operand
        on a disk that did not hold it, so a delete through it reads as inside
        the sandbox (`makes_links`, the dispatcher's note on DEF-2099). On
        this leg an operand spelled absolute is the escaping form's already
        (5), so the relative one is driven: ACCEPTED at main before the lane,
        and read by the lane's first reading as an unplaceable move, which
        the one link reading of both legs replaces. On this leg the allowlist
        answers first (no row holds a link maker's words); held to the
        profile's words, the link reading is the belt that refuses."""
        victim = tmp_path / "victim"
        victim.mkdir()
        rendered = link.format(out=tmp_path.parent.as_posix(), bs=chr(92))
        cmd = f"{rendered} {prd._RI} ./victim/l/x"
        with pytest.raises(prd.UnsafeToExecute, match=_ALLOWLIST_REFUSAL):
            prd.assert_safe_to_execute(cmd, victim, tmp_path)
        with pytest.raises(prd.UnsafeToExecute, match="in a row that makes a link"):
            prd._confinement.assert_confined(cmd, victim, tmp_path, _holding(prd, cmd))

    def test_a_word_after_a_double_dash_is_an_operand(self, prd, tmp_path):
        """PowerShell's binder ends the parameters at `--` (driven on 5.1:
        `Write-Output -- -x` printed `-x`), so the word after it binds as a
        path; both readers skipped it as a switch (both reviews)."""
        victim = tmp_path / "victim"
        victim.mkdir()
        assert prd._delete_operands(f"{prd._RI} -- -x") == ["-x"]
        with pytest.raises(prd.UnsafeToExecute, match="resolves outside sandbox"):
            prd.assert_safe_to_execute(f"{prd._RI} ./victim -- -victim/../..", victim, tmp_path)

    def test_the_moved_reading_judges_a_head_that_names_no_operand_as_here(self, prd):
        """`_moved_operands`: the whole command's operands, and `.` for each
        delete or enumerator head that names none; `_delete_operands` reads
        those heads as naming nothing."""
        assert prd._moved_operands(f"Get-ChildItem | {prd._RI} -Recurse") == [".", "."]
        assert prd._moved_operands(f"{prd._RI} ./victim") == ["./victim"]
        assert prd._delete_operands(f"Get-ChildItem | {prd._RI} -Recurse") == []

    @pytest.mark.parametrize("trailing", ["$(Resolve-Path ~)", '"$(Get-Location)/.."'],
                             ids=["subexpression", "quoted-subexpression"])
    def test_refuses_a_subexpression_behind_the_declared_operand(self, prd, tmp_path, trailing):
        """Condition (9) on this leg (DEF-5085): a `$(...)` operand is a value
        the interpreter computes after this assertion reads the text, so the
        row is classifier-only. Both spellings were ACCEPTED before (9): the
        operand reader stops at the `(` and keeps the bare `$`, or keeps the
        quoted span as one relative word, and neither pattern scan reads a
        `$`."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match="a substitution"):
            prd.assert_safe_to_execute(
                f"Remove-Item -Recurse -Force ./victim {trailing}", victim, tmp_path)

    @pytest.mark.parametrize("trailing", ["..{bs}outside", "victim{bs}..{bs}..{bs}outside",
                                          "{bs}Windows"],
                             ids=["parent-walk", "inner-walk", "drive-root-child"])
    def test_refuses_a_backslash_walk_behind_the_declared_operand(self, prd, tmp_path, trailing):
        """DEF-2100: the reader lexed with the POSIX escape, the backslash, and
        dropped it, so each of these was the name of a file inside the
        sandbox (`..outside`) and was ACCEPTED. PowerShell's escape is the
        backtick and its provider reads a backslash as a separator on every
        host (driven on PowerShell 5.1: the first resolved to the working
        directory's sibling, the second to its parent)."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match="resolves outside sandbox"):
            prd.assert_safe_to_execute(
                f"Remove-Item -Recurse -Force ./victim {trailing.format(bs=chr(92))}",
                victim, tmp_path)

    def test_the_set_reads_a_profiles_separators_before_it_resolves(self, prd, tmp_path):
        """The mechanism under the walk test above, on any host: a Windows
        host's path reads a backslash as a separator whatever the profile
        says, so that test reds only on the POSIX legs if the set stops
        reading `separators`. A separator no host reads (`%`) reds here."""
        import dataclasses

        victim = tmp_path / "victim"
        victim.mkdir()
        shell = dataclasses.replace(prd.POWERSHELL, separators="/%")
        with pytest.raises(prd.UnsafeToExecute, match="resolves outside sandbox"):
            prd._confinement.assert_confined(
                "Remove-Item -Recurse -Force ./victim ..%outside", victim, tmp_path, shell)

    def test_the_profile_declares_the_backslash_a_separator(self, prd):
        """PowerShell's provider reads `..\\outside` as a parent walk on every
        host (driven on PowerShell 5.1: it resolved to the working
        directory's sibling). Only the POSIX legs could red on the behavior,
        so the declaration is pinned where every host reads it."""
        assert chr(92) in prd.POWERSHELL.separators

    @pytest.mark.parametrize("trailing", [
        "(Resolve-Path ~)", "((Get-Location))", "@('/')", "@p", "{ $_.FullName + '/..' }",
    ], ids=["argument-expression", "nested-argument-expression", "array-subexpression",
            "splat", "delay-bind-scriptblock"])
    def test_refuses_an_argument_the_interpreter_computes(self, prd, tmp_path, trailing):
        """DEF-2100: the operand list ended at a `(` or `{`, so the argument
        behind it was never read and the row was ACCEPTED, and a splat or an
        array (`@`) was a harmless name. Each is a value PowerShell computes
        after this assertion reads the text (driven on PowerShell 5.1: the
        home directory, or the working directory's parent), so the reader
        hands the opener over and condition (9) refuses it."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match="a substitution"):
            prd.assert_safe_to_execute(
                f"Remove-Item -Recurse -Force ./victim {trailing}", victim, tmp_path)

    @pytest.mark.parametrize("trailing", [
        "HKCU:{bs}Software{bs}x", "Env:{bs}X", "Temp:/x", "FileSystem::/",
    ], ids=["registry-drive", "environment-drive", "temp-drive", "provider-qualified"])
    def test_refuses_a_drive_the_provider_maps(self, prd, tmp_path, trailing):
        """DEF-2100: a drive name longer than one letter, or a provider-
        qualified path, lands wherever the interpreter's drive table maps it
        (`HKCU:` is the registry), which no path this assertion resolves can
        say; each read as a relative name inside the sandbox and was
        ACCEPTED."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match="an expansion \\(mapped-drive"):
            prd.assert_safe_to_execute(
                f"Remove-Item -Recurse -Force ./victim {trailing.format(bs=chr(92))}",
                victim, tmp_path)

    @pytest.mark.parametrize(("command", "says"), [
        ("Remove-Item -Recurse -Force ./victim HK`CU:{bs}x", "mapped-drive"),
        ('Remove-Item -Recurse -Force ./victim "`/"', "a substitution"),
        ('Remove-Item -Recurse -Force ./victim "`~"', "a substitution"),
        ('Remove-Item -Recurse -Force ./victim "`.`.{bs}outside"', "a substitution"),
        ("Remove-Item`\n-Recurse -Force ./victim /", "resolves outside sandbox"),
        ("Remove-Item -Recurse -Force ./victim `\nHKCU:{bs}Software{bs}x", "mapped-drive"),
    ], ids=["escaped-drive-name", "quoted-escaped-root", "quoted-escaped-home",
            "quoted-escaped-walk", "continued-verb", "continued-operand"])
    def test_reads_the_backtick_as_powershell_does(self, prd, tmp_path, command, says):
        """DEF-2100's review: the backtick is PowerShell's escape. Outside
        quotes the lexer consumes it (`HK`CU:` is `HKCU:`); inside a double-
        quoted span one is left in the word, and PowerShell yields the
        character after it (`"`/"` is the root); before a line break it is a
        line continuation, which the lexer would glue into the word. Each was
        ACCEPTED as a name inside the sandbox."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match=says):
            prd.assert_safe_to_execute(command.format(bs=chr(92)), victim, tmp_path)

    def test_finds_quoted_placeholder_is_no_scriptblock(self, prd, tmp_path):
        """The calibration twin of the `{` mark: the sweep rows hand find
        `'{}'`, which the lexer strips to `{}`; that whole word, or an empty
        scriptblock, binds no path, so the row is accepted (both reviews: the
        mark refused eight POSIX rows per nested head before this)."""
        victim = tmp_path / "victim"
        victim.mkdir()
        prd.assert_safe_to_execute("find ./victim -exec rm -rf '{}' +", victim, tmp_path)

    def test_a_backslash_that_stays_inside_the_sandbox_is_still_accepted(self, prd, tmp_path):
        """The calibration twin: the declared `.\\victim` spelling and a
        backslash path under the victim resolve inside the sandbox once the
        backslash is read as a separator."""
        victim = tmp_path / "victim"
        victim.mkdir()
        bs = chr(92)
        prd.assert_safe_to_execute(f"Remove-Item -Recurse -Force .{bs}victim", victim, tmp_path)
        deeper = f"Remove-Item -Recurse -Force ./victim victim{bs}x"
        prd._confinement.assert_confined(deeper, victim, tmp_path, _holding(prd, deeper))

    def test_the_interpreters_own_null_is_no_unbound_variable(self, prd, tmp_path):
        """The calibration twin of the binding condition: the operand reader
        over-collects, so the or-chained rows' `2>$null` hands it the
        redirect's target as an operand. `$null` binds no path, so the row is
        accepted (three execution rows read that way)."""
        victim = tmp_path / "victim"
        victim.mkdir()
        prd.assert_safe_to_execute(
            "Get-Item ./nonexistent-xyz 2>$null || Remove-Item -Recurse -Force ./victim",
            victim, tmp_path)

    @pytest.mark.parametrize("trailing", ["$null/..", "$null/Windows", "${null}/Windows"],
                             ids=["parent-walk", "root-child", "braced-root-child"])
    def test_the_interpreters_null_is_exempt_only_as_the_whole_operand(self, prd, tmp_path, trailing):
        """`$null/Windows` expands to `/Windows`: the exemption is for the
        redirect target the reader over-collects, the whole operand `$null`,
        never a name the rest of the operand builds a path on (code review,
        driven: all three were accepted when the exemption read the name)."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match="unbound parameter expansion"):
            prd.assert_safe_to_execute(
                f"Remove-Item -Recurse -Force ./victim {trailing}", victim, tmp_path)

    def test_both_legs_raise_one_class_from_one_condition_set(self, prd):
        """The Bash leg loads the set by path and this leg imports it by its
        bare name; both must hold the same module, or a caller catching one
        leg's refusal would miss the other's."""
        spec = importlib.util.spec_from_file_location(
            "_rd_for_the_ps_tests", REPO_ROOT / "bench" / "reachability_differential.py")
        rd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rd)
        assert rd._confinement is prd._confinement
        assert rd.UnsafeToExecute is prd.UnsafeToExecute

    def test_a_refused_row_is_no_verdict_never_a_fail_open(self, prd, monkeypatch, capsys):
        """A row the set refuses stops the run before an interpreter sees it:
        exit 3, the instrument's code, never FAIL-OPEN's 1 (failure-mode
        review: the refusal escaped `main` and read as a fail-open)."""
        monkeypatch.setattr(prd, "find_powershell", lambda: ("pwsh", "pwsh"))
        monkeypatch.setattr(prd, "assert_instrument_is_live", lambda pwsh: None)

        def refused(pwsh, quick=False):
            raise prd.UnsafeToExecute("driven: a refused row")

        monkeypatch.setattr(prd, "run", refused)
        assert prd.main([]) == 3
        assert "a row the confinement set refuses" in capsys.readouterr().err

    @pytest.mark.parametrize("platform", ["nt", "posix"])
    @pytest.mark.parametrize("nested", ["pwsh", "powershell"])
    def test_every_row_of_the_population_passes_the_condition_set(
            self, prd, tmp_path, nested, platform, monkeypatch):
        """The census as a pin: every row `run` hands an interpreter, rendered
        as `_run_pwsh` renders it, passes the assertion in memory. A condition
        that would refuse a calibrated row reds here, on any host, before a
        run with an interpreter finds it as a crash. The sweep rows differ by
        platform, so each platform's population is built on every host (both
        DEF-2100 reviews: find's `'{}'` rows exist on POSIX alone, and a Windows
        run of this pin never built them)."""
        monkeypatch.setattr(prd, "_PLATFORM", platform)
        victim = tmp_path / "victim"
        rows = (prd.inert_rows() + prd.opener_context_rows() + prd.reparsed_inert_rows()
                + prd.call_operator_inert_rows() + prd.execution_rows(nested=nested)
                + prd.call_operator_rows() + prd.sweep_rows(nested=nested))
        assert rows
        for row in rows:
            prd.assert_safe_to_execute(
                row["template"].replace(prd._TARGET, "./victim"), victim, tmp_path)


#: PowerShell's location cmdlets and their aliases, lowercased (driven
#: 2026-11-17, echo-only, on 5.1, for the hand list of moves the allowlist
#: replaced).
_LOCATION_WORDS = frozenset({"set-location", "sl", "cd", "chdir", "push-location", "pushd",
                             "pop-location", "popd", "cd..", "cd\\"})


class TestTheAllowlistHoldsEveryRow:
    """Condition (10) on this leg is an allowlist held as data (the
    dispatcher's ruling on DEF-2099): every row's characters, escapes, words
    and moves are ones the population holds."""

    def test_the_held_allowlist_is_the_populations_own(self, prd):
        """Held as data, pinned to the population both ways: a row that
        needs a new character or word reds here before a run refuses it, and
        a held one no row needs any longer reds too, so the list never widens
        in silence. Some inert rows take characters from the guard's own
        regex (`PRECEDING_CHARS`), so a guard change can red this."""
        derived = prd.derive_allowlist(prd.population_texts())
        held = json.loads(prd.ALLOWLIST_PATH.read_text(encoding="utf-8"))
        extra = sorted(set(derived["words"]) ^ set(held["words"]))
        assert derived == held, (
            f"the held allowlist is not the population's ({len(extra)} words and "
            f"{len(set(derived['alphabet']) ^ set(held['alphabet']))} characters differ): "
            f"run `{prd.POWERSHELL.allowlist.regenerate}` and read its diff")

    def test_the_held_words_move_the_directory_only_by_the_admitted_move(self, prd):
        """A held location cmdlet or alias other than the admitted move would
        be a move the allowlist reads as a plain word: the belt for a
        regeneration whose diff nobody read."""
        allowlist = prd.POWERSHELL.allowlist
        movers = sorted(word for word in allowlist.words if word != allowlist.move and (
            word.lower() in _LOCATION_WORDS or word.lower().endswith("-location")))
        assert movers == []

    @pytest.mark.parametrize("row", [0, 1], ids=["bare-delete", "quoted-mention"])
    def test_the_calibration_rows_pass_the_condition_set(self, prd, tmp_path, row):
        """`assert_instrument_is_live` drives these through the set before
        any row, so they are in the population the allowlist is derived
        from (today their characters and words are the rows' own as well, so
        only the membership pins that they are read)."""
        victim = tmp_path / "victim"
        victim.mkdir()
        rendered = prd.CALIBRATION_ROWS[row].replace(prd._TARGET, "./victim")
        assert rendered in prd.population_texts()
        prd.assert_safe_to_execute(rendered, victim, tmp_path)

    @pytest.mark.parametrize(("operand", "code"), [
        (chr(0x2019) + "/" + chr(0x2019), "U+2019"), (chr(0x2013) + "LiteralPath:/", "U+2013"),
    ], ids=["typographic-quotes-around-a-root", "en-dash-parameter-before-a-root"])
    def test_refuses_a_root_behind_a_character_outside_ascii(self, prd, tmp_path, operand, code):
        """PowerShell reads a typographic quote as a quote and an en-dash as a
        parameter prefix, and every other condition reads either as a name
        character, so a root behind one passed all nine at main (the
        dispatcher's verifier, in memory); no row holds a non-ASCII
        character, so the allowlist refuses any, in every row."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match=re.escape(f"a non-ASCII character ({code})")):
            prd.assert_safe_to_execute(f"{prd._RI} ./victim {operand}", victim, tmp_path)

    @pytest.mark.parametrize(("cmd", "says"), [
        ("{ri} ./victim%", r"characters \['%'\] no row"),
        ("Write-Output a`t; {ri} ./victim", "an escape '`t'"),
        ("Write-Output nota; {ri} ./victim", r"words \['nota'\] no row"),
    ], ids=["a-character-no-row-holds", "an-escape-other-than-the-newline", "a-word-no-row-holds"])
    def test_each_rule_refuses_by_its_own_reason(self, prd, tmp_path, cmd, says):
        """Each rule on a row that differs from a held one by the one thing
        it reads; the admitted-move rule is the move tests' above."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(prd.UnsafeToExecute, match=says):
            prd.assert_safe_to_execute(cmd.format(ri=prd._RI), victim, tmp_path)

    @pytest.mark.parametrize(("change", "says"), [
        ({"alphabet": frozenset("abc" + chr(0xE9))}, "non-ASCII"),
        ({"words": frozenset({"Set-Location", "%x"})}, "outside its alphabet"),
        ({"move": "Push-Location"}, "not among the allowlist's words"),
        ({"destinations": ("/victim",)}, "does not descend"),
        ({"destinations": ("C:/victim",)}, "does not descend"),
        ({"destinations": ("~/victim",)}, "does not descend"),
        ({"destinations": ("../victim",)}, "does not descend"),
        ({"destinations": ("./victim/../..",)}, "does not descend"),
        ({"destinations": (".",)}, "does not descend"),
    ], ids=["non-ascii-alphabet", "word-outside-the-alphabet", "move-not-held", "absolute",
            "drive", "home", "climbing", "climbing-after-a-descent", "where-it-stands"])
    def test_an_allowlist_that_cannot_hold_refuses_to_be_built(self, prd, change, says):
        """The profile's allowlist is checked as it is built: an alphabet
        that admits what the rule refuses, a move it cannot hold, or a
        destination that does not descend would each make a rule vouch for
        what it reads as unsafe."""
        import dataclasses

        with pytest.raises(ValueError, match=says):
            dataclasses.replace(prd.POWERSHELL.allowlist, **change)


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
    # 499 s serial on ubuntu-latest (2026-09-25); under `-n auto` there it
    # overran this ceiling and the thread timeout method exited the xdist
    # worker in all five cells. scripts/proof_tier.py now pins the file to the
    # serial leg (TIMEOUT_NEAR_SERIAL_FILES), where it runs alone at its serial
    # duration; the ceiling stands as measured.
    @pytest.mark.timeout(900)
    @pytest.mark.skipif(
        _load().find_powershell() is None,
        reason="no `pwsh` on this host; set ESPALIER_PWSH to an unpacked build",
    )
    def test_the_gate_completes_against_head(self, prd):
        assert prd.main([]) in (0, 1, 2)
