"""Integrity + audit helpers (Pack 5 Task 5-B).

Visibility layer only — NOT a security boundary. Runs in the same trust
domain as the agent and can be disabled by anyone who reads the source.
Purpose: surface bypass attempts within seconds rather than hours.

Stdlib-only, zero espalier imports. Hook scripts import these helpers and
drive them; the CLI also consumes them via the `espalier integrity`
subcommand.
"""
from __future__ import annotations

import codecs
import functools
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

_T = TypeVar("_T")

try:
    import fcntl  # POSIX advisory locking
    _HAS_FCNTL = True
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]
    _HAS_FCNTL = False

# Sibling-import _hook_utils.warn so all hook stderr output flows through
# the same prefixed helper. _integrity.py is loaded both as a hook script
# subprocess (sys.path includes its own dir) AND via importlib.util by
# espalier/cli.py (where __file__ is set but sibling imports need the
# explicit sys.path push). Mirrors stop_gate.py's pattern.
sys.path.insert(0, str(Path(__file__).parent))
# tools/cc level for the dual-scope JSON chokepoint. Same dual-load context as
# the _hook_utils import above (subprocess + importlib from espalier/cli.py);
# mirrors _protected_zones.py's parent.parent insert.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _hook_utils  # noqa: E402
from _json_safe import decode_bom, load_json_dict_safe, os_error_text  # noqa: E402

# Files covered by the committed integrity manifest. Kept in parity with
# espalier.surface_contract.get_protected_integrity_paths() but hard-coded
# here to preserve the tools/cc/ zero-espalier-import rule.
# sister-site: ok forced copy across the no-import boundary; pinned to surface_contract.get_protected_integrity_paths(), not cli.INIT_HOOK_SCRIPTS
MANIFEST_FILES: tuple[str, ...] = (
    ".github/workflows/harness-guard.yml",
    # _integrity.py hard-imports tools/cc/_json_safe.py (the JSON decode
    # chokepoint it uses to read settings/manifests). Tampering it could
    # subvert the integrity check itself, so it must be in the manifest.
    "tools/cc/_json_safe.py",
    "tools/cc/ci_guard.py",
    "tools/cc/hooks/_bash_patterns.py",
    "tools/cc/hooks/_born_weak.py",
    "tools/cc/hooks/_denial_reasons.py",
    "tools/cc/hooks/_explain_path.py",
    "tools/cc/hooks/_hook_contract.py",
    "tools/cc/hooks/_hook_utils.py",
    "tools/cc/hooks/_integrity.py",
    "tools/cc/hooks/_maintenance_mode.py",
    "tools/cc/hooks/_protected_zones.py",
    "tools/cc/hooks/_recall.py",
    "tools/cc/hooks/_reinject.py",
    "tools/cc/hooks/_self_host_fingerprint.py",
    "tools/cc/hooks/_speedbump.py",
    "tools/cc/hooks/config_guard.py",
    "tools/cc/hooks/context_reinject_failure.py",
    "tools/cc/hooks/plan_guard.py",
    "tools/cc/hooks/post_compact.py",
    "tools/cc/hooks/post_write_check.py",
    "tools/cc/hooks/reflect_trigger.py",
    "tools/cc/hooks/session_start.py",
    "tools/cc/hooks/stop_gate.py",
    "tools/cc/hooks/subagent_start.py",
    "tools/cc/hooks/subagent_stop.py",
    "tools/cc/hooks/task_router.py",
    "tools/cc/hooks/write_guard.py",
)

MANIFEST_PATH = Path(".espalier") / "integrity.json"

# Manifest schema version. Bump when adding or changing
# fields that older verifiers cannot ignore safely. A verifier whose
# ``MANIFEST_SCHEMA_VERSION`` is N must refuse manifests with
# ``schema_version > N`` to avoid the forward-compat trap (e.g. a
# future blake3 manifest read by a sha256-only verifier would report
# every file as mismatched). Callers may upgrade espalier or hand-edit
# the manifest if they understand the change.
MANIFEST_SCHEMA_VERSION = 1
# The hash is taken over the CANONICAL TEXT FORM of each managed file -- a
# leading UTF-8 BOM stripped, CRLF and bare CR folded to LF -- under a name that
# says so, because the bytes on disk are not the harness's to pin: git's
# core.autocrlf=true (the Git for Windows installer's system-scope default)
# rewrites LF to CRLF on checkout, and a manifest written over raw bytes then
# reported every managed file changed (28 of 28, driven 2026-09-09) while
# `refresh` only moved the wrongness to the next LF checkout (DEF-725; the
# operator chose normalize over a .gitattributes pin, which the host owns). An
# ending or a BOM cannot change what a hook does: CPython decodes source with
# universal newlines, so a CR or CRLF file runs as its LF twin, and hooks are
# launched by interpreter path, not by shebang, so a leading BOM is inert too --
# folding them loses no signal. A UTF-16/32 re-encoding is not decoded (the
# fold only sees its 0x0D bytes), so it stays the drift it is: such a hook
# cannot run at all. The raw-bytes name is still verified, so a manifest
# written before this change keeps verifying until its next refresh; any other
# name is refused with one sentinel line (the forward-compat trap above).
MANIFEST_HASH_ALGORITHM = "sha256-lf"
_LEGACY_HASH_ALGORITHM = "sha256"   # raw bytes, as every manifest before DEF-725


def canonical_text_bytes(raw: bytes) -> bytes:
    """The text form the manifest hashes: a leading UTF-8 BOM stripped, CRLF
    and bare CR folded to LF. The one owner of the rule; ``espalier.cli`` reads
    it through the integrity bridge for the ``install-ci`` workflow compare and
    ``espalier.selfcheck`` for the deployed-versus-package hook compare."""
    if raw.startswith(codecs.BOM_UTF8):
        raw = raw[len(codecs.BOM_UTF8):]
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _raw_bytes(raw: bytes) -> bytes:
    return raw


#: What each algorithm name hashes. The supported set is DERIVED from this table
#: so a name cannot be accepted by the verifier and hashed by the wrong rule (the
#: failure-mode review's story: a third name added to a hand-kept tuple beside an
#: if/else that knew two, hashing raw and reproducing DEF-725 with every test
#: green). Widening the canon needs a NEW name with the old one kept here, or
#: every manifest in the field silently mismatches; ``tests/test_integrity.py``
#: pins the name to the canon's digest so that red names the obligation.
_CANON_BY_ALGORITHM: dict[str, Callable[[bytes], bytes]] = {
    MANIFEST_HASH_ALGORITHM: canonical_text_bytes,
    _LEGACY_HASH_ALGORITHM: _raw_bytes,
}
SUPPORTED_HASH_ALGORITHMS: tuple[str, ...] = tuple(_CANON_BY_ALGORITHM)

