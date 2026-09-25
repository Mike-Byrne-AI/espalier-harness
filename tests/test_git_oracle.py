"""The shared git oracle refuses where git would answer the wrong question.

Every assertion here drives REAL ``git`` against a purpose-built worktree rather
than mocking a return code, because the whole point of `tests/_git_oracle.py` is
platform behaviour that nobody would have predicted from reading the docs. A
mocked rc would prove only that the helper branches on the number I told it.

``TestRawGitBehaviourTheOracleDefendsAgainst`` is the load-bearing half: it pins
the two mechanisms as facts about git itself, measured 2026-08-14. If a future
git changes either, those tests red and tell us the guard's premise moved --
rather than the guard quietly becoming ceremony that no longer defends anything.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests._git_oracle import (
    GitAnswerUnavailable,
    owns_its_worktree,
    require_head_tree_paths,
    require_is_gitignored,
    require_tracked_paths,
)


def _commit(root: Path) -> None:
    """Give `root` a HEAD, with the identity passed per-invocation so the test
    never depends on (or mutates) the host's git config."""
    subprocess.run(
        ["git", "-C", str(root),
         "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "-q", "-m", "seed"],
        check=True, capture_output=True, timeout=30,
    )


def _worktree(root: Path) -> Path:
    """A minimal real worktree: one ignored dir, two tracked files, an index.

    No commit is made -- ``ls-files`` and ``check-ignore`` both read the index
    and the ignore rules, neither needs a HEAD, and skipping the commit also
    skips needing a git identity on the host. Call ``_commit`` on top when a
    HEAD tree is the subject.
    """
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True,
                   capture_output=True, timeout=30)
    (root / ".gitignore").write_text("build/\nlocal-note.md\n", encoding="utf-8")
    (root / "kept.md").write_text("kept\n", encoding="utf-8")
    (root / "local-note.md").write_text("ignored\n", encoding="utf-8")
    (root / "build").mkdir()
    (root / "build" / "artifact.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", ".gitignore", "kept.md"],
                   check=True, capture_output=True, timeout=30)
    return root


class TestRawGitBehaviourTheOracleDefendsAgainst:
    """Pin the two mechanisms as facts about git, not as assumptions in a docstring."""

    def test_ls_files_returns_rc_zero_and_no_rows_inside_an_ignored_dir(self, tmp_path):
        """Mechanism 1. The failure that is NOT an error: a caller using
        ``check=True`` sees success and an empty set, and a denylist checked
        against an empty set passes."""
        root = _worktree(tmp_path / "repo")
        proc = subprocess.run(
            ["git", "ls-files"], cwd=str(root / "build"),
            capture_output=True, text=True, timeout=30, encoding="utf-8",
        )
        assert proc.returncode == 0, (
            "premise moved: git used to succeed inside an ignored dir. "
            f"stderr={proc.stderr.strip()[:200]}"
        )
        assert [ln for ln in proc.stdout.split("\n") if ln.strip()] == [], (
            "premise moved: git used to return ZERO ROWS inside an ignored dir"
        )

    def test_ls_files_returns_rc_128_outside_any_worktree(self, tmp_path):
        """The other half of mechanism 1, and the reason location is part of the
        measurement: the SAME command fails loudly here and silently above."""
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        proc = subprocess.run(
            ["git", "ls-files"], cwd=str(outside),
            capture_output=True, text=True, timeout=30, encoding="utf-8",
        )
        assert proc.returncode == 128, (
            f"premise moved: expected rc 128 outside a worktree, got {proc.returncode}"
        )

    def test_check_ignore_says_yes_to_everything_inside_an_ignored_dir(self, tmp_path):
        """Mechanism 2, with a POSITIVE CONTROL: a path that does not exist and
        matches no rule still comes back "ignored", because an ancestor is. This
        is why no size floor can catch this shape -- the answer is wrong, not
        missing."""
        root = _worktree(tmp_path / "repo")
        for probe in ("kept.md", ".gitignore", "totally-made-up-path.xyz"):
            rc = subprocess.run(
                ["git", "check-ignore", "-q", "--", probe],
                cwd=str(root / "build"), capture_output=True, timeout=30,
            ).returncode
            assert rc == 0, (
                f"premise moved: {probe!r} used to read as IGNORED (rc 0) from "
                f"inside an ignored dir; got rc {rc}"
            )
        # Contrast, same repo, same probes, asked from the top.
        for probe in ("kept.md", ".gitignore", "totally-made-up-path.xyz"):
            rc = subprocess.run(
                ["git", "check-ignore", "-q", "--", probe],
                cwd=str(root), capture_output=True, timeout=30,
            ).returncode
            assert rc == 1, (
                f"premise moved: {probe!r} should NOT be ignored at the worktree "
                f"top; got rc {rc}"
            )


