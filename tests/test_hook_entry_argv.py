"""Every reader of a wired hook's interpreter reads the argv the hook runs.

One class, five rows (DEF-968, DEF-1146, DEF-1024, DEF-383b, DEF-1145). An
entry with an ``args`` list is exec form: Claude Code spawns ``command``
itself, no shell, so argv[0] is all of ``command`` -- a spaced interpreter path
included, and a quote is part of the file name. Without ``args`` it is shell
form and argv[0] is the first word. The rule is written twice, hook side
(``tools/cc/hooks/session_start.py::_entry_argv``) and engine side
(``espalier._venv.entry_argv``), since neither may import the other; so is the
"does this word name a Python at all" predicate. One table of entry shapes is
read through both copies here, then through each reader that acts on it:
the SessionStart warning, ``doctor``'s resolver check, the rewire, the
enforcement claim's identity arm, and the hook side's remedy hint and
orientation line. The table's "can it start" column is not taken on faith:
``TestTheSpawnIsTheOracle`` spawns a real interpreter under a spaced path on
this host, plain and quoted, with no shell.

It pins the copies equal and every reader to the table because each reader
had its own idea of argv[0]: SessionStart told an adopter wired to
``C:\\Program Files\\Python312\\python.exe`` that every guard fails open
while all of them ran, doctor said nothing about that entry, and the
enforcement claim asked the bare ``py`` its hooks never run.

Marker: ``security`` (registered in ``tests/conftest.py::_MARKER_RULES``).
"""
# slow-exempt: a few stub and real-interpreter spawns on scratch hosts (the launcher, cannot-start and spaced-path rows); 130 tests in 8.1 s serial, measured 2026-10-16
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from espalier import _venv
from espalier import cli
from espalier import doctor
from tests import _interpreter_hosts as hosts

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"

#: A fabricated interpreter under a directory with a space in its name: no
#: host has it, so every row that needs it to "work" patches the probes to
#: accept it, and every row that needs it absent gets that for free.
SPACED = "/opt/Py Tools/python3"
#: The realistic spaced path: cut at its space, the word left names no Python
#: (``C:\Program``), where :data:`SPACED` cut reads ``/opt/Py`` -- a ``py``.
#: The first fixture alone let a regression through (failure-mode review).
PROGRAM_FILES = "C:\\Program Files\\Python312\\python.exe"
#: A cut path whose cut word DOES name a Python (``/Users/me/Python``): the
#: shape a swap of argv[0] turned into a block on every tool call.
PYTHON_ENVS = "/Users/me/Python Envs/py312/bin/python3"
WRITE_GUARD = "${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"


def _session_start():
    """``session_start`` the way a hook loads it: its directory on ``sys.path``,
    so its ``_hook_utils`` is the shared module object the seams patch."""
    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    spec = importlib.util.spec_from_file_location("_ss_entry_argv", HOOKS_DIR / "session_start.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _settings(root: Path, *entries: dict) -> Path:
    claude = root / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    path = claude / "settings.json"
    path.write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "*", "hooks": [{"type": "command", **e} for e in entries]},
    ]}}), encoding="utf-8")
    return path


def _exec(command, *args):
    return {"command": command, "args": list(args)}


def _shell(command):
    return {"command": command}


#: (id, command, args or None for shell form, argv[0], the words after it)
ENTRIES = [
    ("exec-bare", "python3", ["x.py"], "python3", ["x.py"]),
    ("exec-spaced", SPACED, ["x.py"], SPACED, ["x.py"]),
    ("exec-spaced-quoted", f'"{SPACED}"', ["x.py"], f'"{SPACED}"', ["x.py"]),
    ("exec-windows-spaced", "C:\\Program Files\\Python312\\python.exe", ["x.py"],
     "C:\\Program Files\\Python312\\python.exe", ["x.py"]),
    ("exec-launcher", "py", ["-3", "x.py"], "py", ["-3", "x.py"]),
    ("exec-empty-args", "python3", [], "python3", []),
    ("exec-not-a-string", None, ["x.py"], "", ["x.py"]),
    ("shell-bare", "python3 x.py", None, "python3", ["x.py"]),
    ("shell-spaced-quoted", f'"{SPACED}" x.py', None, SPACED, ["x.py"]),
    ("shell-spaced-single-quoted", f"'{SPACED}' x.py", None, SPACED, ["x.py"]),
    ("shell-spaced-unquoted", f"{SPACED} x.py", None, "/opt/Py", ["Tools/python3", "x.py"]),
    ("shell-launcher", "py -3 x.py", None, "py", ["-3", "x.py"]),
    ("shell-unterminated-quote", f'"{SPACED} x.py', None, f"{SPACED} x.py", []),
    ("shell-blank", "   ", None, "", []),
    ("shell-not-a-string", 42, None, "", []),
    ("shell-program-files-unquoted", f"{PROGRAM_FILES} x.py", None, "C:\\Program",
     ["Files\\Python312\\python.exe", "x.py"]),
    ("shell-tilde", "~/venv/bin/python x.py", None, os.path.expanduser("~/venv/bin/python"), ["x.py"]),
    ("shell-tilde-quoted", '"~/venv/bin/python" x.py', None, "~/venv/bin/python", ["x.py"]),
    ("exec-launcher-in-command", "py -3", ["x.py"], "py -3", ["x.py"]),
]


