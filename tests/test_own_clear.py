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
import re
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
                          "brief": "the brief\nits note", "landed": True, "outcome": None,
                          "written_at": marker["written_at"]}
        assert marker["written_at"].endswith("+00:00")
        assert "own-clear armed for session s-1" in line and "box" in line
        assert [p.name for p in (tmp_path / ".espalier-state").iterdir()] == ["own_clear.json"]

    def test_a_held_arm_records_the_refusal_and_whether_the_push_landed(self, ship, tmp_path):
        """DEF-4057: the marker says why the handoff did not land, so the record
        on disk outlives the window that printed it."""
        ship.arm_own_clear(tmp_path, session_id="s-1", head=HEAD, seat="box", role="worker", brief="b",
                           landed=False, outcome="main red after merge")
        marker = _marker(tmp_path)
        assert marker["landed"] is False and marker["outcome"] == "main red after merge"

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

    def test_a_handoff_refused_on_the_red_base_arms_with_the_lane_to_land_in_the_brief(
            self, ship, seat, repo, monkeypatch):
        """DEF-4057: the window is done with the lane (its row written, the
        tree clean) and the next window must land it before any new job, so
        the brief says so after the role brief: the refusal, the branch and
        the verbs. The tail keeps the brief's rules (ASCII, no double quote,
        no percent), whatever the refusal's text carried."""
        monkeypatch.chdir(repo)
        _in_a_mod_window(monkeypatch)
        held = ship.Held('main red after merge: run 9 concluded "failure" (100% red — read it)', landed=False)
        line = ship.arm_own_clear_here(repo, held=held)
        marker = _marker(repo)
        assert marker["landed"] is False and marker["outcome"] == str(held)
        role_brief = seat.reprime_text(seat.compose_brief(repo, "box", repo))
        assert marker["brief"].startswith(role_brief)
        tail = marker["brief"][len(role_brief):]
        assert "THE HANDOFF DID NOT LAND THIS LANE" in tail and "The push was refused" in tail
        assert "main red after merge" in tail and _git(repo, "branch", "--show-current") in tail
        for verb in ("ship.py status", "ship.py open", "ship.py rebind"):
            assert verb in tail
        assert tail.isascii() and '"' not in tail and "%" not in tail
        assert "with the refusal in its brief" in line and "lands the lane first" in line

    def test_a_push_that_landed_then_refused_says_so_in_the_brief(self, ship, repo, monkeypatch):
        monkeypatch.chdir(repo)
        _in_a_mod_window(monkeypatch)
        ship.arm_own_clear_here(repo, held=ship.Held("the push landed, then: gh pr edit failed", landed=True))
        marker = _marker(repo)
        assert marker["landed"] is True
        assert "The push landed and a step after it refused" in marker["brief"]

    def test_an_unnamed_seat_still_gets_the_lane_to_land(self, ship, repo, monkeypatch):
        """No role brief composes, yet the next window must be told: the tail
        rides alone rather than the mod's generic line."""
        monkeypatch.chdir(repo)
        _in_a_mod_window(monkeypatch)
        _git(repo, "config", "--unset", "espalier.machine")
        ship.arm_own_clear_here(repo, held=ship.Held("main red after merge", landed=False))
        brief = _marker(repo)["brief"]
        assert brief is not None and brief.startswith(ship.GENERIC_BRIEF)
        assert "start no second one" in brief and "THE HANDOFF DID NOT LAND THIS LANE" in brief


def _with_origin(repo: Path) -> None:
    """A bare origin the lane is pushed to with an upstream set: what a
    hand-opened lane looks like to git."""
    bare = repo.parent / "origin.git"
    _git(repo, "init", "--quiet", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "--quiet", "-u", "origin", "main")


