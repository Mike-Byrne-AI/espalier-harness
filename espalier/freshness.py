"""Document freshness signal — public API.

Re-exports scanner types and provides high-level helpers
(``pin_fragment``, ``unpin_fragment``, ``update_state_cache``,
``read_state_cache_safe``, ``is_state_cache_stale``) that
manage the ``.espalier/freshness.json`` manifest.

Per the scanner-canon invariant, ``Fragment``,
``FragmentState``, constants, and ``parse_fragment_markers`` live in
``espalier.scanners.freshness``. This module imports them; it does
not redefine them.
"""
from __future__ import annotations

import contextlib
import json
import os
import stat as _stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MAX_FRESHNESS_MANIFEST_BYTES = 65_536  # 64 KB cap.
STATE_CACHE_MAX_AGE_HOURS = 24
_STATE_CACHE_REASON_TRUNC = 200
# Cap the NUMBER of critical/stale entries written (not just each reason) so the
# manifest stays under MAX_FRESHNESS_MANIFEST_BYTES even with hundreds of
# simultaneously-critical fragments; the true totals live in ``counts``. R3.
_STATE_CACHE_MAX_ENTRIES = 80
_ANCESTOR_WINDOW_COMMITS = 50

# Windows CPython omits ``O_NOFOLLOW`` and ``O_NONBLOCK`` (POSIX-only);
# ``getattr(..., 0)`` degrades to a no-op OR so the constant resolves on
# every platform while preserving the cache-poisoning defenses on POSIX.
_CACHE_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_CLOEXEC", 0)
)

# POSIX advisory locking for the manifest read-modify-write window.
# Absent on Windows / flock-less filesystems, where the RMW degrades to
# best-effort unlocked -- the atomic rename in ``_write_manifest`` still
# prevents torn reads; only the lost-update race is unguarded there.
# Same precedent as ``tools/cc/hooks/_integrity.write_manifest``.
try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover -- Windows
    fcntl = None  # type: ignore[assignment]
    _HAS_FCNTL = False

_FRESHNESS_LOCK_REL = ".espalier/.freshness.write.lock"
# The derived state_cache lives in its OWN gitignored per-install file, NOT as a
# block inside the committed ``.espalier/freshness.json`` manifest -- a ``freshness
# check`` must not dirty the tracked tree. The manifest keeps only the
# committed SoT (``fragments`` + ``schema_version``).
_STATE_CACHE_REL = ".espalier/.freshness_state_cache.json"

from espalier.scanners.freshness import (
    Fragment,
    FragmentState,
    FreshnessError,
    MANIFEST_REL_PATH,
    SCHEMA_VERSION,
    STALE_THRESHOLD_COMMITS,
    CRITICAL_THRESHOLD_DAYS,
    STALE_THRESHOLD_DAYS,
    _literal_edited_by_hand,
    _manifest_fragments_at_head,
    _normalize_bound,
    _utc_now_iso,
    bound_commits_since,
    dirty_bound_paths,
    discover_fragments,
    parse_fragment_markers,
    scan_repo,
)
from espalier._atomic_io import atomic_write_text

__all__ = [
    "Fragment",
    "FragmentState",
    "FreshnessError",
    "RebindingRefusedError",
    "StaleLiteralRefusedError",
    "carried_literal",
    "STALE_THRESHOLD_COMMITS",
    "CRITICAL_THRESHOLD_DAYS",
    "STALE_THRESHOLD_DAYS",
    "is_state_cache_stale",
    "parse_fragment_markers",
    "pin_fragment",
    "read_state_cache_safe",
    "scan_repo",
    "unpin_fragment",
    "update_state_cache",
]


class RebindingRefusedError(FreshnessError):
    """``pin_fragment`` refused to silently overwrite a bound change.

    Distinct subclass so CLI bulk paths (``pin --all``) can catch
    the rebinding refusal specifically (skip + report) without
    swallowing other ``FreshnessError`` causes (missing marker,
    schema mismatch, git failure).
    """


