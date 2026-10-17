"""A fixture repository never runs a background git (DEF-1168, §C28).

Not a test module (leading underscore): no marker classification needed.

``git commit`` spawns ``git maintenance run --auto``, which repacks the
object store in a detached process when it judges there is work. A tree
that a fixture builds once and then copies, or that several tests read, can
lose files mid-read to that process. A per-test copy of
``initialized_repo_root`` found a ``tmp_pack_*`` gone (DEF-1168), and the
census tree in ``tests/test_cli_deploy.py`` lost whole object folders
mid-copy, both in CI only.

Set :data:`NO_BACKGROUND_GIT` right after ``git init``, with the builder's
own git runner. ``.git/config`` keeps the keys for every later command in
the repository and for every file copy of it (``shutil.copytree``, fuse's
copy). A ``git clone`` writes a fresh config, which is enough where the
source is what a clone reads and nothing copies the clone.
``tests/conftest.py``'s ``_build_initialized_repo`` was the first site and
loops over the same tuple in its own timed build steps.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from tests._git_oracle import _git_env

NO_BACKGROUND_GIT: tuple[tuple[str, str], ...] = (
    ("gc.auto", "0"),
    ("gc.autoDetach", "false"),
    ("maintenance.auto", "false"),
)


def background_git_settings(tree: Path) -> dict[str, str]:
    """What ``tree``'s own config holds for each key (an empty string when
    unset), read without a write: a builder's pin compares it with
    ``dict(NO_BACKGROUND_GIT)``, so a shared tree is pinned in place. The
    read strips git's repo-selecting overrides, since an exported
    ``GIT_DIR`` (``git rebase --exec``, a hook) outranks ``-C`` and would
    read the outer repository's config instead."""
    return {key: subprocess.run(["git", "-C", str(tree), "config", "--local", "--get", key],
                                capture_output=True, text=True, encoding="utf-8", timeout=15,
                                env=_git_env()).stdout.strip()
            for key, _ in NO_BACKGROUND_GIT}