class TestTheArgvRuleIsWrittenTwiceAlike:
    @pytest.mark.parametrize("command,args,head,rest", [e[1:] for e in ENTRIES], ids=[e[0] for e in ENTRIES])
    def test_both_copies_read_argv_zero_by_the_form(self, command, args, head, rest):
        hook = _session_start()._entry_argv(command, args)
        engine = _venv.entry_argv(command, args)
        assert tuple(hook) == tuple(engine) == (head, rest)

    def test_an_args_list_is_what_makes_an_entry_exec_form(self):
        """The same spaced string is one word with ``args`` and two without:
        the form decides before the word."""
        assert _venv.entry_argv(SPACED, [])[0] == SPACED
        assert _venv.entry_argv(SPACED)[0] == "/opt/Py"


#: (token, names a Python)
TOKENS = [
    ("python", True), ("python3", True), ("python3.12", True), ("python9", True),
    ("py", True), ("py.exe", True), ("PY.EXE", True), ("Python.exe", True),
    ("/usr/bin/python3", True), ("C:\\Program Files\\Python312\\python.exe", True),
    (f'"{SPACED}"', True), ('"python3"', True), ("'py.exe'", True), ("/opt/Py", True),
    ('"$CLAUDE_PROJECT_DIR"', False),
    # An exec name with a space names the Python it cannot start; a wrapper,
    # pypy and a $-led head are not asked, by decision (each docstring says so).
    ("py -3", True), ("python -X utf8", True), ("node --inspect", False), ("pypy3", False),
    ("env", False), ("C:\\Program", False),
    ("npx", False), ("node", False), ("bash", False), ("powershell.exe", False),
    ("./.claude/hooks/notify", False), ("$CLAUDE_PROJECT_DIR", False), ("$PYTHON", False),
    ("${CLAUDE_PROJECT_DIR}/tools/cc/hooks/x.py", False), ("C:\\tools\\hook.cmd", False), ("", False),
]


class TestThePythonPredicateIsWrittenTwiceAlike:
    @pytest.mark.parametrize("token,named", TOKENS, ids=[t[0] or "empty" for t in TOKENS])
    def test_both_copies_answer_alike(self, token, named):
        assert _session_start()._names_a_python(token) is named
        assert cli._is_python_interpreter_site(token) is named


#: (exec command, its file name holds a space)
EXEC_NAMES = [
    ("python3", False), (SPACED, False), (PROGRAM_FILES, False), ("py", False),
    ("py -3", True), ("python -X utf8", True), ("C:\\Py Dir\\python -u", True),
]

#: (shell command, the Python path the shell cuts, or None)
SHELL_COMMANDS = [
    (f"{PROGRAM_FILES} x.py", PROGRAM_FILES),
    (f"{PYTHON_ENVS} x.py", PYTHON_ENVS),
    (f"{SPACED} x.py", SPACED),
    (f'"{PROGRAM_FILES}" x.py', None),
    ("python3 x.py", None),
    ("/usr/bin/env python3 x.py", None),
    ("/usr/bin/python3 /opt/my dir/python_hook.py", None),
    ("/opt/hooks dir/python_hook.py", None),
    ("node x.js", None),
]


