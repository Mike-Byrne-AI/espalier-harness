#!/usr/bin/env python3
"""Regenerate .github/workflows/harness-guard.yml from its packaged asset.

This mirror runs the OPPOSITE way to every other one in this repo. Elsewhere the
working-tree file is the source of truth and the copy under ``espalier/assets/``
or ``espalier/_vendor/`` is generated. Here the packaged asset
``espalier/assets/github/workflows/harness-guard.yml`` is the source -- it is
what ``espalier init`` deploys into an adopter's repo -- and the root workflow
file is this repo's own generated copy of it.

That inversion is the whole reason this script exists. "Edit the file where it
lives, then sync the packaged copy" is correct for eight of the nine mirror rows
in ``espalier/mirror_registry.py`` and wrong for this one, and the wrong case is
a workflow file that looks exactly like its neighbours in the same directory.
Until now it also had no sync script, so a reader who noticed the drift had
nothing to run -- the correction was a hand copy, which is precisely the state
that let a hand-edit of the generated file reach a full-suite red.

Byte-parity is pinned by
``tests/test_package_resource_parity.py::TestRootMirrorParity::test_root_workflow_mirrors_package``.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
#: Source of truth -- the packaged asset, NOT the root file.
_ASSET = Path("espalier/assets/github/workflows/harness-guard.yml")
#: The generated copy.
_ROOT_MIRROR = Path(".github/workflows/harness-guard.yml")


def _read(rel: Path) -> bytes:
    return (_ROOT / rel).read_bytes()


def _root_file_status() -> str:
    """``"dirty"`` / ``"clean"`` / ``"unknown"`` for the generated root file.

    Tri-state on purpose. An earlier version collapsed "git could not answer" into
    "dirty", which fails in the safe DIRECTION but then reports a fact it never
    established: run this in a git-less container or an unpacked sdist and it
    refused while claiming the file had uncommitted changes. A refusal whose
    stated reason is false is one the reader learns to bypass, and the only
    bypass here is ``--force``, which also disables the protection for the case
    it exists for.
    """
    try:
        completed = subprocess.run(
            # as_posix(): a git pathspec must use forward slashes, and str() on a
            # Path yields backslashes on Windows. Same reason as the repo-wide
            # `.replace("\\", "/")` path convention.
            ["git", "status", "--porcelain", "--", _ROOT_MIRROR.as_posix()],
            cwd=_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return "unknown"
    if completed.returncode != 0:
        return "unknown"
    return "dirty" if completed.stdout.strip() else "clean"


def _git(*args: str) -> "subprocess.CompletedProcess[str] | None":
    """Run git in ``_ROOT``; ``None`` when git cannot be reached at all."""
    try:
        return subprocess.run(
            ["git", *args], cwd=_ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _last_commit_sha(rel: Path) -> "str | None":
    """SHA of the last commit to touch ``rel``; ``None`` if unknowable."""
    completed = _git("log", "-1", "--format=%H", "--", rel.as_posix())
    if completed is None or completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _root_diverged_at_its_last_commit(root_sha: str) -> "bool | None":
    """Were the two sides ALREADY different at the root file's last commit?

    This is the question the guard actually needs, and asking anything else has
    now failed three times:

    * ``git status`` cleanliness is a PROXY for "the root holds unmirrored work",
      and a commit falsifies the proxy while leaving the fact unchanged -- the
      original defect, where a committed root edit was copied over silently.
    * Committer TIMESTAMPS cannot order two commits made in the same second, and
      are reordered by rebase. That cut let the dangerous case straight through.
    * ANCESTRY ("did the root's commit descend the asset's?") is wrong in BOTH
      directions. It false-refuses the ordinary workflow -- commit an asset edit,
      sync, commit the root alone, and from then on the root's commit descends
      the asset's forever, so every later asset edit is refused with a reason
      that is not true and the only exit is ``--force``. And it silently allows
      the dangerous case when both sides land in ONE commit (equal SHAs, which
      ancestry reports as "did not move after"), which is a live shape in a repo
      whose convention is a broad ``git add -A`` straight to main.

    Content at the root's last commit separates all of them, because a sync
    commit leaves the two sides EQUAL and a root-side hand-edit leaves them
    DIFFERENT -- regardless of ordering, timing, or whether the commit also
    touched the asset.

    ``True``  -- that commit carries root-side work the asset never received.
    ``False`` -- they were in parity then, so today's difference is the asset
                 moving forward, which is exactly what this script exists to
                 propagate.
    ``None``  -- git could not answer; the caller refuses rather than guessing.
    """
    root_blob = _git("show", f"{root_sha}:{_ROOT_MIRROR.as_posix()}")
    if root_blob is None or root_blob.returncode != 0:
        return None
    asset_blob = _git("show", f"{root_sha}:{_ASSET.as_posix()}")
    if asset_blob is None:
        return None
    if asset_blob.returncode != 0:
        # The asset did not exist yet at the root's last commit, so the asset is
        # the newer side by construction. Not root-side work -- proceed.
        return False
    return root_blob.stdout != asset_blob.stdout


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Sync (or --check) the harness-guard workflow mirror "
                    "(packaged asset -> repo root)."
    )
    ap.add_argument(
        "--check", action="store_true",
        help="verify asset↔root byte-parity WITHOUT writing; nonzero exit on drift",
    )
    ap.add_argument(
        "--force", action="store_true",
        help="overwrite the root file even when it has uncommitted changes",
    )
    ns = ap.parse_args(argv)

    src = _ROOT / _ASSET
    if not src.is_file():
        print(f"missing source of truth: {_ASSET}", file=sys.stderr)
        return 1
    # Refuse to operate on an empty source, matching sync_vendor_cc.py and
    # sync_claude_mirrors.py. Without it a truncated asset would propagate to the
    # root file and silently disable the workflow.
    if src.stat().st_size == 0:
        print(f"refusing to sync from an EMPTY source: {_ASSET}", file=sys.stderr)
        return 1

    dst = _ROOT / _ROOT_MIRROR
    if ns.check:
        if not dst.is_file():
            print(f"DRIFT: {_ROOT_MIRROR} does not exist", file=sys.stderr)
            return 1
        if _read(_ASSET) != _read(_ROOT_MIRROR):
            # Name the direction in the failure text. A reader who reaches this
            # line is already holding the wrong mental model, and "they differ"
            # would let them fix it backwards.
            print(
                f"DRIFT: {_ROOT_MIRROR} differs from its source {_ASSET}.\n"
                f"  The ASSET is the source of truth; the root file is generated.\n"
                f"  Re-apply any root-only change to the asset, then re-run this script.",
                file=sys.stderr,
            )
            return 1
        print(f"check: {_ROOT_MIRROR} in parity with {_ASSET}")
        return 0

    # The dangerous case, and the reason this guard exists: every other workflow
    # in .github/workflows/ is edited in place, so the habitual move is to edit
    # the root file. Someone who does that, sees the parity test red, and reaches
    # for this script would have their edit overwritten -- and the script would
    # print "synced" and exit 0. That is the manual data loss this script was
    # written to prevent, automated. Refuse when the root file carries
    # uncommitted work and the two sides actually differ.
    if not ns.force and dst.is_file() and _read(_ASSET) != _read(_ROOT_MIRROR):
        status = _root_file_status()
        if status != "clean":
            reason = (
                "it has uncommitted changes" if status == "dirty"
                else "git could not report its status (not a repo, or git unavailable)"
            )
            print(
                f"REFUSING to overwrite {_ROOT_MIRROR}: {reason}, "
                f"and it differs from {_ASSET}.\n"
                f"  This mirror runs asset -> root. Syncing now would DISCARD any "
                f"edit to the root file.\n"
                f"  If you meant to change the workflow, move the edit to the asset "
                f"and re-run.\n"
                f"  If this root file is only the OUTPUT of an earlier run of this "
                f"script -- you edited the asset, synced, then edited the asset again "
                f"without committing in between -- then the edit is already where it "
                f"belongs and --force is the correct move here.\n"
                f"  If you are certain the root copy is disposable, re-run with "
                f"--force.",
                file=sys.stderr,
            )
            return 1
        # git says clean, so any divergence is COMMITTED -- and a commit is exactly
        # what falsifies the cleanliness proxy above. Ask whether the two sides were
        # already diverged at the root's last commit: a sync commit leaves them
        # EQUAL, a root-side hand-edit leaves them DIFFERENT. See
        # _root_diverged_at_its_last_commit for why ordering (timestamp, ancestry)
        # is the wrong question and fails in both directions.
        root_sha = _last_commit_sha(_ROOT_MIRROR)
        diverged = _root_diverged_at_its_last_commit(root_sha) if root_sha else None
        if diverged is not False:
            detail = (
                "git could not read the two sides at that commit, so it cannot rule "
                "out" if diverged is None else
                "at its last commit the two sides ALREADY differed, so that commit "
                "carries"
            )
            print(
                f"REFUSING to overwrite {_ROOT_MIRROR}: it differs from {_ASSET} and "
                f"{detail} a root-side edit the source of truth never received.\n"
                f"  git reports it clean -- that only means the edit was committed, "
                f"not that it is safe to discard.\n"
                f"  This mirror runs asset -> root. Re-apply the root-side change to "
                f"{_ASSET}, then re-run.\n"
                f"  To see what would be lost: git diff -- {_ASSET} {_ROOT_MIRROR}\n"
                f"  If the root copy really is disposable, re-run with --force.",
                file=sys.stderr,
            )
            return 1

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"synced {_ROOT_MIRROR} <- {_ASSET}")
    print(
        "  note: this path is in _integrity.MANIFEST_FILES -- "
        "run `espalier integrity refresh .` before commit."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
