"""Ask git a question only where git can answer it about THIS tree.

Not a test module (leading underscore) -- no marker classification needed.

**Why this exists.** `git` almost never refuses. Asked from the wrong place it
answers a DIFFERENT question, with rc 0, and the caller reads that as its own
answer. Two shapes, both measured on this repo (2026-08-14) by driving the real
release archive at two extraction locations:

1. **Empty is not absent.** `git ls-files` / `git ls-tree` return **rc 0 with
   zero rows** when the cwd is an untracked or gitignored directory inside a
   worktree, and **rc 128** outside any worktree. A guard that turns either into
   an empty set and then asserts `not [x for x in DENYLIST if x in tracked]`
   passes having checked nothing. `tests/test_git_archive_parity.py` did exactly
   this against a 12-entry denylist -- the pre-commit gate against a
   kill-switched `settings.json` reaching the index -- and went green under
   `dist/` while failing outside it.

2. **A blanket yes is worse than an empty set.** `git check-ignore -q` run with
   cwd inside a *gitignored* directory returns **rc 0 for every path**, because
   an ancestor is ignored. Measured with a positive control: from `dist/probe_ci`,
   `ESPALIER_MEMORY.md`, `docs/CONVENTIONS.md`, `pyproject.toml` and
   `totally-made-up-path.xyz` ALL returned rc 0; from the repo root all four
   returned rc 1. No size floor can catch that -- the answer is wrong, not
   missing -- so the guard has to be "does git here answer about this tree at all".

**The API deliberately gives callers no way to tell the two failures apart.**
`DEF-434`/`DEF-435` were `x is None` where `not x` was meant, on this exact
shape; the fix prescribed "treat empty and absent alike ... from one helper so a
third caller cannot re-introduce the distinction." The helper was never built,
and five more sites re-introduced it. So `require_tracked_paths` collapses
unanswerable, errored, empty and implausibly-small into ONE raise: a caller
cannot handle a case it cannot observe.

**Callers choose the disposition, not the discrimination.** Let
`GitAnswerUnavailable` propagate to fail the test (the usual choice -- a
collapsed population means something is wrong), or catch it and `pytest.skip`
where the question is genuinely unanswerable in a legitimate tree. Both are
honest; silently continuing with an empty set is not.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

_TIMEOUT = 30

# git reads its target repository from the environment before it reads the cwd.
# With these inherited, `rev-parse --show-toplevel` echoes GIT_WORK_TREE and
# `ls-files` answers from GIT_DIR -- so the ownership check passes while the
# population comes from a DIFFERENT repository. Driven 2026-08-14: with GIT_DIR
# at repo A and GIT_WORK_TREE at host B, `owns_its_worktree(B)` returned True and
# `require_tracked_paths(B)` returned repo A's files. That is the module's own
# stated hazard ("answers a DIFFERENT question, with rc 0") arriving through the
# one channel it did not close, and unlike every other edge it is a wrong TRUE
# rather than a refusal.
#
# Reachable via `git bisect run pytest`, `git rebase --exec`, `git submodule
# foreach`, or any hook that runs the suite. Found by the adversarial pass.
_GIT_ENV_OVERRIDES = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES",
)


def _git_env() -> dict[str, str]:
    """`os.environ` with every repo-selecting override stripped."""
    return {k: v for k, v in os.environ.items() if k not in _GIT_ENV_OVERRIDES}


class GitAnswerUnavailable(Exception):
    """git could not answer about this tree, or answered implausibly.

    Deliberately ONE exception for "no worktree", "not our worktree", "git
    errored", "zero rows" and "below the floor". See the module docstring: a
    caller that can distinguish them will eventually treat one as an answer.
    """


def owns_its_worktree(repo_root: Path) -> bool:
    """True when `git` invoked at `repo_root` answers about `repo_root` itself.

    False for: not a worktree at all (rc 128), and -- the case that motivates
    this helper -- a directory that merely SITS INSIDE someone else's worktree,
    where every git verb silently answers about the parent. An extracted release
    archive under this repo's gitignored `dist/` is exactly that.

    Identity is `os.path.samefile` (device + inode), not string equality on
    resolved paths. String comparison was the first version and it was wrong on
    this repo's own platform: `Path.resolve()` does NOT case-fold on macOS, so a
    caller reaching the repo through `/users/...` instead of `/Users/...` got a
    refusal while `--show-toplevel` reported the true case -- a false negative
    that then hard-fails every consumer with a worktree message about a worktree
    that is fine. `samefile` also subsumes the `/tmp` -> `/private/tmp` symlink
    normalization the string version hand-rolled, and HFS+ NFC/NFD.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=_TIMEOUT, env=_git_env(), encoding="utf-8",
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        return False
    top = proc.stdout.strip()
    if not top:
        return False
    try:
        return os.path.samefile(top, str(repo_root))
    except OSError:
        return False


