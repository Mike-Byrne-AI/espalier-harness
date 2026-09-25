"""Contracts for ``scripts/fresh_clone_gate.py`` -- the release gate that runs
the full tier in a fresh clone per interpreter.

The pure helpers are pinned directly (the child environment is the whitelist
projection with the venv first; the tier's receipt is read by its tail in BOTH
real spellings and its counts consumed; the runners must resolve under the
venv and the engine under the clone; the worst leg wins and a refusal is 70;
two specs naming one interpreter refuse before any clone). One integration
class drives the whole gate against a scratch repository whose
``scripts/proof_tier.py`` is a stub that records the environment it saw,
declares the full tier's command count and prints whichever receipt the row
asks for -- so the stressor (a leg that ran nothing; a leg that ran and
failed; a venv whose engine is another tree's) is asserted, not assumed.
The receipt regex is pinned against the real producer by running it.

Why this file pins each control separately: a gate that greens on an absent
stressor guards nothing, and every control here was added because a review
named the way it would be bypassed -- the whitelist because a prefix scrub
leaves carriers in place, the counts because a shrunken tier printed a green
receipt, the engine probe because an editable finder from another tree
outranks the clone. Each row prevents one of those from drifting back.
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "fresh_clone_gate.py"
PROOF_TIER_PATH = REPO_ROOT / "scripts" / "proof_tier.py"
if not MODULE_PATH.is_file():
    pytest.skip("scripts/fresh_clone_gate.py is dev tooling not shipped in the sdist",
                allow_module_level=True)

# Marker assignment lives in tests/conftest.py::_MARKER_RULES (integration).

_TAG = f"{sys.version_info[0]}.{sys.version_info[1]}"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gate():
    return _load("fresh_clone_gate", MODULE_PATH)


# ── the child environment ──────────────────────────────────────────────────


class TestChildEnv:
    def test_the_child_env_is_the_whitelist_projection_with_the_venv_first(self, gate, tmp_path):
        parent = {
            "PATH": "/usr/bin:/bin", "HOME": "/h", "TERM": "xterm",
            "PYTEST_XDIST_AUTO_NUM_WORKERS": "4",
            # the carriers a prefix scrub leaves in place -- every one absent below
            "PYTHONPATH": "/x", "VIRTUAL_ENV": "/v", "PIP_INDEX_URL": "http://x",
            "ESPALIER_MAINTENANCE_MODE": "1", "CLAUDE_PROJECT_DIR": "/c", "RANDOM_KEY": "1",
        }
        env = gate.child_env(parent, tmp_path / "venv")
        assert env["PATH"].split(os.pathsep)[0] == str(gate.venv_bin(tmp_path / "venv"))
        assert env["PATH"].endswith(os.pathsep + "/usr/bin:/bin")
        assert set(env) == {"PATH", "HOME", "TERM", "PYTEST_XDIST_AUTO_NUM_WORKERS"}

    def test_an_unset_passthrough_stays_unset(self, gate, tmp_path):
        env = gate.child_env({"PATH": "/bin"}, tmp_path / "venv")
        assert "PYTEST_XDIST_AUTO_NUM_WORKERS" not in env and "PYTEST_ADDOPTS" not in env

    def test_the_whitelist_names_no_carrier(self, gate):
        for key in gate.ENV_WHITELIST:
            assert not key.startswith(("ESPALIER_", "CLAUDE_", "PIP_", "PYTHON")) and key != "VIRTUAL_ENV", key

    def test_the_passthroughs_are_echoed_set_or_unset(self, gate):
        lines = gate.passthrough_lines({"PYTEST_ADDOPTS": "-rs"})
        assert "passthrough PYTEST_ADDOPTS=-rs" in lines
        assert any(line.startswith("passthrough PYTEST_XDIST_AUTO_NUM_WORKERS=<unset>") and "one worker per" in line
                   for line in lines)
        assert set(gate.PASSTHROUGH_KEYS) <= set(gate.ENV_WHITELIST)


# ── the receipt ────────────────────────────────────────────────────────────


class TestReceipt:
    @pytest.mark.parametrize("text,expected", [
        ("proof: PASS -- 3 of 3 command(s) ran\n", ("PASS", 0, 3, 3)),
        ("exit 1: pytest -q\nproof: FAIL (worst exit 1) -- 3 of 3 command(s) ran\n", ("FAIL", 1, 3, 3)),
        ("noise\nproof: FAIL (worst exit 2) -- 3 of 3 command(s) ran\ntrailing\n", ("FAIL", 2, 3, 3)),
        # the tier's untracked-files refusal prints no receipt at all
        ("contract\nrun: pytest -m contract -q\nuntracked -- invisible ...\n  git add -N x\n", None),
        ("", None),
    ])
    def test_both_real_spellings_read_as_ran_and_silence_as_none(self, gate, text, expected):
        assert gate.read_receipt(text) == expected

    def test_the_last_receipt_wins(self, gate):
        text = "proof: PASS -- 3 of 3 command(s) ran\nproof: FAIL (worst exit 4) -- 3 of 3 command(s) ran\n"
        assert gate.read_receipt(text) == ("FAIL", 4, 3, 3)

    def test_the_receipt_regex_reads_what_proof_tier_actually_prints(self, gate, capsys, monkeypatch):
        """Pinned against the PRODUCER, not a re-spelling: run
        `proof_tier.run_commands` on one trivial command and read its
        receipt back (red-team lane A: three restatements, zero links)."""
        pt = _load("proof_tier_for_the_gate", PROOF_TIER_PATH)
        rc = pt.run_commands([("pytest", "--version")], REPO_ROOT)
        out = capsys.readouterr().out
        assert rc == 0, out
        assert gate.read_receipt(out) == ("PASS", 0, 1, 1), out
        # and the failing spelling, through the same producer
        monkeypatch.setattr(pt.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 3))
        rc = pt.run_commands([("pytest", "--version"), ("mypy", "x")], REPO_ROOT)
        out = capsys.readouterr().out
        assert rc == 3
        assert gate.read_receipt(out) == ("FAIL", 3, 2, 2), out

    def test_the_counts_are_consumed(self, gate, tmp_path):
        log = tmp_path / "leg.log"
        log.write_text("x\n", encoding="utf-8")
        assert gate.check_receipt(("PASS", 0, 3, 3), 3, "3.14", log) == ("PASS", 0, 3, 3)
        with pytest.raises(gate.GateRefusal, match=r"reported 1 of 1 command\(s\) ran .* declares 3"):
            gate.check_receipt(("PASS", 0, 1, 1), 3, "3.14", log)
        with pytest.raises(gate.GateRefusal, match=r"reported 2 of 3"):
            gate.check_receipt(("FAIL", 1, 2, 3), 3, "3.14", log)
        with pytest.raises(gate.GateRefusal, match=r"NOTHING RAN \(3\.14\)"):
            gate.check_receipt(None, 3, "3.14", log)

    def test_the_full_tier_count_comes_from_the_clones_own_proof_tier(self, gate, tmp_path):
        assert gate.full_tier_command_count(REPO_ROOT) == 3
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "proof_tier.py").write_text("FULL_COMMANDS = ('a', 'b')\n", encoding="utf-8")
        assert gate.full_tier_command_count(tmp_path) == 2
        with pytest.raises(gate.GateRefusal, match="missing"):
            gate.full_tier_command_count(tmp_path / "nowhere")


# ── interpreter and runner resolution ──────────────────────────────────────


class TestInterpreterResolution:
    def test_an_existing_executable_is_itself(self, gate):
        assert gate.resolve_interpreter(sys.executable) == Path(sys.executable).resolve()

    def test_a_directory_named_like_a_version_is_not_an_interpreter(self, gate, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "3.10").mkdir()
        assert gate.resolve_interpreter("3.10", find=lambda v: sys.executable) == Path(sys.executable).resolve()

    def test_a_bare_version_goes_through_the_finder(self, gate):
        assert gate.resolve_interpreter("3.10", find=lambda v: sys.executable) == Path(sys.executable).resolve()

    def test_a_bare_version_the_finder_cannot_place_is_refused(self, gate):
        with pytest.raises(gate.GateRefusal, match=r"uv python install 3\.10"):
            gate.resolve_interpreter("3.10", find=lambda v: None)

    def test_a_bare_version_without_uv_is_refused_naming_the_install(self, gate, monkeypatch):
        monkeypatch.setattr(gate.shutil, "which", lambda name, path=None: None)
        with pytest.raises(gate.GateRefusal, match="needs `uv` on PATH"):
            gate.resolve_interpreter("3.10")

    def test_an_unknown_name_is_refused(self, gate, monkeypatch):
        monkeypatch.setattr(gate.shutil, "which", lambda name, path=None: None)
        with pytest.raises(gate.GateRefusal, match="not an executable file, not a version, not on PATH"):
            gate.resolve_interpreter("no-such-interpreter")

    def test_two_specs_naming_one_interpreter_refuse_before_any_clone(self, gate):
        with pytest.raises(gate.GateRefusal, match=r"both " + _TAG.replace(".", r"\.") + " -- one clone per"):
            gate.resolve_all([sys.executable, str(Path(sys.executable).resolve())])
        assert [tag for _, _, tag in gate.resolve_all([sys.executable])] == [_TAG]

    def test_the_default_interpreter_is_a_base_install(self, gate):
        exe = gate.default_interpreter()
        assert exe.is_file()
        probe = subprocess.run(
            [str(exe), "-c", "import sys; print(sys.prefix == sys.base_prefix)"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        assert probe.stdout.strip() == "True", (exe, probe.stdout, probe.stderr)


def _plant(bin_dir: Path, name: str) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = bin_dir / name
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return exe


@pytest.mark.skipif(sys.platform == "win32", reason="planted POSIX executables")
class TestRunnerResolution:
    def test_runners_under_the_venv_resolve_and_are_named(self, gate, tmp_path):
        venv = tmp_path / "venv"
        for name in gate.RUNNERS:
            _plant(gate.venv_bin(venv), name)
        env = gate.child_env({"PATH": str(tmp_path / "nowhere")}, venv)
        found = gate.resolve_runners(env, venv)
        assert set(found) == set(gate.RUNNERS)
        assert all(gate._under(p, venv) for p in found.values())

    def test_a_host_runner_ahead_of_the_venv_is_refused_naming_it(self, gate, tmp_path):
        """PATH-first is the control, not a guarantee: a venv with no `pytest`
        lets the search fall through to the host's. The gate refuses."""
        venv = tmp_path / "venv"
        gate.venv_bin(venv).mkdir(parents=True)
        host = _plant(tmp_path / "hostbin", "pytest")
        _plant(tmp_path / "hostbin", "mypy")
        env = gate.child_env({"PATH": str(tmp_path / "hostbin")}, venv)
        with pytest.raises(gate.GateRefusal, match=r"outside the venv") as exc:
            gate.resolve_runners(env, venv)
        assert str(host.resolve()) in str(exc.value)

    def test_a_missing_runner_is_refused_with_the_install_line(self, gate, tmp_path):
        venv = tmp_path / "venv"
        _plant(gate.venv_bin(venv), "pytest")  # no mypy
        env = gate.child_env({"PATH": str(tmp_path / "nowhere")}, venv)
        with pytest.raises(gate.GateRefusal, match=r"`mypy` does not resolve"):
            gate.resolve_runners(env, venv)


