"""TP-218 — ``/read-summary`` falls back to the durable captured artifact.

TP-215's ``post_compact.py`` persists the verbatim native compaction summary to
``cc/blueprints/compact_summaries/<session>.md`` so it outlives the GC'd
``.jsonl``. This pins the read-side wiring: the live transcript stays the
**primary** source; the durable artifact is the **fallback** only when the
TARGETED transcript is absent (gone/GC'd) — never when a live-but-uncompacted
transcript exists (no cross-session bleed), and never for ``--path`` (an explicit
pointer is honored verbatim). ``--list`` unions artifact-only sessions; the source
indicator prints to stderr so piped stdout stays the pure summary body.

TP-219: the BARE no-flag default now dumps the live ``cc/_working_summary.md``
(see the two ``test_bare_default_*`` cases); the transcript/artifact wiring this
file pins governs ``--session``/``--all``/``--index``/``--path``.
"""
# pytest-marker: default-unit  (in-process reader unit tests; not a grandfather entry)
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.cc.read_summary import (
    _artifact_dir,
    _artifact_summaries,
    main,
)


def _entry(text: str) -> str:
    return json.dumps(
        {"type": "user", "isCompactSummary": True,
         "message": {"role": "user", "content": text}}
    )


def _noise(text: str = "hello") -> str:
    return json.dumps({"type": "assistant", "message": {"content": text}})


def _write_transcript(path: Path, summaries: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [_noise("intro")]
    for s in summaries:
        lines.append(_entry(s))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _capture_header(stem: str) -> str:
    """Byte-for-byte the header post_compact.py::_capture_compact_summary writes."""
    return f"\n\n===== compaction captured (transcript {stem}) =====\n\n"


def _write_artifact(art_dir: Path, stem: str, bodies: list[str]) -> Path:
    """Replicate post_compact's append format: header + body + '\\n' per leg."""
    art_dir.mkdir(parents=True, exist_ok=True)
    dest = art_dir / f"{stem}.md"
    with dest.open("a", encoding="utf-8") as f:
        for body in bodies:
            f.write(_capture_header(stem) + body + "\n")
    return dest


def _setup(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    """Pin Path.home + Path.cwd at a sandbox repo. Returns (proj_dir, artifact_dir).

    proj_dir is the ~/.claude/projects/<enc> transcript dir; artifact_dir is the
    in-repo cc/blueprints/compact_summaries dir (_artifact_dir() == cwd-based).
    """
    from tools.cc.read_summary import _project_dir

    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: cwd))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    proj = _project_dir(cwd)
    proj.mkdir(parents=True, exist_ok=True)
    return proj, _artifact_dir()


def _write_live_doc(cwd_root: Path, body: str) -> Path:
    """Write the live working-summary doc under the monkeypatched cwd (TP-219).

    main()'s bare default reads ``Path.cwd()/"cc"/"_working_summary.md"``; the
    doc MUST land at exactly that path or the present-branch is never exercised.
    """
    live = cwd_root / "cc" / "_working_summary.md"
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_text(body, encoding="utf-8")
    return live


# ─── durable fallback ─────────────────────────────────────────────────────────


