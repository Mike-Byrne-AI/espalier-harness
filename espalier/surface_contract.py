"""Canonical authority for Espalier-Harness's managed surface.

One module, one source of truth for "what this repo manages". Consumers are
added by Packs 2+ — this module owns the contract, they own the consumption.

Data-first, deterministic, stdlib-only. No network, no subprocesses, no
ambient state beyond the `repo_root: Path` passed in. All returned path
lists are sorted, deduplicated, and forward-slash-normalized.
"""
from __future__ import annotations

import codecs
import errno
import fnmatch
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from espalier._safe_walk import is_own_git_repo
from espalier.release_noise import RELEASE_NOISE_PATTERNS

from espalier._compat import tomllib as _tomllib
from espalier._text import os_error_text


# Download-dupe filename detector.
# Catches Chrome re-download artifacts ("foo (1).md") and macOS Finder
# copy artifacts ("foo copy.md" / "foo copy 2.md"). The bare-trailing-
# number branch was dropped: " <N>.ext" is textually indistinguishable
# from legitimate adopter names ("Python 3.md", "Catch 22.md",
# "COVID 19.csv"), so it false-flagged real docs as transient and dropped
# them from release archives. Shipping one stray "foo 2.txt" re-download
# is strictly less harmful than silently dropping an adopter's "Chapter 7.md".
_DOWNLOAD_DUPE_RE = re.compile(
    r" \(\d+\)(?:\.[^/]*)?$"            # " (1).md" or " (1)"  — browser re-download
    r"| copy(?: \d+)?(?:\.[^/]*)?$",   # " copy.md" / " copy 2.md" — macOS Finder copy
)


def _is_download_dupe(rel_path: str) -> bool:
    """True for browser/OS download or copy duplicates."""
    basename = rel_path.rsplit("/", 1)[-1]
    return _DOWNLOAD_DUPE_RE.search(basename) is not None


# ---------------------------------------------------------------------------
# Static inventories — edited by hand when the contract changes.
# ---------------------------------------------------------------------------

_REQUIRED_INIT_FILES: tuple[str, ...] = (
    "cc/COMMANDS.md",
    "cc/LIVE_SURFACE.md",
    "cc/PACK_MANIFEST.txt",
)

# sister-site: ok canonical wired-hook SoT; the forced hook-side copies (_reinject._CANONICAL_HOOK_SCRIPT_NAMES) and guard subsets pin to this
_CANONICAL_HOOK_SCRIPTS: tuple[str, ...] = (
    "config_guard.py",
    "context_reinject_failure.py",
    "plan_guard.py",
    "post_compact.py",
    "post_write_check.py",
    "reflect_trigger.py",
    "session_start.py",
    "stop_gate.py",
    "subagent_start.py",
    "subagent_stop.py",
    "task_router.py",
    "write_guard.py",
)

_MANAGED_REPORT_PATHS: tuple[str, ...] = (
    "reports/harness_config.json",
    "reports/repo_fingerprint.json",
)

_INTERNAL_PATH_PREFIXES: tuple[str, ...] = (
    "docs/internal/",
)

# sister-site: ok purpose-scoped: don't-SHIP filename vocab, not claim_extractor.EXCLUDED_DOC_GLOBS (don't-AUDIT-as-claim)
_INTERNAL_FILENAME_PATTERNS: tuple[str, ...] = (
    "BLUEPRINT*.md",
    # `blueprint.md` is internal-doc filename vocabulary — a design-proposal name
    # that should never ship. This entry guards an adopter's own `blueprint.md`
    # the same way as the *-atlas.md / TP-*.md vocabulary.
    # Exact-filename, not a case-folded glob, to stay narrow.
    "blueprint.md",
    # ESPALIER_MEMORY.md INTENTIONALLY stays `public` here — it is a shipped managed
    # surface (managed_inventory._PACKAGED_ROOT_DOCS, cc/PACK_MANIFEST.txt). Its
    # real leak vectors are each closed at the right layer: the git-archive
    # "Download ZIP" via .gitattributes export-ignore, the sdist via
    # MANIFEST.in's exclude line, and the wheel by package layout (a repo-root file is
    # outside the `espalier/` package and its package-data globs, so MANIFEST.in
    # has no say over the wheel either way). The bespoke release_pack /
    # build_release_archive builders honor export-ignore through
    # export_ignore_patterns() and matches_export_ignore() in THIS module
    # (pre_release aliases them). Flipping classify to `internal` would cascade
    # through _PACKAGED_ROOT_DOCS, cc/PACK_MANIFEST.txt, self_hosting,
    # test_manifest_truth, test_wheel_payload, and `init`-deploy — all of which
    # model ESPALIER_MEMORY.md as a shipped managed surface — so it stays public
    # by design.
    # The injection/bypass atlases catalogue the harness's own inject + bypass
    # vectors — internal material that must not reach any public release archive
    # (git-archive OR the bespoke release zip).
    "*-atlas.md",
    "TASK_PACK*.md",
    "TP-*.md",
    "docs/session-archive.md",
    # Release-engineering provenance: the finding->commit ledger for the pre-OSS
    # sprint. Internal historical narrative full of dev-vocab + dead-hash notes —
    # same not-shipped class as session-archive above. Sister-sites:
    # claim_extractor.EXCLUDED_DOC_GLOBS, MANIFEST.in exclude, .gitattributes
    # export-ignore, test_git_archive_parity EXPORT_IGNORED_INTERNAL_DOCS (it is
    # TRACKED, like REDEFINED below).
    "docs/RELEASE_FINDINGS_LEDGER.md",
    # Pure internal contract-shorthand (dev vocabulary, zero adopter value). It is
    # TRACKED, so it leaked into `git archive` (closed by a .gitattributes
    # export-ignore) AND the bespoke release zip, whose walker keys off
    # classify_release_path — classifying it `internal` here closes that second
    # vector. MANIFEST.in already excludes it from the sdist. The parity test in
    # test_git_archive_parity now binds every such exclude.
    "docs/REDEFINED_INFORMATION_REGISTRY.md",
    # The two release-engineering docs, 2026-08-13. Maintainer ritual naming the
    # operator's own accounts and one-time pre-flip sequence; an adopter never
    # receives either (neither is in managed_inventory._SEED_DOC_REL_PATHS nor
    # espalier/assets/docs/), so this closes the three surfaces that still
    # carried them: the bespoke release zip (here), the sdist (MANIFEST.in --
    # `recursive-include docs *.md` is not classify-derived), and `git archive`
    # / "Download ZIP" (.gitattributes).
    #
    # SPLIT ON THE claim_extractor SITE of the sister-site footprint
    # (docs/SHARP_EDGES.md), and the split is the point:
    #   RELEASE_DECISIONS  -> IS in claim_extractor.EXCLUDED_DOC_GLOBS +
    #     FROZEN_RECORD_DOCS. A chronological decision log is point-in-time
    #     narrative; auditing its historical counts as live claims is the
    #     category error test_doc_maintenance_classes.py:8-11 names.
    #   RELEASE_CHECKLIST  -> deliberately NOT excluded from claim extraction.
    #     It is a PROCEDURE someone executes, not a record of one. Its numbers
    #     are live and must keep drifting-red; it stays in
    #     _PUBLIC_DOC_RELPATHS (AUDITED) and leaves only the derived INDEXED
    #     set. Not shipping a doc is not a reason to stop checking it.
    "docs/RELEASE_CHECKLIST.md",
    "docs/RELEASE_DECISIONS.md",
    # The one-way-door publish memo: maintainer-only, export-ignored and
    # registered in test_git_archive_parity, yet `public` here -- so
    # MANIFEST.in's `recursive-include memory *.md` shipped it in every sdist
    # (measured 2026-09-21 as a release-listing check). `internal` and the
    # MANIFEST exclude land together: the co-required pair in
    # docs/SHARP_EDGES.md "A tracked internal doc needs a sister-site footprint".
    "memory/publish-from-a-generated-public-repo.md",
)


_LOCAL_ONLY_PATHS: tuple[str, ...] = (
    # Per-install runtime artifacts generated by `espalier init`
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/scheduled_tasks.lock",
    ".espalier/integrity.json",
    # write_manifest flock sentinel. Created by every `espalier integrity refresh`
    # invocation; not a release artifact.
    ".espalier/.manifest.write.lock",
    # The remaining gitignored .espalier/ runtime files. EXACT entries — never a
    # `.espalier/` prefix: `.espalier/freshness.json` is COMMITTED and intended
    # public (BC-039); a prefix would strip it.
    ".espalier/.freshness.write.lock",
    # The derived freshness state_cache, relocated OUT of the committed manifest
    # so a `freshness check` never dirties the tracked tree. Per-install read-perf
    # cache regenerated by any `freshness check`; never a release artifact. EXACT
    # entry (sibling of the lock line above).
    ".espalier/.freshness_state_cache.json",
    ".espalier/reasoning_review_log.jsonl",
    # /reflect memory-promotion disposition log. Per-operator rolling history;
    # gitignored, never a release artifact (sibling of the line above).
    ".espalier/memory_candidate_log.jsonl",
    # Per-session local state
    "cc/execution_plan.json",
    "cc/BLUEPRINT_HANDOFF.md",
    "cc/SURFACE_HANDOFF.md",
    # Per-operator fan-out finding ledger (rolling JSONL; gitignored, never a
    # release artifact — sibling of the .espalier/*.jsonl rolling logs above).
    # EXACT entry, never a `cc/` prefix: cc/ carries committed PUBLIC surfaces
    # (cc/COMMANDS.md, cc/LIVE_SURFACE.md, cc/PACK_MANIFEST.txt).
    "cc/finding_ledger.jsonl",
    # Local goal/progress snapshot (gitignored; refreshed at /handoff, surfaced
    # at SessionStart). Defense-in-depth so a future re-tracking can't ship
    # espalier's OWN goal doc into an adopter release. EXACT entry, never a
    # `cc/` prefix (cc/ carries committed PUBLIC surfaces).
    "cc/GOAL.md",
    "reports/analysis.json",
    "reports/cc_surface_gate.json",
    # Internal release planning doc that lived in repo root. Gitignored; this
    # entry is defense-in-depth so a future re-tracking can't ship it via the
    # release archive.
    "CONSOLIDATED_RELEASE_PLAN.md",
    # The codename gate's local pattern arm (DEF-708): the operator's own
    # regexes for terms the public repo must not carry, read by
    # tests/test_no_internal_codenames.py and gitignored so a sensitive name
    # never enters the tracked denylist. Classified `public` until 2026-09-21,
    # and the archive builder's no-index fallback walks the tree, so a copy
    # taken without `.git/` would have shipped the very list the arm exists to
    # keep off every surface. EXACT root entry, sibling of the line above.
    ".local-codenames.txt",
)

