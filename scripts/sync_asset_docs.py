#!/usr/bin/env python3
"""Regenerate espalier/assets/ doc mirrors from their docs/ (+ task-packs/) sources.

Assets ship via package-data and MUST be byte-identical to source —
tests/test_deploy_doc_parity.py::TestSourceAssetDocByteParity pins the
assets/docs/** bodies and a targeted test in the same module pins
assets/task-packs/CLAUDE.md. Run after editing any carried doc so the mirror
stays in lockstep with its source.

After the copy (and under ``--check``) the seeded docs are read for
maintainer-addressed text, the count the audience gate holds to
``espalier.surface_hygiene.SEED_BASELINE``: over the ceiling, the sync exits 1
with the per-file counts, the source each is fixed at, and the hits new in this
lane -- each mirror body judged against its committed form (the merge-base with
origin's default branch, else HEAD; the replaced mirror body where there is no
git), so a second run after a refusal names the same words. The walk is git's
view of the checkout, as the gate's is. The parity copy is made first, so the
refusal is the ceiling's alone. This sync is the first step the handoff's fold
into docs/FAILURE_MODES.md runs; the landing check's test selection
(``scripts/check_handoff_landing.py::SELECTION``) is the stop before the push. A
fold of four catalog rows carried six hits past the ceiling through both, and
the pull request's test cells said so first (2026-10-25).
"""
from __future__ import annotations

import argparse
import functools
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _mirrored() -> tuple[str, ...]:
    """DERIVE the mirror set from the deploy inventory, don't hand-keep it.

    A seed is mirrored iff ``init`` copies its body straight out of
    ``espalier/assets/<dest>`` -- i.e. iff its asset source is the identity.
    The two Tier-3 stubs (``docs/SHARP_EDGES.md``, ``docs/CONVENTIONS.md``)
    redirect to ``seed/`` and have no source twin, so they fall out naturally
    rather than needing an exclusion.

    This was a hand-written tuple, and it failed the first time it was tested:
    adding ``docs/HOOK_ASSUMPTIONS.md`` to the deploy set left the mirror
    un-synced and silently stale, so `init` shipped the OLD body while the
    source read correct -- the enumeration-drift class (§C1) inside the very
    script that exists to keep two copies in step. Derived, that cannot recur.
    """
    from espalier import managed_inventory

    return tuple(
        rel for rel in sorted(managed_inventory.get_seed_docs())
        if managed_inventory.get_seed_asset_source(rel) == rel
    )


_MIRRORED: tuple[str, ...] = _mirrored()


def _diff_only() -> list[str]:
    """Byte-parity drift for the ``_MIRRORED`` set, WITHOUT copying. Returns
    human-readable drift lines (empty == in parity)."""
    drift: list[str] = []
    for rel in _MIRRORED:
        src = _ROOT / rel
        dst = _ROOT / "espalier" / "assets" / rel
        if not src.is_file():
            drift.append(f"missing source: {rel}")
        elif not dst.is_file():
            drift.append(f"missing asset: espalier/assets/{rel}")
        elif src.read_bytes() != dst.read_bytes():
            drift.append(f"stale asset: espalier/assets/{rel} != {rel}")
    return drift


_ASSETS = "espalier/assets/"
_GIT_TIMEOUT_S = 20


def _bounded_spawn():
    """``run_bounded`` from this checkout's ``tools/cc/_json_safe.py``, loaded by
    path: ``subprocess.run`` whose timeout holds on Windows, where ``run`` waits
    on a grandchild holding its pipe (Git for Windows's launcher is one)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_json_safe_for_sync_asset_docs", _ROOT / "tools" / "cc" / "_json_safe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_bounded


run_bounded = _bounded_spawn()


def _git(*args: str) -> bytes | None:
    """``git -C <root> <args>``'s stdout, or None when git is absent, the root is
    no checkout, or the command fails (a ref or a path that does not resolve)."""
    try:
        proc = run_bounded(
            ["git", "-C", str(_ROOT), *args], capture_output=True, timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _baseline() -> tuple[str | None, str]:
    """``(ref, label)``: the committed form each mirror is judged against -- the
    merge-base with origin's default branch, else HEAD; ``(None, label)`` where
    git cannot answer, and the mirror body this sync replaced stands in. Read off
    git, not the mirror on disk: a refused run has already copied, so a second
    run judged against the disk would find nothing new and name no word."""
    if _git("rev-parse", "--verify", "-q", "HEAD") is None:
        return None, "the mirror body this sync replaced"
    default = _git("rev-parse", "--abbrev-ref", "origin/HEAD")
    if default is not None:
        name = default.decode("utf-8", errors="replace").strip()
        base = _git("merge-base", "HEAD", name)
        if base is not None:
            return base.decode("ascii", errors="replace").strip(), f"the merge-base with {name}"
    return "HEAD", "HEAD"


def _committed(ref: str, rel: str) -> bytes | None:
    """``espalier/assets/<rel>`` as committed at ``ref``; None when absent there."""
    return _git("show", f"{ref}:{_ASSETS}{rel}")


def _git_view(base: Path) -> Iterable[Path]:
    """The files git sees under ``base`` (tracked, and untracked but not ignored):
    the audience gate's view, so a scratch file git ignores is no hit here either.
    The directory as it is where git cannot answer."""
    out = _git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", str(base))
    if out is None:
        return base.rglob("*")  # espalier:safe-walk-ok the packaged assets of this checkout, never an adopter tree
    return [_ROOT / rel for rel in out.decode("utf-8", errors="replace").split("\0") if rel]


@functools.lru_cache(maxsize=1)
def _deployed_prefixes() -> tuple[str, ...]:
    from espalier.managed_inventory import get_managed_public_prefixes

    return tuple(get_managed_public_prefixes())


def _seeded_hits() -> dict[str, list[tuple[str, str]]]:
    """Every seeded text file's maintainer-addressed hits by repo-relative path:
    the audience gate's own walk (``espalier.surface_hygiene.seeded_marker_hits``)."""
    from espalier import surface_hygiene

    return surface_hygiene.seeded_marker_hits(
        _ROOT, deployed_prefixes=_deployed_prefixes(), walk=_git_view,
    )


