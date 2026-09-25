#!/usr/bin/env python3
"""Archive a Claude Code transcript tree to a verified, dated tarball.

Why this exists, measured on 2026-08-31: Claude Code auto-prunes
``~/.claude/projects`` on a retention timer. ``cleanupPeriodDays`` had never been
set on this machine, so the default applied and the oldest surviving transcript
was ``2026-07-31`` against a ``2026-04-30`` first commit -- roughly three months
of session history was already gone when anyone looked. Setting
``cleanupPeriodDays`` stops the clock; it does not create a second copy, and a
single-disk machine with no Time Machine destination is one failure from losing
all of it.

THE FAILURE THIS IS BUILT AGAINST is not "the archive is missing". A missing
archive is loud -- you look in the directory and it is not there. The dangerous
outcome is an archive that EXISTS, is well-formed gzip, and is short: it reads as
a backup and is not one.

Verification is therefore three gates, all required, and the file only takes its
final name after all three pass:

    1. ``tarfile`` completed AND skipped nothing. A file it could not add is a
       hard failure, not a silent omission.
    2. ``gzip`` decompresses the whole stream (``verify_archive`` reads it).
    3. The archive's member count equals ``len(snapshot)`` -- the list taken
       BEFORE writing -- never the count of what tar managed to write.

Gate 3's comparand is easy to get wrong. An earlier revision passed
``build_archive``'s return value, which decrements once per skipped file -- so
every loss subtracted from BOTH sides of the equality and the gate could never
fire. A red-team pass caught it by making one source file unreadable: 7 files in,
6 archived, "verified", exit 0.

A lost file is now caught by TWO independent detectors, and mutation testing
confirms neither alone is decorative -- removing either leaves the property
intact, removing both breaks it:

    * gate 1 (the skip list) catches it at ADD time and names which file;
    * gate 3 catches it at VERIFY time, structurally, by comparing against
      ``len(snapshot)``.

Because gate 1 makes ``added == len(files)`` whenever the run proceeds, the two
comparands are provably equal at gate 3 -- so no single mutation can distinguish
them, and ``verify_archive``'s own unit test pins its logic directly instead. Do
not "simplify" by deleting one: they detect at different moments, and the failure
this file exists to prevent is precisely the one where a single detector was
believed to be watching and was not.

What gate 3 still cannot catch is a snapshot that was wrong to begin with, so two
further things are recorded rather than assumed: ``walk_errors`` (a directory the
walk could not enter -- previously swallowed, which silently dropped its whole
subtree) and ``drift`` from a fresh post-write walk. Drift is reported and never
fatal, because the tree legitimately grows while this runs. Do not "fix" that by
making the post-walk authoritative -- a growing tree would read as a failed
archive.

THRESHOLD SEMANTICS: growth since the last archive, not absolute size. With
retention pinned the source only grows (~1.2 GB/month measured), so an absolute
threshold would re-archive the entire tree on every run once crossed. The last
archived size lives in a sidecar manifest, scoped to the source it came from --
a manifest written by a run against a different ``--source`` is ignored rather
than used as a baseline, which would otherwise latch this permanently quiet.

A source that SHRANK is the single most important signal this tool can produce,
so it is not folded into the quiet path: it archives immediately and exits 4.

Exit codes are distinct on purpose, because "the job ran fine" must not mean
several different things to a scheduler:

    0  archived and verified
    1  script error / refused (bad arguments, unreadable source, target exists)
    2  verification FAILED -- the partial archive was discarded
    3  below threshold, nothing written (not an error)
    4  archived, AND the source had shrunk since the last run -- investigate

This script never writes to the source tree and never deletes a transcript. It
prunes only archives it recorded in its own manifest, never the archive it just
wrote, and never below one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SOURCE = Path.home() / ".claude" / "projects"
DEFAULT_DEST = Path.home()
DEFAULT_THRESHOLD_MB = 512
DEFAULT_KEEP = 4
ARCHIVE_PREFIX = "claude-transcripts-"
#: tar compression -> archive suffix. gzip is the default: fast and about 1 MB
#: of memory. xz packs the same transcripts roughly a third smaller (measured
#: 2026-09-14 on a 32 MB transcript sample: 6.75 MB at gzip -6, 4.47 MB at
#: lzma preset 6, the tarfile default) for about ten times the CPU and a
#: 110 MB peak -- the trade a destination with a quota wants, and a nightly
#: job can afford. The suffix names the codec, so a directory can hold both
#: and ``prune_archives`` treats them as one population.
ARCHIVE_SUFFIXES: dict[str, str] = {"gz": ".tgz", "xz": ".txz"}
DEFAULT_COMPRESSION = "gz"
ARCHIVE_SUFFIX = ARCHIVE_SUFFIXES[DEFAULT_COMPRESSION]
MANIFEST_NAME = ".archive_transcripts_manifest.json"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_VERIFY_FAILED = 2
EXIT_BELOW_THRESHOLD = 3
EXIT_SOURCE_SHRANK = 4


def snapshot_source(source: Path) -> tuple[list[str], int, list[str]]:
    """Return (sorted relative paths, total bytes, walk errors).

    Taken ONCE, before the archive is written, and it is this list -- not a live
    walk -- that is handed to tar. A tree being written to while it is archived
    would otherwise produce a member set nothing can verify against.

    ``walk_errors`` is the third element because the previous revision passed
    ``onerror=lambda _e: None``, which discarded exactly the information needed
    to notice that an unreadable or symlinked directory had removed its entire
    subtree from the archive while every gate still passed.
    """
    files: list[str] = []
    errors: list[str] = []
    total = 0

    def _onerror(exc: OSError) -> None:
        errors.append(f"{getattr(exc, 'filename', '?')}: {exc.strerror or exc}")

    for dirpath, dirnames, filenames in os.walk(source, onerror=_onerror):
        for d in dirnames:
            full = Path(dirpath) / d
            if full.is_symlink():
                # os.walk does not follow it, so its contents would vanish from
                # the archive with no other trace.
                errors.append(f"{full}: symlinked directory not followed")
        for name in filenames:
            full = Path(dirpath) / name
            try:
                total += full.lstat().st_size
            except OSError as exc:
                errors.append(f"{full}: {exc.strerror or exc}")
                continue
            files.append(str(full.relative_to(source)).replace("\\", "/"))
    files.sort()
    return files, total, errors


def build_archive(
    source: Path, files: list[str], out_tmp: Path, arcroot: str,
    compression: str = DEFAULT_COMPRESSION,
) -> tuple[int, list[str]]:
    """Write the tarball from the SNAPSHOT list. Returns (added, skipped).

    ``skipped`` is returned rather than swallowed. The caller treats a non-empty
    skip list as a hard failure: a file this could not add is missing from a
    thing that will be called a backup.
    """
    added = 0
    skipped: list[str] = []
    with tarfile.open(out_tmp, f"w:{compression}") as tar:
        for rel in files:
            full = source / rel
            try:
                tar.add(full, arcname=f"{arcroot}/{rel}", recursive=False)
            except (OSError, ValueError) as exc:
                skipped.append(f"{rel}: {type(exc).__name__}: {exc}")
                continue
            added += 1
    return added, skipped


def verify_archive(
    path: Path, expected_members: int, compression: str = DEFAULT_COMPRESSION,
) -> tuple[bool, dict]:
    """Decompress the whole archive and count its members.

    Opened as the codec it was written with, not auto-detected: an archive of
    the wrong shape is a failed verification, never a passed one.

    Counts regular files, symlinks and hardlinks. ``TarInfo.isfile()`` alone is
    ``isreg()``, which excludes SYMTYPE/LNKTYPE -- so a source containing one
    symlink made a correctly-written archive fail verification and be discarded
    on every run, training the operator to disable the gate.
    """
    report: dict = {"expected_members": expected_members}
    try:
        with tarfile.open(path, f"r:{compression}") as tar:
            actual = sum(1 for m in tar if m.isfile() or m.issym() or m.islnk())
    except (tarfile.TarError, OSError, EOFError) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["actual_members"] = None
        return False, report

    report["actual_members"] = actual
    report["sha256"] = _sha256(path)
    report["bytes"] = path.stat().st_size
    if actual != expected_members:
        report["error"] = (
            f"member count mismatch: archive has {actual}, snapshot had "
            f"{expected_members}"
        )
        return False, report
    return True, report


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(dest: Path) -> dict:
    try:
        data = json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_manifest(dest: Path, data: dict) -> None:
    tmp = dest / (MANIFEST_NAME + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, dest / MANIFEST_NAME)


def prune_archives(
    dest: Path, keep: int, protect: Path | None = None, known: list[str] | None = None
) -> list[Path]:
    """Delete all but the ``keep`` newest archives. Never leaves zero.

    Three refusals, each earned from a demonstrated failure:

    * ``protect`` -- the archive this run just wrote is never a candidate. A
      pre-existing file with a future mtime otherwise sorted ahead of it and the
      run deleted its own output while reporting success.
    * ``known`` -- only archives this tool recorded are eligible. The glob alone
      cannot tell its own output from a file restored by hand from a backup
      drive, which is by construction the copy holding unique history.
    * the floor -- ``keep`` is clamped to at least 1, and the clamp decides
      WHICH copy lives: the list is newest-first, so an unclamped ``keep=0``
      slices from index 0 and deletes the newest.
    """
    archives = sorted(
        (p for p in dest.glob(f"{ARCHIVE_PREFIX}*")
         if p.is_file() and p.suffix in ARCHIVE_SUFFIXES.values()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if protect is not None:
        archives = [p for p in archives if p != protect]
    if known is not None:
        archives = [p for p in archives if p.name in known]
    if keep < 1:
        keep = 1
    if len(archives) <= keep:
        return []
    removed = []
    for old in archives[keep:]:
        # Recomputed every iteration: the floor must hold against the CURRENT
        # count, not the count when the loop started (a concurrent run may be
        # deleting too).
        remaining = [p for p in archives if p.exists()]
        if len(remaining) <= 1:
            break
        try:
            old.unlink()
            removed.append(old)
        except OSError:
            continue
    return removed


def render_plist(
    script: Path, python: str, hour: int = 3, extra_args: tuple[str, ...] = (),
) -> str:
    """Emit a launchd plist with absolute paths already filled in.

    Generated rather than documented so the scheduling instructions cannot drift
    from the script, and ``extra_args`` -- the options the previewing invocation
    was given -- ride along so the installed job runs exactly what was
    previewed. This is printed, never installed -- a recurring background job
    on someone's machine is theirs to authorise.
    """
    from xml.sax.saxutils import escape
    extra = "".join(f"    <string>{escape(a)}</string>\n" for a in extra_args)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.espalier.archive-transcripts</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>{script}</string>
{extra}  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>{hour}</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>{Path.home()}/Library/Logs/archive-transcripts.log</string>
  <key>StandardErrorPath</key><string>{Path.home()}/Library/Logs/archive-transcripts.log</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
"""