class TestTheByHandArm:
    """``ship.py arm``: the handoff's last act by hand, for a lane opened by
    hand (``gh pr create``; air-work's #353 on 2026-10-30 ran no verb, left no
    marker, and its window sat past the threshold) or a handoff whose arm did
    not run. Only over a lane that is on origin (the failure-mode review: a
    handoff refused for a reason the window must fix first could otherwise be
    cleared past with the plain role brief, the lane left unpushed and
    unmentioned), and never over a marker already armed for this session (a
    held marker's tail would be dropped). Dies to: an arm on a dirty tracked
    tree (the verb would promise a clear the mod holds), an arm outside a mod
    window that exits 0 as if it had armed, or an arm over an unpushed lane."""

    def test_it_arms_for_this_session_and_records_why(self, ship, repo, monkeypatch, capsys):
        monkeypatch.chdir(repo)
        _in_a_mod_window(monkeypatch)
        _with_origin(repo)
        assert ship.arm(why="hand-opened #353") == 0
        marker = _marker(repo)
        assert marker["session_id"] == "s-here" and marker["landed"] is True
        assert marker["outcome"] == "armed by hand: hand-opened #353"
        assert "THE HANDOFF DID NOT LAND" not in (marker["brief"] or "")
        assert "own-clear armed" in capsys.readouterr().out

    def test_a_lane_not_on_origin_is_refused_and_names_the_verbs_that_land_it(self, ship, repo, monkeypatch):
        monkeypatch.chdir(repo)
        _in_a_mod_window(monkeypatch)
        with pytest.raises(ship.Refused, match="never pushed"):
            ship.arm()
        _with_origin(repo)
        (repo / "README.md").write_bytes(b"more\n")
        _git(repo, "commit", "--quiet", "-am", "ahead")
        with pytest.raises(ship.Refused, match="1 commit") as stop:
            ship.arm()
        assert "/handoff" in str(stop.value) and "ship.py open" in str(stop.value)
        assert not (repo / ".espalier-state" / "own_clear.json").exists()

    def test_a_marker_already_armed_for_this_session_is_kept(self, ship, repo, monkeypatch):
        monkeypatch.chdir(repo)
        _in_a_mod_window(monkeypatch)
        _with_origin(repo)
        ship.arm_own_clear_here(repo, held=ship.Held("main red after merge", landed=False))
        before = _marker(repo)
        with pytest.raises(ship.Refused, match="already armed") as plain:
            ship.arm(why="again")
        assert _marker(repo) == before
        assert "clears this window at the turn's end" in str(plain.value) and "refused" not in str(plain.value)
        # The mod's record of a refused clear (DEF-5031): the refusal says so and
        # sends the operator to the hand clear, not a second arm.
        path = repo / ".espalier-state" / "own_clear.json"
        path.write_text(json.dumps({**before, "clear_refusals": 41, "clear_refused": "HooksError: x"}), encoding="utf-8")
        with pytest.raises(ship.Refused, match="already armed") as refused:
            ship.arm(why="again")
        assert "refused its clear 41 time(s)" in str(refused.value) and "/clear by hand" in str(refused.value)
        assert "clears this window at the turn's end" not in str(refused.value)

    def test_a_dirty_tracked_tree_is_refused_and_nothing_is_armed(self, ship, repo, monkeypatch):
        monkeypatch.chdir(repo)
        _in_a_mod_window(monkeypatch)
        _with_origin(repo)
        (repo / "README.md").write_bytes(b"edited\n")
        with pytest.raises(ship.Refused, match="dirty"):
            ship.arm()
        assert not (repo / ".espalier-state" / "own_clear.json").exists()

    def test_outside_a_mod_window_it_refuses_by_name(self, ship, repo, monkeypatch):
        monkeypatch.chdir(repo)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-here")
        with pytest.raises(ship.Refused, match="did not load the own-clear mod"):
            ship.arm()
        assert not (repo / ".espalier-state" / "own_clear.json").exists()

    def test_a_dry_run_arms_nothing_and_says_what_it_would(self, ship, repo, monkeypatch, capsys):
        monkeypatch.chdir(repo)
        _in_a_mod_window(monkeypatch)
        _with_origin(repo)
        assert ship.arm(dry_run=True) == 0
        assert not (repo / ".espalier-state" / "own_clear.json").exists()
        assert "dry-run" in capsys.readouterr().out

    def test_the_verb_runs_through_main(self, ship, repo, monkeypatch):
        monkeypatch.chdir(repo)
        _in_a_mod_window(monkeypatch)
        _with_origin(repo)
        assert ship.main(["arm", "--why", "x"]) == 0
        assert _marker(repo)["outcome"] == "armed by hand: x"
        args = ship.build_parser().parse_args(["arm", "--why", "x", "--dry-run"])
        assert args.verb == "arm" and args.why == "x" and args.dry_run


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


