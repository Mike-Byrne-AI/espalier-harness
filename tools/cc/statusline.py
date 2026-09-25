#!/usr/bin/env python3
"""Espalier statusline — observable state in one line.

Outputs pipe-separated indicators of the current harness state so
operators see at a glance:

- ``MAINT``           when ``ESPALIER_MAINTENANCE_MODE=1`` is exported
                      (otherwise easy to forget; the docs/SHARP_EDGES.md
                      "sticky env-var debt" footgun).
- ``STOP=full|light`` when ``ESPALIER_STOP_GATE`` is set; full enables
                      the opt-in pytest stop_gate path.
- ``bp=<id>/d<N>``    short id + accumulated depth of the active
                      cognitive blueprint chain (from cc/blueprints/
                      latest.json).

Stdlib-only, zero espalier imports. Never raises on missing state;
prints ``espalier`` alone when nothing is observable.
"""
from __future__ import annotations

import json
import os
import stat as _stat
import sys
from pathlib import Path

# Sibling import: shared blueprint cap constant.
# tools/cc/ scripts can import siblings; only `espalier` imports are forbidden.
from _blueprint_limits import BLUEPRINT_MAX_SIZE
from _freshness_cache import _is_state_cache_stale, _read_state_cache_safe
from _json_safe import os_error_text

# BC-027b: in-content amplification defense.
# A blueprint under the byte cap can still be a JSON bomb (deep nesting
# or one giant string field). Post-load walk caps both.
MAX_BLUEPRINT_STRING_BYTES = 4096
MAX_BLUEPRINT_DEPTH = 10


