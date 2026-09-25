#!/usr/bin/env python3
"""Protected-zone path checks for write_guard.

Mirrors ``espalier.surface_contract.get_protected_mutation_prefixes()`` via
``_hook_utils.harness_protected_prefixes`` (already a sibling helper).
Stdlib-only with one sibling import.

The zone classification surface (PROTECTED_PREFIXES + PROTECTED_FILES +
ALLOWED_IN_PROTECTED + ALLOWED_PREFIXES_IN_PROTECTED) is the friction-
layer's source of truth on what gets blocked. Parity with
``surface_contract`` is asserted by
``tests/test_contract_consumers.py::TestWriteGuardSurfaceParity`` --
this module's inventory must remain a superset of surface_contract's.
"""
from __future__ import annotations

import os
import stat
import sys
import unicodedata
from pathlib import Path

# Co-located helper module -- same zero-espalier-import pattern as other hooks.
sys.path.insert(0, str(Path(__file__).parent))
import _hook_utils  # noqa: E402

# SoT for cc/ path strings. Lives one directory up at tools/cc/_paths.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _paths  # noqa: E402

# Universal protected harness zones -- the prefixes that ALWAYS protect
# regardless of repo context. On the self-host repo, _is_protected() also
# treats `espalier/` as protected via _hook_utils.harness_protected_prefixes().
# Tests that pin the universal contract import this constant directly
# (e.g., test_contract_consumers.py).
#
# All GitHub Actions workflows are protected. The harness-guard workflow
# specifically is also in PROTECTED_FILES below; the prefix extends
# coverage to release.yml, refresh-externals.yml, end-to-end-bench.yml,
# benchmark.yml, and any future workflow.
PROTECTED_PREFIXES = [
    "tools/cc/",
    "cc/",
    ".github/workflows/",
    # espalier/ (the harness's own engine source) is listed so this
    # test-/audit-facing declaration equals the engine SoT
    # surface_contract.get_protected_mutation_prefixes(). NON-OPERATIVE for the
    # runtime deny, which iterates _hook_utils.harness_protected_prefixes (adds
    # espalier/ only on self-host, never on an adopter repo). Pinned by
    # tests/test_forced_copy_parity.py::TestProtectedPrefixDeclarationParity.
    "espalier/",
]

# Exact-match files outside the directory prefixes that still need protection.
# Functionally equivalent to (a superset of) espalier.surface_contract.
# get_protected_mutation_paths() -- surface_contract enumerates each individual
# file (e.g. tools/cc/hooks/write_guard.py) while we cover those by the
# `tools/cc/` prefix in PROTECTED_PREFIXES. Hard-coded here because hooks
# must stay zero-espalier-import (standalone). Parity is asserted by
# tests/test_contract_consumers.py::TestWriteGuardSurfaceParity.
# sister-site: ok forced hook-side copy across the no-import boundary; runtime write-deny exact-match set
PROTECTED_FILES = {
    ".espalier/integrity.json",
    ".espalier/freshness.json",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".github/workflows/harness-guard.yml",
}

# Files in protected zones that agents legitimately need to update.
#
# cc/ is a PROTECTED_PREFIX to guard the blueprint chain from slip/agent
# corruption, but two continuity docs living under cc/ are REWRITTEN every
# `/handoff`: cc/GOAL.md (the goal/progress snapshot) and cc/_working_summary.md
# (the always-current session-resume mirror). Without an allowlist entry a
# NORMAL (non-maintenance) session cannot refresh them, so the continuity docs
# silently go stale — the object-level bug behind the `trigger-gated-defect`
# memory (bypass-mask sub-case: months of maintenance-mode handoffs hid the
# block). Both are gitignored, local-only continuity docs — NOT governance
# files — so allowing writes does not loosen the anti-self-disable floor.
# Exact paths, plus ONE prefix: `ALLOWED_PREFIXES_IN_PROTECTED` below carves out
# the blueprint chain directory, and has since the zone was first extracted
# (2026-05-19), because the per-session nodes under it are written by the workflow
# itself (record / finalize / handoff). cc/LIVE_SURFACE.md is an exact entry
# here too (`_paths.LIVE_SURFACE_REL`). So the floor this list leaves is: a
# write to any cc/ path NOT listed is denied, and `_fs_equiv` below folds every
# spelling of a listed path onto the listed one. Widen by exact entry; a second
# prefix needs its reason written here. (An earlier version of this note,
# written 2026-07-03, said "exact paths only, never a prefix" while the prefix
# had been in the tuple since 2026-05-19 -- the tuples below are the oracle,
# not the prose.)
ALLOWED_IN_PROTECTED = {
    "cc/execution_plan.json",
    "cc/GOAL.md",
    "cc/_working_summary.md",
    _paths.SURFACE_HANDOFF_REL,
    _paths.LIVE_SURFACE_REL,
    _paths.COMMANDS_INDEX_REL,
    _paths.PACK_MANIFEST_REL,
}
ALLOWED_PREFIXES_IN_PROTECTED = (
    _paths.BLUEPRINTS_DIR_REL + "/",
)


