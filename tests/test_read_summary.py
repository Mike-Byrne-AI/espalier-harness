"""TP-214 — contract for ``tools/cc/read_summary.py``.

Pins the verbatim post-compaction-summary reader that ``/read-summary``
invokes:

- Extract every ``isCompactSummary`` transcript entry verbatim, in file
  order; ``--all`` / ``--index`` / negative index resolve correctly.
- ``--list`` reports per-session compaction counts; a session with no
  compaction prints the "no compaction summary yet" line and exits 0.
- Fail soft on oversize / symlinked / malformed-line transcripts — the
  reader is a pull-side visibility utility, never a correctness gate, so a
  traceback (or a wrong resolved dir) silently denies the operator the one
  best "pick up where we left off" artifact.
- ``_project_dir`` reproduces Claude Code's PER-CHARACTER cwd encoding: a
  run of adjacent separators (a leading-dot dir) must yield one dash each,
  or the reader resolves the wrong ``~/.claude/projects`` dir and finds no
  transcript. The run-bearing fixture below is the known-negative that a
  run-collapsing regex cannot satisfy.
"""
# pytest-marker: default-unit  (reader unit tests; not a grandfather entry)
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tools.cc.read_summary import (
    _project_dir,
    _resolve,
    _sessions,
    _summaries,
    main,
)


def _entry(text: str) -> str:
    """A realistic ``isCompactSummary`` transcript line (CC shape)."""
    return json.dumps(
        {
            "type": "user",
            "isCompactSummary": True,
            "message": {"role": "user", "content": text},
        }
    )


def _noise(text: str = "hello") -> str:
    """A normal (non-summary) transcript line."""
    return json.dumps({"type": "assistant", "message": {"content": text}})


