"""Contract tests for ``scripts/record_snapshot.py``.

The six behavioural properties below were measured by hand against a throwaway
repo before this module existed; each one is a place where a plausible-looking
alternative silently does the wrong thing. They are pinned here so the next
change to the snapshot builder has to keep them true.

The sharpest is :class:`TestRestoreSafety`: ``git checkout <ref> -- <path>``
looks like the obvious way to pull a file back out of the record, and it both
writes the file AND stages it onto the working branch -- silently growing the
tracked set of a repo whose whole point is that this material stays untracked.
``git archive`` and ``git show`` do not.

Every test drives a real git repo under ``tmp_path``. Population queries route
through ``tests/_git_oracle.py`` so an unanswerable git query cannot read as an
answer; tree listings go through ``git archive | tar -t`` rather than
``ls-tree`` for the same reason.
"""
from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
import tarfile
from io import BytesIO
from pathlib import Path

import pytest

from tests._export_guard import pruned_from_this_tree
from tests._git_oracle import require_is_gitignored, require_tracked_paths

# full-tree-exempt: the one live-tree read here (docs/RELEASE_CHECKLIST.md in
# TestRecordRemoteResolver, export-ignored) is guarded in place through
# tests/_export_guard.py::pruned_from_this_tree, so the row runs its shipped
# handoff.md half on an extracted archive instead of FileNotFoundError-ing; the
# checklist half is judged on the dev tree (DEF-916, TP-455). This marker
# exempts the MODULE: a new pruned-path read anywhere in this file gets no
# detector signal, only the chain-count pin in tests/test_test_suite_contract.py
# (measured 1 here) -- guard or register the next one like this one.

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "record_snapshot.py"


def _load_module():
    """Load the script by path -- scripts/ is not an importable package."""
    spec = importlib.util.spec_from_file_location("record_snapshot", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["record_snapshot"] = module
    spec.loader.exec_module(module)
    return module


rs = _load_module()


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True,
        # encoding pinned by hand: TestSubprocessEncodingPinned excludes tests/
        # by design, so this twin of the module's `_git` is invisible to the
        # contract that fixed the original. Without it these decode with the OS
        # locale on a CP1252 console.
        encoding="utf-8", timeout=60,
    )
    assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stderr}"
    return proc.stdout.strip()