#: The verifier's protocol sentinels: a manifest this module cannot read at all,
#: as opposed to a file that changed. Every remedy printer (the SessionStart
#: banner, ``espalier integrity verify``) sends the operator to redeploy the
#: hooks (``espalier upgrade --execute``), never to ``refresh``: the manifest is
#: written by the engine's own copy of this module while the session reads it
#: with the DEPLOYED copy, and the two upgrade by different commands, so a
#: refresh under a name the deployed hooks do not know would loop (driven by the
#: DEF-725 failure-mode review). ``_writer_algorithm`` keeps the writer from
#: opening that gap in the first place.
PROTOCOL_MISMATCH_PREFIXES: tuple[str, ...] = (
    "<algorithm_unsupported:", "<schema_version_unsupported:",
)


def is_protocol_mismatch(mismatched: list[str]) -> bool:
    """True when a verdict is one protocol sentinel, not a drifted file."""
    return len(mismatched) == 1 and mismatched[0].startswith(PROTOCOL_MISMATCH_PREFIXES)


_DEPLOYED_ALGORITHM_RE = re.compile(r'^MANIFEST_HASH_ALGORITHM\s*=\s*"([^"]+)"', re.M)


def _writer_algorithm(repo_root: Path) -> str:
    """The name to write a manifest under: this module's own canon, unless the
    DEPLOYED copy of this module -- ``tools/cc/hooks/_integrity.py`` under the
    repo, the one the session's hooks verify with -- is older and knows only
    the raw-bytes name.

    The engine writes the manifest with its own (vendored) copy of this module
    and the hooks read it with the deployed one, and the two upgrade by
    different commands: ``pip install -U`` moves the writer, only ``init`` and
    ``upgrade --execute`` redeploy the readers. A manifest under a name the
    deployed reader refuses would strand the session on one sentinel line whose
    remedy, ``refresh``, rewrites the same name (driven by the DEF-725
    failure-mode review). So the writer follows the reader and says why. Read
    statically, never executed: the deployed copy is a sibling module whose
    import would rebind ``_hook_utils`` under the engine. This module's own file
    (the self-host tree), no deployed copy (a fresh tree), an unreadable one,
    or one naming something this module does not know (a NEWER reader, which
    keeps the older names by the rule above) all answer this module's own name.
    """
    deployed = repo_root / "tools" / "cc" / "hooks" / "_integrity.py"
    try:
        if not deployed.is_file() or deployed.resolve() == Path(__file__).resolve():
            return MANIFEST_HASH_ALGORITHM
        match = _DEPLOYED_ALGORITHM_RE.search(
            deployed.read_text(encoding="utf-8", errors="replace"),
        )
    except (OSError, ValueError):
        return MANIFEST_HASH_ALGORITHM
    if match is None:
        return MANIFEST_HASH_ALGORITHM
    reader = match.group(1)
    if reader == MANIFEST_HASH_ALGORITHM or reader not in _CANON_BY_ALGORITHM:
        return MANIFEST_HASH_ALGORITHM
    _hook_utils.warn(
        f"integrity: the deployed hooks under tools/cc/hooks/ verify manifests under "
        f"{reader!r} (raw bytes: a CRLF checkout reads as drift there), so the manifest "
        f"was written under that name. Run `espalier upgrade --execute` to redeploy "
        f"them, then `espalier integrity refresh .` once to adopt {MANIFEST_HASH_ALGORITHM!r}."
    )
    return reader

# Files scanned for kill-switch kv pairs. Per-machine or gitignored, so
# content-based checks sit outside the manifest.
_SETTINGS_CANDIDATES: tuple[Path, ...] = (
    Path(".claude") / "settings.json",
    Path(".claude") / "settings.local.json",
)


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path, algorithm: str = MANIFEST_HASH_ALGORITHM) -> str:
    """SHA-256 of ``path`` under ``algorithm`` -- the canonical text form for
    the manifest's own name, the raw bytes for the legacy name
    (``_CANON_BY_ALGORITHM``); any other name is a caller bug and raises
    ``ValueError``, never a quiet raw hash. The ``open("rb")`` is deliberate:
    an unreadable file must raise here (see ``compute_current_hashes``)."""
    try:
        canon = _CANON_BY_ALGORITHM[algorithm]
    except KeyError:
        raise ValueError(
            f"unsupported manifest hash algorithm {algorithm!r}; "
            f"supported: {SUPPORTED_HASH_ALGORITHMS}"
        ) from None
    with path.open("rb") as fh:
        raw = fh.read()
    return hashlib.sha256(canon(raw)).hexdigest()


def compute_current_hashes(
    repo_root: Path, algorithm: str = MANIFEST_HASH_ALGORITHM,
) -> dict[str, str]:
    """Return {rel_path: sha256} for every file in the manifest inventory
    that exists on disk, hashed under ``algorithm`` (the manifest's own canon
    by default; the legacy raw-bytes name when verifying a manifest that
    declares it). Missing files are omitted (verify_integrity will surface
    the mismatch against the committed manifest).

    An UNREADABLE managed file is omitted too, and that is the loud answer, not
    the quiet one: omission renders downstream as ``"<rel> (missing on disk)"``
    drift, so a file we cannot hash reports as drift rather than as agreement.
    Neither probe here may raise. ``Path.is_file()`` re-raises EACCES on
    CPython 3.10-3.13 (the version-gated class), and ``_sha256_file``'s
    ``open()`` raises on EVERY version including 3.14 -- and because
    ``doctor.py``'s caller catches ``(OSError, AttributeError)`` and passes, a
    raise here does not surface as an error. It leaves ``integrity_drift``
    EMPTY and doctor reports CLEAN on a repo whose tamper-detection could not
    read its own managed files -- the exact state the MANIFEST_ABSENT /
    MANIFEST_UNREADABLE split above exists to prevent, re-entered one layer up.
    Measured before this guard: `chmod 000` on one managed file made
    ``verify_integrity`` raise and ``espalier doctor`` print no integrity line
    at all, byte-identical to a healthy tree.
    """
    out: dict[str, str] = {}
    for rel in MANIFEST_FILES:
        p = repo_root / rel
        if os.path.isfile(p):
            try:
                out[rel] = _sha256_file(p, algorithm)
            except OSError:
                continue  # present but unreadable -> reported as drift, not agreement
    return out


