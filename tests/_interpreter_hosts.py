"""Stubbed-PATH interpreter hosts: the shared oracle for choosing an interpreter.

Two host shapes every interpreter-choosing surface must land on a working
Python under (``task-packs/FORWARD_LEDGER.md``, the class on picking the
interpreter by what it answers):

* ``STORE_PYTHON3`` -- ``python3`` is the Microsoft Store App Execution Alias
  stub and ``python`` is a working interpreter.
* ``LAUNCHER_ONLY`` -- ``python`` and ``python3`` are both Store stubs and
  only the ``py`` launcher works: the python.org full installer, which leaves
  PATH alone unless its "Add python.exe to PATH" box is ticked.
* ``PYTHON3_ONLY`` -- only ``python3`` answers (``python`` and ``py`` are
  stubs that do not): stock macOS with a newer ``python3``, the maintainer's
  own host. Without it nothing reaches a chooser's ``python3`` candidate,
  because the other two shapes are decided by an earlier one.

Each shape is built in one of two flavours, because the two kinds of consumer
resolve a name differently:

* ``NATIVE`` -- what ``shutil.which`` and ``subprocess`` resolve on this OS:
  a ``.cmd`` file on Windows (found through ``PATHEXT``), an executable ``sh``
  script elsewhere.
* ``SH`` -- executable ``sh`` scripts for a bash that resolves names itself.
  Git Bash runs a shebang script and does not consult ``PATHEXT``, so a
  ``.cmd`` stub is invisible to it.

Every working stub forwards to ``sys.executable``, so a probe that runs one
gets a real banner and real behaviour. The ``py`` stub first drops one
leading launcher version flag (``-3``, ``-3.11``, ``-3.11-64``), as the real
launcher consumes it before the interpreter starts. The Store stub prints the
alias's not-found text on stderr and exits 9009, which a POSIX shell reports
as 49 (9009 mod 256): the exit Git Bash showed against the real App Installer
stub on 2026-10-01.

``HOOK_PYTHON`` is the one name here that is not a stub: the interpreter a test
spawns a hook (or any tools/cc script) with when it asserts on the spawned
process's parent (the comment at its definition; a contract pins the form).
"""
from __future__ import annotations

import os
import shlex
import stat
import sys
from pathlib import Path

STORE_PYTHON3 = "store_python3"
LAUNCHER_ONLY = "launcher_only"
PYTHON3_ONLY = "python3_only"
SHAPES = (STORE_PYTHON3, LAUNCHER_ONLY, PYTHON3_ONLY)

NATIVE = "native"
SH = "sh"

# The interpreter a test spawns a HOOK (or any tools/cc script) with when it
# asserts on the spawned process's parent. A Windows venv's ``python.exe`` is a
# redirector that launches the base interpreter as its own child, so a hook
# spawned through ``sys.executable`` there records the redirector's pid, not the
# test's, and every run gets a fresh one (the Windows box, 2026-10-06:
# ``tests/test_hooks.py::TestSessionMarkerEndToEnd``'s clear-retire row red with
# ``assert not True``); ``py.exe``, a launcher that runs the interpreter as its
# child, reads as the same shape (not measured). CPython's ``multiprocessing``
# bypasses the redirector the same way on Windows in a venv (bpo-35797:
# ``popen_spawn_win32.py`` launches ``sys._base_executable``). Equal to
# ``sys.executable`` everywhere else: a POSIX venv runs the interpreter through a
# symlink with no process between, and on 3.10 its ``_base_executable`` is the
# venv path itself (alternate-name resolution landed in 3.11, bpo-46028); a
# ``--copies`` POSIX venv records an empty string (gh-96861) and an embedded or
# frozen interpreter none, hence the fallback. What the base interpreter cannot
# see is the venv's site-packages: the hooks are stdlib-only except the ``tomli``
# fallback ``_hook_utils._toml_parser`` takes below 3.11, so a 3.10 venv's hook
# run under it reads ``espalier.toml`` through the regex arm. The pin in
# ``tests/test_test_suite_contract.py`` keeps every module that asserts on a
# parent pid on this constant.
HOOK_PYTHON = getattr(sys, "_base_executable", None) or sys.executable