def _hits_of(body: bytes | None) -> Counter:
    from espalier import surface_hygiene

    text = (body or b"").decode("utf-8", errors="replace")
    return Counter(surface_hygiene.maintainer_marker_hits(text, deployed_prefixes=_deployed_prefixes()))


def _source_of(asset_rel: str) -> str:
    rel = asset_rel[len(_ASSETS):] if asset_rel.startswith(_ASSETS) else ""
    if rel in _MIRRORED:
        return f"fix at {rel}, then run this sync again"
    return "its own source: no mirror row"


def _ceiling_lines(
    by_file: dict[str, list[tuple[str, str]]],
    *,
    check: bool,
    label: str = "",
    new_hits: dict[str, Counter] | None = None,
    differing: int = 0,
) -> tuple[bool, list[str]]:
    """``(over, lines)``: the count line; over the ceiling, the refusal with the
    per-file counts highest first, the source each is fixed at, and (a sync) the
    hits new against ``label`` (``new_hits``: asset path -> the hits its committed
    form lacked; ``differing``: how many mirror bodies differ from it at all)."""
    from espalier.surface_hygiene import SEED_BASELINE

    date, ceiling = SEED_BASELINE
    total = sum(len(hits) for hits in by_file.values())
    if total <= ceiling:
        return False, [
            f"seeded docs: {total} of {ceiling} maintainer-addressed hits (ceiling taken {date})",
        ]
    lines = [
        f"REFUSED: the seeded docs carry {total} maintainer-addressed hits, "
        f"over the ceiling of {ceiling} taken {date}.",
        "  Per file, highest first:",
    ]
    for rel, hits in sorted(by_file.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"  {len(hits):5d}  {rel}  ({_source_of(rel)})")
    if check:
        lines.append("  (--check reads the mirrors as they are; a DRIFT line above means the source differs.)")
    elif new_hits:
        lines.append(f"  New against {label}:")
        for rel, counted in new_hits.items():
            for (family, match), n in counted.most_common():
                times = f" x{n}" if n > 1 else ""
                lines.append(f"    {rel}: [{family}] {match!r}{times}")
    elif differing:
        bodies = "mirror body differs" if differing == 1 else "mirror bodies differ"
        lines.append(f"  {differing} {bodies} from {label} and gained no hit: "
                     "the excess is in bodies committed before this lane.")
    else:
        lines.append(f"  No mirror body differs from {label}: "
                     "the excess is in bodies committed before this lane.")
    lines.append("  Reword the new text at its source (named per file above); never raise the ceiling.")
    lines.append("REFUSED (exit 1): " + (
        "the seeded docs are over the ceiling." if check
        else "the mirrors are copied, and the seeded docs are over the ceiling."
    ))
    return True, lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sync (or --check) the asset doc mirrors.")
    ap.add_argument(
        "--check", action="store_true",
        help="verify source<->asset byte-parity WITHOUT writing; nonzero exit on drift "
             "or on seeded docs over the audience ceiling",
    )
    ns = ap.parse_args(argv)
    if ns.check:
        drift = _diff_only()
        for d in drift:
            print(f"DRIFT: {d}", file=sys.stderr)
        over, lines = _ceiling_lines(_seeded_hits(), check=True)
        print("\n".join(lines), file=sys.stderr if over else sys.stdout)
        if drift or over:
            return 1
        print(f"check: {len(_MIRRORED)} asset doc mirror(s) in parity")
        return 0
    ref, label = _baseline()
    replaced: dict[str, bytes | None] = {}
    for rel in _MIRRORED:
        src = _ROOT / rel
        dst = _ROOT / "espalier" / "assets" / rel
        replaced[rel] = dst.read_bytes() if dst.is_file() else None
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    synced = f"synced {len(_MIRRORED)} asset doc mirrors"
    new_hits: dict[str, Counter] = {}
    differing = 0
    for rel in _MIRRORED:
        after = (_ROOT / "espalier" / "assets" / rel).read_bytes()
        baseline = _committed(ref, rel) if ref is not None else replaced[rel]
        if after == baseline:
            continue
        differing += 1
        gained = _hits_of(after) - _hits_of(baseline)
        if gained:
            new_hits[f"{_ASSETS}{rel}"] = gained
    over, lines = _ceiling_lines(
        _seeded_hits(), check=False, label=label, new_hits=new_hits, differing=differing,
    )
    if over:
        print(synced, file=sys.stderr)
        print("\n".join(lines), file=sys.stderr)
        return 1
    print(synced)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