# Absent and unreadable are DIFFERENT states and must not share a sentinel.
# A fresh checkout legitimately has no manifest, and every consumer forgives
# that. A manifest that is PRESENT but cannot be trusted -- unparseable, the
# wrong top-level type, unreadable, or symlinked -- means tamper-detection is
# BLIND, which must be loud. Conflating the two made `espalier doctor` report
# status=warn / exit 0 / failures=[] on a repo whose integrity checking was
# not running at all.
MANIFEST_ABSENT = "<manifest missing>"
MANIFEST_UNREADABLE = "<manifest unreadable>"


def _manifest_is_symlinked(repo_root: Path) -> bool:
    """The manifest path or its ``.espalier/`` parent is a symlink.

    Following either would ingest attacker JSON into the drift verdict
    (orientation-poison). Mirrors the is_symlink refusal already used for the
    audit-dir override (_validate_*). Single owner of the rule: the loader
    refuses on it and the absent-vs-unreadable split consults it, so the two
    cannot drift into disagreeing about what "present" means.

    ``os.path.islink``, NOT ``Path.is_symlink()``. The bound method shares the
    ``_ignore_error`` table with ``Path.exists()`` -- ENOENT/ENOTDIR/EBADF/ELOOP
    are swallowed and EACCES is NOT -- so on CPython 3.10-3.13 it RAISES on a
    ``.espalier/`` the process cannot traverse, while 3.14 swallows it. This
    function is the FIRST thing ``_manifest_absent`` calls, so that raise
    escaped the very discrimination the caller's docstring promises. Measured:
    with the 3.10-3.13 probe bodies substituted, ``_manifest_absent`` raised
    PermissionError instead of returning False. ``os.path.islink`` catches
    every OSError on every supported version, and False here is the right
    answer -- "cannot tell whether it is a symlink" routes on to the ``os.stat``
    below, which reports present-or-unknowable rather than absent. No refusal is
    weakened: a symlink we cannot even traverse to cannot be followed either.
    """
    path = repo_root / MANIFEST_PATH
    return os.path.islink(path) or os.path.islink(path.parent)


def _manifest_absent(repo_root: Path) -> bool:
    """True only when there is genuinely NO manifest to read.

    ``_load_manifest_unlocked`` returns None for several distinct reasons: the
    file is absent, it (or its parent) is a symlink, it will not parse into a
    dict, or the read raised OSError. Only the FIRST is benign. A symlink in
    particular is a present-and-refused manifest -- reporting it as "missing"
    told the operator a poisoning attempt was a fresh checkout.

    ``Path.exists()`` is NOT the right test here and was the first thing tried.
    It swallows every OSError, not just ENOENT, so a ``.espalier/`` the process
    cannot traverse (EACCES) returns False and reads as "never existed" -- the
    same "cannot tell" collapsed into "nothing to tell" that this whole seam
    exists to separate, one level further down. ``os.stat`` lets the two be
    told apart: only ENOENT / ENOTDIR mean genuinely absent, and anything else
    means present-or-unknowable, which routes to UNREADABLE.
    """
    if _manifest_is_symlinked(repo_root):
        return False
    try:
        os.stat(repo_root / MANIFEST_PATH)
    except (FileNotFoundError, NotADirectoryError):
        return True
    except OSError:
        return False  # cannot determine -> never claim absence
    return False


def _load_manifest_unlocked(repo_root: Path) -> dict[str, object] | None:
    """Manifest read with no lock acquisition. Callers that already hold
    the read or write lock use this to avoid nested-lock waste.

    Returns None for several distinct reasons; callers that need to tell a
    benign absence from an unusable manifest must ask ``_manifest_absent``
    rather than treating None as "nothing to check".
    """
    path = repo_root / MANIFEST_PATH
    # os.path.exists, not Path.exists() -- same EACCES re-raise on 3.10-3.13 as
    # _manifest_is_symlinked above, on the same untraversable parent. False here
    # is correct: "cannot tell" yields None, and the caller asks
    # _manifest_absent to split absent from unreadable.
    if not os.path.exists(path) or _manifest_is_symlinked(repo_root):
        return None
    try:
        # A non-dict manifest must read as None (drift = unverifiable), not be
        # returned as a list to callers that do manifest["files"].
        # Bytes, not text: the helper decodes tolerantly; a strict read here
        # raised UnicodeDecodeError past the OSError handler (DEF-829).
        return load_json_dict_safe(path.read_bytes(), default=None)
    except OSError:
        return None


def _under_shared_lock(repo_root: Path, fn: Callable[[Path], _T]) -> _T:
    """Run ``fn(repo_root)`` holding fcntl.LOCK_SH on the manifest write-lock.

    One owner keeps the read-lock discipline (Windows fcntl absence,
    missing-.espalier fallthrough, LOCK_UN-then-close) in a single place.
    ``fn`` returns whatever the caller needs (dict|None or (bool, list)); the
    lock wrapper is return-type agnostic.
    """
    manifest_path = repo_root / MANIFEST_PATH
    if not _HAS_FCNTL:
        return fn(repo_root)
    lock_path = manifest_path.parent / ".manifest.write.lock"
    if not os.path.exists(lock_path.parent):
        # No .espalier/ dir → nothing to lock against; just attempt the read.
        return fn(repo_root)
    try:
        lock_fh = open(lock_path, "a+", encoding="utf-8")
    except OSError as exc:
        # The directory is there but we cannot open a lock inside it --
        # untraversable (EACCES), read-only, full, or occupied by a directory.
        # Degrade to the UNLOCKED read, as the no-.espalier branch above does
        # and for the same reason: the caller's job is to return a VERDICT.
        # Raising here turned an unreadable manifest into an uncaught
        # PermissionError out of `verify_integrity` and `load_manifest` -- a
        # traceback instead of the MANIFEST_UNREADABLE this seam exists to
        # report, on every interpreter including 3.14. Sister site with the
        # same degradation: `espalier/fan_out_findings.py`'s corpus lock.
        #
        # AND IT MUST WARN, because the degradation is NOT always self-
        # announcing. On an untraversable `.espalier/` the read fails anyway and
        # routes to UNREADABLE, so the operator hears about it. On a READ-ONLY
        # `.espalier/` (0o555) the read SUCCEEDS: measured, `verify_integrity`
        # returned a clean `(True, [])` computed with no lock held and, before
        # this line, no signal of any kind. That is the BC-036 race silently
        # retired for the life of the condition. stderr is the right channel --
        # the hook protocol's XOR rule constrains STDOUT only
        # (docs/external/cc-hook-protocol.md), and this module already warns on
        # four other exit-0 paths.
        _hook_utils.warn_exc(
            "integrity: manifest lock unavailable; reading UNLOCKED "
            "(a concurrent refresh can make this verdict stale)", exc
        )
        return fn(repo_root)
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_SH)
        return fn(repo_root)
    finally:
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
        finally:
            lock_fh.close()


