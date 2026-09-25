"""Earn-the-gate fixture for ``espalier.scanners.encoding_contracts``.

Each function below uses one text-mode I/O shape the scanner is expected to
flag: the builtin open family, a Path-style ``.open()``, ``.read_text()`` /
``.write_text()`` (keyword or positional encoding), a text-mode ``subprocess``
call (the module under its name, under an alias, or a function imported by
name), a text-mode ``tempfile`` and an ``io.TextIOWrapper`` -- each either
omitting the encoding (MISSING) or pinning a value that is not UTF-8
(NOT_UTF8). Real code pins ``encoding="utf-8"`` everywhere; this file's job is
to be the corpus the scanner proves it can see. Without these positives, a
regression that quietly disabled a detection branch would leave the scanner
reporting "clean" against a clean repo with no failing test.

The two ``historic_*`` functions reproduce the shapes the pre-existing gates
caught before this scanner existed: the pre-fix body of
``espalier.analyze.detect_git_conventions`` (TP-189 XPLAT-1, pinned by
``tests/test_git_conventions_encoding.py``) and the two present-but-wrong
``encoding=`` values ``tests/test_contracts.py::TestSubprocessEncodingPinned``
rejects (SOUND-3). The ``aliased_*`` functions reproduce the shape the first
cut of this scanner could not see (two live sites in ``tests/test_hooks.py``,
found by the failure-mode review of 2026-09-14), and ``production_path_open``
the one production site the code review found the same day.

The earn-the-gate test in tests/test_scanner_encoding_contracts.py calls
``_scan_file`` on this path directly (``tests/fixtures/`` is exempt from the
live walk) and asserts the exact finding count and shape distribution.

Discoverability: prefixed `test_` so `pathlib.Path.rglob('test_*.py')`
(the convention pytest's collector uses internally) collects this file. The
file contains no `def test_*` functions; pytest collects no tests from it.
"""
from __future__ import annotations

import io
import os
import subprocess
import subprocess as _sub
import tempfile
from pathlib import Path
from subprocess import check_output as _co


def shape_open_default_mode(p: Path) -> str:
    return open(p).read()  # MISSING: the default mode is text


def shape_open_write_mode(p: Path, s: str) -> None:
    with open(p, "w") as fh:  # MISSING: a literal text mode
        fh.write(s)


def shape_open_mode_keyword(p: Path):
    return open(p, mode="a+")  # MISSING: mode= as a keyword


def shape_io_open_is_the_builtin(p: Path):
    return io.open(p, "r")  # MISSING


def shape_os_fdopen_text(fd: int):
    return os.fdopen(fd, "w")  # MISSING


def production_path_open(p: Path):
    return p.open()  # MISSING: the pathlib idiom, default text mode


def shape_path_open_write_mode(p: Path):
    return p.open("w")  # MISSING: mode in the first slot


def shape_read_text_bare(p: Path) -> str:
    return p.read_text()  # MISSING


def shape_read_text_errors_only(p: Path) -> str:
    return p.read_text(errors="replace")  # MISSING: errors= is not encoding=


def shape_read_text_positional_wrong(p: Path) -> str:
    return p.read_text("latin-1")  # NOT_UTF8: the positional slot IS the encoding


def shape_write_text_bare(p: Path, s: str) -> None:
    p.write_text(s)  # MISSING


def shape_write_text_positional_none(p: Path, s: str) -> None:
    p.write_text(s, None)  # NOT_UTF8: None follows the locale


def shape_subprocess_run_text(argv: list[str]):
    return subprocess.run(argv, capture_output=True, text=True)  # MISSING


def shape_check_output_universal_newlines(argv: list[str]):
    return subprocess.check_output(argv, universal_newlines=True)  # MISSING


def aliased_module(argv: list[str]):
    return _sub.run(argv, text=True)  # MISSING: the module under an alias


def aliased_function(argv: list[str]):
    return _co(argv, text=True)  # MISSING: a function imported by name


def shape_encoding_none(p: Path) -> str:
    return p.read_text(encoding=None)  # NOT_UTF8: None follows the locale


def shape_encoding_latin1(argv: list[str]):
    return subprocess.run(argv, text=True, encoding="latin-1")  # NOT_UTF8


def shape_tempfile_text_mode():
    return tempfile.NamedTemporaryFile("w", suffix=".py")  # MISSING


def shape_text_io_wrapper(buf):
    return io.TextIOWrapper(buf)  # MISSING


def historic_git_conventions(repo: Path):
    # The pre-fix body of espalier.analyze.detect_git_conventions: git's UTF-8
    # commit subjects decoded through the locale (TP-189 XPLAT-1).
    return subprocess.run(
        ["git", "log", "--format=%s"], cwd=repo, capture_output=True, text=True,
    )


def historic_contract_offenders(argv: list[str]):
    # The two value shapes TestSubprocessEncodingPinned rejects beyond absence
    # (SOUND-3): key present, value wrong.
    first = subprocess.check_output(argv, text=True, encoding=None)
    second = subprocess.check_output(argv, text=True, encoding="cp1252")
    return first, second