class TestTheOwnershipGuardIsLoadBearing:
    """The mutation these exist to kill.

    MEASURED 2026-08-14 by the adversarial pass: replacing every
    `if not owns_its_worktree(repo_root):` in `tests/_git_oracle.py` with
    `if False:` left **24 of the module's 26 tests green**. The ownership check
    -- the entire premise of the helper, and of the commit message's claim that
    the distinction is unavailable "by construction rather than by discipline"
    -- was witnessed by essentially nothing. Every refusal the suite asserted
    was reachable through the FLOOR or through `returncode != 0` instead.

    The one case where the guard is not redundant with the floor is a NON-EMPTY
    FOREIGN answer: a tree sitting in a *tracked* subdirectory of someone else's
    worktree. git answers rc 0 with plenty of rows -- clearing any floor -- and
    they are the wrong repository's rows. That is what these construct.

    Delete the guard and these two go red; delete the floor and the older tests
    go red. Both halves are now pinned separately.
    """

    def _outer_with_tracked_subdir(self, root: Path, n: int = 8) -> Path:
        """A real worktree whose `sub/` is TRACKED and holds `n` files."""
        root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(root)], check=True,
                       capture_output=True, timeout=30)
        sub = root / "sub"
        sub.mkdir()
        for i in range(n):
            (sub / f"f{i}.txt").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "sub"],
                       check=True, capture_output=True, timeout=30)
        return sub

    def test_tracked_subdir_of_a_foreign_worktree_is_refused(self, tmp_path):
        """rc 0, 8 rows, clears any floor -- and they are the OTHER repo's."""
        sub = self._outer_with_tracked_subdir(tmp_path / "outer")
        assert not owns_its_worktree(sub)
        with pytest.raises(GitAnswerUnavailable):
            require_tracked_paths(sub, minimum=5)

    def test_head_tree_in_a_tracked_subdir_is_refused_too(self, tmp_path):
        """Same for the HEAD-tree entry point, which shares the failure mode."""
        sub = self._outer_with_tracked_subdir(tmp_path / "outer")
        _commit(sub.parent)
        with pytest.raises(GitAnswerUnavailable):
            require_head_tree_paths(sub, minimum=5)

    def test_a_foreign_git_dir_in_the_environment_cannot_redirect_the_answer(
        self, tmp_path, monkeypatch
    ):
        """The one edge that produced a wrong TRUE rather than a refusal.

        git resolves its repository from GIT_DIR/GIT_WORK_TREE BEFORE the cwd,
        so `--show-toplevel` echoes GIT_WORK_TREE and `ls-files` answers from
        GIT_DIR. Driven before the fix: `owns_its_worktree(hostB)` returned True
        and `require_tracked_paths(hostB)` returned repo A's files.
        """
        a = _worktree(tmp_path / "repoA")
        b = _worktree(tmp_path / "hostB")
        (b / "host-only.md").write_text("b\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(b), "add", "host-only.md"],
                       check=True, capture_output=True, timeout=30)
        monkeypatch.setenv("GIT_DIR", str(a / ".git"))
        monkeypatch.setenv("GIT_WORK_TREE", str(b))
        assert owns_its_worktree(b), (
            "the env scrub should let git answer about b normally"
        )
        assert "host-only.md" in require_tracked_paths(b), (
            "population came from the environment's repo, not from b"
        )