def load_manifest(repo_root: Path) -> dict[str, object] | None:
    """Read the integrity manifest under a shared lock (BC-036).

    ``write_manifest`` holds ``fcntl.LOCK_EX`` on
    ``.espalier/.manifest.write.lock`` for the full read-modify-write
    window. Without a corresponding ``LOCK_SH`` on readers, a reader
    landing between ``compute_current_hashes`` and the atomic rename
    sees the OLD manifest paired with the NEW filesystem state -- every
    refreshed hash reports as a spurious mismatch. The shared lock
    serializes readers with writers without blocking other readers.

    Windows: ``fcntl`` is absent; readers proceed without the lock. The
    same asymmetry exists in ``write_manifest`` and is accepted: the
    integrity layer is a visibility surface, not a hard boundary.
    """
    return _under_shared_lock(repo_root, _load_manifest_unlocked)


def write_manifest(repo_root: Path) -> Path:
    """Regenerate .espalier/integrity.json from current file hashes.

    Atomic write: the manifest is read by every hook subprocess
    on every tool call to verify file hashes. A direct ``write_text``
    truncates first then writes, opening a window where concurrent
    hook readers see an empty/torn JSON and report bogus "<manifest
    missing>" alarms. Atomic replace closes that window.

    flock around the read-modify-write window. Without it,
    two concurrent ``espalier integrity refresh`` invocations both
    call ``compute_current_hashes`` against a moving filesystem;
    last-writer-wins could commit a manifest that reflects neither
    pre-state cleanly. fcntl.flock serializes the operation across
    processes on POSIX. Windows falls through without the lock; the
    same asymmetry exists in ``cognitive_blueprint._acquire_write_lock``.
    The lock file lives at ``.espalier/.manifest.write.lock``;
    POSIX advisory locks scope to the file descriptor so the file
    can be a sibling sentinel rather than the manifest itself.
    """
    manifest_path = repo_root / MANIFEST_PATH
    # The READER refuses a symlinked manifest or .espalier/ parent as
    # orientation-poison; the WRITER must refuse the same shape or the two
    # disagree about what "the manifest" is. Without this, a symlinked
    # .espalier/ produced a loop the operator could not escape: verification
    # reports the manifest unreadable, the remedy says "rebuild it", the
    # rebuild writes THROUGH the symlink to wherever it points, and the next
    # verification reports unreadable again -- while the manifest silently
    # lands outside the repo. Refusing here makes _manifest_is_symlinked the
    # single owner for all three participants, not just the two it named.
    if _manifest_is_symlinked(repo_root):
        # os.path.islink for the same reason _manifest_is_symlinked uses it --
        # this only picks WHICH path to name in the message, and must not raise
        # on the version range while doing it.
        target = manifest_path if os.path.islink(manifest_path) else manifest_path.parent
        raise OSError(
            f"refusing to write the integrity manifest through a symlink: "
            f"{target} is a symlink. Replace it with a real path -- following "
            f"it would write the manifest outside the repo and leave "
            f"verification permanently unreadable."
        )
    lock_path = manifest_path.parent / ".manifest.write.lock"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if _HAS_FCNTL:
        lock_fh = open(lock_path, "a+", encoding="utf-8")
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX)
            return _write_manifest_locked(repo_root, manifest_path)
        finally:
            try:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)
            finally:
                lock_fh.close()
    return _write_manifest_locked(repo_root, manifest_path)


def _write_manifest_locked(repo_root: Path, manifest_path: Path) -> Path:
    """Inner write — called with the flock held on POSIX."""
    algorithm = _writer_algorithm(repo_root)
    data = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": _iso(),
        "algorithm": algorithm,
        "files": compute_current_hashes(repo_root, algorithm),
    }
    _hook_utils.atomic_write_text(
        manifest_path,
        json.dumps(data, indent=2, sort_keys=True) + "\n",
    )
    return manifest_path


def verify_integrity(repo_root: Path) -> tuple[bool, list[str]]:
    """Return (ok, mismatched_paths). mismatched_paths empty means ok=True.

    Only checks files in the committed manifest — per-machine files
    (e.g., .claude/settings.json) are covered by scan_for_kill_switches.

    Refuses fast when the manifest's ``schema_version`` is
    newer than this verifier's ``MANIFEST_SCHEMA_VERSION`` or its
    ``algorithm`` is not in ``SUPPORTED_HASH_ALGORITHMS`` (the canon name,
    and the legacy raw-bytes name every manifest before DEF-725 carried, which
    keeps verifying raw-against-raw until its next refresh). Otherwise a
    future blake3 manifest read by a sha256-only verifier would
    silently compare sha256(disk) against blake3(stored) and report
    every file as mismatched; instead the failure mode is a single
    sentinel that names the protocol problem (``is_protocol_mismatch``).

    BC-036: holds ``fcntl.LOCK_SH`` for the full
    load+compute+compare window so a concurrent ``write_manifest`` (which
    holds ``LOCK_EX``) cannot regenerate the manifest mid-verify. Without
    this, the verifier could read the OLD manifest, then iterate the
    filesystem after a writer's atomic rename landed -- every refreshed
    hash would report as a spurious mismatch.
    """
    return _verify_under_read_lock(repo_root)


def _verify_under_read_lock(repo_root: Path) -> tuple[bool, list[str]]:
    return _under_shared_lock(repo_root, _verify_unlocked)


