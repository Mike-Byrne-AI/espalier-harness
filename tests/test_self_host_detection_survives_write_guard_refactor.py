"""TP-79 regression: pin refresh survives write_guard refactor.

Regression guard for the silent self-host-detection-loss failure mode.
The SHA pin in ``espalier/_self_host_fingerprint.WRITE_GUARD_PREFIX_SHA256``
and its mirror in ``tools/cc/hooks/_self_host_fingerprint.py`` hash the
first 200 bytes of ``tools/cc/hooks/write_guard.py``. A refactor that
rewrites the file's opening (imports, docstring) invalidates both pins;
without an explicit refresh, ``is_self_host_repo`` returns False on
self-host immediately after the refactor and the harness-dev tier
overlay silently vanishes.

Companion test to ``tests/test_self_host_fingerprint_parity.py`` (which
asserts the two mirrored constants are byte-equal) and
``tests/test_library_hook_parity.py::TestSelfHostDetectorConvergence``
(which asserts the library + hook-side detectors agree on every fixture).
"""
from __future__ import annotations

from pathlib import Path

from espalier.surface_contract import is_self_host_repo


def test_is_self_host_repo_after_write_guard_refactor() -> None:
    """``is_self_host_repo`` must return True on the live self-host
    repo immediately after any refactor that touches the first 200
    bytes of ``tools/cc/hooks/write_guard.py``. If this assertion
    fires, the SHA pin needs to be refreshed in BOTH
    ``espalier/_self_host_fingerprint.py`` AND
    ``tools/cc/hooks/_self_host_fingerprint.py`` (lockstep -- see
    TP-79 sec. 10-E). The byte-equality test for the lockstep
    requirement lives in
    ``tests/test_self_host_fingerprint_parity.py``."""
    repo_root = Path(__file__).resolve().parent.parent
    assert is_self_host_repo(repo_root), (
        "After write_guard.py refactor, the SHA pin must be refreshed "
        "in espalier/_self_host_fingerprint.py AND "
        "tools/cc/hooks/_self_host_fingerprint.py. See TP-79 sec. 10-E."
    )
