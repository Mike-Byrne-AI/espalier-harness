#!/usr/bin/env python3
"""PostCompact hook — captures the compaction summary and arms the
post-compaction checkpoint; it re-injects nothing.

Always exits 0. Three effects: the verbatim compaction summary is captured to
``cc/blueprints/compact_summaries/`` and the live ``cc/_working_summary.md``
(pull-only); the ``post_compact_pending`` flag arms write_guard's CP-COMPACT
checkpoint for the first mutating call; and a short re-orientation block
(max 20 lines) goes to stderr -- which reaches Claude Code's DEBUG LOG ONLY.
PostCompact has no channel to Claude under the protocol pin
(docs/external/cc-hook-protocol.md: no additionalContext, ``systemMessage``
discarded, exit-2 stderr shown to the user only), so that block is a debug
record, declared as such. What re-orients the session is SessionStart, which
the pin re-fires with source ``compact`` after every compaction: its banner
carries the live state. A fault here is recorded once a session
(``say_once``), since stderr alone would reach nobody.

BC-033: the blueprint summary line emits ONLY typed-integer state
(`bp=<hex>/d<int>`). String-typed blueprint fields (continuation_fragments,
reasoning_entries[].description) never reach the stderr block — they
are operator-writable disk content that a corrupted or hand-edited
blueprint could fill with arbitrary text, so keeping them out means a
damaged blueprint degrades to no-summary rather than feeding garbage into
the next session. The cmd_load allowlist is defense-in-depth for OTHER
consumers; the typed-integer-only path is the load-bearing closure here.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
# Second path push reaches `tools/cc/` (one level up from `tools/cc/hooks/`)
# so we can import the shared blueprint-limits constant. This is the first
# hook to need the parent-dir level on sys.path; future hooks importing
# from `tools/cc/` follow the same pattern.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _hook_utils  # noqa: E402
from _hook_utils import STATE_DIR, check_branch, repo_name, surface_status  # noqa: E402
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
    except (OSError, UnicodeDecodeError) as exc:
        # A BOM/non-UTF-8 latest.json raises UnicodeDecodeError (a ValueError,
        # not OSError); without this it escapes _read_blueprint_safe, crashes
        # _run_main, and drops the capture and the checkpoint flag with it.
        # Recorded once a session: the blueprint line is skipped, not silently
        # empty, and stderr alone would reach the debug log only.
        _hook_utils.say_once(
            root, f"post_compact-blueprint-read-{type(exc).__name__}", "post_compact",
            "postcompact_failed_open_blueprint_read",
            f"cc/blueprints/latest.json could not be read ({type(exc).__name__}); "
            "the post-compaction blueprint line is skipped",
            fault=type(exc).__name__,
        )
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
        _hook_utils.say_once(
            root, "post_compact-blueprint-json", "post_compact",
            "postcompact_failed_open_blueprint_json",
            f"cc/blueprints/latest.json is not valid JSON ({type(e).__name__}); "
            "the post-compaction blueprint line is skipped",
            fault=type(e).__name__,
        )
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
    stderr block, or written into latest.json. This function only
    *captures*; the artifact is surfaced solely on explicit pull (/handoff,
    /read-summary). Best-effort: every failure mode degrades to "no artifact
    written," never a crash or a deny (advisory hook fails open); the two that
    lose an artifact the capture had in hand are recorded once a session.

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
        except Exception as exc:  # noqa: BLE001 -- fail-open: import/index failure must never break the capture
            index = ""  # fail-open: still write the summary body, and say the index is missing
            _hook_utils.say_once(
                root, f"post_compact-resume-index-{type(exc).__name__}", "post_compact",
                "postcompact_failed_open_resume_index",
                f"the resume index was not built ({type(exc).__name__}); "
                "cc/_working_summary.md carries the summary without it",
                fault=type(exc).__name__,
            )
        # Atomic write: a crash mid-rewrite must not leave a truncated/empty
        # live doc that read_summary would surface as the (false) current state.
        _hook_utils.atomic_write_text(live, latest + "\n" + index + "\n")
    except (OSError, ValueError, TypeError) as exc:
        _hook_utils.say_once(
            root, f"post_compact-working-summary-{type(exc).__name__}", "post_compact",
            "postcompact_failed_open_working_summary",
            f"the compaction summary was not captured ({type(exc).__name__}); "
            "cc/_working_summary.md and the per-session archive keep their previous text",
            fault=type(exc).__name__,
        )
        return


def _load_mail() -> Any:
    """``tools/cc/mail.py`` by path (the parent-dir level this hook already
    reaches), under a private alias so a test's own instance of the module is
    left alone; None where it is not deployed, which costs the line only."""
    path = Path(__file__).resolve().parent.parent / "mail.py"
    if not path.is_file():
        return None
    alias = "_post_compact_mail"
    mod = sys.modules.get(alias)
    if mod is None:
        spec = importlib.util.spec_from_file_location(alias, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[alias] = mod
        spec.loader.exec_module(mod)
    return mod


def _mail_unread_line(root: Path, mail: Any = None, timeout: float = 3.0) -> str:
    """``N unread (a from <machine>, ...) -- /inbox`` from the LOCAL refs and
    the cursor, no fetch: a compaction is mid-session, and the fetch is
    SessionStart's. '' where no machine is named here, nothing is unread, or
    the channel module is not deployed. Reporter: a failure costs the line
    and is recorded once a session; ``timeout`` bounds each local git read under the hook's own
    ceiling. ``mail`` is the channel module, injectable for tests."""
    try:
        mail = mail if mail is not None else _load_mail()
        if mail is None:
            return ""
        machine, _how = mail.machine_setting(root, timeout=timeout)
        if machine is None:
            return ""
        by_machine, _skipped = mail.read_mail(root, timeout=timeout)
        pending = mail.unread(by_machine, mail.read_cursor(root), exclude_machine=machine)
        if not pending:
            return ""
        counts: dict[str, int] = {}
        for m in pending:
            who = str(m.get("from") or "?")
            counts[who] = counts.get(who, 0) + 1
        parts = ", ".join(f"{n} from {who}" for who, n in sorted(counts.items()))
        return f"{len(pending)} unread ({parts}) -- /inbox for the bodies; the other machine's text, unverified"
    except Exception as exc:  # noqa: BLE001 — bounded, never break the hook
        _hook_utils.say_once(
            root, f"post_compact-mail-{type(exc).__name__}", "post_compact",
            "postcompact_failed_open_mail",
            f"the unread-mail line could not be read ({type(exc).__name__}); it is omitted",
            fault=type(exc).__name__,
        )
        return ""


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

    mail = _mail_unread_line(root)
    if mail:
        lines.append(f"Mail:    {mail}")

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
    # voice: debug-log PostCompact has no channel to Claude; the SessionStart banner the pin re-fires after compaction re-orients
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
    except OSError:  # fail-open: ok telemetry -- the post-compaction checkpoint window; a flag that cannot be written costs one advisory, never the context
        pass

    return 0


def main() -> int:
    """Public entry-point. Fail-OPEN umbrella: post_compact is an advisory
    PostCompact reporter, so an uncaught crash must degrade to a no-op (exit 0,
    recorded once a session through ``say_crash``), never a traceback. Mirrors
    task_router.main.
    """
    try:
        return _run_main()
    except BaseException as exc:  # noqa: BLE001 — fail-open crash guard (advisory hook)
        # Exit 0, so a stderr line alone reaches the debug log only (the
        # protocol pin): the record, once a session, is what `/status --log`
        # counts, with the stderr line as its copy.
        _hook_utils.say_crash(
            "post_compact", "postcompact_failed_open_crash", exc,
            "the post-compaction capture did not run",
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
