"""The sandbox read drive's verdicts, on planted streams: no paid run, no claude.

``bench/sandbox_read_drive/drive.py`` and its ``rescore.py`` score a case from the
tool results of its saved stream. This file pins the verdict rule both share. A
run that never executed (logged out, rate-limited, the model declining, a late
file never planted) must not read as the sandbox refusing, because a seat closing
a ledger arm off the refused lines would close it on nothing. Re-scored under this rule, the 2026-10-15 macOS streams keep
every figure, and the Grep-tool and user-scope arms, which never ran, read
``not-run`` where the substring-era scorer read them as refused.
"""
# pytest-marker: default-unit  (pure functions over planted streams; nothing spawned)
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

DRIVE_DIR = Path(__file__).resolve().parent.parent / "bench" / "sandbox_read_drive"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"sandbox_read_{name}", DRIVE_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def drive():
    return _load("drive")


@pytest.fixture(scope="module")
def rescore():
    return _load("rescore")


def _stream(path: Path, *results: str) -> None:
    lines = [json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": f"t{i}", "content": text}]}}) for i, text in enumerate(results)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


class TestAVerdictNeedsEvidence:
    def test_read_refused_and_not_run_are_told_apart(self, drive):
        """Dies to: every missing marker scored as refused (the run that never
        happened read as the sandbox working), or another path's refusal line
        counted for this one."""
        seen = {drive.slug(".env.example")}
        refusal = "head: .env: Operation not permitted\nhead: sub/.env: Operation not permitted"
        assert drive.verdict_of(".env.example", seen, refusal) == "read"
        assert drive.verdict_of(".env", seen, refusal) == "refused"
        assert drive.verdict_of(".env", seen, "head: sub/.env: Operation not permitted") == "not-run"
        assert drive.verdict_of(".env", set(), "") == "not-run"
        assert drive.verdict_of("late/.env", set(), "head: late/.env: Operation not permitted", unplanted=True) \
            == "not-run"

    def test_the_rescorer_reads_a_run_that_never_executed_as_not_run(self, rescore, tmp_path):
        """Dies to: the re-scorer's own rule drifting from the driver's, or a
        late case whose files were never planted counted as refused."""
        cases = {
            "ran": (["cat: .env: Operation not permitted"], {"verdict": {".env": "x"}}),
            "never": ([], {"verdict": {".env": "x"}}),
            "late": (["head: late/.env: Operation not permitted"], {"kind": "late", "planted_at": None,
                                                                    "verdict": {"late/.env": "x"}}),
        }
        for name, (results, summary) in cases.items():
            _stream(tmp_path / f"{name}.jsonl", *results)
            (tmp_path / f"{name}.summary.json").write_text(json.dumps({"case": name, **summary}), encoding="utf-8")
        got = dict(rescore.rescore(tmp_path))
        assert got == {"late": {"late/.env": "not-run"}, "never": {".env": "not-run"},
                       "ran": {".env": "refused"}}, got


class TestTheDriverNeverRunsByAccident:
    def test_list_needs_no_claude_and_a_run_names_its_cases(self, drive, capsys):
        """Dies to: the driver running all 40 paid cases when no case is named."""
        assert drive.main(["--list"]) == 0
        assert "posture" in capsys.readouterr().out
        with pytest.raises(SystemExit) as stopped:
            drive.main(["--tree", "."])
        assert stopped.value.code == 2
