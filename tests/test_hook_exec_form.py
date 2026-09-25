"""TP-35: hook entries must use exec form (``command`` + ``args``).

Pins the post-TP-35 emission shape against the pre-TP-35
regression: the renderer used to emit shell form with an absolute
interpreter path (``/usr/bin/python3 "$CLAUDE_PROJECT_DIR/..."``).
That failed on Windows (no ``/usr/bin/python3``) and broke when
``$CLAUDE_PROJECT_DIR`` contained spaces — every adopter on
either Windows or a spaces-in-path checkout silently lost all hook
enforcement.

Exec form passes ``command="python"`` and ``args=[path]`` directly
to Claude Code, which spawns the interpreter from PATH with each
arg verbatim. No shell, no tokenization, no platform-specific
variable syntax. The ``${CLAUDE_PROJECT_DIR}`` placeholder uses
Claude Code's curly syntax so the substitution is one verbatim
string regardless of platform.

Without this contract a renderer tweak could silently re-introduce
shell form, leaving the harness emission broken on the platforms
the test fixtures don't cover. See ``docs/HOOKS.md`` for the
python-on-PATH requirement and macOS symlink guidance.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# The two bare interpreter names `cli._detect_python_command` can resolve
# (it returns "python3" or "python"). Portable = on PATH, not absolute.
_PORTABLE_INTERPRETERS = {"python", "python3"}


@pytest.fixture
def initialized_repo(tmp_path: Path) -> Path:
    subprocess.run(
        ["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True
    )
    subprocess.run(
        [sys.executable, "-m", "espalier.cli", "init", str(tmp_path)],
        check=True, cwd=REPO_ROOT, capture_output=True,
    )
    return tmp_path


def _load_settings(repo: Path) -> dict:
    return json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))


def _iter_hooks(settings: dict):
    for event, entries in settings.get("hooks", {}).items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                yield event, hook


@pytest.mark.integration
class TestExecForm:
    def test_every_hook_uses_exec_form(self, initialized_repo):
        """All hooks must carry an `args` list (exec form). Shell form
        with embedded paths is the regressed shape."""
        settings = _load_settings(initialized_repo)
        shell_form = []
        for event, hook in _iter_hooks(settings):
            if "args" not in hook or not isinstance(hook["args"], list):
                shell_form.append(
                    f"{event}: command={hook.get('command', '?')[:80]!r}"
                )
        assert not shell_form, (
            "TP-35: every hook must use exec form ({command, args}).\n"
            "Shell-form hooks found:\n  " + "\n  ".join(shell_form)
        )

    def test_command_is_bare_interpreter(self, initialized_repo):
        """Command must be a bare interpreter name, not an absolute path.
        TP-40 follow-up relaxed this from `== "python"` to accept either
        `python` or `python3` (whichever resolved on PATH at init time
        via ``_detect_python_command``). Absolute paths still break
        Windows; the resolver picks one of the two bare names."""
        settings = _load_settings(initialized_repo)
        allowed = {"python", "python3"}
        for event, hook in _iter_hooks(settings):
            cmd = hook.get("command", "")
            assert cmd in allowed, (
                f"hook command must be one of {sorted(allowed)} "
                f"(got {cmd!r} in {event}). Absolute paths break Windows; "
                f"only bare interpreter names are portable."
            )
            assert "/" not in cmd and "\\" not in cmd, (
                f"command must not be an absolute path (got {cmd!r})"
            )

    def test_args_use_curly_project_dir_placeholder(self, initialized_repo):
        """The script path must use Claude Code's ``${CLAUDE_PROJECT_DIR}``
        (curly) placeholder. Bare ``$CLAUDE_PROJECT_DIR`` is documented
        to expand only inside shell form, not in args."""
        settings = _load_settings(initialized_repo)
        for event, hook in _iter_hooks(settings):
            args = hook.get("args", [])
            assert args, f"{event}: empty args"
            script_arg = args[0]
            assert "${CLAUDE_PROJECT_DIR}" in script_arg, (
                f"TP-35: arg must use curly ${{CLAUDE_PROJECT_DIR}} "
                f"placeholder. Got: {script_arg!r} in {event}"
            )
            assert "$CLAUDE_PROJECT_DIR/" not in script_arg.replace(
                "${CLAUDE_PROJECT_DIR}", ""
            ), (
                f"TP-35: bare $CLAUDE_PROJECT_DIR found alongside "
                f"the curly form. Use only the curly form: {script_arg!r}"
            )

    def test_args_path_points_under_tools_cc_hooks(self, initialized_repo):
        """Every hook script path must live under ``tools/cc/hooks/``
        relative to the project root."""
        settings = _load_settings(initialized_repo)
        for event, hook in _iter_hooks(settings):
            args = hook.get("args", [])
            assert args, f"{event}: empty args"
            script_arg = args[0]
            # Strip placeholder
            tail = script_arg.replace("${CLAUDE_PROJECT_DIR}/", "")
            assert tail.startswith("tools/cc/hooks/"), (
                f"TP-35: hook script path must be under "
                f"tools/cc/hooks/. Got: {script_arg!r} in {event}"
            )
            assert tail.endswith(".py"), (
                f"TP-35: hook script path must end in .py. "
                f"Got: {script_arg!r} in {event}"
            )

    def test_no_absolute_interpreter_path(self, initialized_repo):
        """No hook command should be an absolute path. Absolute paths
        break cross-platform portability — that's the regression TP-35
        guards against."""
        settings = _load_settings(initialized_repo)
        bad = []
        for event, hook in _iter_hooks(settings):
            cmd = hook.get("command", "")
            if cmd.startswith("/") or (len(cmd) > 2 and cmd[1] == ":"):
                bad.append(f"{event}: {cmd}")
        assert not bad, (
            "TP-35: hook command must be the relative interpreter name "
            "('python'), not an absolute path:\n  " + "\n  ".join(bad)
        )

    def test_settings_round_trips_through_json(self, initialized_repo):
        settings = _load_settings(initialized_repo)
        # Assert on REAL emitted content, not a dumps(loads()) identity that can
        # never raise: init emitting {} (hooks dropped) must RED. Re-encode with a
        # constant-rejecting loader so a Python-lenient Infinity/NaN — valid to
        # json.dumps but invalid strict JSON — is caught, not silently accepted.
        assert settings.get("hooks"), "init must emit a non-empty hooks block"

        def _reject_constant(token):
            raise AssertionError(f"non-strict-JSON constant emitted: {token}")

        reparsed = json.loads(json.dumps(settings), parse_constant=_reject_constant)
        assert reparsed["hooks"] == settings["hooks"]


class TestStatusLinePortability:
    """TP-150 (D-3): settings['statusLine'] must meet the same portability
    bar as the hooks. The TP-35 exec-form contract above walks only
    settings['hooks'], so statusLine drifted uncovered — the §1.11 (gate
    credibility) contract-coverage gap: a gate that inspects a subset of the
    surfaces it claims to govern. statusLine stays shell-form (a single
    `command` string) because Claude Code's statusLine schema is not
    confirmed to accept exec-form `args` (docs/external/cc-hook-protocol.md
    does not pin it); the full exec-form migration is Scope-out. What IS
    enforced: a bare (non-absolute) detected interpreter plus the
    ${CLAUDE_PROJECT_DIR} placeholder, so a relocated repo or a host without
    a `python` symlink still resolves the script.
    """

    def test_statusline_present_and_command_type(self, initialized_repo):
        settings = _load_settings(initialized_repo)
        sl = settings.get("statusLine")
        assert sl, "settings.json missing statusLine"
        assert sl.get("type") == "command", (
            f"statusLine type must be 'command'; got {sl.get('type')!r}"
        )

    def test_statusline_path_survives_a_space_bearing_project_dir(self, initialized_repo):
        """The placeholder must be QUOTED, which is orthogonal to the exec-form
        question the class docstring scopes out.

        Unquoted, ``sh -c`` word-splits a ``CLAUDE_PROJECT_DIR`` containing a
        space and the interpreter receives the pre-space fragment — reproduced
        end-to-end as ``Python: can't open file '/private/tmp/.../blind2/my'``.
        What stays genuinely unverified is only WHICH shell Claude Code
        dispatches with (zsh does not word-split unquoted expansions; POSIX
        ``sh`` does), so this pins the quoting, not the dispatcher.

        Asserts on exact MEMBERSHIP of the full path rather than a token count: a count breaks the
        moment ``python_cmd`` itself contains a space — precisely the Windows
        path shape ``_detect_python_command`` can return, and precisely the bug
        class this fix is about. A count here would be a born-weak gate that
        reds on a legitimate interpreter.
        """
        import shlex

        command = _load_settings(initialized_repo).get("statusLine", {}).get("command", "")
        expanded = command.replace("${CLAUDE_PROJECT_DIR}", "/tmp/my project")
        tokens = shlex.split(expanded)
        assert tokens, expanded
        # The path must arrive INTACT — i.e. the space-bearing project dir is
        # still inside the final token. `endswith("statusline.py")` is NOT a
        # discriminator here and looks like one: split at the space, the tail
        # `project/tools/cc/statusline.py` still ends in statusline.py, so that
        # assertion passes both before AND after the fix. Caught by earning the
        # red; it is the born-weak shape this repo treats as first-class.
        # Membership, not the last token: since DEF-508 the POSIX string
        # carries `|| echo '...'` after the script, so the path is no longer
        # last. Exact equality keeps the discrimination -- split at the space,
        # the fragments are `/tmp/my` and `project/tools/cc/statusline.py`,
        # and neither EQUALS the full path.
        # On an nt render the head is the Windows shim and the script is not
        # named at all (DEF-729): the same quoting question, the other file.
        expected_file = "statusline.cmd" if os.name == "nt" else "statusline.py"
        assert f"/tmp/my project/tools/cc/{expected_file}" in tokens, (
            "statusLine path word-split under a space-bearing CLAUDE_PROJECT_DIR: "
            f"tokens {tokens!r} from {expanded!r}"
        )

    def test_statusline_uses_project_dir_placeholder(self, initialized_repo):
        settings = _load_settings(initialized_repo)
        command = settings.get("statusLine", {}).get("command", "")
        assert "${CLAUDE_PROJECT_DIR}" in command, (
            "statusLine command must reference ${CLAUDE_PROJECT_DIR} for a "
            f"portable script path; got {command!r}"
        )
        expected_file = (
            "tools/cc/statusline.cmd" if os.name == "nt" else "tools/cc/statusline.py"
        )
        assert expected_file in command, (
            f"statusLine must invoke {expected_file} on this host; got {command!r}"
        )

    def test_statusline_interpreter_is_bare_and_not_absolute(self, initialized_repo):
        from espalier._venv import interpreter_site_token

        settings = _load_settings(initialized_repo)
        command = settings.get("statusLine", {}).get("command", "")
        # argv[0], or argv[1] behind the Windows shim -- the reader doctor and
        # the rewire share, so this test asks the same question they do.
        interp = interpreter_site_token(command)
        assert interp and not interp.startswith("/") and not os.path.isabs(interp), (
            f"statusLine interpreter {interp!r} must be a bare name, not an "
            "absolute path (TP-35 portability — breaks on relocated installs)."
        )
        assert interp in _PORTABLE_INTERPRETERS, (
            f"statusLine interpreter {interp!r} is not a portable bare "
            f"interpreter name. Expected one of {sorted(_PORTABLE_INTERPRETERS)}."
        )

    def test_statusline_fallback_is_posix_only(self):
        """DEF-508: the interpreter-missing fallback clause is rendered for a
        POSIX host and withheld for Windows, where the string may run under
        Windows PowerShell 5.1, which has no `||` -- a parse error there would
        blank the statusline on a HEALTHY install. On Windows the fallback
        lives in the deployed batch shim instead, wired as the command's head
        with the interpreter as its argument (DEF-729). Keyed on the render
        host because `init` renders settings.json on the host that runs it."""
        from espalier import cli

        posix = cli._statusline_command("python", posix=True)
        windows = cli._statusline_command("python", posix=False)
        plain = 'python "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.py"'
        assert windows == '"${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" python', windows
        assert " || " not in windows
        assert posix.startswith(plain + " || echo '"), posix
        assert cli.STATUSLINE_FALLBACK_TEXT in posix
        # The text sits inside single quotes in a `sh -c` string: a quote or a
        # shell metacharacter in it would end the clause early or expand.
        assert not set(cli.STATUSLINE_FALLBACK_TEXT) & set("'\"$`\\!"), (
            cli.STATUSLINE_FALLBACK_TEXT
        )
        assert cli.STATUSLINE_FALLBACK_TEXT.isascii()
        # No interpreter name: `--rewire-interpreter` swaps only argv[0], so a
        # name in the text would outlive the wiring it described.
        assert "python" not in cli.STATUSLINE_FALLBACK_TEXT.lower()
        # An OBSERVATION, not a diagnosis: the shell that prints this cannot
        # know why the command failed (interpreter gone, script gone,
        # placeholder unexpanded, partial deploy), so the text may claim
        # nothing about the hooks and must send the reader to the doc that
        # can diagnose. A bare `espalier <verb>` hint is banned separately
        # (tests/test_no_bare_espalier_hints.py: a fusion has no console
        # script).
        assert "hook" not in cli.STATUSLINE_FALLBACK_TEXT.lower()
        assert "docs/TROUBLESHOOTING.md" in cli.STATUSLINE_FALLBACK_TEXT

    def test_statusline_host_key_is_read_at_render_time(self, monkeypatch):
        """The render consults `os.name`, not a hard-wired `posix=`: a
        refactor that "makes it explicit" ships `||` to Windows PowerShell 5.1
        with the helper test above still green."""
        from espalier import cli

        # Through the seam, not `os.name`: pathlib reads `os.name` to pick
        # WindowsPath, which raises UnsupportedOperation on a POSIX box.
        monkeypatch.setattr(cli, "_render_host_is_posix", lambda: False)
        windows = cli._build_settings_json()["statusLine"]["command"]
        assert "||" not in windows
        assert windows.startswith('"${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" '), windows
        monkeypatch.setattr(cli, "_render_host_is_posix", lambda: True)
        assert " || echo '" in cli._build_settings_json()["statusLine"]["command"]

    @staticmethod
    def _batch_sources() -> list:
        """Every ``.cmd`` under tools/cc -- the population the mirror row, the
        sync, the wheel and the sdist admit, so the batch constraints bind a
        second shim on arrival and not only the one named today."""
        from espalier.cli import _deploy_source_path

        root = _deploy_source_path("tools/cc")
        return sorted(p for p in root.glob("*.cmd") if p.is_file())

    def test_every_batch_deploy_source_keeps_the_batch_constraints(self):
        """Any ``tools/cc/*.cmd``: LF-only on disk (the ``*.cmd text eol=lf``
        pin), ASCII (cmd.exe reads the OEM code page), ``@echo off`` first
        (the deployed marker goes on line 2 -- a line before it is echoed to
        stdout, the statusline's channel), and no label search: cmd.exe
        misreads a ``goto`` / ``call :label`` seek in an LF-only file. The
        source carries no label at all; the deployed copy's ``::`` marker
        line is one, tolerated exactly because nothing seeks it."""
        shims = self._batch_sources()
        assert shims, "no .cmd under tools/cc: the population went empty"
        for shim in shims:
            raw = shim.read_bytes()
            assert b"\r" not in raw, f"{shim.name} must be LF-only on disk"
            text = raw.decode("ascii")
            lines = text.splitlines()
            assert lines[0].strip().lower() == "@echo off", (shim.name, lines[0])
            code = [
                line for line in lines
                if line.strip() and not line.strip().lower().startswith("rem")
            ]
            assert not any(line.lstrip().startswith(":") for line in code), (shim.name, code)
            lowered = [line.lower() for line in code]
            assert not any("goto" in line for line in lowered), (shim.name, code)
            assert not any("call :" in line or "call:" in line for line in lowered), (shim.name, code)

    def test_the_statusline_shim_carries_the_same_fallback(self):
        """DEF-729: the shim is the one surface that runs without the wired
        interpreter, so its fallback text is `STATUSLINE_FALLBACK_TEXT`
        verbatim (one owner; the shim cannot import it), it forces exit 0 on
        that branch (Claude Code blanks a non-zero statusline), and it runs
        the interpreter it is handed, defaulting to `python`."""
        from espalier import cli
        from espalier.cli import _deploy_source_path
        from espalier.managed_paths import STATUSLINE_SHIM

        shim = _deploy_source_path(STATUSLINE_SHIM)
        assert shim in self._batch_sources()
        # encoding-locale-ok: a strict seven-bit decode IS the assertion -- cmd.exe reads a batch file in the OEM code page
        text = shim.read_text(encoding="ascii")
        lines = text.splitlines()
        assert cli.STATUSLINE_FALLBACK_TEXT in text
        fallback_line = next(line for line in lines if cli.STATUSLINE_FALLBACK_TEXT in line)
        assert "||" in fallback_line and "exit /b 0" in fallback_line, fallback_line
        assert "%~dp0statusline.py" in text, "runs the script beside itself"
        assert 'set "ESPALIER_PY=python"' in text, "defaults to python when handed nothing"

    @pytest.mark.skipif(os.name == "nt", reason="the fallback is withheld on Windows")
    def test_statusline_prints_the_fallback_when_its_interpreter_is_missing(
        self, initialized_repo
    ):
        """Driven through `sh -c`, the shell Claude Code hands the string to on
        macOS and Linux. With the wired interpreter swapped for a name that
        resolves nowhere the statusline prints the fallback line and exits 0
        (Claude Code blanks a statusline that exits non-zero or prints
        nothing, so both halves matter); with the interpreter as rendered it
        prints the real statusline and never the fallback."""
        from espalier import cli

        command = _load_settings(initialized_repo)["statusLine"]["command"]
        assert cli.STATUSLINE_FALLBACK_TEXT in command, command
        expanded = command.replace("${CLAUDE_PROJECT_DIR}", str(initialized_repo))
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(initialized_repo)}

        broken = cli._swap_interpreter_token(expanded, "definitely-not-a-python-qqq")
        assert broken != expanded
        result = subprocess.run(
            ["sh", "-c", broken], input="{}", capture_output=True, text=True,
            env=env, cwd=str(initialized_repo), timeout=30, encoding="utf-8",
        )
        assert result.returncode == 0, result
        assert result.stdout.strip() == cli.STATUSLINE_FALLBACK_TEXT, result

        healthy = subprocess.run(
            ["sh", "-c", expanded], input="{}", capture_output=True, text=True,
            env=env, cwd=str(initialized_repo), timeout=30, encoding="utf-8",
        )
        assert healthy.returncode == 0, healthy
        assert healthy.stdout.strip(), healthy
        assert cli.STATUSLINE_FALLBACK_TEXT not in healthy.stdout, healthy

        # A second cause the same line must stay TRUE for: the placeholder
        # reaching the shell unexpanded (the interpreter then opens
        # `/tools/cc/statusline.py` and fails). The text reports only that the
        # statusline did not run, so it is right here too -- the reason this
        # test drives a cause other than the missing interpreter.
        bare_env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        unexpanded = subprocess.run(
            ["sh", "-c", command], input="{}", capture_output=True, text=True,
            env=bare_env, cwd=str(initialized_repo), timeout=30, encoding="utf-8",
        )
        assert unexpanded.returncode == 0, unexpanded
        assert unexpanded.stdout.strip() == cli.STATUSLINE_FALLBACK_TEXT, unexpanded


# ── The wired interpreter must survive the shell that ran `init` ────────────


class TestWiredInterpreterIsAnInterpreter:
    """2-E: the SIBLING of ``TestWiredInterpreterSurvivesTheShell``, and it runs
    EVERYWHERE — no ``nt`` skipif.

    ⚠ The Windows walk's write-up proposed deleting that skipif. That would be
    wrong: it quotes only the first of its two reasons, and the second ("the
    constructed PATH would also have no python3.exe to link and would false-red")
    is independent and un-falsified, so deleting it produces a FALSE RED. The
    right move is a sibling that asks a question Windows can answer.

    That question is IDENTITY. The venv-shim test asks whether the wired name
    still RESOLVES once the shell is gone; this asks whether what it resolves to
    is a Python 3 at all — the property a Microsoft Store App Execution Alias
    satisfies the first of and fails the second. `.github/workflows/portability.yml`
    carries a real `windows-latest` leg and the suite has run there since
    2026-09-23 (Portability run 35943088158, the one that closed `DEF-921`), so
    this class's Windows reading is real.
    """

    def test_every_wired_interpreter_answers_as_python3(self, initialized_repo):
        settings = _load_settings(initialized_repo)
        wired = set()
        for _event, entry in _iter_hooks(settings):
            cmd = entry.get("command")
            if isinstance(cmd, str) and cmd.strip():
                wired.add(cmd.strip())
        assert wired, "init wired no interpreter at all — fixture is vacuous"

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                               / "tools" / "cc" / "hooks"))
        try:
            import _hook_utils
        finally:
            sys.path.pop(0)

        for name in sorted(wired):
            # Skip bare-PATH scripts: they run via shebang, not as a PATH name.
            if "${" in name or name.endswith((".py", ".sh")):
                continue
            _hook_utils._INTERPRETER_IDENTITY_MEMO.clear()
            try:
                ok = _hook_utils.interpreter_is_python3(name)
            finally:
                _hook_utils._INTERPRETER_IDENTITY_MEMO.clear()
            assert ok, (
                f"init wired interpreter {name!r}, which does not answer as "
                f"Python 3 on this host. Every hook spawned with it exits "
                f"outside the blocking range, so each guard fails OPEN while "
                f"init reports success."
            )

    def test_identity_probe_rejects_a_resolving_non_interpreter(self):
        """Discrimination, both directions — otherwise the assertion above could
        pass by always answering True. A real executable that is not Python must
        be rejected; this is the cheapest stand-in for a Store alias."""
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                               / "tools" / "cc" / "hooks"))
        try:
            import _hook_utils
        finally:
            sys.path.pop(0)
        non_interpreter = shutil.which("cmd" if os.name == "nt" else "ls")
        if not non_interpreter:
            pytest.skip("no non-interpreter executable available to probe")
        _hook_utils._INTERPRETER_IDENTITY_MEMO.clear()
        try:
            assert _hook_utils.interpreter_is_python3(non_interpreter) is False
            assert _hook_utils.interpreter_is_python3(sys.executable) is True
        finally:
            _hook_utils._INTERPRETER_IDENTITY_MEMO.clear()


def _venv_bin(venv_dir: Path) -> Path:
    """bin/ on POSIX, Scripts/ on Windows."""
    return venv_dir / ("Scripts" if sys.platform == "win32" else "bin")


def _base_interpreter() -> Path:
    """The interpreter a fixture venv is built FROM: the base install when the
    test runner is itself a venv python (`sys.prefix != sys.base_prefix`),
    else `sys.executable`. See `venv_wired_repo` for why a venv python will
    not do on CPython 3.10."""
    if sys.prefix == sys.base_prefix:
        return Path(sys.executable)
    major, minor = sys.version_info[:2]
    base = Path(sys.base_prefix)
    for candidate in (
        base / "bin" / f"python{major}.{minor}",
        base / "bin" / "python3",
        base / "python.exe",
    ):
        if candidate.exists():
            return candidate
    return Path(sys.executable)


@pytest.mark.skipif(
    os.name == "nt",
    reason=(
        "On Windows a bare `python` legitimately resolves outside a venv, so "
        "there is no red to earn; the constructed PATH would also have no "
        "python3.exe to link and would false-red."
    ),
)
class TestWiredInterpreterSurvivesTheShell:
    """The interpreter `init` writes into settings.json must still resolve
    once the shell that ran `init` is gone.

    An ACTIVATED virtualenv puts its own ``bin/`` first on PATH, and that
    directory holds BOTH a ``python`` and a ``python3`` shim regardless of
    which name created it. ``_detect_python_command`` probes PATH, finds
    ``python``, and wires it into all 13 interpreter sites. But settings.json
    outlives that shell — Claude Code is routinely launched from another
    terminal, an IDE, or the desktop app — and on a host with no bare
    ``python`` the shim is gone, so every hook fails to spawn and every
    blocking guard fails OPEN.

    ``test_command_is_bare_interpreter`` above cannot catch this: it asserts
    only MEMBERSHIP in {python, python3}, and the broken value satisfies it.
    This asserts RESOLVABILITY instead.

    The PATH is CONSTRUCTED here, never inherited. An inherited PATH makes the
    verdict a property of the HOST rather than of ``cli.py`` — on a runner that
    supplies a bare ``python`` outside any venv, the venv-stripped-but-inherited
    PATH still resolves it and this assertion would pass on a fully disarmed
    tree.
    """

    @pytest.fixture(params=[(), ("--copies",)], ids=["symlinked", "copies"])
    def venv_wired_repo(self, request, tmp_path: Path):
        """Run `init` with a venv first on a constructed PATH.

        Both venv layouts are exercised: the POSIX default (symlinked
        interpreter) and ``--copies`` (the Windows shape, and the only case
        where a naive file-containment check would fire).
        """
        venv_dir = tmp_path / "venv"
        # Built from the BASE interpreter, never from a venv python, and
        # `--without-pip` (the fixture needs `bin/python` on a constructed PATH
        # and nothing else). On CPython 3.10 a venv's `sys._base_executable` is
        # the venv's own python, so `-m venv --copies` run from inside a venv --
        # uv's ephemeral one, the release gate's, an IDE's -- writes
        # `home = <that venv>/bin` into the new venv: its copied python answers
        # `--version` and cannot import anything (`<no Python frame>`), so
        # `ensurepip` failed here, and with pip skipped the detector's identity
        # probe crashed and its permissive branch wired the dead `python`
        # (measured 2026-09-22 in a fresh clone on the floor; 3.11+ record the
        # real base). The probe below turns that shape into a loud setup error.
        base = _base_interpreter()
        subprocess.run(
            [str(base), "-m", "venv", "--without-pip", *request.param, str(venv_dir)],
            check=True, capture_output=True,
        )
        vpy = _venv_bin(venv_dir) / ("python.exe" if sys.platform == "win32" else "python")
        probe = subprocess.run(
            [str(vpy), "-c", "import sys"], capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        assert probe.returncode == 0, (
            f"the fixture venv's python cannot start ({probe.stderr.strip()[-160:]}); "
            f"built from {base} -- a copies venv made from a venv python on CPython < 3.11"
        )

        # The non-venv leg of PATH, built explicitly so the assertion below
        # tests cli.py and not the host. It must carry every external the
        # child needs -- `git` included.
        fakebin = tmp_path / "fakebin"
        fakebin.mkdir()
        os.symlink(Path(os.path.realpath(sys.executable)), fakebin / "python3")
        git_path = shutil.which("git")
        assert git_path, "git must be on PATH to build the constructed leg"
        os.symlink(git_path, fakebin / "git")

        venv_bin = _venv_bin(venv_dir)
        env = {**os.environ, "PATH": f"{venv_bin}{os.pathsep}{fakebin}"}
        env.pop("VIRTUAL_ENV", None)

        target = tmp_path / "repo"
        target.mkdir()
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(target)],
            check=True, env=env, capture_output=True,
        )
        subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(target)],
            check=True, cwd=REPO_ROOT, env=env, capture_output=True,
        )
        # PATH with the venv REMOVED -- what a later shell actually has.
        return target, str(fakebin)

    def test_every_wired_interpreter_resolves_without_the_venv(
        self, venv_wired_repo
    ):
        """All 13 sites -- 12 hook commands + statusLine -- must resolve on a
        PATH that no longer contains the venv."""
        target, stripped_path = venv_wired_repo
        settings = _load_settings(target)

        sites: list[tuple[str, str]] = [
            (event, hook.get("command", ""))
            for event, hook in _iter_hooks(settings)
        ]
        status_cmd = settings.get("statusLine", {}).get("command", "")
        if status_cmd:
            # Shell-string form. First token is the interpreter; handle a
            # quoted path with spaces without shlex, which mangles backslashes
            # in posix mode (see tools/cc/hooks/session_start.py).
            cmd = status_cmd.strip()
            if cmd[:1] in ("'", '"'):
                end = cmd.find(cmd[0], 1)
                interp = cmd[1:end] if end > 0 else cmd[1:]
            else:
                interp = cmd.split(None, 1)[0]
            sites.append(("statusLine", interp))

        assert sites, "no interpreter sites found in settings.json"

        unresolved = [
            (where, name) for where, name in sites
            if shutil.which(name, path=stripped_path) is None
        ]
        assert not unresolved, (
            "settings.json wires an interpreter that does NOT resolve once the "
            "shell that ran `init` is gone -- every hook exits before it can "
            "run and every blocking guard fails OPEN.\n"
            + "\n".join(f"  {where}: {name!r}" for where, name in unresolved)
            + f"\n(PATH without the venv: {stripped_path})"
        )
