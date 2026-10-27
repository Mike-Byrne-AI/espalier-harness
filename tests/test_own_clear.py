"""Contract tests for the own-clear's marker: ``tools/cc/ship.py`` arms
``.espalier-state/own_clear.json`` as the handoff's last act, and
``tools/cc/seat.py::reprime_text`` composes the brief it carries (the own-clear
lane, 2026-10-26).

The marker is what the own-clear mod (``tools/cc/mods/own-clear``) reads: at
the turn's end an armed marker naming the session runs the real ``/clear``,
and on the clear's SessionStart the mod consumes it and submits its brief. It
is keyed by the session id (``CLAUDE_CODE_SESSION_ID``, which a Claude Code
session exports to its tool shells), and armed only in a window that loaded
the mod (``ESPALIER_OWN_CLEAR=1``, which ``seat.py launch`` exports when the
mod rides); elsewhere nothing is armed, and the handoff says so.

This file pins the contract between the handoff's writer and the mod's reader
(the marker's path, states and gate) and guards the arm against the two
silent failures the reviews named: an arm in a window with no mod, and a
brief that refuses after the push landed. REAL-GIT case for the whole arm: a
scratch repository named ``box`` whose brief ``compose_brief`` composes; the
pure writer, the brief's shape and the launcher's flag are in-process. The handoff verb's own paths (off, pushed,
refused, dry run) are driven beside their siblings in
``tests/test_ship_driver.py``; the mod's hooks run against the engine's test
kit (``claude plugin test``), and ``bench/own_clear/drive.py`` drives the real
thing.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests._git_oracle import _git_env

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_CC = REPO_ROOT / "tools" / "cc"
HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


def _load(alias: str, name: str):
    """The importlib dance ``tests/CLAUDE.md`` mandates for a ``tools/cc`` module."""
    if str(TOOLS_CC) not in sys.path:
        sys.path.insert(0, str(TOOLS_CC))
    spec = importlib.util.spec_from_file_location(alias, TOOLS_CC / name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod   # registered before exec (3.14)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ship():
    return _load("ship_own_clear_under_test", "ship.py")


@pytest.fixture(scope="module")
def seat():
    return _load("seat_own_clear_under_test", "seat.py")


@pytest.fixture(scope="module")
def module_text(seat) -> str:
    """The mod's hooks module, as the engine reads it."""
    return (seat.MOD_DIR / "hooks" / "register.ts").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _outside_a_mod_window(monkeypatch):
    """The suite may run inside a Claude session, which exports its id to the
    shell, and inside a seat the launcher started, which exports the mod's
    flag; each case sets what it means."""
    for name in ("CLAUDE_CODE_SESSION_ID", "ESPALIER_OWN_CLEAR"):
        monkeypatch.delenv(name, raising=False)


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=_git_env(), check=True, timeout=45)
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A scratch repository with one commit, named ``box`` and naming itself
    the dispatcher, as a seat's clone is."""
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "--quiet", "-b", "main")
    for key, value in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false"),
                       ("espalier.machine", "box")):
        _git(work, "config", key, value)
    (work / "README.md").write_bytes(b"seed\n")
    (work / "espalier.toml").write_text('dispatcher = "box"\n', encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "--quiet", "-m", "seed")
    return work


def _marker(root: Path) -> dict:
    return json.loads((root / ".espalier-state" / "own_clear.json").read_text(encoding="utf-8"))


def _in_a_mod_window(monkeypatch, session_id: str = "s-here") -> None:
    monkeypatch.setenv("ESPALIER_OWN_CLEAR", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session_id)


