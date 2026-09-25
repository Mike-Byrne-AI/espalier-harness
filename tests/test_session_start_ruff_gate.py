"""TP-345 1-B: session_start's load-bearing-tool banner (ruff) is self-host-gated.

Guards the adopter-friction parity between the SessionStart banner and the
``doctor`` command: ruff ships only in espalier's own dev-extras and its CI lint
gate is ``if: is_source == 'true'``, so a ruff-less ``pip install`` adopter has no
ruff gate and must not be nagged at every session boot. This pins the gate that
prevents that nag while preserving the self-host signal — because a self-host-only
warning that degrades to friction on an adopter's machine is a regression, not a
banner. Mirrors the doctor-side gate so the two sides tell one story.
"""
from __future__ import annotations

import io
import shutil
import sys
from contextlib import redirect_stderr
from pathlib import Path


def _import_session_start():
    """Load the hook module fresh with the correct sys.path discipline."""
    hooks_dir = Path(__file__).parent.parent / "tools" / "cc" / "hooks"
    tools_cc_dir = Path(__file__).parent.parent / "tools" / "cc"
    sys.path.insert(0, str(hooks_dir))
    sys.path.insert(0, str(tools_cc_dir))
    if "session_start" in sys.modules:
        del sys.modules["session_start"]
    import session_start  # type: ignore[import-not-found]
    return session_start


def _warn_stderr(self_host: bool, monkeypatch) -> str:
    """Call the banner with ruff stubbed absent; return captured stderr.

    The function does ``import shutil as _shutil`` then ``_shutil.which(tool)``;
    patching ``shutil.which`` on the shared module object reaches it.
    """
    ss = _import_session_start()
    monkeypatch.setattr(shutil, "which", lambda name: None)  # ruff absent on PATH
    buf = io.StringIO()
    with redirect_stderr(buf):
        ss._warn_if_load_bearing_tool_missing(self_host)
    return buf.getvalue()


class TestSessionStartRuffGate:
    def test_adopter_context_suppresses_ruff_banner(self, monkeypatch):
        """1-B earn-the-red: a non-self-host adopter (self_host=False) with ruff
        absent must get NO ruff banner. RED before the gate: the ungated function
        warned regardless of context, nagging every ruff-less adopter at boot.
        GREEN after: the early-return suppresses it."""
        out = _warn_stderr(self_host=False, monkeypatch=monkeypatch)
        assert "ruff" not in out, (
            f"ruff banner leaked to a non-self-host adopter (self_host=False): {out!r}"
        )

    def test_self_host_still_warns(self, monkeypatch):
        """The gate must not silence the self-host signal: with ruff absent on the
        self-host repo the lint gate is load-bearing, so the banner is real signal
        and must remain."""
        out = _warn_stderr(self_host=True, monkeypatch=monkeypatch)
        assert "ruff" in out and "[WARN]" in out, (
            f"self-host repo lost its ruff-absent banner (self_host=True): {out!r}"
        )
