#!/usr/bin/env python3
"""Born-weak co-occurrence OBSERVER for post_write_check.

Mirrors how ``write_guard.py`` factors ``_bash_patterns`` /
``_protected_zones`` / ``_speedbump`` / ``_reinject`` into co-located sibling
helpers. Stdlib + git-subprocess only, one sibling import (``_hook_utils`` for
``STATE_DIR``) -- the ``tools/cc/`` zero-espalier-import standalone contract is
preserved.

OBSERVE-ONLY. Never blocks, never denies, never nudges -- it COUNTS. The behavior
is moved here byte-for-byte from post_write_check (no predicate change).
``post_write_check`` re-exports ``_BW_LOG_NAME`` / ``observe_born_weak`` /
``bw_log_observation`` / ``_observe_born_weak`` / ``_bw_is_guard_material`` /
``_bw_count_exempt_entries`` so ``tests/test_born_weak_observer.py`` (which
imports ``post_write_check as p``) keeps resolving ``p.<symbol>`` unchanged.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

# Co-located helper module -- same zero-espalier-import pattern as other hooks.
import sys
sys.path.insert(0, str(Path(__file__).parent))
import _hook_utils  # noqa: E402


# ---------------------------------------------------------------------------
# Born-weak co-occurrence OBSERVER (autoimmune-regression instrument).
#
# OBSERVE-ONLY. Never blocks, never denies, never nudges -- it COUNTS. Its one
# job is to COUNT co-occurrences toward a future base rate (the numerator only --
# total guard-material writes, the denominator, are not logged in v1): how often
# does a change add a guard/scanner/test AND a same-material suppression
# *together*, WITHOUT a paired must-NOT-trip negative fixture -- the "born-weak"
# fingerprint (autoimmune regression, Harm B:
# a guard born blind, green-but-never-catching). That frequency is currently
# UNMEASURED (zero recorded instances in git history), so the workflow-partner
# frame (FP/friction outrank closing bypass classes) says: instrument first,
# never enforce on an unmeasured magnitude. The abandon-vs-revive decision for
# any *enforcing* form is deferred to this data -- see
# docs/RELEASE_FINDINGS_LEDGER.md §C.4 and docs/FAILURE_MODES.md.
#
# Self-host-gated: it counts toward the HARNESS'S OWN born-weak rate (the question
# is "does Espalier's own guard-development produce born-weak guards?"); adopter
# repos are noise for that and stay untouched. It diffs the written file against
# ``git show HEAD:<path>`` (not the PreToolUse old_string, which post_write_check
# does not carry) -- diffing vs HEAD also makes within-file co-occurrence
# accumulate across edits in a session. v1 scope = WITHIN-FILE co-occurrence (the
# dominant Espalier vector); cross-FILE co-occurrence is a documented v1 gap.
# Recursive-risk: this observer is itself a guard, so it ships a paired
# earn-the-red + must-NOT-trip negative (tests/test_born_weak_observer.py).
# ---------------------------------------------------------------------------
_BW_LOG_NAME = "born_weak_observations.jsonl"
_BW_SCANNER_RE = re.compile(r"(?:^|/)espalier/scanners/[^/]+\.py$")
_BW_CHECK_SCRIPT_RE = re.compile(r"(?:^|/)scripts/check_[^/]+\.py$")
_BW_TEST_RE = re.compile(r"(?:^|/)tests/(?:[^/]+/)*test_[^/]+\.py$")
# NB: no literal "return 2" OR "sys.exit(2)" token -- either collides with the
# check_hook_protocol_correct grep (\breturn\s+2\b / \bsys\.exit\(\s*2\s*\)) since
# post_write_check is a non-underscore hook it scans (an autoimmune collision,
# §1.13). The five tokens below detect a deny-path addition without tripping it.
# sister-site: ok purpose-scoped: deliberately OMITS return-2/exit-2 (autoimmune §1.13 — born_weak runs inside a scanned non-_ hook)
_BW_DENY_TOKENS = ("return deny", "deny(", "return block", "block(", "permissionDecision")
_BW_DEF_TEST_RE = re.compile(r"^\s*def test_\w", re.MULTILINE)
_BW_FINDING_TOKENS = ("findings.append", "yield Finding", "re.compile(")
_BW_SKIP_TOKENS = ("mark.skip", "mark.xfail", "pytest.skip(", "unittest.skip", "@skip")
_BW_PRAGMA_TOKENS = ("# noqa", "# type: ignore")
# Matches BOTH the bare `EXEMPT_X = (...)` and the ANNOTATED forms every real
# scanner uses -- `EXEMPT_X: tuple[str, ...] = (...)` and
# `EXEMPT_X: frozenset[str] = frozenset({...})`. `[^=\n]*` swallows the type
# annotation up to `=` (stays on the assignment line); the optional `frozenset(`
# unwraps the frozenset value. ReDoS-safe: negated classes only, no bare dot.
# Matching ONLY the bare form would leave the signal dead against the live
# convention (the observer's own born-weak collision).
_BW_EXEMPT_ASSIGN_RE = re.compile(
    r"EXEMPT_[A-Z_]*[^=\n]*=\s*(?:frozenset\s*\()?\s*[\(\[{]([^)\]}]*)[\)\]}]")
_BW_QUOTED_RE = re.compile(r'"[^"]*"' + r"|'[^']*'")
_BW_ASSERT_RE = re.compile(r"^\s*assert\b", re.MULTILINE)


def _bw_is_guard_material(rel_path: str) -> bool:
    """True if the path is a scanner / check-script / test / guard-hook file."""
    p = (rel_path or "").replace("\\", "/")
    # Invariant #1 (own your trigger; never scan your own DEFINING material): the
    # scanner fixture corpus (subject-data) and the observer's OWN test both carry
    # born-weak example tokens (findings.append / EXEMPT_* / def test_), so
    # observing them self-collides (Harm A -- a guard firing on the material that
    # defines its pattern; the exact §1.13 mode). Exempt them, like the scanners
    # exempt tests/fixtures/.
    if "tests/fixtures/" in p or p.endswith("tests/test_born_weak_observer.py"):
        return False
    if _BW_SCANNER_RE.search(p) or _BW_CHECK_SCRIPT_RE.search(p) or _BW_TEST_RE.search(p):
        return True
    # DERIVED, not enumerated. This was a five-name tuple -- write_guard,
    # plan_guard, config_guard, stop_gate, _speedbump -- and the two files it
    # omitted were THIS FILE and its host, post_write_check.py. So the one
    # instrument in the repo whose declared subject is "a guard born blind"
    # (Harm B, §1.13) defined its own population to exclude itself: across 215
    # recorded observations, no edit to the observer was ever eligible for
    # observation. That is the shape it exists to catch, committed in the
    # instrument built to catch it.
    #
    # Safe against the SIBLING harm (Harm A, a guard firing on its own defining
    # material) because `_bw_guard_signals` is a COUNT DELTA -- `new.count(t) >
    # old.count(t)`. This file carries the deny/finding tokens as string
    # literals, but mere presence cannot fire the signal; only an edit that
    # ADDS one does, and an edit that adds a deny path to the observer is
    # genuine guard development that belongs in the record. The two Invariant
    # #1 exemptions above (fixture corpus, the observer's own test) still stand:
    # those DO self-collide, because their content is the pattern definition.
    return "tools/cc/hooks/" in p and p.endswith(".py")


def _bw_count_exempt_entries(text: str) -> int:
    """Count NON-fixture exemption entries. The standard ``tests/fixtures/``
    quarantine is the MANDATED, born-RIGHT convention (SHARP_EDGES: every scanner
    ships it), so it is excluded -- only a BROAD carve-out (a source dir, a
    specific file excused) is the born-weak suppression vector."""
    n = 0
    for m in _BW_EXEMPT_ASSIGN_RE.finditer(text):
        for q in _BW_QUOTED_RE.findall(m.group(1)):
            inner = q[1:-1]
            if inner and not inner.startswith("tests/fixtures/"):
                n += 1
    return n


def _bw_guard_signals(old: str, new: str, *, is_new_file: bool, rel_path: str) -> list[str]:
    """The 'guard born / grown' half: a detection surface appeared or strengthened."""
    sigs: list[str] = []
    if is_new_file and (_BW_SCANNER_RE.search(rel_path) or _BW_CHECK_SCRIPT_RE.search(rel_path)):
        sigs.append("scanner_or_gate_born")
    if len(_BW_DEF_TEST_RE.findall(new)) > len(_BW_DEF_TEST_RE.findall(old)):
        sigs.append("test_function_born")
    if any(new.count(t) > old.count(t) for t in _BW_DENY_TOKENS):
        sigs.append("deny_path_added")
    if any(new.count(t) > old.count(t) for t in _BW_FINDING_TOKENS):
        sigs.append("scanner_rule_added")
    return sigs


def _bw_suppression_signals(old: str, new: str) -> list[str]:
    """The 'same-material suppression added' half."""
    sigs: list[str] = []
    if any(new.count(t) > old.count(t) for t in _BW_SKIP_TOKENS):
        sigs.append("skip_or_xfail_added")
    if any(new.count(t) > old.count(t) for t in _BW_PRAGMA_TOKENS):
        sigs.append("lint_pragma_added")
    if _bw_count_exempt_entries(new) > _bw_count_exempt_entries(old):
        sigs.append("exempt_list_grew")
    if len(_BW_ASSERT_RE.findall(new)) < len(_BW_ASSERT_RE.findall(old)):
        sigs.append("assertion_removed")
    return sigs


def _bw_paired_mitigant(old: str, new: str) -> bool:
    """The BLESSED pattern: suppression shipped WITH a paired negative fixture
    (proving the guard still fires on a non-exempt twin) or a reasoned skip.
    Then the co-occurrence is born-RIGHT, not born-weak -- do not record it.

    NB: this is a bare-substring test (an incidental ``reason=`` kwarg or a
    ``_negatives`` mention in a comment also mitigates), so the logged count is a
    LOWER BOUND on the true within-file Harm-B rate -- conservative by design
    (an observe-only instrument should under-count, never false-alarm). Do not
    read 'zero observations' as a tight measurement, and do not tighten this
    predicate before the base rate justifies the added false-positive risk."""
    return (
        new.count("_negatives") > old.count("_negatives")
        or new.count("_positives") > old.count("_positives")
        or new.count("reason=") > old.count("reason=")
    )


def observe_born_weak(rel_path: str, *, old_content: str, new_content: str) -> dict | None:
    """Pure detection core (no I/O, no git, no clock -- the unit-test seam).
    Returns an observation record if the within-file diff shows a born-weak
    co-occurrence, else None."""
    rel_path = (rel_path or "").replace("\\", "/")
    if not _bw_is_guard_material(rel_path):
        return None
    guard = _bw_guard_signals(old_content, new_content, is_new_file=(old_content == ""), rel_path=rel_path)
    if not guard:
        return None
    supp = _bw_suppression_signals(old_content, new_content)
    if not supp:
        return None
    if _bw_paired_mitigant(old_content, new_content):
        return None
    return {
        "path": rel_path,
        "guard_signals": guard,
        "suppression_signals": supp,
        "co_occurrence": True,
        "scope": "within_file_v1",
    }


def _bw_git_head(root: Path, rel_path: str) -> str:
    """The HEAD version of the file, or '' if absent/new/unavailable."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{rel_path}"],
            # errors="replace" mirrors the new-content read below — the
            # HEAD blob can hold non-UTF-8 bytes; degrade them rather than drop
            # the born-weak observation on a UnicodeDecodeError.
            cwd=str(root), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def bw_log_observation(root: Path, record: dict, *, now: datetime | None = None) -> None:
    """Append one timestamped record to the gitignored observation log.

    The append is serialized under an ``fcntl.flock`` on a STABLE
    sibling lock file (mirrors ``_hook_utils._locked_increment``). Two concurrent
    PostToolUse hooks — a parent repo + a git worktree sharing one
    ``.espalier-state`` — could otherwise interleave a >512-byte record (the
    ``rel_path`` field is unbounded) into one malformed JSONL line, the exact
    hazard the flock-protected counter sibling already defends against. Degrades
    to a best-effort unlocked append on Windows (no ``fcntl``) or a flock-less FS
    (some NFS mounts): an observe-only instrument may garble a record under that
    rare race but must never crash the non-blocking hook.
    """
    stamped = dict(record)
    stamped["ts"] = (now or datetime.now(timezone.utc)).isoformat()
    state = root / _hook_utils.STATE_DIR
    state.mkdir(parents=True, exist_ok=True)
    line = json.dumps(stamped, ensure_ascii=True, sort_keys=True) + "\n"
    log_path = state / _BW_LOG_NAME

    def _append() -> None:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    try:
        import fcntl  # POSIX only
    except ImportError:
        _append()  # Windows: best-effort unlocked append (documented limit)
        return
    lock_path = state / (_BW_LOG_NAME + ".lock")
    # Acquire the lock in its OWN try so the unlocked fallback fires ONLY when
    # lock acquisition fails (flock-less FS / unwritable lock) — never as a
    # retry of a mid-write append. _hook_utils._locked_increment's fallback is
    # safe because it RE-READS (idempotent); a re-WRITE here would double-append
    # a torn record on a partial-write OSError, the exact hazard this guards.
    lock_fh = None
    try:
        lock_fh = open(lock_path, "a+", encoding="utf-8")
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
    except OSError:
        # flock-less FS (flock raised after open) / unwritable lock (open raised)
        # — close the fd if it opened (no leak), then unlocked best-effort append.
        if lock_fh is not None:
            lock_fh.close()
        _append()
        return
    try:
        _append()  # a mid-write OSError propagates ONCE (caller umbrella swallows it).
    finally:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        finally:
            lock_fh.close()


