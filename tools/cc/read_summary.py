#!/usr/bin/env python3
"""Read the verbatim post-compaction summary from a CC session transcript.

Claude Code records each compaction as a ``user`` transcript entry with
``isCompactSummary: true``; ``message.content`` holds the 9-section summary
(containing a native "read the full transcript at: <path>" pointer, usually
near the end). There is no built-in command to re-display a past summary, so
this reader extracts it from ``~/.claude/projects/<encoded-cwd>/<session>.jsonl``.

Stdlib-only (``tools/cc/`` runs standalone, zero espalier imports).

Usage:
    python3 tools/cc/read_summary.py                 # latest summary, current repo's newest session
    python3 tools/cc/read_summary.py --all           # every compaction in that session
    python3 tools/cc/read_summary.py --index 0        # the first (oldest) compaction
    python3 tools/cc/read_summary.py --list          # sessions for this repo + their compaction counts
    python3 tools/cc/read_summary.py --session <id>  # a specific session id
    python3 tools/cc/read_summary.py --path <file>   # an explicit .jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _json_safe import decode_text_or_problem  # noqa: E402

_MAX_BYTES = 200 * 1024 * 1024  # refuse pathological transcripts (fail-soft)


def _project_dir(cwd: Path) -> Path:
    """The ~/.claude/projects/<encoded> dir for ``cwd``.

    CC encodes the project dir by replacing every non-alphanumeric CHARACTER in
    the absolute cwd with ``-`` (``/Users/x/Repo`` -> ``-Users-x-Repo``;
    ``/Users/x/.cfg`` -> ``-Users-x--cfg``). Per-character, NOT per-run: a run
    of adjacent separators (a leading-dot dir, ``a/../b``) yields one dash each,
    so collapsing runs would compute the wrong dir and find no transcript.
    """
    enc = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    return Path.home() / ".claude" / "projects" / enc


def _safe_mtime(p: Path) -> float:
    """``st_mtime`` for ``p``, or ``0.0`` if it vanished mid-scan (CC GCs transcripts)."""
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _sessions(proj: Path) -> list[Path]:
    """Session .jsonl files for the project, newest first."""
    if not proj.is_dir():
        return []
    files = [p for p in proj.glob("*.jsonl") if p.is_file() and not p.is_symlink()]
    return sorted(files, key=_safe_mtime, reverse=True)


def _summaries(jsonl: Path) -> list[str]:
    """Verbatim text of every ``isCompactSummary`` entry, in file order."""
    if not jsonl.is_file() or jsonl.is_symlink():
        return []
    out: list[str] = []
    try:
        if jsonl.stat().st_size > _MAX_BYTES:
            return []
        with jsonl.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"isCompactSummary"' not in line:
                    continue  # cheap pre-filter before json.loads
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(obj, dict) or not obj.get("isCompactSummary"):
                    continue
                content = (obj.get("message") or {}).get("content")
                if isinstance(content, list):
                    content = "".join(
                        p.get("text", "") for p in content if isinstance(p, dict)
                    )
                if isinstance(content, str) and content:
                    out.append(content)
    except OSError:
        return []
    return out


_ARTIFACT_HEADER = re.compile(
    r"\n*=====\s+compaction captured \(transcript [^)]*\)\s+=====\n*"
)
# Known limit: if a captured summary BODY contains this exact header phrase
# verbatim, split() yields spurious blocks. Acceptable — CC-generated summary
# prose carries hex session ids, not the literal "===== compaction captured" line.


def _artifact_dir() -> Path:
    """The local-only dir post_compact.py persists captured summaries under.

    Keyed off ``Path.cwd()`` — the same cwd-is-repo-root contract the transcript
    half (``_project_dir``) already assumes, so both halves of one command
    resolve the same root. Durable copy that outlives the GC'd ``.jsonl``.
    """
    return Path.cwd() / "cc" / "blueprints" / "compact_summaries"


def _artifact_summaries(md: Path) -> list[str]:
    """Per-compaction blocks from a persisted artifact, in append order."""
    if not md.is_file() or md.is_symlink():
        return []
    try:
        if md.stat().st_size > _MAX_BYTES:
            return []
        text = md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [b.strip() for b in _ARTIFACT_HEADER.split(text) if b.strip()]


def _resolve_artifact(args: argparse.Namespace) -> Path | None:
    """The artifact file for the requested session, or the newest one."""
    d = _artifact_dir()
    if not d.is_dir():
        return None
    if args.session:
        cand = d / f"{args.session}.md"
        return cand if cand.is_file() and not cand.is_symlink() else None
    files = [p for p in d.glob("*.md") if p.is_file() and not p.is_symlink()]
    return max(files, key=_safe_mtime) if files else None


def _resolve(args: argparse.Namespace) -> Path | None:
    if args.path:
        return Path(args.path).expanduser()
    proj = _project_dir(Path.cwd())
    sessions = _sessions(proj)
    if args.session:
        for p in sessions:
            if p.stem == args.session:
                return p
        return None
    return sessions[0] if sessions else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read a CC post-compaction summary.")
    ap.add_argument("--list", action="store_true", help="list sessions + compaction counts")
    ap.add_argument("--all", action="store_true", help="print every compaction, not just the latest")
    ap.add_argument("--index", type=int, default=None, help="print the Nth compaction (0-based)")
    ap.add_argument("--session", default=None, help="session id (the .jsonl stem)")
    ap.add_argument("--path", default=None, help="explicit transcript .jsonl path")
    args = ap.parse_args(argv)

    if args.list:
        proj = _project_dir(Path.cwd())
        sessions = _sessions(proj)
        seen: set[str] = set()
        for p in sessions:
            seen.add(p.stem)
            print(f"  {p.stem}  compactions={len(_summaries(p))}  [transcript]")
        d = _artifact_dir()
        durable = (
            sorted(d.glob("*.md"), key=_safe_mtime, reverse=True) if d.is_dir() else []
        )
        for p in durable:
            if p.stem in seen or p.is_symlink():
                continue
            print(f"  {p.stem}  compactions={len(_artifact_summaries(p))}  [durable]")
        if not sessions and not durable:
            print(f"read_summary: no transcripts for this repo at {proj}")
        return 0

    # Default (BARE invocation, no mode flag): dump the LIVE working-summary doc
    # — the entire current picture + espalier additions. The guard MUST exclude
    # --all/--index too (they browse a transcript's compaction legs); only a bare
    # call with no mode flag is intercepted. --session/--path read history.
    if not (args.list or args.session or args.path or args.all
            or args.index is not None):
        live = Path.cwd() / "cc" / "_working_summary.md"
        if live.is_file() and not live.is_symlink():
            body, problem = decode_text_or_problem(live.read_bytes())
            if problem:
                # A re-encoded or hand-edited doc (DEF-797): name the encoding
                # to re-save in rather than traceback out of the reader.
                print(f"read_summary: cc/_working_summary.md is {problem}", file=sys.stderr)
                return 1
            # Content-gate: a 0-byte / whitespace-only live doc (e.g. a torn
            # write) must NOT be surfaced as the current state — fall through to
            # the missing-doc hint instead of printing a blank line.
            if body.strip():
                print(body)
                return 0
        print("read_summary: no cc/_working_summary.md yet "
              "(written at the first compaction or at /handoff; empty/torn reads as missing).",
              file=sys.stderr)
        return 0

    jsonl = _resolve(args)
    summaries = _summaries(jsonl) if (jsonl and jsonl.is_file()) else []

    # Durable fallback: when the TARGETED transcript is gone (GC'd after ~30d), read
    # the persisted capture the post-compaction hook wrote. Gated on transcript
    # ABSENCE — a present but not-yet-compacted transcript keeps its "no compaction
    # summary yet" path, so a fresh session never bleeds a prior session's artifact.
    # --path is exempt: an explicit transcript pointer is honored verbatim (existing
    # exit codes/text).
    if not summaries and not args.path and not (jsonl and jsonl.is_file()):
        art = _resolve_artifact(args)
        arts = _artifact_summaries(art) if art is not None else []
        if arts:
            print(f"[read_summary: from durable artifact {art.stem}]", file=sys.stderr)
            summaries = arts

    if not summaries:
        if jsonl is None or not jsonl.is_file():
            print("read_summary: no matching transcript (try --list).", file=sys.stderr)
            return 1
        print(f"read_summary: {jsonl.stem} has no compaction summary yet.")
        return 0

    if args.all:
        for i, s in enumerate(summaries):
            print(f"===== compaction {i} / {len(summaries) - 1} =====\n{s}\n")
        return 0
    idx = args.index if args.index is not None else len(summaries) - 1
    if not -len(summaries) <= idx < len(summaries):
        print(f"read_summary: index {idx} out of range (0..{len(summaries) - 1}).", file=sys.stderr)
        return 1
    print(summaries[idx])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