# Prefix-matched local-only roots. A path is local-only if its
# normalized form starts with any of these prefixes. Captures generated
# state, per-session artifacts, and experimental surfaces that belong
# in source control for development but not in the public release.
_LOCAL_ONLY_PREFIXES: tuple[str, ...] = (
    # Per-session cognitive blueprints (gitignored)
    "cc/blueprints/",
    # Per-install harness reports (gitignored; regenerated by init)
    "reports/",
    # Timestamped benchmark runtime artifacts (gitignored)
    "bench/results/",
    "bench/end_to_end/runs/",
    # Local archive directories
    "zDone/",
    "Finished Tasks/",
    # Local developer experiment fixtures (untracked)
    "receiver-test/",
    # The task-pack folder, FAIL-CLOSED: everything under it is local-only
    # except the ship set that `is_local_only` carves out by name -- the forward
    # ledger, its probes file, the router (SHIPPED_TASK_PACK_FILES) and the
    # packs directly under task-packs/ and task-packs/Deferred/
    # (is_shipped_pack), tracked and public since 2026-09-21. The landed, merged
    # and scrapped packs, the dated archive files, a findings JSON, a stray
    # note: all stay here, untracked, on the record branch, out of every
    # archive, with nothing to remember when a new one appears. A findings JSON
    # once carried a private home-dir path and classified `public` while only
    # the `.md` packs had a rule; this prefix is what closed that class, and the
    # carve-out is an exact allow-list so it stays closed. NOT a prune-dir any
    # more: the fallback walker must descend to find the ledger, so
    # get_release_excluded_prefixes leaves this one out and the per-file
    # classify decides (tests/test_release_archive_class_regression.py pins
    # both halves). Sister walls, each independently written: .gitignore (the
    # same allow-list), .gitattributes (export-ignore per subtree and family --
    # git offers no re-include for a pruned directory) and
    # scripts/release_check.py's tracked-noise patterns.
    "task-packs/",
    # Underscore-prefixed cc/ review scratch (gitignored: `cc/_pack_review_*`,
    # `cc/_recall_engine_review*`). cc/'s ONLY public surfaces are the explicit
    # COMMANDS.md / LIVE_SURFACE.md / PACK_MANIFEST.txt allowlist; everything
    # underscore-prefixed under cc/ is local review work product. Same bespoke-
    # walker leak class as task-packs/. Non-slash prefix: `is_local_only` matches
    # it via `startswith`; it is not a prune-dir (the per-file classify excludes
    # each one), and no `cc/_*` file is git-tracked.
    "cc/_",
    # Harness-dev fan-out review scaffolds (`.claude/workflows/*.js`). Unlike the
    # gitignored entries above these are git-TRACKED for transparency, but they
    # are internal review tooling — full of dev vocabulary and "adversarially
    # re-attack" prompts — with zero adopter value. They already classify
    # `internal` for the FUSION OVERLAY (fusion_manifest.HARNESS_EXCLUDE +
    # test_fuse), but the release-zip and `git archive` sister-sites were missed.
    # Excluded prefix → the fallback walker prunes the dir; the parallel
    # `.claude/workflows/ export-ignore` in .gitattributes covers `git archive`
    # (the "every shipped surface" class).
    ".claude/workflows/",
)

# Non-hook exact-match paths. The tools/cc/hooks/ portion is DERIVED from the
# managed_inventory entry+helper SoT (see _hook_protected_files below) so the
# protected lists cannot drift from what `init` actually deploys.
# sister-site: ok purpose-scoped: engine mutation-SoT non-hook slice (membership deliberately differs from the CI gate set)
_PROTECTED_MUTATION_NONHOOK: tuple[str, ...] = (
    ".espalier/integrity.json",
    # The hook `_protected_zones.PROTECTED_FILES` already guards this; the engine
    # SoT omitted it. Reverse-parity (engine ⊇ hook) is now asserted in
    # tests/test_contract_consumers.py.
    ".espalier/freshness.json",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".github/workflows/harness-guard.yml",
    "tools/cc/ci_guard.py",
)

_PROTECTED_INTEGRITY_NONHOOK: tuple[str, ...] = (
    ".github/workflows/harness-guard.yml",
    # _integrity.py hard-imports tools/cc/_json_safe.py (the JSON decode
    # chokepoint it uses to read settings/manifests). Tampering it could subvert
    # the integrity check itself, yet it was absent from the manifest.
    "tools/cc/_json_safe.py",
    "tools/cc/ci_guard.py",
)

# _denial_reasons.py is integrity-tracked but intentionally NOT a write_guard
# mutation-deny exact file (it is covered by the tools/cc/hooks/ PREFIX at
# runtime). Encode the divergence as an explicit subtraction with this why.
_MUTATION_HOOK_OMISSIONS: frozenset[str] = frozenset({"tools/cc/hooks/_denial_reasons.py"})


def _hook_protected_files() -> tuple[str, ...]:
    """tools/cc/hooks/ entry + helper files, sourced from the managed_inventory SoT.

    Lazy import (NOT top-level): managed_inventory imports surface_contract at
    module load (managed_inventory.py:30), so a top-level import here would be a
    reverse edge and a cycle. Importing inside the call — which only runs after
    both modules are fully defined — is cycle-safe. get_hook_entry_files itself
    derives from surface_contract.get_canonical_hook_scripts, so this closes the
    loop on the SoT without a structural import dependency.
    """
    from espalier import managed_inventory  # lazy — cycle-safe, see docstring
    return tuple(managed_inventory.get_hook_entry_files()) + tuple(
        managed_inventory.get_hook_helper_files()
    )

# Paths whose CI-side modification requires the HARNESS-UPDATE-APPROVED marker.
# sister-site: ok purpose-scoped: CI approval-marker gate slice (membership deliberately differs from the mutation set)
_PROTECTED_CI_FILES: tuple[str, ...] = (
    ".espalier/integrity.json",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".github/workflows/harness-guard.yml",
    "tools/cc/ci_guard.py",
)

_PROTECTED_CI_PREFIXES: tuple[str, ...] = (
    # All hook scripts and helper modules — substantive harness logic.
    "tools/cc/hooks/",
    # All GitHub Actions workflows — releases, CI, refresh-externals,
    # benchmark, end-to-end-bench. Workflow mutation can change release
    # or test enforcement, so changes require HARNESS-UPDATE-APPROVED.
    # Mirrors tools/cc/ci_guard.py::PROTECTED_PREFIXES.
    ".github/workflows/",
)


def _sorted_tuple(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(items)))


# ---------------------------------------------------------------------------
# Static inventory accessors
# ---------------------------------------------------------------------------


def get_required_init_files() -> tuple[str, ...]:
    return _sorted_tuple(_REQUIRED_INIT_FILES)


def get_canonical_hook_scripts() -> tuple[str, ...]:
    return _sorted_tuple(_CANONICAL_HOOK_SCRIPTS)


def get_managed_report_paths() -> tuple[str, ...]:
    return _sorted_tuple(_MANAGED_REPORT_PATHS)


def get_internal_path_prefixes() -> tuple[str, ...]:
    return _sorted_tuple(_INTERNAL_PATH_PREFIXES)


def get_internal_filename_patterns() -> tuple[str, ...]:
    return _sorted_tuple(_INTERNAL_FILENAME_PATTERNS)


def get_transient_path_patterns() -> tuple[str, ...]:
    return _sorted_tuple(RELEASE_NOISE_PATTERNS)


def get_local_only_paths() -> tuple[str, ...]:
    return _sorted_tuple(_LOCAL_ONLY_PATHS)


def get_public_release_exclusions() -> tuple[str, ...]:
    """Path classes excluded from a public release artifact, minus the local-only prefix subtrees (``_LOCAL_ONLY_PREFIXES``) — those live in ``get_release_excluded_prefixes``."""
    return _sorted_tuple(
        list(_INTERNAL_PATH_PREFIXES)
        + list(_INTERNAL_FILENAME_PATTERNS)
        + list(RELEASE_NOISE_PATTERNS)
        + list(_LOCAL_ONLY_PATHS)
    )


def get_protected_mutation_paths() -> tuple[str, ...]:
    """Exact paths the write_guard and related hooks deny mutation on."""
    hooks = (p for p in _hook_protected_files() if p not in _MUTATION_HOOK_OMISSIONS)
    return _sorted_tuple(list(_PROTECTED_MUTATION_NONHOOK) + list(hooks))


def get_protected_mutation_prefixes() -> tuple[str, ...]:
    """Directory prefixes the write_guard denies mutation on (repo-relative).

    ``.github/workflows/`` is in the hook-side ``PROTECTED_PREFIXES``
    (in tools/cc/hooks/_protected_zones.py) and is mirrored here in the engine-side SoT. The
    hook-side covers it via prefix at runtime; consumers of the engine-side
    contract (e.g., docs generators) need it here so they do not under-report
    what's actually protected. The hook side enumerates ``harness-guard.yml`` as
    an exact-match in PROTECTED_FILES while the other workflows
    (release.yml, refresh-externals.yml, benchmark.yml) are protected by
    prefix only.
    """
    return _sorted_tuple((
        "espalier/", "cc/", "tools/cc/", ".github/workflows/",
    ))


def get_protected_integrity_paths() -> tuple[str, ...]:
    """Files covered by the committed integrity manifest."""
    return _sorted_tuple(
        list(_PROTECTED_INTEGRITY_NONHOOK) + list(_hook_protected_files())
    )


def get_protected_ci_files() -> tuple[str, ...]:
    """Exact paths whose CI-tracked change requires the approval marker."""
    return _sorted_tuple(_PROTECTED_CI_FILES)


def get_protected_ci_prefixes() -> tuple[str, ...]:
    """Directory prefixes whose CI-tracked change requires the approval marker."""
    return _sorted_tuple(_PROTECTED_CI_PREFIXES)


def is_protected_from_ci(rel_path: str) -> bool:
    """True if `rel_path` requires the HARNESS-UPDATE-APPROVED marker on CI."""
    p = _normalize(rel_path)
    if p in _PROTECTED_CI_FILES:
        return True
    for prefix in _PROTECTED_CI_PREFIXES:
        if p.startswith(prefix):
            return True
    return False


# ---------------------------------------------------------------------------
# Classifiers — pure functions over forward-slash relative paths.
# ---------------------------------------------------------------------------


def _normalize(rel_path: str) -> str:
    """Normalize a relative path for prefix/exact-match comparison.

    Handles two real-world variants the classifiers must agree on:
    - Windows backslash separators (``cc\\blueprints\\x.json``).
    - A leading ``./`` from ``Path.relative_to`` / ``os.path.relpath``
      results that include the current-dir component.

    Without the ``./`` strip, callers like
    ``classify_release_path("./reports/x.json")`` would return ``public``
    instead of ``local_only`` because ``startswith("reports/")`` fails
    on the dotted prefix. The two production callers (release archive
    archive builder + release_check scanner) already strip this, but the public
    predicates ``is_release_included`` / ``is_release_excluded`` accept any
    caller's path shape and must defend the contract.
    """
    p = rel_path.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def is_internal_path_prefix(rel_path: str) -> bool:
    """True if `rel_path` falls under an internal path prefix (e.g.
    ``docs/internal/``).

    This is the prefix arm of :func:`is_internal_release_leak`. It is the only
    arm that is meaningful on an ADOPTER tree: the filename-pattern arm
    (``*-atlas.md``, ``TP-*.md``, ``blueprint.md``) encodes Espalier-Harness's
    OWN internal-doc naming conventions, which an adopter's like-named files do
    not share — so `_find_internal_leaks` gates that arm behind self-host.
    """
    p = _normalize(rel_path)
    for prefix in _INTERNAL_PATH_PREFIXES:
        stripped = prefix.rstrip("/")
        if p == stripped or p.startswith(prefix):
            return True
    return False