def require_tracked_paths(
    repo_root: Path, *patterns: str, minimum: int = 1, what: str = "tracked paths"
) -> list[str]:
    """The tracked set at `repo_root`, or raise -- never a silently empty list.

    `patterns` are passed through to `git ls-files` verbatim (e.g. `"*.md"`).
    `minimum` is the non-vacuity floor: pass the smallest count that still makes
    the caller's assertion meaningful. The default of 1 only rules out the empty
    set; a caller sweeping the whole tree should pass a real floor so a small
    FOREIGN population is caught too -- see `test_release_pack.py`.

    The floor does NOT detect a shallow or sparse checkout, and an earlier
    version of this docstring claimed it did. Driven 2026-08-14: `--depth 1`
    and a cone sparse-checkout both leave `ls-files` reporting the FULL index
    (shallow truncates history, sparse marks entries skip-worktree; neither
    removes index rows). What the floor actually catches is a collapsed or
    foreign population -- which is its real job, and worth saying accurately
    so nobody trusts it for the other one.

    Raises `GitAnswerUnavailable` when the answer is unavailable OR implausible.
    """
    if not owns_its_worktree(repo_root):
        raise GitAnswerUnavailable(
            f"{repo_root} is not the top of its own git worktree, so `git "
            f"ls-files` here answers about a DIFFERENT tree (or not at all). "
            f"Refusing to report {what}: an empty or foreign population would "
            f"pass this caller's assertion while checking nothing."
        )
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", *patterns],
            capture_output=True, text=True, timeout=_TIMEOUT, env=_git_env(), encoding="utf-8",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitAnswerUnavailable(f"git ls-files failed at {repo_root}: {exc}") from exc
    if proc.returncode != 0:
        raise GitAnswerUnavailable(
            f"git ls-files exited {proc.returncode} at {repo_root}: "
            f"{proc.stderr.strip()[:200]}"
        )
    paths = [line for line in proc.stdout.split("\n") if line.strip()]
    if len(paths) < minimum:
        raise GitAnswerUnavailable(
            f"git reported only {len(paths)} {what} at {repo_root} "
            f"(floor {minimum}). The population is too small for this to be a "
            f"real check -- a collapsed population, or a tree whose git context "
            f"is not its own. Asserting over it would pass vacuously."
        )
    return paths


def require_head_tree_paths(
    repo_root: Path, *, minimum: int = 1, what: str = "paths at HEAD"
) -> list[str]:
    """The paths in `repo_root`'s HEAD commit tree, or raise -- same contract as
    :func:`require_tracked_paths`, different question.

    The index (`ls-files`) and the HEAD tree (`ls-tree`) are NOT interchangeable:
    a staged-but-uncommitted add is in one and not the other, and `git archive
    HEAD` draws from this one. Callers comparing against an archive must use
    this; callers asserting a pre-commit property must use the index.

    Shares every failure mode with `ls-files`, including the one that motivates
    the module: zero rows at rc 0 inside someone else's worktree.
    """
    if not owns_its_worktree(repo_root):
        raise GitAnswerUnavailable(
            f"{repo_root} is not the top of its own git worktree, so `git "
            f"ls-tree HEAD` here answers about a DIFFERENT tree (or not at all). "
            f"Refusing to report {what}."
        )
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "ls-tree", "-r", "HEAD", "--name-only"],
            capture_output=True, text=True, timeout=_TIMEOUT, env=_git_env(), encoding="utf-8",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitAnswerUnavailable(f"git ls-tree failed at {repo_root}: {exc}") from exc
    if proc.returncode != 0:
        raise GitAnswerUnavailable(
            f"git ls-tree exited {proc.returncode} at {repo_root}: "
            f"{proc.stderr.strip()[:200]}"
        )
    paths = [line for line in proc.stdout.split("\n") if line.strip()]
    if len(paths) < minimum:
        raise GitAnswerUnavailable(
            f"git reported only {len(paths)} {what} at {repo_root} "
            f"(floor {minimum}). Too small to assert over -- a collapsed "
            f"population, an unborn HEAD, or a tree whose git context is not its own."
        )
    return paths


def require_is_gitignored(repo_root: Path, rel: str) -> bool:
    """Would git, at `repo_root`, ignore `rel`?

    Deliberately NOT "would `repo_root`'s own .gitignore ignore it" -- an
    earlier version of this line said that and it over-scoped the mechanism
    three ways. `check-ignore` consults `.gitignore` at every level, PLUS
    `$GIT_DIR/info/exclude` and the user's `core.excludesFile`; this repo has
    already been bitten by the `info/exclude` half (an untracked-scan detector
    went blind to exclude-listed paths). And it answers about the INDEX first:
    a TRACKED path returns "not ignored" however many rules match it.
    None of that is wrong for today's callers -- all three ask only about paths
    already known absent, and index-awareness is strictly better for them (a
    force-added sentinel reds) -- but a future caller reading the old sentence
    would use this to answer a question it does not answer.

    Raises `GitAnswerUnavailable` rather than answering when `repo_root` does
    not own its worktree -- see mechanism 2 in the module docstring, where every
    path (including one that does not exist) comes back "ignored". A caller
    reading a bare rc 0 there waves its whole registry through.

    Answers for a path that does not exist on disk, which is the point: an
    entry can be legitimately absent AND legitimately ignored.
    """
    if not owns_its_worktree(repo_root):
        raise GitAnswerUnavailable(
            f"{repo_root} is not the top of its own git worktree. `git "
            f"check-ignore` here returns rc 0 for EVERY path -- including "
            f"nonexistent ones -- because an ancestor directory is ignored, so "
            f"a bare rc-0 read would wave every entry through."
        )
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "check-ignore", "-q", "--", rel],
            capture_output=True, timeout=_TIMEOUT, env=_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitAnswerUnavailable(
            f"git check-ignore failed at {repo_root} for {rel!r}: {exc}"
        ) from exc
    # 0 = ignored, 1 = not ignored. Anything else is git failing, not answering.
    if proc.returncode not in (0, 1):
        raise GitAnswerUnavailable(
            f"git check-ignore exited {proc.returncode} at {repo_root} for {rel!r}"
        )
    return proc.returncode == 0