def _fs_equiv(rel_path: str, *, all_components: bool) -> str:
    """Canonicalise a repo-relative path to its OS-equivalence form for the
    protected-zone comparison.

    Folds the spelling-equivalence classes the OS treats as the SAME on-disk
    file but a naive string compare does not:

      * separators            -- ``a\\b`` == ``a/b``
      * trailing dot/space per component -- Windows strips ``. `` at open(),
        so ``settings.json.`` / ``settings.json `` / ``tools/cc./hooks/x.py``
        all name the canonical protected path;
      * NTFS ADS suffix -- ``settings.json::$DATA`` / ``:stream`` write the
        base file's data stream, AND ``dir::$INDEX_ALLOCATION`` is a
        *traversable* directory stream, so ``tools/cc::$INDEX_ALLOCATION/x.py``
        opens ``tools/cc/x.py`` on NTFS. Hence the strip must reach
        NON-final components, not just the basename.

    Composed with the pre-existing NFKC + casefold case/Unicode folding.
    Applied to BOTH the candidate path AND every set member so the two sides
    of each comparison fold identically.

    ``all_components`` makes the fold ASYMMETRIC, and both directions fail
    CLOSED:

      * ``_is_protected`` passes ``all_components=True`` -- strip every
        component, so a directory-stream / dotted-directory traversal folds
        onto the protected prefix (over-PROTECT on an exotic POSIX dir name is
        a recoverable over-block).
      * ``_is_allowed`` passes ``all_components=False`` -- strip the BASENAME
        only. A POSIX directory literally named ``blueprints.`` or
        ``blueprints:notes`` is a DIFFERENT real directory from the allowlisted
        ``blueprints``; folding it would WIDEN the allowlist (fail-OPEN). The
        basename strip still recognises the Windows ``execution_plan.json.`` /
        ``::$DATA`` spelling of a legitimately-allowed FILE without admitting
        a forged directory component.

    ``.``/``..`` segments are preserved verbatim (rstrip would erase a bare
    ``.``); in practice the normalize chokepoint resolves them away first.
    """
    parts = rel_path.replace("\\", "/").split("/")
    last = len(parts) - 1
    out = []
    for i, seg in enumerate(parts):
        if seg in (".", ".."):
            out.append(seg)
            continue
        if all_components or i == last:
            # ADS suffix (name:stream / name::$DATA / dir::$INDEX_ALLOCATION):
            # everything from the first colon names a stream of the base entry.
            if ":" in seg:
                seg = seg.split(":", 1)[0]
            # Windows strips trailing dots/spaces per component at open().
            seg = seg.rstrip(". ")
        out.append(seg)
    folded = "/".join(out)
    return unicodedata.normalize("NFKC", folded).casefold()