def tracked_paths(repo_root: Path) -> set[str] | None:
    """Repo-relative paths in ``repo_root``'s git INDEX -- the enumeration both
    archive builders (``espalier/release_pack.py`` and
    ``scripts/build_release_archive.py``) ship from.

    The index, not ``git archive``: ``classify_release_path`` marks
    ``ESPALIER_MEMORY.md`` public while ``.gitattributes`` export-ignores it, so
    an archive-driven enumeration would drop a shipped surface (the builders
    honour export-ignore themselves). And the index, not the working tree: the
    tree walk shipped whatever was lying in the maintainer's checkout -- first
    ``cc/discard_snapshots.log``, gitignored, carrying an absolute home
    directory and recorded shell commands (closed by filtering on git's ignore
    set), then any untracked file that was NOT gitignored and classified public
    -- the gap that filter left. A file git does not track never enters the
    archive now, whatever it classifies as; a tracked file still goes through
    the contract.

    ``None`` when there is no index to ask, and the caller falls back to
    walking the working tree, with only the release-noise patterns between an
    untracked file and the archive. Two shapes return it, and they differ:
    a root that is not a repository at all (a plain directory, the release
    matrix's extracted archive) has no index to miss -- the tree walk is the
    whole truth there, and this returns quietly; a root that OWNS a ``.git``
    git could not answer for (git absent from PATH, dubious ownership, a
    moved gitdir) is a degraded build, said on stderr rather than discovered
    in a published archive -- and the gates (``pre_release``, ``release_check``,
    the ``release-pack`` verb) refuse that shape outright, because a WARN is
    not something a gate reads. One subprocess for the whole tree; this
    lives beside the classifier both builders already route through, so the
    two do not carry the same subprocess twice -- **any new archive builder
    must call it.**

    Not the test oracle. ``tests/_git_oracle.require_tracked_paths`` refuses
    (raises) where this falls back, and a test that needs a population must
    use that one; this helper exists for builders that have a working tree to
    fall back to.
    """
    # `git ls-files` walks UP to the enclosing repository. An extracted release
    # archive sits inside this repo's gitignored `dist/`, so querying it that way
    # answers about the PARENT -- the wrong index entirely (with the ignore set,
    # every extracted file read as ignored, which emptied the archive and failed
    # the matrix's own release_check). Only trust the answer when `repo_root` is
    # the root of its own repository.
    if not is_own_git_repo(repo_root):
        return None
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "-z"],
            cwd=str(repo_root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120, check=False,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError) as exc:
        # errors="replace" above: a tracked name git prints in bytes UTF-8
        # refuses (a latin-1 filename on ext4) used to make this whole answer
        # None -- one unnameable file read the entire tree as untracked. Now
        # the set is complete and only that path carries a replacement
        # character, so it alone misses (DEF-821). The UnicodeDecodeError arm
        # stays as the belt beside the braces.
        _warn_no_index(repo_root, f"{type(exc).__name__}: {os_error_text(exc)}")
        return None
    if result.returncode != 0:
        _warn_no_index(repo_root, f"`git ls-files` failed (rc={result.returncode})")
        return None
    return {p for p in result.stdout.split("\0") if p}


def _warn_no_index(repo_root: Path, why: str) -> None:
    print(
        f"[WARN] surface_contract: no git index to enumerate at {repo_root} "
        f"({why}); the release archive is built from the working tree, so "
        f"untracked local state is filtered only by the release-noise patterns.",
        file=sys.stderr,
    )


def export_ignore_patterns(repo_root: Path) -> list[str]:
    """``export-ignore`` patterns from ``.gitattributes`` — files git omits
    from ``git archive`` (the public Download-ZIP / source-archive surface).

    Hoisted here from ``pre_release`` so the bespoke release-zip builders
    (``release_pack``, ``scripts/build_release_archive``) can reuse it
    without a ``release_pack``↔``pre_release`` import cycle. Parsing the file
    directly (not calling git) keeps it self-contained and lets tmp-repo tests
    opt in/out by the file's presence.
    """
    ga = repo_root / ".gitattributes"
    if not ga.is_file():
        return []
    patterns: list[str] = []
    for raw in ga.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) >= 2 and "export-ignore" in fields[1:]:
            patterns.append(fields[0])
    return patterns


def _match_path_segments(candidate: str, pattern: str) -> bool:
    """Path-anchored glob where ``*`` and ``?`` never cross a ``/``.

    :func:`fnmatch.fnmatch` treats the whole string as one blob, so its ``*``
    happily spans separators — ``memory/*-atlas.md`` would match
    ``memory/sub/y-atlas.md``, which git does NOT prune. Matching segment by
    segment reproduces git's rule. ``**`` is deliberately not implemented; no
    live pattern uses it and
    ``test_live_gitattributes_uses_no_unsupported_double_star`` reds if one
    appears.
    """
    cand_parts = candidate.split("/")
    pat_parts = pattern.split("/")
    if len(cand_parts) != len(pat_parts):
        return False
    return all(fnmatch.fnmatch(c, p) for c, p in zip(cand_parts, pat_parts))


def matches_export_ignore(rel: str, pattern: str) -> bool:
    """True if git would apply ``export-ignore`` to ``rel`` under ``pattern``.

    Implements the three rules that matter, each measured by driving ``git
    archive --worktree-attributes`` rather than read off ``gitattributes(5)``:

    1. **Anchoring.** A LEADING ``/``, or a separator in the MIDDLE, anchors the
       pattern to the repo root. A separator that is only TRAILING does not —
       ``task-packs/`` matches a directory of that name at *any* depth, while
       ``/task-packs/`` matches only the top-level one.
    2. **Directory inheritance.** ``export-ignore`` on a directory prunes its
       whole subtree, so a path matches if the pattern matches the path itself
       *or any of its ancestor directories*. This holds with or without a
       trailing slash — a bare ``task-packs`` prunes the subtree too.
    3. **Segment-bounded globs.** ``*`` does not cross ``/`` (see
       :func:`_match_path_segments`).

    Rule 1 is the one this function got backwards for its whole life, in both
    directions: it read an unanchored ``task-packs/`` as root-anchored (so a
    genuinely pruned package asset looked safe) and an anchored ``/task-packs/``
    as matching nothing at all. Every model-based check asked this function and
    was told the wrong thing while git quietly dropped
    ``espalier/assets/task-packs/CLAUDE.md`` — a file ``espalier init`` needs —
    from the archive. A model of the artifact is not the artifact; see
    ``docs/sharp-edges/source-tree-is-not-an-artifact-oracle.md``.
    """
    core = pattern.strip("/")
    if not core:
        return False
    # Separator at the START or MIDDLE anchors; a trailing one does not.
    anchored = pattern.startswith("/") or "/" in core
    parts = [p for p in _normalize(rel).split("/") if p]
    for depth in range(1, len(parts) + 1):
        if anchored:
            # Compare the leading `depth` segments — this is `rel` itself at
            # the last iteration and an ancestor directory before that.
            if _match_path_segments("/".join(parts[:depth]), core):
                return True
        elif fnmatch.fnmatch(parts[depth - 1], core):
            return True
    return False


# The ship set under task-packs/ (2026-09-21), carved out of the folder's
# local-only prefix by NAME: an allow-list, so a file nobody named stays
# local-only. The router was tracked-but-export-ignored before; it ships now
# because the ledger it routes to does.
SHIPPED_TASK_PACK_FILES: tuple[str, ...] = (
    "task-packs/CLAUDE.md",
    "task-packs/FORWARD_LEDGER.md",
    "task-packs/LEDGER_PROBES.json",
)
# The two locations whose packs SHIP: a `TP-*.md` directly under `task-packs/`
# (active) or `task-packs/Deferred/` (drafted and held). Everything else a pack
# can be -- landed in `Done/`, folded in `Merged/`, abandoned in `Scrapped/`, or
# a stray at the repo root -- stays internal. Exact PARENT match, never a
# prefix: a pack one level deeper under Deferred/ is not in a shipped location,
# and neither is an adopter's `src/vendor/task-packs/`.
SHIPPED_PACK_DIRS: tuple[str, ...] = ("task-packs", "task-packs/Deferred")
_PACK_FILENAME_PATTERN = "TP-*.md"
# The one local-only prefix whose subtree is NOT wholesale: `is_local_only`
# carves the ship set out of it, and `get_release_excluded_prefixes` leaves it
# off the walkers' prune list for the same reason.
_CARVED_OUT_PREFIX = "task-packs/"


def is_shipped_pack(rel_path: str) -> bool:
    """True if ``rel_path`` is a task pack in one of :data:`SHIPPED_PACK_DIRS`.

    The one predicate for "is this a plan that ships". The classifier exempts
    such a file from the ``TP-*.md`` internal-filename arm and from the
    ``task-packs/`` local-only prefix, and the tree-wide prose gates
    (``tests/test_catalog_self_consistency.py``,
    ``tests/test_doc_source_citations.py``) import it to keep dated plans out of
    populations built for live documentation -- a pack cites the files it
    proposes to create and the line it measured at authoring, and its own
    Affected-symbols walk (scope-check) re-derives both at execution. One
    function, imported, never re-typed.
    """
    p = _normalize(rel_path)
    parent, _, name = p.rpartition("/")
    # fnmatchcase, not fnmatch: the answer must not depend on the platform's
    # case folding. On a case-insensitive checkout git's own `!task-packs/TP-*.md`
    # re-includes a pack typed in lower case while this says no; the two derived
    # gates (every tracked path under the folder is in the ship set; no
    # local-only path reaches the archive) report that disagreement instead of
    # one wall silently shipping what the other silently drops.
    return parent in SHIPPED_PACK_DIRS and fnmatch.fnmatchcase(name, _PACK_FILENAME_PATTERN)


def is_shipped_task_pack_surface(rel_path: str) -> bool:
    """True if ``rel_path`` is any member of the task-pack ship set: one of
    :data:`SHIPPED_TASK_PACK_FILES` or a pack :func:`is_shipped_pack` accepts."""
    p = _normalize(rel_path)
    return p in SHIPPED_TASK_PACK_FILES or is_shipped_pack(p)


def is_internal_release_leak(rel_path: str) -> bool:
    """True if `rel_path` is internal and must not ship in a public release."""
    p = _normalize(rel_path)
    if is_internal_path_prefix(p):
        return True
    # A shipped pack ships by decision, whatever its basename says: the filename
    # arms below encode the harness's own internal-doc naming vocabulary, and a
    # pack whose name carries the atlas suffix would otherwise fail closed with
    # the archive gate's "add an export-ignore row" remedy, which is the wrong one.
    if is_shipped_pack(p):
        return False
    basename = Path(p).name
    for pattern in _INTERNAL_FILENAME_PATTERNS:
        if "/" in pattern:
            if p == pattern:
                return True
        elif fnmatch.fnmatch(basename, pattern):
            return True
    return False


def is_transient(rel_path: str) -> bool:
    """True if `rel_path` is a build/cache/junk path never worth shipping."""
    p = _normalize(rel_path)
    if not p:
        return False
    # Catch browser/OS download dupes before pattern matching.
    # These shapes are not expressible as fnmatch patterns over path parts.
    if _is_download_dupe(p):
        return True
    parts = p.split("/")
    for pattern in RELEASE_NOISE_PATTERNS:
        marker = pattern.rstrip("/")
        # A DIRECTORY pattern (trailing slash, e.g. `build*/`) must
        # match only directory components — never the final filename. Otherwise a
        # FILE whose name happens to glob the pattern is wrongly excluded: the
        # release builder `scripts/build_release_archive.py` matched `build*` and
        # excluded itself while its sibling `scripts/release_check.py` shipped.
        # A path is transient iff it LIVES UNDER such a dir, so test the dir
        # components (parts[:-1]). FILE patterns (no trailing slash, e.g. *.zip)
        # still match any component including the filename.
        candidates = parts[:-1] if pattern.endswith("/") else parts
        for part in candidates:
            if part and fnmatch.fnmatch(part, marker):
                return True
    return False