class TestOwnsItsWorktree:
    def test_true_at_the_top_of_a_real_worktree(self, tmp_path):
        assert owns_its_worktree(_worktree(tmp_path / "repo"))

    def test_false_inside_someone_elses_worktree(self, tmp_path):
        """The motivating case: an extracted release archive under this repo's
        gitignored ``dist/``. git works perfectly there -- about the wrong tree."""
        root = _worktree(tmp_path / "repo")
        assert not owns_its_worktree(root / "build")

    def test_false_for_a_tracked_subdir_too(self, tmp_path):
        """Not just IGNORED subdirs: any subdir is not the top. A guard keyed on
        "is this ignored" would miss a plain nested directory."""
        root = _worktree(tmp_path / "repo")
        nested = root / "pkg"
        nested.mkdir()
        assert not owns_its_worktree(nested)

    def test_false_outside_any_worktree(self, tmp_path):
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        assert not owns_its_worktree(outside)

    def test_false_for_a_path_that_does_not_exist(self, tmp_path):
        assert not owns_its_worktree(tmp_path / "nope" / "still-nope")


class TestRequireTrackedPaths:
    def test_returns_the_tracked_set_at_a_real_worktree(self, tmp_path):
        paths = require_tracked_paths(_worktree(tmp_path / "repo"))
        assert sorted(paths) == [".gitignore", "kept.md"]

    def test_patterns_are_passed_through(self, tmp_path):
        paths = require_tracked_paths(_worktree(tmp_path / "repo"), "*.md")
        assert paths == ["kept.md"]

    def test_raises_inside_an_ignored_dir_rather_than_returning_empty(self, tmp_path):
        """THE defect this module exists for. Without the guard this returns
        ``[]`` at rc 0 and every membership assertion downstream passes."""
        root = _worktree(tmp_path / "repo")
        with pytest.raises(GitAnswerUnavailable):
            require_tracked_paths(root / "build")

    def test_raises_outside_any_worktree(self, tmp_path):
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        with pytest.raises(GitAnswerUnavailable):
            require_tracked_paths(outside)

    def test_raises_below_the_floor(self, tmp_path):
        """A shallow/partial checkout answers honestly and is still too small to
        assert over -- the case ``test_release_pack.py``'s floor was written for."""
        root = _worktree(tmp_path / "repo")
        with pytest.raises(GitAnswerUnavailable):
            require_tracked_paths(root, minimum=500)

    def test_the_floor_is_inclusive_at_its_boundary(self, tmp_path):
        """Two tracked files must satisfy ``minimum=2``. An off-by-one here would
        make every caller's floor one stricter than it reads."""
        root = _worktree(tmp_path / "repo")
        assert len(require_tracked_paths(root, minimum=2)) == 2

    def test_the_message_names_the_caller_s_subject(self, tmp_path):
        """Diagnostic contract: the raise has to say WHAT population collapsed,
        or the next reader gets a bare 'git unavailable' and re-derives it."""
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        with pytest.raises(GitAnswerUnavailable, match="tracked markdown"):
            require_tracked_paths(outside, "*.md", what="tracked markdown")