class TestTheShapeHelpersAreWrittenTwiceAlike:
    @pytest.mark.parametrize("command,spaced", EXEC_NAMES, ids=[e[0] for e in EXEC_NAMES])
    def test_an_exec_name_with_a_space_reads_alike(self, command, spaced):
        assert _session_start()._exec_name_has_space(command) is spaced
        assert _venv.exec_name_has_space(command) is spaced

    @pytest.mark.parametrize("command,cut", SHELL_COMMANDS, ids=[s[0] for s in SHELL_COMMANDS])
    def test_a_cut_shell_path_reads_alike(self, command, cut):
        assert _session_start()._shell_cut_path(command) == cut
        assert _venv.shell_cut_path(command) == cut


def _ci_guard():
    spec = importlib.util.spec_from_file_location(
        "_ci_guard_entry_argv", REPO_ROOT / "tools" / "cc" / "ci_guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


#: (exec command, the gate-wiring check calls it a bare interpreter)
GATE_COMMANDS = [
    ("python3", True), ("py", True), ("Python.exe", True), (SPACED, True), (PROGRAM_FILES, True),
    ("C:/Py Launcher/py.exe", True), ("py -3", False), ("python -u", False), ("node", False),
    ("echo", False), ("", False),
]


class TestTheGateWiringCheckReadsTheExecName:
    """The gate-wiring check's three copies (engine, CI guard, hook side) call
    an exec ``command`` a bare interpreter by one rule: a space in the
    directory is a real path's, one in the file name is none (DEF-968). They
    refused any space, so on a host whose interpreter sits under a spaced
    directory doctor called every gate unwired and config_guard recorded no
    gate to protect."""

    @pytest.mark.parametrize("command,bare", GATE_COMMANDS, ids=[g[0] or "empty" for g in GATE_COMMANDS])
    def test_the_three_copies_answer_alike(self, command, bare):
        if str(HOOKS_DIR) not in sys.path:
            sys.path.insert(0, str(HOOKS_DIR))
        import _integrity  # type: ignore[import-not-found]

        from espalier import surface_contract
        assert surface_contract._is_python_interpreter(command) is bare
        assert _ci_guard()._ci_is_python_interpreter(command) is bare
        assert _integrity._is_python_interpreter(command) is bare

    def test_a_spaced_interpreter_wires_a_gate(self):
        from espalier import surface_contract
        hook = {"type": "command", "command": PROGRAM_FILES,
                "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"]}
        assert surface_contract._hook_executes_script_path(hook) == "tools/cc/hooks/write_guard.py"


class TestSessionStartWarnsAboutTheArgvItRuns:
    """DEF-968 and DEF-1024, in process, with the floor and identity probes
    patched to accept ``python3`` and :data:`SPACED` alone."""

    @pytest.fixture
    def warn(self, tmp_path, monkeypatch):
        ss = _session_start()
        hu = ss._hook_utils
        asked: list[str] = []

        def accepts(spelling):
            asked.append(spelling)
            return spelling in ("python3", SPACED, "py -3")

        said: list[str] = []
        monkeypatch.setattr(hu, "interpreter_meets_floor", accepts)
        monkeypatch.setattr(hu, "interpreter_is_python3", accepts)
        monkeypatch.setattr(hu, "advise", lambda line, **_kw: said.append(line))

        def run(*entries):
            asked.clear()
            said.clear()
            _settings(tmp_path, *entries)
            ss._warn_if_hook_interpreter_unresolved(tmp_path)
            named = sorted({line.split("`")[1] for line in said if "`" in line})
            return named, list(asked)
        return run

    @pytest.mark.parametrize("entry,named", [
        (_exec("python3", "x.py"), []),
        (_exec(SPACED, "x.py"), []),
        (_shell("python3 x.py"), []),
        (_shell('"python3" x.py'), []),
        (_shell(f'"{SPACED}" x.py'), []),
        (_exec('"python3"', "x.py"), ['"python3"']),
        (_exec(f'"{SPACED}"', "x.py"), [f'"{SPACED}"']),
        (_shell(f"{SPACED} x.py"), ["/opt/Py"]),
        (_shell(f"{PROGRAM_FILES} x.py"), ["C:\\Program"]),
        (_exec("py -3", "x.py"), ["py -3"]),
        (_exec("python -X utf8", "x.py"), ["python -X utf8"]),
    ], ids=["exec-bare", "exec-spaced", "shell-bare", "shell-quoted-bare", "shell-spaced-quoted",
            "exec-quoted-bare", "exec-spaced-quoted", "shell-spaced-unquoted",
            "shell-program-files-unquoted", "exec-launcher-in-command", "exec-flag-in-command"])
    def test_silent_where_the_entry_starts_and_named_where_it_cannot(self, warn, entry, named):
        """The launchable spellings stay silent. Named, each as the word the
        spawn would use: the quoted exec forms (the quotes are part of the file
        name), an exec name with words after it (one file name no host has --
        never split into the launcher and a flag), and the unquoted spaced
        shell form (``sh -c`` cuts it), whether or not the cut word names a
        Python (``C:\\Program`` does not: the regression the real-host drive
        and the failure-mode review found)."""
        assert warn(entry)[0] == named

    def test_the_launcher_is_asked_with_its_flag(self, warn):
        named, asked = warn(_exec("py", "-3", "x.py"))
        assert named == [] and "py -3" in asked and "py" not in asked

    @pytest.mark.parametrize("entry", [
        _shell("npx prettier --write"), _shell("node x.js"), _shell("bash x.sh"),
        _shell('"$CLAUDE_PROJECT_DIR"/.claude/hooks/x.sh'), _exec("powershell.exe", "-File", "x.ps1"),
        _shell("powershell.exe -Command x"), _shell("./.claude/hooks/notify"),
        _exec("C:\\tools\\hook.cmd", "x"),
    ], ids=["npx", "node", "bash", "unbraced-var", "powershell-exec", "powershell-command",
            "path-hook", "cmd-hook"])
    def test_a_head_that_names_no_python_is_never_spawned(self, warn, entry):
        """DEF-1024: nothing that is not a Python is asked whether it is one --
        no warning, and no ``--version`` spawn (a path hook ran twice)."""
        assert warn(entry) == ([], [])

    def test_a_python_shaped_head_that_does_not_answer_is_still_named(self, warn):
        """The control: the predicate skips non-Pythons, not broken Pythons."""
        assert warn(_shell("python9 x.py")) == (["python9"], ["python9", "python9"])