# ── aggregation ────────────────────────────────────────────────────────────


class TestReceiptLinesFlush:
    def test_every_echo_flushes(self, gate, monkeypatch):
        """A redirected gate run must show each receipt line as it happens: the
        first real run printed two lines in fifty minutes because the leg echo
        went through a block-buffered `print` (driven 2026-09-22)."""
        calls = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: calls.append(k))
        gate.say("x")
        assert calls == [{"flush": True}]
        import inspect
        for fn in (gate.run_leg, gate.run_tier):
            assert inspect.signature(fn).parameters["echo"].default is gate.say, fn.__name__


class TestAggregation:
    def test_the_worst_leg_wins(self, gate):
        legs = [gate.Leg(spec="a", rc=0), gate.Leg(spec="b", rc=1), gate.Leg(spec="c", rc=0)]
        assert gate.aggregate(legs) == 1

    def test_a_refused_leg_is_70_whatever_the_others_did(self, gate):
        legs = [gate.Leg(spec="a", rc=0), gate.Leg(spec="b", refused="no receipt")]
        assert gate.aggregate(legs) == gate.GATE_REFUSED == 70

    def test_all_green_is_zero(self, gate):
        assert gate.aggregate([gate.Leg(spec="a", rc=0), gate.Leg(spec="b", rc=0)]) == 0

    def test_the_refusal_code_is_outside_pytests(self, gate):
        assert gate.GATE_REFUSED not in range(0, 6)

    def test_a_crash_anywhere_is_70_never_pytests_1(self, gate, tmp_path, capsys):
        rc = gate.main(["--root", str(tmp_path / "nope")])
        out = capsys.readouterr().out
        assert rc == 70
        assert out.startswith("gate: REFUSED"), out


