"""Gate for the gate: `bench/reachability_differential.py`'s own safety.

That script hands genuine recursive deletes to a real `/bin/bash`. Its confinement
is therefore not a nicety — it is the only thing standing between a mis-substituted
template and the operator's filesystem. This file drives every refusal path.

It also pins the two instrument failures that made the original incident so hard to
see, because both produced a REASSURING result rather than an error:

* :class:`TestTheOracleIsLive` — a baseline that denies nothing scores zero
  fail-opens on every row. The first probe written during that incident archived
  `tools/cc/hooks` without its sibling `tools/cc/_paths.py`, so the baseline guard
  died on import and reported 0/12 fail-opens while 63 were live.
* :class:`TestDenialIsReadFromTheDecisionChannel` — `deny()` writes JSON to stdout
  and returns 0, so a return-code check reports every deny as an allow.

⚠ If you are tempted to simplify a refusal into a comment, read
:func:`assert_safe_to_execute`'s docstring first: the four conditions are
deliberately redundant.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "bench" / "reachability_differential.py"

# The same artifact-keyed stand-down `_NEEDS_REAL_BASH` (below) applies, spelled
# once here so the confinement class above it can use it before the definition.
_NEEDS_REAL_BASH_DEFERRED = pytest.mark.skipif(
    not Path("/bin/bash").exists(),
    reason="the oracle's ground truth is a real /bin/bash, not any shell on PATH",
)


def _load():
    spec = importlib.util.spec_from_file_location("_reachability_diff", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rd():
    return _load()


class TestRefusesToExecuteAnythingUnconfined:
    """Every path that could put a real delete outside the sandbox."""

    def test_accepts_a_properly_confined_command(self, rd, tmp_path):
        victim = tmp_path / "victim"
        victim.mkdir()
        rd.assert_safe_to_execute(f"rm -rf {victim}", victim, tmp_path)

    def test_refuses_an_unsubstituted_placeholder(self, rd, tmp_path):
        """The catastrophic case: substitution silently did not happen."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(rd.UnsafeToExecute, match="placeholder"):
            rd.assert_safe_to_execute(f"rm -rf {rd._TARGET}", victim, tmp_path)

    def test_refuses_when_the_victim_is_absent(self, rd, tmp_path):
        """Substituted, but with something other than the intended victim."""
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(rd.UnsafeToExecute, match="victim path absent"):
            rd.assert_safe_to_execute("rm -rf /somewhere/else", victim, tmp_path)

    def test_refuses_a_victim_outside_the_sandbox(self, rd, tmp_path):
        outside = tmp_path.parent / "not_in_sandbox"
        with pytest.raises(rd.UnsafeToExecute, match="outside sandbox"):
            rd.assert_safe_to_execute(f"rm -rf {outside}", outside, tmp_path)

    @pytest.mark.parametrize("operand", ["/", "~", "*"])
    def test_refuses_a_catastrophic_operand_however_it_arrived(self, rd, tmp_path,
                                                               operand):
        """The belt to the other three braces.

        This arm does not care HOW a root/home/glob operand got into the string —
        only that one is present. It must fire even when the victim path is also
        present and every other condition is satisfied.
        """
        victim = tmp_path / "victim"
        victim.mkdir()
        cmd = f"rm -rf {victim}; rm -rf {operand}"
        with pytest.raises(rd.UnsafeToExecute, match="catastrophic operand"):
            rd.assert_safe_to_execute(cmd, victim, tmp_path)

    @pytest.mark.parametrize(
        "trailing", ["/", "~", "~/Documents", "../../etc"],
        ids=["root", "home", "home-child", "parent-escape"],
    )
    def test_refuses_a_second_operand_riding_behind_the_victim(self, rd, tmp_path,
                                                               trailing):
        """⚠ REGRESSION PIN, and the twin of the same hole on the PowerShell leg.

        `_CATASTROPHIC_OPERAND_RE` reads the verb plus its FIRST operand, so a
        delete naming the victim and THEN the home directory matched nothing and
        was accepted — handed to a real `/bin/bash`. `rm` takes a list.
        """
        victim = tmp_path / "victim"
        victim.mkdir()
        with pytest.raises(rd.UnsafeToExecute, match="operand"):
            rd.assert_safe_to_execute(
                f"rm -rf {victim} {trailing}", victim, tmp_path)

    def test_an_inert_quoted_delete_is_still_accepted(self, rd, tmp_path):
        """The calibration twin. A quoted delete lexes to ONE token, so it is not
        a verb — which is correct, because the shell will not execute it either.
        Without this the operand check would refuse well-formed prose rows."""
        victim = tmp_path / "victim"
        victim.mkdir()
        rd.assert_safe_to_execute(
            f"echo 'rm -rf /' ; rm -rf {victim}", victim, tmp_path)

    def test_a_heredoc_terminator_is_not_read_as_an_operand(self, rd, tmp_path):
        """The other calibration twin: a bare trailing word resolves against the
        SANDBOX, not the caller's cwd, so a heredoc terminator is confined."""
        victim = tmp_path / "victim"
        victim.mkdir()
        rd.assert_safe_to_execute(
            f"cat <<'EOF' | bash\nrm -rf {victim}\nEOF", victim, tmp_path)

    def test_every_body_template_carries_the_placeholder(self, rd):
        """A body without the placeholder would be executed verbatim; a body
        with two would carry a second operand that condition (5) cannot see
        inside an interpreter program (one quoted token to shlex); a body
        carrying `$`, a backtick or `"` would be expanded by the outer shell
        inside a double-quoted wrapper before the interpreter saw it, so the
        row would measure a different command than it prints."""
        for name, template in rd.BODIES:
            assert template.count(rd._TARGET) == 1, name
            if name in rd.BODIES_WITH_A_BOUND_EXPANSION:
                # the reasoned exception (DEF-830): no backtick, and every
                # expansion is the ONE name the sandbox environment binds
                # inside the sandbox -- `assert_safe_to_execute` refuses any
                # other before a shell sees it (condition 6, pinned below)
                assert "`" not in template, name
                assert set(rd._PARAMETER_EXPANSION_RE.findall(template)) == {rd._ITEM}, name
                continue
            assert not (set('$`"') & set(template)), name
        assert rd.BODIES_WITH_A_BOUND_EXPANSION <= {name for name, _ in rd.BODIES}, (
            "the exception names a body that no longer exists"
        )

    def test_the_bound_expansion_resolves_inside_the_sandbox(self, rd, tmp_path):
        """The exception's promise, driven: the environment a row runs in
        binds the loop variable to a path inside the sandbox, and a row that
        expands it is accepted with that environment."""
        from pathlib import Path

        env = rd._sandbox_env(tmp_path)
        assert Path(env[rd._ITEM]).resolve().relative_to(tmp_path.resolve())
        victim = tmp_path / "victim"
        victim.mkdir()
        rd.assert_safe_to_execute(f'rm -rf {victim} "${rd._ITEM}"', victim, tmp_path, env=env)

    def test_refuses_an_expansion_the_environment_does_not_bind(self, rd, tmp_path):
        """The must-trip twin of condition (6): the binding absent, empty, or
        outside the sandbox, and the row is refused before any shell sees it
        -- whatever the shell would have made of the name. The 2026-09-17
        incident was an unbound fixture variable; this is the check that was
        missing."""
        victim = tmp_path / "victim"
        victim.mkdir()
        cmd = f'rm -rf {victim} "${rd._ITEM}"'
        with pytest.raises(rd.UnsafeToExecute, match="unbound parameter expansion"):
            rd.assert_safe_to_execute(cmd, victim, tmp_path)
        with pytest.raises(rd.UnsafeToExecute, match="unbound parameter expansion"):
            rd.assert_safe_to_execute(cmd, victim, tmp_path, env={})
        with pytest.raises(rd.UnsafeToExecute, match="bound outside sandbox"):
            rd.assert_safe_to_execute(cmd, victim, tmp_path, env={rd._ITEM: "/"})
        braced = f'rm -rf {victim} "${{{rd._ITEM}}}"'
        with pytest.raises(rd.UnsafeToExecute, match="unbound parameter expansion"):
            rd.assert_safe_to_execute(braced, victim, tmp_path, env={})
        # the calibration twin: an expansion that is no delete's operand (the
        # git rows probe their environment so) is the shell's, not this check's
        rd.assert_safe_to_execute(f'[ -z "$GIT_DIR" ] && rm -rf {victim}', victim, tmp_path, env={})

    @_NEEDS_REAL_BASH_DEFERRED
    def test_an_inherited_git_variable_does_not_reach_the_row(self, rd, monkeypatch):
        """A `GIT_DIR` / `GIT_WORK_TREE` set by a hook, `rebase --exec` or
        `bisect run` would route a `git commit -F -` row into the operator's
        repository. The row's shell sees none of them: the `-z` test reaches
        only if the variable is absent in the child, so an unscrubbed
        environment reds this with the variable set here."""
        monkeypatch.setenv("GIT_DIR", "/nonexistent-git-dir")
        monkeypatch.setenv("GIT_WORK_TREE", "/nonexistent-work-tree")
        assert rd.bash_reaches(
            '[ -z "$GIT_DIR" ] && [ -z "$GIT_WORK_TREE" ] && '
            f"rm -rf {rd._TARGET}") is True

    @_NEEDS_REAL_BASH_DEFERRED
    def test_git_discovery_stops_at_the_sandbox(self, rd):
        assert rd.bash_reaches(
            '[ "$GIT_CEILING_DIRECTORIES" = "$(cd .. && pwd -P)" ] && '
            f"rm -rf {rd._TARGET}") is True

    @_NEEDS_REAL_BASH_DEFERRED
    @pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
    def test_a_commit_row_under_a_tmpdir_inside_a_repository_does_not_commit_there(
            self, rd, tmp_path, monkeypatch):
        """`tempfile` honours a `TMPDIR` that CI sometimes points inside the
        checkout; without a ceiling git walks up from the sandbox, finds that
        repository and commits into it, silently (`-q`, output discarded)."""
        outer = tmp_path / "outer"
        outer.mkdir()
        ident = ["-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", str(outer)], check=True, timeout=60)
        subprocess.run(["git", "-C", str(outer), *ident, "commit", "-q",
                        "--allow-empty", "-m", "base"], check=True, timeout=60)

        def count() -> str:
            return subprocess.run(
                ["git", "-C", str(outer), "rev-list", "--count", "HEAD"],
                capture_output=True, text=True, timeout=60, encoding="utf-8").stdout.strip()

        before = count()
        deep = outer / "deep"
        deep.mkdir()
        # `tempfile` caches its directory on first use, so the env var alone
        # would not move the sandbox; the cache is the thing to point.
        monkeypatch.setattr(tempfile, "tempdir", str(deep))
        template = ("git " + " ".join(ident) + " commit -q --allow-empty -m x; "
                    f"rm -rf {rd._TARGET}")
        reached, _rc = rd.bash_run(template)
        assert reached is True
        assert count() == before, "the row committed into the repository above the sandbox"