class TestArmOwnClear:
    """The pure writer: one JSON object, written whole and renamed into place,
    keyed by the session. Dies to: a marker with no session id (any window
    would clear on it), a temp file left beside it, or a second arm that does
    not replace the first."""

    def test_the_marker_names_the_session_the_head_the_seat_and_the_brief(self, ship, tmp_path):
        line = ship.arm_own_clear(tmp_path, session_id="s-1", head=HEAD, seat="box", role="worker",
                                  brief="the brief\nits note")
        marker = _marker(tmp_path)
        assert marker == {"state": "armed", "session_id": "s-1", "head": HEAD, "seat": "box", "role": "worker",
                          "brief": "the brief\nits note", "written_at": marker["written_at"]}
        assert marker["written_at"].endswith("+00:00")
        assert "own-clear armed for session s-1" in line and "box" in line
        assert [p.name for p in (tmp_path / ".espalier-state").iterdir()] == ["own_clear.json"]

    def test_a_second_arm_replaces_the_first(self, ship, tmp_path):
        ship.arm_own_clear(tmp_path, session_id="s-1", head=HEAD, seat="box", role="worker", brief="one")
        ship.arm_own_clear(tmp_path, session_id="s-2", head=HEAD, seat=None, role=None, brief=None)
        marker = _marker(tmp_path)
        assert marker["session_id"] == "s-2" and marker["seat"] is None and marker["brief"] is None

    def test_the_marker_is_ascii_json_a_mod_can_read_without_a_decoder(self, ship, tmp_path):
        ship.arm_own_clear(tmp_path, session_id="s-1", head=HEAD, seat="box", role="worker",
                           brief="a brief with a ’ quote")
        raw = (tmp_path / ".espalier-state" / "own_clear.json").read_bytes()
        assert raw.isascii() and raw.endswith(b"\n")
        assert json.loads(raw)["brief"] == "a brief with a ’ quote"


class TestArmOwnClearHere:
    """The handoff's call: only in a window the launcher started with the mod,
    the session from the environment, HEAD from git, the seat's brief from
    seat.py. Dies to: an arm in a window with no mod (the handoff's line would
    promise a clear nothing performs), an arm with no session id, or a seat
    that cannot be named failing the handoff instead of arming without a
    brief."""

    def test_a_window_without_the_mod_arms_nothing_and_names_the_by_hand_reset(self, ship, repo, monkeypatch):
        monkeypatch.chdir(repo)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-here")
        line = ship.arm_own_clear_here(repo)
        assert "not armed" in line and "did not load the own-clear mod" in line and "/clear by hand" in line
        assert not (repo / ".espalier-state" / "own_clear.json").exists()

    def test_no_session_id_arms_nothing_and_says_so(self, ship, repo, monkeypatch):
        monkeypatch.chdir(repo)
        monkeypatch.setenv("ESPALIER_OWN_CLEAR", "1")
        line = ship.arm_own_clear_here(repo)
        assert "not armed" in line and "CLAUDE_CODE_SESSION_ID" in line
        assert not (repo / ".espalier-state" / "own_clear.json").exists()

    def test_the_session_the_head_and_the_dispatchers_brief_ride_the_marker(self, ship, seat, repo, monkeypatch):
        monkeypatch.chdir(repo)
        _in_a_mod_window(monkeypatch)
        line = ship.arm_own_clear_here(repo)
        marker = _marker(repo)
        assert marker["session_id"] == "s-here" and marker["head"] == _git(repo, "rev-parse", "HEAD")
        assert marker["seat"] == "box" and marker["role"] == "dispatcher"
        assert marker["brief"] == seat.reprime_text(seat.compose_brief(repo, "box", repo))
        assert "own-clear armed for session s-here" in line and "dispatcher" in line

    def test_an_unnamed_seat_arms_with_no_brief_and_says_so(self, ship, repo, monkeypatch):
        monkeypatch.chdir(repo)
        _in_a_mod_window(monkeypatch)
        _git(repo, "config", "--unset", "espalier.machine")
        line = ship.arm_own_clear_here(repo)
        marker = _marker(repo)
        assert marker["session_id"] == "s-here" and marker["seat"] is None and marker["brief"] is None
        assert "no brief" in line and "espalier.machine" in line

    def test_a_seat_driver_that_will_not_load_arms_with_no_brief_and_says_so(self, ship, repo, monkeypatch):
        """The brief's composer is loaded by path; one that raises on load is
        a reason on the line, never a failed handoff after its push landed."""
        monkeypatch.chdir(repo)
        _in_a_mod_window(monkeypatch)

        def broken():
            raise ImportError("seat.py: a syntax error")

        monkeypatch.setattr(ship, "_seat_module", broken)
        line = ship.arm_own_clear_here(repo)
        assert _marker(repo)["brief"] is None
        assert "no brief" in line and "seat.py: a syntax error" in line