class TestDoctorReadsTheArgvItRuns:
    """DEF-968 and DEF-383b on ``doctor._check_python_resolver``."""

    @pytest.fixture(autouse=True)
    def _remedy(self, monkeypatch):
        calls: list[int] = []
        monkeypatch.setattr(doctor, "_remedy_py", lambda: calls.append(1) or "python")
        return calls

    def test_a_spaced_exec_path_is_examined_whole(self, tmp_path):
        issues = doctor._check_python_resolver(tmp_path, _settings(tmp_path, _exec(SPACED, WRITE_GUARD)))
        assert len(issues) == 1 and f"`{SPACED}` does not resolve" in issues[0], issues

    def test_a_quoted_exec_path_is_named_with_its_quotes(self, tmp_path):
        issues = doctor._check_python_resolver(
            tmp_path, _settings(tmp_path, _exec(f'"{SPACED}"', WRITE_GUARD)))
        assert len(issues) == 1 and f'`"{SPACED}"` does not resolve' in issues[0], issues

    def test_the_remedy_is_asked_once_for_every_broken_entry(self, tmp_path, _remedy):
        """DEF-383b: three broken entries, one remedy probe (it was one per
        entry, each two child processes)."""
        settings = _settings(tmp_path, *(_shell(f"python-missing-{i} x.py") for i in range(3)))
        issues = doctor._check_python_resolver(tmp_path, settings)
        assert len(issues) == 3 and len(_remedy) == 1, (issues, _remedy)

    def test_a_healthy_host_asks_no_remedy(self, tmp_path, _remedy):
        settings = _settings(tmp_path, _exec(sys.executable, WRITE_GUARD))
        assert doctor._check_python_resolver(tmp_path, settings) == [] and _remedy == []

    @pytest.mark.parametrize("entry,named", [
        (_exec("py -3", WRITE_GUARD), "py -3"),
        (_exec("python -X utf8", WRITE_GUARD), "python -X utf8"),
        (_shell(f"{PROGRAM_FILES} {WRITE_GUARD}"), "C:\\Program"),
        (_shell(f"{PYTHON_ENVS} {WRITE_GUARD}"), "/Users/me/Python"),
    ], ids=["exec-launcher-in-command", "exec-flag-in-command", "shell-cut-program-files",
            "shell-cut-python-envs"])
    def test_an_entry_no_spawn_can_start_is_named_and_sent_to_a_hand_edit(self, tmp_path, entry, named):
        """The rewire declines each of these (a swap would drop the words or
        write a blocking command), so doctor must not prescribe it."""
        issues = doctor._check_python_resolver(tmp_path, _settings(tmp_path, entry))
        assert len(issues) == 1 and f"`{named}` does not resolve" in issues[0], issues
        assert "will NOT fix this one" in issues[0], issues[0]

    def test_a_tilde_head_is_read_as_the_shell_expands_it(self, tmp_path, monkeypatch):
        """``~/...`` in shell form runs the expanded path; doctor read the raw
        word, which never resolves (failure-mode review)."""
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        settings = _settings(tmp_path / "repo", _shell(f"~/nowhere/python3 {WRITE_GUARD}"))
        issues = doctor._check_python_resolver(tmp_path / "repo", settings)
        assert len(issues) == 1 and str(home) in issues[0] and "`~/" not in issues[0], issues

    def test_the_cannot_start_remedy_is_asked_once(self, tmp_path, monkeypatch):
        """DEF-383b's sibling in the cannot-start branch: two entries whose
        banner passes and whose start fails, one ``_remedy_hint`` ask."""
        calls: list[int] = []
        monkeypatch.setattr(doctor, "_remedy_hint", lambda: calls.append(1) or ("python", True, "x"))
        monkeypatch.setenv("PATH", str(hosts.build_cannot_start(tmp_path / "host", ("python-a", "python-b"))))
        settings = _settings(tmp_path, _shell(f"python-a {WRITE_GUARD}"), _shell(f"python-b {WRITE_GUARD}"))
        issues = doctor._check_python_resolver(tmp_path, settings)
        assert len(issues) == 2 and len(calls) == 1, (issues, calls)


