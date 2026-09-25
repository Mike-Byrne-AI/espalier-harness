# slow-exempt: the round trip is one bare init, two clones, one commit and a
# fetch on a two-file repository -- measured under two seconds.
"""Pins ``scripts/host_check.py``: the runner that carries a host's suite and
bench results to the remote as one commit, and reads them back elsewhere.

The publish/read round trip is driven on scratch repositories with a local
bare remote, so the property that matters -- the working branch, tree and
index of the running checkout are untouched, and the other side gets the
files under the same path -- is measured rather than asserted from the
plumbing's reputation. No step is actually run: the steps are planned and
their report written from stubbed results.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "host_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("_host_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hc():
    return _load()


def _facts(**over) -> dict:
    base = {
        "host": "MacBook-Air.local", "platform": "x", "python": "3.12.0",
        "executable": sys.executable, "head": "0123456789abcdef", "branch": "main",
        "dirty": False,
        "tools": {"pwsh": None, "powershell": None, "bash": "/bin/bash", "git": "/usr/bin/git"},
        "windows_powershell": None, "espalier_pwsh_override": None,
        "maintenance_mode_in_parent_env": False,
        "utc": "2026-09-10T23:00:00+00:00", "stamp": "20260910-2300",
    }
    base.update(over)
    return base


class TestTheLabel:
    def test_label_is_host_stamp_and_short_head(self, hc):
        assert hc.make_label(_facts()) == "macbook-air-local-20260910-2300-0123456"

    def test_a_hostname_with_spaces_and_case_is_sanitised(self, hc):
        assert hc.make_label(_facts(host="Mike's PC (Win)")).startswith("mike-s-pc-win-")

    def test_latest_is_by_stamp_not_by_name(self, hc):
        labels = ["zzz-20260901-0100-aaaaaaa", "aaa-20260910-2300-bbbbbbb",
                  "mmm-20260905-1200-ccccccc"]
        assert hc.latest_label(labels) == "aaa-20260910-2300-bbbbbbb"


class TestThePlan:
    def test_without_powershell_the_differential_is_planned_as_skipped(self, hc):
        steps = {s["name"]: s for s in hc.plan_steps(_facts())}
        assert set(steps) == {"pytest", "rehearsal", "row-probe", "pwsh-differential"}
        assert steps["pwsh-differential"]["skip"]
        assert steps["pytest"]["skip"] is None and steps["rehearsal"]["skip"] is None
        assert steps["row-probe"]["skip"] is None

    def test_the_51_step_joins_only_when_pwsh_won_the_lookup_on_windows(self, hc):
        both = _facts(tools={"pwsh": "C:/pwsh.exe", "powershell": "C:/ps.exe",
                             "bash": None, "git": "git"},
                      windows_powershell="C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
        names = [s["name"] for s in hc.plan_steps(both)]
        assert names[-1] == "ps51-differential"
        ps51 = hc.plan_steps(both)[-1]
        assert ps51["env"]["ESPALIER_PWSH"] == both["windows_powershell"]
        only_51 = _facts(tools={"pwsh": None, "powershell": "C:/ps.exe", "bash": None, "git": "git"},
                         windows_powershell="C:/x/powershell.exe")
        assert "ps51-differential" not in [s["name"] for s in hc.plan_steps(only_51)]
        overridden = dict(both, espalier_pwsh_override="D:/pwsh/pwsh.exe")
        assert "ps51-differential" not in [s["name"] for s in hc.plan_steps(overridden)]

    def test_a_requested_skip_keeps_the_step_in_the_report(self, hc):
        steps = {s["name"]: s for s in hc.plan_steps(_facts(), {"pytest"})}
        assert steps["pytest"]["skip"] == "skipped on request"

    def test_the_child_env_drops_maintenance_mode_and_forces_utf8(self, hc, monkeypatch):
        monkeypatch.setenv("ESPALIER_MAINTENANCE_MODE", "1")
        env = hc.child_env({"X": "1"})
        assert "ESPALIER_MAINTENANCE_MODE" not in env
        assert env["PYTHONUTF8"] == "1" and env["PYTHONIOENCODING"] == "utf-8"
        assert env["X"] == "1"


class TestTheSummary:
    def test_every_step_appears_with_its_verdict_and_pipes_are_escaped(self, hc, tmp_path):
        facts = _facts(label="lbl")
        results = [
            {"name": "pytest", "rc": 0, "skipped": None, "seconds": 12.5,
             "tail": ["1 passed | 0 failed"]},
            {"name": "rehearsal", "rc": 1, "skipped": None, "seconds": 3.0, "tail": ["red"]},
            {"name": "pwsh-differential", "rc": None, "skipped": "no PowerShell on this host",
             "seconds": 0.0, "tail": []},
            {"name": "ps51-differential", "rc": None, "skipped": None, "seconds": 3600.0,
             "tail": ["[host-check] timed out after 3600 s"]},
        ]
        text = hc.write_summary(tmp_path, facts, results)
        assert "| pytest | 0 | 12.5 | 1 passed \\| 0 failed |" in text
        assert "| rehearsal | 1 | 3.0 | red |" in text
        assert "| pwsh-differential | skipped |" in text
        assert "| ps51-differential | timeout |" in text
        assert (tmp_path / "SUMMARY.md").read_text(encoding="utf-8") == text
        data = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
        assert [r["name"] for r in data["results"]] == [r["name"] for r in results]

    def test_a_skipped_step_writes_its_reason_and_runs_nothing(self, hc, tmp_path):
        step = {"name": "pwsh-differential", "argv": ["never-run"], "env": {},
                "skip": "no PowerShell on this host", "timeout": 1}
        result = hc.run_step(step, tmp_path)
        assert result["skipped"] and result["rc"] is None
        assert (tmp_path / "pwsh-differential.txt").read_text(encoding="utf-8").startswith("skipped:")


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", check=True, timeout=120).stdout.strip()


def _scratch_checkout(root: Path, name: str, remote: Path) -> Path:
    repo = root / name
    subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True, timeout=120)
    _git("config", "user.name", "t", cwd=repo)
    _git("config", "user.email", "t@t", cwd=repo)
    return repo


@pytest.mark.skipif(sys.platform == "win32", reason="plumbing measured on POSIX git")
class TestPublishAndReadRoundTrip:
    """A bare local remote stands in for origin; two clones stand in for the
    two machines."""

    def test_the_report_travels_and_the_publishing_checkout_is_untouched(self, hc, tmp_path):
        remote = tmp_path / "origin.git"
        # The bare remote's default branch is PINNED: the seed pushes `main`,
        # and a runner whose `init.defaultBranch` is `master` leaves the
        # remote's HEAD on a branch nothing pushes, so the clone below checks
        # out nothing and `rev-parse HEAD` fails 128 (Portability, ubuntu,
        # 2026-09-23 -- green on every box whose config says `main`).
        subprocess.run(
            ["git", "-c", "init.defaultBranch=main", "init", "-q", "--bare", str(remote)],
            check=True, timeout=120,
        )
        seed = tmp_path / "seed"
        seed.mkdir()
        _git("init", "-q", cwd=seed)
        _git("config", "user.name", "t", cwd=seed)
        _git("config", "user.email", "t@t", cwd=seed)
        (seed / "README.md").write_text("seed\n", encoding="utf-8")
        (seed / ".gitignore").write_text("/reports/\n", encoding="utf-8")
        _git("add", "-A", cwd=seed)
        _git("commit", "-q", "-m", "seed", cwd=seed)
        _git("push", "-q", str(remote), "HEAD:refs/heads/main", cwd=seed)

        windows = _scratch_checkout(tmp_path, "windows", remote)
        head_before = _git("rev-parse", "HEAD", cwd=windows)
        (windows / "untracked.txt").write_text("x\n", encoding="utf-8")   # a dirty tree
        out_dir = windows / "reports" / "host-check" / "win-20260910-2300-0123456"
        out_dir.mkdir(parents=True)
        (out_dir / "SUMMARY.md").write_text("# host-check win\n", encoding="utf-8")
        (out_dir / "pytest.txt").write_text("1 passed\n", encoding="utf-8")

        commit = hc.publish("win-20260910-2300-0123456", out_dir, "host-check: win",
                            repo_root=windows)

        # the publishing checkout: same HEAD, same branch, clean index, dirty file kept
        assert _git("rev-parse", "HEAD", cwd=windows) == head_before
        assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=windows) == "main"
        assert _git("status", "--porcelain", cwd=windows) == "?? untracked.txt"
        # the pushed commit: parented on HEAD, HEAD's tree plus the report
        assert _git("rev-parse", f"{commit}^", cwd=windows) == head_before
        names = _git("ls-tree", "-r", "--name-only", commit, cwd=windows).splitlines()
        assert "README.md" in names
        assert "reports/host-check/win-20260910-2300-0123456/pytest.txt" in names
        assert "untracked.txt" not in names
        assert "win-20260910-2300-0123456" in hc.list_labels(repo_root=windows)

        mac = _scratch_checkout(tmp_path, "mac", remote)
        summary = hc.read("win-20260910-2300-0123456", repo_root=mac)
        assert summary == "# host-check win\n"
        assert (mac / "reports" / "host-check" / "win-20260910-2300-0123456"
                / "pytest.txt").read_text(encoding="utf-8") == "1 passed\n"
        assert _git("status", "--porcelain", cwd=mac) == "", "the read left the tree dirty"