class TestRequireHeadTreePaths:
    """The HEAD tree is a DIFFERENT population from the index, and shares every
    failure mode -- so it needs its own entry point, not a caller re-rolling
    ``ls-tree`` beside the guarded ``ls-files``."""

    def test_returns_the_head_tree_at_a_real_worktree(self, tmp_path):
        root = _worktree(tmp_path / "repo")
        _commit(root)
        assert sorted(require_head_tree_paths(root)) == [".gitignore", "kept.md"]

    def test_differs_from_the_index_on_a_staged_but_uncommitted_add(self, tmp_path):
        """The reason both entry points exist. Conflating them reports a staged
        add as 'pruned by git archive'."""
        root = _worktree(tmp_path / "repo")
        _commit(root)
        (root / "added.md").write_text("new\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "added.md"],
                       check=True, capture_output=True, timeout=30)
        assert "added.md" in require_tracked_paths(root)
        assert "added.md" not in require_head_tree_paths(root)

    def test_raises_inside_an_ignored_dir_rather_than_returning_empty(self, tmp_path):
        root = _worktree(tmp_path / "repo")
        _commit(root)
        with pytest.raises(GitAnswerUnavailable):
            require_head_tree_paths(root / "build")

    def test_raises_outside_any_worktree(self, tmp_path):
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        with pytest.raises(GitAnswerUnavailable):
            require_head_tree_paths(outside)

    def test_raises_on_an_unborn_head(self, tmp_path):
        """A worktree it OWNS, with no commit yet: git errors rather than
        returning empty, and the caller must not read that as 'nothing tracked'."""
        root = _worktree(tmp_path / "repo")
        with pytest.raises(GitAnswerUnavailable):
            require_head_tree_paths(root)

    def test_raises_below_the_floor(self, tmp_path):
        root = _worktree(tmp_path / "repo")
        _commit(root)
        with pytest.raises(GitAnswerUnavailable):
            require_head_tree_paths(root, minimum=900)


class TestRequireIsGitignored:
    def test_true_for_an_ignored_path(self, tmp_path):
        assert require_is_gitignored(_worktree(tmp_path / "repo"), "local-note.md")

    def test_false_for_a_tracked_path(self, tmp_path):
        assert not require_is_gitignored(_worktree(tmp_path / "repo"), "kept.md")

    def test_answers_for_a_path_that_does_not_exist_on_disk(self, tmp_path):
        """The legitimate use: an exempt-registry entry may be absent AND
        deliberately ignored. Existence is not the question being asked."""
        root = _worktree(tmp_path / "repo")
        assert require_is_gitignored(root, "build/never-created.txt")
        assert not require_is_gitignored(root, "also-never-created.txt")

    def test_raises_inside_an_ignored_dir_rather_than_saying_yes(self, tmp_path):
        """Without the guard this returns True for every path ever asked --
        including ``totally-made-up-path.xyz``, pinned above."""
        root = _worktree(tmp_path / "repo")
        with pytest.raises(GitAnswerUnavailable):
            require_is_gitignored(root / "build", "kept.md")

    def test_raises_outside_any_worktree(self, tmp_path):
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        with pytest.raises(GitAnswerUnavailable):
            require_is_gitignored(outside, "anything.md")


def test_the_repo_redirecting_env_list_has_one_shape_everywhere() -> None:
    """Four owners of the same six keys: this module, the engine's hermetic
    gitignore oracle (DEF-635), the handoff snapshot script, and the release
    matrix's git seed (DEF-670, the first WRITING git site -- inherited, the
    channel would re-initialise the operator's repo from inside the extract).
    A key added to one and not the others re-opens the channel there; parity
    is pinned rather than claimed in a docstring."""
    import importlib.util
    import sys as _sys

    from espalier.cli import _GIT_REDIRECT_ENV
    from tests._git_oracle import _GIT_ENV_OVERRIDES

    scripts = Path(__file__).resolve().parent.parent / "scripts"

    def _load(name: str, alias: str):
        spec = importlib.util.spec_from_file_location(alias, scripts / name)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        # Registered before exec so a @dataclass in the script resolves its
        # module (the matrix script carries one).
        _sys.modules[alias] = module
        spec.loader.exec_module(module)
        return module

    snapshot = _load("record_snapshot.py", "_record_snapshot_env")
    matrix = _load("final_release_matrix.py", "_final_release_matrix_env")

    assert (
        tuple(_GIT_REDIRECT_ENV)
        == tuple(_GIT_ENV_OVERRIDES)
        == tuple(snapshot._GIT_ENV_OVERRIDES)
        == tuple(matrix._GIT_REDIRECT_ENV)
    )