class TestTheRecordTheModWritesIsWhatTheHooksRead:
    """DEF-5031, DEF-5032 (2026-10-30): the marker's record crosses the language
    line twice -- the mod (TypeScript) writes it, the banner's ``Own-clear:``
    line (``session_start.py``) and the router's advisory (``task_router.py``)
    read it. The field names are pinned here on all three sides, and the two
    fixes' shapes are pinned by text in the module, since no Python test drives
    the mod's hooks (the kit does, ``claude plugin test``). Dies to: a field
    renamed on one side, the refusal record dropped or written with the state
    moved off ``armed``, or the ``lastId`` guard loosened back to the
    unconditional write that took the new session's id under a pending clear."""

    #: What the mod writes beyond the arm's own fields; the readers below read a subset.
    FIELDS = ("clear_asked_at", "clear_refused", "clear_refusals", "clear_refused_at", "clear_resolved_at",
              "turns_since_ask", "previous_session_id", "stale_because")

    def test_every_field_the_hooks_read_is_one_the_mod_writes(self, module_text):
        banner = (TOOLS_CC / "hooks" / "session_start.py").read_text(encoding="utf-8")
        router = (TOOLS_CC / "hooks" / "task_router.py").read_text(encoding="utf-8")
        for field in self.FIELDS:
            assert field in module_text, f"the mod no longer writes {field}"
        for name in ("clear_refusals", "clear_refused", "clear_asked_at", "clear_resolved_at", "turns_since_ask",
                     "stale_because"):
            assert f'"{name}"' in banner, f"the banner no longer reads {name}"
        for name in ("clear_refusals", "clear_refused", "clear_asked_at", "clear_refused_at"):
            assert f'"{name}"' in router, f"the router no longer reads {name}"
        assert 'OWN_CLEAR_MARKER = "own_clear.json"' in banner
        assert '_OWN_CLEAR_MARKER = "own_clear.json"' in router

    def test_a_refusal_is_recorded_with_the_state_left_armed(self, module_text):
        """DEF-5031's guard: the rejected ask's continuation writes the reason,
        the count and the time onto the armed marker, and never its state (Gate
        5, the handoff's refusal of a second arm and the mod's own retry all
        read ``armed``)."""
        assert "clear_refused: reason" in module_text, "the refusal is not recorded on the marker"
        # The rejection handler is the second argument of the one then(), so a
        # throw in the fulfilment handler is never read as a refusal.
        start = module_text.index("}, async err => {")
        rejected = module_text[start:module_text.index("return next(e)", start)]
        assert "clear_refusals: count" in rejected and "clear_refused_at" in rejected
        assert "state:" not in rejected
        assert ".catch(" not in module_text[module_text.rindex("$.command", 0, start):start]

    def test_a_pending_clear_holds_the_last_session(self, module_text):
        """DEF-5032's guard: a turn's end writes ``lastId`` only outside a
        pending clear or for the asked session; the clear's SessionStart reads
        its last session before the marker (three engine round-trips a turn's
        end could land inside) and takes the marker as its own for the asked
        session, or, with no last session known, by the marker's own ask."""
        assert "if (clearedFor === undefined || id === clearedFor) lastId = id" in module_text, (
            "the turn end writes lastId unconditionally: a queued clear's flip is taken as the last session")
        start = module_text.index("on('classic.SessionStart'")
        handler = module_text[start:module_text.find("\n  on('", start + 1)]
        assert handler.index("const before = lastId") < handler.index("await readMarker($)")
        assert "marker.session_id === asked" in handler
        assert "recentAsk(marker, now)" in handler, "the reload arm no longer reads the marker's own ask, bounded"

    def test_a_session_start_under_a_pending_clear_keeps_the_asked_session(self, module_text):
        """The third defense, pinned alone (the failure-mode review drove the
        kit with each of the three removed and found the others covering):
        ``session.start`` resets the module's memory only outside a pending
        clear, so an engine that raised it at a clear would not hand the new id
        to the clear's SessionStart as this process's last."""
        start = module_text.index("on('session.start'")
        handler = module_text[start:module_text.find("\n  on('", start + 1)]
        assert "if (clearedFor === undefined) {" in handler, "session.start resets lastId under a pending clear"
        assert handler.index("if (clearedFor === undefined) {") < handler.index("lastId = id")


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

    def test_the_stop_gate_reads_the_marker_the_driver_writes(self, ship, module_text):
        """Gate 5 lets a Stop through over a marker armed at HEAD (DEF-4057), and
        the generic brief the driver puts before a held tail is the mod's own
        line: both pinned by text, since neither side imports the other."""
        gate = (TOOLS_CC / "hooks" / "stop_gate.py").read_text(encoding="utf-8")
        assert f'OWN_CLEAR_MARKER = "{ship.OWN_CLEAR_MARKER}"' in gate
        for phrase in ("cleared by the own-clear", "start no second one"):
            assert phrase in ship.GENERIC_BRIEF and phrase in module_text

    def test_the_mod_names_its_two_variables_literally(self, seat, module_text):
        """The engine lists what a module reads and refuses a constant at
        `$.env.get`; the catalog rows cite these literals."""
        for name in ("ESPALIER_OWN_CLEAR_ROOT", "ESPALIER_OWN_CLEAR_LOG"):
            assert f"$.env.get('{name}')" in module_text
            assert name in seat.OWN_CLEAR_ENV

    def test_the_in_flight_read_precedes_the_hand_on_of_the_clears_session_start(self, module_text):
        """The project's SessionStart hook runs inside the mod's ``next(e)`` and
        catches the checkout up (a lane branch GitHub deleted at the merge moves
        onto the base), so what the old window left in flight is read before the
        event is handed on, beside the marker; read after it, the catch-up named
        itself as a HEAD move on every re-prime whose lane had merged (the
        dispatcher window 28cea670, 2026-10-30). Pinned by text, since no Python
        test drives the hooks; the kit's case moves HEAD beneath the mod. Read
        with the line comments stripped (the module keeps no ``//`` inside a
        string) and bounded to this handler: the read must be awaited before the
        hand-on and absent after it. Dies to: the read moved back below ``await
        next(e)`` with or without a comment naming it, the hoisted read kept
        and a second one after the hand-on feeding the brief, and the read
        started before the hand-on but awaited after it (the failure-mode
        review drove all four, 2026-10-30)."""
        code = "\n".join(line.split("//", 1)[0] for line in module_text.splitlines())
        start = code.index("on('classic.SessionStart'")
        end = code.find("\n  on('", start + 1)
        handler = code[start:end if end != -1 else None]
        before, hand_on, after = handler.partition("await next(e)")
        assert hand_on, "the handler no longer hands the event on with `await next(e)`"
        assert "await inFlight(" in before, (
            "the in-flight read is not awaited before the hand-on: the catch-up beneath reads as a HEAD move")
        assert "inFlight(" not in after, (
            "an in-flight read after the hand-on reads the caught-up checkout, not the old window")

    def test_every_git_read_hands_on_why_it_failed(self, module_text):
        """DEF-3019 (2026-10-31): the ``git()`` helper kept stdout alone, so
        win-2's 06:25Z re-prime said 'HEAD could not be read' while HEAD
        equalled the marker's head, and nothing said why. The kit hands each
        read a failing value and reads the reason back, but no CI cell installs
        ``claude``, so the shape is pinned here by text, line comments stripped.
        Dies to: the helper dropping git's stderr again, and a git read whose
        reason its caller never reads (a new ``git(`` call included)."""
        code = "\n".join(line.split("//", 1)[0] for line in module_text.splitlines())
        start = code.index("async function git(")
        helper = code[start:code.index("\n}\n", start)]
        assert ".stderr" in helper, "the git helper drops git's own words again"
        reads = re.findall(r"const (\w+) = await git\(", code)
        assert reads, "no git read found: the helper's callers were renamed past this pin"
        for name in reads:
            assert f"{name}.why" in code, f"the git read `{name}` drops why it failed"

    @pytest.mark.skipif(shutil.which("claude") is None, reason="claude is not on PATH")
    def test_the_engine_accepts_the_manifest_and_the_module(self, seat):
        """`claude plugin validate` reads the module as the engine will (the
        env-literal rule is checked there); a refused module loads nowhere."""
        done = subprocess.run(["claude", "plugin", "validate", str(seat.MOD_DIR)], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=30)
        assert "Validation passed" in done.stdout, done.stdout[-600:] + done.stderr[-300:]

    @pytest.mark.skipif(shutil.which("claude") is None, reason="claude is not on PATH")
    def test_the_engine_runs_the_kit_green_with_every_case_counted(self, seat):
        """`claude plugin test` is the mod's own kit, and no workflow runs it
        (the cells install no `claude`), so the suite drives it wherever the
        engine is on PATH: green, with as many passes as the kit file holds
        cases, so the count is derived and never kept by hand. The failure-mode
        review (2026-10-30) drove three refactors of the SessionStart handler
        that only the kit catches; without this case a lane could merge them on
        a green tier."""
        done = subprocess.run([shutil.which("claude"), "plugin", "test", str(seat.MOD_DIR)], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=30)
        cases = (seat.MOD_DIR / "hooks" / "own-clear.test.ts").read_text(encoding="utf-8").count("\ntest(")
        assert cases > 0, "no case found in the kit file"
        assert done.returncode == 0 and f" {cases} pass" in done.stdout and " 0 fail" in done.stdout, (
            done.stdout[-800:] + done.stderr[-300:])


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