# Private-cert / keystore family. Homed on the LOCAL-ONLY arm deliberately: a
# key material file in the working tree is per-machine state that must never
# leave the machine, which is exactly what `local_only` means to every consumer
# (`release_pack` skips it, `pre_release` scans for it). Nothing DELETES on this
# predicate — `cleanup.py` drives its own `_LOCAL_RUNTIME_REL_PATHS` tuple — so
# classifying an operator's key here cannot cost them the file.
#
# Rejected alternative: a fifth `"secret"` bucket in `classify_release_path`.
# More precise, but it widens a public function's return domain and every
# consumer that switches on the bucket string, to say something the operator
# already learns from the denylist's own reason text ("PEM private key").
# The exact-negation contract (is_public_release_allowed <-> bucket == "public")
# stays green for free this way, because both read the same three predicates.
_SECRET_SUFFIX_RE = re.compile(r"\.(?:pem|key|p12|pfx)$", re.IGNORECASE)


def is_local_only(rel_path: str) -> bool:
    """True if `rel_path` is local-only state (or a per-session/experimental
    prefix). Exact-file match plus prefix match against
    ``_LOCAL_ONLY_PREFIXES`` so generated state under ``reports/`` and
    blueprints under ``cc/blueprints/`` are caught uniformly. Private-key /
    keystore suffixes are included — see ``_SECRET_SUFFIX_RE``.
    """
    p = _normalize(rel_path)
    if p in _LOCAL_ONLY_PATHS:
        return True
    # A `<x>.lock` sentinel inherits `<x>`'s classification. _LOCAL_ONLY_PATHS is
    # deliberately exact-match (a `cc/` or `.espalier/` prefix would strip
    # committed public surfaces), so its lock entries were enumerated one at a
    # time -- and the fourth was missed: `cc/execution_plan.json` was local-only
    # while `cc/execution_plan.json.lock` classified public and SHIPPED. Deriving
    # from the base closes that gap for every future sentinel at once.
    #
    # NOT a blanket `*.lock` rule, which would be wrong on an adopter repo:
    # `poetry.lock` / `Cargo.lock` / `package-lock.json` are shipped artifacts,
    # and their bases carry no local-only entry, so they stay public.
    if p.endswith(".lock") and p[: -len(".lock")] in _LOCAL_ONLY_PATHS:
        return True
    for prefix in _LOCAL_ONLY_PREFIXES:
        if p == prefix.rstrip("/") or p.startswith(prefix):
            # The task-pack folder is local-only with a NAMED carve-out (the
            # ship set, 2026-09-21); every other prefix is wholesale.
            if prefix == _CARVED_OUT_PREFIX and is_shipped_task_pack_surface(p):
                continue
            return True
    if _SECRET_SUFFIX_RE.search(p):
        return True
    return False


def is_public_release_allowed(rel_path: str) -> bool:
    p = _normalize(rel_path)
    return not (is_internal_release_leak(p) or is_transient(p) or is_local_only(p))


# Paths deployed code CREATES on the adopter's own tree.
#
# This is a different question from `is_local_only`, and conflating the two
# shipped a real defect. `is_local_only` answers *"must this never ship?"* —
# it is satisfied by `cc/GOAL.md`, whose entry exists as defense-in-depth so a
# future re-tracking cannot leak espalier's OWN goal doc into a release.
# Nothing creates a `cc/GOAL.md` on an adopter's tree. A consumer that reads
# `is_local_only` and concludes "the harness writes this later, so a pointer
# at it is safe" is reading the adjacent answer: it exempted a banner line
# that PRINTS `cc/GOAL.md` at a reader who will never have the file.
#
# Membership requires a creating call, cited and verified. Not "it is
# gitignored", not "it is local-only" — a line of deployed code that writes
# the path. Anything without one is not a member, which is exactly how
# `cc/GOAL.md` falls out.
ADOPTER_RUNTIME_GENERATED: tuple[str, ...] = (
    # Rewritten at every compaction by the deployed PostCompact hook:
    # `tools/cc/hooks/post_compact.py` builds `root / "cc" /
    # "_working_summary.md"` and calls `_hook_utils.atomic_write_text(live, …)`.
    "cc/_working_summary.md",
    # Written by `espalier strengthen`: `espalier/cli.py` calls
    # `atomic_write_text(reports_dir / "strengthen_report.md", …)`.
    "reports/strengthen_report.md",
    # Its JSON twin, from the same `cmd_strengthen` write pair
    # (`reports_dir / "strengthen_report.json"`).
    "reports/strengthen_report.json",
    # Written by the deployed plan tool: `tools/cc/execution_plan.py`
    # resolves `_repo_root() / "cc" / "execution_plan.json"` and `create`
    # writes it through `atomic_write_text`.
    "cc/execution_plan.json",
    # Written by `espalier freshness discover` / `pin`: `espalier/cli.py`
    # builds `repo_root / ".espalier" / "freshness.json"` and writes the
    # manifest there; the scanner (`scanners/freshness.py::MANIFEST_REL_PATH`)
    # reads it back.
    ".espalier/freshness.json",
    # The state cache beside the manifest: `espalier/freshness.py` names it
    # (`_STATE_CACHE_REL`) and rewrites it on every `freshness check`.
    ".espalier/.freshness_state_cache.json",
    # Parked by `espalier install-ci` when the host already tracks a
    # differing workflow: `cli.cmd_install_ci` writes
    # `workflow_dst.with_name(workflow_dst.name + ".new")` and warns. This
    # tuple has a second reader -- `managed_inventory.local_state_on_disk`,
    # the uninstall accounting -- so this entry is also what makes a parked
    # `.new` twin show up as runtime state the uninstall leaves behind.
    ".github/workflows/harness-guard.yml.new",
)


def is_adopter_runtime_generated(rel_path: str) -> bool:
    """True if deployed code creates ``rel_path`` on the adopter's tree.

    Use this — never ``is_local_only`` — to decide whether a pointer at a
    not-yet-existing file is safe. See ``ADOPTER_RUNTIME_GENERATED`` for why
    the two are not interchangeable.
    """
    return _normalize(rel_path) in ADOPTER_RUNTIME_GENERATED


# ---------------------------------------------------------------------------
# Release archive classifier — labeled bucket for callers that need
# more than a boolean. Build scripts and the release_check archive scanner
# both consume this so they cannot drift.
# ---------------------------------------------------------------------------


def classify_release_path(rel_path: str) -> str:
    """Return the release-archive bucket for ``rel_path``.

    Returns one of:
    - ``"public"``    — included in the public release archive
    - ``"internal"``  — internal planning/blueprint material, excluded
    - ``"transient"`` — caches, build outputs, junk; never shipped
    - ``"local_only"`` — local-only / per-session / experimental;
      excluded (covers ``reports/``, ``cc/blueprints/``,
      ``settings.local.json``, etc.)

    The buckets are checked in priority order matching ``is_public_release_allowed``
    so callers that need only a boolean keep the same answer.
    """
    p = _normalize(rel_path)
    if is_internal_release_leak(p):
        return "internal"
    if is_transient(p):
        return "transient"
    if is_local_only(p):
        return "local_only"
    return "public"


def is_release_included(rel_path: str) -> bool:
    """True iff ``rel_path`` is in the ``public`` release bucket.

    Thin convenience wrapper over :func:`classify_release_path` for callers
    that only need a boolean.
    """
    return classify_release_path(rel_path) == "public"


def is_release_excluded(rel_path: str) -> bool:
    """True iff ``rel_path`` is excluded from the public release archive.

    Negation of :func:`is_release_included`. Provided so build scripts can
    write the negative case without double-negation noise.
    """
    return classify_release_path(rel_path) != "public"


def get_release_excluded_prefixes() -> tuple[str, ...]:
    """All directory prefixes that route WHOLESALE to a non-public bucket.

    Useful for build scripts that want to prune entire subtrees during
    a directory walk rather than checking every file. A prefix with a named
    carve-out (``_CARVED_OUT_PREFIX``) is deliberately absent: pruning it
    would drop the ship set it carves out, so the walkers descend and the
    per-file classifier decides there.
    """
    return _sorted_tuple(
        list(_INTERNAL_PATH_PREFIXES)
        + [p for p in _LOCAL_ONLY_PREFIXES if p != _CARVED_OUT_PREFIX]
        # Transient patterns ending with `/` are also directory prefixes.
        + [p for p in RELEASE_NOISE_PATTERNS if p.endswith("/")]
    )


# ---------------------------------------------------------------------------
# Discovery functions — read-only inspection of a repo_root.
# ---------------------------------------------------------------------------


def _strip_project_dir_prefix(script: str) -> str:
    for prefix in ("$CLAUDE_PROJECT_DIR/", "${CLAUDE_PROJECT_DIR}/"):
        if script.startswith(prefix):
            return script[len(prefix) :]
    return script


def _extract_script_path(command: str) -> str | None:
    """Pull the trailing `.py` script path out of a hook command string."""
    tokens: list[str] = []
    i = 0
    while i < len(command):
        c = command[i]
        if c == '"':
            end = command.find('"', i + 1)
            if end == -1:
                break
            tokens.append(command[i + 1 : end])
            i = end + 1
        elif c.isspace():
            i += 1
        else:
            j = i
            while j < len(command) and not command[j].isspace():
                j += 1
            tokens.append(command[i:j])
            i = j
    py_tokens = [t for t in tokens if t.endswith(".py")]
    if not py_tokens:
        return None
    return _normalize(_strip_project_dir_prefix(py_tokens[-1]))


def _extract_script_path_from_args(args: list) -> str | None:
    """Pull the .py script path out of a hook's ``args`` list.

    Exec-form hooks set ``command: "python"`` and put the script path
    in ``args[0]``. Discover-wired-hooks must inspect both surfaces to
    survive the shell-form → exec-form switchover.
    """
    if not isinstance(args, list):
        return None
    for arg in args:
        if isinstance(arg, str) and arg.endswith(".py"):
            return _normalize(_strip_project_dir_prefix(arg))
    return None


