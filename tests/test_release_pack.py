"""Tests for ``espalier.release_pack.create_release_zip`` — the
zip-bundler that ``espalier release`` runs to produce the
distributable archive in ``dist/``.

Pins the bundler's exclusion contract: ``__pycache__`` directories,
``.git/``, and other dev-only paths must not land in the published
zip. Without this guard a release could silently ship adopter-
visible ``.pyc`` files or, worse, a snapshot of the source-repo
``.git`` history including unrelated branches and notes — both
exposures are hard to recall once the archive is mirrored.
"""
from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from espalier import release_pack, surface_contract
from espalier.release_pack import create_release_zip
from tests._git_oracle import GitAnswerUnavailable, require_tracked_paths

REPO_ROOT = Path(__file__).resolve().parent.parent


def _stage_tree(repo: Path) -> None:
    """Initialise (idempotent) and stage the whole tree, so the build below
    enumerates a git INDEX the way a release is built from one. No fixture in
    this module writes a .gitignore, so every seeded junk file is TRACKED junk --
    the shape the contract must still refuse on the index branch (an untracked
    file never reaches the builder at all; see TestArchiveIsTheGitIndex)."""
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    # `-f`: this machine's global git ignore excludes `**/.claude/settings.local.json`,
    # and any machine may exclude more; a fixture that lets the global excludes
    # decide what is tracked proves the contract on whatever survived them.
    # Junk must be TRACKED here, or the index never enumerates it.
    subprocess.run(["git", "-C", str(repo), "add", "-A", "-f"], check=True, capture_output=True)


def _build(repo: Path, out: Path):
    """Stage, then build: `create_release_zip` on the index branch."""
    _stage_tree(repo)
    return create_release_zip(repo, out)


class TestCreateReleaseZip:
    def test_creates_valid_zip(self, harness_repo):
        """create_release_zip produces a non-empty zip file."""
        out = harness_repo / "dist" / "release.zip"
        summary = _build(harness_repo, out)
        assert out.exists()
        assert out.stat().st_size > 0
        assert summary.files_written > 0

    def test_zip_is_openable(self, harness_repo):
        """The produced zip opens without error and has entries."""
        out = harness_repo / "dist" / "release.zip"
        _build(harness_repo, out)
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
        assert len(names) > 0

    def test_excludes_pycache(self, harness_repo):
        pycache = harness_repo / "__pycache__"
        pycache.mkdir()
        (pycache / "foo.pyc").write_bytes(b"PYC")
        out = harness_repo / "dist" / "release.zip"
        _build(harness_repo, out)
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
        assert not any("__pycache__" in n for n in names)

    def test_excludes_git_dir(self, harness_repo):
        git_dir = harness_repo / ".git"
        git_dir.mkdir(exist_ok=True)
        (git_dir / "config").write_text("[core]\n", encoding="utf-8")
        out = harness_repo / "dist" / "release.zip"
        _build(harness_repo, out)
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
        assert not any(".git" in n for n in names)

    def test_excludes_ds_store(self, harness_repo):
        (harness_repo / ".DS_Store").write_bytes(b"\x00")
        out = harness_repo / "dist" / "release.zip"
        _build(harness_repo, out)
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
        assert ".DS_Store" not in names

    def test_includes_source_files(self, harness_repo):
        out = harness_repo / "dist" / "release.zip"
        _build(harness_repo, out)
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
        assert any("app.py" in n for n in names)

    def test_does_not_include_self(self, harness_repo):
        out = harness_repo / "dist" / "release.zip"
        _build(harness_repo, out)
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
        assert not any("release.zip" in n for n in names)

    def test_summary_counts_match(self, harness_repo):
        out = harness_repo / "dist" / "release.zip"
        summary = _build(harness_repo, out)
        with zipfile.ZipFile(out, "r") as zf:
            actual_count = len(zf.namelist())
        assert summary.files_written == actual_count


class TestReleasePackMissingPath:
    """W10-1 (TP-177): `release-pack` on a non-existent repo path used to write
    an empty 22-byte zip and exit 0 (a successful-looking no-op release). It
    must now fail loudly without writing anything."""

    def test_missing_repo_path_exits_nonzero_and_writes_nothing(self, tmp_path):
        import argparse
        from espalier.cli import cmd_release_pack
        missing = tmp_path / "does-not-exist"
        out = tmp_path / "out.zip"
        args = argparse.Namespace(repo=str(missing), output=str(out))
        rc = cmd_release_pack(args)
        assert rc != 0, "release-pack must not exit 0 on a missing repo path"
        assert not out.exists(), "no zip should be written for a missing repo path"