def _is_protected(rel_path: str, root: Path) -> bool:
    """Check if path is in a protected harness zone or protected file list.

    Resolves the prefix list per-call via _hook_utils.harness_protected_prefixes
    so the self-host overlay (espalier/ as protected source) doesn't leak
    into user-repo behavior.

    Case-insensitive comparison. On case-insensitive filesystems
    (macOS HFS+/APFS, Windows NTFS), ``tools/CC/hooks/evil.py`` points
    to the same inode as ``tools/cc/hooks/evil.py`` but ``startswith``
    on path strings is case-sensitive -- pre-fix the prefix check let
    that bypass through. ``os.path.normcase`` only handles Windows, not
    macOS HFS+ (Python can't tell which macOS variant is in use), so
    use ``.lower()`` unconditionally. Protected prefixes are all
    lowercase by project convention, so this is a no-op on Linux paths
    that already match the convention.

    plan_guard._is_exempt has an explicit absolute-path exemption for paths
    outside the repo. write_guard does NOT need the same branch --
    PROTECTED_PREFIXES is rel-only (tools/cc/, cc/, espalier/, .github/workflows/) so
    absolute out-of-repo paths naturally fall through to "not protected."
    Additionally, _normalize_path above resolves symlinks via Path.resolve()
    before this check fires, so a stray symlink can't silently redirect an
    out-of-repo absolute path into a protected zone (de-prioritized
    defense-in-depth — no self-user reaches this by mistake).

    NFKC + casefold rather than ``.lower()``: ``.lower()`` was ASCII-only;
    fullwidth Latin (U+FF21..U+FF5A),
    Turkish dotted I (U+0130), German ss (U+00DF), and other Unicode
    equivalents fold to the ASCII form on case-insensitive APFS via
    the filesystem's Unicode case-folding tables -- the file lands
    in the protected zone but ``.lower()`` left a string mismatch so
    ``startswith`` returned False. ``NFKC`` collapses compatibility
    variants (fullwidth -> ASCII); ``casefold`` handles ss -> ss and
    Turkish I. PROTECTED_FILES / PROTECTED_PREFIXES are ASCII by
    project convention so the normalization is a no-op for the
    expected-path side, but defensive: normalize both sides.

    The NFKC+casefold fold is one step of the shared ``_fs_equiv``
    canonicaliser, which additionally folds the Windows trailing-dot/space +
    NTFS-ADS spelling-equivalence classes. Both the candidate path and every
    set member route through it identically.
    """
    rel_norm = _fs_equiv(rel_path, all_components=True)
    protected_files_norm = {_fs_equiv(p, all_components=True) for p in PROTECTED_FILES}
    if rel_norm in protected_files_norm:
        return True
    for prefix in _hook_utils.harness_protected_prefixes(root):
        pfx = _fs_equiv(prefix, all_components=True)  # e.g. "cc/"
        # Match the dir's CONTENTS (``cc/x``) AND the bare governed directory
        # itself (``cc``): a ``ln -s other cc`` symlink in place of the
        # protected DIRECTORY would, if the bare ``cc`` linkname missed the
        # trailing-slash prefix, let a later reader follow the symlinked
        # governed parent off-path. Matching the bare name closes that.
        # Over-protecting a hypothetical root-level file literally named ``cc``
        # is the safe fail-closed direction. (De-prioritized defense-in-depth.)
        if rel_norm == pfx.rstrip("/") or rel_norm.startswith(pfx):
            return True
    return False


def _encloses_protected(rel_path: str, root: Path) -> bool:
    """True when ``rel_path`` is an ANCESTOR of a protected prefix or file:
    removing or relocating that directory takes the zone with it (§C52 --
    `tools` encloses `tools/cc/`, `.claude` the settings files, `.github` the
    CI guard workflow on every tree). The empty path and `.` enclose
    everything and answer True (the catastrophic tier walls them first; this
    is the fail-closed direction). A name that merely PREFIXES a zone
    (`tools/ccx`) encloses nothing: the comparison is on a whole component.
    Consulted only for a removed or relocated operand; a write to a
    directory's name is not a write into it, so the write checks do not ask.
    The empty path and `.` enclose everything and answer FALSE here: they
    are the catastrophic tier's (`rm -rf .`), and reading them as enclosing
    walled `find . -name '*.pyc' -delete` and `git rm -r --cached .` -- an
    everyday spelling refused harder than the dangerous one (review, driven).
    A `git clean` of the whole tree is the one whole-tree remove the zone
    check refuses, by its own effect, at the consumer.
    """
    rel_norm = _fs_equiv(rel_path, all_components=True).strip("/")
    while rel_norm.startswith("./"):
        rel_norm = rel_norm[2:]
    if rel_norm in ("", "."):
        return False
    prefix = rel_norm + "/"
    zones = list(_hook_utils.harness_protected_prefixes(root)) + sorted(PROTECTED_FILES)
    return any(_fs_equiv(zone, all_components=True).startswith(prefix) for zone in zones)