# The guard below mirrors the product stand-down in
# `bench/reachability_differential.py::main` EXACTLY, and deliberately keys on
# the artifact rather than on `sys.platform`. These two tests call
# `bash_reaches` directly, bypassing `main()` and therefore bypassing that
# stand-down -- which is why they, and not the end-to-end arm, are the ones
# that fail on a host where `bash` resolves but `/bin/bash` does not exist.
# That is their job: they are the only check that the oracle is alive.
_NEEDS_REAL_BASH = pytest.mark.skipif(
    not Path("/bin/bash").exists(),
    reason="the oracle's ground truth is a real /bin/bash, not any shell on PATH",
)


class TestTheOracleIsLive:
    """A dead instrument reports the comforting answer, not an error."""

    @_NEEDS_REAL_BASH
    def test_bash_reaches_detects_a_real_delete(self, rd):
        assert rd.bash_reaches(f"rm -rf {rd._TARGET}") is True

    @_NEEDS_REAL_BASH
    def test_bash_reaches_is_false_when_the_delete_is_only_mentioned(self, rd):
        assert rd.bash_reaches(f"echo 'rm -rf {rd._TARGET}'") is False

    @_NEEDS_REAL_BASH
    def test_bash_run_reports_the_exit_status_beside_the_reach(self, rd):
        """A render its interpreter rejects exits non-zero and reaches nothing;
        an inert mention exits zero. The pair is what lets `main` tell a
        render that did not run from inert text."""
        assert rd.bash_run(f"echo 'rm -rf {rd._TARGET}'") == (False, 0)
        reached, rc = rd.bash_run(f": {rd._TARGET}; python3 -c 'this is not python'")
        assert (reached, rc != 0) == (False, True)

    @_NEEDS_REAL_BASH
    def test_a_process_substitution_child_is_waited_for(self, rd):
        """bash does not wait for a `>(sh)` child, so the victim can still be
        there the instant bash exits and gone the instant after: measured at
        HEAD, `heredoc_procsub_shell` reached 4 of 9 bodies with no pattern
        across them. The oracle waits for the process group to empty."""
        template = f"cat <<'EOF' > >(sh) ; ls\ntrue && rm -rf {rd._TARGET}\nEOF"
        assert all(rd.bash_reaches(template) for _ in range(5))

    def test_a_baseline_that_denies_nothing_is_rejected(self, rd, tmp_path):
        """The exact shape of the archived-without-siblings failure."""
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        (hooks / "write_guard.py").write_text("import sys\nsys.exit(0)\n",
                                              encoding="utf-8")
        with pytest.raises(RuntimeError, match="denies nothing"):
            rd.assert_baseline_is_live(hooks, str(tmp_path))

    def test_a_baseline_that_denies_everything_is_rejected(self, rd, tmp_path):
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        (hooks / "write_guard.py").write_text(
            'import json\nprint(json.dumps({"hookSpecificOutput": '
            '{"permissionDecision": "deny"}}))\n',
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="denies everything"):
            rd.assert_baseline_is_live(hooks, str(tmp_path))

    def test_a_crashing_guard_raises_rather_than_reading_as_allow(self, rd,
                                                                  tmp_path):
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        (hooks / "write_guard.py").write_text("import nonexistent_module\n",
                                              encoding="utf-8")
        with pytest.raises(RuntimeError, match="instrument is broken"):
            rd.guard_denies("ls", hooks, str(tmp_path))


