"""TP-216 — contract for ``tools/cc/session_summary.py``.

The deterministic resume-index block ``/handoff`` appends beneath its narrative.
Mechanical only (git + filesystem + computed paths) so the index can never
drift. Pins:

- ``_compaction_legs`` lists the TP-215 captures when present and a placeholder
  when absent — BOTH branches, because the self-host repo now only exercises
  the populated one.
- ``_transcript_path`` resolves via read_summary's PER-CHARACTER cwd encoding;
  the leading-dot fixture is the known-negative a run-collapsing resolver fails.
- ``cc/_working_summary.md`` is local-only AND git-ignored — ``local_only``
  governs release-archive exclusion, not git, and the harness writes the doc on
  adopter repos, so a missing gitignore line lets ``/commit``'s ``git add -A``
  commit a per-machine disposable.
"""
# pytest-marker: default-unit  (mechanical generator unit tests; not a grandfather entry)
from __future__ import annotations

import os
from pathlib import Path

from tools.cc.session_summary import (
    _compaction_legs,
    _recent_edits,
    _transcript_path,
    main,
)

from tests._git_oracle import require_is_gitignored
from tests._symlink_support import requires_symlink

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestCompactionLegs:
    def test_absent_dir_returns_placeholder(self, tmp_path):
        assert _compaction_legs(tmp_path) == ["(none — no compaction captures present)"]

    def test_empty_dir_returns_none_captured(self, tmp_path):
        (tmp_path / "cc" / "blueprints" / "compact_summaries").mkdir(parents=True)
        assert _compaction_legs(tmp_path) == ["(none captured)"]

    def test_lists_capture_files_newest_first(self, tmp_path):
        # Newest-first by mtime. Stamp explicit mtimes so the order is
        # deterministic regardless of write order or the filesystem's mtime
        # resolution (the old alphabetical assertion relied on a write-order
        # timing coincidence once the sort became mtime-based).
        d = tmp_path / "cc" / "blueprints" / "compact_summaries"
        d.mkdir(parents=True)
        older = d / "a.md"
        newer = d / "b.md"
        older.write_text("x", encoding="utf-8")
        newer.write_text("y", encoding="utf-8")
        os.utime(older, (1000, 1000))
        os.utime(newer, (2000, 2000))
        assert _compaction_legs(tmp_path) == [
            "cc/blueprints/compact_summaries/b.md",
            "cc/blueprints/compact_summaries/a.md",
        ]

    def test_caps_display_and_elides_older_legs(self, tmp_path):
        from tools.cc.session_summary import _COMPACTION_LEG_DISPLAY_CAP

        d = tmp_path / "cc" / "blueprints" / "compact_summaries"
        d.mkdir(parents=True)
        n = _COMPACTION_LEG_DISPLAY_CAP + 3
        for i in range(n):
            p = d / f"leg{i:03d}.md"
            p.write_text("x", encoding="utf-8")
            os.utime(p, (1000 + i, 1000 + i))  # leg{n-1} is newest
        legs = _compaction_legs(tmp_path)
        assert len(legs) == _COMPACTION_LEG_DISPLAY_CAP + 1  # cap + 1 elision line
        assert legs[0] == f"cc/blueprints/compact_summaries/leg{n - 1:03d}.md"
        assert legs[-1] == f"(+{n - _COMPACTION_LEG_DISPLAY_CAP} older legs elided)"

    @requires_symlink
    def test_symlinked_capture_is_skipped(self, tmp_path):
        d = tmp_path / "cc" / "blueprints" / "compact_summaries"
        d.mkdir(parents=True)
        real = tmp_path / "real.md"
        real.write_text("x", encoding="utf-8")
        (d / "link.md").symlink_to(real)
        assert _compaction_legs(tmp_path) == ["(none captured)"]