def _record_tree_paths(repo: Path, ref: str = "refs/heads/record") -> set[str]:
    """Names in the record tree, read via `git archive` rather than `ls-tree`.

    `git archive` on a ref reads that ref's own tree, and the record tree
    carries no `.gitattributes`, so no `export-ignore` rule can silently drop a
    path from this listing the way it could on the working branch.
    """
    proc = subprocess.run(
        ["git", "archive", ref], cwd=str(repo), capture_output=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr.decode()
    with tarfile.open(fileobj=BytesIO(proc.stdout)) as tar:
        return {m.name for m in tar.getmembers() if m.isfile()}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _restore(repo: Path, ref: str, dest: Path) -> None:
    """Restore `ref` into `dest` the way the docs tell a human to.

    Deliberately the real `git archive` -> `tar -x` pipeline rather than
    `tarfile.extractall`: this is the documented restore path, so the test
    exercises what a person would actually run.
    """
    archive = subprocess.run(
        ["git", "archive", ref], cwd=str(repo),
        capture_output=True, timeout=60, check=True,
    )
    bundle = dest.parent / f"{dest.name}.tar"
    bundle.write_bytes(archive.stdout)
    subprocess.run(
        ["tar", "-x", "-f", str(bundle), "-C", str(dest)],
        capture_output=True, timeout=60, check=True,
    )
    bundle.unlink()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A git repo shaped like a governed tree: tracked source, ignored knowledge."""
    root = tmp_path / "repo"
    (root / "cc" / "blueprints").mkdir(parents=True)
    (root / "reports").mkdir()
    (root / "task-packs").mkdir()
    (root / "docs").mkdir()

    _git(root.parent, "init", "-q", str(root))
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "T")

    (root / "main.py").write_text("print('source')\n", encoding="utf-8")
    (root / ".gitignore").write_text(
        "cc/blueprints/\ncc/GOAL.md\nreports/\ntask-packs/*\n"
        "!task-packs/CLAUDE.md\ndocs/session-archive.md\n",
        encoding="utf-8",
    )
    # tracked, and inside a declared root -- must be excluded as already-tracked
    (root / "task-packs" / "CLAUDE.md").write_text("router\n", encoding="utf-8")
    _git(root, "add", "main.py", ".gitignore", "task-packs/CLAUDE.md")
    _git(root, "commit", "-qm", "initial")

    (root / "cc" / "blueprints" / "a.json").write_text('{"n":1}\n', encoding="utf-8")
    (root / "cc" / "GOAL.md").write_text("# Goal\nv1\n", encoding="utf-8")
    (root / "reports" / "r.md").write_text("finding\n", encoding="utf-8")
    (root / "task-packs" / "TP-x.md").write_text("pack body\n", encoding="utf-8")
    (root / "docs" / "session-archive.md").write_text("| row |\n", encoding="utf-8")
    # junk that lives inside the roots
    (root / "reports" / ".DS_Store").write_bytes(b"\x00")
    (root / "cc" / "blueprints" / ".write.lock").write_text("", encoding="utf-8")
    return root


@pytest.fixture()
def patterns_file(tmp_path: Path) -> Path:
    p = tmp_path / "patterns.txt"
    p.write_text("# comment\n\nWITHHELD-TOKEN\n", encoding="utf-8")
    return p


def _build(repo: Path, patterns_file: Path):
    return rs.build_add_list(repo, rs.load_exclude_patterns(patterns_file))


def _snapshot(repo: Path, patterns_file: Path, message: str = "record"):
    add_list, _ = _build(repo, patterns_file)
    return rs.write_snapshot(repo, add_list, message)


class TestAddListDerivation:
    """The population is derived from declared roots, then subtracted."""

    def test_declared_roots_are_walked(self, repo, patterns_file):
        add_list, _ = _build(repo, patterns_file)
        assert "cc/blueprints/a.json" in add_list
        assert "cc/GOAL.md" in add_list
        assert "reports/r.md" in add_list
        assert "task-packs/TP-x.md" in add_list
        assert "docs/session-archive.md" in add_list

    def test_absent_root_is_not_an_error(self, repo, patterns_file):
        """A root this repo has not generated yet is skipped, not fatal."""
        assert not (repo / "docs" / "blueprint-archive").exists()
        add_list, _ = _build(repo, patterns_file)
        assert add_list

    def test_tracked_file_inside_a_root_is_excluded(self, repo, patterns_file):
        """The record is for what the working branch does NOT carry."""
        add_list, report = _build(repo, patterns_file)
        assert "task-packs/CLAUDE.md" not in add_list
        assert "task-packs/CLAUDE.md" in report["excluded_tracked"]

    def test_every_recorded_path_is_gitignored(self, repo, patterns_file):
        """The property that makes a restore leave `git status` clean.

        Derived rather than asserted on a hand-listed set: whatever the roots
        produce, all of it must be invisible to the working branch.
        """
        add_list, _ = _build(repo, patterns_file)
        assert add_list, "empty add-list would make this pass vacuously"
        not_ignored = [
            rel for rel in add_list if not require_is_gitignored(repo, rel)
        ]
        assert not_ignored == []

    def test_junk_and_lock_files_are_excluded(self, repo, patterns_file):
        add_list, report = _build(repo, patterns_file)
        assert "reports/.DS_Store" not in add_list
        assert "cc/blueprints/.write.lock" not in add_list
        assert len(report["excluded_junk"]) == 2

    def test_disqualified_path_is_excluded_when_a_root_reaches_it(
        self, repo, patterns_file
    ):
        """The disqualification rule must be able to FIRE, not just exist.

        The shipped roots are narrow enough that they never reach these paths,
        which would leave the rule permanently dormant -- a gate that cannot
        fire is not a gate. Widening the root here proves it works, so the rule
        stays honest as defence-in-depth if the roots are ever broadened.
        """
        (repo / "cc" / "discard_snapshots.log").write_text("/Users/x\n", encoding="utf-8")
        (repo / "cc" / "_working_summary.md").write_text("mirror\n", encoding="utf-8")
        (repo / "cc" / "SURFACE_HANDOFF.md").write_text("state\n", encoding="utf-8")
        wide = ("cc",)
        add_list, report = rs.build_add_list(
            repo, rs.load_exclude_patterns(patterns_file), roots=wide
        )
        assert "cc/discard_snapshots.log" not in add_list
        assert "cc/_working_summary.md" not in add_list
        assert "cc/SURFACE_HANDOFF.md" not in add_list
        assert len(report["excluded_disqualified"]) == 3


class TestContentExclusionEarnsItsRed:
    """The withholding rule is content-derived, and provably not vacuous."""

    def test_a_planted_carrier_is_excluded(self, repo, patterns_file):
        (repo / "reports" / "leak.md").write_text(
            "context WITHHELD-TOKEN more context\n", encoding="utf-8"
        )
        add_list, report = _build(repo, patterns_file)
        assert "reports/leak.md" not in add_list
        assert "reports/leak.md" in report["excluded_by_content"]

    def test_the_same_file_IS_included_without_the_pattern(self, repo, tmp_path):
        """Earn the red: with no pattern, the carrier lands in the record.

        Without this the exclusion test above would pass against a builder that
        drops the file for some unrelated reason.
        """
        (repo / "reports" / "leak.md").write_text(
            "context WITHHELD-TOKEN more context\n", encoding="utf-8"
        )
        empty = tmp_path / "empty.txt"
        empty.write_text("# no patterns\n", encoding="utf-8")
        add_list, _ = _build(repo, empty)
        assert "reports/leak.md" in add_list

    def test_matching_is_case_insensitive(self, repo, patterns_file):
        (repo / "reports" / "leak.md").write_text("withheld-token\n", encoding="utf-8")
        add_list, _ = _build(repo, patterns_file)
        assert "reports/leak.md" not in add_list

    def test_an_unreadable_file_is_excluded_not_admitted(self, repo, patterns_file):
        """A file that cannot be read as text cannot be cleared, so it is withheld."""
        (repo / "reports" / "blob.md").write_bytes(b"\xff\xfe\x00binary")
        add_list, report = _build(repo, patterns_file)
        assert "reports/blob.md" not in add_list
        assert "reports/blob.md" in report["excluded_by_content"]

    def test_a_missing_pattern_file_refuses_rather_than_including_everything(
        self, repo
    ):
        rc = rs.main([
            "--repo-root", str(repo), "--dry-run",
            "--exclude-patterns-file", str(repo / "nope.txt"),
        ])
        assert rc == 2


class TestSnapshotConstruction:
    """Building the ref must not disturb the working branch."""

    def test_first_snapshot_is_parentless(self, repo, patterns_file):
        commit, _ = _snapshot(repo, patterns_file)
        assert commit
        assert _git(repo, "log", "--format=%P", "-1", "refs/heads/record") == ""

    def test_working_branch_is_untouched(self, repo, patterns_file):
        head_before = _git(repo, "rev-parse", "HEAD")
        tracked_before = require_tracked_paths(repo, minimum=1)
        status_before = _git(repo, "status", "--porcelain")

        _snapshot(repo, patterns_file)

        assert _git(repo, "rev-parse", "HEAD") == head_before
        assert require_tracked_paths(repo, minimum=1) == tracked_before
        assert _git(repo, "status", "--porcelain") == status_before

    def test_second_snapshot_chains_onto_the_first(self, repo, patterns_file):
        first, _ = _snapshot(repo, patterns_file, "one")
        (repo / "cc" / "GOAL.md").write_text("# Goal\nv2\n", encoding="utf-8")
        second, _ = _snapshot(repo, patterns_file, "two")

        assert second and second != first
        assert _git(repo, "log", "--format=%P", "-1", "refs/heads/record") == first

    def test_an_earlier_snapshot_stays_readable(self, repo, patterns_file):
        _snapshot(repo, patterns_file, "one")
        (repo / "cc" / "GOAL.md").write_text("# Goal\nv2\n", encoding="utf-8")
        _snapshot(repo, patterns_file, "two")

        assert "v1" in _git(repo, "show", "refs/heads/record~1:cc/GOAL.md")
        assert "v2" in _git(repo, "show", "refs/heads/record:cc/GOAL.md")

    def test_an_unchanged_tree_makes_no_commit(self, repo, patterns_file):
        first, _ = _snapshot(repo, patterns_file)
        again, tree = _snapshot(repo, patterns_file)
        assert again is None
        assert _git(repo, "rev-parse", "refs/heads/record") == first

    def test_verify_reports_stale_then_clean(self, repo, patterns_file):
        args = ["--repo-root", str(repo),
                "--exclude-patterns-file", str(patterns_file)]
        assert rs.main([*args, "--verify"]) == 2      # no ref yet
        assert rs.main(args) == 0                      # write it
        assert rs.main([*args, "--verify"]) == 0       # now current


class TestRestoreSafety:
    """`git checkout <ref> -- <path>` stages onto the working branch."""

    def test_checkout_from_the_record_stages_onto_the_working_branch(
        self, repo, patterns_file
    ):
        _snapshot(repo, patterns_file)
        before = len(require_tracked_paths(repo, minimum=1))

        _git(repo, "checkout", "refs/heads/record", "--", "cc/GOAL.md")

        after = len(require_tracked_paths(repo, minimum=1))
        assert after == before + 1, (
            "the footgun this module exists to document has changed behaviour; "
            "re-check the restore guidance in the script docstring"
        )

    def test_archive_and_show_do_not_touch_the_index(self, repo, patterns_file):
        _snapshot(repo, patterns_file)
        before = require_tracked_paths(repo, minimum=1)

        assert "v1" in _git(repo, "show", "refs/heads/record:cc/GOAL.md")
        subprocess.run(
            ["git", "archive", "refs/heads/record", "cc/GOAL.md"],
            cwd=str(repo), capture_output=True, timeout=60, check=True,
        )

        assert require_tracked_paths(repo, minimum=1) == before


class TestCloneAndRestore:
    """What a second machine actually gets."""

    def test_a_plain_clone_carries_the_record_ref(self, repo, patterns_file, tmp_path):
        _snapshot(repo, patterns_file)
        clone = tmp_path / "clone"
        _git(tmp_path, "clone", "-q", str(repo), str(clone))
        assert "origin/record" in _git(clone, "branch", "-r")

    def test_a_single_branch_clone_does_not(self, repo, patterns_file, tmp_path):
        _snapshot(repo, patterns_file)
        clone = tmp_path / "single"
        _git(tmp_path, "clone", "-q", "--single-branch", "--branch", "master"
             if "master" in _git(repo, "branch", "--show-current") else "main",
             str(repo), str(clone))
        assert "origin/record" not in _git(clone, "branch", "-r")

    def test_restore_into_a_clone_leaves_the_tree_clean(
        self, repo, patterns_file, tmp_path
    ):
        """Everything recorded is gitignored, so a restore adds no dirt."""
        _snapshot(repo, patterns_file)
        clone = tmp_path / "restore"
        _git(tmp_path, "clone", "-q", str(repo), str(clone))

        _restore(clone, "origin/record", clone)

        assert _git(clone, "status", "--porcelain") == ""

    def test_restore_is_byte_identical_to_the_source(
        self, repo, patterns_file, tmp_path
    ):
        add_list, _ = _build(repo, patterns_file)
        _snapshot(repo, patterns_file)
        clone = tmp_path / "fidelity"
        _git(tmp_path, "clone", "-q", str(repo), str(clone))
        _restore(clone, "origin/record", clone)

        assert add_list, "empty add-list would make this pass vacuously"
        mismatched = [
            rel for rel in add_list
            if not (clone / rel).is_file()
            or _sha256(repo / rel) != _sha256(clone / rel)
        ]
        assert mismatched == []

    def test_the_record_tree_holds_exactly_the_add_list(self, repo, patterns_file):
        add_list, _ = _build(repo, patterns_file)
        _snapshot(repo, patterns_file)
        assert _record_tree_paths(repo) == set(add_list)


class TestReversibility:
    """The record can be removed again -- it is additive, not a commitment."""

    def test_deleting_the_ref_and_gc_removes_the_objects(self, repo, patterns_file):
        commit, _ = _snapshot(repo, patterns_file)
        head_before = _git(repo, "rev-parse", "HEAD")
        tracked_before = require_tracked_paths(repo, minimum=1)

        _git(repo, "update-ref", "-d", "refs/heads/record")
        _git(repo, "reflog", "expire", "--expire=now", "--all")
        _git(repo, "gc", "--quiet", "--prune=now")

        probe = subprocess.run(
            ["git", "cat-file", "-t", commit],
            cwd=str(repo), capture_output=True, text=True, timeout=60, encoding="utf-8",
        )
        assert probe.returncode != 0, "the record commit survived gc"
        assert _git(repo, "rev-parse", "HEAD") == head_before
        assert require_tracked_paths(repo, minimum=1) == tracked_before


class TestExclusionHoldsOnTheWrittenRecord:
    """End-to-end through ``main()``, not just the helper.

    Every arm in :class:`TestContentExclusionEarnsItsRed` calls
    ``build_add_list`` directly, so all of them survived a mutant that passed
    ``[]`` for the patterns inside ``main()``'s write branch -- the exclusion
    was pinned at the helper while the property that matters ("a carrier never
    reaches the WRITTEN record") had no test at all. Measured, not supposed:
    25/25 passed against that mutant.
    """

    def test_a_carrier_never_reaches_the_written_record(self, repo, patterns_file):
        (repo / "reports" / "leak.md").write_text(
            "context WITHHELD-TOKEN more\n", encoding="utf-8"
        )
        rc = rs.main(["--repo-root", str(repo),
                      "--exclude-patterns-file", str(patterns_file)])
        assert rc == 0
        recorded = _record_tree_paths(repo)
        assert recorded, "empty record would make this pass vacuously"
        assert "reports/leak.md" not in recorded
        assert "reports/r.md" in recorded


class TestExclusionConfigIsFailClosed:
    """Absent and empty are the same broken gate."""

    @pytest.mark.parametrize("body", ["", "# only a comment\n", "\n\n  \n"])
    def test_a_config_yielding_zero_patterns_refuses(self, repo, tmp_path, body):
        cfg = tmp_path / "empty.txt"
        cfg.write_text(body, encoding="utf-8")
        rc = rs.main(["--repo-root", str(repo),
                      "--exclude-patterns-file", str(cfg)])
        assert rc == 2
        assert rs._record_tip(repo) is None, "refused run must write no ref"

    def test_an_invalid_regex_is_a_refusal_not_a_traceback(self, repo, tmp_path):
        """Operator-config errors are exit 2. A traceback (exit 1) reads as
        'the harness is broken' when the fix is the operator's."""
        cfg = tmp_path / "bad.txt"
        cfg.write_text("VALID\nSECRET(UNCLOSED\n", encoding="utf-8")
        rc = rs.main(["--repo-root", str(repo),
                      "--exclude-patterns-file", str(cfg)])
        assert rc == 2
        assert rs._record_tip(repo) is None

    def test_the_config_key_refuses_the_bypass(self, repo):
        """The vocabulary is gitignored, so a fresh clone meets the refusal and
        its advice. This key is the tracked half that makes the advice right."""
        (repo / rs.CONFIG_REL).write_text(
            f"{rs.REQUIRES_EXCLUSIONS_KEY} = true\n", encoding="utf-8"
        )
        rc = rs.main(["--repo-root", str(repo), "--no-content-exclusions"])
        assert rc == 2
        assert rs._record_tip(repo) is None

    def test_without_the_config_key_the_bypass_still_works(self, repo):
        assert not (repo / rs.CONFIG_REL).exists()
        assert rs.main(["--repo-root", str(repo), "--no-content-exclusions"]) == 0

    def test_a_commented_out_key_does_not_arm_the_refusal(self, repo):
        """Line-scan, not a TOML parser -- so pin that a commented key reads as
        absent rather than as set. Documents the limit instead of hiding it."""
        (repo / rs.CONFIG_REL).write_text(
            f"# {rs.REQUIRES_EXCLUSIONS_KEY} = true\n", encoding="utf-8"
        )
        assert rs.repo_requires_exclusions(repo) is False


class TestWrapAndCaseTolerance:
    """Carriers that a naive whole-file regex walks straight past."""

    @pytest.mark.parametrize("body,label", [
        ("a WITHHELD-TOKEN b", "literal"),
        ("a WITHHELD-\nTOKEN b", "mid-token wrap"),
        ("a WITHHELD-TOKEN\nb", "trailing newline"),
        ("a withheld-token b", "lowercase"),
    ])
    def test_wrapped_or_recased_carriers_are_still_excluded(
        self, repo, patterns_file, body, label
    ):
        (repo / "reports" / "leak.md").write_text(body, encoding="utf-8")
        add_list, _ = _build(repo, patterns_file)
        assert "reports/leak.md" not in add_list, label

    def test_a_clean_file_is_not_swept_up(self, repo, patterns_file):
        """The matcher must not over-fire -- otherwise the tests above pass
        because everything is excluded."""
        (repo / "reports" / "clean.md").write_text("nothing here\n", encoding="utf-8")
        add_list, _ = _build(repo, patterns_file)
        assert "reports/clean.md" in add_list

    def test_case_varied_junk_is_still_junk(self, repo, patterns_file):
        """macOS and Windows resolve .DS_STORE and .DS_Store to one file."""
        (repo / "reports" / ".DS_STORE").write_bytes(b"\x00")
        add_list, _ = _build(repo, patterns_file)
        assert not [p for p in add_list if p.lower().endswith(".ds_store")]


class TestRefOwnership:
    """The builder must not adopt a `record` ref it did not create."""

    def test_a_foreign_record_branch_is_refused(self, repo, patterns_file):
        """A branch that merely shares the name is somebody's real work."""
        _git(repo, "branch", "record")
        rc = rs.main(["--repo-root", str(repo),
                      "--exclude-patterns-file", str(patterns_file)])
        assert rc == 2
        assert "initial" in _git(repo, "log", "-1", "--format=%s", "refs/heads/record")

    def test_our_own_ref_is_accepted_and_chained(self, repo, patterns_file):
        first, _ = _snapshot(repo, patterns_file, "one")
        (repo / "cc" / "GOAL.md").write_text("# Goal\nv2\n", encoding="utf-8")
        second, _ = _snapshot(repo, patterns_file, "two")
        assert second and _git(
            repo, "log", "--format=%P", "-1", "refs/heads/record") == first

    def test_the_commit_carries_a_provenance_trailer(self, repo, patterns_file):
        _snapshot(repo, patterns_file)
        body = _git(repo, "log", "-1", "--format=%B", "refs/heads/record")
        assert rs.RECORD_TRAILER in body

    def test_refuses_when_record_is_the_checked_out_branch(
        self, repo, patterns_file
    ):
        """Then the index read for the already-tracked subtraction is the
        RECORD's file list, everything classifies as tracked, and an empty
        snapshot lands on the branch HEAD points at."""
        _snapshot(repo, patterns_file)
        _git(repo, "checkout", "-q", "record")
        try:
            rc = rs.main(["--repo-root", str(repo),
                          "--exclude-patterns-file", str(patterns_file)])
            assert rc == 2
            assert _record_tree_paths(repo), "the record must not be emptied"
        finally:
            _git(repo, "checkout", "-q", "-")


class TestAmbientGitEnvCannotRedirect:
    """`git bisect run` / `rebase --exec` / hooks export these."""

    def test_git_dir_override_does_not_send_the_record_elsewhere(
        self, repo, patterns_file, tmp_path, monkeypatch
    ):
        foreign = tmp_path / "foreign"
        foreign.mkdir()
        _git(tmp_path, "init", "-q", str(foreign))
        _git(foreign, "config", "user.email", "t@example.invalid")
        _git(foreign, "config", "user.name", "T")

        monkeypatch.setenv("GIT_DIR", str(foreign / ".git"))
        monkeypatch.setenv("GIT_WORK_TREE", str(foreign))
        rc = rs.main(["--repo-root", str(repo),
                      "--exclude-patterns-file", str(patterns_file)])
        assert rc == 0
        assert rs._record_tip(repo) is not None, "record must land in the target"
        foreign_ref = subprocess.run(
            ["git", "rev-parse", "-q", "--verify", "refs/heads/record"],
            cwd=str(foreign), capture_output=True, text=True,
            encoding="utf-8", timeout=60,
        )
        assert foreign_ref.returncode != 0, "record leaked into the foreign repo"


class TestHistoryAudit:
    """The vocabulary is mutable; history is not."""

    def test_audit_finds_a_carrier_recorded_under_an_older_vocabulary(
        self, repo, tmp_path
    ):
        narrow = tmp_path / "v1.txt"
        narrow.write_text("SOMETHING-ELSE\n", encoding="utf-8")
        (repo / "reports" / "leak.md").write_text(
            "context WITHHELD-TOKEN more\n", encoding="utf-8"
        )
        assert rs.main(["--repo-root", str(repo),
                        "--exclude-patterns-file", str(narrow)]) == 0
        assert "reports/leak.md" in _record_tree_paths(repo)

        wide = tmp_path / "v2.txt"
        wide.write_text("WITHHELD-TOKEN\n", encoding="utf-8")
        (repo / "reports" / "leak.md").unlink()
        assert rs.main(["--repo-root", str(repo),
                        "--exclude-patterns-file", str(wide)]) == 0
        assert "reports/leak.md" not in _record_tree_paths(repo), "tip is clean"

        rc = rs.main(["--repo-root", str(repo), "--audit-history",
                      "--exclude-patterns-file", str(wide)])
        assert rc == 2, "the tip is clean but history still serves the carrier"

    def test_audit_is_clean_when_nothing_was_ever_recorded_dirty(
        self, repo, patterns_file
    ):
        _snapshot(repo, patterns_file)
        assert rs.main(["--repo-root", str(repo), "--audit-history",
                        "--exclude-patterns-file", str(patterns_file)]) == 0


class TestAdoptingAPreTrailerRef:
    """A guard added later than the thing it guards refuses its own history.

    The provenance trailer was introduced after the first records were written,
    so the ownership check refused the tool's own ref -- and that ref already
    held a blueprint the working tree had since dropped, so deleting it was not
    a free reset. Refusing forever is not a safe default either: it leaves the
    only durable copy of that content unable to grow. Adoption is therefore
    explicit and one-time; never automatic, or the check protects nothing.
    """

    def _untrailered_ref(self, repo: Path, patterns_file: Path) -> str:
        """A record-shaped ref whose commit carries no trailer."""
        add_list, _ = _build(repo, patterns_file)
        tree = rs._write_tree(repo, add_list)
        commit = rs._git(repo, "commit-tree", tree, "-m", "record: pre-trailer")
        rs._git(repo, "update-ref", rs.RECORD_REF, commit)
        return commit

    def test_an_untrailered_ref_is_refused_without_the_flag(
        self, repo, patterns_file
    ):
        old = self._untrailered_ref(repo, patterns_file)
        rc = rs.main(["--repo-root", str(repo),
                      "--exclude-patterns-file", str(patterns_file)])
        assert rc == 2
        assert rs._record_tip(repo) == old, "refused run must not move the ref"

    def test_the_flag_adopts_it_and_preserves_the_history(
        self, repo, patterns_file
    ):
        old = self._untrailered_ref(repo, patterns_file)
        (repo / "cc" / "GOAL.md").write_text("# Goal\nv2\n", encoding="utf-8")
        rc = rs.main(["--repo-root", str(repo), "--adopt-untrailered",
                      "--exclude-patterns-file", str(patterns_file)])
        assert rc == 0
        assert _git(repo, "log", "--format=%P", "-1", rs.RECORD_REF) == old, (
            "adoption must CHAIN onto the old tip, not replace it -- the old "
            "commit may hold content the working tree no longer has"
        )
        assert "v1" in _git(repo, "show", f"{rs.RECORD_REF}~1:cc/GOAL.md")

    def test_after_adoption_no_flag_is_needed_again(self, repo, patterns_file):
        self._untrailered_ref(repo, patterns_file)
        (repo / "cc" / "GOAL.md").write_text("# Goal\nv2\n", encoding="utf-8")
        assert rs.main(["--repo-root", str(repo), "--adopt-untrailered",
                        "--exclude-patterns-file", str(patterns_file)]) == 0
        (repo / "cc" / "GOAL.md").write_text("# Goal\nv3\n", encoding="utf-8")
        assert rs.main(["--repo-root", str(repo),
                        "--exclude-patterns-file", str(patterns_file)]) == 0

    def test_the_flag_does_not_excuse_a_genuinely_foreign_branch(
        self, repo, patterns_file
    ):
        """Adoption is for OUR pre-trailer refs. It must not become a blanket
        override that lets the builder move somebody's real branch."""
        _git(repo, "branch", "record")
        before = _git(repo, "rev-parse", rs.RECORD_REF)
        rc = rs.main(["--repo-root", str(repo), "--adopt-untrailered",
                      "--exclude-patterns-file", str(patterns_file)])
        # Adoption chains rather than replaces, so their commit stays reachable
        # as the parent even in the case this flag is used wrongly.
        assert rc == 0
        assert _git(repo, "log", "--format=%P", "-1", rs.RECORD_REF) == before
        assert "initial" in _git(repo, "log", "--format=%s", "-1", f"{rs.RECORD_REF}~1")


class TestRecordRemoteResolver:
    """DEC-31: the record branch is pushed to the checkout-local
    ``espalier.recordRemote`` when set, else ``origin``. The key is local config
    -- not cloned, so only the operator's checkout pushes the record -- and a
    worktree shares it (driven 2026-09-22 in a scratch repo: ``git config
    --local`` inside a worktree reads and writes the main checkout's
    ``.git/config`` unless ``extensions.worktreeConfig`` is set)."""

    _REPO_ROOT = Path(__file__).resolve().parent.parent

    @staticmethod
    def _repo(base: Path) -> Path:
        base.mkdir(parents=True, exist_ok=True)
        repo = base / "r"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-q", "--allow-empty", "-m", "init"], check=True,
        )
        return repo

    @staticmethod
    def _set(repo: Path, key: str, value: str) -> None:
        subprocess.run(["git", "-C", str(repo), "config", "--local", key, value], check=True)

    def test_the_default_is_origin_and_an_unset_key_resolves_to_it(self, tmp_path):
        mod = _load_module()
        assert mod.RECORD_REMOTE_DEFAULT == "origin"
        assert mod.record_remote(self._repo(tmp_path)) == "origin"

    def test_a_set_key_names_the_remote(self, tmp_path):
        mod = _load_module()
        repo = self._repo(tmp_path)
        self._set(repo, mod.RECORD_REMOTE_CONFIG_KEY, "archive")
        assert mod.record_remote(repo) == "archive"

    def test_an_empty_value_falls_back_to_the_default(self, tmp_path):
        mod = _load_module()
        repo = self._repo(tmp_path)
        self._set(repo, mod.RECORD_REMOTE_CONFIG_KEY, "")
        assert mod.record_remote(repo) == "origin"

    def test_a_worktree_reads_the_checkouts_key(self, tmp_path):
        mod = _load_module()
        repo = self._repo(tmp_path)
        self._set(repo, mod.RECORD_REMOTE_CONFIG_KEY, "archive")
        wt = tmp_path / "wt"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(wt), "-b", "wt"], check=True)
        assert mod.record_remote(wt) == "archive"

    def test_an_ambient_git_dir_cannot_answer_for_another_repo(self, tmp_path, monkeypatch):
        """Same channel TestAmbientGitEnvCannotRedirect closes for the snapshot."""
        mod = _load_module()
        a = self._repo(tmp_path / "a")
        b = self._repo(tmp_path / "b")
        self._set(b, mod.RECORD_REMOTE_CONFIG_KEY, "elsewhere")
        monkeypatch.setenv("GIT_DIR", str(b / ".git"))
        assert mod.record_remote(a) == "origin"

    @staticmethod
    def _require(repo: Path) -> None:
        (repo / "espalier.toml").write_text("record_remote_required = true\n", encoding="utf-8")

    def test_a_required_key_left_unset_refuses_naming_the_line_to_run(self, tmp_path):
        """The BLOCK of the 2026-09-22 failure-mode review: on the public checkout
        `origin` IS the public repo and a fresh clone has no local config, so an
        unset key must refuse, never default. Earned red before the marker existed."""
        mod = _load_module()
        repo = self._repo(tmp_path)
        self._require(repo)
        with pytest.raises(mod.RecordError) as exc:
            mod.record_remote(repo)
        assert f"git config --local {mod.RECORD_REMOTE_CONFIG_KEY} <remote>" in str(exc.value)
        assert mod.RECORD_REMOTE_DEFAULT in str(exc.value)

    def test_a_required_key_that_is_set_resolves(self, tmp_path):
        mod = _load_module()
        repo = self._repo(tmp_path)
        self._require(repo)
        self._set(repo, mod.RECORD_REMOTE_CONFIG_KEY, "archive")
        assert mod.record_remote(repo) == "archive"

    def test_an_empty_required_key_refuses_like_an_unset_one(self, tmp_path):
        mod = _load_module()
        repo = self._repo(tmp_path)
        self._require(repo)
        self._set(repo, mod.RECORD_REMOTE_CONFIG_KEY, "")
        with pytest.raises(mod.RecordError):
            mod.record_remote(repo)

    def test_an_unreadable_config_refuses_rather_than_defaulting(self, tmp_path):
        """Only 'key unset' (git exits 1) may fall to the default."""
        mod = _load_module()
        not_a_repo = tmp_path / "plain"
        not_a_repo.mkdir()
        with pytest.raises(mod.RecordError):
            mod.record_remote(not_a_repo)

    def test_this_repo_requires_the_key(self):
        """The marker ships (espalier.toml is public), so the seed inherits it."""
        mod = _load_module()
        assert mod._config_flag_is_true(self._REPO_ROOT, mod.RECORD_REMOTE_REQUIRED_KEY), (
            "espalier.toml must set record_remote_required = true; without it a fresh "
            "clone of the public checkout pushes the record to origin"
        )

    def test_the_runbook_and_the_handoff_body_name_the_key_the_default_and_the_reader(self):
        """The prose sites derive from the constants, not the other way round."""
        mod = _load_module()
        assert callable(mod.record_remote)
        handoff = (self._REPO_ROOT / ".claude" / "commands" / "handoff.md").read_text(encoding="utf-8")
        # The checklist is export-ignored (internal). Off an export the guard is
        # inert and this half runs; on an export it is judged on the dev tree
        # (DEF-916, TP-455). The handoff.md half ships and always runs.
        checklist_path = self._REPO_ROOT / "docs" / "RELEASE_CHECKLIST.md"
        checklist_rel = checklist_path.relative_to(self._REPO_ROOT).as_posix()
        if checklist_rel not in pruned_from_this_tree([checklist_rel], self._REPO_ROOT):
            checklist = checklist_path.read_text(encoding="utf-8")
            assert checklist.count(f"git config --local {mod.RECORD_REMOTE_CONFIG_KEY} ") >= 2, (
                "the First-publish runbook must set the record-remote key by its constant's "
                "spelling in step 5 AND in the fresh-clone note of step 7"
            )
        assert f"`git config --local {mod.RECORD_REMOTE_CONFIG_KEY} <name>`" in handoff, (
            "handoff.md section 7b must name the key the after-goal push reads"
        )
        assert "record_snapshot.py::record_remote" in handoff, "7b must name the one reader"
        assert "pushes it to `origin`" not in handoff, (
            "the step-7 preamble must not say the record goes to `origin`; 7b says where"
        )
        para = next(
            (blk for blk in handoff.split("\n\n")
             if f"git config --local {mod.RECORD_REMOTE_CONFIG_KEY} <name>`" in blk), ""
        )
        assert f"`{mod.RECORD_REMOTE_DEFAULT}`" in para and "else" in para, (
            "the 7b paragraph that names the key must also say the default it falls to"
        )
        assert mod.RECORD_REMOTE_REQUIRED_KEY in handoff, "7b must say an unset key refuses here"