def decode_bom(raw: bytes) -> str:
    """Decode bytes that may carry a UTF-8/16/32 BOM —
    a PowerShell ``Out-File`` / editor re-encode of a byte-canonical file. No
    BOM → UTF-8. UTF-32 checked before UTF-16 (the UTF-32-LE BOM starts with the
    UTF-16-LE BOM). Mirrored in ``tools/cc/_json_safe.decode_bom`` and
    ``ci_guard._ci_decode_bom`` (parity-pinned by tests)."""
    if raw[:4] in (codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE):
        return raw.decode("utf-32")
    if raw[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def decode_text_or_problem(raw: bytes) -> tuple[str, str]:
    """``(text, "")`` when ``raw`` decodes through ``decode_bom`` and carries no
    NUL, else ``("", problem)`` -- ``problem`` names what is wrong and the
    encoding to re-save in, in one sentence every caller prefixes with the
    file's name. A NUL in decoded text is UTF-16 with no byte-order mark:
    ASCII in UTF-16 decodes as UTF-8 with a NUL after every character, and no
    text file the harness reads carries one on purpose. The one owner of that
    sentence for the files an operator writes by hand (DEF-797); mirrored in
    ``tools/cc/_json_safe.decode_text_or_problem`` (parity-pinned by tests)."""
    try:
        text = decode_bom(raw)
    except UnicodeDecodeError as exc:
        detail = f"{exc.reason} at byte {exc.start}"
    else:
        if "\x00" not in text:
            return text, ""
        detail = "NUL bytes -- UTF-16 without a byte-order mark?"
    return "", (
        f"not UTF-8 text ({detail}) -- re-save it as UTF-8; a UTF-8 or UTF-16 "
        "byte-order mark is read"
    )


def is_effectively_empty_file(path: Path) -> bool:
    """True when ``path`` exists and holds nothing but whitespace after any
    BOM -- the frame an editor crash, an OS update or a truncating save leaves
    behind. Absent, unreadable and non-empty files all return False, so a
    caller that treats True as "absent" can never overwrite content (DEF-700:
    ``init`` preserved a 0-byte settings.json as operator-edited and sent the
    adopter through a move-aside round trip for a file with nothing in it).
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    try:
        text = decode_bom(raw)
    except (UnicodeDecodeError, ValueError):
        return False
    return text.strip() == ""


# -- Path presence, classified by errno ---------------------------------------
#
# Never ask pathlib whether a harness path exists. ``Path.exists()``,
# ``is_file()``, ``is_dir()`` and ``is_symlink()`` answer a parent that denies
# traversal differently per interpreter: CPython 3.10-3.13 let the stat's
# ``PermissionError`` out, 3.14 routes through ``os.path.*`` and swallows
# every ``OSError`` into ``False`` (measured on real 3.10, 3.13 and 3.14
# interpreters 2026-09-13; ``tests/_legacy_pathlib.py`` transcribes the
# 3.10-3.13 bodies so the raise reproduces on a 3.14 host). So a ``.claude``
# the adopter cannot search read as a crash on four supported floors and as
# "absent" -- with ``init`` offered as the remedy -- on the fifth (DEF-763:
# ``doctor`` listed every deployed file as missing, ``upgrade`` dry-ran
# green, ``merge-settings`` said "no settings.json found"). This oracle
# classifies the stat's own errno and answers the same everywhere;
# ``tests/test_contracts.py`` pins that no settings-path existence check in
# the engine bypasses it, and runs the engine under the legacy bodies.
PRESENCE_PRESENT = "present"
PRESENCE_ABSENT = "absent"
PRESENCE_UNREADABLE = "unreadable"

#: The errnos that mean "nothing is there": the path or a parent does not
#: exist, or a parent is a file. Everything else means something is there
#: that we cannot see: EACCES on a parent with no search bit, ELOOP on a
#: symlink cycle, EIO or ESTALE on a dead mount. Deliberately NARROWER than
#: pathlib's own ``_IGNORED_ERRNOS`` (ENOENT, ENOTDIR, EBADF, ELOOP -- see
#: ``tests/_legacy_pathlib.py``): a ``.claude`` that is a symlink loop is
#: not absent, it is something the operator has to resolve, and ``init``
#: could not write through it either.
_ABSENT_ERRNOS = frozenset({errno.ENOENT, errno.ENOTDIR})


def path_presence(path: Path | str) -> tuple[str, str]:
    """Classify ``path`` as ``present`` / ``absent`` / ``unreadable``, with the
    OS's own detail for the unreadable case and ``""`` otherwise.

    Follows symlinks, as ``Path.exists()`` does, so a dangling link is
    absent. A present path may still be unreadable as a FILE (mode 000): that
    is the read's error to report, with the read's message; this answers only
    whether the path can be reached.
    """
    try:
        os.stat(path)
    except OSError as exc:
        looped = _symlink_loop_on_the_way(path)
        if looped is not None:
            # One reading on every host. POSIX says ELOOP ("Too many levels of
            # symbolic links"); Windows says the name cannot be resolved
            # (WinError 1921) on the link itself and file-not-found under it
            # (Portability, 2026-09-23), which read a looped `.claude` as
            # absent -- with `init` offered as the remedy, on a directory that
            # is there (DEF-763's shape). The words are the ones
            # `unreadable_root_sentence` and its test look for.
            return PRESENCE_UNREADABLE, (
                f"symlink loop at {looped}: too many levels of symbolic links"
            )
        if exc.errno in _ABSENT_ERRNOS:
            return PRESENCE_ABSENT, ""
        return PRESENCE_UNREADABLE, os_error_text(exc)
    return PRESENCE_PRESENT, ""


def _symlink_loop_on_the_way(path: Path | str) -> str | None:
    """The first ancestor of ``path`` (itself included) that is a symlink whose
    target chain returns to a link already followed; ``None`` when no
    ancestor loops (a dangling link is not a loop, and stays absent)."""
    here = Path(path)
    for candidate in (here, *here.parents):
        try:
            if not os.path.islink(candidate):
                continue
        except OSError:
            continue
        seen: set[str] = set()
        current = candidate
        for _ in range(64):
            key = os.path.normcase(str(current))
            if key in seen:
                return str(candidate)
            seen.add(key)
            try:
                if not os.path.islink(current):
                    break
                target = os.readlink(current)
            except OSError:
                break
            current = Path(target) if os.path.isabs(target) else current.parent / target
    return None


def unreadable_harness_root(repo_root: Path) -> str | None:
    """The OS detail when ``.claude`` is a directory this process cannot
    search or list, else ``None``.

    An absent ``.claude`` is ``None`` (``init`` owns it), and a ``.claude``
    that is a plain file is ``None`` too (the not-a-directory arm owns it:
    ENOTDIR reads as absent at every settings-path site, and the merge's own
    ``no file`` verdict names it). Three lock shapes are caught: no search
    bit (a child cannot be stat'ed), no read bit (the directory cannot be
    listed), and a parent of ``.claude`` itself denying traversal.
    """
    claude_dir = Path(repo_root) / ".claude"
    kind, detail = path_presence(claude_dir)
    if kind == PRESENCE_UNREADABLE:
        return detail
    if kind == PRESENCE_ABSENT:
        return None
    try:
        if not stat.S_ISDIR(os.stat(claude_dir).st_mode):
            return None
    except OSError as exc:
        return os_error_text(exc)
    kind, detail = path_presence(claude_dir / "settings.json")
    if kind == PRESENCE_UNREADABLE:
        return detail
    try:
        with os.scandir(claude_dir):
            pass
    except OSError as exc:
        return os_error_text(exc)
    return None


def unreadable_root_sentence(detail: str) -> str:
    """The one operator-facing line for a ``.claude`` this process cannot
    search or list: rendered here so doctor's step, the audit gate's finding
    and each command's refusal cannot drift. ``detail`` is the OS's own
    message from :func:`unreadable_harness_root`."""
    return (
        f".claude cannot be read ({detail}) -- resolve that (usually its "
        "permissions: it must be searchable and listable by you), then re-run"
    )


def _load_settings_hooks_cfg(repo_root: Path) -> dict | None:
    """Return the parsed ``hooks`` block of ``.claude/settings.json`` (a dict),
    or ``None`` when the file is absent / unreadable / malformed / non-dict, or
    has no dict ``hooks`` block. Shared by the wired-hook discoverers.

    No existence pre-check: the read's ``OSError`` already answers absent,
    not-a-directory and unreadable alike, and a pathlib ``exists()`` here
    answered a locked parent per interpreter (DEF-763)."""
    settings_path = repo_root / ".claude" / "settings.json"
    try:
        # decode_bom tolerates a UTF-8/16/32 BOM (PowerShell Out-File / editor
        # re-encode) per the project's BOM convention — else a
        # byte-canonical-but-BOM'd settings.json fails CLOSED and the governance
        # oracle false-flags every gate on a healthy repo.
        data = json.loads(decode_bom(settings_path.read_bytes()))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    hooks_cfg = data.get("hooks")
    return hooks_cfg if isinstance(hooks_cfg, dict) else None


def _scripts_in_event_entries(event_entries: object) -> set[str]:
    """Extract repo-relative hook script paths wired in one event's entry list.

    Used by :func:`discover_wired_hooks` to extract wired scripts (handles both
    the exec-form and shell-form entry shapes)."""
    scripts: set[str] = set()
    if not isinstance(event_entries, list):
        return scripts
    for entry in event_entries:
        if not isinstance(entry, dict):
            continue
        hooks_list = entry.get("hooks")
        if not isinstance(hooks_list, list):
            continue
        for hook in hooks_list:
            if not isinstance(hook, dict):
                continue
            # Exec form puts the script in args; shell form
            # puts it in command. Check both.
            script = _extract_script_path_from_args(hook.get("args"))
            if script is None:
                cmd = hook.get("command", "")
                if isinstance(cmd, str):
                    script = _extract_script_path(cmd)
            if script:
                scripts.add(script)
    return scripts


def discover_wired_hooks(repo_root: Path) -> list[str]:
    """Return repo-relative hook script paths wired in `.claude/settings.json`."""
    hooks_cfg = _load_settings_hooks_cfg(repo_root)
    if hooks_cfg is None:
        return []
    seen: set[str] = set()
    for event_entries in hooks_cfg.values():
        seen |= _scripts_in_event_entries(event_entries)
    return sorted(seen)


# ── Executable-wiring discovery ──────────────────────────────────────────────
# discover_wired_hooks answers "what script PATH is referenced"; that
# is too weak for the N7 governance oracle, which must answer "is this DENY gate
# actually live". A hook whose path is textually present but whose command is a
# no-op (`true` / `:` / `echo` / a `#`-commented invocation), whose `type` is not
# `command`, whose path points at a stale copy, or whose matcher excludes the
# gated tools is DEAD — yet the path-only extractors report it wired (a fail-OPEN).
# The functions below model executability.

_MUTATION_MATCHER_TOOLS = ("Write", "Edit", "NotebookEdit")


def _is_python_interpreter(token: str) -> bool:
    """True if ``token`` is a BARE python interpreter command word — ``python`` /
    ``python3`` / ``python3.12`` / ``py``, optionally a full path. A token with
    whitespace (a shell-form command string like ``python3 -c pass x.py``) is
    NOT a bare interpreter and returns False — so only the canonical exec form
    (``command`` == a single interpreter binary) is recognized."""
    if not token or any(c.isspace() for c in token):
        return False
    base = token.replace("\\", "/").rsplit("/", 1)[-1]
    return base == "py" or base.startswith("python")


def _hook_executes_script_path(hook: dict) -> str | None:
    """Repo-relative path of the ``.py`` script a hook ENTRY actually EXECUTES as
    its program, or ``None`` if it does not — recognizing ONLY the canonical
    exec form that ``espalier init`` writes.

    Deciding "does this arbitrary shell string run the guard" is undecidable
    (every incremental shell/flag parser is defeated by ``-c``/``-m`` flags,
    ``&&``/``||``/``;`` short-circuits, ``python3 -m pytest <hook>``, …). So the
    governance oracle whitelists the one canonical shape and fails CLOSED on
    everything else — fix the class, not the constructs:

      * ``type`` is EXACTLY ``"command"`` — absent does NOT count, see
        :func:`hooks_config_voided_by`;
      * ``command`` is a BARE python interpreter (rejects ``true``/``:``/``echo``
        and any shell-form ``command`` string with spaces/flags);
      * ``args`` is a non-empty list whose FIRST element — python's program slot —
        is the ``.py`` (rejects ``-c CODE`` / ``-m MODULE`` prefixes that make the
        path inert ``sys.argv`` data, and shell-form entries that carry no args).

    Non-canonical-but-legitimate wirings (shell wrappers, ``env python …``,
    interpreter flags) are flagged — a conservative false-positive that points
    the operator at canonical wiring, never a fail-open. The caller verifies the
    returned path equals the canonical ``tools/cc/hooks/<script>``."""
    if not isinstance(hook, dict):
        return None
    # ⚠ ABSENT IS NOT "command". This read `htype is not None and htype !=
    # "command"` for months, on the reasonable-sounding theory that CC defaults
    # the field. Driven against real Claude Code 2.1.247 with a marker rig and a
    # control on both sides of every negative: an entry with no `type` DOES NOT
    # RUN. Modelling it as live was a fail-OPEN — the governance oracle read a
    # disarmed entry as wired. See `hooks_config_voided_by` for the far larger
    # half of the same platform fact.
    if hook.get("type") != "command":
        return None
    cmd = hook.get("command")
    if not (isinstance(cmd, str) and _is_python_interpreter(cmd)):
        return None
    args = hook.get("args")
    if not isinstance(args, list) or not args:
        return None
    first = args[0]
    if not isinstance(first, str):
        return None
    path = _normalize(_strip_project_dir_prefix(first.replace("\\", "/")))
    return path if path.endswith(".py") else None


def matcher_covers_mutations(matcher: str) -> bool:
    """True if a PreToolUse ``matcher`` actually fires on Write/Edit/NotebookEdit.

    ``*`` / empty / ``.*`` cover everything; otherwise the matcher is treated as
    the CC tool-name regex and must FULL-match all three mutation tools. A
    tool-excluding matcher (``Bash``, ``Read``, ``Agent``) silently disables a
    PreToolUse DENY gate.
    ``fullmatch`` (not ``search``) is deliberate: it is the stricter, fail-CLOSED
    reading — a substring-only matcher (``Write|Edit|Notebook``, which never
    anchors on ``NotebookEdit``) is treated as a coverage gap rather than
    silently accepted. An unparseable matcher also fails CLOSED."""
    if matcher in ("", "*", ".*"):
        return True
    try:
        pat = re.compile(matcher)
    except re.error:
        return False
    return all(pat.fullmatch(tool) for tool in _MUTATION_MATCHER_TOOLS)


def matcher_covers_canonical(deployed: str, canonical: str) -> bool:
    """True if a deployed ``matcher`` (a PreToolUse gate's, or a PostToolUse /
    PostToolUseFailure reporter's) is at least as broad as the hook's
    CANONICAL matcher.

    ``matcher_covers_mutations`` alone is too weak for ``write_guard``: its
    canonical matcher is ``"*"`` (fire on EVERY tool) because its kill-switch
    deny runs before the mutation-tool early-return and must reach
    Bash/Agent/MCP/etc. A narrowed ``"Write|Edit|NotebookEdit"`` *covers
    mutations* yet silently collapses the kill-switch to mutations-only — a
    dead-ish gate that read as wired. So require, per hook:
      * canonical fires on all (``""``/``"*"``/``".*"`` — write_guard) → the
        deployed matcher must ALSO fire on all;
      * canonical names specific tools (``Write|Edit|NotebookEdit`` — plan_guard)
        → the deployed matcher must cover those mutation tools.
    """
    fire_all = ("", "*", ".*")
    if canonical in fire_all:
        return deployed in fire_all
    if not matcher_covers_mutations(deployed):
        return False
    if deployed in fire_all:
        return True
    # DEF-619: every token of the canonical alternation, not only the three
    # mutation tools. post_write_check's canonical carries
    # `Bash|PowerShell|mcp__.*`, and a deployed matcher narrowed to the
    # mutation trio read as fully wired -- the neutered-but-armed shape this
    # oracle exists to catch (found by review, driven on the fixture). A plain
    # token must fullmatch as itself; a pattern token (`mcp__.*`) is probed
    # with a name it would match, since regex inclusion is not a string
    # compare. The token shapes are pinned in tests/test_hook_event_contracts.py
    # so a new one reds when it is declared. tools/cc/ci_guard.py's twin stays
    # on the mutation set: it only ever sees the blocking tier, whose canonical
    # tokens are all mutation tools (pinned beside the shapes).
    try:
        pat = re.compile(deployed)
    except re.error:
        return False
    return all(
        pat.fullmatch(matcher_token_probe(token)) is not None
        for token in canonical.split("|") if token
    )


def matcher_token_probe(token: str) -> str:
    """A tool name the canonical matcher ``token`` would match: the token
    itself when it is a plain name, else the pattern with its wildcard filled
    (``mcp__.*`` -> ``mcp__probe``)."""
    if re.fullmatch(r"[A-Za-z0-9_]+", token):
        return token
    return token.replace(".*", "probe").replace(".+", "probe")


def hooks_config_voided_by(hooks_cfg: object) -> str | None:
    """The first hook object whose ``type`` is not exactly ``"command"``,
    described for an operator, or ``None`` when every hook object is valid.

    ⚠ THIS IS NOT A PER-ENTRY RULE, AND IT IS NOT A RULE ABOUT ``type``.
    Claude Code SCHEMA-VALIDATES the whole hooks block and refuses ALL of it if
    any group or hook object fails — silently, stderr empty on every voided run.
    So one stray entry, which may be an adopter's OWN unrelated hook rather than
    anything espalier wrote, disarms every governance gate at once.

    ⚠ THE FIRST VERSION OF THIS FUNCTION GOT THE RULE WRONG IN BOTH DIRECTIONS,
    and the way it was wrong is this repo's signature defect: it tested
    ``type != "command"``, generalised from ONE malformed member, and so (a)
    missed seven other voiding shapes and (b) invented a FALSE RED on
    ``{"type": "prompt", "prompt": ...}``, a legitimate CC feature. The
    ``type="prompt"`` row that justified it had been built with ``command`` and
    ``args`` instead of ``prompt`` — malformed, not a prompt hook.

    Driven against real Claude Code 2.1.247, marker-file rig, every row
    bracketed by a control hook that fired:

      VOIDS THE WHOLE FILE — a hook object that is a string or ``null``; a group
      that is a string; a group with no ``"hooks"`` key; a group whose
      ``"hooks"`` is a string; ``{"type": "command"}`` with no ``command``;
      ``"matcher": 123``; ``"args"`` as a string; ``type`` absent; ``type``
      with an unknown value (``"wibble"``).

      LOADS NORMALLY — a well-formed ``{"type": "prompt", "prompt": "..."}``;
      a command hook with an extra ``timeout`` key; an empty ``"hooks": []``;
      an empty event list; a voider living in ``settings.local.json`` (voiding
      is per-file).

      BLAST RADIUS — a typed hook under ``SessionStart`` stops firing when the
      offending entry sits under ``PostToolUse`` or ``PreToolUse``. Whole file,
      not per-event and not per-entry.

    ⚠ Returns a DESCRIPTION, not a bool, because the caller has to be able to
    name the offender. A gate that reports every hook dead without saying which
    entry killed them is a verdict paired with nothing to do — the defect one
    row over (DEF-433), and it would be especially cruel here because the
    offending entry is often not one espalier manages.
    """
    if not isinstance(hooks_cfg, dict):
        return None
    for event, entries in hooks_cfg.items():
        if not isinstance(entries, list):
            return (f"hooks.{event} is {type(entries).__name__}, not a list of "
                    "hook groups")
        for entry in entries:
            if not isinstance(entry, dict):
                return (f"hooks.{event}: a hook group is "
                        f"{type(entry).__name__}, not an object")
            if "matcher" in entry and not isinstance(entry["matcher"], str):
                return (f"hooks.{event}: a group's \"matcher\" is "
                        f"{type(entry['matcher']).__name__}, not a string")
            if "hooks" not in entry:
                return f"hooks.{event}: a group has no \"hooks\" list"
            hooks_list = entry["hooks"]
            if not isinstance(hooks_list, list):
                return (f"hooks.{event}: a group's \"hooks\" is "
                        f"{type(hooks_list).__name__}, not a list")
            for hook in hooks_list:
                problem = _hook_object_schema_error(hook)
                if problem:
                    return f"hooks.{event}: {problem}"
    return None


def _hook_object_schema_error(hook: object) -> str | None:
    """What makes this hook object invalid to Claude Code, or ``None``.

    A POSITIVE whitelist of the two accepted shapes, which is safe precisely
    because CC itself rejects anything else: an unknown ``type`` value
    (``"wibble"``) was driven and VOIDS the file, so whitelisting cannot invent
    a red that CC would not also produce. Extra keys are tolerated by CC
    (``timeout`` driven), so they are tolerated here.

    ⚠ ``args`` present-but-``None`` is deliberately NOT flagged. A string
    ``args`` was driven and voids; ``null`` was not driven, and the cost
    asymmetry is steep -- a false red here declares every gate on a healthy
    tree dead and fails the adopter's CI, which is exactly the harm the
    ``type: "prompt"`` over-generalisation caused. Undriven shapes get the
    permissive reading until someone drives them.
    """
    if not isinstance(hook, dict):
        return f"a hook entry is {type(hook).__name__}, not an object"
    htype = hook.get("type")
    if htype == "command":
        if not isinstance(hook.get("command"), str):
            return 'a "command" hook has no string "command"'
        args = hook.get("args")
        if args is not None and not isinstance(args, list):
            return (f'a "command" hook\'s "args" is {type(args).__name__}, '
                    "not a list")
        return None
    if htype == "prompt":
        if not isinstance(hook.get("prompt"), str):
            return 'a "prompt" hook has no string "prompt"'
        return None
    shown = "<absent>" if htype is None else repr(htype)
    return f'a hook entry has type {shown} (expected "command" or "prompt")'


def discover_executable_hook_wirings(repo_root: Path) -> list[dict]:
    """One record per hook entry that genuinely EXECUTES a python script:
    ``{"event": str, "script": <repo-rel path>, "matcher": str}``. Entries that
    run no script (wrong ``type``, no-op/echo/commented/non-interpreter command)
    are omitted. The N7 governance oracle (doctor + ci_guard mirror) uses this —
    not the path-only discoverers — so a neutered-but-path-present gate is treated
    as UNWIRED. Returns ``[]`` when settings are absent/unreadable/malformed."""
    hooks_cfg = _load_settings_hooks_cfg(repo_root)
    if hooks_cfg is None:
        return []
    # A voided file loads NO hooks at all, so reporting the well-formed entries
    # as live would describe a state Claude Code never produces. Returning []
    # here is not a conservative guess — it is the measured truth, and it makes
    # every downstream consumer (unwired_governance_gates, doctor, ci_guard, the
    # enforcement claim) correct at once instead of one at a time.
    if hooks_config_voided_by(hooks_cfg) is not None:
        return []
    out: list[dict] = []
    for event, entries in hooks_cfg.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            # Absent matcher → "" (fire-on-all). PRESENT but non-string →
            # malformed → a sentinel that fails coverage (fail-closed), not ""
            # which would read covered.
            if "matcher" in entry:
                matcher = entry["matcher"]
                if not isinstance(matcher, str):
                    matcher = "\x00invalid"
            else:
                matcher = ""
            hooks_list = entry.get("hooks")
            if not isinstance(hooks_list, list):
                continue
            for hook in hooks_list:
                script = _hook_executes_script_path(hook)
                if script:
                    out.append({"event": str(event), "script": script, "matcher": matcher})
    return out


# ── Stale write_guard matcher (init re-init upgrade WARN) ─────────────────────
# Distinct from the N7 governance oracle above: that asks "is this DENY gate
# executable"; this asks the narrower "does write_guard's matcher still reach MCP
# tool calls". write_guard's kill-switch + protected-zone deny must fire on MCP
# writes; its canonical matcher is "*". A pre-v0.6.5 settings.json wired
# write_guard under a combined tool-list matcher (e.g.
# "Write|Edit|NotebookEdit|Bash|PowerShell") with NO mcp__/"*" coverage, so MCP
# tool calls bypassed it. A heuristic that scans EVERY entry for
# `"Write" in matcher and "mcp__" not in matcher` would trip on plan_guard's and
# context_reinject_failure's narrow-by-design "Write|Edit|NotebookEdit" matchers
# — a false alarm on every re-init of a CORRECT v0.7.x config. The fix is to
# scope the predicate to the write_guard ENTRY only.

_WRITE_GUARD_SCRIPT = "write_guard.py"


def _entry_references_script(entry: dict, script_basename: str) -> bool:
    """PERMISSIVE: does this settings.json hook ENTRY wire ``script_basename`` in
    any of its hooks' ``command``/``args``? Unlike the exec-form-only
    :func:`_hook_executes_script_path`, this also recognizes OLD shell-form wirings
    (``bash -c "… write_guard.py"``) and ``-c``/``-m`` forms — required because the
    stale-matcher WARN exists precisely to flag pre-v0.6.5 (often shell-form)
    settings.json, the very shapes the N7 oracle deliberately fails CLOSED on.
    Matches a path-anchored ``/<basename>`` so a sibling like ``not_write_guard.py``
    does not false-match; ``espalier init`` always emits the canonical
    ``tools/cc/hooks/<basename>`` path."""
    if not isinstance(entry, dict):
        return False
    hooks_list = entry.get("hooks")
    if not isinstance(hooks_list, list):
        return False
    needle = "/" + script_basename
    for hook in hooks_list:
        if not isinstance(hook, dict):
            continue
        tokens: list[str] = []
        cmd = hook.get("command")
        if isinstance(cmd, str):
            tokens.append(cmd)
        args = hook.get("args")
        if isinstance(args, list):
            tokens.extend(a for a in args if isinstance(a, str))
        for tok in tokens:
            if needle in tok.replace("\\", "/"):
                return True
    return False


# A representative live MCP tool name. CC dispatches a hook iff its matcher
# ``re.fullmatch``-es the TOOL NAME — the codebase's single authoritative model
# (:func:`matcher_covers_mutations`, ci_guard's mirror, the "Stale .claude/
# settings.json PreToolUse Matcher" SHARP_EDGES entry), NOT iff the matcher merely
# contains a substring. A heuristic using `"mcp__" in matcher` would be fooled by
# a hand-edit typo like ``Write|Edit|mcp__`` (bare token, no ``.*``) or
# ``…|mcp__\.\*`` (escaped): both CONTAIN the substring yet fullmatch NO real MCP
# tool, so write_guard would not fire on an MCP write — a bypass the WARN would be
# silent on. (Low severity: the N7 oracle — doctor + ci_guard — already flags any
# write_guard matcher narrower than fire-on-all, so CI catches it; this tightening
# is the friendly init-time advisory matching that stricter gate + collapses a
# second, weaker matcher-semantics model onto the one authoritative fullmatch
# model.)
_MCP_TOOL_PROBE = "mcp__filesystem__write_file"


def _matcher_reaches_mcp(matcher: str) -> bool:
    """True if a hook ``matcher`` would actually dispatch on a real MCP tool call.
    ``""``/``"*"``/``".*"`` fire on everything; otherwise the matcher is the CC
    tool-name regex and must ``fullmatch`` a representative MCP tool name. An
    unparseable matcher fails CLOSED (NOT reaching MCP → the stale-matcher WARN
    fires) — the same fail-closed reading as :func:`matcher_covers_mutations`."""
    if matcher in ("", "*", ".*"):
        return True
    try:
        pat = re.compile(matcher)
    except re.error:
        return False
    return bool(pat.fullmatch(_MCP_TOOL_PROBE))


def write_guard_matcher_excludes_mcp(settings: object) -> bool:
    """True if a hook entry wiring ``write_guard.py`` carries a matcher that does
    NOT reach MCP tool calls — the genuine pre-v0.6.5 regression the ``espalier
    init`` re-init WARN targets.

    SCOPED TO THE write_guard ENTRY: plan_guard's and context_reinject_failure's
    narrow ``Write|Edit|NotebookEdit`` matchers (intentional — MCP write coverage
    is write_guard's ``"*"`` matcher's job) must NOT trip this. Pre-fix the
    heuristic scanned every entry, so those two tripped on every re-init of a
    correct config.

    MCP-reachability is decided by :func:`_matcher_reaches_mcp` (CC's ``fullmatch``
    model), NOT a substring test — a ``Write|Edit|mcp__`` typo CONTAINS ``mcp__``
    yet fullmatches no real MCP tool, so it IS stale. ``write_guard`` UNWIRED
    entirely returns False — that deleted-gate case is the N7 oracle's concern
    (doctor + ci_guard), not this advisory. A PRESENT-but-non-string matcher on the
    write_guard entry fails CLOSED (warns) — consistent with the N7 oracle. Returns False on a
    non-dict / hooks-less / malformed ``settings``."""
    if not isinstance(settings, dict):
        return False
    hooks_block = settings.get("hooks")
    if not isinstance(hooks_block, dict):
        return False
    for entries in hooks_block.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not _entry_references_script(entry, _WRITE_GUARD_SCRIPT):
                continue
            matcher = entry.get("matcher", "")
            if not isinstance(matcher, str):
                return True  # malformed matcher on write_guard → fail-CLOSED
            if not _matcher_reaches_mcp(matcher):
                return True
    return False


def _list_dir_relative(repo_root: Path, rel_dir: str, pattern: str) -> list[str]:
    target = repo_root / rel_dir
    if not target.is_dir():
        return []
    # A precise final component (``*/SKILL.md``) is resolved by pathlib with
    # an existence check, not a listing, so on APFS and NTFS a stray
    # ``skill.md`` matched and was reported with the pattern's spelling: a
    # path that is not on disk and a file the deploy never wrote. List the
    # parent by wildcard and keep only the exact name (driven 2026-09-11).
    head, _, leaf = pattern.rpartition("/")
    precise = not any(ch in leaf for ch in "*?[")
    listing = pattern if not precise else (f"{head}/*" if head else "*")
    results: list[str] = []
    for path in target.glob(listing):
        if precise and path.name != leaf:
            continue
        if path.is_file():
            results.append(_normalize(str(path.relative_to(repo_root))))
    return sorted(set(results))


#: The deployed shape of each ``.claude/`` kind ``init`` writes from packaged
#: bodies: the kind is the directory under ``.claude/``, the glob is the file's
#: shape beneath it (skills sit one level deeper, ``<name>/SKILL.md``). This
#: mapping is the ONE owner of the kinds -- ``CLAUDE_SURFACE_KINDS`` is its key
#: order and the discoverers read their glob from it -- and every view that
#: answers "what does the harness own on disk under .claude/" reads all of
#: its kinds: the two disk-reality views in ``managed_paths``, the public
#: prefixes in ``managed_inventory``, the init banner's counts and the
#: upgrade's orphan scan in ``cli``. A kind added here without a glob is a
#: KeyError at the owner, not deep inside an uninstall. Driven 2026-09-11 on
#: a fresh init: nine skill files deployed, nine named by ``clean-generated``,
#: none in the doctor's ``ownership.managed_paths``, because the two views
#: globbed agents and commands by hand and never learned the third kind.
CLAUDE_KIND_GLOBS: dict[str, str] = {
    "agents": "*.md",
    "commands": "*.md",
    "skills": "*/SKILL.md",
}
CLAUDE_SURFACE_KINDS: tuple[str, ...] = tuple(CLAUDE_KIND_GLOBS)


def discover_claude_kind(repo_root: Path, kind: str) -> list[str]:
    """Repo-relative paths of one deployed ``.claude/`` kind, as on disk now."""
    return _list_dir_relative(repo_root, f".claude/{kind}", CLAUDE_KIND_GLOBS[kind])


def discover_claude_surface(repo_root: Path) -> dict[str, list[str]]:
    """Every deployed ``.claude/`` kind by name -- all of them, nothing else."""
    return {kind: discover_claude_kind(repo_root, kind) for kind in CLAUDE_SURFACE_KINDS}


def discover_installed_agents(repo_root: Path) -> list[str]:
    return discover_claude_kind(repo_root, "agents")


def discover_installed_commands(repo_root: Path) -> list[str]:
    return discover_claude_kind(repo_root, "commands")


def discover_installed_skills(repo_root: Path) -> list[str]:
    return discover_claude_kind(repo_root, "skills")


def discover_managed_reports(repo_root: Path) -> list[str]:
    return sorted(
        rel for rel in _MANAGED_REPORT_PATHS if (repo_root / rel).exists()
    )


def discover_self_host_surface(repo_root: Path) -> dict[str, list[str]]:
    """Composite view of the managed surface for a given repo root."""
    return {
        **discover_claude_surface(repo_root),
        "hooks": discover_wired_hooks(repo_root),
        "managed_reports": discover_managed_reports(repo_root),
        "required_init_files": sorted(get_required_init_files()),
    }


# ---------------------------------------------------------------------------
# Self-host detection
# ---------------------------------------------------------------------------


def _project_name_from_pyproject(text: str) -> str | None:
    if _tomllib is None:
        return None
    try:
        data = _tomllib.loads(text)
    except (ValueError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    project = data.get("project")
    if isinstance(project, dict):
        name = project.get("name")
        if isinstance(name, str):
            return name
    tool = data.get("tool")
    if isinstance(tool, dict):
        poetry = tool.get("poetry")
        if isinstance(poetry, dict):
            name = poetry.get("name")
            if isinstance(name, str):
                return name
    return None


def off_self_host(repo_root: Path) -> bool:
    """True when ``repo_root`` is NOT the Espalier-Harness source tree.

    THE single owner of "should this apply Espalier's own standards here?".
    Deliberately one function rather than a `not is_self_host_repo(...)` at
    each site: the verbs that consult it are exactly the ones that were found
    applying Espalier's internal vocabulary, release requirements or branding
    to an adopter's content, and two independently-authored spellings of one
    policy is the drift class this repo keeps closing.

    Callers: ``cli._off_self_host`` (provenance / pre-release / release-pack),
    ``surface_impact._scan_existing`` (the content scans) and
    ``surface_impact.build_report`` (withholds the provenance OBLIGATION, so the
    checklist never demands a check that cannot run). Note the last two live in
    a VISIBLE verb -- hidden-ness is neither necessary nor sufficient for
    membership, which is why the accounting test derives from callers of this
    predicate rather than from the hidden-command list.
    """
    return not is_self_host_repo(repo_root)


def is_self_host_repo(repo_root: Path) -> bool:
    """True if ``repo_root`` is the Espalier-Harness repo itself (vs a consumer repo).

    BC-035: requires 5 signals -- ``espalier/``
    directory, ``tools/cc/`` directory, ``bench/`` directory, project
    name match in pyproject.toml, and a content-hash match on
    ``tools/cc/hooks/write_guard.py`` (first 200 bytes vs pinned SHA).
    Pre-fix a user repo could spoof self-host with just an
    ``espalier-harness`` name in pyproject + empty ``espalier/`` and
    ``tools/cc/`` stubs and acquire the elevated harness posture
    (espalier/ added to write_guard's protected prefixes, espalier/
    added to plan_guard's exempt prefixes, dogfood-reflect including
    harness paths). The pinned content hash forces a spoofer to ship
    the actual write_guard.py prefix -- an observable supply-chain
    action rather than a passive name match.

    The pin is intentionally NOT a cryptographic boundary -- it is
    defense-in-depth alongside name+layout checks. See
    ``espalier/_self_host_fingerprint.py`` for the pinned constant and
    the refresh CLI.
    """
    if not (repo_root / "espalier").is_dir():
        return False
    if not (repo_root / "tools" / "cc").is_dir():
        return False
    if not (repo_root / "bench").is_dir():
        return False
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        return False
    try:
        text = pyproject.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    name = _project_name_from_pyproject(text)
    if not isinstance(name, str):
        return False
    if name.strip().lower() not in {"espalier-harness", "espalier_harness"}:
        return False
    return _write_guard_prefix_matches_pin(repo_root)


def _write_guard_prefix_matches_pin(repo_root: Path) -> bool:
    """Compare SHA-256 of the first 200 bytes of write_guard.py against
    the pinned constant. Returns False on any read failure -- the safer
    default (treat as user-repo)."""
    from espalier._self_host_fingerprint import (
        WRITE_GUARD_PREFIX_BYTES,
        WRITE_GUARD_PREFIX_SHA256,
    )
    write_guard = repo_root / "tools" / "cc" / "hooks" / "write_guard.py"
    if not write_guard.is_file():
        return False
    try:
        prefix = write_guard.read_bytes()[:WRITE_GUARD_PREFIX_BYTES]
    except OSError:
        return False
    import hashlib
    actual = hashlib.sha256(prefix).hexdigest()
    return actual == WRITE_GUARD_PREFIX_SHA256


def is_release_export(repo_root: Path) -> bool:
    """True when ``repo_root`` is a *source-release export* of Espalier-Harness
    (``git archive`` / GitHub "Download ZIP" / an extracted sdist) rather than
    the full development tree.

    Why this exists -- layout vs. content. :func:`is_self_host_repo` answers
    "is this the Espalier-Harness project?" by testing the code *layout*
    (``espalier/`` + ``tools/cc/`` + ``bench/`` + pyproject name + the
    ``write_guard.py`` hash). A source export ships that whole layout, so
    ``is_self_host_repo`` returns **True** for an export too. Reaching for it as
    a proxy for "the full dev tree is present" is a category error: an export
    *prunes* the tracked-but-``export-ignore``'d internal content (``ESPALIER_MEMORY.md``,
    ``docs/REDEFINED_INFORMATION_REGISTRY.md``, ...). A check that asserts
    full-dev-tree invariants must gate on *this* function, not on
    ``is_self_host_repo``.

    Discriminator (no magic filename). The sentinels are the ``export-ignore``
    plain-file entries declared in ``.gitattributes`` -- derived, not hard-coded,
    so a rename that updates ``.gitattributes`` in the same commit is picked up
    automatically. An export prunes *all* of them; a full dev tree (and a fresh
    clone) keeps the tracked ones, so at least one is always present. Requiring
    *every* sentinel absent is redundant across several tracked files: an
    accidental local deletion of one cannot misclassify a dev tree as an export.

    Conservative -- positive confirmation only. Returns True *only* when the
    layout is present AND ``.gitattributes`` yields at least one plain-file
    sentinel AND every such sentinel is absent. Any uncertainty (not self-host,
    no ``.gitattributes``, no plain-file sentinels) returns False, so callers
    keep running their dev-content checks: a loud failure on a genuine export is
    recoverable, a silent skip on a real dev tree quietly loses coverage.
    """
    if not is_self_host_repo(repo_root):
        return False
    # Plain-file export-ignore entries only: skip directory patterns (trailing
    # "/") and globs (need path-walking to resolve) -- a reliably-tracked single
    # file is a stronger, simpler signal than a globbed or directory pattern.
    # Minus the harness-managed memory file: DEC-31's public repository is an
    # export that grows its own ESPALIER_MEMORY.md at the seed and at every
    # handoff after it, so its presence says nothing about which tree this is
    # (it stays export-ignored; the maintainers' copy never ships). Pinned by
    # tests/test_export_guard.py::TestIsReleaseExport.
    sentinels = [
        pat
        for pat in export_ignore_patterns(repo_root)
        if not pat.endswith("/")
        and not any(ch in pat for ch in "*?[")
        and pat not in _EXPORT_SENTINEL_EXCLUSIONS
    ]
    if not sentinels:
        return False
    return all(not (repo_root / pat).exists() for pat in sentinels)


#: Export-ignored plain files that every governed tree carries, so they cannot
#: tell an export from a development tree. See ``is_release_export``.
_EXPORT_SENTINEL_EXCLUSIONS: frozenset[str] = frozenset({"ESPALIER_MEMORY.md"})


# ---------------------------------------------------------------------------
# Public docs discovery
#
# TWO AXES, deliberately separated — this list used to mean both at once.
#
#   AUDITED  — "scan this doc's numeric claims for drift."  _PUBLIC_DOC_RELPATHS,
#              read by scripts/release_check.py::check_docs_count_claims,
#              tests/test_count_claims.py::PUBLIC_DOCS, test_documented_claims,
#              and test_surface_support_matrix.
#   INDEXED  — "docs/README.md must link this."  get_indexed_doc_relpaths(),
#              whose derivation tests/test_operator_docs.py::TestIndexedDocsAreShippable
#              pins. (TestDocIndexCompleteness no longer reads it: since
#              2026-09-22 it derives its own population from `git ls-files
#              docs/*.md` filtered `public`, because INDEXED covered ten of the
#              thirty-one public top-level docs and a public doc outside the
#              audited set shipped unindexed while that class was green.)
#
# INDEXED is DERIVED from AUDITED by dropping anything classify_release_path()
# calls `internal` — never hand-written. A doc can be normative enough to audit
# while being maintainer-only material that no shipped index should advertise;
# docs/RELEASE_CHECKLIST.md is exactly that, and conflating the two axes is what
# made "it is allowlisted as operator-facing" read as "therefore it ships."
# ---------------------------------------------------------------------------

_PUBLIC_DOC_RELPATHS: tuple[str, ...] = (
    "README.md",
    "CONTRIBUTING.md",
    "docs/QUICKSTART.md",
    "docs/CHEAT-SHEET.md",
    "docs/POSITIONING.md",
    "docs/SHARP_EDGES.md",
    "docs/CONVENTIONS.md",
    "docs/TASK_RECIPES.md",
    "docs/HOOKS.md",
    "docs/WORKFLOW.md",
    # Operator-facing additions — both are normative for what ships and how to
    # verify it; the count-claim scan applies.
    "docs/SURFACE_SUPPORT_MATRIX.md",
    # AUDITED but not INDEXED -- it classifies `internal` and ships nowhere, so
    # it is dropped from the derived INDEXED set above rather than removed from
    # this one. Declared as the asymmetric case in
    # claim_extractor.AUDITED_INTERNAL_DOCS, which carries the measured reason:
    # count-drift is NOT what membership buys today (extract_claims yields 0 on
    # this file); the two phrase sweeps in test_surface_support_matrix.py and
    # test_documented_claims.py are.
    #
    # OVERTURN, 2026-08-13, by operator decision -- a 2026-07-05 review filed
    # "RELEASE_CHECKLIST.md ships to adopters" as refuted-do-not-reopen because
    # it was "allowlisted in _PUBLIC_DOC_RELPATHS as operator-facing/normative".
    # Right that the doc is normative, wrong to infer `therefore it ships` from a
    # list that also meant `link this from the index`. The tracked record is
    # docs/RELEASE_DECISIONS.md § 2026-08-13 -- cite that, not the review report,
    # which lives under the gitignored reports/ and reaches no clone. NOTE: this
    # source file ships, and BOTH cited paths are maintainer-only (one gitignored,
    # one export-ignored), so neither resolves beside you in an sdist or a
    # Download ZIP -- read them in the repo on GitHub.
    "docs/RELEASE_CHECKLIST.md",
    # Pack-authoring contract for the `Affected symbols` section that `espalier
    # scope-check` consumes. Operator-facing; ships in sdist.
    "docs/PACK_AUTHORING.md",
)
# CHANGELOG.md is intentionally excluded: it is a historical record and
# deliberately references old counts ("13 commands → 14") as changelog prose.


def get_public_doc_relpaths() -> tuple[str, ...]:
    """Return the canonical list of public Markdown doc relpaths.

    To add a file to the count-audit default set, add it here — both
    release_check and test_count_claims pick it up automatically.
    """
    return _PUBLIC_DOC_RELPATHS


def discover_public_docs(repo_root: Path) -> list[Path]:
    """Return absolute Paths for every existing public doc.

    Missing files are silently skipped (they may not exist in a fresh
    source archive). Order matches _PUBLIC_DOC_RELPATHS for stability.
    """
    return [
        repo_root / rel for rel in _PUBLIC_DOC_RELPATHS
        if (repo_root / rel).exists()
    ]


def get_indexed_doc_relpaths() -> tuple[str, ...]:
    """Audited docs that a shipped index may advertise — AUDITED minus internal.

    DERIVED, never hand-written (``docs/STANDING_PRINCIPLES.md`` §14): the
    moment a doc is added to ``_INTERNAL_FILENAME_PATTERNS`` it leaves this set
    with no second list to update. A hand-kept copy here would be the exact
    declared-population shape §C1 catalogues.

    Why the two sets differ: ``_PUBLIC_DOC_RELPATHS`` answers *"scan this for
    count drift"*, which is worth doing for any normative doc including
    maintainer-only ones. This answers *"must docs/README.md link it"*, which is
    only true for docs that actually reach a reader of the shipped artifact.
    Requiring an index link to an ``internal`` doc plants a link that resolves
    in the dev tree and 404s in the release archive and the sdist -- caught by
    ``test_git_archive_parity.py`` and ``test_wheel_payload.py``, which check
    two different exclusion mechanisms and so can disagree.
    """
    return tuple(
        rel for rel in _PUBLIC_DOC_RELPATHS
        if classify_release_path(rel) != "internal"
    )


# ---------------------------------------------------------------------------
# Count-claim regex helpers
#
# Widens the count regex to accept spelled-out small numbers ("three",
# "four", ..., "fifteen") in addition to digits. This is the gap that
# let "three helper modules" survive to 0.5.0 in QUICKSTART.
# ---------------------------------------------------------------------------

# Stops at fifteen — beyond that, standard English uses digits.
_WORD_NUMBERS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15,
}

_COUNT_TOKEN_PATTERN = (
    r"\b("
    r"\d+"
    r"|"
    + "|".join(re.escape(w) for w in _WORD_NUMBERS)
    + r")\b"
)


def parse_count_token(token: str) -> int | None:
    """Translate a count token to an integer.

    Accepts decimal digits ("12" → 12) and spelled-out small numbers
    ("three" → 3, "twelve" → 12, case-insensitive).
    Returns None for unrecognized tokens.
    """
    if token.isdigit():
        return int(token)
    return _WORD_NUMBERS.get(token.lower())


def make_count_claim_regex(noun_pattern: str) -> "re.Pattern[str]":
    """Build a count-claim regex for a particular noun pattern.

    `noun_pattern` is a regex fragment for the noun the count qualifies,
    e.g. ``r"agents?"`` or ``r"(?:hook\\s+)?helpers?(?:\\s+modules?)?"``.

    The returned regex captures the count token in group 1. Use
    parse_count_token to translate the token to an integer.

    The single optional intervening word means a phrasing like "6 specialized
    governance agents" (two adjectives) evades the count check — a *latent*
    false-negative (no such phrasing exists in the
    scanned public docs today). Widening the allowance to ``{0,3}`` was measured
    to introduce a worse FALSE POSITIVE: it newly matches subset prose like
    "4 of the hooks" in docs/CONVENTIONS.md, where "4" is not a total claim. A
    word-count widen cannot tell adjectives ("specialized") from function words
    ("of the"). Per the governing frame (a gate false-positive outranks a latent
    false-negative), the allowance stays at one word.
    """
    return re.compile(
        _COUNT_TOKEN_PATTERN
        + r"\s+(?:[a-z-]+\s+)?(?:"
        + noun_pattern
        + r")\b",
        re.IGNORECASE,
    )
