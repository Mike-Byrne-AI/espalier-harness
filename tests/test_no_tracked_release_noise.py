"""Tracked-file leak guard — TP-RELEASE-03 task 3-E.

Runs `git ls-files` and asserts no tracked path matches the
release-noise pattern set. This catches re-leaks introduced by
contributors running `git add .` after generating reports, building
artifacts, or saving local Claude settings.

Marker assignment is centralized in tests/conftest.py; this file's
stem doesn't match a pattern there, so it falls through to the
`unit` default. That's fine — the test is a tiny static check.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_PATTERNS: tuple[str, ...] = (
    r"(?:^|/)\.DS_Store$",
    r"\.pyc$",
    r"\.egg-info(?:/|$)",
    r"\.code-workspace$",
    r"^bench/results/",
    r"^cc/blueprints/",
    # A task pack outside its two shipped locations (task-packs/ root and
    # task-packs/Deferred/, tracked and shipping since 2026-09-21), and the
    # landed / merged / scrapped subtrees. Independently written twin of
    # scripts/release_check.py::_TRACKED_NOISE_PATTERNS.
    r"^(?!task-packs/(?:Deferred/)?TP-[^/]+\.md$)(?:.*/)?TP-[^/]+\.md$",
    r"^task-packs/(?:Done|Merged|Scrapped)/",
    r"(?:^|/)TP-[^/]+/",
    r"_task_pack\.md$",
    r"^\.claude/settings\.json$",
    r"^\.claude/settings\.local\.json$",
    r"(?:^|/)zDone/",
    r"^\.env$",
)


def _git_ls_files() -> list[str]:
    """Return file list as repo-relative POSIX paths.

    TP-RELEASE-19: name is historical. On a git checkout returns
    ``git ls-files`` output. On a non-git context (source archive,
    sdist) returns a filesystem walk of the working tree. Either way
    the noise patterns are applied to a real file list — the test
    cannot silently skip on a fresh extract.
    """
    from espalier.repo_mode import list_tracked_or_walked_files
    files, _source = list_tracked_or_walked_files(REPO_ROOT)
    return files


def test_no_tracked_release_noise():
    """No tracked file may match a release-noise pattern."""
    tracked = _git_ls_files()
    assert tracked, "git ls-files returned no paths — repo state is suspicious"

    compiled = [(re.compile(p), p) for p in FORBIDDEN_PATTERNS]
    offenders: list[tuple[str, str]] = []
    for path in tracked:
        for pattern, source in compiled:
            if pattern.search(path):
                offenders.append((path, source))
                break

    assert not offenders, (
        "Tracked release-noise files found:\n"
        + "\n".join(f"  - {p}  (matched: {pat})" for p, pat in offenders)
        + "\nUntrack each via `git rm --cached <path>`. "
        "If a path should legitimately ship, update FORBIDDEN_PATTERNS "
        "and the corresponding rule in .gitignore + "
        "scripts/build_release_archive.py."
    )
