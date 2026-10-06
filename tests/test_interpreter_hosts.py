"""The stubbed-PATH interpreter hosts behave like the hosts they stand for.

Pins the shared oracle every interpreter-choosing surface is driven under,
because a stub that drifted from the real host would let a surface pass the
fixture and fail the machine. Also pins the one shell resolver line the
shipped bodies carry, against drift and against the Store alias. Each stub is driven through
the same lookup its consumers use: `shutil.which` plus `subprocess` for the
native flavour, a POSIX bash for the `sh` flavour.
"""
# slow-exempt: about twenty short child processes of the running interpreter through stub launchers, measured 0.9s on Windows
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests import _interpreter_hosts as hosts

def _posix_bash() -> str | None:
    """A real POSIX bash: ``/bin/bash`` off Windows; on Windows, Git Bash found
    beside ``git`` -- never a bare ``bash``, which a Windows subprocess resolves
    through System32 to the WSL shim. Git Bash is the shell the defect lived
    in, so the Windows dev box drives the `sh` flavour too, not only CI."""
    if os.name != "nt":
        return "/bin/bash" if Path("/bin/bash").exists() else None
    git = shutil.which("git")
    if not git:
        return None
    for root in Path(git).resolve().parents:
        for cand in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
            if cand.is_file():
                return str(cand)
    return None


_POSIX_BASH = _posix_bash()
_STORE_EXIT = (
    hosts.STORE_STUB_EXIT_WINDOWS if os.name == "nt" else hosts.STORE_STUB_EXIT_POSIX
)


def _run_native(bin_dir: Path, name: str, *args: str) -> subprocess.CompletedProcess:
    resolved = shutil.which(name, path=str(bin_dir))
    assert resolved, f"{name} does not resolve in {bin_dir}: {sorted(os.listdir(bin_dir))}"
    return subprocess.run(
        [resolved, *args], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=30,
    )


def _run_bash(bin_dir: Path, script: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PATH": hosts.path_with(bin_dir)}
    return subprocess.run(
        [_POSIX_BASH, "-c", script], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30, env=env,
    )


class TestNativeFlavour:
    @pytest.mark.parametrize("shape", hosts.SHAPES)
    def test_every_working_name_answers_with_this_interpreter(self, tmp_path, shape):
        bin_dir = hosts.build_host(tmp_path, shape)
        for name in hosts.WORKING_NAMES[shape]:
            args = ("-3", "-c") if name == "py" else ("-c",)
            got = _run_native(bin_dir, name, *args, "import sys; print(sys.version_info[0])")
            assert (got.returncode, got.stdout.strip()) == (0, "3"), (name, got)

    @pytest.mark.parametrize("shape", hosts.SHAPES)
    def test_every_stubbed_name_fails_like_the_store_alias(self, tmp_path, shape):
        bin_dir = hosts.build_host(tmp_path, shape)
        for name in hosts.STUBBED_NAMES[shape]:
            got = _run_native(bin_dir, name, "--version")
            assert got.returncode == _STORE_EXIT, (name, got)
            assert got.stdout == "", (name, got.stdout)
            assert "Microsoft Store" in got.stderr, (name, got.stderr)

    @pytest.mark.parametrize("flag", ["-3", "-3.11", "-3.11-64"])
    def test_the_launcher_consumes_one_version_flag(self, tmp_path, flag):
        bin_dir = hosts.build_host(tmp_path, hosts.LAUNCHER_ONLY)
        got = _run_native(bin_dir, "py", flag, "-c", "import sys; print(sys.argv[1:])", "x")
        assert (got.returncode, got.stdout.strip()) == (0, "['x']"), got

    def test_the_launcher_without_a_flag_still_runs(self, tmp_path):
        bin_dir = hosts.build_host(tmp_path, hosts.LAUNCHER_ONLY)
        got = _run_native(bin_dir, "py", "--version")
        assert got.returncode == 0 and (got.stdout + got.stderr).startswith("Python 3."), got

    def test_the_old_default_launcher_disagrees_with_its_flag(self, tmp_path):
        bin_dir = hosts.build_old_default_launcher(tmp_path)
        assert _run_native(bin_dir, "py", "--version").stdout.strip() == "Python 3.9.6"
        got = _run_native(bin_dir, "py", "-3", "-c", "import sys; print(sys.version_info >= (3, 10))")
        assert (got.returncode, got.stdout.strip()) == (0, "True"), got

    def test_an_unknown_shape_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="unknown host shape"):
            hosts.build_host(tmp_path, "both_missing")


