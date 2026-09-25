"""Release pack — bundle a distributable artifact from the repo.

Classification of "what ships publicly" is delegated to `surface_contract`.
`release_pack` and `pre_release` share that authority so they cannot drift.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from espalier import surface_contract
from espalier._atomic_io import _TEMPFILE_OPEN_FLAGS
from espalier._safe_walk import safe_rglob


@dataclass(frozen=True)
class ReleasePackSummary:
    repo_root: str
    output_zip: str
    files_written: int
    skipped_entries: list[str] = field(default_factory=list)
    skipped_internal: list[str] = field(default_factory=list)
    skipped_transient: list[str] = field(default_factory=list)
    skipped_local_only: list[str] = field(default_factory=list)
    # "index" when the archive was enumerated from the git index, "tree" when
    # the root had no index to ask and the working-tree walk stood in. A gate
    # that reads "tree" on a root that owns its `.git` has a silently degraded
    # build in front of it (git absent from PATH, dubious ownership, a moved
    # gitdir): the WARN on stderr is not something any gate reads, this is.
    enumeration: str = "index"

    def to_dict(self) -> dict:
        return {
            "repo_root": self.repo_root,
            "output_zip": self.output_zip,
            "files_written": self.files_written,
            "skipped_entries": list(self.skipped_entries),
            "skipped_internal": list(self.skipped_internal),
            "skipped_transient": list(self.skipped_transient),
            "skipped_local_only": list(self.skipped_local_only),
            "enumeration": self.enumeration,
        }


def _zipinfo_for(rel_path: Path) -> ZipInfo:
    info = ZipInfo(rel_path.as_posix())
    info.compress_type = ZIP_DEFLATED
    info.date_time = (2024, 1, 1, 0, 0, 0)
    info.external_attr = 0o644 << 16
    return info


def _atomic_write_zip(output_zip: Path, files: list[tuple[Path, Path]]) -> None:
    """Atomically write ``files`` into ``output_zip``: write a tempfile
    sibling, then os.replace onto output_zip only on success. Without this,
    ZipFile(output_zip, "w") truncates immediately — any OSError in the
    writestr loop (e.g., a source file deleted mid-flight) leaves a partial /
    corrupt ZIP at the destination, destroying any previously valid release
    artifact at that path.

    For a binary zip write, ``os.replace`` IS the atomic primitive (POSIX
    rename). Neither ``_atomic_io`` helper can carry a ``ZipFile`` stream,
    so the tempfile-and-rename is inlined here -- with the helper's create
    (mode 0o666 under the kernel umask, ``_TEMPFILE_OPEN_FLAGS``), because
    ``tempfile.mkstemp`` hardcodes 0o600 and the release artifact landed
    unreadable to the group (DEF-783). ``tests/test_atomic_io.py`` rosters
    this function as one of the writers that commit with ``os.replace``.
    """
    output_zip_path = Path(output_zip)
    output_zip_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = f".{output_zip_path.name[:64]}."
    for _attempt in range(100):
        tmp_path = os.path.join(
            str(output_zip_path.parent), prefix + os.urandom(4).hex() + ".tmp",
        )
        try:
            fd = os.open(tmp_path, _TEMPFILE_OPEN_FLAGS, 0o666)
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError(f"no free tempfile name beside {output_zip_path}")
    os.close(fd)
    try:
        with ZipFile(tmp_path, "w") as zf:
            for src, rel in files:
                data = src.read_bytes()
                zf.writestr(_zipinfo_for(rel), data)
        os.replace(tmp_path, output_zip)
    except Exception:  # noqa: BLE001 — re-raised; tempfile cleanup must run for every exit
        # Clean up tempfile on any failure so we don't litter dist/.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _is_pruned_from_walk(rel: str) -> bool:
    """Trees this walker must not enumerate.

    Each path matched here would be rejected anyway by
    ``is_transient``/``is_public_release_allowed`` -- the cost is not a wrong
    ZIP, it is one report STRING per file. On a measured run the repo's own
    ``.git`` contributed 5,455 of 10,004 skipped entries (54.5%), and a stale
    release-matrix workspace had previously contributed 8,862 more. Pruning at
    walk time keeps the payload byte-identical and stops the report growing
    with local scratch.

    NOT pushed down into ``safe_rglob``: that walker has ten other callers with
    different needs, and only this one builds a report keyed on what it
    rejected.

    **This predicate is REPORT-ONLY and must stay that way.** It runs before
    classification, so anything it matches is invisible to
    ``is_transient``/``is_public_release_allowed`` -- a second exclusion
    authority, not a filter, and the release archive already has one of those.
    ``TestWalkPruning.test_pruned_paths_are_never_shippable`` is the oracle:
    every path this returns True for must ALSO be rejected by the contract, so
    the prune can only ever remove report lines, never payload.

    Two spellings are deliberate and each has its own test:

    * ``.git`` is matched as the ROOT component, directory or bare file. Not
      as a prefix -- ``.gitignore`` and ``.gitattributes`` are tracked,
      shippable files, and ``startswith`` would silently swallow both. The
      bare file is the ``git worktree`` / submodule gitlink (``gitdir:
      /abs/path``); it stayed out of the prune while the contract still
      classified it as shippable (pruning it then would have been a payload
      change wearing a report-only label) and joined once
      ``release_noise.TRANSIENT_FILES`` rejected it. Nested repos never enter
      the index, and the tree-walk fallback prunes them upstream via
      ``safe_rglob(skip_nested_repos=True)``.
    * ``venv``/``.venv`` are matched against ``parts[:-1]`` -- the directory
      components only -- mirroring ``surface_contract.is_transient``'s own
      documented convention. A bare FILE named ``venv`` is public-release
      allowed, and matching the basename would drop it from the payload AND
      the report with no trace.
    """
    parts = rel.split("/")
    dirs = parts[:-1]
    if parts[0] == ".git":
        return True
    if "venv" in dirs or ".venv" in dirs:
        return True
    # Only the matrix workspace SUBTREE -- genuine release artifacts sitting
    # directly in dist/ are exactly what an operator wants reported (in the
    # tree-walk fallback's report; on the index branch an untracked dist/*.whl
    # is never a candidate, so it is neither shipped nor reported).
    return rel.startswith("dist/final-release-matrix/")


def create_release_zip(repo_root: Path, output_zip: Path) -> ReleasePackSummary:
    """Create a clean release zip.

    A path is included iff `surface_contract.is_public_release_allowed(rel)`.
    Excluded paths are bucketed by reason (internal / transient / local-only)
    so debugging a surprising exclusion is straightforward.
    """
    repo_root = repo_root.resolve()
    output_zip = output_zip.resolve()
    output_zip.parent.mkdir(parents=True, exist_ok=True)

    skipped_internal: list[str] = []
    skipped_transient: list[str] = []
    skipped_local_only: list[str] = []
    skipped_self: list[str] = []
    files: list[tuple[Path, Path]] = []

    # .claude/settings.json is gitignored per Pack 0 (machine-detected
    # interpreter name) but exclude it here as defense-in-depth when pack runs against a
    # working tree that has one.
    _EXTRA_LOCAL_ONLY = {".claude/settings.json"}

    # Honor .gitattributes export-ignore. classify_release_path marks
    # ESPALIER_MEMORY.md `public` (it IS a shipped managed surface), and git archive
    # excludes it via export-ignore — the enumeration below is the index, not
    # `git archive`, so without this skip ESPALIER_MEMORY.md (and any other
    # export-ignored tracked file) would ship in the zip.
    export_ignored = surface_contract.export_ignore_patterns(repo_root)

    # Enumerate the git INDEX: a file git does not track never enters the
    # archive, whatever it classifies as. (The bare tree walk shipped whatever
    # lay in the checkout; the ignore-set filter that replaced it closed only
    # the gitignored half and left an untracked public file shipping.) Only a
    # root with no index to ask falls back to the working-tree walk -- the
    # helper says so on stderr -- and there safe_rglob is symlink-safe AND
    # (default skip_nested_repos=True) prunes embedded git repos, so a foreign
    # nested repo's files never enter the zip even when they classify as
    # public. A nested repo never reaches the index branch at all: a submodule
    # is a gitlink entry that `is_file()` rejects, and a plain nested clone is
    # untracked.
    tracked = surface_contract.tracked_paths(repo_root)
    # Both branches order by the posix string, so the archive and the report
    # come out byte-stable whichever enumeration answered.
    candidates = (
        sorted(safe_rglob(repo_root), key=Path.as_posix) if tracked is None
        else [repo_root / rel for rel in sorted(tracked)]
    )
    for path in candidates:
        if not path.is_file():
            continue
        # Skip symlinks. ``is_file()`` returns True for a symlink that points
        # at a regular file — without this, a symlink inside the working tree
        # pointing to ``/etc/passwd`` (or any other file outside the repo)
        # would be embedded into the release ZIP. Same symlink-filtering
        # pattern as scope_walker.
        if path.is_symlink():
            continue
        rel_path = path.relative_to(repo_root)
        rel = rel_path.as_posix()
        # Before any classification or resolve(): these trees can never ship,
        # and enumerating them is what made the report scale with local junk.
        if _is_pruned_from_walk(rel):
            continue
        if path.resolve() == output_zip:
            skipped_self.append(rel)
            continue
        if any(surface_contract.matches_export_ignore(rel, p) for p in export_ignored):
            skipped_internal.append(rel)
            continue
        if surface_contract.is_internal_release_leak(rel):
            skipped_internal.append(rel)
            continue
        if surface_contract.is_transient(rel):
            skipped_transient.append(rel)
            continue
        if surface_contract.is_local_only(rel) or rel in _EXTRA_LOCAL_ONLY:
            skipped_local_only.append(rel)
            continue
        if not surface_contract.is_public_release_allowed(rel):
            # defense-in-depth: anything the contract disallows
            skipped_transient.append(rel)
            continue
        files.append((path, rel_path))

    # When nothing is packageable, do NOT write — and critically do NOT clobber
    # a pre-existing valid archive at output_zip. The caller keys on
    # files_written==0 to fail loudly; writing an empty 22-byte zip here (then
    # erroring) would both make the "refusing to write" message a lie AND
    # re-introduce the exact "destroy a previously valid release artifact"
    # failure the atomic-write block was added to prevent.
    if files:
        _atomic_write_zip(output_zip, files)

    all_skipped = sorted(
        skipped_internal + skipped_transient + skipped_local_only + skipped_self
    )
    return ReleasePackSummary(
        repo_root=str(repo_root),
        output_zip=str(output_zip),
        files_written=len(files),
        skipped_entries=all_skipped,
        skipped_internal=sorted(skipped_internal),
        skipped_transient=sorted(skipped_transient),
        skipped_local_only=sorted(skipped_local_only),
        enumeration="tree" if tracked is None else "index",
    )