def _verify_unlocked(repo_root: Path) -> tuple[bool, list[str]]:
    manifest = _load_manifest_unlocked(repo_root)
    if manifest is None:
        if _manifest_absent(repo_root):
            return False, [MANIFEST_ABSENT]
        # Present but unusable. Downstream consumers exempt only MANIFEST_ABSENT,
        # so this reports as real drift -- which is what "the manifest exists and
        # I cannot verify anything against it" deserves.
        return False, [MANIFEST_UNREADABLE]
    schema_v = manifest.get("schema_version", 1)
    if not isinstance(schema_v, int) or schema_v > MANIFEST_SCHEMA_VERSION:
        return False, [
            f"<schema_version_unsupported: manifest={schema_v!r} "
            f"verifier={MANIFEST_SCHEMA_VERSION}>"
        ]
    # A manifest with no algorithm field predates the canon: raw bytes.
    algorithm = manifest.get("algorithm", _LEGACY_HASH_ALGORITHM)
    if algorithm not in SUPPORTED_HASH_ALGORITHMS:
        return False, [
            f"<algorithm_unsupported: manifest={algorithm!r} "
            f"verifier={MANIFEST_HASH_ALGORITHM!r}>"
        ]
    files_obj = manifest.get("files", {})
    # load_json_dict_safe guarantees the TOP level is a dict, but a non-dict
    # `files` (corrupt/poisoned manifest) would crash sorted(recorded.items()).
    # Treat it as a verification FAILURE with an observable marker — matching
    # the schema_version / algorithm guards above — NOT a silent recorded={}
    # that would falsely report integrity OK.
    if not isinstance(files_obj, dict):
        return False, [f"<files_not_object: {type(files_obj).__name__}>"]
    recorded: dict[str, str] = files_obj
    mismatched: list[str] = []
    # Hash the way the MANIFEST was hashed, so a legacy raw-bytes manifest keeps
    # verifying (raw against raw) until its next refresh re-pins it.
    current = compute_current_hashes(repo_root, algorithm)
    for rel, expected in sorted(recorded.items()):
        actual = current.get(rel)
        if actual is None:
            mismatched.append(f"{rel} (missing on disk)")
        elif actual != expected:
            mismatched.append(rel)
    return (not mismatched), mismatched


# ── Kill-switch scanning ────────────────────────────────────────────────────


def _load_settings_json(path: Path) -> dict | None:
    try:
        # decode_bom (UTF-8/16/32 BOM-tolerant) — this
        # feeds the RUNTIME kill-switch DENY (write_guard PreToolUse +
        # session_start + config_guard). A BOM'd disableAllHooks/bypassPermissions
        # (incl. PowerShell's UTF-16 Out-File default) must not evade the LIVE gate.
        data = json.loads(decode_bom(path.read_bytes()))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


_NOOP_COMMANDS = frozenset({
    "",
    ":",
    "true",
    "/bin/true",
    "/usr/bin/true",
})

_EXIT_NOOP_RE = re.compile(r"^\s*exit\s+\d+\s*$")


def _is_noop_command(command: object) -> bool:
    """True if `command` is a literal no-op shell command.

    Conservative: only matches commands that are unambiguously no-ops in
    isolation. Any pipe, subshell, or substitution exits the no-op family
    immediately — it might be doing real work we can't see from here.
    """
    if not isinstance(command, str):
        return False
    stripped = command.strip()
    if stripped in _NOOP_COMMANDS:
        return True
    if _EXIT_NOOP_RE.match(stripped):
        return True
    return False


# Hook events Espalier wires (see cli._build_settings_json — can't import here,
# this file is stdlib-only / zero-espalier-import). An empty top-level list is a kill-switch
# ONLY for one of these events (it neuters a deployed Espalier hook); an empty
# list for an event Espalier does NOT govern (e.g. an adopter's own
# "PreCompact": []) is identical to omitting the key — not a kill-switch.
_ESPALIER_GOVERNED_EVENTS = frozenset({
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "ConfigChange", "Stop", "SubagentStop", "PostCompact", "SubagentStart",
    "PostToolUseFailure",
})


def _find_kill_switches(rel_path: str, data: dict) -> list[str]:
    findings: list[str] = []
    if data.get("disableAllHooks") is True:
        findings.append(f"{rel_path}: disableAllHooks: true")
    permissions = data.get("permissions")
    if isinstance(permissions, dict):
        default_mode = permissions.get("defaultMode")
        if isinstance(default_mode, str) and default_mode == "bypassPermissions":
            findings.append(f'{rel_path}: permissions.defaultMode: "bypassPermissions"')
    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        for event, entries in hooks.items():
            # 3.0 — Empty top-level list: no matchers at all for this event. Only
            # a kill-switch when Espalier wires the event (an empty list there
            # neuters a deployed hook); an empty list for a non-governed event is
            # the adopter's own config, identical to omitting the key.
            if isinstance(entries, list) and not entries:
                if event in _ESPALIER_GOVERNED_EVENTS:
                    findings.append(f"{rel_path}: hooks.{event} is an empty list")
                continue
            if not (isinstance(entries, list) and entries):
                continue
            # 3-A — Inner-empty hooks: every matcher entry has an empty
            # inner `hooks` list. Looks valid, runs nothing.
            if all(
                isinstance(entry, dict)
                and isinstance(entry.get("hooks"), list)
                and not entry["hooks"]
                for entry in entries
            ):
                findings.append(
                    f"{rel_path}: hooks.{event} entries all have empty "
                    "inner hooks list"
                )
                continue
            # 3-B — No-op command neutering: every command entry across
            # all matchers is a literal no-op (`true`, `:`, `exit 0`, etc.).
            all_commands: list[object] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    all_commands = []
                    break
                inner = entry.get("hooks")
                if not isinstance(inner, list) or not inner:
                    # Inner-empty was handled above; mixed shapes here mean
                    # at least one matcher does something — bail on 3-B.
                    all_commands = []
                    break
                for cmd_entry in inner:
                    if isinstance(cmd_entry, dict):
                        all_commands.append(cmd_entry.get("command"))
                    else:
                        all_commands = []
                        break
                else:
                    continue
                break
            if all_commands and all(_is_noop_command(c) for c in all_commands):
                findings.append(
                    f"{rel_path}: hooks.{event} commands are all no-ops"
                )
    return findings


def scan_for_kill_switches(
    repo_root: Path, *, include_unreadable: bool = False
) -> list[str]:
    """Return ["{path}: {reason}", ...] for each kill-switch finding.

    ``include_unreadable`` adds a finding for a settings file that EXISTS but
    cannot be parsed -- a state where the scan cannot answer its own question.
    It defaults False so the two BLOCKING consumers (``write_guard``, which
    denies every tool call on any finding, and ``config_guard``) keep their
    current behaviour: denying on an unparseable settings.json would block the
    edit that repairs it. Reporters and gates that cannot lock anyone out --
    ``session_start``, ``doctor``, ``ci_guard`` -- pass True.
    """
    findings: list[str] = []
    for rel in _SETTINGS_CANDIDATES:
        path = repo_root / rel
        rel_norm = str(rel).replace("\\", "/")
        # ABSENT and UNREADABLE are different answers here, and collapsing
        # them is what this whole module exists to stop doing one layer down.
        # `Path.exists()` re-raises EACCES on 3.10-3.13, so it could not be used;
        # but plain `os.path.exists` swaps the raise for a silent False, which
        # on those versions REMOVED a signal -- config_guard used to log
        # "config_guard: scan failed" and went quiet. os.stat discriminates:
        # ENOENT/ENOTDIR mean genuinely absent (skip), anything else means
        # present-but-unreadable, which is exactly the state
        # `include_unreadable` exists to surface. The two BLOCKING callers
        # (write_guard, config_guard) still see nothing by default, because
        # denying every tool call over an unreadable settings file would wedge
        # the session that repairs it.
        try:
            os.stat(path)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            if include_unreadable:
                findings.append(
                    f"{rel_norm}: present but unreadable -- kill-switch scan "
                    "could not answer for this file"
                )
            continue
        data = _load_settings_json(path)
        if data is None:
            # PRESENT but unparseable is not "nothing to see" -- the same
            # absent-vs-unusable collapse the manifest sentinel above fixes,
            # in the same file. But this verdict is consumed by a HARD BLOCKER
            # (write_guard denies every tool call on any finding), and a
            # settings.json is most likely to be unparseable while someone is
            # mid-edit. Reporting it unconditionally would deny the very Edit
            # needed to repair it -- a self-inflicted lockout, strictly worse
            # than the fail-open. So reporters opt IN and blockers do not.
            if include_unreadable:
                findings.append(
                    f"{rel_norm}: unreadable settings file "
                    f"(kill-switch scan could not run)"
                )
            continue
        findings.extend(_find_kill_switches(rel_norm, data))
    return findings