# ── the scratch repository and the stub tier ───────────────────────────────

_STUB_TIER = '''\
"""A stub proof tier: declares the full tier's command count like the real one,
records the environment it saw, prints the receipt the row asked for."""
import json, os, sys, pathlib
FULL_COMMANDS = ("mypy tools/cc/hooks/", "pytest -q -n auto", "pytest -q serial")
if __name__ == "__main__":
    mode = pathlib.Path("gate_stub_mode").read_text(encoding="utf-8").strip()
    pathlib.Path("gate_stub_env.json").write_text(json.dumps(dict(os.environ)), encoding="utf-8")
    print("full")
    if mode == "pass":
        print("proof: PASS -- 3 of 3 command(s) ran"); sys.exit(0)
    if mode == "fail":
        print("exit 1: pytest -q"); print("proof: FAIL (worst exit 1) -- 3 of 3 command(s) ran"); sys.exit(1)
    if mode == "short":
        print("proof: PASS -- 1 of 1 command(s) ran"); sys.exit(0)
    print("untracked -- invisible to the git ls-files gates until staged:"); sys.exit(2)
'''


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@x"},
    )


def _stub_repo(tmp_path: Path, mode: str, *, with_engine: bool = True) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "proof_tier.py").write_text(_STUB_TIER, encoding="utf-8")
    (repo / "gate_stub_mode").write_text(mode + "\n", encoding="utf-8")
    if with_engine:
        (repo / "espalier").mkdir()
        (repo / "espalier" / "__init__.py").write_text("", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "stub")
    return repo