class TestDurableFallback:
    def test_bare_default_dumps_live_doc(self, tmp_path, monkeypatch, capsys):
        """TP-219: bare main([]) dumps the live working-summary doc when present.

        (The "no-transcript → durable artifact" guarantee is held by
        test_session_flag_reads_artifact, which drives via --session.)
        """
        _proj, _art = _setup(monkeypatch, tmp_path)
        _write_live_doc(tmp_path / "repo", "LIVE WORKING SUMMARY BODY")
        rc = main([])
        cap = capsys.readouterr()
        assert rc == 0
        assert "LIVE WORKING SUMMARY BODY" in cap.out

    def test_bare_default_reads_a_byte_order_marked_live_doc_and_names_one_it_cannot(
        self, tmp_path, monkeypatch, capsys
    ):
        """DEF-797: the live doc is the third hand-rewritten continuity doc. A
        byte-order-marked one dumps clean; one the reader cannot decode is named
        on stderr with the encoding to re-save in, exit 1, instead of a
        traceback out of /read-summary."""
        import codecs

        _setup(monkeypatch, tmp_path)
        live = _write_live_doc(tmp_path / "repo", "placeholder")
        live.write_bytes(codecs.BOM_UTF16_LE + "LIVE WORKING SUMMARY BODY".encode("utf-16-le"))
        rc = main([])
        cap = capsys.readouterr()
        assert rc == 0 and "LIVE WORKING SUMMARY BODY" in cap.out and "\ufeff" not in cap.out
        live.write_bytes("LIVE WORKING SUMMARY BODY".encode("utf-16-le"))
        rc = main([])
        cap = capsys.readouterr()
        assert rc == 1 and cap.out == ""
        assert "read_summary: cc/_working_summary.md is not UTF-8 text (NUL bytes" in cap.err

    def test_bare_default_absent_doc_stderr_hint(self, tmp_path, monkeypatch, capsys):
        """TP-219: bare main([]) with no live doc → stderr hint, exit 0, empty stdout."""
        _setup(monkeypatch, tmp_path)
        rc = main([])
        cap = capsys.readouterr()
        assert rc == 0
        assert "no cc/_working_summary.md yet" in cap.err
        assert cap.out.strip() == ""

    def test_bare_default_empty_doc_falls_through_to_hint(self, tmp_path, monkeypatch, capsys):
        """R2: a 0-byte / whitespace-only live doc (e.g. a torn write) must NOT
        print as the current state — it falls through to the same stderr hint as
        a missing doc, not a blank line on stdout. (Read-side complement to the
        R1 atomic-write fix in post_compact.)"""
        _setup(monkeypatch, tmp_path)
        _write_live_doc(tmp_path / "repo", "   \n\n")
        rc = main([])
        cap = capsys.readouterr()
        assert rc == 0
        assert "no cc/_working_summary.md yet" in cap.err
        assert cap.out.strip() == ""

    def test_transcript_primary_wins(self, tmp_path, monkeypatch, capsys):
        """Transcript present WITH a summary AND an artifact present → transcript."""
        proj, art_dir = _setup(monkeypatch, tmp_path)
        _write_transcript(proj / "live.jsonl", ["LIVE transcript summary"])
        _write_artifact(art_dir, "live", ["STALE artifact body"])
        rc = main(["--session", "live"])  # TP-219: bare default now dumps the live doc
        cap = capsys.readouterr()
        assert rc == 0
        assert "LIVE transcript summary" in cap.out
        assert "STALE artifact body" not in cap.out
        assert "durable artifact" not in cap.err

    def test_session_flag_reads_artifact(self, tmp_path, monkeypatch, capsys):
        """--session X with no transcript X but X.md present → reads the artifact."""
        _proj, art_dir = _setup(monkeypatch, tmp_path)
        _write_artifact(art_dir, "abc123", ["session-targeted body"])
        rc = main(["--session", "abc123"])
        cap = capsys.readouterr()
        assert rc == 0
        assert "session-targeted body" in cap.out
        assert "from durable artifact abc123" in cap.err

    def test_present_but_uncompacted_transcript_no_bleed(self, tmp_path, monkeypatch, capsys):
        """Live transcript present, ZERO compactions, a DIFFERENT session's artifact
        on disk → reports no-summary for THIS session; never prints the other body."""
        proj, art_dir = _setup(monkeypatch, tmp_path)
        _write_transcript(proj / "fresh.jsonl", [])  # live, not yet compacted
        _write_artifact(art_dir, "old_other", ["a PRIOR session's body"])
        rc = main(["--session", "fresh"])  # TP-219: bare default now dumps the live doc
        cap = capsys.readouterr()
        assert rc == 0
        assert "no compaction summary yet" in cap.out
        assert "a PRIOR session's body" not in cap.out
        assert "durable artifact" not in cap.err

    def test_path_with_no_summary_does_not_fall_back(self, tmp_path, monkeypatch, capsys):
        """--path to a real transcript with no compaction → existing exit-0 path,
        never the artifact (explicit pointer honored verbatim)."""
        _proj, art_dir = _setup(monkeypatch, tmp_path)
        _write_artifact(art_dir, "whatever", ["should NOT appear"])
        empty = tmp_path / "explicit.jsonl"
        empty.write_text(_noise("a") + "\n", encoding="utf-8")
        rc = main(["--path", str(empty)])
        cap = capsys.readouterr()
        assert rc == 0
        assert "no compaction summary yet" in cap.out
        assert "should NOT appear" not in cap.out

    def test_all_over_multiblock_artifact(self, tmp_path, monkeypatch, capsys):
        """--all prints every captured leg in append order."""
        _proj, art_dir = _setup(monkeypatch, tmp_path)
        _write_artifact(art_dir, "multi", ["FIRST leg", "SECOND leg"])
        rc = main(["--all"])
        out = capsys.readouterr().out
        assert rc == 0
        assert out.index("FIRST leg") < out.index("SECOND leg")

    def test_index_selects_artifact_block(self, tmp_path, monkeypatch, capsys):
        """--index addresses captured legs by append order."""
        _proj, art_dir = _setup(monkeypatch, tmp_path)
        _write_artifact(art_dir, "multi", ["FIRST leg", "SECOND leg"])
        rc = main(["--index", "0"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "FIRST leg" in out
        assert "SECOND leg" not in out

    def test_all_not_intercepted_when_live_doc_present(self, tmp_path, monkeypatch, capsys):
        """TP-219 guard regression: --all browses transcript/artifact legs even
        when a live doc exists. The bare-only guard would have dumped the live
        doc instead (the --all/--index path must NOT be intercepted)."""
        _proj, art_dir = _setup(monkeypatch, tmp_path)
        _write_live_doc(tmp_path / "repo", "LIVE DOC SHOULD NOT APPEAR")
        _write_artifact(art_dir, "multi", ["FIRST leg", "SECOND leg"])
        rc = main(["--all"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "LIVE DOC SHOULD NOT APPEAR" not in out
        assert out.index("FIRST leg") < out.index("SECOND leg")


# ─── artifact parsing ─────────────────────────────────────────────────────────


class TestArtifactParsing:
    def test_header_roundtrip(self, tmp_path):
        """A file built with post_compact's exact header splits back into bodies."""
        dest = _write_artifact(tmp_path, "round", ["body one", "body two"])
        blocks = _artifact_summaries(dest)
        assert blocks == ["body one", "body two"]

    def test_single_block(self, tmp_path):
        dest = _write_artifact(tmp_path, "single", ["just one"])
        assert _artifact_summaries(dest) == ["just one"]

    def test_symlinked_artifact_refused(self, tmp_path):
        real = _write_artifact(tmp_path, "real", ["x"])
        link = tmp_path / "link.md"
        try:
            link.symlink_to(real)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unsupported on this platform")
        assert _artifact_summaries(link) == []

    def test_oversize_artifact_refused(self, tmp_path, monkeypatch):
        import tools.cc.read_summary as rs
        dest = _write_artifact(tmp_path, "big", ["over the cap"])
        monkeypatch.setattr(rs, "_MAX_BYTES", 4)
        assert _artifact_summaries(dest) == []

    def test_missing_and_empty_no_crash(self, tmp_path):
        assert _artifact_summaries(tmp_path / "ghost.md") == []
        empty = tmp_path / "empty.md"
        empty.write_text("", encoding="utf-8")
        assert _artifact_summaries(empty) == []


# ─── --list union ─────────────────────────────────────────────────────────────


class TestListUnion:
    def test_list_shows_durable_only_session(self, tmp_path, monkeypatch, capsys):
        _proj, art_dir = _setup(monkeypatch, tmp_path)
        _write_artifact(art_dir, "gcd_one", ["b"])
        rc = main(["--list"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "gcd_one  compactions=1  [durable]" in out

    def test_list_tags_transcript_and_durable(self, tmp_path, monkeypatch, capsys):
        proj, art_dir = _setup(monkeypatch, tmp_path)
        _write_transcript(proj / "alive.jsonl", ["a", "b"])
        _write_artifact(art_dir, "buried", ["c"])
        rc = main(["--list"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "alive  compactions=2  [transcript]" in out
        assert "buried  compactions=1  [durable]" in out

    def test_list_dedupes_stem_present_in_both(self, tmp_path, monkeypatch, capsys):
        proj, art_dir = _setup(monkeypatch, tmp_path)
        _write_transcript(proj / "both.jsonl", ["a"])
        _write_artifact(art_dir, "both", ["a"])
        rc = main(["--list"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "both  compactions=1  [transcript]" in out
        assert "[durable]" not in out  # the artifact row for 'both' is deduped


# ─── source-indicator channel ─────────────────────────────────────────────────


class TestSourceIndicator:
    def test_indicator_to_stderr_not_stdout(self, tmp_path, monkeypatch, capsys):
        """The provenance indicator goes to stderr so a piped stdout stays the
        pure summary body (pins the channel against a future refactor)."""
        _proj, art_dir = _setup(monkeypatch, tmp_path)
        _write_artifact(art_dir, "s", ["pure body content"])
        rc = main(["--session", "s"])  # TP-219: bare default now dumps the live doc
        cap = capsys.readouterr()
        assert rc == 0
        assert "from durable artifact" in cap.err
        assert "from durable artifact" not in cap.out
        assert cap.out.strip() == "pure body content"
