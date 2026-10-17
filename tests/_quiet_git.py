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
the repository and for every copy of it. ``tests/conftest.py``'s
``_build_initialized_repo`` was the first site; it sets the same three keys
in its own timed build steps.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

NO_BACKGROUND_GIT: tuple[tuple[str, str], ...] = (
    ("gc.auto", "0"),
    ("gc.autoDetach", "false"),
    ("maintenance.auto", "false"),
)


def background_git_settings(tree: Path) -> dict[str, str]:
    """What ``tree``'s own config holds for each key (an empty string when
    unset), read without a write: a builder's pin compares it with
    ``dict(NO_BACKGROUND_GIT)``, so a shared tree is pinned in place."""
    return {key: subprocess.run(["git", "-C", str(tree), "config", "--local", "--get", key],
                                capture_output=True, text=True, timeout=15).stdout.strip()
            for key, _ in NO_BACKGROUND_GIT}
