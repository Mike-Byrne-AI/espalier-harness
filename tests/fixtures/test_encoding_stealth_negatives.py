"""Must-NOT-trip negatives corpus for ``espalier.scanners.encoding_contracts``.

Companion to tests/fixtures/test_encoding_stealth_positives.py. Where the
positives file plants the locale-following shapes the scanner MUST flag, this
file plants the clean-but-tempting near-boundary shapes it MUST stay silent
on. Without a negatives corpus the harness only proves the scanner FIRES; it
never proves the scanner does not OVER-fire on correct I/O.

The test_does_not_trip_on_negatives check in
tests/test_scanner_encoding_contracts.py direct-calls ``_scan_file`` on this
fixture (mirroring the earn-the-gate test) and asserts ZERO findings.

Every shape below is defanged against one specific detection branch:

- ``encoding="utf-8"`` in any spelling, ``utf-8-sig`` included, keyword or in
  the positional slot -> pinned.
- binary modes (``"rb"``, ``"wb"``, ``mode="ab"``, a Path ``.open("rb")``, the
  tempfile default ``w+b``), ``read_bytes`` / ``write_bytes``, a subprocess
  with no text flag or ``text=False`` -> bytes never decode.
- a non-literal mode, a non-literal ``encoding=``, a ``**kwargs`` splat ->
  cannot be judged statically; the benefit of the doubt.
- ``os.open`` / ``tarfile.open`` / ``gzip.open`` -> module openers, not files.
- ``runner.run(argv, text=True)`` -> the receiver is not the subprocess module,
  under its name or any alias bound in this module.
- the pragma on the line ABOVE a deliberate non-UTF-8 decode -> honored.
"""
from __future__ import annotations

import gzip
import io
import os
import subprocess
import subprocess as sp
import tarfile
import tempfile
from pathlib import Path
from subprocess import run as _run


def pinned_open_read(p: Path) -> str:
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def pinned_open_write_mode(p: Path, s: str) -> None:
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(s)


def pinned_io_open(p: Path):
    return io.open(p, "r", encoding="utf-8")


def pinned_fdopen(fd: int):
    return os.fdopen(fd, "w", encoding="utf-8", newline="")


def binary_fdopen(fd: int):
    return os.fdopen(fd, "wb")


def binary_open_read(p: Path) -> bytes:
    with open(p, "rb") as fh:
        return fh.read()


def binary_open_write(p: Path, b: bytes) -> None:
    with open(p, "wb") as fh:
        fh.write(b)


def binary_mode_keyword(p: Path):
    return open(p, mode="ab")


def dynamic_mode_is_not_judged(p: Path, mode: str):
    return open(p, mode)


def pinned_path_open(p: Path):
    return p.open("w", encoding="utf-8")


def pinned_path_open_default_mode(p: Path):
    return p.open(encoding="utf-8", errors="replace")


def binary_path_open(p: Path):
    return p.open("rb")


def read_bytes_and_write_bytes(p: Path, b: bytes) -> bytes:
    p.write_bytes(b)
    return p.read_bytes()


def pinned_read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def pinned_read_text_upper(p: Path) -> str:
    return p.read_text(encoding="UTF-8")


def pinned_read_text_underscore(p: Path) -> str:
    return p.read_text(encoding="utf_8")


def pinned_read_text_positional(p: Path) -> str:
    return p.read_text("utf-8")


def bom_tolerant_read_is_utf8(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig")


def pinned_write_text_with_errors(p: Path, s: str) -> None:
    p.write_text(s, encoding="utf-8", errors="replace")


def pinned_write_text_positional(p: Path, s: str) -> None:
    p.write_text(s, "utf-8")


def dynamic_encoding_is_not_judged(p: Path, enc: str) -> str:
    return p.read_text(encoding=enc)


def kwargs_splat_is_not_judged(p: Path, **kw) -> str:
    return p.read_text(**kw)


def subprocess_bytes(argv: list[str]):
    return subprocess.run(argv, capture_output=True)


def subprocess_text_pinned(argv: list[str]):
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8")


def subprocess_text_false(argv: list[str]):
    return subprocess.run(argv, text=False)


def subprocess_check_output_bytes(argv: list[str]):
    return subprocess.check_output(argv)


def subprocess_popen_pinned(argv: list[str]):
    return subprocess.Popen(
        argv, stdout=subprocess.PIPE, universal_newlines=True, encoding="utf-8",
    )


def aliased_module_pinned(argv: list[str]):
    return sp.run(argv, text=True, encoding="utf-8")


def aliased_function_bytes(argv: list[str]):
    return _run(argv, capture_output=True)


def not_the_subprocess_module(runner, argv: list[str]):
    return runner.run(argv, text=True)


def os_open_is_not_the_builtin(p: Path) -> int:
    return os.open(p, os.O_RDONLY)


def tarfile_open_is_a_module_opener(p: Path):
    return tarfile.open(p, "r:gz")


def gzip_open_is_a_module_opener(p: Path):
    return gzip.open(p, "rb")


def tempfile_default_is_binary():
    return tempfile.NamedTemporaryFile(suffix=".bin")


def tempfile_text_pinned():
    return tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8")


def text_io_wrapper_pinned(buf):
    return io.TextIOWrapper(buf, encoding="utf-8")


def text_io_wrapper_positional_pinned(buf):
    return io.TextIOWrapper(buf, "utf-8")


def pragma_honored_above_a_deliberate_decode(p: Path) -> str:
    # encoding-locale-ok: the assertion IS that the file decodes as seven-bit ASCII
    return p.read_text(encoding="ascii")
