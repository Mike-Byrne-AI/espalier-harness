"""Independent denylist for release-archive members.

This module is the SECOND witness on what should never appear in a release
archive. ``espalier/release_noise.py`` is the FIRST witness — the
inventory the release classifier consumes.

Two independent witnesses are harder to fool than one. The classifier may
have a blind spot (e.g., a new path pattern not yet added); this denylist
catches the same shape via a different lens.

By convention this module imports NOTHING from ``espalier.surface_contract``
or ``espalier.release_noise``. Overlap with release_noise is fine — that is
defense in depth. If this denylist and the classifier ever disagree on a
real archive member, investigate the divergence rather than dismissing it.

See ``docs/SHARP_EDGES.md`` "Release gates that grade themselves through
the same path they validate" for the v0.6.0 ``project.zip`` leak that
motivated the dual-witness pattern.
"""
from __future__ import annotations

import re
from collections.abc import Iterable


# (regex pattern, human-readable reason). Patterns match against archive
# member paths normalised to forward slashes with no leading slash.
DENIED_PATTERNS: tuple[tuple[str, str], ...] = (
    # Nested archives — release archives must not contain release archives
    (r"\.zip$", "nested archive file"),
    (r"\.tar$", "nested tar archive"),
    (r"\.tar\.gz$", "nested compressed tarball"),
    (r"\.tgz$", "nested compressed tarball"),
    (r"\.tar\.bz2$", "nested compressed tarball"),
    (r"\.7z$", "nested 7-zip archive"),

    # Wheel / package artifacts — built outputs don't belong in source archive
    (r"\.whl$", "wheel package artifact"),
    (r"\.egg$", "egg package artifact"),
    (r"\.egg-info(?:/|$)", "egg-info directory"),

    # Repository admin state: `.git/` as a directory, and `.git` as the bare
    # gitlink FILE a `git worktree` or submodule checkout leaves at its root
    # (`gitdir: /abs/path/...`, a local absolute path). `.gitignore`,
    # `.gitattributes`, `.gitmodules` and `.github/` share the prefix, are
    # tracked, shippable names, and must not match.
    (r"(?:^|/)\.git(?:/|$)", "git admin directory or worktree gitlink file"),

    # Cache and editor state
    (r"(?:^|/)\.vscode/", "VS Code workspace state"),
    (r"(?:^|/)\.idea/", "JetBrains IDE state"),
    (r"(?:^|/)\.pytest_cache/", "pytest cache"),
    (r"(?:^|/)__pycache__/", "Python bytecode cache"),
    (r"(?:^|/)\.mypy_cache/", "mypy cache"),
    (r"(?:^|/)\.ruff_cache/", "ruff cache"),
    (r"\.coverage$", "coverage data file"),
    (r"(?:^|/)htmlcov/", "coverage HTML report"),

    # OS dross
    (r"(?:^|/)\.DS_Store$", "macOS finder metadata"),
    (r"(?:^|/)Thumbs\.db$", "Windows thumbnail cache"),
    (r"(?:^|/)__MACOSX/", "macOS resource fork"),
    (r"(?:^|/)\._[^/]*$", "AppleDouble resource fork"),

    # Editor / merge / backup droppings. A stray that is tracked, or one walked
    # by the no-index fallback, would otherwise sail past both witnesses into
    # the public archive.
    (r"\.swp$", "vim swap file"),
    (r"\.swo$", "vim swap file"),
    (r"\.orig$", "merge conflict leftover"),
    (r"\.rej$", "patch reject leftover"),
    (r"\.bak$", "editor backup file"),
    (r"~$", "editor backup file"),

    # Test-runner virtualenv directories
    (r"(?:^|/)\.tox/", "tox environment directory"),
    (r"(?:^|/)\.nox/", "nox environment directory"),

    # Secrets / credentials. The builders enumerate the git index, so the shapes
    # left are a TRACKED secret (committed or force-added by mistake) and the
    # no-index fallback walk — and CI `release_check` uses this same denylist,
    # so both witnesses AND CI would miss it.
    # Squarely in-threat-model (operator MISTAKE, not malice).
    (r"(?:^|/)\.env(?:\.[^/]*)?$", "environment secrets file"),
    (r"(?:^|/)\.pypirc$", "PyPI upload credentials"),
    (r"(?:^|/)\.netrc$", "netrc credentials"),
    (r"(?:^|/)id_(?:rsa|dsa|ecdsa|ed25519)$", "SSH private key"),
    (r"(?:^|/)credentials(?:\.json)?$", "credentials file"),
    # Private-cert / keystore family. Calibrated against the live population
    # before adding: `git ls-files | grep -icE '\.(pem|key|p12|pfx)$'` -> 0, so
    # the false-positive cost here is measured, not assumed. The FP objection on
    # record was precautionary only.
    # `(?i)` per-pattern, NOT re.IGNORECASE on _compiled(): the flag there would
    # silently loosen all 56 patterns. The sibling witness
    # (surface_contract._SECRET_SUFFIX_RE) is case-insensitive, and a Windows
    # PFX export is commonly `.PFX` — without this the two "independent
    # witnesses" disagree on the uppercase spelling, which is exactly the
    # redundancy this module exists to provide.
    (r"(?i)\.pem$", "PEM private key / certificate"),
    (r"(?i)\.key$", "private key file"),
    (r"(?i)\.p12$", "PKCS#12 keystore"),
    (r"(?i)\.pfx$", "PKCS#12 keystore"),

    # Espalier runtime / per-install state
    (r"(?:^|/)\.espalier-state/", "espalier session state"),
    # `.espalier/freshness.json` is COMMITTED (BC-039) so it must NOT be
    # denied by the release archive scrub. The integrity manifest and the
    # manifest-write lock remain per-install state.
    (r"(?:^|/)\.espalier/integrity\.json$", "espalier integrity manifest"),
    (r"(?:^|/)\.espalier/\.manifest\.write\.lock$", "espalier manifest write lock"),
    # The remaining gitignored .espalier/ runtime files. EXACT-anchored, NOT
    # a broad `.espalier/` glob — freshness.json (BC-039) must keep shipping.
    (r"(?:^|/)\.espalier/\.freshness\.write\.lock$", "espalier freshness write lock"),
    (r"(?:^|/)\.espalier/\.freshness_state_cache\.json$", "espalier freshness state cache"),
    (r"(?:^|/)\.espalier/reasoning_review_log\.jsonl$", "espalier reasoning review log"),
    (r"(?:^|/)\.espalier/memory_candidate_log\.jsonl$", "espalier memory candidate log"),
    (r"(?:^|/)\.claude/settings\.json$", "per-install Claude Code settings"),
    (r"(?:^|/)\.claude/settings\.local\.json$", "per-machine Claude Code settings"),
    (r"(?:^|/)reports/", "per-run generated reports"),
    (r"(?:^|/)cc/blueprints/", "cognitive blueprint state"),
    (r"(?:^|/)bench/results/", "per-run benchmark output"),

    # Build outputs: family-glob, not exact literal. `build[^/]*/` catches
    # `build/`, `build_orig_stale/`, `build2/`, … while still anchoring to a
    # single path segment (no match across `/`) — an exact `build/` pattern
    # would be blind to a stale `build_orig_stale/` mirror.
    (r"(?:^|/)build[^/]*/", "build* directory family"),
    (r"(?:^|/)dist/", "distribution directory"),
    (r"(?:^|/)receiver-test/", "post-install receiver test scratch"),

    # Working notes. A task pack ships from exactly two locations since
    # 2026-09-21 -- directly under `task-packs/` or `task-packs/Deferred/` --
    # so the lookahead carves those out and a `TP-*.md` anywhere else, the
    # landed / merged / scrapped subtrees and an adopter's vendored copy
    # included, stays a working note. Members arrive REPO-RELATIVE: the one
    # production caller (scripts/release_check.py::_archive_member_to_rel)
    # strips the release zip's version directory before asking, so the
    # carve-out is anchored at the root exactly like its two hand-written
    # twins in release_check and tests/test_no_tracked_release_noise.py, and
    # accepts the same `TP-<anything>.md` spelling they do. One pattern, not
    # two: the tuple's length is bound on four surfaces
    # (tests/test_documented_claims.py).
    (r"^(?!task-packs/(?:Deferred/)?TP-[^/]+\.md$)(?:.*/)?TP-[^/]+\.md$",
     "task pack working note"),
    (r"_task_pack\.md$", "task pack working note"),
)


def _compiled() -> list[tuple[re.Pattern[str], str]]:
    return [(re.compile(p), reason) for p, reason in DENIED_PATTERNS]


def find_denied_members(member_paths: Iterable[str]) -> list[tuple[str, str]]:
    """Return ``[(path, reason), ...]`` for any member matching a denied pattern.

    Empty list ⇒ clean archive. Non-empty ⇒ release archive is dirty.

    The matcher normalises Windows-style backslashes to forward slashes
    before checking, and stops at the first pattern that matches each
    member (one reason per offender).
    """
    compiled = _compiled()
    found: list[tuple[str, str]] = []
    for member in member_paths:
        norm = member.replace("\\", "/")
        for regex, reason in compiled:
            if regex.search(norm):
                found.append((member, reason))
                break
    return found


def assert_clean(member_paths: Iterable[str]) -> None:
    """Raise ``ValueError`` if any denied member is present.

    Convenience wrapper for places that want exception flow rather than
    inspecting a return value.
    """
    bad = find_denied_members(member_paths)
    if bad:
        msg = "Release archive contains denied members:\n"
        for path, reason in bad:
            msg += f"  {path}: {reason}\n"
        raise ValueError(msg)
