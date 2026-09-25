"""Interactive "wire hooks now?" arming prompt on plain init (case b).

When a plain ``init`` reconciles an existing hookless ``.claude/settings.json``
(case b), it offers to wire Espalier's hooks interactively — but ONLY on a TTY,
defaulting to NO. These are in-process unit tests over
``_reconcile_existing_settings`` that mock the ``isatty`` gate + ``input()``; the
subprocess-level non-TTY regression (the ~20 captured-subprocess init tests can
never hang or ``EOFError``) is pinned separately by
``test_init_upgrade_paths.py::TestNewAdopterSettingsHonesty
::test_plain_init_leaves_existing_settings_disarmed``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from espalier import cli

# slow-exempt: one `git init` and one in-process init on a scratch tree (the
# DEF-800 on-disk pin), measured 0.11s; every other test here is in-process.

REPO_ROOT = Path(__file__).resolve().parent.parent


def _hookless_settings(tmp_path: Path) -> Path:
    """An adopter's own settings.json: permissions only, NO Espalier hooks.

    Written at the canonical `.claude/settings.json` under a repo root that
    ALSO carries a stub hook tree, so `repo_root` can be `tmp_path` and the
    arming assertions describe THIS fixture.

    ⚠ They did not, before 2026-08-27. The settings lived at `tmp_path/
    settings.json` while every call passed `repo_root=REPO_ROOT`, so the
    armament check read the HARNESS REPO'S OWN `.claude/settings.json` and
    resolved scripts against its real `tools/cc/hooks/`. `settings_hooks_wired
    is True` was reporting that this repo is healthy -- it would have passed
    with the fixture wiring nothing at all. Measured: pointed at a hookless
    `tmp_path`, both assertions in `test_interactive_yes_arms` red.
    """
    claude = tmp_path / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    settings = claude / "settings.json"
    settings.write_text(
        json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}, indent=2) + "\n",
        encoding="utf-8",
    )
    _deploy_stub_hook_tree(tmp_path)
    return settings


def _deploy_stub_hook_tree(root: Path) -> None:
    """The hook scripts a wired settings.json will point at.

    Derived from `espalier.cli.INIT_HOOK_SCRIPTS` rather than a hand-written
    copy (STANDING_PRINCIPLES 14): when init's deploy list grows, this fixture
    grows with it instead of quietly testing a stale population.
    """
    from espalier.cli import INIT_HOOK_SCRIPTS

    for rel in INIT_HOOK_SCRIPTS:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# stub\n", encoding="utf-8")


def _force_tty(monkeypatch, *, on: bool) -> None:
    # Deterministic TTY state — never depend on pytest's capture mode (`-s`
    # leaves a real TTY on stderr, which would flip these tests non-deterministically).
    monkeypatch.setattr("sys.stdin.isatty", lambda: on)
    monkeypatch.setattr("sys.stderr.isatty", lambda: on)


class TestInteractiveArming:
    def test_interactive_yes_arms(self, tmp_path, monkeypatch, capsys):
        # earn-the-red: this arming path did not exist before the 2-A prompt —
        # a mocked TTY + input "y" now routes into _wire_hooks_into_existing.
        settings = _hookless_settings(tmp_path)
        _force_tty(monkeypatch, on=True)
        monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

        outcome = cli._reconcile_existing_settings(
            settings, wire_hooks=False, profile_name="workflow", repo_root=tmp_path,
        )

        data = json.loads(settings.read_text(encoding="utf-8"))
        assert outcome.settings_hooks_wired is True
        assert "tools/cc/hooks" in json.dumps(data.get("hooks", {})), (
            "answering yes did not wire the hooks"
        )
        assert data["permissions"]["allow"] == ["Bash(ls:*)"], (
            "operator keys not preserved through the interactive merge"
        )
        assert any(p.name.endswith(".bak") for p in settings.parent.iterdir()), (
            "no .bak backup written on the interactive arm"
        )
        assert "Enforcement is now active" in capsys.readouterr().err

    def test_interactive_no_preserves(self, tmp_path, monkeypatch, capsys):
        settings = _hookless_settings(tmp_path)
        before = settings.read_bytes()
        _force_tty(monkeypatch, on=True)
        monkeypatch.setattr("builtins.input", lambda *a, **k: "")  # bare Enter = default NO

        outcome = cli._reconcile_existing_settings(
            settings, wire_hooks=False, profile_name="workflow", repo_root=tmp_path,
        )

        assert outcome.settings_hooks_wired is False
        assert settings.read_bytes() == before, "declined prompt still mutated the file"
        # 3-A: the case-(b) WARN still carries its self-remedy (present pre-pack;
        # must survive the prompt). No duplicate remedy line is appended.
        err = capsys.readouterr().err
        assert "NOT active" in err, err
        assert "merge-settings" in err and "--wire-hooks" in err, err
        assert err.count("-m espalier merge-settings") == 1, (
            "remedy line duplicated (3-A regression)"
        )
        # TP-391 4-B: the count above is a substring count, so it stays GREEN when the
        # single remedy line is rendered with NO interpreter token. Both assertions are
        # kept: the first pins "exactly one remedy line" (the 3-A invariant), this one
        # pins "and it carries an interpreter". Together they red on a duplicate AND on
        # an interpreter-less rendering.
        # `[\w./-]+` not `\S+`: a backticked hint (`{py} -m ...`) lets `\S+` match the
        # BACKTICK as the interpreter, so an empty token would slip through.
        assert len(re.findall(r"[\w./-]+ -m espalier merge-settings", err)) == 1, (
            "the remedy line must read `<interp> -m espalier merge-settings` -- an "
            f"interpreter-less hint is command-not-found in a fusion.\n{err}"
        )

    def test_non_tty_never_prompts(self, tmp_path, monkeypatch):
        # The load-bearing safety pin: off a TTY the prompt must NOT fire, so a
        # captured-subprocess / CI init can never block on stdin or EOFError.
        settings = _hookless_settings(tmp_path)
        before = settings.read_bytes()
        _force_tty(monkeypatch, on=False)

        def _boom(*_a, **_k):
            raise AssertionError("init prompted on a non-TTY (would EOFError on a pipe)")

        monkeypatch.setattr("builtins.input", _boom)

        outcome = cli._reconcile_existing_settings(
            settings, wire_hooks=False, profile_name="workflow", repo_root=tmp_path,
        )

        assert outcome.settings_hooks_wired is False
        assert settings.read_bytes() == before

    def test_stdin_tty_but_stderr_not_never_prompts(self, tmp_path, monkeypatch):
        # Partial-redirect guard: stdin is a TTY but stderr is piped (the operator
        # can't see the prompt) — the AND-gate must still skip it.
        settings = _hookless_settings(tmp_path)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stderr.isatty", lambda: False)

        def _boom(*_a, **_k):
            raise AssertionError("prompted with a non-TTY stderr")

        monkeypatch.setattr("builtins.input", _boom)

        outcome = cli._reconcile_existing_settings(
            settings, wire_hooks=False, profile_name="workflow", repo_root=tmp_path,
        )
        assert outcome.settings_hooks_wired is False

    def test_none_stdin_does_not_crash(self, tmp_path, monkeypatch, capsys):
        """TP-274 5-A: sys.stdin can be None (closed fd ``0<&-``, pythonw, embedded).
        271b's gate called ``sys.stdin.isatty()`` unguarded → an AttributeError
        crash on the EXACT non-interactive path it was meant to harden. With stdin
        None the gate must degrade to the preserve+WARN default (no prompt, no
        crash). RED before (AttributeError), GREEN after. (A bare fresh tmp does not
        reach this branch — a pre-existing hookless settings.json is required, which
        ``_hookless_settings`` provides.)"""
        settings = _hookless_settings(tmp_path)
        before = settings.read_bytes()
        monkeypatch.setattr("sys.stdin", None)

        def _boom(*_a, **_k):
            raise AssertionError("prompted with a None stdin")

        monkeypatch.setattr("builtins.input", _boom)

        outcome = cli._reconcile_existing_settings(
            settings, wire_hooks=False, profile_name="workflow", repo_root=tmp_path,
        )
        assert outcome.settings_hooks_wired is False
        assert settings.read_bytes() == before, "None-stdin path mutated the file"
        assert "NOT active" in capsys.readouterr().err


def test_stream_isatty_is_none_safe():
    """TP-274 5-A: ``_stream_isatty`` returns False for None / a stream lacking
    isatty, and delegates for a real stream — so an interactive gate degrades to
    the non-interactive default instead of raising AttributeError."""
    class _FakeTTY:
        def isatty(self):
            return True

    class _FakePipe:
        def isatty(self):
            return False

    assert cli._stream_isatty(_FakeTTY()) is True
    assert cli._stream_isatty(_FakePipe()) is False
    assert cli._stream_isatty(None) is False
    assert cli._stream_isatty(object()) is False  # no .isatty attribute


def test_stream_isatty_closed_stream_safe(tmp_path: Path) -> None:
    """TP-275 2-A: a *closed* (non-None) file object raises ``ValueError`` from
    ``isatty()``; ``_stream_isatty`` must catch it and return False so an
    interactive gate degrades to the non-interactive default instead of
    propagating. (``test_stream_isatty_is_none_safe`` covers None / no-attr.)"""
    f = open(tmp_path / "closed.txt", "w", encoding="utf-8")
    f.close()
    # Sanity: the raw call really does raise ValueError on a closed stream, so
    # this test would be vacuous if _stream_isatty simply never reached isatty().
    raised = False
    try:
        f.isatty()
    except ValueError:
        raised = True
    assert raised, "expected a closed stream's isatty() to raise ValueError"
    assert cli._stream_isatty(f) is False


def test_no_raw_sys_isatty_calls_in_cli():
    """TP-274 5-A: both isatty sites must route through ``_stream_isatty``, never
    call ``sys.stdin.isatty()`` / ``sys.stderr.isatty()`` directly (which crash on
    a None stream). Pins both sites + blocks a regression re-introducing a raw call."""
    src = (REPO_ROOT / "espalier" / "cli.py").read_text(encoding="utf-8")
    for raw in ("sys.stdin.isatty(", "sys.stderr.isatty("):
        assert raw not in src, f"raw {raw}) in cli.py — route through _stream_isatty"


class TestInterruptedAtThePrompt:
    """DEF-800: the wire prompt is the first question init ever asks, and a
    hesitating adopter presses Ctrl+C at it. Driven 2026-09-14 on the Windows
    walk and 2026-09-15 on POSIX: a raw traceback (runpy frames plus cli.py)
    over a tree with 25 hook scripts deployed and settings.json unwired,
    which the traceback did not describe. Now the prompt site names that
    state and re-raises, ``main`` turns the interrupt into one line and
    exit 130, and Ctrl+D is the default No instead of an uncaught EOFError."""

    def test_ctrl_c_names_the_partial_state_then_reraises(self, tmp_path, monkeypatch, capsys):
        settings = _hookless_settings(tmp_path)
        before = settings.read_bytes()
        _force_tty(monkeypatch, on=True)

        def _ctrl_c(*_a, **_k):
            raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", _ctrl_c)
        with pytest.raises(KeyboardInterrupt):
            cli._reconcile_existing_settings(
                settings, wire_hooks=False, profile_name="workflow", repo_root=tmp_path,
            )
        err = capsys.readouterr().err
        assert "Interrupted at the wire prompt." in err
        assert "hook and tool scripts under tools/cc/" in err, "what IS deployed"
        assert ".claude/settings.json is unchanged (hooks NOT wired)" in err, "what is NOT"
        assert re.search(r"Re-run `\S+ -m espalier init \. --wire-hooks`", err), "the finishing verb"
        assert settings.read_bytes() == before, "the interrupt must not touch the file"

    def test_ctrl_d_is_the_default_no(self, tmp_path, monkeypatch, capsys):
        settings = _hookless_settings(tmp_path)
        before = settings.read_bytes()
        _force_tty(monkeypatch, on=True)

        def _eof(*_a, **_k):
            raise EOFError

        monkeypatch.setattr("builtins.input", _eof)
        outcome = cli._reconcile_existing_settings(
            settings, wire_hooks=False, profile_name="workflow", repo_root=tmp_path,
        )
        err = capsys.readouterr().err
        assert outcome.settings_hooks_wired is False
        assert settings.read_bytes() == before
        assert "NO Espalier hooks wired" in err, "the declined path's WARN, as for a bare Enter"
        assert "Interrupted" not in err

    def test_ctrl_c_through_main_leaves_the_tree_the_sentence_describes(self, tmp_path, monkeypatch, capsys):
        """The sentence is prose about deploy ORDER (seed docs and reports,
        then the hook and tool scripts, then the prompt, then the `.claude/`
        bodies and CLAUDE.md), so it is pinned to the tree a real `init`
        leaves behind, not to its own words: a later reordering of
        `deploy_harness` reds here, not in a substring test."""
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        claude = tmp_path / ".claude"
        claude.mkdir()
        settings = claude / "settings.json"
        settings.write_text(
            json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}, indent=2) + "\n",
            encoding="utf-8",
        )
        before = settings.read_bytes()
        monkeypatch.setattr(cli, "_stream_isatty", lambda _stream: True)

        def _ctrl_c(*_a, **_k):
            raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", _ctrl_c)
        monkeypatch.setattr("sys.argv", ["espalier", "init", str(tmp_path)])
        monkeypatch.chdir(tmp_path)

        rc = cli.main()

        err = capsys.readouterr().err
        assert rc == 130
        assert "Traceback" not in err
        assert "Interrupted at the wire prompt." in err and err.rstrip().endswith("Interrupted.")
        # Deployed so far, as the sentence says:
        assert (tmp_path / "reports").is_dir(), "reports/ is written before the prompt"
        assert (tmp_path / "docs").is_dir(), "the seed docs are written before the prompt"
        assert (tmp_path / "tools" / "cc" / "hooks" / "write_guard.py").is_file(), "the hook scripts land before the prompt"
        # Not done, as the sentence says:
        assert settings.read_bytes() == before, "settings.json is unchanged"
        assert not (claude / "agents").exists() and not (claude / "commands").exists(), (
            "the .claude/ bodies are deployed AFTER the prompt; if that order changed, reword the sentence"
        )
        assert not (tmp_path / "CLAUDE.md").exists(), "CLAUDE.md is written after the prompt"