class TestRecentEdits:
    def test_dirty_tree_lists_status_and_log(self, tmp_path, monkeypatch):
        canned = {
            ("status", "--short"): " M foo.py\n?? bar.py",
            ("log", "--oneline", "-n", "5"): "abc123 do a thing",
        }
        monkeypatch.setattr(
            "tools.cc.session_summary._git",
            lambda root, *args: canned.get(args, ""),
        )
        out = _recent_edits(tmp_path)
        assert "Uncommitted:" in out
        assert any("foo.py" in ln for ln in out)
        assert "Recent commits:" in out
        assert any("abc123" in ln for ln in out)

    def test_clean_non_git_returns_placeholder(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tools.cc.session_summary._git", lambda root, *a: "")
        assert _recent_edits(tmp_path) == ["(clean tree, no recent commits)"]

    def test_status_capped_at_30_lines(self, tmp_path, monkeypatch):
        big = "\n".join(f" M file{i}.py" for i in range(50))
        monkeypatch.setattr(
            "tools.cc.session_summary._git",
            lambda root, *a: big if a == ("status", "--short") else "",
        )
        out = _recent_edits(tmp_path)
        body = [ln for ln in out if "file" in ln]
        assert len(body) == 30


class TestTranscriptPath:
    def test_missing_project_dir_is_graceful(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        assert _transcript_path(Path("/no/such/repo")) == "(no local transcript dir)"

    def test_resolves_jsonl_via_per_char_encoding(self, tmp_path, monkeypatch):
        # Leading-dot path: correct per-character encoding is the DOUBLE-dash
        # form. A re-inlined run-collapsing resolver would name the dir wrong
        # and miss the transcript — this fixture is the regression guard.
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        proj = tmp_path / ".claude" / "projects" / "-Users-x--config-proj"
        proj.mkdir(parents=True)
        (proj / "s.jsonl").write_text("{}", encoding="utf-8")
        got = _transcript_path(Path("/Users/x/.config/proj"))
        # Compare separator-agnostically: _transcript_path returns an OS-native
        # path, so the tail uses backslashes on Windows.
        assert got.replace("\\", "/").endswith("-Users-x--config-proj/s.jsonl")

    def test_no_jsonl_reports_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        proj = tmp_path / ".claude" / "projects" / "-Users-x-Repo"
        proj.mkdir(parents=True)
        assert _transcript_path(Path("/Users/x/Repo")).startswith("(no transcript under")


class TestMainAssembly:
    def test_emits_all_sections(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("tools.cc.session_summary._project_root", lambda: tmp_path)
        monkeypatch.setattr(
            "tools.cc.session_summary._transcript_path", lambda cwd: "/x/t.jsonl"
        )
        monkeypatch.setattr("tools.cc.session_summary._git", lambda root, *a: "")
        assert main() == 0
        text = capsys.readouterr().out
        assert "## Resume index" in text
        assert "Full transcript:" in text and "/x/t.jsonl" in text
        assert "Recent edits:" in text
        assert "Recent compaction legs (all sessions, newest first):" in text
        assert "Footguns / known issues" in text and "ESPALIER_MEMORY.md" in text


class TestBuildResumeIndex:
    def test_returns_index_with_all_sections(self, tmp_path, monkeypatch):
        from tools.cc.session_summary import build_resume_index

        monkeypatch.setattr(
            "tools.cc.session_summary._transcript_path", lambda cwd: "/x/t.jsonl"
        )
        monkeypatch.setattr("tools.cc.session_summary._git", lambda root, *a: "")
        out = build_resume_index(tmp_path, cwd=tmp_path)
        assert "## Resume index" in out
        assert "Full transcript:" in out and "/x/t.jsonl" in out
        assert "Recent edits:" in out
        assert "Recent compaction legs (all sessions, newest first):" in out
        assert "Footguns / known issues" in out and "ESPALIER_MEMORY.md" in out

    def test_cwd_param_drives_transcript_resolution(self, tmp_path, monkeypatch):
        # cwd (not root) selects the transcript dir — pins no cwd/root split-brain
        # (the post-compaction hook passes cwd=root explicitly).
        from tools.cc.session_summary import build_resume_index

        seen = {}

        def fake_tp(cwd):
            seen["cwd"] = cwd
            return "/x/t.jsonl"

        monkeypatch.setattr("tools.cc.session_summary._transcript_path", fake_tp)
        monkeypatch.setattr("tools.cc.session_summary._git", lambda root, *a: "")
        build_resume_index(tmp_path, cwd=tmp_path / "elsewhere")
        assert seen["cwd"] == tmp_path / "elsewhere"


class TestArtifactRouting:
    def test_working_summary_doc_is_local_only(self):
        from espalier.surface_contract import classify_release_path

        assert classify_release_path("cc/_working_summary.md") == "local_only"

    def test_working_summary_doc_is_gitignored(self):
        """The live doc AND its dated siblings must be ignored, asked of git.

        local_only != gitignored. The committed .gitignore must cover these so a
        `git add -A` never stages a per-session disposable.

        ⚠ THIS ASSERTION USED TO BE A STRING MATCH for the literal
        ``cc/_working_summary.md``, and it was green on 2026-09-01 while a
        `git add -A` staged ``cc/_working_summary.2026-08-29-handoff.md`` -- the
        exact outcome the comment above says it prevents. The rule named one
        member; the disposables are a CLASS. Asking git resolves the real rule
        including precedence and any later negation, which a set-membership test
        over stripped lines cannot see (STANDING_PRINCIPLES 14).
        """
        for rel in (
            "cc/_working_summary.md",
            "cc/_working_summary.2026-08-29-handoff.md",   # dated sibling: the miss
            "cc/GOAL_OWED.json",                            # sidecar to the ignored goal doc
        ):
            assert require_is_gitignored(REPO_ROOT, rel), (
                f"{rel} is NOT gitignored, so `git add -A` will stage it. "
                "Cover the class, not the one filename."
            )

        # Control: the assertions above must be capable of failing. A raw
        # `check-ignore` returns rc 0 for EVERY path when an ancestor is ignored,
        # which is why this routes through the oracle -- it refuses to answer
        # there rather than waving the whole set through.
        assert not require_is_gitignored(REPO_ROOT, "cc/COMMANDS.md"), (
            "cc/COMMANDS.md is tracked and must NOT be ignored -- if this passes, "
            "the ignore query is matching everything and the assertions above "
            "are vacuous."
        )
