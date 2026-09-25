"""Single source of truth for release-archive noise patterns.

The release-archive classifier and the tracked-noise audit historically
maintained independent pattern lists. They drifted, and `project.zip`
sailed past both gates into a public release (v0.6.0). This module is
the structural fix: one inventory, two consumers, one parity test.

Pattern conventions:
- Trailing `/` = directory prefix (matched against normalized rel path).
- Leading `*.` = extension/glob match on basename.
- No leading `/` — paths are project-relative.
- Patterns are case-sensitive on Linux; `.DS_Store` is a literal name
  match and that's deliberate.

Two consumers:
- `espalier.surface_contract` imports `RELEASE_NOISE_PATTERNS` from
  this module — used by `classify_release_path` and the build_release
  glob filter.
- `scripts.release_check` builds `_TRACKED_NOISE_PATTERNS` from this
  module — used by `check_tracked_noise` (regex form translation
  happens at the consumer; this module stays glob-style).

A parity test (`tests/test_release_noise_parity.py`) ensures every
pattern here is also covered by `.gitignore`. `.gitignore` may be a
strict superset (it covers dev-only patterns the release classifier
need not know about); the SoT is the floor.
"""
from __future__ import annotations

# Transient build/cache directories that should never appear in any
# committed surface or public archive.
TRANSIENT_DIRS: tuple[str, ...] = (
    ".espalier-state/",
    ".git/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".idea/",
    ".vscode/",
    ".venv/",
    "venv/",
    "env/",
    "htmlcov/",
    "*.egg-info/",
    "__MACOSX/",
    "__pycache__/",
    # The `build*/` family glob also matches adopter dirs like
    # `builder/`/`buildkite/`. Deliberately ACCEPT-AND-LEAVE (not narrowed):
    # release_pack runs only on the harness's own tree (adopters never build
    # the espalier archive), so on an adopter repo this surfaces at most a soft
    # `_find_transient_noise` WARNING — never a blocked zip or failed gate.
    # The asymmetric narrowing relocates friction to a release-abort and loses
    # leak coverage; if ever narrowed, mirror release_denylist.py symmetrically.
    "build*/",
    "dist/",
    # Test-runner virtualenv directories.
    ".tox/",
    ".nox/",
)

# OS- and editor-emitted files that should never ship.
TRANSIENT_FILES: tuple[str, ...] = (
    ".DS_Store",
    "Thumbs.db",
    "*.code-workspace",
    ".coverage",
    # AppleDouble resource forks + editor/merge/backup droppings.
    "._*",
    "*.swp",
    "*.swo",
    "*.orig",
    "*.rej",
    "*.bak",
    "*~",
    # A bare `.git` FILE: a `git worktree` or submodule checkout keeps its admin
    # dir elsewhere and leaves a one-line gitlink (`gitdir: /abs/path/...`) at
    # its root. The directory form is `.git/` above; this is the file form,
    # which the index enumeration never sees but the no-index fallback walk
    # and every other consumer of the contract classified as shippable.
    ".git",
)

# Secret / credential files that must never enter a release archive.
# The archive builders enumerate the git index, so an untracked secret never
# ships from a git root; what these still catch is a TRACKED one (committed or
# force-added by mistake) and the no-index fallback, where the builders walk
# the working tree.
# This is the FIRST witness; `espalier.release_denylist` is the second.
SECRET_FILES: tuple[str, ...] = (
    ".env",
    ".env.*",
    ".pypirc",
    ".netrc",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "credentials",
    "credentials.json",
)

# Archive artifacts at any path in the repo. `dist/*.zip` is already
# covered by `dist/` above; this catches the v0.6.0 class where a
# top-level `project.zip` slipped past both classifiers.
ARCHIVE_FILES: tuple[str, ...] = (
    "*.zip",
    "*.tar",
    "*.tar.gz",
    "*.tgz",
    "*.tar.bz2",
    "*.7z",
    "*.whl",
    "*.egg",
)

# Aggregated view — the floor inventory both consumers must respect.
RELEASE_NOISE_PATTERNS: tuple[str, ...] = (
    TRANSIENT_DIRS
    + TRANSIENT_FILES
    + ARCHIVE_FILES
    + SECRET_FILES
)