class DirtyBoundRefusedError(FreshnessError):
    """Raised by ``pin_fragment`` when a bound path carries uncommitted changes
    and ``force`` is not set: a pin records HEAD as the point where the claim
    was verified, and HEAD is not the tree the operator looked at. ``paths``
    names them, so ``pin --all`` (which takes no ``--force``) can word its own
    remedy instead of repeating the single pin's."""

    def __init__(self, message: str, *, paths: list[str]) -> None:
        super().__init__(message)
        self.paths = list(paths)


class StaleLiteralRefusedError(FreshnessError):
    """``pin_fragment`` refused to carry a ``numeric-contract`` entry's
    ``expected_value`` onto a new pin. A pin given no literal carries the
    entry's own -- a re-pin refreshes the clock, not the number -- but only
    across a bound nothing has touched since the pin that verified it: a
    bound that moved (commits to it, or the marker rebinding it) or a literal
    that differs from the committed one beside an unchanged pin (edited by
    hand) would stamp a number nobody re-read as verified at a new SHA. The
    remedy is to restate it (CLI: ``--expected-value``); ``force`` does not
    consent to this. Distinct subclass so ``pin --all`` can refuse before
    pinning anything and name the fragment."""


#: The default for ``pin_fragment``'s ``expected_value``: carry the entry's
#: existing literal under ``carried_literal``'s rules. An explicit ``None``
#: records no literal (the way one is retired on purpose); a value replaces it.
_KEEP: object = object()


def carried_literal(repo_root: Path, frag: Fragment, existing: Any) -> object:
    """The ``expected_value`` a pin given no literal records for ``frag``.

    The entry's own, when the entry has one, the marker's policy still takes
    one and nothing has moved under it. ``None`` when there is nothing to
    carry: no entry, no literal, or a marker whose policy no longer takes one
    (the literal retires with the policy). Raises
    ``StaleLiteralRefusedError`` when carrying would re-attest an unverified
    number: the marker binds something other than what the literal was
    verified against, the literal was edited by hand beside an unchanged pin
    (a check that stands down where the manifest is not at HEAD, as the
    scan's does), or commits since the pin touched the bound. Shared by
    ``pin_fragment`` and ``pin --all``'s pre-flight, so the two cannot
    disagree about what a re-pin carries. The CLI passed ``None`` here for a
    year and the entry, rebuilt from scratch, lost its literal on every bare
    re-pin -- ff9eaff (2026-09-19) dropped ``hook-count``'s ``12`` that way.
    """
    if not isinstance(existing, dict) or "expected_value" not in existing:
        return None
    if frag.policy != "numeric-contract":
        return None
    literal = existing["expected_value"]
    prior_bound = existing.get("bound", [])
    prior_norm = (
        tuple(_normalize_bound(b) for b in prior_bound)
        if isinstance(prior_bound, list) else ()
    )
    if prior_norm != tuple(_normalize_bound(b) for b in frag.bound):
        raise StaleLiteralRefusedError(
            f"refusing to carry expected_value {literal!r} for {frag.id!r}: it was "
            f"verified against bound={list(prior_bound)} and the marker now claims "
            f"bound={list(frag.bound)}; verify the number against the new bound, "
            f"then restate it with --expected-value"
        )
    at_head = _manifest_fragments_at_head(repo_root)
    edited, head_value = _literal_edited_by_hand(existing, (at_head or {}).get(frag.id))
    if edited:
        raise StaleLiteralRefusedError(
            f"refusing to carry expected_value {literal!r} for {frag.id!r}: it was "
            f"edited by hand (HEAD carries {head_value!r}) beside an unchanged pin; "
            f"verify the number, then restate it with --expected-value"
        )
    since = existing.get("last_verified_sha") or ""
    moved = bound_commits_since(repo_root, since, frag.bound) if since else 0
    if moved:
        raise StaleLiteralRefusedError(
            f"refusing to carry expected_value {literal!r} for {frag.id!r}: "
            f"{moved} commit(s) since the pin at {since[:7]} touched its bound, so "
            f"the number may have moved; verify it, then restate it with "
            f"--expected-value"
        )
    return literal


