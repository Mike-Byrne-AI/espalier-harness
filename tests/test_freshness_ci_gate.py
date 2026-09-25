"""TP-56-C Sub-task 1-F: ``espalier freshness check --critical-only
--changed-files <list>`` exit semantics.

Pins the CI gate's blast-radius contract: it runs against the PR's
changed-files set, and a critical fragment whose bound paths do
not intersect that set is reported in the output but does not
block the merge. Stale (non-critical) fragments never block. This
prevents the failure mode where a totally unrelated PR fails CI
because some critical fragment elsewhere in the repo went out-of-
date — only the fragments the PR actually touches gate the merge.

These tests build a tmp repo with controlled fragment state and
invoke the CLI directly (no subprocess) so the assertions are
stable on Windows and CI runners.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from espalier.freshness import STALE_THRESHOLD_COMMITS



def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "-C", str(repo), *args],
        check=True, capture_output=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    return repo


def _commit_all(repo: Path, message: str) -> str:
    subprocess.run(
        ["git", "-C", str(repo), "add", "-A"],
        check=True, capture_output=True,
    )
    _git(repo, "commit", "-q", "-m", message)
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return result.stdout.strip()


def _seed_fragment(
    repo: Path,
    fragment_id: str,
    bound: str,
    target_path: str,
    *,
    state: str = "critical",
    policy: str = "verify-on-touch",
) -> None:
    from datetime import datetime, timezone
    (repo / target_path).parent.mkdir(parents=True, exist_ok=True)
    (repo / target_path).write_text("x = 1\n", encoding="utf-8")
    doc_dir = repo / "docs"
    doc_dir.mkdir(exist_ok=True)
    doc = doc_dir / f"{fragment_id}.md"
    doc.write_text(
        f"<!-- espalier:fragment id={fragment_id} bound={bound} "
        f"policy={policy} -->\nclaim.\n",
        encoding="utf-8",
    )
    sha = _commit_all(repo, f"init {fragment_id}")
    manifest = repo / ".espalier" / "freshness.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    last_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = {
        "schema_version": 1,
        "fragments": {
            fragment_id: {
                "bound": [bound],
                "policy": policy,
                "last_verified_sha": sha,
                "last_verified_at": last_at,
            }
        },
    }
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if state == "critical":
        # One past the threshold is enough to classify "critical"; 50 spent ~44
        # needless git subprocesses per critical seed (×~5 critical tests).
        commits = STALE_THRESHOLD_COMMITS + 1
    elif state == "stale":
        commits = 2
    else:
        commits = 0
    for n in range(commits):
        (repo / target_path).write_text(
            f"x = {n + 2}\n", encoding="utf-8"
        )
        _commit_all(repo, f"bump {n}")


def _run_cli(
    repo: Path, *cli_args: str
) -> int:
    import sys
    from espalier.cli import main
    saved_argv = sys.argv
    sys.argv = ["espalier", "freshness", "check", *cli_args, str(repo)]
    try:
        return main()
    finally:
        sys.argv = saved_argv


class TestCriticalOnlyChangedFiles:
    """``--critical-only --changed-files <list>`` exits 0 when no
    critical fragment intersects, exits 2 when at least one does."""

    def test_critical_outside_changed_files_exits_zero(
        self, tmp_path: Path, capsys
    ) -> None:
        repo = _init_repo(tmp_path)
        _seed_fragment(
            repo, "test-critical-out", "src/foo.py",
            "src/foo.py", state="critical",
        )
        rc = _run_cli(
            repo, "--critical-only",
            "--changed-files", "docs/something_else.md",
        )
        capsys.readouterr()
        assert rc == 0

    def test_critical_inside_changed_files_exits_two(
        self, tmp_path: Path, capsys
    ) -> None:
        repo = _init_repo(tmp_path)
        _seed_fragment(
            repo, "test-critical-in", "src/foo.py",
            "src/foo.py", state="critical",
        )
        rc = _run_cli(
            repo, "--critical-only",
            "--changed-files", "src/foo.py",
        )
        capsys.readouterr()
        assert rc == 2

    def test_empty_changed_files_means_repo_wide(
        self, tmp_path: Path, capsys
    ) -> None:
        repo = _init_repo(tmp_path)
        _seed_fragment(
            repo, "test-critical-repo-wide", "src/foo.py",
            "src/foo.py", state="critical",
        )
        rc = _run_cli(repo, "--critical-only", "--changed-files", "")
        capsys.readouterr()
        assert rc == 2

    def test_no_criticals_exits_zero(
        self, tmp_path: Path, capsys
    ) -> None:
        repo = _init_repo(tmp_path)
        _seed_fragment(
            repo, "test-fresh", "src/foo.py", "src/foo.py",
            state="fresh",
        )
        rc = _run_cli(
            repo, "--critical-only",
            "--changed-files", "src/foo.py",
        )
        capsys.readouterr()
        assert rc == 0

    def test_directory_change_intersects_file_bound(
        self, tmp_path: Path, capsys
    ) -> None:
        """Changing ``src/`` should intersect bound ``src/foo.py``."""
        repo = _init_repo(tmp_path)
        _seed_fragment(
            repo, "test-dir-intersect", "src/foo.py",
            "src/foo.py", state="critical",
        )
        rc = _run_cli(
            repo, "--critical-only",
            "--changed-files", "src",
        )
        capsys.readouterr()
        assert rc == 2

    def test_changed_files_does_not_affect_non_critical_states(
        self, tmp_path: Path, capsys
    ) -> None:
        """Stale fragments never block, regardless of changed-files."""
        repo = _init_repo(tmp_path)
        _seed_fragment(
            repo, "test-stale-only", "src/foo.py", "src/foo.py",
            state="stale",
        )
        rc = _run_cli(
            repo, "--critical-only",
            "--changed-files", "src/foo.py",
        )
        capsys.readouterr()
        assert rc == 0


class TestRepoWideMode:
    """Without ``--changed-files``, any critical blocks."""

    def test_any_critical_blocks_without_changed_files(
        self, tmp_path: Path, capsys
    ) -> None:
        repo = _init_repo(tmp_path)
        _seed_fragment(
            repo, "test-any-critical", "unrelated/file.py",
            "unrelated/file.py", state="critical",
        )
        rc = _run_cli(repo)
        capsys.readouterr()
        assert rc == 2

    def test_no_critical_exits_zero(
        self, tmp_path: Path, capsys
    ) -> None:
        repo = _init_repo(tmp_path)
        _seed_fragment(
            repo, "test-clean", "src/x.py", "src/x.py",
            state="fresh",
        )
        rc = _run_cli(repo)
        capsys.readouterr()
        assert rc == 0


class TestBoundsIntersectHelper:
    """Unit tests for ``_bounds_intersect`` (TP-56-C)."""

    def test_exact_path_match(self) -> None:
        from espalier.cli import _bounds_intersect
        assert _bounds_intersect(("src/foo.py",), {"src/foo.py"})

    def test_directory_covers_file(self) -> None:
        from espalier.cli import _bounds_intersect
        assert _bounds_intersect(("src/foo.py",), {"src"})

    def test_file_covered_by_parent_directory(self) -> None:
        from espalier.cli import _bounds_intersect
        assert _bounds_intersect(("src",), {"src/foo.py"})

    def test_unrelated_paths_do_not_intersect(self) -> None:
        from espalier.cli import _bounds_intersect
        assert not _bounds_intersect(
            ("src/foo.py",), {"docs/other.md"}
        )

    def test_strips_symbol_suffix(self) -> None:
        from espalier.cli import _bounds_intersect
        assert _bounds_intersect(
            ("src/foo.py::DENIED_PATTERNS",), {"src/foo.py"}
        )

    def test_empty_changed_returns_false(self) -> None:
        from espalier.cli import _bounds_intersect
        assert not _bounds_intersect(("src/foo.py",), set())

    def test_closure_widens_intersection(self) -> None:
        from espalier.cli import _bounds_intersect
        assert _bounds_intersect(
            ("src/foo.py",), {"src/caller.py"},
            closure_paths={"src/foo.py", "src/caller.py"},
        )
