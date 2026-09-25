#!/usr/bin/env python3
"""Build a clean release .zip archive of the espalier source tree.

Deterministic, exclusion-driven companion to `python -m build`. Where
`build` produces an sdist/wheel governed by setuptools metadata, this
script produces a flat .zip suitable for direct download or embedding,
with an explicit allowlist of release assets and a hard-fail when any
forbidden path is about to be included.

Behavior contract:

  1. Builds from the current repo root, enumerating its git index (a root
     with no index falls back to a working-tree walk, said on stderr).
  2. Refuses to run outside the repo root (checks pyproject.toml + espalier/).
  3. Creates dist/espalier-harness-<version>-release.zip.
  4. Excludes every path classified non-public by
     ``espalier.surface_contract.classify_release_path`` (the SoT).
  5. Excludes generated reports unless explicitly allowlisted.
  6. Excludes the landed, merged and scrapped task packs, the dated archive
     files beside them and private blueprint files; the forward ledger, its
     probes file and the active packs ship (2026-09-21).
  7. Prints included file count.
  8. Prints excluded path count by rule (so drift is visible at build time).
  9. Exits 1 if any forbidden path was about to be included (the rule
     classifier and the inclusion classifier must agree by construction).

This script, ``espalier/release_pack.py``, and the
``release_check.py`` archive scanner all consume the same classifier
in ``espalier.surface_contract``. There is no duplicate
``FORBIDDEN_PATTERNS`` / ``EXCLUDED_PREFIXES`` here; everything routes
through ``classify_release_path``.
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path
from typing import Iterable

# Make the script work whether installed or run from the source tree.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from espalier import surface_contract  # noqa: E402
from espalier._safe_walk import has_git_entry  # noqa: E402
from espalier.version_surfaces import VERSION_SURFACES, read_surface_version  # noqa: E402

# Marker-based repo-root heuristic for the release build — intentionally SEPARATE from
# the tools/cc hook repo-root walk-up (env `CLAUDE_PROJECT_DIR` → ascend → cwd). Different
# environments (offline release build vs in-session hook); do not collapse the two.
REPO_MARKERS = ("pyproject.toml", "espalier")


def _find_repo_root(start: Path) -> Path:
    """Walk up from `start` until a directory containing every REPO_MARKER is found."""
    cur = start.resolve()
    for candidate in (cur, *cur.parents):
        if all((candidate / m).exists() for m in REPO_MARKERS):
            return candidate
    raise SystemExit(
        f"Could not locate repo root (looking for {REPO_MARKERS}) from {start}."
    )


def _classify(rel_posix: str) -> str | None:
    """Return the exclusion bucket name, or None if the path is includable.

    Bucket names match ``surface_contract.classify_release_path`` —
    ``"internal"``, ``"transient"``, ``"local_only"``. ``"public"``
    paths return None (no exclusion).
    """
    bucket = surface_contract.classify_release_path(rel_posix)
    return None if bucket == "public" else bucket


def _walk_repo(root: Path) -> Iterable[Path]:
    """Yield every regular file under `root`, skipping pruned directories early.

    The no-index FALLBACK enumeration; ``build_release_archive`` ships from the
    git index when the root has one.
    """
    pruned_dirs = {
        p.rstrip("/") for p in surface_contract.get_release_excluded_prefixes()
        if p.endswith("/")
    }

    def _scan(current: Path) -> Iterable[Path]:
        for entry in sorted(current.iterdir(), key=lambda p: p.name):
            rel = entry.relative_to(root).as_posix()
            # Skip symlinks before is_dir/is_file: is_file() is True for a symlink
            # to a regular file, so an in-tree symlink pointing outside the repo would
            # embed the target's bytes into the zip. Mirrors espalier/release_pack.py.
            if entry.is_symlink():
                continue
            if entry.is_dir():
                # Stop descending into known-pruned directories early.
                if any(rel == p or rel.startswith(p + "/") for p in pruned_dirs):
                    continue
                # A nested git repo is a foreign project, not part of this
                # release — never descend into it. The root-anchored prune above
                # catches only the repo-root `.git`, not a nested one.
                # `has_git_entry` is the PRUNE predicate: a dangling `.git`
                # symlink (a removed worktree, a moved admin dir) still marks a
                # foreign tree, where the own-repo test says no and descends
                # (DEF-673's shape, per _safe_walk).
                if has_git_entry(entry):
                    continue
                yield from _scan(entry)
            elif entry.is_file():
                yield entry

    yield from _scan(root)


def _read_version(root: Path) -> str:
    """Pull the [project].version from pyproject.toml via the canonical
    espalier.version_surfaces registry (VERSION_SURFACES[0]).

    Routing through the shared column-0-anchored extractor keeps the release
    build, the release gate, and the version-parity test reading the version
    the same way — an indented decoy ``version = ...`` in an earlier [tool.*]
    table cannot shadow the real [project].version. (This script already imports
    espalier for surface_contract, so the earlier 'espalier-import-free' note
    was stale.)"""
    relpath, pattern = VERSION_SURFACES[0]
    version = read_surface_version(root, relpath, pattern)
    if version is None:
        raise SystemExit("Could not parse [project].version from pyproject.toml")
    return version


def build_release_archive(root: Path, *, output_dir: Path | None = None) -> Path:
    """Build the release zip and return its path. Pure of argv; testable."""
    root = root.resolve()
    if not all((root / m).exists() for m in REPO_MARKERS):
        raise SystemExit(f"Refusing to build: {root} is not a espalier repo root.")
    version = _read_version(root)
    out_dir = (output_dir or root / "dist").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    archive_path = out_dir / f"espalier-harness-{version}-release.zip"

    included: list[Path] = []
    excluded_by_rule: dict[str, int] = {}
    leaks: list[tuple[str, str]] = []  # (rel, rule) — should never happen

    # Honor .gitattributes export-ignore — classify_release_path marks
    # ESPALIER_MEMORY.md `public`, and the enumeration below is the git index,
    # not `git archive`, so without this skip an export-ignored tracked file
    # would ship.
    export_ignored = surface_contract.export_ignore_patterns(root)
    # Sister site of the same enumeration in espalier/release_pack.py; both
    # call the one helper rather than carrying the subprocess twice. The index
    # means an untracked file never ships, whatever it classifies as; a root
    # with no index falls back to the working-tree walk (the helper warns).
    tracked = surface_contract.tracked_paths(root)
    enumeration = "tree" if tracked is None else "index"
    if tracked is None:
        candidates: Iterable[Path] = _walk_repo(root)
    else:
        candidates = (
            root / rel for rel in sorted(tracked)
            if (root / rel).is_file() and not (root / rel).is_symlink()
        )

    for path in candidates:
        rel = path.relative_to(root).as_posix()
        if any(surface_contract.matches_export_ignore(rel, p) for p in export_ignored):
            excluded_by_rule["internal"] = excluded_by_rule.get("internal", 0) + 1
            continue
        rule = _classify(rel)
        if rule is None:
            included.append(path)
        else:
            excluded_by_rule[rule] = excluded_by_rule.get(rule, 0) + 1

    if not included:
        # The sister builder's refusal, carried across with the enumeration: an
        # empty git index (nothing staged) enumerates nothing, and a 22-byte zip
        # at exit 0 is a successful-looking no-op release that the size guard
        # in release_check cannot see (an empty zip is 22 bytes, not 0).
        raise SystemExit(
            f"Refusing to write an empty release archive: nothing packageable "
            f"under {root} ({enumeration} enumeration; is the git index empty?)."
        )

    # Write the archive
    if archive_path.exists():
        archive_path.unlink()
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in included:
            rel = path.relative_to(root).as_posix()
            # Defense-in-depth: re-classify before writing. If a forbidden
            # path slipped past the inclusion filter, fail rather than ship.
            second_check = _classify(rel)
            if second_check is not None:
                leaks.append((rel, second_check))
                continue
            zf.write(path, arcname=f"espalier-harness-{version}/{rel}")

    print(f"Built: {archive_path}")
    print(f"Enumeration: {enumeration}")
    print(f"Included files: {len(included) - len(leaks)}")
    print("Excluded paths by rule:")
    for rule, count in sorted(excluded_by_rule.items()):
        print(f"  {rule}: {count}")
    if leaks:
        archive_path.unlink(missing_ok=True)
        print("FORBIDDEN content was about to be shipped:", file=sys.stderr)
        for rel, rule in leaks:
            print(f"  {rel}  (rule: {rule})", file=sys.stderr)
        raise SystemExit(1)
    return archive_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Override output directory (default: <repo>/dist).",
    )
    args = parser.parse_args(argv)

    root = _find_repo_root(Path.cwd())
    build_release_archive(root, output_dir=args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