_REPORT_KEYS = (
    "source", "files", "source_bytes", "last_archived_bytes", "growth_bytes",
    "threshold_bytes", "decision", "archive", "actual_members",
    "expected_members", "skipped", "walk_errors", "post_walk_files", "drift",
    "sha256", "pruned", "note", "error",
)


def _report(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    for key in _REPORT_KEYS:
        if payload.get(key) not in (None, [], ""):
            print(f"  {key}: {payload[key]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    ap.add_argument("--threshold-mb", type=float, default=DEFAULT_THRESHOLD_MB)
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    ap.add_argument("--compression", choices=sorted(ARCHIVE_SUFFIXES), default=DEFAULT_COMPRESSION,
                    help="gz (default: fast, ~1 MB of memory) or xz (about a third smaller, "
                         "a 110 MB peak, ~10x the CPU)")
    ap.add_argument("--force", action="store_true",
                    help="archive regardless of threshold, and replace an existing target")
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    ap.add_argument("--print-plist", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--now", default=None, help="ISO date stamp override (testing)")
    args = ap.parse_args(argv)

    if args.print_plist:
        # The five scheduling options this invocation was given are recorded in
        # the plist, so the job launchd runs is the one that was previewed, and
        # the plist says where the archives go and how without reading this
        # file. A source that does not exist is refused here, not discovered
        # nightly in a log nobody reads; a missing dest is only noted, because
        # the run creates its last component (never a missing parent).
        src_dir = args.source.expanduser()
        if not src_dir.is_dir():
            print(f"error: --source is not a directory: {src_dir} -- refusing to render a "
                  "plist for a job that would fail every night", file=sys.stderr)
            return EXIT_ERROR
        dst_dir = args.dest.expanduser()
        if not dst_dir.is_dir():
            print(f"note: --dest does not exist yet: {dst_dir} -- its parent must, the first "
                  "run creates the last component", file=sys.stderr)
        recorded = (
            "--source", str(args.source.expanduser().resolve()),
            "--dest", str(args.dest.expanduser().resolve()),
            "--compression", args.compression,
            "--keep", str(args.keep),
            "--threshold-mb", str(args.threshold_mb),
        )
        print(render_plist(Path(__file__).resolve(), sys.executable, extra_args=recorded))
        return EXIT_OK

    source: Path = args.source.expanduser()
    dest: Path = args.dest.expanduser()
    if not source.is_dir():
        print(f"error: source is not a directory: {source}", file=sys.stderr)
        return EXIT_ERROR
    if not args.check:
        try:
            # NOT parents=True: a missing parent means an unmounted volume, and
            # fabricating the tree writes the archive to the internal disk under
            # a stale mountpoint where it vanishes when the drive is attached.
            dest.mkdir(exist_ok=True)
        except OSError as exc:
            print(f"error: unusable --dest {dest}: {exc}", file=sys.stderr)
            return EXIT_ERROR

    files, source_bytes, walk_errors = snapshot_source(source)
    manifest = read_manifest(dest)

    payload: dict = {
        "source": str(source),
        "files": len(files),
        "source_bytes": source_bytes,
        "walk_errors": walk_errors,
    }

    # A manifest written against a DIFFERENT source is not a baseline for this
    # one; using it latches the threshold permanently shut.
    recorded_source = manifest.get("source")
    if recorded_source is not None and recorded_source != str(source):
        payload["note"] = (
            f"manifest baseline is from {recorded_source!r}; treating as first run"
        )
        manifest = {}

    last_raw = manifest.get("source_bytes")
    try:
        last_bytes = None if last_raw is None else int(last_raw)
    except (TypeError, ValueError):
        payload["note"] = "manifest source_bytes unreadable; treating as first run"
        last_bytes = None

    threshold_bytes = int(args.threshold_mb * 1024 * 1024)
    growth = None if last_bytes is None else source_bytes - last_bytes
    payload["last_archived_bytes"] = last_bytes
    payload["growth_bytes"] = growth
    payload["threshold_bytes"] = threshold_bytes

    shrank = growth is not None and growth < 0
    over = last_bytes is None or shrank or (growth is not None and growth >= threshold_bytes)

    if not files:
        payload["decision"] = "source has 0 files -- refusing to write an empty archive"
        _report(payload, args.json)
        return EXIT_VERIFY_FAILED

    if walk_errors and not args.force:
        payload["decision"] = (
            "refusing: the walk could not read part of the source, so the "
            "snapshot is incomplete (pass --force to archive anyway)"
        )
        _report(payload, args.json)
        return EXIT_VERIFY_FAILED

    if args.check:
        payload["decision"] = "would archive" if (over or args.force) else "below threshold"
        _report(payload, args.json)
        if shrank:
            return EXIT_SOURCE_SHRANK
        return EXIT_OK if (over or args.force) else EXIT_BELOW_THRESHOLD

    if not over and not args.force:
        payload["decision"] = "below threshold -- nothing written"
        _report(payload, args.json)
        return EXIT_BELOW_THRESHOLD

    stamp = args.now or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    suffix = ARCHIVE_SUFFIXES[args.compression]
    final = dest / f"{ARCHIVE_PREFIX}{stamp}{suffix}"
    tmp = dest / f"{ARCHIVE_PREFIX}{stamp}.{os.getpid()}{suffix}.tmp"

    # Any codec's archive for this stamp is the day's archive: a same-day switch
    # of --compression must not quietly write a second one and halve retention.
    clash = next(
        (dest / f"{ARCHIVE_PREFIX}{stamp}{s}" for s in ARCHIVE_SUFFIXES.values()
         if (dest / f"{ARCHIVE_PREFIX}{stamp}{s}").exists()),
        None,
    )
    if clash is not None and not args.force:
        payload["decision"] = (
            f"refusing: {clash.name} already exists for {stamp} -- pass --force to replace it"
        )
        _report(payload, args.json)
        return EXIT_ERROR

    payload["decision"] = (
        "SOURCE SHRANK since the last run -- archiving now" if shrank else "archiving"
    )

    try:
        added, skipped = build_archive(source, files, tmp, arcroot=source.name,
                                       compression=args.compression)
        payload["skipped"] = skipped
        if skipped:
            tmp.unlink(missing_ok=True)
            payload["decision"] = "VERIFICATION FAILED -- files could not be added"
            _report(payload, args.json)
            return EXIT_VERIFY_FAILED

        # len(files), NOT `added`. See the module docstring: `added` decrements
        # with every loss, so comparing against it can never fail.
        ok, report = verify_archive(tmp, len(files), compression=args.compression)
        payload.update(report)
        post_files, _post_bytes, _post_errors = snapshot_source(source)
        payload["post_walk_files"] = len(post_files)
        payload["drift"] = len(post_files) - len(files)

        if not ok:
            tmp.unlink(missing_ok=True)
            payload["decision"] = "VERIFICATION FAILED -- archive discarded"
            _report(payload, args.json)
            return EXIT_VERIFY_FAILED

        os.replace(tmp, final)
        payload["archive"] = str(final)

        known = list(dict.fromkeys([*manifest.get("known_archives", []), final.name]))
        write_manifest(
            dest,
            {
                "source": str(source),
                "source_bytes": source_bytes,
                "files": len(files),
                "archive": final.name,
                "sha256": report["sha256"],
                "stamp": stamp,
                "known_archives": known,
            },
        )
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        payload["error"] = f"{type(exc).__name__}: {exc}"
        payload["decision"] = "VERIFICATION FAILED -- run did not complete"
        _report(payload, args.json)
        return EXIT_VERIFY_FAILED

    removed = prune_archives(dest, args.keep, protect=final, known=known)
    payload["pruned"] = [p.name for p in removed]
    _report(payload, args.json)
    return EXIT_SOURCE_SHRANK if shrank else EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