def _write_transcript(path: Path, summaries: list[str]) -> None:
    lines = [_noise("intro")]
    for s in summaries:
        lines.append(_entry(s))
        lines.append(_noise("after"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestProjectDirEncoding:
    """CC encodes cwd -> projects dir per-character, not per-run."""

    def test_simple_path_encodes(self, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/u")))
        got = _project_dir(Path("/Users/x/Repo"))
        assert got == Path("/home/u/.claude/projects/-Users-x-Repo")

    def test_single_dot_is_not_a_run(self, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/u")))
        # A lone '.' is one non-alnum char -> one dash under both algorithms;
        # this case alone cannot distinguish per-char from per-run.
        got = _project_dir(Path("/Users/x/My.Repo"))
        assert got.name == "-Users-x-My-Repo"

    def test_leading_dot_dir_yields_double_dash(self, monkeypatch):
        """RUN-BEARING fixture: '/.' is two adjacent non-alnum chars.

        Per-char -> '--' (correct, matches CC); a run-collapsing
        ``[^A-Za-z0-9]+`` regex -> '-' (wrong, resolves no transcript).
        """
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/u")))
        got = _project_dir(Path("/Users/x/.config/proj"))
        assert got.name == "-Users-x--config-proj"

    def test_adjacent_separators_each_become_a_dash(self, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/u")))
        got = _project_dir(Path("/Users/x/a..b"))
        assert got.name == "-Users-x-a--b"


class TestSummaryExtraction:
    def test_extracts_single_summary_verbatim(self, tmp_path):
        jsonl = tmp_path / "s.jsonl"
        _write_transcript(jsonl, ["# Section\n- bullet\nread the full transcript at: /x"])
        assert _summaries(jsonl) == ["# Section\n- bullet\nread the full transcript at: /x"]

    def test_extracts_every_summary_in_file_order(self, tmp_path):
        jsonl = tmp_path / "s.jsonl"
        _write_transcript(jsonl, ["first", "second", "third"])
        assert _summaries(jsonl) == ["first", "second", "third"]

    def test_list_form_content_is_joined(self, tmp_path):
        jsonl = tmp_path / "s.jsonl"
        line = json.dumps(
            {
                "type": "user",
                "isCompactSummary": True,
                "message": {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]},
            }
        )
        jsonl.write_text(line + "\n", encoding="utf-8")
        assert _summaries(jsonl) == ["ab"]

    def test_no_compaction_returns_empty(self, tmp_path):
        jsonl = tmp_path / "s.jsonl"
        jsonl.write_text(_noise("a") + "\n" + _noise("b") + "\n", encoding="utf-8")
        assert _summaries(jsonl) == []


class TestFailSoft:
    def test_malformed_line_is_skipped_not_raised(self, tmp_path):
        jsonl = tmp_path / "s.jsonl"
        # A line that contains the pre-filter substring but is invalid JSON,
        # followed by a real summary — the bad line is skipped, the good one wins.
        jsonl.write_text(
            '{"isCompactSummary": true, BROKEN\n' + _entry("real") + "\n",
            encoding="utf-8",
        )
        assert _summaries(jsonl) == ["real"]

    def test_oversize_transcript_fails_soft(self, tmp_path, monkeypatch):
        jsonl = tmp_path / "s.jsonl"
        _write_transcript(jsonl, ["x"])
        monkeypatch.setattr("tools.cc.read_summary._MAX_BYTES", 1)
        assert _summaries(jsonl) == []

    def test_symlinked_transcript_is_skipped(self, tmp_path):
        real = tmp_path / "real.jsonl"
        _write_transcript(real, ["x"])
        link = tmp_path / "link.jsonl"
        try:
            link.symlink_to(real)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable on this platform")
        assert _summaries(link) == []

    def test_missing_file_returns_empty(self, tmp_path):
        assert _summaries(tmp_path / "nope.jsonl") == []

    def test_sessions_tolerates_missing_dir(self, tmp_path):
        assert _sessions(tmp_path / "nope") == []


class TestSessionsOrdering:
    def test_sessions_newest_first(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        old = proj / "old.jsonl"
        new = proj / "new.jsonl"
        old.write_text("{}\n", encoding="utf-8")
        new.write_text("{}\n", encoding="utf-8")
        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))
        assert [p.stem for p in _sessions(proj)] == ["new", "old"]


class TestResolve:
    def test_path_wins_over_session(self, tmp_path):
        jsonl = tmp_path / "explicit.jsonl"
        jsonl.write_text("{}\n", encoding="utf-8")
        ns = _make_ns(path=str(jsonl), session="ignored")
        assert _resolve(ns) == jsonl

    def test_session_no_match_returns_none(self, tmp_path, monkeypatch):
        proj = _fake_project(monkeypatch, tmp_path, ["abc"])
        _write_transcript(proj / "abc.jsonl", ["x"])
        ns = _make_ns(session="does-not-exist")
        assert _resolve(ns) is None

    def test_default_returns_newest_session(self, tmp_path, monkeypatch):
        proj = _fake_project(monkeypatch, tmp_path, [])
        a = proj / "a.jsonl"
        b = proj / "b.jsonl"
        a.write_text("{}\n", encoding="utf-8")
        b.write_text("{}\n", encoding="utf-8")
        os.utime(a, (1000, 1000))
        os.utime(b, (2000, 2000))
        ns = _make_ns()
        assert _resolve(ns) == b


class TestMainOutput:
    def test_default_prints_latest_summary(self, tmp_path, capsys):
        jsonl = tmp_path / "s.jsonl"
        _write_transcript(jsonl, ["first", "LAST"])
        rc = main(["--path", str(jsonl)])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "LAST"

    def test_all_prints_every_compaction(self, tmp_path, capsys):
        jsonl = tmp_path / "s.jsonl"
        _write_transcript(jsonl, ["one", "two"])
        rc = main(["--path", str(jsonl), "--all"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "one" in out and "two" in out
        assert out.index("one") < out.index("two")

    def test_index_selects_specific_compaction(self, tmp_path, capsys):
        jsonl = tmp_path / "s.jsonl"
        _write_transcript(jsonl, ["zero", "one", "two"])
        rc = main(["--path", str(jsonl), "--index", "0"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "zero"

    def test_negative_index_resolves(self, tmp_path, capsys):
        jsonl = tmp_path / "s.jsonl"
        _write_transcript(jsonl, ["zero", "one", "two"])
        rc = main(["--path", str(jsonl), "--index", "-1"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "two"

    def test_out_of_range_index_errors(self, tmp_path, capsys):
        jsonl = tmp_path / "s.jsonl"
        _write_transcript(jsonl, ["only"])
        rc = main(["--path", str(jsonl), "--index", "5"])
        assert rc == 1
        assert "out of range" in capsys.readouterr().err

    def test_no_compaction_yet_exits_zero(self, tmp_path, capsys):
        jsonl = tmp_path / "s.jsonl"
        jsonl.write_text(_noise("a") + "\n", encoding="utf-8")
        rc = main(["--path", str(jsonl)])
        assert rc == 0
        assert "no compaction summary yet" in capsys.readouterr().out

    def test_missing_path_exits_one(self, tmp_path, capsys):
        rc = main(["--path", str(tmp_path / "absent.jsonl")])
        assert rc == 1
        assert "no matching transcript" in capsys.readouterr().err


class TestListMode:
    def test_list_reports_compaction_counts(self, tmp_path, monkeypatch, capsys):
        proj = _fake_project(monkeypatch, tmp_path, [])
        _write_transcript(proj / "sess1.jsonl", ["a", "b"])
        _write_transcript(proj / "sess2.jsonl", [])
        rc = main(["--list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "sess1  compactions=2" in out
        assert "sess2  compactions=0" in out

    def test_list_no_transcripts(self, tmp_path, monkeypatch, capsys):
        _fake_project(monkeypatch, tmp_path, [])
        rc = main(["--list"])
        assert rc == 0
        assert "no transcripts for this repo" in capsys.readouterr().out


# --- helpers -----------------------------------------------------------------

def _make_ns(path=None, session=None):
    import argparse

    return argparse.Namespace(path=path, session=session, list=False, all=False, index=None)


def _fake_project(monkeypatch, tmp_path: Path, sessions: list[str]) -> Path:
    """Point ``_project_dir(cwd())`` at a writable tmp project dir."""
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    cwd.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: cwd))
    proj = _project_dir(cwd)
    proj.mkdir(parents=True)
    for s in sessions:
        _write_transcript(proj / f"{s}.jsonl", ["x"])
    return proj