def _is_allowed(rel_path: str) -> bool:
    """Check if path is in the allowlist (agents legitimately write here).

    Case-insensitize to match ``_is_protected``: it lowercases its inputs,
    and on HFS+/NTFS ``CC/blueprints/x.json`` would match the protected
    prefix (case-insensitive) but fail the allowlist (case-sensitive),
    spuriously denying a legitimate allowlisted write.

    NFKC + casefold parity with _is_protected: without it a fullwidth
    ``CC/blueprints/x.json`` would fail the allowlist (string mismatch) but
    pass _is_protected (NFKC-aware), producing a spurious deny on a
    legitimate allowed write.

    Routes through the same ``_fs_equiv`` canonicaliser as ``_is_protected``
    so the allowlist recognises the trailing-dot / ADS spellings of a
    legitimately-allowed file (else the protected-but-not-allowed verdict
    spuriously denies it -- an over-block).
    """
    rel_norm = _fs_equiv(rel_path, all_components=False)
    allowed_files_norm = {_fs_equiv(p, all_components=False) for p in ALLOWED_IN_PROTECTED}
    if rel_norm in allowed_files_norm:
        return True
    for prefix in ALLOWED_PREFIXES_IN_PROTECTED:
        if rel_norm.startswith(_fs_equiv(prefix, all_components=False)):
            return True
    return False


# Inode-aware hardlink-alias backstop. ``_is_protected`` above compares PATH
# STRINGS, which Path.resolve() canonicalises -- but resolve CANNOT follow a
# hardlink (there is no link target), so a hardlink alias of a protected file
# at an UNPROTECTED name (``ln tools/cc/hooks/write_guard.py wg_alias``) reads
# as unprotected and a write through it rewrites protected bytes.
# This is the inode sister of the symlink class (BC-015 / _LN_S_RE). The decisive
# close is to deny a WRITE whose target inode matches a protected file's inode --
# channel-agnostic (Bash redirect, Write/Edit, PowerShell, MCP canonical field,
# and any pre-existing alias however it was created), which a creation-time
# command check alone cannot guarantee.
_INODE_WALK_BUDGET = 5000  # node cap for the protected-inode-set walk (fail-safe)