class TestPack3InternalLeakExclusion:
    """Pack 3-A — contract-driven internal exclusions."""

    def _bare_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "README.md").write_text("# Repo\n", encoding="utf-8")
        (tmp_path / "LICENSE").write_text("MIT\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "t"\n', encoding="utf-8")
        (tmp_path / "espalier").mkdir()
        (tmp_path / "espalier" / "foo.py").write_text("x = 1\n", encoding="utf-8")
        return tmp_path

    def _names(self, zip_path: Path) -> list[str]:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return zf.namelist()

    def test_excludes_docs_internal_tree(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        (repo / "docs" / "internal").mkdir(parents=True)
        (repo / "docs" / "internal" / "secret.md").write_text("private\n", encoding="utf-8")
        out = repo / "dist" / "release.zip"
        summary = _build(repo, out)
        names = self._names(out)
        assert not any("docs/internal" in n for n in names)
        assert any("docs/internal/secret.md" in p for p in summary.skipped_internal)

    def test_excludes_session_archive(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        (repo / "docs").mkdir(exist_ok=True)
        (repo / "docs" / "session-archive.md").write_text("history\n", encoding="utf-8")
        out = repo / "dist" / "release.zip"
        summary = _build(repo, out)
        names = self._names(out)
        assert "docs/session-archive.md" not in names
        assert "docs/session-archive.md" in summary.skipped_internal

    def test_excludes_task_pack_root_docs(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        (repo / "TASK_PACK_FOO.md").write_text("internal\n", encoding="utf-8")
        out = repo / "dist" / "release.zip"
        summary = _build(repo, out)
        names = self._names(out)
        assert "TASK_PACK_FOO.md" not in names
        assert "TASK_PACK_FOO.md" in summary.skipped_internal

    def test_excludes_blueprint_root_docs(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        (repo / "BLUEPRINT_ESPALIER_MEMORY.md").write_text("internal\n", encoding="utf-8")
        out = repo / "dist" / "release.zip"
        summary = _build(repo, out)
        names = self._names(out)
        assert "BLUEPRINT_ESPALIER_MEMORY.md" not in names
        assert "BLUEPRINT_ESPALIER_MEMORY.md" in summary.skipped_internal

    def test_excludes_export_ignored_memory_md(self, tmp_path):
        """TP-174b T10: ESPALIER_MEMORY.md classifies `public` (a shipped managed
        surface) but is marked export-ignore in .gitattributes. git archive
        excludes it; the builder enumerates the index, not `git archive`, so it must honor
        export-ignore explicitly or ESPALIER_MEMORY.md leaks into the release zip."""
        repo = self._bare_repo(tmp_path)
        (repo / "ESPALIER_MEMORY.md").write_text("internal session log\n", encoding="utf-8")
        (repo / ".gitattributes").write_text("ESPALIER_MEMORY.md export-ignore\n", encoding="utf-8")
        out = repo / "dist" / "release.zip"
        summary = _build(repo, out)
        names = self._names(out)
        assert "ESPALIER_MEMORY.md" not in names
        assert "ESPALIER_MEMORY.md" in summary.skipped_internal

    def test_ships_memory_md_when_not_export_ignored(self, tmp_path):
        """Negative: the skip is driven by .gitattributes export-ignore, not a
        hardcoded ESPALIER_MEMORY.md exclusion — a repo that does NOT export-ignore it
        still ships it (ESPALIER_MEMORY.md classifies public)."""
        repo = self._bare_repo(tmp_path)
        (repo / "ESPALIER_MEMORY.md").write_text("public memory\n", encoding="utf-8")
        out = repo / "dist" / "release.zip"
        _build(repo, out)
        assert "ESPALIER_MEMORY.md" in self._names(out)

    def test_excludes_local_only_settings(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        (repo / ".claude").mkdir()
        (repo / ".claude" / "settings.local.json").write_text("{}\n", encoding="utf-8")
        (repo / ".claude" / "settings.json").write_text('{"hooks": {}}\n', encoding="utf-8")
        out = repo / "dist" / "release.zip"
        summary = _build(repo, out)
        names = self._names(out)
        assert ".claude/settings.local.json" not in names
        # settings.json is local-only because it records a machine-detected
        # interpreter name; it must not ship in public releases.
        assert ".claude/settings.json" in summary.skipped_transient or \
               ".claude/settings.json" in summary.skipped_local_only or \
               ".claude/settings.json" not in names

    def test_excludes_ephemeral_reports(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        (repo / "reports").mkdir()
        (repo / "reports" / "analysis.json").write_text("{}\n", encoding="utf-8")
        (repo / "reports" / "cc_surface_gate.json").write_text("{}\n", encoding="utf-8")
        out = repo / "dist" / "release.zip"
        summary = _build(repo, out)
        names = self._names(out)
        assert "reports/analysis.json" not in names
        assert "reports/cc_surface_gate.json" not in names

    def test_excludes_espalier_state(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        state = repo / ".espalier-state"
        state.mkdir()
        (state / "session.json").write_text("{}\n", encoding="utf-8")
        out = repo / "dist" / "release.zip"
        summary = _build(repo, out)
        names = self._names(out)
        assert not any(".espalier-state" in n for n in names)

    def test_excludes_all_snapshot_junk(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        junk_dirs = ["__MACOSX", "build", "foo.egg-info", ".pytest_cache"]
        for d in junk_dirs:
            (repo / d).mkdir()
            (repo / d / "x").write_text("junk", encoding="utf-8")
        (repo / ".DS_Store").write_text("", encoding="utf-8")
        out = repo / "dist" / "release.zip"
        summary = _build(repo, out)
        names = self._names(out)
        # Check each directory by its exact path prefix (not substring — "build"
        # is a substring of "espalier/" which ships publicly).
        for d in junk_dirs:
            leaks = [n for n in names if n.startswith(f"{d}/") or n == d]
            assert not leaks, f"{d!r} leaked into zip: {leaks}"
        assert ".DS_Store" not in names

    def test_includes_public_files(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        out = repo / "dist" / "release.zip"
        _build(repo, out)
        names = self._names(out)
        assert "README.md" in names
        assert "LICENSE" in names
        assert "pyproject.toml" in names
        assert "espalier/foo.py" in names

    def test_skipped_entries_surfaced_by_bucket(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        (repo / "docs" / "internal").mkdir(parents=True)
        (repo / "docs" / "internal" / "secret.md").write_text("p\n", encoding="utf-8")
        (repo / "__pycache__").mkdir()
        (repo / "__pycache__" / "x.pyc").write_bytes(b"x")
        out = repo / "dist" / "release.zip"
        summary = _build(repo, out)
        assert summary.skipped_internal  # bucketed
        assert summary.skipped_transient

    def test_excludes_execution_plan_json(self, tmp_path):
        """cc/execution_plan.json is runtime state and must never ship."""
        repo = self._bare_repo(tmp_path)
        (repo / "cc").mkdir(exist_ok=True)
        (repo / "cc" / "execution_plan.json").write_text('{"status": "complete"}\n', encoding="utf-8")
        out = repo / "dist" / "release.zip"
        summary = _build(repo, out)
        names = self._names(out)
        assert "cc/execution_plan.json" not in names

    def test_excludes_blueprint_handoff(self, tmp_path):
        """cc/BLUEPRINT_HANDOFF.md is an internal session file and must never ship."""
        repo = self._bare_repo(tmp_path)
        (repo / "cc").mkdir(exist_ok=True)
        (repo / "cc" / "BLUEPRINT_HANDOFF.md").write_text("internal\n", encoding="utf-8")
        out = repo / "dist" / "release.zip"
        _build(repo, out)
        names = self._names(out)
        assert "cc/BLUEPRINT_HANDOFF.md" not in names


class TestReleaseDenylistRegression:
    """Consolidated regression: a real zip must never contain any denylisted path."""

    _DENY = [
        ".git/",
        ".DS_Store",
        "__MACOSX/",
        "__pycache__/",
        ".pytest_cache/",
        ".espalier-state/",
        ".claude/settings.local.json",
        "cc/execution_plan.json",
        "cc/BLUEPRINT_HANDOFF.md",
        "docs/session-archive.md",
        "build/",
        ".egg-info/",
    ]

    def _names(self, out):
        import zipfile
        with zipfile.ZipFile(out, "r") as zf:
            return zf.namelist()

    def _bare_repo(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "README.md").write_text("# Test\n", encoding="utf-8")
        (repo / "LICENSE").write_text("MIT\n", encoding="utf-8")
        (repo / "pyproject.toml").write_text('[project]\nname="test"\n', encoding="utf-8")
        (repo / "espalier").mkdir()
        (repo / "espalier" / "foo.py").write_text("x = 1\n", encoding="utf-8")
        return repo

    def test_no_denylisted_path_in_release_zip(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        # Seed every denylisted type
        (repo / ".git").mkdir()
        (repo / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        (repo / ".DS_Store").write_bytes(b"\x00")
        (repo / "__MACOSX").mkdir()
        (repo / "__MACOSX" / "._file").write_bytes(b"\x00")
        (repo / "__pycache__").mkdir()
        (repo / "__pycache__" / "x.pyc").write_bytes(b"PYC")
        (repo / ".pytest_cache").mkdir()
        (repo / ".pytest_cache" / "v").mkdir()
        (repo / ".espalier-state").mkdir()
        (repo / ".espalier-state" / "flag").write_text("x", encoding="utf-8")
        (repo / ".claude").mkdir()
        (repo / ".claude" / "settings.local.json").write_text("{}", encoding="utf-8")
        (repo / "cc").mkdir()
        (repo / "cc" / "execution_plan.json").write_text("{}", encoding="utf-8")
        (repo / "cc" / "BLUEPRINT_HANDOFF.md").write_text("internal", encoding="utf-8")
        (repo / "docs").mkdir()
        (repo / "docs" / "session-archive.md").write_text("history", encoding="utf-8")
        (repo / "build").mkdir()
        (repo / "build" / "lib").mkdir()
        (repo / "build" / "lib" / "x.py").write_text("x", encoding="utf-8")
        (repo / "foo.egg-info").mkdir()
        (repo / "foo.egg-info" / "PKG-INFO").write_text("x", encoding="utf-8")

        out = repo / "dist" / "release.zip"
        _build(repo, out)
        names = self._names(out)

        leaks = []
        for marker in self._DENY:
            if marker.endswith("/"):
                prefix = marker
                bad = [n for n in names if n.startswith(prefix) or n + "/" == prefix]
            else:
                bad = [n for n in names if n == marker or n.endswith("/" + marker)]
            if bad:
                leaks.append(f"{marker!r}: {bad}")

        assert not leaks, "Denylisted paths leaked into release zip:\n" + "\n".join(leaks)


class TestCreateReleaseZipAtomicity:
    """R10 B3 (R11 coverage): ``create_release_zip`` writes to a tempfile
    sibling then ``os.replace`` onto the destination. A failure during
    the build must NOT destroy a pre-existing valid ZIP at the
    destination. Pre-fix, ``ZipFile(output_zip, "w")`` truncated
    immediately and any OSError left a partial / corrupt ZIP.
    """

    def test_preexisting_zip_preserved_on_oserror_during_replace(
        self, harness_repo, monkeypatch, tmp_path,
    ):
        from espalier import release_pack as release_pack_module
        dest = tmp_path / "dist" / "espalier-harness.zip"
        dest.parent.mkdir(parents=True, exist_ok=True)
        original_content = b"PRE-EXISTING-ZIP-DO-NOT-DESTROY"
        dest.write_bytes(original_content)

        def boom(src, dst, *args, **kwargs):
            raise OSError(13, "simulated replace failure")

        monkeypatch.setattr(release_pack_module.os, "replace", boom)
        with pytest.raises(OSError):
            _build(harness_repo, dest)

        # Pre-existing ZIP must be untouched.
        assert dest.read_bytes() == original_content, (
            "create_release_zip destroyed a pre-existing ZIP on partial failure"
        )
        # Temp file must be cleaned up.
        leftover = list(dest.parent.glob(f".{dest.name}.*"))
        assert leftover == [], f"tempfile leaked on partial failure: {leftover}"

    def test_no_temp_left_on_success(self, harness_repo, tmp_path):
        """Sanity: a normal successful run leaves zero tempfiles."""
        dest = tmp_path / "dist" / "espalier-harness.zip"
        _build(harness_repo, dest)
        assert dest.exists()
        leftover = list(dest.parent.glob(f".{dest.name}.*"))
        assert leftover == [], f"tempfile leaked on success: {leftover}"


class TestWalkPruning:
    """The walker must not ENUMERATE trees it can never ship from.

    Every path pruned here would be rejected anyway by
    ``is_transient``/``is_public_release_allowed`` -- the cost was never a
    wrong ZIP, it was one report STRING per file. On a measured run the
    repo's own ``.git`` contributed 5,455 of 10,004 skipped entries (54.5%),
    and a leftover release-matrix workspace had previously contributed 8,862
    more. The report grew with the staleness of local scratch.

    The payload assertions below are the load-bearing half: they must hold
    IDENTICALLY before and after the prune, which is what proves the change
    touched reporting only.

    These pins are about the REPORT of the tree-walk FALLBACK, on purpose:
    ``_seeded_repo`` plants a ``.git`` that is not a repository, so
    ``tracked_paths`` returns None (with its WARN) and the walk runs. On the
    index branch nothing pruned is ever a candidate, so the prune has no
    report to keep small there.
    """

    # Exactly the files a correct run ships from ``_seeded_repo``. Pinned as a
    # literal set, not derived, so a prune that ate a shippable file fails here
    # rather than silently shrinking both sides of a computed comparison.
    EXPECTED_PAYLOAD = {
        "README.md",
        "LICENSE",
        "pyproject.toml",
        "espalier/foo.py",
        # tools/ is shipped surface -- it carries the whole hook layer, which is
        # the harness's mechanical enforcement. Seeded here deliberately: a
        # one-line `parts[0] == "tools"` arm in _is_pruned_from_walk drops 47
        # files from the real release archive, and before this entry existed the
        # entire suite stayed green at 7,051 passed. A prune predicate is only
        # as safe as the breadth of the payload it is pinned against.
        "tools/cc/hooks/x.py",
        # A FILE named `venv` (not a directory) is public-release allowed. The
        # prune must match venv as a DIRECTORY component only -- matching the
        # basename would drop this from the payload AND the report, leaving no
        # trace anywhere.
        "scripts/venv",
    }

    def _seeded_repo(self, tmp_path: Path) -> Path:
        # Shippable surface.
        (tmp_path / "README.md").write_text("# Repo\n", encoding="utf-8")
        (tmp_path / "LICENSE").write_text("MIT\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "t"\n', encoding="utf-8")
        (tmp_path / "espalier").mkdir()
        (tmp_path / "espalier" / "foo.py").write_text("x = 1\n", encoding="utf-8")
        hooks = tmp_path / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "x.py").write_text("x = 3\n", encoding="utf-8")
        scripts = tmp_path / "scripts"
        scripts.mkdir(exist_ok=True)
        (scripts / "venv").write_text("#!/bin/sh\n# a wrapper script, not a venv\n", encoding="utf-8")

        # The three trees the prune targets.
        objects = tmp_path / ".git" / "objects" / "ab"
        objects.mkdir(parents=True)
        (objects / "cdef123").write_bytes(b"\x00git-object")
        (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

        venv_bin = tmp_path / "tooling" / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").write_text("#!/bin/sh\n", encoding="utf-8")

        dot_venv = tmp_path / ".venv" / "lib"
        dot_venv.mkdir(parents=True)
        (dot_venv / "site.py").write_text("x = 2\n", encoding="utf-8")

        matrix = tmp_path / "dist" / "final-release-matrix" / "sdist_work"
        matrix.mkdir(parents=True)
        (matrix / "build.log").write_text("log\n", encoding="utf-8")
        return tmp_path

    def _run(self, repo: Path):
        out = repo / "dist" / "release.zip"
        summary = create_release_zip(repo, out)
        with zipfile.ZipFile(out, "r") as zf:
            return summary, set(zf.namelist())

    def test_pruned_trees_absent_from_skipped_entries(self, tmp_path):
        """Earns its red at HEAD: every path below IS enumerated today."""
        summary, _ = self._run(self._seeded_repo(tmp_path))
        offenders = [
            rel
            for rel in summary.skipped_entries
            if rel.split("/")[0] == ".git"
            or "venv" in rel.split("/")
            or ".venv" in rel.split("/")
            or rel.startswith("dist/final-release-matrix/")
        ]
        assert offenders == [], (
            f"walker still enumerates {len(offenders)} un-shippable paths: "
            f"{offenders[:8]}"
        )

    def test_prune_leaves_the_payload_untouched(self, tmp_path):
        """Criterion 5. Passes BEFORE and AFTER the prune -- that is the point.

        A prune that removed something shippable would red here while the
        enumeration test above went green, which is the failure mode worth
        catching: report size is never worth a byte of payload.
        """
        _, members = self._run(self._seeded_repo(tmp_path))
        assert members == self.EXPECTED_PAYLOAD, (
            f"payload moved: missing={sorted(self.EXPECTED_PAYLOAD - members)} "
            f"unexpected={sorted(members - self.EXPECTED_PAYLOAD)}"
        )

    def test_dist_artifacts_are_still_reported(self, tmp_path):
        """Fallback-branch pin: on the index an untracked wheel is never a
        candidate, so it is neither shipped nor reported."""
        """The prune is surgical: only the matrix SUBTREE, never ``dist/``.

        Genuine release artifacts sitting directly in ``dist/`` are exactly
        what an operator wants to see reported. Pruning ``dist/`` wholesale
        would silence them -- so this pins the boundary the predicate walks.
        """
        repo = self._seeded_repo(tmp_path)
        (repo / "dist").mkdir(exist_ok=True)
        (repo / "dist" / "espalier_harness-9.9.9-py3-none-any.whl").write_bytes(b"whl")
        summary, _ = self._run(repo)
        assert "dist/espalier_harness-9.9.9-py3-none-any.whl" in summary.skipped_entries, (
            "a real release artifact in dist/ must still be reported; only "
            "dist/final-release-matrix/ is pruned"
        )

    def test_pruned_paths_are_never_shippable(self):
        """The predicate's entire safety argument, written as an assertion.

        ``_is_pruned_from_walk`` runs BEFORE classification, so anything it
        matches is invisible to ``surface_contract`` -- it is a second
        exclusion authority, and the release archive already has one. That is
        only safe while every pruned path would have been rejected anyway.
        Nothing checked that claim; the docstring simply asserted it, which is
        this repo's "claim with no oracle" shape sitting inside the gate that
        guards the release artifact.

        Unlike the other tests here this needs no tree -- it is a property of
        the predicate, so it costs nothing and covers paths no fixture would
        think to seed.
        """
        must_be_pruned = (
            ".git/HEAD",
            ".git/objects/ab/cdef",
            "tooling/venv/bin/python",
            ".venv/lib/site.py",
            "dist/final-release-matrix/sdist_work/build.log",
        )
        must_not_be_pruned = (
            ".gitignore",
            ".gitattributes",
            "scripts/venv",           # a FILE named venv -- ships
            "docs/.venv",             # ditto
            "dist/espalier-harness.zip",  # a real artifact -- must stay reported
            "tools/cc/hooks/write_guard.py",
        )
        for rel in must_be_pruned:
            assert release_pack._is_pruned_from_walk(rel), f"{rel} should prune"
        for rel in must_not_be_pruned:
            assert not release_pack._is_pruned_from_walk(rel), (
                f"{rel} must NOT be pruned"
            )

        # The invariant itself: pruned => the contract would have rejected it.
        # If this ever fails, the prune has started removing payload while
        # wearing a report-only label, and nothing downstream would notice.
        for rel in must_be_pruned:
            assert surface_contract.is_transient(
                rel
            ) or not surface_contract.is_public_release_allowed(rel), (
                f"{rel} is pruned but the contract says it SHIPS -- the prune "
                "is acting as a second exclusion authority, not a report filter"
            )

    def test_no_tracked_shippable_path_is_pruned(self):
        """The invariant against the REAL population, not a sample list.

        A hand-picked fixture can only catch a widening over a prefix someone
        thought to seed. Measured: with samples alone, widening the predicate
        over ``tools/``, ``scripts/`` or ``espalier/`` reds, but ``bench/`` --
        81 shipped files -- slipped through, because no sample lived there.
        Enumerating prefixes by hand is the same class of gap one level up.

        This walks every tracked file instead, so any future arm that prunes
        something the contract ships reds immediately regardless of where it
        lives. O(tracked files), no fixture, nothing to keep in sync.
        """
        # §C21/`DEF-572`: the two empty cases were once handled ASYMMETRICALLY
        # -- rc 128 skipped, rc-0-with-zero-rows fell through to the floor and
        # reddened. Measured 2026-08-14 on one archive at two locations: outside
        # a worktree it skipped silently (so the contract went unverified in the
        # environment a consumer actually has), under this repo's `dist/` the
        # floor fired as a FALSE failure. Neither answer was about this tree.
        #
        # The first repair hand-rolled `if rc != 0 or not tracked: skip` HERE,
        # in the same commit that built `tests/_git_oracle.py` -- which is the
        # §C21 recurrence in miniature: the rule ("route every site through the
        # helper") stayed prose while the code went its own way, and the
        # hand-rolled form was strictly weaker, unable to see a NON-EMPTY
        # foreign answer from a tracked subdirectory of another worktree.
        # Routed properly now; the skip is this caller's disposition, chosen
        # explicitly, which is what the helper's contract asks for.
        try:
            tracked = require_tracked_paths(
                REPO_ROOT, minimum=500, what="tracked files"
            )
        except GitAnswerUnavailable as exc:  # pragma: no cover - not a git checkout
            pytest.skip(f"tracked-set population unavailable: {exc}")
        offenders = [
            rel
            for rel in tracked
            if release_pack._is_pruned_from_walk(rel)
            and surface_contract.is_public_release_allowed(rel)
            and not surface_contract.is_transient(rel)
        ]
        assert offenders == [], (
            f"{len(offenders)} tracked file(s) are pruned from the walk but the "
            f"contract says they SHIP: {offenders[:10]} -- the prune has become "
            "a second exclusion authority and is silently removing payload"
        )

    def test_a_file_named_venv_still_ships(self, tmp_path):
        """``venv`` matches directory components only, per is_transient.

        ``surface_contract.is_transient`` deliberately tests ``parts[:-1]`` for
        directory-style patterns. Matching the basename too would silently drop
        a public file named ``venv`` from both the archive and the report.
        """
        repo = self._seeded_repo(tmp_path)
        summary, members = self._run(repo)
        assert "scripts/venv" in members, (
            "a FILE named venv was dropped from the payload -- the prune is "
            "matching the basename instead of the directory components"
        )
        assert summary.files_written == len(self.EXPECTED_PAYLOAD)

    def test_gitignore_and_gitattributes_are_not_eaten_by_the_git_prune(
        self, tmp_path
    ):
        """``.gitignore``/``.gitattributes`` are FILES at the repo root.

        The predicate tests ``parts[0] == ".git"`` for the directory. A
        ``startswith(".git")`` spelling would swallow both of these tracked,
        shippable files -- and neither would appear in the payload OR the
        report, which is the silent shape.
        """
        repo = self._seeded_repo(tmp_path)
        (repo / ".gitignore").write_text("dist/\n", encoding="utf-8")
        (repo / ".gitattributes").write_text("*.md text\n", encoding="utf-8")
        summary, members = self._run(repo)
        seen = set(summary.skipped_entries) | members
        for rel in (".gitignore", ".gitattributes"):
            assert rel in seen, (
                f"{rel} vanished from BOTH the zip and the report -- the "
                "'.git' prune is matching by prefix instead of by path component"
            )

    def test_a_worktree_gitlink_file_is_pruned_and_never_ships(self, tmp_path):
        """§C13 (DEF-417f), the tree-walk fallback: a `git worktree` checkout has
        a `.git` FILE at its root holding a local absolute gitdir path. The prune
        takes a root `.git` of either kind now that the contract rejects both
        (``test_pruned_paths_are_never_shippable`` is what keeps the prune
        report-only). A gitlink whose gitdir does not resolve is a root git
        cannot answer for, so this exercises the walk, not the index."""
        repo = self._seeded_repo(tmp_path)
        shutil.rmtree(repo / ".git")
        (repo / ".git").write_text(
            "gitdir: /Users/someone/src/main/.git/worktrees/wt\n", encoding="utf-8"
        )
        assert release_pack._is_pruned_from_walk(".git")
        assert not release_pack._is_pruned_from_walk(".gitignore")
        summary, members = self._run(repo)
        assert ".git" not in members, "the worktree's gitlink file shipped"
        assert ".git" not in summary.skipped_entries
        assert members == self.EXPECTED_PAYLOAD


class TestGitignoredLocalStateNeverShips:
    """§C3: the dev tree is not the artifact.

    The builder enumerates the git index rather than `git archive` because
    `ESPALIER_MEMORY.md` is export-ignored by `.gitattributes` yet IS a shipped
    managed surface, so an archive-driven enumeration would wrongly drop it.
    Before the index was the enumeration, the tree walk let gitignored LOCAL
    state straight into the ZIP. The live instance: `cc/discard_snapshots.log`,
    written by the speed-bump hook, carrying the operator's home directory and
    recorded shell commands. It failed the release matrix's source-archive
    stage — the artifact was contaminated by whatever happened to be lying in
    the maintainer's working tree.

    Note the asymmetry this pins: gitIGNORED (untracked local junk) must not
    ship; export-ignored-but-tracked must still ship. The fixtures stage the
    tree the way a release is built from one: a gitignored file is never
    staged, so it is never in the index.
    """

    def _git_init(self, repo: Path) -> None:
        """A release archive is built FROM a git repo; the index needs one."""
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)

    def _stage_all(self, repo: Path) -> None:
        """`git add -A` honours the .gitignore the scratch helper wrote."""
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)

    def _ignored_scratch(self, repo: Path, rel: str, body: str) -> Path:
        gitignore = repo / ".gitignore"
        prior = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        gitignore.write_text(f"{prior}\n{rel}\n", encoding="utf-8")
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return target

    def test_gitignored_log_does_not_reach_the_zip(self, harness_repo):
        """Earn-the-red: pre-fix this shipped, home directory and all."""
        self._git_init(harness_repo)
        self._ignored_scratch(
            harness_repo, "cc/discard_snapshots.log",
            "2026-08-08\tabc123\tcd /Users/someone/Desktop/Repo && git checkout HEAD -- x\n",
        )
        self._stage_all(harness_repo)
        out = harness_repo / "dist" / "release.zip"
        create_release_zip(harness_repo, out)
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
        assert not any(n.endswith("discard_snapshots.log") for n in names), (
            "gitignored local scratch reached the release ZIP"
        )

    def test_gitignored_file_of_any_extension_does_not_ship(self, harness_repo):
        """The class is 'gitignored local state', not 'files named *.log'."""
        self._git_init(harness_repo)
        self._ignored_scratch(harness_repo, "cc/local_notes.txt", "/Users/someone/secrets\n")
        self._stage_all(harness_repo)
        out = harness_repo / "dist" / "release.zip"
        create_release_zip(harness_repo, out)
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
        assert not any(n.endswith("local_notes.txt") for n in names)

    def test_non_git_tree_warns_rather_than_silently_shipping(self, harness_repo, capsys):
        """No git means no INDEX: the archive is the working tree filtered by
        the patterns alone, and every untracked public file in it ships. That
        is said out loud rather than assumed away -- and `pre-release` and
        `release_check` refuse a tree-enumerated build on a root that owns its
        `.git`, because that shape is git failing, not a plain directory."""
        out = harness_repo / "dist" / "release.zip"
        create_release_zip(harness_repo, out)
        err = capsys.readouterr().err
        assert "surface_contract:" in err and "release-noise patterns" in err, (
            f"a tree with no git repo must warn that the ignore set is "
            f"unavailable; stderr was {err!r}"
        )

    def test_tracked_source_still_ships(self, harness_repo):
        """Control: the exclusion must not swallow real content."""
        out = harness_repo / "dist" / "release.zip"
        summary = create_release_zip(harness_repo, out)
        assert summary.files_written > 0
        with zipfile.ZipFile(out, "r") as zf:
            assert zf.namelist()


class TestArchiveIsTheGitIndex:
    """§C13 (DEF-417g): the release archive is the git index, classified.

    The tree walk shipped whatever lay in the checkout; the ignore-set filter
    narrowed that to whatever lay there and was NOT gitignored -- an untracked
    public file still shipped (driven 2026-09-08: `stray_public.py` was in the
    archive built from a worktree checkout). The index closes it structurally:
    a file git does not track never enters the archive, whatever it classifies
    as. Tracked files still go through the contract, so a tracked internal
    file and a tracked export-ignored file stay out.
    """

    def _git(self, repo: Path, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t.com", *args],
            check=True, capture_output=True,
        )

    def _repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "README.md").write_text("# r\n", encoding="utf-8")
        (repo / "espalier").mkdir()
        (repo / "espalier" / "foo.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "docs" / "internal").mkdir(parents=True)
        (repo / "docs" / "internal" / "notes.md").write_text("private\n", encoding="utf-8")
        (repo / "ESPALIER_MEMORY.md").write_text("session log\n", encoding="utf-8")
        (repo / ".gitattributes").write_text("ESPALIER_MEMORY.md export-ignore\n", encoding="utf-8")
        self._git(repo, "init", "-q")
        self._git(repo, "add", "-A")
        return repo

    def _members(self, repo: Path) -> set[str]:
        out = repo / "dist" / "release.zip"
        create_release_zip(repo, out)
        with zipfile.ZipFile(out) as zf:
            return set(zf.namelist())

    def test_untracked_public_file_never_ships(self, tmp_path):
        """Earn-the-red: this file was in the archive while the enumeration was
        the working tree filtered by the ignore set."""
        repo = self._repo(tmp_path)
        (repo / "espalier" / "stray_public.py").write_text("y = 2\n", encoding="utf-8")
        assert surface_contract.is_public_release_allowed("espalier/stray_public.py")
        members = self._members(repo)
        assert "espalier/stray_public.py" not in members, "an untracked public file shipped"
        assert "espalier/foo.py" in members  # control: a tracked public file ships

    def test_members_equal_the_tracked_public_set_both_ways(self, tmp_path):
        """Presence AND absence: nothing untracked ships, every tracked public
        file ships, and a tracked file still goes through the contract."""
        repo = self._repo(tmp_path)
        (repo / "untracked.md").write_text("stray\n", encoding="utf-8")
        members = self._members(repo)
        tracked = surface_contract.tracked_paths(repo)
        assert tracked is not None and "README.md" in tracked
        expected = {
            rel for rel in tracked
            if surface_contract.is_public_release_allowed(rel)
            and rel != "ESPALIER_MEMORY.md"  # tracked, public, export-ignored
        }
        assert members == expected
        assert "docs/internal/notes.md" in tracked
        assert "docs/internal/notes.md" not in members
        assert "ESPALIER_MEMORY.md" in tracked
        assert "ESPALIER_MEMORY.md" not in members

    def test_worktree_checkout_builds_from_its_own_index(self, tmp_path):
        """The class oracle from the ledger preamble: a `git worktree` checkout,
        where `.git` is a FILE holding an absolute gitdir path. Its index is the
        branch's tree; the gitlink file and an untracked public file are not in
        it, and neither ships."""
        repo = self._repo(tmp_path)
        self._git(repo, "commit", "-q", "-m", "init")
        wt = tmp_path / "wt"
        self._git(repo, "worktree", "add", "--quiet", str(wt), "-b", "wt")
        assert (wt / ".git").is_file()
        (wt / "stray_public.py").write_text("z = 3\n", encoding="utf-8")
        members = self._members(wt)
        assert "README.md" in members
        assert ".git" not in members, "the worktree's gitlink file shipped"
        assert "stray_public.py" not in members

    def test_index_entry_missing_from_the_worktree_is_skipped(self, tmp_path):
        """A path in the index but deleted from the checkout is neither a crash
        nor a member."""
        repo = self._repo(tmp_path)
        (repo / "espalier" / "foo.py").unlink()
        members = self._members(repo)
        assert "espalier/foo.py" not in members
        assert "README.md" in members

    def test_nested_repos_never_reach_the_index_branch(self, tmp_path):
        """A plain nested clone is untracked, and a submodule is a gitlink entry
        (mode 160000) that `is_file()` rejects; neither ships."""
        repo = self._repo(tmp_path)
        nested = repo / "vendor" / "clone"
        nested.mkdir(parents=True)
        self._git(nested, "init", "-q")
        (nested / "lib.py").write_text("v = 1\n", encoding="utf-8")
        gitlink = repo / "vendor" / "sub"
        gitlink.mkdir()
        (gitlink / "sub.py").write_text("s = 1\n", encoding="utf-8")
        self._git(
            repo, "update-index", "--add", "--cacheinfo",
            "160000,0123456789abcdef0123456789abcdef01234567,vendor/sub",
        )
        tracked = surface_contract.tracked_paths(repo)
        assert tracked is not None and "vendor/sub" in tracked
        members = self._members(repo)
        assert not any(m.startswith("vendor/") for m in members), sorted(members)

    def test_the_live_tree_answers_from_its_index(self):
        """The gate the WARN is not: on this checkout the index must answer,
        or every release built here is silently the tree walk (git absent
        from PATH, dubious ownership, a moved gitdir). The floor matches the
        `> 500` idiom in TestWalkPruning."""
        tracked = surface_contract.tracked_paths(REPO_ROOT)
        assert tracked is not None, "git could not answer for the live checkout"
        assert len(tracked) > 500, f"implausible index size {len(tracked)}"
        assert "pyproject.toml" in tracked

    def test_no_index_falls_back_to_the_tree_walk_quietly(self, tmp_path, capsys):
        """A root with no repository has no notion of "untracked": the
        working-tree walk is the whole truth there, so it is not a degraded
        build and nothing is said (the release matrix builds inside one). The
        loud shape is a root that OWNS a `.git` git cannot answer for --
        `test_non_git_tree_warns_rather_than_silently_shipping` -- and that
        one the gates refuse."""
        root = tmp_path / "plain"
        root.mkdir()
        (root / "README.md").write_text("# r\n", encoding="utf-8")
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "x.pyc").write_bytes(b"x")
        out = root / "dist" / "release.zip"
        create_release_zip(root, out)
        with zipfile.ZipFile(out) as zf:
            members = set(zf.namelist())
        assert members == {"README.md"}
        assert "no git index" not in capsys.readouterr().err

    def test_the_summary_says_which_enumeration_answered(self, tmp_path):
        repo = self._repo(tmp_path)
        assert create_release_zip(repo, repo / "dist" / "a.zip").enumeration == "index"
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "README.md").write_text("# r\n", encoding="utf-8")
        summary = create_release_zip(plain, plain / "dist" / "b.zip")
        assert summary.enumeration == "tree"
        assert summary.to_dict()["enumeration"] == "tree"


class TestBothArchiveBuildersEnumerateTheIndex:
    """§C3 / §C13 sister site. The repo has TWO archive builders and the leak was in both.

    `espalier/release_pack.py` backs `espalier release-pack`; the release
    matrix's source-archive stage builds with `scripts/build_release_archive.py`
    instead. Fixing only the first left the gate red on the identical defect —
    which is Core Rule 12 in the wild: the unit of work was the class, not the
    site. Both call one helper, `surface_contract.tracked_paths`, rather than
    carrying the subprocess twice; this pins both call sites so a future edit
    cannot quietly drop one. The ignore-set filter that preceded the index was
    the same class one layer down: it closed gitignored junk and left every
    untracked-but-not-ignored file shipping from both builders.
    """

    def _load_script_builder(self):
        import importlib.util
        candidate = Path(__file__).resolve().parents[1] / "scripts" / "build_release_archive.py"
        spec = importlib.util.spec_from_file_location("_bra_index_pin", candidate)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_both_builders_route_through_the_shared_helper(self):
        """Structural pin: neither builder may grow its own copy of the query."""
        root = Path(__file__).resolve().parents[1]
        for rel in ("espalier/release_pack.py", "scripts/build_release_archive.py"):
            src = (root / rel).read_text(encoding="utf-8")
            assert "tracked_paths(" in src, f"{rel} does not enumerate the git index"
            assert "ls-files" not in src, (
                f"{rel} carries its own `git ls-files` call — that is the "
                f"duplication the shared helper exists to prevent"
            )
        # The retired sentence. Four sites still said it after the index landed,
        # two of them inside files that diff had already edited; a reader who
        # finds it stops looking for the sister site.
        for rel in (
            "espalier/release_pack.py", "scripts/build_release_archive.py",
            "espalier/surface_contract.py", "espalier/pre_release.py",
        ):
            src = (root / rel).read_text(encoding="utf-8")
            assert "walks the working tree" not in src, (
                f"{rel} still says the release walker walks the working tree"
            )

    def test_script_builder_refuses_an_empty_index(self, tmp_path):
        """Earn-the-red: pre-fix an empty index took the index branch and wrote
        a 22-byte zip at exit 0 -- the sister's refusal had not travelled."""
        mod = self._load_script_builder()
        root = tmp_path / "repo"
        (root / "espalier").mkdir(parents=True)
        (root / "espalier" / "__init__.py").write_text("", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "0.0.0"\n', encoding="utf-8"
        )
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        with pytest.raises(SystemExit, match="empty release archive"):
            mod.build_release_archive(root, output_dir=tmp_path / "out")
        assert not list((tmp_path / "out").glob("*.zip")) if (tmp_path / "out").exists() else True

    def test_script_builder_ships_only_the_index(self, tmp_path):
        """Earn-the-red: pre-fix the matrix's own builder shipped the stray."""
        mod = self._load_script_builder()
        root = tmp_path / "repo"
        (root / "espalier").mkdir(parents=True)
        (root / "espalier" / "__init__.py").write_text("", encoding="utf-8")
        (root / "README.md").write_text("# r\n", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "0.0.0"\n', encoding="utf-8"
        )
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        # Untracked, NOT gitignored, classifies public: the exact gap the
        # ignore-set filter left open.
        (root / "espalier" / "stray_public.py").write_text("x = 1\n", encoding="utf-8")
        archive = mod.build_release_archive(root, output_dir=tmp_path / "out")
        with zipfile.ZipFile(archive) as zf:
            names = {n.split("/", 1)[1] for n in zf.namelist()}
        assert "README.md" in names and "espalier/__init__.py" in names
        assert "espalier/stray_public.py" not in names, "an untracked public file shipped"

    def test_a_directory_inside_another_repo_has_no_index_of_its_own(self, tmp_path):
        """`git ls-files` walks UP. An extracted archive lives inside this repo's
        gitignored `dist/`, so querying it answers about the PARENT — the wrong
        index entirely (with the ignore set it emptied the archive and failed the
        matrix's own release_check). Only a directory that owns its `.git`
        counts; the rest get the tree walk, and say so."""
        from espalier import surface_contract as sc
        outer = tmp_path / "outer"
        outer.mkdir()
        subprocess.run(["git", "init", "-q", str(outer)], check=True)
        (outer / ".gitignore").write_text("nested/\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(outer), "add", "-A"], check=True)
        nested = outer / "nested"
        nested.mkdir()
        (nested / "real_source.py").write_text("x = 1\n", encoding="utf-8")
        assert sc.tracked_paths(outer) == {".gitignore"}
        assert sc.tracked_paths(nested) is None, (
            "a directory that does not own its .git must yield no index, "
            "or an extracted archive enumerates its parent's files"
        )