def _resolve_head_sha(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", check=False, timeout=10,
        )
    except ValueError as exc:  # strict decode: a structured answer (DEF-821)
        # A SHA is ASCII; output this strict decode refuses is git failing to
        # answer, and it becomes this function's own error rather than a
        # UnicodeDecodeError traceback (DEF-821). Deliberately not
        # errors="replace": a replaced SHA would compare unequal downstream and
        # read as staleness, masking the corruption.
        raise FreshnessError(f"git rev-parse HEAD output was not UTF-8: {exc}") from exc
    if result.returncode != 0:
        raise FreshnessError(
            f"git rev-parse HEAD failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _load_manifest_for_write(repo_root: Path) -> dict[str, Any]:
    manifest_path = repo_root / MANIFEST_REL_PATH
    if not manifest_path.is_file():
        return {"schema_version": SCHEMA_VERSION, "fragments": {}}
    try:
        raw = manifest_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        # A present-but-non-UTF-8 or malformed manifest must raise the module's
        # typed FreshnessError (like the non-dict / schema-mismatch branches
        # below), not a bare UnicodeDecodeError/JSONDecodeError that tracebacks
        # through every freshness write caller.
        raise FreshnessError(
            f"manifest is not readable UTF-8 JSON: {exc}"
        ) from exc
    # A valid-JSON non-dict manifest must raise a clean FreshnessError, not
    # crash data.get with AttributeError.
    if not isinstance(data, dict):
        raise FreshnessError(
            f"manifest is not a JSON object (found {type(data).__name__})"
        )
    if data.get("schema_version") != SCHEMA_VERSION:
        raise FreshnessError(
            f"manifest schema_version mismatch "
            f"(found {data.get('schema_version')!r}, "
            f"this version requires {SCHEMA_VERSION})"
        )
    if not isinstance(data.get("fragments"), dict):
        data["fragments"] = {}
    # Self-healing migration: the derived state_cache used to live here but now
    # has its own gitignored per-install file. Strip any orphan block left by a
    # pre-relocation manifest so a pin/unpin never re-commits dead cache data and
    # the "manifest carries only fragments + schema_version" invariant holds.
    data.pop("state_cache", None)
    return data


def _write_manifest(repo_root: Path, manifest: dict[str, Any]) -> None:
    # Route through the shared atomic-write helper instead of reimplementing
    # the temp-file dance inline. atomic_write_text handles
    # parent mkdir, a random temp name (no fixed ``.json.tmp`` collision),
    # the MAX_PATH prefix cap, unlink-on-failure cleanup, and the target's
    # mode; a symlinked manifest is replaced by a regular file, which is what
    # the O_NOFOLLOW readers below can read.
    manifest_path = repo_root / MANIFEST_REL_PATH
    body = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    atomic_write_text(manifest_path, body)


@contextlib.contextmanager
def _freshness_write_lock(repo_root: Path):
    """Serialize the manifest load-modify-save window across processes,
    mirroring ``_integrity.write_manifest``.
    Without it, two interleaved ``pin``/``unpin``/``update_state_cache``
    calls can lose an update -- both read the same manifest and the second
    write clobbers the first. NIT-priority: the atomic rename already
    prevents torn reads; this closes only the lost-update race. Windows /
    flock-less FS degrade to a best-effort unlocked RMW."""
    if not _HAS_FCNTL:
        yield
        return
    lock_path = repo_root / _FRESHNESS_LOCK_REL
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fh = open(lock_path, "a+", encoding="utf-8")
    except OSError:
        yield
        return
    acquired = False
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        acquired = True
    except OSError:
        # flock-less mount (NFS / SMB / some FUSE + bind mounts): `import fcntl`
        # succeeding does not mean the SYSCALL works. Degrade to the same
        # best-effort unlocked RMW this module already documents for the
        # no-fcntl case rather than failing the caller's pin/unpin outright.
        pass
    try:
        yield
    finally:
        try:
            # Only unlock what was locked -- LOCK_UN on the degrade path raises
            # the same OSError, out of a `finally`, masking the real outcome.
            if acquired:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)
        finally:
            lock_fh.close()