def _observe_born_weak(root: Path, rel_path: str, *, base: Path | None = None) -> dict | None:
    """Hook-path orchestrator: diff the written path vs HEAD and log any
    co-occurrence. Best-effort -- never perturbs the non-blocking hook.

    ``base`` is the checkout the write landed in -- the root, or a registered
    worktree of it (DEF-743; ``_hook_utils.resolve_in_checkout``) -- and is
    where the bytes and their HEAD are read; the observation log stays at
    ``root``. ``None`` means the root."""
    checkout = root if base is None else base
    try:
        if not _bw_is_guard_material(rel_path):
            return None
        # Containment: the observer runs BEFORE post_write_check's _is_harness_file
        # gate, so it must reject out-of-repo escapes itself (absolute / parent-
        # relative / ``..`` segment) -- else ``root / rel_path`` reads file content
        # outside the project and pollutes the count with an out-of-boundary path
        # (BC: path traversal, a documented failure class).
        # is_absolute()/.drive catch a Windows drive-letter absolute
        # (``C:\...`` / ``C:/...``) or drive-relative (``C:x``) that
        # startswith("/") misses -- else the containment check leaks and
        # ``root / rel_path`` reads out-of-repo content on Windows. Both are
        # no-ops on POSIX (is_absolute() ⟺ startswith("/"); .drive is "").
        p = Path(rel_path)
        if (
            rel_path.startswith(("/", "../"))
            or ".." in p.parts
            or p.is_absolute()
            or p.drive
        ):
            return None
        try:
            new = (checkout / rel_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        record = observe_born_weak(rel_path, old_content=_bw_git_head(checkout, rel_path), new_content=new)
        if record is not None:
            bw_log_observation(root, record)
        return record
    except Exception:  # noqa: BLE001 -- observer must never perturb the hook
        return None