class TestTheRewireReadsTheArgvItRuns:
    def test_a_spaced_exec_path_below_the_floor_is_rewired_whole(self, tmp_path, monkeypatch):
        """DEF-968: the rewire read ``/opt/Py``, not a Python, and left the
        entry alone; read whole, it swaps ``command`` and keeps every arg."""
        target = "python-target"
        monkeypatch.setattr(cli, "interpreter_meets_floor", lambda spelling: spelling == target)
        settings = _settings(tmp_path, _exec(SPACED, WRITE_GUARD))
        result = cli.rewire_interpreter_in_settings(settings, new_interpreter=target)
        entry = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]
        assert result.status == cli.REWIRE_DONE, result
        assert (entry["command"], entry["args"]) == (target, [WRITE_GUARD])

    def test_a_quoted_exec_path_is_rewired_unquoted(self, tmp_path, monkeypatch):
        target = "python-target"
        monkeypatch.setattr(cli, "interpreter_meets_floor", lambda spelling: spelling == target)
        settings = _settings(tmp_path, _exec(f'"{SPACED}"', WRITE_GUARD))
        cli.rewire_interpreter_in_settings(settings, new_interpreter=target)
        entry = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]
        assert entry["command"] == target

    @pytest.mark.parametrize("entry", [
        _shell(f"{PYTHON_ENVS} {WRITE_GUARD}"), _shell(f"{PROGRAM_FILES} {WRITE_GUARD}"),
        _exec("python -X utf8", WRITE_GUARD), _exec("py -3", WRITE_GUARD),
    ], ids=["shell-cut-python-envs", "shell-cut-program-files", "exec-flag-in-command",
            "exec-launcher-in-command"])
    def test_an_entry_a_swap_would_break_is_declined_and_left_alone(self, tmp_path, monkeypatch, entry):
        """A swap of the cut word wrote ``python Envs/py312/...``, exit 2 from
        PreToolUse: a block on every tool call where the cut path had only
        failed open. A whole-``command`` swap dropped ``-X utf8``. Both are
        declined, counted, and the file is untouched."""
        target = "python-target"
        monkeypatch.setattr(cli, "interpreter_meets_floor", lambda spelling: spelling == target)
        settings = _settings(tmp_path, entry)
        before = settings.read_bytes()
        result = cli.rewire_interpreter_in_settings(settings, new_interpreter=target)
        assert result.status == cli.REWIRE_NOTHING and len(result.declined) == 1, result
        assert settings.read_bytes() == before