def _find_fragment(repo_root: Path, fragment_id: str) -> Fragment:
    for frag in discover_fragments(repo_root):
        if frag.id == fragment_id:
            return frag
    raise FreshnessError(
        f"fragment id {fragment_id!r} not found in any doc under "
        f"{repo_root}; add the marker before pinning"
    )


def pin_fragment(
    fragment_id: str,
    repo_root: Path,
    sha: str | None = None,
    *,
    expected_value: object = _KEEP,
    force: bool = False,
) -> dict[str, Any]:
    """Record ``sha`` (default HEAD) as verified for ``fragment_id``.

    The fragment's CURRENT bound paths are captured alongside the
    SHA — bound-change invalidation (BC-040) requires this paired
    storage so the scanner can detect a redirect after pinning.

    ``expected_value`` left at its default carries the entry's existing
    literal under ``carried_literal``'s rules (and raises
    ``StaleLiteralRefusedError`` where carrying would re-attest a number
    nobody re-read); an explicit ``None`` records no literal; a value
    replaces it. The entry is otherwise rebuilt from scratch, which is why
    the default is a carry and not ``None``.

    When an existing manifest entry's normalized ``bound`` differs
    from the current marker's normalized ``bound`` (a rebinding),
    refuse with ``FreshnessError`` unless ``force=True``. Mirrors
    ``scan_repo``'s rebinding-attempt defense at the pin call site
    so a hurried operator cannot silently clear the critical
    finding by re-pinning. CLI exposes this as ``--force``.

    Returns the resulting manifest entry (useful for CLI display
    and tests).
    """
    with _freshness_write_lock(repo_root):
        return _pin_fragment_locked(
            fragment_id, repo_root, sha,
            expected_value=expected_value, force=force,
        )


