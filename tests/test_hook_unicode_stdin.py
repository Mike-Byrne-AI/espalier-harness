"""Hook stdin handling: every hook must tolerate non-UTF-8 bytes and
BOM-prefixed JSON without crashing or fail-opening.

History
-------
TP-39 (post-v0.6.5 audit) added a ``ValueError`` catch to 4 hooks
(``write_guard``, ``plan_guard``, ``post_write_check``,
``reflect_trigger``) so a Windows-CP1252 stdin with non-ASCII bytes
would not crash with ``UnicodeDecodeError`` → exit 1 → CC fail-open.
The fix landed for 4 of 10 hooks; the remaining 4 (``config_guard``,
``stop_gate``, ``session_start``, ``post_compact``) still crashed.

The post-TP-40 multi-agent review caught the sister-site gap AND a
second class: BOM-prefixed JSON (``\\xef\\xbb\\xbf{...}``) was valid
UTF-8 but invalid JSON prefix. The ``json.JSONDecodeError`` except
fell through to ``data = {}``, ``tool_name = ""``, and every
protected-path check missed — so ``write_guard`` returned exit 0
without emitting a deny payload (silent ALLOW for a protected write).

Fix (this pack): single helper ``_hook_utils.read_stdin_safely``
decodes via ``utf-8-sig`` (strips BOM) and returns ``{}`` on any
parse/decode/EOF failure. Every hook routes through it.

Parametrization
---------------
``HOOKS`` is built from ``surface_contract.get_canonical_hook_scripts``
so that future hooks added to the SoT are covered automatically.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from espalier.surface_contract import get_canonical_hook_scripts

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
HOOKS = list(get_canonical_hook_scripts())


def _run_hook(hook_name: str, stdin_bytes: bytes, tmp_path: Path) -> subprocess.CompletedProcess:
    script = HOOKS_DIR / hook_name
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    env.pop("ESPALIER_MAINTENANCE_MODE", None)
    return subprocess.run(
        [sys.executable, str(script)],
        input=stdin_bytes,
        capture_output=True,
        timeout=15,
        env=env,
    )


@pytest.mark.parametrize("hook_name", HOOKS)
def test_hook_tolerates_invalid_utf8_stdin(tmp_path, hook_name):
    """``\\xff\\xff\\xff`` on stdin must not produce exit 1 (script bug)."""
    result = _run_hook(hook_name, b"\xff\xff\xff", tmp_path)
    assert result.returncode != 1, (
        f"{hook_name} crashed on invalid UTF-8 stdin "
        f"(exit code {result.returncode}); "
        f"stderr={result.stderr.decode('utf-8', errors='replace')!r}"
    )


@pytest.mark.parametrize("hook_name", HOOKS)
def test_hook_tolerates_empty_stdin(tmp_path, hook_name):
    """Empty stdin must not produce exit 1 (degenerate input)."""
    result = _run_hook(hook_name, b"", tmp_path)
    assert result.returncode != 1, (
        f"{hook_name} crashed on empty stdin (exit code {result.returncode}); "
        f"stderr={result.stderr.decode('utf-8', errors='replace')!r}"
    )


@pytest.mark.parametrize("hook_name", HOOKS)
def test_hook_tolerates_bom_prefixed_json(tmp_path, hook_name):
    """BOM-prefixed valid JSON must not produce exit 1.

    Universal contract: every hook accepts UTF-8 BOM on stdin. The
    BOM is a real-world artifact of files saved on Windows or copied
    via certain editors; ``json.load`` raises ``JSONDecodeError`` on
    it but ``utf-8-sig`` decode strips it transparently.
    """
    bom_payload = b"\xef\xbb\xbf{}"
    result = _run_hook(hook_name, bom_payload, tmp_path)
    assert result.returncode != 1, (
        f"{hook_name} crashed on BOM-prefixed JSON "
        f"(exit code {result.returncode}); "
        f"stderr={result.stderr.decode('utf-8', errors='replace')!r}"
    )


def test_write_guard_bom_bypass_closed():
    """write_guard with BOM-prefixed JSON pointing at a protected file
    must emit the deny payload, not silently allow.

    This is the regression test for the v0.6.5 BOM bypass: prior to
    the ``utf-8-sig`` fix, the BOM caused ``json.JSONDecodeError``,
    the except returned ``data = {}``, ``tool_name`` was empty,
    every protected-path check missed, and the hook exited 0 with
    empty stdout (silent ALLOW for a protected write).
    """
    repo_root = Path(__file__).resolve().parent.parent
    payload = (
        b"\xef\xbb\xbf"
        b'{"tool_name":"Write","tool_input":'
        b'{"file_path":"tools/cc/hooks/write_guard.py","content":"x"}}'
    )
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(repo_root)
    env.pop("ESPALIER_MAINTENANCE_MODE", None)
    result = subprocess.run(
        [sys.executable, str(HOOKS_DIR / "write_guard.py")],
        input=payload,
        capture_output=True,
        timeout=15,
        env=env,
    )
    assert result.returncode == 0, (
        f"write_guard exited {result.returncode} (expected 0); "
        f"stderr={result.stderr.decode('utf-8', errors='replace')!r}"
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    assert '"permissionDecision":"deny"' in stdout or '"permissionDecision": "deny"' in stdout, (
        f"write_guard did not emit deny payload for BOM-prefixed protected "
        f"write; stdout={stdout!r}"
    )