class TestTheLauncherIsAskedAsTheHooksRunIt:
    """DEF-1146 on a host whose bare ``py`` answers Python 2 while ``py -3``
    runs this interpreter: a real stub, spawned."""

    @pytest.fixture
    def py2_default(self, tmp_path, monkeypatch):
        bin_dir = hosts.build_old_default_launcher(tmp_path / "host", default_banner="Python 2.7.18")
        monkeypatch.setenv("PATH", str(bin_dir))
        return _settings(tmp_path, _exec("py", "-3", WRITE_GUARD))

    def test_the_enforcement_claim_asks_py_dash_3(self, py2_default):
        # Non-vacuous: the walker sees the entry, spelled as the hook runs it.
        assert [e.spelling for e in cli._wired_espalier_entries(py2_default)] == ["py -3"]
        assert cli._wired_interpreters_not_python3(py2_default) == {}

    def test_doctor_asks_py_dash_3(self, tmp_path, py2_default, monkeypatch):
        monkeypatch.setattr(doctor, "_remedy_py", lambda: "python")
        assert doctor._check_python_resolver(tmp_path, py2_default) == []

    def test_the_bare_launcher_is_what_answers_python_2(self, py2_default):
        """The control: the host really does split the two spellings."""
        import shutil
        py = shutil.which("py")
        bare = subprocess.run([py, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=30)
        flagged = subprocess.run([py, "-3", "--version"], capture_output=True, text=True, encoding="utf-8",
                                 timeout=30)
        assert "Python 2.7" in bare.stdout and flagged.stdout.startswith("Python 3"), (bare, flagged)


class TestTheClaimNamesWhatCannotStart:
    @pytest.mark.parametrize("entry,named", [
        (_exec("py -3", WRITE_GUARD), "py -3"),
        (_shell(f"{PROGRAM_FILES} {WRITE_GUARD}"), "C:\\Program"),
    ], ids=["exec-launcher-in-command", "shell-cut-program-files"])
    def test_the_identity_arm_holds_the_claim(self, tmp_path, entry, named):
        """An exec name with a space is probed whole and resolves nowhere; a
        cut shell path is asked by the cut word the shell runs. Both left the
        claim "active" while every guard failed open."""
        found = cli._wired_interpreters_not_python3(_settings(tmp_path, entry))
        assert list(found) == [named], found
        assert found[named].rels == ["tools/cc/hooks/write_guard.py"]


class TestTheHookSideNamesOnlyAnInterpreterThatStarts:
    """DEF-1145: the remedy hint and the orientation line, on a host whose
    ``python3`` and ``python`` answer a Python 3 banner and cannot start."""

    @pytest.fixture
    def hu(self, monkeypatch):
        ss = _session_start()
        monkeypatch.setattr(ss._hook_utils, "_INTERPRETER_IDENTITY_MEMO", {})
        return ss._hook_utils

    def test_cannot_start_names_are_neither_spelled_nor_reported(self, tmp_path, hu, monkeypatch):
        monkeypatch.setenv("PATH", str(hosts.build_cannot_start(tmp_path, ("python3", "python"))))
        assert hu.python_command_hint() not in ("python3", "python")
        assert "python3=no python=no" in hu.host_orientation_line()

    def test_a_working_name_is_still_spelled_and_reported(self, tmp_path, hu, monkeypatch):
        """The control: the start probe refuses what cannot start, not a stub."""
        monkeypatch.setenv("PATH", str(hosts.build_cannot_start(tmp_path, (), working=("python3",))))
        assert hu.python_command_hint() == "python3"
        assert "python3=yes" in hu.host_orientation_line()

    def test_the_two_start_probes_agree(self, tmp_path, hu, monkeypatch):
        """The hook-side probe and the engine's agree on a name that cannot
        start and on one that can."""
        import shutil

        from espalier._python_floor import interpreter_start_failure as engine_probe
        monkeypatch.setenv("PATH", str(hosts.build_cannot_start(tmp_path, ("python",), working=("python3",))))
        for name, starts in (("python", False), ("python3", True)):
            assert (hu.interpreter_start_failure(name) is None) is starts
            assert (engine_probe([shutil.which(name)]) is None) is starts


class TestTheHookStartProbesOwnRule:
    """The reporter's start probe and where it differs from the engine's on
    purpose (its docstring names both): no ``-I`` and no environment rescue,
    since a hook inherits this session's environment, and two timeouts keep
    the banner's verdict. The shortcut for the running interpreter keys on
    its invoked path, as the engine's does. Each pinned here, since four
    mutants of the first draft survived every test (failure-mode review)."""

    @pytest.fixture
    def probe(self, tmp_path, monkeypatch):
        ss = _session_start()
        hu = ss._hook_utils
        monkeypatch.setattr(hu, "_INTERPRETER_IDENTITY_MEMO", {})
        monkeypatch.setenv("PATH", str(hosts.build_cannot_start(tmp_path / "host", ("python",))))
        calls: list[list[str]] = []
        outcomes: list[object] = []

        def fake_run(argv, **kwargs):
            calls.append(list(argv))
            outcome = outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return subprocess.CompletedProcess(argv, outcome, stdout="", stderr="")

        monkeypatch.setattr(hu, "run_bounded", fake_run)

        def run(name, *planned):
            hu._INTERPRETER_IDENTITY_MEMO.clear()
            calls.clear()
            outcomes[:] = list(planned)
            return hu.interpreter_start_failure(name), list(calls)
        return run

    def test_the_probe_runs_in_the_hooks_own_environment(self, probe):
        failure, calls = probe("python", 0)
        assert failure is None and calls[0][1:] == ["-c", "import sys"], calls

    def test_two_timeouts_keep_the_banners_verdict_and_an_exit_status_is_not_retried(self, probe):
        slow = subprocess.TimeoutExpired(["python"], 2)
        failure, calls = probe("python", slow, slow)
        assert failure is None and len(calls) == 2, calls
        failure, calls = probe("python", 1)
        assert failure is not None and "exits 1" in failure and len(calls) == 1, (failure, calls)

    def test_the_running_interpreter_is_not_spawned_whatever_the_environment(self, probe, monkeypatch):
        monkeypatch.setenv("PYTHONPATH", "rescue")
        assert probe(sys.executable) == (None, [])

    def test_the_running_interpreter_shortcut_keys_on_its_path_not_its_file(self, probe, monkeypatch):
        import shutil

        stub = Path(shutil.which("python"))
        link = stub.with_name("python-linked" + stub.suffix)
        try:
            os.link(stub, link)
        except OSError as exc:  # a filesystem without hardlinks
            pytest.skip(f"no hardlink here: {exc}")
        monkeypatch.setattr(sys, "executable", str(stub))
        assert probe(str(stub)) == (None, [])
        failure, calls = probe(str(link), 1)
        assert failure is not None and len(calls) == 1, "a second path to the running binary passed on identity"


def _spaced_interpreter(root: Path) -> Path:
    """A real interpreter under a directory with a space in its name: a fresh
    virtualenv without pip, the shape of a checkout under ``Systems and
    Software``. A venv, not a junction or a link to the running install, so a
    run killed mid-test leaves nothing in a temp dir that points into the live
    Python (failure-mode review)."""
    venv = root / "Py Tools" / "v"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)],
                   check=True, capture_output=True, timeout=50)
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")