#: The alias's not-found text, as the real stub prints it on stderr.
STORE_STUB_TEXT = (
    "Python was not found; run without arguments to install from the "
    "Microsoft Store, or disable this shortcut from Settings > Manage App "
    "Execution Aliases."
)
STORE_STUB_EXIT_WINDOWS = 9009
STORE_STUB_EXIT_POSIX = STORE_STUB_EXIT_WINDOWS % 256

#: Which names work and which are Store stubs, per shape.
WORKING_NAMES = {
    STORE_PYTHON3: ("python",), LAUNCHER_ONLY: ("py",), PYTHON3_ONLY: ("python3",),
}
STUBBED_NAMES = {
    STORE_PYTHON3: ("python3",), LAUNCHER_ONLY: ("python", "python3"),
    PYTHON3_ONLY: ("python", "py"),
}

#: A launcher version flag the ``py`` stub consumes, as a Python regex and as
#: the ``case`` patterns its ``sh`` form matches. This is the REAL launcher's
#: grammar (``-2`` included), deliberately wider than the oracle's ``-3``-only
#: pattern, so the stub models the machine rather than the code under test.
LAUNCHER_FLAG_RE = r"-[23](\.\d+)?(-(32|64|arm64))?"
_SH_LAUNCHER_CASE = "-2|-3|-2.*|-3.*|-2-*|-3-*"

_PY_FORWARDER = (
    "import re, subprocess, sys\n"
    "args = sys.argv[1:]\n"
    f"if args and re.fullmatch(r'{LAUNCHER_FLAG_RE}', args[0]):\n"
    "    args = args[1:]\n"
    "sys.exit(subprocess.call([sys.executable, *args]))\n"
)


def _write(path: Path, body: str, *, crlf: bool) -> Path:
    newline = "\r\n" if crlf else "\n"
    path.write_bytes(newline.join(body.splitlines()).encode("utf-8") + newline.encode("ascii"))
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _cmd_stub(bin_dir: Path, name: str, *, working: bool) -> Path:
    exe = sys.executable
    if not working:
        # `>` is a redirection to cmd.exe; `^>` prints it.
        text = STORE_STUB_TEXT.replace(">", "^>")
        body = f"@echo {text} 1>&2\n@exit /b {STORE_STUB_EXIT_WINDOWS}"
    elif name == "py":
        forwarder = _write(bin_dir / "_py_forwarder.py", _PY_FORWARDER, crlf=False)
        body = f'@"{exe}" "{forwarder}" %*'
    else:
        body = f'@"{exe}" %*'
    return _write(bin_dir / f"{name}.cmd", body, crlf=True)


def _sh_stub(bin_dir: Path, name: str, *, working: bool) -> Path:
    exe = shlex.quote(Path(sys.executable).as_posix())
    if not working:
        body = (
            "#!/bin/sh\n"
            f"echo {shlex.quote(STORE_STUB_TEXT)} >&2\n"
            f"exit {STORE_STUB_EXIT_POSIX}"
        )
    elif name == "py":
        body = (
            "#!/bin/sh\n"
            f'case "$1" in {_SH_LAUNCHER_CASE}) shift ;; esac\n'
            f'exec {exe} "$@"'
        )
    else:
        body = f'#!/bin/sh\nexec {exe} "$@"'
    return _write(bin_dir / name, body, crlf=False)


_PY_OLD_DEFAULT_FORWARDER = (
    "import re, subprocess, sys\n"
    "args = sys.argv[1:]\n"
    f"if args and re.fullmatch(r'{LAUNCHER_FLAG_RE}', args[0]):\n"
    "    sys.exit(subprocess.call([sys.executable, *args[1:]]))\n"
    "if args == ['--version']:\n"
    "    print('Python 3.9.6')\n"
    "    sys.exit(0)\n"
    "sys.exit(subprocess.call([sys.executable, *args]))\n"
)