@pytest.mark.skipif(
    not _POSIX_BASH,
    reason="the sh flavour needs a POSIX bash (/bin/bash, or Git Bash on Windows)",
)
class TestShFlavour:
    @pytest.mark.parametrize("shape", hosts.SHAPES)
    def test_bash_sees_the_shape(self, tmp_path, shape):
        bin_dir = hosts.build_host(tmp_path, shape, hosts.SH)
        for name in hosts.STUBBED_NAMES[shape]:
            got = _run_bash(bin_dir, f"{name} --version")
            assert got.returncode == hosts.STORE_STUB_EXIT_POSIX, (name, got)
            assert "Microsoft Store" in got.stderr, (name, got.stderr)
        for name in hosts.WORKING_NAMES[shape]:
            head = "py -3" if name == "py" else name
            got = _run_bash(bin_dir, f"{head} -c 'import sys; print(sys.version_info[0])'")
            assert (got.returncode, got.stdout.strip()) == (0, "3"), (name, got)


def test_working_stubs_forward_to_the_running_interpreter(tmp_path):
    bin_dir = hosts.build_host(tmp_path, hosts.STORE_PYTHON3)
    got = _run_native(bin_dir, "python", "-c", "import sys; print(sys.executable)")
    assert got.returncode == 0, got
    assert os.path.normcase(os.path.realpath(got.stdout.strip())) == os.path.normcase(
        os.path.realpath(sys.executable)
    ), got.stdout


# --- the shell resolver line --------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
#: ANY shell assignment to PY: the canonical line opens `PY=;`, and every
#: other spelling (`PY=python3;`, `PY="python3"`, `PY=$(command -v ...)`) is a
#: site the census must see and the canonical-line test must red on.
_RESOLVER_SITE = re.compile(r"\bPY=[^\n`]*")
#: How a workflow template literal ends a line: a backslash-n, then the backtick.
_JS_LINE_END = "\\n"


def _resolver_sites() -> list[tuple[str, int, str]]:
    """Every resolver line a shipped command body, skill, agent or workflow
    body carries, derived by scanning `.claude/` (the mirrors are byte copies
    the mirror-parity tests hold to it)."""
    sites = []
    for path in sorted((_REPO_ROOT / ".claude").rglob("*")):
        if path.suffix not in (".md", ".js") or not path.is_file():
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = _RESOLVER_SITE.search(line)
            if m:
                text = m.group(0)
                if text.endswith(_JS_LINE_END):
                    text = text[: -len(_JS_LINE_END)]
                sites.append((path.relative_to(_REPO_ROOT).as_posix(), n, text))
    return sites