class TestModArgs:
    """What `seat.py launch` puts first in claude's arguments: `--plugin-dir`
    for the own-clear mod beside the driver, when its manifest is there. Dies
    to: a flag for a directory with no manifest (claude would refuse the
    launch), or this repository's launch loading nothing."""

    def test_a_directory_with_the_manifest_rides_as_a_plugin_dir(self, seat, tmp_path):
        mod = tmp_path / "own-clear"
        (mod / ".claude-plugin").mkdir(parents=True)
        (mod / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
        assert seat.mod_args(mod) == ["--plugin-dir", str(mod)]

    def test_no_manifest_rides_nothing(self, seat, tmp_path):
        assert seat.mod_args(tmp_path / "missing") == []
        (tmp_path / "half" / ".claude-plugin").mkdir(parents=True)
        assert seat.mod_args(tmp_path / "half") == []

    def test_this_repository_ships_the_mod_beside_the_driver(self, seat):
        assert seat.MOD_DIR == TOOLS_CC / "mods" / "own-clear"
        assert seat.mod_args() == ["--plugin-dir", str(seat.MOD_DIR)]


class TestTheModReadsWhatTheDriverWrites:
    """The Python side and the TypeScript side share a contract no test could
    see across the language line: the marker's path and states, the flag the
    launcher exports, and the two variables the catalog lists. Dies to: a
    rename on one side the other side's tests stay green over."""

    def test_the_marker_path_and_its_states_match_the_writer(self, ship, module_text):
        assert f"const MARKER = '{ship.STATE_DIR}/{ship.OWN_CLEAR_MARKER}'" in module_text
        for state in ("'armed'", "'consumed'", "'stale'"):
            assert state in module_text
        assert '"state": "armed"' in (TOOLS_CC / "ship.py").read_text(encoding="utf-8")

    def test_the_launchers_flag_is_the_drivers_gate(self, ship, seat):
        assert ship.OWN_CLEAR_ENV == seat.OWN_CLEAR_KEY == "ESPALIER_OWN_CLEAR"
        assert seat.OWN_CLEAR_KEY in seat.OWN_CLEAR_ENV

    def test_the_mod_names_its_two_variables_literally(self, seat, module_text):
        """The engine lists what a module reads and refuses a constant at
        `$.env.get`; the catalog rows cite these literals."""
        for name in ("ESPALIER_OWN_CLEAR_ROOT", "ESPALIER_OWN_CLEAR_LOG"):
            assert f"$.env.get('{name}')" in module_text
            assert name in seat.OWN_CLEAR_ENV

    @pytest.mark.skipif(shutil.which("claude") is None, reason="claude is not on PATH")
    def test_the_engine_accepts_the_manifest_and_the_module(self, seat):
        """`claude plugin validate` reads the module as the engine will (the
        env-literal rule is checked there); a refused module loads nowhere."""
        done = subprocess.run(["claude", "plugin", "validate", str(seat.MOD_DIR)], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=30)
        assert "Validation passed" in done.stdout, done.stdout[-600:] + done.stderr[-300:]


class TestReprimeText:
    """The brief a cleared window is re-primed with: the role brief with its
    loop line replaced by the note that a loop started in that window
    survived (DEF-4052: the interval loop survives a /clear, measured
    2026-10-15). Dies to: a loop line in the text (a second loop in the same
    window) or a note that does not name the interval."""

    def test_the_worker_brief_loses_its_loop_line_and_gains_the_note(self, seat, tmp_path):
        brief = seat.compose_brief(tmp_path, "box", tmp_path)
        assert brief.role == "worker" and brief.text.endswith("\n" + brief.loop)
        text = seat.reprime_text(brief)
        assert "/loop" not in text
        assert text.startswith(brief.text[: -len(brief.loop) - 1])
        assert "survived the clear" in text and "start no second one" in text and "every 10m" in text

    def test_the_dispatcher_brief_too(self, seat, tmp_path):
        (tmp_path / "espalier.toml").write_text('dispatcher = "box"\n', encoding="utf-8")
        brief = seat.compose_brief(tmp_path, "box", tmp_path)
        assert brief.role == "dispatcher"
        text = seat.reprime_text(brief)
        assert "/loop" not in text and "every 15m" in text and "survived the clear" in text

    def test_a_brief_whose_text_does_not_end_with_its_loop_keeps_the_text_whole(self, seat):
        brief = seat.Brief("worker", "a brief without its loop", "/loop 10m tick")
        text = seat.reprime_text(brief)
        assert text.startswith("a brief without its loop\n")
        assert "survived the clear" in text and "/loop" not in text
