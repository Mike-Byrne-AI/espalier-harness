"""Behaviour tests for ``scripts/archive_transcripts.py``.

The script is a *verifier*, and this repo's dominant defect class -- measured
across two fan-outs on 2026-08-30, where eight of thirteen surviving findings
were one broken oracle -- is a verification that cannot fail. A red-team pass on
2026-08-31 confirmed the pattern held here: the load-bearing gate compared the
archive against ``build_archive``'s return value, which decrements once per lost
file, so both sides of the equality moved together and the gate could never fire.
13 of 15 mutants survived the first version of this suite.

Every class below therefore pins a *specific demonstrated* failure, and the
comments say which. Cases are weighted to failures that exit 0.

# slow-exempt: 30 in-process/CLI cases over tmp_path tarballs, measured 1.2s
# total (every individual duration < 0.005s). Belongs in the `-m "not slow"` PR
# slice: this is the only mechanical coverage of a tool that DELETES files, and
# _SLOW_FILES would deselect it from both that slice and release_check.py's.
# The `integration` marker in conftest's _MARKER_RULES is still required and
# still correct -- it spawns subprocesses, so it cannot be `unit`.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "archive_transcripts.py"

# 1 / 2 / 4 files per directory and non-arithmetic sizes. Both are load-bearing:
# an earlier fixture used 2/2/3 with sizes 10..70, where two directory counts
# coincided AND 7 files x 40 bytes equalled the 280-byte total -- so a counter
# returning `count * middle_size` passed. 7+13+29+41+67+103+211 = 471, and
# 7 x 67 = 469, so the sum cannot be reproduced by multiplication.
_SIZES = {
    "proj-a/one.jsonl": 7,
    "proj-b/two.jsonl": 13,
    "proj-b/three.jsonl": 29,
    "proj-c/four.jsonl": 41,
    "proj-c/five.jsonl": 67,
    "proj-c/six.jsonl": 103,
    "proj-c/seven.jsonl": 211,
}
_TOTAL = sum(_SIZES.values())      # 471
_COUNT = len(_SIZES)               # 7


def _load():
    spec = importlib.util.spec_from_file_location("_archive_transcripts", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8"
    )


@pytest.fixture
def source(tmp_path: Path) -> Path:
    src = tmp_path / "projects"
    for rel, size in _SIZES.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x" * size, encoding="utf-8")
    return src


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    d = tmp_path / "archives"
    d.mkdir()
    return d


class TestSnapshot:
    def test_counts_every_file_and_sums_bytes(self, source: Path) -> None:
        mod = _load()
        files, total, errors = mod.snapshot_source(source)
        assert len(files) == _COUNT
        assert total == _TOTAL
        assert total != _COUNT * 67, "fixture must not let count*size reproduce the sum"
        assert errors == []
        assert files == sorted(files)
        assert "proj-c/seven.jsonl" in files

    def test_unreadable_directory_is_reported_not_swallowed(
        self, source: Path
    ) -> None:
        """F3: os.walk's onerror previously discarded this, dropping a subtree."""
        mod = _load()
        secret = source / "proj-c"
        secret.chmod(0o000)
        try:
            # PRECONDITION PROBE, in the spirit of
            # `tests/test_integrity.py::_traversal_denied`: ask the OS whether
            # the deny actually took, rather than assuming `chmod` staged it.
            # On Windows `os.chmod` only toggles the read-only FILE attribute,
            # which does not apply to directories, so the walk succeeded, no
            # error surfaced, and this red-team reproduction failed against a
            # tree that was never damaged. A platform skipif would miss the
            # root and permissive-network-mount cases this also covers.
            # Asked with `listdir`, not `stat` -- `stat` answers for a
            # chmod-000 directory on some platforms; enumeration is the
            # capability `snapshot_source` actually needs.
            try:
                os.listdir(secret)
            except PermissionError:
                pass                  # good -- the directory really is closed
            else:
                pytest.skip("chmod did not deny directory traversal here")
            files, _total, errors = mod.snapshot_source(source)
        finally:
            secret.chmod(0o755)
        assert errors, "an unreadable directory must surface, not vanish"
        assert len(files) < _COUNT

    def test_symlinked_directory_is_reported(self, source: Path, tmp_path: Path) -> None:
        """F3b: os.walk does not follow it, so its contents leave no trace."""
        mod = _load()
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        (outside / "hidden.jsonl").write_text("z" * 5, encoding="utf-8")
        (source / "linked").symlink_to(outside, target_is_directory=True)
        _files, _total, errors = mod.snapshot_source(source)
        assert any("symlinked directory" in e for e in errors)