def _read_blueprint_safe(path: Path) -> str | None:
    """Read latest blueprint with fd-level symlink refusal + bounded size.

    BC-027: an unbounded read_text on a symlinked or oversize
    latest.json hangs or delays every prompt cycle, AND silently
    disables the MAINT / STOP visibility signal that makes
    maintenance-mode observable.

    Returns None on: missing file, symlink (rejected at open() via
    O_NOFOLLOW), non-regular file (named pipe / socket / device —
    caught by fstat S_ISREG), oversize, or any read error. Closing
    the lstat/open TOCTOU window requires fd-level atomicity:
    O_NOFOLLOW raises ELOOP on symlinks, O_NONBLOCK refuses
    blocking opens on FIFOs / devices.

    The POSIX-only ``O_*`` flags are ``getattr``-guarded so this does
    not ``AttributeError`` on Windows, where those constants are absent.
    On Windows the guarded flags collapse to 0 — the open still succeeds
    (losing fd-level symlink/nonblock protection, which Windows does not
    provide anyway).
    """
    try:
        fd = os.open(
            str(path),
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not _stat.S_ISREG(st.st_mode):
            return None
        if st.st_size > BLUEPRINT_MAX_SIZE:
            return None
        raw_bytes = os.read(fd, BLUEPRINT_MAX_SIZE + 1)
        if len(raw_bytes) > BLUEPRINT_MAX_SIZE:
            return None
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return None
    except OSError:
        return None
    finally:
        os.close(fd)


def _parse_blueprint_safe(raw: str) -> dict | None:
    """Parse blueprint JSON with depth + per-string byte bounds.

    BC-027b: the 128 KB byte cap still admits a JSON bomb
    (deeply nested arrays or a single huge string field that
    amplifies on traversal). Walk the tree post-load, capping both.
    `parse_constant` rejects NaN/Infinity inline at json.loads —
    downstream `json.dumps` would re-serialize those and break
    consumers that expect strict JSON.
    """
    try:
        data = json.loads(raw, parse_constant=lambda _t: None)
    except (json.JSONDecodeError, ValueError):
        return None

    def _walk(node: object, depth: int) -> bool:
        if depth > MAX_BLUEPRINT_DEPTH:
            return False
        if isinstance(node, str):
            return len(node.encode("utf-8")) <= MAX_BLUEPRINT_STRING_BYTES
        if isinstance(node, dict):
            return all(
                isinstance(k, str)
                and len(k) <= MAX_BLUEPRINT_STRING_BYTES
                and _walk(v, depth + 1)
                for k, v in node.items()
            )
        if isinstance(node, list):
            return all(_walk(item, depth + 1) for item in node)
        return True  # numbers / bool / None — bounded by JSON syntax

    if not _walk(data, 0):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _blueprint_summary(root: Path) -> str | None:
    bp_latest = root / "cc" / "blueprints" / "latest.json"
    raw = _read_blueprint_safe(bp_latest)
    if raw is None:
        return None
    data = _parse_blueprint_safe(raw)
    if data is None:
        return None
    depth = data.get("accumulated_depth", "?")
    # str() coercion: a numeric session_id (e.g. 12345) would raise TypeError
    # on the slice; mirror session_resume.py's str() guard.
    bp_id = str(data.get("session_id") or "")[:6]
    if not bp_id:
        return f"bp=d{depth}"
    return f"bp={bp_id}/d{depth}"


def _maintenance_indicator() -> str | None:
    return "MAINT" if os.environ.get("ESPALIER_MAINTENANCE_MODE") == "1" else None


def _stop_gate_indicator() -> str | None:
    # SoT for this normalization is _hook_utils.stop_gate_mode. It is duplicated
    # as a one-liner rather than imported because statusline.py lives OUTSIDE
    # hooks/ and a new cross-directory import is a deploy-set risk: a script
    # copied without its sibling deps crashes SILENTLY in its subprocess
    # (tools/cc/CLAUDE.md). Keep the two in lockstep -- this previously used
    # `.lower()` alone, so a padded value rendered no indicator while stop_gate
    # resolved it to full.
    # NOTE the deliberate absence of a default. _hook_utils.stop_gate_mode()
    # resolves UNSET to "light" because its callers need a mode to act on; this
    # reader needs the opposite — an unset variable must render NO segment, not
    # `STOP=light`. Defaulting here made the indicator permanently visible on
    # every statusline (caught by 11 test_statusline failures). Share the
    # NORMALIZATION (strip + casefold), not the fallback.
    value = (os.environ.get("ESPALIER_STOP_GATE") or "").strip().lower()
    return f"STOP={value}" if value in ("full", "light") else None


def _freshness_summary(root: Path) -> str | None:
    """Short freshness segment, suppressed when all fresh
    or when the state cache is missing/stale."""
    cache = _read_state_cache_safe(root)
    if cache is None or _is_state_cache_stale(cache, repo_root=root):
        return None
    counts = cache.get("counts", {})
    critical = counts.get("critical", 0)
    stale = counts.get("stale", 0)
    fresh = counts.get("fresh", 0)
    if critical:
        return f"fresh:{fresh} crit:{critical}"
    if stale:
        return f"fresh:{fresh} stale:{stale}"
    return None


def main() -> int:
    # Resolve to absolute path so the statusline does not silently
    # degrade to a cwd-relative read when CLAUDE_PROJECT_DIR is unset
    # (multi-repo workspaces, IDE integrations, spawned subshells).
    # This is the shared harness idiom: $CLAUDE_PROJECT_DIR first, cwd only as
    # a fallback, always .resolve()'d — the hook scripts resolve root the same
    # way. A raw Path.cwd() here misreports when launched from a subdirectory
    # even with the env var set.
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
    parts = ["espalier"]
    # Compute each indicator independently so one failing segment
    # (e.g. a malformed freshness cache) degrades only ITSELF, not the healthy
    # MAINT/STOP/blueprint segments — and log the masked error to stderr (safe;
    # the status line is stdout) so the silent degradation is observable rather
    # than invisible. The statusline contract (never raise, exit 0) is upheld.
    indicators = (
        _maintenance_indicator,
        _stop_gate_indicator,
        lambda: _blueprint_summary(root),
        lambda: _freshness_summary(root),
    )
    for indicator in indicators:
        try:
            piece = indicator()
        except Exception as exc:  # noqa: BLE001 -- never raise on unexpected shape
            print(f"[statusline] indicator degraded: {os_error_text(exc)}", file=sys.stderr)
            continue
        if piece:
            parts.append(piece)
    print(" | ".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
