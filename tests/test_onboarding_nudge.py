# pytest-marker: default-unit
"""TP-220: onboarding nudge for ungoverned clones.

``espalier init`` gitignores ``.claude/settings.json``, so a ``git clone`` of a
governed repo arrives with the full committed harness surface but no running
hooks until the cloner re-runs ``init`` — a silent loss, because the warning
hooks themselves require the settings.json they would warn about. The CLI nudge
(:func:`espalier.cli._maybe_nudge_source_checkout`) is the one deterministic
channel that survives that chicken-and-egg.

Earn-the-red: the nudge must fire for a ``source_checkout`` repo on a TTY with a
non-exempt command, and stay silent for an initialized repo, an exempt
(state-fixing or self-messaging) command, or a non-TTY (CI) invocation — the
last guard is what keeps the message off every CI log, since a clean CI checkout
of any Espalier repo is itself a ``source_checkout`` (the runtime markers are
gitignored).
"""
from __future__ import annotations

import argparse
import io
import sys

import pytest

from espalier import cli


class _FakeStderr(io.StringIO):
    """A stderr stand-in with a controllable ``isatty()`` — the nudge gates on
    it, and capsys's stream reports ``isatty() == False``, so we drive it
    explicitly."""

    def __init__(self, tty: bool):
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _dummy_command(args: argparse.Namespace) -> int:
    """A non-exempt command func — not in the nudge's exempt set."""
    return 0


def _make_source_checkout(root):
    """Committed harness surface present, no runtime markers → source_checkout."""
    (root / "cc").mkdir()
    (root / "cc" / "COMMANDS.md").write_text("# cmds\n", encoding="utf-8")
    return root


def _make_initialized(root):
    """Committed surface plus a runtime marker (settings.json) → initialized."""
    _make_source_checkout(root)
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    return root


def _run_nudge(monkeypatch, *, func, repo, tty):
    """Invoke the helper with a fake TTY-aware stderr; return captured stderr."""
    fake = _FakeStderr(tty=tty)
    monkeypatch.setattr(sys, "stderr", fake)
    args = argparse.Namespace(func=func, repo=repo)
    cli._maybe_nudge_source_checkout(args)
    return fake.getvalue()


class TestSourceCheckoutNudge:
    def test_source_checkout_on_tty_prints_init_nudge(self, monkeypatch, tmp_path):
        repo = _make_source_checkout(tmp_path)
        err = _run_nudge(monkeypatch, func=_dummy_command, repo=str(repo), tty=True)
        assert "governance is NOT active" in err
        assert ".claude/settings.json" in err
        assert f"init {repo}" in err

    def test_initialized_repo_does_not_nudge(self, monkeypatch, tmp_path):
        repo = _make_initialized(tmp_path)
        err = _run_nudge(monkeypatch, func=_dummy_command, repo=str(repo), tty=True)
        assert err == ""

    def test_non_tty_does_not_nudge(self, monkeypatch, tmp_path):
        """CI-noise guard: a clean CI checkout is itself a source_checkout, so an
        ungated nudge would noise every CI run. isatty False → silent."""
        repo = _make_source_checkout(tmp_path)
        err = _run_nudge(monkeypatch, func=_dummy_command, repo=str(repo), tty=False)
        assert err == ""

    def test_missing_repo_attr_does_not_nudge(self, monkeypatch):
        """Commands without a ``repo`` arg (e.g. render-template) → silent."""
        fake = _FakeStderr(tty=True)
        monkeypatch.setattr(sys, "stderr", fake)
        args = argparse.Namespace(func=_dummy_command)  # no .repo
        cli._maybe_nudge_source_checkout(args)
        assert fake.getvalue() == ""


# The commands whose job is to FIX the unwired state (or which message mode
# themselves): they must never nudge, even in a source_checkout on a TTY. The
# func-exempt check runs BEFORE the repo check, so passing a real source_checkout
# repo here genuinely exercises the exemption (a non-exempt func with the same
# repo would nudge — see TestSourceCheckoutNudge).
def _exempt_command_params():
    params = [
        pytest.param(cli.cmd_init, id="cmd_init"),
        pytest.param(cli.cmd_merge_settings, id="cmd_merge_settings"),
        pytest.param(cli.cmd_doctor, id="cmd_doctor"),
        pytest.param(cli.cmd_upgrade, id="cmd_upgrade"),
        pytest.param(cli.cmd_install_ci, id="cmd_install_ci"),
        # self-host / _refresh-self-host-pin operate on a source checkout BY
        # DESIGN (self-host's documented --mode source-checkout CI mode) — the
        # nudge must never tell them to init, which would corrupt what they check.
        pytest.param(cli.cmd_self_host, id="cmd_self_host"),
        pytest.param(cli.cmd_refresh_self_host_pin, id="cmd_refresh_self_host_pin"),
    ]
    # cmd_fuse is lazily imported (it imports cli), so it is not a cli attribute.
    # Resolve the real function object the fuse subparser binds — the helper must
    # exempt this exact object (the pack's globals().get("cmd_fuse") never could,
    # since cmd_fuse is a build_parser local, not a module global).
    #
    # TP-225-A: import UNCONDITIONALLY. The prior `try/except ImportError: pass`
    # silently dropped this parametrize case if espalier.fuse failed to import —
    # so a broken fuse module left TestExemptCommands green while the cmd_fuse
    # exemption went untested. espalier.fuse is first-party and always importable
    # in this tree; a genuine ImportError here is a real regression that must
    # fail loudly at collection, not vanish.
    from espalier.fuse import cmd_fuse
    params.append(pytest.param(cmd_fuse, id="cmd_fuse"))
    return params


class TestExemptCommands:
    @pytest.mark.parametrize("func", _exempt_command_params())
    def test_exempt_func_does_not_nudge(self, monkeypatch, tmp_path, func):
        repo = _make_source_checkout(tmp_path)
        err = _run_nudge(monkeypatch, func=func, repo=str(repo), tty=True)
        assert err == ""


class TestMainCallSite:
    """Pin the load-bearing wiring: main() must call the nudge before dispatch.
    The helper is unit-tested above; this guards against a future refactor of
    main() silently dropping the `_maybe_nudge_source_checkout(args)` line (the
    suite would otherwise stay green while the nudge dies)."""

    def test_main_invokes_nudge_before_dispatch(self, monkeypatch, capsys):
        called = {}
        monkeypatch.setattr(
            cli, "_maybe_nudge_source_checkout",
            lambda args: called.__setitem__("args", args),
        )
        # render-template is a cheap, repo-less command that dispatches cleanly.
        monkeypatch.setattr(sys, "argv", ["espalier", "render-template", "claude"])
        rc = cli.main()
        capsys.readouterr()  # swallow the rendered template
        assert rc == 0
        assert "args" in called, "main() did not call _maybe_nudge_source_checkout"