def _pin_fragment_locked(
    fragment_id: str,
    repo_root: Path,
    sha: str | None = None,
    *,
    expected_value: object = _KEEP,
    force: bool = False,
) -> dict[str, Any]:
    """Inner pin -- called with the freshness write-lock held on POSIX."""
    frag = _find_fragment(repo_root, fragment_id)
    explicit = expected_value is not _KEEP
    if explicit and expected_value is not None and frag.policy != "numeric-contract":
        raise FreshnessError(
            f"fragment {fragment_id!r} has policy={frag.policy!r}, which takes no "
            f"expected_value: the test that derives the number is the witness. "
            f"Pin it without --expected-value, or change the marker's policy to "
            f"numeric-contract if no test can derive it."
        )
    resolved_sha = sha or _resolve_head_sha(repo_root)
    manifest = _load_manifest_for_write(repo_root)

    existing = manifest.get("fragments", {}).get(fragment_id)
    if existing is not None and not force:
        prior_bound_raw = existing.get("bound", [])
        if isinstance(prior_bound_raw, list) and prior_bound_raw:
            prior_norm = tuple(_normalize_bound(b) for b in prior_bound_raw)
            current_norm = tuple(_normalize_bound(b) for b in frag.bound)
            if prior_norm != current_norm:
                raise RebindingRefusedError(
                    f"refusing to silently rebind fragment "
                    f"{fragment_id!r}: manifest pins "
                    f"bound={list(prior_bound_raw)} but marker now "
                    f"claims bound={list(frag.bound)}. Verify the new "
                    f"bound is correct, then re-run with force=True "
                    f"(CLI: --force). If the prior bound is no longer "
                    f"correct (e.g., the claim moved), prefer "
                    f"`espalier freshness unpin {fragment_id} && "
                    f"espalier freshness pin {fragment_id}` over "
                    f"--force — unpin makes the rebind auditable in "
                    f"git history."
                    + (
                        " A numeric-contract entry loses its literal with "
                        "unpin: give the next pin --expected-value."
                        if frag.policy == "numeric-contract" else ""
                    )
                )

    if not force:
        # A pin vouches for HEAD. A bound with uncommitted changes means HEAD
        # is not what was verified: the manifest would assert a claim (and,
        # for numeric-contract, a literal) that is false at the SHA it names,
        # and ``check`` would read it fresh until the commit lands -- measured
        # 2026-09-06 with a count pinned at 47 against a HEAD holding 46.
        # Order is load-bearing: the rebind check above fires first, and
        # ``bench/run_benchmark.py``'s pin-side verifier catches only
        # ``RebindingRefusedError`` on a tree whose bound is committed.
        dirty = dirty_bound_paths(repo_root, frag.bound)
        if dirty:
            raise DirtyBoundRefusedError(
                f"refusing to pin fragment {fragment_id!r}: its bound has "
                f"uncommitted changes ({', '.join(dirty)}), so HEAD "
                f"{resolved_sha[:7]} is not the tree you verified and the "
                f"manifest would vouch for a verification that never happened. "
                f"Commit the bound first, then pin; or re-run with force=True "
                f"(CLI: --force) to record the pin at HEAD anyway.",
                paths=dirty,
            )

    if not explicit:
        expected_value = carried_literal(repo_root, frag, existing)
    entry: dict[str, Any] = {
        "bound": list(frag.bound),
        "policy": frag.policy,
        "last_verified_sha": resolved_sha,
        "last_verified_at": _utc_now_iso(),
    }
    if expected_value is not None:
        entry["expected_value"] = expected_value
    if frag.source_path:
        # Persist the marker-doc path so the freshness cache invalidation can
        # watch the claim doc itself, not only the bound source.
        # A doc whose marker text drifts (or that is deleted) must invalidate the
        # cached scan even when no bound SOURCE changed.
        entry["marker_path"] = frag.source_path
    manifest["fragments"][fragment_id] = entry
    _write_manifest(repo_root, manifest)
    return entry


def unpin_fragment(fragment_id: str, repo_root: Path) -> bool:
    """Remove the manifest entry for ``fragment_id``.

    Returns True if an entry was removed, False if the id was not
    present.
    """
    with _freshness_write_lock(repo_root):
        manifest = _load_manifest_for_write(repo_root)
        if fragment_id not in manifest.get("fragments", {}):
            return False
        del manifest["fragments"][fragment_id]
        _write_manifest(repo_root, manifest)
        return True


def update_state_cache(
    repo_root: Path,
    *,
    counts: dict[str, int],
    critical: list[dict[str, Any]],
    stale: list[dict[str, Any]],
    computed_at: str,
    computed_at_sha: str,
) -> None:
    """Persist the derived state_cache to the gitignored per-install cache
    file (``.espalier/.freshness_state_cache.json``) -- NOT the committed
    manifest, so a ``freshness check`` never dirties the tracked tree.

    Each entry's ``reason`` is truncated to ``_STATE_CACHE_REASON_TRUNC``
    chars AND each list is capped at ``_STATE_CACHE_MAX_ENTRIES`` entries so
    the cache stays within the 64 KB cap even with hundreds of critical
    fragments (else ``read_state_cache_safe`` rejects the oversize file and
    loses the cache); the true totals are preserved in ``counts``.
    Atomic-write via the shared ``atomic_write_text`` helper, held under
    ``_freshness_write_lock`` (shared with pin/unpin's manifest RMW) so a
    concurrent manifest write and a state-cache write never race on the lock.
    """
    with _freshness_write_lock(repo_root):
        def _trunc(entry: dict[str, Any]) -> dict[str, Any]:
            reason = entry.get("reason") or ""
            return {**entry, "reason": reason[:_STATE_CACHE_REASON_TRUNC]}

        cache = {
            "computed_at": computed_at,
            "computed_at_sha": computed_at_sha,
            "counts": dict(counts),
            "critical": [_trunc(e) for e in critical[:_STATE_CACHE_MAX_ENTRIES]],
            "stale": [_trunc(e) for e in stale[:_STATE_CACHE_MAX_ENTRIES]],
        }
        body = json.dumps(cache, indent=2, sort_keys=True) + "\n"
        atomic_write_text(repo_root / _STATE_CACHE_REL, body)