def is_kill_switch_set(settings: dict) -> bool:
    """Pure bool predicate over a settings-dict (mirrors _find_kill_switches:314).

    Returns True iff settings["disableAllHooks"] is the boolean True
    (absent / explicit-false both mean "enforcement runs"). Used by
    the truth-table contract test for the kill_switch state
    field; behavioral test lives in tests/test_write_guard.py.
    """
    return settings.get("disableAllHooks") is True


# ── Audit log ───────────────────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def _make_fallback_dir() -> Path:
    """Create a unique per-process audit-log fallback directory.

    Wrapped in ``lru_cache`` so the directory is created exactly once
    per process — multiple ``_audit_dir()`` calls within one hook
    invocation share the dir.

    The directory is created via ``tempfile.mkdtemp`` (O_EXCL atomic
    create, random suffix, mode 0o700 by default), so the predictable-
    name window of a stable-path fallback is closed.
    """
    import tempfile
    p = Path(tempfile.mkdtemp(prefix=".espalier-audit-"))
    print(
        f"[WARN] espalier: HOME is unset; audit log falling back "
        f"to per-process ephemeral dir {p}. Set HOME to persist "
        f"audit entries.",
        file=sys.stderr,
    )
    return p


def _audit_dir() -> Path:
    """Return the per-user audit-log directory.

    ``Path.home()`` raises ``RuntimeError`` on POSIX when ``HOME`` is
    unset (minimal container, CI runner with stripped env); the raise
    would propagate out of ``audit_path`` (called outside the broad
    except in ``append_audit``) and crash the hook, so it falls back.

    The fallback uses ``tempfile.mkdtemp(prefix=".espalier-audit-")`` —
    a unique per-process directory created with mode 0o700 — rather than
    a stable path under ``gettempdir()``. A stable fallback could be
    pre-placed as a symlink by another user on a multi-tenant POSIX host
    with a world-writable ``/tmp``; ``mkdtemp`` uses ``O_EXCL`` and a
    random suffix, so the predictable-name window is closed entirely.
    The fallback dir is created via an ``lru_cache``-wrapped helper
    (``_make_fallback_dir``); set ``HOME`` if you need audit entries to
    persist across processes.

    Honors the ``ESPALIER_AUDIT_DIR`` env var when set, so test runs can
    redirect audit logs to a tmp dir without polluting
    ``~/.espalier/audit/``.
    """
    override = os.environ.get("ESPALIER_AUDIT_DIR")
    if override:
        candidate = Path(override)
        rejection = _validate_audit_override(candidate)
        if rejection:
            print(
                f"[_audit_dir] WARN: rejecting ESPALIER_AUDIT_DIR "
                f"override {candidate}: {rejection}",
                file=sys.stderr,
            )
        else:
            return candidate
    try:
        return Path.home() / ".espalier" / "audit"
    except RuntimeError:
        return _make_fallback_dir()


def _validate_audit_override(p: Path) -> str | None:
    """Return None if the override is safe; a rejection reason otherwise.

    ESPALIER_AUDIT_DIR is inherited from the parent shell — a
    compromised parent could set it to ``/etc/cron.d`` (or any other
    sensitive location) and cause every blocked tool call's audit JSON
    to write into that directory. Validates that the override is:

    - not a symlink (symlink targets are operator-controllable);
    - resolves under ``Path.home()`` OR ``tempfile.gettempdir()`` (the
      two legitimate locations: developer state and per-test isolation);
    - if the path exists, owned by the current user (POSIX only).

    Returns None on success, a short rejection reason on failure.
    Caller logs the rejection to stderr and falls back to defaults.
    """
    try:
        if p.is_symlink():
            return "is a symlink"
    except OSError as e:
        return f"symlink check failed: {os_error_text(e)}"
    try:
        resolved = p.resolve()
    except OSError as e:
        return f"resolve failed: {os_error_text(e)}"
    safe_roots: list[Path] = []
    try:
        safe_roots.append(Path.home().resolve())
    except (OSError, RuntimeError):
        pass
    # ``tempfile.gettempdir()`` honors $TMPDIR. An attacker-
    # controlled parent shell that sets TMPDIR to a sensitive
    # directory outside home (e.g., /etc/cron.d) would silently
    # legitimize ESPALIER_AUDIT_DIR=$TMPDIR/silent. Skip the env-
    # driven tempdir entry when TMPDIR is set; the hard-coded
    # /tmp + /var/folders fallback covers the legitimate POSIX/macOS
    # tempdir locations regardless of env.
    if not os.environ.get("TMPDIR"):
        import tempfile as _tempfile
        try:
            safe_roots.append(Path(_tempfile.gettempdir()).resolve())
        except OSError:
            pass
    for hardcoded in (Path("/tmp"), Path("/var/folders")):
        try:
            safe_roots.append(hardcoded.resolve())
        except OSError:
            pass
    under_safe_root = False
    for root in safe_roots:
        try:
            resolved.relative_to(root)
            under_safe_root = True
            break
        except ValueError:
            continue
    if not under_safe_root:
        return f"not under home or tempdir (resolved: {resolved})"
    if p.exists():
        try:
            if p.stat().st_uid != os.getuid():
                return "owned by different user"
        except (AttributeError, OSError):
            pass  # Windows: no st_uid; skip ownership check.
    return None