def _protected_not_allowed_inodes(root: Path) -> tuple:
    """``((st_dev, st_ino) set, complete: bool)`` for every EXISTING file whose
    repo-relative path is protected-AND-not-allowed -- the SAME predicate
    ``check_write_edit`` applies, keyed on inode so a hardlink alias at an
    unprotected name resolves to the same verdict.

    POSIX-only (``st_ino`` reliable; Windows hardlinks via ``getattr`` guard
    elsewhere). Walks ``PROTECTED_FILES`` + the harness protected prefixes,
    PRUNING allowlisted-in-protected subtrees (``cc/blueprints/`` -- a hardlink of
    an allowlist-writable file confers nothing, and that dir holds the bulk of the
    tree). ``PROTECTED_FILES`` are statted FIRST and are NEVER dropped by the
    budget. The prefix walk is bounded by ``_INODE_WALK_BUDGET``; on exhaustion it
    logs to stderr and returns ``complete=False`` so the caller can FAIL CLOSED
    (failing OPEN on exhaustion would be a wrong-direction latent weakening --
    though it is not session-reachable, since creating >budget files under a
    protected prefix is itself denied by this layer, and the real harness tree is
    ~hundreds of files vs the 5000 budget). This whole inode-budget branch is
    de-prioritized defense-in-depth: kept (deleting fails toward over-protect)
    but no self-user reaches it by slip.

    Only ever called for a write target that already passed the ``st_nlink >= 2``
    gate in ``aliases_protected_inode`` -- i.e. the rare multi-linked candidate --
    so the walk is off the hot path.
    """
    inodes = set()
    budget = [_INODE_WALK_BUDGET]

    def _add(path_obj: Path, rel: str) -> None:
        try:
            st = path_obj.stat()
        except OSError:
            return
        ino = getattr(st, "st_ino", 0)
        if not ino:
            return
        if _is_protected(rel, root) and not _is_allowed(rel):
            inodes.add((st.st_dev, ino))

    # The explicit protected FILES are few and high-value -- never budget-dropped.
    for rel in PROTECTED_FILES:
        _add(root / rel, rel)

    allowed_prefixes = tuple(p.replace("\\", "/") for p in ALLOWED_PREFIXES_IN_PROTECTED)
    root_posix = str(root).replace("\\", "/").rstrip("/")
    for prefix in _hook_utils.harness_protected_prefixes(root):
        base = root / prefix
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dp_posix = dirpath.replace("\\", "/")
            # Prune allowlisted-in-protected subtrees (cc/blueprints/ etc.) so the
            # walk skips the allowlist-writable bulk -- they would be filtered out
            # by _is_allowed anyway; pruning just avoids statting them.
            kept = []
            for d in dirnames:
                sub_posix = f"{dp_posix}/{d}"
                sub_rel = sub_posix[len(root_posix) + 1:] if sub_posix.startswith(root_posix + "/") else sub_posix
                if any((sub_rel + "/").startswith(ap) for ap in allowed_prefixes):
                    continue
                kept.append(d)
            dirnames[:] = kept
            for fn in filenames:
                budget[0] -= 1
                if budget[0] <= 0:
                    sys.stderr.write(
                        "[write_guard] A4 inode-set walk hit the node budget; "
                        "failing CLOSED for this nlink>=2 candidate\n"
                    )
                    return inodes, False
                fp = os.path.join(dirpath, fn)
                fp_posix = fp.replace("\\", "/")
                rel = fp_posix[len(root_posix) + 1:] if fp_posix.startswith(root_posix + "/") else fp_posix
                _add(Path(fp), rel)
    return inodes, True


def aliases_protected_inode(rel_path: str, root: Path, *, base: Path | None = None) -> bool:
    """True if the write target ``rel_path`` is a HARDLINK alias (same
    ``st_dev``/``st_ino``) of a protected-not-allowed file, so a write to its
    unprotected-looking name would rewrite protected bytes.

    ``rel_path`` is relative to ``base`` -- the checkout containing the target
    (``_hook_utils.resolve_in_checkout``), which is ``root`` unless the target
    sits inside a registered worktree of the repository (DEF-743) -- and that
    is where the stat happens; the protected-inode set is always the ROOT's,
    the deployed hooks whose bytes a write-through would rewrite. ``None``
    means ``root``.

    Fast-paths (return False) on: a nonexistent target (new-file write -- the
    common case), ``st_ino`` unavailable (Windows), ``st_nlink < 2`` (only one
    name -> cannot be an alias), or a non-regular-file target. The expensive
    protected-inode-set walk runs ONLY for a target that survives the
    ``nlink >= 2`` gate -- the rare suspicious write -- so the hot path is one
    ``stat``.
    """
    if not isinstance(rel_path, str) or not rel_path or rel_path == "<invalid>":
        return False
    abs_path = (root if base is None else base) / rel_path
    try:
        st = abs_path.stat()  # a hardlink IS the file -> the SHARED inode
    except OSError:
        return False
    ino = getattr(st, "st_ino", 0)
    if not ino:                              # Windows / unreliable st_ino
        return False
    if getattr(st, "st_nlink", 1) < 2:       # single name -> not an alias
        return False
    if not stat.S_ISREG(st.st_mode):         # dirs have nlink>=2; only files write
        return False
    inodes, complete = _protected_not_allowed_inodes(root)
    if not complete:
        # The protected-inode set could not be fully enumerated (walk budget hit).
        # FAIL CLOSED for this already-suspicious nlink>=2 candidate rather than
        # silently waving it through. (Not session-reachable, since flooding a
        # protected prefix is itself denied.)
        return True
    return (st.st_dev, ino) in inodes