def read_state_cache_safe(repo_root: Path) -> dict[str, Any] | None:
    """Fd-level safe read of the per-install state_cache file
    (``.espalier/.freshness_state_cache.json``); the whole body IS the cache.

    Returns ``None`` when the file is missing (e.g. fresh clone before any
    local ``freshness check``), symlinked, oversize, not a regular file, or
    fails to parse. Mirrors the ``_read_blueprint_safe`` discipline.
    """
    path = repo_root / _STATE_CACHE_REL
    try:
        fd = os.open(str(path), _CACHE_OPEN_FLAGS)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not _stat.S_ISREG(st.st_mode):
            return None
        if st.st_size > MAX_FRESHNESS_MANIFEST_BYTES:
            return None
        raw = os.read(fd, MAX_FRESHNESS_MANIFEST_BYTES + 1)
        if len(raw) > MAX_FRESHNESS_MANIFEST_BYTES:
            return None
    except OSError:
        return None
    finally:
        os.close(fd)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    cache = data if isinstance(data, dict) else None
    if not isinstance(cache, dict):
        return None
    # Mirror the tools/cc reader — coerce a present-but-non-dict
    # 'counts' to {} so the two readers stay byte-equivalent (verbatim-mirror
    # invariant) and any future espalier-side consumer that dereferences
    # counts.get(...) degrades instead of raising AttributeError.
    if "counts" in cache and not isinstance(cache["counts"], dict):
        cache = {**cache, "counts": {}}
    return cache


def is_state_cache_stale(
    cache: dict[str, Any],
    *,
    repo_root: Path | None = None,
    max_age_hours: int = STATE_CACHE_MAX_AGE_HOURS,
) -> bool:
    """Stale when older than ``max_age_hours`` OR computed at a SHA
    that does not match HEAD (with a recent-ancestor fallback for
    shallow-clone / merge-commit PR contexts)."""
    computed_at_str = cache.get("computed_at")
    if not isinstance(computed_at_str, str):
        return True
    try:
        computed_at = datetime.fromisoformat(
            computed_at_str.replace("Z", "+00:00")
        )
    except ValueError:
        return True
    if computed_at.tzinfo is None:
        return True  # naive timestamp: treat as stale rather than crash
    now = datetime.now(timezone.utc)
    if computed_at > now + timedelta(minutes=1):
        return True  # future-dated; clock-skew defense
    if (now - computed_at) > timedelta(hours=max_age_hours):
        return True
    if repo_root is None:
        return True
    cache_sha = cache.get("computed_at_sha")
    if not cache_sha:
        return True
    head = _git_head_sha_quiet(repo_root)
    if not head:
        return True  # git unavailable -> treat as stale
    if head == cache_sha:
        return False
    if _git_is_ancestor_within_n(
        cache_sha, "HEAD", n=_ANCESTOR_WINDOW_COMMITS, cwd=repo_root,
    ):
        # HEAD advanced but cache_sha is a recent ancestor — the cached scan is
        # still trusted UNLESS a commit since cache_sha touched a pinned
        # fragment's bound source: a bound-change must read stale, else
        # consumers (audit-accuracy, statusline, session_start) serve the
        # pre-change critical/stale verdicts.
        if _pinned_bound_changed_since(repo_root, cache_sha):
            return True
        return False
    return True


