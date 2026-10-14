"""The one writer of executable stand-ins in the suite: a stub is written, made
executable, and executed once before any test times it.

Why: the first exec of a freshly written executable is slow on macOS and slower
under load (the system checks a new file before it runs), and the production
probes these stubs stand in for give an interpreter one or two seconds to
answer (`session_start._probe_engine`, `cli._detect_python_command`,
`_python_floor`, `doctor`, `_hook_utils`). Measured 2026-10-14 on the 8 GB Air,
the hook's engine probe of fresh `/bin/sh` stubs interleaved under 8 busy
processes: cold, median 0.159 s with 1 of 40 past the 1.0 s cap (13 of 30 in an
earlier run); executed once beforehand, median 0.012 s and 0 of 40. A test whose
subject is parsing or a choice of candidate then failed whenever a probe met a
cold file under a loaded tier (the `tests/README.md` races line, 2026-09-23 and
2026-10-14, and two `TestEngineLine` reds in a fresh worktree's tier).

The warm-up leaves no trace: the stub's first line after its shebang (after
`@echo off` for a `.cmd`) is a guard that exits 0 when
:data:`STUB_WARMUP_ENV` is set, and the warm-up runs with it set, so a stub
that records its calls, writes a marker or counts invocations records nothing
until a test runs it. A stub whose subject is slowness or the timeout itself
stays cold: it does not come through here, and
`tests/test_stub_warmup.py` exempts it by name.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

#: The variable the warm-up sets; no probe or test sets it, so a real run of
#: the stub always reaches its body.
STUB_WARMUP_ENV = "ESPALIER_STUB_WARMUP"
_SH_GUARD = f'[ -n "${{{STUB_WARMUP_ENV}:-}}" ] && exit 0'  # `:-`: safe under a `sh -u` shebang
_CMD_GUARD = f"@if defined {STUB_WARMUP_ENV} exit /b 0"

#: What a refused stub does instead.
_WAY_OUT = ("write a /bin/sh stand-in that execs the interpreter, or run a Python one through "
            "sys.executable without making it executable (tests/_interpreter_hosts.py does both); "
            "a stub whose subject is timing or a failed exec is exempted by name in "
            "tests/test_stub_warmup.py::EXEMPT")

#: Every stub this module warmed, in order (the contract reads it).
WARMED: list[Path] = []


def _is_cmd(path: Path) -> bool:
    return path.suffix.lower() in (".cmd", ".bat")


def _guarded(path: Path, body: str) -> str:
    lines = body.splitlines()
    if _is_cmd(path):
        at = 1 if lines and lines[0].strip().lower() == "@echo off" else 0
        return "\n".join(lines[:at] + [_CMD_GUARD] + lines[at:])
    if not lines or not lines[0].startswith("#!"):
        raise ValueError(f"{path.name}: a stub runs as its own program and needs a shebang; {_WAY_OUT}")
    shell = lines[0][2:].strip().split()
    if not shell or Path(shell[0]).name not in ("sh", "bash", "dash", "zsh"):
        raise ValueError(f"{path.name}: the warm-up guard is shell; {lines[0]!r} is not a shell; {_WAY_OUT}")
    return "\n".join(lines[:1] + [_SH_GUARD] + lines[1:])


def write_stub(path: Path, body: str, *, crlf: bool = False, encoding: str = "utf-8") -> Path:
    """Write ``body`` to ``path`` as an executable stand-in, with the warm-up
    guard, then execute it once with the guard set where this platform can run
    it (a shell script off Windows, a ``.cmd``/``.bat`` on it). Returns ``path``."""
    newline = "\r\n" if crlf else "\n"
    text = _guarded(path, body)
    path.write_bytes(newline.join(text.splitlines()).encode(encoding) + newline.encode("ascii"))
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    if _is_cmd(path) == (os.name == "nt"):
        # Below the suite's 60 s per-test ceiling, so a hung warm-up fails here, by name.
        done = subprocess.run([str(path)], capture_output=True, timeout=30,
                              env={**os.environ, STUB_WARMUP_ENV: "1"})
        if done.returncode != 0 or done.stdout or done.stderr:
            raise RuntimeError(f"{path.name}: the warm-up reached the stub's body "
                               f"(exit {done.returncode}, out {done.stdout[:80]!r}, err {done.stderr[:80]!r})")
        WARMED.append(path)
    return path