class TestTheSpawnIsTheOracle:
    """The table's premise, on this host: an exec-form spawn (no shell) of a
    spaced interpreter path runs, and the same path quoted does not."""

    @pytest.fixture
    def spaced(self, tmp_path):
        try:
            return _spaced_interpreter(tmp_path)
        except (OSError, subprocess.SubprocessError) as exc:
            pytest.skip(f"no spaced interpreter on this host: {exc}")

    def test_the_plain_spaced_path_starts_and_the_quoted_one_cannot(self, spaced):
        ran = subprocess.run([str(spaced), "-c", "pass"], capture_output=True, timeout=30)
        assert ran.returncode == 0, ran.stderr
        with pytest.raises(OSError):
            subprocess.run([f'"{spaced}"', "-c", "pass"], capture_output=True, timeout=30)

    def test_session_start_agrees_with_the_spawn(self, tmp_path, spaced, monkeypatch):
        """Unpatched probes: the spaced exec path is silent, its quoted twin is
        named -- the verdicts the spawn above gives."""
        ss = _session_start()
        monkeypatch.setattr(ss._hook_utils, "_INTERPRETER_IDENTITY_MEMO", {})
        said: list[str] = []
        monkeypatch.setattr(ss._hook_utils, "advise", lambda line, **_kw: said.append(line))
        _settings(tmp_path / "plain", _exec(str(spaced), "x.py"))
        ss._warn_if_hook_interpreter_unresolved(tmp_path / "plain")
        assert said == []
        _settings(tmp_path / "quoted", _exec(f'"{spaced}"', "x.py"))
        ss._warn_if_hook_interpreter_unresolved(tmp_path / "quoted")
        assert len(said) == 1 and f'`"{spaced}"`' in said[0], said