def _git_head_sha_quiet(cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):  # strict decode: a structured answer (DEF-821)
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    # accept 40-char SHA-1 and 64-char SHA-256 HEADs; hex-validate either way
    return (
        sha
        if len(sha) in (40, 64) and all(c in "0123456789abcdef" for c in sha)
        else None
    )


def _git_is_ancestor_within_n(
    candidate_sha: str, ref: str, *, n: int, cwd: Path,
) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-list", f"-n{n}", ref],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):  # strict decode: a structured answer (DEF-821)
        return False
    if result.returncode != 0:
        return False
    return candidate_sha in result.stdout.split()


def _read_fragments_safe(repo_root: Path) -> dict[str, Any]:
    """Fd-safe read of the manifest's ``fragments`` block (mirrors
    ``read_state_cache_safe``'s symlink / size / regular-file discipline)."""
    path = repo_root / MANIFEST_REL_PATH
    try:
        fd = os.open(str(path), _CACHE_OPEN_FLAGS)
    except OSError:
        return {}
    try:
        st = os.fstat(fd)
        if not _stat.S_ISREG(st.st_mode):
            return {}
        if st.st_size > MAX_FRESHNESS_MANIFEST_BYTES:
            return {}
        raw = os.read(fd, MAX_FRESHNESS_MANIFEST_BYTES + 1)
        if len(raw) > MAX_FRESHNESS_MANIFEST_BYTES:
            return {}
    except OSError:
        return {}
    finally:
        os.close(fd)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    frags = data.get("fragments") if isinstance(data, dict) else None
    return frags if isinstance(frags, dict) else {}


def _pinned_bound_paths(repo_root: Path) -> list[str]:
    """Repo-relative paths every pinned fragment's bound is derived from."""
    paths: set[str] = set()
    for frag in _read_fragments_safe(repo_root).values():
        if not isinstance(frag, dict):
            continue
        # Guard the bound is a list — a hand-edited `"bound": "x.py"`
        # (string) would otherwise char-iterate into single-character pathspecs.
        bound = frag.get("bound")
        if not isinstance(bound, list):
            continue
        for entry in bound:
            if isinstance(entry, str) and entry:
                # A bound may be `path::symbol`. git treats `path::symbol` as a
                # pathspec matching NO file, so the freshness cache-invalidation
                # guard below would silently report "not stale" for every commit
                # touching a ::symbol-bound source (nearly all of them). Strip to
                # the bare path — mirrors scanners/freshness.py::_bound_to_paths.
                path = entry.split("::", 1)[0]
                if path and not path.startswith("-"):
                    paths.add(path)
    return sorted(paths)


def _pinned_marker_paths(repo_root: Path) -> list[str]:
    """Repo-relative marker-doc paths of every pinned fragment (the doc the
    fragment's marker lives in, persisted as ``marker_path`` at pin time).

    The staleness guard watches these alongside the bound sources: a claim doc
    can drift (its marker text edited, or the doc deleted) without any bound
    SOURCE changing, and a bound-only watch would silently report the cached
    scan 'not stale'. Fragments pinned before ``marker_path`` was added carry
    none and are simply skipped (re-pinning captures it)."""
    paths: set[str] = set()
    for frag in _read_fragments_safe(repo_root).values():
        if not isinstance(frag, dict):
            continue
        marker = frag.get("marker_path")
        if isinstance(marker, str) and marker and not marker.startswith("-"):
            paths.add(marker)
    return sorted(paths)


def _pinned_bound_changed_since(repo_root: Path, cache_sha: str) -> bool:
    """True iff a commit since ``cache_sha`` touched any pinned fragment's
    bound source OR marker doc — the cached scan no longer reflects HEAD."""
    paths = sorted(
        set(_pinned_bound_paths(repo_root)) | set(_pinned_marker_paths(repo_root))
    )
    if not paths:
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--quiet",
             cache_sha, "HEAD", "--", *paths],
            capture_output=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True  # cannot compare -> conservatively stale
    return result.returncode != 0