class TestMemberCountGate:
    """F1 -- the gate that must compare against the SNAPSHOT, not against `added`."""

    def test_rejects_archive_with_fewer_members_than_snapshot(
        self, source: Path, dest: Path
    ) -> None:
        mod = _load()
        files, _t, _e = mod.snapshot_source(source)
        out = dest / "short.tgz"
        mod.build_archive(source, files[:5], out, arcroot="projects")
        ok, report = mod.verify_archive(out, expected_members=len(files))
        assert ok is False
        assert report["actual_members"] == 5
        assert "member count mismatch" in report["error"]

    def test_unreadable_file_fails_the_run_instead_of_shrinking_both_sides(
        self, source: Path, dest: Path
    ) -> None:
        """The red-team's F1 reproduction: 7 in, 6 archived, previously exit 0."""
        victim = source / "proj-c" / "four.jsonl"
        victim.chmod(0o000)
        try:
            # Same probe, different question: a chmod-000 FILE still answers
            # `os.stat` (that permission lives on the parent directory), so the
            # capability to test is the READ the archiver performs. On Windows
            # the read succeeds, all 7 members archive, and the gate correctly
            # exits 0 -- the earn-the-red is what could not be staged, not the
            # product. The Windows-reachable sibling covering this gate is
            # `test_rejects_archive_with_fewer_members_than_snapshot`.
            try:
                victim.read_bytes()
            except PermissionError:
                pass                  # good -- the file really is unreadable
            else:
                pytest.skip("chmod did not deny reads here")
            rc = _run("--source", str(source), "--dest", str(dest),
                      "--now", "2026-01-01", "--json")
        finally:
            victim.chmod(0o644)
        assert rc.returncode == 2, rc.stdout
        assert list(dest.glob("*.tgz")) == [], "a short archive was promoted"

    def test_accepts_a_complete_archive(self, source: Path, dest: Path) -> None:
        mod = _load()
        files, _t, _e = mod.snapshot_source(source)
        out = dest / "full.tgz"
        added, skipped = mod.build_archive(source, files, out, arcroot="projects")
        assert skipped == []
        ok, report = mod.verify_archive(out, expected_members=added)
        assert ok is True
        assert report["actual_members"] == _COUNT

    def test_sha256_is_the_files_actual_digest(self, source: Path, dest: Path) -> None:
        """F13: the old assertions pinned LENGTH and self-consistency only, so
        replacing the hash with a constant passed both."""
        mod = _load()
        files, _t, _e = mod.snapshot_source(source)
        out = dest / "full.tgz"
        added, _sk = mod.build_archive(source, files, out, arcroot="projects")
        _ok, report = mod.verify_archive(out, expected_members=added)
        assert report["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()

    def test_rejects_a_truncated_archive(self, source: Path, dest: Path) -> None:
        mod = _load()
        files, _t, _e = mod.snapshot_source(source)
        out = dest / "trunc.tgz"
        added, _sk = mod.build_archive(source, files, out, arcroot="projects")
        raw = out.read_bytes()
        out.write_bytes(raw[: len(raw) // 2])
        ok, report = mod.verify_archive(out, expected_members=added)
        assert ok is False
        assert report["actual_members"] is None

    def test_symlink_members_are_counted_not_rejected(
        self, source: Path, dest: Path
    ) -> None:
        """F11: isfile() is isreg(), so a symlink made a GOOD archive fail."""
        mod = _load()
        (source / "proj-a" / "link.jsonl").symlink_to(source / "proj-a" / "one.jsonl")
        files, _t, _e = mod.snapshot_source(source)
        out = dest / "linked.tgz"
        added, _sk = mod.build_archive(source, files, out, arcroot="projects")
        ok, report = mod.verify_archive(out, expected_members=len(files))
        assert ok is True, report.get("error")
        assert report["actual_members"] == _COUNT + 1


class TestEmptySource:
    def test_zero_files_refuses_and_writes_nothing(self, tmp_path: Path, dest: Path) -> None:
        """F2: an empty tree previously produced an 83-byte 'verified' archive."""
        empty = tmp_path / "empty"
        empty.mkdir()
        rc = _run("--source", str(empty), "--dest", str(dest), "--now", "2026-01-01")
        assert rc.returncode == 2
        assert list(dest.glob("*.tgz")) == []

    def test_zero_files_does_not_prune_existing_archives(
        self, tmp_path: Path, dest: Path
    ) -> None:
        """F2b: the 83-byte non-backup also evicted real archives."""
        mod = _load()
        pre = []
        for i in range(3):
            p = dest / f"{mod.ARCHIVE_PREFIX}2026-0{i+1}-01{mod.ARCHIVE_SUFFIX}"
            p.write_text("real", encoding="utf-8")
            pre.append(p.name)
        empty = tmp_path / "empty"
        empty.mkdir()
        _run("--source", str(empty), "--dest", str(dest), "--now", "2026-01-01")
        assert sorted(p.name for p in dest.glob("*.tgz")) == sorted(pre)


class TestOverwriteRefusal:
    def test_refuses_to_replace_an_existing_archive(
        self, source: Path, dest: Path
    ) -> None:
        """F7: the default target for today was the operator's real 398 MB file."""
        mod = _load()
        target = dest / f"{mod.ARCHIVE_PREFIX}2026-01-01{mod.ARCHIVE_SUFFIX}"
        target.write_bytes(b"PRECIOUS" * 100)
        before = target.read_bytes()
        rc = _run("--source", str(source), "--dest", str(dest), "--now", "2026-01-01")
        assert rc.returncode == 1
        assert target.read_bytes() == before, "an existing archive was overwritten"

    def test_force_allows_replacement(self, source: Path, dest: Path) -> None:
        mod = _load()
        target = dest / f"{mod.ARCHIVE_PREFIX}2026-01-01{mod.ARCHIVE_SUFFIX}"
        target.write_bytes(b"old")
        rc = _run("--source", str(source), "--dest", str(dest),
                  "--now", "2026-01-01", "--force")
        assert rc.returncode == 0, rc.stdout
        assert target.read_bytes() != b"old"


class TestPruneFloor:
    def test_keeps_the_n_most_recent(self, dest: Path) -> None:
        mod = _load()
        made = []
        for i in range(5):
            p = dest / f"{mod.ARCHIVE_PREFIX}2026-08-0{i}{mod.ARCHIVE_SUFFIX}"
            p.write_text("x", encoding="utf-8")
            os.utime(p, (1000 + i, 1000 + i))
            made.append(p)
        known = [p.name for p in made]
        removed = mod.prune_archives(dest, keep=2, known=known)
        surviving = sorted(p.name for p in dest.glob(f"{mod.ARCHIVE_PREFIX}*"))
        assert len(surviving) == 2
        assert len(removed) == 3
        assert surviving == sorted(p.name for p in made[-2:])

    def test_never_removes_the_only_copy_even_at_keep_zero(self, dest: Path) -> None:
        mod = _load()
        only = dest / f"{mod.ARCHIVE_PREFIX}2026-08-01{mod.ARCHIVE_SUFFIX}"
        only.write_text("x", encoding="utf-8")
        assert mod.prune_archives(dest, keep=0, known=[only.name]) == []
        assert only.exists()

    def test_at_keep_zero_the_survivor_is_the_NEWEST(self, dest: Path) -> None:
        """Isolates the ``keep < 1`` clamp, which the floor-of-one cannot backstop.

        Earned: mutating the clamp alone left the sibling test above green,
        because the in-loop floor caught it. Both guards keep *a* copy -- but
        they disagree about WHICH. ``archives`` is newest-first, so an unclamped
        ``keep=0`` slices from index 0 and deletes the NEWEST.
        """
        mod = _load()
        made = []
        for i in range(3):
            p = dest / f"{mod.ARCHIVE_PREFIX}2026-08-0{i}{mod.ARCHIVE_SUFFIX}"
            p.write_text("x", encoding="utf-8")
            os.utime(p, (2000 + i, 2000 + i))
            made.append(p)
        mod.prune_archives(dest, keep=0, known=[p.name for p in made])
        surviving = [p for p in dest.glob(f"{mod.ARCHIVE_PREFIX}*") if p.exists()]
        assert len(surviving) == 1
        assert surviving[0].name == made[-1].name

    def test_never_prunes_an_archive_it_did_not_create(self, dest: Path) -> None:
        """F8: a copy restored by hand is the one holding unique history."""
        mod = _load()
        mine = []
        for i in range(3):
            p = dest / f"{mod.ARCHIVE_PREFIX}2026-08-1{i}{mod.ARCHIVE_SUFFIX}"
            p.write_text("mine", encoding="utf-8")
            os.utime(p, (5000 + i, 5000 + i))
            mine.append(p)
        imported = dest / f"{mod.ARCHIVE_PREFIX}2026-05-01{mod.ARCHIVE_SUFFIX}"
        imported.write_text("restored from a backup drive", encoding="utf-8")
        os.utime(imported, (1, 1))
        mod.prune_archives(dest, keep=1, known=[p.name for p in mine])
        assert imported.exists(), "pruned a file this tool never created"

    def test_never_prunes_the_archive_just_written(self, dest: Path) -> None:
        """F9: a future-mtime bystander sorted ahead and the run ate its own output."""
        mod = _load()
        fresh = dest / f"{mod.ARCHIVE_PREFIX}2026-08-31{mod.ARCHIVE_SUFFIX}"
        fresh.write_text("just written", encoding="utf-8")
        future = dest / f"{mod.ARCHIVE_PREFIX}2099-01-01{mod.ARCHIVE_SUFFIX}"
        future.write_text("from the windows box", encoding="utf-8")
        os.utime(future, (time.time() + 86400, time.time() + 86400))
        mod.prune_archives(dest, keep=1, protect=fresh,
                           known=[fresh.name, future.name])
        assert fresh.exists(), "the run deleted the archive it had just written"


class TestThreshold:
    def test_first_run_archives_with_no_manifest(self, source: Path, dest: Path) -> None:
        rc = _run("--source", str(source), "--dest", str(dest), "--now", "2026-01-01")
        assert rc.returncode == 0, rc.stdout + rc.stderr
        assert list(dest.glob("claude-transcripts-*.tgz"))

    def test_below_threshold_writes_nothing_and_exits_three(
        self, source: Path, dest: Path
    ) -> None:
        assert _run("--source", str(source), "--dest", str(dest),
                    "--now", "2026-01-01").returncode == 0
        before = {p.name for p in dest.glob("*.tgz")}
        second = _run("--source", str(source), "--dest", str(dest),
                      "--now", "2026-01-02", "--threshold-mb", "1")
        assert second.returncode == 3
        assert {p.name for p in dest.glob("*.tgz")} == before

    def test_check_reports_below_threshold_with_exit_three(
        self, source: Path, dest: Path
    ) -> None:
        """M15: --check's below-threshold code was pinned by nothing."""
        _run("--source", str(source), "--dest", str(dest), "--now", "2026-01-01")
        rc = _run("--source", str(source), "--dest", str(dest),
                  "--check", "--threshold-mb", "1")
        assert rc.returncode == 3

    def test_growth_past_threshold_archives_again(self, source: Path, dest: Path) -> None:
        _run("--source", str(source), "--dest", str(dest), "--now", "2026-01-01")
        (source / "proj-b" / "big.jsonl").write_text("z" * 3_000_000, encoding="utf-8")
        rc = _run("--source", str(source), "--dest", str(dest),
                  "--now", "2026-01-03", "--threshold-mb", "1")
        assert rc.returncode == 0, rc.stdout + rc.stderr

    def test_a_shrunken_source_archives_immediately_and_signals(
        self, source: Path, dest: Path
    ) -> None:
        """F4: negative growth previously spent itself on a silent exit 3."""
        (source / "proj-c" / "bulk.jsonl").write_text("q" * 2_000_000, encoding="utf-8")
        assert _run("--source", str(source), "--dest", str(dest),
                    "--now", "2026-01-01").returncode == 0
        (source / "proj-c" / "bulk.jsonl").unlink()
        rc = _run("--source", str(source), "--dest", str(dest),
                  "--now", "2026-01-02", "--json")
        assert rc.returncode == 4, rc.stdout
        assert (dest / "claude-transcripts-2026-01-02.tgz").exists()

    def test_a_manifest_from_another_source_is_not_used_as_a_baseline(
        self, source: Path, dest: Path, tmp_path: Path
    ) -> None:
        """F5: one run against a different tree latched this permanently quiet."""
        other = tmp_path / "other"
        (other / "p").mkdir(parents=True)
        (other / "p" / "big.jsonl").write_text("y" * 5_000_000, encoding="utf-8")
        _run("--source", str(other), "--dest", str(dest), "--now", "2026-01-01")
        rc = _run("--source", str(source), "--dest", str(dest),
                  "--now", "2026-01-02", "--json")
        assert rc.returncode == 0, rc.stdout
        assert json.loads(rc.stdout)["last_archived_bytes"] is None


class TestEndToEnd:
    def test_archive_round_trips_and_records_a_manifest(
        self, source: Path, dest: Path
    ) -> None:
        rc = _run("--source", str(source), "--dest", str(dest),
                  "--now", "2026-01-01", "--json")
        assert rc.returncode == 0, rc.stderr
        payload = json.loads(rc.stdout)
        assert payload["actual_members"] == payload["expected_members"] == _COUNT
        archive = Path(payload["archive"])
        with tarfile.open(archive, "r:gz") as tar:
            names = sorted(m.name for m in tar if m.isfile())
        assert len(names) == _COUNT
        manifest = json.loads((dest / ".archive_transcripts_manifest.json").read_text(encoding="utf-8"))
        assert manifest["files"] == _COUNT
        assert manifest["sha256"] == payload["sha256"]
        assert archive.name in manifest["known_archives"]

    def test_no_tmp_file_survives_a_successful_run(
        self, source: Path, dest: Path
    ) -> None:
        rc = _run("--source", str(source), "--dest", str(dest), "--now", "2026-01-01")
        assert rc.returncode == 0, "the run must succeed for this to mean anything"
        assert list(dest.glob("*.tmp")) == []

    def test_source_is_never_modified(self, source: Path, dest: Path) -> None:
        before = {str(p.relative_to(source)): p.read_bytes()
                  for p in source.rglob("*") if p.is_file()}
        _run("--source", str(source), "--dest", str(dest), "--now", "2026-01-01")
        after = {str(p.relative_to(source)): p.read_bytes()
                 for p in source.rglob("*") if p.is_file()}
        assert before == after

    def test_missing_source_is_an_error_not_a_silent_success(self, dest: Path) -> None:
        rc = _run("--source", str(dest / "nope"), "--dest", str(dest))
        assert rc.returncode == 1
        assert "not a directory" in rc.stderr

    def test_dest_with_a_missing_parent_is_refused(
        self, source: Path, tmp_path: Path
    ) -> None:
        """F10: parents=True fabricated an unmounted-volume path on the local disk."""
        rc = _run("--source", str(source),
                  "--dest", str(tmp_path / "Volumes" / "Backup" / "archives"))
        assert rc.returncode == 1
        assert not (tmp_path / "Volumes").exists()


class TestPlist:
    @pytest.mark.skipif(
        sys.platform != "darwin",
        reason="launchd plist is macOS-only -- the body hardcodes "
               "~/Library/Logs, so asserting it elsewhere proves nothing",
    )
    def test_print_plist_is_valid_and_carries_absolute_paths(self, source: Path) -> None:
        import plistlib
        rc = _run("--print-plist", "--source", str(source))
        assert rc.returncode == 0, rc.stderr
        parsed = plistlib.loads(rc.stdout.encode())
        assert parsed["Label"] == "com.espalier.archive-transcripts"
        args = parsed["ProgramArguments"]
        assert args[0].startswith("/") and args[1] == str(SCRIPT.resolve())
        # The options the job will run with are recorded, not implied.
        opts = dict(zip(args[2::2], args[3::2]))
        assert set(opts) == {"--source", "--dest", "--compression", "--keep", "--threshold-mb"}
        assert opts["--compression"] == "gz"
        assert opts["--source"].startswith("/") and opts["--dest"].startswith("/")
        assert parsed["RunAtLoad"] is False

    @pytest.mark.skipif(sys.platform != "darwin", reason="launchd plist is macOS-only")
    def test_print_plist_records_the_options_it_was_given(self, tmp_path: Path, source: Path) -> None:
        import plistlib
        rc = _run("--print-plist", "--source", str(source), "--dest", str(tmp_path),
                  "--compression", "xz", "--keep", "2")
        assert rc.returncode == 0, rc.stderr
        args = plistlib.loads(rc.stdout.encode())["ProgramArguments"]
        opts = dict(zip(args[2::2], args[3::2]))
        assert opts["--dest"] == str(tmp_path.resolve())
        assert opts["--compression"] == "xz" and opts["--keep"] == "2"

    def test_print_plist_refuses_a_source_that_does_not_exist(self, tmp_path: Path) -> None:
        rc = _run("--print-plist", "--source", str(tmp_path / "projcts"))
        assert rc.returncode == 1
        assert "not a directory" in rc.stderr and "every night" in rc.stderr
        assert rc.stdout == ""

    def test_print_plist_notes_a_dest_that_does_not_exist_yet(self, tmp_path: Path, source: Path) -> None:
        rc = _run("--print-plist", "--source", str(source), "--dest", str(tmp_path / "later"))
        assert rc.returncode == 0, rc.stderr
        assert "does not exist yet" in rc.stderr


class TestCompression:
    """``--compression xz`` is opt-in: gzip stays the default, the suffix names
    the codec, verification opens the codec it was told, and pruning treats both
    suffixes as one population (DEF-667: a destination with a quota)."""

    def test_gz_stays_the_default_suffix(self, source: Path, dest: Path) -> None:
        rc = _run("--source", str(source), "--dest", str(dest), "--now", "2026-01-01")
        assert rc.returncode == 0, rc.stderr
        assert (dest / "claude-transcripts-2026-01-01.tgz").exists()
        assert not list(dest.glob("*.txz"))

    def test_xz_archive_round_trips_verifies_and_is_recorded(self, source: Path, dest: Path) -> None:
        import json
        import tarfile
        rc = _run("--source", str(source), "--dest", str(dest), "--compression", "xz",
                  "--now", "2026-01-01", "--json")
        assert rc.returncode == 0, rc.stderr
        final = dest / "claude-transcripts-2026-01-01.txz"
        assert final.exists()
        with tarfile.open(final, "r:xz") as tar:
            assert sum(1 for m in tar if m.isfile()) == _COUNT
        payload = json.loads(rc.stdout)
        assert payload["actual_members"] == _COUNT == payload["expected_members"]
        manifest = json.loads((dest / ".archive_transcripts_manifest.json").read_text(encoding="utf-8"))
        assert manifest["archive"] == final.name
        assert final.name in manifest["known_archives"]

    def test_verify_opens_the_codec_it_was_told_not_whatever_it_finds(self, source: Path, dest: Path) -> None:
        mod = _load()
        files, _total, _errors = mod.snapshot_source(source)
        out = dest / "claude-transcripts-2026-01-01.txz"
        added, skipped = mod.build_archive(source, files, out, "projects", compression="xz")
        assert (added, skipped) == (_COUNT, [])
        ok, _report = mod.verify_archive(out, len(files), compression="xz")
        assert ok
        wrong, report = mod.verify_archive(out, len(files), compression="gz")
        assert not wrong and "error" in report

    def test_a_same_day_switch_of_codec_is_refused_without_force(self, source: Path, dest: Path) -> None:
        first = _run("--source", str(source), "--dest", str(dest), "--now", "2026-01-01")
        assert first.returncode == 0, first.stderr
        # --threshold-mb 0: the growth gate sits before the clash check, and
        # the source has not grown since the archive a moment ago.
        second = _run("--source", str(source), "--dest", str(dest), "--now", "2026-01-01",
                      "--compression", "xz", "--threshold-mb", "0")
        assert second.returncode == 1, second.stdout
        assert "already exists for 2026-01-01" in second.stdout
        assert not (dest / "claude-transcripts-2026-01-01.txz").exists()
        forced = _run("--source", str(source), "--dest", str(dest), "--now", "2026-01-01",
                      "--compression", "xz", "--threshold-mb", "0", "--force")
        assert forced.returncode == 0, forced.stderr
        assert (dest / "claude-transcripts-2026-01-01.txz").exists()

    def test_prune_counts_both_suffixes_as_one_population(self, dest: Path) -> None:
        import os
        mod = _load()
        old = dest / "claude-transcripts-2026-01-01.tgz"
        new = dest / "claude-transcripts-2026-01-02.txz"
        old.write_bytes(b"x")
        new.write_bytes(b"x")
        os.utime(old, (1_000_000, 1_000_000))
        os.utime(new, (2_000_000, 2_000_000))
        removed = mod.prune_archives(dest, keep=1, known=[old.name, new.name])
        assert removed == [old]
        assert new.exists()
