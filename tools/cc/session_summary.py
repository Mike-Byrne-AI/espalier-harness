#!/usr/bin/env python3
"""Emit the deterministic 'resume index' block for the handoff session summary.

Mechanical only (git + filesystem + computed paths) so the index can never
drift or hallucinate. The narrative half of ``cc/_working_summary.md`` is
written by the agent during ``/handoff`` (and the verbatim summary at
compaction); this script produces the pointer table appended beneath it.
Stdlib-only (``tools/cc/`` runs standalone, zero espalier imports).

Usage:
    python3 tools/cc/session_summary.py            # print the index block to stdout
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Reuse the cwd->~/.claude/projects resolver from read_summary instead of
# inlining a second copy. The encoding is PER-CHARACTER (a run of adjacent
# separators -> one dash each); a re-encode that collapses runs computes the
# wrong dir for leading-dot paths and silently finds no transcript. Sibling
# import via sys.path, mirroring session_resume.py -> _paths.
# read_summary's main() is __main__-guarded, so importing it has no side
# effect.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_summary import _project_dir, _safe_mtime  # noqa: E402

# Cap the resume-index compaction-leg list so a long-lived checkout does not
# render hundreds of paths. Newest legs are the useful ones; older are elided.
_COMPACTION_LEG_DISPLAY_CAP = 12


def _project_root() -> Path:
    """Git toplevel, or cwd when not in a work tree (graceful)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):  # strict decode: a structured answer (DEF-821)
        pass
    return Path.cwd()


def _transcript_path(cwd: Path) -> str:
    """Newest CC transcript for this repo, via read_summary's tested resolver.

    ``_safe_mtime`` tolerates a ``.jsonl`` vanishing mid-scan (CC GCs
    transcripts), so the max() key never raises.
    """
    proj = _project_dir(cwd)
    if not proj.is_dir():
        return "(no local transcript dir)"
    jsonls = [p for p in proj.glob("*.jsonl") if p.is_file() and not p.is_symlink()]
    if not jsonls:
        return f"(no transcript under {proj})"
    return str(max(jsonls, key=_safe_mtime))


def _git(root: Path, *args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""


def _recent_edits(root: Path) -> list[str]:
    """Uncommitted changes + recent commits (mechanical; the agent's narrative
    refines intent)."""
    lines: list[str] = []
    staged = _git(root, "status", "--short")
    if staged:
        lines.append("Uncommitted:")
        lines += [f"  {ln}" for ln in staged.splitlines()[:30]]
    log = _git(root, "log", "--oneline", "-n", "5")
    if log:
        lines.append("Recent commits:")
        lines += [f"  {ln}" for ln in log.splitlines()]
    return lines or ["(clean tree, no recent commits)"]


def _compaction_legs(root: Path) -> list[str]:
    """The most-recent per-compaction captures the PostCompact hook persisted,
    newest first, capped to _COMPACTION_LEG_DISPLAY_CAP with an elision line
    when older legs exist.

    Symlinks are skipped for parity with read_summary's artifact resolver.
    """
    d = root / "cc" / "blueprints" / "compact_summaries"
    if not d.is_dir():
        return ["(none — no compaction captures present)"]
    files = [p for p in d.glob("*.md") if p.is_file() and not p.is_symlink()]
    if not files:
        return ["(none captured)"]
    files.sort(key=_safe_mtime, reverse=True)
    shown = files[:_COMPACTION_LEG_DISPLAY_CAP]
    lines = [f"cc/blueprints/compact_summaries/{p.name}" for p in shown]
    elided = len(files) - len(shown)
    if elided:
        lines.append(f"(+{elided} older legs elided)")
    return lines


def build_resume_index(root: Path, cwd: Path | None = None) -> str:
    """The deterministic espalier resume-index block rendered beneath the summary
    in the working-summary doc.

    Mechanical only (git + filesystem + computed paths) so it can never drift.
    Reused by ``/handoff`` and by the post-compaction hook so both boundaries
    produce the same ``[summary] + [index]`` shape. ``cwd`` (default
    ``Path.cwd()``) is the transcript-resolution root — pass it explicitly from a
    hook so it matches ``root`` (no cwd/root split-brain on the transcript
    pointer).
    """
    cwd = cwd or Path.cwd()
    out = ["", "## Resume index (mechanical — regenerated each boundary)", ""]
    out += [f"- **Full transcript:** `{_transcript_path(cwd)}`", ""]
    out += ["- **Recent edits:**"] + [f"  - {ln}" for ln in _recent_edits(root)] + [""]
    out += ["- **Recent compaction legs (all sessions, newest first):**"] + \
           [f"  - {ln}" for ln in _compaction_legs(root)] + [""]
    out += [
        "- **Footguns / known issues (pointers — do not restate):**",
        "  - Relevant footguns/failure-modes: pull with `/recall <topic>` "
        "(indexes SHARP_EDGES + FAILURE_MODES); per-surface footguns also fire "
        "via the folder CLAUDE.md ladder on entry.",
        "  - Known blockers: ESPALIER_MEMORY.md Session Log + the blueprint `Next steps`.",
        "",
    ]
    return "\n".join(out)


def main() -> int:
    print(build_resume_index(_project_root()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
