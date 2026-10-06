"""Contract tests for ``scripts/handoff_mechanics.py``.

The handoff's mechanical steps have ordering constraints that a hurried
session drifts past (commit before the summary measures the ahead count,
snapshot after the goal rewrite, landing check last); this script encodes
them, and these tests pin that encoding. The pure helpers are tested
directly; the two phases are driven with ``--dry-run`` against this checkout
(nothing written) and against the preconditions each hand step owes, which
the script must refuse rather than paper over. The values it must not restate
-- the memory cap, the trailer, the archive header -- are checked against
their owners, because a restated constant is the drift the script exists to
remove.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "handoff_mechanics.py"


def _load():
    spec = importlib.util.spec_from_file_location("handoff_mechanics", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hm():
    return _load()


class TestTheOwnedValuesAreRead:
    def test_the_memory_cap_is_the_hooks(self, hm):
        sys.path.insert(0, str(REPO_ROOT / "tools" / "cc" / "hooks"))
        try:
            import post_write_check
        finally:
            sys.path.pop(0)
        assert hm.memory_cap(REPO_ROOT) == post_write_check._MEMORY_MD_CAP

    def test_rows_to_prune_is_one_per_line_over(self, hm):
        assert hm.rows_to_prune(120, 120) == 0
        assert hm.rows_to_prune(121, 120) == 1
        assert hm.rows_to_prune(119, 120) == 0

    def test_the_archive_header_is_the_one_read_summary_splits_on(self, hm):
        sys.path.insert(0, str(REPO_ROOT / "tools" / "cc"))
        try:
            import read_summary
        finally:
            sys.path.pop(0)
        header = "\n\n===== compaction captured (transcript abc123) =====\n\n"
        assert read_summary._ARTIFACT_HEADER.search(header)


class TestTheHelpers:
    def test_newest_transcript_stem_skips_durable_rows(self, hm):
        out = ("  aaaa  compactions=0  [durable]\n"
               "  bbbb  compactions=2  [transcript]\n"
               "  cccc  compactions=0  [transcript]\n")
        assert hm.newest_transcript_stem(out) == "bbbb"
        assert hm.newest_transcript_stem("read_summary: no transcripts for this repo") is None

    def test_commit_message_carries_the_canonical_trailer_once(self, hm):
        canon = "Co-Authored-By: Claude, Scion <claude@espalier.dev>"
        msg = hm.compose_commit_message("docs(memory): x", [canon, "Claude-Session: https://u"], canon)
        assert msg.count(canon) == 1
        assert msg.splitlines() == ["docs(memory): x", "", canon, "Claude-Session: https://u"]

    @pytest.mark.parametrize("text,expect", [
        ("", "empty"),
        ("# Something else\n## 9. Optional Next Step\n", "does not start with"),
        ("# Working summary\n## 1. Primary\n", "lacks section 9"),
        ("# Working summary\n## 9. Optional Next Step\n\n## Resume index\n", "already carries a resume index"),
        ("# Working summary — s\n## 1.\n## 9. Optional Next Step\nx\n", "ok"),
    ])
    def test_summary_body_state_names_the_missing_hand_step(self, hm, text, expect):
        state = hm.summary_body_state(text)
        assert state == "ok" if expect == "ok" else expect in state


class TestPhasesRefuseWhatTheHandStepOwes:
    def test_after_memory_row_refuses_an_unmodified_memory_file(self, hm, tmp_path, capsys):
        # a scratch git repo with a clean ESPALIER_MEMORY.md
        import subprocess
        r = tmp_path / "r"; r.mkdir()
        (r / "ESPALIER_MEMORY.md").write_text("# m\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(r), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(r), "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "i"], check=True)
        rc = hm.main(["--root", str(r), "after-memory-row", "--message", "x", "--dry-run"])
        assert rc == 2 and "unmodified" in capsys.readouterr().err

    def test_after_goal_refuses_without_a_summary_body(self, hm, tmp_path, capsys):
        r = tmp_path / "r"; (r / "cc").mkdir(parents=True)
        rc = hm.main(["--root", str(r), "after-goal", "--dry-run"])
        assert rc == 2 and "write the 9-section body first" in capsys.readouterr().err

    def test_after_goal_refuses_a_stale_goal_date(self, hm, tmp_path, capsys):
        r = tmp_path / "r"; (r / "cc").mkdir(parents=True)
        (r / "cc" / "_working_summary.md").write_text("# Working summary\n## 9. Optional Next Step\nx\n", encoding="utf-8")
        (r / "cc" / "GOAL.md").write_text("# Goal\n\n_Updated: 2001-01-01 (handoff)._\n\n## x\n", encoding="utf-8")
        rc = hm.main(["--root", str(r), "after-goal", "--dry-run"])
        err = capsys.readouterr().err
        assert rc == 2 and "_Updated line does not carry today" in err and "crossed midnight" in err


class TestDryRunOnThisTree:
    def test_after_memory_row_dry_run_plans_without_writing(self, hm, tmp_path, capsys, monkeypatch):
        """Against this checkout: the plan names the prune decision, the
        finalize, the explicit-path add and the composed message, and writes
        nothing (the memory file is made 'modified' in a scratch copy only)."""
        import shutil
        import subprocess
        r = tmp_path / "copy"

        def _skip(directory, names):
            # only the TOP-LEVEL cc/ and reports/ are session state; `tools/cc/`
            # must come along (the script reads the memory cap from its hook)
            skip = {".git", "__pycache__", ".pytest_cache", "build", "dist", "node_modules"}
            if Path(directory) == REPO_ROOT:
                skip |= {"cc", "reports"}
            return [n for n in names if n in skip]

        shutil.copytree(REPO_ROOT, r, symlinks=True, ignore=_skip)
        subprocess.run(["git", "-C", str(r), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(r), "add", "-A"], check=True, capture_output=True)
        # this repo's .gitignore carries `espalier_*.md`, which a case-insensitive
        # filesystem matches against ESPALIER_MEMORY.md in a FRESH clone (the real
        # tree tracks the file from before that rule, so git keeps tracking it);
        # force-add it or the script correctly reports "unmodified" (driven).
        subprocess.run(["git", "-C", str(r), "add", "-f", "ESPALIER_MEMORY.md"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(r), "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "i"], check=True, capture_output=True)
        # An origin/<branch> ref, so the ahead-count line prints and the GOAL
        # suffix assertion below can fail (without it the line never printed
        # and that assertion was decoration -- review round three, driven).
        branch = subprocess.run(["git", "-C", str(r), "rev-parse", "--abbrev-ref", "HEAD"],
                                check=True, capture_output=True, text=True,
                                encoding="utf-8").stdout.strip()
        subprocess.run(["git", "-C", str(r), "update-ref", f"refs/remotes/origin/{branch}", "HEAD"],
                       check=True, capture_output=True)
        mem = r / "ESPALIER_MEMORY.md"
        # Pad the scratch copy to the cap BEFORE the new row, so the planned
        # prune of exactly one row is a property of the mechanics, not of the
        # live file happening to sit at the cap (measured 2026-09-10: the live
        # file was one line under it and this test read "no prune").
        cap = hm.memory_cap(r)
        lines = mem.read_text(encoding="utf-8").splitlines()
        assert len(lines) <= cap, "the live memory file is over its cap; the hook should have pruned it"
        lines += ["| 2099-01-01 | pad | note |"] * (cap - len(lines))
        mem.write_text("\n".join(lines) + "\n| 2099-01-01 | row | note |\n", encoding="utf-8")
        before = mem.read_text(encoding="utf-8")
        rc = hm.main(["--root", str(r), "after-memory-row", "--dry-run", "--message", "docs(memory): t",
                      "--trailer", "Claude-Session: https://example"])
        out = capsys.readouterr().out
        assert rc == 0
        assert re.search(r"would run: .*espalier memory prune --rows 1", out), out
        assert "cognitive_blueprint.py finalize" in out and "git add -- ESPALIER_MEMORY.md" in out
        assert "would run: git commit -q -F - -- ESPALIER_MEMORY.md" in out, out
        assert "Co-Authored-By: Claude, Scion <claude@espalier.dev>" in out
        assert "Claude-Session: https://example" in out
        assert mem.read_text(encoding="utf-8") == before
        # The copy carries no cc/GOAL.md (top-level cc/ is skipped): on this
        # source tree the file's presence is check_handoff_landing's
        # operator-tree tell, so the next step must say skip, never "write it"
        # -- an unconditional "write cc/GOAL.md" led a second clone to create
        # one and turned two landing notes red (driven, 2026-09-30 review).
        assert "next: skip step 7" in out and "do NOT create" in out, out
        assert f"ahead of origin/{branch}:" in out, "the line the next assert reads never printed"
        assert "write this into cc/GOAL.md" not in out, out
        (r / "cc").mkdir(exist_ok=True)
        (r / "cc" / "GOAL.md").write_text("# Goal / progress\n", encoding="utf-8")
        capsys.readouterr()
        assert hm.main(["--root", str(r), "after-memory-row", "--dry-run", "--message", "docs(memory): t"]) == 0
        assert "next: write cc/GOAL.md" in capsys.readouterr().out
        (r / "cc" / "GOAL.md").unlink()
        # a promotion into a skill body stages both twins AND runs that row's
        # sync (the claude mirrors), not the docs sync
        capsys.readouterr()
        rc = hm.main(["--root", str(r), "after-memory-row", "--dry-run", "--message", "docs(memory): t",
                      "--also", ".claude/skills/reflect/SKILL.md"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "sync_claude_mirrors.py" in out and "sync_asset_docs.py" not in out
        assert "espalier/assets/claude/skills/reflect/SKILL.md" in out


_CANON = "Co-Authored-By: Claude, Scion <claude@espalier.dev>"


def _scratch_git(repo: Path):
    import subprocess

    def git(*argv: str) -> "subprocess.CompletedProcess[str]":
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
             "-c", "core.hooksPath=", "-c", "commit.gpgsign=false", *argv],
            cwd=repo, capture_output=True, text=True, encoding="utf-8", check=False,
        )
    return git


class TestTheMemoryCommitTakesOnlyItsOwnPaths:
    """The phase stages by path and now commits by path. Its commit was a bare
    `git commit -q -F -`, which takes the whole index: a change somebody staged
    before the handoff (held back from `/commit`, or a parallel session's) rode
    into the `docs(memory):` commit and left with the handoff's push, reviewed
    by nobody (reproduced 2026-10-01). Driven through real git on a scratch
    repo; only the phase's two harness children (the blueprint finalize, the
    owed-list probes) and the two owners it loads (the memory cap, the
    trailer) are stood in for."""

    @staticmethod
    def _arm(hm, monkeypatch) -> list[list[str]]:
        import subprocess
        import types

        real_run = subprocess.run
        harness_children: list[list[str]] = []

        def run(argv, **kw):
            argv = [str(a) for a in argv]
            if argv[0] == "git":
                return real_run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                                 "-c", "core.hooksPath=", "-c", "commit.gpgsign=false", *argv[1:]], **kw)
            harness_children.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        monkeypatch.setattr(hm, "subprocess", types.SimpleNamespace(
            run=run, CompletedProcess=subprocess.CompletedProcess,
            TimeoutExpired=subprocess.TimeoutExpired,
        ))
        monkeypatch.setattr(hm, "_load", lambda _p, _n: types.SimpleNamespace(
            canonical_trailer=lambda: _CANON, _MEMORY_MD_CAP=120,
        ))
        return harness_children

    @staticmethod
    def _repo(tmp_path: Path):
        repo = tmp_path / "r"
        repo.mkdir()
        git = _scratch_git(repo)
        assert git("init", "-q", "-b", "main").returncode == 0
        (repo / "app.py").write_text("a = 1\n", encoding="utf-8")
        (repo / "ESPALIER_MEMORY.md").write_text("# memory\n", encoding="utf-8")
        assert git("add", "--", "app.py", "ESPALIER_MEMORY.md").returncode == 0
        assert git("commit", "-q", "-m", "init").returncode == 0
        return repo, git

    def test_a_change_staged_before_the_handoff_stays_staged_and_out_of_the_commit(
            self, hm, tmp_path, monkeypatch, capsys):
        repo, git = self._repo(tmp_path)
        (repo / "app.py").write_text("a = 2\n", encoding="utf-8")
        assert git("add", "--", "app.py").returncode == 0                      # somebody's, staged
        (repo / "ESPALIER_MEMORY.md").write_text("# memory\n| 2026-10-06 | row |\n", encoding="utf-8")
        (repo / "memory").mkdir()
        (repo / "memory" / "new note.md").write_text("# a promoted note\n", encoding="utf-8")
        self._arm(hm, monkeypatch)
        rc = hm.main(["--root", str(repo), "after-memory-row", "--message", "docs(memory): t",
                      "--also", "memory/new note.md"])
        assert rc == 0, capsys.readouterr()
        committed = git("show", "--name-only", "--format=", "HEAD").stdout.strip().splitlines()
        assert sorted(committed) == ["ESPALIER_MEMORY.md", "memory/new note.md"], committed
        assert git("diff", "--cached", "--name-only").stdout.split() == ["app.py"], (
            "the change staged before the handoff was committed, or was unstaged"
        )
        assert _CANON in git("log", "-1", "--format=%B").stdout

    @pytest.mark.parametrize("operation", ["merge", "cherry-pick", "rebase"])
    def test_an_operation_in_progress_stops_the_phase_before_it_stages_anything(
            self, hm, tmp_path, monkeypatch, capsys, operation):
        """Git refuses a path-limited commit during a merge or a cherry-pick,
        and takes one into the history a rebase is rewriting. Staging first
        and then refusing left the row inside the merge, where the way out the
        harness names elsewhere (`git merge --abort`) deleted it from disk
        (driven by the failure-mode review). The phase now refuses before it
        prunes, finalizes or stages; it never retries without the paths."""
        repo, git = self._repo(tmp_path)
        (repo / "f.txt").write_text("base\n", encoding="utf-8")
        assert git("add", "--", "f.txt").returncode == 0
        assert git("commit", "-q", "-m", "base").returncode == 0
        assert git("checkout", "-q", "-b", "topic").returncode == 0
        (repo / "f.txt").write_text("topic\n", encoding="utf-8")
        assert git("commit", "-q", "-m", "topic", "--", "f.txt").returncode == 0
        assert git("checkout", "-q", "main").returncode == 0
        (repo / "f.txt").write_text("main\n", encoding="utf-8")
        assert git("commit", "-q", "-m", "main", "--", "f.txt").returncode == 0
        if operation == "rebase":
            assert git("checkout", "-q", "topic").returncode == 0
            stopped = git("rebase", "main")
        else:
            stopped = git(operation, "topic")
        assert stopped.returncode != 0, f"the {operation} did not stop on its conflict"
        head = git("rev-parse", "HEAD").stdout.strip()
        row = "# memory\n| 2026-10-06 | row |\n"
        (repo / "ESPALIER_MEMORY.md").write_text(row, encoding="utf-8")
        children = self._arm(hm, monkeypatch)
        rc = hm.main(["--root", str(repo), "after-memory-row", "--message", "docs(memory): t"])
        err = capsys.readouterr().err
        assert rc == 2, err
        assert "in progress" in err and "do not fall back to a broad commit" in err, err
        assert children == [], f"the phase ran {children} before refusing"
        assert "ESPALIER_MEMORY.md" not in git("diff", "--cached", "--name-only").stdout
        assert git("rev-parse", "HEAD").stdout.strip() == head, "a commit landed mid-operation"
        if operation == "rebase":
            # `git rebase --abort` resets the working tree hard, unstaged edits
            # included, whatever the phase does; the row is the operator's to
            # keep there. A merge or cherry-pick abort keeps unstaged edits.
            return
        assert git(operation, "--abort").returncode == 0
        assert (repo / "ESPALIER_MEMORY.md").read_text(encoding="utf-8") == row, (
            f"`git {operation} --abort` took the session row with it"
        )


def _answer_or_raise(value):
    if isinstance(value, Exception):
        raise value
    return value


class TestAfterGoalPushesTheRecord:
    """DEF-710: the snapshot is pushed inside after-goal -- after it is written,
    before the landing check, with no prompt and a bounded wait -- the first push
    of a record stays a hand step gated on the history audit, and a refused push
    stops the phase with the documented exit code. Driven with a fake runner:
    every subprocess the phase spawns is recorded, none runs."""

    @staticmethod
    def _root(tmp_path: Path) -> Path:
        r = tmp_path / "r"
        (r / "cc").mkdir(parents=True)
        (r / "cc" / "_working_summary.md").write_text(
            "# Working summary\n## 9. Optional Next Step\nx\n", encoding="utf-8"
        )
        return r

    @staticmethod
    def _arm(
        hm, monkeypatch, *, push_rc: int = 0, probe_rc: int = 0,
        record_remote: str | Exception = "origin",
    ) -> list[tuple[list[str], dict]]:
        import re
        import subprocess
        import types

        calls: list[tuple[list[str], dict]] = []

        def fake_run(argv, **kw):
            argv = [str(a) for a in argv]
            calls.append((argv, kw))
            rc = 0
            if argv[:2] == ["git", "push"]:
                rc = push_rc
            elif argv[:2] == ["git", "ls-remote"]:
                rc = probe_rc
            stdout = (
                "abc123 compactions=0 [transcript]\n" if argv[-1] == "--list"
                else "\n## Resume index\n- x\n"   # the marker the re-entry guard reads
            )
            return subprocess.CompletedProcess(argv, rc, stdout=stdout, stderr="")

        monkeypatch.setattr(hm, "subprocess", types.SimpleNamespace(
            run=fake_run, TimeoutExpired=subprocess.TimeoutExpired,
        ))
        # the owners the phase reads: read_summary's header, record_snapshot's ref
        # and its record-remote resolver (DEC-31: the phase reads the answer once
        # and never restates `origin`; the real resolver has its own rows in
        # tests/test_record_snapshot.py::TestRecordRemoteResolver)
        monkeypatch.setattr(
            hm, "_load",
            lambda _p, _n: types.SimpleNamespace(
                _ARTIFACT_HEADER=re.compile(r"===== compaction captured"),
                RECORD_REF="refs/heads/record",
                record_remote=lambda _root: _answer_or_raise(record_remote),
            ),
        )
        return calls

    @staticmethod
    def _tails(calls) -> list[str]:
        return [" ".join(a) if a[0] == "git" else a[-1] for a, _kw in calls]

    def test_probe_then_push_run_after_the_snapshot_and_before_the_landing_check(self, hm, tmp_path, monkeypatch):
        r = self._root(tmp_path)
        calls = self._arm(hm, monkeypatch)
        assert hm.main(["--root", str(r), "after-goal"]) == 0
        assert self._tails(calls) == [
            "--list",
            "tools/cc/session_summary.py",
            "scripts/record_snapshot.py",
            "git ls-remote --exit-code origin refs/heads/record",
            "git push origin record",
            "scripts/check_handoff_landing.py",
        ], calls
        push_argv, push_kw = next(c for c in calls if c[0][:2] == ["git", "push"])
        assert not {"--force", "-f", "--force-with-lease"} & set(push_argv)
        # no prompt, bounded wait -- a credential prompt cannot be answered here
        assert push_kw["timeout"] == 120 and push_kw["env"]["GIT_TERMINAL_PROMPT"] == "0"
        probe_kw = next(kw for a, kw in calls if a[:2] == ["git", "ls-remote"])
        assert probe_kw["timeout"] == 120 and probe_kw["env"]["GIT_TERMINAL_PROMPT"] == "0"

    def test_a_missing_remote_record_refuses_before_pushing_and_names_the_audit(self, hm, tmp_path, monkeypatch, capsys):
        r = self._root(tmp_path)
        calls = self._arm(hm, monkeypatch, probe_rc=2)
        assert hm.main(["--root", str(r), "after-goal"]) == 2
        err = capsys.readouterr().err
        assert "--audit-history" in err and "git push origin record" in err
        assert not any(a[:2] == ["git", "push"] for a, _ in calls)
        assert not any(a[-1] == "scripts/check_handoff_landing.py" for a, _ in calls)

    def test_a_refused_push_stops_the_phase_with_exit_two_before_the_landing_check(self, hm, tmp_path, monkeypatch, capsys):
        r = self._root(tmp_path)
        calls = self._arm(hm, monkeypatch, push_rc=128)
        with pytest.raises(SystemExit) as exc:
            hm.main(["--root", str(r), "after-goal"])
        assert exc.value.code == 2
        assert "record push exited 128" in capsys.readouterr().err
        assert not any(a[-1] == "scripts/check_handoff_landing.py" for a, _ in calls), calls

    def test_dry_run_announces_the_probe_and_the_push_without_running_them(self, hm, tmp_path, monkeypatch, capsys):
        r = self._root(tmp_path)
        calls = self._arm(hm, monkeypatch)
        assert hm.main(["--root", str(r), "after-goal", "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "would run: git ls-remote --exit-code origin refs/heads/record" in out
        assert "would run: git push origin record" in out
        assert not any(a[0] == "git" for a, _ in calls)

    def test_the_probe_the_refusal_and_the_push_name_the_configured_record_remote(self, hm, tmp_path, monkeypatch, capsys):
        """DEC-31: the resolver's answer, read once, at all three sites. A literal
        `origin` at any of them reds here -- earned red 2026-09-22, when all three
        still said `origin` while the resolver said `archive`. The rows above
        keep pinning `origin` through the fake resolver's DEFAULT."""
        # a fresh root per run: after-goal appends the resume index and refuses
        # to run twice over the same summary
        r = self._root(tmp_path / "push")
        calls = self._arm(hm, monkeypatch, record_remote="archive")
        assert hm.main(["--root", str(r), "after-goal"]) == 0
        capsys.readouterr()
        tails = self._tails(calls)
        assert "git ls-remote --exit-code archive refs/heads/record" in tails, tails
        assert "git push archive record" in tails, tails
        assert not any("origin" in t for t in tails if t.startswith("git ")), tails
        # the refusal on a missing remote record names the same remote
        r = self._root(tmp_path / "refuse")
        calls = self._arm(hm, monkeypatch, record_remote="archive", probe_rc=2)
        assert hm.main(["--root", str(r), "after-goal"]) == 2
        err = capsys.readouterr().err
        assert "git push archive record" in err and "origin" not in err, err
        # and so does the dry run
        r = self._root(tmp_path / "dry")
        calls = self._arm(hm, monkeypatch, record_remote="archive")
        assert hm.main(["--root", str(r), "after-goal", "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "would run: git push archive record" in out, out
        assert "origin" not in out, out

    def test_an_unresolved_record_remote_stops_the_phase_before_any_git_call(self, hm, tmp_path, monkeypatch, capsys):
        """The resolver refuses (the key is required and unset on a fresh clone of
        the public checkout): no probe, no push, no landing check, exit 2 with the
        owner's instruction on stderr -- the default would publish the record."""
        r = self._root(tmp_path / "refused")
        calls = self._arm(hm, monkeypatch, record_remote=RuntimeError(
            "espalier.recordRemote is not set in this checkout and espalier.toml requires it"))
        assert hm.main(["--root", str(r), "after-goal"]) == 2
        err = capsys.readouterr().err
        assert "record remote unresolved" in err and "espalier.recordRemote is not set" in err, err
        assert not any(a[0] == "git" for a, _ in calls), calls
        assert not any(a[-1] == "scripts/check_handoff_landing.py" for a, _ in calls), calls

    def test_a_rerun_after_a_failed_push_does_not_append_the_leg_twice(self, hm, tmp_path, monkeypatch, capsys):
        r = self._root(tmp_path)
        calls = self._arm(hm, monkeypatch, push_rc=1)
        with pytest.raises(SystemExit):
            hm.main(["--root", str(r), "after-goal"])
        leg = r / "cc" / "blueprints" / "compact_summaries" / "abc123.md"
        assert leg.read_text(encoding="utf-8").count("===== compaction captured") == 1
        # the operator follows the re-entry message: drop the resume index, re-run
        summary = r / "cc" / "_working_summary.md"
        text = summary.read_text(encoding="utf-8")
        summary.write_text(text[: text.index("## Resume index")].rstrip() + "\n", encoding="utf-8")
        calls.clear()
        with pytest.raises(SystemExit):
            hm.main(["--root", str(r), "after-goal"])
        assert leg.read_text(encoding="utf-8").count("===== compaction captured") == 1
        assert "not appended twice" in capsys.readouterr().out
