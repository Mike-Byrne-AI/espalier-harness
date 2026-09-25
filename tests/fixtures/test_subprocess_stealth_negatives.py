"""Must-NOT-trip negatives corpus for
``espalier.scanners.subprocess_contracts``.

Companion to tests/fixtures/test_subprocess_stealth_positives.py. Where
the positives file plants espalier-internal subprocess shapes the scanner
MUST flag, this file plants the *clean-but-tempting* near-boundary shapes
the scanner MUST stay silent on. Without a negatives corpus the harness
only proves the scanner FIRES; it never proves the scanner doesn't
OVER-fire on legitimate subprocess use.

The test_does_not_trip_on_negatives check in
tests/test_scanner_subprocess_contracts.py direct-calls ``_scan_file`` on
this fixture (mirroring the earn-the-gate test) and asserts ZERO findings.

Every shape below is defanged against one specific detection branch:

- OS-utility subprocess calls (git, pytest, tar) -> skipped by
  ``_is_os_binary`` even though the call shape is identical to a positive.
- ``shell=True`` string targeting an OS binary -> same skip; ``shell=True``
  alone is not the trigger, the espalier-internal descriptor is.
- subprocess.run / Popen / os.system / os.popen against a NON-espalier,
  NON-internal target -> ``_is_espalier_internal`` returns False, so the
  call is not part of the contract surface.
- A Name-bound argv that the scanner DOES statically resolve (its
  list-binding tracker reads ``cmd = ["espalier", "memory", "prune"]``
  to the descriptor ``espalier memory prune``, so without a pragma it
  fires as UNPINNED, not UNRESOLVED) but carries a valid
  ``# subprocess-contract: ok <reason >=12 chars>`` pragma on the
  preceding line -> ``_has_pragma_above`` suppresses it.

Discoverability mirrors the positives fixture: prefixed ``test_`` so
``rglob('test_*.py')`` collects the file, but every inner function OMITS
the ``test_`` prefix so pytest collects ZERO tests here. There are no real
assertions; the shapes exist only to be read by the scanner under test.
"""
from __future__ import annotations

import os
import subprocess


# precision-boundary: a third-party CLI that names the harness mid-command (a
# non-leading mention) — the bare interpreter signature anchors to the leading
# token, so a mid-command mention is not an internal subprocess.


# ── OS-utility binaries: identical call shape to a positive, but the
#    leading token is an OS_BINARIES member, so _is_os_binary skips it. ──
def clean_subprocess_run_os_binary() -> None:
    subprocess.run(["git", "status", "--porcelain"])


def clean_subprocess_check_output_os_binary() -> None:
    subprocess.check_output(["pytest", "tests/", "-q"])


def clean_subprocess_popen_os_binary() -> None:
    proc = subprocess.Popen(["tar", "-czf", "out.tgz", "src/"])
    proc.wait()


def clean_subprocess_popen_communicate_os_binary() -> None:
    subprocess.Popen(["grep", "-r", "needle", "."]).communicate()


def clean_os_system_os_binary() -> None:
    os.system("ls -la")


def clean_os_popen_os_binary() -> None:
    os.popen("find . -name '*.py'")


def clean_shell_true_os_binary() -> None:
    # shell=True is not itself the trigger; the descriptor still resolves
    # to an OS binary, so _is_os_binary skips it.
    subprocess.run("git rev-parse HEAD", shell=True)


def clean_abs_path_os_binary() -> None:
    # Absolute-path OS binary: _is_os_binary strips the dir and matches
    # the basename against OS_BINARIES.
    subprocess.run(["/usr/bin/git", "fetch", "--all"])


# ── Non-espalier, non-internal targets: real subprocess use, but the
#    descriptor matches no ESPALIER_SIGNATURE, so it is not contract
#    surface (_is_espalier_internal returns False). ──
def clean_subprocess_run_third_party() -> None:
    subprocess.run(["docker", "build", "-t", "image", "."])


def clean_subprocess_check_output_third_party() -> None:
    subprocess.check_output(["node", "build/index.js", "--prod"])


def clean_os_system_third_party() -> None:
    os.system("terraform apply -auto-approve")


def clean_os_popen_third_party() -> None:
    os.popen("kubectl get pods")


# ── Name-bound argv WITH a valid contract pragma. The scanner resolves the
#    list literal to the descriptor `espalier memory prune`, so without the
#    pragma this fires as UNPINNED; _has_pragma_above suppresses it. The
#    reason is >=12 chars (PRAGMA_RE requirement) and cites the contract
#    test that pins the surface. ──
def clean_dynamic_argv_with_pragma() -> None:
    cmd = ["espalier", "memory", "prune"]
    cmd.append("--rows")
    # subprocess-contract: ok pinned by test_subprocess_cli_contract.py::test_memory_prune_accepts_documented_flags
    subprocess.run(cmd)


def clean_third_party_cli_mentions_espalier() -> None:
    # Twin of an espalier-internal call: "espalier" appears mid-command but the
    # LEADING token is a third-party tool, so _is_espalier_internal must NOT fire
    # (sweep T3). npm/kubectl/docker are not OS_BINARIES, so without the
    # leading-token anchor these mis-classify as internal.
    subprocess.run(["npm", "run", "espalier", "deploy"], check=False)
    subprocess.run(["kubectl", "espalier", "get"], check=False)
    subprocess.run(["docker", "espalier", "build"], check=False)