# Cap the prune iteration so an attacker spamming the audit dir
# with empty log files can't slow session_start to a crawl. Above the
# cap, process the lexicographically-first N and warn; that keeps
# legitimate older entries visible to pruning under flood conditions.
_MAX_PRUNE_SCAN = 5000

# Forced twin of _blueprint_limits.BLUEPRINT_COLD_DIR_NAME. A literal, not a
# sibling import: hooks run standalone and a script copied without its deps
# fails SILENTLY in its subprocess. Must not match ``base.glob("*.log")`` or
# the demotion tail would re-enter itself -- a directory name cannot.
_COLD_DIR_NAME = "_cold"


def _prune_old_audit_logs(max_age_days: int = 30) -> int:
    """Demote .log files in _audit_dir() older than max_age_days into ``_cold/``.

    Returns the count demoted. Best-effort; never raises. Capped at
    ``_MAX_PRUNE_SCAN`` files per call so a flood of spam log files
    can't slow session_start indefinitely.

    These are the harness's own enforcement record, and this ran on EVERY
    SessionStart with a 30-day window against a store measured at 4,923 files
    on 2026-08-31 — i.e. it was already at the window's edge. It unlinked until
    then. Demotion makes the irreversible half reversible; whether the cold
    store is worth backing up is a separate question and does not have to be
    answered before this stops destroying.
    """
    import time
    try:
        base = _audit_dir()
    except (OSError, RuntimeError):
        return 0
    if not base.exists():
        return 0
    cutoff = time.time() - (max_age_days * 86400)
    all_logs = sorted(base.glob("*.log"))
    if len(all_logs) > _MAX_PRUNE_SCAN:
        print(
            f"[_prune_old_audit_logs] WARN: {len(all_logs)} log files "
            f"exceeds cap {_MAX_PRUNE_SCAN}; processing first "
            f"{_MAX_PRUNE_SCAN}",
            file=sys.stderr,
        )
        scan_files = all_logs[:_MAX_PRUNE_SCAN]
    else:
        scan_files = all_logs
    deleted = 0
    cold = base / _COLD_DIR_NAME
    for f in scan_files:
        try:
            age_ts = _parse_first_log_timestamp(f)
            if age_ts is None:
                # Parse failed (empty file, corrupted JSON, no timestamp
                # field). Fall back to mtime; this is the legacy
                # behavior and still catches the common case.
                age_ts = f.stat().st_mtime
            if age_ts < cutoff:
                cold.mkdir(parents=True, exist_ok=True)
                f.replace(cold / f.name)
                deleted += 1
        except OSError:
            pass
    return deleted


def _parse_first_log_timestamp(f: Path) -> float | None:
    """Read the first JSON line of an audit log and return its
    ``timestamp`` field as a unix float. None if any step fails.

    Using the log-content timestamp rather than ``st_mtime`` prevents
    mtime tampering — ``touch -t 209901010000 <log>`` can keep a
    tampered log alive past its real cutoff if mtime is the only age
    signal.
    """
    try:
        # Bytes: the line goes to load_json_dict_safe, which decodes tolerantly
        # (a strict text read raised past the OSError handler; DEF-829).
        with f.open("rb") as fh:
            first = fh.readline()
    except OSError:
        return None
    if not first.strip():
        return None
    # A non-dict first line (e.g. `[]`) parses cleanly but would crash
    # rec.get("timestamp"); collapse it to None.
    rec = load_json_dict_safe(first, default=None)
    if rec is None:
        return None
    ts = rec.get("timestamp")
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return None


def _safe_slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "repo"


def audit_path(repo_root: Path, now: datetime | None = None) -> Path:
    now = now or datetime.now(timezone.utc)
    slug = _safe_slug(Path(repo_root).resolve().name)
    return _audit_dir() / f"{slug}-{now.strftime('%Y%m%d')}.log"


def append_audit(repo_root: Path, event: dict, *, quiet: bool = False) -> bool:
    """Append a JSON line to ~/.espalier/audit/{repo}-{YYYYMMDD}.log.

    Never raises. Returns ``True`` when the line landed. On an ``OSError``
    (an unwritable audit dir, a full disk) it returns ``False`` and warns to
    stderr -- unless ``quiet``, which the audited deny/block funnels pass:
    their stdout JSON is the protocol's channel and nothing may join it on
    stderr, so a record that cannot be written is dropped in silence there.
    Audit log is best-effort visibility, not a security mechanism.
    """
    now = datetime.now(timezone.utc)
    record = {
        "timestamp": now.isoformat(),
        "event_type": event.get("event_type", "unknown"),
        "repo_path": str(Path(repo_root).resolve()),
        "details": event.get("details", {}),
    }
    try:
        base = _audit_dir()
        base.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(base, 0o700)
        except OSError:
            pass
        log_path = audit_path(repo_root, now)
        existed = log_path.exists()  # TOCTOU: best-effort; audit log is not a security boundary
        # POSIX flock around the append. The append-mode write
        # itself is atomic at line boundaries only for writes < PIPE_BUF
        # (4096 on Linux, 512 on macOS). A record carrying a long
        # `findings` list can exceed 512 bytes; without a lock, two
        # concurrent hook events on macOS interleave their JSON into
        # one malformed line that breaks downstream `jq` parsing.
        line = json.dumps(record) + "\n"
        with log_path.open("a", encoding="utf-8") as fh:
            try:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                try:
                    fh.write(line)
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except ImportError:
                # Windows: no fcntl. Append is best-effort. Audit log is
                # documented as a visibility layer, not a security boundary.
                fh.write(line)
        if not existed:
            try:
                os.chmod(log_path, 0o600)
            except OSError:
                pass
    except OSError as e:
        if not quiet:
            _hook_utils.warn_exc("audit log write failed", e)
        return False
    return True