class TestDenialIsReadFromTheDecisionChannel:
    """`deny()` is exit 0 + JSON on stdout, so a return code proves nothing."""

    def test_a_deny_payload_with_exit_zero_is_read_as_a_deny(self, rd, tmp_path):
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        (hooks / "write_guard.py").write_text(
            'import json, sys\nprint(json.dumps({"hookSpecificOutput": '
            '{"permissionDecision": "deny"}}))\nsys.exit(0)\n',
            encoding="utf-8",
        )
        assert rd.guard_denies("anything", hooks, str(tmp_path)) is True


class TestTheGateRunsEndToEnd:
    """Driven as a real subprocess, the way an operator or CI would run it."""

    @_NEEDS_REAL_BASH
    def test_quick_matrix_exits_clean_against_head(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--quick"],
            capture_output=True, text=True, timeout=300, cwd=REPO_ROOT, encoding="utf-8",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "FAIL-OPEN (must be 0): 0" in result.stdout, result.stdout

class TestClassificationIsExhaustive:
    """All 2^3 verdicts, so the gate's judgement is pinned rather than sampled.

    ⚠ The first draft of this class asserted `reaches and base and not work` —
    a restatement of the predicate, true by construction, catching nothing. It is
    the same vacuity this whole change was written to stop shipping. The table
    below is written independently of the implementation, so an inverted branch
    reds instead of agreeing with itself.
    """

    #: (reaches, base_denies, work_denies) -> verdict. Hand-derived from the
    #: definitions, NOT from reading `classify`.
    EXPECTED = {
        # A genuinely-executing delete that the baseline caught and we no longer
        # do. The one result this gate exists to produce.
        (True, True, False): "fail_open",
        # Inert text the baseline refused and we now allow. The win.
        (False, True, False): "relief",
        # Inert text nobody refused before and we now refuse. New friction.
        (False, False, True): "new_false_positive",
        # Newly denied but genuinely dangerous -- a tightening, not a regression.
        (True, False, True): "unchanged",
        # Both agree, in all four combinations.
        (True, True, True): "unchanged",
        (False, False, False): "unchanged",
        (True, False, False): "unchanged",
        (False, True, True): "unchanged",
    }

    def test_every_combination_is_covered(self):
        import itertools
        assert set(self.EXPECTED) == set(
            itertools.product([True, False], repeat=3)
        )

    @pytest.mark.parametrize("bits,expected", sorted(EXPECTED.items()))
    def test_classification(self, rd, bits, expected):
        assert rd.classify(*bits) == expected

    def test_a_fail_open_row_makes_the_gate_exit_nonzero(self, rd, tmp_path,
                                                         monkeypatch):
        """Earn the red: drive `main` with an oracle that reports a fail-open.

        A gate that cannot report a failure is decoration. Rather than break the
        live guards, stub the three bits so exactly one row classifies as a
        fail-open, and assert the process-level contract (non-zero exit).
        """
        monkeypatch.setattr(rd, "bash_run", lambda template: (True, 0))
        monkeypatch.setattr(rd, "_bash_oracle_available", lambda: True)
        monkeypatch.setattr(rd, "assert_baseline_is_live",
                            lambda hooks, project: None)
        monkeypatch.setattr(rd, "materialise_baseline",
                            lambda ref, dest: tmp_path)
        calls = {"n": 0}

        def fake_guard(cmd, hooks_dir, project_dir):
            # baseline denies, working tree does not -> fail-open on every row
            calls["n"] += 1
            return hooks_dir == tmp_path

        monkeypatch.setattr(rd, "guard_denies", fake_guard)
        assert rd.main(["--quick"]) == 1
        assert calls["n"] > 0, "the stub was never consulted"


class TestTheRosterIsWellFormed:
    """Properties of the roster, never a count of it.

    A count literal moves on ordinary growth and proves nothing about the rows
    (memory: a-hand-written-count-that-moves-on-ordinary-growth-is-tax). What
    a malformed row would actually break is pinned instead: a template with no
    slot runs its body verbatim or not at all; a duplicated name hides one row
    under another; a quick-subset or needs-map entry naming no row is a filter
    on nothing.
    """

    def test_every_wrapper_template_takes_exactly_one_body(self, rd):
        for name, template in rd.WRAPPERS:
            # A second slot raises TypeError here (one argument, two slots);
            # `printf '%%s'` is a legitimate escaped percent, not a slot.
            rendered = template % "BODY_MARK"
            assert rendered.count("BODY_MARK") == 1, name

    def test_wrapper_and_body_names_are_unique(self, rd):
        wnames = [n for n, _ in rd.WRAPPERS]
        bnames = [n for n, _ in rd.BODIES]
        assert len(wnames) == len(set(wnames)), "a duplicated wrapper name"
        assert len(bnames) == len(set(bnames)), "a duplicated body name"

    def test_quick_subsets_name_real_rows(self, rd):
        assert rd.QUICK_WRAPPERS <= {n for n, _ in rd.WRAPPERS}
        assert rd.QUICK_BODIES <= {n for n, _ in rd.BODIES}

    def test_the_needs_map_names_real_rows_and_bare_executables(self, rd):
        names = {n for n, _ in rd.WRAPPERS}
        assert set(rd.WRAPPER_NEEDS) <= names, set(rd.WRAPPER_NEEDS) - names
        for wrapper, exe in rd.WRAPPER_NEEDS.items():
            assert exe and "/" not in exe and " " not in exe, (wrapper, exe)

    def test_the_syntax_map_names_real_rows_with_a_parseable_snippet(self, rd):
        names = {n for n, _ in rd.WRAPPERS}
        assert set(rd.WRAPPER_SYNTAX) <= names, set(rd.WRAPPER_SYNTAX) - names
        for wrapper, snippet in rd.WRAPPER_SYNTAX.items():
            assert snippet.strip() and "\n" not in snippet, (wrapper, snippet)

    def test_the_feature_map_names_real_rows_with_a_one_line_probe(self, rd):
        """A feature probe is RUN by bash, so it must touch nothing: one line,
        and every command word in it POSIX-assumed or the row's own need."""
        names = {n for n, _ in rd.WRAPPERS}
        assert set(rd.WRAPPER_FEATURE) <= names, set(rd.WRAPPER_FEATURE) - names
        for wrapper, probe in rd.WRAPPER_FEATURE.items():
            assert probe.strip() and "\n" not in probe, (wrapper, probe)
            allowed = rd.POSIX_ASSUMED | {rd.WRAPPER_NEEDS.get(wrapper)}
            assert _command_words(probe) <= allowed, (wrapper, _command_words(probe))

    def test_every_command_word_is_posix_assumed_or_the_declared_need(self, rd):
        """The population contract, derived from the templates rather than
        from a list of interpreter names: every word at a command position in
        a wrapper is either on `POSIX_ASSUMED` (present wherever `/bin/bash`
        is) or is that wrapper's declared need -- and every declared need is
        such a word. A row headed by an interpreter nobody listed reds here
        instead of running unpinned and, on a host without it, being scored
        inert (the `timeout` lesson in the WRAPPERS comment, made a rule).
        Direction of error: friction -- a POSIX name missing from the set
        reds a test, never silences a row."""
        for name, template in rd.WRAPPERS:
            words = _command_words(template)
            need = rd.WRAPPER_NEEDS.get(name)
            foreign = words - rd.POSIX_ASSUMED
            assert foreign <= ({need} if need else set()), (
                f"{name} puts {sorted(foreign)} at a command position; "
                f"declared need: {need!r}")
            if need:
                assert need in words, (name, need, sorted(words))

    def test_the_command_word_walk_reads_shell_the_way_the_templates_use_it(self):
        """The extractor itself, pinned on the constructs the roster uses:
        a heredoc body is not command text, a separator inside quotes does
        not split, an escaped separator does not split, a grouping character
        is not a word, the body slot and a comment are not words, and the
        ampersand of a redirect-duplication operator does not split."""
        assert _command_words("bash <<'B' ; cat <<'A'\n%s\nB\nhi\nA") == {"bash", "cat"}
        assert _command_words("cat <<'EOF' |& bash\n%s\nEOF") == {"cat", "bash"}
        assert _command_words("cat <<'EOF' 2>&1 | bash\n%s\nEOF") == {"cat", "bash"}
        assert _command_words("echo x &>/dev/null; ls") == {"echo", "ls"}
        assert _command_words("python3 -c 'import os; os.system(\"\"\"%s\"\"\")'") == {"python3"}
        assert _command_words("find . -exec sh -c '%s' \\;") == {"find"}
        assert _command_words("{ cat <<'EOF'\n%s\nEOF\n} | sh") == {"cat", "sh"}
        assert _command_words("( %s )") == set()
        assert _command_words("# %s\nls") == {"ls"}
        assert _command_words("cd /tmp && deno eval '%s'") == {"cd", "deno"}
        assert _command_words("sh<<<'%s'") == {"sh"}
        assert _command_words("echo \"%s\" $(true) | sh") == {"echo", "sh"}

    @_NEEDS_REAL_BASH
    def test_no_declared_need_is_a_shell_builtin(self, rd):
        """A need is resolved by asking bash (`command -v`), which also
        answers for a builtin -- so a builtin declared here would never be
        absent and the entry would be dead weight that reads as coverage."""
        for exe in sorted(set(rd.WRAPPER_NEEDS.values())):
            kind = subprocess.run(
                ["/bin/bash", "-c", 'type -t -- "$1"', "_", exe],
                capture_output=True, text=True, timeout=30, encoding="utf-8").stdout.strip()
            assert kind not in {"builtin", "keyword", "function", "alias"}, (exe, kind)


class TestTheInterpreterRowsAreLive:
    """Instrument liveness for the interpreter family.

    A row that never reaches contributes no coverage while looking like it
    does, and a "mention" row that DOES reach is not the inert twin it claims
    to be. Both are pinned against the real oracle. This is not an expectation
    about the GUARD -- the differential keeps none -- it is an expectation
    about the ROWS, the same kind `TestTheOracleIsLive` already holds.
    """

    #: Programs that execute the body: through a shell (`os.system`,
    #: `subprocess ... shell=True`, perl/ruby/awk `system`, node `execSync`,
    #: a git shell alias) or with NO shell at all (the list-form subprocess
    #: row), plus the cross-statement `eval` twins of the mention pairs.
    SHELL_OUT = (
        "py_c_sq_os_system", "py_c_dq_os_system", "py_c_sq_subprocess_shell",
        "py_stdin_os_system", "py_stdin_subprocess_list",
        "perl_e_system", "node_e_execsync", "ruby_e_system",
        "awk_system_inline", "awk_system_var", "git_shell_alias",
        "sed_heredoc_piped_to_shell", "heredoc_piped_to_shell",
        "heredoc_procsub_shell", "echo_dq_piped_to_shell",
        "printf_piped_to_shell", "interpreter_then_eval_dq",
        "eval_dq_then_interpreter", "echo_then_eval_dq", "zsh_c_sq",
        "heredoc_stderr_dup_piped_to_shell", "heredoc_pipe_amp_to_shell",
        "interpreter_newline_eval_dq", "echo_dq_pipe_newline_to_shell",
        "heredoc_pipe_newline_then_shell",
        # the trio's third step (2026-09-11): the second executing spelling
        # per head, landed with the reader that refuses them
        "py_c_sq_subprocess_list_sh_c", "py_stdin_split_argv", "perl_e_qx",
        "node_e_exec_dq", "ruby_e_percent_x", "awk_stream_system",
        "awk_print_pipe_sh", "sed_e_stream", "git_config_alias_then_run",
        "printf_piped_to_python", "herestring_sh", "herestring_dq_bash",
        "herestring_glued_sh", "echo_dq_stderr_dup_piped_to_shell",
        "echo_dq_cmdsub_piped_to_shell", "git_rebase_exec",
        # DEF-832: the program operand as one bash word -- a body handed to
        # `sh -c` inside a spliced single-quoted literal
        "py_c_sq_spliced_list_sh_c",
    )
    #: The same interpreters and containers holding the body as DATA -- a
    #: string literal, a commit body or message, a stream to `sed`, a file
    #: written and never run -- and the inert side of the cross-statement
    #: pairs.
    MENTION = (
        "py_c_sq_print", "py_stdin_string", "perl_e_print", "node_e_log",
        "ruby_e_puts", "awk_print_var", "git_commit_stdin", "commit_message",
        "sed_heredoc_print", "heredoc_to_file_then_run",
        "echo_dq_then_interpreter", "interpreter_then_echo_dq",
        "echo_dq_newline_then_interpreter",
        "py_c_sq_spliced_print",          # DEF-832: the spliced literal held as data
    )

    @staticmethod
    def _render(rd, wrapper: str) -> str:
        template = dict(rd.WRAPPERS)[wrapper]
        need = rd.WRAPPER_NEEDS.get(wrapper)
        if need and not rd._executable_available(need):
            pytest.skip(f"{need} is absent on this host")
        snippet = rd.WRAPPER_SYNTAX.get(wrapper)
        if snippet and not rd._syntax_supported(snippet):
            pytest.skip(f"this host's bash cannot parse {snippet!r}")
        probe = rd.WRAPPER_FEATURE.get(wrapper)
        if probe and not rd._feature_supported(probe):
            pytest.skip(f"this host lacks the feature {probe!r} exercises")
        return template % dict(rd.BODIES)["one_statement"]

    @_NEEDS_REAL_BASH
    @pytest.mark.parametrize("wrapper", SHELL_OUT)
    def test_an_executing_row_reaches_the_delete(self, rd, wrapper):
        assert rd.bash_reaches(self._render(rd, wrapper)) is True

    @_NEEDS_REAL_BASH
    @pytest.mark.parametrize("wrapper", MENTION)
    def test_a_mention_row_does_not_reach(self, rd, wrapper):
        assert rd.bash_reaches(self._render(rd, wrapper)) is False

    def test_every_row_declaring_a_need_is_pinned_above(self, rd):
        """A new interpreter row cannot enrol without a liveness pin: every
        wrapper in the needs map is in one of the two tuples."""
        pinned = set(self.SHELL_OUT) | set(self.MENTION)
        assert set(rd.WRAPPER_NEEDS) <= pinned, set(rd.WRAPPER_NEEDS) - pinned
        assert set(rd.WRAPPER_SYNTAX) <= pinned, set(rd.WRAPPER_SYNTAX) - pinned
        assert set(rd.WRAPPER_FEATURE) <= pinned, set(rd.WRAPPER_FEATURE) - pinned

    def test_each_mention_row_has_an_executing_twin_on_the_same_head(self, rd):
        """The relief/fail-open discipline (memory:
        a-friction-fix-and-a-fail-open-are-one-edit): for every inert row's
        head word there is an executing row with the same head word, so a
        change that relieves the mention is answered by a row that runs. The
        pairing is by HEAD WORD -- the container may differ (`awk -v` twins
        `awk "BEGIN{...}"`), which is as fine as this test can see."""
        def head(wrapper: str) -> str:
            return dict(rd.WRAPPERS)[wrapper].split()[0]
        executing_heads = {head(w) for w in self.SHELL_OUT}
        for wrapper in self.MENTION:
            assert head(wrapper) in executing_heads, (wrapper, head(wrapper))

    def test_the_quick_matrix_never_carries_a_mention_row_alone(self, rd):
        """A relief row without its executing twin is a smoke that can only
        report the win (the same memory): every mention wrapper in the quick
        subset has an executing wrapper with the same head word beside it."""
        def head(wrapper: str) -> str:
            return dict(rd.WRAPPERS)[wrapper].split()[0]
        quick_executing = {head(w) for w in rd.QUICK_WRAPPERS if w in self.SHELL_OUT}
        for wrapper in rd.QUICK_WRAPPERS:
            if wrapper in self.MENTION:
                assert head(wrapper) in quick_executing, wrapper


def _command_words(template: str) -> set[str]:
    """Every word at a command position in a wrapper template.

    A small walk that reads shell the way the roster writes it: the first
    word of the template and of every segment after an UNQUOTED `;`, `|`, `&`
    or newline, with grouping characters stripped; a heredoc body is skipped up
    to its terminator; a backslash escapes the next character; the body slot
    and a comment line are not words. Pinned by
    `test_the_command_word_walk_reads_shell_the_way_the_templates_use_it`.
    """
    words: set[str] = set()
    pending: list[str] = []
    heredoc_re = re.compile(r"(?<!<)<<(?!<)-?[ \t]*'?(\w+)'?")
    for line in template.split("\n"):
        if pending:
            if line == pending[0]:
                pending.pop(0)
            continue
        pending.extend(heredoc_re.findall(line))
        segments: list[str] = []
        cur: list[str] = []
        quote: str | None = None
        i = 0
        while i < len(line):
            c = line[i]
            if c == "\\" and quote != "'":
                cur.append(line[i:i + 2])
                i += 2
                continue
            if quote:
                if c == quote:
                    quote = None
                cur.append(c)
            elif c in "'\"":
                quote = c
                cur.append(c)
            elif c == "&" and i > 0 and line[i - 1] == "|":
                pass  # `|&`: the pipe already split; the ampersand is its operator's
            elif c == "&" and ((i > 0 and line[i - 1] in "<>")
                               or (i + 1 < len(line) and line[i + 1] == ">"
                                   and not (i > 0 and line[i - 1] == "&"))):
                cur.append(c)  # `2>&1`, `<&0`, `&>f`: a redirect, not a separator
            elif c in ";|&":
                segments.append("".join(cur))
                cur = []
            else:
                cur.append(c)
            i += 1
        segments.append("".join(cur))
        for seg in segments:
            tokens = seg.strip().lstrip("(){} \t").split()
            if not tokens:
                continue
            # a redirect glued to the head (`sh<<<'...'`, `cat<<EOF`) is not
            # part of the word bash resolves
            word = tokens[0].split("<", 1)[0].split(">", 1)[0]
            if not word or word in ("%s", ")", "}") or word.startswith("#"):
                continue
            words.add(word)
    return words


def _stub_instrument(rd, monkeypatch, tmp_path, *, reaches, base_denies,
                     work_denies, exit_status=lambda template: 0,
                     available=lambda exe: True,
                     syntax=lambda snippet: True,
                     feature=lambda snippet: True):
    """Replace the shell and both guards with pure functions of the row text,
    the way `test_a_fail_open_row_makes_the_gate_exit_nonzero` does, so
    `main` can be driven without a shell and its printed numbers recomputed
    from the same predicates rather than typed. The oracle's stand-down and
    the need resolver are stubbed too: these tests need no bash, and must
    not fail on a host without one (the Windows walk runs this file)."""
    monkeypatch.setattr(rd, "bash_run",
                        lambda template: (reaches(template), exit_status(template)))
    monkeypatch.setattr(rd, "_bash_oracle_available", lambda: True)
    monkeypatch.setattr(rd, "_executable_available", available)
    monkeypatch.setattr(rd, "_syntax_supported", syntax)
    monkeypatch.setattr(rd, "_feature_supported", feature)
    monkeypatch.setattr(rd, "assert_baseline_is_live", lambda hooks, project: None)
    monkeypatch.setattr(rd, "materialise_baseline", lambda ref, dest: tmp_path)

    def fake_guard(cmd, hooks_dir, project_dir):
        return base_denies(cmd) if hooks_dir == tmp_path else work_denies(cmd)

    monkeypatch.setattr(rd, "guard_denies", fake_guard)


def _quick_rows(rd):
    wrappers = [w for w in rd.WRAPPERS if w[0] in rd.QUICK_WRAPPERS]
    bodies = [b for b in rd.BODIES if b[0] in rd.QUICK_BODIES]
    return [(wn, wt % bt) for wn, wt in wrappers for bn, bt in bodies]


class TestAnAbsentInterpreterSkipsTheRowInsteadOfScoringIt:
    """A row whose interpreter is absent can never reach, so an oracle reading
    "did not reach" would file it as INERT -- and a change that stops denying
    it would score RELIEF on a row that was never exercised."""

    def test_the_quick_matrix_carries_a_row_that_needs_an_interpreter(self, rd):
        assert any(w in rd.WRAPPER_NEEDS for w in rd.QUICK_WRAPPERS)

    def test_rows_needing_an_absent_executable_are_named_and_not_scored(
            self, rd, tmp_path, monkeypatch, capsys):
        need = next(rd.WRAPPER_NEEDS[w] for w in sorted(rd.QUICK_WRAPPERS)
                    if w in rd.WRAPPER_NEEDS)
        needing = {w for w in rd.QUICK_WRAPPERS if rd.WRAPPER_NEEDS.get(w) == need}
        # Every row is inert to the stub and the working tree stops denying:
        # RELIEF on every row that is scored, so a skipped row scored anyway
        # would show up in the relief count.
        _stub_instrument(rd, monkeypatch, tmp_path, reaches=lambda t: False,
                         base_denies=lambda c: True, work_denies=lambda c: False,
                         available=lambda exe: exe != need)
        assert rd.main(["--quick"]) == 0
        out = capsys.readouterr().out
        scored = [r for r in _quick_rows(rd) if r[0] not in needing]
        assert f"false positives relieved: {len(scored)}" in out, out
        for wrapper in needing:
            assert wrapper in out, f"{wrapper} was skipped silently:\n{out}"
        assert need in out

    def test_a_row_whose_spelling_the_host_bash_rejects_is_named_and_not_scored(
            self, rd, tmp_path, monkeypatch, capsys):
        """The syntax stand-down is the executable stand-down's twin: a row
        the host's bash cannot parse is skipped and named with its snippet,
        never scored inert on every body."""
        gated = next(iter(rd.WRAPPER_SYNTAX))
        monkeypatch.setattr(rd, "QUICK_WRAPPERS", rd.QUICK_WRAPPERS | {gated})
        _stub_instrument(rd, monkeypatch, tmp_path, reaches=lambda t: False,
                         base_denies=lambda c: True, work_denies=lambda c: False,
                         syntax=lambda snippet: False)
        assert rd.main(["--quick"]) == 0
        out = capsys.readouterr().out
        scored = [r for r in _quick_rows(rd) if r[0] != gated]
        assert f"false positives relieved: {len(scored)}" in out, out
        assert gated in out and rd.WRAPPER_SYNTAX[gated] in out, out

    def test_a_row_whose_feature_the_host_lacks_is_named_and_not_scored(
            self, rd, tmp_path, monkeypatch, capsys):
        """The feature stand-down is the third twin: a row whose tool lacks
        the feature its probe exercises (GNU sed's `e` on a BSD sed) is
        skipped and named with the probe, never scored inert on every body."""
        gated = next(iter(rd.WRAPPER_FEATURE))
        monkeypatch.setattr(rd, "QUICK_WRAPPERS", rd.QUICK_WRAPPERS | {gated})
        _stub_instrument(rd, monkeypatch, tmp_path, reaches=lambda t: False,
                         base_denies=lambda c: True, work_denies=lambda c: False,
                         feature=lambda snippet: False)
        assert rd.main(["--quick"]) == 0
        out = capsys.readouterr().out
        scored = [r for r in _quick_rows(rd) if r[0] != gated]
        assert f"false positives relieved: {len(scored)}" in out, out
        assert gated in out and rd.WRAPPER_FEATURE[gated] in out, out

    def test_nothing_is_skipped_when_every_executable_is_present(
            self, rd, tmp_path, monkeypatch, capsys):
        _stub_instrument(rd, monkeypatch, tmp_path, reaches=lambda t: False,
                         base_denies=lambda c: True, work_denies=lambda c: False)
        assert rd.main(["--quick"]) == 0
        out = capsys.readouterr().out
        assert f"false positives relieved: {len(_quick_rows(rd))}" in out, out
        assert "skipped" not in out

    def test_a_matrix_with_every_wrapper_skipped_is_a_dead_instrument(
            self, rd, tmp_path, monkeypatch, capsys):
        """The population floor: a needs map over-declared onto a thin host
        must not print FAIL-OPEN 0 over nothing (the archived-baseline
        failure, relocated from the guard to the population)."""
        _stub_instrument(rd, monkeypatch, tmp_path, reaches=lambda t: False,
                         base_denies=lambda c: True, work_denies=lambda c: False,
                         available=lambda exe: False)
        monkeypatch.setattr(rd, "WRAPPER_NEEDS",
                            {name: "x" for name, _ in rd.WRAPPERS})
        assert rd.main(["--quick"]) == 1
        out = capsys.readouterr().out
        assert "FAIL-OPEN (must be 0): 0" not in out
        assert "nothing to measure" in out


class TestTheAbsoluteReportReadsTheWorkingTree:
    """Beside the differential verdicts (base vs work) the gate now states what
    the WORKING tree does in absolute terms: how many rows reach and are
    allowed anyway, how many are inert and are denied anyway. Instrumentation
    for reading a tree, not a gate: a base and a work that agree on every row
    exit 0 whatever those numbers say, because the differential's contract is
    unchanged and a policy allow (file-mediated execution, declared out of
    scope in `mask_inert_syntax`) must not red it.
    """

    @staticmethod
    def _bits():
        # Reach is a property of the WRAPPER (only `eval` runs), denial of
        # the BODY (only a two-statement body is refused): the two axes cross,
        # so every cell of the absolute tally is populated -- a reaching row
        # that is allowed, an inert row that is denied, and their opposites.
        reaches = lambda t: "eval" in t     # noqa: E731
        base = lambda c: "true;" in c       # noqa: E731
        work = base                         # agree on every row
        return reaches, base, work

    def test_the_two_absolute_lines_derive_from_the_bits(
            self, rd, tmp_path, monkeypatch, capsys):
        reaches, base, work = self._bits()
        _stub_instrument(rd, monkeypatch, tmp_path, reaches=reaches,
                         base_denies=base, work_denies=work)
        assert rd.main(["--quick"]) == 0
        out = capsys.readouterr().out
        rows = _quick_rows(rd)
        reaching = [(w, t) for w, t in rows if reaches(t)]
        inert = [t for _, t in rows if not reaches(t)]
        allowed = [(w, t) for w, t in reaching if not work(t.replace(rd._TARGET, "/"))]
        denied = [t for t in inert if work(t.replace(rd._TARGET, "/"))]
        assert reaching and inert and allowed and denied, "a vacuous stub"
        assert (f"reaching rows: {len(reaching)}, of which ALLOWED: "
                f"{len(allowed)}") in out, out
        assert (f"inert rows: {len(inert)}, of which DENIED: "
                f"{len(denied)}") in out, out
        # the allowed reaching rows are named, like fail-opens are
        for wrapper, _ in allowed:
            assert f"     {wrapper} / " in out, (wrapper, out)
        # and the differential verdict stays the headline
        assert out.index("FAIL-OPEN") < out.index("[working tree]")

    def test_a_render_that_did_not_run_is_named_and_split_out_of_relief(
            self, rd, tmp_path, monkeypatch, capsys):
        """A row that reaches nothing AND exits non-zero, on a wrapper that
        reaches with another body, is a render its interpreter rejected --
        not inert text, and no relief to anyone when a change stops denying
        it. A wrapper that never reaches at all is an inert consumer whatever
        its exit (grep exits 1 on no match), so its rows are never called
        dead: the stub gives every non-reaching row a non-zero exit to pin
        exactly that distinction."""
        reaches = lambda t: "eval" in t and "true;" not in t  # noqa: E731
        # base refuses every row; work keeps refusing the rows that reach
        # (unchanged) and stops refusing every other row (relief) -- so no
        # row is a fail-open and every inert row, dead or not, is relieved
        _stub_instrument(rd, monkeypatch, tmp_path, reaches=reaches,
                         base_denies=lambda c: True, work_denies=reaches,
                         exit_status=lambda t: 0 if reaches(t) else 1)
        assert rd.main(["--quick", "--report"]) == 0
        out = capsys.readouterr().out
        rows = _quick_rows(rd)
        executing = {w for w, t in rows if reaches(t)}
        dead = [(w, t) for w, t in rows if not reaches(t) and w in executing]
        inert = [t for _, t in rows if not reaches(t)]
        assert dead and len(dead) < len(inert), "a vacuous stub"
        assert f"false positives relieved: {len(inert)}" in out, out
        assert f"renders that did not run: {len(dead)}" in out, out
        row_lines = [ln for ln in out.splitlines() if ln.lstrip().startswith("reach=")]
        for wrapper, _ in dead:
            assert any("rc=1" in ln and f"  {wrapper} / " in ln for ln in row_lines), wrapper

    def test_report_prints_one_line_per_row_and_a_line_per_wrapper(
            self, rd, tmp_path, monkeypatch, capsys):
        reaches, base, work = self._bits()
        _stub_instrument(rd, monkeypatch, tmp_path, reaches=reaches,
                         base_denies=base, work_denies=work)
        assert rd.main(["--quick", "--report"]) == 0
        out = capsys.readouterr().out
        rows = _quick_rows(rd)
        row_lines = [ln for ln in out.splitlines() if ln.lstrip().startswith("reach=")]
        assert len(row_lines) == len(rows)
        for wrapper in rd.QUICK_WRAPPERS:
            assert any(ln.lstrip().startswith(wrapper + " ")
                       for ln in out.splitlines()), (wrapper, out)
        # and the bits on a row line are the stub's, not a constant
        denied = next(ln for ln in row_lines
                      if "eval_dq / two_statements_semicolon" in ln)
        assert "reach=1" in denied and "work=1" in denied, denied
        allowed = next(ln for ln in row_lines if "eval_dq / one_statement" in ln)
        assert "reach=1" in allowed and "work=0" in allowed, allowed

    def test_without_report_no_row_lines_are_printed(
            self, rd, tmp_path, monkeypatch, capsys):
        reaches, base, work = self._bits()
        _stub_instrument(rd, monkeypatch, tmp_path, reaches=reaches,
                         base_denies=base, work_denies=work)
        assert rd.main(["--quick"]) == 0
        out = capsys.readouterr().out
        assert not any(ln.lstrip().startswith("reach=") for ln in out.splitlines())
