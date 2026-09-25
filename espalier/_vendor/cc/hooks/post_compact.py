#!/usr/bin/env python3
"""PostCompact hook — re-injects critical harness context after context compaction.

Always exits 0. Prints compact context to stderr (max 20 lines).

BC-033: the blueprint summary line emits ONLY typed-integer state
(`bp=<hex>/d<int>`). String-typed blueprint fields (continuation_fragments,
reasoning_entries[].description) never reach the priming channel — they
are operator-writable disk content that a corrupted or hand-edited
blueprint could fill with arbitrary text, so keeping them out means a
damaged blueprint degrades to no-summary rather than feeding garbage into
the next session. The cmd_load allowlist is defense-in-depth for OTHER
consumers; the typed-integer-only path is the load-bearing closure here.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
# Second path push reaches `tools/cc/` (one level up from `tools/cc/hooks/`)
# so we can import the shared blueprint-limits constant. This is the first
# hook to need the parent-dir level on sys.path; future hooks importing
# from `tools/cc/` follow the same pattern.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _hook_utils  # noqa: E402
from _hook_utils import os_error_text  # noqa: E402
from _hook_utils import STATE_DIR, check_branch, repo_name, surface_status, warn_exc  # noqa: E402
from _blueprint_limits import BLUEPRINT_MAX_SIZE  # noqa: E402


_resolve_project_root = _hook_utils.resolve_project_root


def _read_blueprint_safe(root: Path) -> str | None:
    """Read cc/blueprints/latest.json with size cap + symlink refusal.

    BC-038 mirror: symlink-refused + size-capped read at the
    consumption point. Mirrors the same guards `_load_latest` applies
    in `tools/cc/cognitive_blueprint.py`. Returns None for any failure
    mode (missing, symlinked, oversize, unreadable) — caller treats
    None as "no blueprint summary available."
    """
    bp = root / "cc" / "blueprints" / "latest.json"
    try:
        if not bp.is_file() or bp.is_symlink():
            return None
        if bp.stat().st_size > BLUEPRINT_MAX_SIZE:
            return None
        return bp.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # A BOM/non-UTF-8 latest.json raises UnicodeDecodeError (a ValueError,
        # not OSError); without this it escapes _read_blueprint_safe, crashes
        # _run_main, and drops the whole post-compaction re-orientation.
        return None


def _blueprint_summary(root: Path) -> str:
    """Emit ONLY typed-integer blueprint state (BC-033 primary defense).

    Reads `cc/blueprints/latest.json` directly (no subprocess to cmd_load)
    and emits `bp=<hex_sid>/d<int_depth>`. String-typed fields
    (continuation_fragments, reasoning_entries[].description) are
    operator-controllable and never reach the priming channel — that
    closes BC-033 unconditionally. `session_id` is sanitized to hex-only
    `[a-f0-9]{0,16}` (the writer-side already generates hex-only ids;
    this is reader-side robustness against a corrupted or hand-edited
    blueprint, so a damaged file degrades to no-summary, never a crash).
    Empty string means "no summary"; caller skips the line.
    """
    raw = _read_blueprint_safe(root)
    if raw is None:
        return ""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        warn_exc("post_compact: malformed blueprint json", e)
        return ""
    # A valid-JSON non-dict blueprint must not crash data.get.
    if not isinstance(data, dict):
        return ""
    sid = data.get("session_id", "")
    depth = data.get("accumulated_depth", 0)
    if not isinstance(sid, str) or not isinstance(depth, int):
        return ""
    safe_sid = re.sub(r"[^a-f0-9]", "", sid.lower())[:16]
    return f"bp={safe_sid}/d{depth}"


_SUMMARY_MAX_BYTES = 200 * 1024 * 1024  # refuse a pathological transcript


def _capture_compact_summary(root: Path, transcript_path: str) -> None:
    """Persist the verbatim native compaction summary to a durable artifact.

    BC-033 (load-bearing): the summary is operator-writable free text, so it is
    written to a SEPARATE file and is NEVER returned to the caller, added to the
    stderr priming block, or written into latest.json. This function only
    *captures*; the artifact is surfaced solely on explicit pull (/handoff,
    /read-summary). Best-effort: every failure mode degrades to "no artifact
    written," never a crash or a deny (advisory hook fails open).

    Symlink discipline runs on BOTH sides: the transcript is refused if it is a
    symlink (input), and the output dir + dest file are refused if symlinked
    (output) — cc/blueprints/ is Write-allowed, so a planted symlink there would
    otherwise make the append write THROUGH it to an arbitrary target. The stem
    is refused if it carries a path separator (Windows backslash edge) so dest
    can never escape out_dir.
    """
    if not transcript_path:
        return
    tp = Path(transcript_path)
    try:
        if not tp.is_file() or tp.is_symlink():
            return
        if tp.stat().st_size > _SUMMARY_MAX_BYTES:
            return
        stem = tp.stem
        if "/" in stem or "\\" in stem or stem in ("", ".", ".."):
            return
        latest = None
        with tp.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"isCompactSummary"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(obj, dict) or not obj.get("isCompactSummary"):
                    continue
                msg = obj.get("message")
                content = msg.get("content") if isinstance(msg, dict) else None
                if isinstance(content, list):
                    content = "".join(
                        p.get("text", "") for p in content if isinstance(p, dict)
                    )
                if isinstance(content, str) and content:
                    latest = content
        if latest is None:
            return
        out_dir = root / "cc" / "blueprints" / "compact_summaries"
        if out_dir.is_symlink():
            return
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{stem}.md"
        if dest.is_symlink():
            return
        header = f"\n\n===== compaction captured (transcript {stem}) =====\n\n"
        with dest.open("a", encoding="utf-8") as out:
            out.write(header + latest + "\n")

        # Live working-summary doc: the always-current "tool" doc. OVERWRITE
        # (never stale) with the verbatim summary + the espalier resume index.
        # BC-033 preserved: write-only, never injected / never in latest.json.
        live = root / "cc" / "_working_summary.md"
        if live.is_symlink():
            return
        try:
            import sys as _sys
            _here = str(Path(__file__).resolve().parent.parent)  # tools/cc/
            if _here not in _sys.path:
                _sys.path.insert(0, _here)
            from session_summary import build_resume_index  # sibling, stdlib-only

            # cwd=root so _transcript_path resolves against the SAME root as the
            # git/fs reads (the hook's cwd is not guaranteed to be the repo root).
            index = build_resume_index(root, cwd=root)
        except Exception:  # noqa: BLE001 -- fail-open: import/index failure must never break the capture
            index = ""  # fail-open: still write the summary body
        # Atomic write: a crash mid-rewrite must not leave a truncated/empty
        # live doc that read_summary would surface as the (false) current state.
        _hook_utils.atomic_write_text(live, latest + "\n" + index + "\n")
    except (OSError, ValueError, TypeError):
        return


def _run_main() -> int:
    from _hook_utils import read_stdin_safely  # noqa: E402

    # read_stdin_safely() returns an ALREADY-PARSED dict (or {} on any failure);
    # it tolerates BOM / non-UTF-8 stdin. Do NOT json.loads it again.
    payload = read_stdin_safely()

    root = _resolve_project_root()

    # BC-033: capture is write-only to a SEPARATE artifact; nothing it reads
    # ever reaches the stderr block below or latest.json. Fail-open: a capture
    # failure must never break the post-compaction re-orientation.
    try:
        _capture_compact_summary(root, str(payload.get("transcript_path", "")))
    except (OSError, ValueError, TypeError):
        pass

    name = repo_name(root, warn_label="post_compact")
    branch = check_branch(root)
    surface = surface_status(root, degraded_format="paren")
    blueprint = _blueprint_summary(root)

    lines = [
        "=== POST-COMPACTION CONTEXT ===",
        f"Repo:    {name}",
        f"Branch:  {branch}",
        f"Surface: {surface}",
    ]

    if blueprint:
        lines.append(f"Blueprint: {blueprint}")

    lines.append("")
    # An adopter repo has no espalier/ source tree (the package is
    # installed, not vendored). Naming it leaks self-host vocab. Gate it.
    if _hook_utils.is_self_host_repo(root):
        managed = "tools/cc/ and espalier/ are harness-managed"
    else:
        managed = "tools/cc/ is harness-managed"
    lines.append(f"RESUME: you were mid-task -- run /status to re-orient, continue the active plan, finish via /handoff. ({managed}; change them via /implement-task, not by hand.)")
    lines.append("=" * 31)

    # Enforce max 20 lines
    output = "\n".join(lines[:20])
    print(output, file=sys.stderr)

    # Producer for CP-COMPACT. The first mutating PreToolUse after
    # compaction reads this flag (the model's plan was rebuilt from a summary,
    # not retained). Empty sentinel file -- existence is the bit; no string
    # state reaches any priming channel (BC-033 safe). Cleared at
    # SessionStart (session_start._clean_state_flags). Best-effort: if the drop
    # fails, CP-COMPACT simply won't fire (fail toward no-nudge, never a deny).
    try:
        flag = root / STATE_DIR / "post_compact_pending"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("", encoding="utf-8")
    except OSError:
        pass

    return 0


def main() -> int:
    """Public entry-point. Fail-OPEN umbrella: post_compact is an advisory
    PostCompact reporter, so an uncaught crash must degrade to a no-op advisory
    (exit 0 + one [ERROR] line), never a traceback that breaks the post-compaction
    re-orientation. Mirrors task_router.main.
    """
    try:
        return _run_main()
    except BaseException as exc:  # noqa: BLE001 — fail-open crash guard (advisory hook)
        print(
            f"[ERROR] post_compact crashed: {type(exc).__name__}: {os_error_text(exc)}",
            file=sys.stderr,
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
