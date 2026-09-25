"""TP-121: every scanner's ``main()`` accepts ``--out`` without a
directory component.

Pins the CLI surface of all 5 scanner modules against the
``os.makedirs(os.path.dirname(""))`` class. Pre-fix, any
``python3 -m espalier.scanners.<scanner> --out flat.json`` invocation
from a cwd where the default ``reports/`` directory does not exist
crashed with ``FileNotFoundError: [Errno 2] No such file or
directory: ''``.

Scanner tests usually call functions directly (CONVENTIONS.md L128);
subprocess is required here precisely BECAUSE the bug is in the
``__main__`` path's ``os.makedirs`` call, not in ``scan_repo``. The
parametrize matrix exercises each scanner's CLI entry independently
so a future regression on any one module is caught.

Failure mode prevented: a future refactor reverts one scanner's
guard back to bare ``os.makedirs(os.path.dirname(args.out))``; the
parametrize matrix fails on that scanner specifically rather than
silently degrading the adopter-facing CLI.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest


SCANNER_MODULES: tuple[str, ...] = (
    "espalier.scanners.exceptions",
    "espalier.scanners.godfiles",
    "espalier.scanners.perf_smells",
    "espalier.scanners.prints",
    "espalier.scanners.test_loosening",
)


@pytest.mark.parametrize(
    "module", SCANNER_MODULES, ids=lambda m: m.rsplit(".", 1)[-1]
)
def test_scanner_main_accepts_flat_out_path(tmp_path, module):
    out_file = tmp_path / "flat.json"
    args = [
        # Use ``sys.executable`` — the literal "python3" resolves to the
        # system interpreter via PATH, which on many dev machines doesn't
        # have ``espalier`` installed. ``sys.executable`` is the running
        # pytest's Python, which is guaranteed to import ``espalier``
        # because pytest already did.
        sys.executable, "-m", module,
        "--root", str(tmp_path),
        "--out", out_file.name,
    ]
    # godfiles writes a second report file via ``--md``; flatten
    # that too so the test doesn't crash on a missing ``reports/``
    # directory in the fresh tmp_path cwd. The other 4 scanners
    # only write one file (``--out``), so no extra arg needed.
    if module.endswith(".godfiles"):
        args.extend(["--md", "flat.md"])
    # Drop ESPALIER_AUDIT_DIR per CONVENTIONS.md subprocess-test
    # pattern — scanners don't read it today, but the contract says
    # subprocess tests must not inherit it.
    env = {k: v for k, v in os.environ.items() if k != "ESPALIER_AUDIT_DIR"}
    # Ensure the subprocess can import espalier when running from a
    # source checkout. Force-set (not setdefault) because an inherited
    # PYTHONPATH of "." would resolve against ``cwd=tmp_path`` and miss
    # the repo's espalier package. Use the absolute repo root.
    env["PYTHONPATH"] = os.getcwd()
    result = subprocess.run(
        args,
        cwd=tmp_path,
        capture_output=True, text=True,
        env=env, encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"{module} main() crashed on flat --out path.\n"
        f"stderr:\n{result.stderr}\n"
        f"stdout:\n{result.stdout}"
    )
    assert out_file.exists(), (
        f"{module} did not write {out_file.name} to {tmp_path}"
    )