# Enforcement BLOCK event types, in two tiers -- the records a "what did the
# harness just block" reader (``/status --log``) surfaces. Single owner so the
# reader filter, the ``docs/HOOKS.md`` table, and the writers can't drift -- and
# since ownership alone did not stop a drift (a writer landed a type this set
# lacked, and the reader hid that denial until the gap was measured),
# ``tests/test_governance_audit_log.py`` derives the written set from the hooks
# and pins both tiers and the doc table to it in both directions.
#
# A REFUSAL (``DENIAL_EVENT_TYPES``) is a call that did not run. A PAUSE
# (``PAUSE_EVENT_TYPES``) is once-then-continue: a speed-bump fire lets the
# re-issued command proceed, and a Stop-gate block is let through by the
# protocol's loop signal on the next Stop -- so on a busy day their records can
# outnumber the rare refusal inside a window of twenty. The reader tails the
# refusals by default, counts the day's pauses on their own line so the window
# cannot lose one without a trace, and widens the tail to them under ``--all``.
#
# The audit log ALSO carries advisory records (``action_justification_missing``
# fires on every un-justified write, ``post_write_integrity_drift``,
# ``session_*``); those are in neither tier so blocks aren't buried under noise.
#
# A crash guard's block sits in the tier of the hook it guards (DEF-803): the
# PreToolUse and ConfigChange ones refuse the call; the Stop one is a pause
# because the loop signal lets the continuation's Stop through -- a crash
# that persists re-blocks on the first Stop of every later turn until its
# cause is fixed, and the default view counts those on the pause line. The
# PreToolUse hooks share one type, so ``details.hook`` names which;
# ``details.error`` is the exception's class, never its message. A wedged
# PreToolUse hook writes one refusal per denied call, so the tail fills with
# them; the day-wide by-type line above it is where every other type's count
# survives.
DENIAL_EVENT_TYPES = frozenset({
    "pretooluse_blocked_protected_zone",
    "pretooluse_blocked_dangerous_command",
    "pretooluse_blocked_no_active_plan",
    "pretooluse_blocked_kill_switch",
    "pretooluse_blocked_secret_path",
    "pretooluse_blocked_internal_error",
    "configchange_blocked_kill_switch",
    "configchange_blocked_internal_error",
})

PAUSE_EVENT_TYPES = frozenset({
    "pretooluse_blocked_speed_bump",
    "stop_blocked_pytest",
    "stop_blocked_docs_refresh",
    "stop_blocked_code_review",
    "stop_blocked_internal_error",
})

BLOCKED_EVENT_TYPES = DENIAL_EVENT_TYPES | PAUSE_EVENT_TYPES

#: The advisory records a hook writes ONCE per session when
#: ``ESPALIER_MAINTENANCE_MODE`` switches one of its checks off (DEF-789):
#: ``write_guard`` (the protected-zone check) and ``plan_guard`` (the plan
#: requirement) write the PreToolUse type with ``details.hook`` naming which;
#: ``stop_gate`` (Gates 2 and 3) writes the Stop type. Neither a refusal nor a
#: pause -- nothing was blocked -- so they are in neither tier and never in the
#: tail; the reader counts them on their own line so a day on which the
#: anti-self-disable floor was bypassed cannot read as a clean one. Each writer
#: spells its literal itself (the ledger probe and the audit-log tests read the
#: literal reaching the writer); ``tests/test_governance_audit_log.py`` pins the
#: written set and this set equal. ``subagent_stop``'s maintenance skip is a
#: consequence of the Stop gates' and records nothing.
MAINTENANCE_BYPASS_EVENT_TYPES = frozenset({
    "pretooluse_bypassed_maintenance_mode",
    "stop_bypassed_maintenance_mode",
})
#: One guard flag per hook, ``<prefix><hook>``, under STATE_DIR: the record is
#: once per session per hook, and session_start clears the family by glob.
MAINTENANCE_BYPASS_FLAG_PREFIX = "maintenance_bypass_recorded_"


def maintenance_bypass_recorded(repo_root: Path, hook: str) -> bool:
    """Has ``hook`` already recorded its maintenance bypass this session?"""
    flag = Path(repo_root) / _hook_utils.STATE_DIR / f"{MAINTENANCE_BYPASS_FLAG_PREFIX}{hook}"
    return flag.exists()


def mark_maintenance_bypass_recorded(repo_root: Path, hook: str) -> None:
    """Set the once-per-session guard AFTER the record is written, so a failed
    flag write yields a duplicate record on the next fire, never a silent
    session. Best-effort: a reporter on an allow path never raises."""
    try:
        flag = Path(repo_root) / _hook_utils.STATE_DIR / f"{MAINTENANCE_BYPASS_FLAG_PREFIX}{hook}"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("", encoding="utf-8")
    except OSError:
        pass


def tail_audit(
    repo_root: Path,
    n: "int | None" = 20,
    event_types: "frozenset[str] | set[str] | None" = None,
) -> list[str]:
    """Return the last ``n`` records of THIS repo's audit log for today
    (``[]`` if none); ``n=None`` returns every matching record. Read-only
    companion to ``append_audit`` — reuses ``audit_path`` so the resolution
    (``ESPALIER_AUDIT_DIR`` override, repo slug, date) can never drift from
    the writer's.

    The log file is keyed by the repo's BASENAME, so two checkouts named
    ``myrepo`` (a worktree, a scratch clone) share one file. Every record
    carries the writer's resolved ``repo_path`` for exactly that reason, and
    the reader keeps only the records whose ``repo_path`` is this root. A line
    that is not a JSON object, or has no ``repo_path``, cannot be attributed
    and is dropped.

    If ``event_types`` is given (e.g. ``DENIAL_EVENT_TYPES``), records whose
    ``event_type`` is outside the set are dropped too. Both filters run BEFORE
    the last-``n`` slice, so ``--log 20`` shows the last 20 *matching* records
    — not 20 that may all be another checkout's, or advisory noise.
    ``n <= 0`` yields ``[]`` (last 0 = nothing).

    Best-effort: any read error yields ``[]`` (a visibility convenience must
    never raise). ``errors="replace"`` decodes a partial/interleaved multi-byte
    line (the lock-free Windows append ``append_audit`` documents) into a
    visible replacement character rather than raising ``UnicodeDecodeError``
    and dropping the whole tail; such a line then fails the JSON parse and is
    dropped like any other unattributable line."""
    try:
        path = audit_path(repo_root)
        if not path.exists():
            return []
        this_repo = os.path.normcase(str(Path(repo_root).resolve()))
        text = path.read_text(encoding="utf-8", errors="replace")
        kept: list[str] = []
        for ln in text.splitlines():
            if not ln.strip():
                continue
            try:
                rec = json.loads(ln)
            except ValueError:  # JSONDecodeError subclass -- skip corrupt line
                continue
            if not isinstance(rec, dict):
                continue
            if os.path.normcase(str(rec.get("repo_path", ""))) != this_repo:
                continue
            if event_types is not None and rec.get("event_type") not in event_types:
                continue
            kept.append(ln)
        if n is None:
            return kept
        return kept[-n:] if n > 0 else []
    except OSError:
        return []


# ── Convenience for CLI / session_start ─────────────────────────────────────


def summarize_state(repo_root: Path) -> dict:
    """Run both checks and return a structured summary."""
    ok, mismatched = verify_integrity(repo_root)
    findings = scan_for_kill_switches(repo_root)
    return {
        "integrity_ok": ok,
        "mismatched_paths": mismatched,
        "kill_switches": findings,
    }