class TestTheBenchDriverLoadsWhereThereIsNoPty:
    """``bench/own_clear/drive.py`` is POSIX (it forks a pty) and the Windows
    seats are driven by hand -- but it must still LOAD on Windows: the
    bounded-spawn census (``tests/test_contracts.py::
    TestEveryTimedSpawnOutsideToolsCcIsBounded``) imports every file outside
    the engine that routes a spawn, to read which ``run_bounded`` it bound,
    and a module-level ``import fcntl`` made that read ``ModuleNotFoundError``
    on windows-latest (red on main from #351, 2026-10-27). The three
    POSIX-only modules are made unimportable the way the import system reads
    ``None`` in ``sys.modules`` (``ImportError``), on any host. Dies to: one of
    those three back at module level, or a main that makes its output
    directory before it refuses. The tuple below is typed by hand, so a
    fourth POSIX-only name (``resource``, ``pwd``, ``grp``) imported bare would
    pass here and red Windows again: the census-level stand-in that derives
    the file set is the class fix (the failure-mode review, 2026-10-29)."""

    POSIX_ONLY = ("fcntl", "pty", "termios")

    def _load_without_a_pty(self, monkeypatch):
        for name in self.POSIX_ONLY:
            monkeypatch.setitem(sys.modules, name, None)
        path = REPO_ROOT / "bench" / "own_clear" / "drive.py"
        spec = importlib.util.spec_from_file_location("own_clear_drive_without_a_pty", path)
        mod = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, mod)
        try:
            spec.loader.exec_module(mod)
        except ImportError as exc:   # the Windows census read: a failure by name, not a traceback
            pytest.fail(f"the driver does not load where there is no pty: {type(exc).__name__}: {exc}")
        return mod

    def test_the_driver_loads_and_binds_this_checkouts_bounded_spawn(self, monkeypatch):
        mod = self._load_without_a_pty(monkeypatch)
        assert Path(mod.run_bounded.__code__.co_filename).resolve() == (TOOLS_CC / "_json_safe.py").resolve()
        assert mod.fcntl is None and mod.pty is None and mod.termios is None

    def test_main_refuses_by_name_before_it_writes(self, monkeypatch, tmp_path, capsys):
        mod = self._load_without_a_pty(monkeypatch)
        out = tmp_path / "drive-out"
        assert mod.main(["--out", str(out)]) == 2
        assert not out.exists()
        err = capsys.readouterr().err
        assert "POSIX" in err and "pty" in err and "Windows" in err and "by hand" in err