def _venv_with_planted_runners(gate, where: Path) -> Path:
    subprocess.run(
        [str(gate.default_interpreter()), "-m", "venv", "--without-pip", str(where)], check=True,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    for name in gate.RUNNERS:
        _plant(gate.venv_bin(where), name)
    return where


#: Keys the platform writes into every process it starts, which no gate can
#: keep out: macOS CoreFoundation sets the first in each child; older macOS
#: framework Pythons set the second from the venv launcher. Named here so the
#: whole-environment assertion below tolerates exactly these and nothing else.
_PLATFORM_INJECTED = frozenset({"__CF_USER_TEXT_ENCODING", "__PYVENV_LAUNCHER__"})


@pytest.mark.skipif(sys.platform == "win32", reason="planted POSIX executables")
class TestTheGateEndToEndOnAStubTier:
    """The whole gate driven on a scratch repository: the stub tier records
    the environment the real tier would see and prints the receipt the row
    asks for. Mutations this class dies to (driven at landing): the whitelist
    replaced by a prefix scrub (the planted carriers reappear), the worst-exit
    aggregation removed (the fail row returns 0), the receipt match narrowed
    to the PASS spelling (the fail row reads as NOTHING RAN), the counts left
    unconsumed (the short row passes), the engine check dropped (the
    engineless row passes)."""

    def _drive(self, gate, tmp_path, monkeypatch, capsys, mode: str, *, with_engine: bool = True,
               keep: bool = True, venv_in_scratch: bool = False):
        repo = _stub_repo(tmp_path, mode, with_engine=with_engine)
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        venv = _venv_with_planted_runners(
            gate, (scratch / f"venv-{_TAG}") if venv_in_scratch else (tmp_path / "venv"),
        )
        for key, value in (("PYTHONPATH", "/planted"), ("VIRTUAL_ENV", "/planted"),
                           ("PIP_INDEX_URL", "http://planted"), ("ESPALIER_MAINTENANCE_MODE", "1"),
                           ("PYTEST_XDIST_AUTO_NUM_WORKERS", "2")):
            monkeypatch.setenv(key, value)
        # The rows assert this passthrough reads `<unset>`; the gate passes a
        # parent's PYTEST_ADDOPTS through BY DESIGN, and the first real gate run
        # (launched with `-rs` so the clone's skips are enumerated) carried it
        # into this very row and reddened it. Clear it here, never assume it.
        monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
        argv = ["--root", str(repo), "--python", sys.executable, "--scratch", str(scratch),
                "--reuse-venv", str(venv)]
        if keep:
            argv.append("--keep")
        rc = gate.main(argv)
        out = capsys.readouterr().out
        recorded_path = scratch / f"clone-{_TAG}" / "gate_stub_env.json"
        recorded = json.loads(recorded_path.read_text(encoding="utf-8")) if recorded_path.exists() else None
        return rc, out, recorded, venv

    def test_a_passing_tier_is_a_zero_leg_under_the_whitelisted_env(self, gate, tmp_path, monkeypatch, capsys):
        rc, out, recorded, venv = self._drive(gate, tmp_path, monkeypatch, capsys, "pass")
        assert rc == 0, out
        assert f"PYTEST_EXIT_{_TAG}=0" in out
        assert f"runner pytest={gate.venv_bin(venv).resolve() / 'pytest'}" in out
        engine = (tmp_path / "scratch" / f"clone-{_TAG}" / "espalier" / "__init__.py").resolve()
        assert f"engine espalier={engine}" in out
        assert "passthrough PYTEST_XDIST_AUTO_NUM_WORKERS=2" in out
        assert "passthrough PYTEST_ADDOPTS=<unset>" in out
        assert "gate: PASS -- 1 of 1 interpreter(s) ran; HEAD " in out
        assert recorded is not None
        # the WHOLE recorded environment is the whitelist projection of the parent,
        # plus at most the keys the platform injects into every process
        expected = {k: v for k, v in os.environ.items() if k in gate.ENV_WHITELIST}
        seen = {k: v for k, v in recorded.items() if k != "PATH" and k not in _PLATFORM_INJECTED}
        assert seen == {k: v for k, v in expected.items() if k != "PATH"}
        assert recorded["PATH"].split(os.pathsep)[0] == str(gate.venv_bin(venv))
        for carrier in ("PYTHONPATH", "VIRTUAL_ENV", "PIP_INDEX_URL", "ESPALIER_MAINTENANCE_MODE"):
            assert carrier not in recorded, carrier
        assert recorded["PYTEST_XDIST_AUTO_NUM_WORKERS"] == "2"

    def test_a_failing_tier_is_a_ran_and_failed_leg_never_nothing_ran(self, gate, tmp_path, monkeypatch, capsys):
        rc, out, recorded, _ = self._drive(gate, tmp_path, monkeypatch, capsys, "fail")
        assert rc == 1, out
        assert f"PYTEST_EXIT_{_TAG}=1" in out
        assert "NOTHING RAN" not in out
        assert "gate: FAIL -- 1 of 1 interpreter(s) ran" in out
        assert recorded is not None

    def test_a_tier_that_printed_no_receipt_is_nothing_ran_at_70(self, gate, tmp_path, monkeypatch, capsys):
        rc, out, _, _ = self._drive(gate, tmp_path, monkeypatch, capsys, "silent")
        assert rc == 70, out
        assert f"NOTHING RAN ({_TAG})" in out
        assert "gate: FAIL -- 0 of 1 interpreter(s) ran" in out

    def test_a_tier_that_ran_fewer_commands_than_it_declares_is_refused(self, gate, tmp_path, monkeypatch, capsys):
        rc, out, _, _ = self._drive(gate, tmp_path, monkeypatch, capsys, "short")
        assert rc == 70, out
        assert "reported 1 of 1 command(s) ran" in out and "declares 3" in out

    def test_a_venv_whose_engine_is_not_the_clones_is_refused(self, gate, tmp_path, monkeypatch, capsys):
        """The clone carries no `espalier` package, so the import fails or lands
        elsewhere; either way the tier must not run (red-team lane A: an
        editable finder from another tree outranks `pythonpath`)."""
        rc, out, recorded, _ = self._drive(gate, tmp_path, monkeypatch, capsys, "pass", with_engine=False)
        assert rc == 70, out
        assert "`import espalier`" in out or "outside the clone" in out, out
        assert recorded is None  # the tier never ran

    def test_a_reused_venv_survives_a_green_run_even_inside_the_scratch(self, gate, tmp_path, monkeypatch, capsys):
        rc, out, _, venv = self._drive(gate, tmp_path, monkeypatch, capsys, "pass", keep=False, venv_in_scratch=True)
        assert rc == 0, out
        assert venv.is_dir(), "the reused venv was removed on PASS"
        assert not (tmp_path / "scratch" / f"clone-{_TAG}").exists(), "the run's own clone was kept"


class TestDirtyTree:
    def test_a_dirty_tree_is_refused_before_any_clone(self, gate, tmp_path, capsys):
        repo = _stub_repo(tmp_path, "pass")
        (repo / "stray.txt").write_text("x\n", encoding="utf-8")
        scratch = tmp_path / "scratch"
        rc = gate.main(["--root", str(repo), "--scratch", str(scratch)])
        out = capsys.readouterr().out
        assert rc == 70
        assert "1 path(s) not in HEAD" in out and "--allow-dirty" in out
        assert not (scratch / f"clone-{_TAG}").exists()

    def test_the_dirty_line_says_the_tree_is_not_in_the_proof(self, gate):
        assert gate.dirty_line(3, "abc1234") == "gate: proves HEAD abc1234; 3 path(s) in the working tree are not in it"

    def test_two_specs_naming_one_interpreter_refuse_before_any_clone_through_main(self, gate, tmp_path, capsys):
        repo = _stub_repo(tmp_path, "pass")
        scratch = tmp_path / "scratch"
        rc = gate.main(["--root", str(repo), "--scratch", str(scratch), "--python", sys.executable,
                        "--python", str(Path(sys.executable).resolve())])
        out = capsys.readouterr().out
        assert rc == 70
        assert "one clone per interpreter; drop one" in out
        assert not scratch.exists() or not any(scratch.iterdir())