class TestShellResolverLine:
    """The six shipped shell lines that pick an interpreter are one line, and
    it keeps the first candidate that ANSWERS a Python clearing the floor."""

    def test_the_derivation_sees_all_six_sites(self):
        sites = _resolver_sites()
        assert len(sites) >= 6, sites  # preflight Steps 4, 7, 8 and three persist heads

    def test_every_site_carries_the_canonical_line(self):
        canonical = {hosts.shell_resolver_line(), hosts.shell_resolver_line(espalier=True)}
        drift = [
            f"{rel}:{n}: {text[:70]}"
            for rel, n, text in _resolver_sites() if text not in canonical
        ]
        assert not drift, (
            "a resolver line drifted from tests/_interpreter_hosts.py::shell_resolver_line:\n  "
            + "\n  ".join(drift)
        )

    def test_every_persist_command_requires_espalier(self):
        persist = [text for rel, _, text in _resolver_sites() if rel.endswith(".js")]
        assert len(persist) >= 3, persist
        assert set(persist) == {hosts.shell_resolver_line(espalier=True)}, persist

    def test_the_line_states_the_floor_the_package_declares(self):
        from espalier._python_floor import MIN_PYTHON, floor_text

        for line in (hosts.shell_resolver_line(), hosts.shell_resolver_line(espalier=True)):
            m = re.search(r"sys\.version_info < \((\d+), (\d+)\)", line)
            assert m and (int(m.group(1)), int(m.group(2))) == tuple(MIN_PYTHON), line
            assert f"no Python {floor_text()}+" in line, line

    def test_no_body_quotes_the_resolved_interpreter(self):
        """`$PY` runs unquoted: quoted, `py -3` is one word naming no program,
        and only a launcher-only host (no required CI cell) would show it. A
        linter's quote-your-variables advice is the likeliest way back."""
        canonical = (hosts.shell_resolver_line(), hosts.shell_resolver_line(espalier=True))
        quoted = []
        for path in sorted((_REPO_ROOT / ".claude").rglob("*")):
            if path.suffix not in (".md", ".js") or not path.is_file():
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for c in canonical:
                    line = line.replace(c, "")
                if '"$PY"' in line:
                    quoted.append(f"{path.relative_to(_REPO_ROOT).as_posix()}:{n}: {line.strip()[:70]}")
        assert not quoted, "a body quotes the resolved interpreter:\n  " + "\n  ".join(quoted)

    def test_the_line_keeps_the_operator_doc_portability_contract(self):
        for line in (hosts.shell_resolver_line(), hosts.shell_resolver_line(espalier=True)):
            assert "python3 " not in line and "/tmp/" not in line, line


@pytest.mark.skipif(
    not _POSIX_BASH,
    reason="the resolver line is driven under a POSIX bash; a Windows subprocess resolves a bare `bash` to the WSL shim",
)
class TestShellResolverLineRuns:
    _REPORT = "\necho \"PY=[$PY]\"\n$PY -c 'import sys; print(sys.version_info[0])'"

    @pytest.mark.parametrize("shape,picked", [
        (hosts.STORE_PYTHON3, "python"), (hosts.LAUNCHER_ONLY, "py -3"),
        (hosts.PYTHON3_ONLY, "python3"),
    ])
    def test_every_extracted_site_picks_the_interpreter_that_answers(self, tmp_path, shape, picked):
        bin_dir = hosts.build_host(tmp_path, shape, hosts.SH)
        for rel, n, text in _resolver_sites():
            got = _run_bash(bin_dir, text + self._REPORT)
            assert got.returncode == 0, (rel, n, got)
            assert got.stdout.splitlines() == [f"PY=[{picked}]", "3"], (rel, n, got.stdout)

    def test_nothing_that_answers_is_a_loud_stop(self, tmp_path):
        """The line needs nothing but shell builtins beyond the candidates, so a
        PATH holding one empty directory is a host where none answers."""
        empty = tmp_path / "empty"
        empty.mkdir()
        got = subprocess.run(
            [_POSIX_BASH, "-c", hosts.shell_resolver_line() + "\necho ran-on"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, env={**os.environ, "PATH": str(empty)},
        )
        assert got.returncode == 1 and "ran-on" not in got.stdout, got
        assert "no Python" in got.stderr, got.stderr


class TestHookPython:
    """``HOOK_PYTHON`` fronts every hook spawn in the modules that assert on a
    spawned process's parent; a stale base executable (a pruned uv or pyenv
    base) would fail each of them with a FileNotFoundError naming no constant."""

    def test_hook_python_answers_as_this_interpreters_python_3(self):
        got = subprocess.run(
            [hosts.HOOK_PYTHON, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        assert got.returncode == 0, (hosts.HOOK_PYTHON, got.stderr)
        assert got.stdout.strip() == "%d.%d" % sys.version_info[:2], (hosts.HOOK_PYTHON, got.stdout)