def build_old_default_launcher(root: Path) -> Path:
    """A launcher-only host whose ``py`` DEFAULT is a 3.9 (a ``PY_PYTHON=3.9``
    setting, or a py.ini default) while ``py -3`` runs this interpreter: the
    one host where a bare ``py`` probe and a ``py -3`` probe disagree, so two
    readers of one settings site that spell it differently disagree too.
    Native flavour only."""
    bin_dir = root / "old-default-launcher"
    bin_dir.mkdir(parents=True)
    forwarder = _write(bin_dir / "_py_old_default.py", _PY_OLD_DEFAULT_FORWARDER, crlf=False)
    if os.name == "nt":
        _write(bin_dir / "py.cmd", f'@"{sys.executable}" "{forwarder}" %*', crlf=True)
        for name in ("python", "python3"):
            _cmd_stub(bin_dir, name, working=False)
    else:
        exe = shlex.quote(sys.executable)
        _write(bin_dir / "py", f'#!/bin/sh\nexec {exe} {shlex.quote(str(forwarder))} "$@"', crlf=False)
        for name in ("python", "python3"):
            _sh_stub(bin_dir, name, working=False)
    return bin_dir


def build_host(root: Path, shape: str, flavour: str = NATIVE) -> Path:
    """Build ``shape`` under ``root`` in ``flavour`` and return its bin dir."""
    if shape not in SHAPES:
        raise ValueError(f"unknown host shape {shape!r}; expected one of {SHAPES}")
    if flavour not in (NATIVE, SH):
        raise ValueError(f"unknown flavour {flavour!r}; expected {NATIVE!r} or {SH!r}")
    bin_dir = root / f"{shape}-{flavour}"
    bin_dir.mkdir(parents=True)
    write = _cmd_stub if (flavour == NATIVE and os.name == "nt") else _sh_stub
    for name in STUBBED_NAMES[shape]:
        write(bin_dir, name, working=False)
    for name in WORKING_NAMES[shape]:
        write(bin_dir, name, working=True)
    return bin_dir


def shell_resolver_line(*, espalier: bool = False) -> str:
    """The ONE shell line every shipped command body and workflow persist
    command uses to pick an interpreter: the first of ``python3``, ``python``
    and ``py -3`` that ANSWERS a Python clearing the floor (and, for a
    persist command, imports espalier), or a loud stop when none does.

    ``command -v`` asks whether a name resolves, and a Store alias resolves:
    the line it replaced ran the stub (exit 49 under Git Bash) on a Windows
    host whose ``python3`` is the App Execution Alias. ``$PY`` is used
    unquoted after it, so ``py -3`` runs as two words. The order is the
    rendered invocation rule's (``python3``, then ``python``, then the
    launcher), so a session following the rule by hand and a body running
    this line pick the same interpreter where both names answer.
    ``python3`` is single-quoted only because the operator-doc portability
    contract bans the name followed by a space. Rendered from the floor, so
    a raised ``requires-python`` moves every site with it.
    """
    from espalier._python_floor import MIN_PYTHON, floor_text

    imports = "sys, espalier" if espalier else "sys"
    needs = " with espalier" if espalier else ""
    return (
        f"PY=; for c in 'python3' python 'py -3'; do $c -c 'import {imports}; "
        f"sys.exit(sys.version_info < {tuple(MIN_PYTHON)!r})' >/dev/null 2>&1 "
        "&& { PY=$c; break; }; done; [ -n \"$PY\" ] || { echo 'no Python "
        f"{floor_text()}+{needs} answered to python3, python or py -3' >&2; exit 1; }}"
    )


def path_with(bin_dir: Path) -> str:
    """A PATH value with ``bin_dir`` ahead of this process's own PATH, so the
    stubbed names shadow any real interpreter of the same name."""
    return str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
