"""TP-176 W3-2: advisory reporter-hook fail-OPEN umbrella.

The four advisory hooks (``context_reinject_failure``, ``subagent_start``,
``post_compact``, ``subagent_stop``) never block — they only inject advisory
context or finalize the blueprint. Each wraps ``_run_main`` in the
``try/except BaseException -> [ERROR]; return 0`` umbrella that
``task_router`` / ``post_write_check`` / ``reflect_trigger`` carry
(TP-150 §10.4) — the first three added it in TP-176, ``subagent_stop`` in
TP-369 — so an uncaught crash surfaces a single stderr line + exit 0 instead of
a raw traceback (exit 1) that Claude Code would treat as failed.

This contract pins the advisory-tier umbrella: an uncaught crash in
``_run_main`` degrades to a single ``[ERROR] <hook> crashed`` line on stderr
and exit 0 (fail OPEN), never a traceback. It is the advisory counterpart of
the blocking hooks' fail-CLOSED umbrellas (tests/test_hooks.py).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))


def _load_hook(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_tp176_umbrella_{name}", HOOKS_DIR / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class _BaseBoom(BaseException):
    """A BaseException that is NOT an Exception -- a narrowed ``except Exception``
    umbrella would let it escape, so this case pins the ``except BaseException``
    breadth the reporter hooks actually use (TP-372, absorbing dropped TP-375).
    A custom BaseException subclass (not KeyboardInterrupt/SystemExit), so it
    does not abort the pytest session."""


@pytest.mark.parametrize(
    "exc_factory",
    [
        pytest.param(lambda: RuntimeError("synthetic crash"), id="Exception"),
        pytest.param(lambda: _BaseBoom("synthetic BaseException crash"), id="BaseException"),
    ],
)
@pytest.mark.parametrize(
    "hook_name",
    ["context_reinject_failure", "subagent_start", "post_compact", "subagent_stop"],
)
def test_reporter_umbrella_fails_open_on_crash(hook_name, exc_factory, capsys, monkeypatch):
    mod = _load_hook(hook_name)

    def _boom() -> int:
        raise exc_factory()

    # main() looks up _run_main in module globals at call time.
    monkeypatch.setattr(mod, "_run_main", _boom)
    rc = mod.main()
    captured = capsys.readouterr()
    assert rc == 0, f"{hook_name}.main() must fail OPEN (exit 0) on crash"
    assert f"{hook_name} crashed" in captured.err, (
        f"{hook_name} umbrella must emit a single [ERROR] advisory line; "
        f"stderr was: {captured.err!r}"
    )
